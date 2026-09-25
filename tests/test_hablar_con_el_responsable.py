# -*- coding: utf-8 -*-
"""Sara tiene que saber si habla con quien decide y, si no, llegar a esa persona.

POR QUE EXISTE
--------------
Idea de Pablo (25-sep-2026, docs/PLAN_HABLAR_CON_EL_RESPONSABLE.md): en una peluqueria
suele coger el telefono quien esta en el mostrador, no quien decide. Despues del gancho
Sara pregunta, una vez, si habla con quien lleva el negocio; si no, pregunta por esa
persona: o se pone (y Sara se vuelve a presentar entera, porque la ley lo exige a quien
recibe la llamada) o le dan su nombre y cuando esta, y el lanzador vuelve a llamar UNA
vez al fijo del negocio en esa franja. Un movil que de un empleado nunca se usa para
llamar solos.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_captacion_voz import _Falso, captacion  # noqa: F401
from test_lanzador_llamadas import MARTES_10_30, _prospecto, lanzador  # noqa: F401

MARTES_16_30 = datetime(2026, 9, 29, 14, 30, tzinfo=timezone.utc)  # 16:30 en Madrid


# --- El guion y la agente -----------------------------------------------------------

def test_el_guion_pregunta_por_quien_decide_despues_del_gancho(captacion):  # noqa: F811
    agente = captacion.agente_de_captacion("https://app.test")
    guion = agente["conversation_config"]["agent"]["prompt"]["prompt"]
    assert guion.index("el gancho") < guion.index("QUIEN DECIDE"), "la pregunta va despues del gancho"
    assert "UNA sola vez" in guion and "No lo preguntes si ya lo ha dicho" in guion
    assert "PRESENTATE ENTERA OTRA VEZ" in guion, "a quien se pone despues hay que decirle que es una IA"
    assert "Nunca pidas el movil personal" in guion
    nombres = {t["name"] for t in agente["conversation_config"]["agent"]["prompt"]["tools"]}
    assert {"anotar_responsable", "skip_turn"} <= nombres
    assert agente["conversation_config"]["turn"]["silence_end_call_timeout"] > 0


def test_el_saludo_pregunta_por_el_negocio_o_por_quien_decide(captacion):  # noqa: F811
    agente = captacion.agente_de_captacion("https://app.test")["conversation_config"]["agent"]
    assert "{{a_quien}}" in agente["first_message"] and "asistente virtual" in agente["first_message"]
    variables = agente["dynamic_variables"]["dynamic_variable_placeholders"]
    assert {"a_quien", "responsable"} <= set(variables)


def test_elevenlabs_clasifica_cada_llamada_al_terminar(captacion):  # noqa: F811
    datos = captacion.agente_de_captacion("https://app.test")["platform_settings"]["data_collection"]
    assert {"interlocutor", "desenlace", "escucho_la_demo", "responsable_nombre"} <= set(datos)
    assert "ocupado_sin_rechazo" in datos["desenlace"]["description"]


# --- La herramienta ------------------------------------------------------------------

def _una_llamada(captacion, **campos):
    falso = _Falso()
    hecho = captacion.llamar("911111111", "Pelu Marta", "peluqueria", "hola@pelu.es", origen="auto", cliente=falso)
    if campos:
        captacion._actualizar(hecho["llamada"], **campos)
    return hecho["llamada"]


def test_anotar_responsable_guarda_quien_decide(captacion):  # noqa: F811
    llamada = _una_llamada(captacion)
    r = captacion.herramienta("anotar_responsable", {
        captacion.CAMPO_LLAMADA: llamada, "interlocutor": "empleado", "nombre": "Marta",
        "cuando": "por las tardes", "email": "Marta@Pelu.es", "telefono": "675 111 222"})
    fila = captacion._fila(llamada)
    assert r["ok"] and fila["interlocutor"] == "empleado" and fila["responsable_nombre"] == "Marta"
    assert fila["responsable_cuando"] == "por las tardes" and fila["responsable_email"] == "marta@pelu.es"
    assert "+34675111222" in fila["responsable_nota"] and "no se usa para llamar" in fila["responsable_nota"]


def test_datos_raros_no_se_cuelan(captacion):  # noqa: F811
    llamada = _una_llamada(captacion)
    captacion.herramienta("anotar_responsable", {
        captacion.CAMPO_LLAMADA: llamada, "interlocutor": "el jefe supremo", "email": "no-es-un-email"})
    fila = captacion._fila(llamada)
    assert fila["interlocutor"] == "no_se_sabe" and fila["responsable_email"] == ""


def test_si_se_pone_al_telefono_la_herramienta_le_recuerda_presentarse(captacion):  # noqa: F811
    llamada = _una_llamada(captacion)
    r = captacion.herramienta("anotar_responsable", {
        captacion.CAMPO_LLAMADA: llamada, "interlocutor": "empleado", "se_pone_ahora": True})
    assert "espera" in r["mensaje"] and "presentate entera" in r["mensaje"]
    assert captacion._fila(llamada)["se_pone_ahora"] == 1


def test_al_descolgar_pregunta_por_el_negocio_y_en_la_rellamada_por_la_persona(captacion):  # noqa: F811
    from backend import clients

    captacion_config = {"voice": {captacion.CLAVE_AGENTE: "agent_sara"}}
    original = clients._get_client_config
    clients._get_client_config = lambda cid: captacion_config if cid == captacion.TENANT else original(cid)
    try:
        variables = []

        class _Registro(_Falso):
            def post(self, url, **k):
                if "register-call" in url:
                    variables.append(k["json"]["conversation_initiation_client_data"]["dynamic_variables"])
                return super().post(url, **k)

        normal = captacion.llamar("911111111", "Pelu Marta", origen="auto", cliente=_Registro())["llamada"]
        captacion.twiml_al_descolgar(normal, "human", "+34910000000", "+34911111111", cliente=_Registro())
        dirigida = captacion.llamar("911111111", "Pelu Marta", origen="auto", responsable="Marta",
                                    rellamada_de=normal, cliente=_Registro())["llamada"]
        captacion.twiml_al_descolgar(dirigida, "human", "+34910000000", "+34911111111", cliente=_Registro())
    finally:
        clients._get_client_config = original
    assert variables[0]["a_quien"] == "Pelu Marta"
    assert variables[1]["a_quien"] == "Marta" and variables[1]["responsable"] == "Marta"


# --- La rellamada dirigida ---------------------------------------------------------

class _Marcador:
    def __init__(self, lanzador, ahora):
        self.lanzador, self.ahora, self.llamadas = lanzador, ahora, []

    def __call__(self, telefono, negocio, sector, prospecto, origen="manual", **dirigida):
        self.llamadas.append(dict(dirigida, telefono=telefono))
        with self.lanzador._db() as conn:
            conn.execute("INSERT INTO llamadas_voz (id, telefono, estado, origen, rellamada_de, responsable_nombre, "
                         "creada, actualizada) VALUES (?,?,?,?,?,?,?,?)",
                         ("ll_nueva_%d" % len(self.llamadas), telefono, "marcando", origen,
                          dirigida.get("rellamada_de", ""), dirigida.get("responsable", ""),
                          self.lanzador._iso(self.ahora), self.lanzador._iso(self.ahora)))
            conn.commit()
        return {"ok": True, "llamada": "ll_nueva_%d" % len(self.llamadas)}


def _hablo_con_un_empleado(lanzador, cuando="por las tardes", telefono="+34911111111", hace_horas=26, **mas):
    creada = lanzador._iso(MARTES_16_30 - timedelta(hours=hace_horas))
    campos = dict({"interlocutor": "empleado", "responsable_nombre": "Marta", "responsable_cuando": cuando,
                   "resultado": "", "conversation_id": "conv_1"}, **mas)
    with lanzador._db() as conn:
        conn.execute("INSERT INTO llamadas_voz (id, telefono, negocio, prospecto, estado, origen, creada, actualizada) "
                     "VALUES ('ll_original', ?, 'Pelu Marta', 'hola@pelu.es', 'terminada', 'auto', ?, ?)",
                     (telefono, creada, creada))
        conn.execute("UPDATE llamadas_voz SET %s WHERE id='ll_original'" % ", ".join("%s=?" % c for c in campos),
                     tuple(campos.values()))
        conn.commit()


def _ronda(lanzador, ahora, en_robinson=()):
    marcador = _Marcador(lanzador, ahora)
    lanzador.ronda(ahora=ahora, llamar=marcador, consultar=lambda ns: {n: n in en_robinson for n in ns})
    return marcador


def test_se_vuelve_a_llamar_a_quien_decide_en_su_franja(lanzador):  # noqa: F811
    lanzador.guardar_config(activo=True)
    _prospecto(lanzador, "frio@pelu.es", "912222222")  # un negocio en frio compite por la llamada
    _hablo_con_un_empleado(lanzador, cuando="por las tardes")
    marcador = _ronda(lanzador, MARTES_16_30)
    assert marcador.llamadas[0] == {"telefono": "+34911111111", "responsable": "Marta", "rellamada_de": "ll_original"}, (
        "la rellamada a quien decide va antes que las llamadas en frio")


def test_por_la_manana_no_se_llama_a_quien_esta_por_las_tardes(lanzador):  # noqa: F811
    _hablo_con_un_empleado(lanzador, cuando="por las tardes", hace_horas=30)
    assert lanzador.rellamadas_dirigidas(MARTES_10_30) == []
    assert len(lanzador.rellamadas_dirigidas(MARTES_16_30)) == 1


def test_solo_una_rellamada_por_negocio(lanzador):  # noqa: F811
    lanzador.guardar_config(activo=True, minutos_entre=5)
    _hablo_con_un_empleado(lanzador)
    assert len(_ronda(lanzador, MARTES_16_30).llamadas) == 1
    with lanzador._db() as conn:
        conn.execute("UPDATE llamadas_voz SET estado='terminada'")
        conn.commit()
    assert lanzador.rellamadas_dirigidas(MARTES_16_30 + timedelta(minutes=30)) == []


@pytest.mark.parametrize("variante", [
    {"resultado": "no_llamar"}, {"resultado": "interesado"}, {"interlocutor": "duena_o_encargada"},
    {"responsable_nombre": ""},
])
def test_no_se_rellama_si_no_toca(lanzador, variante):  # noqa: F811
    _hablo_con_un_empleado(lanzador, **variante)
    assert lanzador.rellamadas_dirigidas(MARTES_16_30) == []


def test_nunca_a_un_movil(lanzador):  # noqa: F811
    _hablo_con_un_empleado(lanzador, telefono="+34675111222")
    assert lanzador.rellamadas_dirigidas(MARTES_16_30) == []


def test_si_la_transcripcion_dice_rechazo_no_se_rellama(lanzador):  # noqa: F811
    _hablo_con_un_empleado(lanzador)
    with lanzador._db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS llamadas_transcripcion (llamada_id TEXT PRIMARY KEY, analisis_json TEXT)")
        conn.execute("INSERT INTO llamadas_transcripcion VALUES ('ll_original', ?)",
                     (json.dumps({"data_collection_results": {"desenlace": {"value": "rechazo"}}}),))
        conn.commit()
    assert lanzador.rellamadas_dirigidas(MARTES_16_30) == []


def test_manana_suelto_es_otro_dia(lanzador):  # noqa: F811
    _hablo_con_un_empleado(lanzador, cuando="manana", hace_horas=3)  # la llamada fue hoy a las 13:30
    assert lanzador.rellamadas_dirigidas(MARTES_16_30) == []
    assert len(lanzador.rellamadas_dirigidas(MARTES_16_30 + timedelta(days=1))) == 1


def test_la_lista_robinson_tambien_manda_en_la_rellamada(lanzador):  # noqa: F811
    lanzador.guardar_config(activo=True)
    _hablo_con_un_empleado(lanzador)
    assert _ronda(lanzador, MARTES_16_30, en_robinson={"+34911111111"}).llamadas == []


@pytest.mark.parametrize("dicho,franja,dia", [
    ("por las tardes", 1, None), ("el jueves a partir de las cuatro", 1, 3),
    ("manana por la manana", 0, None), ("a primera hora", 0, None), ("a las 11", 0, None), ("no se", None, None),
])
def test_entiende_cuando_esta(lanzador, dicho, franja, dia):  # noqa: F811
    leido = lanzador.cuando_esta(dicho)
    assert (leido["franja"], leido["dia"]) == (franja, dia)
