# -*- coding: utf-8 -*-
"""La gente escribe deprisa: "quiero agendare una cita" también es pedir cita.

Caso real por WhatsApp (21-ago):

    > quiero agendare una cita
    < ¡Genial! 😊 Para agendar tu cita, primero necesito saber:
      1. ¿Qué día te gustaría venir? ...

En vez del formulario de reserva, contestó el modelo pidiendo los datos a mano.
Dos motivos, los dos del detector:

- `\\bagendar\\b` exige la palabra exacta y "agendare" no casa.
- "quiero una cita" tenía que ir seguido, así que cualquier palabra por medio
  ("quiero **agendare** una cita") lo rompía.

Y al hacerlo tolerante aparece el riesgo contrario: "quiero cancelar mi cita"
también dice "quiero … cita", y no puede abrir el formulario de reserva.
"""
from __future__ import annotations

import pytest

from backend import booking

PIDE_CITA = [
    "quiero agendar una cita",
    "quiero agendare una cita",        # el caso que fallaba
    "quiero agendarme una cita",
    "quiero reservarme una cita",
    "agendar cita",
    "quiero reservar",
    "quiero pedir cita",
    "quiero una cita",
    "quisiera agendar una cita",
    "me gustaria agendar cita",
    "necesito una cita",
    "quiero coger cita para el martes",
    "podria reservar una cita?",
    "quiero sacar cita",
]

NO_PIDE_CITA = [
    "quiero cancelar mi cita",
    "quiero cambiar mi cita",
    "ya tengo una cita agendada",
    "gracias",
    "hola",
    "¿que precio tiene?",
]


@pytest.mark.parametrize("mensaje", PIDE_CITA)
def test_pedir_cita_abre_el_formulario(mensaje):
    assert booking._message_requests_booking_form(mensaje), mensaje


@pytest.mark.parametrize("mensaje", NO_PIDE_CITA)
def test_gestionar_una_cita_existente_no_abre_el_formulario(mensaje):
    assert not booking._message_requests_booking_form(mensaje), mensaje


def test_cancelar_gana_aunque_diga_quiero_y_cita():
    """El riesgo de aflojar el patrón: "quiero cancelar mi cita" encaja en
    "quiero … cita". Si abriera el formulario, quien quiere cancelar acabaría
    reservando otra."""
    assert booking._message_requests_cancel_booking("quiero cancelar mi cita")
    assert not booking._message_requests_booking_form("quiero cancelar mi cita")
