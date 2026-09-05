# -*- coding: utf-8 -*-
"""No se le mueve la cita a un dia que ella no ha elegido.

POR QUE EXISTE
--------------
Medido el 5-sep-2026 sobre 100 conversaciones: `reprogramar` era lo peor del
producto (57 %). La conversacion que lo enseña:

    ELLA: tengo una cita el 8 y no puedo ir, puedo moverla a otro dia?
    IA:   he reprogramado tu cita para el miercoles 9 a las 20:00
    ELLA: el 9 es jueves, podrias moverlo a otro dia?
    IA:   he reprogramado tu cita para el jueves 10 a las 20:00
    ELLA: el 10 es viernes, puedes moverlo a otra fecha?
    IA:   he reprogramado tu cita para el martes 15 a las 20:00

Ella nunca eligio un dia: preguntaba SI se podia mover. El asistente la movio
tres veces por su cuenta. La duenya lo dejo dicho: "le preguntas que dia le viene
bien", y "a partir de la tercera le ofrecemos llamar".

Es el gemelo del freno de la HORA, que ya existia: alli la hora salia de la
manga, aqui el dia.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


class _Estado:
    dia_le_da_igual = False
    fecha_de_los_huecos = ""
    fecha = ""
    veces_movida = 0


@pytest.fixture
def sin_citas(monkeypatch):
    from backend import booking

    monkeypatch.setattr(booking, "citas_vivas_del_telefono", lambda *a, **k: [])


# ─── 1. Cuando NO se puede mover sola ──────────────────────────────────────

@pytest.mark.parametrize("dicho", [
    "tengo una cita el 8 y no puedo ir, puedo moverla a otro dia?",
    "no puedo ir, hay que cambiarla",
    "necesito cambiar mi cita",
])
def test_no_la_mueve_a_un_dia_que_no_ha_pedido(api_module, sin_citas, dicho):  # noqa: F811
    from backend import agent

    assert agent._dia_que_nadie_ha_pedido("demo", _Estado(), dicho, "2026-09-09", "34600111222")


# ─── 2. Cuando SI ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("dicho,fecha", [
    ("el jueves me viene bien", "2026-09-10"),   # el 10 de sept de 2026 es jueves
    ("muevela al 12", "2026-09-12"),
    ("el 12 de septiembre", "2026-09-12"),
])
def test_si_ella_dice_ESE_dia_se_mueve(api_module, sin_citas, dicho, fecha):  # noqa: F811
    from backend import agent

    assert not agent._dia_que_nadie_ha_pedido("demo", _Estado(), dicho, fecha, "34600111222")


def test_manana_es_manana_de_verdad(api_module, sin_citas):  # noqa: F811
    import datetime

    from backend import agent

    manana = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    assert not agent._dia_que_nadie_ha_pedido("demo", _Estado(), "manana mejor", manana, "34600111222")


def test_el_dia_que_dice_tiene_que_ser_ESE(api_module, sin_citas):  # noqa: F811
    """Pide el 12 y el modelo la mueve al 9: eso es inventarselo igual."""
    from backend import agent

    assert agent._dia_que_nadie_ha_pedido("demo", _Estado(), "muevela al 12",
                                          "2026-09-09", "34600111222")


def test_el_dia_que_se_le_ofrecio_vale(api_module, sin_citas):  # noqa: F811
    """Si le enseñamos los huecos de ese dia, moverla ahi no es inventarselo."""
    from backend import agent

    estado = _Estado()
    estado.fecha_de_los_huecos = "2026-09-09"
    assert not agent._dia_que_nadie_ha_pedido("demo", estado, "esa me vale", "2026-09-09", "34600111222")


def test_si_le_da_igual_el_dia_no_se_le_pregunta(api_module, sin_citas):  # noqa: F811
    from backend import agent

    estado = _Estado()
    estado.dia_le_da_igual = True
    assert not agent._dia_que_nadie_ha_pedido("demo", estado, "me da igual", "2026-09-09", "34600111222")


def test_cambiar_solo_la_hora_del_mismo_dia_no_es_moverla_de_dia(api_module, monkeypatch):  # noqa: F811
    from backend import agent, booking

    monkeypatch.setattr(booking, "citas_vivas_del_telefono",
                        lambda *a, **k: [{"booking_date": "2026-09-09", "booking_time": "20:00"}])
    assert not agent._dia_que_nadie_ha_pedido("demo", _Estado(), "mejor mas temprano",
                                              "2026-09-09", "34600111222")


# ─── 3. A la tercera, se le ofrece llamar ──────────────────────────────────

def test_a_la_tercera_vez_se_le_ofrece_llamar(api_module, monkeypatch):  # noqa: F811
    from backend import agent, clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": "600 100 200"}, "booking": {}})
    salida = agent._con_el_telefono_si_hace_falta(
        "demo", "puedes moverla otra vez?", "Listo, te la he movido.", True, veces_movida=3)
    assert "600 100 200" in salida


def test_las_dos_primeras_veces_no_se_le_ofrece(api_module, monkeypatch):  # noqa: F811
    """Ofrecer el telefono al primer cambio es echarla del canal."""
    from backend import agent, clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": "600 100 200"}, "booking": {}})
    for veces in (0, 1, 2):
        salida = agent._con_el_telefono_si_hace_falta(
            "demo", "puedes moverla?", "Listo, te la he movido.", True, veces_movida=veces)
        assert "600 100 200" not in salida, veces
