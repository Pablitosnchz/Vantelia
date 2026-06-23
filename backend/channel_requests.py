"""Solicitudes asistidas de provision de canales por cliente."""
from __future__ import annotations

import sqlite3
import uuid
from html import escape
from typing import Any, Dict, List

from backend import db, emailing, security, settings, textnorm, timeutils


REQUEST_CHANNELS = {"sms", "voice"}
REQUEST_TYPES = {
    "managed_number",
    "alphanumeric_sender",
    "dedicated_number",
    "twilio_own_account",
    "voice_install",
}
REQUEST_STATUSES = {"pending", "in_progress", "active", "rejected", "cancelled"}


def _request_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "cliente_id": row["cliente_id"],
        "channel": row["channel"],
        "request_type": row["request_type"],
        "requested_sender": row["requested_sender"] or "",
        "requested_phone": row["requested_phone"] or "",
        "contact_name": row["contact_name"] or "",
        "contact_email": row["contact_email"] or "",
        "notes": row["notes"] or "",
        "status": row["status"] or "pending",
        "admin_notes": row["admin_notes"] or "",
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
    }


def _notify_new_request(item: Dict[str, Any]) -> None:
    recipient = settings.CONSULTA_NOTIFICATION_EMAIL
    if not recipient or not emailing._email_delivery_configured():
        return
    channel_label = "SMS" if item["channel"] == "sms" else "Voz"
    subject = f"Nueva solicitud de canal {channel_label}: {item['cliente_id']}"
    lines = [
        "Nueva solicitud de canal en Vantelia.",
        "",
        f"Cliente ID: {item['cliente_id']}",
        f"Canal: {channel_label}",
        f"Tipo: {item['request_type']}",
        f"Remitente solicitado: {item['requested_sender'] or '-'}",
        f"Numero solicitado: {item['requested_phone'] or '-'}",
        f"Contacto: {item['contact_name'] or '-'} <{item['contact_email'] or '-'}>",
        "",
        item["notes"] or "Sin notas.",
    ]
    html = (
        "<h2>Nueva solicitud de canal</h2>"
        "<table>"
        f"<tr><td>Cliente</td><td><strong>{escape(item['cliente_id'])}</strong></td></tr>"
        f"<tr><td>Canal</td><td>{escape(channel_label)}</td></tr>"
        f"<tr><td>Tipo</td><td>{escape(item['request_type'])}</td></tr>"
        f"<tr><td>Remitente</td><td>{escape(item['requested_sender'] or '-')}</td></tr>"
        f"<tr><td>Numero</td><td>{escape(item['requested_phone'] or '-')}</td></tr>"
        f"<tr><td>Contacto</td><td>{escape(item['contact_name'] or '-')} "
        f"&lt;{escape(item['contact_email'] or '-')}&gt;</td></tr>"
        "</table>"
        f"<p>{escape(item['notes'] or 'Sin notas.')}</p>"
    )
    try:
        emailing._send_email_message(recipient, subject, "\n".join(lines), html)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudo notificar solicitud de canal %s: %s", item["id"], exc)


def create_request(
    *,
    cliente_id: str,
    channel: str,
    request_type: str,
    requested_sender: str = "",
    requested_phone: str = "",
    contact_name: str = "",
    contact_email: str = "",
    notes: str = "",
    notify: bool = True,
) -> Dict[str, Any]:
    channel = textnorm._sanitize_text(channel).lower()
    request_type = textnorm._sanitize_text(request_type).lower()
    if channel not in REQUEST_CHANNELS:
        raise ValueError("Canal no valido.")
    if request_type not in REQUEST_TYPES:
        raise ValueError("Tipo de solicitud no valido.")
    now = timeutils._utc_now_iso()
    request_id = "cr_" + uuid.uuid4().hex
    values = {
        "id": request_id,
        "cliente_id": cliente_id,
        "channel": channel,
        "request_type": request_type,
        "requested_sender": textnorm._sanitize_text(requested_sender)[:32],
        "requested_phone": textnorm._sanitize_text(requested_phone)[:40],
        "contact_name": textnorm._sanitize_text(contact_name)[:120],
        "contact_email": textnorm._normalize_email(contact_email)[:200],
        "notes": textnorm._sanitize_text(notes, allow_multiline=True)[:1000],
        "status": "pending",
        "admin_notes": "",
        "created_at": now,
        "updated_at": now,
    }
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_channel_requests
                (id, cliente_id, channel, request_type, requested_sender, requested_phone,
                 contact_name, contact_email, notes, status, admin_notes, created_at, updated_at)
            VALUES (:id, :cliente_id, :channel, :request_type, :requested_sender, :requested_phone,
                    :contact_name, :contact_email, :notes, :status, :admin_notes, :created_at, :updated_at)
            """,
            values,
        )
        connection.commit()
    security._channel_audit(cliente_id, channel, "request_created", request_type, True, values["status"])
    if notify:
        _notify_new_request(values)
    return values


def list_requests(*, status: str = "", cliente_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if cliente_id:
        clauses.append("cliente_id = ?")
        params.append(cliente_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with db._get_db_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM client_channel_requests
            {where}
            ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,
                     created_at DESC
            LIMIT ?
            """,
            (*params, max(1, min(int(limit or 100), 250))),
        ).fetchall()
    return [_request_dict(row) for row in rows]


def update_request_status(request_id: str, *, status: str, admin_notes: str = "") -> Dict[str, Any]:
    status = textnorm._sanitize_text(status).lower()
    if status not in REQUEST_STATUSES:
        raise ValueError("Estado de solicitud no valido.")
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        row = connection.execute("SELECT * FROM client_channel_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise KeyError(request_id)
        notes = textnorm._sanitize_text(admin_notes, allow_multiline=True)[:1000]
        connection.execute(
            """
            UPDATE client_channel_requests
            SET status=?, admin_notes=?, updated_at=?
            WHERE id=?
            """,
            (status, notes, now, request_id),
        )
        connection.commit()
        updated = connection.execute("SELECT * FROM client_channel_requests WHERE id=?", (request_id,)).fetchone()
    security._channel_audit(updated["cliente_id"], updated["channel"], "request_updated", updated["request_type"], True, status)
    return _request_dict(updated)
