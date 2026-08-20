"""Agenda interna multi-tenant: empleados, servicios, horarios y disponibilidad (refactor F3).

La disponibilidad es por intervalos: un servicio de N min ocupa N min sobre el
grid (slot_minutes = paso) en TODOS los canales. Helpers clave:
_service_duration_minutes, _booked_intervals, _interval_overlaps.

Puntos de entrada (mapa completo en docs/MAPA_DEL_CODIGO.md):

* HUECOS: `_build_slots_for_day` es de donde salen los huecos de cualquier canal.
  El horario que aplica lo resuelve `_weekly_schedule_matrix`, que tambien
  alimenta los prompts de chat y voz para que no puedan contradecirse.
* CATALOGO: la tabla `services` se serializa SIEMPRE por `_service_row_to_public`
  (panel, widget, central y WhatsApp beben de ahi). Al anadir una columna hay que
  tocar ese serializador ademas de los modelos y el alta/edicion.
* DESDE EL TEXTO DEL NEGOCIO: `_extract_services_from_info` lee el info.txt DEL
  DISCO (no el texto que le pases) y `_sync_services_from_info` lo vuelca a la
  tabla. CUIDADO con `deactivate_missing=True`: apaga todo servicio que no salga
  en ese texto y ya borro el catalogo de un cliente real. Solo para altas nuevas.
"""
from __future__ import annotations

import copy
import json
import re
import secrets
import sqlite3
import unicodedata
from datetime import datetime, timedelta
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
    PortalLocationPayload,
    PortalLocationPublic,
    PortalLocationsResponse,
    PortalResourcePayload,
    PortalResourcePublic,
    PortalSchedulePublic,
    PortalScheduleUpdatePayload,
    ServiceLocationOverrideItem,
    ServiceLocationOverridePayload,
    ServiceLocationsResponse,
)
from backend import appstate, clients, db, emailing, messaging, settings, textnorm, timeutils

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
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT slug, name FROM services WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchall()
    if rows:
        return {
            str(row["slug"]): {"id": str(row["slug"]), "nombre": str(row["name"])}
            for row in rows
            if row["slug"] and row["name"]
        }
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
    booking_row = config.get("booking", {})
    break_windows = textnorm._normalize_break_windows(
        booking_row.get("day_start", "09:00"),
        booking_row.get("day_end", "18:00"),
        booking_row.get("break_windows", []),
        booking_row.get("break_start", ""),
        booking_row.get("break_end", ""),
    )
    break_start, break_end = textnorm._first_break_pair(break_windows)
    return {
        "timezone": booking_row.get("timezone", settings.DEFAULT_TIMEZONE),
        "slot_minutes": int(booking_row.get("slot_minutes", 30)),
        "day_start": booking_row.get("day_start", "09:00"),
        "day_end": booking_row.get("day_end", "18:00"),
        "break_start": break_start,
        "break_end": break_end,
        "break_windows": break_windows,
        "closed_weekdays": _normalize_closed_weekdays_list(booking_row.get("closed_weekdays", [])),
        "weekly_hours": textnorm._normalize_weekly_hours(booking_row.get("weekly_hours", {})),
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
                        break_windows_json, closed_weekdays_json, weekly_hours_json,
                        service_ids_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        json.dumps(defaults.get("weekly_hours", {})),
                        "[]",
                        now_iso,
                        now_iso,
                    ),
                )
                row = connection.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
            if row:
                stored_weekly = row["weekly_hours_json"] if "weekly_hours_json" in row.keys() else "{}"
                expected_weekly = json.dumps(defaults.get("weekly_hours", {}))
                if (stored_weekly or "{}") != expected_weekly:
                    connection.execute(
                        "UPDATE employees SET weekly_hours_json = ?, updated_at = ? WHERE id = ?",
                        (expected_weekly, now_iso, row["id"]),
                    )
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


def _list_employee_rows(
    cliente_id: str,
    *,
    include_inactive: bool = True,
    location_id: str = "",
) -> List[sqlite3.Row]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if not include_inactive:
        clauses.append("is_active = 1")
    if location_id:
        clauses.append("location_id = ?")
        params.append(location_id)
    sql = (
        "SELECT * FROM employees WHERE "
        + " AND ".join(clauses)
        # `sort_order` lo fija el negocio; a igualdad (todos 0, que es el default)
        # se mantiene el orden alfabetico de siempre.
        + " ORDER BY is_default DESC, is_active DESC, sort_order ASC, name COLLATE NOCASE ASC"
    )
    with db._get_db_connection() as connection:
        return connection.execute(sql, tuple(params)).fetchall()


def _list_public_employee_rows(
    cliente_id: str,
    *,
    include_inactive: bool = False,
    location_id: str = "",
) -> List[sqlite3.Row]:
    rows = _list_employee_rows(cliente_id, include_inactive=include_inactive, location_id=location_id)
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
        "cancel_free_hours": _row_int_or_none(row, "cancel_free_hours"),
        "cancel_late_fee_pct": _row_int_or_none(row, "cancel_late_fee_pct"),
        "no_show_fee_pct": _row_int_or_none(row, "no_show_fee_pct"),
        "image_url": _row_str_or_empty(row, "image_url"),
        "category": _row_str_or_empty(row, "category"),
        "booking_note": _row_str_or_empty(row, "booking_note"),
        "gaps": _service_gaps_from_row(row),
    }


def _service_gaps_from_row(row: sqlite3.Row) -> List[Dict[str, int]]:
    """Tramos trabajo/espera del servicio, saneados. Vacio = ocupa su rango entero."""
    crudo = _row_str_or_empty(row, "gap_json")
    if not crudo:
        return []
    try:
        tramos = json.loads(crudo)
    except (ValueError, TypeError):
        return []
    if not isinstance(tramos, list):
        return []
    limpios: List[Dict[str, int]] = []
    for tramo in tramos:
        if not isinstance(tramo, dict):
            continue
        try:
            limpios.append({
                "activo": max(0, int(tramo.get("activo") or 0)),
                "espera": max(0, int(tramo.get("espera") or 0)),
            })
        except (TypeError, ValueError):
            continue
    return limpios


def _row_str_or_empty(row: sqlite3.Row, key: str) -> str:
    try:
        return str(row[key] or "")
    except (KeyError, IndexError):
        return ""


def _row_int_or_none(row: sqlite3.Row, key: str) -> Optional[int]:
    try:
        value = row[key]
    except (KeyError, IndexError):
        return None
    return None if value is None else int(value)


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


def _sync_services_from_info(
    cliente_id: str,
    info_txt: str = "",
    *,
    deactivate_missing: bool = False,
) -> Dict[str, int]:
    """Crea/actualiza en la tabla services los servicios detectados en info.txt.

    Por defecto no elimina servicios existentes: puede haber ajustes manuales,
    overrides por centro o servicios temporales que no conviene borrar durante
    un scrapeo incremental. Los rebrains que reemplazan el conocimiento pueden
    pasar deactivate_missing=True para ocultar servicios antiguos.
    """
    seeded = _extract_services_from_info(cliente_id)
    if not seeded:
        return {"created": 0, "updated": 0, "detected": 0}

    now = timeutils._utc_now_iso()
    created = 0
    updated = 0
    with db._get_db_connection() as connection:
        seen_slugs: Set[str] = set()
        for idx, svc in enumerate(seeded):
            slug = _normalize_service_id(svc.get("nombre") or svc.get("id") or "")
            if not slug:
                continue
            seen_slugs.add(slug)
            name = textnorm._sanitize_text(svc.get("nombre") or slug)[:160]
            description = textnorm._sanitize_text(
                svc.get("descripcion") or "", allow_multiline=True
            )[:800]
            duration = int(svc.get("duration_minutes") or 0) or 30
            price_cents = max(0, int(svc.get("price_cents") or 0))
            existing = connection.execute(
                "SELECT slug FROM services WHERE cliente_id = ? AND slug = ? LIMIT 1",
                (cliente_id, slug),
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE services
                    SET name = ?, duration_minutes = ?, price_cents = ?,
                        description = ?, is_active = 1, updated_at = ?
                    WHERE cliente_id = ? AND slug = ?
                    """,
                    (name, duration, price_cents, description, now, cliente_id, slug),
                )
                updated += 1
            else:
                connection.execute(
                    """
                    INSERT INTO services
                    (cliente_id, slug, name, duration_minutes, price_cents, description,
                     is_active, sort_order, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        cliente_id,
                        slug,
                        name,
                        duration,
                        price_cents,
                        description,
                        idx,
                        now,
                        now,
                    ),
                )
                created += 1
        if deactivate_missing and seen_slugs:
            placeholders = ",".join("?" for _ in seen_slugs)
            connection.execute(
                f"""
                UPDATE services
                SET is_active = 0, updated_at = ?
                WHERE cliente_id = ?
                  AND slug NOT IN ({placeholders})
                """,
                (now, cliente_id, *sorted(seen_slugs)),
            )
        connection.commit()
    return {"created": created, "updated": updated, "detected": len(seeded)}


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


