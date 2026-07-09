"""Captacion TikTok (espejo de Instagram) (refactor F3)."""
from __future__ import annotations

import os
import random
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional



from backend import settings, timeutils

tk_campaign_thread: Optional[threading.Thread] = None

TK_DEFAULT_DB = Path(os.getenv("TK_DB_PATH", str(settings.STORAGE_DIR / "tiktok" / "tiktok.db")))


try:
    # Verifica solo que los modulos esten importables.
    import importlib as _tk_importlib
    _tk_importlib.import_module("tiktok_templates_v2")
    _tk_importlib.import_module("tiktok_discover")
    TK_AVAILABLE = True
except Exception as _tk_err:  # noqa: BLE001
    settings.logger.warning(f"Modulo tiktok no disponible: {_tk_err}")
    TK_AVAILABLE = False


tk_campaign_stop = threading.Event()


def _tk_env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _tk_now() -> str:
    return timeutils._utc_now().isoformat()


def _tk_db():
    TK_DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(TK_DEFAULT_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _tk_row_dict(row) -> Dict[str, Any]:
    return dict(row) if row else {}


def tk_is_autosend_enabled() -> bool:
    return _tk_env_bool("TK_AUTOSEND_ENABLED", False)


def _tk_migrate() -> None:
    """Crea tablas TK si no existen."""
    with _tk_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS tk_prospects (
            username TEXT PRIMARY KEY,
            business_name TEXT DEFAULT '',
            niche TEXT DEFAULT '',
            city TEXT DEFAULT '',
            website TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            source TEXT DEFAULT '',
            status TEXT DEFAULT 'new',
            last_contacted_at TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tk_sends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            stage TEXT DEFAULT 'cold',
            variant TEXT DEFAULT '',
            message_text TEXT NOT NULL,
            mode TEXT DEFAULT 'draft',
            ready INTEGER DEFAULT 1,
            drafted_at TEXT DEFAULT '',
            sent_at TEXT DEFAULT '',
            skip_reason TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_tk_sends_user ON tk_sends(username);
        CREATE INDEX IF NOT EXISTS idx_tk_sends_mode ON tk_sends(mode);
        CREATE TABLE IF NOT EXISTS tk_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            type TEXT NOT NULL,
            stage TEXT DEFAULT '',
            data_json TEXT DEFAULT '',
            ts TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tk_events_user ON tk_events(username);
        CREATE TABLE IF NOT EXISTS tk_suppressions (
            username TEXT PRIMARY KEY,
            reason TEXT DEFAULT '',
            added_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tk_dm_templates_v2 (
            variant TEXT PRIMARY KEY,
            body TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tk_campaign (
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
        );
        INSERT OR IGNORE INTO tk_campaign (id) VALUES (1);
        """)
        conn.commit()


def _tk_resolve_username(raw: str) -> str:
    return (raw or "").lstrip("@").strip().lower()


def _tk_campaign_state() -> Dict[str, Any]:
    if not TK_AVAILABLE:
        return {"available": False}
    _tk_migrate()
    with _tk_db() as conn:
        row = conn.execute("SELECT * FROM tk_campaign WHERE id=1").fetchone()
        cfg = _tk_row_dict(row)
        cfg["discovered_count"] = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_prospects WHERE source LIKE 'campaign%'"
        ).fetchone()["c"]
        cfg["sent_count"] = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_sends WHERE mode='sent_auto'"
        ).fetchone()["c"]
        cfg["replied_count"] = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_prospects WHERE status='replied'"
        ).fetchone()["c"]
        cfg["pending_drafts"] = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_sends WHERE mode='draft' AND ready=1"
        ).fetchone()["c"]
    cfg["worker_alive"] = bool(tk_campaign_thread and tk_campaign_thread.is_alive())
    return cfg


def _tk_campaign_update(**fields: Any) -> None:
    if not fields:
        return
    parts = [f"{k}=?" for k in fields.keys()]
    parts.append("updated_at=?")
    params = list(fields.values()) + [_tk_now()]
    with _tk_db() as conn:
        conn.execute(f"UPDATE tk_campaign SET {', '.join(parts)} WHERE id=1", params)
        conn.commit()


def _tk_render_dm(prospect: Dict[str, Any]) -> str:
    try:
        from tiktok_templates_v2 import render_natural  # type: ignore
    except ImportError:
        return "Hola, soy Pablo de Vantelia. Te escribo por curiosidad."
    return render_natural(
        username=prospect.get("username", ""),
        business_name=prospect.get("business_name", "") or "",
        niche=prospect.get("niche", "") or "",
        city=prospect.get("city", "") or "",
        db_path=str(TK_DEFAULT_DB),
    )


def _tk_insert_candidates(candidates: List[Any]) -> int:
    if not candidates:
        return 0
    now = _tk_now()
    added = 0
    with _tk_db() as conn:
        for c in candidates:
            try:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO tk_prospects
                       (username, business_name, bio, niche, city, website, source, status, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (c.normalized_username(), c.business_name, c.bio_snippet,
                     c.niche, c.city, c.website, c.source, "new", now, now),
                )
                if cur.rowcount:
                    added += 1
            except Exception as exc:
                settings.logger.warning("tk_campaign insert %s: %s", getattr(c, "username", "?"), exc)
        conn.commit()
    return added


def _tk_create_draft(prospect_row: Dict[str, Any]) -> Optional[int]:
    text = _tk_render_dm(prospect_row)
    if not text or len(text) < 30:
        return None
    now = _tk_now()
    try:
        from tiktok_templates_v2 import pick_variant  # type: ignore
        variant = pick_variant(prospect_row.get("username", ""))
    except ImportError:
        variant = "A"
    with _tk_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM tk_sends WHERE username=? AND stage='cold' LIMIT 1",
            (prospect_row["username"],),
        ).fetchone()
        if existing:
            return None
        conn.execute(
            """INSERT INTO tk_sends (username, stage, variant, message_text, mode, ready, drafted_at)
               VALUES (?,?,?,?,?,?,?)""",
            (prospect_row["username"], "cold", variant, text, "draft", 1, now),
        )
        send_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute(
            "INSERT INTO tk_events (username, type, stage, ts) VALUES (?,?,?,?)",
            (prospect_row["username"], "draft", "cold", now),
        )
        conn.execute(
            "UPDATE tk_prospects SET status='queued', updated_at=? WHERE username=? AND status='new'",
            (now, prospect_row["username"]),
        )
        conn.commit()
    return int(send_id)


def _tk_fetch_eligible_prospects(limit: int) -> List[Dict[str, Any]]:
    with _tk_db() as conn:
        rows = conn.execute(
            """SELECT p.* FROM tk_prospects p
               WHERE p.status IN ('new','queued')
                 AND p.source LIKE 'campaign%'
                 AND p.username NOT IN (SELECT username FROM tk_suppressions)
                 AND p.username NOT IN (SELECT username FROM tk_sends)
               ORDER BY p.created_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _tk_last_autosend_error() -> str:
    try:
        with _tk_db() as conn:
            row = conn.execute(
                """SELECT username, skip_reason
                   FROM tk_sends
                   WHERE mode='skipped' AND COALESCE(skip_reason,'')<>''
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            if row:
                return f"@{row['username']}: {row['skip_reason']}"
    except Exception:
        pass
    return ""


def _tk_campaign_iteration(state: Dict[str, Any]) -> Dict[str, Any]:
    target = int(state.get("target_count") or 30)
    sent_count = int(state.get("sent_count") or 0)
    discovered = int(state.get("discovered_count") or 0)
    remaining = max(0, target - sent_count)
    if remaining <= 0:
        _tk_campaign_update(status="completed", completed_at=_tk_now())
        return {"action": "completed"}

    pending_drafts = int(state.get("pending_drafts") or 0)
    pool_target = int(target * 1.5)
    campaign_status = str(state.get("status") or "")

    if discovered < pool_target:
        _tk_campaign_update(status="discovering")
        try:
            from tiktok_discover import discover_real  # type: ignore
        except ImportError as exc:
            _tk_campaign_update(status="paused", error_msg=f"discover no disponible: {exc}")
            return {"action": "error", "reason": "discover_module_missing"}
        with _tk_db() as conn:
            suppressed = {r["username"] for r in conn.execute(
                "SELECT username FROM tk_suppressions").fetchall()}
            known = {r["username"] for r in conn.execute(
                "SELECT username FROM tk_prospects").fetchall()}
        need = min(15, pool_target - discovered)
        candidates = discover_real(
            target_count=need, suppressed=suppressed, known=known,
            log=lambda msg: settings.logger.info("[tk-campaign] %s", msg),
        )
        added = _tk_insert_candidates(candidates)
        settings.logger.info("[tk-campaign] discovery: %s candidatos, %s nuevos", len(candidates), added)
        return {"action": "discovery", "added": added}

    if campaign_status != "sending" and pending_drafts < remaining and pending_drafts < 10:
        eligible = _tk_fetch_eligible_prospects(min(10 - pending_drafts, remaining - pending_drafts))
        drafted = 0
        for p in eligible:
            if _tk_create_draft(p):
                drafted += 1
        settings.logger.info("[tk-campaign] drafts: %s nuevos", drafted)
        return {"action": "draft", "drafted": drafted}

    if pending_drafts > 0 and tk_is_autosend_enabled():
        try:
            from tiktok_autosend import fetch_pending_drafts, autosend_drafts  # type: ignore
        except ImportError:
            _tk_campaign_update(status="paused", error_msg="autosend no disponible")
            return {"action": "error", "reason": "autosend_missing"}
        _tk_campaign_update(status="sending")
        drafts = fetch_pending_drafts(1)
        if not drafts:
            return {"action": "idle_no_drafts"}
        try:
            sent = autosend_drafts(drafts, dry_run=False)
            settings.logger.info("[tk-campaign] autosend: %s/1 enviado", sent)
            if sent == 0:
                reason = _tk_last_autosend_error() or "autosend no pudo enviar el DM"
                _tk_campaign_update(status="paused", error_msg=f"Envio pausado: {reason}")
                return {"action": "error", "reason": "send_failed"}
            return {"action": "sent", "count": sent}
        except RuntimeError as exc:
            err = str(exc)[:200]
            if "Sesion TikTok" in err or "sesion_expirada" in err:
                _tk_campaign_update(status="paused", error_msg=f"sesion expirada: {err}")
                return {"action": "error", "reason": "session_expired"}
            settings.logger.warning("[tk-campaign] autosend RuntimeError: %s", err)
            _tk_campaign_update(status="paused", error_msg=f"autosend fallo: {err}")
            return {"action": "error", "reason": err}
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("[tk-campaign] autosend error: %s", exc)
            _tk_campaign_update(status="paused", error_msg=f"autosend error: {str(exc)[:160]}")
            return {"action": "error", "reason": str(exc)[:120]}

    if pending_drafts > 0 and not tk_is_autosend_enabled():
        _tk_campaign_update(status="paused", error_msg="TK_AUTOSEND_ENABLED=false en env")
        return {"action": "error", "reason": "autosend_disabled"}

    return {"action": "idle"}


def _tk_campaign_worker() -> None:
    settings.logger.info("[tk-campaign] worker iniciado")
    while not tk_campaign_stop.is_set():
        try:
            if not TK_AVAILABLE:
                tk_campaign_stop.wait(60)
                continue
            state = _tk_campaign_state()
            status = state.get("status", "idle")
            if status not in ("discovering", "sending"):
                tk_campaign_stop.wait(45)
                continue
            res = _tk_campaign_iteration(state)
            action = (res or {}).get("action", "")
            if action == "sent":
                mn = int(os.getenv("TK_AUTOSEND_MIN_DELAY_SEC", "60") or 60)
                mx = int(os.getenv("TK_AUTOSEND_MAX_DELAY_SEC", "240") or 240)
                if mx < mn:
                    mx = mn + 30
                tk_campaign_stop.wait(random.uniform(mn, mx))
            elif action == "completed":
                settings.logger.info("[tk-campaign] objetivo alcanzado")
                tk_campaign_stop.wait(60)
            elif action == "error":
                tk_campaign_stop.wait(180)
            else:
                tk_campaign_stop.wait(20)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("[tk-campaign] loop error: %s", exc)
            tk_campaign_stop.wait(60)


def _tk_dm_default(variant: str) -> str:
    try:
        from tiktok_templates_v2 import render_natural  # type: ignore
        return render_natural(
            username=f"demo_{variant.lower()}",
            business_name="Clinica Sonrisa",
            niche="clinica dental",
            city="Madrid",
            variant=variant,
        )
    except Exception:
        return ""


