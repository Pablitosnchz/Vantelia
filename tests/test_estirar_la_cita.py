# -*- coding: utf-8 -*-
"""Estirar o acortar una cita arrastrando su borde, y que el asistente se entere.

POR QUE EXISTE
--------------
Peticion del salon piloto (9-sep-2026), viendo su agenda de verdad al lado de la
nuestra: la duracion del catalogo es una MEDIA, y ellas saben lo que tarda esa
clienta en concreto -"el mismo color, a una le lleva media hora mas"-. En su
programa de siempre estiran la cita con el raton.

Lo que se vigila aqui no es el raton, es lo de detras: la duracion a mano se
guarda en `end_at`, que es de donde sale la disponibilidad. Si se guardara solo
para pintarlo, el calendario ensenyaria una cosa y el asistente ofreceria otra: le
daria a otra clienta un hueco que en realidad esta ocupado, que es el fallo que
mas caro sale en un salon.
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CID = "demo"


def _payload(booking, **cambios):
    from api_models import BookingUpdatePayload

    datos = {
        "nombre": booking["nombre"] or "Clienta",
        "email": booking["email"] or "",
        "telefono": booking["telefono"] or "",
        "servicio": booking["servicio"] or "",
        "employee_id": booking["employee_id"] or "",
        "fecha": booking["booking_date"],
        "hora": booking["booking_time"],
        "notas": "",
    }
    datos.update(cambios)
    return BookingUpdatePayload(**datos)


@pytest.fixture
def una_cita(api_module):  # noqa: F811
    """Una cita real de mañana, creada por el mismo nucleo que usa el portal."""
    import datetime

    from backend import agenda, booking, db, timeutils

    fecha = (timeutils._utc_now().date() + datetime.timedelta(days=1)).isoformat()
    empleado = agenda._resolve_employee_for_booking(CID, "", require_active=False)
    creada = asyncio.run(booking._create_booking_core(
        CID, employee_row=empleado, nombre="Clienta Prueba", email="c@example.com",
        telefono="600111222", servicio="", booking_date=fecha, booking_time="10:00",
        notas="", source="portal_manual", send_confirmation=False,
    ))
    bid = creada["id"]
    fila = booking._load_booking_or_404(bid)
    yield fila
    with db._get_db_connection() as cx:
        cx.execute("DELETE FROM bookings WHERE id=?", (bid,))
        cx.commit()


def _minutos(fila):
    from backend import agenda

    return agenda._booking_row_duration_min(fila, CID)


def test_se_puede_alargar(api_module, una_cita):  # noqa: F811
    from backend import booking

    antes = _minutos(una_cita)
    asyncio.run(booking._update_booking_details(
        una_cita, _payload(una_cita, duracion_minutos=antes + 45), None, source="portal"))
    despues = booking._load_booking_or_404(una_cita["id"])
    assert _minutos(despues) == antes + 45


def test_se_puede_acortar(api_module, una_cita):  # noqa: F811
    from backend import booking

    asyncio.run(booking._update_booking_details(
        una_cita, _payload(una_cita, duracion_minutos=15), None, source="portal"))
    despues = booking._load_booking_or_404(una_cita["id"])
    assert _minutos(despues) == 15


def test_sin_duracion_manda_el_catalogo(api_module, una_cita):  # noqa: F811
    """Lo de siempre no cambia: sin pedir duracion, la del servicio."""
    from backend import booking

    antes = _minutos(una_cita)
    asyncio.run(booking._update_booking_details(
        una_cita, _payload(una_cita), None, source="portal"))
    despues = booking._load_booking_or_404(una_cita["id"])
    assert _minutos(despues) == antes


def test_el_asistente_ve_la_cita_estirada(api_module, una_cita):  # noqa: F811
    """LO IMPORTANTE: estirarla ocupa la agenda de verdad, no solo el dibujo."""
    from backend import agenda, booking

    fecha = una_cita["booking_date"]
    empleado = una_cita["employee_id"] or ""
    asyncio.run(booking._update_booking_details(
        una_cita, _payload(una_cita, duracion_minutos=180), None, source="portal"))

    ocupados = agenda._booked_intervals(CID, fecha, employee_id=empleado)
    assert any(ini <= 600 and fin >= 600 + 180 for ini, fin in ocupados), (
        "la agenda no ve la cita estirada: el asistente ofreceria ese rato"
    )
    _, libres = asyncio.run(agenda._public_slot_sets_for_day(CID, fecha))
    dentro = [h for h in libres if "11:00" <= h < "13:00"]
    assert not dentro, "sigue ofreciendo huecos dentro de la cita estirada: %s" % dentro


def test_no_se_puede_estirar_encima_de_otra(api_module, una_cita):  # noqa: F811
    """Estirar no puede pisar a la clienta de despues."""
    import datetime

    from backend import agenda, booking, db, timeutils
    from fastapi import HTTPException

    fecha = una_cita["booking_date"]
    empleado = agenda._resolve_employee_for_booking(CID, una_cita["employee_id"] or "",
                                                    require_active=False)
    otra = asyncio.run(booking._create_booking_core(
        CID, employee_row=empleado, nombre="Otra Clienta", email="", telefono="600333444",
        servicio="", booking_date=fecha, booking_time="11:00", notas="",
        source="portal_manual", send_confirmation=False,
    ))
    bid = otra["id"]
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(booking._update_booking_details(
                una_cita, _payload(una_cita, duracion_minutos=180), None, source="portal"))
        assert exc.value.status_code == 409
    finally:
        with db._get_db_connection() as cx:
            cx.execute("DELETE FROM bookings WHERE id=?", (bid,))
            cx.commit()


def test_estirar_no_le_manda_nada_a_la_clienta(api_module, una_cita, monkeypatch):  # noqa: F811
    """"no hace falta mandar recordatorio de cambio de cita" (el salon).

    Viene a la misma hora, con la misma persona y a lo mismo: que le llegue un
    email cada vez que en el mostrador ajustan el hueco es ruido, y encima le
    reiniciaba el recordatorio -asi que le llegaria dos veces-.
    """
    from backend import booking

    avisos = []

    async def _espia(row, kind, request=None):
        avisos.append(kind)

    monkeypatch.setattr(booking, "_send_booking_reminder_by_kind", _espia)
    asyncio.run(booking._update_booking_details(
        una_cita, _payload(una_cita, duracion_minutos=90), None, source="portal"))
    assert avisos == [], "estirar la cita le manda un aviso a la clienta: %s" % avisos


def test_moverla_de_hora_si_avisa(api_module, una_cita, monkeypatch):  # noqa: F811
    """El freno es SOLO para la duracion: cambiarle la hora se le sigue diciendo."""
    from backend import booking

    avisos = []

    async def _espia(row, kind, request=None):
        avisos.append(kind)

    monkeypatch.setattr(booking, "_send_booking_reminder_by_kind", _espia)
    asyncio.run(booking._update_booking_details(
        una_cita, _payload(una_cita, hora="12:00", duracion_minutos=90), None, source="portal"))
    assert avisos == ["rescheduled"], avisos


def test_estirar_no_le_reinicia_el_recordatorio(api_module, una_cita):  # noqa: F811
    from backend import booking, db, timeutils

    with db._get_db_connection() as cx:
        cx.execute("UPDATE bookings SET reminder_24h_sent_at=? WHERE id=?",
                   (timeutils._utc_now_iso(), una_cita["id"]))
        cx.commit()
    fila = booking._load_booking_or_404(una_cita["id"])
    asyncio.run(booking._update_booking_details(
        fila, _payload(fila, duracion_minutos=75), None, source="portal"))
    despues = booking._load_booking_or_404(una_cita["id"])
    assert despues["reminder_24h_sent_at"], "le llegaria el recordatorio dos veces"
