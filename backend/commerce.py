"""Comercio del portal: productos, bonos (paquetes de sesiones) y tarjetas regalo.

Patrón Fresha/Mindbody simplificado:
- Productos: catálogo + registro de venta (POS ligero), stock opcional.
- Bonos: N sesiones por servicio con caducidad; redención descuenta sesión y
  marca la cita como pagada.
- Tarjetas regalo: código único con saldo; redención descuenta saldo contra el
  precio efectivo de la cita (cubre total o parcial). Ledger completo en
  gift_card_transactions.

Todo scoped por cliente_id (+ location_id informativo para informes). El precio
siempre sale del catálogo/snapshot del backend, nunca del request.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from backend import agenda, booking, db, settings, stripe_gateway, textnorm, timeutils

PAYMENT_METHODS = {"cash", "card", "transfer", "stripe", "gift_card", "other"}


def _normalize_payment_method(value: str) -> str:
    method = (value or "").strip().lower()
    return method if method in PAYMENT_METHODS else "other"


def _unique_catalog_id(connection: sqlite3.Connection, table: str, cliente_id: str, name: str) -> str:
    base = agenda._normalize_service_id(name) or f"item_{secrets.token_urlsafe(4)}"
    candidate = base
    suffix = 2
    while connection.execute(
        f"SELECT 1 FROM {table} WHERE cliente_id = ? AND id = ?", (cliente_id, candidate)
    ).fetchone():
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


# ---------------------------------------------------------------------------
# Productos
# ---------------------------------------------------------------------------


def _product_to_public(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "price_cents": int(row["price_cents"] or 0),
        "currency": row["currency"] or "eur",
        "stock": row["stock"],
        "is_active": bool(row["is_active"]),
        "sort_order": int(row["sort_order"] or 0),
    }


def _list_products(cliente_id: str, *, include_inactive: bool = True) -> List[Dict[str, Any]]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if not include_inactive:
        clauses.append("is_active = 1")
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM products WHERE " + " AND ".join(clauses)
            + " ORDER BY is_active DESC, sort_order ASC, name COLLATE NOCASE ASC",
            tuple(params),
        ).fetchall()
    return [_product_to_public(row) for row in rows]


def _get_product_row(cliente_id: str, product_id: str) -> Optional[sqlite3.Row]:
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM products WHERE cliente_id = ? AND id = ? LIMIT 1",
            (cliente_id, product_id),
        ).fetchone()


def _create_product(cliente_id: str, data: Any) -> Dict[str, Any]:
    name = textnorm._sanitize_text(data.name)
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="El nombre del producto es obligatorio.")
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        product_id = _unique_catalog_id(connection, "products", cliente_id, name)
        next_order = connection.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM products WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO products (cliente_id, id, name, description, price_cents, currency,
                                  stock, is_active, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'eur', ?, ?, ?, ?, ?)
            """,
            (
                cliente_id,
                product_id,
                name,
                textnorm._sanitize_text(data.description, allow_multiline=True),
                max(0, int(data.price_cents or 0)),
                data.stock if data.stock is None else max(0, int(data.stock)),
                1 if data.is_active else 0,
                int(next_order),
                now_iso,
                now_iso,
            ),
        )
        connection.commit()
    return _product_to_public(_get_product_row(cliente_id, product_id))


