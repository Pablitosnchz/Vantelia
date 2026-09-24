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
    # Pablo (24-sep) lo pidio corto y detras del gancho, pero tiene que estar al empezar.
    assert "es comercial, y si no quieres mas llamadas, me lo dices" in guion
    assert "tu nunca haces de clienta" in guion, "en la demo la clienta es el negocio, no Sara"
    # Segunda prueba (24-sep): se le colo el ingles y deletreo el email 25 segundos.
    assert "siempre en español" in guion and "no lo deletrees" in guion
    nombres = {t["name"] for t in agente["agent"]["prompt"]["tools"]}
    assert {"enviar_informacion", "volver_a_llamar", "no_volver_a_llamar", "end_call"} <= nombres
    buzon = [t for t in agente["agent"]["prompt"]["tools"] if t["name"] == "voicemail_detection"]
    assert buzon and buzon[0]["params"]["voicemail_message"] == "", "a un contestador: colgar sin mensaje"
    assert agente["tts"]["agent_output_audio_format"] == "ulaw_8000"
    assert agente["agent"]["prompt"]["llm"] != "gemini-2.5-flash"


def test_no_llamar_mas_se_cumple_de_verdad(captacion):
    falso = _Falso()
    llamada = captacion.llamar("91 123 45 67", "Peluqueria Prueba", cliente=falso)
    assert llamada["ok"] is True
    datos = falso.peticiones[0][1]["data"]
    assert "llamada=" + llamada["llamada"] in datos["Url"]
    # Tercera prueba (24-sep): la deteccion de Twilio hacia esperar ~6 s en silencio.
    assert "MachineDetection" not in datos, "quien descuelga no puede oir silencio"
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
        "negocio": "Peluqueria Elidio", "sector": "peluqueria", "llamada": llamada,
        "canal_envio": "pedir_email", "email_negocio": ""}


# --- El cierre: no pedir lo que ya sabemos (segunda prueba, 24-sep) ---------


@pytest.fixture()
def envios(captacion, monkeypatch):
    from backend import messaging, outreach

    registro = {"sms": [], "email": [], "avisos": [], "demos": []}
    monkeypatch.setattr(outreach, "_outreach_maybe_pregenerate_demo", lambda email: registro["demos"].append(email))

    async def sms(to, remitente, texto, **k):
        registro["sms"].append((to, texto))
        return True

    monkeypatch.setattr(messaging, "_send_twilio_sms", sms)
    monkeypatch.setattr(outreach, "_outreach_send_email_object", lambda msg: registro["email"].append(msg))
    monkeypatch.setattr(outreach, "_outreach_notify_admin", lambda *a: registro["avisos"].append(a) or True)
    return registro


def _con_negocio_en_captacion(email, telefono):
    from backend import outreach

    with outreach._outreach_db() as conn:
        conn.execute("INSERT OR REPLACE INTO prospects (email, business_name, niche, phone, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?)", (email, "Peluqueria Fija", "peluqueria", telefono, "x", "x"))
        conn.commit()


@pytest.mark.parametrize("telefono,email,canal", [
    ("+34675802001", "", "sms"), ("+34675802001", "a@b.es", "sms"),
    ("+34911234570", "info@pelu.es", "email"), ("+34911234571", "", "pedir_email"),
])
def test_el_canal_depende_de_si_es_movil_y_de_lo_que_sabemos(captacion, telefono, email, canal):
    assert captacion.canal_de_envio(telefono, email) == canal


def test_a_un_movil_se_le_manda_un_sms_sin_pedir_nada(captacion, envios):
    llamada = captacion.llamar("675 802 001", "Peluqueria Movil", cliente=_Falso())["llamada"]
    r = captacion.herramienta("enviar_informacion", {"_llamada": llamada})
    assert r["ok"] is True and "SMS" in r["mensaje"]
    assert len(envios["sms"]) == 1 and envios["sms"][0][0] == "+34675802001"
    sms = envios["sms"][0][1]
    assert "Peluqueria Movil" in sms and "vantelia.es" in sms
    assert "675 802 001" in sms and "info@vantelia.es" in sms, "cualquier duda: Pablo o info@ (Pablo, 24-sep)"
    assert sms.isascii(), "una tilde cambia la codificacion y el SMS cuesta mas del doble"
    enlace_largo = "https://app.vantelia.es/demo/go/" + "x" * 60
    assert len(captacion.texto_sms("Peluqueria Con Nombre Largo", enlace_largo)) <= 306, "mas de 2 SMS"
    assert envios["email"] == []
    assert captacion._fila(llamada)["resultado"] == "interesado"
    assert len(envios["avisos"]) == 1, "Pablo tiene que enterarse"


def test_a_un_fijo_conocido_se_le_manda_al_correo_del_negocio(captacion, envios, monkeypatch):
    monkeypatch.setenv("OUTREACH_TRACKING_SECRET", "secreto-seguimiento")
    _con_negocio_en_captacion("info@pelufija.es", "91 123 45 72")
    llamada = captacion.llamar("911234572", "Peluqueria Fija", cliente=_Falso())["llamada"]
    assert captacion._fila(llamada)["prospecto"] == "info@pelufija.es", "se reconoce por su telefono"
    r = captacion.herramienta("enviar_informacion", {"_llamada": llamada})
    assert r["ok"] is True and envios["sms"] == []
    assert len(envios["email"]) == 1 and envios["email"][0]["To"] == "info@pelufija.es"
    cuerpo = envios["email"][0].get_body(("plain",)).get_content()
    assert "/demo/go/" in cuerpo, "la demo del propio negocio, como en los correos de captacion"
    assert envios["demos"] == ["info@pelufija.es"], "su demo tiene que empezar a generarse ya"


def test_a_un_fijo_sin_email_se_le_pide_y_uno_mal_dictado_no_vale(captacion, envios):
    llamada = captacion.llamar("911234573", "Peluqueria Sin Email", cliente=_Falso())["llamada"]
    assert captacion.herramienta("enviar_informacion", {"_llamada": llamada})["ok"] is False
    assert captacion.herramienta("enviar_informacion", {"_llamada": llamada, "email": "pepe arroba"})["ok"] is False
    assert envios["email"] == [] and envios["avisos"] == []
    r = captacion.herramienta("enviar_informacion", {"_llamada": llamada, "email": "Pepe@Correo.es"})
    assert r["ok"] is True and envios["email"][0]["To"] == "pepe@correo.es"


def test_si_no_se_puede_mandar_el_interesado_no_se_pierde(captacion, envios, monkeypatch):
    from backend import messaging

    async def falla(*a, **k):
        raise RuntimeError("Twilio caido")

    monkeypatch.setattr(messaging, "_send_twilio_sms", falla)
    llamada = captacion.llamar("675802002", "Peluqueria Sin Suerte", cliente=_Falso())["llamada"]
    r = captacion.herramienta("enviar_informacion", {"_llamada": llamada})
    assert r["ok"] is True and "en un rato" in r["mensaje"]
    assert captacion._fila(llamada)["resultado"] == "interesado"
    assert "NO se pudo" in envios["avisos"][0][1], "Pablo tiene que saber que le toca escribirle"


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
