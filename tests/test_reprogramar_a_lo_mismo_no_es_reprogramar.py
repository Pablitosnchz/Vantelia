# -*- coding: utf-8 -*-
"""Mover una cita al mismo día, la misma hora y el mismo servicio no es moverla.

POR QUE EXISTE
--------------
13-sep-2026, banco completo con modelo real sobre 6bed2f1 (copia de producción),
caso `cambiar-la-hora-de-verdad`, primer intento:

    ella «necesito cambiar mi cita de dia»
    IA   reprogramar_cita(15-sep, 17:45)            -> ok: false «YA es de ese dia y esa hora»
    ella «cualquier otro hueco que tengas me vale»  (el modelo no consulta nada)
    ella «vale, la primera opcion que me has dicho»
    IA   reprogramar_cita(15-sep, 17:45,
                          servicio="Acido lactico bio premium-corto medio")  -> ok: TRUE
    IA   «Listo, cariño. He reprogramado tu cita para el martes 15 a las 17:45»

La cita seguía donde estaba (auditoría: `booking_updated` con la misma fecha y hora)
y ella leyó que se la habían movido. El control «ya es de ese día y esa hora» solo
se aplicaba si la llamada NO traía `servicio`; traer el mismo servicio escrito sin
tildes bastaba para saltárselo, y `dijo_haberlo_hecho_sin_hacerlo` no podía saltar
porque la tool había dicho que sí.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

ORIGEN = {"Origin": "http://testserver"}
_HUECOS = iter(["12:%02d" % m for m in (0, 30)] + ["13:%02d" % m for m in (0, 30)]
               + ["14:%02d" % m for m in (0, 30)])


@pytest.fixture(autouse=True)
def sin_rate_limit(api_module):  # noqa: F811
    from backend import appstate

    appstate.rate_limit_buckets.clear()
    yield
    appstate.rate_limit_buckets.clear()


@pytest.fixture
def cita(client):  # noqa: F811
    dia = date.today() + timedelta(days=9)
    while dia.weekday() == 6:
        dia += timedelta(days=1)
    respuesta = client.post("/agendar", json={
        "cliente_id": "demo", "nombre": "Cliente Mover", "email": "mover@ejemplo.com",
        "telefono": "600999777", "fecha": dia.isoformat(), "hora": next(_HUECOS),
        "servicio": "Consulta", "notas": "",
    }, headers=ORIGEN)
    assert respuesta.status_code == 200, respuesta.text[:200]
    return respuesta.json()


def _cita_guardada(codigo):
    from backend import db

    with db._get_db_connection() as cx:
        fila = cx.execute(
            "SELECT id, booking_date, booking_time, servicio FROM bookings"
            " WHERE cliente_id='demo' AND booking_code=?", (codigo,)).fetchone()
        eventos = [e["event_type"] for e in cx.execute(
            "SELECT event_type FROM booking_audit WHERE booking_id=? ORDER BY created_at",
            (fila["id"],))]
    return fila, eventos


@pytest.mark.parametrize("servicio", ["Consulta", "consulta", "  CONSULTA  "])
def test_mismo_dia_hora_y_servicio_no_es_un_cambio(api_module, cita, servicio):  # noqa: F811
    from backend import voice

    antes, eventos_antes = _cita_guardada(cita["booking_code"])

    resultado = asyncio.run(voice._voice_reschedule_booking(
        "demo", cita["booking_code"], antes["booking_date"], antes["booking_time"],
        servicio=servicio, telefono="600999777"))

    assert resultado.get("ok") is False, (
        "se ha dado por reprogramada una cita que no cambia nada: %r" % resultado)
    assert "YA es de ese dia" in str(resultado.get("error") or "")
    despues, eventos_despues = _cita_guardada(cita["booking_code"])
    assert (despues["booking_date"], despues["booking_time"], despues["servicio"]) == (
        antes["booking_date"], antes["booking_time"], antes["servicio"])
    assert eventos_despues == eventos_antes, "se ha auditado un cambio que no existe"


def test_cambiar_solo_el_servicio_no_lo_frena_este_control(api_module, cita):  # noqa: F811
    """Control: cambiar de verdad el servicio, misma fecha y hora, sigue siendo posible.

    Puede fallar por otra razón legítima (el servicio no existe, no cabe), pero no
    por «ya es de ese día y esa hora».
    """
    from backend import voice

    antes, _ = _cita_guardada(cita["booking_code"])

    resultado = asyncio.run(voice._voice_reschedule_booking(
        "demo", cita["booking_code"], antes["booking_date"], antes["booking_time"],
        servicio="Otro servicio distinto", telefono="600999777"))

    assert "YA es de ese dia" not in str(resultado.get("error") or ""), resultado
