from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


CID = "qa_pliego"


def _next_open_day() -> str:
    day = datetime.now().date() + timedelta(days=2)
    while day.weekday() == 6:
        day += timedelta(days=1)
    return day.isoformat()


@pytest.fixture(scope="module")
def acceptance(vantelia_env_factory):
    config = {
        CID: {
            "nombre": "Centro QA Pliego",
            "allowed_origins": ["http://testserver"],
            "plan": "business",
            "subscription": {"plan": "business", "status": "active"},
            "whatsapp": {"enabled": True, "phone_number_id": "WA_QA"},
            "booking": {
                "enabled": True,
                "timezone": "Europe/Madrid",
                "slot_minutes": 15,
                "day_start": "09:00",
                "day_end": "13:00",
                "closed_weekdays": [6],
                "provider": "internal",
            },
        }
    }
    api = vantelia_env_factory(
        config,
        info_txt="SERVICIOS Y PRECIOS:\nPREGUNTAS FRECUENTES:\n",
        env_overrides={
            "EMAIL_SEND_PROVIDER": "smtp",
            "SMTP_HOST": "",
            "SMTP_USERNAME": "",
            "SMTP_PASSWORD": "",
            "SMTP_FROM_EMAIL": "",
            "WHATSAPP_ACCESS_TOKEN": "",
        },
    )
    client = TestClient(api.app)
    owner = api._create_user(
        email="owner.pliego@example.com",
        password="owner-pass-123",
        role="client",
        display_name="Propietaria QA",
        cliente_id=CID,
        portal_role="owner",
    )
    owner_cookies = {"vantelia_portal_session": api._create_auth_session(owner["id"])}
    return {
        "api": api,
        "client": client,
        "owner": owner,
        "owner_cookies": owner_cookies,
        "params": {"cliente_id": CID},
        "date": _next_open_day(),
    }


def _post_booking(ctx, cookies, *, employee_id: str, service: str, time: str, name: str, email: str):
    return ctx["client"].post(
        "/auth/bookings",
        params=ctx["params"],
        cookies=cookies,
        json={
            "nombre": name,
            "email": email,
            "telefono": "+34600111222",
            "servicio": service,
            "employee_id": employee_id,
            "fecha": ctx["date"],
            "hora": time,
            "notas": "Creada durante aceptacion manual",
        },
    )


