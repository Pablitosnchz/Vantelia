# -*- coding: utf-8 -*-
"""Una Q&A reconocida no puede contestar a otra cosa.

POR QUE EXISTE
--------------
Salio en la simulacion del 2-sep-2026, y es de los fallos que no se notan porque
la conversacion sigue teniendo sentido:

    ELLA  Quiero hacerme MECHAS pero no se que tecnica elegir
    IA    "Tenemos 3 tipos... Bio Premium, Liso Japones, Keratina Premium"
    ELLA  creo que lo mas logico seria ir por el Bio Premium
    IA    [le reserva Acido Lactico Bio Premium, que es un ALISADO]

El emparejador semantico le sirvio la Q&A de "que tipos de ALISADO teneis". A
partir de ahi la clienta elige del menu equivocado, y nadie lo nota hasta que se
planta en el salon para algo que no pidio. Dos de las 30 conversaciones acabaron
asi.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def _con_familias(monkeypatch, por_texto):
    """Controla que familias ve el comprobador, sin depender de un catalogo real."""
    from backend import catalog_pick

    monkeypatch.setattr(
        catalog_pick, "familias_pedidas",
        lambda cliente_id, texto: por_texto(texto),
    )


QA_ALISADO = {"question": "Que tipos de alisado teneis?",
              "answer": "Tenemos 3 tipos: Bio Premium, Liso Japones y Keratina Premium."}


def test_no_se_sirve_una_qa_de_otra_familia(api_module, monkeypatch):
    from backend import intents

    _con_familias(monkeypatch,
                  lambda t: ["mechas"] if "mechas" in t else ["alisados"])

    assert intents._habla_de_otra_cosa(
        "demo", "quiero hacerme mechas pero no se que tecnica elegir", QA_ALISADO,
    ), "mechas y alisado no son lo mismo"


def test_la_qa_de_su_familia_si_se_sirve(api_module, monkeypatch):
    from backend import intents

    _con_familias(monkeypatch, lambda t: ["alisados"])

    assert not intents._habla_de_otra_cosa(
        "demo", "que alisado me recomendais?", QA_ALISADO,
    )


def test_una_qa_sin_familia_vale_para_cualquier_pregunta(api_module, monkeypatch):
    """El horario o la direccion no van de ninguna familia: no se frenan."""
    from backend import intents

    qa = {"question": "Cual es vuestro horario?", "answer": "De martes a sabado."}
    _con_familias(monkeypatch, lambda t: ["mechas"] if "mechas" in t else [])

    assert not intents._habla_de_otra_cosa(
        "demo", "a que hora abris para unas mechas?", qa,
    )


def test_si_el_cliente_no_nombra_familia_tampoco_se_frena(api_module, monkeypatch):
    from backend import intents

    _con_familias(monkeypatch, lambda t: [] if "como funciona" in t else ["alisados"])

    assert not intents._habla_de_otra_cosa("demo", "y eso como funciona?", QA_ALISADO)
