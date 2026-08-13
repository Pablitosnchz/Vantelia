"""Informes económicos del portal (F5).

Un único overview agregado al estilo Fresha/Mindbody:
- KPIs con delta vs periodo anterior (ingresos, citas, ticket medio, asistencia,
  ocupación, clientes nuevos).
- Serie diaria (ingresos + citas) para gráficos.
- Desgloses: por servicio, por profesional, por centro, por canal y mix de pago.

Ingresos = citas pagadas (snapshot service_price_cents, fecha de la cita)
         + ventas de productos + bonos vendidos + tarjetas regalo emitidas
           (fecha de venta/emisión). La redención de gift card/bono NO suma
           (ya contó al vender) — criterio contable estándar de los POS de
           belleza/bienestar.

Todo filtrable por centro (location_id), servicio (service_id) y rango de fechas.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8
    from backports.zoneinfo import ZoneInfo  # type: ignore

from fastapi import HTTPException

from backend import agenda, db, textnorm, timeutils

REVENUE_BOOKING_FILTER = "payment_status = 'paid'"


def _today_in(tz_name: str) -> date:
    """Fecha de HOY en la zona del negocio (por defecto, UTC)."""
    if not tz_name:
        return timeutils._utc_now().date()
    try:
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:  # noqa: BLE001 - zona invalida en config
        return timeutils._utc_now().date()


def _parse_range(date_from: str, date_to: str, tz_name: str = "") -> Tuple[date, date]:
    """Rango de dias LOCALES del negocio. Sin `date_to`, termina HOY en su zona
    horaria: tomarlo del dia UTC cerraba el rango en ayer durante las horas en que
    las dos fechas no coinciden, y las ventas del dia no salian en Informes."""
    try:
        hoy = _today_in(tz_name)
        end = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else hoy
        start = (
            datetime.strptime(date_from, "%Y-%m-%d").date()
            if date_from
            else end - timedelta(days=29)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Formato de fecha invalido (YYYY-MM-DD).") from exc
    if start > end:
        start, end = end, start
    if (end - start).days > 366:
        raise HTTPException(status_code=400, detail="El rango maximo es de 1 ano.")
    return start, end


def _loc_clause(location_id: str, column: str = "location_id") -> Tuple[str, List[Any]]:
    if location_id:
        return f" AND {column} = ?", [location_id]
    return "", []


def _service_clause(service_id: str, column: str = "service_id") -> Tuple[str, List[Any]]:
    if service_id:
        return f" AND {column} = ?", [service_id]
    return "", []


def _bookings_aggregates(
    connection: sqlite3.Connection, cliente_id: str, start: date, end: date,
    location_id: str, service_id: str,
) -> Dict[str, Any]:
    loc_sql, loc_params = _loc_clause(location_id)
    service_sql, service_params = _service_clause(service_id)
    base_params = [cliente_id, start.isoformat(), end.isoformat()] + loc_params + service_params
    by_status: Dict[str, int] = {}
    for row in connection.execute(
        f"""
        SELECT status, COUNT(*) AS n
        FROM bookings
        WHERE cliente_id = ? AND booking_date >= ? AND booking_date <= ?{loc_sql}{service_sql}
        GROUP BY status
        """,
        base_params,
    ):
        by_status[row["status"]] = int(row["n"])
    revenue_row = connection.execute(
        f"""
        SELECT COALESCE(SUM(service_price_cents), 0) AS cents, COUNT(*) AS n
        FROM bookings
        WHERE cliente_id = ? AND booking_date >= ? AND booking_date <= ?{loc_sql}{service_sql}
          AND {REVENUE_BOOKING_FILTER}
        """,
        base_params,
    ).fetchone()
    return {
        "by_status": by_status,
        "revenue_cents": int(revenue_row["cents"] or 0),
        "paid_count": int(revenue_row["n"] or 0),
    }


def _client_timezone(cliente_id: str) -> str:
    """Zona horaria configurada del negocio (la de su agenda)."""
    from backend import appstate  # tardio: evita ciclo en el arranque

    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    return str((config.get("booking") or {}).get("timezone") or "Europe/Madrid")


def _local_day_bounds_utc(tz_name: str, start: date, end: date) -> Tuple[str, str]:
    """Convierte un rango de dias LOCALES del negocio en sellos UTC.

    `created_at` de las ventas se guarda en UTC, mientras que el rango que elige
    el negocio (o "hoy" del mostrador) es en SU zona horaria. Comparar un dia
    local contra un sello UTC se come las ventas de las horas en las que las dos
    fechas no coinciden: en Madrid en verano (UTC+2), las de 00:00 a 02:00
    contaban como del dia anterior y desaparecian del "hoy".
    """
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:  # noqa: BLE001 - zona invalida en config
        tz = ZoneInfo("UTC")
    desde = datetime(start.year, start.month, start.day, tzinfo=tz).astimezone(timezone.utc)
    fin = end + timedelta(days=1)
    hasta = datetime(fin.year, fin.month, fin.day, tzinfo=tz).astimezone(timezone.utc)
    return desde.isoformat().replace("+00:00", "Z"), hasta.isoformat().replace("+00:00", "Z")


def _sales_revenue(
    connection: sqlite3.Connection, table: str, amount_expr: str,
    cliente_id: str, start: date, end: date, location_id: str, tz_name: str = "",
) -> int:
    loc_sql, loc_params = _loc_clause(location_id)
    desde, hasta = _local_day_bounds_utc(tz_name, start, end)
    row = connection.execute(
        f"""
        SELECT COALESCE(SUM({amount_expr}), 0) AS cents
        FROM {table}
        WHERE cliente_id = ? AND created_at >= ? AND created_at < ?{loc_sql}
        """,
        [cliente_id, desde, hasta] + loc_params,
    ).fetchone()
    return int(row["cents"] or 0)


def _daily_series(
    connection: sqlite3.Connection, cliente_id: str, start: date, end: date,
    location_id: str, service_id: str,
) -> List[Dict[str, Any]]:
    loc_sql, loc_params = _loc_clause(location_id)
    service_sql, service_params = _service_clause(service_id)
    bookings_by_day: Dict[str, Dict[str, int]] = {}
    for row in connection.execute(
        f"""
        SELECT booking_date AS d,
               COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN {REVENUE_BOOKING_FILTER} THEN service_price_cents ELSE 0 END), 0) AS cents
        FROM bookings
        WHERE cliente_id = ? AND booking_date >= ? AND booking_date <= ?{loc_sql}{service_sql}
          AND status != 'cancelled'
        GROUP BY booking_date
        """,
        [cliente_id, start.isoformat(), end.isoformat()] + loc_params + service_params,
    ):
        bookings_by_day[row["d"]] = {"bookings": int(row["total"]), "cents": int(row["cents"] or 0)}
    extras_by_day: Dict[str, int] = {}
    for table, expr in (() if service_id else (
        ("product_sales", "total_cents"),
        ("package_purchases", "price_cents"),
        ("gift_cards", "initial_cents"),
    )):
        for row in connection.execute(
            f"""
            SELECT substr(created_at, 1, 10) AS d, COALESCE(SUM({expr}), 0) AS cents
            FROM {table}
            WHERE cliente_id = ? AND created_at >= ? AND created_at < ?{loc_sql}
            GROUP BY substr(created_at, 1, 10)
            """,
            [cliente_id, start.isoformat(), (end + timedelta(days=1)).isoformat()] + loc_params,
        ):
            extras_by_day[row["d"]] = extras_by_day.get(row["d"], 0) + int(row["cents"] or 0)
    series: List[Dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        item = bookings_by_day.get(key, {"bookings": 0, "cents": 0})
        series.append(
            {
                "date": key,
                "bookings": item["bookings"],
                "revenue_cents": item["cents"] + extras_by_day.get(key, 0),
            }
        )
        cursor += timedelta(days=1)
    return series


def _breakdown(
    connection: sqlite3.Connection, cliente_id: str, start: date, end: date,
    location_id: str, service_id: str, column: str, label_fallback: str, limit: int = 8,
) -> List[Dict[str, Any]]:
    loc_sql, loc_params = _loc_clause(location_id)
    service_sql, service_params = _service_clause(service_id)
    rows = connection.execute(
        f"""
        SELECT COALESCE(NULLIF({column}, ''), ?) AS label,
               COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN {REVENUE_BOOKING_FILTER} THEN service_price_cents ELSE 0 END), 0) AS cents
        FROM bookings
        WHERE cliente_id = ? AND booking_date >= ? AND booking_date <= ?{loc_sql}{service_sql}
          AND status != 'cancelled'
        GROUP BY label
        ORDER BY total DESC
        LIMIT ?
        """,
        [label_fallback, cliente_id, start.isoformat(), end.isoformat()]
        + loc_params + service_params + [limit],
    ).fetchall()
    return [
        {"label": row["label"], "bookings": int(row["total"]), "revenue_cents": int(row["cents"] or 0)}
        for row in rows
    ]


def _employee_available_minutes(row: sqlite3.Row, start: date, end: date) -> int:
    """Minutos de agenda abiertos del empleado en el rango (horario - descansos)."""
    try:
        day_start = textnorm._parse_time(row["day_start"] or "09:00")
        day_end = textnorm._parse_time(row["day_end"] or "18:00")
    except Exception:  # noqa: BLE001
        return 0
    minutes_per_day = (day_end.hour * 60 + day_end.minute) - (day_start.hour * 60 + day_start.minute)
    if minutes_per_day <= 0:
        return 0
    try:
        breaks = json.loads(row["break_windows_json"] or "[]")
    except (ValueError, TypeError):
        breaks = []
    for window in breaks:
        try:
            b_start = textnorm._parse_time(str(window.get("start", "")))
            b_end = textnorm._parse_time(str(window.get("end", "")))
            minutes_per_day -= max(0, (b_end.hour * 60 + b_end.minute) - (b_start.hour * 60 + b_start.minute))
        except Exception:  # noqa: BLE001
            continue
    if minutes_per_day <= 0:
        return 0
    try:
        closed = set(json.loads(row["closed_weekdays_json"] or "[]"))
    except (ValueError, TypeError):
        closed = set()
    open_days = 0
    cursor = start
    today = timeutils._utc_now().date()
    effective_end = min(end, today)  # ocupación solo de días ya transcurridos o en curso
    while cursor <= effective_end:
        if cursor.weekday() not in closed:
            open_days += 1
        cursor += timedelta(days=1)
    return minutes_per_day * open_days


def _occupancy_rate(
    connection: sqlite3.Connection, cliente_id: str, start: date, end: date,
    location_id: str, service_id: str,
) -> float:
    employees = [
        row
        for row in agenda._list_employee_rows(cliente_id, include_inactive=False, location_id=location_id)
        if not service_id or not agenda._employee_service_ids_from_row(row, cliente_id)
        or service_id in agenda._employee_service_ids_from_row(row, cliente_id)
    ]
    available = sum(_employee_available_minutes(row, start, end) for row in employees)
    if available <= 0:
        return 0.0
    loc_sql, loc_params = _loc_clause(location_id)
    service_sql, service_params = _service_clause(service_id)
    booked = 0
    for row in connection.execute(
        f"""
        SELECT start_at, end_at
        FROM bookings
        WHERE cliente_id = ? AND booking_date >= ? AND booking_date <= ?{loc_sql}{service_sql}
          AND status IN ('confirmed', 'pending_review', 'completed', 'no_show')
        """,
        [cliente_id, start.isoformat(), end.isoformat()] + loc_params + service_params,
    ):
        try:
            start_dt = datetime.fromisoformat(str(row["start_at"]).replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(str(row["end_at"]).replace("Z", "+00:00"))
            booked += max(0, int((end_dt - start_dt).total_seconds() // 60))
        except (ValueError, TypeError):
            booked += 30
    return round(min(1.0, booked / available), 4)


def _new_customers(
    connection: sqlite3.Connection, cliente_id: str, start: date, end: date,
    location_id: str, service_id: str,
) -> int:
    loc_sql, loc_params = _loc_clause(location_id)
    service_sql, service_params = _service_clause(service_id)
    row = connection.execute(
        f"""
        SELECT COUNT(*) AS n FROM (
            SELECT LOWER(email) AS e, MIN(booking_date) AS first_date
            FROM bookings
            WHERE cliente_id = ? AND email != ''{loc_sql}{service_sql}
            GROUP BY LOWER(email)
        )
        WHERE first_date >= ? AND first_date <= ?
        """,
        [cliente_id] + loc_params + service_params + [start.isoformat(), end.isoformat()],
    ).fetchone()
    return int(row["n"] or 0)


def _kpis_for_range(
    connection: sqlite3.Connection, cliente_id: str, start: date, end: date,
    location_id: str, service_id: str,
) -> Dict[str, Any]:
    agg = _bookings_aggregates(connection, cliente_id, start, end, location_id, service_id)
    tz_name = _client_timezone(cliente_id)
    extras = 0 if service_id else (
        _sales_revenue(connection, "product_sales", "total_cents", cliente_id, start, end, location_id, tz_name)
        + _sales_revenue(connection, "package_purchases", "price_cents", cliente_id, start, end, location_id, tz_name)
        + _sales_revenue(connection, "gift_cards", "initial_cents", cliente_id, start, end, location_id, tz_name)
    )
    by_status = agg["by_status"]
    completed = by_status.get("completed", 0)
    no_show = by_status.get("no_show", 0)
    finished = completed + no_show
    total_active = sum(n for status, n in by_status.items() if status != "cancelled")
    revenue = agg["revenue_cents"] + extras
    return {
        "revenue_cents": revenue,
        "bookings_total": total_active,
        "bookings_cancelled": by_status.get("cancelled", 0),
        "completed": completed,
        "no_show": no_show,
        "attendance_rate": round(completed / finished, 4) if finished else None,
        "avg_ticket_cents": int(agg["revenue_cents"] / agg["paid_count"]) if agg["paid_count"] else 0,
        "extras_revenue_cents": extras,
        "new_customers": _new_customers(connection, cliente_id, start, end, location_id, service_id),
    }


def _central_summary(cliente_id: str) -> Dict[str, Any]:
    """KPIs de mostrador para HOY (zona horaria del negocio) + valor vivo en
    circulacion (bonos activos, saldo de tarjetas regalo). Ligero a proposito:
    lo consume la Central de Ventas del portal en cada apertura, con permiso
    commerce.sell (staff), a diferencia del overview (reports.view)."""
    from backend import appstate  # tardio: evita ciclo en el arranque

    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    tz_name = str((config.get("booking") or {}).get("timezone") or "Europe/Madrid")
    today = _today_in(tz_name)
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        agg = _bookings_aggregates(connection, cliente_id, today, today, "", "")
        by_status = agg["by_status"]
        bookings_today = sum(n for status, n in by_status.items() if status != "cancelled")
        products_cents = _sales_revenue(connection, "product_sales", "total_cents", cliente_id, today, today, "", tz_name)
        packages_cents = _sales_revenue(connection, "package_purchases", "price_cents", cliente_id, today, today, "", tz_name)
        gifts_cents = _sales_revenue(connection, "gift_cards", "initial_cents", cliente_id, today, today, "", tz_name)
        desde_hoy, hasta_hoy = _local_day_bounds_utc(tz_name, today, today)
        product_sales_today = int(connection.execute(
            "SELECT COUNT(*) FROM product_sales WHERE cliente_id = ? AND created_at >= ? AND created_at < ?",
            (cliente_id, desde_hoy, hasta_hoy),
        ).fetchone()[0])
        # Valor vivo: sin refresco lazy (solo lectura) — se excluye lo ya caducado.
        not_expired = "(expires_at IS NULL OR expires_at = '' OR expires_at >= ?)"
        sessions_left = 0
        packages_active = 0
        for row in connection.execute(
            f"SELECT remaining_json FROM package_purchases WHERE cliente_id = ? AND status = 'active' AND {not_expired}",
            (cliente_id, now_iso),
        ):
            packages_active += 1
            try:
                remaining = json.loads(row["remaining_json"] or "{}")
            except (ValueError, TypeError):
                remaining = {}
            sessions_left += sum(int(v or 0) for v in remaining.values())
        gift_row = connection.execute(
            f"SELECT COUNT(*) AS n, COALESCE(SUM(balance_cents), 0) AS cents FROM gift_cards "
            f"WHERE cliente_id = ? AND status = 'active' AND {not_expired}",
            (cliente_id, now_iso),
        ).fetchone()
    return {
        "date": today.isoformat(),
        "bookings_today": bookings_today,
        "bookings_today_paid": agg["paid_count"],
        "revenue_today_cents": agg["revenue_cents"] + products_cents + packages_cents + gifts_cents,
        "revenue_breakdown": {
            "bookings_cents": agg["revenue_cents"],
            "products_cents": products_cents,
            "packages_cents": packages_cents,
            "gift_cards_cents": gifts_cents,
        },
        "product_sales_today": product_sales_today,
        "packages_active": packages_active,
        "packages_sessions_left": sessions_left,
        "gift_active": int(gift_row["n"] or 0),
        "gift_balance_cents": int(gift_row["cents"] or 0),
    }


def _overview(
    cliente_id: str, *, location_id: str = "", service_id: str = "",
    date_from: str = "", date_to: str = "",
) -> Dict[str, Any]:
    start, end = _parse_range(date_from, date_to, _client_timezone(cliente_id))
    location_filter = (
        agenda._resolve_location_id(cliente_id, location_id, require_active=False) if location_id else ""
    )
    service_filter = agenda._normalize_service_id(service_id) if service_id else ""
    if service_filter and not agenda._get_service_row(cliente_id, service_filter):
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    with db._get_db_connection() as connection:
        current = _kpis_for_range(connection, cliente_id, start, end, location_filter, service_filter)
        previous = _kpis_for_range(connection, cliente_id, prev_start, prev_end, location_filter, service_filter)
        current["occupancy_rate"] = _occupancy_rate(connection, cliente_id, start, end, location_filter, service_filter)
        previous["occupancy_rate"] = _occupancy_rate(connection, cliente_id, prev_start, prev_end, location_filter, service_filter)
        series = _daily_series(connection, cliente_id, start, end, location_filter, service_filter)
        by_service = _breakdown(connection, cliente_id, start, end, location_filter, service_filter, "servicio", "Sin servicio")
        by_employee = _breakdown(connection, cliente_id, start, end, location_filter, service_filter, "employee_name", "Sin asignar")
        by_source = _breakdown(connection, cliente_id, start, end, location_filter, service_filter, "source", "otro")
        by_location_raw = _breakdown(connection, cliente_id, start, end, "", service_filter, "location_id", "", limit=20)
    location_names = {
        row["id"]: row["name"] for row in agenda._list_location_rows(cliente_id)
    }
    by_location = [
        {**item, "label": location_names.get(item["label"], item["label"] or "Centro principal")}
        for item in by_location_raw
    ]
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "location_id": location_filter,
        "service_id": service_filter,
        "kpis": current,
        "previous": previous,
        "series": series,
        "by_service": by_service,
        "by_employee": by_employee,
        "by_source": by_source,
        "by_location": by_location,
    }


def _export_csv(
    cliente_id: str, *, location_id: str = "", service_id: str = "",
    date_from: str = "", date_to: str = "",
) -> str:
    data = _overview(
        cliente_id, location_id=location_id, service_id=service_id,
        date_from=date_from, date_to=date_to,
    )
    lines = ["fecha;citas;ingresos_eur"]
    for item in data["series"]:
        lines.append(f"{item['date']};{item['bookings']};{item['revenue_cents'] / 100:.2f}")
    lines.append("")
    lines.append("servicio;citas;ingresos_eur")
    for item in data["by_service"]:
        lines.append(f"{item['label']};{item['bookings']};{item['revenue_cents'] / 100:.2f}")
    lines.append("")
    lines.append("profesional;citas;ingresos_eur")
    for item in data["by_employee"]:
        lines.append(f"{item['label']};{item['bookings']};{item['revenue_cents'] / 100:.2f}")
    return "\n".join(lines) + "\n"
