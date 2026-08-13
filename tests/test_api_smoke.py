from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib
import json
import os
import re
import sqlite3
import sys
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
import httpx
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
                    "plan": "business",
                    "subscription": {"plan": "business", "status": "active"},
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
    )
    sys.modules.pop("api", None)
    return importlib.import_module("api")


@pytest.fixture()
def client(api_module):
    return TestClient(api_module.app)


@pytest.fixture(autouse=True)
def _no_real_outbound_email(monkeypatch, api_module):
    """Nunca enviar emails reales en tests (regla CLAUDE.md).

    El entorno de test carga el .env del proyecto, asi que si hay SMTP/Gmail validos
    los envios saldrian de verdad. Bloqueamos el transporte de mas bajo nivel para que
    el envio falle de forma deterministica (equivale a "correo no entregado"); los
    tests que necesitan un 'enviado' OK parchean una capa superior (_send_booking_email).
    """
    from backend import emailing as _em

    def _blocked(*_a, **_k):
        raise RuntimeError("test: envio de email real deshabilitado")

    # Capa de RED mas baja (no el despachador _send_email_object): asi un test que
    # comprueba la seleccion de proveedor puede sobreescribir estos patches.
    monkeypatch.setattr(_em, "_smtp_send_message", _blocked, raising=False)
    monkeypatch.setattr(_em, "_gmail_send_message", _blocked, raising=False)
    monkeypatch.setattr(_em, "_send_gmail_message", _blocked, raising=False)


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


class _FakeStripeWebhook:
    @staticmethod
    def construct_event(payload, sig_header, secret):
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return json.loads(payload)


class _FakeStripeError:
    class SignatureVerificationError(Exception):
        pass


class _FakeStripe:
    api_key = ""
    checkout = _FakeStripeCheckout()
    Webhook = _FakeStripeWebhook
    error = _FakeStripeError


class _FakeStripeSubscriptionApi:
    current_period_end = int((datetime.now() + timedelta(days=30)).timestamp())

    @classmethod
    def retrieve(cls, subscription_id):
        return {
            "id": subscription_id,
            "status": "active",
            "current_period_end": cls.current_period_end,
            "start_date": int((datetime.now() - timedelta(days=1)).timestamp()),
        }


class _FakeStripeWithSubscription(_FakeStripe):
    Subscription = _FakeStripeSubscriptionApi


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


def test_security_headers_are_sent(client: TestClient):
    response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "max-age=31536000" in response.headers["strict-transport-security"]


def test_public_uploads_static_mount_serves_catalog_images(client: TestClient, api_module):
    image_path = api_module.UPLOADS_DIR / "demo" / "probe.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    try:
        response = client.get("/uploads/demo/probe.png")
        assert response.status_code == 200
        assert response.content == b"\x89PNG\r\n\x1a\n"
        assert response.headers["content-type"].startswith("image/png")
    finally:
        image_path.unlink(missing_ok=True)


def test_new_booking_config_defaults_to_sunday_closed(api_module):
    normalized = api_module._normalize_client_config(
        "nuevo_cliente",
        {
            "nombre": "Nuevo Cliente",
            "icono": "NC",
            "color": "#00b1d9",
            "bienvenida": "Hola, soy el asistente.",
            "prompt_extra": "",
            "booking": {"enabled": True},
        },
    )

    assert normalized["booking"]["closed_weekdays"] == [6]
    assert all(normalized["booking"]["message_template_enabled"].values())


def test_unrestricted_employee_accepts_generic_service_name(api_module):
    employee = next(row for row in api_module._list_public_employee_rows("demo") if row["is_default"])

    assert api_module._service_name_allowed_for_employee("demo", employee, "Consulta general") is True


def test_service_duration_resolves_regardless_of_accents(api_module):
    """La duracion debe resolverse aunque el servicio llegue con la tilde en otra
    forma Unicode (NFD), sin tilde, en otra caja o como etiqueta completa. Si no,
    cae al slot del profesional y un servicio de 75 min se trataria como 30."""
    cliente_id = "demo"
    db_path = api_module.DB_PATH
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "DELETE FROM services WHERE cliente_id = ? AND slug = 'masaje_antiestr_s'",
            (cliente_id,),
        )
        conn.execute(
            """
            INSERT INTO services
                (cliente_id, slug, name, duration_minutes, price_cents, description, is_active, sort_order, created_at, updated_at)
            VALUES (?, 'masaje_antiestr_s', 'Masaje Antiestrés', 75, 8000, '', 1, 50, 'now', 'now')
            """,
            (cliente_id,),
        )
        conn.commit()
    try:
        variants = [
            "Masaje Antiestrés",                                   # NFC tal cual
            unicodedata.normalize("NFD", "Masaje Antiestrés"),    # tilde descompuesta
            "Masaje Antiestres",                                   # sin tilde
            "  masaje   ANTIESTRÉS ",                              # caja/espacios
            "Masaje Antiestrés · 75 min · 80€",                   # etiqueta completa
        ]
        for variant in variants:
            assert (
                api_module._service_duration_minutes(cliente_id, variant) == 75
            ), f"no resolvio 75 min para {variant!r}"
    finally:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "DELETE FROM services WHERE cliente_id = ? AND slug = 'masaje_antiestr_s'",
                (cliente_id,),
            )
            conn.commit()


def test_service_extraction_keeps_scraper_descriptions(api_module):
    demo_services = api_module._extract_services_from_info("demo")
    assert demo_services[0]["nombre"] == "Auditoria IA"
    assert "Categoria: Consultoria" in demo_services[0]["descripcion"]
    assert "Precio: A medida" in demo_services[0]["descripcion"]

    cliente_id = f"svc_{uuid.uuid4().hex[:8]}"
    client_dir = api_module.DATA_DIR / cliente_id
    client_dir.mkdir(parents=True, exist_ok=True)
    (client_dir / "info.txt").write_text(
        "\n".join(
            [
                "SERVICIOS Y PRECIOS:",
                "1. Starter",
                "- Precio: 19 EUR al mes",
                "- Incluye leads, documentos y personalizacion de marca.",
                "",
                "2. Pro",
                "- Precio: 49 EUR al mes",
                "- Incluye reservas, agenda integrada y Live Chat.",
                "",
                "PREGUNTAS FRECUENTES:",
                "P: Algo?",
            ]
        ),
        encoding="utf-8",
    )

    services = api_module._extract_services_from_info(cliente_id)
    assert [item["nombre"] for item in services] == ["Starter", "Pro"]

    compact_id = f"svc_compact_{uuid.uuid4().hex[:8]}"
    compact_dir = api_module.DATA_DIR / compact_id
    compact_dir.mkdir(parents=True, exist_ok=True)
    (compact_dir / "info.txt").write_text(
        "\n".join(
            [
                "SERVICIOS Y PRECIOS:",
                "- Masaje Descontracturante / 60€ / 55 min",
                "- Masaje Relajante / Desde 35€ / 1 sesión Individual",
                "- Masaje a Cuatro Manos / 80€ / 75 min",
                "- Ritual Premium - 95 EUR - 1 h 30 min",
                "- Drenaje Linfático: 75€ · 75 min",
                "- Reflexología Podal | 60 EUR | 50 min",
                "- Bonos de 5 sesiones: 12% dto.",
                "- Bonos de 10 sesiones: 15% dto.",
                "",
                "PREGUNTAS FRECUENTES:",
            ]
        ),
        encoding="utf-8",
    )
    compact = api_module._extract_services_from_info(compact_id)
    assert [item["nombre"] for item in compact] == [
        "Masaje Descontracturante",
        "Masaje Relajante",
        "Masaje a Cuatro Manos",
        "Ritual Premium",
        "Drenaje Linfático",
        "Reflexología Podal",
    ]
    assert compact[0]["price_cents"] == 6000
    assert compact[0]["duration_minutes"] == 55
    assert compact[1]["price_cents"] == 3500
    assert compact[2]["duration_minutes"] == 75
    assert compact[3]["price_cents"] == 9500
    assert compact[3]["duration_minutes"] == 90
    assert compact[4]["price_cents"] == 7500
    assert compact[5]["duration_minutes"] == 50
    assert "Precio: 19 EUR al mes" in services[0]["descripcion"]
    assert "personalizacion de marca" in services[0]["descripcion"]

    variants_id = f"svc_variants_{uuid.uuid4().hex[:8]}"
    variants_dir = api_module.DATA_DIR / variants_id
    variants_dir.mkdir(parents=True, exist_ok=True)
    (variants_dir / "info.txt").write_text(
        "\n".join(
            [
                "SERVICIOS Y PRECIOS:",
                "- Servicio: Masaje Futura Mama",
                "  - Precio: 60 EUR (50 min) / 80 EUR (75 min)",
                "  - Detalle: Tratamiento para futuras mamas.",
                "- Servicio: Masaje a Cuatro Manos",
                "  - Precio: 110 EUR (50 min) / 160 EUR (80 min)",
                "  - Detalle: Dos terapeutas trabajan simultaneamente.",
                "",
                "PREGUNTAS FRECUENTES:",
            ]
        ),
        encoding="utf-8",
    )
    variants = api_module._extract_services_from_info(variants_id)
    assert [item["nombre"] for item in variants] == ["Masaje Futura Mama", "Masaje a Cuatro Manos"]
    assert variants[0]["price_cents"] == 6000
    assert variants[0]["duration_minutes"] == 50
    assert variants[1]["price_cents"] == 11000
    assert variants[1]["duration_minutes"] == 50


def test_scraped_services_sync_into_catalog_table(api_module):
    cliente_id = f"svc_sync_{uuid.uuid4().hex[:8]}"
    client_dir = api_module.DATA_DIR / cliente_id
    client_dir.mkdir(parents=True, exist_ok=True)
    info_path = client_dir / "info.txt"
    info_path.write_text(
        "\n".join(
            [
                "SERVICIOS Y PRECIOS:",
                "- Masaje Relajante / 60 EUR / 50 min",
                "- Ritual Sakura / 95 EUR / 1 h 30 min",
                "",
                "PREGUNTAS FRECUENTES:",
            ]
        ),
        encoding="utf-8",
    )

    created = api_module._sync_services_from_info(cliente_id)
    assert created == {"created": 2, "updated": 0, "detected": 2}

    with sqlite3.connect(api_module.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT slug, name, duration_minutes, price_cents, is_active FROM services WHERE cliente_id=? ORDER BY slug",
            (cliente_id,),
        ).fetchall()
    assert {row[0] for row in rows} == {"masaje_relajante", "ritual_sakura"}
    assert any(row[1] == "Masaje Relajante" and row[2] == 50 and row[3] == 6000 and row[4] == 1 for row in rows)
    assert any(row[1] == "Ritual Sakura" and row[2] == 90 and row[3] == 9500 and row[4] == 1 for row in rows)

    info_path.write_text(
        "\n".join(
            [
                "SERVICIOS Y PRECIOS:",
                "- Masaje Relajante / 65 EUR / 55 min",
                "- Ritual Sakura / 95 EUR / 1 h 30 min",
                "",
                "PREGUNTAS FRECUENTES:",
            ]
        ),
        encoding="utf-8",
    )
    updated = api_module._sync_services_from_info(cliente_id)
    assert updated == {"created": 0, "updated": 2, "detected": 2}

    with sqlite3.connect(api_module.DB_PATH) as conn:
        row = conn.execute(
            "SELECT duration_minutes, price_cents FROM services WHERE cliente_id=? AND slug='masaje_relajante'",
            (cliente_id,),
        ).fetchone()
    assert row == (55, 6500)


def test_onboarding_merges_detected_service_candidates():
    import onboarding_utils

    info = "\n".join(
        [
            "SERVICIOS Y PRECIOS:",
            "- Servicio: Masaje Relajante",
            "  - Precio: 35 EUR",
            "- Servicio: Masaje Descontracturante",
            "  - Precio: 35 EUR",
            "- Servicio: Masaje con Piedras Calientes",
            "  - Precio: 65 EUR",
            "",
            "TARJETAS REGALO, BONOS Y PRODUCTOS:",
            "- Tarjetas regalo: No especificado en la web",
        ]
    )
    merged = onboarding_utils._merge_detected_service_candidates(
        info,
        [
            {"name": "Masaje Relajante", "price": "35 EUR", "duration": "50 min", "url": "https://example.com/a"},
            {"name": "Masajes", "price": "A consultar", "duration": "", "url": "https://example.com/generic"},
            {"name": "Masaje Descontractuante", "price": "A consultar", "duration": "", "url": "https://example.com/des"},
            {"name": "Masaje Piedras Calientes", "price": "A consultar", "duration": "55 min", "url": "https://example.com/stones"},
            {"name": "Masaje 2 personas", "price": "A consultar", "duration": "75 min", "url": "https://example.com/two"},
            {"name": "Shiatsu", "price": "A consultar", "duration": "55 min", "detail": "Tecnica japonesa.", "url": "https://example.com/shiatsu"},
        ],
    )
    assert merged.count("- Servicio: Masaje Relajante") == 1
    assert "- Servicio: Masajes" not in merged
    assert "- Servicio: Masaje Descontractuante" not in merged
    assert "- Servicio: Masaje Piedras Calientes" not in merged
    assert "- Servicio: Masaje 2 personas" not in merged
    assert "- Servicio: Shiatsu" in merged
    assert "  - Duracion: 55 min" in merged
    assert merged.index("- Servicio: Shiatsu") < merged.index("TARJETAS REGALO")


def test_vantelia_commercial_brain_matches_public_pricing():
    info = (REPO_ROOT / "data" / "Vantelia" / "info.txt").read_text(encoding="utf-8")

    for expected in (
        "1. Free",
        "Precio: 0 EUR al mes",
        "2. Starter",
        "Precio: 19 EUR al mes",
        "3. Pro",
        "Precio: 49 EUR al mes",
        "4. Business",
        "Precio: 149 EUR al mes",
        "Free es gratis para siempre",
    ):
        assert expected in info

    for forbidden in (
        "Asistente IA Web",
        "Asistente IA WhatsApp",
        "Plan Completo",
        "Precio: 79 EUR",
        "Precio: 89 EUR",
        "30 dias gratis",
    ):
        assert forbidden not in info


def test_self_serve_schema_v2_is_provisioned(client: TestClient, api_module):
    """Sem 1: clientes table mirrors config.json, users has google_sub/email_verified,
    and the new self-serve tables (subscriptions, kb_documents, bot_leads,
    live_chat_sessions, message_usage_events) exist and are queryable."""
    connection = sqlite3.connect(api_module.DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for required in {
            "clientes",
            "subscriptions",
            "kb_documents",
            "bot_leads",
            "live_chat_sessions",
            "message_usage_events",
        }:
            assert required in tables, f"Falta tabla {required}"

        user_cols = {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
        for col in {"google_sub", "email_verified", "signup_source", "avatar_url"}:
            assert col in user_cols, f"Falta columna users.{col}"

        mirrored = {
            row["cliente_id"]: dict(row)
            for row in connection.execute(
                "SELECT cliente_id, plan, owner_user_id, source FROM clientes"
            ).fetchall()
        }
        assert "demo" in mirrored, "El cliente legacy demo no se ha replicado a la tabla clientes"
        assert mirrored["demo"]["source"] == "legacy"
        assert mirrored["demo"]["owner_user_id"] == ""
    finally:
        connection.close()


def test_self_serve_helpers_persist_owner_and_subscription(api_module):
    """Ownership y suscripciones free se mantienen tras mutaciones de config.json."""
    api_module.db_set_client_owner("demo", "user_test_owner", source="self_serve")
    try:
        # Re-persistir el config sin tocar nada debe preservar owner/source.
        api_module._persist_configs_to_disk(api_module.CONFIG_CLIENTES)
        assert api_module.db_get_client_owner("demo") == "user_test_owner"
        row = api_module.db_get_client_row("demo")
        assert row is not None
        assert row["source"] == "self_serve"

        sub = api_module.db_ensure_free_subscription("user_test_owner", cliente_id="demo")
        assert sub["plan"] == "free"
        assert sub["messages_quota"] >= 1
        sub_again = api_module.db_ensure_free_subscription("user_test_owner")
        assert sub_again["id"] == sub["id"], "ensure_free_subscription debe ser idempotente"
    finally:
        # Limpieza para no contaminar otros tests de la sesion.
        connection = sqlite3.connect(api_module.DB_PATH)
        try:
            connection.execute(
                "UPDATE clientes SET owner_user_id='', source='legacy' WHERE cliente_id='demo'"
            )
            connection.execute(
                "DELETE FROM subscriptions WHERE user_id='user_test_owner'"
            )
            connection.commit()
        finally:
            connection.close()


def test_public_client_config_enforces_allowed_origin(client: TestClient):
    forbidden = client.get("/cliente/demo")
    allowed = client.get("/cliente/demo", headers={"Origin": "http://testserver"})

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["nombre"] == "Agencia IA Demo"


def test_cors_preflight_allows_app_methods_and_credentials(client: TestClient):
    response = client.options(
        "/auth/app/leads/lead_test",
        headers={
            "Origin": "http://testserver",
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "http://testserver"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "DELETE" in response.headers["access-control-allow-methods"]
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_public_client_config_includes_base_starters_with_booking(
    client: TestClient, api_module
):
    """/cliente/{id} fuses BASE_STARTERS with extras. Booking enabled → all 3 base."""
    api_module.CONFIG_CLIENTES["demo"]["starter_questions"] = ["¿Cuanto cuesta?", "¿Hay parking?"]
    resp = client.get("/cliente/demo", headers={"Origin": "http://testserver"})
    assert resp.status_code == 200
    starters = resp.json()["starter_questions"]
    assert starters[:3] == ["Agendar cita", "Información servicios", "Preguntas frecuentes"]
    assert "¿Cuanto cuesta?" in starters
    assert "¿Hay parking?" in starters
    assert len(starters) == 5


def test_public_client_config_omits_agendar_when_booking_disabled(
    client: TestClient, api_module
):
    """When booking disabled, 'Agendar cita' must not appear in /cliente/{id} starters."""
    api_module.CONFIG_CLIENTES["demo"]["booking"]["enabled"] = False
    api_module.CONFIG_CLIENTES["demo"]["starter_questions"] = []
    try:
        resp = client.get("/cliente/demo", headers={"Origin": "http://testserver"})
        assert resp.status_code == 200
        starters = resp.json()["starter_questions"]
        assert "Agendar cita" not in starters
        assert "Información servicios" in starters
        assert "Preguntas frecuentes" in starters
    finally:
        api_module.CONFIG_CLIENTES["demo"]["booking"]["enabled"] = True


def test_persist_strips_base_from_extras(client: TestClient, api_module):
    """Base entries submitted by client are filtered out before persisting."""
    api_module.CONFIG_CLIENTES["demo"]["starter_questions"] = []
    saved = api_module._strip_base_from_extras(
        ["Agendar cita", "Información servicios", "¿Cuanto cuesta?", "Preguntas frecuentes", "¿Hacen envios?"]
    )
    assert saved == ["¿Cuanto cuesta?", "¿Hacen envios?"]


def test_admin_token_protects_client_list(client: TestClient):
    forbidden = client.get("/admin/clientes")
    allowed = client.get("/admin/clientes", headers={"Authorization": "Bearer test-admin-token"})

    assert forbidden.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()[0]["cliente_id"] == "demo"


def test_admin_demo_agenda_seed_and_purge(client: TestClient, api_module):
    headers = {"Authorization": "Bearer test-admin-token"}
    db_path = api_module.DB_PATH

    def _counts():
        with sqlite3.connect(db_path) as conn:
            bookings = conn.execute(
                "SELECT COUNT(*) FROM bookings WHERE cliente_id='demo' AND source='demo_seed'"
            ).fetchone()[0]
            emps = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE cliente_id='demo' AND id LIKE 'empdemo_%'"
            ).fetchone()[0]
        return bookings, emps

    def _active_locations():
        with sqlite3.connect(db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM locations WHERE cliente_id='demo' AND is_active=1"
            ).fetchone()[0]

    def _booking_location_spread():
        with sqlite3.connect(db_path) as conn:
            return conn.execute(
                "SELECT COUNT(DISTINCT location_id) FROM bookings WHERE cliente_id='demo' AND source='demo_seed'"
            ).fetchone()[0]

    # Protegido sin token de admin.
    assert client.post("/admin/clientes/demo/demo-agenda").status_code == 401

    gen = client.post("/admin/clientes/demo/demo-agenda", headers=headers)
    assert gen.status_code == 200
    assert gen.json()["ok"] is True
    bookings, emps = _counts()
    assert bookings > 0
    # Un equipo por centro: empleados = centros activos * tamaño de equipo demo.
    assert emps == _active_locations() * api_module._DEMO_TEAM_SIZE
    # La demo crea centros adicionales y reparte la agenda: citas en >1 centro.
    assert _active_locations() > 1
    assert _booking_location_spread() > 1

    # Idempotente: regenerar no acumula profesionales ni centros demo.
    assert client.post("/admin/clientes/demo/demo-agenda", headers=headers).status_code == 200
    _, emps_again = _counts()
    assert emps_again == _active_locations() * api_module._DEMO_TEAM_SIZE

    rm = client.delete("/admin/clientes/demo/demo-agenda", headers=headers)
    assert rm.status_code == 200
    assert _counts() == (0, 0)


def test_demo_page_includes_voice_call_ui(client: TestClient):
    # El demo debe seguir sirviendo el chat (widget) y ademas el boton/overlay de
    # la "llamada simulada" por voz.
    resp = client.get("/demo/demo")
    assert resp.status_code == 200
    # La pagina del demo debe permitir el microfono (self) para la llamada simulada,
    # sin abrir el resto del sitio (que mantiene microphone=()).
    assert "microphone=(self)" in resp.headers.get("Permissions-Policy", "")
    html = resp.text
    assert "ia-w-btn" not in html or "widget.min.js" in html  # widget de chat presente
    assert 'id="vdemoCallBtn"' in html
    assert "Llamar al asistente" in html
    assert 'id="vdemoOverlay"' in html
    assert "/voice/session" in html
    # La config JS quedo inyectada (placeholders sustituidos).
    assert '"cliente": "demo"' in html
    for leftover in ("__VOICE_CFG__", "__NOMBRE__", "__INITIAL__", "__COLOR__"):
        assert leftover not in html
    # No se filtra la API key de OpenAI en la pagina.
    assert "OPENAI_API_KEY" not in html


def test_demo_voice_session_requires_openai_key(client: TestClient):
    # En el entorno de test OPENAI_API_KEY="" -> 503 antes de llamar a OpenAI.
    resp = client.post("/demo/demo/voice/session")
    assert resp.status_code == 503


def test_demo_voice_session_unknown_client_404(client: TestClient):
    resp = client.post("/demo/clientequenoexiste/voice/session")
    assert resp.status_code == 404


def test_admin_app_and_onboarding_redirect_to_dashboard(client: TestClient, api_module):
    # Un admin no tiene portal de cliente ni onboarding. Si llega a /app o /onboarding
    # (bookmark o ?next heredado tras login), debe ir a /dashboard, NO al wizard.
    cookies = _portal_admin_cookies(api_module)
    r_app = client.get("/app", cookies=cookies, follow_redirects=False)
    assert r_app.status_code in (302, 307)
    assert r_app.headers["location"] == "/dashboard"
    r_onb = client.get("/onboarding", cookies=cookies, follow_redirects=False)
    assert r_onb.status_code in (302, 307)
    assert r_onb.headers["location"] == "/dashboard"
    # El panel admin sigue sirviendose en /dashboard (sin redirigir).
    r_dash = client.get("/dashboard", cookies=cookies, follow_redirects=False)
    assert r_dash.status_code == 200


def test_demo_seed_never_touches_payment_logic(api_module, monkeypatch):
    # Regresion 504: el sembrado demo debe usar skip_payment y NO pasar por la logica
    # de pago. Antes, un servicio demo payment_required disparaba un checkout Stripe real
    # por cada cita (flood sincrono que bloqueaba el worker -> 504). Forzamos fallo si se
    # invoca cualquiera de las dos funciones de pago durante el seed.
    from backend import booking as bk, demo_agenda as da

    def _boom(*args, **kwargs):
        raise AssertionError("el sembrado demo no debe invocar la logica de pago")

    monkeypatch.setattr(bk, "resolve_payment_requirement", _boom)
    monkeypatch.setattr(bk, "_booking_payment_after_store", _boom)
    try:
        da._seed_demo_agenda("demo")
        with sqlite3.connect(api_module.DB_PATH) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM bookings WHERE cliente_id='demo' AND source=?",
                (api_module.DEMO_BOOKING_SOURCE,),
            ).fetchone()[0]
            pending_pay = conn.execute(
                "SELECT COUNT(*) FROM bookings WHERE cliente_id='demo' AND source=? AND status='pending_payment'",
                (api_module.DEMO_BOOKING_SOURCE,),
            ).fetchone()[0]
        assert total > 0
        assert pending_pay == 0
    finally:
        da._purge_demo_agenda("demo")


def test_demo_agenda_uses_visible_services_catalog(client: TestClient, api_module):
    headers = {"Authorization": "Bearer test-admin-token"}
    cliente_id = "demo"
    db_path = api_module.DB_PATH
    client_dir = api_module.DATA_DIR / cliente_id
    info_path = client_dir / "info.txt"
    original_info = info_path.read_text(encoding="utf-8")
    try:
        info_path.write_text(
            "\n".join(
                [
                    "SERVICIOS Y PRECIOS:",
                    "- Masaje visible / 60 EUR / 55 min",
                    "- Bonos de 5 sesiones: 12% dto.",
                    "",
                    "PREGUNTAS FRECUENTES:",
                ]
            ),
            encoding="utf-8",
        )
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM services WHERE cliente_id = ?", (cliente_id,))
            conn.execute(
                """
                INSERT INTO services
                    (cliente_id, slug, name, duration_minutes, price_cents, description, is_active, sort_order, created_at, updated_at)
                VALUES (?, 'masaje_visible', 'Masaje visible', 55, 6000, '', 1, 0, 'now', 'now')
                """,
                (cliente_id,),
            )
            conn.commit()

        gen = client.post(f"/admin/clientes/{cliente_id}/demo-agenda", headers=headers)
        assert gen.status_code == 200, gen.text
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT servicio, start_at, end_at, service_id, service_price_cents "
                "FROM bookings WHERE cliente_id = ? AND source = ?",
                (cliente_id, api_module.DEMO_BOOKING_SOURCE),
            ).fetchall()
            services = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT servicio FROM bookings WHERE cliente_id = ? AND source = ?",
                    (cliente_id, api_module.DEMO_BOOKING_SOURCE),
                ).fetchall()
            }
            demo_services_seeded = conn.execute(
                "SELECT COUNT(*) FROM services WHERE cliente_id = ? AND slug LIKE ?",
                (cliente_id, api_module.DEMO_SERVICE_SLUG_PREFIX + "%"),
            ).fetchone()[0]
        assert rows
        # El catalogo real visible del tenant se sigue respetando (se reserva).
        assert "Masaje visible" in services
        # Y ademas el demo siembra servicios propios de varias casuisticas de pago.
        assert demo_services_seeded > 0
        assert any(s != "Masaje visible" for s in services)
        # Las citas del servicio real visible mantienen su duracion/precio del catalogo.
        masaje_rows = [r for r in rows if r[3] == "masaje_visible"]
        assert masaje_rows
        for _, start_at, end_at, service_id, service_price_cents in masaje_rows:
            start_dt = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
            assert int((end_dt - start_dt).total_seconds() // 60) == 55
            assert service_price_cents == 6000
    finally:
        info_path.write_text(original_info, encoding="utf-8")
        api_module._purge_demo_agenda(cliente_id)
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM services WHERE cliente_id = ?", (cliente_id,))
            conn.commit()


def _seed_past_booking(api_module, status: str = "confirmed") -> str:
    booking_id = uuid.uuid4().hex
    start = datetime.utcnow() - timedelta(hours=2)
    end = start + timedelta(minutes=30)
    iso = lambda d: d.isoformat(timespec="seconds") + "Z"
    api_module._store_booking({
        "id": booking_id, "cliente_id": "demo", "employee_id": "", "employee_name": "",
        "nombre": "Cliente Prueba", "email": "prueba@example.com", "telefono": "",
        "servicio": "Consulta", "booking_date": start.date().isoformat(),
        "booking_time": start.strftime("%H:%M"), "notas": "", "status": status,
        "provider_name": "internal", "provider_status": status, "provider_booking_id": "",
        "provider_booking_url": "", "manage_token": f"mg_{booking_id}", "timezone": "Europe/Madrid",
        "start_at": iso(start), "end_at": iso(end),
        "confirmed_at": iso(start) if status == "confirmed" else "", "cancelled_at": "",
        "rescheduled_at": "", "rescheduled_from_booking_id": "", "confirmation_email_sent_at": "",
        "reminder_24h_sent_at": "", "reminder_2h_sent_at": "", "customer_email_status": "",
        "customer_email_last_error": "", "source": "test", "created_at": iso(start),
    })
    return booking_id


def test_booking_attendance_marks_completed_and_no_show(client: TestClient, api_module):
    user = api_module._get_user_by_email("admin@example.com")
    raw_session = api_module._create_auth_session(user["id"])
    cookies = {"vantelia_portal_session": raw_session}

    booking_id = _seed_past_booking(api_module)

    def _db_state():
        with sqlite3.connect(api_module.DB_PATH) as conn:
            return conn.execute(
                "SELECT status, completed_source FROM bookings WHERE id = ?", (booking_id,)
            ).fetchone()

    # No-show.
    r = client.post(f"/auth/bookings/{booking_id}/attendance", json={"attended": False}, cookies=cookies)
    assert r.status_code == 200
    assert r.json()["estado"] == "no_show"
    assert _db_state() == ("no_show", "manual")

    # Corregir a realizada.
    r = client.post(f"/auth/bookings/{booking_id}/attendance", json={"attended": True}, cookies=cookies)
    assert r.status_code == 200
    assert r.json()["estado"] == "completed"
    assert _db_state() == ("completed", "manual")

    # Stats de cliente exponen asistencia.
    stats = client.get("/auth/dashboard", params={"cliente_id": "demo"}, cookies=cookies).json()["stats"]
    assert "completed" in stats and "no_show" in stats and "attendance_rate" in stats

    # No se puede marcar asistencia de una cancelada.
    cancelled_id = _seed_past_booking(api_module, status="cancelled")
    r = client.post(f"/auth/bookings/{cancelled_id}/attendance", json={"attended": True}, cookies=cookies)
    assert r.status_code == 409

    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE id IN (?, ?)", (booking_id, cancelled_id))
        conn.commit()


def test_staff_can_create_booking_manually(client: TestClient, api_module):
    user = api_module._get_user_by_email("admin@example.com")
    raw_session = api_module._create_auth_session(user["id"])
    cookies = {"vantelia_portal_session": raw_session}

    target = datetime.utcnow().date() + timedelta(days=2)
    while target.weekday() == 6:  # domingo cerrado en demo
        target += timedelta(days=1)
    fecha = target.isoformat()

    r = client.post(
        "/auth/bookings",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={
            "nombre": "Walk In", "email": "", "telefono": "600111222", "servicio": "",
            "employee_id": "", "fecha": fecha, "hora": "09:00", "notas": "manual",
        },
    )
    assert r.status_code == 200, r.text
    booking_id = r.json()["booking_id"]
    assert r.json()["estado"] == "confirmed"
    with sqlite3.connect(api_module.DB_PATH) as conn:
        row = conn.execute(
            "SELECT status, source, nombre FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
    assert row == ("confirmed", "portal_manual", "Walk In")

    # Mismo hueco/profesional otra vez -> conflicto.
    r2 = client.post(
        "/auth/bookings",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={
            "nombre": "Otro", "email": "", "telefono": "", "servicio": "",
            "employee_id": "", "fecha": fecha, "hora": "09:00", "notas": "",
        },
    )
    assert r2.status_code == 409

    r3 = client.post(
        "/auth/bookings",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={
            "nombre": "Sin Contacto", "email": "", "telefono": "", "servicio": "",
            "employee_id": "", "fecha": fecha, "hora": "09:30", "notas": "",
        },
    )
    assert r3.status_code == 200, r3.text
    no_contact_id = r3.json()["booking_id"]
    assert r3.json()["warning"]
    with sqlite3.connect(api_module.DB_PATH) as conn:
        missing_event = conn.execute(
            "SELECT COUNT(*) FROM booking_audit WHERE booking_id=? AND event_type='booking_contact_missing'",
            (no_contact_id,),
        ).fetchone()[0]
    assert missing_event == 1

    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE id IN (?, ?)", (booking_id, no_contact_id))
        conn.commit()


def test_public_booking_requires_contact_but_accepts_phone_only(client: TestClient, api_module):
    origin = {"Origin": "http://testserver"}
    target = datetime.utcnow().date() + timedelta(days=17)
    while target.weekday() == 6:
        target += timedelta(days=1)
    fecha = target.isoformat()

    missing = client.post(
        "/agendar",
        headers=origin,
        json={
            "cliente_id": "demo", "nombre": "Sin Contacto", "email": "", "telefono": "",
            "servicio": "", "employee_id": "", "fecha": fecha, "hora": "09:00", "notas": "",
        },
    )
    assert missing.status_code == 400
    assert "email o telefono" in missing.json()["detail"].lower()

    phone_only = client.post(
        "/agendar",
        headers=origin,
        json={
            "cliente_id": "demo", "nombre": "Solo Telefono", "email": "", "telefono": "600111222",
            "servicio": "", "employee_id": "", "fecha": fecha, "hora": "09:00", "notas": "",
        },
    )
    assert phone_only.status_code == 200, phone_only.text
    booking_id = phone_only.json()["booking_id"]
    try:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            row = conn.execute(
                "SELECT email, telefono, source FROM bookings WHERE id = ?",
                (booking_id,),
            ).fetchone()
        assert row == ("", "600111222", "widget")
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
            conn.execute("DELETE FROM booking_audit WHERE booking_id = ?", (booking_id,))
            conn.commit()


def test_multilocation_isolation_and_crud(client: TestClient, api_module):
    user = api_module._get_user_by_email("admin@example.com")
    raw_session = api_module._create_auth_session(user["id"])
    cookies = {"vantelia_portal_session": raw_session}
    origin = {"Origin": "http://testserver"}

    # Centro por defecto auto-creado en el arranque.
    locs = client.get("/auth/locations", params={"cliente_id": "demo"}, cookies=cookies).json()["items"]
    assert len(locs) >= 1
    default_loc = next(l for l in locs if l["is_default"])
    loc_a = default_loc["location_id"]

    # Crear segundo centro.
    created = client.post(
        "/auth/locations",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={"name": "Centro Norte", "address": "C/ Norte 1", "phone": "910000000"},
    )
    assert created.status_code == 200, created.text
    loc_b = created.json()["location_id"]
    assert created.json()["is_default"] is False

    # Empleado en A (default) y empleado en B.
    emp_a = client.post(
        "/auth/employees", params={"cliente_id": "demo"}, cookies=cookies,
        json={"name": "Ana A", "service_ids": []},
    ).json()
    emp_b = client.post(
        "/auth/employees", params={"cliente_id": "demo"}, cookies=cookies,
        json={"name": "Bea B", "location_id": loc_b, "service_ids": []},
    ).json()
    assert emp_a["location_id"] == loc_a
    assert emp_b["location_id"] == loc_b

    # /profesionales filtra por centro.
    only_b = client.get("/profesionales/demo", params={"location_id": loc_b}, headers=origin).json()["items"]
    ids_b = {e["employee_id"] for e in only_b}
    assert emp_b["employee_id"] in ids_b and emp_a["employee_id"] not in ids_b
    only_a = client.get("/profesionales/demo", params={"location_id": loc_a}, headers=origin).json()["items"]
    ids_a = {e["employee_id"] for e in only_a}
    assert emp_a["employee_id"] in ids_a and emp_b["employee_id"] not in ids_a

    # Aislamiento de agenda: reservar con Ana (A) no bloquea el mismo hueco de Bea (B).
    target = datetime.utcnow().date() + timedelta(days=2)
    while target.weekday() == 6:
        target += timedelta(days=1)
    fecha = target.isoformat()

    booked = client.post(
        "/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies,
        json={"nombre": "Cliente A", "email": "", "telefono": "600000001", "servicio": "",
              "employee_id": emp_a["employee_id"], "fecha": fecha, "hora": "09:00", "notas": ""},
    )
    assert booked.status_code == 200, booked.text
    booking_id = booked.json()["booking_id"]

    # La cita queda sellada con el centro de Ana (A).
    with sqlite3.connect(api_module.DB_PATH) as conn:
        loc_stamp = conn.execute(
            "SELECT location_id FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()[0]
    assert loc_stamp == loc_a

    # Disponibilidad de Bea (B) en el mismo hueco sigue libre.
    disp = client.get(
        "/disponibilidad",
        params={"cliente_id": "demo", "fecha": fecha, "employee_id": emp_b["employee_id"]},
        headers=origin,
    ).json()
    libre = {s["hora"]: s["disponible"] for s in disp["slots"]}
    assert libre.get("09:00") is True

    # Borrar centro con profesional asignado -> 409.
    blocked = client.delete(f"/auth/locations/{loc_b}", params={"cliente_id": "demo"}, cookies=cookies)
    assert blocked.status_code == 409

    # Limpieza.
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conn.execute("DELETE FROM employees WHERE id IN (?, ?)", (emp_a["employee_id"], emp_b["employee_id"]))
        conn.execute("DELETE FROM locations WHERE id = ?", (loc_b,))
        conn.commit()


def test_service_location_overrides(client: TestClient, api_module):
    """F1.5: carta/precios por centro via overlay de overrides."""
    user = api_module._get_user_by_email("admin@example.com")
    cookies = {"vantelia_portal_session": api_module._create_auth_session(user["id"])}
    origin = {"Origin": "http://testserver"}

    locs = client.get("/auth/locations", params={"cliente_id": "demo"}, cookies=cookies).json()["items"]
    loc_a = next(l for l in locs if l["is_default"])["location_id"]
    loc_b = client.post(
        "/auth/locations", params={"cliente_id": "demo"}, cookies=cookies,
        json={"name": "Centro Override"},
    ).json()["location_id"]

    # Dos servicios base.
    for nombre, dur, precio in (("Masaje base", 30, 5000), ("Solo en A", 30, 4000)):
        r = client.post(
            "/auth/services", params={"cliente_id": "demo"}, cookies=cookies,
            json={"nombre": nombre, "duration_minutes": dur, "price_cents": precio},
        )
        assert r.status_code == 200, r.text

    # Override en B: "Masaje base" cuesta 70EUR y dura 60 min; "Solo en A" no se ofrece.
    r = client.put(
        "/auth/services/masaje_base/locations/" + loc_b,
        params={"cliente_id": "demo"}, cookies=cookies,
        json={"is_available": True, "price_cents": 7000, "duration_minutes": 60},
    )
    assert r.status_code == 200, r.text
    r = client.put(
        "/auth/services/solo_en_a/locations/" + loc_b,
        params={"cliente_id": "demo"}, cookies=cookies,
        json={"is_available": False},
    )
    assert r.status_code == 200, r.text

    # Catalogo publico por centro.
    svcs_b = {s["id"]: s for s in client.get(
        "/servicios/demo", params={"location_id": loc_b}, headers=origin
    ).json()["servicios"]}
    assert "solo_en_a" not in svcs_b
    assert svcs_b["masaje_base"]["price_cents"] == 7000
    assert svcs_b["masaje_base"]["duration_minutes"] == 60

    svcs_a = {s["id"]: s for s in client.get(
        "/servicios/demo", params={"location_id": loc_a}, headers=origin
    ).json()["servicios"]}
    assert "solo_en_a" in svcs_a
    assert svcs_a["masaje_base"]["price_cents"] == 5000
    assert svcs_a["masaje_base"]["duration_minutes"] == 30

    # Duracion efectiva por centro del empleado.
    emp_b = client.post(
        "/auth/employees", params={"cliente_id": "demo"}, cookies=cookies,
        json={"name": "Empleada B Ovr", "location_id": loc_b, "service_ids": []},
    ).json()
    emp_row = api_module._get_employee_row(emp_b["employee_id"], cliente_id="demo")
    assert api_module._service_duration_minutes("demo", "Masaje base", emp_row) == 60

    # Reset del override -> vuelve a heredar.
    r = client.delete(
        "/auth/services/masaje_base/locations/" + loc_b,
        params={"cliente_id": "demo"}, cookies=cookies,
    )
    assert r.status_code == 200
    assert api_module._service_duration_minutes("demo", "Masaje base", emp_row) == 30

    # Limpieza.
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM employees WHERE id = ?", (emp_b["employee_id"],))
        conn.execute("DELETE FROM services WHERE cliente_id='demo' AND slug IN ('masaje_base','solo_en_a')")
        conn.execute("DELETE FROM service_location_overrides WHERE cliente_id='demo'")
        conn.execute("DELETE FROM locations WHERE id = ?", (loc_b,))
        conn.commit()


def test_portal_service_editor_exposes_multicenter_and_preauth_controls():
    """El editor no debe depender de controles antiguos que rompan abrir/guardar."""
    html = (REPO_ROOT / "app_ui" / "index.html").read_text(encoding="utf-8")

    assert 'id="svcPaymentType"' in html
    assert '<option value="preauth">' in html
    assert 'id="svcLocationsWrap"' in html
    assert 'id="svcLocationsList"' in html
    assert "document.getElementById('servicioNewBtn').addEventListener" in html
    assert "row.querySelector('[data-edit]').addEventListener" in html
    assert "await saveSvcLocations(saved.id)" in html
    assert "svcDepositValue" not in html
    assert "svcConfirmOnPaid" not in html


def test_resources_capacity_limits_overlap(client: TestClient, api_module):
    """F2: con N salas en el centro, max N citas solapadas aunque haya mas personal."""
    user = api_module._get_user_by_email("admin@example.com")
    cookies = {"vantelia_portal_session": api_module._create_auth_session(user["id"])}
    origin = {"Origin": "http://testserver"}

    loc = client.post(
        "/auth/locations", params={"cliente_id": "demo"}, cookies=cookies,
        json={"name": "Centro Aforo"},
    ).json()["location_id"]

    emp1 = client.post(
        "/auth/employees", params={"cliente_id": "demo"}, cookies=cookies,
        json={"name": "Aforo Uno", "location_id": loc, "service_ids": []},
    ).json()
    emp2 = client.post(
        "/auth/employees", params={"cliente_id": "demo"}, cookies=cookies,
        json={"name": "Aforo Dos", "location_id": loc, "service_ids": []},
    ).json()

    # 1 sala para 2 profesionales.
    r = client.post(
        f"/auth/locations/{loc}/resources", params={"cliente_id": "demo"}, cookies=cookies,
        json={"name": "Sala unica"},
    )
    assert r.status_code == 200, r.text
    sala_id = r.json()["resource_id"]

    target = datetime.utcnow().date() + timedelta(days=3)
    while target.weekday() == 6:
        target += timedelta(days=1)
    fecha = target.isoformat()

    # Cita con emp1 a las 09:00 ocupa la unica sala.
    booked = client.post(
        "/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies,
        json={"nombre": "Aforo Cli", "email": "", "telefono": "600333444", "servicio": "",
              "employee_id": emp1["employee_id"], "fecha": fecha, "hora": "09:00", "notas": ""},
    )
    assert booked.status_code == 200, booked.text
    booking_id = booked.json()["booking_id"]

    # La cita lleva la sala asignada.
    with sqlite3.connect(api_module.DB_PATH) as conn:
        res_stamp = conn.execute(
            "SELECT resource_id FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()[0]
    assert res_stamp == sala_id

    # emp2 a las 09:00 -> sin sala libre: slot no disponible y reserva rechazada.
    disp = client.get(
        "/disponibilidad",
        params={"cliente_id": "demo", "fecha": fecha, "employee_id": emp2["employee_id"]},
        headers=origin,
    ).json()
    estado = {s["hora"]: s["disponible"] for s in disp["slots"]}
    assert estado.get("09:00") is False
    assert estado.get("09:30") is True

    rejected = client.post(
        "/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies,
        json={"nombre": "Aforo Cli 2", "email": "", "telefono": "600555666", "servicio": "",
              "employee_id": emp2["employee_id"], "fecha": fecha, "hora": "09:00", "notas": ""},
    )
    assert rejected.status_code == 409

    # Con una segunda sala, el mismo hueco vuelve a estar disponible.
    client.post(
        f"/auth/locations/{loc}/resources", params={"cliente_id": "demo"}, cookies=cookies,
        json={"name": "Sala dos"},
    )
    disp2 = client.get(
        "/disponibilidad",
        params={"cliente_id": "demo", "fecha": fecha, "employee_id": emp2["employee_id"]},
        headers=origin,
    ).json()
    estado2 = {s["hora"]: s["disponible"] for s in disp2["slots"]}
    assert estado2.get("09:00") is True

    # Limpieza.
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conn.execute("DELETE FROM employees WHERE id IN (?, ?)", (emp1["employee_id"], emp2["employee_id"]))
        conn.execute("DELETE FROM resources WHERE cliente_id='demo' AND location_id = ?", (loc,))
        conn.execute("DELETE FROM locations WHERE id = ?", (loc,))
        conn.commit()


def test_preauth_capture_release_refund(client: TestClient, api_module, monkeypatch):
    """F3: retencion sin cobro (capture manual) + cobrar/liberar/reembolsar desde el panel."""
    user = api_module._get_user_by_email("admin@example.com")
    cookies = {"vantelia_portal_session": api_module._create_auth_session(user["id"])}

    calls = {"capture": [], "cancel": [], "refund": []}

    class _FakePI:
        @staticmethod
        def capture(pi_id, **kwargs):
            calls["capture"].append((pi_id, kwargs))
            return SimpleNamespace(id=pi_id, status="succeeded")

        @staticmethod
        def cancel(pi_id, **kwargs):
            calls["cancel"].append((pi_id, kwargs))
            return SimpleNamespace(id=pi_id, status="canceled")

    class _FakeRefund:
        @staticmethod
        def create(**kwargs):
            calls["refund"].append(kwargs)
            return SimpleNamespace(id="re_test", status="succeeded")

    fake_stripe = SimpleNamespace(PaymentIntent=_FakePI, Refund=_FakeRefund, api_key="sk_test_dummy")
    import backend.stripe_gateway as sg
    monkeypatch.setattr(sg, "stripe", fake_stripe, raising=False)
    monkeypatch.setattr(sg, "_stripe_init", lambda: None, raising=False)

    _seed_times = {"cap": "09:00", "rel": "09:30", "wh": "10:00"}

    def _seed_preauth_booking(suffix):
        booking_id = f"bk_preauth_{suffix}"
        now = api_module._utc_now_iso()
        fecha = (datetime.utcnow().date() + timedelta(days=2)).isoformat()
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute(
                """INSERT INTO bookings (id, cliente_id, employee_id, employee_name, nombre, email,
                    telefono, servicio, booking_date, booking_time, notas, status, provider_name,
                    provider_status, manage_token, timezone, start_at, end_at, confirmed_at,
                    payment_status, source, created_at)
                   VALUES (?, 'demo', '', '', 'Preauth Cli', 'pre@example.com', '', 'Masaje',
                    ?, ?, '', 'confirmed', 'internal', 'internal', ?, 'Europe/Madrid',
                    '', '', ?, 'preauthorized', 'vantelia_widget', ?)""",
                (booking_id, fecha, _seed_times[suffix], f"tok_{suffix}", now, now),
            )
            conn.execute(
                """INSERT INTO booking_payments (id, cliente_id, booking_id, stripe_account_id,
                    checkout_session_id, payment_intent_id, amount_cents, currency, status,
                    checkout_url, capture_method, created_at, updated_at)
                   VALUES (?, 'demo', ?, 'acct_test', ?, ?, 5000, 'eur', 'preauthorized',
                    'https://stripe.test/x', 'manual', ?, ?)""",
                (f"pay_{suffix}", booking_id, f"cs_{suffix}", f"pi_{suffix}", now, now),
            )
            conn.commit()
        return booking_id

    # Capture parcial (penalizacion 30 EUR de una retencion de 50).
    b1 = _seed_preauth_booking("cap")
    r = client.post(
        f"/auth/bookings/{b1}/payment/capture", params={"cliente_id": "demo"}, cookies=cookies,
        json={"amount_cents": 3000, "reason": "no-show"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["payment_status"] == "paid"
    assert calls["capture"][0][0] == "pi_cap"
    assert calls["capture"][0][1]["amount_to_capture"] == 3000
    assert calls["capture"][0][1]["stripe_account"] == "acct_test"

    # Refund parcial del pago capturado.
    r = client.post(
        f"/auth/bookings/{b1}/payment/refund", params={"cliente_id": "demo"}, cookies=cookies,
        json={"amount_cents": 1000, "reason": "gesto comercial"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["payment_status"] == "partially_refunded"
    assert calls["refund"][0]["payment_intent"] == "pi_cap"
    assert calls["refund"][0]["amount"] == 1000

    # Release de otra retencion (cancelacion dentro de plazo).
    b2 = _seed_preauth_booking("rel")
    r = client.post(
        f"/auth/bookings/{b2}/payment/release", params={"cliente_id": "demo"}, cookies=cookies,
        json={"reason": "cancelacion en plazo"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["payment_status"] == "released"
    assert calls["cancel"][0][0] == "pi_rel"

    # Release de una retencion ya cobrada -> 409.
    r = client.post(
        f"/auth/bookings/{b1}/payment/release", params={"cliente_id": "demo"}, cookies=cookies,
        json={},
    )
    assert r.status_code == 409

    # Webhook con capture manual marca preauthorized (no paid).
    b3 = _seed_preauth_booking("wh")
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("UPDATE booking_payments SET status='pending', payment_intent_id='' WHERE booking_id=?", (b3,))
        conn.execute("UPDATE bookings SET payment_status='pending' WHERE id=?", (b3,))
        conn.commit()
    handled = api_module.process_booking_payment_webhook(
        {"id": "cs_wh2", "payment_intent": "pi_wh2",
         "metadata": {"source": "booking_payment", "cliente_id": "demo", "booking_id": b3}}
    )
    assert handled is True
    with sqlite3.connect(api_module.DB_PATH) as conn:
        st = conn.execute("SELECT status FROM booking_payments WHERE booking_id=?", (b3,)).fetchone()[0]
        bst = conn.execute("SELECT payment_status FROM bookings WHERE id=?", (b3,)).fetchone()[0]
    assert st == "preauthorized"
    assert bst == "preauthorized"

    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE id IN (?, ?, ?)", (b1, b2, b3))
        conn.execute("DELETE FROM booking_payments WHERE booking_id IN (?, ?, ?)", (b1, b2, b3))
        conn.commit()


def test_channel_number_maps_to_location_and_prompt_lists_centers(client: TestClient, api_module):
    """F1.6: numero entrante -> centro + el system prompt conoce los centros."""
    user = api_module._get_user_by_email("admin@example.com")
    cookies = {"vantelia_portal_session": api_module._create_auth_session(user["id"])}

    loc = client.post(
        "/auth/locations", params={"cliente_id": "demo"}, cookies=cookies,
        json={
            "name": "Centro Canal",
            "address": "C/ Canal 5",
            "whatsapp_phone_number_id": "999888777",
            "voice_phone_number": "+34911000111",
        },
    ).json()["location_id"]

    assert api_module._location_for_channel("demo", whatsapp_phone_number_id="999888777") == loc
    assert api_module._location_for_channel("demo", voice_phone_number="+34911000111") == loc
    assert api_module._location_for_channel("demo", voice_phone_number="34911000111") == loc
    assert api_module._location_for_channel("demo", whatsapp_phone_number_id="000") == ""

    # Con >1 centro, el prompt del agente lista los centros y pide elegir.
    config = api_module.CONFIG_CLIENTES["demo"]
    prompt = api_module._build_system_prompt("demo", config)
    assert "CENTROS DEL NEGOCIO" in prompt
    assert "Centro Canal" in prompt
    assert "C/ Canal 5" in prompt

    # Limpieza: con un solo centro el bloque desaparece.
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM locations WHERE id = ?", (loc,))
        conn.commit()
    prompt_single = api_module._build_system_prompt("demo", config)
    assert "CENTROS DEL NEGOCIO" not in prompt_single


def _portal_admin_cookies(api_module):
    user = api_module._get_user_by_email("admin@example.com")
    raw_session = api_module._create_auth_session(user["id"])
    return {"vantelia_portal_session": raw_session}


def test_commerce_products_packages_giftcards(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    params = {"cliente_id": "demo"}

    # --- Producto: CRUD + venta con stock ---
    r = client.post("/auth/products", params=params, cookies=cookies,
                    json={"name": "Aceite esencial", "price_cents": 1500, "stock": 2})
    assert r.status_code == 200, r.text
    product_id = r.json()["id"]
    r = client.post(f"/auth/products/{product_id}/sell", params=params, cookies=cookies,
                    json={"qty": 2, "payment_method": "card", "customer_name": "Ana"})
    assert r.status_code == 200, r.text
    assert r.json()["total_cents"] == 3000
    # Stock agotado -> 409
    r = client.post(f"/auth/products/{product_id}/sell", params=params, cookies=cookies, json={"qty": 1})
    assert r.status_code == 409
    sales = client.get("/auth/product-sales", params=params, cookies=cookies).json()["items"]
    assert any(s["product_id"] == product_id and s["total_cents"] == 3000 for s in sales)

    # --- Bono: crear, vender, redimir hasta agotar ---
    svc = client.post("/auth/services", params=params, cookies=cookies,
                      json={"nombre": "Masaje Bono Test", "duration_minutes": 30, "price_cents": 6000})
    assert svc.status_code == 200, svc.text
    slug = svc.json()["id"]
    r = client.post("/auth/packages", params=params, cookies=cookies,
                    json={"name": "Bono 2 sesiones", "items": [{"service_slug": slug, "qty": 2}],
                          "price_cents": 10000, "validity_days": 90})
    assert r.status_code == 200, r.text
    package_id = r.json()["id"]
    r = client.post(f"/auth/packages/{package_id}/sell", params=params, cookies=cookies,
                    json={"buyer_name": "Luis", "buyer_email": "luis@example.com"})
    assert r.status_code == 200, r.text
    purchase_id = r.json()["purchase_id"]
    assert r.json()["remaining"][slug] == 2

    seed_counter = {"n": 0}

    def _seed_service_booking() -> str:
        booking_id = uuid.uuid4().hex
        seed_counter["n"] += 1
        start = datetime.utcnow() + timedelta(days=3, minutes=30 * seed_counter["n"])
        iso = lambda d: d.isoformat(timespec="seconds") + "Z"
        api_module._store_booking({
            "id": booking_id, "cliente_id": "demo", "employee_id": "", "employee_name": "",
            "nombre": "Luis", "email": "luis@example.com", "telefono": "",
            "servicio": "Masaje Bono Test", "booking_date": start.date().isoformat(),
            "booking_time": start.strftime("%H:%M"), "notas": "", "status": "confirmed",
            "provider_name": "internal", "provider_status": "confirmed", "provider_booking_id": "",
            "provider_booking_url": "", "manage_token": f"mg_{booking_id}", "timezone": "Europe/Madrid",
            "start_at": iso(start), "end_at": iso(start + timedelta(minutes=30)),
            "confirmed_at": iso(start), "cancelled_at": "",
            "rescheduled_at": "", "rescheduled_from_booking_id": "", "confirmation_email_sent_at": "",
            "reminder_24h_sent_at": "", "reminder_2h_sent_at": "", "customer_email_status": "",
            "customer_email_last_error": "", "service_id": slug, "service_price_cents": 6000,
            "source": "test", "created_at": iso(start),
        })
        return booking_id

    bk1, bk2, bk3 = _seed_service_booking(), _seed_service_booking(), _seed_service_booking()
    r = client.post(f"/auth/package-purchases/{purchase_id}/redeem", params=params, cookies=cookies,
                    json={"booking_id": bk1})
    assert r.status_code == 200, r.text
    assert r.json()["remaining"][slug] == 1
    with sqlite3.connect(api_module.DB_PATH) as conn:
        assert conn.execute("SELECT payment_status FROM bookings WHERE id = ?", (bk1,)).fetchone()[0] == "paid"
    r = client.post(f"/auth/package-purchases/{purchase_id}/redeem", params=params, cookies=cookies,
                    json={"booking_id": bk2})
    assert r.status_code == 200
    assert r.json()["purchase_status"] == "used"
    # Sin sesiones restantes -> 409
    r = client.post(f"/auth/package-purchases/{purchase_id}/redeem", params=params, cookies=cookies,
                    json={"booking_id": bk3})
    assert r.status_code == 409

    # --- Gift card: emitir, parcial, cubrir ---
    r = client.post("/auth/gift-cards", params=params, cookies=cookies,
                    json={"amount_cents": 5000, "buyer_name": "Eva"})
    assert r.status_code == 200, r.text
    code_small = r.json()["code"]
    assert code_small.startswith("GC-")
    r = client.post("/auth/gift-cards/redeem", params=params, cookies=cookies,
                    json={"code": code_small, "booking_id": bk3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["covered"] is False and body["charged_cents"] == 5000 and body["remaining_due_cents"] == 1000
    with sqlite3.connect(api_module.DB_PATH) as conn:
        # Parcial: la cita NO queda pagada
        assert conn.execute("SELECT payment_status FROM bookings WHERE id = ?", (bk3,)).fetchone()[0] != "paid"
    bk4 = _seed_service_booking()
    r = client.post("/auth/gift-cards", params=params, cookies=cookies, json={"amount_cents": 8000})
    code_big = r.json()["code"]
    r = client.post("/auth/gift-cards/redeem", params=params, cookies=cookies,
                    json={"code": code_big, "booking_id": bk4})
    assert r.status_code == 200 and r.json()["covered"] is True
    assert r.json()["balance_after_cents"] == 2000
    with sqlite3.connect(api_module.DB_PATH) as conn:
        assert conn.execute("SELECT payment_status FROM bookings WHERE id = ?", (bk4,)).fetchone()[0] == "paid"

    # Limpieza
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE id IN (?, ?, ?, ?)", (bk1, bk2, bk3, bk4))
        conn.execute("DELETE FROM products WHERE cliente_id = 'demo' AND id = ?", (product_id,))
        conn.execute("DELETE FROM product_sales WHERE cliente_id = 'demo'")
        conn.execute("DELETE FROM packages WHERE cliente_id = 'demo'")
        conn.execute("DELETE FROM package_purchases WHERE cliente_id = 'demo'")
        conn.execute("DELETE FROM gift_cards WHERE cliente_id = 'demo'")
        conn.execute("DELETE FROM gift_card_transactions WHERE cliente_id = 'demo'")
        conn.execute("DELETE FROM services WHERE cliente_id = 'demo' AND slug = ?", (slug,))
        conn.commit()


def test_analytics_overview_and_portal_roles(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    params = {"cliente_id": "demo"}

    # Analytics responde con estructura completa para admin (owner)
    r = client.get("/auth/analytics/overview", params=params, cookies=cookies)
    assert r.status_code == 200, r.text
    data = r.json()
    for key in ("kpis", "previous", "series", "by_service", "by_employee", "by_location"):
        assert key in data
    assert "revenue_cents" in data["kpis"] and "occupancy_rate" in data["kpis"]
    csv_resp = client.get("/auth/analytics/export.csv", params=params, cookies=cookies)
    assert csv_resp.status_code == 200 and "fecha;citas;ingresos_eur" in csv_resp.text

    # Usuario staff: agenda si, gestion no
    staff = api_module._create_user(
        email="staff@example.com", password="staff-pass-123", role="client",
        display_name="Staff Demo", cliente_id="demo", portal_role="staff",
    )
    staff_cookies = {"vantelia_portal_session": api_module._create_auth_session(staff["id"])}
    me = client.get("/auth/me", cookies=staff_cookies)
    assert me.status_code == 200 and me.json()["portal_role"] == "staff"
    assert client.get("/auth/analytics/overview", cookies=staff_cookies).status_code == 403
    assert client.post("/auth/services", cookies=staff_cookies,
                       json={"nombre": "Prohibido", "price_cents": 100}).status_code == 403
    assert client.post("/auth/employees", cookies=staff_cookies,
                       json={"name": "Prohibido Tambien"}).status_code == 403
    assert client.get("/auth/products", cookies=staff_cookies).status_code == 200
    assert client.get("/auth/app/team", cookies=staff_cookies).status_code == 403

    # Owner self-serve gestiona su equipo
    owner = api_module._create_user(
        email="owner@example.com", password="owner-pass-123", role="client",
        display_name="Owner Demo", cliente_id="demo", portal_role="owner",
    )
    owner_cookies = {"vantelia_portal_session": api_module._create_auth_session(owner["id"])}
    team = client.get("/auth/app/team", cookies=owner_cookies)
    assert team.status_code == 200
    r = client.post("/auth/app/team", cookies=owner_cookies,
                    json={"email": "recep@example.com", "password": "recep-pass-123",
                          "display_name": "Recepcion", "portal_role": "manager"})
    assert r.status_code == 200 and r.json()["portal_role"] == "manager"
    member_id = r.json()["user_id"]
    r = client.post(f"/auth/app/team/{member_id}", cookies=owner_cookies, json={"portal_role": "staff"})
    assert r.status_code == 200 and r.json()["portal_role"] == "staff"
    # No puede dejar al negocio sin owner activo
    r = client.post(f"/auth/app/team/{owner['id']}", cookies=owner_cookies, json={"portal_role": "staff"})
    assert r.status_code == 409
    assert client.delete(f"/auth/app/team/{member_id}", cookies=owner_cookies).status_code == 200

    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM users WHERE email IN ('staff@example.com', 'owner@example.com', 'recep@example.com')")
        conn.commit()


def test_whatsapp_reminder_buttons_confirm_and_cancel(client: TestClient, api_module, monkeypatch):
    sent_messages = []

    async def _fake_send_text(**kwargs):
        sent_messages.append(kwargs.get("text", ""))
        return True

    monkeypatch.setattr(api_module, "_send_whatsapp_text", _fake_send_text)

    wa_seed_counter = {"n": 0}

    def _seed_future_booking(phone: str) -> str:
        booking_id = uuid.uuid4().hex
        wa_seed_counter["n"] += 1
        start = datetime.utcnow() + timedelta(days=2, minutes=30 * wa_seed_counter["n"])
        iso = lambda d: d.isoformat(timespec="seconds") + "Z"
        api_module._store_booking({
            "id": booking_id, "cliente_id": "demo", "employee_id": "", "employee_name": "",
            "nombre": "Cliente WA", "email": "wa@example.com", "telefono": phone,
            "servicio": "Consulta", "booking_date": start.date().isoformat(),
            "booking_time": start.strftime("%H:%M"), "notas": "", "status": "confirmed",
            "provider_name": "internal", "provider_status": "confirmed", "provider_booking_id": "",
            "provider_booking_url": "", "manage_token": f"mg_{booking_id}", "timezone": "Europe/Madrid",
            "start_at": iso(start), "end_at": iso(start + timedelta(minutes=30)),
            "confirmed_at": iso(start), "cancelled_at": "",
            "rescheduled_at": "", "rescheduled_from_booking_id": "", "confirmation_email_sent_at": "",
            "reminder_24h_sent_at": "", "reminder_2h_sent_at": "", "customer_email_status": "",
            "customer_email_last_error": "", "source": "test", "created_at": iso(start),
        })
        return booking_id

    class _FakeRequest:
        client = None
        base_url = "http://testserver/"
        headers = {}

    # Confirmacion de asistencia -> audit, sin cambio de estado
    bk_ok = _seed_future_booking("+34600777001")
    asyncio.run(
        api_module._wa_handle_reminder_reply(
            cliente_id="demo", phone_number_id="1234567890",
            from_number="+34600777001", interactive_id=f"bkok_{bk_ok}", request=_FakeRequest(),
        )
    )
    with sqlite3.connect(api_module.DB_PATH) as conn:
        status_row = conn.execute("SELECT status FROM bookings WHERE id = ?", (bk_ok,)).fetchone()
        audit = conn.execute(
            "SELECT COUNT(*) FROM booking_audit WHERE booking_id = ? AND event_type = 'attendance_confirmed_by_customer'",
            (bk_ok,),
        ).fetchone()[0]
    assert status_row[0] == "confirmed" and audit == 1
    assert any("confirmada" in m for m in sent_messages)

    # Cancelacion -> cita cancelada
    bk_cancel = _seed_future_booking("+34600777002")
    asyncio.run(
        api_module._wa_handle_reminder_reply(
            cliente_id="demo", phone_number_id="1234567890",
            from_number="+34600777002", interactive_id=f"bkcancel_{bk_cancel}", request=_FakeRequest(),
        )
    )
    with sqlite3.connect(api_module.DB_PATH) as conn:
        assert conn.execute("SELECT status FROM bookings WHERE id = ?", (bk_cancel,)).fetchone()[0] == "cancelled"

    # Telefono que no coincide -> no toca la cita
    bk_other = _seed_future_booking("+34600777003")
    asyncio.run(
        api_module._wa_handle_reminder_reply(
            cliente_id="demo", phone_number_id="1234567890",
            from_number="+34699999999", interactive_id=f"bkcancel_{bk_other}", request=_FakeRequest(),
        )
    )
    with sqlite3.connect(api_module.DB_PATH) as conn:
        assert conn.execute("SELECT status FROM bookings WHERE id = ?", (bk_other,)).fetchone()[0] == "confirmed"

    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE id IN (?, ?, ?)", (bk_ok, bk_cancel, bk_other))
        conn.commit()


def test_reminders_reach_future_bookings_past_legacy_window(client: TestClient, api_module):
    """Regresion: con muchas citas viejas, el recordatorio de una cita futura
    (rank > 500 en orden fecha ASC) debe seguir seleccionandose. El antiguo
    ``_list_booking_rows(limit=500)`` la perdia; ``_bookings_due_for_reminders``
    la encuentra porque filtra por fecha, no por volumen."""
    now = api_module._utc_now()
    old_day = (now - timedelta(days=120)).date().isoformat()
    # 520 citas viejas confirmadas: empujan cualquier futura mas alla del rank 500.
    old_rows = [
        (
            f"old_rem_{i}", "demo", f"oldemp_{i}", "", "Viejo", "", "", "", old_day, "10:00", "",
            "confirmed", "internal", "confirmed", f"mg_old_{i}", "Europe/Madrid",
            f"{old_day}T08:00:00Z", f"{old_day}T08:30:00Z", "seed_old", old_day + "T08:00:00Z", "", "",
        )
        for i in range(520)
    ]
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.executemany(
            "INSERT INTO bookings (id, cliente_id, employee_id, employee_name, nombre, email, telefono, "
            "servicio, booking_date, booking_time, notas, status, provider_name, provider_status, "
            "manage_token, timezone, start_at, end_at, source, created_at, reminder_24h_sent_at, "
            "reminder_2h_sent_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            old_rows,
        )
        conn.commit()

    # Cita futura ~24h+20min: dentro de la ventana del recordatorio 24h.
    start = now + timedelta(hours=24, minutes=20)
    iso = lambda d: d.isoformat(timespec="seconds").replace("+00:00", "") + "Z"
    future_id = "fut_rem_" + uuid.uuid4().hex
    api_module._store_booking({
        "id": future_id, "cliente_id": "demo", "employee_id": "", "employee_name": "",
        "nombre": "Cliente Futuro", "email": "fut@example.com", "telefono": "+34600111000",
        "servicio": "", "booking_date": start.date().isoformat(), "booking_time": start.strftime("%H:%M"),
        "notas": "", "status": "confirmed", "provider_name": "internal", "provider_status": "confirmed",
        "provider_booking_id": "", "provider_booking_url": "", "manage_token": f"mg_{future_id}",
        "timezone": "Europe/Madrid", "start_at": iso(start), "end_at": iso(start + timedelta(minutes=30)),
        "confirmed_at": iso(start), "cancelled_at": "", "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": "", "reminder_2h_sent_at": "",
        "customer_email_status": "", "customer_email_last_error": "", "source": "test", "created_at": iso(now),
    })

    try:
        # El path legacy (oldest-500) NO la veria.
        legacy_rows, _ = api_module._list_booking_rows(limit=500)
        assert future_id not in {r["id"] for r in legacy_rows}
        # El nuevo selector SI la incluye y el gate exacto la marca como debida.
        cand = api_module._bookings_due_for_reminders(now)
        cand_ids = {r["id"] for r in cand}
        assert future_id in cand_ids
        assert not (cand_ids & {f"old_rem_{i}" for i in range(520)})  # excluye las viejas
        future_row = api_module._get_booking_row_by_id(future_id)
        assert api_module._booking_due_for_reminder(future_row, now, api_module.REMINDER_24H_HOURS)
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id = ? OR id LIKE 'old_rem_%'", (future_id,))
            conn.commit()


def _seed_confirmed_booking(
    api_module, *, booking_id, start, status="confirmed", reminder_24h_sent="",
    email="fu@example.com", telefono="+34600222333",
):
    iso = lambda d: d.isoformat(timespec="seconds").replace("+00:00", "") + "Z"
    api_module._store_booking({
        "id": booking_id, "cliente_id": "demo", "employee_id": "", "employee_name": "",
        "nombre": "Cliente FU", "email": email, "telefono": telefono,
        "servicio": "", "booking_date": start.date().isoformat(), "booking_time": start.strftime("%H:%M"),
        "notas": "", "status": status, "provider_name": "internal", "provider_status": status,
        "provider_booking_id": "", "provider_booking_url": "", "manage_token": f"mg_{booking_id}",
        "timezone": "Europe/Madrid", "start_at": iso(start), "end_at": iso(start + timedelta(minutes=30)),
        "confirmed_at": iso(start), "cancelled_at": "", "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": reminder_24h_sent, "reminder_2h_sent_at": "",
        "customer_email_status": "", "customer_email_last_error": "", "source": "test", "created_at": iso(start),
    })


def test_email_confirm_link_marks_attendance(client: TestClient, api_module):
    """Enlace del email: ABRIRLO no confirma; confirma el boton (POST).

    Un GET no debe cambiar el estado: los antivirus y los previsualizadores de
    correo abren los enlaces y daban citas por confirmadas solas."""
    start = api_module._utc_now() + timedelta(days=2)
    bid = "conf_" + uuid.uuid4().hex
    _seed_confirmed_booking(api_module, booking_id=bid, start=start)
    token = f"mg_{bid}"
    try:
        assert client.get("/booking/confirm/nope-" + uuid.uuid4().hex).status_code == 404

        def _audit_count():
            with sqlite3.connect(api_module.DB_PATH) as conn:
                return conn.execute(
                    "SELECT COUNT(*) FROM booking_audit WHERE booking_id=? AND event_type='attendance_confirmed_by_customer'",
                    (bid,),
                ).fetchone()[0]

        r1 = client.get(f"/booking/confirm/{token}")
        assert r1.status_code == 200 and "confirmo" in r1.text.lower()
        assert _audit_count() == 0  # abrir el enlace no confirma nada

        r2 = client.post(f"/booking/confirm/{token}")
        assert r2.status_code == 200 and r2.json()["ok"] is True
        assert _audit_count() == 1

        assert client.post(f"/booking/confirm/{token}").status_code == 200  # idempotente
        assert _audit_count() == 1  # no duplica el audit
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id=?", (bid,))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (bid,))
            conn.commit()


def test_followup_suppress_2h_if_confirmed(client: TestClient, api_module, monkeypatch):
    """El aviso de 2h NO se envia si el cliente ya confirmo (escalera). Control: si
    NO ha confirmado, si se envia."""
    sent = []

    async def _rec(row, kind, *a, **k):
        sent.append((row["id"], kind))

    monkeypatch.setattr("backend.booking._send_booking_reminder_by_kind", _rec)
    now = api_module._utc_now()
    start = now + timedelta(hours=2, minutes=20)  # dentro de la ventana del 2h
    past24 = (now - timedelta(hours=1)).isoformat()
    confirmed_id = "fu2c_" + uuid.uuid4().hex
    control_id = "fu2n_" + uuid.uuid4().hex
    _seed_confirmed_booking(api_module, booking_id=confirmed_id, start=start, reminder_24h_sent=past24)
    _seed_confirmed_booking(api_module, booking_id=control_id, start=start + timedelta(minutes=5), reminder_24h_sent=past24)
    api_module._mark_booking_confirmed_by_customer(confirmed_id, "demo", channel="email")
    try:
        asyncio.run(api_module._run_booking_reminders())
        kinds_confirmed = [k for (bid, k) in sent if bid == confirmed_id]
        kinds_control = [k for (bid, k) in sent if bid == control_id]
        assert "reminder_2h" not in kinds_confirmed  # suprimido
        assert "reminder_2h" in kinds_control        # control si lo recibe
        with sqlite3.connect(api_module.DB_PATH) as conn:
            skipped = conn.execute(
                "SELECT COUNT(*) FROM booking_audit WHERE booking_id=? AND event_type='booking_email_skipped'",
                (confirmed_id,),
            ).fetchone()[0]
        assert skipped >= 1
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id IN (?, ?)", (confirmed_id, control_id))
            conn.execute("DELETE FROM booking_audit WHERE booking_id IN (?, ?)", (confirmed_id, control_id))
            conn.commit()


def test_followup_uses_single_channel_priority_and_fallback(api_module, monkeypatch):
    """Si hay varios canales activos, el envio real usa un solo canal:
    primero el prioritario y luego respaldo si falta el dato."""
    from backend import agenda as agenda_module
    from backend import booking as booking_module

    original_channels = api_module.CONFIG_CLIENTES["demo"]["booking"].get("message_template_channels")
    original_reminders = api_module.CONFIG_CLIENTES["demo"].get("reminders")
    api_module.CONFIG_CLIENTES["demo"]["booking"]["message_template_channels"] = {
        "reminder_24h": {"email": True, "whatsapp": False, "sms": True}
    }
    api_module.CONFIG_CLIENTES["demo"]["reminders"] = dict(original_reminders or {})
    monkeypatch.setattr(
        agenda_module,
        "_reminder_channel_availability",
        lambda _cid: {
            "email": {"available": True, "reason": "Disponible."},
            "whatsapp": {"available": False, "reason": "No disponible."},
            "sms": {"available": True, "reason": "Disponible."},
        },
    )

    sent_email = []
    sent_sms = []
    monkeypatch.setattr(
        booking_module,
        "_send_booking_email",
        lambda row, kind, request=None, extra_message="": sent_email.append(row["email"]),
    )

    async def _fake_sms(row, kind, request=None, extra_message=""):
        sent_sms.append(row["telefono"])
        return True

    monkeypatch.setattr(booking_module, "_send_booking_sms_reminder", _fake_sms)

    start = api_module._utc_now() + timedelta(days=1)
    with_email = "fu_pref_email_" + uuid.uuid4().hex
    no_email = "fu_pref_sms_" + uuid.uuid4().hex
    _seed_confirmed_booking(
        api_module,
        booking_id=with_email,
        start=start,
        email="pref@example.com",
        telefono="+34600111222",
    )
    _seed_confirmed_booking(
        api_module,
        booking_id=no_email,
        start=start + timedelta(minutes=5),
        email="",
        telefono="+34600333444",
    )
    try:
        with api_module._get_db_connection() as connection:
            row_email = connection.execute("SELECT * FROM bookings WHERE id=?", (with_email,)).fetchone()
            row_sms = connection.execute("SELECT * FROM bookings WHERE id=?", (no_email,)).fetchone()

        res_email = asyncio.run(booking_module._send_booking_reminder_by_kind(row_email, "reminder_24h"))
        assert res_email["sent"] == ["email"]
        assert sent_email == ["pref@example.com"]
        assert sent_sms == []
        assert res_email["skipped"]["sms"] == "Ya se envio por email."

        res_sms = asyncio.run(booking_module._send_booking_reminder_by_kind(row_sms, "reminder_24h"))
        assert res_sms["sent"] == ["sms"]
        assert sent_sms == ["+34600333444"]
        assert res_sms["skipped"]["email"] == "La cita no tiene email."

        api_module.CONFIG_CLIENTES["demo"]["reminders"]["delivery_priority"] = ["sms", "email", "whatsapp"]
        sent_email.clear()
        sent_sms.clear()
        res_priority = asyncio.run(booking_module._send_booking_reminder_by_kind(row_email, "reminder_24h"))
        assert res_priority["sent"] == ["sms"]
        assert sent_email == []
        assert sent_sms == ["+34600111222"]
        assert res_priority["skipped"]["email"] == "Ya se envio por sms."
    finally:
        if original_channels is None:
            api_module.CONFIG_CLIENTES["demo"]["booking"].pop("message_template_channels", None)
        else:
            api_module.CONFIG_CLIENTES["demo"]["booking"]["message_template_channels"] = original_channels
        if original_reminders is None:
            api_module.CONFIG_CLIENTES["demo"].pop("reminders", None)
        else:
            api_module.CONFIG_CLIENTES["demo"]["reminders"] = original_reminders
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id IN (?, ?)", (with_email, no_email))
            conn.execute("DELETE FROM booking_audit WHERE booking_id IN (?, ?)", (with_email, no_email))
            conn.commit()


def test_call_due_window():
    """`_call_due_for_booking`: dentro de la ventana T-X (y por encima del 2h) -> True."""
    from backend import booking as bk
    now = bk.timeutils._utc_now()

    def _row(hours):
        start = now + timedelta(hours=hours)
        return {"status": "confirmed", "start_at": start.isoformat().replace("+00:00", "") + "Z"}

    assert bk._call_due_for_booking(_row(4), now, 5) is True      # 4h fuera, <=5h
    assert bk._call_due_for_booking(_row(1), now, 5) is False     # 1h: ya pegado (<=2h)
    assert bk._call_due_for_booking(_row(9), now, 5) is False     # 9h: aun lejos


def test_followup_overview_endpoint_capabilities(client: TestClient, api_module):
    """GET /auth/app/follow-up expone pasos + capacidades; la llamada queda
    bloqueada si el plan no tiene voz."""
    cookies = _portal_admin_cookies(api_module)
    r = client.get("/auth/app/follow-up", params={"cliente_id": "demo"}, cookies=cookies)
    assert r.status_code == 200
    data = r.json()
    keys = [s["key"] for s in data["steps"]]
    # demo es plan business (incluye voz) -> aparece el paso de verificacion por codigo.
    assert keys == ["confirmed", "reminder_24h", "call", "reminder_2h", "review", "voice_otp"]
    # Canales GLOBALES (una sola tira para todos los avisos).
    gchans = {c["channel"]: c for c in data["channels"]}
    assert set(gchans) == {"email", "whatsapp", "sms"}
    assert gchans["email"]["available"] is True and gchans["email"]["locked"] is False
    otp_step = next(s for s in data["steps"] if s["key"] == "voice_otp")
    # El OTP ya no selecciona canales: solo tiene on/off (usa los canales globales).
    assert "enabled" in otp_step and otp_step["kind"] == "otp"
    review_step = next(s for s in data["steps"] if s["key"] == "review")
    assert "enabled" in review_step and "needs_setup" in review_step
    # Sin enlace configurado en demo, el paso pide setup y no esta activo.
    assert review_step["needs_setup"] is True
    assert review_step["enabled"] is False
    assert data["channel_availability"]["email"] is True
    assert isinstance(data["email_confirm_button"], bool)
    assert isinstance(data["voice_otp_enabled"], bool)
    assert data["delivery_priority"] == ["email", "whatsapp", "sms"]
    # Los avisos de mensaje exponen on/off pero no canales propios (son globales).
    for key in ("confirmed", "reminder_24h", "reminder_2h"):
        step = next(s for s in data["steps"] if s["key"] == key)
        assert step["kind"] == "message" and step["channels"] == []
        assert "enabled" in step and "active" in step
    call_step = next(s for s in data["steps"] if s["key"] == "call")
    call_chan = call_step["channels"][0]
    assert call_chan["channel"] == "call"
    # locked = gating por PLAN; si esta bloqueado, la voz no puede estar disponible.
    if call_chan["locked"]:
        assert data["voice_available"] is False
    # un canal activo nunca puede estar bloqueado
    if call_chan["active"]:
        assert call_chan["locked"] is False
    # SMS gateado por plan (Business) en la tira global: si esta bloqueado, no disponible ni activo.
    sms_chan = gchans["sms"]
    if sms_chan["locked"]:
        assert sms_chan["plan_needed"] == "Business"
        assert sms_chan["active"] is False
        assert data["channel_availability"]["sms"] is False


def test_followup_save_delivery_priority(client: TestClient, api_module):
    """PUT /auth/app/follow-up guarda el orden de entrega y completa canales omitidos."""
    from backend import clients as clients_module

    cookies = _portal_admin_cookies(api_module)
    original_reminders = json.loads(json.dumps(api_module.CONFIG_CLIENTES["demo"].get("reminders")))
    try:
        r = client.put(
            "/auth/app/follow-up",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={"delivery_priority": ["sms", "email"]},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["delivery_priority"] == ["sms", "email", "whatsapp"]
        assert api_module.CONFIG_CLIENTES["demo"]["reminders"]["delivery_priority"] == ["sms", "email", "whatsapp"]
    finally:
        next_configs = json.loads(json.dumps(api_module.CONFIG_CLIENTES))
        if original_reminders is None:
            next_configs["demo"].pop("reminders", None)
        else:
            next_configs["demo"]["reminders"] = original_reminders
        clients_module._update_runtime_configs(next_configs)
        clients_module._persist_configs_to_disk(next_configs)


def test_reviews_overview_and_save_endpoint(client: TestClient, api_module):
    """GET/PUT /auth/app/reviews: config post-cita + canales por plan + validacion de enlace."""
    cookies = _portal_admin_cookies(api_module)
    r = client.get("/auth/app/reviews", params={"cliente_id": "demo"}, cookies=cookies)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["enabled"] is False
    assert data["default_message"]
    chans = {c["channel"] for c in data["channels"]}
    assert chans == {"email", "whatsapp", "sms"}
    email_chan = next(c for c in data["channels"] if c["channel"] == "email")
    assert email_chan["locked"] is False and email_chan["available"] is True

    saved = client.put(
        "/auth/app/reviews", params={"cliente_id": "demo"}, cookies=cookies,
        json={"enabled": True, "link": "https://g.page/r/demo/review",
              "delay_hours": 6, "channels": {"email": True, "whatsapp": False, "sms": False},
              "message": "Gracias {empresa}, reseña: {enlace}"},
    )
    assert saved.status_code == 200, saved.text
    out = saved.json()
    assert out["enabled"] is True
    assert out["link_valid"] is True
    assert out["platform_label"] == "Dejar resena en Google"
    assert out["delay_hours"] == 6
    assert out["preview_html"]
    # SMS gateado por plan: si bloqueado, nunca activo.
    sms_chan = next(c for c in out["channels"] if c["channel"] == "sms")
    if sms_chan["locked"]:
        assert sms_chan["active"] is False


def test_review_request_engine_sends_and_dedups(api_module, monkeypatch):
    """El motor post-cita envia la peticion de resena una sola vez por cita completada."""
    from backend import booking as bk, emailing as em

    sent = []
    monkeypatch.setattr(em, "_send_client_email",
                        lambda cid, to, subject, text, html="", reply_to=None: sent.append((to, subject)) or "vantelia_smtp")

    api_module.CONFIG_CLIENTES["demo"]["reviews"] = {
        "enabled": True, "link": "https://g.page/r/demo/review", "delay_hours": 3,
        "channels": {"email": True, "whatsapp": False, "sms": False},
    }
    now = api_module._utc_now()
    end_at = (now - timedelta(hours=5)).isoformat().replace("+00:00", "") + "Z"
    booking_id = "bk_review_demo"
    api_module._store_booking({
        "id": booking_id, "cliente_id": "demo", "employee_id": "default_rev", "employee_name": "Equipo",
        "nombre": "Cliente Resena", "email": "review@example.com", "telefono": "+34600123456",
        "servicio": "Consulta", "booking_date": "2099-01-01", "booking_time": "10:00", "notas": "",
        "status": "completed", "provider_name": "internal", "provider_status": "completed",
        "provider_booking_id": "", "provider_booking_url": "", "manage_token": "manage_rev",
        "timezone": "Europe/Madrid", "start_at": end_at, "end_at": end_at,
        "confirmed_at": "", "cancelled_at": "", "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": "", "reminder_2h_sent_at": "",
        "customer_email_status": "", "customer_email_last_error": "", "booking_code": "",
        "completed_source": "auto", "service_id": "consulta", "service_price_cents": 0,
        "source": "test_review", "created_at": api_module._utc_now_iso(),
    })
    try:
        n1 = asyncio.run(bk._run_review_requests(now))
        assert n1 == 1
        assert len(sent) == 1 and sent[0][0] == "review@example.com"
        with sqlite3.connect(api_module.DB_PATH) as conn:
            row = conn.execute("SELECT review_request_sent_at FROM bookings WHERE id=?", (booking_id,)).fetchone()
            assert row and row[0]
            audit = conn.execute(
                "SELECT COUNT(*) FROM booking_audit WHERE booking_id=? AND event_type='review_request_sent'",
                (booking_id,),
            ).fetchone()[0]
            assert audit == 1
        # Segunda pasada: ya marcada -> no reenvia.
        n2 = asyncio.run(bk._run_review_requests(now))
        assert n2 == 0 and len(sent) == 1
    finally:
        api_module.CONFIG_CLIENTES["demo"].pop("reviews", None)
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (booking_id,))
            conn.commit()


def test_reschedule_via_drag_payload_moves_booking(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    target = datetime.utcnow().date() + timedelta(days=2)
    while target.weekday() == 6:
        target += timedelta(days=1)
    fecha = target.isoformat()
    created = client.post("/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies,
                          json={"nombre": "Drag Cliente", "email": "", "telefono": "600333111",
                                "servicio": "", "employee_id": "", "fecha": fecha, "hora": "09:00", "notas": ""})
    assert created.status_code == 200, created.text
    bid = created.json()["booking_id"]
    emp_id = created.json().get("employee_id", "")
    # Payload que envía el drag&drop: {employee_id, fecha, hora}.
    r = client.post(f"/auth/bookings/{bid}/reschedule", cookies=cookies,
                    json={"employee_id": emp_id, "fecha": fecha, "hora": "09:30"})
    assert r.status_code == 200, r.text
    with sqlite3.connect(api_module.DB_PATH) as conn:
        bt = conn.execute("SELECT booking_time FROM bookings WHERE id=?", (bid,)).fetchone()[0]
    assert bt == "09:30"
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE id=?", (bid,)); conn.commit()


def test_ai_rebooking_selects_inactive_and_dedups(api_module, monkeypatch):
    api_module._ensure_channel_settings("demo")
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("UPDATE client_channel_settings SET ai_rebooking_enabled=1 WHERE cliente_id='demo'")
        conn.commit()

    def _seed_completed(phone, days_ago):
        bid = uuid.uuid4().hex
        d = datetime.utcnow().date() - timedelta(days=days_ago)
        start = datetime.utcnow() - timedelta(days=days_ago)
        iso = lambda x: x.isoformat(timespec="seconds") + "Z"
        api_module._store_booking({
            "id": bid, "cliente_id": "demo", "employee_id": "", "employee_name": "",
            "nombre": "Inactivo", "email": "", "telefono": phone,
            "servicio": "Masaje", "booking_date": d.isoformat(), "booking_time": "09:00",
            "notas": "", "status": "completed", "provider_name": "internal", "provider_status": "internal",
            "provider_booking_id": "", "provider_booking_url": "", "manage_token": f"mg_{bid}",
            "timezone": "Europe/Madrid", "start_at": iso(start), "end_at": iso(start + timedelta(minutes=30)),
            "confirmed_at": iso(start), "cancelled_at": "", "rescheduled_at": "",
            "rescheduled_from_booking_id": "", "confirmation_email_sent_at": "", "reminder_24h_sent_at": "",
            "reminder_2h_sent_at": "", "customer_email_status": "", "customer_email_last_error": "",
            "source": "test", "created_at": iso(start),
        })
        return bid

    sent = []

    async def _fake_wa(**kwargs):
        sent.append(kwargs.get("to_number"))
        return True

    monkeypatch.setattr(api_module, "_send_whatsapp_text", _fake_wa)
    api_module.ai_rebooking_last_run = ""

    _seed_completed("600900001", 40)   # elegible
    _seed_completed("600900002", 5)    # demasiado reciente
    _seed_completed("600900003", 40)   # tiene cita futura (abajo)
    future_d = (datetime.utcnow().date() + timedelta(days=3)).isoformat()
    with sqlite3.connect(api_module.DB_PATH) as conn:
        fbid = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO bookings (id,cliente_id,employee_id,employee_name,nombre,email,telefono,servicio,booking_date,booking_time,notas,status,provider_name,provider_status,manage_token,timezone,source,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (fbid, "demo", "", "", "Futuro", "", "600900003", "Masaje", future_d, "11:00", "", "confirmed",
             "internal", "internal", f"mg_{fbid}", "Europe/Madrid", "test", future_d + "T11:00:00Z"),
        )
        conn.commit()

    asyncio.run(api_module._run_ai_rebooking_pass())
    assert "600900001" in sent
    assert "600900002" not in sent
    assert "600900003" not in sent

    sent.clear()
    asyncio.run(api_module._run_ai_rebooking_pass())
    assert "600900001" not in sent  # dedup

    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE cliente_id='demo' AND telefono LIKE '6009000%'")
        conn.execute("DELETE FROM ai_rebooking_log WHERE cliente_id='demo'")
        conn.execute("UPDATE client_channel_settings SET ai_rebooking_enabled=0 WHERE cliente_id='demo'")
        conn.commit()


def test_gift_card_assign_to_client_and_movements(client: TestClient, api_module):
    """Asignar una tarjeta regalo existente a un cliente: dedup, reasignacion forzada
    y trazabilidad (movimientos issue + assign)."""
    cookies = _portal_admin_cookies(api_module)
    params = {"cliente_id": "demo"}
    r = client.post("/auth/gift-cards", params=params, cookies=cookies, json={"amount_cents": 5000})
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    gid = r.json()["gift_card_id"]
    try:
        # Asignar a Ana por codigo.
        r = client.post("/auth/gift-cards/assign", params=params, cookies=cookies,
                        json={"code": code, "recipient_name": "Ana Cliente", "recipient_email": "ana@example.com"})
        assert r.status_code == 200, r.text
        assert r.json()["recipient_email"] == "ana@example.com"
        kinds = [t["kind"] for t in r.json()["transactions"]]
        assert "assign" in kinds and "issue" in kinds
        # Reasignar al MISMO cliente -> 409 (duplicado).
        r = client.post("/auth/gift-cards/assign", params=params, cookies=cookies,
                        json={"code": code, "recipient_email": "ana@example.com"})
        assert r.status_code == 409 and "este cliente" in r.json()["detail"]
        # Asignar a OTRO cliente sin force -> 409.
        r = client.post("/auth/gift-cards/assign", params=params, cookies=cookies,
                        json={"code": code, "recipient_name": "Beto", "recipient_email": "beto@example.com"})
        assert r.status_code == 409 and "reasignar" in r.json()["detail"].lower()
        # Con force -> 200 y queda a nombre de Beto.
        r = client.post("/auth/gift-cards/assign", params=params, cookies=cookies,
                        json={"code": code, "recipient_name": "Beto", "recipient_email": "beto@example.com", "force": True})
        assert r.status_code == 200 and r.json()["recipient_email"] == "beto@example.com"
        # La tarjeta aparece al buscar por el email del destinatario.
        listed = client.get("/auth/gift-cards", params={**params, "q": "beto@example.com"}, cookies=cookies).json()["items"]
        assert any(g["gift_card_id"] == gid for g in listed)
        # Detalle con movimientos.
        detail = client.get(f"/auth/gift-cards/{gid}", params=params, cookies=cookies).json()
        assert detail["gift_card_id"] == gid and len(detail["transactions"]) >= 3
        # Codigo inexistente -> 404.
        r = client.post("/auth/gift-cards/assign", params=params, cookies=cookies,
                        json={"code": "GC-ZZZZ-ZZZZ", "recipient_name": "X"})
        assert r.status_code == 404
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM gift_cards WHERE cliente_id='demo'")
            conn.execute("DELETE FROM gift_card_transactions WHERE cliente_id='demo'")
            conn.commit()


def test_reschedule_changes_employee_and_preserves_payment(client: TestClient, api_module):
    """Reprogramar permite cambiar de profesional y conserva el estado de pago y la
    trazabilidad (audit booking_rescheduled)."""
    cookies = _portal_admin_cookies(api_module)
    params = {"cliente_id": "demo"}
    # Segundo profesional.
    emp = client.post("/auth/employees", params=params, cookies=cookies,
                      json={"name": "Pro Dos", "role_label": "", "color": "#ff8800"})
    assert emp.status_code == 200, emp.text
    emp2 = emp.json().get("employee_id") or emp.json().get("id")
    target = datetime.utcnow().date() + timedelta(days=2)
    while target.weekday() == 6:
        target += timedelta(days=1)
    fecha = target.isoformat()
    created = client.post("/auth/bookings", params=params, cookies=cookies,
                          json={"nombre": "Resched Cliente", "email": "rs@example.com", "telefono": "600111222",
                                "servicio": "", "employee_id": "", "fecha": fecha, "hora": "09:00", "notas": ""})
    assert created.status_code == 200, created.text
    bid = created.json()["booking_id"]
    try:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("UPDATE bookings SET payment_status='paid' WHERE id=?", (bid,))
            conn.commit()
        # Reprogramar a otra hora Y otro profesional.
        r = client.post(f"/auth/bookings/{bid}/reschedule", cookies=cookies,
                        json={"employee_id": emp2, "fecha": fecha, "hora": "09:30"})
        assert r.status_code == 200, r.text
        with sqlite3.connect(api_module.DB_PATH) as conn:
            row = conn.execute("SELECT booking_time, employee_id, payment_status FROM bookings WHERE id=?", (bid,)).fetchone()
            assert row[0] == "09:30" and row[1] == emp2 and row[2] == "paid"
            audit = conn.execute(
                "SELECT COUNT(*) FROM booking_audit WHERE booking_id=? AND event_type='booking_rescheduled'", (bid,)
            ).fetchone()[0]
            assert audit >= 1
        # El payload legacy {new_datetime} ya no es valido (contrato fecha/hora).
        r = client.post(f"/auth/bookings/{bid}/reschedule", cookies=cookies, json={"new_datetime": fecha + "T10:00:00"})
        assert r.status_code == 422
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id=?", (bid,))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (bid,))
            conn.execute("DELETE FROM employees WHERE id=?", (emp2,))
            conn.commit()


def test_confirm_call_dedup_and_validations(client: TestClient, api_module, monkeypatch):
    """Llamar para confirmar: coloca la llamada (proveedor simulado), evita duplicados
    recientes y devuelve errores claros sin telefono o en citas no activas."""
    from backend import booking as bk
    cookies = _portal_admin_cookies(api_module)
    placed = []

    def _fake_place(cliente_id, booking_row, *, base_url="", purpose="confirm"):
        bk._record_booking_audit(booking_row["id"], cliente_id, "confirm_call_placed",
                                 {"call_sid": "CA_test", "purpose": purpose})
        placed.append(booking_row["id"])
        return {"ok": True, "call_sid": "CA_test"}

    monkeypatch.setattr("backend.voice._voice_place_outbound_call", _fake_place)
    now = api_module._utc_now()
    bid = "cc_" + uuid.uuid4().hex
    _seed_confirmed_booking(api_module, booking_id=bid, start=now + timedelta(days=1, minutes=11))
    bid_np = "ccnp_" + uuid.uuid4().hex
    _seed_confirmed_booking(api_module, booking_id=bid_np, start=now + timedelta(days=1, minutes=41))
    try:
        r = client.post(f"/auth/bookings/{bid}/confirm-call", cookies=cookies)
        assert r.status_code == 200, r.text
        assert placed == [bid]
        # Dedup: segundo intento inmediato -> 409.
        r = client.post(f"/auth/bookings/{bid}/confirm-call", cookies=cookies)
        assert r.status_code == 409 and "reciente" in r.json()["detail"].lower()
        # Sin telefono -> 409 claro.
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("UPDATE bookings SET telefono='' WHERE id=?", (bid_np,)); conn.commit()
        r = client.post(f"/auth/bookings/{bid_np}/confirm-call", cookies=cookies)
        assert r.status_code == 409 and "telefono" in r.json()["detail"].lower()
        # Cita cancelada -> 409.
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (bid_np,)); conn.commit()
        r = client.post(f"/auth/bookings/{bid_np}/confirm-call", cookies=cookies)
        assert r.status_code == 409
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id IN (?, ?)", (bid, bid_np))
            conn.execute("DELETE FROM booking_audit WHERE booking_id IN (?, ?)", (bid, bid_np))
            conn.commit()


def test_confirm_call_clear_error_without_voice_number(client: TestClient, api_module):
    """Sin numero de voz configurado, la llamada falla con un mensaje claro (no 500)."""
    cookies = _portal_admin_cookies(api_module)
    now = api_module._utc_now()
    bid = "ccv_" + uuid.uuid4().hex
    _seed_confirmed_booking(api_module, booking_id=bid, start=now + timedelta(days=1, hours=2, minutes=13))
    try:
        r = client.post(f"/auth/bookings/{bid}/confirm-call", cookies=cookies)
        assert r.status_code == 409
        assert "voz" in r.json()["detail"].lower() or "telefon" in r.json()["detail"].lower()
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id=?", (bid,))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (bid,))
            conn.commit()


def test_send_confirmation_validates_and_reports(client: TestClient, api_module, monkeypatch):
    """Enviar confirmacion: 409 claro si no hay email o el correo no esta configurado;
    200 con canal entregado cuando el envio funciona; registra confirmation_resent."""
    from backend import booking as bk
    cookies = _portal_admin_cookies(api_module)
    now = api_module._utc_now()
    # Cita SIN email -> 409 claro.
    bid_ne = "scne_" + uuid.uuid4().hex
    _seed_confirmed_booking(api_module, booking_id=bid_ne, start=now + timedelta(days=1, hours=3, minutes=17))
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("UPDATE bookings SET email='' WHERE id=?", (bid_ne,)); conn.commit()
    # Cita CON email (correo no configurado en test) -> 409 con motivo concreto.
    bid_em = "scem_" + uuid.uuid4().hex
    _seed_confirmed_booking(api_module, booking_id=bid_em, start=now + timedelta(days=1, hours=3, minutes=47))
    try:
        r = client.post(f"/auth/bookings/{bid_ne}/send-confirmation", cookies=cookies)
        assert r.status_code == 409 and "email" in r.json()["detail"].lower()

        r = client.post(f"/auth/bookings/{bid_em}/send-confirmation", cookies=cookies)
        assert r.status_code == 409  # correo no configurado -> error concreto

        # Con envio funcionando -> 200 + audit.
        monkeypatch.setattr("backend.booking._send_booking_email", lambda *a, **k: None)
        r = client.post(f"/auth/bookings/{bid_em}/send-confirmation", cookies=cookies)
        assert r.status_code == 200, r.text
        assert "email" in r.json()["mensaje"].lower()
        with sqlite3.connect(api_module.DB_PATH) as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM booking_audit WHERE booking_id=? AND event_type='confirmation_resent'", (bid_em,)
            ).fetchone()[0]
            assert n >= 1
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id IN (?, ?)", (bid_ne, bid_em))
            conn.execute("DELETE FROM booking_audit WHERE booking_id IN (?, ?)", (bid_ne, bid_em))
            conn.commit()


def test_follow_up_ladder_end_to_end(client: TestClient, api_module, monkeypatch):
    """Escalera de Seguimiento de punta a punta en una pasada, sin envios reales:
    recordatorio 24h, recordatorio 2h y llamada de confirmacion (proveedor simulado)."""
    from backend import booking as bk
    sent = []

    async def _rec(row, kind, *a, **k):
        sent.append((row["id"], kind))
        return {"sent": ["email"], "failed": {}, "skipped": {}}

    calls = []

    def _fake_place(cliente_id, booking_row, *, base_url="", purpose="confirm"):
        bk._record_booking_audit(booking_row["id"], cliente_id, "confirm_call_placed", {"purpose": purpose})
        calls.append(booking_row["id"])
        return {"ok": True, "call_sid": "CA_x"}

    monkeypatch.setattr("backend.booking._send_booking_reminder_by_kind", _rec)
    monkeypatch.setattr("backend.voice._voice_place_outbound_call", _fake_place)
    # Gate de llamada (quiet hours/twilio) neutralizado en test: solo nos interesa la escalera.
    monkeypatch.setattr("backend.booking._reminder_calls_ok_now", lambda *a, **k: True)
    # Activa la llamada de confirmacion del tenant via config['reminders'].
    cfg = api_module.CONFIG_CLIENTES["demo"]
    prev_reminders = cfg.get("reminders")
    cfg["reminders"] = {"call_enabled": True, "call_hours_before": 5, "daily_call_cap": 50}
    now = api_module._utc_now()
    b24 = "lad24_" + uuid.uuid4().hex   # a ~24h -> recordatorio 24h
    b2 = "lad2_" + uuid.uuid4().hex     # a ~2h, ya enviado 24h -> recordatorio 2h
    bcall = "ladc_" + uuid.uuid4().hex  # a ~4h, sin confirmar -> llamada
    _seed_confirmed_booking(api_module, booking_id=b24, start=now + timedelta(hours=24, minutes=10))
    _seed_confirmed_booking(api_module, booking_id=b2, start=now + timedelta(hours=2, minutes=10),
                            reminder_24h_sent=(now - timedelta(hours=20)).isoformat())
    _seed_confirmed_booking(api_module, booking_id=bcall, start=now + timedelta(hours=4, minutes=10),
                            reminder_24h_sent=(now - timedelta(hours=2)).isoformat())
    try:
        asyncio.run(api_module._run_booking_reminders())
        assert (b24, "reminder_24h") in sent
        assert (b2, "reminder_2h") in sent
        # La llamada se coloca para la cita en ventana T-5 aun sin confirmar.
        assert bcall in calls
    finally:
        if prev_reminders is None:
            cfg.pop("reminders", None)
        else:
            cfg["reminders"] = prev_reminders
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id IN (?, ?, ?)", (b24, b2, bcall))
            conn.execute("DELETE FROM booking_audit WHERE booking_id IN (?, ?, ?)", (b24, b2, bcall))
            conn.execute("DELETE FROM voice_calls WHERE cliente_id='demo'")
            conn.commit()


def test_follow_up_test_endpoint_each_phase(client: TestClient, api_module, monkeypatch):
    """Los botones de 'Probar' del Seguimiento ejecutan la fase real contra un
    destinatario de prueba, reportan por canal y no dejan rastro en la agenda."""
    cookies = _portal_admin_cookies(api_module)
    params = {"cliente_id": "demo"}

    # El overview expone destinatarios de prueba por defecto.
    ov = client.get("/auth/app/follow-up", params=params, cookies=cookies).json()
    assert "default_test_email" in ov and "default_test_phone" in ov

    # Email sin SMTP -> canal email no entregado (failed/skipped) con motivo.
    # Y los 3 canales SIEMPRE aparecen: los no activos en la fase como 'inactive'.
    r = client.post("/auth/app/follow-up/test", params=params, cookies=cookies,
                    json={"step": "confirmed", "email": "probar@example.com"})
    assert r.status_code == 200, r.text
    chans = {x["channel"]: x for x in r.json()["results"]}
    assert set(chans) == {"email", "whatsapp", "sms"}
    assert chans["email"]["status"] in ("failed", "skipped") and chans["email"]["detail"]
    # WhatsApp/SMS no activos por defecto en la demo -> reportados como inactive.
    assert chans["whatsapp"]["status"] == "inactive" and chans["sms"]["status"] == "inactive"

    # Con el envío funcionando -> email 'sent'.
    monkeypatch.setattr("backend.booking._send_booking_email", lambda *a, **k: None)
    r = client.post("/auth/app/follow-up/test", params=params, cookies=cookies,
                    json={"step": "reminder_24h", "email": "probar@example.com"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert any(x["channel"] == "email" and x["status"] == "sent" for x in r.json()["results"])

    # Llamada de prueba con proveedor simulado.
    placed = []

    def _fake_place(cliente_id, booking_row, *, base_url="", purpose="confirm"):
        placed.append(booking_row["id"])
        return {"ok": True, "call_sid": "CA_x"}

    monkeypatch.setattr("backend.voice._voice_place_outbound_call", _fake_place)
    r = client.post("/auth/app/follow-up/test", params=params, cookies=cookies,
                    json={"step": "call", "phone": "+34600111222"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert placed and placed[0].startswith("futest_")

    # Sin destinatario y sin contacto del negocio -> 400 (fase de mensaje).
    import json as _json
    cfg = api_module.CONFIG_CLIENTES["demo"]
    prev_contact = _json.loads(_json.dumps(cfg.get("contacto", {})))
    cfg["contacto"] = {}
    try:
        r = client.post("/auth/app/follow-up/test", params=params, cookies=cookies, json={"step": "confirmed"})
        assert r.status_code == 400
    finally:
        cfg["contacto"] = prev_contact

    # Reseña: 200 (si hay enlace) o 409 (si falta), nunca 500.
    r = client.post("/auth/app/follow-up/test", params=params, cookies=cookies,
                    json={"step": "review", "email": "x@example.com"})
    assert r.status_code in (200, 409)

    # Cita efímera: sin rastro en agenda ni auditoría.
    with sqlite3.connect(api_module.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM bookings WHERE id LIKE 'futest_%'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM booking_audit WHERE booking_id LIKE 'futest_%'").fetchone()[0] == 0


def test_service_price_and_duration_parsing(api_module):
    assert api_module._parse_price_to_cents("45 €") == 4500
    assert api_module._parse_price_to_cents("Desde 30 €") == 3000
    assert api_module._parse_price_to_cents("60,50 €") == 6050
    assert api_module._parse_price_to_cents("1.250 €") == 125000
    assert api_module._parse_price_to_cents("40.50") == 4050
    assert api_module._parse_price_to_cents("A consultar") == 0
    assert api_module._parse_price_to_cents("gratis") == 0
    assert api_module._parse_duration_minutes_text("45 min") == 45
    assert api_module._parse_duration_minutes_text("1 h") == 60
    assert api_module._parse_duration_minutes_text("1h 30 min") == 90
    assert api_module._parse_duration_minutes_text("sin dato") == 0


def test_services_catalog_duration_and_overlap(client: TestClient, api_module):
    user = api_module._get_user_by_email("admin@example.com")
    raw_session = api_module._create_auth_session(user["id"])
    cookies = {"vantelia_portal_session": raw_session}

    created = client.post(
        "/auth/services",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={"nombre": "Larga", "duration_minutes": 60, "price_cents": 5000},
    )
    assert created.status_code == 200, created.text
    svc = created.json()
    slug = svc["id"]
    assert svc["duration_minutes"] == 60 and svc["price_cents"] == 5000
    assert svc["price_label"] == "50 €"

    listed = client.get("/auth/services", params={"cliente_id": "demo"}, cookies=cookies).json()["items"]
    assert any(s["id"] == slug for s in listed)

    public = client.get("/servicios/demo", headers={"Origin": "http://testserver"}).json()["servicios"]
    assert any(s.get("id") == slug and s.get("duration_minutes") == 60 for s in public)

    target = datetime.utcnow().date() + timedelta(days=2)
    while target.weekday() == 6:
        target += timedelta(days=1)
    fecha = target.isoformat()

    # Reserva con servicio de 60 min a las 09:00 (demo abre 09:00-10:00).
    r1 = client.post(
        "/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies,
        json={"nombre": "A", "email": "", "telefono": "", "servicio": "Larga",
              "employee_id": "", "fecha": fecha, "hora": "09:00", "notas": ""},
    )
    assert r1.status_code == 200, r1.text
    booking_id = r1.json()["booking_id"]
    with sqlite3.connect(api_module.DB_PATH) as conn:
        row = conn.execute(
            "SELECT start_at, end_at, service_id, service_price_cents FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
    ds = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
    de = datetime.fromisoformat(row[1].replace("Z", "+00:00"))
    assert int((de - ds).total_seconds() // 60) == 60
    assert row[2] == slug and row[3] == 5000

    # Otra cita a las 09:30 solapa el bloque de 60 min -> conflicto.
    r2 = client.post(
        "/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies,
        json={"nombre": "B", "email": "", "telefono": "", "servicio": "",
              "employee_id": "", "fecha": fecha, "hora": "09:30", "notas": ""},
    )
    assert r2.status_code == 409
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("UPDATE bookings SET source = ? WHERE id = ?", (api_module.DEMO_BOOKING_SOURCE, booking_id))
        conn.commit()

    updated = client.patch(
        f"/auth/services/{slug}",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={"duration_minutes": 15, "price_cents": 3000},
    )
    assert updated.status_code == 200, updated.text
    listed_bookings = client.get(
        "/auth/bookings",
        params={"cliente_id": "demo", "date_from": fecha, "date_to": fecha},
        cookies=cookies,
    )
    assert listed_bookings.status_code == 200, listed_bookings.text
    booking_summary = next(
        item for item in listed_bookings.json()["items"] if item["booking_id"] == booking_id
    )
    assert booking_summary["service_duration_minutes"] == 15
    assert booking_summary["service_price_cents"] == 3000
    with sqlite3.connect(api_module.DB_PATH) as conn:
        synced = conn.execute(
            "SELECT start_at, end_at, service_price_cents FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
    ds = datetime.fromisoformat(synced[0].replace("Z", "+00:00"))
    de = datetime.fromisoformat(synced[1].replace("Z", "+00:00"))
    assert int((de - ds).total_seconds() // 60) == 15
    assert synced[2] == 3000

    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conn.execute("DELETE FROM services WHERE cliente_id = 'demo' AND slug = ?", (slug,))
        conn.commit()


def test_service_duration_allows_adjacent_short_slot_but_blocks_long_overlap(client: TestClient, api_module):
    user = api_module._get_user_by_email("admin@example.com")
    raw_session = api_module._create_auth_session(user["id"])
    cookies = {"vantelia_portal_session": raw_session}
    suffix = uuid.uuid4().hex[:8]
    short_name = f"Corta {suffix}"
    long_name = f"Larga solape {suffix}"

    target = datetime.utcnow().date() + timedelta(days=5)
    while target.weekday() == 6:
        target += timedelta(days=1)
    fecha = target.isoformat()

    created_short = client.post(
        "/auth/services",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={"nombre": short_name, "duration_minutes": 30, "price_cents": 0},
    )
    created_long = client.post(
        "/auth/services",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={"nombre": long_name, "duration_minutes": 50, "price_cents": 0},
    )
    assert created_short.status_code == 200, created_short.text
    assert created_long.status_code == 200, created_long.text
    short_slug = created_short.json()["id"]
    long_slug = created_long.json()["id"]
    booking_id = ""
    try:
        booked = client.post(
            "/auth/bookings",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={
                "nombre": "Reserva borde",
                "email": "",
                "telefono": "",
                "servicio": short_name,
                "employee_id": "",
                "fecha": fecha,
                "hora": "09:30",
                "notas": "",
            },
        )
        assert booked.status_code == 200, booked.text
        booking_id = booked.json()["booking_id"]
        with sqlite3.connect(api_module.DB_PATH) as conn:
            employee_id = conn.execute(
                "SELECT employee_id FROM bookings WHERE id = ?", (booking_id,)
            ).fetchone()[0]

        short_slots = client.get(
            "/disponibilidad",
            params={
                "cliente_id": "demo",
                "fecha": fecha,
                "employee_id": employee_id,
                "servicio": short_name,
            },
            headers={"Origin": "http://testserver"},
        )
        assert short_slots.status_code == 200, short_slots.text
        short_by_hour = {slot["hora"]: slot["disponible"] for slot in short_slots.json()["slots"]}
        assert short_by_hour["09:00"] is True
        assert short_by_hour["09:30"] is False

        long_slots = client.get(
            "/disponibilidad",
            params={
                "cliente_id": "demo",
                "fecha": fecha,
                "employee_id": employee_id,
                "servicio": long_name,
            },
            headers={"Origin": "http://testserver"},
        )
        assert long_slots.status_code == 200, long_slots.text
        long_by_hour = {slot["hora"]: slot["disponible"] for slot in long_slots.json()["slots"]}
        assert long_by_hour["09:00"] is False
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            if booking_id:
                conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
            conn.execute(
                "DELETE FROM services WHERE cliente_id = 'demo' AND slug IN (?, ?)",
                (short_slug, long_slug),
            )
            conn.commit()


def test_schedule_break_filters_slots_by_service_duration(client: TestClient, api_module):
    user = api_module._get_user_by_email("admin@example.com")
    raw_session = api_module._create_auth_session(user["id"])
    cookies = {"vantelia_portal_session": raw_session}
    suffix = uuid.uuid4().hex[:8]
    short_name = f"Corta pausa {suffix}"
    long_name = f"Larga pausa {suffix}"
    created_ids: list[str] = []
    employee_id = ""

    target = datetime.utcnow().date() + timedelta(days=6)
    while target.weekday() == 6:
        target += timedelta(days=1)
    fecha = target.isoformat()

    try:
        for name, duration in ((short_name, 30), (long_name, 50)):
            response = client.post(
                "/auth/services",
                params={"cliente_id": "demo"},
                cookies=cookies,
                json={"nombre": name, "duration_minutes": duration, "price_cents": 0},
            )
            assert response.status_code == 200, response.text
            created_ids.append(response.json()["id"])

        employee_response = client.post(
            "/auth/employees",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={
                "name": f"Turnos {suffix}",
                "role_label": "Pruebas",
                "color": "#00b1d9",
                "is_active": True,
                "timezone": "Europe/Madrid",
                "slot_minutes": 30,
                "day_start": "09:00",
                "day_end": "16:00",
                "break_windows": [
                    {"start": "12:00", "end": "12:30", "reason": "Media manana"},
                    {"start": "14:00", "end": "15:00", "reason": "Comida"},
                ],
                "closed_weekdays": [],
                "service_ids": [],
            },
        )
        assert employee_response.status_code == 200, employee_response.text
        employee_id = employee_response.json()["employee_id"]

        short_slots = client.get(
            "/disponibilidad",
            params={
                "cliente_id": "demo",
                "fecha": fecha,
                "employee_id": employee_id,
                "servicio": short_name,
            },
            headers={"Origin": "http://testserver"},
        )
        assert short_slots.status_code == 200, short_slots.text
        short_by_hour = {slot["hora"]: slot["disponible"] for slot in short_slots.json()["slots"]}
        assert short_by_hour["11:30"] is True
        assert "12:00" not in short_by_hour
        assert short_by_hour["12:30"] is True
        assert short_by_hour["13:30"] is True
        assert "14:00" not in short_by_hour
        assert "14:30" not in short_by_hour
        assert short_by_hour["15:00"] is True

        long_slots = client.get(
            "/disponibilidad",
            params={
                "cliente_id": "demo",
                "fecha": fecha,
                "employee_id": employee_id,
                "servicio": long_name,
            },
            headers={"Origin": "http://testserver"},
        )
        assert long_slots.status_code == 200, long_slots.text
        long_by_hour = {slot["hora"]: slot["disponible"] for slot in long_slots.json()["slots"]}
        assert "11:30" not in long_by_hour
        assert long_by_hour["11:00"] is True
        assert "13:30" not in long_by_hour
        assert long_by_hour["15:00"] is True

        blocked_booking = client.post(
            "/auth/bookings",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={
                "nombre": "No cabe",
                "email": "",
                "telefono": "",
                "servicio": long_name,
                "employee_id": employee_id,
                "fecha": fecha,
                "hora": "11:30",
                "notas": "",
            },
        )
        assert blocked_booking.status_code == 409
    finally:
        if employee_id:
            client.delete(f"/auth/employees/{employee_id}", params={"cliente_id": "demo"}, cookies=cookies)
        with sqlite3.connect(api_module.DB_PATH) as conn:
            if created_ids:
                conn.execute(
                    "DELETE FROM services WHERE cliente_id = 'demo' AND slug IN (%s)"
                    % ",".join("?" for _ in created_ids),
                    tuple(created_ids),
                )
            conn.commit()


def test_schedule_break_rejects_future_booking_conflicts(client: TestClient, api_module):
    user = api_module._get_user_by_email("admin@example.com")
    raw_session = api_module._create_auth_session(user["id"])
    cookies = {"vantelia_portal_session": raw_session}
    suffix = uuid.uuid4().hex[:8]
    service_name = f"Cita pausa {suffix}"
    service_id = ""
    employee_id = ""
    booking_id = ""

    target = datetime.utcnow().date() + timedelta(days=7)
    while target.weekday() == 6:
        target += timedelta(days=1)
    fecha = target.isoformat()

    try:
        service_response = client.post(
            "/auth/services",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={"nombre": service_name, "duration_minutes": 30, "price_cents": 0},
        )
        assert service_response.status_code == 200, service_response.text
        service_id = service_response.json()["id"]

        employee_response = client.post(
            "/auth/employees",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={
                "name": f"Conflicto pausa {suffix}",
                "role_label": "Pruebas",
                "color": "#00b1d9",
                "is_active": True,
                "timezone": "Europe/Madrid",
                "slot_minutes": 30,
                "day_start": "09:00",
                "day_end": "14:00",
                "closed_weekdays": [],
                "service_ids": [],
            },
        )
        assert employee_response.status_code == 200, employee_response.text
        employee_id = employee_response.json()["employee_id"]

        booking_response = client.post(
            "/auth/bookings",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={
                "nombre": "Reserva comida",
                "email": "",
                "telefono": "",
                "servicio": service_name,
                "employee_id": employee_id,
                "fecha": fecha,
                "hora": "12:00",
                "notas": "",
            },
        )
        assert booking_response.status_code == 200, booking_response.text
        booking_id = booking_response.json()["booking_id"]

        update_response = client.post(
            f"/auth/schedule/employee/{employee_id}",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={
                "enabled": True,
                "timezone": "Europe/Madrid",
                "slot_minutes": 30,
                "day_start": "09:00",
                "day_end": "14:00",
                "break_windows": [
                    {"start": "11:00", "end": "11:30", "reason": "Pausa"},
                    {"start": "12:00", "end": "13:00", "reason": "Comida"},
                ],
                "closed_weekdays": [],
            },
        )
        assert update_response.status_code == 409
        detail = update_response.json()["detail"]
        assert detail["type"] == "schedule_booking_conflicts"
        assert "descanso" in detail["message"].lower()
        assert detail["conflicts"][0]["booking_id"] == booking_id
        assert detail["conflicts"][0]["can_reschedule"] is True
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            if booking_id:
                conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
            if service_id:
                conn.execute("DELETE FROM services WHERE cliente_id = 'demo' AND slug = ?", (service_id,))
            conn.commit()
        if employee_id:
            client.delete(f"/auth/employees/{employee_id}", params={"cliente_id": "demo"}, cookies=cookies)


def test_today_availability_hides_past_slots_and_rejects_past_booking(
    client: TestClient,
    api_module,
    monkeypatch: pytest.MonkeyPatch,
):
    booking_cfg = api_module.CONFIG_CLIENTES["demo"]["booking"]
    previous_closed = list(booking_cfg.get("closed_weekdays", []))
    tz = api_module.ZoneInfo("Europe/Madrid")
    # Fija "hoy" en un dia laborable (lunes-viernes) para que el horario por defecto
    # (09:00) tenga manana abierta SIEMPRE; si no, el test era flaky en fin de semana.
    today = datetime.now(tz).date()
    while today.weekday() >= 5:  # 5=sabado, 6=domingo
        today += timedelta(days=1)
    fixed_now = datetime(today.year, today.month, today.day, 9, 15, tzinfo=tz)
    monkeypatch.setattr(api_module, "_utc_now", lambda: fixed_now.astimezone(api_module.timezone.utc))
    booking_cfg["closed_weekdays"] = []

    user = api_module._get_user_by_email("admin@example.com")
    raw_session = api_module._create_auth_session(user["id"])
    cookies = {"vantelia_portal_session": raw_session}
    employee = api_module._resolve_employee_for_booking("demo", "", require_active=False)

    try:
        availability = client.get(
            "/disponibilidad",
            params={
                "cliente_id": "demo",
                "fecha": today.isoformat(),
                "employee_id": employee["id"],
            },
            headers={"Origin": "http://testserver"},
        )
        assert availability.status_code == 200, availability.text
        by_hour = {slot["hora"]: slot["disponible"] for slot in availability.json()["slots"]}
        assert "09:00" not in by_hour
        assert by_hour["09:30"] is True

        past_booking = client.post(
            "/auth/bookings",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={
                "nombre": "Tarde",
                "email": "",
                "telefono": "",
                "servicio": "",
                "employee_id": employee["id"],
                "fecha": today.isoformat(),
                "hora": "09:00",
                "notas": "",
            },
        )
        assert past_booking.status_code == 409
    finally:
        booking_cfg["closed_weekdays"] = previous_closed


def test_block_conflicts_use_actual_booking_duration(api_module):
    target = datetime.utcnow().date() + timedelta(days=8)
    while target.weekday() == 6:
        target += timedelta(days=1)
    fecha = target.isoformat()
    employee = api_module._resolve_employee_for_booking("demo", "", require_active=False)
    start_local, end_local = api_module._booking_start_end(
        "demo",
        fecha,
        "09:00",
        employee_id=employee["id"],
        duration_minutes=50,
    )
    booking_id = uuid.uuid4().hex
    created_at = api_module._utc_now_iso()
    api_module._store_booking({
        "id": booking_id,
        "cliente_id": "demo",
        "employee_id": employee["id"],
        "employee_name": employee["name"] or "",
        "nombre": "Cita larga",
        "email": "",
        "telefono": "",
        "servicio": "Servicio largo",
        "booking_date": fecha,
        "booking_time": "09:00",
        "notas": "",
        "status": "confirmed",
        "provider_name": "internal",
        "provider_status": "confirmed",
        "provider_booking_id": "",
        "provider_booking_url": "",
        "manage_token": f"mg_{booking_id}",
        "timezone": employee["timezone"] or "Europe/Madrid",
        "start_at": api_module._to_utc_iso(start_local),
        "end_at": api_module._to_utc_iso(end_local),
        "confirmed_at": created_at,
        "cancelled_at": "",
        "rescheduled_at": "",
        "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "",
        "reminder_24h_sent_at": "",
        "reminder_2h_sent_at": "",
        "customer_email_status": "",
        "customer_email_last_error": "",
        "service_id": "",
        "service_price_cents": 0,
        "source": "test",
        "created_at": created_at,
    })
    try:
        conflicts = api_module._booking_conflicts_for_block(
            "demo",
            fecha,
            "09:30",
            "09:45",
            employee_id=employee["id"],
        )
        assert [row["id"] for row in conflicts] == [booking_id]
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
            conn.commit()


def test_booking_manage_page_renders_with_service_catalog(client: TestClient, api_module):
    # Regresion: la pagina publica de gestion construye available_services desde el
    # catalogo (con duration/price int + is_active bool). Debe renderizar, no 500.
    user = api_module._get_user_by_email("admin@example.com")
    raw_session = api_module._create_auth_session(user["id"])
    cookies = {"vantelia_portal_session": raw_session}
    target = datetime.utcnow().date() + timedelta(days=2)
    while target.weekday() == 6:
        target += timedelta(days=1)
    created = client.post(
        "/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies,
        json={"nombre": "Manage Test", "email": "", "telefono": "", "servicio": "",
              "employee_id": "", "fecha": target.isoformat(), "hora": "09:00", "notas": ""},
    )
    assert created.status_code == 200, created.text
    token = created.json()["manage_url"].rsplit("/", 1)[-1].split("?")[0]
    page = client.get(f"/booking/manage/{token}")
    assert page.status_code == 200, page.text
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE id = ?", (created.json()["booking_id"],))
        conn.commit()


def test_onboarding_seeds_qa_panel_from_scrape(api_module):
    # Regresion: run_onboarding saca las FAQ del info.txt y las deja en faq_pairs;
    # cualquier flujo de scrape (rebrain/alta-express) debe sembrarlas en kb_qa o
    # el panel de Preguntas Frecuentes queda vacio.
    cid = "demo"
    qs = ("Teneis parking?", "Cual es el horario?")

    class _Result:
        info_txt = "PREGUNTAS FRECUENTES:\n(gestionadas en panel)\n"
        faq_pairs = [(qs[0], "Si, gratis para clientes."), (qs[1], "Lunes a viernes de 9 a 18.")]
        faq_source = "literal"

    def _clean():
        with sqlite3.connect(api_module.DB_PATH) as c:
            c.execute("DELETE FROM kb_qa WHERE cliente_id=? AND question IN (?,?)", (cid, qs[0], qs[1]))
            c.commit()

    _clean()
    created = api_module._seed_qa_from_onboarding(cid, _Result(), "")
    assert created == 2
    with sqlite3.connect(api_module.DB_PATH) as c:
        rows = c.execute("SELECT question FROM kb_qa WHERE cliente_id=? AND question IN (?,?)", (cid, qs[0], qs[1])).fetchall()
    assert len(rows) == 2
    # Idempotente: re-sembrar no duplica.
    assert api_module._seed_qa_from_onboarding(cid, _Result(), "") == 0
    _clean()


def test_onboarding_literal_faq_filter_rejects_cookie_noise():
    from onboarding_utils import _looks_like_faq_pair

    assert not _looks_like_faq_pair(
        "Google Fonts Marketing/Seguimiento Consent to service google-fonts",
        "Uso Usamos Google Fonts para display of webfonts.",
    )
    assert not _looks_like_faq_pair(
        "Preferencias Preferencias",
        "El almacenamiento o acceso tecnico es necesario para almacenar preferencias.",
    )
    assert _looks_like_faq_pair(
        "¿Qué es el drenaje linfático?",
        "El drenaje linfático es una técnica terapéutica manual.",
    )


def test_login_creates_portal_session(client: TestClient):
    response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "test-password-123"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    assert "vantelia_portal_session" in response.cookies


def test_cookie_authenticated_post_rejects_foreign_origin(client: TestClient, api_module):
    user = api_module._get_user_by_email("admin@example.com")
    raw_session = api_module._create_auth_session(user["id"])

    response = client.post(
        "/auth/profile",
        json={"display_name": "Admin Test", "email": "admin@example.com"},
        headers={
            "Cookie": f"vantelia_portal_session={raw_session}",
            "Origin": "https://evil.example",
        },
    )

    assert response.status_code == 403
    assert "Origen no autorizado" in response.json()["detail"]


def test_login_google_signup_account_prompts_google(client: TestClient, api_module):
    email = f"google_login_{uuid.uuid4().hex[:8]}@example.com"
    api_module._create_user_self_serve(
        email=email,
        display_name="Google Login",
        google_sub="google-sub-" + uuid.uuid4().hex,
        signup_source="google",
        email_verified=True,
    )

    response = client.post(
        "/auth/login",
        json={"email": email, "password": "not-the-google-password"},
    )

    assert response.status_code == 409
    assert "Google" in response.json()["detail"]


def test_portal_can_update_professional_schedule(client: TestClient):
    login_response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "test-password-123"},
    )
    assert login_response.status_code == 200
    cookies = {"vantelia_portal_session": login_response.cookies["vantelia_portal_session"]}

    create_response = client.post(
        "/auth/employees",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={
            "name": "Profesional Horario",
            "role_label": "Pruebas",
            "color": "#00b1d9",
            "is_active": True,
            "timezone": "Europe/Madrid",
            "slot_minutes": 30,
            "day_start": "09:00",
            "day_end": "10:00",
            "break_start": "",
            "break_end": "",
            "closed_weekdays": [],
            "service_ids": [],
        },
    )
    assert create_response.status_code == 200, create_response.text
    employee_id = create_response.json()["employee_id"]
    try:
        update_response = client.post(
            f"/auth/schedule/employee/{employee_id}",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={
                "enabled": True,
                "timezone": "Europe/Madrid",
                "slot_minutes": 45,
                "day_start": "11:00",
                "day_end": "15:30",
                "break_windows": [
                    {"start": "13:00", "end": "14:00", "reason": "Comida"},
                    {"start": "14:30", "end": "15:00", "reason": "Pausa"},
                ],
                "closed_weekdays": [0, 2],
            },
        )
        assert update_response.status_code == 200, update_response.text
        schedule = update_response.json()
        assert schedule["slot_minutes"] == 45
        assert schedule["day_start"] == "11:00"
        assert schedule["day_end"] == "15:30"
        assert schedule["break_start"] == "13:00"
        assert schedule["break_end"] == "14:00"
        assert schedule["break_windows"] == [
            {"start": "13:00", "end": "14:00", "reason": "Comida"},
            {"start": "14:30", "end": "15:00", "reason": "Pausa"},
        ]
        assert schedule["closed_weekdays"] == [0, 2]

        get_response = client.get(
            f"/auth/schedule/employee/{employee_id}",
            params={"cliente_id": "demo"},
            cookies=cookies,
        )
        assert get_response.status_code == 200
        assert get_response.json()["slot_minutes"] == 45
        assert get_response.json()["break_start"] == "13:00"
        assert len(get_response.json()["break_windows"]) == 2
    finally:
        client.delete(f"/auth/employees/{employee_id}", params={"cliente_id": "demo"}, cookies=cookies)


def test_portal_can_delete_professional(client: TestClient):
    login_response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "test-password-123"},
    )
    assert login_response.status_code == 200
    cookies = {"vantelia_portal_session": login_response.cookies["vantelia_portal_session"]}

    create_response = client.post(
        "/auth/employees",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={
            "name": "Profesional Borrable",
            "role_label": "Pruebas",
            "color": "#00b1d9",
            "is_active": False,
            "timezone": "Europe/Madrid",
            "slot_minutes": 30,
            "day_start": "09:00",
            "day_end": "10:00",
            "closed_weekdays": [],
            "service_ids": [],
        },
    )
    assert create_response.status_code == 200
    employee_id = create_response.json()["employee_id"]

    delete_response = client.delete(
        f"/auth/employees/{employee_id}",
        params={"cliente_id": "demo"},
        cookies=cookies,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["ok"] is True

    list_response = client.get("/auth/employees", params={"cliente_id": "demo"}, cookies=cookies)
    assert list_response.status_code == 200
    assert employee_id not in {item["employee_id"] for item in list_response.json()["items"]}


def test_portal_cannot_delete_default_professional(client: TestClient):
    login_response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "test-password-123"},
    )
    assert login_response.status_code == 200
    cookies = {"vantelia_portal_session": login_response.cookies["vantelia_portal_session"]}

    list_response = client.get("/auth/employees", params={"cliente_id": "demo"}, cookies=cookies)
    assert list_response.status_code == 200
    default_employee = next(item for item in list_response.json()["items"] if item["is_default"])

    delete_response = client.delete(
        f"/auth/employees/{default_employee['employee_id']}",
        params={"cliente_id": "demo"},
        cookies=cookies,
    )
    assert delete_response.status_code == 409
    assert "agenda principal" in delete_response.json()["detail"]


def test_admin_client_portal_has_full_plan_capabilities(client: TestClient, api_module):
    login_response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "test-password-123"},
    )
    assert login_response.status_code == 200
    cookies = {"vantelia_portal_session": login_response.cookies["vantelia_portal_session"]}

    subscription = client.get("/auth/subscription", params={"cliente_id": "demo"}, cookies=cookies)
    assert subscription.status_code == 200
    sub = subscription.json()
    assert sub["admin_override"] is True
    assert sub["effective_plan"] == "business"
    assert sub["features"]["branding_customization"] is True
    assert sub["features"]["csv_export"] is True
    assert sub["features"]["max_professionals"] is None

    export_response = client.get("/auth/bookings/export", params={"cliente_id": "demo"}, cookies=cookies)
    assert export_response.status_code == 200

    employee_response = client.post(
        "/auth/employees",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={
            "name": "Profesional Admin Full",
            "role_label": "Pruebas",
            "color": "#00b1d9",
            "is_active": True,
            "timezone": "Europe/Madrid",
            "slot_minutes": 30,
            "day_start": "09:00",
            "day_end": "10:00",
            "closed_weekdays": [],
            "service_ids": [],
        },
    )
    assert employee_response.status_code == 200, employee_response.text
    employee_id = employee_response.json()["employee_id"]
    try:
        previous_configs = json.loads(json.dumps(api_module.CONFIG_CLIENTES))
        ai_response = client.post(
            "/auth/ai-config",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={
                "nombre": "Demo Admin Full",
                "icono": "DA",
                "bienvenida": "Hola, soy el asistente demo.",
                "prompt_extra": "Responde con tono profesional.",
                "color": "#123456",
                "accent_color": "#654321",
                "branding_text": "Demo Brand",
                "logo_url": "",
            },
        )
        assert ai_response.status_code == 200, ai_response.text
        ai_config = ai_response.json()
        assert ai_config["color"] == "#123456"
        assert ai_config["accent_color"] == "#654321"
        assert ai_config["branding_text"] == "Demo Brand"
    finally:
        client.delete(f"/auth/employees/{employee_id}", params={"cliente_id": "demo"}, cookies=cookies)
        api_module._persist_configs_to_disk(previous_configs)
        api_module._update_runtime_configs(previous_configs)


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


def test_calendar_range_query_does_not_truncate_at_page_cap(client: TestClient, api_module):
    """La vista calendario pide una ventana de fechas acotada y debe recibir
    todas las citas del rango, no las primeras 100 (que dejaria dias en blanco).
    """
    # Evita un 429 por el rate limit de login acumulado por tests previos.
    with api_module.state_lock:
        api_module.rate_limit_buckets.clear()
    login_response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "test-password-123"},
    )
    assert login_response.status_code == 200
    cookies = {"vantelia_portal_session": login_response.cookies["vantelia_portal_session"]}

    # Ventana muy lejana para no colisionar con citas creadas por otros tests.
    base = datetime.now() + timedelta(days=100)
    total_inserted = 120  # 40 dias x 3 citas/dia, supera el page cap de 100.
    horas = ["09:00", "09:30", "10:00"]
    try:
        with api_module._get_db_connection() as conn:
            for i in range(total_inserted):
                day = base + timedelta(days=i // 3)
                conn.execute(
                    """
                    INSERT INTO bookings
                        (id, cliente_id, employee_id, nombre, email, booking_date,
                         booking_time, status, provider_name, provider_status, source, created_at)
                    VALUES (?, 'demo', '', ?, ?, ?, ?, 'confirmed', 'internal', 'confirmed', 'cal-test', ?)
                    """,
                    (
                        f"cal-test-{i}-{uuid.uuid4().hex[:8]}",
                        f"Cliente {i}",
                        f"cliente{i}@example.com",
                        day.strftime("%Y-%m-%d"),
                        horas[i % 3],
                        api_module._utc_now_iso(),
                    ),
                )
            conn.commit()

        # Rango corto (calendario): devuelve todas las citas, sin truncar.
        short = client.get(
            "/auth/bookings",
            params={
                "cliente_id": "demo",
                "scope": "all",
                "date_from": base.strftime("%Y-%m-%d"),
                "date_to": (base + timedelta(days=39)).strftime("%Y-%m-%d"),
                "limit": 5000,
            },
            cookies=cookies,
        )
        assert short.status_code == 200, short.text
        short_data = short.json()
        assert short_data["total"] >= total_inserted
        assert len(short_data["items"]) == short_data["total"]
        assert len(short_data["items"]) > 100  # antes se truncaba aqui

        # Rango muy amplio: se mantiene el page cap como salvaguarda anti-abuso.
        wide = client.get(
            "/auth/bookings",
            params={
                "cliente_id": "demo",
                "scope": "all",
                "date_from": base.strftime("%Y-%m-%d"),
                "date_to": (base + timedelta(days=200)).strftime("%Y-%m-%d"),
                "limit": 5000,
            },
            cookies=cookies,
        )
        assert wide.status_code == 200, wide.text
        wide_data = wide.json()
        assert wide_data["limit"] == 100
        assert len(wide_data["items"]) == 100
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE source = 'cal-test'")
            conn.commit()


def _build_booking_record(api_module, **overrides):
    """Construye un record minimo valido para api_module._store_booking."""
    now_iso = api_module._utc_now_iso()
    base = api_module.datetime.now() + api_module.timedelta(days=120)
    record = {
        "id": f"bk_test_{uuid.uuid4().hex[:10]}",
        "cliente_id": "demo",
        "employee_id": "",
        "employee_name": "",
        "nombre": "Cliente Prueba",
        "email": "cliente@example.com",
        "telefono": "+34611222333",
        "servicio": "Consulta",
        "booking_date": base.strftime("%Y-%m-%d"),
        "booking_time": "09:00",
        "notas": "",
        "status": "confirmed",
        "provider_name": "internal",
        "provider_status": "confirmed",
        "provider_booking_id": "",
        "provider_booking_url": "",
        "manage_token": f"mg_test_{uuid.uuid4().hex[:10]}",
        "timezone": "Europe/Madrid",
        "start_at": "",
        "end_at": "",
        "confirmed_at": now_iso,
        "cancelled_at": "",
        "rescheduled_at": "",
        "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "",
        "reminder_24h_sent_at": "",
        "reminder_2h_sent_at": "",
        "customer_email_status": "",
        "customer_email_last_error": "",
        "source": "test",
        "created_at": now_iso,
    }
    record.update(overrides)
    return record


def test_booking_code_generation_format(api_module):
    pattern = re.compile(r"^R-[0-9]{6}$")
    for _ in range(50):
        code = api_module._generate_booking_code()
        assert pattern.match(code), code


def test_phone_normalization_for_match(api_module):
    assert api_module._normalize_phone_for_match("+34 611 22 23 33") == "611222333"
    assert api_module._normalize_phone_for_match("0034611222333") == "611222333"
    assert api_module._normalize_phone_for_match("611222333") == "611222333"


def test_sms_recipient_normalization_adds_spanish_prefix(api_module):
    assert api_module._normalize_sms_recipient("600 111 222") == "+34600111222"
    assert api_module._normalize_sms_recipient("0034 600 111 222") == "+34600111222"
    assert api_module._normalize_sms_recipient("+34 600 111 222") == "+34600111222"
    assert api_module._normalize_sms_recipient("123") == ""


def test_booking_code_lookup_and_contact_verification(api_module):
    record = _build_booking_record(api_module)
    try:
        api_module._store_booking(record)
        code = record["booking_code"]
        assert re.match(r"^R-[0-9]{6}$", code)

        # Lookup por codigo (scoped al cliente), tolerante a espacios/mayusculas
        row = api_module._get_booking_row_by_code("demo", code.lower())
        assert row is not None and row["id"] == record["id"]
        assert api_module._get_booking_row_by_code("otro_cliente", code) is None

        # Verificacion de titularidad: telefono (con formato distinto) y email
        assert api_module._booking_contact_matches(row, telefono="611 22 23 33")
        assert api_module._booking_contact_matches(row, email="CLIENTE@example.com")
        assert not api_module._booking_contact_matches(row, telefono="999888777")
        assert not api_module._booking_contact_matches(row, email="otro@example.com")

        # Exposicion en la serializacion que consume el portal
        data = api_module._serialize_booking_row(row)
        assert data["booking_code"] == code
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_backfill_assigns_codes_to_active_bookings_only(api_module):
    base = api_module.datetime.now() + api_module.timedelta(days=130)
    now_iso = api_module._utc_now_iso()
    ids = {
        "confirmed": f"bk_bf_{uuid.uuid4().hex[:10]}",
        "cancelled": f"bk_bf_{uuid.uuid4().hex[:10]}",
    }
    try:
        with api_module._get_db_connection() as conn:
            for status_value, time_value in (("confirmed", "11:00"), ("cancelled", "11:30")):
                conn.execute(
                    "INSERT INTO bookings "
                    "(id, cliente_id, nombre, email, booking_date, booking_time, status, "
                    " provider_status, source, created_at, booking_code) "
                    "VALUES (?, 'demo', 'Cliente BF', 'bf@example.com', ?, ?, ?, ?, 'test', ?, '')",
                    (ids[status_value], base.strftime("%Y-%m-%d"), time_value, status_value, status_value, now_iso),
                )
            conn.commit()

        assigned = api_module._backfill_booking_codes()
        assert assigned >= 1

        with api_module._get_db_connection() as conn:
            code_conf = conn.execute(
                "SELECT booking_code FROM bookings WHERE id = ?", (ids["confirmed"],)
            ).fetchone()[0]
            code_canc = conn.execute(
                "SELECT booking_code FROM bookings WHERE id = ?", (ids["cancelled"],)
            ).fetchone()[0]
        assert re.match(r"^R-[0-9]{6}$", code_conf)
        assert code_canc == ""  # cancelada: no necesita codigo

        # Idempotencia: una segunda pasada no reasigna nada de estas dos
        with api_module._get_db_connection() as conn:
            second = conn.execute(
                "SELECT booking_code FROM bookings WHERE id = ?", (ids["confirmed"],)
            ).fetchone()[0]
        assert second == code_conf
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute(
                "DELETE FROM bookings WHERE id IN (?, ?)", (ids["confirmed"], ids["cancelled"])
            )
            conn.commit()


def test_chat_can_cancel_booking_by_code(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    record = _build_booking_record(api_module)

    async def _noop_cancel_provider(_row):
        return None

    async def _noop_email(*_args, **_kwargs):
        return True

    monkeypatch.setattr(api_module, "_cancel_provider_booking", _noop_cancel_provider)
    monkeypatch.setattr(api_module, "_send_booking_email_by_kind", _noop_email)
    try:
        api_module._store_booking(record)
        code = record["booking_code"]

        response = client.post(
            "/chat",
            json={
                "cliente_id": "demo",
                "mensaje": f"Quiero cancelar mi cita {code}, mi email es cliente@example.com",
                "session_id": f"s_cancel_{uuid.uuid4().hex[:8]}",
            },
            headers={"Origin": "http://testserver"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "booking_cancel"
        assert "cancelada" in data["respuesta"].lower()
        with api_module._get_db_connection() as conn:
            status_value = conn.execute(
                "SELECT status FROM bookings WHERE id = ?", (record["id"],)
            ).fetchone()[0]
        assert status_value == "cancelled"
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_chat_can_reschedule_booking_by_code(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    record = _build_booking_record(api_module)
    captured = {}

    async def _fake_update(row, payload, request, *, source, audit_payload=None):
        captured.update(
            {
                "booking_id": row["id"],
                "fecha": payload.fecha,
                "hora": payload.hora,
                "source": source,
                "audit_payload": audit_payload,
            }
        )
        return api_module.BookingActionResponse(
            ok=True,
            booking_id=row["id"],
            estado="confirmed",
            mensaje="La cita se ha actualizado correctamente.",
            employee_id=row["employee_id"] or "",
            employee_name=row["employee_name"] or "",
            manage_url="",
            provider_booking_url="",
        )

    monkeypatch.setattr(api_module, "_update_booking_details", _fake_update)
    try:
        api_module._store_booking(record)
        code = record["booking_code"]

        response = client.post(
            "/chat",
            json={
                "cliente_id": "demo",
                "mensaje": (
                    f"Quiero cambiar la cita {code} al 2026-06-15 a las 09:30. "
                    "Mi telefono es 611222333"
                ),
                "session_id": f"s_reschedule_{uuid.uuid4().hex[:8]}",
            },
            headers={"Origin": "http://testserver"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "booking_reschedule"
        assert "09:30" in data["respuesta"]
        assert captured == {
            "booking_id": record["id"],
            "fecha": "2026-06-15",
            "hora": "09:30",
            "source": "chat",
            "audit_payload": {"channel": "chat", "trusted_phone": ""},
        }
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_chat_manage_flow_remembers_steps(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    """Cancelacion en 3 mensajes SIN repetir datos: intencion -> codigo -> contacto.
    La memoria conversacional (chat_manage_state) recuerda lo ya dicho en la sesion."""
    record = _build_booking_record(api_module)

    async def _noop_cancel_provider(_row):
        return None

    async def _noop_email(*_args, **_kwargs):
        return True

    monkeypatch.setattr(api_module, "_cancel_provider_booking", _noop_cancel_provider)
    monkeypatch.setattr(api_module, "_send_booking_email_by_kind", _noop_email)
    session_id = f"s_manage_mem_{uuid.uuid4().hex[:8]}"

    def _say(msg):
        response = client.post(
            "/chat",
            json={"cliente_id": "demo", "mensaje": msg, "session_id": session_id},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200
        return response.json()

    try:
        api_module._store_booking(record)
        code = record["booking_code"]

        step1 = _say("Quiero cancelar mi cita")
        assert step1["intent"] == "booking_manage"
        assert "numero de reserva" in step1["respuesta"].lower()

        step2 = _say(f"Es la {code}")
        assert step2["intent"] == "booking_manage"
        assert "telefono o el email" in step2["respuesta"].lower()

        step3 = _say("Mi email es cliente@example.com")
        assert step3["intent"] == "booking_cancel"
        assert "cancelada" in step3["respuesta"].lower()
        with api_module._get_db_connection() as conn:
            status_value = conn.execute(
                "SELECT status FROM bookings WHERE id = ?", (record["id"],)
            ).fetchone()[0]
        assert status_value == "cancelled"
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_chat_greeting_with_intent_is_not_hijacked_by_menu(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    """'Hola, quiero cancelar mi cita R-XXXX' debe procesar la CANCELACION, no responder
    con el menu (el saludo solo gana si es un saludo puro)."""
    record = _build_booking_record(api_module)

    async def _noop_cancel_provider(_row):
        return None

    async def _noop_email(*_args, **_kwargs):
        return True

    monkeypatch.setattr(api_module, "_cancel_provider_booking", _noop_cancel_provider)
    monkeypatch.setattr(api_module, "_send_booking_email_by_kind", _noop_email)
    try:
        api_module._store_booking(record)
        code = record["booking_code"]
        response = client.post(
            "/chat",
            json={
                "cliente_id": "demo",
                "mensaje": f"Hola, quiero cancelar mi cita {code}, mi email es cliente@example.com",
                "session_id": f"s_hola_cancel_{uuid.uuid4().hex[:8]}",
            },
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "booking_cancel"
        assert "cancelada" in data["respuesta"].lower()
        # Un saludo PURO sigue mostrando el menu.
        pure = client.post(
            "/chat",
            json={
                "cliente_id": "demo",
                "mensaje": "Hola, buenas tardes",
                "session_id": f"s_hola_puro_{uuid.uuid4().hex[:8]}",
            },
            headers={"Origin": "http://testserver"},
        ).json()
        assert pure["intent"] == "menu"
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_chat_reschedule_intent_with_articles_is_detected(client: TestClient, api_module):
    """Bug real de produccion: 'quiero cambiar la fecha de una cita' caia al LLM (el
    detector solo tenia literales sin articulo) y este respondia 'estamos cerrados,
    contacta en horario de atencion'. Debe entrar al flujo de gestion y pedir el codigo."""
    for msg in (
        "quiero cambiar la fecha de una cita",
        "necesito mover el dia de mi reserva",
        "me gustaria modificar la hora de la cita",
    ):
        response = client.post(
            "/chat",
            json={
                "cliente_id": "demo",
                "mensaje": msg,
                "session_id": f"s_resch_art_{uuid.uuid4().hex[:8]}",
            },
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "booking_manage", msg
        assert "numero de reserva" in data["respuesta"].lower(), msg
    # El detector no debe dispararse sin objeto de cita/fecha/hora.
    assert api_module._message_requests_reschedule_booking("quiero cambiar de peinado") is False


def test_chat_live_context_declares_assistant_24_7(api_module):
    """El bloque de datos en vivo deja claro que el ASISTENTE atiende 24/7 aunque el
    local este cerrado: nunca debe mandar al usuario a 'horario de atencion'."""
    from backend import chat as chat_mod

    config = api_module.CONFIG_CLIENTES["demo"]
    block = chat_mod._build_live_context_block("demo", config)
    assert "24/7" in block
    assert "NUNCA pidas" in block


def test_chat_manage_ambiguous_intent_asks_which(client: TestClient, api_module):
    """'Cancelar o cambiar mi cita' (quick action del menu) es ambiguo: pregunta cual de
    las dos y NO asume cancelacion."""
    session_id = f"s_manage_amb_{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/chat",
        json={
            "cliente_id": "demo",
            "mensaje": "Quiero cancelar o cambiar mi cita",
            "session_id": session_id,
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "booking_manage"
    assert "cual de las dos" in data["respuesta"].lower()


def test_cancellation_policy_question_is_not_booking_management(api_module):
    assert api_module._message_requests_cancel_booking("¿Cuáles son las condiciones de cancelación?") is False
    assert api_module._message_requests_booking_policy_info("¿Cómo puedo reservar y cuáles son las condiciones de cancelación?") is True
    assert api_module._message_requests_cancel_booking("Quiero cancelar mi cita") is True


def test_chat_reschedule_conflict_offers_alternatives(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    """Reprogramar a una hora ocupada no devuelve un error seco: ofrece huecos reales."""
    record = _build_booking_record(api_module)

    async def _fake_update(row, payload, request, *, source, audit_payload=None):
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="Esa hora ya no esta disponible.")

    async def _fake_slots(cliente_id, fecha, **_kwargs):
        return ["10:00", "10:30", "12:00"]

    monkeypatch.setattr(api_module, "_update_booking_details", _fake_update)
    monkeypatch.setattr(api_module, "_available_slots_for_day", _fake_slots)
    try:
        api_module._store_booking(record)
        code = record["booking_code"]
        response = client.post(
            "/chat",
            json={
                "cliente_id": "demo",
                "mensaje": (
                    f"Quiero cambiar la cita {code} al 2026-06-15 a las 09:30. "
                    "Mi telefono es 611222333"
                ),
                "session_id": f"s_resch_alt_{uuid.uuid4().hex[:8]}",
            },
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "booking_reschedule"
        assert "10:00" in data["respuesta"]
        assert "12:00" in data["respuesta"]
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_chat_live_context_uses_weekly_matrix(api_module, monkeypatch: pytest.MonkeyPatch):
    """El bloque DATOS_EN_VIVO (estado abierto/cerrado y horas de hoy) sale de la MISMA
    matriz semanal que el bloque HORARIO del prompt, no de config['booking'] crudo."""
    from backend import chat as chat_mod

    def _fake_matrix(cliente_id, config):
        rows = []
        for wd in range(7):
            rows.append({
                "weekday": wd,
                "closed": wd in (5, 6),
                "start": "" if wd in (5, 6) else "10:15",
                "end": "" if wd in (5, 6) else "20:45",
                "source": "employees",
            })
        return rows

    monkeypatch.setattr(api_module, "_weekly_schedule_matrix", _fake_matrix)
    config = api_module.CONFIG_CLIENTES["demo"]
    block = chat_mod._build_live_context_block("demo", config)
    import datetime as _dt

    weekday = _dt.datetime.now().weekday()  # el bloque usa la hora local del negocio
    if weekday in (5, 6):
        assert "CERRADO hoy" in block
    else:
        assert "10:15-20:45" in block
    assert "sabado" in block and "domingo" in block  # dias cerrados desde la matriz


def test_chat_system_prompt_includes_schedule_and_catalog(api_module):
    """El prompt del chat lleva el HORARIO SEMANAL REAL (misma fuente que la voz y la
    disponibilidad) y el CATALOGO REAL de servicios (tabla services), como el de voz."""
    config = api_module.CONFIG_CLIENTES["demo"]
    prompt = api_module._build_system_prompt("demo", config)
    assert "HORARIO SEMANAL REAL" in prompt
    assert "NUNCA ofrezcas cita" in prompt
    catalog_lines = api_module._service_catalog_lines("demo")
    if catalog_lines:
        assert "CATALOGO REAL DE SERVICIOS" in prompt
        assert catalog_lines[0].lstrip("- ").split(" · ")[0] in prompt


def test_chat_menu_quick_actions_include_manage(client: TestClient, api_module):
    response = client.post(
        "/chat",
        json={
            "cliente_id": "demo",
            "mensaje": "hola",
            "session_id": f"s_menu_qa_{uuid.uuid4().hex[:8]}",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    data = response.json()
    labels = [a.get("label", "") for a in (data.get("quick_actions") or [])]
    assert "Cancelar o cambiar mi cita" in labels


def test_whatsapp_cancel_booking_by_code_uses_sender_phone(api_module, monkeypatch: pytest.MonkeyPatch):
    record = _build_booking_record(api_module, telefono="34611222333")
    sent_messages = []

    async def _noop_cancel_provider(_row):
        return None

    async def _noop_email(*_args, **_kwargs):
        return True

    async def _capture_whatsapp_text(*, cliente_id, phone_number_id, to_number, text):
        sent_messages.append(text)
        return True

    monkeypatch.setattr(api_module, "_cancel_provider_booking", _noop_cancel_provider)
    monkeypatch.setattr(api_module, "_send_booking_email_by_kind", _noop_email)
    monkeypatch.setattr(api_module, "_send_whatsapp_text", _capture_whatsapp_text)
    try:
        api_module._store_booking(record)
        code = record["booking_code"]

        asyncio.run(
            api_module._handle_whatsapp_message(
                cliente_id="demo",
                phone_number_id="1234567890",
                from_number="34611222333",
                incoming_text=f"Cancelar cita {code}",
                interactive_id="",
                request=None,
            )
        )

        assert any("cancelada" in message.lower() for message in sent_messages)
        with api_module._get_db_connection() as conn:
            status_value = conn.execute(
                "SELECT status FROM bookings WHERE id = ?", (record["id"],)
            ).fetchone()[0]
        assert status_value == "cancelled"
    finally:
        api_module._wa_clear_flow("demo", "34611222333")
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_whatsapp_reschedule_success_speaks_human_date(api_module, monkeypatch: pytest.MonkeyPatch):
    """La confirmacion de cambio por WhatsApp dice la fecha en humano, no ISO crudo."""
    record = _build_booking_record(api_module, telefono="34611222333")
    sent_messages = []

    async def _fake_update(row, payload, request, *, source, audit_payload=None):
        return api_module.BookingActionResponse(
            ok=True, booking_id=row["id"], estado="confirmed", mensaje="ok",
            employee_id=row["employee_id"] or "", employee_name=row["employee_name"] or "",
            manage_url="", provider_booking_url="",
        )

    async def _capture_whatsapp_text(*, cliente_id, phone_number_id, to_number, text):
        sent_messages.append(text)
        return True

    monkeypatch.setattr(api_module, "_update_booking_details", _fake_update)
    monkeypatch.setattr(api_module, "_send_whatsapp_text", _capture_whatsapp_text)
    try:
        api_module._store_booking(record)
        code = record["booking_code"]
        asyncio.run(
            api_module._handle_whatsapp_message(
                cliente_id="demo",
                phone_number_id="1234567890",
                from_number="34611222333",
                incoming_text=f"Quiero cambiar la cita {code} al 2026-06-15 a las 09:30",
                interactive_id="",
                request=None,
            )
        )
        joined = " ".join(sent_messages)
        assert "15 de junio" in joined
        assert "2026-06-15" not in joined
    finally:
        api_module._wa_clear_flow("demo", "34611222333")
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_whatsapp_reschedule_conflict_offers_alternatives(api_module, monkeypatch: pytest.MonkeyPatch):
    """Cambiar a una hora ocupada por WhatsApp ofrece huecos reales (texto compartido
    booking._reschedule_failure_text), no un error seco."""
    record = _build_booking_record(api_module, telefono="34611222333")
    sent_messages = []

    async def _fake_update(row, payload, request, *, source, audit_payload=None):
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="Esa hora ya no esta disponible.")

    async def _fake_slots(cliente_id, fecha, **_kwargs):
        return ["10:00", "10:30", "12:00"]

    async def _capture_whatsapp_text(*, cliente_id, phone_number_id, to_number, text):
        sent_messages.append(text)
        return True

    monkeypatch.setattr(api_module, "_update_booking_details", _fake_update)
    monkeypatch.setattr(api_module, "_available_slots_for_day", _fake_slots)
    monkeypatch.setattr(api_module, "_send_whatsapp_text", _capture_whatsapp_text)
    try:
        api_module._store_booking(record)
        code = record["booking_code"]
        asyncio.run(
            api_module._handle_whatsapp_message(
                cliente_id="demo",
                phone_number_id="1234567890",
                from_number="34611222333",
                incoming_text=f"Quiero cambiar la cita {code} al 2026-06-15 a las 09:30",
                interactive_id="",
                request=None,
            )
        )
        joined = " ".join(sent_messages)
        assert "10:00" in joined and "12:00" in joined
    finally:
        api_module._wa_clear_flow("demo", "34611222333")
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_whatsapp_ai_booking_intent_starts_with_service_picker(api_module, monkeypatch: pytest.MonkeyPatch):
    """Cuando la IA detecta intencion de reserva en texto libre, WhatsApp arranca el MISMO
    flujo que el menu (selector de SERVICIO), no salta al dia sin servicio."""
    sent_messages = []
    picker_calls = []

    async def _capture_whatsapp_text(*, cliente_id, phone_number_id, to_number, text):
        sent_messages.append(text)
        return True

    async def _capture_service_picker(*, cliente_id, phone_number_id, to_number, location_id=""):
        picker_calls.append(to_number)
        return True

    def _fake_services(cliente_id, location_id=""):
        return [{"nombre": "Masaje", "duration_minutes": 30, "price_cents": 1000}]

    monkeypatch.setattr(api_module, "_send_whatsapp_text", _capture_whatsapp_text)
    monkeypatch.setattr(api_module, "_wa_send_service_picker", _capture_service_picker)
    monkeypatch.setattr(api_module, "_public_services_for_booking", _fake_services)
    try:
        asyncio.run(
            api_module._handle_whatsapp_message(
                cliente_id="demo",
                phone_number_id="1234567890",
                from_number="34699887766",
                incoming_text="Hola, me gustaria pedir cita para un masaje",
                interactive_id="",
                request=None,
            )
        )
        assert picker_calls, "no abrio el selector de servicio"
        flow = api_module._wa_get_flow("demo", "34699887766")
        assert flow.flow == "booking_service"
    finally:
        api_module._wa_clear_flow("demo", "34699887766")


def test_whatsapp_closed_weekdays_come_from_weekly_matrix(api_module, monkeypatch: pytest.MonkeyPatch):
    """Los pickers de WhatsApp excluyen dias segun la matriz semanal real (empleados),
    no el config['booking'] crudo: un domingo reabierto solo por horarios de empleados
    debe aparecer, y un dia cerrado por empleados debe ocultarse."""
    from backend import whatsapp as wa_mod

    def _fake_matrix(cliente_id, config):
        return [
            {"weekday": wd, "closed": wd in (2, 6), "start": "09:00", "end": "17:00", "source": "employees"}
            for wd in range(7)
        ]

    monkeypatch.setattr(api_module, "_weekly_schedule_matrix", _fake_matrix)
    config = api_module.CONFIG_CLIENTES["demo"]
    closed = wa_mod._wa_closed_weekdays("demo", config)
    assert closed == {2, 6}
    # Fallback a config si la matriz no esta disponible.
    monkeypatch.setattr(api_module, "_weekly_schedule_matrix", lambda *_a, **_k: [])
    config_closed = set(int(x) for x in (config.get("booking", {}).get("closed_weekdays") or []))
    assert wa_mod._wa_closed_weekdays("demo", config) == config_closed


def test_whatsapp_multicenter_generic_number_asks_location_first(api_module, monkeypatch: pytest.MonkeyPatch):
    """Numero de WhatsApp generico + negocio multi-centro: el flujo de reserva pide el
    CENTRO antes del servicio, y el centro elegido acota el resto del flujo."""
    lists_sent = []
    picker_calls = []
    locs = [
        {"id": "loc_a", "name": "Sede Centro", "address": "Calle Mayor 1"},
        {"id": "loc_b", "name": "Sede Norte", "address": "Avenida del Parque 22"},
    ]

    async def _capture_list(*, cliente_id, phone_number_id, to_number, body, button_text, sections, header=""):
        lists_sent.append({"body": body, "sections": sections})
        return True

    async def _capture_service_picker(*, cliente_id, phone_number_id, to_number, location_id=""):
        picker_calls.append(location_id)
        return True

    async def _noop_text(*, cliente_id, phone_number_id, to_number, text):
        return True

    def _fake_locations(cliente_id, include_inactive=True):
        return locs

    def _fake_get_location(location_id, *, cliente_id=""):
        return next((l for l in locs if l["id"] == location_id), None)

    monkeypatch.setattr(api_module, "_send_whatsapp_list", _capture_list)
    monkeypatch.setattr(api_module, "_send_whatsapp_text", _noop_text)
    monkeypatch.setattr(api_module, "_wa_send_service_picker", _capture_service_picker)
    monkeypatch.setattr(api_module, "_list_location_rows", _fake_locations)
    monkeypatch.setattr(api_module, "_get_location_row", _fake_get_location)
    monkeypatch.setattr(
        api_module, "_public_services_for_booking",
        lambda cliente_id, location_id="": [{"nombre": "Masaje"}],
    )
    try:
        asyncio.run(
            api_module._handle_whatsapp_message(
                cliente_id="demo",
                phone_number_id="",
                from_number="34677001122",
                incoming_text="agendar",
                interactive_id="",
                request=None,
            )
        )
        flow = api_module._wa_get_flow("demo", "34677001122")
        assert flow.flow == "booking_location"
        assert lists_sent and "centro" in lists_sent[-1]["body"].lower()
        # Elige Sede Norte -> se guarda el centro y sigue al selector de servicio.
        asyncio.run(
            api_module._handle_whatsapp_message(
                cliente_id="demo",
                phone_number_id="",
                from_number="34677001122",
                incoming_text="",
                interactive_id="loc_loc_b",
                request=None,
            )
        )
        flow = api_module._wa_get_flow("demo", "34677001122")
        assert flow.location_id == "loc_b"
        assert flow.flow == "booking_service"
        assert picker_calls and picker_calls[-1] == "loc_b"
    finally:
        api_module._wa_clear_flow("demo", "34677001122")


def test_orphan_tenant_account_cannot_login_or_use_session(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    """Cuenta ligada a un tenant que ya no existe (cliente borrado / demo expirada): ni el
    login ni una sesion previa valen. Caso real: usuario de demo expirada seguia entrando."""
    user = api_module._create_user(
        email="huerfano@example.com", password="pass12345", role="client",
        display_name="Huerfano", cliente_id="tenant_que_no_existe", portal_role="owner",
    )
    raw_session = api_module._create_auth_session(user["id"])
    try:
        # Sesion previa: rechazada.
        me = client.get("/auth/me", cookies={"vantelia_portal_session": raw_session})
        assert me.status_code == 401
        # Login: rechazado con mensaje claro.
        r = client.post(
            "/auth/login",
            json={"email": "huerfano@example.com", "password": "pass12345"},
        )
        assert r.status_code == 403
        assert "no esta activo" in r.json()["detail"]
    finally:
        api_module._delete_user(user["id"])


def test_delete_client_purges_catalog_commerce_and_users(client: TestClient, api_module):
    """Borrar un cliente elimina TODO: usuarios (no pueden volver a entrar), catalogo,
    centros, comercio y voz. Nada queda huerfano."""
    cliente_id = "cliente_purga_total"
    next_configs = dict(api_module.CONFIG_CLIENTES)
    next_configs[cliente_id] = json.loads(json.dumps(api_module.CONFIG_CLIENTES["demo"]))
    next_configs[cliente_id]["nombre"] = "Purga Total"
    api_module._persist_configs_to_disk(next_configs)
    api_module._update_runtime_configs(next_configs)
    data_dir = Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "info.txt").write_text("Temporal.", encoding="utf-8")
    api_module._create_user(
        email="purga.total@example.com", password="pass12345", role="client",
        display_name="Purga", cliente_id=cliente_id, portal_role="owner",
    )
    with api_module._get_db_connection() as conn:
        conn.execute(
            "INSERT INTO products (id, cliente_id, name, price_cents, is_active, created_at, updated_at)"
            " VALUES ('prod_purga', ?, 'Crema', 1000, 1, datetime('now'), datetime('now'))",
            (cliente_id,),
        )
        conn.execute(
            "INSERT INTO voice_calls (call_sid, cliente_id, from_number, to_number, started_at, status)"
            " VALUES ('CA_purga', ?, '', '', datetime('now'), 'completed')",
            (cliente_id,),
        )
        conn.execute(
            "INSERT INTO services (cliente_id, slug, name, duration_minutes, price_cents, is_active, created_at, updated_at)"
            " VALUES (?, 'svc-purga', 'Masaje Purga', 30, 1000, 1, datetime('now'), datetime('now'))",
            (cliente_id,),
        )
        conn.commit()

    api_module._delete_client_everywhere(cliente_id)

    with api_module._get_db_connection() as conn:
        for table, col, val in (
            ("users", "email", "purga.total@example.com"),
            ("services", "cliente_id", cliente_id),
            ("locations", "cliente_id", cliente_id),
            ("products", "cliente_id", cliente_id),
            ("voice_calls", "cliente_id", cliente_id),
        ):
            count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (val,)).fetchone()[0]
            assert count == 0, f"{table} no quedo limpio"
    # Login imposible (usuario borrado con el cliente).
    r = client.post("/auth/login", json={"email": "purga.total@example.com", "password": "pass12345"})
    assert r.status_code == 404



def _gift_enable_demo(api_module, monkeypatch, *, stripe_ok=True):
    monkeypatch.setitem(
        api_module.CONFIG_CLIENTES["demo"], "gift_cards_public",
        {"enabled": True, "suggested_amounts": [3000, 5000], "min_cents": 1000, "max_cents": 20000, "validity_days": 365},
    )
    account = SimpleNamespace(connected=stripe_ok, charges_enabled=stripe_ok, stripe_account_id="acct_gift_test")
    monkeypatch.setattr(api_module, "_connect_account_status", lambda cliente_id, refresh=False: account)


def test_gift_public_page_gating_and_render(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    """OFF por defecto -> 404. Activa sin Stripe -> 404. Activa con Stripe -> pagina con
    branding, chips e importes."""
    assert client.get("/gift/demo").status_code == 404
    assert client.post(
        "/gift/demo/checkout",
        json={"amount_cents": 3000, "buyer_name": "Ana", "buyer_email": "a@a.com",
              "recipient_name": "Luis", "recipient_email": "l@l.com"},
    ).status_code == 404

    _gift_enable_demo(api_module, monkeypatch, stripe_ok=False)
    assert client.get("/gift/demo").status_code == 404

    _gift_enable_demo(api_module, monkeypatch, stripe_ok=True)
    page = client.get("/gift/demo")
    assert page.status_code == 200
    assert "Tarjeta regalo" in page.text
    assert "chip" in page.text and "30" in page.text
    assert "/checkout" in page.text


def test_gift_public_checkout_creates_pending_payment(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    _gift_enable_demo(api_module, monkeypatch)
    created_sessions = []

    def fake_create(**kwargs):
        created_sessions.append(kwargs)
        return SimpleNamespace(id="cs_gift_test", url="https://checkout.stripe.test/gift")

    monkeypatch.setattr(api_module, "_stripe_init", lambda: None)
    monkeypatch.setattr(api_module.stripe.checkout.Session, "create", fake_create)
    payment_id = ""
    try:
        r = client.post(
            "/gift/demo/checkout",
            json={
                "amount_cents": 5000,
                "buyer_name": "Ana Compradora",
                "buyer_email": "ana@example.com",
                "recipient_name": "Luis Regalado",
                "recipient_email": "luis@example.com",
                "message": "Felicidades!",
                "scheduled_send_at": "",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        payment_id = data["payment_id"]
        assert data["url"] == "https://checkout.stripe.test/gift"
        assert created_sessions[0]["stripe_account"] == "acct_gift_test"
        assert created_sessions[0]["metadata"]["kind"] == "gift_card"
        assert "session_id={CHECKOUT_SESSION_ID}" in created_sessions[0]["success_url"]
        with api_module._get_db_connection() as conn:
            row = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
        assert row["kind"] == "gift_card" and row["status"] == "pending"
        meta = json.loads(row["line_items_json"])
        assert meta["recipient_email"] == "luis@example.com"
        assert meta["message"] == "Felicidades!"
        pending = client.get("/gift/demo/checkout-status?session_id=cs_gift_test")
        assert pending.status_code == 200
        assert pending.json()["status"] == "pending" and pending.json()["ready"] is False
        with api_module._get_db_connection() as conn:
            conn.execute("UPDATE customer_payments SET status='paid' WHERE id=?", (payment_id,))
            row = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            api_module._finalize_gift_card_payment(conn, row, api_module._utc_now_iso())
            conn.commit()
        ready = client.get("/gift/demo/checkout-status?session_id=cs_gift_test")
        assert ready.status_code == 200
        ready_body = ready.json()
        assert ready_body["status"] == "paid" and ready_body["ready"] is True
        assert ready_body["code"].startswith("GC-")
        assert "/gift/demo/saldo?code=" in ready_body["balance_url"]
        # Importe fuera de rango -> 400.
        bad = client.post(
            "/gift/demo/checkout",
            json={"amount_cents": 100, "buyer_name": "Ana", "buyer_email": "a@a.com",
                  "recipient_name": "Luis", "recipient_email": "l@l.com"},
        )
        assert bad.status_code == 400
    finally:
        if payment_id:
            with api_module._get_db_connection() as conn:
                for card in conn.execute("SELECT id FROM gift_cards WHERE customer_payment_id=?", (payment_id,)).fetchall():
                    conn.execute("DELETE FROM gift_card_transactions WHERE gift_card_id=?", (card["id"],))
                conn.execute("DELETE FROM gift_cards WHERE customer_payment_id=?", (payment_id,))
                conn.execute("DELETE FROM customer_payments WHERE id=?", (payment_id,))
                conn.commit()


def test_finalize_gift_card_payment_is_idempotent_and_sends_email(api_module, monkeypatch: pytest.MonkeyPatch):
    """El webhook emite la tarjeta UNA sola vez, con saldo=importe y metadatos del
    comprador; el email al destinatario sella sent_at y no se reenvia."""
    payment_id = "pay_gift_" + uuid.uuid4().hex[:8]
    now = api_module._utc_now_iso()
    meta = {
        "buyer_name": "Ana", "buyer_email": "ana@example.com",
        "recipient_name": "Luis", "recipient_email": "luis@example.com",
        "message": "Disfrutalo", "scheduled_send_at": "", "validity_days": 30,
    }
    emails = []
    monkeypatch.setattr(
        api_module, "_send_client_email",
        lambda cliente_id, to, subject, text, html="", reply_to=None: emails.append((to, subject)) or "smtp",
    )
    card_id = ""
    try:
        with api_module._get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO customer_payments
                    (id, cliente_id, contact_id, booking_id, service_id, service_name, stripe_account_id,
                     stripe_checkout_session_id, amount_cents, currency, status, checkout_url,
                     kind, line_items_json, created_at, updated_at)
                VALUES (?, 'demo', '', '', '', 'Ana', 'acct_x', 'cs_x', 5000, 'eur', 'paid', '',
                        'gift_card', ?, ?, ?)
                """,
                (payment_id, json.dumps(meta), now, now),
            )
            payment = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            api_module._finalize_gift_card_payment(conn, payment, now)
            api_module._finalize_gift_card_payment(conn, payment, now)  # idempotente
            conn.commit()
            cards = conn.execute(
                "SELECT * FROM gift_cards WHERE customer_payment_id=?", (payment_id,)
            ).fetchall()
        assert len(cards) == 1
        card = cards[0]
        card_id = card["id"]
        assert card["balance_cents"] == 5000 and card["initial_cents"] == 5000
        assert card["recipient_email"] == "luis@example.com"
        assert card["message"] == "Disfrutalo"
        assert card["expires_at"]  # validity 30 dias
        assert card["code"].startswith("GC-")
        # Envio: una vez, sella sent_at; la segunda pasada no reenvia.
        sent = api_module._send_pending_gift_card_emails()
        assert sent == 1 and emails and emails[0][0] == "luis@example.com"
        assert api_module._send_pending_gift_card_emails() == 0
        with api_module._get_db_connection() as conn:
            sent_at = conn.execute("SELECT sent_at FROM gift_cards WHERE id=?", (card_id,)).fetchone()[0]
        assert sent_at
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM customer_payments WHERE id=?", (payment_id,))
            if card_id:
                conn.execute("DELETE FROM gift_cards WHERE id=?", (card_id,))
                conn.execute("DELETE FROM gift_card_transactions WHERE gift_card_id=?", (card_id,))
            conn.commit()


def test_scheduled_gift_card_waits_for_date(api_module, monkeypatch: pytest.MonkeyPatch):
    emails = []
    monkeypatch.setattr(
        api_module, "_send_client_email",
        lambda cliente_id, to, subject, text, html="", reply_to=None: emails.append(to) or "smtp",
    )
    future = (api_module._utc_now() + api_module.timedelta(days=10)).date().isoformat()
    now = api_module._utc_now_iso()
    card_id = "gc_test_" + uuid.uuid4().hex[:6]
    try:
        with api_module._get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO gift_cards (id, cliente_id, code, initial_cents, balance_cents, currency,
                                        status, buyer_name, buyer_email, recipient_name, recipient_email,
                                        notes, expires_at, location_id, created_at, updated_at,
                                        message, scheduled_send_at, sent_at, customer_payment_id)
                VALUES (?, 'demo', ?, 3000, 3000, 'eur', 'active', 'Ana', 'a@a.com', 'Luis', 'l@l.com',
                        '', '', '', ?, ?, '', ?, '', 'pay_sched_x')
                """,
                (card_id, "GC-TEST-SCHD", now, now, future),
            )
            conn.commit()
        assert api_module._send_pending_gift_card_emails() == 0  # aun no toca
        assert not emails
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM gift_cards WHERE id=?", (card_id,))
            conn.commit()


def test_chat_offers_gift_card_link_when_available(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    """Con la venta online activa, el chat responde con el ENLACE (determinista) y el menu
    muestra la quick action; sin activarla, ni rastro."""
    session_id = f"s_gift_{uuid.uuid4().hex[:8]}"
    # Desactivada: el mensaje cae al flujo normal (sin intent gift_card).
    off = client.post(
        "/chat",
        json={"cliente_id": "demo", "mensaje": "Quiero comprar una tarjeta regalo", "session_id": session_id},
        headers={"Origin": "http://testserver"},
    ).json()
    assert off.get("intent") != "gift_card"

    monkeypatch.setattr(api_module, "gift_public_available", lambda cliente_id: True)
    on = client.post(
        "/chat",
        json={"cliente_id": "demo", "mensaje": "Quiero comprar una tarjeta regalo", "session_id": session_id + "b"},
        headers={"Origin": "http://testserver"},
    ).json()
    assert on["intent"] == "gift_card"
    assert "/gift/demo" in on["respuesta"]

    menu = client.post(
        "/chat",
        json={"cliente_id": "demo", "mensaje": "hola", "session_id": session_id + "c"},
        headers={"Origin": "http://testserver"},
    ).json()
    labels = [a.get("label", "") for a in (menu.get("quick_actions") or [])]
    assert any("Tarjeta regalo" in l for l in labels)


def test_gift_card_info_questions_do_not_use_purchase_shortcut(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    """Las preguntas sobre condiciones deben llegar al RAG/conocimiento, no al enlace generico."""
    session_id = f"s_gift_info_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(api_module, "gift_public_available", lambda cliente_id: True)
    monkeypatch.setattr(api_module, "_get_or_create_session", lambda session_id, cliente_id: SimpleNamespace(
        last_seen=0,
        message_count=0,
        engine=SimpleNamespace(chat=lambda message: SimpleNamespace(response="No caducan y se pueden transferir.")),
    ))
    resp = client.post(
        "/chat",
        json={
            "cliente_id": "demo",
            "mensaje": "Que incluye la tarjeta regalo y caduca?",
            "session_id": session_id,
        },
        headers={"Origin": "http://testserver"},
    ).json()
    assert resp.get("intent") != "gift_card"
    assert "No caducan" in resp["respuesta"]
    assert "/gift/demo" not in resp["respuesta"]


def test_gift_public_assistant_knowledge_is_configurable_and_in_prompt(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    _gift_enable_demo(api_module, monkeypatch, stripe_ok=False)
    cookies = _portal_admin_cookies(api_module)
    payload = {
        "enabled": True,
        "assistant_knowledge": "No caducan. Se pueden transferir a familiares o amigos.",
    }
    response = client.put(
        "/auth/app/gift-cards-public",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json=payload,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "No caducan" in data["assistant_knowledge"]

    block = api_module.gift_public_prompt_block("demo")
    assert "No caducan" in block
    prompt = api_module._build_system_prompt("demo", api_module.CONFIG_CLIENTES["demo"])
    assert "TARJETAS REGALO" in prompt
    assert "familiares o amigos" in prompt


def _provision_seed_client(api_module, cliente_id: str, info_txt: str) -> None:
    cfg = api_module._normalize_client_config(cliente_id, {
        "nombre": f"Seed {cliente_id}",
        "icono": "S",
        "color": "#00b1d9",
        "bienvenida": "Hola",
        "allowed_origins": ["http://testserver"],
        "contacto": {"email": "seed@example.com", "telefono": "+34600000000"},
        "plan": "business",
        "subscription": {"plan": "business", "status": "active"},
        "booking": {"enabled": True, "timezone": "Europe/Madrid", "provider": "internal"},
    })
    next_configs = json.loads(json.dumps(api_module.CONFIG_CLIENTES))
    next_configs[cliente_id] = cfg
    api_module._update_runtime_configs(next_configs)
    api_module._persist_configs_to_disk(next_configs)
    cdir = Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "info.txt").write_text(info_txt, encoding="utf-8")


def test_scraped_commerce_seed_creates_only_real_catalog_items(api_module):
    cliente_id = f"seed_com_{uuid.uuid4().hex[:8]}"
    info = "\n".join([
        "===== INFO SEED =====",
        "SERVICIOS Y PRECIOS:",
        "- Servicio: Masaje relajante",
        "  - Precio: 50 EUR",
        "  - Duracion: 60 min",
        "",
        "TARJETAS REGALO, BONOS Y PRODUCTOS:",
        "- Productos:",
        "  - Producto: Aceite de masaje - 15 EUR - Stock: 10",
        "- Bonos:",
        "  - Bono 5 sesiones Masaje relajante - 220 EUR - 5 sesiones",
        "- Tarjetas regalo: no caducan, se pueden transferir y valen en cualquier centro.",
        "- Condiciones de compra, reserva, uso, caducidad, transferencia, cambios, descuentos y cancelacion: sin descuentos promocionales.",
    ])
    _provision_seed_client(api_module, cliente_id, info)

    result = api_module._seed_commerce_from_info(cliente_id, info)

    assert result["products_created"] == 1
    assert result["packages_created"] == 1
    assert result["gift_knowledge"] == 1
    products = api_module._list_products(cliente_id)
    packages = api_module._list_packages(cliente_id)
    assert products[0]["name"] == "Aceite de masaje"
    assert products[0]["price_cents"] == 1500
    assert packages[0]["price_cents"] == 22000
    assert packages[0]["items"][0]["qty"] == 5
    cfg = api_module.CONFIG_CLIENTES[cliente_id]
    assert cfg["gift_cards_public"]["enabled"] is True
    assert cfg["gift_cards_public"]["validity_days"] == 0
    assert "se pueden transferir" in cfg["gift_cards_public"]["assistant_knowledge"]
    prompt = api_module._build_system_prompt(cliente_id, api_module._get_client_config(cliente_id))
    assert "CATALOGO REAL DE COMERCIO" in prompt
    assert "Aceite de masaje" in prompt
    assert "Bono 5 sesiones" in prompt


def test_scraped_commerce_seed_ignores_missing_or_placeholder_content(api_module):
    cliente_id = f"seed_empty_{uuid.uuid4().hex[:8]}"
    info = "\n".join([
        "===== INFO EMPTY =====",
        "SERVICIOS Y PRECIOS:",
        "- Servicio: Consulta",
        "  - Precio: 30 EUR",
        "",
        "TARJETAS REGALO, BONOS Y PRODUCTOS:",
        "- Tarjetas regalo: No especificado en la web",
        "- Bonos: No especificado en la web",
        "- Productos: No especificado en la web",
    ])
    _provision_seed_client(api_module, cliente_id, info)

    result = api_module._seed_commerce_from_info(cliente_id, info)

    assert result == {"products_created": 0, "packages_created": 0, "gift_knowledge": 0, "config_updated": 0}
    assert api_module._list_products(cliente_id) == []
    assert api_module._list_packages(cliente_id) == []
    assert not (api_module.CONFIG_CLIENTES[cliente_id].get("gift_cards_public") or {}).get("assistant_knowledge")


def test_gift_service_purchase_uses_server_price(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    """Tarjeta POR SERVICIO: el precio lo pone el catalogo del servidor (el importe del
    cliente se ignora) y el nombre del servicio viaja en la metadata y el checkout."""
    _gift_enable_demo(api_module, monkeypatch)
    monkeypatch.setattr(
        api_module, "_public_services_for_booking",
        lambda cliente_id, employee_id="", location_id="": [
            {"id": "masaje-60", "nombre": "Masaje 60 min", "price_cents": 6500},
            {"id": "sin-precio", "nombre": "A consultar", "price_cents": 0},
        ],
    )
    created_sessions = []

    def fake_create(**kwargs):
        created_sessions.append(kwargs)
        return SimpleNamespace(id="cs_gift_svc", url="https://checkout.stripe.test/gift-svc")

    monkeypatch.setattr(api_module, "_stripe_init", lambda: None)
    monkeypatch.setattr(api_module.stripe.checkout.Session, "create", fake_create)
    payment_id = ""
    try:
        r = client.post(
            "/gift/demo/checkout",
            json={
                "amount_cents": 0,
                "service_slug": "masaje-60",
                "buyer_name": "Ana", "buyer_email": "ana@example.com",
                "recipient_name": "Luis", "recipient_email": "luis@example.com",
                "accent_color": "#0E7490",
                "hide_value": True,
            },
        )
        assert r.status_code == 200, r.text
        payment_id = r.json()["payment_id"]
        assert r.json()["amount_cents"] == 6500  # precio del servidor
        assert "Masaje 60 min" in created_sessions[0]["line_items"][0]["price_data"]["product_data"]["name"]
        with api_module._get_db_connection() as conn:
            row = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
        meta = json.loads(row["line_items_json"])
        assert meta["service_name"] == "Masaje 60 min"
        assert meta["accent_color"] == "#0E7490"
        assert meta["hide_value"] is True
        # Servicio sin precio fijo -> 400.
        bad = client.post(
            "/gift/demo/checkout",
            json={"amount_cents": 0, "service_slug": "sin-precio",
                  "buyer_name": "Ana", "buyer_email": "a@a.com",
                  "recipient_name": "Luis", "recipient_email": "l@l.com"},
        )
        assert bad.status_code == 400
    finally:
        if payment_id:
            with api_module._get_db_connection() as conn:
                conn.execute("DELETE FROM customer_payments WHERE id=?", (payment_id,))
                conn.commit()


def test_gift_email_respects_customization_and_sends_buyer_copy(api_module, monkeypatch: pytest.MonkeyPatch):
    """hide_value oculta el importe (muestra el servicio o 'Una experiencia'), hide_expiry
    quita la caducidad, el color de acento tinye el email, y el comprador recibe copia
    imprimible. Color invalido -> se descarta."""
    payment_id = "pay_gift_f2_" + uuid.uuid4().hex[:8]
    now = api_module._utc_now_iso()
    meta = {
        "buyer_name": "Ana", "buyer_email": "ana@example.com",
        "recipient_name": "Luis", "recipient_email": "luis@example.com",
        "message": "", "scheduled_send_at": "", "validity_days": 30,
        "accent_color": "#0E7490", "hide_value": True, "hide_expiry": True,
        "service_name": "Masaje 60 min",
    }
    emails = []
    monkeypatch.setattr(
        api_module, "_send_client_email",
        lambda cliente_id, to, subject, text, html="", reply_to=None: emails.append(
            {"to": to, "subject": subject, "text": text, "html": html}
        ) or "smtp",
    )
    card_id = ""
    try:
        with api_module._get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO customer_payments
                    (id, cliente_id, contact_id, booking_id, service_id, service_name, stripe_account_id,
                     stripe_checkout_session_id, amount_cents, currency, status, checkout_url,
                     kind, line_items_json, created_at, updated_at)
                VALUES (?, 'demo', '', '', '', 'Ana', 'acct_x', 'cs_f2', 6500, 'eur', 'paid', '',
                        'gift_card', ?, ?, ?)
                """,
                (payment_id, json.dumps(meta), now, now),
            )
            payment = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            api_module._finalize_gift_card_payment(conn, payment, now)
            conn.commit()
            card = conn.execute("SELECT * FROM gift_cards WHERE customer_payment_id=?", (payment_id,)).fetchone()
        card_id = card["id"]
        assert card["accent_color"] == "#0E7490"
        assert card["hide_value"] == 1 and card["hide_expiry"] == 1
        assert card["service_name"] == "Masaje 60 min"

        sent = api_module._send_pending_gift_card_emails()
        assert sent == 1
        assert len(emails) == 2  # destinatario + copia al comprador
        dest = emails[0]
        assert dest["to"] == "luis@example.com"
        assert "Masaje 60 min" in dest["html"]           # headline = servicio
        assert "65,00" not in dest["html"]               # importe oculto
        assert "Caduca" not in dest["html"]              # caducidad oculta
        assert "#0E7490" in dest["html"]                 # acento aplicado
        copia = emails[1]
        assert copia["to"] == "ana@example.com"
        assert "imprimir" in copia["html"].lower()
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM customer_payments WHERE id=?", (payment_id,))
            if card_id:
                conn.execute("DELETE FROM gift_cards WHERE id=?", (card_id,))
                conn.execute("DELETE FROM gift_card_transactions WHERE gift_card_id=?", (card_id,))
            conn.commit()
    assert api_module._gift_accent_or_empty("rojo") == ""
    assert api_module._gift_accent_or_empty("#12ab") == ""


def test_gift_page_shows_service_tab_and_palette(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    _gift_enable_demo(api_module, monkeypatch)
    monkeypatch.setattr(
        api_module, "_public_services_for_booking",
        lambda cliente_id, employee_id="", location_id="": [
            {"id": "masaje-60", "nombre": "Masaje 60 min", "price_cents": 6500},
        ],
    )
    page = client.get("/gift/demo")
    assert page.status_code == 200
    assert "Un servicio" in page.text
    assert "Masaje 60 min" in page.text
    assert "swatches" in page.text
    assert "hide_value" in page.text


def test_config_extra_sections_survive_load_and_persist(api_module):
    """Las secciones extra del config (empresa, reminders, reviews, gift_cards_public)
    sobreviven a la normalizacion de carga Y a la serializacion de guardado. Bug real:
    la whitelist las descartaba en cada arranque y el Seguimiento/identidad/tarjetas
    volvian a defaults en runtime aunque el JSON las tuviera."""
    raw = {
        "nombre": "X", "icono": "X", "color": "#ffffff", "bienvenida": "hola",
        "booking": {"enabled": True},
        "empresa": "Negocio Real",
        "reviews": {"enabled": True, "link": "https://g.example"},
        "reminders": {"call_enabled": True, "daily_call_cap": 10},
        "gift_cards_public": {"enabled": True, "min_cents": 2000, "assistant_knowledge": "No caducan."},
    }
    normalized = api_module._normalize_client_config("demo", raw)
    for key in ("empresa", "reviews", "reminders", "gift_cards_public"):
        assert key in normalized, key
    assert normalized["gift_cards_public"]["enabled"] is True
    assert normalized["gift_cards_public"]["assistant_knowledge"] == "No caducan."
    serialized = api_module._serialize_client_config(normalized)
    for key in ("empresa", "reviews", "reminders", "gift_cards_public"):
        assert key in serialized, key
    assert serialized["reviews"]["link"] == "https://g.example"


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


def test_chat_disponibilidad_proximo_lunes_uses_real_slots(client: TestClient):
    response = client.post(
        "/chat",
        json={
            "cliente_id": "demo",
            "mensaje": "Tienes cita para el proximo lunes?",
            "session_id": "s_test_chat_availability_monday",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    payload = response.json()
    text = payload["respuesta"]
    assert payload["mostrar_formulario"] is False
    assert "09:00" in text
    assert "09:30" in text
    assert "17:00" not in text
    assert "\\n" not in text
    assert "lunes" in text.lower()


def test_chat_disponibilidad_manana_tarde_filters_period(client: TestClient):
    # "proximo lunes" es siempre laborable (demo solo cierra domingos), asi el test
    # no depende del dia real de ejecucion: si "manana" cae en domingo el bot
    # responde "cerrados" en lugar de filtrar por periodo.
    response = client.post(
        "/chat",
        json={
            "cliente_id": "demo",
            "mensaje": "Hay hueco el proximo lunes por la tarde?",
            "session_id": "s_test_chat_availability_tomorrow_afternoon",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    text = response.json()["respuesta"]
    assert "tarde" in text.lower()
    assert "no veo huecos" in text.lower() or "no hay huecos" in text.lower()
    assert "17:00" not in text
    assert "\\n" not in text


def test_chat_disponibilidad_dia_cerrado_reports_closed(client: TestClient):
    response = client.post(
        "/chat",
        json={
            "cliente_id": "demo",
            "mensaje": "Estais abiertos este domingo?",
            "session_id": "s_test_chat_availability_closed_day",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    text = response.json()["respuesta"].lower()
    assert "domingo" in text
    assert "cerrados" in text or "no laborable" in text
    assert "\\n" not in response.json()["respuesta"]


def test_chat_disponibilidad_dia_sin_slots_suggests_next_day(client: TestClient, api_module):
    target = api_module._resolve_relative_date_es("proximo lunes", "Europe/Madrid")
    assert target is not None
    block_id = f"blk_test_{uuid.uuid4().hex}"
    with sqlite3.connect(api_module.DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO agenda_blocks (id, cliente_id, employee_id, block_date, start_time, end_time, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (block_id, "demo", "", target.isoformat(), "09:00", "10:00", "Cierre tecnico", api_module._utc_now_iso()),
        )
        connection.commit()
    try:
        response = client.post(
            "/chat",
            json={
                "cliente_id": "demo",
                "mensaje": "Tienes cita para el proximo lunes?",
                "session_id": "s_test_chat_availability_full_day",
            },
            headers={"Origin": "http://testserver"},
        )
    finally:
        with sqlite3.connect(api_module.DB_PATH) as connection:
            connection.execute("DELETE FROM agenda_blocks WHERE id = ?", (block_id,))
            connection.commit()

    assert response.status_code == 200
    text = response.json()["respuesta"]
    assert "no queda disponibilidad" in text.lower() or "agenda completa" in text.lower()
    assert "siguiente dia" in text.lower()
    assert "17:00" not in text
    assert "\\n" not in text


def test_chat_disponibilidad_booking_disabled_does_not_invent_slots(client: TestClient, api_module):
    booking_cfg = api_module.CONFIG_CLIENTES["demo"]["booking"]
    previous_enabled = booking_cfg["enabled"]
    booking_cfg["enabled"] = False
    try:
        response = client.post(
            "/chat",
            json={
                "cliente_id": "demo",
                "mensaje": "Tienes cita para manana?",
                "session_id": "s_test_chat_availability_booking_disabled",
            },
            headers={"Origin": "http://testserver"},
        )
    finally:
        booking_cfg["enabled"] = previous_enabled

    assert response.status_code == 200
    text = response.json()["respuesta"].lower()
    assert "no puedo consultar la agenda en tiempo real" in text
    assert "09:00" not in text
    assert "17:00" not in text


def test_chat_response_normalizes_literal_newlines_and_menu_footer(api_module):
    raw = "Horario disponible\\n\\n_Escribe menú para volver al menu principal._"

    cleaned = api_module._normalize_chat_response_text(raw)

    assert "\\n" not in cleaned
    assert "Horario disponible\n\n" in cleaned
    assert cleaned.endswith("Escribe **menú** para volver al menú principal.")


def test_whatsapp_webhook_uses_same_chat_storage(client: TestClient, api_module, monkeypatch):
    monkeypatch.setattr(api_module, "WHATSAPP_APP_SECRET", "test-whatsapp-app-secret")
    verify_response = client.get(
        "/whatsapp/webhook/demo",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test-whatsapp-token",
            "hub.challenge": "challenge-ok",
        },
    )
    body = json.dumps({
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
    }).encode("utf-8")
    signature = "sha256=" + hmac.new(
        b"test-whatsapp-app-secret", body, hashlib.sha256
    ).hexdigest()
    webhook_response = client.post(
        "/whatsapp/webhook/demo",
        content=body,
        headers={"content-type": "application/json", "x-hub-signature-256": signature},
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
        json={"plan": "pro", "billing_period": "monthly"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "url": "https://checkout.stripe.test/session/cs_test_vantelia",
        "session_id": "cs_test_vantelia",
    }
    payload = _FakeStripeSessionApi.last_create_payload
    assert payload["mode"] == "subscription"
    assert payload["line_items"] == [{"price": "price_test_pro", "quantity": 1}]
    assert payload["client_reference_id"] == "public:pro:monthly"
    assert payload["metadata"] == {"source": "public_plans", "plan": "pro", "billing_period": "monthly"}
    assert "trial_period_days" not in payload["subscription_data"]
    assert payload["subscription_data"]["metadata"] == payload["metadata"]
    assert [field["key"] for field in payload["custom_fields"]] == ["website", "empresa", "ianame"]
    assert payload["billing_address_collection"] == "required"
    assert payload["phone_number_collection"] == {"enabled": True}
    assert payload["tax_id_collection"] == {"enabled": True}
    assert payload["allow_promotion_codes"] is True


def test_analytics_events_are_recorded_and_visible_to_admin(client: TestClient):
    public_response = client.post(
        "/analytics/event",
        json={
            "event": "demo_submit",
            "event_source": "vantelia_site",
            "page_path": "/demo/",
            "page_url": "https://www.vantelia.es/demo/",
            "sector": "Servicios B2B",
            "has_website_url": True,
        },
        headers={"User-Agent": "pytest-browser"},
    )
    admin_response = client.get(
        "/admin/analytics?days=30",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert public_response.status_code == 200
    assert public_response.json()["ok"] is True
    assert admin_response.status_code == 200
    payload = admin_response.json()
    assert payload["total_events"] >= 1
    assert payload["kpis"]["demo_submits"] >= 1
    assert any(item["event_name"] == "demo_submit" for item in payload["events_by_name"])
    assert payload["recent"][0]["event_name"] == "demo_submit"


def test_growth_endpoints_require_admin_and_daily_is_upserted(client: TestClient):
    forbidden = client.get("/admin/growth/overview")
    headers = {"Authorization": "Bearer test-admin-token"}
    activity_date = datetime.now().date().isoformat()
    payload = {
        "researched": 10,
        "contacts": 20,
        "followups": 5,
        "calls": 3,
        "positive_replies": 2,
        "conversations": 1,
        "meetings": 1,
        "proposals": 0,
        "won": 0,
        "eur_sold": 0,
        "new_recurring": 0,
        "delivery_hours": 1.5,
        "learning": "Mensaje concreto funciona mejor.",
        "blocker": "",
        "next_action": "Hacer follow-up.",
    }
    created = client.put(f"/admin/growth/daily/{activity_date}", json=payload, headers=headers)
    payload["contacts"] = 25
    updated = client.put(f"/admin/growth/daily/{activity_date}", json=payload, headers=headers)
    overview = client.get("/admin/growth/overview", headers=headers)

    assert forbidden.status_code == 401
    assert created.status_code == 200 and created.json()["created"] is True
    assert updated.status_code == 200 and updated.json()["created"] is False
    assert overview.status_code == 200
    body = overview.json()
    assert body["today"]["contacts"] == 25
    assert body["summaries"]["30"]["contacts"] >= 25
    assert body["plan_markdown"].startswith("# Sistema operativo")
    assert body["overall_state"] in {"green", "alert", "stop", "insufficient"}


def test_growth_pipeline_crud_history_and_weekly_review(client: TestClient):
    headers = {"Authorization": "Bearer test-admin-token"}
    item = {
        "company": "Empresa Growth Test",
        "campaign": "Campaña 1",
        "offer": "Oferta A",
        "stage": "conversacion",
        "value_eur": 1500,
        "decision_maker": "Laura",
        "contact": "laura@example.com",
        "problem": "Consultas sin contexto",
        "next_action": "Agendar descubrimiento",
        "next_action_date": datetime.now().date().isoformat(),
        "decision_date": "",
        "notes": "",
        "lost_reason": "",
    }
    created = client.post("/admin/growth/opportunities", json=item, headers=headers)
    assert created.status_code == 200
    opportunity_id = created.json()["item"]["id"]

    item["stage"] = "propuesta"
    item["next_action"] = "Pedir decisión"
    updated = client.patch(f"/admin/growth/opportunities/{opportunity_id}", json=item, headers=headers)
    listed = client.get("/admin/growth/opportunities?stage=propuesta", headers=headers)
    history = client.get(f"/admin/growth/opportunities/{opportunity_id}/history", headers=headers)
    review = client.post("/admin/growth/review/generate", headers=headers)
    saved = client.put(
        "/admin/growth/review",
        json={"week_start": datetime.now().date().isoformat(), "decision": "Mantener", "notes": "Test"},
        headers=headers,
    )

    assert updated.status_code == 200
    assert listed.status_code == 200
    assert any(row["id"] == opportunity_id for row in listed.json()["items"])
    assert len(history.json()["items"]) >= 2
    assert review.status_code == 200 and len(review.json()["priorities"]) == 5
    assert saved.status_code == 200

    deleted = client.delete(f"/admin/growth/opportunities/{opportunity_id}", headers=headers)
    assert deleted.status_code == 200


def test_growth_thresholds_and_plan_tasks(client: TestClient, api_module):
    headers = {"Authorization": "Bearer test-admin-token"}
    insufficient = api_module._growth_states(
        {"positive_reply_rate": 0, "meeting_rate": 0, "proposal_rate": 0, "close_rate": 0,
         "contacts": 99, "conversations": 0, "meetings": 0, "proposals": 7}
    )
    stop = api_module._growth_states(
        {"positive_reply_rate": 1, "meeting_rate": 20, "proposal_rate": 10, "close_rate": 5,
         "contacts": 100, "conversations": 10, "meetings": 10, "proposals": 8}
    )
    task = client.put(
        "/admin/growth/tasks",
        json={"task_key": "d1_pipeline", "completed": True},
        headers=headers,
    )
    overview = client.get("/admin/growth/overview", headers=headers)

    assert insufficient["positive_reply_rate"] == "insufficient"
    assert insufficient["close_rate"] == "insufficient"
    assert set(stop.values()) == {"stop"}
    assert task.status_code == 200
    assert next(row for row in overview.json()["tasks"] if row["key"] == "d1_pipeline")["completed"] is True


def test_stripe_webhook_activates_client_subscription(client: TestClient, api_module, monkeypatch):
    api_module.stripe = _FakeStripe
    monkeypatch.setattr(api_module, "STRIPE_WEBHOOK_SECRET", "whsec_test_dummy")

    response = client.post(
        "/webhooks/stripe",
        headers={"stripe-signature": "t=1,v1=test"},
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


def test_auth_subscription_refreshes_billing_dates_from_stripe(client: TestClient, api_module):
    api_module.stripe = _FakeStripeWithSubscription
    expected_iso_prefix = datetime.fromtimestamp(
        _FakeStripeSubscriptionApi.current_period_end,
        tz=api_module.timezone.utc,
    ).date().isoformat()
    api_module._set_client_subscription(
        "demo",
        plan="whatsapp",
        status="active",
        stripe_customer_id="cus_test_demo",
        stripe_subscription_id="sub_test_demo_refresh",
        renews_at="",
    )

    payload = api_module._build_subscription_public("demo").model_dump()

    assert payload["renews_at"].startswith(expected_iso_prefix)


def test_lifetime_subscription_does_not_refresh_from_stripe(client: TestClient, api_module):
    api_module.stripe = _FakeStripeWithSubscription
    api_module._set_client_subscription(
        "demo",
        plan="business",
        status="active",
        stripe_customer_id="cus_test_demo",
        stripe_subscription_id="sub_test_lifetime",
        renews_at="",
        lifetime=True,
        billing_period="lifetime",
    )

    payload = api_module._build_subscription_public("demo").model_dump()

    assert payload["plan"] == "business"
    assert payload["lifetime"] is True
    assert payload["renews_at"] == ""


def test_public_stripe_webhook_creates_client_with_alta_express(client: TestClient, api_module, monkeypatch):
    api_module.stripe = _FakeStripe
    monkeypatch.setattr(api_module, "STRIPE_WEBHOOK_SECRET", "whsec_test_dummy")
    captured_welcome = {}
    monkeypatch.setattr(api_module, "OPENAI_API_KEY", "sk-test-onboarding")
    monkeypatch.setattr(api_module, "run_onboarding", lambda **kwargs: _FakeOnboardingResult())
    monkeypatch.setattr(api_module, "cargar_indice", lambda cliente_id: None)
    monkeypatch.setattr(api_module, "_send_checkout_welcome_email", lambda **kwargs: captured_welcome.update(kwargs))

    response = client.post(
        "/webhooks/stripe",
        headers={"stripe-signature": "t=1,v1=test"},
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


# ---------------- Outreach panel tests ----------------

def _admin_headers():
    return {"Authorization": "Bearer test-admin-token"}


def test_outreach_stats_requires_admin_token(client: TestClient):
    response = client.get("/admin/outreach/stats")
    assert response.status_code in (401, 403)


def test_outreach_stats_with_token(client: TestClient):
    response = client.get("/admin/outreach/stats", headers=_admin_headers())
    assert response.status_code == 200
    data = response.json()
    assert "totals" in data and "funnel" in data and "daily" in data


def test_outreach_prospect_detail_exposes_reply_content(client: TestClient, api_module):
    email = "reply.detail@example.com"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with api_module._outreach_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO prospects (email, business_name, created_at, updated_at) VALUES (?,?,?,?)",
                (email, "Reply Detail", now, now),
            )
            conn.execute(
                """INSERT INTO events
                   (email, type, stage, url, subject, body_excerpt, ts, ua, ip)
                   VALUES (?, 'reply', 'fu1', ?, ?, ?, ?, '', '')""",
                (email, "<reply-detail-1@mx>", "Re: propuesta", "Quiero más información.", now),
            )
            conn.commit()

        response = client.get(f"/admin/outreach/prospects/{email}", headers=_admin_headers())
        assert response.status_code == 200, response.text
        reply = next(item for item in response.json()["events"] if item["type"] == "reply")
        assert reply["subject"] == "Re: propuesta"
        assert reply["body_excerpt"] == "Quiero más información."
    finally:
        with api_module._outreach_db() as conn:
            conn.execute("DELETE FROM events WHERE email=?", (email,))
            conn.execute("DELETE FROM prospects WHERE email=?", (email,))
            conn.commit()


def test_outreach_manual_reply_note_is_visible_in_detail(client: TestClient, api_module):
    email = "reply.manual@example.com"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with api_module._outreach_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO prospects (email, business_name, created_at, updated_at) VALUES (?,?,?,?)",
                (email, "Reply Manual", now, now),
            )
            conn.commit()

        recorded = client.post(
            "/admin/outreach/replies",
            headers=_admin_headers(),
            json={"email": email, "stage": "whatsapp", "note": "Me interesa; llámame mañana."},
        )
        assert recorded.status_code == 200, recorded.text

        detail = client.get(f"/admin/outreach/prospects/{email}", headers=_admin_headers())
        assert detail.status_code == 200, detail.text
        reply = next(item for item in detail.json()["events"] if item["type"] == "reply")
        assert reply["stage"] == "whatsapp"
        assert reply["body_excerpt"] == "Me interesa; llámame mañana."
    finally:
        with api_module._outreach_db() as conn:
            conn.execute("DELETE FROM events WHERE email=?", (email,))
            conn.execute("DELETE FROM prospects WHERE email=?", (email,))
            conn.commit()


def test_outreach_import_and_list_csv(client: TestClient):
    csv_payload = (
        "business_name,email,contact_name,niche,website,service_hint,city,phone,tags,source\n"
        "ACME Test,acme.test@example.com,Pablo,clinica,https://acme.test,medicina,Torrejon,,test,smoke\n"
    )
    response = client.post(
        "/admin/outreach/import",
        headers={**_admin_headers(), "Content-Type": "text/csv"},
        content=csv_payload,
    )
    assert response.status_code == 200, response.text
    assert response.json()["added"] >= 1

    listing = client.get("/admin/outreach/prospects?q=ACME", headers=_admin_headers())
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert any(item["email"] == "acme.test@example.com" for item in items)


def test_outreach_suppress_add_and_remove(client: TestClient):
    add = client.post(
        "/admin/outreach/suppress",
        headers={**_admin_headers(), "Content-Type": "application/json"},
        json={"email": "baja.test@example.com", "reason": "smoke"},
    )
    assert add.status_code == 200
    listed = client.get("/admin/outreach/suppressions", headers=_admin_headers()).json()
    assert any(item["email"] == "baja.test@example.com" for item in listed["items"])

    rm = client.delete("/admin/outreach/suppress/baja.test@example.com", headers=_admin_headers())
    assert rm.status_code == 200


def test_outreach_tracking_pixel_logs_open(client: TestClient, api_module):
    from outreach_templates import make_tracking_token

    token = make_tracking_token("track.test@example.com", "cold", "test-outreach-secret")
    response = client.get(f"/track/open/{token}.gif")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/gif"

    detail = client.get(
        "/admin/outreach/prospects/track.test@example.com",
        headers=_admin_headers(),
    )
    if detail.status_code == 200:
        events = detail.json().get("events", [])
        assert any(e["type"] == "open" for e in events)


def test_outreach_reply_intent_opens_prefilled_mail_and_logs_event(client: TestClient, api_module):
    from outreach_templates import make_tracking_token

    csv_payload = (
        "business_name,email,contact_name,niche,website,service_hint,city,phone,tags,source\n"
        "Demo Intent,demo.intent@example.com,Pablo,clinica,https://demo.test,medicina,Torrejon,,test,smoke\n"
    )
    created = client.post(
        "/admin/outreach/import",
        headers={**_admin_headers(), "Content-Type": "text/csv"},
        content=csv_payload,
    )
    assert created.status_code == 200

    token = make_tracking_token("demo.intent@example.com", "cold", "test-outreach-secret")
    mailto = (
        "mailto:info@vantelia.es"
        "?subject=Demo%20gratuita%20Vantelia"
        "&body=Buenas%2C%0A%0AMe%20interesa.%20Preparame%20la%20demo%20gratuita%20sin%20compromiso."
    )
    with pytest.raises(httpx.InvalidURL):
        client.get(f"/track/reply/{token}", params={"u": mailto}, follow_redirects=False)

    detail = client.get(
        "/admin/outreach/prospects/demo.intent@example.com",
        headers=_admin_headers(),
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["prospect"]["status"] == "engaged"
    assert any(e["type"] == "reply_intent" for e in payload.get("events", []))


def test_outreach_preflight_renders_html_even_when_wizard_email_not_imported(client: TestClient):
    response = client.post(
        "/admin/outreach/preflight",
        headers={**_admin_headers(), "Content-Type": "application/json"},
        json={"stage": "cold", "emails": ["not.imported@example.com"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["counts"]["real_candidates"] == 0
    assert data["counts"]["skipped"]["missing_email"] == 1
    assert data["html_active"] is True
    # Copy v2: el cold NO lleva enlace (mejor entregabilidad); pide respuesta si/no.
    # El enlace instantaneo /demo/go aparece a partir de fu1.
    assert "Responde" in data["html"]
    assert "/demo/go/" not in data["html"]


def test_outreach_email_uses_prefilled_demo_link(client: TestClient, api_module):
    from outreach_templates import Prospect, demo_url_with_utm, render

    prospect = Prospect(
        email="prefill.demo@example.com",
        business_name="Clinica Demo Norte",
        niche="clinica dental",
        website="https://clinicademo.test",
        city="Madrid",
    )
    # demo_url_with_utm sigue construyendo el formulario prefilled (fallback sin web).
    url = demo_url_with_utm("cold", prospect)
    assert url.startswith("https://www.vantelia.es/demo/?")
    assert "signup=1" not in url
    assert "utm_source=outreach" in url
    assert "empresa=Clinica+Demo+Norte" in url
    assert "email=prefill.demo%40example.com" in url
    assert "web=https%3A%2F%2Fclinicademo.test" in url

    # Copy v2: el cold va SIN enlace (solo pide respuesta si/no) para no quemar
    # entregabilidad; el enlace instantaneo /demo/go/{token} (demo pre-generada)
    # entra a partir de fu1. El servidor resuelve el prospect por el token.
    _subject, cold_text, cold_html = render("cold", prospect, "baja@vantelia.es")
    assert "Responde" in cold_text
    assert "/demo/go/" not in cold_text
    assert "/demo/go/" not in cold_html

    _subject, text, html = render("fu1", prospect, "baja@vantelia.es")
    assert "/demo/go/" in html
    assert "/demo/go/" in text


def test_outreach_campaigns_backfill_orphan_cold_sends(client: TestClient, api_module):
    for email, business in [
        ("legacy.one@example.com", "Legacy One"),
        ("legacy.two@example.com", "Legacy Two"),
    ]:
        created = client.post(
            "/admin/outreach/prospects",
            headers=_admin_headers(),
            json={"email": email, "business_name": business},
        )
        assert created.status_code == 200, created.text

    with api_module._outreach_db() as conn:
        for email in ["legacy.one@example.com", "legacy.two@example.com"]:
            conn.execute(
                """INSERT INTO sends
                   (campaign_id, email, stage, subject, body_text, body_html, sent_at, mode, message_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (0, email, "cold", "Hola", "texto", "<p>texto</p>", "2026-05-07T00:00:00+00:00", "send", f"msg-{email}"),
            )
        conn.commit()

    listing = client.get("/admin/outreach/campaigns", headers=_admin_headers())
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    legacy = next(item for item in items if item["name"].startswith("Emails cold lanzados"))
    assert legacy["status"] == "completed"
    assert legacy["metrics"]["total"] == 2
    assert legacy["metrics"]["sent"] == 2

    detail = client.get(f"/admin/outreach/campaigns/{legacy['id']}", headers=_admin_headers())
    assert detail.status_code == 200
    assert {member["email"] for member in detail.json()["members"]} == {
        "legacy.one@example.com",
        "legacy.two@example.com",
    }


def test_outreach_hot_leads_prioritizes_generated_demo(client: TestClient, api_module):
    sent_at = (datetime.utcnow() - timedelta(days=4)).isoformat(timespec="seconds") + "+00:00"
    created = client.post(
        "/admin/outreach/prospects",
        headers=_admin_headers(),
        json={"email": "hot.demo@example.com", "business_name": "Hot Demo"},
    )
    assert created.status_code == 200, created.text

    with api_module._outreach_db() as conn:
        conn.execute(
            "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,?,?)",
                (
                    "hot.demo@example.com",
                    "demo_generated",
                    "cold",
                    "https://app.test.local/demo/demo_auto_hot",
                    sent_at,
                    "pytest",
                    "127.0.0.1",
                ),
        )
        conn.commit()

    response = client.get("/admin/outreach/hot-leads?limit=5&days=60", headers=_admin_headers())
    assert response.status_code == 200, response.text
    item = next(row for row in response.json()["items"] if row["email"] == "hot.demo@example.com")
    assert item["demos_recent"] == 1
    assert item["score"] >= 12


def test_outreach_followup_queue_segments_and_returns_copy(client: TestClient, api_module):
    now = datetime.utcnow().isoformat(timespec="seconds") + "+00:00"
    prospects = [
        ("fu.p1@example.com", "Follow P1"),
        ("fu.p2@example.com", "Follow P2"),
        ("fu.p3@example.com", "Follow P3"),
    ]
    for email, business in prospects:
        created = client.post(
            "/admin/outreach/prospects",
            headers=_admin_headers(),
            json={
                "email": email,
                "business_name": business,
                "niche": "clinica dental",
                "website": f"https://{email.split('@')[0]}.test",
            },
        )
        assert created.status_code == 200, created.text

    with api_module._outreach_db() as conn:
        for email, _business in prospects:
            conn.execute(
                """INSERT INTO sends
                   (email, stage, subject, body_text, body_html, sent_at, mode, message_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (email, "cold", "Hola", "texto", "<p>texto</p>", now, "send", f"msg-{email}"),
            )
        conn.execute(
            "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,?,?)",
            ("fu.p1@example.com", "click", "cold", "https://www.vantelia.es/demo/", now, "pytest", "127.0.0.1"),
        )
        conn.execute(
            "INSERT INTO events (email, type, stage, ts, ua, ip) VALUES (?,?,?,?,?,?)",
            ("fu.p2@example.com", "open", "cold", now, "pytest", "127.0.0.1"),
        )
        conn.commit()

    queue = client.get("/admin/outreach/followup-queue?days=60", headers=_admin_headers())
    assert queue.status_code == 200, queue.text
    by_email = {item["email"]: item for item in queue.json()["items"]}
    assert by_email["fu.p1@example.com"]["priority"] == 1
    assert by_email["fu.p2@example.com"]["priority"] == 2
    assert by_email["fu.p3@example.com"]["priority"] == 3
    assert "respondes \"si\"" in by_email["fu.p1@example.com"]["body_text"]
    assert "empresa=Follow+P1" in by_email["fu.p1@example.com"]["demo_url"]

    copy = client.get("/admin/outreach/prospects/fu.p1@example.com/followup-copy", headers=_admin_headers())
    assert copy.status_code == 200
    assert copy.json()["subject"].startswith("Follow P1")
    assert "mailto:" in copy.json()["mailto"]


def test_outreach_autopilot_marks_engaged_and_groups_approvals(client: TestClient, api_module):
    sent_at = (datetime.utcnow() - timedelta(days=4)).isoformat(timespec="seconds") + "+00:00"
    created = client.post(
        "/admin/outreach/prospects",
        headers=_admin_headers(),
        json={
            "email": "auto.p1@example.com",
            "business_name": "Auto P1",
            "niche": "clinica dental",
            "website": "https://autop1.test",
        },
    )
    assert created.status_code == 200, created.text

    with api_module._outreach_db() as conn:
        conn.execute(
            """INSERT INTO sends
               (email, stage, subject, body_text, body_html, sent_at, mode, message_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("auto.p1@example.com", "cold", "Hola", "texto", "<p>texto</p>", sent_at, "send", "msg-auto-p1"),
        )
        conn.execute(
            "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,?,?)",
            ("auto.p1@example.com", "demo_generated", "cold", "https://app.test.local/demo/x", sent_at, "pytest", "127.0.0.1"),
        )
        conn.commit()

    status_response = client.get("/admin/outreach/autopilot?days=60", headers=_admin_headers())
    assert status_response.status_code == 200, status_response.text
    status_data = status_response.json()
    assert status_data["p1_count"] >= 1
    assert "auto.p1@example.com" in status_data["approval_groups"]["fu1"]
    plan_item = next(item for item in status_data["today_plan"] if item["email"] == "auto.p1@example.com")
    assert plan_item["next_action"] == "approve_send"
    assert plan_item["next_action_label"] == "Aprobar fu1"
    assert plan_item["requires_approval"] is True
    assert "Asunto:" in plan_item["suggested_message"]
    assert status_data["rules"]["safeguards"].startswith("Maximo")

    run_response = client.post(
        "/admin/outreach/autopilot/run",
        headers=_admin_headers(),
        json={"days": 60, "limit": 120, "apply_status": True},
    )
    assert run_response.status_code == 200, run_response.text
    assert run_response.json()["updated_engaged"] >= 1

    detail = client.get("/admin/outreach/prospects/auto.p1@example.com", headers=_admin_headers())
    assert detail.status_code == 200
    assert detail.json()["prospect"]["status"] == "engaged"


def test_outreach_autopilot_blocks_prospect_after_max_touches(client: TestClient, api_module):
    sent_at = (datetime.utcnow() - timedelta(days=12)).isoformat(timespec="seconds") + "+00:00"
    created = client.post(
        "/admin/outreach/prospects",
        headers=_admin_headers(),
        json={
            "email": "max.touch@example.com",
            "business_name": "Max Touch",
            "niche": "clinica dental",
            "website": "https://max-touch.test",
        },
    )
    assert created.status_code == 200, created.text

    with api_module._outreach_db() as conn:
        for idx, stage in enumerate(["cold", "cold", "fu1", "fu2"], start=1):
            conn.execute(
                """INSERT INTO sends
                   (email, stage, subject, body_text, body_html, sent_at, mode, message_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                ("max.touch@example.com", stage, "Hola", "texto", "<p>texto</p>", sent_at, "send", f"msg-max-{idx}"),
            )
        conn.execute(
            "INSERT INTO events (email, type, stage, ts, ua, ip) VALUES (?,?,?,?,?,?)",
            ("max.touch@example.com", "open", "fu2", sent_at, "pytest", "127.0.0.1"),
        )
        conn.commit()

    queue = client.get("/admin/outreach/followup-queue?days=60", headers=_admin_headers())
    assert queue.status_code == 200, queue.text
    item = next(row for row in queue.json()["items"] if row["email"] == "max.touch@example.com")
    assert item["recommended_stage"] == "breakup"
    assert item["can_send"] is False
    assert item["blocked_reason"] == "limite de contactos alcanzado"

    response = client.get("/admin/outreach/autopilot?days=60", headers=_admin_headers())
    assert response.status_code == 200, response.text
    assert "max.touch@example.com" not in response.json()["approval_groups"].get("breakup", [])


def test_outreach_stats_and_list_show_vantelia_link_clicks(client: TestClient, api_module):
    from outreach_templates import make_tracking_token

    csv_payload = (
        "business_name,email,contact_name,niche,website,service_hint,city,phone,tags,source\n"
        "Vantelia Click,click.vantelia@example.com,Pablo,clinica,https://demo.test,medicina,Torrejon,,test,smoke\n"
    )
    created = client.post(
        "/admin/outreach/import",
        headers={**_admin_headers(), "Content-Type": "text/csv"},
        content=csv_payload,
    )
    assert created.status_code == 200

    token = make_tracking_token("click.vantelia@example.com", "cold", "test-outreach-secret")
    click = client.get(
        f"/track/click/{token}",
        params={"u": "https://www.vantelia.es/planes"},
        follow_redirects=False,
    )
    assert click.status_code == 302

    stats = client.get("/admin/outreach/stats", headers=_admin_headers())
    assert stats.status_code == 200
    stats_data = stats.json()
    assert stats_data["totals"]["vantelia_clicks_unique"] >= 1
    assert any(item["email"] == "click.vantelia@example.com" for item in stats_data["vantelia_clickers"])

    listing = client.get("/admin/outreach/prospects?clicked_vantelia=true", headers=_admin_headers())
    assert listing.status_code == 200
    item = next(i for i in listing.json()["items"] if i["email"] == "click.vantelia@example.com")
    assert item["vantelia_clicks"] >= 1


def test_outreach_admin_preview_does_not_include_live_tracking(client: TestClient, api_module):
    from outreach_templates import make_tracking_token

    csv_payload = (
        "business_name,email,contact_name,niche,website,service_hint,city,phone,tags,source\n"
        "Preview Safe,preview.safe@example.com,Pablo,clinica,https://demo.test,medicina,Torrejon,,test,smoke\n"
    )
    created = client.post(
        "/admin/outreach/import",
        headers={**_admin_headers(), "Content-Type": "text/csv"},
        content=csv_payload,
    )
    assert created.status_code == 200

    token = make_tracking_token("preview.safe@example.com", "cold", "test-outreach-secret")
    tracked = (
        f'<html><body><a href="https://app.test.local/track/click/{token}?u=https%3A%2F%2Fwww.vantelia.es%2Fplanes">web</a>'
        f'<img src="https://app.test.local/track/open/{token}.gif" width="1" height="1" /></body></html>'
    )
    with api_module._outreach_db() as conn:
        cur = conn.execute(
            """INSERT INTO sends (email, stage, subject, body_text, body_html, sent_at, mode, message_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("preview.safe@example.com", "cold", "Preview", "texto", tracked, "2026-05-07T00:00:00+00:00", "send", "msg-test"),
        )
        send_id = cur.lastrowid
        conn.commit()

    preview = client.get(
        f"/admin/outreach/prospects/preview.safe@example.com/render?stage=cold&send_id={send_id}",
        headers=_admin_headers(),
    )
    assert preview.status_code == 200
    html = preview.json()["html"]
    assert "/track/open/" not in html
    assert "/track/click/" not in html
    assert 'href="https://www.vantelia.es/planes"' in html


def test_outreach_tracking_invalid_token_does_not_crash(client: TestClient):
    response = client.get("/track/open/invalid-token.gif")
    assert response.status_code == 200  # devuelve pixel igualmente
    click = client.get("/track/click/invalid-token", params={"u": "https://www.vantelia.es"})
    assert click.status_code in (302, 404)


# ---------------- Autopilot activity log ----------------

def test_autopilot_log_requires_admin(client: TestClient):
    response = client.get("/admin/outreach/autopilot-log")
    assert response.status_code in (401, 403)


def test_autopilot_log_returns_items_shape(client: TestClient):
    response = client.get("/admin/outreach/autopilot-log?limit=10", headers=_admin_headers())
    assert response.status_code == 200, response.text
    data = response.json()
    assert "items" in data and isinstance(data["items"], list)
    assert "count" in data


def test_autopilot_tick_records_event(client: TestClient):
    import time

    tick = client.post("/admin/outreach/autopilot-tick", headers=_admin_headers())
    assert tick.status_code == 200, tick.text
    # El endpoint registra manual_run_requested síncrono y dispara la ronda en un thread.
    # Damos margen a que el thread escriba al menos skip_env_disabled / tick_end.
    deadline = time.time() + 5.0
    events = []
    while time.time() < deadline:
        resp = client.get("/admin/outreach/autopilot-log?limit=20", headers=_admin_headers())
        assert resp.status_code == 200
        events = [it["event"] for it in resp.json()["items"]]
        if "manual_run_requested" in events and "tick_end" in events:
            break
        time.sleep(0.1)
    assert "manual_run_requested" in events, f"Eventos vistos: {events}"


def test_autopilot_tick_overlap_is_reported_without_legacy_skip_event(client: TestClient, api_module):
    lock = api_module.outreach_autonomous_tick_lock
    acquired = lock.acquire(blocking=False)
    if not acquired:
        pytest.skip("autonomous tick lock already held by another test thread")
    try:
        tick = client.post("/admin/outreach/autopilot-tick", headers=_admin_headers())
        assert tick.status_code == 200, tick.text
        assert tick.json()["started"] is False
    finally:
        lock.release()

    resp = client.get("/admin/outreach/autopilot-log?limit=20", headers=_admin_headers())
    assert resp.status_code == 200
    events = [it["event"] for it in resp.json()["items"]]
    assert "tick_skipped_running" in events
    assert "tick_overlap_skipped" not in events


def test_autopilot_config_followup_days_control_queue_readiness(client: TestClient, api_module):
    email = "delay.config@example.com"
    sent_at = (datetime.utcnow() - timedelta(days=4)).isoformat(timespec="seconds") + "+00:00"
    try:
        resp = client.put(
            "/admin/outreach/autopilot-config",
            headers=_admin_headers(),
            json={"followup_days": {"fu1": 7, "fu2": 8, "breakup": 9}},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["followup_days"] == {"fu1": 7, "fu2": 8, "breakup": 9}

        created = client.post(
            "/admin/outreach/prospects",
            headers=_admin_headers(),
            json={"email": email, "business_name": "Delay Config", "niche": "clinica dental"},
        )
        assert created.status_code == 200, created.text

        with api_module._outreach_db() as conn:
            conn.execute(
                """INSERT INTO sends
                   (email, stage, subject, body_text, body_html, sent_at, mode, message_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (email, "cold", "Hola", "texto", "<p>texto</p>", sent_at, "send", "msg-delay-config"),
            )
            conn.commit()

        queue = client.get("/admin/outreach/followup-queue?days=60", headers=_admin_headers())
        assert queue.status_code == 200, queue.text
        item = next(it for it in queue.json()["items"] if it["email"] == email)
        assert item["recommended_stage"] == "fu1"
        assert item["can_send"] is False
        assert item["blocked_reason"].startswith("esperar")
    finally:
        client.put(
            "/admin/outreach/autopilot-config",
            headers=_admin_headers(),
            json={"followup_days": {"fu1": 4, "fu2": 5, "breakup": 6}},
        )


def test_autopilot_config_one_button_target_generates_spain_targets(client: TestClient):
    try:
        resp = client.put(
            "/admin/outreach/autopilot-config",
            headers=_admin_headers(),
            json={"target_companies": 12, "targets": []},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["target_companies"] == 12
        assert data["daily_new_target"] == 12
        assert data["daily_cold_cap"] == 12
        assert data["auto_targets_enabled"] is True
        assert data["targets"] == []
        assert len(data["generated_targets"]) >= 4
        assert len(data["active_targets"]) == len(data["generated_targets"])
        assert all(item["sector"] and item["city"] for item in data["active_targets"])
    finally:
        client.put(
            "/admin/outreach/autopilot-config",
            headers=_admin_headers(),
            json={"target_companies": 20},
        )


def test_autopilot_log_level_filter(client: TestClient):
    # manual_run_requested es info -> con filter=error no debe aparecer.
    client.post("/admin/outreach/autopilot-tick", headers=_admin_headers())
    resp = client.get("/admin/outreach/autopilot-log?level=error&limit=5", headers=_admin_headers())
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(it["level"] == "error" for it in items)


def test_outreach_discovery_expands_large_city_queries(api_module):
    from outreach_discover import _places_queries  # type: ignore

    queries = _places_queries("centro estetica", "Madrid", 80)
    joined = " ".join(queries).lower()
    assert len(queries) > 4
    assert len(queries) <= 14
    assert "centro estetica en madrid" in joined
    assert "salon belleza" in joined or "clinica estetica" in joined
    assert "salamanca" in joined or "chamberi" in joined


def test_outreach_places_search_uses_places_api_new(api_module, monkeypatch):
    import outreach_discover  # type: ignore

    calls = []

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "places": [
                    {
                        "id": "places/test-place",
                        "displayName": {"text": "Clinica Test"},
                        "formattedAddress": "Calle Test, 28830 San Fernando de Henares, Madrid, Espana",
                        "websiteUri": "https://example.test",
                        "nationalPhoneNumber": "911111111",
                        "types": ["beauty_salon"],
                    }
                ]
            }

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            calls.append({"url": url, "headers": headers or {}, "json": json or {}})
            return _Resp()

    monkeypatch.setattr(outreach_discover.httpx, "Client", _Client)

    results = outreach_discover.google_places_search("clinicas esteticas en San Fernando del Henares", "test-key", max_results=1)

    assert results[0]["place_id"] == "places/test-place"
    assert calls[0]["url"] == "https://places.googleapis.com/v1/places:searchText"
    assert "maps.googleapis.com/maps/api/place" not in calls[0]["url"]
    assert calls[0]["headers"]["X-Goog-Api-Key"] == "test-key"
    assert "places.displayName" in calls[0]["headers"]["X-Goog-FieldMask"]
    assert calls[0]["json"]["textQuery"] == "clinicas esteticas en San Fernando del Henares"


def test_outreach_discovery_caps_email_scraping(api_module, monkeypatch):
    import outreach_discover  # type: ignore

    raw_places = [
        {
            "place_id": f"places/test-{i}",
            "name": f"Centro {i}",
            "formatted_address": "Calle Test, 28830 San Fernando de Henares, Madrid, Espana",
            "types": ["beauty_salon"],
                "_details": {
                    "name": f"Centro {i}",
                    "website": f"https://centro{i}.test",
                    "international_phone_number": f"91111111{i}",
                "formatted_address": "Calle Test, 28830 San Fernando de Henares, Madrid, Espana",
                "types": ["beauty_salon"],
            },
        }
        for i in range(6)
    ]
    scrape_calls = []

    monkeypatch.setattr(outreach_discover, "google_places_search", lambda *args, **kwargs: raw_places)

    def _fake_extract(url):
        scrape_calls.append(url)
        return [f"hola@{url.replace('https://', '')}"]

    monkeypatch.setattr(outreach_discover, "extract_emails_from_website", _fake_extract)

    companies = outreach_discover.discover_companies(
        "clinica estetica",
        "San Fernando del Henares",
        max_results=6,
        extract_emails=True,
        api_key="test-key",
        source="places",
        email_target=2,
        max_email_scrapes=2,
    )

    assert len(scrape_calls) == 2
    assert sum(1 for c in companies if c.email) == 2


def test_outreach_filter_new_discoveries_excludes_existing_campaigns_and_sends(api_module):
    with api_module._outreach_db() as conn:
        now = api_module._outreach_now()
        conn.execute(
            """INSERT INTO prospects (email, business_name, website, phone, city, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            ("known@example.com", "Known Center", "https://known.example", "911111111", "Madrid", now, now),
        )
        conn.execute(
            """INSERT INTO campaigns (name, status, stage, created_at, updated_at)
               VALUES (?,?,?,?,?)""",
            ("Camp", "draft", "cold", now, now),
        )
        campaign_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute(
            """INSERT INTO campaign_members (campaign_id, email, stage, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (campaign_id, "campaign@example.com", "cold", "pending", now, now),
        )
        conn.execute(
            """INSERT INTO sends (email, stage, subject, sent_at, mode)
               VALUES (?,?,?,?,?)""",
            ("sent@example.com", "cold", "Subject", now, "send"),
        )
        conn.execute(
            "INSERT INTO suppressions (email, reason, added_at) VALUES (?,?,?)",
            ("baja@example.com", "manual", now),
        )
        conn.commit()

        items = [
            SimpleNamespace(email="known@example.com", website="", phone="", business_name="Other", city="Madrid"),
            SimpleNamespace(email="campaign@example.com", website="", phone="", business_name="Other", city="Madrid"),
            SimpleNamespace(email="sent@example.com", website="", phone="", business_name="Other", city="Madrid"),
            SimpleNamespace(email="baja@example.com", website="", phone="", business_name="Other", city="Madrid"),
            SimpleNamespace(email="new@example.com", website="https://new.example", phone="922222222", business_name="New Center", city="Madrid"),
        ]
        filtered = api_module._outreach_filter_new_discoveries(conn, items)

    assert [item.email for item in filtered] == ["new@example.com"]


# ----------- Instagram captacion -----------


def test_instagram_stats_requires_admin_token(client: TestClient):
    resp = client.get("/admin/instagram/stats")
    assert resp.status_code in (401, 403)


def test_instagram_stats_with_token_returns_expected_shape(client: TestClient):
    resp = client.get("/admin/instagram/stats", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "totals" in data and "funnel" in data
    assert "prospects" in data["totals"]
    assert set(data["funnel"].keys()) >= {"cold", "fu1", "fu2", "breakup"}


def test_instagram_prospect_crud_flow(client: TestClient):
    create = client.post(
        "/admin/instagram/prospects",
        headers={**_admin_headers(), "Content-Type": "application/json"},
        json={
            "username": "demo_dental_test",
            "full_name": "Clinica Demo",
            "niche": "clinica dental",
            "city": "Madrid",
            "followers_count": 1200,
        },
    )
    assert create.status_code == 200

    listing = client.get(
        "/admin/instagram/prospects?q=demo_dental",
        headers=_admin_headers(),
    )
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert any(it["username"] == "demo_dental_test" for it in items)

    patch = client.patch(
        "/admin/instagram/prospects/demo_dental_test",
        headers={**_admin_headers(), "Content-Type": "application/json"},
        json={"status": "queued", "score": 42},
    )
    assert patch.status_code == 200

    detail = client.get(
        "/admin/instagram/prospects/demo_dental_test",
        headers=_admin_headers(),
    )
    assert detail.status_code == 200
    assert detail.json()["prospect"]["status"] == "queued"
    assert detail.json()["prospect"]["score"] == 42

    suppress = client.post(
        "/admin/instagram/suppress",
        headers={**_admin_headers(), "Content-Type": "application/json"},
        json={"username": "demo_dental_test", "reason": "test"},
    )
    assert suppress.status_code == 200
    suppr = client.get("/admin/instagram/suppressions", headers=_admin_headers())
    assert any(s["username"] == "demo_dental_test" for s in suppr.json()["items"])

    # Quitar supresion para no afectar drafts test siguiente
    client.delete("/admin/instagram/suppress/demo_dental_test", headers=_admin_headers())

    delete = client.delete(
        "/admin/instagram/prospects/demo_dental_test",
        headers=_admin_headers(),
    )
    assert delete.status_code == 200


def test_instagram_draft_generation_no_network(client: TestClient, api_module):
    # Crear prospect fresco y generar draft cold sin pegar a red.
    client.post(
        "/admin/instagram/prospects",
        headers={**_admin_headers(), "Content-Type": "application/json"},
        json={
            "username": "demo_draft_user",
            "full_name": "Demo Draft Studio",
            "niche": "estetica",
            "city": "Barcelona",
            "followers_count": 800,
        },
    )
    resp = client.post(
        "/admin/instagram/draft",
        headers={**_admin_headers(), "Content-Type": "application/json"},
        json={"stage": "cold", "max": 5, "after_days": 0},
    )
    assert resp.status_code == 200
    drafts = resp.json()["drafts"]
    assert any(d["username"] == "demo_draft_user" for d in drafts)
    target = next(d for d in drafts if d["username"] == "demo_draft_user")
    assert target["stage"] == "cold"
    # Cold usa las plantillas editables del panel (Mensajes / templates_v2): variantes A/B/C.
    assert target["variant"] in {"A", "B", "C"}
    assert "ig.me/m/" in target["deep_link"]
    # Mensaje sin reventar limite 500 chars
    assert len(target["message"]) <= 500
    # Cleanup
    client.delete("/admin/instagram/prospects/demo_draft_user", headers=_admin_headers())


def test_instagram_draft_generation_skips_prior_dm_attempt(client: TestClient, api_module):
    headers = {**_admin_headers(), "Content-Type": "application/json"}
    blocked_user = "resume_blocked_user"
    fresh_user = "resume_fresh_user"
    for username in (blocked_user, fresh_user):
        created = client.post(
            "/admin/instagram/prospects",
            headers=headers,
            json={
                "username": username,
                "full_name": username.replace("_", " ").title(),
                "niche": "estetica",
                "city": "Madrid",
                "followers_count": 700,
                "score": 90,
            },
        )
        assert created.status_code == 200, created.text

    with api_module._instagram_db() as conn:
        now = api_module._instagram_now()
        conn.execute(
            """INSERT INTO ig_sends (username, stage, variant, message_text, mode, ready, drafted_at)
               VALUES (?,?,?,?,?,?,?)""",
            (blocked_user, "cold", "A", "dm ya intentado", "sending", 0, now),
        )
        conn.commit()

    resp = client.post(
        "/admin/instagram/draft",
        headers=headers,
        json={"stage": "cold", "max": 50, "after_days": 0},
    )
    assert resp.status_code == 200, resp.text
    usernames = {d["username"] for d in resp.json()["drafts"]}
    assert blocked_user not in usernames
    assert fresh_user in usernames


def test_instagram_autosend_claim_skips_draft_on_resume(client: TestClient, api_module, monkeypatch):
    scripts_dir = REPO_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    monkeypatch.setenv("IG_DB_PATH", str(api_module._instagram_db_path()))
    sys.modules.pop("instagram_autosend", None)
    instagram_autosend = importlib.import_module("instagram_autosend")

    username = "resume_claim_user"
    with api_module._instagram_db() as conn:
        now = api_module._instagram_now()
        conn.execute(
            """INSERT OR IGNORE INTO ig_prospects
               (username, full_name, niche, city, status, source, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (username, "Resume Claim User", "estetica", "Madrid", "queued", "test", now, now),
        )
        conn.execute(
            """INSERT INTO ig_sends (username, stage, variant, message_text, mode, ready, drafted_at)
               VALUES (?,?,?,?,?,?,?)""",
            (username, "cold", "A", "hola desde test", "draft", 1, now),
        )
        send_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.commit()

    before = instagram_autosend.fetch_pending_drafts(20)
    assert any(d["id"] == send_id for d in before)

    with api_module._instagram_db() as conn:
        claimed = instagram_autosend._claim_send_attempt(conn, send_id)  # type: ignore[attr-defined]
    assert claimed is not None

    after = instagram_autosend.fetch_pending_drafts(20)
    assert all(d["id"] != send_id for d in after)
    with api_module._instagram_db() as conn:
        row = conn.execute("SELECT mode, ready FROM ig_sends WHERE id=?", (send_id,)).fetchone()
    assert row["mode"] == "sending"
    assert row["ready"] == 0


def test_tiktok_autosend_claim_skips_draft_on_resume(client: TestClient, api_module, monkeypatch):
    scripts_dir = REPO_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    monkeypatch.setenv("TK_DB_PATH", str(api_module.TK_DEFAULT_DB))
    sys.modules.pop("tiktok_autosend", None)
    tiktok_autosend = importlib.import_module("tiktok_autosend")

    api_module._tk_migrate()
    username = "tk_resume_claim_user"
    with api_module._tk_db() as conn:
        now = api_module._tk_now()
        conn.execute(
            """INSERT OR IGNORE INTO tk_prospects
               (username, business_name, niche, city, status, source, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (username, "TK Resume Claim User", "estetica", "Madrid", "queued", "test", now, now),
        )
        conn.execute(
            """INSERT INTO tk_sends (username, stage, variant, message_text, mode, ready, drafted_at)
               VALUES (?,?,?,?,?,?,?)""",
            (username, "cold", "A", "hola desde test", "draft", 1, now),
        )
        send_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.commit()

    assert any(d["id"] == send_id for d in tiktok_autosend.fetch_pending_drafts(20))
    with api_module._tk_db() as conn:
        claimed = tiktok_autosend._claim_send_attempt(conn, send_id)  # type: ignore[attr-defined]
    assert claimed is not None
    assert all(d["id"] != send_id for d in tiktok_autosend.fetch_pending_drafts(20))

    with api_module._tk_db() as conn:
        row = conn.execute("SELECT mode, ready FROM tk_sends WHERE id=?", (send_id,)).fetchone()
    assert row["mode"] == "sending"
    assert row["ready"] == 0


def test_tiktok_campaign_pauses_when_autosend_cannot_send(client: TestClient, api_module, monkeypatch):
    scripts_dir = REPO_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    monkeypatch.setenv("TK_AUTOSEND_ENABLED", "true")
    monkeypatch.setenv("TK_DB_PATH", str(api_module.TK_DEFAULT_DB))
    sys.modules.pop("tiktok_autosend", None)
    tiktok_autosend = importlib.import_module("tiktok_autosend")

    api_module._tk_migrate()
    username = "tk_send_fail_user"
    with api_module._tk_db() as conn:
        now = api_module._tk_now()
        conn.execute(
            """INSERT OR IGNORE INTO tk_prospects
               (username, business_name, niche, city, status, source, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (username, "TK Send Fail User", "estetica", "Madrid", "queued", "campaign_test", now, now),
        )
        conn.execute(
            """INSERT INTO tk_sends (username, stage, variant, message_text, mode, ready, drafted_at)
               VALUES (?,?,?,?,?,?,?)""",
            (username, "cold", "A", "hola desde test", "draft", 1, now),
        )
        conn.commit()

    monkeypatch.setattr(tiktok_autosend, "autosend_drafts", lambda drafts, dry_run=False: 0)
    state = {"target_count": 30, "sent_count": 0, "discovered_count": 45, "pending_drafts": 1, "status": "sending"}
    result = api_module._tk_campaign_iteration(state)
    assert result["action"] == "error"

    current = api_module._tk_campaign_state()
    assert current["status"] == "paused"
    assert "Envio pausado" in current["error_msg"]


def test_instagram_manual_contact_creates_timeline_and_summary(client: TestClient):
    old_ts = "2026-01-01T10:00:00+00:00"
    resp = client.post(
        "/admin/instagram/manual-contact",
        headers={**_admin_headers(), "Content-Type": "application/json"},
        json={
            "username": "@Demo_Manual_User",
            "full_name": "Demo Manual",
            "message_text": "hola, te he preparado una demo",
            "stage": "cold",
            "contacted_at": old_ts,
            "niche": "estetica",
            "city": "Madrid",
            "notes": "contacto manual test",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["username"] == "demo_manual_user"
    assert data["stage"] == "cold"
    assert data["next_stage"] == "fu1"
    assert data["next_followup_at"]

    detail = client.get("/admin/instagram/prospects/demo_manual_user", headers=_admin_headers())
    assert detail.status_code == 200
    prospect = detail.json()["prospect"]
    assert prospect["status"] == "contacted"
    assert prospect["last_contacted_at"] == old_ts
    assert prospect["next_followup_at"]

    timeline = client.get("/admin/instagram/prospects/demo_manual_user/timeline", headers=_admin_headers())
    assert timeline.status_code == 200
    assert any(item["kind"] == "send" and item["stage"] == "cold" for item in timeline.json()["items"])

    summary = client.get("/admin/instagram/ops-summary", headers=_admin_headers())
    assert summary.status_code == 200
    assert "totals" in summary.json()


def test_instagram_manual_contact_dedupes_username_and_followup_queue(client: TestClient):
    headers = {**_admin_headers(), "Content-Type": "application/json"}
    first = client.post(
        "/admin/instagram/manual-contact",
        headers=headers,
        json={
            "username": "Queue_User",
            "message_text": "primer contacto",
            "stage": "cold",
            "contacted_at": "2026-01-01T09:00:00+00:00",
        },
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/admin/instagram/manual-contact",
        headers=headers,
        json={
            "username": "@queue_user",
            "message_text": "follow up manual",
            "stage": "fu1",
            "contacted_at": "2026-01-07T09:00:00+00:00",
        },
    )
    assert second.status_code == 200, second.text

    listing = client.get("/admin/instagram/prospects?q=queue_user", headers=_admin_headers())
    assert listing.status_code == 200
    assert [p["username"] for p in listing.json()["items"]].count("queue_user") == 1

    queue = client.get("/admin/instagram/followup-queue?limit=20", headers=_admin_headers())
    assert queue.status_code == 200
    items = queue.json()["items"]
    target = next((item for item in items if item["username"] == "queue_user"), None)
    assert target is not None
    assert target["next_stage"] == "fu2"
    assert "suggested_message" in target


def test_instagram_igme_deep_link_encoded():
    import sys as _sys
    from pathlib import Path as _Path
    _scripts = _Path(__file__).resolve().parent.parent / "scripts"
    if str(_scripts) not in _sys.path:
        _sys.path.insert(0, str(_scripts))
    from instagram_templates import igme_deep_link  # type: ignore

    link = igme_deep_link("a_user", "hola con espacios & simbolos ?=")
    assert link.startswith("https://ig.me/m/a_user?text=")
    # Espacios escapados como %20 (quote default), no '+'
    assert "%20" in link
    assert "&" not in link.split("?text=", 1)[1]  # & del input se escapa
    # Strip arroba al inicio
    link2 = igme_deep_link("@xx", "hi")
    assert link2.startswith("https://ig.me/m/xx?text=")


# ── Sem 2: self-serve signup + Google OAuth + wizard onboarding ────────

def test_signup_creates_self_serve_user_and_session(client: TestClient, api_module):
    email = f"signup_{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "secret-pass-123",
            "display_name": "Nuevo Usuario",
            "marketing_optin": True,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["redirect_to"] == "/onboarding"
    assert data["user"]["email"] == email
    # session cookie set
    assert api_module.PORTAL_COOKIE_NAME in response.cookies
    # user is persisted with signup_source='email'
    row = api_module._get_user_by_email(email)
    assert row is not None
    assert row["signup_source"] == "email"
    assert row["google_sub"] == ""
    assert row["cliente_id"] == ""  # wizard not started yet


def test_signup_rejects_duplicate_email(client: TestClient, api_module):
    email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
    first = client.post(
        "/auth/signup",
        json={"email": email, "password": "secret-pass-123", "display_name": "Uno"},
    )
    assert first.status_code == 200
    second = client.post(
        "/auth/signup",
        json={"email": email, "password": "secret-pass-123", "display_name": "Dos"},
    )
    assert second.status_code == 409
    assert "ya tiene cuenta" in second.json()["detail"].lower()


def test_signup_disabled_when_flag_false(client: TestClient, api_module, monkeypatch):
    monkeypatch.setattr(api_module, "SIGNUP_ENABLED", False)
    response = client.post(
        "/auth/signup",
        json={"email": "blocked@example.com", "password": "secret-pass-123", "display_name": "X"},
    )
    assert response.status_code == 403


def test_google_oauth_start_503_when_not_configured(client: TestClient, api_module, monkeypatch):
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_SECRET", "")
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 503


def test_google_oauth_start_redirects_when_configured(client: TestClient, api_module, monkeypatch):
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_ID", "fake-id.apps.googleusercontent.com")
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_SECRET", "fake-secret")
    monkeypatch.setattr(api_module, "GOOGLE_REDIRECT_URI", "https://app.test/auth/google/callback")
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=fake-id.apps.googleusercontent.com" in location
    assert "state=" in location
    assert "scope=openid%20email%20profile" in location


def test_google_oauth_rejects_email_signup_account(client: TestClient, api_module, monkeypatch):
    email = f"email_google_{uuid.uuid4().hex[:8]}@example.com"
    user = api_module._create_user_self_serve(
        email=email,
        password="secret-pass-123",
        display_name="Email User",
        signup_source="email",
    )
    state = api_module._oauth_create_state(intent="login")
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_ID", "fake-id.apps.googleusercontent.com")
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_SECRET", "fake-secret")
    monkeypatch.setattr(api_module, "GOOGLE_REDIRECT_URI", "https://app.test/auth/google/callback")

    class FakeGoogleResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return FakeGoogleResponse({"access_token": "fake-access"})

        async def get(self, *args, **kwargs):
            return FakeGoogleResponse({
                "sub": "google-sub-" + uuid.uuid4().hex,
                "email": email,
                "name": "Email User",
                "picture": "",
            })

    monkeypatch.setattr(api_module.httpx, "AsyncClient", FakeAsyncClient)
    response = client.get(
        f"/auth/google/callback?code=fake-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/acceso?google_error=email_account"
    assert api_module._get_user_by_id(user["id"])["google_sub"] == ""


def _signup_and_get_cookie(client: TestClient, email: str, password: str = "secret-pass-123", name: str = "Wizard User"):
    resp = client.post(
        "/auth/signup",
        json={"email": email, "password": password, "display_name": name},
    )
    assert resp.status_code == 200, resp.text
    cookie_name = "vantelia_portal_session"
    assert cookie_name in resp.cookies, f"signup response missing {cookie_name} cookie"
    return {cookie_name: resp.cookies[cookie_name]}


def test_onboarding_state_returns_empty_for_fresh_user(client: TestClient, api_module):
    email = f"wiz_state_{uuid.uuid4().hex[:8]}@example.com"
    cookies = _signup_and_get_cookie(client, email)
    response = client.get("/onboarding/state", cookies=cookies)
    assert response.status_code == 200
    data = response.json()
    assert data["cliente_id"] == ""
    assert data["step"] == "name"


def test_onboarding_start_provisions_cliente_with_ownership(client: TestClient, api_module):
    email = f"wiz_start_{uuid.uuid4().hex[:8]}@example.com"
    cookies = _signup_and_get_cookie(client, email)
    user_before = api_module._get_user_by_email(email)
    response = client.post(
        "/onboarding/start",
        json={"nombre": "Cafeteria del Sol"},
        cookies=cookies,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    cliente_id = data["cliente_id"]
    assert cliente_id.startswith("cafeteria_del_sol")
    assert data["step"] == "learn"
    # user.cliente_id linked
    user_after = api_module._get_user_by_id(user_before["id"])
    assert user_after["cliente_id"] == cliente_id
    # clientes row owned by user
    owner = api_module.db_get_client_owner(cliente_id)
    assert owner == user_before["id"]
    # free subscription created
    sub = api_module.db_get_subscription_for_user(user_before["id"])
    assert sub is not None
    assert sub["plan"] == "free"
    # config.json + data dir provisioned
    assert cliente_id in api_module.CONFIG_CLIENTES
    info_path = Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id / "info.txt"
    assert info_path.exists()


def test_onboarding_full_wizard_flow(client: TestClient, api_module, monkeypatch):
    """name → learn → personality → finalize, end to end."""
    monkeypatch.setattr(api_module, "OPENAI_API_KEY", "sk-test-wizard")
    monkeypatch.setattr(api_module, "run_onboarding", lambda **kwargs: _FakeOnboardingResult())
    email = f"wiz_full_{uuid.uuid4().hex[:8]}@example.com"
    cookies = _signup_and_get_cookie(client, email)

    # Step name
    start = client.post(
        "/onboarding/start", json={"nombre": "Mi Negocio"}, cookies=cookies
    )
    assert start.status_code == 200
    cliente_id = start.json()["cliente_id"]

    # Step learn
    learn = client.post(
        "/onboarding/learn",
        json={"website_url": "https://cliente-auto.example", "just_this_page": True},
        cookies=cookies,
    )
    assert learn.status_code == 200, learn.text
    learn_data = learn.json()
    assert learn_data["cliente_id"] == cliente_id
    assert learn_data["detected_business_name"] == "Cliente Auto"
    assert learn_data["suggested_starters"] == []
    # info.txt got written with the scraper output
    info_path = Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id / "info.txt"
    assert "CLIENTE AUTO" in info_path.read_text(encoding="utf-8")

    # Step personality
    pers = client.post(
        "/onboarding/personality",
        json={
            "bienvenida": "Hola, te ayudo con todo.",
            "prompt_extra": "Tono cercano.",
            "starter_questions": ["Pregunta 1", "Pregunta 2"],
        },
        cookies=cookies,
    )
    assert pers.status_code == 200
    pers_data = pers.json()
    assert pers_data["bienvenida"] == "Hola, te ayudo con todo."
    assert len(pers_data["starter_questions"]) == 2
    cfg = api_module.CONFIG_CLIENTES[cliente_id]
    assert cfg["bienvenida"] == "Hola, te ayudo con todo."
    assert cfg["prompt_extra"] == "Tono cercano."

    # Step finalize
    final = client.post("/onboarding/finalize", cookies=cookies)
    assert final.status_code == 200
    final_data = final.json()
    assert final_data["cliente_id"] == cliente_id
    assert "<script" in final_data["install_snippet"]
    assert cliente_id in final_data["install_snippet"]
    assert final_data["demo_url"].endswith(f"/demo/{cliente_id}")
    assert final_data["dashboard_url"].endswith("/app")


def test_onboarding_endpoints_require_authentication(client: TestClient):
    # GET /onboarding HTML redirects to acceso
    resp = client.get("/onboarding", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "/acceso" in resp.headers["location"]
    # POST /onboarding/start without session → 401
    resp = client.post("/onboarding/start", json={"nombre": "X"})
    assert resp.status_code == 401
    # Pasos operativos y readiness tambien requieren sesion
    assert client.get("/onboarding/setup").status_code == 401
    assert client.get("/onboarding/readiness").status_code == 401
    assert client.post("/onboarding/business", json={}).status_code == 401
    assert client.post("/onboarding/booking-setup", json={}).status_code == 401
    assert client.post("/onboarding/shop", json={}).status_code == 401


def test_onboarding_business_booking_shop_readiness_flow(client: TestClient, api_module, monkeypatch):
    """Pasos operativos del wizard: Negocio → Reservas → Venta → checklist readiness."""
    monkeypatch.setattr(api_module, "OPENAI_API_KEY", "sk-test-wizard")
    monkeypatch.setattr(api_module, "run_onboarding", lambda **kwargs: _FakeOnboardingResult())
    email = f"wiz_ops_{uuid.uuid4().hex[:8]}@example.com"
    cookies = _signup_and_get_cookie(client, email)
    start = client.post("/onboarding/start", json={"nombre": "Estetica Luz"}, cookies=cookies)
    assert start.status_code == 200
    cliente_id = start.json()["cliente_id"]
    learn = client.post(
        "/onboarding/learn",
        json={"website_url": "https://cliente-auto.example", "just_this_page": True},
        cookies=cookies,
    )
    assert learn.status_code == 200, learn.text

    # learn ahora encamina al paso Negocio
    state = client.get("/onboarding/state", cookies=cookies).json()
    assert state["step"] == "business"

    # Paso Negocio
    biz = client.post(
        "/onboarding/business",
        json={
            "contact_email": "hola@estetica.example",
            "contact_phone": "+34 600 111 222",
            "sector": "Centro de estetica",
            "ciudad": "Madrid",
            "timezone": "Atlantic/Canary",
        },
        cookies=cookies,
    )
    assert biz.status_code == 200, biz.text
    assert biz.json()["step"] == "booking"
    cfg = api_module.CONFIG_CLIENTES[cliente_id]
    assert cfg["contacto"]["email"] == "hola@estetica.example"
    assert cfg["negocio"]["sector"] == "Centro de estetica"
    assert cfg["negocio"]["ciudad"] == "Madrid"
    assert cfg["booking"]["timezone"] == "Atlantic/Canary"

    # Zona horaria invalida → 400
    bad = client.post(
        "/onboarding/business", json={"timezone": "Marte/Colonia1"}, cookies=cookies
    )
    assert bad.status_code == 400

    # GET setup agregado para los pasos nuevos
    setup = client.get("/onboarding/setup", cookies=cookies)
    assert setup.status_code == 200, setup.text
    setup_data = setup.json()
    assert setup_data["cliente_id"] == cliente_id
    assert setup_data["timezone"] == "Atlantic/Canary"
    assert setup_data["contact_email"] == "hola@estetica.example"
    assert setup_data["employee_name"]
    assert setup_data["location_name"]
    assert isinstance(setup_data["services"], list)
    assert setup_data["links"]["central"].endswith(f"/central/{cliente_id}")
    assert setup_data["links"]["reservas"].endswith(f"/reservas/{cliente_id}")

    # Paso Reservas: horario general + nombres de profesional y centro
    bk = client.post(
        "/onboarding/booking-setup",
        json={
            "enabled": True,
            "day_start": "10:00",
            "day_end": "19:00",
            "slot_minutes": 15,
            "closed_weekdays": [5, 6],
            "employee_name": "Laura",
            "location_name": "Centro Madrid",
        },
        cookies=cookies,
    )
    assert bk.status_code == 200, bk.text
    assert bk.json()["step"] == "personality"
    cfg = api_module.CONFIG_CLIENTES[cliente_id]
    assert cfg["booking"]["day_start"] == "10:00"
    assert cfg["booking"]["day_end"] == "19:00"
    assert cfg["booking"]["slot_minutes"] == 15
    assert cfg["booking"]["closed_weekdays"] == [5, 6]
    with api_module._get_db_connection() as connection:
        emp = connection.execute(
            "SELECT name, day_start FROM employees WHERE cliente_id = ? AND is_default = 1",
            (cliente_id,),
        ).fetchone()
        loc = connection.execute(
            "SELECT name FROM locations WHERE cliente_id = ? AND is_default = 1",
            (cliente_id,),
        ).fetchone()
    assert emp is not None and emp["name"] == "Laura"
    assert emp["day_start"] == "10:00"  # horario sincronizado al profesional por defecto
    assert loc is not None and loc["name"] == "Centro Madrid"

    # Paso Venta: opt-in tienda + tarjetas regalo
    shop = client.post(
        "/onboarding/shop",
        json={"enabled_packages": True, "gift_enabled": True},
        cookies=cookies,
    )
    assert shop.status_code == 200, shop.text
    cfg = api_module.CONFIG_CLIENTES[cliente_id]
    assert cfg["shop_public"]["enabled_packages"] is True
    assert cfg["gift_cards_public"]["enabled"] is True

    # Readiness: semaforos por bloque
    ready = client.get("/onboarding/readiness", cookies=cookies)
    assert ready.status_code == 200, ready.text
    data = ready.json()
    blocks = {b["key"]: b for b in data["blocks"]}
    assert set(blocks) == {
        "knowledge", "services", "booking", "payments", "email",
        "shop", "whatsapp", "voice", "public_links",
    }
    assert blocks["public_links"]["status"] == "ready"
    assert blocks["booking"]["status"] == "ready"
    assert blocks["payments"]["status"] == "pending"  # sin Stripe Connect
    assert blocks["shop"]["status"] == "action"  # opt-in activado pero sin Stripe
    assert blocks["whatsapp"]["status"] == "not_in_plan"  # plan free
    assert blocks["voice"]["status"] == "not_in_plan"
    assert data["links"]["tienda"].endswith(f"/tienda/{cliente_id}")
    assert data["links"]["gift"].endswith(f"/gift/{cliente_id}")


# ── Sem 3: dashboard nuevo /auth/app/* ─────────────────────────────────

def _signup_and_wizard(client: TestClient, api_module, monkeypatch, *, name="Mi Bot 3"):
    monkeypatch.setattr(api_module, "OPENAI_API_KEY", "sk-test-app")
    monkeypatch.setattr(api_module, "run_onboarding", lambda **kwargs: _FakeOnboardingResult())
    email = f"app_{uuid.uuid4().hex[:8]}@example.com"
    cookies = _signup_and_get_cookie(client, email)
    start = client.post("/onboarding/start", json={"nombre": name}, cookies=cookies)
    assert start.status_code == 200
    cliente_id = start.json()["cliente_id"]
    learn = client.post(
        "/onboarding/learn",
        json={"website_url": "https://cliente-auto.example", "just_this_page": True},
        cookies=cookies,
    )
    assert learn.status_code == 200, learn.text
    return cookies, cliente_id, email


def test_app_overview_returns_stats_for_self_serve_user(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch)
    resp = client.get("/auth/app/overview", cookies=cookies)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["cliente_id"] == cliente_id
    assert data["subscription"]["plan"] == "free"
    assert data["subscription"]["messages_quota"] >= 1
    assert "users_today" in data["stats"]
    assert "training_chars" in data["stats"]
    # training_chars > 0 because the fake onboarding wrote info.txt
    assert data["stats"]["training_chars"] > 0


def test_self_service_funnel_tracks_activation_and_install(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Funnel")
    landing = client.post(
        "/analytics/event",
        json={
            "event": "landing_view",
            "event_source": "vantelia_site",
            "page_path": "/",
            "page_url": "https://www.vantelia.es/",
            "session_id": f"s_{uuid.uuid4().hex[:16]}",
            "page_type": "home",
        },
    )
    pricing = client.post(
        "/analytics/event",
        json={
            "event": "pricing_viewed",
            "event_source": "vantelia_site",
            "page_path": "/planes/",
            "page_url": "https://www.vantelia.es/planes/",
            "session_id": f"s_{uuid.uuid4().hex[:16]}",
        },
    )
    site_click = client.post(
        "/analytics/event",
        json={
            "event": "signup_clicked",
            "event_source": "vantelia_site",
            "page_path": "/planes/",
            "page_url": "https://www.vantelia.es/planes/",
            "cta_href": "https://app.vantelia.es/acceso?signup=1",
            "source": "pytest",
        },
    )
    preview = client.post(
        "/auth/app/track",
        cookies=cookies,
        json={"event": "bot_preview_message", "metadata": {"surface": "right_panel_preview", "message_length": 14}},
    )
    snippet = client.post(
        "/auth/app/track",
        cookies=cookies,
        json={"event": "snippet_copied", "metadata": {"surface": "deploy"}},
    )
    first_chat = client.post(
        "/auth/app/track",
        cookies=cookies,
        json={"event": "first_chat_tested", "metadata": {"surface": "right_panel_preview", "message_length": 14}},
    )
    upgrade = client.post(
        "/auth/app/track",
        cookies=cookies,
        json={"event": "upgrade_clicked", "metadata": {"surface": "billing", "plan": "pro", "billing_period": "monthly"}},
    )
    dashboard = client.get("/admin/self-service-funnel?days=30", headers=_admin_headers())

    assert landing.status_code == 200
    assert pricing.status_code == 200
    assert site_click.status_code == 200
    assert preview.status_code == 200
    assert snippet.status_code == 200
    assert first_chat.status_code == 200
    assert upgrade.status_code == 200
    assert dashboard.status_code == 200, dashboard.text
    payload = dashboard.json()
    assert payload["tracking"]["landing_view"] is True
    assert payload["tracking"]["signup_clicked"] is True
    assert payload["tracking"]["signup_completed"] is True
    assert payload["tracking"]["bot_created"] is True
    assert payload["tracking"]["first_chat_tested"] is True
    assert payload["tracking"]["pricing_viewed"] is True
    assert payload["tracking"]["upgrade_clicked"] is True
    assert payload["kpis"]["free_bot_clicks"] >= 1
    assert payload["kpis"]["signups"] >= 1
    assert payload["kpis"]["bots_created"] >= 1
    assert payload["kpis"]["activated_bots"] >= 1
    assert payload["kpis"]["snippet_copied"] >= 1
    assert any(step["key"] == "snippet_copied" for step in payload["funnel"])
    assert any(item["cliente_id"] == cliente_id for item in payload["recent_bots"])


def test_app_overview_400_when_no_cliente(client: TestClient, api_module):
    email = f"app_nobot_{uuid.uuid4().hex[:8]}@example.com"
    cookies = _signup_and_get_cookie(client, email)
    resp = client.get("/auth/app/overview", cookies=cookies)
    assert resp.status_code == 400


def test_app_deploy_returns_snippet_and_share_link(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Deploy")
    resp = client.get("/auth/app/deploy", cookies=cookies)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["cliente_id"] == cliente_id
    assert "<script" in data["install_snippet"]
    assert cliente_id in data["install_snippet"]
    assert data["share_link"].endswith(f"/demo/{cliente_id}")


def test_app_appearance_get_and_update(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Apariencia")
    initial = client.get("/auth/app/appearance", cookies=cookies)
    assert initial.status_code == 200
    initial_data = initial.json()
    assert initial_data["cliente_id"] == cliente_id
    assert initial_data["starter_questions"] == []

    update = client.post(
        "/auth/app/appearance",
        json={
            "nombre": "Bot Renovado",
            "color": "#aabbcc",
            "icono": "BR",
            "bienvenida": "Hola hola.",
            "prompt_extra": "Tono breve.",
            "starter_questions": ["Una", "Dos"],
            "allowed_origins": ["https://miweb.com", "https://miweb.com"],  # dedupe
        },
        cookies=cookies,
    )
    assert update.status_code == 200, update.text
    updated = update.json()
    assert updated["nombre"] == "Bot Renovado"
    assert updated["color"] == "#aabbcc"
    assert updated["icono"] == "BR"
    assert updated["bienvenida"] == "Hola hola."
    assert updated["starter_questions"] == ["Una", "Dos"]
    assert updated["allowed_origins"] == ["https://miweb.com"]

    cfg = api_module.CONFIG_CLIENTES[cliente_id]
    assert cfg["nombre"] == "Bot Renovado"
    assert cfg["color"] == "#aabbcc"
    assert cfg["bienvenida"] == "Hola hola."


def test_app_appearance_rejects_bad_color(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Color")
    cfg_before = dict(api_module.CONFIG_CLIENTES[cliente_id])
    # 7-char string but not a valid hex (#zzzzzz) → endpoint should silently keep prior color.
    resp = client.post(
        "/auth/app/appearance",
        json={"color": "#zzzzzz"},
        cookies=cookies,
    )
    assert resp.status_code == 200, resp.text
    cfg_after = api_module.CONFIG_CLIENTES[cliente_id]
    assert cfg_after["color"] == cfg_before["color"]


def test_app_entry_redirects_when_no_cliente(client: TestClient, api_module):
    email = f"app_entry_{uuid.uuid4().hex[:8]}@example.com"
    cookies = _signup_and_get_cookie(client, email)
    resp = client.get("/app", cookies=cookies, follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "/onboarding" in resp.headers["location"]


# ── Sem 4: Leads / Q&A / Knowledge / Tune AI / Live Chat ──────────────

def test_app_leads_crud_and_export(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Leads")
    # initial list empty
    resp = client.get("/auth/app/leads", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    # create
    created = client.post(
        "/auth/app/leads",
        json={"name": "Ana Pruebas", "email": "ana@test.com", "phone": "+34600111222", "message": "Quiero info"},
        cookies=cookies,
    )
    assert created.status_code == 200, created.text
    lead_id = created.json()["id"]
    assert created.json()["email"] == "ana@test.com"

    # list shows it
    listed = client.get("/auth/app/leads", cookies=cookies).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == lead_id

    # search filter
    found = client.get("/auth/app/leads?q=ana", cookies=cookies).json()
    assert found["total"] == 1
    notfound = client.get("/auth/app/leads?q=zzznoexiste", cookies=cookies).json()
    assert notfound["total"] == 0

    # export csv
    export = client.get("/auth/app/leads/export.csv", cookies=cookies)
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    assert "ana@test.com" in export.text

    # delete
    deleted = client.delete(f"/auth/app/leads/{lead_id}", cookies=cookies)
    assert deleted.status_code == 200
    assert client.get("/auth/app/leads", cookies=cookies).json()["total"] == 0

    # delete non-existent → 404
    missing = client.delete("/auth/app/leads/lead_nope", cookies=cookies)
    assert missing.status_code == 404


def test_app_leads_rejects_empty_payload(client: TestClient, api_module, monkeypatch):
    cookies, _, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot LeadsEmpty")
    resp = client.post("/auth/app/leads", json={}, cookies=cookies)
    assert resp.status_code == 400


def test_app_qa_crud_persists_in_info_txt(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot QA")
    info_path = Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id / "info.txt"

    # create
    resp = client.post(
        "/auth/app/qa",
        json={"question": "¿Hacen envíos a Canarias?", "answer": "Sí, en 3-5 días laborables.", "tags": ["envios", "canarias"]},
        cookies=cookies,
    )
    assert resp.status_code == 200, resp.text
    qa_id = resp.json()["id"]
    assert resp.json()["tags"] == ["envios", "canarias"]
    # info.txt now contains the FAQ block
    content = info_path.read_text(encoding="utf-8")
    assert "PREGUNTAS FRECUENTES (PANEL)" in content
    assert "Canarias" in content

    # patch
    patched = client.patch(
        f"/auth/app/qa/{qa_id}",
        json={"answer": "Sí, 2-4 días.", "tags": ["envios"]},
        cookies=cookies,
    )
    assert patched.status_code == 200
    assert patched.json()["answer"] == "Sí, 2-4 días."
    assert patched.json()["tags"] == ["envios"]
    assert "2-4 días" in info_path.read_text(encoding="utf-8")

    # list
    listed = client.get("/auth/app/qa", cookies=cookies).json()
    assert listed["total"] == 1

    # delete
    client.delete(f"/auth/app/qa/{qa_id}", cookies=cookies).status_code == 200
    assert "PREGUNTAS FRECUENTES (PANEL)" not in info_path.read_text(encoding="utf-8")


def test_chat_faq_uses_panel_qa_and_caps_four(client: TestClient, api_module):
    qa_ids = [f"qa_test_faq_{i}_{uuid.uuid4().hex}" for i in range(5)]
    with api_module._get_db_connection() as connection:
        for i, qa_id in enumerate(qa_ids):
            created_at = (datetime(2026, 1, 1) + timedelta(seconds=i)).isoformat()
            connection.execute(
                """
                INSERT INTO kb_qa (id, cliente_id, question, answer, tags_json, created_at, updated_at, created_by_user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    qa_id,
                    "demo",
                    f"Pregunta frecuente {i + 1}?",
                    f"Respuesta frecuente {i + 1}.",
                    "[]",
                    created_at,
                    created_at,
                    "",
                ),
            )
        connection.commit()
    try:
        response = client.post(
            "/chat",
            json={
                "cliente_id": "demo",
                "mensaje": "Muestrame las preguntas frecuentes principales",
                "session_id": "s_test_chat_faq_panel",
            },
            headers={"Origin": "http://testserver"},
        )
    finally:
        with api_module._get_db_connection() as connection:
            connection.execute(
                f"DELETE FROM kb_qa WHERE id IN ({','.join('?' for _ in qa_ids)})",
                qa_ids,
            )
            connection.commit()

    assert response.status_code == 200, response.text
    text = response.json()["respuesta"]
    assert text.count("Pregunta frecuente") == 4
    assert "Pregunta frecuente 5?" in text
    assert "Pregunta frecuente 2?" in text
    assert "Pregunta frecuente 1?" not in text


def test_app_knowledge_text_appended_to_info(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot KB")
    info_path = Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id / "info.txt"
    before = info_path.read_text(encoding="utf-8")

    resp = client.post(
        "/auth/app/knowledge/text",
        json={"title": "Política de devoluciones", "content": "Aceptamos devoluciones hasta 30 días desde la compra."},
        cookies=cookies,
    )
    assert resp.status_code == 200, resp.text
    after = info_path.read_text(encoding="utf-8")
    assert "Política de devoluciones" in after
    assert "AÑADIDO DESDE PANEL" in after
    assert len(after) > len(before)

    listed = client.get("/auth/app/knowledge", cookies=cookies).json()
    assert listed["info_chars"] == len(after)
    assert any(it["source"] == "text" for it in listed["items"])


def test_app_knowledge_url_invokes_scraper(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot KB URL")
    # _signup_and_wizard already patched run_onboarding; reuse the fake.
    info_path = Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id / "info.txt"
    before = info_path.read_text(encoding="utf-8")
    resp = client.post(
        "/auth/app/knowledge/url",
        json={"url": "https://otra.example", "just_this_page": True, "replace": False},
        cookies=cookies,
    )
    assert resp.status_code == 200, resp.text
    after = info_path.read_text(encoding="utf-8")
    assert "Web: https://otra.example" in after
    assert len(after) > len(before)

    duplicate = client.post(
        "/auth/app/knowledge/url",
        json={"url": "https://otra.example/", "just_this_page": True, "replace": False},
        cookies=cookies,
    )
    assert duplicate.status_code == 409


def test_app_knowledge_url_caps_derived_auto_qa(client: TestClient, api_module, monkeypatch):
    cookies, _, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot KB QA Cap")

    class ManyDerivedFaqResult(_FakeOnboardingResult):
        normalized_url = "https://faq-cap.example"
        faq_source = "derived"
        faq_pairs = [
            (f"Pregunta derivada {idx}?", f"Respuesta derivada {idx}.")
            for idx in range(25)
        ]

    monkeypatch.setattr(api_module, "run_onboarding", lambda **kwargs: ManyDerivedFaqResult())
    resp = client.post(
        "/auth/app/knowledge/url",
        json={"url": "https://faq-cap.example", "just_this_page": True, "replace": False},
        cookies=cookies,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["qa_created"] == 5
    listed = client.get("/auth/app/qa", cookies=cookies)
    assert listed.status_code == 200
    assert listed.json()["total"] == 5


def test_app_knowledge_url_caps_literal_auto_qa(client: TestClient, api_module, monkeypatch):
    cookies, _, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot KB QA Literal")

    class LiteralFaqResult(_FakeOnboardingResult):
        normalized_url = "https://faq-literal.example"
        faq_source = "literal"
        faq_pairs = [
            (f"Pregunta literal {idx}?", f"Respuesta literal {idx}.")
            for idx in range(12)
        ]

    monkeypatch.setattr(api_module, "run_onboarding", lambda **kwargs: LiteralFaqResult())
    resp = client.post(
        "/auth/app/knowledge/url",
        json={"url": "https://faq-literal.example", "just_this_page": True, "replace": False},
        cookies=cookies,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["qa_created"] == 5


def test_app_tune_get_and_post(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Tune")
    initial = client.get("/auth/app/tune", cookies=cookies).json()
    assert "gpt-4o-mini" in initial["available_models"]
    assert 0.0 <= initial["temperature"] <= 2.0

    updated = client.post(
        "/auth/app/tune",
        json={"prompt_extra": "Sé conciso.", "chat_model": "gpt-4o", "temperature": 0.7},
        cookies=cookies,
    )
    assert updated.status_code == 200, updated.text
    data = updated.json()
    assert data["prompt_extra"] == "Sé conciso."
    assert data["chat_model"] == "gpt-4o"
    assert abs(data["temperature"] - 0.7) < 1e-6
    # config.json reflects the change
    cfg = api_module.CONFIG_CLIENTES[cliente_id]
    assert cfg["chat_model"] == "gpt-4o"
    assert abs(cfg["temperature"] - 0.7) < 1e-6

    # invalid model is silently ignored (no crash)
    silent = client.post(
        "/auth/app/tune",
        json={"chat_model": "fake-model-9000"},
        cookies=cookies,
    )
    assert silent.status_code == 200
    assert silent.json()["chat_model"] == "gpt-4o"  # unchanged


def test_app_services_update_rewrites_info_txt(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Services")

    initial = client.get("/auth/app/services", cookies=cookies)
    assert initial.status_code == 200
    assert initial.json()["items"]

    updated = client.post(
        "/auth/app/services",
        cookies=cookies,
        json={
            "items": [
                {"nombre": "Consultoria IA", "descripcion": "Diagnostico y plan de accion."},
                {"nombre": "Automatizacion CRM", "descripcion": "Flujos de captacion y seguimiento."},
            ]
        },
    )

    assert updated.status_code == 200, updated.text
    names = [item["nombre"] for item in updated.json()["items"]]
    assert names == ["Consultoria IA", "Automatizacion CRM"]
    info_txt = api_module._read_info_txt(cliente_id)
    assert "SERVICIOS Y PRECIOS:" in info_txt
    assert "- Servicio: Consultoria IA" in info_txt
    assert "Diagnostico y plan de accion." in info_txt

    public_services = api_module._public_services_for_booking(cliente_id, "")
    assert [item["nombre"] for item in public_services] == names


def test_message_templates_preview_and_partial_save(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Messages")

    schedule = client.get("/auth/schedule", cookies=cookies)
    assert schedule.status_code == 200
    assert all(schedule.json()["message_template_enabled"].values())
    assert schedule.json()["message_template_channels"]["confirmed"]["email"] is True
    assert schedule.json()["message_template_channels"]["reminder_24h"]["email"] is True
    assert schedule.json()["reminder_channel_availability"]["email"]["available"] is True
    assert schedule.json()["closed_weekdays"] == [6]

    saved = client.post(
        "/auth/schedule",
        cookies=cookies,
        json={
            "message_templates": {"confirmed": "Texto confirmado desde mensajes."},
            "message_template_channels": {
                "confirmed": {"email": True, "whatsapp": True, "sms": True},
                "reminder_24h": {"email": True, "whatsapp": True, "sms": True},
                "reminder_2h": {"email": False, "whatsapp": True, "sms": True},
                "cancelled": {"email": True, "whatsapp": True, "sms": True},
                "rescheduled": {"email": True, "whatsapp": True, "sms": True},
            },
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["closed_weekdays"] == [6]
    assert all(saved.json()["message_template_enabled"].values())
    assert saved.json()["message_template_channels"]["reminder_24h"] == {
        "email": True,
        "whatsapp": False,
        "sms": False,
    }
    assert saved.json()["message_template_channels"]["reminder_2h"] == {
        "email": False,
        "whatsapp": False,
        "sms": False,
    }
    assert saved.json()["message_template_channels"]["confirmed"] == {
        "email": True,
        "whatsapp": False,
        "sms": False,
    }
    assert saved.json()["message_template_channels"]["cancelled"]["whatsapp"] is False
    assert saved.json()["message_template_channels"]["rescheduled"]["sms"] is False

    preview = client.post(
        "/auth/schedule/message-preview",
        cookies=cookies,
        json={"template_key": "confirmacion", "content": "Texto legacy para preview."},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["kind"] == "confirmed"
    assert "Texto legacy para preview." in preview.json()["text_body"]


def test_app_whatsapp_settings_and_plan_gate(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, email = _signup_and_wizard(client, api_module, monkeypatch, name="Bot WhatsApp")
    user = api_module._get_user_by_email(email)
    assert user is not None

    initial = client.get("/auth/app/whatsapp", cookies=cookies)
    assert initial.status_code == 200
    assert initial.json()["enabled"] is False
    assert initial.json()["webhook_url"].endswith(f"/whatsapp/webhook/{cliente_id}")
    assert initial.json()["verify_token"] == "test-whatsapp-token"

    saved_disabled = client.post(
        "/auth/app/whatsapp",
        cookies=cookies,
        json={
            "enabled": False,
            "phone_number_id": "999123",
            "access_token_env": "WHATSAPP_ACCESS_TOKEN_TEST",
            "verify_token_env": "",
        },
    )
    assert saved_disabled.status_code == 200, saved_disabled.text
    assert saved_disabled.json()["phone_number_id"] == "999123"
    assert saved_disabled.json()["enabled"] is False

    blocked = client.post(
        "/auth/app/whatsapp",
        cookies=cookies,
        json={"enabled": True, "phone_number_id": "999123"},
    )
    assert blocked.status_code == 403

    with api_module._get_db_connection() as connection:
        connection.execute(
            "UPDATE subscriptions SET plan = 'business', messages_quota = 25000 WHERE user_id = ?",
            (user["id"],),
        )
        connection.commit()

    enabled = client.post(
        "/auth/app/whatsapp",
        cookies=cookies,
        json={"enabled": True, "phone_number_id": "999123"},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["enabled"] is True
    assert enabled.json()["plan_allows_whatsapp"] is True
    assert api_module.CONFIG_CLIENTES[cliente_id]["whatsapp"]["enabled"] is True


def test_app_voice_settings_plan_gate_and_session(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, email = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Voz")
    user = api_module._get_user_by_email(email)
    assert user is not None

    # El panel debe permitir el microfono (self) para la prueba de voz por navegador.
    panel = client.get("/app", cookies=cookies)
    assert panel.status_code == 200
    assert "microphone=(self)" in panel.headers.get("Permissions-Policy", "")

    initial = client.get("/auth/app/voice", cookies=cookies)
    assert initial.status_code == 200
    assert initial.json()["enabled"] is False
    assert initial.json()["plan_allows_voice"] is False
    assert initial.json()["webhook_url"].endswith(f"/voice/{cliente_id}")

    saved = client.post(
        "/auth/app/voice",
        cookies=cookies,
        json={"enabled": False, "openai_voice": "verse"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["openai_voice"] == "verse"
    # Un solo agente (web/WhatsApp/voz): la voz no tiene nombre ni saludo propios.
    assert "name" not in saved.json()
    assert "greeting" not in saved.json()

    # Activar y probar en navegador estan gated a Business.
    assert client.post("/auth/app/voice", cookies=cookies, json={"enabled": True}).status_code == 403
    assert client.post("/auth/app/voice/session", cookies=cookies).status_code == 403

    with api_module._get_db_connection() as connection:
        connection.execute(
            "UPDATE subscriptions SET plan = 'business', messages_quota = 25000 WHERE user_id = ?",
            (user["id"],),
        )
        connection.commit()

    enabled = client.post("/auth/app/voice", cookies=cookies, json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["enabled"] is True
    assert enabled.json()["plan_allows_voice"] is True
    assert api_module.CONFIG_CLIENTES[cliente_id]["voice"]["enabled"] is True
    assert api_module.CONFIG_CLIENTES[cliente_id]["voice"]["openai_voice"] == "verse"

    logged = client.post(
        "/auth/app/voice/log",
        cookies=cookies,
        json={
            "duration_seconds": 12,
            "transcript": [
                {"role": "assistant", "text": "Hola, soy el asistente.", "ts": "2026-06-24T10:00:00Z"},
                {"role": "user", "text": "Quiero probar una llamada.", "ts": "2026-06-24T10:00:02Z"},
            ],
        },
    )
    assert logged.status_code == 200, logged.text
    call_sid = logged.json()["call_sid"]
    with api_module._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * "
            "FROM voice_calls WHERE call_sid=?",
            (call_sid,),
        ).fetchone()
        assert row is not None
        assert row["cliente_id"] == cliente_id
        assert row["duration_seconds"] == 12
        assert row["status"] == "completed"
        assert row["direction"] == "inbound"
        assert row["purpose"] == "app_test"
        stored_transcript = json.loads(row["transcript_json"])
        assert stored_transcript[0]["role"] == "assistant"
        assert stored_transcript[1]["text"] == "Quiero probar una llamada."
        conversation = api_module._voice_conversation_dict(row)
        assert conversation["contact"] == "Prueba del panel"
        assert conversation["intents"] == ["prueba"]
        connection.execute("DELETE FROM voice_calls WHERE call_sid=?", (call_sid,))
        connection.commit()

    # Con plan Business pero sin OPENAI_API_KEY -> 503: no se mintea token real.
    monkeypatch.setattr(api_module, "OPENAI_API_KEY", "")
    assert client.post("/auth/app/voice/session", cookies=cookies).status_code == 503


def test_voice_uses_shared_identity_and_greeting(api_module):
    # La config de voz ya no guarda nombre ni saludo propios (un solo agente).
    norm = api_module._normalize_voice_config({"openai_voice": "verse", "name": "X"})
    assert "name" not in norm
    assert norm["openai_voice"] == "verse"
    # El saludo de voz sale de la bienvenida de Apariencia (mismo agente que web/WhatsApp).
    greeting = api_module._voice_default_greeting(
        {"nombre": "MG Clinic", "bienvenida": "Hola, MG Clinic al habla."}, {}
    )
    assert greeting == "Hola, MG Clinic al habla."


def test_voice_instructions_resume_after_interruption_without_repeating(api_module):
    instructions = api_module._voice_build_instructions("demo", api_module.CONFIG_CLIENTES["demo"]).lower()

    assert "no reinicies ni repitas la frase desde el principio" in instructions
    assert "retoma desde la siguiente idea" in instructions


def test_app_livechat_402_when_free_plan(client: TestClient, api_module, monkeypatch):
    cookies, _, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Free")
    resp = client.get("/auth/app/livechat", cookies=cookies)
    assert resp.status_code == 402
    assert "pro" in resp.json()["detail"].lower()


# ── Sem 5: Billing (Stripe + quota enforcement) ────────────────────────

def test_app_billing_state_defaults_to_free_plan(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Billing")
    resp = client.get("/auth/app/billing", cookies=cookies)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["subscription"]["plan"] == "free"
    assert data["subscription"]["status"] == "active"
    plan_slugs = [p["slug"] for p in data["plans"]]
    assert plan_slugs == ["free", "starter", "pro", "business"]
    free_plan = next(p for p in data["plans"] if p["slug"] == "free")
    assert free_plan["is_current"] is True
    assert data["portal_available"] is False


def test_app_stripe_connect_requires_authentication(client: TestClient):
    assert client.get("/auth/app/stripe-connect").status_code == 401
    assert client.post("/auth/app/stripe-connect/start").status_code == 401


def test_app_stripe_connect_state_defaults_to_not_connected(client: TestClient, api_module, monkeypatch):
    cookies, _, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Connect State")
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test_connect")
    resp = client.get("/auth/app/stripe-connect", cookies=cookies)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "configured": True,
        "connected": False,
        "stripe_account_id": "",
        "status": "not_connected",
        "requirements_due": 0,
        "last_error": "",
    }


def test_app_stripe_connect_start_creates_and_reuses_account(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, email = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Connect Start")
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test_connect")
    calls = []

    def fake_connect_request(method, path, *, payload=None):
        calls.append((method, path, payload))
        if path == "/accounts":
            assert payload["contact_email"] == email
            assert payload["identity"]["country"] == "es"
            assert payload["configuration"]["merchant"]["capabilities"]["card_payments"]["requested"] is True
            return {"id": "acct_connect_test", "configuration": {"merchant": {}}, "requirements": {"entries": []}}
        assert path == "/account_links"
        assert payload["account"] == "acct_connect_test"
        return {"url": "https://connect.stripe.test/onboarding"}

    monkeypatch.setattr(api_module, "_stripe_connect_request", fake_connect_request)
    first = client.post("/auth/app/stripe-connect/start", cookies=cookies)
    second = client.post("/auth/app/stripe-connect/start", cookies=cookies)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["onboarding_url"] == "https://connect.stripe.test/onboarding"
    assert [path for _, path, _ in calls].count("/accounts") == 1
    row = api_module._stripe_connected_account_row(cliente_id)
    assert row["stripe_account_id"] == "acct_connect_test"


def test_stripe_connect_display_name_falls_back_when_runtime_config_is_missing(api_module):
    cliente_id = "stripe_connect_legacy"
    now_iso = api_module._utc_now_iso()
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO clientes
                (cliente_id, owner_user_id, plan, nombre, website_url,
                 config_json, created_at, updated_at, source)
            VALUES (?, '', 'free', ?, '', '{}', ?, ?, 'legacy')
            """,
            (cliente_id, "Negocio legado", now_iso, now_iso),
        )
        connection.commit()
    assert cliente_id not in api_module.CONFIG_CLIENTES
    assert api_module._stripe_connect_display_name(cliente_id) == "Negocio legado"


def test_app_stripe_connect_state_syncs_active_account(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Connect Active")
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test_connect")
    owner_id = api_module.db_get_client_owner(cliente_id)
    api_module._save_stripe_connected_account(cliente_id, owner_id, "acct_active_test")
    requested_paths = []

    def fake_connect_request(method, path, payload=None):
        requested_paths.append(path)
        return {
            "id": "acct_active_test",
            "configuration": {
                "merchant": {
                    "capabilities": {
                        "card_payments": {"status": "active"},
                    },
                },
            },
            "requirements": {"entries": []},
        }

    monkeypatch.setattr(api_module, "_stripe_connect_request", fake_connect_request)
    resp = client.get("/auth/app/stripe-connect", cookies=cookies)
    assert resp.status_code == 200, resp.text
    assert resp.json()["connected"] is True
    assert resp.json()["status"] == "active"
    assert requested_paths == [
        "/accounts/acct_active_test?include[0]=configuration.merchant&include[1]=requirements"
    ]


def test_app_billing_checkout_503_when_stripe_not_configured(client: TestClient, api_module, monkeypatch):
    cookies, _, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Stripe")
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "")
    resp = client.post(
        "/auth/app/billing/checkout",
        json={"plan": "pro", "billing_period": "monthly"},
        cookies=cookies,
    )
    assert resp.status_code == 503


def test_app_billing_checkout_400_for_free_plan(client: TestClient, api_module, monkeypatch):
    cookies, _, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot StripeFree")
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    resp = client.post(
        "/auth/app/billing/checkout",
        json={"plan": "free"},
        cookies=cookies,
    )
    assert resp.status_code == 400


def test_app_billing_checkout_creates_stripe_session(client: TestClient, api_module, monkeypatch):
    cookies, _, email = _signup_and_wizard(client, api_module, monkeypatch, name="Bot StripeOK")
    monkeypatch.setattr(api_module, "stripe", _FakeStripe)
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test_real")
    # Plan needs a Stripe price id configured
    api_module.SELF_SERVE_PLANS["pro"]["stripe_price_monthly"] = "price_test_pro_monthly"
    try:
        resp = client.post(
            "/auth/app/billing/checkout",
            json={"plan": "pro", "billing_period": "monthly"},
            cookies=cookies,
            headers={"X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["checkout_url"].startswith("https://checkout.stripe.test/")
        sent = _FakeStripeSessionApi.last_create_payload or {}
        assert sent["mode"] == "subscription"
        assert sent["line_items"][0]["price"] == "price_test_pro_monthly"
        assert sent["metadata"]["source"] == "self_serve"
        assert sent["metadata"]["plan"] == "pro"
        assert sent["client_reference_id"].startswith("self_serve:usr_")
        assert sent["success_url"].startswith("https://app.test.local/")
        assert sent["cancel_url"].startswith("https://app.test.local/")
        with api_module._get_db_connection() as connection:
            rows = connection.execute(
                "SELECT event_name FROM analytics_events WHERE event_name IN ('checkout_started','upgrade_started')"
            ).fetchall()
        assert {row["event_name"] for row in rows} >= {"checkout_started", "upgrade_started"}
    finally:
        api_module.SELF_SERVE_PLANS["pro"]["stripe_price_monthly"] = ""


def test_stripe_webhook_activates_self_serve_subscription(client: TestClient, api_module, monkeypatch):
    cookies, _, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot WebhookSS")
    monkeypatch.setattr(api_module, "stripe", _FakeStripe)
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test_real")
    monkeypatch.setattr(api_module, "STRIPE_WEBHOOK_SECRET", "whsec_test_dummy")
    # Look up the user id we just signed up.
    state = client.get("/onboarding/state", cookies=cookies).json()
    user_row = api_module._get_user_by_id(
        api_module._get_user_by_email.__wrapped__(api_module, state["cliente_id"]) if False else None
    ) if False else None
    # Easier: lookup by cliente_id → owner
    owner_id = api_module.db_get_client_owner(state["cliente_id"])
    assert owner_id

    payload = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_selfserve_001",
                "customer": "cus_selfserve_001",
                "subscription": "sub_selfserve_001",
                "client_reference_id": f"self_serve:{owner_id}",
                "metadata": {
                    "source": "self_serve",
                    "user_id": owner_id,
                    "plan": "pro",
                    "billing_period": "monthly",
                },
            }
        },
    }
    response = client.post(
        "/webhooks/stripe",
        headers={"stripe-signature": "t=1,v1=test"},
        json=payload,
    )
    assert response.status_code == 200
    assert response.json()["received"] is True

    sub = api_module.db_get_subscription_for_user(owner_id)
    assert sub is not None
    assert sub["plan"] == "pro"
    assert sub["status"] == "active"
    assert sub["stripe_customer_id"] == "cus_selfserve_001"
    assert sub["stripe_subscription_id"] == "sub_selfserve_001"
    # Pro plan quota
    assert sub["messages_quota"] == api_module.SELF_SERVE_PLANS["pro"]["messages_quota"]


def test_chat_enforces_self_serve_quota(client: TestClient, api_module, monkeypatch):
    cookies, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Quota")
    owner_id = api_module.db_get_client_owner(cliente_id)
    sub = api_module.db_get_subscription_for_user(owner_id)
    # Force the free quota to 0 so the very first /chat call is blocked.
    with api_module._get_db_connection() as conn:
        conn.execute(
            "UPDATE subscriptions SET messages_quota = 1, messages_used_period = 1 WHERE id = ?",
            (sub["id"],),
        )
        conn.commit()
    # Add origin to allowed_origins so /chat passes CORS check.
    api_module.CONFIG_CLIENTES[cliente_id].setdefault("allowed_origins", []).append("http://testserver")
    resp = client.post(
        "/chat",
        json={"cliente_id": cliente_id, "session_id": "s_quota_test1234567", "mensaje": "hola"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 402
    assert "limite" in resp.json()["detail"].lower() or "límite" in resp.json()["detail"].lower()


# ── Sem 6: Bridge captacion (claim) + migracion legacy ─────────────────

def test_self_serve_free_plan_exposes_booking_with_ten_booking_quota(client: TestClient, api_module, monkeypatch):
    _, cliente_id, _ = _signup_and_wizard(client, api_module, monkeypatch, name="Bot Free Booking")
    api_module.CONFIG_CLIENTES[cliente_id].setdefault("allowed_origins", []).append("http://testserver")
    api_module.CONFIG_CLIENTES[cliente_id].setdefault("booking", {})["enabled"] = True

    config_resp = client.get(f"/cliente/{cliente_id}", headers={"Origin": "http://testserver"})
    assert config_resp.status_code == 200, config_resp.text
    config_data = config_resp.json()
    assert config_data["booking_enabled"] is True
    assert "Agendar cita" in config_data["starter_questions"]
    assert api_module._plan_limits("free")["monthly_bookings"] == 10


def _create_demo_tenant_for_test(api_module, suffix: str = "claimme") -> str:
    """Provision a demo_auto_* cliente in CONFIG_CLIENTES + demo_tenants.json,
    matching what /demo/generate would have created at outreach time. Returns
    the cliente_id."""
    cliente_id = f"{api_module.DEMO_TENANT_PREFIX}{suffix}_{uuid.uuid4().hex[:6]}"
    # Add a minimal normalized config so _get_client_config works.
    normalized = api_module._normalize_client_config(cliente_id, {
        "nombre": f"Demo {suffix}",
        "color": "#00b1d9",
        "icono": "AI",
        "bienvenida": "Hola, demo.",
        "allowed_origins": [],
        "contacto": {"email": "lead@test.example"},
        "booking": {"enabled": False},
        "whatsapp": {"enabled": False},
    })
    with api_module.state_lock:
        next_configs = dict(api_module.CONFIG_CLIENTES)
        next_configs[cliente_id] = normalized
        api_module._update_runtime_configs(next_configs)
    api_module._persist_configs_to_disk(next_configs)
    api_module._register_demo_tenant(cliente_id)
    # Ensure data dir exists
    (Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id).mkdir(parents=True, exist_ok=True)
    (Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id / "info.txt").write_text("demo", encoding="utf-8")
    return cliente_id


def test_signup_claim_transfers_ownership_of_demo_tenant(client: TestClient, api_module):
    cliente_id = _create_demo_tenant_for_test(api_module, "claim1")
    assert api_module.db_get_client_owner(cliente_id) == ""
    assert cliente_id in api_module._load_demo_registry()

    email = f"claimer_{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "secret-pass-123",
            "display_name": "Reclamante",
            "claim": cliente_id,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["redirect_to"] == "/app"  # claim succeeded, skip wizard
    user = api_module._get_user_by_email(email)
    assert user["cliente_id"] == cliente_id
    assert api_module.db_get_client_owner(cliente_id) == user["id"]
    # TTL removed
    assert cliente_id not in api_module._load_demo_registry()
    # Free subscription seeded
    sub = api_module.db_get_subscription_for_user(user["id"])
    assert sub is not None
    assert sub["plan"] == "free"


def test_signup_claim_silently_ignores_invalid_token(client: TestClient, api_module):
    # Claiming a cliente that does not exist must not block signup; user lands
    # in onboarding instead.
    email = f"badclaim_{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "secret-pass-123",
            "display_name": "Reclamante Malo",
            "claim": "demo_auto_no_existe_xyz999",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["redirect_to"] == "/onboarding"
    user = api_module._get_user_by_email(email)
    assert user["cliente_id"] == ""


def test_claim_rejects_non_demo_cliente_publicly(client: TestClient, api_module):
    # 'demo' is a legacy cliente, not a demo_auto_*; public claim must refuse.
    email = f"legacyclaim_{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "secret-pass-123",
            "display_name": "X",
            "claim": "demo",
        },
    )
    assert resp.status_code == 200  # signup succeeds
    assert resp.json()["redirect_to"] == "/onboarding"  # claim silently rejected
    user = api_module._get_user_by_email(email)
    assert user["cliente_id"] == ""
    assert api_module.db_get_client_owner("demo") == ""


def test_demo_claimable_flag_allows_public_claim_and_banner(client: TestClient, api_module):
    # Un demo creado a mano (NO demo_auto_*) con demo_claimable=True debe mostrar el
    # banner de reclamar y permitir el claim publico, sin abrir clientes reales.
    cliente_id = f"saleslead_{uuid.uuid4().hex[:6]}"
    assert not cliente_id.startswith(api_module.DEMO_TENANT_PREFIX)
    normalized = api_module._normalize_client_config(cliente_id, {
        "nombre": "Sales Lead Demo",
        "color": "#00b1d9",
        "icono": "AI",
        "bienvenida": "Hola, demo.",
        "allowed_origins": [],
        "booking": {"enabled": False},
        "whatsapp": {"enabled": False},
        "demo_claimable": True,
    })
    # El flag sobrevive normalizacion y serializacion (round-trip).
    assert normalized["demo_claimable"] is True
    assert api_module._serialize_client_config(normalized)["demo_claimable"] is True

    with api_module.state_lock:
        next_configs = dict(api_module.CONFIG_CLIENTES)
        next_configs[cliente_id] = normalized
        api_module._update_runtime_configs(next_configs)
    # Persistir crea/actualiza la fila en la tabla clientes (necesaria para fijar owner).
    api_module._persist_configs_to_disk(next_configs)
    (Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id).mkdir(parents=True, exist_ok=True)
    (Path(os.environ["VANTELIA_DATA_DIR"]) / cliente_id / "info.txt").write_text("demo", encoding="utf-8")

    # Banner de reclamar visible en la pagina demo.
    page = client.get(f"/demo/{cliente_id}")
    assert page.status_code == 200
    assert "claim-banner" in page.text

    # Claim publico funciona (transfiere propiedad).
    email = f"claimflag_{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post(
        "/auth/signup",
        json={
            "email": email,
            "password": "secret-pass-123",
            "display_name": "Reclamante Flag",
            "claim": cliente_id,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["redirect_to"] == "/app"
    user = api_module._get_user_by_email(email)
    assert user["cliente_id"] == cliente_id
    assert api_module.db_get_client_owner(cliente_id) == user["id"]


def test_claim_rejects_already_owned_demo(client: TestClient, api_module):
    cliente_id = _create_demo_tenant_for_test(api_module, "owned1")
    first_email = f"first_{uuid.uuid4().hex[:8]}@example.com"
    first = client.post(
        "/auth/signup",
        json={"email": first_email, "password": "secret-pass-123", "display_name": "First", "claim": cliente_id},
    )
    assert first.status_code == 200
    assert first.json()["redirect_to"] == "/app"

    # Second user tries to claim the same demo → claim rejected, lands in onboarding.
    second_email = f"second_{uuid.uuid4().hex[:8]}@example.com"
    second = client.post(
        "/auth/signup",
        json={"email": second_email, "password": "secret-pass-123", "display_name": "Second", "claim": cliente_id},
    )
    assert second.status_code == 200
    assert second.json()["redirect_to"] == "/onboarding"
    second_user = api_module._get_user_by_email(second_email)
    assert second_user["cliente_id"] == ""


def test_demo_page_shows_claim_banner_for_demo_auto(client: TestClient, api_module):
    cliente_id = _create_demo_tenant_for_test(api_module, "banner1")
    resp = client.get(
        f"/demo/{cliente_id}",
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    assert "Activar gratis e instalar" in resp.text
    assert "Tu asistente ya esta listo" in resp.text
    assert f"claim={cliente_id}" in resp.text


def test_demo_page_no_claim_banner_for_legacy_client(client: TestClient, api_module):
    resp = client.get("/demo/demo", headers={"Origin": "http://testserver"})
    assert resp.status_code == 200
    assert 'data-claim-cta="1"' not in resp.text


def test_admin_assign_owner_links_legacy_cliente(client: TestClient, api_module):
    # Create a fake legacy cliente
    cliente_id = "legacy_test_" + uuid.uuid4().hex[:6]
    normalized = api_module._normalize_client_config(cliente_id, {
        "nombre": "Legacy Test",
        "color": "#00b1d9",
        "icono": "LT",
        "bienvenida": "Hola legacy.",
        "allowed_origins": [],
        "booking": {"enabled": False},
        "whatsapp": {"enabled": False},
    })
    with api_module.state_lock:
        next_configs = dict(api_module.CONFIG_CLIENTES)
        next_configs[cliente_id] = normalized
        api_module._update_runtime_configs(next_configs)
    api_module._persist_configs_to_disk(next_configs)
    # Create a target user
    target_email = f"owner_{uuid.uuid4().hex[:8]}@example.com"
    api_module._create_user_self_serve(
        email=target_email,
        password="secret-pass-123",
        display_name="Legacy Owner",
    )

    # Without admin token → 401
    resp_no_auth = client.post(
        f"/admin/clientes/{cliente_id}/assign-owner",
        json={"email": target_email, "plan": "free"},
    )
    assert resp_no_auth.status_code == 401

    # With admin token → 200
    resp = client.post(
        f"/admin/clientes/{cliente_id}/assign-owner",
        json={"email": target_email, "plan": "free"},
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert resp.status_code == 200, resp.text
    assert api_module.db_get_client_owner(cliente_id)
    user = api_module._get_user_by_email(target_email)
    assert user["cliente_id"] == cliente_id
    sub = api_module.db_get_subscription_for_user(user["id"])
    assert sub is not None
    assert sub["plan"] == "free"


def test_admin_assign_owner_404_for_missing_user(client: TestClient, api_module):
    resp = client.post(
        "/admin/clientes/demo/assign-owner",
        json={"email": "no.existe@example.com", "plan": "free"},
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert resp.status_code == 404


def test_admin_stats_overview_returns_kpis(client: TestClient, api_module):
    """/admin/stats/overview devuelve KPIs y tablas para el dashboard admin."""
    no_auth = client.get("/admin/stats/overview")
    assert no_auth.status_code == 401

    resp = client.get(
        "/admin/stats/overview",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for key in [
        "clientes_total",
        "clientes_activos",
        "clientes_demo",
        "clientes_sin_owner",
        "mensajes_mes",
        "mensajes_quota_mes",
        "top_clientes",
        "altas_recientes",
        "churn_riesgo",
        "generated_at",
    ]:
        assert key in data
    assert isinstance(data["top_clientes"], list)
    assert isinstance(data["altas_recientes"], list)
    assert isinstance(data["churn_riesgo"], list)


def test_admin_clientes_returns_enriched_owner_info(client: TestClient, api_module):
    """/admin/clientes now exposes owner_email/plan/messages_quota."""
    cliente_id = "enrich_test_" + uuid.uuid4().hex[:6]
    normalized = api_module._normalize_client_config(cliente_id, {
        "nombre": "Enrich Test",
        "color": "#00b1d9",
        "icono": "ET",
        "bienvenida": "Hola.",
        "allowed_origins": [],
        "booking": {"enabled": False},
        "whatsapp": {"enabled": False},
    })
    with api_module.state_lock:
        next_configs = dict(api_module.CONFIG_CLIENTES)
        next_configs[cliente_id] = normalized
        api_module._update_runtime_configs(next_configs)
    api_module._persist_configs_to_disk(next_configs)
    owner_email = f"enrich_{uuid.uuid4().hex[:8]}@example.com"
    api_module._create_user_self_serve(
        email=owner_email,
        password="secret-pass-123",
        display_name="Enrich Owner",
    )
    resp = client.post(
        f"/admin/clientes/{cliente_id}/assign-owner",
        json={"email": owner_email, "plan": "free"},
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert resp.status_code == 200, resp.text

    listing = client.get(
        "/admin/clientes", headers={"Authorization": "Bearer test-admin-token"}
    )
    assert listing.status_code == 200
    rows = listing.json()
    target = next(r for r in rows if r["cliente_id"] == cliente_id)
    assert target["owner_email"] == owner_email
    assert target["plan"] == "free"
    assert "messages_quota" in target


def test_admin_impersonate_rejects_without_owner(client: TestClient, api_module):
    cliente_id = "noowner_test_" + uuid.uuid4().hex[:6]
    normalized = api_module._normalize_client_config(cliente_id, {
        "nombre": "Sin Owner",
        "color": "#00b1d9",
        "icono": "SO",
        "bienvenida": "Hola.",
        "allowed_origins": [],
        "booking": {"enabled": False},
        "whatsapp": {"enabled": False},
    })
    with api_module.state_lock:
        next_configs = dict(api_module.CONFIG_CLIENTES)
        next_configs[cliente_id] = normalized
        api_module._update_runtime_configs(next_configs)
    api_module._persist_configs_to_disk(next_configs)
    resp = client.post(
        f"/admin/clientes/{cliente_id}/impersonate",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert resp.status_code == 409


def test_admin_impersonate_flow_sets_cookie_and_blocks_password(
    client: TestClient, api_module
):
    cliente_id = "imp_test_" + uuid.uuid4().hex[:6]
    normalized = api_module._normalize_client_config(cliente_id, {
        "nombre": "Imp Test",
        "color": "#00b1d9",
        "icono": "IT",
        "bienvenida": "Hola.",
        "allowed_origins": [],
        "booking": {"enabled": False},
        "whatsapp": {"enabled": False},
    })
    with api_module.state_lock:
        next_configs = dict(api_module.CONFIG_CLIENTES)
        next_configs[cliente_id] = normalized
        api_module._update_runtime_configs(next_configs)
    api_module._persist_configs_to_disk(next_configs)
    owner_email = f"imp_owner_{uuid.uuid4().hex[:8]}@example.com"
    api_module._create_user_self_serve(
        email=owner_email,
        password="secret-pass-123",
        display_name="Imp Owner",
    )
    assigned = client.post(
        f"/admin/clientes/{cliente_id}/assign-owner",
        json={"email": owner_email, "plan": "free"},
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert assigned.status_code == 200, assigned.text

    # Without admin auth → 401
    no_auth = client.post(f"/admin/clientes/{cliente_id}/impersonate")
    assert no_auth.status_code == 401

    impersonate = client.post(
        f"/admin/clientes/{cliente_id}/impersonate",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert impersonate.status_code == 200, impersonate.text
    data = impersonate.json()
    assert data["target_email"] == owner_email
    assert data["expires_in_minutes"] >= 5
    cookie = impersonate.cookies.get(api_module.PORTAL_COOKIE_NAME)
    assert cookie

    # Calling /auth/me with the impersonation cookie reveals the flag.
    me = client.get("/auth/me", cookies={api_module.PORTAL_COOKIE_NAME: cookie})
    assert me.status_code == 200
    body = me.json()
    assert body["as_admin_session"] is True
    assert "@bearer-token" in body["impersonator_email"] or "@" in body["impersonator_email"]
    assert body["email"] == owner_email

    # Password change blocked while impersonated.
    blocked = client.post(
        "/auth/password/change",
        cookies={api_module.PORTAL_COOKIE_NAME: cookie},
        json={"current_password": "secret-pass-123", "new_password": "another-pass-456"},
    )
    assert blocked.status_code == 403

    # End impersonation clears the cookie.
    end = client.post(
        "/admin/impersonate/end",
        cookies={api_module.PORTAL_COOKIE_NAME: cookie},
    )
    assert end.status_code == 200
    assert end.json()["admin_redirect_url"] == "/acceso"
    after_end = client.get("/auth/me", cookies={api_module.PORTAL_COOKIE_NAME: cookie})
    assert after_end.status_code == 401

    admin_user = api_module._get_user_by_email("admin@example.com")
    admin_session = api_module._create_auth_session(admin_user["id"])
    impersonate_from_session = client.post(
        f"/admin/clientes/{cliente_id}/impersonate",
        cookies={api_module.PORTAL_COOKIE_NAME: admin_session},
    )
    assert impersonate_from_session.status_code == 200, impersonate_from_session.text
    session_cookie = impersonate_from_session.cookies.get(api_module.PORTAL_COOKIE_NAME)
    admin_return_cookie = impersonate_from_session.cookies.get(api_module.ADMIN_RETURN_COOKIE_NAME)
    assert session_cookie
    assert admin_return_cookie == admin_session

    restored = client.post(
        "/admin/impersonate/end",
        cookies={
            api_module.PORTAL_COOKIE_NAME: session_cookie,
            api_module.ADMIN_RETURN_COOKIE_NAME: admin_return_cookie,
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["admin_redirect_url"] == "/dashboard"
    restored_admin_cookie = restored.cookies.get(api_module.PORTAL_COOKIE_NAME)
    assert restored_admin_cookie == admin_session
    restored_me = client.get("/auth/me", cookies={api_module.PORTAL_COOKIE_NAME: restored_admin_cookie})
    assert restored_me.status_code == 200
    assert restored_me.json()["role"] == "admin"


def test_admin_cliente_audit_returns_impersonations(client: TestClient, api_module):
    cliente_id = "audit_test_" + uuid.uuid4().hex[:6]
    normalized = api_module._normalize_client_config(cliente_id, {
        "nombre": "Audit Test",
        "color": "#00b1d9",
        "icono": "AT",
        "bienvenida": "Hola.",
        "allowed_origins": [],
        "booking": {"enabled": False},
        "whatsapp": {"enabled": False},
    })
    with api_module.state_lock:
        next_configs = dict(api_module.CONFIG_CLIENTES)
        next_configs[cliente_id] = normalized
        api_module._update_runtime_configs(next_configs)
    api_module._persist_configs_to_disk(next_configs)
    owner_email = f"audit_owner_{uuid.uuid4().hex[:8]}@example.com"
    api_module._create_user_self_serve(
        email=owner_email,
        password="secret-pass-123",
        display_name="Audit Owner",
    )
    assigned = client.post(
        f"/admin/clientes/{cliente_id}/assign-owner",
        json={"email": owner_email, "plan": "free"},
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert assigned.status_code == 200, assigned.text
    impersonate = client.post(
        f"/admin/clientes/{cliente_id}/impersonate",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert impersonate.status_code == 200, impersonate.text

    audit = client.get(
        f"/admin/clientes/{cliente_id}/audit",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert audit.status_code == 200, audit.text
    data = audit.json()
    assert data["cliente_id"] == cliente_id
    assert data["items"]
    assert data["items"][0]["admin_email"]
    assert data["items"][0]["started_at"]
    assert data["items"][0]["ended_at"] == ""


def test_self_serve_period_reset_on_month_boundary(api_module):
    # Manually craft a subscription stuck on an old period; helper should reset usage.
    user_id = api_module._create_user_self_serve(
        email=f"period_{uuid.uuid4().hex[:8]}@example.com",
        password="secret-pass-123",
        display_name="Period Test",
    )["id"]
    sub = api_module.db_ensure_free_subscription(user_id)
    # Backdate period_start by setting it to last year and adding usage.
    with api_module._get_db_connection() as conn:
        conn.execute(
            "UPDATE subscriptions SET current_period_start = ?, messages_used_period = 30 WHERE id = ?",
            ("2024-01-01T00:00:00+00:00", sub["id"]),
        )
        conn.commit()
        stale = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub["id"],)).fetchone()
    refreshed = api_module._maybe_reset_subscription_period(stale)
    assert refreshed["messages_used_period"] == 0
    assert refreshed["current_period_start"] >= api_module._subscription_period_start_now()[:7]


def test_voice_admin_calls_requires_auth(client: TestClient):
    response = client.get("/admin/voice/calls")
    assert response.status_code in (401, 403)


def test_voice_admin_calls_listing_with_token(client: TestClient):
    response = client.get(
        "/admin/voice/calls",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert "stats" in payload
    assert set(payload["stats"]) >= {"today", "week", "avg_duration", "with_booking"}


def test_voice_incoming_rejects_missing_twilio_signature(client: TestClient, api_module, monkeypatch):
    # Voice channel needs Twilio creds configured to even reach the signature check.
    monkeypatch.setattr(api_module, "TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setattr(api_module, "TWILIO_AUTH_TOKEN", "twilio-auth-token-test")
    response = client.post(
        "/voice/demo",
        data={"CallSid": "CA123", "From": "+34600000000", "To": "+34911111111"},
    )
    assert response.status_code == 403


def test_voice_incoming_unknown_client_returns_hangup(client: TestClient, api_module, monkeypatch):
    monkeypatch.setattr(api_module, "TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setattr(api_module, "TWILIO_AUTH_TOKEN", "twilio-auth-token-test")
    # Pretend the Twilio signature is valid so we exercise the client-resolution path.
    monkeypatch.setattr(api_module, "_twilio_request_valid", lambda url, params, signature: True)
    response = client.post(
        "/voice/ghostclient",
        data={"CallSid": "CA999", "From": "+34600000000", "To": "+34911111111"},
        headers={"X-Twilio-Signature": "irrelevant-because-mocked"},
    )
    assert response.status_code == 200
    assert "<Hangup" in response.text


def test_voice_incoming_enabled_client_returns_stream(client: TestClient, api_module, monkeypatch):
    monkeypatch.setattr(api_module, "TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setattr(api_module, "TWILIO_AUTH_TOKEN", "twilio-auth-token-test")
    monkeypatch.setattr(api_module, "_twilio_request_valid", lambda url, params, signature: True)
    # Voice is plan-gated (Business). This test checks the webhook/Stream wiring, not
    # the plan gate, so force the plan check True to stay robust against test ordering.
    monkeypatch.setattr(api_module, "_client_voice_plan_enabled", lambda cliente_id: True)
    # Enable voice on the demo client in the in-memory config.
    api_module.CONFIG_CLIENTES["demo"]["voice"] = api_module._normalize_voice_config(
        {"enabled": True, "greeting": "Hola demo", "openai_voice": "alloy"}
    )
    response = client.post(
        "/voice/demo",
        data={"CallSid": "CA777", "From": "+34600000000", "To": "+34911111111"},
        headers={"X-Twilio-Signature": "irrelevant-because-mocked"},
    )
    assert response.status_code == 200
    assert "<Connect>" in response.text
    assert "/voice/stream/demo" in response.text
    # The call should have been registered as in_progress.
    detail = client.get(
        "/admin/voice/calls/CA777",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "in_progress"


def test_voice_truncates_twilio_playback_at_the_heard_audio(api_module):
    import asyncio
    import base64
    import json

    class FakeOpenAIWebSocket:
        def __init__(self):
            self.sent = []

        async def send(self, value):
            self.sent.append(json.loads(value))

    class FakeTwilioWebSocket:
        def __init__(self):
            self.sent = []

        async def send_text(self, value):
            self.sent.append(json.loads(value))

    openai_ws = FakeOpenAIWebSocket()
    twilio_ws = FakeTwilioWebSocket()
    state = {
        "stream_sid": "MZ123",
        "assistant_item_id": "item_123",
        "assistant_audio_started_at": 1000,
        "latest_media_timestamp": 1750,
        "assistant_audio_generated_ms": 1200,
    }

    assert api_module._voice_pcmu_duration_ms(base64.b64encode(b"x" * 800).decode()) == 100
    truncated = asyncio.run(
        api_module._voice_truncate_interrupted_response(openai_ws, twilio_ws, state)
    )

    assert truncated is True
    assert twilio_ws.sent == [{"event": "clear", "streamSid": "MZ123"}]
    assert openai_ws.sent == [
        {
            "type": "conversation.item.truncate",
            "item_id": "item_123",
            "content_index": 0,
            "audio_end_ms": 750,
        }
    ]
    assert state["assistant_item_id"] == ""
    assert state["assistant_audio_started_at"] is None
    assert state["assistant_audio_generated_ms"] == 0


def test_voice_clear_twilio_playback_without_truncating_openai(api_module):
    import asyncio
    import json

    class FakeTwilioWebSocket:
        def __init__(self):
            self.sent = []

        async def send_text(self, value):
            self.sent.append(json.loads(value))

    twilio_ws = FakeTwilioWebSocket()
    state = {
        "stream_sid": "MZ123",
        "assistant_item_id": "item_123",
        "assistant_audio_started_at": 1000,
        "assistant_audio_generated_ms": 1200,
    }

    cleared = asyncio.run(api_module._voice_clear_twilio_playback(twilio_ws, state))

    assert cleared is True
    assert twilio_ws.sent == [{"event": "clear", "streamSid": "MZ123"}]
    assert state["assistant_item_id"] == ""
    assert state["assistant_audio_started_at"] is None
    assert state["assistant_audio_generated_ms"] == 0


def test_voice_booking_tool_creates_real_booking(api_module):
    import asyncio
    from datetime import datetime, timedelta

    # Near-future weekday that isn't Sunday (demo closes weekday 6).
    day = datetime.now().date() + timedelta(days=1)
    while day.weekday() == 6:
        day += timedelta(days=1)
    fecha = day.isoformat()

    avail = asyncio.run(api_module._voice_check_availability("demo", fecha))
    assert avail["ok"] is True, avail
    assert avail["hay_huecos"] is True, avail
    hora = avail["huecos"][0]
    servicio = api_module._voice_service_options("demo")[0]

    result = asyncio.run(
        api_module._voice_perform_booking(
            "demo",
            nombre="Cliente Voz",
            telefono="+34600111222",
            fecha=fecha,
            hora=hora,
            servicio=servicio,
        )
    )
    assert result["ok"] is True, result
    assert result["booking_id"].startswith("bk_")

    with api_module._get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (result["booking_id"],)
        ).fetchone()
    assert row is not None
    assert row["source"] == "voice"
    assert row["status"] == "confirmed"
    assert row["telefono"] == "+34600111222"
    assert result["mensaje_voz"].startswith("Perfecto, la cita queda confirmada")


def test_voice_spoken_weekday_resolves_from_local_today(api_module):
    base = datetime(2026, 6, 27).date()  # Sabado.
    assert api_module._voice_date_from_spoken_phrase(
        "demo", "lunes", base_date=base
    ).isoformat() == "2026-06-29"
    assert api_module._voice_date_from_spoken_phrase(
        "demo", "martes", base_date=base
    ).isoformat() == "2026-06-30"
    assert api_module._voice_date_from_spoken_phrase(
        "demo", "12 de julio", base_date=base
    ).isoformat() == "2026-07-12"


def test_voice_spoken_weekday_with_accents_resolves_exact_next_day(api_module):
    base = datetime(2026, 6, 30).date()  # Martes; el miercoles es 1 de julio.
    expected = "2026-07-01"
    for phrase in [
        "el mi\u00e9rcoles",
        "el miercoles",
        "el mi\u00c3\u00a9rcoles",
        "el mi?rcoles",
        "el mi rcoles",
    ]:
        resolved = api_module._voice_date_from_spoken_phrase("demo", phrase, base_date=base)
        assert resolved is not None, phrase
        assert resolved.isoformat() == expected, phrase
    # Si el modelo mezcla el dia correcto con una fecha numerica incompatible, gana
    # el dia hablado por el cliente.
    assert api_module._voice_date_from_spoken_phrase(
        "demo", "miercoles 3 de julio", base_date=base
    ).isoformat() == expected
    assert api_module._voice_date_from_spoken_phrase(
        "demo", "viernes 3 de julio", base_date=base
    ).isoformat() == "2026-07-03"


def test_voice_dispatch_corrects_spoken_weekday_before_booking(api_module):
    import asyncio

    target = api_module._voice_date_from_spoken_phrase("demo", "lunes que viene")
    assert target is not None
    assert target.weekday() == 0
    target_iso = target.isoformat()
    wrong_iso = (target + timedelta(days=1)).isoformat()
    servicio = api_module._voice_service_options("demo")[0]

    # Aisla el dia de la prueba: otros tests de voz pueden haber usado el primer lunes.
    with api_module._get_db_connection() as conn:
        conn.execute(
            "DELETE FROM bookings WHERE cliente_id = ? AND booking_date = ? AND source = 'voice'",
            ("demo", target_iso),
        )

    availability = asyncio.run(
        api_module._voice_dispatch_tool(
            "demo",
            "consultar_disponibilidad",
            json.dumps({
                "fecha": wrong_iso,
                "fecha_texto": "lunes que viene",
                "servicio": servicio,
            }),
        )
    )
    assert availability["ok"] is True, availability
    assert availability["fecha"] == target_iso
    assert availability["fecha_corregida"] is True
    assert availability["fecha_original"] == wrong_iso
    assert availability["huecos"], availability
    hora = availability["huecos"][0]

    exact = asyncio.run(
        api_module._voice_dispatch_tool(
            "demo",
            "consultar_disponibilidad",
            json.dumps({
                "fecha": wrong_iso,
                "fecha_texto": "lunes que viene",
                "servicio": servicio,
                "hora": hora,
            }),
        )
    )
    assert exact["ok"] is True, exact
    assert exact["fecha"] == target_iso
    assert exact["hora_disponible"] is True
    assert "voy a" not in exact["mensaje_voz"].lower()

    result = asyncio.run(
        api_module._voice_dispatch_tool(
            "demo",
            "crear_cita",
            json.dumps({
                "nombre": "Pablo Sanchez",
                "telefono": "675802001",
                "servicio": servicio,
                "fecha": wrong_iso,
                "fecha_texto": "lunes que viene",
                "hora": hora,
            }),
        )
    )
    assert result["ok"] is True, result
    assert result["fecha"] == target_iso
    assert result["fecha_corregida"] is True
    assert "martes" not in result["mensaje_voz"].lower()

    with api_module._get_db_connection() as conn:
        row = conn.execute(
            "SELECT booking_date, booking_time FROM bookings WHERE id = ?",
            (result["booking_id"],),
        ).fetchone()
    assert row is not None
    assert row["booking_date"] == target_iso
    assert row["booking_time"] == hora


def test_voice_booking_tool_requires_service_when_catalog_exists(api_module):
    import asyncio
    from datetime import datetime, timedelta

    day = datetime.now().date() + timedelta(days=1)
    while day.weekday() == 6:
        day += timedelta(days=1)
    fecha = day.isoformat()

    result = asyncio.run(
        api_module._voice_perform_booking(
            "demo",
            nombre="Cliente Voz Sin Servicio",
            telefono="+34600111333",
            fecha=fecha,
            hora="10:00",
            servicio="",
        )
    )
    assert result["ok"] is False
    assert result["needs_service"] is True
    assert result["missing_field"] == "servicio"
    assert "servicio" in result["mensaje_voz"].lower()


def test_voice_booking_rejects_unknown_service_and_bad_phone(api_module):
    import asyncio
    from datetime import datetime, timedelta

    day = datetime.now().date() + timedelta(days=1)
    while day.weekday() == 6:
        day += timedelta(days=1)
    fecha = day.isoformat()

    unknown_service = asyncio.run(
        api_module._voice_perform_booking(
            "demo",
            nombre="Cliente Voz Servicio Inventado",
            telefono="600111333",
            fecha=fecha,
            hora="10:00",
            servicio="Masaje deportivo",
        )
    )
    assert unknown_service["ok"] is False
    assert unknown_service["needs_service"] is True
    assert "no encuentro" in unknown_service["mensaje_voz"].lower()

    bad_phone = asyncio.run(
        api_module._voice_perform_booking(
            "demo",
            nombre="Cliente Voz Telefono Corto",
            telefono="65 802 001",
            fecha=fecha,
            hora="10:00",
            servicio=api_module._voice_service_options("demo")[0],
        )
    )
    assert bad_phone["ok"] is False
    assert bad_phone["needs_phone"] is True
    assert bad_phone["missing_field"] == "telefono"
    assert "nueve digitos" in bad_phone["mensaje_voz"].lower()


def test_voice_services_match_active_portal_services(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    suffix = uuid.uuid4().hex[:8]
    active_name = f"Voz Catalogo Real {suffix}"
    inactive_name = f"Voz Inactivo No Decir {suffix}"
    created_slugs = []
    try:
        active = client.post(
            "/auth/services",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={
                "nombre": active_name,
                "duration_minutes": 30,
                "price_cents": 2500,
                "is_active": True,
            },
        )
        assert active.status_code == 200, active.text
        created_slugs.append(active.json()["id"])
        inactive = client.post(
            "/auth/services",
            params={"cliente_id": "demo"},
            cookies=cookies,
            json={
                "nombre": inactive_name,
                "duration_minutes": 30,
                "price_cents": 2500,
                "is_active": False,
            },
        )
        assert inactive.status_code == 200, inactive.text
        created_slugs.append(inactive.json()["id"])

        portal_items = client.get(
            "/auth/services",
            params={"cliente_id": "demo", "include_inactive": True},
            cookies=cookies,
        ).json()["items"]
        assert any(item["nombre"] == active_name and item["is_active"] for item in portal_items)
        assert any(item["nombre"] == inactive_name and not item["is_active"] for item in portal_items)

        voice_options = api_module._voice_service_options("demo")
        assert active_name in voice_options
        assert inactive_name not in voice_options
        assert set(voice_options) == {
            item["nombre"] for item in portal_items if item["is_active"]
        }

        instructions = api_module._voice_build_instructions("demo", api_module.CONFIG_CLIENTES["demo"])
        assert active_name in instructions
        assert inactive_name not in instructions
    finally:
        with api_module._get_db_connection() as connection:
            for slug in created_slugs:
                connection.execute(
                    "DELETE FROM service_location_overrides WHERE cliente_id = 'demo' AND service_slug = ?",
                    (slug,),
                )
                connection.execute(
                    "DELETE FROM services WHERE cliente_id = 'demo' AND slug = ?",
                    (slug,),
                )
            connection.commit()


def test_voice_booking_tools_absent_when_booking_disabled(api_module):
    cfg_enabled = api_module.CONFIG_CLIENTES["demo"]
    tools = api_module._voice_booking_tools("demo", cfg_enabled)
    assert any(t["name"] == "crear_cita" for t in tools)
    crear = next(t for t in tools if t["name"] == "crear_cita")
    assert "servicio" in crear["parameters"]["required"]

    # A config with booking disabled exposes no tools.
    cfg_disabled = dict(cfg_enabled)
    cfg_disabled["booking"] = dict(cfg_enabled["booking"])
    cfg_disabled["booking"]["enabled"] = False
    assert api_module._voice_booking_tools("demo", cfg_disabled) == []


def test_voice_booking_code_is_digits_and_regex_back_compatible(api_module):
    code = api_module._generate_booking_code()
    assert code.startswith("R-") and code[2:].isdigit() and len(code[2:]) == 6
    # La extraccion reconoce el formato nuevo (6 digitos) y el antiguo (4 alfanumericos).
    assert api_module._extract_booking_code_from_text("mi reserva es R-481523") == "R-481523"
    assert api_module._extract_booking_code_from_text("codigo R-7F4K gracias") == "R-7F4K"


def test_voice_otp_lets_owner_verify_from_another_phone(vantelia_env_factory, monkeypatch):
    import asyncio
    import json as _json
    from datetime import datetime, timedelta

    cfg = {
        "otpqa": {
            "nombre": "OTP QA", "icono": "QA", "color": "#00b1d9", "bienvenida": "Hola",
            "prompt_extra": "", "allowed_origins": ["http://testserver"],
            "contacto": {"email": "qa@example.com", "telefono": "+34600000000"},
            "branding": {"powered_by": "Vantelia"}, "plan": "business",
            "subscription": {"plan": "business", "status": "active"},
            "whatsapp": {"enabled": False, "phone_number_id": ""},
            "voice": {"enabled": True, "twilio_phone_number": "+34910000001"},
            "booking": {"enabled": True, "timezone": "Europe/Madrid", "slot_minutes": 30,
                        "day_start": "09:00", "day_end": "18:00", "closed_weekdays": [6],
                        "provider": "internal", "success_message": "ok",
                        # El OTP de voz usa los canales GLOBALES del Seguimiento: activamos SMS
                        # para que el codigo se entregue por SMS al contacto de la cita.
                        "message_template_channels": {
                            "confirmed": {"email": True, "whatsapp": False, "sms": True}}},
        }
    }
    api = vantelia_env_factory(cfg, info_txt="SERVICIOS Y PRECIOS:\n")
    from backend import agenda, appstate, emailing, messaging

    monkeypatch.setattr(emailing, "_send_client_email", lambda *a, **k: "test")
    monkeypatch.setattr(
        agenda,
        "_reminder_channel_availability",
        lambda cliente_id: {
            "sms": {"available": True},
            "whatsapp": {"available": False},
            "email": {"available": True},
        },
    )

    sent_sms = {}

    async def _ok_sms(cliente_id, to_number, body):
        sent_sms["to_number"] = to_number
        return True

    monkeypatch.setattr(messaging, "_send_client_sms", _ok_sms)

    day = datetime.now().date() + timedelta(days=2)
    while day.weekday() == 6:
        day += timedelta(days=1)
    fecha = day.isoformat()
    owner, other = "600111222", "+34999000000"

    created = asyncio.run(api._voice_dispatch_tool(
        "otpqa", "crear_cita",
        _json.dumps({"nombre": "Cli", "telefono": owner, "email": "cli@test.com",
                     "fecha": fecha, "hora": "10:00", "servicio": ""}),
        from_number=owner))
    assert created["ok"], created
    bid = created["booking_id"]
    with api._get_db_connection() as connection:
        code = connection.execute(
            "SELECT booking_code FROM bookings WHERE id=?", (bid,)
        ).fetchone()["booking_code"]

    # consultar_cita localiza la cita desde otro telefono (la lectura no exige titularidad).
    looked = asyncio.run(api._voice_dispatch_tool(
        "otpqa", "consultar_cita", _json.dumps({"codigo_reserva": code}), from_number=other))
    assert looked["ok"] and looked["hora"] == "10:00"

    # Sin OTP y desde otro telefono no se puede reprogramar.
    blocked = asyncio.run(api._voice_dispatch_tool(
        "otpqa", "reprogramar_cita",
        _json.dumps({"codigo_reserva": code, "fecha": fecha, "hora": "11:00"}), from_number=other))
    assert blocked["ok"] is False and blocked.get("needs_verification")

    sent = asyncio.run(api._voice_dispatch_tool(
        "otpqa", "enviar_codigo_verificacion", _json.dumps({"codigo_reserva": code}), from_number=other))
    assert sent["ok"], sent
    assert sent_sms["to_number"] == "+34600111222"
    assert "codigo" in sent["mensaje_voz"].lower()
    assert api._voice_tool_followup_prompt("enviar_codigo_verificacion", sent)
    otp = appstate.voice_otp["otpqa:" + bid]["code"]

    wrong = "0000" if otp != "0000" else "1111"
    bad = asyncio.run(api._voice_dispatch_tool(
        "otpqa", "verificar_codigo",
        _json.dumps({"codigo_reserva": code, "codigo": wrong}), from_number=other))
    assert bad["ok"] is False

    good = asyncio.run(api._voice_dispatch_tool(
        "otpqa", "verificar_codigo",
        _json.dumps({"codigo_reserva": code, "codigo": otp}), from_number=other))
    assert good["ok"]
    assert good["mensaje_voz"] == "Perfecto, codigo verificado."
    assert "llama ahora a la herramienta" in api._voice_tool_followup_prompt("verificar_codigo", good)

    done = asyncio.run(api._voice_dispatch_tool(
        "otpqa", "reprogramar_cita",
        _json.dumps({"codigo_reserva": code, "fecha": fecha, "hora": "11:00"}), from_number=other))
    assert done["ok"], done
    assert done["mensaje_voz"].startswith("Listo, he verificado el codigo y he reprogramado")
    assert api._voice_tool_followup_prompt("reprogramar_cita", done)
    with api._get_db_connection() as connection:
        when = connection.execute(
            "SELECT booking_time FROM bookings WHERE id=?", (bid,)
        ).fetchone()["booking_time"]
    assert when == "11:00"

    cancelled = asyncio.run(api._voice_dispatch_tool(
        "otpqa", "cancelar_cita",
        _json.dumps({"codigo_reserva": code}), from_number=other))
    assert cancelled["ok"], cancelled
    assert cancelled["mensaje_voz"] == "Listo, he verificado el codigo y he cancelado la cita."
    assert api._voice_tool_followup_prompt("cancelar_cita", cancelled)


def test_gmail_tokens_are_encrypted_and_connection_status_is_safe(client: TestClient, api_module):
    with api_module._get_db_connection() as connection:
        connection.execute("DELETE FROM gmail_connections")
        connection.commit()

    api_module._gmail_save_tokens(
        {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_in": 3600,
            "scope": api_module.GOOGLE_GMAIL_SCOPES,
        },
        "sender@example.com",
    )

    row = api_module._gmail_connection()
    assert row is not None
    assert "access-secret" not in row["access_token_encrypted"]
    assert "refresh-secret" not in row["refresh_token_encrypted"]
    assert api_module._gmail_decrypt(row["access_token_encrypted"]) == "access-secret"
    assert api_module._gmail_decrypt(row["refresh_token_encrypted"]) == "refresh-secret"

    response = client.get(
        "/admin/email-channels/status",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert response.status_code == 200
    assert response.json()["gmail"]["connected"] is True
    assert "access-secret" not in response.text
    assert "refresh-secret" not in response.text

    with api_module._get_db_connection() as connection:
        connection.execute("DELETE FROM gmail_connections")
        connection.commit()


def test_gmail_oauth_connect_requests_offline_send_scope(client: TestClient, api_module, monkeypatch):
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(api_module, "GOOGLE_GMAIL_REDIRECT_URI", "https://app.test.local/auth/google/gmail/callback")

    response = client.get(
        "/admin/email-channels/gmail/connect",
        headers={"Authorization": "Bearer test-admin-token"},
        follow_redirects=False,
    )

    assert response.status_code == 307
    location = response.headers["location"]
    assert "https://accounts.google.com/o/oauth2/v2/auth?" in location
    assert "gmail.send" in location
    assert "access_type=offline" in location
    assert "prompt=consent+select_account" in location


def test_email_provider_auto_prefers_gmail_and_falls_back_to_smtp(api_module, monkeypatch):
    sent = []
    message = api_module.EmailMessage()
    message["From"] = "Vantelia <info@vantelia.es>"
    message["To"] = "test@example.com"
    message["Subject"] = "Prueba"
    message.set_content("Hola")

    monkeypatch.setattr(api_module, "EMAIL_SEND_PROVIDER", "auto")
    monkeypatch.setattr(api_module, "_gmail_oauth_configured", lambda: True)
    monkeypatch.setattr(api_module, "_gmail_connected", lambda: True)
    monkeypatch.setattr(api_module, "_smtp_configured", lambda: True)
    monkeypatch.setattr(api_module, "_gmail_send_message", lambda msg: sent.append("gmail"))
    monkeypatch.setattr(api_module, "_smtp_send_message", lambda msg: sent.append("smtp"))
    api_module._send_email_object(message)
    assert sent == ["gmail"]

    sent.clear()

    def fail_gmail(msg):
        raise RuntimeError("gmail unavailable")

    monkeypatch.setattr(api_module, "_gmail_send_message", fail_gmail)
    api_module._send_email_object(message)
    assert sent == ["smtp"]


def test_admin_can_change_vantelia_fallback_sender(client: TestClient, api_module, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(api_module, "OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(api_module, "SMTP_HOST", "smtp.env.local")
    monkeypatch.setattr(api_module, "EMAIL_SEND_PROVIDER", "smtp")
    sent = {}

    def fake_smtp_send(msg):
        sent["host"] = api_module._smtp_host()
        sent["port"] = api_module._smtp_port()
        sent["starttls"] = api_module._smtp_starttls()
        sent["login"] = (api_module._smtp_username(), api_module._smtp_password())
        sent["from"] = msg["From"]
        sent["reply_to"] = msg.get("Reply-To", "")

    monkeypatch.setattr(api_module, "_smtp_send_message", fake_smtp_send)

    try:
        response = client.post(
            "/admin/email-channels/smtp-settings",
            headers={"Authorization": "Bearer test-admin-token"},
            json={
                "host": "smtp.vantelia.test",
                "port": 2525,
                "username": "no-reply@vantelia.es",
                "password": "smtp-secret",
                "starttls": True,
                "from_email": "operaciones@example.com",
                "from_name": "Operaciones Vantelia",
                "reply_to": "soporte@example.com",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["smtp"]["from_email"] == "operaciones@example.com"
        assert response.json()["smtp"]["password_configured"] == "1"
        with api_module._get_db_connection() as connection:
            row = connection.execute(
                "SELECT value FROM system_settings WHERE key='smtp_password_encrypted'"
            ).fetchone()
        assert row is not None
        assert "smtp-secret" not in row["value"]
        assert api_module._decrypt_channel_secret(row["value"]) == "smtp-secret"

        api_module._send_email_message("destino@example.com", "Prueba", "Hola")
        assert sent["host"] == "smtp.vantelia.test"
        assert sent["port"] == 2525
        assert sent["starttls"] is True
        assert sent["login"] == ("no-reply@vantelia.es", "smtp-secret")
        assert sent["from"] == "Operaciones Vantelia <operaciones@example.com>"
        assert sent["reply_to"] == "soporte@example.com"
    finally:
        with api_module._get_db_connection() as connection:
            connection.execute(
                """
                DELETE FROM system_settings
                WHERE key IN (
                    'smtp_host', 'smtp_port', 'smtp_username', 'smtp_password_encrypted',
                    'smtp_starttls', 'smtp_from_email', 'smtp_from_name', 'smtp_reply_to'
                )
                """
            )
            connection.commit()


def test_client_gmail_connection_is_encrypted_and_isolated(api_module):
    with api_module._get_db_connection() as connection:
        connection.execute("DELETE FROM gmail_connections WHERE id IN ('client_a', 'client_b')")
        connection.commit()

    api_module._gmail_save_tokens(
        {"access_token": "access-a", "refresh_token": "refresh-a", "expires_in": 3600},
        "a@example.com",
        cliente_id="client_a",
    )
    api_module._gmail_save_tokens(
        {"access_token": "access-b", "refresh_token": "refresh-b", "expires_in": 3600},
        "b@example.com",
        cliente_id="client_b",
    )

    row_a = api_module._gmail_connection("client_a")
    row_b = api_module._gmail_connection("client_b")
    assert row_a["email"] == "a@example.com"
    assert row_b["email"] == "b@example.com"
    assert api_module._gmail_decrypt(row_a["refresh_token_encrypted"]) == "refresh-a"
    assert api_module._gmail_decrypt(row_b["refresh_token_encrypted"]) == "refresh-b"
    assert "refresh-a" not in row_a["refresh_token_encrypted"]

    with api_module._get_db_connection() as connection:
        connection.execute("DELETE FROM gmail_connections WHERE id IN ('client_a', 'client_b')")
        connection.commit()


def test_required_booking_payment_is_idempotent_and_confirmed_by_webhook(api_module, monkeypatch):
    service_slug = f"paid-{uuid.uuid4().hex[:8]}"
    record = _build_booking_record(
        api_module,
        servicio="Consulta de pago",
        service_id=service_slug,
        service_price_cents=4900,
        booking_time="09:30",
    )
    created_sessions = []
    sent_emails = []

    def fake_create(**kwargs):
        created_sessions.append(kwargs)
        return SimpleNamespace(id="cs_booking_test", url="https://checkout.stripe.test/booking")

    with api_module._get_db_connection() as connection:
        now = api_module._utc_now_iso()
        connection.execute(
            """
            INSERT INTO services
                (cliente_id, slug, name, duration_minutes, price_cents, payment_mode,
                 payment_type, deposit_amount_cents, currency, created_at, updated_at)
            VALUES (?, ?, ?, 30, 4900, 'payment_required', 'deposit', 1200, 'eur', ?, ?)
            """,
            ("demo", service_slug, "Consulta de pago", now, now),
        )
        connection.commit()

    api_module._save_stripe_connected_account("demo", "owner-test", "acct_booking_test", status_value="active")
    monkeypatch.setattr(api_module, "_stripe_init", lambda: None)
    monkeypatch.setattr(api_module.stripe.checkout.Session, "create", fake_create)
    monkeypatch.setattr(api_module, "_send_booking_email", lambda row, kind, *args, **kwargs: sent_emails.append(kind))

    try:
        api_module._store_booking(record)
        stored = api_module._get_booking_row_by_id(record["id"])
        payment = api_module._booking_payment_row(record["id"])
        assert stored["status"] == "pending_payment"
        assert stored["payment_status"] == "pending"
        assert payment["amount_cents"] == 1200
        assert payment["checkout_url"] == "https://checkout.stripe.test/booking"
        assert created_sessions[0]["stripe_account"] == "acct_booking_test"
        assert created_sessions[0]["success_url"].endswith(
            f"/booking/manage/{record['manage_token']}?payment=success"
        )
        assert created_sessions[0]["cancel_url"].endswith(
            f"/booking/manage/{record['manage_token']}?payment=cancel"
        )
        assert f"/reservas/{record['manage_token']}" not in created_sessions[0]["success_url"]

        assert api_module.create_booking_payment_checkout("demo", record["id"]) == payment["checkout_url"]
        assert len(created_sessions) == 1

        event = {
            "id": "cs_booking_test",
            "payment_intent": "pi_booking_test",
            "metadata": {"source": "booking_payment", "cliente_id": "demo", "booking_id": record["id"]},
        }
        assert api_module.process_booking_payment_webhook(event) is True
        assert api_module.process_booking_payment_webhook(event) is True
        paid = api_module._get_booking_row_by_id(record["id"])
        assert paid["status"] == "confirmed"
        assert paid["payment_status"] == "paid"
        assert sent_emails == ["confirmed"]
    finally:
        with api_module._get_db_connection() as connection:
            connection.execute("DELETE FROM booking_payments WHERE booking_id = ?", (record["id"],))
            connection.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            connection.execute("DELETE FROM services WHERE cliente_id = 'demo' AND slug = ?", (service_slug,))
            connection.execute("DELETE FROM stripe_connected_accounts WHERE cliente_id = 'demo'")
            connection.commit()


def test_required_payment_expiry_releases_booking_and_stripe_unavailable_does_not_block(api_module, monkeypatch):
    service_slug = f"paid-expire-{uuid.uuid4().hex[:8]}"
    record = _build_booking_record(
        api_module,
        servicio="Consulta caducable",
        service_id=service_slug,
        service_price_cents=3000,
        booking_time="09:30",
    )
    with api_module._get_db_connection() as connection:
        now = api_module._utc_now_iso()
        connection.execute(
            """
            INSERT INTO services
                (cliente_id, slug, name, duration_minutes, price_cents, payment_mode,
                 payment_type, deposit_amount_cents, currency, created_at, updated_at)
            VALUES (?, ?, ?, 30, 3000, 'payment_required', 'full', 0, 'eur', ?, ?)
            """,
            ("demo", service_slug, "Consulta caducable", now, now),
        )
        connection.execute("DELETE FROM stripe_connected_accounts WHERE cliente_id = 'demo'")
        connection.commit()

    try:
        api_module._store_booking(record)
        stored = api_module._get_booking_row_by_id(record["id"])
        assert stored["status"] == "confirmed"
        assert stored["payment_status"] == "not_required"

        api_module._save_stripe_connected_account("demo", "owner-test", "acct_booking_test", status_value="active")
        record_two = _build_booking_record(
            api_module,
            servicio="Consulta caducable",
            service_id=service_slug,
            service_price_cents=3000,
            booking_time="10:00",
        )
        monkeypatch.setattr(api_module, "_booking_payment_after_store", lambda booking_id, request=None: "")
        api_module._store_booking(record_two)
        expired_event = {
            "metadata": {"source": "booking_payment", "cliente_id": "demo", "booking_id": record_two["id"]}
        }
        assert api_module.process_booking_payment_expired_webhook(expired_event) is True
        expired = api_module._get_booking_row_by_id(record_two["id"])
        assert expired["status"] == "cancelled"
        assert expired["payment_status"] == "expired"
    finally:
        with api_module._get_db_connection() as connection:
            connection.execute("DELETE FROM booking_payments WHERE cliente_id = 'demo'")
            connection.execute("DELETE FROM bookings WHERE id IN (?, ?)", (record["id"], locals().get("record_two", {}).get("id", "")))
            connection.execute("DELETE FROM services WHERE cliente_id = 'demo' AND slug = ?", (service_slug,))
            connection.execute("DELETE FROM stripe_connected_accounts WHERE cliente_id = 'demo'")
            connection.commit()


def test_cancellation_policy_engine(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    params = {"cliente_id": "demo"}
    iso = lambda d: d.isoformat(timespec="seconds") + "Z"
    now = api_module.datetime.utcnow()

    # Configura la politica via endpoint (admin = owner -> pasa el guard manager+).
    r = client.put("/auth/app/cancellation-policy", params=params, cookies=cookies, json={
        "enabled": True, "free_cancel_hours": 24, "late_cancel_fee_pct": 50,
        "no_show_fee_pct": 100, "auto_apply": True, "policy_text": "Cancela gratis 24h antes.",
    })
    assert r.status_code == 200, r.text
    assert r.json()["late_cancel_fee_pct"] == 50
    g = client.get("/auth/app/cancellation-policy", params=params, cookies=cookies).json()
    assert g["enabled"] is True and g["no_show_fee_pct"] == 100 and g["free_cancel_hours"] == 24

    # Validacion de rango: >100 -> 422.
    bad = client.put("/auth/app/cancellation-policy", params=params, cookies=cookies,
                     json={"late_cancel_fee_pct": 250})
    assert bad.status_code == 422

    created = []
    try:
        # Fuera de plazo (faltan 5h, margen 24h) -> penalizacion 50%.
        late = _build_booking_record(
            api_module, service_id="svc-x", service_price_cents=6000, booking_time="08:00",
            start_at=iso(now + api_module.timedelta(hours=5)),
            end_at=iso(now + api_module.timedelta(hours=6)))
        api_module._store_booking(late); created.append(late["id"])
        prev = client.get(f"/auth/bookings/{late['id']}/cancellation-preview", cookies=cookies).json()
        assert prev["cancel"]["within_free_window"] is False
        assert prev["cancel"]["fee_pct"] == 50 and prev["cancel"]["fee_cents"] == 3000
        assert prev["cancel"]["refund_cents"] == 3000
        assert prev["no_show"]["fee_cents"] == 6000

        # Dentro de plazo (faltan 48h) -> sin penalizacion.
        early = _build_booking_record(
            api_module, service_id="svc-x", service_price_cents=6000, booking_time="09:30",
            start_at=iso(now + api_module.timedelta(hours=48)),
            end_at=iso(now + api_module.timedelta(hours=49)))
        api_module._store_booking(early); created.append(early["id"])
        prev2 = client.get(f"/auth/bookings/{early['id']}/cancellation-preview", cookies=cookies).json()
        assert prev2["cancel"]["within_free_window"] is True
        assert prev2["cancel"]["fee_cents"] == 0 and prev2["cancel"]["refund_cents"] == 6000

        # Cancelar la cita tardia (sin pago) -> registra la evaluacion de politica.
        cc = client.post(f"/auth/bookings/{late['id']}/cancel", cookies=cookies)
        assert cc.status_code == 200, cc.text
        events = [row["event_type"] for row in api_module._list_booking_audit_rows(late["id"])]
        assert "cancellation_policy_evaluated" in events
        assert "booking_cancelled" in events
    finally:
        with api_module._get_db_connection() as connection:
            for bid in created:
                connection.execute("DELETE FROM bookings WHERE id = ?", (bid,))
                connection.execute("DELETE FROM booking_audit WHERE booking_id = ?", (bid,))
            connection.execute("DELETE FROM cancellation_policies WHERE cliente_id = 'demo'")
            connection.commit()


def test_service_cancellation_override_resolves(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    params = {"cliente_id": "demo"}
    # Politica tenant: no-show 100%.
    client.put("/auth/app/cancellation-policy", params=params, cookies=cookies,
               json={"enabled": True, "no_show_fee_pct": 100, "free_cancel_hours": 24})
    slug = None
    try:
        svc = client.post("/auth/services", params=params, cookies=cookies, json={
            "nombre": "Masaje Override Test", "duration_minutes": 30, "price_cents": 8000,
            "no_show_fee_pct": 30})
        assert svc.status_code == 200, svc.text
        slug = svc.json()["id"]
        assert svc.json()["no_show_fee_pct"] == 30
        # El override del servicio (30%) gana sobre el tenant (100%).
        rec = _build_booking_record(api_module, service_id=slug, service_price_cents=8000,
                                    servicio="Masaje Override Test")
        api_module._store_booking(rec)
        try:
            outcome = api_module.compute_cancellation_outcome(
                api_module._load_booking_or_404(rec["id"]), kind="no_show")
            assert outcome["fee_pct"] == 30 and outcome["fee_cents"] == 2400
        finally:
            with api_module._get_db_connection() as connection:
                connection.execute("DELETE FROM bookings WHERE id = ?", (rec["id"],))
                connection.execute("DELETE FROM booking_audit WHERE booking_id = ?", (rec["id"],))
                connection.commit()
    finally:
        with api_module._get_db_connection() as connection:
            if slug:
                connection.execute("DELETE FROM services WHERE cliente_id='demo' AND slug=?", (slug,))
            connection.execute("DELETE FROM cancellation_policies WHERE cliente_id = 'demo'")
            connection.commit()


def test_granular_permissions(client: TestClient, api_module):
    owner_cookies = _portal_admin_cookies(api_module)
    # Crea un usuario staff real en el tenant demo (evita limites de plan).
    staff = api_module._create_user(
        email="staff_perm@example.com", password="staffpass123", role="client",
        display_name="Recepcion Test", cliente_id="demo", portal_role="staff",
    )
    staff_id = staff["id"]
    staff_cookies = {"vantelia_portal_session": api_module._create_auth_session(staff_id)}
    created_bookings = []
    try:
        # --- Defaults de rol staff ---
        me = client.get("/auth/me", cookies=staff_cookies).json()
        perms = set(me.get("permissions") or [])
        assert "agenda.cancel" in perms
        assert "payments.refund" not in perms
        assert "reports.view" not in perms
        assert "channels.manage" not in perms

        # staff no ve informes ni reembolsa
        assert client.get("/auth/analytics/overview", cookies=staff_cookies).status_code == 403
        assert client.post("/auth/bookings/nope/payment/refund", cookies=staff_cookies, json={}).status_code == 403

        # --- Owner afina permisos del staff ---
        r = client.put(
            f"/auth/app/team/{staff_id}/permissions", params={"cliente_id": "demo"}, cookies=owner_cookies,
            json={"overrides": {"reports.view": "allow", "agenda.cancel": "deny", "channels.manage": "allow"}},
        )
        assert r.status_code == 200, r.text

        # reports.view concedido -> 200; channels.manage NO delegable -> sigue sin efecto
        me2 = client.get("/auth/me", cookies=staff_cookies).json()
        perms2 = set(me2.get("permissions") or [])
        assert "reports.view" in perms2
        assert "agenda.cancel" not in perms2
        assert "channels.manage" not in perms2
        assert client.get("/auth/analytics/overview", cookies=staff_cookies).status_code == 200

        # agenda.cancel denegado -> cancelar una cita real da 403
        rec = _build_booking_record(api_module, booking_time="11:00")
        api_module._store_booking(rec); created_bookings.append(rec["id"])
        cc = client.post(f"/auth/bookings/{rec['id']}/cancel", cookies=staff_cookies)
        assert cc.status_code == 403, cc.text

        # El owner (admin) sigue pudiendo cancelar
        ok = client.post(f"/auth/bookings/{rec['id']}/cancel", cookies=owner_cookies)
        assert ok.status_code == 200, ok.text

        # GET permissions refleja override y owner_only bloqueado
        detail = client.get(f"/auth/app/team/{staff_id}/permissions", params={"cliente_id": "demo"}, cookies=owner_cookies).json()
        by_key = {it["key"]: it for it in detail["items"]}
        assert by_key["reports.view"]["override"] == "allow" and by_key["reports.view"]["effective"] is True
        assert by_key["agenda.cancel"]["override"] == "deny" and by_key["agenda.cancel"]["effective"] is False
        assert by_key["channels.manage"]["owner_only"] is True and by_key["channels.manage"]["effective"] is False
    finally:
        with api_module._get_db_connection() as connection:
            for bid in created_bookings:
                connection.execute("DELETE FROM bookings WHERE id = ?", (bid,))
                connection.execute("DELETE FROM booking_audit WHERE booking_id = ?", (bid,))
            connection.execute("DELETE FROM user_permission_overrides WHERE user_id = ?", (staff_id,))
            connection.commit()
        api_module._delete_user(staff_id)


def test_voice_audio_input_config_noise_and_vad(api_module):
    # Defaults: far_field + server_vad agil pero estable (0.65 s) + interrupt + whisper.
    cfg = api_module._voice_audio_input_config({})
    assert cfg["noise_reduction"]["type"] == "far_field"
    assert cfg["turn_detection"]["type"] == "server_vad"
    assert cfg["turn_detection"]["silence_duration_ms"] == 650
    assert cfg["turn_detection"]["threshold"] == 0.72
    assert cfg["turn_detection"]["interrupt_response"] is True
    assert cfg["transcription"]["model"] == "whisper-1"
    # Navegador: near_field por defecto.
    assert api_module._voice_audio_input_config({}, default_noise="near_field")["noise_reduction"]["type"] == "near_field"
    # Override por tenant: tiempo de respuesta + umbral.
    over = api_module._voice_audio_input_config({"noise_reduction": "near_field", "vad_silence_ms": 800, "vad_threshold": 0.7})
    assert over["noise_reduction"]["type"] == "near_field"
    assert over["turn_detection"]["silence_duration_ms"] == 800
    assert over["turn_detection"]["threshold"] == 0.7
    # Clamp de silencio a rango seguro.
    assert api_module._voice_audio_input_config({"vad_silence_ms": 50})["turn_detection"]["silence_duration_ms"] == 200
    assert api_module._voice_audio_input_config({"vad_silence_ms": 9000})["turn_detection"]["silence_duration_ms"] == 2000
    # Opt-in semantic_vad si se prefiere robustez sobre velocidad.
    sem = api_module._voice_audio_input_config({"vad_type": "semantic_vad"})
    assert sem["turn_detection"]["type"] == "semantic_vad"
    assert sem["turn_detection"]["eagerness"] == "high"
    # Valores invalidos -> fallback seguro.
    bad = api_module._voice_audio_input_config({"noise_reduction": "xxx", "vad_type": "turbo"})
    assert bad["noise_reduction"]["type"] == "far_field"
    assert bad["turn_detection"]["type"] == "server_vad"


def test_voice_is_unintelligible(api_module):
    for empty in ["", "   ", "...", "¿?", "-", "a"]:
        assert api_module._voice_is_unintelligible(empty) is True, empty
    for real in ["ok", "si", "hola", "los servicios", "no"]:
        assert api_module._voice_is_unintelligible(real) is False, real
    for artifact in [
        "Subtitulos realizados por la comunidad de Amara.org",
        "SubtÃ­tulos realizados por la comunidad de Amara.org",
        "Diosos mios",
        "Y alas",
    ]:
        assert api_module._voice_is_unintelligible(artifact) is True, artifact
    assert api_module._voice_is_unintelligible("a las once y media") is False



def test_voice_confirmation_acceptance_needs_nudge(api_module):
    asked = "Perfecto, repito: Pablo Sanchez, telefono 675 802 001, masaje el lunes a la una. ¿Confirmas que es correcto?"
    for yes in ["Si", "sí, correcto", "vale", "adelante", "resérvala", "confirmo"]:
        assert api_module._voice_confirmation_acceptance_needs_nudge(asked, yes) is True, yes
    assert api_module._voice_confirmation_acceptance_needs_nudge(asked, "no, espera") is False
    assert api_module._voice_confirmation_acceptance_needs_nudge("A esa hora hay hueco.", "si") is False
    assert api_module._voice_booking_confirmation_prompt_seen(asked) is True
    assert api_module._voice_booking_confirmation_prompt_seen("A esa hora hay hueco.") is False


def test_voice_extract_booking_contact_from_text(api_module):
    contact = api_module._voice_extract_booking_contact_from_text("Pablo Sanchez, 675 802 001")
    assert contact["nombre"] == "Pablo Sanchez"
    assert contact["telefono"].endswith("675802001")
    assert api_module._voice_extract_booking_contact_from_text("675 802") == {}


def test_voice_instructions_forbid_announce_before_tool(api_module):
    config = api_module._get_client_config("demo")
    text = api_module._voice_build_instructions("demo", config).lower()
    # Version flexible: no scripting rigido, pero mantiene la guia clave "no anuncies, llama
    # a la herramienta directamente" y las reglas de exactitud (fecha, horas de la tool).
    assert "nunca anuncies que vas a mirar" in text
    assert "no digas 'un momento'" in text
    assert "en el acto" in text
    assert "fecha_texto" in text
    assert "nunca confirmes un dia distinto" in text
    # Solo horas que devuelva la herramienta (no inventadas).
    assert "solo puedes ofrecer o aceptar horas que la herramienta" in text
    # Ya no debe quedar el scripting verbatim antiguo.
    assert "prohibido anunciar y callarte" not in text
    assert "di exactamente esta frase" not in text


def test_voice_instructions_strip_chat_menu_footer(api_module):
    config = api_module._get_client_config("demo")
    text = api_module._voice_build_instructions("demo", config)
    assert "FLUJO_DE_MENU_ACTIVO" not in text
    assert "Cierra siempre con una linea separada" not in text
    assert "Escribe **menu** para volver" not in text
    assert "Escribe **menú** para volver" not in text
    assert "nunca digas 'escribe menu'" in text.lower()


def test_voice_multilocation_prompt_and_tools_use_real_location_names(vantelia_env_factory):
    cfg = {
        "voicecenters": {
            "nombre": "Van",
            "empresa": "Clinica QA",
            "bienvenida": "Hola, soy Van.",
            "allowed_origins": ["http://testserver"],
            "contacto": {"email": "qa@example.com", "telefono": "+34600000000"},
            "branding": {"powered_by": "Vantelia"},
            "plan": "business",
            "subscription": {"plan": "business", "status": "active"},
            "booking": {
                "enabled": True,
                "timezone": "Europe/Madrid",
                "slot_minutes": 30,
                "day_start": "09:00",
                "day_end": "17:00",
                "closed_weekdays": [6],
                "provider": "internal",
            },
            "voice": {"enabled": True},
        }
    }
    api = vantelia_env_factory(cfg, info_txt={"voicecenters": "SERVICIOS Y PRECIOS:\n"})
    client = TestClient(api.app)
    user = api._get_user_by_email("admin@example.com")
    cookies = {"vantelia_portal_session": api._create_auth_session(user["id"])}
    params = {"cliente_id": "voicecenters"}

    default_loc = next(
        item for item in client.get("/auth/locations", params=params, cookies=cookies).json()["items"]
        if item["is_default"]
    )
    client.post(
        f"/auth/locations/{default_loc['location_id']}",
        params=params,
        cookies=cookies,
        json={"name": "Sede Centro", "address": "Calle Mayor 1", "phone": "910000001"},
    )
    client.post(
        "/auth/locations",
        params=params,
        cookies=cookies,
        json={"name": "Sede Norte", "address": "Avenida del Parque 22", "phone": "910000002"},
    )

    text = api._voice_build_instructions("voicecenters", api._get_client_config("voicecenters"))
    assert "CENTROS REALES DEL NEGOCIO" in text
    assert "- Sede Centro: Calle Mayor 1" in text
    assert "- Sede Norte: Avenida del Parque 22" in text
    assert "las direcciones NO son centros" in text

    tools = api._voice_booking_tools("voicecenters", api._get_client_config("voicecenters"))
    by_name = {tool["name"]: tool for tool in tools}
    centro = by_name["consultar_disponibilidad"]["parameters"]["properties"]["centro"]
    assert centro["enum"] == ["Sede Centro", "Sede Norte"]
    assert "no uses direcciones" in centro["description"]

    parts = api._voice_extract_booking_request_parts("voicecenters", "En la sede Norte.", config=api._get_client_config("voicecenters"))
    assert parts["centro"] == "Sede Norte"
    parts = api._voice_extract_booking_request_parts("voicecenters", "En la sede Centro.", config=api._get_client_config("voicecenters"))
    assert parts["centro"] == "Sede Centro"


def test_voice_booking_rejects_placeholder_contact(api_module):
    """El modelo no puede inventar contacto: telefono placeholder (000000000) o nombre
    generico ("Cliente") se rechazan con guia para pedir los datos reales (visto en QA
    real: cita creada con contacto basura)."""
    assert api_module._voice_normalize_booking_phone("000000000") == ""
    assert api_module._voice_normalize_booking_phone("111 111 111") == ""
    assert api_module._voice_normalize_booking_phone("123456789") == ""  # empieza por 1
    assert api_module._voice_normalize_booking_phone("675 802 001").endswith("675802001")
    assert api_module._voice_normalize_booking_phone("+34 912 345 678").endswith("912345678")

    result = asyncio.run(api_module._voice_perform_booking(
        "demo", nombre="Cliente", telefono="675802001",
        fecha="2099-01-02", hora="10:00", servicio="Masaje",
    ))
    assert result["ok"] is False
    assert result.get("missing_field") == "nombre"
    assert "nombre" in result.get("mensaje_voz", "").lower()


def test_voice_otp_tools_hidden_when_disabled(api_module, monkeypatch: pytest.MonkeyPatch):
    """OTP desactivado por config -> enviar_codigo_verificacion y verificar_codigo NO se
    exponen al modelo (camino muerto visto en QA real: bucle reintentando el codigo en vez
    de caer a verificacion por telefono/email)."""
    config = api_module._get_client_config("demo")
    monkeypatch.setattr(api_module, "_voice_otp_enabled", lambda cliente_id: False)
    names = {t["name"] for t in api_module._voice_booking_tools("demo", config)}
    assert "enviar_codigo_verificacion" not in names
    assert "verificar_codigo" not in names
    assert "cancelar_cita" in names and "reprogramar_cita" in names
    monkeypatch.setattr(api_module, "_voice_otp_enabled", lambda cliente_id: True)
    names_on = {t["name"] for t in api_module._voice_booking_tools("demo", config)}
    assert "enviar_codigo_verificacion" in names_on and "verificar_codigo" in names_on


def test_voice_send_code_failure_guides_contact_fallback(api_module, monkeypatch: pytest.MonkeyPatch):
    """Si el codigo no se puede enviar (OTP off o sin canal enviable), el error GUIA al
    modelo hacia la verificacion por telefono/email en cancelar/reprogramar, nunca un
    callejon sin salida."""
    record = _build_booking_record(api_module)
    try:
        api_module._store_booking(record)
        code = record["booking_code"]
        # OTP desactivado
        monkeypatch.setattr(api_module, "_voice_otp_enabled", lambda cliente_id: False)
        r1 = asyncio.run(api_module._voice_send_verification_code("demo", code))
        assert r1["ok"] is False and r1.get("fallback_contact_verification") is True
        assert "cancelar_cita o reprogramar_cita" in r1["error"]
        # OTP activo pero sin canal enviable (sin SMS/WhatsApp/email utilizables)
        monkeypatch.setattr(api_module, "_voice_otp_enabled", lambda cliente_id: True)
        monkeypatch.setattr(api_module, "_voice_pick_otp_channel", lambda *_a, **_k: ("", "", ""))
        r2 = asyncio.run(api_module._voice_send_verification_code("demo", code))
        assert r2["ok"] is False and r2.get("fallback_contact_verification") is True
        assert "cancelar_cita o reprogramar_cita" in r2["error"]
        assert "no tiene telefono ni email" not in r2["error"]
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_voice_booking_tools_require_spoken_date_text(api_module):
    config = api_module._get_client_config("demo")
    tools = api_module._voice_booking_tools("demo", config)
    by_name = {tool["name"]: tool for tool in tools}

    availability_required = by_name["consultar_disponibilidad"]["parameters"]["required"]
    booking_required = by_name["crear_cita"]["parameters"]["required"]

    assert "fecha_texto" in availability_required
    assert "fecha_texto" in booking_required
    assert by_name["consultar_disponibilidad"]["parameters"]["properties"]["fecha_texto"]
    assert by_name["crear_cita"]["parameters"]["properties"]["fecha_texto"]


def test_voice_booking_slot_required_response(api_module):
    result = api_module._voice_booking_slot_required_response(
        {"fecha": "2026-07-02"},
        config=api_module._get_client_config("demo"),
    )
    assert result["needs_slot"] is True
    assert "hora" in result["mensaje_voz"].lower()


def test_voice_availability_followup_does_not_confirm_before_customer_data(api_module):
    followup = api_module._voice_tool_followup_prompt(
        "consultar_disponibilidad",
        {
            "ok": True,
            "hora": "13:00",
            "hora_disponible": True,
            "mensaje_voz": "Si, a esa hora hay hueco. Para dejarla reservada necesito tu nombre completo y telefono.",
        },
    )
    assert "pide solo nombre completo y telefono" in followup
    assert "No digas 'repito'" in followup
    assert "aun no tienes los datos" in followup


def test_voice_requirements_document_mentions_spoken_date_contract():
    text = (REPO_ROOT / "docs" / "REQUISITOS_ASISTENTE_VOZ.md").read_text(encoding="utf-8")
    assert "Fechas habladas blindadas" in text
    assert "fecha_texto" in text
    assert "primero actúa, luego habla con el resultado" in text


def test_voice_requirements_document_mentions_anti_silence_suite():
    text = (REPO_ROOT / "docs" / "REQUISITOS_ASISTENTE_VOZ.md").read_text(encoding="utf-8")
    assert "Contrato anti-silencio" in text
    assert "qa_voice_realtime_silence.py" in text
    assert "No puede haber turnos de usuario sin respuesta nueva" in text


def test_browser_voice_bridge_matches_twilio_recovery_contract():
    widget = (REPO_ROOT / "widget" / "voice.js").read_text(encoding="utf-8")
    portal = (REPO_ROOT / "app_ui" / "index.html").read_text(encoding="utf-8")
    core = (REPO_ROOT / "widget" / "voice_core.js").read_text(encoding="utf-8")
    minified = (REPO_ROOT / "widget" / "widget.min.js").read_text(encoding="utf-8")

    # La lógica determinista PURA (detección de intención/silencio, normalización, construcción
    # de instrucciones) vive UNA sola vez en voice_core.js. Antes estaba duplicada literalmente
    # en widget/voice.js y app_ui/index.html (de ahí este test "match"); ahora la fuente única es
    # el núcleo y ambos clientes lo consumen.
    for needle in (
        "needs_location",
        "needs_slot",
        "subtitulos realizados por la comunidad de amara",
        "diosos",
        "isUnintelligibleText",
        "toolResponseInstruction",
        "CONTINUE_NUDGE_TEXT",
    ):
        assert needle in core, needle
    # Version flexible: los resultados de tool se transmiten NATURAL (no verbatim).
    assert "Di exactamente esta frase" not in core

    # Cada cliente conserva su bucle CON ESTADO (watchdog + cancelación técnica) y consume el
    # núcleo compartido. En silencio real da UN empujon interno (continueNudge), sin frases fijas.
    for source in (widget, portal):
        assert "voice_core.js" in source or "VanteliaVoiceCore" in source
        assert "SILENCE_WATCHDOG_MS" in source
        assert "ACTIVE_RESPONSE_GRACE_MS" in source
        assert "responseActiveStartedAt" in source
        assert "response.cancel" in source
        assert "responseCancelPending" in source
        assert "armPostCancelWatchdog" in source
        assert "setTimeout(runSilenceWatchdog, 180)" not in source
        assert "isUnintelligibleText" in source
        assert "armSilenceWatchdog" in source
        assert "toolResponseInstruction" in source
        assert "continueNudge" in source
        assert "CONTINUE_NUDGE_TEXT" in source
        # Se elimino el scripting rigido (frases verbatim y "no te he entendido").
        assert "Di exactamente esta frase y nada mas" not in source
        assert "no te he entendido" not in source.lower()

    assert "needs_location" in minified
    assert "response.cancel" in minified
    assert "responseCancelPending" in minified
    assert "responseActiveStartedAt" in minified
    assert "subtitulos realizados por la comunidad de amara" in minified
    # El empujon interno viaja al bundle; el scripting verbatim ya no.
    assert "Continua la conversacion de forma" in minified
    assert "Di exactamente esta frase y nada mas" not in minified


def test_twilio_voice_bridge_cancels_silent_active_response():
    # La logica determinista del puente Twilio vive ahora en backend/voice_engine.py
    # (VoiceCallEngine); voice_web.py solo transporta y delega. Contrato sobre el motor.
    engine_src = (REPO_ROOT / "backend" / "voice_engine.py").read_text(encoding="utf-8")
    assert "response.cancel" in engine_src
    assert "response_cancel_pending" in engine_src
    assert "active_response_grace_seconds" in engine_src
    assert "response_active_started_at" in engine_src
    assert "active_response_silent" in engine_src
    assert "unintelligible_user" in engine_src
    # Version flexible: el watchdog da UN empujon interno (el modelo reformula), sin frases fijas.
    assert "_nudge_continue" in engine_src
    assert "no te he entendido" not in engine_src.lower()
    # El puente sigue delegando en el motor y cableando el transporte (clear playback).
    bridge_src = (REPO_ROOT / "backend" / "routers" / "voice_web.py").read_text(encoding="utf-8")
    assert "VoiceCallEngine" in bridge_src
    assert "engine.on_openai_event" in bridge_src
    assert "engine.maybe_recover_silence" in bridge_src
    assert "_voice_clear_twilio_playback" in bridge_src


def test_voice_specific_time_available_asks_for_data_without_claiming_booking(api_module):
    msg = api_module._voice_specific_time_availability_message(
        "demo",
        "2099-01-02",
        "16:00",
        all_slots={"16:00"},
        available_slots={"16:00"},
    ).lower()
    assert "hay hueco" in msg
    assert "nombre completo" in msg
    assert "telefono" in msg
    assert "voy a" not in msg
    assert "reservada" in msg


def test_voice_phone_match_tolerates_missing_prefix(api_module):
    # El cliente puede dictar el telefono de verificacion sin prefijo (+34): la correspondencia
    # es por los ultimos 9 digitos, asi que con o sin prefijo debe casar.
    from backend import crm
    a = crm._normalize_phone_for_match("600123456")
    b = crm._normalize_phone_for_match("+34 600 123 456")
    c = crm._normalize_phone_for_match("0034600123456")
    assert a == b == c == "600123456"
    # Y el prompt le dice al asistente que acepte el numero sin prefijo.
    text = api_module._voice_build_instructions("demo", api_module._get_client_config("demo")).lower()
    assert "con o sin prefijo" in text


def test_voice_transfer_and_hangup_tools_config_and_prompt(api_module):
    # Numero de transferencia: normaliza 9 digitos ES; vacio si no hay.
    assert api_module._voice_transfer_number({"transfer_number": "600111222"}) == "+34600111222"
    assert api_module._voice_transfer_number({}) == ""
    cfg = api_module._get_client_config("demo")
    names = {t["name"] for t in api_module._voice_booking_tools("demo", cfg)}
    assert "finalizar_llamada" in names          # colgar limpio siempre disponible
    assert "transferir_a_humano" not in names     # demo no tiene numero de transferencia
    cfg2 = dict(cfg)
    cfg2["voice"] = dict(cfg2.get("voice") or {})
    cfg2["voice"]["transfer_number"] = "600111222"
    names2 = {t["name"] for t in api_module._voice_booking_tools("demo", cfg2)}
    assert "transferir_a_humano" in names2        # con numero, se ofrece la transferencia
    text = api_module._voice_build_instructions("demo", cfg).lower()
    assert "transferir_a_humano" in text and "finalizar_llamada" in text


def test_voice_conversation_dict_exposes_outcome_label(api_module):
    # El resultado etiquetado se expone en Conversaciones del portal del cliente (pestana Chats).
    assert api_module.VOICE_OUTCOME_LABELS["cancelada"] == "Cita cancelada"
    assert api_module.VOICE_OUTCOME_LABELS["transferida"] == "Pasada a una persona"
    assert "sin_accion" not in api_module.VOICE_OUTCOME_LABELS  # sin accion no pone etiqueta


def test_voice_dispatch_finalizar_and_transfer(api_module):
    r = asyncio.run(api_module._voice_dispatch_tool("demo", "finalizar_llamada", "{}"))
    assert r["ok"] is True and r.get("end_call") is True
    # Sin numero de transferencia en demo: no transfiere, toma nota.
    r2 = asyncio.run(api_module._voice_dispatch_tool("demo", "transferir_a_humano", "{}"))
    assert r2["ok"] is False


def test_voice_instructions_have_resume_protocol(api_module):
    config = api_module._get_client_config("demo")
    text = api_module._voice_build_instructions("demo", config).lower()
    assert "no te he pillado" in text
    assert "sigo contandote" in text or "continues con lo que" in text
    # Listar por trozos para sonar humano.
    assert "trozos" in text or "dos o tres" in text
    assert "catalogo real de servicios" in text
    assert "responde solo con los datos de esta lista" in text
    assert "si hay catalogo real de servicios arriba, ese catalogo manda" in text
    assert "si el cliente lo da o dice que prefiere recibir avisos por email" in text


def test_conversations_unify_web_whatsapp_and_voice(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    params = {"cliente_id": "demo"}
    now = api_module._utc_now_iso()
    suffix = uuid.uuid4().hex[:8]
    web_id = f"sess_web_{suffix}"
    wa_id = f"sess_wa_{suffix}"
    call_sid = f"CA_{suffix}"
    try:
        with api_module._get_db_connection() as conn:
            for sid, origin in ((web_id, "https://acme.example"), (wa_id, "whatsapp:+34611000111")):
                conn.execute(
                    "INSERT INTO chat_sessions (id, cliente_id, origin, user_agent, started_at, last_message_at, message_count, intents_json) "
                    "VALUES (?, 'demo', ?, '', ?, ?, 1, '[]')",
                    (sid, origin, now, now),
                )
                conn.execute(
                    "INSERT INTO chat_messages (session_id, cliente_id, role, content, intent, created_at) VALUES (?, 'demo', 'user', ?, '', ?)",
                    (sid, f"hola desde {origin}", now),
                )
            conn.execute(
                "INSERT INTO voice_calls (call_sid, cliente_id, from_number, started_at, ended_at, duration_seconds, status, transcript_json, summary, booking_created) "
                "VALUES (?, 'demo', '+34699888777', ?, ?, 125, 'completed', ?, 'Cliente pidió cita de masaje.', 1)",
                (call_sid, now, now, json.dumps([
                    {"role": "assistant", "text": "Hola, ¿en qué le ayudo?", "ts": now},
                    {"role": "user", "text": "Quiero un masaje el martes", "ts": now},
                ], ensure_ascii=False)),
            )
            conn.commit()
            voice_pk = conn.execute("SELECT id FROM voice_calls WHERE call_sid=?", (call_sid,)).fetchone()["id"]

        # Lista unificada: aparecen los 3 canales con su etiqueta.
        data = client.get("/auth/conversations", params=params, cookies=cookies).json()
        by_id = {it["id"]: it for it in data["items"]}
        assert by_id[web_id]["channel"] == "web"
        assert by_id[wa_id]["channel"] == "whatsapp" and "+34611000111" in by_id[wa_id]["contact"]
        voice_item = by_id[str(voice_pk)]
        assert voice_item["channel"] == "voice" and voice_item["kind"] == "voice"
        assert voice_item["duration_seconds"] == 125 and voice_item["booking_created"] is True

        # Filtro por canal.
        voz = client.get("/auth/conversations", params={**params, "channel": "voice"}, cookies=cookies).json()
        assert all(it["channel"] == "voice" for it in voz["items"])
        assert str(voice_pk) in {it["id"] for it in voz["items"]}

        # Detalle de voz: transcripción + resumen.
        det = client.get(f"/auth/conversations/voice/{voice_pk}", params=params, cookies=cookies).json()
        assert det["summary_text"].startswith("Cliente pidió")
        assert [m["content"] for m in det["messages"]] == ["Hola, ¿en qué le ayudo?", "Quiero un masaje el martes"]

        # Detalle de chat WhatsApp.
        det2 = client.get(f"/auth/conversations/chat/{wa_id}", params=params, cookies=cookies).json()
        assert det2["conversation"]["channel"] == "whatsapp"
        assert det2["messages"][0]["content"].startswith("hola desde whatsapp")
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM chat_messages WHERE session_id IN (?, ?)", (web_id, wa_id))
            conn.execute("DELETE FROM chat_sessions WHERE id IN (?, ?)", (web_id, wa_id))
            conn.execute("DELETE FROM voice_calls WHERE call_sid=?", (call_sid,))
            conn.commit()


def test_demo_commerce_seed_and_purge(api_module):
    counts = api_module._seed_demo_commerce("demo")
    assert counts["locations"] >= 1 and counts["products"] >= 1
    assert counts["packages"] >= 1 and counts["gift_cards"] >= 1 and counts["sales"] >= 1
    try:
        with api_module._get_db_connection() as c:
            assert c.execute("SELECT COUNT(*) FROM locations WHERE cliente_id='demo' AND id LIKE 'locdemo_%'").fetchone()[0] == counts["locations"]
            assert c.execute("SELECT COUNT(*) FROM products WHERE cliente_id='demo' AND id LIKE 'proddemo_%'").fetchone()[0] == counts["products"]
            assert c.execute("SELECT COUNT(*) FROM gift_cards WHERE cliente_id='demo' AND id LIKE 'gcdemo_%'").fetchone()[0] == counts["gift_cards"]
            assert c.execute("SELECT COUNT(*) FROM product_sales WHERE cliente_id='demo' AND id LIKE 'saledemo_%'").fetchone()[0] == counts["sales"]
            assert c.execute("SELECT COUNT(*) FROM packages WHERE cliente_id='demo' AND id LIKE 'pkgdemo_%'").fetchone()[0] == counts["packages"]
    finally:
        removed = api_module._purge_demo_commerce("demo")
    assert removed["locations_removed"] == counts["locations"]
    assert removed["products_removed"] == counts["products"]
    with api_module._get_db_connection() as c:
        for table, pref in (("locations", "locdemo_"), ("products", "proddemo_"), ("packages", "pkgdemo_"),
                            ("gift_cards", "gcdemo_"), ("product_sales", "saledemo_"),
                            ("package_purchases", "ppdemo_")):
            assert c.execute(f"SELECT COUNT(*) FROM {table} WHERE cliente_id='demo' AND id LIKE ?", (pref + "%",)).fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM gift_card_transactions WHERE cliente_id='demo' AND gift_card_id LIKE 'gcdemo_%'").fetchone()[0] == 0


def test_widget_voice_gating_and_public_flag(client: TestClient, api_module):
    # Por defecto la voz en widget esta desactivada.
    cfg = client.get("/cliente/demo", headers={"Origin": "http://testserver"}).json()
    assert cfg["voice_widget_enabled"] is False
    assert api_module._voice_widget_enabled("demo") is False
    # Endpoints publicos de voz del widget rechazan si no hay opt-in (403).
    r = client.post("/voice/widget/demo/session", headers={"Origin": "http://testserver"}, json={})
    assert r.status_code == 403
    r2 = client.post("/voice/widget/demo/tool", headers={"Origin": "http://testserver"},
                     json={"name": "consultar_disponibilidad", "arguments": "{}"})
    assert r2.status_code == 403


def test_reminders_call_gating(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    g = client.get("/auth/app/reminders", params={"cliente_id": "demo"}, cookies=cookies).json()
    assert g["call_fallback"] is False and g["daily_call_cap"] == 30
    assert g["voice_call_available"] is False  # demo sin numero de voz
    assert api_module._reminder_calls_ok_now("demo") is False
    rec = _build_booking_record(api_module, booking_time="13:00")
    api_module._store_booking(rec)
    try:
        # Sin Twilio/numero/plan -> no se puede llamar.
        res = api_module._voice_place_outbound_call("demo", api_module._get_booking_row_by_id(rec["id"]))
        assert res["ok"] is False
        r = client.post(f"/auth/bookings/{rec['id']}/confirm-call", cookies=cookies)
        assert r.status_code == 409
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id=?", (rec["id"],))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (rec["id"],))
            conn.commit()


def test_mark_booking_confirmed_by_customer(api_module):
    rec = _build_booking_record(api_module, booking_time="13:30", status="pending_review")
    api_module._store_booking(rec)
    rec_confirmed = _build_booking_record(api_module, booking_time="14:00", status="confirmed")
    rec_confirmed["confirmed_at"] = ""
    api_module._store_booking(rec_confirmed)
    try:
        assert api_module._mark_booking_confirmed_by_customer(rec["id"], "demo", channel="voice_outbound") is True
        row = api_module._get_booking_row_by_id(rec["id"])
        assert row["status"] == "confirmed"
        assert row["confirmed_at"]
        assert api_module._mark_booking_confirmed_by_customer(
            rec_confirmed["id"], "demo", channel="voice_outbound"
        ) is True
        row_confirmed = api_module._get_booking_row_by_id(rec_confirmed["id"])
        assert row_confirmed["status"] == "confirmed"
        assert row_confirmed["confirmed_at"]
        events = [r["event_type"] for r in api_module._list_booking_audit_rows(rec["id"])]
        assert "attendance_confirmed_by_customer" in events
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id=?", (rec["id"],))
            conn.execute("DELETE FROM bookings WHERE id=?", (rec_confirmed["id"],))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (rec["id"],))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (rec_confirmed["id"],))
            conn.commit()


def test_alerts_and_widget_voice_log_gating(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    a = client.get("/auth/app/alerts", params={"cliente_id": "demo"}, cookies=cookies)
    assert a.status_code == 200
    body = a.json()
    assert "total" in body and isinstance(body.get("items"), list)
    # Log de voz del widget sin opt-in -> 403.
    r = client.post("/voice/widget/demo/log", headers={"Origin": "http://testserver"},
                    json={"transcript": [{"role": "user", "text": "hola"}], "duration_seconds": 5})
    assert r.status_code == 403


def test_widget_voice_log_stores_outcome(client: TestClient, api_module, monkeypatch: pytest.MonkeyPatch):
    """Las llamadas de voz del navegador etiquetan su resultado (outcome) como las de
    telefono: el front lo acumula por tools ejecutadas y el /log lo persiste validado."""
    monkeypatch.setattr(api_module, "_voice_widget_enabled", lambda *_a, **_k: True)
    monkeypatch.setattr(api_module, "_voice_summarize", lambda *_a, **_k: "")
    call_sids = []
    try:
        for sent, expected in (("cancelada", "cancelada"), ("hackeo", "")):
            r = client.post(
                "/voice/widget/demo/log",
                headers={"Origin": "http://testserver"},
                json={
                    "transcript": [{"role": "user", "text": "quiero cancelar mi cita"}],
                    "duration_seconds": 12,
                    "outcome": sent,
                },
            )
            assert r.status_code == 200 and r.json().get("ok") is True
            with api_module._get_db_connection() as conn:
                row = conn.execute(
                    "SELECT call_sid, outcome FROM voice_calls WHERE cliente_id='demo' ORDER BY id DESC LIMIT 1"
                ).fetchone()
            call_sids.append(row["call_sid"])
            assert (row["outcome"] or "") == expected
    finally:
        with api_module._get_db_connection() as conn:
            for sid in call_sids:
                conn.execute("DELETE FROM voice_calls WHERE call_sid=?", (sid,))
            conn.commit()
