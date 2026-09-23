# -*- coding: utf-8 -*-
"""El apellido se pide UNA vez: si la clienta no lo quiere dar, cita con su nombre.

POR QUE EXISTE
--------------
Simulacion de 40 clientas de Alicia (23-sep-2026): 4 de las 5 reservas perdidas eran
clientas nuevas que no querian dar su apellido. El asistente se lo pedia en bucle
("para poder reservar necesito tu apellido") hasta que se iban: "seguire buscando
otra peluqueria". Decision de Pablo ese dia: se pide una vez y, si no quiere, la
cita va con su nombre. El salon ya la identifica por el telefono de WhatsApp.
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.mark.parametrize("frase", [
    "no quiero dar el apellido, pero puedo darte mi nombre",
    "lo siento, pero no quiero dar mi apellido",
    "prefiero no dar mi apellido",
    "¿podemos confirmar la cita solo con mi nombre?",
    "No puedo dar mi apellido",
    "¿hay alguna manera de reservar sin el apellido?",
    "no quiero darte mis apellidos",
])
def test_se_reconoce_que_no_lo_quiere_dar(api_module, frase):  # noqa: F811
    from backend import textnorm

    assert textnorm.no_quiere_dar_el_apellido(frase), frase


@pytest.mark.parametrize("frase", [
    "me llamo Ana Ruiz", "mi apellido es Martínez", "solo quiero cortarme el pelo",
    "no quiero mechas, solo corte", "quiero la cita para mañana",
])
def test_lo_demas_no_es_negarse(api_module, frase):  # noqa: F811
    from backend import textnorm

    assert not textnorm.no_quiere_dar_el_apellido(frase), frase


def _crear(dicho):
    from backend import agent

    return asyncio.run(agent._ejecutar(
        "demo", "crear_cita",
        {"servicio": "Consulta", "fecha": "2030-01-15", "hora": "10:00", "nombre": "Laura"},
        telefono="34600888101", quien={"telefono": "34600888101", "nombre": ""},
        remate_manual=True, dicho=dicho,
    ))


@pytest.mark.parametrize("dos_apellidos", [False, True])
def test_el_agente_la_cita_con_su_nombre_si_no_lo_quiere_dar(api_module, monkeypatch, dos_apellidos):  # noqa: F811
    monkeypatch.setitem(api_module.CONFIG_CLIENTES["demo"]["booking"], "exigir_dos_apellidos", dos_apellidos)

    pedido = _crear("me llamo Laura")
    assert pedido["ok"] is False and "apellido" in pedido["error"].lower(), "la primera vez se pide"
    assert "no insistas" in pedido["que_hacer"].lower()

    resultado = _crear("me llamo Laura. no quiero dar mi apellido, solo quiero la cita")
    assert resultado.get("pendiente_de_confirmacion") is True, resultado


@pytest.mark.parametrize("dos_apellidos", [False, True])
def test_el_flujo_de_listas_sigue_con_su_nombre(api_module, monkeypatch, dos_apellidos):  # noqa: F811
    from backend import messaging, whatsapp

    monkeypatch.setitem(api_module.CONFIG_CLIENTES["demo"]["booking"], "exigir_dos_apellidos", dos_apellidos)
    enviados, resumenes = [], []

    async def texto(*, text, **kwargs):
        enviados.append(text)
        return True

    async def resumen(**kwargs):
        resumenes.append(kwargs["flow"].nombre)

    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(whatsapp, "_wa_send_booking_summary", resumen)
    telefono = "34600888110"
    whatsapp._wa_clear_flow("demo", telefono)
    whatsapp._wa_get_flow("demo", telefono).flow = "booking_name"

    def dice(frase):
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id="WA_NUM_ID", from_number=telefono,
            incoming_text=frase, interactive_id="", request=None,
        ))

    try:
        dice("Laura")
        assert resumenes == [] and "apellido" in enviados[-1].lower(), "la primera vez se pide"
        dice("no quiero dar mi apellido")
        assert resumenes == ["Laura"], (resumenes, enviados[-1:])
    finally:
        whatsapp._wa_clear_flow("demo", telefono)
