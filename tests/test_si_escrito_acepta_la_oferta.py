# -*- coding: utf-8 -*-
"""Un «sí» escrito a la oferta que se acaba de hacer la acepta, igual que el botón.

POR QUE EXISTE
--------------
13-sep-2026, conversación repetida turno a turno con modelo real contra copia de
producción. Con la regla de orientación de Alicia (a quien no sabe qué alisado
quiere se le ofrece la cita de diagnóstico) la oferta ya salía bien, con los
botones «Sí, esa cita» / «No, gracias» y la propuesta en estado «ofrecida». Pero
la clienta escribió «si» en vez de pulsar, y:

    propuesta = ofrecida   (nadie la aceptó)
    IA  «Tengo varias opciones para el 15...»
    IA  «...solo me falta saber qué tipo de alisado prefieres: ¿Keratina...?»

El modelo tenía la herramienta `responder_propuesta` y no la usaba. Lo que el
modelo puede hacer mal lo impide el código: un sí sin pega a la oferta que se le
acaba de hacer se acepta por el MISMO camino que el botón.

Lo que NO puede aceptar, y también se vigila:
  · «sí, pero mejor otro día»: es una petición, no un sí (`_wa_dice_que_si`).
  · un sí que respondía a OTRA pregunta posterior: solo cuenta si lo último que
    se le envió fue la oferta.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from test_alternativa_de_precio import ofrecer, politica  # noqa: F401
from test_booking_exhaustive import api_module  # noqa: F401


def _canal(monkeypatch, estado, *, ultimo_fue_la_oferta):
    from backend import agenda, agent, appstate, messaging, reserva, whatsapp

    async def sin_huecos(*a, **k):
        return set(), set()

    # Sin hueco libre a su hora: aceptar sigue ofreciendo las horas del dia. El caso
    # con la hora libre lo vigila `test_la_hora_dicha_sobrevive_a_aceptar.py`.
    monkeypatch.setattr(agenda, "_public_slot_sets_for_day", sin_huecos)
    monkeypatch.setattr(agent, "disponible", lambda cliente_id: True)
    monkeypatch.setattr(whatsapp, "_wa_cita_recien_hecha", lambda *a, **k: "")
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **k: "sesion-de-la-oferta")
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(whatsapp, "_wa_lo_ultimo_fue_la_oferta",
                        lambda cliente_id, session_id: ultimo_fue_la_oferta)
    anotado = {"agente": [], "textos": [], "huecos": []}

    async def responder(*args, **kwargs):
        anotado["agente"].append(args[1] if len(args) > 1 else kwargs.get("mensaje"))
        return "respuesta del agente", False

    async def texto(**kwargs):
        anotado["textos"].append(kwargs["text"])
        return True

    async def huecos(**kwargs):
        anotado["huecos"].append(kwargs["servicio"])
        return True

    async def sin_resumen(**kwargs):
        return False

    monkeypatch.setattr(agent, "responder", responder)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(whatsapp, "_wa_ofrecer_huecos_hablando", huecos)
    monkeypatch.setattr(whatsapp, "_wa_resumen_para_confirmar", sin_resumen)
    flow = appstate.WAFlowState(cliente_id="salon", from_number="persona")
    return flow, anotado


def _turno(flow, dicho):
    from backend import whatsapp

    return asyncio.run(whatsapp._wa_turno_del_agente(
        cliente_id="salon", phone_number_id="canal", from_number="persona",
        incoming_text=dicho, flow=flow, config={}, request=None))


@pytest.mark.parametrize("dicho", ["si", "sí", "Sí, perfecto"])
def test_un_si_escrito_a_la_oferta_la_acepta(politica, monkeypatch, dicho):  # noqa: F811
    estado, propuesta = ofrecer()
    estado.fecha = "2030-01-08"
    flow, anotado = _canal(monkeypatch, estado, ultimo_fue_la_oferta=True)

    assert _turno(flow, dicho) is True

    assert estado.propuesta_servicio.estado == "aceptada", (
        "un sí escrito a la oferta no la acepta: se le seguirá preguntando la técnica")
    assert estado.servicio_exacto == "Diagnóstico"
    assert anotado["agente"] == [], "se lo pasó al modelo en vez de aceptarlo el código"
    assert anotado["huecos"] == ["Diagnóstico"], "aceptada, tiene que seguir con las horas"


@pytest.mark.parametrize("dicho,ultimo_fue_la_oferta", [
    ("si, pero mejor otro dia", True),   # una peticion, no un si
    ("no, gracias", True),               # la negativa la interpreta el agente
    ("si", False),                       # respondia a OTRA pregunta posterior
])
def test_lo_que_no_es_aceptar_la_oferta_lo_lleva_el_agente(politica, monkeypatch, dicho,  # noqa: F811
                                                            ultimo_fue_la_oferta):
    estado, propuesta = ofrecer()
    flow, anotado = _canal(monkeypatch, estado, ultimo_fue_la_oferta=ultimo_fue_la_oferta)

    _turno(flow, dicho)

    assert estado.propuesta_servicio.estado == "ofrecida", (
        "se acepto una oferta con %r (ultimo_fue_la_oferta=%s)" % (dicho, ultimo_fue_la_oferta))
    assert anotado["agente"] == [dicho]


def test_lo_ultimo_fue_la_oferta_mira_el_ultimo_mensaje_del_asistente(api_module):  # noqa: F811
    """Contra la base de verdad: lo que cuenta es el ÚLTIMO mensaje del asistente."""
    from backend import db, whatsapp

    sesion = "sesion-%s" % uuid.uuid4().hex[:8]
    otra = "sesion-%s" % uuid.uuid4().hex[:8]

    def apuntar(sesion_id, rol, intent):
        with db._get_db_connection() as cx:
            cx.execute(
                "INSERT INTO chat_messages (session_id, cliente_id, role, content, intent, created_at)"
                " VALUES (?, 'demo', ?, 'x', ?, '2030-01-01T00:00:00Z')", (sesion_id, rol, intent))
            cx.commit()

    try:
        apuntar(sesion, "assistant", "oferta_propuesta")
        apuntar(sesion, "user", "")          # su «sí» ya se ha registrado
        assert whatsapp._wa_lo_ultimo_fue_la_oferta("demo", sesion) is True

        apuntar(sesion, "assistant", "agenda_agente")   # luego se le preguntó otra cosa
        assert whatsapp._wa_lo_ultimo_fue_la_oferta("demo", sesion) is False

        assert whatsapp._wa_lo_ultimo_fue_la_oferta("demo", otra) is False
        assert whatsapp._wa_lo_ultimo_fue_la_oferta("otro-negocio", sesion) is False
    finally:
        with db._get_db_connection() as cx:
            cx.execute("DELETE FROM chat_messages WHERE session_id IN (?, ?)", (sesion, otra))
            cx.commit()


def test_con_propuesta_pendiente_el_modelo_recibe_la_guia(api_module):  # noqa: F811
    """La guía existía, pero no estaba en la instrucción que el agente inyecta."""
    from backend import reserva

    estado = reserva.Estado(intencion="reservar")
    propuesta = reserva.preparar_propuesta_servicio(
        estado, servicio_id="diag", nombre="Diagnóstico y presupuesto", origen="orientacion:x",
        revision_config="r1", servicio_origen="alisado")
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "oferta:" + propuesta.id)

    instruccion = reserva.instruccion_de_cierre(estado)

    assert "responder_propuesta" in instruccion, (
        "con una oferta pendiente el modelo no recibe ninguna guia y vuelve a pedir la tecnica")
    assert "tecnica" in instruccion.lower()
