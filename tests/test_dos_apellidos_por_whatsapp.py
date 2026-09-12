# -*- coding: utf-8 -*-
"""Clienta nueva por WhatsApp: nombre y DOS apellidos, como en el mostrador.

POR QUE EXISTE
--------------
Decision de Pablo (11-sep-2026). Por WhatsApp bastaba un apellido y se pedia una
sola vez ("insistir por chat es donde se pierden reservas"), pero en la agenda el
salon necesita distinguir a dos clientas que se llaman igual, y el mostrador ya
exige dos apellidos desde el 10-sep. A la clienta CONOCIDA (su telefono ya esta en
la ficha) no se le pide nada.

Ademas: el nombre que se anota al decir "me llamo Ana Ruiz" no puede ganarle al
completo que da despues; si no, el resumen saldria sin el segundo apellido.
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture(autouse=True)
def regla_del_salon(api_module, monkeypatch):
    monkeypatch.setitem(api_module.CONFIG_CLIENTES["demo"]["booking"], "exigir_dos_apellidos", True)


@pytest.mark.parametrize("antes,dice,queda", [
    ("Ana Ruiz", "Pérez", "Ana Ruiz Pérez"),
    ("Ana", "Ruiz Pérez", "Ana Ruiz Pérez"),
    ("Ana Ruiz", "Ana Ruiz Pérez", "Ana Ruiz Pérez"),
    ("Ana Ruiz", "Ruiz Pérez", "Ana Ruiz Pérez"),
])
def test_se_junta_lo_que_falta(api_module, antes, dice, queda):  # noqa: F811
    from backend import textnorm

    assert textnorm.juntar_nombre(antes, dice) == queda


def _crear(nombre, conocida=""):
    from backend import agent

    return asyncio.run(agent._ejecutar(
        "demo", "crear_cita",
        {"servicio": "Consulta", "fecha": "2030-01-15", "hora": "10:00", "nombre": nombre},
        telefono="34600888001", quien={"telefono": "34600888001", "nombre": conocida},
        remate_manual=True, dicho=nombre,
    ))


def test_a_una_clienta_nueva_se_le_piden_los_dos_apellidos(api_module):  # noqa: F811
    resultado = _crear("Ana Ruiz")

    assert resultado["ok"] is False
    assert not resultado.get("pendiente_de_confirmacion"), "no puede llegar al resumen"
    assert "apellidos" in resultado["error"].lower()


def test_con_los_dos_apellidos_sigue_al_resumen(api_module):  # noqa: F811
    assert _crear("Ana Ruiz Pérez").get("pendiente_de_confirmacion") is True


def test_a_una_clienta_conocida_no_se_le_piden(api_module):  # noqa: F811
    assert _crear("Ana Ruiz", conocida="Ana Ruiz").get("pendiente_de_confirmacion") is True


def test_a_una_conocida_con_solo_nombre_tampoco_se_le_piden(api_module):  # noqa: F811
    assert _crear("Ana", conocida="Ana").get("pendiente_de_confirmacion") is True


def test_el_nombre_completo_llega_al_resumen(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_intencion(estado, "reservar")
    reserva.anotar_lo_que_dice(estado, "me llamo Ana Ruiz")
    assert estado.nombre == "Ana Ruiz"

    reserva.anotar_resultado(
        estado, "crear_cita",
        {"servicio": "Corte", "fecha": "2030-01-15", "hora": "10:00", "nombre": "Ana Ruiz Pérez"},
        {"ok": False, "pendiente_de_confirmacion": True},
    )

    assert estado.nombre == "Ana Ruiz Pérez"


def test_el_flujo_con_listas_los_pide_hasta_tenerlos(api_module, monkeypatch):  # noqa: F811
    from backend import messaging, whatsapp

    enviados, resumenes = [], []

    async def texto(*, text, **kwargs):
        enviados.append(text)
        return True

    async def resumen(**kwargs):
        resumenes.append(kwargs["flow"].nombre)

    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(whatsapp, "_wa_send_booking_summary", resumen)
    telefono = "34600888010"
    whatsapp._wa_clear_flow("demo", telefono)
    whatsapp._wa_get_flow("demo", telefono).flow = "booking_name"

    def dice(frase):
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id="WA_NUM_ID", from_number=telefono,
            incoming_text=frase, interactive_id="", request=None,
        ))

    try:
        dice("Ana")
        dice("Ruiz")
        assert resumenes == [], "con un solo apellido no se pasa al resumen"
        assert "segundo apellido" in enviados[-1]
        dice("Pérez")
        assert resumenes == ["Ana Ruiz Pérez"]
    finally:
        whatsapp._wa_clear_flow("demo", telefono)
