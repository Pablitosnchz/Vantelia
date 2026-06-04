"""WhatsApp Web autosend via Playwright.

Envia mensajes de WhatsApp automaticamente usando una sesion persistente de
WhatsApp Web (tu propio numero, vinculado por QR). Opt-in via
``WA_AUTOSEND_ENABLED=true``. RIESGO de bloqueo del numero por parte de Meta si
se usa para spam — usar un numero secundario y respetar caps + delays.

A diferencia de Instagram (cookies), WhatsApp Web guarda la sesion en
IndexedDB/localStorage, asi que usamos un *user data dir* persistente
(launch_persistent_context) en vez de storage_state JSON.

Flujo de conexion (headless, en el VPS):
    1. start_login_session() abre WhatsApp Web, captura el QR a un PNG.
    2. El panel muestra el PNG; el usuario lo escanea con su movil.
    3. Al detectar la lista de chats, marca la sesion como conectada.

CLI:
    python scripts/whatsapp_autosend.py login    # login interactivo local (headed)
    python scripts/whatsapp_autosend.py status   # estado de la sesion
    python scripts/whatsapp_autosend.py qr        # genera/actualiza el QR (headless)

Env vars:
    WA_AUTOSEND_ENABLED          true para activar.
    WA_SESSION_DIR               user data dir persistente. Default storage/whatsapp/profile
    WA_QR_PATH                   PNG del QR. Default storage/whatsapp/qr.png
    WA_AUTOSEND_HEADLESS         true por defecto.
    WA_AUTOSEND_DAILY_CAP        mensajes/dia (default 20).
    WA_AUTOSEND_MIN_DELAY_SEC    delay min entre mensajes (default 60).
    WA_AUTOSEND_MAX_DELAY_SEC    delay max entre mensajes (default 240).
    WA_AUTOSEND_USER_AGENT       UA opcional.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import quote

logger = logging.getLogger("whatsapp_autosend")

DEFAULT_SESSION_DIR = Path(os.getenv("WA_SESSION_DIR", "storage/whatsapp/profile"))
DEFAULT_QR_PATH = Path(os.getenv("WA_QR_PATH", "storage/whatsapp/qr.png"))
DEFAULT_MARKER = Path("storage/whatsapp/connected.json")
DEFAULT_DEBUG = Path(os.getenv("WA_DEBUG_PATH", "storage/whatsapp/debug_last.png"))
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

WA_WEB = "https://web.whatsapp.com/"

# Selectores que indican sesion iniciada (lista de chats). WhatsApp rota markup;
# usamos varios candidatos estables historicamente.
_LOGGED_IN_SELECTORS = (
    "div#pane-side",
    '[data-testid="chat-list"]',
    '[aria-label="Lista de chats"]',
    '[aria-label="Chat list"]',
    'div[title="Nuevo chat"]',
    'div[title="New chat"]',
)
# Selectores del lienzo del QR en la landing.
_QR_SELECTORS = (
    'div[data-ref] canvas',
    'canvas[aria-label*="Scan"]',
    'canvas[aria-label*="Escanea"]',
    '[data-testid="qrcode"]',
    'canvas',
)
# Composer de mensaje (footer) en la pantalla de chat. WhatsApp rota markup;
# orden de mas a menos especifico.
_COMPOSER_SELECTORS = (
    'div[contenteditable="true"][data-tab="10"]',
    'div[aria-placeholder="Escribe un mensaje"]',
    'div[aria-placeholder="Type a message"]',
    'div[aria-label="Escribe un mensaje"]',
    'div[aria-label="Type a message"]',
    'footer div[contenteditable="true"][role="textbox"]',
    'div[contenteditable="true"][role="textbox"]',
    'footer div[contenteditable="true"]',
    'div[data-testid="conversation-compose-box-input"]',
)
# Boton enviar.
_SEND_SELECTORS = (
    'span[data-icon="send"]',
    '[data-testid="send"]',
    'button[aria-label="Enviar"]',
    'button[aria-label="Send"]',
)


# --------------------------------------------------------------------------
# Helpers basicos
# --------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def is_autosend_enabled() -> bool:
    return _env_bool("WA_AUTOSEND_ENABLED", False)


def _session_dir() -> Path:
    return Path(os.getenv("WA_SESSION_DIR", str(DEFAULT_SESSION_DIR))).expanduser()


def _qr_path() -> Path:
    return Path(os.getenv("WA_QR_PATH", str(DEFAULT_QR_PATH))).expanduser()


def _marker_path() -> Path:
    return DEFAULT_MARKER


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        return sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Playwright no instalado. Ejecuta: pip install playwright==1.47.0 "
            "&& python -m playwright install chromium"
        ) from exc


def _write_marker(connected: bool, extra: Optional[Dict[str, Any]] = None) -> None:
    try:
        p = _marker_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {"connected": connected, "updated_at": _now_iso()}
        if extra:
            data.update(extra)
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception as exc:
        logger.warning("no se pudo escribir marker: %s", exc)


# --------------------------------------------------------------------------
# Estado de sesion
# --------------------------------------------------------------------------

def session_info() -> Dict[str, Any]:
    """Metadata ligera (sin lanzar navegador) sobre la sesion guardada."""
    sess_dir = _session_dir()
    marker = _marker_path()
    has_profile = sess_dir.exists() and any(sess_dir.iterdir()) if sess_dir.exists() else False
    info: Dict[str, Any] = {"connected": False, "path": str(sess_dir), "has_profile": bool(has_profile)}
    if marker.exists():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            info["connected"] = bool(data.get("connected")) and has_profile
            info["saved_at"] = data.get("updated_at")
            if data.get("phone"):
                info["phone"] = data["phone"]
        except Exception:
            pass
    if not has_profile:
        info["connected"] = False
        info["reason"] = "sin sesion vinculada"
    return info


def clear_session() -> bool:
    """Borra el perfil persistente + marker + QR. Devuelve True si habia algo."""
    removed = False
    for target in (_session_dir(),):
        if target.exists():
            import shutil
            shutil.rmtree(target, ignore_errors=True)
            removed = True
    for f in (_marker_path(), _qr_path()):
        try:
            if f.exists():
                f.unlink()
                removed = True
        except Exception:
            pass
    return removed


def _launch_persistent(p, headless: bool):
    sess_dir = _session_dir()
    sess_dir.mkdir(parents=True, exist_ok=True)
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(sess_dir),
        headless=headless,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        user_agent=os.getenv("WA_AUTOSEND_USER_AGENT", DEFAULT_USER_AGENT),
        viewport={"width": 1280, "height": 900},
        locale="es-ES",
    )
    try:
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get: () => undefined});"
        )
    except Exception:
        pass
    return context


def _is_logged_in(page) -> bool:
    for sel in _LOGGED_IN_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                return True
        except Exception:
            continue
    return False


def _capture_qr(page) -> bool:
    """Guarda el QR de la landing en _qr_path(). True si encontro el lienzo."""
    for sel in _QR_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                qr = _qr_path()
                qr.parent.mkdir(parents=True, exist_ok=True)
                loc.screenshot(path=str(qr))
                return True
        except Exception:
            continue
    return False


def start_login_session(timeout_sec: int = 180, headless: bool = True,
                        on_status: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Abre WhatsApp Web headless, captura el QR repetidamente y espera a que el
    usuario lo escanee. Pensado para correr en un hilo de fondo.

    Devuelve {connected: bool, reason}. Mientras corre, va refrescando el PNG del QR.
    """
    def _log(msg: str) -> None:
        logger.info("[wa-login] %s", msg)
        if on_status:
            try:
                on_status(msg)
            except Exception:
                pass

    sync_playwright = _import_playwright()
    deadline = time.time() + max(30, timeout_sec)
    try:
        with sync_playwright() as p:
            context = _launch_persistent(p, headless=headless)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(WA_WEB, wait_until="domcontentloaded", timeout=45000)
            _log("WhatsApp Web cargado, esperando QR / sesion")
            while time.time() < deadline:
                if _is_logged_in(page):
                    _write_marker(True)
                    try:
                        if _qr_path().exists():
                            _qr_path().unlink()
                    except Exception:
                        pass
                    _log("sesion vinculada")
                    context.close()
                    return {"connected": True}
                _capture_qr(page)
                page.wait_for_timeout(2500)
            context.close()
            _log("timeout esperando escaneo")
            return {"connected": False, "reason": "timeout_qr"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[wa-login] error: %s", exc)
        return {"connected": False, "reason": str(exc)[:200]}


def verify_session(timeout_sec: int = 40) -> Dict[str, Any]:
    """Comprueba de verdad (lanzando navegador) si la sesion sigue valida."""
    sync_playwright = _import_playwright()
    try:
        with sync_playwright() as p:
            context = _launch_persistent(p, headless=True)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(WA_WEB, wait_until="domcontentloaded", timeout=45000)
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                if _is_logged_in(page):
                    _write_marker(True)
                    context.close()
                    return {"ok": True}
                # Si aparece QR, la sesion expiro.
                if _looks_logged_out(page) or _capture_qr(page):
                    _capture_qr(page)
                    _write_marker(False)
                    context.close()
                    return {"ok": False, "reason": "sesion_expirada"}
                page.wait_for_timeout(1500)
            context.close()
            return {"ok": False, "reason": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)[:200]}


