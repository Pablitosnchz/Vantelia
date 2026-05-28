"""Instagram autosend via Playwright.

Envia DMs automaticamente usando sesion persistente de IG. Opt-in via
``IG_AUTOSEND_ENABLED=true``. Riesgo de bloqueo de cuenta Meta — usar
cuenta secundaria y respetar caps.

CLI:
    python scripts/instagram_autosend.py login         # crea sesion persistente (interactivo)
    python scripts/instagram_autosend.py send --max 5  # envia hasta N drafts pendientes
    python scripts/instagram_autosend.py status        # comprueba sesion guardada

Env vars relevantes:
    IG_AUTOSEND_ENABLED          true para activar (panel + worker lo respetan).
    IG_USERNAME, IG_PASSWORD     credenciales (solo se usan en `login` interactivo).
    IG_SESSION_PATH              ruta del JSON de storage state. Default storage/instagram/session.json
    IG_AUTOSEND_HEADLESS         true por defecto. Pon false para depurar localmente.
    IG_AUTOSEND_DAILY_CAP        DMs reales por dia (default 20).
    IG_AUTOSEND_MIN_DELAY_SEC    delay minimo entre DMs (default 45).
    IG_AUTOSEND_MAX_DELAY_SEC    delay maximo entre DMs (default 180).
    IG_AUTOSEND_TYPING_MIN_MS    delay min entre teclas (default 35).
    IG_AUTOSEND_TYPING_MAX_MS    delay max entre teclas (default 120).
    IG_AUTOSEND_USER_AGENT       UA opcional para spoof.
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

logger = logging.getLogger("instagram_autosend")

DEFAULT_SESSION_PATH = Path("storage/instagram/session.json")
DEFAULT_DB_PATH = Path(os.getenv("IG_DB_PATH", "storage/instagram/instagram.db"))
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
    return Path(os.getenv("IG_SESSION_PATH", str(DEFAULT_SESSION_PATH))).expanduser()


def _ensure_session_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _connect_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target = Path(db_path) if db_path else DEFAULT_DB_PATH
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    return conn


def _mark_send_state(conn: sqlite3.Connection, send_id: int, mode: str, error: str = "") -> None:
    """Update ig_sends row + ig_events + ig_prospects mirrors mark-sent endpoint."""
    row = conn.execute("SELECT * FROM ig_sends WHERE id=?", (send_id,)).fetchone()
    if not row:
        return
    now = _now_iso()
    if mode == "sent_auto":
        conn.execute(
            "UPDATE ig_sends SET mode=?, ready=0, sent_at=? WHERE id=?",
            (mode, now, send_id),
        )
        conn.execute(
            "INSERT INTO ig_events (username, type, stage, ts) VALUES (?,?,?,?)",
            (row["username"], "sent", row["stage"], now),
        )
        conn.execute(
            """UPDATE ig_prospects
               SET status=CASE WHEN status IN ('replied','client','lost','dnc') THEN status ELSE 'contacted' END,
                   last_contacted_at=?, next_followup_at=COALESCE(next_followup_at, ?), updated_at=?
               WHERE username=?""",
            (now, now, now, row["username"]),
        )
    else:
        # failure → log skip with reason
        conn.execute(
            "UPDATE ig_sends SET mode=?, ready=0, skip_reason=? WHERE id=?",
            (mode, (error or "autosend_error")[:120], send_id),
        )
        conn.execute(
            "INSERT INTO ig_events (username, type, stage, ts, meta) VALUES (?,?,?,?,?)",
            (row["username"], "send_error", row["stage"], now, error[:240]),
        )
    conn.commit()


def _human_delay() -> None:
    mn = float(os.getenv("IG_AUTOSEND_MIN_DELAY_SEC", "45") or 45)
    mx = float(os.getenv("IG_AUTOSEND_MAX_DELAY_SEC", "180") or 180)
    if mx < mn:
        mx = mn + 30
    delay = random.uniform(mn, mx)
    logger.info("autosend: sleep %.1fs entre DMs", delay)
    time.sleep(delay)


def _typing_kwargs() -> Dict[str, Any]:
    mn = int(os.getenv("IG_AUTOSEND_TYPING_MIN_MS", "35") or 35)
    mx = int(os.getenv("IG_AUTOSEND_TYPING_MAX_MS", "120") or 120)
    if mx < mn:
        mx = mn + 50
    return {"delay": random.randint(mn, mx)}


def _is_session_valid(state_path: Path) -> bool:
    if not state_path.exists():
        return False
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        cookies = data.get("cookies") or []
        has_sessionid = any(c.get("name") == "sessionid" and c.get("value") for c in cookies)
        return bool(has_sessionid)
    except Exception:
        return False


def session_info(state_path: Optional[Path] = None) -> Dict[str, Any]:
    """Devuelve metadata sobre la sesion guardada (sin exponer valores)."""
    target = state_path or _session_path()
    if not target.exists():
        return {"connected": False, "path": str(target)}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        cookies = data.get("cookies") or []
        sessionid = next((c for c in cookies if c.get("name") == "sessionid"), None)
        ds_user = next((c for c in cookies if c.get("name") == "ds_user_id"), None)
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
            "ds_user_id": (ds_user or {}).get("value"),
            "sessionid_expires_at": expires_iso,
        }
    except Exception as exc:
        return {"connected": False, "path": str(target), "reason": f"corrupto: {exc}"}


def save_session_from_cookies(
    sessionid: str,
    csrftoken: str,
    ds_user_id: str,
    mid: str = "",
    rur: str = "",
    state_path: Optional[Path] = None,
) -> Path:
    """Construye storage_state Playwright a partir de cookies crudas pegadas por el usuario."""
    sessionid = (sessionid or "").strip()
    csrftoken = (csrftoken or "").strip()
    ds_user_id = (ds_user_id or "").strip()
    if not sessionid or not csrftoken or not ds_user_id:
        raise ValueError("Faltan cookies obligatorias: sessionid, csrftoken, ds_user_id")
    # Validacion ligera de formato.
    if ":" not in sessionid:
        raise ValueError("Formato sessionid inesperado (esperaba '<uid>%3A...').")

    target = state_path or _session_path()
    _ensure_session_dir(target)
    # Expira ~1 ano. IG suele rotarla pero esto permite que Playwright no la descarte.
    expires = (datetime.now(timezone.utc) + _timedelta(days=365)).timestamp()

    def _cookie(name: str, value: str) -> Dict[str, Any]:
        return {
            "name": name,
            "value": value,
            "domain": ".instagram.com",
            "path": "/",
            "expires": expires,
            "httpOnly": name == "sessionid",
            "secure": True,
            "sameSite": "Lax",
        }

    cookies = [
        _cookie("sessionid", sessionid),
        _cookie("csrftoken", csrftoken),
        _cookie("ds_user_id", ds_user_id),
    ]
    if mid:
        cookies.append(_cookie("mid", mid.strip()))
    if rur:
        cookies.append(_cookie("rur", rur.strip()))

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
            "Playwright no instalado. Ejecuta: pip install playwright && python -m playwright install chromium"
        ) from exc


def _new_context(p, headless: bool, state_path: Path):
    browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
    context_kwargs: Dict[str, Any] = {
        "user_agent": os.getenv("IG_AUTOSEND_USER_AGENT", DEFAULT_USER_AGENT),
        "viewport": {"width": 1280, "height": 800},
        "locale": "es-ES",
    }
    if state_path.exists():
        context_kwargs["storage_state"] = str(state_path)
    context = browser.new_context(**context_kwargs)
    # Hide webdriver footprint slightly.
    context.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get: () => undefined});"
    )
    return browser, context


def login_interactive(state_path: Optional[Path] = None) -> Path:
    """Lanza navegador no-headless para que el usuario haga login (incluye 2FA).
    Guarda storage_state al cerrar la pestana o tras detectar feed cargado."""
    target = state_path or _session_path()
    _ensure_session_dir(target)
    sync_playwright = _import_playwright()
    with sync_playwright() as p:
        browser, context = _new_context(p, headless=False, state_path=target)
        page = context.new_page()
        page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
        print("\n--- LOGIN INSTAGRAM ---")
        print("Acepta cookies, mete usuario+password+2FA si te lo pide.")
        print("Cuando veas tu feed cargado, pulsa ENTER aqui para guardar la sesion.\n")
        try:
            input("ENTER para guardar > ")
        except EOFError:
            pass
        context.storage_state(path=str(target))
        browser.close()
    print(f"Sesion guardada en {target}")
    return target


def _send_one(page, username: str, message: str) -> bool:
    """Open user profile → click Message → type → send. Returns True if sent."""
    username = username.lstrip("@").strip()
    if not username:
        return False
    profile_url = f"https://www.instagram.com/{username}/"
    page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(random.randint(1500, 3500))

    # Some profiles redirect to login → session expired.
    if "/accounts/login" in page.url:
        raise RuntimeError("sesion_expirada")

    # Click "Message" button. Selectors change often — try several.
    message_selectors = [
        'div[role="button"]:has-text("Enviar mensaje")',
        'div[role="button"]:has-text("Message")',
        'button:has-text("Enviar mensaje")',
        'button:has-text("Message")',
        'a:has-text("Enviar mensaje")',
    ]
    clicked = False
    for sel in message_selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.click(timeout=4000)
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        # Fallback: ig.me deep link with prefilled text
        deep = f"https://ig.me/m/{username}"
        page.goto(deep, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(random.randint(2000, 4000))

    # Esperar el textarea del chat.
    textarea_selectors = [
        'div[role="textbox"][contenteditable="true"]',
        'textarea[placeholder*="ensaje"]',
        'div[aria-label*="ensaje"]',
    ]
    composer = None
    deadline = time.time() + 20
    while time.time() < deadline and composer is None:
        for sel in textarea_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    composer = loc
                    break
            except Exception:
                continue
        if composer is None:
            page.wait_for_timeout(500)

    if composer is None:
        raise RuntimeError("composer_no_encontrado")

    composer.click()
    page.wait_for_timeout(random.randint(400, 1100))
    composer.type(message, **_typing_kwargs())
    page.wait_for_timeout(random.randint(800, 2200))

    # Enviar con Enter (los DMs IG aceptan Enter para enviar).
    page.keyboard.press("Enter")
    page.wait_for_timeout(random.randint(1500, 3000))
    return True


def autosend_drafts(drafts: Iterable[Dict[str, Any]], dry_run: bool = False) -> int:
    """Envia hasta IG_AUTOSEND_DAILY_CAP drafts pendientes. Devuelve cuantos se enviaron."""
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
            f"Sesion IG invalida o ausente en {state_path}. Ejecuta: python scripts/instagram_autosend.py login"
        )

    cap = int(os.getenv("IG_AUTOSEND_DAILY_CAP", "20") or 20)
    drafts = drafts[: max(0, cap)]
    headless = _env_bool("IG_AUTOSEND_HEADLESS", True)
    sync_playwright = _import_playwright()
    sent_ok = 0

    with closing(_connect_db()) as conn, sync_playwright() as p:
        browser, context = _new_context(p, headless=headless, state_path=state_path)
        page = context.new_page()
        # Warmup: abrir feed primero para evitar parecer bot directo.
        try:
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(random.randint(2500, 5500))
        except Exception as exc:
            logger.warning("warmup feed fallo: %s", exc)

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
            # Refrescar storage state por si IG rota cookies.
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
               FROM ig_sends
               WHERE mode='draft' AND ready=1
               ORDER BY id ASC
               LIMIT ?""",
            (max(1, limit),),
        ).fetchall()
        return [dict(r) for r in rows]


def _cli() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Instagram autosend (Playwright)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="Lanza navegador para guardar sesion IG (interactivo).")
    sub.add_parser("status", help="Comprueba sesion guardada.")
    p_send = sub.add_parser("send", help="Envia drafts pendientes.")
    p_send.add_argument("--max", type=int, default=20)
    p_send.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.cmd == "login":
        login_interactive()
        return 0
    if args.cmd == "status":
        path = _session_path()
        ok = _is_session_valid(path)
        print(f"sesion: {'OK' if ok else 'FALTA O INVALIDA'} ({path})")
        return 0 if ok else 1
    if args.cmd == "send":
        if not _env_bool("IG_AUTOSEND_ENABLED", False):
            print("IG_AUTOSEND_ENABLED=false. Activa la flag antes de enviar.")
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
