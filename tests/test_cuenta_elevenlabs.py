# -*- coding: utf-8 -*-
"""Si la cuenta de ElevenLabs se acaba, Pablo se entera y Sara no llama a nadie.

POR QUE EXISTE
--------------
24-sep-2026: Pablo cancelo la suscripcion Creator ("lo que nos dure") y pidio que le
avisemos cuando se acabe para pasar a otra cuenta. Con la cuenta en plan gratuito, sin
creditos o con la clave revocada, la voz no suena: un negocio que descolgase una
llamada de Sara oiria colgar. `backend/cuenta_elevenlabs.py` lo detecta, manda UN
correo (no uno por hora) y el lanzador deja de marcar.
"""
from __future__ import annotations

import httpx
import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_lanzador_llamadas import MARTES_10_30, _prospecto, _ronda  # noqa: F401


class _Respuesta:
    def __init__(self, status_code, datos=None):
        self.status_code, self._datos, self.text = status_code, datos or {}, str(datos)

    def json(self):
        return self._datos


class _Api:
    def __init__(self, status_code=200, **suscripcion):
        self.status_code, self.suscripcion, self.peticiones = status_code, suscripcion, 0

    def get(self, url, **k):
        self.peticiones += 1
        if isinstance(self.status_code, Exception):
            raise self.status_code
        return _Respuesta(self.status_code, self.suscripcion)


def _creator(usados=0, limite=300000, plan="creator", estado="active", factura_abierta=False):
    return _Api(200, tier=plan, status=estado, character_count=usados, character_limit=limite,
                next_character_count_reset_unix=1791011567, has_open_invoices=factura_abierta)


@pytest.fixture()
def cuenta(api_module, monkeypatch):  # noqa: F811
    from backend import cuenta_elevenlabs, outreach, settings

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "clave-de-prueba")
    cuenta_elevenlabs._cache.clear()
    cuenta_elevenlabs._avisados.clear()
    correos = []
    monkeypatch.setattr(outreach, "_outreach_notify_admin", lambda asunto, texto, html="": correos.append((asunto, texto)))
    cuenta_elevenlabs.correos = correos
    yield cuenta_elevenlabs
    cuenta_elevenlabs._cache.clear()
    cuenta_elevenlabs._avisados.clear()


@pytest.mark.parametrize("api,ok,tipo", [
    (_creator(), True, ""),                                           # en plan y con creditos
    (_creator(usados=280000), True, "pocos"),                         # avisa, pero aun funciona
    (_creator(usados=300000), False, "agotados"),
    (_creator(plan="free"), False, "gratis"),                         # suscripcion acabada
    (_Api(401, detail={"status": "invalid_api_key"}), False, "clave"),
    # 24-sep-2026: la Creator cancelada decia "creator" y 300.000 creditos, pero con la
    # factura sin pagar ElevenLabs rechazaba todo uso.
    (_creator(estado="past_due", factura_abierta=True), False, "pago"),
    (_creator(estado="past_due"), True, ""),                          # reintentando el cobro, sin deuda
    (_creator(estado="unpaid"), False, "pago"),
])
def test_que_se_considera_una_cuenta_caida(cuenta, api, ok, tipo):
    leido = cuenta.estado(fresco=True, cliente=api)
    assert leido["ok"] is ok and leido["tipo"] == tipo


def test_sin_poder_consultar_no_se_llama_pero_tampoco_se_avisa(cuenta):
    api = _Api(httpx.ConnectError("sin red"))
    assert cuenta.estado(fresco=True, cliente=api)["ok"] is False
    assert cuenta.vigilar_una_vez(cliente=api) == "" and cuenta.correos == []


