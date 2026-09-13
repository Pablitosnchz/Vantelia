# -*- coding: utf-8 -*-
"""Nadie pierde una cita que no ha pedido anular.

POR QUE EXISTE
--------------
13-sep-2026, banco completo con modelo real sobre 5e9f8d7 (copia de producción),
caso `cambiar-la-hora-de-verdad`, primer intento:

    ella «necesito cambiar mi cita de dia»
    ella «cualquier otro hueco que tengas me vale»   -> reprogramar_cita OK (22-sep 17:45)
    IA   «Listo, he reprogramado tu cita para el martes 22 a las 17:45»
    ella «vale, la primera opcion que me has dicho»  -> cancelar_cita OK
                                                     -> crear_cita frenada (la confirma ella)
    IA   «Las 17:45 no las tengo, cariño...»

Resultado en la agenda: la cita CANCELADA y ninguna otra. El modelo intentó
«cancelar y crear otra» para moverla; la cancelación se ejecutó y la creación no.
Crear una cita que nadie ha pedido tenía freno (`cita_sin_pedirla`); cancelar una
que nadie ha pedido anular, no. El reintento pasó: que salga una de cada dos no lo
hace aceptable, porque cuando sale el salón pierde la cita y ella cree que la tiene.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("dicho,esperado", [
    ("quiero anular mi cita", True),
    ("cancelala y ponme otra el jueves", True),
    ("no voy a poder ir", True),
    ("necesito cambiar mi cita de dia", False),
    ("vale, la primera opcion que me has dicho", False),
])
def test_pide_anular(api_module, dicho, esperado):  # noqa: F811
    from backend import reserva

    assert reserva.pide_anular(dicho) is esperado


def _turno(monkeypatch, *, historial, mensaje, intencion="reprogramar"):
    """El turno medido: el modelo llama a cancelar_cita y luego contesta."""
    from backend import agent, reserva, settings

    estado = reserva.Estado(intencion=intencion, codigo="R-892641",
                            fecha="2030-01-22", hora="17:45", hecho=True)
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: list(historial))
    ejecutadas = []

    async def ejecutar(cliente_id, nombre, argumentos, **kwargs):
        ejecutadas.append(nombre)
        return {"ok": True, "codigo_reserva": "R-892641"}

    monkeypatch.setattr(agent, "_ejecutar", ejecutar)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    llamadas = []

    def modelo(**kwargs):
        llamadas.append(kwargs)
        if len(llamadas) == 1:
            llamada = types.SimpleNamespace(id="cancela", function=types.SimpleNamespace(
                name="cancelar_cita",
                arguments=json.dumps({"codigo_reserva": "R-892641", "motivo": "Cambio de cita"})))
            respuesta = types.SimpleNamespace(content="", tool_calls=[llamada])
        else:
            respuesta = types.SimpleNamespace(content="De acuerdo, cariño.", tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=respuesta)])

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)

    asyncio.run(agent.responder("demo", mensaje, session_id="cancelar-sin-pedir",
                                telefono="34600990026", intencion=intencion))
    return ejecutadas


def test_tras_moverla_un_vale_no_la_cancela(api_module, monkeypatch):  # noqa: F811
    ejecutadas = _turno(monkeypatch, historial=[
        {"role": "user", "content": "buenas, necesito cambiar mi cita de dia"},
        {"role": "user", "content": "cualquier otro hueco que tengas me vale"},
        {"role": "assistant", "content": "Listo, he reprogramado tu cita para el martes 22 a las 17:45."},
    ], mensaje="vale, la primera opcion que me has dicho")

    assert "cancelar_cita" not in ejecutadas, (
        "se ha cancelado una cita que nadie ha pedido anular: se queda sin cita")


def test_si_pide_anularla_se_cancela(api_module, monkeypatch):  # noqa: F811
    """El control: el freno no puede quitarle a nadie cancelar su cita."""
    ejecutadas = _turno(monkeypatch, historial=[
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "¡Hola! ¿En qué te ayudo?"},
    ], mensaje="quiero anular mi cita, no voy a poder ir", intencion="")

    assert ejecutadas == ["cancelar_cita"]


def test_si_el_canal_declara_cancelar_se_cancela(api_module, monkeypatch):  # noqa: F811
    """Pulsar «Cancelar mi cita» en WhatsApp declara la intención sin escribirla."""
    ejecutadas = _turno(monkeypatch, historial=[], mensaje="R-892641", intencion="cancelar")

    assert ejecutadas == ["cancelar_cita"]
