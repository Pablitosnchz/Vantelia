"""Reclamaciones de avisos: perder al ejecutor no autoriza repetir una salida."""
from contextlib import closing
from datetime import timedelta, timezone
import json
import uuid

from backend import db, timeutils


# Decision de Pablo (14-sep-2026), «reintentar sin duplicar WhatsApp»: una salida
# dudosa (el proveedor no contesto, o el ejecutor se cayo con el envio a medias)
# nunca se repite por su canal, pero pasado este plazo deja salir el siguiente.
# Antes bloqueaba el aviso para siempre y la clienta se quedaba sin el.
GRACIA_AVISO_DUDOSO_MIN = 30


def _dudoso_vencido(fila):
    cuando = timeutils._from_utc_iso(fila["updated_at"])
    if cuando is None:
        return False  # sin fecha legible se sigue esperando: nunca duplica
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=timezone.utc)
    return timeutils._utc_now() - cuando >= timedelta(minutes=GRACIA_AVISO_DUDOSO_MIN)


def current_notice_booking(cliente_id, booking_id, generation):
    with closing(db._get_db_connection()) as conn:
        return conn.execute(
            "SELECT * FROM bookings WHERE cliente_id=? AND id=? AND reminder_generation=? "
            "AND status NOT IN ('cancelled','completed','no_show')",
            (cliente_id, booking_id, generation)).fetchone()


def notice_claim_still_owned(cliente_id, booking_id, generation, kind, channel, owner_token):
    """Justo antes de enviar: confirma que la reclamación sigue siendo nuestra y la RENUEVA.

    Un ejecutor parado más de la gracia pierde su turno en `claim_notice_delivery`
    (revisión de Codex a 1458540): si al volver no lo comprueba, manda el aviso que otro
    ya entregó por el canal siguiente. Y comprobar sin renovar tampoco basta (segunda
    revisión, 549a1e3): quien vuelve a los 29 min 55 s pasa la comprobación y, con su
    envío aún en camino, otro le retira el turno segundos después. Al renovar
    `updated_at` en el mismo UPDATE, la gracia cuenta desde aquí y el envío (timeout de
    20 s) termina mucho antes de que nadie pueda retirárselo.
    """
    with closing(db._get_db_connection()) as conn, conn:
        return conn.execute(
            "UPDATE booking_notice_deliveries SET updated_at=? "
            "WHERE cliente_id=? AND booking_id=? AND generation=? AND kind=? AND channel=? "
            "AND state='enviando' AND owner_token=? AND EXISTS (SELECT 1 FROM bookings b "
            "WHERE b.cliente_id=booking_notice_deliveries.cliente_id AND b.id=booking_notice_deliveries.booking_id "
            "AND b.reminder_generation=booking_notice_deliveries.generation "
            "AND b.status NOT IN ('cancelled','completed','no_show'))",
            (timeutils._utc_now_iso(), cliente_id, booking_id, generation, kind, channel, owner_token)).rowcount == 1


def notice_has_attempt(cliente_id, booking_id, generation, kind):
    """¿Se empezó ya este aviso por algún canal? Solo así se prorroga su banda."""
    with closing(db._get_db_connection()) as conn:
        return conn.execute(
            "SELECT 1 FROM booking_notice_deliveries WHERE cliente_id=? AND booking_id=? "
            "AND generation=? AND kind=? LIMIT 1",
            (cliente_id, booking_id, generation, kind)).fetchone() is not None


def claim_notice_delivery(cliente_id, booking_id, generation, kind, channel, *, single_delivery=False,
                          atencion_automatica=False):
    identidad = (cliente_id, booking_id, generation, kind)
    with closing(db._get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        vigente = conn.execute(
            "SELECT 1 FROM bookings WHERE cliente_id=? AND id=? AND reminder_generation=? "
            "AND status NOT IN ('cancelled','completed','no_show')", identidad[:3]).fetchone()
        if not vigente:
            return {"estado": "obsoleto"}
        consulta = ("SELECT * FROM booking_notice_deliveries WHERE cliente_id=? AND booking_id=? "
                    "AND generation=? AND kind=?")
        filas = conn.execute(consulta, identidad).fetchall()
        if atencion_automatica and any(fila["state"] == "omitido" and fila["reason"] == "atencion_suprimida"
                                      for fila in filas):
            # Solo es un freno. No concede permiso ni cambia el recorrido manual.
            return {"estado": "omitido", "motivo": "atencion_suprimida"}
        # Un «enviando» pasado de la gracia es un ejecutor perdido: se le retira el
        # turno en esta misma transacción, antes de dejar salir el respaldo, para que
        # si vuelve no pueda enviar ni terminar. La fecha no se toca: la gracia ya corrió.
        caducadas = [fila for fila in filas if fila["state"] == "enviando" and _dudoso_vencido(fila)]
        for fila in caducadas:
            conn.execute(
                "UPDATE booking_notice_deliveries SET state='desconocido',owner_token='',reason='ejecutor_perdido' "
                "WHERE cliente_id=? AND booking_id=? AND generation=? AND kind=? AND channel=? "
                "AND state='enviando' AND owner_token=?",
                identidad + (fila["channel"], fila["owner_token"]))
        if caducadas:
            filas = conn.execute(consulta, identidad).fetchall()
        propia = next((fila for fila in filas if fila["channel"] == channel), None)
        aceptada = next((fila for fila in filas if fila["state"] == "aceptado"
                         and (single_delivery or fila["channel"] == channel)), None)
        if aceptada:
            return {"estado": "aceptado", "canal": aceptada["channel"],
                    "provider_message_id": aceptada["provider_message_id"]}
        if propia and propia["state"] in ("enviando", "desconocido"):
            # Por el mismo canal no se repite nunca; `vencido` solo deja seguir con
            # el siguiente. Un «enviando» viejo es un ejecutor caido: dudoso.
            return {"estado": propia["state"], "canal": channel, "vencido": _dudoso_vencido(propia)}
        # Una salida incierta reciente bloquea tambien el respaldo por otro canal.
        bloqueada = next((fila for fila in filas if fila["state"] in ("enviando", "desconocido")
                          and not _dudoso_vencido(fila)), None)
        if bloqueada:
            return {"estado": bloqueada["state"], "canal": bloqueada["channel"], "vencido": False}
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
