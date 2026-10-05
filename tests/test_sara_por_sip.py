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
        "canal_envio": "pedir_email", "email_negocio": "", "oferta": sip.oferta_de_demo("pedir_email"),
        "a_quien": "Peluqueria Elidio", "responsable": "quien lleva el negocio", "saludo": sip.APERTURA,
        "sentido": "saliente", "primera": "", "huecos_pablo": sip.huecos_de_pablo()}
    fila = sip._fila(hecho["llamada"])
    assert (fila["estado"], fila["conversation_id"], fila["call_sid"]) == ("en_curso", "conv_sip_1", "sip_abc")


def test_por_sip_espera_a_que_descuelguen(sip):
    """La API de ElevenLabs no contesta hasta que descuelgan (27 s con un buzon, 28-sep-2026).
    Con la espera de Twilio (30 s), un negocio lento quedaba 'fallida' y sin transcripcion."""
    _, el = _marcar(sip)
    assert el.peticiones[0][2].get("timeout", 0) >= 90


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


@pytest.mark.parametrize("respuesta", [
    (0, httpx.ReadTimeout("sin respuesta")),
    (504, {"detail": "gateway timeout"}),  # revision de Astra (27-sep): pudo iniciarse
    (502, {"detail": "bad gateway"}),
])
def test_si_no_se_sabe_si_sono_no_se_reintenta_solo(sip, respuesta):
    from backend import lanzador_llamadas

    el = _ElevenLabs({"sip-trunk/outbound-call": respuesta})
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


def test_la_vuelta_atras_de_una_rotacion_restaura_el_numero_sip(sip, api_module):  # noqa: F811
    """Revision de Astra (27-sep): si una rotacion importa el numero en la cuenta nueva y
    falla despues, la cuenta vieja no puede quedarse con el id de la nueva. Y el numero no
    es un agente: no entra en lo que se borra de la cuenta que se deja."""
    from backend import cuenta_elevenlabs, voz_elevenlabs

    antes = cuenta_elevenlabs._ids_de_voz()
    voz_elevenlabs.guardar_en_voz("vantelia", sip.CLAVE_NUMERO_SIP, "phnum_de_la_cuenta_nueva")
    cuenta_elevenlabs._restaurar_ids(antes)
    assert api_module.CONFIG_CLIENTES["vantelia"]["voice"][sip.CLAVE_NUMERO_SIP] == "phnum_1"
    assert "phnum_1" not in cuenta_elevenlabs._agentes_guardados()


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


def test_el_numero_ya_importado_no_se_duplica_y_se_pone_al_dia(sip, monkeypatch):
    """Sin importarlo otra vez; pero Sara y la salida se reenvian siempre: tras rotar la
    agente es otra, y una clave renovada en el proveedor tiene que llegar a ElevenLabs
    (revision de Astra, 27-sep: antes solo se tocaba agent_id)."""
    from backend import settings

    monkeypatch.setattr(settings, "CAPTACION_SIP_CLAVE", "clave-renovada")
    el = _ElevenLabs({"GET /v1/convai/phone-numbers/phnum_1": (200, {
        "phone_number": "+34910000001", "assigned_agent": {"agent_id": "agent_sara"}}),
        "PATCH /v1/convai/phone-numbers/phnum_1": (200, {})})
    assert sip.asegurar_numero_sip(el, "agent_sara") == "phnum_1"
    assert [p[0] for p in el.peticiones] == ["GET", "PATCH"], "nada de importarlo otra vez"
    cuerpo = el.peticiones[1][2]["json"]
    assert cuerpo["agent_id"] == "agent_sara"
    assert cuerpo["outbound_trunk_config"]["credentials"] == {"username": "910000001", "password": "clave-renovada"}


