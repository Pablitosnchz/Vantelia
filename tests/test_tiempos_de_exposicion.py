# -*- coding: utf-8 -*-
"""Los ratos de exposicion de un pack tienen que verse en el panel.

Un pack de 150 minutos con 20 de trabajo, 45 de espera, 10 de trabajo, 15 de
espera y 60 de trabajo NO ocupa 150 minutos de la profesional: ocupa 90. En medio
la clienta espera con el producto puesto y se puede atender a otra.

La agenda ya lo respetaba al dar hora (comprobado aqui abajo). Lo que fallaba era
la pantalla: la funcion que calcula los tramos estaba escrita, el campo declarado
en el modelo y la vista preparada para pintarlos... pero nadie llamaba a la
funcion, asi que el panel recibia `work_intervals: None` y pintaba el pack macizo.
El negocio veia la tarde entera cogida y no metia a nadie.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

def _correr(corrutina):
    """Ejecuta una corrutina con bucle PROPIO.

    `asyncio.get_event_loop()` explota ("no current event loop") en cuanto otro
    modulo de la suite ha cerrado el suyo: estos tests pasaban sueltos y fallaban
    al correr la suite entera.
    """
    return asyncio.run(corrutina)


TRAMOS = json.dumps([{"activo": 20, "espera": 45},
                     {"activo": 10, "espera": 15},
                     {"activo": 60, "espera": 0}])


# Profesional PROPIA para estos tests: la agenda del tenant de pruebas la llenan
# otros tests, y con ella compartida estos fallaban solo al correr la suite entera.
EMPLEADA = "emp_exposicion_qa"


@pytest.fixture
def pack_con_esperas(api_module, client):  # noqa: F811
    from backend import agenda, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
            " duration_minutes, price_cents, description, is_active, sort_order,"
            " gap_json, created_at, updated_at) VALUES ('demo', ?, 'Pack con esperas',"
            " '', 150, 9000, '', 1, 0, ?, ?, ?)",
            (agenda._normalize_service_id("Pack con esperas"), TRAMOS, ahora, ahora))
        conexion.execute(
            "INSERT OR REPLACE INTO employees (id, cliente_id, name, is_active,"
            " is_default, service_ids_json, created_at, updated_at)"
            " VALUES (?, 'demo', 'Prueba exposicion', 1, 0, '[]', ?, ?)",
            (EMPLEADA, ahora, ahora))
        conexion.commit()
    yield
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND name='Pack con esperas'")
        conexion.execute("DELETE FROM bookings WHERE cliente_id='demo' AND employee_id=?", (EMPLEADA,))
        conexion.execute("DELETE FROM employees WHERE id=?", (EMPLEADA,))
        conexion.commit()


def _coger_el_pack(desde_dias=3):
    """Coge el pack a las 10:00 el primer dia que se pueda, y devuelve (fila, dia).

    Buscando un dia en vez de fijarlo se evita que el test dependa de si ese dia
    cae en domingo o el horario del demo cambia.
    """
    import datetime

    from backend import agenda, booking, timeutils

    empleado = agenda._get_employee_row(EMPLEADA, cliente_id="demo")
    for salto in range(desde_dias, desde_dias + 10):
        dia = (timeutils._utc_now().date() + datetime.timedelta(days=salto)).isoformat()
        try:
            fila = _correr(booking._create_booking_core(
                "demo", employee_row=empleado, nombre="Ana", telefono="34600111222",
                email="", servicio="Pack con esperas", booking_date=dia,
                booking_time="10:00", notas="", source="qa", send_confirmation=False))
            return fila, dia
        except Exception:  # noqa: BLE001 - ese dia no vale, se prueba el siguiente
            continue
    raise AssertionError("no se pudo coger el pack ningun dia")


def test_el_panel_recibe_los_ratos_libres_del_pack(pack_con_esperas, api_module):  # noqa: F811
    """Esto es lo que se rompio: llegaba None y el pack se pintaba macizo."""
    from backend import booking, db

    fila, _dia = _coger_el_pack()
    with db._get_db_connection() as conexion:
        row = conexion.execute("SELECT * FROM bookings WHERE id=?", (fila["id"],)).fetchone()

    resumen = booking._portal_booking_summary_from_row(row)
    tramos = resumen.work_intervals

    assert tramos, "el panel no recibe los tramos: pintara el pack macizo"
    assert len(tramos) == 3, "un pack de tres tramos de trabajo, no %d" % len(tramos)
    inicio = 10 * 60
    assert tramos[0] == [inicio, inicio + 20]
    assert tramos[1] == [inicio + 65, inicio + 75]
    assert tramos[2] == [inicio + 90, inicio + 150]


def test_una_cita_normal_no_lleva_tramos(pack_con_esperas, api_module):  # noqa: F811
    """Sin esperas, el panel la pinta como siempre."""
    import datetime

    from backend import agenda, booking, db, timeutils  # noqa: F401

    empleado = agenda._get_employee_row(EMPLEADA, cliente_id="demo")
    fila = None
    for salto in range(3, 13):
        dia = (timeutils._utc_now().date() + datetime.timedelta(days=salto)).isoformat()
        try:
            fila = _correr(booking._create_booking_core(
                "demo", employee_row=empleado, nombre="Ana", telefono="34600111222",
                email="", servicio="", booking_date=dia, booking_time="11:00",
                notas="", source="qa", send_confirmation=False))
            break
        except Exception:  # noqa: BLE001
            continue
    assert fila is not None, "no se pudo coger una cita normal"
    with db._get_db_connection() as conexion:
        row = conexion.execute("SELECT * FROM bookings WHERE id=?", (fila["id"],)).fetchone()
    assert not booking._portal_booking_summary_from_row(row).work_intervals


def test_en_la_espera_cabe_otra_clienta(pack_con_esperas, api_module):  # noqa: F811
    """Y la agenda lo respeta: es lo que hace util verlo en pantalla."""
    from backend import agenda

    _fila, dia = _coger_el_pack(desde_dias=5)
    empleado = agenda._get_employee_row(EMPLEADA, cliente_id="demo")

    async def libre(hora):
        return await agenda._booking_slot_available(
            "demo", dia, hora, employee_id=empleado["id"], duration_minutes=30)

    # 10:00-10:20 trabaja; 10:20-11:05 la clienta espera -> ahi cabe un corte.
    assert _correr(libre("10:00")) is False
    assert _correr(libre("10:30")) is True
    # 11:05-11:15 vuelve a trabajar: un corte de 30 min ya no cabe.
    assert _correr(libre("11:00")) is False
