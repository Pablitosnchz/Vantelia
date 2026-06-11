"""Agenda interna multi-tenant: empleados, servicios, horarios y disponibilidad (refactor F3).

La disponibilidad es por intervalos: un servicio de N min ocupa N min sobre el
grid (slot_minutes = paso) en TODOS los canales. Helpers clave:
_service_duration_minutes, _booked_intervals, _interval_overlaps.
"""
from __future__ import annotations

import copy
import json
import re
import secrets
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException, status

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from api_models import (
    PortalAgendaBlock,
    PortalAgendaBlockPayload,
    PortalEmployeePayload,
    PortalEmployeePublic,
    PortalEmployeesResponse,
    PortalSchedulePublic,
    PortalScheduleUpdatePayload,
)
from backend import appstate, clients, db, emailing, messaging, security, settings, textnorm, timeutils

EMPLOYEE_COLOR_PALETTE = [
    "#00b1d9",
    "#2e86ab",
    "#4caf50",
    "#ff8a65",
    "#f4b400",
    "#8e7dff",
]


DEFAULT_EMPLOYEE_ROLE_LABEL = "Agenda General"


def _normalize_employee_color(value: str, fallback: str = "#00b1d9") -> str:
    candidate = textnorm._sanitize_text(value) or fallback
    if not re.match(r"^#[0-9A-Fa-f]{6}$", candidate):
        return fallback
    return candidate


def _normalize_closed_weekdays_list(values: Any) -> List[int]:
    normalized: List[int] = []
    for value in values or []:
        try:
            day = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in normalized:
            normalized.append(day)
    return sorted(normalized)


def _employee_closed_weekdays_from_row(row: sqlite3.Row) -> List[int]:
    try:
        return _normalize_closed_weekdays_list(json.loads(row["closed_weekdays_json"] or "[]"))
    except json.JSONDecodeError:
        return []


def _normalize_service_id(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", textnorm._sanitize_text(value).lower()).strip("_")


def _service_map_for_client(cliente_id: str) -> Dict[str, Dict[str, str]]:
    return {
        str(service["id"]): service
        for service in _extract_services_from_info(cliente_id)
        if isinstance(service, dict) and service.get("id") and service.get("nombre")
    }


def _normalize_service_ids_for_client(cliente_id: str, values: Any) -> List[str]:
    service_map = _service_map_for_client(cliente_id)
    normalized: List[str] = []
    for value in values or []:
        service_id = _normalize_service_id(str(value))
        if service_id and service_id in service_map and service_id not in normalized:
            normalized.append(service_id)
    return normalized


def _employee_service_ids_from_row(row: sqlite3.Row, cliente_id: str = "") -> List[str]:
    if not row:
        return []
    target_client_id = cliente_id or str(row["cliente_id"] or "")
    try:
        raw_values = json.loads(row["service_ids_json"] or "[]")
    except json.JSONDecodeError:
        return []
    return _normalize_service_ids_for_client(target_client_id, raw_values)


def _employee_defaults_for_client(cliente_id: str) -> Dict[str, Any]:
    config = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    booking = config.get("booking", {})
    break_windows = textnorm._normalize_break_windows(
        booking.get("day_start", "09:00"),
        booking.get("day_end", "18:00"),
        booking.get("break_windows", []),
        booking.get("break_start", ""),
        booking.get("break_end", ""),
    )
    break_start, break_end = textnorm._first_break_pair(break_windows)
    return {
        "timezone": booking.get("timezone", settings.DEFAULT_TIMEZONE),
        "slot_minutes": int(booking.get("slot_minutes", 30)),
        "day_start": booking.get("day_start", "09:00"),
        "day_end": booking.get("day_end", "18:00"),
        "break_start": break_start,
        "break_end": break_end,
        "break_windows": break_windows,
        "closed_weekdays": _normalize_closed_weekdays_list(booking.get("closed_weekdays", [])),
    }


def _default_employee_name(cliente_id: str) -> str:
    config = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    company = textnorm._sanitize_text(config.get("nombre", cliente_id))
    return f"Agenda general {company}".strip()


def _ensure_default_employees_for_all_clients() -> None:
    with db._get_db_connection() as connection:
        now_iso = timeutils._utc_now().isoformat().replace("+00:00", "Z")
        for index, cliente_id in enumerate(appstate.CONFIG_CLIENTES.keys()):
            row = connection.execute(
                "SELECT * FROM employees WHERE cliente_id = ? AND is_default = 1 LIMIT 1",
                (cliente_id,),
            ).fetchone()
            defaults = _employee_defaults_for_client(cliente_id)
            if not row:
                employee_id = f"emp_{secrets.token_urlsafe(8)}"
                connection.execute(
                    """
                    INSERT INTO employees (
                        id, cliente_id, name, role_label, color, is_active, is_default,
                        timezone, slot_minutes, day_start, day_end, break_start, break_end,
                        break_windows_json, closed_weekdays_json, service_ids_json,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        employee_id,
                        cliente_id,
                        _default_employee_name(cliente_id),
                        DEFAULT_EMPLOYEE_ROLE_LABEL,
                        EMPLOYEE_COLOR_PALETTE[index % len(EMPLOYEE_COLOR_PALETTE)],
                        1,
                        1,
                        defaults["timezone"],
                        defaults["slot_minutes"],
                        defaults["day_start"],
                        defaults["day_end"],
                        defaults["break_start"],
                        defaults["break_end"],
                        json.dumps(defaults["break_windows"]),
                        json.dumps(defaults["closed_weekdays"]),
                        "[]",
                        now_iso,
                        now_iso,
                    ),
                )
                row = connection.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
            if row:
                connection.execute(
                    """
                    UPDATE bookings
                    SET employee_id = ?, employee_name = ?
                    WHERE cliente_id = ?
                      AND (employee_id = '' OR employee_name = '')
                    """,
                    (row["id"], row["name"], cliente_id),
                )
        connection.commit()


def _list_employee_rows(cliente_id: str, *, include_inactive: bool = True) -> List[sqlite3.Row]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if not include_inactive:
        clauses.append("is_active = 1")
    sql = (
        "SELECT * FROM employees WHERE "
        + " AND ".join(clauses)
        + " ORDER BY is_default DESC, is_active DESC, name COLLATE NOCASE ASC"
    )
    with db._get_db_connection() as connection:
        return connection.execute(sql, tuple(params)).fetchall()


def _list_public_employee_rows(cliente_id: str, *, include_inactive: bool = False) -> List[sqlite3.Row]:
    rows = _list_employee_rows(cliente_id, include_inactive=include_inactive)
    public_rows = [
        row
        for row in rows
        if not bool(row["is_default"])
    ]
    return public_rows or rows


def _get_employee_row(employee_id: str, *, cliente_id: str = "") -> Optional[sqlite3.Row]:
    clauses = ["id = ?"]
    params: List[Any] = [employee_id]
    if cliente_id:
        clauses.append("cliente_id = ?")
        params.append(cliente_id)
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM employees WHERE " + " AND ".join(clauses) + " LIMIT 1",
            tuple(params),
        ).fetchone()


def _default_employee_row(cliente_id: str) -> sqlite3.Row:
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM employees WHERE cliente_id = ? AND is_default = 1 LIMIT 1",
            (cliente_id,),
        ).fetchone()
        if row:
            return row
        row = connection.execute(
            "SELECT * FROM employees WHERE cliente_id = ? ORDER BY is_active DESC, name COLLATE NOCASE ASC LIMIT 1",
            (cliente_id,),
        ).fetchone()
        if row:
            return row
    raise HTTPException(status_code=404, detail="No hay profesionales configurados para este cliente.")


def _resolve_employee_for_booking(
    cliente_id: str,
    employee_id: str = "",
    *,
    require_active: bool = True,
) -> sqlite3.Row:
    row = _get_employee_row(employee_id, cliente_id=cliente_id) if employee_id else None
    if row is None:
        row = _default_employee_row(cliente_id)
    if require_active and not bool(row["is_active"]):
        raise HTTPException(status_code=409, detail="El profesional seleccionado no esta activo.")
    return row


def _service_row_to_public(row: sqlite3.Row) -> Dict[str, Any]:
    price_cents = int(row["price_cents"] or 0)
    with db._get_db_connection() as connection:
        policy = connection.execute(
            "SELECT * FROM service_payment_policies WHERE cliente_id=? AND service_id=?",
            (row["cliente_id"], row["slug"]),
        ).fetchone()
    return {
        "id": row["slug"],
        "nombre": row["name"],
        "descripcion": row["description"] or "",
        "duration_minutes": int(row["duration_minutes"] or 0),
        "price_cents": price_cents,
        "price_label": textnorm._format_price_cents(price_cents),
        "is_active": bool(row["is_active"]),
        "payment_mode": policy["mode"] if policy else (row["payment_mode"] or "payment_disabled"),
        "payment_type": row["payment_type"] or "full",
        "deposit_amount_cents": int(row["deposit_amount_cents"] or 0),
        "currency": (row["currency"] or "eur").lower(),
        "deposit_value": int(policy["deposit_value"] or 0) if policy else 0,
        "confirm_booking_on_paid": bool(policy["confirm_booking_on_paid"]) if policy else True,
    }


def _services_count(cliente_id: str) -> int:
    with db._get_db_connection() as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM services WHERE cliente_id = ?", (cliente_id,)
            ).fetchone()[0]
        )


def _ensure_services_seeded(cliente_id: str) -> None:
    """Siembra el catalogo desde info.txt si esta vacio (duracion = slot del
    cliente, precio 0). Idempotente; mantiene los slug que ya usan los empleados."""
    if _services_count(cliente_id) > 0:
        return
    seeded = _extract_services_from_info(cliente_id)
    if not seeded:
        return
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        for idx, svc in enumerate(seeded):
            slug = _normalize_service_id(svc.get("nombre") or svc.get("id") or "")
            if not slug:
                continue
            duration = int(svc.get("duration_minutes") or 0) or 30
            price_cents = int(svc.get("price_cents") or 0)
            connection.execute(
                """
                INSERT OR IGNORE INTO services
                (cliente_id, slug, name, duration_minutes, price_cents, description, is_active, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    cliente_id, slug, textnorm._sanitize_text(svc.get("nombre") or slug),
                    duration, price_cents, textnorm._sanitize_text(svc.get("descripcion") or "", allow_multiline=True),
                    idx, now, now,
                ),
            )
        connection.commit()


def _list_service_rows(cliente_id: str, *, include_inactive: bool = False) -> List[sqlite3.Row]:
    _ensure_services_seeded(cliente_id)
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if not include_inactive:
        clauses.append("is_active = 1")
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM services WHERE " + " AND ".join(clauses)
            + " ORDER BY sort_order ASC, name COLLATE NOCASE ASC",
            tuple(params),
        ).fetchall()


