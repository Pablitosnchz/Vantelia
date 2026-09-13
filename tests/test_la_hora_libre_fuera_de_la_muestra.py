# -*- coding: utf-8 -*-
"""Una hora libre que no sale en la MUESTRA de huecos no es una hora inventada.

POR QUE EXISTE
--------------
13-sep-2026, escenario «reinicio a mitad de reserva» medido con modelo real sobre
copia de producción (2a794c2). Turnos leídos en agent_turns:

    ella «quiero cita para un corte de señora»
         consultar_disponibilidad(15-sep) -> muestra: 10:00..11:00, 14:00..15:00, 18:00..
    IA   «... te puedo ofrecer las 10:00, 11:00 o 14:00»
    ella «el 15/09/2026 a las 17:00»
         freno `ofrecio_una_hora_que_no_tiene`: «Las 17:00 NO estan entre los huecos
         que tienes: 10:00, 10:15, 10:30, 10:45, 11:00, 14:00, 14:15, 14:30»
    IA   «Lo siento, cariño, pero a las 17:00 no tengo disponibilidad»      <-- falso
    ...
         la cita se crea a las 17:00 sin conflicto: estaba libre.

`consultar_disponibilidad` da una MUESTRA por franja (5 de mañana, 5 de tarde, 4 de
noche) y el estado guarda las 8 primeras. El freno trataba esa lista como si fuera
todo lo libre del día y obligaba al modelo a negar una hora que sí había. Es el
«fantasma» que más desanima: le dicen que no a la hora que pide.

El freno sigue haciendo lo suyo -para eso nació, `test_el_si_coge_la_hora_ofrecida`-:
si la hora de verdad no está libre, frena.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

from test_booking_exhaustive import api_module  # noqa: F401

FECHA = "2030-01-08"
# Un día del salón: mañana de 10:00 a 13:45 y tarde de 14:00 a 20:00, cada cuarto.
DIA = (["%02d:%02d" % (h, m) for h in range(10, 14) for m in (0, 15, 30, 45)]
       + ["%02d:%02d" % (h, m) for h in range(14, 20) for m in (0, 15, 30, 45)] + ["20:00"])
NIEGA = "NO estan entre los huecos"


def _estado_medido():
    """El estado tras el primer turno medido: servicio, día y la muestra de huecos.

    El día ya estaba puesto antes del segundo turno: el freno medido listó los 8
    huecos, y si «el 15/09/2026» hubiera cambiado la fecha se habrían vaciado.
    """
    from backend import reserva, voice

    estado = reserva.Estado()
    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = estado.servicio_exacto = "Corte señora"
    estado.fecha = FECHA
    resultado = dict(ok=True, fecha=FECHA, **voice._huecos_por_franja(DIA))
    reserva.anotar_resultado(estado, "consultar_disponibilidad",
                             {"fecha": FECHA, "servicio": "Corte señora"}, resultado)
    assert "17:00" not in estado.huecos, "el caso medido: las 17:00 no salen en la muestra"
    return estado, resultado


def _turno(monkeypatch, *, libres):
    """El segundo turno medido. Devuelve lo que ha visto el modelo y sus pasos."""
    from backend import agenda, agent, reserva, settings

    estado, resultado = _estado_medido()
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [
        {"role": "user", "content": "quiero cita para un corte de señora"},
        {"role": "assistant", "content": ("Perfecto, cariño. Para el martes 8 de enero te puedo "
                                          "ofrecer las 10:00, 11:00 o 14:00. ¿Cuál te gusta más?")},
    ])

    async def ejecutar(cliente_id, nombre, argumentos, **kwargs):
        return dict(resultado)

    async def huecos_del_dia(cliente_id, fecha, servicio="", location_id=""):
        return set(DIA), set(libres)

    monkeypatch.setattr(agent, "_ejecutar", ejecutar)
    monkeypatch.setattr(agenda, "_public_slot_sets_for_day", huecos_del_dia)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    vistos, pasos = [], []

    def modelo(**kwargs):
        vistos.extend(kwargs.get("messages") or [])
        mensajes = kwargs.get("messages") or []
        # Como en el turno medido: contesta ofreciendo las 17:00 sin mirar, y solo
        # consulta la agenda cuando el codigo se lo exige.
        forzada = kwargs.get("tool_choice") not in (None, "auto")
        if forzada and not any(m.get("role") == "tool" for m in mensajes if isinstance(m, dict)):
            llamada = types.SimpleNamespace(id="mira", function=types.SimpleNamespace(
                name="consultar_disponibilidad",
                arguments=json.dumps({"fecha": FECHA, "servicio": "Corte señora"})))
            respuesta = types.SimpleNamespace(content="", tool_calls=[llamada])
        else:
            respuesta = types.SimpleNamespace(
                content="Perfecto, cariño. Te reservo el martes 8 a las 17:00, ¿te parece bien?",
                tool_calls=None)
        pasos.append((kwargs.get("tool_choice"), "tool" if respuesta.tool_calls else "texto",
                      [str(m.get("content") or "")[:90] for m in mensajes
                       if isinstance(m, dict) and m.get("role") == "system"][1:]))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=respuesta)])

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)

    asyncio.run(agent.responder("demo", "el 08/01/2030 a las 17:00", session_id="hora-fuera-de-muestra",
                                telefono="34600970040", intencion="reservar"))
    return [str(m.get("content") or "") for m in vistos if isinstance(m, dict)], pasos


def test_una_hora_libre_fuera_de_la_muestra_no_se_niega(api_module, monkeypatch):  # noqa: F811
    vistos, pasos = _turno(monkeypatch, libres=DIA)

    assert not any(NIEGA in texto for texto in vistos), (
        "el freno obliga a negar las 17:00, que estan libres: le dirian que no a su hora. %r" % pasos)


def test_una_hora_que_no_esta_libre_se_sigue_frenando(api_module, monkeypatch):  # noqa: F811
    """Control: para esto nació el freno."""
    vistos, pasos = _turno(monkeypatch, libres=[h for h in DIA if h != "17:00"])

    assert any(NIEGA in texto for texto in vistos), "ofrecer una hora ocupada ya no se frena. %r" % pasos
