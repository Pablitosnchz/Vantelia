# -*- coding: utf-8 -*-
"""No se le manda un recordatorio a quien ya ha cancelado.

`_run_booking_reminders` carga las citas candidatas de una vez y luego recorre la
lista enviando avisos, y cada envio es I/O de red (email, WhatsApp, SMS). Con
agenda cargada ese recorrido dura, y durante ese rato la fila que tiene en
memoria puede haber quedado obsoleta:

- la clienta cancela a las 9:00:05, el worker llega a su fila a las 9:00:30 y le
  llega "te recordamos que mañana tienes cita";
- o reprograma, y el recordatorio le llega con la hora vieja.

La consulta filtra por `status='confirmed'`, pero eso solo vale para el instante
en que se hizo. La cita se relee justo antes de tocarla.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def cita_de_manana(api_module):  # noqa: F811
    """Una cita confirmada dentro de la ventana del recordatorio de 24 h."""
    from backend import booking, db, timeutils

    # 24 h + 20 min: dentro de la banda de tolerancia del recordatorio de 24 h
    # (`grace_minutes` >= 45). A 24 h exactas se caeria por debajo del borde por
    # los segundos que pasan entre crear la cita y correr el worker.
    inicio = timeutils._utc_now() + timedelta(hours=24, minutes=20)
    booking_id = "bk_recordatorio_test"
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conexion.execute(
            "INSERT INTO bookings (id, cliente_id, nombre, email, telefono, servicio,"
            " booking_date, booking_time, status, provider_status, source, manage_token,"
            " booking_code, created_at, start_at, end_at, timezone)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (booking_id, "demo", "Clienta Test", "clienta@ejemplo.com", "600111222",
             "Consulta", inicio.date().isoformat(), inicio.strftime("%H:%M"), "confirmed",
             "internal", "test", "tok_recordatorio_test", "R-REC001", timeutils._utc_now_iso(),
             inicio.isoformat(), (inicio + timedelta(minutes=30)).isoformat(), "Europe/Madrid"),
        )
        conexion.commit()
    yield booking_id
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conexion.commit()


def _capturar_envios(monkeypatch):
    from backend import booking

    enviados = []

    async def falso(booking_row, kind, request=None, **kwargs):
        enviados.append((booking_row["id"], kind))
        return True

    monkeypatch.setattr(booking, "_send_booking_reminder_by_kind", falso)
    return enviados


def test_una_cita_cancelada_entre_medias_no_recibe_recordatorio(
    api_module, cita_de_manana, monkeypatch  # noqa: F811
):
    """Se cancela DESPUES de cargar la lista de candidatas, antes de enviar."""
    from backend import booking, db

    enviados = _capturar_envios(monkeypatch)
    original = booking._bookings_due_for_reminders

    def cargar_y_cancelar(now_utc, **kwargs):
        filas = original(now_utc, **kwargs)
        # La clienta cancela justo despues de que el worker haya hecho su consulta.
        with db._get_db_connection() as conexion:
            conexion.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (cita_de_manana,))
            conexion.commit()
        return filas

    monkeypatch.setattr(booking, "_bookings_due_for_reminders", cargar_y_cancelar)
    asyncio.run(booking._run_booking_reminders())

    assert not [e for e in enviados if e[0] == cita_de_manana], (
        "se ha mandado un recordatorio de una cita cancelada: %r" % enviados
    )


def test_una_cita_confirmada_si_recibe_su_recordatorio(
    api_module, cita_de_manana, monkeypatch  # noqa: F811
):
    """Control: la releida no puede cargarse los recordatorios legitimos."""
    from backend import booking

    enviados = _capturar_envios(monkeypatch)
    asyncio.run(booking._run_booking_reminders())

    assert [e for e in enviados if e[0] == cita_de_manana], (
        "la cita confirmada tenia que recibir su recordatorio de 24 h: %r" % enviados
    )