def _update_product(cliente_id: str, product_id: str, data: Any) -> Dict[str, Any]:
    row = _get_product_row(cliente_id, product_id)
    if not row:
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    fields_set = set(getattr(data, "model_fields_set", set()))
    name = textnorm._sanitize_text(data.name) if "name" in fields_set else row["name"]
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="El nombre del producto es obligatorio.")
    with db._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE products
            SET name = ?, description = ?, price_cents = ?, stock = ?, is_active = ?, updated_at = ?
            WHERE cliente_id = ? AND id = ?
            """,
            (
                name,
                textnorm._sanitize_text(data.description, allow_multiline=True)
                if "description" in fields_set else (row["description"] or ""),
                max(0, int(data.price_cents)) if "price_cents" in fields_set else int(row["price_cents"] or 0),
                (data.stock if data.stock is None else max(0, int(data.stock)))
                if "stock" in fields_set else row["stock"],
                (1 if data.is_active else 0) if "is_active" in fields_set else row["is_active"],
                timeutils._utc_now_iso(),
                cliente_id,
                product_id,
            ),
        )
        connection.commit()
    return _product_to_public(_get_product_row(cliente_id, product_id))


def _delete_product(cliente_id: str, product_id: str) -> None:
    if not _get_product_row(cliente_id, product_id):
        raise HTTPException(status_code=404, detail="Producto no encontrado.")
    with db._get_db_connection() as connection:
        connection.execute(
            "DELETE FROM products WHERE cliente_id = ? AND id = ?", (cliente_id, product_id)
        )
        connection.commit()


def _sell_product(cliente_id: str, product_id: str, data: Any) -> Dict[str, Any]:
    row = _get_product_row(cliente_id, product_id)
    if not row or not bool(row["is_active"]):
        raise HTTPException(status_code=404, detail="Producto no disponible.")
    qty = max(1, int(data.qty or 1))
    if row["stock"] is not None and int(row["stock"]) < qty:
        raise HTTPException(
            status_code=409,
            detail=f"Stock insuficiente: quedan {int(row['stock'])} unidad(es).",
        )
    unit = int(row["price_cents"] or 0)
    location_id = agenda._resolve_location_id(cliente_id, getattr(data, "location_id", "") or "", require_active=False)
    sale_id = f"sale_{secrets.token_urlsafe(8)}"
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO product_sales (id, cliente_id, location_id, product_id, product_name,
                                       qty, unit_price_cents, total_cents, booking_id,
                                       customer_name, customer_email, payment_method, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sale_id,
                cliente_id,
                location_id,
                product_id,
                row["name"],
                qty,
                unit,
                unit * qty,
                textnorm._sanitize_text(getattr(data, "booking_id", "") or ""),
                textnorm._sanitize_text(getattr(data, "customer_name", "") or ""),
                textnorm._sanitize_text(getattr(data, "customer_email", "") or ""),
                _normalize_payment_method(getattr(data, "payment_method", "") or ""),
                textnorm._sanitize_text(getattr(data, "notes", "") or "", allow_multiline=True),
                now_iso,
            ),
        )
        if row["stock"] is not None:
            connection.execute(
                "UPDATE products SET stock = stock - ?, updated_at = ? WHERE cliente_id = ? AND id = ?",
                (qty, now_iso, cliente_id, product_id),
            )
        connection.commit()
    return {
        "sale_id": sale_id,
        "product_id": product_id,
        "product_name": row["name"],
        "qty": qty,
        "total_cents": unit * qty,
        "location_id": location_id,
    }


def _list_product_sales(
    cliente_id: str, *, location_id: str = "", date_from: str = "", date_to: str = "", limit: int = 200
) -> List[Dict[str, Any]]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if location_id:
        clauses.append("location_id = ?")
        params.append(location_id)
    if date_from:
        clauses.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("created_at < ?")
        params.append(date_to + "T99")
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM product_sales WHERE " + " AND ".join(clauses)
            + " ORDER BY created_at DESC LIMIT ?",
            tuple(params) + (max(1, min(500, limit)),),
        ).fetchall()
    return [
        {
            "sale_id": r["id"],
            "product_id": r["product_id"],
            "product_name": r["product_name"],
            "qty": int(r["qty"] or 1),
            "total_cents": int(r["total_cents"] or 0),
            "booking_id": r["booking_id"] or "",
            "customer_name": r["customer_name"] or "",
            "payment_method": r["payment_method"] or "",
            "location_id": r["location_id"] or "",
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Cobro POS con Stripe: QR/enlace en mostrador (#1) y producto sobre la cita (#2)
#
# A diferencia de _sell_product (registro manual de efectivo/datafono), aqui el
# cliente paga DE VERDAD con su tarjeta via Stripe Checkout sobre la cuenta
# Connect del negocio. La venta NO se registra hasta que el webhook confirma el
# pago (_finalize_pos_payment), evitando ventas fantasma. El precio sale siempre
# del catalogo/snapshot, nunca del request.
# ---------------------------------------------------------------------------


def _qr_svg(url: str) -> str:
    """SVG del QR para el enlace de pago. Cadena vacia si segno no esta disponible
    (el panel cae a mostrar solo el enlace)."""
    if not url:
        return ""
    try:
        import io
        import segno
        buf = io.StringIO()
        segno.make(url, error="m").save(buf, kind="svg", scale=5, border=2, xmldecl=False, svgclass="vqr")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return ""


def _pos_resolve_lines(cliente_id: str, items: Any) -> List[Dict[str, Any]]:
    """Valida [{product_id, qty}] -> lineas con precio del catalogo + control de stock."""
    lines: List[Dict[str, Any]] = []
    for it in items or []:
        pid = textnorm._sanitize_text(
            getattr(it, "product_id", "") or (it.get("product_id") if isinstance(it, dict) else "")
        )
        qty = int(getattr(it, "qty", 0) or (it.get("qty", 0) if isinstance(it, dict) else 0) or 0)
        if not pid or qty < 1:
            continue
        row = _get_product_row(cliente_id, pid)
        if not row or not bool(row["is_active"]):
            raise HTTPException(status_code=404, detail="Producto no disponible.")
        qty = min(qty, 999)
        if row["stock"] is not None and int(row["stock"]) < qty:
            raise HTTPException(
                status_code=409,
                detail=f"Stock insuficiente de {row['name']}: quedan {int(row['stock'])}.",
            )
        lines.append({
            "type": "product", "product_id": pid, "name": row["name"],
            "qty": qty, "unit_price_cents": int(row["price_cents"] or 0),
        })
    return lines


def create_pos_payment_link(
    cliente_id: str, *, items: Any, booking_id: str = "", base_url: str = "",
    customer_name: str = "", customer_email: str = "",
) -> Dict[str, Any]:
    """Crea un Stripe Checkout (cuenta Connect del negocio) para un cobro de
    mostrador: productos y/o el servicio de una cita. Devuelve enlace + QR. La venta
    se materializa en el webhook (_finalize_pos_payment)."""
    booking_id = textnorm._sanitize_text(booking_id or "")
    lines = _pos_resolve_lines(cliente_id, items)
    booking_row = None
    location_id = ""
    if booking_id:
        booking_row = booking._get_booking_row_by_id(booking_id)
        if not booking_row or booking_row["cliente_id"] != cliente_id:
            raise HTTPException(status_code=404, detail="Cita no encontrada.")
        location_id = booking_row["location_id"] or ""
        svc_cents = int(booking_row["service_price_cents"] or 0)
        if svc_cents > 0 and (booking_row["payment_status"] or "") != "paid":
            lines.insert(0, {
                "type": "booking", "booking_id": booking_id,
                "name": booking_row["servicio"] or "Cita", "qty": 1, "unit_price_cents": svc_cents,
            })
    if not lines:
        raise HTTPException(status_code=400, detail="Anade al menos un producto o un importe a cobrar.")
    amount = sum(int(l["unit_price_cents"]) * int(l["qty"]) for l in lines)
    if amount < 50:
        raise HTTPException(status_code=400, detail="El importe minimo de cobro es 0,50 EUR.")

    account = booking._connect_account_status(cliente_id, refresh=True)
    if not account.connected or not account.charges_enabled:
        raise HTTPException(status_code=409, detail="Conecta y activa Stripe antes de cobrar.")

    payment_id, now = "pay_" + secrets.token_hex(10), timeutils._utc_now_iso()
    metadata = {
        "source": "customer_payment", "kind": "pos", "payment_id": payment_id,
        "cliente_id": cliente_id, "booking_id": booking_id,
    }
    base = (base_url or "").rstrip("/")
    stripe_gateway._stripe_init()
    stripe_lines = [
        {
            "price_data": {"currency": "eur", "unit_amount": int(l["unit_price_cents"]),
                           "product_data": {"name": l["name"]}},
            "quantity": int(l["qty"]),
        }
        for l in lines
    ]
    try:
        kwargs: Dict[str, Any] = dict(
            mode="payment", line_items=stripe_lines, metadata=metadata,
            success_url=f"{base}/dashboard?pos=success", cancel_url=f"{base}/dashboard?pos=cancel",
            stripe_account=account.stripe_account_id,
        )
        email = textnorm._sanitize_text(customer_email or (booking_row["email"] if booking_row else ""))
        if email:
            kwargs["customer_email"] = email
        session = stripe_gateway.stripe.checkout.Session.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("No se pudo crear checkout POS %s: %s", cliente_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo crear el enlace de pago.") from exc

    checkout_url = textnorm._object_get(session, "url", "")
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO customer_payments
                (id, cliente_id, contact_id, booking_id, service_id, service_name, stripe_account_id,
                 stripe_checkout_session_id, amount_cents, currency, status, checkout_url,
                 kind, line_items_json, created_at, updated_at)
            VALUES (?, ?, '', ?, '', ?, ?, ?, ?, 'eur', 'pending', ?, 'pos', ?, ?, ?)
            """,
            (
                payment_id, cliente_id, booking_id,
                textnorm._sanitize_text(customer_name or "")[:120],
                account.stripe_account_id, textnorm._object_get(session, "id", ""),
                amount, checkout_url, json.dumps(lines, ensure_ascii=False), now, now,
            ),
        )
        connection.commit()
    return {
        "payment_id": payment_id, "url": checkout_url, "amount_cents": amount,
        "currency": "eur", "status": "pending", "qr_svg": _qr_svg(checkout_url),
        "line_items": lines,
    }


