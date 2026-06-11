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
