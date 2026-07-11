"""Endpoints: seccion admin_core (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

import copy
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import (
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field


import onboarding_utils
from api_models import *  # noqa: F401,F403
from backend import (
    appstate,
    booking,
    channel_requests,
    clients,
    db,
    demo_agenda,
    emailing,
    messaging,
    portal,
    rag,
    security,
    settings,
    textnorm,
    timeutils,
    voice,
)
from backend.main import app

@app.get("/admin/template/{cliente_id}", dependencies=[Depends(security._require_admin_token)])
async def admin_template(cliente_id: str, request: Request) -> AdminClienteDetalle:
    textnorm._assert_valid_client_id(cliente_id)
    payload = portal._default_admin_payload(cliente_id)
    snippet = clients._build_install_snippet(cliente_id, request)
    return AdminClienteDetalle(
        cliente_id=cliente_id,
        config=payload,
        install_snippet=snippet["install_snippet"],
        widget_script_url=snippet["widget_script_url"],
        api_base_url=snippet["api_base_url"],
        demo_url=snippet["demo_url"],
    )


@app.post(
    "/admin/alta-express",
    dependencies=[Depends(security._require_admin_token)],
    response_model=AdminAltaExpressResponse,
)
async def admin_alta_express(
    data: AdminAltaExpressPayload,
    request: Request,
) -> AdminAltaExpressResponse:
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY no esta configurada en el backend.",
        )

    cliente_id = onboarding_utils.slugify_company(data.cliente_id)
    textnorm._assert_valid_client_id(cliente_id)

    try:
        result = onboarding_utils.run_onboarding(
            website_url=data.website_url,
            api_key=settings.OPENAI_API_KEY,
            nombre_bot=data.nombre_bot,
            tono=data.tono,
            idioma=data.idioma,
            max_paginas=data.max_paginas,
        )
        payload = portal._payload_from_alta_express(
            cliente_id=cliente_id,
            result=result,
            nombre_bot=data.nombre_bot,
            tono=data.tono,
            idioma=data.idioma,
            color=data.color,
            booking_enabled=data.booking_enabled,
            booking_timezone=data.booking_timezone,
        )
        payload.reindex_after_save = data.reindex_after_save
        clients._validate_single_client_runtime(cliente_id, portal._config_from_admin_payload(cliente_id, payload))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se ha podido completar el alta express: {exc}",
        ) from exc

    snippet = clients._build_install_snippet(cliente_id, request)
    save_result = None
    if data.auto_save:
        save_result = portal._save_admin_client_payload(cliente_id, payload, request)
        rag._seed_qa_from_onboarding(cliente_id, result)

    return AdminAltaExpressResponse(
        cliente_id=cliente_id,
        detected_business_name=result.detected_business_name,
        normalized_url=result.normalized_url,
        links_found=len(result.links),
        config=payload,
        saved=bool(save_result),
        reindexed=save_result.reindexed if save_result else False,
        reindex_error=save_result.reindex_error if save_result else "",
        install_snippet=(save_result.install_snippet if save_result else snippet["install_snippet"]),
        widget_script_url=(save_result.widget_script_url if save_result else snippet["widget_script_url"]),
        api_base_url=(save_result.api_base_url if save_result else snippet["api_base_url"]),
        demo_url=(save_result.demo_url if save_result else snippet["demo_url"]),
    )


@app.get(
    "/admin/clientes",
    dependencies=[Depends(security._require_admin_token)],
    response_model=List[AdminClienteResumen],
)
async def admin_clientes() -> List[AdminClienteResumen]:
    booking._auto_confirm_pending_bookings()
    summaries: List[AdminClienteResumen] = []
    booking_counts: Dict[str, Dict[str, int]] = {}
    owners_by_cliente: Dict[str, Dict[str, Any]] = {}
    with db._get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT cliente_id,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status IN ('confirmed', 'pending_review') THEN 1 ELSE 0 END) AS pending
            FROM bookings
            GROUP BY cliente_id
            """
        ).fetchall()
        booking_counts = {
            row["cliente_id"]: {
                "total": int(row["total"] or 0),
                "pending": int(row["pending"] or 0),
            }
            for row in rows
        }
        owner_rows = connection.execute(
            """
            SELECT c.cliente_id AS cliente_id,
                   c.owner_user_id AS owner_user_id,
                   c.created_at AS cliente_created_at,
                   u.email AS owner_email,
                   u.display_name AS owner_display_name,
                   u.last_login_at AS owner_last_login_at,
                   u.created_at AS owner_created_at
            FROM clientes c
            LEFT JOIN users u ON u.id = c.owner_user_id
            """
        ).fetchall()
        owners_by_cliente = {
            row["cliente_id"]: {
                "owner_user_id": row["owner_user_id"] or "",
                "owner_email": row["owner_email"] or "",
                "owner_display_name": row["owner_display_name"] or "",
                "owner_last_login_at": row["owner_last_login_at"] or "",
                "owner_created_at": row["owner_created_at"] or "",
                "cliente_created_at": row["cliente_created_at"] or "",
            }
            for row in owner_rows
        }

    demo_registry = demo_agenda._load_demo_registry()
    now_ts = time.time()

    for cliente_id, config in sorted(appstate.CONFIG_CLIENTES.items(), key=lambda item: item[0].lower()):
        owner_uid_early = (owners_by_cliente.get(cliente_id) or {}).get("owner_user_id") or ""
        booking_cfg = config.get("booking", {})
        whatsapp_cfg = config.get("whatsapp", {})
        voice_cfg = config.get("voice", {})
        contacto = config.get("contacto", {})
        branding = config.get("branding", {})
        info_path = rag._client_info_path(cliente_id)
        client_counts = booking_counts.get(cliente_id, {})

        # Reclamado (con dueño) => cliente real, no demo, aunque conserve el prefijo.
        is_demo = (
            cliente_id.startswith(demo_agenda.DEMO_TENANT_PREFIX) or cliente_id in demo_registry
        ) and not owner_uid_early
        demo_expires_at = ""
        demo_remaining = 0
        if is_demo and cliente_id in demo_registry:
            created_ts = demo_registry[cliente_id]
            expires_ts = created_ts + demo_agenda.DEMO_TTL_SECONDS
            demo_remaining = max(0, int(expires_ts - now_ts))
            demo_expires_at = datetime.fromtimestamp(expires_ts, tz=timezone.utc).isoformat()

        sub = clients._client_subscription(cliente_id) if not is_demo else {
            "plan": "", "status": "", "stripe_subscription_id": "",
            "messages_quota": 0, "messages_used_period": 0,
        }
        owner_info = owners_by_cliente.get(cliente_id, {})
        owner_uid = (owner_info.get("owner_user_id") or "").strip()
        if owner_uid:
            ss_sub = db.db_get_subscription_for_user(owner_uid)
            if ss_sub:
                sub = dict(sub)
                sub["plan"] = ss_sub["plan"] or sub.get("plan") or "free"
                sub["status"] = ss_sub["status"] or sub.get("status") or "active"
                sub["messages_quota"] = int(ss_sub["messages_quota"] or 0)
                sub["messages_used_period"] = int(ss_sub["messages_used_period"] or 0)

        summaries.append(
            AdminClienteResumen(
                cliente_id=cliente_id,
                nombre=config["nombre"],
                owner_user_id=owner_info.get("owner_user_id", ""),
                owner_email=owner_info.get("owner_email", ""),
                owner_display_name=owner_info.get("owner_display_name", ""),
                owner_last_login_at=owner_info.get("owner_last_login_at", ""),
                owner_created_at=owner_info.get("owner_created_at", ""),
                cliente_created_at=owner_info.get("cliente_created_at", ""),
                plan=str(sub.get("plan") or "free") if (owner_info.get("owner_user_id") or sub.get("plan")) else "",
                messages_used=int(sub.get("messages_used_period") or 0),
                messages_quota=int(sub.get("messages_quota") or 0),
                booking_enabled=bool(booking_cfg.get("enabled")),
                booking_provider=str(booking_cfg.get("provider", "internal")),
                booking_timezone=str(booking_cfg.get("timezone", settings.DEFAULT_TIMEZONE)),
                booking_day_start=str(booking_cfg.get("day_start", "09:00")),
                booking_day_end=str(booking_cfg.get("day_end", "18:00")),
                allowed_origins=list(config.get("allowed_origins", [])),
                contacto_email=str(contacto.get("email", "")),
                contacto_telefono=str(contacto.get("telefono", "")),
                branding_text=str(branding.get("powered_by", "")),
                whatsapp_enabled=bool(whatsapp_cfg.get("enabled", False)),
                whatsapp_phone_number_id=str(whatsapp_cfg.get("phone_number_id", "")),
                voice_enabled=bool(voice_cfg.get("enabled", False)),
                voice_phone_number=str(voice_cfg.get("twilio_phone_number", "")),
                voice_realtime_model=str(voice_cfg.get("realtime_model", "")),
                voice_realtime_model_effective=str(voice_cfg.get("realtime_model") or settings.VOICE_REALTIME_MODEL),
                has_info_file=info_path.exists(),
                info_file_size=(info_path.stat().st_size if info_path.exists() else 0),
                bookings_total=int(client_counts.get("total", 0)),
                bookings_pending=int(client_counts.get("pending", 0)),
                is_demo=is_demo,
                demo_expires_at=demo_expires_at,
                demo_expires_in_seconds=demo_remaining,
                subscription_plan=str(sub.get("plan") or ""),
                subscription_status=str(sub.get("status") or ""),
                stripe_subscription_id=str(sub.get("stripe_subscription_id") or ""),
            )
        )
    return summaries


