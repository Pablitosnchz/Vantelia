"""Captacion email outbound multi-touch (panel + autopilot) (refactor F3)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote, unquote, urlparse

from fastapi import HTTPException


from backend import appstate, clients, emailing, settings, timeutils

OUTREACH_DEFAULT_FOLLOWUP_DAYS: Dict[str, int] = {"fu1": 4, "fu2": 6, "breakup": 8}



import sys as _outreach_sys

_OUTREACH_SCRIPTS_DIR = settings.BASE_DIR / "scripts"
if str(_OUTREACH_SCRIPTS_DIR) not in _outreach_sys.path:
    _outreach_sys.path.insert(0, str(_OUTREACH_SCRIPTS_DIR))

try:
    from outreach_campaign import (  # type: ignore
        DEFAULT_DB as OUTREACH_DEFAULT_DB,
        connect as outreach_connect,
        smtp_settings as outreach_smtp_settings,
        build_message as outreach_build_message,
        fetch_candidates as outreach_fetch_candidates,
        normalize_email as outreach_normalize_email,
        _row_to_prospect as outreach_row_to_prospect,
        STAGE_ORDER as OUTREACH_STAGES,
    )
    from outreach_templates import (  # type: ignore
        Prospect as OutreachProspect,
        render as outreach_render,
        verify_tracking_token as outreach_verify_token,
        apply_tracking as outreach_apply_tracking,
        demo_url_with_utm as outreach_demo_url_with_utm,
    )
    try:
        from outreach_imap import poll_once as outreach_imap_poll  # type: ignore
        OUTREACH_IMAP_AVAILABLE = True
    except Exception as _imap_err:  # noqa: BLE001
        settings.logger.warning(f"Modulo outreach_imap no disponible: {_imap_err}")
        OUTREACH_IMAP_AVAILABLE = False
        outreach_imap_poll = None  # type: ignore
    OUTREACH_AVAILABLE = True
except Exception as _outreach_err:  # noqa: BLE001
    settings.logger.warning(f"Modulo outreach no disponible: {_outreach_err}")
    OUTREACH_AVAILABLE = False
    OUTREACH_IMAP_AVAILABLE = False
    outreach_imap_poll = None  # type: ignore
    OUTREACH_DEFAULT_DB = settings.STORAGE_DIR / "outreach" / "outreach.db"
    OUTREACH_STAGES = ["cold", "fu1", "fu2", "breakup"]

outreach_autonomous_tick_state: Dict[str, Any] = {}
outreach_autonomous_thread: Optional[threading.Thread] = None

def _outreach_imap_worker() -> None:
    interval_minutes = int(os.getenv("OUTREACH_IMAP_INTERVAL_MINUTES", "10"))
    if interval_minutes <= 0:
        settings.logger.info("Poller IMAP outreach desactivado por configuracion.")
        return
    if not os.getenv("IMAP_HOST", "").strip():
        settings.logger.info("Poller IMAP outreach: IMAP_HOST vacio, no se arranca.")
        return
    interval_seconds = max(60, interval_minutes * 60)
    settings.logger.info("Poller IMAP outreach iniciado. Intervalo: %s minutos.", interval_minutes)
    while not appstate.outreach_imap_stop.is_set():
        try:
            if not OUTREACH_IMAP_AVAILABLE or outreach_imap_poll is None:
                break
            db_path = Path(os.getenv("OUTREACH_DB_PATH", str(OUTREACH_DEFAULT_DB)))
            stats = outreach_imap_poll(db_path)
            if stats.get("replies_new"):
                settings.logger.info(
                    "IMAP poll: respuestas nuevas=%s matched=%s checked=%s",
                    stats.get("replies_new"), stats.get("matched"), stats.get("checked"),
                )
            elif stats.get("matched"):
                settings.logger.debug("IMAP poll stats: %s", stats)
            _outreach_after_imap_poll(stats)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("Error en poller IMAP outreach: %s", exc)
        appstate.outreach_imap_stop.wait(interval_seconds)


def _outreach_after_imap_poll(stats: Dict[str, Any]) -> None:
    """Post-proceso de cada pasada IMAP: notificar replies al dueño, registrar
    bounces en el log de actividad, vigilar bounce rate y reintentar avisos."""
    try:
        for reply in stats.get("replies_detail") or []:
            _outreach_notify_reply(reply)
        for bounce in stats.get("bounces_detail") or []:
            _autopilot_log(
                "warning", "bounce_detected",
                f"Bounce: {bounce.get('email', '')} marcado como bounced y suprimido",
                {"email": bounce.get("email", "")},
            )
        if stats.get("bounces_new"):
            _outreach_check_bounce_rate()
        with _outreach_db() as conn:
            _outreach_flush_notify_queue(conn)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Post-proceso IMAP outreach fallo: %s", exc)


def _outreach_notify_reply(reply: Dict[str, Any]) -> None:
    """Email al dueño con la respuesta del prospect y su ficha. Esto es el
    producto final de la captacion: una empresa interesada ha contestado."""
    email_addr = str(reply.get("email") or "")
    if not email_addr:
        return
    prospect: Dict[str, Any] = {}
    try:
        with _outreach_db() as conn:
            row = conn.execute("SELECT * FROM prospects WHERE email=?", (email_addr,)).fetchone()
            if row:
                prospect = dict(row)
    except Exception:
        pass
    business = str(prospect.get("business_name") or "") or email_addr
    subject = f"📬 Respuesta de {business} (captacion Vantelia)"
    body_excerpt = str(reply.get("body_excerpt") or "").strip() or "(sin texto extraible)"
    text = (
        f"Ha respondido un prospect de la captacion:\n\n"
        f"Negocio:  {business}\n"
        f"Email:    {email_addr}\n"
        f"Telefono: {prospect.get('phone') or '-'}\n"
        f"Sector:   {prospect.get('niche') or '-'}\n"
        f"Ciudad:   {prospect.get('city') or '-'}\n"
        f"Web:      {prospect.get('website') or '-'}\n"
        f"Etapa:    {reply.get('stage') or '-'}\n\n"
        f"Asunto: {reply.get('subject') or '-'}\n"
        f"--- Mensaje ---\n{body_excerpt}\n\n"
        f"Responde directamente a {email_addr}. La secuencia de emails se ha detenido sola.\n"
        f"Panel: {settings.APP_BASE_URL}/dashboard\n"
    )
    html = (
        f"<div style='font-family:sans-serif;max-width:560px;margin:0 auto;color:#1a1a2e'>"
        f"<h2 style='color:#00b1d9'>📬 Respuesta de {escape(business)}</h2>"
        f"<table style='width:100%;border-collapse:collapse'>"
        f"<tr><td style='padding:4px 0;color:#666;width:100px'>Email</td><td><a href='mailto:{escape(email_addr)}'>{escape(email_addr)}</a></td></tr>"
        f"<tr><td style='padding:4px 0;color:#666'>Telefono</td><td>{escape(str(prospect.get('phone') or '-'))}</td></tr>"
        f"<tr><td style='padding:4px 0;color:#666'>Sector</td><td>{escape(str(prospect.get('niche') or '-'))}</td></tr>"
        f"<tr><td style='padding:4px 0;color:#666'>Ciudad</td><td>{escape(str(prospect.get('city') or '-'))}</td></tr>"
        f"<tr><td style='padding:4px 0;color:#666'>Etapa</td><td>{escape(str(reply.get('stage') or '-'))}</td></tr>"
        f"</table>"
        f"<p style='margin-top:14px;color:#333'><strong>Asunto:</strong> {escape(str(reply.get('subject') or '-'))}</p>"
        f"<blockquote style='border-left:3px solid #00b1d9;margin:8px 0;padding:8px 12px;background:#f6fbfd;color:#333;white-space:pre-wrap'>{escape(body_excerpt)}</blockquote>"
        f"<p style='color:#333'>Responde directamente a este prospect. La secuencia se ha detenido sola.</p>"
        f"</div>"
    )
    sent = _outreach_notify_admin(subject, text, html)
    _autopilot_log(
        "success", "reply_notified" if sent else "reply_notify_queued",
        f"Respuesta de {business} ({email_addr})" + ("" if sent else " — aviso encolado, SMTP caido"),
        {"email": email_addr, "stage": reply.get("stage", ""), "notified": sent},
    )


def _outreach_check_bounce_rate(threshold_pct: float = 8.0, window: int = 100) -> bool:
    """Si el bounce rate de los ultimos `window` envios supera el umbral, pausa
    automatica 48h + aviso. Devuelve True si ha pausado."""
    try:
        with _outreach_db() as conn:
            rows = conn.execute(
                "SELECT email FROM sends WHERE mode='send' ORDER BY id DESC LIMIT ?", (window,)
            ).fetchall()
            if len(rows) < 20:
                return False
            recent_emails = {r["email"] for r in rows}
            placeholders = ",".join("?" for _ in recent_emails)
            bounced = conn.execute(
                f"SELECT COUNT(DISTINCT email) AS c FROM events WHERE type='bounce' AND email IN ({placeholders})",
                list(recent_emails),
            ).fetchone()["c"]
            rate = 100.0 * float(bounced or 0) / float(len(rows))
            if rate <= threshold_pct:
                return False
            pause = _outreach_pause_state(conn)
            if pause["auto"]:
                return False
            until = datetime.now(timezone.utc) + timedelta(hours=48)
            _outreach_set_auto_pause(conn, until, f"Bounce rate {rate:.1f}% (pausa 48h)")
        _autopilot_log(
            "error", "bounce_rate_autopause",
            f"Bounce rate {rate:.1f}% en los ultimos {len(rows)} envios: pausa 48h",
            {"rate_pct": round(rate, 1), "window": len(rows), "bounced": int(bounced or 0)},
        )
        _outreach_notify_admin(
            "Captacion Vantelia pausada 48h (bounce rate alto)",
            f"El bounce rate es {rate:.1f}% en los ultimos {len(rows)} envios (umbral {threshold_pct}%).\n"
            f"La captacion queda pausada 48h y se reanudara sola.\n"
            "Los emails rebotados quedan suprimidos automaticamente. Si persiste, "
            "revisa la calidad del discovery (emails scrapeados invalidos).",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Check de bounce rate fallo: %s", exc)
        return False


def _mark_outreach_prospect_as_client_for_cliente(cliente_id: str, user_email: str) -> None:
    """If outreach is configured and the prospect is discoverable, flip its
    status to 'client'. Lookup: exact match on prospects.email = user_email or
    on the contacto.email saved in the cliente config. Anything missing is
    silently skipped."""
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    candidate_emails: List[str] = []
    if user_email:
        candidate_emails.append(user_email.lower())
    contacto_email = (cfg.get("contacto", {}) or {}).get("email", "").lower()
    if contacto_email and contacto_email not in candidate_emails:
        candidate_emails.append(contacto_email)

    db_path = os.getenv("OUTREACH_DB_PATH", "").strip() or str(settings.STORAGE_DIR / "outreach" / "outreach.db")
    if not Path(db_path).exists():
        return
    try:
        with sqlite3.connect(db_path, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            now_iso = timeutils._utc_now().isoformat()
            for email in candidate_emails:
                conn.execute(
                    "UPDATE prospects SET status = 'client', updated_at = ? "
                    "WHERE LOWER(email) = ? AND status NOT IN ('client', 'lost')",
                    (now_iso, email),
                )
            conn.commit()
    except sqlite3.Error as exc:
        settings.logger.warning("Outreach DB no accesible para marcar client: %s", exc)


def _growth_automatic_outreach() -> Dict[str, int]:
    result = {"prospects": 0, "sends_30d": 0, "replies_30d": 0}
    try:
        since = (timeutils._utc_now() - timedelta(days=30)).isoformat()
        with _outreach_db() as connection:
            result["prospects"] = int(connection.execute("SELECT COUNT(*) FROM prospects").fetchone()[0])
            result["sends_30d"] = int(connection.execute("SELECT COUNT(*) FROM sends WHERE created_at >= ?", (since,)).fetchone()[0])
            result["replies_30d"] = int(connection.execute("SELECT COUNT(*) FROM events WHERE type = 'reply' AND ts >= ?", (since,)).fetchone()[0])
    except Exception:
        pass
    return result


OUTREACH_TRACKING_SECRET = os.getenv("OUTREACH_TRACKING_SECRET", "").strip()


OUTREACH_TRACKING_BASE_URL = os.getenv("OUTREACH_TRACKING_BASE_URL", "").strip().rstrip("/") or settings.APP_BASE_URL


_TRACKING_ENABLED_EXPLICIT = os.getenv("OUTREACH_TRACKING_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


OUTREACH_TRACKING_DISABLED = not _TRACKING_ENABLED_EXPLICIT


def _outreach_db():
    if not OUTREACH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Modulo outreach no disponible.")
    return outreach_connect(Path(os.getenv("OUTREACH_DB_PATH", str(OUTREACH_DEFAULT_DB))))


def _outreach_now() -> str:
    return timeutils._utc_now().isoformat(timespec="seconds")


def _autopilot_log(level: str, event: str, message: str, detail: Any = None) -> None:
    """Registra evento estructurado en autopilot_activity_log. Nunca lanza. Reintenta brevemente si DB está locked."""
    if not OUTREACH_AVAILABLE:
        return
    lvl = (level or "info").lower()
    if lvl not in {"info", "success", "warning", "error"}:
        lvl = "info"
    if detail is None:
        detail_s = ""
    elif isinstance(detail, str):
        detail_s = detail
    else:
        try:
            detail_s = json.dumps(detail, ensure_ascii=False, default=str)
        except Exception:
            detail_s = str(detail)
    last_exc: Optional[Exception] = None
    for attempt in range(5):
        try:
            with _outreach_db() as conn:
                try:
                    conn.execute("PRAGMA busy_timeout=4000")
                except Exception:
                    pass
                conn.execute(
                    "INSERT INTO autopilot_activity_log (ts, level, event, message, detail) VALUES (?,?,?,?,?)",
                    (_outreach_now(), lvl, str(event or "")[:80], str(message or "")[:500], detail_s[:2000]),
                )
                conn.commit()
            return
        except sqlite3.OperationalError as exc:
            last_exc = exc
            if "locked" in str(exc).lower():
                time.sleep(0.2 * (attempt + 1))
                continue
            break
        except Exception as exc:
            last_exc = exc
            break
    try:
        settings.logger.warning("[autopilot] no se pudo persistir log %s: %s", event, last_exc)
    except Exception:
        pass


# --- Pre-generacion de demo al ABRIR el email -----------------------------
# Al abrir (pixel), se lanza la generacion de la demo personalizada en segundo
# plano. Cuando el prospecto hace clic (segundos/minutos despues) la demo YA
# esta lista -> carga instantanea -> parece legitimo, no un loader eterno.

_demo_pregen_lock = threading.Lock()
_demo_pregen_inflight: Set[str] = set()


def _outreach_prospect_row_for_email(email: str) -> Optional[Dict[str, Any]]:
    email = (email or "").strip().lower()
    if not email:
        return None
    try:
        with _outreach_db() as conn:
            row = conn.execute("SELECT * FROM prospects WHERE email=?", (email,)).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def _outreach_latest_stage_for_email(email: str, default: str = "cold") -> str:
    """Devuelve la etapa del ultimo envio real, sin inferirla desde aperturas."""
    email_clean = (email or "").strip().lower()
    default_clean = (default or "cold").strip().lower() or "cold"
    if not email_clean or not OUTREACH_AVAILABLE:
        return default_clean
    try:
        with _outreach_db() as conn:
            row = conn.execute(
                """SELECT stage FROM sends
                   WHERE email=? AND mode='send'
                   ORDER BY sent_at DESC, id DESC LIMIT 1""",
                (email_clean,),
            ).fetchone()
        stage = str(row["stage"] if row else "").strip().lower()
        return stage or default_clean
    except Exception:
        return default_clean


_DEMO_ORIENTATIVE_ANALYTICS_EVENTS = {
    "demo_chat_started": "demo_chat_opened",
    "demo_contact_clicked": "contact_intent",
    "demo_whatsapp_clicked": "whatsapp_intent",
    "demo_claim_clicked": "claim_intent",
}
_DEMO_AUTO_PREFIX = "demo_auto_"
_DEMO_SIGNAL_TOKEN_TTL_SECONDS = max(
    60, int(os.getenv("DEMO_TENANT_TTL_SECONDS", "3600"))
)


def _outreach_demo_signal_token(
    cliente_id: str,
    event_name: str,
    session_id: str,
    *,
    expires_at: Optional[int] = None,
) -> str:
    """Firma cliente+expiry+evento+sesion sin revelar el secreto."""
    cliente_clean = (cliente_id or "").strip()[:80]
    event_clean = str(event_name or "").strip()[:80]
    session_clean = str(session_id or "").strip()[:128]
    if (
        not OUTREACH_TRACKING_SECRET
        or not cliente_clean.startswith(_DEMO_AUTO_PREFIX)
        or not settings.CLIENT_ID_PATTERN.match(cliente_clean)
        or event_clean not in _DEMO_ORIENTATIVE_ANALYTICS_EVENTS
        or not settings.SESSION_ID_PATTERN.match(session_clean)
    ):
        return ""
    try:
        from backend import demo_agenda

        if not demo_agenda._demo_is_active_unclaimed(cliente_clean):
            return ""
    except Exception:
        return ""
    expiry = (
        int(expires_at)
        if expires_at is not None
        else int(time.time()) + _DEMO_SIGNAL_TOKEN_TTL_SECONDS
    )
    message = (
        f"vantelia-demo-signal:v2:{cliente_clean}:{expiry}:{event_clean}:{session_clean}"
    ).encode("utf-8")
    signature = hmac.new(
        OUTREACH_TRACKING_SECRET.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()
    return f"v2.{expiry}.{signature}"


def _outreach_verify_demo_signal_token(
    cliente_id: str,
    event_name: str,
    session_id: str,
    signal_token: str,
) -> bool:
    cliente_clean = (cliente_id or "").strip()[:80]
    event_clean = str(event_name or "").strip()[:80]
    session_clean = str(session_id or "").strip()[:128]
    token_clean = str(signal_token or "").strip()[:160]
    if (
        not OUTREACH_TRACKING_SECRET
        or not cliente_clean.startswith(_DEMO_AUTO_PREFIX)
        or not settings.CLIENT_ID_PATTERN.match(cliente_clean)
        or event_clean not in _DEMO_ORIENTATIVE_ANALYTICS_EVENTS
        or not settings.SESSION_ID_PATTERN.match(session_clean)
    ):
        return False
    try:
        version, expiry_raw, provided_signature = token_clean.split(".", 2)
        expiry = int(expiry_raw)
    except (TypeError, ValueError):
        return False
    if version != "v2" or expiry <= int(time.time()):
        return False
    message = (
        f"vantelia-demo-signal:v2:{cliente_clean}:{expiry}:{event_clean}:{session_clean}"
    ).encode("utf-8")
    expected_signature = hmac.new(
        OUTREACH_TRACKING_SECRET.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(provided_signature, expected_signature)


def _outreach_mirror_demo_analytics_event(
    payload: Dict[str, Any], *, signal_token: str = ""
) -> bool:
    """Replica una senal orientativa del navegador en las metricas de outreach.

    Es idempotente por prospecto, tipo y sesion de analitica. No replica URLs,
    mensajes ni otros datos del visitante y nunca cambia el estado comercial.
    """
    if not OUTREACH_AVAILABLE or not isinstance(payload, dict):
        return False

    event_name = str(payload.get("event") or "").strip()
    outreach_type = _DEMO_ORIENTATIVE_ANALYTICS_EVENTS.get(event_name)
    if not outreach_type:
        return False

    cliente_id = str(
        payload.get("widget_client_id") or payload.get("cliente_id") or ""
    ).strip()[:80]
    if not cliente_id.startswith(_DEMO_AUTO_PREFIX):
        return False
    if not settings.CLIENT_ID_PATTERN.match(cliente_id):
        return False

    session_id = str(payload.get("session_id") or "").strip()[:128]
    if not session_id or not settings.SESSION_ID_PATTERN.match(session_id):
        return False
    if not _outreach_verify_demo_signal_token(
        cliente_id, event_name, session_id, signal_token
    ):
        return False

    try:
        config = clients._get_client_config(cliente_id)
    except HTTPException:
        return False
    contacto = config.get("contacto") if isinstance(config, dict) else {}
    email = str((contacto or {}).get("email") or "").strip().lower()
    if not email:
        return False
    fingerprint = hashlib.sha256(
        f"{cliente_id}\0{event_name}\0{session_id}".encode("utf-8")
    ).hexdigest()[:32]
    event_key = f"demo-analytics:{fingerprint}"

    try:
        with _outreach_db() as conn:
            prospect = conn.execute(
                "SELECT 1 FROM prospects WHERE email=?", (email,)
            ).fetchone()
            if not prospect:
                return False
            stage_row = conn.execute(
                """SELECT stage FROM sends
                   WHERE email=? AND mode='send'
                   ORDER BY sent_at DESC, id DESC LIMIT 1""",
                (email,),
            ).fetchone()
            stage = str(stage_row["stage"] if stage_row else "cold").strip().lower() or "cold"
            insert_cursor = conn.execute(
                """INSERT INTO events (email, type, stage, url, ts, ua, ip)
                   SELECT ?,?,?,?,?,?,?
                   WHERE NOT EXISTS (
                       SELECT 1 FROM events
                       WHERE email=? AND type=? AND url=?
                   )""",
                (
                    email,
                    outreach_type,
                    stage,
                    event_key,
                    _outreach_now(),
                    "",
                    "",
                    email,
                    outreach_type,
                    event_key,
                ),
            )
            inserted = insert_cursor.rowcount == 1
            conn.commit()
        return inserted
    except Exception as exc:  # noqa: BLE001
        settings.logger.debug("No se pudo reflejar interaccion de demo en outreach: %s", exc)
        return False


def _outreach_record_demo_chat_message(cliente_id: str, session_id: str) -> bool:
    """Senal fuerte: /chat valido y persistio el mensaje de una auto-demo."""
    cliente_clean = (cliente_id or "").strip()[:80]
    session_clean = str(session_id or "").strip()[:128]
    if (
        not OUTREACH_AVAILABLE
        or not cliente_clean.startswith(_DEMO_AUTO_PREFIX)
        or not settings.CLIENT_ID_PATTERN.match(cliente_clean)
        or not settings.SESSION_ID_PATTERN.match(session_clean)
    ):
        return False
    try:
        from backend import demo_agenda

        if not demo_agenda._demo_is_active_unclaimed(cliente_clean):
            return False
    except Exception:
        return False
    try:
        config = clients._get_client_config(cliente_clean)
    except HTTPException:
        return False
    email = str(((config.get("contacto") or {}).get("email")) or "").strip().lower()
    if not email:
        return False
    event_key = "demo-server:" + hashlib.sha256(
        f"{cliente_clean}\0chat_message\0{session_clean}".encode("utf-8")
    ).hexdigest()[:32]
    try:
        with _outreach_db() as conn:
            if not conn.execute(
                "SELECT 1 FROM prospects WHERE email=?", (email,)
            ).fetchone():
                return False
            stage_row = conn.execute(
                """SELECT stage FROM sends WHERE email=? AND mode='send'
                   ORDER BY sent_at DESC, id DESC LIMIT 1""",
                (email,),
            ).fetchone()
            stage = str(stage_row["stage"] if stage_row else "cold").strip().lower() or "cold"
            cursor = conn.execute(
                """INSERT INTO events (email, type, stage, url, ts, ua, ip)
                   SELECT ?, 'demo_interacted', ?, ?, ?, '', ''
                   WHERE NOT EXISTS (
                       SELECT 1 FROM events
                       WHERE email=? AND type='demo_interacted' AND url=?
                   )""",
                (email, stage, event_key, _outreach_now(), email, event_key),
            )
            inserted = cursor.rowcount == 1
            if inserted:
                conn.execute(
                    """UPDATE prospects SET status='engaged', updated_at=?
                       WHERE email=? AND status IN ('new','contacted')""",
                    (_outreach_now(), email),
                )
            conn.commit()
        return inserted
    except Exception as exc:  # noqa: BLE001
        settings.logger.debug("No se pudo registrar chat real de demo en outreach: %s", exc)
        return False


def _outreach_demo_sector_for_row(row: Dict[str, Any]) -> str:
    try:
        from outreach_templates import Prospect as _P, _demo_sector_for_prospect  # type: ignore

        p = _P(email=row.get("email", ""), business_name=row.get("business_name", ""),
               niche=row.get("niche", ""), service_hint=row.get("service_hint", ""))
        return _demo_sector_for_prospect(p)
    except Exception:
        return "Otro"


def _outreach_demo_pregen_enabled() -> bool:
    return os.getenv("OUTREACH_DEMO_PREGEN", "true").strip().lower() in {"1", "true", "yes", "on"}


def _outreach_maybe_pregenerate_demo(email: str) -> None:
    """Si el prospecto tiene web y aun no tiene demo viva, la genera en background.
    Idempotente y con guard de in-flight para no duplicar ni gastar de mas."""
    if not _outreach_demo_pregen_enabled() or not OUTREACH_AVAILABLE:
        return
    email = (email or "").strip().lower()
    if not email:
        return
    row = _outreach_prospect_row_for_email(email)
    if not row or not (row.get("website") or "").strip():
        return  # sin web no hay nada que rastrear; se genera al hacer clic
    try:
        from backend import demo_agenda
        existing, _ = demo_agenda._existing_demo_for_email(email)
        if existing:
            return
    except Exception:
        return
    with _demo_pregen_lock:
        if email in _demo_pregen_inflight:
            return
        _demo_pregen_inflight.add(email)

    def _worker():
        try:
            from backend import demo_agenda
            if not settings.OPENAI_API_KEY:
                return
            res = demo_agenda.build_demo_tenant(
                nombre_empresa=row.get("business_name") or "Empresa",
                sector=_outreach_demo_sector_for_row(row),
                email=email,
                website_url=(row.get("website") or "").strip(),
            )
            _autopilot_log(
                "success", "demo_pregenerated",
                f"Demo pre-generada al abrir: {row.get('business_name') or email}",
                {"email": email, "cliente_id": res.get("cliente_id"), "reused": res.get("reused")},
            )
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("Pre-generacion de demo fallo para %s: %s", email, exc)
        finally:
            with _demo_pregen_lock:
                _demo_pregen_inflight.discard(email)

    threading.Thread(target=_worker, daemon=True).start()


def _outreach_demo_target_for_email(email: str) -> Dict[str, Any]:
    """Resuelve a donde mandar el clic del email. Devuelve
    {status: 'ready'|'generating'|'form', demo_url?, business?, form_url?}."""
    email = (email or "").strip().lower()
    row = _outreach_prospect_row_for_email(email)
    business = (row or {}).get("business_name") or ""
    base_app = (settings.APP_BASE_URL or "https://app.vantelia.es").rstrip("/")
    try:
        from backend import demo_agenda
        existing, _ = demo_agenda._existing_demo_for_email(email)
        if existing:
            return {"status": "ready", "demo_url": f"{base_app}/demo/{existing}", "business": business}
    except Exception:
        pass
    # No lista: si tiene web, dispara/continua generacion y muestra pagina de espera.
    if row and (row.get("website") or "").strip():
        with _demo_pregen_lock:
            generating = email in _demo_pregen_inflight
        if not generating:
            _outreach_maybe_pregenerate_demo(email)
        return {"status": "generating", "business": business}
    # Sin web: al formulario clasico (con datos precargados).
    return {"status": "form", "business": business, "form_url": _outreach_demo_form_url(row or {})}


def _outreach_demo_form_url(row: Dict[str, Any]) -> str:
    from urllib.parse import urlencode
    params = {
        "utm_source": "outreach", "utm_medium": "email", "utm_campaign": "cold",
        "empresa": row.get("business_name") or "",
        "email": row.get("email") or "",
        "web": row.get("website") or "",
        "sector": _outreach_demo_sector_for_row(row) if row else "",
    }
    q = urlencode({k: v for k, v in params.items() if v})
    return f"https://www.vantelia.es/demo/?{q}"


def _outreach_record_external_bounce(email: str, reason: str = "", kind: str = "bounce") -> bool:
    """Registra un rebote/queja notificado por un proveedor externo (webhook Brevo).

    Marca el prospect (bounced/baja), lo suprime y registra el evento. Idempotente.
    Devuelve True si el evento era nuevo. Espeja _record_bounce del poller IMAP,
    necesario porque con SMTP dedicado (Brevo) los NDR NO llegan al buzon IMAP.
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False
    status = "baja" if kind in ("spam", "unsubscribe", "complaint") else "bounced"
    ev_type = "bounce" if status == "bounced" else "unsubscribe"
    try:
        with _outreach_db() as conn:
            if not conn.execute("SELECT 1 FROM prospects WHERE email=?", (email,)).fetchone():
                return False
            already = conn.execute(
                "SELECT 1 FROM events WHERE email=? AND type=? LIMIT 1", (email, ev_type)
            ).fetchone()
            conn.execute(
                "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,'','')",
                (email, ev_type, "", reason[:200], _outreach_now()),
            )
            conn.execute(
                "UPDATE prospects SET status=?, updated_at=? WHERE email=?",
                (status, _outreach_now(), email),
            )
            conn.execute(
                "INSERT OR IGNORE INTO suppressions (email, reason, added_at) VALUES (?,?,?)",
                (email, kind or "bounce", _outreach_now()),
            )
            conn.commit()
        _autopilot_log(
            "warning", "external_bounce" if status == "bounced" else "external_unsubscribe",
            f"{'Rebote' if status=='bounced' else 'Baja'} (Brevo): {email} → {status} + suprimido",
            {"email": email, "kind": kind, "reason": reason[:160]},
        )
        return not already
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("No se pudo registrar rebote externo de %s: %s", email, exc)
        return False


