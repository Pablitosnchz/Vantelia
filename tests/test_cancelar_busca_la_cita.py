# -*- coding: utf-8 -*-
""""Quiero cancelar mi cita" busca SU CITA, no el catalogo.

POR QUE EXISTE
--------------
28-sep-2026, humo del despliegue (dos de dos, y otra vez con la version que ya estaba en
produccion). Por WhatsApp, con la cita cogida desde ese mismo telefono:

    ella «quiero cancelar mi cita»
         buscar_servicio("quiero cancelar mi cita cancelar cita")      <-- obligado
    IA   «para cancelar tu cita necesito saber la fecha y hora...»
    ella «si, cancelala»
         buscar_servicio("quiero cancelar mi cita si, cancelala")      <-- obligado
    IA   «necesito localizarla en el sistema...»
         la cita sigue viva.

Todo lo que dice mientras no hay servicio elegido se acumula como si describiera un
servicio (sirve para «unas mechas» + «por los hombros»), asi que la regla de «mira el
catalogo antes de preguntar» se llevaba tambien la frase de cancelar y obligaba a
`buscar_servicio`. Con intencion de cancelar o cambiar y la cita sin identificar, lo que
se obliga es `consultar_cita`, que la busca por su telefono.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


def _primer_turno(monkeypatch, mensaje):
    """Lo que el codigo obliga a llamar en el primer turno de la conversacion."""
    from backend import agent, reserva, settings

    estado = reserva.Estado()
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [])

    async def ejecutar(cliente_id, nombre, argumentos, **kwargs):
        return {"ok": False, "error": "sin datos en la prueba"}

    monkeypatch.setattr(agent, "_ejecutar", ejecutar)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    obligadas = []

    def modelo(**kwargs):
        eleccion = kwargs.get("tool_choice")
        if isinstance(eleccion, dict):
            nombre = eleccion["function"]["name"]
            obligadas.append(nombre)
            argumentos = {"descripcion": mensaje} if nombre == "buscar_servicio" else {}
            llamada = types.SimpleNamespace(id="obligada", function=types.SimpleNamespace(
                name=nombre, arguments=json.dumps(argumentos)))
            respuesta = types.SimpleNamespace(content="", tool_calls=[llamada])
        else:
            respuesta = types.SimpleNamespace(content="Ahora lo miro, cariño.", tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=respuesta)])

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)

    asyncio.run(agent.responder("demo", mensaje, session_id="cancelar-busca-la-cita",
                                telefono="34600970041"))
    return obligadas, estado


@pytest.mark.parametrize("mensaje", ["quiero cancelar mi cita", "necesito anular la cita que tengo"])
def test_cancelar_obliga_a_buscar_la_cita_no_el_catalogo(api_module, monkeypatch, mensaje):  # noqa: F811
    obligadas, estado = _primer_turno(monkeypatch, mensaje)
    assert estado.intencion == "cancelar"
    assert obligadas[:1] == ["consultar_cita"], "le pedia fecha y hora sin buscar su cita: %r" % obligadas
    assert "buscar_servicio" not in obligadas


def test_pedir_un_servicio_sigue_mirando_el_catalogo(api_module, monkeypatch):  # noqa: F811
    """Control: para esto nacio la regla del catalogo."""
    obligadas, _ = _primer_turno(monkeypatch, "quiero cita para unas mechas")
    assert "consultar_cita" not in obligadas