def pos_payment_status(cliente_id: str, payment_id: str) -> Dict[str, Any]:
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM customer_payments WHERE id=? AND cliente_id=? AND kind='pos'",
            (payment_id, cliente_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cobro no encontrado.")
    return {
        "payment_id": row["id"], "status": row["status"],
        "amount_cents": int(row["amount_cents"] or 0),
        "paid": row["status"] == "paid", "url": row["checkout_url"] or "",
    }


def _finalize_pos_payment(connection: sqlite3.Connection, payment: sqlite3.Row, now: str) -> None:
    """Materializa un cobro POS pagado: registra las ventas de producto (descontando
    stock) y marca la cita como pagada. Idempotente y usa la conexion/transaccion del
    webhook (no hace commit)."""
    cliente_id = payment["cliente_id"]
    pay_id = payment["id"]
    booking_id = payment["booking_id"] or ""
    try:
        lines = json.loads(payment["line_items_json"] or "[]")
    except (ValueError, TypeError):
        lines = []
    already = connection.execute(
        "SELECT COUNT(*) FROM product_sales WHERE customer_payment_id=?", (pay_id,)
    ).fetchone()[0]
    location_id = ""
    if booking_id:
        brow = connection.execute(
            "SELECT location_id FROM bookings WHERE id=? AND cliente_id=?", (booking_id, cliente_id)
        ).fetchone()
        if brow:
            location_id = brow["location_id"] or ""
    if not already:
        for l in lines:
            if l.get("type") != "product":
                continue
            qty = max(1, int(l.get("qty") or 1))
            unit = int(l.get("unit_price_cents") or 0)
            sale_id = "sale_" + secrets.token_urlsafe(8)
            connection.execute(
                """
                INSERT INTO product_sales
                    (id, cliente_id, location_id, product_id, product_name, qty, unit_price_cents,
                     total_cents, booking_id, customer_name, customer_email, payment_method, notes,
                     status, customer_payment_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', 'stripe', '', 'paid', ?, ?)
                """,
                (
                    sale_id, cliente_id, location_id, l.get("product_id", ""), l.get("name", ""),
                    qty, unit, unit * qty, booking_id, pay_id, now,
                ),
            )
            connection.execute(
                "UPDATE products SET stock = CASE WHEN stock IS NULL THEN NULL ELSE MAX(0, stock - ?) END, "
                "updated_at=? WHERE cliente_id=? AND id=?",
                (qty, now, cliente_id, l.get("product_id", "")),
            )
    if booking_id:
        connection.execute(
            "UPDATE bookings SET payment_status='paid' WHERE id=? AND cliente_id=? AND payment_status!='paid'",
            (booking_id, cliente_id),
        )
        connection.execute(
            "INSERT INTO booking_audit (booking_id, cliente_id, event_type, payload_json, created_at) "
            "VALUES (?, ?, 'booking_paid_pos', ?, ?)",
            (booking_id, cliente_id, json.dumps({"payment_id": pay_id, "amount_cents": int(payment["amount_cents"] or 0)}), now),
        )


# ---------------------------------------------------------------------------
# Bonos (paquetes de sesiones)
# ---------------------------------------------------------------------------


def _normalize_package_items(cliente_id: str, items: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in items or []:
        slug = textnorm._sanitize_text(getattr(item, "service_slug", "") or (item.get("service_slug") if isinstance(item, dict) else ""))
        qty = int(getattr(item, "qty", 0) or (item.get("qty", 0) if isinstance(item, dict) else 0) or 0)
        if not slug or qty < 1:
            continue
        if not agenda._get_service_row(cliente_id, slug):
            raise HTTPException(status_code=400, detail=f"El servicio '{slug}' no existe en el catalogo.")
        normalized.append({"service_slug": slug, "qty": min(qty, 100)})
    if not normalized:
        raise HTTPException(status_code=400, detail="El bono debe incluir al menos un servicio con sesiones.")
    return normalized


def _package_to_public(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        items = json.loads(row["items_json"] or "[]")
    except (ValueError, TypeError):
        items = []
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "items": items,
        "price_cents": int(row["price_cents"] or 0),
        "validity_days": int(row["validity_days"] or 365),
        "is_active": bool(row["is_active"]),
        "sort_order": int(row["sort_order"] or 0),
    }


def _list_packages(cliente_id: str, *, include_inactive: bool = True) -> List[Dict[str, Any]]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if not include_inactive:
        clauses.append("is_active = 1")
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM packages WHERE " + " AND ".join(clauses)
            + " ORDER BY is_active DESC, sort_order ASC, name COLLATE NOCASE ASC",
            tuple(params),
        ).fetchall()
    return [_package_to_public(row) for row in rows]


def _get_package_row(cliente_id: str, package_id: str) -> Optional[sqlite3.Row]:
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM packages WHERE cliente_id = ? AND id = ? LIMIT 1",
            (cliente_id, package_id),
        ).fetchone()


