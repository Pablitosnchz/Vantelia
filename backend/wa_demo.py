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
import hashlib
import json
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend import atencion, atencion_operaciones, db, settings, textnorm, timeutils

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
        row = _demo_route_row(connection, phone)
    return _demo_live_route_cliente(row)


def _demo_route_row(connection, phone):
    return connection.execute("SELECT * FROM wa_demo_routes WHERE phone = ?", (phone,)).fetchone()


def _demo_live_route_cliente(row):
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
        cliente_id = _bind_demo_phone_en_transaccion(connection, phone, row)
        connection.commit()
    return cliente_id


def _bind_demo_phone_en_transaccion(connection, phone, row):
    """SQL único de binding; el llamador controla la transacción."""
    code = row["code"]
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
    return cliente_id


HELP_TEXT = (
    "Hola. Este es el numero de demostracion de Vantelia.\n\n"
    "Para hablar con el asistente que te hemos preparado, envia *DEMO* seguido del "
    "codigo que aparece en nuestro correo (por ejemplo: DEMO ABC123).\n\n"
    "Si no tienes codigo, escribenos a info@vantelia.es y te lo damos."
)


@dataclass(frozen=True)
class DemoIncomingResolution:
    """Lectura consultiva: code_to_bind propone un efecto, no lo acredita."""

    cliente_id: str
    code_to_bind: str = ""
    help_text: str = ""
    phone_number_id: str = ""
    from_number: str = ""
    input_hash: str = ""
    code_snapshot: Optional[tuple] = None
    route_snapshot: Optional[tuple] = None


def _demo_route_resolution(from_number: str, invalid_code: bool) -> DemoIncomingResolution:
    # Un codigo invalido/caducado conserva una demo abierta; no borra rutas.
    existing = route_for_phone(from_number)
    if existing:
        return DemoIncomingResolution(cliente_id=existing)
    prefix = "Ese codigo no es valido o ha caducado. " if invalid_code else ""
    return DemoIncomingResolution(cliente_id="", help_text=prefix + HELP_TEXT)


def resolve_incoming_readonly(
    phone_number_id: str, from_number: str, incoming_text: str
) -> DemoIncomingResolution:
    """Resuelve tenant/codigo sin vincular, consumir usos, reiniciar ni borrar.

    No concede permiso: apply_demo_resolution comprueba ticket y fotos en la
    misma transaccion del efecto. resolve_incoming sigue siendo solo legacy.
    """
    code = extract_code(incoming_text)
    phone = _normalize_phone(from_number)
    hub = str(phone_number_id or "").strip()
    input_hash = hashlib.sha256(_demo_operation_bytes(
        [hub, phone, code or str(incoming_text or "").strip()])).hexdigest()
    with closing(db._get_db_connection()) as connection, connection:
        connection.execute("BEGIN")
        row = _code_row(connection, code) if code and phone else None
        route = _demo_route_row(connection, phone) if phone else None
    metadata = dict(phone_number_id=hub, from_number=phone, input_hash=input_hash,
                    code_snapshot=_demo_code_snapshot(row), route_snapshot=_demo_route_snapshot(route))
    if row:
        return DemoIncomingResolution(cliente_id=row["cliente_id"], code_to_bind=code, **metadata)
    existing = _demo_live_route_cliente(route)
    prefix = "Ese codigo no es valido o ha caducado. " if code else ""
    return DemoIncomingResolution(cliente_id=existing,
                                  help_text="" if existing else prefix + HELP_TEXT, **metadata)


def _demo_operation_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _demo_code_snapshot(row):
    # Otros teléfonos pueden consumir el mismo código: uses no es su identidad.
    return tuple(row[k] for k in ("code", "cliente_id", "active", "expires_at", "created_at")) if row else None


def _demo_route_snapshot(row):
    return tuple(row[k] for k in ("phone", "cliente_id", "code", "expires_at", "created_at")) if row else None


