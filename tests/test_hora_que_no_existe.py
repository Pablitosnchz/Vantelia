# -*- coding: utf-8 -*-
"""No se ensenya un resumen con una hora que no se puede reservar.

POR QUE EXISTE
--------------
10-sep-2026, conversacion real:

    EL    hoy a las 11:55?
    IA    Te agendo una cita para el diagnostico hoy a las 11:55. Lo confirmas?
    IA    [Resumen de tu cita ... 11:55]  [Confirmar] [Cancelar]
    EL    (pulsa Confirmar)
    IA    Ese hueco se acaba de ocupar, carinyo. Ese dia tengo libres: 11:30,
          11:45, 12:00...

La agenda va de quince en quince: las 11:55 NUNCA existieron. Nadie se las
ofrecio, el modelo dio por buena la hora que ella dijo, y el resumen -que es una
PROMESA- salio con una hora que el nucleo iba a rechazar. Encima el mensaje
mentia: no se ocupo, no existia.

REGLA: la hora se comprueba ANTES de ensenyar el resumen, no despues de que ella
pulse. Y si no vale, se le dice la verdad y se le ofrecen las horas reales.
"""
from __future__ import annotations

import asyncio
import datetime

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

CID = "demo"


def _manana():
    from backend import timeutils

    dia = timeutils._utc_now().date() + datetime.timedelta(days=1)
    while dia.weekday() == 6:
        dia += datetime.timedelta(days=1)
    return dia.isoformat()


def test_una_hora_fuera_de_la_rejilla_no_esta_disponible(api_module):  # noqa: F811
    """La comprobacion que faltaba: el nucleo ya lo sabia, el resumen no preguntaba."""
    from backend import agenda

    libre = asyncio.run(agenda._booking_slot_available(CID, _manana(), "11:55"))
    assert not libre, "si la rejilla admite las 11:55, este test deja de probar lo suyo"


def test_el_resumen_comprueba_la_hora_antes_de_prometerla(api_module):  # noqa: F811
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_resumen_para_confirmar)
    assert "_booking_slot_available" in fuente, (
        "el resumen vuelve a prometer horas sin comprobarlas"
    )
    assert fuente.index("_booking_slot_available") < fuente.index("_wa_send_booking_summary")


def test_el_mensaje_no_dice_que_se_ha_ocupado(api_module):  # noqa: F811
    """Decir "se acaba de ocupar" de una hora que no existe es mentir: la clienta
    cree que ha tenido mala suerte y vuelve a intentarlo a las 11:56."""
    from backend import whatsapp

    texto = asyncio.run(whatsapp._wa_hora_que_no_existe(CID, _manana(), "11:55"))
    assert "11:55" in texto
    assert "ocupa" not in texto.lower(), texto


def test_el_mensaje_ofrece_horas_de_verdad(api_module):  # noqa: F811
    from backend import whatsapp

    texto = asyncio.run(whatsapp._wa_hora_que_no_existe(CID, _manana(), "11:55"))
    # Alguna hora real del dia, en punto o en cuarto: sale del mismo helper que
    # usa el fallo al reprogramar.
    import re

    assert re.search(r"\b\d{2}:(00|15|30|45)\b", texto), texto
