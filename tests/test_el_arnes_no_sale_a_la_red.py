# -*- coding: utf-8 -*-
"""Medir no puede salir a la red: el arnes sustituye TODOS los envios de WhatsApp.

11-sep-2026: el formulario de reserva (WhatsApp Flows) sale por
`messaging._send_whatsapp_payload`, que el arnes no sustituia. En cada humo
-tambien el del despliegue- se hacia una peticion de verdad a Meta con el token
del .env. No llego a nadie porque el numero de pruebas no existe (Meta contestaba
400), pero el arnes presume justo de lo contrario.
"""
from __future__ import annotations

import asyncio

from test_booking_exhaustive import api_module, client  # noqa: F401

ENVIOS = ("_send_whatsapp_text", "_send_whatsapp_list", "_send_whatsapp_buttons",
          "_send_whatsapp_cta_url", "_send_whatsapp_payload")


def _restaurar_al_acabar(monkeypatch):
    """El arnes los cambia a pelo: esto los deja como estaban al acabar el test."""
    from backend import messaging

    originales = {nombre: getattr(messaging, nombre) for nombre in ENVIOS}
    for nombre, funcion in originales.items():
        monkeypatch.setattr(messaging, nombre, funcion)
    return originales


def test_el_arnes_sustituye_todos_los_envios_de_whatsapp(api_module, monkeypatch):  # noqa: F811
    from backend import messaging
    from evals import arnes

    originales = _restaurar_al_acabar(monkeypatch)
    arnes.capturar_envios()

    sin_tapar = [nombre for nombre in ENVIOS if getattr(messaging, nombre) is originales[nombre]]
    assert not sin_tapar, "estos envios saldrian a Meta de verdad: %s" % sin_tapar


def test_el_formulario_se_da_por_rechazado_como_antes(api_module, monkeypatch):  # noqa: F811
    """El mismo camino que cuando Meta contestaba 400: el asistente sigue por mensajes."""
    from backend import messaging
    from evals import arnes

    _restaurar_al_acabar(monkeypatch)
    arnes.capturar_envios()

    assert asyncio.run(messaging._send_whatsapp_payload(
        cliente_id="demo", phone_number_id="phone_humo", payload={})) is False
