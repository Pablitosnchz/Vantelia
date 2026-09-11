# -*- coding: utf-8 -*-
"""Los botones de WhatsApp salen bien formados, o no se manda nada a medias.

POR QUE EXISTE
--------------
10-sep-2026. El salon probo la conversacion entera, le llego el resumen, pulso
"✅ Confirmar"... y no paso NADA: ni cita, ni mensaje, ni error visible. En los
logs del servidor:

    ERROR (400) (#131009) Parameter value is not valid
    details: "Duplicate button id"

El aviso de "ya tienes otra cita" pasaba sus botones como DICCIONARIOS a un
emisor que espera TUPLAS `(id, texto)`. Al iterar un diccionario salen sus
CLAVES, asi que los dos botones se quedaban con el id "id", Meta rechazaba el
mensaje entero y la rama hacia `return` sin crear la cita.

Solo le pasaba a quien YA tenia otra cita viva, que es justo quien mas usa el
asistente.

Se arregla en los DOS sitios: el que llamaba mal, y el emisor -por donde salen
todos los botones del producto-, para que la clase no pueda repetirse.
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

CID = "demo"


def _capturar(monkeypatch):
    """Se queda con el payload en vez de mandarlo a Meta."""
    from backend import messaging

    enviados = []

    async def _falso(*, cliente_id, phone_number_id, payload):
        enviados.append(payload)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_payload", _falso)
    return enviados


def test_las_tuplas_de_siempre_siguen_saliendo(api_module, monkeypatch):  # noqa: F811
    from backend import messaging

    enviados = _capturar(monkeypatch)
    asyncio.run(messaging._send_whatsapp_buttons(
        cliente_id=CID, phone_number_id="1", to_number="34600",
        body="¿Confirmamos?", buttons=[("confirm_yes", "Confirmar"), ("confirm_no", "Cancelar")]))
    ids = [b["reply"]["id"] for b in enviados[0]["interactive"]["action"]["buttons"]]
    assert ids == ["confirm_yes", "confirm_no"]


def test_los_diccionarios_tambien_valen(api_module, monkeypatch):  # noqa: F811
    """La forma que rompio la confirmacion: ahora se entiende en vez de reventar."""
    from backend import messaging

    enviados = _capturar(monkeypatch)
    asyncio.run(messaging._send_whatsapp_buttons(
        cliente_id=CID, phone_number_id="1", to_number="34600", body="¿Cual?",
        buttons=[{"id": "dup_mover", "title": "Cambiar la que tengo"},
                 {"id": "dup_crear", "title": "Quiero las dos"}]))
    botones = enviados[0]["interactive"]["action"]["buttons"]
    assert [b["reply"]["id"] for b in botones] == ["dup_mover", "dup_crear"]
    assert botones[0]["reply"]["title"] == "Cambiar la que tengo"


def test_un_id_repetido_no_tumba_el_mensaje(api_module, monkeypatch):  # noqa: F811
    """Meta rechaza el mensaje ENTERO por un id repetido: mejor mandar el bueno."""
    from backend import messaging

    enviados = _capturar(monkeypatch)
    asyncio.run(messaging._send_whatsapp_buttons(
        cliente_id=CID, phone_number_id="1", to_number="34600", body="hola",
        buttons=[("mismo", "Uno"), ("mismo", "Dos"), ("otro", "Tres")]))
    ids = [b["reply"]["id"] for b in enviados[0]["interactive"]["action"]["buttons"]]
    assert ids == ["mismo", "otro"]


def test_sin_botones_validos_no_se_manda(api_module, monkeypatch):  # noqa: F811
    from backend import messaging

    enviados = _capturar(monkeypatch)
    ok = asyncio.run(messaging._send_whatsapp_buttons(
        cliente_id=CID, phone_number_id="1", to_number="34600", body="hola",
        buttons=[("", "Sin id")]))
    assert ok is False
    assert enviados == []


def test_el_aviso_de_cita_duplicada_manda_tuplas(api_module):  # noqa: F811
    """El sitio exacto que fallo: si vuelve a pasar diccionarios, salta aqui."""
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_message)
    assert '("dup_mover", ' in fuente, "los botones del aviso de duplicada no son tuplas"
    assert '{"id": "dup_mover"' not in fuente, "vuelven a ir como diccionario"
    assert '{"id": "dup_crear"' not in fuente


def test_el_resumen_no_se_guarda_si_no_se_envia(api_module, monkeypatch):  # noqa: F811
    """El panel no puede ensenyar un mensaje que la clienta nunca recibio.

    Se prueba EJECUTANDO la funcion, no mirando el orden de las lineas. La
    version anterior de este test comprobaba que el `if not enviado:` iba antes
    de `_wa_registrar`, y habria seguido pasando aunque alguien quitara el
    `return`. Lo cazo la revision cruzada con GPT-6 Astra (11-sep-2026), y es
    justo la regla que el propio AGENTS.md pide vigilar.
    """
    from backend import appstate, messaging, whatsapp

    registrados = []
    monkeypatch.setattr(whatsapp, "_wa_registrar",
                        lambda **kw: registrados.append(kw) or "sesion")

    async def sin_freno(**kwargs):
        return False

    monkeypatch.setattr(whatsapp, "_wa_freno_del_precio", sin_freno)

    async def rechazado(**kwargs):
        return False

    async def aceptado(**kwargs):
        return True

    def _flow():
        flow = appstate.WAFlowState(cliente_id=CID, from_number="34600123456")
        flow.nombre, flow.servicio = "Pablo Sanchez Ruiz", "Corte"
        flow.fecha, flow.hora = "2026-09-01", "12:30"
        return flow

    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", rechazado)
    asyncio.run(whatsapp._wa_send_booking_summary(
        cliente_id=CID, phone_number_id="PN", to_number="34600123456", flow=_flow()))
    assert registrados == [], "se guardo en el historial un resumen que Meta rechazo"

    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", aceptado)
    asyncio.run(whatsapp._wa_send_booking_summary(
        cliente_id=CID, phone_number_id="PN", to_number="34600123456", flow=_flow()))
    assert len(registrados) == 1, "el resumen enviado no quedo en el historial"
    assert registrados[0].get("intent") == "resumen_para_confirmar"
