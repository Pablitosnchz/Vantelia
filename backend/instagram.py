"""Captacion Instagram (drafts 1-clic, autopilot, replies) (refactor F3)."""
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

from backend import appstate, clients, db, outreach, security, settings, textnorm, timeutils

try:
    from instagram_campaign import (  # type: ignore
        DEFAULT_DB as IG_DEFAULT_DB,
        connect as ig_connect,
        STAGE_ORDER as IG_STAGES,
        fetch_candidates as ig_fetch_candidates,
        create_draft as ig_create_draft,
        upsert_profile as ig_upsert_profile,
        is_autosend_enabled as ig_is_autosend_enabled,
        now_iso as ig_now_iso,
    )
    from instagram_templates import (  # type: ignore
        IGProspect,
        render as ig_render,
        igme_deep_link as ig_deep_link,
    )
    from instagram_discover import (  # type: ignore
        IGProfile,
        discover_usernames as ig_discover_usernames,
        normalize_username as ig_normalize_username,
    )
    try:
        from instagram_replies import poll_once as ig_replies_poll  # type: ignore
        IG_REPLIES_AVAILABLE = True
    except Exception as _ig_repl_err:  # noqa: BLE001
        settings.logger.warning(f"Modulo instagram_replies no disponible: {_ig_repl_err}")
        IG_REPLIES_AVAILABLE = False
        ig_replies_poll = None  # type: ignore
    IG_AVAILABLE = True
except Exception as _ig_err:  # noqa: BLE001
    settings.logger.warning(f"Modulo instagram no disponible: {_ig_err}")
    IG_AVAILABLE = False
    IG_REPLIES_AVAILABLE = False
    ig_replies_poll = None  # type: ignore
    IG_DEFAULT_DB = settings.STORAGE_DIR / "instagram" / "instagram.db"
    IG_STAGES = ["cold", "fu1", "fu2", "breakup"]

ig_replies_thread: Optional[threading.Thread] = None
ig_autopilot_thread: Optional[threading.Thread] = None
ig_campaign_thread: Optional[threading.Thread] = None

ig_replies_stop = threading.Event()


ig_autopilot_stop = threading.Event()


def _instagram_db():
    if not IG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Modulo instagram no disponible.")
    return ig_connect(_instagram_db_path())


def _instagram_db_path() -> Path:
    return Path(os.getenv("IG_DB_PATH", str(settings.STORAGE_DIR / "instagram" / "instagram.db")))


def _instagram_now() -> str:
    return timeutils._utc_now().isoformat(timespec="seconds")


def _ig_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _ig_in_window() -> bool:
    if not _ig_env_bool("IG_RESPECT_WINDOW", True):
        return True
    now = datetime.now(ZoneInfo(settings.DEFAULT_TIMEZONE))
    if _ig_env_bool("IG_SKIP_WEEKEND", True) and now.weekday() >= 5:
        return False
    start = int(os.getenv("IG_START_HOUR", "10"))
    end = int(os.getenv("IG_END_HOUR", "20"))
    return start <= now.hour < end


def _ig_row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _ig_resolve_username(value: str) -> str:
    return ig_normalize_username(value) if IG_AVAILABLE else (value or "").strip().lstrip("@").lower()


