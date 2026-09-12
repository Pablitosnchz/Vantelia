# -*- coding: utf-8 -*-
"""En la agenda del salon hace falta el nombre completo.

POR QUE EXISTE
--------------
Peticion del salon (10-sep-2026): "en una cita, aunque sea de 15 minutos, tiene
que verse el nombre y 2 apellidos y el servicio obligatoriamente". El motivo es
practico: en la agenda tienen que distinguir a dos clientas que se llaman igual.

Hay DOS listones a proposito, y la diferencia importa:

  · MOSTRADOR (panel): nombre y DOS apellidos, obligatorio. Ahi escribe el
    equipo, que se los sabe.
  · WHATSAPP: si la clienta solo da su nombre de pila se le piden los apellidos
    UNA vez. Insistir por chat es donde se pierden reservas; lo que falte lo
    completa el equipo desde el panel.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.fixture(autouse=True)
def regla_del_salon(api_module, monkeypatch):
    monkeypatch.setitem(api_module.CONFIG_CLIENTES["demo"]["booking"], "exigir_dos_apellidos", True)


@pytest.mark.parametrize("nombre,dos,alguno", [
    ("Ana", False, False),
    ("Ana Ruiz", False, True),
    ("Ana Ruiz Perez", True, True),
    ("Ana de la Fuente Ruiz", True, True),
    ("   Ana   Ruiz  ", False, True),
    ("", False, False),
])
def test_el_liston_de_cada_canal(api_module, nombre, dos, alguno):  # noqa: F811
    from backend import textnorm

    assert textnorm.tiene_dos_apellidos(nombre) is dos, nombre
    assert textnorm.tiene_algun_apellido(nombre) is alguno, nombre


def test_el_panel_rechaza_media_ficha(api_module):  # noqa: F811
    """No basta con esconder el boton: quien decide es el backend."""
    import inspect

    from backend.routers import portal_app

    fuente = inspect.getsource(portal_app)
    assert fuente.count("tiene_dos_apellidos") >= 2, (
        "falta el liston en el alta de cita o en el alta de cliente"
    )


def test_whatsapp_pide_los_apellidos_a_la_clienta_nueva(api_module):  # noqa: F811
    """Por WhatsApp se piden hasta tenerlos (decision de Pablo, 11-sep-2026: dos
    apellidos a la clienta nueva, como en el mostrador). El comportamiento lo
    prueba `tests/test_dos_apellidos_por_whatsapp.py`; esto solo vigila que el
    paso siga llevando la cuenta de lo ya pedido."""
    import inspect

    from backend import appstate, whatsapp

    assert hasattr(appstate.WAFlowState(cliente_id="x", from_number="y"), "apellidos_pedidos")
    fuente = inspect.getsource(whatsapp._handle_whatsapp_message)
    assert "tiene_algun_apellido" in fuente
    assert "apellidos_pedidos" in fuente


def test_el_agente_no_coge_la_cita_sin_apellido(api_module):  # noqa: F811
    """Modo conversacional: lo impide la TOOL, no el prompt."""
    import asyncio

    from backend import agent

    salida = asyncio.run(agent._ejecutar(
        "demo", "crear_cita",
        {"servicio": "Corte", "fecha": "2026-09-15", "hora": "10:00", "nombre": "Ana"},
        telefono="34600111222", remate_manual=True,
    ))
    assert salida.get("ok") is False
    assert "apellido" in str(salida.get("error", "")).lower()
    assert salida.get("conserva_los_datos") is True


def test_con_apellido_sigue_su_curso(api_module):  # noqa: F811
    """El freno es para el nombre incompleto, no para todo el mundo: con nombre y
    dos apellidos (lo que se pide a una clienta nueva por WhatsApp) sigue."""
    import asyncio

    from backend import agent

    salida = asyncio.run(agent._ejecutar(
        "demo", "crear_cita",
        {"servicio": "Corte", "fecha": "2026-09-15", "hora": "10:00", "nombre": "Ana Ruiz Pérez"},
        telefono="34600111222", remate_manual=True,
    ))
    assert "apellido" not in str(salida.get("error", "")).lower()
