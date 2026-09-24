# -*- coding: utf-8 -*-
"""La voz de ElevenLabs habla con la voz de Laura pero dice y hace lo NUESTRO.

POR QUE EXISTE
--------------
Pablo eligio a oido (23-sep-2026) una voz castellana nativa de ElevenLabs frente a
las de OpenAI. Lo que no puede cambiar con el proveedor: las instrucciones, el saludo
con el aviso de IA (art. 50 del Reglamento de IA) y la UNICA forma de tocar la agenda
(`voice._voice_dispatch_tool`). Estos tests lo vigilan, y vigilan la puerta por la
que ElevenLabs pide las herramientas: sin el secreto no entra nadie.
"""
from __future__ import annotations

import json

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

SECRETO = "secreto-de-prueba"


@pytest.fixture()
def configurado(api_module, monkeypatch):  # noqa: F811
    from backend import settings

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(settings, "ELEVENLABS_TOOL_SECRET", SECRETO)


def test_las_herramientas_son_las_de_la_voz_de_siempre(api_module, configurado):  # noqa: F811
    from backend import voice, voz_elevenlabs

    config = api_module.CONFIG_CLIENTES["demo"]
    nuestras = [t["name"] for t in voice._voice_booking_tools("demo", config)]
    assert "crear_cita" in nuestras, "el tenant de prueba tiene que tener agenda"
    suyas = voz_elevenlabs.herramientas("demo", config, "https://app.test")

    webhooks = {t["name"]: t for t in suyas if t["type"] == "webhook"}
    assert set(webhooks) == set(nuestras) - {"finalizar_llamada", "transferir_a_humano"}
    assert any(t["type"] == "system" and t["name"] == "end_call" for t in suyas)
    for nombre, tool in webhooks.items():
        api = tool["api_schema"]
        assert api["url"] == "https://app.test/voice/el/demo/tool/%s" % nombre
        assert api["request_headers"] == {"X-Vantelia-Voz": SECRETO}

        def todo_descrito(esquema):
            assert esquema.get("description"), (nombre, esquema)
            for hijo in (esquema.get("properties") or {}).values():
                todo_descrito(hijo)

        todo_descrito(api["request_body_schema"])


def test_el_agente_sale_de_las_fuentes_unicas(api_module, configurado):  # noqa: F811
    from backend import textnorm, voice, voz_elevenlabs

    config = api_module.CONFIG_CLIENTES["demo"]
    cuerpo = voz_elevenlabs.agente_para("demo", config, "https://app.test")["conversation_config"]
    assert cuerpo["agent"]["first_message"] == textnorm._voice_default_greeting(config, config.get("voice") or {})
    assert "asistente virtual" in cuerpo["agent"]["first_message"]
    assert cuerpo["agent"]["prompt"]["prompt"] == voice._voice_build_instructions("demo", config)
    assert cuerpo["agent"]["language"] == "es"
    assert cuerpo["tts"]["model_id"] == "eleven_flash_v2_5", "un agente en espanol exige flash o turbo"


URL = "/voice/el/demo/tool/consultar_disponibilidad"


def test_sin_configurar_no_se_abre(client, api_module):  # noqa: F811
    from backend import settings

    assert not settings.ELEVENLABS_TOOL_SECRET
    assert client.post(URL, json={}, headers={"X-Vantelia-Voz": ""}).status_code == 503


@pytest.mark.parametrize("cabeceras", [{}, {"X-Vantelia-Voz": "otro"}])
def test_sin_el_secreto_no_entra_nadie(client, configurado, cabeceras):  # noqa: F811
    assert client.post(URL, json={"fecha": "2030-01-15"}, headers=cabeceras).status_code == 401


def test_una_herramienta_que_no_es_del_negocio_no_existe(client, configurado):  # noqa: F811
    r = client.post("/voice/el/demo/tool/borrar_todo", json={}, headers={"X-Vantelia-Voz": SECRETO})
    assert r.status_code == 404


def test_la_peticion_buena_va_al_despachador_de_siempre(client, configurado, monkeypatch):  # noqa: F811
    from backend import voice

    llamadas = []

    async def despachar(cliente_id, nombre, argumentos, **kwargs):
        llamadas.append((cliente_id, nombre, json.loads(argumentos)))
        return {"ok": True, "huecos": ["10:00"]}

    monkeypatch.setattr(voice, "_voice_dispatch_tool", despachar)
    r = client.post(URL, json={"fecha": "2030-01-15"}, headers={"X-Vantelia-Voz": SECRETO})
    assert r.status_code == 200 and r.json() == {"ok": True, "huecos": ["10:00"]}
    assert llamadas == [("demo", "consultar_disponibilidad", {"fecha": "2030-01-15"})]


def test_con_la_atencion_pausada_no_toca_la_agenda(client, configurado, monkeypatch):  # noqa: F811
    from backend import atencion_voz, voice

    llamadas = []

    async def despachar(*a, **k):
        llamadas.append(a)
        return {"ok": True}

    monkeypatch.setattr(voice, "_voice_dispatch_tool", despachar)
    monkeypatch.setattr(atencion_voz, "puede_atender", lambda cliente_id: False)
    r = client.post(URL, json={"fecha": "2030-01-15"}, headers={"X-Vantelia-Voz": SECRETO})
    assert r.status_code == 409 and llamadas == []


