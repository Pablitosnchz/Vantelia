# -*- coding: utf-8 -*-
"""Los cuatro hallazgos de la revisión independiente del candidato (13-sep-2026).

POR QUE EXISTE
--------------
Antes de desplegar, una revisión en frío de 782a53f..HEAD (sin el contexto de por qué
se hizo cada cosa) encontró cuatro defectos, todos reproducidos ejecutándolos:

1. «el jueves 18 a las 11» con huecos a las 11:00 y a las 18:00 daba las **18:00**:
   `_hora_coloquial` probaba también el número del día. Aceptada la cita de
   diagnóstico, se le guardaba a una hora que no había dicho.
2. En `booking_name` (desde 8ca6088 llega la conversación hablada) cualquier texto era
   el nombre: «perdona, mejor a las 16» se guardaba como tal.
3. «sí, el jueves a las 17» contaba como un «sí» a secas: se aceptaba la oferta sin
   pasar por el agente y el día y la hora nuevos se perdían.
4. El freno `cancelar_sin_pedirlo` bloqueaba cancelaciones legítimas: «no puedo venir,
   quítamela», «bórramela», y el «sí» a «¿quieres que la cancele?».

Además, la hora pendiente (`hora_sin_hueco`) no se soltaba al empezar otra gestión.
"""
from __future__ import annotations

import asyncio

import pytest

from test_alternativa_de_precio import politica  # noqa: F401
from test_booking_exhaustive import api_module  # noqa: F401
from test_la_hora_dicha_sobrevive_a_aceptar import _libres
from test_la_hora_suelta_sin_huecos import _con_la_oferta, _conversacion


# ─── 1. El número del día no es una hora ─────────────────────────────────

HUECOS = ["10:00", "10:30", "11:00", "14:00", "15:00", "16:00", "17:00", "18:00"]


@pytest.mark.parametrize("dicho,hora", [
    ("el jueves 18 a las 11", "11:00"),        # el caso de la revision
    ("el martes 15 a las 10", "10:00"),
    ("el 16 a las 11 me va bien", "11:00"),
    ("el 15/09 a las 17", "17:00"),
    ("el 15 de septiembre a las 14", "14:00"),
    ("a las 15", "15:00"),                      # lo de siempre
    ("14", "14:00"),                            # contestar solo la hora
    ("sobre las 5 de la tarde", "17:00"),
    ("mejor la de las 10:30", "10:30"),
    ("el 15 de septiembre", ""),                # un dia no es una hora
    ("el jueves 18", ""),
])
def test_la_hora_no_se_confunde_con_el_dia(dicho, hora):
    from backend import reserva

    assert reserva._hora_coloquial(dicho, HUECOS) == hora


def test_aceptar_con_dia_y_hora_en_la_frase_guarda_su_hora(politica, monkeypatch):  # noqa: F811
    from backend import booking

    _libres(monkeypatch, {"11:00", "18:00"})
    estado = _conversacion("quiero un alisado", "no lo tengo claro", "el 2030-01-18 a las 11")
    propuesta = _con_la_oferta(estado)
    assert booking.contestar_alternativa_de_precio("salon", estado, propuesta.id, "acepta")

    assert asyncio.run(booking.conservar_la_hora_dicha("salon", estado, "")) is True
    assert estado.hora == "11:00", "se le guardaria a las %s, una hora que no ha dicho" % estado.hora


def test_empezar_otra_gestion_suelta_la_hora_pendiente():
    from backend import reserva

    estado = reserva.Estado(intencion="reservar", hora_sin_hueco="a las 15", hecho=True)
    reserva.empezar_otra_gestion(estado)
    assert estado.hora_sin_hueco == ""


# ─── 2. Lo que no es un nombre vuelve al agente ──────────────────────────

@pytest.mark.parametrize("dicho,no_es", [
    ("perdona, mejor a las 16", True),   # el caso de la revision
    ("si", True),
    ("¿y cuanto dura?", True),
    ("mejor el jueves", True),
    ("Ana Ruiz Perez", False),
    ("María José López García", False),
])
def test_distingue_un_nombre_de_una_conversacion(api_module, dicho, no_es):  # noqa: F811
    from backend import whatsapp

    assert whatsapp._wa_no_parece_un_nombre(dicho) is no_es


