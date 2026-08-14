"""Numero de WhatsApp compartido para demos comerciales (ago 2026).

Problema: el numero de pruebas de Meta solo responde a moviles autorizados de
antemano, y pedirle a un prospecto el codigo de verificacion que le llega por
WhatsApp huele a fraude. La solucion de fondo es un numero PROPIO en Cloud API
al que cualquiera pueda escribir. Pero un numero mapea a UN tenant, y aqui hace
falta que el mismo numero atienda a muchos prospectos, cada uno hablando con SU
asistente.

Este modulo resuelve eso: el comercial genera un CODIGO por prospecto y le pasa
un enlace `wa.me` con el texto ya escrito. El prospecto solo pulsa enviar; el
primer mensaje ata su telefono a ese tenant durante unos dias y a partir de ahi
conversa con su propio asistente con normalidad.

Seguridad: solo se puede entrar con un codigo emitido por un admin (aleatorio,
caducable y revocable). Nunca se acepta el id del tenant como codigo, para que
nadie pueda colarse en el asistente de un cliente real probando nombres.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
from typing import Any, Dict, List, Optional

from backend import db, settings, textnorm, timeutils

# Alfabeto sin caracteres ambiguos (0/O, 1/I): el codigo se dicta por telefono.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
DEFAULT_CODE_DAYS = 30
DEFAULT_ROUTE_DAYS = 15

# "DEMO ABC123", "demo: abc123", "Hola, DEMO-ABC123"
_CODE_IN_TEXT_RE = re.compile(r"\bdemo\W{0,3}([a-z0-9]{%d})\b" % CODE_LENGTH, re.IGNORECASE)


def hub_phone_number_ids() -> set:
    """phone_number_id de los numeros de demo compartidos (env, admite varios)."""
    raw = str(getattr(settings, "WHATSAPP_DEMO_PHONE_NUMBER_ID", "") or "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def is_hub(phone_number_id: str) -> bool:
    return str(phone_number_id or "").strip() in hub_phone_number_ids()


def _normalize_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _normalize_phone(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def extract_code(text: str) -> str:
    """Codigo dentro del mensaje. Acepta el enlace wa.me prellenado ("DEMO ABC123")
    y tambien el codigo suelto, por si el prospecto lo teclea a mano."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    match = _CODE_IN_TEXT_RE.search(raw)
    if match:
        return _normalize_code(match.group(1))
    bare = _normalize_code(raw)
    return bare if len(bare) == CODE_LENGTH else ""


def _row_to_code(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "code": row["code"],
        "cliente_id": row["cliente_id"],
        "label": row["label"] or "",
        "active": bool(row["active"]),
        "expires_at": row["expires_at"] or "",
        "uses": int(row["uses"] or 0),
        "created_at": row["created_at"] or "",
        "wa_link": wa_link(row["code"]),
    }


def wa_link(code: str) -> str:
    """Enlace que se le pasa al prospecto: abre WhatsApp con el texto ya escrito."""
    number = _normalize_phone(getattr(settings, "WHATSAPP_DEMO_PUBLIC_NUMBER", ""))
    if not number:
        return ""
    return f"https://wa.me/{number}?text=DEMO%20{_normalize_code(code)}"