@app.get(
    "/admin/clientes/{cliente_id}",
    dependencies=[Depends(security._require_admin_token)],
    response_model=AdminClienteDetalle,
)
async def admin_cliente_detalle(cliente_id: str, request: Request) -> AdminClienteDetalle:
    textnorm._assert_valid_client_id(cliente_id)
    config = clients._get_client_config(cliente_id)
    payload = portal._client_payload_from_config(config, rag._read_info_txt(cliente_id))
    snippet = clients._build_install_snippet(cliente_id, request)
    return AdminClienteDetalle(
        cliente_id=cliente_id,
        config=payload,
        install_snippet=snippet["install_snippet"],
        widget_script_url=snippet["widget_script_url"],
        api_base_url=snippet["api_base_url"],
        demo_url=snippet["demo_url"],
    )


@app.get(
    "/admin/clientes/{cliente_id}/audit",
    dependencies=[Depends(security._require_admin_token)],
    response_model=AdminClienteAuditResponse,
)
async def admin_cliente_audit(cliente_id: str) -> AdminClienteAuditResponse:
    textnorm._assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    def _duration_seconds(started_at: str, ended_at: str) -> Optional[int]:
        if not started_at or not ended_at:
            return None
        try:
            start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            return max(0, int((end_dt - start_dt).total_seconds()))
        except ValueError:
            return None

    with db._get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT admin_email, started_at, ended_at, ip, user_agent
            FROM admin_impersonations
            WHERE target_cliente_id = ?
            ORDER BY started_at DESC
            LIMIT 50
            """,
            (cliente_id,),
        ).fetchall()

    return AdminClienteAuditResponse(
        cliente_id=cliente_id,
        items=[
            AdminClienteAuditEntry(
                admin_email=row["admin_email"] or "",
                started_at=row["started_at"] or "",
                ended_at=row["ended_at"] or "",
                ip=row["ip"] or "",
                user_agent=row["user_agent"] or "",
                duration_seconds=_duration_seconds(row["started_at"] or "", row["ended_at"] or ""),
            )
            for row in rows
        ],
    )


@app.put(
    "/admin/clientes/{cliente_id}",
    dependencies=[Depends(security._require_admin_token)],
    response_model=AdminClienteSaveResult,
)
async def admin_guardar_cliente(
    cliente_id: str,
    data: AdminClientePayload,
    request: Request,
) -> AdminClienteSaveResult:
    textnorm._assert_valid_client_id(cliente_id)
    return portal._save_admin_client_payload(cliente_id, data, request)


@app.delete(
    "/admin/clientes/{cliente_id}",
    dependencies=[Depends(security._require_admin_token)],
    response_model=AuthSimpleResponse,
)
async def admin_eliminar_cliente(cliente_id: str) -> AuthSimpleResponse:
    clients._delete_client_everywhere(cliente_id)
    return AuthSimpleResponse(ok=True, message=f"Cliente {cliente_id} eliminado correctamente.")


@app.post(
    "/admin/clientes/{cliente_id}/demo-agenda",
    dependencies=[Depends(security._require_admin_token)],
    response_model=AuthSimpleResponse,
)
async def admin_generar_demo_agenda(cliente_id: str) -> AuthSimpleResponse:
    """Genera datos de demostracion en la agenda del cliente (~1 mes de citas
    repartidas entre varios profesionales) para que vea como luce su calendario.
    Es idempotente: regenera limpiando los datos demo anteriores."""
    textnorm._assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    result = demo_agenda._seed_demo_agenda(cliente_id)
    com = result.get("commerce", {}) or {}
    return AuthSimpleResponse(
        ok=True,
        message=(
            f"Demo generada: {result['bookings_created']} citas en "
            f"{result['employees_created']} profesionales, "
            f"{com.get('locations', 0)} centros, {com.get('products', 0)} productos, "
            f"{com.get('packages', 0)} bonos, {com.get('gift_cards', 0)} tarjetas regalo "
            f"y {com.get('sales', 0)} ventas."
        ),
    )


@app.delete(
    "/admin/clientes/{cliente_id}/demo-agenda",
    dependencies=[Depends(security._require_admin_token)],
    response_model=AuthSimpleResponse,
)
async def admin_borrar_demo_agenda(cliente_id: str) -> AuthSimpleResponse:
    """Borra todos los datos de demostracion de la agenda del cliente
    (citas con source='demo_seed' y profesionales demo 'empdemo_*')."""
    textnorm._assert_valid_client_id(cliente_id)
    result = demo_agenda._purge_demo_agenda(cliente_id)
    com = result.get("commerce", {}) or {}
    return AuthSimpleResponse(
        ok=True,
        message=(
            f"Demo eliminada: {result['bookings_removed']} citas, "
            f"{result['employees_removed']} profesionales, "
            f"{com.get('locations', 0)} centros, {com.get('products', 0)} productos, "
            f"{com.get('packages', 0)} bonos, {com.get('gift_cards', 0)} tarjetas regalo "
            f"y {com.get('sales', 0)} ventas demo."
        ),
    )


class AdminServicePatchPayload(BaseModel):
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=600)
    price_cents: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


@app.patch(
    "/admin/services/{cliente_id}/{slug}",
    dependencies=[Depends(security._require_admin_token)],
)
async def admin_patch_service(
    cliente_id: str,
    slug: str,
    data: AdminServicePatchPayload,
) -> Dict[str, Any]:
    """Actualiza duración, precio o estado de un servicio del catálogo sin requerir sesión portal."""
    textnorm._assert_valid_client_id(cliente_id)
    updates: Dict[str, Any] = {}
    if data.duration_minutes is not None:
        updates["duration_minutes"] = int(data.duration_minutes)
    if data.price_cents is not None:
        updates["price_cents"] = int(data.price_cents)
    if data.is_active is not None:
        updates["is_active"] = 1 if data.is_active else 0
    if not updates:
        raise HTTPException(status_code=400, detail="Nada que actualizar.")
    updates["updated_at"] = timeutils._utc_now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db._get_db_connection() as conn:
        row = conn.execute(
            "SELECT slug FROM services WHERE cliente_id = ? AND slug = ?", (cliente_id, slug)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Servicio '{slug}' no encontrado para {cliente_id}.")
        conn.execute(
            f"UPDATE services SET {set_clause} WHERE cliente_id = ? AND slug = ?",
            (*updates.values(), cliente_id, slug),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT slug, name, duration_minutes, price_cents, is_active FROM services WHERE cliente_id = ? AND slug = ?",
            (cliente_id, slug),
        ).fetchone()
    return {"ok": True, "slug": updated["slug"], "name": updated["name"],
            "duration_minutes": updated["duration_minutes"], "price_cents": updated["price_cents"],
            "is_active": bool(updated["is_active"])}


class AdminVoicePayload(BaseModel):
    enabled: Optional[bool] = None
    twilio_phone_number: Optional[str] = Field(default=None, max_length=32)
    openai_voice: Optional[str] = Field(default=None, max_length=40)
    realtime_model: Optional[str] = Field(default=None, max_length=40)
    greeting: Optional[str] = Field(default=None, max_length=600)
    request_id: Optional[str] = Field(default=None, max_length=80)


@app.post("/admin/clientes/{cliente_id}/voice", dependencies=[Depends(security._require_admin_token)])
async def admin_set_voice(cliente_id: str, data: AdminVoicePayload) -> Dict[str, Any]:
    """Activa/configura el canal de voz de un cliente sin requerir sesión portal.

    Persiste el cambio en config.json (duradero: el deploy preserva el config de
    producción). Devuelve también diagnóstico del gate de plan y de las credenciales
    Twilio del backend para depurar por qué una llamada podría no entrar.
    """
    textnorm._assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail=f"Cliente '{cliente_id}' no encontrado.")
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        voice_row = dict(cfg.get("voice", {}) or {})
        if data.enabled is not None:
            if data.enabled and not voice._client_voice_plan_enabled(cliente_id):
                raise HTTPException(
                    status_code=403,
                    detail="El asistente de voz requiere plan Business para este cliente.",
                )
            voice_row["enabled"] = bool(data.enabled)
        if data.twilio_phone_number is not None:
            voice_row["twilio_phone_number"] = textnorm._sanitize_text(data.twilio_phone_number)[:32]
        if data.openai_voice is not None:
            v = textnorm._sanitize_text(data.openai_voice).lower()
            voice_row["openai_voice"] = v if v in textnorm.VOICE_ALLOWED_OPENAI_VOICES else (voice_row.get("openai_voice") or "alloy")
        if data.realtime_model is not None:
            m = textnorm._sanitize_text(data.realtime_model)
            # Vacio = usar el default global; valor valido = override por cliente.
            if not m:
                voice_row.pop("realtime_model", None)
            elif m in settings.VOICE_REALTIME_MODELS:
                voice_row["realtime_model"] = m
            else:
                raise HTTPException(status_code=400, detail="Modelo de voz no permitido.")
        if data.greeting is not None:
            voice_row["greeting"] = textnorm._sanitize_text(data.greeting, allow_multiline=True)[:600]
        cfg["voice"] = voice_row
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    if data.request_id:
        try:
            channel_requests.update_request_status(data.request_id, status="active", admin_notes="Voz activada desde admin.")
        except KeyError:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada.") from None
    resolved = voice._get_voice_config(cliente_id)
    return {
        "ok": True,
        "cliente_id": cliente_id,
        "voice_enabled": bool(voice_row.get("enabled")),
        "twilio_phone_number": voice_row.get("twilio_phone_number", ""),
        "realtime_model": voice_row.get("realtime_model", ""),
        "realtime_model_effective": voice_row.get("realtime_model") or settings.VOICE_REALTIME_MODEL,
        "realtime_models": list(settings.VOICE_REALTIME_MODELS),
        "realtime_model_default": settings.VOICE_REALTIME_MODEL,
        "plan_allows_voice": voice._client_voice_plan_enabled(cliente_id),
        "twilio_backend_configured": messaging._voice_twilio_configured(),
        "openai_configured": bool(settings.OPENAI_API_KEY),
        "webhook_active": resolved is not None,
        "webhook_url": f"{settings.APP_BASE_URL.rstrip('/')}/voice/{cliente_id}" if settings.APP_BASE_URL else f"/voice/{cliente_id}",
    }


@app.get("/admin/channel-requests", dependencies=[Depends(security._require_admin_token)])
async def admin_channel_requests(
    status: str = "",
    cliente_id: str = "",
    limit: int = 100,
) -> Dict[str, Any]:
    return {
        "ok": True,
        "items": channel_requests.list_requests(status=status.strip(), cliente_id=cliente_id.strip(), limit=limit),
    }


@app.post("/admin/channel-requests/{request_id}", dependencies=[Depends(security._require_admin_token)])
async def admin_channel_request_update(
    request_id: str,
    data: AdminChannelRequestUpdatePayload,
) -> Dict[str, Any]:
    try:
        item = channel_requests.update_request_status(
            request_id, status=data.status, admin_notes=data.admin_notes
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "item": item}


@app.post("/admin/clientes/{cliente_id}/sms", dependencies=[Depends(security._require_admin_token)])
async def admin_set_sms(cliente_id: str, data: AdminSmsSettingsPayload) -> Dict[str, Any]:
    textnorm._assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail=f"Cliente '{cliente_id}' no encontrado.")
    if data.mode not in {"vantelia_default", "twilio_alphanumeric_sender", "twilio_dedicated_number"}:
        raise HTTPException(status_code=400, detail="Modo SMS no valido.")
    if data.sender_status not in {"not_configured", "pending_registration", "active", "error"}:
        raise HTTPException(status_code=400, detail="Estado SMS no valido.")
    sender = data.sender.strip()
    if data.mode == "twilio_dedicated_number" and not re.fullmatch(r"\+[1-9]\d{7,14}", sender):
        raise HTTPException(status_code=400, detail="El numero SMS debe estar en formato E.164.")
    if data.mode == "twilio_alphanumeric_sender":
        sender = sender.upper()
        if not re.fullmatch(r"(?=.*[A-Z])[A-Z0-9 ]{3,11}", sender):
            raise HTTPException(status_code=400, detail="El Sender ID debe tener 3-11 caracteres y alguna letra.")
    security._ensure_channel_settings(cliente_id)
    current = security._ensure_channel_settings(cliente_id)
    sid_encrypted = current["sms_twilio_account_sid_encrypted"] or ""
    token_encrypted = current["sms_twilio_auth_token_encrypted"] or ""
    if data.account_sid.strip():
        if not re.fullmatch(r"AC[a-zA-Z0-9]{8,}", data.account_sid.strip()):
            raise HTTPException(status_code=400, detail="Account SID de Twilio no valido.")
        sid_encrypted = security._encrypt_channel_secret(data.account_sid.strip())
    if data.auth_token.strip():
        if len(data.auth_token.strip()) < 12:
            raise HTTPException(status_code=400, detail="Auth Token de Twilio no valido.")
        token_encrypted = security._encrypt_channel_secret(data.auth_token.strip())
    with db._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE client_channel_settings
            SET sms_mode=?, sms_sender=?, sms_sender_status=?,
                sms_twilio_account_sid_encrypted=?, sms_twilio_auth_token_encrypted=?,
                updated_at=?
            WHERE cliente_id=?
            """,
            (
                data.mode,
                sender,
                data.sender_status,
                sid_encrypted,
                token_encrypted,
                timeutils._utc_now_iso(),
                cliente_id,
            ),
        )
        connection.commit()
    security._channel_audit(cliente_id, "sms", "admin_configured", data.mode, True, data.sender_status)
    if data.request_id:
        try:
            channel_requests.update_request_status(
                data.request_id,
                status="active" if data.sender_status == "active" else "in_progress",
                admin_notes="SMS actualizado desde admin.",
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada.") from None
    public = emailing._channel_settings_public(cliente_id).model_dump()
    return {"ok": True, "cliente_id": cliente_id, "sms": public["sms"]}


class AdminClienteAssignOwnerPayload(BaseModel):
    email: EmailStr
    plan: str = Field(default="free", max_length=40)


@app.post(
    "/admin/clientes/{cliente_id}/assign-owner",
    dependencies=[Depends(security._require_admin_token)],
    response_model=AuthSimpleResponse,
)
async def admin_assign_cliente_owner(
    cliente_id: str,
    data: AdminClienteAssignOwnerPayload,
) -> AuthSimpleResponse:
    """Admin path for migrating legacy clientes into the self-serve model.

    Looks up (or rejects if missing) a user by email, binds them as the
    owner_user_id of cliente_id, and seeds a subscription. Used to migrate
    existing config.json clients into Vantelia 2.0 without forcing them to
    re-register through the wizard."""
    textnorm._assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    target_email = textnorm._normalize_email(data.email)
    user = security._get_user_by_email(target_email)
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"No existe usuario con email {target_email}. Crealo primero (POST /auth/users) o usa /auth/signup.",
        )
    existing_cid = (user["cliente_id"] or "").strip()
    if existing_cid and existing_cid != cliente_id:
        raise HTTPException(
            status_code=409,
            detail=f"El usuario ya tiene asignado el bot {existing_cid}.",
        )
    db.db_set_client_owner(cliente_id, user["id"], source="admin_migration")
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET cliente_id = ? WHERE id = ?",
            (cliente_id, user["id"]),
        )
        connection.commit()
    # Seed subscription with the requested plan (default free).
    plan_slug = (data.plan or "free").lower()
    if plan_slug not in settings.SELF_SERVE_PLANS:
        plan_slug = "free"
    if plan_slug == "free":
        db.db_ensure_free_subscription(user["id"], cliente_id=cliente_id)
    else:
        db.db_set_subscription_from_stripe(
            user_id=user["id"],
            plan_slug=plan_slug,
            status="active",
        )
    return AuthSimpleResponse(
        ok=True,
        message=f"Cliente {cliente_id} asignado a {target_email} (plan {plan_slug}).",
    )


