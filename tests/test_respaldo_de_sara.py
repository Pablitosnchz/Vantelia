# -*- coding: utf-8 -*-
"""Lo que Sara dice que hara y no hace lo hace el servidor al terminar la llamada.

POR QUE EXISTE
--------------
28-sep-2026, llamada de prueba de Pablo: «es José, mañana sobre las 8» y un correo dictado;
Sara dijo «te mando ahora mismo un correo» y no llamo a ninguna herramienta. Con el
analisis de ElevenLabs al colgar, el servidor manda la informacion y apunta a quien decide.
Una prueba por fila de la tabla de fallos de docs/PLAN_RESPALDO_DE_SARA.md: como mucho un
envio por llamada, y ante la duda no se manda.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401
from test_captacion_voz import _Falso, captacion, envios  # noqa: F401
from test_transcripciones_llamadas import _conversacion, llamada  # noqa: F401


def _analisis(conversation_id="conv_1", **valores):
    datos = dict({"interlocutor": "empleado", "desenlace": "interesado", "responsable_nombre": "José",
                  "responsable_cuando": "mañana sobre las 8", "quiere_informacion": True,
                  "email_para_informacion": "jose@pelu.es"}, **valores)
    return _conversacion(conversation_id, data_collection_results={k: {"value": v} for k, v in datos.items()})


def _correos(envios):  # noqa: F811
    return [str(m["To"]) for m in envios["email"]]


def test_si_lo_acepto_y_sara_no_lo_mando_se_manda_una_sola_vez(llamada, envios):  # noqa: F811
    llamada_id, transcripciones = llamada
    transcripciones.guardar(_analisis(), "aviso")
    transcripciones.guardar(_analisis(), "recogida")  # el analisis llega otra vez
    assert _correos(envios) == ["jose@pelu.es"]
    fila = transcripciones.captacion_voz._fila(llamada_id)
    assert fila["resultado"] == "interesado" and "respaldo" in fila["notas"].lower()
    assert len(envios["avisos"]) == 1, "Pablo se entera, y sabe que fue de respaldo"


def test_si_sara_ya_lo_mando_no_se_repite(llamada, envios, captacion):  # noqa: F811
    llamada_id, transcripciones = llamada
    captacion.herramienta("enviar_informacion", {"_llamada": llamada_id, "email": "jose@pelu.es"})
    transcripciones.guardar(_analisis(), "aviso")
    assert _correos(envios) == ["jose@pelu.es"]


def test_si_el_analisis_llega_mientras_la_herramienta_manda_sale_un_correo(llamada, envios, monkeypatch):  # noqa: F811
    """Astra, 28-sep: la herramienta tarda (timeout de ElevenLabs) y el analisis llega a
    mitad del envio. Sin sello compartido ANTES de mandar, salian dos correos."""
    from backend import outreach

    llamada_id, transcripciones = llamada
    anotar = outreach._outreach_send_email_object

    def mandar_y_que_llegue_el_analisis(mensaje):
        if not envios["email"]:
            transcripciones.guardar(_analisis(), "aviso")  # el respaldo, en mitad del envio
        anotar(mensaje)

    monkeypatch.setattr(outreach, "_outreach_send_email_object", mandar_y_que_llegue_el_analisis)
    transcripciones.captacion_voz.herramienta("enviar_informacion", {"_llamada": llamada_id, "email": "jose@pelu.es"})
    assert _correos(envios) == ["jose@pelu.es"]
    assert transcripciones.captacion_voz._fila(llamada_id)["informacion"] == "enviada"


def test_si_el_respaldo_ya_lo_mando_la_herramienta_no_repite(llamada, envios, captacion):  # noqa: F811
    llamada_id, transcripciones = llamada
    transcripciones.guardar(_analisis(), "aviso")
    r = captacion.herramienta("enviar_informacion", {"_llamada": llamada_id, "email": "jose@pelu.es"})
    assert r["ok"] is True and "Ya se le ha mandado" in r["mensaje"]
    assert _correos(envios) == ["jose@pelu.es"]


def test_si_sara_llama_dos_veces_a_la_herramienta_sale_un_correo(llamada, envios, captacion):  # noqa: F811
    llamada_id, _ = llamada
    for _vez in range(2):
        captacion.herramienta("enviar_informacion", {"_llamada": llamada_id, "email": "jose@pelu.es"})
    assert _correos(envios) == ["jose@pelu.es"]
    assert len(envios["avisos"]) == 1


@pytest.mark.parametrize("cambio", [
    {"quiere_informacion": False},
    {"quiere_informacion": "no se"},
    {"desenlace": "rechazo"},
    {"desenlace": "persona_equivocada"},
    {"desenlace": "buzon"},
])
def test_ante_la_duda_o_un_no_no_se_manda(llamada, envios, cambio):  # noqa: F811
    _, transcripciones = llamada
    transcripciones.guardar(_analisis(**cambio), "aviso")
    assert envios["email"] == [] and envios["sms"] == []


def test_a_quien_pidio_no_mas_llamadas_no_se_le_escribe(llamada, envios, captacion):  # noqa: F811
    llamada_id, transcripciones = llamada
    captacion.herramienta("no_volver_a_llamar", {"_llamada": llamada_id, "motivo": "no llameis"})
    transcripciones.guardar(_analisis(), "aviso")
    assert envios["email"] == []


def test_a_un_correo_dado_de_baja_no_se_le_escribe(llamada, envios, captacion):  # noqa: F811
    _, transcripciones = llamada
    with captacion._db() as conn:
        conn.execute("INSERT INTO suppressions (email, reason, added_at) VALUES (?,?,?)",
                     ("jose@pelu.es", "BAJA", "x"))
        conn.commit()
    transcripciones.guardar(_analisis(), "aviso")
    assert envios["email"] == []


def test_si_quedo_en_volver_a_llamar_no_se_contradice(llamada, envios, captacion):  # noqa: F811
    llamada_id, transcripciones = llamada
    captacion.herramienta("volver_a_llamar", {"_llamada": llamada_id, "cuando": "el jueves"})
    transcripciones.guardar(_analisis(), "aviso")
    assert envios["email"] == []


def test_un_fijo_sin_ningun_correo_no_manda_nada(captacion, envios):  # noqa: F811
    from backend import transcripciones_llamadas

    hecho = captacion.llamar("911111112", "Pelu Sin Correo", "peluqueria", "", origen="auto", cliente=_Falso())
    captacion._actualizar(hecho["llamada"], estado="terminada", conversation_id="conv_2")
    transcripciones_llamadas.guardar(_analisis("conv_2", email_para_informacion="jose arroba"), "aviso")
    assert envios["email"] == [] and envios["sms"] == []
    assert captacion._fila(hecho["llamada"])["resultado"] == "", "sin sello: no se ha mandado nada"


def test_quien_decide_y_cuando_rellenan_sin_pisar(llamada, envios, captacion):  # noqa: F811
    llamada_id, transcripciones = llamada
    transcripciones.guardar(_analisis(quiere_informacion=False), "aviso")
    fila = captacion._fila(llamada_id)
    assert (fila["responsable_nombre"], fila["responsable_cuando"]) == ("José", "mañana sobre las 8")

    captacion._actualizar(llamada_id, responsable_cuando="los martes por la tarde")
    transcripciones.guardar(_analisis(quiere_informacion=False, responsable_cuando="nunca"), "recogida")
    assert captacion._fila(llamada_id)["responsable_cuando"] == "los martes por la tarde"


def test_el_analisis_pide_lo_que_hace_falta_y_el_guion_lo_dice(captacion):  # noqa: F811
    agente = captacion.agente_de_captacion("https://app.test")
    datos = agente["platform_settings"]["data_collection"]
    assert {"quiere_informacion", "email_para_informacion", "responsable_cuando"} <= set(datos)
    guion = agente["conversation_config"]["agent"]["prompt"]["prompt"]
    assert "Nunca digas que se lo mandas sin haber usado antes `enviar_informacion`" in guion
    # Pablo, 28-sep: demo corta, y lo del propietario en su propio turno.
    assert "NO le preguntes por separado el servicio, el dia ni el nombre" in guion
    assert "Esa pregunta va SOLA, en su propio turno" in guion
