# -*- coding: utf-8 -*-
"""Sara atiende las llamadas que entran al 91 (casi siempre, devolver una llamada suya).

POR QUE EXISTE
--------------
Pablo, 30-sep-2026: "si llaman de vuelta, que llamen al asistente y que atienda Sara", y
nunca desviarlo a su movil. El puente pasa la entrante a ElevenLabs con el numero de quien
llama (X-Caller-ID -> system__caller_id). Revision de Astra: una entrante no trae el id de la
llamada, asi que sin ficha propia las herramientas respondian "No encuentro esta llamada".
Plan y tabla de fallos: docs/PLAN_SARA_ENTRANTES.md.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401
from test_captacion_voz import _Falso, captacion, envios  # noqa: F401
from test_sara_por_sip import sip  # noqa: F401
from test_segunda_oportunidad import MARTES_1630, _llamada, _negocio, _ronda, so  # noqa: F401


def _entrante(**cuerpo):
    return dict({"_llamada": "", "_quien": "+34675802001", "_conversacion": "conv_in_1"}, **cuerpo)


def test_las_herramientas_llevan_quien_llama_y_la_entrante_tiene_su_saludo(captacion):  # noqa: F811
    agente = captacion.agente_de_captacion("https://app.test")["conversation_config"]["agent"]
    enviar = [t for t in agente["prompt"]["tools"] if t["name"] == "enviar_informacion"][0]
    campos = enviar["api_schema"]["request_body_schema"]["properties"]
    assert campos["_quien"]["dynamic_variable"] == "system__caller_id"
    assert campos["_conversacion"]["dynamic_variable"] == "system__conversation_id"
    # Si nadie manda variables (solo pasa en una entrante), saluda como quien coge el telefono.
    por_defecto = agente["dynamic_variables"]["dynamic_variable_placeholders"]
    assert (por_defecto["saludo"], por_defecto["sentido"]) == (captacion.SALUDO_ENTRANTE, "entrante")
    assert "inteligencia artificial" in captacion.SALUDO_ENTRANTE, "tambien al coger: que es una IA"
    assert "SI TE LLAMAN ELLOS" in agente["prompt"]["prompt"] and "{{sentido}}" in agente["prompt"]["prompt"]
    # Las salientes mandan siempre lo suyo.
    hecho = captacion.llamar("911111111", "Pelu Marta", "peluqueria", "", origen="auto", cliente=_Falso())
    variables = captacion._variables(captacion._fila(hecho["llamada"]))
    assert (variables["sentido"], variables["saludo"]) == ("saliente", captacion.APERTURA)


def test_quien_devuelve_la_llamada_recibe_la_informacion(captacion, envios):  # noqa: F811
    """Le llamamos, no lo cogio, devuelve la llamada y pide la informacion: le llega el SMS y
    la ficha es la del negocio al que llamamos."""
    captacion.llamar("675802001", "Pelu Movil", "peluqueria", "pelu@movil.es", origen="auto", cliente=_Falso())
    r = captacion.herramienta("enviar_informacion", _entrante())
    assert r["ok"] is True and "SMS" in r["mensaje"]
    assert envios["sms"] and envios["sms"][0][0] == "+34675802001"
    with captacion._db() as conn:
        filas = conn.execute("SELECT origen, negocio, prospecto, conversation_id, resultado FROM llamadas_voz "
                             "WHERE origen='entrante'").fetchall()
    assert [tuple(f) for f in filas] == [("entrante", "Pelu Movil", "pelu@movil.es", "conv_in_1", "interesado")]


def test_una_entrante_es_una_sola_ficha(captacion, envios):  # noqa: F811
    captacion.herramienta("anotar_responsable", _entrante(interlocutor="empleado", nombre="Marta"))
    captacion.herramienta("pasar_a_pablo", _entrante(cuando="por la tarde"))
    captacion.herramienta("volver_a_llamar", _entrante(_conversacion="", cuando="mañana"))  # sin conversacion: por numero
    with captacion._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llamadas_voz WHERE origen='entrante'").fetchone()[0] == 1


def test_dos_llamadas_del_mismo_numero_son_dos_fichas(captacion, envios):  # noqa: F811
    """Astra, 30-sep: llamaba dos veces en media hora y la segunda reutilizaba la primera ficha
    (pisaba su transcripcion y su sello de envio: no le llegaba lo que pidio)."""
    captacion.herramienta("enviar_informacion", _entrante(_conversacion="conv_primera"))
    r = captacion.herramienta("enviar_informacion", _entrante(_conversacion="conv_segunda"))
    assert r["ok"] is True and "Ya se le ha mandado" not in r["mensaje"]
    with captacion._db() as conn:
        conversaciones = sorted(f[0] for f in conn.execute(
            "SELECT conversation_id FROM llamadas_voz WHERE origen='entrante'"))
    assert conversaciones == ["conv_primera", "conv_segunda"]


def test_sin_numero_ni_conversacion_no_se_inventa_nada(captacion):  # noqa: F811
    r = captacion.herramienta("pasar_a_pablo", _entrante(_quien="", _conversacion=""))
    assert r["ok"] is False and "No encuentro esta llamada" in r["error"]


def test_una_saliente_con_id_equivocado_no_se_cuela_como_entrante(captacion):  # noqa: F811
    r = captacion.herramienta("pasar_a_pablo", _entrante(_llamada="ll_que_no_existe"))
    assert r["ok"] is False
    with captacion._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llamadas_voz WHERE origen='entrante'").fetchone()[0] == 0


def _conversacion_entrante(agente="agent_sara", direccion="inbound", conversation_id="conv_in_9"):
    return {"conversation_id": conversation_id, "status": "done", "agent_id": agente,
            "transcript": [{"role": "agent", "message": "Hola, soy Sara.", "time_in_call_secs": 0},
                           {"role": "user", "message": "Me habeis llamado antes", "time_in_call_secs": 3}],
            "metadata": {"call_duration_secs": 20, "termination_reason": "end_call tool",
                         "phone_call": {"direction": direccion, "external_number": "+34911234567"}},
            "analysis": {"data_collection_results": {"interlocutor": {"value": "empleado"}}}}


def test_la_entrante_sin_herramientas_llega_igual_al_panel(sip):  # noqa: F811
    from backend import transcripciones_llamadas

    llamada_id = transcripciones_llamadas.guardar(_conversacion_entrante(), "aviso")
    assert llamada_id
    fila = sip._fila(llamada_id)
    assert (fila["origen"], fila["telefono"], fila["conversation_id"]) == ("entrante", "+34911234567", "conv_in_9")
    with transcripciones_llamadas._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llamadas_transcripcion WHERE llamada_id=?",
                            (llamada_id,)).fetchone()[0] == 1


@pytest.mark.parametrize("cambio", [{"agente": "agent_de_otro"}, {"direccion": "outbound"}])
def test_una_conversacion_ajena_se_sigue_ignorando(sip, cambio):  # noqa: F811
    from backend import transcripciones_llamadas

    assert transcripciones_llamadas.guardar(_conversacion_entrante(**cambio), "aviso") is None


def test_a_quien_nos_devolvio_la_llamada_no_le_llega_la_segunda_oportunidad(so, captacion):  # noqa: F811
    _negocio()
    _llamada(captacion, desenlace="colgo_al_principio")
    assert [e["prospecto"] for e in so.elegibles(MARTES_1630)] == ["hola@pelu.es"], "control: sin la entrante, si"
    captacion._fila_entrante("+34911111111", "conv_devuelta")
    registro, _ = _ronda(so, MARTES_1630)
    assert registro == []
