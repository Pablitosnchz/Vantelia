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

from test_booking_exhaustive import api_module  # noqa: F401
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


def _creator(usados=0, limite=300000, plan="creator"):
    return _Api(200, tier=plan, status="past_due", character_count=usados, character_limit=limite,
                next_character_count_reset_unix=1791011567)


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
