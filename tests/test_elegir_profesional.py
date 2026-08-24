# -*- coding: utf-8 -*-
"""Elegir con quien te atienden, y saber si con esa persona cuesta mas.

Todas las citas salian con "Asignacion automatica" y nadie podia pedir a alguien
en concreto. Y en este salon elegir a la duenya cuesta un 25% mas: eso hay que
decirlo ANTES de coger la cita, no en el mostrador.

El recargo NO se cobra automaticamente: se AVISA. Tocar el importe descuadraria
las senyales ya pagadas y la politica de pago del servicio; lo que se cobre de mas
se ajusta en el salon.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def equipo(api_module, client):  # noqa: F811
    """Dos profesionales: una con recargo y otra sin el."""
    from backend import agenda, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
            " duration_minutes, price_cents, description, is_active, sort_order,"
            " created_at, updated_at) VALUES ('demo', ?, 'Corte señora', '', 20, 2000,"
            " '', 1, 0, ?, ?)",
            (agenda._normalize_service_id("Corte señora"), ahora, ahora),
        )
        for eid, nombre, pct in (("emp_duenya", "Alicia Rincon", 25), ("emp_otra", "Conchi", 0)):
            conexion.execute(
                "INSERT OR REPLACE INTO employees (id, cliente_id, name, is_active,"
                " is_default, price_surcharge_pct, service_ids_json, created_at, updated_at)"
                " VALUES (?, 'demo', ?, 1, 0, ?, '[]', ?, ?)",
                (eid, nombre, pct, ahora, ahora),
            )
        conexion.commit()
    yield
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM employees WHERE id IN ('emp_duenya','emp_otra')")
        conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND name='Corte señora'")
        conexion.commit()


def test_avisa_de_lo_que_cuesta_con_ella(equipo, api_module):  # noqa: F811
    """Con la duenya son 25 € en vez de 20, y hay que decirlo antes."""
    from backend import agent

    r = agent._tool_consultar_profesionales("demo", {"servicio": "Corte señora"})
    assert r["ok"] and r["hay_recargo"]
    ella = next(p for p in r["profesionales"] if p["nombre"] == "Alicia Rincon")
    assert ella["recargo_pct"] == 25
    assert "25" in ella["precio_con_ella"]
    assert "antes de coger la cita" in r["nota"]

    otra = next(p for p in r["profesionales"] if p["nombre"] == "Conchi")
    assert otra["recargo_pct"] == 0
    assert "precio_con_ella" not in otra


def test_el_recargo_no_cambia_lo_que_se_cobra(equipo, api_module):  # noqa: F811
    """Se AVISA, no se cobra: tocar el importe descuadraria las senyales pagadas."""
    from backend import agenda

    servicio = agenda._find_service_by_name("demo", "Corte señora")
    assert agenda._service_price_cents_resolved("demo", servicio) == 2000


def test_sin_recargo_nadie_tiene_que_elegir(api_module, client):  # noqa: F811
    """Un negocio donde todas cobran igual no marea al cliente con la eleccion."""
    from backend import agent

    r = agent._tool_consultar_profesionales("demo", {})
    assert r["ok"] and not r["hay_recargo"]
    assert "no le hagas elegir" in r["nota"]


def test_se_reserva_con_la_que_pide(equipo, api_module):  # noqa: F811
    """Pedirla por su nombre tiene que llevar la cita a SU agenda."""
    from backend import voice

    assert voice._empleado_por_nombre("demo", "Alicia") == "emp_duenya"
    assert voice._empleado_por_nombre("demo", "conchi") == "emp_otra"
    # Alguien que no trabaja aqui no fuerza nada: la coge quien este libre.
    assert voice._empleado_por_nombre("demo", "Penelope") == ""
    assert voice._empleado_por_nombre("demo", "") == ""


def test_el_nombre_de_la_peluquera_no_es_el_de_la_clienta(equipo, api_module):  # noqa: F811
    """A "un corte de señora con Alicia" le cogia la cita a nombre de "Alicia"."""
    from backend import agent

    assert agent._es_una_profesional("demo", "Alicia")
    assert agent._es_una_profesional("demo", "Conchi")
    assert not agent._es_una_profesional("demo", "Marta Gil")