def test_se_avisa_una_vez_con_los_pasos_para_cambiar_de_cuenta(cuenta):
    assert cuenta.vigilar_una_vez(cliente=_creator(plan="free")) == "gratis"
    assert cuenta.vigilar_una_vez(cliente=_creator(plan="free")) == "", "el mismo aviso no se repite en 24 h"
    assert len(cuenta.correos) == 1
    asunto, texto = cuenta.correos[0]
    assert "ElevenLabs" in asunto and "ELEVENLABS_API_KEY" in texto and "no llama a nadie" in texto
    assert cuenta.vigilar_una_vez(cliente=_creator(usados=300000)) == "agotados", "un problema distinto si avisa"


def test_con_pocos_creditos_el_aviso_dice_que_aun_funciona(cuenta):
    cuenta.vigilar_una_vez(cliente=_creator(usados=280000))
    texto = cuenta.correos[0][1]
    assert "Todavia funciona" in texto and "no llama a nadie" not in texto


def test_en_plan_no_se_manda_nada(cuenta):
    assert cuenta.vigilar_una_vez(cliente=_creator()) == "" and cuenta.correos == []


def test_la_consulta_se_guarda_media_hora(cuenta):
    api = _creator()
    cuenta.estado(cliente=api)
    cuenta.estado(cliente=api)
    assert api.peticiones == 1


def test_con_la_cuenta_caida_el_lanzador_no_marca(cuenta, monkeypatch, tmp_path):
    """Integracion: bloqueos() del lanzador mira la cuenta de verdad (sin el doble del fixture)."""
    from backend import captacion_voz, clients, lanzador_llamadas, settings

    monkeypatch.setenv("OUTREACH_DB_PATH", str(tmp_path / "outreach.db"))
    for nombre, valor in {"ELEVENLABS_TOOL_SECRET": "s", "TWILIO_ACCOUNT_SID": "AC", "TWILIO_AUTH_TOKEN": "t",
                          "CAPTACION_TWILIO_NUMBER": "+34910000000", "ROBINSON_API_KEY": "k",
                          "ROBINSON_API_SECRET": "s", "CAPTACION_LLAMADAS_ENABLED": True}.items():
        monkeypatch.setattr(settings, nombre, valor)
    original = clients._get_client_config
    monkeypatch.setattr(clients, "_get_client_config", lambda cid: (
        {"voice": {captacion_voz.CLAVE_AGENTE: "agent_sara"}} if cid == captacion_voz.TENANT else original(cid)))
    cuenta.estado(fresco=True, cliente=_creator(plan="free"))  # queda en la cache
    lanzador_llamadas.guardar_config(activo=True)
    _prospecto(lanzador_llamadas, "a@pelu.es", "911111111")
    salida, marcador = _ronda(lanzador_llamadas)
    assert marcador.llamados == [] and "plan gratuito" in salida["motivo"]


# --- Si ElevenLabs falla con el negocio ya al telefono -------------------------

@pytest.fixture()
def al_descolgar(cuenta, monkeypatch, tmp_path, client):  # noqa: F811
    """Twilio firmado, cuenta en plan gratuito y un negocio que acaba de descolgar."""
    from backend import captacion_voz, clients, lanzador_llamadas, messaging, settings, voz_elevenlabs

    monkeypatch.setenv("OUTREACH_DB_PATH", str(tmp_path / "outreach.db"))
    monkeypatch.setattr(messaging, "_voice_twilio_configured", lambda: True)
    monkeypatch.setattr(messaging, "_twilio_request_valid", lambda *a, **k: True)
    monkeypatch.setattr(settings, "ELEVENLABS_TOOL_SECRET", "s")
    monkeypatch.setattr(cuenta, "estado", lambda **k: {
        "ok": False, "tipo": "gratis", "problema": "La cuenta de ElevenLabs ha vuelto al plan gratuito."})

    def sin_voz(*a, **k):
        raise RuntimeError("ElevenLabs no registro la llamada (402): payment_required")

    monkeypatch.setattr(voz_elevenlabs, "twiml_registrar_llamada", sin_voz)
    original = clients._get_client_config
    monkeypatch.setattr(clients, "_get_client_config", lambda cid: (
        {"voice": {captacion_voz.CLAVE_AGENTE: "agent_sara"}} if cid == captacion_voz.TENANT else original(cid)))
    with captacion_voz._db() as conn:
        conn.execute("INSERT INTO llamadas_voz (id, telefono, estado, origen, creada, actualizada) "
                     "VALUES ('ll_x', '+34911111111', 'marcando', 'auto', 'x', 'x')")
        conn.commit()
    return client, lanzador_llamadas, captacion_voz


