"""Canales de envio por cliente: por donde sale cada email y cada SMS.

Un negocio puede mandar sus correos por el SMTP de Vantelia o por su propio
Gmail (OAuth), y sus SMS por el Twilio global o por un remitente suyo. Aqui se
comprueba la eleccion (`emailing._send_client_email`, `_send_client_sms`), el
baile OAuth completo (PKCE, state firmado de un solo uso, tokens cifrados con
Fernet) y que un remitente sin aprobar NO pueda enviar todavia.

Ningun test manda nada de verdad: los transportes van con dobles.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet

from backend import channel_requests
from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401


@pytest.fixture(autouse=True)
def channel_crypto(api_module, monkeypatch):
    monkeypatch.setattr(api_module, "OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())


def _seed_gmail(api_module, cliente_id: str = "demo", *, status: str = "active"):
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_oauth_connections
                (cliente_id, provider, account_email, account_name, scopes_json,
                 access_token_encrypted, refresh_token_encrypted, expires_at,
                 status, created_at, updated_at)
            VALUES (?, 'gmail_oauth', ?, 'Cuenta Demo', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id, provider) DO UPDATE SET
                account_email=excluded.account_email, access_token_encrypted=excluded.access_token_encrypted,
                refresh_token_encrypted=excluded.refresh_token_encrypted, expires_at=excluded.expires_at,
                status=excluded.status, updated_at=excluded.updated_at
            """,
            (
                cliente_id,
                f"{cliente_id}@example.com",
                json.dumps([api_module.GOOGLE_GMAIL_SEND_SCOPE]),
                api_module._encrypt_channel_secret("access-secret"),
                api_module._encrypt_channel_secret("refresh-secret"),
                (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                status,
                now,
                now,
            ),
        )
        connection.commit()


def _seed_channel_booking(api_module, booking_id: str, cliente_id: str = "demo"):
    start = datetime.now(timezone.utc) + timedelta(days=2)
    iso = lambda d: d.isoformat(timespec="seconds").replace("+00:00", "") + "Z"
    api_module._store_booking({
        "id": booking_id, "cliente_id": cliente_id, "employee_id": "", "employee_name": "",
        "nombre": "Cliente Canal", "email": "cliente@example.com", "telefono": "+34600111222",
        "servicio": "Consulta", "booking_date": start.date().isoformat(), "booking_time": start.strftime("%H:%M"),
        "notas": "", "status": "confirmed", "provider_name": "internal", "provider_status": "confirmed",
        "provider_booking_id": "", "provider_booking_url": "", "manage_token": f"mg_{booking_id}",
        "timezone": "Europe/Madrid", "start_at": iso(start), "end_at": iso(start + timedelta(minutes=30)),
        "confirmed_at": iso(start), "cancelled_at": "", "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": "", "reminder_2h_sent_at": "",
        "customer_email_status": "", "customer_email_last_error": "", "source": "test", "created_at": iso(start),
    })


def test_channel_secrets_are_encrypted(api_module):
    encrypted = api_module._encrypt_channel_secret("super-secret-token")
    assert encrypted != "super-secret-token"
    assert "super-secret-token" not in encrypted
    assert api_module._decrypt_channel_secret(encrypted) == "super-secret-token"


def test_gmail_state_is_single_use_and_tenant_bound(api_module):
    state, verifier = api_module._gmail_channel_state_create("demo", "user-one")
    assert api_module._gmail_channel_state_consume(state, "demo", "user-one") == verifier
    with pytest.raises(api_module.HTTPException):
        api_module._gmail_channel_state_consume(state, "demo", "user-one")

    other_state, _ = api_module._gmail_channel_state_create("demo", "user-one")
    with pytest.raises(api_module.HTTPException):
        api_module._gmail_channel_state_consume(other_state, "otro", "user-one")


def test_gmail_state_rejects_expired_and_tampered(api_module):
    state, _ = api_module._gmail_channel_state_create("demo", "user-one")
    with api_module._get_db_connection() as connection:
        connection.execute(
            "UPDATE client_channel_oauth_states SET created_at=? WHERE state_hash=?",
            (api_module.time.time() - 700, api_module.hashlib.sha256(state.encode()).hexdigest()),
        )
        connection.commit()
    with pytest.raises(api_module.HTTPException):
        api_module._gmail_channel_state_consume(state, "demo", "user-one")
    with pytest.raises(api_module.HTTPException):
        api_module._gmail_channel_state_consume(state + "tampered", "demo", "user-one")