def _catalog_services(cliente_id: str, *, include_inactive: bool = False) -> List[Dict[str, Any]]:
    return [_service_row_to_public(r) for r in _list_service_rows(cliente_id, include_inactive=include_inactive)]


def _get_service_row(cliente_id: str, slug: str) -> Optional[sqlite3.Row]:
    if not slug:
        return None
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM services WHERE cliente_id = ? AND slug = ? LIMIT 1",
            (cliente_id, slug),
        ).fetchone()


def _service_match_key(value: str) -> str:
    """Clave de comparacion de nombres de servicio robusta a tildes, mayusculas y
    forma de normalizacion Unicode. Permite casar el servicio que llega de
    cualquier canal con el catalogo aunque difieran en tildes o caja."""
    text = unicodedata.normalize("NFKD", textnorm._sanitize_text(value or "")).casefold()
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _find_service_by_name(cliente_id: str, name: str) -> Optional[sqlite3.Row]:
    name_clean = textnorm._sanitize_text(name or "")
    if not name_clean:
        return None
    # El nombre puede llegar como etiqueta completa ("Nombre . 75 min . 80EUR");
    # probamos tambien solo la parte del nombre antes del separador.
    variants = [name_clean]
    if " · " in name_clean:
        variants.append(name_clean.split(" · ", 1)[0].strip())

    rows = _list_service_rows(cliente_id, include_inactive=True)
    for variant in variants:
        if not variant:
            continue
        row = _get_service_row(cliente_id, _normalize_service_id(variant))
        if row:
            return row
        key = _service_match_key(variant)
        if not key:
            continue
        for candidate in rows:
            if _service_match_key(candidate["name"]) == key:
                return candidate
    return None


def _service_duration_minutes(
    cliente_id: str, servicio_name: str, employee_row: Optional[sqlite3.Row] = None
) -> int:
    row = _find_service_by_name(cliente_id, servicio_name) if servicio_name else None
    if row and int(row["duration_minutes"] or 0) > 0:
        return int(row["duration_minutes"])
    if employee_row is not None:
        return int(_employee_schedule_from_row(employee_row)["slot_minutes"])
    return int(_employee_defaults_for_client(cliente_id).get("slot_minutes", 30) or 30)


def _employee_schedule_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        raw_break_windows = json.loads(row["break_windows_json"] or "[]")
    except (IndexError, KeyError, json.JSONDecodeError):
        raw_break_windows = []
    break_windows = textnorm._normalize_break_windows(
        row["day_start"] or "09:00",
        row["day_end"] or "18:00",
        raw_break_windows,
        row["break_start"] or "",
        row["break_end"] or "",
    )
    break_start, break_end = textnorm._first_break_pair(break_windows)
    return {
        "timezone": row["timezone"] or settings.DEFAULT_TIMEZONE,
        "slot_minutes": int(row["slot_minutes"] or 30),
        "day_start": row["day_start"] or "09:00",
        "day_end": row["day_end"] or "18:00",
        "break_start": break_start,
        "break_end": break_end,
        "break_windows": break_windows,
        "closed_weekdays": _employee_closed_weekdays_from_row(row),
    }


def _employee_booking_counters(cliente_id: str, employee_id: str) -> Dict[str, int]:
    employee_row = _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    timezone_name = _employee_schedule_from_row(employee_row)["timezone"]
    today = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        today_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM bookings
            WHERE cliente_id = ?
              AND employee_id = ?
              AND booking_date = ?
              AND status IN ('confirmed', 'pending_review', 'pending_payment')
            """,
            (cliente_id, employee_id, today),
        ).fetchone()[0]
        upcoming_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM bookings
            WHERE cliente_id = ?
              AND employee_id = ?
              AND status IN ('confirmed', 'pending_review', 'pending_payment')
              AND (start_at = '' OR start_at >= ?)
            """,
            (cliente_id, employee_id, now_iso),
        ).fetchone()[0]
    return {"today": int(today_count), "upcoming": int(upcoming_count)}


def _serialize_agenda_block(row: sqlite3.Row) -> PortalAgendaBlock:
    return PortalAgendaBlock(
        block_id=row["id"],
        employee_id=row["employee_id"] or "",
        fecha=row["block_date"],
        hora_inicio=row["start_time"],
        hora_fin=row["end_time"],
        motivo=row["reason"] or "",
        created_at=row["created_at"] or "",
    )


def _list_agenda_blocks(
    cliente_id: str,
    *,
    employee_id: Optional[str] = None,
    include_general: bool = False,
    date_from: str = "",
    date_to: str = "",
) -> List[sqlite3.Row]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if employee_id is None:
        pass
    elif employee_id:
        if include_general:
            clauses.append("(employee_id = ? OR employee_id = '')")
        else:
            clauses.append("employee_id = ?")
        params.append(employee_id)
    else:
        clauses.append("employee_id = ''")
    if date_from:
        clauses.append("block_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("block_date <= ?")
        params.append(date_to)
    sql = (
        "SELECT * FROM agenda_blocks WHERE "
        + " AND ".join(clauses)
        + " ORDER BY block_date ASC, start_time ASC"
    )
    with db._get_db_connection() as connection:
        return connection.execute(sql, tuple(params)).fetchall()


def _agenda_block_date_range(date_from: str, date_to: str = "") -> List[str]:
    start_date = textnorm._parse_date(date_from).date()
    end_date = textnorm._parse_date(date_to or date_from).date()
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="La fecha final no puede ser anterior a la inicial.")
    total_days = (end_date - start_date).days + 1
    if total_days > 366:
        raise HTTPException(status_code=400, detail="El intervalo de bloqueo no puede superar 366 dias.")
    return [(start_date + timedelta(days=offset)).isoformat() for offset in range(total_days)]


