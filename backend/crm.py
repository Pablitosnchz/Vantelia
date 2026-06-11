"""CRM ligero multi-tenant (refactor F3).

Contactos unificados por cliente con normalizacion de email/telefono,
prioridad de estados y auditoria. Detalle en docs/CRM_Y_PAGOS_MVP.md.
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
import unicodedata
from typing import Any, Dict, List, Optional

from backend import appstate, clients, db, settings, textnorm, timeutils

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


