from __future__ import annotations

import importlib
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def api_module(tmp_path_factory: pytest.TempPathFactory):
    runtime_dir = tmp_path_factory.mktemp("vantelia-runtime")
    data_dir = runtime_dir / "data"
    storage_dir = runtime_dir / "storage"
    config_path = runtime_dir / "config.json"
    client_dir = data_dir / "demo"
    client_dir.mkdir(parents=True)
    storage_dir.mkdir(parents=True)

    (client_dir / "info.txt").write_text(
        "\n".join(
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
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps(
            {
                "demo": {
                    "nombre": "Agencia IA Demo",
                    "icono": "AI",
                    "color": "#00b1d9",
                    "bienvenida": "Hola, soy el asistente demo.",
                    "prompt_extra": "Responde solo con informacion de la demo.",
                    "allowed_origins": ["http://testserver"],
                    "contacto": {
                        "email": "soporte@vantelia.es",
                        "telefono": "+34 600000000",
                    },
                    "branding": {"powered_by": "Powered by Vantelia"},
                    "whatsapp": {
                        "enabled": True,
                        "phone_number_id": "1234567890",
                    },
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
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    os.environ.update(
        {
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
        }
    )
    sys.modules.pop("api", None)
    return importlib.import_module("api")


@pytest.fixture()
def client(api_module):
    return TestClient(api_module.app)


def test_healthcheck_reports_runtime_status(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["config"] == "ok"
    assert payload["checks"]["database"] == "ok"
    assert payload["clientes_configurados"] == 1


def test_public_client_config_enforces_allowed_origin(client: TestClient):
    forbidden = client.get("/cliente/demo")
    allowed = client.get("/cliente/demo", headers={"Origin": "http://testserver"})

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["nombre"] == "Agencia IA Demo"


def test_admin_token_protects_client_list(client: TestClient):
    forbidden = client.get("/admin/clientes")
    allowed = client.get("/admin/clientes", headers={"Authorization": "Bearer test-admin-token"})

    assert forbidden.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()[0]["cliente_id"] == "demo"


def test_login_creates_portal_session(client: TestClient):
    response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "test-password-123"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    assert "vantelia_portal_session" in response.cookies


def test_booking_availability_works_without_openai(client: TestClient):
    selected_day = datetime.now() + timedelta(days=1)
    while selected_day.weekday() in {5, 6}:
        selected_day += timedelta(days=1)

    response = client.get(
        "/disponibilidad",
        params={"cliente_id": "demo", "fecha": selected_day.strftime("%Y-%m-%d")},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    assert "slots" in response.json()


def test_legal_pages_are_public(client: TestClient):
    response = client.get("/legal/privacidad")

    assert response.status_code == 200
    assert "Politica de privacidad" in response.text


def test_chat_booking_intent_is_saved_without_openai(client: TestClient):
    chat_response = client.post(
        "/chat",
        json={
            "cliente_id": "demo",
            "mensaje": "Quiero pedir cita",
            "session_id": "s_test_chat_booking",
        },
        headers={"Origin": "http://testserver"},
    )
    list_response = client.get(
        "/admin/chats?cliente_id=demo",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    detail_response = client.get(
        "/admin/chats/s_test_chat_booking?cliente_id=demo",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert chat_response.status_code == 200
    assert chat_response.json()["mostrar_formulario"] is True
    assert list_response.status_code == 200
    assert list_response.json()[0]["session_id"] == "s_test_chat_booking"
    assert "booking" in list_response.json()[0]["intents"]
    assert detail_response.status_code == 200
    assert [message["role"] for message in detail_response.json()["messages"]] == ["user", "assistant"]


def test_whatsapp_webhook_uses_same_chat_storage(client: TestClient):
    verify_response = client.get(
        "/whatsapp/webhook/demo",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test-whatsapp-token",
            "hub.challenge": "challenge-ok",
        },
    )
    webhook_response = client.post(
        "/whatsapp/webhook/demo",
        json={
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "1234567890"},
                                "messages": [
                                    {
                                        "id": "wamid.test-message-1",
                                        "from": "34600000000",
                                        "type": "text",
                                        "text": {"body": "Quiero pedir cita"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        },
    )
    chats_response = client.get(
        "/admin/chats?cliente_id=demo",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert verify_response.status_code == 200
    assert verify_response.text == "challenge-ok"
    assert webhook_response.status_code == 200
    assert webhook_response.json()["processed"] == 1
    assert chats_response.status_code == 200
    assert any(chat["origin"] == "whatsapp:34600000000" for chat in chats_response.json())