def _create_agenda_blocks(
    cliente_id: str,
    data: PortalAgendaBlockPayload,
    *,
    employee_id: str = "",
) -> Tuple[List[sqlite3.Row], int, str, str]:
    selected_days = _agenda_block_date_range(data.fecha, data.fecha_fin)
    start_time = textnorm._parse_time(data.hora_inicio).strftime("%H:%M")
    end_time = textnorm._parse_time(data.hora_fin).strftime("%H:%M")
    if start_time >= end_time:
        raise HTTPException(status_code=400, detail="La hora de fin debe ser posterior a la hora de inicio.")
    if employee_id:
        _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    conflicts: List[sqlite3.Row] = []
    for selected_day in selected_days:
        conflicts.extend(
            _booking_conflicts_for_block(
                cliente_id,
                selected_day,
                start_time,
                end_time,
                employee_id=employee_id,
            )
        )
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail=_booking_conflict_message(
                conflicts,
                "Hay citas activas dentro del intervalo solicitado. Cancelalas o reprogramalas antes de bloquear la ",
            ),
        )

    created_at = timeutils._utc_now_iso()
    reason = textnorm._sanitize_text(data.motivo)
    created_rows: List[sqlite3.Row] = []
    skipped_count = 0
    with db._get_db_connection() as connection:
        for selected_day in selected_days:
            existing = connection.execute(
                """
                SELECT *
                FROM agenda_blocks
                WHERE cliente_id = ?
                  AND employee_id = ?
                  AND block_date = ?
                  AND start_time = ?
                  AND end_time = ?
                LIMIT 1
                """,
                (cliente_id, employee_id, selected_day, start_time, end_time),
            ).fetchone()
            if existing:
                skipped_count += 1
                continue

            block_id = f"blk_{secrets.token_urlsafe(10)}"
            connection.execute(
                """
                INSERT INTO agenda_blocks (id, cliente_id, employee_id, block_date, start_time, end_time, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    block_id,
                    cliente_id,
                    employee_id,
                    selected_day,
                    start_time,
                    end_time,
                    reason,
                    created_at,
                ),
            )
            row = connection.execute("SELECT * FROM agenda_blocks WHERE id = ?", (block_id,)).fetchone()
            if row:
                created_rows.append(row)
        connection.commit()
    return created_rows, skipped_count, selected_days[0], selected_days[-1]


def _delete_agenda_block(cliente_id: str, block_id: str, *, employee_id: Optional[str] = None) -> None:
    with db._get_db_connection() as connection:
        clauses = ["id = ?", "cliente_id = ?"]
        params: List[Any] = [block_id, cliente_id]
        if employee_id is None:
            pass
        elif employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        else:
            clauses.append("employee_id = ''")
        row = connection.execute(
            "SELECT id FROM agenda_blocks WHERE " + " AND ".join(clauses),
            tuple(params),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Bloqueo no encontrado.")
        connection.execute("DELETE FROM agenda_blocks WHERE id = ?", (block_id,))
        connection.commit()


def _reminder_channel_availability(cliente_id: str) -> Dict[str, Dict[str, Any]]:
    config = clients._get_client_config(cliente_id)
    whatsapp_cfg = config.get("whatsapp", {}) or {}

    whatsapp_plan = bool(clients._plan_feature(cliente_id, "whatsapp_enabled"))
    whatsapp_token = messaging._whatsapp_access_token_for_client(cliente_id)
    whatsapp_ready = bool(
        whatsapp_plan
        and whatsapp_cfg.get("enabled")
        and str(whatsapp_cfg.get("phone_number_id", "") or "").strip()
        and whatsapp_token
    )
    if not whatsapp_plan:
        whatsapp_reason = "Necesitas un plan con WhatsApp."
    elif not whatsapp_cfg.get("enabled"):
        whatsapp_reason = "Activa WhatsApp en el portal."
    elif not str(whatsapp_cfg.get("phone_number_id", "") or "").strip():
        whatsapp_reason = "Falta el Phone Number ID de WhatsApp."
    elif not whatsapp_token:
        whatsapp_reason = "Falta el token de envio de WhatsApp en servidor."
    else:
        whatsapp_reason = "Disponible."

    channel_status = emailing._channel_settings_public(cliente_id)
    sms_ready = channel_status.sms.available
    sms_reason = "Disponible." if sms_ready else "Configura y activa un remitente en Canales de envio."

    return {
        "email": {"available": True, "reason": "Disponible.", "label": "Email"},
        "whatsapp": {"available": whatsapp_ready, "reason": whatsapp_reason, "label": "WhatsApp"},
        "sms": {"available": sms_ready, "reason": sms_reason, "label": "SMS"},
    }


def _portal_schedule_from_config(cliente_id: str) -> PortalSchedulePublic:
    config = clients._get_client_config(cliente_id)
    booking = config["booking"]
    break_windows = textnorm._normalize_break_windows(
        booking.get("day_start", "09:00"),
        booking.get("day_end", "18:00"),
        booking.get("break_windows", []),
        booking.get("break_start", ""),
        booking.get("break_end", ""),
    )
    break_start, break_end = textnorm._first_break_pair(break_windows)
    today = timeutils._utc_now().date().isoformat()
    future_limit = (timeutils._utc_now() + timedelta(days=180)).date().isoformat()
    return PortalSchedulePublic(
        enabled=bool(booking.get("enabled", False)),
        timezone=booking.get("timezone", settings.DEFAULT_TIMEZONE),
        slot_minutes=int(booking.get("slot_minutes", 30)),
        day_start=booking.get("day_start", "09:00"),
        day_end=booking.get("day_end", "18:00"),
        break_start=break_start,
        break_end=break_end,
        break_windows=break_windows,
        closed_weekdays=list(booking.get("closed_weekdays", [])),
        message_templates=textnorm._normalize_message_templates(booking.get("message_templates", {})),
        message_template_enabled=textnorm._normalize_message_template_enabled(
            booking.get("message_template_enabled", {}),
            booking.get("message_templates", {}),
        ),
        message_template_channels=textnorm._normalize_message_template_channels(
            booking.get("message_template_channels", {})
        ),
        reminder_channel_availability=_reminder_channel_availability(cliente_id),
        blocks=[
            _serialize_agenda_block(row)
            for row in _list_agenda_blocks(cliente_id, employee_id="", date_from=today, date_to=future_limit)
        ],
    )


def _portal_schedule_from_employee(cliente_id: str, employee_id: str) -> PortalSchedulePublic:
    row = _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    schedule = _employee_schedule_from_row(row)
    booking = clients._get_client_config(cliente_id)["booking"]
    today = timeutils._utc_now().date().isoformat()
    future_limit = (timeutils._utc_now() + timedelta(days=180)).date().isoformat()
    return PortalSchedulePublic(
        enabled=bool(row["is_active"]),
        timezone=schedule["timezone"],
        slot_minutes=schedule["slot_minutes"],
        day_start=schedule["day_start"],
        day_end=schedule["day_end"],
        break_start=schedule["break_start"],
        break_end=schedule["break_end"],
        break_windows=schedule["break_windows"],
        closed_weekdays=schedule["closed_weekdays"],
        message_templates=textnorm._normalize_message_templates(booking.get("message_templates", {})),
        message_template_enabled=textnorm._normalize_message_template_enabled(
            booking.get("message_template_enabled", {}),
            booking.get("message_templates", {}),
        ),
        message_template_channels=textnorm._normalize_message_template_channels(
            booking.get("message_template_channels", {})
        ),
        reminder_channel_availability=_reminder_channel_availability(cliente_id),
        blocks=[
            _serialize_agenda_block(block)
            for block in _list_agenda_blocks(
                cliente_id,
                employee_id=employee_id,
                date_from=today,
                date_to=future_limit,
            )
        ],
    )


def _update_client_schedule(cliente_id: str, data: PortalScheduleUpdatePayload) -> PortalSchedulePublic:
    next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
    config = next_configs.get(cliente_id)
    if not config:
        raise HTTPException(status_code=404, detail="Cliente no configurado")
    booking = dict(config.get("booking", {}))
    raw_fields_set = getattr(data, "model_fields_set", None)
    if raw_fields_set is None:
        raw_fields_set = getattr(data, "__fields_set__", set())
    fields_set = set(raw_fields_set)
    schedule_fields = {
        "enabled",
        "timezone",
        "slot_minutes",
        "day_start",
        "day_end",
        "break_start",
        "break_end",
        "break_windows",
        "closed_weekdays",
    }
    should_update_schedule = bool(fields_set & schedule_fields) or (
        data.message_templates is None
        and data.message_template_enabled is None
        and data.message_template_channels is None
    )
    if should_update_schedule:
        start = textnorm._parse_time(data.day_start).strftime("%H:%M")
        end = textnorm._parse_time(data.day_end).strftime("%H:%M")
        if start >= end:
            raise HTTPException(status_code=400, detail="La hora de fin debe ser posterior a la hora de inicio.")
        break_windows = textnorm._normalize_break_windows(start, end, data.break_windows, data.break_start, data.break_end)
        break_start, break_end = textnorm._first_break_pair(break_windows)
        closed_weekdays = sorted({int(day) for day in data.closed_weekdays if 0 <= int(day) <= 6})
        if len(closed_weekdays) != len(set(data.closed_weekdays)):
            closed_weekdays = sorted(set(closed_weekdays))
        previous_closed_weekdays = {
            int(day)
            for day in config.get("booking", {}).get("closed_weekdays", [])
            if isinstance(day, int) and 0 <= day <= 6
        }
        newly_closed_weekdays = set(closed_weekdays) - previous_closed_weekdays
        if newly_closed_weekdays:
            conflicts = _booking_conflicts_for_closed_weekdays(cliente_id, newly_closed_weekdays)
            if conflicts:
                raise HTTPException(
                    status_code=409,
                    detail=_booking_conflict_message(
                        conflicts,
                        "Hay citas activas en los dias que quieres cerrar. Cancelalas o reprogramalas antes de guardar.",
                    ),
                )
        previous_break_windows = textnorm._normalize_break_windows(
            config.get("booking", {}).get("day_start", "09:00"),
            config.get("booking", {}).get("day_end", "18:00"),
            config.get("booking", {}).get("break_windows", []),
            config.get("booking", {}).get("break_start", ""),
            config.get("booking", {}).get("break_end", ""),
        )
        if break_windows != previous_break_windows and break_windows:
            try:
                default_employee_id = _default_employee_row(cliente_id)["id"]
            except HTTPException:
                default_employee_id = ""
            conflicts = _booking_conflicts_for_break_windows(
                cliente_id,
                break_windows,
                employee_id=default_employee_id,
            )
            if conflicts:
                raise HTTPException(
                    status_code=409,
                    detail=_schedule_conflict_detail(
                        conflicts,
                        "Hay citas activas dentro del descanso que quieres guardar. Cancelalas o reprogramalas antes.",
                    ),
                )
        booking.update(
            {
                "enabled": bool(data.enabled),
                "timezone": textnorm._sanitize_text(data.timezone) or settings.DEFAULT_TIMEZONE,
                "slot_minutes": int(data.slot_minutes),
                "day_start": start,
                "day_end": end,
                "break_start": break_start,
                "break_end": break_end,
                "break_windows": break_windows,
                "closed_weekdays": closed_weekdays,
            }
        )
    if data.message_templates is not None:
        booking["message_templates"] = textnorm._normalize_message_templates(data.message_templates)
    if data.message_template_enabled is not None:
        booking["message_template_enabled"] = textnorm._normalize_message_template_enabled(
            data.message_template_enabled,
            data.message_templates,
        )
    if data.message_template_channels is not None:
        availability = _reminder_channel_availability(cliente_id)
        channels = textnorm._normalize_message_template_channels(data.message_template_channels)
        for kind, channel_map in channels.items():
            for channel_name in ("whatsapp", "sms"):
                if channel_map.get(channel_name) and not availability.get(channel_name, {}).get("available"):
                    channel_map[channel_name] = False
        booking["message_template_channels"] = channels
    config["booking"] = booking
    clients._validate_single_client_runtime(cliente_id, config)
    clients._persist_configs_to_disk(next_configs)
    if should_update_schedule:
        with db._get_db_connection() as connection:
            connection.execute(
                """
                UPDATE employees
                SET timezone = ?, slot_minutes = ?, day_start = ?, day_end = ?,
                    break_start = ?, break_end = ?, break_windows_json = ?,
                    closed_weekdays_json = ?, updated_at = ?
                WHERE cliente_id = ? AND is_default = 1
                """,
                (
                    booking["timezone"],
                    int(booking["slot_minutes"]),
                    booking["day_start"],
                    booking["day_end"],
                    booking.get("break_start", ""),
                    booking.get("break_end", ""),
                    json.dumps(booking.get("break_windows", [])),
                    json.dumps(booking["closed_weekdays"]),
                    timeutils._utc_now_iso(),
                    cliente_id,
                ),
            )
            connection.commit()
    clients._update_runtime_configs(next_configs)
    return _portal_schedule_from_config(cliente_id)


def _update_employee_schedule(cliente_id: str, employee_id: str, data: PortalScheduleUpdatePayload) -> PortalSchedulePublic:
    row = _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    start = textnorm._parse_time(data.day_start).strftime("%H:%M")
    end = textnorm._parse_time(data.day_end).strftime("%H:%M")
    if start >= end:
        raise HTTPException(status_code=400, detail="La hora de fin debe ser posterior a la hora de inicio.")
    break_windows = textnorm._normalize_break_windows(start, end, data.break_windows, data.break_start, data.break_end)
    break_start, break_end = textnorm._first_break_pair(break_windows)
    closed_weekdays = _normalize_closed_weekdays_list(data.closed_weekdays)
    previous_closed_weekdays = set(_employee_closed_weekdays_from_row(row))
    newly_closed_weekdays = set(closed_weekdays) - previous_closed_weekdays
    if newly_closed_weekdays:
        conflicts = _booking_conflicts_for_closed_weekdays(
            cliente_id,
            newly_closed_weekdays,
            employee_id=employee_id,
        )
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail=_booking_conflict_message(
                    conflicts,
                    "Hay citas activas en los dias que quieres cerrar. Cancelalas o reprogramalas antes de guardar.",
                ),
            )
    previous_schedule = _employee_schedule_from_row(row)
    previous_break_windows = previous_schedule.get("break_windows", [])
    if break_windows != previous_break_windows and break_windows:
        conflicts = _booking_conflicts_for_break_windows(
            cliente_id,
            break_windows,
            employee_id=employee_id,
        )
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail=_schedule_conflict_detail(
                    conflicts,
                    "Hay citas activas dentro del descanso que quieres guardar. Cancelalas o reprogramalas antes.",
                ),
            )
    with db._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE employees
            SET timezone = ?, slot_minutes = ?, day_start = ?, day_end = ?,
                break_start = ?, break_end = ?, break_windows_json = ?,
                closed_weekdays_json = ?, updated_at = ?
            WHERE id = ? AND cliente_id = ?
            """,
            (
                textnorm._sanitize_text(data.timezone) or settings.DEFAULT_TIMEZONE,
                int(data.slot_minutes),
                start,
                end,
                break_start,
                break_end,
                json.dumps(break_windows),
                json.dumps(closed_weekdays),
                timeutils._utc_now_iso(),
                employee_id,
                cliente_id,
            ),
        )
        connection.commit()
    return _portal_schedule_from_employee(cliente_id, employee_id)