def test_gmail_connect_requests_only_send_scope(client, portal_cookies, api_module, monkeypatch):
    monkeypatch.setattr(api_module, "GOOGLE_GMAIL_CLIENT_ID", "client-id")
    monkeypatch.setattr(api_module, "GOOGLE_GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(api_module, "GOOGLE_GMAIL_REDIRECT_URL", "https://app.test/callback")
    response = client.post("/auth/app/channels/email/google/connect", cookies=portal_cookies)
    assert response.status_code == 200, response.text
    query = parse_qs(urlparse(response.json()["url"]).query)
    scopes = set(query["scope"][0].split())
    assert api_module.GOOGLE_GMAIL_SEND_SCOPE in scopes
    assert not any("readonly" in scope or "modify" in scope for scope in scopes)
    assert query["code_challenge_method"] == ["S256"]


def test_send_client_email_uses_gmail(api_module, monkeypatch):
    _seed_gmail(api_module)
    api_module._ensure_channel_settings("demo")
    with api_module._get_db_connection() as connection:
        connection.execute(
            "UPDATE client_channel_settings SET email_provider='gmail_oauth' WHERE cliente_id='demo'"
        )
        connection.commit()
    captured = {}
    monkeypatch.setattr(
        api_module,
        "_send_gmail_message",
        lambda cliente_id, row, to, subject, text, html="", reply_to=None: captured.update(
            {"cliente_id": cliente_id, "to": to, "from": row["account_email"]}
        ),
    )
    monkeypatch.setattr(
        api_module,
        "_send_email_message",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No debe usar SMTP")),
    )
    provider = api_module._send_client_email("demo", "target@example.com", "Asunto", "Texto")
    assert provider == "gmail_oauth"
    assert captured == {"cliente_id": "demo", "to": "target@example.com", "from": "demo@example.com"}


def test_booking_email_uses_connected_client_gmail(api_module, monkeypatch):
    _seed_gmail(api_module)
    api_module._ensure_channel_settings("demo")
    with api_module._get_db_connection() as connection:
        connection.execute(
            "UPDATE client_channel_settings SET email_provider='gmail_oauth' WHERE cliente_id='demo'"
        )
        connection.commit()

    captured = {}
    monkeypatch.setattr(
        api_module,
        "_send_gmail_message",
        lambda cliente_id, row, to, subject, text, html="", reply_to=None: captured.update(
            {"cliente_id": cliente_id, "to": to, "from": row["account_email"], "subject": subject}
        ),
    )
    monkeypatch.setattr(
        api_module,
        "_send_email_message",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No debe saltarse el canal del cliente")),
    )

    booking_id = "chanmail_" + uuid.uuid4().hex
    try:
        _seed_channel_booking(api_module, booking_id)
        provider = api_module._send_booking_email(api_module._get_booking_row_by_id(booking_id), "confirmed")
    finally:
        with api_module._get_db_connection() as connection:
            connection.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
            connection.commit()

    assert provider == "gmail_oauth"
    assert captured["cliente_id"] == "demo"
    assert captured["to"] == "cliente@example.com"
    assert captured["from"] == "demo@example.com"


def test_send_client_email_falls_back_to_vantelia(api_module, monkeypatch):
    _seed_gmail(api_module, status="error")
    api_module._ensure_channel_settings("demo")
    with api_module._get_db_connection() as connection:
        connection.execute(
            "UPDATE client_channel_settings SET email_provider='gmail_oauth', email_fallback_enabled=1 WHERE cliente_id='demo'"
        )
        connection.commit()
    captured = {}
    monkeypatch.setattr(api_module, "_send_email_message", lambda to, *a, **k: captured.update({"to": to}))
    assert api_module._send_client_email("demo", "fallback@example.com", "Asunto", "Texto") == "vantelia_smtp"
    assert captured["to"] == "fallback@example.com"


def test_client_smtp_settings_are_encrypted_and_used(client, portal_cookies, api_module, monkeypatch):
    api_module._ensure_channel_settings("demo")
    response = client.post(
        "/auth/app/channels/email/smtp/settings",
        cookies=portal_cookies,
        json={
            "host": "smtp.cliente.test",
            "port": 2525,
            "username": "reservas@cliente.test",
            "password": "smtp-client-secret",
            "starttls": True,
            "from_email": "reservas@cliente.test",
            "from_name": "Cliente Test",
            "reply_to": "info@cliente.test",
            "fallback_enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    email = response.json()["email"]
    assert email["provider"] == "client_smtp"
    assert email["smtp_configured"] is True
    assert email["smtp_password_configured"] is True

    row = api_module._ensure_channel_settings("demo")
    assert "smtp-client-secret" not in row["email_smtp_password_encrypted"]
    assert api_module._decrypt_channel_secret(row["email_smtp_password_encrypted"]) == "smtp-client-secret"

    captured = {}
    monkeypatch.setattr(
        api_module,
        "_send_client_smtp_message",
        lambda cliente_id, settings_row, to, subject, text, html="", reply_to=None: captured.update(
            {
                "cliente_id": cliente_id,
                "to": to,
                "host": settings_row["email_smtp_host"],
                "from": settings_row["email_smtp_from_email"],
            }
        ),
    )
    monkeypatch.setattr(
        api_module,
        "_send_email_message",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No debe usar el respaldo Vantelia")),
    )
    provider = api_module._send_client_email("demo", "destino@example.com", "Asunto", "Texto")
    assert provider == "client_smtp"
    assert captured == {
        "cliente_id": "demo",
        "to": "destino@example.com",
        "host": "smtp.cliente.test",
        "from": "reservas@cliente.test",
    }


def test_gmail_refresh_updates_encrypted_token(api_module, monkeypatch):
    _seed_gmail(api_module)
    with api_module._get_db_connection() as connection:
        connection.execute(
            "UPDATE client_oauth_connections SET expires_at=? WHERE cliente_id='demo' AND provider='gmail_oauth'",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),),
        )
        connection.commit()
    monkeypatch.setattr(
        api_module.httpx,
        "post",
        lambda *a, **k: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"access_token": "fresh-access-token", "expires_in": 3600},
        ),
    )
    row = api_module._client_gmail_connection("demo")
    assert api_module._client_gmail_access_token("demo", row) == "fresh-access-token"
    refreshed = api_module._client_gmail_connection("demo")
    assert refreshed["access_token_encrypted"] != "fresh-access-token"
    assert api_module._decrypt_channel_secret(refreshed["access_token_encrypted"]) == "fresh-access-token"


