# -*- coding: utf-8 -*-
"""Los tres fallos de la demo del 8-sep-2026, en la misma conversacion.

(El freno de "no elijas por ella" del 3-sep vive en test_no_elige_por_ella.py;
aqui esta la vuelta que dio el 8-sep, cuando se descubrio que quien elegia por
ella era nuestra propia nota anti-repeticion.)

Pablo probo el asistente como una clienta cualquiera y en cuatro minutos salieron
tres cosas distintas, las tres de codigo:

    ELLA  manana
    IA    veo que mencionas "manana", pero no tengo un servicio con ese nombre
    ELLA  un alisado
    IA    Keratina premium o Acido lactico bio premium? Si no estas seguro, en la
          cita te asesoramos
    ELLA  no estoy seguro
    IA    ... te gustaria que te agende una cita de diagnostico?
    ELLA  si
    IA    Ahora necesito saber como tienes el pelo de largo
    ELLA  corto
    IA    tengo disponibilidad de 10:00 a 11:00 ...
    ELLA  a las 10
    IA    puedo reservarte el alisado con Acido lactico bio premium corto. Si en
          la cita prefieres la Keratina, se puede cambiar sin problema

1. Una palabra suelta -un dia, una hora, un "vale"- se tomaba por el nombre de un
   servicio (misma forma que el "gracias" del 4-sep).
2. El "si" al diagnostico no valia: solo contaba escribir la palabra.
3. Eligio la tecnica por ella. Y eso NO lo decidio el modelo: se lo pedia nuestra
   propia nota anti-repeticion ("mojate y recomiendale UNA... dile que en la cita
   se puede cambiar"), que iba despues de la regla del salon y le ganaba.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CID = "demo"


# --------------------------------------------------------------------------- 1
@pytest.mark.parametrize("dicho", [
    "manana", "mañana", "el jueves", "a las 10", "si", "vale", "por la tarde",
    "el martes que viene", "me viene bien manana", "las 10:30",
])
def test_una_palabra_suelta_no_es_un_servicio(api_module, dicho):  # noqa: F811
    from backend import agent

    assert agent._no_dice_ningun_servicio(CID, dicho), dicho


@pytest.mark.parametrize("dicho", [
    "un corte", "quiero un corte manana", "mechas", "unas mechas a las 10",
    "algo para las canas", "tinte y peinado el jueves",
])
def test_lo_que_si_dice_un_servicio_pasa(api_module, dicho):  # noqa: F811
    """Ante la duda se deja pasar: negar un servicio real es peor."""
    from backend import agent

    assert not agent._no_dice_ningun_servicio(CID, dicho), dicho


def test_la_tool_no_devuelve_la_palabra_como_servicio(api_module):  # noqa: F811
    from backend import agent

    salida = agent._tool_buscar_servicio(CID, {"descripcion": "manana"})
    assert salida.get("ok") is False
    assert "no_inventes" in salida
    assert "no existe un servicio" in salida["no_inventes"]


# --------------------------------------------------------------------------- 2
def _conversacion(ofrecido: str):
    return [{"role": "user", "content": "un alisado"},
            {"role": "assistant", "content": ofrecido}]


def test_el_si_al_diagnostico_cuenta_como_pedirlo(api_module, monkeypatch):  # noqa: F811
    from backend import agent, booking

    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda cid, location_id="": {"nombre": "Diagnostico y presupuesto"})
    charla = _conversacion("¿Te gustaria que te agende una cita de diagnostico?")
    for dicho in ("si", "sí", "vale", "si por favor", "claro", "de acuerdo"):
        assert agent._pide_la_valoracion(CID, dicho, mensajes=charla), dicho


def test_el_si_a_otra_cosa_no_cuenta(api_module, monkeypatch):  # noqa: F811
    """Un "si" a "¿te viene bien el jueves?" no es pedir un diagnostico."""
    from backend import agent, booking

    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda cid, location_id="": {"nombre": "Diagnostico y presupuesto"})
    charla = _conversacion("¿Te viene bien el jueves a las 10?")
    assert not agent._pide_la_valoracion(CID, "si", mensajes=charla)


def test_sin_conversacion_se_comporta_como_siempre(api_module):  # noqa: F811
    from backend import agent

    assert not agent._pide_la_valoracion(CID, "si")


def test_el_si_se_busca_por_el_nombre_de_la_valoracion(api_module, monkeypatch):  # noqa: F811
    """Un "si" no se puede mandar al catalogo tal cual: no dice nada."""
    from backend import agent, booking

    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda cid, location_id="": {"nombre": "Diagnostico y presupuesto"})
    charla = _conversacion("¿Quieres que te coja el diagnostico?")
    descripcion, acumulado = agent._descripcion_para_buscar(
        CID, "si", "un alisado", mensajes=charla)
    assert descripcion == "Diagnostico y presupuesto"
    assert acumulado == ""


# --------------------------------------------------------------------------- 3
def test_con_la_regla_escrita_no_se_moja_ofrece_la_valoracion(api_module, monkeypatch):  # noqa: F811
    from backend import agent, booking

    monkeypatch.setattr(agent, "_lo_que_el_negocio_dice_al_recomendar",
                        lambda cid, config=None: "Sin ver tu cabello no te puedo decir cual.")
    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda cid, location_id="": {"nombre": "Diagnostico y presupuesto"})
    nota = agent._nota_al_repetir_la_pregunta(CID)
    assert "NO elijas tu por ella" in nota
    assert "Diagnostico y presupuesto" in nota
    assert "mojate" not in nota
    assert "se puede cambiar" not in nota


def test_sin_regla_escrita_se_sigue_pudiendo_mojar(api_module, monkeypatch):  # noqa: F811
    """Recomendar es legitimo para quien no haya dicho lo contrario."""
    from backend import agent

    monkeypatch.setattr(agent, "_lo_que_el_negocio_dice_al_recomendar",
                        lambda cid, config=None: "")
    assert "mojate" in agent._nota_al_repetir_la_pregunta(CID)


def test_con_regla_pero_sin_valoracion_tampoco_recomienda(api_module, monkeypatch):  # noqa: F811
    from backend import agent, booking

    monkeypatch.setattr(agent, "_lo_que_el_negocio_dice_al_recomendar",
                        lambda cid, config=None: "Eso se ve en persona.")
    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda cid, location_id="": None)
    nota = agent._nota_al_repetir_la_pregunta(CID)
    assert "NO elijas tu por ella" in nota
    assert "mojate" not in nota


def test_la_nota_esta_enchufada_en_el_bucle(api_module):  # noqa: F811
    """Que exista no basta: la tenia que usar el freno de la repeticion."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_nota_al_repetir_la_pregunta" in fuente


