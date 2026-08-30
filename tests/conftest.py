"""Fixtures compartidas de la suite de Vantelia.

Los archivos de test historicos definen su propia fixture `api_module`
session-scoped (pytest da precedencia a la local del archivo); los tests
NUEVOS deben usar las de aqui en lugar de duplicar el bloque de entorno.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from fastapi.testclient import TestClient

# --- Cortafuegos: la suite NUNCA sale al mundo real -------------------------
# Incidente ago-2026: `python -m pytest` en local carga el .env de verdad
# (settings.py hace load_dotenv sin override), asi que las credenciales de
# info@vantelia.es llegaban intactas a los tests. Un solo fichero
# (test_booking_exhaustive.py) abria 22 conexiones a smtp.hostinger.com y
# mandaba confirmaciones de cita REALES a test@test.es y @example.com. Cientos
# de rebotes duros -> Hostinger suspendia el envio del buzon y acababa en el
# limite diario. Los tests que ya vaciaban SMTP_HOST a mano estaban a salvo;
# los demas, no.
#
# Dos capas, las dos a nivel de IMPORT de este conftest (antes de que se
# colecte ningun test, antes de que ningun modulo lea el entorno):
#   1. El entorno se deja en blanco -> el codigo se comporta como "sin canal
#      configurado". Se pone "" en vez de borrar la clave: load_dotenv solo
#      rellena lo AUSENTE, asi que el .env ya no puede recolonizarlo.
#   2. smtplib/imaplib bloqueados -> si algun dia alguien vuelve a inyectar un
#      host real, el fallo es ruidoso y dice por que.
# Un test que necesite credenciales falsas las pone en su propio env_overrides
# (se aplica despues) y monkeypatchea el envio.

CREDENCIALES_QUE_NO_ENTRAN_EN_TESTS = (
    # Email transaccional (Hostinger)
    "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL", "SMTP_REPLY_TO",
    # Buzon de captacion (lectura de respuestas)
    "IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD",
    # Email de captacion (Brevo)
    "OUTREACH_SMTP_HOST", "OUTREACH_SMTP_USERNAME", "OUTREACH_SMTP_PASSWORD", "OUTREACH_BCC",
    # Mensajes a personas de verdad
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_DEFAULT_PHONE_NUMBER", "TWILIO_SMS_SENDER",
    "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_APP_SECRET",
    # Modelo de pago
    "OPENAI_API_KEY",
)

for _clave in CREDENCIALES_QUE_NO_ENTRAN_EN_TESTS:
    os.environ[_clave] = ""

# Foto del entorno JUSTO despues de limpiarlo. Los ficheros de test inyectan
# despues sus propias credenciales de mentira (smtp.test.invalid y demas), asi
# que la unica manera honesta de comprobar la limpieza es mirar este momento.
ENTORNO_AL_ARRANCAR_LA_SUITE = {
    clave: os.environ.get(clave, "") for clave in CREDENCIALES_QUE_NO_ENTRAN_EN_TESTS
}

# Stripe: solo se neutraliza la clave VIVA (las de test las ponen los propios
# ficheros y varias dan por hecho que Stripe esta configurado).
if os.environ.get("STRIPE_SECRET_KEY", "").startswith("sk_live_"):
    os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"

# Avisos internos: sin host no sale nada, pero que el destinatario tampoco sea real.
os.environ["CONSULTA_NOTIFICATION_EMAIL"] = "qa-avisos@example.invalid"

_MENSAJE_CORTAFUEGOS = (
    "Los tests no pueden abrir conexiones {proto} de verdad ({host}). "
    "Si el test necesita ejercitar el envio, monkeypatchea la funcion de envio."
)


def _bloquear_salidas_de_red_de_correo() -> None:
    import imaplib
    import smtplib

    def _prohibido(proto, original):
        class Bloqueado(original):  # type: ignore[misc, valid-type]
            def __init__(self, host="", *args, **kwargs):  # noqa: D401
                raise RuntimeError(_MENSAJE_CORTAFUEGOS.format(proto=proto, host=host or "sin host"))

        return Bloqueado

    smtplib.SMTP = _prohibido("SMTP", smtplib.SMTP)
    smtplib.SMTP_SSL = _prohibido("SMTP", smtplib.SMTP_SSL)
    imaplib.IMAP4 = _prohibido("IMAP", imaplib.IMAP4)
    imaplib.IMAP4_SSL = _prohibido("IMAP", imaplib.IMAP4_SSL)


_bloquear_salidas_de_red_de_correo()


DEFAULT_INFO = "\n".join(
    [
        "===== INFORMACION DE AGENCIA IA DEMO =====",
        "SERVICIOS Y PRECIOS:",
        "- Consultoria:",
        "  - Servicio: Auditoria IA",
        "  - Precio: A medida",
        "PREGUNTAS FRECUENTES:",
        "P: Puedo pedir una cita?",
        "R: Si, puedes solicitar una cita desde el formulario.",
    ]
)

DEFAULT_DEMO_CONFIG = {
    "demo": {
        "nombre": "Agencia IA Demo",
        "icono": "AI",
        "color": "#00b1d9",
        "bienvenida": "Hola, soy el asistente demo.",
        "prompt_extra": "Responde solo con informacion de la demo.",
        "allowed_origins": ["http://testserver"],
        "contacto": {"email": "soporte@vantelia.es", "telefono": "+34 600000000"},
        "branding": {"powered_by": "Powered by Vantelia"},
        "plan": "business",
        "subscription": {"plan": "business", "status": "active"},
        "whatsapp": {"enabled": True, "phone_number_id": "1234567890"},
        "booking": {
            "enabled": True,
            "timezone": "Europe/Madrid",
            "slot_minutes": 30,
            "day_start": "09:00",
            "day_end": "10:00",
            "closed_weekdays": [6],
            "provider": "internal",
            "success_message": "Solicitud registrada.",
        },
    }
}


@pytest.fixture(scope="session")
def vantelia_env_factory(tmp_path_factory: pytest.TempPathFactory):
    """Crea un runtime aislado (data/storage/config temporales) y reimporta api.

    El shim de api.py purga backend.* al reimportarse, asi que todo el paquete
    relee el entorno. Uso: api = vantelia_env_factory(config_dict).
    """

    def make(config: dict | None = None, info_txt=DEFAULT_INFO, env_overrides: dict | None = None):
        config = config or DEFAULT_DEMO_CONFIG
        runtime_dir = tmp_path_factory.mktemp("vantelia-runtime")
        data_dir = runtime_dir / "data"
        storage_dir = runtime_dir / "storage"
        config_path = runtime_dir / "config.json"
        storage_dir.mkdir(parents=True)
        infos = info_txt if isinstance(info_txt, dict) else {cid: info_txt for cid in config}
        for cliente_id, texto in infos.items():
            cdir = data_dir / cliente_id
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / "info.txt").write_text(texto, encoding="utf-8")
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        env = {
            "VANTELIA_DATA_DIR": str(data_dir),
            "VANTELIA_STORAGE_DIR": str(storage_dir),
            "VANTELIA_CONFIG_PATH": str(config_path),
            "OPENAI_API_KEY": "",
            "ADMIN_API_TOKEN": "test-admin-token",
            "PORTAL_ADMIN_EMAIL": "admin@example.com",
            "PORTAL_ADMIN_PASSWORD": "test-password-123",
            "APP_BASE_URL": "https://app.test.local",
            "PORTAL_COOKIE_NAME": "vantelia_portal_session",
            "PORTAL_COOKIE_DOMAIN": "",
            "REMINDER_RUN_INTERVAL_MINUTES": "0",
            "WEBHOOK_DEFAULT": "",
            "EXTRA_CORS_ORIGINS": "http://testserver",
            "WHATSAPP_VERIFY_TOKEN": "test-whatsapp-token",
            "WHATSAPP_ACCESS_TOKEN": "",
            "WHATSAPP_APP_SECRET": "",
            "TWILIO_ACCOUNT_SID": "",
            "TWILIO_AUTH_TOKEN": "",
            "TWILIO_DEFAULT_PHONE_NUMBER": "",
            "TWILIO_SMS_SENDER": "",
            "STRIPE_SECRET_KEY": "sk_test_dummy",
            "STRIPE_WEBHOOK_SECRET": "",
            "STRIPE_PRICE_STARTER": "price_test_starter",
            "STRIPE_PRICE_PRO": "price_test_pro",
            "STRIPE_PRICE_BUSINESS": "price_test_business",
            "STRIPE_PRICE_STARTER_ANNUAL": "price_test_starter_annual",
            "STRIPE_PRICE_PRO_ANNUAL": "price_test_pro_annual",
            "STRIPE_PRICE_BUSINESS_ANNUAL": "price_test_business_annual",
            "OUTREACH_DB_PATH": str(storage_dir / "outreach" / "outreach.db"),
            "OUTREACH_TRACKING_SECRET": "test-outreach-secret",
            "OUTREACH_TRACKING_BASE_URL": "https://app.test.local",
            "OUTREACH_RESPECT_WINDOW": "false",
            "TK_DB_PATH": str(storage_dir / "tiktok" / "tiktok.db"),
        }
        env.update(env_overrides or {})
        os.environ.update(env)
        sys.modules.pop("api", None)
        return importlib.import_module("api")

    return make


@pytest.fixture(scope="session")
def api_module(vantelia_env_factory):
    return vantelia_env_factory()


@pytest.fixture()
def client(api_module):
    return TestClient(api_module.app)
