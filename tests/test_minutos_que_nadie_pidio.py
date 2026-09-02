# -*- coding: utf-8 -*-
"""Los minutos se dicen si los preguntan, no al elegir servicio.

POR QUE EXISTE
--------------
Queja literal de la duenya del salon, viendo "el servicio es Mechas o balayage
largo y dura 440 minutos" cuando nadie lo habia preguntado: "no le he preguntado
nada de precio ni del tiempo que dura, todo eso no tiene que decirlo". Siete
horas sueltas de golpe asustan a cualquiera.

Habia una INSTRUCCION al modelo pidiendoselo, y una instruccion se desobedece:
el mismo dia se comprobo dos veces con los precios. Esto es el freno en codigo.

OJO al equilibrio: hay un caso CRITICO en el banco
(`cuanto-tarda-lo-que-ya-ha-elegido`) que exige decir los minutos cuando SI los
preguntan. La primera version de este freno lo rompio -miraba el historial de la
base de datos, donde el mensaje recien escrito todavia no esta- y el banco lo
pillo.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("frase", [
    "el servicio es Mechas o balayage largo y dura 440 minutos",
    "El corte de senora dura aproximadamente 20 minutos",
    "son unos 30 min",
    "el alisado tarda 2 horas",
])
def test_se_detecta_que_ha_soltado_una_duracion(api_module, frase):
    from backend import agent

    assert agent._dice_una_duracion(frase), frase


@pytest.mark.parametrize("frase", [
    "Perfecto, has elegido Mechas o balayage largo. Que dia te viene bien?",
    "Tengo hueco a las 10:00, 10:30 y 11:00",
    "Te espero el jueves 3 a las 10:00",
    "Tu cita queda para el 12 de septiembre",
])
def test_una_hora_no_es_una_duracion(api_module, frase):
    from backend import agent

    assert not agent._dice_una_duracion(frase), frase


def test_el_freno_mira_tambien_el_mensaje_de_ahora(api_module):
    """El mensaje recien escrito no esta aun en el historial de la base de datos.

    Sin esto, a "¿que suele tardar?" el freno tapaba justo la respuesta que ella
    acababa de pedir. Lo pillo el caso critico del banco.
    """
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_pregunta_cuanto_dura(dicho_de_ella)" in fuente, (
        "el freno tiene que mirar lo que acaba de escribir, no solo el historial"
    )
    assert "pidio_la_duracion_en_la_conversacion" in fuente, (
        "y tambien lo que pregunto turnos atras"
    )
