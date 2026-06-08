from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from types import SimpleNamespace

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture(scope="module")
def portal_cookies(api_module, client):
    email = f"crm-portal-{uuid.uuid4().hex[:8]}@example.com"
    password = "crm-test-password-123"
    api_module._create_user(
        email=email,
        password=password,
        role="client",
        display_name="CRM Portal",
        cliente_id="demo",
    )
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"vantelia_portal_session": response.cookies["vantelia_portal_session"]}


def test_crm_deduplicates_email_and_phone(api_module):
    suffix = uuid.uuid4().hex[:8]
    email = f"crm-{suffix}@example.com"
    first_id = api_module._crm_upsert_contact(
        "demo",
        name="Contacto inicial",
        email=email.upper(),
        phone="600 123 456",
        source="chat",
        status="interesado",
        entity_type="lead",
        entity_id=f"lead_{suffix}",
    )
    second_id = api_module._crm_upsert_contact(
        "demo",
        name="Contacto actualizado",
        email=email,
        phone="+34 600 123 456",
        source="booking",
        status="confirmado",
        entity_type="booking",
        entity_id=f"booking_{suffix}",
    )

    assert first_id == second_id
    with api_module._get_db_connection() as connection:
        row = connection.execute("SELECT * FROM crm_contacts WHERE id = ?", (first_id,)).fetchone()
        links = connection.execute(
            "SELECT entity_type FROM crm_contact_links WHERE contact_id = ? ORDER BY entity_type",
            (first_id,),
        ).fetchall()
    assert row["name"] == "Contacto actualizado"
    assert row["status"] == "confirmado"
    assert [item["entity_type"] for item in links] == ["booking", "lead"]


def test_crm_keeps_tenants_isolated(api_module):
    phone = f"+3491{uuid.uuid4().int % 10_000_000:07d}"
    first_id = api_module._crm_upsert_contact("demo", phone=phone, source="voice")
    second_id = api_module._crm_upsert_contact("otro_cliente", phone=phone, source="voice")

    assert first_id != second_id
    with api_module._get_db_connection() as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM crm_contacts WHERE phone_normalized = ?",
            (api_module._normalize_crm_phone(phone),),
        ).fetchone()[0]
    assert total == 2


