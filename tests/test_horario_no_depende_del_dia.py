# -*- coding: utf-8 -*-
"""`horario-escrito-manda` no puede aprobar o suspender según el día en que se mide.

POR QUE EXISTE
--------------
14-sep-2026 (lunes). El caso exigía la palabra «lunes». El domingo pasaba en todas las versiones
porque la respuesta decía «mañana, lunes»; el lunes suspendía en todas porque decía «hoy estamos
abiertos de 09:00 a 18:00… mañana, martes». Ninguna de las dos daba el horario de la semana, que
es lo que se pregunta: el caso medía el calendario, no al asistente. Ahora exige nombrar al menos
dos días de la semana distintos, y eso no depende de qué día sea hoy.
"""
from __future__ import annotations

import pytest


def _caso():
    from evals.casos_asistente import CASOS

    return next(c for c in CASOS if c["id"] == "horario-escrito-manda")


@pytest.mark.parametrize("respuesta", [
    "Hoy lunes estamos abiertos de 09:00 a 18:00.",
    "Hoy estamos abiertos de 09:00 a 18:00. Mañana, martes 15, también.",
    "Mañana, lunes, abrimos a las 9.",
])
def test_hablar_de_hoy_y_manana_no_es_dar_el_horario(respuesta):
    from scripts.evaluar_asistente import _falta_en_respuestas

    assert _falta_en_respuestas(_caso(), [respuesta]), respuesta


@pytest.mark.parametrize("respuesta", [
    "Abrimos de lunes a viernes de 9:00 a 18:00 y los sábados de 10:00 a 14:00.",
    "Nuestro horario: martes a sábado, de 10 a 20 h.",
])
def test_el_horario_de_la_semana_aprueba_sea_el_dia_que_sea(respuesta):
    from scripts.evaluar_asistente import _falta_en_respuestas

    assert _falta_en_respuestas(_caso(), [respuesta]) == ""


def test_varios_cuenta_palabras_enteras_y_sin_tildes():
    from scripts.evaluar_asistente import _falta_en_respuestas

    caso = {"debe_varios": {"de": ["lunes", "sábado"], "minimo": 2}}
    assert _falta_en_respuestas(caso, ["lunes y sabado"]) == ""
    assert _falta_en_respuestas(caso, ["lunes", "lunes otra vez"])
    assert _falta_en_respuestas(caso, ["lunesdia sabadete"])