def create_code(
    cliente_id: str,
    *,
    label: str = "",
    days: int = DEFAULT_CODE_DAYS,
    created_by: str = "",
) -> Dict[str, Any]:
    textnorm._assert_valid_client_id(cliente_id)
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))
    expires_at = timeutils._expires_at_in_hours(24 * max(1, int(days or DEFAULT_CODE_DAYS)))
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO wa_demo_codes (code, cliente_id, label, active, expires_at, uses, created_at, created_by)
            VALUES (?, ?, ?, 1, ?, 0, ?, ?)
            """,
            (
                code,
                cliente_id,
                textnorm._sanitize_text(label)[:120],
                expires_at,
                timeutils._utc_now_iso(),
                textnorm._sanitize_text(created_by)[:120],
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM wa_demo_codes WHERE code = ?", (code,)).fetchone()
    return _row_to_code(row)


def list_codes(cliente_id: str = "") -> List[Dict[str, Any]]:
    sql = "SELECT * FROM wa_demo_codes"
    params: tuple = ()
    if cliente_id:
        sql += " WHERE cliente_id = ?"
        params = (cliente_id,)
    sql += " ORDER BY created_at DESC LIMIT 200"
    with db._get_db_connection() as connection:
        rows = connection.execute(sql, params).fetchall()
    return [_row_to_code(r) for r in rows]


def revoke_code(code: str) -> bool:
    """Desactiva el codigo Y corta las conversaciones que entraron con el."""
    code = _normalize_code(code)
    with db._get_db_connection() as connection:
        # `active = 1` en el WHERE: revocar dos veces no debe decir que hizo algo.
        cur = connection.execute(
            "UPDATE wa_demo_codes SET active = 0 WHERE code = ? AND active = 1", (code,)
        )
        connection.execute("DELETE FROM wa_demo_routes WHERE code = ?", (code,))
        connection.commit()
        return cur.rowcount > 0


def _code_row(connection: sqlite3.Connection, code: str) -> Optional[sqlite3.Row]:
    row = connection.execute(
        "SELECT * FROM wa_demo_codes WHERE code = ? AND active = 1", (code,)
    ).fetchone()
    if not row:
        return None
    if row["expires_at"] and row["expires_at"] <= timeutils._utc_now_iso():
        return None
    return row


def route_for_phone(phone: str) -> str:
    """Tenant al que esta atado ese telefono, si la ruta sigue viva."""
    phone = _normalize_phone(phone)
    if not phone:
        return ""
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT cliente_id, expires_at FROM wa_demo_routes WHERE phone = ?", (phone,)
        ).fetchone()
    if not row:
        return ""
    if row["expires_at"] and row["expires_at"] <= timeutils._utc_now_iso():
        return ""
    return row["cliente_id"] or ""


def bind_phone(phone: str, code: str) -> str:
    """Ata el telefono al tenant del codigo. Devuelve el cliente_id o "" si el
    codigo no vale. Reata sin problema: un mismo movil puede ver varias demos."""
    phone = _normalize_phone(phone)
    code = _normalize_code(code)
    if not phone or not code:
        return ""
    with db._get_db_connection() as connection:
        row = _code_row(connection, code)
        if not row:
            return ""
        cliente_id = row["cliente_id"]
        connection.execute(
            """
            INSERT INTO wa_demo_routes (phone, cliente_id, code, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                cliente_id = excluded.cliente_id,
                code = excluded.code,
                expires_at = excluded.expires_at,
                created_at = excluded.created_at
            """,
            (
                phone,
                cliente_id,
                code,
                timeutils._expires_at_in_hours(24 * DEFAULT_ROUTE_DAYS),
                timeutils._utc_now_iso(),
            ),
        )
        connection.execute("UPDATE wa_demo_codes SET uses = uses + 1 WHERE code = ?", (code,))
        connection.commit()
    return cliente_id


HELP_TEXT = (
    "Hola. Este es el numero de demostracion de Vantelia.\n\n"
    "Para hablar con el asistente que te hemos preparado, envia *DEMO* seguido del "
    "codigo que aparece en nuestro correo (por ejemplo: DEMO ABC123).\n\n"
    "Si no tienes codigo, escribenos a info@vantelia.es y te lo damos."
)


def resolve_incoming(phone_number_id: str, from_number: str, incoming_text: str) -> Dict[str, Any]:
    """Decide con que tenant habla este remitente en el numero compartido.

    Devuelve `{"cliente_id", "just_bound", "help_text"}`. Con `cliente_id` vacio
    el webhook responde `help_text` y no molesta a ningun asistente.
    """
    code = extract_code(incoming_text)
    if code:
        cliente_id = bind_phone(from_number, code)
        if cliente_id:
            return {"cliente_id": cliente_id, "just_bound": True, "help_text": ""}
        # Codigo con formato correcto pero invalido/caducado: si ya tenia una demo
        # abierta se sigue en ella; si no, se explica.
        existing = route_for_phone(from_number)
        if existing:
            return {"cliente_id": existing, "just_bound": False, "help_text": ""}
        return {
            "cliente_id": "",
            "just_bound": False,
            "help_text": "Ese codigo no es valido o ha caducado. " + HELP_TEXT,
        }
    existing = route_for_phone(from_number)
    if existing:
        return {"cliente_id": existing, "just_bound": False, "help_text": ""}
    return {"cliente_id": "", "just_bound": False, "help_text": HELP_TEXT}