def test_disconnect_is_tenant_scoped(client, portal_cookies, api_module):
    _seed_gmail(api_module, "demo")
    _seed_gmail(api_module, "otro")
    response = client.post("/auth/app/channels/email/google/disconnect", cookies=portal_cookies)
    assert response.status_code == 200
    assert api_module._client_gmail_connection("demo") is None
    assert api_module._client_gmail_connection("otro") is not None


def test_sms_sender_pending_is_not_used(api_module, monkeypatch):
    api_module._ensure_channel_settings("demo")
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE client_channel_settings
            SET sms_mode='twilio_alphanumeric_sender', sms_sender='DEMO',
                sms_sender_status='pending_registration'
            WHERE cliente_id='demo'
            """
        )
        connection.commit()

    async def fail_send(*args, **kwargs):
        raise AssertionError("Un remitente pendiente no debe enviar")

    monkeypatch.setattr(api_module, "_send_twilio_sms", fail_send)
    assert asyncio.run(api_module._send_client_sms("demo", "+34600123456", "Prueba")) is False


def test_active_sms_sender_uses_provisioned_identity(api_module, monkeypatch):
    api_module._ensure_channel_settings("demo")
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE client_channel_settings
            SET sms_mode='twilio_alphanumeric_sender', sms_sender='DEMO',
                sms_sender_status='active',
                sms_twilio_account_sid_encrypted=?, sms_twilio_auth_token_encrypted=?
            WHERE cliente_id='demo'
            """,
            (api_module._encrypt_channel_secret("AC_SUB"), api_module._encrypt_channel_secret("sub-token")),
        )
        connection.commit()
    captured = {}

    async def capture(to, sender, body, **kwargs):
        captured.update({"to": to, "sender": sender, **kwargs})
        return True

    monkeypatch.setattr(api_module, "_send_twilio_sms", capture)
    assert asyncio.run(api_module._send_client_sms("demo", "+34600123456", "Prueba")) is True
    assert captured["sender"] == "DEMO"
    assert captured["account_sid"] == "AC_SUB"


