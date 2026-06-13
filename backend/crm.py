"""CRM ligero multi-tenant (refactor F3).

Contactos unificados por cliente con normalizacion de email/telefono,
prioridad de estados y auditoria. Detalle en docs/CRM_Y_PAGOS_MVP.md.
"""
from __future__ import annotations

import copy
import json
import re
import secrets
import sqlite3
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException

from api_models import AppLeadPublic, CRMContactActivity, CRMContactListItem, CRMContactPublic
from backend import appstate, clients, db, settings, textnorm, timeutils

CRM_BACKFILLED_CLIENTS: Set[str] = set()

def _normalize_phone_for_match(value: str) -> str:
    """Deja solo digitos y se queda con los ultimos 9 (numero nacional ES)."""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-9:] if len(digits) >= 9 else digits


CRM_CONTACT_STATUSES = {"nuevo", "interesado", "cita_pendiente", "confirmado", "cliente", "perdido"}


CRM_STATUS_PRIORITY = {
    "nuevo": 0,
    "interesado": 1,
    "cita_pendiente": 2,
    "confirmado": 3,
    "cliente": 4,
    "perdido": -1,
}


def _normalize_crm_email(value: str) -> str:
    return textnorm._sanitize_text(value).strip().lower()


def _normalize_crm_phone(value: str) -> str:
    raw = textnorm._sanitize_text(value).strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return "+" + digits
    if len(digits) == 9:
        return "+34" + digits
    return "+" + digits


def _normalize_crm_search(value: str) -> str:
    text = unicodedata.normalize("NFKD", textnorm._sanitize_text(value, allow_multiline=True)).casefold()
    normalized = " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).split())
    digits = re.sub(r"\D", "", normalized)
    if len(digits) >= 6 and not re.search(r"[a-z]", normalized):
        return digits
    return normalized


def _crm_search_text(*values: str) -> str:
    combined = " ".join(value or "" for value in values)
    normalized = _normalize_crm_search(combined)
    digits = re.sub(r"\D", "", combined)
    return f"{normalized} {digits}".strip() if len(digits) >= 6 else normalized