def test_booking_name_devuelve_la_conversacion_al_agente(api_module, monkeypatch):  # noqa: F811
    from backend import appstate, clients, messaging, whatsapp

    flow = appstate.WAFlowState(cliente_id="demo", from_number="34600777444", flow="booking_name",
                                servicio="Diagnostico y presupuesto", fecha="2030-01-08", hora="15:00")
    monkeypatch.setattr(whatsapp, "_wa_get_flow", lambda *a: flow)
    monkeypatch.setattr(whatsapp, "_wa_modo_conversacional", lambda config: True)
    monkeypatch.setattr(clients, "exige_dos_apellidos", lambda cliente_id: True)
    monkeypatch.setattr(whatsapp.inbox, "remember_inbound_number", lambda *a: None)
    monkeypatch.setattr(whatsapp.inbox, "bot_is_muted", lambda *a: False)
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **k: "sesion")
    al_agente, resumenes = [], []

    async def turno(**kwargs):
        al_agente.append(kwargs["incoming_text"])
        return True

    async def resumen(**kwargs):
        resumenes.append(kwargs["flow"].nombre)
        return True

    async def enviar(**kwargs):
        return True

    monkeypatch.setattr(whatsapp, "_wa_turno_del_agente", turno)
    monkeypatch.setattr(whatsapp, "_wa_send_booking_summary", resumen)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviar)

    asyncio.run(whatsapp._handle_whatsapp_message(
        cliente_id="demo", phone_number_id="canal", from_number="34600777444",
        incoming_text="perdona, mejor a las 16", interactive_id="", request=None))

    assert al_agente == ["perdona, mejor a las 16"], "la correccion no ha llegado al agente"
    assert resumenes == [], "se ha montado un resumen con la conversacion como nombre"
    assert flow.nombre != "perdona, mejor a las 16"


# ─── 3. Un «sí» que trae día u hora no es solo un sí ─────────────────────

@pytest.mark.parametrize("dicho,trae", [
    ("si, el jueves a las 17", True),   # el caso de la revision
    ("si, mañana", True),
    ("sí, a las 10", True),
    ("si", False),
    ("sí, perfecto", False),
])
def test_detecta_dia_u_hora_en_el_si(api_module, dicho, trae):  # noqa: F811
    from backend import whatsapp

    assert whatsapp._wa_trae_dia_u_hora(dicho) is trae


def test_si_con_dia_y_hora_lo_lleva_el_agente(politica, monkeypatch):  # noqa: F811
    from test_si_escrito_acepta_la_oferta import _canal, _turno
    from test_alternativa_de_precio import ofrecer

    estado, _propuesta = ofrecer()
    flow, anotado = _canal(monkeypatch, estado, ultimo_fue_la_oferta=True)

    _turno(flow, "si, el jueves a las 17")

    assert estado.propuesta_servicio.estado == "ofrecida", "se ha aceptado perdiendo el dia y la hora"
    assert anotado["agente"] == ["si, el jueves a las 17"]


# ─── 4. Cancelar lo que ella pide, dicho como lo diga ────────────────────

@pytest.mark.parametrize("dicho,pide", [
    ("no puedo venir mañana, quítamela", True),
    ("bórramela porfa", True),
    ("elimínala", True),
    ("quiero anular mi cita", True),
    ("quiero cambiar mi cita de dia", False),
])
def test_formas_de_pedir_que_se_la_quiten(api_module, dicho, pide):  # noqa: F811
    from backend import reserva

    assert reserva.pide_anular(dicho) is pide


@pytest.mark.parametrize("ultimo,mensaje,autoriza", [
    ("¿Quieres que te cancele la cita del martes?", "si", True),
    ("¿La anulo entonces?", "sí, gracias", True),
    ("¿A qué hora te viene bien?", "si", False),           # otra pregunta
    ("¿Quieres que te cancele la cita del martes?", "no", False),
])
def test_si_a_la_pregunta_de_cancelar(api_module, ultimo, mensaje, autoriza):  # noqa: F811
    from backend import agent

    historial = [{"role": "user", "content": "tengo una cita el martes"},
                 {"role": "assistant", "content": ultimo}]
    assert agent._le_pregunto_si_la_cancela(historial, mensaje) is autoriza


def test_el_si_a_cancelar_llega_a_cancelar_cita(api_module, monkeypatch):  # noqa: F811
    from test_no_se_cancela_sin_pedirlo import _turno

    ejecutadas = _turno(monkeypatch, historial=[
        {"role": "user", "content": "tengo cita el martes y no se si ire"},
        {"role": "assistant", "content": "¿Quieres que te cancele la cita del martes?"},
    ], mensaje="si", intencion="")

    assert ejecutadas == ["cancelar_cita"]
