# -*- coding: utf-8 -*-
"""Pedir hablar con una persona funciona tambien a media reserva.

POR QUE EXISTE
--------------
3-sep-2026, midiendo el salon piloto:

    ELLA  quiero cita para un alisado
    ELLA  oye prefiero hablar con una persona
    IA    Entiendo, a veces es mas facil hablar con alguien en persona. PERO para
          poder ayudarte a reservar la cita, necesito saber un poco mas.

De entrada funcionaba ("ahora mismo aviso a una companera"). En cuanto habia una
reserva empezada, se ignoraba: el traspaso vivia DENTRO del bloque que solo corre
sin flujo activo (`if not flow.flow and not iid`).

Es la misma forma que el fallo de las digresiones: el guard se apagaba al entrar
en un flujo. Y contradecia el comentario que el propio codigo tiene al lado:
"quien pide una persona no quiere seguir hablando con la maquina".
"""
from __future__ import annotations

import inspect

from test_booking_exhaustive import api_module  # noqa: F401


def test_el_traspaso_va_antes_del_guard_de_flujo(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_message)

    traspaso = fuente.index("inbox.pide_una_persona(incoming_text)")
    guard = fuente.index('if not flow.flow and not iid:')
    assert traspaso < guard, (
        "si el traspaso queda dentro del bloque sin-flujo, a media reserva se "
        "ignora: es el fallo que este test viene a impedir"
    )


def test_el_traspaso_registra_la_conversacion(api_module):
    """Una rama que responde sola y no registra pierde el chat del panel."""
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_message)
    trozo = fuente[fuente.index("inbox.pide_una_persona(incoming_text)"):]
    trozo = trozo[:1200]

    assert "inbox.claim(" in trozo, "sin claim el asistente sigue hablando encima"
    assert "_wa_registrar(" in trozo, (
        "sin registrar, el negocio no ve ese chat en Conversaciones"
    )


def test_solo_cuando_el_negocio_lo_tiene_activado(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_message)
    trozo = fuente[fuente.index("inbox.pide_una_persona(incoming_text)"):][:400]

    assert "paso_a_persona_activo" in trozo, (
        "quien no lo tenga activado no puede empezar a prometer companeras"
    )