def test_full_pliego_as_owner_manager_and_staff(acceptance, monkeypatch):
    api = acceptance["api"]
    client = acceptance["client"]
    owner_cookies = acceptance["owner_cookies"]
    params = acceptance["params"]

    # El propietario crea los accesos que usaria un negocio real.
    manager_response = client.post(
        "/auth/app/team",
        cookies=owner_cookies,
        json={
            "email": "manager.pliego@example.com",
            "password": "manager-pass-123",
            "display_name": "Encargada QA",
            "portal_role": "manager",
        },
    )
    staff_response = client.post(
        "/auth/app/team",
        cookies=owner_cookies,
        json={
            "email": "staff.pliego@example.com",
            "password": "staff-pass-123",
            "display_name": "Recepcion QA",
            "portal_role": "staff",
        },
    )
    assert manager_response.status_code == 200, manager_response.text
    assert staff_response.status_code == 200, staff_response.text
    manager = api._get_user_by_email("manager.pliego@example.com")
    staff = api._get_user_by_email("staff.pliego@example.com")
    manager_cookies = {"vantelia_portal_session": api._create_auth_session(manager["id"])}
    staff_cookies = {"vantelia_portal_session": api._create_auth_session(staff["id"])}

    # Catalogo multi-centro, personal y sala creados por la encargada.
    service_response = client.post(
        "/auth/services",
        params=params,
        cookies=manager_cookies,
        json={"nombre": "Tratamiento QA", "duration_minutes": 45, "price_cents": 6000},
    )
    assert service_response.status_code == 200, service_response.text
    service = service_response.json()
    location_a = next(
        item
        for item in client.get("/auth/locations", params=params, cookies=manager_cookies).json()["items"]
        if item["is_default"]
    )
    location_b_response = client.post(
        "/auth/locations",
        params=params,
        cookies=manager_cookies,
        json={"name": "Centro Norte", "address": "Calle Norte 1"},
    )
    assert location_b_response.status_code == 200, location_b_response.text
    location_b = location_b_response.json()
    override = client.put(
        f"/auth/services/{service['id']}/locations/{location_b['location_id']}",
        params=params,
        cookies=manager_cookies,
        json={"is_available": True, "price_cents": 7500, "duration_minutes": 30},
    )
    assert override.status_code == 200, override.text

    employee_payload = {
        "role_label": "Especialista",
        "color": "#00b1d9",
        "is_active": True,
        "timezone": "Europe/Madrid",
        "slot_minutes": 15,
        "day_start": "09:00",
        "day_end": "13:00",
        "break_windows": [],
        "closed_weekdays": [6],
        "service_ids": [service["id"]],
    }
    employee_a = client.post(
        "/auth/employees",
        params=params,
        cookies=manager_cookies,
        json={**employee_payload, "name": "Ana QA", "location_id": location_a["location_id"]},
    )
    employee_b = client.post(
        "/auth/employees",
        params=params,
        cookies=manager_cookies,
        json={**employee_payload, "name": "Berta QA", "location_id": location_b["location_id"]},
    )
    employee_b2 = client.post(
        "/auth/employees",
        params=params,
        cookies=manager_cookies,
        json={**employee_payload, "name": "Beatriz QA", "location_id": location_b["location_id"]},
    )
    assert employee_a.status_code == 200 and employee_b.status_code == 200 and employee_b2.status_code == 200
    employee_a, employee_b, employee_b2 = employee_a.json(), employee_b.json(), employee_b2.json()
    room = client.post(
        f"/auth/locations/{location_b['location_id']}/resources",
        params=params,
        cookies=manager_cookies,
        json={"name": "Cabina Norte", "is_active": True},
    )
    assert room.status_code == 200, room.text

    # Staff usa agenda y mostrador, pero no puede gestionar catalogo, salas ni informes.
    assert client.get("/auth/products", params=params, cookies=staff_cookies).status_code == 200
    assert client.post(
        "/auth/services", params=params, cookies=staff_cookies, json={"nombre": "No permitido"}
    ).status_code == 403
    assert client.post(
        f"/auth/locations/{location_b['location_id']}/resources",
        params=params,
        cookies=staff_cookies,
        json={"name": "Sala no permitida"},
    ).status_code == 403
    assert client.get("/auth/analytics/overview", params=params, cookies=staff_cookies).status_code == 403
    assert client.get("/auth/app/team", cookies=manager_cookies).status_code == 403

    # Recepcion crea una cita: se asignan profesional, centro, precio efectivo y sala.
    booking_response = _post_booking(
        acceptance,
        staff_cookies,
        employee_id=employee_b["employee_id"],
        service=service["nombre"],
        time="10:00",
        name="Cliente Pliego",
        email="cliente.pliego@example.com",
    )
    assert booking_response.status_code == 200, booking_response.text
    booking_id = booking_response.json()["booking_id"]
    with api._get_db_connection() as connection:
        booking_row = connection.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    assert booking_row["employee_id"] == employee_b["employee_id"]
    assert booking_row["location_id"] == location_b["location_id"]
    assert booking_row["resource_id"] == room.json()["resource_id"]
    assert booking_row["service_price_cents"] == 7500

    # Centros distintos son independientes aunque compartan horario.
    other_center = _post_booking(
        acceptance,
        staff_cookies,
        employee_id=employee_a["employee_id"],
        service=service["nombre"],
        time="10:15",
        name="Cliente Otro Centro",
        email="otro.centro@example.com",
    )
    assert other_center.status_code == 200

    # Aforo: aun con otro profesional del mismo centro, la unica sala impide solapar.
    blocked = _post_booking(
        acceptance,
        staff_cookies,
        employee_id=employee_b2["employee_id"],
        service=service["nombre"],
        time="10:15",
        name="Cliente Solape",
        email="solape@example.com",
    )
    assert blocked.status_code == 409

    # Registro automatico y deduplicacion: mismo telefono + email nuevo = mismo contacto.
    contacts = client.get(
        "/auth/app/contacts", cookies=staff_cookies, params={"q": "+34600111222"}
    )
    with api._get_db_connection() as connection:
        raw_contacts = [dict(row) for row in connection.execute(
            "SELECT id, cliente_id, name, email, search_text FROM crm_contacts WHERE cliente_id = ?",
            (CID,),
        ).fetchall()]
    assert contacts.status_code == 200 and contacts.json()["total"] == 1, {
        "response": contacts.json(),
        "database": raw_contacts,
    }
    contact_id = contacts.json()["items"][0]["id"]
    contact = client.get(f"/auth/app/contacts/{contact_id}", cookies=staff_cookies)
    assert contact.status_code == 200
    assert contact.json()["contact"]["bookings_count"] == 2
    assert any(item.get("reference_id") == booking_id for item in contact.json()["activity"])

    # Mostrador: producto con stock, bono con descuento y tarjeta regalo parcial.
    product = client.post(
        "/auth/products",
        params=params,
        cookies=manager_cookies,
        json={"name": "Serum QA", "price_cents": 2500, "stock": 2},
    )
    assert product.status_code == 200, product.text
    sale = client.post(
        f"/auth/products/{product.json()['id']}/sell",
        params=params,
        cookies=staff_cookies,
        json={"qty": 2, "payment_method": "card", "location_id": location_b["location_id"]},
    )
    assert sale.status_code == 200 and sale.json()["total_cents"] == 5000
    assert client.post(
        f"/auth/products/{product.json()['id']}/sell",
        params=params,
        cookies=staff_cookies,
        json={"qty": 1, "location_id": location_b["location_id"]},
    ).status_code == 409

    package = client.post(
        "/auth/packages",
        params=params,
        cookies=manager_cookies,
        json={
            "name": "Bono QA 2 sesiones",
            "items": [{"service_slug": service["id"], "qty": 2}],
            "price_cents": 10000,
            "validity_days": 90,
        },
    )
    assert package.status_code == 200, package.text
    purchase = client.post(
        f"/auth/packages/{package.json()['id']}/sell",
        params=params,
        cookies=staff_cookies,
        json={
            "buyer_name": "Cliente Pliego",
            "buyer_email": "cliente.pliego@example.com",
            "location_id": location_b["location_id"],
        },
    )
    assert purchase.status_code == 200 and purchase.json()["remaining"][service["id"]] == 2
    redeemed = client.post(
        f"/auth/package-purchases/{purchase.json()['purchase_id']}/redeem",
        params=params,
        cookies=staff_cookies,
        json={"booking_id": booking_id},
    )
    assert redeemed.status_code == 200 and redeemed.json()["remaining"][service["id"]] == 1

    gift = client.post(
        "/auth/gift-cards",
        params=params,
        cookies=staff_cookies,
        json={"amount_cents": 3000, "buyer_name": "Cliente Pliego", "location_id": location_b["location_id"]},
    )
    assert gift.status_code == 200, gift.text
    # No permite cobrar dos veces una cita ya cubierta por bono.
    assert client.post(
        "/auth/gift-cards/redeem",
        params=params,
        cookies=staff_cookies,
        json={"code": gift.json()["code"], "booking_id": booking_id, "amount_cents": 2000},
    ).status_code == 409
    gift_booking = _post_booking(
        acceptance,
        staff_cookies,
        employee_id=employee_b["employee_id"],
        service=service["nombre"],
        time="11:00",
        name="Cliente Gift",
        email="gift@example.com",
    )
    assert gift_booking.status_code == 200, gift_booking.text
    gift_booking_id = gift_booking.json()["booking_id"]
    gift_redeem = client.post(
        "/auth/gift-cards/redeem",
        params=params,
        cookies=staff_cookies,
        json={"code": gift.json()["code"], "booking_id": gift_booking_id, "amount_cents": 2000},
    )
    assert gift_redeem.status_code == 200 and gift_redeem.json()["charged_cents"] == 2000

    # Notificacion multicanal: los tres canales se despachan y quedan auditados.
    from backend import agenda as agenda_module
    from backend import booking as booking_module

    sent_channels = []

    def fake_email(*args, **kwargs):
        sent_channels.append("email")

    async def fake_whatsapp(*args, **kwargs):
        sent_channels.append("whatsapp")
        return True

    async def fake_sms(*args, **kwargs):
        sent_channels.append("sms")
        return True

    monkeypatch.setattr(
        agenda_module,
        "_reminder_channel_availability",
        lambda _cid: {
            "email": {"available": True},
            "whatsapp": {"available": True},
            "sms": {"available": True},
        },
    )
    monkeypatch.setattr(booking_module, "_send_booking_email", fake_email)
    monkeypatch.setattr(booking_module, "_send_booking_whatsapp_reminder", fake_whatsapp)
    monkeypatch.setattr(booking_module, "_send_booking_sms_reminder", fake_sms)
    api.CONFIG_CLIENTES[CID]["booking"]["message_template_channels"] = {
        "reminder_24h": {"email": True, "whatsapp": True, "sms": True}
    }
    with api._get_db_connection() as connection:
        notification_booking = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (gift_booking_id,)
        ).fetchone()
    asyncio.run(
        booking_module._send_booking_reminder_by_kind(
            notification_booking, "reminder_24h", respect_enabled=False
        )
    )
    assert sent_channels == ["email", "whatsapp", "sms"]
    with api._get_db_connection() as connection:
        audit_payload = connection.execute(
            """
            SELECT payload_json FROM booking_audit
            WHERE booking_id = ? AND event_type = 'booking_email_sent'
            ORDER BY id DESC LIMIT 1
            """,
            (gift_booking_id,),
        ).fetchone()[0]
    assert json.loads(audit_payload)["channels"] == ["email", "whatsapp", "sms"]

    # Informes: el filtro del Centro Norte contiene sus ventas; el principal no.
    analytics_b = client.get(
        "/auth/analytics/overview",
        params={**params, "location_id": location_b["location_id"]},
        cookies=manager_cookies,
    )
    analytics_a = client.get(
        "/auth/analytics/overview",
        params={**params, "location_id": location_a["location_id"]},
        cookies=manager_cookies,
    )
    assert analytics_b.status_code == 200 and analytics_a.status_code == 200
    assert analytics_b.json()["kpis"]["extras_revenue_cents"] >= 18000
    assert analytics_a.json()["kpis"]["extras_revenue_cents"] == 0
    analytics_service = client.get(
        "/auth/analytics/overview",
        params={**params, "service_id": service["id"]},
        cookies=manager_cookies,
    )
    assert analytics_service.status_code == 200, analytics_service.text
    assert analytics_service.json()["service_id"] == service["id"]
    assert analytics_service.json()["kpis"]["extras_revenue_cents"] == 0
    assert all(item["label"] == service["nombre"] for item in analytics_service.json()["by_service"])
    assert client.get(
        "/auth/analytics/overview",
        params={**params, "service_id": "servicio-inexistente"},
        cookies=manager_cookies,
    ).status_code == 404
    export = client.get(
        "/auth/analytics/export.csv",
        params={**params, "location_id": location_b["location_id"], "service_id": service["id"]},
        cookies=manager_cookies,
    )
    assert export.status_code == 200 and "fecha;citas;ingresos_eur" in export.text

    # Timeline y cancelacion quedan auditados y la sala vuelve a quedar libre.
    timeline = client.get(f"/auth/bookings/{booking_id}/timeline", cookies=staff_cookies)
    event_types = {item["event_type"] for item in timeline.json()["items"]}
    assert {"booking_created", "package_redeemed"} <= event_types
    gift_events = {
        item["event_type"]
        for item in client.get(f"/auth/bookings/{gift_booking_id}/timeline", cookies=staff_cookies).json()["items"]
    }
    assert "gift_card_redeemed" in gift_events
    cancelled = client.post(
        f"/auth/bookings/{booking_id}/cancel",
        cookies=staff_cookies,
        json={"motivo": "Cancelacion solicitada durante QA"},
    )
    assert cancelled.status_code == 200 and cancelled.json()["estado"] == "cancelled"
    replacement = _post_booking(
        acceptance,
        staff_cookies,
        employee_id=employee_b["employee_id"],
        service=service["nombre"],
        time="10:00",
        name="Cliente Reemplazo",
        email="reemplazo@example.com",
    )
    assert replacement.status_code == 200, replacement.text
    final_timeline = client.get(f"/auth/bookings/{booking_id}/timeline", cookies=staff_cookies).json()["items"]
    assert any(item["event_type"] == "booking_cancelled" for item in final_timeline)


def test_portal_html_exposes_pliego_controls():
    html = (Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")
    for marker in (
        'value="preauth"',
        "Disponibilidad y precio por centro",
        "loadVentasProductos",
        "loadVentasBonos",
        "loadVentasGift",
        "loadInformes",
        "loadAccessTeam",
        "ROLE_HIDDEN_TABS",
    ):
        assert marker in html
