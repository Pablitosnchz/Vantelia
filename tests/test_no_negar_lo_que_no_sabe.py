# -*- coding: utf-8 -*-
"""Lo que el negocio no ha escrito, el asistente no lo puede negar.

POR QUE EXISTE
--------------
Clase 20 de docs/CAZA_DE_FALLOS.md. Una clienta pregunto por promociones y el
asistente contesto:

    "No tenemos promociones especificas para el alisado en este momento."

La duenya SI tenia promocion los martes y miercoles; simplemente no estaba en el
sistema. Ante un hueco en la configuracion, el modelo elige la salida rotunda en
vez de reconocer que no lo sabe, y negar por defecto cuesta clientas. Es primo
hermano de negar un servicio que si se hace, que ya es critico en el banco.

El freno solo actua cuando el negocio NO ha escrito nada del tema: quien tenga
sus promociones puestas sigue contestando con ellas, incluso para decir que en
esa fecha no hay.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("frase", [
    "Lo siento, no tenemos promociones especificas para el alisado en este momento",
    "No hay ofertas ahora mismo",
    "no contamos con descuentos",
    "No disponemos de promociones",
])
def test_se_detecta_la_negativa_rotunda(api_module, frase):
    from backend import agent, catalog_pick

    assert agent._NIEGA_PROMOCIONES.search(catalog_pick._norm(frase)), frase


@pytest.mark.parametrize("frase", [
    "Si, tenemos promocion los martes y miercoles",
    "No tenemos ese servicio en el catalogo",
    "No hay hueco esa tarde, te ofrezco el jueves",
])
def test_no_se_confunde_con_otras_negativas(api_module, frase):
    from backend import agent, catalog_pick

    assert not agent._NIEGA_PROMOCIONES.search(catalog_pick._norm(frase)), frase


def test_si_el_negocio_lo_ha_escrito_no_se_frena(api_module, monkeypatch):
    """Quien tiene sus promociones puestas puede hablar de ellas, tambien para decir que no."""
    from backend import agent

    monkeypatch.setattr(agent, "_el_negocio_ha_escrito_de_promociones", lambda cid: True)

    assert not agent._niega_algo_que_no_puede_saber("demo", "no tenemos promociones")


def test_sin_nada_escrito_no_puede_negar(api_module, monkeypatch):
    from backend import agent

    monkeypatch.setattr(agent, "_el_negocio_ha_escrito_de_promociones", lambda cid: False)

    assert agent._niega_algo_que_no_puede_saber("demo", "no tenemos promociones")


def test_ante_un_fallo_de_lectura_no_se_frena_nada(api_module, monkeypatch):
    """Un freno nunca puede romper una respuesta por no poder leer la base."""
    from backend import agent, db

    def _revienta():
        raise RuntimeError("base caida")

    monkeypatch.setattr(db, "_get_db_connection", _revienta)

    assert agent._el_negocio_ha_escrito_de_promociones("demo") is True
