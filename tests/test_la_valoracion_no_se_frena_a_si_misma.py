# -*- coding: utf-8 -*-
"""Aceptada la cita de diagnóstico, el nombre lleva al resumen: sin freno ni frase.

POR QUE EXISTE
--------------
13-sep-2026, caso crítico `dice-que-si-y-acaba-en-cita`, 6 tiradas con modelo
real sobre 197afb0: 6 de 6 OK al reintento y 0 de 6 al primer intento. Los seis
primeros intentos acabaron igual:

    ella «si»                  IA «De acuerdo, cita de Diagnóstico y presupuesto el
                                   martes 15 a las 15:00. ¿Me dices tu nombre?»
    ella «me llamo Ana Ruiz»   IA «Te lo digo con sinceridad, cariño: el precio
                                   depende mucho de tu pelo... te cogemos una cita
                                   de 15 minutos para hacerte un diagnóstico»

Tres fallos, cada uno con su test:
  1. El freno del precio frenaba LA PROPIA valoración: la regla «Color y mechas»
     casaba con «Diagnóstico y presupuesto» por su categoría, «Trabajos de color».
  2. «Ha preguntado el precio en esta conversación» leía los últimos 30 mensajes
     del teléfono SIN corte por tiempo. El teléfono del primer intento arrastraba
     17 preguntas de precio del 22 de agosto; el del reintento, ninguna. Una
     clienta que preguntó el precio hace semanas es otra conversación.
  3. Desde 8ca6088 el nombre tras aceptar entra por `booking_name`, que tomaba el
     mensaje entero: la cita salía a nombre de «me llamo Ana Ruiz Perez».
"""
from __future__ import annotations

import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


# ─── 1. La valoración no se frena a sí misma ─────────────────────────────

@pytest.mark.parametrize("servicio", [
    "Diagnostico y presupuesto", "Diagnóstico y presupuesto",
    "Diagnostico y presupuesto para extensiones", "Consulta de valoracion",
])
def test_reservar_la_valoracion_no_dispara_el_freno(api_module, monkeypatch, servicio):  # noqa: F811
    from backend import booking

    regla = {"id": "color", "accion": "ofrecer_cita", "texto": "El precio depende de tu pelo"}
    monkeypatch.setattr(booking, "regla_de_precio_para", lambda *a, **k: dict(regla))
    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda *a, **k: {"nombre": "Diagnostico y presupuesto"})

    assert booking.bloquea_por_regla_de_precio("salon", servicio, True) == {}, (
        "se le ofrece un diagnostico a quien esta cogiendo el diagnostico")


def test_el_tratamiento_sigue_frenandose(api_module, monkeypatch):  # noqa: F811
    """El control: lo que el freno protege no se ha apagado."""
    from backend import booking

    regla = {"id": "color", "accion": "ofrecer_cita", "texto": "El precio depende de tu pelo"}
    monkeypatch.setattr(booking, "regla_de_precio_para", lambda *a, **k: dict(regla))
    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda *a, **k: {"nombre": "Diagnostico y presupuesto"})

    parada = booking.bloquea_por_regla_de_precio("salon", "Mechas o balayage medio", True)

    assert parada["reserva_esto_en_su_lugar"] == "Diagnostico y presupuesto"


# ─── 2. «En esta conversación» es esta conversación ──────────────────────

def _escribir(sesion, mensajes):
    from backend import db

    with db._get_db_connection() as cx:
        for rol, texto, momento in mensajes:
            cx.execute(
                "INSERT INTO chat_messages (session_id, cliente_id, role, content, intent, created_at)"
                " VALUES (?, 'demo', ?, ?, '', ?)",
                (sesion, rol, texto, momento.strftime("%Y-%m-%dT%H:%M:%SZ")))
        cx.commit()


def _borrar(sesion):
    from backend import db

    with db._get_db_connection() as cx:
        cx.execute("DELETE FROM chat_messages WHERE session_id = ?", (sesion,))
        cx.commit()


