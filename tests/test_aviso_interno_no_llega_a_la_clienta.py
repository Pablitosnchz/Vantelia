# -*- coding: utf-8 -*-
"""El aviso "ya tiene una cita a esa hora" es para el modelo, no para la clienta.

POR QUE EXISTE
--------------
Simulacion de Alicia (23-sep-2026): tras confirmar su cita, cada "gracias" de la
clienta le traia por WhatsApp, tres veces seguidas:

    ⚠️ Esta persona ya tiene una cita a esa hora (R-027742, Diagnostico y
    presupuesto). Si quiere otra cosa, hay que CAMBIAR esa cita, no crear una segunda.

Es el texto del freno de citas duplicadas del nucleo, escrito para el MODELO.
WhatsApp reenviaba cualquier `detail` con un triangulo delante.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from test_booking_exhaustive import api_module, client  # noqa: F401

DETALLE = ("Esta persona ya tiene una cita a esa hora (R-027742, Diagnostico y presupuesto). "
           "Si quiere otra cosa, hay que CAMBIAR esa cita, no crear una segunda.")


def test_se_reconoce_el_aviso_y_su_codigo(api_module):  # noqa: F811
    from backend import booking

    assert booking.cita_suya_a_esa_hora(DETALLE) == "R-027742"
    assert booking.cita_suya_a_esa_hora("No queda nadie libre a esa hora") == ""


@pytest.fixture()
def resumen_con_cita_ya_cogida(api_module, monkeypatch):  # noqa: F811
    from backend import agenda, booking, messaging, reserva, whatsapp

    enviados = []

    async def texto(*, text, **kwargs):
        enviados.append(text)
        return True

    async def ya_tiene_cita(*a, **k):
        raise HTTPException(status_code=409, detail=DETALLE)

    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(booking, "validar_servicio_publico", lambda *a, **k: None)
    monkeypatch.setattr(agenda, "_validate_booking_window", lambda *a, **k: None)
    monkeypatch.setattr(booking, "_prepare_booking_creation", ya_tiene_cita)
    telefono = "34600888201"
    whatsapp._wa_clear_flow("demo", telefono)
    reserva.olvidar("demo", telefono)
    flow = whatsapp._wa_get_flow("demo", telefono)
    flow.servicio, flow.fecha, flow.hora, flow.nombre = "Consulta", "2030-01-15", "10:00", "Laura"
    flow.employee_id = str(agenda._default_employee_row("demo")["id"])

    def pedir_resumen():
        asyncio.run(whatsapp._wa_send_booking_summary(
            cliente_id="demo", phone_number_id="WA_NUM_ID", to_number=telefono, flow=flow))

    yield telefono, enviados, pedir_resumen
    whatsapp._wa_clear_flow("demo", telefono)
    reserva.olvidar("demo", telefono)


def test_a_la_clienta_no_le_llega_el_texto_interno(resumen_con_cita_ya_cogida):
    _telefono, enviados, pedir_resumen = resumen_con_cita_ya_cogida
    pedir_resumen()
    assert enviados, "algo hay que decirle si es OTRA cita suya"
    for texto in enviados:
        assert "hay que CAMBIAR" not in texto and "Esta persona" not in texto, texto
    assert "Ya tienes una cita a esa hora (R-027742)" in enviados[-1]


def test_si_es_la_cita_que_acaba_de_confirmar_no_se_dice_nada(resumen_con_cita_ya_cogida):
    from backend import reserva

    telefono, enviados, pedir_resumen = resumen_con_cita_ya_cogida
    estado = reserva.cargar("demo", telefono)
    estado.hecho, estado.codigo = True, "R-027742"
    reserva.guardar("demo", telefono, estado)

    pedir_resumen()
    assert enviados == [], enviados
