# -*- coding: utf-8 -*-
"""Cuando el equipo contesta desde su WhatsApp Business, el asistente se calla; al
volver no empieza de cero.

POR QUE EXISTE
--------------
Decision de Pablo (11-sep-2026), con el +31 ya en Coexistence:

- el asistente vuelve solo a la HORA del ultimo mensaje de Alicia (antes, 2 h);
- al volver no le suelta "Hola cariño, ¿en que puedo ayudarte?" con el menu a
  quien Alicia acaba de atender;
- y sigue sabiendo lo hablado, tambien lo que escribio ella. El historial del
  agente se cortaba a la media hora de silencio: al volver ya no sabia de que iba.
"""
from __future__ import annotations

import asyncio
import datetime
import uuid

from test_booking_exhaustive import api_module, client  # noqa: F401


def _hace(minutos):
    from backend import timeutils

    return timeutils._to_utc_iso(timeutils._utc_now() - datetime.timedelta(minutes=minutos))


def _mensaje(session_id, rol, texto, intent, hace_min):
    from backend import db

    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO chat_messages (session_id, cliente_id, role, content, intent, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, "demo", rol, texto, intent, _hace(hace_min)),
        )
        conexion.commit()


def _minutos_callado(session_id):
    from backend import db, timeutils

    with db._get_db_connection() as conexion:
        fila = conexion.execute(
            "SELECT expires_at FROM chat_takeovers WHERE session_id = ?", (session_id,)
        ).fetchone()
    return (timeutils._from_utc_iso(fila["expires_at"]) - timeutils._utc_now()).total_seconds() / 60


def test_al_contestar_desde_la_app_se_calla_una_hora(api_module):  # noqa: F811
    from backend import inbox, whatsapp

    telefono = "34600777001"
    session_id = whatsapp._whatsapp_session_id("demo", telefono)
    inbox.release(session_id)
    whatsapp._handle_whatsapp_echoes(
        "WA_NUM_ID", [{"to": telefono, "type": "text", "text": {"body": "Te espero a las 6"}}],
        forced_cliente_id="demo",
    )
    try:
        assert 55 <= _minutos_callado(session_id) <= 61
    finally:
        inbox.release(session_id)


def test_el_plazo_se_cuenta_en_minutos(api_module):  # noqa: F811
    """En horas, cualquier plazo corto se redondeaba a una hora."""
    from backend import inbox

    session_id = "wa_plazo_%s" % uuid.uuid4().hex[:10]
    inbox.claim(session_id, "demo", agent_user_id="", minutes=45)
    try:
        assert 40 <= _minutos_callado(session_id) <= 46
    finally:
        inbox.release(session_id)


def test_el_negocio_puede_cambiar_cuanto_se_calla(api_module, monkeypatch):  # noqa: F811
    from backend import clients, whatsapp

    original = clients._get_client_config

    def con_45(cliente_id, *args, **kwargs):
        config = dict(original(cliente_id, *args, **kwargs))
        config["whatsapp"] = dict(config.get("whatsapp") or {}, silencio_tras_responder_min=45)
        return config

    monkeypatch.setattr(clients, "_get_client_config", con_45)
    assert whatsapp._wa_minutos_de_silencio("demo") == 45


def test_lo_hablado_con_alicia_sigue_contando_al_volver(api_module):  # noqa: F811
    """Mas de media hora despues, el agente sigue viendo lo que dijo Alicia."""
    from backend import agent

    session_id = "wa_contexto_%s" % uuid.uuid4().hex[:10]
    _mensaje(session_id, "user", "hola, puedo ir hoy?", "", 100)
    _mensaje(session_id, "assistant", "Si, pasate a las 6 y te lo miro yo", "human_reply_app", 95)
    _mensaje(session_id, "user", "vale, gracias", "human_takeover", 90)
    _mensaje(session_id, "user", "hola", "", 0)  # vuelve a escribir: ya habla el asistente

    contenidos = [m["content"] for m in agent._historial(session_id, "demo")]

    assert "Si, pasate a las 6 y te lo miro yo" in contenidos, contenidos
    assert "hola, puedo ir hoy?" in contenidos, contenidos


def test_sin_persona_de_por_medio_el_silencio_sigue_cerrando(api_module):  # noqa: F811
    """Control: la charla de hace hora y media sin nadie del equipo no se cuela."""
    from backend import agent

    session_id = "wa_sin_persona_%s" % uuid.uuid4().hex[:10]
    _mensaje(session_id, "user", "cuanto cuesta un corte?", "", 100)
    _mensaje(session_id, "assistant", "20 euros", "", 99)
    _mensaje(session_id, "user", "hola", "", 0)

    assert [m["content"] for m in agent._historial(session_id, "demo")] == ["hola"]


def _saluda(monkeypatch, telefono):
    from backend import whatsapp

    turnos, menus = [], []

    async def agente(**kwargs):
        turnos.append(kwargs["incoming_text"])
        return True

    async def menu(**kwargs):
        menus.append(kwargs)

    monkeypatch.setattr(whatsapp, "_wa_turno_del_agente", agente)
    monkeypatch.setattr(whatsapp, "_wa_send_main_menu", menu)
    monkeypatch.setattr(whatsapp, "_wa_modo_conversacional", lambda config: True)
    whatsapp._wa_clear_flow("demo", telefono)
    asyncio.run(whatsapp._handle_whatsapp_message(
        cliente_id="demo", phone_number_id="WA_NUM_ID", from_number=telefono,
        incoming_text="hola", interactive_id="", request=None,
    ))
    return turnos, menus


def test_un_hola_despues_de_alicia_no_saca_el_menu(api_module, monkeypatch):  # noqa: F811
    from backend import inbox, whatsapp

    telefono = "34600777005"
    session_id = whatsapp._whatsapp_session_id("demo", telefono)
    inbox.release(session_id)
    _mensaje(session_id, "assistant", "Te espero a las 6", "human_reply_app", 70)

    turnos, menus = _saluda(monkeypatch, telefono)

    assert menus == [], "le ha soltado la bienvenida con el menu a quien acaba de atender Alicia"
    assert turnos == ["hola"], "lo tiene que coger el agente, que tiene la conversacion"


def test_sin_persona_de_por_medio_un_hola_sigue_saludando(api_module, monkeypatch):  # noqa: F811
    """Control: a quien escribe por primera vez se le sigue dando la bienvenida."""
    turnos, menus = _saluda(monkeypatch, "34600777006")

    assert menus and turnos == []
