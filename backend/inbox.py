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

import re
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


# --- Cuando la clienta pide hablar con alguien -----------------------------
#
# La accion `pasar_a_humano` existia solo como REGLA del negocio, y su plantilla
# se dispara con quejas. Si nadie la configura -el salon piloto tiene tres reglas
# y ninguna es esa-, a "quiero hablar con una persona" el asistente seguia
# hablando. Pedir una persona no puede depender de que el negocio se acuerde de
# configurarlo: es lo mismo que con una foto, hace falta alguien de verdad.

_PIDE_UNA_PERSONA = re.compile(
    # Un verbo de hablar/pasar/atender y, cerca, una palabra de persona.
    r"\b(?:habl\w*|pas\w*|atien\w*|atend\w*|pon\w*|contact\w*)\b[^.!?]{0,30}?\b(?:persona|humano|humana|alguien|encargad[ao]|responsable|recepcion|operador[ao]?)\b"
    r"|\bno quiero (?:hablar|seguir)[^.!?]{0,20}?(?:bot|robot|maquina|ia|inteligencia artificial)\b"
    r"|\beres (?:un |una )?(?:bot|robot|maquina|ia)\b"
    # En ingles: un hotel recibe a huespedes de fuera, y "can I speak to someone?"
    # no llegaba a nadie.
    r"|\b(?:speak|talk|chat)\w*\b[^.!?]{0,30}?\b(?:person|human|someone|somebody|staff|reception|receptionist|manager|agent)\b"
    r"|\bare you (?:a |an )?(?:bot|robot|machine|ai)\b"
)

DEFECTO_PASO_A_PERSONA = (
    "Claro, ahora mismo aviso a una compañera. Espera un momento y te contesta ella por aquí 😊"
)

# El de arriba es el del salon piloto: tutea, pone emoji y da por hecho que
# contesta una compañera. Un hotel que trata de usted, o un huesped que escribe
# en ingles, no pueden recibir eso. El trato y los emojis salen del TONO que el
# negocio ya eligio en el portal (fuente unica `textnorm._tono_config`).
_TEXTOS_PERSONA = {
    # (trato, hay_vuelta, con_telefono)
    ("usted", True, False): "Por supuesto, aviso ahora mismo a alguien del equipo. "
                            "Espere un momento y le contestarán por aquí.",
    ("usted", False, True): "Por supuesto. Por aquí no puedo pasarle con nadie, pero si llama "
                            "al %s le atienden directamente.",
    ("usted", False, False): "Por supuesto. Por aquí no puedo pasarle con nadie, pero si nos "
                             "escribe por WhatsApp le atiende alguien del equipo.",
    ("en", True, False): "Of course, I'm letting someone from the team know right now. "
                         "Please wait a moment and they will reply here.",
    ("en", False, True): "Of course. I can't transfer you from here, but if you call %s "
                         "someone will help you directly.",
    ("en", False, False): "Of course. I can't transfer you from here, but if you message us "
                          "on WhatsApp someone from the team will help you.",
}


def _trato_para(config, mensaje: str) -> str:
    """"en" si escribe en otro idioma, "usted" si el negocio trata de usted, o ""."""
    from backend import keywords, textnorm

    idioma = keywords.idioma_de(mensaje) if mensaje else ""
    if idioma and idioma != "es":
        return "en"
    tono = textnorm._tono_config(config or {}) or {}
    return "usted" if tono.get("tratamiento") == "usted" else ""


def _sin_emojis_si_no_quiere(texto: str, config) -> str:
    from backend import textnorm

    tono = textnorm._tono_config(config or {}) or {}
    if tono.get("emojis") == "ninguno":
        return texto.replace(" 😊", "").replace("😊", "").strip()
    return texto


def pide_una_persona(texto: str) -> bool:
    """Esta pidiendo que le atienda alguien del equipo, no el asistente."""
    from backend import textnorm as _t

    return bool(_PIDE_UNA_PERSONA.search(_t._strip_accents(str(texto or "").lower())))


