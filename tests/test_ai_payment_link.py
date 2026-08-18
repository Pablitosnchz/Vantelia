"""El asistente manda el enlace de pago, con todos los frenos puestos.

Opt-in por negocio, canal segun por donde reservo (voz -> SMS, resto -> email),
importe SIEMPRE de la politica del servicio (nunca del cliente), solo al
contacto ya registrado en la cita, Stripe conectado, dedup si ya esta pagada,
rate limit por cita y auditoria. Cada uno de esos frenos tiene su test: son los
que impiden que la IA cobre a quien no debe o cobre de mas.
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import (  # noqa: F401
    portal_cookies,
    _seed_connect_account,
    _seed_service,
)


def _seed_booking(api_module, suffix: str, *, source: str, email: str, telefono: str) -> str:
    """Crea una cita real con un origen/contacto concretos para probar el envio IA."""
    booking_id = f"bk_aipay_{suffix}"
    now = api_module._utc_now_iso()
    record = {
        "id": booking_id, "cliente_id": "demo", "employee_id": f"default_{suffix}",
        "employee_name": "Equipo", "nombre": "Cliente Pago", "email": email,
        "telefono": telefono, "servicio": "Consulta", "booking_date": "2099-06-15",
        "booking_time": "10:00", "notas": "", "status": "confirmed", "provider_name": "internal",
        "provider_status": "confirmed", "provider_booking_id": "", "provider_booking_url": "",
        "manage_token": f"manage_{suffix}", "timezone": "Europe/Madrid",
        "start_at": "2099-06-15T08:00:00+00:00", "end_at": "2099-06-15T08:30:00+00:00",
        "confirmed_at": now, "cancelled_at": "", "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": "", "reminder_2h_sent_at": "",
        "customer_email_status": "", "customer_email_last_error": "", "booking_code": "",
        "service_id": "consulta", "service_price_cents": 10000, "source": source, "created_at": now,
    }
    api_module._store_booking(record)
    return booking_id


def _booking_row(api_module, booking_id: str):
    return api_module._get_booking_row_by_id(booking_id)


def _seed_full_policy(api_module, cliente_id: str = "demo", service_id: str = "consulta") -> None:
    """Politica de cobro 'full': el importe sale del precio del servicio."""
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO service_payment_policies
                (cliente_id, service_id, mode, deposit_value, confirm_booking_on_paid, created_at, updated_at)
            VALUES (?, ?, 'full', 0, 1, ?, ?)
            ON CONFLICT(cliente_id, service_id) DO UPDATE SET mode='full', updated_at=excluded.updated_at
            """,
            (cliente_id, service_id, now, now),
        )
        connection.commit()


def _patch_stripe_ok(api_module, monkeypatch, suffix: str, captured: dict) -> None:
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(
        api_module.stripe.Account, "retrieve",
        lambda account_id: SimpleNamespace(charges_enabled=True, payouts_enabled=True, details_submitted=True),
    )

    def create_session(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=f"cs_{suffix}", url=f"https://checkout.test/{suffix}")

    monkeypatch.setattr(api_module.stripe.checkout.Session, "create", create_session)


@pytest.fixture(autouse=True)
def _isolate_payment_delivery(api_module, monkeypatch):
    """Los tests de pago no dependen del SMTP real ni envian correos."""
    monkeypatch.setattr(api_module, "_ai_payment_delivery_available", lambda cliente_id, method: True)
    monkeypatch.setattr(api_module, "_send_client_email", lambda *args, **kwargs: None)


