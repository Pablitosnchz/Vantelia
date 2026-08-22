# -*- coding: utf-8 -*-
"""Un ajuste nuevo de agenda no puede desaparecer al guardar.

`_serialize_client_config` y `_normalize_client_config` enumeran las claves de la
seccion `booking` una a una, asi que cualquier ajuste nuevo se descarta EN
SILENCIO: ni error, ni aviso, simplemente no esta.

Paso de verdad (22-ago-2026): se activo el modo de reserva conversacional en
produccion, el script dijo que lo habia guardado, y `booking.estilo` seguia sin
existir. Es el mismo fallo que ya obligo a crear `CONFIG_EXTRA_SECTIONS` para las
secciones de primer nivel, pero una capa mas adentro.

Si anades un ajuste a `booking`, anadelo a `clients.CONFIG_BOOKING_EXTRA_KEYS` o
este test te lo recordara.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("clave,valor", [
    ("estilo", "conversacional"),
    ("rescate_enabled", False),
    ("rescate_texto", "Llamanos al {telefono} y te cuadramos hueco."),
])
def test_sobrevive_al_guardar_y_volver_a_cargar(api_module, clave, valor):  # noqa: F811
    from backend import clients

    config = {
        "nombre": "Salon", "icono": "💇", "color": "#000", "bienvenida": "Hola",
        "allowed_origins": [], "booking": {"enabled": True, clave: valor},
    }
    guardado = clients._serialize_client_config(config)
    assert guardado["booking"].get(clave) == valor, (
        "%r se pierde al guardar el config" % clave
    )
    recargado = clients._normalize_client_config("demo", guardado)
    assert recargado["booking"].get(clave) == valor, (
        "%r se pierde al arrancar" % clave
    )


def test_el_modo_de_reserva_sobrevive_al_ciclo_completo(api_module):  # noqa: F811
    """El caso real: se activo en produccion y no quedaba rastro."""
    from backend import clients, whatsapp

    config = clients._normalize_client_config("demo", clients._serialize_client_config({
        "nombre": "Salon", "icono": "💇", "color": "#000", "bienvenida": "Hola",
        "allowed_origins": [], "booking": {"enabled": True, "estilo": "conversacional"},
    }))
    assert whatsapp._wa_modo_conversacional(config) is True
