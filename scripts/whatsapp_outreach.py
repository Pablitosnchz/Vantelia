"""WhatsApp outreach — capa de datos.

Coge telefonos de los prospects de Captacion (outreach.db, modulo email) y
gestiona una cola de envios por WhatsApp con dedup por telefono. NO hace
discovery propio (no Google Places): reutiliza los negocios ya descubiertos.

Envio single-touch: un unico mensaje por telefono, nunca se repite.

DB en storage/whatsapp/whatsapp.db (env WA_DB_PATH).
Lee outreach.db en storage/outreach/outreach.db (env OUTREACH_DB_PATH).

Tablas:
    wa_messages   un registro por telefono normalizado (PK). Estado del envio.
    wa_settings   clave/valor (plantilla del mensaje, etc).
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DB = Path(os.getenv("WA_DB_PATH", "storage/whatsapp/whatsapp.db"))
OUTREACH_DB = Path(os.getenv("OUTREACH_DB_PATH", "storage/outreach/outreach.db"))

DEFAULT_MESSAGE = (
    "Hola, soy Pablo de Vantelia.\n\n"
    "He estado mirando tu negocio esta mañana y queria escribirte directamente, "
    "sin guion ni nada.\n\n"
    "Lo que hago es esto: un asistente IA por chat, whatsapp o llamada que contesta "
    "los DMs y consultas de la web por vosotros (suena como una persona, no como bot) "
    "y agenda las citas. Pensado para que no se os escape ningun cliente por no "
    "contestar a tiempo, sobre todo fuera de horario.\n\n"
    "Para que veas el tiempo que realmente os puede ahorrar, avisame y te preparo una "
    "minidemo para que pruebes. Si no os encaja, te dejo tranquilo. Sin compromiso."
)

# Placeholders sustituibles en la plantilla.
PLACEHOLDERS_HELP = "Placeholders: {business_name}, {city}, {niche}. Usa saltos de linea normales."


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Telefonos
# --------------------------------------------------------------------------

def normalize_phone(raw: str, default_cc: str = "34") -> str:
    """Normaliza a digitos E.164 sin '+'. Devuelve '' si no es valido.

    - Quita espacios, guiones, parentesis, puntos.
    - '00xx...' -> 'xx...'.
    - Si no trae prefijo de pais y son 9 digitos (movil/fijo ES), antepone default_cc.
    - Acepta solo numeros de 8 a 15 digitos.
    """
    if not raw:
        return ""
    s = str(raw).strip()
    has_plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
        has_plus = True
    # Numero nacional ES de 9 digitos sin prefijo -> anteponer 34.
    if not has_plus and len(digits) == 9 and digits[0] in "6789":
        digits = default_cc + digits
    # Caso '34' duplicado raro: 3434...
    if digits.startswith(default_cc + default_cc):
        digits = digits[len(default_cc):]
    if len(digits) < 8 or len(digits) > 15:
        return ""
    return digits


# --------------------------------------------------------------------------
# Conexion / esquema
# --------------------------------------------------------------------------

def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target = Path(db_path) if db_path else DEFAULT_DB
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=8000")
    except Exception:
        pass
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wa_messages (
            phone           TEXT PRIMARY KEY,
            prospect_email  TEXT DEFAULT '',
            business_name   TEXT DEFAULT '',
            niche           TEXT DEFAULT '',
            city            TEXT DEFAULT '',
            message_text    TEXT DEFAULT '',
            mode            TEXT NOT NULL DEFAULT 'queued',
            skip_reason     TEXT DEFAULT '',
            created_at      TEXT NOT NULL,
            sent_at         TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wa_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )
    conn.commit()


# --------------------------------------------------------------------------
# Plantilla del mensaje
# --------------------------------------------------------------------------

def get_message_template(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM wa_settings WHERE key='message_template'").fetchone()
    if row and (row["value"] or "").strip():
        return row["value"]
    return DEFAULT_MESSAGE


def set_message_template(conn: sqlite3.Connection, text: str) -> None:
    body = (text or "").strip()
    if not body:
        conn.execute("DELETE FROM wa_settings WHERE key='message_template'")
    else:
        conn.execute(
            """INSERT INTO wa_settings (key, value) VALUES ('message_template', ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (body,),
        )
    refresh_queued_messages(conn)
    conn.commit()


def render_message(template: str, business_name: str = "", niche: str = "", city: str = "") -> str:
    name = (business_name or "").strip()
    return (template
            .replace("{business_name}", name or "vosotros")
            .replace("{niche}", (niche or "").strip() or "negocio")
            .replace("{city}", (city or "").strip()))


def refresh_queued_messages(conn: sqlite3.Connection) -> int:
    """Re-renderiza los mensajes pendientes con la plantilla actual."""
    template = get_message_template(conn)
    rows = conn.execute(
        "SELECT phone, business_name, niche, city FROM wa_messages WHERE mode='queued'"
    ).fetchall()
    for r in rows:
        conn.execute(
            "UPDATE wa_messages SET message_text=? WHERE phone=? AND mode='queued'",
            (render_message(template, r["business_name"], r["niche"], r["city"]), r["phone"]),
        )
    return len(rows)


# --------------------------------------------------------------------------
# Fuente de telefonos: prospects de Captacion (outreach.db)
# --------------------------------------------------------------------------

def _outreach_path() -> Path:
    return Path(os.getenv("OUTREACH_DB_PATH", str(OUTREACH_DB)))


