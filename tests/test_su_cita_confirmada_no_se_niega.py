# -*- coding: utf-8 -*-
"""Decirle que su cita está confirmada, cuando la tiene, no es inventarse una cita.

POR QUE EXISTE
--------------
13-sep-2026, `cambiar-la-hora-de-verdad` medido con modelo real sobre copia de producción
(6bed2f1 y 112b26c, leído en agent_turns): movida la cita en un turno anterior, al
cerrar la conversación el modelo decía «tu cita está confirmada para el martes 22 a las
17:45» -verdad- y saltaba `dijo_que_hay_cita_sin_haberla`, que le obligaba a decir que
NO había ninguna cita.

El freno solo miraba si en ESTE turno se había creado, movido o consultado algo. Nació
para lo contrario (2-sep): cancelada su cita, remató con «tu cita está confirmada para
mañana a las 10:00» sin haber ninguna. Ahora se mira la agenda: si ella tiene una cita
viva y la hora que se le dice es la suya, no se frena. Sin cita viva, o con otra hora,
se frena como siempre.
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

AVISO = "NO hay ninguna cita"
SU_CITA = {"booking_code": "R-892641", "servicio": "Corte señora", "booking_date": "2030-01-22",
           "booking_time": "17:45", "telefono": "34600990026"}


def _turno(monkeypatch, *, respuesta, citas):
    from backend import agent, booking, reserva, settings

    estado = reserva.Estado(intencion="reprogramar", codigo="R-892641",
                            fecha="2030-01-22", hora="17:45", hecho=True)
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [
        {"role": "user", "content": "necesito cambiar mi cita de dia"},
        {"role": "assistant", "content": "Listo, he reprogramado tu cita para el martes 22 a las 17:45."},
    ])
    monkeypatch.setattr(booking, "citas_vivas_del_telefono", lambda c, t: list(citas))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    vistos = []

    def modelo(**kwargs):
        vistos.extend(str(m.get("content") or "") for m in (kwargs.get("messages") or [])
                      if isinstance(m, dict))
        mensaje = types.SimpleNamespace(content=respuesta, tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=mensaje)])

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)

    asyncio.run(agent.responder("demo", "vale, muchas gracias", session_id="su-cita-confirmada",
                                telefono="34600990026", intencion="reprogramar"))
    return vistos


def test_su_cita_viva_se_puede_confirmar(api_module, monkeypatch):  # noqa: F811
    vistos = _turno(monkeypatch, respuesta="Tu cita está confirmada para el martes 22 a las 17:45. ¡Hasta pronto!",
                    citas=[SU_CITA])

    assert not any(AVISO in t for t in vistos), "freno en falso: su cita existe y es a las 17:45"


@pytest.mark.parametrize("respuesta,citas", [
    # Sin cita viva: el caso para el que nacio el freno.
    ("Tu cita está confirmada para mañana a las 10:00.", []),
    # Con su cita a las 17:45, decirle las 10:00 no es su cita.
    ("Tu cita está confirmada para mañana a las 10:00.", [SU_CITA]),
])
def test_una_cita_que_no_es_la_suya_se_sigue_frenando(api_module, monkeypatch, respuesta, citas):  # noqa: F811
    vistos = _turno(monkeypatch, respuesta=respuesta, citas=citas)

    assert any(AVISO in t for t in vistos), "se da por confirmada una cita que no tiene: %r" % citas
