# -*- coding: utf-8 -*-
"""Decir "confirmo" no vuelve a disparar las reglas del negocio.

POR QUE EXISTE
--------------
El peor bucle de la simulacion del 2-sep-2026. La clienta ya tenia elegido el
dia y la hora y solo faltaba cerrar:

    ELLA  confirmo.
    IA    Laura, confirmame que todo esta correcto...
    IA    Te lo digo con sinceridad: el precio depende mucho de tu pelo...
    ELLA  confirmo.
    IA    [lo mismo, otra vez]
    IA    [la regla del precio, otra vez]

Siete veces. La decision del negocio se consulta en CADA mensaje, asi que la
regla "precio -> ofrecer diagnostico" se disparaba tambien cuando ella solo
estaba contestando que si, y la confirmacion no llegaba a procesarse nunca. La
cita no se cogio.

Ojo con la tentacion de arreglarlo saltandose la respuesta del negocio cuando ya
se ha dicho: eso se probo, se MIDIO y salio peor (las reservas cayeron del 61% al
41%). Lo que se frena aqui es solo el mensaje que no pregunta nada.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("frase", [
    "confirmo", "confirmo.", "Confirmo!", "si", "Si, por favor", "vale",
    "de acuerdo", "perfecto", "correcto", "todo correcto",
    "ya he dicho que confirmo",
])
def test_una_confirmacion_a_secas_no_es_consulta(api_module, frase):
    from backend import chat

    assert chat._es_solo_confirmacion(frase), frase


@pytest.mark.parametrize("frase", [
    "si, y cuanto cuesta?",
    "vale pero antes dime el precio",
    "quiero mechas",
    "confirmo la cita para el jueves a las 10",
    "perfecto, gracias",
])
def test_lo_que_trae_algo_mas_sigue_su_camino(api_module, frase):
    from backend import chat

    assert not chat._es_solo_confirmacion(frase), frase


def test_confirmar_no_devuelve_decision_del_negocio(api_module):
    """Es lo que hacia que se repitiera la regla del precio en cada turno."""
    from backend import chat

    assert chat.decision_del_negocio("demo", "confirmo") is None
