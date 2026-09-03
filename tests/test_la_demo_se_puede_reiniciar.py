# -*- coding: utf-8 -*-
"""Mandar el codigo de demo otra vez empieza de cero.

POR QUE EXISTE
--------------
3-sep-2026, probando el envio de fotos por el hub de demos:

    DEMO YDCP9E
    Hola carino. En que puedo ayudarte?
    quiero unas mechas, te mando foto para que me aconsejes
    [foto]
    Gracias, ya nos ha llegado tu foto. La miramos y te contestamos
    personalmente en un momento.          <- pasa a una persona: el bot se calla
    gracias!                              (sin respuesta, CORRECTO)
    DEMO YDCP9E
    Hola carino. En que puedo ayudarte?   <- saluda...
    quiero hacerme las mechas             (sin respuesta)   <- ...y sigue mudo

Callarse tras recibir una foto esta BIEN: la conversacion es de una persona hasta
que el equipo la devuelva. Lo que no vale es que la demo salude y luego no
conteste: parece rota y no hay forma de seguir probando.

Mandar el codigo es "empieza de cero", asi que suelta el traspaso y limpia el
flujo. SOLO en el hub de demos y SOLO para el numero que acaba de escribir el
codigo: en un negocio de verdad el traspaso lo suelta su equipo desde el panel, y
que lo pudiera soltar el cliente escribiendo algo seria un fallo grave.
"""
from __future__ import annotations

import inspect

from test_booking_exhaustive import api_module  # noqa: F401


def test_el_codigo_suelta_el_traspaso(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_webhook)
    assert "inbox.release(" in fuente, (
        "sin soltarlo, la demo saluda y no vuelve a contestar nunca"
    )


def test_solo_dentro_del_hub_de_demos(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_webhook)
    i = fuente.index("inbox.release(")
    antes = fuente[:i]

    assert "if demo_hub:" in antes, "fuera del hub esto no puede ejecutarse"
    assert antes.rindex('routing["just_bound"]') > antes.rindex("if demo_hub:"), (
        "tiene que colgar de que ACABE de escribir el codigo, no de cualquier "
        "mensaje: si no, el cliente de un negocio real podria soltar el traspaso "
        "escribiendo lo que fuera"
    )


def test_tambien_limpia_el_flujo(api_module):
    """Si no, la demo nueva arranca a mitad del formulario de la anterior."""
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_webhook)
    i = fuente.index("inbox.release(")
    assert "_wa_clear_flow(" in fuente[max(0, i - 300):i]
