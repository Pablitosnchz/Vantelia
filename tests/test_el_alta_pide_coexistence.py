# -*- coding: utf-8 -*-
"""El alta de WhatsApp tiene que pedir COEXISTENCE por los dos caminos.

POR QUE EXISTE
--------------
9-sep-2026, probando el alta de verdad con un numero real: Meta contesto

    "Este numero de telefono ya esta registrado en una cuenta de WhatsApp.
     Para usar este numero, desvinculalo de la cuenta actual."

No era Meta poniendo pegas: el boton del panel lanzaba el alta CLASICA (dar de
alta un numero nuevo en la Cloud API), que exige un numero que no este en
WhatsApp. Coexistence -que el numero siga en la app del movil y el asistente
responda en paralelo- se pide con `featureType`, y el enlace alojado si lo
mandaba pero el boton del panel no.

Importa porque el caso del error es el de TODOS los clientes: un negocio que ya
trabaja con su numero. Sin Coexistence habria que pedirle que lo desvincule de su
movil, que es exactamente lo que le prometimos que no haria falta.
"""
from __future__ import annotations

import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1]
COEXISTENCE = "whatsapp_business_app_onboarding"


def test_el_boton_del_panel_pide_coexistence():
    panel = (RAIZ / "app_ui" / "index.html").read_text(encoding="utf-8")
    i = panel.find("FB.login(")
    assert i > 0, "no se encuentra el lanzador del alta en el panel"
    trozo = panel[i:i + 600]
    assert COEXISTENCE in trozo, (
        "el alta del panel no pide Coexistence: Meta ofrecera dar de alta un numero "
        "NUEVO y rechazara el numero que el negocio ya usa"
    )


def test_el_enlace_alojado_pide_coexistence():
    fuente = (RAIZ / "backend" / "wa_onboarding.py").read_text(encoding="utf-8")
    assert COEXISTENCE in fuente
