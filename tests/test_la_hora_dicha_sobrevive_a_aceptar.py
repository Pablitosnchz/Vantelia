# -*- coding: utf-8 -*-
"""Aceptar la cita de diagnóstico no borra la hora que ella ya dijo.

POR QUE EXISTE
--------------
13-sep-2026, caso crítico `dice-que-si-y-acaba-en-cita` con modelo real contra
copia de producción (3a899f8, primer intento y reintento iguales):

    ella «el 2026-09-15»   IA  oferta con botones: «¿Quieres una cita de Diagnóstico?»
    ella «a las 15»        IA  «¿Te gustaría que te agende la cita de diagnóstico
                                y presupuesto ... a las 15:00?»   (agenda_agente)
    ella «si»              IA  «...solo necesito que me confirmes si aceptas...»
    ella «me llamo Ana»    IA  «Ana, solo necesito que me confirmes si aceptas...»

Dos muros:
  1. El agente repetía la oferta con sus palabras y se registraba como
     `agenda_agente`: el «si» ya no contaba como respuesta a la oferta.
  2. Aceptar suelta la hora (pudo apartarse para otro tratamiento). Aunque el
     «si» se aceptara, se le volvían a listar las horas del día y la cita no
     llegaba al resumen.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

from test_alternativa_de_precio import ofrecer, politica  # noqa: F401
from test_booking_exhaustive import api_module  # noqa: F401


def _libres(monkeypatch, libres):
    from backend import agenda

    consultas = []

    async def huecos(cliente_id, fecha, servicio="", location_id=""):
        consultas.append((cliente_id, fecha, servicio))
        return set(libres), set(libres)

    monkeypatch.setattr(agenda, "_public_slot_sets_for_day", huecos)
    return consultas


def _ofrecida_con_dia():
    estado, propuesta = ofrecer()          # hora 15:00 dicha, huecos del servicio anterior
    estado.fecha = "2030-01-08"
    return estado, propuesta


# ─── El núcleo compartido ────────────────────────────────────────────────

def test_la_hora_que_dijo_se_conserva_si_le_cabe(politica, monkeypatch):  # noqa: F811
    from backend import booking

    consultas = _libres(monkeypatch, {"15:00"})
    estado, propuesta = _ofrecida_con_dia()
    hora, del_codigo = estado.hora, estado.hora_del_codigo
    assert booking.contestar_alternativa_de_precio("salon", estado, propuesta.id, "acepta")
    assert estado.hora == "", "aceptar sigue soltando la hora del servicio anterior"

    assert asyncio.run(booking.conservar_la_hora_dicha(
        "salon", estado, hora, del_codigo=del_codigo)) is True

    assert estado.hora == "15:00"
    assert consultas == [("salon", "2030-01-08", "Diagnóstico")], (
        "la hora se mira contra el servicio ACEPTADO, no contra el anterior")


@pytest.mark.parametrize("libres,del_codigo,respuesta", [
    (set(), False, "acepta"),        # a esa hora no hay hueco para el diagnóstico
    ({"15:00"}, True, "acepta"),     # la eligió el código para OTRO servicio
    ({"15:00"}, False, "rechaza"),   # no ha aceptado nada
])
def test_la_hora_no_se_conserva_si_no_toca(politica, monkeypatch, libres, del_codigo,  # noqa: F811
                                           respuesta):
    from backend import booking

    _libres(monkeypatch, libres)
    estado, propuesta = _ofrecida_con_dia()
    hora = estado.hora
    booking.contestar_alternativa_de_precio("salon", estado, propuesta.id, respuesta)
    estado.hora = ""   # rechazar no la suelta: se aísla la condición que se prueba

    assert asyncio.run(booking.conservar_la_hora_dicha(
        "salon", estado, hora, del_codigo=del_codigo)) is False
    assert estado.hora == ""


# ─── WhatsApp: botón y «sí» escrito ──────────────────────────────────────

def _canal(monkeypatch, estado, *, contacto=None):
    from backend import appstate, clients, crm, messaging, reserva, whatsapp

    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(crm, "contact_by_phone", lambda *a: contacto)
    monkeypatch.setattr(clients, "exige_dos_apellidos", lambda cliente_id: True)
    anotado = {"textos": [], "huecos": [], "resumen": []}

    async def texto(**kwargs):
        anotado["textos"].append(kwargs["text"])
        return True

    async def huecos(**kwargs):
        anotado["huecos"].append(kwargs)
        return True

    async def resumen(**kwargs):
        anotado["resumen"].append(kwargs)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **k: "sesion")
    monkeypatch.setattr(whatsapp, "_wa_ofrecer_huecos_hablando", huecos)
    monkeypatch.setattr(whatsapp, "_wa_resumen_para_confirmar", resumen)
    return appstate.WAFlowState(cliente_id="salon", from_number="persona"), anotado


def _aceptar(flow, propuesta):
    from backend import whatsapp

    return asyncio.run(whatsapp._wa_contestar_propuesta(
        cliente_id="salon", phone_number_id="canal", from_number="persona",
        propuesta_id=propuesta.id, respuesta="acepta", flow=flow,
        incoming_text="", request=None))


def test_aceptada_con_su_hora_se_le_pide_el_nombre_y_no_las_horas(politica, monkeypatch):  # noqa: F811
    _libres(monkeypatch, {"15:00"})
    estado, propuesta = _ofrecida_con_dia()
    flow, anotado = _canal(monkeypatch, estado)

    assert _aceptar(flow, propuesta) is True

    assert anotado["huecos"] == [], "ya dijo a que hora: volver a listarlas es el bucle"
    assert "15:00" in anotado["textos"][0]
    assert "apellidos" in anotado["textos"][0], "sin nombre no hay resumen: se le pide"
    assert anotado["resumen"] == []
    assert flow.hora == "15:00" and estado.hora == "15:00"


def test_aceptada_con_su_hora_y_conocida_va_al_resumen(politica, monkeypatch):  # noqa: F811
    _libres(monkeypatch, {"15:00"})
    estado, propuesta = _ofrecida_con_dia()
    flow, anotado = _canal(monkeypatch, estado, contacto={"name": "Ana Ruiz Perez", "email": ""})

    _aceptar(flow, propuesta)

    assert anotado["huecos"] == []
    assert "apellidos" not in anotado["textos"][0]
    assert len(anotado["resumen"]) == 1, "con todos los datos lo que toca es el resumen"


def test_aceptada_sin_hueco_a_su_hora_se_le_ofrecen_las_del_dia(politica, monkeypatch):  # noqa: F811
    _libres(monkeypatch, set())
    estado, propuesta = _ofrecida_con_dia()
    flow, anotado = _canal(monkeypatch, estado)

    _aceptar(flow, propuesta)

    assert len(anotado["huecos"]) == 1
    assert estado.hora == "" and flow.hora == ""


# ─── La oferta repetida por el agente sigue siendo la oferta ─────────────

@pytest.mark.parametrize("texto,esperado", [
    ("¿Te gustaría que te agende la cita de diagnóstico el 15 a las 15:00? 😊", True),
    ("¿A qué hora te viene bien?", False),                     # otra pregunta
    ("La cita de Diagnóstico dura unos 20 minutos.", False),   # no pregunta nada
])
def test_reconoce_la_oferta_repetida(politica, texto, esperado):  # noqa: F811
    from backend import whatsapp

    estado, _propuesta = ofrecer()
    assert whatsapp._wa_vuelve_a_ofrecer(estado, texto) is esperado


def test_una_oferta_ya_contestada_no_se_repite(politica):  # noqa: F811
    from backend import booking, whatsapp

    estado, propuesta = ofrecer()
    booking.contestar_alternativa_de_precio("salon", estado, propuesta.id, "acepta")
    assert whatsapp._wa_vuelve_a_ofrecer(estado, "¿Te agendo la cita de diagnóstico?") is False


def test_el_turno_registra_la_oferta_repetida_como_oferta(politica, monkeypatch):  # noqa: F811
    """El recorrido medido: sin esto, el «si» siguiente no encuentra la oferta."""
    from backend import agent, appstate, messaging, reserva, whatsapp

    estado, _propuesta = _ofrecida_con_dia()
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(agent, "disponible", lambda cliente_id: True)
    monkeypatch.setattr(whatsapp, "_wa_cita_recien_hecha", lambda *a, **k: "")
    monkeypatch.setattr(whatsapp, "_wa_lo_ultimo_fue_la_oferta", lambda *a: False)
    registrados = []

    def registrar(**kwargs):
        registrados.append(kwargs)
        return "sesion"

    async def responder(*args, **kwargs):
        return "¿Te gustaría que te agende la cita de Diagnóstico el 8 a las 15:00? 😊", False

    async def nada(**kwargs):
        return False

    async def enviar(**kwargs):
        return True

    monkeypatch.setattr(whatsapp, "_wa_registrar", registrar)
    monkeypatch.setattr(agent, "responder", responder)
    monkeypatch.setattr(whatsapp, "_wa_resumen_para_confirmar", nada)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviar)
    flow = appstate.WAFlowState(cliente_id="salon", from_number="persona")

    asyncio.run(whatsapp._wa_turno_del_agente(
        cliente_id="salon", phone_number_id="canal", from_number="persona",
        incoming_text="a las 15", flow=flow, config={}, request=None))

    respuestas = [r for r in registrados if r.get("respuesta")]
    assert [r["intent"] for r in respuestas] == ["oferta_propuesta"], respuestas


# ─── El otro camino de aceptar: la herramienta del modelo ────────────────

def test_responder_propuesta_del_modelo_conserva_la_hora(api_module, monkeypatch):  # noqa: F811
    from backend import agent, booking, reserva, settings

    estado = reserva.Estado(intencion="reservar", fecha="2030-01-08", hora="15:00",
                            servicio_texto="quiero un alisado no lo tengo claro")
    propuesta = reserva.preparar_propuesta_servicio(
        estado, servicio_id="diag", nombre="Diagnostico y presupuesto",
        origen="orientacion:regla", revision_config="r1", servicio_origen="alisado")
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "oferta:" + propuesta.id)
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(reserva, "persistir_respuesta_de_propuesta", lambda *a: True)
    monkeypatch.setattr(agent, "_historial", lambda *a: [])
    monkeypatch.setattr(booking, "revalidar_alternativa_de_propuesta", lambda cid, e: {
        "nombre": "Diagnostico y presupuesto", "duracion": 20, "revision": "r1"})
    _libres(monkeypatch, {"15:00"})
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    llamadas = []

    def modelo(**kwargs):
        llamadas.append(kwargs)
        if len(llamadas) == 1:
            llamada = types.SimpleNamespace(id="acepta", function=types.SimpleNamespace(
                name="responder_propuesta",
                arguments=json.dumps({"propuesta_id": propuesta.id, "respuesta": "acepta"})))
            mensaje = types.SimpleNamespace(content="", tool_calls=[llamada])
        else:
            mensaje = types.SimpleNamespace(content="Perfecto, ¿me dices tu nombre?", tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=mensaje)])

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)

    asyncio.run(agent.responder("demo", "si", session_id="hora-dicha",
                                telefono="34600777222", intencion="reservar"))

    assert estado.propuesta_servicio.estado == "aceptada", "el modelo no llegó a aceptar"
    assert estado.hora == "15:00", "aceptada por el modelo, la hora que dijo se ha perdido"