def test_si_la_voz_falla_al_descolgar_se_apaga_y_avisa(al_descolgar, cuenta):
    client, lanzador, captacion_voz = al_descolgar
    lanzador.guardar_config(activo=True)
    r = client.post(captacion_voz.RUTA + "/twiml?llamada=ll_x",
                    data={"AnsweredBy": "human", "From": "+34910000000", "To": "+34911111111"})
    assert r.status_code == 200 and "<Hangup/>" in r.text
    assert lanzador.config()["activo"] == 0, "ni una llamada mas a alguien que va a oir colgar"
    assert captacion_voz._fila("ll_x")["resultado"] == "fallida"
    assert len(cuenta.correos) == 1 and "dejado de llamar" in cuenta.correos[0][0]
    assert "plan gratuito" in cuenta.correos[0][1]
    assert cuenta._avisados.get("gratis"), "el vigilante no repite el mismo aviso"


def test_en_una_llamada_de_prueba_no_se_manda_correo(al_descolgar, cuenta):
    client, lanzador, captacion_voz = al_descolgar
    client.post(captacion_voz.RUTA + "/twiml?llamada=ll_x", data={"AnsweredBy": "human"})
    assert cuenta.correos == [] and lanzador.config()["activo"] == 0


# --- Varias cuentas: pasar sola a la siguiente (Pablo, 24-sep-2026) -------------------

def _suscripcion(plan="creator", estado="active", usados=0, limite=300000, factura=False):
    return {"tier": plan, "status": estado, "character_count": usados, "character_limit": limite,
            "has_open_invoices": factura, "next_character_count_reset_unix": 1791011567}


class _Reserva:
    """Varias cuentas de ElevenLabs: cada clave con su suscripcion. Apunta lo que se borra."""

    def __init__(self, cuentas, agentes=None):
        self.cuentas, self.agentes, self.borrados = cuentas, agentes or {}, []

    def get(self, url, headers=None, **k):
        if "/v1/convai/agents/" in url:
            agente = url.rsplit("/", 1)[1]
            if agente in self.agentes:
                return _Respuesta(200, {"conversation_config": {"agent": {"prompt": {"tool_ids": self.agentes[agente]}}}})
            return _Respuesta(404)
        datos = self.cuentas[(headers or {})["xi-api-key"]]
        return _Respuesta(datos) if isinstance(datos, int) else _Respuesta(200, datos)

    def delete(self, url, headers=None, **k):
        self.borrados.append(((headers or {})["xi-api-key"], url.rsplit("/", 1)[1]))
        return _Respuesta(204)


@pytest.fixture()
def reserva(cuenta, monkeypatch, tmp_path):
    """Activa sin creditos; en la reserva, dos caidas y dos buenas. Agentes guardados en 'demo'."""
    from backend import appstate, settings

    monkeypatch.setattr(settings, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_agotada")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_agotada", "k_con_factura", "k_gratis", "k_buena", "k_otra"])
    monkeypatch.setitem(appstate.CONFIG_CLIENTES, "negocio_voz", {"voice": {"elevenlabs_agent_id": "agent_viejo"}})
    sincronizados = []
    monkeypatch.setattr(cuenta, "sincronizar_agentes", lambda: sincronizados.append(settings.ELEVENLABS_API_KEY)
                        or {"negocio_voz": "agent_nuevo"})
    api = _Reserva({
        "k_agotada": _suscripcion(usados=300000),
        "k_con_factura": _suscripcion(estado="past_due", factura=True),
        "k_gratis": _suscripcion(plan="free", limite=10000),
        "k_buena": _suscripcion(plan="starter", usados=4000, limite=40000),
        "k_otra": _suscripcion(plan="payg", limite=10000),
    }, agentes={"agent_viejo": ["tool_viejo"]})
    api.sincronizados = sincronizados
    return api