@app.post(
    "/admin/clientes/{cliente_id}/impersonate",
    response_model=AdminImpersonateResponse,
)
async def admin_impersonate_cliente(
    cliente_id: str,
    request: Request,
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
    admin: Dict[str, str] = Depends(portal._require_admin_identity),
) -> Response:
    """Admin opens cliente's portal as the cliente owner.

    Creates a short-lived auth_sessions row stamped with impersonator_* fields,
    sets the portal cookie, and audits the action in admin_impersonations.
    The portal banner picks up the impersonation flag via /auth/me.
    """
    textnorm._assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT owner_user_id FROM clientes WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchone()
    target_user_id = (row["owner_user_id"] if row else "") or ""
    if not target_user_id:
        raise HTTPException(
            status_code=409,
            detail="El cliente no tiene un owner asignado. Usa /admin/clientes/{id}/assign-owner primero.",
        )
    target_user = security._get_user_by_id(target_user_id)
    if not target_user or not target_user["is_active"]:
        raise HTTPException(status_code=409, detail="El owner del cliente no está activo.")
    if target_user["role"] == "admin":
        raise HTTPException(status_code=403, detail="No se puede impersonar a otro admin.")

    ip = request.client.host if request.client else ""
    user_agent = (request.headers.get("user-agent") or "")[:512]
    raw_token, session_id = security._create_impersonation_session(
        target_user_id=target_user["id"],
        admin_user_id=admin["user_id"],
        admin_email=admin["email"],
        ip=ip,
    )
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO admin_impersonations
                (id, admin_user_id, admin_email, target_user_id, target_cliente_id,
                 session_id, started_at, ip, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"imp_{secrets.token_hex(8)}",
                admin["user_id"],
                admin["email"],
                target_user["id"],
                cliente_id,
                session_id,
                timeutils._utc_now_iso(),
                ip,
                user_agent,
            ),
        )
        connection.commit()

    settings.logger.info(
        "[admin] impersonate admin=%s cliente=%s target=%s ttl_min=%s",
        admin["email"], cliente_id, target_user["email"], security.ADMIN_IMPERSONATION_TTL_MINUTES,
    )

    response = JSONResponse(
        AdminImpersonateResponse(
            ok=True,
            cliente_id=cliente_id,
            target_user_id=target_user["id"],
            target_email=target_user["email"],
            expires_in_minutes=security.ADMIN_IMPERSONATION_TTL_MINUTES,
            redirect_url="/app?as_admin=1",
        ).model_dump()
    )
    response.headers["Cache-Control"] = "no-store"
    if portal_session and admin.get("via") == "session":
        security._set_admin_return_cookie(response, portal_session)
    else:
        security._clear_admin_return_cookie(response)
    security._set_portal_cookie(response, raw_token)
    return response


