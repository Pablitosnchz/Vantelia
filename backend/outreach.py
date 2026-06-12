"""Captacion email outbound multi-touch (panel + autopilot) (refactor F3)."""
from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import httpx
from fastapi import BackgroundTasks, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from backend import appstate, clients, db, emailing, security, settings, textnorm, timeutils

OUTREACH_DEFAULT_FOLLOWUP_DAYS: Dict[str, int] = {"fu1": 4, "fu2": 5, "breakup": 6}



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
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("Error en poller IMAP outreach: %s", exc)
        appstate.outreach_imap_stop.wait(interval_seconds)


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
    smtp_ok = emailing._email_delivery_configured()
    env_enabled = os.getenv("OUTREACH_AUTONOMOUS_ENABLED", "").lower() == "true"
    google_ok = bool(os.getenv("GOOGLE_PLACES_API_KEY", "").strip())
    targets_count = len(targets)
    target_companies = _autopilot_target_companies(row["daily_new_target"] or 20)
    generated_targets = _autopilot_generated_targets(target_companies)
    active_targets = _autopilot_targets_for_run(targets, target_companies)
    enabled_db = bool(row["enabled"])
    try:
        discovery_enabled = bool(row["discovery_enabled"]) if "discovery_enabled" in row.keys() else True
    except Exception:
        discovery_enabled = True
    blockers: List[str] = []
    if not env_enabled:
        blockers.append("OUTREACH_AUTONOMOUS_ENABLED no está 'true' en el VPS")
    if not enabled_db:
        blockers.append("Modo automático pausado en el panel")
    if not smtp_ok:
        blockers.append("No hay canal de email conectado (Gmail o SMTP)")
    if False and not google_ok:
        blockers.append("GOOGLE_PLACES_API_KEY vacía (no hay discovery)")
    tick_state = _outreach_tick_state_snapshot()
    return {
        "enabled": enabled_db,
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


def _outreach_autocapture_is_paused(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute("SELECT enabled FROM autopilot_config WHERE id=1").fetchone()
        return bool(row and not bool(row["enabled"]))
    except Exception:
        return False


def _outreach_pause_autocapture_for_smtp_limit(
    conn: sqlite3.Connection,
    *,
    reason: str,
    job_id: int = 0,
    campaign_id: int = 0,
    email: str = "",
    stage: str = "",
) -> None:
    now = _outreach_now()
    detail = {
        "reason": reason[:300],
        "job_id": job_id,
        "campaign_id": campaign_id,
        "email": email,
        "stage": stage,
    }
    try:
        conn.execute("UPDATE autopilot_config SET enabled=0, updated_at=? WHERE id=1", (now,))
    except Exception:
        pass
    try:
        conn.execute(
            "UPDATE campaigns SET status='paused', updated_at=? WHERE status='running'",
            (now,),
        )
    except Exception:
        pass
    try:
        conn.commit()
    except Exception:
        pass
    _outreach_tick_state_update(
        "smtp_ratelimit_paused",
        "Autocaptacion pausada: el SMTP ha devuelto rate limit",
        detail=detail,
        status="error",
    )
    _autopilot_log(
        "error",
        "smtp_ratelimit_autopause",
        "Autocaptacion pausada automaticamente por rate limit SMTP",
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
        from outreach_campaign import render_with_override, load_template_overrides  # type: ignore
        overrides = load_template_overrides(conn)
    except Exception:
        overrides = {}

    try:
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        conn.commit()

        sent_total = 0
        stage_days = _outreach_followup_stage_days(
            params.get("followup_days") or _outreach_config_followup_days(conn)
        )

        for stage, after_days in stage_days:
            if sent_total >= max_total:
                break
            remaining = max_total - sent_total
            candidates = outreach_fetch_candidates(conn, stage, after_days=after_days, limit=remaining)
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

                if overrides:
                    subject, text, html_body = render_with_override(stage, p, unsub, overrides)
                else:
                    subject, text, html_body = outreach_render(stage, p, unsub)
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

                msg = outreach_build_message(p.email, subject, text, html_body, settings_row, in_reply_to=in_reply_to)
                try:
                    emailing._send_email_object(msg)
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

                try:
                    from outreach_templates import assign_variant as _assign_variant  # type: ignore
                    _variant = _assign_variant(p.email, stage)
                except Exception:
                    _variant = ""

                conn.execute(
                    "INSERT INTO sends (email, stage, subject, body_text, body_html, sent_at, mode, message_id, subject_variant)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (p.email, stage, subject, text, html_body, _outreach_now(), "send", msg["Message-ID"] or "", _variant),
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

                import random as _r
                _delay = max(0.0, float(params.get("delay", 70.0)) + _r.uniform(
                    -float(params.get("jitter", 25.0)), float(params.get("jitter", 25.0))
                ))
                time.sleep(_delay)

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
            try:
                discovery_enabled = bool(row["discovery_enabled"]) if "discovery_enabled" in row.keys() else True
            except Exception:
                discovery_enabled = True
            auto_followups = bool(row["auto_followups"])
            followup_days = _outreach_config_followup_days(conn)

        if not enabled:
            _autopilot_log("info", "skip_disabled_db", "Autopiloto pausado en panel")
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

        settings_row = outreach_smtp_settings()
        smtp_ok = emailing._email_delivery_configured()
        if not smtp_ok:
            _autopilot_log("warning", "smtp_not_configured", "No hay canal de email conectado")
            _outreach_tick_state_update("smtp_not_configured", "No hay canal de email conectado")
            return

        # ---- PASO 1: FOLLOW-UPS (cold pendientes + fu1 + fu2 + breakup) ----
        if auto_followups:
            _outreach_tick_state_update("followups_start", "Enviando cold pendientes y follow-ups...")

            # Cold pendientes: todos los prospects sin cold enviado, sin límite de cap
            with _outreach_db() as conn:
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

            if cold_emails:
                _autopilot_log("info", "cold_pending",
                               f"Cold: {len(cold_emails)} prospects pendientes "
                               f"({already_cold} ya contactados anteriormente, saltados)",
                               {"pending": len(cold_emails), "already_cold": already_cold})
                params_cold = {
                    "stage": "cold", "emails": cold_emails, "max": len(cold_emails),
                    "send": True, "dry_run": False, "delay": 70.0, "jitter": 25.0,
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
                               f"Cold: {len(cold_emails)} emails encolados",
                               {"job_id": cold_job_id, "count": len(cold_emails)})
            else:
                _autopilot_log("info", "cold_skip",
                               f"Cold: sin prospects pendientes "
                               f"({already_cold} ya contactados anteriormente)")

            # FU1, FU2, Breakup (sin límite)
            params_fu = {
                "max": 99999, "send": True, "delay": 70.0, "jitter": 25.0,
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
                           "FU1 / FU2 / Breakup: job lanzado en segundo plano",
                           {"job_id": fu_job_id})
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
        pool_target = daily_new_target
        with _outreach_db() as conn:
            pool_size = conn.execute(
                """SELECT COUNT(*) AS c FROM prospects
                   WHERE COALESCE(status,'new')='new'
                     AND email NOT IN (SELECT email FROM suppressions)
                     AND email NOT IN (SELECT email FROM sends WHERE mode='send' AND stage='cold')"""
            ).fetchone()["c"]
        if run_discovery and pool_size >= pool_target:
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
                new_emails: List[str] = []
                with _outreach_db() as conn:
                    known: set = {r["email"] for r in conn.execute("SELECT email FROM prospects").fetchall()}
                    suppressed: set = {r["email"] for r in conn.execute("SELECT email FROM suppressions").fetchall()}

                for t in targets_for_run:
                    if imported_total >= daily_new_target:
                        _autopilot_log("info", "discovery_budget_reached",
                                       f"Discovery: objetivo de {daily_new_target} empresas alcanzado")
                        break
                    sector = (t.get("sector") or "").strip()
                    city = (t.get("city") or "").strip()
                    if not sector or not city:
                        continue
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
                    skipped = found_count - len(companies)

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
                    log(f"discovery {sector}/{city}: {discovered_count} encontrados, {len(companies)} nuevos tras dedupe, {added} importados (sin_email={no_email_count}, dup={duplicate_count}, chain={chain_count})")
                    _outreach_tick_state_update(
                        "discovery_target_done",
                        f"{sector} · {city}: {len(companies)} encontrados, {added} importados",
                        detail={"sector": sector, "city": city, "found": discovered_count, "new_after_dedupe": len(companies), "imported": added,
                                "no_email": no_email_count, "duplicates": duplicate_count, "chains": chain_count},
                        current_target={"sector": sector, "city": city},
                        imported_total=imported_total + added,
                    )
                    _autopilot_log(
                        "success" if added > 0 else "info",
                        "discovery_target_done",
                        f"{sector} · {city}: {len(companies)} encontrados, {added} importados",
                        {"sector": sector, "city": city, "found": discovered_count, "new_after_dedupe": len(companies), "imported": added,
                         "no_email": no_email_count, "duplicates": duplicate_count, "chains": chain_count},
                    )

                with _outreach_db() as conn:
                    conn.execute("UPDATE autopilot_config SET last_discovery_at=?, updated_at=? WHERE id=1",
                                 (_outreach_now(), _outreach_now()))
                    conn.commit()

                _autopilot_log(
                    "success" if imported_total > 0 else "info",
                    "discovery_done",
                    f"Discovery: {imported_total} empresas nuevas importadas"
                    + (f", cold encolado para {len(new_emails)}" if new_emails else ""),
                    {"imported_total": imported_total},
                )
                _outreach_tick_state_update("discovery_done",
                                            f"Discovery: {imported_total} empresas importadas")

                # Cold solo a las recién descubiertas
                if new_emails:
                    params_disc = {
                        "stage": "cold", "emails": new_emails, "max": len(new_emails),
                        "send": True, "dry_run": False, "delay": 70.0, "jitter": 25.0,
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
                                   f"Cold a empresas descubiertas: {len(new_emails)} emails encolados",
                                   {"job_id": disc_job_id, "count": len(new_emails)})
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


def _outreach_autonomous_worker() -> None:
    interval_minutes = max(10, int(os.getenv("OUTREACH_AUTONOMOUS_TICK_MINUTES", "60") or 60))
    if os.getenv("OUTREACH_AUTONOMOUS_ENABLED", "").lower() != "true":
        settings.logger.info("[autopilot] worker autónomo desactivado por env")
        return
    settings.logger.info("[autopilot] worker autónomo iniciado. Tick cada %s min.", interval_minutes)
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
        from outreach_campaign import render_with_override, load_template_overrides  # type: ignore
        overrides = load_template_overrides(conn)
    except Exception:
        overrides = {}

    try:
        conn.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        if campaign_id and params.get("send"):
            conn.execute(
                "UPDATE campaigns SET status='running', job_id=?, updated_at=? WHERE id=? AND status<>'archived'",
                (job_id, _outreach_now(), campaign_id),
            )
        conn.commit()

        selected_emails = [
            str(email).lower().strip()
            for email in (params.get("emails") or [])
            if str(email).strip()
        ]
        if selected_emails and not params.get("test_to"):
            placeholders = ",".join("?" for _ in selected_emails)
            rows = conn.execute(
                f"SELECT * FROM prospects WHERE email IN ({placeholders}) ORDER BY created_at ASC",
                selected_emails,
            ).fetchall()
            candidates = [outreach_row_to_prospect(r) for r in rows]
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

            if overrides:
                subject, text, html_body = render_with_override(stage, p, unsub, overrides)
            else:
                subject, text, html_body = outreach_render(stage, p, unsub)
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

            msg = outreach_build_message(recipient, subject, text, html_body, settings_row, in_reply_to=in_reply_to)
            try:
                emailing._send_email_object(msg)
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
                try:
                    from outreach_templates import assign_variant as _assign_variant  # type: ignore
                    _variant = _assign_variant(p.email, stage)
                except Exception:
                    _variant = ""
                conn.execute(
                    "INSERT INTO sends (campaign_id, email, stage, subject, body_text, body_html, sent_at, mode, message_id, subject_variant) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (campaign_id, p.email, stage, subject, text, html_body, _outreach_now(), mode, msg["Message-ID"] or "", _variant),
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

            if idx < len(candidates):
                import random as _r
                delay = max(0.0, float(params.get("delay", 70.0)) + _r.uniform(-float(params.get("jitter", 25.0)), float(params.get("jitter", 25.0))))
                time.sleep(delay)

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

