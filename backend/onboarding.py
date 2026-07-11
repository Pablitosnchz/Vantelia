"""Onboarding y provisioning self-serve de clientes (refactor F3)."""
from __future__ import annotations

import json
import re
import secrets
from typing import Any, Dict

import copy
from fastapi import HTTPException

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

import onboarding_utils
from api_models import (
    OnboardingBookingSetupPayload,
    OnboardingBusinessPayload,
    OnboardingShopPayload,
    PortalScheduleUpdatePayload,
)
from backend import agenda, appstate, clients, db, demo_agenda, outreach, security, settings, textnorm, timeutils

def _read_onboarding_state(cliente_id: str) -> Dict[str, Any]:
    row = db.db_get_client_row(cliente_id)
    if not row:
        return {}
    try:
        cfg = json.loads(row["config_json"] or "{}")
    except json.JSONDecodeError:
        return {}
    return cfg.get("_onboarding_state", {}) or {}


def _write_onboarding_state(cliente_id: str, state: Dict[str, Any]) -> None:
    row = db.db_get_client_row(cliente_id)
    if not row:
        return
    try:
        cfg = json.loads(row["config_json"] or "{}")
    except json.JSONDecodeError:
        cfg = {}
    cfg["_onboarding_state"] = state
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE clientes SET config_json = ?, updated_at = ? WHERE cliente_id = ?",
            (json.dumps(cfg, ensure_ascii=False), now_iso, cliente_id),
        )
        connection.commit()


def _slugify_cliente_id(value: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", textnorm._sanitize_text(value).lower()).strip("_")
    return base[:50] or "bot"


def _generate_unique_cliente_id(name: str) -> str:
    base = _slugify_cliente_id(name)
    candidate = base
    suffix = 0
    with appstate.state_lock:
        existing = set(appstate.CONFIG_CLIENTES.keys())
    while candidate in existing or db.db_get_client_row(candidate) is not None:
        suffix += 1
        candidate = f"{base}_{secrets.token_hex(3)}"
        if suffix > 10:
            candidate = f"{base}_{secrets.token_hex(6)}"
            break
    return candidate


def _provision_self_serve_cliente(
    *,
    owner_user_id: str,
    nombre: str,
) -> str:
    """Provision a brand-new cliente_id owned by the user. Returns cliente_id."""
    cliente_id = _generate_unique_cliente_id(nombre)
    color_default = "#1F6FEB"
    icon_default = (nombre.strip()[:2] or "AI").upper()
    base_config = {
        "nombre": textnorm._sanitize_text(nombre)[:120] or cliente_id,
        "icono": icon_default,
        "color": color_default,
        "bienvenida": f"Hola, soy el asistente de {textnorm._sanitize_text(nombre)[:80]}. En que puedo ayudarte?",
        "prompt_extra": "",
        "allowed_origins": [],
        "contacto": {"email": "", "telefono": ""},
        "branding": {"powered_by": "Powered by Vantelia"},
        "whatsapp": {"enabled": False},
        "booking": {"enabled": True},
        "plan": "free",
    }
    normalized = clients._normalize_client_config(cliente_id, base_config)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        next_configs[cliente_id] = normalized
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    # ensure data dir exists for RAG indexing later
    cliente_data_dir = settings.DATA_DIR / cliente_id
    cliente_data_dir.mkdir(parents=True, exist_ok=True)
    info_path = cliente_data_dir / "info.txt"
    if not info_path.exists():
        info_path.write_text(
            f"===== INFORMACION DE {nombre.upper()} =====\n\n(Pendiente de completar)\n",
            encoding="utf-8",
        )
    # bind ownership in DB
    db.db_set_client_owner(cliente_id, owner_user_id, source="self_serve")
    # ensure free subscription
    db.db_ensure_free_subscription(owner_user_id, cliente_id=cliente_id)
    # link user.cliente_id 1:1
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET cliente_id = ? WHERE id = ?",
            (cliente_id, owner_user_id),
        )
        connection.commit()
    agenda._ensure_default_employees_for_all_clients()
    agenda._ensure_default_locations_for_all_clients()
    # init wizard state
    _write_onboarding_state(cliente_id, {"step": "learn", "started_at": timeutils._utc_now_iso()})
    return cliente_id


