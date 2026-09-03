# -*- coding: utf-8 -*-
"""Dos personas no caben en un hueco.

POR QUE EXISTE
--------------
3-sep-2026, llevado hasta el final sobre el salon piloto:

    ELLA  queria cita para mi y para mi madre el mismo dia, cortes las dos
    IA    Perfecto, ya tengo el servicio de Corte senora para las dos
    ...
    IA    *Cita confirmada*

Quedo UNA cita. Un hueco de veinte minutos para dos cortes, y el negocio con dos
personas plantadas a la misma hora.

Misma familia que `_freno_de_varios_servicios` y el mismo incidente que ya costo
una tarde al salon: el modelo da la cita por buena porque para el se creo bien.
Lo tiene que impedir el codigo.

TRAMPA QUE COSTO EL PRIMER INTENTO: lo que ella escribio no se borra nunca, asi
que un freno que solo mira el texto acumulado bloquea PARA SIEMPRE. Medido:
repetia "cada persona necesita su propio hueco" tres veces y no cogia ni la
primera cita. Quedarse sin ninguna es peor que el fallo original. Ahora avisa una
vez -se reconoce por la marca en el resultado de la tool- y despues deja
reservar de una en una.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401

VARIAS = ["queria cita para mi y para mi madre el mismo dia, cortes las dos",
          "somos dos para cortarnos el pelo", "mi hija y yo queremos cita",
          "cita para dos personas", "nos cortamos las dos"]
UNA = ["quiero cita para un corte de senora", "el jueves a las dos de la tarde",
       "las dos y media me viene bien", "a las dos en punto", "me llamo Ana"]


def _dichos(*textos):
    return [{"role": "user", "content": t} for t in textos]


def test_reconoce_que_son_varias(api_module):
    from backend import agent

    for t in VARIAS:
        assert agent._freno_de_varias_personas("demo", _dichos(t)) is not None, t


def test_una_hora_no_son_dos_personas(api_module):
    """"a las dos", "las dos y media": son horas, no clientas."""
    from backend import agent

    for t in UNA:
        assert agent._freno_de_varias_personas("demo", _dichos(t)) is None, t


def test_avisa_una_vez_y_luego_deja_reservar(api_module):
    from backend import agent

    dichos = _dichos(VARIAS[0])
    primero = agent._freno_de_varias_personas("demo", dichos)
    assert primero is not None

    # El aviso ya viajo a la conversacion como resultado de tool.
    dichos.append({"role": "tool", "content": primero["error"]})

    assert agent._freno_de_varias_personas("demo", dichos) is None, (
        "si sigue bloqueando, se queda sin NINGUNA cita: peor que el fallo"
    )


def test_el_freno_esta_cableado_al_crear(api_module):
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_freno_de_varias_personas(" in fuente
    i = fuente.index("_freno_de_varias_personas(")
    assert 'llamada.function.name == "crear_cita"' in fuente[:i], (
        "tiene que actuar al CREAR la cita, que es donde se rompe la agenda"
    )