# Eventos de Brevo que tratamos como rebote duro / baja.
# OJO: "deferred"/"soft_bounce" son retrasos temporales; solo el hard bounce
# repetido es muerte real. Brevo ya suprime el hard tras varios soft, asi que
# actuamos sobre hard_bounce/blocked/invalid/error, NO sobre soft/deferred
# (marcar bounced por un retraso temporal quemaria prospects validos).
BREVO_BOUNCE_EVENTS = {"hard_bounce", "blocked", "invalid_email", "error"}
BREVO_UNSUB_EVENTS = {"spam", "complaint", "unsubscribed", "unsubscribe", "list_addition"}


def _outreach_process_brevo_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Procesa un evento del webhook de Brevo. Devuelve {handled, action, email}."""
    event = str(payload.get("event") or payload.get("type") or "").strip().lower()
    email = str(payload.get("email") or "").strip().lower()
    reason = str(payload.get("reason") or payload.get("subject") or "")[:200]
    if not email:
        return {"handled": False, "action": "no_email"}
    if event in BREVO_BOUNCE_EVENTS:
        created = _outreach_record_external_bounce(email, reason, kind="bounce")
        if created:
            _outreach_check_bounce_rate()
        return {"handled": True, "action": "bounce", "email": email, "new": created}
    if event in BREVO_UNSUB_EVENTS:
        _outreach_record_external_bounce(email, reason, kind="unsubscribe")
        return {"handled": True, "action": "unsubscribe", "email": email}
    # opened/click/delivered los ignoramos (ya tenemos tracking propio).
    return {"handled": False, "action": "ignored", "event": event}


outreach_autonomous_tick_lock = threading.Lock()


outreach_autonomous_tick_state_lock = threading.Lock()


def _outreach_tick_state_snapshot() -> Dict[str, Any]:
    with outreach_autonomous_tick_state_lock:
        state = dict(outreach_autonomous_tick_state)
    if outreach_autonomous_tick_lock.locked():
        state.setdefault("running", True)
        state.setdefault("status", "running")
        state.setdefault("source", "unknown")
        state.setdefault("step", "unknown")
    return state


def _outreach_tick_state_start(source: str) -> Dict[str, Any]:
    state = {
        "tick_id": f"tick_{uuid.uuid4().hex[:10]}",
        "source": source,
        "status": "queued",
        "step": "queued",
        "message": "Ronda encolada",
        "started_at": _outreach_now(),
        "updated_at": _outreach_now(),
        "running": True,
    }
    with outreach_autonomous_tick_state_lock:
        outreach_autonomous_tick_state.clear()
        outreach_autonomous_tick_state.update(state)
    return dict(state)


def _outreach_tick_state_update(step: str, message: str = "", detail: Any = None, **extra: Any) -> Dict[str, Any]:
    with outreach_autonomous_tick_state_lock:
        if not outreach_autonomous_tick_state:
            outreach_autonomous_tick_state.update({
                "tick_id": f"tick_{uuid.uuid4().hex[:10]}",
                "source": "unknown",
                "started_at": _outreach_now(),
            })
        outreach_autonomous_tick_state.update({
            "status": extra.pop("status", "running"),
            "step": step,
            "message": message or step,
            "updated_at": _outreach_now(),
            "running": True,
        })
        if detail is not None:
            outreach_autonomous_tick_state["detail"] = detail
        outreach_autonomous_tick_state.update(extra)
        return dict(outreach_autonomous_tick_state)


def _outreach_tick_state_finish(status: str = "done", message: str = "") -> Dict[str, Any]:
    with outreach_autonomous_tick_state_lock:
        if not outreach_autonomous_tick_state:
            return {}
        final_status = outreach_autonomous_tick_state.get("status")
        if final_status not in {"error"}:
            final_status = status
        outreach_autonomous_tick_state.update({
            "status": final_status,
            "step": "finished" if final_status != "error" else outreach_autonomous_tick_state.get("step", "error"),
            "message": message or ("Ronda terminada" if final_status != "error" else outreach_autonomous_tick_state.get("message", "Ronda fallida")),
            "finished_at": _outreach_now(),
            "updated_at": _outreach_now(),
            "running": False,
        })
        return dict(outreach_autonomous_tick_state)


def _outreach_prospect_from_row(row: sqlite3.Row) -> OutreachProspect:
    return OutreachProspect(
        email=row["email"] or "",
        business_name=row["business_name"] or "",
        contact_name=row["contact_name"] or "",
        niche=row["niche"] or "",
        service_hint=row["service_hint"] or "",
        city=row["city"] or "",
        website=row["website"] or "",
        phone=row["phone"] or "",
        tags=row["tags"] or "",
        source=row["source"] or "",
    )


def _outreach_followup_subject(row: sqlite3.Row, priority: int) -> str:
    business = row["business_name"] or "tu negocio"
    if priority == 1:
        return f"{business} - te la preparo yo?"
    if priority == 2:
        return f"re: demo para {business}"
    return f"cierro lo de {business}"


def _outreach_followup_body(row: sqlite3.Row, priority: int, signals: Dict[str, int], demo_url: str) -> str:
    business = row["business_name"] or "tu negocio"
    first_name = (row["contact_name"] or "").strip().split(" ", 1)[0]
    greeting = f"Hola {first_name}," if first_name else "Hola,"
    if priority == 1:
        reason = "vi que la demo te intereso" if signals.get("demos", 0) else "vi movimiento con la demo"
        return (
            f"{greeting}\n\n"
            f"{reason} de {business}.\n\n"
            "Para hacerlo facil: si me respondes \"si\", la preparo yo con vuestra web y te mando un enlace privado. "
            "Sin llamada y sin compromiso.\n\n"
            f"Tambien puedes generarla aqui, ya con los datos cargados:\n{demo_url}\n\n"
            "Si te encaja, puedes empezar con el plan Free gratis para siempre o subir al plan que necesites.\n\n"
            "Un saludo,\nPablo"
        )
    if priority == 2:
        return (
            f"{greeting}\n\n"
            f"Te dejo esto mas facil: el formulario de demo de {business} ya va con los datos cargados.\n\n"
            f"{demo_url}\n\n"
            "Si prefieres no tocar nada, responde \"si\" y la preparo yo. "
            "Si no es prioridad ahora, respondes \"no\" y cierro ficha.\n\n"
            "Un saludo,\nPablo"
        )
    return (
        f"{greeting}\n\n"
        f"Cierro por ahora lo de la demo de {business} para no insistir.\n\n"
        "Si quieres verla, responde \"si\" y te la preparo yo con vuestra web. "
        "Si no encaja, todo bien.\n\n"
        "Un saludo,\nPablo"
    )


OUTREACH_MAX_TOUCHES_PER_PROSPECT = 4


def _outreach_normalize_followup_days(value: Any = None) -> Dict[str, int]:
    raw: Dict[str, Any] = {}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                raw = parsed
        except Exception:
            raw = {}
    elif isinstance(value, dict):
        raw = value
    clean = dict(OUTREACH_DEFAULT_FOLLOWUP_DAYS)
    for stage in ("fu1", "fu2", "breakup"):
        try:
            clean[stage] = max(0, min(90, int(raw.get(stage, clean[stage]))))
        except Exception:
            clean[stage] = OUTREACH_DEFAULT_FOLLOWUP_DAYS[stage]
    return clean


def _outreach_followup_stage_days(value: Any = None) -> List[tuple[str, int]]:
    days = _outreach_normalize_followup_days(value)
    return [(stage, days[stage]) for stage in ("fu1", "fu2", "breakup")]


def _outreach_ensure_autopilot_config_columns(conn: sqlite3.Connection) -> None:
    try:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(autopilot_config)").fetchall()}
        if "followup_days_json" not in existing:
            conn.execute(
                "ALTER TABLE autopilot_config ADD COLUMN followup_days_json TEXT DEFAULT '{\"fu1\":4,\"fu2\":5,\"breakup\":6}'"
            )
            conn.commit()
        if "discovery_enabled" not in existing:
            conn.execute(
                "ALTER TABLE autopilot_config ADD COLUMN discovery_enabled INTEGER DEFAULT 1"
            )
        if "paused_until" not in existing:
            conn.execute("ALTER TABLE autopilot_config ADD COLUMN paused_until TEXT DEFAULT ''")
        if "paused_reason" not in existing:
            conn.execute("ALTER TABLE autopilot_config ADD COLUMN paused_reason TEXT DEFAULT ''")
        if "ratelimit_days_json" not in existing:
            conn.execute("ALTER TABLE autopilot_config ADD COLUMN ratelimit_days_json TEXT DEFAULT '[]'")
        if "exhausted_targets_json" not in existing:
            conn.execute("ALTER TABLE autopilot_config ADD COLUMN exhausted_targets_json TEXT DEFAULT '{}'")
            conn.commit()
    except sqlite3.OperationalError:
        pass


def _outreach_config_followup_days(conn: sqlite3.Connection) -> Dict[str, int]:
    _outreach_ensure_autopilot_config_columns(conn)
    try:
        row = conn.execute("SELECT followup_days_json FROM autopilot_config WHERE id=1").fetchone()
        return _outreach_normalize_followup_days(row["followup_days_json"] if row else None)
    except Exception:
        return dict(OUTREACH_DEFAULT_FOLLOWUP_DAYS)


def _outreach_parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


OUTREACH_TERMINAL_STATUSES = frozenset(
    {"replied", "client", "lost", "bounced", "baja"}
)


def _outreach_send_eligibility(
    conn: sqlite3.Connection,
    email: str,
    stage: str,
    after_days: int,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Evalua todas las condiciones que permiten un envio real.

    Las listas explicitas y ``only_email`` son filtros de entrada, nunca un
    atajo a estas reglas. El mismo dictamen se usa en preflight, al seleccionar
    candidatos y justo antes de entregar el mensaje a SMTP.
    """
    stage_clean = str(stage or "").strip().lower()
    if stage_clean not in OUTREACH_STAGES:
        raise ValueError(f"Stage invalido: {stage_clean or '-'}")
    try:
        wait_days = max(0, int(after_days))
    except (TypeError, ValueError):
        wait_days = 0

    email_clean = outreach_normalize_email(str(email or ""))
    result: Dict[str, Any] = {
        "eligible": False,
        "email": email_clean,
        "stage": stage_clean,
        "reason": "",
        "after_days": wait_days,
    }
    if not email_clean or "@" not in email_clean:
        result["reason"] = "invalid_email"
        return result

    prospect = conn.execute(
        "SELECT * FROM prospects WHERE email=?", (email_clean,)
    ).fetchone()
    if not prospect:
        result["reason"] = "prospect_missing"
        return result
    result["prospect"] = prospect

    if conn.execute(
        "SELECT 1 FROM suppressions WHERE email=? LIMIT 1", (email_clean,)
    ).fetchone():
        result["reason"] = "suppressed"
        return result

    # Solo una respuesta recibida cuenta como reply. ``reply_intent`` y clics
    # son senales de interes, no autorizan a alterar la secuencia.
    if conn.execute(
        "SELECT 1 FROM events WHERE email=? AND type='reply' LIMIT 1",
        (email_clean,),
    ).fetchone():
        result["reason"] = "replied"
        return result

    status = str(prospect["status"] or "").strip().lower()
    if status in OUTREACH_TERMINAL_STATUSES:
        result["reason"] = f"status_{status}"
        return result

    if stage_clean == "cold":
        # Un cold nunca reinicia una secuencia que ya tuvo cualquier envio real.
        if conn.execute(
            "SELECT 1 FROM sends WHERE email=? AND mode='send' LIMIT 1",
            (email_clean,),
        ).fetchone():
            result["reason"] = "already_contacted"
            return result
    else:
        if conn.execute(
            "SELECT 1 FROM sends WHERE email=? AND stage=? AND mode='send' LIMIT 1",
            (email_clean, stage_clean),
        ).fetchone():
            result["reason"] = "stage_already_sent"
            return result

        previous_stage = OUTREACH_STAGES[OUTREACH_STAGES.index(stage_clean) - 1]
        previous = conn.execute(
            """SELECT sent_at FROM sends
               WHERE email=? AND stage=? AND mode='send'
               ORDER BY sent_at DESC, id DESC LIMIT 1""",
            (email_clean, previous_stage),
        ).fetchone()
        if not previous:
            result["reason"] = "predecessor_missing"
            result["previous_stage"] = previous_stage
            return result

        previous_at = _outreach_parse_dt(str(previous["sent_at"] or ""))
        if previous_at is None:
            # Un historico sin fecha fiable no debe habilitar automaticamente
            # el siguiente toque.
            result["reason"] = "predecessor_date_invalid"
            result["previous_stage"] = previous_stage
            return result
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        current_time = current_time.astimezone(timezone.utc)
        eligible_at = previous_at + timedelta(days=wait_days)
        result.update(
            {
                "previous_stage": previous_stage,
                "previous_sent_at": previous_at.isoformat(timespec="seconds"),
                "eligible_at": eligible_at.isoformat(timespec="seconds"),
            }
        )
        if current_time < eligible_at:
            result["reason"] = "after_days_pending"
            return result

    result["eligible"] = True
    result["reason"] = "eligible"
    return result


