# -*- coding: utf-8 -*-
"""Una pregunta de verdad a mitad de reservar se contesta, y se sigue.

POR QUE EXISTE
--------------
Caso real de la duenya del salon, 2-sep-2026. A mitad de elegir alisado:

    ELLA  Y si es asi, habria algun problema si estoy dando pecho?
    IA    ...siempre es mejor consultar con tu medico

El salon tiene escrito que su Acido Lactico Bio Premium es 100 % biologico y apto
para embarazadas y madres lactantes. La MISMA frase, preguntada sola, se contesta
perfecta: falla solo dentro de una reserva.

Dos motivos, los dos de diseno: `whatsapp.py` apaga la capa del negocio en cuanto
hay flujo activo (`if not flow.flow`), y el agente solo mira las Q&A si el MODELO
se acuerda de llamar a la tool `politica_del_negocio`. No se acordo.

Asi lo resuelven los asistentes de produccion -digressions en Rasa, state
handlers en Dialogflow CX-: la comprension NO se apaga dentro de una tarea. Se
contesta la digresion y se retoma. Aqui retomar sale gratis porque el agente
conserva su estado.

ACOTADO A PROPOSITO: solo lo INFORMATIVO (`qa_exact`/`qa_semantica`), nunca las
acciones de las reglas. Esas son las que secuestran la conversacion -la del precio
se repitio siete veces mientras una clienta intentaba confirmar- y hay un
experimento medido que las tocaba y hundio las reservas del 61% al 41%.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def test_una_pregunta_del_negocio_se_le_da_al_agente(api_module, monkeypatch):
    from backend import agent, chat

    monkeypatch.setattr(chat, "decision_del_negocio", lambda *a, **k: {
        "texto": "Lava el cabello el mismo dia, solo champu.",
        "intent": "qa_semantica", "accion": "responder", "intencion": "",
    })

    guia = agent._lo_que_el_negocio_tiene_escrito("demo", "como voy con el pelo?")

    assert "Lava el cabello el mismo dia" in guia
    assert "sigue con lo que estabais haciendo" in guia, (
        "sin el remate se contesta la digresion y se pierde la reserva"
    )


def test_las_acciones_de_las_reglas_NO_entran(api_module, monkeypatch):
    """Son las que secuestran la conversacion a media reserva."""
    from backend import agent, chat

    monkeypatch.setattr(chat, "decision_del_negocio", lambda *a, **k: {
        "texto": "El precio depende de tu pelo, te cogemos un diagnostico.",
        "intent": "regla_negocio", "accion": "ofrecer_cita", "intencion": "precio",
    })

    assert agent._lo_que_el_negocio_tiene_escrito("demo", "quiero mechas") == ""


def test_sin_nada_configurado_no_estorba(api_module, monkeypatch):
    from backend import agent, chat

    monkeypatch.setattr(chat, "decision_del_negocio", lambda *a, **k: None)

    assert agent._lo_que_el_negocio_tiene_escrito("demo", "el jueves a las 10") == ""


def test_un_fallo_al_entender_no_deja_sin_respuesta(api_module, monkeypatch):
    from backend import agent, chat

    def _revienta(*a, **k):
        raise RuntimeError("modelo caido")

    monkeypatch.setattr(chat, "decision_del_negocio", _revienta)

    assert agent._lo_que_el_negocio_tiene_escrito("demo", "algo") == ""


def test_la_guia_llega_al_turno(api_module):
    """Si no entra en `guia`, el agente no la ve y no sirve de nada."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_lo_que_el_negocio_tiene_escrito(cliente_id, mensaje, config)" in fuente
    # El ORDEN dentro de la guia no se fija aqui a proposito: fijarlo hacia que
    # anyadir una linea nueva rompiera este test sin haber roto nada.
    linea = [l for l in fuente.splitlines() if "guia = [t for t in (" in l]
    assert linea, "no se encuentra la guia del turno"
    bloque = fuente[fuente.index(linea[0]):]
    assert "qa_negocio" in bloque[:400], "tiene que ir dentro de la guia del turno"


def test_una_peticion_de_cita_no_es_una_digresion(api_module):
    """El fallo que metio este mismo arreglo, cazado por el banco.

    "quiero unas mechas" es pedir CITA, pero la capa del negocio la reconocia
    como la pregunta del presupuesto: la guia le metia la parrafada del
    diagnostico y el asistente dejaba de preguntar el largo, que era lo unico
    que hacia falta. Es el riesgo del experimento medido que hundio las reservas
    del 61 % al 41 %: meter texto del negocio en un turno de reserva la
    descarrila. Asi que solo cuenta como digresion lo que tiene forma de
    PREGUNTA.
    """
    from backend import agent, catalog_pick

    def parece_pregunta(m):
        return bool("?" in m
                    or agent._PARECE_UNA_PREGUNTA.search(catalog_pick._norm(m)))

    for m in ("quiero unas mechas", "quiero cita para un alisado",
              "el jueves a las 10", "me llamo ana", "si, confirmo"):
        assert not parece_pregunta(m), m

    for m in ("cuanto cuestan unas mechas?", "y como tengo que venir con el cabello?",
              "que horario teneis", "teneis parking"):
        assert parece_pregunta(m), m


def test_el_signo_solo_ya_hace_pregunta(api_module):
    """Hay digresiones que son pregunta UNICAMENTE por el signo.

    "me lo puedo hacer dando pecho?" no lleva ninguna palabra interrogativa. Si
    el detector solo mirase palabras, el caso que motivo todo esto -la duenya
    preguntando por la lactancia a media reserva- se quedaria fuera.
    """
    from backend import agent, catalog_pick

    solo_el_signo = "me lo puedo hacer dando pecho?"

    assert agent._PARECE_UNA_PREGUNTA.search(catalog_pick._norm(solo_el_signo))
    # Y quitandole el signo deja de serlo: es lo unico que la marca.
    assert not agent._PARECE_UNA_PREGUNTA.search(
        catalog_pick._norm(solo_el_signo.replace("?", ""))
    ), "si casara por palabras, este test dejaria de probar lo que prueba"
