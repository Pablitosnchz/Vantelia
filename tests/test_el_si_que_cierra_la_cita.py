# -*- coding: utf-8 -*-
"""Que un "si" contento tambien cierre la cita.

Por WhatsApp el ultimo paso es decir que si al resumen. Ese si se reconocia con un
corte por LARGO: mas de 40 caracteres, no era un si. Y ahi se perdian citas de
verdad:

    "si, perfecto, me viene genial esa hora, confirmo"   (47 caracteres)

Cuanto mas contenta contestaba la clienta, menos probable era que se le cogiera la
cita. El largo nunca fue lo que separaba un si de un "si, PERO": lo que lo separa
es que detras venga una pega.

Aqui se fijan las dos mitades, porque aflojar solo una rompe la otra:

* los sies de verdad cierran, por largos que sean, y
* un "vale, pero mejor a las 5" NO cierra: esta pidiendo otra cosa, y cogerle la
  cita que no queria es peor que no cogerle ninguna.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


SIES = [
    "si",
    "confirmo",
    "vale",
    "si, confirmo",
    "Si, perfecto, me viene genial esa hora, confirmo",
    "perfecto, adelante con eso",
    "claro que si, reservala",
    "vale confirmo la cita del jueves a las 10 de la manana gracias",
    # Cerrar la cita y preguntar otra cosa a la vez es lo normal. Rechazarlo por
    # el signo de interrogacion le costaba la cita a quien ya habia dicho que si.
    "si, confirmo. me recuerdas la direccion?",
    "perfecto, confirmo, donde estais exactamente?",
]

NO_SON_SI = [
    "no",
    "no, mejor otro dia",
    "vale, pero mejor a las 5",
    "si pero cambiame la hora",
    "vale, y podria ser el viernes?",
    "perfecto aunque prefiero por la tarde",
    "me lo pienso y te digo",
    "si, aunque mejor otro dia",
    "vale, y podria ser el viernes?",
    "y si mejor el sabado?",
    "a que hora dices?",
]


def _plano(texto):
    from backend import textnorm

    return textnorm._strip_accents(texto.lower())


@pytest.mark.parametrize("texto", SIES)
def test_un_si_contento_tambien_cierra(api_module, texto):  # noqa: F811
    from backend import whatsapp

    assert whatsapp._wa_dice_que_si(_plano(texto)) is True, (
        "se pierde la cita de quien contesta que si con entusiasmo: %r" % texto
    )


@pytest.mark.parametrize("texto", NO_SON_SI)
def test_un_si_con_pega_no_cierra(api_module, texto):  # noqa: F811
    from backend import whatsapp

    assert whatsapp._wa_dice_que_si(_plano(texto)) is False, (
        "cogerle la cita que NO queria es peor que no cogerle ninguna: %r" % texto
    )


def test_un_parrafo_entero_no_es_una_confirmacion(api_module):  # noqa: F811
    """Sin ningun tope, cualquier mensaje largo que empiece por "vale" cerraria."""
    from backend import whatsapp

    largo = ("vale te cuento un poco mi caso porque llevo tiempo con el pelo muy "
             "estropeado desde que me hice un alisado hace dos anyos y no se muy "
             "bien que hacer ahora, la verdad")
    assert whatsapp._wa_dice_que_si(_plano(largo)) is False
