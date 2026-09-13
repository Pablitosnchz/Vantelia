# -*- coding: utf-8 -*-
"""Con `preferir_packs`, pedir unas mechas lleva al pack aunque el extractor apunte la talla en la técnica.

POR QUE EXISTE
--------------
13-sep-2026, humo `elegir-una-opcion-resuelve` medido con modelo real sobre copia de
producción, dos tiradas con el MISMO turno:

    ella «mechas» / «lo tengo medio»
         buscar_servicio("mechas lo tengo medio mechas medio")
    413c170 -> «Pack mechas o balayage medio» (360 min)
    0bca1eb -> «Mechas medio» (75 min)       <-- cinco horas de menos en la agenda

El salón piloto tiene `preferir_packs` («los técnicos se reservan como pack, no
sueltos»). La elección la hace el código, pero con lo que EXTRAE el modelo, y el
modelo varía: si apunta `tecnica: "mechas medio"` (la frase lo contiene tal cual), el
filtro «la técnica que ha nombrado manda» se quedaba solo con el servicio cuyo nombre
lleva esas dos palabras seguidas -el suelto- y el pack ya no llegaba a elegirse.

La talla no es parte de la técnica: se quita antes de filtrar.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_packs_y_recargo import salon_con_packs  # noqa: F401


@pytest.mark.parametrize("tecnica", [
    "mechas medio",   # lo que explica el humo de 0bca1eb
    "mechas",
    "",
])
def test_la_talla_en_la_tecnica_no_saca_al_pack(salon_con_packs, api_module, tecnica):  # noqa: F811
    from backend import catalog_pick

    datos = {"familia": "mechas", "tecnica": tecnica, "talla": "medio", "para_quien": "",
             "edad": None, "texto": "mechas lo tengo medio mechas medio"}

    assert catalog_pick.elegir("demo", datos).servicio == "Pack mechas o balayage medio", (
        "con preferir_packs se apartaria el suelto de 75 min en vez del pack")


def test_una_tecnica_de_verdad_sigue_mandando(salon_con_packs, api_module):  # noqa: F811
    """Control: quitar la talla no convierte cualquier técnica en «mechas»."""
    from backend import catalog_pick

    assert catalog_pick._tecnica_sin_talla("keratina premium medio largo") == "keratina premium"
    assert catalog_pick._tecnica_sin_talla("acido lactico bio premium") == "acido lactico bio premium"
    assert catalog_pick._tecnica_sin_talla("mechas medio") == "mechas"