def _claim_cliente_id(claim_token: str, user_id: str, *, source: str = "claim_demo") -> str:
    """Transfer ownership of a claimable cliente to user_id.

    A claimable cliente_id is one that:
      - is a self-serve auto demo (starts with DEMO_TENANT_PREFIX), or
      - exists in CONFIG_CLIENTES with empty owner_user_id (no other user claimed it yet).

    Side effects:
      - Sets db owner + source.
      - Removes TTL from the demo registry so it survives _purge_expired_demos.
      - Links user.cliente_id 1:1 (errors if the user already owns another bot).
      - Ensures the user has a free subscription bound to the claimed cliente_id.
      - Best-effort marks any matching outreach prospect as status='client'.

    Returns the cliente_id on success. Raises HTTPException(400/404/409) otherwise.
    """
    cliente_id = (claim_token or "").strip()
    if not cliente_id or not settings.CLIENT_ID_PATTERN.match(cliente_id):
        raise HTTPException(status_code=400, detail="Claim token invalido.")
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Bot no encontrado.")

    existing_owner = db.db_get_client_owner(cliente_id)
    if existing_owner and existing_owner != user_id:
        raise HTTPException(status_code=409, detail="Este bot ya esta reclamado por otra cuenta.")

    # Check the user doesn't already own a different bot (one-bot-per-account model).
    user_row = security._get_user_by_id(user_id)
    if not user_row:
        raise HTTPException(status_code=400, detail="Usuario invalido.")
    existing_cid = (user_row["cliente_id"] or "").strip()
    if existing_cid and existing_cid != cliente_id:
        raise HTTPException(
            status_code=409,
            detail="Ya tienes un bot creado. Solo se permite un bot por cuenta en planes free.",
        )

    is_demo_tenant = (
        cliente_id.startswith(demo_agenda.DEMO_TENANT_PREFIX)
        or bool(appstate.CONFIG_CLIENTES.get(cliente_id, {}).get("demo_claimable"))
    )
    if not is_demo_tenant and not existing_owner:
        # Allow claiming legacy unowned clients only via admin path; reject here to
        # avoid letting any signed-in user grab a production cliente_id.
        raise HTTPException(
            status_code=403,
            detail="Este bot no se puede reclamar publicamente. Contacta con soporte.",
        )

    db.db_set_client_owner(cliente_id, user_id, source=source)
    db.db_ensure_free_subscription(user_id, cliente_id=cliente_id)
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET cliente_id = ? WHERE id = ?",
            (cliente_id, user_id),
        )
        connection.commit()

    # Remove TTL so _purge_expired_demos no longer kills it.
    try:
        registry = demo_agenda._load_demo_registry()
        if cliente_id in registry:
            registry.pop(cliente_id)
            demo_agenda._save_demo_registry(registry)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudo limpiar TTL para demo reclamada %s: %s", cliente_id, exc)

    # Best-effort: mark the outreach prospect linked to this demo as client.
    try:
        outreach._mark_outreach_prospect_as_client_for_cliente(cliente_id, user_row["email"])
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudo marcar prospect como client en outreach: %s", exc)

    return cliente_id


def _unique_cliente_id(seed: str) -> str:
    base = (onboarding_utils.slugify_company(seed) or "cliente").lower()
    base = base[:64].strip("_") or "cliente"
    candidate = base
    index = 2
    while candidate in appstate.CONFIG_CLIENTES:
        suffix = f"_{index}"
        candidate = f"{base[:80 - len(suffix)]}{suffix}"
        index += 1
    textnorm._assert_valid_client_id(candidate)
    return candidate


# ── Onboarding operativo (jul 2026): pasos Negocio/Reservas/Venta + readiness ──

def _public_links(cliente_id: str, base_url: str) -> Dict[str, str]:
    base = (base_url or "").rstrip("/")
    return {
        "central": f"{base}/central/{cliente_id}",
        "reservas": f"{base}/reservas/{cliente_id}",
        "tienda": f"{base}/tienda/{cliente_id}",
        "gift": f"{base}/gift/{cliente_id}",
        "demo": f"{base}/demo/{cliente_id}",
        "app": f"{base}/app",
    }


def _plan_features_for_client(cliente_id: str) -> set:
    plan = clients._client_plan(cliente_id)
    return set(settings._self_serve_plan(plan).get("features") or [])


