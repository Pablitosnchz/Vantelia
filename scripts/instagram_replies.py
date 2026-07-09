"""Poller respuestas Instagram via Graph API.

Solo legal con cuenta IG Business + IG_GRAPH_TOKEN + IG_BUSINESS_ACCOUNT_ID.
Pull-based (lista conversations recientes). Si configurado el webhook, ese tiene
prioridad y este poller funciona como fallback.

Marca ig_prospects.status='replied' y registra evento type='reply' cuando detecta
mensajes nuevos de usuarios a los que hemos contactado (registrados en ig_sends
con mode in ('sent','sent_auto')).

API: poll_once(db_path) -> dict con estadisticas. Llamado desde worker en api.py.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from instagram_campaign import connect  # noqa: E402


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _api_version() -> str:
    return _env("IG_GRAPH_API_VERSION", "v22.0") or "v22.0"


def _contacted_usernames(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT username FROM ig_sends WHERE mode IN ('sent','sent_auto')"
    ).fetchall()
    return {r["username"] for r in rows}


def _record_reply(conn: sqlite3.Connection, username: str, message_id: str = "", text: str = "") -> bool:
    """Devuelve True si era nuevo reply."""
    exists = conn.execute(
        "SELECT 1 FROM ig_events WHERE username=? AND type='reply' AND data_json LIKE ?",
        (username, f"%{message_id}%" if message_id else "%"),
    ).fetchone()
    if exists and message_id:
        return False
    payload = {"message_id": message_id, "text": (text or "")[:400]}
    conn.execute(
        "INSERT INTO ig_events (username, type, stage, data_json, ts) VALUES (?,?,?,?,?)",
        (username, "reply", "", json.dumps(payload, ensure_ascii=False), _now()),
    )
    conn.execute(
        "UPDATE ig_prospects SET status='replied', updated_at=? WHERE username=?",
        (_now(), username),
    )
    return True


def poll_once(db_path: Path) -> dict:
    """Pasada unica del poller. Devuelve stats: checked, matched, replies_new."""
    stats = {"checked": 0, "matched": 0, "replies_new": 0, "error": ""}
    token = _env("IG_GRAPH_TOKEN")
    biz_id = _env("IG_BUSINESS_ACCOUNT_ID")
    if not (token and biz_id and httpx):
        stats["error"] = "missing_token_or_httpx"
        return stats
    base = f"https://graph.facebook.com/{_api_version()}/{biz_id}/conversations"
    params = {
        "platform": "instagram",
        "fields": "participants,messages.limit(5){from,id,message,created_time}",
        "limit": 25,
        "access_token": token,
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(base, params=params)
            if resp.status_code != 200:
                stats["error"] = f"graph_{resp.status_code}"
                return stats
            data = resp.json().get("data") or []
    except Exception as exc:  # noqa: BLE001
        stats["error"] = f"exception:{type(exc).__name__}"
        return stats

    with closing(connect(db_path)) as conn:
        contacted = _contacted_usernames(conn)
        for conv in data:
            stats["checked"] += 1
            participants = (conv.get("participants") or {}).get("data") or []
            other_users = [p for p in participants if p.get("id") != biz_id]
            usernames = [normalize := (p.get("username") or "").strip().lower() for p in other_users]
            usernames = [u for u in usernames if u]
            messages = (conv.get("messages") or {}).get("data") or []
            for u in usernames:
                if u not in contacted:
                    continue
                stats["matched"] += 1
                for msg in messages:
                    sender = (msg.get("from") or {}).get("username", "").strip().lower()
                    if sender != u:
                        continue
                    msg_id = msg.get("id") or ""
                    text = msg.get("message") or ""
                    if _record_reply(conn, u, msg_id, text):
                        stats["replies_new"] += 1
                        break
        conn.commit()
    return stats


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv
    base_dir = Path(__file__).resolve().parent.parent
    load_dotenv(base_dir / ".env")
    db = Path(os.getenv("IG_DB_PATH", str(base_dir / "storage" / "instagram" / "instagram.db")))
    stats = poll_once(db)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
