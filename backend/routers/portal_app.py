"""Endpoints del portal del cliente (`/auth/...`), unos 130 en un solo fichero.

Es el router mas grande del proyecto y el que consume `app_ui/index.html`. Todo
lo que hace una pestana del panel esta aqui. Van por bloques, en este orden:

|  Linea aprox | Bloque | Pestana del portal |
| --- | --- | --- |
|   60 | Contrasena, perfil, `/auth/me` | (sesion) |
|  148 | Dashboard, citas, export | Inicio / Citas |
|  279 | Chats, conversaciones y bandeja (`/auth/inbox/...`) | Chats |
|  529 | Overview, despliegue, apariencia | Asistente / Apariencia |
|  781 | CRM de contactos | Clientes |
|  972 | Canales de envio (email SMTP/Gmail, SMS) | Canales de envio |
| 1358 | Stripe Connect, metodos de pago, cobros y reembolsos | Pagos |
| 1414 | Politica de cancelacion, recordatorios, seguimiento, resenas | Recordatorios |
| 1663 | Acciones sobre una cita (llamada, confirmacion, preview) | Citas (detalle) |
| 1927 | Servicios, WhatsApp, voz, chat en vivo | Servicios / WhatsApp / Voz |
| 2446 | Facturacion del propio SaaS | Cuenta |
| 2573 | Horarios, bloqueos, empleados, centros, salas | Horarios / Equipo |
| 2801 | Retenciones: capturar, liberar, reembolsar | Citas (detalle) |
| 2984 | Alta, cancelacion, asistencia y cambios de cita | Citas |
| 3309 | Venta online: tarjetas regalo y tienda | Ventas |

Reglas al anadir uno:

- Los endpoints se decoran sobre `backend.main.app` DIRECTAMENTE (no hay
  `APIRouter`) para que el orden de registro no cambie. Una ruta generica como
  `/auth/conversations/{kind}/{id}` secuestra a cualquier hermana declarada
  despues: por eso la bandeja vive en `/auth/inbox/...` y no bajo ella.
- El permiso se comprueba SIEMPRE en servidor con
  `security._require_portal_permission(user, clave)`; que la UI esconda el boton
  no cuenta.
- La logica va en el modulo de dominio (`booking`, `commerce`, `agenda`...), no
  aqui: esto resuelve sesion, permisos y forma de la respuesta.
"""
from __future__ import annotations

import copy
import base64
import csv
import hashlib
import json
import re
import secrets
import sqlite3
from datetime import timedelta
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