@pytest.mark.parametrize("pregunta", ["cuanto cuestan unas mechas?"])
def test_una_pregunta_de_precio_de_hace_semanas_no_cuenta(api_module, pregunta):  # noqa: F811
    from backend import booking

    sesion = "wa_prueba_%s" % uuid.uuid4().hex[:8]
    ahora = datetime.now(timezone.utc)
    hace_semanas = ahora - timedelta(days=22)
    try:
        _escribir(sesion, [
            ("user", pregunta, hace_semanas),
            ("assistant", "El precio depende de tu pelo", hace_semanas + timedelta(seconds=5)),
            ("user", "quiero un alisado", ahora - timedelta(minutes=3)),
            ("assistant", "¿Keratina o ácido láctico?", ahora - timedelta(minutes=3)),
            ("user", "me llamo Ana Ruiz Perez", ahora),
        ])
        assert booking.pidio_precio_en_la_conversacion("demo", sesion) is False, (
            "una pregunta de precio de otra conversacion frena la cita de hoy")
    finally:
        _borrar(sesion)


def test_la_pregunta_de_precio_de_hoy_si_cuenta(api_module):  # noqa: F811
    from backend import booking

    sesion = "wa_prueba_%s" % uuid.uuid4().hex[:8]
    ahora = datetime.now(timezone.utc)
    try:
        _escribir(sesion, [
            ("user", "cuanto cuestan unas mechas?", ahora - timedelta(minutes=4)),
            ("assistant", "El precio depende de tu pelo", ahora - timedelta(minutes=4)),
            ("user", "vale, quiero cita", ahora - timedelta(minutes=2)),
            ("user", "me llamo Ana Ruiz Perez", ahora),
        ])
        assert booking.pidio_precio_en_la_conversacion("demo", sesion) is True
    finally:
        _borrar(sesion)


def test_renunciar_al_diagnostico_hace_semanas_tampoco_cuenta(api_module, monkeypatch):  # noqa: F811
    from backend import booking

    vistos = []

    def renuncio(cliente_id, mensajes):
        vistos.append(list(mensajes))
        return any("sin diagnostico" in m for m in mensajes)

    monkeypatch.setattr(booking, "renuncio_al_diagnostico_en_mensajes", renuncio)
    sesion = "wa_prueba_%s" % uuid.uuid4().hex[:8]
    ahora = datetime.now(timezone.utc)
    try:
        _escribir(sesion, [
            ("user", "lo quiero sin diagnostico", ahora - timedelta(days=20)),
            ("user", "quiero unas mechas", ahora),
        ])
        assert booking.renuncio_al_diagnostico_en_la_conversacion("demo", sesion) is False
        assert vistos and vistos[-1] == ["quiero unas mechas"], vistos
    finally:
        _borrar(sesion)


# ─── 3. El nombre dentro de una frase ────────────────────────────────────

@pytest.mark.parametrize("dicho", ["me llamo Ana Ruiz Perez", "Ana Ruiz Perez"])
def test_booking_name_guarda_el_nombre_y_no_la_frase(api_module, monkeypatch, dicho):  # noqa: F811
    from backend import appstate, clients, messaging, whatsapp

    flow = appstate.WAFlowState(cliente_id="demo", from_number="34600777333", flow="booking_name",
                                servicio="Diagnostico y presupuesto", fecha="2030-01-08", hora="15:00")
    monkeypatch.setattr(whatsapp, "_wa_get_flow", lambda *a: flow)
    monkeypatch.setattr(clients, "exige_dos_apellidos", lambda cliente_id: True)
    monkeypatch.setattr(whatsapp.inbox, "remember_inbound_number", lambda *a: None)
    monkeypatch.setattr(whatsapp.inbox, "bot_is_muted", lambda *a: False)
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **k: "sesion")
    resumenes = []

    async def resumen(**kwargs):
        resumenes.append(kwargs["flow"].nombre)
        return True

    async def enviar(**kwargs):
        return True

    monkeypatch.setattr(whatsapp, "_wa_send_booking_summary", resumen)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviar)

    asyncio.run(whatsapp._handle_whatsapp_message(
        cliente_id="demo", phone_number_id="canal", from_number="34600777333",
        incoming_text=dicho, interactive_id="", request=types.SimpleNamespace(
            client=None, headers={})))

    assert resumenes == ["Ana Ruiz Perez"], (
        "la cita saldria a nombre de %r" % (resumenes or [flow.nombre]))