def _ig_parse_ts(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return _instagram_now()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(settings.DEFAULT_TIMEZONE)).astimezone(timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        raise HTTPException(400, "contacted_at invalido")


IG_STAGE_ALIASES = {
    "": "",
    "cold": "cold",
    "fu1": "fu1",
    "followup1": "fu1",
    "follow-up1": "fu1",
    "fu2": "fu2",
    "followup2": "fu2",
    "follow-up2": "fu2",
    "breakup": "breakup",
    "cierre": "breakup",
    "respuesta": "reply",
    "respondio": "reply",
    "reply": "reply",
    "interesado": "interested",
    "interest": "interested",
    "perdido": "lost",
    "lost": "lost",
    "cliente": "client",
    "client": "client",
    "demo": "demo",
    "cita": "demo",
}


def _ig_normalize_manual_stage(stage: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "", (stage or "").strip().lower())
    return IG_STAGE_ALIASES.get(key, key)


def _ig_stage_from_history(conn: sqlite3.Connection, username: str) -> str:
    sent = {
        r["stage"] for r in conn.execute(
            "SELECT stage FROM ig_sends WHERE username=? AND mode IN ('sent','sent_auto')",
            (username,),
        ).fetchall()
    }
    for stage in IG_STAGES:
        if stage not in sent:
            return stage
    return "breakup"


def _ig_next_followup(stage: str, sent_at: str) -> Dict[str, str]:
    delays = {
        "cold": int(os.getenv("IG_FU1_DAYS", "5") or 5),
        "fu1": int(os.getenv("IG_FU2_DAYS", "7") or 7),
        "fu2": int(os.getenv("IG_BREAKUP_DAYS", "10") or 10),
    }
    next_stage = {"cold": "fu1", "fu1": "fu2", "fu2": "breakup"}.get(stage, "")
    if not next_stage:
        return {"next_stage": "", "next_followup_at": ""}
    try:
        dt = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
    except Exception:
        dt = timeutils._utc_now()
    return {
        "next_stage": next_stage,
        "next_followup_at": (dt + timedelta(days=delays.get(stage, 7))).isoformat(timespec="seconds"),
    }


def _ig_prospect_from_row(row: sqlite3.Row) -> IGProspect:
    return IGProspect(
        username=row["username"],
        full_name=row["full_name"] or "",
        bio=row["bio"] or "",
        business_category=row["business_category"] or "",
        niche=row["niche"] or "",
        city=row["city"] or "",
        website=row["website"] or "",
        public_email=row["public_email"] or "",
        service_hint=row["service_hint"] or "",
    )


def _ig_followup_queue_items(conn: sqlite3.Connection, limit: int = 50, include_upcoming: bool = False) -> List[Dict[str, Any]]:
    now = _instagram_now()
    where = [
        "COALESCE(p.next_followup_at,'')<>''",
        "p.status NOT IN ('replied','client','lost','dnc')",
        "p.username NOT IN (SELECT username FROM ig_suppressions)",
    ]
    params: List[Any] = []
    if not include_upcoming:
        where.append("p.next_followup_at<=?")
        params.append(now)
    params.append(max(1, min(200, limit)))
    rows = conn.execute(
        f"""SELECT p.*,
                   (SELECT s.stage FROM ig_sends s WHERE s.username=p.username AND s.mode IN ('sent','sent_auto') ORDER BY s.sent_at DESC, s.id DESC LIMIT 1) AS last_stage,
                   (SELECT s.sent_at FROM ig_sends s WHERE s.username=p.username AND s.mode IN ('sent','sent_auto') ORDER BY s.sent_at DESC, s.id DESC LIMIT 1) AS last_sent_at
            FROM ig_prospects p
            WHERE {' AND '.join(where)}
            ORDER BY p.next_followup_at ASC, p.score DESC
            LIMIT ?""",
        params,
    ).fetchall()
    items: List[Dict[str, Any]] = []
    for row in rows:
        d = _ig_row_dict(row)
        last_stage = d.get("last_stage") or ""
        next_stage = _ig_next_followup(last_stage, d.get("last_sent_at") or "")["next_stage"] or "fu1"
        if next_stage not in IG_STAGES:
            next_stage = "fu1"
        try:
            message, variant = ig_render(next_stage, _ig_prospect_from_row(row))
        except Exception:
            message, variant = "", ""
        d["next_stage"] = next_stage
        d["suggested_message"] = message
        d["variant"] = variant
        d["deep_link"] = ig_deep_link(d["username"], message) if message else f"https://ig.me/m/{d['username']}"
        d["due"] = bool((d.get("next_followup_at") or "") <= now)
        items.append(d)
    return items


def _ig_autopilot_run_once() -> Dict[str, Any]:
    """Una pasada autopilot. Discovery (si toca) + drafts + autosend (si toca)."""
    stats = {"discovered": 0, "drafted_cold": 0, "drafted_fu": 0, "autosent": 0, "skipped": ""}
    if not IG_AVAILABLE:
        stats["skipped"] = "ig_unavailable"
        return stats
    with _instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_autopilot_config WHERE id=1").fetchone()
        if not row or not row["enabled"]:
            stats["skipped"] = "disabled"
            return stats
        if not _ig_in_window():
            stats["skipped"] = "out_of_window"
            return stats
        try:
            targets = json.loads(row["targets_json"] or "[]")
        except Exception:
            targets = []

        # Discovery via lista de usernames semilla. Si targets contiene
        # {"usernames": [...]}, los toma. Hashtag/location search via Graph API
        # se reserva para una pasada manual (requiere business permissions extra).
        discovery_hours = float(os.getenv("IG_AUTONOMOUS_DISCOVERY_HOURS", "12") or 12)
        last_disc = row["last_discovery_at"] or ""
        do_discovery = False
        if not last_disc:
            do_discovery = True
        else:
            try:
                last_dt = datetime.fromisoformat(last_disc.replace("Z", "+00:00"))
                age = (timeutils._utc_now() - last_dt).total_seconds() / 3600.0
                do_discovery = age >= discovery_hours
            except Exception:
                do_discovery = True

        if do_discovery:
            seed_users: List[str] = []
            for tgt in targets:
                if isinstance(tgt, dict):
                    raw_users = tgt.get("usernames", [])
                    if isinstance(raw_users, str):
                        raw_users = [u.strip() for u in raw_users.split(",") if u.strip()]
                    seed_users.extend(raw_users or [])
            seed_users = list(dict.fromkeys(seed_users))[: int(row["daily_new_target"] or 15)]
            if seed_users:
                profiles = ig_discover_usernames(
                    seed_users,
                    niche=(targets[0].get("niche") if targets and isinstance(targets[0], dict) else "") or "",
                    city=(targets[0].get("city") if targets and isinstance(targets[0], dict) else "") or "",
                    source_label="autopilot",
                )
                for p in profiles:
                    a, _u = ig_upsert_profile(conn, p)
                    if a:
                        stats["discovered"] += 1
                conn.execute(
                    "UPDATE ig_autopilot_config SET last_discovery_at=? WHERE id=1",
                    (_instagram_now(),),
                )

        # Drafts cold hasta cap diario
        today = timeutils._utc_now().date().isoformat()
        sent_today = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto','draft','sending') AND substr(coalesce(sent_at,drafted_at),1,10)=?",
            (today,),
        ).fetchone()["c"]
        cap = int(row["daily_outreach_cap"] or 25)
        remaining = max(0, cap - int(sent_today or 0))
        if remaining > 0:
            cand = ig_fetch_candidates(conn, "cold", min(remaining, int(row["daily_new_target"] or 15)), 0)
            for r in cand:
                ig_create_draft(conn, r, "cold")
                stats["drafted_cold"] += 1
            if stats["drafted_cold"]:
                conn.execute(
                    "UPDATE ig_autopilot_config SET last_outreach_at=? WHERE id=1",
                    (_instagram_now(),),
                )

        # Follow-ups desactivados por defecto: single-touch (solo cold). Cada cuenta
        # recibe un unico DM y nunca se recontacta. Para reactivar la secuencia
        # fu1/fu2/breakup hay que poner IG_AUTONOMOUS_FOLLOWUPS=true en el entorno
        # ademas del toggle del panel.
        if row["auto_followups"] and _ig_env_bool("IG_AUTONOMOUS_FOLLOWUPS", False):
            for fu_stage, after in (("fu1", 5), ("fu2", 7), ("breakup", 10)):
                fu_cand = ig_fetch_candidates(conn, fu_stage, 5, after)
                for r in fu_cand:
                    ig_create_draft(conn, r, fu_stage)
                    stats["drafted_fu"] += 1

        conn.commit()

    # ---- AUTOSEND AUTOMATICO ----
    # Solo si IG_AUTOSEND_ENABLED=true + IG_AUTONOMOUS_AUTOSEND=true. Riesgo ban Meta.
    autosend_on = ig_is_autosend_enabled() and _ig_env_bool("IG_AUTONOMOUS_AUTOSEND", False)
    if autosend_on:
        try:
            from instagram_autosend import autosend_drafts, fetch_pending_drafts  # type: ignore
            # Cap: DB.daily_outreach_cap (panel) tiene prioridad; fallback env IG_AUTOSEND_DAILY_CAP.
            try:
                db_cap = int((row["daily_outreach_cap"] if row else 0) or 0)
            except Exception:
                db_cap = 0
            env_cap = int(os.getenv("IG_AUTOSEND_DAILY_CAP", "20") or 20)
            cap = db_cap if db_cap > 0 else env_cap
            # Cuenta enviados hoy con autosend para respetar tope diario.
            today = timeutils._utc_now().date().isoformat()
            with _instagram_db() as conn:
                sent_today_auto = conn.execute(
                    "SELECT COUNT(*) AS c FROM ig_sends WHERE mode='sent_auto' AND substr(coalesce(sent_at,drafted_at),1,10)=?",
                    (today,),
                ).fetchone()["c"]
            remaining = max(0, cap - int(sent_today_auto or 0))
            if remaining > 0:
                pending = fetch_pending_drafts(remaining)
                if pending:
                    sent = autosend_drafts(pending, dry_run=False)
                    stats["autosent"] = int(sent or 0)
                    settings.logger.info("IG autopilot: autosend envio %s/%s drafts (cap %s, ya enviados %s)",
                                sent, len(pending), cap, sent_today_auto)
            else:
                settings.logger.info("IG autopilot: cap diario alcanzado (%s/%s).", sent_today_auto, cap)
        except ImportError:
            settings.logger.warning("IG autopilot: instagram_autosend o playwright no disponible.")
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("IG autopilot: autosend error: %s", exc)
    return stats