def _serialize_portal_employee(row: sqlite3.Row) -> PortalEmployeePublic:
    counters = _employee_booking_counters(row["cliente_id"], row["id"])
    today = timeutils._utc_now().date().isoformat()
    future_limit = (timeutils._utc_now() + timedelta(days=180)).date().isoformat()
    schedule = _employee_schedule_from_row(row)
    is_default = bool(row["is_default"])
    service_ids = _employee_service_ids_from_row(row)
    return PortalEmployeePublic(
        employee_id=row["id"],
        cliente_id=row["cliente_id"],
        name=row["name"],
        role_label=DEFAULT_EMPLOYEE_ROLE_LABEL if is_default else (row["role_label"] or ""),
        color=_normalize_employee_color(row["color"] or "#00b1d9"),
        is_active=bool(row["is_active"]),
        is_default=is_default,
        timezone=schedule["timezone"],
        slot_minutes=schedule["slot_minutes"],
        day_start=schedule["day_start"],
        day_end=schedule["day_end"],
        break_start=schedule["break_start"],
        break_end=schedule["break_end"],
        break_windows=schedule["break_windows"],
        closed_weekdays=schedule["closed_weekdays"],
        service_ids=service_ids,
        allows_all_services=not service_ids,
        bookings_today=counters["today"],
        bookings_upcoming=counters["upcoming"],
        blocks=[
            _serialize_agenda_block(block)
            for block in _list_agenda_blocks(
                row["cliente_id"],
                employee_id=row["id"],
                date_from=today,
                date_to=future_limit,
            )
        ],
    )


def _portal_employees_for_client(cliente_id: str) -> PortalEmployeesResponse:
    return PortalEmployeesResponse(
        items=[_serialize_portal_employee(row) for row in _list_employee_rows(cliente_id)]
    )


def _validate_employee_payload(
    cliente_id: str,
    data: PortalEmployeePayload,
    *,
    existing_row: Optional[sqlite3.Row] = None,
) -> Dict[str, Any]:
    raw_fields_set = getattr(data, "model_fields_set", None)
    if raw_fields_set is None:
        raw_fields_set = getattr(data, "__fields_set__", set())
    fields_set = set(raw_fields_set)
    defaults = _employee_schedule_from_row(existing_row) if existing_row is not None else _employee_defaults_for_client(cliente_id)
    start_value = data.day_start if "day_start" in fields_set else defaults["day_start"]
    end_value = data.day_end if "day_end" in fields_set else defaults["day_end"]
    break_start_value = data.break_start if "break_start" in fields_set else defaults.get("break_start", "")
    break_end_value = data.break_end if "break_end" in fields_set else defaults.get("break_end", "")
    break_windows_value = data.break_windows if "break_windows" in fields_set else defaults.get("break_windows", [])
    start = textnorm._parse_time(start_value).strftime("%H:%M")
    end = textnorm._parse_time(end_value).strftime("%H:%M")
    if start >= end:
        raise HTTPException(status_code=400, detail="La hora de fin debe ser posterior a la hora de inicio.")
    break_windows = textnorm._normalize_break_windows(start, end, break_windows_value, break_start_value, break_end_value)
    break_start, break_end = textnorm._first_break_pair(break_windows)
    closed_weekdays = (
        _normalize_closed_weekdays_list(data.closed_weekdays)
        if "closed_weekdays" in fields_set
        else list(defaults.get("closed_weekdays", []))
    )
    service_ids = (
        _normalize_service_ids_for_client(cliente_id, data.service_ids)
        if "service_ids" in fields_set or existing_row is None
        else _employee_service_ids_from_row(existing_row, cliente_id)
    )
    return {
        "name": textnorm._sanitize_text(data.name),
        "role_label": (
            textnorm._sanitize_text(data.role_label)
            if "role_label" in fields_set or existing_row is None
            else textnorm._sanitize_text(existing_row["role_label"] or "")
        ),
        "color": _normalize_employee_color(
            data.color if "color" in fields_set or existing_row is None else existing_row["color"],
            "#00b1d9",
        ),
        "is_active": (
            bool(data.is_active)
            if "is_active" in fields_set or existing_row is None
            else bool(existing_row["is_active"])
        ),
        "timezone": (
            (textnorm._sanitize_text(data.timezone) or defaults["timezone"])
            if "timezone" in fields_set
            else defaults["timezone"]
        ),
        "slot_minutes": int(data.slot_minutes if "slot_minutes" in fields_set else defaults["slot_minutes"]),
        "day_start": start,
        "day_end": end,
        "break_start": break_start,
        "break_end": break_end,
        "break_windows": break_windows,
        "break_windows_json": json.dumps(break_windows),
        "closed_weekdays_json": json.dumps(closed_weekdays),
        "closed_weekdays": closed_weekdays,
        "service_ids_json": json.dumps(service_ids),
        "service_ids": service_ids,
    }