def _service_overrides_for_location(cliente_id: str, location_id: str) -> Dict[str, sqlite3.Row]:
    """Overrides de catalogo por centro (overlay): slug -> fila de override."""
    if not location_id:
        return {}
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM service_location_overrides WHERE cliente_id = ? AND location_id = ?",
            (cliente_id, location_id),
        ).fetchall()
    return {row["service_slug"]: row for row in rows}


def _apply_service_override(public: Dict[str, Any], override: Optional[sqlite3.Row]) -> Dict[str, Any]:
    if override is None:
        return public
    if override["price_cents"] is not None:
        price_cents = int(override["price_cents"])
        public["price_cents"] = price_cents
        public["price_label"] = textnorm._format_price_cents(price_cents)
    if override["duration_minutes"] is not None and int(override["duration_minutes"]) > 0:
        public["duration_minutes"] = int(override["duration_minutes"])
    return public


def _catalog_services(
    cliente_id: str, *, include_inactive: bool = False, location_id: str = ""
) -> List[Dict[str, Any]]:
    overrides = _service_overrides_for_location(cliente_id, location_id)
    items: List[Dict[str, Any]] = []
    for row in _list_service_rows(cliente_id, include_inactive=include_inactive):
        override = overrides.get(row["slug"])
        if override is not None and not bool(override["is_available"]):
            continue
        items.append(_apply_service_override(_service_row_to_public(row), override))
    return items


def _get_service_override(cliente_id: str, slug: str, location_id: str) -> Optional[sqlite3.Row]:
    if not location_id or not slug:
        return None
    with db._get_db_connection() as connection:
        return connection.execute(
            """
            SELECT * FROM service_location_overrides
            WHERE cliente_id = ? AND service_slug = ? AND location_id = ?
            LIMIT 1
            """,
            (cliente_id, slug, location_id),
        ).fetchone()


