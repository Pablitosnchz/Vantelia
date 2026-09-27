# -*- coding: utf-8 -*-
"""Sara marca desde un 91 de un proveedor espanol importado en ElevenLabs (via SIP).

POR QUE EXISTE
--------------
27-sep-2026: Twilio aprobo el bundle pero no tiene numeros espanoles, y desde el
17-oct-2026 no deja usar los locales para llamadas comerciales. Pablo eligio Zadarma (91 de
Madrid, guia oficial para ElevenLabs; Netelip pedia firma FNMT y factura a su nombre). Con
CAPTACION_VOZ_VIA=sip:

- se marca por la API de ElevenLabs con las MISMAS variables del guion que por Twilio;
- "comunicaba / no lo cogio" llega por el aviso `call_initiation_failure` y queda igual
  que con Twilio (resultado sin conversacion y sin conversation_id), para que el lanzador
  aplique las mismas reglas de reintento;
- el numero y el aviso se crean en la cuenta de ElevenLabs activa (y en la nueva al rotar);
  el secreto de cada aviso vive en storage/, nunca en git, y la clave SIP nunca sale en un
  error.
"""
from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_captacion_voz import _Respuesta, captacion  # noqa: F401
from test_transcripciones_llamadas import _conversacion, _firma

CLAVE_SIP = "clave-sip-secreta-123"


class _ElevenLabs:
    """ElevenLabs de mentira: apunta cada peticion y responde lo que se le diga por ruta."""

    def __init__(self, respuestas=None):
        self.peticiones = []
        self.respuestas = dict({
            "sip-trunk/outbound-call": (200, {"success": True, "conversation_id": "conv_sip_1",
                                              "sip_call_id": "sip_abc"}),
            "POST /v1/convai/phone-numbers": (200, {"phone_number_id": "phnum_nuevo"}),
            "POST /v1/workspace/webhooks": (200, {"webhook_id": "wh_1", "webhook_secret": "wsec_1"}),
            "GET /v1/workspace/webhooks": (200, {"webhooks": []}),
        }, **(respuestas or {}))

    def _responder(self, metodo, url, k):
        self.peticiones.append((metodo, url, k))
        for clave, (codigo, datos) in self.respuestas.items():
            if (clave.startswith(metodo + " ") and url.endswith(clave.split(" ", 1)[1])) or \
                    (" " not in clave and clave in url):
                if isinstance(datos, Exception):
                    raise datos
                return _Respuesta(codigo, datos, texto=json.dumps(datos))
        return _Respuesta(404, {}, texto='{"detail": "not found"}')

    def get(self, url, **k):
        return self._responder("GET", url, k)

    def post(self, url, **k):
        return self._responder("POST", url, k)

    def patch(self, url, **k):
        return self._responder("PATCH", url, k)

    def close(self):
        pass


