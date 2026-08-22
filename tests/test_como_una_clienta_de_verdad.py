# -*- coding: utf-8 -*-
"""Fallos salidos de comportarse como una clienta real, no como un guion.

Se probo escribiendo con faltas, partiendo una frase en tres mensajes, cortandose
a media palabra, preguntando cosas que no vienen a cuento a media reserva, y
tratando de que diera una cita por hecha. Salieron cuatro:

1. "¿me haceis las cejas?" -> "no realizamos servicios de cejas", teniendo
   "Depilacion cejas", "Diseño cejas" y "Tinte cejas" en el catalogo... que ESTABA
   en su prompt. Pedirle que lo mire no basta.
2. "el jueves 27 estamos cerrados" -> abren de 10:00 a 20:30. Lo dijo sin haber
   consultado la agenda ese turno.
3. "no espera, mejor un corte" -> se entendio como REPROGRAMAR (esta cambiando de
   idea, no de cita) y le pidio un numero de reserva que no tiene.
4. Contestaba sin llamar a ninguna tool cuando la respuesta dependia de datos.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def catalogo(api_module, client):  # noqa: F811
    from backend import agenda, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for nombre, categoria in (("Depilacion cejas", "Depilaciones"),
                                  ("Corte senora", "Cortes")):
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo', ?, ?, ?, 20, 1000, '', 1, 0, ?, ?)",
                (agenda._normalize_service_id(nombre), nombre, categoria, ahora, ahora),
            )
        conexion.commit()
    yield
    with db._get_db_connection() as conexion:
        conexion.execute(
            "DELETE FROM services WHERE cliente_id='demo' AND name IN"
            " ('Depilacion cejas','Corte senora')"
        )
        conexion.commit()


def test_no_puede_negar_un_servicio_que_si_existe(catalogo, api_module):  # noqa: F811
    """El fallo que mas caro sale: perder una clienta diciendole que no."""
    from backend import chat

    contexto = chat._contexto_del_catalogo("demo", "me haceis las cejas?")
    assert "SI ofrece" in contexto
    assert "Depilacion cejas" in contexto


def test_la_puntuacion_no_rompe_la_busqueda(catalogo, api_module):  # noqa: F811
    """"cejas?" con el signo pegado no casaba con "Depilacion cejas"."""
    from backend import chat

    for pregunta in ("me haceis las cejas?", "¿me hacéis las cejas?", "haceis cejas"):
        assert "Depilacion cejas" in chat._contexto_del_catalogo("demo", pregunta), (
            "no lo encuentra escrito asi: %r" % pregunta
        )


def test_lo_que_no_esta_se_dice_que_no_esta(catalogo, api_module):  # noqa: F811
    from backend import chat

    contexto = chat._contexto_del_catalogo("demo", "haceis manicura?")
    assert "no hay ningun servicio" in contexto


def test_solo_se_mira_el_catalogo_si_preguntan_si_lo_hacen(catalogo, api_module):  # noqa: F811
    """No hay que gastar una busqueda en cada mensaje."""
    from backend import chat

    assert chat._contexto_del_catalogo("demo", "gracias, hasta luego") == ""


def test_no_afirma_nada_de_la_agenda_sin_mirarla(api_module):  # noqa: F811
    """"el jueves estamos cerrados" siendo falso: lo dijo sin consultar."""
    from backend import agent

    assert agent._afirma_sobre_la_agenda("El jueves estamos cerrados") is True
    assert agent._afirma_sobre_la_agenda("no tengo hueco esa tarde") is True
    assert agent._afirma_sobre_la_agenda("¿Qué te apetece hacerte?") is False


def test_consulta_cuando_la_respuesta_depende_de_datos(api_module):  # noqa: F811
    from backend import agent

    assert agent._necesita_consultar("quiero cita el jueves") is True
    assert agent._necesita_consultar("quiero un corte") is True
    assert agent._necesita_consultar("gracias, muy amable") is False


def test_cambiar_de_idea_no_es_cambiar_de_cita(api_module):  # noqa: F811
    """"no espera, mejor un corte" le pedia su numero de reserva."""
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_message)
    assert "_wa_tiene_cita" in fuente, (
        "cancelar/reprogramar por intencion tiene que exigir que TENGA una cita"
    )


def test_sin_cita_no_se_dispara_reprogramar(catalogo, api_module):  # noqa: F811
    from backend import whatsapp

    assert whatsapp._wa_tiene_cita("demo", "34600999123") is False
