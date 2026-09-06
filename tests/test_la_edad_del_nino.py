# -*- coding: utf-8 -*-
"""Con la edad dicha, el corte de nino no necesita mas preguntas.

POR QUE EXISTE
--------------
Medido el 6-sep-2026. La madre escribe "cortarle el pelo a mi hijo de 7 anos" y
despues "seria el corte de nino de 0 a 7", y el catalogo recibia esto:

    datos = {"familia": "corte", "para_quien": "nino"}   <- sin edad

Sin edad no podia elegir entre "Corte nino de 0 a 7" y "Corte de nino de 8 a 12",
asi que decia que faltaba la TECNICA, y el asistente acababa preguntando "como
tiene el pelo de largo" para un corte de nino. Doce turnos y se fue sin cita.

La edad la dice ella; que el modelo se la deje no puede costar la cita. Se saca
del texto, que es dato suyo y no interpretacion. La duenya lo confirmo: "elegir el
tramo deberia bastar".
"""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("dicho,edad", [
    ("cortarle el pelo a mi hijo de 7 anos", 7),
    ("mi hija tiene 10 años", 10),
    ("seria el corte de nino de 0 a 7", 7),
    ("el de 8 a 12", 12),
    ("quiero un corte de pelo", None),
    ("", None),
])
def test_la_edad_sale_de_lo_que_dice_ella(dicho, edad):
    from backend import catalog_pick

    assert catalog_pick._edad_en_lo_que_dijo(dicho) == edad


def test_el_tramo_del_catalogo_incluye_esa_edad():
    from backend import catalog_pick

    assert catalog_pick._tramo_incluye("Corte nino de 0 a 7", 7)
    assert not catalog_pick._tramo_incluye("Corte nino de 0 a 7", 9)
    assert catalog_pick._tramo_incluye("Corte de nino de 8 a 12", 9)


def test_no_se_inventa_una_edad_donde_no_la_hay():
    """Un precio o una hora no son una edad."""
    from backend import catalog_pick

    assert catalog_pick._edad_en_lo_que_dijo("me viene bien a las 11") is None
    assert catalog_pick._edad_en_lo_que_dijo("cuesta 45 euros") is None