def _outreach_select_eligible_prospects(
    conn: sqlite3.Connection,
    stage: str,
    after_days: int,
    limit: int,
    *,
    emails: Optional[List[str]] = None,
    only_email: str = "",
    now: Optional[datetime] = None,
) -> tuple[List[Any], List[Dict[str, Any]]]:
    """Selecciona y filtra prospects conservando el orden del selector actual."""
    max_items = max(0, int(limit or 0))
    requested = list(
        dict.fromkeys(
            outreach_normalize_email(str(value or ""))
            for value in (emails or [])
            if str(value or "").strip()
        )
    )
    only_clean = outreach_normalize_email(only_email or "")
    if not requested and only_clean:
        requested = [only_clean]

    source: List[Any] = []
    if requested:
        placeholders = ",".join("?" for _ in requested)
        rows = conn.execute(
            f"SELECT * FROM prospects WHERE email IN ({placeholders})",
            requested,
        ).fetchall()
        by_email = {str(row["email"] or "").strip().lower(): row for row in rows}
        source = [by_email[email] for email in requested if email in by_email]
    else:
        # El selector existente conserva su priorizacion. La evaluacion comun
        # sigue siendo la autoridad y protege ante cualquier divergencia futura.
        selected = outreach_fetch_candidates(
            conn,
            stage,
            after_days=max(0, int(after_days or 0)),
            limit=max_items,
            only_email=None,
        )
        for candidate in selected:
            row = conn.execute(
                "SELECT * FROM prospects WHERE email=?", (candidate.email,)
            ).fetchone()
            if row:
                source.append(row)

    assessments: List[Dict[str, Any]] = []
    eligible: List[Any] = []
    present = {str(row["email"] or "").strip().lower() for row in source}
    for requested_email in requested:
        if requested_email not in present:
            assessments.append(
                {
                    "eligible": False,
                    "email": requested_email,
                    "stage": stage,
                    "reason": "prospect_missing",
                    "after_days": max(0, int(after_days or 0)),
                }
            )
    for row in source:
        assessment = _outreach_send_eligibility(
            conn,
            str(row["email"] or ""),
            stage,
            after_days,
            now=now,
        )
        assessments.append(assessment)
        if assessment["eligible"] and (not max_items or len(eligible) < max_items):
            eligible.append(outreach_row_to_prospect(row))
    return eligible, assessments


def _outreach_next_stage(row: sqlite3.Row) -> str:
    if int(row["fu1_sent"] or 0) <= 0:
        return "fu1"
    if int(row["fu2_sent"] or 0) <= 0:
        return "fu2"
    if int(row["breakup_sent"] or 0) <= 0:
        return "breakup"
    return ""


def _outreach_autopilot_gate(
    row: sqlite3.Row,
    priority: int,
    stage: str,
    followup_days: Optional[Dict[str, int]] = None,
) -> tuple[bool, str]:
    if not stage:
        return False, "secuencia completada"
    if int(row["total_sent"] or 0) >= OUTREACH_MAX_TOUCHES_PER_PROSPECT:
        return False, "limite de contactos alcanzado"
    if int(row[f"{stage}_sent"] or 0) > 0:
        return False, f"{stage} ya enviado"
    if int(row["replies"] or 0) > 0 or (row["status"] or "") in ("replied", "client", "lost"):
        return False, "respuesta/estado final"
    last_sent = _outreach_parse_dt(row["last_sent_at"] or "")
    if not last_sent:
        return False, "sin envio previo"
    min_wait = _outreach_normalize_followup_days(followup_days).get(stage, 3)
    age_days = (timeutils._utc_now() - last_sent).total_seconds() / 86400
    if age_days < min_wait:
        return False, f"esperar {max(1, int((min_wait - age_days) + 0.999))}d"
    return True, "listo para aprobar"


def _outreach_action_for_item(
    row: sqlite3.Row,
    priority: int,
    stage: str,
    can_send: bool,
    blocked_reason: str,
    signals: Dict[str, int],
) -> Dict[str, Any]:
    status_value = row["status"] or "new"
    if signals.get("replies", 0) > 0 or status_value == "replied":
        return {
            "next_action": "manual_reply",
            "next_action_label": "Responder personalmente",
            "action_reason": "Ya respondio; toca convertir conversacion en piloto.",
            "expected_state": "consulta, alta Free o plan de pago",
            "requires_approval": False,
        }
    if status_value in ("client", "lost"):
        return {
            "next_action": "stop",
            "next_action_label": "No contactar mas",
            "action_reason": "Estado final.",
            "expected_state": status_value,
            "requires_approval": False,
        }
    if can_send and stage:
        return {
            "next_action": "approve_send",
            "next_action_label": f"Aprobar {stage}",
            "action_reason": "Cumple senales y separacion minima; queda pendiente tu aprobacion.",
            "expected_state": "follow-up enviado; esperar respuesta/demo",
            "requires_approval": True,
        }
    if priority == 1:
        return {
            "next_action": "manual_contact",
            "next_action_label": "Contactar hoy",
            "action_reason": blocked_reason or "Alta intencion detectada.",
            "expected_state": "respuesta, consulta o piloto",
            "requires_approval": False,
        }
    if not stage:
        return {
            "next_action": "stop",
            "next_action_label": "No insistir",
            "action_reason": blocked_reason or "Secuencia completada.",
            "expected_state": "sin siguiente contacto",
            "requires_approval": False,
        }
    if str(blocked_reason).startswith("esperar"):
        return {
            "next_action": "wait",
            "next_action_label": blocked_reason,
            "action_reason": "Aun no toca otro email.",
            "expected_state": "revisar en proximo scoring",
            "requires_approval": False,
        }
    return {
        "next_action": "review",
        "next_action_label": "Revisar",
        "action_reason": blocked_reason or "Necesita revision manual.",
        "expected_state": "decidir si avanzar o pausar",
        "requires_approval": False,
    }