ig_campaign_stop = threading.Event()


def _ig_campaign_migrate() -> None:
    """Crea tabla ig_campaign si no existe (singleton id=1)."""
    if not IG_AVAILABLE:
        return
    with _instagram_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS ig_campaign (
            id INTEGER PRIMARY KEY CHECK (id=1),
            target_count INTEGER DEFAULT 30,
            status TEXT DEFAULT 'idle',
            discovered_count INTEGER DEFAULT 0,
            sent_count INTEGER DEFAULT 0,
            replied_count INTEGER DEFAULT 0,
            started_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            completed_at TEXT DEFAULT '',
            error_msg TEXT DEFAULT ''
        )""")
        conn.execute("INSERT OR IGNORE INTO ig_campaign (id) VALUES (1)")
        conn.commit()


def _ig_campaign_state() -> Dict[str, Any]:
    if not IG_AVAILABLE:
        return {"available": False}
    _ig_campaign_migrate()
    with _instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_campaign WHERE id=1").fetchone()
        cfg = dict(row) if row else {}
        # contadores reales de DB (no confiar solo en campaign columns).
        cfg["discovered_count"] = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_prospects WHERE source LIKE 'campaign%'"
        ).fetchone()["c"]
        cfg["sent_count"] = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode='sent_auto'"
        ).fetchone()["c"]
        cfg["replied_count"] = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_prospects WHERE status='replied'"
        ).fetchone()["c"]
        cfg["pending_drafts"] = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode='draft' AND ready=1"
        ).fetchone()["c"]
    cfg["worker_alive"] = bool(ig_campaign_thread and ig_campaign_thread.is_alive())
    return cfg


def _ig_campaign_update(**fields: Any) -> None:
    if not fields:
        return
    parts = [f"{k}=?" for k in fields.keys()]
    parts.append("updated_at=?")
    params = list(fields.values()) + [_instagram_now()]
    with _instagram_db() as conn:
        conn.execute(f"UPDATE ig_campaign SET {', '.join(parts)} WHERE id=1", params)
        conn.commit()


def _ig_campaign_should_run() -> bool:
    with _instagram_db() as conn:
        row = conn.execute("SELECT status FROM ig_campaign WHERE id=1").fetchone()
    return bool(row and row["status"] in ("discovering", "sending"))


def _ig_campaign_render_dm(prospect: Dict[str, Any]) -> str:
    try:
        from instagram_templates_v2 import render_natural  # type: ignore
    except ImportError:
        return f"Hola, te escribo desde Vantelia. Hacemos asistentes IA para negocios como el vuestro. ¿Hablamos?"
    return render_natural(
        username=prospect.get("username", ""),
        business_name=prospect.get("business_name", "") or prospect.get("full_name", "") or "",
        niche=prospect.get("niche", "") or "",
        city=prospect.get("city", "") or "",
        db_path=str(_instagram_db_path()),
    )


def _ig_campaign_insert_candidates(candidates: List[Any]) -> int:
    """Inserta candidatos en ig_prospects con source=campaign_discover. Devuelve nuevos."""
    if not candidates:
        return 0
    now = _instagram_now()
    added = 0
    with _instagram_db() as conn:
        for c in candidates:
            try:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO ig_prospects
                       (username, full_name, bio, niche, city, website, source, status, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (c.normalized_username(), c.business_name, c.bio_snippet,
                     c.niche, c.city, c.website, c.source, "new", now, now),
                )
                if cur.rowcount:
                    added += 1
            except Exception as exc:
                settings.logger.warning("ig_campaign insert %s: %s", getattr(c, "username", "?"), exc)
        conn.commit()
    return added


def _ig_campaign_create_draft(prospect_row: Dict[str, Any]) -> Optional[int]:
    """Crea un draft cold con texto natural para este prospect. Devuelve send_id."""
    text = _ig_campaign_render_dm(prospect_row)
    if not text or len(text) < 30:
        return None
    now = _instagram_now()
    try:
        from instagram_templates_v2 import pick_variant  # type: ignore
        variant = pick_variant(prospect_row.get("username", ""))
    except ImportError:
        variant = "A"
    with _instagram_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM ig_sends WHERE username=? AND stage='cold' LIMIT 1",
            (prospect_row["username"],),
        ).fetchone()
        if existing:
            return None
        cur = conn.execute(
            """INSERT INTO ig_sends (username, stage, variant, message_text, mode, ready, drafted_at)
               VALUES (?,?,?,?,?,?,?)""",
            (prospect_row["username"], "cold", variant, text, "draft", 1, now),
        )
        send_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute(
            "INSERT INTO ig_events (username, type, stage, ts) VALUES (?,?,?,?)",
            (prospect_row["username"], "draft", "cold", now),
        )
        conn.execute(
            "UPDATE ig_prospects SET status='queued', updated_at=? WHERE username=? AND status='new'",
            (now, prospect_row["username"]),
        )
        conn.commit()
    return int(send_id)


def _ig_campaign_fetch_eligible_prospects(limit: int) -> List[Dict[str, Any]]:
    """Prospects que aun no tienen ningun intento de DM previo."""
    with _instagram_db() as conn:
        rows = conn.execute(
            """SELECT p.* FROM ig_prospects p
               WHERE p.status IN ('new','queued')
                 AND p.source LIKE 'campaign%'
                 AND p.username NOT IN (SELECT username FROM ig_suppressions)
                 AND p.username NOT IN (SELECT username FROM ig_sends)
               ORDER BY p.created_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _ig_campaign_run_iteration(state: Dict[str, Any]) -> Dict[str, Any]:
    """Una iteracion del loop: discover si falta + create drafts + autosend uno."""
    target = int(state.get("target_count") or 30)
    sent_count = int(state.get("sent_count") or 0)
    discovered = int(state.get("discovered_count") or 0)
    remaining = max(0, target - sent_count)
    if remaining <= 0:
        _ig_campaign_update(status="completed", completed_at=_instagram_now())
        return {"action": "completed"}

    pending_drafts = int(state.get("pending_drafts") or 0)

    # 1) Discovery si pool de candidatos < target * 1.5
    pool_target = int(target * 1.5)
    if discovered < pool_target:
        _ig_campaign_update(status="discovering")
        try:
            from instagram_discover_v2 import discover_real  # type: ignore
        except ImportError as exc:
            _ig_campaign_update(status="paused", error_msg=f"discover_v2 no disponible: {exc}")
            return {"action": "error", "reason": "discover_module_missing"}
        with _instagram_db() as conn:
            suppressed = {r["username"] for r in conn.execute(
                "SELECT username FROM ig_suppressions").fetchall()}
            known = {r["username"] for r in conn.execute(
                "SELECT username FROM ig_prospects").fetchall()}
        need = min(15, pool_target - discovered)
        candidates = discover_real(
            target_count=need, suppressed=suppressed, known=known,
            log=lambda msg: settings.logger.info("[ig-campaign] %s", msg),
        )
        added = _ig_campaign_insert_candidates(candidates)
        settings.logger.info("[ig-campaign] discovery: %s candidatos, %s nuevos en DB", len(candidates), added)
        return {"action": "discovery", "added": added}

    # 2) Crear drafts si quedan envios pendientes y pocas en cola
    if pending_drafts < remaining and pending_drafts < 10:
        eligible = _ig_campaign_fetch_eligible_prospects(min(10 - pending_drafts, remaining - pending_drafts))
        drafted = 0
        for p in eligible:
            sid = _ig_campaign_create_draft(p)
            if sid:
                drafted += 1
        settings.logger.info("[ig-campaign] drafts: %s nuevos (pending ahora %s)", drafted, pending_drafts + drafted)
        return {"action": "draft", "drafted": drafted}

    # 3) Autosend uno
    if pending_drafts > 0 and ig_is_autosend_enabled():
        try:
            from instagram_autosend import fetch_pending_drafts, autosend_drafts  # type: ignore
        except ImportError:
            _ig_campaign_update(status="paused", error_msg="autosend module no disponible")
            return {"action": "error", "reason": "autosend_missing"}
        _ig_campaign_update(status="sending")
        drafts = fetch_pending_drafts(1)
        if not drafts:
            return {"action": "idle_no_drafts"}
        try:
            sent = autosend_drafts(drafts, dry_run=False)
            settings.logger.info("[ig-campaign] autosend: %s/1 enviado", sent)
            if sent == 0:
                # autosend retorna 0 si falla → revisa si fue sesion expirada
                return {"action": "send_failed"}
            return {"action": "sent", "count": sent}
        except RuntimeError as exc:
            err = str(exc)[:200]
            if "Sesion IG invalida" in err or "sesion_expirada" in err:
                _ig_campaign_update(status="paused", error_msg=f"sesion expirada: {err}")
                return {"action": "error", "reason": "session_expired"}
            settings.logger.warning("[ig-campaign] autosend RuntimeError: %s", err)
            return {"action": "error", "reason": err}
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("[ig-campaign] autosend error: %s", exc)
            return {"action": "error", "reason": str(exc)[:120]}

    return {"action": "idle"}


