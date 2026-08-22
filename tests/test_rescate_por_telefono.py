# -*- coding: utf-8 -*-
"""Antes de perder una cita, ofrecer que llamen.

Peticion del salon (21-ago-2026), literal:

    "Cuando la IA detecte que una clienta tiene intencion real de coger cita pero
     finalmente no consigue reservar, quiero que antes de dar por terminada la
     conversacion le ofrezca la posibilidad de llamarnos por telefono. (...) En
     esos casos no quiero que la IA de la cita por perdida."

Y el limite, igual de importante: "no quiero que se ofrezca llamar por telefono
constantemente, sino unicamente cuando detecte que existe intencion de reservar
pero la conversacion puede terminar sin cita".
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def con_telefono(api_module, client):  # noqa: F811
    from backend import clients

    config = clients._get_client_config("demo")
    previo = dict(config.get("contacto") or {})
    config.setdefault("contacto", {})["telefono"] = "966 670 924"
    yield
    config["contacto"] = previo


def test_se_ofrece_el_telefono_del_negocio(con_telefono, api_module):  # noqa: F811
    from backend import rag

    linea = rag._call_us_line("demo")
    assert "966 670 924" in linea
    assert "llamarnos" in linea or "llamanos" in linea.lower()


def test_sin_telefono_no_se_inventa_nada(api_module, client):  # noqa: F811
    """Un negocio sin telefono publicado no puede recibir llamadas."""
    from backend import clients, rag

    config = clients._get_client_config("demo")
    previo = dict(config.get("contacto") or {})
    config.setdefault("contacto", {})["telefono"] = ""
    try:
        assert rag._call_us_line("demo") == ""
    finally:
        config["contacto"] = previo


def test_el_negocio_escribe_su_propio_texto(con_telefono, api_module):  # noqa: F811
    """El salon dio su redaccion; no se le impone la nuestra."""
    from backend import clients, rag

    config = clients._get_client_config("demo")
    config["booking"]["rescate_texto"] = (
        "Si ninguna de estas opciones te encaja, puedes llamarnos al {telefono} 😊."
    )
    try:
        linea = rag._call_us_line("demo")
        assert "Si ninguna de estas opciones te encaja" in linea
        assert "966 670 924" in linea, "el telefono se sustituye en la plantilla"
        assert "{telefono}" not in linea
    finally:
        config["booking"].pop("rescate_texto", None)


def test_se_puede_apagar(con_telefono, api_module):  # noqa: F811
    from backend import clients, rag

    config = clients._get_client_config("demo")
    config["booking"]["rescate_enabled"] = False
    try:
        assert rag._call_us_line("demo") == ""
    finally:
        config["booking"].pop("rescate_enabled", None)


def test_una_reprogramacion_fallida_no_se_cierra_en_seco(con_telefono, api_module):  # noqa: F811
    """Es una cita a punto de perderse: el negocio puede cuadrarla a mano."""
    import asyncio

    from backend import booking

    texto = asyncio.run(booking._reschedule_failure_text(
        "demo", {"error": "Ese hueco ya esta ocupado."}, "2026-09-10", "10:00",
    ))
    assert "966 670 924" in texto, "no se le ofrecio llamar: %r" % texto


def test_al_segundo_intento_fallido_se_le_ofrece_llamar(con_telefono, api_module):  # noqa: F811
    """"La conversacion se complica o la clienta no termina de aclararse"."""
    import asyncio

    from backend import messaging, whatsapp

    enviados = []

    async def _texto(*, text="", **kwargs):
        enviados.append(text)
        return True

    original = messaging._send_whatsapp_text
    messaging._send_whatsapp_text = _texto
    whatsapp._wa_clear_flow("demo", "34600999888")
    try:
        async def _fallar():
            await whatsapp._wa_atender_duda_sin_perder_el_paso(
                cliente_id="demo", phone_number_id="p", from_number="34600999888",
                incoming_text="xyz", request=None,
                aviso_error="No he reconocido la hora.",
                repetir_paso=lambda: None,
            )

        asyncio.run(_fallar())
        assert "966 670 924" not in enviados[-1], (
            "al primer intento seria pesado ofrecer el telefono"
        )
        asyncio.run(_fallar())
        assert "966 670 924" in enviados[-1], (
            "al segundo intento seguido hay que ofrecer llamar: %r" % enviados[-1]
        )
    finally:
        messaging._send_whatsapp_text = original
        whatsapp._wa_clear_flow("demo", "34600999888")