def _create_portal_employee(
    cliente_id: str,
    data: PortalEmployeePayload,
    *,
    full_access: bool = False,
) -> PortalEmployeePublic:
    payload = _validate_employee_payload(cliente_id, data)
    max_professionals = clients._plan_feature(cliente_id, "max_professionals")
    if not full_access and max_professionals is not None and payload["is_active"]:
        current_count = len([item for item in _list_employee_rows(cliente_id, include_inactive=False) if bool(item["is_active"])])
        if current_count >= int(max_professionals):
            limits = clients._plan_limits(clients._client_plan(cliente_id))
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Tu plan {limits.get('label')} permite hasta {max_professionals} profesional(es). "
                    "Sube de plan para ampliar el equipo."
                ),
            )
    created_at = timeutils._utc_now_iso()
    employee_id = f"emp_{secrets.token_urlsafe(8)}"
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO employees (
                id, cliente_id, name, role_label, color, is_active, is_default,
                timezone, slot_minutes, day_start, day_end, break_start, break_end,
                break_windows_json, closed_weekdays_json, service_ids_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                cliente_id,
                payload["name"],
                payload["role_label"],
                payload["color"],
                1 if payload["is_active"] else 0,
                payload["timezone"],
                payload["slot_minutes"],
                payload["day_start"],
                payload["day_end"],
                payload["break_start"],
                payload["break_end"],
                payload["break_windows_json"],
                payload["closed_weekdays_json"],
                payload["service_ids_json"],
                created_at,
                created_at,
            ),
        )
        connection.commit()
    row = _get_employee_row(employee_id, cliente_id=cliente_id)
    if not row:
        raise HTTPException(status_code=500, detail="No se ha podido crear el profesional.")
    return _serialize_portal_employee(row)


def _active_future_bookings_for_employee(cliente_id: str, employee_id: str) -> int:
    with db._get_db_connection() as connection:
        return int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM bookings
                WHERE cliente_id = ?
                  AND employee_id = ?
                  AND status IN ('confirmed', 'pending_review', 'pending_payment')
                  AND (start_at = '' OR start_at >= ?)
                """,
                (cliente_id, employee_id, timeutils._utc_now_iso()),
            ).fetchone()[0]
        )


def _update_portal_employee(
    cliente_id: str,
    employee_id: str,
    data: PortalEmployeePayload,
    *,
    full_access: bool = False,
) -> PortalEmployeePublic:
    row = _get_employee_row(employee_id, cliente_id=cliente_id)
    if not row:
        raise HTTPException(status_code=404, detail="Profesional no encontrado.")
    payload = _validate_employee_payload(cliente_id, data, existing_row=row)
    max_professionals = clients._plan_feature(cliente_id, "max_professionals")
    if (
        not full_access
        and max_professionals is not None
        and payload["is_active"]
        and not bool(row["is_active"])
    ):
        active_count = len([item for item in _list_employee_rows(cliente_id, include_inactive=False) if bool(item["is_active"])])
        if active_count >= int(max_professionals):
            limits = clients._plan_limits(clients._client_plan(cliente_id))
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Tu plan {limits.get('label')} permite hasta {max_professionals} profesional(es) activos. "
                    "Sube de plan para reactivar mas equipo."
                ),
            )
    if row["is_default"]:
        payload["role_label"] = DEFAULT_EMPLOYEE_ROLE_LABEL
    if row["is_default"] and not payload["is_active"]:
        raise HTTPException(status_code=409, detail="La agenda principal no se puede desactivar.")
    if not payload["is_active"] and _active_future_bookings_for_employee(cliente_id, employee_id):
        raise HTTPException(
            status_code=409,
            detail="Este profesional tiene citas futuras activas. Reasignalas o reprogramalas antes de desactivarlo.",
        )
    previous_break_windows = _employee_schedule_from_row(row).get("break_windows", [])
    if payload["break_windows"] != previous_break_windows and payload["break_windows"]:
        conflicts = _booking_conflicts_for_break_windows(
            cliente_id,
            payload["break_windows"],
            employee_id=employee_id,
        )
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail=_schedule_conflict_detail(
                    conflicts,
                    "Hay citas activas dentro del descanso que quieres guardar. Cancelalas o reprogramalas antes.",
                ),
            )
    with db._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE employees
            SET name = ?, role_label = ?, color = ?, is_active = ?, timezone = ?,
                slot_minutes = ?, day_start = ?, day_end = ?, break_start = ?, break_end = ?,
                break_windows_json = ?, closed_weekdays_json = ?, service_ids_json = ?, updated_at = ?
            WHERE id = ? AND cliente_id = ?
            """,
            (
                payload["name"],
                payload["role_label"],
                payload["color"],
                1 if payload["is_active"] else 0,
                payload["timezone"],
                payload["slot_minutes"],
                payload["day_start"],
                payload["day_end"],
                payload["break_start"],
                payload["break_end"],
                payload["break_windows_json"],
                payload["closed_weekdays_json"],
                payload["service_ids_json"],
                timeutils._utc_now_iso(),
                employee_id,
                cliente_id,
            ),
        )
        connection.execute(
            """
            UPDATE bookings
            SET employee_name = ?
            WHERE cliente_id = ? AND employee_id = ?
            """,
            (payload["name"], cliente_id, employee_id),
        )
        connection.commit()
    refreshed = _get_employee_row(employee_id, cliente_id=cliente_id)
    if not refreshed:
        raise HTTPException(status_code=404, detail="Profesional no encontrado.")
    return _serialize_portal_employee(refreshed)


def _delete_portal_employee(cliente_id: str, employee_id: str) -> None:
    row = _get_employee_row(employee_id, cliente_id=cliente_id)
    if not row:
        raise HTTPException(status_code=404, detail="Profesional no encontrado.")
    if row["is_default"]:
        raise HTTPException(status_code=409, detail="La agenda principal no se puede eliminar.")
    if _active_future_bookings_for_employee(cliente_id, employee_id):
        raise HTTPException(
            status_code=409,
            detail="Este profesional tiene citas futuras activas. Reasignalas o reprogramalas antes de eliminarlo.",
        )
    with db._get_db_connection() as connection:
        connection.execute(
            "DELETE FROM agenda_blocks WHERE cliente_id = ? AND employee_id = ?",
            (cliente_id, employee_id),
        )
        connection.execute(
            "DELETE FROM employees WHERE cliente_id = ? AND id = ?",
            (cliente_id, employee_id),
        )
        connection.commit()


def _schedule_preview_payload_from_config(cliente_id: str) -> PortalScheduleUpdatePayload:
    booking = clients._get_client_config(cliente_id).get("booking", {})
    break_windows = textnorm._normalize_break_windows(
        booking.get("day_start", "09:00"),
        booking.get("day_end", "18:00"),
        booking.get("break_windows", []),
        booking.get("break_start", ""),
        booking.get("break_end", ""),
    )
    break_start, break_end = textnorm._first_break_pair(break_windows)
    return PortalScheduleUpdatePayload(
        enabled=bool(booking.get("enabled", True)),
        timezone=textnorm._sanitize_text(booking.get("timezone", settings.DEFAULT_TIMEZONE)) or settings.DEFAULT_TIMEZONE,
        slot_minutes=int(booking.get("slot_minutes", 30)),
        day_start=textnorm._sanitize_text(booking.get("day_start", "09:00")) or "09:00",
        day_end=textnorm._sanitize_text(booking.get("day_end", "18:00")) or "18:00",
        break_start=break_start,
        break_end=break_end,
        break_windows=break_windows,
        closed_weekdays=_normalize_closed_weekdays_list(booking.get("closed_weekdays", [])),
        message_templates=textnorm._normalize_message_templates(booking.get("message_templates", {})),
        message_template_enabled=textnorm._normalize_message_template_enabled(
            booking.get("message_template_enabled", {}),
            booking.get("message_templates", {}),
        ),
        message_template_channels=textnorm._normalize_message_template_channels(
            booking.get("message_template_channels", {})
        ),
    )


def _sample_booking_preview_slot(schedule: PortalScheduleUpdatePayload) -> Tuple[str, str]:
    timezone_name = textnorm._sanitize_text(schedule.timezone) or settings.DEFAULT_TIMEZONE
    today = datetime.now(ZoneInfo(timezone_name)).date()
    closed_days = {
        int(day)
        for day in schedule.closed_weekdays
        if isinstance(day, int) and 0 <= int(day) <= 6
    }
    for offset in range(1, 15):
        candidate = today + timedelta(days=offset)
        if candidate.weekday() not in closed_days:
            return candidate.isoformat(), schedule.day_start
    fallback = today + timedelta(days=1)
    return fallback.isoformat(), schedule.day_start


def _booking_start_end(
    cliente_id: str,
    fecha: str,
    hora: str,
    *,
    employee_id: str = "",
    duration_minutes: Optional[int] = None,
) -> Tuple[datetime, datetime]:
    employee_row = _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    schedule = _employee_schedule_from_row(employee_row)
    tzinfo = ZoneInfo(schedule["timezone"])
    start_local = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=tzinfo)
    minutes = int(duration_minutes or schedule["slot_minutes"]) or int(schedule["slot_minutes"])
    end_local = start_local + timedelta(minutes=minutes)
    return start_local, end_local


