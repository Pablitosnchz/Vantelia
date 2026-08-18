"""Helpers del panel admin y portal cliente (payloads, stats, analytics) (refactor F3)."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import copy
from fastapi import Cookie, Header, HTTPException, Request, status

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from api_models import AdminClientePayload, AdminClienteSaveResult, AppOverviewStats, PortalAgendaBlock, PortalAiConfigPayload, PortalAiConfigPublic, PortalBookingSummary
from backend import agenda, appstate, booking, clients, commerce, db, rag, security, settings, textnorm, timeutils

def _client_payload_from_config(config: Dict[str, Any], info_txt: str) -> AdminClientePayload:
    return AdminClientePayload(
        nombre=config["nombre"],
        icono=config["icono"],
        color=config["color"],
        accent_color=config.get("accent_color", "") or None,
        logo_url=config.get("logo_url", "") or None,
        bienvenida=config["bienvenida"],
        prompt_extra=config.get("prompt_extra", ""),
        allowed_origins=list(config.get("allowed_origins", [])),
        contacto_email=config.get("contacto", {}).get("email", ""),
        contacto_telefono=config.get("contacto", {}).get("telefono", ""),
        branding_text=config.get("branding", {}).get("powered_by", "Powered by Vantelia"),
        whatsapp_enabled=bool(config.get("whatsapp", {}).get("enabled", False)),
        whatsapp_phone_number_id=config.get("whatsapp", {}).get("phone_number_id", ""),
        whatsapp_access_token_env=config.get("whatsapp", {}).get("access_token_env", ""),
        whatsapp_verify_token_env=config.get("whatsapp", {}).get("verify_token_env", ""),
        booking_enabled=bool(config.get("booking", {}).get("enabled", False)),
        booking_timezone=config.get("booking", {}).get("timezone", settings.DEFAULT_TIMEZONE),
        booking_slot_minutes=int(config.get("booking", {}).get("slot_minutes", 30)),
        booking_day_start=config.get("booking", {}).get("day_start", "09:00"),
        booking_day_end=config.get("booking", {}).get("day_end", "18:00"),
        booking_closed_weekdays=list(config.get("booking", {}).get("closed_weekdays", [6])),
        booking_provider="internal",
        booking_webhook_env=config.get("booking", {}).get("webhook_env", ""),
        booking_webhook_url=config.get("booking", {}).get("webhook_url", ""),
        booking_calendly_user_env="",
        booking_calendly_event_type_env="",
        booking_calendly_location_kind="",
        booking_calendly_location_value="",
        booking_google_calendar_id="",
        booking_google_calendar_id_env="",
        booking_google_service_account_path="",
        booking_google_service_account_env="",
        booking_google_service_account_json="",
        booking_success_message=config.get("booking", {}).get(
            "success_message",
            "Tu solicitud de cita ha quedado registrada correctamente.",
        ),
        info_txt=info_txt,
        reindex_after_save=True,
    )


def _config_from_admin_payload(cliente_id: str, payload: AdminClientePayload) -> Dict[str, Any]:
    existing_booking = appstate.CONFIG_CLIENTES.get(cliente_id, {}).get("booking", {})
    existing_config = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    # accent_color: usa el valor del payload si viene, si no conserva el existente
    if payload.accent_color is not None:
        accent_color = textnorm._sanitize_text(payload.accent_color or "")
    else:
        accent_color = existing_config.get("accent_color", "")
    # logo_url: usa el valor del payload si viene, si no conserva el existente
    if payload.logo_url is not None:
        logo_url = textnorm._sanitize_text(payload.logo_url or "")
    else:
        logo_url = existing_config.get("logo_url", "")
    return clients._normalize_client_config(
        cliente_id,
        {
            "nombre": payload.nombre,
            "plan": existing_config.get("plan", settings.PLAN_DEFAULT),
            "subscription": dict(existing_config.get("subscription") or {}),
            "icono": payload.icono,
            "color": payload.color,
            "accent_color": accent_color,
            "logo_url": logo_url,
            "bienvenida": payload.bienvenida,
            "prompt_extra": payload.prompt_extra,
            "allowed_origins": payload.allowed_origins,
            "contacto": {
                "email": payload.contacto_email,
                "telefono": payload.contacto_telefono,
            },
            "branding": {"powered_by": payload.branding_text},
            "whatsapp": {
                "enabled": payload.whatsapp_enabled,
                "phone_number_id": payload.whatsapp_phone_number_id,
                "access_token_env": payload.whatsapp_access_token_env,
                "verify_token_env": payload.whatsapp_verify_token_env,
            },
            "booking": {
                "enabled": payload.booking_enabled,
                "timezone": payload.booking_timezone,
                "slot_minutes": payload.booking_slot_minutes,
                "day_start": payload.booking_day_start,
                "day_end": payload.booking_day_end,
                "break_start": existing_booking.get("break_start", ""),
                "break_end": existing_booking.get("break_end", ""),
                "break_windows": existing_booking.get("break_windows", []),
                "closed_weekdays": payload.booking_closed_weekdays,
                "provider": "internal",
                "webhook_env": payload.booking_webhook_env,
                "webhook_url": payload.booking_webhook_url,
                "calendly_user_env": "",
                "calendly_event_type_env": "",
                "calendly_location_kind": "",
                "calendly_location_value": "",
                "google_calendar_id": "",
                "google_calendar_id_env": "",
                "google_service_account_path": "",
                "google_service_account_env": "",
                "success_message": payload.booking_success_message,
                "message_templates": existing_booking.get("message_templates", {}),
                "message_template_enabled": existing_booking.get("message_template_enabled", {}),
                "message_template_channels": existing_booking.get("message_template_channels", {}),
            },
        },
    )


def _portal_ai_config_from_client_config(cliente_id: str) -> PortalAiConfigPublic:
    config = clients._get_client_config(cliente_id)
    return PortalAiConfigPublic(
        nombre=config.get("nombre", cliente_id),
        icono=config.get("icono", "AI"),
        color=config.get("color", "#00b1d9"),
        accent_color=config.get("accent_color", ""),
        logo_url=config.get("logo_url", ""),
        bienvenida=config.get("bienvenida", ""),
        prompt_extra=config.get("prompt_extra", ""),
        branding_text=config.get("branding", {}).get("powered_by", "Powered by Vantelia"),
    )


def _is_admin_client_portal_override(user: sqlite3.Row, cliente_id: str = "") -> bool:
    return bool(user and user["role"] == "admin" and str(cliente_id or "").strip())


def _update_portal_ai_config(
    cliente_id: str,
    data: PortalAiConfigPayload,
    *,
    full_access: bool = False,
) -> PortalAiConfigPublic:
    next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
    config = next_configs.get(cliente_id)
    if not config:
        raise HTTPException(status_code=404, detail="Cliente no configurado")

    plan = clients._client_plan(cliente_id)
    limits = clients._plan_limits(plan)
    branding_allowed = full_access or bool(limits.get("branding_customization"))

    config["bienvenida"] = textnorm._sanitize_text(data.bienvenida, allow_multiline=True)[:400]
    config["prompt_extra"] = textnorm._sanitize_text(data.prompt_extra, allow_multiline=True)[:2000]
    if data.nombre is not None:
        nombre = textnorm._sanitize_text(data.nombre)[:120]
        if nombre:
            config["nombre"] = nombre

    # Logo del asistente disponible en todos los planes (feature basica de identidad).
    if data.logo_url is not None:
        config["logo_url"] = textnorm._sanitize_text(data.logo_url)

    if branding_allowed:
        config["icono"] = textnorm._sanitize_text(data.icono)[:12] or "AI"
        if data.color is not None:
            color = textnorm._sanitize_text(data.color)
            if color:
                config["color"] = color
        if data.accent_color is not None:
            config["accent_color"] = textnorm._sanitize_text(data.accent_color)
        if data.branding_text is not None:
            branding = config.get("branding") or {}
            branding_value = textnorm._sanitize_text(data.branding_text) or "Powered by Vantelia"
            branding["powered_by"] = branding_value
            config["branding"] = branding
    else:
        # Plan sin personalización completa: forzamos branding por defecto Vantelia.
        branding = config.get("branding") or {}
        branding["powered_by"] = "Powered by Vantelia"
        config["branding"] = branding

    clients._validate_single_client_runtime(cliente_id, config)
    clients._persist_configs_to_disk(next_configs)
    clients._update_runtime_configs(next_configs)
    return _portal_ai_config_from_client_config(cliente_id)


def _prepare_admin_payload(cliente_id: str, payload: AdminClientePayload) -> AdminClientePayload:
    _ = cliente_id
    return payload.model_copy(
        update={
            "booking_provider": "internal",
            "booking_calendly_user_env": "",
            "booking_calendly_event_type_env": "",
            "booking_calendly_location_kind": "",
            "booking_calendly_location_value": "",
            "booking_google_calendar_id": "",
            "booking_google_calendar_id_env": "",
            "booking_google_service_account_path": "",
            "booking_google_service_account_env": "",
            "booking_google_service_account_json": "",
        }
    )


def _save_admin_client_payload(
    cliente_id: str,
    data: AdminClientePayload,
    request: Request,
) -> AdminClienteSaveResult:
    if not data.info_txt.strip():
        raise HTTPException(status_code=400, detail="`info_txt` no puede estar vacio.")

    try:
        data = _prepare_admin_payload(cliente_id, data)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    next_config = _config_from_admin_payload(cliente_id, data)
    clients._validate_single_client_runtime(cliente_id, next_config)

    next_configs = dict(appstate.CONFIG_CLIENTES)
    next_configs[cliente_id] = next_config

    clients._persist_configs_to_disk(next_configs)
    rag._write_info_txt(cliente_id, data.info_txt)
    clients._update_runtime_configs(next_configs)
    # deactivate_missing=False A PROPOSITO. Con True, guardar cualquier campo de la
    # ficha apagaba todos los servicios que no aparecieran en info.txt: un salon con
    # 183 servicios importados de su Excel se quedo con los 8 de su descripcion.
    # Se siguen creando/actualizando los que el texto mencione; lo demas se respeta.
    agenda._sync_services_from_info(cliente_id, data.info_txt, deactivate_missing=False)
    commerce._seed_commerce_from_info(cliente_id, data.info_txt)
    rag._invalidate_client_runtime(cliente_id)

    reindexed = False
    reindex_error = ""
    if data.reindex_after_save:
        try:
            rag.cargar_indice(cliente_id)
            reindexed = True
        except Exception as exc:  # noqa: BLE001
            reindex_error = str(exc)
            settings.logger.warning("No se pudo reindexar automaticamente %s: %s", cliente_id, exc)

    snippet = clients._build_install_snippet(cliente_id, request)
    return AdminClienteSaveResult(
        status="ok",
        cliente_id=cliente_id,
        reindexed=reindexed,
        reindex_error=reindex_error,
        install_snippet=snippet["install_snippet"],
        widget_script_url=snippet["widget_script_url"],
        api_base_url=snippet["api_base_url"],
        demo_url=snippet["demo_url"],
    )


def _default_admin_payload(cliente_id: str) -> AdminClientePayload:
    display_name = cliente_id.replace("_", " ").strip() or "Nuevo cliente"
    return AdminClientePayload(
        nombre=display_name.title(),
        icono="AI",
        color="#00b1d9",
        bienvenida=f"Hola, soy el asistente de {display_name.title()}. En que puedo ayudarte hoy?",
        prompt_extra=(
            "Habla con tono profesional, mantente dentro del contexto del negocio y "
            "deriva al equipo humano cuando falte informacion."
        ),
        allowed_origins=["https://www.vantelia.es", "https://vantelia.es"],
        contacto_email="",
        contacto_telefono="",
        branding_text="Powered by Vantelia",
        booking_enabled=True,
        booking_timezone=settings.DEFAULT_TIMEZONE,
        booking_slot_minutes=30,
        booking_day_start="09:00",
        booking_day_end="18:00",
        booking_closed_weekdays=[6],
        booking_provider="internal",
        booking_webhook_env="WEBHOOK_DEFAULT",
        booking_webhook_url="",
        booking_calendly_user_env="",
        booking_calendly_event_type_env="",
        booking_calendly_location_kind="",
        booking_calendly_location_value="",
        booking_google_calendar_id_env="",
        booking_google_service_account_env="",
        booking_success_message="Tu solicitud de cita ha quedado registrada correctamente.",
        info_txt=(
            f"===== INFORMACION DE {display_name.upper()} =====\n\n"
            "DATOS GENERALES:\n"
            f"- Nombre: {display_name.title()}\n"
            "- Tipo de negocio: No especificado\n"
            "- Descripcion: No especificado\n"
            "- Eslogan: No especificado\n"
        ),
        reindex_after_save=True,
    )


def _payload_from_alta_express(
    *,
    cliente_id: str,
    result: Any,
    nombre_bot: str,
    tono: str,
    idioma: str,
    color: str,
    booking_enabled: bool,
    booking_timezone: str,
) -> AdminClientePayload:
    website_variants = []
    parsed = urlparse(result.normalized_url)
    base_domain = parsed.netloc.replace("www.", "")
    primary_origin = f"{parsed.scheme}://{parsed.netloc}"
    website_variants.append(primary_origin)
    if "." in base_domain and not re.match(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$", parsed.netloc):
        if parsed.netloc.startswith("www."):
            website_variants.append(f"{parsed.scheme}://{base_domain}")
        else:
            website_variants.append(f"{parsed.scheme}://www.{base_domain}")

    allowed_origins = []
    for origin in website_variants:
        if origin not in allowed_origins:
            allowed_origins.append(origin)

    company_name = textnorm._sanitize_text(result.detected_business_name) or cliente_id.replace("_", " ").title()

    return AdminClientePayload(
        nombre=company_name,
        icono=nombre_bot[:2].upper() or "AI",
        color=color,
        bienvenida=result.suggested_welcome,
        prompt_extra=(
            f"Habla con tono {tono.lower()}, mantente dentro del contexto del negocio, "
            "responde solo con informacion apoyada en la base documental y deriva al equipo humano "
            "cuando falten datos."
        ),
        allowed_origins=allowed_origins,
        contacto_email="",
        contacto_telefono="",
        branding_text="Powered by Vantelia",
        booking_enabled=booking_enabled,
        booking_timezone=booking_timezone,
        booking_slot_minutes=30,
        booking_day_start="09:00",
        booking_day_end="18:00",
        booking_closed_weekdays=[6],
        booking_provider="internal",
        booking_webhook_env="WEBHOOK_DEFAULT",
        booking_webhook_url="",
        booking_calendly_user_env="",
        booking_calendly_event_type_env="",
        booking_calendly_location_kind="",
        booking_calendly_location_value="",
        booking_google_calendar_id_env="",
        booking_google_service_account_env="",
        booking_success_message="Tu solicitud de cita ha quedado registrada correctamente.",
        info_txt=result.info_txt,
        reindex_after_save=True,
    )


def _portal_client_id_or_403(user: sqlite3.Row, cliente_id: str = "") -> str:
    requested_client_id = str(cliente_id or "").strip()
    if user["role"] == "admin":
        if not requested_client_id:
            raise HTTPException(status_code=403, detail="Indica el cliente que quieres abrir en el portal.")
        clients._get_client_config(requested_client_id)
        return requested_client_id
    user_client_id = user["cliente_id"] or ""
    if not user_client_id:
        raise HTTPException(status_code=403, detail="Tu usuario no tiene cliente asociado.")
    if requested_client_id and requested_client_id != user_client_id:
        raise HTTPException(status_code=403, detail="No tienes acceso a ese cliente.")
    clients._get_client_config(user_client_id)
    return user_client_id


def _require_admin_identity(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
) -> Dict[str, str]:
    """Like _require_admin_token, but returns admin identity (id + email).

    Required for actions that need attribution: impersonation, audit logs, etc.
    Falls back to a synthetic identity when only the Bearer token is used.
    """
    portal_user = security._get_authenticated_portal_user_or_none(portal_session)
    if portal_user and portal_user["role"] == "admin":
        return {
            "user_id": portal_user["id"],
            "email": portal_user["email"] or "",
            "via": "session",
        }

    if not settings.ADMIN_API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Los endpoints de administracion no estan habilitados.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta token admin o sesion valida.")
    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, settings.ADMIN_API_TOKEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token admin invalido")
    return {"user_id": "admin-api-token", "email": "admin@bearer-token", "via": "bearer"}


def _portal_stats_for_user(user: sqlite3.Row, cliente_id_override: str = "") -> Dict[str, Any]:
    with db._get_db_connection() as connection:
        if user["role"] == "admin" and not cliente_id_override:
            total_bookings = connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
            pending = connection.execute(
                "SELECT COUNT(*) FROM bookings WHERE status = 'pending_review'"
            ).fetchone()[0]
            upcoming = connection.execute(
                """
                SELECT COUNT(*)
                FROM bookings
                WHERE status = 'confirmed'
                  AND (start_at = '' OR start_at >= ?)
                """,
                (timeutils._utc_now_iso(),),
            ).fetchone()[0]
            total_users = connection.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]
            client_users = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'client' AND is_active = 1"
            ).fetchone()[0]
            return {
                "total_bookings": total_bookings,
                "pending_review": pending,
                "upcoming": upcoming,
                "active_users": total_users,
                "client_users": client_users,
            }

        target_client_id = cliente_id_override or (user["cliente_id"] or "")
        total_bookings = connection.execute(
            "SELECT COUNT(*) FROM bookings WHERE cliente_id = ?",
            (target_client_id,),
        ).fetchone()[0]
        upcoming = connection.execute(
            """
            SELECT COUNT(*)
            FROM bookings
            WHERE cliente_id = ?
              AND status IN ('confirmed', 'pending_review', 'pending_payment')
              AND (start_at = '' OR start_at >= ?)
            """,
            (target_client_id, timeutils._utc_now_iso()),
        ).fetchone()[0]
        history = connection.execute(
            """
            SELECT COUNT(*)
            FROM bookings
            WHERE cliente_id = ?
              AND (
                status IN ('cancelled', 'completed', 'no_show')
                OR (start_at <> '' AND start_at < ?)
              )
            """,
            (target_client_id, timeutils._utc_now_iso()),
        ).fetchone()[0]
        completed = connection.execute(
            "SELECT COUNT(*) FROM bookings WHERE cliente_id = ? AND status = 'completed'",
            (target_client_id,),
        ).fetchone()[0]
        no_show = connection.execute(
            "SELECT COUNT(*) FROM bookings WHERE cliente_id = ? AND status = 'no_show'",
            (target_client_id,),
        ).fetchone()[0]
        attendance_total = completed + no_show
        attendance_rate = round(completed * 100 / attendance_total, 1) if attendance_total else None
        return {
            "total_bookings": total_bookings,
            "upcoming": upcoming,
            "history": history,
            "completed": completed,
            "no_show": no_show,
            "attendance_rate": attendance_rate,
            "empresa": clients._get_client_config(target_client_id)["nombre"] if target_client_id else "",
        }


def _portal_today_dashboard(
    cliente_id: str,
    request: Optional[Request] = None,
) -> Tuple[List[PortalBookingSummary], List[PortalAgendaBlock]]:
    today = datetime.now(ZoneInfo(clients._get_client_config(cliente_id)["booking"]["timezone"])).date().isoformat()
    rows, _ = booking._list_booking_rows(
        cliente_id=cliente_id,
        date_from=today,
        date_to=today,
        limit=30,
        scope="all",
    )
    today_bookings = [booking._portal_booking_summary_from_row(row, request) for row in rows]
    blocks = [
        agenda._serialize_agenda_block(row)
        for row in agenda._list_agenda_blocks(cliente_id, date_from=today, date_to=today)
    ]
    return today_bookings, blocks


def _services_info_section(items: List[Dict[str, str]]) -> str:
    lines = ["SERVICIOS Y PRECIOS:"]
    cleaned: Dict[str, Dict[str, str]] = {}
    for item in items:
        nombre = textnorm._sanitize_text(str(item.get("nombre") or item.get("name") or ""))[:160]
        if not nombre:
            continue
        service_id = agenda._normalize_service_id(nombre)
        if not service_id:
            continue
        descripcion = textnorm._sanitize_text(str(item.get("descripcion") or item.get("description") or ""), allow_multiline=True)[:800]
        cleaned[service_id] = {"nombre": nombre, "descripcion": descripcion}
    for item in cleaned.values():
        lines.append(f"- Servicio: {item['nombre']}")
        if item["descripcion"]:
            desc = " ".join(item["descripcion"].splitlines())
            lines.append(f"  - Descripcion: {desc}")
    return "\n".join(lines)


def _replace_services_section(info_txt: str, items: List[Dict[str, str]]) -> str:
    section = _services_info_section(items)
    lines = (info_txt or "").splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith("servicios y precios"):
            start = idx
            break
    if start is None:
        base = (info_txt or "").rstrip()
        return (base + "\n\n" + section + "\n").lstrip()

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        value = lines[idx].strip()
        if value and value.endswith(":") and value.upper() == value and len(value) > 3:
            end = idx
            break
    next_lines = lines[:start] + section.splitlines() + lines[end:]
    return "\n".join(next_lines).strip() + "\n"


def _compute_dashboard_stats(cliente_id: str, period_start_iso: str) -> AppOverviewStats:
    today_start = timeutils._utc_now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    today_date = timeutils._utc_now().date().isoformat()
    upcoming_date = (timeutils._utc_now().date() + timedelta(days=7)).isoformat()
    training_path = settings.DATA_DIR / cliente_id / "info.txt"
    training_chars = 0
    if training_path.exists():
        try:
            training_chars = training_path.stat().st_size
        except OSError:
            training_chars = 0
    with db._get_db_connection() as connection:
        sessions_today = connection.execute(
            "SELECT COUNT(*) FROM chat_sessions WHERE cliente_id = ? AND last_message_at >= ?",
            (cliente_id, today_start),
        ).fetchone()[0] or 0
        messages_today = connection.execute(
            "SELECT COUNT(*) FROM chat_messages m JOIN chat_sessions s ON s.id = m.session_id "
            "WHERE s.cliente_id = ? AND m.role = 'assistant' AND m.created_at >= ?",
            (cliente_id, today_start),
        ).fetchone()[0] or 0
        messages_period = connection.execute(
            "SELECT COUNT(*) FROM chat_messages m JOIN chat_sessions s ON s.id = m.session_id "
            "WHERE s.cliente_id = ? AND m.role = 'assistant' AND m.created_at >= ?",
            (cliente_id, period_start_iso),
        ).fetchone()[0] or 0
        leads_generated = connection.execute(
            "SELECT COUNT(*) FROM bot_leads WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchone()[0] or 0
        chat_sessions_total = connection.execute(
            "SELECT COUNT(*) FROM chat_sessions WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchone()[0] or 0
        bookings_today = connection.execute(
            "SELECT COUNT(*) FROM bookings WHERE cliente_id = ? AND booking_date = ? "
            "AND status IN ('confirmed', 'pending_review', 'pending_payment')",
            (cliente_id, today_date),
        ).fetchone()[0] or 0
        bookings_upcoming = connection.execute(
            "SELECT COUNT(*) FROM bookings WHERE cliente_id = ? AND booking_date > ? AND booking_date <= ? "
            "AND status IN ('confirmed', 'pending_review', 'pending_payment')",
            (cliente_id, today_date, upcoming_date),
        ).fetchone()[0] or 0
    return AppOverviewStats(
        users_today=int(sessions_today),
        messages_today=int(messages_today),
        messages_period=int(messages_period),
        leads_generated=int(leads_generated),
        training_chars=int(training_chars),
        chat_sessions_total=int(chat_sessions_total),
        bookings_today=int(bookings_today),
        bookings_upcoming=int(bookings_upcoming),
        countries=[],
    )


_ANALYTICS_ALLOWED_KEYS = {
    "event",
    "event_source",
    "page_path",
    "page_url",
    "timestamp",
    "cta_label",
    "cta_href",
    "plan",
    "plan_label",
    "billing_period",
    "sector",
    "source",
    "utm_source",
    "has_website_url",
    "demo_url",
    "expires_in_minutes",
    "status",
    "error_message",
    "widget_client_id",
    "widget_position",
    "session_id",
    "booking_enabled",
    "message_length",
    "forced_message",
    "response_length",
    "booking_form_shown",
    "quick_action",
    "date",
    "time",
    "service",
    "has_employee",
    "booking_id",
    "booking_status",
    "has_manage_url",
    "has_provider_booking_url",
    "lead_type",
    "checkout_session_id",
    "checkout_status",
    "action",
    "surface",
    "step",
    "page_type",
    "signup_source",
    "user_id",
    "cliente_id",
    "bot_name",
    "message_previewed",
}


def _analytics_client_id(payload: Dict[str, Any]) -> str:
    value = payload.get("widget_client_id") or payload.get("cliente_id") or ""
    value = str(value).strip()
    return value[:80] if settings.CLIENT_ID_PATTERN.match(value) else ""


def _safe_analytics_value(value: Any) -> Any:
    if isinstance(value, bool) or isinstance(value, int) or isinstance(value, float):
        return value
    if isinstance(value, str):
        return textnorm._sanitize_text(value, allow_multiline=False)[:300]
    return str(value)[:300]


def _record_analytics_event(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    event_name = textnorm._sanitize_text(payload.get("event", ""), allow_multiline=False)[:80]
    if not re.match(r"^[a-zA-Z0-9_.:-]{2,80}$", event_name):
        raise HTTPException(status_code=400, detail="Evento de analitica invalido.")

    metadata = {
        key: _safe_analytics_value(value)
        for key, value in payload.items()
        if key in _ANALYTICS_ALLOWED_KEYS and key not in {"event", "session_id"}
    }
    session_id = str(payload.get("session_id") or "").strip()[:128]
    if session_id and not settings.SESSION_ID_PATTERN.match(session_id):
        session_id = ""
    client_ip = request.client.host if request.client else ""
    ip_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:24] if client_ip else ""
    user_agent = textnorm._sanitize_text(request.headers.get("user-agent", ""), allow_multiline=False)[:240]
    created_at = timeutils._utc_now_iso()

    with db._get_db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO analytics_events (
                event_name, event_source, cliente_id, session_id, page_path, page_url,
                metadata_json, user_agent, ip_hash, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_name,
                textnorm._sanitize_text(payload.get("event_source", "vantelia_site"), allow_multiline=False)[:80],
                _analytics_client_id(payload),
                session_id,
                textnorm._sanitize_text(payload.get("page_path", ""), allow_multiline=False)[:220],
                textnorm._sanitize_text(payload.get("page_url", ""), allow_multiline=False)[:500],
                json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))[:4000],
                user_agent,
                ip_hash,
                created_at,
            ),
        )
        connection.commit()
        event_id = int(cursor.lastrowid or 0)

    return {"ok": True, "id": event_id}


def _try_record_analytics_event(payload: Dict[str, Any], request: Request) -> None:
    try:
        _record_analytics_event(payload, request)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudo registrar evento de analitica %s: %s", payload.get("event"), exc)


