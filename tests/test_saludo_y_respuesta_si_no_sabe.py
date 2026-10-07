# -*- coding: utf-8 -*-
"""Dos cambios que pidio Cap Rocat el 7-oct-2026, genericos y opt-in por negocio:

1. **Sin bienvenida** (`chat_menu.saludo = false`): "cuando se envia el primer mensaje sale
   directamente este mensaje [la bienvenida]; ¿se puede quitar del todo?". Sin saludo, ni el
   codigo de la demo ni un "Hola" suelto sacan la bienvenida: lo contesta el asistente.
2. **Respuesta fija si no sabe** (`respuesta_si_no_sabe`): a "I want biggie" contesto "No
   tengo ese dato publicado... puede contactar llamando al..."; quieren "por favor marque la
   extension 100 y nuestro equipo le ayudara enseguida", en español a los +34 y en ingles al
   resto. El modelo marca que no sabe y el CODIGO pone el texto del negocio.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401

ES = "Por favor, marque la extensión 100 desde cualquier teléfono de Cap Rocat y nuestro equipo le ayudará enseguida."
EN = "Please dial extension 100 from any telephone at Cap Rocat and our team will assist you right away."


@pytest.fixture()
def motor(api_module, monkeypatch):
    """El motor documental de mentira: contesta lo que diga `motor.respuesta`."""
    from backend import rag

    estado = SimpleNamespace(respuesta="Buenos días, ¿en qué puedo ayudarle?", vistos=[])

    def chat(mensaje):
        estado.vistos.append(mensaje)
        return SimpleNamespace(response=estado.respuesta)

    monkeypatch.setattr(rag, "cargar_indice", lambda cliente_id: SimpleNamespace(
        as_chat_engine=lambda **kwargs: SimpleNamespace(chat=chat)))
    return estado


@pytest.fixture()
def fija(client, portal_cookies):  # noqa: F811
    res = client.put("/auth/app/respuesta-si-no-sabe", cookies=portal_cookies,
                     json={"es": ES, "en": EN, "idioma_por_prefijo": True})
    assert res.status_code == 200, res.text
    assert res.json()["activa"] is True
    yield
    assert client.put("/auth/app/respuesta-si-no-sabe", cookies=portal_cookies, json={}).status_code == 200


def _saludo(client, portal_cookies, saludo):  # noqa: F811
    res = client.put("/auth/app/chat-menu", cookies=portal_cookies, json={"enabled": False, "saludo": saludo})
    assert res.status_code == 200, res.text
    return res.json()


def _chat(client, mensaje):  # noqa: F811
    res = client.post("/chat", headers={"Origin": "http://testserver"},
                      json={"cliente_id": "demo", "mensaje": mensaje, "session_id": ""})
    assert res.status_code == 200, res.text
    return res.json()


# --- La respuesta fija si no sabe ------------------------------------------------------------------

def test_el_prompt_solo_cambia_con_la_respuesta_fija(api_module, client, portal_cookies):  # noqa: F811
    from backend import clients, rag

    sin = rag._build_system_prompt("demo", clients._get_client_config("demo"))
    assert "No tengo ese dato publicado todavia" in sin and rag.SIN_DATO not in sin
    client.put("/auth/app/respuesta-si-no-sabe", cookies=portal_cookies, json={"es": ES, "en": EN})
    try:
        con = rag._build_system_prompt("demo", clients._get_client_config("demo"))
        assert rag.SIN_DATO in con and "REGLA FINAL" in con and "No tengo ese dato publicado todavia" not in con
    finally:
        client.put("/auth/app/respuesta-si-no-sabe", cookies=portal_cookies, json={})


def test_si_no_sabe_sale_la_frase_del_negocio(client, motor, fija):  # noqa: F811
    motor.respuesta = "[[SIN_DATO]]"
    assert _chat(client, "¿Tenéis parking para bicicletas?")["respuesta"] == ES


def test_en_la_web_el_idioma_sale_del_mensaje(client, motor, fija):  # noqa: F811
    motor.respuesta = "[[SIN_DATO]]"
    assert _chat(client, "Do you have a bicycle parking? I would like to know")["respuesta"] == EN


def test_aunque_el_modelo_se_salte_la_marca(client, motor, fija):  # noqa: F811
    motor.respuesta = ("No tengo ese dato publicado todavía, pero puedo derivarle al equipo humano para que se lo "
                       "confirme. Puede contactar llamando al (+34) 971 74 78 78.")
    assert _chat(client, "I want biggie")["respuesta"] == EN


def test_lo_que_si_sabe_no_se_toca(client, motor, fija):  # noqa: F811
    motor.respuesta = "El desayuno se sirve de 8:00 a 11:00 en la terraza."
    assert _chat(client, "¿A qué hora es el desayuno?")["respuesta"] == motor.respuesta


def test_sin_respuesta_fija_la_marca_nunca_llega_a_nadie(client, motor):  # noqa: F811
    motor.respuesta = "Un momento. [[SIN_DATO]]"
    assert "SIN_DATO" not in _chat(client, "¿Tenéis parking?")["respuesta"]


def test_por_whatsapp_el_idioma_lo_decide_el_prefijo(api_module, client, portal_cookies):  # noqa: F811
    from backend import chat

    client.put("/auth/app/respuesta-si-no-sabe", cookies=portal_cookies,
               json={"es": ES, "en": EN, "idioma_por_prefijo": True})
    try:
        # Un +34 que escribe en ingles recibe el español (asi lo pidio el hotel); el resto, ingles.
        assert chat._si_no_sabe("demo", "[[SIN_DATO]]", "I want biggie", "34600111222") == ES
        assert chat._si_no_sabe("demo", "[[SIN_DATO]]", "Quiero un buggy", "447700900123") == EN
        assert chat._si_no_sabe("demo", "[[SIN_DATO]]", "Quiero un buggy", "+49 151 2345678") == EN
    finally:
        client.put("/auth/app/respuesta-si-no-sabe", cookies=portal_cookies, json={})


# --- Sin bienvenida ---------------------------------------------------------------------------------

def test_sin_saludo_un_hola_lo_contesta_el_asistente(client, portal_cookies, motor):  # noqa: F811
    try:
        assert _saludo(client, portal_cookies, False)["saludo"] is False
        respuesta = _chat(client, "Hola")
        assert respuesta["intent"] not in ("greeting", "menu")
        assert respuesta["respuesta"] == motor.respuesta
    finally:
        _saludo(client, portal_cookies, True)
    assert _chat(client, "Hola")["intent"] == "greeting", "con el saludo encendido, la bienvenida de siempre"


def test_cambiar_el_menu_no_borra_las_opciones_ocultas_ni_el_saludo(client, portal_cookies):  # noqa: F811
    try:
        res = client.put("/auth/app/chat-menu", cookies=portal_cookies,
                         json={"enabled": True, "ocultas": ["Preguntas frecuentes"], "saludo": False})
        assert res.json()["ocultas"] == ["Preguntas frecuentes"]
        res = client.put("/auth/app/chat-menu", cookies=portal_cookies, json={"enabled": False})
        assert res.json()["ocultas"] == ["Preguntas frecuentes"] and res.json()["saludo"] is False
    finally:
        client.put("/auth/app/chat-menu", cookies=portal_cookies, json={"enabled": True, "ocultas": [], "saludo": True})


def test_por_whatsapp_sin_saludo_un_hola_no_saca_la_bienvenida(api_module, client, portal_cookies,  # noqa: F811
                                                              motor, monkeypatch):
    from backend import clients, inbox, messaging, whatsapp

    enviados = []

    async def enviar(**kwargs):
        enviados.append(kwargs.get("text") or kwargs.get("body") or "")
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviar)
    monkeypatch.setattr(messaging, "_send_whatsapp_list", enviar)
    monkeypatch.setattr(inbox, "bot_is_muted", lambda *a: False)
    bienvenida = str(clients._get_client_config("demo").get("bienvenida") or "").strip()
    try:
        _saludo(client, portal_cookies, False)
        asyncio.run(whatsapp._handle_whatsapp_message(cliente_id="demo", phone_number_id="WA_NUM_ID",
                                                      from_number="34600111222", incoming_text="Hola",
                                                      interactive_id="", request=None))
        assert enviados and bienvenida not in enviados
    finally:
        _saludo(client, portal_cookies, True)