@pytest.fixture()
def sip(captacion, api_module, monkeypatch, tmp_path):  # noqa: F811
    """Via SIP (Zadarma), Sara creada y su 91 importado. Storage temporal."""
    from backend import clients, settings

    monkeypatch.setattr(settings, "CAPTACION_VOZ_VIA", "sip")
    monkeypatch.setattr(settings, "CAPTACION_SIP_NUMERO", "+34910000001")
    monkeypatch.setattr(settings, "CAPTACION_SIP_USUARIO", "910000001")
    monkeypatch.setattr(settings, "CAPTACION_SIP_CLAVE", CLAVE_SIP)
    monkeypatch.setattr(settings, "CAPTACION_SIP_HOST", "pbx.zadarma.com")
    monkeypatch.setattr(settings, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(clients, "_persist_configs_to_disk", lambda configs: None)
    voz = dict(api_module.CONFIG_CLIENTES.get("vantelia", {}).get("voice") or {})
    voz.update({"elevenlabs_agent_captacion": "agent_sara", captacion.CLAVE_NUMERO_SIP: "phnum_1"})
    monkeypatch.setitem(api_module.CONFIG_CLIENTES, "vantelia", {"voice": voz, "nombre": "Vantelia"})
    return captacion


def _marcar(sip, el=None, telefono="911234561"):
    el = el or _ElevenLabs()
    hecho = sip.llamar(telefono, "Peluqueria Elidio", "peluqueria", cliente=el)
    return hecho, el


# --- Marcar ---------------------------------------------------------------------------

def test_por_sip_marca_elevenlabs_con_las_variables_de_siempre(sip):
    hecho, el = _marcar(sip)
    assert [p[1].rsplit("/v1/", 1)[1] for p in el.peticiones] == ["convai/sip-trunk/outbound-call"], "nada de Twilio"
    cuerpo = el.peticiones[0][2]["json"]
    assert (cuerpo["agent_id"], cuerpo["agent_phone_number_id"], cuerpo["to_number"]) == (
        "agent_sara", "phnum_1", "+34911234561")
    assert cuerpo["conversation_initiation_client_data"]["dynamic_variables"] == {
        "negocio": "Peluqueria Elidio", "sector": "peluqueria", "llamada": hecho["llamada"],
        "canal_envio": "pedir_email", "email_negocio": "",
        "a_quien": "Peluqueria Elidio", "responsable": "quien lleva el negocio"}
    fila = sip._fila(hecho["llamada"])
    assert (fila["estado"], fila["conversation_id"], fila["call_sid"]) == ("en_curso", "conv_sip_1", "sip_abc")


def test_la_rellamada_pregunta_por_quien_decide_tambien_por_sip(sip):
    el = _ElevenLabs()
    hecho = sip.llamar("911234561", "Pelu Marta", "peluqueria", responsable="Marta", rellamada_de="ll_x", cliente=el)
    variables = el.peticiones[0][2]["json"]["conversation_initiation_client_data"]["dynamic_variables"]
    assert (variables["a_quien"], variables["responsable"], variables["llamada"]) == ("Marta", "Marta", hecho["llamada"])


def test_sin_el_numero_importado_no_marca(sip, api_module):  # noqa: F811
    api_module.CONFIG_CLIENTES["vantelia"]["voice"].pop(sip.CLAVE_NUMERO_SIP)
    el = _ElevenLabs()
    with pytest.raises(RuntimeError):
        sip.llamar("911234561", "Pelu", cliente=el)
    assert el.peticiones == []


def test_si_elevenlabs_no_puede_marcar_se_puede_reintentar(sip):
    from backend import lanzador_llamadas

    el = _ElevenLabs({"sip-trunk/outbound-call": (200, {"success": False, "message": "Trunk rechazo la llamada"})})
    with pytest.raises(RuntimeError):
        _marcar(sip, el)
    with sip._db() as conn:
        fila = conn.execute("SELECT estado, resultado, conversation_id FROM llamadas_voz").fetchone()
    assert tuple(fila) == ("fallida", "fallida", "")
    assert fila[1] in lanzador_llamadas.SIN_CONVERSACION, "nadie oyo nada: como un 'fallida' de Twilio"


def test_si_no_se_sabe_si_sono_no_se_reintenta_solo(sip):
    from backend import lanzador_llamadas

    el = _ElevenLabs({"sip-trunk/outbound-call": (0, httpx.ReadTimeout("sin respuesta"))})
    with pytest.raises(RuntimeError):
        _marcar(sip, el)
    with sip._db() as conn:
        fila = conn.execute("SELECT estado, resultado FROM llamadas_voz").fetchone()
    assert fila[0] == "fallida" and fila[1] not in lanzador_llamadas.SIN_CONVERSACION


def test_con_la_cuenta_de_voz_caida_se_avisa_para_rotar(sip, monkeypatch):
    from backend import lanzador_llamadas

    avisos = []
    monkeypatch.setattr(lanzador_llamadas, "fallo_de_voz", lambda llamada, error: avisos.append(error) or True)
    el = _ElevenLabs({"sip-trunk/outbound-call": (401, {"detail": {"status": "payment_required"}})})
    with pytest.raises(RuntimeError):
        _marcar(sip, el)
    assert len(avisos) == 1 and "401" in avisos[0]


# --- Comunicaba / no lo cogio (aviso call_initiation_failure) ----------------------------

@pytest.mark.parametrize("motivo,resultado", [("busy", "ocupado"), ("no-answer", "no_contesta"),
                                              ("unknown", "fallida"), ("", "fallida")])
def test_el_fallo_al_marcar_queda_como_con_twilio(sip, motivo, resultado):
    from backend import lanzador_llamadas

    hecho, _ = _marcar(sip)
    assert sip.fallo_al_marcar("conv_sip_1", motivo, {"type": "sip", "body": {"sip_status_code": 486}}) == hecho["llamada"]
    fila = sip._fila(hecho["llamada"])
    assert (fila["estado"], fila["resultado"], fila["conversation_id"]) == ("terminada", resultado, "")
    assert resultado in lanzador_llamadas.SIN_CONVERSACION and "486" in fila["notas"]


def test_un_comunicaba_que_llega_antes_de_guardar_la_conversacion_no_se_pierde(sip):
    """Revision de Astra (27-sep): el aviso llega mientras ElevenLabs aun no ha respondido a
    `outbound-call`; antes se descartaba con 200 y la llamada quedaba "en curso" sin reintento."""
    el = _ElevenLabs()
    responder = el._responder

    def aviso_durante_la_peticion(metodo, url, k):
        if "outbound-call" in url:
            assert sip.fallo_al_marcar("conv_sip_1", "busy", {"sip_status_code": 486}) is None, "aun no hay llamada"
        return responder(metodo, url, k)

    el._responder = aviso_durante_la_peticion
    hecho, _ = _marcar(sip, el)
    fila = sip._fila(hecho["llamada"])
    assert (fila["estado"], fila["resultado"], fila["conversation_id"]) == ("terminada", "ocupado", "")
    with sip._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llamadas_fallos_pendientes").fetchone()[0] == 0


def test_un_fallo_de_otra_conversacion_no_toca_ninguna_llamada(sip):
    hecho, _ = _marcar(sip)
    assert sip.fallo_al_marcar("conv_de_otro", "busy") is None
    assert sip._fila(hecho["llamada"])["estado"] == "en_curso"


def test_el_fallo_al_marcar_no_pisa_lo_que_apunto_sara(sip):
    hecho, _ = _marcar(sip)
    sip._actualizar(hecho["llamada"], resultado="interesado")
    sip.fallo_al_marcar("conv_sip_1", "busy")
    fila = sip._fila(hecho["llamada"])
    assert (fila["resultado"], fila["conversation_id"]) == ("interesado", "conv_sip_1")


def test_el_aviso_llega_firmado_con_el_secreto_de_su_cuenta(sip, client, monkeypatch):  # noqa: F811
    from backend import settings

    hecho, _ = _marcar(sip)
    # Una llamada que acaba justo despues de rotar viene firmada por la cuenta vieja: vale
    # cualquiera de los secretos, no solo el primero.
    monkeypatch.setattr(settings, "ELEVENLABS_WEBHOOK_SECRET", "secreto-del-entorno")
    (settings.STORAGE_DIR / "elevenlabs_avisos.json").write_text(
        json.dumps({"cuenta_b": {"webhook_id": "wh_b", "secreto": "wsec_b"},
                    "cuenta_a": {"webhook_id": "wh_a", "secreto": "wsec_a"}}), encoding="utf-8")
    cuerpo = json.dumps({"type": "call_initiation_failure",
                         "data": {"conversation_id": "conv_sip_1", "failure_reason": "no-answer",
                                  "metadata": {"type": "sip", "body": {"sip_status_code": 480}}}}).encode()
    malo = client.post("/voice/el-captacion/fin", content=cuerpo,
                       headers={"ElevenLabs-Signature": _firma(cuerpo, "otro-secreto")})
    assert malo.status_code == 401
    bueno = client.post("/voice/el-captacion/fin", content=cuerpo,
                        headers={"ElevenLabs-Signature": _firma(cuerpo, "wsec_a")})
    assert bueno.status_code == 200 and bueno.json()["llamada"] == hecho["llamada"]
    assert sip._fila(hecho["llamada"])["resultado"] == "no_contesta"


def test_sin_ningun_secreto_el_aviso_se_rechaza(sip, client):  # noqa: F811
    r = client.post("/voice/el-captacion/fin", content=b"{}", headers={"ElevenLabs-Signature": "t=1,v0=x"})
    assert r.status_code == 503


# --- Terminar sin Twilio ----------------------------------------------------------------

def test_la_transcripcion_cierra_la_llamada_por_sip(sip):
    from backend import transcripciones_llamadas

    hecho, _ = _marcar(sip)
    assert transcripciones_llamadas.guardar(_conversacion("conv_sip_1"), "aviso") == hecho["llamada"]
    assert sip._fila(hecho["llamada"])["estado"] == "terminada"


def test_la_recogida_de_respaldo_encuentra_las_que_nadie_cerro(sip, monkeypatch):
    from backend import settings, transcripciones_llamadas

    hecho, _ = _marcar(sip)
    with sip._db() as conn:  # se perdio el aviso: sigue "en_curso" desde hace un rato
        antes = (sip.timeutils._utc_now() - timedelta(minutes=30)).isoformat(timespec="seconds")
        conn.execute("UPDATE llamadas_voz SET actualizada=?", (antes,))
        conn.commit()
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_vieja"])

    class _Api:
        def get(self, url, headers=None, **k):
            return _Respuesta(200, _conversacion("conv_sip_1"))

    assert transcripciones_llamadas.recoger_pendientes(cliente=_Api()) == 1
    assert sip._fila(hecho["llamada"])["estado"] == "terminada"


# --- El numero y el aviso en la cuenta activa ---------------------------------------------

def test_el_numero_se_importa_con_los_datos_del_proveedor(sip, api_module):  # noqa: F811
    api_module.CONFIG_CLIENTES["vantelia"]["voice"].pop(sip.CLAVE_NUMERO_SIP)
    el = _ElevenLabs()
    assert sip.asegurar_numero_sip(el, "agent_sara") == "phnum_nuevo"
    metodo, url, k = el.peticiones[-1]
    assert (metodo, url.rsplit("/v1/", 1)[1]) == ("POST", "convai/phone-numbers")
    cuerpo = k["json"]
    assert (cuerpo["phone_number"], cuerpo["provider"], cuerpo["agent_id"]) == ("+34910000001", "sip_trunk", "agent_sara")
    assert cuerpo["outbound_trunk_config"] == {
        "address": "pbx.zadarma.com", "transport": "tcp", "media_encryption": "disabled",
        "credentials": {"username": "910000001", "password": CLAVE_SIP}}
    assert api_module.CONFIG_CLIENTES["vantelia"]["voice"][sip.CLAVE_NUMERO_SIP] == "phnum_nuevo"


def test_el_numero_ya_importado_no_se_duplica(sip):
    el = _ElevenLabs({"GET /v1/convai/phone-numbers/phnum_1": (200, {
        "phone_number": "+34910000001", "assigned_agent": {"agent_id": "agent_sara"}})})
    assert sip.asegurar_numero_sip(el, "agent_sara") == "phnum_1"
    assert [p[0] for p in el.peticiones] == ["GET"]
    # Tras rotar de cuenta la agente es otra: se le asigna, sin importar de nuevo.
    el = _ElevenLabs({"GET /v1/convai/phone-numbers/phnum_1": (200, {
        "phone_number": "+34910000001", "assigned_agent": {"agent_id": "agent_vieja"}}),
        "PATCH /v1/convai/phone-numbers/phnum_1": (200, {})})
    assert sip.asegurar_numero_sip(el, "agent_sara") == "phnum_1"
    assert [(p[0], p[2].get("json")) for p in el.peticiones] == [("GET", None), ("PATCH", {"agent_id": "agent_sara"})]


def test_la_clave_sip_nunca_sale_en_un_error(sip, api_module):  # noqa: F811
    api_module.CONFIG_CLIENTES["vantelia"]["voice"].pop(sip.CLAVE_NUMERO_SIP)
    el = _ElevenLabs({"POST /v1/convai/phone-numbers": (400, {"detail": "credenciales %s no validas" % CLAVE_SIP})})
    with pytest.raises(RuntimeError) as error:
        sip.asegurar_numero_sip(el, "agent_sara")
    assert CLAVE_SIP not in str(error.value)


def test_el_aviso_se_crea_una_vez_por_cuenta_y_su_secreto_no_va_a_git(sip):
    from backend import cuenta_elevenlabs, settings

    el = _ElevenLabs()
    assert sip.asegurar_aviso(el, "https://app.test") == "wh_1"
    metodo, url, k = el.peticiones[-1]
    assert (metodo, k["json"]["settings"]["webhook_url"]) == ("POST", "https://app.test/voice/el-captacion/fin")
    guardado = json.loads((settings.STORAGE_DIR / "elevenlabs_avisos.json").read_text(encoding="utf-8"))
    assert guardado == {cuenta_elevenlabs.huella(settings.ELEVENLABS_API_KEY): {"webhook_id": "wh_1", "secreto": "wsec_1"}}
    assert "wsec_1" in sip.secretos_de_aviso()
    el = _ElevenLabs({"GET /v1/workspace/webhooks": (200, {"webhooks": [{"webhook_id": "wh_1"}]})})
    assert sip.asegurar_aviso(el, "https://app.test") == "wh_1"
    assert [p[0] for p in el.peticiones] == ["GET"], "ya existe en esta cuenta: no se crea otro"


def test_sara_por_sip_lleva_el_aviso_con_los_fallos_al_marcar(sip):
    assert "workspace_overrides" not in sip.agente_de_captacion("https://app.test")["platform_settings"]
    avisos = sip.agente_de_captacion("https://app.test", "wh_1")["platform_settings"]["workspace_overrides"]["webhooks"]
    assert avisos["post_call_webhook_id"] == "wh_1"
    assert set(avisos["events"]) == {"transcript", "call_initiation_failure"}


def test_sincronizar_por_sip_deja_aviso_agente_y_numero(sip, monkeypatch, api_module):  # noqa: F811
    from backend import voz_elevenlabs

    publicado = []
    monkeypatch.setattr(voz_elevenlabs, "configurado", lambda: True)
    monkeypatch.setattr(voz_elevenlabs, "publicar_agente",
                        lambda cliente, cuerpo, previo: publicado.append(cuerpo) or "agent_sara")
    api_module.CONFIG_CLIENTES["vantelia"]["voice"].pop(sip.CLAVE_NUMERO_SIP)
    hecho = sip.sincronizar_agente(base_url="https://app.test", cliente=_ElevenLabs())
    assert hecho == {"agent_id": "agent_sara", "numero_sip": "phnum_nuevo", "aviso": "wh_1"}
    assert publicado[0]["platform_settings"]["workspace_overrides"]["webhooks"]["post_call_webhook_id"] == "wh_1"


# --- Lo que el lanzador exige por SIP ----------------------------------------------------

def test_por_sip_el_lanzador_pide_el_sip_y_el_aviso_no_el_numero_de_twilio(sip, api_module, monkeypatch):  # noqa: F811
    from backend import lanzador_llamadas, settings

    faltan = " ".join(lanzador_llamadas.bloqueos())
    assert "CAPTACION_TWILIO_NUMBER" not in faltan and "aviso de fin de llamada" in faltan
    monkeypatch.setattr(settings, "CAPTACION_SIP_CLAVE", "")
    assert "SIP de Sara" in " ".join(lanzador_llamadas.bloqueos())
    monkeypatch.setattr(settings, "CAPTACION_SIP_CLAVE", CLAVE_SIP)
    api_module.CONFIG_CLIENTES["vantelia"]["voice"].pop(sip.CLAVE_NUMERO_SIP)
    assert "no esta importado" in " ".join(lanzador_llamadas.bloqueos())


def test_por_twilio_todo_sigue_igual(captacion, monkeypatch):  # noqa: F811
    from backend import lanzador_llamadas, settings

    monkeypatch.setattr(settings, "CAPTACION_VOZ_VIA", "")
    assert captacion.via_sip() is False
    assert "CAPTACION_TWILIO_NUMBER" in " ".join(lanzador_llamadas.bloqueos())
