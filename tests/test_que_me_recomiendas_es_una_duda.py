# -*- coding: utf-8 -*-
"""«¿Qué me recomiendas?» es la misma duda que «¿cuál me recomiendas?».

POR QUE EXISTE
--------------
Banco del salón, caso `recomienda-ante-un-problema`, medido con modelo real sobre copia
de producción el 13-sep-2026 (413c170 y 0bca1eb, primer intento fallido en los dos):

    ella «se me esta cayendo mucho el pelo, que me recomiendas?»
    IA   «...podemos trabajar en tratamientos de color o alisados que pueden ayudar...»

El negocio tiene escrito qué contestar cuando alguien pide que se le recomiende sin
verle el pelo («sin ver tu cabello no te puedo decir...»), y el agente ya lo aplica
cuando detecta la duda. Pero la detección reconocía «cuál me recomiendas» y no «qué me
recomiendas», así que a esta clienta se le proponía un alisado para la caída del pelo.

No se inventa ninguna respuesta: se usa la que el negocio tiene escrita, y un negocio
que no tenga nada escrito sigue igual (recomendar es legítimo si no ha dicho lo contrario).
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("dicho", [
    "se me esta cayendo mucho el pelo, que me recomiendas?",   # el caso del banco
    "¿qué me recomiendas para las puntas abiertas?",
    "que me recomendais para el encrespamiento",
    "que me aconsejais?",
])
def test_que_me_recomiendas_es_una_duda(api_module, dicho):  # noqa: F811
    from backend import agent, catalog_pick

    assert agent._DUDA_AL_ELEGIR.search(catalog_pick._norm(dicho)), dicho


@pytest.mark.parametrize("dicho", [
    "quiero cita para keratina premium",
    "me llamo Ana",
    "el jueves por la manana",
    "vale, lo que me recomendaste el otro dia",   # ya lo eligio: no es pedir consejo
])
def test_lo_que_no_es_pedir_consejo_no_cambia(api_module, dicho):  # noqa: F811
    from backend import agent, catalog_pick

    assert not agent._DUDA_AL_ELEGIR.search(catalog_pick._norm(dicho)), dicho