def test_la_clave_sip_nunca_sale_en_un_error(sip, api_module):  # noqa: F811
    api_module.CONFIG_CLIENTES["vantelia"]["voice"].pop(sip.CLAVE_NUMERO_SIP)
    # La respuesta es JSON: '{"detail": "' son 12 caracteres, y con 178 de relleno la clave
    # empieza en el 190 y cruza el recorte de 200 (revision de Astra, 27-sep).
    for relleno in ("credenciales no validas: ", "x" * 178):
        el = _ElevenLabs({"POST /v1/convai/phone-numbers": (400, {"detail": relleno + CLAVE_SIP})})
        with pytest.raises(RuntimeError) as error:
            sip.asegurar_numero_sip(el, "agent_sara")
        assert CLAVE_SIP[:6] not in str(error.value)


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
    ids = {sip.NOMBRE_DEL_AGENTE: "agent_sara", sip.NOMBRE_DEL_AGENTE_ENTRADA: "agent_entrada"}
    monkeypatch.setattr(voz_elevenlabs, "configurado", lambda: True)
    monkeypatch.setattr(voz_elevenlabs, "publicar_agente",
                        lambda cliente, cuerpo, previo: publicado.append(cuerpo) or ids[cuerpo["name"]])
    api_module.CONFIG_CLIENTES["vantelia"]["voice"].pop(sip.CLAVE_NUMERO_SIP)
    el = _ElevenLabs()
    hecho = sip.sincronizar_agente(base_url="https://app.test", cliente=el)
    assert hecho == {"agent_id": "agent_sara", "agente_entrada": "agent_entrada", "numero_sip": "phnum_nuevo",
                     "aviso": "wh_1"}
    for cuerpo in publicado:  # las dos Saras llevan el aviso de fin de llamada
        assert cuerpo["platform_settings"]["workspace_overrides"]["webhooks"]["post_call_webhook_id"] == "wh_1"
    # Al 91 va la Sara de ENTRADA (30-sep: con la de llamar, ElevenLabs colgaba cada entrante).
    importado = [p for p in el.peticiones if p[0] == "POST" and p[1].endswith("/v1/convai/phone-numbers")][0]
    assert importado[2]["json"]["agent_id"] == "agent_entrada"
    voz = api_module.CONFIG_CLIENTES["vantelia"]["voice"]
    assert (voz[sip.CLAVE_AGENTE], voz[sip.CLAVE_AGENTE_ENTRADA]) == ("agent_sara", "agent_entrada")


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


# --- Cambiar de cuenta con el 91 (29-sep-2026) --------------------------------------------
#
# ElevenLabs no deja el mismo numero en dos cuentas ("Phone number ... already exists", 409),
# y la rotacion importaba el 91 en la nueva ANTES de soltarlo de la vieja: fallaba siempre y
# el vigilante lo reintentaba cada hora. Si la cuenta activa se hubiera quedado sin
# creditos, Sara se habria quedado muda.

NUMERO = "+34910000001"


class _Cuentas:
    """Varias cuentas de ElevenLabs de mentira: cada peticion va a la de su xi-api-key y un
    numero solo puede estar en una cuenta a la vez."""

    def __init__(self, numeros):
        self.numeros = {clave: dict(ns) for clave, ns in numeros.items()}
        self.peticiones = []
        self._siguiente = 0

    def _registrar(self, metodo, url, k):
        clave = (k.get("headers") or {}).get("xi-api-key", "")
        self.peticiones.append((metodo, url.rsplit("/v1/", 1)[-1], clave))
        return clave, url.rsplit("/v1/", 1)[-1]

    def get(self, url, **k):
        clave, ruta = self._registrar("GET", url, k)
        propios = self.numeros.get(clave, {})
        if ruta == "convai/phone-numbers":
            return _Respuesta(200, [{"phone_number_id": i, "phone_number": n} for i, n in propios.items()])
        numero_id = ruta.rsplit("/", 1)[-1]
        if ruta.startswith("convai/phone-numbers/") and numero_id in propios:
            return _Respuesta(200, {"phone_number_id": numero_id, "phone_number": propios[numero_id]})
        return _Respuesta(404, {}, texto='{"detail": "not found"}')

    def post(self, url, **k):
        clave, _ = self._registrar("POST", url, k)
        numero = (k.get("json") or {}).get("phone_number")
        if any(numero in ns.values() for ns in self.numeros.values()):
            datos = {"detail": {"type": "conflict", "code": "resource_already_exists",
                                "message": "Phone number %s already exists." % numero}}
            return _Respuesta(409, datos, texto=json.dumps(datos))
        self._siguiente += 1
        numero_id = "phnum_%s_%d" % (clave, self._siguiente)
        self.numeros.setdefault(clave, {})[numero_id] = numero
        return _Respuesta(200, {"phone_number_id": numero_id})

    def patch(self, url, **k):
        self._registrar("PATCH", url, k)
        return _Respuesta(200, {})

    def delete(self, url, **k):
        clave, ruta = self._registrar("DELETE", url, k)
        numero_id = ruta.rsplit("/", 1)[-1]
        if self.numeros.get(clave, {}).pop(numero_id, None) is None:
            return _Respuesta(404, {})
        return _Respuesta(200, {})

    def close(self):
        pass

    def donde(self):
        return {clave: sorted(ns.values()) for clave, ns in self.numeros.items() if ns}