def latest_qr_bytes() -> Optional[bytes]:
    qr = _qr_path()
    if qr.exists():
        try:
            return qr.read_bytes()
        except Exception:
            return None
    return None


def _debug_path() -> Path:
    return Path(os.getenv("WA_DEBUG_PATH", str(DEFAULT_DEBUG)))


def _debug_shot(page, tag: str = "") -> None:
    """Guarda captura del estado actual del navegador headless para diagnostico."""
    try:
        p = _debug_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(p), full_page=False)
        logger.info("wa debug screenshot (%s) -> %s", tag, p)
    except Exception as exc:
        logger.warning("wa debug shot fail: %s", exc)


def latest_debug_bytes() -> Optional[bytes]:
    p = _debug_path()
    if p.exists():
        try:
            return p.read_bytes()
        except Exception:
            return None
    return None


# --------------------------------------------------------------------------
# Envio
# --------------------------------------------------------------------------

def _human_delay() -> None:
    mn = float(os.getenv("WA_AUTOSEND_MIN_DELAY_SEC", "60") or 60)
    mx = float(os.getenv("WA_AUTOSEND_MAX_DELAY_SEC", "240") or 240)
    if mx < mn:
        mx = mn + 30
    delay = random.uniform(mn, mx)
    logger.info("autosend: sleep %.1fs entre mensajes", delay)
    time.sleep(delay)


