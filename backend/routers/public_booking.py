"""Endpoints: seccion public_booking (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

import secrets
import sqlite3
from typing import Any, Dict, List

import httpx
from fastapi import (
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse


from api_models import *  # noqa: F401,F403
from backend import (
    agenda,
    billing,
    booking,
    clients,
    db,
    demo_agenda,
    outreach,
    portal,
    rag,
    security,
    settings,
    textnorm,
    timeutils,
    voice,
)
from backend import chat as chat_mod
from backend.main import app

@app.get("/booking/manage/{manage_token}", include_in_schema=False)
async def booking_manage_page(manage_token: str, request: Request) -> HTMLResponse:
    booking_row = booking._load_booking_by_token_or_404(manage_token)
    booking_row = booking._booking_public_detail_from_row(booking_row, request)
    viewer = str(request.query_params.get("viewer", "customer")).strip().lower()
    if viewer not in {"customer", "client"}:
        viewer = "customer"
    return HTMLResponse(booking._booking_manage_page(booking_row, viewer=viewer))


@app.get("/p/{manage_token}", include_in_schema=False)
async def booking_payment_shortlink(manage_token: str, request: Request) -> RedirectResponse:
    """Enlace corto de pago: redirige al checkout de Stripe de esa cita.

    Existe para no mandar 300 caracteres de URL por WhatsApp o SMS. No expone
    nada: el token es el mismo que ya gobierna la gestion de la cita. Si ya esta
    pagada o no hay cobro pendiente, lleva a la pagina de la cita en vez de dar
    un error que el cliente no sabria interpretar.
    """
    booking_row = booking._load_booking_by_token_or_404(manage_token)
    pago = booking._booking_payment_row(booking_row["id"])
    destino = ""
    # "expired": la sesion de Stripe ya no vale y la cita se cancelo con ella, asi que
    # llevarle al checkout muerto solo le ensena un error de Stripe.
    if pago and pago["status"] not in ("paid", "preauthorized", "expired"):
        destino = pago["checkout_url"] or ""
    return RedirectResponse(
        destino or booking._build_booking_manage_url(manage_token, request), status_code=302
    )


@app.get("/booking/confirm/{manage_token}", include_in_schema=False)
async def booking_confirm_page(manage_token: str, request: Request) -> HTMLResponse:
    """Pagina de confirmacion de asistencia (enlace del email).

    Abrirla NO confirma nada: hay que pulsar el boton, que llama al POST. Un GET
    no debe cambiar el estado, y ademas los antivirus y previsualizadores de
    correo abren los enlaces: antes daban por confirmadas citas que el cliente ni
    habia llegado a ver."""
    booking_row = booking._load_booking_by_token_or_404(manage_token)
    company = clients._get_client_config(booking_row["cliente_id"])["nombre"]
    when_text = booking._booking_datetime_display(booking_row)
    manage_url = booking._booking_row_manage_url(booking_row, request)
    if booking_row["status"] == "cancelled":
        estado = "cancelled"
    elif booking._booking_confirmed_by_customer(booking_row["id"]):
        estado = "already"
    else:
        estado = "pending"
    return HTMLResponse(
        booking._booking_confirm_result_page(
            company, state=estado, when_text=when_text, manage_url=manage_url,
            cliente_id=booking_row["cliente_id"],
        )
    )


@app.post("/booking/confirm/{manage_token}", response_model=BookingActionResponse)
async def booking_confirm_action(manage_token: str) -> BookingActionResponse:
    """Confirma la asistencia. Idempotente: repetirlo no rompe nada."""
    booking_row = booking._load_booking_by_token_or_404(manage_token)
    if booking_row["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="Esta cita esta cancelada y no se puede confirmar.")
    ya_estaba = booking._booking_confirmed_by_customer(booking_row["id"])
    if not ya_estaba:
        booking._mark_booking_confirmed_by_customer(
            booking_row["id"], booking_row["cliente_id"], channel="email"
        )
    fresco = booking._get_booking_row_by_id(booking_row["id"]) or booking_row
    return BookingActionResponse(
        ok=True,
        booking_id=booking_row["id"],
        estado=fresco["status"],
        mensaje="Ya estaba confirmada, gracias." if ya_estaba else "Asistencia confirmada. Te esperamos.",
    )


@app.get("/booking/manage/{manage_token}/data", response_model=BookingDetailPublic)
async def booking_manage_data(manage_token: str, request: Request) -> BookingDetailPublic:
    booking_row = booking._load_booking_by_token_or_404(manage_token)
    return booking._booking_public_detail_from_row(booking_row, request)


@app.post("/booking/manage/{manage_token}/cancel", response_model=BookingActionResponse)
async def booking_manage_cancel(manage_token: str, request: Request) -> BookingActionResponse:
    booking_row = booking._load_booking_by_token_or_404(manage_token)
    if booking_row["status"] == "cancelled":
        return BookingActionResponse(
            ok=True,
            booking_id=booking_row["id"],
            estado="cancelled",
            mensaje="La cita ya estaba cancelada.",
            manage_url=booking._booking_row_manage_url(booking_row, request),
            provider_booking_url=booking_row["provider_booking_url"] or "",
        )
    refreshed = await booking._cancel_booking_core(
        booking_row,
        source="customer",
        request=request,
        audit_extra={"channel": "public_manage"},
    )
    return BookingActionResponse(
        ok=True,
        booking_id=refreshed["id"],
        estado="cancelled",
        mensaje="Tu cita ha sido cancelada correctamente.",
        manage_url=booking._booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
    )


@app.post("/booking/manage/{manage_token}/reschedule", response_model=BookingActionResponse)
async def booking_manage_reschedule(
    manage_token: str,
    data: BookingReschedulePayload,
    request: Request,
) -> BookingActionResponse:
    booking_row = booking._load_booking_by_token_or_404(manage_token)
    return await booking._update_booking_details(
        booking_row,
        booking._booking_update_payload_from_reschedule(booking_row, data),
        request,
        source="customer",
    )


@app.post("/booking/manage/{manage_token}/update", response_model=BookingActionResponse)
async def booking_manage_update(
    manage_token: str,
    data: BookingUpdatePayload,
    request: Request,
) -> BookingActionResponse:
    booking_row = booking._load_booking_by_token_or_404(manage_token)
    protected_payload = data.model_copy(update={"email": booking_row["email"]})
    return await booking._update_booking_details(
        booking_row,
        protected_payload,
        request,
        source="customer",
    )


@app.get("/cliente/{cliente_id}", response_model=ConfigPublicaCliente)
async def info_cliente(cliente_id: str, request: Request) -> ConfigPublicaCliente:
    textnorm._assert_valid_client_id(cliente_id)
    security._enforce_allowed_origin(request, cliente_id)
    config = clients._get_client_config(cliente_id)

    contacto = config.get("contacto", {})
    branding = config.get("branding", {})

    launcher_shape = str(config.get("launcher_shape", "circle") or "circle").lower()
    if launcher_shape not in ("circle", "bar"):
        launcher_shape = "circle"
    try:
        launcher_size = int(config.get("launcher_size", 60) or 60)
    except (TypeError, ValueError):
        launcher_size = 60
    if launcher_shape == "circle":
        launcher_size = max(48, min(96, launcher_size))
    else:
        launcher_size = max(120, min(280, launcher_size))

    booking_enabled = bool(config["booking"]["enabled"]) and clients._client_booking_plan_enabled(cliente_id)
    starter_questions = settings._resolve_widget_starters(config, booking_enabled=booking_enabled)

    return ConfigPublicaCliente(
        nombre=config["nombre"],
        icono=config["icono"],
        color=config["color"],
        accent_color=config.get("accent_color", ""),
        logo_url=config.get("logo_url", ""),
        launcher_shape=launcher_shape,
        launcher_size=launcher_size,
        bienvenida=config["bienvenida"],
        booking_enabled=booking_enabled,
        branding_text=branding.get("powered_by", "Powered by Vantelia"),
        contact_email=contacto.get("email", ""),
        contact_phone=contacto.get("telefono", ""),
        starter_questions=starter_questions,
        voice_widget_enabled=voice._voice_widget_enabled(cliente_id, config),
    )


@app.get("/centros/{cliente_id}")
async def public_locations(cliente_id: str, request: Request) -> Dict[str, List[Dict[str, Any]]]:
    textnorm._assert_valid_client_id(cliente_id)
    security._enforce_allowed_origin(request, cliente_id)
    return {
        "items": [
            {
                "location_id": row["id"],
                "name": row["name"],
                "address": row["address"] or "",
                "phone": row["phone"] or "",
                "is_default": bool(row["is_default"]),
            }
            for row in agenda._list_location_rows(cliente_id, include_inactive=False)
        ]
    }


@app.get("/profesionales/{cliente_id}")
async def public_employees(
    cliente_id: str, request: Request, location_id: str = ""
) -> Dict[str, List[Dict[str, Any]]]:
    textnorm._assert_valid_client_id(cliente_id)
    security._enforce_allowed_origin(request, cliente_id)
    location_filter = agenda._resolve_location_id(cliente_id, location_id) if location_id else ""
    return {
        "items": [
            {
                "employee_id": row["id"],
                "name": row["name"],
                "role_label": row["role_label"] or "",
                "color": agenda._normalize_employee_color(row["color"] or "#00b1d9"),
                "is_default": bool(row["is_default"]),
                "location_id": row["location_id"] or "",
                "service_ids": agenda._employee_service_ids_from_row(row, cliente_id),
                "allows_all_services": not agenda._employee_service_ids_from_row(row, cliente_id),
            }
            for row in agenda._list_public_employee_rows(
                cliente_id, include_inactive=False, location_id=location_filter
            )
        ]
    }


@app.post("/chat", response_model=RespuestaChat)
async def chat(data: MensajeChat, request: Request) -> RespuestaChat:
    textnorm._assert_valid_client_id(data.cliente_id)
    security._enforce_allowed_origin(request, data.cliente_id)
    rag._cleanup_sessions()

    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"chat:{data.cliente_id}:{client_ip}", settings.CHAT_RATE_LIMIT)

    message = textnorm._sanitize_text(data.mensaje, allow_multiline=True)
    if not message:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacio.")

    # Self-serve quota (Sem 5): only applies to clientes owned by a self-serve user.
    # Legacy clients fall through to the original public-plan checks below.
    self_serve_sub = db.db_check_self_serve_quota(data.cliente_id)

    if not self_serve_sub:
        # Plan legacy: bloquear si suscripción cancelada o se supera límite mensual
        billing._require_active_subscription(data.cliente_id)
        sub = clients._client_subscription(data.cliente_id)
        if sub.get("status") in {"canceled", "past_due"}:
            raise HTTPException(status_code=402, detail="La suscripción de este asistente no está activa.")
        conv_limit = clients._plan_limits(sub["plan"]).get("monthly_conversations")
        if conv_limit is not None and billing._count_conversations_this_month(data.cliente_id) >= int(conv_limit):
            raise HTTPException(
                status_code=429,
                detail="Se ha alcanzado el límite mensual de conversaciones del plan. Contacta con la empresa para ampliar el plan.",
            )

    session_id = rag._normalize_session_id(data.session_id)

    def _record_persisted_demo_message(persisted_session_id: str) -> None:
        outreach._outreach_record_demo_chat_message(
            data.cliente_id, persisted_session_id
        )

    try:
        response = await chat_mod._process_chat_message(
            cliente_id=data.cliente_id,
            message=message,
            session_id=session_id,
            request=request,
            on_user_message_persisted=_record_persisted_demo_message,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        settings.logger.exception("Error procesando chat de %s: %s", data.cliente_id, exc)
        raise HTTPException(status_code=500, detail="No se pudo procesar el mensaje.") from exc

    # Count this bot reply against the owner's monthly quota (only for self-serve).
    if self_serve_sub:
        try:
            db.db_increment_message_usage(data.cliente_id, count=1, kind="bot_reply")
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("No se pudo incrementar usage en %s: %s", data.cliente_id, exc)
    return response


@app.get("/disponibilidad", response_model=RespuestaDisponibilidad)
async def disponibilidad(
    cliente_id: str,
    fecha: str,
    request: Request,
    employee_id: str = "",
    servicio: str = "",
    location_id: str = "",
) -> RespuestaDisponibilidad:
    textnorm._assert_valid_client_id(cliente_id)
    security._enforce_allowed_origin(request, cliente_id)
    config = clients._get_client_config(cliente_id)

    if not config["booking"]["enabled"]:
        raise HTTPException(status_code=404, detail="La reserva online no esta habilitada para este cliente.")
    if not clients._client_booking_plan_enabled(cliente_id):
        raise booking._booking_plan_unavailable_error()

    selected_day = textnorm._parse_date(fecha)
    agenda._validate_booking_window(cliente_id, selected_day)
    location_filter = agenda._resolve_location_id(cliente_id, location_id) if location_id else ""

    try:
        if employee_id:
            employee_row = agenda._resolve_employee_for_booking(cliente_id, employee_id)
            if servicio and not agenda._service_name_allowed_for_employee(cliente_id, employee_row, servicio):
                raise HTTPException(
                    status_code=400,
                    detail="El servicio seleccionado no esta disponible para ese profesional.",
                )
            slots, available_slots = await agenda._employee_slot_sets_for_day(
                cliente_id,
                fecha,
                employee_row=employee_row,
                servicio=servicio,
            )

            return RespuestaDisponibilidad(
                fecha=fecha,
                timezone=employee_row["timezone"] or config["booking"]["timezone"],
                employee_id=employee_row["id"],
                slots=[
                    SlotDisponibilidad(hora=hora, disponible=hora in available_slots)
                    for hora in sorted(slots)
                ],
            )

        all_slots, available_slots = await agenda._public_slot_sets_for_day(
            cliente_id,
            fecha,
            servicio=textnorm._sanitize_text(servicio),
            location_id=location_filter,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        settings.logger.error("No se pudo consultar disponibilidad externa de %s: %s", cliente_id, exc)
        raise HTTPException(
            status_code=502,
            detail="No se ha podido consultar la disponibilidad del proveedor de calendario.",
        ) from exc

    return RespuestaDisponibilidad(
        fecha=fecha,
        timezone=config["booking"]["timezone"],
        employee_id="",
        slots=[
            SlotDisponibilidad(hora=hora, disponible=hora in available_slots)
            for hora in sorted(all_slots)
        ],
    )


@app.post("/agendar", response_model=RespuestaAgendado)
async def agendar(data: DatosCita, request: Request) -> RespuestaAgendado:
    textnorm._assert_valid_client_id(data.cliente_id)
    security._enforce_allowed_origin(request, data.cliente_id)
    config = clients._get_client_config(data.cliente_id)

    if not config["booking"]["enabled"]:
        raise HTTPException(status_code=404, detail="La reserva online no esta habilitada para este cliente.")
    if not clients._client_booking_plan_enabled(data.cliente_id):
        raise booking._booking_plan_unavailable_error()

    # Plan: límite mensual de citas
    billing._require_active_subscription(data.cliente_id)
    booking_limit = clients._plan_limits(clients._client_plan(data.cliente_id)).get("monthly_bookings")
    if booking_limit is not None and booking._count_bookings_this_month(data.cliente_id) >= int(booking_limit):
        raise HTTPException(
            status_code=429,
            detail="Se ha alcanzado el límite mensual de citas del plan. Contacta con la empresa para ampliar el plan.",
        )

    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"booking:{data.cliente_id}:{client_ip}", settings.BOOKING_RATE_LIMIT)

    booking_date_dt = textnorm._parse_date(data.fecha)
    agenda._validate_booking_window(data.cliente_id, booking_date_dt)
    booking_date = booking_date_dt.strftime("%Y-%m-%d")
    booking_time = textnorm._parse_time(data.hora).strftime("%H:%M")
    nombre = textnorm._sanitize_text(data.nombre)
    email = textnorm._normalize_email(data.email)
    telefono = textnorm._sanitize_text(data.telefono)
    servicio = textnorm._sanitize_text(data.servicio)
    notas = textnorm._sanitize_text(data.notas, allow_multiline=True)
    if email and not booking._booking_email_looks_valid(email):
        raise HTTPException(status_code=400, detail="Indica un email valido o deja el email vacio y usa un telefono.")
    if not booking._booking_has_reminder_contact(email, telefono):
        raise HTTPException(status_code=400, detail="Indica al menos un email o telefono para poder enviar confirmaciones y recordatorios.")
    location_filter = (
        agenda._resolve_location_id(data.cliente_id, data.location_id) if data.location_id else ""
    )
    employee_row = await agenda._resolve_public_booking_employee(
        data.cliente_id,
        booking_date,
        booking_time,
        employee_id=data.employee_id,
        servicio=servicio,
        location_id=location_filter,
    )

    stored_booking = await booking._create_booking_core(
        data.cliente_id,
        employee_row=employee_row,
        nombre=nombre,
        email=email,
        telefono=telefono,
        servicio=servicio,
        booking_date=booking_date,
        booking_time=booking_time,
        notas=notas,
        source="widget",
        webhook_source="vantelia_widget",
        request=request,
    )
    payment_row = booking._booking_payment_row(stored_booking["id"])
    return RespuestaAgendado(
        ok=True,
        booking_id=stored_booking["id"],
        estado=stored_booking["status"],
        mensaje=config["booking"]["success_message"],
        employee_id=employee_row["id"],
        employee_name=employee_row["name"],
        provider_name=stored_booking["provider_name"] or "",
        provider_booking_id=stored_booking["provider_booking_id"] or "",
        provider_booking_url=stored_booking["provider_booking_url"] or "",
        manage_url=booking._build_booking_manage_url(stored_booking["manage_token"], request),
        payment_status=stored_booking["payment_status"],
        payment_url=payment_row["checkout_url"] if payment_row else "",
    )


@app.get("/servicios/{cliente_id}")
async def servicios(
    cliente_id: str, request: Request, employee_id: str = "", location_id: str = ""
) -> Dict[str, List[Dict[str, Any]]]:
    textnorm._assert_valid_client_id(cliente_id)
    security._enforce_allowed_origin(request, cliente_id)
    location_filter = agenda._resolve_location_id(cliente_id, location_id) if location_id else ""
    return {"servicios": booking._public_services_for_booking(cliente_id, employee_id, location_filter)}


@app.post("/auth/services", response_model=ServicePublic)
async def auth_create_service(
    data: ServicePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ServicePublic:
    security._require_portal_permission(user, "catalog.manage")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    agenda._ensure_services_seeded(target_client_id)
    name = textnorm._sanitize_text(data.nombre)
    slug = agenda._normalize_service_id(name)
    if not name or not slug:
        raise HTTPException(status_code=400, detail="Nombre de servicio invalido.")
    if agenda._get_service_row(target_client_id, slug):
        raise HTTPException(status_code=409, detail="Ya existe un servicio con ese nombre.")
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO services
            (cliente_id, slug, name, duration_minutes, price_cents, description, is_active, sort_order,
             payment_mode, payment_type, deposit_amount_cents, currency, image_url, category,
             booking_note, cancel_free_hours, cancel_late_fee_pct, no_show_fee_pct, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_client_id, slug, name, int(data.duration_minutes), int(data.price_cents),
                textnorm._sanitize_text(data.descripcion, allow_multiline=True),
                1 if data.is_active else 0, int(data.sort_order),
                data.payment_mode, data.payment_type, int(data.deposit_amount_cents),
                data.currency.lower(), textnorm._public_image_url(data.image_url),
                textnorm._sanitize_text(data.category)[:60],
                textnorm._sanitize_text(data.booking_note, allow_multiline=True)[:1000],
                None if data.cancel_free_hours is None else int(data.cancel_free_hours),
                None if data.cancel_late_fee_pct is None else int(data.cancel_late_fee_pct),
                None if data.no_show_fee_pct is None else int(data.no_show_fee_pct),
                now, now,
            ),
        )
        connection.commit()
    return ServicePublic(**agenda._service_row_to_public(agenda._get_service_row(target_client_id, slug)))


@app.patch("/auth/services/{slug}", response_model=ServicePublic)
async def auth_update_service(
    slug: str,
    data: ServiceUpdatePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> ServicePublic:
    security._require_portal_permission(user, "catalog.manage")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    row = agenda._get_service_row(target_client_id, slug)
    if not row:
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    updates: Dict[str, Any] = {}
    if data.nombre is not None:
        name = textnorm._sanitize_text(data.nombre)
        if not name:
            raise HTTPException(status_code=400, detail="Nombre de servicio invalido.")
        duplicate_slug = agenda._normalize_service_id(name)
        duplicate = agenda._get_service_row(target_client_id, duplicate_slug)
        if duplicate is not None and duplicate["slug"] != slug:
            raise HTTPException(status_code=409, detail="Ya existe un servicio con ese nombre.")
        updates["name"] = name
    if data.duration_minutes is not None:
        updates["duration_minutes"] = int(data.duration_minutes)
    if data.price_cents is not None:
        updates["price_cents"] = int(data.price_cents)
    if data.descripcion is not None:
        updates["description"] = textnorm._sanitize_text(data.descripcion, allow_multiline=True)
    if data.is_active is not None:
        updates["is_active"] = 1 if data.is_active else 0
    if data.sort_order is not None:
        updates["sort_order"] = int(data.sort_order)
    if data.payment_mode is not None:
        updates["payment_mode"] = data.payment_mode
    if data.payment_type is not None:
        updates["payment_type"] = data.payment_type
    if data.deposit_amount_cents is not None:
        updates["deposit_amount_cents"] = int(data.deposit_amount_cents)
    if data.currency is not None:
        updates["currency"] = data.currency.lower()
    if data.image_url is not None:
        updates["image_url"] = textnorm._public_image_url(data.image_url)
    if data.category is not None:
        updates["category"] = textnorm._sanitize_text(data.category)[:60]
    if data.booking_note is not None:
        updates["booking_note"] = textnorm._sanitize_text(data.booking_note, allow_multiline=True)[:1000]
    # Overrides de politica de cancelacion por servicio: -1 = reset a heredar (NULL).
    for field_name, col in (
        ("cancel_free_hours", "cancel_free_hours"),
        ("cancel_late_fee_pct", "cancel_late_fee_pct"),
        ("no_show_fee_pct", "no_show_fee_pct"),
    ):
        value = getattr(data, field_name)
        if value is not None:
            updates[col] = None if int(value) < 0 else int(value)
    if updates:
        updates["updated_at"] = timeutils._utc_now_iso()
        assignments = ", ".join(f"{col} = ?" for col in updates)
        with db._get_db_connection() as connection:
            connection.execute(
                f"UPDATE services SET {assignments} WHERE cliente_id = ? AND slug = ?",
                (*updates.values(), target_client_id, slug),
            )
            connection.commit()
        updated_row = agenda._get_service_row(target_client_id, slug)
        if updated_row is not None:
            demo_agenda._sync_demo_bookings_for_service(
                target_client_id,
                old_slug=slug,
                old_name=row["name"] or "",
                service_row=updated_row,
            )
    return ServicePublic(**agenda._service_row_to_public(agenda._get_service_row(target_client_id, slug)))


@app.delete("/auth/services/{slug}", response_model=AuthSimpleResponse)
async def auth_delete_service(
    slug: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    security._require_portal_permission(user, "catalog.manage")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    if not agenda._get_service_row(target_client_id, slug):
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    with db._get_db_connection() as connection:
        connection.execute(
            "DELETE FROM services WHERE cliente_id = ? AND slug = ?", (target_client_id, slug)
        )
        connection.execute(
            "DELETE FROM service_payment_policies WHERE cliente_id = ? AND service_id = ?", (target_client_id, slug)
        )
        connection.commit()
    return AuthSimpleResponse(ok=True, message="Servicio eliminado.")




































































