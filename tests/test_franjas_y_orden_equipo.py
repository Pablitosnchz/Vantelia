# -*- coding: utf-8 -*-
"""Tres cosas que pidió un salón real y que el sistema no cubría.

1. **Las tardes eran invisibles por WhatsApp.** Una lista admite 10 filas y se
   mandaban `sorted(available)[:10]`: con jornada de 10:00 a 20:30 eso llegaba a
   las 14:30. Quien pedía cita por WhatsApp no veía NINGÚN hueco de tarde. Ahora
   se pregunta la franja cuando no caben.

2. **Sin hueco, que llamen.** Un salón puede hacer sitio moviendo cosas que el
   sistema no sabe (juntar clientas, repartirse el trabajo). Antes se le decía
   "prueba otro día" y se acababa ahí.

3. **El orden del equipo lo decide el negocio.** Se listaban por orden
   alfabético; la dueña quiere el suyo (ella primero, luego por antigüedad).
"""
from __future__ import annotations

import pytest

from backend import rag, whatsapp
from test_booking_exhaustive import api_module, client  # noqa: F401


# ─── 1. Franjas ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("hora,esperada", [
    ("09:00", "manana"), ("10:30", "manana"), ("13:45", "manana"),
    ("14:00", "tarde"), ("16:30", "tarde"), ("17:59", "tarde"),
    ("18:00", "noche"), ("20:30", "noche"),
])
def test_cada_hora_cae_en_su_franja(hora, esperada):
    assert whatsapp._wa_franja_de(hora) == esperada


def test_una_hora_ilegible_no_rompe():
    """El valor puede venir de un id manipulado."""
    assert whatsapp._wa_franja_de("") == "manana"
    assert whatsapp._wa_franja_de("no-es-una-hora") == "manana"


# ─── 2. Ofrecer el teléfono ────────────────────────────────────────────────

def test_se_ofrece_llamar_cuando_el_negocio_tiene_telefono(monkeypatch):
    monkeypatch.setattr(
        rag.clients, "_get_client_config",
        lambda cid: {"contacto": {"telefono": "966 670 924"}},
    )
    linea = rag._call_us_line("demo")
    assert "966 670 924" in linea
    # La redaccion la puede cambiar el negocio (`booking.rescate_texto`); lo que
    # no puede faltar es la invitacion a llamar.
    assert "llam" in linea.lower()


def test_sin_telefono_no_se_inventa_nada(monkeypatch):
    monkeypatch.setattr(rag.clients, "_get_client_config", lambda cid: {"contacto": {}})
    assert rag._call_us_line("demo") == ""


def test_el_mensaje_de_dia_sin_huecos_incluye_el_telefono(monkeypatch):
    monkeypatch.setattr(
        rag.clients, "_get_client_config",
        lambda cid: {"contacto": {"telefono": "966 670 924"}},
    )
    monkeypatch.setattr(rag.agenda, "_agenda_block_reasons_for_day", lambda cid, fecha: [])
    texto = rag._day_unavailable_explanation("demo", "2026-09-01", "martes 1 de septiembre")
    assert "966 670 924" in texto


def test_un_fallo_leyendo_la_config_no_rompe_el_mensaje(monkeypatch):
    """El mensaje tiene que salir aunque la config falle: es lo único que recibe
    el cliente cuando no hay hueco."""
    def revienta(cid):
        raise RuntimeError("config caida")

    monkeypatch.setattr(rag.clients, "_get_client_config", revienta)
    assert rag._call_us_line("demo") == ""


# ─── 3. Orden del equipo ───────────────────────────────────────────────────

def test_el_orden_del_equipo_lo_fija_el_negocio(api_module):  # noqa: F811
    """El salon quiere a la duena primero y luego por antiguedad, no de la A a la Z."""
    from backend import agenda, db, timeutils

    equipo = [("Conchi", 3), ("Alicia", 1), ("Jose", 5), ("Lorena", 2), ("Lucia", 4)]
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM employees WHERE cliente_id = 'orden_test'")
        for nombre, orden in equipo:
            conexion.execute(
                "INSERT INTO employees (id, cliente_id, name, role_label, color, is_active,"
                " is_default, timezone, slot_minutes, day_start, day_end, break_start, break_end,"
                " break_windows_json, closed_weekdays_json, weekly_hours_json, service_ids_json,"
                " location_id, sort_order, created_at, updated_at)"
                " VALUES (?,?,?,'','#000',1,0,'Europe/Madrid',30,'09:00','20:00','','','[]','[]','{}','[]','',?,?,'')",
                ("emp_orden_%s" % nombre.lower(), "orden_test", nombre, orden,
                 timeutils._utc_now_iso()),
            )
        conexion.commit()

    nombres = [f["name"] for f in agenda._list_employee_rows("orden_test")]
    assert nombres == ["Alicia", "Lorena", "Conchi", "Lucia", "Jose"], nombres

    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM employees WHERE cliente_id = 'orden_test'")
        conexion.commit()


def test_sin_orden_fijado_se_mantiene_el_alfabetico(api_module):  # noqa: F811
    """Todos a 0 (el default) = el orden de siempre. Ningun negocio existente cambia."""
    from backend import agenda, db, timeutils

    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM employees WHERE cliente_id = 'orden_test2'")
        for nombre in ("Zoe", "Ana", "Marta"):
            conexion.execute(
                "INSERT INTO employees (id, cliente_id, name, role_label, color, is_active,"
                " is_default, timezone, slot_minutes, day_start, day_end, break_start, break_end,"
                " break_windows_json, closed_weekdays_json, weekly_hours_json, service_ids_json,"
                " location_id, sort_order, created_at, updated_at)"
                " VALUES (?,?,?,'','#000',1,0,'Europe/Madrid',30,'09:00','20:00','','','[]','[]','{}','[]','',0,?,'')",
                ("emp_o2_%s" % nombre.lower(), "orden_test2", nombre, timeutils._utc_now_iso()),
            )
        conexion.commit()

    nombres = [f["name"] for f in agenda._list_employee_rows("orden_test2")]
    assert nombres == ["Ana", "Marta", "Zoe"], nombres

    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM employees WHERE cliente_id = 'orden_test2'")
        conexion.commit()
