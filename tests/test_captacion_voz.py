# -*- coding: utf-8 -*-
"""Sara llama a los negocios: lo que la ley exige y lo que no puede pasar nunca.

POR QUE EXISTE
--------------
Parte C del plan de voz (docs/PLAN_VOZ_HUMANA_Y_AUTOCAPTACION.md, 23-sep-2026). Una
llamada comercial en frio tiene reglas (Circular AEPD 1/2023 y Reglamento de IA,
art. 50): decir quien llama y que es una IA, que es comercial, y que puede pedir que
no le llamemos mas. Y "no me llameis" tiene que cumplirse de verdad: ese telefono no
vuelve a sonar. Estos tests vigilan eso y que un contestador no reciba un mensaje.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

SECRETO = "secreto-de-prueba"


@pytest.fixture()
def captacion(api_module, monkeypatch, tmp_path):  # noqa: F811
    """Base de captacion SIEMPRE temporal: nunca la de verdad."""
    from backend import settings

    monkeypatch.setenv("OUTREACH_DB_PATH", str(tmp_path / "outreach.db"))
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(settings, "ELEVENLABS_TOOL_SECRET", SECRETO)
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "token-test")
    monkeypatch.setattr(settings, "TWILIO_DEFAULT_PHONE_NUMBER", "+18030000000")
    from backend import captacion_voz
    return captacion_voz


class _Respuesta:
    def __init__(self, status_code=200, datos=None, texto=""):
        self.status_code, self._datos = status_code, datos or {}
        self.text = texto or "{}"

    def json(self):
        return self._datos


class _Falso:
    def __init__(self):
        self.peticiones = []

    def post(self, url, **k):
        self.peticiones.append((url, k))
        if "register-call" in url:
            return _Respuesta(200, texto='<?xml version="1.0"?><Response><Connect/></Response>')
        return _Respuesta(201, {"sid": "CA_captacion"})


@pytest.mark.parametrize("dado,esperado", [
    ("91 123 45 67", "+34911234567"), ("0034 675 802 001", "+34675802001"),
    ("+34 911 23 45 67", "+34911234567"), ("34911234567", "+34911234567"), ("12", ""),
])
def test_telefonos_en_formato_internacional(captacion, dado, esperado):
    assert captacion.telefono_e164(dado) == esperado


def test_el_guion_cumple_lo_que_exige_la_ley(captacion):
    agente = captacion.agente_de_captacion("https://app.test")["conversation_config"]
    primera = agente["agent"]["first_message"].lower()
    assert "asistente virtual" in primera and "vantelia" in primera, "quien llama y que es una IA, al empezar"
    guion = agente["agent"]["prompt"]["prompt"].lower()
    assert "llamada comercial" in guion
    assert "no se les vuelve a llamar" in guion
    nombres = {t["name"] for t in agente["agent"]["prompt"]["tools"]}
    assert {"apuntar_interes", "volver_a_llamar", "no_volver_a_llamar", "end_call"} <= nombres
    assert agente["tts"]["agent_output_audio_format"] == "ulaw_8000"


def test_no_llamar_mas_se_cumple_de_verdad(captacion):
    falso = _Falso()
    llamada = captacion.llamar("91 123 45 67", "Peluqueria Prueba", cliente=falso)
    assert llamada["ok"] is True
    datos = falso.peticiones[0][1]["data"]
    assert datos["MachineDetection"] == "Enable" and "llamada=" + llamada["llamada"] in datos["Url"]
    assert "/voice/el-captacion/estado" in datos["StatusCallback"]

    r = captacion.herramienta("no_volver_a_llamar", {"_llamada": llamada["llamada"], "motivo": "no llameis"})
    assert r["ok"] is True
    otra = _Falso()
    assert captacion.llamar("+34911234567", "Peluqueria Prueba", cliente=otra) == {"ok": False, "motivo": "no_llamar"}
    assert otra.peticiones == [], "ese telefono no puede volver a sonar"


def test_a_un_contestador_se_le_cuelga_sin_mensaje(captacion):
    llamada = captacion.llamar("911234560", "Peluqueria Contestador", cliente=_Falso())["llamada"]
    falso = _Falso()
    twiml = captacion.twiml_al_descolgar(llamada, "machine_end_beep", "+18030000000", "+34911234560", cliente=falso)
    assert "<Hangup" in twiml and falso.peticiones == []
    assert captacion._fila(llamada)["resultado"] == "contestador"


def test_si_contesta_una_persona_habla_con_sara(captacion, api_module, monkeypatch):  # noqa: F811
    voz = dict(api_module.CONFIG_CLIENTES.get("vantelia", {}).get("voice") or {})
    voz["elevenlabs_agent_captacion"] = "agent_sara"
    monkeypatch.setitem(api_module.CONFIG_CLIENTES, "vantelia", {"voice": voz, "nombre": "Vantelia"})
    llamada = captacion.llamar("911234561", "Peluqueria Elidio", "peluqueria", cliente=_Falso())["llamada"]
    falso = _Falso()
    twiml = captacion.twiml_al_descolgar(llamada, "human", "+18030000000", "+34911234561", cliente=falso)
    assert "<Connect" in twiml
    cuerpo = falso.peticiones[0][1]["json"]
    assert cuerpo["agent_id"] == "agent_sara" and cuerpo["direction"] == "outbound"
    assert cuerpo["conversation_initiation_client_data"]["dynamic_variables"] == {
        "negocio": "Peluqueria Elidio", "sector": "peluqueria", "llamada": llamada}


def test_un_email_mal_dictado_no_se_apunta(captacion, monkeypatch):
    from backend import outreach

    avisos = []
    monkeypatch.setattr(outreach, "_outreach_notify_admin", lambda *a: avisos.append(a) or True)
    llamada = captacion.llamar("911234562", "Peluqueria Email", cliente=_Falso())["llamada"]
    malo = captacion.herramienta("apuntar_interes", {"_llamada": llamada, "email": "elidio arroba"})
    assert malo["ok"] is False and avisos == []
    bueno = captacion.herramienta("apuntar_interes", {"_llamada": llamada, "email": "Elidio@Correo.es",
                                                      "nombre": "Elidio"})
    assert bueno["ok"] is True
    fila = captacion._fila(llamada)
    assert fila["resultado"] == "interesado" and fila["email"] == "elidio@correo.es"
    assert len(avisos) == 1 and "Peluqueria Email" in avisos[0][0], "Pablo tiene que enterarse"


def test_twilio_cuenta_como_acabo_la_llamada(captacion):
    llamada = captacion.llamar("911234563", "Peluqueria Ocupada", cliente=_Falso())["llamada"]
    captacion.estado_final(llamada, "busy")
    assert captacion._fila(llamada)["resultado"] == "ocupado"


def test_la_puerta_de_las_tools_exige_el_secreto(client, captacion):  # noqa: F811
    llamada = captacion.llamar("911234564", "Peluqueria Puerta", cliente=_Falso())["llamada"]
    cuerpo = {"_llamada": llamada, "cuando": "el jueves"}
    assert client.post("/voice/el-captacion/tool/volver_a_llamar", json=cuerpo).status_code == 401
    r = client.post("/voice/el-captacion/tool/volver_a_llamar", json=cuerpo, headers={"X-Vantelia-Voz": SECRETO})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert captacion._fila(llamada)["resultado"] == "volver_a_llamar"