def _page_text_ascii(page) -> str:
    try:
        raw = page.inner_text("body") or ""
    except Exception:
        return ""
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", raw.lower())
        if not unicodedata.combining(ch)
    )


def _invalid_number(page) -> bool:
    text = _page_text_ascii(page)
    if not text:
        return False
    return any(
        needle in text
        for needle in (
            "numero de telefono compartido a traves de la url no es valido",
            "numero de telefono compartido mediante el enlace no es valido",
            "phone number shared via url is invalid",
            "no esta en whatsapp",
            "no est? en whatsapp",
            "not on whatsapp",
            "is not on whatsapp",
        )
    )


def _looks_logged_out(page) -> bool:
    text = _page_text_ascii(page)
    if not text:
        return False
    return any(
        needle in text
        for needle in (
            "escanea para iniciar sesion",
            "vincular con el numero de telefono",
            "scan to log in",
            "link with phone number",
        )
    )


def _find_composer(page):
    for sel in _COMPOSER_SELECTORS:
        try:
            loc = page.locator(sel).last
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _click_send(page) -> bool:
    for sel in _SEND_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click(timeout=4000)
                return True
        except Exception:
            continue
    return False


def _send_one(page, phone: str, message: str) -> Dict[str, Any]:
    """Envia un mensaje a un telefono via la URL de WhatsApp Web.

    Devuelve {ok: bool, reason}. El texto va prerelleno por la URL; solo
    confirmamos el composer y pulsamos enviar.
    """
    url = f"{WA_WEB}send?phone={phone}&text={quote(message)}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as exc:
        return {"ok": False, "reason": f"goto:{str(exc)[:80]}"}

    # Espera a composer o a modal de invalido (hasta 45s; WA carga lento).
    deadline = time.time() + 45
    composer = None
    while time.time() < deadline:
        if _invalid_number(page):
            return {"ok": False, "reason": "numero_invalido"}
        if _looks_logged_out(page):
            _capture_qr(page)
            _write_marker(False)
            return {"ok": False, "reason": "sesion_expirada"}
        composer = _find_composer(page)
        if composer is not None:
            break
        page.wait_for_timeout(800)
    if composer is None:
        if _invalid_number(page):
            return {"ok": False, "reason": "numero_invalido"}
        if _looks_logged_out(page):
            _capture_qr(page)
            _write_marker(False)
            return {"ok": False, "reason": "sesion_expirada"}
        _debug_shot(page, "composer")  # captura para diagnostico
        return {"ok": False, "reason": "composer_no_cargo"}

    # Pequena pausa humana, foco y envio.
    page.wait_for_timeout(random.randint(700, 1800))
    try:
        composer.click(timeout=4000)
    except Exception:
        pass
    sent = _click_send(page)
    if not sent:
        # Fallback: Enter envia en WhatsApp Web.
        try:
            page.keyboard.press("Enter")
            sent = True
        except Exception:
            return {"ok": False, "reason": "no_enviado"}
    page.wait_for_timeout(random.randint(1500, 3000))
    return {"ok": True}


