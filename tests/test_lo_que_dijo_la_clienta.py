# -*- coding: utf-8 -*-
"""Al agente le llega lo que dijo la clienta, no una frase inventada.

POR QUE EXISTE
--------------
Fallo real del salon piloto, y el que mas dano hizo a la confianza en el producto.
En modo conversacional, `_wa_start_booking_flow` llamaba al agente con el texto
FIJO "Quiero coger cita." y tiraba el mensaje de la clienta. Consecuencias, las dos
medidas en conversaciones de verdad:

- Ella escribia "No quiero cita para diagnostico, quiero cita para hacermelas" y el
  asistente seguia ofreciendole el diagnostico. No la ignoraba: nunca la habia
  oido. Lo repitio tres veces y acabo mandandola a llamar por telefono.
- Al agente le llegaba "Quiero coger cita." y trataba de resolverlo contra el
  catalogo: "no tengo un servicio especifico que se llame coger cita".

La intencion de reservar ya viaja aparte, en el parametro `intencion`, asi que no
hacia falta falsear el mensaje para transmitirla.
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


def _arrancar(monkeypatch, api_module, dicho):
    """Arranca el flujo conversacional y devuelve lo que recibio el agente."""
    from backend import appstate, whatsapp

    visto = {}

    async def _falso_agente(*, cliente_id, phone_number_id, from_number,
                            incoming_text, flow, config, request, intencion="", **kwargs):
        visto["incoming_text"] = incoming_text
        visto["intencion"] = intencion
        return True

    monkeypatch.setattr(whatsapp, "_wa_turno_del_agente", _falso_agente)
    monkeypatch.setattr(whatsapp, "_wa_modo_conversacional", lambda config: True)

    async def _sin_formulario(**kwargs):
        return False

    monkeypatch.setattr(whatsapp, "_wa_send_booking_form", _sin_formulario)
    # El tenant de pruebas no tiene catalogo y sin servicios no se llega al agente.
    monkeypatch.setattr(whatsapp, "_wa_servicios_sin_precio",
                        lambda cliente_id, servicios: [{"id": "corte", "nombre": "Corte"}])

    flow = appstate.WAFlowState(cliente_id="demo", from_number="34600000001")
    asyncio.run(whatsapp._wa_start_booking_flow(
        cliente_id="demo", phone_number_id="pn", from_number="34600000001",
        flow=flow, config={}, dicho=dicho,
    ))
    return visto


def test_llega_lo_que_dijo_no_una_frase_fija(api_module, monkeypatch):
    dicho = "No quiero cita para diagnostico, quiero cita para hacermelas"

    visto = _arrancar(monkeypatch, api_module, dicho)

    assert visto["incoming_text"] == dicho, (
        "si se pierde su frase, el asistente no puede saber que NO quiere diagnostico"
    )
    assert visto["intencion"] == "reservar", "la intencion viaja aparte, no en el texto"


def test_sin_frase_detras_se_mantiene_el_arranque_de_siempre(api_module, monkeypatch):
    """Cuando se pulsa un boton del menu no hay frase: ahi el texto fijo si vale."""
    visto = _arrancar(monkeypatch, api_module, "")

    assert visto["incoming_text"] == "Quiero coger cita."
