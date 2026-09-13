"""Identidad duradera de una creación; resultado desconocido no autoriza repetir.

Opt-in del núcleo. Los adaptadores deben conservar la misma clave de operación
antes de ejecutar y tratar el estado real de la fila recuperada.
"""
import hashlib
import json
from contextlib import closing

from fastapi import HTTPException

from backend import db, timeutils


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


def recover_creation_operation(cliente_id, operation_key, request_hash):
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
        booking = conn.execute("SELECT * FROM bookings WHERE id=? AND cliente_id=?",
                               (op["booking_id"], cliente_id)).fetchone()
    if booking is None:
        raise HTTPException(status_code=409, detail={"code": "OPERATION_PENDING",
            "message": "El resultado de esa solicitud aún no está verificado. No se repetirá automáticamente."})
    return booking


def claim_creation_operation(cliente_id, operation_key, request_hash, booking_id):
    with closing(db._get_db_connection()) as conn, conn:
        result = conn.execute(
            "INSERT OR IGNORE INTO booking_operations"
            " (cliente_id,operation_key,request_hash,booking_id,created_at) VALUES (?,?,?,?,?)",
            (cliente_id, operation_key, request_hash, booking_id, timeutils._utc_now_iso()))
        creada = result.rowcount == 1
    # Solo el ganador llama al proveedor. Otro proceso recupera el resultado
    # ya persistido o informa de que sigue sin verificarse.
    return None if creada else recover_creation_operation(cliente_id, operation_key, request_hash)
