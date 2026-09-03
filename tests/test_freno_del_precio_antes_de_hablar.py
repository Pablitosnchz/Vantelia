# -*- coding: utf-8 -*-
"""Si la cita se va a parar, el agente no habla primero.

POR QUE EXISTE
--------------
3-sep-2026. El freno que impide cogerle el TRATAMIENTO a quien vino preguntando
el precio estaba pegado al resumen, y el resumen se manda DESPUES del mensaje del
agente. Resultado, en el mismo turno:

    IA  Ana, para confirmar, tenemos el servicio de mechas o balayage corto el
        jueves 4 de septiembre a las 10:00.
    IA  Te lo digo con sinceridad: el precio depende mucho de tu pelo... ¿Te cojo
        la cita de valoracion?

Dos mensajes que se contradicen. El segundo reabre la pregunta que ella acababa
de contestar, y el simulador lo cuenta -con razon- como repetir la misma
pregunta.

MEDIDO con `--persona mechas-precio`, 8 conversaciones, misma semilla:

    el agente habla primero   37,5 % consigue lo que queria   (4 repite)
    el freno va antes         50,0 %                          (3 repite)

Fue el cuarto intento sobre esta clase de fallo; los tres anteriores iban a que
eligiera bien el servicio y los tres salieron PEORES. Lo que fallaba no era la
eleccion, era el orden.
"""
from __future__ import annotations

import inspect

from test_booking_exhaustive import api_module  # noqa: F401


def test_el_freno_va_antes_que_el_texto_del_agente(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_resumen_para_confirmar)

    freno = fuente.index("_wa_freno_del_precio(")
    habla = fuente.index("text=texto_previo,")
    assert freno < habla, (
        "si el agente habla antes, la clienta recibe su confirmacion y acto "
        "seguido el freno diciendole que esa cita no se le puede coger"
    )


def test_si_frena_no_se_manda_nada_mas(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_resumen_para_confirmar)
    trozo = fuente[fuente.index("_wa_freno_del_precio("):]
    trozo = trozo[:trozo.index("if texto_previo:")]

    assert "return True" in trozo, (
        "el freno ya explica la regla y ofrece la valoracion: se basta solo"
    )
