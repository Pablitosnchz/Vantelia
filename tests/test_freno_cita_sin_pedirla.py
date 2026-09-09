# -*- coding: utf-8 -*-
"""El freno de "nadie acaba con una cita que no ha pedido", decidido por HECHOS.

POR QUE EXISTE
--------------
El freno es necesario: el modelo cogia citas a quien solo estaba preguntando.
Pero decidia mirando las PALABRAS, y por ahi se colaba el caso legitimo -el
asistente propone hora y ella dice que si-. Cada vez que el modelo redactaba el
ofrecimiento de otra forma, el freno bloqueaba una reserva de verdad.

Conversacion real del 9-sep-2026 (23:09-23:14), medida en produccion:

    IA    Manana a las 15:00 tengo hueco para el Diagnostico y presupuesto.
          Te gustaria que te reserve esa hora?
    EL    si
    IA    Perfecto. Para manana a las 15:00, solo necesito que me digas si
          prefieres Keratina premium o Acido lactico bio premium.
    EL    si
    IA    Lo siento, necesito que me digas cual de los dos prefieres...
    EL    quiero el diagnostico nose cual hacerme te lo he dicho antes
    IA    ... Te gustaria que te reserve esa hora?
    EL    si
    IA    Parece que hubo un malentendido... Voy a reservarte esa hora. Un
          momento, por favor.

Y ahi se acabo: sin cita. El freno salto CINCO veces seguidas. La lista de frases
tenia "te reservo" y el asistente escribio "te reserve": una letra.

LA REGLA AHORA: si la hora la ofrecimos NOSOTROS -salio de consultar_disponibilidad
o el asistente la escribio-, decir que nadie ha pedido la cita es falso por
construccion. Eso no se escapa por una letra.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

CID = "demo"

CHARLA_REAL = [
    {"role": "user", "content": "cuánto dura un alisado?"},
    {"role": "assistant", "content": "De 80 a 165 minutos. ¿Keratina premium o Ácido láctico bio premium?"},
    {"role": "user", "content": "no lo tengo claro"},
    {"role": "assistant", "content": "Se decide mejor en la cita. Tengo disponibilidad el martes 15 de septiembre."},
    {"role": "user", "content": "puede ser el mañana?"},
    {"role": "assistant", "content": "Mañana tengo varias opciones: A las 10:00, A las 10:15, A las 10:30"},
    {"role": "user", "content": "a las 15"},
    {"role": "assistant", "content": "Mañana a las 15:00 tengo hueco para el Diagnóstico y presupuesto. "
                                     "¿Te gustaría que te reserve esa hora?"},
]
ARGS = {"servicio": "Diagnostico y presupuesto", "fecha": "2026-09-10",
        "hora": "15:00", "nombre": "Pablo Sanchez"}


def _estado(**campos):
    from backend import reserva

    e = reserva.Estado()
    for k, v in campos.items():
        setattr(e, k, v)
    return e


def test_la_conversacion_real_ya_no_se_frena(api_module):  # noqa: F811
    """El caso que dejo a una clienta sin cita despues de decir "si" tres veces."""
    from backend import agent

    e = _estado(huecos=["10:00", "10:15", "10:30", "15:00"])
    assert not agent._nadie_ha_pedido_esta_cita(CID, e, "si", CHARLA_REAL, "si", ARGS)


def test_basta_con_que_el_asistente_dijera_la_hora(api_module):  # noqa: F811
    """Aunque el estado se haya perdido (reinicio, TTL), la conversacion lo dice."""
    from backend import agent

    assert not agent._nadie_ha_pedido_esta_cita(CID, _estado(), "si", CHARLA_REAL, "si", ARGS)


def test_sigue_frenando_a_quien_solo_pregunta(api_module):  # noqa: F811
    """Lo que el freno protege: preguntar el horario NO es pedir cita, y el
    modelo se lanzaba a coger una a una hora que nadie habia nombrado."""
    from backend import agent

    charla = [
        {"role": "user", "content": "a qué hora abrís?"},
        {"role": "assistant", "content": "Abrimos de lunes a viernes de 10:00 a 20:00."},
    ]
    assert agent._nadie_ha_pedido_esta_cita(
        CID, _estado(), "vale gracias", charla, "vale gracias",
        {"servicio": "Corte", "fecha": "2026-09-10", "hora": "18:30", "nombre": "Ana"})


def test_con_servicio_y_hora_ya_elegidos_no_frena(api_module):  # noqa: F811
    """A tener servicio y hora solo se llega recorriendo la reserva entera."""
    from backend import agent

    e = _estado(servicio="Corte senora", hora="11:00")
    assert not agent._nadie_ha_pedido_esta_cita(CID, e, "si", [], "si", ARGS)


def test_pedirlo_con_sus_palabras_sigue_valiendo(api_module):  # noqa: F811
    from backend import agent

    assert not agent._nadie_ha_pedido_esta_cita(
        CID, _estado(), "quiero pedir cita para un corte", [], "quiero pedir cita para un corte", ARGS)


@pytest.mark.parametrize("frase", [
    "¿Te gustaría que te reserve esa hora?",
    "Te la dejo apuntada a las 15:00, ¿te va bien?",
    "Puedo dejarte hueco a las 15:00.",
    "A las 15:00 lo tengo libre, ¿lo cierro?",
])
def test_da_igual_como_lo_redacte(api_module, frase):  # noqa: F811
    """El punto de todo esto: la redaccion del ofrecimiento deja de importar,
    porque lo que se mira es que la HORA la pusimos nosotros."""
    from backend import agent

    charla = [{"role": "user", "content": "a las 15"}, {"role": "assistant", "content": frase}]
    assert not agent._nadie_ha_pedido_esta_cita(CID, _estado(), "si", charla, "si", ARGS)


def test_la_red_de_seguridad_esta_puesta(api_module):  # noqa: F811
    """Un freno que salta dos veces en la misma conversacion ya no protege: bloquea."""
    import inspect

    from backend import agent, reserva

    assert hasattr(reserva.Estado(), "veces_sin_pedirla")
    fuente = inspect.getsource(agent.responder)
    assert "veces_sin_pedirla" in fuente
    assert '"veces_sin_pedirla", 0) < 2' in fuente