def _service_price_cents_resolved(
    cliente_id: str, service_row: Optional[sqlite3.Row], location_id: str = ""
) -> int:
    """Precio efectivo de un servicio: override del centro si existe, si no el base."""
    if service_row is None:
        return 0
    override = _get_service_override(cliente_id, service_row["slug"], location_id)
    if override is not None and override["price_cents"] is not None:
        return int(override["price_cents"])
    return int(service_row["price_cents"] or 0)


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
    if row is not None:
        # La duracion efectiva depende del centro del profesional (override por centro).
        location_id = ""
        if employee_row is not None:
            try:
                location_id = employee_row["location_id"] or ""
            except (IndexError, KeyError):
                location_id = ""
        override = _get_service_override(cliente_id, row["slug"], location_id)
        if override is not None and override["duration_minutes"] is not None and int(override["duration_minutes"]) > 0:
            return int(override["duration_minutes"])
        if int(row["duration_minutes"] or 0) > 0:
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
    try:
        raw_weekly = json.loads(row["weekly_hours_json"] or "{}")
    except (IndexError, KeyError, json.JSONDecodeError):
        raw_weekly = {}
    try:
        weekly_hours = textnorm._normalize_weekly_hours(raw_weekly)
    except Exception:  # noqa: BLE001  (dato guardado invalido: se ignora, no rompe la agenda)
        weekly_hours = {}
    return {
        "timezone": row["timezone"] or settings.DEFAULT_TIMEZONE,
        "slot_minutes": int(row["slot_minutes"] or 30),
        "day_start": row["day_start"] or "09:00",
        "day_end": row["day_end"] or "18:00",
        "break_start": break_start,
        "break_end": break_end,
        "break_windows": break_windows,
        "closed_weekdays": _employee_closed_weekdays_from_row(row),
        "weekly_hours": weekly_hours,
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
    sms_plan = bool(clients._plan_feature(cliente_id, "sms_enabled"))
    if sms_ready:
        sms_reason = "Disponible."
    elif not sms_plan:
        sms_reason = "SMS requiere plan Business."
    elif channel_status.sms.mode == "vantelia_default":
        sms_reason = "El SMS gestionado por Vantelia no esta disponible: falta configurar Twilio o el remitente global."
    else:
        sms_reason = "Configura y activa un remitente en Canales de envio."

    return {
        "email": {"available": True, "reason": "Disponible.", "label": "Email"},
        "whatsapp": {"available": whatsapp_ready, "reason": whatsapp_reason, "label": "WhatsApp"},
        "sms": {"available": sms_ready, "reason": sms_reason, "label": "SMS"},
    }


def _effective_followup_channels(cliente_id: str) -> Dict[str, Dict[str, bool]]:
    """Canales efectivos por aviso (Seguimiento), tal y como el tenant los tiene
    guardados. Es la fuente que usa el motor de envio: nunca activa un canal nuevo
    por su cuenta (sin sorpresas de coste). La recomendacion de activar WhatsApp en
    pro/business se expone aparte en el overview (campo ``recommended``) para que el
    negocio la confirme con un guardado."""
    booking_cfg = (clients._get_client_config(cliente_id).get("booking", {}) or {})
    return textnorm._normalize_message_template_channels(
        booking_cfg.get("message_template_channels") or {}
    )


def _portal_schedule_from_config(cliente_id: str) -> PortalSchedulePublic:
    config = clients._get_client_config(cliente_id)
    booking_row = config["booking"]
    break_windows = textnorm._normalize_break_windows(
        booking_row.get("day_start", "09:00"),
        booking_row.get("day_end", "18:00"),
        booking_row.get("break_windows", []),
        booking_row.get("break_start", ""),
        booking_row.get("break_end", ""),
    )
    break_start, break_end = textnorm._first_break_pair(break_windows)
    today = timeutils._utc_now().date().isoformat()
    future_limit = (timeutils._utc_now() + timedelta(days=180)).date().isoformat()
    return PortalSchedulePublic(
        enabled=bool(booking_row.get("enabled", False)),
        timezone=booking_row.get("timezone", settings.DEFAULT_TIMEZONE),
        slot_minutes=int(booking_row.get("slot_minutes", 30)),
        day_start=booking_row.get("day_start", "09:00"),
        day_end=booking_row.get("day_end", "18:00"),
        break_start=break_start,
        break_end=break_end,
        break_windows=break_windows,
        closed_weekdays=list(booking_row.get("closed_weekdays", [])),
        weekly_hours=dict(booking_row.get("weekly_hours", {}) or {}),
        message_templates=textnorm._normalize_message_templates(booking_row.get("message_templates", {})),
        message_template_enabled=textnorm._normalize_message_template_enabled(
            booking_row.get("message_template_enabled", {}),
            booking_row.get("message_templates", {}),
        ),
        message_template_channels=textnorm._normalize_message_template_channels(
            booking_row.get("message_template_channels", {})
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
    booking_row = clients._get_client_config(cliente_id)["booking"]
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
        weekly_hours=schedule.get("weekly_hours", {}),
        message_templates=textnorm._normalize_message_templates(booking_row.get("message_templates", {})),
        message_template_enabled=textnorm._normalize_message_template_enabled(
            booking_row.get("message_template_enabled", {}),
            booking_row.get("message_templates", {}),
        ),
        message_template_channels=textnorm._normalize_message_template_channels(
            booking_row.get("message_template_channels", {})
        ),
        reminder_channel_availability=_reminder_channel_availability(cliente_id),
        blocks=[
            _serialize_agenda_block(block)
            for block in _list_agenda_blocks(
                cliente_id,
                employee_id=employee_id,
                # Los bloqueos generales (vacaciones/festivos del negocio) tambien
                # afectan a este profesional: se listan junto a los suyos para que
                # el calendario filtrado por profesional no los pierda.
                include_general=True,
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
    booking_row = dict(config.get("booking", {}))
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
        "weekly_hours",
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
        weekly_hours = (
            textnorm._normalize_weekly_hours(data.weekly_hours)
            if "weekly_hours" in fields_set
            else dict(config.get("booking", {}).get("weekly_hours", {}) or {})
        )
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
                        "Hay citas activas en los días que quieres cerrar. Cancélalas o reprográmalas antes de guardar.",
                    ),
                )
        previous_break_windows = textnorm._normalize_break_windows(
            config.get("booking", {}).get("day_start", "09:00"),
            config.get("booking", {}).get("day_end", "18:00"),
            config.get("booking", {}).get("break_windows", []),
            config.get("booking", {}).get("break_start", ""),
            config.get("booking", {}).get("break_end", ""),
        )
        try:
            default_employee_id = _default_employee_row(cliente_id)["id"]
        except HTTPException:
            default_employee_id = ""
        previous_start = config.get("booking", {}).get("day_start", "09:00")
        previous_end = config.get("booking", {}).get("day_end", "18:00")
        if (start, end) != (previous_start, previous_end):
            conflicts = _booking_conflicts_outside_schedule(
                cliente_id,
                start,
                end,
                employee_id=default_employee_id,
            )
            if conflicts:
                raise HTTPException(
                    status_code=409,
                    detail=_schedule_conflict_detail(
                        conflicts,
                        "Hay citas activas fuera del nuevo horario. Cancelalas o reprogramalas antes.",
                    ),
                )
        if break_windows != previous_break_windows and break_windows:
            # El descanso general aplica a TODO el equipo: valida contra las citas
            # de todos los profesionales, no solo la agenda general.
            conflicts = _booking_conflicts_for_break_windows(
                cliente_id,
                break_windows,
                employee_id="",
            )
            if conflicts:
                raise HTTPException(
                    status_code=409,
                    detail=_schedule_conflict_detail(
                        conflicts,
                        "Hay citas activas dentro del descanso que quieres guardar. Cancelalas o reprogramalas antes.",
                    ),
                )
        booking_row.update(
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
                "weekly_hours": weekly_hours,
            }
        )
    if data.message_templates is not None:
        booking_row["message_templates"] = textnorm._normalize_message_templates(data.message_templates)
    if data.message_template_enabled is not None:
        booking_row["message_template_enabled"] = textnorm._normalize_message_template_enabled(
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
        booking_row["message_template_channels"] = channels
    config["booking"] = booking_row
    clients._validate_single_client_runtime(cliente_id, config)
    clients._persist_configs_to_disk(next_configs)
    if should_update_schedule:
        with db._get_db_connection() as connection:
            connection.execute(
                """
                UPDATE employees
                SET timezone = ?, slot_minutes = ?, day_start = ?, day_end = ?,
                    break_start = ?, break_end = ?, break_windows_json = ?,
                    closed_weekdays_json = ?, weekly_hours_json = ?, updated_at = ?
                WHERE cliente_id = ? AND is_default = 1
                """,
                (
                    booking_row["timezone"],
                    int(booking_row["slot_minutes"]),
                    booking_row["day_start"],
                    booking_row["day_end"],
                    booking_row.get("break_start", ""),
                    booking_row.get("break_end", ""),
                    json.dumps(booking_row.get("break_windows", [])),
                    json.dumps(booking_row["closed_weekdays"]),
                    json.dumps(booking_row.get("weekly_hours", {})),
                    timeutils._utc_now_iso(),
                    cliente_id,
                ),
            )
            # El paso de la agenda (cada cuanto se ofrece cita) es del NEGOCIO, no
            # una preferencia de cada profesional: se aplica a todo el equipo. Las
            # horas, descansos y dias cerrados si son personales y se quedan como
            # estan. Sin esto, un salon ponia "citas de 15 minutos" en Horarios y
            # sus clientas seguian viendo huecos de 30, porque la disponibilidad se
            # calcula por profesional y solo cambiaba la agenda general.
            connection.execute(
                "UPDATE employees SET slot_minutes = ?, updated_at = ? WHERE cliente_id = ?",
                (int(booking_row["slot_minutes"]), timeutils._utc_now_iso(), cliente_id),
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
    schedule_fields_set = set(getattr(data, "model_fields_set", None) or getattr(data, "__fields_set__", set()))
    weekly_hours = (
        textnorm._normalize_weekly_hours(data.weekly_hours)
        if "weekly_hours" in schedule_fields_set
        else dict(_employee_schedule_from_row(row).get("weekly_hours") or {})
    )
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
                    "Hay citas activas en los días que quieres cerrar. Cancélalas o reprográmalas antes de guardar.",
                ),
            )
    previous_schedule = _employee_schedule_from_row(row)
    if (start, end) != (previous_schedule["day_start"], previous_schedule["day_end"]):
        conflicts = _booking_conflicts_outside_schedule(
            cliente_id,
            start,
            end,
            employee_id=employee_id,
        )
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail=_schedule_conflict_detail(
                    conflicts,
                    "Hay citas activas fuera del nuevo horario. Cancelalas o reprogramalas antes.",
                ),
            )
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
                closed_weekdays_json = ?, weekly_hours_json = ?, updated_at = ?
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
                json.dumps(weekly_hours),
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
        weekly_hours=schedule.get("weekly_hours", {}),
        service_ids=service_ids,
        location_id=row["location_id"] or "",
        sort_order=int((row["sort_order"] if "sort_order" in row.keys() else 0) or 0),
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
    weekly_hours = (
        textnorm._normalize_weekly_hours(data.weekly_hours)
        if "weekly_hours" in fields_set
        else dict(defaults.get("weekly_hours") or {})
    )
    service_ids = (
        _normalize_service_ids_for_client(cliente_id, data.service_ids)
        if "service_ids" in fields_set or existing_row is None
        else _employee_service_ids_from_row(existing_row, cliente_id)
    )
    if "location_id" in fields_set:
        location_id = _resolve_location_id(cliente_id, data.location_id, require_active=False)
    elif existing_row is not None and (existing_row["location_id"] or ""):
        location_id = existing_row["location_id"]
    else:
        location_id = _resolve_location_id(cliente_id, "", require_active=False)
    return {
        "name": textnorm._sanitize_text(data.name),
        "location_id": location_id,
        "sort_order": (
            max(0, int(getattr(data, "sort_order", 0) or 0))
            if "sort_order" in fields_set or existing_row is None
            else int((existing_row["sort_order"] if "sort_order" in existing_row.keys() else 0) or 0)
        ),
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
        "weekly_hours_json": json.dumps(weekly_hours),
        "weekly_hours": weekly_hours,
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
                break_windows_json, closed_weekdays_json, weekly_hours_json,
                service_ids_json, location_id, sort_order,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                payload["weekly_hours_json"],
                payload["service_ids_json"],
                payload["location_id"],
                payload["sort_order"],
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
    previous_schedule = _employee_schedule_from_row(row)
    previous_closed_weekdays = set(previous_schedule["closed_weekdays"])
    newly_closed_weekdays = set(payload["closed_weekdays"]) - previous_closed_weekdays
    if newly_closed_weekdays:
        conflicts = _booking_conflicts_for_closed_weekdays(
            cliente_id,
            newly_closed_weekdays,
            employee_id=employee_id,
        )
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail=_schedule_conflict_detail(
                    conflicts,
                    "Hay citas activas en los días que quieres cerrar. Cancélalas o reprográmalas antes.",
                ),
            )
    if (payload["day_start"], payload["day_end"]) != (
        previous_schedule["day_start"],
        previous_schedule["day_end"],
    ):
        conflicts = _booking_conflicts_outside_schedule(
            cliente_id,
            payload["day_start"],
            payload["day_end"],
            employee_id=employee_id,
        )
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail=_schedule_conflict_detail(
                    conflicts,
                    "Hay citas activas fuera del nuevo horario. Cancelalas o reprogramalas antes.",
                ),
            )
    previous_break_windows = previous_schedule.get("break_windows", [])
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
                break_windows_json = ?, closed_weekdays_json = ?, weekly_hours_json = ?,
                service_ids_json = ?,
                location_id = ?, sort_order = ?, updated_at = ?
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
                payload["weekly_hours_json"],
                payload["service_ids_json"],
                payload["location_id"],
                payload["sort_order"],
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
        # Si el profesional cambia de centro, sus citas se mudan con el (todas) y se
        # despega cualquier sala asignada (pertenecia al centro anterior). El profesional
        # queda solo en el centro nuevo (employees.location_id ya actualizado arriba).
        new_location = payload["location_id"] or ""
        old_location = (row["location_id"] or "")
        if new_location != old_location:
            connection.execute(
                """
                UPDATE bookings
                SET location_id = ?, resource_id = ''
                WHERE cliente_id = ? AND employee_id = ?
                """,
                (new_location, cliente_id, employee_id),
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


# ---------------------------------------------------------------------------
# Centros (locations) — soporte multi-local por cliente
# ---------------------------------------------------------------------------


def _list_location_rows(cliente_id: str, *, include_inactive: bool = True) -> List[sqlite3.Row]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if not include_inactive:
        clauses.append("is_active = 1")
    sql = (
        "SELECT * FROM locations WHERE "
        + " AND ".join(clauses)
        + " ORDER BY is_default DESC, sort_order ASC, name COLLATE NOCASE ASC"
    )
    with db._get_db_connection() as connection:
        return connection.execute(sql, tuple(params)).fetchall()


def _get_location_row(location_id: str, *, cliente_id: str = "") -> Optional[sqlite3.Row]:
    clauses = ["id = ?"]
    params: List[Any] = [location_id]
    if cliente_id:
        clauses.append("cliente_id = ?")
        params.append(cliente_id)
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM locations WHERE " + " AND ".join(clauses) + " LIMIT 1",
            tuple(params),
        ).fetchone()


