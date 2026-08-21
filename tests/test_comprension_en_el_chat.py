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
    from backend import chat

    return inspect.getsource(chat._process_chat_message)


def test_lo_que_el_negocio_escribio_va_antes_que_la_comprension(api_module):  # noqa: F811
    """Sus Q&A literales y sus palabras clave no se pueden reinterpretar."""
    fuente = _fuente(api_module)
    assert fuente.index("keywords.match_reply") < fuente.index("_match_qa_answer")
    assert fuente.index("_match_qa_answer") < fuente.index("intents.classify")


def test_la_comprension_va_antes_que_las_heuristicas(api_module):  # noqa: F811
    """Su razon de ser: entender lo que los patrones no entendian."""
    fuente = _fuente(api_module)
    assert fuente.index("intents.classify") < fuente.index("_message_requests_availability")


def test_no_se_clasifica_con_una_gestion_a_medias(api_module):  # noqa: F811
    """Si esta cancelando su cita, su "el jueves a las 5" NO es pedir una nueva."""
    fuente = _fuente(api_module)
    assert fuente.index("_chat_manage_state_get") < fuente.index("intents.classify")
    assert "not gestion_en_curso" in fuente


def test_apagado_por_defecto(api_module, client):  # noqa: F811
    """Ningun negocio empieza pagando llamadas sin haberlo pedido."""
    from backend import clients, intents

    assert intents.enabled_for("demo", clients._get_client_config("demo")) is False


def test_solo_contarlo_cuenta_de_verdad(api_module):  # noqa: F811
    """La accion "continuar" existe para MEDIR una regla antes de activarla.

    Se contaba solo cuando la regla respondia, que es justo lo que "continuar" no
    hace: servia para nada.
    """
    fuente = _fuente(api_module)
    assert fuente.index("rules.contar_uso") < fuente.index('!= "continuar"')
