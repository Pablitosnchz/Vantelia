"""El panel admin ante lo que no deberia pasar: casos limite de punta a punta.

Clientes con datos incompletos o raros, acciones sobre entidades que ya no
existen, permisos insuficientes y peticiones con campos fuera de rango. Son los
casos que en produccion salen como un 500 y aqui tienen que salir como un error
con sentido.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


CID = "qa_admin_edges"
PARAMS = {"cliente_id": CID}


def _future_open_day(offset: int = 2) -> str:
    day = datetime.now().date() + timedelta(days=offset)
    while day.weekday() == 6:
        day += timedelta(days=1)
    return day.isoformat()


@pytest.fixture(scope="module")
def edge_env(vantelia_env_factory):
    api = vantelia_env_factory(
        {
            CID: {
                "nombre": "QA Administracion",
                "allowed_origins": ["http://testserver"],
                "plan": "business",
                "subscription": {"plan": "business", "status": "active"},
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
        },
        info_txt="SERVICIOS Y PRECIOS:\nPREGUNTAS FRECUENTES:\n",
    )
    client = TestClient(api.app)
    user = api._create_user(
        email="manager.edges@example.com",
        password="manager-pass-123",
        role="client",
        display_name="Manager Edges",
        cliente_id=CID,
        portal_role="manager",
    )
    cookies = {"vantelia_portal_session": api._create_auth_session(user["id"])}
    return api, client, cookies


def _create_service(client, cookies, name: str):
    response = client.post(
        "/auth/services",
        params=PARAMS,
        cookies=cookies,
        json={"nombre": name, "duration_minutes": 30, "price_cents": 3000},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_employee(client, cookies, location_id: str, service_id: str, name: str):
    response = client.post(
        "/auth/employees",
        params=PARAMS,
        cookies=cookies,
        json={
            "name": name,
            "location_id": location_id,
            "service_ids": [service_id],
            "slot_minutes": 15,
            "day_start": "09:00",
            "day_end": "13:00",
            "closed_weekdays": [6],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _book(client, cookies, employee_id: str, service: str, time: str = "10:00"):
    return client.post(
        "/auth/bookings",
        params=PARAMS,
        cookies=cookies,
        json={
            "nombre": "Cliente Edge",
            "email": "edge@example.com",
            "telefono": "+34600999000",
            "servicio": service,
            "employee_id": employee_id,
            "fecha": _future_open_day(),
            "hora": time,
            "notas": "",
        },
    )


def test_service_duplicate_rename_inactive_and_override_reset(edge_env):
    _, client, cookies = edge_env
    first = _create_service(client, cookies, "Servicio Alfa")
    second = _create_service(client, cookies, "Servicio Beta")

    assert client.post(
        "/auth/services",
        params=PARAMS,
        cookies=cookies,
        json={"nombre": "Servicio Alfa"},
    ).status_code == 409
    assert client.patch(
        f"/auth/services/{second['id']}",
        params=PARAMS,
        cookies=cookies,
        json={"nombre": "Servicio Alfa"},
    ).status_code == 409

    location = client.post(
        "/auth/locations",
        params=PARAMS,
        cookies=cookies,
        json={"name": "Centro Override"},
    ).json()
    override_url = f"/auth/services/{first['id']}/locations/{location['location_id']}"
    changed = client.put(
        override_url,
        params=PARAMS,
        cookies=cookies,
        json={"is_available": True, "price_cents": 5500, "duration_minutes": 45},
    )
    changed_item = next(item for item in changed.json()["items"] if item["location_id"] == location["location_id"])
    assert changed_item["has_override"] and changed_item["effective_price_cents"] == 5500
    reset = client.delete(override_url, params=PARAMS, cookies=cookies)
    reset_item = next(item for item in reset.json()["items"] if item["location_id"] == location["location_id"])
    assert not reset_item["has_override"] and reset_item["effective_price_cents"] == 3000

    assert client.patch(
        f"/auth/services/{first['id']}", params=PARAMS, cookies=cookies, json={"is_active": False}
    ).status_code == 200
    public = client.get(f"/servicios/{CID}", headers={"Origin": "http://testserver"}).json()["servicios"]
    assert all(item["id"] != first["id"] for item in public)


def test_dependencies_protect_employee_location_and_resource(edge_env):
    _, client, cookies = edge_env
    service = _create_service(client, cookies, "Servicio Dependencias")
    default_location = next(
        item for item in client.get("/auth/locations", params=PARAMS, cookies=cookies).json()["items"]
        if item["is_default"]
    )
    location = client.post(
        "/auth/locations", params=PARAMS, cookies=cookies, json={"name": "Centro Dependencias"}
    ).json()
    employee = _create_employee(client, cookies, location["location_id"], service["id"], "Profesional Dependencias")
    resource = client.post(
        f"/auth/locations/{location['location_id']}/resources",
        params=PARAMS,
        cookies=cookies,
        json={"name": "Sala Dependencias"},
    ).json()
    booking = _book(client, cookies, employee["employee_id"], service["nombre"])
    assert booking.status_code == 200, booking.text
    booking_id = booking.json()["booking_id"]

    assert client.post(
        f"/auth/employees/{employee['employee_id']}",
        params=PARAMS,
        cookies=cookies,
        json={"name": employee["name"], "is_active": False},
    ).status_code == 409
    assert client.delete(
        f"/auth/employees/{employee['employee_id']}", params=PARAMS, cookies=cookies
    ).status_code == 409
    assert client.post(
        f"/auth/locations/{location['location_id']}",
        params=PARAMS,
        cookies=cookies,
        json={"name": location["name"], "is_active": False},
    ).status_code == 409
    assert client.delete(
        f"/auth/locations/{location['location_id']}", params=PARAMS, cookies=cookies
    ).status_code == 409
    assert client.post(
        f"/auth/resources/{resource['resource_id']}",
        params=PARAMS,
        cookies=cookies,
        json={"name": resource["name"], "is_active": False},
    ).status_code == 409
    assert client.delete(
        f"/auth/resources/{resource['resource_id']}", params=PARAMS, cookies=cookies
    ).status_code == 409
    assert client.post(
        f"/auth/locations/{default_location['location_id']}",
        params=PARAMS,
        cookies=cookies,
        json={"name": default_location["name"], "is_active": False},
    ).status_code == 409
    assert client.delete(
        f"/auth/locations/{default_location['location_id']}", params=PARAMS, cookies=cookies
    ).status_code == 409

    assert client.post(f"/auth/bookings/{booking_id}/cancel", cookies=cookies, json={"motivo": "QA"}).status_code == 200
    assert client.post(
        f"/auth/resources/{resource['resource_id']}",
        params=PARAMS,
        cookies=cookies,
        json={"name": resource["name"], "is_active": False},
    ).status_code == 200
    assert client.post(
        f"/auth/employees/{employee['employee_id']}",
        params=PARAMS,
        cookies=cookies,
        json={"name": employee["name"], "is_active": False},
    ).status_code == 200
    assert client.post(
        f"/auth/locations/{location['location_id']}",
        params=PARAMS,
        cookies=cookies,
        json={"name": location["name"], "is_active": False},
    ).status_code == 409  # sigue teniendo el profesional asignado, aunque este inactivo


def test_agenda_block_validation_conflict_and_idempotency(edge_env):
    _, client, cookies = edge_env
    date = _future_open_day(5)
    base = {"fecha": date, "hora_inicio": "10:00", "hora_fin": "11:00", "motivo": "QA"}
    created = client.post("/auth/schedule/blocks", params=PARAMS, cookies=cookies, json=base)
    assert created.status_code == 200 and created.json()["created_count"] == 1
    duplicate = client.post("/auth/schedule/blocks", params=PARAMS, cookies=cookies, json=base)
    assert duplicate.status_code == 200
    assert duplicate.json()["created_count"] == 0 and duplicate.json()["skipped_count"] == 1
    assert client.post(
        "/auth/schedule/blocks",
        params=PARAMS,
        cookies=cookies,
        json={**base, "hora_inicio": "11:00", "hora_fin": "10:00"},
    ).status_code == 400
    assert client.post(
        "/auth/schedule/blocks",
        params=PARAMS,
        cookies=cookies,
        json={**base, "fecha_fin": (datetime.fromisoformat(date).date() - timedelta(days=1)).isoformat()},
    ).status_code == 400
    assert client.post(
        "/auth/schedule/blocks",
        params=PARAMS,
        cookies=cookies,
        json={**base, "fecha_fin": (datetime.fromisoformat(date).date() + timedelta(days=366)).isoformat()},
    ).status_code == 400


def test_schedule_changes_cannot_leave_future_bookings_outside_hours(edge_env):
    _, client, cookies = edge_env
    service = _create_service(client, cookies, "Servicio Horario Protegido")
    default_location = next(
        item for item in client.get("/auth/locations", params=PARAMS, cookies=cookies).json()["items"]
        if item["is_default"]
    )
    employee = _create_employee(
        client,
        cookies,
        default_location["location_id"],
        service["id"],
        "Profesional Horario Protegido",
    )
    booking = _book(client, cookies, employee["employee_id"], service["nombre"], "10:00")
    assert booking.status_code == 200, booking.text
    booking_id = booking.json()["booking_id"]
    schedule = {
        "enabled": True,
        "timezone": "Europe/Madrid",
        "slot_minutes": 15,
        "day_start": "11:00",
        "day_end": "13:00",
        "break_windows": [],
        "closed_weekdays": [6],
    }

    response = client.post(
        f"/auth/schedule/employee/{employee['employee_id']}",
        params=PARAMS,
        cookies=cookies,
        json=schedule,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["type"] == "schedule_booking_conflicts"

    response = client.post(
        f"/auth/employees/{employee['employee_id']}",
        params=PARAMS,
        cookies=cookies,
        json={"name": employee["name"], "day_end": "10:15"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["type"] == "schedule_booking_conflicts"

    booking_weekday = datetime.fromisoformat(_future_open_day()).weekday()
    response = client.post(
        f"/auth/employees/{employee['employee_id']}",
        params=PARAMS,
        cookies=cookies,
        json={"name": employee["name"], "closed_weekdays": [booking_weekday, 6]},
    )
    assert response.status_code == 409

    assert client.post(f"/auth/bookings/{booking_id}/cancel", cookies=cookies, json={"motivo": "QA"}).status_code == 200
    assert client.post(
        f"/auth/schedule/employee/{employee['employee_id']}",
        params=PARAMS,
        cookies=cookies,
        json=schedule,
    ).status_code == 200


def test_expired_disabled_and_wrong_service_commerce_cases(edge_env):
    api, client, cookies = edge_env
    service_a = _create_service(client, cookies, "Servicio Bono A")
    service_b = _create_service(client, cookies, "Servicio Bono B")
    default_location = next(
        item for item in client.get("/auth/locations", params=PARAMS, cookies=cookies).json()["items"]
        if item["is_default"]
    )
    employee = _create_employee(
        client,
        cookies,
        default_location["location_id"],
        service_a["id"],
        "Profesional Comercio Edge",
    )
    assert client.post(
        f"/auth/employees/{employee['employee_id']}",
        params=PARAMS,
        cookies=cookies,
        json={"name": employee["name"], "service_ids": [service_a["id"], service_b["id"]]},
    ).status_code == 200
    booking_a = _book(client, cookies, employee["employee_id"], service_a["nombre"], "09:00")
    booking_b = _book(client, cookies, employee["employee_id"], service_b["nombre"], "09:30")
    assert booking_a.status_code == 200 and booking_b.status_code == 200

    package = client.post(
        "/auth/packages",
        params=PARAMS,
        cookies=cookies,
        json={
            "name": "Bono Solo A",
            "items": [{"service_slug": service_a["id"], "qty": 2}],
            "price_cents": 5000,
            "validity_days": 30,
        },
    )
    assert package.status_code == 200, package.text
    purchase = client.post(
        f"/auth/packages/{package.json()['id']}/sell",
        params=PARAMS,
        cookies=cookies,
        json={"buyer_email": "bono-edge@example.com"},
    )
    purchase_id = purchase.json()["purchase_id"]
    assert client.post(
        f"/auth/package-purchases/{purchase_id}/redeem",
        params=PARAMS,
        cookies=cookies,
        json={"booking_id": booking_b.json()["booking_id"]},
    ).status_code == 409
    with api._get_db_connection() as connection:
        connection.execute(
            "UPDATE package_purchases SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", purchase_id),
        )
        connection.commit()
    expired_package = client.post(
        f"/auth/package-purchases/{purchase_id}/redeem",
        params=PARAMS,
        cookies=cookies,
        json={"booking_id": booking_a.json()["booking_id"]},
    )
    assert expired_package.status_code == 409
    assert "expired" in str(expired_package.json()["detail"])

    wrong_code = client.post(
        "/auth/gift-cards/redeem",
        params=PARAMS,
        cookies=cookies,
        json={"code": "GC-NOPE-NOPE", "booking_id": booking_a.json()["booking_id"]},
    )
    assert wrong_code.status_code == 404
    disabled_card = client.post(
        "/auth/gift-cards", params=PARAMS, cookies=cookies, json={"amount_cents": 5000}
    ).json()
    assert client.post(
        f"/auth/gift-cards/{disabled_card['gift_card_id']}/status",
        params=PARAMS,
        cookies=cookies,
        json={"enabled": False},
    ).status_code == 200
    assert client.post(
        "/auth/gift-cards/redeem",
        params=PARAMS,
        cookies=cookies,
        json={"code": disabled_card["code"], "booking_id": booking_a.json()["booking_id"]},
    ).status_code == 409

    expired_card = client.post(
        "/auth/gift-cards", params=PARAMS, cookies=cookies, json={"amount_cents": 5000}
    ).json()
    with api._get_db_connection() as connection:
        connection.execute(
            "UPDATE gift_cards SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", expired_card["gift_card_id"]),
        )
        connection.commit()
    expired_gift = client.post(
        "/auth/gift-cards/redeem",
        params=PARAMS,
        cookies=cookies,
        json={"code": expired_card["code"], "booking_id": booking_a.json()["booking_id"]},
    )
    assert expired_gift.status_code == 409
    assert "expired" in str(expired_gift.json()["detail"])