def _default_location_id(cliente_id: str) -> str:
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT id FROM locations WHERE cliente_id = ? AND is_default = 1 LIMIT 1",
            (cliente_id,),
        ).fetchone()
        if row:
            return row["id"]
        row = connection.execute(
            "SELECT id FROM locations WHERE cliente_id = ? ORDER BY is_active DESC, sort_order ASC LIMIT 1",
            (cliente_id,),
        ).fetchone()
        return row["id"] if row else ""


def _resolve_location_id(cliente_id: str, location_id: str = "", *, require_active: bool = True) -> str:
    """Devuelve un id de centro valido para el cliente. Cae al centro por defecto si vacio/invalido."""
    if location_id:
        row = _get_location_row(location_id, cliente_id=cliente_id)
        if row and (not require_active or bool(row["is_active"])):
            return row["id"]
    return _default_location_id(cliente_id)


def _location_employee_count(cliente_id: str, location_id: str) -> int:
    with db._get_db_connection() as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM employees WHERE cliente_id = ? AND location_id = ?",
                (cliente_id, location_id),
            ).fetchone()[0]
        )


def _serialize_portal_location(row: sqlite3.Row) -> PortalLocationPublic:
    return PortalLocationPublic(
        location_id=row["id"],
        cliente_id=row["cliente_id"],
        name=row["name"],
        address=row["address"] or "",
        phone=row["phone"] or "",
        timezone=row["timezone"] or settings.DEFAULT_TIMEZONE,
        is_active=bool(row["is_active"]),
        is_default=bool(row["is_default"]),
        sort_order=int(row["sort_order"] or 0),
        employee_count=_location_employee_count(row["cliente_id"], row["id"]),
        resource_count=_location_room_count(row["cliente_id"], row["id"]),
        whatsapp_phone_number_id=row["whatsapp_phone_number_id"] or "",
        voice_phone_number=row["voice_phone_number"] or "",
    )


def _location_for_channel(
    cliente_id: str, *, whatsapp_phone_number_id: str = "", voice_phone_number: str = ""
) -> str:
    """Resuelve el centro por el numero del canal entrante (un numero por centro).

    Devuelve '' si el numero no esta mapeado a ningun centro: el flujo cae al
    comportamiento sin filtro (el cliente final elige o se usa el default)."""
    clauses: List[str] = []
    params: List[Any] = []
    if whatsapp_phone_number_id:
        clauses.append("whatsapp_phone_number_id = ?")
        params.append(whatsapp_phone_number_id.strip())
    if voice_phone_number:
        # Comparacion robusta a formato E.164: ignora '+' y espacios en ambos lados.
        normalized = voice_phone_number.strip().replace("+", "").replace(" ", "")
        clauses.append("REPLACE(REPLACE(voice_phone_number, '+', ''), ' ', '') = ?")
        params.append(normalized)
    if not clauses:
        return ""
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT id FROM locations WHERE cliente_id = ? AND is_active = 1 AND ("
            + " OR ".join(clauses)
            + ") LIMIT 1",
            tuple([cliente_id] + params),
        ).fetchone()
    return row["id"] if row else ""


def _portal_locations_for_client(cliente_id: str) -> PortalLocationsResponse:
    return PortalLocationsResponse(
        items=[_serialize_portal_location(row) for row in _list_location_rows(cliente_id)]
    )


def _ensure_default_locations_for_all_clients() -> None:
    """Garantiza un centro por defecto por cliente y rellena location_id en filas heredadas."""
    now_iso = timeutils._utc_now().isoformat().replace("+00:00", "Z")
    with db._get_db_connection() as connection:
        for cliente_id in list(appstate.CONFIG_CLIENTES.keys()):
            row = connection.execute(
                "SELECT * FROM locations WHERE cliente_id = ? AND is_default = 1 LIMIT 1",
                (cliente_id,),
            ).fetchone()
            if not row:
                location_id = f"loc_{secrets.token_urlsafe(8)}"
                config = clients._get_client_config(cliente_id)
                contacto = config.get("contacto") if isinstance(config.get("contacto"), dict) else {}
                booking_cfg = config.get("booking") if isinstance(config.get("booking"), dict) else {}
                connection.execute(
                    """
                    INSERT INTO locations (
                        id, cliente_id, name, address, phone, timezone,
                        is_active, is_default, sort_order, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, 1, 0, ?, ?)
                    """,
                    (
                        location_id,
                        cliente_id,
                        config.get("nombre") or cliente_id,
                        "",
                        str((contacto or {}).get("telefono", "") or ""),
                        (booking_cfg or {}).get("timezone") or settings.DEFAULT_TIMEZONE,
                        now_iso,
                        now_iso,
                    ),
                )
                row = connection.execute("SELECT * FROM locations WHERE id = ?", (location_id,)).fetchone()
            if row:
                default_id = row["id"]
                connection.execute(
                    "UPDATE employees SET location_id = ? WHERE cliente_id = ? AND (location_id = '' OR location_id IS NULL)",
                    (default_id, cliente_id),
                )
                # Citas/bloqueos heredan el centro de su profesional; el resto al centro por defecto.
                connection.execute(
                    """
                    UPDATE bookings SET location_id = (
                        SELECT location_id FROM employees WHERE employees.id = bookings.employee_id
                    )
                    WHERE cliente_id = ? AND (location_id = '' OR location_id IS NULL)
                      AND employee_id <> ''
                      AND EXISTS (SELECT 1 FROM employees WHERE employees.id = bookings.employee_id)
                    """,
                    (cliente_id,),
                )
                connection.execute(
                    "UPDATE bookings SET location_id = ? WHERE cliente_id = ? AND (location_id = '' OR location_id IS NULL)",
                    (default_id, cliente_id),
                )
                connection.execute(
                    """
                    UPDATE agenda_blocks SET location_id = (
                        SELECT location_id FROM employees WHERE employees.id = agenda_blocks.employee_id
                    )
                    WHERE cliente_id = ? AND (location_id = '' OR location_id IS NULL)
                      AND employee_id <> ''
                      AND EXISTS (SELECT 1 FROM employees WHERE employees.id = agenda_blocks.employee_id)
                    """,
                    (cliente_id,),
                )
                connection.execute(
                    "UPDATE agenda_blocks SET location_id = ? WHERE cliente_id = ? AND (location_id = '' OR location_id IS NULL)",
                    (default_id, cliente_id),
                )
        connection.commit()


