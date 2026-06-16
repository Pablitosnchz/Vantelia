"""Endpoints: seccion portal_app (refactor F3).

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

@app.post("/auth/password/change", response_model=AuthSimpleResponse)
async def auth_change_password(
    data: AuthPasswordChangePayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Response:
    if security._session_is_impersonated(user):
        raise HTTPException(
            status_code=403,
            detail="Acción bloqueada en sesión de admin (impersonación). Cierra la sesión admin para cambiar la contraseña.",
        )
    if not security._verify_secret(data.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="La contrasena actual no es correcta.")
    if data.current_password == data.new_password:
        raise HTTPException(status_code=400, detail="La nueva contrasena debe ser distinta a la actual.")

    security._update_user_password(user["id"], data.new_password)
    security._delete_user_auth_sessions(user["id"])
    raw_token = security._create_auth_session(user["id"])
    response = JSONResponse(
        AuthSimpleResponse(ok=True, message="Contrasena actualizada correctamente.").model_dump()
    )
    security._set_portal_cookie(response, raw_token)
    return response


@app.post("/auth/password/forgot", response_model=AuthSimpleResponse)
async def auth_forgot_password(
    data: AuthPasswordForgotPayload,
    request: Request,
) -> AuthSimpleResponse:
    if not emailing._email_delivery_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La recuperacion por correo no esta disponible todavia. Configura SMTP en el servidor.",
        )

    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"password-reset:{client_ip}", 5)

    user = security._get_user_by_email(data.email)
    if user and user["is_active"]:
        public_token = security._create_password_reset_token(user["id"], requested_from_ip=client_ip)
        try:
            emailing._send_password_reset_email(user, public_token, request)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("No se ha podido enviar el email de reset a %s: %s", user["email"], exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No se ha podido enviar el correo de recuperacion. Revisa la configuracion SMTP.",
            ) from exc

    return AuthSimpleResponse(
        ok=True,
        message="Si el correo esta registrado, se te enviara un enlace para cambiar la contrasena.",
        retry_after_seconds=max(0, settings.PASSWORD_RESET_RESEND_SECONDS),
    )


@app.post("/auth/password/reset", response_model=AuthSimpleResponse)
async def auth_reset_password(data: AuthPasswordResetPayload) -> AuthSimpleResponse:
    reset_row = security._consume_password_reset_token(data.token)
    if security._verify_secret(data.new_password, reset_row["password_hash"]):
        raise HTTPException(status_code=400, detail="La nueva contrasena debe ser distinta a la actual.")

    security._update_user_password(reset_row["user_id"], data.new_password)
    security._delete_user_auth_sessions(reset_row["user_id"])
    return AuthSimpleResponse(ok=True, message="Contrasena restablecida correctamente. Ya puedes iniciar sesion.")


@app.get("/auth/me", response_model=AuthUserPublic)
async def auth_me(user: sqlite3.Row = Depends(security._require_authenticated_portal_user)) -> AuthUserPublic:
    return security._serialize_auth_user(user)


@app.post("/auth/profile", response_model=AuthUserPublic)
async def auth_update_profile(
    data: AuthProfileUpdatePayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthUserPublic:
    updated = security._update_user_profile(
        user["id"],
        email=str(data.email),
        display_name=data.display_name,
    )
    return security._serialize_auth_user(updated)


@app.get("/auth/dashboard", response_model=PortalDashboardResponse)
async def auth_dashboard_data(
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalDashboardResponse:
    booking._auto_confirm_pending_bookings()
    booking._auto_complete_past_bookings()
    target_client_id = portal._portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    bookings, _ = booking._list_booking_rows(cliente_id=target_client_id, limit=6, scope="upcoming")
    today_bookings: List[PortalBookingSummary] = []
    today_blocks: List[PortalAgendaBlock] = []
    if target_client_id:
        today_bookings, today_blocks = portal._portal_today_dashboard(target_client_id, request)
    install_assets = clients._build_install_snippet(target_client_id, request) if target_client_id else {}
    return PortalDashboardResponse(
        user=security._serialize_auth_user(user),
        stats=portal._portal_stats_for_user(user, target_client_id),
        bookings_upcoming=[booking._portal_booking_summary_from_row(row, request) for row in bookings],
        bookings_today=today_bookings,
        today_blocks=today_blocks,
        install_snippet=install_assets.get("install_snippet", ""),
        widget_script_url=install_assets.get("widget_script_url", ""),
        api_base_url=install_assets.get("api_base_url", ""),
        demo_url=install_assets.get("demo_url", ""),
    )


@app.get("/auth/bookings", response_model=PortalBookingsResponse)
async def auth_bookings(
    request: Request,
    cliente_id: str = "",
    estado: str = "",
    employee_id: str = "",
    location_id: str = "",
    scope: str = "all",
    q: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 20,
    offset: int = 0,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalBookingsResponse:
    booking._auto_confirm_pending_bookings()
    booking._auto_complete_past_bookings()
    target_client_id = portal._portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    normalized_scope = scope.strip().lower() or "all"
    if normalized_scope not in {"all", "upcoming", "history"}:
        raise HTTPException(status_code=400, detail="Scope invalido.")
    date_from_clean = date_from.strip()
    date_to_clean = date_to.strip()
    cap = booking._portal_bookings_effective_cap(date_from_clean, date_to_clean)
    effective_limit = max(1, min(limit, cap))
    location_filter = (
        agenda._resolve_location_id(target_client_id, location_id.strip())
        if (location_id.strip() and target_client_id) else ""
    )
    rows, total = booking._list_booking_rows(
        cliente_id=target_client_id,
        employee_id=employee_id.strip(),
        location_id=location_filter,
        status_filter=estado.strip(),
        search=q.strip(),
        date_from=date_from_clean,
        date_to=date_to_clean,
        limit=effective_limit,
        offset=max(0, offset),
        scope=normalized_scope,
    )
    return PortalBookingsResponse(
        items=booking._portal_booking_summaries(rows, request, cliente_id=target_client_id),
        total=total,
        limit=effective_limit,
        offset=max(0, offset),
        scope=normalized_scope,
    )


@app.get("/auth/bookings/export")
async def auth_export_bookings(
    cliente_id: str = "",
    date_from: str = "",
    date_to: str = "",
    estado: str = "",
    employee_id: str = "",
    q: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Response:
    target_client_id = portal._portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    if target_client_id and not portal._is_admin_client_portal_override(user, cliente_id):
        clients._require_plan_feature(
            target_client_id,
            "csv_export",
            "La exportacion CSV esta disponible desde el plan Starter.",
        )
    rows, _ = booking._list_booking_rows(
        cliente_id=target_client_id,
        employee_id=employee_id.strip(),
        status_filter=estado.strip(),
        search=q.strip(),
        date_from=date_from.strip(),
        date_to=date_to.strip(),
        limit=5000,
        scope="all",
    )
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Fecha", "Hora", "Profesional", "Estado", "Nombre", "Email", "Telefono", "Servicio", "Notas"])
    for row in rows:
        writer.writerow(
            [
                row["id"],
                row["booking_date"],
                row["booking_time"],
                row["employee_name"] or "",
                row["status"],
                row["nombre"],
                row["email"],
                row["telefono"] or "",
                row["servicio"] or "",
                row["notas"] or "",
            ]
        )
    filename = f"citas_{date_from or 'inicio'}_{date_to or 'fin'}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/auth/chats", response_model=List[ChatSessionSummary])
async def auth_chats(
    cliente_id: str = "",
    limit: int = 50,
    offset: int = 0,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> List[ChatSessionSummary]:
    target_client_id = portal._portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    return [
        rag._chat_session_summary_from_row(row)
        for row in rag._list_chat_session_rows(
            cliente_id=target_client_id,
            limit=limit,
            offset=offset,
        )
    ]


@app.get("/auth/chats/{session_id}", response_model=ChatSessionDetail)
async def auth_chat_detail(
    session_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ChatSessionDetail:
    target_client_id = portal._portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    session_row = rag._load_chat_session_or_404(session_id, cliente_id=target_client_id)
    return ChatSessionDetail(
        session=rag._chat_session_summary_from_row(session_row),
        messages=[rag._chat_message_from_row(row) for row in rag._load_chat_message_rows(session_id)],
    )


@app.get("/auth/app/alerts")
async def app_alerts(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Bandeja de avisos operativos: citas sin confirmar, retenciones por capturar,
    pagos fallidos y stock bajo. Conteos rapidos para el badge del panel."""
    target = portal._portal_client_id_or_403(user, cliente_id)
    now_iso = timeutils._utc_now_iso()
    items: List[Dict[str, Any]] = []
    with db._get_db_connection() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE cliente_id=? AND status='pending_review' AND start_at>=?",
            (target, now_iso),
        ).fetchone()[0]
        preauth = conn.execute(
            "SELECT COUNT(*) FROM booking_payments WHERE cliente_id=? AND status='preauthorized'",
            (target,),
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM customer_payments WHERE cliente_id=? AND status='failed'",
            (target,),
        ).fetchone()[0]
        low_stock = conn.execute(
            "SELECT COUNT(*) FROM products WHERE cliente_id=? AND is_active=1 AND stock IS NOT NULL AND stock<=3",
            (target,),
        ).fetchone()[0]
    if pending:
        items.append({"type": "pending_bookings", "count": int(pending), "tab": "citas",
                      "label": f"{pending} cita(s) sin confirmar", "severity": "warn"})
    if preauth and security._user_has_permission(user, "payments.capture"):
        items.append({"type": "preauth_hold", "count": int(preauth), "tab": "citas",
                      "label": f"{preauth} retención(es) por cobrar o liberar", "severity": "warn"})
    if failed and security._user_has_permission(user, "payments.refund"):
        items.append({"type": "failed_payments", "count": int(failed), "tab": "citas",
                      "label": f"{failed} pago(s) fallido(s)", "severity": "danger"})
    if low_stock and security._user_has_permission(user, "catalog.manage"):
        items.append({"type": "low_stock", "count": int(low_stock), "tab": "ventas",
                      "label": f"{low_stock} producto(s) con stock bajo", "severity": "warn"})
    return {"total": sum(i["count"] for i in items), "items": items}