def test_sms_settings_reject_arbitrary_dedicated_number(client, portal_cookies):
    response = client.post(
        "/auth/app/channels/sms/settings",
        cookies=portal_cookies,
        json={"mode": "twilio_dedicated_number", "sender": "+34600123456"},
    )
    assert response.status_code == 400


def test_channel_request_created_and_listed(client, portal_cookies, api_module, monkeypatch):
    monkeypatch.setattr(channel_requests.emailing, "_email_delivery_configured", lambda: False)
    response = client.post(
        "/auth/app/channels/requests",
        cookies=portal_cookies,
        json={
            "channel": "sms",
            "request_type": "alphanumeric_sender",
            "requested_sender": "demoid",
            "notes": "Alta de marca",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["cliente_id"] == "demo"
    assert data["requested_sender"] == "DEMOID"
    assert data["status"] == "pending"

    listing = client.get("/auth/app/channels/requests", cookies=portal_cookies)
    assert listing.status_code == 200
    assert any(item["id"] == data["id"] for item in listing.json())


def test_client_twilio_sms_settings_are_encrypted_and_active(client, portal_cookies, api_module):
    response = client.post(
        "/auth/app/channels/sms/twilio-settings",
        cookies=portal_cookies,
        json={
            "account_sid": "AC1234567890abcdef",
            "auth_token": "client-twilio-token",
            "sender_kind": "number",
            "sender": "+34600123456",
        },
    )
    assert response.status_code == 200, response.text
    sms = response.json()["sms"]
    assert sms["mode"] == "twilio_dedicated_number"
    assert sms["sender"] == "+34600123456"
    assert sms["sender_status"] == "active"

    row = api_module._ensure_channel_settings("demo")
    assert "client-twilio-token" not in row["sms_twilio_auth_token_encrypted"]
    assert api_module._decrypt_channel_secret(row["sms_twilio_auth_token_encrypted"]) == "client-twilio-token"


def test_admin_can_activate_sms_request(client, portal_cookies, api_module, monkeypatch):
    monkeypatch.setattr(channel_requests.emailing, "_email_delivery_configured", lambda: False)
    created = client.post(
        "/auth/app/channels/requests",
        cookies=portal_cookies,
        json={
            "channel": "sms",
            "request_type": "dedicated_number",
            "requested_phone": "+34600999888",
        },
    )
    assert created.status_code == 200, created.text
    request_id = created.json()["id"]
    headers = {"Authorization": "Bearer test-admin-token"}
    response = client.post(
        "/admin/clientes/demo/sms",
        headers=headers,
        json={
            "mode": "twilio_dedicated_number",
            "sender": "+34600999888",
            "sender_status": "active",
            "account_sid": "ACabcdef1234567890",
            "auth_token": "admin-twilio-token",
            "request_id": request_id,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["sms"]["available"] is True
    listed = client.get("/admin/channel-requests?status=active", headers=headers)
    assert listed.status_code == 200
    assert any(item["id"] == request_id for item in listed.json()["items"])


def test_follow_up_test_uses_vantelia_managed_sms(client, portal_cookies, api_module, monkeypatch):
    monkeypatch.setattr(api_module, "TWILIO_ACCOUNT_SID", "AC_GLOBAL")
    monkeypatch.setattr(api_module, "TWILIO_AUTH_TOKEN", "global-token")
    monkeypatch.setattr(api_module, "TWILIO_SMS_SENDER", "+18038849920")
    api_module._ensure_channel_settings("demo")
    with api_module._get_db_connection() as connection:
        connection.execute(
            "UPDATE client_channel_settings SET sms_mode='vantelia_default' WHERE cliente_id='demo'"
        )
        connection.commit()
    captured = {}

    async def capture_sms(to, sender, body, **kwargs):
        captured.update({"to": to, "sender": sender, "body": body})
        return True

    monkeypatch.setattr(api_module, "_send_twilio_sms", capture_sms)
    response = client.post(
        "/auth/app/follow-up/test",
        cookies=portal_cookies,
        json={
            "step": "reminder_24h",
            "phone": "+34600123456",
            "channels": {"email": False, "whatsapp": False, "sms": True},
        },
    )
    assert response.status_code == 200, response.text
    results = {item["channel"]: item for item in response.json()["results"]}
    assert results["sms"]["status"] == "sent"
    assert captured["sender"] == "+18038849920"
