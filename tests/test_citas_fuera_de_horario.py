# -*- coding: utf-8 -*-
"""El mostrador puede apuntar citas fuera del horario. La IA no.

POR QUE EXISTE
--------------
Peticion literal del salon piloto (9-sep-2026):

    "Abrimos a las 10:00 de la mañana pero hay veces que necesitamos abrir a las
     nueve o a las ocho por algún evento, y necesito que la agenda me dé la opción
     de poder escribir citas antes, fuera de nuestro horario normal. Que la IA no
     coja citas fuera de sus horarios me parece bien, esos horarios extras los
     hacemos nosotras personalmente; pero la agenda me tiene que permitir
     escribirlo."

O sea: dos reglas distintas para la misma agenda segun quien escriba. Lo que NO
cambia para nadie es lo que puede hacer dano: pisar otra cita, un bloqueo o el
aforo del centro.
"""
from __future__ import annotations

import asyncio
import datetime

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CID = "demo"


def _dia_util():
    from backend import timeutils

    dia = timeutils._utc_now().date() + datetime.timedelta(days=2)
    while dia.weekday() == 6:
        dia += datetime.timedelta(days=1)
    return dia.isoformat()


def _limpiar(bid):
    from backend import db

    with db._get_db_connection() as cx:
        cx.execute("DELETE FROM bookings WHERE id=?", (bid,))
        cx.commit()


def test_el_mostrador_puede_apuntar_antes_de_abrir(api_module):  # noqa: F811
    from backend import agenda, booking

    fecha = _dia_util()
    emp = agenda._resolve_employee_for_booking(CID, "", require_active=False)
    cita = asyncio.run(booking._create_booking_core(
        CID, employee_row=emp, nombre="Clienta Evento", email="", telefono="600777888",
        servicio="", booking_date=fecha, booking_time="08:00", notas="",
        source="portal_manual", send_confirmation=False, fuera_de_horario=True,
    ))
    try:
        assert cita["booking_time"] == "08:00"
    finally:
        _limpiar(cita["id"])


def test_la_ia_sigue_sin_poder(api_module):  # noqa: F811
    """Lo que pidio el salon: los horarios extra los hacen ellas, no el asistente."""
    from backend import agenda, booking
    from fastapi import HTTPException

    fecha = _dia_util()
    emp = agenda._resolve_employee_for_booking(CID, "", require_active=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(booking._create_booking_core(
            CID, employee_row=emp, nombre="Clienta Chat", email="", telefono="600777999",
            servicio="", booking_date=fecha, booking_time="08:00", notas="",
            source="whatsapp", send_confirmation=False,
        ))
    assert exc.value.status_code == 409


def test_fuera_de_horario_tampoco_pisa_otra_cita(api_module):  # noqa: F811
    """La puerta se abre para el horario, no para las colisiones."""
    from backend import agenda, booking
    from fastapi import HTTPException

    fecha = _dia_util()
    emp = agenda._resolve_employee_for_booking(CID, "", require_active=False)
    primera = asyncio.run(booking._create_booking_core(
        CID, employee_row=emp, nombre="Primera", email="", telefono="600111000",
        servicio="", booking_date=fecha, booking_time="08:00", notas="",
        source="portal_manual", send_confirmation=False, fuera_de_horario=True,
    ))
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(booking._create_booking_core(
                CID, employee_row=emp, nombre="Segunda", email="", telefono="600222000",
                servicio="", booking_date=fecha, booking_time="08:00", notas="",
                source="portal_manual", send_confirmation=False, fuera_de_horario=True,
            ))
        assert exc.value.status_code == 409
    finally:
        _limpiar(primera["id"])


def test_el_endpoint_del_portal_lo_permite(api_module):  # noqa: F811
    """No basta con que el nucleo lo acepte: el portal tiene que pedirlo."""
    import inspect

    from backend.routers import portal_app

    fuente = inspect.getsource(portal_app)
    assert "fuera_de_horario=True" in fuente
    assert "en_rejilla=False" in fuente


def test_el_pasado_sigue_cerrado(api_module):  # noqa: F811
    """"Fuera de horario" no es "cualquier cosa": una cita de ayer es un error.

    Se me colo al abrir esta puerta -el portal aceptaba un 200 donde daba 409- y lo
    caza el test de siempre del humo.
    """
    import datetime

    from backend import agenda, booking
    from fastapi import HTTPException

    ayer = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    emp = agenda._resolve_employee_for_booking(CID, "", require_active=False)
    with pytest.raises(HTTPException):
        asyncio.run(booking._create_booking_core(
            CID, employee_row=emp, nombre="Cita de ayer", email="", telefono="600123123",
            servicio="", booking_date=ayer, booking_time="08:00", notas="",
            source="portal_manual", send_confirmation=False, fuera_de_horario=True,
        ))


def test_el_descanso_se_respeta(api_module):  # noqa: F811
    """Abrir antes por un evento es una cosa; meter a alguien en mitad de la
    parada de comer es otra, y esa parada cierra la agenda de TODO el equipo."""
    from backend import agenda

    emp = agenda._resolve_employee_for_booking(CID, "", require_active=False)
    ventanas = [{"start": "14:00", "end": "15:00"}]   # el formato real del config
    original = agenda._client_break_windows
    agenda._client_break_windows = lambda config: ventanas
    try:
        assert agenda._pisa_un_descanso(CID, 14 * 60 + 30, 14 * 60 + 45, emp)
        assert not agenda._pisa_un_descanso(CID, 8 * 60, 8 * 60 + 30, emp)
    finally:
        agenda._client_break_windows = original


def test_un_dia_cerrado_sigue_cerrado(api_module):  # noqa: F811
    """Lo pidio por HORAS, no por dias.

    Adelantar la apertura es una cosa; abrir un domingo que se pinta "No
    disponible" de arriba abajo es otra, y ahi una cita seria una sorpresa. Si
    algun dia hacen eventos en domingo se abre quitando esa comprobacion.
    """
    import datetime

    from backend import agenda, booking
    from fastapi import HTTPException

    dia = datetime.date.today() + datetime.timedelta(days=1)
    while dia.weekday() != 6:
        dia += datetime.timedelta(days=1)
    emp = agenda._resolve_employee_for_booking(CID, "", require_active=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(booking._create_booking_core(
            CID, employee_row=emp, nombre="Domingo", email="", telefono="600321321",
            servicio="", booking_date=dia.isoformat(), booking_time="08:00", notas="",
            source="portal_manual", send_confirmation=False, fuera_de_horario=True,
        ))
    assert exc.value.status_code == 409
