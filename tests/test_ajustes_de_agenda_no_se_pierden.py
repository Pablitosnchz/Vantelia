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


def test_los_canales_de_aviso_sobreviven_al_arranque(api_module, client):  # noqa: F811
    """Por que canales sale cada aviso de cita es CONFIGURACION del negocio.

    Sin registrarla en la whitelist, lo que marcaba en su portal se perdia en el
    siguiente arranque y los avisos volvian a salir solo por email: a un salon que
    trabaja por WhatsApp eso le deja al cliente sin enterarse de que le han
    cancelado la cita.
    """
    from backend import clients, textnorm

    base = dict(clients._get_client_config("demo"))
    base["message_template_channels"] = {
        "cancelled": {"email": True, "whatsapp": True, "sms": False},
        "rescheduled": {"email": True, "whatsapp": True, "sms": False},
    }
    guardado = clients._serialize_client_config(base)
    assert "message_template_channels" in guardado, "se descarta al guardar"

    recargado = clients._normalize_client_config("demo", guardado)
    canales = textnorm._normalize_message_template_channels(
        recargado.get("message_template_channels")
    )
    assert canales["cancelled"]["whatsapp"] is True
    assert canales["rescheduled"]["whatsapp"] is True


def test_la_direccion_y_el_mapa_sobreviven_al_despliegue(api_module, client):  # noqa: F811
    """Sin la direccion, el asistente se inventa donde esta el salon.

    Paso: a "¿donde estais ubicados?" contesto "en el centro de la ciudad, en una
    zona muy accesible". Se le puso la direccion, y el siguiente despliegue se la
    comio: `contacto` tambien es una whitelist y solo guardaba email y telefono.
    """
    from backend import clients

    base = dict(clients._get_client_config("demo"))
    base["contacto"] = dict(base.get("contacto") or {},
                            direccion="Calle Mayor 1, Elche",
                            mapa="https://maps.example/ficha")
    guardado = clients._serialize_client_config(base)
    assert guardado["contacto"]["direccion"] == "Calle Mayor 1, Elche"
    assert guardado["contacto"]["mapa"] == "https://maps.example/ficha"

    recargado = clients._normalize_client_config("demo", guardado)
    assert recargado["contacto"]["direccion"] == "Calle Mayor 1, Elche"
    assert recargado["contacto"]["mapa"] == "https://maps.example/ficha"