def test_ai_send_uses_email_for_web_booking(api_module, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    _seed_full_policy(api_module)
    booking_id = _seed_booking(
        api_module, suffix, source="vantelia_widget",
        email=f"web-{suffix}@example.com", telefono="+34600123456",
    )
    captured_session: dict = {}
    _patch_stripe_ok(api_module, monkeypatch, suffix, captured_session)
    sent_email: dict = {}
    monkeypatch.setattr(
        api_module, "_send_client_email",
        lambda cliente_id, to, subject, text, html="", reply_to=None: sent_email.update(
            {"cliente_id": cliente_id, "to": to, "subject": subject, "text": text}
        ),
    )

    async def fail_sms(*args, **kwargs):
        raise AssertionError("Una cita web no debe enviar SMS.")

    monkeypatch.setattr(api_module, "_send_twilio_sms", fail_sms)

    result = asyncio.run(
        api_module._ai_send_payment_link("demo", _booking_row(api_module, booking_id))
    )
    assert result["ok"] is True
    assert result["method"] == "email"
    assert result["sent"] is True
    assert result["amount_cents"] == 10000  # precio completo del servicio
    assert sent_email["to"] == f"web-{suffix}@example.com"
    assert captured_session["stripe_account"] == "acct_demo"


def test_ai_send_uses_sms_for_voice_booking(api_module, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    _seed_full_policy(api_module)
    booking_id = _seed_booking(
        api_module, suffix, source="voice",
        email=f"voice-{suffix}@example.com", telefono="+34600999888",
    )
    captured_session: dict = {}
    _patch_stripe_ok(api_module, monkeypatch, suffix, captured_session)
    sent_sms: dict = {}

    async def capture_sms(to, sender, body):
        sent_sms.update({"to": to, "sender": sender, "body": body})
        return True

    monkeypatch.setattr(api_module, "_send_twilio_sms", capture_sms)
    monkeypatch.setattr(api_module, "_ai_payment_delivery_available", lambda cliente_id, method: method == "sms")
    monkeypatch.setattr(
        api_module, "_send_client_email",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Una cita de voz no debe enviar email.")),
    )

    result = asyncio.run(
        api_module._ai_send_payment_link("demo", _booking_row(api_module, booking_id))
    )
    assert result["ok"] is True
    assert result["method"] == "sms"
    assert result["sent"] is True
    assert sent_sms["to"] == "+34600999888"
    assert f"https://checkout.test/{suffix}" in sent_sms["body"]


def test_ai_send_amount_is_not_set_by_customer(api_module, monkeypatch):
    """El importe sale del servicio (10000), nunca de un override del cliente final."""
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    _seed_full_policy(api_module)
    booking_id = _seed_booking(
        api_module, suffix, source="whatsapp",
        email=f"wa-{suffix}@example.com", telefono="+34600123456",
    )
    captured_session: dict = {}
    _patch_stripe_ok(api_module, monkeypatch, suffix, captured_session)

    result = asyncio.run(
        api_module._ai_send_payment_link("demo", _booking_row(api_module, booking_id))
    )
    assert result["amount_cents"] == 10000
    assert captured_session["line_items"][0]["price_data"]["unit_amount"] == 10000


def test_payment_link_blocked_when_booking_already_paid_via_deposit(api_module):
    """Regresion doble cobro: una cita ya pagada por la reserva (bookings.payment_status
    ='paid', sin fila customer_payments) debe bloquear un segundo enlace de pago."""
    import sqlite3
    from fastapi import HTTPException

    suffix = uuid.uuid4().hex[:8]
    booking_id = _seed_booking(
        api_module, suffix, source="vantelia_widget",
        email=f"paid-{suffix}@example.com", telefono="",
    )
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("UPDATE bookings SET payment_status='paid' WHERE id=?", (booking_id,))
        conn.commit()
    with pytest.raises(HTTPException) as exc:
        api_module._create_customer_payment_link(
            "demo", _booking_row(api_module, booking_id), base_url="https://app.test.local"
        )
    assert exc.value.status_code == 409


def test_ai_send_blocked_when_stripe_is_not_charging(api_module, monkeypatch):
    """Ya no hay opt-in aparte (nadie lo encontraba y nacia apagado). Lo unico que
    apaga el envio es no tener los cobros operativos."""
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    with api_module._get_db_connection() as connection:
        connection.execute("UPDATE client_payment_accounts SET charges_enabled=0 WHERE cliente_id='demo'")
        connection.commit()
    booking_id = _seed_booking(
        api_module, suffix, source="whatsapp",
        email=f"off-{suffix}@example.com", telefono="+34600123456",
    )
    result = asyncio.run(
        api_module._ai_send_payment_link("demo", _booking_row(api_module, booking_id))
    )
    assert result["ok"] is False
    assert result["reason"] == "stripe_unavailable"


def test_ai_send_rejected_without_connected_stripe(api_module, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    # Opt-in activo pero SIN cuenta Stripe conectada.
    with api_module._get_db_connection() as connection:
        connection.execute("DELETE FROM client_payment_accounts WHERE cliente_id='demo'")
        connection.commit()
    _seed_service(api_module)
    booking_id = _seed_booking(
        api_module, suffix, source="whatsapp",
        email=f"nostripe-{suffix}@example.com", telefono="+34600123456",
    )
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    result = asyncio.run(
        api_module._ai_send_payment_link("demo", _booking_row(api_module, booking_id))
    )
    assert result["ok"] is False
    assert result["reason"] == "stripe_unavailable"


@pytest.mark.parametrize(
    ("source", "email", "telefono", "expected_method"),
    [
        ("vantelia_widget", "web@example.com", "+34600123456", "email"),
        ("whatsapp", "whatsapp@example.com", "+34600123456", "email"),
        ("voice", "voice@example.com", "+34600999888", "sms"),
    ],
)
def test_ai_send_rejected_before_checkout_when_required_channel_is_unavailable(
    api_module, monkeypatch, source, email, telefono, expected_method
):
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    _seed_full_policy(api_module)
    booking_id = _seed_booking(
        api_module, suffix, source=source, email=email, telefono=telefono,
    )
    captured_session: dict = {}
    _patch_stripe_ok(api_module, monkeypatch, suffix, captured_session)
    monkeypatch.setattr(api_module, "_ai_payment_delivery_available", lambda cliente_id, method: False)

    result = asyncio.run(
        api_module._ai_send_payment_link("demo", _booking_row(api_module, booking_id))
    )

    assert result["ok"] is False
    assert result["reason"] == "channel_unavailable"
    assert result["method"] == expected_method
    assert captured_session == {}


def test_ai_send_dedup_when_already_paid(api_module, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    _seed_full_policy(api_module)
    booking_id = _seed_booking(
        api_module, suffix, source="whatsapp",
        email=f"paid-{suffix}@example.com", telefono="+34600123456",
    )
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO customer_payments
                (id, cliente_id, booking_id, service_id, service_name, stripe_account_id,
                 amount_cents, status, created_at, updated_at)
            VALUES (?, 'demo', ?, 'consulta', 'Consulta', 'acct_demo', 10000, 'paid', ?, ?)
            """,
            (f"pay_{suffix}", booking_id, now, now),
        )
        connection.commit()
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    result = asyncio.run(
        api_module._ai_send_payment_link("demo", _booking_row(api_module, booking_id))
    )
    assert result["ok"] is False
    assert result["reason"] == "link_error"  # 409 ya pagado desde el core


def test_ai_send_rate_limited_after_two_links(api_module, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    _seed_full_policy(api_module)
    booking_id = _seed_booking(
        api_module, suffix, source="whatsapp",
        email=f"rl-{suffix}@example.com", telefono="+34600123456",
    )
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as connection:
        for i in range(2):
            connection.execute(
                """
                INSERT INTO customer_payments
                    (id, cliente_id, booking_id, service_id, amount_cents, status, created_at, updated_at)
                VALUES (?, 'demo', ?, 'consulta', 10000, 'pending', ?, ?)
                """,
                (f"pay_{suffix}_{i}", booking_id, now, now),
            )
        connection.commit()
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    result = asyncio.run(
        api_module._ai_send_payment_link("demo", _booking_row(api_module, booking_id))
    )
    assert result["ok"] is False
    assert result["reason"] == "rate_limited"


def test_ai_send_sms_fallback_when_no_phone(api_module, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    _seed_full_policy(api_module)
    booking_id = _seed_booking(
        api_module, suffix, source="voice",
        email=f"nophone-{suffix}@example.com", telefono="",
    )
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    result = asyncio.run(
        api_module._ai_send_payment_link("demo", _booking_row(api_module, booking_id))
    )
    assert result["ok"] is False
    assert result["reason"] == "no_phone"


def test_payment_methods_endpoint(client, portal_cookies, api_module):
    """El negocio elige con que le pueden pagar; la tarjeta no se toca."""
    _seed_connect_account(api_module)
    sin_bizum = client.put(
        "/auth/app/payments/methods", cookies=portal_cookies, json={"bizum": False, "wallets": True}
    )
    assert sin_bizum.status_code == 200, sin_bizum.text
    assert sin_bizum.json()["bizum_enabled"] is False
    assert api_module.payment_method_prefs("demo") == {"bizum": False, "wallets": True}

    con_bizum = client.put(
        "/auth/app/payments/methods", cookies=portal_cookies, json={"bizum": True, "wallets": False}
    )
    assert con_bizum.status_code == 200
    assert con_bizum.json()["bizum_enabled"] is True
    assert con_bizum.json()["wallets_enabled"] is False


def test_chat_payment_intent_generates_link(api_module, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    _seed_full_policy(api_module)
    booking_id = _seed_booking(
        api_module, suffix, source="vantelia_widget",
        email=f"chat-{suffix}@example.com", telefono="+34600123456",
    )
    code = _booking_row(api_module, booking_id)["booking_code"]
    captured_session: dict = {}
    _patch_stripe_ok(api_module, monkeypatch, suffix, captured_session)

    result = asyncio.run(
        api_module._process_payment_request_message(
            cliente_id="demo", message=f"quiero pagar mi cita {code}", request=None, source="chat",
        )
    )
    assert result is not None
    intent, text = result
    assert intent == "payment"
    assert f"https://checkout.test/{suffix}" in text


def test_chat_payment_without_code_resolves_by_trusted_phone(api_module, monkeypatch):
    """WhatsApp: sin numero de reserva, identifica la cita por el telefono verificado."""
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    _seed_full_policy(api_module)
    booking_id = _seed_booking(
        api_module, suffix, source="whatsapp",
        email=f"wa-{suffix}@example.com", telefono="+34600555444",
    )
    captured_session: dict = {}
    _patch_stripe_ok(api_module, monkeypatch, suffix, captured_session)

    result = asyncio.run(
        api_module._process_payment_request_message(
            cliente_id="demo", message="quiero pagar", request=None, source="chat",
            trusted_phone="+34600555444",
        )
    )
    assert result is not None
    intent, text = result
    assert intent == "payment"
    assert f"https://checkout.test/{suffix}" in text


def test_chat_payment_without_code_resolves_by_email_in_message(api_module, monkeypatch):
    """Web: sin codigo ni telefono, identifica por el email que escribe el cliente."""
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    _seed_full_policy(api_module)
    email = f"webid-{suffix}@example.com"
    booking_id = _seed_booking(
        api_module, suffix, source="vantelia_widget", email=email, telefono="+34600111000",
    )
    captured_session: dict = {}
    _patch_stripe_ok(api_module, monkeypatch, suffix, captured_session)

    result = asyncio.run(
        api_module._process_payment_request_message(
            cliente_id="demo", message=f"quiero pagar, mi correo es {email}", request=None, source="chat",
        )
    )
    assert result is not None
    intent, text = result
    assert intent == "payment"
    assert f"https://checkout.test/{suffix}" in text


def test_chat_payment_without_code_or_identity_asks(api_module, monkeypatch):
    """Web anonimo sin pistas: pide el numero de reserva o el contacto."""
    suffix = uuid.uuid4().hex[:8]
    _seed_connect_account(api_module)
    _seed_service(api_module)
    _seed_full_policy(api_module)
    result = asyncio.run(
        api_module._process_payment_request_message(
            cliente_id="demo", message="quiero pagar", request=None, source="chat",
        )
    )
    assert result is not None
    intent, text = result
    assert intent == "payment"
    from backend import textnorm

    assert "numero de reserva" in textnorm._strip_accents(text.lower())


def test_chat_payment_intent_sin_cobros_deja_seguir(api_module, monkeypatch):
    """Sin cobros operativos no se contesta con un portazo: el pipeline sigue y
    responde el negocio (sus Q&A o su informacion). Un salon que cobra la senal por
    Bizum tiene escrito como se paga, y "no puedo gestionar el pago online" tapaba
    esa respuesta."""
    with api_module._get_db_connection() as connection:
        connection.execute("DELETE FROM client_payment_accounts WHERE cliente_id='demo'")
        connection.commit()
    result = asyncio.run(
        api_module._process_payment_request_message(
            cliente_id="demo", message="quiero pagar mi cita R-1234", request=None, source="chat",
        )
    )
    assert result is None
