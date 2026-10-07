"""Saca las capturas REALES del portal para el manual de conectar WhatsApp (generar.py).

Levanta el portal en local, en una carpeta temporal y con un negocio de EJEMPLO ("Hotel
Mirador"): ni toca la base de verdad ni ensena datos de ningun cliente. Con un usuario de ese
negocio entra como lo haria el cliente y fotografia:

  img/01_acceso.png      la pantalla de entrada (app.vantelia.es/acceso)
  img/02_whatsapp.png    la pestana WhatsApp con el boton "Conectar mi WhatsApp" resaltado
  img/03_conectado.png   la misma pestana tras conectar ("✓ Conectado")

Volver a sacarlas cuando cambie el portal:

    .venv/Scripts/python.exe scripts/manual_whatsapp/capturas.py

Hace falta Google Chrome instalado (lo usa Playwright) o la variable CHROME_PATH.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SALIDA = Path(__file__).resolve().parent / "img"
NEGOCIO_ID = "hotel_mirador"
USUARIO, CLAVE = "recepcion@hotelmirador.es", "Manual-ejemplo-2026"
PUERTO = 8765
CHROME = os.getenv("CHROME_PATH") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def _entorno(tmp: Path) -> None:
    datos, almacen = tmp / "data", tmp / "storage"
    (datos / NEGOCIO_ID).mkdir(parents=True)
    almacen.mkdir()
    (datos / NEGOCIO_ID / "info.txt").write_text("===== HOTEL MIRADOR =====\nHotel de ejemplo para el manual.\n",
                                                 encoding="utf-8")
    config = {NEGOCIO_ID: {
        "nombre": "Hotel Mirador", "icono": "HM", "color": "#00b1d9", "bienvenida": "Bienvenido al Hotel Mirador.",
        "prompt_extra": "", "allowed_origins": [], "contacto": {"email": USUARIO, "telefono": ""},
        "branding": {"powered_by": "Vantelia"}, "plan": "pro", "subscription": {"plan": "pro", "status": "active"},
        "whatsapp": {"enabled": False}, "booking": {"enabled": False, "timezone": "Europe/Madrid"},
    }}
    (tmp / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    os.environ.update({
        "VANTELIA_DATA_DIR": str(datos), "VANTELIA_STORAGE_DIR": str(almacen),
        "VANTELIA_CONFIG_PATH": str(tmp / "config.json"), "OPENAI_API_KEY": "",
        "ADMIN_API_TOKEN": "manual-local", "PORTAL_ADMIN_EMAIL": "admin@manual.local",
        "PORTAL_ADMIN_PASSWORD": "admin-manual-local-123", "APP_BASE_URL": "http://127.0.0.1:%d" % PUERTO,
        "PORTAL_COOKIE_DOMAIN": "", "EXTRA_CORS_ORIGINS": "http://127.0.0.1:%d" % PUERTO,
        "REMINDER_RUN_INTERVAL_MINUTES": "0", "OUTREACH_DB_PATH": str(almacen / "outreach.db"),
        # Lo justo para que el portal ofrezca el boton de Meta (no se llega a pulsar).
        "WHATSAPP_APP_ID": "000000000000000", "WHATSAPP_APP_SECRET": "manual-local",
        "WHATSAPP_ES_CONFIG_ID": "000000000000000", "WHATSAPP_ES_TENANTS": NEGOCIO_ID,
        "WHATSAPP_ACCESS_TOKEN": "", "SMTP_HOST": "", "STRIPE_SECRET_KEY": "",
        "OAUTH_TOKEN_ENCRYPTION_KEY": "bWFudWFsLWxvY2FsLWNsYXZlLWRlLWVqZW1wbG8tMzI=",
    })


def _servidor():
    import uvicorn

    sys.path.insert(0, str(RAIZ))
    api = importlib.import_module("api")
    api._create_user(email=USUARIO, password=CLAVE, role="client", display_name="Recepción", cliente_id=NEGOCIO_ID)
    servidor = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=PUERTO, log_level="warning",
                                             lifespan="off"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(100):
        if servidor.started:
            return servidor
        time.sleep(0.1)
    raise SystemExit("El portal local no ha arrancado.")


def _conectar_de_mentira() -> None:
    """Lo mismo que deja el alta real al terminar (`_completar_alta_whatsapp`): la cuenta del
    negocio con su token y el canal activo con su numero. Asi el portal pinta lo que vera el
    cliente: "✓ Conectado" y todo en verde."""
    import copy

    from backend import appstate, clients, wa_onboarding

    wa_onboarding.save_account(NEGOCIO_ID, waba_id="100000000000001", phone_number_id="100000000000002",
                               token="token-de-ejemplo", display_phone_number="+34 971 00 00 00",
                               verified_name="Hotel Mirador", mode=wa_onboarding.MODE_COEXISTENCE)
    with appstate.state_lock:
        siguiente = copy.deepcopy(appstate.CONFIG_CLIENTES)
        siguiente[NEGOCIO_ID]["whatsapp"] = {"enabled": True, "phone_number_id": "100000000000002"}
        clients._update_runtime_configs(siguiente)
    clients._persist_configs_to_disk(siguiente)


_SIN_BURBUJA = "() => { const s = document.createElement('style'); s.textContent = "     "'[id^=\"ia-w\"], .ia-w-root, #ia-widget-root { display: none !important; }'; document.head.appendChild(s); }"

_RESALTE = """(sel) => { const e = document.querySelector(sel); if (!e) return false;
  e.scrollIntoView({block: 'center'});
  e.style.outline = '4px solid #FF3D7F'; e.style.outlineOffset = '5px'; e.style.borderRadius = '10px';
  return true; }"""


def main() -> None:
    from playwright.sync_api import sync_playwright

    tmp = Path(tempfile.mkdtemp(prefix="vantelia-manual-"))
    SALIDA.mkdir(exist_ok=True)
    try:
        _entorno(tmp)
        servidor = _servidor()
        base = "http://127.0.0.1:%d" % PUERTO
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=CHROME)
            pagina = navegador.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2,
                                        color_scheme="dark", locale="es-ES")
            pagina.goto(base + "/acceso")
            pagina.wait_for_timeout(900)
            pagina.fill("#email", USUARIO)
            pagina.evaluate(_RESALTE, "#email")
            caja = pagina.evaluate("() => { let e = document.querySelector('#email');"
                                   " while (e && e.parentElement && e.getBoundingClientRect().width < 400)"
                                   " e = e.parentElement; const r = e.getBoundingClientRect();"
                                   " return {x: r.x, y: r.y, w: r.width, h: r.height}; }")
            margen = 28
            pagina.screenshot(path=str(SALIDA / "01_acceso.png"), clip={
                "x": max(0, caja["x"] - margen), "y": max(0, caja["y"] - margen),
                "width": caja["w"] + 2 * margen, "height": min(800 - max(0, caja["y"] - margen), caja["h"] + 2 * margen)})
            pagina.fill("#password", CLAVE)
            pagina.keyboard.press("Enter")
            pagina.wait_for_url("**/app**", timeout=15000)
            pagina.wait_for_timeout(1500)
            pagina.click(".nav-item[data-tab='whatsapp']")
            pagina.wait_for_selector("#waConnectBtn", state="visible", timeout=10000)
            pagina.wait_for_timeout(700)
            pagina.evaluate(_SIN_BURBUJA)
            pagina.evaluate(_RESALTE, "#waConnectBtn")
            pagina.evaluate(_RESALTE, ".nav-item[data-tab='whatsapp']")
            pagina.evaluate(_RESALTE, "#waConnectBtn")  # la tarjeta, centrada en pantalla
            pagina.screenshot(path=str(SALIDA / "02_whatsapp.png"), clip={"x": 0, "y": 0, "width": 1280, "height": 452})
            _conectar_de_mentira()
            pagina.reload()
            pagina.wait_for_timeout(1500)
            pagina.click(".nav-item[data-tab='whatsapp']")
            pagina.wait_for_selector("#waConnectedBox", state="visible", timeout=10000)
            pagina.wait_for_timeout(500)
            pagina.evaluate(_SIN_BURBUJA)
            pagina.evaluate(_RESALTE, "#waConnectedBox")
            pagina.screenshot(path=str(SALIDA / "03_conectado.png"), clip={"x": 0, "y": 0, "width": 1280, "height": 640})
            navegador.close()
        servidor.should_exit = True
        print("Capturas en", SALIDA)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
