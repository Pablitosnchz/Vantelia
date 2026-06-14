"""Endpoints: comercio del portal (F4) e informes (F5).

Productos, bonos y tarjetas regalo + analytics economico. Decoran la app de
backend.main directamente (mismo patron que el resto de routers).

Roles: lectura y operaciones de mostrador (vender, redimir) = staff;
gestion de catalogo y consulta de informes = manager.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

from fastapi import Depends, Response

from api_models import *  # noqa: F401,F403
from backend import analytics, commerce, portal, security
from backend.main import app


# ---------------------------------------------------------------------------
# Productos
# ---------------------------------------------------------------------------


@app.get("/auth/products")
async def auth_list_products(
    cliente_id: str = "",
    include_inactive: bool = True,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, List[Dict[str, Any]]]:
    target = portal._portal_client_id_or_403(user, cliente_id)
    return {"items": commerce._list_products(target, include_inactive=include_inactive)}


@app.post("/auth/products")
async def auth_create_product(
    data: ProductPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    security._require_portal_permission(user, "catalog.manage")
    return commerce._create_product(portal._portal_client_id_or_403(user, cliente_id), data)


@app.post("/auth/products/{product_id}")
async def auth_update_product(
    product_id: str,
    data: ProductPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    security._require_portal_permission(user, "catalog.manage")
    return commerce._update_product(portal._portal_client_id_or_403(user, cliente_id), product_id, data)


@app.delete("/auth/products/{product_id}", response_model=AuthSimpleResponse)
async def auth_delete_product(
    product_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    security._require_portal_permission(user, "catalog.manage")
    commerce._delete_product(portal._portal_client_id_or_403(user, cliente_id), product_id)
    return AuthSimpleResponse(ok=True, message="Producto eliminado.")


@app.post("/auth/products/{product_id}/sell")
async def auth_sell_product(
    product_id: str,
    data: ProductSalePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    security._require_portal_permission(user, "commerce.sell")
    return commerce._sell_product(portal._portal_client_id_or_403(user, cliente_id), product_id, data)


@app.get("/auth/product-sales")
async def auth_list_product_sales(
    cliente_id: str = "",
    location_id: str = "",
    date_from: str = "",
    date_to: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, List[Dict[str, Any]]]:
    target = portal._portal_client_id_or_403(user, cliente_id)
    return {
        "items": commerce._list_product_sales(
            target, location_id=location_id, date_from=date_from, date_to=date_to
        )
    }


# ---------------------------------------------------------------------------
# Bonos (paquetes)
# ---------------------------------------------------------------------------


@app.get("/auth/packages")
async def auth_list_packages(
    cliente_id: str = "",
    include_inactive: bool = True,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, List[Dict[str, Any]]]:
    target = portal._portal_client_id_or_403(user, cliente_id)
    return {"items": commerce._list_packages(target, include_inactive=include_inactive)}


@app.post("/auth/packages")
async def auth_create_package(
    data: PackagePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    security._require_portal_permission(user, "catalog.manage")
    return commerce._create_package(portal._portal_client_id_or_403(user, cliente_id), data)


@app.post("/auth/packages/{package_id}")
async def auth_update_package(
    package_id: str,
    data: PackagePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    security._require_portal_permission(user, "catalog.manage")
    return commerce._update_package(portal._portal_client_id_or_403(user, cliente_id), package_id, data)


@app.delete("/auth/packages/{package_id}", response_model=AuthSimpleResponse)
async def auth_delete_package(
    package_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    security._require_portal_permission(user, "catalog.manage")
    commerce._delete_package(portal._portal_client_id_or_403(user, cliente_id), package_id)
    return AuthSimpleResponse(ok=True, message="Bono eliminado.")


@app.post("/auth/packages/{package_id}/sell")
async def auth_sell_package(
    package_id: str,
    data: PackageSellPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    security._require_portal_permission(user, "commerce.sell")
    return commerce._sell_package(portal._portal_client_id_or_403(user, cliente_id), package_id, data)


@app.get("/auth/package-purchases")
async def auth_list_package_purchases(
    cliente_id: str = "",
    q: str = "",
    status: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, List[Dict[str, Any]]]:
    target = portal._portal_client_id_or_403(user, cliente_id)
    return {"items": commerce._list_package_purchases(target, q=q, status=status)}


@app.post("/auth/package-purchases/{purchase_id}/redeem")
async def auth_redeem_package(
    purchase_id: str,
    data: PackageRedeemPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    security._require_portal_permission(user, "commerce.sell")
    target = portal._portal_client_id_or_403(user, cliente_id)
    return commerce._redeem_package_for_booking(target, purchase_id, data.booking_id)


# ---------------------------------------------------------------------------
# Tarjetas regalo
# ---------------------------------------------------------------------------


@app.get("/auth/gift-cards")
async def auth_list_gift_cards(
    cliente_id: str = "",
    q: str = "",
    status: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, List[Dict[str, Any]]]:
    target = portal._portal_client_id_or_403(user, cliente_id)
    return {"items": commerce._list_gift_cards(target, q=q, status=status)}


@app.post("/auth/gift-cards")
async def auth_issue_gift_card(
    data: GiftCardIssuePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    security._require_portal_permission(user, "commerce.sell")
    return commerce._issue_gift_card(portal._portal_client_id_or_403(user, cliente_id), data)


@app.post("/auth/gift-cards/{gift_card_id}/status")
async def auth_gift_card_status(
    gift_card_id: str,
    data: GiftCardStatusPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    security._require_portal_permission(user, "catalog.manage")
    target = portal._portal_client_id_or_403(user, cliente_id)
    return commerce._set_gift_card_status(target, gift_card_id, data.enabled)


@app.post("/auth/gift-cards/redeem")
async def auth_redeem_gift_card(
    data: GiftCardRedeemPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    security._require_portal_permission(user, "commerce.sell")
    target = portal._portal_client_id_or_403(user, cliente_id)
    return commerce._redeem_gift_card_for_booking(
        target, data.code, data.booking_id, amount_cents=data.amount_cents
    )


# ---------------------------------------------------------------------------
# Informes (F5)
# ---------------------------------------------------------------------------


@app.get("/auth/analytics/overview")
async def auth_analytics_overview(
    cliente_id: str = "",
    location_id: str = "",
    service_id: str = "",
    date_from: str = "",
    date_to: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    security._require_portal_permission(user, "reports.view")
    target = portal._portal_client_id_or_403(user, cliente_id)
    return analytics._overview(
        target, location_id=location_id, service_id=service_id,
        date_from=date_from, date_to=date_to,
    )


@app.get("/auth/analytics/export.csv")
async def auth_analytics_export(
    cliente_id: str = "",
    location_id: str = "",
    service_id: str = "",
    date_from: str = "",
    date_to: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Response:
    security._require_portal_permission(user, "reports.export")
    target = portal._portal_client_id_or_403(user, cliente_id)
    csv_text = analytics._export_csv(
        target, location_id=location_id, service_id=service_id,
        date_from=date_from, date_to=date_to,
    )
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=informe_vantelia.csv"},
    )
