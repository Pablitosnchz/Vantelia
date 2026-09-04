# -*- coding: utf-8 -*-
"""Dar las gracias cierra la conversacion; no se interpreta como una peticion.

POR QUE EXISTE
--------------
En la demo del salon (4-sep-2026) la clienta escribio "gracias" y recibio ESTO,
dos veces seguidas:

    ¡Gracias a ti! 😊
    Hola cariño, ¿qué tal? 😊 Veo que has mencionado "gracias", pero no tengo un
    servicio con ese nombre. ¿Podrías decirme un poco más sobre lo que te
    gustaría hacerte?

Dos capas contestaban al mismo mensaje: una anteponia el agradecimiento y el
agente, por debajo, tomaba "gracias" por el nombre de un servicio. El agradecer
esta bien; lo que sobra es todo lo que viene detras.

Se vigila en los DOS canales: el chat web y WhatsApp tienen recorridos distintos
y arreglarlo en uno no arregla el otro.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

TELEFONO = "34600777888"
NUMERO = "phone_demo"


# ─── 1. Que cuenta como "solo dar las gracias" ─────────────────────────────

@pytest.mark.parametrize("mensaje", [
    "gracias",
    "Gracias!",
    "muchas gracias",
    "mil gracias, un beso",
    "gracias por todo, hasta luego",
    "graciasss",
    "ok, perfecto, gracias 😊",
    "te lo agradezco",
])
def test_solo_da_las_gracias(mensaje):
    from backend import chat

    assert chat._es_solo_agradecimiento(mensaje), mensaje


@pytest.mark.parametrize("mensaje", [
    "gracias, ¿a que hora abris?",
    "gracias, quiero una cita",
    "gracias, al final no puedo ir",
    "gracias por el hueco pero prefiero el jueves",
    "hola",
    "quiero mechas",
])
def test_pide_algo_ademas_de_dar_las_gracias(mensaje):
    """Si trae contenido real, eso manda: el freno tiene que apartarse."""
    from backend import chat

    assert not chat._es_solo_agradecimiento(mensaje), mensaje


# ─── 2. El chat web ────────────────────────────────────────────────────────

def test_el_chat_contesta_las_gracias_y_no_sigue(client):  # noqa: F811
    from backend import chat

    respuesta = client.post(
        "/chat",
        json={"cliente_id": "demo", "mensaje": "gracias",
              "session_id": "s_gr_%s" % uuid.uuid4().hex[:8]},
        headers={"Origin": "http://testserver"},
    )
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["intent"] == "agradecimiento"
    assert datos["respuesta"] == chat.TEXTO_SOLO_GRACIAS
    assert "servicio" not in datos["respuesta"].lower()


# ─── 3. WhatsApp (recorrido propio) ────────────────────────────────────────

class _Capturas:
    def __init__(self):
        self.mensajes = []

    def instalar(self, monkeypatch):
        from backend import messaging

        async def texto(*, text="", **kwargs):
            self.mensajes.append(text)
            return True

        async def otro(*, body="", **kwargs):
            self.mensajes.append(body)
            return True

        for nombre, doble in (
            ("_send_whatsapp_text", texto), ("_send_whatsapp_list", otro),
            ("_send_whatsapp_buttons", otro), ("_send_whatsapp_cta_url", otro),
        ):
            monkeypatch.setattr(messaging, nombre, doble)


def test_whatsapp_contesta_las_gracias_sin_llegar_al_agente(
    api_module, client, monkeypatch  # noqa: F811
):
    from backend import agent, chat, whatsapp

    capturas = _Capturas()
    capturas.instalar(monkeypatch)

    llamadas = []

    async def agente_no_deberia(*args, **kwargs):
        llamadas.append(kwargs.get("mensaje") or args)
        return ("no deberia hablar", False)

    monkeypatch.setattr(agent, "responder", agente_no_deberia)
    whatsapp._wa_clear_flow("demo", TELEFONO)
    try:
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id=NUMERO, from_number=TELEFONO,
            incoming_text="gracias", interactive_id="", request=None,
        ))
        assert capturas.mensajes == [chat.TEXTO_SOLO_GRACIAS], capturas.mensajes
        assert not llamadas, "el agente no tiene que opinar sobre un 'gracias'"
    finally:
        whatsapp._wa_clear_flow("demo", TELEFONO)


def test_whatsapp_no_se_come_lo_que_viene_con_las_gracias(
    api_module, client, monkeypatch  # noqa: F811
):
    """"gracias, ¿a que hora abris?" tiene que seguir su camino."""
    from backend import chat, whatsapp

    capturas = _Capturas()
    capturas.instalar(monkeypatch)
    whatsapp._wa_clear_flow("demo", TELEFONO)
    try:
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id=NUMERO, from_number=TELEFONO,
            incoming_text="gracias, ¿a que hora abris?", interactive_id="", request=None,
        ))
        assert capturas.mensajes, "se quedo callado"
        assert capturas.mensajes != [chat.TEXTO_SOLO_GRACIAS]
    finally:
        whatsapp._wa_clear_flow("demo", TELEFONO)
