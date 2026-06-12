"""Pasarela Stripe: SDK, precios por plan, sesiones checkout y Connect v2 (refactor F3).

Unico modulo que importa el SDK stripe. Los tests parchean `stripe` con
fakes via el proxy de api.py.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException, Request

try:
    import stripe as _stripe_module
    stripe: Any = _stripe_module
except ImportError:
    stripe = None

from backend import appstate, clients, db, security, settings, textnorm, timeutils

def _stripe_configured() -> bool:
    return bool(stripe is not None and settings.STRIPE_SECRET_KEY)


def _stripe_init() -> None:
    if stripe is None:
        raise HTTPException(status_code=503, detail="Stripe no está disponible (instala el paquete 'stripe').")
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="STRIPE_SECRET_KEY no configurada.")
    stripe.api_key = settings.STRIPE_SECRET_KEY


def _stripe_price_for_plan(plan: str, billing_period: str = "monthly") -> Tuple[str, str]:
    normalized_plan = settings._normalize_plan_slug(plan)
    if normalized_plan not in settings.PLAN_VALID:
        raise HTTPException(status_code=400, detail="Plan no valido.")

    plan_def = settings._self_serve_plan(normalized_plan)
    normalized_period = str(billing_period or "monthly").strip().lower()
    if normalized_period in {"annual", "yearly", "year"}:
        price_id = plan_def.get("stripe_price_annual", "")
        period = "annual"
    elif normalized_period in {"monthly", "month", ""}:
        price_id = plan_def.get("stripe_price_monthly", "")
        period = "monthly"
    else:
        raise HTTPException(status_code=400, detail="Periodo de facturacion no valido.")

    if not price_id:
        env_suffix = "_ANNUAL" if period == "annual" else ""
        raise HTTPException(
            status_code=503,
            detail=f"STRIPE_PRICE_{normalized_plan.upper()}{env_suffix} no configurado.",
        )
    return price_id, period


def _stripe_onboarding_custom_fields() -> List[Dict[str, Any]]:
    return [
        {
            "key": "website",
            "label": {"type": "custom", "custom": "Web donde instalaremos la IA"},
            "type": "text",
            "text": {"maximum_length": 200, "minimum_length": 4},
            "optional": False,
        },
        {
            "key": "empresa",
            "label": {"type": "custom", "custom": "Nombre de tu empresa"},
            "type": "text",
            "text": {"maximum_length": 80, "minimum_length": 2},
            "optional": False,
        },
        {
            "key": "ianame",
            "label": {"type": "custom", "custom": "Nombre del asistente IA"},
            "type": "text",
            "text": {"maximum_length": 40, "minimum_length": 2},
            "optional": True,
        },
    ]


def _stripe_custom_field_values(session_object: Dict[str, Any]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for field in session_object.get("custom_fields") or []:
        key = str(field.get("key") or "").strip()
        text_value = ((field.get("text") or {}).get("value") or "").strip()
        if key and text_value:
            values[key] = text_value
    return values


_STRIPE_SESSIONS_FILE = settings.STORAGE_DIR / "stripe_sessions.json"


_STRIPE_SESSIONS_LOCK = threading.Lock()


def _load_stripe_sessions() -> Dict[str, Dict[str, Any]]:
    if not _STRIPE_SESSIONS_FILE.exists():
        return {}
    try:
        with _STRIPE_SESSIONS_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudo leer stripe_sessions.json: %s", exc)
        return {}


def _save_stripe_sessions(data: Dict[str, Dict[str, Any]]) -> None:
    settings.STORAGE_DIR.mkdir(exist_ok=True)
    tmp = _STRIPE_SESSIONS_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(_STRIPE_SESSIONS_FILE)


def _claim_stripe_session(session_id: str) -> bool:
    """Reserva session_id de Stripe en disco. False si ya fue vista (procesando/done/failed)."""
    if not session_id:
        return True
    with _STRIPE_SESSIONS_LOCK:
        sessions = _load_stripe_sessions()
        if session_id in sessions:
            return False
        sessions[session_id] = {
            "status": "processing",
            "ts": timeutils._utc_now().isoformat(),
        }
        _save_stripe_sessions(sessions)
    return True


def _mark_stripe_session(session_id: str, *, status: str, cliente_id: str = "", error: str = "") -> None:
    if not session_id:
        return
    with _STRIPE_SESSIONS_LOCK:
        sessions = _load_stripe_sessions()
        entry = dict(sessions.get(session_id) or {})
        entry["status"] = status
        entry["ts"] = timeutils._utc_now().isoformat()
        if cliente_id:
            entry["cliente_id"] = cliente_id
        if error:
            entry["error"] = error[:500]
        sessions[session_id] = entry
        _save_stripe_sessions(sessions)


def _find_client_by_stripe_id(
    *, customer_id: str = "", subscription_id: str = "", session_id: str = ""
) -> str:
    if not (customer_id or subscription_id or session_id):
        return ""
    for cid, cfg in appstate.CONFIG_CLIENTES.items():
        sub = cfg.get("subscription") or {}
        if subscription_id and sub.get("stripe_subscription_id") == subscription_id:
            return cid
        if customer_id and sub.get("stripe_customer_id") == customer_id:
            return cid
        if session_id and sub.get("stripe_checkout_session_id") == session_id:
            return cid
    return ""


def _stripe_connect_headers() -> Dict[str, str]:
    if not _stripe_connect_configured():
        raise HTTPException(status_code=503, detail="Stripe no configurado en el servidor.")
    return {
        "Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}",
        "Stripe-Version": settings.STRIPE_CONNECT_API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _stripe_connect_configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def _stripe_connect_request(method: str, path: str, *, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=25.0) as client:
            response = client.request(
                method,
                f"{settings.STRIPE_CONNECT_BASE_URL}{path}",
                headers=_stripe_connect_headers(),
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="No se pudo conectar con Stripe Connect.") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.is_error:
        message = (
            body.get("error", {}).get("message", "")
            if isinstance(body.get("error"), dict)
            else ""
        )
        settings.logger.error("Stripe Connect %s %s fallo (%s): %s", method, path, response.status_code, message)
        raise HTTPException(
            status_code=502,
            detail=message or "Stripe no pudo completar la operacion de conexion.",
        )
    return body


def _stripe_connected_account_row(cliente_id: str) -> Optional[sqlite3.Row]:
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM stripe_connected_accounts WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchone()


def _save_stripe_connected_account(
    cliente_id: str,
    owner_user_id: str,
    stripe_account_id: str,
    *,
    status_value: str = "pending",
    requirements_due: int = 0,
    last_error: str = "",
) -> None:
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO stripe_connected_accounts
                (cliente_id, owner_user_id, stripe_account_id, status,
                 requirements_due, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id) DO UPDATE SET
                owner_user_id = excluded.owner_user_id,
                stripe_account_id = excluded.stripe_account_id,
                status = excluded.status,
                requirements_due = excluded.requirements_due,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (
                cliente_id,
                owner_user_id,
                stripe_account_id,
                status_value,
                requirements_due,
                last_error,
                now_iso,
                now_iso,
            ),
        )
        connection.commit()


def _stripe_connect_requirement_count(account: Dict[str, Any]) -> int:
    requirements = account.get("requirements")
    if not isinstance(requirements, dict):
        return 0
    entries = requirements.get("entries")
    return len(entries) if isinstance(entries, list) else 0


def _stripe_connect_account_status(account: Dict[str, Any]) -> Tuple[str, int]:
    due = _stripe_connect_requirement_count(account)
    merchant = account.get("configuration", {}).get("merchant", {})
    card_payments = merchant.get("capabilities", {}).get("card_payments", {})
    capability_status = str(card_payments.get("status", "")).lower()
    if capability_status == "active" and due == 0:
        return "active", 0
    return ("requirements_due" if due else "pending"), due


def _stripe_connect_display_name(cliente_id: str) -> str:
    config = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    configured_name = str(config.get("nombre", "")).strip()
    if configured_name:
        return configured_name
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT nombre FROM clientes WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchone()
    return str(row["nombre"] or cliente_id).strip() if row else cliente_id


def _create_stripe_connected_account(user: sqlite3.Row) -> str:
    cliente_id = str(user["cliente_id"] or "")
    payload = {
        "contact_email": user["email"],
        "display_name": _stripe_connect_display_name(cliente_id),
        "dashboard": "full",
        "identity": {
            "country": settings.STRIPE_CONNECT_COUNTRY,
        },
        "configuration": {
            "merchant": {
                "capabilities": {
                    "card_payments": {"requested": True},
                },
            },
        },
        "defaults": {
            "currency": "eur",
            "responsibilities": {
                "fees_collector": "stripe",
                "losses_collector": "stripe",
            },
            "locales": ["es-ES"],
        },
        "include": ["configuration.merchant", "requirements"],
    }
    account = _stripe_connect_request("POST", "/accounts", payload=payload)
    account_id = str(account.get("id", ""))
    if not account_id:
        raise HTTPException(status_code=502, detail="Stripe no devolvio una cuenta conectada valida.")
    status_value, due = _stripe_connect_account_status(account)
    _save_stripe_connected_account(
        cliente_id,
        user["id"],
        account_id,
        status_value=status_value,
        requirements_due=due,
    )
    return account_id


def _stripe_connect_account_id(user: sqlite3.Row) -> str:
    cliente_id = str(user["cliente_id"] or "")
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Tu usuario no tiene un negocio asociado.")
    row = _stripe_connected_account_row(cliente_id)
    return str(row["stripe_account_id"]) if row else _create_stripe_connected_account(user)


def _stripe_connect_onboarding_url(user: sqlite3.Row, request: Request) -> str:
    account_id = _stripe_connect_account_id(user)
    base_url = textnorm._public_base_url(request)
    account_link = _stripe_connect_request(
        "POST",
        "/account_links",
        payload={
            "account": account_id,
            "use_case": {
                "type": "account_onboarding",
                "account_onboarding": {
                    "collection_options": {"fields": "eventually_due"},
                    "configurations": ["merchant"],
                    "return_url": f"{base_url}/auth/app/stripe-connect/return",
                    "refresh_url": f"{base_url}/auth/app/stripe-connect/refresh",
                },
            },
        },
    )
    onboarding_url = str(account_link.get("url", ""))
    if not onboarding_url:
        raise HTTPException(status_code=502, detail="Stripe no devolvio un enlace de conexion valido.")
    return onboarding_url


def _construct_stripe_webhook_event(payload: bytes, sig_header: str) -> Any:
    secrets_to_try = list(
        dict.fromkeys(secret for secret in (settings.STRIPE_WEBHOOK_SECRET, settings.STRIPE_CONNECT_WEBHOOK_SECRET) if secret)
    )
    last_error: Optional[Exception] = None
    for webhook_secret in secrets_to_try:
        try:
            return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except stripe.error.SignatureVerificationError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("Stripe webhook secret no configurado.")




def _save_connect_account(cliente_id: str, account: Any) -> str:
    account_id = str(textnorm._object_get(account, "id", "") or "")
    if not account_id:
        raise HTTPException(status_code=502, detail="Stripe no devolvio una cuenta Connect valida.")
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_payment_accounts
                (cliente_id, stripe_account_id, charges_enabled, payouts_enabled, details_submitted, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id) DO UPDATE SET stripe_account_id=excluded.stripe_account_id,
                charges_enabled=excluded.charges_enabled, payouts_enabled=excluded.payouts_enabled,
                details_submitted=excluded.details_submitted, updated_at=excluded.updated_at
            """,
            (
                cliente_id, account_id, int(bool(textnorm._object_get(account, "charges_enabled", False))),
                int(bool(textnorm._object_get(account, "payouts_enabled", False))),
                int(bool(textnorm._object_get(account, "details_submitted", False))), now, now,
            ),
        )
        connection.commit()
    return account_id