# ------------------------------------------------- la tercera pregunta no existe
def _charla_con_dudas():
    return [{"role": "user", "content": "quiero un alisado"},
            {"role": "assistant", "content": "¿Keratina premium o Acido lactico?"},
            {"role": "user", "content": "no estoy segura de cual"},
            {"role": "assistant", "content": "Se decide en la cita. ¿Que dia?"},
            {"role": "user", "content": "manana a las 10"}]


@pytest.fixture
def negocio_que_no_elige(monkeypatch):
    from backend import agent, booking

    monkeypatch.setattr(agent, "_lo_que_el_negocio_dice_al_recomendar",
                        lambda cid, config=None: "Eso se ve en persona.")
    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda cid, location_id="": {"nombre": "Diagnostico y presupuesto"})


def test_a_la_tercera_se_le_coge_la_valoracion(api_module, negocio_que_no_elige):  # noqa: F811
    from backend import agent

    assert agent._hay_que_cogerle_la_valoracion(
        CID, _charla_con_dudas(), 2) == "Diagnostico y presupuesto"


def test_preguntar_dos_veces_todavia_se_aguanta(api_module, negocio_que_no_elige):  # noqa: F811
    from backend import agent

    assert not agent._hay_que_cogerle_la_valoracion(CID, _charla_con_dudas(), 1)


def test_sin_duda_de_ella_no_se_le_impone_nada(api_module, negocio_que_no_elige):  # noqa: F811
    """Si nunca ha dicho que no sabe, se le sigue preguntando: quiza si lo sabe."""
    from backend import agent

    charla = [{"role": "user", "content": "quiero un alisado manana a las 10"}]
    assert not agent._hay_que_cogerle_la_valoracion(CID, charla, 3)


def test_sin_regla_del_negocio_no_se_toca_nada(api_module, monkeypatch):  # noqa: F811
    from backend import agent

    monkeypatch.setattr(agent, "_lo_que_el_negocio_dice_al_recomendar",
                        lambda cid, config=None: "")
    assert not agent._hay_que_cogerle_la_valoracion(CID, _charla_con_dudas(), 3)


def test_el_corte_esta_enchufado(api_module):  # noqa: F811
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_hay_que_cogerle_la_valoracion" in fuente
    assert "estado.veces_falta" in fuente
