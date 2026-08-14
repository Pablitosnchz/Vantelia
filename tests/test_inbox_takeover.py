"""Intervencion humana sobre una conversacion de WhatsApp (backend/inbox.py).

Lo que se valida es lo que puede costar un cliente:

- Que mientras una persona tiene el chat tomado, el asistente NO conteste por
  encima (el mensaje entra y se guarda, pero el bot calla).
- Que responder desde el panel tome la conversacion automaticamente, para que
  nadie tenga que acordarse de pulsar nada antes de escribir.
- Que fuera de la ventana de 24 h de WhatsApp se avise en vez de intentar el
  envio y fallar en silencio.
- Que un negocio no pueda tocar la conversacion de otro.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401


def _crear_conversacion_wa(api_module, cliente_id="demo", phone="34600123123"):
    """Crea una sesion de chat de WhatsApp con un mensaje entrante reciente."""
    from backend import rag, whatsapp, db, timeutils

    session_id = whatsapp._whatsapp_session_id(cliente_id, phone)
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO chat_sessions
                (id, cliente_id, origin, user_agent, started_at, last_message_at, message_count, intents_json)
            VALUES (?, ?, ?, 'WhatsApp Cloud API', ?, ?, 1, '[]')
            """,
            (session_id, cliente_id, f"whatsapp:{phone}", now, now),
        )
        connection.commit()
    rag._record_chat_message(
        session_id=session_id, cliente_id=cliente_id, role="user", content="Hola, una consulta",
    )
    return session_id


@pytest.fixture(autouse=True)
def _limpiar(api_module):
    from backend import db

    yield
    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM chat_takeovers")
        connection.commit()


# --- Estado ----------------------------------------------------------------


def test_por_defecto_el_bot_responde(api_module):
    from backend import inbox

    session_id = _crear_conversacion_wa(api_module)
    assert inbox.bot_is_muted(session_id) is False
    assert inbox.takeover_state(session_id)["active"] is False


def test_tomar_y_devolver(api_module):
    from backend import inbox

    session_id = _crear_conversacion_wa(api_module)
    estado = inbox.claim(session_id, "demo", agent_user_id="usr_1", agent_name="Recepcion")
    assert estado["active"] is True
    assert estado["agent_name"] == "Recepcion"
    assert inbox.bot_is_muted(session_id) is True

    inbox.release(session_id)
    assert inbox.bot_is_muted(session_id) is False


def test_la_intervencion_caduca_sola(api_module):
    """Nadie debe poder dejar una conversacion muda para siempre por olvido."""
    from backend import db, inbox

    session_id = _crear_conversacion_wa(api_module)
    inbox.claim(session_id, "demo", agent_user_id="usr_1")
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE chat_takeovers SET expires_at = '2020-01-01T00:00:00Z' WHERE session_id = ?",
            (session_id,),
        )
        connection.commit()
    assert inbox.bot_is_muted(session_id) is False


# --- El bot se calla de verdad ---------------------------------------------


def test_el_asistente_no_responde_con_el_chat_tomado(api_module, monkeypatch):
    """El corte esta en `_handle_whatsapp_message`, antes de menu, flujos y reglas."""
    from backend import inbox, messaging, whatsapp

    enviados = []

    async def fake_text(**kwargs):
        enviados.append(kwargs.get("text", ""))
        return True

    async def fake_list(**kwargs):
        enviados.append(kwargs.get("body", ""))
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", fake_text)
    monkeypatch.setattr(messaging, "_send_whatsapp_list", fake_list)

    phone = "34600123999"
    session_id = _crear_conversacion_wa(api_module, phone=phone)

    class _Req:  # el handler solo lo usa para registrar la sesion
        headers: dict = {}
        client = None

        def __init__(self):
            self.headers = {}

    # Sin intervencion: el saludo dispara respuesta del asistente.
    asyncio.run(
        whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id="123", from_number=phone,
            incoming_text="hola", interactive_id="", request=_Req(),
        )
    )
    assert enviados, "sin intervencion el asistente deberia responder"

    # Con el chat tomado: silencio absoluto.
    enviados.clear()
    inbox.claim(session_id, "demo", agent_user_id="usr_1", agent_name="Recepcion")
    asyncio.run(
        whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id="123", from_number=phone,
            incoming_text="hola", interactive_id="", request=_Req(),
        )
    )
    assert enviados == [], "con el chat tomado el asistente no debe hablar"


# --- Ventana de 24 h --------------------------------------------------------


def test_ventana_abierta_y_cerrada(api_module):
    from backend import db, inbox

    session_id = _crear_conversacion_wa(api_module, phone="34600123456")
    assert inbox.window_open(session_id) is True

    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE chat_messages SET created_at = '2020-01-01T00:00:00Z' WHERE session_id = ?",
            (session_id,),
        )
        connection.commit()
    assert inbox.window_open(session_id) is False


# --- API del portal ---------------------------------------------------------


