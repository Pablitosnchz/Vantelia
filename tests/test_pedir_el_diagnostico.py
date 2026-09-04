# -*- coding: utf-8 -*-
"""Pedir cita para el diagnostico es una peticion COMPLETA, no un detalle.

POR QUE EXISTE
--------------
Reportado por la duenya del salon el 5-sep-2026, con la conversacion delante:

    CLIENTA: me puedes agendar una cita para un diagnostico
    IA:      Para agendarte la cita de diagnostico, necesito saber como tienes
             el pelo de largo. Es corto, medio, largo o extra largo?
    CLIENTA: (audio) lo que me gustaria es que me dieras una cita para hacerme
             un diagnostico, que me veais el cabello
    IA:      Para agendarte la cita de diagnostico, necesito saber como tienes
             el pelo de largo...

El diagnostico son 15 minutos y NO depende del largo del pelo. La pregunta salia
porque al buscar el servicio se arrastra todo lo que la clienta ha dicho antes
-que es lo correcto para "unas mechas" + "lo tengo por los hombros"-, y en esa
conversacion habia hablado de alisados: el catalogo veia "alisado ... mechas ...
diagnostico" y pedia el largo para desambiguar entre alisados.

Solo se reproduce con conversacion larga: en un chat recien empezado funcionaba,
que es por lo que no se habia visto antes.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def con_valoracion(monkeypatch):
    """El negocio tiene cita de diagnostico. Sin ella, nada de esto aplica."""
    from backend import booking

    monkeypatch.setattr(
        booking, "_servicio_de_valoracion",
        lambda cliente_id, **kw: {"slug": "diagnostico_y_presupuesto",
                                  "nombre": "Diagnostico y presupuesto"},
    )


# ─── 1. Que cuenta como pedir el diagnostico ───────────────────────────────

@pytest.mark.parametrize("dicho", [
    "diagnostico",
    "una cita para un diagnostico",
    "quiero que me hagais un diagnóstico",
    "prefiero una valoracion primero",
    "podeis valorarme el pelo?",
])
def test_pide_el_diagnostico(api_module, con_valoracion, dicho):  # noqa: F811
    from backend import agent

    assert agent._pide_la_valoracion("demo", dicho), dicho


@pytest.mark.parametrize("dicho", [
    "unas mechas",
    "lo tengo por los hombros",
    "un alisado de queratina",
    "",
])
def test_no_pide_el_diagnostico(api_module, con_valoracion, dicho):  # noqa: F811
    from backend import agent

    assert not agent._pide_la_valoracion("demo", dicho), dicho


def test_sin_cita_de_diagnostico_configurada_no_aplica(api_module, monkeypatch):  # noqa: F811
    """Un negocio que no tiene esa cita no cambia de comportamiento."""
    from backend import agent, booking

    monkeypatch.setattr(booking, "_servicio_de_valoracion", lambda cliente_id, **kw: None)
    assert not agent._pide_la_valoracion("demo", "quiero un diagnostico")


# ─── 2. Que se le pasa al catalogo ─────────────────────────────────────────

def test_el_diagnostico_no_arrastra_lo_dicho_antes(api_module, con_valoracion):  # noqa: F811
    """El fallo reportado: se buscaba "alisado ... diagnostico" y pedia el largo."""
    from backend import agent

    descripcion, acumulado = agent._descripcion_para_buscar(
        "demo", "un diagnostico", "un alisado, no se cual. mechas, matiz o tinte",
    )
    assert descripcion == "un diagnostico"
    assert "alisado" not in descripcion
    # Y deja de arrastrarlo, o la siguiente vuelta repite el fallo.
    assert acumulado == ""


def test_lo_que_completa_el_servicio_si_se_acumula(api_module, con_valoracion):  # noqa: F811
    """Sin esto vuelve el fallo que ese codigo vino a arreglar."""
    from backend import agent

    descripcion, acumulado = agent._descripcion_para_buscar(
        "demo", "lo tengo por los hombros", "unas mechas",
    )
    assert "mechas" in descripcion and "hombros" in descripcion
    assert acumulado == "unas mechas"


def test_no_se_repite_lo_que_ya_estaba(api_module, con_valoracion):  # noqa: F811
    from backend import agent

    descripcion, _ = agent._descripcion_para_buscar("demo", "mechas", "unas mechas largas")
    assert descripcion == "unas mechas largas"


def test_sin_nada_acumulado_se_pasa_lo_dicho(api_module, con_valoracion):  # noqa: F811
    from backend import agent

    descripcion, acumulado = agent._descripcion_para_buscar("demo", "unas mechas", "")
    assert descripcion == "unas mechas"
    assert acumulado == ""