def _create_package(cliente_id: str, data: Any) -> Dict[str, Any]:
    name = textnorm._sanitize_text(data.name)
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="El nombre del bono es obligatorio.")
    items = _normalize_package_items(cliente_id, data.items)
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        package_id = _unique_catalog_id(connection, "packages", cliente_id, name)
        next_order = connection.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM packages WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO packages (cliente_id, id, name, description, items_json, price_cents,
                                  currency, validity_days, is_active, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'eur', ?, ?, ?, ?, ?)
            """,
            (
                cliente_id,
                package_id,
                name,
                textnorm._sanitize_text(data.description, allow_multiline=True),
                json.dumps(items, ensure_ascii=False),
                max(0, int(data.price_cents or 0)),
                max(1, min(3650, int(data.validity_days or 365))),
                1 if data.is_active else 0,
                int(next_order),
                now_iso,
                now_iso,
            ),
        )
        connection.commit()
    return _package_to_public(_get_package_row(cliente_id, package_id))


def _update_package(cliente_id: str, package_id: str, data: Any) -> Dict[str, Any]:
    row = _get_package_row(cliente_id, package_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bono no encontrado.")
    fields_set = set(getattr(data, "model_fields_set", set()))
    name = textnorm._sanitize_text(data.name) if "name" in fields_set else row["name"]
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="El nombre del bono es obligatorio.")
    items_json = (
        json.dumps(_normalize_package_items(cliente_id, data.items), ensure_ascii=False)
        if "items" in fields_set else row["items_json"]
    )
    with db._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE packages
            SET name = ?, description = ?, items_json = ?, price_cents = ?,
                validity_days = ?, is_active = ?, updated_at = ?
            WHERE cliente_id = ? AND id = ?
            """,
            (
                name,
                textnorm._sanitize_text(data.description, allow_multiline=True)
                if "description" in fields_set else (row["description"] or ""),
                items_json,
                max(0, int(data.price_cents)) if "price_cents" in fields_set else int(row["price_cents"] or 0),
                max(1, min(3650, int(data.validity_days))) if "validity_days" in fields_set else int(row["validity_days"] or 365),
                (1 if data.is_active else 0) if "is_active" in fields_set else row["is_active"],
                timeutils._utc_now_iso(),
                cliente_id,
                package_id,
            ),
        )
        connection.commit()
    return _package_to_public(_get_package_row(cliente_id, package_id))


