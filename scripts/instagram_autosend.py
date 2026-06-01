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
            "INSERT INTO ig_events (username, type, stage, data_json, ts) VALUES (?,?,?,?,?)",
            (row["username"], "send_error", row["stage"], (error or "")[:240], now),
        )
    conn.commit()


def _claim_send_attempt(conn: sqlite3.Connection, send_id: int) -> Optional[sqlite3.Row]:
    """Reserve a draft before opening IG so resume never sends it twice."""
    row = conn.execute(
        "SELECT * FROM ig_sends WHERE id=? AND mode='draft' AND ready=1",
        (send_id,),
    ).fetchone()
    if not row:
        return None
    prior = conn.execute(
        """SELECT 1 FROM ig_sends
           WHERE username=? AND id<>? AND mode IN ('sent','sent_auto','sending')
           LIMIT 1""",
        (row["username"], send_id),
    ).fetchone()
    now = _now_iso()
    if prior:
        conn.execute(
            "UPDATE ig_sends SET mode='skipped', ready=0, skip_reason=? WHERE id=?",
            ("ya_contactado", send_id),
        )
        conn.execute(
            "INSERT INTO ig_events (username, type, stage, data_json, ts) VALUES (?,?,?,?,?)",
            (row["username"], "skip", row["stage"], "ya_contactado", now),
        )
        conn.commit()
        return None
    conn.execute(
        "UPDATE ig_sends SET mode='sending', ready=0, skip_reason='' WHERE id=?",
        (send_id,),
    )
    conn.execute(
        "INSERT INTO ig_events (username, type, stage, ts) VALUES (?,?,?,?)",
        (row["username"], "send_attempt", row["stage"], now),
    )
    conn.commit()
    return conn.execute("SELECT * FROM ig_sends WHERE id=?", (send_id,)).fetchone()


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
    # Validacion ligera: sessionid suele tener separador ':' o '%3A'.
    sep_ok = (":" in sessionid) or ("%3A" in sessionid.upper())
    if not sep_ok or len(sessionid) < 20:
        raise ValueError("Formato sessionid inesperado. Copia el valor completo de la cookie.")

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


def _dismiss_overlays(page) -> None:
    """Cierra cookie banners + modales 'Save info'/'Turn on notifications' que bloquean UI."""
    dismiss_texts = [
        "Permitir todas las cookies", "Allow all cookies", "Accept all",
        "Aceptar", "Ahora no", "Not Now", "Not now",
        "Cerrar", "Close", "Mas tarde",
    ]
    for txt in dismiss_texts:
        try:
            loc = page.locator(f'button:has-text("{txt}")').first
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=2000)
                page.wait_for_timeout(random.randint(300, 800))
        except Exception:
            continue


def _debug_screenshot(page, username: str, tag: str) -> None:
    if not _env_bool("IG_AUTOSEND_DEBUG", False):
        return
    try:
        debug_dir = Path(os.getenv("IG_AUTOSEND_DEBUG_DIR", "storage/instagram/debug"))
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = debug_dir / f"{ts}_{username}_{tag}.png"
        page.screenshot(path=str(path), full_page=False)
        logger.info("debug screenshot: %s", path)
    except Exception as exc:
        logger.warning("screenshot fail: %s", exc)


def _count_message_bubbles(page) -> int:
    """Cuenta burbujas de mensaje en thread. Robusto a cambios markup IG.

    IG renderiza texto de cada mensaje dentro de divs/spans con dir="auto"
    (mas estable que clases CSS dinamicas). El composer NO usa dir="auto"
    sino contenteditable. Si hay >=1 div[dir="auto"] en la zona del chat,
    asumimos historial previo.
    """
    selectors = [
        'div[dir="auto"]',
        'span[dir="auto"]',
        'div[role="row"]',
        'div[data-testid="message-container"]',
        'div[data-block="message"]',
    ]
    best = 0
    for sel in selectors:
        try:
            n = page.locator(sel).count()
            if n > best:
                best = n
        except Exception:
            continue
    return best


