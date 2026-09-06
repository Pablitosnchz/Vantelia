# -*- coding: utf-8 -*-
"""Repetir "confirmo" con la cita ya hecha no vuelve a empezar.

POR QUE EXISTE
--------------
Medido el 6-sep-2026. Con la cita YA creada, la clienta escribe "confirmo" otra
vez -algo normal: no ha visto el mensaje, o quiere asegurarse- y pasaba esto:

    ELLA: confirmo
    IA:   *Cita confirmada*  R-563007          <- bien
    ELLA: confirmo
    IA:   "parece que no tenemos el servicio de corte de senora en nuestro
           catalogo"                            <- FALSO, y de los graves
    ELLA: ya he confirmado varias veces, solo quiero que me agenden la cita
    IA:   *Resumen de tu cita* ...              <- otra vez, a un paso de duplicar

El agente no sabia que la cita existia y volvia a empezar. La verdad esta en la
agenda, no en lo que el modelo recuerde: se mira ahi antes de dejarle contestar.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CID = "demo"
TEL = "34600333111"
CITA = {"booking_code": "R-563007", "booking_date": "2026-09-08",
        "booking_time": "13:30", "servicio": "Corte senora"}


@pytest.fixture
def con_cita_hecha(api_module, monkeypatch):  # noqa: F811
    from backend import booking, reserva

    estado = reserva.cargar(CID, TEL)
    estado.hecho = True
    reserva.guardar(CID, TEL, estado)
    monkeypatch.setattr(booking, "citas_vivas_del_telefono", lambda *a, **k: [CITA])
    yield
    estado.hecho = False


@pytest.mark.parametrize("mensaje", [
    "confirmo",
    "si",
    "ya he confirmado varias veces, solo quiero que me agenden la cita",
    "te lo he confirmado ya",
])
def test_se_le_dice_lo_que_ya_tiene(api_module, con_cita_hecha, mensaje):  # noqa: F811
    from backend import whatsapp

    texto = whatsapp._wa_cita_recien_hecha(CID, TEL, mensaje)
    assert "R-563007" in texto
    assert "13:30" in texto


@pytest.mark.parametrize("mensaje", [
    "mejor el jueves",
    "cancelala por favor",
    "cuanto cuesta un alisado?",
    "quiero otra cita para mi hija",
])
def test_lo_que_no_es_confirmar_sigue_su_camino(api_module, con_cita_hecha, mensaje):  # noqa: F811
    """Solo se corta la pura confirmacion: lo demas lo lleva el agente."""
    from backend import whatsapp

    assert whatsapp._wa_cita_recien_hecha(CID, TEL, mensaje) == ""


def test_sin_cita_hecha_no_se_corta_nada(api_module, monkeypatch):  # noqa: F811
    from backend import booking, reserva, whatsapp

    estado = reserva.cargar(CID, TEL)
    estado.hecho = False
    reserva.guardar(CID, TEL, estado)
    monkeypatch.setattr(booking, "citas_vivas_del_telefono", lambda *a, **k: [CITA])
    assert whatsapp._wa_cita_recien_hecha(CID, TEL, "confirmo") == ""


def test_si_falla_la_consulta_sigue_el_agente(api_module, monkeypatch):  # noqa: F811
    """Un freno no puede dejar a nadie sin respuesta."""
    from backend import booking, reserva, whatsapp

    estado = reserva.cargar(CID, TEL)
    estado.hecho = True
    reserva.guardar(CID, TEL, estado)

    def revienta(*a, **k):
        raise RuntimeError("base caida")

    monkeypatch.setattr(booking, "citas_vivas_del_telefono", revienta)
    assert whatsapp._wa_cita_recien_hecha(CID, TEL, "confirmo") == ""
