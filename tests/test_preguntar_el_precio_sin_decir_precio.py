# -*- coding: utf-8 -*-
"""Preguntar cuanto cuesta sin decir la palabra "precio".

Dos fallos CRITICOS del banco de casos, los dos vivos en produccion:

    "mas o menos en cuanto se me queda un balayage?"

El salon tiene configurada la regla "color y mechas: precio tras valoracion", y el
asistente iba derecho a dar una cifra. La deteccion de "pregunta el precio" tenia
esas formas -"mas o menos", "me sale por"- en la lista de INSISTIR, que no se mira
hasta DESPUES de la primera negativa. Quien abria preguntando asi se colaba entero.

Y la segunda mitad, que es la que hace esto generico: la salida solo miraba el
interruptor global `booking.mostrar_precios`. Un negocio que SI publica sus precios
pero tiene una regla para una familia concreta no estaba cubierto por ningun sitio:
el agente solo habria visto esa regla si al modelo le daba por llamar a
`politica_del_negocio`, y no le daba.

Lo que el negocio configura lo aplica el CODIGO.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


PREGUNTA_EL_PRECIO = [
    "cuanto cuestan unas mechas?",
    "mas o menos en cuanto se me queda un balayage?",
    "en cuanto me sale un alisado?",
    "cuanto me va a costar?",
    "que me cobrais por unas mechas?",
    "se queda en mucho un balayage?",
    "cuanto pagaria por un balayage?",
]

NO_PREGUNTA_EL_PRECIO = [
    # "mas o menos" tambien vale para el tiempo: por eso sigue necesitando que ya
    # se le haya negado una vez.
    "cuanto tarda un corte?",
    "mas o menos cuanto dura?",
    "quiero unas mechas",
    "a que hora abris?",
    "me haceis las cejas?",
]


@pytest.mark.parametrize("texto", PREGUNTA_EL_PRECIO)
def test_se_reconoce_desde_el_primer_mensaje(api_module, texto):  # noqa: F811
    from backend import agent

    assert agent._pregunta_el_precio(texto) is True, repr(texto)


@pytest.mark.parametrize("texto", NO_PREGUNTA_EL_PRECIO)
def test_no_se_confunde_con_preguntar_cuanto_dura(api_module, texto):  # noqa: F811
    """Mandar a una valoracion a quien preguntaba cuanto TARDA es otro fallo."""
    from backend import agent

    assert agent._pregunta_el_precio(texto) is False, repr(texto)


def test_una_regla_por_familia_basta_aunque_el_negocio_publique_precios(
        api_module, client):  # noqa: F811
    """El hueco generico: sin interruptor global, la regla del panel no se aplicaba."""
    from backend import booking, rules

    # El tenant de prueba NO tiene el interruptor global.
    assert booking.precios_ocultos("demo") is False

    regla = rules.guardar("demo", nombre="Color y mechas: precio tras valoracion",
                          intenciones=["precio", "presupuesto"],
                          familias=["mechas", "balayage"], accion="ofrecer_cita",
                          texto="De mechas no damos precio sin ver el pelo.")
    try:
        assert booking.no_se_da_precio_de("demo", "cuanto cuestan unas mechas?"), (
            "la regla que el negocio configuro en su panel no se esta aplicando"
        )
        # Y viene con SU texto, que manda sobre el nuestro.
        assert "sin ver el pelo" in booking.no_se_da_precio_de(
            "demo", "un balayage?")["texto"]
        # De lo que NO tiene regla si se da precio: no se vuelve mudo de todo.
        assert booking.no_se_da_precio_de("demo", "cuanto cuesta un corte?") == {}
    finally:
        rules.borrar("demo", regla["id"])


def test_pedir_foto_tambien_significa_que_no_hay_precio_por_mensaje(
        api_module, client):  # noqa: F811
    """Las dos acciones significan lo mismo ante "¿cuanto cuesta?".

    Lo que cambia entre "ofrecer cita" y "pedir foto" es la SALIDA que se ofrece,
    no si se dice la cifra. `_familias_que_exigen_valoracion` se quedaba solo con
    la primera, y por eso los alisados quedaban fuera.
    """
    from backend import booking, rules

    regla = rules.guardar("demo", nombre="Alisado: pedir foto",
                          intenciones=["precio"], familias=["alisado"],
                          accion="pedir_foto", texto="Mandanos una foto del pelo.")
    try:
        assert "alisado" in booking.familias_sin_precio("demo")
        assert booking.no_se_da_precio_de("demo", "que vale un alisado?")
    finally:
        rules.borrar("demo", regla["id"])


def test_la_salida_del_precio_consulta_las_reglas(api_module, client):  # noqa: F811
    """El enganche: si se suelta, vuelve a depender del interruptor global."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent._salida_para_quien_pregunta_el_precio)
    assert "no_se_da_precio_de" in fuente
    assert "precios_ocultos" not in fuente, (
        "ha vuelto a colgarse solo del interruptor global"
    )
