# -*- coding: utf-8 -*-
"""Quien dice que lo deja para luego, se va sin que le insistan.

POR QUE EXISTE
--------------
3-sep-2026, midiendo el salon piloto:

    ELLA  dejalo, ya lo miro luego
    IA    Entiendo, si prefieres mirar mas tarde, no hay problema. PERO para
          poder reservar la cita necesito saber el largo de tu cabello.
          Tienes el cabello corto, medio, largo o extra largo?

Dice "sin problema" y repite la misma pregunta. Es el bot pesado del que la gente
deja de contestar, y hace quedar mal al negocio.

Los asistentes de produccion lo tratan como un patron con nombre propio
-cancellation en Rasa, junto a digressions y corrections-: cuando alguien
abandona una tarea se acepta, se cierra con la puerta abierta y no se le pide
nada mas.

Medido: "mira al final no, gracias" YA se cerraba bien. Lo que fallaba era el
abandono BLANDO ("dejalo", "me lo pienso", "ya te dire"), que es justo el que un
humano deja marchar sin insistir.

TRAMPA QUE COSTO EL PRIMER INTENTO: el detector miraba `dicho_de_ella`, que
acumula TODO lo que ella ha escrito en la conversacion. Con eso, quien decia
"dejalo por ahora" y dos mensajes despues "va, si que quiero, el viernes" seguia
recibiendo la despedida una y otra vez: la conversacion quedaba muerta. Tiene que
mirar SOLO el ultimo mensaje.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401

INSISTE = "Entiendo, no hay problema. Pero para reservar la cita necesito saber el largo."
SE_DESPIDE = "Sin problema, cuando quieras me lo dices y te lo miro. Un abrazo!"


def test_frena_cuando_le_insiste_tras_dejarlo(api_module):
    from backend import agent

    for dicho in ("dejalo, ya lo miro luego", "me lo pienso y te digo",
                  "ya te dire", "lo miro mas tarde", "dejalo por ahora",
                  # Medidas con el simulador: una clienta dijo OCHO veces que
                  # solo queria el horario y en cada respuesta le ofrecian un
                  # alisado. Cerrar no es solo aplazar; tambien es decir "ya esta".
                  "solo queria saber los horarios", "no necesito cita",
                  "solo era eso, gracias", "con eso me vale"):
        assert agent._sigue_insistiendo_tras_dejarlo(dicho, INSISTE), dicho


def test_empujar_no_es_solo_pedirle_un_dato(api_module):
    """A quien decia que solo queria el horario le colaban un tratamiento."""
    from backend import agent

    ofrece = ("Entiendo que solo querias saber los horarios. Si en algun momento "
              "decides hacerte un alisado, te recomendaria la Keratina premium.")
    assert agent._sigue_insistiendo_tras_dejarlo(
        "Solo queria saber los horarios. LISTO", ofrece)

    cierra = ("Hoy abrimos de 10:00 a 20:30 y los sabados de 09:00 a 20:30. "
              "Cualquier cosa, aqui estoy.")
    assert not agent._sigue_insistiendo_tras_dejarlo(
        "Solo queria saber los horarios. LISTO", cierra)


def test_no_frena_una_despedida_correcta(api_module):
    from backend import agent

    assert not agent._sigue_insistiendo_tras_dejarlo("dejalo, ya lo miro luego",
                                                     SE_DESPIDE)


def test_no_frena_a_quien_no_ha_dejado_nada(api_module):
    from backend import agent

    for dicho in ("el jueves por la manana", "quiero cita para un corte",
                  "si, confirmo", "cuanto cuesta?"):
        assert not agent._sigue_insistiendo_tras_dejarlo(dicho, INSISTE), dicho


def test_si_vuelve_se_le_atiende(api_module):
    """El fallo del primer intento: la despedida se quedaba pegada."""
    from backend import agent

    # Su ULTIMO mensaje ya no es un abandono, aunque antes lo dijera.
    assert not agent._sigue_insistiendo_tras_dejarlo(
        "va, si que quiero, el viernes por la manana", INSISTE)


def test_el_freno_mira_solo_el_ultimo_mensaje(api_module):
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_sigue_insistiendo_tras_dejarlo(mensaje, texto_final)" in fuente, (
        "con `dicho_de_ella` se queda despidiendose para siempre: acumula todo "
        "lo que ella ha escrito"
    )
    assert 'traza.freno("insistio_tras_dejarlo")' in fuente