def _create_portal_location(cliente_id: str, data: PortalLocationPayload) -> PortalLocationPublic:
    name = textnorm._sanitize_text(data.name)
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="El nombre del centro es obligatorio.")
    now_iso = timeutils._utc_now_iso()
    location_id = f"loc_{secrets.token_urlsafe(8)}"
    with db._get_db_connection() as connection:
        has_default = connection.execute(
            "SELECT 1 FROM locations WHERE cliente_id = ? AND is_default = 1 LIMIT 1",
            (cliente_id,),
        ).fetchone()
        next_order = connection.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM locations WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO locations (
                id, cliente_id, name, address, phone, timezone,
                is_active, is_default, sort_order,
                whatsapp_phone_number_id, voice_phone_number,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                location_id,
                cliente_id,
                name,
                textnorm._sanitize_text(data.address),
                textnorm._sanitize_text(data.phone),
                textnorm._sanitize_text(data.timezone) or settings.DEFAULT_TIMEZONE,
                1 if data.is_active else 0,
                0 if has_default else 1,
                int(next_order),
                textnorm._sanitize_text(data.whatsapp_phone_number_id),
                textnorm._sanitize_text(data.voice_phone_number),
                now_iso,
                now_iso,
            ),
        )
        connection.commit()
    return _serialize_portal_location(_get_location_row(location_id, cliente_id=cliente_id))


def _update_portal_location(cliente_id: str, location_id: str, data: PortalLocationPayload) -> PortalLocationPublic:
    row = _get_location_row(location_id, cliente_id=cliente_id)
    if not row:
        raise HTTPException(status_code=404, detail="Centro no encontrado.")
    fields_set = set(getattr(data, "model_fields_set", set()))
    name = textnorm._sanitize_text(data.name) if "name" in fields_set else (row["name"] or "")
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="El nombre del centro es obligatorio.")
    is_active = bool(data.is_active) if "is_active" in fields_set else bool(row["is_active"])
    if bool(row["is_default"]) and not is_active:
        raise HTTPException(status_code=409, detail="El centro principal no se puede desactivar.")
    if bool(row["is_active"]) and not is_active and _location_employee_count(cliente_id, location_id):
        raise HTTPException(
            status_code=409,
            detail="Este centro tiene profesionales asignados. Reasignalos a otro centro antes de desactivarlo.",
        )
    with db._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE locations
            SET name = ?, address = ?, phone = ?, timezone = ?, is_active = ?,
                whatsapp_phone_number_id = ?, voice_phone_number = ?, updated_at = ?
            WHERE id = ? AND cliente_id = ?
            """,
            (
                name,
                textnorm._sanitize_text(data.address) if "address" in fields_set else (row["address"] or ""),
                textnorm._sanitize_text(data.phone) if "phone" in fields_set else (row["phone"] or ""),
                (textnorm._sanitize_text(data.timezone) or settings.DEFAULT_TIMEZONE)
                if "timezone" in fields_set
                else (row["timezone"] or settings.DEFAULT_TIMEZONE),
                1 if is_active else 0,
                textnorm._sanitize_text(data.whatsapp_phone_number_id)
                if "whatsapp_phone_number_id" in fields_set
                else (row["whatsapp_phone_number_id"] or ""),
                textnorm._sanitize_text(data.voice_phone_number)
                if "voice_phone_number" in fields_set
                else (row["voice_phone_number"] or ""),
                timeutils._utc_now_iso(),
                location_id,
                cliente_id,
            ),
        )
        connection.commit()
    return _serialize_portal_location(_get_location_row(location_id, cliente_id=cliente_id))


def _delete_portal_location(cliente_id: str, location_id: str) -> None:
    row = _get_location_row(location_id, cliente_id=cliente_id)
    if not row:
        raise HTTPException(status_code=404, detail="Centro no encontrado.")
    if bool(row["is_default"]):
        raise HTTPException(status_code=409, detail="El centro principal no se puede eliminar.")
    if _location_employee_count(cliente_id, location_id):
        raise HTTPException(
            status_code=409,
            detail="Este centro tiene profesionales asignados. Reasignalos a otro centro antes de eliminarlo.",
        )
    with db._get_db_connection() as connection:
        connection.execute(
            "DELETE FROM locations WHERE id = ? AND cliente_id = ?",
            (location_id, cliente_id),
        )
        connection.execute(
            "DELETE FROM resources WHERE cliente_id = ? AND location_id = ?",
            (cliente_id, location_id),
        )
        connection.execute(
            "DELETE FROM service_location_overrides WHERE cliente_id = ? AND location_id = ?",
            (cliente_id, location_id),
        )
        connection.commit()


# ---------------------------------------------------------------------------
# Overrides de servicios por centro (carta/precios distintos por local)
# ---------------------------------------------------------------------------


def _set_service_location_override(
    cliente_id: str, slug: str, location_id: str, data: "ServiceLocationOverridePayload"
) -> None:
    if not _get_service_row(cliente_id, slug):
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    if not _get_location_row(location_id, cliente_id=cliente_id):
        raise HTTPException(status_code=404, detail="Centro no encontrado.")
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO service_location_overrides
                (cliente_id, service_slug, location_id, is_available, price_cents, duration_minutes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id, service_slug, location_id) DO UPDATE SET
                is_available = excluded.is_available,
                price_cents = excluded.price_cents,
                duration_minutes = excluded.duration_minutes,
                updated_at = excluded.updated_at
            """,
            (
                cliente_id,
                slug,
                location_id,
                1 if data.is_available else 0,
                data.price_cents,
                data.duration_minutes,
                timeutils._utc_now_iso(),
            ),
        )
        connection.commit()


def _delete_service_location_override(cliente_id: str, slug: str, location_id: str) -> None:
    with db._get_db_connection() as connection:
        connection.execute(
            """
            DELETE FROM service_location_overrides
            WHERE cliente_id = ? AND service_slug = ? AND location_id = ?
            """,
            (cliente_id, slug, location_id),
        )
        connection.commit()


def _service_locations_overview(cliente_id: str, slug: str) -> "ServiceLocationsResponse":
    """Vista por centro de un servicio: override + valores efectivos. Para el editor del portal."""
    service_row = _get_service_row(cliente_id, slug)
    if not service_row:
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    base_price = int(service_row["price_cents"] or 0)
    base_duration = int(service_row["duration_minutes"] or 0) or 30
    items: List[ServiceLocationOverrideItem] = []
    for loc in _list_location_rows(cliente_id):
        override = _get_service_override(cliente_id, slug, loc["id"])
        eff_price = (
            int(override["price_cents"])
            if override is not None and override["price_cents"] is not None
            else base_price
        )
        eff_duration = (
            int(override["duration_minutes"])
            if override is not None and override["duration_minutes"] is not None and int(override["duration_minutes"]) > 0
            else base_duration
        )
        items.append(
            ServiceLocationOverrideItem(
                location_id=loc["id"],
                location_name=loc["name"],
                is_default_location=bool(loc["is_default"]),
                is_available=override is None or bool(override["is_available"]),
                has_override=override is not None,
                price_cents=int(override["price_cents"]) if override is not None and override["price_cents"] is not None else None,
                duration_minutes=int(override["duration_minutes"]) if override is not None and override["duration_minutes"] is not None else None,
                effective_price_cents=eff_price,
                effective_price_label=textnorm._format_price_cents(eff_price),
                effective_duration_minutes=eff_duration,
            )
        )
    return ServiceLocationsResponse(service_slug=slug, items=items)


# ---------------------------------------------------------------------------
# Recursos (salas/carriles genericos por centro) y aforo
# ---------------------------------------------------------------------------


def _list_resource_rows(cliente_id: str, location_id: str = "", *, include_inactive: bool = True) -> List[sqlite3.Row]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if location_id:
        clauses.append("location_id = ?")
        params.append(location_id)
    if not include_inactive:
        clauses.append("is_active = 1")
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM resources WHERE " + " AND ".join(clauses)
            + " ORDER BY sort_order ASC, name COLLATE NOCASE ASC",
            tuple(params),
        ).fetchall()


