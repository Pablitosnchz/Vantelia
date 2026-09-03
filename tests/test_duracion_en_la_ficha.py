# -*- coding: utf-8 -*-
"""La ficha de la cita dice cuanto dura.

POR QUE EXISTE
--------------
Pedido por el negocio el 3-sep-2026: no es lo mismo reservar veinte minutos que
tres horas, y el cliente necesita saberlo para organizarse el dia.

OJO AL MATIZ, porque parece contradecir otra regla. La duenya del salon se quejo
de lo contrario -"no le he preguntado nada del tiempo que dura, todo eso no tiene
que decirlo"- y hay un freno (`duracion_que_no_pidio`) que impide soltar
duraciones CHARLANDO. Son cosas distintas:

    en la conversacion   soltar "dura 440 minutos" sin que lo pregunten -> FRENADO
    en la ficha de cita  "Corte senora / 20 min" en el resumen          -> BIEN

La duracion sale del MISMO resolutor que aparta el hueco
(`agenda._service_duration_minutes`), asi que lo que lee el cliente y lo que se le
guarda no pueden discrepar. Calcularlo aparte es el fallo que costo una tarde con
las duraciones inventadas.
"""
from __future__ import annotations

import inspect

from test_booking_exhaustive import api_module  # noqa: F401


def test_formato_humano(api_module):
    from backend import textnorm

    assert textnorm.duracion_humana(20) == "20 min"
    assert textnorm.duracion_humana(60) == "1 h"
    assert textnorm.duracion_humana(90) == "1 h 30 min"
    assert textnorm.duracion_humana(180) == "3 h"
    # Sin duracion no se inventa nada.
    assert textnorm.duracion_humana(0) == ""
    assert textnorm.duracion_humana(None) == ""


def test_no_dice_la_palabra_minutos(api_module):
    """"min" y no "minutos": es una ficha, y ademas no choca con el freno."""
    from backend import textnorm

    for m in (20, 90, 440):
        assert "minutos" not in textnorm.duracion_humana(m)


def test_sale_del_mismo_resolutor_que_la_agenda(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_duracion_del_servicio)
    assert "_service_duration_minutes" in fuente, (
        "calcularla aparte hace que lo que lee el cliente y lo que se le guarda "
        "puedan discrepar"
    )


def test_esta_en_el_resumen_y_en_la_confirmacion(api_module):
    from backend import whatsapp

    resumen = inspect.getsource(whatsapp._wa_send_booking_summary)
    assert "_wa_duracion_del_servicio(" in resumen, "falta en el resumen que firma"

    confirmacion = inspect.getsource(whatsapp._wa_create_booking)
    assert "_wa_duracion_del_servicio(" in confirmacion, (
        "falta en la confirmacion y en la reserva pendiente de pago"
    )