def _ig_campaign_worker() -> None:
    """Worker autonomo. Lee status DB y avanza la campana.

    NO chequea ventana laboral — el user controla con boton Empezar/Pausar.
    """
    settings.logger.info("[ig-campaign] worker iniciado")
    while not ig_campaign_stop.is_set():
        try:
            if not IG_AVAILABLE:
                ig_campaign_stop.wait(60)
                continue
            state = _ig_campaign_state()
            status = state.get("status", "idle")
            if status not in ("discovering", "sending"):
                ig_campaign_stop.wait(45)
                continue
            res = _ig_campaign_run_iteration(state)
            action = (res or {}).get("action", "")
            if action == "sent":
                # Delay humano entre envios
                mn = int(os.getenv("IG_AUTOSEND_MIN_DELAY_SEC", "60") or 60)
                mx = int(os.getenv("IG_AUTOSEND_MAX_DELAY_SEC", "240") or 240)
                if mx < mn:
                    mx = mn + 30
                ig_campaign_stop.wait(random.uniform(mn, mx))
            elif action == "completed":
                settings.logger.info("[ig-campaign] objetivo alcanzado")
                ig_campaign_stop.wait(60)
            elif action == "error":
                ig_campaign_stop.wait(180)
            else:
                ig_campaign_stop.wait(20)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("[ig-campaign] loop error: %s", exc)
            ig_campaign_stop.wait(60)


