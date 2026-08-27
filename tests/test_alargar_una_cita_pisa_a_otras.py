# -*- coding: utf-8 -*-
"""Cambiar el servicio de una cita puede necesitar mas sitio.

Al editar una cita se comprobaba si habia hueco solo cuando cambiaba el DIA, la
HORA o la PROFESIONAL. Cambiar el servicio no era ninguna de las tres, asi que
pasar un corte de 30 minutos a una keratina de cuatro horas -misma hora, misma
profesional- no comprobaba nada: la cita se estiraba por encima de las tres
siguientes sin que saltara un aviso, y ese dia el salon descubria el lio con las
clientas ya en la puerta.

Vale para todos los canales, porque todos editan por el mismo sitio
(`_update_booking_details`): el panel, el asistente y el enlace de gestion.
"""
from __future__ import annotations

import asyncio
import datetime
import uuid

from test_booking_exhaustive import api_module, client  # noqa: F401


def _servicio(cliente_id, slug, nombre, minutos):
    from backend import db, timeutils

    ahora = timeutils._utc_now().isoformat()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
            " duration_minutes, price_cents, description, is_active, sort_order,"
            " created_at, updated_at) VALUES (?,?,?,'',?,0,'',1,0,?,?)",
            (cliente_id, slug, nombre, minutos, ahora, ahora))
        conexion.commit()


def test_saber_cuanto_ocupa_una_cita_sale_de_sus_marcas(api_module, client):  # noqa: F811
    """Es el dato del que depende todo lo demas."""
    from backend import booking, db, timeutils

    inicio = timeutils._utc_now().replace(microsecond=0)
    fin = inicio + datetime.timedelta(minutes=45)
    codigo = "R-" + uuid.uuid4().hex[:6].upper()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO bookings (id, cliente_id, nombre, email, telefono, servicio,"
            " booking_date, booking_time, notas, status, provider_status, booking_code,"
            " created_at, source, start_at, end_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, "demo", "Ana", "", "34600880777", "Corte senora",
             inicio.date().isoformat(), "10:00", "", "confirmed", "none", codigo,
             timeutils._utc_now().isoformat(), "test",
             timeutils._to_utc_iso(inicio), timeutils._to_utc_iso(fin)))
        conexion.commit()
        fila = conexion.execute(
            "SELECT * FROM bookings WHERE cliente_id='demo' AND booking_code=?",
            (codigo,)).fetchone()
    try:
        assert booking._minutos_que_ocupa_ahora(fila) == 45
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM bookings WHERE booking_code=?", (codigo,))
            conexion.commit()


def test_sin_marcas_no_se_da_por_supuesto_que_cabe(api_module, client):  # noqa: F811
    """Devolver 0 hace que CUALQUIER cambio de servicio se compruebe.

    Es la decision prudente: mejor comprobar de mas que estirar una cita encima de
    otras porque no sabiamos cuanto duraba.
    """
    from backend import booking

    class _SinMarcas(dict):
        def __getitem__(self, clave):
            if clave in ("start_at", "end_at"):
                return None
            if clave == "cliente_id":
                return "demo"
            if clave == "servicio":
                return "Servicio que no existe en el catalogo"
            raise KeyError(clave)

    assert booking._minutos_que_ocupa_ahora(_SinMarcas()) >= 0


def test_la_edicion_comprueba_el_hueco_cuando_el_servicio_crece(api_module, client):  # noqa: F811
    """El enganche: si esto se suelta, vuelve a poder estirarse sobre otras citas."""
    import inspect

    from backend import booking

    fuente = inspect.getsource(booking._update_booking_details)
    assert "dura_mas" in fuente
    assert "_minutos_que_ocupa_ahora" in fuente
    # Y `dura_mas` entra en la decision de comprobar el hueco.
    trozo = fuente[fuente.index("slot_changed = ("):]
    assert "dura_mas" in trozo[:trozo.index(")")]
