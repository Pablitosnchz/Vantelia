# -*- coding: utf-8 -*-
"""No se le devuelven sus palabras como si fueran un servicio.

POR QUE EXISTE
--------------
3-sep-2026, midiendo el salon piloto:

    ELLA  hola?
    IA    No tengo un servicio especifico llamado "hola"

    ELLA  hmm
    IA    No tengo un servicio especifico que se llame "hmm"

    ELLA  hay alguien?
    IA    No tengo un servicio que se llame "hola? hay alguien?"

Da sensacion de maquina rota, y es lo primero que ve alguien que solo estaba
saludando.

Se intento primero pidiendoselo en el mensaje de la tool ("si lo que ha escrito
no es un servicio, no se lo repitas como si lo fuera") y NO cambio absolutamente
nada: siguio haciendolo. Por eso el freno esta en el codigo. Es el ejemplo mas
limpio de la regla de la casa: lo que el modelo puede hacer mal lo impide el
codigo, no el prompt.

TRAMPA: el entrecomillado acumula VARIOS mensajes suyos, asi que su ultimo
mensaje esta dentro de la cita y no al reves. Comprobando un solo sentido, el
tercer caso se escapaba.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def test_caza_las_tres_formas_medidas(api_module):
    from backend import agent

    casos = [
        ("hola?", 'No tengo un servicio especifico llamado "hola", dime.'),
        ("hmm", 'No tengo un servicio especifico que se llame "hmm".'),
        ("hay alguien?", 'No tengo un servicio que se llame "hola? hay alguien?".'),
    ]
    for dicho, respuesta in casos:
        assert agent._le_repite_sus_palabras_como_servicio(dicho, respuesta), dicho


def test_no_frena_una_negativa_legitima(api_module):
    """Negar un servicio que de verdad le han pedido esta bien."""
    from backend import agent

    assert not agent._le_repite_sus_palabras_como_servicio(
        "quiero mechas", 'No tengo un servicio llamado "manicura" en el catalogo.')
    assert not agent._le_repite_sus_palabras_como_servicio(
        "me haceis la manicura?", "No tenemos manicura, lo siento.")


def test_el_freno_esta_cableado(api_module):
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_le_repite_sus_palabras_como_servicio(mensaje, texto_final)" in fuente
    assert 'traza.freno("le_repitio_su_muletilla")' in fuente