def _serialize_portal_resource(row: sqlite3.Row) -> PortalResourcePublic:
    return PortalResourcePublic(
        resource_id=row["id"],
        cliente_id=row["cliente_id"],
        location_id=row["location_id"] or "",
        name=row["name"],
        is_active=bool(row["is_active"]),
        sort_order=int(row["sort_order"] or 0),
    )


def _create_portal_resource(cliente_id: str, location_id: str, data: PortalResourcePayload) -> PortalResourcePublic:
    if not _get_location_row(location_id, cliente_id=cliente_id):
        raise HTTPException(status_code=404, detail="Centro no encontrado.")
    name = textnorm._sanitize_text(data.name)
    if not name:
        raise HTTPException(status_code=400, detail="El nombre de la sala es obligatorio.")
    now_iso = timeutils._utc_now_iso()
    resource_id = f"res_{secrets.token_urlsafe(8)}"
    with db._get_db_connection() as connection:
        next_order = connection.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM resources WHERE cliente_id = ? AND location_id = ?",
            (cliente_id, location_id),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO resources (id, cliente_id, location_id, name, is_active, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (resource_id, cliente_id, location_id, name, 1 if data.is_active else 0, int(next_order), now_iso, now_iso),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
    return _serialize_portal_resource(row)


def _update_portal_resource(cliente_id: str, resource_id: str, data: PortalResourcePayload) -> PortalResourcePublic:
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM resources WHERE id = ? AND cliente_id = ? LIMIT 1",
            (resource_id, cliente_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Sala no encontrada.")
        fields_set = set(getattr(data, "model_fields_set", set()))
        name = textnorm._sanitize_text(data.name) if "name" in fields_set else (row["name"] or "")
        if not name:
            raise HTTPException(status_code=400, detail="El nombre de la sala es obligatorio.")
        is_active = bool(data.is_active) if "is_active" in fields_set else bool(row["is_active"])
        if bool(row["is_active"]) and not is_active and _active_future_bookings_for_resource(cliente_id, resource_id):
            raise HTTPException(
                status_code=409,
                detail="Esta sala tiene citas futuras activas. Reasignalas antes de desactivarla.",
            )
        connection.execute(
            "UPDATE resources SET name = ?, is_active = ?, updated_at = ? WHERE id = ? AND cliente_id = ?",
            (name, 1 if is_active else 0, timeutils._utc_now_iso(), resource_id, cliente_id),
        )
        connection.commit()
        refreshed = connection.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
    return _serialize_portal_resource(refreshed)


def _delete_portal_resource(cliente_id: str, resource_id: str) -> None:
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT id FROM resources WHERE id = ? AND cliente_id = ? LIMIT 1",
            (resource_id, cliente_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Sala no encontrada.")
        if _active_future_bookings_for_resource(cliente_id, resource_id):
            raise HTTPException(
                status_code=409,
                detail="Esta sala tiene citas futuras activas. Reasignalas antes de eliminarla.",
            )
        connection.execute("DELETE FROM resources WHERE id = ? AND cliente_id = ?", (resource_id, cliente_id))
        connection.commit()


def _active_future_bookings_for_resource(cliente_id: str, resource_id: str) -> int:
    with db._get_db_connection() as connection:
        return int(
            connection.execute(
                """
                SELECT COUNT(*) FROM bookings
                WHERE cliente_id = ? AND resource_id = ?
                  AND status IN ('confirmed', 'pending_review', 'pending_payment')
                  AND (start_at = '' OR start_at >= ?)
                """,
                (cliente_id, resource_id, timeutils._utc_now_iso()),
            ).fetchone()[0]
        )


def _location_room_count(cliente_id: str, location_id: str) -> int:
    if not location_id:
        return 0
    with db._get_db_connection() as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM resources WHERE cliente_id = ? AND location_id = ? AND is_active = 1",
                (cliente_id, location_id),
            ).fetchone()[0]
        )


def _location_booked_intervals(
    cliente_id: str, location_id: str, fecha: str, *, exclude_booking_id: str = ""
) -> List[Tuple[int, int]]:
    """Intervalos ocupados (min desde medianoche) de TODAS las citas activas del centro en el dia."""
    if not location_id:
        return []
    clauses = [
        "cliente_id = ?",
        "location_id = ?",
        "booking_date = ?",
        "status IN ('confirmed', 'pending_review', 'pending_payment')",
    ]
    params: List[Any] = [cliente_id, location_id, fecha]
    if exclude_booking_id:
        clauses.append("id <> ?")
        params.append(exclude_booking_id)
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM bookings WHERE " + " AND ".join(clauses),
            tuple(params),
        ).fetchall()
    intervals: List[Tuple[int, int]] = []
    for row in rows:
        start_min = textnorm._time_to_min(row["booking_time"])
        if start_min is None:
            continue
        intervals.append((start_min, start_min + _booking_row_duration_min(row, cliente_id)))
    return intervals


def _location_capacity_ok(
    cliente_id: str,
    location_id: str,
    fecha: str,
    start_min: int,
    end_min: int,
    *,
    exclude_booking_id: str = "",
) -> bool:
    """Aforo de salas del centro: True si hay sala libre en [start,end).

    Opt-in: un centro sin salas configuradas no limita aforo (solo limita el
    personal). Con N salas activas, como mucho N citas pueden solaparse."""
    room_count = _location_room_count(cliente_id, location_id)
    if room_count <= 0:
        return True
    overlapping = 0
    for b_start, b_end in _location_booked_intervals(
        cliente_id, location_id, fecha, exclude_booking_id=exclude_booking_id
    ):
        if start_min < b_end and b_start < end_min:
            overlapping += 1
            if overlapping >= room_count:
                return False
    return True


