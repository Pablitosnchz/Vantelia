"""Reclamaciones de avisos: perder al ejecutor no autoriza repetir una salida."""
from contextlib import closing
import json
import uuid

from backend import db, timeutils


def current_notice_booking(cliente_id, booking_id, generation):
    with closing(db._get_db_connection()) as conn:
        return conn.execute(
            "SELECT * FROM bookings WHERE cliente_id=? AND id=? AND reminder_generation=? "
            "AND status NOT IN ('cancelled','completed','no_show')",
            (cliente_id, booking_id, generation)).fetchone()


def claim_notice_delivery(cliente_id, booking_id, generation, kind, channel, *, single_delivery=False):
    identidad = (cliente_id, booking_id, generation, kind)
    with closing(db._get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        vigente = conn.execute(
            "SELECT 1 FROM bookings WHERE cliente_id=? AND id=? AND reminder_generation=? "
            "AND status NOT IN ('cancelled','completed','no_show')", identidad[:3]).fetchone()
        if not vigente:
            return {"estado": "obsoleto"}
        filas = conn.execute(
            "SELECT * FROM booking_notice_deliveries WHERE cliente_id=? AND booking_id=? "
            "AND generation=? AND kind=?", identidad).fetchall()
        propia = next((fila for fila in filas if fila["channel"] == channel), None)
        aceptada = next((fila for fila in filas if fila["state"] == "aceptado"
                         and (single_delivery or fila["channel"] == channel)), None)
        if aceptada:
            return {"estado": "aceptado", "canal": aceptada["channel"],
                    "provider_message_id": aceptada["provider_message_id"]}
        # Una salida incierta bloquea tambien el respaldo por otro canal.
        bloqueada = next((fila for fila in filas if fila["state"] in ("enviando", "desconocido")), None)
        if bloqueada:
            return {"estado": bloqueada["state"], "canal": bloqueada["channel"]}
        if propia and propia["state"] == "omitido":
            return {"estado": "omitido", "motivo": propia["reason"]}
        token = uuid.uuid4().hex
        if propia:
            conn.execute(
                "UPDATE booking_notice_deliveries SET state='enviando',owner_token=?,updated_at=? "
                "WHERE cliente_id=? AND booking_id=? AND generation=? AND kind=? AND channel=?",
                (token, timeutils._utc_now_iso()) + identidad + (channel,))
        else:
            conn.execute(
                "INSERT INTO booking_notice_deliveries "
                "(cliente_id,booking_id,generation,kind,channel,state,owner_token,updated_at) "
                "VALUES (?,?,?,?,?,'enviando',?,?)",
                identidad + (channel, token, timeutils._utc_now_iso()))
    return {"estado": "reclamado", "owner_token": token}


def finish_notice_delivery(cliente_id, booking_id, generation, kind, channel, owner_token,
                           state, *, provider_message_id="", provider_message_ids=(), reason="",
                           template_name=""):
    if state not in ("aceptado", "rechazado", "desconocido", "omitido"):
        raise ValueError("Resultado de aviso no valido")
    with closing(db._get_db_connection()) as conn, conn:
        terminado = conn.execute(
            "UPDATE booking_notice_deliveries SET state=?,provider_message_id=?,provider_message_ids_json=?,reason=?,updated_at=? "
            "WHERE cliente_id=? AND booking_id=? AND generation=? AND kind=? AND channel=? "
            "AND owner_token=? AND state='enviando'",
            (state, provider_message_id, json.dumps(list(provider_message_ids)), reason, timeutils._utc_now_iso(), cliente_id,
             booking_id, generation, kind, channel, owner_token)).rowcount == 1
        if terminado and state == "aceptado" and channel == "whatsapp" and template_name:
            # El tope diario lee este evento: no puede perderse tras aceptar Meta.
            # El CAS y la misma transaccion impiden omitirlo o contarlo dos veces.
            conn.execute(
                "INSERT INTO booking_audit (booking_id,cliente_id,event_type,payload_json,created_at) "
                "VALUES (?,?,'reminder_whatsapp_template_sent',?,?)",
                (booking_id, cliente_id,
                 json.dumps({"kind": kind, "template": template_name, "generation": generation},
                            ensure_ascii=False), timeutils._utc_now_iso()))
        return terminado


def mark_notice_complete(cliente_id, booking_id, generation, sent_column, status, error=""):
    if sent_column not in ("confirmation_email_sent_at", "reminder_24h_sent_at", "reminder_2h_sent_at"):
        raise ValueError("Marca de aviso no valida")
    with closing(db._get_db_connection()) as conn, conn:
        return conn.execute(
            "UPDATE bookings SET " + sent_column + "=?,customer_email_status=?,customer_email_last_error=? "
            "WHERE cliente_id=? AND id=? AND reminder_generation=? "
            "AND status NOT IN ('cancelled','completed','no_show')",
            (timeutils._utc_now_iso(), status, error, cliente_id, booking_id, generation)).rowcount == 1
