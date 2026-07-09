"""Suscripciones self-serve: planes, checkout, sync Stripe (refactor F3)."""
from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, List, Tuple

import copy
from fastapi import HTTPException, Request


import onboarding_utils
from api_models import BillingPlanTier, BillingSubscriptionPublic, SubscriptionFeatures, SubscriptionPublic, SubscriptionUsage
from backend import agenda, booking, portal, rag, appstate, clients, commerce, db, emailing, onboarding, security, settings, stripe_gateway, textnorm, timeutils

def _send_checkout_admin_notification(
    *,
    customer_email: str,
    customer_name: str,
    customer_phone: str,
    company_name: str,
    cliente_id: str,
    ai_name: str,
    website_url: str,
    plan: str,
    billing_period: str,
    customer_id: str,
    subscription_id: str,
    session_id: str,
) -> None:
    if not settings.CONSULTA_NOTIFICATION_EMAIL:
        return
    plan_label = clients._plan_limits(plan).get("label") or plan.title()
    period_label = "mensual" if billing_period == "monthly" else "anual"
    price_eur = clients._plan_limits(plan).get("price_eur") or "-"
    subject = f"Nueva alta Vantelia: {company_name} ({plan_label})"
    text_body = (
        f"Nuevo cliente dado de alta automaticamente desde Stripe Checkout.\n\n"
        f"Empresa: {company_name}\n"
        f"Cliente interno: {cliente_id}\n"
        f"IA: {ai_name}\n"
        f"Web: {website_url}\n\n"
        f"Contacto:\n"
        f"  Nombre: {customer_name or '-'}\n"
        f"  Email:  {customer_email or '-'}\n"
        f"  Telefono: {customer_phone or '-'}\n\n"
        f"Suscripcion:\n"
        f"  Plan: {plan_label} ({period_label}) - {price_eur} EUR/mes\n"
        f"  Stripe customer: {customer_id or '-'}\n"
        f"  Stripe subscription: {subscription_id or '-'}\n"
        f"  Stripe session: {session_id or '-'}\n"
        f"  Condiciones: sin permanencia. IVA no incluido.\n\n"
        f"Panel: https://app.vantelia.es/dashboard\n"
    )
    html_body = (
        f"<h2>Nueva alta Vantelia</h2>"
        f"<p>Cliente dado de alta desde Stripe Checkout.</p>"
        f"<table cellpadding='6' style='border-collapse:collapse'>"
        f"<tr><td><strong>Empresa</strong></td><td>{escape(company_name)}</td></tr>"
        f"<tr><td><strong>Cliente interno</strong></td><td>{escape(cliente_id)}</td></tr>"
        f"<tr><td><strong>IA</strong></td><td>{escape(ai_name)}</td></tr>"
        f"<tr><td><strong>Web</strong></td><td>{escape(website_url)}</td></tr>"
        f"<tr><td><strong>Contacto</strong></td><td>{escape(customer_name or '-')}<br>{escape(customer_email or '-')}<br>{escape(customer_phone or '-')}</td></tr>"
        f"<tr><td><strong>Plan</strong></td><td>{escape(str(plan_label))} ({escape(period_label)}) - {escape(str(price_eur))} EUR/mes</td></tr>"
        f"<tr><td><strong>Stripe customer</strong></td><td>{escape(customer_id or '-')}</td></tr>"
        f"<tr><td><strong>Stripe subscription</strong></td><td>{escape(subscription_id or '-')}</td></tr>"
        f"<tr><td><strong>Stripe session</strong></td><td>{escape(session_id or '-')}</td></tr>"
        f"<tr><td><strong>Condiciones</strong></td><td>Sin permanencia. IVA no incluido.</td></tr>"
        f"</table>"
        f"<p><a href='https://app.vantelia.es/dashboard'>Abrir panel admin</a></p>"
    )
    try:
        emailing._send_email_message(settings.CONSULTA_NOTIFICATION_EMAIL, subject, text_body, html_body)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudo enviar notificacion de alta a %s: %s", settings.CONSULTA_NOTIFICATION_EMAIL, exc)


def _require_active_subscription(cliente_id: str) -> None:
    sub = clients._client_subscription(cliente_id)
    if sub.get("status") in {"canceled", "past_due", "unpaid", "incomplete_expired"}:
        raise HTTPException(status_code=402, detail="La suscripcion de este cliente no esta activa.")


