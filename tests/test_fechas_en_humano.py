# -*- coding: utf-8 -*-
"""La clienta lee «martes 15 de septiembre», no «2026-09-15».

POR QUE EXISTE
--------------
13-sep-2026, caso crítico `dice-que-si-y-acaba-en-cita` medido con modelo real sobre
copia de producción (0bca1eb): en 3 de 6 tiradas una respuesta decía

    «¿Te gustaría que te agende la cita de diagnóstico y presupuesto para el
     2026-09-15 a las 15:00? 😊»

El modelo copia la fecha de las herramientas tal cual. Pedírselo en el prompt no basta:
se convierte en el código, en la salida del agente (la misma para WhatsApp, widget y voz).
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("texto,queda", [
    ("¿Te agendo la cita para el 2026-09-15 a las 15:00?",
     "¿Te agendo la cita para el martes 15 de septiembre a las 15:00?"),
    ("Tengo el 2026-09-15 y el 2026-09-16.", "Tengo el martes 15 de septiembre y el miércoles 16 de septiembre."),
    ("Tu cita es el martes 15 de septiembre.", "Tu cita es el martes 15 de septiembre."),   # ya en humano
    ("Gestiona tu cita: https://app.vantelia.es/b/2026-09-15/abc", "Gestiona tu cita: https://app.vantelia.es/b/2026-09-15/abc"),
    ("https://app.vantelia.es/disponibilidad?fecha=2026-09-15", "https://app.vantelia.es/disponibilidad?fecha=2026-09-15"),
    ("Referencia R-2026-09-15X", "Referencia R-2026-09-15X"),
    ("el 2026-02-30 no existe", "el 2026-02-30 no existe"),          # fecha imposible: se deja
])
def test_convierte_solo_fechas_sueltas(api_module, texto, queda):  # noqa: F811
    from backend import agent

    assert agent._fechas_en_humano(texto) == queda


def test_la_respuesta_del_agente_sale_en_humano(api_module, monkeypatch):  # noqa: F811
    """El recorrido de `responder`: lo que devuelve ya no lleva la fecha ISO."""
    from backend import agent, reserva, settings

    estado = reserva.Estado(intencion="reservar", servicio="Diagnóstico y presupuesto")
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [
        {"role": "user", "content": "quiero un diagnostico"},
        {"role": "assistant", "content": "¿Qué día te viene bien?"},
    ])
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")

    def modelo(**kwargs):
        respuesta = types.SimpleNamespace(
            content="Perfecto, cariño. ¿Te agendo el diagnóstico para el 2030-01-08 por la mañana?",
            tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=respuesta)])

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)

    texto, _creada = asyncio.run(agent.responder(
        "demo", "me da igual la hora", session_id="fechas-en-humano", telefono="34600970099"))

    assert "2030-01-08" not in texto, texto
    assert "martes 8 de enero" in texto, texto