def _outreach_followup_item(
    row: sqlite3.Row,
    followup_days: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    signals = {
        "opens": int(row["opens"] or 0),
        "clicks": int(row["clicks"] or 0),
        "demos": int(row["demos"] or 0),
        "reply_intents": int(row["reply_intents"] or 0),
        "replies": int(row["replies"] or 0),
    }
    status_value = row["status"] or "new"
    high_intent = (
        signals["demos"] > 0
        or signals["clicks"] > 0
        or signals["reply_intents"] > 0
        or signals["replies"] > 0
        or status_value in ("engaged", "replied", "client")
    )
    if high_intent:
        priority = 1
        priority_label = "Prioridad 1"
        reason = "demo/click/respuesta"
    elif signals["opens"] > 0:
        priority = 2
        priority_label = "Prioridad 2"
        reason = "abrio el email"
    elif row["last_sent_at"]:
        priority = 3
        priority_label = "Prioridad 3"
        reason = "cold enviado sin senales"
    else:
        priority = 3
        priority_label = "Prioridad 3"
        reason = "sin contacto reciente"

    prospect = _outreach_prospect_from_row(row)
    next_stage = _outreach_next_stage(row)
    can_send, blocked_reason = _outreach_autopilot_gate(row, priority, next_stage, followup_days)
    demo_stage = next_stage or ("fu1" if priority in (1, 2) else "breakup")
    demo_url = outreach_demo_url_with_utm(demo_stage, prospect)
    subject = _outreach_followup_subject(row, priority)
    body = _outreach_followup_body(row, priority, signals, demo_url)
    action = _outreach_action_for_item(row, priority, next_stage, can_send, blocked_reason, signals)
    return {
        "email": row["email"],
        "business_name": row["business_name"] or "",
        "contact_name": row["contact_name"] or "",
        "niche": row["niche"] or "",
        "city": row["city"] or "",
        "phone": row["phone"] or "",
        "website": row["website"] or "",
        "status": status_value,
        "last_sent_at": row["last_sent_at"] or "",
        "last_event_at": row["last_event_at"] or "",
        "contact_count": int(row["total_sent"] or 0),
        "priority": priority,
        "priority_label": priority_label,
        "reason": reason,
        "signals": signals,
        "recommended_stage": next_stage,
        "can_send": can_send,
        "blocked_reason": blocked_reason,
        "needs_human": priority == 1,
        "demo_url": demo_url,
        "subject": subject,
        "body_text": body,
        "suggested_message": f"Asunto: {subject}\n\n{body}",
        "mailto": f"mailto:{quote(row['email'] or '')}?subject={quote(subject)}&body={quote(body)}",
        **action,
    }


def _outreach_autopilot_summary(queue: Dict[str, Any]) -> Dict[str, Any]:
    items = list(queue.get("items") or [])
    followup_days = _outreach_normalize_followup_days(queue.get("followup_days"))
    approval_groups: Dict[str, List[str]] = {}
    for item in items:
        stage = item.get("recommended_stage") or ""
        if item.get("can_send") and stage:
            approval_groups.setdefault(stage, []).append(item["email"])
    p1 = [item for item in items if int(item.get("priority") or 0) == 1]
    ready = [item for item in items if item.get("can_send")]
    today_plan = [
        item for item in items
        if item.get("next_action") in ("manual_reply", "manual_contact", "approve_send")
    ][:10]
    if not today_plan:
        today_plan = (p1[:10] or ready[:10] or items[:10])
    next_best = today_plan
    manual_count = len([item for item in items if item.get("next_action") in ("manual_reply", "manual_contact")])
    return {
        "window_days": queue.get("window_days", 0),
        "total": queue.get("total", 0),
        "counts": queue.get("counts", {}),
        "p1_alerts": p1[:20],
        "p1_count": len(p1),
        "ready_to_approve": len(ready),
        "manual_needed": manual_count,
        "approval_groups": approval_groups,
        "followup_days": followup_days,
        "today_plan": today_plan,
        "next_best": next_best,
        "rules": {
            "fu1": f"Enviar/aprobar cuando hubo cold previo, no hay respuesta y pasaron {followup_days['fu1']} dias.",
            "fu2": f"Enviar/aprobar cuando fu1 ya salio, no hay respuesta y pasaron {followup_days['fu2']} dias desde el ultimo envio.",
            "breakup": f"Enviar/aprobar cuando fu2 ya salio, no hay respuesta y pasaron {followup_days['breakup']} dias desde el ultimo envio.",
            "hot_lead": "Marcar como P1 si hay demo generada, click, intento de respuesta, respuesta o estado engaged.",
            "manual": "Intervenir personalmente si es P1, si ya respondio o si hay demo/click reciente.",
            "stop": "No contactar mas si completo la secuencia, esta dado de baja, respondio con estado final, es cliente o perdido.",
            "safeguards": f"Maximo {OUTREACH_MAX_TOUCHES_PER_PROSPECT} contactos por prospect, separacion minima por etapa, sin bajas, sin estados finales y sin envio automatico desde Autopiloto.",
        },
        "daily_brief": (
            f"{len(p1)} P1 requieren atencion. "
            f"{len(ready)} follow-ups estan listos para aprobar. "
            f"{manual_count} necesitan toque manual. "
            "No se enviara nada sin confirmacion manual."
        ),
    }


def _autopilot_config_row(conn) -> Dict[str, Any]:
    _outreach_ensure_autopilot_config_columns(conn)
    row = conn.execute("SELECT * FROM autopilot_config WHERE id=1").fetchone()
    if not row:
        conn.execute("INSERT OR IGNORE INTO autopilot_config (id) VALUES (1)")
        conn.commit()
        row = conn.execute("SELECT * FROM autopilot_config WHERE id=1").fetchone()
    try:
        targets = json.loads(row["targets_json"] or "[]")
    except Exception:
        targets = []
    followup_days = _outreach_normalize_followup_days(row["followup_days_json"] if "followup_days_json" in row.keys() else None)
    sent_today = conn.execute(
        "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND stage='cold' AND date(sent_at)=date('now')"
    ).fetchone()["c"]
    imported_24h = conn.execute(
        "SELECT COUNT(*) AS c FROM prospects WHERE (source LIKE '%autopilot%' OR tags LIKE '%autopilot%') AND created_at >= datetime('now','-1 day')"
    ).fetchone()["c"]
    valid_candidates = conn.execute(
        """
        SELECT COUNT(*) AS c FROM prospects
        WHERE (source LIKE '%autopilot%' OR tags LIKE '%autopilot%')
          AND email <> '' AND website <> ''
          AND email NOT IN (SELECT email FROM suppressions)
          AND email NOT IN (SELECT email FROM sends WHERE mode='send')
        """
    ).fetchone()["c"]
    pending_followups = conn.execute(
        """
        SELECT COUNT(DISTINCT p.email) AS c
        FROM prospects p
        JOIN sends s ON s.email = p.email AND s.mode='send'
        WHERE (p.source LIKE '%autopilot%' OR p.tags LIKE '%autopilot%')
          AND COALESCE(p.status,'') NOT IN ('replied','client','lost')
          AND p.email NOT IN (SELECT email FROM suppressions)
        """
    ).fetchone()["c"]
    sent_24h = conn.execute(
        "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND sent_at >= datetime('now','-1 day')"
    ).fetchone()["c"]
    followups_24h = conn.execute(
        "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND stage IN ('fu1','fu2','breakup') AND sent_at >= datetime('now','-1 day')"
    ).fetchone()["c"]
    replies_30d = conn.execute(
        "SELECT COUNT(DISTINCT email) AS c FROM events WHERE type='reply' AND ts >= datetime('now','-30 day')"
    ).fetchone()["c"]
    clicks_30d = conn.execute(
        "SELECT COUNT(*) AS c FROM events WHERE type='click' AND ts >= datetime('now','-30 day')"
    ).fetchone()["c"]
    smtp_configured = bool(_outreach_dedicated_smtp_config()) or emailing._email_delivery_configured()
    smtp_health = _outreach_smtp_health()
    smtp_ok = smtp_configured and smtp_health.get("ok") is not False
    env_enabled = os.getenv("OUTREACH_AUTONOMOUS_ENABLED", "").lower() == "true"
    google_ok = bool(os.getenv("GOOGLE_PLACES_API_KEY", "").strip())
    targets_count = len(targets)
    target_companies = _autopilot_target_companies(row["daily_new_target"] or 20)
    generated_targets = _autopilot_generated_targets(target_companies)
    active_targets = _autopilot_targets_for_run(targets, target_companies)
    enabled_db = bool(row["enabled"])
    pause = _outreach_pause_state(conn)
    exhausted_targets = _outreach_exhausted_targets(conn)
    effective_cap = _outreach_warmup_effective_cap(conn, int(row["daily_cold_cap"] or 20))
    try:
        discovery_enabled = bool(row["discovery_enabled"]) if "discovery_enabled" in row.keys() else True
    except Exception:
        discovery_enabled = True
    blockers: List[str] = []
    if not env_enabled:
        blockers.append("OUTREACH_AUTONOMOUS_ENABLED no está 'true' en el VPS")
    if not enabled_db:
        blockers.append("Modo automático pausado en el panel")
    if pause["auto"]:
        blockers.append(f"Pausa automática hasta {pause['until']} ({pause['reason']}) — se reanuda sola")
    if not smtp_configured:
        blockers.append("No hay canal de email conectado (Gmail o SMTP)")
    elif smtp_health.get("ok") is False:
        blockers.append(f"SMTP caído: {smtp_health.get('error', '')[:120]}")
    # Sin GOOGLE_PLACES_API_KEY el discovery usa OpenStreetMap (gratis): no es blocker.
    tick_state = _outreach_tick_state_snapshot()
    return {
        "enabled": enabled_db,
        "paused_until": pause["until"] if pause["auto"] else "",
        "paused_reason": pause["reason"] if pause["auto"] else "",
        "auto_paused": pause["auto"],
        "smtp_health": smtp_health,
        "effective_daily_cap": effective_cap,
        "exhausted_targets": sorted(exhausted_targets.keys()),
        "targets": targets,
        "generated_targets": generated_targets,
        "active_targets": active_targets,
        "target_companies": target_companies,
        "daily_new_target": target_companies,
        "daily_cold_cap": int(row["daily_cold_cap"] or target_companies),
        "auto_followups": bool(row["auto_followups"]),
        "discovery_enabled": discovery_enabled,
        "followup_days": followup_days,
        "last_discovery_at": row["last_discovery_at"] or "",
        "last_cold_at": row["last_cold_at"] or "",
        "updated_at": row["updated_at"] or "",
        "env_enabled": env_enabled,
        "smtp_ok": smtp_ok,
        "google_places_ok": google_ok,
        "targets_count": len(active_targets),
        "manual_targets_count": targets_count,
        "auto_targets_enabled": targets_count == 0,
        "ready": (env_enabled and enabled_db and smtp_ok),
        "blockers": blockers,
        "active_tick": tick_state if outreach_autonomous_tick_lock.locked() else None,
        "last_tick": tick_state or None,
        "stats": {
            "cold_today": sent_today,
            "imported_24h": imported_24h,
            "valid_candidates": valid_candidates,
            "pending_followups": pending_followups,
            "sent_24h": sent_24h,
            "followups_24h": followups_24h,
            "replies_30d": replies_30d,
            "clicks_30d": clicks_30d,
        },
    }


def _outreach_admin_preview_html(html: str) -> str:
    """Evita que las previews del panel admin disparen opens/clicks reales."""
    if not html:
        return html

    def _unwrap_tracking_link(match: re.Match[str]) -> str:
        quote_char = match.group(1)
        href = match.group(2)
        parsed = urlparse(href)
        query = parsed.query or ""
        target = ""
        for part in query.split("&"):
            key, _, value = part.partition("=")
            if key == "u":
                target = unquote(value)
                break
        if not target:
            return match.group(0)
        return f'href={quote_char}{escape(target, quote=True)}{quote_char}'

    cleaned = re.sub(
        r'<img\b[^>]*src=["\'][^"\']*/track/open/[^"\']+["\'][^>]*>',
        "",
        html,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r'href=(["\'])([^"\']*/track/(?:click|reply)/[^"\']*)\1',
        _unwrap_tracking_link,
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def _outreach_preflight_auth_status(settings_row: Dict[str, object]) -> Dict[str, Any]:
    from_email = str(settings_row.get("from_email") or "").strip().lower()
    smtp_user = str(settings_row.get("username") or "").strip().lower()
    from_domain = from_email.rsplit("@", 1)[-1] if "@" in from_email else ""
    smtp_domain = smtp_user.rsplit("@", 1)[-1] if "@" in smtp_user else ""
    aligned = bool(from_domain and smtp_domain and from_domain == smtp_domain)
    return {
        "spf": {
            "status": "ok" if aligned else "warning",
            "message": "Dominio del remitente alineado con SMTP." if aligned else "El dominio del remitente no coincide claramente con el usuario SMTP.",
        },
        "dkim": {
            "status": "ok" if from_domain else "unknown",
            "message": f"DKIM depende del proveedor para {from_domain or 'el dominio remitente'}; no se firma localmente.",
        },
        "dmarc": {
            "status": "ok" if aligned else "unknown",
            "message": "DMARC deberia alinear si SPF/DKIM pasan con el dominio remitente." if aligned else "No se puede confirmar DMARC solo con la configuracion local.",
        },
    }


def _outreach_unfilled_vars(*parts: str) -> List[str]:
    found: Set[str] = set()
    for part in parts:
        for match in re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", part or ""):
            found.add(match)
    return sorted(found)


def _outreach_campaign_metrics(conn: sqlite3.Connection, campaign_id: int) -> Dict[str, int]:
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM campaign_members WHERE campaign_id=?",
        (campaign_id,),
    ).fetchone()["c"]
    sent = conn.execute(
        "SELECT COUNT(*) AS c FROM campaign_members WHERE campaign_id=? AND status='sent'",
        (campaign_id,),
    ).fetchone()["c"]
    skipped = conn.execute(
        "SELECT COUNT(*) AS c FROM campaign_members WHERE campaign_id=? AND status='skipped'",
        (campaign_id,),
    ).fetchone()["c"]
    errors = conn.execute(
        "SELECT COUNT(*) AS c FROM campaign_members WHERE campaign_id=? AND status='error'",
        (campaign_id,),
    ).fetchone()["c"]
    suppressed = conn.execute(
        """SELECT COUNT(*) AS c
           FROM campaign_members cm
           JOIN suppressions s ON s.email=cm.email
           WHERE cm.campaign_id=?""",
        (campaign_id,),
    ).fetchone()["c"]
    opens = conn.execute(
        """SELECT COUNT(DISTINCT e.email) AS c
           FROM campaign_members cm
           JOIN events e ON e.email=cm.email AND e.type='open'
           WHERE cm.campaign_id=?""",
        (campaign_id,),
    ).fetchone()["c"]
    clicks = conn.execute(
        """SELECT COUNT(DISTINCT e.email) AS c
           FROM campaign_members cm
           JOIN events e ON e.email=cm.email AND e.type='click'
           WHERE cm.campaign_id=?""",
        (campaign_id,),
    ).fetchone()["c"]
    replies = conn.execute(
        """SELECT COUNT(DISTINCT e.email) AS c
           FROM campaign_members cm
           JOIN events e ON e.email=cm.email AND e.type='reply'
           WHERE cm.campaign_id=?""",
        (campaign_id,),
    ).fetchone()["c"]
    return {
        "total": int(total or 0),
        "sent": int(sent or 0),
        "pending": max(0, int(total or 0) - int(sent or 0) - int(skipped or 0) - int(errors or 0)),
        "skipped": int(skipped or 0),
        "errors": int(errors or 0),
        "suppressed": int(suppressed or 0),
        "opens": int(opens or 0),
        "clicks": int(clicks or 0),
        "replies": int(replies or 0),
    }


def _outreach_backfill_orphan_send_campaigns(conn: sqlite3.Connection) -> int:
    """Materializa envios reales antiguos sin campana para que aparezcan en el panel."""
    rows = conn.execute(
        """SELECT s.*
           FROM sends s
           JOIN (
               SELECT email, MAX(id) AS id
               FROM sends
               WHERE mode='send' AND COALESCE(campaign_id,0)=0
               GROUP BY email
           ) latest ON latest.id=s.id
           WHERE NOT EXISTS (
               SELECT 1 FROM campaign_members cm WHERE cm.email=s.email
           )
           ORDER BY s.sent_at ASC, s.id ASC"""
    ).fetchall()
    by_stage: Dict[str, List[sqlite3.Row]] = {}
    for row in rows:
        email = (row["email"] or "").strip().lower()
        stage = row["stage"] or "cold"
        if not email or "@" not in email or stage not in OUTREACH_STAGES:
            continue
        by_stage.setdefault(stage, []).append(row)

    created = 0
    sender = str(outreach_smtp_settings().get("from_email") or "")
    for stage in OUTREACH_STAGES:
        stage_rows = by_stage.get(stage) or []
        if not stage_rows:
            continue
        now = _outreach_now()
        first_sent = min((r["sent_at"] or now) for r in stage_rows)
        last_sent = max((r["sent_at"] or now) for r in stage_rows)
        name = f"Emails {stage} lanzados ({len(stage_rows)})"
        cur = conn.execute(
            """INSERT INTO campaigns
               (name, status, stage, template_stage, sender, delay, jitter, force_window, tracking, job_id,
                created_at, updated_at, last_sent_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, "completed", stage, stage, sender, 0, 0, 0, 0, 0, first_sent, now, last_sent),
        )
        campaign_id = int(cur.lastrowid)
        for row in stage_rows:
            email = (row["email"] or "").strip().lower()
            conn.execute(
                """INSERT OR IGNORE INTO campaign_members
                   (campaign_id, email, stage, status, last_send_id, last_sent_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (campaign_id, email, stage, "sent", int(row["id"]), row["sent_at"] or "", first_sent, now),
            )
            conn.execute(
                "UPDATE sends SET campaign_id=? WHERE id=? AND COALESCE(campaign_id,0)=0",
                (campaign_id, int(row["id"])),
            )
        created += 1
    if created:
        conn.commit()
    return created


def _outreach_create_campaign(
    conn: sqlite3.Connection,
    *,
    name: str,
    stage: str,
    emails: List[str],
    settings_row: Dict[str, object],
    delay: float,
    jitter: float,
    force_window: bool,
    status: str = "draft",
    job_id: int = 0,
    skip_existing: bool = False,
) -> int:
    now = _outreach_now()
    unique_emails = list(dict.fromkeys(email.lower().strip() for email in emails if email and "@" in email))
    if unique_emails:
        placeholders = ",".join("?" for _ in unique_emails)
        existing = conn.execute(
            f"""SELECT cm.email, cm.campaign_id, c.name AS campaign_name, c.status
                FROM campaign_members cm
                LEFT JOIN campaigns c ON c.id=cm.campaign_id
                WHERE cm.email IN ({placeholders})""",
            unique_emails,
        ).fetchall()
        if existing:
            if skip_existing:
                existing_set = {r["email"] for r in existing}
                unique_emails = [email for email in unique_emails if email not in existing_set]
                settings.logger.warning(
                    "_outreach_create_campaign skip_existing: omitidos %d emails ya en campana",
                    len(existing_set),
                )
            else:
                examples = ", ".join(
                    f"{r['email']} ({r['campaign_name'] or 'campana #' + str(r['campaign_id'])})"
                    for r in existing[:5]
                )
                raise HTTPException(
                    status_code=409,
                    detail=f"{len(existing)} email(s) ya pertenecen a otra campana: {examples}",
                )
    sender = str(settings_row.get("from_email") or "")
    tracking = int(bool((not OUTREACH_TRACKING_DISABLED) and OUTREACH_TRACKING_SECRET and OUTREACH_TRACKING_BASE_URL))
    cur = conn.execute(
        """INSERT INTO campaigns
           (name, status, stage, template_stage, sender, delay, jitter, force_window, tracking, job_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name.strip() or f"Campana {now[:10]}", status, stage, stage, sender, float(delay), float(jitter), int(force_window), tracking, int(job_id), now, now),
    )
    campaign_id = int(cur.lastrowid)
    for email in unique_emails:
        conn.execute(
            """INSERT INTO campaign_members
               (campaign_id, email, stage, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (campaign_id, email, stage, "pending", now, now),
        )
    return campaign_id


def _outreach_campaign_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    data["metrics"] = _outreach_campaign_metrics(conn, int(row["id"]))
    return data


def _job_log(conn: sqlite3.Connection, job_id: int, line: str) -> None:
    try:
        conn.execute(
            "UPDATE jobs SET log = COALESCE(log,'') || ? WHERE id=?",
            (f"[{_outreach_now()}] {line}\n", job_id),
        )
        conn.commit()
    except Exception:
        pass


def _job_finish(conn: sqlite3.Connection, job_id: int, status: str) -> None:
    conn.execute(
        "UPDATE jobs SET status=?, finished_at=? WHERE id=?",
        (status, _outreach_now(), job_id),
    )
    conn.commit()


# --- SMTP dedicado de captacion (RF-4.7) -----------------------------------
# El cold NUNCA deberia salir por el mismo canal que el email transaccional del
# SaaS (incidente ago-2026: MailChannels/Hostinger bloquea el contenido de cold
# con "550 [SDC] Blocked" aunque el transaccional pase). Con OUTREACH_SMTP_HOST
# configurado, la captacion usa su propio buzon/proveedor sin tocar codigo.


def _outreach_dedicated_smtp_config() -> Optional[Dict[str, Any]]:
    host = os.getenv("OUTREACH_SMTP_HOST", "").strip()
    if not host:
        return None
    try:
        port = int(os.getenv("OUTREACH_SMTP_PORT", "587") or 587)
    except Exception:
        port = 587
    return {
        "host": host,
        "port": port,
        "username": os.getenv("OUTREACH_SMTP_USERNAME", "").strip(),
        "password": os.getenv("OUTREACH_SMTP_PASSWORD", "").strip(),
        "starttls": os.getenv("OUTREACH_SMTP_STARTTLS", "true").strip().lower()
        in {"1", "true", "yes", "on"},
    }


def _outreach_send_email_object(msg) -> None:
    """Envia un email de captacion: SMTP dedicado si esta configurado, si no el canal global."""
    cfg = _outreach_dedicated_smtp_config()
    if not cfg:
        emailing._send_email_object(msg)
        return
    import smtplib

    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as smtp:
        smtp.ehlo()
        if cfg["starttls"]:
            smtp.starttls()
            smtp.ehlo()
        if cfg["username"]:
            smtp.login(cfg["username"], cfg["password"])
        smtp.send_message(msg)


def _outreach_smtp_health() -> Dict[str, Any]:
    """Salud del canal de envio de CAPTACION: el dedicado si existe, si no el global."""
    cfg = _outreach_dedicated_smtp_config()
    if not cfg:
        return emailing._smtp_health_check()
    import smtplib

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as smtp:
            smtp.ehlo()
            if cfg["starttls"]:
                smtp.starttls()
                smtp.ehlo()
            if cfg["username"]:
                smtp.login(cfg["username"], cfg["password"])
            smtp.noop()
        return {"ok": True, "error": "", "checked_at": _outreach_now(), "dedicated": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300], "checked_at": _outreach_now(), "dedicated": True}


# --- Ritmo de envio seguro -------------------------------------------------
# Espaciado GLOBAL entre emails, compartido por todos los jobs (cold + follow-ups
# corren en hilos paralelos; sin esto el espaciado por-job se divide entre hilos:
# el 15-jul salieron 11 emails en 6 min y Hostinger devolvio rate limit).

_outreach_send_slot_lock = threading.Lock()
_outreach_last_send_monotonic: List[float] = [0.0]


def _outreach_send_spacing_seconds() -> float:
    try:
        lo = float(os.getenv("OUTREACH_SEND_SPACING_MIN_SEC", "120") or 120)
        hi = float(os.getenv("OUTREACH_SEND_SPACING_MAX_SEC", "300") or 300)
    except Exception:
        lo, hi = 120.0, 300.0
    if hi < lo:
        hi = lo
    return random.uniform(lo, hi)


def _outreach_wait_send_slot(sleep_fn=time.sleep) -> float:
    """Bloquea hasta que toque el siguiente hueco de envio global. Devuelve lo esperado."""
    spacing = _outreach_send_spacing_seconds()
    with _outreach_send_slot_lock:
        now = time.monotonic()
        earliest = _outreach_last_send_monotonic[0] + spacing
        wait_for = max(0.0, earliest - now)
        _outreach_last_send_monotonic[0] = max(now, earliest)
    if wait_for > 0:
        sleep_fn(wait_for)
    return wait_for


def _outreach_warmup_effective_cap(conn: sqlite3.Connection, configured_cap: int, today: Optional[datetime] = None) -> int:
    """Cap diario efectivo con warm-up: tras >7 dias sin enviar, arranca en 10/dia
    y sube +5 por semana de envio continuado, hasta min(configured_cap, 30)."""
    hard_top = min(max(1, int(configured_cap or 20)), 30)
    now_date = (today or datetime.now(timezone.utc)).date()
    try:
        rows = conn.execute(
            "SELECT DISTINCT date(sent_at) AS d FROM sends WHERE mode='send' "
            "AND sent_at >= datetime('now','-90 days') ORDER BY d DESC"
        ).fetchall()
    except Exception:
        return 10
    send_days = [r["d"] for r in rows if r["d"]]
    if not send_days:
        return min(10, hard_top)
    last_send = datetime.strptime(send_days[0], "%Y-%m-%d").date()
    if (now_date - last_send).days > 7:
        return min(10, hard_top)
    # Buscar el arranque de la racha actual: primer dia sin hueco de >7 dias
    streak_start = last_send
    prev = last_send
    for d in send_days[1:]:
        day = datetime.strptime(d, "%Y-%m-%d").date()
        if (prev - day).days > 7:
            break
        streak_start = day
        prev = day
    weeks = max(0, (now_date - streak_start).days // 7)
    return min(10 + 5 * weeks, hard_top)


def _outreach_smtp_ratelimit_reason(exc: BaseException) -> str:
    raw = str(exc)
    msg = raw.lower()
    if (
        "ratelimit" in msg
        or "rate limit" in msg
        or "too many" in msg
        or "quota" in msg
        or "throttl" in msg
        or "hostinger_out_ratelimit" in msg
        or ("451" in msg and ("limit" in msg or "temporar" in msg))
    ):
        return raw[:300]
    return ""


def _outreach_madrid_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo  # type: ignore

        return datetime.now(ZoneInfo("Europe/Madrid"))
    except Exception:  # noqa: BLE001 — Python 3.8 local sin zoneinfo: UTC+2 aprox
        return datetime.now(timezone.utc) + timedelta(hours=2)


def _outreach_next_business_day_9h_utc() -> datetime:
    """Siguiente dia laborable a las 9:00 Europe/Madrid, devuelto en UTC."""
    local = _outreach_madrid_now()
    candidate = local.replace(hour=9, minute=0, second=0, microsecond=0)
    if local.hour >= 9:
        candidate = candidate + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _outreach_pause_state(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Estado de pausa: {'manual': bool, 'auto': bool, 'until': str, 'reason': str, 'expired': bool}."""
    state = {"manual": False, "auto": False, "until": "", "reason": "", "expired": False}
    try:
        _outreach_ensure_autopilot_config_columns(conn)
        row = conn.execute(
            "SELECT enabled, paused_until, paused_reason FROM autopilot_config WHERE id=1"
        ).fetchone()
        if not row:
            return state
        state["manual"] = not bool(row["enabled"])
        until_raw = str(row["paused_until"] or "")
        state["until"] = until_raw
        state["reason"] = str(row["paused_reason"] or "")
        if until_raw:
            until_dt = _outreach_parse_dt(until_raw)
            if until_dt and until_dt > datetime.now(timezone.utc):
                state["auto"] = True
            elif until_dt:
                state["expired"] = True
    except Exception:
        pass
    return state


def _outreach_autocapture_is_paused(conn: sqlite3.Connection) -> bool:
    state = _outreach_pause_state(conn)
    return bool(state["manual"] or state["auto"])


def _outreach_set_auto_pause(conn: sqlite3.Connection, until_utc: datetime, reason: str) -> None:
    now = _outreach_now()
    try:
        conn.execute(
            "UPDATE autopilot_config SET paused_until=?, paused_reason=?, updated_at=? WHERE id=1",
            (until_utc.isoformat(timespec="seconds"), reason[:200], now),
        )
        conn.commit()
    except Exception:
        pass


def _outreach_clear_auto_pause(conn: sqlite3.Connection) -> None:
    now = _outreach_now()
    try:
        conn.execute(
            "UPDATE autopilot_config SET paused_until='', paused_reason='', updated_at=? WHERE id=1",
            (now,),
        )
        conn.commit()
    except Exception:
        pass


def _outreach_ratelimit_streak_days(conn: sqlite3.Connection, register_today: bool = False) -> int:
    """Dias distintos (consecutivos hacia atras) con rate limit. Opcionalmente registra hoy."""
    try:
        row = conn.execute("SELECT ratelimit_days_json FROM autopilot_config WHERE id=1").fetchone()
        days = json.loads((row["ratelimit_days_json"] if row else "[]") or "[]")
    except Exception:
        days = []
    today = datetime.now(timezone.utc).date()
    if register_today and today.isoformat() not in days:
        days.append(today.isoformat())
        days = sorted(days)[-10:]
        try:
            conn.execute(
                "UPDATE autopilot_config SET ratelimit_days_json=? WHERE id=1",
                (json.dumps(days),),
            )
            conn.commit()
        except Exception:
            pass
    streak = 0
    cursor = today
    day_set = set(days)
    while cursor.isoformat() in day_set:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


def _outreach_notify_admin(subject: str, text_body: str, html_body: str = "") -> bool:
    """Email de aviso al dueño. Best-effort; si falla, se encola para reintento."""
    to_email = settings.CONSULTA_NOTIFICATION_EMAIL
    if not to_email:
        return False
    try:
        emailing._send_email_message(to_email, subject, text_body, html_body or "")
        return True
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Aviso de captacion no enviado (%s); encolado", exc)
        try:
            with _outreach_db() as conn:
                _outreach_ensure_notify_queue(conn)
                conn.execute(
                    "INSERT INTO notify_queue (kind, subject, body_text, body_html, created_at) VALUES (?,?,?,?,?)",
                    ("admin_alert", subject[:300], text_body, html_body or "", _outreach_now()),
                )
                conn.commit()
        except Exception:
            pass
        return False


def _outreach_ensure_notify_queue(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS notify_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL DEFAULT 'admin_alert',
            subject TEXT NOT NULL DEFAULT '',
            body_text TEXT NOT NULL DEFAULT '',
            body_html TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            sent_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )"""
    )


def _outreach_flush_notify_queue(conn: sqlite3.Connection, max_items: int = 10) -> int:
    """Reintenta avisos encolados. Devuelve cuantos salieron."""
    _outreach_ensure_notify_queue(conn)
    rows = conn.execute(
        "SELECT * FROM notify_queue WHERE sent_at='' AND attempts < 20 ORDER BY id ASC LIMIT ?",
        (max_items,),
    ).fetchall()
    sent = 0
    for row in rows:
        try:
            emailing._send_email_message(
                settings.CONSULTA_NOTIFICATION_EMAIL,
                row["subject"],
                row["body_text"],
                row["body_html"] or "",
            )
            conn.execute(
                "UPDATE notify_queue SET sent_at=? WHERE id=?", (_outreach_now(), row["id"])
            )
            sent += 1
        except Exception:  # noqa: BLE001
            conn.execute(
                "UPDATE notify_queue SET attempts=attempts+1 WHERE id=?", (row["id"],)
            )
            break  # SMTP sigue caido: no insistir con el resto en esta pasada
    conn.commit()
    return sent


def _outreach_pause_autocapture_for_smtp_limit(
    conn: sqlite3.Connection,
    *,
    reason: str,
    job_id: int = 0,
    campaign_id: int = 0,
    email: str = "",
    stage: str = "",
) -> None:
    """Rate limit SMTP → pausa CON VENCIMIENTO (no permanente) + auto-reanudacion.

    - Normal: pausa hasta el siguiente dia laborable a las 9h (Madrid).
    - 3+ dias seguidos con rate limit: pausa 72h + aviso al dueño.
    La pausa manual del panel (enabled=0) es otra cosa y no se toca aqui.
    """
    now = _outreach_now()
    streak = _outreach_ratelimit_streak_days(conn, register_today=True)
    if streak >= 3:
        until = datetime.now(timezone.utc) + timedelta(hours=72)
        reason_label = f"Rate limit SMTP {streak} dias seguidos (pausa 72h)"
        _outreach_notify_admin(
            "Captacion Vantelia pausada 72h (rate limit SMTP persistente)",
            f"El SMTP ha devuelto rate limit {streak} dias seguidos.\n"
            f"La captacion queda pausada hasta {until.isoformat(timespec='seconds')} y se reanudara sola.\n"
            f"Ultimo error: {reason[:300]}\n\n"
            "Si persiste, revisa el limite de envio del buzon en Hostinger o configura un SMTP dedicado de captacion.",
        )
    else:
        until = _outreach_next_business_day_9h_utc()
        reason_label = "Rate limit SMTP (reanudacion automatica)"
    _outreach_set_auto_pause(conn, until, reason_label)
    detail = {
        "reason": reason[:300],
        "job_id": job_id,
        "campaign_id": campaign_id,
        "email": email,
        "stage": stage,
        "paused_until": until.isoformat(timespec="seconds"),
        "streak_days": streak,
    }
    try:
        conn.execute(
            "UPDATE campaigns SET status='paused', updated_at=? WHERE status='running'",
            (now,),
        )
        conn.commit()
    except Exception:
        pass
    _outreach_tick_state_update(
        "smtp_ratelimit_paused",
        f"Rate limit SMTP: pausado hasta {until.isoformat(timespec='seconds')} (se reanuda solo)",
        detail=detail,
        status="error",
    )
    _autopilot_log(
        "error",
        "smtp_ratelimit_autopause",
        f"Rate limit SMTP: captacion pausada hasta {until.strftime('%d/%m %H:%M')} UTC, se reanuda sola",
        detail,
    )


def _outreach_run_autopilot_job(job_id: int, params: dict) -> None:
    """Hilo en background: envía follow-ups pendientes (fu1→fu2→breakup) hasta max total."""
    db_path = Path(os.getenv("OUTREACH_DB_PATH", str(OUTREACH_DEFAULT_DB)))
    try:
        conn = outreach_connect(db_path)
    except Exception as err:
        settings.logger.error(f"Autopilot job {job_id} sin DB: {err}")
        return

    max_total = int(params.get("max", 10))
    send_real = bool(params.get("send", True))
    settings_row = outreach_smtp_settings()
    unsub = str(settings_row.get("unsubscribe_mailto") or "baja@vantelia.es")
    is_autopilot = bool(params.get("autopilot"))

    try:
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        conn.commit()
        try:
            from outreach_campaign import (  # type: ignore
                load_template_overrides,
                render_with_override_and_variant,
            )
            overrides = load_template_overrides(conn, fail_closed=send_real)
        except Exception as template_err:
            _job_log(conn, job_id, f"FATAL plantillas: {template_err}")
            _job_finish(conn, job_id, "error")
            return

        sent_total = 0
        stage_days = _outreach_followup_stage_days(
            params.get("followup_days") or _outreach_config_followup_days(conn)
        )

        for stage, after_days in stage_days:
            if sent_total >= max_total:
                break
            remaining = max_total - sent_total
            candidates, assessments = _outreach_select_eligible_prospects(
                conn,
                stage,
                after_days=after_days,
                limit=remaining,
            )
            skipped_initial = sum(1 for item in assessments if not item.get("eligible"))
            if skipped_initial:
                _job_log(conn, job_id, f"{stage}: {skipped_initial} descartados por elegibilidad")
            if not candidates:
                _job_log(conn, job_id, f"{stage}: sin candidatos (after_days={after_days})")
                continue
            _job_log(conn, job_id, f"{stage}: {len(candidates)} candidatos")

            for p in candidates:
                if is_autopilot and _outreach_autocapture_is_paused(conn):
                    _job_log(conn, job_id, "Autocaptacion pausada. El job se detiene.")
                    _job_finish(conn, job_id, "done")
                    return
                if sent_total >= max_total:
                    break
                eligibility = _outreach_send_eligibility(conn, p.email, stage, after_days)
                if not eligibility["eligible"]:
                    reason = str(eligibility["reason"])
                    _job_log(conn, job_id, f"skip {p.email} ({reason})")
                    if is_autopilot:
                        _autopilot_log(
                            "info", "email_skipped", f"Saltado {p.email}: {reason}",
                            {"email": p.email, "reason": reason, "stage": stage},
                        )
                    continue
                if conn.execute("SELECT 1 FROM suppressions WHERE email=?", (p.email,)).fetchone():
                    _job_log(conn, job_id, f"skip {p.email} (baja)")
                    if is_autopilot:
                        _autopilot_log("info", "email_skipped", f"Saltado {p.email}: en lista de bajas",
                                       {"email": p.email, "reason": "suppression", "stage": stage})
                    continue
                if conn.execute("SELECT 1 FROM events WHERE email=? AND type='reply' LIMIT 1", (p.email,)).fetchone():
                    _job_log(conn, job_id, f"skip {p.email} (ya respondio)")
                    if is_autopilot:
                        _autopilot_log("info", "email_skipped", f"Saltado {p.email}: ya respondió",
                                       {"email": p.email, "reason": "already_replied", "stage": stage})
                    continue
                status_row = conn.execute("SELECT status FROM prospects WHERE email=?", (p.email,)).fetchone()
                if status_row and (status_row["status"] or "") in ("replied", "client", "lost"):
                    _job_log(conn, job_id, f"skip {p.email} (status={status_row['status']})")
                    if is_autopilot:
                        _autopilot_log("info", "email_skipped",
                                       f"Saltado {p.email}: status={status_row['status']}",
                                       {"email": p.email, "reason": f"status_{status_row['status']}", "stage": stage})
                    continue
                if conn.execute(
                    "SELECT 1 FROM sends WHERE email=? AND stage=? AND mode='send'", (p.email, stage)
                ).fetchone():
                    _job_log(conn, job_id, f"skip {p.email} ({stage} ya enviado)")
                    if is_autopilot:
                        _autopilot_log("info", "email_skipped", f"Saltado {p.email}: {stage} ya enviado",
                                       {"email": p.email, "reason": "stage_already_sent", "stage": stage})
                    continue

                subject, text, html_body, subject_variant = render_with_override_and_variant(
                    stage, p, unsub, overrides
                )
                if not OUTREACH_TRACKING_DISABLED and OUTREACH_TRACKING_SECRET and OUTREACH_TRACKING_BASE_URL:
                    html_body = outreach_apply_tracking(
                        html_body, p.email, stage,
                        OUTREACH_TRACKING_BASE_URL, OUTREACH_TRACKING_SECRET,
                    )

                in_reply_to = None
                prev_stage = OUTREACH_STAGES[OUTREACH_STAGES.index(stage) - 1]
                prev_row = conn.execute(
                    "SELECT message_id FROM sends WHERE email=? AND stage=? AND message_id<>'' ORDER BY id DESC LIMIT 1",
                    (p.email, prev_stage),
                ).fetchone()
                if prev_row and prev_row["message_id"]:
                    in_reply_to = prev_row["message_id"]

                if not send_real:
                    _job_log(conn, job_id, f"[DRY] {p.email} | {p.business_name} | {stage} | {subject}")
                    sent_total += 1
                    continue

                _outreach_wait_send_slot()
                eligibility = _outreach_send_eligibility(conn, p.email, stage, after_days)
                if not eligibility["eligible"]:
                    reason = str(eligibility["reason"])
                    _job_log(conn, job_id, f"skip {p.email} pre-SMTP ({reason})")
                    if is_autopilot:
                        _autopilot_log(
                            "info", "email_skipped", f"Saltado {p.email} antes de SMTP: {reason}",
                            {"email": p.email, "reason": reason, "stage": stage},
                        )
                    continue
                msg = outreach_build_message(p.email, subject, text, html_body, settings_row, in_reply_to=in_reply_to)
                try:
                    _outreach_send_email_object(msg)
                except Exception as send_err:  # noqa: BLE001
                    _job_log(conn, job_id, f"ERROR {p.email}: {send_err}")
                    limit_reason = _outreach_smtp_ratelimit_reason(send_err)
                    if limit_reason:
                        _job_log(conn, job_id, "RATE LIMIT SMTP detectado. Pausando autocaptacion y deteniendo job.")
                        _outreach_pause_autocapture_for_smtp_limit(
                            conn,
                            reason=limit_reason,
                            job_id=job_id,
                            email=p.email,
                            stage=stage,
                        )
                        _job_finish(conn, job_id, "error")
                        return
                    if is_autopilot:
                        _autopilot_log("error", "email_failed",
                                       f"Fallo SMTP a {p.email}: {send_err}",
                                       {"email": p.email, "stage": stage, "error": str(send_err)[:240]})
                    continue

                conn.execute(
                    "INSERT INTO sends (email, stage, subject, body_text, body_html, sent_at, mode, message_id, subject_variant)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (p.email, stage, subject, text, html_body, _outreach_now(), "send", msg["Message-ID"] or "", subject_variant or "unknown"),
                )
                conn.execute(
                    "UPDATE prospects SET status=CASE WHEN COALESCE(status,'new') IN ('','new') THEN 'contacted' ELSE status END,"
                    " updated_at=? WHERE email=?",
                    (_outreach_now(), p.email),
                )
                conn.commit()
                sent_total += 1
                _job_log(conn, job_id, f"OK {p.email} | {p.business_name} | {stage}")
                if is_autopilot:
                    _autopilot_log("success", "email_sent",
                                   f"Enviado {stage} → {p.email} ({p.business_name or '-'})",
                                   {"email": p.email, "stage": stage, "business": p.business_name or "",
                                    "subject": subject})

                # Espaciado global gestionado por _outreach_wait_send_slot antes del envio.

        _job_log(conn, job_id, f"Autopiloto completo. Enviados: {sent_total}/{max_total}")
        if is_autopilot:
            _autopilot_log(
                "success" if sent_total > 0 else "info",
                "followup_job_done",
                f"Job follow-ups #{job_id} terminado: {sent_total}/{max_total} enviados",
                {"job_id": job_id, "sent": sent_total, "max": max_total},
            )
        _job_finish(conn, job_id, "done")
    except Exception as exc:  # noqa: BLE001
        settings.logger.error(f"Autopilot job {job_id} error: {exc}")
        if is_autopilot:
            _autopilot_log("error", "followup_job_fatal", f"Job follow-ups #{job_id} fatal: {exc}",
                           {"job_id": job_id, "error": str(exc)[:240]})
        try:
            _job_finish(conn, job_id, "error")
        except Exception:
            pass


OUTREACH_AUTONOMOUS_GENERIC_PREFIXES = {
    "info", "contacto", "hola", "admin", "administracion", "recepcion",
    "cita", "citaciones", "cliente", "clientes", "soporte", "help",
    "ayuda", "reservas", "marketing", "ventas", "comercial", "rrhh", "contact",
}


OUTREACH_AUTONOMOUS_CHAIN_KEYWORDS = (
    "vivanta", "plus dental", "kivet", "sanitas", "vitaldent", "dentix",
    "donte group", "asisa", "dkv", "mapfre", "adeslas",
)


OUTREACH_AUTOPILOT_SECTORS = [
    "clinica dental",
    "clinica estetica",
    "fisioterapia",
    "centro de psicologia",
    "logopeda",
    "podologo",
    "optica",
    "clinica veterinaria",
    "centro veterinario",
    "academia de ingles",
    "academia oposiciones",
    "academia refuerzo escolar",
    "autoescuela",
    "escuela infantil",
    "guarderia",
    "taller mecanico",
    "taller chapa y pintura",
    "restaurante",
    "cafeteria",
    "hotel boutique",
    "inmobiliaria",
    "agencia de viajes",
    "asesoria fiscal",
    "asesoria laboral",
    "gestoria",
    "despacho abogados",
    "notaria",
    "arquitecto",
    "consultoria informatica",
    "agencia marketing digital",
    "peluqueria",
    "barberia",
    "centro de estetica",
    "centro depilacion laser",
    "centro de unas",
    "cerrajeria",
    "empresa de reformas",
    "empresa de mudanzas",
    "empresa de limpieza",
    "carpinteria",
    "fontaneria",
    "electricista",
    "gimnasio",
    "estudio pilates",
    "centro yoga",
    "academia danza",
    "academia musica",
    "residencia mayores",
    "centro dia mayores",
    "ayuda a domicilio",
    "clinica nutricion",
    "centro fertilidad",
    "clinica capilar",
    "ortodoncia",
    "centro auditivo",
    "tienda informatica",
    "joyeria",
    "floristeria",
    "tintoreria",
    "agencia seguros",
]


OUTREACH_AUTOPILOT_CITIES = [
    "Madrid", "Barcelona", "Valencia", "Sevilla", "Zaragoza", "Malaga", "Murcia", "Palma",
    "Las Palmas de Gran Canaria", "Bilbao", "Alicante", "Cordoba", "Valladolid", "Vigo",
    "Gijon", "Hospitalet de Llobregat", "A Coruna", "Granada", "Vitoria-Gasteiz", "Elche",
    "Oviedo", "Badalona", "Cartagena", "Terrassa", "Jerez de la Frontera", "Sabadell",
    "Mostoles", "Alcala de Henares", "Pamplona", "Fuenlabrada", "Almeria", "Leganes",
    "Donostia", "Burgos", "Santander", "Castellon de la Plana", "Albacete", "Getafe",
    "Logrono", "Badajoz", "Salamanca", "Huelva", "Lleida", "Tarragona", "Leon", "Cadiz",
    "Jaen", "Ourense", "Torrejon de Ardoz", "Alcorcon", "Reus", "Girona",
    "Santa Cruz de Tenerife", "San Sebastian de los Reyes", "Mataro", "Marbella",
    "Algeciras", "Toledo", "Caceres", "Lugo", "Pontevedra", "Roquetas de Mar",
    "Avila", "Segovia", "Merida", "Ferrol", "Manresa", "Ciudad Real", "Vilanova i la Geltru",
    "Mijas", "Estepona", "Benidorm", "Pozuelo de Alarcon", "Las Rozas", "Majadahonda",
    "Boadilla del Monte", "Rivas-Vaciamadrid", "Coslada", "San Fernando", "El Puerto de Santa Maria",
    "Chiclana de la Frontera", "Talavera de la Reina", "Lorca", "Cuenca", "Soria",
    "Teruel", "Huesca", "Guadalajara", "Palencia", "Zamora", "Vic",
]


def _autopilot_target_companies(value: Any) -> int:
    try:
        return max(1, min(200, int(value or 20)))
    except Exception:
        return 20


def _autopilot_generated_targets(target_count: int, max_targets: int = 18) -> List[Dict[str, str]]:
    """Rotacion aleatoria por toda Espana. Distinta en cada ronda.

    - Sin seed fija: cada tick saca combos diferentes.
    - Cap 2 apariciones por sector y por ciudad → reparto amplio.
    - Cubre toda Espana con ~80 ciudades y ~60 sectores B2B.
    """
    target_count = _autopilot_target_companies(target_count)
    limit = max(4, min(max_targets, max(6, target_count * 2)))
    rng = random.SystemRandom()
    all_combos = [(s, c) for s in OUTREACH_AUTOPILOT_SECTORS for c in OUTREACH_AUTOPILOT_CITIES]
    rng.shuffle(all_combos)
    max_per_sector = max(1, limit // 6)
    max_per_city = max(1, limit // 6)
    sector_count: Dict[str, int] = {}
    city_count: Dict[str, int] = {}
    combos: List[Dict[str, str]] = []
    for sector, city in all_combos:
        if sector_count.get(sector, 0) >= max_per_sector:
            continue
        if city_count.get(city, 0) >= max_per_city:
            continue
        combos.append({"sector": sector, "city": city, "auto": "spain"})
        sector_count[sector] = sector_count.get(sector, 0) + 1
        city_count[city] = city_count.get(city, 0) + 1
        if len(combos) >= limit:
            break
    return combos


def _outreach_exhausted_targets(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Combos sector|city marcados agotados: {key: {'misses': n, 'exhausted_at': ts}}."""
    try:
        _outreach_ensure_autopilot_config_columns(conn)
        row = conn.execute("SELECT exhausted_targets_json FROM autopilot_config WHERE id=1").fetchone()
        data = json.loads((row["exhausted_targets_json"] if row else "{}") or "{}")
        return {k: v for k, v in data.items() if isinstance(v, dict) and v.get("exhausted_at")}
    except Exception:
        return {}


def _outreach_register_target_result(conn: sqlite3.Connection, combo_key: str, imported: int) -> bool:
    """Registra el resultado de un combo. 2 rondas seguidas sin importables → agotado.
    Devuelve True si el combo acaba de marcarse agotado."""
    try:
        _outreach_ensure_autopilot_config_columns(conn)
        row = conn.execute("SELECT exhausted_targets_json FROM autopilot_config WHERE id=1").fetchone()
        data = json.loads((row["exhausted_targets_json"] if row else "{}") or "{}")
    except Exception:
        data = {}
    entry = data.get(combo_key) if isinstance(data.get(combo_key), dict) else {}
    newly_exhausted = False
    if imported > 0:
        data.pop(combo_key, None)
    else:
        misses = int(entry.get("misses", 0)) + 1
        entry["misses"] = misses
        if misses >= 2 and not entry.get("exhausted_at"):
            entry["exhausted_at"] = _outreach_now()
            newly_exhausted = True
        data[combo_key] = entry
    try:
        conn.execute(
            "UPDATE autopilot_config SET exhausted_targets_json=? WHERE id=1",
            (json.dumps(data),),
        )
        conn.commit()
    except Exception:
        pass
    return newly_exhausted


def _outreach_clear_exhausted_targets(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("UPDATE autopilot_config SET exhausted_targets_json='{}' WHERE id=1")
        conn.commit()
    except Exception:
        pass


def _autopilot_targets_for_run(configured_targets: List[Dict[str, str]], target_count: int) -> List[Dict[str, str]]:
    clean = []
    for target in configured_targets or []:
        sector = str(target.get("sector") or "").strip()
        city = str(target.get("city") or "").strip()
        if sector and city:
            clean.append({"sector": sector, "city": city, "manual": "1"})
    return clean or _autopilot_generated_targets(target_count)


def _autonomous_company_score(company: Any) -> int:
    email = (getattr(company, "email", "") or "").strip()
    website = (getattr(company, "website", "") or "").strip()
    phone = (getattr(company, "phone", "") or "").strip()
    name = (getattr(company, "business_name", "") or "").strip()
    niche = f"{getattr(company, 'niche', '')} {getattr(company, 'service_hint', '')}".lower()
    score = 0
    if email and "@" in email:
        score += 35
    if website.startswith(("http://", "https://")):
        score += 30
    if _autonomous_email_is_personal(email):
        score += 10
    if phone:
        score += 5
    if any(token in niche for token in ("clinic", "dental", "estet", "fisio", "academ", "taller", "restaurant", "inmobili", "asesor", "abogad", "peluquer", "veterin", "reforma")):
        score += 15
    if name and not _autonomous_is_chain(name):
        score += 5
    return min(score, 100)


def _autonomous_is_chain(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in OUTREACH_AUTONOMOUS_CHAIN_KEYWORDS)


def _autonomous_email_is_personal(email: str) -> bool:
    local = (email or "").lower().split("@", 1)[0].strip()
    if not local:
        return False
    if local in OUTREACH_AUTONOMOUS_GENERIC_PREFIXES:
        return False
    return "." in local or len(local) >= 8


def _autonomous_within_window() -> bool:
    """Mismas reglas que _outreach_within_window pero locales aquí por si no existe."""
    if (os.getenv("OUTREACH_RESPECT_WINDOW", "true").lower() != "true"):
        return True
    now = timeutils._utc_now()
    try:
        from zoneinfo import ZoneInfo
        tz_name = os.getenv("OUTREACH_TIMEZONE", "Europe/Madrid")
        now = now.astimezone(ZoneInfo(tz_name))
    except Exception:
        pass
    if os.getenv("OUTREACH_SKIP_WEEKEND", "true").lower() == "true" and now.weekday() >= 5:
        return False
    start_h = int(os.getenv("OUTREACH_START_HOUR", "9") or 9)
    end_h = int(os.getenv("OUTREACH_END_HOUR", "19") or 19)
    return start_h <= now.hour < end_h


def _outreach_autonomous_tick() -> None:
    """Una pasada del modo autónomo: discovery + cold + follow-ups."""
    if not outreach_autonomous_tick_lock.acquire(blocking=False):
        settings.logger.info("[autopilot] tick ya en curso, ignorando solapamiento")
        running_state = _outreach_tick_state_snapshot()
        _autopilot_log(
            "info",
            "tick_skipped_running",
            "Ronda omitida: ya hay otra ronda en curso",
            {"source": "worker", "running_tick": running_state},
        )
        return
    _outreach_tick_state_start("worker")
    _outreach_run_autonomous_tick_locked()


def _outreach_run_autonomous_tick_locked() -> None:
    """Ejecuta una ronda asumiendo que outreach_autonomous_tick_lock ya está adquirido."""
    try:
        _outreach_autonomous_tick_inner()
    finally:
        _outreach_tick_state_finish("done", "Ronda terminada")
        outreach_autonomous_tick_lock.release()


def _outreach_start_autonomous_tick(*, source: str = "panel", log_overlap: bool = True) -> bool:
    """Arranca una ronda en segundo plano si no hay otra en curso."""
    if not outreach_autonomous_tick_lock.acquire(blocking=False):
        if log_overlap:
            running_state = _outreach_tick_state_snapshot()
            _autopilot_log(
                "info",
                "tick_skipped_running",
                "Ronda no iniciada: ya hay otra ronda en curso",
                {"source": source, "running_tick": running_state},
            )
        return False
    state = _outreach_tick_state_start(source)
    _autopilot_log(
        "info",
        "tick_queued",
        "Ronda encolada en segundo plano",
        {"source": source, "tick": state},
    )
    try:
        threading.Thread(target=_outreach_run_autonomous_tick_locked, daemon=True).start()
    except Exception as exc:
        _outreach_tick_state_finish("error", f"No se pudo arrancar la ronda: {exc}")
        outreach_autonomous_tick_lock.release()
        _autopilot_log(
            "error",
            "tick_thread_start_failed",
            f"No se pudo arrancar la ronda: {exc}",
            {"source": source, "exception": str(exc)},
        )
        return False
    return True


def _outreach_autonomous_tick_inner() -> None:  # noqa: C901
    log = lambda msg: settings.logger.info("[autopilot] %s", msg)
    log_err = lambda msg: settings.logger.error("[autopilot] %s", msg)
    env_on = os.getenv("OUTREACH_AUTONOMOUS_ENABLED", "").lower() == "true"
    _outreach_tick_state_update("start", "Ronda iniciada")
    _autopilot_log("info", "tick_start", "▶ Ronda iniciada")
    if not env_on:
        _autopilot_log("warning", "skip_env_disabled", "OUTREACH_AUTONOMOUS_ENABLED no está en true en el VPS")
        return
    if not OUTREACH_AVAILABLE:
        _autopilot_log("error", "skip_module_unavailable", "Módulo outreach no disponible")
        return
    try:
        with _outreach_db() as conn:
            row = conn.execute("SELECT * FROM autopilot_config WHERE id=1").fetchone()
            if not row:
                _autopilot_log("warning", "skip_no_config", "Sin configuración en autopilot_config")
                return
            enabled = bool(row["enabled"])
            try:
                targets = json.loads(row["targets_json"] or "[]")
            except Exception:
                targets = []
            daily_new_target = _autopilot_target_companies(row["daily_new_target"] or 50)
            daily_cold_cap = int(row["daily_cold_cap"] or 20)
            try:
                discovery_enabled = bool(row["discovery_enabled"]) if "discovery_enabled" in row.keys() else True
            except Exception:
                discovery_enabled = True
            auto_followups = bool(row["auto_followups"])
            followup_days = _outreach_config_followup_days(conn)

        if not enabled:
            _autopilot_log("info", "skip_disabled_db", "Autopiloto pausado manualmente en el panel")
            return

        # Pausa automatica (rate limit / bounces): con vencimiento y auto-reanudacion.
        with _outreach_db() as conn:
            pause = _outreach_pause_state(conn)
            if pause["expired"]:
                _outreach_clear_auto_pause(conn)
                _autopilot_log(
                    "success", "auto_resumed",
                    f"Pausa automatica vencida ({pause['reason'] or 'sin motivo'}): captacion reanudada",
                    {"reason": pause["reason"], "until": pause["until"]},
                )
            elif pause["auto"]:
                _autopilot_log(
                    "info", "skip_auto_paused",
                    f"Pausado automaticamente hasta {pause['until']} ({pause['reason']})",
                    {"until": pause["until"], "reason": pause["reason"]},
                )
                return

        if not _autonomous_within_window():
            h_start = os.getenv("OUTREACH_START_HOUR", "9")
            h_end = os.getenv("OUTREACH_END_HOUR", "19")
            _autopilot_log("info", "skip_off_hours", f"Fuera de ventana laboral ({h_start}h–{h_end}h)")
            return

        # Ambos desactivados → nada que hacer
        if not auto_followups and not discovery_enabled:
            _autopilot_log("warning", "skip_nothing_to_do",
                           "Nada que hacer: activa al menos un checkbox (Follow-ups o Discovery)")
            _outreach_tick_state_update("nothing_to_do", "Sin acciones: activa al menos un checkbox")
            return

        _autopilot_log("info", "tick_config",
                       f"Follow-ups automáticos: {'✓' if auto_followups else '✗'}  |  "
                       f"Descubrir empresas: {'✓' if discovery_enabled else '✗'}  |  "
                       f"Empresas nuevas objetivo: {daily_new_target}",
                       {"auto_followups": auto_followups, "discovery_enabled": discovery_enabled,
                        "daily_new_target": daily_new_target})

        smtp_ok = emailing._email_delivery_configured()
        if not smtp_ok:
            _autopilot_log("warning", "smtp_not_configured", "No hay canal de email conectado")
            _outreach_tick_state_update("smtp_not_configured", "No hay canal de email conectado")
            return

        # Check REAL de SMTP (login+NOOP): si el buzon esta caido (p.ej. "Disabled
        # by user from hPanel") no lanzamos jobs y avisamos. Usa el SMTP dedicado
        # de captacion si esta configurado. Mantiene el cache de /health fresco.
        smtp_health = _outreach_smtp_health()
        if smtp_health.get("ok") is False:
            _autopilot_log(
                "error", "smtp_down",
                f"SMTP caido: {smtp_health.get('error', '')[:160]}",
                {"error": smtp_health.get("error", "")},
            )
            _outreach_tick_state_update("smtp_down", "SMTP caido: ronda omitida", status="error")
            return

        # Reintentar avisos pendientes ahora que el SMTP responde.
        try:
            with _outreach_db() as conn:
                _outreach_flush_notify_queue(conn)
        except Exception:
            pass

        # ---- PRESUPUESTO DE COLD DEL DIA (warm-up + reparto entre ticks) ----
        with _outreach_db() as conn:
            effective_cap = _outreach_warmup_effective_cap(conn, daily_cold_cap)
            cold_sent_today = conn.execute(
                "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND stage='cold' AND date(sent_at)=date('now')"
            ).fetchone()["c"]
            sent_today_all = conn.execute(
                "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND date(sent_at)=date('now')"
            ).fetchone()["c"]
            already_cold = conn.execute(
                "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND stage='cold'"
            ).fetchone()["c"]
            cold_rows = conn.execute(
                """SELECT email FROM prospects
                   WHERE COALESCE(status,'new')='new'
                     AND email NOT IN (SELECT email FROM suppressions)
                     AND email NOT IN (SELECT email FROM sends WHERE mode='send' AND stage='cold')
                   ORDER BY score DESC, created_at ASC"""
            ).fetchall()
        cold_emails = [r["email"] for r in cold_rows]
        pool_size = len(cold_emails)
        remaining_today = max(0, effective_cap - int(cold_sent_today or 0))
        # Reparto: no quemar todo el cap en la primera ronda de la manana.
        per_tick_share = min(remaining_today, max(3, (effective_cap + 2) // 3))
        # Tope diario TOTAL (cold + follow-ups): en un dominio de envio nuevo el
        # warm-up debe limitar el VOLUMEN total, no solo el cold. Multiplo del cap
        # de cold (env OUTREACH_TOTAL_DAILY_MULTIPLIER, default 4): dia 1 ~40 con
        # cap 10, hasta ~120 a warm-up pleno (cap 30).
        try:
            total_multiplier = max(1.0, float(os.getenv("OUTREACH_TOTAL_DAILY_MULTIPLIER", "4") or 4))
        except Exception:
            total_multiplier = 4.0
        total_daily_cap = int(effective_cap * total_multiplier)
        followup_budget_today = max(0, total_daily_cap - int(sent_today_all or 0))
        # Pipeline bajo: discovery primero, el cold sale despues con lo importado (RF-2.4).
        cold_deferred_for_discovery = bool(discovery_enabled and pool_size < 30)
        _autopilot_log(
            "info", "cold_budget",
            f"Cold hoy: {cold_sent_today}/{effective_cap} enviados (cap config {daily_cold_cap}, "
            f"warm-up aplicado) · esta ronda: hasta {per_tick_share} · pool: {pool_size}",
            {"effective_cap": effective_cap, "configured_cap": daily_cold_cap,
             "sent_today": int(cold_sent_today or 0), "per_tick": per_tick_share,
             "pool": pool_size, "deferred_for_discovery": cold_deferred_for_discovery},
        )

        # Guard de concurrencia: los jobs de envio duran horas (espaciado 2-5min ×
        # decenas de emails) y pueden solapar el siguiente tick. Lanzar otro job
        # mientras hay uno activo dispara envios DUPLICADOS (dos jobs drenando el
        # mismo pool). Si hay uno vivo, este tick solo hace discovery.
        with _outreach_db() as conn:
            active_job = _outreach_active_send_job(conn)
        skip_sending = active_job is not None
        if skip_sending:
            _autopilot_log(
                "info", "sending_job_active",
                f"Envio omitido: el job #{active_job} sigue activo (evita duplicados). Solo discovery esta ronda.",
                {"active_job": active_job},
            )

        # ---- PASO 1: FOLLOW-UPS (cold pendientes + fu1 + fu2 + breakup) ----
        if auto_followups and not skip_sending:
            _outreach_tick_state_update("followups_start", "Enviando cold pendientes y follow-ups...")

            launch_emails = [] if cold_deferred_for_discovery else cold_emails[:per_tick_share]
            if launch_emails:
                _autopilot_log("info", "cold_pending",
                               f"Cold: {len(launch_emails)} de {pool_size} pendientes en esta ronda "
                               f"({already_cold} ya contactados anteriormente, saltados)",
                               {"launch": len(launch_emails), "pending": pool_size, "already_cold": already_cold})
                params_cold = {
                    "stage": "cold", "emails": launch_emails, "max": len(launch_emails),
                    "send": True, "dry_run": False,
                    "force_window": False, "campaign_name": "Autopilot", "autopilot": True,
                }
                with _outreach_db() as conn:
                    cur = conn.execute(
                        "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
                        ("send", "queued", json.dumps(params_cold), "", _outreach_now()),
                    )
                    cold_job_id = int(cur.lastrowid)
                    conn.execute("UPDATE autopilot_config SET last_cold_at=?, updated_at=? WHERE id=1",
                                 (_outreach_now(), _outreach_now()))
                    conn.commit()
                threading.Thread(target=_outreach_run_send_job, args=(cold_job_id, params_cold), daemon=True).start()
                _autopilot_log("success", "cold_launched",
                               f"Cold: {len(launch_emails)} emails encolados",
                               {"job_id": cold_job_id, "count": len(launch_emails)})
                remaining_today = max(0, remaining_today - len(launch_emails))
            elif cold_deferred_for_discovery and pool_size:
                _autopilot_log("info", "cold_deferred",
                               f"Cold aplazado: pipeline bajo ({pool_size} < 30), discovery primero")
            elif not pool_size:
                _autopilot_log("info", "cold_skip",
                               f"Cold: sin prospects pendientes "
                               f"({already_cold} ya contactados anteriormente)")
            elif not remaining_today:
                _autopilot_log("info", "cold_cap_reached",
                               f"Cold: cap diario alcanzado ({cold_sent_today}/{effective_cap})")

            # FU1, FU2, Breakup: acotados al presupuesto TOTAL diario (warm-up del
            # dominio). El cold ya lanzado en esta ronda cuenta contra el total.
            fu_max = max(0, followup_budget_today - len(launch_emails))
            if fu_max <= 0:
                _autopilot_log(
                    "info", "followups_cap_reached",
                    f"Follow-ups pausados: tope diario total alcanzado "
                    f"({sent_today_all}/{total_daily_cap} enviados hoy)",
                    {"sent_today_all": int(sent_today_all or 0), "total_daily_cap": total_daily_cap},
                )
            if fu_max > 0:
                params_fu = {
                    "max": fu_max, "send": True,
                    "autopilot": True, "followup_days": followup_days,
                }
                with _outreach_db() as conn:
                    cur = conn.execute(
                        "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
                        ("autopilot", "queued", json.dumps(params_fu), "", _outreach_now()),
                    )
                    fu_job_id = int(cur.lastrowid)
                    conn.commit()
                threading.Thread(target=_outreach_run_autopilot_job, args=(fu_job_id, params_fu), daemon=True).start()
                _autopilot_log("info", "followups_launched",
                               f"FU1 / FU2 / Breakup: job lanzado (hasta {fu_max}, tope diario {total_daily_cap})",
                               {"job_id": fu_job_id, "fu_max": fu_max, "total_daily_cap": total_daily_cap})
                _outreach_tick_state_update("followups_launched", "Follow-ups lanzados en segundo plano")

        # ---- PASO 2: DISCOVERY + COLD A NUEVAS EMPRESAS ----
        if discovery_enabled:
            _outreach_tick_state_update("discovery_start", "Descubriendo empresas nuevas...")
            targets_for_run = _autopilot_targets_for_run(targets, daily_new_target)

            if not targets_for_run:
                _autopilot_log("warning", "discovery_no_targets",
                               "Discovery: sin sectores/ciudades (se usará rotación automática de España)")
                targets_for_run = _autopilot_generated_targets(daily_new_target)

        # Early-exit: si pool de cold elegibles ya cubre el objetivo, SKIP discovery
        # y pasa directo a cold. Asi el dia siguiente que se reactiva, continua donde
        # se quedo en vez de seguir descubriendo de mas.
        run_discovery = discovery_enabled
        pool_target = daily_new_target
        if run_discovery and pool_size >= pool_target and not cold_deferred_for_discovery:
            log(f"discovery skip: pool {pool_size} >= objetivo {pool_target}, pasando a cold")
            _outreach_tick_state_update(
                "discovery_pool_full",
                f"Discovery omitido: pool {pool_size} >= objetivo {pool_target}",
                detail={"pool_size": pool_size, "pool_target": pool_target},
            )
            _autopilot_log(
                "info", "discovery_pool_full",
                f"Discovery omitido: ya hay {pool_size} prospects listos para cold (objetivo {pool_target})",
                {"pool_size": pool_size, "pool_target": pool_target},
            )
            run_discovery = False

        if run_discovery:
            try:
                from outreach_discover import discover_companies  # type: ignore
            except Exception as exc:
                _autopilot_log("error", "discovery_module_error", f"Discovery: módulo no disponible ({exc})")
                discover_companies = None  # type: ignore

            if discover_companies is not None:
                imported_total = 0
                targets_attempted = 0
                new_emails: List[str] = []
                with _outreach_db() as conn:
                    known: set = {r["email"] for r in conn.execute("SELECT email FROM prospects").fetchall()}
                    suppressed: set = {r["email"] for r in conn.execute("SELECT email FROM suppressions").fetchall()}
                    exhausted = _outreach_exhausted_targets(conn)

                for t in targets_for_run:
                    if imported_total >= daily_new_target:
                        _autopilot_log("info", "discovery_budget_reached",
                                       f"Discovery: objetivo de {daily_new_target} empresas alcanzado")
                        break
                    sector = (t.get("sector") or "").strip()
                    city = (t.get("city") or "").strip()
                    if not sector or not city:
                        continue
                    combo_key = f"{sector}|{city}".lower()
                    if combo_key in exhausted:
                        continue
                    targets_attempted += 1
                    remaining = max(0, daily_new_target - imported_total)
                    _outreach_tick_state_update("discovery_run", f"Buscando: {sector} · {city}",
                                               current_target={"sector": sector, "city": city})
                    _autopilot_log("info", "discovery_run", f"Buscando: {sector} · {city}",
                                   {"sector": sector, "city": city})
                    try:
                        raw_cap = max(10, min(80, int(os.getenv("OUTREACH_DISCOVERY_RAW_MAX", "30"))))
                        scrape_cap = max(0, min(80, int(os.getenv("OUTREACH_DISCOVERY_EMAIL_SCRAPES", "8"))))
                        companies = discover_companies(
                            sector=sector, ciudad=city,
                            max_results=max(10, min(raw_cap, remaining * 3)),
                            extract_emails=True, source="auto",
                            email_target=remaining,
                            max_email_scrapes=min(scrape_cap, max(3, remaining * 2)),
                        )
                    except Exception as exc:
                        log_err(f"discovery {sector}/{city}: {exc}")
                        _autopilot_log("error", "discovery_error", f"Error en {sector}/{city}: {exc}",
                                       {"sector": sector, "city": city})
                        continue

                    found_count = len(companies)
                    with _outreach_db() as conn:
                        companies = _outreach_filter_new_discoveries(conn, companies)

                    now_iso = _outreach_now()
                    added = 0
                    min_score = int(os.getenv("OUTREACH_AUTONOMOUS_MIN_SCORE", "60") or 60)
                    with _outreach_db() as conn:
                        no_email_count = 0
                        chain_count = 0
                        duplicate_count = 0
                        for c in companies:
                            email = (getattr(c, "email", "") or "").lower().strip()
                            if not email:
                                no_email_count += 1
                                continue
                            if email in known or email in suppressed:
                                duplicate_count += 1
                                continue
                            if _autonomous_is_chain(getattr(c, "business_name", "")):
                                chain_count += 1
                                continue
                            score = _autonomous_company_score(c)
                            if score < min_score:
                                continue
                            payload = c.as_csv_row()
                            payload.update({
                                "email": email, "score": score, "now": now_iso,
                                "tags": "autopilot", "source": "autopilot",
                            })
                            try:
                                cur = conn.execute(
                                    """INSERT OR IGNORE INTO prospects
                                       (email, business_name, contact_name, niche, website, service_hint,
                                        city, phone, tags, source, score, created_at, updated_at)
                                       VALUES (:email,:business_name,:contact_name,:niche,:website,:service_hint,
                                               :city,:phone,:tags,:source,:score,:now,:now)""",
                                    payload,
                                )
                                if cur.rowcount:
                                    known.add(email)
                                    new_emails.append(email)
                                    added += 1
                            except Exception as exc:
                                log_err(f"insert {email}: {exc}")
                        conn.commit()
                    if no_email_count:
                        _autopilot_log(
                            "warning",
                            "discovery_no_email_skip",
                            f"{sector} · {city}: {no_email_count} empresas sin email descartadas",
                            {"sector": sector, "city": city, "no_email": no_email_count,
                             "total_after_dedupe": len(companies)},
                        )
                    if duplicate_count:
                        _autopilot_log(
                            "info",
                            "discovery_duplicate_skip",
                            f"{sector} · {city}: {duplicate_count} duplicados (ya en DB o suprimidos)",
                            {"sector": sector, "city": city, "duplicates": duplicate_count},
                        )
                    if chain_count:
                        _autopilot_log(
                            "info",
                            "discovery_chain_skip",
                            f"{sector} · {city}: {chain_count} descartadas por cadena conocida",
                            {"sector": sector, "city": city, "chains": chain_count},
                        )
                    log(f"discovery {sector}/{city}: {found_count} encontrados, {len(companies)} nuevos tras dedupe, {added} importados (sin_email={no_email_count}, dup={duplicate_count}, chain={chain_count})")
                    _outreach_tick_state_update(
                        "discovery_target_done",
                        f"{sector} · {city}: {len(companies)} encontrados, {added} importados",
                        detail={"sector": sector, "city": city, "found": found_count, "new_after_dedupe": len(companies), "imported": added,
                                "no_email": no_email_count, "duplicates": duplicate_count, "chains": chain_count},
                        current_target={"sector": sector, "city": city},
                        imported_total=imported_total + added,
                    )
                    _autopilot_log(
                        "success" if added > 0 else "info",
                        "discovery_target_done",
                        f"{sector} · {city}: {len(companies)} encontrados, {added} importados",
                        {"sector": sector, "city": city, "found": found_count, "new_after_dedupe": len(companies), "imported": added,
                         "no_email": no_email_count, "duplicates": duplicate_count, "chains": chain_count},
                    )
                    with _outreach_db() as conn:
                        if _outreach_register_target_result(conn, combo_key, added):
                            _autopilot_log(
                                "warning", "discovery_target_exhausted",
                                f"{sector} · {city}: agotado (2 rondas sin importables); se excluye de la rotación",
                                {"sector": sector, "city": city},
                            )
                    imported_total += added

                with _outreach_db() as conn:
                    conn.execute("UPDATE autopilot_config SET last_discovery_at=?, updated_at=? WHERE id=1",
                                 (_outreach_now(), _outreach_now()))
                    conn.commit()

                # Coste: con Places, ~1 Text Search (0.032 USD)/combo + Details
                # (0.017 USD)/importada. Sin key, OSM/Overpass = 0 USD.
                if os.getenv("GOOGLE_PLACES_API_KEY", "").strip():
                    est_cost = round(targets_attempted * 0.032 + imported_total * 0.017, 3)
                    cost_label = f"~{est_cost} USD Places"
                else:
                    est_cost = 0.0
                    cost_label = "0 USD (OpenStreetMap gratis)"
                _autopilot_log(
                    "success" if imported_total > 0 else "info",
                    "discovery_done",
                    f"Discovery: {imported_total} empresas nuevas importadas "
                    f"({targets_attempted} combos, {cost_label})",
                    {"imported_total": imported_total, "targets_attempted": targets_attempted,
                     "estimated_places_cost_usd": est_cost},
                )
                _outreach_tick_state_update("discovery_done",
                                            f"Discovery: {imported_total} empresas importadas")

                # Cold post-discovery: recién descubiertas + (si el cold se aplazó
                # por pipeline bajo) el pool que quedó pendiente. Siempre dentro
                # del presupuesto diario restante.
                launch_after_discovery = list(new_emails)
                if cold_deferred_for_discovery:
                    launch_after_discovery += [e for e in cold_emails if e not in set(new_emails)]
                launch_after_discovery = launch_after_discovery[: max(0, remaining_today)]
                if skip_sending:
                    launch_after_discovery = []  # ya hay un job de envio activo
                if launch_after_discovery:
                    params_disc = {
                        "stage": "cold", "emails": launch_after_discovery, "max": len(launch_after_discovery),
                        "send": True, "dry_run": False,
                        "force_window": False, "campaign_name": "Autopilot discovery", "autopilot": True,
                    }
                    with _outreach_db() as conn:
                        cur = conn.execute(
                            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
                            ("send", "queued", json.dumps(params_disc), "", _outreach_now()),
                        )
                        disc_job_id = int(cur.lastrowid)
                        conn.execute("UPDATE autopilot_config SET last_cold_at=?, updated_at=? WHERE id=1",
                                     (_outreach_now(), _outreach_now()))
                        conn.commit()
                    threading.Thread(target=_outreach_run_send_job, args=(disc_job_id, params_disc), daemon=True).start()
                    _autopilot_log("success", "discovery_cold_launched",
                                   f"Cold post-discovery: {len(launch_after_discovery)} emails encolados "
                                   f"({len(new_emails)} nuevas + pool pendiente)",
                                   {"job_id": disc_job_id, "count": len(launch_after_discovery),
                                    "new_discovered": len(new_emails)})
                else:
                    _autopilot_log("info", "discovery_cold_skip",
                                   "Cold discovery: ninguna empresa nueva con email válido")

        _autopilot_log("info", "tick_end", "◀ Ronda completada")
        _outreach_tick_state_update("done", "Ronda completada")
    except Exception as exc:
        log_err(f"tick falló: {exc}")
        _outreach_tick_state_update("tick_error", f"Ronda falló: {exc}", status="error")
        _autopilot_log("error", "tick_error", f"Ronda falló: {exc}", {"exception": str(exc)})


outreach_autonomous_stop = threading.Event()


def _outreach_reset_stale_jobs() -> None:
    """Marca como interrumpidos los jobs 'running'/'queued' huerfanos: sus hilos
    murieron con el proceso anterior (reinicio del contenedor). Sin esto quedan
    zombies eternos que confunden el guard de concurrencia."""
    if not OUTREACH_AVAILABLE:
        return
    try:
        with _outreach_db() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status='interrupted', finished_at=? "
                "WHERE status IN ('running','queued')",
                (_outreach_now(),),
            )
            conn.commit()
            if cur.rowcount:
                settings.logger.info("[autopilot] %s jobs zombie marcados como interrumpidos al arrancar", cur.rowcount)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[autopilot] no se pudieron limpiar jobs zombie: %s", exc)


def _outreach_active_send_job(conn: sqlite3.Connection) -> Optional[int]:
    """Id de un job de envio (send/autopilot) todavia activo, o None. Solo cuenta
    los iniciados en las ultimas 6h para ignorar zombies que escaparan a la limpieza."""
    try:
        row = conn.execute(
            "SELECT id FROM jobs WHERE kind IN ('send','autopilot') AND status IN ('running','queued') "
            "AND started_at >= datetime('now','-6 hours') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row else None
    except Exception:
        return None


def _outreach_autonomous_worker() -> None:
    interval_minutes = max(10, int(os.getenv("OUTREACH_AUTONOMOUS_TICK_MINUTES", "60") or 60))
    if os.getenv("OUTREACH_AUTONOMOUS_ENABLED", "").lower() != "true":
        settings.logger.info("[autopilot] worker autónomo desactivado por env")
        return
    settings.logger.info("[autopilot] worker autónomo iniciado. Tick cada %s min.", interval_minutes)
    _outreach_reset_stale_jobs()
    # Primera pasada tras 60s para no bloquear startup
    outreach_autonomous_stop.wait(60)
    while not outreach_autonomous_stop.is_set():
        try:
            _outreach_autonomous_tick()
        except Exception as exc:
            settings.logger.error("[autopilot] worker error: %s", exc)
        outreach_autonomous_stop.wait(interval_minutes * 60)


def _outreach_autopilot_worker() -> None:
    """Cron interno: ejecuta autopiloto cada AUTOPILOT_INTERVAL_MINUTES si AUTOPILOT_ENABLED=true."""
    if not os.getenv("AUTOPILOT_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        settings.logger.info("Autopiloto outreach desactivado (AUTOPILOT_ENABLED no activo).")
        return
    interval_minutes = max(10, int(os.getenv("AUTOPILOT_INTERVAL_MINUTES", "60") or 60))
    max_per_run = max(1, int(os.getenv("AUTOPILOT_MAX", "10") or 10))
    settings.logger.info("Autopiloto outreach iniciado. Intervalo: %s min, max/ciclo: %s.", interval_minutes, max_per_run)
    while not appstate.outreach_autopilot_stop.is_set():
        appstate.outreach_autopilot_stop.wait(interval_minutes * 60)
        if appstate.outreach_autopilot_stop.is_set():
            break
        try:
            if not OUTREACH_AVAILABLE:
                continue
            db_path = Path(os.getenv("OUTREACH_DB_PATH", str(OUTREACH_DEFAULT_DB)))
            conn = outreach_connect(db_path)
            params = {"max": max_per_run, "send": True, "delay": 70.0, "jitter": 25.0}
            cur = conn.execute(
                "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
                ("autopilot", "queued", json.dumps(params), "", _outreach_now()),
            )
            job_id = cur.lastrowid
            conn.commit()
            conn.close()
            threading.Thread(
                target=_outreach_run_autopilot_job, args=(job_id, params), daemon=True
            ).start()
            settings.logger.info("Autopiloto outreach: job #%s lanzado (%s max).", job_id, max_per_run)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("Error en autopiloto outreach worker: %s", exc)


def _outreach_run_send_job(job_id: int, params: dict) -> None:
    """Hilo en background que ejecuta envio real/dry-run."""
    db_path = Path(os.getenv("OUTREACH_DB_PATH", str(OUTREACH_DEFAULT_DB)))
    try:
        conn = outreach_connect(db_path)
    except Exception as err:
        settings.logger.error(f"Job {job_id} no pudo abrir DB: {err}")
        return

    stage = params.get("stage", "cold")
    campaign_id = int(params.get("campaign_id") or 0)
    real_send = bool(params.get("send")) or bool(params.get("test_to"))
    settings_row = outreach_smtp_settings()
    unsub = str(settings_row["unsubscribe_mailto"]) or "baja@vantelia.es"
    is_autopilot = bool(params.get("autopilot"))

    try:
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        if campaign_id and params.get("send"):
            conn.execute(
                "UPDATE campaigns SET status='running', job_id=?, updated_at=? WHERE id=? AND status<>'archived'",
                (job_id, _outreach_now(), campaign_id),
            )
        conn.commit()
        try:
            from outreach_campaign import (  # type: ignore
                load_template_overrides,
                render_with_override_and_variant,
            )
            overrides = load_template_overrides(conn, fail_closed=real_send)
        except Exception as template_err:
            _job_log(conn, job_id, f"FATAL plantillas: {template_err}")
            _job_finish(conn, job_id, "error")
            return

        selected_emails = [
            str(email).lower().strip()
            for email in (params.get("emails") or [])
            if str(email).strip()
        ]
        if not params.get("test_to"):
            candidates, assessments = _outreach_select_eligible_prospects(
                conn,
                stage,
                after_days=int(params.get("after_days", 4)),
                limit=int(params.get("max", 20)),
                emails=selected_emails,
                only_email=str(params.get("email") or ""),
            )
            for assessment in assessments:
                if not assessment.get("eligible"):
                    _job_log(
                        conn,
                        job_id,
                        f"skip {assessment.get('email') or '-'} ({assessment.get('reason') or 'ineligible'})",
                    )
        else:
            candidates = outreach_fetch_candidates(
                conn,
                stage,
                after_days=int(params.get("after_days", 4)),
                limit=int(params.get("max", 20)),
                only_email=params.get("email") or None,
            )
        # Modo test sin email concreto: si la query estandar no devuelve nada,
        # caemos a "cualquier prospect" para poder previsualizar el envio real.
        if not candidates and params.get("test_to") and not params.get("email"):
            limit = int(params.get("max", 1)) or 1
            rows = conn.execute(
                "SELECT * FROM prospects ORDER BY created_at ASC LIMIT ?", (limit,)
            ).fetchall()
            candidates = [outreach_row_to_prospect(r) for r in rows]
            if not candidates:
                # BD sin prospects: prospect sintetico para que renderice plantilla.
                from outreach_templates import Prospect as _Prospect  # type: ignore
                candidates = [_Prospect(
                    email=str(params["test_to"]),
                    business_name="Prospect de prueba",
                    contact_name="",
                    niche="",
                    website="",
                    service_hint="",
                    city="Madrid",
                    phone="",
                    tags="",
                    source="test",
                )]
                _job_log(conn, job_id, "Test-mode fallback: BD sin prospects, usando prospect sintetico")
            else:
                _job_log(conn, job_id, f"Test-mode fallback: usando {len(candidates)} prospect(s) sin filtrar historial")

        _job_log(conn, job_id, f"Stage={stage} candidatos={len(candidates)} mode={'send' if real_send else 'dry-run'}")
        if not candidates:
            _job_log(conn, job_id, "Sin candidatos. Comprueba que hay prospects en BD y que el stage seleccionado tiene pendientes.")
            _job_finish(conn, job_id, "done")
            return

        if params.get("send") and not campaign_id and stage == "cold":
            campaign_id = _outreach_create_campaign(
                conn,
                name=params.get("campaign_name") or f"Campana {stage} {_outreach_now()[:10]}",
                stage=stage,
                emails=[p.email for p in candidates],
                settings_row=settings_row,
                delay=float(params.get("delay", 70.0)),
                jitter=float(params.get("jitter", 25.0)),
                force_window=bool(params.get("force_window")),
                status="running",
                job_id=job_id,
                skip_existing=bool(params.get("autopilot")),
            )
            params["campaign_id"] = campaign_id
            conn.execute(
                "UPDATE jobs SET params_json=? WHERE id=?",
                (json.dumps(params), job_id),
            )
            conn.commit()
            _job_log(conn, job_id, f"Campana #{campaign_id} creada para {len(candidates)} candidatos")

        sent_count = 0
        for idx, p in enumerate(candidates, 1):
            if is_autopilot and _outreach_autocapture_is_paused(conn):
                _job_log(conn, job_id, "Autocaptacion pausada. El job se detiene.")
                if campaign_id:
                    conn.execute(
                        "UPDATE campaigns SET status='paused', updated_at=? WHERE id=?",
                        (_outreach_now(), campaign_id),
                    )
                    conn.commit()
                _job_finish(conn, job_id, "done")
                return
            if campaign_id and params.get("send"):
                status_row = conn.execute("SELECT status FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
                if status_row and status_row["status"] == "paused":
                    _job_log(conn, job_id, "Campana pausada. El job se detiene sin marcar pendientes como error.")
                    _job_finish(conn, job_id, "done")
                    return
            if real_send and not params.get("test_to"):
                eligibility = _outreach_send_eligibility(
                    conn, p.email, stage, int(params.get("after_days", 4))
                )
                if not eligibility["eligible"]:
                    reason = str(eligibility["reason"])
                    if campaign_id:
                        conn.execute(
                            "UPDATE campaign_members SET status='skipped', skip_reason=?, updated_at=? WHERE campaign_id=? AND email=?",
                            (reason, _outreach_now(), campaign_id, p.email),
                        )
                        conn.commit()
                    _job_log(conn, job_id, f"skip {p.email} ({reason})")
                    if is_autopilot:
                        _autopilot_log(
                            "info", "email_skipped", f"Saltado {p.email}: {reason}",
                            {"email": p.email, "reason": reason, "stage": stage},
                        )
                    continue
                if conn.execute("SELECT 1 FROM suppressions WHERE email=?", (p.email,)).fetchone():
                    if campaign_id:
                        conn.execute(
                            "UPDATE campaign_members SET status='skipped', skip_reason='baja', updated_at=? WHERE campaign_id=? AND email=?",
                            (_outreach_now(), campaign_id, p.email),
                        )
                        conn.commit()
                    _job_log(conn, job_id, f"skip {p.email} (baja)")
                    if is_autopilot:
                        _autopilot_log("info", "email_skipped", f"Saltado {p.email}: en lista de bajas",
                                       {"email": p.email, "reason": "suppression", "stage": stage})
                    continue
                if conn.execute(
                    "SELECT 1 FROM events WHERE email=? AND type='reply' LIMIT 1", (p.email,)
                ).fetchone():
                    if campaign_id:
                        conn.execute(
                            "UPDATE campaign_members SET status='skipped', skip_reason='ya respondio', updated_at=? WHERE campaign_id=? AND email=?",
                            (_outreach_now(), campaign_id, p.email),
                        )
                        conn.commit()
                    _job_log(conn, job_id, f"skip {p.email} (ya respondio)")
                    if is_autopilot:
                        _autopilot_log("info", "email_skipped", f"Saltado {p.email}: ya respondió",
                                       {"email": p.email, "reason": "already_replied", "stage": stage})
                    continue
                prospect_status_row = conn.execute(
                    "SELECT status FROM prospects WHERE email=?", (p.email,)
                ).fetchone()
                if prospect_status_row and (prospect_status_row["status"] or "") in ("replied", "client", "lost"):
                    if campaign_id:
                        conn.execute(
                            "UPDATE campaign_members SET status='skipped', skip_reason=?, updated_at=? WHERE campaign_id=? AND email=?",
                            (f"status={prospect_status_row['status']}", _outreach_now(), campaign_id, p.email),
                        )
                        conn.commit()
                    _job_log(conn, job_id, f"skip {p.email} (status={prospect_status_row['status']})")
                    if is_autopilot:
                        _autopilot_log("info", "email_skipped",
                                       f"Saltado {p.email}: status={prospect_status_row['status']}",
                                       {"email": p.email, "reason": f"status_{prospect_status_row['status']}", "stage": stage})
                    continue
                if stage == "cold" and conn.execute("SELECT 1 FROM sends WHERE email=? AND mode='send'", (p.email,)).fetchone():
                    if campaign_id:
                        conn.execute(
                            "UPDATE campaign_members SET status='skipped', skip_reason='ya contactado', updated_at=? WHERE campaign_id=? AND email=?",
                            (_outreach_now(), campaign_id, p.email),
                        )
                        conn.commit()
                    _job_log(conn, job_id, f"skip {p.email} (ya contactado)")
                    if is_autopilot:
                        _autopilot_log("info", "email_skipped", f"Saltado {p.email}: ya contactado",
                                       {"email": p.email, "reason": "already_contacted", "stage": stage})
                    continue
                if stage != "cold" and conn.execute(
                    "SELECT 1 FROM sends WHERE email=? AND stage=? AND mode='send'",
                    (p.email, stage),
                ).fetchone():
                    if campaign_id:
                        conn.execute(
                            "UPDATE campaign_members SET status='skipped', skip_reason='stage ya enviado', updated_at=? WHERE campaign_id=? AND email=?",
                            (_outreach_now(), campaign_id, p.email),
                        )
                        conn.commit()
                    _job_log(conn, job_id, f"skip {p.email} (stage ya enviado)")
                    if is_autopilot:
                        _autopilot_log("info", "email_skipped", f"Saltado {p.email}: stage {stage} ya enviado",
                                       {"email": p.email, "reason": "stage_already_sent", "stage": stage})
                    continue

            subject, text, html_body, subject_variant = render_with_override_and_variant(
                stage, p, unsub, overrides
            )
            if not OUTREACH_TRACKING_DISABLED and OUTREACH_TRACKING_SECRET and OUTREACH_TRACKING_BASE_URL:
                html_body = outreach_apply_tracking(
                    html_body, p.email, stage,
                    OUTREACH_TRACKING_BASE_URL, OUTREACH_TRACKING_SECRET,
                )

            recipient = (params.get("test_to") or p.email).lower()
            mode = "test" if params.get("test_to") else ("send" if params.get("send") else "dry-run")

            if not real_send:
                _job_log(conn, job_id, f"[{idx}/{len(candidates)}] DRY {recipient} | {p.business_name} | {subject}")
                continue

            in_reply_to = None
            if stage != "cold":
                prev_stage = OUTREACH_STAGES[OUTREACH_STAGES.index(stage) - 1]
                row = conn.execute(
                    "SELECT message_id FROM sends WHERE email=? AND stage=? AND message_id<>'' ORDER BY id DESC LIMIT 1",
                    (p.email, prev_stage),
                ).fetchone()
                if row and row["message_id"]:
                    in_reply_to = row["message_id"]

            _outreach_wait_send_slot()
            if mode == "send":
                eligibility = _outreach_send_eligibility(
                    conn, p.email, stage, int(params.get("after_days", 4))
                )
                if not eligibility["eligible"]:
                    reason = str(eligibility["reason"])
                    if campaign_id:
                        conn.execute(
                            "UPDATE campaign_members SET status='skipped', skip_reason=?, updated_at=? WHERE campaign_id=? AND email=?",
                            (reason, _outreach_now(), campaign_id, p.email),
                        )
                        conn.commit()
                    _job_log(conn, job_id, f"skip {p.email} pre-SMTP ({reason})")
                    if is_autopilot:
                        _autopilot_log(
                            "info", "email_skipped", f"Saltado {p.email} antes de SMTP: {reason}",
                            {"email": p.email, "reason": reason, "stage": stage},
                        )
                    continue
            msg = outreach_build_message(recipient, subject, text, html_body, settings_row, in_reply_to=in_reply_to)
            try:
                _outreach_send_email_object(msg)
            except Exception as err:  # noqa: BLE001
                limit_reason = _outreach_smtp_ratelimit_reason(err)
                if campaign_id and mode == "send":
                    conn.execute(
                        "UPDATE campaign_members SET status='error', skip_reason=?, updated_at=? WHERE campaign_id=? AND email=?",
                        (str(err)[:240], _outreach_now(), campaign_id, p.email),
                    )
                    conn.commit()
                _job_log(conn, job_id, f"ERROR {recipient}: {err}")
                if limit_reason:
                    _job_log(conn, job_id, "RATE LIMIT SMTP detectado. Pausando autocaptacion y deteniendo job.")
                    _outreach_pause_autocapture_for_smtp_limit(
                        conn,
                        reason=limit_reason,
                        job_id=job_id,
                        campaign_id=campaign_id,
                        email=recipient,
                        stage=stage,
                    )
                    _job_finish(conn, job_id, "error")
                    return
                if is_autopilot:
                    _autopilot_log("error", "email_failed",
                                   f"Fallo SMTP a {recipient}: {err}",
                                   {"email": recipient, "stage": stage, "error": str(err)[:240]})
                continue

            if mode == "send":
                conn.execute(
                    "INSERT INTO sends (campaign_id, email, stage, subject, body_text, body_html, sent_at, mode, message_id, subject_variant) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (campaign_id, p.email, stage, subject, text, html_body, _outreach_now(), mode, msg["Message-ID"] or "", subject_variant or "unknown"),
                )
                send_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
                conn.execute(
                    "UPDATE prospects SET status=CASE WHEN status='new' THEN 'contacted' ELSE status END, updated_at=? WHERE email=?",
                    (_outreach_now(), p.email),
                )
                if campaign_id:
                    conn.execute(
                        """UPDATE campaign_members
                           SET status='sent', stage=?, last_send_id=?, last_sent_at=?, skip_reason='', updated_at=?
                           WHERE campaign_id=? AND email=?""",
                        (stage, send_id, _outreach_now(), _outreach_now(), campaign_id, p.email),
                    )
                    conn.execute(
                        "UPDATE campaigns SET last_sent_at=?, updated_at=? WHERE id=?",
                        (_outreach_now(), _outreach_now(), campaign_id),
                    )
                conn.commit()
            sent_count += 1
            _job_log(conn, job_id, f"[{idx}/{len(candidates)}] OK {recipient} | {p.business_name} ({mode})")
            if is_autopilot and mode == "send":
                _autopilot_log("success", "email_sent",
                               f"Enviado {stage} → {recipient} ({p.business_name or '-'})",
                               {"email": recipient, "stage": stage, "business": p.business_name or "",
                                "subject": subject, "idx": f"{idx}/{len(candidates)}"})

            # Espaciado global gestionado por _outreach_wait_send_slot antes del envio.

        _job_log(conn, job_id, f"Enviados: {sent_count}")
        if is_autopilot:
            _autopilot_log(
                "success" if sent_count > 0 else "info",
                "send_job_done",
                f"Job cold #{job_id} terminado: {sent_count}/{len(candidates)} enviados",
                {"job_id": job_id, "sent": sent_count, "total": len(candidates), "stage": stage},
            )
        if campaign_id and params.get("send"):
            pending = conn.execute(
                "SELECT COUNT(*) AS c FROM campaign_members WHERE campaign_id=? AND status='pending'",
                (campaign_id,),
            ).fetchone()["c"]
            conn.execute(
                "UPDATE campaigns SET status=?, updated_at=? WHERE id=? AND status<>'paused'",
                ("completed" if int(pending or 0) == 0 else "running", _outreach_now(), campaign_id),
            )
            conn.commit()
        _job_finish(conn, job_id, "done")
    except Exception as err:  # noqa: BLE001
        settings.logger.exception("Outreach send job error")
        try:
            _job_log(conn, job_id, f"FATAL: {err}")
            _job_finish(conn, job_id, "error")
        except Exception:
            pass
        if is_autopilot:
            _autopilot_log("error", "send_job_fatal", f"Job cold #{job_id} fatal: {err}",
                           {"job_id": job_id, "error": str(err)[:240]})
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _manual_email_html_document(html_body: str, css_body: str) -> str:
    html_body = (html_body or "").strip()
    css_body = (css_body or "").strip()
    if not html_body:
        html_body = '<div class="email-shell"><div class="email-card"><div class="brand">Vantelia</div><p></p></div></div>'
    style_tag = f"<style>{css_body}</style>" if css_body else ""
    if re.search(r"<!doctype|<html[\s>]", html_body, flags=re.IGNORECASE):
        if style_tag and re.search(r"</head>", html_body, flags=re.IGNORECASE):
            return re.sub(r"</head>", f"{style_tag}</head>", html_body, count=1, flags=re.IGNORECASE)
        return f"{style_tag}{html_body}"
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"{style_tag}</head><body>{html_body}</body></html>"
    )


def _outreach_norm_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value).lower()
    return re.sub(r"\s+", " ", value).strip()


def _outreach_norm_domain(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.netloc or parsed.path.split("/", 1)[0]).lower()
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host.strip(".")


def _outreach_norm_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if digits.startswith("34") and len(digits) > 9:
        digits = digits[2:]
    return digits[-9:] if len(digits) >= 9 else digits


def _outreach_filter_new_discoveries(conn: sqlite3.Connection, companies: List[Any]) -> List[Any]:
    """Quita resultados ya existentes o suprimidos antes de mostrar/importar."""
    prospect_rows = conn.execute("SELECT email, website, phone, business_name, city FROM prospects").fetchall()
    campaign_rows = conn.execute("SELECT email FROM campaign_members").fetchall()
    send_rows = conn.execute("SELECT DISTINCT email FROM sends").fetchall()
    suppressed_emails = {
        (r["email"] or "").strip().lower()
        for r in conn.execute("SELECT email FROM suppressions").fetchall()
    }
    known_emails = {(r["email"] or "").strip().lower() for r in prospect_rows if r["email"]}
    known_emails.update((r["email"] or "").strip().lower() for r in campaign_rows if r["email"])
    known_emails.update((r["email"] or "").strip().lower() for r in send_rows if r["email"])
    known_domains = {_outreach_norm_domain(r["website"] or "") for r in prospect_rows if r["website"]}
    known_phones = {_outreach_norm_phone(r["phone"] or "") for r in prospect_rows if r["phone"]}
    known_name_city = {
        (_outreach_norm_text(r["business_name"] or ""), _outreach_norm_text(r["city"] or ""))
        for r in prospect_rows
        if r["business_name"]
    }
    known_domains.discard("")
    known_phones.discard("")

    out: List[Any] = []
    seen_keys: Set[str] = set()
    for c in companies:
        email = (getattr(c, "email", "") or "").strip().lower()
        domain = _outreach_norm_domain(getattr(c, "website", "") or "")
        phone = _outreach_norm_phone(getattr(c, "phone", "") or "")
        name_city = (
            _outreach_norm_text(getattr(c, "business_name", "") or ""),
            _outreach_norm_text(getattr(c, "city", "") or ""),
        )
        if email and (email in suppressed_emails or email in known_emails):
            continue
        if domain and domain in known_domains:
            continue
        if phone and phone in known_phones:
            continue
        if name_city[0] and name_city in known_name_city:
            continue
        identity = email or domain or phone or "|".join(name_city)
        if identity and identity in seen_keys:
            continue
        if identity:
            seen_keys.add(identity)
        out.append(c)
    return out


def _outreach_run_discovery_job(job_id: int, params: dict) -> None:
    db_path = Path(os.getenv("OUTREACH_DB_PATH", str(OUTREACH_DEFAULT_DB)))
    try:
        conn = outreach_connect(db_path)
    except Exception as err:
        settings.logger.error(f"Discovery job {job_id} sin DB: {err}")
        return
    try:
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        conn.commit()
        try:
            from outreach_discover import discover_companies  # type: ignore
        except Exception as err:
            _job_log(conn, job_id, f"Modulo discover no disponible: {err}")
            _job_finish(conn, job_id, "error")
            return
        try:
            requested_max = max(1, int(params.get("max", 30)))
            raw_max = max(requested_max, min(180, requested_max * 4))
            companies = discover_companies(
                sector=params["sector"],
                ciudad=params["ciudad"],
                max_results=raw_max,
                extract_emails=bool(params.get("extract_emails", True)),
                source=params.get("source", "auto"),
            )
            discovery_metrics = getattr(discover_companies, "last_metrics", {}) or {}
        except Exception as err:
            _job_log(conn, job_id, f"Error discovery: {err}")
            _job_finish(conn, job_id, "error")
            return
        before_filter = len(companies)
        companies = _outreach_filter_new_discoveries(conn, companies)
        new_after_filter = len(companies)
        companies = companies[:requested_max]
        skipped_existing = before_filter - new_after_filter
        if discovery_metrics:
            _job_log(
                conn,
                job_id,
                "Métricas discovery: "
                f"places={discovery_metrics.get('places_raw', 0)}, "
                f"osm={discovery_metrics.get('osm_raw', 0)}, "
                f"dedupe={discovery_metrics.get('deduped', 0)}, "
                f"queries={len(discovery_metrics.get('queries') or [])}",
            )
        _job_log(conn, job_id, f"Encontradas {len(companies)} empresas, {sum(1 for c in companies if c.email)} con email")
        if skipped_existing:
            _job_log(conn, job_id, f"Omitidas {skipped_existing} ya existentes, duplicadas o en bajas")

        if params.get("import_direct"):
            now = _outreach_now()
            added = updated = 0
            for c in companies:
                if not c.email:
                    continue
                payload = {**c.as_csv_row(), "now": now}
                payload["email"] = payload["email"].lower()
                exists = conn.execute("SELECT email FROM prospects WHERE email=?", (payload["email"],)).fetchone()
                if exists:
                    conn.execute(
                        """UPDATE prospects SET business_name=:business_name, contact_name=:contact_name,
                           niche=:niche, website=:website, service_hint=:service_hint, city=:city,
                           phone=:phone, tags=:tags, source=:source, updated_at=:now WHERE email=:email""",
                        payload,
                    )
                    updated += 1
                else:
                    conn.execute(
                        """INSERT INTO prospects (email, business_name, contact_name, niche, website,
                           service_hint, city, phone, tags, source, created_at, updated_at)
                           VALUES (:email,:business_name,:contact_name,:niche,:website,:service_hint,:city,:phone,:tags,:source,:now,:now)""",
                        payload,
                    )
                    added += 1
            conn.commit()
            _job_log(conn, job_id, f"Importados {added} nuevos, {updated} actualizados")

        # Guardar resultado json en log para que UI los muestre
        result_payload = json.dumps([{
            "business_name": c.business_name, "email": c.email, "niche": c.niche,
            "website": c.website, "phone": c.phone, "city": c.city, "place_id": c.place_id,
            "source": c.source, "address": getattr(c, "address", ""),
        } for c in companies])
        _job_log(conn, job_id, f"RESULT_JSON: {result_payload}")
        _job_finish(conn, job_id, "done")
    finally:
        try:
            conn.close()
        except Exception:
            pass




OUTREACH_TRACKING_ALLOWED_HOSTS = {"vantelia.es", "www.vantelia.es", "app.vantelia.es"}

GA4_PROPERTY_ID = os.getenv("GA4_PROPERTY_ID", "").strip()

GA4_SERVICE_ACCOUNT_JSON = (
    os.getenv("GA4_SERVICE_ACCOUNT_JSON", "").strip()
    or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_VANTELIA", "").strip()
)

OUTREACH_PIXEL_GIF = bytes.fromhex("47494638396101000100800000ffffff00000021f90401000000002c00000000010001000002024401003b")

