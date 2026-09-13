# -*- coding: utf-8 -*-
"""«Cliente» no es el nombre de nadie: ni se guarda, ni tapa el nombre que ella dice.

POR QUE EXISTE
--------------
13-sep-2026, escenario «hora bloqueada con el resumen delante» medido con modelo real
sobre copia de producción. Turnos leídos en agent_turns:

    ella «el 15/09/2026 a las 17:00»
         crear_cita(servicio=Corte señora, 15-sep, 17:00, nombre="Cliente")
         -> {"ok": false, "error": "Falta el apellido", "conserva_los_datos": true}
    IA   «necesito que me digas tu apellido»
    IA   📋 Resumen de tu cita · 👤 Cliente · Corte señora · 17:00
    ella «me llamo Ana Ruiz Perez»
    IA   📋 Resumen de tu cita · 👤 Cliente · ...

El freno de apellidos se comprobaba antes que el de nombres de relleno, y al conservar
los datos de la llamada rechazada el estado se quedó con «Cliente». Con el nombre ya
puesto, «me llamo Ana Ruiz Perez» no lo sustituía. Si ella confirmaba, la cita entraba
en la agenda del salón a nombre de «Cliente». El mismo fallo que la referencia de
producción («👤 clienta»).
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

LLAMADA = {"servicio": "Corte señora", "fecha": "2030-01-08", "hora": "17:00", "nombre": "Cliente"}


def test_una_llamada_rechazada_no_deja_un_nombre_de_relleno(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado(intencion="reservar", servicio="Corte señora")
    reserva.anotar_resultado(estado, "crear_cita", dict(LLAMADA),
                             {"ok": False, "error": "Falta el apellido", "conserva_los_datos": True})

    assert estado.nombre == "", "el resumen saldria a nombre de %r" % estado.nombre
    assert (estado.fecha, estado.hora) == ("2030-01-08", "17:00"), "los datos buenos si se conservan"


def test_una_cita_pendiente_de_confirmar_no_guarda_un_nombre_de_relleno(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado(intencion="reservar")
    reserva.anotar_resultado(estado, "crear_cita", dict(LLAMADA, nombre="la clienta"),
                             {"ok": False, "pendiente_de_confirmacion": True})

    assert estado.nombre == ""
    assert estado.esperando_confirmacion is True


def test_me_llamo_sustituye_al_nombre_de_relleno(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado(intencion="reservar", servicio="Corte señora", fecha="2030-01-08",
                            hora="17:00", nombre="Cliente")
    reserva.anotar_lo_que_dice(estado, "me llamo Ana Ruiz Perez", "Europe/Madrid")

    assert estado.nombre == "Ana Ruiz Perez"


def test_me_llamo_no_pisa_un_nombre_de_verdad(api_module):  # noqa: F811
    """Control: no se toca el nombre bueno que ya había."""
    from backend import reserva

    estado = reserva.Estado(intencion="reservar", nombre="Ana Ruiz Perez")
    reserva.anotar_lo_que_dice(estado, "me llamo Ana", "Europe/Madrid")

    assert estado.nombre == "Ana Ruiz Perez"


@pytest.mark.parametrize("relleno", ["Cliente", "clienta", "sin nombre"])
def test_la_herramienta_pide_el_nombre_y_no_los_apellidos(api_module, relleno):  # noqa: F811
    from backend import agent

    resultado = asyncio.run(agent._ejecutar(
        "demo", "crear_cita", dict(LLAMADA, nombre=relleno), telefono="34600970099",
        remate_manual=True, quien={}, dicho="el 15/09/2026 a las 17:00"))

    assert resultado.get("ok") is False
    assert "nombre" in str(resultado.get("error") or "").lower(), resultado
    assert not resultado.get("conserva_los_datos"), (
        "conservar los datos de esta llamada guardaria %r como su nombre" % relleno)


def test_un_nombre_de_verdad_sigue_llegando_al_resumen(api_module):  # noqa: F811
    """Control: a quien da su nombre completo se le deja confirmar."""
    from backend import agent

    resultado = asyncio.run(agent._ejecutar(
        "demo", "crear_cita", dict(LLAMADA, nombre="Ana Ruiz Perez"), telefono="34600970099",
        remate_manual=True, quien={}, dicho="me llamo Ana Ruiz Perez"))

    assert resultado.get("pendiente_de_confirmacion") is True, resultado