def test_endpoints_del_portal(api_module, client, portal_cookies, monkeypatch):
    from backend import clients, messaging

    enviados = []

    async def fake_text(**kwargs):
        enviados.append((kwargs.get("to_number"), kwargs.get("text")))
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", fake_text)

    # WhatsApp configurado para el tenant de prueba (lo exige el envio).
    cfg = clients._get_client_config("demo")
    original_wa = dict(cfg.get("whatsapp") or {})
    cfg["whatsapp"] = {"enabled": True, "phone_number_id": "123456", "access_token_env": "", "verify_token_env": ""}
    session_id = _crear_conversacion_wa(api_module, phone="34600555111")
    try:
        estado = client.get(f"/auth/inbox/{session_id}/takeover", cookies=portal_cookies)
        assert estado.status_code == 200, estado.text
        assert estado.json()["active"] is False
        assert estado.json()["window_open"] is True

        tomado = client.post(f"/auth/inbox/{session_id}/takeover", cookies=portal_cookies)
        assert tomado.status_code == 200
        assert tomado.json()["active"] is True

        enviado = client.post(
            f"/auth/inbox/{session_id}/reply",
            cookies=portal_cookies,
            json={"text": "Le subimos la botella a la habitacion en 10 minutos."},
        )
        assert enviado.status_code == 200, enviado.text
        assert enviados and enviados[-1][0] == "34600555111"

        # El mensaje del humano queda en el historial de la conversacion.
        detalle = client.get(f"/auth/conversations/chat/{session_id}", cookies=portal_cookies).json()
        assert any("botella" in m["content"] for m in detalle["messages"])

        assert client.delete(f"/auth/inbox/{session_id}/takeover", cookies=portal_cookies).status_code == 200
        assert client.get(f"/auth/inbox/{session_id}/takeover", cookies=portal_cookies).json()["active"] is False
    finally:
        cfg["whatsapp"] = original_wa


def test_no_se_puede_responder_fuera_de_la_ventana(api_module, client, portal_cookies):
    from backend import clients, db

    cfg = clients._get_client_config("demo")
    original_wa = dict(cfg.get("whatsapp") or {})
    cfg["whatsapp"] = {"enabled": True, "phone_number_id": "123456", "access_token_env": "", "verify_token_env": ""}
    session_id = _crear_conversacion_wa(api_module, phone="34600555222")
    try:
        with db._get_db_connection() as connection:
            connection.execute(
                "UPDATE chat_messages SET created_at = '2020-01-01T00:00:00Z' WHERE session_id = ?",
                (session_id,),
            )
            connection.commit()
        res = client.post(
            f"/auth/inbox/{session_id}/reply",
            cookies=portal_cookies,
            json={"text": "Hola"},
        )
        assert res.status_code == 409
        assert "24 horas" in res.json()["detail"]
    finally:
        cfg["whatsapp"] = original_wa


def test_conversacion_de_otro_tenant_no_es_accesible(api_module, client, portal_cookies):
    session_id = _crear_conversacion_wa(api_module, cliente_id="van", phone="34600777333")
    res = client.post(f"/auth/inbox/{session_id}/takeover", cookies=portal_cookies)
    assert res.status_code == 404


def test_conversacion_web_no_admite_intervencion(api_module, client, portal_cookies):
    """De momento solo WhatsApp: el chat web no tiene canal de vuelta."""
    from backend import db, timeutils

    session_id = "web_" + uuid.uuid4().hex[:20]
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO chat_sessions (id, cliente_id, origin, user_agent, started_at, last_message_at, message_count, intents_json)
            VALUES (?, 'demo', 'https://web.example', 'test', ?, ?, 1, '[]')
            """,
            (session_id, now, now),
        )
        connection.commit()
    res = client.post(f"/auth/inbox/{session_id}/takeover", cookies=portal_cookies)
    assert res.status_code == 400


def test_responde_por_el_numero_por_el_que_entro(api_module, client, portal_cookies, monkeypatch):
    """El numero del hub de demos (o el de un centro) no es el de la config del
    tenant: contestar por el numero equivocado le llega al cliente desde un
    remitente que no conoce. Bug real detectado en produccion (ago 2026)."""
    from backend import clients, inbox, messaging

    enviados = []

    async def fake_text(**kwargs):
        enviados.append(kwargs.get("phone_number_id"))
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", fake_text)

    cfg = clients._get_client_config("demo")
    original_wa = dict(cfg.get("whatsapp") or {})
    cfg["whatsapp"] = {"enabled": True, "phone_number_id": "NUMERO_DEL_TENANT",
                       "access_token_env": "", "verify_token_env": ""}
    session_id = _crear_conversacion_wa(api_module, phone="34600555777")
    try:
        inbox.remember_inbound_number(session_id, "NUMERO_POR_EL_QUE_ENTRO")
        res = client.post(
            f"/auth/inbox/{session_id}/reply",
            cookies=portal_cookies,
            json={"text": "Le atendemos enseguida."},
        )
        assert res.status_code == 200, res.text
        assert enviados == ["NUMERO_POR_EL_QUE_ENTRO"]
    finally:
        cfg["whatsapp"] = original_wa


def test_conversacion_antigua_cae_al_numero_del_tenant(api_module, client, portal_cookies, monkeypatch):
    """Las conversaciones anteriores a la columna no tienen numero sellado."""
    from backend import clients, messaging

    enviados = []

    async def fake_text(**kwargs):
        enviados.append(kwargs.get("phone_number_id"))
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", fake_text)

    cfg = clients._get_client_config("demo")
    original_wa = dict(cfg.get("whatsapp") or {})
    cfg["whatsapp"] = {"enabled": True, "phone_number_id": "NUMERO_DEL_TENANT",
                       "access_token_env": "", "verify_token_env": ""}
    session_id = _crear_conversacion_wa(api_module, phone="34600555888")
    try:
        res = client.post(
            f"/auth/inbox/{session_id}/reply",
            cookies=portal_cookies,
            json={"text": "Hola"},
        )
        assert res.status_code == 200, res.text
        assert enviados == ["NUMERO_DEL_TENANT"]
    finally:
        cfg["whatsapp"] = original_wa
