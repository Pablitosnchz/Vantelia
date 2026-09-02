# -*- coding: utf-8 -*-
"""Un precio que el negocio no da no sale por el chat web tampoco.

POR QUE EXISTE
--------------
El agente ya frena los precios prohibidos en su bucle, pero la respuesta
documental del chat web NO pasaba por ahi. Medido en produccion el 2-sep-2026,
con el salon piloto -que tiene los precios ocultos-:

    CLIENTA  precio del secado al aire corto
    IA       El precio del secado al aire corto es de 10 EUR

Ese servicio cuesta 4. No era una fuga del catalogo -el modelo no ve los precios
de ese negocio-: copiaba la DURACION, "10 min", y la daba como precio. Lo hizo
con tres servicios seguidos, siempre por encima del doble.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.fixture
def salon_sin_precios(api_module):
    from backend import appstate, clients

    config = clients._get_client_config("demo")
    previo = dict(config.get("booking") or {})
    config["booking"] = dict(previo, mostrar_precios=False)
    yield
    config["booking"] = previo
    _ = appstate


def test_no_sale_una_cifra_que_el_negocio_no_publica(api_module, salon_sin_precios):
    from backend import chat

    limpio = chat._sin_precios_que_no_se_dan(
        "demo", "El precio del secado al aire corto es de 10 €",
        "precio del secado al aire corto",
    )

    assert "10" not in limpio
    assert "€" not in limpio
    assert limpio, "hay que decirle algo, no dejarla sin respuesta"


def test_una_respuesta_sin_dinero_no_se_toca(api_module, salon_sin_precios):
    from backend import chat

    original = "El secado al aire corto dura 10 minutos. ¿Te busco hueco?"

    assert chat._sin_precios_que_no_se_dan("demo", original, "cuanto dura?") == original


def test_donde_si_se_dan_precios_no_estorba(api_module):
    """El negocio que publica sus precios los sigue diciendo."""
    from backend import chat

    original = "El corte son 20 €."

    assert chat._sin_precios_que_no_se_dan("demo", original, "cuanto vale el corte?") == original
