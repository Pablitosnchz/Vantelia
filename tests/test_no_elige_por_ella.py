# -*- coding: utf-8 -*-
"""Cuando ella dice que no sabe, no se elige por ella.

POR QUE EXISTE
--------------
3-sep-2026, midiendo el salon piloto. Preguntado DE FRENTE contesta exactamente
lo que la duenya escribio:

    ELLA  quiero un alisado pero no se cual me va mejor
    IA    Sin ver tu cabello y poder tocarlo en persona no te puedo decir cual
          te recomendariamos de forma profesional...

Pero dicho como duda, sin forma de pregunta, se inventaba un criterio
profesional que el negocio tiene escrito que NO se da por mensaje:

    ELLA  no se, ni idea de que largo tengo
    IA    te recomendaria el Acido lactico bio premium

    ELLA  uf no se, me lo pienso y te digo
    IA    te recomendaria las Mechas o balayage medio

Es la misma forma que el fallo de la lactancia: la capa que entiende dispara con
la pregunta directa y se queda muda cuando la duda se expresa sin preguntar. Aqui
la duda se traduce a la pregunta que lleva dentro y se le pregunta al negocio.

SOLO frena donde el negocio lo ha dicho por escrito. Recomendar es legitimo para
quien no haya dicho lo contrario, y este freno no puede colarsele a ese negocio.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401

DUDAS = ["no se, ni idea de que largo tengo", "uf no se, me lo pienso y te digo",
         "no estoy segura", "no tengo claro cual", "lo que tu veas"]
NO_DUDAS = ["quiero cita para keratina premium", "el jueves por la manana",
            "me llamo Ana", "si, confirmo"]


def test_reconoce_la_duda_y_no_confunde_lo_que_no_lo_es(api_module):
    from backend import agent, catalog_pick

    for m in DUDAS:
        assert agent._DUDA_AL_ELEGIR.search(catalog_pick._norm(m)), m
    for m in NO_DUDAS:
        assert not agent._DUDA_AL_ELEGIR.search(catalog_pick._norm(m)), m


def test_ve_que_esta_recomendando_un_servicio_del_catalogo(api_module, monkeypatch):
    from backend import agenda, agent

    monkeypatch.setattr(agenda, "_catalog_services", lambda *a, **k: [
        {"nombre": "Acido lactico bio premium-corto medio"},
        {"nombre": "Keratina premium-largo"},
    ])

    # El catalogo lleva la variante pegada y el modelo dice el nombre a secas:
    # comparar el nombre entero no casaba NUNCA, y el freno no salto en la
    # primera version pese a estar bien escrito.
    assert agent._recomienda_un_servicio(
        "demo", "te recomendaria el **Acido lactico bio premium**, es muy efectivo")
    assert not agent._recomienda_un_servicio(
        "demo", "tenemos Keratina premium y Acido lactico bio premium, cual prefieres?"
    ), "enumerar las opciones no es recomendar una"


def test_solo_manda_si_el_negocio_lo_tiene_escrito(api_module, monkeypatch):
    from backend import agent, chat

    monkeypatch.setattr(chat, "decision_del_negocio", lambda *a, **k: {
        "texto": "Sin ver tu cabello no te puedo decir cual.",
        "intent": "qa_semantica", "accion": "responder", "intencion": "",
    })
    assert "Sin ver tu cabello" in agent._lo_que_el_negocio_dice_al_no_saber(
        "demo", "no se, ni idea")

    # Un negocio que no ha dicho nada de esto puede recomendar tranquilamente.
    monkeypatch.setattr(chat, "decision_del_negocio", lambda *a, **k: None)
    assert agent._lo_que_el_negocio_dice_al_no_saber("demo", "no se, ni idea") == ""

    # Y una ACCION de sus reglas no es una respuesta: no vale para esto.
    monkeypatch.setattr(chat, "decision_del_negocio", lambda *a, **k: {
        "texto": "Te cogemos un diagnostico.", "intent": "regla_negocio",
        "accion": "ofrecer_cita", "intencion": "precio",
    })
    assert agent._lo_que_el_negocio_dice_al_no_saber("demo", "no se, ni idea") == ""


def test_sin_duda_no_se_pregunta_al_negocio(api_module, monkeypatch):
    """No puede costar una llamada al modelo en cada turno normal."""
    from backend import agent, chat

    def _no_deberia(*a, **k):
        raise AssertionError("se ha preguntado al negocio sin haber ninguna duda")

    monkeypatch.setattr(chat, "decision_del_negocio", _no_deberia)
    assert agent._lo_que_el_negocio_dice_al_no_saber("demo", "el jueves a las 10") == ""


def test_el_freno_esta_cableado_en_el_turno(api_module):
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_lo_que_el_negocio_dice_al_no_saber(cliente_id, mensaje, config)" in fuente
    assert "guia_no_sabe" in fuente, "la guia tiene que entrar en el turno"
    assert 'traza.freno("eligio_por_ella")' in fuente, (
        "sin el freno esto es solo una instruccion del prompt, y el prompt se ignora"
    )


def test_los_dos_formatos_de_nombre_del_catalogo(api_module, monkeypatch):
    """El catalogo mezcla formatos y solo uno casaba.

    "Acido lactico bio premium-corto medio" lleva la variante tras un GUION;
    "Keratina premium largo" la lleva con un ESPACIO. La primera version cortaba
    por el guion, asi que con los nombres sin guion comparaba el nombre entero
    contra lo que el modelo dice a secas ("te recomendaria el alisado con
    Keratina premium") y no casaba NUNCA. El freno parecia funcionar porque el
    unico caso que se probo era de los que llevan guion.

    Se compara por las DOS PRIMERAS PALABRAS, que es la familia y no depende del
    formato.
    """
    from backend import agenda, agent

    monkeypatch.setattr(agenda, "_catalog_services", lambda *a, **k: [
        {"nombre": "Acido lactico bio premium-corto medio"},   # con guion
        {"nombre": "Keratina premium largo"},                  # sin guion
        {"nombre": "Corte de senora"},                         # familia generica
    ])

    assert agent._recomienda_un_servicio(
        "demo", "te recomendaria el alisado con **Keratina premium**, es ideal")
    assert agent._recomienda_un_servicio(
        "demo", "te recomendaria el **Acido lactico bio premium**")

    # "corte de" mide 8 y se cae sola: aparece en cualquier frase.
    assert not agent._recomienda_un_servicio(
        "demo", "te recomendaria que vengas antes del corte de luz")
