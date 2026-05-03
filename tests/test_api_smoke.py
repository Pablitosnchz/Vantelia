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
            "WHATSAPP_APP_SECRET": "",
            "STRIPE_SECRET_KEY": "sk_test_dummy",
            "STRIPE_WEBHOOK_SECRET": "",
            "STRIPE_PRICE_WEB": "price_test_web",
            "STRIPE_PRICE_WHATSAPP": "price_test_whatsapp",
            "STRIPE_PRICE_COMPLETO": "price_test_completo",
            "STRIPE_PRICE_WEB_ANNUAL": "price_test_web_annual",
            "STRIPE_PRICE_WHATSAPP_ANNUAL": "price_test_whatsapp_annual",
            "STRIPE_PRICE_COMPLETO_ANNUAL": "price_test_completo_annual",
        }
    )
    sys.modules.pop("api", None)
    return importlib.import_module("api")


@pytest.fixture()
def client(api_module):
    return TestClient(api_module.app)


class _FakeStripeSession:
    id = "cs_test_vantelia"
    url = "https://checkout.stripe.test/session/cs_test_vantelia"


class _FakeStripeSessionApi:
    last_create_payload = None

    @classmethod
    def create(cls, **kwargs):
        cls.last_create_payload = kwargs
        return _FakeStripeSession()


class _FakeStripeCheckout:
    Session = _FakeStripeSessionApi


class _FakeStripe:
    api_key = ""
    checkout = _FakeStripeCheckout()


class _FakeOnboardingResult:
    normalized_url = "https://cliente-auto.example"
    detected_business_name = "Cliente Auto"
    suggested_welcome = "Hola, soy Aura. En que puedo ayudarte?"
    info_txt = "\n".join(
        [
            "===== INFORMACION DE CLIENTE AUTO =====",
            "DATOS GENERALES:",
            "- Nombre: Cliente Auto",
            "- Tipo de negocio: Prueba automatica",
            "SERVICIOS Y PRECIOS:",
            "- Servicio: Consulta",
            "  - Precio: A medida",
        ]
    )
    links = ["https://cliente-auto.example"]


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


