from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet

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
