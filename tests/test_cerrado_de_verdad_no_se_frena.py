# -*- coding: utf-8 -*-
"""«Hoy estamos cerrados» en el día que cierra es verdad: el freno no puede corregirlo.

POR QUE EXISTE
--------------
13-sep-2026 (domingo), banco del segundo negocio (metareview, cierra los domingos,
`closed_weekdays: [6]`) medido con modelo real sobre copia de producción. Turno leído en
agent_turns, igual en 2a794c2 y en 413c170:

    ella «cual es vuestro horario?»
         consultar_horario; consultar_disponibilidad(2026-09-14, lunes: abre)
    IA   «Hoy estamos cerrados, pero mañana, lunes 14, abrimos de 09:00 a 18:00»
         freno `dijo_cerrado_estando_abierto`                        <-- en falso

El freno nació para «el jueves estamos cerrados» cuando el jueves SÍ abre y lo que no
hay es hueco. Pero bastaba con haber consultado CUALQUIER día abierto para que saltara
con cualquier «estamos cerrados», hablara del día que hablara. Cada salto en falso es
una vuelta más del modelo y una corrección que le hace dudar de algo cierto.

Ahora se mira de qué día habla la frase: si ese día cierra de verdad, no se frena. Si
no se sabe de qué día habla, se frena como siempre.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import datetime

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

DOMINGO = datetime(2030, 1, 6, 11, 0)          # 6-ene-2030 es domingo
LUNES = "2030-01-07"
AVISO = "Ese dia el negocio SI ABRE"


def _turno(monkeypatch, respuesta_final):
    """Consulta el lunes (abre) y contesta. Devuelve lo que ha visto el modelo."""
    from backend import agent, reserva, settings, voice

    estado = reserva.Estado()
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(reserva, "ahora_local", lambda *a, **k: DOMINGO)
    monkeypatch.setattr(agent, "_historial", lambda *a: [])
    # El negocio cierra los domingos y abre el resto.
    monkeypatch.setattr(voice, "_dia_cerrado",
                        lambda cliente_id, fecha, config=None: datetime.strptime(fecha, "%Y-%m-%d").weekday() == 6)

    async def ejecutar(cliente_id, nombre, argumentos, **kwargs):
        return {"ok": True, "fecha": LUNES, "dia_cerrado": False, "huecos": ["09:00", "09:30"]}

    monkeypatch.setattr(agent, "_ejecutar", ejecutar)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    vistos = []

    def modelo(**kwargs):
        mensajes = kwargs.get("messages") or []
        vistos.extend(str(m.get("content") or "") for m in mensajes if isinstance(m, dict))
        if not any(isinstance(m, dict) and m.get("role") == "tool" for m in mensajes):
            llamada = types.SimpleNamespace(id="mira", function=types.SimpleNamespace(
                name="consultar_disponibilidad", arguments=json.dumps({"fecha": LUNES})))
            respuesta = types.SimpleNamespace(content="", tool_calls=[llamada])
        else:
            respuesta = types.SimpleNamespace(content=respuesta_final, tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=respuesta)])

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)

    asyncio.run(agent.responder("demo", "cual es vuestro horario?", session_id="cerrado-de-verdad",
                                telefono="34600970077"))
    return vistos


def test_hoy_cerrado_en_su_dia_de_cierre_no_se_frena(api_module, monkeypatch):  # noqa: F811
    vistos = _turno(monkeypatch, "Hoy estamos cerrados, pero mañana, lunes 7 de enero, abrimos de 09:00 a 18:00.")

    assert not any(AVISO in t for t in vistos), "freno en falso: hoy domingo SI esta cerrado"


@pytest.mark.parametrize("respuesta", [
    "El lunes estamos cerrados, lo siento.",          # el lunes abre: mentira
    "Mañana estamos cerrados.",                        # mañana es lunes: mentira
    "Ahora mismo estamos cerrados.",                   # no dice qué día: se frena como siempre
])
def test_un_cierre_falso_se_sigue_frenando(api_module, monkeypatch, respuesta):  # noqa: F811
    vistos = _turno(monkeypatch, respuesta)

    assert any(AVISO in t for t in vistos), "decir cerrado un dia que abre ya no se frena: %s" % respuesta


@pytest.mark.parametrize("texto,verdad", [
    ("Hoy estamos cerrados, pero mañana abrimos.", True),
    ("Hoy estamos cerrados. El lunes estamos cerrados.", False),     # una de las dos es falsa
    ("Por la mañana estamos cerrados.", False),                      # «por la mañana» no es un día
    ("El domingo estamos cerrados.", True),
    ("Estamos cerrados.", False),
])
def test_de_que_dia_habla(api_module, monkeypatch, texto, verdad):  # noqa: F811
    from backend import agent, voice

    monkeypatch.setattr(voice, "_dia_cerrado",
                        lambda cliente_id, fecha, config=None: datetime.strptime(fecha, "%Y-%m-%d").weekday() == 6)
    assert agent._el_cierre_que_dice_es_verdad("demo", texto, DOMINGO) is verdad