@app.post(
    "/admin/impersonate/end",
    response_model=AdminImpersonateEndResponse,
)
async def admin_impersonate_end(
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
    admin_return_session: Optional[str] = Cookie(default=None, alias=settings.ADMIN_RETURN_COOKIE_NAME),
) -> Response:
    """Closes the impersonated session and returns the admin to the dashboard.

    Safe to call without admin auth: the cookie itself proves ownership of
    the impersonation. If the cookie is not an impersonation, behaves as a
    plain logout for that token.
    """
    user_row = security._get_authenticated_portal_user_or_none(portal_session)
    was_impersonated = security._session_is_impersonated(user_row)
    if was_impersonated:
        admin_email = security._session_impersonator_email(user_row)
        with db._get_db_connection() as connection:
            connection.execute(
                "UPDATE admin_impersonations SET ended_at = ? WHERE session_id = ? AND ended_at = ''",
                (timeutils._utc_now_iso(), user_row["session_id"]),
            )
            connection.commit()
        settings.logger.info("[admin] impersonate end admin=%s session=%s", admin_email, user_row["session_id"])
    if portal_session:
        security._delete_auth_session(portal_session)
    admin_redirect_url = "/acceso"
    admin_row = security._get_authenticated_portal_user_or_none(admin_return_session) if was_impersonated else None
    response = JSONResponse(
        AdminImpersonateEndResponse(
            ok=True,
            admin_redirect_url="/dashboard" if admin_row and admin_row["role"] == "admin" else admin_redirect_url,
        ).model_dump()
    )
    response.headers["Cache-Control"] = "no-store"
    if admin_row and admin_row["role"] == "admin":
        security._set_portal_cookie(response, admin_return_session or "")
    else:
        security._clear_portal_cookie(response)
    security._clear_admin_return_cookie(response)
    return response