def _setup_overview(cliente_id: str, base_url: str) -> Dict[str, Any]:
    """Datos agregados para los pasos Negocio/Reservas/Venta del wizard."""
    from backend import booking, commerce  # tardio: evita ciclos en el arranque

    # El centro por defecto se crea en startup; un tenant recien provisionado
    # dentro del mismo proceso aun no lo tiene. Idempotente.
    agenda._ensure_default_locations_for_all_clients()
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    contacto = cfg.get("contacto") if isinstance(cfg.get("contacto"), dict) else {}
    negocio = cfg.get("negocio") if isinstance(cfg.get("negocio"), dict) else {}
    booking_cfg = cfg.get("booking") if isinstance(cfg.get("booking"), dict) else {}
    try:
        employee_name = str(agenda._default_employee_row(cliente_id)["name"] or "")
    except HTTPException:
        employee_name = ""
    location_name = ""
    with db._get_db_connection() as connection:
        loc_row = connection.execute(
            "SELECT name FROM locations WHERE cliente_id = ? AND is_default = 1 LIMIT 1",
            (cliente_id,),
        ).fetchone()
        if loc_row:
            location_name = str(loc_row["name"] or "")
        service_rows = connection.execute(
            """
            SELECT slug, name, duration_minutes, price_cents FROM services
            WHERE cliente_id = ? AND is_active = 1
            ORDER BY sort_order, name COLLATE NOCASE
            """,
            (cliente_id,),
        ).fetchall()
    services = [
        {
            "slug": row["slug"],
            "name": row["name"],
            "duration_minutes": int(row["duration_minutes"] or 30),
            "price_label": textnorm._format_price_cents(int(row["price_cents"] or 0)) or "A consultar",
        }
        for row in service_rows
    ]
    shop_cfg = commerce._shop_public_config(cliente_id)
    gift_cfg = commerce._gift_public_config(cliente_id)
    try:
        account = booking._connect_account_status(cliente_id)
        stripe_ready = bool(account.connected and account.charges_enabled)
    except Exception:  # noqa: BLE001
        stripe_ready = False
    return {
        "ok": True,
        "cliente_id": cliente_id,
        "contact_email": str((contacto or {}).get("email", "") or ""),
        "contact_phone": str((contacto or {}).get("telefono", "") or ""),
        "sector": str((negocio or {}).get("sector", "") or ""),
        "ciudad": str((negocio or {}).get("ciudad", "") or ""),
        "booking_enabled": bool((booking_cfg or {}).get("enabled", False)),
        "timezone": str((booking_cfg or {}).get("timezone") or settings.DEFAULT_TIMEZONE),
        "slot_minutes": int((booking_cfg or {}).get("slot_minutes", 30) or 30),
        "day_start": str((booking_cfg or {}).get("day_start", "09:00") or "09:00"),
        "day_end": str((booking_cfg or {}).get("day_end", "18:00") or "18:00"),
        "closed_weekdays": [
            int(day) for day in (booking_cfg or {}).get("closed_weekdays", []) or []
            if isinstance(day, int) and 0 <= int(day) <= 6
        ],
        "employee_name": employee_name,
        "location_name": location_name,
        "services": services,
        "shop_enabled_packages": bool(shop_cfg.get("enabled_packages")),
        "shop_enabled_products": bool(shop_cfg.get("enabled_products")),
        "gift_enabled": bool(gift_cfg.get("enabled")),
        "stripe_ready": stripe_ready,
        "links": _public_links(cliente_id, base_url),
    }


def _save_business_profile(cliente_id: str, data: OnboardingBusinessPayload) -> None:
    """Paso Negocio: contacto + sector/ciudad (seccion `negocio`) + timezone de agenda."""
    email = textnorm._sanitize_text(data.contact_email)[:200]
    if email and "@" not in email:
        raise HTTPException(status_code=400, detail="Email de contacto invalido.")
    phone = textnorm._sanitize_text(data.contact_phone)[:40]
    sector = textnorm._sanitize_text(data.sector)[:80]
    ciudad = textnorm._sanitize_text(data.ciudad)[:80]
    tz = textnorm._sanitize_text(data.timezone)[:80]
    if tz:
        try:
            ZoneInfo(tz)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Zona horaria invalida.")
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id)
        if not cfg:
            raise HTTPException(status_code=404, detail="Cliente no configurado.")
        cfg["contacto"] = {"email": email, "telefono": phone}
        negocio = dict(cfg.get("negocio") or {})
        negocio["sector"] = sector
        negocio["ciudad"] = ciudad
        cfg["negocio"] = negocio
        if tz:
            booking_cfg = dict(cfg.get("booking") or {})
            booking_cfg["timezone"] = tz
            cfg["booking"] = booking_cfg
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)


