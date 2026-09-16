# -*- coding: utf-8 -*-
"""El freno del precio no vuelve a ofrecer la valoración que ella acaba de rechazar.

POR QUE EXISTE
--------------
Cierre de Alicia, 16-sep-2026. El caso crítico `no-quiero-diagnostico-quiero-cita` falló
con modelo real en e81f010 (dos intentos del banco y 2 de 6 repeticiones). Leído en
agent_turns: tras «no quiero cita para diagnostico, quiero cita para hacermelas» el modelo
consultaba la agenda y su borrador llevaba una cifra en euros (la fianza de las mechas).
Con los precios ocultos, el freno `precio_que_no_se_da` le mandaba reescribir «ofreciéndole
esa cita» de valoración: era el propio código el que le hacía insistir en el diagnóstico
que ella había rechazado. «Se le ofrece, y si dice que no, se le coge lo que pide»
(`booking.renuncio_al_diagnostico`). Revisión de Astra: el fallo impide aceptar el candidato.
"""
from __future__ import annotations

import asyncio
import sys
import types

from test_booking_exhaustive import api_module  # noqa: F401

OFRECE_LA_VALORACION = "ofreciendole esa cita"


def _turno(monkeypatch, mensaje, historial):
    """Un turno cuyo primer borrador lleva una cifra en euros. Devuelve lo que ve el modelo."""
    from backend import agent, booking, reserva, settings

    estado = reserva.Estado()
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: list(historial))
    monkeypatch.setattr(booking, "precios_ocultos", lambda *a, **k: True)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    vistos = []

    def modelo(**kwargs):
        mensajes = kwargs.get("messages") or []
        vistos.extend(str(m.get("content") or "") for m in mensajes if isinstance(m, dict))
        corregido = any(isinstance(m, dict) and m.get("role") == "system"
                        and "Reescribe tu respuesta sin" in str(m.get("content") or "") for m in mensajes)
        texto = ("Perfecto, te apunto las mechas largas. ¿Qué día te viene bien?" if corregido else
                 "Perfecto, las mechas largas llevan una fianza de 50 €. ¿Qué día te viene bien?")
        respuesta = types.SimpleNamespace(content=texto, tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=respuesta)])

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)
    asyncio.run(agent.responder("demo", mensaje, session_id="precio-tras-rechazo", telefono="34600970078"))
    return vistos


def _aviso(vistos):
    avisos = [v for v in vistos if "Reescribe tu respuesta sin" in v]
    assert avisos, "el freno del precio no ha saltado: la prueba no mide nada"
    return avisos[-1]


def test_tras_rechazar_el_diagnostico_el_freno_no_lo_vuelve_a_ofrecer(api_module, monkeypatch):  # noqa: F811
    historial = [{"role": "user", "content": "quiero unas mechas y tengo el pelo largo"},
                 {"role": "assistant", "content": "Te cogemos una cita de 15 minutos de diagnóstico."}]
    aviso = _aviso(_turno(monkeypatch, "no quiero cita para diagnostico, quiero cita para hacermelas", historial))
    assert OFRECE_LA_VALORACION not in aviso, aviso
    assert "no se la vuelvas a ofrecer" in aviso, aviso


def test_sin_rechazo_el_freno_sigue_ofreciendo_la_valoracion(api_module, monkeypatch):  # noqa: F811
    aviso = _aviso(_turno(monkeypatch, "cuanto me costarian unas mechas largas?", []))
    assert OFRECE_LA_VALORACION in aviso, aviso
