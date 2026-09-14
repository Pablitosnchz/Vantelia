# -*- coding: utf-8 -*-
"""Unas vacaciones puestas en Horario son un día CERRADO, no un día «completo».

POR QUE EXISTE
--------------
13-sep-2026, `scripts/medir_portal_y_reinicio.py` (vacaciones después de ofrecer el día): el
negocio bloquea el día entero desde Horario («Sin horas = día completo», 00:00-23:59) y el
asistente le cuenta a la clienta que ese día lo tiene completo. `voice._dia_cerrado` solo miraba
el horario semanal: ese día abría, así que `consultar_disponibilidad` lo trataba como día abierto
sin hueco («NO digas que estamos cerrados; dile que ese dia lo tienes completo») y el freno
`dijo_cerrado_estando_abierto` corregía a quien decía la verdad. Para la clienta no es lo mismo:
«completo» la deja buscando otra hora ese día; «cerrado por vacaciones» le dice que no la hay.

Un bloqueo que deja sin horario a todos los que trabajan ese día cierra el día. Uno parcial, o el
de un solo profesional mientras otro trabaja, no.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from test_booking_exhaustive import (  # noqa: F401
    _delete_employee, _make_employee, _next_weekday, _run_async, admin_cookies, api_module, client)


@pytest.fixture
def bloqueo(api_module):  # noqa: F811
    creados = []

    def poner(fecha, inicio, fin, motivo="Vacaciones", employee_id=""):
        block_id = "blk_vac_%s" % uuid.uuid4().hex
        with api_module._get_db_connection() as conn:
            conn.execute(
                "INSERT INTO agenda_blocks (id, cliente_id, employee_id, block_date, start_time,"
                " end_time, reason, created_at) VALUES (?, 'demo', ?, ?, ?, ?, ?, ?)",
                (block_id, employee_id, fecha, inicio, fin, motivo, api_module._utc_now_iso()),
            )
            conn.commit()
        creados.append(block_id)

    yield poner
    with api_module._get_db_connection() as conn:
        for block_id in creados:
            conn.execute("DELETE FROM agenda_blocks WHERE id = ?", (block_id,))
        conn.commit()


def test_vacaciones_de_dia_entero_cierran_el_dia(api_module, bloqueo):  # noqa: F811
    from backend import voice

    fecha = _next_weekday(4)
    assert voice._dia_cerrado("demo", fecha) is False
    bloqueo(fecha, "00:00", "23:59")
    assert voice._dia_cerrado("demo", fecha) is True


def test_la_herramienta_dice_cerrado_y_no_completo(api_module, bloqueo):  # noqa: F811
    fecha = _next_weekday(4)
    bloqueo(fecha, "00:00", "23:59")

    dia = _run_async(api_module._voice_check_availability("demo", fecha))
    assert dia["ok"] is True and dia["hay_huecos"] is False, dia
    assert dia["dia_cerrado"] is True
    assert "completo" not in dia["nota_del_dia"].lower()
    assert "cerrados" in dia["mensaje_voz"] and "Vacaciones" in dia["mensaje_voz"], dia["mensaje_voz"]

    a_una_hora = _run_async(api_module._voice_check_availability("demo", fecha, hora="10:00"))
    assert a_una_hora["dia_cerrado"] is True
    assert "cerrados" in a_una_hora["mensaje_voz"], a_una_hora["mensaje_voz"]
    assert "Vacaciones" in a_una_hora["mensaje_voz"]


def test_el_freno_no_corrige_a_quien_dice_que_cierran_por_vacaciones(api_module, bloqueo):  # noqa: F811
    from backend import agent

    fecha = _next_weekday(4)
    texto = "El %s estamos cerrados por vacaciones, ¿te miro otro día?" % fecha
    ahora = datetime.now()
    assert agent._el_cierre_que_dice_es_verdad("demo", texto, ahora) is False
    bloqueo(fecha, "00:00", "23:59")
    assert agent._el_cierre_que_dice_es_verdad("demo", texto, ahora) is True


def test_un_bloqueo_parcial_no_cierra_el_dia(api_module, bloqueo):  # noqa: F811
    from backend import voice

    fecha = _next_weekday(4)
    bloqueo(fecha, "09:00", "12:00", motivo="Medico")
    assert voice._dia_cerrado("demo", fecha) is False
    a_una_hora = _run_async(api_module._voice_check_availability("demo", fecha, hora="10:00"))
    assert a_una_hora["dia_cerrado"] is False
    assert a_una_hora["mensaje_voz"].lower().startswith("a esa hora la agenda esta bloqueada")


def test_las_vacaciones_de_una_profesional_no_cierran_el_salon(  # noqa: F811
        api_module, client, admin_cookies, bloqueo):
    from backend import voice

    fecha = _next_weekday(4)
    ana = _make_employee(client, admin_cookies)
    eva = _make_employee(client, admin_cookies)
    try:
        bloqueo(fecha, "00:00", "23:59", employee_id=ana)
        assert voice._dia_cerrado("demo", fecha) is False, "Eva trabaja ese dia"
        bloqueo(fecha, "00:00", "23:59", employee_id=eva)
        assert voice._dia_cerrado("demo", fecha) is True, "no queda nadie"
    finally:
        _delete_employee(client, admin_cookies, ana)
        _delete_employee(client, admin_cookies, eva)


def test_el_descanso_no_es_horario_de_trabajo(api_module, client, admin_cookies, bloqueo):  # noqa: F811
    """Revision de Astra sobre ef0d0dc: 09-18 con pausa de 13 a 14, bloqueos 09-13 y 14-18."""
    from backend import voice

    fecha = _next_weekday(4)
    ana = _make_employee(client, admin_cookies, break_windows=[{"start": "13:00", "end": "14:00"}])
    try:
        bloqueo(fecha, "09:00", "13:00", motivo="Vacaciones")
        assert voice._dia_cerrado("demo", fecha) is False, "de 14 a 18 trabaja"
        bloqueo(fecha, "14:00", "18:00", motivo="Vacaciones")
        assert voice._dia_cerrado("demo", fecha) is True, "solo le queda el descanso"
    finally:
        _delete_employee(client, admin_cookies, ana)
