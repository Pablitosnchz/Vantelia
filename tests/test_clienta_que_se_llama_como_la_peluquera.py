# -*- coding: utf-8 -*-
"""Llamarse igual que una empleada no puede impedirte reservar.

POR QUE EXISTE
--------------
Medido el 2-sep-2026. Una clienta llamada Lucia -que es tambien el nombre de una
profesional del salon- no consiguio cita:

    IA    Solo necesito tu nombre para crear la cita
    ELLA  Lucia.
    IA    Parece que hay un problema con el nombre. Te recomiendo que llames al
          625 120 100...
    ELLA  No, gracias.
    IA    [lo mismo, otra vez]

El freno que evita coger la cita a nombre de la peluquera -nacio de "un corte de
senora CON Alicia", donde el modelo reservaba a nombre de Alicia- la tomaba por
la profesional. En un salon con varias estilistas eso deja fuera a las Laura, las
Ana y las Maria.

Lo que distingue los dos casos no es el nombre, es COMO se dijo.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("dicho", [
    "Lucia.", "lucia", "me llamo Lucia", "soy Lucia", "mi nombre es Lucia",
])
def test_si_lo_dice_como_su_nombre_es_su_nombre(api_module, dicho):
    from backend import agent

    assert agent._lo_dijo_como_su_nombre(dicho, "Lucia"), dicho


@pytest.mark.parametrize("dicho", [
    "quiero cita con Lucia",
    "que me atienda Lucia por favor",
    "para Lucia el jueves",
    "pregunto por Lucia",
])
def test_con_preposicion_delante_es_la_profesional(api_module, dicho):
    from backend import agent

    assert not agent._lo_dijo_como_su_nombre(dicho, "Lucia"), dicho


def test_el_freno_de_la_peluquera_mira_lo_que_dijo_ella(api_module):
    """Sin ese contexto vuelve a bloquear a las clientas que se llaman igual."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent._ejecutar)
    assert fuente.count("_lo_dijo_como_su_nombre(dicho") == 2, (
        "los DOS sitios que aplican el freno tienen que mirar como lo dijo ella"
    )