def _crm_audit(
    connection: sqlite3.Connection,
    cliente_id: str,
    contact_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    actor: str = "system",
) -> None:
    connection.execute(
        """
        INSERT INTO crm_contact_audit (cliente_id, contact_id, event_type, actor, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (cliente_id, contact_id, event_type, actor, json.dumps(payload or {}, ensure_ascii=False), timeutils._utc_now_iso()),
    )


def _crm_link(
    connection: sqlite3.Connection,
    cliente_id: str,
    contact_id: str,
    entity_type: str,
    entity_id: str,
    source: str,
) -> None:
    if not entity_id:
        return
    connection.execute(
        """
        INSERT INTO crm_contact_links (cliente_id, contact_id, entity_type, entity_id, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(cliente_id, entity_type, entity_id) DO UPDATE SET
            contact_id=excluded.contact_id, source=excluded.source
        """,
        (cliente_id, contact_id, entity_type, entity_id, source, timeutils._utc_now_iso()),
    )


def _crm_upsert_contact(
    cliente_id: str,
    *,
    name: str = "",
    email: str = "",
    phone: str = "",
    source: str = "",
    status: str = "",
    entity_type: str = "",
    entity_id: str = "",
    actor: str = "system",
) -> str:
    name = textnorm._sanitize_text(name)[:200]
    email = textnorm._sanitize_text(email)[:200]
    phone = textnorm._sanitize_text(phone)[:80]
    source = textnorm._sanitize_text(source)[:40] or "unknown"
    email_norm = _normalize_crm_email(email)
    phone_norm = _normalize_crm_phone(phone)
    if not (name or email_norm or phone_norm):
        return ""
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        row = None
        if email_norm:
            row = connection.execute(
                "SELECT * FROM crm_contacts WHERE cliente_id = ? AND email_normalized = ? LIMIT 1",
                (cliente_id, email_norm),
            ).fetchone()
        if not row and phone_norm:
            row = connection.execute(
                "SELECT * FROM crm_contacts WHERE cliente_id = ? AND phone_normalized = ? LIMIT 1",
                (cliente_id, phone_norm),
            ).fetchone()
        if row:
            contact_id = row["id"]
            next_status = row["status"] or "nuevo"
            if status in CRM_CONTACT_STATUSES and next_status != "perdido":
                if CRM_STATUS_PRIORITY.get(status, 0) > CRM_STATUS_PRIORITY.get(next_status, 0):
                    next_status = status
            updates = {
                "name": name or row["name"],
                "email": email or row["email"],
                "email_normalized": email_norm or row["email_normalized"],
                "phone": phone or row["phone"],
                "phone_normalized": phone_norm or row["phone_normalized"],
                "search_text": _crm_search_text(
                    name or row["name"], email or row["email"], phone or row["phone"],
                ),
                "status": next_status,
                "source_last": source,
                "last_seen_at": now_iso,
                "updated_at": now_iso,
            }
            # Do not steal an identifier that already belongs to another contact.
            for key, normalized_key in (("email", "email_normalized"), ("phone", "phone_normalized")):
                normalized = updates[normalized_key]
                if normalized:
                    collision = connection.execute(
                        f"SELECT id FROM crm_contacts WHERE cliente_id = ? AND {normalized_key} = ? AND id <> ? LIMIT 1",
                        (cliente_id, normalized, contact_id),
                    ).fetchone()
                    if collision:
                        updates[key] = row[key]
                        updates[normalized_key] = row[normalized_key]
            connection.execute(
                """
                UPDATE crm_contacts SET
                    name=?, email=?, email_normalized=?, phone=?, phone_normalized=?, search_text=?, status=?,
                    source_last=?, last_seen_at=?, updated_at=?
                WHERE id=? AND cliente_id=?
                """,
                (*updates.values(), contact_id, cliente_id),
            )
            event_type = "contact_seen"
        else:
            contact_id = "ct_" + secrets.token_hex(10)
            next_status = status if status in CRM_CONTACT_STATUSES else "nuevo"
            connection.execute(
                """
                INSERT INTO crm_contacts (
                    id, cliente_id, name, email, email_normalized, phone, phone_normalized, search_text, status,
                    notes, tags_json, owner, next_action, next_action_at, source_first, source_last,
                    first_seen_at, last_seen_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', '[]', '', '', '', ?, ?, ?, ?, ?, ?)
                """,
                (
                    contact_id, cliente_id, name, email, email_norm, phone, phone_norm,
                    _crm_search_text(name, email, phone), next_status,
                    source, source, now_iso, now_iso, now_iso, now_iso,
                ),
            )
            event_type = "contact_created"
        _crm_link(connection, cliente_id, contact_id, entity_type, entity_id, source)
        _crm_audit(
            connection, cliente_id, contact_id, event_type,
            {"source": source, "entity_type": entity_type, "entity_id": entity_id},
            actor=actor,
        )
        connection.commit()
    return contact_id




def _crm_json_list(raw: str) -> List[str]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in value if str(item).strip()] if isinstance(value, list) else []


def _crm_contact_public(row: sqlite3.Row, connection: Optional[sqlite3.Connection] = None) -> CRMContactPublic:
    counts = {"lead": 0, "booking": 0, "chat": 0, "voice": 0}
    owns_connection = connection is None
    if owns_connection:
        connection = db._get_db_connection()
    try:
        for item in connection.execute(
            """
            SELECT entity_type, COUNT(*) AS total
            FROM crm_contact_links
            WHERE cliente_id = ? AND contact_id = ?
            GROUP BY entity_type
            """,
            (row["cliente_id"], row["id"]),
        ).fetchall():
            counts[item["entity_type"]] = int(item["total"] or 0)
    finally:
        if owns_connection:
            connection.close()
    return CRMContactPublic(
        id=row["id"],
        cliente_id=row["cliente_id"],
        name=row["name"] or "",
        email=row["email"] or "",
        phone=row["phone"] or "",
        status=row["status"] or "nuevo",
        notes=row["notes"] or "",
        tags=_crm_json_list(row["tags_json"]),
        owner=row["owner"] or "",
        next_action=row["next_action"] or "",
        next_action_at=row["next_action_at"] or "",
        source_first=row["source_first"] or "",
        source_last=row["source_last"] or "",
        first_seen_at=row["first_seen_at"] or "",
        last_seen_at=row["last_seen_at"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
        leads_count=counts["lead"],
        bookings_count=counts["booking"],
        chats_count=counts["chat"],
        voice_calls_count=counts["voice"],
    )


def _crm_contact_list_item(row: sqlite3.Row) -> CRMContactListItem:
    return CRMContactListItem(
        id=row["id"],
        name=row["name"] or "",
        email=row["email"] or "",
        phone=row["phone"] or "",
        status=row["status"] or "nuevo",
        tags=_crm_json_list(row["tags_json"]),
        owner=row["owner"] or "",
        next_action=row["next_action"] or "",
        next_action_at=row["next_action_at"] or "",
        source_first=row["source_first"] or "",
        source_last=row["source_last"] or "",
        last_seen_at=row["last_seen_at"] or "",
        created_at=row["created_at"] or "",
        leads_count=int(row["leads_count"] or 0),
        bookings_count=int(row["bookings_count"] or 0),
        chats_count=int(row["chats_count"] or 0),
        voice_calls_count=int(row["voice_calls_count"] or 0),
    )


def _crm_contact_or_404(connection: sqlite3.Connection, cliente_id: str, contact_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM crm_contacts WHERE id = ? AND cliente_id = ? LIMIT 1",
        (contact_id, cliente_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Contacto no encontrado.")
    return row


def _crm_contact_activity(connection: sqlite3.Connection, cliente_id: str, contact_id: str) -> List[CRMContactActivity]:
    links = connection.execute(
        """
        SELECT entity_type, entity_id, source, created_at
        FROM crm_contact_links WHERE cliente_id = ? AND contact_id = ?
        ORDER BY created_at DESC LIMIT 200
        """,
        (cliente_id, contact_id),
    ).fetchall()
    activity: List[CRMContactActivity] = []
    for link in links:
        kind, entity_id = link["entity_type"], link["entity_id"]
        title, detail, item_status, occurred_at = kind, "", "", link["created_at"]
        if kind == "booking":
            row = connection.execute("SELECT * FROM bookings WHERE id = ? AND cliente_id = ?", (entity_id, cliente_id)).fetchone()
            if row:
                title = f"Cita: {row['servicio'] or 'Consulta'}"
                detail = f"{row['booking_date']} {row['booking_time']}".strip()
                item_status, occurred_at = row["status"], row["created_at"]
        elif kind == "lead":
            row = connection.execute("SELECT * FROM bot_leads WHERE id = ? AND cliente_id = ?", (entity_id, cliente_id)).fetchone()
            if row:
                title, detail, occurred_at = "Lead captado", row["message"] or "", row["created_at"]
        elif kind == "chat":
            row = connection.execute("SELECT * FROM chat_sessions WHERE id = ? AND cliente_id = ?", (entity_id, cliente_id)).fetchone()
            if row:
                title, detail, occurred_at = "Conversacion", row["origin"] or "", row["last_message_at"]
        elif kind == "voice":
            row = connection.execute("SELECT * FROM voice_calls WHERE call_sid = ? AND cliente_id = ?", (entity_id, cliente_id)).fetchone()
            if row:
                title, detail, item_status, occurred_at = "Llamada", row["summary"] or "", row["status"], row["started_at"]
        activity.append(CRMContactActivity(
            kind=kind, reference_id=entity_id, title=title, detail=detail,
            status=item_status, occurred_at=occurred_at or "", source=link["source"] or "",
        ))
    activity.sort(key=lambda item: item.occurred_at, reverse=True)
    payment_rows = connection.execute(
        "SELECT * FROM customer_payments WHERE cliente_id=? AND contact_id=? ORDER BY created_at DESC LIMIT 100",
        (cliente_id, contact_id),
    ).fetchall()
    for row in payment_rows:
        activity.append(CRMContactActivity(
            kind="payment", reference_id=row["id"], title=f"Pago: {row['service_name'] or 'Servicio'}",
            detail=textnorm._format_price_cents(int(row["amount_cents"] or 0)), status=row["status"],
            occurred_at=row["paid_at"] or row["created_at"], source="stripe_connect",
        ))
    activity.sort(key=lambda item: item.occurred_at, reverse=True)
    return activity


def _crm_backfill_client(cliente_id: str) -> None:
    """Enlaza datos historicos de forma idempotente al abrir el CRM."""
    with appstate.state_lock:
        if cliente_id in CRM_BACKFILLED_CLIENTS:
            return
    with db._get_db_connection() as connection:
        bookings = connection.execute(
            """
            SELECT b.* FROM bookings b
            LEFT JOIN crm_contact_links l
              ON l.cliente_id=b.cliente_id AND l.entity_type='booking' AND l.entity_id=b.id
            WHERE b.cliente_id=? AND l.id IS NULL
            """,
            (cliente_id,),
        ).fetchall()
        leads = connection.execute(
            """
            SELECT b.* FROM bot_leads b
            LEFT JOIN crm_contact_links l
              ON l.cliente_id=b.cliente_id AND l.entity_type='lead' AND l.entity_id=b.id
            WHERE b.cliente_id=? AND l.id IS NULL
            """,
            (cliente_id,),
        ).fetchall()
        calls = connection.execute(
            """
            SELECT v.* FROM voice_calls v
            LEFT JOIN crm_contact_links l
              ON l.cliente_id=v.cliente_id AND l.entity_type='voice' AND l.entity_id=v.call_sid
            WHERE v.cliente_id=? AND l.id IS NULL AND v.from_number <> ''
            """,
            (cliente_id,),
        ).fetchall()
        whatsapp = connection.execute(
            "SELECT DISTINCT from_number FROM whatsapp_inbound_messages WHERE cliente_id=? AND from_number <> ''",
            (cliente_id,),
        ).fetchall()
        linked_whatsapp_ids = {
            row["entity_id"]
            for row in connection.execute(
                "SELECT entity_id FROM crm_contact_links WHERE cliente_id=? AND entity_type='chat' AND entity_id LIKE 'wa_%'",
                (cliente_id,),
            ).fetchall()
        }
        search_rows = connection.execute(
            "SELECT id, name, email, phone FROM crm_contacts WHERE cliente_id=? AND search_text=''",
            (cliente_id,),
        ).fetchall()
        for row in search_rows:
            connection.execute(
                "UPDATE crm_contacts SET search_text=? WHERE id=? AND cliente_id=?",
                (_crm_search_text(row["name"], row["email"], row["phone"]), row["id"], cliente_id),
            )
        connection.commit()
    for row in bookings:
        _crm_upsert_contact(
            cliente_id, name=row["nombre"], email=row["email"], phone=row["telefono"] or "",
            source=row["source"] or "booking",
            status="confirmado" if row["status"] == "confirmed" else "cita_pendiente",
            entity_type="booking", entity_id=row["id"],
        )
    for row in leads:
        contact_id = _crm_upsert_contact(
            cliente_id, name=row["name"], email=row["email"], phone=row["phone"],
            source=row["source"] or "lead", status="interesado", entity_type="lead", entity_id=row["id"],
        )
        if contact_id and row["session_id"]:
            with db._get_db_connection() as connection:
                _crm_link(connection, cliente_id, contact_id, "chat", row["session_id"], row["source"] or "chat")
                connection.commit()
    for row in calls:
        _crm_upsert_contact(
            cliente_id, phone=row["from_number"], source="voice", status="nuevo",
            entity_type="voice", entity_id=row["call_sid"],
        )
    for row in whatsapp:
        entity_id = f"wa_{_normalize_crm_phone(row['from_number'])}"
        if entity_id in linked_whatsapp_ids:
            continue
        _crm_upsert_contact(
            cliente_id, phone=row["from_number"], source="whatsapp", status="nuevo",
            entity_type="chat", entity_id=entity_id,
        )
    with appstate.state_lock:
        CRM_BACKFILLED_CLIENTS.add(cliente_id)


def _crm_contact_filters(
    cliente_id: str,
    *,
    q: str = "",
    status_filter: str = "",
    tag: str = "",
    owner: str = "",
    source: str = "",
    next_action_filter: str = "",
    date_from: str = "",
    date_to: str = "",
) -> Tuple[str, List[Any]]:
    clauses = ["c.cliente_id = ?"]
    params: List[Any] = [cliente_id]
    query = _normalize_crm_search(q)
    if query:
        clauses.append("c.search_text LIKE ?")
        params.append(f"%{query}%")
    if status_filter in CRM_CONTACT_STATUSES:
        clauses.append("c.status = ?")
        params.append(status_filter)
    clean_tag = textnorm._sanitize_text(tag)[:80]
    if clean_tag:
        # Match the exact JSON string value without requiring SQLite's optional
        # JSON1 extension (some supported Python/SQLite builds omit json_each).
        encoded_tag = json.dumps(clean_tag, ensure_ascii=False).casefold()
        escaped_tag = encoded_tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("LOWER(c.tags_json) LIKE ? ESCAPE '\\'")
        params.append(f"%{escaped_tag}%")
    clean_owner = textnorm._sanitize_text(owner)[:200]
    if clean_owner:
        clauses.append("LOWER(c.owner) = LOWER(?)")
        params.append(clean_owner)
    clean_source = textnorm._sanitize_text(source)[:40]
    if clean_source:
        clauses.append("(c.source_first = ? OR c.source_last = ? OR EXISTS (SELECT 1 FROM crm_contact_links sl WHERE sl.cliente_id=c.cliente_id AND sl.contact_id=c.id AND sl.source=?))")
        params.extend([clean_source, clean_source, clean_source])
    now_iso = timeutils._utc_now_iso()
    if next_action_filter == "pending":
        clauses.append("c.next_action_at <> ''")
    elif next_action_filter == "overdue":
        clauses.append("c.next_action_at <> '' AND c.next_action_at < ?")
        params.append(now_iso)
    elif next_action_filter == "upcoming":
        clauses.append("c.next_action_at <> '' AND c.next_action_at >= ?")
        params.append(now_iso)
    elif next_action_filter == "none":
        clauses.append("c.next_action_at = ''")
    for value, operator in ((date_from, ">="), (date_to, "<=")):
        clean_date = textnorm._sanitize_text(value)[:40]
        if clean_date:
            clauses.append(f"c.last_seen_at {operator} ?")
            params.append(clean_date)
    return " AND ".join(clauses), params


def _crm_contacts_query(
    connection: sqlite3.Connection,
    where: str,
    params: List[Any],
    *,
    order_by: str,
    limit: int,
    offset: int,
) -> List[sqlite3.Row]:
    return connection.execute(
        f"""
        WITH link_counts AS (
            SELECT cliente_id, contact_id,
                SUM(CASE WHEN entity_type='lead' THEN 1 ELSE 0 END) AS leads_count,
                SUM(CASE WHEN entity_type='booking' THEN 1 ELSE 0 END) AS bookings_count,
                SUM(CASE WHEN entity_type='chat' THEN 1 ELSE 0 END) AS chats_count,
                SUM(CASE WHEN entity_type='voice' THEN 1 ELSE 0 END) AS voice_calls_count
            FROM crm_contact_links
            WHERE cliente_id = ?
            GROUP BY cliente_id, contact_id
        )
        SELECT c.*,
            COALESCE(lc.leads_count, 0) AS leads_count,
            COALESCE(lc.bookings_count, 0) AS bookings_count,
            COALESCE(lc.chats_count, 0) AS chats_count,
            COALESCE(lc.voice_calls_count, 0) AS voice_calls_count
        FROM crm_contacts c
        LEFT JOIN link_counts lc ON lc.cliente_id=c.cliente_id AND lc.contact_id=c.id
        WHERE {where}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """,
        (params[0], *params, limit, offset),
    ).fetchall()


def _lead_row_to_public(row: sqlite3.Row) -> AppLeadPublic:
    return AppLeadPublic(
        id=row["id"],
        name=row["name"] or "",
        email=row["email"] or "",
        phone=row["phone"] or "",
        message=row["message"] or "",
        source=row["source"] or "chat",
        session_id=row["session_id"] or "",
        created_at=row["created_at"] or "",
    )