def _already_contacted(page) -> bool:
    """Detecta si ya hay historial de mensajes con este usuario.

    Senyales acumulativas:
    - URL contiene /direct/t/ Y hay >=2 divs dir=auto visibles
    - O directamente hay >=3 burbujas detectadas
    """
    try:
        url = page.url or ""
    except Exception:
        url = ""
    bubbles = _count_message_bubbles(page)
    if "/direct/t/" in url and bubbles >= 2:
        return True
    if bubbles >= 3:
        return True
    return False


def _verify_sent(page, message: str, baseline: int, composer, timeout_sec: int = 12) -> bool:
    """Verifica envio. Estrategia laxa para no marcar como fallo cuando IG si mando.

    Espera unos segundos tras Enter. Si NO hay modal de error visible y
    paso al menos 3s en URL /direct/t/ → asumimos enviado.

    Tambien checks especificos:
    - texto del mensaje YA NO en composer
    - burbujas crecieron y texto en burbuja (match exacto)
    """
    snippet = (message or "").strip().split("\n", 1)[0][:40]
    message_full = (message or "").strip().replace("\n", " ")
    start_ts = time.time()
    deadline = start_ts + timeout_sec
    last_composer_text = None
    while time.time() < deadline:
        try:
            try:
                cur_url = page.url or ""
            except Exception:
                cur_url = ""

            # Composer text actual
            composer_text = ""
            try:
                composer_text = (composer.text_content() or "").strip()
            except Exception:
                pass
            if last_composer_text is None:
                last_composer_text = composer_text

            # 1) composer perdio el mensaje → IG lo envio
            if message_full and len(message_full) > 30:
                first_chunk = message_full[:30].lower()
                if first_chunk not in composer_text.lower().replace("\n", " "):
                    # Check sin modal de error
                    if not _has_error_modal(page):
                        return True

            # 2) burbujas + texto en burbuja
            try:
                current = _count_message_bubbles(page)
            except Exception:
                current = 0
            grew = current > baseline + 1  # margen, head info puede sumar
            if grew and snippet and len(snippet) >= 6:
                try:
                    hit = page.locator(f'div[dir="auto"]:has-text("{snippet}")').count()
                    if hit >= 1:
                        return True
                except Exception:
                    pass

            # 3) En /direct/t/ desde hace ≥3s, sin error modal, composer no vuelve a tener nuestro mensaje
            elapsed = time.time() - start_ts
            if elapsed >= 3.5 and "/direct/t/" in cur_url and not _has_error_modal(page):
                # Verifica que el composer no esta mostrando el mensaje completo
                if message_full[:30].lower() not in composer_text.lower():
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _has_error_modal(page) -> bool:
    """Detecta modales de error de IG."""
    for err_sel in (
        'div[role="dialog"]:has-text("Error")',
        'div[role="alert"]',
        'div:has-text("Something went wrong")',
        'div:has-text("Algo salio mal")',
        'div:has-text("Inténtalo de nuevo")',
        'div:has-text("Try again")',
    ):
        try:
            loc = page.locator(err_sel).first
            if loc.count() > 0 and loc.is_visible():
                return True
        except Exception:
            continue
    return False