@app.get(
    "/admin/bookings",
    dependencies=[Depends(security._require_admin_token)],
    response_model=List[AdminBookingResumen],
)
async def admin_bookings(
    request: Request,
    cliente_id: str = "",
    estado: str = "",
    q: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
    limit: int = 100,
) -> List[AdminBookingResumen]:
    booking._auto_confirm_pending_bookings()
    booking._auto_complete_past_bookings()
    rows, _ = booking._list_booking_rows(
        cliente_id=cliente_id.strip(),
        status_filter=estado.strip(),
        search=q.strip(),
        date_from=fecha_desde.strip(),
        date_to=fecha_hasta.strip(),
        limit=max(1, min(limit, 500)),
    )
    return [booking._booking_admin_summary_from_row(row, request) for row in rows]


@app.post(
    "/admin/bookings/{booking_id}/cancel",
    dependencies=[Depends(security._require_admin_token)],
    response_model=BookingActionResponse,
)
async def admin_cancel_booking(booking_id: str, request: Request) -> BookingActionResponse:
    booking_row = booking._load_booking_or_404(booking_id)
    if booking_row["status"] == "cancelled":
        return BookingActionResponse(
            ok=True,
            booking_id=booking_id,
            estado="cancelled",
            mensaje="La cita ya estaba cancelada.",
            manage_url=booking._booking_row_manage_url(booking_row, request),
            provider_booking_url=booking_row["provider_booking_url"] or "",
        )

    refreshed = await booking._cancel_booking_core(booking_row, source="admin", request=request)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado="cancelled",
        mensaje="La cita ha sido cancelada.",
        manage_url=booking._booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
    )