class _Respuesta:
    def __init__(self, status_code=200, datos=None):
        self.status_code, self._datos, self.text = status_code, datos or {}, json.dumps(datos or {})

    def json(self):
        return self._datos

    def raise_for_status(self):
        assert self.status_code < 400


class _ElevenLabsFalso:
    """Guarda lo que se le pide; cada guardado cambia las tools del agente."""

    def __init__(self):
        self.peticiones, self.tools = [], ["tool_viejo"]

    def get(self, url, **k):
        self.peticiones.append(("GET", url))
        return _Respuesta(200, {"conversation_config": {"agent": {"prompt": {"tool_ids": list(self.tools)}}}})

    def post(self, url, **k):
        self.peticiones.append(("POST", url))
        self.tools = ["tool_nuevo"]
        return _Respuesta(200, {"agent_id": "agent_prueba"})

    def patch(self, url, **k):
        self.peticiones.append(("PATCH", url))
        self.tools = ["tool_nuevo"]
        return _Respuesta(200, {})

    def delete(self, url, **k):
        self.peticiones.append(("DELETE", url))
        return _Respuesta(204)


def test_sincronizar_crea_guarda_el_id_y_luego_actualiza(api_module, configurado, monkeypatch):  # noqa: F811
    from backend import clients, voz_elevenlabs

    monkeypatch.setattr(clients, "_persist_configs_to_disk", lambda configs: None)
    api_module.CONFIG_CLIENTES["demo"].setdefault("voice", {}).pop("elevenlabs_agent_id", None)

    falso = _ElevenLabsFalso()
    primero = voz_elevenlabs.sincronizar_agente("demo", base_url="https://app.test", cliente=falso)
    assert primero["agent_id"] == "agent_prueba"
    from backend import appstate
    assert appstate.CONFIG_CLIENTES["demo"]["voice"]["elevenlabs_agent_id"] == "agent_prueba"
    assert ("POST", voz_elevenlabs.API + "/v1/convai/agents/create") in falso.peticiones

    falso2 = _ElevenLabsFalso()
    voz_elevenlabs.sincronizar_agente("demo", base_url="https://app.test", cliente=falso2)
    metodos = [m for m, _ in falso2.peticiones]
    assert "PATCH" in metodos and "POST" not in metodos, "con id guardado se actualiza, no se duplica"
    assert ("DELETE", voz_elevenlabs.API + "/v1/convai/tools/tool_viejo") in falso2.peticiones, (
        "las tools que el agente ya no usa se quedan en la cuenta para siempre")
    assert appstate.CONFIG_CLIENTES["demo"]["voice"]["elevenlabs_agent_id_telefono"] == "agent_prueba", (
        "el agente de telefono tambien se crea y se guarda")
    appstate.CONFIG_CLIENTES["demo"]["voice"].pop("elevenlabs_agent_id", None)
    appstate.CONFIG_CLIENTES["demo"]["voice"].pop("elevenlabs_agent_id_telefono", None)


class _CuentaNueva(_ElevenLabsFalso):
    """Otra cuenta de ElevenLabs: los agentes guardados no existen en ella."""

    def get(self, url, **k):
        if url.endswith("/agent_de_la_cuenta_vieja"):
            self.peticiones.append(("GET", url))
            return _Respuesta(404, {"detail": "not_found"})
        return super().get(url, **k)


def test_con_una_clave_de_otra_cuenta_se_crean_agentes_nuevos(api_module, configurado, monkeypatch):  # noqa: F811
    """24-sep-2026: Pablo paso a una cuenta Creator nueva. Los ids guardados eran de la
    vieja y sincronizar tiraba un 500 en vez de crear los agentes en la cuenta actual."""
    from backend import appstate, clients, voz_elevenlabs

    monkeypatch.setattr(clients, "_persist_configs_to_disk", lambda configs: None)
    voz = api_module.CONFIG_CLIENTES["demo"].setdefault("voice", {})
    voz["elevenlabs_agent_id"] = voz["elevenlabs_agent_id_telefono"] = "agent_de_la_cuenta_vieja"
    falso = _CuentaNueva()
    salida = voz_elevenlabs.sincronizar_agente("demo", base_url="https://app.test", cliente=falso)
    assert salida["agent_id"] == salida["agente_telefono"] == "agent_prueba"
    metodos = [m for m, _ in falso.peticiones]
    assert "PATCH" not in metodos and metodos.count("POST") == 2
    assert appstate.CONFIG_CLIENTES["demo"]["voice"]["elevenlabs_agent_id"] == "agent_prueba"
    assert appstate.CONFIG_CLIENTES["demo"]["voice"]["elevenlabs_agent_id_telefono"] == "agent_prueba"
    appstate.CONFIG_CLIENTES["demo"]["voice"].pop("elevenlabs_agent_id", None)
    appstate.CONFIG_CLIENTES["demo"]["voice"].pop("elevenlabs_agent_id_telefono", None)


