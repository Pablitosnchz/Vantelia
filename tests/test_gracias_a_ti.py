# -*- coding: utf-8 -*-
"""Cuando el cliente da las gracias, se le devuelven.

Petición de un salón: *"siempre que la clienta diga gracias, que la IA le diga
Gracias a ti"*. Con el modelo basta ponerlo en su cerebro, pero hay respuestas
que NO pasan por el modelo —las Q&A que el negocio escribe palabra por palabra y
las reglas por palabra clave— y ahí se perdía:

    > mil gracias, ¿y a qué hora abrís los sábados?
    < Nuestro horario es: • Lunes cerrado • Martes...

Correcto, pero seco. Ahora esas respuestas se sirven con el agradecimiento
delante.
"""
from __future__ import annotations

import pytest

from backend import chat

AGRADECEN = [
    "gracias",
    "muchas gracias",
    "mil gracias",
    "gracias por la info",
    "vale, gracias!",
    "mil gracias, ¿y a qué hora abrís los sábados?",
    "te lo agradezco",
    "graciasss",
]

NO_AGRADECEN = [
    "¿cuál es vuestro horario?",
    "quiero cita",
    "qué gracioso",           # contiene "gracios", no "gracias"
    "es una chica muy agraciada",
    "",
]


@pytest.mark.parametrize("mensaje", AGRADECEN)
def test_se_devuelve_el_agradecimiento(mensaje):
    salida = chat._con_gracias_a_ti(mensaje, "Nuestro horario es de 10 a 20.")
    assert salida.startswith("¡Gracias a ti!"), salida
    assert "Nuestro horario" in salida, "la respuesta original no se pierde"


@pytest.mark.parametrize("mensaje", NO_AGRADECEN)
def test_sin_gracias_la_respuesta_no_se_toca(mensaje):
    original = "Nuestro horario es de 10 a 20."
    assert chat._con_gracias_a_ti(mensaje, original) == original


def test_no_se_repite_si_la_respuesta_ya_lo_dice():
    """El negocio puede haber escrito su Q&A empezando por "Gracias a ti"."""
    ya = "Gracias a ti por escribirnos. Abrimos de 10 a 20."
    assert chat._con_gracias_a_ti("muchas gracias", ya) == ya


def test_el_agradecimiento_lleva_emoji():
    """El salón lo pidió expresamente: tono cercano y con emoticonos."""
    salida = chat._con_gracias_a_ti("gracias", "Abrimos de 10 a 20.")
    assert any(ord(c) > 0x2100 for c in salida), salida