def _validate_booking_window(cliente_id: str, selected_day: datetime) -> None:
    config = clients._get_client_config(cliente_id)
    timezone_name = config["booking"]["timezone"]
    today = datetime.now(ZoneInfo(timezone_name)).date()

    if selected_day.date() < today:
        raise HTTPException(status_code=400, detail="No se permiten reservas en fechas pasadas.")

    max_day = today + timedelta(days=settings.MAX_BOOKING_ADVANCE_DAYS)
    if selected_day.date() > max_day:
        raise HTTPException(
            status_code=400,
            detail=f"Solo se admiten reservas con hasta {settings.MAX_BOOKING_ADVANCE_DAYS} dias de antelacion.",
        )


def _build_slots_for_day(
    cliente_id: str, fecha: str, *, employee_id: str = "", duration_minutes: Optional[int] = None
) -> List[str]:
    config = clients._get_client_config(cliente_id)
    if not config["booking"]["enabled"]:
        return []

    employee_row = _resolve_employee_for_booking(cliente_id, employee_id)
    booking_cfg = _employee_schedule_from_row(employee_row)
    selected_day = textnorm._parse_date(fecha)
    _validate_booking_window(cliente_id, selected_day)
    if selected_day.weekday() in booking_cfg["closed_weekdays"]:
        return []

    start_dt = datetime.combine(selected_day.date(), textnorm._parse_time(booking_cfg["day_start"]).time())
    end_dt = datetime.combine(selected_day.date(), textnorm._parse_time(booking_cfg["day_end"]).time())
    slot_minutes = booking_cfg["slot_minutes"]
    span = int(duration_minutes or slot_minutes) or slot_minutes

    if end_dt <= start_dt:
        raise HTTPException(status_code=500, detail="Configuracion horaria invalida para este cliente")

    # Paso del grid = slot_minutes; el hueco debe caber la duracion completa.
    slots: List[str] = []
    current = start_dt
    tzinfo = ZoneInfo(booking_cfg["timezone"])
    now_local = timeutils._utc_now().astimezone(tzinfo)
    break_intervals = _break_intervals_from_windows(booking_cfg.get("break_windows", []))
    while current + timedelta(minutes=span) <= end_dt:
        slot = current.strftime("%H:%M")
        slot_start_min = textnorm._time_to_min(slot)
        slot_end_min = (slot_start_min + span) if slot_start_min is not None else None
        slot_start_local = current.replace(tzinfo=tzinfo)
        overlaps_break = (
            slot_start_min is not None
            and slot_end_min is not None
            and _interval_overlaps(slot_start_min, slot_end_min, break_intervals)
        )
        if not overlaps_break and (selected_day.date() != now_local.date() or slot_start_local > now_local):
            slots.append(slot)
        current += timedelta(minutes=slot_minutes)

    return slots


async def _available_slots_for_day(
    cliente_id: str, fecha: str, *, employee_id: str = "", duration_minutes: Optional[int] = None
) -> List[str]:
    return _build_slots_for_day(cliente_id, fecha, employee_id=employee_id, duration_minutes=duration_minutes)


def _break_intervals_from_windows(windows: Any) -> List[Tuple[int, int]]:
    intervals: List[Tuple[int, int]] = []
    for raw in windows or []:
        start_value, end_value, _ = textnorm._break_window_values(raw)
        start_min = textnorm._time_to_min(start_value)
        end_min = textnorm._time_to_min(end_value)
        if start_min is not None and end_min is not None and start_min < end_min:
            intervals.append((start_min, end_min))
    return intervals


