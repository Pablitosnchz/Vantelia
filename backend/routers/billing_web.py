"""Endpoints: seccion billing_web (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

import asyncio
import copy
import base64
import csv
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import shutil
import sqlite3
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import httpx
from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

import onboarding_utils
from api_models import *  # noqa: F401,F403
from backend import (
    agenda,
    appstate,
    billing,
    booking,
    chat,
    clients,
    crm,
    db,
    demo_agenda,
    emailing,
    growth,
    instagram,
    messaging,
    onboarding,
    outreach,
    portal,
    rag,
    security,
    settings,
    stripe_gateway,
    textnorm,
    tiktok,
    timeutils,
    voice,
    wa_capture,
    whatsapp,
)
from backend.main import app

@app.post("/subscription/checkout", response_model=SubscriptionCheckoutResponse)
async def public_subscription_checkout(
    data: SubscriptionCheckoutPayload,
    request: Request,
) -> SubscriptionCheckoutResponse:
    plan = data.plan.strip().lower()
    price_id, billing_period = stripe_gateway._stripe_price_for_plan(plan, data.billing_period)
    stripe_gateway._stripe_init()

    marketing_url = settings.MARKETING_SITE_URL.rstrip("/") or "https://www.vantelia.es"
    success_url = (
        f"{marketing_url}/bienvenido/?plan={quote(plan)}&period={quote(billing_period)}"
        "&session={CHECKOUT_SESSION_ID}"
    )
    cancel_url = f"{marketing_url}/planes/?checkout=cancel&plan={quote(plan)}"

    try:
        session = stripe_gateway.stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=f"public:{plan}:{billing_period}",
            metadata={"source": "public_plans", "plan": plan, "billing_period": billing_period},
            subscription_data={
                "metadata": {"source": "public_plans", "plan": plan, "billing_period": billing_period},
            },
            custom_fields=stripe_gateway._stripe_onboarding_custom_fields(),
            billing_address_collection="required",
            phone_number_collection={"enabled": True},
            tax_id_collection={"enabled": True},
            payment_method_collection="if_required",
            allow_promotion_codes=True,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Error creando Stripe Checkout publico para plan=%s: %s", plan, exc)
        raise HTTPException(status_code=502, detail="No se pudo iniciar el proceso de pago.") from exc

    return SubscriptionCheckoutResponse(url=session.url, session_id=session.id)


@app.get("/subscription/checkout/status", response_model=PublicCheckoutStatusResponse)
async def public_subscription_checkout_status(
    request: Request,
    session_id: str = "",
    session: str = "",
) -> PublicCheckoutStatusResponse:
    checkout_session_id = session_id or session
    session_object = billing._retrieve_public_checkout_session(checkout_session_id)
    state_value, cliente_id, message = billing._public_checkout_session_state(session_object)
    base_url = textnorm._public_base_url(request)
    portal_enter_url = (
        f"{base_url}/subscription/checkout/enter?session_id={quote(checkout_session_id, safe='')}"
        if state_value == "ready"
        else ""
    )
    return PublicCheckoutStatusResponse(
        status=state_value,
        message=message,
        cliente_id=cliente_id,
        portal_enter_url=portal_enter_url,
    )


@app.get("/subscription/checkout/enter", include_in_schema=False)
async def public_subscription_checkout_enter(
    session_id: str = "",
    session: str = "",
) -> Response:
    checkout_session_id = session_id or session
    session_object = billing._retrieve_public_checkout_session(checkout_session_id)
    state_value, cliente_id, _ = billing._public_checkout_session_state(session_object)
    if state_value != "ready" or not cliente_id:
        return RedirectResponse(url=f"/acceso?checkout_status={quote(state_value)}", status_code=303)
    user = billing._portal_user_for_checkout_client(cliente_id, session_object)
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (timeutils._utc_now_iso(), user["id"]),
        )
        connection.commit()
    raw_token = security._create_auth_session(user["id"])
    response = RedirectResponse(url="/portal?welcome=1", status_code=303)
    security._set_portal_cookie(response, raw_token)
    return response


@app.post("/auth/subscription/portal", response_model=SubscriptionPortalResponse)
async def auth_subscription_portal(
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> SubscriptionPortalResponse:
    cid = portal._portal_client_id_or_403(user, cliente_id)
    sub = clients._client_subscription(cid)
    if not sub.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="Aún no tienes una suscripción activa con pago.")
    stripe_gateway._stripe_init()
    base_url = textnorm._public_base_url(request)
    try:
        session = stripe_gateway.stripe.billing_portal.Session.create(
            customer=sub["stripe_customer_id"],
            return_url=f"{base_url}/portal",
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Error creando Stripe Billing Portal para %s: %s", cid, exc)
        raise HTTPException(status_code=502, detail="No se pudo abrir el portal de facturación.") from exc
    return SubscriptionPortalResponse(url=session.url)




@app.post("/stripe/connect/webhook", include_in_schema=False)
async def stripe_connect_webhook(request: Request) -> Dict[str, Any]:
    if not stripe_gateway._stripe_configured() or not settings.STRIPE_CONNECT_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe Connect webhook no configurado.")
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe_gateway.stripe.Webhook.construct_event(payload, signature, settings.STRIPE_CONNECT_WEBHOOK_SECRET)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Webhook Connect invalido.") from exc
    event_id = str(textnorm._object_get(event, "id", "") or "")
    event_type = str(textnorm._object_get(event, "type", "") or "")
    account_id = str(textnorm._object_get(event, "account", "") or "")
    data = textnorm._object_get(textnorm._object_get(event, "data", {}), "object", {}) or {}
    metadata = textnorm._object_get(data, "metadata", {}) or {}
    payment_id = str(textnorm._object_get(metadata, "payment_id", "") or "")
    session_id = str(textnorm._object_get(data, "id", "") or "") if event_type.startswith("checkout.session.") else ""
    with db._get_db_connection() as connection:
        account_row = connection.execute(
            "SELECT cliente_id FROM client_payment_accounts WHERE stripe_account_id=?", (account_id,)
        ).fetchone()
        if not account_row:
            raise HTTPException(status_code=404, detail="Cuenta Connect no reconocida.")
        cliente_id = account_row["cliente_id"]
        if connection.execute("SELECT 1 FROM customer_payment_events WHERE stripe_event_id=?", (event_id,)).fetchone():
            return {"received": True, "duplicate": True}
        payment = None
        if payment_id:
            payment = connection.execute(
                "SELECT * FROM customer_payments WHERE id=? AND cliente_id=?", (payment_id, cliente_id)
            ).fetchone()
        if not payment and session_id:
            payment = connection.execute(
                "SELECT * FROM customer_payments WHERE stripe_checkout_session_id=? AND cliente_id=?",
                (session_id, cliente_id),
            ).fetchone()
        if not payment and event_type == "charge.refunded":
            payment_intent_id = str(textnorm._object_get(data, "payment_intent", "") or "")
            if payment_intent_id:
                payment = connection.execute(
                    "SELECT * FROM customer_payments WHERE stripe_payment_intent_id=? AND cliente_id=?",
                    (payment_intent_id, cliente_id),
                ).fetchone()
        connection.execute(
            """
            INSERT INTO customer_payment_events (stripe_event_id, cliente_id, payment_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, cliente_id, payment["id"] if payment else payment_id, event_type, json.dumps(data, ensure_ascii=False, default=str), timeutils._utc_now_iso()),
        )
        if event_type == "account.updated":
            connection.execute(
                """
                UPDATE client_payment_accounts SET charges_enabled=?, payouts_enabled=?,
                    details_submitted=?, updated_at=? WHERE cliente_id=?
                """,
                (
                    int(bool(textnorm._object_get(data, "charges_enabled", False))),
                    int(bool(textnorm._object_get(data, "payouts_enabled", False))),
                    int(bool(textnorm._object_get(data, "details_submitted", False))),
                    timeutils._utc_now_iso(), cliente_id,
                ),
            )
        if payment:
            now = timeutils._utc_now_iso()
            new_status = payment["status"]
            paid_at = payment["paid_at"] or ""
            payment_intent = payment["stripe_payment_intent_id"] or ""
            if event_type == "checkout.session.completed" and str(textnorm._object_get(data, "payment_status", "")) == "paid":
                new_status, paid_at = "paid", now
                payment_intent = str(textnorm._object_get(data, "payment_intent", "") or "")
            elif event_type in {"checkout.session.expired", "payment_intent.payment_failed"}:
                new_status = "failed"
            elif event_type == "charge.refunded":
                refunded = int(textnorm._object_get(data, "amount_refunded", 0) or 0)
                total = int(textnorm._object_get(data, "amount", 0) or payment["amount_cents"])
                new_status = "refunded" if refunded >= total else "partially_refunded"
            connection.execute(
                "UPDATE customer_payments SET status=?, paid_at=?, stripe_payment_intent_id=?, updated_at=? WHERE id=?",
                (new_status, paid_at, payment_intent, now, payment["id"]),
            )
            if new_status == "paid" and payment["booking_id"]:
                booking_row = connection.execute("SELECT * FROM bookings WHERE id=? AND cliente_id=?", (payment["booking_id"], cliente_id)).fetchone()
                if booking_row:
                    policy = booking._payment_policy(cliente_id, payment["service_id"] or "")
                    if policy["confirm_booking_on_paid"] and booking_row["status"] == "pending_review":
                        connection.execute(
                            "UPDATE bookings SET status='confirmed', confirmed_at=? WHERE id=?",
                            (now, booking_row["id"]),
                        )
                        connection.execute(
                            "INSERT INTO booking_audit (booking_id, cliente_id, event_type, payload_json, created_at) VALUES (?, ?, 'booking_confirmed_by_payment', ?, ?)",
                            (booking_row["id"], cliente_id, json.dumps({"payment_id": payment["id"]}), now),
                        )
            connection.commit()
        else:
            connection.commit()
    return {"received": True}