def _delete_package(cliente_id: str, package_id: str) -> None:
    if not _get_package_row(cliente_id, package_id):
        raise HTTPException(status_code=404, detail="Bono no encontrado.")
    with db._get_db_connection() as connection:
        connection.execute(
            "DELETE FROM packages WHERE cliente_id = ? AND id = ?", (cliente_id, package_id)
        )
        connection.commit()


def _purchase_to_public(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        remaining = json.loads(row["remaining_json"] or "{}")
    except (ValueError, TypeError):
        remaining = {}
    return {
        "purchase_id": row["id"],
        "package_id": row["package_id"],
        "package_name": row["package_name"] or "",
        "buyer_name": row["buyer_name"] or "",
        "buyer_email": row["buyer_email"] or "",
        "buyer_phone": row["buyer_phone"] or "",
        "price_cents": int(row["price_cents"] or 0),
        "remaining": remaining,
        "remaining_total": sum(int(v) for v in remaining.values()),
        "expires_at": row["expires_at"] or "",
        "status": row["status"] or "active",
        "created_at": row["created_at"],
    }


def _refresh_purchase_expiry(connection: sqlite3.Connection, row: sqlite3.Row) -> sqlite3.Row:
    """Caducidad lazy: marca expired si pasó la fecha."""
    if (
        row["status"] == "active"
        and (row["expires_at"] or "")
        and row["expires_at"] < timeutils._utc_now_iso()
    ):
        connection.execute(
            "UPDATE package_purchases SET status = 'expired', updated_at = ? WHERE id = ?",
            (timeutils._utc_now_iso(), row["id"]),
        )
        connection.commit()
        return connection.execute(
            "SELECT * FROM package_purchases WHERE id = ?", (row["id"],)
        ).fetchone()
    return row


def _sell_package(cliente_id: str, package_id: str, data: Any) -> Dict[str, Any]:
    row = _get_package_row(cliente_id, package_id)
    if not row or not bool(row["is_active"]):
        raise HTTPException(status_code=404, detail="Bono no disponible.")
    buyer_email = textnorm._sanitize_text(getattr(data, "buyer_email", "") or "").lower()
    buyer_phone = textnorm._sanitize_text(getattr(data, "buyer_phone", "") or "")
    if not buyer_email and not buyer_phone:
        raise HTTPException(status_code=400, detail="Indica el email o telefono del comprador para poder redimir el bono.")
    try:
        items = json.loads(row["items_json"] or "[]")
    except (ValueError, TypeError):
        items = []
    remaining: Dict[str, int] = {}
    for item in items:
        slug = str(item.get("service_slug", ""))
        if slug:
            remaining[slug] = remaining.get(slug, 0) + int(item.get("qty", 0) or 0)
    if not remaining:
        raise HTTPException(status_code=409, detail="El bono no tiene sesiones configuradas.")
    purchase_id = f"pkp_{secrets.token_urlsafe(8)}"
    now = timeutils._utc_now()
    expires_at = (now + timedelta(days=int(row["validity_days"] or 365))).isoformat()
    location_id = agenda._resolve_location_id(cliente_id, getattr(data, "location_id", "") or "", require_active=False)
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO package_purchases (id, cliente_id, package_id, package_name, buyer_name,
                                           buyer_email, buyer_phone, price_cents, remaining_json,
                                           expires_at, status, payment_method, location_id,
                                           created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
            """,
            (
                purchase_id,
                cliente_id,
                package_id,
                row["name"],
                textnorm._sanitize_text(getattr(data, "buyer_name", "") or ""),
                buyer_email,
                buyer_phone,
                int(row["price_cents"] or 0),
                json.dumps(remaining, ensure_ascii=False),
                expires_at,
                _normalize_payment_method(getattr(data, "payment_method", "") or ""),
                location_id,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.commit()
        purchase = connection.execute(
            "SELECT * FROM package_purchases WHERE id = ?", (purchase_id,)
        ).fetchone()
    return _purchase_to_public(purchase)


def _list_package_purchases(
    cliente_id: str, *, q: str = "", status: str = "", limit: int = 200
) -> List[Dict[str, Any]]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if status:
        clauses.append("status = ?")
        params.append(status)
    if q:
        clauses.append("(buyer_name LIKE ? OR buyer_email LIKE ? OR buyer_phone LIKE ? OR package_name LIKE ?)")
        like = f"%{q.strip()}%"
        params.extend([like, like, like, like])
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM package_purchases WHERE " + " AND ".join(clauses)
            + " ORDER BY created_at DESC LIMIT ?",
            tuple(params) + (max(1, min(500, limit)),),
        ).fetchall()
        rows = [_refresh_purchase_expiry(connection, row) for row in rows]
    return [_purchase_to_public(row) for row in rows]


def _redeem_package_for_booking(cliente_id: str, purchase_id: str, booking_id: str) -> Dict[str, Any]:
    booking_row = booking._get_booking_row_by_id(booking_id)
    if not booking_row or booking_row["cliente_id"] != cliente_id:
        raise HTTPException(status_code=404, detail="Cita no encontrada.")
    if booking_row["payment_status"] == "paid":
        raise HTTPException(status_code=409, detail="Esta cita ya esta pagada.")
    service_slug = booking_row["service_id"] or ""
    if not service_slug:
        raise HTTPException(status_code=409, detail="La cita no tiene un servicio del catalogo asociado.")
    with db._get_db_connection() as connection:
        purchase = connection.execute(
            "SELECT * FROM package_purchases WHERE id = ? AND cliente_id = ? LIMIT 1",
            (purchase_id, cliente_id),
        ).fetchone()
        if not purchase:
            raise HTTPException(status_code=404, detail="Bono no encontrado.")
        purchase = _refresh_purchase_expiry(connection, purchase)
        if purchase["status"] != "active":
            raise HTTPException(status_code=409, detail=f"El bono no esta activo (estado: {purchase['status']}).")
        try:
            remaining = json.loads(purchase["remaining_json"] or "{}")
        except (ValueError, TypeError):
            remaining = {}
        left = int(remaining.get(service_slug, 0) or 0)
        if left < 1:
            raise HTTPException(
                status_code=409,
                detail="El bono no tiene sesiones restantes para este servicio.",
            )
        remaining[service_slug] = left - 1
        new_status = "used" if all(int(v) <= 0 for v in remaining.values()) else "active"
        connection.execute(
            "UPDATE package_purchases SET remaining_json = ?, status = ?, updated_at = ? WHERE id = ?",
            (json.dumps(remaining, ensure_ascii=False), new_status, timeutils._utc_now_iso(), purchase_id),
        )
        connection.commit()
    booking._update_booking_record(booking_id, payment_status="paid")
    booking._record_booking_audit(
        booking_id,
        cliente_id,
        "package_redeemed",
        {
            "purchase_id": purchase_id,
            "package_name": purchase["package_name"] or "",
            "service_slug": service_slug,
            "remaining_after": remaining,
        },
    )
    return {
        "ok": True,
        "purchase_id": purchase_id,
        "service_slug": service_slug,
        "remaining": remaining,
        "purchase_status": new_status,
    }


# ---------------------------------------------------------------------------
# Tarjetas regalo
# ---------------------------------------------------------------------------


def _generate_gift_card_code(connection: sqlite3.Connection, cliente_id: str) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin O/0/I/1 (legibilidad)
    while True:
        raw = "".join(secrets.choice(alphabet) for _ in range(8))
        code = f"GC-{raw[:4]}-{raw[4:]}"
        if not connection.execute(
            "SELECT 1 FROM gift_cards WHERE cliente_id = ? AND code = ?", (cliente_id, code)
        ).fetchone():
            return code


def _gift_card_to_public(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "gift_card_id": row["id"],
        "code": row["code"],
        "initial_cents": int(row["initial_cents"] or 0),
        "balance_cents": int(row["balance_cents"] or 0),
        "status": row["status"] or "active",
        "buyer_name": row["buyer_name"] or "",
        "buyer_email": row["buyer_email"] or "",
        "recipient_name": row["recipient_name"] or "",
        "recipient_email": row["recipient_email"] or "",
        "notes": row["notes"] or "",
        "expires_at": row["expires_at"] or "",
        "created_at": row["created_at"],
    }


def _refresh_gift_card_expiry(connection: sqlite3.Connection, row: sqlite3.Row) -> sqlite3.Row:
    if (
        row["status"] == "active"
        and (row["expires_at"] or "")
        and row["expires_at"] < timeutils._utc_now_iso()
    ):
        connection.execute(
            "UPDATE gift_cards SET status = 'expired', updated_at = ? WHERE id = ?",
            (timeutils._utc_now_iso(), row["id"]),
        )
        connection.commit()
        return connection.execute("SELECT * FROM gift_cards WHERE id = ?", (row["id"],)).fetchone()
    return row


def _issue_gift_card(cliente_id: str, data: Any) -> Dict[str, Any]:
    amount = int(data.amount_cents or 0)
    if amount < 100:
        raise HTTPException(status_code=400, detail="El importe minimo de la tarjeta regalo es 1 EUR.")
    now = timeutils._utc_now()
    validity_days = int(getattr(data, "validity_days", 0) or 0)
    expires_at = (now + timedelta(days=validity_days)).isoformat() if validity_days > 0 else ""
    card_id = f"gc_{secrets.token_urlsafe(8)}"
    location_id = agenda._resolve_location_id(cliente_id, getattr(data, "location_id", "") or "", require_active=False)
    with db._get_db_connection() as connection:
        code = _generate_gift_card_code(connection, cliente_id)
        connection.execute(
            """
            INSERT INTO gift_cards (id, cliente_id, code, initial_cents, balance_cents, currency,
                                    status, buyer_name, buyer_email, recipient_name, recipient_email,
                                    notes, expires_at, location_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'eur', 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card_id,
                cliente_id,
                code,
                amount,
                amount,
                textnorm._sanitize_text(getattr(data, "buyer_name", "") or ""),
                textnorm._sanitize_text(getattr(data, "buyer_email", "") or "").lower(),
                textnorm._sanitize_text(getattr(data, "recipient_name", "") or ""),
                textnorm._sanitize_text(getattr(data, "recipient_email", "") or "").lower(),
                textnorm._sanitize_text(getattr(data, "notes", "") or "", allow_multiline=True),
                expires_at,
                location_id,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT INTO gift_card_transactions (cliente_id, gift_card_id, kind, amount_cents,
                                                balance_after_cents, notes, created_at)
            VALUES (?, ?, 'issue', ?, ?, '', ?)
            """,
            (cliente_id, card_id, amount, amount, now.isoformat()),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM gift_cards WHERE id = ?", (card_id,)).fetchone()
    return _gift_card_to_public(row)


def _list_gift_cards(cliente_id: str, *, q: str = "", status: str = "", limit: int = 200) -> List[Dict[str, Any]]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if status:
        clauses.append("status = ?")
        params.append(status)
    if q:
        clauses.append("(code LIKE ? OR buyer_name LIKE ? OR buyer_email LIKE ? OR recipient_name LIKE ?)")
        like = f"%{q.strip()}%"
        params.extend([like, like, like, like])
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM gift_cards WHERE " + " AND ".join(clauses)
            + " ORDER BY created_at DESC LIMIT ?",
            tuple(params) + (max(1, min(500, limit)),),
        ).fetchall()
        rows = [_refresh_gift_card_expiry(connection, row) for row in rows]
    return [_gift_card_to_public(row) for row in rows]


def _get_gift_card_by_code(cliente_id: str, code: str) -> Optional[sqlite3.Row]:
    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM gift_cards WHERE cliente_id = ? AND code = ? LIMIT 1",
            (cliente_id, normalized),
        ).fetchone()
        if row:
            row = _refresh_gift_card_expiry(connection, row)
    return row


def _set_gift_card_status(cliente_id: str, gift_card_id: str, enabled: bool) -> Dict[str, Any]:
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM gift_cards WHERE cliente_id = ? AND id = ? LIMIT 1",
            (cliente_id, gift_card_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tarjeta regalo no encontrada.")
        if enabled and row["status"] == "disabled":
            new_status = "active" if int(row["balance_cents"] or 0) > 0 else "redeemed"
        elif not enabled:
            new_status = "disabled"
        else:
            new_status = row["status"]
        connection.execute(
            "UPDATE gift_cards SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, timeutils._utc_now_iso(), gift_card_id),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM gift_cards WHERE id = ?", (gift_card_id,)).fetchone()
    return _gift_card_to_public(row)


def _redeem_gift_card_for_booking(
    cliente_id: str, code: str, booking_id: str, *, amount_cents: Optional[int] = None
) -> Dict[str, Any]:
    booking_row = booking._get_booking_row_by_id(booking_id)
    if not booking_row or booking_row["cliente_id"] != cliente_id:
        raise HTTPException(status_code=404, detail="Cita no encontrada.")
    if booking_row["payment_status"] == "paid":
        raise HTTPException(status_code=409, detail="Esta cita ya esta pagada.")
    card = _get_gift_card_by_code(cliente_id, code)
    if not card:
        raise HTTPException(status_code=404, detail="Tarjeta regalo no encontrada. Revisa el codigo.")
    if card["status"] != "active":
        raise HTTPException(status_code=409, detail=f"La tarjeta no esta activa (estado: {card['status']}).")
    due = int(amount_cents) if amount_cents else int(booking_row["service_price_cents"] or 0)
    if due < 1:
        raise HTTPException(
            status_code=409,
            detail="La cita no tiene importe asociado. Indica el importe a cobrar.",
        )
    balance = int(card["balance_cents"] or 0)
    charge = min(balance, due)
    new_balance = balance - charge
    covered = charge >= due
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE gift_cards SET balance_cents = ?, status = ?, updated_at = ? WHERE id = ?",
            (new_balance, "redeemed" if new_balance <= 0 else "active", now_iso, card["id"]),
        )
        connection.execute(
            """
            INSERT INTO gift_card_transactions (cliente_id, gift_card_id, kind, amount_cents,
                                                balance_after_cents, booking_id, notes, created_at)
            VALUES (?, ?, 'redeem', ?, ?, ?, ?, ?)
            """,
            (cliente_id, card["id"], charge, new_balance, booking_id,
             "" if covered else f"pago parcial, pendiente {due - charge}", now_iso),
        )
        connection.commit()
    if covered:
        booking._update_booking_record(booking_id, payment_status="paid")
    booking._record_booking_audit(
        booking_id,
        cliente_id,
        "gift_card_redeemed" if covered else "gift_card_partial",
        {
            "code": card["code"],
            "charged_cents": charge,
            "balance_after_cents": new_balance,
            "remaining_due_cents": max(0, due - charge),
        },
    )
    return {
        "ok": True,
        "code": card["code"],
        "charged_cents": charge,
        "balance_after_cents": new_balance,
        "covered": covered,
        "remaining_due_cents": max(0, due - charge),
    }