def apply_demo_resolution(resolution, *, cliente_id, ticket_id, evento_id):
    """Aplica solo binding SQLite. No autoriza reset, respuesta ni otro efecto.

    cliente_id procede del contexto autenticado, no de una resolución mutable.
    Conocido + mismo evento conserva evidencia aun tras pausa/caducidad; nunca
    devuelve un permiso ni reaplica el binding. El caller sigue sin conectar WA.
    """
    if (not isinstance(resolution, DemoIncomingResolution)
            or not resolution.phone_number_id or not resolution.from_number
            or not re.fullmatch(r"[a-f0-9]{64}", resolution.input_hash)):
        raise ValueError("La resolución demo no contiene una entrada verificable.")
    # Nada identificativo de la entrada se persiste: solo hashes en el diario.
    event_key = hashlib.sha256(_demo_operation_bytes([resolution.phone_number_id, evento_id])).hexdigest()
    request = _demo_operation_bytes([resolution.phone_number_id, evento_id, resolution.input_hash])
    payload = _demo_operation_bytes([resolution.cliente_id, resolution.code_to_bind,
                                     resolution.code_snapshot, resolution.route_snapshot])
    try:
        with closing(db._get_db_connection()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            atencion_operaciones._buscar_ticket_atencion(
                connection, cliente_id, ticket_id, evento_id=evento_id)
            known = atencion_operaciones.consultar_intento_operacion_atencion_en_transaccion(
                connection, cliente_id, ticket_id, "vincular", event_key, tipo="wa_demo")
            if known is not None:
                if known["request_hash"] != hashlib.sha256(request).hexdigest():
                    raise atencion_operaciones.AtencionIdentidadEnConflicto("La entrada del evento no coincide.")
                return {"cliente_id": cliente_id, "estado": known["estado"],
                        "binding_aplicado_ahora": False, "repetido": True}
            if not resolution.code_to_bind:
                ticket = atencion_operaciones.comprobar_ticket_atencion_en_transaccion(
                    connection, cliente_id, ticket_id)
                route = _demo_route_row(connection, resolution.from_number)
                matches = (resolution.cliente_id == cliente_id
                           and _demo_route_snapshot(route) == resolution.route_snapshot
                           and _demo_live_route_cliente(route) == cliente_id)
                return {"cliente_id": cliente_id,
                        "estado": "suprimido" if not ticket["puede_preparar"] else (
                            "ruta_vigente" if matches else "rechazado"),
                        "binding_aplicado_ahora": False, "repetido": False}
            operation = atencion_operaciones.admitir_operacion_atencion_en_transaccion(
                connection, cliente_id, ticket_id, tipo="wa_demo", canal="vincular",
                clave_intento=event_key, payload=payload, solicitud=request)
            if not operation["ejecutar_operacion"]:
                return {"cliente_id": cliente_id, "estado": operation["estado"],
                        "binding_aplicado_ahora": False, "repetido": False}
            row = _code_row(connection, resolution.code_to_bind)
            route = _demo_route_row(connection, resolution.from_number)
            matches = (resolution.cliente_id == cliente_id and row is not None
                       and row["cliente_id"] == cliente_id
                       and _demo_code_snapshot(row) == resolution.code_snapshot
                       and _demo_route_snapshot(route) == resolution.route_snapshot)
            if matches:
                _bind_demo_phone_en_transaccion(connection, resolution.from_number, row)
            atencion_operaciones.registrar_resultado_operacion_atencion_en_transaccion(
                connection, cliente_id, ticket_id, tipo="wa_demo", canal="vincular",
                clave_intento=event_key, owner_token=operation["owner_token"],
                resultado="aceptado" if matches else "rechazado")
            return {"cliente_id": cliente_id, "estado": "aceptado" if matches else "rechazado",
                    "binding_aplicado_ahora": matches, "repetido": False}
    except sqlite3.Error as exc:
        raise atencion.AtencionNoDisponible("No se puede aplicar la resolución demo.") from exc


def resolve_incoming(phone_number_id: str, from_number: str, incoming_text: str) -> Dict[str, Any]:
    """Entrada legacy con efectos: devuelve cliente_id, just_bound y help_text."""
    resolution = resolve_incoming_readonly(phone_number_id, from_number, incoming_text)
    if resolution.code_to_bind:
        cliente_id = bind_phone(from_number, resolution.code_to_bind)
        if cliente_id:
            return {"cliente_id": cliente_id, "just_bound": True, "help_text": ""}
        # El codigo pudo caducar/revocarse tras la consulta. El wrapper legacy
        # conserva su fallback con la ruta vigente, sin volver a interpretar texto.
        resolution = _demo_route_resolution(from_number, invalid_code=True)
    return {
        "cliente_id": resolution.cliente_id,
        "just_bound": False,
        "help_text": resolution.help_text,
    }
