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
import os
import re
import secrets
import sqlite3
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from backend import agenda, booking, db, settings, stripe_gateway, textnorm, timeutils

PAYMENT_METHODS = {"cash", "card", "transfer", "stripe", "gift_card", "other"}
_COMMERCE_INFO_MARKER = "TARJETAS REGALO, BONOS Y PRODUCTOS:"
_COMMERCE_BAD_LINE_RE = re.compile(
    r"\b(no especificado|no detectado|no aplica|ninguno|sin productos|sin bonos|sin tarjetas|"
    r"no hay productos|no hay bonos|no hay tarjetas)\b",
    re.IGNORECASE,
)
_COMMERCE_SECTION_HEADER_RE = re.compile(r"^[A-ZÁÉÍÓÚÜÑ0-9][A-ZÁÉÍÓÚÜÑ0-9\s/(),.-]{3,}:\s*$")


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


def _read_client_info_for_commerce(cliente_id: str) -> str:
    path = settings.DATA_DIR / cliente_id / "info.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _commerce_section_from_info(info_txt: str) -> str:
    if not info_txt:
        return ""
    marker_pos = textnorm._strip_accents(info_txt).upper().find(
        textnorm._strip_accents(_COMMERCE_INFO_MARKER).upper()
    )
    if marker_pos < 0:
        return ""
    section = info_txt[marker_pos:]
    lines: List[str] = []
    for index, raw in enumerate(section.splitlines()):
        line = raw.rstrip()
        if index > 0 and _COMMERCE_SECTION_HEADER_RE.match(line.strip()):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _commerce_clean_line(raw: str) -> str:
    line = re.sub(r"^\s*(?:[-*•·]|\d+[\.)])\s*", "", str(raw or "").strip())
    line = re.sub(r"\s+", " ", line).strip()
    return textnorm._sanitize_text(line, allow_multiline=False)


def _commerce_line_is_real(line: str) -> bool:
    clean = _commerce_clean_line(line)
    if len(clean) < 4:
        return False
    if clean.endswith(":") and len(clean.split()) <= 5:
        return False
    if _COMMERCE_BAD_LINE_RE.search(clean):
        return False
    return True


def _commerce_section_lines(info_txt: str) -> List[str]:
    section = _commerce_section_from_info(info_txt)
    if not section:
        return []
    lines = []
    for raw in section.splitlines()[1:]:
        clean = _commerce_clean_line(raw)
        if _commerce_line_is_real(clean):
            lines.append(clean)
    return lines[:120]


def _commerce_has_signal(lines: List[str], keywords: Tuple[str, ...]) -> bool:
    joined = textnorm._strip_accents("\n".join(lines).lower())
    return any(keyword in joined for keyword in keywords)


def _commerce_name_from_line(line: str, prefixes: Tuple[str, ...]) -> str:
    clean = _commerce_clean_line(line)
    clean = re.sub(r"\s*(?:/|\||·|•|–|—)\s*", " / ", clean)
    for prefix in prefixes:
        m = re.match(rf"^{re.escape(prefix)}\s*:\s*(.+)$", clean, flags=re.IGNORECASE)
        if m:
            clean = m.group(1).strip()
            break
    clean = re.sub(r"\b(?:precio|importe|tarifa)\s*:\s*.*$", "", clean, flags=re.IGNORECASE).strip()
    clean = re.split(r"\s+-\s+|\s+/\s+", clean, maxsplit=1)[0].strip()
    clean = re.sub(r"\s+\d[\d\s.,]*\s*(?:€|eur|euros?).*$", "", clean, flags=re.IGNORECASE).strip()
    return textnorm._sanitize_text(clean)[:120]


def _commerce_stock_from_line(line: str) -> Optional[int]:
    m = re.search(r"\b(?:stock|unidades|existencias)\s*[:=]?\s*(\d{1,5})\b", line, re.IGNORECASE)
    if not m:
        return None
    return max(0, min(99999, int(m.group(1))))


def _commerce_price_to_cents(line: str) -> int:
    candidates: List[int] = []
    for m in re.finditer(r"\b(\d[\d\s.,]*)\s*(?:€|eur|euros?)\b", line, re.IGNORECASE):
        candidates.append(textnorm._parse_price_to_cents(m.group(0)))
    for m in re.finditer(r"(?:€|eur|euros?)\s*(\d[\d\s.,]*)\b", line, re.IGNORECASE):
        candidates.append(textnorm._parse_price_to_cents(m.group(0)))
    candidates = [c for c in candidates if c > 0]
    return max(candidates) if candidates else 0


def _commerce_package_qty(line: str) -> int:
    m = re.search(r"\b(\d{1,3})\s*(?:sesiones|sessiones|sessions|usos|visitas)\b", line, re.IGNORECASE)
    if not m:
        return 0
    return max(1, min(100, int(m.group(1))))


def _commerce_infer_service_slug(cliente_id: str, line: str) -> str:
    services: List[Dict[str, Any]] = []
    try:
        with db._get_db_connection() as connection:
            rows = connection.execute(
                "SELECT slug, name FROM services WHERE cliente_id = ?",
                (cliente_id,),
            ).fetchall()
        services.extend({"id": row["slug"], "nombre": row["name"]} for row in rows)
    except Exception:  # noqa: BLE001
        pass
    if not services:
        try:
            services.extend(agenda._extract_services_from_info(cliente_id))
        except Exception:  # noqa: BLE001
            pass
    if not services:
        return ""
    norm_line = textnorm._strip_accents(line.lower())
    matches: List[Tuple[int, str]] = []
    for svc in services:
        name = str(svc.get("nombre") or svc.get("name") or "")
        slug = str(svc.get("id") or svc.get("slug") or "")
        if not name or not slug:
            continue
        norm_name = textnorm._strip_accents(name.lower())
        if norm_name and norm_name in norm_line:
            matches.append((len(norm_name), slug))
    if matches:
        matches.sort(reverse=True)
        return matches[0][1]
    if len(services) == 1:
        return str(services[0].get("id") or services[0].get("slug") or "")
    return ""


def _extract_commerce_from_info_text(cliente_id: str, info_txt: str) -> Dict[str, Any]:
    lines = _commerce_section_lines(info_txt)
    if not lines:
        return {"products": [], "packages": [], "gift_knowledge": "", "has_gift": False}

    products: List[Dict[str, Any]] = []
    packages: List[Dict[str, Any]] = []
    gift_lines: List[str] = []
    mode = ""

    for line in lines:
        lower = textnorm._strip_accents(line.lower())
        if re.match(r"^(tarjetas?\s+regalo|gift\s*cards?|cheques?\s+regalo)\s*:", lower):
            mode = "gift"
            if _commerce_line_is_real(line.split(":", 1)[-1]):
                gift_lines.append(line)
            continue
        if re.match(r"^(bonos?|paquetes?)\s*:", lower):
            mode = "package"
            if _commerce_line_is_real(line.split(":", 1)[-1]):
                line = line.split(":", 1)[-1].strip()
            else:
                continue
        elif re.match(r"^(productos?|tienda)\s*:", lower):
            mode = "product"
            if _commerce_line_is_real(line.split(":", 1)[-1]):
                line = line.split(":", 1)[-1].strip()
            else:
                continue
        elif lower.startswith("condiciones"):
            mode = "gift"
            gift_lines.append(line)
            continue

        if "tarjeta" in lower and "regalo" in lower:
            gift_lines.append(line)
            mode = "gift"
            continue

        price_cents = _commerce_price_to_cents(line)
        is_package = mode == "package" or "bono" in lower or "paquete" in lower
        is_product = mode == "product" or lower.startswith("producto:") or " producto " in f" {lower} "

        if is_package:
            qty = _commerce_package_qty(line)
            service_slug = _commerce_infer_service_slug(cliente_id, line)
            name = _commerce_name_from_line(line, ("Bono", "Paquete"))
            if name and qty and service_slug and price_cents > 0:
                packages.append({
                    "name": name,
                    "description": line,
                    "items": [{"service_slug": service_slug, "qty": qty}],
                    "price_cents": price_cents,
                    "validity_days": 365,
                })
            else:
                gift_lines.append(line) if "tarjeta" in lower else None
            continue

        if is_product:
            name = _commerce_name_from_line(line, ("Producto", "Tienda"))
            if name and price_cents > 0:
                products.append({
                    "name": name,
                    "description": line,
                    "price_cents": price_cents,
                    "stock": _commerce_stock_from_line(line),
                })
            continue

        if mode == "gift":
            gift_lines.append(line)

    # Si el sitio habla de tarjetas regalo, guardamos el bloque completo como conocimiento,
    # pero sin crear nada cuando solo hay placeholders.
    has_gift = _commerce_has_signal(gift_lines, ("tarjeta regalo", "tarjetas regalo", "gift card", "cheque regalo"))
    gift_knowledge = "\n".join(dict.fromkeys(gift_lines)).strip() if has_gift else ""

    # Dedup por nombre normalizado para no duplicar ruido del scraper.
    product_map = {agenda._normalize_service_id(p["name"]): p for p in products if agenda._normalize_service_id(p["name"])}
    package_map = {agenda._normalize_service_id(p["name"]): p for p in packages if agenda._normalize_service_id(p["name"])}
    return {
        "products": list(product_map.values())[:50],
        "packages": list(package_map.values())[:30],
        "gift_knowledge": gift_knowledge[:GIFT_PUBLIC_ASSISTANT_KNOWLEDGE_MAX_CHARS],
        "has_gift": bool(gift_knowledge),
    }


def _table_count(cliente_id: str, table: str) -> int:
    with db._get_db_connection() as connection:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE cliente_id = ?",
                (cliente_id,),
            ).fetchone()[0]
        )


def _infer_gift_validity_days(text: str, fallback: int) -> int:
    norm = textnorm._strip_accents(text.lower())
    if re.search(r"\b(no\s+caduc|sin\s+caduc|no\s+expir|sin\s+expir)", norm):
        return 0
    m = re.search(r"\b(\d{1,4})\s*(dias?|days?)\b", norm)
    if m:
        return max(0, min(3650, int(m.group(1))))
    m = re.search(r"\b(\d{1,3})\s*(mes|meses|months?)\b", norm)
    if m:
        return max(0, min(3650, int(m.group(1)) * 30))
    m = re.search(r"\b(\d{1,2})\s*(ano|anos|años|year|years)\b", norm)
    if m:
        return max(0, min(3650, int(m.group(1)) * 365))
    return fallback


def _merge_knowledge(existing: str, incoming: str, max_chars: int) -> str:
    lines: List[str] = []
    seen = set()
    for block in (existing or "", incoming or ""):
        for raw in str(block).splitlines():
            line = _commerce_clean_line(raw)
            if not _commerce_line_is_real(line):
                continue
            key = textnorm._strip_accents(line.lower())
            if key in seen:
                continue
            seen.add(key)
            lines.append(line)
    return "\n".join(lines).strip()[:max_chars]


def _update_scraped_commerce_config(
    cliente_id: str,
    *,
    products_created: int,
    packages_created: int,
    gift_knowledge: str,
) -> bool:
    if not products_created and not packages_created and not gift_knowledge:
        return False
    from backend import appstate, clients  # tardio: evita ciclos

    with appstate.state_lock:
        next_configs = json.loads(json.dumps(appstate.CONFIG_CLIENTES))
    cfg = dict(next_configs.get(cliente_id, {}) or {})
    changed = False

    if products_created or packages_created:
        shop_cfg = dict(cfg.get("shop_public", {}) or {})
        if products_created and not shop_cfg.get("enabled_products"):
            shop_cfg["enabled_products"] = True
            changed = True
        if packages_created and not shop_cfg.get("enabled_packages"):
            shop_cfg["enabled_packages"] = True
            changed = True
        if not shop_cfg.get("intro_text"):
            shop_cfg["intro_text"] = "Compra online productos y bonos del negocio."
            changed = True
        cfg["shop_public"] = shop_cfg

    if gift_knowledge:
        gift_cfg = dict(cfg.get("gift_cards_public", {}) or {})
        merged = _merge_knowledge(
            str(gift_cfg.get("assistant_knowledge") or ""),
            gift_knowledge,
            GIFT_PUBLIC_ASSISTANT_KNOWLEDGE_MAX_CHARS,
        )
        if merged != str(gift_cfg.get("assistant_knowledge") or ""):
            gift_cfg["assistant_knowledge"] = merged
            changed = True
        if not gift_cfg.get("enabled"):
            gift_cfg["enabled"] = True
            changed = True
        inferred_days = _infer_gift_validity_days(merged, int(gift_cfg.get("validity_days") or 365))
        if inferred_days != int(gift_cfg.get("validity_days") or 365):
            gift_cfg["validity_days"] = inferred_days
            changed = True
        cfg["gift_cards_public"] = gift_cfg

    if not changed:
        return False
    next_configs[cliente_id] = cfg
    clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    return True


def _seed_commerce_from_info(cliente_id: str, info_txt: str = "") -> Dict[str, int]:
    """Siembra productos/bonos/tarjetas detectados por el scraper.

    Conservador por diseño: si no hay señales reales no hace nada; si ya existe
    catalogo manual de productos o bonos, no lo pisa.
    """
    info_txt = info_txt or _read_client_info_for_commerce(cliente_id)
    extracted = _extract_commerce_from_info_text(cliente_id, info_txt)
    products_created = 0
    packages_created = 0

    now = timeutils._utc_now_iso()
    if extracted["products"] and _table_count(cliente_id, "products") == 0:
        with db._get_db_connection() as connection:
            for idx, product in enumerate(extracted["products"]):
                product_id = _unique_catalog_id(connection, "products", cliente_id, product["name"])
                connection.execute(
                    """
                    INSERT INTO products (cliente_id, id, name, description, price_cents, currency,
                                          stock, is_active, sort_order, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'eur', ?, 1, ?, ?, ?)
                    """,
                    (
                        cliente_id,
                        product_id,
                        textnorm._sanitize_text(product["name"])[:120],
                        textnorm._sanitize_text(product.get("description") or "", allow_multiline=True)[:800],
                        max(0, int(product.get("price_cents") or 0)),
                        product.get("stock"),
                        idx,
                        now,
                        now,
                    ),
                )
                products_created += 1
            connection.commit()

    if extracted["packages"] and _table_count(cliente_id, "packages") == 0:
        try:
            agenda._ensure_services_seeded(cliente_id)
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("No se pudieron sembrar servicios antes de bonos %s: %s", cliente_id, exc)
        with db._get_db_connection() as connection:
            for idx, package in enumerate(extracted["packages"]):
                try:
                    items = _normalize_package_items(cliente_id, package.get("items") or [])
                except HTTPException:
                    continue
                package_id = _unique_catalog_id(connection, "packages", cliente_id, package["name"])
                connection.execute(
                    """
                    INSERT INTO packages (cliente_id, id, name, description, items_json, price_cents,
                                          currency, validity_days, is_active, sort_order, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'eur', ?, 1, ?, ?, ?)
                    """,
                    (
                        cliente_id,
                        package_id,
                        textnorm._sanitize_text(package["name"])[:120],
                        textnorm._sanitize_text(package.get("description") or "", allow_multiline=True)[:800],
                        json.dumps(items, ensure_ascii=False),
                        max(0, int(package.get("price_cents") or 0)),
                        max(1, min(3650, int(package.get("validity_days") or 365))),
                        idx,
                        now,
                        now,
                    ),
                )
                packages_created += 1
            connection.commit()

    config_updated = _update_scraped_commerce_config(
        cliente_id,
        products_created=products_created,
        packages_created=packages_created,
        gift_knowledge=extracted.get("gift_knowledge") or "",
    )
    return {
        "products_created": products_created,
        "packages_created": packages_created,
        "gift_knowledge": 1 if extracted.get("gift_knowledge") else 0,
        "config_updated": 1 if config_updated else 0,
    }


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
        "image_url": _row_image_url(row),
    }


def _row_image_url(row: sqlite3.Row) -> str:
    try:
        return str(row["image_url"] or "")
    except (KeyError, IndexError):
        return ""


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
                                  stock, is_active, sort_order, image_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'eur', ?, ?, ?, ?, ?, ?)
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
                textnorm._public_image_url(data.image_url),
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
            SET name = ?, description = ?, price_cents = ?, stock = ?, is_active = ?, image_url = ?, updated_at = ?
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
                textnorm._public_image_url(data.image_url) if "image_url" in fields_set else _row_image_url(row),
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
    """Devuelve un <img> PNG (data-URI) con el QR del enlace de pago, listo para
    inyectar en el panel. Cadena vacia si segno no esta disponible (cae al enlace).

    Se usa PNG raster (no SVG): el writer SVG de segno dibuja los modulos como
    lineas con `stroke`, que al escalar producen grosores desiguales y un QR
    ilegible. El PNG a escala alta es exacto y se escanea siempre.
    Robustez: border=4 (quiet zone del spec), fondo blanco solido (contraste),
    error="m" (~15% correccion). Nombre historico por compat del campo `qr_svg`."""
    if not url:
        return ""
    try:
        import base64
        import io
        import segno
        buf = io.BytesIO()
        segno.make(url, error="m").save(
            buf, kind="png", scale=10, border=4, dark="#000000", light="#ffffff",
        )
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f'<img class="vqr" alt="Codigo QR de pago" src="data:image/png;base64,{b64}">'
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
    if booking_id:
        booking_row = booking._get_booking_row_by_id(booking_id)
        if not booking_row or booking_row["cliente_id"] != cliente_id:
            raise HTTPException(status_code=404, detail="Cita no encontrada.")
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
        "image_url": _row_image_url(row),
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
                                  currency, validity_days, is_active, sort_order, image_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'eur', ?, ?, ?, ?, ?, ?)
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
                textnorm._public_image_url(data.image_url),
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
                validity_days = ?, is_active = ?, image_url = ?, updated_at = ?
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
                textnorm._public_image_url(data.image_url) if "image_url" in fields_set else _row_image_url(row),
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


def _purchase_initial_sessions(row: sqlite3.Row) -> Dict[str, int]:
    """Snapshot inicial de sesiones del bono (fallback: lo que quede)."""
    raw = ""
    if "initial_json" in row.keys():
        raw = row["initial_json"] or ""
    try:
        initial = json.loads(raw or row["remaining_json"] or "{}")
    except (ValueError, TypeError):
        initial = {}
    return {str(k): int(v or 0) for k, v in initial.items()}


def _package_wallet_url(cliente_id: str, wallet_token: str) -> str:
    if not wallet_token:
        return ""
    base = textnorm._preferred_public_base_url().rstrip("/")
    return f"{base}/bono/{cliente_id}/{wallet_token}"