def _booking_row_duration_min(row: sqlite3.Row, cliente_id: str) -> int:
    start_at, end_at = row["start_at"], row["end_at"]
    if start_at and end_at:
        try:
            ds = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
            de = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
            minutes = int((de - ds).total_seconds() // 60)
            if minutes > 0:
                return minutes
        except ValueError:
            pass
    return _service_duration_minutes(cliente_id, row["servicio"] or "")


def _booking_catalog_service_row(row: sqlite3.Row, cliente_id: str) -> Optional[sqlite3.Row]:
    service_id = ""
    try:
        service_id = row["service_id"] or ""
    except (KeyError, IndexError):
        service_id = ""
    if service_id:
        service_row = _get_service_row(cliente_id, service_id)
        if service_row is not None:
            return service_row
    return _find_service_by_name(cliente_id, row["servicio"] or "")


def _booking_display_service_meta(row: sqlite3.Row, cliente_id: str) -> Dict[str, Any]:
    service_row = _booking_catalog_service_row(row, cliente_id)
    if service_row is not None:
        price_cents = int(service_row["price_cents"] or 0)
        return {
            "service_id": service_row["slug"] or "",
            "service_duration_minutes": int(service_row["duration_minutes"] or 0),
            "service_price_cents": price_cents,
            "service_price_label": textnorm._format_price_cents(price_cents),
        }
    price_cents = int(row["service_price_cents"] or 0)
    return {
        "service_id": row["service_id"] or "",
        "service_duration_minutes": _booking_row_duration_min(row, cliente_id),
        "service_price_cents": price_cents,
        "service_price_label": textnorm._format_price_cents(price_cents),
    }


def _booked_intervals(
    cliente_id: str, fecha: str, *, employee_id: str = "", exclude_booking_id: str = ""
) -> List[Tuple[int, int]]:
    intervals: List[Tuple[int, int]] = []
    for row in _active_booking_rows_for_day(cliente_id, fecha, employee_id=employee_id):
        if exclude_booking_id and row["id"] == exclude_booking_id:
            continue
        start_min = textnorm._time_to_min(row["booking_time"])
        if start_min is None:
            continue
        intervals.append((start_min, start_min + _booking_row_duration_min(row, cliente_id)))
    return intervals


def _blocked_intervals(cliente_id: str, fecha: str, *, employee_id: str = "") -> List[Tuple[int, int]]:
    intervals: List[Tuple[int, int]] = []
    for row in _list_agenda_blocks(
        cliente_id,
        employee_id=employee_id or "",
        include_general=bool(employee_id),
        date_from=fecha,
        date_to=fecha,
    ):
        start_min = textnorm._time_to_min(row["start_time"])
        end_min = textnorm._time_to_min(row["end_time"])
        if start_min is None or end_min is None:
            continue
        intervals.append((start_min, end_min))
    return intervals


def _interval_overlaps(start_min: int, end_min: int, intervals: List[Tuple[int, int]]) -> bool:
    return any(start_min < iv_end and end_min > iv_start for iv_start, iv_end in intervals)


def _booked_slots(
    cliente_id: str,
    fecha: str,
    *,
    employee_id: str = "",
    exclude_booking_id: str = "",
) -> Set[str]:
    with db._get_db_connection() as connection:
        clauses = [
            "cliente_id = ?",
            "booking_date = ?",
            "status IN ('confirmed', 'pending_review', 'pending_payment')",
        ]
        params: List[Any] = [cliente_id, fecha]
        if employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        if exclude_booking_id:
            clauses.append("id <> ?")
            params.append(exclude_booking_id)
        rows = connection.execute(
            "SELECT booking_time FROM bookings WHERE " + " AND ".join(clauses),
            tuple(params),
        ).fetchall()

    occupied = {row["booking_time"] for row in rows}

    return occupied


def _active_booking_rows_for_day(cliente_id: str, fecha: str, *, employee_id: str = "") -> List[sqlite3.Row]:
    with db._get_db_connection() as connection:
        clauses = [
            "cliente_id = ?",
            "booking_date = ?",
            "status IN ('confirmed', 'pending_review', 'pending_payment')",
        ]
        params: List[Any] = [cliente_id, fecha]
        if employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        return connection.execute(
            "SELECT * FROM bookings WHERE " + " AND ".join(clauses) + " ORDER BY booking_time ASC",
            tuple(params),
        ).fetchall()


def _booking_conflict_message(rows: List[sqlite3.Row], prefix: str) -> str:
    examples = ", ".join(
        f"{row['booking_date']} {row['booking_time']} ({row['nombre'] or row['email'] or row['id']})"
        for row in rows[:3]
    )
    suffix = f" Citas afectadas: {examples}." if examples else ""
    if len(rows) > 3:
        suffix += f" Y {len(rows) - 3} mas."
    return f"{prefix}{suffix}"


def _booking_conflict_items(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    now_dt = timeutils._utc_now()
    for row in rows[:12]:
        start_at = timeutils._from_utc_iso(row["start_at"] or "")
        status_value = str(row["status"] or "")
        can_reschedule = status_value not in {"cancelled", "completed", "no_show"} and not (start_at and start_at < now_dt)
        items.append(
            {
                "booking_id": row["id"],
                "nombre": row["nombre"] or row["email"] or "Cita",
                "email": row["email"] or "",
                "telefono": row["telefono"] or "",
                "servicio": row["servicio"] or "Consulta",
                "fecha": row["booking_date"],
                "hora": row["booking_time"],
                "employee_id": row["employee_id"] or "",
                "employee_name": row["employee_name"] or "",
                "estado": status_value,
                "start_at": row["start_at"] or "",
                "end_at": row["end_at"] or "",
                "can_reschedule": can_reschedule,
            }
        )
    return items


def _schedule_conflict_detail(rows: List[sqlite3.Row], prefix: str) -> Dict[str, Any]:
    return {
        "type": "schedule_booking_conflicts",
        "message": _booking_conflict_message(rows, prefix),
        "conflicts": _booking_conflict_items(rows),
    }


def _booking_conflicts_for_block(
    cliente_id: str,
    fecha: str,
    start_time: str,
    end_time: str,
    *,
    employee_id: str = "",
) -> List[sqlite3.Row]:
    timezone_name = (
        _employee_schedule_from_row(_resolve_employee_for_booking(cliente_id, employee_id, require_active=False))["timezone"]
        if employee_id
        else clients._get_client_config(cliente_id)["booking"]["timezone"]
    )
    tzinfo = ZoneInfo(timezone_name)
    block_start = datetime.strptime(f"{fecha} {start_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tzinfo)
    block_end = datetime.strptime(f"{fecha} {end_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tzinfo)
    conflicts: List[sqlite3.Row] = []
    for row in _active_booking_rows_for_day(cliente_id, fecha, employee_id=employee_id):
        booking_start, booking_end = _booking_start_end(
            cliente_id,
            row["booking_date"],
            row["booking_time"],
            employee_id=row["employee_id"] or employee_id,
            duration_minutes=_booking_row_duration_min(row, cliente_id),
        )
        if booking_start < block_end and booking_end > block_start:
            conflicts.append(row)
    return conflicts


def _booking_conflicts_for_closed_weekdays(
    cliente_id: str,
    weekdays: Set[int],
    *,
    employee_id: str = "",
) -> List[sqlite3.Row]:
    if not weekdays:
        return []
    today = timeutils._utc_now().date().isoformat()
    with db._get_db_connection() as connection:
        clauses = [
            "cliente_id = ?",
            "booking_date >= ?",
            "status IN ('confirmed', 'pending_review', 'pending_payment')",
        ]
        params: List[Any] = [cliente_id, today]
        if employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        rows = connection.execute(
            "SELECT * FROM bookings WHERE " + " AND ".join(clauses) + " ORDER BY booking_date ASC, booking_time ASC",
            tuple(params),
        ).fetchall()
    conflicts: List[sqlite3.Row] = []
    for row in rows:
        try:
            weekday = datetime.strptime(row["booking_date"], "%Y-%m-%d").weekday()
        except ValueError:
            continue
        if weekday in weekdays:
            conflicts.append(row)
    return conflicts


def _booking_conflicts_for_break_windows(
    cliente_id: str,
    break_windows: List[Dict[str, str]],
    *,
    employee_id: str = "",
) -> List[sqlite3.Row]:
    break_intervals = _break_intervals_from_windows(break_windows)
    if not break_intervals:
        return []
    if employee_id:
        schedule = _employee_schedule_from_row(_resolve_employee_for_booking(cliente_id, employee_id, require_active=False))
        timezone_name = schedule["timezone"]
    else:
        timezone_name = clients._get_client_config(cliente_id)["booking"].get("timezone", settings.DEFAULT_TIMEZONE)
    try:
        local_today = timeutils._utc_now().astimezone(ZoneInfo(timezone_name)).date().isoformat()
    except Exception:
        local_today = timeutils._utc_now().date().isoformat()
    now_utc = timeutils._utc_now()
    with db._get_db_connection() as connection:
        clauses = [
            "cliente_id = ?",
            "booking_date >= ?",
            "status IN ('confirmed', 'pending_review', 'pending_payment')",
        ]
        params: List[Any] = [cliente_id, local_today]
        if employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        rows = connection.execute(
            "SELECT * FROM bookings WHERE " + " AND ".join(clauses) + " ORDER BY booking_date ASC, booking_time ASC",
            tuple(params),
        ).fetchall()
    conflicts: List[sqlite3.Row] = []
    for row in rows:
        start_at = timeutils._from_utc_iso(row["start_at"] or "")
        if start_at and start_at < now_utc:
            continue
        start_min = textnorm._time_to_min(row["booking_time"])
        if start_min is None:
            continue
        end_min = start_min + _booking_row_duration_min(row, cliente_id)
        if _interval_overlaps(start_min, end_min, break_intervals):
            conflicts.append(row)
    return conflicts


def _blocked_slots(cliente_id: str, fecha: str, *, employee_id: str = "") -> Set[str]:
    available_slots = _build_slots_for_day(cliente_id, fecha, employee_id=employee_id)
    if not available_slots:
        return set()
    employee_row = _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    slot_minutes = int(_employee_schedule_from_row(employee_row)["slot_minutes"])
    blocked: Set[str] = set()
    rows = _list_agenda_blocks(
        cliente_id,
        employee_id=employee_id or "",
        include_general=bool(employee_id),
        date_from=fecha,
        date_to=fecha,
    )
    for row in rows:
        block_start = textnorm._parse_time(row["start_time"])
        block_end = textnorm._parse_time(row["end_time"])
        for slot in available_slots:
            slot_start = textnorm._parse_time(slot)
            slot_end = slot_start + timedelta(minutes=slot_minutes)
            if slot_start < block_end and slot_end > block_start:
                blocked.add(slot)
    return blocked


async def _booking_slot_available(
    cliente_id: str, fecha: str, hora: str, *, employee_id: str = "", duration_minutes: Optional[int] = None
) -> bool:
    employee_row = _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    dur = int(duration_minutes or _employee_schedule_from_row(employee_row)["slot_minutes"])
    start_min = textnorm._time_to_min(hora)
    if start_min is None:
        return False
    grid = await _available_slots_for_day(cliente_id, fecha, employee_id=employee_id, duration_minutes=dur)
    if hora not in grid:
        return False
    end_min = start_min + dur
    return not (
        _interval_overlaps(start_min, end_min, _booked_intervals(cliente_id, fecha, employee_id=employee_id))
        or _interval_overlaps(start_min, end_min, _blocked_intervals(cliente_id, fecha, employee_id=employee_id))
    )


async def _employee_slot_sets_for_day(
    cliente_id: str,
    fecha: str,
    *,
    employee_row: Optional[sqlite3.Row] = None,
    employee_id: str = "",
    servicio: str = "",
    duration_minutes: Optional[int] = None,
    exclude_booking_id: str = "",
) -> Tuple[Set[str], Set[str]]:
    employee = employee_row or _resolve_employee_for_booking(cliente_id, employee_id)
    dur = int(duration_minutes or _service_duration_minutes(cliente_id, textnorm._sanitize_text(servicio), employee))
    slots = await _available_slots_for_day(
        cliente_id,
        fecha,
        employee_id=employee["id"],
        duration_minutes=dur,
    )
    booked = _booked_intervals(
        cliente_id,
        fecha,
        employee_id=employee["id"],
        exclude_booking_id=exclude_booking_id,
    )
    blocked = _blocked_intervals(cliente_id, fecha, employee_id=employee["id"])
    available: Set[str] = set()
    for slot in slots:
        start_min = textnorm._time_to_min(slot)
        if start_min is None:
            continue
        end_min = start_min + dur
        if not _interval_overlaps(start_min, end_min, booked) and not _interval_overlaps(start_min, end_min, blocked):
            available.add(slot)
    return set(slots), available


async def _booking_slot_available_for_reschedule(
    cliente_id: str,
    fecha: str,
    hora: str,
    *,
    employee_id: str = "",
    exclude_booking_id: str,
    duration_minutes: Optional[int] = None,
) -> bool:
    employee_row = _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    dur = int(duration_minutes or _employee_schedule_from_row(employee_row)["slot_minutes"])
    start_min = textnorm._time_to_min(hora)
    if start_min is None:
        return False
    grid = await _available_slots_for_day(cliente_id, fecha, employee_id=employee_id, duration_minutes=dur)
    if hora not in grid:
        return False
    end_min = start_min + dur
    return not (
        _interval_overlaps(
            start_min, end_min,
            _booked_intervals(cliente_id, fecha, employee_id=employee_id, exclude_booking_id=exclude_booking_id),
        )
        or _interval_overlaps(start_min, end_min, _blocked_intervals(cliente_id, fecha, employee_id=employee_id))
    )


def _extract_services_from_info(cliente_id: str) -> List[Dict[str, Any]]:
    ruta_info = settings.DATA_DIR / cliente_id / "info.txt"
    if not ruta_info.exists():
        return []

    contenido = ruta_info.read_text(encoding="utf-8")
    servicios: List[Dict[str, str]] = []
    en_seccion = False
    current: Optional[Dict[str, str]] = None
    current_category = ""

    def start_service(nombre: str) -> None:
        nonlocal current
        service_id = _normalize_service_id(nombre)
        if not service_id:
            current = None
            return
        current = {"id": service_id, "nombre": nombre.strip(), "descripcion": "", "price_cents": 0, "duration_minutes": 0}
        if current_category:
            current["descripcion"] = f"Categoria: {current_category}"
        servicios.append(current)

    def append_detail(label: str, text: str) -> None:
        if not current:
            return
        clean = textnorm._sanitize_text(str(text or ""), allow_multiline=True).strip()
        if not clean:
            return
        prefix = textnorm._sanitize_text(str(label or "")).strip()
        prefix_lower = prefix.lower()
        if ("precio" in prefix_lower or "tarifa" in prefix_lower) and not current.get("price_cents"):
            cents = textnorm._parse_price_to_cents(clean)
            if cents:
                current["price_cents"] = cents
        if ("duracion" in prefix_lower or "duración" in prefix_lower) and not current.get("duration_minutes"):
            minutes = textnorm._parse_duration_minutes_text(clean)
            if minutes:
                current["duration_minutes"] = minutes
        detail = f"{prefix}: {clean}" if prefix else clean
        existing = str(current.get("descripcion") or "").strip()
        current["descripcion"] = f"{existing}\n{detail}".strip() if existing else detail

    def start_compact_service(raw_text: str) -> bool:
        """Soporta lineas compactas frecuentes del scraper:
        '- Masaje / 60€ / 55 min', '- Masaje - Desde 35€ - 1h',
        '- Masaje: 60€ · 55 min'. Los bloques numerados con detalles debajo
        siguen pasando por start_service() + append_detail().
        """
        raw = str(raw_text or "").strip()
        if not raw:
            return False
        known_detail_labels = {
            "precio", "tarifa", "coste", "duracion", "duración", "descripcion",
            "descripción", "detalle", "incluye", "ideal para", "para quien",
        }
        parts: List[str] = []
        colon_match = re.match(r"^([^:]{2,90}):\s*(.+)$", raw)
        if colon_match and colon_match.group(1).strip().lower() not in known_detail_labels:
            parts = [colon_match.group(1).strip(), colon_match.group(2).strip()]
        else:
            parts = [
                p.strip()
                for p in re.split(r"\s*(?:/|\||·|•|–|—|\s+-\s+)\s*", raw)
                if p.strip()
            ]
        if len(parts) < 2:
            return False
        nombre = parts[0]
        if not nombre or nombre.lower() in known_detail_labels:
            return False
        price_part = next((p for p in parts[1:] if textnorm._parse_price_to_cents(p)), "")
        duration_part = next((p for p in parts[1:] if textnorm._parse_duration_minutes_text(p)), "")
        raw_lower = raw.lower()
        if (
            not duration_part
            and "%" in raw
            and any(marker in raw_lower for marker in ("bono", "bonos", "descuento", "dto"))
        ):
            return False
        # Evita convertir bullets descriptivos largos en servicios.
        if not price_part and not duration_part:
            return False
        start_service(nombre)
        if not current:
            return False
        if price_part:
            current["price_cents"] = textnorm._parse_price_to_cents(price_part)
        if duration_part:
            current["duration_minutes"] = textnorm._parse_duration_minutes_text(duration_part)
        details = [p for p in parts[1:] if p not in {price_part, duration_part}]
        compact_bits = []
        if price_part:
            compact_bits.append(f"Precio: {price_part}")
        if duration_part:
            compact_bits.append(f"Duracion: {duration_part}")
        compact_bits.extend(details)
        if compact_bits:
            append_detail("", " / ".join(compact_bits))
        return True

    for linea in contenido.splitlines():
        valor = linea.strip()
        lower = valor.lower()

        if not valor:
            continue

        if lower.startswith("servicios y precios"):
            en_seccion = True
            continue

        if en_seccion and valor.endswith(":") and valor.upper() == valor and len(valor) > 3:
            break

        if not en_seccion:
            continue

        numbered_match = re.match(r"^\d+[\.)]\s+(.+)$", valor)
        if numbered_match:
            start_service(numbered_match.group(1).strip())
            continue

        if valor.startswith("- Servicio:"):
            start_service(valor.split(":", 1)[1].strip())
            continue

        if valor.startswith("- ") and start_compact_service(valor[2:].strip()):
            continue

        if valor.startswith("- ") and valor.endswith(":"):
            current_category = valor[2:-1].strip()
            current = None
            continue

        if lower.startswith("- descripcion:") or lower.startswith("- descripción:"):
            append_detail("Descripcion", valor.split(":", 1)[1].strip())
            continue

        detail_match = re.match(r"^-\s*([^:]{1,60}):\s*(.+)$", valor)
        if detail_match:
            append_detail(detail_match.group(1).strip(), detail_match.group(2).strip())
            continue

        if valor.startswith("- "):
            append_detail("", valor[2:].strip())
            continue

        if valor and current:
            append_detail("", valor)
            continue

    unique: Dict[str, Dict[str, str]] = {}
    for servicio in servicios:
        servicio["descripcion"] = textnorm._sanitize_text(servicio.get("descripcion", ""), allow_multiline=True)[:800]
        unique[servicio["id"]] = servicio

    return list(unique.values())


def _services_for_employee(cliente_id: str, employee_row: Optional[sqlite3.Row]) -> List[Dict[str, Any]]:
    services = _catalog_services(cliente_id)
    if not employee_row:
        return services
    service_ids = _employee_service_ids_from_row(employee_row, cliente_id)
    if not service_ids:
        return services
    allowed = set(service_ids)
    return [service for service in services if str(service.get("id") or "") in allowed]


def _service_name_allowed_for_employee(cliente_id: str, employee_row: sqlite3.Row, service_name: str) -> bool:
    normalized_name = textnorm._sanitize_text(service_name)
    if not normalized_name:
        return True
    if not _employee_service_ids_from_row(employee_row, cliente_id):
        return True
    allowed_services = _services_for_employee(cliente_id, employee_row)
    if not allowed_services:
        return not _catalog_services(cliente_id)
    return any(textnorm._sanitize_text(service.get("nombre")) == normalized_name for service in allowed_services)


async def _public_slot_sets_for_day(
    cliente_id: str,
    fecha: str,
    *,
    servicio: str = "",
) -> Tuple[Set[str], Set[str]]:
    all_slots: Set[str] = set()
    available_slots: Set[str] = set()
    for employee_row in _list_public_employee_rows(cliente_id, include_inactive=False):
        if servicio and not _service_name_allowed_for_employee(cliente_id, employee_row, servicio):
            continue
        employee_slots, employee_available = await _employee_slot_sets_for_day(
            cliente_id,
            fecha,
            employee_row=employee_row,
            servicio=servicio,
        )
        all_slots.update(employee_slots)
        available_slots.update(employee_available)
    return all_slots, available_slots


async def _resolve_public_booking_employee(
    cliente_id: str,
    fecha: str,
    hora: str,
    *,
    employee_id: str = "",
    servicio: str = "",
) -> sqlite3.Row:
    if employee_id:
        employee_row = _resolve_employee_for_booking(cliente_id, employee_id)
        if bool(employee_row["is_default"]):
            raise HTTPException(status_code=400, detail="La agenda general no se puede seleccionar desde el formulario.")
        if servicio and not _service_name_allowed_for_employee(cliente_id, employee_row, servicio):
            raise HTTPException(
                status_code=400,
                detail="El servicio seleccionado no esta disponible para ese profesional.",
            )
        return employee_row

    candidates = [
        row
        for row in _list_public_employee_rows(cliente_id, include_inactive=False)
        if not servicio or _service_name_allowed_for_employee(cliente_id, row, servicio)
    ]
    if not candidates:
        raise HTTPException(
            status_code=409,
            detail="No hay profesionales disponibles para ese servicio en este momento.",
        )

    available_candidates: List[sqlite3.Row] = []
    for row in candidates:
        dur = _service_duration_minutes(cliente_id, servicio, row)
        if await _booking_slot_available(cliente_id, fecha, hora, employee_id=row["id"], duration_minutes=dur):
            available_candidates.append(row)

    if not available_candidates:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese horario ya no esta disponible. Elige otro tramo.",
        )

    return secrets.choice(available_candidates)


def _agenda_block_reasons_for_day(cliente_id: str, fecha: str) -> List[str]:
    reasons: List[str] = []
    try:
        with db._get_db_connection() as connection:
            rows = connection.execute(
                """
                SELECT reason, start_time, end_time
                FROM agenda_blocks
                WHERE cliente_id = ? AND block_date = ?
                ORDER BY start_time ASC
                """,
                (cliente_id, fecha),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudieron leer bloqueos de agenda %s/%s: %s", cliente_id, fecha, exc)
        return reasons
    for row in rows:
        reason = (row["reason"] or "").strip()
        rng = f"{row['start_time']}-{row['end_time']}"
        reasons.append(f"{reason} ({rng})" if reason else f"Bloqueo {rng}")
    return reasons




def _is_open_now(booking_cfg: Dict[str, Any], now_dt: datetime) -> Optional[bool]:
    try:
        day_start = booking_cfg.get("day_start") or "09:00"
        day_end = booking_cfg.get("day_end") or "18:00"
        break_windows = textnorm._normalize_break_windows(
            day_start,
            day_end,
            booking_cfg.get("break_windows", []),
            booking_cfg.get("break_start", ""),
            booking_cfg.get("break_end", ""),
        )
        closed = set(booking_cfg.get("closed_weekdays") or [])
        if now_dt.weekday() in closed:
            return False
        sh, sm = (int(x) for x in day_start.split(":"))
        eh, em = (int(x) for x in day_end.split(":"))
        start = now_dt.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = now_dt.replace(hour=eh, minute=em, second=0, microsecond=0)
        for break_window in break_windows:
            bh, bm = (int(x) for x in break_window["start"].split(":"))
            rh, rm = (int(x) for x in break_window["end"].split(":"))
            pause_start = now_dt.replace(hour=bh, minute=bm, second=0, microsecond=0)
            pause_end = now_dt.replace(hour=rh, minute=rm, second=0, microsecond=0)
            if pause_start <= now_dt < pause_end:
                return False
        return start <= now_dt <= end
    except Exception:
        return None


