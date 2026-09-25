# -*- coding: utf-8 -*-
"""Las transcripciones de las llamadas de Sara quedan guardadas para analizarlas.

POR QUE EXISTE
--------------
Pablo (25-sep-2026) quiere la transcripcion de cada llamada para analizarlas despues.
Llegan por el aviso de fin de llamada de ElevenLabs (firmado) o por la recogida de
respaldo, que prueba todas las claves de la reserva: tras una rotacion de cuenta, la
conversacion sigue en la cuenta vieja. Lo que ElevenLabs clasifica al terminar
(interlocutor, desenlace...) rellena lo que Sara no apunto, y un "rechazo" impide la
rellamada dirigida (backend/transcripciones_llamadas.py).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_captacion_voz import _Falso, _Respuesta, captacion  # noqa: F401

SECRETO = "secreto-del-aviso"
CABECERAS_ADMIN = {"Authorization": "Bearer test-admin-token"}


def _conversacion(conversation_id="conv_1", **analisis):
    return {
        "conversation_id": conversation_id, "status": "done",
        "transcript": [
            {"role": "agent", "message": "Hola, buenas. Soy Sara, una asistente virtual de Vantelia.",
             "time_in_call_secs": 0},
            {"role": "user", "message": "Si, digame", "time_in_call_secs": 4},
            {"role": "agent", "message": "", "time_in_call_secs": 20,
             "tool_calls": [{"tool_name": "anotar_responsable"}]},
        ],
        "metadata": {"call_duration_secs": 42, "termination_reason": "end_call tool"},
        "analysis": dict({"transcript_summary": "Cogio una empleada; la duena esta por las tardes.",
                          "call_successful": "success",
                          "data_collection_results": {"interlocutor": {"value": "empleado"},
                                                      "desenlace": {"value": "ocupado_sin_rechazo"},
                                                      "responsable_nombre": {"value": "Marta"}}}, **analisis),
    }


@pytest.fixture()
def llamada(captacion):  # noqa: F811
    """Una llamada terminada, con su conversacion de ElevenLabs."""
    from backend import transcripciones_llamadas

    hecho = captacion.llamar("911111111", "Pelu Marta", "peluqueria", "hola@pelu.es", origen="auto", cliente=_Falso())
    captacion._actualizar(hecho["llamada"], estado="terminada", conversation_id="conv_1")
    with captacion._db() as conn:  # hace 20 minutos: ya se puede recoger
        antes = (captacion.timeutils._utc_now() - timedelta(minutes=20)).isoformat(timespec="seconds")
        conn.execute("UPDATE llamadas_voz SET actualizada=?", (antes,))
        conn.commit()
    return hecho["llamada"], transcripciones_llamadas


# --- Firma del aviso -------------------------------------------------------------------

def _firma(cuerpo: bytes, secreto=SECRETO, marca=None):
    marca = int(marca if marca is not None else time.time())
    v0 = hmac.new(secreto.encode(), str(marca).encode() + b"." + cuerpo, hashlib.sha256).hexdigest()
    return "t=%d,v0=%s" % (marca, v0)


def test_la_firma_del_aviso(captacion):  # noqa: F811
    from backend import transcripciones_llamadas as t

    cuerpo = b'{"type":"post_call_transcription"}'
    assert t.firma_valida(cuerpo, _firma(cuerpo), SECRETO)
    assert not t.firma_valida(cuerpo + b" ", _firma(cuerpo), SECRETO), "cuerpo cambiado"
    assert not t.firma_valida(cuerpo, _firma(cuerpo, secreto="otro"), SECRETO)
    assert not t.firma_valida(cuerpo, _firma(cuerpo, marca=time.time() - 3 * 3600), SECRETO), "caducada"
    assert not t.firma_valida(cuerpo, "basura", SECRETO) and not t.firma_valida(cuerpo, _firma(cuerpo), "")


# --- El aviso de fin de llamada -----------------------------------------------------

def _avisar(client, cuerpo_dict, firma=None):  # noqa: F811
    cuerpo = json.dumps(cuerpo_dict).encode()
    return client.post("/voice/el-captacion/fin", content=cuerpo,
                       headers={"ElevenLabs-Signature": firma or _firma(cuerpo), "Content-Type": "application/json"})


def test_sin_secreto_el_aviso_no_se_acepta(client, llamada):  # noqa: F811
    assert _avisar(client, {"type": "post_call_transcription", "data": _conversacion()}).status_code == 503


def test_el_aviso_guarda_la_transcripcion(client, llamada, monkeypatch):  # noqa: F811
    from backend import settings

    llamada_id, t = llamada
    monkeypatch.setattr(settings, "ELEVENLABS_WEBHOOK_SECRET", SECRETO)
    assert _avisar(client, {"type": "post_call_transcription", "data": _conversacion()}, firma="t=1,v0=mala"
                   ).status_code == 401
    r = _avisar(client, {"type": "post_call_transcription", "data": _conversacion()})
    assert r.status_code == 200 and r.json()["llamada"] == llamada_id
    guardada = t.de_la_llamada(llamada_id)
    assert [x["quien"] for x in guardada["turnos"]] == ["agente", "persona", "agente"]
    assert guardada["turnos"][2]["herramientas"] == ["anotar_responsable"]
    assert guardada["duracion"] == 42 and "duena" in guardada["resumen"]
    assert guardada["analisis"]["data_collection_results"]["desenlace"]["value"] == "ocupado_sin_rechazo"
    # Idempotente: el mismo aviso otra vez no duplica.
    _avisar(client, {"type": "post_call_transcription", "data": _conversacion()})
    with t._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llamadas_transcripcion").fetchone()[0] == 1


def test_avisos_que_no_son_de_nuestras_llamadas_se_ignoran(client, llamada, monkeypatch):  # noqa: F811
    from backend import settings

    monkeypatch.setattr(settings, "ELEVENLABS_WEBHOOK_SECRET", SECRETO)
    assert _avisar(client, {"type": "post_call_transcription", "data": _conversacion("conv_de_otro")}
                   ).json()["llamada"] == ""
    assert _avisar(client, {"type": "post_call_audio", "data": {}}).json()["ignorado"] == "post_call_audio"


# --- Lo clasificado rellena lo que Sara no apunto ------------------------------------

def test_la_clasificacion_rellena_sin_pisar(llamada, captacion):  # noqa: F811
    llamada_id, t = llamada
    t.guardar(_conversacion(), "aviso")
    fila = captacion._fila(llamada_id)
    assert fila["interlocutor"] == "empleado" and fila["responsable_nombre"] == "Marta"
    captacion._actualizar(llamada_id, interlocutor="duena_o_encargada", responsable_nombre="Ana")
    t.guardar(_conversacion(), "aviso")
    fila = captacion._fila(llamada_id)
    assert fila["interlocutor"] == "duena_o_encargada" and fila["responsable_nombre"] == "Ana", (
        "lo que apunto la herramienta en la llamada manda")


def test_un_rechazo_transcrito_impide_la_rellamada(llamada, captacion):  # noqa: F811
    from datetime import datetime, timezone

    from backend import lanzador_llamadas

    llamada_id, t = llamada
    captacion._actualizar(llamada_id, interlocutor="empleado", responsable_nombre="Marta",
                          responsable_cuando="por las tardes")
    with captacion._db() as conn:
        conn.execute("UPDATE llamadas_voz SET creada='2026-09-28T08:00:00+00:00'")
        conn.commit()
    martes_tarde = datetime(2026, 9, 29, 14, 30, tzinfo=timezone.utc)
    assert len(lanzador_llamadas.rellamadas_dirigidas(martes_tarde)) == 1
    t.guardar(_conversacion(data_collection_results={"desenlace": {"value": "rechazo"}}), "aviso")
    assert lanzador_llamadas.rellamadas_dirigidas(martes_tarde) == []


# --- Recogida de respaldo, en cualquier cuenta de la reserva --------------------------

class _ApiConversaciones:
    """Solo la cuenta 'k_vieja' tiene la conversacion (se hizo antes de rotar)."""

    def __init__(self, conversacion, estado="done"):
        self.conversacion, self.estado, self.pedidas = conversacion, estado, []

    def get(self, url, headers=None, **k):
        self.pedidas.append(headers["xi-api-key"])
        if headers["xi-api-key"] == "k_vieja":
            return _Respuesta(200, dict(self.conversacion, status=self.estado))
        return _Respuesta(404, {})

    def close(self):
        pass


def test_la_recogida_busca_en_todas_las_cuentas(llamada, monkeypatch):  # noqa: F811
    from backend import settings

    llamada_id, t = llamada
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "k_nueva")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_nueva", "k_vieja"])
    api = _ApiConversaciones(_conversacion())
    assert t.recoger_pendientes(cliente=api) == 1
    assert api.pedidas == ["k_nueva", "k_vieja"] and t.de_la_llamada(llamada_id) is not None
    assert t.recoger_pendientes(cliente=api) == 0, "lo ya guardado no se vuelve a pedir"


def test_no_se_recoge_lo_que_aun_esta_en_curso(llamada, captacion, monkeypatch):  # noqa: F811
    from backend import settings

    llamada_id, t = llamada
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEYS", ["k_vieja"])
    assert t.recoger_pendientes(cliente=_ApiConversaciones(_conversacion(), estado="processing")) == 0
    captacion._actualizar(llamada_id, notas="acaba de colgar")  # actualizada ahora: hace menos de 10 min
    assert t.recoger_pendientes(cliente=_ApiConversaciones(_conversacion())) == 0


# --- Leer y exportar -----------------------------------------------------------------------

def test_el_panel_lee_lo_guardado_sin_llamar_a_elevenlabs(client, llamada):  # noqa: F811
    llamada_id, t = llamada
    t.guardar(_conversacion(), "aviso")

    class _NoLlames:
        def get(self, *a, **k):
            raise AssertionError("ya estaba guardada")

    assert t.leer(llamada_id, cliente=_NoLlames())["duracion"] == 42
    r = client.get("/admin/captacion/llamadas/%s/transcripcion" % llamada_id, headers=CABECERAS_ADMIN)
    assert r.status_code == 200 and r.json()["turnos"][0]["quien"] == "agente"


def test_se_exportan_todas_las_llamadas_para_analizarlas(client, llamada, captacion, monkeypatch):  # noqa: F811
    llamada_id, t = llamada
    t.guardar(_conversacion(), "aviso")
    captacion.llamar("912222222", "Otro Salon", origen="auto", cliente=_Falso())  # sin transcripcion
    monkeypatch.setattr(t, "recoger_pendientes", lambda **k: 0)
    assert client.get("/admin/captacion/llamadas/transcripciones.jsonl").status_code in (401, 403)
    r = client.get("/admin/captacion/llamadas/transcripciones.jsonl", headers=CABECERAS_ADMIN)
    lineas = [json.loads(x) for x in r.text.splitlines() if x.strip()]
    assert r.status_code == 200 and len(lineas) == 2
    con = next(x for x in lineas if x["id"] == llamada_id)
    assert con["transcripcion"][1]["texto"] == "Si, digame" and con["analisis"]["call_successful"] == "success"
    assert con["interlocutor"] == "empleado"
