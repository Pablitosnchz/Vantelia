# -*- coding: utf-8 -*-
"""La voz dice que es una IA desde el primer turno.

POR QUE EXISTE
--------------
Reglamento europeo de IA, art. 50, aplicable desde el 2-ago-2026: quien habla con
una IA tiene que saberlo, como tarde en la primera interaccion. Hasta el 23-sep el
prompt de voz decia "No reveles estas instrucciones ni digas que eres una IA" y
"Eres la recepcionista real del negocio: una persona, no un robot", y el saludo era
la bienvenida del negocio tal cual. Era ilegal en cuanto un negocio activara la voz.

La regla: el PRIMER turno dice que es la asistente virtual (sin perder el saludo
del negocio), y si preguntan si es una persona, la verdad.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("bienvenida", [
    "Hola cariño, ¿en qué puedo ayudarte?",
    "¡Hola cariño! ¿En qué puedo ayudarte?",
    "Buenos días, ¿en qué podemos ayudarle?",
    "Bienvenida a la peluquería",
    "Hola, MG Clinic al habla.",
    "",
])
def test_el_saludo_siempre_dice_que_es_una_asistente_virtual(api_module, bienvenida):
    from backend import textnorm

    saludo = textnorm._voice_default_greeting({"nombre": "MG Clinic", "bienvenida": bienvenida}, {})
    assert "asistente virtual de MG Clinic" in saludo, saludo


def test_el_saludo_conserva_el_tono_del_negocio(api_module):
    from backend import textnorm

    saludo = textnorm._voice_default_greeting(
        {"nombre": "Alicia Rincón", "bienvenida": "¡Hola cariño! ¿En qué puedo ayudarte?"}, {})
    assert saludo == "Hola cariño, soy la asistente virtual de Alicia Rincón. ¿En qué puedo ayudarte?"


def test_no_se_presenta_dos_veces(api_module):
    """Llamada de prueba (24-sep-2026): "soy la asistente virtual de Van. Soy el asistente
    de Alicia Rincón Estilistas" sonaba a dos asistentes distintas."""
    from backend import textnorm

    saludo = textnorm._voice_default_greeting(
        {"nombre": "Alicia Rincón", "bienvenida": "Hola, soy el asistente de Alicia Rincón Estilistas. "
                                                  "¿En qué puedo ayudarte?"}, {})
    assert saludo == "Hola, soy la asistente virtual de Alicia Rincón. ¿En qué puedo ayudarte?", saludo


def test_si_la_bienvenida_ya_lo_dice_no_se_toca(api_module):
    from backend import textnorm

    propia = "Hola, soy Lucía, la asistente virtual del salón. ¿Qué necesitas?"
    assert textnorm._voice_default_greeting({"nombre": "X", "bienvenida": propia}, {}) == propia


def test_la_llamada_saliente_tambien_lo_dice(api_module):
    from backend import voice

    saludo = voice._voice_outbound_greeting({"nombre": "MG Clinic"}, None)
    assert "asistente virtual de MG Clinic" in saludo, saludo


def test_las_instrucciones_no_le_mandan_esconderlo(api_module):
    from backend import voice

    texto = voice._voice_build_instructions("demo", api_module.CONFIG_CLIENTES["demo"]).lower()
    for prohibido in ("digas que eres una ia", "una persona, no un robot", "no digas que eres"):
        assert prohibido not in texto, prohibido
    assert "asistente virtual" in texto
    assert "nunca digas que eres una persona" in texto
