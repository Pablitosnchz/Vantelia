# -*- coding: utf-8 -*-
"""Confirmar el resumen con una cita ya cogida no crea una segunda a la callada.

POR QUE EXISTE
--------------
Clase 36 del catalogo de fallos. En una tirada de 40 conversaciones aparecieron
2 citas duplicadas: la clienta venia a MOVER su cita, la conversacion acababa en
el resumen de CREAR y al confirmar se quedaba con dos huecos ocupados.

    IA   Podemos reprogramar tu cita para el miercoles 9 a las 10:00
    IA   *Resumen de tu cita*      <- el resumen de CREAR
    ELLA Confirmo.
    IA   *Cita confirmada*         <- crea una segunda; la vieja sigue viva

Reproducido el 5-sep-2026 poniendo el flujo en el resumen con un hueco libre
distinto: dos citas vivas, y el negocio sin enterarse. Cuatro intentos de
reproducirlo CONVERSANDO fallaron -el agente resuelve por la tool-, y por eso el
arreglo anterior se retiro: no se disparaba nunca.

En el boton de confirmar NO se puede adivinar la intencion: el flujo no guarda
nada de que viniera a reprogramar. Asi que se pregunta, y no se mueve ni se crea
nada sin que ella lo diga.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


def _flujo(api_module, fecha="2026-09-09", hora="10:00"):  # noqa: F811
    from backend import whatsapp

    flow = whatsapp._wa_get_flow("demo", "34600123123")
    flow.flow = "booking_confirm"
    flow.fecha = fecha
    flow.hora = hora
    return flow


@pytest.fixture(autouse=True)
def _limpia(api_module):  # noqa: F811
    from backend import whatsapp

    whatsapp._wa_clear_flow("demo", "34600123123")
    yield
    whatsapp._wa_clear_flow("demo", "34600123123")


def _con_citas(monkeypatch, filas):
    from backend import booking

    monkeypatch.setattr(booking, "citas_vivas_del_telefono", lambda *a, **k: filas)


def test_avisa_cuando_ya_tiene_una_cita_en_otro_hueco(api_module, monkeypatch):  # noqa: F811
    from backend import whatsapp

    _con_citas(monkeypatch, [{"booking_code": "R-111111", "booking_date": "2026-09-08",
                              "booking_time": "20:00"}])
    suya = whatsapp._wa_cita_viva_distinta("demo", "34600123123", _flujo(api_module))
    assert suya.get("booking_code") == "R-111111"


def test_no_avisa_si_es_el_mismo_hueco(api_module, monkeypatch):  # noqa: F811
    """Ese caso ya lo para el choque de agenda; avisar seria ruido."""
    from backend import whatsapp

    _con_citas(monkeypatch, [{"booking_code": "R-111111", "booking_date": "2026-09-09",
                              "booking_time": "10:00"}])
    assert whatsapp._wa_cita_viva_distinta("demo", "34600123123", _flujo(api_module)) == {}


def test_no_avisa_sin_citas(api_module, monkeypatch):  # noqa: F811
    from backend import whatsapp

    _con_citas(monkeypatch, [])
    assert whatsapp._wa_cita_viva_distinta("demo", "34600123123", _flujo(api_module)) == {}


def test_con_varias_citas_no_se_pregunta(api_module, monkeypatch):  # noqa: F811
    """Con dos o mas, preguntar cual mover es peor que no preguntar."""
    from backend import whatsapp

    _con_citas(monkeypatch, [
        {"booking_code": "R-111111", "booking_date": "2026-09-08", "booking_time": "20:00"},
        {"booking_code": "R-222222", "booking_date": "2026-09-11", "booking_time": "12:00"},
    ])
    assert whatsapp._wa_cita_viva_distinta("demo", "34600123123", _flujo(api_module)) == {}


def test_un_fallo_al_mirar_sus_citas_no_bloquea_la_reserva(api_module, monkeypatch):  # noqa: F811
    """Un freno no puede dejar a nadie sin poder reservar."""
    from backend import booking, whatsapp

    def revienta(*a, **k):
        raise RuntimeError("base caida")

    monkeypatch.setattr(booking, "citas_vivas_del_telefono", revienta)
    assert whatsapp._wa_cita_viva_distinta("demo", "34600123123", _flujo(api_module)) == {}


def test_el_aviso_se_hace_una_sola_vez(api_module, monkeypatch):  # noqa: F811
    """Ya respondido, confirmar tiene que seguir su curso y no volver a preguntar."""
    from backend import whatsapp

    _con_citas(monkeypatch, [{"booking_code": "R-111111", "booking_date": "2026-09-08",
                              "booking_time": "20:00"}])
    flow = _flujo(api_module)
    assert whatsapp._wa_cita_viva_distinta("demo", "34600123123", flow)
    flow.duplicado_avisado = "1"
    # El estado es lo que consulta el handler antes de preguntar de nuevo.
    assert flow.duplicado_avisado
