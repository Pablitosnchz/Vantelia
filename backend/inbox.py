"""Intervencion humana sobre una conversacion de WhatsApp (ago 2026).

Al pasar su numero a Cloud API, el negocio pierde la app del movil: veia los
mensajes en el panel pero no podia contestar, y todo lo que el asistente no
cubre (un hotel: "subidme una botella a la habitacion") se quedaba sin respuesta.

Aqui esta la pieza que faltaba: el equipo "toma" la conversacion, el asistente se
calla en ESA conversacion, y responden ellos desde el panel. Al terminar la
devuelven al asistente (o se devuelve sola por inactividad, para que nadie deje
un chat mudo sin darse cuenta).

Limite de Meta que condiciona todo: solo se puede escribir texto libre dentro de
las 24 h siguientes al ultimo mensaje del cliente. Fuera de esa ventana haria
falta una plantilla aprobada, que hoy no soportamos, asi que se avisa claro en
lugar de intentar el envio y fallar en silencio.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from backend import db, settings, textnorm, timeutils

# Si nadie escribe desde el panel en este tiempo, el asistente recupera la
# conversacion solo: evita dejarlo mudo por olvidar pulsar "devolver".
DEFAULT_TAKEOVER_MINUTES = int(getattr(settings, "INBOX_TAKEOVER_MINUTES", 120) or 120)

# Ventana de servicio de WhatsApp Cloud API para texto libre.
CUSTOMER_WINDOW_HOURS = 24

WINDOW_CLOSED_MESSAGE = (
    "Han pasado mas de 24 horas desde el ultimo mensaje del cliente. WhatsApp solo "
    "permite escribir libremente dentro de esa ventana: espera a que vuelva a "
    "escribir o contacta por telefono o email."
)


def _row_to_state(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    if not row:
        return {"active": False, "agent_user_id": "", "agent_name": "", "since": "", "expires_at": ""}
    return {
        "active": True,
        "agent_user_id": row["agent_user_id"] or "",
        "agent_name": row["agent_name"] or "",
        "since": row["created_at"] or "",
        "expires_at": row["expires_at"] or "",
    }


def _active_row(connection: sqlite3.Connection, session_id: str) -> Optional[sqlite3.Row]:
    row = connection.execute(
        "SELECT * FROM chat_takeovers WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not row:
        return None
    if row["expires_at"] and row["expires_at"] <= timeutils._utc_now_iso():
        return None
    return row


def takeover_state(session_id: str) -> Dict[str, Any]:
    session_id = str(session_id or "").strip()
    if not session_id:
        return _row_to_state(None)
    try:
        with db._get_db_connection() as connection:
            return _row_to_state(_active_row(connection, session_id))
    except Exception as exc:  # noqa: BLE001 - nunca debe tumbar el webhook
        settings.logger.warning("No se pudo leer el estado de intervencion de %s: %s", session_id, exc)
        return _row_to_state(None)


def bot_is_muted(session_id: str) -> bool:
    """True si un humano tiene tomada la conversacion (el asistente no responde)."""
    return bool(takeover_state(session_id)["active"])


def claim(session_id: str, cliente_id: str, *, agent_user_id: str, agent_name: str = "",
          minutes: int = DEFAULT_TAKEOVER_MINUTES) -> Dict[str, Any]:
    """El equipo toma la conversacion. Renovable: cada respuesta la prolonga."""
    expires_at = timeutils._expires_at_in_hours(max(1, int(minutes or DEFAULT_TAKEOVER_MINUTES)) // 60 or 1)
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO chat_takeovers (session_id, cliente_id, agent_user_id, agent_name, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                agent_user_id = excluded.agent_user_id,
                agent_name = excluded.agent_name,
                expires_at = excluded.expires_at
            """,
            (
                session_id,
                cliente_id,
                agent_user_id,
                textnorm._sanitize_text(agent_name)[:120],
                now_iso,
                expires_at,
            ),
        )
        connection.commit()
    return takeover_state(session_id)


def release(session_id: str) -> Dict[str, Any]:
    """Devuelve la conversacion al asistente."""
    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM chat_takeovers WHERE session_id = ?", (session_id,))
        connection.commit()
    return _row_to_state(None)


def remember_inbound_number(session_id: str, phone_number_id: str) -> None:
    """Sella en la conversacion el numero por el que ENTRO el mensaje.

    Es el que hay que usar para responder: el de la config del tenant puede ser
    otro (numero de demo compartido, numero por centro) y la respuesta saldria
    desde un numero distinto al que el cliente conoce.
    """
    session_id = str(session_id or "").strip()
    phone_number_id = str(phone_number_id or "").strip()
    if not session_id or not phone_number_id:
        return
    try:
        with db._get_db_connection() as connection:
            connection.execute(
                "UPDATE chat_sessions SET wa_phone_number_id = ? WHERE id = ?",
                (phone_number_id, session_id),
            )
            connection.commit()
    except Exception as exc:  # noqa: BLE001 - nunca debe tumbar el webhook
        settings.logger.warning("No se pudo sellar el numero de %s: %s", session_id, exc)


def inbound_number(session_id: str) -> str:
    """Numero por el que entro la conversacion ("" si es antigua y no se sello)."""
    try:
        with db._get_db_connection() as connection:
            row = connection.execute(
                "SELECT wa_phone_number_id FROM chat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
    except Exception:  # noqa: BLE001
        return ""
    return (row["wa_phone_number_id"] if row else "") or ""


def last_inbound_at(session_id: str) -> str:
    with db._get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT created_at FROM chat_messages
            WHERE session_id = ? AND role = 'user'
            ORDER BY created_at DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    return (row["created_at"] if row else "") or ""


def window_open(session_id: str) -> bool:
    """¿Se puede escribir texto libre? (menos de 24 h desde el ultimo mensaje del cliente)"""
    last = last_inbound_at(session_id)
    if not last:
        return False
    dt = timeutils._from_utc_iso(last)
    if not dt:
        return False
    delta = timeutils._utc_now() - dt
    return delta.total_seconds() <= CUSTOMER_WINDOW_HOURS * 3600