def test_public_stripe_checkout_builds_subscription_session(client: TestClient, api_module):
    api_module.stripe = _FakeStripe
    _FakeStripeSessionApi.last_create_payload = None

    response = client.post(
        "/subscription/checkout",
        json={"plan": "whatsapp", "billing_period": "monthly"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "url": "https://checkout.stripe.test/session/cs_test_vantelia",
        "session_id": "cs_test_vantelia",
    }
    payload = _FakeStripeSessionApi.last_create_payload
    assert payload["mode"] == "subscription"
    assert payload["line_items"] == [{"price": "price_test_whatsapp", "quantity": 1}]
    assert payload["client_reference_id"] == "public:whatsapp:monthly"
    assert payload["metadata"] == {"source": "public_plans", "plan": "whatsapp", "billing_period": "monthly"}
    assert payload["subscription_data"]["trial_period_days"] == 30
    assert payload["subscription_data"]["metadata"] == payload["metadata"]
    assert [field["key"] for field in payload["custom_fields"]] == ["website", "empresa", "ianame"]
    assert payload["billing_address_collection"] == "required"
    assert payload["phone_number_collection"] == {"enabled": True}
    assert payload["tax_id_collection"] == {"enabled": True}
    assert payload["allow_promotion_codes"] is True


def test_stripe_webhook_activates_client_subscription(client: TestClient, api_module):
    api_module.stripe = _FakeStripe

    response = client.post(
        "/webhooks/stripe",
        json={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "demo",
                    "customer": "cus_test_demo",
                    "subscription": "sub_test_demo",
                    "metadata": {"cliente_id": "demo", "plan": "whatsapp"},
                }
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["received"] is True
    subscription = api_module.CONFIG_CLIENTES["demo"]["subscription"]
    assert subscription["plan"] == "whatsapp"
    assert subscription["status"] == "active"
    assert subscription["stripe_customer_id"] == "cus_test_demo"
    assert subscription["stripe_subscription_id"] == "sub_test_demo"


def test_public_stripe_webhook_creates_client_with_alta_express(client: TestClient, api_module, monkeypatch):
    api_module.stripe = _FakeStripe
    captured_welcome = {}
    monkeypatch.setattr(api_module, "OPENAI_API_KEY", "sk-test-onboarding")
    monkeypatch.setattr(api_module, "run_onboarding", lambda **kwargs: _FakeOnboardingResult())
    monkeypatch.setattr(api_module, "cargar_indice", lambda cliente_id: None)
    monkeypatch.setattr(api_module, "_send_checkout_welcome_email", lambda **kwargs: captured_welcome.update(kwargs))

    response = client.post(
        "/webhooks/stripe",
        json={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "public:pro:monthly",
                    "customer": "cus_test_auto",
                    "subscription": "sub_test_auto",
                    "customer_details": {
                        "email": "cliente.auto@example.com",
                        "name": "Cliente Auto",
                        "phone": "+34600000001",
                    },
                    "custom_fields": [
                        {"key": "website", "text": {"value": "https://cliente-auto.example"}},
                        {"key": "empresa", "text": {"value": "Cliente Auto"}},
                        {"key": "ianame", "text": {"value": "Aura"}},
                    ],
                    "metadata": {
                        "source": "public_plans",
                        "plan": "pro",
                        "billing_period": "monthly",
                    },
                }
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["received"] is True
    assert "cliente_auto" in api_module.CONFIG_CLIENTES
    config = api_module.CONFIG_CLIENTES["cliente_auto"]
    assert config["nombre"] == "Cliente Auto"
    assert config["contacto"]["email"] == "cliente.auto@example.com"
    assert config["contacto"]["telefono"] == "+34600000001"
    assert config["subscription"]["plan"] == "pro"
    assert config["subscription"]["stripe_customer_id"] == "cus_test_auto"
    assert config["subscription"]["stripe_subscription_id"] == "sub_test_auto"
    assert (Path(os.environ["VANTELIA_DATA_DIR"]) / "cliente_auto" / "info.txt").exists()
    assert api_module._get_user_by_email("cliente.auto@example.com")["cliente_id"] == "cliente_auto"
    assert captured_welcome["to_email"] == "cliente.auto@example.com"
    assert captured_welcome["cliente_id"] == "cliente_auto"
    assert captured_welcome["temporary_password"]

    login_response = client.post(
        "/auth/login",
        json={"email": "cliente.auto@example.com", "password": captured_welcome["temporary_password"]},
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["role"] == "client"


def test_admin_can_delete_client(client: TestClient, api_module):
    cliente_id = "cliente_borrable"
    next_configs = dict(api_module.CONFIG_CLIENTES)
    next_configs[cliente_id] = json.loads(json.dumps(api_module.CONFIG_CLIENTES["demo"]))
    next_configs[cliente_id]["nombre"] = "Cliente Borrable"
    api_module._persist_configs_to_disk(next_configs)
    api_module._update_runtime_configs(next_configs)

    data_dir = Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id
    storage_dir = Path(os.environ["VANTELIA_STORAGE_DIR"]) / cliente_id
    data_dir.mkdir(parents=True, exist_ok=True)
    storage_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "info.txt").write_text("Cliente temporal para borrar.", encoding="utf-8")
    api_module._create_user(
        email="cliente.borrable@example.com",
        password="temp-password-123",
        role="client",
        display_name="Cliente Borrable",
        cliente_id=cliente_id,
    )

    response = client.delete(
        f"/admin/clientes/{cliente_id}",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert cliente_id not in api_module.CONFIG_CLIENTES
    assert not data_dir.exists()
    assert not storage_dir.exists()
    assert api_module._get_user_by_email("cliente.borrable@example.com") is None