@app.post(
    "/admin/bookings/{booking_id}/reschedule",
    dependencies=[Depends(security._require_admin_token)],
    response_model=BookingActionResponse,
)
async def admin_reschedule_booking(
    booking_id: str,
    data: BookingReschedulePayload,
    request: Request,
) -> BookingActionResponse:
    booking_row = booking._load_booking_or_404(booking_id)
    return await booking._update_booking_details(
        booking_row,
        booking._booking_update_payload_from_reschedule(booking_row, data),
        request,
        source="admin",
    )


@app.post(
    "/admin/bookings/{booking_id}/resend-email",
    dependencies=[Depends(security._require_admin_token)],
    response_model=BookingActionResponse,
)
async def admin_resend_booking_email(booking_id: str, request: Request) -> BookingActionResponse:
    booking_row = booking._load_booking_or_404(booking_id)
    kind = "received" if booking_row["status"] == "pending_review" else "confirmed"
    if booking_row["status"] == "cancelled":
        kind = "cancelled"
    await booking._send_booking_email_by_kind(booking_row, kind, request, respect_enabled=False)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado=booking_row["status"],
        mensaje="Correo reenviado correctamente.",
        manage_url=booking._booking_row_manage_url(booking_row, request),
        provider_booking_url=booking_row["provider_booking_url"] or "",
    )


