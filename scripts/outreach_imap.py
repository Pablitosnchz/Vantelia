"""IMAP poller para autodeteccion de respuestas en captacion outbound.

Lee la bandeja de entrada IMAP, identifica respuestas a emails de campanas
(matching de In-Reply-To / References con sends.message_id) y:

  1. Registra evento `reply` en outreach.db.
  2. Marca el prospect con status='replied'.
  3. Cancela futuros stages (fu1, fu2, breakup) para ese prospect.

Diseno:
  - Idempotente: marca cada email procesado con flag IMAP \\Seen + memoria
    en tabla `imap_seen` por Message-Id para no reprocesar.
  - Solo lee; no borra ni mueve mensajes salvo marcar como leido.
  - Filtra autoresponders (Auto-Submitted, X-Autoreply) para no contar
    como respuesta humana.
  - Background safe: pensado para ejecutarse cada N minutos desde un thread
    en api.py (similar al motor de recordatorios).

Variables de entorno:
  IMAP_HOST, IMAP_PORT (default 993), IMAP_USER, IMAP_PASSWORD
  IMAP_FOLDER             (default INBOX)
  IMAP_USE_SSL            (default true)
  OUTREACH_IMAP_LOOKBACK_DAYS (default 14)
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


IMAP_SEEN_SCHEMA = """
CREATE TABLE IF NOT EXISTS imap_seen (
    message_id TEXT PRIMARY KEY,
    email      TEXT DEFAULT '',
    stage      TEXT DEFAULT '',
    seen_at    TEXT NOT NULL
);
"""

AUTOREPLY_HEADERS = (
    "Auto-Submitted",
    "X-Autoreply",
    "X-Autorespond",
    "X-Auto-Response-Suppress",
)
AUTOREPLY_VALUES_BAD = ("auto-replied", "auto-generated", "yes")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(IMAP_SEEN_SCHEMA)
    conn.commit()


def _is_autoreply(msg: Message) -> bool:
    for hdr in AUTOREPLY_HEADERS:
        val = (msg.get(hdr, "") or "").strip().lower()
        if not val:
            continue
        if any(bad in val for bad in AUTOREPLY_VALUES_BAD):
            return True
    subject = (msg.get("Subject", "") or "").lower()
    if subject.startswith(("out of office", "fuera de la oficina", "ausencia automatic")):
        return True
    return False


def _extract_msgid_refs(msg: Message) -> list[str]:
    refs: list[str] = []
    for header in ("In-Reply-To", "References"):
        raw = msg.get(header, "") or ""
        for match in re.findall(r"<[^<>]+>", raw):
            refs.append(match.strip())
    return refs


def _from_email(msg: Message) -> str:
    addrs = getaddresses([msg.get("From", "") or ""])
    if not addrs:
        return ""
    return (addrs[0][1] or "").strip().lower()


def _received_at(msg: Message) -> str:
    raw = msg.get("Date", "")
    if not raw:
        return _now_iso()
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return _now_iso()


def _connect_imap() -> imaplib.IMAP4 | None:
    host = os.getenv("IMAP_HOST", "").strip()
    user = os.getenv("IMAP_USER", "").strip()
    password = os.getenv("IMAP_PASSWORD", "").strip()
    if not host or not user or not password:
        return None
    port = int(os.getenv("IMAP_PORT", "993"))
    use_ssl = os.getenv("IMAP_USE_SSL", "true").strip().lower() in {"1", "true", "yes", "on"}
    folder = os.getenv("IMAP_FOLDER", "INBOX").strip() or "INBOX"
    try:
        if use_ssl:
            client: imaplib.IMAP4 = imaplib.IMAP4_SSL(host, port, timeout=25)
        else:
            client = imaplib.IMAP4(host, port, timeout=25)
        client.login(user, password)
        client.select(folder)
        return client
    except Exception as exc:  # noqa: BLE001
        logger.warning("IMAP poller: no se pudo conectar (%s)", exc)
        return None


def _search_recent_uids(client: imaplib.IMAP4, lookback_days: int) -> list[bytes]:
    since_dt = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    since_str = since_dt.strftime("%d-%b-%Y")
    try:
        typ, data = client.search(None, "(SINCE %s)" % since_str)
    except Exception as exc:  # noqa: BLE001
        logger.warning("IMAP poller: search fallo (%s)", exc)
        return []
    if typ != "OK" or not data or not data[0]:
        return []
    return data[0].split()


def _fetch_message(client: imaplib.IMAP4, uid: bytes) -> Message | None:
    try:
        typ, data = client.fetch(uid, "(RFC822)")
    except Exception as exc:  # noqa: BLE001
        logger.debug("IMAP fetch fallo uid=%s err=%s", uid, exc)
        return None
    if typ != "OK" or not data or not data[0]:
        return None
    raw = data[0][1] if isinstance(data[0], tuple) else None
    if not raw:
        return None
    try:
        return email.message_from_bytes(raw)
    except Exception:
        return None


def _matches_outreach(
    conn: sqlite3.Connection, refs: Iterable[str], from_email: str,
) -> tuple[str, str, int] | None:
    """Devuelve (prospect_email, stage, send_id) si el mensaje es respuesta a un envio.

    Estrategia:
      1. Buscar Message-Id en sends.
      2. Si no hay match por id, comprobar si el remitente es un prospect conocido
         con envio reciente (ultimos 60 dias).
    """
    refs_clean = [r for r in refs if r]
    for ref in refs_clean:
        row = conn.execute(
            "SELECT email, stage, id FROM sends WHERE message_id = ? ORDER BY id DESC LIMIT 1",
            (ref,),
        ).fetchone()
        if row:
            return row["email"], row["stage"] or "", int(row["id"])

    if from_email:
        row = conn.execute(
            """SELECT email, stage, id FROM sends
               WHERE email = ? AND mode = 'send'
               AND sent_at >= datetime('now', '-60 days')
               ORDER BY id DESC LIMIT 1""",
            (from_email,),
        ).fetchone()
        if row:
            return row["email"], row["stage"] or "", int(row["id"])
    return None


def _record_reply(
    conn: sqlite3.Connection,
    prospect_email: str,
    stage: str,
    received_at: str,
    msg_id: str,
) -> bool:
    """Registra evento reply, marca prospect como replied. Devuelve True si era nuevo."""
    existing = conn.execute(
        "SELECT 1 FROM events WHERE email = ? AND type = 'reply' AND ts = ?",
        (prospect_email, received_at),
    ).fetchone()
    if existing:
        return False

    conn.execute(
        "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?, 'reply', ?, ?, ?, '', '')",
        (prospect_email, stage, msg_id, received_at),
    )
    try:
        conn.execute(
            "UPDATE prospects SET status = 'replied', updated_at = ? WHERE email = ?",
            (_now_iso(), prospect_email),
        )
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            """UPDATE campaign_members SET status = 'replied', skip_reason = 'auto-reply-detected',
                                          updated_at = ? WHERE email = ?""",
            (_now_iso(), prospect_email),
        )
    except sqlite3.OperationalError:
        pass
    return True


def poll_once(db_path: Path) -> dict:
    """Ejecuta una ronda del poller. Pensado para llamar desde un scheduler.

    Devuelve dict con metricas. No lanza excepciones por error de red/IMAP.
    """
    stats = {"checked": 0, "matched": 0, "replies_new": 0, "skipped": 0, "errors": 0}

    if not os.getenv("IMAP_HOST", "").strip():
        return stats

    client = _connect_imap()
    if not client:
        stats["errors"] += 1
        return stats

    try:
        lookback = int(os.getenv("OUTREACH_IMAP_LOOKBACK_DAYS", "14"))
        uids = _search_recent_uids(client, lookback)
        if not uids:
            return stats

        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_schema(conn)

            for uid in uids:
                msg = _fetch_message(client, uid)
                if msg is None:
                    stats["errors"] += 1
                    continue
                stats["checked"] += 1

                msg_id = (msg.get("Message-Id") or msg.get("Message-ID") or "").strip()
                if msg_id:
                    seen = conn.execute(
                        "SELECT 1 FROM imap_seen WHERE message_id = ?", (msg_id,)
                    ).fetchone()
                    if seen:
                        stats["skipped"] += 1
                        continue

                if _is_autoreply(msg):
                    if msg_id:
                        conn.execute(
                            "INSERT OR IGNORE INTO imap_seen (message_id, email, stage, seen_at) VALUES (?, '', 'autoreply', ?)",
                            (msg_id, _now_iso()),
                        )
                    stats["skipped"] += 1
                    continue

                from_email = _from_email(msg)
                refs = _extract_msgid_refs(msg)
                match = _matches_outreach(conn, refs, from_email)
                if not match:
                    if msg_id:
                        conn.execute(
                            "INSERT OR IGNORE INTO imap_seen (message_id, email, stage, seen_at) VALUES (?, '', 'no-match', ?)",
                            (msg_id, _now_iso()),
                        )
                    continue

                prospect_email, stage, _send_id = match
                received = _received_at(msg)
                created = _record_reply(conn, prospect_email, stage, received, msg_id or "")
                stats["matched"] += 1
                if created:
                    stats["replies_new"] += 1

                if msg_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO imap_seen (message_id, email, stage, seen_at) VALUES (?, ?, ?, ?)",
                        (msg_id, prospect_email, stage, _now_iso()),
                    )
            conn.commit()
    finally:
        try:
            client.logout()
        except Exception:
            pass

    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from dotenv import load_dotenv

    BASE_DIR = Path(__file__).resolve().parent.parent
    load_dotenv(BASE_DIR / ".env")
    db = Path(os.getenv("OUTREACH_DB_PATH", str(BASE_DIR / "storage" / "outreach" / "outreach.db")))
    print("IMAP poll", poll_once(db))
