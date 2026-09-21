# -*- coding: utf-8 -*-
"""La entrada de WhatsApp con la atención pausada: se guarda, no se contesta.

POR QUE EXISTE
--------------
La autoridad de atención (fase 1) no servía de nada mientras la puerta de WhatsApp
no la consultara: el webhook seguía preparando respuesta, bajando audios y dejando
crear citas. Aquí se cubre esa frontera (fase 2, WA2), con el negocio ya resuelto
-incluido el del número de demo- y ANTES de procesar nada.

Lo que NO puede romper una pausa, porque no es atención automática: la verificación
del webhook, los estados de entrega, los ecos del equipo desde su móvil y el 200 a
Meta. Un error haría que Meta reintentara el mismo mensaje sin que nadie lo pare.

Y lo que la clienta escribe se guarda igual: el equipo tiene que poder leerlo en el
panel y contestar a mano.
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
NUMERO = "34600111222"


def _peticion(payload):
    from starlette.requests import Request

    cuerpo = json.dumps(payload).encode("utf-8")
    firma = "sha256=" + hmac.new(SECRETO.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()

    async def recibir():
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/whatsapp/webhook/demo",
                    "query_string": b"", "client": ("testclient", 50000),
                    "headers": [(b"x-hub-signature-256", firma.encode("ascii"))]}, recibir)


def _payload(mensaje=None, **valor):
    contenido = {"metadata": {"phone_number_id": "WA_NUM_ID"}}
    if mensaje is not None:
        contenido["messages"] = [mensaje]
    contenido.update(valor)
    return {"entry": [{"changes": [{"value": contenido}]}]}


def _texto(cuerpo, telefono=NUMERO):
    return {"from": telefono, "id": "wamid.%s" % uuid.uuid4().hex, "type": "text",
            "text": {"body": cuerpo}}


def _recibir(payload, cliente_id="demo"):
    from backend import whatsapp

    return asyncio.run(whatsapp._handle_whatsapp_webhook(_peticion(payload), forced_cliente_id=cliente_id))


def _historial(cliente_id, telefono):
    from backend import db, whatsapp

    session_id = whatsapp._whatsapp_session_id(cliente_id, telefono)
    with db._get_db_connection() as conexion:
        filas = conexion.execute(
            "SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,)).fetchall()
    return [(f["role"], f["content"]) for f in filas]


def _pausar(cliente_id):
    from backend import atencion

    estado = atencion.leer_atencion(cliente_id)
    return atencion.cambiar_atencion(cliente_id, "pausada", version_esperada=estado["version"],
                                     motivo="cierre_temporada", actor="sistema")


def _reactivar(cliente_id):
    """Deja el negocio atendiendo otra vez. Si la prueba dejó la lectura rota
    (simulando la base de datos caída), se limpia la fila directamente: es
    limpieza de la prueba, no una transición de verdad."""
    from backend import atencion, db

    try:
        estado = atencion.leer_atencion(cliente_id)
        if estado["estado"] == "pausada":
            atencion.cambiar_atencion(cliente_id, "activa", version_esperada=estado["version"],
                                      motivo="reapertura", actor="sistema")
        return
    except Exception:
        pass
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM client_attention_state WHERE cliente_id = ?", (cliente_id,))
        conexion.commit()


@pytest.fixture
def enviados(api_module, monkeypatch):  # noqa: F811
    """Todo lo que saldría hacia la clienta, interceptado."""
    from backend import messaging, settings

    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", SECRETO)
    salida = []

    async def _texto_enviado(*, text, **kwargs):
        salida.append(text)
        return True

    async def _otro(**kwargs):
        salida.append(kwargs)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", _texto_enviado)
    for nombre in ("_send_whatsapp_buttons", "_send_whatsapp_list",
                   "_send_whatsapp_cta_url", "_send_whatsapp_payload"):
        monkeypatch.setattr(messaging, nombre, _otro)
    return salida


@pytest.fixture
def atencion_activa(api_module):  # noqa: F811
    """Deja la atención como estaba, pase lo que pase en la prueba."""
    yield
    _reactivar("demo")


def test_con_la_atencion_pausada_no_se_contesta_pero_se_guarda(enviados, atencion_activa):
    telefono = "34600111333"
    _pausar("demo")
    resultado = _recibir(_payload(_texto("hola, quiero cita", telefono)))

    assert resultado.status == "ok", "Meta tiene que recibir su 200 o reintentará el mensaje"
    assert enviados == [], "se ha contestado con la atención pausada: %r" % enviados
    assert ("user", "hola, quiero cita") in _historial("demo", telefono), (
        "lo que escribió la clienta no está en el panel")
    assert not [r for r, _ in _historial("demo", telefono) if r == "assistant"], (
        "se ha guardado una respuesta del asistente que nadie ha mandado")


def test_con_la_atencion_activa_todo_sigue_igual(enviados, atencion_activa):
    telefono = "34600111444"
    _recibir(_payload(_texto("hola", telefono)))
    assert enviados, "sin pausa el asistente tiene que contestar como siempre"


def test_la_pausa_es_de_cada_negocio(enviados, atencion_activa):
    """Pausar un negocio no puede callar al de al lado: la fila es por tenant."""
    from backend import atencion, atencion_whatsapp

    _pausar("demo")
    assert atencion.leer_atencion("demo")["estado"] == "pausada"
    assert atencion.leer_atencion("otro_negocio")["estado"] == "activa", (
        "la pausa de un negocio ha alcanzado a otro")
    assert atencion_whatsapp.puede_atender("otro_negocio") is True
    assert atencion_whatsapp.puede_atender("demo") is False


def test_los_ecos_del_equipo_siguen_llegando_con_la_pausa(enviados, atencion_activa, monkeypatch):
    """Que el negocio conteste desde su móvil no es atención automática."""
    from backend import whatsapp

    vistos = []
    monkeypatch.setattr(whatsapp, "_handle_whatsapp_echoes",
                        lambda *a, **k: vistos.append(a))
    _pausar("demo")
    resultado = _recibir(_payload(None, smb_message_echoes=[{"from": "34600111222"}]))
    assert vistos, "los ecos del equipo se han bloqueado por la pausa"
    assert resultado.processed == 1


def test_con_la_pausa_no_se_baja_ni_se_transcribe_el_audio(enviados, atencion_activa, monkeypatch):
    """Transcribir cuesta dinero: pausado no se toca el audio."""
    from backend import wa_audio

    escuchados = []

    async def _escuchar(cliente_id, media_id):
        escuchados.append(media_id)
        return "hola"

    monkeypatch.setattr(wa_audio, "escuchar", _escuchar)
    telefono = "34600111666"
    _pausar("demo")
    _recibir(_payload({"from": telefono, "id": "wamid.%s" % uuid.uuid4().hex,
                       "type": "audio", "audio": {"id": "media-123"}}))
    assert escuchados == [], "se ha transcrito un audio con la atención pausada"
    assert enviados == [], "se ha contestado a un audio con la atención pausada"
    assert _historial("demo", telefono), "la nota de voz no ha quedado registrada para el equipo"


def test_si_no_se_puede_saber_el_estado_no_se_atiende(enviados, atencion_activa, monkeypatch):
    """Un error al verificar nunca es permiso para atender.

    Se rompe por los dos caminos que se usan de verdad: la foto barata previa y la
    comprobación del ticket, que es la que decide.
    """
    from backend import atencion, atencion_operaciones, atencion_whatsapp

    def _romper_lectura(cliente_id):
        raise atencion.AtencionNoDisponible("base de datos no disponible")

    monkeypatch.setattr(atencion, "leer_atencion", _romper_lectura)
    assert atencion_whatsapp.puede_atender("demo") is False

    def _romper_ticket(cliente_id, ticket_id):
        raise atencion.AtencionNoDisponible("base de datos no disponible")

    monkeypatch.setattr(atencion_operaciones, "comprobar_ticket_atencion", _romper_ticket)
    telefono = "34600111777"
    resultado = _recibir(_payload(_texto("hola", telefono)))
    assert resultado.status == "ok", "Meta tiene que recibir su 200 igualmente"
    assert enviados == [], "se ha contestado sin poder verificar la atención"
    assert ("user", "hola") in _historial("demo", telefono), (
        "sin poder verificar tampoco se puede perder lo que escribió")


# ─── El formulario de reserva (Flows) ──────────────────────────────────────

def _token_de_formulario(monkeypatch, cliente_id="demo", telefono=NUMERO):
    from backend import settings, wa_flows

    monkeypatch.setattr(settings, "WHATSAPP_FLOW_TOKEN_SECRET", "secreto-de-flows", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", SECRETO)
    return wa_flows.make_flow_token(cliente_id, telefono)


def test_el_formulario_no_ofrece_nada_con_la_atencion_pausada(api_module, atencion_activa, monkeypatch):  # noqa: F811
    """Mientras se rellena, el formulario pide catálogo y huecos. Pausado, no se dan:
    dejarle avanzar hasta una cita que no se va a crear sería mentirle."""
    from backend import wa_flows

    token = _token_de_formulario(monkeypatch)
    activa = asyncio.run(wa_flows.handle_data_exchange({"action": "INIT", "flow_token": token}))
    assert activa["data"]["hay_aviso"] is False, activa

    _pausar("demo")
    pausada = asyncio.run(wa_flows.handle_data_exchange({"action": "INIT", "flow_token": token}))
    assert pausada["data"]["servicios"] == [], "ofrece servicios con la atención pausada"
    assert pausada["data"]["hay_aviso"] is True, pausada
    # El chequeo de salud de Meta no depende del negocio y tiene que seguir contestando.
    assert asyncio.run(wa_flows.handle_data_exchange({"action": "ping"}))["data"]["status"] == "active"


# ─── El formulario queda ligado a la version de atencion ───────────────────
#
# Una pausa y su reactivacion suben la version dos veces. Un formulario abierto
# antes de la pausa no puede revivir al reactivar: ya no corresponde a lo que el
# negocio ofrece ahora, y la clienta lo retomaria donde lo dejo.


def _pantalla_inicial(token):
    from backend import wa_flows

    return asyncio.run(wa_flows.handle_data_exchange({"action": "INIT", "flow_token": token}))


def test_un_formulario_de_antes_de_la_pausa_no_revive_al_reactivar(
        api_module, atencion_activa, monkeypatch):  # noqa: F811
    token = _token_de_formulario(monkeypatch)
    assert _pantalla_inicial(token)["data"]["hay_aviso"] is False

    _pausar("demo")
    _reactivar("demo")
    despues = _pantalla_inicial(token)
    assert despues["data"]["servicios"] == [], "un formulario de antes de la pausa ha revivido"
    assert "caducado" in despues["data"]["aviso"], despues

    nuevo = _token_de_formulario(monkeypatch)
    assert _pantalla_inicial(nuevo)["data"]["hay_aviso"] is False, (
        "tras reactivar, un formulario NUEVO tiene que funcionar")


def test_un_token_de_antes_del_cambio_solo_vale_si_nunca_hubo_pausa(
        api_module, atencion_activa, monkeypatch):  # noqa: F811
    """Los tokens emitidos antes de ligarlos no llevan version. Con version 0
    no ha habido ninguna pausa y no hay nada que proteger; si la ha habido, no
    se puede saber si es de antes o de despues, y no se da por bueno."""
    import base64
    import hashlib
    import hmac
    import secrets

    from backend import atencion, timeutils, wa_flows

    _token_de_formulario(monkeypatch)       # fija los secretos de firma
    carga = "demo|%s|%s|%s" % (NUMERO, timeutils._utc_now_iso(), secrets.token_hex(16))
    raw = base64.urlsafe_b64encode(carga.encode("utf-8")).decode("ascii").rstrip("=")
    firma = hmac.new(wa_flows._token_secret(), raw.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    antiguo = raw + "." + firma
    contexto = wa_flows.read_flow_token(antiguo)
    assert contexto and contexto["version"] is None

    if atencion.leer_atencion("demo")["version"] == 0:
        assert wa_flows.token_sigue_vigente(contexto) is True
    _pausar("demo")
    _reactivar("demo")
    assert wa_flows.token_sigue_vigente(contexto) is False, (
        "un token sin version se ha dado por bueno despues de una pausa")


def test_no_poder_comprobarlo_no_es_decir_que_ha_caducado(
        api_module, atencion_activa, monkeypatch):  # noqa: F811
    """Incertidumbre no es invalidez: a la clienta no se le dice que su
    solicitud ha caducado cuando lo que pasa es que no se puede comprobar."""
    from backend import atencion, wa_flows

    token = _token_de_formulario(monkeypatch)

    def _romper(cliente_id):
        raise atencion.AtencionNoDisponible("base de datos no disponible")

    monkeypatch.setattr(atencion, "leer_atencion", _romper)
    assert wa_flows.token_sigue_vigente(wa_flows.read_flow_token(token)) is None
    pantalla = _pantalla_inicial(token)
    assert pantalla["data"]["servicios"] == []
    assert "caducado" not in pantalla["data"]["aviso"], pantalla
    assert wa_flows.make_flow_token("demo", NUMERO) == "", (
        "se ha abierto un formulario nuevo sin poder comprobar la atencion")


def test_enviar_un_formulario_de_antes_de_la_pausa_no_prepara_la_cita(
        enviados, atencion_activa, monkeypatch):
    """El otro lector del token: el envio final del formulario. Relleno antes
    de la pausa y enviado despues de reactivar, no prepara ningun resumen."""
    from backend import whatsapp

    import hashlib

    from backend import reserva

    telefono = "34600111888"
    token = _token_de_formulario(monkeypatch, telefono=telefono)
    # Como lo deja `_wa_send_booking_form` al mandarlo de verdad: sin esto, otra
    # barrera (el formulario no consta como enviado) lo frenaria igual y la
    # prueba no demostraria nada sobre la version.
    estado = reserva.cargar("demo", telefono)
    assert reserva.preparar_formulario_reserva(
        estado, hashlib.sha256(token.encode("utf-8")).hexdigest())
    reserva.guardar("demo", telefono, estado)
    preparados = []
    monkeypatch.setattr(whatsapp, "_wa_send_booking_summary",
                        lambda **k: preparados.append(k))
    _pausar("demo")
    _reactivar("demo")

    respuesta = json.dumps({"flow_token": token, "servicio": "consulta",
                            "hueco": "2030-01-15T10:00", "nombre": "Ana Ruiz"})
    _recibir(_payload({"from": telefono, "id": "wamid.%s" % uuid.uuid4().hex,
                       "type": "interactive",
                       "interactive": {"type": "nfm_reply",
                                       "nfm_reply": {"response_json": respuesta}}}))
    assert preparados == [], "un formulario de antes de la pausa ha preparado una cita"
    assert any("caducado" in str(t) for t in enviados), (
        "a la clienta no se le ha dicho que la solicitud ya no vale: %r" % enviados)