def _assign_free_resource(
    cliente_id: str, location_id: str, fecha: str, start_min: int, end_min: int
) -> str:
    """Asigna una sala libre del centro para el intervalo dado. '' si no hay salas configuradas."""
    rooms = _list_resource_rows(cliente_id, location_id, include_inactive=False)
    if not rooms:
        return ""
    used: Set[str] = set()
    with db._get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM bookings
            WHERE cliente_id = ? AND location_id = ? AND booking_date = ?
              AND status IN ('confirmed', 'pending_review', 'pending_payment')
              AND resource_id <> ''
            """,
            (cliente_id, location_id, fecha),
        ).fetchall()
    for row in rows:
        b_start = textnorm._time_to_min(row["booking_time"])
        if b_start is None:
            continue
        b_end = b_start + _booking_row_duration_min(row, cliente_id)
        if start_min < b_end and b_start < end_min:
            used.add(row["resource_id"])
    for room in rooms:
        if room["id"] not in used:
            return room["id"]
    return ""


def _schedule_preview_payload_from_config(cliente_id: str) -> PortalScheduleUpdatePayload:
    booking_row = clients._get_client_config(cliente_id).get("booking", {})
    break_windows = textnorm._normalize_break_windows(
        booking_row.get("day_start", "09:00"),
        booking_row.get("day_end", "18:00"),
        booking_row.get("break_windows", []),
        booking_row.get("break_start", ""),
        booking_row.get("break_end", ""),
    )
    break_start, break_end = textnorm._first_break_pair(break_windows)
    return PortalScheduleUpdatePayload(
        enabled=bool(booking_row.get("enabled", True)),
        timezone=textnorm._sanitize_text(booking_row.get("timezone", settings.DEFAULT_TIMEZONE)) or settings.DEFAULT_TIMEZONE,
        slot_minutes=int(booking_row.get("slot_minutes", 30)),
        day_start=textnorm._sanitize_text(booking_row.get("day_start", "09:00")) or "09:00",
        day_end=textnorm._sanitize_text(booking_row.get("day_end", "18:00")) or "18:00",
        break_start=break_start,
        break_end=break_end,
        break_windows=break_windows,
        closed_weekdays=_normalize_closed_weekdays_list(booking_row.get("closed_weekdays", [])),
        message_templates=textnorm._normalize_message_templates(booking_row.get("message_templates", {})),
        message_template_enabled=textnorm._normalize_message_template_enabled(
            booking_row.get("message_template_enabled", {}),
            booking_row.get("message_templates", {}),
        ),
        message_template_channels=textnorm._normalize_message_template_channels(
            booking_row.get("message_template_channels", {})
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
            detail=f"Solo se admiten reservas con hasta {settings.MAX_BOOKING_ADVANCE_DAYS} días de antelación.",
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
    # Franja del dia: override por dia de la semana si el profesional lo tiene
    # configurado (sabado corto y similares), si no la franja general.
    day_window = textnorm._weekday_hours(booking_cfg, selected_day.weekday())
    if day_window is None:
        return []
    day_start_value, day_end_value = day_window

    start_dt = datetime.combine(selected_day.date(), textnorm._parse_time(day_start_value).time())
    end_dt = datetime.combine(selected_day.date(), textnorm._parse_time(day_end_value).time())
    slot_minutes = booking_cfg["slot_minutes"]
    span = int(duration_minutes or slot_minutes) or slot_minutes

    if end_dt <= start_dt:
        raise HTTPException(status_code=500, detail="Configuracion horaria invalida para este cliente")

    # Paso del grid = slot_minutes; el hueco debe caber la duracion completa.
    slots: List[str] = []
    current = start_dt
    tzinfo = ZoneInfo(booking_cfg["timezone"])
    now_local = timeutils._utc_now().astimezone(tzinfo)
    # Descansos propios del profesional + descansos GENERALES del negocio (cierre de
    # mediodia y similares): el descanso general aplica a todo el equipo en todos los
    # canales (widget, portal, chat, voz, WhatsApp).
    break_intervals = _break_intervals_from_windows(booking_cfg.get("break_windows", []))
    break_intervals.extend(_break_intervals_from_windows(_client_break_windows(config)))
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


def _client_break_windows(config: Dict[str, Any]) -> List[Dict[str, str]]:
    """Descansos GENERALES del negocio (config['booking']), normalizados.

    Semantica: el descanso del horario general es un cierre del NEGOCIO (p.ej. parada
    de comida) y aplica a TODO el equipo ademas de los descansos propios de cada
    profesional. Los descansos escalonados por persona se configuran por profesional
    dejando el general vacio."""
    booking_row = (config or {}).get("booking") or {}
    try:
        return textnorm._normalize_break_windows(
            booking_row.get("day_start", "09:00"),
            booking_row.get("day_end", "18:00"),
            booking_row.get("break_windows", []),
            booking_row.get("break_start", ""),
            booking_row.get("break_end", ""),
        )
    except Exception:  # noqa: BLE001
        return []


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


def _booking_service_meta_index(
    cliente_id: str, rows: List[sqlite3.Row]
) -> Dict[str, Dict[str, Any]]:
    """Version BATCH de ``_booking_display_service_meta`` para listados grandes.

    Carga el catalogo de servicios UNA vez y resuelve la meta de cada cita en
    memoria (replicando la logica de ``_booking_catalog_service_row``: por slug y
    si no por nombre normalizado), evitando 1-2 conexiones SQLite por fila. El
    resultado es identico al per-row salvo en el ``fallback`` (servicio no
    catalogado), que es poco frecuente.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not rows:
        return out
    service_rows = _list_service_rows(cliente_id, include_inactive=True)
    by_slug: Dict[str, sqlite3.Row] = {}
    by_key: Dict[str, sqlite3.Row] = {}
    for candidate in service_rows:
        slug = candidate["slug"] or ""
        if slug:
            by_slug.setdefault(slug, candidate)
        key = _service_match_key(candidate["name"] or "")
        if key:
            by_key.setdefault(key, candidate)
    for row in rows:
        try:
            service_id = row["service_id"] or ""
        except (KeyError, IndexError):
            service_id = ""
        service_row = by_slug.get(service_id) if service_id else None
        if service_row is None:
            name_clean = textnorm._sanitize_text(row["servicio"] or "")
            variants = [name_clean]
            if " · " in name_clean:
                variants.append(name_clean.split(" · ", 1)[0].strip())
            for variant in variants:
                if not variant:
                    continue
                service_row = by_slug.get(_normalize_service_id(variant)) or by_key.get(
                    _service_match_key(variant)
                )
                if service_row is not None:
                    break
        if service_row is not None:
            price_cents = int(service_row["price_cents"] or 0)
            out[row["id"]] = {
                "service_id": service_row["slug"] or "",
                "service_duration_minutes": int(service_row["duration_minutes"] or 0),
                "service_price_cents": price_cents,
                "service_price_label": textnorm._format_price_cents(price_cents),
            }
        else:
            out[row["id"]] = _booking_display_service_meta(row, cliente_id)
    return out


def _service_gap_json(cliente_id: str, servicio_name: str) -> str:
    """Tramos activo/espera configurados para un servicio (vacio = sin esperas)."""
    row = _find_service_by_name(cliente_id, servicio_name) if servicio_name else None
    if row is None:
        return ""
    return (row["gap_json"] if "gap_json" in row.keys() else "") or ""


def _tramos_de_trabajo(gap_json: str, inicio_min: int, duracion_min: int) -> List[Tuple[int, int]]:
    """Los ratos en que la profesional esta OCUPADA dentro de una cita.

    Un alisado o unas mechas se hacen por pasos, y entre paso y paso el producto
    tiene que actuar: la clienta espera pero la profesional queda libre y puede
    atender a otra. Esos huecos no pueden bloquear la agenda.

    `gap_json` son los tramos en orden: [{"activo": 105, "espera": 90}, ...].
    Sin tramos (el caso normal) la cita ocupa su duracion entera, como siempre.
    """
    entero = [(inicio_min, inicio_min + duracion_min)]
    if not gap_json:
        return entero
    try:
        tramos = json.loads(gap_json)
    except (ValueError, TypeError):
        return entero
    if not isinstance(tramos, list) or not tramos:
        return entero

    ocupados: List[Tuple[int, int]] = []
    cursor = inicio_min
    for tramo in tramos:
        if not isinstance(tramo, dict):
            continue
        try:
            activo = max(0, int(tramo.get("activo") or 0))
            espera = max(0, int(tramo.get("espera") or 0))
        except (TypeError, ValueError):
            continue
        if activo:
            ocupados.append((cursor, cursor + activo))
        cursor += activo + espera
    # Si los tramos no cuadran con la duracion guardada, manda la duracion: mejor
    # bloquear de mas que dejar entrar una cita encima de otra.
    if not ocupados or cursor > inicio_min + duracion_min:
        return entero
    return ocupados


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
        gap_json = (row["gap_json"] if "gap_json" in row.keys() else "") or ""
        intervals.extend(
            _tramos_de_trabajo(gap_json, start_min, _booking_row_duration_min(row, cliente_id))
        )
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


def slot_pisa_otra_cita(
    cliente_id: str, fecha: str, hora: str, *, employee_id: str, duration_minutes: int,
    exclude_booking_id: str = "",
) -> bool:
    """¿Este tramo se solapa AHORA MISMO con otra cita de ese profesional?

    Sincrona y sin I/O de red a proposito: se llama con el lock de insercion
    cogido, justo antes de guardar, para cerrar la ventana entre comprobar el
    hueco y crear la cita. `_booking_slot_available` sigue siendo la validacion
    completa (horario, bloqueos, aforo); esto solo repite la parte que otra
    peticion simultanea puede haber invalidado.
    """
    inicio = textnorm._time_to_min(hora)
    if inicio is None:
        return False
    fin = inicio + max(1, int(duration_minutes or 0))
    ocupados = _booked_intervals(
        cliente_id, fecha, employee_id=employee_id, exclude_booking_id=exclude_booking_id
    )
    return _interval_overlaps(inicio, fin, ocupados)


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