@pytest.fixture()
def dos_cuentas(sip, monkeypatch):
    """El 91 importado en la cuenta vieja (phnum_1); la activa pasa a ser la nueva."""
    from backend import cuenta_elevenlabs, settings

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_nueva")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_vieja", "k_nueva"])
    monkeypatch.setattr(cuenta_elevenlabs, "estado", lambda **k: {"ok": True, "tipo": "", "problema": "", "aviso": ""})
    monkeypatch.setattr(cuenta_elevenlabs, "_correo_rotacion", lambda *a, **k: None)
    monkeypatch.setattr(cuenta_elevenlabs, "_correo_rotacion_fallida", lambda *a, **k: None)
    return _Cuentas({"k_vieja": {"phnum_1": NUMERO}})


def test_el_91_se_muda_de_la_cuenta_vieja_a_la_nueva(sip, dos_cuentas, api_module):  # noqa: F811
    numero_id = sip.asegurar_numero_sip(dos_cuentas, "agent_nueva")
    assert dos_cuentas.donde() == {"k_nueva": [NUMERO]}, "en una sola cuenta: la activa"
    assert api_module.CONFIG_CLIENTES["vantelia"]["voice"][sip.CLAVE_NUMERO_SIP] == numero_id


def test_con_una_llamada_en_curso_el_91_no_se_mueve(sip, dos_cuentas):
    _marcar(sip)  # queda "en_curso"
    with pytest.raises(RuntimeError) as error:
        sip.asegurar_numero_sip(dos_cuentas, "agent_nueva")
    assert "llamada en curso" in str(error.value)
    assert dos_cuentas.donde() == {"k_vieja": [NUMERO]}
    assert not [p for p in dos_cuentas.peticiones if p[0] == "DELETE"]


def test_si_la_cuenta_vieja_no_lo_suelta_se_dice_claro(sip, dos_cuentas, monkeypatch):
    monkeypatch.setattr(dos_cuentas, "delete", lambda url, **k: _Respuesta(500, {}))
    with pytest.raises(RuntimeError) as error:
        sip.asegurar_numero_sip(dos_cuentas, "agent_nueva")
    assert "No se pudo quitar el numero SIP de la cuenta" in str(error.value)
    assert dos_cuentas.donde() == {"k_vieja": [NUMERO]}


def test_un_91_de_una_cuenta_ajena_no_se_toca(sip, dos_cuentas):
    dos_cuentas.numeros = {"k_de_otro": {"phnum_x": NUMERO}}
    with pytest.raises(RuntimeError) as error:
        sip.asegurar_numero_sip(dos_cuentas, "agent_nueva")
    assert "no es de la reserva" in str(error.value)
    assert dos_cuentas.donde() == {"k_de_otro": [NUMERO]}


def test_la_rotacion_se_lleva_el_91_a_la_cuenta_nueva(sip, dos_cuentas, monkeypatch):
    from backend import cuenta_elevenlabs, settings

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_vieja")
    salida = cuenta_elevenlabs.rotar("prueba", cliente=dos_cuentas, destino="k_nueva", sincronizar=lambda: {
        "captacion (Sara)": sip.asegurar_numero_sip(dos_cuentas, "agent_sara") and "agent_sara"})
    assert salida["rotada"] is True and settings.ELEVENLABS_API_KEY == "k_nueva"
    assert dos_cuentas.donde() == {"k_nueva": [NUMERO]}


def test_si_la_rotacion_falla_despues_el_91_vuelve_a_la_cuenta_vieja(sip, dos_cuentas, monkeypatch, api_module):  # noqa: F811
    """El 91 ya se habia mudado a la nueva y falla otro agente: sin devolverlo, la cuenta vieja
    (que sigue activa) se quedaba sin numero y Sara no podia marcar."""
    from backend import cuenta_elevenlabs, settings

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_vieja")

    def muda_el_numero_y_falla():
        sip.asegurar_numero_sip(dos_cuentas, "agent_sara")
        raise RuntimeError("fallo el agente de un negocio")

    salida = cuenta_elevenlabs.rotar("prueba", cliente=dos_cuentas, destino="k_nueva",
                                     sincronizar=muda_el_numero_y_falla)
    assert salida["rotada"] is False and settings.ELEVENLABS_API_KEY == "k_vieja"
    assert dos_cuentas.donde() == {"k_vieja": [NUMERO]}, "el 91 vuelve con la cuenta que sigue activa"
    numero_id = api_module.CONFIG_CLIENTES["vantelia"]["voice"][sip.CLAVE_NUMERO_SIP]
    assert numero_id in dos_cuentas.numeros["k_vieja"], "y la config apunta al que existe"
