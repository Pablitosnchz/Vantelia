# -*- coding: utf-8 -*-
"""No se niega un servicio que el salon SI hace.

POR QUE EXISTE
--------------
Medido en produccion el 2-sep-2026, probando otra cosa:

    ELLA  cuanto dura un corte de senora?
    IA    En nuestro catalogo no tenemos un servicio especifico llamado
          "corte de senora", pero ofrecemos varios tipos de cortes...

`Corte senora` existe: 20 minutos, 20 EUR, activo. Negar un servicio que si se
hace es de los fallos criticos del banco -es perder una clienta- y estaba
prohibido en el PROMPT ("antes de decir que NO haceis algo, buscalo en esta
lista"). Una instruccion se desobedece; este es el freno en codigo.

Se comprueba contra las FAMILIAS del catalogo, no contra el nombre exacto: la
clienta dice "corte de senora" y en el catalogo pone "Corte senora".
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def test_no_niega_lo_que_el_salon_si_hace(api_module, monkeypatch):
    from backend import catalog_pick, chat

    monkeypatch.setattr(catalog_pick, "familias_pedidas", lambda cid, t: ["cortes"])

    salida = chat._sin_negar_un_servicio_que_existe(
        "demo",
        "En nuestro catalogo no tenemos un servicio especifico llamado corte de "
        "senora, pero ofrecemos varios tipos. Cual prefieres?",
        "cuanto dura un corte de senora?",
    )

    assert "no tenemos" not in salida.lower()
    assert "si lo hacemos" in salida.lower()
    # Y lo que venia detras se conserva: sin eso la respuesta queda coja.
    assert "cual prefieres" in salida.lower()


def test_lo_que_de_verdad_no_hacen_se_sigue_negando(api_module, monkeypatch):
    """Si el salon no hace manicura, decirlo es lo correcto."""
    from backend import catalog_pick, chat

    monkeypatch.setattr(catalog_pick, "familias_pedidas", lambda cid, t: [])

    original = "No tenemos un servicio de manicura en nuestro catalogo."

    assert chat._sin_negar_un_servicio_que_existe("demo", original, "haceis manicura?") == original


def test_una_respuesta_sin_negativas_no_se_toca(api_module):
    from backend import chat

    original = "El corte de senora dura 20 minutos. ¿Que dia prefieres?"

    assert chat._sin_negar_un_servicio_que_existe("demo", original, "cuanto dura?") == original


def test_ante_un_fallo_no_se_rompe_la_respuesta(api_module, monkeypatch):
    from backend import catalog_pick, chat

    def _revienta(cid, t):
        raise RuntimeError("catalogo caido")

    monkeypatch.setattr(catalog_pick, "familias_pedidas", _revienta)
    original = "No tenemos ese servicio en nuestro catalogo."

    assert chat._sin_negar_un_servicio_que_existe("demo", original, "algo") == original