def _save_booking_setup(cliente_id: str, data: OnboardingBookingSetupPayload) -> None:
    """Paso Reservas: horario general (reusa agenda._update_client_schedule, que
    valida conflictos y sincroniza el profesional por defecto) + nombres del
    profesional inicial y del centro principal."""
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    booking_cfg = cfg.get("booking") if isinstance(cfg.get("booking"), dict) else {}
    schedule = PortalScheduleUpdatePayload(
        enabled=bool(data.enabled),
        timezone=str((booking_cfg or {}).get("timezone") or settings.DEFAULT_TIMEZONE),
        slot_minutes=int(data.slot_minutes),
        day_start=data.day_start,
        day_end=data.day_end,
        break_start=str((booking_cfg or {}).get("break_start", "") or ""),
        break_end=str((booking_cfg or {}).get("break_end", "") or ""),
        break_windows=list((booking_cfg or {}).get("break_windows", []) or []),
        closed_weekdays=[int(day) for day in data.closed_weekdays if 0 <= int(day) <= 6],
    )
    agenda._update_client_schedule(cliente_id, schedule)
    employee_name = textnorm._sanitize_text(data.employee_name)[:120]
    location_name = textnorm._sanitize_text(data.location_name)[:120]
    if not employee_name and not location_name:
        return
    agenda._ensure_default_locations_for_all_clients()
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        if employee_name:
            connection.execute(
                "UPDATE employees SET name = ?, updated_at = ? WHERE cliente_id = ? AND is_default = 1",
                (employee_name, now_iso, cliente_id),
            )
        if location_name:
            connection.execute(
                "UPDATE locations SET name = ?, updated_at = ? WHERE cliente_id = ? AND is_default = 1",
                (location_name, now_iso, cliente_id),
            )
        connection.commit()


def _save_shop_setup(cliente_id: str, data: OnboardingShopPayload) -> None:
    """Paso Venta: opt-in de tienda publica (bonos/productos) y tarjetas regalo.
    Mismo patron de escritura que PUT /auth/app/shop-public y /gift-cards-public."""
    from backend import rag  # tardio: evita ciclos en el arranque

    if data.enabled_packages is None and data.enabled_products is None and data.gift_enabled is None:
        return
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id)
        if not cfg:
            raise HTTPException(status_code=404, detail="Cliente no configurado.")
        sp = dict(cfg.get("shop_public", {}) or {})
        if data.enabled_packages is not None:
            sp["enabled_packages"] = bool(data.enabled_packages)
        if data.enabled_products is not None:
            sp["enabled_products"] = bool(data.enabled_products)
        cfg["shop_public"] = sp
        if data.gift_enabled is not None:
            gp = dict(cfg.get("gift_cards_public", {}) or {})
            gp["enabled"] = bool(data.gift_enabled)
            cfg["gift_cards_public"] = gp
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    rag._invalidate_client_runtime(cliente_id)


