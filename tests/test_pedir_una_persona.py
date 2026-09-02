# -*- coding: utf-8 -*-
"""Quien pide hablar con una persona, la tiene: el asistente se calla.

POR QUE EXISTE
--------------
La accion `pasar_a_humano` existia solo como REGLA del negocio, y su plantilla se
dispara con QUEJAS. Si nadie la configura -el salon piloto tiene tres reglas y
ninguna es esa-, a "quiero hablar con una persona" el asistente seguia hablando.

Pedir una persona no puede depender de que el negocio se acuerde de configurarlo,
igual que no puede depender de eso lo que se hace con una foto: en los dos casos
hace falta alguien de verdad, y seguir contestando solo estorba.

El silencio caduca solo (INBOX_TAKEOVER_MINUTES), asi que nadie se queda sin
respuesta para siempre.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("frase", [
    "quiero hablar con una persona",
    "me pasas con alguien?",
    "puedes ponerme con el encargado",
    "no quiero hablar con un bot",
    "eres un robot?",
    "quiero que me atienda una persona de verdad",
])
def test_se_reconoce_que_pide_una_persona(api_module, frase):
    from backend import inbox

    assert inbox.pide_una_persona(frase), frase


@pytest.mark.parametrize("frase", [
    "quiero que me atienda Alicia",   # pide una PROFESIONAL, no un humano
    "quiero hablar de mechas",
    "hola, quiero cita",
    "me paso el jueves por el salon",
])
def test_no_se_confunde_con_otras_cosas(api_module, frase):
    from backend import inbox

    assert not inbox.pide_una_persona(frase), frase


def test_la_decision_pide_callar_al_asistente(api_module):
    """Los dos canales ya saben tratar `pasar_a_humano`: contestan y hacen claim."""
    from backend import chat

    decision = chat.decision_del_negocio("demo", "quiero hablar con una persona")

    assert decision, "pedir una persona tiene que decidir algo"
    assert decision["accion"] == "pasar_a_humano"
    assert decision["texto"], "hay que contestarle algo antes de callarse"


def test_el_negocio_puede_apagarlo(api_module):
    from backend import chat

    decision = chat.decision_del_negocio(
        "demo", "quiero hablar con una persona",
        config={"pasar_a_humano": {"enabled": False}},
    )

    assert decision is None or decision.get("accion") != "pasar_a_humano"


def test_el_negocio_puede_poner_su_texto(api_module):
    from backend import inbox

    config = {"pasar_a_humano": {"texto": "Te llamamos en 5 minutos."}}

    assert inbox.texto_al_pedir_persona("demo", config) == "Te llamamos en 5 minutos."


# --- Y por donde puede contestar de verdad ---------------------------------


def test_por_whatsapp_se_le_dice_que_espere(api_module):
    """Ahi SI hay vuelta: el equipo contesta desde su movil o desde el panel."""
    from backend import inbox

    texto = inbox.texto_al_pedir_persona("demo", hay_vuelta=True)

    assert "espera" in texto.lower()


def test_por_el_widget_no_se_promete_una_respuesta_que_no_puede_llegar(api_module):
    """El widget no tiene canal de vuelta: el salon no puede contestar por ahi.

    Callar al asistente ahi dejaria a la clienta mirando el silencio hasta que
    caduque el turno. Lo correcto es darle un sitio donde SI la atiendan.
    """
    from backend import inbox

    texto = inbox.texto_al_pedir_persona("demo", hay_vuelta=False)

    assert "espera" not in texto.lower()
    assert "llamas" in texto.lower() or "whatsapp" in texto.lower()


def test_el_texto_del_negocio_manda_en_los_dos_casos(api_module):
    from backend import inbox

    config = {"pasar_a_humano": {"texto": "Te llamamos en 5 minutos."}}

    assert inbox.texto_al_pedir_persona("demo", config, hay_vuelta=True) == "Te llamamos en 5 minutos."
    assert inbox.texto_al_pedir_persona("demo", config, hay_vuelta=False) == "Te llamamos en 5 minutos."


def test_el_chat_web_no_silencia_al_asistente(api_module):
    """Si silenciara, la clienta se quedaria sin nadie que le conteste."""
    import inspect

    from backend import chat

    fuente = inspect.getsource(chat._process_chat_message)
    assert 'decision["intent"] == "pide_una_persona"' in fuente
    assert "hay_vuelta=False" in fuente
