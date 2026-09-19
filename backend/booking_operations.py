"""Identidad duradera de una creación; resultado desconocido no autoriza repetir.

Opt-in del núcleo. Los adaptadores deben conservar la misma clave de operación
antes de ejecutar y tratar el estado real de la fila recuperada.
"""
import hashlib
import json
import os
from contextlib import closing
from datetime import timedelta

from fastapi import HTTPException

from backend import atencion_contexto, clients, db, settings, timeutils


_PENDING_CREATION_TIMEOUT = timedelta(minutes=15)


def _booking_has_webhook(cliente_id):
    """Un resultado externo no se libera: puede llegar tarde al webhook."""
    booking_cfg = (clients._get_client_config(cliente_id).get("booking") or {})
    if str(booking_cfg.get("webhook_url") or "").strip():
        return True
    webhook_env = str(booking_cfg.get("webhook_env") or "").strip()
    return bool((webhook_env and os.getenv(webhook_env, "").strip())
                or str(settings.WEBHOOK_DEFAULT or "").strip())


def _pending_creation_is_expired(created_at):
    created = timeutils._from_utc_iso(created_at)
    if created is None:
        return False
    return timeutils._utc_now() - created >= _PENDING_CREATION_TIMEOUT


def creation_request_fingerprint(datos):
    return hashlib.sha256(json.dumps(datos, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def booking_creation_fingerprint(*, employee_row, nombre, email, telefono, servicio,
                                 booking_date, booking_time, notas, source, fuera_de_horario=False,
                                 expected_terms=None):
    """El núcleo y el canal identifican exactamente la misma solicitud ejecutable."""
    datos = {
        "employee_id": employee_row["id"], "nombre": nombre, "email": email,
        "telefono": telefono, "servicio": servicio, "fecha": booking_date,
        "hora": booking_time, "notas": notas, "source": source,
        "fuera_de_horario": fuera_de_horario,
    }
    if expected_terms is not None:
        datos["terms"] = expected_terms
    return creation_request_fingerprint(datos)


def read_completed_creation_operation(cliente_id, operation_key, request_hash):
    """Solo resultado conocido: no reclama ni libera operaciones pendientes."""
    if not isinstance(operation_key, str) or not operation_key.strip() or len(operation_key) > 128:
        raise HTTPException(status_code=422, detail="Identidad de operación no válida")
    with closing(db._get_db_connection()) as conn:
        op = conn.execute(
            "SELECT request_hash,booking_id FROM booking_operations WHERE cliente_id=? AND operation_key=?",
            (cliente_id, operation_key)).fetchone()
        if op is None:
            return None
        if op["request_hash"] != request_hash:
            raise HTTPException(status_code=409, detail={"code": "OPERATION_KEY_REUSED",
                "message": "La solicitud ha cambiado; necesita una nueva confirmación."})
        return conn.execute("SELECT * FROM bookings WHERE id=? AND cliente_id=?",
                            (op["booking_id"], cliente_id)).fetchone()


def recover_creation_operation(cliente_id, operation_key, request_hash):
    if not isinstance(operation_key, str) or not operation_key.strip() or len(operation_key) > 128:
        raise HTTPException(status_code=422, detail="Identidad de operación no válida")
    with closing(db._get_db_connection()) as conn, conn:
        op = conn.execute(
            "SELECT request_hash,booking_id,created_at FROM booking_operations WHERE cliente_id=? AND operation_key=?",
            (cliente_id, operation_key)).fetchone()
        if op is None:
            return None
        if op["request_hash"] != request_hash:
            raise HTTPException(status_code=409, detail={"code": "OPERATION_KEY_REUSED",
                "message": "La solicitud ha cambiado; necesita una nueva confirmación."})
        booking = conn.execute("SELECT * FROM bookings WHERE id=? AND cliente_id=?",
                               (op["booking_id"], cliente_id)).fetchone()
    if booking is None:
        atencion_contexto.verificar_turno_atencion(cliente_id)
        # No hubo proveedor externo ni webhook que pueda terminar la operación
        # tarde. Tras el margen, conservar esta llave para siempre solo atrapa a
        # la clienta en un 409. La borramos de forma condicionada y dejamos un
        # rastro sin teléfono, nombre ni datos de la cita.
        if _pending_creation_is_expired(op["created_at"]) and not _booking_has_webhook(cliente_id):
            atencion_contexto.exigir_mutacion_atencion(cliente_id)
            with closing(db._get_db_connection()) as conn, conn:
                liberada = conn.execute(
                    "DELETE FROM booking_operations WHERE cliente_id=? AND operation_key=? "
                    "AND request_hash=? AND booking_id=? AND created_at=?",
                    (cliente_id, operation_key, request_hash, op["booking_id"], op["created_at"]),
                ).rowcount == 1
                if liberada:
                    conn.execute(
                        "INSERT INTO booking_operation_audit "
                        "(cliente_id,operation_key,event_type,created_at) VALUES (?,?,?,?)",
                        (cliente_id, operation_key, "creation_pending_released", timeutils._utc_now_iso()),
                    )
            if liberada:
                atencion_contexto.registrar_mutacion_rechazada(cliente_id)
                raise HTTPException(status_code=409, detail={"code": "OPERATION_RELEASED",
                    "message": "La solicitud anterior no llegó a registrarse; necesita una nueva confirmación."})
        raise HTTPException(status_code=409, detail={"code": "OPERATION_PENDING",
            "message": "El resultado de esa solicitud aún no está verificado. No se repetirá automáticamente."})
    return booking


def claim_creation_operation(cliente_id, operation_key, request_hash, booking_id):
    atencion_contexto.exigir_mutacion_atencion(cliente_id)
    with closing(db._get_db_connection()) as conn, conn:
        result = conn.execute(
            "INSERT OR IGNORE INTO booking_operations"
            " (cliente_id,operation_key,request_hash,booking_id,created_at) VALUES (?,?,?,?,?)",
            (cliente_id, operation_key, request_hash, booking_id, timeutils._utc_now_iso()))
        creada = result.rowcount == 1
    # Solo el ganador llama al proveedor. Otro proceso recupera el resultado
    # ya persistido o informa de que sigue sin verificarse.
    return None if creada else recover_creation_operation(cliente_id, operation_key, request_hash)
