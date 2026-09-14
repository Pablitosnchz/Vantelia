# -*- coding: utf-8 -*-
"""`horario-escrito-manda` no puede aprobar o suspender según el día en que se mide.

POR QUE EXISTE
--------------
14-sep-2026 (lunes). El caso exigía la palabra «lunes». El domingo pasaba en todas las versiones
porque la respuesta decía «mañana, lunes»; el lunes suspendía en todas porque decía «hoy estamos
abiertos de 09:00 a 18:00… mañana, martes». Ninguna de las dos daba el horario de la semana, que
es lo que se pregunta: el caso medía el calendario, no al asistente.

El primer arreglo (ef0d0dc) pedía dos días de la semana distintos. Revisión de Astra: «todos los
días de 09:00 a 18:00» y «excepto los domingos» suspendían, y «hoy lunes… mañana martes» aprobaba.
Ahora los días pegados a hoy/mañana no cuentan, y valen la semana entera o la excepción.
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
    "Hoy lunes estamos abiertos de 09:00 a 18:00. Manana martes tambien",   # Astra
    "Hoy cerramos, pasado mañana miércoles abrimos a las 10.",
])
def test_hablar_de_hoy_y_manana_no_es_dar_el_horario(respuesta):
    from scripts.evaluar_asistente import _falta_en_respuestas

    assert _falta_en_respuestas(_caso(), [respuesta]), respuesta


@pytest.mark.parametrize("respuesta", [
    "Abrimos de lunes a viernes de 9:00 a 18:00 y los sábados de 10:00 a 14:00.",
    "Nuestro horario: martes a sábado, de 10 a 20 h.",
    "Abrimos todos los dias de 09:00 a 18:00",                  # Astra
    "Abrimos de 09:00 a 18:00 excepto los domingos",            # Astra
    "Hoy lunes cerramos; de martes a sábado, de 10:00 a 20:00.",
    "De lunes a viernes por la mañana, sábados de 10 a 14.",
])
def test_el_horario_de_la_semana_aprueba_sea_el_dia_que_sea(respuesta):
    from scripts.evaluar_asistente import _falta_en_respuestas

    assert _falta_en_respuestas(_caso(), [respuesta]) == "", respuesta
