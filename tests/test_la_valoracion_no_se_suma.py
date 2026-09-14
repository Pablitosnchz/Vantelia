# -*- coding: utf-8 -*-
"""A «¿cuánto duran?» la cita de valoración no se suma al tratamiento que la exige.

POR QUE EXISTE
--------------
14-sep-2026, prueba de Pablo por WhatsApp sobre el negocio de Alicia:

    ELLA: cuánto duran las extensiones?
    ELLA: Diagnostico y presupuesto
    ELLA: quiero saber cuánto duran
      IA: Las extensiones adhesivas tardan 45 minutos, y el diagnóstico y presupuesto son
          15 minutos. En total, serían 60 minutos.

En su negocio las extensiones exigen diagnóstico antes (`booking.valoracion_obligatoria`):
son DOS citas. `_cuanto_duran_juntos` sumaba la valoración con lo que se valora y cogía el
diagnóstico genérico (15 min) teniendo uno para extensiones (25 min).

Revisión de Astra al primer arreglo (7fbf190): separaba por el NOMBRE del servicio, sin mirar
la política del negocio (en otro salón, «diagnóstico y corte» dejaba de sumarse y se decía
«otro día», que nadie ha dicho), y con un tratamiento pendiente de largo la guía llevaba
«EXACTAMENTE» y la pregunta de duración se daba por contestada.
"""
from __future__ import annotations

import types

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CATALOGO = [
    ("dur_val_diag", "Diagnostico y presupuesto", "Trabajos de color", 15),
    ("dur_val_diag_ext", "Diagnostico y presupuesto para extensiones", "Extensiones", 25),
    ("dur_val_ext_adh", "Extensiones adhesivas 1 paquete o 60 gramos", "Extensiones", 45),
    ("dur_val_corte", "Corte senora", "Cortes", 20),
    ("dur_val_sec_cor", "Secado al aire corto", "Peinados", 10),
    ("dur_val_sec_med", "Secado al aire medio", "Peinados", 10),
    ("dur_val_sec_lar", "Secado al aire largo", "Peinados", 15),
]

LO_QUE_ESCRIBIO = "cuánto duran las extensiones?\nDiagnostico y presupuesto\nquiero saber cuánto duran"


@pytest.fixture()
def salon(api_module, client):  # noqa: F811
    from backend import appstate, db, timeutils

    ahora = timeutils._utc_now().isoformat()
    with db._get_db_connection() as conexion:
        for slug, nombre, categoria, minutos in CATALOGO:
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo',?,?,?,?,0,'',1,0,?,?)",
                (slug, nombre, categoria, minutos, ahora, ahora))
        conexion.commit()
    with appstate.state_lock:
        appstate.intent_cache.clear()
    try:
        yield "demo"
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND slug LIKE 'dur_val_%'")
            conexion.commit()
        with appstate.state_lock:
            appstate.intent_cache.clear()


def _politica(monkeypatch, familias):
    """`booking.valoracion_obligatoria` del negocio: la pone el negocio en su config."""
    from backend import booking

    monkeypatch.setattr(booking, "valoracion_obligatoria", lambda cliente_id: list(familias))


def test_la_valoracion_y_el_tratamiento_no_se_suman(salon, monkeypatch):
    from backend import agent

    _politica(monkeypatch, ["extensiones"])
    guia = agent._cuanto_duran_juntos(salon, LO_QUE_ESCRIBIO, mensaje="quiero saber cuánto duran")
    assert guia, "a la pregunta de cuanto duran no se le dio ninguna guia"
    assert "60 minutos" not in guia and "70 minutos" not in guia, guia
    assert "EN TOTAL" not in guia.upper(), guia
    assert "45" in guia, "falta la duracion del tratamiento: %s" % guia
    assert "aparte" in guia.lower(), "no dice que la valoracion es otra cita: %s" % guia
    assert "otro dia" not in guia.lower(), "nadie ha dicho que sea otro dia: %s" % guia


def test_la_valoracion_es_la_del_tratamiento_que_pregunta(salon, monkeypatch):
    from backend import agent

    _politica(monkeypatch, ["extensiones"])
    guia = agent._cuanto_duran_juntos(salon, LO_QUE_ESCRIBIO, mensaje="quiero saber cuánto duran")
    assert "25" in guia and "para extensiones" in guia.lower(), guia
    assert "15 min" not in guia, "cogio el diagnostico generico: %s" % guia


def test_sin_politica_del_negocio_se_suma_como_siempre(salon, monkeypatch):
    """Revisión de Astra: el nombre «diagnóstico» no basta para separar citas."""
    from backend import agent

    _politica(monkeypatch, [])
    dicho = "diagnostico y presupuesto y corte de señora, cuanto tarda?"
    guia = agent._cuanto_duran_juntos(salon, dicho, mensaje=dicho)
    assert "aparte" not in guia.lower(), guia
    assert "35" in guia, guia


def test_con_un_tratamiento_pendiente_la_pregunta_sigue_viva(salon, monkeypatch):
    """Revisión de Astra: con el largo pendiente la guía decía EXACTAMENTE y la pregunta se perdía."""
    from backend import agent

    _politica(monkeypatch, ["corte"])
    primero = "diagnostico y presupuesto, corte de señora y secado, cuanto tarda?"
    estado = types.SimpleNamespace(duracion_pendiente=0, servicio_exacto="", servicio="")
    guia = agent._duracion_si_la_pregunta(salon, primero, estado, pedido=primero)
    assert guia and "aparte" in guia.lower(), guia
    assert estado.duracion_pendiente > 0, "dio la pregunta por contestada faltando el largo: %s" % guia
    siguiente = agent._duracion_si_la_pregunta(salon, "corto", estado, pedido=primero + "\ncorto")
    assert siguiente, "en el turno siguiente se olvido de que preguntaba cuanto tarda"


def test_lo_que_va_junto_se_sigue_sumando(salon, monkeypatch):
    """Control: corte y secado en el mismo mensaje siguen siendo una sola cita."""
    from backend import agent

    _politica(monkeypatch, ["extensiones"])
    guia = agent._cuanto_duran_juntos(salon, "corte de señora y secado al aire largo, cuanto tarda?",
                                      mensaje="corte de señora y secado al aire largo, cuanto tarda?")
    assert "35" in guia, guia
