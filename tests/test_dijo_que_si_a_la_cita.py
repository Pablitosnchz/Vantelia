# -*- coding: utf-8 -*-
"""Decir "si" a una cita que te acaban de proponer ES pedirla.

POR QUE EXISTE
--------------
Medido en produccion el 9-sep-2026, conversacion real por WhatsApp:

    IA    Te puedo ofrecer la cita para manana a las 12:00. Te va bien esa hora?
          Si es asi, solo necesito tu nombre para confirmar.
    EL    si
    IA    Perfecto. Entonces, para manana a las 12:00, solo me falta que elijas
          entre Keratina premium o Acido lactico bio premium.

Le habia dicho que queria el DIAGNOSTICO cuatro mensajes antes. Lo que pasaba por
debajo: el freno de "no te ha pedido ninguna cita" bloqueo `crear_cita`, y al
modelo no le quedo otra que improvisar, asi que volvio a preguntar el servicio.

El freno mira las palabras de ELLA -y "si" no lleva ninguna forma de pedir cita-,
asi que existe `_le_ofrecieron_cita_y_dijo_que_si` para el camino legitimo. Fallaba
por dos cosas: la lista de frases no cubria "te puedo ofrecer la cita" ni "te va
bien esa hora", y solo miraba el ULTIMO mensaje del asistente.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


def _charla(*mensajes):
    return [{"role": "assistant", "content": m} for m in mensajes]


@pytest.mark.parametrize("ofrecimiento", [
    "Te puedo ofrecer la cita para mañana a las 12:00. ¿Te va bien esa hora?",
    "¿Te parece bien esa hora? Si es así, solo necesito tu nombre.",
    "Voy a reservar tu cita para mañana. ¿Me confirmas?",
    "¿Te la cojo para el jueves?",
])
def test_le_proponen_y_dice_que_si(api_module, ofrecimiento):  # noqa: F811
    from backend import agent

    assert agent._le_ofrecieron_cita_y_dijo_que_si(_charla(ofrecimiento), "si")


def test_el_ofrecimiento_puede_estar_un_mensaje_mas_atras(api_module):  # noqa: F811
    """Entre medias el asistente contesta a otra cosa y el ofrecimiento se aleja."""
    from backend import agent

    charla = _charla(
        "Te puedo ofrecer la cita para mañana a las 12:00. ¿Te va bien esa hora?",
        "El diagnóstico dura 15 minutos, cariño.",
    )
    assert agent._le_ofrecieron_cita_y_dijo_que_si(charla, "si")


def test_sin_ofrecimiento_un_si_no_es_pedir_cita(api_module):  # noqa: F811
    """El freno tiene que seguir frenando: nadie acaba con una cita que no pidio."""
    from backend import agent

    charla = _charla("Abrimos de lunes a viernes de 9:00 a 20:00.",
                     "El corte de señora dura 20 minutos.")
    assert not agent._le_ofrecieron_cita_y_dijo_que_si(charla, "si")


def test_un_no_nunca_es_que_si(api_module):  # noqa: F811
    from backend import agent

    charla = _charla("Te puedo ofrecer la cita para mañana a las 12:00.")
    assert not agent._le_ofrecieron_cita_y_dijo_que_si(charla, "no, mejor otro dia")


def test_muy_atras_ya_no_cuenta(api_module):  # noqa: F811
    """Tres mensajes es el limite: un ofrecimiento de hace media conversacion no
    convierte cualquier "si" posterior en una reserva."""
    from backend import agent

    charla = _charla("¿Te la cojo para el jueves?", "Abrimos a las 9:00.",
                     "El corte dura 20 minutos.", "Los alisados son de 80 a 165 minutos.")
    assert not agent._le_ofrecieron_cita_y_dijo_que_si(charla, "si")
