# -*- coding: utf-8 -*-
"""A quien se queja de un trabajo hecho no se le vende otro.

POR QUE EXISTE
--------------
3-sep-2026, midiendo el salon piloto:

    ELLA  me hice el alisado la semana pasada y se me ha quedado fatal el pelo
    IA    Lamento que no te haya salido bien. Para solucionarlo, podemos optar por
          un tratamiento de Keratina premium o de Acido lactico bio premium.

    ELLA  no estoy nada contenta con el color que me hicisteis
    IA    Lamento que no estes contenta. Te gustaria hacerte un Matiz, un Elumen,
          un cambio de color por todo o un Grey blending?

A una clienta que se queja de un trabajo mal hecho se le esta vendiendo otro. Es
el mensaje que convierte una queja en una resenya de una estrella.

El playbook `pasar_a_persona` cubre las quejas para quien lo active en el portal
-el salon piloto NO lo tenia activado-, pero el suelo no puede depender de que
alguien se acuerde. Aqui solo se impide lo indefendible (nombrarle un
tratamiento); que hacer con la queja lo sigue decidiendo el negocio.

TRAMPA QUE COSTO EL PRIMER INTENTO: el filtro de nombres pedia 10 caracteres,
heredado del freno de recomendar. "Matiz" y "Elumen" tienen 5 y 6, asi que la
segunda queja se colaba entera. Aqui el umbral es 5 y se exige palabra completa:
dentro de una queja, nombrar CUALQUIER servicio sobra.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401

CATALOGO = [{"nombre": "Keratina premium-largo"}, {"nombre": "Matiz"},
            {"nombre": "Elumen"}, {"nombre": "Corte de senora"}]

QUEJAS = ["me hice el alisado la semana pasada y se me ha quedado fatal el pelo",
          "no estoy nada contenta con el color que me hicisteis",
          "me habeis estropeado el pelo", "quiero poner una reclamacion",
          "el tinte me ha salido mal"]


def test_frena_cuando_le_ofrece_un_tratamiento(api_module, monkeypatch):
    from backend import agenda, agent

    monkeypatch.setattr(agenda, "_catalog_services", lambda *a, **k: CATALOGO)

    for queja in QUEJAS:
        assert agent._vende_sobre_una_queja(
            "demo", queja, "Lo siento. Podemos hacerte un Matiz para arreglarlo."
        ), queja


def test_nombres_cortos_tambien_cuentan(api_module, monkeypatch):
    """"Matiz" y "Elumen" se colaban con el umbral de 10 del otro freno."""
    from backend import agenda, agent

    monkeypatch.setattr(agenda, "_catalog_services", lambda *a, **k: CATALOGO)

    assert agent._vende_sobre_una_queja(
        "demo", QUEJAS[1],
        "Lamento que no estes contenta. Te gustaria un Elumen o un Matiz?")


def test_no_frena_la_respuesta_correcta(api_module, monkeypatch):
    from backend import agenda, agent

    monkeypatch.setattr(agenda, "_catalog_services", lambda *a, **k: CATALOGO)

    assert not agent._vende_sobre_una_queja(
        "demo", QUEJAS[0],
        "Lo siento mucho. Queremos verlo en el salon: te busco un hueco?")


def test_no_frena_a_quien_no_se_queja(api_module, monkeypatch):
    from backend import agenda, agent

    monkeypatch.setattr(agenda, "_catalog_services", lambda *a, **k: CATALOGO)

    for m in ("quiero hacerme un alisado, cuales teneis?",
              "cuanto cuesta un Matiz?", "el jueves por la manana"):
        assert not agent._vende_sobre_una_queja(
            "demo", m, "Tenemos Matiz y Elumen, cual prefieres?"), m


def test_el_freno_esta_cableado(api_module):
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_vende_sobre_una_queja(cliente_id, mensaje, texto_final)" in fuente
    assert 'traza.freno("vendio_sobre_una_queja")' in fuente