def _seccion(cliente_id: str, config=None) -> Dict[str, Any]:
    if config is None:
        from backend import clients

        try:
            config = clients._get_client_config(cliente_id)
        except Exception:  # noqa: BLE001
            return {}
    seccion = (config or {}).get("pasar_a_humano")
    return seccion if isinstance(seccion, dict) else {}


def paso_a_persona_activo(cliente_id: str, config=None) -> bool:
    """Encendido salvo que el negocio lo apague."""
    return bool(_seccion(cliente_id, config).get("enabled", True))


def texto_al_pedir_persona(cliente_id: str, config=None, *, hay_vuelta: bool = True,
                           mensaje: str = "") -> str:
    """Que se le contesta a quien pide una persona.

    `hay_vuelta` dice si por ESE canal alguien puede contestarle. Por WhatsApp si:
    el equipo responde desde su movil o desde el panel, y por eso ahi el asistente
    se calla. Por el widget de la web NO hay vuelta -no existe canal de respuesta-,
    asi que prometerle que "te contesta enseguida" seria mentira: se le da un
    telefono donde si le van a atender.
    """
    propio = str(_seccion(cliente_id, config).get("texto") or "").strip()
    if propio:
        return propio
    if config is None:
        from backend import clients

        try:
            config = clients._get_client_config(cliente_id)
        except Exception:  # noqa: BLE001
            config = {}
    trato = _trato_para(config, mensaje)
    if hay_vuelta:
        if trato:
            return _TEXTOS_PERSONA[(trato, True, False)]
        return _sin_emojis_si_no_quiere(DEFECTO_PASO_A_PERSONA, config)
    from backend import clients

    telefono = ""
    try:
        telefono = str((clients._get_client_config(cliente_id).get("contacto") or {})
                       .get("telefono") or "").strip()
    except Exception:  # noqa: BLE001
        telefono = ""
    if trato:
        if telefono:
            return _TEXTOS_PERSONA[(trato, False, True)] % telefono
        return _TEXTOS_PERSONA[(trato, False, False)]
    if telefono:
        return ("Claro. Por aquí no puedo pasarte con nadie, pero si llamas al %s "
                "te atienden directamente." % telefono)
    return ("Claro. Por aquí no puedo pasarte con nadie, pero si nos escribes por "
            "WhatsApp te atiende una compañera.")


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
    from datetime import timedelta

    # En minutos: la cuenta en horas redondeaba cualquier plazo corto a una hora.
    plazo = max(1, int(minutes or DEFAULT_TAKEOVER_MINUTES))
    expires_at = timeutils._to_utc_iso(timeutils._utc_now() + timedelta(minutes=plazo))
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


def inbound_number_for_phone(cliente_id: str, phone: str) -> str:
    """Numero por el que este cliente escribio por ultima vez ("" si no consta).

    Hace falta para responderle desde el mismo numero al que escribio: el negocio
    puede tener varios (numero por centro, numero de demo compartido) y la
    confirmacion saldria desde uno que el cliente no reconoce, o no saldria.
    """
    cliente_id = str(cliente_id or "").strip()
    digitos = "".join(c for c in str(phone or "") if c.isdigit())
    if not cliente_id or not digitos:
        return ""
    try:
        with db._get_db_connection() as connection:
            fila = connection.execute(
                """
                SELECT wa_phone_number_id FROM chat_sessions
                WHERE cliente_id = ? AND origin LIKE ? AND wa_phone_number_id <> ''
                ORDER BY last_message_at DESC LIMIT 1
                """,
                (cliente_id, "whatsapp:%" + digitos[-9:]),
            ).fetchone()
    except Exception:  # noqa: BLE001 - nunca debe tumbar un envio
        return ""
    return (fila["wa_phone_number_id"] if fila else "") or ""


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