def fetch_prospect_phones(conn: sqlite3.Connection, limit: int) -> List[Dict[str, Any]]:
    """Devuelve hasta `limit` negocios con telefono valido aun NO contactados por WA.

    Lee prospects de outreach.db. Excluye telefonos ya en wa_messages (cualquier
    estado salvo los que fallaron por numero invalido) y prospects en lista de baja.
    """
    out_path = _outreach_path()
    if not out_path.exists():
        return []

    # Telefonos ya gestionados (no re-encolar): cualquiera ya en wa_messages.
    # Los 'queued'/'sending' se reintentan por fetch_queued, no re-encolando.
    already = {
        r["phone"]
        for r in conn.execute(
            "SELECT phone FROM wa_messages WHERE mode IN ('sent','queued','sending','skipped')"
        ).fetchall()
    }

    candidates: List[Dict[str, Any]] = []
    with closing(sqlite3.connect(str(out_path))) as oc:
        oc.row_factory = sqlite3.Row
        # Bajas/suprimidos del modulo outreach.
        suppressed_emails = set()
        try:
            suppressed_emails = {
                (r["email"] or "").lower()
                for r in oc.execute("SELECT email FROM suppressions").fetchall()
            }
        except Exception:
            suppressed_emails = set()
        try:
            rows = oc.execute(
                """SELECT email, business_name, phone, niche, city, status
                   FROM prospects
                   WHERE phone IS NOT NULL AND phone<>''
                     AND status NOT IN ('client','lost')
                   ORDER BY updated_at DESC"""
            ).fetchall()
        except Exception:
            return []

    seen_phones = set()
    for r in rows:
        phone = normalize_phone(r["phone"] or "")
        if not phone or phone in already or phone in seen_phones:
            continue
        if (r["email"] or "").lower() in suppressed_emails:
            continue
        seen_phones.add(phone)
        candidates.append({
            "phone": phone,
            "email": r["email"] or "",
            "business_name": r["business_name"] or "",
            "niche": r["niche"] or "",
            "city": r["city"] or "",
        })
        if len(candidates) >= max(1, limit):
            break
    return candidates


def available_count(conn: sqlite3.Connection) -> int:
    """Cuantos negocios con telefono quedan por contactar (sin tope)."""
    return len(fetch_prospect_phones(conn, 100000))


# --------------------------------------------------------------------------
# Cola de envios
# --------------------------------------------------------------------------

def enqueue(conn: sqlite3.Connection, count: int) -> List[Dict[str, Any]]:
    """Crea hasta `count` registros 'queued' con el mensaje renderizado. Dedup por telefono."""
    template = get_message_template(conn)
    prospects = fetch_prospect_phones(conn, count)
    created: List[Dict[str, Any]] = []
    now = now_iso()
    for p in prospects:
        msg = render_message(template, p["business_name"], p["niche"], p["city"])
        try:
            conn.execute(
                """INSERT INTO wa_messages
                   (phone, prospect_email, business_name, niche, city, message_text, mode, created_at)
                   VALUES (?,?,?,?,?,?,'queued',?)
                   ON CONFLICT(phone) DO NOTHING""",
                (p["phone"], p["email"], p["business_name"], p["niche"], p["city"], msg, now),
            )
        except Exception:
            continue
        created.append({**p, "message": msg})
    conn.commit()
    return created


def fetch_queued(conn: sqlite3.Connection, limit: int) -> List[Dict[str, Any]]:
    template = get_message_template(conn)
    rows = conn.execute(
        "SELECT phone, business_name, niche, city, message_text FROM wa_messages "
        "WHERE mode='queued' ORDER BY created_at ASC LIMIT ?",
        (max(1, limit),),
    ).fetchall()
    return [
        {
            "phone": r["phone"],
            "business_name": r["business_name"],
            "niche": r["niche"],
            "city": r["city"],
            "message": render_message(template, r["business_name"], r["niche"], r["city"]),
        }
        for r in rows
    ]


def mark_sent(conn: sqlite3.Connection, phone: str) -> None:
    conn.execute(
        "UPDATE wa_messages SET mode='sent', sent_at=?, skip_reason='' WHERE phone=?",
        (now_iso(), phone),
    )
    conn.commit()


def mark_skipped(conn: sqlite3.Connection, phone: str, reason: str) -> None:
    conn.execute(
        "UPDATE wa_messages SET mode='skipped', skip_reason=? WHERE phone=?",
        ((reason or "")[:120], phone),
    )
    conn.commit()


def mark_sending(conn: sqlite3.Connection, phone: str) -> None:
    """Marca un envio como en curso (antes de intentarlo) para evitar duplicados si crashea."""
    conn.execute("UPDATE wa_messages SET mode='sending' WHERE phone=? AND mode='queued'", (phone,))
    conn.commit()


def stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    def _count(where: str) -> int:
        return conn.execute(f"SELECT COUNT(*) AS c FROM wa_messages WHERE {where}").fetchone()["c"]

    today = datetime.now(timezone.utc).date().isoformat()
    return {
        "sent_total": _count("mode='sent'"),
        "sent_today": conn.execute(
            "SELECT COUNT(*) AS c FROM wa_messages WHERE mode='sent' AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"],
        "queued": _count("mode='queued'"),
        "sending": _count("mode='sending'"),
        "skipped": _count("mode='skipped'"),
        "available": available_count(conn),
    }


def recent(conn: sqlite3.Connection, limit: int = 30) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT phone, business_name, niche, city, mode, skip_reason, created_at, sent_at "
        "FROM wa_messages ORDER BY COALESCE(NULLIF(sent_at,''), created_at) DESC LIMIT ?",
        (max(1, min(200, limit)),),
    ).fetchall()
    return [dict(r) for r in rows]
