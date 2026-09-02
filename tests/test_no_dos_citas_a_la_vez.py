# -*- coding: utf-8 -*-
"""Nadie puede tener dos citas a la misma hora.

POR QUE EXISTE
--------------
Salio en la simulacion del 2-sep-2026, dos veces de treinta conversaciones:

    ELLA  quiero unas mechas ... me viene bien a las 11:00
    IA    [confirma "Mechas medio", jueves 11:00, R-xxxx]
    ELLA  ahora que lo pienso, mejor solo quiero cortarme las puntas
    IA    [confirma "Corte mecha", jueves 11:00, R-yyyy]

Dos citas a la vez para la misma persona, la primera sin cancelar, y el negocio
con el hueco ocupado dos veces. Cambiar de servicio es CAMBIAR la cita, no coger
otra.

Habia un antiduplicados, pero solo en la voz y solo para citas identicas dentro
de la misma llamada: no cubria esto (clase 17 de docs/CAZA_DE_FALLOS.md, el freno
que solo protege un camino).
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def test_se_detecta_la_cita_que_se_solapa(api_module, monkeypatch):
    from backend import booking

    fila = {"id": "bk_1", "booking_code": "R-1111", "servicio": "Mechas medio",
            "booking_time": "11:00", "telefono": "34600700021"}

    monkeypatch.setattr(booking.db, "_get_db_connection", lambda: _conexion([fila]))
    monkeypatch.setattr(booking.agenda, "_service_duration_minutes",
                        lambda *a, **k: 60)

    encontrada = booking._cita_suya_a_esa_hora(
        "demo", "34600700021", "2026-09-03", "11:30", 60, "whatsapp",
    )

    assert encontrada is not None, "11:30 cae dentro de una cita de 11:00 a 12:00"


def test_dos_citas_seguidas_si_valen(api_module, monkeypatch):
    """A las 12:00 despues de una de 11:00 a 12:00 no se solapa: es legitimo."""
    from backend import booking

    fila = {"id": "bk_1", "booking_code": "R-1111", "servicio": "Mechas medio",
            "booking_time": "11:00", "telefono": "34600700021"}
    monkeypatch.setattr(booking.db, "_get_db_connection", lambda: _conexion([fila]))
    monkeypatch.setattr(booking.agenda, "_service_duration_minutes", lambda *a, **k: 60)

    assert booking._cita_suya_a_esa_hora(
        "demo", "34600700021", "2026-09-03", "12:00", 30, "whatsapp",
    ) is None


def test_el_mostrador_no_se_frena(api_module, monkeypatch):
    """Dos ninyos de la misma madre a la vez con dos profesionales es normal."""
    from backend import booking

    fila = {"id": "bk_1", "booking_code": "R-1111", "servicio": "Corte ninyo",
            "booking_time": "11:00", "telefono": "34600700021"}
    monkeypatch.setattr(booking.db, "_get_db_connection", lambda: _conexion([fila]))
    monkeypatch.setattr(booking.agenda, "_service_duration_minutes", lambda *a, **k: 30)

    assert booking._cita_suya_a_esa_hora(
        "demo", "34600700021", "2026-09-03", "11:00", 30, "portal_manual",
    ) is None


def test_otro_telefono_no_se_confunde(api_module, monkeypatch):
    from backend import booking

    fila = {"id": "bk_1", "booking_code": "R-1111", "servicio": "Mechas",
            "booking_time": "11:00", "telefono": "34600700099"}
    monkeypatch.setattr(booking.db, "_get_db_connection", lambda: _conexion([fila]))
    monkeypatch.setattr(booking.agenda, "_service_duration_minutes", lambda *a, **k: 60)

    assert booking._cita_suya_a_esa_hora(
        "demo", "34600700021", "2026-09-03", "11:00", 60, "whatsapp",
    ) is None


class _conexion:
    """Una conexion de mentira que devuelve las filas que se le den."""

    def __init__(self, filas):
        self._filas = filas

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        return self

    def fetchall(self):
        return self._filas