def _count_conversations_this_month(cliente_id: str) -> int:
    period_start, _ = clients._current_billing_period()
    try:
        with db._get_db_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT session_id) FROM chat_messages "
                "WHERE cliente_id = ? AND created_at >= ?",
                (cliente_id, period_start),
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def _timestamp_to_iso(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _refresh_subscription_from_stripe(cliente_id: str, sub: Dict[str, Any]) -> Dict[str, Any]:
    subscription_id = str(sub.get("stripe_subscription_id") or "").strip()
    if not subscription_id or not stripe_gateway._stripe_configured():
        return sub
    try:
        stripe_gateway._stripe_init()
        stripe_subscription = stripe_gateway.stripe.Subscription.retrieve(subscription_id)
    except Exception as exc:
        settings.logger.warning("No se pudo sincronizar suscripcion Stripe %s para %s: %s", subscription_id, cliente_id, exc)
        return sub

    fields: Dict[str, Any] = {}
    status = str(textnorm._object_get(stripe_subscription, "status", "") or "")
    renews_at = _timestamp_to_iso(textnorm._object_get(stripe_subscription, "current_period_end"))
    started_at = _timestamp_to_iso(textnorm._object_get(stripe_subscription, "start_date"))
    canceled_at = _timestamp_to_iso(textnorm._object_get(stripe_subscription, "canceled_at"))

    if status and status != sub.get("status"):
        fields["status"] = status
    if renews_at and renews_at != sub.get("renews_at"):
        fields["renews_at"] = renews_at
    if started_at and not sub.get("started_at"):
        fields["started_at"] = started_at
    if canceled_at and canceled_at != sub.get("canceled_at"):
        fields["canceled_at"] = canceled_at

    if fields:
        _set_client_subscription(cliente_id, **fields)
        next_sub = dict(sub)
        next_sub.update(fields)
        return next_sub
    return sub


def _build_subscription_public(cliente_id: str, *, admin_override: bool = False) -> SubscriptionPublic:
    sub = clients._client_subscription(cliente_id)
    if not sub.get("lifetime"):
        sub = _refresh_subscription_from_stripe(cliente_id, sub)
    plan = sub["plan"]
    effective_plan = "business" if admin_override else plan
    limits = clients._plan_limits(effective_plan)
    actual_limits = clients._plan_limits(plan)
    period_start, period_end = clients._current_billing_period()
    usage = SubscriptionUsage(
        conversations=_count_conversations_this_month(cliente_id),
        conversations_limit=limits.get("monthly_conversations"),
        bookings=booking._count_bookings_this_month(cliente_id),
        bookings_limit=limits.get("monthly_bookings"),
        period_start=period_start,
        period_end=period_end,
    )
    features = SubscriptionFeatures(
        branding_customization=bool(limits.get("branding_customization")),
        whatsapp_enabled=bool(limits.get("whatsapp_enabled")),
        csv_export=bool(limits.get("csv_export")),
        multi_branch=bool(limits.get("multi_branch")),
        crm_integration=bool(limits.get("crm_integration")),
        show_powered_by=bool(limits.get("show_powered_by")),
        max_professionals=limits.get("max_professionals"),
        max_users=limits.get("max_users"),
        max_extra_documents=limits.get("max_extra_documents"),
    )
    available = [
        {
            "plan": pid,
            "label": settings.PLAN_LIMITS[pid]["label"],
            "price_eur": settings.PLAN_LIMITS[pid]["price_eur"],
            "is_current": pid == plan,
        }
        for pid in ("starter", "pro", "business")
    ]
    return SubscriptionPublic(
        plan=plan,
        plan_label=str(actual_limits.get("label") or plan.title()),
        effective_plan=effective_plan,
        effective_plan_label=str(limits.get("label") or effective_plan.title()),
        admin_override=admin_override,
        status=sub["status"],
        price_eur=int(actual_limits.get("price_eur") or 0),
        lifetime=bool(sub.get("lifetime")),
        renews_at=sub["renews_at"],
        started_at=sub["started_at"],
        canceled_at=sub["canceled_at"],
        stripe_customer_id=sub["stripe_customer_id"],
        stripe_subscription_id=sub["stripe_subscription_id"],
        features=features,
        usage=usage,
        available_plans=available,
    )


def _set_client_subscription(cliente_id: str, **fields: Any) -> None:
    next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
    config = next_configs.get(cliente_id)
    if not config:
        raise HTTPException(status_code=404, detail="Cliente no configurado")
    sub = dict(config.get("subscription") or {})
    for key, value in fields.items():
        if value is None:
            sub.pop(key, None)
        else:
            sub[key] = value
    config["subscription"] = sub
    if "plan" in fields and settings._normalize_plan_slug(str(fields.get("plan") or "")) in settings.PLAN_VALID:
        config["plan"] = settings._normalize_plan_slug(str(fields["plan"]))
    clients._persist_configs_to_disk(next_configs)
    clients._update_runtime_configs(next_configs)


def _public_checkout_customer_details(session_object: Dict[str, Any]) -> Dict[str, str]:
    customer_details = session_object.get("customer_details") or {}
    return {
        "email": str(customer_details.get("email") or session_object.get("customer_email") or "").strip(),
        "name": str(customer_details.get("name") or "").strip(),
        "phone": str(customer_details.get("phone") or "").strip(),
    }


def _retrieve_public_checkout_session(session_id: str) -> Any:
    session_id = str(session_id or "").strip()
    if not session_id or not settings.SESSION_ID_PATTERN.match(session_id) or not session_id.startswith("cs_"):
        raise HTTPException(status_code=400, detail="Sesion de Stripe no valida.")
    stripe_gateway._stripe_init()
    try:
        return stripe_gateway.stripe.checkout.Session.retrieve(session_id)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudo recuperar Stripe Checkout session %s: %s", session_id, exc)
        raise HTTPException(status_code=404, detail="No se ha encontrado la sesion de Stripe.") from exc


def _public_checkout_session_state(session_object: Any) -> Tuple[str, str, str]:
    session_id = str(session_object.get("id") or "").strip()
    metadata = session_object.get("metadata") or {}
    source = str(metadata.get("source") or "").strip()
    client_reference_id = str(session_object.get("client_reference_id") or "")
    if source != "public_plans" or not client_reference_id.startswith("public:"):
        raise HTTPException(status_code=403, detail="Esta sesion no corresponde a un alta publica.")

    status_value = str(session_object.get("status") or "").strip()
    payment_status = str(session_object.get("payment_status") or "").strip()
    if status_value != "complete" or payment_status not in {"paid", "no_payment_required"}:
        return "pending", "", "Stripe aun no ha confirmado el alta."

    customer_id = str(session_object.get("customer") or "")
    subscription_id = str(session_object.get("subscription") or "")
    cliente_id = stripe_gateway._find_client_by_stripe_id(
        customer_id=customer_id,
        subscription_id=subscription_id,
        session_id=session_id,
    )
    sessions = stripe_gateway._load_stripe_sessions()
    local_entry = sessions.get(session_id) or {}
    if not cliente_id and local_entry.get("cliente_id"):
        cliente_id = str(local_entry.get("cliente_id") or "")
    if cliente_id and cliente_id in appstate.CONFIG_CLIENTES:
        return "ready", cliente_id, "Tu portal ya esta listo."
    if local_entry.get("status") == "failed":
        return "failed", "", "El alta automatica ha fallado. Soporte revisara tu caso."
    return "processing", "", "Estamos creando tu asistente y tu usuario del portal."


def _portal_user_for_checkout_client(cliente_id: str, session_object: Any) -> sqlite3.Row:
    customer = _public_checkout_customer_details(session_object)
    customer_email = textnorm._normalize_email(customer.get("email", ""))
    if customer_email:
        user = security._get_user_by_email(customer_email)
        if user and user["is_active"] and user["role"] == "client":
            if user["cliente_id"] != cliente_id:
                user = security._assign_client_user_to_cliente(user["id"], cliente_id)
            return user
    users = security._list_users(role="client", cliente_id=cliente_id, include_inactive=False)
    if users:
        return users[0]
    raise HTTPException(status_code=409, detail="El cliente existe, pero aun no hay usuario de portal activo.")


def _create_client_from_public_checkout(
    session_object: Dict[str, Any],
    *,
    request: Request,
    plan: str,
    billing_period: str,
    customer_id: str,
    subscription_id: str,
) -> str:
    session_id = str(session_object.get("id") or "").strip()
    existing_cid = stripe_gateway._find_client_by_stripe_id(
        customer_id=customer_id, subscription_id=subscription_id, session_id=session_id
    )
    if existing_cid:
        settings.logger.info(
            "checkout.session.completed ignorado (idempotente): cliente=%s session=%s sub=%s",
            existing_cid, session_id, subscription_id,
        )
        return existing_cid
    fields = stripe_gateway._stripe_custom_field_values(session_object)
    customer = _public_checkout_customer_details(session_object)
    website_url = fields.get("website", "")
    company_name = fields.get("empresa") or customer.get("name") or customer.get("email") or "Cliente Vantelia"
    ai_name = fields.get("ianame") or "Clara"

    if not website_url:
        raise RuntimeError("Stripe Checkout no incluyo la web del cliente.")
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY no configurada; no se puede ejecutar alta express.")

    cliente_id = onboarding._unique_cliente_id(company_name)
    result = onboarding_utils.run_onboarding(
        website_url=website_url,
        api_key=settings.OPENAI_API_KEY,
        nombre_bot=ai_name,
        tono="Profesional y cercano",
        idioma="Espanol",
        max_paginas=12,
    )
    payload = portal._payload_from_alta_express(
        cliente_id=cliente_id,
        result=result,
        nombre_bot=ai_name,
        tono="Profesional y cercano",
        idioma="Espanol",
        color="#00b1d9",
        booking_enabled=True,
        booking_timezone=settings.DEFAULT_TIMEZONE,
    )
    payload.contacto_email = customer.get("email", "")
    payload.contacto_telefono = customer.get("phone", "")
    save_result = portal._save_admin_client_payload(cliente_id, payload, request)
    rag._seed_qa_from_onboarding(cliente_id, result)
    agenda._sync_services_from_info(cliente_id, result.info_txt, deactivate_missing=True)
    commerce._seed_commerce_from_info(cliente_id, result.info_txt)
    agenda._ensure_default_employees_for_all_clients()
    _set_client_subscription(
        cliente_id,
        plan=plan,
        status="active",
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        stripe_checkout_session_id=session_id,
        billing_period=billing_period,
        started_at=timeutils._utc_now().isoformat(),
    )

    customer_email = customer.get("email", "")
    temporary_password = secrets.token_urlsafe(12)
    if customer_email:
        try:
            existing_user = security._get_user_by_email(customer_email)
            if existing_user:
                if existing_user["role"] == "client" and existing_user["cliente_id"] != cliente_id:
                    security._assign_client_user_to_cliente(existing_user["id"], cliente_id)
                temporary_password = ""
            else:
                security._create_user(
                    email=customer_email,
                    password=temporary_password,
                    role="client",
                    display_name=customer.get("name") or company_name,
                    cliente_id=cliente_id,
                )
            emailing._send_checkout_welcome_email(
                to_email=customer_email,
                display_name=customer.get("name") or company_name,
                company_name=company_name,
                cliente_id=cliente_id,
                ai_name=ai_name,
                plan=plan,
                billing_period=billing_period,
                subscription_id=subscription_id,
                temporary_password=temporary_password or "Usa tu contrasena actual",
                request=request,
            )
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("Cliente %s creado, pero no se pudo crear/enviar acceso portal: %s", cliente_id, exc)

    _send_checkout_admin_notification(
        customer_email=customer_email,
        customer_name=customer.get("name") or "",
        customer_phone=customer.get("phone") or "",
        company_name=company_name,
        cliente_id=cliente_id,
        ai_name=ai_name,
        website_url=website_url,
        plan=plan,
        billing_period=billing_period,
        customer_id=customer_id,
        subscription_id=subscription_id,
        session_id=session_id,
    )

    settings.logger.info(
        "Alta express automatica completada desde Stripe: cliente=%s plan=%s snippet=%s",
        cliente_id,
        plan,
        save_result.install_snippet,
    )
    return cliente_id


def _require_pro_plan(user: sqlite3.Row) -> None:
    plan = security._user_plan(user)
    if plan in {"free", ""}:
        raise HTTPException(
            status_code=402,
            detail="Live Chat requiere plan Pro o superior. Actualiza tu plan para usar esta funcion.",
        )


def _serialize_billing_subscription(sub: sqlite3.Row) -> BillingSubscriptionPublic:
    if not sub:
        free = settings.SELF_SERVE_PLANS["free"]
        return BillingSubscriptionPublic(
            plan="free", status="active",
            messages_quota=int(free["messages_quota"]),
            messages_used=0,
            messages_remaining=int(free["messages_quota"]),
            cancel_at_period_end=False,
            current_period_start="", current_period_end="",
            stripe_customer_id="",
        )
    quota = int(sub["messages_quota"] or 0)
    used = int(sub["messages_used_period"] or 0)
    return BillingSubscriptionPublic(
        plan=sub["plan"] or "free",
        status=sub["status"] or "active",
        messages_quota=quota,
        messages_used=used,
        messages_remaining=max(0, quota - used),
        cancel_at_period_end=bool(sub["cancel_at_period_end"]),
        current_period_start=sub["current_period_start"] or "",
        current_period_end=sub["current_period_end"] or "",
        stripe_customer_id=sub["stripe_customer_id"] or "",
    )


def _build_plan_tiers(current_plan_slug: str) -> List[BillingPlanTier]:
    out: List[BillingPlanTier] = []
    for slug in ["free", "starter", "pro", "business"]:
        plan = settings.SELF_SERVE_PLANS[slug]
        limits = clients._plan_limits(slug)
        out.append(BillingPlanTier(
            slug=plan["slug"],
            label=plan["label"],
            price_monthly_eur=int(plan["price_monthly_eur"]),
            price_annual_eur=int(plan["price_annual_eur"]),
            messages_quota=int(plan["messages_quota"]),
            bookings_quota=limits.get("monthly_bookings"),
            features=list(plan["features"]),
            has_monthly_price_id=bool(plan["stripe_price_monthly"]),
            has_annual_price_id=bool(plan["stripe_price_annual"]),
            is_current=(slug == current_plan_slug),
        ))
    return out