@app.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    if not stripe_gateway._stripe_configured():
        raise HTTPException(status_code=503, detail="Stripe no configurado.")
    if not settings.STRIPE_WEBHOOK_SECRET and not settings.STRIPE_CONNECT_WEBHOOK_SECRET:
        settings.logger.error("Stripe webhook recibido pero STRIPE_WEBHOOK_SECRET no está configurado; rechazando por seguridad.")
        raise HTTPException(status_code=503, detail="Stripe webhook secret no configurado.")
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    if not sig_header:
        settings.logger.warning("Stripe webhook recibido sin cabecera stripe-signature; rechazando.")
        raise HTTPException(status_code=400, detail="Falta firma del webhook.")
    try:
        event = stripe_gateway._construct_stripe_webhook_event(payload, sig_header)
    except stripe_gateway.stripe.error.SignatureVerificationError as exc:
        settings.logger.warning("Stripe webhook firma inválida: %s", exc)
        raise HTTPException(status_code=400, detail="Firma del webhook inválida.") from exc
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Stripe webhook payload error: %s", exc)
        raise HTTPException(status_code=400, detail="Webhook payload inválido.") from exc

    event_type = event.get("type") if isinstance(event, dict) else event["type"]
    data_object = (event.get("data") if isinstance(event, dict) else event["data"]).get("object", {})

    try:
        if event_type == "checkout.session.completed":
            if booking.process_booking_payment_webhook(data_object):
                return {"received": True}
            cid = (data_object.get("metadata") or {}).get("cliente_id") or data_object.get("client_reference_id")
            plan = (data_object.get("metadata") or {}).get("plan") or settings.PLAN_DEFAULT
            billing_period = (data_object.get("metadata") or {}).get("billing_period") or "monthly"
            customer_id = data_object.get("customer") or ""
            sub_id = data_object.get("subscription") or ""
            source = (data_object.get("metadata") or {}).get("source") or ""
            if source == "self_serve":
                user_id = (data_object.get("metadata") or {}).get("user_id") or ""
                ref = str(data_object.get("client_reference_id") or "")
                if not user_id and ref.startswith("self_serve:"):
                    user_id = ref.split(":", 1)[1]
                if user_id and plan in settings.SELF_SERVE_PLANS and plan != "free":
                    db.db_set_subscription_from_stripe(
                        user_id=user_id,
                        plan_slug=plan,
                        stripe_customer_id=customer_id,
                        stripe_subscription_id=sub_id,
                        status="active",
                        current_period_start=timeutils._utc_now().isoformat(),
                    )
                    settings.logger.info("Self-serve subscription activada user=%s plan=%s", user_id, plan)
                else:
                    settings.logger.warning(
                        "Self-serve checkout completed sin user_id/plan validos: user=%s plan=%s",
                        user_id, plan,
                    )
                return {"received": True}
            if source == "public_plans" and str(cid or "").startswith("public:"):
                session_id = str(data_object.get("id") or "").strip()
                existing_cid = stripe_gateway._find_client_by_stripe_id(
                    customer_id=customer_id, subscription_id=sub_id, session_id=session_id
                )
                if existing_cid:
                    settings.logger.info(
                        "checkout.session.completed duplicado ignorado: cliente=%s session=%s",
                        existing_cid, session_id,
                    )
                elif not stripe_gateway._claim_stripe_session(session_id):
                    settings.logger.info(
                        "checkout.session.completed en curso, reintento ignorado: session=%s",
                        session_id,
                    )
                else:
                    # Onboarding lento (scrape + indexado): correr en background y
                    # responder 200 a Stripe para evitar reintentos que generan duplicados.
                    def _run_onboarding_bg(
                        data_object=data_object, plan=plan, billing_period=billing_period,
                        customer_id=customer_id, sub_id=sub_id, session_id=session_id, request=request,
                    ) -> None:
                        try:
                            new_cid = billing._create_client_from_public_checkout(
                                data_object,
                                request=request,
                                plan=plan,
                                billing_period=billing_period,
                                customer_id=customer_id,
                                subscription_id=sub_id,
                            )
                            stripe_gateway._mark_stripe_session(session_id, status="done", cliente_id=new_cid or "")
                            portal._try_record_analytics_event(
                                {
                                    "event": "checkout_completed",
                                    "event_source": "stripe_webhook",
                                    "cliente_id": new_cid or "",
                                    "plan": plan,
                                    "billing_period": billing_period,
                                    "checkout_session_id": session_id,
                                    "checkout_status": "completed",
                                },
                                request,
                            )
                        except Exception as exc:  # noqa: BLE001
                            settings.logger.exception(
                                "Onboarding async fallido session=%s: %s", session_id, exc
                            )
                            stripe_gateway._mark_stripe_session(session_id, status="failed", error=str(exc))
                    background_tasks.add_task(_run_onboarding_bg)
            elif cid and cid in appstate.CONFIG_CLIENTES:
                billing._set_client_subscription(
                    cid,
                    plan=plan,
                    status="active",
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=sub_id,
                    billing_period=billing_period,
                    started_at=timeutils._utc_now().isoformat(),
                )
                portal._try_record_analytics_event(
                    {
                        "event": "checkout_completed",
                        "event_source": "stripe_webhook",
                        "cliente_id": cid,
                        "plan": plan,
                        "billing_period": billing_period,
                        "checkout_session_id": str(data_object.get("id") or ""),
                        "checkout_status": "completed",
                    },
                    request,
                )
                settings.logger.info("Suscripción activada para %s · plan=%s", cid, plan)
        elif event_type == "checkout.session.expired":
            if booking.process_booking_payment_expired_webhook(data_object):
                return {"received": True}
        elif event_type in {"customer.subscription.updated", "customer.subscription.created"}:
            sub_id = data_object.get("id", "")
            status_str = data_object.get("status", "")
            current_period_end = data_object.get("current_period_end")
            current_period_start = data_object.get("current_period_start")
            cancel_at_period_end_flag = bool(data_object.get("cancel_at_period_end"))
            cid = (data_object.get("metadata") or {}).get("cliente_id")
            plan = (data_object.get("metadata") or {}).get("plan")
            # Self-serve first: match by stripe_subscription_id in subscriptions table.
            with db._get_db_connection() as _conn_ss:
                _conn_ss.row_factory = sqlite3.Row
                _ss_row = _conn_ss.execute(
                    "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?", (sub_id,)
                ).fetchone()
            if _ss_row:
                period_end_iso = (
                    datetime.fromtimestamp(int(current_period_end), tz=timezone.utc).isoformat()
                    if current_period_end else (_ss_row["current_period_end"] or "")
                )
                period_start_iso = (
                    datetime.fromtimestamp(int(current_period_start), tz=timezone.utc).isoformat()
                    if current_period_start else (_ss_row["current_period_start"] or "")
                )
                ss_plan = plan if plan in settings.SELF_SERVE_PLANS else (_ss_row["plan"] or "free")
                db.db_set_subscription_from_stripe(
                    user_id=_ss_row["user_id"],
                    plan_slug=ss_plan,
                    stripe_customer_id=_ss_row["stripe_customer_id"] or "",
                    stripe_subscription_id=sub_id,
                    status=status_str or "active",
                    current_period_start=period_start_iso,
                    current_period_end=period_end_iso,
                    cancel_at_period_end=cancel_at_period_end_flag,
                )
                settings.logger.info("Self-serve subscription %s user=%s status=%s", event_type, _ss_row["user_id"], status_str)
                return {"received": True}
            if not cid:
                # Buscar por subscription_id
                for candidate_cid, cfg in appstate.CONFIG_CLIENTES.items():
                    if (cfg.get("subscription") or {}).get("stripe_subscription_id") == sub_id:
                        cid = candidate_cid
                        break
            if cid and cid in appstate.CONFIG_CLIENTES:
                renews_at = ""
                if current_period_end:
                    renews_at = datetime.fromtimestamp(int(current_period_end), tz=timezone.utc).isoformat()
                fields = {"status": status_str or "active", "stripe_subscription_id": sub_id}
                if renews_at:
                    fields["renews_at"] = renews_at
                if plan and settings._normalize_plan_slug(plan) in settings.PLAN_VALID:
                    fields["plan"] = settings._normalize_plan_slug(plan)
                billing._set_client_subscription(cid, **fields)
                settings.logger.info("Suscripción actualizada %s · status=%s", cid, status_str)
        elif event_type == "customer.subscription.deleted":
            sub_id = data_object.get("id", "")
            with db._get_db_connection() as _conn_ss:
                _conn_ss.row_factory = sqlite3.Row
                _ss_row = _conn_ss.execute(
                    "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?", (sub_id,)
                ).fetchone()
            if _ss_row:
                db.db_set_subscription_from_stripe(
                    user_id=_ss_row["user_id"],
                    plan_slug="free",
                    stripe_customer_id=_ss_row["stripe_customer_id"] or "",
                    stripe_subscription_id="",
                    status="canceled",
                )
                settings.logger.info("Self-serve subscription cancelada user=%s", _ss_row["user_id"])
                return {"received": True}
            cid_target = None
            for candidate_cid, cfg in appstate.CONFIG_CLIENTES.items():
                if (cfg.get("subscription") or {}).get("stripe_subscription_id") == sub_id:
                    cid_target = candidate_cid
                    break
            if cid_target:
                billing._set_client_subscription(
                    cid_target,
                    status="canceled",
                    canceled_at=timeutils._utc_now().isoformat(),
                )
                settings.logger.info("Suscripción cancelada %s", cid_target)
        elif event_type == "invoice.payment_failed":
            sub_id = str(data_object.get("subscription") or "")
            customer_id = str(data_object.get("customer") or "")
            customer_email = str(data_object.get("customer_email") or "")
            attempt_count = int(data_object.get("attempt_count") or 1)
            next_payment_attempt = data_object.get("next_payment_attempt")
            hosted_invoice_url = str(data_object.get("hosted_invoice_url") or "")
            amount_due_cents = int(data_object.get("amount_due") or 0)
            amount_due_eur = f"{amount_due_cents / 100:.2f}" if amount_due_cents else "-"
            next_iso = ""
            if next_payment_attempt:
                next_iso = datetime.fromtimestamp(int(next_payment_attempt), tz=timezone.utc).isoformat()
            cid_target = stripe_gateway._find_client_by_stripe_id(customer_id=customer_id, subscription_id=sub_id)
            if cid_target and cid_target in appstate.CONFIG_CLIENTES:
                cfg = appstate.CONFIG_CLIENTES.get(cid_target) or {}
                sub_cfg = cfg.get("subscription") or {}
                billing._set_client_subscription(
                    cid_target,
                    status="past_due",
                    last_payment_failed_at=timeutils._utc_now().isoformat(),
                    last_payment_failed_invoice_url=hosted_invoice_url,
                )
                emailing._send_payment_failed_emails(
                    cliente_id=cid_target,
                    customer_email=customer_email or sub_cfg.get("contacto_email", "") or "",
                    company_name=cfg.get("nombre", "") or cid_target,
                    plan=sub_cfg.get("plan", "") or cfg.get("plan", "") or settings.PLAN_DEFAULT,
                    amount_due_eur=amount_due_eur,
                    attempt_count=attempt_count,
                    next_attempt_iso=next_iso,
                    hosted_invoice_url=hosted_invoice_url,
                    customer_id=customer_id,
                    subscription_id=sub_id,
                )
                settings.logger.warning(
                    "invoice.payment_failed cliente=%s sub=%s intento=%s importe=%s",
                    cid_target, sub_id, attempt_count, amount_due_eur,
                )
            else:
                settings.logger.warning(
                    "invoice.payment_failed sin cliente asociado: customer=%s sub=%s",
                    customer_id, sub_id,
                )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Error procesando evento Stripe %s: %s", event_type, exc)

    return {"received": True}