@app.get(
    "/admin/bookings/{booking_id}/timeline",
    dependencies=[Depends(security._require_admin_token)],
    response_model=BookingAuditResponse,
)
async def admin_booking_timeline(booking_id: str) -> BookingAuditResponse:
    booking._load_booking_or_404(booking_id)
    return BookingAuditResponse(items=[booking._booking_audit_entry_from_row(row) for row in booking._list_booking_audit_rows(booking_id)])


@app.get(
    "/admin/chats",
    dependencies=[Depends(security._require_admin_token)],
    response_model=List[ChatSessionSummary],
)
async def admin_chats(
    cliente_id: str = "",
    limit: int = 50,
    offset: int = 0,
) -> List[ChatSessionSummary]:
    if cliente_id:
        clients._get_client_config(cliente_id)
    return [
        rag._chat_session_summary_from_row(row)
        for row in rag._list_chat_session_rows(
            cliente_id=cliente_id.strip(),
            limit=limit,
            offset=offset,
        )
    ]


@app.get(
    "/admin/chats/{session_id}",
    dependencies=[Depends(security._require_admin_token)],
    response_model=ChatSessionDetail,
)
async def admin_chat_detail(session_id: str, cliente_id: str = "") -> ChatSessionDetail:
    if cliente_id:
        clients._get_client_config(cliente_id)
    session_row = rag._load_chat_session_or_404(session_id, cliente_id=cliente_id.strip())
    return ChatSessionDetail(
        session=rag._chat_session_summary_from_row(session_row),
        messages=[rag._chat_message_from_row(row) for row in rag._load_chat_message_rows(session_id)],
    )


@app.post(
    "/admin/bookings/reminders/run",
    dependencies=[Depends(security._require_admin_token)],
    response_model=AdminReminderRunResult,
)
async def admin_run_booking_reminders(request: Request) -> AdminReminderRunResult:
    return await booking._run_booking_reminders(request)