def _readiness_overview(cliente_id: str, base_url: str) -> Dict[str, Any]:
    """Semaforos de activacion por bloque: que esta listo y que falta para operar."""
    from backend import booking, commerce, emailing  # tardio: evita ciclos en el arranque

    cfg = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    features = _plan_features_for_client(cliente_id)
    blocks = []

    info_path = settings.DATA_DIR / cliente_id / "info.txt"
    has_kb = info_path.exists() and info_path.stat().st_size > 200
    blocks.append({
        "key": "knowledge",
        "title": "Conocimiento del negocio",
        "status": "ready" if has_kb else "action",
        "detail": "Base de conocimiento generada desde tu web." if has_kb
        else "Pega tu web en el paso Aprender o completa el cerebro en el panel.",
    })

    with db._get_db_connection() as connection:
        services_count = connection.execute(
            "SELECT COUNT(*) FROM services WHERE cliente_id = ? AND is_active = 1",
            (cliente_id,),
        ).fetchone()[0]
        employees_count = connection.execute(
            "SELECT COUNT(*) FROM employees WHERE cliente_id = ? AND is_active = 1",
            (cliente_id,),
        ).fetchone()[0]
    blocks.append({
        "key": "services",
        "title": "Servicios",
        "status": "ready" if services_count else "action",
        "detail": f"{services_count} servicio(s) activo(s)." if services_count
        else "No hay servicios activos. Anadelos en el panel (pestana Servicios).",
    })

    booking_cfg = cfg.get("booking") if isinstance(cfg.get("booking"), dict) else {}
    booking_on = bool((booking_cfg or {}).get("enabled", False))
    if booking_on and employees_count:
        booking_status, booking_detail = "ready", "Reservas activas con horario y profesional configurados."
    elif booking_on:
        booking_status, booking_detail = "action", "Reservas activas pero sin profesionales activos."
    else:
        booking_status, booking_detail = "off", "Reservas desactivadas. Activalas en el paso Reservas o en el panel."
    blocks.append({"key": "booking", "title": "Reservas", "status": booking_status, "detail": booking_detail})

    try:
        account = booking._connect_account_status(cliente_id)
    except Exception:  # noqa: BLE001
        account = None
    if account is not None and account.connected and account.charges_enabled:
        pay_status, pay_detail = "ready", "Stripe conectado y cobros habilitados."
    elif account is not None and account.connected:
        pay_status, pay_detail = "action", "Stripe conectado pero sin cobros habilitados. Completa la verificacion."
    else:
        pay_status, pay_detail = "pending", "Conecta Stripe en el panel (pestana Pagos) para cobrar online."
    blocks.append({"key": "payments", "title": "Cobros (Stripe)", "status": pay_status, "detail": pay_detail})

    email_status, email_detail = "action", "Sin canal de email configurado."
    try:
        channel_settings = security._ensure_channel_settings(cliente_id)
        gmail = emailing._client_gmail_connection(cliente_id)
        if gmail and gmail["status"] == "active":
            email_status, email_detail = "ready", f"Gmail conectado ({gmail['account_email']})."
        elif emailing._client_smtp_configured(channel_settings):
            email_status, email_detail = "ready", "SMTP propio configurado."
        elif settings.SMTP_HOST:
            email_status, email_detail = "ready", "Emails enviados por Vantelia (por defecto). Puedes conectar Gmail en el panel."
    except Exception:  # noqa: BLE001
        pass
    blocks.append({"key": "email", "title": "Email", "status": email_status, "detail": email_detail})

    shop_cfg = commerce._shop_public_config(cliente_id)
    gift_cfg = commerce._gift_public_config(cliente_id)
    shop_opted = bool(shop_cfg.get("enabled_packages") or shop_cfg.get("enabled_products") or gift_cfg.get("enabled"))
    try:
        shop_live = bool(commerce.shop_public_available(cliente_id).get("any")) or commerce.gift_public_available(cliente_id)
    except Exception:  # noqa: BLE001
        shop_live = False
    if shop_live:
        shop_status, shop_detail = "ready", "Venta online activa (tienda y/o tarjetas regalo)."
    elif shop_opted:
        shop_status, shop_detail = "action", "Venta online preparada, pendiente de cobros: conecta Stripe y ten catalogo activo."
    else:
        shop_status, shop_detail = "off", "Venta online desactivada. Activala en el paso Lanzamiento o en Ventas."
    blocks.append({"key": "shop", "title": "Venta online", "status": shop_status, "detail": shop_detail})

    wa_cfg = cfg.get("whatsapp") if isinstance(cfg.get("whatsapp"), dict) else {}
    if "whatsapp" not in features:
        wa_status, wa_detail = "not_in_plan", "Disponible desde el plan Pro."
    elif bool((wa_cfg or {}).get("enabled")) and str((wa_cfg or {}).get("phone_number_id", "")).strip():
        wa_status, wa_detail = "ready", "WhatsApp conectado."
    elif bool((wa_cfg or {}).get("enabled")):
        wa_status, wa_detail = "action", "WhatsApp activado pero falta el numero (Meta Business)."
    else:
        wa_status, wa_detail = "pending", "Requiere conexion con Meta Business. Te guiamos desde el panel."
    blocks.append({"key": "whatsapp", "title": "WhatsApp", "status": wa_status, "detail": wa_detail})

    voice_cfg = cfg.get("voice") if isinstance(cfg.get("voice"), dict) else {}
    if "voice" not in features:
        voice_status, voice_detail = "not_in_plan", "Disponible en el plan Business."
    elif bool((voice_cfg or {}).get("enabled")):
        voice_status, voice_detail = "ready", "Asistente de voz activo."
    else:
        voice_status, voice_detail = "pending", "Requiere numero de telefono (Twilio). Se configura con nuestro equipo."
    blocks.append({"key": "voice", "title": "Voz", "status": voice_status, "detail": voice_detail})

    blocks.append({
        "key": "public_links",
        "title": "Enlaces publicos y widget",
        "status": "ready",
        "detail": "Pagina de reservas, tienda y widget listos para compartir.",
    })

    return {
        "ok": True,
        "cliente_id": cliente_id,
        "blocks": blocks,
        "links": _public_links(cliente_id, base_url),
    }