import httpx
from fastapi import (
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse


import onboarding_utils
from api_models import *  # noqa: F401,F403
from backend import (
    agenda,
    appstate,
    billing,
    booking,
    channel_requests,
    clients,
    commerce,
    crm,
    db,
    emailing,
    inbox,
    messaging,
    onboarding,
    portal,
    rag,
    security,
    settings,
    stripe_gateway,
    textnorm,
    timeutils,
    voice,
    wa_onboarding,
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


# --- Intervencion humana sobre una conversacion (backend/inbox.py) ----------
#
# OJO con el prefijo: van bajo /auth/inbox/ y no bajo /auth/conversations/ porque
# la ruta generica `/auth/conversations/{kind}/{conv_id}` (definida arriba) casaria
# antes y devolveria 404 tratando "takeover" como el id de la conversacion.
#
# El asistente responde solo hasta que alguien del negocio "toma" el chat; a
# partir de ahi calla y contesta la persona desde el panel. Necesario desde que
# el numero vive en Cloud API y el equipo ya no tiene la app del movil.


class ConversationReplyPayload(BaseModel):
    text: str = Field(min_length=1, max_length=3000)


def _wa_conversation_or_403(conv_id: str, user: sqlite3.Row, cliente_id: str = "") -> Tuple[str, str]:
    """Devuelve (cliente_id, telefono) validando que la conversacion es del tenant."""
    target = portal._portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    row = rag._load_chat_session_or_404(conv_id, cliente_id=target)
    origin = str(row["origin"] or "")
    if not origin.startswith("whatsapp:"):
        raise HTTPException(status_code=400, detail="Solo se puede intervenir en conversaciones de WhatsApp.")
    owner = str(row["cliente_id"] or "")
    if target and owner != target:
        raise HTTPException(status_code=404, detail="Conversacion no encontrada.")
    return owner, origin.split("whatsapp:", 1)[1].strip()


@app.get("/auth/inbox/{conv_id}/takeover")
async def auth_conversation_takeover_state(
    conv_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    _wa_conversation_or_403(conv_id, user, cliente_id)
    state = inbox.takeover_state(conv_id)
    state["window_open"] = inbox.window_open(conv_id)
    state["window_note"] = "" if state["window_open"] else inbox.WINDOW_CLOSED_MESSAGE
    return state


@app.post("/auth/inbox/{conv_id}/takeover")
async def auth_conversation_takeover(
    conv_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """El equipo toma la conversacion: el asistente deja de responder en ella."""
    target, _phone = _wa_conversation_or_403(conv_id, user, cliente_id)
    state = inbox.claim(
        conv_id, target,
        agent_user_id=str(user["id"]),
        agent_name=str(user["display_name"] or user["email"] or ""),
    )
    state["window_open"] = inbox.window_open(conv_id)
    return state


@app.delete("/auth/inbox/{conv_id}/takeover")
async def auth_conversation_release(
    conv_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Devuelve la conversacion al asistente."""
    _wa_conversation_or_403(conv_id, user, cliente_id)
    return inbox.release(conv_id)


@app.post("/auth/inbox/{conv_id}/reply")
async def auth_conversation_reply(
    conv_id: str,
    data: ConversationReplyPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Envia un mensaje escrito por una persona del negocio al cliente final."""
    target, phone = _wa_conversation_or_403(conv_id, user, cliente_id)
    texto = textnorm._sanitize_text(data.text, allow_multiline=True)[:3000].strip()
    if not texto:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacio.")
    if not inbox.window_open(conv_id):
        raise HTTPException(status_code=409, detail=inbox.WINDOW_CLOSED_MESSAGE)

    # Se responde SIEMPRE por el numero por el que entro la conversacion: el de la
    # config del tenant puede ser otro (numero de demo compartido, numero por centro)
    # y el cliente recibiria la respuesta desde un numero que no conoce.
    phone_number_id = inbox.inbound_number(conv_id)
    if not phone_number_id:
        wa_cfg = (clients._get_client_config(target).get("whatsapp") or {})
        phone_number_id = str(wa_cfg.get("phone_number_id") or "").strip()
        if not (wa_cfg.get("enabled") and phone_number_id):
            raise HTTPException(status_code=409, detail="WhatsApp no esta configurado para este negocio.")

    # Responder implica atender: si el chat no estaba tomado, se toma solo (y se
    # renueva el plazo con cada mensaje) para que el bot no pise al humano.
    inbox.claim(
        conv_id, target,
        agent_user_id=str(user["id"]),
        agent_name=str(user["display_name"] or user["email"] or ""),
    )
    enviado = await messaging._send_whatsapp_text(
        cliente_id=target, phone_number_id=phone_number_id, to_number=phone, text=texto,
    )
    if not enviado:
        raise HTTPException(status_code=502, detail="WhatsApp no acepto el mensaje. Intentalo de nuevo.")
    rag._record_chat_message(
        session_id=conv_id, cliente_id=target, role="assistant", content=texto, intent="human_reply",
    )
    return {"ok": True, "takeover": inbox.takeover_state(conv_id)}


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
        central_url=assets.get("central_url", f"{api_base}/central/{cliente_id}"),
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
        empresa=cfg.get("empresa", ""),
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
        if data.empresa is not None:
            # Nombre del negocio (separado del nombre del bot). Vacio = usa el del bot.
            cfg["empresa"] = textnorm._sanitize_text(data.empresa)[:120]
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
    if data.provider not in {"vantelia_smtp", "gmail_oauth", "client_smtp"}:
        raise HTTPException(status_code=400, detail="Proveedor de email no valido.")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    if data.provider == "gmail_oauth" and not emailing._client_gmail_connection(cliente_id):
        raise HTTPException(status_code=400, detail="Conecta primero una cuenta de Google.")
    if data.provider == "client_smtp":
        current = security._ensure_channel_settings(cliente_id)
        if not emailing._client_smtp_configured(current):
            raise HTTPException(status_code=400, detail="Configura primero tu cuenta SMTP.")
    security._ensure_channel_settings(cliente_id)
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE client_channel_settings SET email_provider=?, email_fallback_enabled=?, updated_at=? WHERE cliente_id=?",
            (data.provider, int(data.fallback_enabled), timeutils._utc_now_iso(), cliente_id),
        )
        connection.commit()
    return emailing._channel_settings_public(cliente_id)


@app.post("/auth/app/channels/email/smtp/settings", response_model=ChannelSettingsResponse)
async def app_channels_email_smtp_settings(
    data: ChannelEmailSmtpSettingsPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ChannelSettingsResponse:
    security._require_portal_min_role(user, "owner")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    current = security._ensure_channel_settings(cliente_id)
    host = textnorm._sanitize_text(data.host)
    username = textnorm._sanitize_text(data.username)
    from_email = textnorm._normalize_email(data.from_email or username)
    reply_to = textnorm._normalize_email(data.reply_to or from_email)
    from_name = textnorm._sanitize_text(data.from_name) or from_email
    if not host:
        raise HTTPException(status_code=400, detail="Indica el servidor SMTP.")
    if not from_email:
        raise HTTPException(status_code=400, detail="Indica el email remitente.")
    if username and not (data.password or current["email_smtp_password_encrypted"]):
        raise HTTPException(status_code=400, detail="Indica la contrasena SMTP.")
    encrypted_password = current["email_smtp_password_encrypted"]
    if data.password:
        encrypted_password = security._encrypt_channel_secret(data.password)
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE client_channel_settings SET
                email_provider='client_smtp',
                email_fallback_enabled=?,
                email_smtp_host=?,
                email_smtp_port=?,
                email_smtp_username=?,
                email_smtp_password_encrypted=?,
                email_smtp_from_email=?,
                email_smtp_from_name=?,
                email_smtp_reply_to=?,
                email_smtp_starttls=?,
                last_error='',
                updated_at=?
            WHERE cliente_id=?
            """,
            (
                int(data.fallback_enabled), host, int(data.port), username, encrypted_password,
                from_email, from_name, reply_to, int(data.starttls), now, cliente_id,
            ),
        )
        connection.commit()
    security._channel_audit(cliente_id, "email", "smtp_configured", "client_smtp", True)
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


@app.post("/auth/app/channels/sms/twilio-settings", response_model=ChannelSettingsResponse)
async def app_channels_sms_twilio_settings(
    data: ChannelSmsTwilioSettingsPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ChannelSettingsResponse:
    security._require_portal_min_role(user, "owner")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    clients._require_plan_feature(
        cliente_id, "sms_enabled", "El envio por SMS esta disponible desde el plan Business."
    )
    sender = data.sender.strip()
    kind = data.sender_kind.strip().lower()
    if kind not in {"number", "alphanumeric"}:
        raise HTTPException(status_code=400, detail="Tipo de remitente SMS no valido.")
    if not re.fullmatch(r"AC[a-zA-Z0-9]{8,}", data.account_sid.strip()):
        raise HTTPException(status_code=400, detail="Account SID de Twilio no valido.")
    if len(data.auth_token.strip()) < 12:
        raise HTTPException(status_code=400, detail="Indica el Auth Token de Twilio.")
    if kind == "number":
        if not re.fullmatch(r"\+[1-9]\d{7,14}", sender):
            raise HTTPException(status_code=400, detail="El numero remitente debe estar en formato E.164, por ejemplo +34600123456.")
        sms_mode = "twilio_dedicated_number"
    else:
        sender = sender.upper()
        if not re.fullmatch(r"(?=.*[A-Z])[A-Z0-9 ]{3,11}", sender):
            raise HTTPException(status_code=400, detail="El Sender ID debe tener 3-11 caracteres y alguna letra.")
        sms_mode = "twilio_alphanumeric_sender"
    security._ensure_channel_settings(cliente_id)
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE client_channel_settings
            SET sms_mode=?, sms_sender=?, sms_sender_status='active',
                sms_twilio_account_sid_encrypted=?, sms_twilio_auth_token_encrypted=?,
                updated_at=?
            WHERE cliente_id=?
            """,
            (
                sms_mode,
                sender,
                security._encrypt_channel_secret(data.account_sid.strip()),
                security._encrypt_channel_secret(data.auth_token.strip()),
                now,
                cliente_id,
            ),
        )
        connection.commit()
    security._channel_audit(cliente_id, "sms", "twilio_configured", sms_mode, True, sender)
    return emailing._channel_settings_public(cliente_id)


@app.get("/auth/app/channels/requests", response_model=List[ChannelProvisioningRequest])
async def app_channels_requests(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> List[ChannelProvisioningRequest]:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    return [
        ChannelProvisioningRequest(**item)
        for item in channel_requests.list_requests(cliente_id=cliente_id, limit=50)
    ]


@app.post("/auth/app/channels/requests", response_model=ChannelProvisioningRequest)
async def app_channels_request_create(
    data: ChannelProvisioningRequestPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ChannelProvisioningRequest:
    security._require_portal_min_role(user, "owner")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    channel = data.channel.strip().lower()
    request_type = data.request_type.strip().lower()
    if channel == "sms":
        clients._require_plan_feature(
            cliente_id, "sms_enabled", "El envio por SMS esta disponible desde el plan Business."
        )
    if channel == "voice" and not voice._client_voice_plan_enabled(cliente_id):
        raise HTTPException(status_code=403, detail="El asistente de voz esta disponible en el plan Business.")
    requested_sender = data.requested_sender.strip()
    requested_phone = data.requested_phone.strip()
    if request_type == "alphanumeric_sender":
        requested_sender = requested_sender.upper()
        if not re.fullmatch(r"(?=.*[A-Z])[A-Z0-9 ]{3,11}", requested_sender):
            raise HTTPException(status_code=400, detail="El Sender ID debe tener 3-11 caracteres y alguna letra.")
    if request_type in {"managed_number", "dedicated_number", "voice_install"}:
        if not requested_phone:
            raise HTTPException(status_code=400, detail="Indica el numero que quieres usar.")
        requested_phone = textnorm._sanitize_text(requested_phone)[:40]
    try:
        item = channel_requests.create_request(
            cliente_id=cliente_id,
            channel=channel,
            request_type=request_type,
            requested_sender=requested_sender,
            requested_phone=requested_phone,
            contact_name=str(user["display_name"] or ""),
            contact_email=str(user["email"] or ""),
            notes=data.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChannelProvisioningRequest(**item)


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


@app.post("/auth/app/payments/connect/disconnect", response_model=ConnectAccountStatus)
async def app_connect_disconnect(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ConnectAccountStatus:
    """Deja de cobrar por esa cuenta de Stripe. No borra nada en Stripe."""
    security._require_portal_min_role(user, "owner")
    return booking.disconnect_stripe_account(security._resolve_cliente_for_self_serve_user(user))


@app.put("/auth/app/payments/methods", response_model=ConnectAccountStatus)
async def app_payments_methods(
    data: PaymentMethodsPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ConnectAccountStatus:
    """Que metodos de pago acepta el negocio (la tarjeta va siempre)."""
    security._require_portal_min_role(user, "owner")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    return booking.save_payment_method_prefs(cliente_id, bizum=data.bizum, wallets=data.wallets)


@app.get("/auth/app/rebooking-ai")
async def app_rebooking_ai_status(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    target = portal._portal_client_id_or_403(user, cliente_id)
    return {"enabled": booking._ai_rebooking_enabled_for_client(target)}


@app.post("/auth/app/rebooking-ai")
async def app_rebooking_ai_toggle(
    data: ToggleEnabledPayload,
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
        if data.delivery_priority is not None:
            rem["delivery_priority"] = booking._normalize_followup_delivery_priority(data.delivery_priority)
        # On/off de la verificacion por codigo (voz). Acepta el flag nuevo o, por compat, infiere
        # de los canales OTP antiguos (algun canal activo = encendido).
        if data.voice_otp_enabled is not None:
            rem["voice_otp_enabled"] = bool(data.voice_otp_enabled)
        elif data.voice_otp_channels is not None:
            rem["voice_otp_enabled"] = bool(any(data.voice_otp_channels.values()))
        rem.pop("voice_otp_channels", None)  # ya no hay seleccion de canales propia del OTP
        cfg["reminders"] = rem

        booking_cfg = dict(cfg.get("booking", {}) or {})
        booking_dirty = False
        # Canales GLOBALES (una sola tira). Se escriben en abanico (mismo valor a cada aviso)
        # sobre message_template_channels, asi el motor de envio no cambia.
        if data.channels is not None:
            g = {k: bool(data.channels.get(k)) for k in ("email", "whatsapp", "sms")}
            mtc = textnorm._normalize_message_template_channels(
                booking_cfg.get("message_template_channels") or {}
            )
            for kind in mtc:
                mtc[kind] = dict(g)
            booking_cfg["message_template_channels"] = mtc
            booking_dirty = True
        elif data.message_template_channels is not None:
            # Compat: payload viejo {kind:{email,...}} -> se respeta tal cual.
            booking_cfg["message_template_channels"] = textnorm._normalize_message_template_channels(
                data.message_template_channels
            )
            booking_dirty = True
        # On/off por aviso temporizado (confirmed / reminder_24h / reminder_2h).
        if data.steps_enabled is not None:
            mte = textnorm._normalize_message_template_enabled(
                booking_cfg.get("message_template_enabled", {}), booking_cfg.get("message_templates", {})
            )
            for key, val in data.steps_enabled.items():
                if key in mte:
                    mte[key] = bool(val)
            booking_cfg["message_template_enabled"] = mte
            booking_dirty = True
        if booking_dirty:
            cfg["booking"] = booking_cfg
        next_configs[target] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    return FollowUpResponse(**booking._follow_up_overview_dict(target))


@app.post("/auth/app/follow-up/test", response_model=FollowUpTestResponse)
async def app_follow_up_test(
    data: FollowUpTestPayload,
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> FollowUpTestResponse:
    """Prueba REAL de una fase del Seguimiento (envio/llamada) a un destinatario de
    prueba. Devuelve por canal si se entrego, fallo o se omitio. manager+ (coste real)."""
    security._require_portal_min_role(user, "manager")
    target = portal._portal_client_id_or_403(user, cliente_id)
    result = await booking._run_follow_up_test(
        target, data.step, request, email=data.email, phone=data.phone, channels=data.channels
    )
    return FollowUpTestResponse(**result)


@app.get("/auth/app/reviews", response_model=ReviewRequestResponse)
async def app_reviews_get(
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ReviewRequestResponse:
    """Estado del seguimiento post-cita: config + canales por plan + vista previa."""
    target = portal._portal_client_id_or_403(user, cliente_id)
    return ReviewRequestResponse(**booking._reviews_overview_dict(target, request))


@app.put("/auth/app/reviews", response_model=ReviewRequestResponse)
async def app_reviews_put(
    data: ReviewRequestPayload,
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ReviewRequestResponse:
    """Guarda el seguimiento post-cita (peticion de resena). manager+."""
    security._require_portal_min_role(user, "manager")
    target = portal._portal_client_id_or_403(user, cliente_id)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(target, {})
        rev = dict(cfg.get("reviews", {}) or {})
        if data.enabled is not None:
            rev["enabled"] = bool(data.enabled)
        if data.link is not None:
            rev["link"] = textnorm._sanitize_text(data.link)[:600]
        if data.platform is not None:
            rev["platform"] = textnorm._sanitize_text(data.platform)[:60]
        if data.delay_hours is not None:
            rev["delay_hours"] = max(1, min(168, int(data.delay_hours)))
        if data.only_manual_attendance is not None:
            rev["only_manual_attendance"] = bool(data.only_manual_attendance)
        if data.message is not None:
            rev["message"] = textnorm._sanitize_text(data.message, allow_multiline=True)[:800]
        if data.channels is not None:
            rev["channels"] = {
                "email": bool(data.channels.get("email", True)),
                "whatsapp": bool(data.channels.get("whatsapp", False)),
                "sms": bool(data.channels.get("sms", False)),
            }
        cfg["reviews"] = rev
        next_configs[target] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    return ReviewRequestResponse(**booking._reviews_overview_dict(target, request))


@app.post("/auth/bookings/{booking_id}/review-request", response_model=BookingActionResponse)
async def auth_booking_review_request(
    booking_id: str,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingActionResponse:
    """Envia manualmente la peticion de resena de una cita (staff)."""
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    security._require_portal_permission(user, "agenda.attendance")
    cfg = booking._reviews_config(booking_row["cliente_id"])
    if not booking._review_link_valid(cfg["link"]):
        raise HTTPException(status_code=409, detail="Configura primero el enlace de resenas en Seguimiento.")
    res = await booking._send_review_request(booking_row, request, cfg=cfg, manual=True)
    if not res.get("sent_channels"):
        raise HTTPException(status_code=409, detail="No se pudo enviar (sin contacto valido o canal activo).")
    return BookingActionResponse(
        ok=True, booking_id=booking_id, estado=booking_row["status"],
        mensaje="Peticion de resena enviada.",
    )


@app.post("/auth/bookings/{booking_id}/confirm-call", response_model=BookingActionResponse)
async def auth_booking_confirm_call(
    booking_id: str,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> BookingActionResponse:
    """Lanza una llamada de IA al cliente para confirmar su cita (manual).

    Valida estado, telefono y dedup: no coloca una segunda llamada si ya hay una
    reciente para la misma cita (doble clic/reintento). Si falta configuracion de voz,
    telefono o creditos, devuelve un 409 con el motivo concreto."""
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    security._require_portal_permission(user, "agenda.attendance")
    if booking_row["status"] in {"cancelled", "completed", "no_show"}:
        raise HTTPException(status_code=409, detail="Solo se puede llamar para confirmar citas activas.")
    if not (booking_row["telefono"] or "").strip():
        raise HTTPException(status_code=409, detail="La cita no tiene telefono al que llamar.")
    if booking._recent_confirm_call_placed(booking_id):
        raise HTTPException(status_code=409, detail="Ya hay una llamada de confirmacion reciente para esta cita.")
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
    """Reenvia la confirmacion de la cita por los canales configurados (email/WhatsApp/SMS).

    Valida contacto y configuracion: si no hay email/telefono o el correo no esta
    configurado, devuelve un 409 con el motivo concreto en vez de un exito falso."""
    booking_row = booking._load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    security._require_portal_permission(user, "agenda.attendance")
    result = await booking._resend_booking_confirmation(booking_row, request, by_user=user["id"])
    return BookingActionResponse(
        ok=True, booking_id=booking_id, estado=booking_row["status"],
        mensaje=f"Confirmacion enviada por {booking._confirmation_channels_label(result['sent'])}.",
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
    return PaymentLinkResponse(
        payment=booking._payment_public(row), checkout_url=row["checkout_url"],
        qr_svg=commerce._qr_svg(row["checkout_url"]),
    )






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
    # Si el pago emitio una tarjeta regalo o un bono ya usados, exige 'forzar'
    # (el revert del activo lo aplica el webhook charge.refunded).
    commerce._guard_refundable_asset(payment, data.amount_cents, bool(data.force))
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
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE services SET is_active = 0, updated_at = ? WHERE cliente_id = ?",
            (timeutils._utc_now_iso(), cliente_id),
        )
        connection.commit()
    agenda._sync_services_from_info(cliente_id, info_txt)
    return await app_services_get(user)




@app.get("/auth/app/whatsapp", response_model=AppWhatsAppResponse)
async def app_whatsapp_get(
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AppWhatsAppResponse:
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    return whatsapp._app_whatsapp_response(cliente_id, request)


class WhatsAppSignupPayload(BaseModel):
    code: str = Field(min_length=4, max_length=1000)
    waba_id: str = Field(default="", max_length=80)
    phone_number_id: str = Field(default="", max_length=80)
    event: str = Field(default="", max_length=80)


@app.post("/auth/app/whatsapp/connect")
async def app_whatsapp_connect(
    data: WhatsAppSignupPayload,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Cierra el alta self-service de WhatsApp (Embedded Signup + Coexistence).

    El negocio conserva su numero en la app del movil; nosotros guardamos SU token
    y suscribimos su cuenta a nuestro webhook. owner+ (es una conexion de canal).
    """
    security._require_portal_min_role(user, "owner")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    if not wa_onboarding.embedded_signup_available():
        raise HTTPException(status_code=503, detail="La conexion automatica de WhatsApp no esta configurada.")
    if not clients._plan_feature(cliente_id, "whatsapp_enabled"):
        raise HTTPException(status_code=403, detail="WhatsApp esta disponible desde el plan Pro.")
    try:
        cuenta = await wa_onboarding.complete_signup(
            cliente_id,
            code=data.code,
            waba_id=data.waba_id,
            phone_number_id=data.phone_number_id,
            pin=settings.WHATSAPP_ES_PIN,
            event=data.event,
        )
    except Exception as exc:  # noqa: BLE001 - el error de Meta se le muestra al usuario
        security._channel_audit(cliente_id, "whatsapp", "connect_failed", "embedded_signup", False, str(exc)[:300])
        raise HTTPException(status_code=502, detail=f"Meta rechazo la conexion: {exc}")

    # El canal queda operativo con el numero recien conectado.
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        wa = dict(cfg.get("whatsapp", {}) or {})
        wa["enabled"] = True
        wa["phone_number_id"] = cuenta.get("phone_number_id", "")
        cfg["whatsapp"] = wa
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    security._channel_audit(cliente_id, "whatsapp", "connect", "embedded_signup", True)
    return {"ok": True, "account": cuenta}


@app.delete("/auth/app/whatsapp/connect")
async def app_whatsapp_disconnect(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, bool]:
    """Desconecta el numero: dejamos de responder por el (Meta conserva su cuenta)."""
    security._require_portal_min_role(user, "owner")
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    borrado = wa_onboarding.disconnect(cliente_id)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        wa = dict(cfg.get("whatsapp", {}) or {})
        wa["enabled"] = False
        cfg["whatsapp"] = wa
        next_configs[cliente_id] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    security._channel_audit(cliente_id, "whatsapp", "disconnect", "embedded_signup", True)
    return {"ok": borrado}


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
        if data.transfer_number is not None:
            voice_row["transfer_number"] = textnorm._sanitize_text(data.transfer_number)[:32]
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


@app.post("/auth/app/voice/log", include_in_schema=False)
async def app_voice_log(
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Registra la transcripcion de la prueba de voz del panel del cliente.

    El panel habla directo con OpenAI por WebRTC; sin este endpoint la llamada de prueba
    solo vive en el navegador y se pierde al cerrar.
    """
    cliente_id = security._resolve_cliente_for_self_serve_user(user)
    if not voice._client_voice_plan_enabled(cliente_id):
        raise HTTPException(status_code=403, detail="El asistente de voz estÃ¡ disponible en el plan Business.")
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"app_voice_log:{cliente_id}:{client_ip}", 30)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw = (body or {}).get("transcript") if isinstance(body, dict) else None
    transcript: List[Dict[str, str]] = []
    for item in (raw or [])[:300]:
        if not isinstance(item, dict):
            continue
        text = textnorm._sanitize_text(str(item.get("text", "")), allow_multiline=True)[:2000]
        if not text:
            continue
        role = "assistant" if str(item.get("role")) in ("assistant", "bot") else "user"
        transcript.append({"role": role, "text": text, "ts": str(item.get("ts", ""))[:40]})
    if not transcript:
        return {"ok": True, "skipped": True}
    try:
        duration = max(0, min(7200, int((body or {}).get("duration_seconds") or 0)))
    except (TypeError, ValueError):
        duration = 0
    # Etiqueta de resultado acumulada por el front (paridad con el motor de telefono).
    outcome = str((body or {}).get("outcome") or "").strip().lower()
    if outcome not in ("reservada", "cancelada", "reprogramada", "transferida"):
        outcome = ""
    text_all = "\n".join(f"{i['role']}: {i['text']}" for i in transcript)
    summary = await timeutils._to_thread(voice._voice_summarize, text_all)
    booking_created = 1 if voice._voice_detect_booking_intent(text_all) else 0
    now = timeutils._utc_now().isoformat()
    call_sid = "app_" + secrets.token_hex(8)
    try:
        with db._get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO voice_calls (call_sid, cliente_id, from_number, to_number, started_at, ended_at,
                                         duration_seconds, status, transcript_json, summary, booking_created,
                                         direction, purpose, outcome)
                VALUES (?, ?, '', '', ?, ?, ?, 'completed', ?, ?, ?, 'inbound', 'app_test', ?)
                """,
                (call_sid, cliente_id, now, now, duration,
                 json.dumps(transcript, ensure_ascii=False), summary, booking_created, outcome),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] no se pudo registrar prueba de voz del panel %s: %s", cliente_id, exc)
        return {"ok": False}
    return {"ok": True, "call_sid": call_sid}


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
    emailing._send_client_email(target_client_id, target_email, preview.subject, preview.text_body, preview.html_body)
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
    email = textnorm._normalize_email(data.email)
    telefono = textnorm._sanitize_text(data.telefono)
    servicio = textnorm._sanitize_text(data.servicio)
    notas = textnorm._sanitize_text(data.notas, allow_multiline=True)
    if email and not booking._booking_email_looks_valid(email):
        raise HTTPException(status_code=400, detail="Indica un email valido o deja el email vacio.")
    missing_reminder_contact = not booking._booking_has_reminder_contact(email, telefono)
    contact_warning = (
        "Cita creada sin email ni telefono valido: no recibira confirmaciones ni recordatorios automaticos."
        if missing_reminder_contact else ""
    )

    employee_row = agenda._resolve_employee_for_booking(target_client_id, data.employee_id, require_active=False)
    service_duration = agenda._service_duration_minutes(target_client_id, servicio, employee_row)

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

    booking_row = await booking._create_booking_core(
        target_client_id,
        employee_row=employee_row,
        nombre=nombre,
        email=email,
        telefono=telefono,
        servicio=servicio,
        booking_date=booking_date,
        booking_time=booking_time,
        notas=notas,
        source="portal_manual",
        request=request,
        audit_extra={"role": user["role"], "user_id": user["id"]},
    )
    booking_id = booking_row["id"]
    if missing_reminder_contact:
        booking._record_booking_audit(
            booking_id,
            target_client_id,
            "booking_contact_missing",
            {"source": "portal_manual", "warning": contact_warning},
        )

    payment_row = booking._booking_payment_row(booking_id)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado=booking_row["status"],
        mensaje=contact_warning or "Cita creada correctamente.",
        warning=contact_warning,
        employee_id=employee_row["id"],
        employee_name=employee_row["name"],
        manage_url=booking._build_booking_manage_url(booking_row["manage_token"], request),
        payment_status=booking_row["payment_status"],
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

    refreshed = await booking._cancel_booking_core(
        booking_row,
        source="portal",
        reason=(data.motivo if data else ""),
        request=request,
        audit_extra={"role": user["role"], "user_id": user["id"]},
    )
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



# --- Compra publica de tarjetas regalo: config del portal --------------------------

@app.get("/auth/app/gift-cards-public")
async def app_gift_public_get(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Config de la compra publica de tarjetas + estado real (Stripe operativo) + URL."""
    target = portal._portal_client_id_or_403(user, cliente_id)
    cfg = commerce._gift_public_config(target)
    try:
        account = booking._connect_account_status(target)
        stripe_ready = bool(account.connected and account.charges_enabled)
    except Exception:  # noqa: BLE001
        stripe_ready = False
    base = textnorm._preferred_public_base_url().rstrip("/")
    return {
        **cfg,
        "stripe_ready": stripe_ready,
        "available": cfg["enabled"] and stripe_ready,
        "public_url": f"{base}/gift/{target}",
        # Consulta publica de saldo: disponible tambien para tarjetas de mostrador.
        "balance_url": f"{base}/gift/{target}/saldo",
    }


@app.get("/auth/app/shop-public")
async def app_shop_public_get(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Config de la tienda online (bonos + productos) + estado real (Stripe, catalogo)."""
    target = portal._portal_client_id_or_403(user, cliente_id)
    cfg = commerce._shop_public_config(target)
    availability = commerce.shop_public_available(target)
    try:
        account = booking._connect_account_status(target)
        stripe_ready = bool(account.connected and account.charges_enabled)
    except Exception:  # noqa: BLE001
        stripe_ready = False
    active_packages = len(commerce._list_packages(target, include_inactive=False))
    active_products = len(commerce._list_products(target, include_inactive=False))
    base = textnorm._preferred_public_base_url().rstrip("/")
    return {
        **cfg,
        "stripe_ready": stripe_ready,
        "available_packages": availability["packages"],
        "available_products": availability["products"],
        "active_packages": active_packages,
        "active_products": active_products,
        "public_url": f"{base}/tienda/{target}",
    }


@app.put("/auth/app/shop-public")
async def app_shop_public_put(
    data: Dict[str, Any],
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Guarda la config de la tienda online. manager+ (catalogo)."""
    security._require_portal_min_role(user, "manager")
    target = portal._portal_client_id_or_403(user, cliente_id)
    data = data or {}
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(target, {})
        sp = dict(cfg.get("shop_public", {}) or {})
        for key in ("enabled_packages", "enabled_products"):
            if key in data:
                sp[key] = bool(data.get(key))
        if "intro_text" in data:
            sp["intro_text"] = textnorm._sanitize_text(str(data.get("intro_text") or ""))[:300]
        if "pickup_note" in data:
            sp["pickup_note"] = textnorm._sanitize_text(str(data.get("pickup_note") or ""))[:200]
        if "accent_color" in data:
            ac = textnorm._sanitize_text(str(data.get("accent_color") or "")).strip()
            sp["accent_color"] = ac if commerce._GIFT_ACCENT_RE.match(ac) else ""
        if "hero_image_url" in data:
            sp["hero_image_url"] = textnorm._public_image_url(data.get("hero_image_url"))
        if "hero_tagline" in data:
            sp["hero_tagline"] = textnorm._sanitize_text(str(data.get("hero_tagline") or ""))[:140]
        cfg["shop_public"] = sp
        next_configs[target] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    return await app_shop_public_get(cliente_id=cliente_id, user=user)


@app.put("/auth/app/gift-cards-public")
async def app_gift_public_put(
    data: Dict[str, Any],
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Guarda la config de compra publica de tarjetas. manager+ (catalogo)."""
    security._require_portal_min_role(user, "manager")
    target = portal._portal_client_id_or_403(user, cliente_id)
    data = data or {}
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(target, {})
        gp = dict(cfg.get("gift_cards_public", {}) or {})
        if "enabled" in data:
            gp["enabled"] = bool(data.get("enabled"))
        if "suggested_amounts" in data:
            amounts = []
            for item in (data.get("suggested_amounts") or [])[:6]:
                try:
                    cents = int(item)
                except (TypeError, ValueError):
                    continue
                if 100 <= cents <= 100000 and cents not in amounts:
                    amounts.append(cents)
            gp["suggested_amounts"] = amounts
        for key in ("min_cents", "max_cents"):
            if key in data:
                try:
                    gp[key] = max(100, min(100000, int(data.get(key))))
                except (TypeError, ValueError):
                    pass
        if "validity_days" in data:
            try:
                gp["validity_days"] = max(0, min(3650, int(data.get("validity_days"))))
            except (TypeError, ValueError):
                pass
        if "intro_text" in data:
            gp["intro_text"] = textnorm._sanitize_text(str(data.get("intro_text") or ""))[:300]
        if "assistant_knowledge" in data:
            gp["assistant_knowledge"] = textnorm._sanitize_text(
                str(data.get("assistant_knowledge") or ""),
                allow_multiline=True,
            )[:commerce.GIFT_PUBLIC_ASSISTANT_KNOWLEDGE_MAX_CHARS]
        cfg["gift_cards_public"] = gp
        next_configs[target] = cfg
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    rag._invalidate_client_runtime(target)
    return await app_gift_public_get(cliente_id=cliente_id, user=user)