def autosend_messages(
    items: Iterable[Dict[str, Any]],
    dry_run: bool = False,
    on_result: Optional[Callable[[str, bool, str], None]] = None,
    on_attempt: Optional[Callable[[str], None]] = None,
    target_ok: Optional[int] = None,
) -> int:
    """Envia hasta WA_AUTOSEND_DAILY_CAP mensajes OK. items: [{phone, message}].

    Llama on_result(phone, ok, reason) por cada uno para que el caller persista.
    Los numeros invalidos no consumen el cap; devuelve cuantos se enviaron OK.
    """
    items = list(items)
    if not items:
        return 0
    cap = int(target_ok if target_ok is not None else (os.getenv("WA_AUTOSEND_DAILY_CAP", "20") or 20))
    cap = max(0, cap)
    if dry_run:
        sent_ok = 0
        for it in items:
            if sent_ok >= cap:
                break
            print(f"[DRY] -> {it.get('phone')}: {(it.get('message') or '')[:60]}...")
            if on_result:
                on_result(it.get("phone", ""), True, "dry_run")
            sent_ok += 1
        return sent_ok

    info = session_info()
    if not info.get("connected"):
        raise RuntimeError("Sesion WhatsApp no conectada. Vincula tu numero primero (QR).")

    headless = _env_bool("WA_AUTOSEND_HEADLESS", True)
    sync_playwright = _import_playwright()
    sent_ok = 0

    with sync_playwright() as p:
        context = _launch_persistent(p, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()
        # Warmup: abrir la home y esperar a que restaure la sesion (la lista de
        # chats tarda 10-30s en aparecer; NO concluir 'expirada' al primer vistazo).
        try:
            page.goto(WA_WEB, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            logger.warning("warmup fallo: %s", exc)
        login_deadline = time.time() + 45
        logged = False
        while time.time() < login_deadline:
            if _is_logged_in(page):
                logged = True
                break
            if _looks_logged_out(page) or _capture_qr(page):
                _capture_qr(page)
                _write_marker(False)
                context.close()
                raise RuntimeError("sesion_expirada")
            page.wait_for_timeout(1500)
        if not logged:
            context.close()
            raise RuntimeError("sesion_expirada")
        page.wait_for_timeout(random.randint(1500, 3500))

        for idx, it in enumerate(items):
            if sent_ok >= cap:
                break
            phone = (it.get("phone") or "").strip()
            message = it.get("message") or ""
            if not phone or not message:
                continue
            if on_attempt:
                try:
                    on_attempt(phone)
                except Exception:
                    pass
            try:
                res = _send_one(page, phone, message)
            except Exception as exc:  # noqa: BLE001
                res = {"ok": False, "reason": str(exc)[:120]}
            ok = bool(res.get("ok"))
            reason = res.get("reason", "")
            if ok:
                sent_ok += 1
                logger.info("wa autosend OK -> %s", phone)
            else:
                logger.warning("wa autosend FAIL -> %s: %s", phone, reason)
            if on_result:
                try:
                    on_result(phone, ok, reason)
                except Exception:
                    pass
            if reason == "sesion_expirada":
                _write_marker(False)
                break
            if sent_ok < cap and idx < len(items) - 1:
                if not ok and reason == "numero_invalido":
                    logger.info("autosend: sin pausa tras numero_invalido -> siguiente")
                else:
                    _human_delay()

        context.close()
    return sent_ok


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cli_login() -> int:
    print("Abriendo WhatsApp Web (headed). Escanea el QR con tu movil...")
    res = start_login_session(timeout_sec=180, headless=False)
    print("Resultado:", res)
    return 0 if res.get("connected") else 1


def _cli_qr() -> int:
    print("Generando QR (headless). Revisa", _qr_path())
    res = start_login_session(timeout_sec=120, headless=True)
    print("Resultado:", res)
    return 0 if res.get("connected") else 1


def _cli_status() -> int:
    print(json.dumps(session_info(), indent=2, ensure_ascii=False))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="WhatsApp Web autosend")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("login")
    sub.add_parser("qr")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.cmd == "login":
        return _cli_login()
    if args.cmd == "qr":
        return _cli_qr()
    if args.cmd == "status":
        return _cli_status()
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
