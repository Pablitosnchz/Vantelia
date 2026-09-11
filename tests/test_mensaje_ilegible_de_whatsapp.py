# -*- coding: utf-8 -*-
"""Lo que Meta entrega sin contenido legible no se le cuela al modelo como si lo
hubiera escrito la clienta.

POR QUE EXISTE
--------------
11-sep-2026, primer mensaje al numero de Vantelia recien pasado a Coexistence:

    CLIENTE  hola                      (a nosotros nos llega sin texto)
    IA       Parece que has enviado un mensaje que no puedo leer...
    CLIENTE  porque ni lo puedes leer?
    IA       No puedo leer mensajes que no esten en formato de texto...

Para lo que no era texto, al modelo se le pasaba una INSTRUCCION ("el usuario ha
enviado un mensaje que no es texto, responde...") por el mismo hueco que lo que
escribe la clienta. Quedaba en el historial como si ella lo hubiera dicho -tambien
en el panel del negocio-, y en el turno siguiente, con un mensaje de texto normal,
el modelo seguia con la misma cantinela. Con un flujo de cita a medias, esa
instruccion podia acabar tomada como la respuesta al paso en curso.

Estos tests ejecutan el webhook entero, firmado como lo firma Meta. En cada uno va
primero la comprobacion de COMPORTAMIENTO (lo que queda en el historial, lo que se
contesta), que es la que falla sin el arreglo.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

SECRETO = "secreto-de-prueba"


def _peticion(payload):
    from starlette.requests import Request

    cuerpo = json.dumps(payload).encode("utf-8")
    firma = "sha256=" + hmac.new(SECRETO.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()

    async def recibir():
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    scope = {
        "type": "http", "method": "POST", "path": "/whatsapp/webhook/demo",
        "query_string": b"", "client": ("testclient", 50000),
        "headers": [(b"x-hub-signature-256", firma.encode("ascii"))],
    }
    return Request(scope, recibir)


def _mensaje(telefono, tipo, **cuerpo):
    """El payload que manda Meta para un mensaje de este tipo."""
    mensaje = {"from": telefono, "id": "wamid.%s" % uuid.uuid4().hex, "type": tipo}
    mensaje.update(cuerpo)
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "WA_NUM_ID"},
        "messages": [mensaje],
    }}]}]}


def _recibir(payload):
    from backend import whatsapp

    return asyncio.run(whatsapp._handle_whatsapp_webhook(_peticion(payload), forced_cliente_id="demo"))


def _historial(session_id):
    from backend import db

    with db._get_db_connection() as connection:
        filas = connection.execute(
            "SELECT role, content, intent FROM chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [(f["role"], f["content"], f["intent"]) for f in filas]


def _sin_instrucciones(historial):
    """Nada de lo que el codigo le dice al modelo puede quedar como dicho por ella."""
    for rol, contenido, _ in historial:
        if rol == "user":
            assert "no es texto" not in contenido, historial
            assert "Pidele" not in contenido, historial


@pytest.fixture
def enviados(api_module, monkeypatch):  # noqa: F811
    """Lo que el asistente manda a la clienta (textos, y el resto como dict)."""
    from backend import messaging, settings

    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", SECRETO)
    salida = []

    async def _texto(*, text, **kwargs):
        salida.append(text)
        return True

    async def _otro(**kwargs):
        salida.append(kwargs)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", _texto)
    for nombre in ("_send_whatsapp_buttons", "_send_whatsapp_list",
                   "_send_whatsapp_cta_url", "_send_whatsapp_payload"):
        monkeypatch.setattr(messaging, nombre, _otro)
    return salida


def _sesion_limpia(telefono):
    from backend import inbox, whatsapp

    session_id = whatsapp._whatsapp_session_id("demo", telefono)
    inbox.release(session_id)
    return session_id


def test_lo_que_meta_no_entrega_se_pide_repetir(enviados):
    """El caso real: un `unsupported`. Se pide que lo repita, sin pasar por el modelo."""
    from backend import whatsapp

    telefono = "34600555001"
    session_id = _sesion_limpia(telefono)

    _recibir(_mensaje(telefono, "unsupported",
                      errors=[{"code": 131051, "title": "Message type unknown"}]))

    historial = _historial(session_id)
    _sin_instrucciones(historial)
    assert len(enviados) == 1 and "escrib" in str(enviados[0]).lower(), enviados
    entrante, respuesta = whatsapp.TEXTOS_ILEGIBLE["mensaje"]
    assert enviados == [respuesta]
    assert historial[0][:2] == ("user", entrante), historial


def test_si_meta_rechaza_la_respuesta_no_se_inventa_en_el_historial(enviados, monkeypatch):
    from backend import messaging, whatsapp

    async def rechazar(**kwargs):
        return False

    monkeypatch.setattr(messaging, "_send_whatsapp_text", rechazar)
    telefono = "34600555991"
    session_id = _sesion_limpia(telefono)
    _recibir(_mensaje(telefono, "unsupported"))
    historial = _historial(session_id)
    assert any(rol == "user" for rol, _, _ in historial)
    assert not any(rol == "assistant" for rol, _, _ in historial), historial


def test_si_la_lleva_una_persona_solo_se_guarda(enviados):
    """Con el equipo contestando desde el movil, el asistente no habla por encima."""
    from backend import inbox, whatsapp

    telefono = "34600555002"
    session_id = _sesion_limpia(telefono)
    inbox.claim(session_id, "demo", agent_user_id="", agent_name="Equipo (WhatsApp)")
    try:
        _recibir(_mensaje(telefono, "unsupported"))
    finally:
        inbox.release(session_id)

    historial = _historial(session_id)
    _sin_instrucciones(historial)
    assert enviados == []
    entrante, _ = whatsapp.TEXTOS_ILEGIBLE["mensaje"]
    assert ("user", entrante, "human_takeover") in historial


def test_abrir_el_chat_por_primera_vez_es_un_saludo(enviados):
    """`request_welcome` llega antes de que escriba nada: se le saluda, no se le riñe."""
    from backend import whatsapp

    telefono = "34600555003"
    session_id = _sesion_limpia(telefono)

    _recibir(_mensaje(telefono, "request_welcome"))

    _sin_instrucciones(_historial(session_id))
    assert enviados, "hay que contestar al abrir el chat"
    assert not any("no he podido procesar" in str(m) for m in enviados), enviados
    _, respuesta = whatsapp.TEXTOS_ILEGIBLE["mensaje"]
    assert respuesta not in enviados


def test_un_audio_que_no_se_puede_escuchar_se_pide_por_escrito(enviados, monkeypatch):
    """Misma trampa con el audio fallido: la instruccion iba por el hueco del texto."""
    from backend import wa_audio, whatsapp

    async def _sordo(cliente_id, media_id):
        return None

    monkeypatch.setattr(wa_audio, "escuchar", _sordo)
    telefono = "34600555004"
    session_id = _sesion_limpia(telefono)

    _recibir(_mensaje(telefono, "audio", audio={"id": "media_123"}))

    historial = _historial(session_id)
    _sin_instrucciones(historial)
    assert len(enviados) == 1 and "escrib" in str(enviados[0]).lower(), enviados
    entrante, respuesta = whatsapp.TEXTOS_ILEGIBLE["audio"]
    assert enviados == [respuesta]
    assert historial[0][:2] == ("user", entrante)


def test_un_aviso_de_sistema_de_meta_no_se_contesta(enviados):
    """"Este cliente ha cambiado de numero" no lo ha escrito nadie: no se le contesta."""
    telefono = "34600555005"
    session_id = _sesion_limpia(telefono)

    _recibir(_mensaje(telefono, "system", system={
        "body": "El cliente ha cambiado de numero", "type": "customer_changed_number"}))

    assert enviados == [], "se le ha contestado a un aviso de Meta"
    assert _historial(session_id) == []