def test_crm_portal_crud_and_contact_detail(client, portal_cookies):
    suffix = uuid.uuid4().hex[:8]
    created = client.post(
        "/auth/app/contacts",
        cookies=portal_cookies,
        json={
            "name": "Contacto Portal",
            "email": f"portal-{suffix}@example.com",
            "phone": "",
            "status": "nuevo",
            "notes": "",
            "tags": ["vip"],
            "owner": "Recepcion",
            "next_action": "Llamar",
            "next_action_at": "",
            "source": "manual",
        },
    )
    assert created.status_code == 200, created.text
    contact_id = created.json()["id"]

    updated = client.put(
        f"/auth/app/contacts/{contact_id}",
        cookies=portal_cookies,
        json={
            "name": "Contacto Portal",
            "email": f"portal-{suffix}@example.com",
            "phone": "+34600111222",
            "status": "cliente",
            "notes": "Prefiere contacto por WhatsApp.",
            "tags": ["vip", "recurrente"],
            "owner": "Recepcion",
            "next_action": "Enviar seguimiento",
            "next_action_at": "",
            "source": "manual",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "cliente"

    detail = client.get(f"/auth/app/contacts/{contact_id}", cookies=portal_cookies)
    assert detail.status_code == 200, detail.text
    assert detail.json()["contact"]["tags"] == ["vip", "recurrente"]

    listed = client.get(
        "/auth/app/contacts",
        params={"q": f"portal-{suffix}", "status_filter": "cliente"},
        cookies=portal_cookies,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1


def _create_filtered_contact(api_module, suffix: str, index: int) -> str:
    contact_id = api_module._crm_upsert_contact(
        "demo",
        name=f"Álvaro Escala {suffix} {index:03d}",
        email=f"escala-{suffix}-{index:03d}@example.com",
        phone=f"+34620{index:06d}",
        source="whatsapp" if index % 2 else "voice",
        status="interesado",
        entity_type="lead",
        entity_id=f"lead_scale_{suffix}_{index}",
    )
    created_at = (datetime.now(timezone.utc) - timedelta(days=index)).isoformat()
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE crm_contacts SET status=?, tags_json=?, owner=?, next_action=?, next_action_at=?,
                created_at=?, last_seen_at=?, updated_at=?
            WHERE id=?
            """,
            (
                "cliente" if index % 3 == 0 else "interesado",
                '["vip", "escala"]' if index % 2 else '["escala"]',
                "Ana" if index % 2 else "Luis",
                "Llamar" if index % 4 else "",
                (datetime.now(timezone.utc) + timedelta(days=index - 5)).isoformat() if index % 4 else "",
                created_at,
                created_at,
                created_at,
                contact_id,
            ),
        )
        connection.commit()
    return contact_id


def test_crm_search_filters_order_and_pagination(api_module, client, portal_cookies):
    suffix = uuid.uuid4().hex[:6]
    ids = [_create_filtered_contact(api_module, suffix, index) for index in range(12)]

    response = client.get(
        "/auth/app/contacts",
        params={
            "q": f"alvaro escala {suffix}",
            "status_filter": "cliente",
            "tag": "vip",
            "owner": "Ana",
            "source": "whatsapp",
            "sort": "name_asc",
            "page": 1,
            "page_size": 2,
        },
        cookies=portal_cookies,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2
    assert data["pages"] == 1
    assert len(data["items"]) == 2
    assert data["items"][0]["name"] < data["items"][1]["name"]
    assert all(item["id"] in ids for item in data["items"])

    paged = client.get(
        "/auth/app/contacts",
        params={"q": f"escala {suffix}", "sort": "created_desc", "page": 2, "page_size": 5},
        cookies=portal_cookies,
    )
    assert paged.status_code == 200, paged.text
    assert paged.json()["total"] == 12
    assert paged.json()["pages"] == 3
    assert len(paged.json()["items"]) == 5

    phone_search = client.get(
        "/auth/app/contacts",
        params={"q": "620 000 003"},
        cookies=portal_cookies,
    )
    assert phone_search.status_code == 200
    assert any(item["id"] == ids[3] for item in phone_search.json()["items"])


def test_crm_next_action_date_filters_and_export(api_module, client, portal_cookies):
    suffix = uuid.uuid4().hex[:6]
    _create_filtered_contact(api_module, suffix, 1)
    _create_filtered_contact(api_module, suffix, 6)

    overdue = client.get(
        "/auth/app/contacts",
        params={"q": suffix, "next_action_filter": "overdue"},
        cookies=portal_cookies,
    )
    upcoming = client.get(
        "/auth/app/contacts",
        params={"q": suffix, "next_action_filter": "upcoming"},
        cookies=portal_cookies,
    )
    assert overdue.status_code == upcoming.status_code == 200
    assert overdue.json()["total"] == 1
    assert upcoming.json()["total"] == 1
    recent = client.get(
        "/auth/app/contacts",
        params={
            "q": suffix,
            "date_from": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        },
        cookies=portal_cookies,
    )
    assert recent.status_code == 200
    assert recent.json()["total"] == 1

    exported = client.get(
        "/auth/app/contacts/export.csv",
        params={"q": suffix, "owner": "Ana"},
        cookies=portal_cookies,
    )
    assert exported.status_code == 200, exported.text
    assert "text/csv" in exported.headers["content-type"]
    assert f"escala-{suffix}-001@example.com" in exported.text
    assert f"escala-{suffix}-006@example.com" not in exported.text


def test_crm_list_is_lightweight_and_avoids_detail_n_plus_one(api_module, client, portal_cookies, monkeypatch):
    suffix = uuid.uuid4().hex[:6]
    for index in range(25):
        _create_filtered_contact(api_module, suffix, index + 20)

    def fail_if_detail_serializer_runs(*args, **kwargs):
        raise AssertionError("El listado no debe cargar contadores contacto a contacto.")

    monkeypatch.setattr(api_module, "_crm_contact_public", fail_if_detail_serializer_runs)
    response = client.get(
        "/auth/app/contacts",
        params={"q": suffix, "page_size": 25},
        cookies=portal_cookies,
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 25
    assert all("notes" not in item for item in response.json()["items"])


def test_crm_portal_cannot_access_other_tenant_contact(api_module, client, portal_cookies):
    contact_id = api_module._crm_upsert_contact(
        "otro_cliente",
        name="Contacto privado",
        email=f"private-{uuid.uuid4().hex[:8]}@example.com",
        source="manual",
    )
    response = client.get(f"/auth/app/contacts/{contact_id}", cookies=portal_cookies)
    assert response.status_code == 404


def _seed_connect_account(api_module, cliente_id: str = "demo", account_id: str = "acct_demo") -> None:
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_payment_accounts
                (cliente_id, stripe_account_id, charges_enabled, payouts_enabled, details_submitted, created_at, updated_at)
            VALUES (?, ?, 1, 1, 1, ?, ?)
            ON CONFLICT(cliente_id) DO UPDATE SET stripe_account_id=excluded.stripe_account_id,
                charges_enabled=1, payouts_enabled=1, details_submitted=1, updated_at=excluded.updated_at
            """,
            (cliente_id, account_id, now, now),
        )
        connection.commit()


def _seed_service(api_module, cliente_id: str = "demo", service_id: str = "consulta") -> str:
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO services
                (cliente_id, slug, name, duration_minutes, price_cents, description, is_active, sort_order, created_at, updated_at)
            VALUES (?, ?, 'Consulta', 30, 10000, '', 1, 0, ?, ?)
            ON CONFLICT(cliente_id, slug) DO UPDATE SET price_cents=10000, updated_at=excluded.updated_at
            """,
            (cliente_id, service_id, now, now),
        )
        connection.commit()
    return service_id


def _seed_payment_booking(api_module, suffix: str, status: str = "pending_review") -> str:
    booking_id = f"bk_pay_{suffix}"
    now = api_module._utc_now_iso()
    record = {
        "id": booking_id, "cliente_id": "demo", "employee_id": f"default_{suffix}",
        "employee_name": "Equipo", "nombre": "Cliente Pago", "email": f"pay-{suffix}@example.com",
        "telefono": "+34600123456", "servicio": "Consulta", "booking_date": "2099-06-15",
        "booking_time": "10:00", "notas": "", "status": status, "provider_name": "internal",
        "provider_status": status, "provider_booking_id": "", "provider_booking_url": "",
        "manage_token": f"manage_{suffix}", "timezone": "Europe/Madrid",
        "start_at": "2099-06-15T08:00:00+00:00", "end_at": "2099-06-15T08:30:00+00:00",
        "confirmed_at": "", "cancelled_at": "", "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": "", "reminder_2h_sent_at": "",
        "customer_email_status": "", "customer_email_last_error": "", "booking_code": "",
        "service_id": "consulta", "service_price_cents": 10000, "source": "test_payment", "created_at": now,
    }
    api_module._store_booking(record)
    return booking_id


def test_connect_start_uses_account_links_without_oauth_client_id(
    api_module, client, portal_cookies, monkeypatch
):
    created = {}
    with api_module._get_db_connection() as connection:
        connection.execute("DELETE FROM client_payment_accounts WHERE cliente_id='demo'")
        connection.commit()

    def create_account(**kwargs):
        created["account"] = kwargs
        return SimpleNamespace(
            id="acct_onboarding_demo",
            charges_enabled=False,
            payouts_enabled=False,
            details_submitted=False,
        )

    def create_account_link(**kwargs):
        created["link"] = kwargs
        return SimpleNamespace(url="https://connect.stripe.test/onboarding")

    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(api_module, "STRIPE_CONNECT_CLIENT_ID", "")
    monkeypatch.setattr(api_module.stripe.Account, "create", create_account)
    monkeypatch.setattr(api_module.stripe.AccountLink, "create", create_account_link)

    response = client.post("/auth/app/payments/connect/start", cookies=portal_cookies)

    assert response.status_code == 200, response.text
    assert response.json()["url"] == "https://connect.stripe.test/onboarding"
    assert created["account"]["type"] == "standard"
    assert created["account"]["metadata"]["vantelia_cliente_id"] == "demo"
    assert created["link"]["account"] == "acct_onboarding_demo"
    assert created["link"]["type"] == "account_onboarding"
    with api_module._get_db_connection() as connection:
        row = connection.execute(
            "SELECT stripe_account_id FROM client_payment_accounts WHERE cliente_id='demo'"
        ).fetchone()
    assert row["stripe_account_id"] == "acct_onboarding_demo"


def test_connect_start_explains_when_platform_connect_is_not_activated(
    api_module, client, portal_cookies, monkeypatch
):
    with api_module._get_db_connection() as connection:
        connection.execute("DELETE FROM client_payment_accounts WHERE cliente_id='demo'")
        connection.commit()

    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(api_module, "STRIPE_CONNECT_CLIENT_ID", "")
    monkeypatch.setattr(
        api_module.stripe.Account,
        "create",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("You can only create new accounts if you've signed up for Connect")
        ),
    )

    response = client.post("/auth/app/payments/connect/start", cookies=portal_cookies)

    assert response.status_code == 503
    assert "dashboard.stripe.com/connect" in response.json()["detail"]


def test_payment_policy_and_connect_account_are_tenant_scoped(api_module, client, portal_cookies):
    _seed_connect_account(api_module)
    service_id = _seed_service(api_module)
    status = client.get("/auth/app/payments/connect/status", cookies=portal_cookies)
    assert status.status_code == 200
    assert status.json()["stripe_account_id"] == "acct_demo"

    policy = client.put(
        f"/auth/app/services/{service_id}/payment-policy",
        cookies=portal_cookies,
        json={"mode": "deposit_percent", "deposit_value": 25, "confirm_booking_on_paid": True},
    )
    assert policy.status_code == 200, policy.text
    assert policy.json()["payment_mode"] == "deposit_percent"
    assert policy.json()["deposit_value"] == 25


def test_payment_link_uses_connected_account_and_policy(api_module, client, portal_cookies, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    booking_id = _seed_payment_booking(api_module, suffix)
    _seed_connect_account(api_module)
    with api_module._get_db_connection() as connection:
        now = api_module._utc_now_iso()
        connection.execute(
            """
            INSERT INTO service_payment_policies
                (cliente_id, service_id, mode, deposit_value, confirm_booking_on_paid, created_at, updated_at)
            VALUES ('demo', 'consulta', 'deposit_percent', 25, 1, ?, ?)
            ON CONFLICT(cliente_id, service_id) DO UPDATE SET mode='deposit_percent', deposit_value=25
            """,
            (now, now),
        )
        connection.commit()
    captured = {}

    def create_session(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=f"cs_{suffix}", url=f"https://checkout.test/{suffix}")

    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(api_module.stripe.Account, "retrieve", lambda account_id: SimpleNamespace(charges_enabled=True, payouts_enabled=True, details_submitted=True))
    monkeypatch.setattr(api_module.stripe.checkout.Session, "create", create_session)
    response = client.post(
        f"/auth/app/bookings/{booking_id}/payment-link",
        cookies=portal_cookies,
        json={},
    )
    assert response.status_code == 200, response.text
    assert response.json()["payment"]["amount_cents"] == 2500
    assert captured["stripe_account"] == "acct_demo"
    assert captured["metadata"]["source"] == "customer_payment"


def test_connect_webhook_is_idempotent_and_confirms_booking(api_module, client, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    booking_id = _seed_payment_booking(api_module, suffix)
    _seed_connect_account(api_module)
    now = api_module._utc_now_iso()
    payment_id = f"pay_{suffix}"
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO customer_payments
                (id, cliente_id, booking_id, service_id, service_name, stripe_account_id,
                 stripe_checkout_session_id, amount_cents, status, created_at, updated_at)
            VALUES (?, 'demo', ?, 'consulta', 'Consulta', 'acct_demo', ?, 10000, 'pending', ?, ?)
            """,
            (payment_id, booking_id, f"cs_{suffix}", now, now),
        )
        connection.execute(
            """
            INSERT INTO service_payment_policies
                (cliente_id, service_id, mode, deposit_value, confirm_booking_on_paid, created_at, updated_at)
            VALUES ('demo', 'consulta', 'full', 0, 1, ?, ?)
            ON CONFLICT(cliente_id, service_id) DO UPDATE SET mode='full', confirm_booking_on_paid=1
            """,
            (now, now),
        )
        connection.commit()
    event = {
        "id": f"evt_{suffix}", "type": "checkout.session.completed", "account": "acct_demo",
        "data": {"object": {"id": f"cs_{suffix}", "payment_status": "paid", "payment_intent": f"pi_{suffix}", "metadata": {"payment_id": payment_id}}},
    }
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(api_module, "STRIPE_CONNECT_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(api_module.stripe.Webhook, "construct_event", lambda payload, signature, secret: event)

    first = client.post("/stripe/connect/webhook", content=b"{}", headers={"stripe-signature": "sig"})
    second = client.post("/stripe/connect/webhook", content=b"{}", headers={"stripe-signature": "sig"})
    assert first.status_code == second.status_code == 200
    assert second.json()["duplicate"] is True
    with api_module._get_db_connection() as connection:
        payment = connection.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
        booking = connection.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        events = connection.execute("SELECT COUNT(*) FROM customer_payment_events WHERE stripe_event_id=?", (event["id"],)).fetchone()[0]
    assert payment["status"] == "paid"
    assert booking["status"] == "confirmed"
    assert events == 1


def test_payment_refund_uses_connected_account(api_module, client, portal_cookies, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    payment_id, now = f"pay_ref_{suffix}", api_module._utc_now_iso()
    _seed_connect_account(api_module)
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO customer_payments
                (id, cliente_id, stripe_account_id, stripe_payment_intent_id, amount_cents,
                 status, created_at, updated_at)
            VALUES (?, 'demo', 'acct_demo', ?, 5000, 'paid', ?, ?)
            """,
            (payment_id, f"pi_{suffix}", now, now),
        )
        connection.commit()
    captured = {}
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(api_module.stripe.Refund, "create", lambda **kwargs: captured.update(kwargs) or SimpleNamespace(id="re_test"))
    response = client.post(
        f"/auth/app/payments/{payment_id}/refund",
        cookies=portal_cookies,
        json={"amount_cents": 1200},
    )
    assert response.status_code == 200, response.text
    assert captured == {"payment_intent": f"pi_{suffix}", "stripe_account": "acct_demo", "amount": 1200}
