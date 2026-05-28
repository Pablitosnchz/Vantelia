"""TikTok autosend via Playwright + cookies pegadas.

Espejo de instagram_autosend.py adaptado a TikTok.

Cookies TikTok que importan (sacar de DevTools en tiktok.com):
- sessionid (obligatoria)
- sessionid_ss
- tt_csrf_token
- msToken
- ttwid

CLI:
    python scripts/tiktok_autosend.py status
    python scripts/tiktok_autosend.py send --max 5
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timedelta as _timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("tiktok_autosend")

DEFAULT_SESSION_PATH = Path("storage/tiktok/session.json")
DEFAULT_DB_PATH = Path(os.getenv("TK_DB_PATH", "storage/tiktok/tiktok.db"))
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _session_path() -> Path:
    return Path(os.getenv("TK_SESSION_PATH", str(DEFAULT_SESSION_PATH))).expanduser()


def _ensure_session_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _connect_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target = Path(db_path) if db_path else DEFAULT_DB_PATH
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    return conn


def _mark_send_state(conn: sqlite3.Connection, send_id: int, mode: str, error: str = "") -> None:
    row = conn.execute("SELECT * FROM tk_sends WHERE id=?", (send_id,)).fetchone()
    if not row:
        return
    now = _now_iso()
    if mode == "sent_auto":
        conn.execute(
            "UPDATE tk_sends SET mode=?, ready=0, sent_at=? WHERE id=?",
            (mode, now, send_id),
        )
        conn.execute(
            "INSERT INTO tk_events (username, type, stage, ts) VALUES (?,?,?,?)",
            (row["username"], "sent", row["stage"], now),
        )
        conn.execute(
            """UPDATE tk_prospects
               SET status=CASE WHEN status IN ('replied','client','lost','dnc') THEN status ELSE 'contacted' END,
                   last_contacted_at=?, updated_at=?
               WHERE username=?""",
            (now, now, row["username"]),
        )
    else:
        conn.execute(
            "UPDATE tk_sends SET mode=?, ready=0, skip_reason=? WHERE id=?",
            (mode, (error or "autosend_error")[:120], send_id),
        )
        conn.execute(
            "INSERT INTO tk_events (username, type, stage, data_json, ts) VALUES (?,?,?,?,?)",
            (row["username"], "send_error", row["stage"], (error or "")[:240], now),
        )
    conn.commit()


def _human_delay() -> None:
    mn = float(os.getenv("TK_AUTOSEND_MIN_DELAY_SEC", "60") or 60)
    mx = float(os.getenv("TK_AUTOSEND_MAX_DELAY_SEC", "240") or 240)
    if mx < mn:
        mx = mn + 30
    delay = random.uniform(mn, mx)
    logger.info("autosend: sleep %.1fs entre DMs", delay)
    time.sleep(delay)


def _typing_kwargs() -> Dict[str, Any]:
    mn = int(os.getenv("TK_AUTOSEND_TYPING_MIN_MS", "35") or 35)
    mx = int(os.getenv("TK_AUTOSEND_TYPING_MAX_MS", "120") or 120)
    if mx < mn:
        mx = mn + 50
    return {"delay": random.randint(mn, mx)}


def _is_session_valid(state_path: Path) -> bool:
    if not state_path.exists():
        return False
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        cookies = data.get("cookies") or []
        return any(c.get("name") == "sessionid" and c.get("value") for c in cookies)
    except Exception:
        return False


def session_info(state_path: Optional[Path] = None) -> Dict[str, Any]:
    target = state_path or _session_path()
    if not target.exists():
        return {"connected": False, "path": str(target)}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        cookies = data.get("cookies") or []
        sessionid = next((c for c in cookies if c.get("name") == "sessionid"), None)
        if not sessionid or not sessionid.get("value"):
            return {"connected": False, "path": str(target), "reason": "sin sessionid"}
        expires_ts = sessionid.get("expires")
        expires_iso = None
        if isinstance(expires_ts, (int, float)) and expires_ts > 0:
            try:
                expires_iso = datetime.fromtimestamp(expires_ts, tz=timezone.utc).isoformat()
            except Exception:
                expires_iso = None
        mtime = datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc).isoformat()
        return {
            "connected": True,
            "path": str(target),
            "saved_at": mtime,
            "sessionid_expires_at": expires_iso,
        }
    except Exception as exc:
        return {"connected": False, "path": str(target), "reason": f"corrupto: {exc}"}


def save_session_from_cookies(
    sessionid: str,
    sessionid_ss: str = "",
    tt_csrf_token: str = "",
    ms_token: str = "",
    ttwid: str = "",
    state_path: Optional[Path] = None,
) -> Path:
    """Construye storage_state Playwright para TikTok."""
    sessionid = (sessionid or "").strip()
    if not sessionid:
        raise ValueError("Falta cookie obligatoria: sessionid")
    if len(sessionid) < 20:
        raise ValueError("sessionid demasiado corta. Copia el valor completo.")

    target = state_path or _session_path()
    _ensure_session_dir(target)
    expires = (datetime.now(timezone.utc) + _timedelta(days=365)).timestamp()

    def _cookie(name: str, value: str, http_only: bool = False) -> Dict[str, Any]:
        return {
            "name": name,
            "value": value,
            "domain": ".tiktok.com",
            "path": "/",
            "expires": expires,
            "httpOnly": http_only,
            "secure": True,
            "sameSite": "Lax",
        }

    cookies = [_cookie("sessionid", sessionid, http_only=True)]
    if sessionid_ss:
        cookies.append(_cookie("sessionid_ss", sessionid_ss.strip(), http_only=True))
    if tt_csrf_token:
        cookies.append(_cookie("tt_csrf_token", tt_csrf_token.strip()))
    if ms_token:
        cookies.append(_cookie("msToken", ms_token.strip()))
    if ttwid:
        cookies.append(_cookie("ttwid", ttwid.strip(), http_only=True))

    state = {"cookies": cookies, "origins": []}
    target.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return target


def clear_session(state_path: Optional[Path] = None) -> bool:
    target = state_path or _session_path()
    if target.exists():
        target.unlink()
        return True
    return False


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        return sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright no instalado. pip install playwright && python -m playwright install chromium"
        ) from exc


def _new_context(p, headless: bool, state_path: Path):
    browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
    context_kwargs: Dict[str, Any] = {
        "user_agent": os.getenv("TK_AUTOSEND_USER_AGENT", DEFAULT_USER_AGENT),
        "viewport": {"width": 1280, "height": 800},
        "locale": "es-ES",
    }
    if state_path.exists():
        context_kwargs["storage_state"] = str(state_path)
    context = browser.new_context(**context_kwargs)
    context.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get: () => undefined});"
    )
    return browser, context


def _debug_screenshot(page, username: str, tag: str) -> None:
    if not _env_bool("TK_AUTOSEND_DEBUG", False):
        return
    try:
        debug_dir = Path(os.getenv("TK_AUTOSEND_DEBUG_DIR", "storage/tiktok/debug"))
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = debug_dir / f"{ts}_{username}_{tag}.png"
        page.screenshot(path=str(path), full_page=False)
        logger.info("debug screenshot: %s", path)
    except Exception as exc:
        logger.warning("screenshot fail: %s", exc)


def _dismiss_overlays(page) -> None:
    dismiss_texts = [
        "Aceptar todas", "Allow all", "Accept all", "Aceptar",
        "Ahora no", "Not now", "Cerrar", "Close", "Mas tarde",
    ]
    for txt in dismiss_texts:
        try:
            loc = page.locator(f'button:has-text("{txt}")').first
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=2000)
                page.wait_for_timeout(random.randint(300, 800))
        except Exception:
            continue


def _has_error_modal(page) -> bool:
    for err_sel in (
        'div[role="dialog"]:has-text("Error")',
        'div[role="alert"]',
        'div:has-text("Something went wrong")',
        'div:has-text("Algo salio mal")',
        'div:has-text("Try again")',
        'div:has-text("Inténtalo de nuevo")',
    ):
        try:
            loc = page.locator(err_sel).first
            if loc.count() > 0 and loc.is_visible():
                return True
        except Exception:
            continue
    return False


def _verify_sent(page, message: str, composer, timeout_sec: int = 12) -> bool:
    """Verifica envio: composer perdio el mensaje + URL pattern + sin error modal."""
    message_full = (message or "").strip().replace("\n", " ")
    first_chunk = message_full[:30].lower()
    start_ts = time.time()
    deadline = start_ts + timeout_sec
    while time.time() < deadline:
        try:
            try:
                cur_url = page.url or ""
            except Exception:
                cur_url = ""
            composer_text = ""
            try:
                composer_text = (composer.text_content() or "").strip()
            except Exception:
                pass

            # Composer perdio el mensaje → enviado (si no hay modal error)
            if first_chunk and first_chunk not in composer_text.lower().replace("\n", " "):
                if not _has_error_modal(page):
                    return True

            elapsed = time.time() - start_ts
            if elapsed >= 3.5 and "/messages" in cur_url and not _has_error_modal(page):
                if first_chunk not in composer_text.lower():
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _send_one(page, username: str, message: str) -> bool:
    username = username.lstrip("@").strip()
    if not username:
        return False
    profile_url = f"https://www.tiktok.com/@{username}"
    page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(random.randint(1500, 3500))

    cur_url = page.url or ""
    if "/login" in cur_url:
        raise RuntimeError("sesion_expirada")

    _dismiss_overlays(page)
    _debug_screenshot(page, username, "01_profile")

    # Click boton "Mensaje" / "Message"
    message_selectors = [
        'button:has-text("Mensaje")',
        'button:has-text("Message")',
        'div[role="button"]:has-text("Mensaje")',
        'div[role="button"]:has-text("Message")',
        'a:has-text("Mensaje")',
    ]
    clicked = False
    for sel in message_selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=4000)
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        # Fallback: ir directo a /messages/
        page.goto("https://www.tiktok.com/messages/", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(random.randint(2000, 4000))
        _dismiss_overlays(page)

    _debug_screenshot(page, username, "02_chat_open")

    # Localiza composer
    composer = None
    deadline = time.time() + 25
    composer_selectors = [
        'div[role="textbox"][contenteditable="true"][aria-label*="ensaje" i]',
        'div[role="textbox"][contenteditable="true"][aria-label*="essage" i]',
        'div[contenteditable="true"][data-e2e*="message" i]',
        'div[role="textbox"][contenteditable="true"]',
        'textarea[placeholder*="ensaje" i]',
        'textarea[placeholder*="essage" i]',
    ]
    while time.time() < deadline and composer is None:
        for sel in composer_selectors:
            try:
                candidates = page.locator(sel)
                n = min(candidates.count(), 5)
                for i in range(n):
                    loc = candidates.nth(i)
                    try:
                        if loc.is_visible():
                            box = loc.bounding_box()
                            if box and box.get("y", 0) > 250:
                                composer = loc
                                break
                    except Exception:
                        continue
                if composer is not None:
                    break
            except Exception:
                continue
        if composer is None:
            page.wait_for_timeout(600)

    if composer is None:
        _debug_screenshot(page, username, "03_no_composer")
        raise RuntimeError("composer_no_encontrado")

    try:
        composer.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    composer.click(timeout=5000)
    page.wait_for_timeout(random.randint(400, 1100))
    try:
        page.keyboard.press("Control+A")
        page.wait_for_timeout(150)
        page.keyboard.press("Delete")
        page.wait_for_timeout(200)
    except Exception:
        pass
    typing_delay = _typing_kwargs().get("delay", 60)
    page.keyboard.type(message, delay=typing_delay)
    page.wait_for_timeout(random.randint(900, 2400))
    _debug_screenshot(page, username, "04_typed")

    sent_via_button = False
    send_button_selectors = [
        'div[role="button"][aria-label*="nviar" i]',
        'div[role="button"][aria-label*="end" i]',
        'button:has-text("Enviar")',
        'button:has-text("Send")',
        'div[data-e2e*="send" i]',
    ]
    for sel in send_button_selectors:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                btn.click(timeout=2000)
                sent_via_button = True
                break
        except Exception:
            continue
    if not sent_via_button:
        try:
            composer.press("Enter")
        except Exception:
            page.keyboard.press("Enter")
    page.wait_for_timeout(random.randint(2000, 3500))
    _debug_screenshot(page, username, "05_after_send")

    if not _verify_sent(page, message, composer, timeout_sec=12):
        _debug_screenshot(page, username, "06_verify_fail")
        raise RuntimeError("envio_no_verificado")

    return True


def autosend_drafts(drafts: Iterable[Dict[str, Any]], dry_run: bool = False) -> int:
    drafts = list(drafts)
    if not drafts:
        return 0
    if dry_run:
        for d in drafts:
            print(f"[DRY] -> @{d.get('username')}: {(d.get('message') or '')[:80]}...")
        return len(drafts)

    state_path = _session_path()
    if not _is_session_valid(state_path):
        raise RuntimeError(
            f"Sesion TikTok invalida o ausente en {state_path}. Pega cookies en el panel."
        )

    cap = int(os.getenv("TK_AUTOSEND_DAILY_CAP", "5") or 5)
    drafts = drafts[: max(0, cap)]
    headless = _env_bool("TK_AUTOSEND_HEADLESS", True)
    sync_playwright = _import_playwright()
    sent_ok = 0

    with closing(_connect_db()) as conn, sync_playwright() as p:
        browser, context = _new_context(p, headless=headless, state_path=state_path)
        page = context.new_page()
        try:
            page.goto("https://www.tiktok.com/foryou", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(random.randint(2500, 5500))
        except Exception as exc:
            logger.warning("warmup foryou fallo: %s", exc)

        for idx, draft in enumerate(drafts):
            send_id = int(draft.get("id") or 0)
            username = draft.get("username") or ""
            message = draft.get("message") or ""
            if not send_id or not username or not message:
                continue
            try:
                ok = _send_one(page, username, message)
                if ok:
                    _mark_send_state(conn, send_id, "sent_auto")
                    sent_ok += 1
                    logger.info("autosend OK -> @%s (send_id=%s)", username, send_id)
                else:
                    _mark_send_state(conn, send_id, "draft", "no_enviado")
            except Exception as exc:
                err = str(exc)[:200]
                logger.warning("autosend FAIL -> @%s: %s", username, err)
                _mark_send_state(conn, send_id, "skipped", f"autosend:{err}")
                if "sesion_expirada" in err:
                    break
            try:
                context.storage_state(path=str(state_path))
            except Exception:
                pass
            if idx < len(drafts) - 1:
                _human_delay()

        browser.close()

    return sent_ok


def fetch_pending_drafts(limit: int) -> List[Dict[str, Any]]:
    with closing(_connect_db()) as conn:
        rows = conn.execute(
            """SELECT id, username, stage, variant, message_text AS message
               FROM tk_sends
               WHERE mode='draft' AND ready=1
               ORDER BY id ASC
               LIMIT ?""",
            (max(1, limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def _cli() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="TikTok autosend (Playwright)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p_send = sub.add_parser("send")
    p_send.add_argument("--max", type=int, default=5)
    p_send.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.cmd == "status":
        path = _session_path()
        ok = _is_session_valid(path)
        print(f"sesion: {'OK' if ok else 'FALTA O INVALIDA'} ({path})")
        return 0 if ok else 1
    if args.cmd == "send":
        if not _env_bool("TK_AUTOSEND_ENABLED", False):
            print("TK_AUTOSEND_ENABLED=false")
            return 2
        drafts = fetch_pending_drafts(args.max)
        if not drafts:
            print("No hay drafts pendientes.")
            return 0
        sent = autosend_drafts(drafts, dry_run=args.dry_run)
        print(f"Enviados: {sent} / {len(drafts)}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
