"""Horario por DIA DE LA SEMANA (weekly_hours).

Cubre el caso real que lo motivo (peluqueria de Elche: martes y miercoles hasta
las 18:30, jueves y viernes hasta las 20:30, sabado corto 09:00-14:00, lunes y
domingo cerrados) contra la franja unica `day_start`/`day_end`, que no puede
describirlo. Se valida en las TRES capas que consumen el horario: normalizador,
construccion de huecos (todos los canales pasan por `_build_slots_for_day`) y la
matriz semanal que alimenta los prompts de chat y voz.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient

WEEKLY = {
    "0": {"closed": True},
    "1": {"start": "10:00", "end": "18:30"},
    "2": {"start": "10:00", "end": "18:30"},
    "3": {"start": "10:00", "end": "20:30"},
    "4": {"start": "10:00", "end": "20:30"},
    "5": {"start": "09:00", "end": "14:00"},
    "6": {"closed": True},
}

CONFIG = {
    "salon": {
        "nombre": "Salon Test",
        "icono": "S",
        "color": "#111111",
        "bienvenida": "Hola",
        "allowed_origins": ["http://testserver"],
        "booking": {
            "enabled": True,
            "timezone": "Europe/Madrid",
            "slot_minutes": 30,
            "day_start": "09:00",
            "day_end": "20:30",
            "closed_weekdays": [0, 6],
            "weekly_hours": WEEKLY,
            "provider": "internal",
            "success_message": "Registrada.",
        },
    }
}

INFO = """SALON TEST

SERVICIOS Y PRECIOS:

1. Corte
- Precio: 20 €
- Duracion: 60 min
"""


@pytest.fixture(scope="module")
def salon_api(vantelia_env_factory):
    return vantelia_env_factory(CONFIG, info_txt={"salon": INFO})


def _next_weekday(weekday: int) -> datetime.date:
    """Proxima fecha (futura) con ese dia de la semana, con margen de una semana
    para que la ventana de reserva y el 'hoy' nunca recorten los huecos."""
    today = datetime.date.today()
    ahead = (weekday - today.weekday()) % 7 or 7
    return today + datetime.timedelta(days=ahead + 7)


def test_normalizer_resolves_window_per_weekday(salon_api):
    from backend import textnorm as tn

    weekly = tn._normalize_weekly_hours(WEEKLY)
    schedule = {
        "day_start": "09:00",
        "day_end": "20:30",
        "closed_weekdays": [0, 6],
        "weekly_hours": weekly,
    }
    assert tn._weekday_hours(schedule, 0) is None          # lunes cerrado
    assert tn._weekday_hours(schedule, 1) == ("10:00", "18:30")
    assert tn._weekday_hours(schedule, 3) == ("10:00", "20:30")
    assert tn._weekday_hours(schedule, 5) == ("09:00", "14:00")
    assert tn._weekday_hours(schedule, 6) is None          # domingo cerrado


def test_normalizer_ignores_invalid_and_rejects_inverted(salon_api):
    from fastapi import HTTPException

    from backend import textnorm as tn

    assert tn._normalize_weekly_hours(None) == {}
    assert tn._normalize_weekly_hours({"9": {"start": "10:00", "end": "12:00"}}) == {}
    assert tn._normalize_weekly_hours({"1": {}}) == {}
    with pytest.raises(HTTPException):
        tn._normalize_weekly_hours({"1": {"start": "18:00", "end": "10:00"}})


def test_slots_respect_each_weekday_window(salon_api):
    client = TestClient(salon_api.app)
    headers = {"Origin": "http://testserver"}

    # Sabado corto: un servicio de 60 min no puede empezar despues de las 13:00.
    sat = _next_weekday(5)
    res = client.get(
        "/disponibilidad",
        params={"cliente_id": "salon", "fecha": sat.isoformat(), "servicio": "Corte"},
        headers=headers,
    )
    assert res.status_code == 200
    horas = [s["hora"] for s in res.json()["slots"]]
    assert horas[0] == "09:00"
    assert horas[-1] == "13:00"

    # Martes: cierra a las 18:30 -> ultimo inicio 17:30.
    tue = _next_weekday(1)
    horas_tue = [
        s["hora"]
        for s in client.get(
            "/disponibilidad",
            params={"cliente_id": "salon", "fecha": tue.isoformat(), "servicio": "Corte"},
            headers=headers,
        ).json()["slots"]
    ]
    assert horas_tue[0] == "10:00"
    assert horas_tue[-1] == "17:30"

    # Jueves: cierra a las 20:30 -> ultimo inicio 19:30.
    thu = _next_weekday(3)
    horas_thu = [
        s["hora"]
        for s in client.get(
            "/disponibilidad",
            params={"cliente_id": "salon", "fecha": thu.isoformat(), "servicio": "Corte"},
            headers=headers,
        ).json()["slots"]
    ]
    assert horas_thu[-1] == "19:30"

    # Lunes cerrado: sin huecos.
    mon = _next_weekday(0)
    assert (
        client.get(
            "/disponibilidad",
            params={"cliente_id": "salon", "fecha": mon.isoformat(), "servicio": "Corte"},
            headers=headers,
        ).json()["slots"]
        == []
    )


def test_booking_outside_weekday_window_is_rejected(salon_api):
    client = TestClient(salon_api.app)
    headers = {"Origin": "http://testserver"}
    sat = _next_weekday(5)
    payload = {
        "cliente_id": "salon",
        "nombre": "Cliente Test",
        "email": "cliente@example.com",
        "telefono": "600111222",
        "servicio": "Corte",
        "fecha": sat.isoformat(),
        "hora": "18:00",  # el sabado cierra a las 14:00
    }
    assert client.post("/agendar", json=payload, headers=headers).status_code == 409

    payload["hora"] = "10:00"  # dentro de la franja del sabado
    assert client.post("/agendar", json=payload, headers=headers).status_code in (200, 201)


def test_weekly_matrix_feeds_prompts_with_real_hours(salon_api):
    from backend import agenda, clients

    matrix = agenda._weekly_schedule_matrix("salon", clients._get_client_config("salon"))
    by_weekday = {item["weekday"]: item for item in matrix}
    assert by_weekday[0]["closed"] is True
    assert (by_weekday[1]["start"], by_weekday[1]["end"]) == ("10:00", "18:30")
    assert (by_weekday[3]["start"], by_weekday[3]["end"]) == ("10:00", "20:30")
    assert (by_weekday[5]["start"], by_weekday[5]["end"]) == ("09:00", "14:00")
    assert by_weekday[6]["closed"] is True
