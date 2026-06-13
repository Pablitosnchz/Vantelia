from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


CID = "qa_multicanal"
ORIGIN = {"Origin": "http://testserver"}


def _next_monday() -> str:
    day = datetime.now().date() + timedelta(days=1)
    while day.weekday() != 0:
        day += timedelta(days=1)
    return day.isoformat()


@pytest.fixture(scope="module")
def scenario(vantelia_env_factory):
    config = {
        CID: {
            "nombre": "Clinica Multicanal QA",
            "icono": "QA",
            "color": "#00b1d9",
            "bienvenida": "Hola, soy el asistente QA.",
            "prompt_extra": "",
            "allowed_origins": ["http://testserver"],
            "contacto": {"email": "qa@example.com", "telefono": "+34600000000"},
            "branding": {"powered_by": "Vantelia"},
            "plan": "business",
            "subscription": {"plan": "business", "status": "active"},
            "whatsapp": {"enabled": True, "phone_number_id": "PH_QA_A"},
            "booking": {
                "enabled": True,
                "timezone": "Europe/Madrid",
                "slot_minutes": 15,
                "day_start": "09:00",
                "day_end": "12:00",
                "closed_weekdays": [6],
                "provider": "internal",
                "success_message": "Cita registrada.",
            },
        }
    }
    info = "SERVICIOS Y PRECIOS:\nPREGUNTAS FRECUENTES:\n"
    api = vantelia_env_factory(
        config,
        info_txt=info,
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
    user = api._get_user_by_email("admin@example.com")
    cookies = {"vantelia_portal_session": api._create_auth_session(user["id"])}
    params = {"cliente_id": CID}

    long_service = client.post(
        "/auth/services",
        params=params,
        cookies=cookies,
        json={"nombre": "Tratamiento 45 minutos", "duration_minutes": 45, "price_cents": 4500},
    ).json()
    short_service = client.post(
        "/auth/services",
        params=params,
        cookies=cookies,
        json={"nombre": "Revision 15 minutos", "duration_minutes": 15, "price_cents": 1500},
    ).json()
    other_service = client.post(
        "/auth/services",
        params=params,
        cookies=cookies,
        json={"nombre": "Servicio auxiliar", "duration_minutes": 15, "price_cents": 1000},
    ).json()
    location_a = next(
        item
        for item in client.get("/auth/locations", params=params, cookies=cookies).json()["items"]
        if item["is_default"]
    )
    location_b = client.post(
        "/auth/locations",
        params=params,
        cookies=cookies,
        json={
            "name": "Centro B",
            "address": "Calle B 2",
            "whatsapp_phone_number_id": "PH_QA_B",
            "voice_phone_number": "+34910000002",
        },
    ).json()
    employee_payload = {
        "role_label": "QA",
        "color": "#00b1d9",
        "is_active": True,
        "timezone": "Europe/Madrid",
        "slot_minutes": 15,
        "day_start": "09:00",
        "day_end": "12:00",
        "break_windows": [],
        "closed_weekdays": [6],
        "service_ids": [long_service["id"], short_service["id"]],
    }
    employee_a = client.post(
        "/auth/employees",
        params=params,
        cookies=cookies,
        json={**employee_payload, "name": "Profesional A", "location_id": location_a["location_id"]},
    ).json()
    employee_a2 = client.post(
        "/auth/employees",
        params=params,
        cookies=cookies,
        json={
            **employee_payload,
            "name": "Profesional A2",
            "location_id": location_a["location_id"],
            "service_ids": [other_service["id"]],
        },
    ).json()
    employee_b = client.post(
        "/auth/employees",
        params=params,
        cookies=cookies,
        json={**employee_payload, "name": "Profesional B", "location_id": location_b["location_id"]},
    ).json()

    return {
        "api": api,
        "client": client,
        "cookies": cookies,
        "params": params,
        "long": long_service,
        "short": short_service,
        "other": other_service,
        "location_a": location_a,
        "location_b": location_b,
        "employee_a": employee_a,
        "employee_a2": employee_a2,
        "employee_b": employee_b,
        "fecha": _next_monday(),
    }


def _book_portal(scenario, *, employee_id: str, servicio: str, hora: str, fecha: str | None = None):
    return scenario["client"].post(
        "/auth/bookings",
        params=scenario["params"],
        cookies=scenario["cookies"],
        json={
            "nombre": "Cliente QA",
            "email": "cliente@example.com",
            "telefono": "600000001",
            "servicio": servicio,
            "employee_id": employee_id,
            "fecha": fecha or scenario["fecha"],
            "hora": hora,
            "notas": "",
        },
    )


def _delete_booking(scenario, booking_id: str) -> None:
    with scenario["api"]._get_db_connection() as connection:
        connection.execute("DELETE FROM booking_audit WHERE booking_id = ?", (booking_id,))
        connection.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        connection.commit()


def _seed_1030_blocker(scenario, employee_id: str | None = None) -> str:
    response = _book_portal(
        scenario,
        employee_id=employee_id or scenario["employee_a"]["employee_id"],
        servicio=scenario["short"]["nombre"],
        hora="10:30",
    )
    assert response.status_code == 200, response.text
    return response.json()["booking_id"]


def test_45_minutes_blocked_at_1000_but_15_minutes_fit_across_channels(scenario, monkeypatch):
    api = scenario["api"]
    client = scenario["client"]
    fecha = scenario["fecha"]
    long_name = scenario["long"]["nombre"]
    short_name = scenario["short"]["nombre"]
    employee_id = scenario["employee_a"]["employee_id"]
    blocker_id = _seed_1030_blocker(scenario)
    blocker_b_id = _seed_1030_blocker(scenario, scenario["employee_b"]["employee_id"])
    created_ids: list[str] = []

    try:
        long_web = client.get(
            "/disponibilidad",
            params={"cliente_id": CID, "fecha": fecha, "employee_id": employee_id, "servicio": long_name},
            headers=ORIGIN,
        ).json()
        short_web = client.get(
            "/disponibilidad",
            params={"cliente_id": CID, "fecha": fecha, "employee_id": employee_id, "servicio": short_name},
            headers=ORIGIN,
        ).json()
        long_slots = {item["hora"]: item["disponible"] for item in long_web["slots"]}
        short_slots = {item["hora"]: item["disponible"] for item in short_web["slots"]}
        assert long_slots["10:00"] is False
        assert short_slots["10:00"] is True
        assert short_slots["10:15"] is True
        assert short_slots["10:30"] is False
        assert long_slots["10:45"] is True

        chat_long = client.post(
            "/chat",
            headers=ORIGIN,
            json={"cliente_id": CID, "mensaje": f"Hay hueco para {long_name} el proximo lunes?", "session_id": "qa-chat-long"},
        )
        chat_short = client.post(
            "/chat",
            headers=ORIGIN,
            json={"cliente_id": CID, "mensaje": f"Hay hueco para {short_name} el proximo lunes?", "session_id": "qa-chat-short"},
        )
        assert chat_long.status_code == 200 and "10:00" not in chat_long.json()["respuesta"]
        assert chat_short.status_code == 200 and "10:00" in chat_short.json()["respuesta"]

        voice_long = asyncio.run(api._voice_check_availability(CID, fecha, long_name))
        voice_short = asyncio.run(api._voice_check_availability(CID, fecha, short_name))
        assert "10:00" not in voice_long["huecos"]
        assert "10:00" in voice_short["huecos"]

        wa_lists: list[dict] = []

        async def fake_list(**kwargs):
            wa_lists.append(kwargs)
            return True

        async def fake_text(**kwargs):
            return True

        from backend import appstate, messaging

        monkeypatch.setattr(messaging, "_send_whatsapp_list", fake_list)
        monkeypatch.setattr(messaging, "_send_whatsapp_text", fake_text)
        assert asyncio.run(api._wa_send_time_picker(
            cliente_id=CID, phone_number_id="PH_QA_A", to_number="34600000001",
            fecha_iso=fecha, fecha_humana="lunes", employee_id=employee_id, servicio=long_name,
        ))
        long_wa_slots = {row["id"].split("time_", 1)[-1] for row in wa_lists[-1]["sections"][0]["rows"]}
        assert "10:00" not in long_wa_slots
        assert asyncio.run(api._wa_send_time_picker(
            cliente_id=CID, phone_number_id="PH_QA_A", to_number="34600000001",
            fecha_iso=fecha, fecha_humana="lunes", employee_id=employee_id, servicio=short_name,
        ))
        short_wa_slots = {row["id"].split("time_", 1)[-1] for row in wa_lists[-1]["sections"][0]["rows"]}
        assert "10:00" in short_wa_slots

        wa_long_flow = appstate.WAFlowState(
            cliente_id=CID,
            from_number="34600000005",
            servicio=long_name,
            employee_id=employee_id,
            employee_name="Profesional A",
            fecha=fecha,
            hora="10:00",
            nombre="WhatsApp larga",
            email="wa@example.com",
        )
        assert asyncio.run(api._wa_create_booking(
            cliente_id=CID, phone_number_id="PH_QA_A", to_number=wa_long_flow.from_number,
            flow=wa_long_flow, config=api.CONFIG_CLIENTES[CID], request=None,
        )) is False
        wa_short_flow = appstate.WAFlowState(
            cliente_id=CID,
            from_number="34600000006",
            servicio=short_name,
            employee_id=employee_id,
            employee_name="Profesional A",
            fecha=fecha,
            hora="10:00",
            nombre="WhatsApp corta",
            email="wa@example.com",
        )
        assert asyncio.run(api._wa_create_booking(
            cliente_id=CID, phone_number_id="PH_QA_A", to_number=wa_short_flow.from_number,
            flow=wa_short_flow, config=api.CONFIG_CLIENTES[CID], request=None,
        )) is True
        with api._get_db_connection() as connection:
            wa_booking = connection.execute(
                "SELECT id FROM bookings WHERE cliente_id = ? AND source = 'whatsapp' AND telefono = ?",
                (CID, wa_short_flow.from_number),
            ).fetchone()
        assert wa_booking is not None
        created_ids.append(wa_booking["id"])
        _delete_booking(scenario, created_ids.pop())

        web_long = client.post(
            "/agendar",
            headers=ORIGIN,
            json={
                "cliente_id": CID, "nombre": "Web larga", "email": "web@example.com",
                "telefono": "600000002", "servicio": long_name, "employee_id": employee_id,
                "fecha": fecha, "hora": "10:00", "notas": "",
            },
        )
        assert web_long.status_code == 409
        web_short = client.post(
            "/agendar",
            headers=ORIGIN,
            json={
                "cliente_id": CID, "nombre": "Web corta", "email": "web@example.com",
                "telefono": "600000002", "servicio": short_name, "employee_id": employee_id,
                "fecha": fecha, "hora": "10:00", "notas": "",
            },
        )
        assert web_short.status_code == 200, web_short.text
        created_ids.append(web_short.json()["booking_id"])
        _delete_booking(scenario, created_ids.pop())

        voice_rejected = asyncio.run(api._voice_perform_booking(
            CID, nombre="Voz larga", telefono="+34600000003", fecha=fecha,
            hora="10:00", servicio=long_name,
        ))
        assert voice_rejected["ok"] is False
        voice_created = asyncio.run(api._voice_perform_booking(
            CID, nombre="Voz corta", telefono="+34600000003", fecha=fecha,
            hora="10:00", servicio=short_name,
        ))
        assert voice_created["ok"] is True, voice_created
        created_ids.append(voice_created["booking_id"])
    finally:
        for booking_id in created_ids:
            _delete_booking(scenario, booking_id)
        _delete_booking(scenario, blocker_id)
        _delete_booking(scenario, blocker_b_id)


def test_multicenter_price_availability_and_direct_booking_guard(scenario):
    client = scenario["client"]
    api = scenario["api"]
    fecha = scenario["fecha"]
    long_service = scenario["long"]
    location_b = scenario["location_b"]["location_id"]
    employee_b = scenario["employee_b"]["employee_id"]
    created_ids: list[str] = []

    override = client.put(
        f"/auth/services/{long_service['id']}/locations/{location_b}",
        params=scenario["params"],
        cookies=scenario["cookies"],
        json={"is_available": True, "price_cents": 9900, "duration_minutes": 45},
    )
    assert override.status_code == 200, override.text
    try:
        booked = client.post(
            "/agendar",
            headers=ORIGIN,
            json={
                "cliente_id": CID, "nombre": "Centro B", "email": "b@example.com",
                "telefono": "600000004", "servicio": long_service["nombre"],
                "employee_id": employee_b, "location_id": location_b,
                "fecha": fecha, "hora": "09:00", "notas": "",
            },
        )
        assert booked.status_code == 200, booked.text
        created_ids.append(booked.json()["booking_id"])
        with api._get_db_connection() as connection:
            row = connection.execute(
                "SELECT service_price_cents, location_id FROM bookings WHERE id = ?",
                (created_ids[-1],),
            ).fetchone()
        assert row["service_price_cents"] == 9900
        assert row["location_id"] == location_b

        disabled = client.put(
            f"/auth/services/{long_service['id']}/locations/{location_b}",
            params=scenario["params"],
            cookies=scenario["cookies"],
            json={"is_available": False},
        )
        assert disabled.status_code == 200
        availability = client.get(
            "/disponibilidad",
            headers=ORIGIN,
            params={
                "cliente_id": CID, "fecha": fecha, "employee_id": employee_b,
                "location_id": location_b, "servicio": long_service["nombre"],
            },
        )
        assert availability.status_code == 400
        rejected = client.post(
            "/agendar",
            headers=ORIGIN,
            json={
                "cliente_id": CID, "nombre": "No permitido", "email": "b@example.com",
                "telefono": "", "servicio": long_service["nombre"], "employee_id": employee_b,
                "location_id": location_b, "fecha": fecha, "hora": "10:00", "notas": "",
            },
        )
        assert rejected.status_code == 400
    finally:
        for booking_id in created_ids:
            _delete_booking(scenario, booking_id)
        client.delete(
            f"/auth/services/{long_service['id']}/locations/{location_b}",
            params=scenario["params"],
            cookies=scenario["cookies"],
        )


def test_room_capacity_overlap_boundaries_and_cancel_release(scenario):
    client = scenario["client"]
    location_a = scenario["location_a"]["location_id"]
    employee_a = scenario["employee_a"]["employee_id"]
    employee_a2 = scenario["employee_a2"]["employee_id"]
    short_name = scenario["short"]["nombre"]
    created_ids: list[str] = []

    room = client.post(
        f"/auth/locations/{location_a}/resources",
        params=scenario["params"],
        cookies=scenario["cookies"],
        json={"name": "Sala unica"},
    )
    assert room.status_code == 200, room.text
    try:
        first = _book_portal(scenario, employee_id=employee_a, servicio=short_name, hora="11:00")
        assert first.status_code == 200, first.text
        created_ids.append(first.json()["booking_id"])

        no_room = _book_portal(scenario, employee_id=employee_a2, servicio=short_name, hora="11:00")
        assert no_room.status_code == 409
        adjacent = _book_portal(scenario, employee_id=employee_a2, servicio=short_name, hora="11:15")
        assert adjacent.status_code == 200, adjacent.text
        created_ids.append(adjacent.json()["booking_id"])

        off_grid = _book_portal(scenario, employee_id=employee_a2, servicio=short_name, hora="11:05")
        assert off_grid.status_code == 409

        cancelled = client.post(
            f"/auth/bookings/{created_ids[0]}/cancel",
            params=scenario["params"],
            cookies=scenario["cookies"],
        )
        assert cancelled.status_code == 200
        released = _book_portal(scenario, employee_id=employee_a2, servicio=short_name, hora="11:00")
        assert released.status_code == 200, released.text
        created_ids.append(released.json()["booking_id"])
    finally:
        for booking_id in created_ids:
            _delete_booking(scenario, booking_id)
        with scenario["api"]._get_db_connection() as connection:
            connection.execute("DELETE FROM resources WHERE cliente_id = ? AND location_id = ?", (CID, location_a))
            connection.commit()