def _booking_conflicts_outside_schedule(
    cliente_id: str,
    day_start: str,
    day_end: str,
    *,
    employee_id: str = "",
) -> List[sqlite3.Row]:
    start_limit = textnorm._time_to_min(day_start)
    end_limit = textnorm._time_to_min(day_end)
    if start_limit is None or end_limit is None:
        return []
    today = timeutils._utc_now().date().isoformat()
    now_utc = timeutils._utc_now()
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
        start_at = timeutils._from_utc_iso(row["start_at"] or "")
        if start_at and start_at < now_utc:
            continue
        booking_start = textnorm._time_to_min(row["booking_time"])
        if booking_start is None:
            continue
        booking_end = booking_start + _booking_row_duration_min(row, cliente_id)
        if booking_start < start_limit or booking_end > end_limit:
            conflicts.append(row)
    return conflicts


async def _booking_slot_available(
    cliente_id: str, fecha: str, hora: str, *, employee_id: str = "",
    duration_minutes: Optional[int] = None, gap_json: str = "",
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
    # Con esperas, solo cuentan los tramos en que la profesional trabaja: el resto
    # del rango puede pisarse con otra cita, que es de lo que se trata.
    tramos = _tramos_de_trabajo(gap_json, start_min, dur)
    ocupados = _booked_intervals(cliente_id, fecha, employee_id=employee_id)
    bloqueados = _blocked_intervals(cliente_id, fecha, employee_id=employee_id)
    if any(_interval_overlaps(a, b, ocupados) for a, b in tramos):
        return False
    if any(_interval_overlaps(a, b, bloqueados) for a, b in tramos):
        return False
    return _location_capacity_ok(
        cliente_id, employee_row["location_id"] or "", fecha, start_min, end_min
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
    employee_location = employee["location_id"] or ""
    room_count = _location_room_count(cliente_id, employee_location)
    location_intervals = (
        _location_booked_intervals(
            cliente_id, employee_location, fecha, exclude_booking_id=exclude_booking_id
        )
        if room_count > 0
        else []
    )
    # Si el servicio que se quiere reservar TAMBIEN tiene esperas, solo hay que
    # mirar sus tramos de trabajo: asi un corte de 30 min puede entrar en el rato
    # en que la profesional espera a que actue un alisado, que es justo el sentido
    # de todo esto.
    gap_servicio = _service_gap_json(cliente_id, textnorm._sanitize_text(servicio)) if servicio else ""

    available: Set[str] = set()
    for slot in slots:
        start_min = textnorm._time_to_min(slot)
        if start_min is None:
            continue
        end_min = start_min + dur
        tramos = _tramos_de_trabajo(gap_servicio, start_min, dur)
        if any(_interval_overlaps(a, b, booked) or _interval_overlaps(a, b, blocked) for a, b in tramos):
            continue
        if room_count > 0:
            overlapping = sum(
                1 for b_start, b_end in location_intervals if start_min < b_end and b_start < end_min
            )
            if overlapping >= room_count:
                continue
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
    if _interval_overlaps(
        start_min, end_min,
        _booked_intervals(cliente_id, fecha, employee_id=employee_id, exclude_booking_id=exclude_booking_id),
    ):
        return False
    if _interval_overlaps(start_min, end_min, _blocked_intervals(cliente_id, fecha, employee_id=employee_id)):
        return False
    return _location_capacity_ok(
        cliente_id,
        employee_row["location_id"] or "",
        fecha,
        start_min,
        end_min,
        exclude_booking_id=exclude_booking_id,
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
        if (
            ("duracion" in prefix_lower or "duración" in prefix_lower)
            or textnorm._parse_duration_minutes_text(clean)
        ) and not current.get("duration_minutes"):
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
            "fuente", "source", "url",
        }
        first_label_match = re.match(r"^([^:]{1,60}):", raw)
        if first_label_match and first_label_match.group(1).strip().lower() in known_detail_labels:
            return False
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
            compact_bits.append(f"Duración: {duration_part}")
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
            en_seccion = False
            current = None
            current_category = ""
            continue

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
    # El catalogo se resuelve con los overrides del centro del profesional
    # (carta/precios por centro): un servicio deshabilitado en su centro no se ofrece.
    employee_location = ""
    if employee_row is not None:
        try:
            employee_location = employee_row["location_id"] or ""
        except (IndexError, KeyError):
            employee_location = ""
    services = _catalog_services(cliente_id, location_id=employee_location)
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
    service_row = _find_service_by_name(cliente_id, normalized_name)
    if service_row is not None:
        available_ids = {
            str(service.get("id") or "")
            for service in _services_for_employee(cliente_id, employee_row)
        }
        return str(service_row["slug"] or "") in available_ids
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
    location_id: str = "",
) -> Tuple[Set[str], Set[str]]:
    all_slots: Set[str] = set()
    available_slots: Set[str] = set()
    for employee_row in _list_public_employee_rows(cliente_id, include_inactive=False, location_id=location_id):
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
    location_id: str = "",
) -> sqlite3.Row:
    if employee_id:
        employee_row = _resolve_employee_for_booking(cliente_id, employee_id)
        if bool(employee_row["is_default"]):
            raise HTTPException(status_code=400, detail="La agenda general no se puede seleccionar desde el formulario.")
        if location_id and (employee_row["location_id"] or "") != location_id:
            raise HTTPException(
                status_code=400,
                detail="El profesional seleccionado no pertenece al centro indicado.",
            )
        if servicio and not _service_name_allowed_for_employee(cliente_id, employee_row, servicio):
            raise HTTPException(
                status_code=400,
                detail="El servicio seleccionado no esta disponible para ese profesional.",
            )
        return employee_row

    candidates = [
        row
        for row in _list_public_employee_rows(cliente_id, include_inactive=False, location_id=location_id)
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





def _weekly_schedule_matrix(cliente_id: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Matriz semanal REAL del negocio (lunes=0..domingo=6): por dia, si esta cerrado y la
    envolvente de horas de apertura. Derivada de los MISMOS profesionales publicos que usa
    la disponibilidad (un dia esta 'cerrado' solo si NINGUN profesional activo trabaja ese
    dia); si no hay profesionales, cae al horario base de config['booking']. Fuente unica
    compartida por los prompts de voz (voice._voice_schedule_block) y de chat
    (rag._build_system_prompt): el horario contado nunca contradice la agenda real.

    Devuelve [] si la reserva esta desactivada o el negocio esta cerrado los 7 dias.
    Cada elemento: {"weekday": 0-6, "closed": bool, "start": "HH:MM", "end": "HH:MM"}.
    """
    booking_cfg = (config or {}).get("booking") or {}
    if not booking_cfg.get("enabled", True):
        return []

    def _norm_hhmm(value: Any, default: str) -> str:
        try:
            return textnorm._parse_time(str(value)).strftime("%H:%M")
        except Exception:  # noqa: BLE001
            return default

    try:
        rows = _list_public_employee_rows(cliente_id, include_inactive=False)
        schedules = [_employee_schedule_from_row(row) for row in rows]
    except Exception:  # noqa: BLE001
        schedules = []

    matrix: List[Dict[str, Any]] = []
    source = "employees" if schedules else "config"
    if schedules:
        for wd in range(7):
            windows = [textnorm._weekday_hours(s, wd) for s in schedules]
            open_today = [w for w in windows if w is not None]
            if not open_today:
                matrix.append({"weekday": wd, "closed": True, "start": "", "end": "", "source": source})
                continue
            starts = [_norm_hhmm(w[0], "09:00") for w in open_today]
            ends = [_norm_hhmm(w[1], "18:00") for w in open_today]
            matrix.append({"weekday": wd, "closed": False, "start": min(starts), "end": max(ends), "source": source})
    else:
        base_schedule = {
            "day_start": _norm_hhmm(booking_cfg.get("day_start", "09:00"), "09:00"),
            "day_end": _norm_hhmm(booking_cfg.get("day_end", "18:00"), "18:00"),
            "closed_weekdays": booking_cfg.get("closed_weekdays") or [],
            "weekly_hours": booking_cfg.get("weekly_hours") or {},
        }
        for wd in range(7):
            window = textnorm._weekday_hours(base_schedule, wd)
            if window is None:
                matrix.append({"weekday": wd, "closed": True, "start": "", "end": "", "source": source})
            else:
                matrix.append({"weekday": wd, "closed": False, "start": window[0], "end": window[1], "source": source})

    if all(item["closed"] for item in matrix):
        return []
    return matrix