def test_si_la_activa_cae_pasa_a_la_primera_que_funciona(cuenta, reserva, tmp_path):
    from backend import settings

    assert cuenta.vigilar_una_vez(cliente=reserva) == "rotada"
    assert settings.ELEVENLABS_API_KEY == "k_buena", "se saltan la de factura pendiente y la gratuita"
    assert reserva.sincronizados == ["k_buena"], "los agentes se crean ya con la clave nueva"
    assert ("k_agotada", "agent_viejo") in reserva.borrados and ("k_agotada", "tool_viejo") in reserva.borrados, (
        "los agentes de la cuenta que se deja se borran de ella")
    guardado = (tmp_path / "elevenlabs_cuenta_activa.json").read_text(encoding="utf-8")
    assert cuenta.huella("k_buena") in guardado and "k_buena" not in guardado, "se guarda la huella, nunca la clave"
    assert len(cuenta.correos) == 1 and "otra cuenta" in cuenta.correos[0][0]
    assert not any(k in cuenta.correos[0][1] for k in ("k_agotada", "k_buena")), "las claves no van en el correo"


def test_la_cuenta_elegida_sobrevive_a_un_reinicio(cuenta, reserva, monkeypatch):
    from backend import settings

    cuenta.vigilar_una_vez(cliente=reserva)
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_agotada")  # lo que trae el .env al arrancar
    assert cuenta.aplicar_activa_guardada() == cuenta.huella("k_buena")
    assert settings.ELEVENLABS_API_KEY == "k_buena"


def test_sin_ninguna_que_funcione_no_se_cambia_y_se_avisa(cuenta, reserva):
    from backend import settings

    reserva.cuentas["k_buena"] = 401
    reserva.cuentas["k_otra"] = _suscripcion(estado="unpaid")
    assert cuenta.vigilar_una_vez(cliente=reserva) == "agotados"
    assert settings.ELEVENLABS_API_KEY == "k_agotada" and reserva.sincronizados == []
    assert "No queda ninguna otra cuenta" in cuenta.correos[0][1]


def test_la_preferida_vuelve_cuando_funciona(cuenta, reserva, monkeypatch):
    """Pablo: "usa la creator primero". Si se paga su factura, la voz vuelve a ella."""
    from backend import settings

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_buena")
    assert cuenta.vigilar_una_vez(cliente=reserva) == "", "con la preferida caida, se sigue en la que funciona"
    reserva.cuentas["k_con_factura"] = _suscripcion()  # factura pagada
    assert cuenta.vigilar_una_vez(cliente=reserva) == "rotada"
    assert settings.ELEVENLABS_API_KEY == "k_con_factura"


def test_el_panel_no_ensena_claves(cuenta, reserva):
    lista = cuenta.cuentas(cliente=reserva)
    assert [c["ok"] for c in lista] == [False, False, False, True, True]
    assert not any(k in str(lista) for k in ("k_agotada", "k_buena", "k_otra"))


def test_si_la_voz_falla_y_hay_otra_cuenta_sigue_llamando(al_descolgar, cuenta, monkeypatch):
    """La cuenta cayo con un negocio al telefono: pasa a otra y el lanzador sigue."""
    client, lanzador, captacion_voz = al_descolgar
    lanzador.guardar_config(activo=True)
    cambios = []
    monkeypatch.setattr(cuenta, "rotar", lambda motivo, **k: cambios.append(motivo) or {"rotada": True})
    client.post(captacion_voz.RUTA + "/twiml?llamada=ll_x", data={"AnsweredBy": "human"})
    assert cambios and "descolgo" in cambios[0]
    assert lanzador.config()["activo"] == 1, "con otra cuenta que funciona, se sigue llamando"
    assert captacion_voz._fila("ll_x")["resultado"] == "fallida"
