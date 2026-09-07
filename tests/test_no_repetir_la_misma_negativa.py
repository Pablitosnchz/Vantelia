# -*- coding: utf-8 -*-
"""Decirle que no dos veces basta: a la tercera se le ofrece el telefono.

POR QUE EXISTE
--------------
Medido el 7-sep-2026, tirada de 100. La clienta pide extensiones sin diagnostico
y recibe CINCO negativas seguidas, cada una con otras palabras, hasta que se
rinde:

    ELLA: podrian ponerme las extensiones sin diagnostico?
    IA:   para las extensiones es necesario hacer un diagnostico previo...
    ELLA: solo quiero ponerme las extensiones, puedo agendar directamente?
    IA:   para poner las extensiones es necesario hacer un diagnostico previo...
    ELLA: no quiero pasar por el diagnostico, hay alguna forma?
    IA:   para las extensiones adhesivas es necesario hacer un diagnostico...

La regla del negocio es CORRECTA y no se toca: en extensiones el diagnostico es
obligatorio. Lo que faltaba era la salida.

`_ya_se_le_dijo` no valia aqui: compara texto identico y el agente reformula cada
vez. Este mira el PARECIDO, que es lo que nota la clienta.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


def test_dos_frases_distintas_que_dicen_lo_mismo_se_parecen(api_module):  # noqa: F811
    from backend import catalog_pick

    a = "Lo siento, para poner las extensiones es necesario hacer un diagnostico previo"
    b = "Lo siento, para las extensiones adhesivas es necesario hacer un diagnostico previo"

    def palabras(s):
        return {p for p in catalog_pick._norm(s)[:400].split() if len(p) > 3}

    comunes = palabras(a) & palabras(b)
    total = palabras(a) | palabras(b)
    assert len(comunes) / float(len(total)) >= 0.45


def test_la_salida_lleva_el_telefono_del_negocio(api_module, monkeypatch):  # noqa: F811
    from backend import clients, whatsapp

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": "600 100 200"}, "booking": {}})
    salida = whatsapp._con_salida_amable("demo", "No podemos hacer excepciones.")
    assert "600 100 200" in salida
    assert salida.startswith("No podemos hacer excepciones.")


def test_no_se_repite_el_telefono_si_ya_estaba(api_module, monkeypatch):  # noqa: F811
    from backend import clients, whatsapp

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": "600 100 200"}, "booking": {}})
    ya = whatsapp._con_salida_amable("demo", "No podemos.")
    assert whatsapp._con_salida_amable("demo", ya).count("600 100 200") == 1


def test_sin_telefono_publicado_no_se_inventa_salida(api_module, monkeypatch):  # noqa: F811
    from backend import clients, whatsapp

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": ""}, "booking": {}})
    assert whatsapp._con_salida_amable("demo", "No podemos.") == "No podemos."


def test_un_texto_corto_no_cuenta_como_repeticion(api_module):  # noqa: F811
    """Con "Vale" o "Perfecto" no se puede juzgar que sea repetir."""
    from backend import whatsapp

    assert not whatsapp._se_esta_repitiendo("demo", "34600111000", "Vale, perfecto.")