def _ig_dm_templates_ensure() -> None:
    with _instagram_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS ig_dm_templates_v2 (
            variant TEXT PRIMARY KEY,
            body TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.commit()


def _ig_dm_default(variant: str) -> str:
    try:
        from instagram_templates_v2 import render_natural  # type: ignore
        return render_natural(
            username=f"demo_{variant.lower()}",
            business_name="Clinica Sonrisa",
            niche="clinica dental",
            city="Madrid",
            variant=variant,
        )
    except Exception:
        return ""


def _ig_replies_worker() -> None:
    interval_minutes = int(os.getenv("IG_REPLIES_INTERVAL_MINUTES", "10"))
    if interval_minutes <= 0:
        settings.logger.info("Poller IG desactivado por configuracion.")
        return
    if not os.getenv("IG_GRAPH_TOKEN", "").strip():
        settings.logger.info("Poller IG: IG_GRAPH_TOKEN vacio, no se arranca.")
        return
    interval_seconds = max(60, interval_minutes * 60)
    settings.logger.info("Poller IG iniciado. Intervalo: %s minutos.", interval_minutes)
    while not ig_replies_stop.is_set():
        try:
            if not IG_REPLIES_AVAILABLE or ig_replies_poll is None:
                break
            db_path = _instagram_db_path()
            stats = ig_replies_poll(db_path)
            if stats.get("replies_new"):
                settings.logger.info("IG poll: nuevas=%s matched=%s checked=%s", stats.get("replies_new"), stats.get("matched"), stats.get("checked"))
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("Error poller IG: %s", exc)
        ig_replies_stop.wait(interval_seconds)


def _ig_autopilot_worker() -> None:
    if not _ig_env_bool("IG_AUTONOMOUS_ENABLED", False):
        settings.logger.info("IG autopilot desactivado (IG_AUTONOMOUS_ENABLED=false).")
        return
    interval_minutes = int(os.getenv("IG_AUTONOMOUS_TICK_MINUTES", "60") or 60)
    interval_seconds = max(300, interval_minutes * 60)
    settings.logger.info("IG autopilot iniciado. Intervalo: %s minutos.", interval_minutes)
    while not ig_autopilot_stop.is_set():
        try:
            stats = _ig_autopilot_run_once()
            if stats.get("discovered") or stats.get("drafted_cold") or stats.get("drafted_fu"):
                settings.logger.info("[ig-autopilot] %s", stats)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("[ig-autopilot] error: %s", exc)
        ig_autopilot_stop.wait(interval_seconds)


