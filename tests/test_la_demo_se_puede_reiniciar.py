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
    assert "_wa_reiniciar_la_demo(" in fuente, (
        "sin reiniciar, la demo saluda y no vuelve a contestar nunca"
    )


def test_solo_dentro_del_hub_de_demos(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_webhook)
    i = fuente.index("_wa_reiniciar_la_demo(")
    antes = fuente[:i]

    assert "if demo_hub:" in antes, "fuera del hub esto no puede ejecutarse"
    assert antes.rindex('routing["just_bound"]') > antes.rindex("if demo_hub:"), (
        "tiene que colgar de que ACABE de escribir el codigo, no de cualquier "
        "mensaje: si no, el cliente de un negocio real podria soltar el traspaso "
        "escribiendo lo que fuera"
    )


def test_reinicia_TODO_el_contexto(api_module):
    """Reportado el 3-sep: la primera respuesta de una demo NUEVA salia asi:

        ELLA  quiero hacerme las mechas y tengo el cabello largo
        IA    Ya se que te lo he dicho, carino, y te entiendo...

    "Ya se que te lo he dicho" en el PRIMER mensaje. Venia del historial de la
    demo anterior, igual que el contador de "ya pregunto el precio", que hacia
    saltar frenos que no tocaban. Soltar el traspaso no basta: hay que empezar
    de cero de verdad.
    """
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_reiniciar_la_demo)

    assert "inbox.release(" in fuente, "sin esto la demo saluda y no vuelve a hablar"
    assert "_wa_clear_flow(" in fuente, "arrancaria a mitad del formulario anterior"
    assert "reserva.olvidar(" in fuente, (
        "sin esto se arrastra `veces_sin_precio` y saltan frenos que no tocan"
    )
    assert "DELETE FROM chat_messages" in fuente, (
        "sin esto sigue diciendo 'ya se que te lo he dicho' en el primer mensaje"
    )