@app.get("/auth/conversations", response_model=ConversationsResponse)
async def auth_conversations(
    cliente_id: str = "",
    channel: str = "",
    q: str = "",
    limit: int = 80,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ConversationsResponse:
    """Historial unificado: chat web, WhatsApp y llamadas de voz en una sola lista,
    etiquetadas por canal y ordenadas por actividad reciente."""
    target = portal._portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    channel = (channel or "").strip().lower()
    items: List[Dict[str, Any]] = []
    if channel in ("", "web", "whatsapp"):
        for row in rag._list_chat_session_rows(cliente_id=target, limit=200):
            d = rag._conversation_chat_dict(row)
            if channel and d["channel"] != channel:
                continue
            items.append(d)
    if channel in ("", "voice"):
        for row in voice._list_voice_calls(target, limit=200):
            items.append(voice._voice_conversation_dict(row))
    ql = (q or "").strip().lower()
    if ql:
        items = [c for c in items if ql in (str(c.get("contact", "")) + " " + str(c.get("preview", ""))).lower()]
    items.sort(key=lambda c: c.get("last_at") or c.get("started_at") or "", reverse=True)
    capped = items[: max(1, min(int(limit or 80), 200))]
    return ConversationsResponse(items=[ConversationSummary(**c) for c in capped])


@app.get("/auth/conversations/{kind}/{conv_id}", response_model=ConversationDetail)
async def auth_conversation_detail(
    kind: str,
    conv_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ConversationDetail:
    target = portal._portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    if kind == "voice":
        d = voice._voice_call_detail_dict(conv_id, cliente_id=target)
        return ConversationDetail(
            conversation=ConversationSummary(**d["conversation"]),
            messages=[ConversationMessage(**m) for m in d["messages"]],
            summary_text=d["summary_text"],
        )
    session_row = rag._load_chat_session_or_404(conv_id, cliente_id=target)
    return ConversationDetail(
        conversation=ConversationSummary(**rag._conversation_chat_dict(session_row)),
        messages=[
            ConversationMessage(role=r["role"], content=r["content"], created_at=r["created_at"])
            for r in rag._load_chat_message_rows(conv_id)
        ],
        summary_text="",
    )


# --- Vantelia 2.0 dashboard endpoints (Sem 3) ---







@app.get("/auth/app/overview", response_model=AppOverviewResponse)
async def app_overview(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppOverviewResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    sub_row = db.db_get_subscription_for_user(user["id"]) or db.db_ensure_free_subscription(user["id"], cliente_id=cliente_id)
    period_start = security._period_start_iso_for_user(user["id"])
    stats = portal._compute_dashboard_stats(cliente_id, period_start)
    subscription = AppOverviewSubscription(
        plan=sub_row["plan"],
        status=sub_row["status"],
        messages_quota=int(sub_row["messages_quota"]),
        messages_used=int(sub_row["messages_used_period"]) or stats.messages_period,
        cancel_at_period_end=bool(sub_row["cancel_at_period_end"]),
        current_period_end=sub_row["current_period_end"] or "",
    )
    channels = AppOverviewChannels(
        web=True,
        whatsapp=bool(cfg.get("whatsapp", {}).get("enabled", False)),
        voice=bool(cfg.get("voice", {}).get("enabled", False)),
        booking=bool(cfg.get("booking", {}).get("enabled", False)),
    )
    return AppOverviewResponse(
        cliente_id=cliente_id,
        nombre=cfg.get("nombre", cliente_id),
        color=cfg.get("color", "#00b1d9"),
        icono=cfg.get("icono", "AI"),
        bienvenida=cfg.get("bienvenida", ""),
        subscription=subscription,
        stats=stats,
        channels=channels,
    )


@app.get("/auth/app/deploy", response_model=AppDeployResponse)
async def app_deploy(
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppDeployResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    assets = clients._build_install_snippet(cliente_id, request)
    api_base = assets["api_base_url"]
    share_link = f"{api_base}/demo/{cliente_id}"
    return AppDeployResponse(
        cliente_id=cliente_id,
        install_snippet=assets["install_snippet"],
        widget_script_url=assets["widget_script_url"],
        api_base_url=api_base,
        demo_url=assets["demo_url"],
        share_link=share_link,
        qr_data_url="",
    )


@app.post("/auth/app/track")
async def app_track_event(
    data: AppTrackEventPayload,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    cliente_id = (user["cliente_id"] or "").strip()
    allowed_events = {
        "bot_preview_message",
        "first_chat_tested",
        "snippet_copied",
        "share_link_copied",
        "demo_url_copied",
        "install_tab_opened",
        "pricing_viewed",
        "upgrade_clicked",
    }
    if data.event not in allowed_events:
        raise HTTPException(status_code=400, detail="Evento de app no permitido.")
    metadata = {
        key: value
        for key, value in (data.metadata or {}).items()
        if key in portal._ANALYTICS_ALLOWED_KEYS
    }
    payload: Dict[str, Any] = {
        "event": data.event,
        "event_source": "vantelia_app",
        "widget_client_id": cliente_id,
        "cliente_id": cliente_id,
        "user_id": user["id"],
        **metadata,
    }
    return portal._record_analytics_event(payload, request)


@app.get("/auth/app/appearance", response_model=AppAppearanceResponse)
async def app_appearance_get(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppAppearanceResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    state = onboarding._read_onboarding_state(cliente_id)
    launcher_shape = str(cfg.get("launcher_shape", "circle") or "circle").lower()
    if launcher_shape not in ("circle", "bar"):
        launcher_shape = "circle"
    try:
        launcher_size = int(cfg.get("launcher_size", 60) or 60)
    except (TypeError, ValueError):
        launcher_size = 60
    starters = cfg.get("starter_questions")
    if not starters:
        starters = state.get("starter_questions", []) or []
    return AppAppearanceResponse(
        ok=True,
        cliente_id=cliente_id,
        nombre=cfg.get("nombre", ""),
        color=cfg.get("color", "#00b1d9"),
        accent_color=cfg.get("accent_color", ""),
        icono=cfg.get("icono", "AI"),
        logo_url=cfg.get("logo_url", ""),
        launcher_shape=launcher_shape,
        launcher_size=launcher_size,
        bienvenida=cfg.get("bienvenida", ""),
        prompt_extra=cfg.get("prompt_extra", ""),
        starter_questions=list(starters),
        allowed_origins=list(cfg.get("allowed_origins", [])),
        booking_enabled=bool(cfg.get("booking", {}).get("enabled", True)),
    )


@app.post("/auth/app/appearance", response_model=AppAppearanceResponse)
async def app_appearance_post(
    data: AppAppearancePayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppAppearanceResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        if data.nombre is not None:
            cfg["nombre"] = textnorm._sanitize_text(data.nombre)[:120] or cliente_id
        if data.color is not None:
            color = textnorm._sanitize_text(data.color)
            if re.match(r"^#[0-9A-Fa-f]{6}$", color):
                cfg["color"] = color
        if data.accent_color is not None:
            ac = textnorm._sanitize_text(data.accent_color)
            cfg["accent_color"] = ac if (not ac or re.match(r"^#[0-9A-Fa-f]{6}$", ac)) else cfg.get("accent_color", "")
        if data.icono is not None:
            cfg["icono"] = textnorm._sanitize_text(data.icono)[:12] or "AI"
        if data.logo_url is not None:
            cfg["logo_url"] = textnorm._sanitize_text(data.logo_url)
        if data.launcher_shape is not None:
            shape = textnorm._sanitize_text(data.launcher_shape).lower()
            cfg["launcher_shape"] = shape if shape in ("circle", "bar") else "circle"
        if data.launcher_size is not None:
            try:
                size_val = int(data.launcher_size)
            except (TypeError, ValueError):
                size_val = 60
            current_shape = cfg.get("launcher_shape", "circle")
            if current_shape == "circle":
                cfg["launcher_size"] = max(48, min(96, size_val))
            else:
                cfg["launcher_size"] = max(120, min(280, size_val))
        if data.bienvenida is not None:
            cfg["bienvenida"] = textnorm._sanitize_text(data.bienvenida, allow_multiline=True)[:600]
        if data.prompt_extra is not None:
            cfg["prompt_extra"] = textnorm._sanitize_text(data.prompt_extra, allow_multiline=True)[:4000]
        if data.allowed_origins is not None:
            cleaned = []
            for origin in data.allowed_origins:
                normalized = textnorm._normalize_optional_http_url(origin)
                if normalized and normalized not in cleaned:
                    cleaned.append(normalized)
            cfg["allowed_origins"] = cleaned
        if data.starter_questions is not None:
            sanitized = [
                textnorm._sanitize_text(q)[:140] for q in data.starter_questions if textnorm._sanitize_text(q)
            ]
            cfg["starter_questions"] = settings._strip_base_from_extras(sanitized)
        if data.booking_enabled is not None:
            if not isinstance(cfg.get("booking"), dict):
                cfg["booking"] = {}
            cfg["booking"]["enabled"] = bool(data.booking_enabled)
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    if data.starter_questions is not None:
        state = onboarding._read_onboarding_state(cliente_id)
        state["starter_questions"] = cfg.get("starter_questions", [])
        onboarding._write_onboarding_state(cliente_id, state)
        try:
            rag._cleanup_orphan_starter_qa(cliente_id, cfg.get("starter_questions", []))
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("No se pudo limpiar Q&A huerfanas de starters %s: %s", cliente_id, exc)
    # Invalidate llama-index cache and active sessions so the next chat rebuilds the prompt.
    try:
        with appstate.state_lock:
            appstate.indices.pop(cliente_id, None)
            stale = [sid for sid, s in appstate.sesiones.items() if s.cliente_id == cliente_id]
            for sid in stale:
                appstate.sesiones.pop(sid, None)
    except NameError:
        pass
    return await app_appearance_get(user)


# --- CRM ligero ------------------------------------------------------------

CRM_CONTACT_SORTS = {
    "last_activity_desc": "c.last_seen_at DESC, c.id DESC",
    "last_activity_asc": "c.last_seen_at ASC, c.id ASC",
    "created_desc": "c.created_at DESC, c.id DESC",
    "created_asc": "c.created_at ASC, c.id ASC",
    "name_asc": "c.name COLLATE NOCASE ASC, c.id ASC",
    "name_desc": "c.name COLLATE NOCASE DESC, c.id DESC",
    "next_action_asc": "CASE WHEN c.next_action_at = '' THEN 1 ELSE 0 END, c.next_action_at ASC, c.id ASC",
    "next_action_desc": "CASE WHEN c.next_action_at = '' THEN 1 ELSE 0 END, c.next_action_at DESC, c.id DESC",
}
































@app.get("/auth/app/contacts", response_model=CRMContactsListResponse)
async def app_contacts_list(
    page: int = 1,
    page_size: int = 50,
    q: str = "",
    status_filter: str = "",
    tag: str = "",
    owner: str = "",
    source: str = "",
    next_action_filter: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "last_activity_desc",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> CRMContactsListResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    crm._crm_backfill_client(cliente_id)
    page, page_size = max(1, page), max(1, min(page_size, 200))
    where, params = crm._crm_contact_filters(
        cliente_id, q=q, status_filter=status_filter, tag=tag, owner=owner, source=source,
        next_action_filter=next_action_filter, date_from=date_from, date_to=date_to,
    )
    order_by = CRM_CONTACT_SORTS.get(sort, CRM_CONTACT_SORTS["last_activity_desc"])
    with db._get_db_connection() as connection:
        total = connection.execute(f"SELECT COUNT(*) FROM crm_contacts c WHERE {where}", tuple(params)).fetchone()[0]
        rows = crm._crm_contacts_query(
            connection, where, params, order_by=order_by,
            limit=page_size, offset=(page - 1) * page_size,
        )
        items = [crm._crm_contact_list_item(row) for row in rows]
    pages = (int(total or 0) + page_size - 1) // page_size
    return CRMContactsListResponse(items=items, total=int(total or 0), page=page, page_size=page_size, pages=pages)


@app.get("/auth/app/contacts/export.csv")
async def app_contacts_export(
    q: str = "",
    status_filter: str = "",
    tag: str = "",
    owner: str = "",
    source: str = "",
    next_action_filter: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "last_activity_desc",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Response:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    crm._crm_backfill_client(cliente_id)
    where, params = crm._crm_contact_filters(
        cliente_id, q=q, status_filter=status_filter, tag=tag, owner=owner, source=source,
        next_action_filter=next_action_filter, date_from=date_from, date_to=date_to,
    )
    order_by = CRM_CONTACT_SORTS.get(sort, CRM_CONTACT_SORTS["last_activity_desc"])
    with db._get_db_connection() as connection:
        rows = connection.execute(
            f"SELECT c.* FROM crm_contacts c WHERE {where} ORDER BY {order_by}",
            tuple(params),
        ).fetchall()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "name", "email", "phone", "status", "tags", "owner", "source_first", "source_last",
        "next_action", "next_action_at", "last_seen_at", "created_at", "notes",
    ])
    for row in rows:
        writer.writerow([
            row["name"], row["email"], row["phone"], row["status"],
            ", ".join(crm._crm_json_list(row["tags_json"])), row["owner"], row["source_first"],
            row["source_last"], row["next_action"], row["next_action_at"], row["last_seen_at"],
            row["created_at"], (row["notes"] or "").replace("\r", " ").replace("\n", " "),
        ])
    filename = f"contactos_{cliente_id}_{timeutils._utc_now().strftime('%Y%m%d')}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/auth/app/contacts", response_model=CRMContactPublic)
async def app_contact_create(
    data: CRMContactPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> CRMContactPublic:
    security._require_portal_permission(user, "clients.edit")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    contact_id = crm._crm_upsert_contact(
        cliente_id, name=data.name, email=data.email, phone=data.phone,
        source=data.source or "manual", status=data.status, actor=f"user:{user['id']}",
    )
    if not contact_id:
        raise HTTPException(status_code=400, detail="Indica al menos nombre, email o telefono.")
    return await app_contact_update(contact_id, data, user)


@app.put("/auth/app/contacts/{contact_id}", response_model=CRMContactPublic)
async def app_contact_update(
    contact_id: str,
    data: CRMContactPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> CRMContactPublic:
    security._require_portal_permission(user, "clients.edit")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    status_value = data.status if data.status in crm.CRM_CONTACT_STATUSES else "nuevo"
    tags = list(dict.fromkeys(textnorm._sanitize_text(tag)[:80] for tag in data.tags if textnorm._sanitize_text(tag)))[:30]
    email_norm, phone_norm = crm._normalize_crm_email(data.email), crm._normalize_crm_phone(data.phone)
    with db._get_db_connection() as connection:
        crm._crm_contact_or_404(connection, cliente_id, contact_id)
        for column, value in (("email_normalized", email_norm), ("phone_normalized", phone_norm)):
            if value and connection.execute(
                f"SELECT 1 FROM crm_contacts WHERE cliente_id = ? AND {column} = ? AND id <> ? LIMIT 1",
                (cliente_id, value, contact_id),
            ).fetchone():
                raise HTTPException(status_code=409, detail="Ese email o telefono ya pertenece a otro contacto.")
        connection.execute(
            """
            UPDATE crm_contacts SET name=?, email=?, email_normalized=?, phone=?, phone_normalized=?, search_text=?,
                status=?, notes=?, tags_json=?, owner=?, next_action=?, next_action_at=?, updated_at=?
            WHERE id=? AND cliente_id=?
            """,
            (
                textnorm._sanitize_text(data.name)[:200], textnorm._sanitize_text(data.email)[:200], email_norm,
                textnorm._sanitize_text(data.phone)[:80], phone_norm, crm._crm_search_text(data.name, data.email, data.phone), status_value,
                textnorm._sanitize_text(data.notes, allow_multiline=True)[:8000], json.dumps(tags, ensure_ascii=False),
                textnorm._sanitize_text(data.owner)[:200], textnorm._sanitize_text(data.next_action)[:500],
                textnorm._sanitize_text(data.next_action_at)[:40], timeutils._utc_now_iso(), contact_id, cliente_id,
            ),
        )
        crm._crm_audit(connection, cliente_id, contact_id, "contact_updated", {"status": status_value}, actor=f"user:{user['id']}")
        connection.commit()
        row = crm._crm_contact_or_404(connection, cliente_id, contact_id)
        return crm._crm_contact_public(row, connection)


@app.get("/auth/app/contacts/{contact_id}", response_model=CRMContactDetailResponse)
async def app_contact_detail(
    contact_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> CRMContactDetailResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        row = crm._crm_contact_or_404(connection, cliente_id, contact_id)
        audit_rows = connection.execute(
            "SELECT event_type, actor, payload_json, created_at FROM crm_contact_audit WHERE cliente_id = ? AND contact_id = ? ORDER BY id DESC LIMIT 100",
            (cliente_id, contact_id),
        ).fetchall()
        audit = [
            {"event_type": item["event_type"], "actor": item["actor"], "payload": json.loads(item["payload_json"] or "{}"), "created_at": item["created_at"]}
            for item in audit_rows
        ]
        return CRMContactDetailResponse(
            contact=crm._crm_contact_public(row, connection),
            activity=crm._crm_contact_activity(connection, cliente_id, contact_id),
            audit=audit,
        )


# --- Pagos de clientes finales / Stripe Connect ----------------------------

PAYMENT_POLICY_MODES = {"none", "full", "deposit_fixed", "deposit_percent"}
PAYMENT_STATUSES = {"pending", "paid", "failed", "refunded", "partially_refunded"}






























@app.get("/auth/app/channels", response_model=ChannelSettingsResponse)
async def app_channels_get(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ChannelSettingsResponse:
    return emailing._channel_settings_public(security._resolve_cliente_for_self_serve_user(user))


@app.post("/auth/app/channels/email/settings", response_model=ChannelSettingsResponse)
async def app_channels_email_settings(
    data: ChannelEmailSettingsPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ChannelSettingsResponse:
    security._require_portal_min_role(user, "owner")
    if data.provider not in {"vantelia_smtp", "gmail_oauth"}:
        raise HTTPException(status_code=400, detail="Proveedor de email no valido.")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    if data.provider == "gmail_oauth" and not emailing._client_gmail_connection(cliente_id):
        raise HTTPException(status_code=400, detail="Conecta primero una cuenta de Google.")
    security._ensure_channel_settings(cliente_id)
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE client_channel_settings SET email_provider=?, email_fallback_enabled=?, updated_at=? WHERE cliente_id=?",
            (data.provider, int(data.fallback_enabled), timeutils._utc_now_iso(), cliente_id),
        )
        connection.commit()
    return emailing._channel_settings_public(cliente_id)


@app.post("/auth/app/channels/email/google/connect", response_model=ChannelConnectResponse)
async def app_channels_google_connect(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ChannelConnectResponse:
    security._require_portal_min_role(user, "owner")
    if not emailing._gmail_channel_configured():
        raise HTTPException(status_code=503, detail="La conexion con Gmail no esta configurada.")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    security._ensure_channel_settings(cliente_id)
    state, verifier = emailing._gmail_channel_state_create(cliente_id, user["id"])
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {
        "client_id": settings.GOOGLE_GMAIL_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_GMAIL_REDIRECT_URL,
        "response_type": "code",
        "scope": f"openid email {settings.GOOGLE_GMAIL_SEND_SCOPE}",
        "state": state,
        "access_type": "offline",
        "prompt": "consent select_account",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return ChannelConnectResponse(url=f"{settings.GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


@app.get("/auth/app/channels/email/google/callback", include_in_schema=False)
async def app_channels_google_callback(
    code: str = "", state: str = "", error: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> RedirectResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    if error:
        return RedirectResponse(url=f"/app?channels_error={quote(error)}", status_code=303)
    verifier = emailing._gmail_channel_state_consume(state, cliente_id, user["id"])
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_response = await client.post(
                settings.GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "code": code, "client_id": settings.GOOGLE_GMAIL_CLIENT_ID,
                    "client_secret": settings.GOOGLE_GMAIL_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_GMAIL_REDIRECT_URL,
                    "grant_type": "authorization_code", "code_verifier": verifier,
                },
            )
            token_response.raise_for_status()
            token = token_response.json()
            access_token = str(token.get("access_token", ""))
            info_response = await client.get(
                settings.GOOGLE_OAUTH_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
            info_response.raise_for_status()
            info = info_response.json()
    except Exception as exc:  # noqa: BLE001
        security._channel_audit(cliente_id, "email", "connect_failed", "gmail_oauth", False, str(exc))
        raise HTTPException(status_code=502, detail="No se pudo conectar la cuenta de Google.") from exc
    granted = set(str(token.get("scope", "")).split())
    if settings.GOOGLE_GMAIL_SEND_SCOPE not in granted:
        raise HTTPException(status_code=400, detail="Google no concedio permiso para enviar correo.")
    now, expires = timeutils._utc_now_iso(), timeutils._utc_now() + timedelta(seconds=int(token.get("expires_in", 3600)))
    existing = emailing._client_gmail_connection(cliente_id)
    refresh_token = str(token.get("refresh_token", "")) or (
        security._decrypt_channel_secret(existing["refresh_token_encrypted"]) if existing else ""
    )
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_oauth_connections
                (cliente_id, provider, account_email, account_name, scopes_json,
                 access_token_encrypted, refresh_token_encrypted, expires_at, status, created_at, updated_at)
            VALUES (?, 'gmail_oauth', ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(cliente_id, provider) DO UPDATE SET
                account_email=excluded.account_email, account_name=excluded.account_name,
                scopes_json=excluded.scopes_json, access_token_encrypted=excluded.access_token_encrypted,
                refresh_token_encrypted=excluded.refresh_token_encrypted, expires_at=excluded.expires_at,
                status='active', last_error='', updated_at=excluded.updated_at
            """,
            (
                cliente_id, textnorm._normalize_email(info.get("email", "")), str(info.get("name", "")),
                json.dumps(sorted(granted)), security._encrypt_channel_secret(access_token),
                security._encrypt_channel_secret(refresh_token), expires.isoformat(), now, now,
            ),
        )
        connection.execute(
            "UPDATE client_channel_settings SET email_provider='gmail_oauth', updated_at=? WHERE cliente_id=?",
            (now, cliente_id),
        )
        connection.commit()
    security._channel_audit(cliente_id, "email", "connected", "gmail_oauth", True)
    return RedirectResponse(url="/app?channels=connected", status_code=303)


@app.post("/auth/app/channels/email/google/disconnect", response_model=ChannelSettingsResponse)
async def app_channels_google_disconnect(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ChannelSettingsResponse:
    security._require_portal_min_role(user, "owner")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    gmail = emailing._client_gmail_connection(cliente_id)
    if gmail and emailing._gmail_channel_configured():
        try:
            token = (
                security._decrypt_channel_secret(gmail["refresh_token_encrypted"])
                or security._decrypt_channel_secret(gmail["access_token_encrypted"])
            )
            if token:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        settings.GOOGLE_OAUTH_REVOKE_URL,
                        data={"token": token},
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
        except Exception:  # noqa: BLE001
            security._channel_audit(
                cliente_id, "email", "revoke_failed", "gmail_oauth", False,
                "Google no confirmo la revocacion; la conexion local se elimino.",
            )
    with db._get_db_connection() as connection:
        connection.execute(
            "DELETE FROM client_oauth_connections WHERE cliente_id=? AND provider='gmail_oauth'", (cliente_id,)
        )
        connection.execute(
            "UPDATE client_channel_settings SET email_provider='vantelia_smtp', updated_at=? WHERE cliente_id=?",
            (timeutils._utc_now_iso(), cliente_id),
        )
        connection.commit()
    security._channel_audit(cliente_id, "email", "disconnected", "gmail_oauth", True)
    return emailing._channel_settings_public(cliente_id)


@app.post("/auth/app/channels/email/test", response_model=AuthSimpleResponse)
async def app_channels_email_test(
    data: ChannelTestPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    security._check_rate_limit(f"channel-email-test:{cliente_id}", 3)
    target = textnorm._normalize_email(data.target)
    if not target:
        raise HTTPException(status_code=400, detail="Indica un email valido.")
    provider = emailing._send_client_email(
        cliente_id, target, "Prueba de canal de Vantelia",
        "El canal de email de tu negocio esta configurado correctamente.",
    )
    return AuthSimpleResponse(ok=True, message=f"Correo de prueba enviado mediante {provider}.")


@app.post("/auth/app/channels/sms/settings", response_model=ChannelSettingsResponse)
async def app_channels_sms_settings(
    data: ChannelSmsSettingsPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ChannelSettingsResponse:
    security._require_portal_min_role(user, "owner")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    clients._require_plan_feature(
        cliente_id, "sms_enabled", "El envio por SMS esta disponible desde el plan Business."
    )
    if data.mode not in {"vantelia_default", "twilio_alphanumeric_sender", "twilio_dedicated_number"}:
        raise HTTPException(status_code=400, detail="Modo SMS no valido.")
    settings = security._ensure_channel_settings(cliente_id)
    sender, sender_status = "", "not_configured"
    if data.mode == "twilio_alphanumeric_sender":
        sender = data.sender.strip().upper()
        if not re.fullmatch(r"(?=.*[A-Z])[A-Z0-9 ]{3,11}", sender):
            raise HTTPException(status_code=400, detail="El Sender ID debe tener 3-11 caracteres y alguna letra.")
        sender_status = "pending_registration"
    elif data.mode == "twilio_dedicated_number":
        if settings["sms_mode"] != data.mode or settings["sms_sender_status"] != "active":
            raise HTTPException(status_code=400, detail="El numero dedicado debe provisionarlo soporte antes de activarlo.")
        sender, sender_status = settings["sms_sender"], "active"
    with db._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE client_channel_settings
            SET sms_mode=?, sms_sender=?, sms_sender_status=?, updated_at=?
            WHERE cliente_id=?
            """,
            (data.mode, sender, sender_status, timeutils._utc_now_iso(), cliente_id),
        )
        connection.commit()
    security._channel_audit(cliente_id, "sms", "settings_updated", data.mode, True, sender_status)
    return emailing._channel_settings_public(cliente_id)


@app.post("/auth/app/channels/sms/test", response_model=AuthSimpleResponse)
async def app_channels_sms_test(
    data: ChannelTestPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    security._check_rate_limit(f"channel-sms-test:{cliente_id}", 3)
    target = booking._booking_customer_phone_for_channel({"telefono": data.target}, "sms")
    if not target:
        raise HTTPException(status_code=400, detail="Indica un telefono valido.")
    if not await messaging._send_client_sms(cliente_id, target, "Prueba de canal SMS de Vantelia."):
        raise HTTPException(status_code=502, detail="No se pudo enviar el SMS de prueba.")
    return AuthSimpleResponse(ok=True, message="SMS de prueba enviado.")


@app.get("/auth/app/payments/connect/status", response_model=ConnectAccountStatus)
async def app_connect_status(
    refresh: bool = False,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ConnectAccountStatus:
    return booking._connect_account_status(security._resolve_cliente_for_self_serve_user(user), refresh=refresh)


@app.post("/auth/app/payments/ai-send", response_model=ConnectAccountStatus)
async def app_payments_ai_send_toggle(
    data: AiSendTogglePayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ConnectAccountStatus:
    security._require_portal_min_role(user, "owner")
    """Opt-in del negocio: permite que la IA envie enlaces de pago en su nombre."""
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    booking._set_ai_send_enabled(cliente_id, data.enabled)
    return booking._connect_account_status(cliente_id)


@app.get("/auth/app/rebooking-ai")
async def app_rebooking_ai_status(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    target = portal._portal_client_id_or_403(user, cliente_id)
    return {"enabled": booking._ai_rebooking_enabled_for_client(target)}


@app.post("/auth/app/rebooking-ai")
async def app_rebooking_ai_toggle(
    data: AiSendTogglePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    """Opt-in: la IA reengancha clientes inactivos por WhatsApp ('¿te reservo otra cita?')."""
    security._require_portal_min_role(user, "owner")
    target = portal._portal_client_id_or_403(user, cliente_id)
    security._ensure_channel_settings(target)
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE client_channel_settings SET ai_rebooking_enabled=?, updated_at=? WHERE cliente_id=?",
            (1 if data.enabled else 0, timeutils._utc_now_iso(), target),
        )
        connection.commit()
    return {"enabled": bool(data.enabled)}


@app.get("/auth/app/cancellation-policy", response_model=CancellationPolicyResponse)
async def app_cancellation_policy_get(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> CancellationPolicyResponse:
    target = portal._portal_client_id_or_403(user, cliente_id)
    return CancellationPolicyResponse(**booking.get_cancellation_policy(target))


@app.put("/auth/app/cancellation-policy", response_model=CancellationPolicyResponse)
async def app_cancellation_policy_put(
    data: CancellationPolicyPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> CancellationPolicyResponse:
    """Politica de cancelacion/no-show del negocio (config manager+)."""
    security._require_portal_min_role(user, "manager")
    target = portal._portal_client_id_or_403(user, cliente_id)
    saved = booking.save_cancellation_policy(
        target,
        enabled=data.enabled,
        free_cancel_hours=data.free_cancel_hours,
        late_cancel_fee_pct=data.late_cancel_fee_pct,
        no_show_fee_pct=data.no_show_fee_pct,
        auto_apply=data.auto_apply,
        policy_text=data.policy_text,
    )
    return CancellationPolicyResponse(**saved)


@app.get("/auth/app/reminders", response_model=ReminderConfigResponse)
async def app_reminders_get(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ReminderConfigResponse:
    target = portal._portal_client_id_or_403(user, cliente_id)
    rcfg = booking._reminders_config(target)
    vcfg = (appstate.CONFIG_CLIENTES.get(target) or {}).get("voice") or {}
    available = bool(vcfg.get("twilio_phone_number") and voice._client_voice_plan_enabled(target))
    return ReminderConfigResponse(voice_call_available=available, **rcfg)


@app.put("/auth/app/reminders", response_model=ReminderConfigResponse)
async def app_reminders_put(
    data: ReminderConfigPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ReminderConfigResponse:
    """Config de llamadas de confirmacion (fallback automatico, quiet hours, cap)."""
    security._require_portal_min_role(user, "manager")
    target = portal._portal_client_id_or_403(user, cliente_id)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(target, {})
        rem = dict(cfg.get("reminders", {}) or {})
        if data.call_fallback is not None:
            rem["call_fallback"] = bool(data.call_fallback)
        if data.quiet_start is not None:
            rem["quiet_start"] = textnorm._sanitize_text(data.quiet_start)[:5] or "21:00"
        if data.quiet_end is not None:
            rem["quiet_end"] = textnorm._sanitize_text(data.quiet_end)[:5] or "09:00"
        if data.daily_call_cap is not None:
            rem["daily_call_cap"] = max(0, min(500, int(data.daily_call_cap)))
        cfg["reminders"] = rem
        next_configs[target] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    rcfg = booking._reminders_config(target)
    vcfg = (appstate.CONFIG_CLIENTES.get(target) or {}).get("voice") or {}
    available = bool(vcfg.get("twilio_phone_number") and voice._client_voice_plan_enabled(target))
    return ReminderConfigResponse(voice_call_available=available, **rcfg)


@app.get("/auth/app/follow-up", response_model=FollowUpResponse)
async def app_follow_up_get(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> FollowUpResponse:
    """Estado del Seguimiento: config + capacidades por plan + flujo efectivo."""
    target = portal._portal_client_id_or_403(user, cliente_id)
    return FollowUpResponse(**booking._follow_up_overview_dict(target))


@app.put("/auth/app/follow-up", response_model=FollowUpResponse)
async def app_follow_up_put(
    data: FollowUpPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> FollowUpResponse:
    """Guarda el flujo de Seguimiento (escalera de confirmacion). manager+."""
    security._require_portal_min_role(user, "manager")
    target = portal._portal_client_id_or_403(user, cliente_id)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(target, {})
        rem = dict(cfg.get("reminders", {}) or {})
        if data.call_enabled is not None:
            rem["call_enabled"] = bool(data.call_enabled)
            rem["call_fallback"] = bool(data.call_enabled)  # alias historico sincronizado
        if data.call_hours_before is not None:
            rem["call_hours_before"] = max(1, min(24, int(data.call_hours_before)))
        if data.quiet_start is not None:
            rem["quiet_start"] = textnorm._sanitize_text(data.quiet_start)[:5] or "21:00"
        if data.quiet_end is not None:
            rem["quiet_end"] = textnorm._sanitize_text(data.quiet_end)[:5] or "09:00"
        if data.daily_call_cap is not None:
            rem["daily_call_cap"] = max(0, min(500, int(data.daily_call_cap)))
        if data.email_confirm_button is not None:
            rem["email_confirm_button"] = bool(data.email_confirm_button)
        if data.suppress_2h_if_confirmed is not None:
            rem["suppress_2h_if_confirmed"] = bool(data.suppress_2h_if_confirmed)
        cfg["reminders"] = rem
        if data.message_template_channels is not None:
            booking_cfg = dict(cfg.get("booking", {}) or {})
            booking_cfg["message_template_channels"] = textnorm._normalize_message_template_channels(
                data.message_template_channels
            )
            cfg["booking"] = booking_cfg
        next_configs[target] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    return FollowUpResponse(**booking._follow_up_overview_dict(target))


@app.post("/auth/bookings/{booking_id}/confirm-call", response_model=BookingActionResponse)
async def auth_booking_confirm_call(
    booking_id: str,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingActionResponse:
    """Lanza una llamada de IA al cliente para confirmar su cita (manual)."""
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    security._require_portal_permission(user, "agenda.attendance")
    if booking_row["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="No se puede llamar para una cita cancelada.")
    result = await timeutils._to_thread(
        voice._voice_place_outbound_call, booking_row["cliente_id"], booking_row,
        base_url=textnorm._public_base_url(request),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error") or "No se pudo iniciar la llamada.")
    return BookingActionResponse(
        ok=True, booking_id=booking_id, estado=booking_row["status"],
        mensaje="Llamada de confirmacion en curso.",
    )


@app.post("/auth/bookings/{booking_id}/send-confirmation", response_model=BookingActionResponse)
async def auth_booking_send_confirmation(
    booking_id: str,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingActionResponse:
    """Reenvia la confirmacion de la cita por los canales configurados (email/WhatsApp/SMS)."""
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    security._require_portal_permission(user, "agenda.attendance")
    await booking._send_booking_reminder_by_kind(booking_row, "confirmed", request, respect_enabled=False)
    booking._record_booking_audit(booking_id, booking_row["cliente_id"], "confirmation_resent",
                                  {"by": user["id"]})
    return BookingActionResponse(
        ok=True, booking_id=booking_id, estado=booking_row["status"],
        mensaje="Confirmacion enviada.",
    )


@app.get("/auth/bookings/{booking_id}/cancellation-preview", response_model=CancellationPreviewResponse)
async def auth_booking_cancellation_preview(
    booking_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> CancellationPreviewResponse:
    """Calcula penalizacion/reembolso (cancelar ahora vs no-show) para mostrarlo
    en el panel antes de confirmar. No toca Stripe."""
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    return CancellationPreviewResponse(
        booking_id=booking_id,
        cancel=CancellationOutcome(**booking.compute_cancellation_outcome(booking_row, kind="cancel")),
        no_show=CancellationOutcome(**booking.compute_cancellation_outcome(booking_row, kind="no_show")),
    )


@app.post("/auth/app/payments/connect/start", response_model=ConnectStartResponse)
async def app_connect_start(
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ConnectStartResponse:
    security._require_portal_min_role(user, "owner")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    if settings.STRIPE_CONNECT_CLIENT_ID:
        state = security._oauth_create_state("stripe_connect", f"{cliente_id}:{user['id']}")
        redirect_uri = settings.STRIPE_CONNECT_RETURN_URL or f"{textnorm._public_base_url(request)}/auth/app/payments/connect/callback"
        url = "https://connect.stripe.com/oauth/authorize?" + urlencode({
            "response_type": "code", "client_id": settings.STRIPE_CONNECT_CLIENT_ID,
            "scope": "read_write", "state": state, "redirect_uri": redirect_uri,
        })
        return ConnectStartResponse(url=url)

    stripe_gateway._stripe_init()
    base_url = textnorm._public_base_url(request)
    try:
        with db._get_db_connection() as connection:
            row = connection.execute(
                "SELECT stripe_account_id FROM client_payment_accounts WHERE cliente_id=?",
                (cliente_id,),
            ).fetchone()
        account_id = str(row["stripe_account_id"] or "") if row else ""
        if account_id:
            account = stripe_gateway.stripe.Account.retrieve(account_id)
        else:
            account = stripe_gateway.stripe.Account.create(
                type="standard",
                metadata={"vantelia_cliente_id": cliente_id},
            )
        account_id = stripe_gateway._save_connect_account(cliente_id, account)
        account_link = stripe_gateway.stripe.AccountLink.create(
            account=account_id,
            refresh_url=settings.STRIPE_CONNECT_REFRESH_URL or f"{base_url}/app?payments=refresh",
            return_url=f"{base_url}/app?payments=connected",
            type="account_onboarding",
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Error iniciando Stripe Connect Onboarding para %s: %s", cliente_id, exc)
        if "signed up for Connect" in str(exc):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Stripe Connect aun no esta activado para Vantelia. "
                    "El administrador debe completar el perfil de plataforma en "
                    "https://dashboard.stripe.com/connect antes de conectar empresas."
                ),
            ) from exc
        raise HTTPException(status_code=502, detail="No se pudo iniciar Stripe Connect.") from exc
    return ConnectStartResponse(url=str(textnorm._object_get(account_link, "url", "") or ""))


@app.get("/auth/app/payments/connect/callback")
async def app_connect_callback(
    request: Request,
    code: str = "",
    state: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> RedirectResponse:
    state_data = security._oauth_consume_state(state)
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    if not state_data or state_data["intent"] != "stripe_connect" or state_data["claim"] != f"{cliente_id}:{user['id']}":
        raise HTTPException(status_code=400, detail="Estado OAuth invalido o caducado.")
    if not code:
        raise HTTPException(status_code=400, detail="Stripe no devolvio un codigo de autorizacion.")
    stripe_gateway._stripe_init()
    try:
        token = stripe_gateway.stripe.OAuth.token(grant_type="authorization_code", code=code)
        account_id = textnorm._object_get(token, "stripe_user_id", "")
        account = stripe_gateway.stripe.Account.retrieve(account_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="No se pudo conectar la cuenta Stripe.") from exc
    stripe_gateway._save_connect_account(cliente_id, account)
    return RedirectResponse(url="/app?payments=connected", status_code=303)


@app.put("/auth/app/services/{service_id}/payment-policy", response_model=ServicePublic)
async def app_service_payment_policy(
    service_id: str,
    data: ServicePaymentPolicyPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ServicePublic:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    agenda._ensure_services_seeded(cliente_id)
    service = agenda._get_service_row(cliente_id, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    if data.mode not in PAYMENT_POLICY_MODES:
        raise HTTPException(status_code=400, detail="Politica de pago invalida.")
    if data.mode == "deposit_percent" and not 1 <= data.deposit_value <= 100:
        raise HTTPException(status_code=400, detail="El porcentaje debe estar entre 1 y 100.")
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO service_payment_policies
                (cliente_id, service_id, mode, deposit_value, confirm_booking_on_paid, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id, service_id) DO UPDATE SET mode=excluded.mode,
                deposit_value=excluded.deposit_value, confirm_booking_on_paid=excluded.confirm_booking_on_paid,
                updated_at=excluded.updated_at
            """,
            (cliente_id, service_id, data.mode, data.deposit_value, int(data.confirm_booking_on_paid), now, now),
        )
        connection.commit()
    return ServicePublic(**agenda._service_row_to_public(service))


@app.get("/auth/app/payments", response_model=CustomerPaymentsResponse)
async def app_customer_payments(
    booking_id: str = "", contact_id: str = "", limit: int = 100,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> CustomerPaymentsResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    clauses, params = ["cliente_id=?"], [cliente_id]
    if booking_id:
        clauses.append("booking_id=?"); params.append(booking_id)
    if contact_id:
        clauses.append("contact_id=?"); params.append(contact_id)
    with db._get_db_connection() as connection:
        total = connection.execute(f"SELECT COUNT(*) FROM customer_payments WHERE {' AND '.join(clauses)}", tuple(params)).fetchone()[0]
        rows = connection.execute(
            f"SELECT * FROM customer_payments WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ?",
            (*params, max(1, min(limit, 500))),
        ).fetchall()
    return CustomerPaymentsResponse(items=[booking._payment_public(row) for row in rows], total=int(total or 0))




@app.post("/auth/app/bookings/{booking_id}/payment-link", response_model=PaymentLinkResponse)
async def app_booking_payment_link(
    booking_id: str,
    data: PaymentLinkPayload,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PaymentLinkResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    booking_row = booking._load_booking_or_404(booking_id)
    if booking_row["cliente_id"] != cliente_id:
        raise HTTPException(status_code=404, detail="Cita no encontrada.")
    row = booking._create_customer_payment_link(
        cliente_id, booking_row, base_url=textnorm._public_base_url(request), override_cents=data.amount_cents
    )
    return PaymentLinkResponse(payment=booking._payment_public(row), checkout_url=row["checkout_url"])






@app.post("/auth/app/payments/{payment_id}/refund", response_model=CustomerPaymentPublic)
async def app_payment_refund(
    payment_id: str,
    data: PaymentRefundPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> CustomerPaymentPublic:
    security._require_portal_min_role(user, "owner")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        payment = connection.execute(
            "SELECT * FROM customer_payments WHERE id=? AND cliente_id=?", (payment_id, cliente_id)
        ).fetchone()
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado.")
    if payment["status"] not in {"paid", "partially_refunded"} or not payment["stripe_payment_intent_id"]:
        raise HTTPException(status_code=409, detail="Este pago no se puede reembolsar.")
    kwargs: Dict[str, Any] = {
        "payment_intent": payment["stripe_payment_intent_id"],
        "stripe_account": payment["stripe_account_id"],
    }
    if data.amount_cents is not None:
        kwargs["amount"] = int(data.amount_cents)
    stripe_gateway._stripe_init()
    try:
        stripe_gateway.stripe.Refund.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="No se pudo solicitar el reembolso.") from exc
    with db._get_db_connection() as connection:
        row = connection.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
    return booking._payment_public(row)


# --- Sem 4: Leads ----------------------------------------------------------



@app.get("/auth/app/leads", response_model=AppLeadsListResponse)
async def app_leads_list(
    page: int = 1,
    page_size: int = 50,
    q: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppLeadsListResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    offset = (page - 1) * page_size
    q_clean = (q or "").strip()
    with db._get_db_connection() as connection:
        if q_clean:
            like = f"%{q_clean.lower()}%"
            total = connection.execute(
                """
                SELECT COUNT(*) FROM bot_leads
                WHERE cliente_id = ?
                  AND (LOWER(name) LIKE ? OR LOWER(email) LIKE ? OR LOWER(phone) LIKE ? OR LOWER(message) LIKE ?)
                """,
                (cliente_id, like, like, like, like),
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT * FROM bot_leads
                WHERE cliente_id = ?
                  AND (LOWER(name) LIKE ? OR LOWER(email) LIKE ? OR LOWER(phone) LIKE ? OR LOWER(message) LIKE ?)
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (cliente_id, like, like, like, like, page_size, offset),
            ).fetchall()
        else:
            total = connection.execute(
                "SELECT COUNT(*) FROM bot_leads WHERE cliente_id = ?", (cliente_id,)
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM bot_leads WHERE cliente_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (cliente_id, page_size, offset),
            ).fetchall()
    return AppLeadsListResponse(
        items=[crm._lead_row_to_public(r) for r in rows],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


@app.post("/auth/app/leads", response_model=AppLeadPublic)
async def app_lead_create(
    data: AppLeadPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppLeadPublic:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    name = textnorm._sanitize_text(data.name)[:200]
    email = textnorm._sanitize_text(data.email)[:200]
    phone = textnorm._sanitize_text(data.phone)[:80]
    message = textnorm._sanitize_text(data.message, allow_multiline=True)[:4000]
    if not (name or email or phone or message):
        raise HTTPException(status_code=400, detail="Indica al menos nombre, email, telefono o mensaje.")
    lead_id = "lead_" + secrets.token_hex(10)
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO bot_leads
                (id, cliente_id, session_id, name, email, phone, message, source, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)
            """,
            (
                lead_id,
                cliente_id,
                textnorm._sanitize_text(data.session_id)[:200],
                name,
                email,
                phone,
                message,
                textnorm._sanitize_text(data.source)[:40] or "manual",
                now_iso,
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM bot_leads WHERE id = ?", (lead_id,)).fetchone()
    contact_id = crm._crm_upsert_contact(
        cliente_id,
        name=name,
        email=email,
        phone=phone,
        source=textnorm._sanitize_text(data.source)[:40] or "manual",
        status="interesado",
        entity_type="lead",
        entity_id=lead_id,
        actor=f"user:{user['id']}",
    )
    if contact_id and data.session_id:
        with db._get_db_connection() as connection:
            crm._crm_link(connection, cliente_id, contact_id, "chat", textnorm._sanitize_text(data.session_id)[:200], "chat")
            connection.commit()
    return crm._lead_row_to_public(row)


@app.delete("/auth/app/leads/{lead_id}")
async def app_lead_delete(
    lead_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        cur = connection.execute(
            "DELETE FROM bot_leads WHERE id = ? AND cliente_id = ?",
            (lead_id, cliente_id),
        )
        connection.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Lead no encontrado.")
    return {"ok": True}


@app.get("/auth/app/leads/export.csv")
async def app_leads_export(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Response:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM bot_leads WHERE cliente_id = ? ORDER BY created_at DESC",
            (cliente_id,),
        ).fetchall()
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["created_at", "name", "email", "phone", "message", "source", "session_id"])
    for r in rows:
        writer.writerow([
            r["created_at"], r["name"] or "", r["email"] or "", r["phone"] or "",
            (r["message"] or "").replace("\n", " ").replace("\r", " "),
            r["source"] or "", r["session_id"] or "",
        ])
    filename = f"leads_{cliente_id}_{timeutils._utc_now().strftime('%Y%m%d')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Sem 4: Q&A -------------------------------------------------------------



@app.get("/auth/app/qa", response_model=AppQAListResponse)
async def app_qa_list(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppQAListResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM kb_qa WHERE cliente_id = ? ORDER BY created_at DESC",
            (cliente_id,),
        ).fetchall()
    items = [rag._qa_row_to_public(r) for r in rows]
    return AppQAListResponse(items=items, total=len(items))


@app.post("/auth/app/qa", response_model=AppQAItem)
async def app_qa_create(
    data: AppQAPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppQAItem:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    qa_id = "qa_" + secrets.token_hex(10)
    now_iso = timeutils._utc_now_iso()
    tags = [textnorm._sanitize_text(t)[:40] for t in (data.tags or []) if textnorm._sanitize_text(t)][:10]
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO kb_qa (id, cliente_id, question, answer, tags_json,
                               created_at, updated_at, created_by_user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                qa_id,
                cliente_id,
                textnorm._sanitize_text(data.question, allow_multiline=True)[:400],
                textnorm._sanitize_text(data.answer, allow_multiline=True)[:4000],
                json.dumps(tags, ensure_ascii=False),
                now_iso,
                now_iso,
                user["id"],
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_qa WHERE id = ?", (qa_id,)).fetchone()
    rag._maybe_regenerate_info_with_qa(cliente_id)
    return rag._qa_row_to_public(row)


@app.patch("/auth/app/qa/{qa_id}", response_model=AppQAItem)
async def app_qa_update(
    qa_id: str,
    data: AppQAUpdatePayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppQAItem:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM kb_qa WHERE id = ? AND cliente_id = ?",
            (qa_id, cliente_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Q&A no encontrada.")
        next_q = textnorm._sanitize_text(data.question, allow_multiline=True)[:400] if data.question is not None else row["question"]
        next_a = textnorm._sanitize_text(data.answer, allow_multiline=True)[:4000] if data.answer is not None else row["answer"]
        if data.tags is not None:
            tags = [textnorm._sanitize_text(t)[:40] for t in data.tags if textnorm._sanitize_text(t)][:10]
            tags_json = json.dumps(tags, ensure_ascii=False)
        else:
            tags_json = row["tags_json"]
        connection.execute(
            "UPDATE kb_qa SET question = ?, answer = ?, tags_json = ?, updated_at = ? WHERE id = ?",
            (next_q, next_a, tags_json, timeutils._utc_now_iso(), qa_id),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_qa WHERE id = ?", (qa_id,)).fetchone()
    rag._maybe_regenerate_info_with_qa(cliente_id)
    return rag._qa_row_to_public(row)


@app.delete("/auth/app/qa/{qa_id}")
async def app_qa_delete(
    qa_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        cur = connection.execute(
            "DELETE FROM kb_qa WHERE id = ? AND cliente_id = ?",
            (qa_id, cliente_id),
        )
        connection.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Q&A no encontrada.")
    rag._maybe_regenerate_info_with_qa(cliente_id)
    return {"ok": True}


# --- Sem 4: Knowledge (text snippets + URLs) -----------------------------

_KB_BLOCK_MARKER = "===== AÑADIDO DESDE PANEL ====="


























@app.get("/auth/app/knowledge", response_model=AppKnowledgeListResponse)
async def app_knowledge_list(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKnowledgeListResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM kb_documents WHERE cliente_id = ? ORDER BY uploaded_at DESC",
            (cliente_id,),
        ).fetchall()
    info = rag._read_info(cliente_id)
    return AppKnowledgeListResponse(
        items=[rag._kb_row_to_public(r) for r in rows],
        info_chars=len(info),
        info_excerpt=info[:1200],
        info_full=info,
    )


@app.post("/auth/app/knowledge/text", response_model=AppKnowledgeItem)
async def app_knowledge_add_text(
    data: AppKnowledgeTextPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKnowledgeItem:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    title = textnorm._sanitize_text(data.title)[:200] or "Nota manual"
    content = textnorm._sanitize_text(data.content, allow_multiline=True)[:20000]
    now_iso = timeutils._utc_now_iso()
    kb_id = "kb_" + secrets.token_hex(10)
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO kb_documents
                (id, cliente_id, filename, mime_type, size_bytes, sha256,
                 source, source_url, storage_path, indexed_at, uploaded_at, uploaded_by_user_id)
            VALUES (?, ?, ?, 'text/plain', ?, '', 'text', '', '', ?, ?, ?)
            """,
            (kb_id, cliente_id, title, len(content.encode("utf-8")), now_iso, now_iso, user["id"]),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_documents WHERE id = ?", (kb_id,)).fetchone()
    info = rag._read_info(cliente_id)
    block = f"\n\n{_KB_BLOCK_MARKER}\n[{title}]\n{content}\n"
    if rag._KB_QA_BLOCK_MARKER in info:
        before, after = info.split(rag._KB_QA_BLOCK_MARKER, 1)
        info = before.rstrip() + block + "\n" + rag._KB_QA_BLOCK_MARKER + after
    else:
        info = info.rstrip() + block
    rag._write_info(cliente_id, info)
    return rag._kb_row_to_public(row)


@app.post("/auth/app/knowledge/url", response_model=AppKnowledgeItem)
async def app_knowledge_add_url(
    data: AppKnowledgeUrlPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKnowledgeItem:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    url = textnorm._sanitize_text(data.url)
    if not re.match(r"^https?://", url):
        raise HTTPException(status_code=400, detail="URL invalida (https:// requerido).")
    canonical_url = rag._canonical_knowledge_url(url)
    with db._get_db_connection() as connection:
        existing_url_rows = connection.execute(
            """
            SELECT source_url
            FROM kb_documents
            WHERE cliente_id = ? AND source = 'url'
            """,
            (cliente_id,),
        ).fetchall()
    if any(rag._canonical_knowledge_url(row["source_url"] or "") == canonical_url for row in existing_url_rows):
        raise HTTPException(
            status_code=409,
            detail="Esta fuente ya esta añadida al conocimiento. Quita la fuente existente antes de volver a indexarla.",
        )
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY no configurada.")
    try:
        max_pages = 1 if data.just_this_page else settings.ONBOARDING_MAX_PAGES_DEFAULT
        result = onboarding_utils.run_onboarding(
            website_url=canonical_url,
            api_key=settings.OPENAI_API_KEY,
            nombre_bot=appstate.CONFIG_CLIENTES.get(cliente_id, {}).get("nombre", cliente_id),
            tono="Profesional y cercano",
            idioma="Espanol",
            max_paginas=max_pages,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("KB URL ingest fallo %s: %s", cliente_id, exc)
        raise HTTPException(status_code=502, detail=f"No se pudo analizar la URL: {exc}") from exc

    now_iso = timeutils._utc_now_iso()
    kb_id = "kb_" + secrets.token_hex(10)
    info_chars = len(result.info_txt.encode("utf-8"))
    stored_url = canonical_url
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO kb_documents
                (id, cliente_id, filename, mime_type, size_bytes, sha256,
                 source, source_url, storage_path, indexed_at, uploaded_at, uploaded_by_user_id)
            VALUES (?, ?, ?, 'text/html', ?, '', 'url', ?, '', ?, ?, ?)
            """,
            (
                kb_id, cliente_id,
                result.detected_business_name or stored_url,
                info_chars,
                stored_url,
                now_iso, now_iso, user["id"],
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_documents WHERE id = ?", (kb_id,)).fetchone()

    if data.replace:
        new_info = result.info_txt
    else:
        existing = rag._read_info(cliente_id)
        block = f"\n\n{_KB_BLOCK_MARKER}\n[Web: {stored_url}]\n{result.info_txt}\n"
        if rag._KB_QA_BLOCK_MARKER in existing:
            before, after = existing.split(rag._KB_QA_BLOCK_MARKER, 1)
            new_info = before.rstrip() + block + "\n" + rag._KB_QA_BLOCK_MARKER + after
        else:
            new_info = existing.rstrip() + block
    rag._write_info(cliente_id, new_info)
    qa_created = 0
    try:
        explicit_pairs = list(getattr(result, "faq_pairs", []) or [])
        faq_source = str(getattr(result, "faq_source", "") or "").lower()
        qa_created = rag._autocreate_qa_from_info(
            cliente_id,
            result.info_txt,
            user["id"],
            explicit_pairs=explicit_pairs,
            max_pairs=rag.AUTO_QA_MAX_PAIRS,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Auto-Q&A extraction failed for %s: %s", cliente_id, exc)
    public = rag._kb_row_to_public(row)
    public.qa_created = qa_created
    return public


@app.delete("/auth/app/knowledge/{kb_id}")
async def app_knowledge_delete(
    kb_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        cur = connection.execute(
            "DELETE FROM kb_documents WHERE id = ? AND cliente_id = ?",
            (kb_id, cliente_id),
        )
        connection.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Recurso no encontrado.")
    # NOTE: we intentionally do NOT auto-truncate info.txt — text was merged in
    # at ingest time and cannot be cleanly de-merged. User can use /reindex.
    return {"ok": True}


@app.post("/auth/app/knowledge/reindex", response_model=AppKnowledgeReindexResponse)
async def app_knowledge_reindex(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppKnowledgeReindexResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    try:
        with appstate.state_lock:
            appstate.indices.pop(cliente_id, None)
    except NameError:
        pass
    info = rag._read_info(cliente_id)
    return AppKnowledgeReindexResponse(ok=True, cliente_id=cliente_id, info_chars=len(info))


# --- Sem 4: Tune AI -------------------------------------------------------

AVAILABLE_CHAT_MODELS = settings.AVAILABLE_CHAT_MODELS_BOOT


@app.get("/auth/app/tune", response_model=AppTuneResponse)
async def app_tune_get(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppTuneResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    return AppTuneResponse(
        cliente_id=cliente_id,
        prompt_extra=cfg.get("prompt_extra", ""),
        chat_model=cfg.get("chat_model", settings.DEFAULT_CHAT_MODEL),
        temperature=float(cfg.get("temperature", 0.2)),
        available_models=AVAILABLE_CHAT_MODELS,
    )


@app.post("/auth/app/tune", response_model=AppTuneResponse)
async def app_tune_post(
    data: AppTunePayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppTuneResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        if data.prompt_extra is not None:
            cfg["prompt_extra"] = textnorm._sanitize_text(data.prompt_extra, allow_multiline=True)[:8000]
        if data.chat_model is not None and data.chat_model.strip() in AVAILABLE_CHAT_MODELS:
            cfg["chat_model"] = data.chat_model.strip()
        if data.temperature is not None:
            cfg["temperature"] = max(0.0, min(2.0, float(data.temperature)))
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    try:
        with appstate.state_lock:
            appstate.indices.pop(cliente_id, None)
    except NameError:
        pass
    return await app_tune_get(user)


@app.get("/auth/app/services", response_model=AppServicesResponse)
async def app_services_get(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppServicesResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    info_txt = rag._read_info(cliente_id)
    items = [
        AppServiceProduct(
            id=item.get("id", ""),
            nombre=item.get("nombre", ""),
            descripcion=item.get("descripcion", ""),
        )
        for item in agenda._extract_services_from_info(cliente_id)
    ]
    return AppServicesResponse(cliente_id=cliente_id, items=items, info_chars=len(info_txt))


@app.post("/auth/app/services", response_model=AppServicesResponse)
async def app_services_post(
    data: AppServicesPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppServicesResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    unique: Dict[str, Dict[str, str]] = {}
    for item in data.items:
        nombre = textnorm._sanitize_text(item.nombre)[:160]
        if not nombre:
            continue
        service_id = agenda._normalize_service_id(nombre)
        if not service_id:
            continue
        unique[service_id] = {
            "nombre": nombre,
            "descripcion": textnorm._sanitize_text(item.descripcion, allow_multiline=True)[:800],
        }
    info_txt = portal._replace_services_section(rag._read_info(cliente_id), list(unique.values()))
    rag._write_info(cliente_id, info_txt)
    return await app_services_get(user)




@app.get("/auth/app/whatsapp", response_model=AppWhatsAppResponse)
async def app_whatsapp_get(
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppWhatsAppResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    return whatsapp._app_whatsapp_response(cliente_id, request)


@app.post("/auth/app/whatsapp", response_model=AppWhatsAppResponse)
async def app_whatsapp_post(
    data: AppWhatsAppPayload,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppWhatsAppResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        wa = dict(cfg.get("whatsapp", {}) or {})
        if data.phone_number_id is not None:
            wa["phone_number_id"] = textnorm._sanitize_text(data.phone_number_id)[:120]
        if data.access_token_env is not None:
            wa["access_token_env"] = textnorm._sanitize_text(data.access_token_env)[:120]
        if data.verify_token_env is not None:
            wa["verify_token_env"] = textnorm._sanitize_text(data.verify_token_env)[:120]
        if data.enabled is not None:
            if data.enabled:
                if not clients._plan_feature(cliente_id, "whatsapp_enabled"):
                    raise HTTPException(
                        status_code=403,
                        detail="WhatsApp esta disponible en el plan Business.",
                    )
                if not str(wa.get("phone_number_id", "") or "").strip():
                    raise HTTPException(status_code=400, detail="Indica el Phone Number ID de WhatsApp.")
            wa["enabled"] = bool(data.enabled)
        cfg["whatsapp"] = wa
        next_configs[cliente_id] = cfg
        clients._validate_single_client_runtime(cliente_id, clients._normalize_client_config(cliente_id, cfg))
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    return whatsapp._app_whatsapp_response(cliente_id, request)




@app.get("/auth/app/voice", response_model=AppVoiceResponse)
async def app_voice_get(
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppVoiceResponse:
    return voice._app_voice_response(security._resolve_cliente_for_self_serve_user(user), request)


@app.post("/auth/app/voice", response_model=AppVoiceResponse)
async def app_voice_post(
    data: AppVoicePayload,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppVoiceResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        voice_row = dict(cfg.get("voice", {}) or {})
        if data.enabled is not None:
            if data.enabled and not voice._client_voice_plan_enabled(cliente_id):
                raise HTTPException(status_code=403, detail="El asistente de voz está disponible en el plan Business.")
            voice_row["enabled"] = bool(data.enabled)
        if data.twilio_phone_number is not None:
            voice_row["twilio_phone_number"] = textnorm._sanitize_text(data.twilio_phone_number)[:32]
        if data.openai_voice is not None:
            v = textnorm._sanitize_text(data.openai_voice).lower()
            voice_row["openai_voice"] = v if v in textnorm.VOICE_ALLOWED_OPENAI_VOICES else (voice_row.get("openai_voice") or "alloy")
        if data.widget_enabled is not None:
            if data.widget_enabled and not voice._client_voice_plan_enabled(cliente_id):
                raise HTTPException(status_code=403, detail="La voz en el widget requiere plan Business.")
            voice_row["widget_enabled"] = bool(data.widget_enabled)
        cfg["voice"] = voice_row
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    return voice._app_voice_response(cliente_id, request)


@app.post("/auth/app/voice/session", include_in_schema=False)
async def app_voice_session(
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Token efimero para probar el asistente de voz en el navegador desde el panel del
    cliente (misma llamada simulada que la demo). Requiere plan Business; reutiliza la
    config de voz del cliente, asi que suena igual que el telefono."""
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    config = clients._get_client_config(cliente_id)
    if not voice._client_voice_plan_enabled(cliente_id):
        raise HTTPException(status_code=403, detail="El asistente de voz está disponible en el plan Business.")
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El asistente de voz no esta disponible ahora mismo.",
        )
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"app_voice:{cliente_id}:{client_ip}", settings.APP_VOICE_RATE_LIMIT)
    voice_cfg = config.get("voice") or {}
    max_seconds = int(voice_cfg.get("max_duration_seconds") or 0) or settings.DEMO_VOICE_MAX_SECONDS
    return await voice._mint_voice_session(cliente_id, config, max_seconds=max_seconds, log_tag="app-voice")


@app.post("/auth/app/voice/tool", include_in_schema=False)
async def app_voice_tool(
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Ejecuta una tool de la voz en navegador desde el panel del cliente. A diferencia de la
    demo publica, aqui SI se reserva/cancela de verdad sobre la agenda del propio cliente
    (es el dueno probando su sistema). Reusa _voice_dispatch_tool (la misma logica que el
    telefono). Sin esto el modelo se queda esperando el function_call_output (silencio)."""
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    if not voice._client_voice_plan_enabled(cliente_id):
        raise HTTPException(status_code=403, detail="El asistente de voz está disponible en el plan Business.")
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"app_voice_tool:{cliente_id}:{client_ip}", 60)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    name = str(body.get("name", ""))
    arguments = body.get("arguments", "")
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    return await voice._voice_dispatch_tool(cliente_id, name, arguments, from_number="")


# --- Sem 4: Live Chat (Pro gate stub) --------------------------------------





@app.get("/auth/app/livechat", response_model=List[AppLiveChatSession])
async def app_livechat_list(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> List[AppLiveChatSession]:
    billing._require_pro_plan(user)
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM live_chat_sessions WHERE cliente_id = ? ORDER BY started_at DESC LIMIT 50",
            (cliente_id,),
        ).fetchall()
    return [
        AppLiveChatSession(
            id=r["id"],
            chat_session_id=r["chat_session_id"] or "",
            status=r["status"] or "pending",
            started_at=r["started_at"] or "",
            claimed_at=r["claimed_at"] or "",
            agent_user_id=r["agent_user_id"] or "",
        )
        for r in rows
    ]


# --- Sem 5: Billing (Stripe checkout + portal + plan state) ---



























@app.get("/auth/app/stripe-connect", response_model=StripeConnectStateResponse)
async def app_stripe_connect_state(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> StripeConnectStateResponse:
    cliente_id = str(user["cliente_id"] or "")
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Tu usuario no tiene un negocio asociado.")
    row = stripe_gateway._stripe_connected_account_row(cliente_id)
    if not row:
        return StripeConnectStateResponse(configured=stripe_gateway._stripe_connect_configured())
    status_value = str(row["status"] or "pending")
    requirements_due = int(row["requirements_due"] or 0)
    last_error = ""
    if stripe_gateway._stripe_connect_configured():
        try:
            account = stripe_gateway._stripe_connect_request(
                "GET",
                f"/accounts/{row['stripe_account_id']}?include[0]=configuration.merchant&include[1]=requirements",
            )
            status_value, requirements_due = stripe_gateway._stripe_connect_account_status(account)
            stripe_gateway._save_stripe_connected_account(
                cliente_id,
                user["id"],
                row["stripe_account_id"],
                status_value=status_value,
                requirements_due=requirements_due,
            )
        except HTTPException as exc:
            last_error = str(exc.detail)
            stripe_gateway._save_stripe_connected_account(
                cliente_id,
                user["id"],
                row["stripe_account_id"],
                status_value=status_value,
                requirements_due=requirements_due,
                last_error=last_error,
            )
    return StripeConnectStateResponse(
        configured=stripe_gateway._stripe_connect_configured(),
        connected=True,
        stripe_account_id=row["stripe_account_id"],
        status=status_value,
        requirements_due=requirements_due,
        last_error=last_error,
    )


@app.post("/auth/app/stripe-connect/start", response_model=StripeConnectStartResponse)
async def app_stripe_connect_start(
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> StripeConnectStartResponse:
    if security._session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Accion bloqueada en sesion de admin (impersonacion).")
    return StripeConnectStartResponse(ok=True, onboarding_url=stripe_gateway._stripe_connect_onboarding_url(user, request))


@app.get("/auth/app/stripe-connect/refresh")
async def app_stripe_connect_refresh(
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> RedirectResponse:
    if security._session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Accion bloqueada en sesion de admin (impersonacion).")
    return RedirectResponse(stripe_gateway._stripe_connect_onboarding_url(user, request), status_code=303)


@app.get("/auth/app/stripe-connect/return")
async def app_stripe_connect_return(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> RedirectResponse:
    return RedirectResponse("/app?stripe_connect=returned", status_code=303)














@app.get("/auth/bookings/{booking_id}/payment", response_model=BookingPaymentStateResponse)
async def auth_booking_payment_state(
    booking_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingPaymentStateResponse:
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    service = agenda._get_service_row(booking_row["cliente_id"], booking_row["service_id"]) or agenda._find_service_by_name(
        booking_row["cliente_id"], booking_row["servicio"]
    )
    decision = booking.resolve_payment_requirement(booking_row["cliente_id"], service, booking_row)
    payment = booking._booking_payment_row(booking_id)
    return BookingPaymentStateResponse(
        booking_id=booking_id,
        payment_required=decision["payment_required"],
        payment_optional=decision["payment_optional"],
        payment_status=payment["status"] if payment else booking_row["payment_status"],
        amount_cents=int(payment["amount_cents"] if payment else decision["amount_cents"]),
        currency=payment["currency"] if payment else decision["currency"],
        checkout_url=payment["checkout_url"] if payment else "",
    )


@app.post("/auth/bookings/{booking_id}/payment/checkout", response_model=BookingPaymentStateResponse)
async def auth_booking_payment_checkout(
    booking_id: str,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingPaymentStateResponse:
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    checkout_url = booking.create_booking_payment_checkout(booking_row["cliente_id"], booking_id, request)
    payment = booking._booking_payment_row(booking_id)
    service = agenda._get_service_row(booking_row["cliente_id"], booking_row["service_id"]) or agenda._find_service_by_name(
        booking_row["cliente_id"], booking_row["servicio"]
    )
    decision = booking.resolve_payment_requirement(booking_row["cliente_id"], service, booking_row)
    return BookingPaymentStateResponse(
        booking_id=booking_id,
        payment_required=decision["payment_required"],
        payment_optional=decision["payment_optional"],
        payment_status=payment["status"] if payment else booking_row["payment_status"],
        amount_cents=int(payment["amount_cents"] if payment else 0),
        currency=payment["currency"] if payment else "eur",
        checkout_url=checkout_url,
    )


@app.get("/auth/app/billing", response_model=BillingStateResponse)
async def app_billing_state(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BillingStateResponse:
    sub = db.db_get_subscription_for_user(user["id"]) or db.db_ensure_free_subscription(user["id"])
    sub = db._maybe_reset_subscription_period(sub)
    current_plan = (sub["plan"] or "free").lower()
    return BillingStateResponse(
        subscription=billing._serialize_billing_subscription(sub),
        plans=billing._build_plan_tiers(current_plan),
        portal_available=bool(sub["stripe_customer_id"]) and stripe_gateway._stripe_configured(),
    )


@app.post("/auth/app/billing/checkout", response_model=BillingCheckoutResponse)
async def app_billing_checkout(
    data: BillingCheckoutPayload,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BillingCheckoutResponse:
    if security._session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Acción bloqueada en sesión de admin (impersonación).")
    if not stripe_gateway._stripe_configured():
        raise HTTPException(status_code=503, detail="Stripe no configurado en el servidor.")
    plan = settings._self_serve_plan(data.plan)
    if plan["slug"] == "free":
        raise HTTPException(status_code=400, detail="El plan Free no requiere checkout.")
    price_id = plan["stripe_price_annual"] if data.billing_period == "annual" else plan["stripe_price_monthly"]
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"STRIPE_PRICE_{plan['slug'].upper()}{'_ANNUAL' if data.billing_period == 'annual' else ''} no configurado.",
        )
    stripe_gateway.stripe.api_key = settings.STRIPE_SECRET_KEY
    api_base = textnorm._public_base_url(request)
    sub = db.db_get_subscription_for_user(user["id"]) or db.db_ensure_free_subscription(user["id"])
    customer_kwargs: Dict[str, Any] = {}
    if sub["stripe_customer_id"]:
        customer_kwargs["customer"] = sub["stripe_customer_id"]
    else:
        customer_kwargs["customer_email"] = user["email"]
    session_kwargs: Dict[str, Any] = {
        "mode": "subscription",
        # Si el total recurrente queda en 0 (p.ej. cupon 100% forever), Stripe
        # no pide tarjeta. Para planes de pago normales sigue exigiendola.
        "payment_method_collection": "if_required",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": f"{api_base}/app?billing=success&plan={plan['slug']}",
        "cancel_url": f"{api_base}/app?billing=cancel",
        "client_reference_id": f"self_serve:{user['id']}",
        "metadata": {
            "source": "self_serve",
            "user_id": user["id"],
            "cliente_id": user["cliente_id"] or "",
            "plan": plan["slug"],
            "billing_period": data.billing_period,
        },
        **customer_kwargs,
    }
    coupon_id = (data.coupon or "").strip()
    if coupon_id:
        # Direct coupon injection (server-side). Stripe rejects invalid coupons with 400.
        # `allow_promotion_codes` and `discounts` are mutually exclusive in Checkout.
        session_kwargs["discounts"] = [{"coupon": coupon_id}]
    else:
        session_kwargs["allow_promotion_codes"] = True
    try:
        session = stripe_gateway.stripe.checkout.Session.create(**session_kwargs)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Stripe checkout self-serve fallo user=%s plan=%s: %s", user["id"], plan["slug"], exc)
        raise HTTPException(status_code=502, detail="No se pudo iniciar el checkout.") from exc
    portal._try_record_analytics_event(
        {
            "event": "checkout_started",
            "event_source": "vantelia_app",
            "widget_client_id": user["cliente_id"] or "",
            "cliente_id": user["cliente_id"] or "",
            "user_id": user["id"],
            "plan": plan["slug"],
            "billing_period": data.billing_period,
            "checkout_session_id": session.id or "",
            "source": "self_serve",
        },
        request,
    )
    portal._try_record_analytics_event(
        {
            "event": "upgrade_started",
            "event_source": "vantelia_app",
            "widget_client_id": user["cliente_id"] or "",
            "cliente_id": user["cliente_id"] or "",
            "user_id": user["id"],
            "plan": plan["slug"],
            "billing_period": data.billing_period,
            "checkout_session_id": session.id or "",
            "source": "self_serve",
        },
        request,
    )
    return BillingCheckoutResponse(ok=True, checkout_url=session.url or "")


@app.post("/auth/app/billing/portal", response_model=BillingPortalResponse)
async def app_billing_portal(
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BillingPortalResponse:
    if security._session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Acción bloqueada en sesión de admin (impersonación).")
    if not stripe_gateway._stripe_configured():
        raise HTTPException(status_code=503, detail="Stripe no configurado.")
    sub = db.db_get_subscription_for_user(user["id"])
    if not sub or not sub["stripe_customer_id"]:
        raise HTTPException(status_code=400, detail="No tienes una suscripcion de pago activa.")
    stripe_gateway.stripe.api_key = settings.STRIPE_SECRET_KEY
    api_base = textnorm._public_base_url(request)
    try:
        portal_row = stripe_gateway.stripe.billing_portal.Session.create(
            customer=sub["stripe_customer_id"],
            return_url=f"{api_base}/app",
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Stripe portal fallo user=%s: %s", user["id"], exc)
        raise HTTPException(status_code=502, detail="No se pudo abrir el portal.") from exc
    return BillingPortalResponse(ok=True, portal_url=portal_row.url or "")


@app.get("/auth/schedule", response_model=PortalSchedulePublic)
async def auth_schedule(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalSchedulePublic:
    return agenda._portal_schedule_from_config(portal._portal_client_id_or_403(user, cliente_id))


@app.get("/auth/ai-config", response_model=PortalAiConfigPublic)
async def auth_ai_config(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalAiConfigPublic:
    return portal._portal_ai_config_from_client_config(portal._portal_client_id_or_403(user, cliente_id))


@app.post("/auth/ai-config", response_model=PortalAiConfigPublic)
async def auth_update_ai_config(
    data: PortalAiConfigPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalAiConfigPublic:
    return portal._update_portal_ai_config(
        portal._portal_client_id_or_403(user, cliente_id),
        data,
        full_access=portal._is_admin_client_portal_override(user, cliente_id),
    )


@app.get("/auth/brain", response_model=PortalBrainPublic)
async def auth_brain(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalBrainPublic:
    return rag._portal_brain_for_client(portal._portal_client_id_or_403(user, cliente_id))


@app.post("/auth/brain", response_model=PortalBrainPublic)
async def auth_update_brain(
    data: PortalBrainPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalBrainPublic:
    return rag._update_portal_brain(portal._portal_client_id_or_403(user, cliente_id), data)


@app.post("/auth/schedule", response_model=PortalSchedulePublic)
async def auth_update_schedule(
    data: PortalScheduleUpdatePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalSchedulePublic:
    return agenda._update_client_schedule(portal._portal_client_id_or_403(user, cliente_id), data)


@app.get("/auth/schedule/employee/{employee_id}", response_model=PortalSchedulePublic)
async def auth_employee_schedule(
    employee_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalSchedulePublic:
    return agenda._portal_schedule_from_employee(portal._portal_client_id_or_403(user, cliente_id), employee_id)


@app.post("/auth/schedule/employee/{employee_id}", response_model=PortalSchedulePublic)
async def auth_update_employee_schedule(
    employee_id: str,
    data: PortalScheduleUpdatePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalSchedulePublic:
    return agenda._update_employee_schedule(portal._portal_client_id_or_403(user, cliente_id), employee_id, data)


@app.post("/auth/schedule/message-preview", response_model=PortalMessagePreviewResponse)
async def auth_schedule_message_preview(
    data: PortalMessagePreviewPayload,
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalMessagePreviewResponse:
    return booking._booking_message_preview(portal._portal_client_id_or_403(user, cliente_id), data, request)


@app.post("/auth/schedule/message-test", response_model=AuthSimpleResponse)
async def auth_schedule_message_test(
    data: PortalMessagePreviewPayload,
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    preview = booking._booking_message_preview(target_client_id, data, request)
    target_email = str(data.target_email or data.test_email or user["email"] or "").strip()
    if not target_email:
        raise HTTPException(status_code=400, detail="Indica un email donde enviar la prueba.")
    emailing._send_email_message(target_email, preview.subject, preview.text_body, preview.html_body, cliente_id=target_client_id)
    return AuthSimpleResponse(ok=True, message=f"Correo de prueba enviado a {target_email}.")


@app.post("/auth/schedule/blocks", response_model=PortalAgendaBlockCreateResponse)
async def auth_create_schedule_block(
    data: PortalAgendaBlockPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalAgendaBlockCreateResponse:
    rows, skipped_count, date_from, date_to = agenda._create_agenda_blocks(portal._portal_client_id_or_403(user, cliente_id), data)
    return PortalAgendaBlockCreateResponse(
        items=[agenda._serialize_agenda_block(row) for row in rows],
        created_count=len(rows),
        skipped_count=skipped_count,
        date_from=date_from,
        date_to=date_to,
    )


@app.delete("/auth/schedule/blocks/{block_id}", response_model=AuthSimpleResponse)
async def auth_delete_schedule_block(
    block_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    agenda._delete_agenda_block(portal._portal_client_id_or_403(user, cliente_id), block_id, employee_id="")
    return AuthSimpleResponse(ok=True, message="Bloqueo eliminado correctamente.")


@app.get("/auth/employees", response_model=PortalEmployeesResponse)
async def auth_list_employees(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalEmployeesResponse:
    return agenda._portal_employees_for_client(portal._portal_client_id_or_403(user, cliente_id))


@app.get("/auth/locations", response_model=PortalLocationsResponse)
async def auth_list_locations(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalLocationsResponse:
    return agenda._portal_locations_for_client(portal._portal_client_id_or_403(user, cliente_id))


@app.post("/auth/locations", response_model=PortalLocationPublic)
async def auth_create_location(
    data: PortalLocationPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalLocationPublic:
    security._require_portal_permission(user, "catalog.manage")
    return agenda._create_portal_location(portal._portal_client_id_or_403(user, cliente_id), data)


@app.post("/auth/locations/{location_id}", response_model=PortalLocationPublic)
async def auth_update_location(
    location_id: str,
    data: PortalLocationPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalLocationPublic:
    security._require_portal_permission(user, "catalog.manage")
    return agenda._update_portal_location(
        portal._portal_client_id_or_403(user, cliente_id), location_id, data
    )


@app.delete("/auth/locations/{location_id}", response_model=AuthSimpleResponse)
async def auth_delete_location(
    location_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    security._require_portal_permission(user, "catalog.manage")
    agenda._delete_portal_location(portal._portal_client_id_or_403(user, cliente_id), location_id)
    return AuthSimpleResponse(ok=True, message="Centro eliminado correctamente.")


@app.get("/auth/locations/{location_id}/resources", response_model=PortalResourcesResponse)
async def auth_list_resources(
    location_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalResourcesResponse:
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    return PortalResourcesResponse(
        items=[
            agenda._serialize_portal_resource(row)
            for row in agenda._list_resource_rows(target_client_id, location_id)
        ]
    )


@app.post("/auth/locations/{location_id}/resources", response_model=PortalResourcePublic)
async def auth_create_resource(
    location_id: str,
    data: PortalResourcePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalResourcePublic:
    security._require_portal_permission(user, "catalog.manage")
    return agenda._create_portal_resource(
        portal._portal_client_id_or_403(user, cliente_id), location_id, data
    )


@app.post("/auth/resources/{resource_id}", response_model=PortalResourcePublic)
async def auth_update_resource(
    resource_id: str,
    data: PortalResourcePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalResourcePublic:
    security._require_portal_permission(user, "catalog.manage")
    return agenda._update_portal_resource(
        portal._portal_client_id_or_403(user, cliente_id), resource_id, data
    )


@app.delete("/auth/resources/{resource_id}", response_model=AuthSimpleResponse)
async def auth_delete_resource(
    resource_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    security._require_portal_permission(user, "catalog.manage")
    agenda._delete_portal_resource(portal._portal_client_id_or_403(user, cliente_id), resource_id)
    return AuthSimpleResponse(ok=True, message="Sala eliminada correctamente.")


@app.post("/auth/bookings/{booking_id}/payment/capture", response_model=BookingPaymentActionResponse)
async def auth_capture_booking_payment(
    booking_id: str,
    data: BookingPaymentActionPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingPaymentActionResponse:
    security._require_portal_permission(user, "payments.capture")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    result = booking.capture_booking_payment(
        target_client_id, booking_id, amount_cents=data.amount_cents, reason=data.reason
    )
    return BookingPaymentActionResponse(
        booking_id=booking_id,
        payment_status=result["payment_status"],
        amount_cents=result["amount_cents"],
        message="Retencion cobrada correctamente.",
    )


@app.post("/auth/bookings/{booking_id}/payment/release", response_model=BookingPaymentActionResponse)
async def auth_release_booking_payment(
    booking_id: str,
    data: BookingPaymentActionPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingPaymentActionResponse:
    security._require_portal_permission(user, "payments.capture")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    result = booking.release_booking_payment(target_client_id, booking_id, reason=data.reason)
    return BookingPaymentActionResponse(
        booking_id=booking_id,
        payment_status=result["payment_status"],
        amount_cents=result["amount_cents"],
        message="Retencion liberada sin cobro.",
    )


@app.post("/auth/bookings/{booking_id}/payment/refund", response_model=BookingPaymentActionResponse)
async def auth_refund_booking_payment(
    booking_id: str,
    data: BookingPaymentActionPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingPaymentActionResponse:
    security._require_portal_permission(user, "payments.refund")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    result = booking.refund_booking_payment(
        target_client_id, booking_id, amount_cents=data.amount_cents, reason=data.reason
    )
    return BookingPaymentActionResponse(
        booking_id=booking_id,
        payment_status=result["payment_status"],
        amount_cents=result["amount_cents"],
        message="Reembolso creado correctamente.",
    )


@app.get("/auth/services/{slug}/locations", response_model=ServiceLocationsResponse)
async def auth_service_locations(
    slug: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ServiceLocationsResponse:
    return agenda._service_locations_overview(portal._portal_client_id_or_403(user, cliente_id), slug)


@app.put("/auth/services/{slug}/locations/{location_id}", response_model=ServiceLocationsResponse)
async def auth_set_service_location_override(
    slug: str,
    location_id: str,
    data: ServiceLocationOverridePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ServiceLocationsResponse:
    security._require_portal_permission(user, "catalog.manage")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    agenda._set_service_location_override(target_client_id, slug, location_id, data)
    return agenda._service_locations_overview(target_client_id, slug)


@app.delete("/auth/services/{slug}/locations/{location_id}", response_model=ServiceLocationsResponse)
async def auth_reset_service_location_override(
    slug: str,
    location_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ServiceLocationsResponse:
    security._require_portal_permission(user, "catalog.manage")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    agenda._delete_service_location_override(target_client_id, slug, location_id)
    return agenda._service_locations_overview(target_client_id, slug)


@app.get("/auth/services", response_model=ServicesResponse)
async def auth_list_services(
    cliente_id: str = "",
    include_inactive: bool = True,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ServicesResponse:
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    return ServicesResponse(
        items=[ServicePublic(**svc) for svc in agenda._catalog_services(target_client_id, include_inactive=include_inactive)]
    )


@app.post("/auth/employees", response_model=PortalEmployeePublic)
async def auth_create_employee(
    data: PortalEmployeePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalEmployeePublic:
    security._require_portal_permission(user, "catalog.manage")
    return agenda._create_portal_employee(
        portal._portal_client_id_or_403(user, cliente_id),
        data,
        full_access=portal._is_admin_client_portal_override(user, cliente_id),
    )


@app.post("/auth/employees/{employee_id}", response_model=PortalEmployeePublic)
async def auth_update_employee(
    employee_id: str,
    data: PortalEmployeePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalEmployeePublic:
    security._require_portal_permission(user, "catalog.manage")
    return agenda._update_portal_employee(
        portal._portal_client_id_or_403(user, cliente_id),
        employee_id,
        data,
        full_access=portal._is_admin_client_portal_override(user, cliente_id),
    )


@app.delete("/auth/employees/{employee_id}", response_model=AuthSimpleResponse)
async def auth_delete_employee(
    employee_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    security._require_portal_permission(user, "catalog.manage")
    agenda._delete_portal_employee(portal._portal_client_id_or_403(user, cliente_id), employee_id)
    return AuthSimpleResponse(ok=True, message="Profesional eliminado correctamente.")


@app.post("/auth/employees/{employee_id}/blocks", response_model=PortalAgendaBlockCreateResponse)
async def auth_create_employee_blocks(
    employee_id: str,
    data: PortalAgendaBlockPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> PortalAgendaBlockCreateResponse:
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    agenda._resolve_employee_for_booking(target_client_id, employee_id, require_active=False)
    rows, skipped_count, date_from, date_to = agenda._create_agenda_blocks(
        target_client_id,
        data,
        employee_id=employee_id,
    )
    return PortalAgendaBlockCreateResponse(
        items=[agenda._serialize_agenda_block(row) for row in rows],
        created_count=len(rows),
        skipped_count=skipped_count,
        date_from=date_from,
        date_to=date_to,
    )


@app.delete("/auth/employees/{employee_id}/blocks/{block_id}", response_model=AuthSimpleResponse)
async def auth_delete_employee_block(
    employee_id: str,
    block_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    agenda._resolve_employee_for_booking(target_client_id, employee_id, require_active=False)
    agenda._delete_agenda_block(target_client_id, block_id, employee_id=employee_id)
    return AuthSimpleResponse(ok=True, message="Bloqueo del profesional eliminado correctamente.")


@app.post("/auth/bookings", response_model=BookingActionResponse)
async def auth_create_booking(
    data: StaffBookingCreatePayload,
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingActionResponse:
    """Alta manual de cita desde el portal (walk-in / cita por telefono)."""
    security._require_portal_permission(user, "agenda.create")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    config = clients._get_client_config(target_client_id)
    if not config["booking"]["enabled"]:
        raise HTTPException(status_code=409, detail="La agenda no esta activada para este cliente.")

    booking_date_dt = textnorm._parse_date(data.fecha)
    agenda._validate_booking_window(target_client_id, booking_date_dt)
    booking_date = booking_date_dt.strftime("%Y-%m-%d")
    booking_time = textnorm._parse_time(data.hora).strftime("%H:%M")
    nombre = textnorm._sanitize_text(data.nombre)
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre del cliente es obligatorio.")
    email = textnorm._sanitize_text(data.email)
    telefono = textnorm._sanitize_text(data.telefono)
    servicio = textnorm._sanitize_text(data.servicio)
    notas = textnorm._sanitize_text(data.notas, allow_multiline=True)

    employee_row = agenda._resolve_employee_for_booking(target_client_id, data.employee_id, require_active=False)
    service_row = agenda._find_service_by_name(target_client_id, servicio)
    service_duration = agenda._service_duration_minutes(target_client_id, servicio, employee_row)
    service_id = service_row["slug"] if service_row else ""
    service_price = agenda._service_price_cents_resolved(
        target_client_id, service_row, employee_row["location_id"] or ""
    )

    # Limites de plan (salvo override admin del portal).
    if not portal._is_admin_client_portal_override(user, cliente_id):
        billing._require_active_subscription(target_client_id)
        booking_limit = clients._plan_limits(clients._client_plan(target_client_id)).get("monthly_bookings")
        if booking_limit is not None and booking._count_bookings_this_month(target_client_id) >= int(booking_limit):
            raise HTTPException(
                status_code=429,
                detail="Se ha alcanzado el limite mensual de citas del plan.",
            )

    if not await agenda._booking_slot_available(
        target_client_id, booking_date, booking_time,
        employee_id=employee_row["id"], duration_minutes=service_duration,
    ):
        raise HTTPException(
            status_code=409,
            detail="Ese horario no esta disponible para el profesional seleccionado.",
        )

    booking_id = f"bk_{secrets.token_urlsafe(10)}"
    manage_token = booking._generate_manage_token()
    created_at = timeutils._utc_now_iso()
    start_local, end_local = agenda._booking_start_end(
        target_client_id, booking_date, booking_time,
        employee_id=employee_row["id"], duration_minutes=service_duration,
    )
    booking_timezone = employee_row["timezone"] or config["booking"]["timezone"]

    record = {
        "id": booking_id,
        "cliente_id": target_client_id,
        "employee_id": employee_row["id"],
        "employee_name": employee_row["name"],
        "nombre": nombre,
        "email": email,
        "telefono": telefono,
        "servicio": servicio,
        "booking_date": booking_date,
        "booking_time": booking_time,
        "notas": notas,
        "status": "confirmed",
        "provider_name": "internal",
        "provider_status": "internal",
        "provider_booking_id": "",
        "provider_booking_url": "",
        "manage_token": manage_token,
        "timezone": booking_timezone,
        "start_at": timeutils._to_utc_iso(start_local),
        "end_at": timeutils._to_utc_iso(end_local),
        "confirmed_at": created_at,
        "cancelled_at": "",
        **booking._booking_blank_tracking_fields(),
        "service_id": service_id,
        "service_price_cents": service_price,
        "source": "portal_manual",
        "created_at": created_at,
    }
    try:
        booking._store_booking(record)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese horario acaba de ocuparse. Elige otro tramo.",
        ) from exc
    booking._record_booking_audit(
        booking_id,
        target_client_id,
        "booking_created",
        {
            "status": "confirmed",
            "source": "portal_manual",
            "role": user["role"],
            "user_id": user["id"],
            "employee_id": employee_row["id"],
            "employee_name": employee_row["name"],
        },
    )

    booking_row = booking._get_booking_row_by_id(booking_id)
    if booking_row and email:
        try:
            await booking._send_booking_reminder_by_kind(
                booking_row,
                "confirmed",
                request,
                sent_column="confirmation_email_sent_at",
            )
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("No se ha podido enviar el aviso de la cita manual %s: %s", booking_id, exc)
            booking._mark_booking_email_result(booking_id, status="failed", error=str(exc))

    payment_row = booking._booking_payment_row(booking_id)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado=booking_row["status"] if booking_row else "confirmed",
        mensaje="Cita creada correctamente.",
        employee_id=employee_row["id"],
        employee_name=employee_row["name"],
        manage_url=booking._build_booking_manage_url(manage_token, request),
        payment_status=booking_row["payment_status"] if booking_row else "not_required",
        payment_url=payment_row["checkout_url"] if payment_row else "",
    )


@app.post("/auth/bookings/{booking_id}/cancel", response_model=BookingActionResponse)
async def auth_cancel_booking(
    booking_id: str,
    request: Request,
    data: Optional[BookingCancelPayload] = None,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingActionResponse:
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    security._require_portal_permission(user, "agenda.cancel")

    if booking_row["status"] == "cancelled":
        return BookingActionResponse(
            ok=True,
            booking_id=booking_id,
            estado="cancelled",
            mensaje="La cita ya estaba cancelada.",
            manage_url=booking._booking_row_manage_url(booking_row, request),
            provider_booking_url=booking_row["provider_booking_url"] or "",
        )

    cancel_reason = textnorm._sanitize_text((data.motivo if data else ""), allow_multiline=True)
    await booking._cancel_provider_booking(booking_row)
    booking._update_booking_record(
        booking_id,
        status="cancelled",
        cancelled_at=timeutils._utc_now_iso(),
        provider_status="cancelled",
    )
    booking._record_booking_audit(
        booking_id,
        booking_row["cliente_id"],
        "booking_cancelled",
        {
            "source": "portal",
            "role": user["role"],
            "user_id": user["id"],
            "reason": cancel_reason,
            "reason_sent_to_customer": bool(cancel_reason),
        },
    )
    # Aplica la politica de cancelacion (penalizacion/reembolso) automaticamente.
    try:
        booking.apply_cancellation_policy(booking_row, kind="cancel", actor_source="portal")
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Politica de cancelacion fallo %s: %s", booking_id, exc)
    refreshed = booking._load_booking_or_404(booking_id)
    try:
        await booking._send_booking_reminder_by_kind(
            refreshed,
            "cancelled",
            request,
            extra_message=cancel_reason,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("No se ha podido enviar el aviso de cancelacion %s: %s", refreshed["id"], exc)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado="cancelled",
        mensaje="La cita ha sido cancelada correctamente.",
        manage_url=booking._booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
    )


@app.post("/auth/bookings/{booking_id}/attendance", response_model=BookingActionResponse)
async def auth_mark_booking_attendance(
    booking_id: str,
    data: BookingAttendancePayload,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingActionResponse:
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    security._require_portal_permission(user, "agenda.attendance")
    if booking_row["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="No se puede marcar la asistencia de una cita cancelada.")
    start_at = booking_row["start_at"] or ""
    if start_at:
        start_dt = timeutils._from_utc_iso(start_at)
        if start_dt and start_dt > timeutils._utc_now():
            raise HTTPException(status_code=409, detail="La cita aun no ha ocurrido; no se puede marcar la asistencia.")
    new_status = "completed" if data.attended else "no_show"
    booking._update_booking_record(booking_id, status=new_status, completed_source="manual")
    booking._record_booking_audit(
        booking_id,
        booking_row["cliente_id"],
        "booking_completed" if data.attended else "booking_no_show",
        {
            "source": "portal",
            "role": user["role"],
            "user_id": user["id"],
            "attended": bool(data.attended),
        },
    )
    # No-show: aplica automaticamente la penalizacion de la politica del negocio.
    if not data.attended:
        try:
            booking.apply_cancellation_policy(booking_row, kind="no_show", actor_source="portal")
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("Politica no-show fallo %s: %s", booking_id, exc)
    refreshed = booking._load_booking_or_404(booking_id)
    crm._crm_upsert_contact(
        refreshed["cliente_id"], name=refreshed["nombre"], email=refreshed["email"],
        phone=refreshed["telefono"] or "", source="portal",
        status="cliente" if data.attended else "interesado",
        entity_type="booking", entity_id=refreshed["id"], actor=f"user:{user['id']}",
    )
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado=new_status,
        mensaje="Cita marcada como realizada." if data.attended else "Cita marcada como no asistida.",
        manage_url=booking._booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
    )


@app.get("/auth/bookings/{booking_id}/timeline", response_model=BookingAuditResponse)
async def auth_booking_timeline(
    booking_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingAuditResponse:
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    return BookingAuditResponse(items=[booking._booking_audit_entry_from_row(row) for row in booking._list_booking_audit_rows(booking_id)])


@app.post("/auth/bookings/{booking_id}/reschedule", response_model=BookingActionResponse)
async def auth_reschedule_booking(
    booking_id: str,
    data: BookingReschedulePayload,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingActionResponse:
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    return await booking._update_booking_details(
        booking_row,
        booking._booking_update_payload_from_reschedule(booking_row, data),
        request,
        source="portal",
        audit_payload={"role": user["role"], "user_id": user["id"]},
    )


@app.post("/auth/bookings/{booking_id}/update", response_model=BookingActionResponse)
async def auth_update_booking(
    booking_id: str,
    data: BookingUpdatePayload,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingActionResponse:
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    return await booking._update_booking_details(
        booking_row,
        data,
        request,
        source="portal",
        audit_payload={"role": user["role"], "user_id": user["id"]},
    )


@app.get("/auth/clientes", response_model=List[AdminClienteResumen])
async def auth_clientes(user: sqlite3.Row = Depends(security._require_authenticated_admin_user)) -> List[AdminClienteResumen]:
    _ = user
    from backend.routers import admin_core  # lazy: evita registrar rutas fuera de orden
    return await admin_core.admin_clientes()


@app.get("/auth/users", response_model=AuthManagedUsersResponse)
async def auth_list_users(
    role: str = "",
    cliente_id: str = "",
    include_inactive: bool = True,
    user: sqlite3.Row = Depends(security._require_authenticated_admin_user),
) -> AuthManagedUsersResponse:
    _ = user
    normalized_role = role.strip().lower()
    if normalized_role and normalized_role not in {"admin", "client"}:
        raise HTTPException(status_code=400, detail="Rol invalido.")
    normalized_cliente_id = onboarding_utils.slugify_company(cliente_id) if cliente_id.strip() else ""
    if normalized_cliente_id:
        clients._get_client_config(normalized_cliente_id)
    rows = security._list_users(role=normalized_role, cliente_id=normalized_cliente_id, include_inactive=include_inactive)
    return AuthManagedUsersResponse(
        items=[security._serialize_managed_user(row) for row in rows],
        total=len(rows),
    )


# ─── Suscripciones / Pagos ────────────────────────────────────────────

@app.get("/auth/subscription", response_model=SubscriptionPublic)
async def auth_subscription(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> SubscriptionPublic:
    return billing._build_subscription_public(
        portal._portal_client_id_or_403(user, cliente_id),
        admin_override=portal._is_admin_client_portal_override(user, cliente_id),
    )


@app.post("/auth/subscription/checkout", response_model=SubscriptionCheckoutResponse)
async def auth_subscription_checkout(
    data: SubscriptionCheckoutPayload,
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> SubscriptionCheckoutResponse:
    cid = portal._portal_client_id_or_403(user, cliente_id)
    plan = data.plan.strip().lower()
    price_id, billing_period = stripe_gateway._stripe_price_for_plan(plan, data.billing_period)
    stripe_gateway._stripe_init()

    base_url = textnorm._public_base_url(request)
    success_url = data.success_url or f"{base_url}/portal?subscription=success"
    cancel_url = data.cancel_url or f"{base_url}/portal?subscription=cancel"

    sub = clients._client_subscription(cid)
    customer_kwargs: Dict[str, Any] = {}
    if sub.get("stripe_customer_id"):
        customer_kwargs["customer"] = sub["stripe_customer_id"]
    else:
        customer_kwargs["customer_email"] = str(user["email"])

    try:
        session = stripe_gateway.stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=cid,
            metadata={"cliente_id": cid, "plan": plan, "billing_period": billing_period},
            subscription_data={"metadata": {"cliente_id": cid, "plan": plan, "billing_period": billing_period}},
            billing_address_collection="required",
            phone_number_collection={"enabled": True},
            tax_id_collection={"enabled": True},
            payment_method_collection="if_required",
            allow_promotion_codes=True,
            **customer_kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Error creando Stripe Checkout para %s: %s", cid, exc)
        raise HTTPException(status_code=502, detail="No se pudo iniciar el proceso de pago.") from exc

    return SubscriptionCheckoutResponse(url=session.url, session_id=session.id)