def test_el_id_de_conversacion_sale_del_twiml():
    from backend import voz_elevenlabs

    twiml = ('<?xml version="1.0"?><Response><Connect><Stream url="wss://x">'
             '<Parameter name="conversation_id" value="conv_01abcXYZ" /></Stream></Connect></Response>')
    assert voz_elevenlabs.id_de_conversacion(twiml) == "conv_01abcXYZ"
    assert voz_elevenlabs.id_de_conversacion("<Response/>") == ""


# --- Telefono de los negocios ------------------------------------------------


def test_el_agente_de_telefono_habla_ulaw_y_sabe_quien_llama(api_module, configurado):  # noqa: F811
    from backend import voz_elevenlabs

    config = api_module.CONFIG_CLIENTES["demo"]
    cuerpo = voz_elevenlabs.agente_para("demo", config, "https://app.test", telefono=True)["conversation_config"]
    assert cuerpo["asr"]["user_input_audio_format"] == "ulaw_8000"
    assert cuerpo["tts"]["agent_output_audio_format"] == "ulaw_8000"
    for tool in cuerpo["agent"]["prompt"]["tools"]:
        if tool["type"] == "webhook":
            campo = tool["api_schema"]["request_body_schema"]["properties"]["_llamante"]
            assert campo == {"type": "string", "dynamic_variable": "llamante"}, tool["name"]


def test_la_tool_verifica_con_el_numero_de_quien_llama(client, configurado, monkeypatch):  # noqa: F811
    from backend import voice

    vistos = []

    async def despachar(cliente_id, nombre, argumentos, **kwargs):
        vistos.append((json.loads(argumentos), kwargs.get("from_number")))
        return {"ok": True}

    monkeypatch.setattr(voice, "_voice_dispatch_tool", despachar)
    r = client.post("/voice/el/demo/tool/cancelar_cita", headers={"X-Vantelia-Voz": SECRETO},
                    json={"codigo_reserva": "R-1", "_llamante": "+34600111222"})
    assert r.status_code == 200
    assert vistos == [({"codigo_reserva": "R-1"}, "+34600111222")], "el llamante no puede llegar como argumento"


def test_el_telefono_solo_cambia_de_motor_si_el_negocio_lo_activa(api_module, configurado, monkeypatch):  # noqa: F811
    from backend import voz_elevenlabs

    voz = api_module.CONFIG_CLIENTES["demo"].setdefault("voice", {})
    monkeypatch.setitem(voz, "elevenlabs_agent_id_telefono", "agent_tel")
    monkeypatch.setitem(voz, "engine", "")
    assert voz_elevenlabs.agente_de_telefono("demo") == ""
    monkeypatch.setitem(voz, "engine", "elevenlabs")
    assert voz_elevenlabs.agente_de_telefono("demo") == "agent_tel"


@pytest.fixture()
def llamada_entrante(api_module, client, configurado, monkeypatch):  # noqa: F811
    from backend import messaging, settings, voice

    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "token-test")
    monkeypatch.setattr(messaging, "_twilio_request_valid", lambda url, params, firma: True)
    monkeypatch.setattr(voice, "_client_voice_plan_enabled", lambda cliente_id: True)
    voz = dict(api_module.CONFIG_CLIENTES["demo"].get("voice") or {})
    voz.update({"enabled": True, "engine": "elevenlabs", "elevenlabs_agent_id_telefono": "agent_tel"})
    monkeypatch.setitem(api_module.CONFIG_CLIENTES["demo"], "voice", voz)

    def llamar():
        return client.post("/voice/demo", data={"CallSid": "CA_EL_1", "From": "+34600111222",
                                                "To": "+34911111111"},
                           headers={"X-Twilio-Signature": "simulada"})
    return llamar


TWIML_ELEVENLABS = ('<?xml version="1.0"?><Response><Connect>'
                    '<Stream url="wss://api.elevenlabs.io/x"/></Connect></Response>')


def test_la_llamada_entrante_va_al_agente_del_negocio(llamada_entrante, monkeypatch):
    from backend import voz_elevenlabs

    pedidas = []

    def registrar(agente, desde, hacia, direccion, variables=None, cliente=None):
        pedidas.append((agente, desde, direccion, variables))
        return TWIML_ELEVENLABS

    monkeypatch.setattr(voz_elevenlabs, "twiml_registrar_llamada", registrar)
    r = llamada_entrante()
    assert r.status_code == 200 and "api.elevenlabs.io" in r.text
    assert pedidas == [("agent_tel", "+34600111222", "inbound", {"llamante": "+34600111222"})]


def test_si_elevenlabs_falla_contesta_el_motor_de_siempre(llamada_entrante, monkeypatch):
    from backend import voz_elevenlabs

    def falla(*a, **k):
        raise RuntimeError("ElevenLabs caido")

    monkeypatch.setattr(voz_elevenlabs, "twiml_registrar_llamada", falla)
    r = llamada_entrante()
    assert r.status_code == 200 and "/voice/stream/demo" in r.text, "la llamada no puede perderse"