def _send_one(page, username: str, message: str) -> bool:
    """Open user profile → click Message → type → send + verify. Raises on fail."""
    username = username.lstrip("@").strip()
    if not username:
        return False

    # Estrategia: ir directo a ig.me/m/{user} con text prefilled. Mas robusto que
    # navegar perfil y buscar boton "Enviar mensaje" (selector cambia mucho).
    profile_url = f"https://www.instagram.com/{username}/"
    page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(random.randint(1500, 3500))

    if "/accounts/login" in page.url:
        raise RuntimeError("sesion_expirada")

    _dismiss_overlays(page)
    _debug_screenshot(page, username, "01_profile")

    # Click boton mensaje.
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
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=4000)
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        # Fallback: ig.me deep link.
        deep = f"https://ig.me/m/{username}"
        page.goto(deep, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(random.randint(2500, 4500))
        _dismiss_overlays(page)

    _debug_screenshot(page, username, "02_chat_open")

    # Localiza composer del chat (no la search bar). Filtros priorizados:
    # 1) aria-label contiene "Mensaje" o "Message" (exclusivo composer DM)
    # 2) placeholder textarea con "Mensaje"/"Message"
    # 3) Lexical editor (IG nuevo composer)
    # 4) Fallback genérico contenteditable visible (excluye los de cabecera con aria-label "Buscar")
    composer = None
    deadline = time.time() + 25
    composer_selectors = [
        'div[role="textbox"][contenteditable="true"][aria-label*="ensaje" i]',
        'div[role="textbox"][contenteditable="true"][aria-label*="essage" i]',
        'div[contenteditable="true"][data-lexical-editor="true"]',
        'textarea[placeholder*="ensaje" i]',
        'textarea[placeholder*="essage" i]',
        'div[role="textbox"][contenteditable="true"]:not([aria-label*="uscar" i]):not([aria-label*="earch" i])',
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
                            # composer del chat suele estar en mitad-baja de viewport (>250px Y)
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

    # Foco. Usar focus() en vez de click() para evitar abrir menus.
    try:
        composer.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    composer.click(timeout=5000)
    page.wait_for_timeout(random.randint(400, 1100))
    # Limpia por si hay prefill del ig.me deep link.
    try:
        page.keyboard.press("Control+A")
        page.wait_for_timeout(150)
        page.keyboard.press("Delete")
        page.wait_for_timeout(200)
    except Exception:
        pass
    # Usa page.keyboard.type tras focus para evitar Locator.type timeout en
    # contenteditable raros. Escribe al elemento activo. El draft ya esta
    # reservado como "sending", asi que una reanudacion no lo coge otra vez.
    # daba falsos positivos por header/perfil → eliminada.
    baseline_bubbles = _count_message_bubbles(page)

    typing_delay = _typing_kwargs().get("delay", 60)
    page.keyboard.type(message, delay=typing_delay)
    page.wait_for_timeout(random.randint(900, 2400))
    _debug_screenshot(page, username, "04_typed")

    # Enviar. Intento: boton Send/Enviar si existe (visible enabled), luego composer.press Enter.
    sent_via_button = False
    send_button_selectors = [
        'div[role="button"][aria-label*="nviar" i]',
        'div[role="button"][aria-label*="end" i]',
        'div[role="button"]:has-text("Enviar")',
        'div[role="button"]:has-text("Send")',
        'button[type="submit"]',
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
        # composer.press("Enter") asegura el evento llega al elemento correcto.
        try:
            composer.press("Enter")
        except Exception:
            page.keyboard.press("Enter")
    page.wait_for_timeout(random.randint(2000, 3500))
    _debug_screenshot(page, username, "05_after_send")

    # Verifica que aparecio nueva burbuja con el texto.
    if not _verify_sent(page, message, baseline_bubbles, composer, timeout_sec=12):
        _debug_screenshot(page, username, "06_verify_fail")
        raise RuntimeError("envio_no_verificado")

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
            claimed = _claim_send_attempt(conn, send_id)
            if not claimed:
                logger.info("autosend SKIP -> @%s (send_id=%s): ya no elegible", username, send_id)
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
                if "ya_contactado" in err:
                    logger.info("autosend SKIP -> @%s: ya contactado previamente", username)
                    _mark_send_state(conn, send_id, "skipped", "ya_contactado")
                    # Marcar prospect para no reintentar
                    try:
                        conn.execute(
                            "UPDATE ig_prospects SET status='contacted', updated_at=? WHERE username=?",
                            (_now_iso(), username),
                        )
                        conn.commit()
                    except Exception:
                        pass
                else:
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
               AND NOT EXISTS (
                 SELECT 1 FROM ig_sends done
                 WHERE done.username=ig_sends.username
                   AND done.id<>ig_sends.id
                   AND done.mode IN ('sent','sent_auto','sending')
               )
               AND NOT EXISTS (
                 SELECT 1 FROM ig_sends earlier
                 WHERE earlier.username=ig_sends.username
                   AND earlier.mode='draft'
                   AND earlier.ready=1
                   AND earlier.id<ig_sends.id
               )
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
