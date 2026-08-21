# -*- coding: utf-8 -*-
"""La comprension se enchufa en el chat sin pisar lo que ya funcionaba.

El orden de las capas ES la logica del asistente, y aqui se vigila:

    saludo > palabra clave > Q&A literal > COMPRENSION > heuristicas de siempre

Lo que el negocio escribe a mano (sus reglas por palabra clave, sus Q&A) manda
sobre cualquier deduccion nuestra. La comprension entra justo despues, para
arreglar lo que las heuristicas no entendian, y nunca antes.
"""
from __future__ import annotations

import inspect

from test_booking_exhaustive import api_module, client  # noqa: F401


def _fuente(api_module):  # noqa: F811
    """El recorrido completo del chat: el turno y la decision que comparte con WhatsApp."""
    from backend import chat

    return (inspect.getsource(chat._process_chat_message)
            + inspect.getsource(chat.decision_del_negocio))


def _turno(api_module):  # noqa: F811
    from backend import chat

    return inspect.getsource(chat._process_chat_message)


def _decision(api_module):  # noqa: F811
    from backend import chat

    return inspect.getsource(chat.decision_del_negocio)


def test_lo_que_el_negocio_escribio_va_antes_que_la_comprension(api_module):  # noqa: F811
    """Sus Q&A literales y sus palabras clave no se pueden reinterpretar."""
    turno = _turno(api_module)
    assert turno.index("keywords.match_reply") < turno.index("decision_del_negocio(")
    decision = _decision(api_module)
    assert decision.index("_match_qa_answer") < decision.index("intents.classify")


def test_la_comprension_va_antes_que_las_heuristicas(api_module):  # noqa: F811
    """Su razon de ser: entender lo que los patrones no entendian."""
    turno = _turno(api_module)
    assert turno.index("decision_del_negocio(") < turno.index("_message_requests_availability")


def test_no_se_clasifica_con_una_gestion_a_medias(api_module):  # noqa: F811
    """Si esta cancelando su cita, su "el jueves a las 5" NO es pedir una nueva."""
    turno = _turno(api_module)
    assert "_chat_manage_state_get" in turno, "el turno tiene que mirar si hay gestion a medias"
    assert "gestion_en_curso=" in turno, "y pasarselo a la decision del negocio"
    decision = _decision(api_module)
    assert decision.index("gestion_en_curso") < decision.index("intents.classify")


def test_apagado_por_defecto(api_module, client):  # noqa: F811
    """Ningun negocio empieza pagando llamadas sin haberlo pedido."""
    from backend import clients, intents

    assert intents.enabled_for("demo", clients._get_client_config("demo")) is False


def test_solo_contarlo_cuenta_de_verdad(api_module):  # noqa: F811
    """La accion "continuar" existe para MEDIR una regla antes de activarla.

    Se contaba solo cuando la regla respondia, que es justo lo que "continuar" no
    hace: servia para nada.
    """
    decision = _decision(api_module)
    assert decision.index("rules.contar_uso") < decision.index('!= "continuar"')


def test_pedir_cita_gana_a_explicar_como_se_pide(api_module):  # noqa: F811
    """Caso real en produccion: "me pones una cita?" no abria el formulario.

    El salon tenia una Q&A explicando como reservar, y la coincidencia semantica
    la devolvia: la clienta acababa leyendo instrucciones en vez de reservando.
    """
    decision = _decision(api_module)
    assert "INTENCIONES_QUE_SE_ACTUAN" in decision
    assert decision.index("pide_algo") < decision.index("respuesta_qa =")


def test_preguntar_si_hay_hueco_devuelve_huecos(api_module):  # noqa: F811
    """"¿puedo ir mañana?" acababa en la IA generica, contestando el horario.

    Lo que la clienta quiere saber es si hay HUECO. Se le da la misma respuesta
    que a quien lo escribe de la forma que los patrones si reconocian.
    """
    turno = _turno(api_module)
    bloque = turno[turno.index("decision_del_negocio("):turno.index("menu_option = _detect_menu_option")]
    assert '== "disponibilidad"' in bloque
    assert "_build_chat_availability_answer" in bloque