def _purchase_to_public(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        remaining = json.loads(row["remaining_json"] or "{}")
    except (ValueError, TypeError):
        remaining = {}
    initial = _purchase_initial_sessions(row)
    wallet_token = row["wallet_token"] if "wallet_token" in row.keys() else ""
    remaining_total = sum(int(v) for v in remaining.values())
    initial_total = max(sum(initial.values()), remaining_total)
    return {
        "purchase_id": row["id"],
        "package_id": row["package_id"],
        "package_name": row["package_name"] or "",
        "buyer_name": row["buyer_name"] or "",
        "buyer_email": row["buyer_email"] or "",
        "buyer_phone": row["buyer_phone"] or "",
        "price_cents": int(row["price_cents"] or 0),
        "remaining": remaining,
        "remaining_total": remaining_total,
        "initial_total": initial_total,
        "used_total": max(0, initial_total - remaining_total),
        "expires_at": row["expires_at"] or "",
        "status": row["status"] or "active",
        "created_at": row["created_at"],
        "wallet_url": _package_wallet_url(row["cliente_id"], wallet_token or ""),
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
    remaining_json = json.dumps(remaining, ensure_ascii=False)
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO package_purchases (id, cliente_id, package_id, package_name, buyer_name,
                                           buyer_email, buyer_phone, price_cents, remaining_json,
                                           initial_json, wallet_token, expires_at, status,
                                           payment_method, location_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
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
                remaining_json,
                remaining_json,
                f"pw_{secrets.token_urlsafe(18)}",
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
    # Venta de mostrador con email: el comprador recibe su bono digital (wallet)
    # igual que en la compra online. Best-effort, nunca rompe la venta.
    if buyer_email:
        try:
            _send_package_purchase_email(cliente_id, purchase_id)
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("Email de bono %s fallo: %s", purchase_id, exc)
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
        snapshot_json = purchase["remaining_json"] or "{}"
        remaining[service_slug] = left - 1
        new_status = "used" if all(int(v) <= 0 for v in remaining.values()) else "active"
        # CAS sobre el JSON leido: dos canjes concurrentes no pueden descontar
        # la misma sesion (el segundo no matchea y recibe 409).
        cursor = connection.execute(
            "UPDATE package_purchases SET remaining_json = ?, status = ?, updated_at = ? "
            "WHERE id = ? AND status = 'active' AND remaining_json = ?",
            (
                json.dumps(remaining, ensure_ascii=False), new_status,
                timeutils._utc_now_iso(), purchase_id, snapshot_json,
            ),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise HTTPException(
                status_code=409,
                detail="El bono se ha actualizado a la vez desde otro sitio. Vuelve a intentarlo.",
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
        clauses.append(
            "(code LIKE ? OR buyer_name LIKE ? OR buyer_email LIKE ? "
            "OR recipient_name LIKE ? OR recipient_email LIKE ?)"
        )
        like = f"%{q.strip()}%"
        params.extend([like, like, like, like, like])
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM gift_cards WHERE " + " AND ".join(clauses)
            + " ORDER BY created_at DESC LIMIT ?",
            tuple(params) + (max(1, min(500, limit)),),
        ).fetchall()
        rows = [_refresh_gift_card_expiry(connection, row) for row in rows]
    return [_gift_card_to_public(row) for row in rows]


def _normalize_gift_code(code: str) -> str:
    """Entrada tolerante del codigo GC-XXXX-XXXX: acepta minusculas, sin guiones o
    sin prefijo, y lo reconstruye al formato canonico."""
    raw = re.sub(r"[^A-Z0-9]", "", (code or "").upper())
    if raw.startswith("GC") and len(raw) > 8:
        raw = raw[2:]
    if len(raw) == 8:
        return f"GC-{raw[:4]}-{raw[4:]}"
    return (code or "").strip().upper()


def _get_gift_card_by_code(cliente_id: str, code: str) -> Optional[sqlite3.Row]:
    normalized = _normalize_gift_code(code)
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


def _gift_card_transaction_to_public(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "kind": row["kind"],
        "amount_cents": int(row["amount_cents"] or 0),
        "balance_after_cents": int(row["balance_after_cents"] or 0),
        "booking_id": row["booking_id"] or "",
        "sale_id": row["sale_id"] or "",
        "notes": row["notes"] or "",
        "created_at": row["created_at"],
    }


def _list_gift_card_transactions(cliente_id: str, gift_card_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM gift_card_transactions WHERE cliente_id = ? AND gift_card_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (cliente_id, gift_card_id, max(1, min(500, limit))),
        ).fetchall()
    return [_gift_card_transaction_to_public(row) for row in rows]


def _gift_card_detail(cliente_id: str, gift_card_id: str) -> Dict[str, Any]:
    """Tarjeta regalo + sus movimientos (emision, asignaciones y canjes) para la ficha
    del cliente / panel de Ventas."""
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM gift_cards WHERE cliente_id = ? AND id = ? LIMIT 1",
            (cliente_id, gift_card_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tarjeta regalo no encontrada.")
        row = _refresh_gift_card_expiry(connection, row)
    card = _gift_card_to_public(row)
    card["transactions"] = _list_gift_card_transactions(cliente_id, gift_card_id)
    return card


def _assign_gift_card_to_contact(
    cliente_id: str,
    *,
    gift_card_id: str = "",
    code: str = "",
    recipient_name: str = "",
    recipient_email: str = "",
    recipient_phone: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    """Asigna una tarjeta regalo EXISTENTE a un cliente (la pone a su nombre).

    Localiza la tarjeta por id o por codigo. Evita asignaciones duplicadas: si ya
    esta asignada a ese mismo cliente devuelve 409; si esta asignada a otro distinto
    exige ``force``. Deja rastro como movimiento ``assign`` para la trazabilidad."""
    name = textnorm._sanitize_text(recipient_name or "")
    email = textnorm._sanitize_text(recipient_email or "").lower()
    phone = textnorm._sanitize_text(recipient_phone or "")
    if not (name or email or phone):
        raise HTTPException(status_code=400, detail="Indica al menos nombre, email o telefono del cliente.")
    with db._get_db_connection() as connection:
        if gift_card_id:
            row = connection.execute(
                "SELECT * FROM gift_cards WHERE cliente_id = ? AND id = ? LIMIT 1",
                (cliente_id, gift_card_id),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM gift_cards WHERE cliente_id = ? AND code = ? LIMIT 1",
                (cliente_id, (code or "").strip().upper()),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tarjeta regalo no encontrada. Revisa el codigo.")
        row = _refresh_gift_card_expiry(connection, row)
        if row["status"] in {"disabled", "expired"}:
            raise HTTPException(
                status_code=409,
                detail=f"La tarjeta no esta disponible para asignar (estado: {row['status']}).",
            )
        current_email = (row["recipient_email"] or "").lower()
        current_name = row["recipient_name"] or ""
        already_same = (email and current_email == email) or (
            not email and not current_email and name and current_name == name
        )
        if already_same:
            raise HTTPException(status_code=409, detail="Esta tarjeta ya esta asignada a este cliente.")
        if (current_email or current_name) and not force:
            who = current_name or current_email
            raise HTTPException(
                status_code=409,
                detail=f"Esta tarjeta ya esta asignada a {who}. Marca reasignar para cambiarla.",
            )
        now_iso = timeutils._utc_now_iso()
        connection.execute(
            "UPDATE gift_cards SET recipient_name = ?, recipient_email = ?, updated_at = ? WHERE id = ?",
            (name or current_name, email or current_email, now_iso, row["id"]),
        )
        note_who = name or email or phone
        connection.execute(
            """
            INSERT INTO gift_card_transactions (cliente_id, gift_card_id, kind, amount_cents,
                                                balance_after_cents, notes, created_at)
            VALUES (?, ?, 'assign', 0, ?, ?, ?)
            """,
            (cliente_id, row["id"], int(row["balance_cents"] or 0), f"Asignada a {note_who}", now_iso),
        )
        connection.commit()
        card_id = row["id"]
    return _gift_card_detail(cliente_id, card_id)


def _redeem_gift_card_for_booking(
    cliente_id: str, code: str, booking_id: str, *, amount_cents: Optional[int] = None
) -> Dict[str, Any]:
    booking_row = booking._get_booking_row_by_id(booking_id)
    if not booking_row or booking_row["cliente_id"] != cliente_id:
        raise HTTPException(status_code=404, detail="Cita no encontrada.")
    if booking_row["payment_status"] == "paid":
        raise HTTPException(status_code=409, detail="Esta cita ya esta pagada.")
    due = int(amount_cents) if amount_cents else int(booking_row["service_price_cents"] or 0)
    if due < 1:
        raise HTTPException(
            status_code=409,
            detail="La cita no tiene importe asociado. Indica el importe a cobrar.",
        )
    normalized_code = _normalize_gift_code(code)
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        card = connection.execute(
            "SELECT * FROM gift_cards WHERE cliente_id = ? AND code = ? LIMIT 1",
            (cliente_id, normalized_code),
        ).fetchone()
        if not card:
            raise HTTPException(status_code=404, detail="Tarjeta regalo no encontrada. Revisa el codigo.")
        card = _refresh_gift_card_expiry(connection, card)
        if card["status"] != "active":
            raise HTTPException(status_code=409, detail=f"La tarjeta no esta activa (estado: {card['status']}).")
        balance = int(card["balance_cents"] or 0)
        charge = min(balance, due)
        new_balance = balance - charge
        covered = charge >= due
        # CAS sobre el saldo leido: dos canjes concurrentes del mismo codigo no
        # pueden gastar el mismo saldo (el segundo no matchea y recibe 409).
        cursor = connection.execute(
            "UPDATE gift_cards SET balance_cents = ?, status = ?, updated_at = ? "
            "WHERE id = ? AND status = 'active' AND balance_cents = ?",
            (new_balance, "redeemed" if new_balance <= 0 else "active", now_iso, card["id"], balance),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise HTTPException(
                status_code=409,
                detail="La tarjeta se ha usado a la vez desde otro sitio. Vuelve a intentarlo.",
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


# --- Compra PUBLICA de tarjetas regalo (jul 2026) ---------------------------------
# El cliente FINAL compra online (pagina /gift/{cliente_id}); el pago va por el MISMO
# rail que el POS (customer_payments + Stripe Connect + webhook idempotente) y la
# tarjeta se emite al confirmarse el pago (_finalize_gift_card_payment). Opt-in por
# tenant via config['gift_cards_public']. Plan: docs/PLAN_GIFT_CARDS_PUBLICO.md.

GIFT_PUBLIC_MIN_CENTS_DEFAULT = 1000       # 10 EUR
GIFT_PUBLIC_MAX_CENTS_DEFAULT = 50000      # 500 EUR
GIFT_PUBLIC_SUGGESTED_DEFAULT = [3000, 5000, 10000]
GIFT_PUBLIC_ASSISTANT_KNOWLEDGE_MAX_CHARS = 3000


def _gift_public_config(cliente_id: str) -> Dict[str, Any]:
    """Config saneada de la compra publica de tarjetas (default OFF)."""
    from backend import appstate  # tardio: evita ciclo en el arranque

    raw = ((appstate.CONFIG_CLIENTES.get(cliente_id) or {}).get("gift_cards_public") or {})

    def _cents(value: Any, default: int) -> int:
        try:
            v = int(value)
            return v if 100 <= v <= 100000 else default
        except (TypeError, ValueError):
            return default

    suggested = []
    for item in (raw.get("suggested_amounts") or GIFT_PUBLIC_SUGGESTED_DEFAULT):
        cents = _cents(item, 0)
        if cents and cents not in suggested:
            suggested.append(cents)
    return {
        "enabled": bool(raw.get("enabled")),
        "suggested_amounts": suggested[:6] or GIFT_PUBLIC_SUGGESTED_DEFAULT,
        "min_cents": _cents(raw.get("min_cents"), GIFT_PUBLIC_MIN_CENTS_DEFAULT),
        "max_cents": _cents(raw.get("max_cents"), GIFT_PUBLIC_MAX_CENTS_DEFAULT),
        "validity_days": max(0, min(3650, int(raw.get("validity_days") or 365))),
        "intro_text": textnorm._sanitize_text(str(raw.get("intro_text") or ""))[:300],
        "assistant_knowledge": textnorm._sanitize_text(
            str(raw.get("assistant_knowledge") or ""),
            allow_multiline=True,
        )[:GIFT_PUBLIC_ASSISTANT_KNOWLEDGE_MAX_CHARS],
    }


def gift_public_available(cliente_id: str) -> bool:
    """True si el tenant tiene la compra publica activa Y puede cobrar (Stripe Connect)."""
    cfg = _gift_public_config(cliente_id)
    if not cfg["enabled"]:
        return False
    try:
        account = booking._connect_account_status(cliente_id)
        return bool(account.connected and account.charges_enabled)
    except Exception:  # noqa: BLE001
        return False


def gift_public_prompt_block(cliente_id: str) -> str:
    """Bloque operativo para que chat/voz conozcan tarjetas regalo configuradas.

    El info.txt sigue siendo la fuente scrapeada. Este bloque es la capa editable
    por el negocio para condiciones que cambian o no estan bien publicadas.
    """
    cfg = _gift_public_config(cliente_id)
    knowledge = str(cfg.get("assistant_knowledge") or "").strip()
    if not cfg["enabled"] and not knowledge:
        return ""

    base = textnorm._preferred_public_base_url().rstrip("/")
    public_url = f"{base}/gift/{cliente_id}"
    try:
        available = gift_public_available(cliente_id)
    except Exception:  # noqa: BLE001
        available = False

    lines = [
        "TARJETAS REGALO (configuracion operativa del negocio)",
    ]
    if cfg["enabled"]:
        if available:
            lines.append(f"- Venta online activa: {public_url}")
        else:
            lines.append("- Venta online configurada pero no operativa ahora mismo; no prometas compra online.")
        suggested = ", ".join(f"{c // 100} EUR" for c in cfg["suggested_amounts"])
        lines.append(
            f"- Importes configurados: sugeridos {suggested}; minimo {cfg['min_cents'] // 100} EUR; "
            f"maximo {cfg['max_cents'] // 100} EUR."
        )
        if cfg["validity_days"] > 0:
            lines.append(f"- Caducidad configurada por defecto: {cfg['validity_days']} dias desde la compra.")
        else:
            lines.append("- Caducidad configurada por defecto: sin caducidad.")
        if cfg["intro_text"]:
            lines.append(f"- Texto publico: {cfg['intro_text']}")

    if knowledge:
        lines.append("Condiciones y respuestas configuradas para el asistente:")
        lines.append(knowledge)

    lines.append(
        "- Si preguntan detalles, responde con estas condiciones y la base documental; no digas solo que compren."
    )
    lines.append(
        "- Si faltan condiciones concretas, dilo y deriva al equipo humano en vez de inventarlas."
    )
    return "\n".join(lines)


def commerce_prompt_block(cliente_id: str) -> str:
    """Catalogo operativo de comercio para system prompt (chat, WhatsApp y voz)."""
    lines: List[str] = []
    try:
        products = _list_products(cliente_id, include_inactive=False)
    except Exception:  # noqa: BLE001
        products = []
    try:
        packages = _list_packages(cliente_id, include_inactive=False)
    except Exception:  # noqa: BLE001
        packages = []

    if products or packages:
        lines.append("CATALOGO REAL DE COMERCIO (productos, bonos y tarjetas)")
        for product in products[:30]:
            price = textnorm._format_price_cents(int(product.get("price_cents") or 0))
            stock = product.get("stock")
            stock_text = "" if stock is None else f" · stock {stock}"
            desc = str(product.get("description") or "").strip()
            lines.append(f"- Producto: {product['name']} · {price}{stock_text}" + (f" · {desc}" if desc else ""))
        for package in packages[:30]:
            price = textnorm._format_price_cents(int(package.get("price_cents") or 0))
            summary = ", ".join(_package_items_summary(cliente_id, package.get("items") or []))
            desc = str(package.get("description") or "").strip()
            parts = [f"- Bono: {package['name']}", price]
            if summary:
                parts.append(summary)
            if package.get("validity_days"):
                parts.append(f"validez {package['validity_days']} dias")
            if desc:
                parts.append(desc)
            lines.append(" · ".join(parts))
        lines.append(
            "- Para productos y bonos, esta lista manda sobre el texto scrapeado si hay contradicciones."
        )
        lines.append(
            "- Si preguntan por compra online, solo ofrece enlace si la tienda/tarjetas estan disponibles; si no, deriva a recepcion."
        )

    gift_block = gift_public_prompt_block(cliente_id)
    if gift_block:
        lines.append(gift_block)
    return "\n".join(lines).strip()


_GIFT_ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _gift_accent_or_empty(value: str) -> str:
    value = (value or "").strip()
    return value if _GIFT_ACCENT_RE.match(value) else ""


def _gift_resolve_service(cliente_id: str, service_slug: str) -> Optional[Dict[str, Any]]:
    """Servicio del catalogo REAL para una tarjeta 'por servicio': nombre + precio actual.
    None si no existe o no tiene precio fijo (>0). El precio SIEMPRE lo pone el servidor."""
    slug = textnorm._sanitize_text(service_slug or "").strip()
    if not slug:
        return None
    try:
        services = booking._public_services_for_booking(cliente_id)
    except Exception:  # noqa: BLE001
        return None
    for svc in services:
        if not isinstance(svc, dict):
            continue
        if str(svc.get("id") or svc.get("slug") or "") == slug:
            price = int(svc.get("price_cents") or 0)
            name = textnorm._sanitize_text(str(svc.get("nombre") or svc.get("name") or ""))
            if price > 0 and name:
                return {"name": name, "price_cents": price}
            return None
    return None


def create_gift_card_payment_link(
    cliente_id: str, *,
    amount_cents: int,
    buyer_name: str,
    buyer_email: str,
    recipient_name: str,
    recipient_email: str,
    message: str = "",
    scheduled_send_at: str = "",
    base_url: str = "",
    service_slug: str = "",
    accent_color: str = "",
    hide_value: bool = False,
    hide_expiry: bool = False,
) -> Dict[str, Any]:
    """Checkout de Stripe (cuenta Connect del negocio) para UNA tarjeta regalo comprada
    por el cliente final. La tarjeta NO se emite aqui: se materializa en el webhook al
    pasar a 'paid' (_finalize_gift_card_payment), evitando tarjetas fantasma."""
    cfg = _gift_public_config(cliente_id)
    if not cfg["enabled"]:
        raise HTTPException(status_code=404, detail="La compra de tarjetas regalo no esta disponible.")
    # Por SERVICIO: el precio manda el catalogo del servidor (se ignora el importe del cliente).
    service = _gift_resolve_service(cliente_id, service_slug)
    service_name = ""
    if service_slug and not service:
        raise HTTPException(status_code=400, detail="Ese servicio no esta disponible para tarjeta regalo.")
    if service:
        amount = int(service["price_cents"])
        service_name = service["name"]
    else:
        amount = int(amount_cents or 0)
        if amount < cfg["min_cents"] or amount > cfg["max_cents"]:
            raise HTTPException(
                status_code=400,
                detail=(
                    "El importe debe estar entre "
                    f"{cfg['min_cents'] // 100} y {cfg['max_cents'] // 100} EUR."
                ),
            )
    accent_color = _gift_accent_or_empty(accent_color)
    buyer_name = textnorm._sanitize_text(buyer_name or "")[:120]
    buyer_email = textnorm._sanitize_text(buyer_email or "").strip().lower()[:160]
    recipient_name = textnorm._sanitize_text(recipient_name or "")[:120]
    recipient_email = textnorm._sanitize_text(recipient_email or "").strip().lower()[:160]
    message = textnorm._sanitize_text(message or "", allow_multiline=True)[:300]
    if len(buyer_name) < 2 or len(recipient_name) < 2:
        raise HTTPException(status_code=400, detail="Faltan el nombre del comprador o del destinatario.")
    if not textnorm.EMAIL_RE.match(buyer_email) or not textnorm.EMAIL_RE.match(recipient_email):
        raise HTTPException(status_code=400, detail="Revisa los emails: no parecen validos.")
    send_at = ""
    raw_send = textnorm._sanitize_text(scheduled_send_at or "").strip()
    if raw_send:
        try:
            send_date = textnorm._parse_date(raw_send).date()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="La fecha de envio no es valida (AAAA-MM-DD).") from exc
        today_local = timeutils._utc_now().date()
        if send_date > today_local:
            if (send_date - today_local).days > 365:
                raise HTTPException(status_code=400, detail="La fecha de envio no puede ser a mas de un anyo vista.")
            send_at = send_date.isoformat()

    account = booking._connect_account_status(cliente_id, refresh=True)
    if not account.connected or not account.charges_enabled:
        raise HTTPException(status_code=409, detail="El negocio aun no tiene el cobro online activo.")

    from backend import appstate  # tardio

    tenant_cfg = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    business_name = str(tenant_cfg.get("empresa") or tenant_cfg.get("nombre") or "el negocio")

    payment_id, now = "pay_" + secrets.token_hex(10), timeutils._utc_now_iso()
    gift_meta = {
        "buyer_name": buyer_name, "buyer_email": buyer_email,
        "recipient_name": recipient_name, "recipient_email": recipient_email,
        "message": message, "scheduled_send_at": send_at,
        "validity_days": cfg["validity_days"],
        "accent_color": accent_color, "hide_value": bool(hide_value),
        "hide_expiry": bool(hide_expiry), "service_name": service_name,
    }
    metadata = {
        "source": "customer_payment", "kind": "gift_card", "payment_id": payment_id,
        "cliente_id": cliente_id,
    }
    base = (base_url or "").rstrip("/")
    stripe_gateway._stripe_init()
    try:
        session = stripe_gateway.stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "eur", "unit_amount": amount,
                    "product_data": {
                        "name": (
                            f"Tarjeta regalo - {service_name} - {business_name}"
                            if service_name else f"Tarjeta regalo - {business_name}"
                        ),
                    },
                },
                "quantity": 1,
            }],
            metadata=metadata,
            customer_email=buyer_email,
            success_url=f"{base}/gift/{cliente_id}?ok=1&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/gift/{cliente_id}?cancel=1",
            stripe_account=account.stripe_account_id,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("No se pudo crear checkout de tarjeta regalo %s: %s", cliente_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo iniciar el pago.") from exc

    checkout_url = textnorm._object_get(session, "url", "")
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO customer_payments
                (id, cliente_id, contact_id, booking_id, service_id, service_name, stripe_account_id,
                 stripe_checkout_session_id, amount_cents, currency, status, checkout_url,
                 kind, line_items_json, created_at, updated_at)
            VALUES (?, ?, '', '', '', ?, ?, ?, ?, 'eur', 'pending', ?, 'gift_card', ?, ?, ?)
            """,
            (
                payment_id, cliente_id, buyer_name,
                account.stripe_account_id, textnorm._object_get(session, "id", ""),
                amount, checkout_url, json.dumps(gift_meta, ensure_ascii=False), now, now,
            ),
        )
        connection.commit()
    return {"payment_id": payment_id, "url": checkout_url, "amount_cents": amount}


def _finalize_gift_card_payment(connection: sqlite3.Connection, payment: sqlite3.Row, now: str) -> None:
    """Emite la tarjeta regalo de un pago 'paid'. Idempotente (gift_cards.customer_payment_id)
    y usa la conexion del webhook (no hace commit). El email sale despues, fuera de la
    transaccion (best-effort via _send_pending_gift_card_emails, sella sent_at)."""
    cliente_id = payment["cliente_id"]
    pay_id = payment["id"]
    already = connection.execute(
        "SELECT COUNT(*) FROM gift_cards WHERE customer_payment_id=?", (pay_id,)
    ).fetchone()[0]
    if already:
        return
    try:
        meta = json.loads(payment["line_items_json"] or "{}")
    except (ValueError, TypeError):
        meta = {}
    validity_days = int(meta.get("validity_days") or 0)
    expires_at = ""
    if validity_days > 0:
        expires_at = (timeutils._utc_now() + timedelta(days=validity_days)).isoformat()
    card_id = f"gc_{secrets.token_urlsafe(8)}"
    code = _generate_gift_card_code(connection, cliente_id)
    amount = int(payment["amount_cents"] or 0)
    connection.execute(
        """
        INSERT INTO gift_cards (id, cliente_id, code, initial_cents, balance_cents, currency,
                                status, buyer_name, buyer_email, recipient_name, recipient_email,
                                notes, expires_at, location_id, created_at, updated_at,
                                message, scheduled_send_at, sent_at, customer_payment_id,
                                accent_color, hide_value, hide_expiry, service_name)
        VALUES (?, ?, ?, ?, ?, 'eur', 'active', ?, ?, ?, ?, '', ?, '', ?, ?, ?, ?, '', ?, ?, ?, ?, ?)
        """,
        (
            card_id, cliente_id, code, amount, amount,
            str(meta.get("buyer_name") or ""), str(meta.get("buyer_email") or ""),
            str(meta.get("recipient_name") or ""), str(meta.get("recipient_email") or ""),
            expires_at, now, now,
            str(meta.get("message") or ""), str(meta.get("scheduled_send_at") or ""),
            pay_id,
            _gift_accent_or_empty(str(meta.get("accent_color") or "")),
            1 if meta.get("hide_value") else 0,
            1 if meta.get("hide_expiry") else 0,
            str(meta.get("service_name") or ""),
        ),
    )
    connection.execute(
        """
        INSERT INTO gift_card_transactions (cliente_id, gift_card_id, kind, amount_cents,
                                            balance_after_cents, notes, created_at)
        VALUES (?, ?, 'issue', ?, ?, 'compra online', ?)
        """,
        (cliente_id, card_id, amount, amount, now),
    )


def _gift_card_email_bodies(cliente_id: str, row: sqlite3.Row) -> Dict[str, str]:
    from backend import appstate  # tardio

    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    business = str(config.get("empresa") or config.get("nombre") or "el negocio")
    color = (
        _gift_accent_or_empty(row["accent_color"] if "accent_color" in row.keys() else "")
        or str((config.get("branding") or {}).get("color") or config.get("color") or "#6d28d9")
    )
    hide_value = bool(row["hide_value"]) if "hide_value" in row.keys() else False
    hide_expiry = bool(row["hide_expiry"]) if "hide_expiry" in row.keys() else False
    service_name = str(row["service_name"] or "") if "service_name" in row.keys() else ""
    amount_label = f"{int(row['balance_cents'] or 0) / 100:.2f} EUR".replace(".", ",")
    # Que se muestra en grande: el servicio regalado, el importe, o nada concreto.
    if service_name:
        headline = service_name
    elif hide_value:
        headline = "Una experiencia"
    else:
        headline = amount_label
    expires_line = ""
    if row["expires_at"] and not hide_expiry:
        expires_line = f"Caduca el {str(row['expires_at'])[:10]}."
    message_block = ""
    if row["message"]:
        message_block = (
            '<p style="font-style:italic;margin:16px 0">&ldquo;'
            + str(row["message"])
            + "&rdquo;</p>"
        )
    regalo_txt = (
        f"un/a {service_name}" if service_name
        else ("una tarjeta regalo" if hide_value else f"una tarjeta de {amount_label}")
    )
    saldo_url = (
        f"{textnorm._preferred_public_base_url().rstrip('/')}/gift/{cliente_id}/saldo?code={row['code']}"
    )
    text_body = (
        f"{row['buyer_name'] or 'Alguien'} te ha regalado {regalo_txt} de {business}.\n\n"
        + (f"Mensaje: {row['message']}\n\n" if row["message"] else "")
        + f"Tu codigo: {row['code']}\n"
        f"Canjeala al reservar online, por telefono o directamente en recepcion. {expires_line}\n"
        f"Consulta tu saldo cuando quieras: {saldo_url}\n"
    )
    html_body = f"""
    <div style="max-width:520px;margin:0 auto;font-family:Arial,sans-serif;color:#1f2937">
      <div style="background:linear-gradient(135deg,{color},#111827);border-radius:16px;padding:28px;color:#fff;text-align:center">
        <div style="font-size:14px;letter-spacing:2px;text-transform:uppercase;opacity:.85">Tarjeta regalo</div>
        <div style="font-size:26px;font-weight:bold;margin:6px 0">{business}</div>
        <div style="font-size:34px;font-weight:bold;margin:14px 0">{headline}</div>
        <div style="background:rgba(255,255,255,.15);border-radius:10px;padding:12px;font-size:22px;letter-spacing:3px;font-weight:bold">{row['code']}</div>
      </div>
      <p style="margin:18px 0 6px">Hola {row['recipient_name'] or ''},</p>
      <p><b>{row['buyer_name'] or 'Alguien'}</b> te ha regalado una tarjeta de <b>{business}</b>.</p>
      {message_block}
      <p>Canjeala al reservar online, por telefono o directamente en recepcion, diciendo tu codigo.</p>
      <div style="text-align:center;margin:20px 0">
        <a href="{saldo_url}" style="display:inline-block;background:{color};color:#fff;text-decoration:none;font-weight:bold;border-radius:12px;padding:12px 24px">Consultar mi saldo</a>
      </div>
      <p style="color:#6b7280;font-size:13px">{expires_line}</p>
    </div>
    """
    return {
        "subject": f"{row['buyer_name'] or 'Alguien'} te ha enviado una tarjeta regalo de {business}",
        "text": text_body,
        "html": html_body,
    }


def _send_gift_card_email(cliente_id: str, gift_card_id: str) -> bool:
    """Envia la tarjeta al destinatario y sella sent_at (idempotente). Best-effort."""
    from backend import emailing  # tardio: evita ciclo commerce<->emailing

    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM gift_cards WHERE id=? AND cliente_id=?", (gift_card_id, cliente_id)
        ).fetchone()
    if not row or row["sent_at"] or not (row["recipient_email"] or "").strip():
        return False
    bodies = _gift_card_email_bodies(cliente_id, row)
    try:
        emailing._send_client_email(
            cliente_id, row["recipient_email"], bodies["subject"], bodies["text"], bodies["html"],
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Email de tarjeta regalo %s fallo: %s", gift_card_id, exc)
        return False
    # Copia al COMPRADOR (imprimible): mismo diseno + nota. Best-effort, no bloquea.
    buyer_email = (row["buyer_email"] or "").strip()
    if buyer_email and buyer_email != (row["recipient_email"] or "").strip():
        try:
            emailing._send_client_email(
                cliente_id, buyer_email,
                f"Copia de tu tarjeta regalo ({row['code']})",
                "Copia de la tarjeta que has regalado. Puedes imprimir este email y entregarla en mano.\n\n" + bodies["text"],
                '<p style="color:#6b7280;font-size:13px">Copia para ti. Puedes imprimir este email y entregar la tarjeta en mano.</p>' + bodies["html"],
            )
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("Copia al comprador de %s fallo: %s", gift_card_id, exc)
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE gift_cards SET sent_at=?, updated_at=? WHERE id=? AND sent_at=''",
            (now, now, gift_card_id),
        )
        connection.commit()
    return True


def _send_pending_gift_card_emails() -> int:
    """Envia tarjetas compradas online pendientes: inmediatas (scheduled vacio) y
    programadas cuya fecha ya llego. Lo llama el worker de recordatorios."""
    today = timeutils._utc_now().date().isoformat()
    with db._get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, cliente_id FROM gift_cards
            WHERE customer_payment_id != '' AND sent_at = '' AND status = 'active'
              AND (scheduled_send_at = '' OR scheduled_send_at <= ?)
            ORDER BY created_at ASC LIMIT 50
            """,
            (today,),
        ).fetchall()
    sent = 0
    for row in rows:
        if _send_gift_card_email(row["cliente_id"], row["id"]):
            sent += 1
    return sent


# --- Wallet publica del bono + consulta de saldo de tarjeta (jul 2026) -------------
# Cierra el viaje del cliente final: tras comprar (mostrador u online) puede VER su
# bono (sesiones restantes, caducidad, historial) en /bono/{cliente}/{wallet_token}
# y consultar el saldo de una tarjeta regalo en /gift/{cliente}/saldo. Sin login:
# el token/codigo es el secreto, con rate limit por IP en las rutas.


def _tenant_brand(cliente_id: str) -> Dict[str, str]:
    """Nombre comercial + color de acento del tenant (mismo criterio que /central)."""
    from backend import appstate  # tardio

    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    business = str(config.get("empresa") or config.get("nombre") or "Nuestro negocio")
    raw_color = str((config.get("branding") or {}).get("color") or config.get("color") or "#0f766e")
    color = raw_color if _GIFT_ACCENT_RE.match(raw_color) else "#0f766e"
    shop_cfg = _shop_public_config(cliente_id)
    if shop_cfg.get("accent_color"):
        color = shop_cfg["accent_color"]
    contacto = config.get("contacto") or {}
    contact_bits = " · ".join(
        x for x in (
            textnorm._sanitize_text(str(contacto.get("telefono") or "")),
            textnorm._sanitize_text(str(contacto.get("direccion") or "")),
        ) if x
    )
    return {"business": business, "color": color, "contact": contact_bits}


def _booking_page_url(cliente_id: str) -> str:
    """URL de la central de reservas si la reserva online esta activa; '' si no."""
    from backend import appstate, clients  # tardio

    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    try:
        enabled = bool((config.get("booking") or {}).get("enabled")) and clients._client_booking_plan_enabled(cliente_id)
    except Exception:  # noqa: BLE001
        enabled = bool((config.get("booking") or {}).get("enabled"))
    if not enabled:
        return ""
    base = textnorm._preferred_public_base_url().rstrip("/")
    return f"{base}/central/{cliente_id}"


def _purchase_sessions_detail(cliente_id: str, row: sqlite3.Row) -> List[Dict[str, Any]]:
    """Sesiones del bono por servicio con nombre legible: restantes vs iniciales."""
    try:
        remaining = json.loads(row["remaining_json"] or "{}")
    except (ValueError, TypeError):
        remaining = {}
    initial = _purchase_initial_sessions(row)
    out: List[Dict[str, Any]] = []
    for slug in sorted(set(list(initial.keys()) + list(remaining.keys()))):
        service_row = agenda._get_service_row(cliente_id, slug)
        name = (service_row["name"] if service_row else slug) or slug
        left = int(remaining.get(slug, 0) or 0)
        total = max(int(initial.get(slug, 0) or 0), left)
        out.append({"slug": slug, "name": name, "left": left, "total": total})
    return out


def _get_purchase_by_wallet_token(cliente_id: str, wallet_token: str) -> Optional[sqlite3.Row]:
    token = textnorm._sanitize_text(wallet_token or "").strip()
    if not token:
        return None
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM package_purchases WHERE cliente_id = ? AND wallet_token = ? LIMIT 1",
            (cliente_id, token),
        ).fetchone()
        if row:
            row = _refresh_purchase_expiry(connection, row)
    return row


def _purchase_redemption_history(cliente_id: str, purchase_id: str, *, limit: int = 12) -> List[Dict[str, str]]:
    """Ultimos canjes del bono (fecha + servicio) desde booking_audit."""
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT payload_json, created_at FROM booking_audit "
            "WHERE cliente_id = ? AND event_type = 'package_redeemed' AND payload_json LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (cliente_id, f"%{purchase_id}%", max(1, min(50, limit))),
        ).fetchall()
    out: List[Dict[str, str]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (ValueError, TypeError):
            continue
        if str(payload.get("purchase_id") or "") != purchase_id:
            continue
        slug = str(payload.get("service_slug") or "")
        service_row = agenda._get_service_row(cliente_id, slug)
        out.append({
            "date": str(row["created_at"] or "")[:10],
            "service": (service_row["name"] if service_row else slug) or slug,
        })
    return out


_PURCHASE_STATUS_LABELS = {
    "active": ("Activo", "#059669"),
    "used": ("Agotado", "#64748b"),
    "expired": ("Caducado", "#b45309"),
    "cancelled": ("Anulado", "#b91c1c"),
}


def _package_purchase_email_bodies(cliente_id: str, row: sqlite3.Row) -> Dict[str, str]:
    """Email del bono al comprador (mostrador y compra online): tarjeta con gradiente,
    contenido, caducidad y boton a la wallet publica."""
    brand = _tenant_brand(cliente_id)
    business, color = brand["business"], brand["color"]
    info = _purchase_to_public(row)
    wallet_url = info["wallet_url"]
    sessions = _purchase_sessions_detail(cliente_id, row)
    amount_label = f"{info['price_cents'] / 100:.2f} EUR".replace(".", ",") if info["price_cents"] else ""
    expires_line = f"Caduca el {info['expires_at'][:10]}." if info["expires_at"] else "Sin caducidad."
    lines_txt = "\n".join(f"- {s['left']} de {s['total']} sesiones: {s['name']}" for s in sessions)
    text = (
        f"Hola {info['buyer_name'] or ''},\n\n"
        f"Tu bono \"{info['package_name']}\" de {business} ya esta activo"
        + (f" ({amount_label})" if amount_label else "") + ".\n\n"
        f"Incluye:\n{lines_txt}\n\n{expires_line}\n\n"
        f"Consulta tus sesiones restantes cuando quieras:\n{wallet_url}\n\n"
        "Para usarlo, reserva tu cita (online, por telefono o en recepcion) y di tu "
        "nombre, email o telefono: descontaremos la sesion del bono.\n"
        + (f"\n{brand['contact']}\n" if brand["contact"] else "")
    )
    html_rows = "".join(
        f'<li>{s["left"]} de {s["total"]} sesiones &middot; <b>{s["name"]}</b></li>' for s in sessions
    )
    html = f"""
    <div style="max-width:520px;margin:0 auto;font-family:Arial,sans-serif;color:#1f2937">
      <div style="background:linear-gradient(135deg,{color},#111827);border-radius:16px;padding:26px;color:#fff;text-align:center">
        <div style="font-size:13px;letter-spacing:2px;text-transform:uppercase;opacity:.85">Bono</div>
        <div style="font-size:24px;font-weight:bold;margin:6px 0">{business}</div>
        <div style="font-size:20px;font-weight:bold;margin:10px 0">{info['package_name']}</div>
        <div style="background:rgba(255,255,255,.15);border-radius:10px;padding:10px;font-size:16px;font-weight:bold">{info['remaining_total']} sesiones disponibles</div>
      </div>
      <p style="margin:18px 0 6px">Hola {info['buyer_name'] or ''},</p>
      <p>Tu bono de <b>{business}</b> ya esta activo{f" ({amount_label})" if amount_label else ""}. Incluye:</p>
      <ul>{html_rows}</ul>
      <p style="color:#6b7280;font-size:13px">{expires_line}</p>
      <div style="text-align:center;margin:22px 0">
        <a href="{wallet_url}" style="display:inline-block;background:{color};color:#fff;text-decoration:none;font-weight:bold;border-radius:12px;padding:13px 26px">Ver mi bono</a>
      </div>
      <p>Para usarlo, reserva tu cita (online, por telefono o en recepcion) y di tu nombre,
      email o telefono: descontaremos la sesion del bono.</p>
      {f'<p style="color:#6b7280;font-size:13px">{brand["contact"]}</p>' if brand["contact"] else ""}
    </div>
    """
    return {"subject": f"Tu bono {info['package_name']} - {business}", "text": text, "html": html}


def _send_package_purchase_email(cliente_id: str, purchase_id: str) -> bool:
    """Envia al comprador su bono digital con el enlace a la wallet. Best-effort."""
    from backend import emailing  # tardio

    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM package_purchases WHERE id = ? AND cliente_id = ?",
            (purchase_id, cliente_id),
        ).fetchone()
    if not row or not (row["buyer_email"] or "").strip():
        return False
    bodies = _package_purchase_email_bodies(cliente_id, row)
    try:
        emailing._send_client_email(cliente_id, row["buyer_email"], bodies["subject"], bodies["text"], bodies["html"])
        return True
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Email de bono %s fallo: %s", purchase_id, exc)
        return False


_WALLET_BASE_CSS = """
  * { box-sizing: border-box; margin: 0; }
  :root { color-scheme: light; --accent: __COLOR__; --ink: #0f172a; --muted: #64748b; --line: #e2e8f0; --bg: #f6f8fb; --ok: #059669; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; color: var(--ink); background: var(--bg); -webkit-font-smoothing: antialiased; }
  .hero { position: relative; overflow: hidden; padding: 34px 18px 92px; color: #fff; background: linear-gradient(130deg, var(--accent), color-mix(in srgb, var(--accent) 55%, #0b1526)); background-size: 200% 200%; animation: heroShift 16s ease-in-out infinite; }
  @keyframes heroShift { 0%,100% { background-position: 0% 30%; } 50% { background-position: 100% 70%; } }
  .hero-inner { width: min(660px, 100%); margin: 0 auto; display: flex; align-items: center; gap: 13px; }
  .monogram { width: 46px; height: 46px; border-radius: 14px; display: flex; align-items: center; justify-content: center; font-size: 21px; font-weight: 900; background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28); }
  .hero-k { font-size: 11.5px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; opacity: .85; }
  .hero h1 { font-size: clamp(22px, 4.5vw, 30px); font-weight: 900; letter-spacing: -.01em; line-height: 1.1; }
  .wrap { width: min(660px, 100%); margin: -64px auto 44px; padding: 0 16px; display: grid; gap: 16px; }
  .card { background: #fff; border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 24px 70px -26px color-mix(in srgb, var(--accent) 30%, rgba(15,23,42,.35)); padding: 24px 24px 22px; animation: riseIn .5s cubic-bezier(.22,.9,.3,1) both; }
  @keyframes riseIn { from { opacity: 0; transform: translateY(16px); } }
  .chip { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 5px 12px; font-size: 12px; font-weight: 800; color: #fff; }
  .k { font-size: 11px; font-weight: 900; letter-spacing: .09em; text-transform: uppercase; color: var(--muted); }
  .cta { display: inline-flex; align-items: center; justify-content: center; gap: 8px; border: 0; border-radius: 13px; background: var(--accent); color: #fff; min-height: 48px; padding: 0 22px; font: inherit; font-weight: 850; font-size: 15px; cursor: pointer; text-decoration: none; box-shadow: 0 12px 26px -10px color-mix(in srgb, var(--accent) 60%, transparent); transition: transform .15s, filter .15s; }
  .cta:hover { filter: brightness(1.06); transform: translateY(-1px); }
  .ghost { display: inline-flex; align-items: center; justify-content: center; gap: 8px; border: 1.5px solid var(--line); border-radius: 13px; background: #fff; color: var(--ink); min-height: 48px; padding: 0 18px; font: inherit; font-weight: 800; cursor: pointer; text-decoration: none; }
  .ghost:hover { border-color: var(--accent); color: var(--accent); }
  footer { text-align: center; font-size: 12.5px; color: #94a3b8; padding: 0 16px 32px; line-height: 1.7; }
  @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; } }
"""


_PACKAGE_WALLET_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="theme-color" content="__COLOR__">
<title>Mi bono &middot; __BUSINESS__</title>
<style>
__BASE_CSS__
  .pkg-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
  .pkg-name { font-size: 21px; font-weight: 900; letter-spacing: -.01em; line-height: 1.2; }
  .big { display: flex; align-items: baseline; gap: 10px; margin: 18px 0 4px; }
  .big b { font-size: 52px; font-weight: 900; line-height: 1; color: var(--accent); letter-spacing: -.02em; }
  .big span { font-size: 15px; font-weight: 700; color: var(--muted); }
  .svc { margin-top: 16px; display: grid; gap: 12px; }
  .svc-row { display: grid; gap: 7px; }
  .svc-top { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
  .svc-name { font-weight: 800; font-size: 14.5px; }
  .svc-count { font-size: 13px; font-weight: 800; color: var(--muted); white-space: nowrap; }
  .bar { height: 9px; border-radius: 99px; background: color-mix(in srgb, var(--accent) 10%, #eef2f7); overflow: hidden; }
  .bar > i { display: block; height: 100%; border-radius: 99px; background: linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--accent) 62%, #fff)); transition: width .5s cubic-bezier(.22,.9,.3,1); }
  .meta { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 18px; }
  .meta span { border: 1px solid var(--line); border-radius: 999px; padding: 6px 12px; background: #f8fafc; color: var(--muted); font-size: 12.5px; font-weight: 700; }
  .hist { display: grid; gap: 0; }
  .hist-row { display: flex; justify-content: space-between; gap: 12px; padding: 11px 0; border-bottom: 1px dashed var(--line); font-size: 14px; }
  .hist-row:last-child { border-bottom: 0; }
  .hist-row b { font-weight: 800; }
  .hist-row time { color: var(--muted); font-size: 13px; white-space: nowrap; }
  .actions { display: flex; gap: 10px; flex-wrap: wrap; }
  .how { color: var(--muted); font-size: 13.5px; line-height: 1.55; }
</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <div class="monogram">__MONOGRAM__</div>
      <div>
        <div class="hero-k">Tu bono</div>
        <h1>__BUSINESS__</h1>
      </div>
    </div>
  </header>
  <main class="wrap">
    <section class="card">
      <div class="pkg-head">
        <div>
          <div class="k">Bono</div>
          <div class="pkg-name">__PACKAGE_NAME__</div>
        </div>
        <span class="chip" style="background:__STATUS_COLOR__">__STATUS_LABEL__</span>
      </div>
      <div class="big"><b>__REMAINING__</b><span>__REMAINING_WORD__</span></div>
      <div class="svc">__SERVICE_ROWS__</div>
      <div class="meta">__META_CHIPS__</div>
    </section>
    __HISTORY_CARD__
    <section class="card" style="display:grid;gap:14px;">
      <div class="actions">__ACTIONS__</div>
      <p class="how">Para usar una sesion, reserva tu cita y di tu nombre, email o telefono
      en recepcion: la descontaremos de este bono. Tambien puedes ensenar esta pantalla.</p>
    </section>
  </main>
  <footer>__BUSINESS____CONTACT__<br>Este enlace es personal: no lo compartas.</footer>
</body>
</html>"""


def package_wallet_page_html(cliente_id: str, wallet_token: str) -> str:
    """Wallet publica del bono: sesiones restantes, caducidad e historial de usos."""
    import html as html_mod

    row = _get_purchase_by_wallet_token(cliente_id, wallet_token)
    if not row:
        raise HTTPException(status_code=404, detail="Bono no encontrado.")
    brand = _tenant_brand(cliente_id)
    info = _purchase_to_public(row)
    sessions = _purchase_sessions_detail(cliente_id, row)
    status_label, status_color = _PURCHASE_STATUS_LABELS.get(
        info["status"], (info["status"], "#64748b")
    )

    service_rows = []
    for s in sessions:
        pct = int(round(100 * s["left"] / s["total"])) if s["total"] else 0
        service_rows.append(
            '<div class="svc-row"><div class="svc-top">'
            f'<span class="svc-name">{html_mod.escape(s["name"])}</span>'
            f'<span class="svc-count">quedan {s["left"]} de {s["total"]}</span></div>'
            f'<div class="bar"><i style="width:{pct}%"></i></div></div>'
        )

    meta_chips = []
    if info["created_at"]:
        meta_chips.append(f"<span>Comprado el {html_mod.escape(str(info['created_at'])[:10])}</span>")
    if info["expires_at"]:
        expires_iso = str(info["expires_at"])[:10]
        chip = f"Caduca el {expires_iso}"
        try:
            days_left = (textnorm._parse_date(expires_iso).date() - timeutils._utc_now().date()).days
            if info["status"] == "active" and 0 <= days_left <= 45:
                chip += f" &middot; quedan {days_left} dias"
        except Exception:  # noqa: BLE001
            pass
        meta_chips.append(f"<span>{chip}</span>")
    else:
        meta_chips.append("<span>Sin caducidad</span>")
    if info["price_cents"]:
        meta_chips.append(f"<span>{textnorm._format_price_cents(info['price_cents'])}</span>")

    history = _purchase_redemption_history(cliente_id, row["id"])
    history_card = ""
    if history:
        hist_rows = "".join(
            f'<div class="hist-row"><b>{html_mod.escape(h["service"])}</b><time>{html_mod.escape(h["date"])}</time></div>'
            for h in history
        )
        history_card = (
            '<section class="card"><div class="k" style="margin-bottom:10px;">Usos recientes</div>'
            f'<div class="hist">{hist_rows}</div></section>'
        )

    actions = []
    booking_url = _booking_page_url(cliente_id)
    if booking_url and info["status"] == "active" and info["remaining_total"] > 0:
        actions.append(f'<a class="cta" href="{html_mod.escape(booking_url)}">Reservar cita</a>')

    page = _PACKAGE_WALLET_TEMPLATE
    page = page.replace("__BASE_CSS__", _WALLET_BASE_CSS)
    replacements = {
        "__COLOR__": brand["color"],
        "__BUSINESS__": html_mod.escape(brand["business"]),
        "__MONOGRAM__": html_mod.escape((brand["business"][:1] or "V").upper()),
        "__PACKAGE_NAME__": html_mod.escape(info["package_name"] or "Bono"),
        "__STATUS_LABEL__": status_label,
        "__STATUS_COLOR__": status_color,
        "__REMAINING__": str(info["remaining_total"]),
        "__REMAINING_WORD__": "sesion disponible" if info["remaining_total"] == 1 else "sesiones disponibles",
        "__SERVICE_ROWS__": "".join(service_rows) or '<p class="how">Este bono no tiene sesiones configuradas.</p>',
        "__META_CHIPS__": "".join(meta_chips),
        "__HISTORY_CARD__": history_card,
        "__ACTIONS__": "".join(actions) or "",
        "__CONTACT__": f" &middot; {html_mod.escape(brand['contact'])}" if brand["contact"] else "",
    }
    for key, value in replacements.items():
        page = page.replace(key, value)
    return page


def gift_balance_available(cliente_id: str) -> bool:
    """La consulta de saldo aplica si el negocio ha emitido alguna tarjeta (mostrador
    u online) o tiene la venta publica activa."""
    if gift_public_available(cliente_id):
        return True
    with db._get_db_connection() as connection:
        return bool(
            connection.execute(
                "SELECT 1 FROM gift_cards WHERE cliente_id = ? LIMIT 1", (cliente_id,)
            ).fetchone()
        )


def gift_card_balance_public(cliente_id: str, code: str) -> Dict[str, Any]:
    """Saldo de una tarjeta para su portador (el codigo es el secreto)."""
    normalized = _normalize_gift_code(textnorm._sanitize_text(code or ""))
    if len(normalized) < 6:
        raise HTTPException(status_code=400, detail="Escribe el codigo completo de la tarjeta.")
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM gift_cards WHERE cliente_id = ? AND code = ? LIMIT 1",
            (cliente_id, normalized),
        ).fetchone()
        if row:
            row = _refresh_gift_card_expiry(connection, row)
    if not row:
        raise HTTPException(status_code=404, detail="No encontramos esa tarjeta. Revisa el codigo.")
    return {
        "code": row["code"],
        "status": row["status"] or "active",
        "balance_cents": int(row["balance_cents"] or 0),
        "initial_cents": int(row["initial_cents"] or 0),
        "expires_at": (row["expires_at"] or "")[:10],
        "recipient_name": row["recipient_name"] or "",
        "service_name": (row["service_name"] or "") if "service_name" in row.keys() else "",
    }


_GIFT_BALANCE_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="theme-color" content="__COLOR__">
<title>Saldo de tu tarjeta &middot; __BUSINESS__</title>
<style>
__BASE_CSS__
  .lookup { display: grid; gap: 12px; }
  .lookup label { font-size: 12px; font-weight: 800; color: #334155; }
  .code-row { display: flex; gap: 10px; }
  .code-row input { flex: 1; border: 1.5px solid var(--line); border-radius: 13px; padding: 13px 15px; font: inherit; font-size: 17px; font-weight: 800; letter-spacing: 2px; text-transform: uppercase; color: var(--ink); }
  .code-row input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 15%, transparent); }
  .err { display: none; border-radius: 12px; padding: 12px 15px; background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; font-size: 14px; }
  .gcard { display: none; border-radius: 18px; padding: 26px 24px; color: #fff; background: linear-gradient(135deg, var(--accent), #111827); position: relative; overflow: hidden; }
  .gcard.on { display: grid; gap: 16px; animation: riseIn .4s cubic-bezier(.22,.9,.3,1); }
  .gcard::after { content: ""; position: absolute; right: -46px; top: -46px; width: 150px; height: 150px; border-radius: 50%; background: rgba(255,255,255,.10); }
  .gcard .brand { font-size: 12px; letter-spacing: 2px; text-transform: uppercase; opacity: .85; }
  .gcard .biz { font-size: 19px; font-weight: 800; margin-top: 2px; }
  .gcard .bal { font-size: 42px; font-weight: 900; letter-spacing: -.02em; line-height: 1; }
  .gcard .bal small { display: block; font-size: 12.5px; font-weight: 700; opacity: .8; letter-spacing: .06em; text-transform: uppercase; margin-bottom: 7px; }
  .gcard .codebox { background: rgba(255,255,255,.16); border-radius: 10px; padding: 10px; text-align: center; font-size: 16px; letter-spacing: 3px; font-weight: 800; }
  .gbar { height: 9px; border-radius: 99px; background: rgba(255,255,255,.22); overflow: hidden; }
  .gbar > i { display: block; height: 100%; border-radius: 99px; background: #fff; transition: width .6s cubic-bezier(.22,.9,.3,1); }
  .gfoot { display: flex; justify-content: space-between; gap: 10px; font-size: 12.5px; opacity: .9; flex-wrap: wrap; }
  .after { display: none; }
  .after.on { display: grid; gap: 12px; }
  .how { color: var(--muted); font-size: 13.5px; line-height: 1.55; }
</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <div class="monogram">__MONOGRAM__</div>
      <div>
        <div class="hero-k">Tarjeta regalo</div>
        <h1>__BUSINESS__</h1>
      </div>
    </div>
  </header>
  <main class="wrap">
    <section class="card lookup">
      <div>
        <div class="k" style="margin-bottom:4px;">Consulta tu saldo</div>
        <p class="how">Escribe el codigo que aparece en tu tarjeta o en el email que recibiste.</p>
      </div>
      <div class="err" id="err"></div>
      <label for="code">Codigo de la tarjeta</label>
      <div class="code-row">
        <input id="code" maxlength="14" placeholder="GC-XXXX-XXXX" autocomplete="off" spellcheck="false">
        <button class="cta" id="go" type="button">Consultar</button>
      </div>
    </section>
    <div class="gcard" id="gcard">
      <div>
        <div class="brand">Tarjeta regalo</div>
        <div class="biz">__BUSINESS__</div>
      </div>
      <div class="bal"><small>Saldo disponible</small><span id="bal"></span></div>
      <div class="gbar"><i id="gbarFill"></i></div>
      <div class="codebox" id="codebox"></div>
      <div class="gfoot"><span id="gstate"></span><span id="gexp"></span></div>
    </div>
    <section class="card after" id="after">
      <div class="actions" style="display:flex;gap:10px;flex-wrap:wrap;">__ACTIONS__</div>
      <p class="how">Para canjearla, di tu codigo al reservar o en recepcion. Si cubre solo
      una parte, el resto se abona en el centro.</p>
    </section>
  </main>
  <footer>__BUSINESS____CONTACT__</footer>
<script>
(function () {
  var input = document.getElementById("code");
  var err = document.getElementById("err");
  var eur = function (c) { return (c / 100).toLocaleString("es-ES", { minimumFractionDigits: c % 100 ? 2 : 0 }) + " \\u20AC"; };
  var STATES = { active: "Activa", redeemed: "Agotada", disabled: "Anulada", expired: "Caducada" };
  // El servidor normaliza (acepta sin guiones o sin prefijo GC); aqui solo mayusculas.
  input.addEventListener("input", function () { this.value = this.value.toUpperCase(); });
  function lookup() {
    err.style.display = "none";
    var code = input.value.trim();
    if (code.length < 6) { err.textContent = "Escribe el codigo completo."; err.style.display = "block"; return; }
    var btn = document.getElementById("go");
    btn.disabled = true;
    fetch(location.pathname, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: code })
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        btn.disabled = false;
        if (!res.ok) throw new Error((res.d && res.d.detail) || "No se pudo consultar el saldo.");
        var d = res.d;
        document.getElementById("bal").textContent = eur(d.balance_cents);
        document.getElementById("codebox").textContent = d.code;
        var pct = d.initial_cents > 0 ? Math.max(0, Math.min(100, Math.round(100 * d.balance_cents / d.initial_cents))) : 0;
        document.getElementById("gbarFill").style.width = pct + "%";
        document.getElementById("gstate").textContent = "Estado: " + (STATES[d.status] || d.status);
        document.getElementById("gexp").textContent = d.expires_at ? "Caduca el " + d.expires_at : "Sin caducidad";
        document.getElementById("gcard").classList.add("on");
        document.getElementById("after").classList.add("on");
        document.getElementById("gcard").scrollIntoView({ block: "nearest", behavior: "smooth" });
      })
      .catch(function (e) {
        btn.disabled = false;
        err.textContent = e.message;
        err.style.display = "block";
      });
  }
  document.getElementById("go").addEventListener("click", lookup);
  input.addEventListener("keydown", function (ev) { if (ev.key === "Enter") { ev.preventDefault(); lookup(); } });
  var qs = new URLSearchParams(location.search);
  var pre = (qs.get("code") || "").trim();
  if (pre) { input.value = pre; lookup(); }
})();
</script>
</body>
</html>"""


def gift_balance_page_html(cliente_id: str) -> str:
    """Pagina publica de consulta de saldo de tarjeta regalo (branding del tenant)."""
    import html as html_mod

    if not gift_balance_available(cliente_id):
        raise HTTPException(status_code=404, detail="La consulta de saldo no esta disponible.")
    brand = _tenant_brand(cliente_id)
    base = textnorm._preferred_public_base_url().rstrip("/")
    actions = []
    booking_url = _booking_page_url(cliente_id)
    if booking_url:
        actions.append(f'<a class="cta" href="{html_mod.escape(booking_url)}">Reservar cita</a>')
    if gift_public_available(cliente_id):
        actions.append(f'<a class="ghost" href="{base}/gift/{cliente_id}">Regalar otra tarjeta</a>')

    page = _GIFT_BALANCE_TEMPLATE
    page = page.replace("__BASE_CSS__", _WALLET_BASE_CSS)
    replacements = {
        "__COLOR__": brand["color"],
        "__BUSINESS__": html_mod.escape(brand["business"]),
        "__MONOGRAM__": html_mod.escape((brand["business"][:1] or "V").upper()),
        "__ACTIONS__": "".join(actions),
        "__CONTACT__": f" &middot; {html_mod.escape(brand['contact'])}" if brand["contact"] else "",
    }
    for key, value in replacements.items():
        page = page.replace(key, value)
    return page


# --- Canje online tras reservar (central publica) ----------------------------------
# El manage_token de la cita (secreto que solo tiene quien reservo) autoriza a
# consultar y aplicar bonos/tarjetas sobre ESA cita. Los bonos se detectan por el
# email/telefono de la reserva; la tarjeta exige poseer el codigo (igual que en
# mostrador). Reusa _redeem_package_for_booking/_redeem_gift_card_for_booking.


def _booking_for_manage_token_or_404(cliente_id: str, manage_token: str) -> sqlite3.Row:
    booking_row = booking._load_booking_by_token_or_404(textnorm._sanitize_text(manage_token or ""))
    if booking_row["cliente_id"] != cliente_id:
        raise HTTPException(status_code=404, detail="No se ha encontrado la reserva.")
    return booking_row


def _packages_for_contact(cliente_id: str, *, email: str = "", phone: str = "") -> List[sqlite3.Row]:
    """Bonos activos cuyo comprador coincide con el email o el telefono dados
    (telefono normalizado a los ultimos 9 digitos, criterio CRM)."""
    from backend import crm  # tardio

    email = (email or "").strip().lower()
    phone_norm = crm._normalize_phone_for_match(phone or "")
    if not email and not phone_norm:
        return []
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM package_purchases WHERE cliente_id = ? AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 100",
            (cliente_id,),
        ).fetchall()
        rows = [_refresh_purchase_expiry(connection, row) for row in rows]
    out = []
    for row in rows:
        if row["status"] != "active":
            continue
        row_email = (row["buyer_email"] or "").strip().lower()
        row_phone = crm._normalize_phone_for_match(row["buyer_phone"] or "")
        if (email and row_email == email) or (phone_norm and row_phone and row_phone == phone_norm):
            out.append(row)
    return out


def _packages_for_booking_contact(cliente_id: str, booking_row: sqlite3.Row) -> List[sqlite3.Row]:
    """Bonos activos cuyo comprador coincide con el contacto de la cita."""
    return _packages_for_contact(
        cliente_id, email=booking_row["email"] or "", phone=booking_row["telefono"] or ""
    )


def packages_summary_for_contact(cliente_id: str, *, email: str = "", phone: str = "") -> Dict[str, Any]:
    """Resumen de los bonos activos de un contacto para los asistentes (voz/WhatsApp).

    El emisor debe garantizar que el contacto esta VERIFICADO por el canal (numero
    del que llama / escribe). Devuelve un `mensaje` hablable y la lista `bonos`."""
    rows = _packages_for_contact(cliente_id, email=email, phone=phone)
    bonos: List[Dict[str, Any]] = []
    for row in rows:
        detail = _purchase_sessions_detail(cliente_id, row)
        parts = [f"{s['left']} de {s['total']} sesiones de {s['name']}" for s in detail if s["total"]]
        bonos.append({
            "purchase_id": row["id"],
            "package_name": row["package_name"] or "Bono",
            "detalle": parts,
            "expires_at": (row["expires_at"] or "")[:10],
        })
    if not bonos:
        return {
            "ok": True,
            "count": 0,
            "bonos": [],
            "mensaje": (
                "No encuentro ningun bono activo asociado a este contacto. Si lo compraste con "
                "otro telefono o email, dimelo y vuelvo a mirar."
            ),
        }
    frases = []
    for b in bonos:
        frase = f"el bono {b['package_name']}, con " + (", ".join(b["detalle"]) or "sin sesiones")
        if b["expires_at"]:
            frase += f", que caduca el {b['expires_at']}"
        frases.append(frase)
    mensaje = ("Tienes " if len(bonos) == 1 else f"Tienes {len(bonos)} bonos activos: ") + "; ".join(frases) + "."
    return {"ok": True, "count": len(bonos), "bonos": bonos, "mensaje": mensaje}


def auto_redeem_package_for_booking(
    cliente_id: str, booking_id: str, *, extra_phone: str = ""
) -> Optional[Dict[str, Any]]:
    """Auto-canje al crear una cita por el asistente (voz/WhatsApp, contacto verificado).

    Si el contacto de la cita (o `extra_phone`, el numero verificado del canal) tiene
    un bono activo que cubre el servicio, descuenta 1 sesion (gasta primero el que
    antes caduque) y deja la cita pagada. Best-effort: NUNCA rompe la reserva; si la
    cita esta pendiente de pago obligatorio (pending_payment) no toca nada."""
    try:
        booking_row = booking._get_booking_row_by_id(booking_id)
        if not booking_row or booking_row["cliente_id"] != cliente_id:
            return None
        if booking_row["payment_status"] == "paid" or booking_row["status"] in ("cancelled", "pending_payment"):
            return None
        service_slug = booking_row["service_id"] or ""
        if not service_slug or int(booking_row["service_price_cents"] or 0) < 1:
            return None
        candidates = {row["id"]: row for row in _packages_for_booking_contact(cliente_id, booking_row)}
        if extra_phone:
            for row in _packages_for_contact(cliente_id, phone=extra_phone):
                candidates.setdefault(row["id"], row)
        eligible = []
        for row in candidates.values():
            try:
                remaining = json.loads(row["remaining_json"] or "{}")
            except (ValueError, TypeError):
                continue
            if int(remaining.get(service_slug, 0) or 0) >= 1:
                eligible.append(row)
        if not eligible:
            return None
        eligible.sort(key=lambda r: (r["expires_at"] or "9999", r["created_at"]))
        chosen = eligible[0]
        result = _redeem_package_for_booking(cliente_id, chosen["id"], booking_id)
        return {
            "purchase_id": chosen["id"],
            "package_name": chosen["package_name"] or "Bono",
            "sessions_left": int((result.get("remaining") or {}).get(service_slug, 0) or 0),
        }
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Auto-canje de bono fallo (%s, %s): %s", cliente_id, booking_id, exc)
        return None


_PACKAGE_BALANCE_INTENT_RE = re.compile(
    r"(mi[s]?\s+bono|bono[s]?\b[^\n]{0,40}\b(quedan?|restan?|sesione?s|saldo)|"
    r"(cuant[ao]s|que)\s+sesione?s|sesione?s\s+(me\s+)?(quedan?|restan?)|"
    r"saldo\s+(de[l]?\s+)?(mi\s+)?bono)",
    re.IGNORECASE,
)


def _message_requests_package_balance(message: str) -> bool:
    """Intencion 'cuantas sesiones me quedan de mi bono' (no confundir con comprar
    un bono ni con tarjeta regalo: 'bono regalo' es intent de gift)."""
    norm = textnorm._strip_accents(str(message or "").lower())
    if "regalo" in norm or "comprar" in norm:
        return False
    return bool(_PACKAGE_BALANCE_INTENT_RE.search(norm))


# --- Ciclo de vida: caducidad proxima + recompra (jul 2026) --------------------------
# Corre en el worker de recordatorios. Emails transaccionales sobre algo que el
# cliente PAGO (a punto de caducar / agotado): default ON por tenant, apagable con
# config['reminders']['lifecycle_emails'] = false. Sellado por fila (idempotente).

LIFECYCLE_EXPIRY_WINDOW_DAYS = int(os.getenv("COMMERCE_EXPIRY_NOTICE_DAYS", "14") or "14")
LIFECYCLE_MIN_AGE_DAYS = 7        # no avisar de caducidad recien comprado
LIFECYCLE_REBUY_WINDOW_DAYS = 14  # recompra solo si se agoto hace poco (no historico)


def _lifecycle_emails_enabled(cliente_id: str) -> bool:
    from backend import appstate  # tardio

    raw = (appstate.CONFIG_CLIENTES.get(cliente_id) or {}).get("reminders") or {}
    value = raw.get("lifecycle_emails")
    return True if value is None else bool(value)


def _lifecycle_cta_urls(cliente_id: str) -> Dict[str, str]:
    """CTAs disponibles para los emails de ciclo de vida: reservar y recomprar."""
    base = textnorm._preferred_public_base_url().rstrip("/")
    urls = {"book": _booking_page_url(cliente_id), "shop": ""}
    try:
        if shop_public_available(cliente_id)["packages"]:
            urls["shop"] = f"{base}/tienda/{cliente_id}?solo=bonos"
    except Exception:  # noqa: BLE001
        pass
    return urls


def _lifecycle_email_shell(color: str, title: str, body_html: str, cta_url: str, cta_label: str) -> str:
    cta = (
        f'<div style="text-align:center;margin:22px 0">'
        f'<a href="{cta_url}" style="display:inline-block;background:{color};color:#fff;'
        f'text-decoration:none;font-weight:bold;border-radius:12px;padding:13px 26px">{cta_label}</a></div>'
        if cta_url else ""
    )
    return (
        '<div style="max-width:520px;margin:0 auto;font-family:Arial,sans-serif;color:#1f2937">'
        f'<h2 style="margin:0 0 14px">{title}</h2>{body_html}{cta}</div>'
    )


def _send_package_expiry_email(cliente_id: str, row: sqlite3.Row) -> bool:
    from backend import emailing  # tardio

    brand = _tenant_brand(cliente_id)
    info = _purchase_to_public(row)
    sessions = _purchase_sessions_detail(cliente_id, row)
    expires = info["expires_at"][:10]
    wallet_url = info["wallet_url"]
    lines = "; ".join(f"{s['left']} de {s['total']} de {s['name']}" for s in sessions if s["total"])
    urls = _lifecycle_cta_urls(cliente_id)
    subject = f"Tu bono {info['package_name']} caduca el {expires} - {brand['business']}"
    text = (
        f"Hola {info['buyer_name'] or ''},\n\n"
        f"Tu bono \"{info['package_name']}\" de {brand['business']} caduca el {expires} y todavia "
        f"te quedan {info['remaining_total']} sesiones ({lines}).\n\n"
        f"Reserva tu cita para aprovecharlas antes de esa fecha"
        + (f": {urls['book']}" if urls["book"] else " (online, por telefono o en recepcion).") + "\n\n"
        f"Consulta tu bono: {wallet_url}\n"
    )
    html_sessions = "".join(
        f"<li>{s['left']} de {s['total']} sesiones &middot; <b>{s['name']}</b></li>" for s in sessions if s["total"]
    )
    html = _lifecycle_email_shell(
        brand["color"],
        f"Tu bono caduca el {expires}",
        (
            f"<p>Hola {info['buyer_name'] or ''}, tu bono <b>{info['package_name']}</b> de "
            f"<b>{brand['business']}</b> caduca el <b>{expires}</b> y todavia te quedan "
            f"<b>{info['remaining_total']} sesiones</b>:</p><ul>{html_sessions}</ul>"
            f'<p style="color:#6b7280;font-size:13px"><a href="{wallet_url}">Ver mi bono</a></p>'
        ),
        urls["book"] or wallet_url,
        "Reservar cita" if urls["book"] else "Ver mi bono",
    )
    try:
        emailing._send_client_email(cliente_id, row["buyer_email"], subject, text, html)
        return True
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Aviso de caducidad de bono %s fallo: %s", row["id"], exc)
        return False


def _send_gift_expiry_email(cliente_id: str, row: sqlite3.Row) -> bool:
    from backend import emailing  # tardio

    to_email = (row["recipient_email"] or "").strip() or (row["buyer_email"] or "").strip()
    if not to_email:
        return False
    brand = _tenant_brand(cliente_id)
    expires = (row["expires_at"] or "")[:10]
    balance = textnorm._format_price_cents(int(row["balance_cents"] or 0))
    base = textnorm._preferred_public_base_url().rstrip("/")
    saldo_url = f"{base}/gift/{cliente_id}/saldo?code={row['code']}"
    urls = _lifecycle_cta_urls(cliente_id)
    subject = f"Tu tarjeta regalo caduca el {expires} - {brand['business']}"
    text = (
        f"Tu tarjeta regalo de {brand['business']} (codigo {row['code']}) caduca el {expires} "
        f"y todavia tiene {balance} de saldo.\n\n"
        f"Canjeala al reservar online, por telefono o en recepcion"
        + (f": {urls['book']}" if urls["book"] else ".") + "\n\n"
        f"Consulta tu saldo: {saldo_url}\n"
    )
    html = _lifecycle_email_shell(
        brand["color"],
        f"Tu tarjeta regalo caduca el {expires}",
        (
            f"<p>Tu tarjeta de <b>{brand['business']}</b> (codigo <b>{row['code']}</b>) caduca el "
            f"<b>{expires}</b> y todavia tiene <b>{balance}</b> de saldo. Canjeala al reservar "
            f"o directamente en recepcion.</p>"
            f'<p style="color:#6b7280;font-size:13px"><a href="{saldo_url}">Consultar mi saldo</a></p>'
        ),
        urls["book"] or saldo_url,
        "Reservar cita" if urls["book"] else "Consultar saldo",
    )
    try:
        emailing._send_client_email(cliente_id, to_email, subject, text, html)
        return True
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Aviso de caducidad de tarjeta %s fallo: %s", row["id"], exc)
        return False


def _send_package_rebuy_email(cliente_id: str, row: sqlite3.Row) -> bool:
    from backend import emailing  # tardio

    brand = _tenant_brand(cliente_id)
    info = _purchase_to_public(row)
    urls = _lifecycle_cta_urls(cliente_id)
    subject = f"Has completado tu bono {info['package_name']} - {brand['business']}"
    renew_line = (
        f"Renuevalo online en un minuto: {urls['shop']}" if urls["shop"]
        else "Puedes renovarlo en recepcion o por telefono cuando quieras."
    )
    text = (
        f"Hola {info['buyer_name'] or ''},\n\n"
        f"Has usado la ultima sesion de tu bono \"{info['package_name']}\" de {brand['business']}. "
        f"Esperamos que lo hayas disfrutado.\n\n{renew_line}\n"
        + (f"\nO reserva tu proxima cita: {urls['book']}\n" if urls["book"] else "")
    )
    html = _lifecycle_email_shell(
        brand["color"],
        "Has completado tu bono 🎉",
        (
            f"<p>Hola {info['buyer_name'] or ''}, has usado la ultima sesion de tu bono "
            f"<b>{info['package_name']}</b> de <b>{brand['business']}</b>. Esperamos que lo hayas disfrutado.</p>"
            + ("" if urls["shop"] else "<p>Puedes renovarlo en recepcion o por telefono cuando quieras.</p>")
        ),
        urls["shop"] or urls["book"],
        "Renovar mi bono" if urls["shop"] else "Reservar cita",
    )
    try:
        emailing._send_client_email(cliente_id, row["buyer_email"], subject, text, html)
        return True
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Aviso de recompra de bono %s fallo: %s", row["id"], exc)
        return False


def _run_commerce_lifecycle_notices() -> Dict[str, int]:
    """Pasada del worker: avisos de caducidad (bono + tarjeta) y de recompra.

    Idempotente via columnas de sellado (se sella SOLO si el email salio; un fallo
    se reintenta en la siguiente pasada). Limita el lote por pasada."""
    now = timeutils._utc_now()
    now_iso = now.isoformat()
    horizon = (now + timedelta(days=LIFECYCLE_EXPIRY_WINDOW_DAYS)).isoformat()
    min_age = (now - timedelta(days=LIFECYCLE_MIN_AGE_DAYS)).isoformat()
    rebuy_since = (now - timedelta(days=LIFECYCLE_REBUY_WINDOW_DAYS)).isoformat()
    sent = {"package_expiry": 0, "gift_expiry": 0, "package_rebuy": 0}

    with db._get_db_connection() as connection:
        expiring_packages = connection.execute(
            "SELECT * FROM package_purchases WHERE status = 'active' AND buyer_email != '' "
            "AND expiry_notice_sent_at = '' AND expires_at != '' AND expires_at > ? "
            "AND expires_at <= ? AND created_at <= ? ORDER BY expires_at ASC LIMIT 50",
            (now_iso, horizon, min_age),
        ).fetchall()
        expiring_gifts = connection.execute(
            "SELECT * FROM gift_cards WHERE status = 'active' AND balance_cents > 0 "
            "AND expiry_notice_sent_at = '' AND expires_at != '' AND expires_at > ? "
            "AND expires_at <= ? AND created_at <= ? ORDER BY expires_at ASC LIMIT 50",
            (now_iso, horizon, min_age),
        ).fetchall()
        used_packages = connection.execute(
            "SELECT * FROM package_purchases WHERE status = 'used' AND buyer_email != '' "
            "AND rebuy_notice_sent_at = '' AND updated_at >= ? ORDER BY updated_at DESC LIMIT 50",
            (rebuy_since,),
        ).fetchall()

    for row in expiring_packages:
        if not _lifecycle_emails_enabled(row["cliente_id"]):
            continue
        try:
            remaining = json.loads(row["remaining_json"] or "{}")
        except (ValueError, TypeError):
            remaining = {}
        if sum(int(v) for v in remaining.values()) < 1:
            continue
        if _send_package_expiry_email(row["cliente_id"], row):
            with db._get_db_connection() as connection:
                connection.execute(
                    "UPDATE package_purchases SET expiry_notice_sent_at = ? WHERE id = ? AND expiry_notice_sent_at = ''",
                    (now_iso, row["id"]),
                )
                connection.commit()
            sent["package_expiry"] += 1

    for row in expiring_gifts:
        if not _lifecycle_emails_enabled(row["cliente_id"]):
            continue
        if _send_gift_expiry_email(row["cliente_id"], row):
            with db._get_db_connection() as connection:
                connection.execute(
                    "UPDATE gift_cards SET expiry_notice_sent_at = ? WHERE id = ? AND expiry_notice_sent_at = ''",
                    (now_iso, row["id"]),
                )
                connection.commit()
            sent["gift_expiry"] += 1

    for row in used_packages:
        if not _lifecycle_emails_enabled(row["cliente_id"]):
            continue
        if _send_package_rebuy_email(row["cliente_id"], row):
            with db._get_db_connection() as connection:
                connection.execute(
                    "UPDATE package_purchases SET rebuy_notice_sent_at = ? WHERE id = ? AND rebuy_notice_sent_at = ''",
                    (now_iso, row["id"]),
                )
                connection.commit()
            sent["package_rebuy"] += 1

    return sent


def booking_redeem_options(cliente_id: str, manage_token: str) -> Dict[str, Any]:
    """Opciones de canje para una cita recien creada (central publica)."""
    booking_row = _booking_for_manage_token_or_404(cliente_id, manage_token)
    price_cents = int(booking_row["service_price_cents"] or 0)
    can_redeem = (
        booking_row["status"] not in ("cancelled",)
        and booking_row["payment_status"] != "paid"
        and price_cents > 0
    )
    service_slug = booking_row["service_id"] or ""
    packages: List[Dict[str, Any]] = []
    if can_redeem and service_slug:
        for row in _packages_for_booking_contact(cliente_id, booking_row):
            try:
                remaining = json.loads(row["remaining_json"] or "{}")
            except (ValueError, TypeError):
                remaining = {}
            left = int(remaining.get(service_slug, 0) or 0)
            if left < 1:
                continue
            packages.append({
                "purchase_id": row["id"],
                "package_name": row["package_name"] or "Bono",
                "sessions_left": left,
                "expires_at": (row["expires_at"] or "")[:10],
            })
    return {
        "booking_id": booking_row["id"],
        "can_redeem": can_redeem,
        "payment_status": booking_row["payment_status"] or "",
        "price_cents": price_cents,
        "packages": packages,
        "gift_enabled": can_redeem,
    }


def booking_redeem_apply(
    cliente_id: str, manage_token: str, *, kind: str, code: str = "", purchase_id: str = ""
) -> Dict[str, Any]:
    """Aplica un bono o una tarjeta regalo a la cita del manage_token."""
    booking_row = _booking_for_manage_token_or_404(cliente_id, manage_token)
    if kind == "package":
        purchase_id = textnorm._sanitize_text(purchase_id or "")
        allowed = {row["id"] for row in _packages_for_booking_contact(cliente_id, booking_row)}
        if purchase_id not in allowed:
            raise HTTPException(status_code=404, detail="Ese bono no esta disponible para esta reserva.")
        result = _redeem_package_for_booking(cliente_id, purchase_id, booking_row["id"])
        return {
            "ok": True, "kind": "package", "covered": True,
            "remaining_due_cents": 0,
            "sessions_left": int((result.get("remaining") or {}).get(booking_row["service_id"] or "", 0) or 0),
        }
    if kind == "gift":
        result = _redeem_gift_card_for_booking(cliente_id, code, booking_row["id"])
        return {
            "ok": True, "kind": "gift", "covered": bool(result.get("covered")),
            "charged_cents": int(result.get("charged_cents") or 0),
            "balance_after_cents": int(result.get("balance_after_cents") or 0),
            "remaining_due_cents": int(result.get("remaining_due_cents") or 0),
        }
    raise HTTPException(status_code=400, detail="Tipo de canje no valido.")


def gift_public_page_html(cliente_id: str) -> str:
    """Pagina publica de compra de tarjeta regalo, con el branding del tenant y una
    VISTA PREVIA en vivo de la tarjeta (se actualiza al escribir). Server-rendered,
    sin dependencias externas (CSP-friendly)."""
    from backend import appstate  # tardio

    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    cfg = _gift_public_config(cliente_id)
    business = str(config.get("empresa") or config.get("nombre") or "Nuestro negocio")
    color = str((config.get("branding") or {}).get("color") or config.get("color") or "#6d28d9")
    contacto = config.get("contacto") or {}
    contact_bits = " &middot; ".join(
        x for x in (
            textnorm._sanitize_text(str(contacto.get("telefono") or "")),
            textnorm._sanitize_text(str(contacto.get("direccion") or "")),
        ) if x
    )
    intro = cfg["intro_text"] or (
        f"Regala una experiencia en {business}. La tarjeta llega por email, "
        "al instante o el dia que elijas."
    )
    chips = "".join(
        f'<button type="button" class="chip" data-cents="{c}">{c // 100} &euro;</button>'
        for c in cfg["suggested_amounts"]
    )
    min_eur, max_eur = cfg["min_cents"] // 100, cfg["max_cents"] // 100
    try:
        services_raw = booking._public_services_for_booking(cliente_id)
    except Exception:  # noqa: BLE001
        services_raw = []
    gift_services = []
    for svc in services_raw[:30]:
        if not isinstance(svc, dict):
            continue
        price = int(svc.get("price_cents") or 0)
        name = textnorm._sanitize_text(str(svc.get("nombre") or svc.get("name") or ""))
        slug = str(svc.get("id") or svc.get("slug") or "")
        if price > 0 and name and slug:
            gift_services.append({"slug": slug, "name": name, "price_cents": price})
    service_options = "".join(
        f'<option value="{svc["slug"]}" data-name="{svc["name"]}" data-cents="{svc["price_cents"]}">'
        f'{svc["name"]} &middot; {svc["price_cents"] // 100} &euro;</option>'
        for svc in gift_services
    )
    service_tab_hidden = "" if gift_services else 'style="display:none"'
    palette = ["", "#6d28d9", "#0e7490", "#be123c", "#b45309", "#166534", "#111827"]
    swatches = "".join(
        (
            f'<button type="button" class="sw{" on" if not c else ""}" data-color="{c}" '
            f'style="background:{c or color}" aria-label="{"Color del negocio" if not c else c}"></button>'
        )
        for c in palette
    )
    validity_hint = (
        f"Validez: {cfg['validity_days']} dias desde la compra." if cfg["validity_days"] else ""
    )
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="theme-color" content="{color}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#127873;</text></svg>">
<title>Tarjeta regalo &middot; {business}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{ --accent: {color}; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    background: #f6f6f9; color: #111827; -webkit-font-smoothing: antialiased;
  }}
  .top {{ background: linear-gradient(135deg, var(--accent), #111827); padding: 40px 16px 88px; text-align: center; color: #fff; }}
  .top .k {{ font-size: 12px; letter-spacing: 3px; text-transform: uppercase; opacity: .8; }}
  .top h1 {{ font-size: 26px; font-weight: 800; margin-top: 6px; }}
  .top p {{ max-width: 560px; margin: 10px auto 0; font-size: 15px; opacity: .92; line-height: 1.5; }}
  .wrap {{ max-width: 980px; margin: -56px auto 40px; padding: 0 16px; display: grid; grid-template-columns: 1fr 380px; gap: 22px; align-items: start; }}
  @media (max-width: 860px) {{ .wrap {{ grid-template-columns: 1fr; }} .preview-col {{ order: -1; position: static; top: auto; }} }}
  .panel {{ background: #fff; border-radius: 16px; padding: 26px; box-shadow: 0 10px 40px rgba(17,24,39,.10); }}
  .step {{ display: flex; align-items: center; gap: 10px; margin: 26px 0 12px; }}
  .step:first-child {{ margin-top: 0; }}
  .step .num {{ width: 26px; height: 26px; border-radius: 50%; background: var(--accent); color: #fff; font-size: 13px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex: none; }}
  .step h2 {{ font-size: 15px; font-weight: 700; }}
  label {{ display: block; font-size: 13px; font-weight: 600; margin: 12px 0 5px; color: #374151; }}
  input, textarea, select {{
    width: 100%; padding: 11px 13px; border: 1.5px solid #e5e7eb; border-radius: 10px;
    font-size: 15px; font-family: inherit; background: #fff; transition: border-color .15s;
  }}
  input:focus, textarea:focus, select:focus {{ outline: none; border-color: var(--accent); }}
  textarea {{ resize: vertical; min-height: 72px; }}
  .tabs {{ display: flex; gap: 8px; }}
  .tab {{
    flex: 1; padding: 11px; border: 1.5px solid #e5e7eb; background: #fff; border-radius: 10px;
    font-size: 14px; font-weight: 600; cursor: pointer; color: #374151; transition: all .15s;
  }}
  .tab.on {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  .chips {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }}
  .chip {{
    padding: 10px 18px; border-radius: 999px; border: 1.5px solid #e5e7eb; background: #fff;
    font-size: 15px; font-weight: 600; cursor: pointer; transition: all .15s;
  }}
  .chip.on {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  @media (max-width: 480px) {{ .row {{ grid-template-columns: 1fr; }} }}
  .hint {{ font-size: 12px; color: #6b7280; margin-top: 4px; }}
  .count {{ float: right; font-weight: 400; color: #9ca3af; }}
  .sw {{ width: 32px; height: 32px; border-radius: 50%; border: 2.5px solid #e5e7eb; cursor: pointer; transition: transform .12s; padding: 0; }}
  .sw.on {{ border-color: #111827; transform: scale(1.15); }}
  .checks label {{ display: flex; gap: 9px; align-items: center; font-weight: 400; font-size: 14px; color: #374151; margin: 9px 0 0; cursor: pointer; }}
  .checks input {{ width: 16px; height: 16px; accent-color: var(--accent); }}
  button.cta {{
    width: 100%; margin-top: 24px; padding: 15px; border: 0; border-radius: 12px;
    background: var(--accent); color: #fff; font-size: 16px; font-weight: 700; cursor: pointer;
    display: flex; align-items: center; justify-content: center; gap: 10px; transition: filter .15s;
  }}
  button.cta:hover {{ filter: brightness(1.08); }}
  button.cta:disabled {{ opacity: .65; cursor: wait; }}
  .spin {{ width: 16px; height: 16px; border: 2px solid rgba(255,255,255,.4); border-top-color: #fff; border-radius: 50%; animation: r 0.7s linear infinite; display: none; }}
  @keyframes r {{ to {{ transform: rotate(360deg); }} }}
  .secure {{ text-align: center; font-size: 12px; color: #6b7280; margin-top: 12px; display: flex; align-items: center; justify-content: center; gap: 6px; line-height: 1.45; }}
  .banner {{ border-radius: 10px; padding: 13px 15px; font-size: 14px; margin-bottom: 16px; display: none; line-height: 1.45; }}
  .banner.ok {{ background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }}
  .banner.err {{ background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }}
  /* --- Vista previa en vivo --- */
  .preview-col {{ position: sticky; top: 18px; }}
  .pv-label {{ font-size: 12px; letter-spacing: 2px; text-transform: uppercase; color: #9ca3af; text-align: center; margin-bottom: 10px; font-weight: 600; }}
  .gcard {{
    border-radius: 18px; padding: 26px 24px; color: #fff; min-height: 210px;
    background: linear-gradient(135deg, var(--pv, var(--accent)), #111827);
    box-shadow: 0 14px 34px rgba(17,24,39,.28); position: relative; overflow: hidden;
    display: flex; flex-direction: column; justify-content: space-between; gap: 14px;
    transition: background .25s;
  }}
  .gcard::after {{ content: ""; position: absolute; right: -46px; top: -46px; width: 150px; height: 150px; border-radius: 50%; background: rgba(255,255,255,.10); }}
  .gcard .brand {{ font-size: 12px; letter-spacing: 2px; text-transform: uppercase; opacity: .85; }}
  .gcard .biz {{ font-size: 20px; font-weight: 800; margin-top: 2px; }}
  .gcard .amount {{ font-size: 32px; font-weight: 800; }}
  .gcard .code {{ background: rgba(255,255,255,.16); border-radius: 10px; padding: 10px; text-align: center; font-size: 17px; letter-spacing: 3px; font-weight: 700; }}
  .gcard .to {{ font-size: 13px; opacity: .9; min-height: 17px; }}
  .gcard .msg {{ font-size: 13px; font-style: italic; opacity: .85; min-height: 17px; word-break: break-word; }}
  .pv-note {{ font-size: 12px; color: #9ca3af; text-align: center; margin-top: 12px; line-height: 1.5; }}
  @media (max-width: 860px) {{ .preview-col {{ position: static; top: auto; margin-top: -30px; }} .gcard {{ min-height: 170px; }} }}
  footer {{ text-align: center; font-size: 12.5px; color: #9ca3af; padding: 0 16px 34px; line-height: 1.7; }}
</style>
</head>
<body>
<div class="top">
  <div class="k">Tarjeta regalo</div>
  <h1>{business}</h1>
  <p>{intro}</p>
</div>
<div class="wrap">
  <div class="panel">
    <div id="bok" class="banner ok">&#127873; <b>&iexcl;Pago completado!</b> La tarjeta llegara por email al destinatario y te hemos enviado una copia a ti. &iexcl;Gracias!</div>
    <div id="berr" class="banner err"></div>
    <form id="f" novalidate>
      <div class="step"><span class="num">1</span><h2>&iquest;Que regalas?</h2></div>
      <div class="tabs">
        <button type="button" class="tab on" id="tabAmount">Un importe</button>
        <button type="button" class="tab" id="tabService" {service_tab_hidden}>Un servicio</button>
      </div>
      <div id="paneAmount">
        <div class="chips">{chips}</div>
        <input type="number" id="amount" min="{min_eur}" max="{max_eur}" step="1" inputmode="numeric" placeholder="Otro importe ({min_eur}&ndash;{max_eur} &euro;)">
        <div class="hint">Entre {min_eur} y {max_eur} &euro;. {validity_hint}</div>
      </div>
      <div id="paneService" style="display:none">
        <select id="service"><option value="">Elige un servicio&hellip;</option>{service_options}</select>
        <div class="hint">El importe es el precio actual del servicio y se entrega como saldo canjeable.</div>
      </div>

      <div class="step"><span class="num">2</span><h2>&iquest;Para quien es?</h2></div>
      <div class="row">
        <div><label for="rn">Nombre de quien lo recibe</label><input id="rn" maxlength="120" autocomplete="off" required></div>
        <div><label for="re">Su email</label><input id="re" type="email" maxlength="160" required></div>
      </div>
      <label for="msg">Mensaje <span class="count" id="msgCount">0/300</span></label>
      <textarea id="msg" maxlength="300" placeholder="Ej.: &iexcl;Felicidades! Disfrutalo mucho."></textarea>

      <div class="step"><span class="num">3</span><h2>Personalizala</h2></div>
      <label>Color de la tarjeta</label>
      <div class="chips" id="swatches">{swatches}</div>
      <div class="checks">
        <label><input type="checkbox" id="hide_value"> Ocultar el importe en el email del destinatario</label>
        <label><input type="checkbox" id="hide_expiry"> Ocultar la fecha de caducidad</label>
      </div>

      <div class="step"><span class="num">4</span><h2>Tus datos y envio</h2></div>
      <div class="row">
        <div><label for="bn">Tu nombre</label><input id="bn" maxlength="120" autocomplete="name" required></div>
        <div><label for="be">Tu email</label><input id="be" type="email" maxlength="160" autocomplete="email" required></div>
      </div>
      <label for="send_at">&iquest;Cuando lo enviamos?</label>
      <input type="date" id="send_at">
      <div class="hint">Dejalo vacio para enviarlo nada mas pagar. Recibiras una copia para imprimir.</div>

      <button class="cta" id="pay" type="submit"><span class="spin" id="spin"></span><span id="payTxt">Pagar y enviar la tarjeta</span></button>
      <div class="secure">&#128274; Pago seguro con tarjeta (Stripe). Recibiras una copia, el destinatario podra consultar saldo y se canjea al reservar o en recepcion.</div>
    </form>
  </div>

  <div class="preview-col">
    <div class="pv-label">Asi la vera</div>
    <div class="gcard" id="gcard">
      <div>
        <div class="brand">Tarjeta regalo</div>
        <div class="biz">{business}</div>
      </div>
      <div class="amount" id="pvAmount">&nbsp;</div>
      <div class="code">GC-&bull;&bull;&bull;&bull;-&bull;&bull;&bull;&bull;</div>
      <div>
        <div class="to" id="pvTo"></div>
        <div class="msg" id="pvMsg"></div>
      </div>
    </div>
    <div class="pv-note">El codigo se genera al completar el pago.<br>Llega por email con este mismo diseno.</div>
  </div>
</div>
<footer>{business}{(" &middot; " + contact_bits) if contact_bits else ""}<br>Compra segura &middot; Sin gastos adicionales<br><a href="/gift/{cliente_id}/saldo" style="color:inherit">&iquest;Ya tienes una tarjeta? Consulta tu saldo</a></footer>
<script>
(function () {{
  var qs = new URLSearchParams(location.search);
  var safe = function (s) {{ var d = document.createElement("div"); d.textContent = String(s == null ? "" : s); return d.innerHTML; }};
  function showGiftSuccess(html) {{
    var box = document.getElementById("bok");
    box.innerHTML = html;
    box.style.display = "block";
    window.scrollTo(0, 0);
  }}
  function pollCheckoutStatus(sessionId) {{
    var attempts = 0;
    function check() {{
      fetch(location.pathname + "/checkout-status?session_id=" + encodeURIComponent(sessionId))
        .then(function (r) {{ return r.json().then(function (d) {{ return {{ ok: r.ok, d: d }}; }}); }})
        .then(function (res) {{
          if (!res.ok) throw new Error((res.d && res.d.detail) || "No se pudo comprobar el pago.");
          var d = res.d;
          if (d.status !== "paid" || !d.ready) {{
            showGiftSuccess("&#127873; <b>Pago completado.</b> Estamos activando tu tarjeta y enviando los emails. En unos segundos deberia aparecer el codigo aqui.");
            if (attempts++ < 8) setTimeout(check, 1500);
            return;
          }}
          if (d.kind === "gift_card") {{
            showGiftSuccess("&#127873; <b>Tarjeta creada.</b> Codigo: <b>" + safe(d.code) + "</b>. El destinatario recibira el email y tu recibiras una copia. <a href=\\"" + safe(d.balance_url) + "\\" target=\\"_blank\\" rel=\\"noopener\\">Consultar saldo</a>");
          }}
        }})
        .catch(function () {{
          showGiftSuccess("&#127873; <b>Pago completado.</b> La tarjeta llegara por email al destinatario y te hemos enviado una copia a ti. Si tarda unos minutos, revisa el correo.");
        }});
    }}
    check();
  }}
  if (qs.get("ok")) {{
    showGiftSuccess("&#127873; <b>&iexcl;Pago completado!</b> Estamos activando la tarjeta y enviando los emails.");
    if (qs.get("session_id")) pollCheckoutStatus(qs.get("session_id"));
  }}
  var amount = 0;
  var serviceSlug = "";
  var serviceName = "";
  var accent = "";
  var eur = function (c) {{ return (c / 100).toLocaleString("es-ES") + " \u20AC"; }};
  function paint() {{
    var card = document.getElementById("gcard");
    card.style.setProperty("--pv", accent || "{color}");
    var hide = document.getElementById("hide_value").checked;
    var label = "\u00A0";
    if (serviceName) label = serviceName;
    else if (hide && amount > 0) label = "Una experiencia";
    else if (amount > 0) label = eur(amount);
    document.getElementById("pvAmount").textContent = label;
    var rn = document.getElementById("rn").value.trim();
    document.getElementById("pvTo").textContent = rn ? "Para: " + rn : "";
    var m = document.getElementById("msg").value.trim();
    document.getElementById("pvMsg").textContent = m ? "\u201C" + m + "\u201D" : "";
  }}
  var tabA = document.getElementById("tabAmount");
  var tabS = document.getElementById("tabService");
  function showPane(svc) {{
    tabA.classList.toggle("on", !svc);
    tabS.classList.toggle("on", !!svc);
    document.getElementById("paneAmount").style.display = svc ? "none" : "block";
    document.getElementById("paneService").style.display = svc ? "block" : "none";
    if (!svc) {{ serviceSlug = ""; serviceName = ""; document.getElementById("service").value = ""; }}
    paint();
  }}
  tabA.addEventListener("click", function () {{ showPane(false); }});
  if (tabS) tabS.addEventListener("click", function () {{ showPane(true); }});
  document.getElementById("service").addEventListener("change", function () {{
    serviceSlug = this.value || "";
    var opt = this.options[this.selectedIndex];
    serviceName = serviceSlug ? (opt.getAttribute("data-name") || "") : "";
    amount = serviceSlug ? parseInt(opt.getAttribute("data-cents") || "0", 10) : amount;
    paint();
  }});
  var chips = document.querySelectorAll(".chip:not(.sw)");
  chips.forEach(function (ch) {{
    ch.addEventListener("click", function () {{
      chips.forEach(function (o) {{ o.classList.remove("on"); }});
      ch.classList.add("on");
      amount = parseInt(ch.getAttribute("data-cents"), 10);
      document.getElementById("amount").value = "";
      paint();
    }});
  }});
  document.getElementById("amount").addEventListener("input", function () {{
    chips.forEach(function (o) {{ o.classList.remove("on"); }});
    amount = Math.round((parseFloat(this.value) || 0) * 100);
    paint();
  }});
  document.querySelectorAll("#swatches .sw").forEach(function (sw) {{
    sw.addEventListener("click", function () {{
      document.querySelectorAll("#swatches .sw").forEach(function (o) {{ o.classList.remove("on"); }});
      sw.classList.add("on");
      accent = sw.getAttribute("data-color") || "";
      paint();
    }});
  }});
  ["rn", "msg"].forEach(function (id) {{
    document.getElementById(id).addEventListener("input", paint);
  }});
  document.getElementById("hide_value").addEventListener("change", paint);
  document.getElementById("msg").addEventListener("input", function () {{
    document.getElementById("msgCount").textContent = this.value.length + "/300";
  }});
  var minDate = new Date();
  document.getElementById("send_at").min = minDate.toISOString().slice(0, 10);
  document.getElementById("f").addEventListener("submit", function (ev) {{
    ev.preventDefault();
    var err = document.getElementById("berr");
    err.style.display = "none";
    if (!serviceSlug && (!amount || amount < {min_eur} * 100 || amount > {max_eur} * 100)) {{
      err.textContent = "Elige un importe entre {min_eur} y {max_eur} \u20AC o un servicio.";
      err.style.display = "block";
      return;
    }}
    var btn = document.getElementById("pay");
    btn.disabled = true;
    document.getElementById("spin").style.display = "inline-block";
    document.getElementById("payTxt").textContent = "Conectando con el pago seguro\u2026";
    var fail = function (msg) {{
      err.textContent = msg || "No se pudo iniciar el pago. Intentalo de nuevo.";
      err.style.display = "block";
      btn.disabled = false;
      document.getElementById("spin").style.display = "none";
      document.getElementById("payTxt").textContent = "Pagar y enviar la tarjeta";
    }};
    fetch(location.pathname + "/checkout", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{
        amount_cents: serviceSlug ? 0 : amount,
        service_slug: serviceSlug,
        accent_color: accent,
        hide_value: document.getElementById("hide_value").checked,
        hide_expiry: document.getElementById("hide_expiry").checked,
        buyer_name: document.getElementById("bn").value.trim(),
        buyer_email: document.getElementById("be").value.trim(),
        recipient_name: document.getElementById("rn").value.trim(),
        recipient_email: document.getElementById("re").value.trim(),
        message: document.getElementById("msg").value.trim(),
        scheduled_send_at: document.getElementById("send_at").value || ""
      }})
    }}).then(function (r) {{ return r.json().then(function (d) {{ return {{ ok: r.ok, d: d }}; }}); }})
      .then(function (res) {{
        if (res.ok && res.d.url) {{ location.href = res.d.url; return; }}
        fail(res.d && res.d.detail);
      }})
      .catch(function () {{ fail(); }});
  }});
  paint();
}})();
</script>
</body>
</html>"""


# --- Tienda publica: bonos y productos (jul 2026) ----------------------------------
# El cliente FINAL compra online en /tienda/{cliente_id} (bonos de sesiones y
# productos con recogida en el centro). MISMO rail que el POS y las tarjetas regalo:
# customer_payments + Stripe Checkout (cuenta Connect) + webhook idempotente que
# materializa la compra al pasar a 'paid'. Opt-in por tenant via config['shop_public']
# (seccion registrada en clients.CONFIG_EXTRA_SECTIONS). El precio SIEMPRE sale del
# catalogo del servidor, nunca del request.


def _shop_public_config(cliente_id: str) -> Dict[str, Any]:
    """Config saneada de la tienda publica (default OFF en ambas secciones)."""
    from backend import appstate  # tardio: evita ciclo en el arranque

    raw = ((appstate.CONFIG_CLIENTES.get(cliente_id) or {}).get("shop_public") or {})
    accent = str(raw.get("accent_color") or "").strip()
    if not _GIFT_ACCENT_RE.match(accent):
        accent = ""
    return {
        "enabled_packages": bool(raw.get("enabled_packages")),
        "enabled_products": bool(raw.get("enabled_products")),
        "intro_text": textnorm._sanitize_text(str(raw.get("intro_text") or ""))[:300],
        "pickup_note": textnorm._sanitize_text(str(raw.get("pickup_note") or ""))[:200],
        "accent_color": accent,
        # Personalizacion de la central publica (hero): foto de cabecera + frase.
        "hero_image_url": textnorm._public_image_url(raw.get("hero_image_url")),
        "hero_tagline": textnorm._sanitize_text(str(raw.get("hero_tagline") or ""))[:140],
    }


def shop_public_available(cliente_id: str) -> Dict[str, bool]:
    """Disponibilidad real de la tienda: opt-in + Stripe operativo + catalogo con items
    activos. Devuelve {'packages': bool, 'products': bool, 'any': bool}."""
    cfg = _shop_public_config(cliente_id)
    result = {"packages": False, "products": False, "any": False}
    if not cfg["enabled_packages"] and not cfg["enabled_products"]:
        return result
    try:
        account = booking._connect_account_status(cliente_id)
        stripe_ok = bool(account.connected and account.charges_enabled)
    except Exception:  # noqa: BLE001
        stripe_ok = False
    if not stripe_ok:
        return result
    if cfg["enabled_packages"]:
        result["packages"] = bool(_list_packages(cliente_id, include_inactive=False))
    if cfg["enabled_products"]:
        result["products"] = any(
            p for p in _list_products(cliente_id, include_inactive=False)
            if p["stock"] is None or int(p["stock"]) > 0
        )
    result["any"] = result["packages"] or result["products"]
    return result


def _shop_validate_buyer(buyer_name: str, buyer_email: str) -> Dict[str, str]:
    name = textnorm._sanitize_text(buyer_name or "")[:120]
    email = textnorm._sanitize_text(buyer_email or "").strip().lower()[:160]
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Falta el nombre del comprador.")
    if not textnorm.EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Revisa el email: no parece valido.")
    return {"buyer_name": name, "buyer_email": email}


def _package_items_summary(cliente_id: str, items: Any) -> List[str]:
    """Lineas legibles del contenido de un bono: '3x Masaje relajante 60 min'."""
    out: List[str] = []
    for item in items or []:
        slug = str(item.get("service_slug") or "")
        qty = int(item.get("qty") or 0)
        if not slug or qty < 1:
            continue
        row = agenda._get_service_row(cliente_id, slug)
        name = (row["name"] if row else slug) or slug
        out.append(f"{qty}x {name}")
    return out


def create_shop_package_payment_link(
    cliente_id: str, *, package_id: str, buyer_name: str, buyer_email: str,
    buyer_phone: str = "", base_url: str = "",
) -> Dict[str, Any]:
    """Checkout de Stripe para la compra ONLINE de un bono. El bono NO se crea aqui:
    se materializa en el webhook (_finalize_shop_package_payment) al confirmarse el
    pago, con snapshot del contenido tomado AHORA (ediciones posteriores del bono no
    afectan a compras en vuelo)."""
    cfg = _shop_public_config(cliente_id)
    if not cfg["enabled_packages"]:
        raise HTTPException(status_code=404, detail="La compra online de bonos no esta disponible.")
    row = _get_package_row(cliente_id, textnorm._sanitize_text(package_id or ""))
    if not row or not bool(row["is_active"]):
        raise HTTPException(status_code=404, detail="Bono no disponible.")
    price = int(row["price_cents"] or 0)
    if price < 50:
        raise HTTPException(status_code=409, detail="Este bono no tiene un precio valido para venta online.")
    buyer = _shop_validate_buyer(buyer_name, buyer_email)
    phone = textnorm._sanitize_text(buyer_phone or "")[:40]
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

    account = booking._connect_account_status(cliente_id, refresh=True)
    if not account.connected or not account.charges_enabled:
        raise HTTPException(status_code=409, detail="El negocio aun no tiene el cobro online activo.")

    from backend import appstate  # tardio

    tenant_cfg = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    business_name = str(tenant_cfg.get("empresa") or tenant_cfg.get("nombre") or "el negocio")

    payment_id, now = "pay_" + secrets.token_hex(10), timeutils._utc_now_iso()
    meta = {
        "package_id": row["id"], "package_name": row["name"],
        "validity_days": int(row["validity_days"] or 365), "remaining": remaining,
        "items_summary": _package_items_summary(cliente_id, items),
        "buyer_name": buyer["buyer_name"], "buyer_email": buyer["buyer_email"],
        "buyer_phone": phone,
    }
    metadata = {
        "source": "customer_payment", "kind": "shop_package", "payment_id": payment_id,
        "cliente_id": cliente_id,
    }
    base = (base_url or "").rstrip("/")
    stripe_gateway._stripe_init()
    try:
        session = stripe_gateway.stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "eur", "unit_amount": price,
                    "product_data": {"name": f"Bono {row['name']} - {business_name}"},
                },
                "quantity": 1,
            }],
            metadata=metadata,
            customer_email=buyer["buyer_email"],
            success_url=f"{base}/tienda/{cliente_id}?solo=bonos&ok=1&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/tienda/{cliente_id}?cancel=1",
            stripe_account=account.stripe_account_id,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("No se pudo crear checkout de bono %s: %s", cliente_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo iniciar el pago.") from exc

    checkout_url = textnorm._object_get(session, "url", "")
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO customer_payments
                (id, cliente_id, contact_id, booking_id, service_id, service_name, stripe_account_id,
                 stripe_checkout_session_id, amount_cents, currency, status, checkout_url,
                 kind, line_items_json, created_at, updated_at)
            VALUES (?, ?, '', '', '', ?, ?, ?, ?, 'eur', 'pending', ?, 'shop_package', ?, ?, ?)
            """,
            (
                payment_id, cliente_id, buyer["buyer_name"],
                account.stripe_account_id, textnorm._object_get(session, "id", ""),
                price, checkout_url, json.dumps(meta, ensure_ascii=False), now, now,
            ),
        )
        connection.commit()
    return {"payment_id": payment_id, "url": checkout_url, "amount_cents": price}


def create_shop_products_payment_link(
    cliente_id: str, *, items: Any, buyer_name: str, buyer_email: str,
    buyer_phone: str = "", base_url: str = "",
) -> Dict[str, Any]:
    """Checkout de Stripe para la compra ONLINE de productos (recogida en el centro).
    Reutiliza la validacion del POS (_pos_resolve_lines: catalogo + stock + precio del
    servidor); la venta se materializa en el webhook (_finalize_shop_products_payment)."""
    cfg = _shop_public_config(cliente_id)
    if not cfg["enabled_products"]:
        raise HTTPException(status_code=404, detail="La compra online de productos no esta disponible.")
    lines = _pos_resolve_lines(cliente_id, items)
    if not lines:
        raise HTTPException(status_code=400, detail="Anade al menos un producto.")
    amount = sum(int(l["unit_price_cents"]) * int(l["qty"]) for l in lines)
    if amount < 50:
        raise HTTPException(status_code=400, detail="El importe minimo de compra es 0,50 EUR.")
    buyer = _shop_validate_buyer(buyer_name, buyer_email)
    phone = textnorm._sanitize_text(buyer_phone or "")[:40]

    account = booking._connect_account_status(cliente_id, refresh=True)
    if not account.connected or not account.charges_enabled:
        raise HTTPException(status_code=409, detail="El negocio aun no tiene el cobro online activo.")

    payment_id, now = "pay_" + secrets.token_hex(10), timeutils._utc_now_iso()
    meta = {
        "lines": lines,
        "buyer_name": buyer["buyer_name"], "buyer_email": buyer["buyer_email"],
        "buyer_phone": phone,
    }
    metadata = {
        "source": "customer_payment", "kind": "shop_products", "payment_id": payment_id,
        "cliente_id": cliente_id,
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
        session = stripe_gateway.stripe.checkout.Session.create(
            mode="payment", line_items=stripe_lines, metadata=metadata,
            customer_email=buyer["buyer_email"],
            success_url=f"{base}/tienda/{cliente_id}?solo=productos&ok=1&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/tienda/{cliente_id}?cancel=1",
            stripe_account=account.stripe_account_id,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("No se pudo crear checkout de tienda %s: %s", cliente_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo iniciar el pago.") from exc

    checkout_url = textnorm._object_get(session, "url", "")
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO customer_payments
                (id, cliente_id, contact_id, booking_id, service_id, service_name, stripe_account_id,
                 stripe_checkout_session_id, amount_cents, currency, status, checkout_url,
                 kind, line_items_json, created_at, updated_at)
            VALUES (?, ?, '', '', '', ?, ?, ?, ?, 'eur', 'pending', ?, 'shop_products', ?, ?, ?)
            """,
            (
                payment_id, cliente_id, buyer["buyer_name"],
                account.stripe_account_id, textnorm._object_get(session, "id", ""),
                amount, checkout_url, json.dumps(meta, ensure_ascii=False), now, now,
            ),
        )
        connection.commit()
    return {"payment_id": payment_id, "url": checkout_url, "amount_cents": amount}


def public_checkout_status(cliente_id: str, session_id: str) -> Dict[str, Any]:
    """Estado publico tras volver de Stripe. El session_id de Checkout es el secreto
    de la redireccion; no lista compras ni acepta busqueda por email/telefono."""
    sid = textnorm._sanitize_text(session_id or "").strip()[:220]
    if not sid:
        raise HTTPException(status_code=400, detail="Falta la sesion de pago.")
    with db._get_db_connection() as connection:
        payment = connection.execute(
            "SELECT * FROM customer_payments WHERE cliente_id = ? AND stripe_checkout_session_id = ? "
            "AND kind IN ('gift_card', 'shop_package', 'shop_products') LIMIT 1",
            (cliente_id, sid),
        ).fetchone()
        if not payment:
            raise HTTPException(status_code=404, detail="No encontramos ese pago.")
        result: Dict[str, Any] = {
            "ok": True,
            "kind": payment["kind"] or "",
            "status": payment["status"] or "pending",
            "amount_cents": int(payment["amount_cents"] or 0),
            "ready": False,
        }
        if result["status"] != "paid":
            return result
        if result["kind"] == "shop_package":
            purchase = connection.execute(
                "SELECT * FROM package_purchases WHERE cliente_id = ? AND customer_payment_id = ? LIMIT 1",
                (cliente_id, payment["id"]),
            ).fetchone()
            if purchase:
                info = _purchase_to_public(purchase)
                result.update({
                    "ready": True,
                    "package_name": info["package_name"],
                    "wallet_url": info["wallet_url"],
                    "remaining_total": info["remaining_total"],
                    "expires_at": (info["expires_at"] or "")[:10],
                })
            return result
        if result["kind"] == "gift_card":
            card = connection.execute(
                "SELECT * FROM gift_cards WHERE cliente_id = ? AND customer_payment_id = ? LIMIT 1",
                (cliente_id, payment["id"]),
            ).fetchone()
            if card:
                balance_url = (
                    f"{textnorm._preferred_public_base_url().rstrip('/')}/gift/{cliente_id}/saldo?code={card['code']}"
                )
                result.update({
                    "ready": True,
                    "code": card["code"],
                    "balance_cents": int(card["balance_cents"] or 0),
                    "balance_url": balance_url,
                    "recipient_email": card["recipient_email"] or "",
                })
            return result
        result["ready"] = True
        return result


def _finalize_shop_package_payment(connection: sqlite3.Connection, payment: sqlite3.Row, now: str) -> bool:
    """Crea el bono comprado online cuando el pago pasa a 'paid'. Idempotente via
    package_purchases.customer_payment_id; usa la conexion del webhook (sin commit).
    Devuelve True si la compra se creo en ESTA llamada (para enviar el email una vez)."""
    cliente_id = payment["cliente_id"]
    pay_id = payment["id"]
    already = connection.execute(
        "SELECT COUNT(*) FROM package_purchases WHERE customer_payment_id=?", (pay_id,)
    ).fetchone()[0]
    if already:
        return False
    try:
        meta = json.loads(payment["line_items_json"] or "{}")
    except (ValueError, TypeError):
        meta = {}
    remaining = {
        str(k): int(v) for k, v in (meta.get("remaining") or {}).items() if int(v or 0) > 0
    }
    if not remaining:
        settings.logger.error("Compra de bono %s sin sesiones en el snapshot; se omite.", pay_id)
        return False
    validity_days = int(meta.get("validity_days") or 365)
    expires_at = (timeutils._utc_now() + timedelta(days=validity_days)).isoformat()
    purchase_id = f"pkp_{secrets.token_urlsafe(8)}"
    remaining_json = json.dumps(remaining, ensure_ascii=False)
    connection.execute(
        """
        INSERT INTO package_purchases (id, cliente_id, package_id, package_name, buyer_name,
                                       buyer_email, buyer_phone, price_cents, remaining_json,
                                       initial_json, wallet_token, expires_at, status,
                                       payment_method, location_id, customer_payment_id,
                                       created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'stripe', '', ?, ?, ?)
        """,
        (
            purchase_id, cliente_id,
            str(meta.get("package_id") or ""), str(meta.get("package_name") or ""),
            str(meta.get("buyer_name") or ""), str(meta.get("buyer_email") or ""),
            str(meta.get("buyer_phone") or ""),
            int(payment["amount_cents"] or 0),
            remaining_json, remaining_json,
            f"pw_{secrets.token_urlsafe(18)}",
            expires_at, pay_id, now, now,
        ),
    )
    return True


def _finalize_shop_products_payment(connection: sqlite3.Connection, payment: sqlite3.Row, now: str) -> bool:
    """Registra las ventas de una compra online de productos pagada (descuenta stock).
    Idempotente via product_sales.customer_payment_id; sin commit (transaccion del
    webhook). Devuelve True si las ventas se crearon en ESTA llamada."""
    cliente_id = payment["cliente_id"]
    pay_id = payment["id"]
    already = connection.execute(
        "SELECT COUNT(*) FROM product_sales WHERE customer_payment_id=?", (pay_id,)
    ).fetchone()[0]
    if already:
        return False
    try:
        meta = json.loads(payment["line_items_json"] or "{}")
    except (ValueError, TypeError):
        meta = {}
    buyer_name = str(meta.get("buyer_name") or "")
    buyer_email = str(meta.get("buyer_email") or "")
    created = False
    for l in meta.get("lines") or []:
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
            VALUES (?, ?, '', ?, ?, ?, ?, ?, '', ?, ?, 'stripe', 'compra online', 'paid', ?, ?)
            """,
            (
                sale_id, cliente_id, l.get("product_id", ""), l.get("name", ""),
                qty, unit, unit * qty, buyer_name, buyer_email, pay_id, now,
            ),
        )
        connection.execute(
            "UPDATE products SET stock = CASE WHEN stock IS NULL THEN NULL ELSE MAX(0, stock - ?) END, "
            "updated_at=? WHERE cliente_id=? AND id=?",
            (qty, now, cliente_id, l.get("product_id", "")),
        )
        created = True
    return created


def _guard_refundable_asset(payment: sqlite3.Row, amount_cents: Optional[int], force: bool) -> None:
    """Pre-check antes de pedir un reembolso a Stripe sobre un pago que emitio un
    activo (tarjeta regalo o bono online): si el activo ya tiene consumo, exige
    ``force`` para no devolver dinero cuyo valor ya se ha gastado. El revert real
    del activo lo aplica el webhook charge.refunded (_revert_assets_after_refund)."""
    kind = payment["kind"] if "kind" in payment.keys() else ""
    if kind not in ("gift_card", "shop_package"):
        return
    refund = int(amount_cents) if amount_cents else int(payment["amount_cents"] or 0)
    with db._get_db_connection() as connection:
        if kind == "gift_card":
            card = connection.execute(
                "SELECT * FROM gift_cards WHERE customer_payment_id = ? LIMIT 1", (payment["id"],)
            ).fetchone()
            if not card:
                return
            balance = int(card["balance_cents"] or 0)
            if refund > balance and not force:
                spent = max(0, int(card["initial_cents"] or 0) - balance)
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"La tarjeta {card['code']} ya tiene {textnorm._format_price_cents(spent)} consumidos "
                        f"(saldo restante {textnorm._format_price_cents(balance)}). Reembolsa como maximo el saldo "
                        "o marca 'forzar' para anular la tarjeta igualmente."
                    ),
                )
        else:
            purchase = connection.execute(
                "SELECT * FROM package_purchases WHERE customer_payment_id = ? LIMIT 1", (payment["id"],)
            ).fetchone()
            if not purchase:
                return
            info = _purchase_to_public(purchase)
            if info["used_total"] > 0 and not force:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"El bono ya tiene {info['used_total']} sesion(es) usadas. "
                        "Marca 'forzar' para reembolsar y anular el bono igualmente."
                    ),
                )


def _revert_assets_after_refund(
    connection: sqlite3.Connection, payment: sqlite3.Row, refunded_total_cents: int, now: str
) -> None:
    """Retira el activo emitido por un pago reembolsado (tarjeta regalo o bono online).

    Orientado a objetivo e idempotente: recibe el TOTAL acumulado reembolsado (el
    ``amount_refunded`` de Stripe) y deja el activo en el estado que corresponde,
    de forma que reintentos del webhook no dupliquen la retirada. Usa la conexion
    del webhook (sin commit)."""
    kind = payment["kind"] if "kind" in payment.keys() else ""
    refunded = max(0, int(refunded_total_cents or 0))
    if not refunded:
        return
    if kind == "gift_card":
        card = connection.execute(
            "SELECT * FROM gift_cards WHERE customer_payment_id = ? LIMIT 1", (payment["id"],)
        ).fetchone()
        if not card:
            return
        initial = int(card["initial_cents"] or 0)
        balance = int(card["balance_cents"] or 0)
        target_balance = max(0, initial - refunded)
        if balance <= target_balance:
            return
        deduct = balance - target_balance
        new_status = "disabled" if target_balance <= 0 else card["status"]
        connection.execute(
            "UPDATE gift_cards SET balance_cents = ?, status = ?, updated_at = ? WHERE id = ?",
            (target_balance, new_status, now, card["id"]),
        )
        connection.execute(
            """
            INSERT INTO gift_card_transactions (cliente_id, gift_card_id, kind, amount_cents,
                                                balance_after_cents, notes, created_at)
            VALUES (?, ?, 'refund', ?, ?, 'reembolso del pago', ?)
            """,
            (payment["cliente_id"], card["id"], deduct, target_balance, now),
        )
    elif kind == "shop_package":
        purchase = connection.execute(
            "SELECT * FROM package_purchases WHERE customer_payment_id = ? LIMIT 1", (payment["id"],)
        ).fetchone()
        # Solo el reembolso TOTAL anula el bono; uno parcial es decision del negocio
        # (p.ej. compensar una sesion) y deja el bono vivo.
        if not purchase or purchase["status"] == "cancelled":
            return
        if refunded >= int(payment["amount_cents"] or 0):
            connection.execute(
                "UPDATE package_purchases SET status = 'cancelled', updated_at = ? WHERE id = ?",
                (now, purchase["id"]),
            )


def _send_shop_confirmation_email(cliente_id: str, payment_id: str) -> bool:
    """Email de confirmacion al comprador tras materializarse una compra de la tienda
    (bono o productos). Best-effort: nunca rompe el webhook."""
    from backend import appstate, emailing  # tardio

    with db._get_db_connection() as connection:
        payment = connection.execute(
            "SELECT * FROM customer_payments WHERE id=? AND cliente_id=?", (payment_id, cliente_id)
        ).fetchone()
    if not payment:
        return False
    try:
        meta = json.loads(payment["line_items_json"] or "{}")
    except (ValueError, TypeError):
        meta = {}
    buyer_email = str(meta.get("buyer_email") or "").strip()
    if not buyer_email:
        return False
    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    business = str(config.get("empresa") or config.get("nombre") or "el negocio")
    contacto = config.get("contacto") or {}
    contact_line = " · ".join(
        x for x in (
            textnorm._sanitize_text(str(contacto.get("telefono") or "")),
            textnorm._sanitize_text(str(contacto.get("direccion") or "")),
        ) if x
    )
    buyer_name = str(meta.get("buyer_name") or "")
    amount_label = f"{int(payment['amount_cents'] or 0) / 100:.2f} EUR".replace(".", ",")
    kind = payment["kind"] if "kind" in payment.keys() else ""
    if kind == "shop_package":
        # El bono ya se materializo en el webhook: el email sale de la compra real
        # (incluye el enlace a la wallet publica), igual que la venta de mostrador.
        with db._get_db_connection() as connection:
            purchase = connection.execute(
                "SELECT id FROM package_purchases WHERE customer_payment_id = ? AND cliente_id = ? LIMIT 1",
                (payment_id, cliente_id),
            ).fetchone()
        if not purchase:
            return False
        return _send_package_purchase_email(cliente_id, purchase["id"])
    if kind == "shop_products":
        pickup = _shop_public_config(cliente_id)["pickup_note"] or "Puedes recoger tu pedido en el centro."
        subject = f"Hemos recibido tu pedido - {business}"
        prod_lines = [
            f"{int(l.get('qty') or 1)}x {l.get('name') or ''}"
            for l in (meta.get("lines") or []) if l.get("type") == "product"
        ]
        lines_txt = "\n".join(f"- {s}" for s in prod_lines)
        text = (
            f"Hola {buyer_name},\n\n"
            f"Tu pedido en {business} esta confirmado ({amount_label}).\n\n"
            f"{lines_txt}\n\n{pickup}\n"
            + (f"\n{contact_line}\n" if contact_line else "")
        )
        html_lines = "".join(f"<li>{s}</li>" for s in prod_lines)
        html = (
            f'<div style="max-width:520px;margin:0 auto;font-family:Arial,sans-serif;color:#1f2937">'
            f"<h2>Pedido confirmado</h2>"
            f"<p>Hola {buyer_name}, gracias por tu compra en <b>{business}</b> ({amount_label}).</p>"
            f"<ul>{html_lines}</ul><p>{pickup}</p>"
            + (f'<p style="color:#6b7280;font-size:13px">{contact_line}</p>' if contact_line else "")
            + "</div>"
        )
    else:
        return False
    try:
        emailing._send_client_email(cliente_id, buyer_email, subject, text, html)
        return True
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Email de confirmacion de tienda %s fallo: %s", payment_id, exc)
        return False


_SHOP_PAGE_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Tienda online · __BUSINESS__</title>
<style>
  :root {
    --acc: __COLOR__;
    --acc-rgb: 109,40,217;
    --bg: #faf8f5;
    --ink: #23201d;
    --muted: #8b857e;
    --line: rgba(35,32,29,.09);
    --card: #ffffff;
    --shadow: 0 1px 2px rgba(35,32,29,.04), 0 8px 24px rgba(35,32,29,.06);
    --radius: 18px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--ink); line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }
  .serif { font-family: "Georgia", "Times New Roman", serif; }
  .wrap { max-width: 900px; margin: 0 auto; padding: 0 18px 80px; }
  a { color: var(--acc); }

  /* Hero */
  .hero {
    position: relative; margin: 18px 0 22px; border-radius: 22px; overflow: hidden;
    background: linear-gradient(135deg, var(--acc) 0%, #16131d 130%);
    color: #fff; padding: 40px 26px 34px; text-align: center;
    box-shadow: var(--shadow);
  }
  .hero::after {
    content: ""; position: absolute; inset: 0; pointer-events: none;
    background: radial-gradient(120% 90% at 80% -10%, rgba(255,255,255,.22), transparent 60%);
  }
  .hero .eyebrow { font-size: .72rem; letter-spacing: .22em; text-transform: uppercase; opacity: .82; margin-bottom: 10px; }
  .hero .biz { font-size: clamp(1.7rem, 4.5vw, 2.5rem); font-weight: 700; line-height: 1.12; }
  .hero .intro { margin: 12px auto 0; max-width: 540px; font-size: .98rem; opacity: .92; }
  .trust { display: flex; flex-wrap: wrap; gap: 8px 16px; justify-content: center; margin-top: 20px; position: relative; z-index: 1; }
  .trust span { display: inline-flex; align-items: center; gap: 6px; font-size: .8rem; opacity: .92; }
  .trust svg { width: 15px; height: 15px; }
  .owned-cta { margin: 0 0 18px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 14px; background: #fff; box-shadow: var(--shadow); display: flex; align-items: center; justify-content: space-between; gap: 14px; }
  .owned-cta b { display: block; font-size: .92rem; }
  .owned-cta span { color: var(--muted); font-size: .82rem; }
  .owned-cta a { flex: none; text-decoration: none; border-radius: 10px; padding: 10px 14px; background: var(--acc); color: #fff; font-size: .86rem; font-weight: 700; }

  /* Banner (ok / cancel) */
  .banner { border-radius: 12px; padding: 13px 16px; margin: 0 0 18px; font-size: .92rem; display: none; align-items: center; gap: 10px; }
  .banner.ok { background: #e7f6ec; color: #17663b; display: flex; }
  .banner.ko { background: #fdecec; color: #9a2b2b; display: flex; }

  /* Tabs */
  .tabs { display: inline-flex; gap: 4px; padding: 5px; background: #fff; border: 1px solid var(--line);
          border-radius: 999px; box-shadow: var(--shadow); margin: 0 auto 24px; }
  .tabs-wrap { display: flex; justify-content: center; }
  .tabs button { border: 0; background: transparent; border-radius: 999px; padding: 9px 22px;
                 font-size: .92rem; cursor: pointer; font-weight: 600; color: var(--muted); transition: .18s; }
  .tabs button.on { background: var(--acc); color: #fff; box-shadow: 0 4px 12px rgba(var(--acc-rgb),.32); }

  .sec-head { display: flex; align-items: baseline; justify-content: space-between; margin: 4px 2px 14px; gap: 12px; }
  .sec-head h2 { font-size: 1.15rem; font-weight: 600; }
  .sec-head .count { font-size: .82rem; color: var(--muted); }

  /* Grid + cards */
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 16px; }
  .card {
    background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
    padding: 20px; display: flex; flex-direction: column; gap: 12px; box-shadow: var(--shadow);
    transition: transform .18s ease, box-shadow .18s ease, border-color .18s; position: relative;
  }
  .card:hover { transform: translateY(-3px); box-shadow: 0 2px 4px rgba(35,32,29,.05), 0 16px 34px rgba(35,32,29,.10); }
  .card.picked { border-color: var(--acc); box-shadow: 0 0 0 2px rgba(var(--acc-rgb),.28), var(--shadow); }
  .card-media { margin: -20px -20px 2px; height: 152px; border-radius: 17px 17px 0 0; overflow: hidden; background: #f4f1ec; }
  .card-media img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform .5s ease; }
  .card:hover .card-media img { transform: scale(1.05); }
  .card-top { display: flex; align-items: flex-start; gap: 12px; }
  .ic { flex: 0 0 auto; width: 42px; height: 42px; border-radius: 12px; display: grid; place-items: center;
        background: rgba(var(--acc-rgb),.10); color: var(--acc); }
  .ic svg { width: 22px; height: 22px; }
  .card h3 { font-size: 1.04rem; font-weight: 650; line-height: 1.25; }
  .badge { display: inline-block; font-size: .64rem; letter-spacing: .12em; text-transform: uppercase;
           font-weight: 700; color: var(--acc); background: rgba(var(--acc-rgb),.10);
           padding: 3px 8px; border-radius: 6px; margin-bottom: 4px; }
  .desc { color: var(--muted); font-size: .87rem; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { font-size: .76rem; color: var(--ink); background: #f4f1ec; border-radius: 7px; padding: 4px 9px; }
  .meta { color: var(--muted); font-size: .8rem; display: flex; align-items: center; gap: 6px; }
  .spacer { flex: 1; }
  .price-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-top: 2px; }
  .price { font-weight: 750; font-size: 1.28rem; letter-spacing: -.01em; }
  .per { font-size: .76rem; color: var(--muted); }
  .stock { font-size: .74rem; font-weight: 600; color: #2f9e56; }
  .stock.low { color: #c07a12; }
  .stock.out { color: #b23b3b; }

  .btn { border: 0; border-radius: 11px; padding: 11px 16px; font-size: .92rem; font-weight: 700;
         cursor: pointer; transition: filter .15s, transform .05s; font-family: inherit; }
  .btn:active { transform: translateY(1px); }
  .btn-acc { background: var(--acc); color: #fff; }
  .btn-acc:hover { filter: brightness(.94); }
  .btn-acc:disabled { opacity: .6; cursor: default; }
  .btn-ghost { background: #fff; border: 1px solid var(--line); color: var(--ink); }
  .btn-full { width: 100%; }

  /* Stepper */
  .stepper { display: inline-flex; align-items: center; gap: 0; border: 1px solid var(--line); border-radius: 11px; overflow: hidden; }
  .stepper button { width: 40px; height: 40px; border: 0; background: #fff; font-size: 1.15rem; cursor: pointer; color: var(--ink); }
  .stepper button:hover { background: #f4f1ec; }
  .stepper button:disabled { opacity: .35; cursor: default; }
  .stepper .q { min-width: 40px; text-align: center; font-weight: 700; font-variant-numeric: tabular-nums; }
  .card-actions { display: flex; align-items: center; justify-content: space-between; gap: 10px; }

  /* Cart bar */
  .cartbar {
    position: sticky; bottom: 16px; margin-top: 22px; z-index: 20;
    background: #1c1a17; color: #fff; border-radius: 16px; padding: 14px 16px 14px 20px;
    display: none; align-items: center; justify-content: space-between; gap: 14px;
    box-shadow: 0 12px 30px rgba(0,0,0,.22);
  }
  .cartbar.show { display: flex; }
  .cartbar .c-info { display: flex; flex-direction: column; }
  .cartbar .c-count { font-size: .78rem; opacity: .7; }
  .cartbar .c-total { font-size: 1.15rem; font-weight: 750; }

  /* Checkout modal */
  .overlay { position: fixed; inset: 0; background: rgba(20,17,24,.55); backdrop-filter: blur(3px);
             display: none; align-items: flex-end; justify-content: center; z-index: 60; padding: 0; }
  .overlay.show { display: flex; }
  .modal { background: #fff; width: 100%; max-width: 460px; border-radius: 22px 22px 0 0;
           padding: 22px 22px 26px; box-shadow: 0 -10px 40px rgba(0,0,0,.2); animation: rise .22s ease; }
  @keyframes rise { from { transform: translateY(28px); opacity: .6; } to { transform: none; opacity: 1; } }
  .modal-head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 14px; }
  .modal-head h3 { font-size: 1.18rem; font-weight: 650; }
  .modal-close { border: 0; background: #f4f1ec; width: 34px; height: 34px; border-radius: 50%;
                 font-size: 1.1rem; cursor: pointer; color: var(--muted); flex: 0 0 auto; }
  .summary { background: #faf8f5; border: 1px solid var(--line); border-radius: 13px; padding: 13px 15px; margin-bottom: 16px; }
  .summary .line { display: flex; justify-content: space-between; gap: 12px; font-size: .9rem; padding: 3px 0; }
  .summary .tot { border-top: 1px dashed var(--line); margin-top: 7px; padding-top: 9px; font-weight: 750; font-size: 1rem; }
  .field { margin-bottom: 12px; }
  .field label { display: block; font-size: .8rem; color: var(--muted); margin-bottom: 5px; font-weight: 600; }
  .field input { width: 100%; border: 1px solid var(--line); border-radius: 11px; padding: 12px 13px; font-size: .96rem;
                 font-family: inherit; color: var(--ink); background: #fff; transition: border-color .15s, box-shadow .15s; }
  .field input:focus { outline: 0; border-color: var(--acc); box-shadow: 0 0 0 3px rgba(var(--acc-rgb),.14); }
  .err { color: #b23b3b; font-size: .86rem; margin: 4px 0 12px; display: none; }
  .pickup { color: var(--muted); font-size: .82rem; margin-top: 12px; text-align: center; }
  .use-copy { color: var(--muted); font-size: .82rem; text-align: center; margin: -2px 0 12px; line-height: 1.45; }
  .secure { display: flex; align-items: center; justify-content: center; gap: 7px; color: var(--muted); font-size: .78rem; margin-top: 12px; }
  .secure svg { width: 14px; height: 14px; }

  .empty { text-align: center; color: var(--muted); padding: 40px 0; }

  footer { text-align: center; color: var(--muted); font-size: .82rem; margin-top: 40px; line-height: 1.7; }
  footer a { font-weight: 600; }

  @media (max-width: 520px) {
    .wrap { padding: 0 12px 90px; }
    .hero { padding: 32px 18px 28px; border-radius: 18px; }
    .grid { grid-template-columns: 1fr; }
    .modal { max-width: 100%; }
    .owned-cta { align-items: stretch; flex-direction: column; }
    .owned-cta a { text-align: center; }
  }
</style>
</head>
<body>
<div class="wrap">

  <div class="hero">
    <div class="eyebrow">Tienda online</div>
    <div class="biz serif">__BUSINESS__</div>
    <div class="intro">__INTRO__</div>
    <div class="trust">
      <span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg> Pago seguro con tarjeta</span>
      <span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg> Confirmación por email</span>
      <span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 12l2 2 4-5"/><circle cx="12" cy="12" r="9"/></svg> Canje online o en recepción</span>
    </div>
  </div>

  <div class="banner" id="banner"><span id="bannerTxt"></span></div>

  <div class="tabs-wrap"__TABS_WRAP_STYLE__>
    <div class="tabs" id="tabs">
      <button type="button" data-tab="bonos" id="tabBonos" __SHOW_BONOS__>Bonos</button>
      <button type="button" data-tab="productos" id="tabProductos" __SHOW_PRODUCTOS__>Productos</button>
    </div>
  </div>

  <section id="secBonos" style="display:none">
    <div class="sec-head"><h2 class="serif">Bonos de sesiones</h2><span class="count" id="bonosCount"></span></div>
    __BONUS_BOOK_CTA__
    <div class="grid" id="gridBonos"></div>
  </section>

  <section id="secProductos" style="display:none">
    <div class="sec-head"><h2 class="serif">Productos</h2><span class="count" id="prodsCount"></span></div>
    <div class="grid" id="gridProductos"></div>
    <div class="cartbar" id="cartBar">
      <div class="c-info"><span class="c-count" id="cartCount"></span><span class="c-total" id="cartTotal"></span></div>
      <button type="button" class="btn btn-acc" id="cartGo">Continuar &rarr;</button>
    </div>
  </section>

  <footer>
    <div>__CONTACT__</div>
    __GIFT_LINK__
    <div style="margin-top:8px; opacity:.85">Pago seguro con tarjeta. Al pagar aceptas las condiciones del negocio.</div>
  </footer>
</div>

<div class="overlay" id="coOverlay">
  <div class="modal" role="dialog" aria-modal="true">
    <div class="modal-head">
      <h3 class="serif" id="coTitle">Completa tu compra</h3>
      <button type="button" class="modal-close" id="coClose" aria-label="Cerrar">&times;</button>
    </div>
    <div class="summary" id="coSummary"></div>
    <div class="use-copy" id="coUseCopy"></div>
    <div class="field"><label>Tu nombre</label><input id="bn" maxlength="120" autocomplete="name" placeholder="Nombre y apellidos"></div>
    <div class="field"><label>Tu email</label><input id="be" type="email" maxlength="160" autocomplete="email" placeholder="tucorreo@email.com"></div>
    <div class="field"><label>Teléfono (opcional)</label><input id="bp" maxlength="40" autocomplete="tel" placeholder="Para avisarte si hace falta"></div>
    <div class="err" id="coErr"></div>
    <button type="button" class="btn btn-acc btn-full" id="payBtn">Pagar de forma segura</button>
    <div class="pickup" id="coPickup"></div>
    <div class="secure"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg> Pago cifrado procesado por Stripe</div>
  </div>
</div>

<script>
(function () {
  var PKGS = __PKGS_JSON__;
  var PRODS = __PRODS_JSON__;
  var PICKUP = __PICKUP_JSON__;

  // Deriva el RGB del acento para tintes (rgba) sin depender de color-mix.
  (function () {
    var hex = (getComputedStyle(document.documentElement).getPropertyValue("--acc") || "").trim();
    var m = /^#?([0-9a-f]{6})$/i.exec(hex);
    if (m) {
      var n = parseInt(m[1], 16);
      document.documentElement.style.setProperty("--acc-rgb", [(n>>16)&255, (n>>8)&255, n&255].join(","));
    }
  })();

  var qs = new URLSearchParams(location.search);
  var banner = document.getElementById("banner");
  var bannerTxt = document.getElementById("bannerTxt");
  var esc = function (s) { var d = document.createElement("div"); d.textContent = String(s == null ? "" : s); return d.innerHTML; };
  function showBanner(kind, html) { banner.className = "banner " + kind; bannerTxt.innerHTML = html; }
  function pollCheckoutStatus(sessionId) {
    var attempts = 0;
    function check() {
      fetch(location.pathname + "/checkout-status?session_id=" + encodeURIComponent(sessionId))
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok) throw new Error((res.d && res.d.detail) || "No se pudo comprobar el pago.");
          var d = res.d;
          if (d.status !== "paid" || !d.ready) {
            showBanner("ok", "✓ Pago completado. Estamos activando tu compra; la confirmacion llegara por email.");
            if (attempts++ < 8) setTimeout(check, 1500);
            return;
          }
          if (d.kind === "shop_package") {
            showBanner("ok", "✓ Tu bono esta activo. Te hemos enviado el enlace por email para ver sesiones restantes. <a href=\"" + esc(d.wallet_url) + "\" target=\"_blank\" rel=\"noopener\">Ver mi bono</a>");
          } else if (d.kind === "shop_products") {
            showBanner("ok", "✓ Pedido confirmado. Te hemos enviado la confirmacion por email con las instrucciones de recogida.");
          }
        })
        .catch(function () {
          showBanner("ok", "✓ Pago completado. Revisa tu email: te hemos enviado la confirmacion.");
        });
    }
    check();
  }
  if (qs.get("ok")) {
    showBanner("ok", "✓ Pago completado. Revisa tu email: te hemos enviado la confirmacion.");
    if (qs.get("session_id")) pollCheckoutStatus(qs.get("session_id"));
  }
  if (qs.get("cancel")) { showBanner("ko", "Pago cancelado. Puedes intentarlo de nuevo cuando quieras."); }

  var eur = function (c) { return (c / 100).toFixed(2).replace(".", ",") + " €"; };
  var sessionsOf = function (items) {
    var t = 0; (items || []).forEach(function (s) { var n = parseInt(String(s), 10); if (!isNaN(n)) t += n; });
    return t;
  };

  var IC_TICKET = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 8a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4V8Z"/><path d="M13 6v12" stroke-dasharray="2 2"/></svg>';
  var IC_BAG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3s6 6.4 6 11a6 6 0 0 1-12 0c0-4.6 6-11 6-11Z"/></svg>';

  var state = { tab: "", pkg: null, cart: {} };

  function setTab(name) {
    state.tab = name;
    document.getElementById("secBonos").style.display = name === "bonos" ? "" : "none";
    document.getElementById("secProductos").style.display = name === "productos" ? "" : "none";
    var tabs = document.querySelectorAll("#tabs button");
    for (var i = 0; i < tabs.length; i++) tabs[i].className = tabs[i].dataset.tab === name ? "on" : "";
  }
  document.getElementById("tabs").addEventListener("click", function (e) {
    var b = e.target.closest("button"); if (b) setTab(b.dataset.tab);
  });

  // --- Bonos ---
  var gb = document.getElementById("gridBonos");
  document.getElementById("bonosCount").textContent = PKGS.length ? PKGS.length + (PKGS.length === 1 ? " bono" : " bonos") : "";
  if (!PKGS.length) gb.innerHTML = '<div class="empty">Aún no hay bonos disponibles.</div>';
  PKGS.forEach(function (p, idx) {
    var sess = sessionsOf(p.items);
    var chips = (p.items || []).map(function (s) { return '<span class="chip">' + esc(s) + "</span>"; }).join("");
    var per = sess > 0 ? '<span class="per">' + eur(Math.round(p.price_cents / sess)) + " / sesión</span>" : "";
    var card = document.createElement("div"); card.className = "card";
    card.innerHTML =
      (p.image_url ? '<div class="card-media"><img src="' + esc(p.image_url) + '" alt="" loading="lazy"></div>' : "")
      + '<div class="card-top"><div class="ic">' + IC_TICKET + '</div>'
        + '<div><span class="badge">Bono</span><h3>' + esc(p.name) + "</h3></div></div>"
      + (p.description ? '<div class="desc">' + esc(p.description) + "</div>" : "")
      + (chips ? '<div class="chips">' + chips + "</div>" : "")
      + '<div class="meta">' + (sess > 0 ? sess + (sess === 1 ? " sesión" : " sesiones") + " · " : "") + "válido " + p.validity_days + " días</div>"
      + '<div class="spacer"></div>'
      + '<div class="price-row"><span class="price">' + eur(p.price_cents) + "</span>" + per + "</div>"
      + '<button type="button" class="btn btn-acc btn-full">Comprar bono</button>';
    card.querySelector("button").addEventListener("click", function () { openPkg(idx); });
    gb.appendChild(card);
  });

  // --- Productos ---
  var gp = document.getElementById("gridProductos");
  document.getElementById("prodsCount").textContent = PRODS.length ? PRODS.length + (PRODS.length === 1 ? " producto" : " productos") : "";
  if (!PRODS.length) gp.innerHTML = '<div class="empty">Aún no hay productos disponibles.</div>';
  PRODS.forEach(function (p) {
    var hasStock = p.stock !== null && p.stock !== undefined;
    var stockHtml = "";
    if (hasStock) {
      var cls = p.stock <= 0 ? "stock out" : (p.stock <= 5 ? "stock low" : "stock");
      var txt = p.stock <= 0 ? "Agotado" : (p.stock <= 5 ? "Últimas " + p.stock + " unidades" : "En stock");
      stockHtml = '<span class="' + cls + '">' + txt + "</span>";
    }
    var card = document.createElement("div"); card.className = "card"; card.dataset.pid = p.id;
    card.innerHTML =
      (p.image_url ? '<div class="card-media"><img src="' + esc(p.image_url) + '" alt="" loading="lazy"></div>' : "")
      + '<div class="card-top"><div class="ic">' + IC_BAG + "</div>"
        + "<div><h3>" + esc(p.name) + "</h3>" + (stockHtml ? '<div class="meta" style="margin-top:4px">' + stockHtml + "</div>" : "") + "</div></div>"
      + (p.description ? '<div class="desc">' + esc(p.description) + "</div>" : "")
      + '<div class="spacer"></div>'
      + '<div class="card-actions"><span class="price">' + eur(p.price_cents) + "</span>"
      + '<div class="stepper"><button type="button" data-d="-1" aria-label="Quitar">−</button><span class="q" data-q>0</span><button type="button" data-d="1" aria-label="Añadir">+</button></div></div>';
    var span = card.querySelector("[data-q]");
    var minus = card.querySelector('[data-d="-1"]');
    var plus = card.querySelector('[data-d="1"]');
    if (hasStock && p.stock <= 0) { minus.disabled = true; plus.disabled = true; }
    card.querySelector(".stepper").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b || b.disabled) return;
      var q = (state.cart[p.id] || 0) + parseInt(b.dataset.d, 10);
      var max = hasStock ? p.stock : 999;
      q = Math.max(0, Math.min(q, max));
      if (q > 0) state.cart[p.id] = q; else delete state.cart[p.id];
      span.textContent = q;
      card.className = q > 0 ? "card picked" : "card";
      paintCart();
    });
    gp.appendChild(card);
  });

  function cartLines() {
    return Object.keys(state.cart).map(function (id) {
      var p = null;
      for (var i = 0; i < PRODS.length; i++) if (PRODS[i].id === id) p = PRODS[i];
      return { p: p, qty: state.cart[id] };
    }).filter(function (x) { return x.p; });
  }
  function cartTotal() { return cartLines().reduce(function (t, x) { return t + x.p.price_cents * x.qty; }, 0); }
  function paintCart() {
    var n = cartLines().reduce(function (t, x) { return t + x.qty; }, 0);
    document.getElementById("cartBar").className = n > 0 ? "cartbar show" : "cartbar";
    document.getElementById("cartCount").textContent = n + (n === 1 ? " artículo en tu carrito" : " artículos en tu carrito");
    document.getElementById("cartTotal").textContent = eur(cartTotal());
  }
  document.getElementById("cartGo").addEventListener("click", openCart);

  // --- Checkout modal ---
  var overlay = document.getElementById("coOverlay");
  function openModal() { overlay.className = "overlay show"; setTimeout(function () { document.getElementById("bn").focus(); }, 60); }
  function closeModal() { overlay.className = "overlay"; document.getElementById("coErr").style.display = "none"; }
  document.getElementById("coClose").addEventListener("click", closeModal);
  overlay.addEventListener("click", function (e) { if (e.target === overlay) closeModal(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeModal(); });

  function openPkg(idx) {
    state.pkg = PKGS[idx];
    var sess = sessionsOf(state.pkg.items);
    var rows = '<div class="line"><span>' + esc(state.pkg.name) + "</span><span>" + eur(state.pkg.price_cents) + "</span></div>"
      + (sess > 0 ? '<div class="line" style="color:var(--muted)"><span>' + sess + " sesiones · válido " + state.pkg.validity_days + ' días</span><span></span></div>' : "")
      + '<div class="line tot"><span>Total</span><span>' + eur(state.pkg.price_cents) + "</span></div>";
    document.getElementById("coTitle").textContent = "Comprar bono";
    document.getElementById("coSummary").innerHTML = rows;
    document.getElementById("coUseCopy").textContent = "Recibiras un email con tu bono y un enlace privado para consultar sesiones restantes.";
    document.getElementById("coPickup").textContent = "Al reservar con este email o telefono, descontaremos la sesion automaticamente si el servicio esta incluido.";
    openModal();
  }
  function openCart() {
    state.pkg = null;
    var lines = cartLines();
    if (!lines.length) return;
    var rows = lines.map(function (x) {
      return '<div class="line"><span>' + x.qty + "× " + esc(x.p.name) + "</span><span>" + eur(x.p.price_cents * x.qty) + "</span></div>";
    }).join("") + '<div class="line tot"><span>Total</span><span>' + eur(cartTotal()) + "</span></div>";
    document.getElementById("coTitle").textContent = "Finalizar pedido";
    document.getElementById("coSummary").innerHTML = rows;
    document.getElementById("coUseCopy").textContent = "Recibiras la confirmacion por email nada mas completarse el pago.";
    document.getElementById("coPickup").textContent = PICKUP || "Recogida en el centro.";
    openModal();
  }

  document.getElementById("payBtn").addEventListener("click", function () {
    var btn = this;
    var err = document.getElementById("coErr");
    var name = document.getElementById("bn").value.trim();
    var email = document.getElementById("be").value.trim();
    var phone = document.getElementById("bp").value.trim();
    if (name.length < 2 || email.indexOf("@") < 1) {
      err.textContent = "Completa tu nombre y un email válido."; err.style.display = "block"; return;
    }
    var url, body;
    if (state.pkg) {
      url = location.pathname + "/checkout/bono";
      body = { package_id: state.pkg.id, buyer_name: name, buyer_email: email, buyer_phone: phone };
    } else {
      var items = cartLines().map(function (x) { return { product_id: x.p.id, qty: x.qty }; });
      if (!items.length) { err.textContent = "Añade al menos un producto."; err.style.display = "block"; return; }
      url = location.pathname + "/checkout/productos";
      body = { items: items, buyer_name: name, buyer_email: email, buyer_phone: phone };
    }
    err.style.display = "none";
    btn.disabled = true; btn.textContent = "Preparando el pago…";
    var fail = function (msg) {
      err.textContent = msg || "No se pudo iniciar el pago. Inténtalo de nuevo.";
      err.style.display = "block"; btn.disabled = false; btn.textContent = "Pagar de forma segura";
    };
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok && res.d.url) { location.href = res.d.url; return; }
        fail(res.d && res.d.detail);
      })
      .catch(function () { fail(); });
  });

  var first = (document.getElementById("tabBonos").style.display !== "none" && PKGS.length) ? "bonos" : "productos";
  setTab(first);
})();
</script>
</body>
</html>"""


def shop_public_page_html(cliente_id: str, section: str = "") -> str:
    """Pagina publica de la tienda (bonos + productos) con el branding del tenant.
    Server-rendered y sin dependencias externas (CSP-friendly), como /gift.
    `section` ('bonos'|'productos') genera una pagina dedicada a un solo canal
    (enlace separado): oculta la barra de pestanas y solo pinta esa seccion."""
    import html as html_mod

    from backend import appstate  # tardio

    section = (section or "").strip().lower()
    if section not in ("bonos", "productos"):
        section = ""
    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    cfg = _shop_public_config(cliente_id)
    availability = shop_public_available(cliente_id)
    business = html_mod.escape(str(config.get("empresa") or config.get("nombre") or "Nuestro negocio"))
    color = str((config.get("branding") or {}).get("color") or config.get("color") or "#6d28d9")
    if not _GIFT_ACCENT_RE.match(color):
        color = "#6d28d9"
    if cfg.get("accent_color"):  # override configurable desde el panel (pestana Ventas)
        color = cfg["accent_color"]
    contacto = config.get("contacto") or {}
    contact_bits = " &middot; ".join(
        html_mod.escape(x) for x in (
            textnorm._sanitize_text(str(contacto.get("telefono") or "")),
            textnorm._sanitize_text(str(contacto.get("direccion") or "")),
        ) if x
    )
    intro = html_mod.escape(cfg["intro_text"] or "Compra online: pagas ahora y lo disfrutas cuando quieras.")

    packages = []
    if availability["packages"] and section in ("", "bonos"):
        for p in _list_packages(cliente_id, include_inactive=False):
            if int(p["price_cents"] or 0) < 50:
                continue
            packages.append({
                "id": p["id"], "name": p["name"], "description": p["description"],
                "price_cents": int(p["price_cents"]), "validity_days": int(p["validity_days"] or 365),
                "items": _package_items_summary(cliente_id, p["items"]),
            })
    products = []
    if availability["products"] and section in ("", "productos"):
        for p in _list_products(cliente_id, include_inactive=False):
            if int(p["price_cents"] or 0) < 1:
                continue
            if p["stock"] is not None and int(p["stock"]) <= 0:
                continue
            products.append({
                "id": p["id"], "name": p["name"], "description": p["description"],
                "price_cents": int(p["price_cents"]), "stock": p["stock"],
            })

    def _js_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")

    gift_link = ""
    if gift_public_available(cliente_id):
        gift_link = f'<div style="margin-top:6px"><a href="/gift/{cliente_id}">&iexcl;Tambien puedes regalar una tarjeta!</a></div>'
    booking_url = _booking_page_url(cliente_id)
    bonus_book_cta = ""
    if booking_url:
        bonus_book_cta = (
            '<div class="owned-cta"><div><b>&iquest;Ya tienes un bono?</b>'
            '<span>Reserva con el mismo email o telefono y descontaremos una sesion si el servicio esta incluido.</span>'
            f'</div><a href="{html_mod.escape(booking_url)}">Reservar cita</a></div>'
        )

    page = _SHOP_PAGE_TEMPLATE
    for token, value in (
        ("__BUSINESS__", business),
        ("__COLOR__", color),
        ("__INTRO__", intro),
        ("__CONTACT__", contact_bits),
        ("__GIFT_LINK__", gift_link),
        ("__BONUS_BOOK_CTA__", bonus_book_cta),
        ("__SHOW_BONOS__", "" if packages else 'style="display:none"'),
        ("__SHOW_PRODUCTOS__", "" if products else 'style="display:none"'),
        ("__TABS_WRAP_STYLE__", ' style="display:none"' if section else ""),
        ("__PKGS_JSON__", _js_json(packages)),
        ("__PRODS_JSON__", _js_json(products)),
        ("__PICKUP_JSON__", _js_json(cfg["pickup_note"])),
    ):
        page = page.replace(token, value)
    return page


_CENTRAL_PAGE_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="theme-color" content="__COLOR__">
<title>Central de reservas &middot; __BUSINESS__</title>
<style>
  * { box-sizing: border-box; margin: 0; }
  :root {
    color-scheme: light;
    --accent: __COLOR__;
    --accent-ink: #ffffff;
    --ink: #0f172a; --muted: #64748b; --line: #e2e8f0;
    --panel: #ffffff; --bg: #f6f8fb;
    --ok: #059669; --ok-soft: #ecfdf5; --ok-line: #a7f3d0;
    --r: 18px;
    --shadow: 0 24px 70px -22px color-mix(in srgb, var(--accent) 34%, rgba(15,23,42,.36));
  }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; color: var(--ink); background: var(--bg); -webkit-font-smoothing: antialiased; }
  button { font: inherit; }

  /* ── Hero ─────────────────────────────────────────────── */
  .hero { position: relative; overflow: hidden; min-height: 320px; padding: 40px 18px 130px; color: #fff; display: flex; align-items: flex-end; __HERO_BG__ }
  .hero.hero-anim { background-size: 220% 220%; animation: heroShift 16s ease-in-out infinite; }
  @keyframes heroShift { 0%,100% { background-position: 0% 30%; } 50% { background-position: 100% 70%; } }
  .orb { position: absolute; border-radius: 50%; filter: blur(70px); opacity: .5; pointer-events: none; }
  .orb-a { width: 380px; height: 380px; right: -90px; top: -140px; background: color-mix(in srgb, var(--accent) 55%, #ffffff); animation: drift 13s ease-in-out infinite; }
  .orb-b { width: 300px; height: 300px; left: 6%; bottom: -170px; background: color-mix(in srgb, var(--accent) 35%, #7dd3fc); animation: drift 17s ease-in-out infinite reverse; }
  @keyframes drift { 0%,100% { transform: translate3d(0,0,0); } 50% { transform: translate3d(-26px,20px,0); } }
  .hero-inner { position: relative; width: min(1140px, 100%); margin: 0 auto; }
  .hero-top { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  .monogram { width: 52px; height: 52px; border-radius: 16px; display: flex; align-items: center; justify-content: center; font-size: 24px; font-weight: 900; background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28); backdrop-filter: blur(8px); box-shadow: 0 10px 26px rgba(0,0,0,.18); }
  .eyebrow { display: inline-flex; gap: 8px; align-items: center; padding: 8px 13px; border-radius: 999px; background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.22); backdrop-filter: blur(8px); font-size: 12px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
  .eyebrow span { width: 8px; height: 8px; border-radius: 50%; background: #34d399; box-shadow: 0 0 0 4px rgba(52,211,153,.22); animation: pulseDot 2.4s ease infinite; }
  @keyframes pulseDot { 50% { box-shadow: 0 0 0 7px rgba(52,211,153,.08); } }
  h1 { margin: 18px 0 0; font-size: clamp(34px, 5vw, 60px); line-height: 1.03; letter-spacing: -.02em; font-weight: 900; max-width: 820px; text-shadow: 0 2px 24px rgba(2,8,20,.25); }
  .lead { max-width: 640px; margin: 12px 0 0; font-size: 17px; line-height: 1.55; color: rgba(255,255,255,.88); }
  .trust { display: flex; gap: 9px; flex-wrap: wrap; margin-top: 18px; }
  .trust-chip { font-size: 12.5px; font-weight: 700; padding: 7px 12px; border-radius: 999px; background: rgba(255,255,255,.13); border: 1px solid rgba(255,255,255,.2); backdrop-filter: blur(8px); }

  /* ── Layout ───────────────────────────────────────────── */
  .wrap { position: relative; width: min(1180px, 100%); margin: -96px auto 48px; padding: 0 20px; display: grid; grid-template-columns: minmax(0, 1fr) 336px; gap: 26px; align-items: start; }
  .panel { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r); box-shadow: var(--shadow); overflow: hidden; animation: riseIn .5s cubic-bezier(.22,.9,.3,1) both; }
  @keyframes riseIn { from { opacity: 0; transform: translateY(16px); } }
  .panel-head { padding: 28px 30px 0; }
  .panel-title { font-size: 21px; font-weight: 850; letter-spacing: -.01em; }
  .panel-sub { color: var(--muted); font-size: 14px; line-height: 1.5; margin-top: 5px; }

  /* Progreso + pasos */
  .wiz-track { height: 4px; border-radius: 99px; background: color-mix(in srgb, var(--accent) 12%, #eef2f7); margin: 22px 30px 0; overflow: hidden; }
  .wiz-track > i { display: block; height: 100%; width: 25%; border-radius: 99px; background: linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--accent) 65%, #fff)); transition: width .4s cubic-bezier(.22,.9,.3,1); }
  .wizard-steps { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; padding: 16px 30px 20px; }
  .step { display: flex; align-items: center; justify-content: center; gap: 7px; border: 0; background: none; color: var(--muted); font-weight: 800; font-size: 12.5px; cursor: pointer; padding: 6px 4px; border-radius: 10px; transition: color .15s; }
  .step .n { width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 11.5px; font-weight: 900; background: #eef2f7; color: var(--muted); border: 1.5px solid var(--line); transition: all .2s; flex: none; }
  .step.on { color: var(--accent); }
  .step.on .n { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 16%, transparent); }
  .step.done { color: var(--ok); }
  .step.done .n { background: var(--ok-soft); border-color: var(--ok-line); color: var(--ok); }
  .step:hover { color: var(--ink); }

  .form { padding: 6px 30px 28px; display: grid; gap: 22px; }
  .step-panel { display: none; gap: 16px; }
  .step-panel.on { display: grid; gap: 20px; animation: fadeSlide .32s cubic-bezier(.22,.9,.3,1); }
  @keyframes fadeSlide { from { opacity: 0; transform: translateX(14px); } }
  .fld-label { font-size: 12px; font-weight: 850; letter-spacing: .07em; text-transform: uppercase; color: #475569; }

  /* Tarjetas de servicio */
  .choice-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(248px, 1fr)); gap: 14px; }
  .choice-card { position: relative; border: 1.5px solid var(--line); border-radius: 16px; background: #fff; padding: 0; display: grid; text-align: left; cursor: pointer; overflow: hidden; transition: transform .16s ease, border-color .16s ease, box-shadow .16s ease, background .16s ease; animation: cardIn .45s cubic-bezier(.22,.9,.3,1) backwards; }
  .choice-card:nth-child(2) { animation-delay: .05s; } .choice-card:nth-child(3) { animation-delay: .1s; }
  .choice-card:nth-child(4) { animation-delay: .15s; } .choice-card:nth-child(5) { animation-delay: .2s; }
  .choice-card:nth-child(6) { animation-delay: .25s; } .choice-card:nth-child(n+7) { animation-delay: .3s; }
  @keyframes cardIn { from { opacity: 0; transform: translateY(10px); } }
  .choice-media { height: 138px; background: linear-gradient(120deg, color-mix(in srgb, var(--accent) 14%, #f1f5f9), #f1f5f9); overflow: hidden; }
  .choice-media.ph { display: flex; align-items: center; justify-content: center; font-size: 38px; font-weight: 900; color: color-mix(in srgb, var(--accent) 45%, #cbd5e1); letter-spacing: .02em; }
  .choice-media img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform .55s cubic-bezier(.2,.8,.2,1); }
  .choice-card:hover .choice-media img { transform: scale(1.06); }
  .choice-body { padding: 15px 17px 16px; display: grid; gap: 9px; }
  .choice-card:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--accent) 55%, var(--line)); box-shadow: 0 14px 34px -14px color-mix(in srgb, var(--accent) 35%, rgba(15,23,42,.3)); }
  .choice-card.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 5%, #fff); box-shadow: 0 14px 34px -14px color-mix(in srgb, var(--accent) 45%, rgba(15,23,42,.3)); }
  .choice-card.on::after { content: "✓"; position: absolute; top: 9px; right: 9px; width: 26px; height: 26px; border-radius: 50%; background: var(--accent); color: var(--accent-ink); font-size: 14px; font-weight: 900; display: flex; align-items: center; justify-content: center; box-shadow: 0 6px 16px color-mix(in srgb, var(--accent) 45%, transparent); animation: popBadge .25s cubic-bezier(.3,1.6,.5,1); }
  @keyframes popBadge { from { transform: scale(.4); opacity: 0; } }
  .choice-row { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
  .choice-title { font-weight: 850; line-height: 1.25; letter-spacing: -.01em; }
  .choice-price { font-weight: 900; color: var(--accent); white-space: nowrap; }
  .choice-meta { color: var(--muted); font-size: 12.5px; display: flex; flex-wrap: wrap; gap: 6px; }
  .choice-meta span { border: 1px solid var(--line); border-radius: 999px; padding: 3px 9px; background: #f8fafc; }

  /* Tarjetas de centro / profesional */
  .pick-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(228px, 1fr)); gap: 12px; }
  .pick-card { position: relative; display: flex; align-items: center; gap: 12px; border: 1.5px solid var(--line); border-radius: 14px; background: #fff; padding: 13px 15px; cursor: pointer; text-align: left; transition: transform .16s ease, border-color .16s ease, box-shadow .16s ease; animation: cardIn .4s cubic-bezier(.22,.9,.3,1) backwards; }
  .pick-card:hover { transform: translateY(-1px); border-color: color-mix(in srgb, var(--accent) 55%, var(--line)); }
  .pick-card.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 5%, #fff); }
  .pick-card.on::after { content: "✓"; position: absolute; top: -8px; right: -8px; width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: var(--accent-ink); font-size: 12px; font-weight: 900; display: flex; align-items: center; justify-content: center; animation: popBadge .25s cubic-bezier(.3,1.6,.5,1); }
  .avatar { width: 38px; height: 38px; border-radius: 50%; flex: none; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 13px; font-weight: 900; letter-spacing: .02em; box-shadow: inset 0 -8px 14px rgba(0,0,0,.14); }
  .pick-txt { display: grid; gap: 2px; min-width: 0; text-align: left; }
  .pick-name { display: block; font-weight: 800; font-size: 14px; line-height: 1.2; }
  .pick-sub { display: block; color: var(--muted); font-size: 12px; }

  /* Selector de día */
  .date-strip { display: flex; gap: 8px; overflow-x: auto; padding: 2px 2px 8px; scrollbar-width: thin; }
  .day-chip { flex: none; min-width: 68px; display: grid; justify-items: center; gap: 1px; border: 1.5px solid var(--line); border-radius: 13px; background: #fff; padding: 9px 8px 7px; cursor: pointer; transition: all .15s ease; }
  .day-chip:hover { border-color: color-mix(in srgb, var(--accent) 55%, var(--line)); transform: translateY(-1px); }
  .day-chip .day-dow { font-size: 10.5px; font-weight: 800; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
  .day-chip .day-num { font-size: 19px; font-weight: 900; line-height: 1.1; }
  .day-chip .day-mon { font-size: 10.5px; color: var(--muted); }
  .day-chip.on { background: var(--accent); border-color: var(--accent); box-shadow: 0 10px 22px -8px color-mix(in srgb, var(--accent) 55%, transparent); }
  .day-chip.on .day-dow, .day-chip.on .day-num, .day-chip.on .day-mon { color: var(--accent-ink); }
  .date-other { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .chip-ghost { border: 1.5px dashed var(--line); background: #fff; color: var(--muted); border-radius: 11px; padding: 9px 13px; font-size: 13px; font-weight: 700; cursor: pointer; }
  .chip-ghost:hover { border-color: var(--accent); color: var(--accent); }
  .date-input { border: 1.5px solid var(--line); border-radius: 11px; padding: 9px 12px; font: inherit; font-size: 14px; color: var(--ink); background: #fff; }

  /* Huecos */
  .slots { display: grid; gap: 14px; min-height: 60px; }
  .slot-glabel { font-size: 11px; font-weight: 900; letter-spacing: .09em; text-transform: uppercase; color: var(--muted); margin-bottom: 7px; }
  .slot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(86px, 1fr)); gap: 9px; }
  .slot { border: 1.5px solid var(--line); background: #fff; border-radius: 12px; padding: 12px 8px; font-weight: 800; font-size: 14.5px; color: var(--ink); cursor: pointer; transition: all .14s ease; }
  .slot:hover { border-color: var(--accent); color: var(--accent); transform: translateY(-1px); }
  .slot.on { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); box-shadow: 0 10px 22px -8px color-mix(in srgb, var(--accent) 55%, transparent); }
  .empty { color: var(--muted); font-size: 14px; line-height: 1.5; padding: 14px 16px; border: 1.5px dashed var(--line); border-radius: 12px; background: #fbfcfe; }

  /* Formulario cliente */
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  label { display: block; font-size: 12px; font-weight: 800; color: #334155; margin: 0 0 6px; }
  input, textarea { width: 100%; border: 1.5px solid var(--line); border-radius: 12px; background: #fff; color: var(--ink); padding: 13px 14px; font: inherit; font-size: 15px; transition: border-color .15s, box-shadow .15s; }
  input:focus, textarea:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 15%, transparent); }
  textarea { min-height: 76px; resize: vertical; }
  .msum { display: none; }

  /* Navegación */
  .wizard-nav { display: flex; justify-content: space-between; gap: 10px; align-items: center; border-top: 1px solid var(--line); padding: 16px 0 14px; position: sticky; bottom: 0; background: #fff; z-index: 5; }
  .primary { border: 0; border-radius: 13px; background: var(--accent); color: var(--accent-ink); min-height: 50px; padding: 0 22px; font-weight: 850; font-size: 15px; cursor: pointer; display: inline-flex; justify-content: center; align-items: center; gap: 8px; text-decoration: none; transition: transform .15s ease, box-shadow .15s ease, filter .15s ease; box-shadow: 0 12px 26px -10px color-mix(in srgb, var(--accent) 60%, transparent); }
  .primary:hover { filter: brightness(1.06); transform: translateY(-1px); box-shadow: 0 16px 32px -10px color-mix(in srgb, var(--accent) 65%, transparent); }
  .primary:active { transform: translateY(0); }
  .primary[disabled] { opacity: .6; cursor: wait; transform: none; }
  .secondary { border: 1.5px solid var(--line); border-radius: 13px; background: #fff; color: var(--ink); min-height: 50px; padding: 0 18px; font-weight: 800; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 8px; text-decoration: none; transition: border-color .15s, color .15s; }
  .secondary:hover { border-color: var(--accent); color: var(--accent); }

  .status { display: none; border-radius: 12px; padding: 12px 15px; line-height: 1.45; font-size: 14px; }
  .status.ok { display: block; background: var(--ok-soft); color: #065f46; border: 1px solid var(--ok-line); }
  .status.err { display: block; background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; animation: shake .3s ease; }
  @keyframes shake { 25% { transform: translateX(-4px); } 75% { transform: translateX(4px); } }

  /* Skeletons */
  .skel { border-radius: 13px; background: linear-gradient(100deg, #eef2f7 40%, #f8fafc 50%, #eef2f7 60%); background-size: 200% 100%; animation: shimmer 1.2s linear infinite; }
  @keyframes shimmer { to { background-position: -200% 0; } }
  .skel-card { height: 92px; }
  .skel-row { height: 60px; }
  .skel-slot { height: 42px; border-radius: 11px; }

  /* Rail resumen */
  .side { display: grid; gap: 14px; position: sticky; top: 20px; }
  .rail { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r); overflow: hidden; box-shadow: var(--shadow); animation: riseIn .55s cubic-bezier(.22,.9,.3,1) .08s both; }
  .rail-head { padding: 15px 18px; background: linear-gradient(120deg, var(--accent), color-mix(in srgb, var(--accent) 62%, #0b1526)); color: var(--accent-ink); font-size: 12px; font-weight: 900; letter-spacing: .12em; text-transform: uppercase; display: flex; align-items: center; gap: 8px; }
  .rail-head::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: rgba(255,255,255,.85); box-shadow: 0 0 0 4px rgba(255,255,255,.2); }
  .rail-body { padding: 6px 18px 16px; }
  .rail-row { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding: 11px 0; border-bottom: 1px dashed var(--line); }
  .rail-row:last-of-type { border-bottom: 0; }
  .rail-k { color: var(--muted); font-size: 12.5px; font-weight: 700; flex: none; }
  .rail-v { font-size: 13.5px; font-weight: 800; text-align: right; overflow-wrap: anywhere; }
  .rail-v.pop { animation: valPop .3s cubic-bezier(.3,1.4,.5,1); }
  @keyframes valPop { from { transform: scale(.94); opacity: .4; } }
  .rail-total { display: flex; justify-content: space-between; align-items: center; margin-top: 6px; padding: 12px 14px; border-radius: 12px; background: color-mix(in srgb, var(--accent) 7%, #fff); border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--line)); }
  .rail-total span { font-size: 12.5px; font-weight: 800; color: var(--muted); }
  .rail-total b { font-size: 17px; font-weight: 900; color: var(--accent); }

  /* Canales */
  .channel { background: var(--panel); border: 1px solid var(--line); border-radius: 15px; padding: 15px 16px; text-decoration: none; color: var(--ink); display: grid; grid-template-columns: 44px minmax(0,1fr) auto; gap: 12px; align-items: center; box-shadow: 0 12px 34px -18px rgba(15,23,42,.25); transition: transform .15s ease, border-color .15s ease; }
  .channel:hover { border-color: var(--accent); transform: translateX(3px); }
  .ic { width: 44px; height: 44px; border-radius: 13px; display: flex; align-items: center; justify-content: center; background: color-mix(in srgb, var(--accent) 12%, #fff); color: var(--accent); font-weight: 900; }
  .ch-title { font-weight: 850; margin: 0 0 3px; font-size: 14.5px; }
  .ch-sub { color: var(--muted); font-size: 12.5px; line-height: 1.4; margin: 0; }
  .arrow { color: var(--muted); font-size: 20px; transition: transform .15s ease, color .15s ease; }
  .channel:hover .arrow { transform: translateX(3px); color: var(--accent); }

  /* Éxito */
  #bookingDone { display: none; padding: 34px 24px 30px; gap: 16px; text-align: center; justify-items: center; }
  #bookingDone.on { display: grid; animation: fadeSlide .35s ease; }
  .ck { width: 84px; height: 84px; }
  .ck circle { fill: none; stroke: var(--ok); stroke-width: 2.6; stroke-dasharray: 166; stroke-dashoffset: 166; animation: ckDraw .7s cubic-bezier(.65,0,.45,1) forwards; }
  .ck path { fill: none; stroke: var(--ok); stroke-width: 3.4; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 48; stroke-dashoffset: 48; animation: ckDraw .45s cubic-bezier(.65,0,.45,1) .55s forwards; }
  @keyframes ckDraw { to { stroke-dashoffset: 0; } }
  #bookingDone.on .ck { animation: ckPop .45s cubic-bezier(.3,1.6,.5,1) .9s both; }
  @keyframes ckPop { 0% { transform: scale(1); } 45% { transform: scale(1.08); } 100% { transform: scale(1); } }
  #bookingDone h3 { font-size: 24px; font-weight: 900; letter-spacing: -.01em; }
  #bookingDone .msg { color: var(--muted); font-size: 15px; line-height: 1.55; max-width: 460px; }
  #bookingDone .summary { width: 100%; max-width: 440px; text-align: left; display: grid; gap: 8px; padding: 15px 17px; border: 1px solid var(--line); border-radius: 13px; background: #fbfcfe; color: var(--muted); font-size: 14px; }
  #bookingDone .summary b { color: var(--ink); }
  .done-actions { display: flex; gap: 10px; flex-wrap: wrap; justify-content: center; }

  /* Canje de bono / tarjeta regalo */
  .pre-redeem { display: grid; gap: 9px; }
  .pre-redeem #preGiftMsg:empty { display: none; }
  #redeemBlock { display: none; width: 100%; max-width: 440px; text-align: left; }
  #redeemBlock.on { display: grid; gap: 10px; animation: fadeSlide .35s ease; }
  .redeem-pkg { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 13px 15px; border: 1.5px solid color-mix(in srgb, var(--accent) 35%, var(--line)); border-radius: 13px; background: color-mix(in srgb, var(--accent) 6%, #fff); }
  .redeem-pkg .t { display: grid; gap: 2px; min-width: 0; }
  .redeem-pkg .t b { font-size: 14px; }
  .redeem-pkg .t span { color: var(--muted); font-size: 12.5px; }
  .redeem-pkg button { flex: none; border: 0; border-radius: 11px; background: var(--accent); color: var(--accent-ink); font-weight: 800; font-size: 13px; padding: 10px 14px; cursor: pointer; transition: filter .15s; }
  .redeem-pkg button:hover { filter: brightness(1.06); }
  .redeem-pkg button[disabled] { opacity: .6; cursor: wait; }
  .redeem-gift-toggle { border: 1.5px dashed var(--line); background: #fff; color: var(--muted); border-radius: 13px; padding: 12px 15px; font-size: 13.5px; font-weight: 700; cursor: pointer; text-align: left; width: 100%; }
  .redeem-gift-toggle:hover { border-color: var(--accent); color: var(--accent); }
  .redeem-gift-row { display: none; gap: 9px; }
  .redeem-gift-row.on { display: flex; animation: fadeSlide .3s ease; }
  .redeem-gift-row input { flex: 1; min-width: 0; border: 1.5px solid var(--line); border-radius: 12px; padding: 12px 13px; font: inherit; font-size: 15px; font-weight: 800; letter-spacing: 2px; text-transform: uppercase; }
  .redeem-gift-row input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 15%, transparent); }
  .redeem-gift-row button { flex: none; border: 0; border-radius: 12px; background: var(--accent); color: var(--accent-ink); font-weight: 800; padding: 0 18px; cursor: pointer; }
  .redeem-gift-row button[disabled] { opacity: .6; cursor: wait; }
  .redeem-note { border-radius: 12px; padding: 12px 15px; font-size: 13.5px; line-height: 1.45; }
  .redeem-note.ok { background: var(--ok-soft); color: #065f46; border: 1px solid var(--ok-line); }
  .redeem-note.err { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }

  .contact { color: var(--muted); text-align: center; font-size: 13px; padding: 0 18px 34px; }
  .contact a { color: inherit; }

  /* ── Responsive ───────────────────────────────────────── */
  @media (max-width: 960px) {
    .hero { min-height: 250px; padding-bottom: 112px; }
    .wrap { grid-template-columns: 1fr; margin-top: -84px; }
    .side { position: static; }
    .rail { display: none; }
    .msum { display: grid; gap: 7px; padding: 14px 16px; border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--line)); border-radius: 13px; background: color-mix(in srgb, var(--accent) 5%, #fff); color: var(--muted); font-size: 13.5px; }
    .msum b { color: var(--ink); }
    .wizard-steps { padding: 12px 16px 14px; gap: 2px; }
    .step { font-size: 0; gap: 0; }
    .step .n { width: 26px; height: 26px; font-size: 12px; }
    .panel-head, .form { padding-left: 18px; padding-right: 18px; }
    .wiz-track { margin-left: 18px; margin-right: 18px; }
    .grid2 { grid-template-columns: 1fr; }
    .wizard-nav { flex-direction: row; }
    .wizard-nav .primary { flex: 1; }
  }

  /* ── Modo embed (iframe en la web del negocio) ─────────── */
  body.embed { background: transparent; }
  .embed .hero, .embed .side, .embed .contact { display: none; }
  .embed .wrap { margin: 0 auto; padding: 6px; grid-template-columns: 1fr; max-width: 780px; }
  .embed .panel { animation: none; box-shadow: 0 10px 34px -18px rgba(15,23,42,.22); }
  .embed .msum { display: grid; gap: 7px; padding: 14px 16px; border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--line)); border-radius: 13px; background: color-mix(in srgb, var(--accent) 5%, #fff); color: var(--muted); font-size: 13.5px; }
  .embed .msum b { color: var(--ink); }

  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; }
  }
</style>
</head>
<body class="__EMBED_CLASS__">
  <header class="hero __HERO_ANIM__">
    <div class="orb orb-a"></div><div class="orb orb-b"></div>
    <div class="hero-inner">
      <div class="hero-top">
        <div class="monogram">__MONOGRAM__</div>
        <div class="eyebrow"><span></span>Reservas online</div>
      </div>
      <h1>__BUSINESS__</h1>
      <p class="lead">__TAGLINE__</p>
      <div class="trust">
        <span class="trust-chip">⚡ Confirmacion inmediata</span>
        <span class="trust-chip">🔔 Recordatorios automaticos</span>
        <span class="trust-chip">🔒 Datos protegidos</span>
      </div>
    </div>
  </header>

  <main class="wrap">
    <section class="panel" id="reservar">
      <div class="panel-head">
        <h2 class="panel-title">Reserva de cita</h2>
        <p class="panel-sub">Cuatro pasos y listo. Recibiras la confirmacion con los datos de tu reserva.</p>
      </div>
      <form id="bookingForm" __BOOKING_DISABLED__>
        <div class="wiz-track"><i id="wizBar"></i></div>
        <div class="wizard-steps">
          <button class="step on" type="button" data-step="service"><span class="n">1</span>Servicio</button>
          <button class="step" type="button" data-step="staff"><span class="n">2</span>Centro</button>
          <button class="step" type="button" data-step="time"><span class="n">3</span>Fecha</button>
          <button class="step" type="button" data-step="client"><span class="n">4</span>Cliente</button>
        </div>
        <div class="form">
          <div class="status" id="bookingStatus"></div>
          <section class="step-panel on" data-panel="service">
            <div class="fld-label">Elige tu servicio</div>
            <div class="choice-grid" id="serviceCards"></div>
          </section>
          <section class="step-panel" data-panel="staff">
            <div id="locBlock" style="display:none;">
              <div class="fld-label" style="margin-bottom:9px;">Centro</div>
              <div class="pick-grid" id="locCards"></div>
            </div>
            <div>
              <div class="fld-label" style="margin-bottom:9px;">Profesional</div>
              <div class="pick-grid" id="empCards"></div>
            </div>
          </section>
          <section class="step-panel" data-panel="time">
            <div>
              <div class="fld-label" style="margin-bottom:9px;">Elige el dia</div>
              <div class="date-strip" id="dateStrip"></div>
              <div class="date-other">
                <button type="button" class="chip-ghost" id="otherDayBtn">📅 Otra fecha</button>
                <input id="fecha" type="date" class="date-input" style="display:none;">
              </div>
            </div>
            <input id="hora" type="hidden">
            <div>
              <div class="fld-label" style="margin-bottom:9px;">Elige la hora</div>
              <div class="slots" id="slots"><div class="empty">Selecciona una fecha para ver horarios.</div></div>
            </div>
          </section>
          <section class="step-panel" data-panel="client">
            <div class="msum" id="bookingSummary"></div>
            <div class="grid2">
              <div>
                <label for="nombre">Nombre</label>
                <input id="nombre" autocomplete="name" placeholder="Tu nombre" required>
              </div>
              <div>
                <label for="telefono">Telefono</label>
                <input id="telefono" autocomplete="tel" placeholder="600 000 000">
              </div>
            </div>
            <div>
              <label for="email">Email</label>
              <input id="email" type="email" autocomplete="email" placeholder="tu@email.com">
            </div>
            <div>
              <label for="notas">Notas <span style="color:var(--muted); font-weight:600;">(opcional)</span></label>
              <textarea id="notas" maxlength="500" placeholder="Preferencias, dudas o detalles utiles"></textarea>
            </div>
            <div class="pre-redeem" id="preRedeemBlock">
              <button type="button" class="redeem-gift-toggle" id="redeemGiftToggle">🎁 &iquest;Tienes una tarjeta regalo? Canjeala ahora</button>
              <div class="redeem-gift-row" id="redeemGiftRow">
                <input id="redeemGiftCode" maxlength="14" placeholder="GC-XXXX-XXXX" autocomplete="off" spellcheck="false">
                <button type="button" id="redeemGiftApply">Usar tarjeta</button>
              </div>
              <div id="preGiftMsg"></div>
            </div>
          </section>
          <div class="wizard-nav">
            <button class="secondary" id="prevStep" type="button">&larr; Atras</button>
            <button class="primary" id="nextStep" type="button">Continuar &rarr;</button>
            <button class="primary" id="submitBooking" type="submit" style="display:none;">Confirmar reserva ✓</button>
          </div>
        </div>
      </form>
      <div class="done" id="bookingDone">
        <svg class="ck" viewBox="0 0 56 56"><circle cx="28" cy="28" r="26.4"/><path d="M16 29.5l8.2 8L40 21"/></svg>
        <h3>&iexcl;Reserva confirmada!</h3>
        <p class="msg" id="doneMsg"></p>
        <div class="summary" id="doneSummary"></div>
        <div id="redeemBlock">
          <div id="redeemPkgs"></div>
          <div id="redeemMsg"></div>
        </div>
        <div class="done-actions">
          <a class="primary" id="donePay" style="display:none;">Completar pago</a>
          <a class="secondary" id="doneManage" style="display:none;">Gestionar mi cita</a>
          <button class="secondary" id="doneAgain" type="button">Hacer otra reserva</button>
        </div>
      </div>
      <div class="form" id="bookingUnavailable" __BOOKING_AVAILABLE_STYLE__>
        <div class="empty">La reserva online no esta activa en este momento.</div>
      </div>
    </section>

    <aside class="side">
      <div class="rail">
        <div class="rail-head">Tu reserva</div>
        <div class="rail-body">
          <div class="rail-row"><span class="rail-k">Servicio</span><b class="rail-v" id="railSvc">&mdash;</b></div>
          <div class="rail-row" id="railLocRow" style="display:none;"><span class="rail-k">Centro</span><b class="rail-v" id="railLoc">&mdash;</b></div>
          <div class="rail-row"><span class="rail-k">Profesional</span><b class="rail-v" id="railEmp">Cualquiera</b></div>
          <div class="rail-row"><span class="rail-k">Fecha</span><b class="rail-v" id="railDate">&mdash;</b></div>
          <div class="rail-row"><span class="rail-k">Hora</span><b class="rail-v" id="railTime">&mdash;</b></div>
          <div class="rail-total" id="railTotalRow" style="display:none;"><span>Precio</span><b id="railPrice"></b></div>
        </div>
      </div>
      __CHANNELS__
    </aside>
  </main>
  <div class="contact">__CONTACT__</div>

<script>
const CFG = __CFG__;
const $ = (id) => document.getElementById(id);
const STEPS = ["service", "staff", "time", "client"];
const st = { step: 0, services: [], service: null, locations: [], locId: "", employees: [], empId: "", date: "", hour: "", staffLoaded: false, pendingGiftCode: "" };

function todayIso() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 10);
}
function toLocalIso(d) {
  const x = new Date(d);
  x.setMinutes(x.getMinutes() - x.getTimezoneOffset());
  return x.toISOString().slice(0, 10);
}
function fmtDayLong(iso) {
  try { return new Date(iso + "T00:00:00").toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" }); }
  catch (_) { return iso; }
}
function status(kind, msg, asHtml) {
  const box = $("bookingStatus");
  if (!box) return;
  box.className = "status " + kind;
  if (asHtml) box.innerHTML = msg;
  else box.textContent = msg;
  if (kind && msg) box.scrollIntoView({ block: "nearest" });
}
function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
async function api(path, opts) {
  const res = await fetch(path, Object.assign({ headers: { "Accept": "application/json" } }, opts || {}));
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) {}
  if (!res.ok) throw new Error((data && data.detail) || text || "No se pudo completar la solicitud.");
  return data;
}
function serviceName(s) { return String(s.nombre || s.name || s.id || "Servicio"); }
function serviceSlug(s) { return String(s.id || s.slug || serviceName(s)); }
function skel(n, kind) {
  let out = "";
  for (let i = 0; i < n; i++) out += '<div class="skel skel-' + kind + '"></div>';
  return kind === "slot" ? '<div class="slot-grid">' + out + "</div>" : out;
}
function initials(name) {
  const parts = String(name || "").trim().split(" ").filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}

// --- Resumen en vivo (rail lateral + version movil) ----------------------------
function setVal(id, txt) {
  const el = $(id);
  if (!el) return;
  if (el.textContent !== txt) {
    el.textContent = txt;
    el.classList.remove("pop");
    void el.offsetWidth;
    el.classList.add("pop");
  }
}
function renderRail() {
  const loc = st.locations.filter(function (l) { return l.location_id === st.locId; })[0];
  const emp = st.employees.filter(function (e) { return e.employee_id === st.empId; })[0];
  setVal("railSvc", st.service ? st.service.label : "—");
  const locRow = $("railLocRow");
  if (locRow) locRow.style.display = st.locations.length > 1 ? "" : "none";
  setVal("railLoc", loc ? loc.name : "—");
  setVal("railEmp", emp ? emp.name : "Cualquiera");
  setVal("railDate", st.date ? fmtDayLong(st.date) : "—");
  setVal("railTime", st.hour || "—");
  const totalRow = $("railTotalRow");
  if (totalRow) {
    const price = st.service && st.service.price;
    totalRow.style.display = price ? "" : "none";
    if (price) $("railPrice").textContent = price;
  }
  const msum = $("bookingSummary");
  if (msum) {
    const rows = [["Servicio", st.service ? st.service.label : "—"]];
    if (loc) rows.push(["Centro", loc.name]);
    rows.push(["Profesional", emp ? emp.name : "Cualquiera"]);
    rows.push(["Fecha", st.date ? fmtDayLong(st.date) : "—"], ["Hora", st.hour || "—"]);
    if (st.service && st.service.price) rows.push(["Precio", st.service.price]);
    msum.innerHTML = rows.map(function (r) { return "<span>" + esc(r[0]) + ": <b>" + esc(r[1]) + "</b></span>"; }).join("");
  }
}

// --- Navegacion del wizard ----------------------------------------------------
function showStep(i) {
  st.step = Math.max(0, Math.min(STEPS.length - 1, i));
  const key = STEPS[st.step];
  document.querySelectorAll(".step-panel").forEach(function (p) { p.classList.toggle("on", p.dataset.panel === key); });
  document.querySelectorAll(".wizard-steps .step").forEach(function (b) {
    const idx = STEPS.indexOf(b.dataset.step);
    b.classList.toggle("on", idx === st.step);
    b.classList.toggle("done", idx < st.step);
    const n = b.querySelector(".n");
    if (n) n.textContent = idx < st.step ? "✓" : String(idx + 1);
  });
  const bar = $("wizBar");
  if (bar) bar.style.width = (((st.step + 1) / STEPS.length) * 100) + "%";
  $("prevStep").style.visibility = st.step === 0 ? "hidden" : "visible";
  const last = st.step === STEPS.length - 1;
  $("nextStep").style.display = last ? "none" : "";
  $("submitBooking").style.display = last ? "" : "none";
  status("", "");
  if (key === "staff") ensureStaff();
  else if (key === "time") loadSlots();
  renderRail();
}
function validateStep() {
  const key = STEPS[st.step];
  if (key === "service" && !st.service) { status("err", "Elige un servicio para continuar."); return false; }
  if (key === "time" && (!$("fecha").value || !st.hour)) { status("err", "Selecciona fecha y hora."); return false; }
  return true;
}

// --- Paso 1: servicio ---------------------------------------------------------
async function loadServices() {
  const wrap = $("serviceCards");
  wrap.innerHTML = skel(4, "card");
  try {
    const data = await api("/servicios/" + encodeURIComponent(CFG.clienteId));
    st.services = Array.isArray(data && data.servicios) ? data.servicios : [];
  } catch (e) { st.services = []; }
  if (!st.services.length) {
    st.service = { name: "", slug: "", label: "Consulta general", price: "", mins: 0 };
    wrap.innerHTML = '<div class="empty">Este negocio no tiene servicios publicados. Continua para reservar una consulta general.</div>';
    renderRail();
    return;
  }
  wrap.innerHTML = st.services.map(function (s, i) {
    const meta = [];
    if (s.duration_minutes) meta.push("<span>⏱ " + esc(String(s.duration_minutes)) + " min</span>");
    const price = s.price_label ? '<span class="choice-price">' + esc(s.price_label) + "</span>" : "";
    // Con catalogo mixto (unas con foto, otras sin), las cards sin foto llevan un
    // placeholder con la inicial para mantener alturas uniformes.
    const anyMedia = st.services.some(function (x) { return x.image_url; });
    const media = s.image_url
      ? '<div class="choice-media"><img src="' + esc(s.image_url) + '" alt="" loading="lazy"></div>'
      : (anyMedia ? '<div class="choice-media ph">' + esc(serviceName(s).charAt(0).toUpperCase()) + "</div>" : "");
    return '<button type="button" class="choice-card" data-svc="' + i + '">' + media
      + '<div class="choice-body">'
      + '<div class="choice-row"><div class="choice-title">' + esc(serviceName(s)) + "</div>" + price + "</div>"
      + '<div class="choice-meta">' + (meta.join("") || "<span>Servicio</span>") + "</div></div></button>";
  }).join("");
  wrap.querySelectorAll("[data-svc]").forEach(function (card) {
    card.addEventListener("click", function () {
      const s = st.services[Number(card.dataset.svc)];
      st.service = { name: serviceName(s), slug: serviceSlug(s), label: serviceName(s), price: s.price_label || "", mins: s.duration_minutes || 0 };
      st.empId = ""; st.hour = "";
      wrap.querySelectorAll(".choice-card").forEach(function (c) { c.classList.remove("on"); });
      card.classList.add("on");
      renderRail();
      setTimeout(function () { if (st.step === 0) showStep(1); }, 260);
    });
  });
}

// --- Paso 2: centro + profesional --------------------------------------------
async function ensureStaff() {
  if (!st.staffLoaded) {
    st.staffLoaded = true;
    try { const d = await api("/centros/" + encodeURIComponent(CFG.clienteId)); st.locations = (d && d.items) || []; }
    catch (e) { st.locations = []; }
    const block = $("locBlock");
    if (st.locations.length > 1) {
      block.style.display = "";
      const def = st.locations.filter(function (l) { return l.is_default; })[0] || st.locations[0];
      st.locId = def.location_id;
      renderLocCards();
    } else {
      block.style.display = "none";
      st.locId = st.locations.length ? st.locations[0].location_id : "";
    }
  }
  await loadEmployees();
}
function renderLocCards() {
  const wrap = $("locCards");
  wrap.innerHTML = st.locations.map(function (l) {
    return '<button type="button" class="pick-card' + (l.location_id === st.locId ? " on" : "") + '" data-loc="' + esc(l.location_id) + '">'
      + '<span class="avatar" style="background:linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 55%, #0b1526));">📍</span>'
      + '<span class="pick-txt"><span class="pick-name">' + esc(l.name) + "</span>"
      + (l.address ? '<span class="pick-sub">' + esc(l.address) + "</span>" : "")
      + "</span></button>";
  }).join("");
  wrap.querySelectorAll("[data-loc]").forEach(function (card) {
    card.addEventListener("click", function () {
      st.locId = card.dataset.loc; st.empId = ""; st.hour = "";
      wrap.querySelectorAll(".pick-card").forEach(function (c) { c.classList.toggle("on", c.dataset.loc === st.locId); });
      loadEmployees();
      renderRail();
    });
  });
}
async function loadEmployees() {
  const wrap = $("empCards");
  wrap.innerHTML = skel(3, "row");
  try {
    const q = st.locId ? "?location_id=" + encodeURIComponent(st.locId) : "";
    const d = await api("/profesionales/" + encodeURIComponent(CFG.clienteId) + q);
    st.employees = (d && d.items) || [];
  } catch (e) { st.employees = []; }
  const slug = st.service && st.service.slug;
  let usable = st.employees.filter(function (e) {
    return e.allows_all_services || !slug || (e.service_ids || []).indexOf(slug) !== -1;
  });
  if (!usable.length && st.employees.length) usable = st.employees;
  if (!usable.some(function (e) { return e.employee_id === st.empId; })) st.empId = "";
  const cards = ['<button type="button" class="pick-card' + (st.empId ? "" : " on") + '" data-emp="">'
    + '<span class="avatar" style="background:linear-gradient(135deg, #64748b, #334155);">👥</span>'
    + '<span class="pick-txt"><span class="pick-name">Cualquier profesional</span><span class="pick-sub">Primera persona disponible</span></span></button>'];
  usable.forEach(function (e) {
    cards.push('<button type="button" class="pick-card' + (e.employee_id === st.empId ? " on" : "") + '" data-emp="' + esc(e.employee_id) + '">'
      + '<span class="avatar" style="background:' + esc(e.color || "#00b1d9") + ';">' + esc(initials(e.name)) + "</span>"
      + '<span class="pick-txt"><span class="pick-name">' + esc(e.name) + "</span>"
      + (e.role_label ? '<span class="pick-sub">' + esc(e.role_label) + "</span>" : "")
      + "</span></button>");
  });
  wrap.innerHTML = cards.join("");
  wrap.querySelectorAll("[data-emp]").forEach(function (card) {
    card.addEventListener("click", function () {
      st.empId = card.dataset.emp || ""; st.hour = "";
      wrap.querySelectorAll(".pick-card").forEach(function (c) { c.classList.toggle("on", (c.dataset.emp || "") === st.empId); });
      renderRail();
    });
  });
  renderRail();
}

// --- Paso 3: dia + hora ---------------------------------------------------------
function buildDateStrip() {
  const stripEl = $("dateStrip");
  if (!stripEl) return;
  const base = new Date();
  const chips = [];
  for (let i = 0; i < 14; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    const iso = toLocalIso(d);
    const dow = i === 0 ? "Hoy" : i === 1 ? "Mañana" : d.toLocaleDateString("es-ES", { weekday: "short" });
    chips.push('<button type="button" class="day-chip" data-day="' + esc(iso) + '">'
      + '<span class="day-dow">' + esc(dow) + "</span>"
      + '<span class="day-num">' + d.getDate() + "</span>"
      + '<span class="day-mon">' + esc(d.toLocaleDateString("es-ES", { month: "short" })) + "</span></button>");
  }
  stripEl.innerHTML = chips.join("");
  stripEl.querySelectorAll("[data-day]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      $("fecha").value = chip.dataset.day;
      st.hour = "";
      markDay(chip.dataset.day);
      loadSlots();
      renderRail();
    });
  });
}
function markDay(iso) {
  document.querySelectorAll("#dateStrip .day-chip").forEach(function (c) { c.classList.toggle("on", c.dataset.day === iso); });
}
function slotPeriod(hora) {
  const hh = parseInt(String(hora).slice(0, 2), 10);
  if (hh < 14) return "Mañana";
  if (hh < 19) return "Tarde";
  return "Noche";
}
async function loadSlots() {
  const fecha = $("fecha").value;
  const slots = $("slots");
  st.hour = "";
  $("hora").value = "";
  st.date = fecha || "";
  if (!fecha) {
    slots.innerHTML = '<div class="empty">Selecciona una fecha para ver horarios.</div>';
    return;
  }
  slots.innerHTML = skel(8, "slot");
  try {
    const params = new URLSearchParams({ cliente_id: CFG.clienteId, fecha: fecha });
    if (st.service && st.service.name) params.set("servicio", st.service.name);
    if (st.locId) params.set("location_id", st.locId);
    if (st.empId) params.set("employee_id", st.empId);
    const data = await api("/disponibilidad?" + params.toString());
    const available = (Array.isArray(data && data.slots) ? data.slots : []).filter(function (s) { return s.disponible !== false; });
    if (!available.length) {
      slots.innerHTML = '<div class="empty">No hay horarios disponibles para ese dia. Prueba otra fecha.</div>';
      return;
    }
    const groups = {};
    const order = ["Mañana", "Tarde", "Noche"];
    available.forEach(function (s) {
      const g = slotPeriod(s.hora || "");
      (groups[g] = groups[g] || []).push(s.hora || "");
    });
    slots.innerHTML = order.filter(function (g) { return groups[g] && groups[g].length; }).map(function (g) {
      return '<div class="slot-group"><div class="slot-glabel">' + esc(g) + '</div><div class="slot-grid">'
        + groups[g].map(function (h) { return '<button type="button" class="slot" data-h="' + esc(h) + '">' + esc(h) + "</button>"; }).join("")
        + "</div></div>";
    }).join("");
    slots.querySelectorAll(".slot").forEach(function (btn) {
      btn.addEventListener("click", function () {
        slots.querySelectorAll(".slot").forEach(function (x) { x.classList.remove("on"); });
        btn.classList.add("on");
        st.hour = btn.dataset.h || "";
        $("hora").value = st.hour;
        renderRail();
        setTimeout(function () { if (st.step === 2 && st.hour) showStep(3); }, 320);
      });
    });
  } catch (e) {
    slots.innerHTML = '<div class="empty">' + esc(e.message) + "</div>";
  }
}

// --- Paso 4: envio --------------------------------------------------------------
async function submitBooking(ev) {
  ev.preventDefault();
  const btn = $("submitBooking");
  const name = $("nombre").value.trim();
  const email = $("email").value.trim();
  const phone = $("telefono").value.trim();
  const giftCode = $("redeemGiftCode").value.trim();
  if (!name) { status("err", "Indica tu nombre."); return; }
  if (!email && !phone) { status("err", "Indica al menos un email o telefono para recibir la confirmacion."); return; }
  if (!$("fecha").value || !st.hour) { status("err", "Vuelve al paso de fecha y elige una hora."); showStep(2); return; }
  if (giftCode && giftCode.replace(/[^A-Za-z0-9]/g, "").length < 6) {
    giftPreNote("err", "Escribe el codigo completo de la tarjeta.");
    $("redeemGiftRow").classList.add("on");
    $("redeemGiftCode").focus();
    return;
  }
  st.pendingGiftCode = giftCode;
  btn.disabled = true;
  btn.textContent = "Confirmando…";
  try {
    const data = await api("/agendar", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({
        cliente_id: CFG.clienteId,
        nombre: name,
        email: email,
        telefono: phone,
        servicio: (st.service && st.service.name) || "",
        fecha: $("fecha").value,
        hora: st.hour,
        location_id: st.locId || "",
        employee_id: st.empId || "",
        notas: $("notas").value.trim()
      })
    });
    showDone(data || {});
  } catch (e) {
    status("err", e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Confirmar reserva ✓";
  }
}
function showDone(data) {
  const loc = st.locations.filter(function (l) { return l.location_id === st.locId; })[0];
  const emp = st.employees.filter(function (e) { return e.employee_id === st.empId; })[0];
  const rows = [
    ["Servicio", (st.service && st.service.label) || "Consulta general"],
    loc ? ["Centro", loc.name] : null,
    ["Profesional", emp ? emp.name : "Cualquiera disponible"],
    ["Fecha", st.date ? fmtDayLong(st.date) : $("fecha").value],
    ["Hora", st.hour || ""]
  ].filter(Boolean);
  if (st.service && st.service.price) rows.push(["Precio", st.service.price]);
  $("doneMsg").textContent = data.mensaje || "Te esperamos. Recibiras la confirmacion con los datos de tu reserva.";
  $("doneSummary").innerHTML = rows.map(function (r) { return "<span>" + esc(r[0]) + ": <b>" + esc(r[1]) + "</b></span>"; }).join("");
  const pay = $("donePay"), manage = $("doneManage");
  if (data.payment_url) { pay.href = data.payment_url; pay.style.display = "inline-flex"; } else pay.style.display = "none";
  if (data.manage_url) { manage.href = data.manage_url; manage.style.display = "inline-flex"; } else manage.style.display = "none";
  $("redeemBlock").classList.remove("on");
  $("redeemMsg").innerHTML = "";
  loadRedeemOptions(data.manage_url, st.pendingGiftCode);
  document.querySelector(".wiz-track").style.display = "none";
  document.querySelector(".wizard-steps").style.display = "none";
  $("bookingForm").querySelector(".form").style.display = "none";
  $("bookingDone").classList.add("on");
  $("bookingDone").scrollIntoView({ block: "nearest" });
}

// --- Canje de bono / tarjeta regalo sobre la cita recien creada -----------------
// El manage_token (secreto del enlace de gestion) autoriza el canje; los bonos se
// detectan por el email/telefono de la reserva, la tarjeta exige poseer el codigo.
const redeem = { token: "", applied: false };
function eurFmt(c) { return ((c || 0) / 100).toLocaleString("es-ES", { minimumFractionDigits: (c || 0) % 100 ? 2 : 0 }) + " €"; }
function redeemUrl(suffix) { return "/central/" + encodeURIComponent(CFG.clienteId) + suffix; }
function giftCodeValue() { return $("redeemGiftCode").value.trim().toUpperCase(); }
function giftPreNote(kind, msg) {
  $("preGiftMsg").innerHTML = '<div class="redeem-note ' + kind + '">' + esc(msg) + "</div>";
}
function redeemNote(kind, html) { $("redeemMsg").innerHTML = '<div class="redeem-note ' + kind + '">' + html + "</div>"; }
function redeemSuccess(html) {
  redeem.applied = true;
  $("redeemPkgs").innerHTML = "";
  $("donePay").style.display = "none";
  redeemNote("ok", html);
}
async function loadRedeemOptions(manageUrl, pendingGiftCode) {
  const code = String(pendingGiftCode || "").trim();
  const m = String(manageUrl || "").match(/\\/booking\\/manage\\/([^\\/?#]+)/);
  if (!m) {
    if (code) {
      $("redeemBlock").classList.add("on");
      redeemNote("err", "Reserva confirmada, pero no hemos podido aplicar la tarjeta automaticamente.");
    }
    return;
  }
  redeem.token = m[1];
  redeem.applied = false;
  let opts = null;
  try {
    opts = await api(redeemUrl("/redeem-options"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manage_token: redeem.token })
    });
  } catch (e) {
    if (code) {
      $("redeemBlock").classList.add("on");
      redeemNote("err", "Reserva confirmada, pero no hemos podido comprobar la tarjeta.");
    }
    return;
  }
  if (!opts || !opts.can_redeem) {
    if (code) {
      $("redeemBlock").classList.add("on");
      redeemNote("err", "La cita no tiene importe pendiente para canjear la tarjeta.");
    }
    return;
  }
  const pkgs = opts.packages || [];
  $("redeemPkgs").innerHTML = pkgs.map(function (p) {
    const plural = p.sessions_left === 1 ? "" : "s";
    return '<div class="redeem-pkg"><div class="t"><b>🎟 ' + esc(p.package_name) + "</b>"
      + "<span>Tienes " + p.sessions_left + " sesion" + (plural ? "es" : "") + " de este servicio"
      + (p.expires_at ? " · caduca el " + esc(p.expires_at) : "") + "</span></div>"
      + '<button type="button" data-purchase="' + esc(p.purchase_id) + '">Usar 1 sesion</button></div>';
  }).join("");
  $("redeemPkgs").querySelectorAll("[data-purchase]").forEach(function (btn) {
    btn.addEventListener("click", function () { applyRedeem({ kind: "package", purchase_id: btn.dataset.purchase }, btn); });
  });
  if (code) {
    $("redeemBlock").classList.add("on");
    redeemNote("ok", "Aplicando tu tarjeta regalo...");
    await applyRedeem({ kind: "gift", code: code }, null);
    st.pendingGiftCode = "";
    return;
  }
  if (pkgs.length) $("redeemBlock").classList.add("on");
}
async function applyRedeem(payload, btn) {
  if (redeem.applied) return;
  const previousText = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Aplicando...";
  }
  try {
    const body = Object.assign({ manage_token: redeem.token }, payload);
    const res = await api(redeemUrl("/redeem"), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    });
    if (res.kind === "package") {
      redeemSuccess("✓ Sesion descontada de tu bono. <b>La cita queda pagada.</b>"
        + (res.sessions_left > 0 ? " Te quedan " + res.sessions_left + " sesiones." : ""));
    } else if (res.covered) {
      redeemSuccess("✓ Tarjeta aplicada (" + eurFmt(res.charged_cents) + "). <b>La cita queda pagada.</b>"
        + (res.balance_after_cents > 0 ? " Saldo restante: " + eurFmt(res.balance_after_cents) + "." : ""));
    } else {
      redeemSuccess("✓ Tarjeta aplicada (" + eurFmt(res.charged_cents) + "). Quedan <b>"
        + eurFmt(res.remaining_due_cents) + "</b> que se abonan en el centro.");
    }
  } catch (e) {
    redeemNote("err", esc(e.message));
    if (btn) {
      btn.disabled = false;
      btn.textContent = previousText;
    }
  }
}
$("redeemGiftToggle").addEventListener("click", function () {
  $("redeemGiftRow").classList.toggle("on");
  if ($("redeemGiftRow").classList.contains("on")) $("redeemGiftCode").focus();
  else $("preGiftMsg").innerHTML = "";
});
$("redeemGiftCode").addEventListener("input", function () {
  this.value = this.value.toUpperCase();
  st.pendingGiftCode = this.value.trim();
  $("preGiftMsg").innerHTML = "";
});
$("redeemGiftCode").addEventListener("keydown", function (ev) {
  if (ev.key === "Enter") { ev.preventDefault(); $("redeemGiftApply").click(); }
});
$("redeemGiftApply").addEventListener("click", function () {
  const code = giftCodeValue();
  if (code.replace(/[^A-Za-z0-9]/g, "").length < 6) { giftPreNote("err", "Escribe el codigo completo de la tarjeta."); return; }
  $("redeemGiftCode").value = code;
  st.pendingGiftCode = code;
  giftPreNote("ok", "Perfecto. La aplicaremos al confirmar la reserva.");
});

$("doneAgain").addEventListener("click", function () {
  $("bookingDone").classList.remove("on");
  $("redeemBlock").classList.remove("on");
  $("redeemMsg").innerHTML = "";
  $("redeemPkgs").innerHTML = "";
  $("preGiftMsg").innerHTML = "";
  $("redeemGiftRow").classList.remove("on");
  $("redeemGiftApply").disabled = false;
  $("redeemGiftApply").textContent = "Usar tarjeta";
  redeem.token = "";
  redeem.applied = false;
  document.querySelector(".wiz-track").style.display = "";
  document.querySelector(".wizard-steps").style.display = "";
  $("bookingForm").querySelector(".form").style.display = "";
  $("bookingForm").reset();
  st.service = null; st.empId = ""; st.hour = ""; st.staffLoaded = false; st.pendingGiftCode = "";
  document.querySelectorAll("#serviceCards .choice-card").forEach(function (c) { c.classList.remove("on"); });
  $("fecha").value = todayIso(); st.date = $("fecha").value;
  markDay(st.date);
  showStep(0);
});

$("nextStep").addEventListener("click", function () { if (validateStep()) showStep(st.step + 1); });
$("prevStep").addEventListener("click", function () { showStep(st.step - 1); });
document.querySelectorAll(".wizard-steps .step").forEach(function (b) {
  b.addEventListener("click", function () {
    const idx = STEPS.indexOf(b.dataset.step);
    if (idx < st.step) showStep(idx);                       // retroceder libre
    else if (idx === st.step + 1 && validateStep()) showStep(idx); // avanzar 1 paso validando
  });
});
$("otherDayBtn").addEventListener("click", function () {
  const inp = $("fecha");
  inp.style.display = inp.style.display === "none" ? "" : "none";
  if (inp.style.display === "") inp.focus();
});

if (CFG.bookingEnabled) {
  $("fecha").min = todayIso();
  $("fecha").value = todayIso();
  st.date = $("fecha").value;
  buildDateStrip();
  markDay(st.date);
  $("fecha").addEventListener("change", function () {
    st.hour = "";
    markDay($("fecha").value);
    loadSlots();
    renderRail();
  });
  $("bookingForm").addEventListener("submit", submitBooking);
  loadServices();
  showStep(0);
}
</script>
</body>
</html>"""


def central_public_page_html(cliente_id: str, embed: bool = False) -> str:
    """Central publica: reserva directa + accesos a ventas online existentes.
    Con embed=True (query ?embed=1) se sirve sin hero/laterales y con fondo
    transparente, pensada para incrustarse via iframe en la web del negocio."""
    import html as html_mod

    from backend import appstate, clients  # tardio

    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    business = html_mod.escape(str(config.get("empresa") or config.get("nombre") or "Nuestro negocio"))
    raw_color = str((config.get("branding") or {}).get("color") or config.get("color") or "#0f766e")
    color = raw_color if _GIFT_ACCENT_RE.match(raw_color) else "#0f766e"
    # Mismo criterio que /tienda: el color de acento configurado en el panel
    # (Ventas > Central online > Apariencia) manda sobre el color de marca del widget.
    shop_cfg = _shop_public_config(cliente_id)
    if shop_cfg.get("accent_color"):
        color = shop_cfg["accent_color"]
    contacto = config.get("contacto") or {}
    contact_bits = " &middot; ".join(
        html_mod.escape(x) for x in (
            textnorm._sanitize_text(str(contacto.get("telefono") or "")),
            textnorm._sanitize_text(str(contacto.get("email") or "")),
            textnorm._sanitize_text(str(contacto.get("direccion") or "")),
        ) if x
    )
    if contact_bits:
        contact_bits = f"{contact_bits} &middot; "
    contact_bits += '<a href="https://www.vantelia.es" target="_blank" rel="noreferrer">Tecnologia Vantelia</a>'

    try:
        booking_enabled = bool((config.get("booking") or {}).get("enabled")) and clients._client_booking_plan_enabled(cliente_id)
    except Exception:  # noqa: BLE001
        booking_enabled = bool((config.get("booking") or {}).get("enabled"))
    shop_available = shop_public_available(cliente_id)
    gift_available = gift_public_available(cliente_id)

    channels: List[str] = []
    if booking_enabled:
        channels.append(
            '<a class="channel" href="#reservar">'
            '<div class="ic">R</div><div><div class="ch-title">Reservar cita</div>'
            '<p class="ch-sub">Agenda directa con disponibilidad en tiempo real.</p></div><div class="arrow">&rarr;</div></a>'
        )
    if shop_available.get("packages"):
        channels.append(
            f'<a class="channel" href="/tienda/{html_mod.escape(cliente_id)}?solo=bonos">'
            '<div class="ic">B</div><div><div class="ch-title">Bonos</div>'
            '<p class="ch-sub">Compra sesiones por adelantado y canjealas al reservar.</p></div><div class="arrow">&rarr;</div></a>'
        )
    if shop_available.get("products"):
        channels.append(
            f'<a class="channel" href="/tienda/{html_mod.escape(cliente_id)}?solo=productos">'
            '<div class="ic">P</div><div><div class="ch-title">Productos</div>'
            '<p class="ch-sub">Compra online y recoge tu pedido en el centro.</p></div><div class="arrow">&rarr;</div></a>'
        )
    if gift_available:
        channels.append(
            f'<a class="channel" href="/gift/{html_mod.escape(cliente_id)}">'
            '<div class="ic">T</div><div><div class="ch-title">Tarjetas regalo</div>'
            '<p class="ch-sub">Regala saldo o una experiencia concreta.</p></div><div class="arrow">&rarr;</div></a>'
        )
    if not channels:
        channels.append('<div class="empty">No hay canales publicos activos.</div>')

    # Hero: foto configurada por el negocio (Ventas > Central online > Apariencia)
    # con overlay para legibilidad; sin foto, gradiente animado del color de marca.
    # Nunca assets de Vantelia (brand_assets/ es la identidad de la plataforma).
    hero_photo = shop_cfg.get("hero_image_url") or ""
    if hero_photo:
        hero_bg = (
            f'background: linear-gradient(105deg, rgba(6,10,24,.86), rgba(6,10,24,.36)), '
            f'url("{html_mod.escape(hero_photo)}") center / cover no-repeat;'
        )
        hero_anim = ""
    else:
        hero_bg = (
            f"background: linear-gradient(120deg, "
            f"color-mix(in srgb, {color} 88%, #06121f), "
            f"color-mix(in srgb, {color} 46%, #0b1526), "
            f"color-mix(in srgb, {color} 72%, #123049));"
        )
        hero_anim = "hero-anim"
    tagline = shop_cfg.get("hero_tagline") or "Elige servicio, dia y hora. Confirmacion al momento, sin llamadas ni esperas."

    # Monograma: el icono/emoji configurado del negocio si existe; si no, su inicial.
    icono = textnorm._sanitize_text(str(config.get("icono") or "")).strip()
    if icono and not icono.isascii():
        monogram = icono[:2]
    else:
        monogram = next((ch for ch in str(config.get("empresa") or config.get("nombre") or "V") if ch.isalnum()), "V").upper()

    cfg_json = json.dumps(
        {"clienteId": cliente_id, "bookingEnabled": bool(booking_enabled)},
        ensure_ascii=False,
    ).replace("</", "<\\/")

    page = _CENTRAL_PAGE_TEMPLATE
    for token, value in (
        ("__BUSINESS__", business),
        ("__COLOR__", color),
        ("__HERO_BG__", hero_bg),
        ("__HERO_ANIM__", hero_anim),
        ("__MONOGRAM__", html_mod.escape(monogram)),
        ("__TAGLINE__", html_mod.escape(tagline)),
        ("__EMBED_CLASS__", "embed" if embed else ""),
        ("__BOOKING_DISABLED__", "" if booking_enabled else 'style="display:none"'),
        ("__BOOKING_AVAILABLE_STYLE__", 'style="display:none"' if booking_enabled else ""),
        ("__CHANNELS__", "\n      ".join(channels)),
        ("__CONTACT__", contact_bits),
        ("__CFG__", cfg_json),
    ):
        page = page.replace(token, value)
    return page
