"""Ciclo de vida de citas multi-tenant (refactor F3).

Alta (_store_booking), codigos y manage tokens, serializacion, emails/SMS/WA
de confirmacion y recordatorio, cancelacion/reprogramacion (tambien por
codigo en chat), asistencia/auto-complete, auditoria, webhooks de pago de
cita (Stripe Connect) y enlaces de pago enviados por la IA.

Es el modulo mas grande del backend. Para orientarte, los cuatro sitios que
concentran casi todo (mapa completo en docs/MAPA_DEL_CODIGO.md):

* MUTACIONES: `_create_booking_core`, `_cancel_booking_core`,
  `_update_booking_details`, `_mark_booking_confirmed_by_customer`. TODOS los
  canales (web, WhatsApp, voz, panel) pasan por aquí; no reimplementes el
  pipeline en un canal nuevo.
* AVISOS AL CLIENTE: `_send_booking_reminder_by_kind` es el unico punto de
  salida. Decide canales con `_channels_reaching_customer` y el texto con
  `_booking_email_bodies` (email y SMS) o `_whatsapp_notice_text` (WhatsApp:
  todo lo de `WA_NOTICE_KINDS`, escrito para leerse en un movil).
* COBROS: `resolve_payment_requirement` (¿hay que pagar?),
  `create_booking_payment_checkout` (enlace) y `process_booking_payment_webhook`
  (entra el dinero). El estado de cobro se calcula en `backend/paystate.py`,
  que suma los DOS sistemas de pago.
* CONSULTA: serializadores para el portal y la pagina publica de gestion.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException, Request, status

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from api_models import (
    AdminBookingResumen,
    AdminReminderRunResult,
    BookingActionResponse,
    BookingAuditEntry,
    BookingDetailPublic,
    BookingReschedulePayload,
    BookingUpdatePayload,
    ConnectAccountStatus,
    CustomerPaymentPublic,
    PortalBookingSummary,
    PortalMessagePreviewPayload,
    PortalMessagePreviewResponse,
    PortalScheduleUpdatePayload,
)
from backend import agenda, appstate, clients, crm, db, emailing, inbox, messaging, paystate, security, settings, stripe_gateway, textnorm, timeutils, wa_demo

_FOLLOWUP_DELIVERY_CHANNELS = ("email", "whatsapp", "sms")
_BOOKING_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def _normalize_followup_delivery_priority(value: Any) -> List[str]:
    raw = value if isinstance(value, list) else []
    out: List[str] = []
    for item in raw:
        channel = str(item or "").strip().lower()
        if channel in _FOLLOWUP_DELIVERY_CHANNELS and channel not in out:
            out.append(channel)
    for channel in _FOLLOWUP_DELIVERY_CHANNELS:
        if channel not in out:
            out.append(channel)
    return out


def _booking_email_looks_valid(email: str) -> bool:
    return bool(_BOOKING_EMAIL_RE.match(textnorm._normalize_email(email)))


def _booking_has_reminder_contact(email: str, telefono: str) -> bool:
    if _booking_email_looks_valid(email):
        return True
    return bool(messaging._normalize_sms_recipient(telefono))


def _booking_reminder_worker() -> None:
    interval_seconds = max(300, settings.REMINDER_RUN_INTERVAL_MINUTES * 60)
    if settings.REMINDER_RUN_INTERVAL_MINUTES <= 0:
        settings.logger.info("Recordatorios automáticos desactivados por configuración.")
        return

    settings.logger.info(
        "Motor de recordatorios automaticos iniciado. Intervalo: %s minutos.",
        settings.REMINDER_RUN_INTERVAL_MINUTES,
    )
    while not appstate.booking_reminder_stop.is_set():
        try:
            try:
                from backend import demo_agenda  # lazy: evita ciclo booking<->demo
                purged_demos = demo_agenda._purge_expired_demos()
                if purged_demos:
                    settings.logger.info("Demos expiradas purgadas en background: %s", purged_demos)
            except Exception as exc:  # noqa: BLE001
                settings.logger.error("Error purgando demos en background: %s", exc)

            auto_confirmed = _auto_confirm_pending_bookings()
            if auto_confirmed:
                settings.logger.info(
                    "Citas pendientes confirmadas automaticamente: %s",
                    auto_confirmed,
                )
            auto_completed = _auto_complete_past_bookings()
            if auto_completed:
                settings.logger.info(
                    "Citas marcadas como completadas automaticamente: %s",
                    auto_completed,
                )
            result = asyncio.run(_run_booking_reminders())
            if result.sent_24h or result.sent_2h or result.failed:
                settings.logger.info(
                    "Recordatorios procesados automaticamente. 24h=%s 2h=%s fallos=%s",
                    result.sent_24h,
                    result.sent_2h,
                    result.failed,
                )
            # Seguimiento post-cita: peticiones de resena (opt-in por negocio).
            try:
                review_sent = asyncio.run(_run_review_requests())
                if review_sent:
                    settings.logger.info("Peticiones de resena enviadas: %s", review_sent)
            except Exception as exc:  # noqa: BLE001
                settings.logger.error("Error en el envio de peticiones de resena: %s", exc)
            # Tarjetas regalo compradas online pendientes de enviar (inmediatas cuyo
            # email fallo en el webhook + programadas cuya fecha llego).
            try:
                from backend import commerce as _commerce  # tardio: evita ciclo
                gift_sent = _commerce._send_pending_gift_card_emails()
                if gift_sent:
                    settings.logger.info("Tarjetas regalo enviadas: %s", gift_sent)
            except Exception as exc:  # noqa: BLE001
                settings.logger.error("Error enviando tarjetas regalo pendientes: %s", exc)
            # Ciclo de vida de comercio: caducidad proxima (bono/tarjeta) y recompra
            # tras agotar el bono. Default ON; apagable por tenant en config
            # reminders.lifecycle_emails.
            try:
                from backend import commerce as _commerce  # tardio: evita ciclo
                lifecycle = _commerce._run_commerce_lifecycle_notices()
                if any(lifecycle.values()):
                    settings.logger.info("Avisos de ciclo de vida de comercio: %s", lifecycle)
            except Exception as exc:  # noqa: BLE001
                settings.logger.error("Error en avisos de ciclo de vida de comercio: %s", exc)
            # Rebooking proactivo por IA (opt-in por negocio, como mucho 1 pasada/dia).
            try:
                if _ai_rebooking_due():
                    nudged = asyncio.run(_run_ai_rebooking_pass())
                    appstate.ai_rebooking_last_run = timeutils._utc_now_iso()
                    if nudged:
                        settings.logger.info("Rebooking IA: %s clientes reenganchados.", nudged)
            except Exception as exc:  # noqa: BLE001
                settings.logger.error("Error en el rebooking IA: %s", exc)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("Error en el motor automatico de recordatorios: %s", exc)

        appstate.booking_reminder_stop.wait(interval_seconds)


# ---------------------------------------------------------------------------
# Rebooking proactivo por IA (re-enganche de clientes inactivos por WhatsApp)
# ---------------------------------------------------------------------------

AI_REBOOKING_AFTER_DAYS = int(os.getenv("AI_REBOOKING_AFTER_DAYS", "28") or "28")
AI_REBOOKING_DEDUP_DAYS = int(os.getenv("AI_REBOOKING_DEDUP_DAYS", "56") or "56")
AI_REBOOKING_CAP_PER_CLIENT = int(os.getenv("AI_REBOOKING_CAP_PER_CLIENT", "15") or "15")
AI_REBOOKING_RUN_INTERVAL_HOURS = int(os.getenv("AI_REBOOKING_RUN_INTERVAL_HOURS", "24") or "24")


def _ai_rebooking_enabled_for_client(cliente_id: str) -> bool:
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT ai_rebooking_enabled FROM client_channel_settings WHERE cliente_id=?",
            (cliente_id,),
        ).fetchone()
    return bool(row["ai_rebooking_enabled"]) if row and "ai_rebooking_enabled" in row.keys() else False


def _ai_rebooking_due() -> bool:
    last = getattr(appstate, "ai_rebooking_last_run", "") or ""
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    return (timeutils._utc_now() - last_dt) >= timedelta(hours=AI_REBOOKING_RUN_INTERVAL_HOURS)


def _ai_rebooking_candidates(cliente_id: str) -> List[Dict[str, str]]:
    """Telefonos cuya ultima cita realizada fue hace >= AFTER dias, sin cita futura y
    sin nudge reciente. Devuelve [{phone, servicio}]."""
    today = timeutils._utc_now().date()
    cutoff_date = (today - timedelta(days=AI_REBOOKING_AFTER_DAYS)).isoformat()
    dedup_cutoff = (timeutils._utc_now() - timedelta(days=AI_REBOOKING_DEDUP_DAYS)).isoformat()
    candidates: List[Dict[str, str]] = []
    with db._get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT telefono, MAX(booking_date) AS last_date
            FROM bookings
            WHERE cliente_id=? AND telefono<>'' AND status='completed'
            GROUP BY telefono
            HAVING last_date <= ?
            ORDER BY last_date DESC
            """,
            (cliente_id, cutoff_date),
        ).fetchall()
        for row in rows:
            phone = row["telefono"]
            future = connection.execute(
                """
                SELECT 1 FROM bookings
                WHERE cliente_id=? AND telefono=? AND booking_date>=?
                  AND status IN ('confirmed','pending_review','pending_payment')
                LIMIT 1
                """,
                (cliente_id, phone, today.isoformat()),
            ).fetchone()
            if future:
                continue
            nudged = connection.execute(
                "SELECT 1 FROM ai_rebooking_log WHERE cliente_id=? AND contact_phone=? AND sent_at>=? LIMIT 1",
                (cliente_id, phone, dedup_cutoff),
            ).fetchone()
            if nudged:
                continue
            last_service = connection.execute(
                """
                SELECT servicio FROM bookings
                WHERE cliente_id=? AND telefono=? AND status='completed'
                ORDER BY booking_date DESC LIMIT 1
                """,
                (cliente_id, phone),
            ).fetchone()
            candidates.append({"phone": phone, "servicio": (last_service["servicio"] if last_service else "") or ""})
            if len(candidates) >= AI_REBOOKING_CAP_PER_CLIENT:
                break
    return candidates


def _ai_rebooking_text(cliente_id: str, servicio: str) -> str:
    config = clients._get_client_config(cliente_id)
    nombre = config.get("nombre", "") or "nosotros"
    svc = f" tu {servicio}" if servicio else " tu cita"
    return (
        f"Hola 👋 Soy el asistente de {nombre}. Hace un tiempo que no vienes — "
        f"¿quieres que te reserve{svc}? Respóndeme y te busco el mejor hueco."
    )


def _log_ai_rebooking(cliente_id: str, phone: str, servicio: str) -> None:
    with db._get_db_connection() as connection:
        connection.execute(
            "INSERT INTO ai_rebooking_log (cliente_id, contact_phone, servicio, sent_at) VALUES (?, ?, ?, ?)",
            (cliente_id, phone, servicio, timeutils._utc_now_iso()),
        )
        connection.commit()


async def _run_ai_rebooking_pass() -> int:
    nudged_clients = 0
    for cliente_id in list(appstate.CONFIG_CLIENTES.keys()):
        if not _ai_rebooking_enabled_for_client(cliente_id):
            continue
        config = clients._get_client_config(cliente_id)
        whatsapp_cfg = config.get("whatsapp", {}) or {}
        phone_number_id = str(whatsapp_cfg.get("phone_number_id", "") or "").strip()
        if not (whatsapp_cfg.get("enabled") and phone_number_id):
            continue
        any_sent = False
        for cand in _ai_rebooking_candidates(cliente_id):
            try:
                ok = await messaging._send_whatsapp_text(
                    cliente_id=cliente_id,
                    phone_number_id=phone_number_id,
                    to_number=cand["phone"],
                    text=_ai_rebooking_text(cliente_id, cand["servicio"]),
                )
            except Exception as exc:  # noqa: BLE001
                settings.logger.error("Rebooking IA: fallo enviando a %s: %s", cand["phone"], exc)
                ok = False
            if ok:
                _log_ai_rebooking(cliente_id, cand["phone"], cand["servicio"])
                any_sent = True
        if any_sent:
            nudged_clients += 1
    return nudged_clients


def _public_services_for_booking(
    cliente_id: str, employee_id: str = "", location_id: str = ""
) -> List[Dict[str, Any]]:
    if employee_id:
        employee_row = agenda._get_employee_row(employee_id, cliente_id=cliente_id)
        return agenda._services_for_employee(cliente_id, employee_row)

    public_rows = agenda._list_public_employee_rows(
        cliente_id, include_inactive=False, location_id=location_id
    )
    all_services = agenda._catalog_services(cliente_id, location_id=location_id)
    if not public_rows:
        return all_services

    if any(not agenda._employee_service_ids_from_row(row, cliente_id) for row in public_rows):
        return all_services

    allowed_ids = {
        service_id
        for row in public_rows
        for service_id in agenda._employee_service_ids_from_row(row, cliente_id)
    }
    return [service for service in all_services if str(service.get("id") or "") in allowed_ids]


def _booking_plan_unavailable_error() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail="Las reservas online no están incluidas en el plan actual. Actualiza a un plan con agenda para activar esta funcion.",
    )


def _count_bookings_this_month(cliente_id: str) -> int:
    period_start, _ = clients._current_billing_period()
    try:
        with db._get_db_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM bookings WHERE cliente_id = ? AND created_at >= ?",
                (cliente_id, period_start),
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


# Los clientes escriben deprisa y con erratas: "quiero agendare una cita" no abria
# el formulario, porque \bagendar\b exige la palabra exacta, y "quiero una cita"
# tampoco casaba al meter una palabra por medio. Ahora los verbos admiten sus
# terminaciones habituales y la peticion admite palabras intermedias. Van SIN
# tildes: el mensaje se normaliza antes de compararlo.
BOOKING_INTENT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\b(agendar|agendarme|agendarla|agendarlo|agendare|agenda|agendo)\b",
        r"\b(reservar|reservarme|reservarla|reservarlo|reservare|reserva|reservo)\b",
        r"\b(formulario|mostrar formulario|ensename el formulario)\b",
        r"\b(pedir|coger|solicitar|sacar|concertar|apuntarme)\s+(una\s+)?cita\b",
        # "quiero / quisiera / necesito ... cita", con lo que metan por medio.
        r"\b(quiero|quisiera|queria|necesito|me gustaria|podria|puedo)\b[^.?!]{0,24}\bcita\b",
    ]
]


def _message_requests_booking_form(message: str) -> bool:
    """¿Pide cita NUEVA? Gestionar una que ya tiene es otra cosa."""
    normalized = textnorm._strip_accents(" ".join(str(message or "").lower().split()))
    # "quiero cancelar mi cita" tambien dice "quiero ... cita": sin descartarlo
    # aqui, pedir una cancelacion abriria el formulario de reserva.
    if _message_requests_cancel_booking(message) or _message_requests_reschedule_booking(message):
        return False
    return any(pattern.search(normalized) for pattern in BOOKING_INTENT_PATTERNS)


def _get_booking_provider(config: Dict[str, Any]) -> str:
    _ = config
    return "internal"


def _normalize_message_kind(kind: str) -> str:
    normalized = textnorm._sanitize_text(kind).lower()
    normalized = settings.MESSAGE_KIND_ALIASES.get(normalized, normalized)
    if normalized not in settings.DEFAULT_MESSAGE_TEMPLATES:
        raise HTTPException(status_code=400, detail="Tipo de plantilla no valido.")
    return normalized


def _booking_preview_context(
    cliente_id: str,
    schedule: PortalScheduleUpdatePayload,
    request: Optional[Request] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    config = clients._get_client_config(cliente_id)
    message_templates = textnorm._normalize_message_templates(schedule.message_templates)
    message_enabled = textnorm._normalize_message_template_enabled(
        schedule.message_template_enabled,
        schedule.message_templates,
    )
    fecha, hora = agenda._sample_booking_preview_slot(schedule)
    booking_row = {
        "cliente_id": cliente_id,
        "servicio": "Revision profesional",
        "booking_date": fecha,
        "booking_time": hora,
        "timezone": textnorm._sanitize_text(schedule.timezone) or settings.DEFAULT_TIMEZONE,
        "email": config.get("contacto", {}).get("email", ""),
    }
    manage_url = _build_booking_manage_url("preview-demo-link", request)
    return booking_row, {
        "message_templates": message_templates,
        "message_template_enabled": message_enabled,
        "contact_email": config.get("contacto", {}).get("email", ""),
        "contact_phone": config.get("contacto", {}).get("telefono", ""),
        "company_name": config["nombre"],
    }, manage_url


def _booking_email_subject(
    status_key: str,
    company_name: str,
    booking_row: Any,
) -> str:
    service_name = booking_row["servicio"] or "tu cita"
    if status_key == "pending_payment":
        return f"Falta el pago para confirmar tu cita con {company_name}"
    if status_key == "received":
        return f"Hemos recibido tu solicitud con {company_name}"
    if status_key == "cancelled":
        return f"Tu cita con {company_name} ha sido cancelada"
    if status_key == "rescheduled":
        return f"Tu cita con {company_name} ha cambiado de fecha"
    if status_key == "reminder_24h":
        return f"Recordatorio: mañana tienes {service_name} con {company_name}"
    if status_key == "reminder_2h":
        return f"Recordatorio: tu cita con {company_name} empieza pronto"
    return f"Tu cita con {company_name} ha sido confirmada"


def _booking_datetime_display(booking_row: sqlite3.Row) -> str:
    try:
        selected = datetime.strptime(
            f"{booking_row['booking_date']} {booking_row['booking_time']}",
            "%Y-%m-%d %H:%M",
        )
        return selected.strftime("%d/%m/%Y a las %H:%M")
    except ValueError:
        return f"{booking_row['booking_date']} {booking_row['booking_time']}"


def _booking_email_bodies(
    booking_row: Any,
    company_name: str,
    status_key: str,
    manage_url: str,
    contact_email: str,
    contact_phone: str,
    message_templates: Optional[Dict[str, str]] = None,
    confirm_url: str = "",
) -> Tuple[str, str]:
    service_name = booking_row["servicio"] or "Consulta"
    try:
        _svc_price_cents = int(booking_row["service_price_cents"] or 0)
    except (KeyError, IndexError):
        _svc_price_cents = 0
    try:
        _has_start = bool(booking_row["start_at"])
    except (KeyError, IndexError):
        _has_start = False
    _svc_bits: List[str] = []
    _svc_duration = agenda._booking_row_duration_min(booking_row, booking_row["cliente_id"]) if _has_start else 0
    if _svc_duration:
        _svc_bits.append(f"{_svc_duration} min")
    _svc_price_label = textnorm._format_price_cents(_svc_price_cents)
    if _svc_price_label:
        _svc_bits.append(_svc_price_label)
    service_suffix = f" ({' · '.join(_svc_bits)})" if _svc_bits else ""
    when_text = _booking_datetime_display(booking_row)
    try:
        booking_code = (booking_row["booking_code"] or "").strip()
    except (KeyError, IndexError):
        booking_code = ""
    show_confirm = bool(confirm_url) and status_key in ("confirmed", "reminder_24h")
    manage_line = f"\nGestiona tu cita aquí: {manage_url}\n" if manage_url else ""
    if show_confirm:
        manage_line = (
            f"\nConfirma tu asistencia: {confirm_url}\n"
            + (f"Cancelar o cambiar la cita: {manage_url}\n" if manage_url else "")
        )
    confirm_button_html = (
        (
            f'<a href="{escape(confirm_url)}" '
            f'style="display:inline-block;margin:0 8px 8px 0;padding:12px 20px;border-radius:12px;'
            f'background:#16a34a;color:#ffffff;text-decoration:none;font-weight:700;">'
            f'&#10003; Confirmar asistencia</a>'
        )
        if show_confirm
        else ""
    )
    manage_button_label = "Cancelar o cambiar" if show_confirm else "Gestionar cita"
    manage_button_html = (
        (
            f'<a href="{escape(manage_url)}" '
            f'style="display:inline-block;margin:0 8px 8px 0;padding:12px 18px;border-radius:12px;'
            f'background:#0b6b8a;color:#ffffff;text-decoration:none;font-weight:700;">'
            f'{manage_button_label}</a>'
        )
        if manage_url
        else ""
    )
    manage_html = (
        f'<p style="margin:20px 0;">{confirm_button_html}{manage_button_html}</p>'
        if (manage_button_html or confirm_button_html)
        else ""
    )
    contact_lines = []
    if contact_phone:
        contact_lines.append(f"Teléfono: {contact_phone}")
    if contact_email:
        contact_lines.append(f"Email: {contact_email}")
    contact_text = "\n".join(contact_lines)
    contact_html = "".join(f"<li>{escape(item)}</li>" for item in contact_lines)

    intro_map = {
        "received": "Hemos recibido tu solicitud de cita y la estamos revisando.",
        "confirmed": settings.DEFAULT_MESSAGE_TEMPLATES["confirmed"],
        "cancelled": settings.DEFAULT_MESSAGE_TEMPLATES["cancelled"],
        "rescheduled": settings.DEFAULT_MESSAGE_TEMPLATES["rescheduled"],
        "reminder_24h": settings.DEFAULT_MESSAGE_TEMPLATES["reminder_24h"],
        "reminder_2h": settings.DEFAULT_MESSAGE_TEMPLATES["reminder_2h"],
    }
    templates = textnorm._normalize_message_templates(message_templates or {})
    intro_map.update(
        {
            "confirmed": templates["confirmed"],
            "cancelled": templates["cancelled"],
            "rescheduled": templates["rescheduled"],
            "reminder_24h": templates["reminder_24h"],
            "reminder_2h": templates["reminder_2h"],
        }
    )
    intro = intro_map.get(status_key, intro_map["confirmed"])
    # Que ha pagado ya y que le queda por pagar. Sin esto, quien deja una señal
    # de 50 EUR recibe el mismo email que quien paga el servicio entero.
    _cobro_texto = ""
    if status_key in ("confirmed", "received", "reminder_24h", "reminder_2h"):
        try:
            _cobro_texto = paystate.customer_line(
                paystate.summary_for_booking(booking_row["cliente_id"], booking_row)
            )
        except Exception as exc:  # noqa: BLE001 - el email vale mas que la linea de cobro
            settings.logger.debug("No se pudo calcular el cobro para el email: %s", exc)
    _cobro_line = f"Pago: {_cobro_texto}\n" if _cobro_texto else ""

    # Con la señal sin pagar, el número de reserva todavia no se entrega: la cita
    # puede caerse. Lo que necesita es el enlace de pago.
    if status_key == "pending_payment":
        booking_code = ""
    codigo_line = f"Número de reserva: {booking_code}\n" if booking_code else ""
    text_body = (
        f"{intro}\n\n"
        f"{codigo_line}"
        f"Empresa: {company_name}\n"
        f"Servicio: {service_name}{service_suffix}\n"
        f"Fecha y hora: {when_text}\n"
        f"Zona horaria: {booking_row['timezone']}\n"
        f"{_cobro_line}"
        f"{manage_line}"
    )
    if booking_code:
        text_body += (
            "\nGuarda tu número de reserva: te servirá para cancelar o cambiar la cita "
            "por teléfono, web o WhatsApp.\n"
        )
    _pago_nota = ""
    # Nota del servicio: solo en la confirmación, que es cuando la cita ya es suya.
    _nota_servicio = (
        service_booking_note(booking_row["cliente_id"], booking_row)
        if status_key == "confirmed" else ""
    )
    if _nota_servicio:
        text_body += f"\n{_nota_servicio}\n"
    if status_key == "pending_payment":
        _pago_url = build_booking_payment_url(booking_row["manage_token"])
        # Senal, pago completo o retencion: el mismo helper que usa WhatsApp explica
        # cual de los tres es, para no llamar "senal" a un cobro entero.
        _pago_nota = payment_prompt_note(
            booking_row["cliente_id"], booking_row, _booking_payment_row(booking_row["id"])
        )
        if _pago_nota:
            text_body += f"\n{_pago_nota}\n"
        if _pago_url:
            text_body += f"\nPaga aquí para confirmar la cita: {_pago_url}\n"
    if contact_text:
        text_body += f"\nContacto:\n{contact_text}\n"

    html_body = (
        f'<div style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;'
        f'padding:24px;background:#f5f8fb;color:#102033;">'
        f'<div style="background:#ffffff;border:1px solid #d8e2ee;border-radius:18px;'
        f'padding:24px 24px 12px;">'
        f'<p style="margin:0 0 16px;line-height:1.6;">{escape(intro)}</p>'
        + (
            f'<div style="margin:0 0 16px;padding:12px 16px;border-radius:12px;'
            f'background:#eef6fb;border:1px solid #cfe3f0;">'
            f'<span style="font-size:12px;color:#4a6173;text-transform:uppercase;'
            f'letter-spacing:.04em;">Número de reserva</span><br>'
            f'<strong style="font-size:22px;letter-spacing:.08em;color:#0b6b8a;">'
            f'{escape(booking_code)}</strong>'
            f'<div style="font-size:12px;color:#4a6173;margin-top:4px;">'
            f'Guárdalo para cancelar o cambiar tu cita por teléfono, web o WhatsApp.</div>'
            f"</div>"
            if booking_code
            else ""
        )
        + f'<ul style="margin:0 0 12px;padding-left:20px;line-height:1.8;">'
        f"<li><strong>Empresa:</strong> {escape(company_name)}</li>"
        f"<li><strong>Servicio:</strong> {escape(service_name + service_suffix)}</li>"
        f"<li><strong>Fecha y hora:</strong> {escape(when_text)}</li>"
        f"<li><strong>Zona horaria:</strong> {escape(booking_row['timezone'])}</li>"
        f"</ul>"
        + (
            f'<div style="margin:0 0 14px;padding:12px 16px;border-radius:12px;'
            f'background:#fff8e6;border:1px solid #f0dca8;line-height:1.5;">'
            f"<strong>Pago:</strong> {escape(_cobro_texto)}</div>"
            if _cobro_texto
            else ""
        )
        + f"{manage_html}"
    )
    if _nota_servicio:
        html_body += (
            f'<div style="margin:0 0 16px;padding:12px 16px;border-radius:12px;'
            f'background:#f2f7f4;border:1px solid #cfe3d8;line-height:1.6;white-space:pre-line;">'
            f'{escape(_nota_servicio)}</div>'
        )
    if status_key == "pending_payment" and _pago_nota:
        html_body += f'<p style="line-height:1.6;">{escape(_pago_nota)}</p>'
    if status_key == "pending_payment" and _pago_url:
        html_body += (
            f'<p style="margin:18px 0;"><a href="{escape(_pago_url)}" '
            f'style="display:inline-block;background:#0b6b8a;color:#ffffff;padding:12px 22px;'
            f'border-radius:10px;text-decoration:none;font-weight:bold;">Pagar y confirmar la cita</a></p>'
        )
    if contact_html:
        html_body += (
            f'<p style="margin-top:18px;">Si necesitas ayuda, puedes escribirnos por:</p>'
            f'<ul style="line-height:1.8;">{contact_html}</ul>'
        )
    html_body += "</div></div>"

    return text_body.strip(), html_body


def _booking_message_preview(
    cliente_id: str,
    payload: PortalMessagePreviewPayload,
    request: Optional[Request] = None,
) -> PortalMessagePreviewResponse:
    kind = _normalize_message_kind(payload.kind or payload.template_key)
    schedule = payload.schedule or agenda._schedule_preview_payload_from_config(cliente_id)
    legacy_content = textnorm._sanitize_text(payload.content, allow_multiline=True)
    if legacy_content:
        templates = textnorm._normalize_message_templates(schedule.message_templates or {})
        templates[kind] = legacy_content[:500]
        schedule.message_templates = templates
    booking_row, context, manage_url = _booking_preview_context(cliente_id, schedule, request)
    subject = _booking_email_subject(kind, context["company_name"], booking_row)
    preview_confirm_url = ""
    if kind in ("confirmed", "reminder_24h") and _follow_up_config(cliente_id)["email_confirm_button"]:
        preview_confirm_url = _booking_row_confirm_url(booking_row, request) or "https://app.vantelia.es/booking/confirm/preview"
    text_body, html_body = _booking_email_bodies(
        booking_row,
        context["company_name"],
        kind,
        manage_url,
        context["contact_email"],
        context["contact_phone"],
        context["message_templates"],
        confirm_url=preview_confirm_url,
    )
    return PortalMessagePreviewResponse(
        kind=kind,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        target_email=str(payload.target_email or ""),
        enabled=bool(context["message_template_enabled"].get(kind, True)),
    )


def _send_booking_email(
    booking_row: sqlite3.Row,
    status_key: str,
    request: Optional[Request] = None,
) -> str:
    config = clients._get_client_config(booking_row["cliente_id"])
    company_name = config["nombre"]
    manage_url = _booking_row_manage_url(booking_row, request)
    contact_email = config.get("contacto", {}).get("email", "")
    contact_phone = config.get("contacto", {}).get("telefono", "")
    confirm_url = ""
    if status_key in ("confirmed", "reminder_24h") and _follow_up_config(booking_row["cliente_id"])["email_confirm_button"]:
        confirm_url = _booking_row_confirm_url(booking_row, request)
    subject = _booking_email_subject(status_key, company_name, booking_row)
    text_body, html_body = _booking_email_bodies(
        booking_row,
        company_name,
        status_key,
        manage_url,
        contact_email,
        contact_phone,
        config.get("booking", {}).get("message_templates", {}),
        confirm_url=confirm_url,
    )
    return emailing._send_client_email(
        booking_row["cliente_id"],
        booking_row["email"],
        subject,
        text_body,
        html_body,
    )


def _booking_email_enabled(config: Dict[str, Any], kind: str) -> bool:
    enabled_map = textnorm._normalize_message_template_enabled(
        config.get("booking", {}).get("message_template_enabled", {}),
        config.get("booking", {}).get("message_templates", {}),
    )
    return enabled_map.get(kind, True)


def _booking_customer_phone_for_channel(booking_row: sqlite3.Row, channel: str) -> str:
    raw_value = textnorm._sanitize_text(booking_row["telefono"] if booking_row["telefono"] else "")
    if not raw_value:
        return ""
    if raw_value.startswith("+"):
        e164 = "+" + re.sub(r"\D", "", raw_value)
    else:
        digits = re.sub(r"\D", "", raw_value)
        if digits.startswith("00"):
            e164 = "+" + digits[2:]
        elif len(digits) == 9 and digits[0] in {"6", "7", "8", "9"}:
            e164 = "+34" + digits
        elif digits.startswith("34") and len(digits) >= 11:
            e164 = "+" + digits
        elif len(digits) >= 10:
            e164 = "+" + digits
        else:
            return ""
    if channel == "whatsapp":
        return e164.lstrip("+")
    return e164


def _booking_message_text_for_channel(
    booking_row: sqlite3.Row,
    kind: str,
    request: Optional[Request] = None,
) -> str:
    config = clients._get_client_config(booking_row["cliente_id"])
    text_body, _ = _booking_email_bodies(
        booking_row,
        config["nombre"],
        kind,
        _booking_row_manage_url(booking_row, request),
        config.get("contacto", {}).get("email", ""),
        config.get("contacto", {}).get("telefono", ""),
        config.get("booking", {}).get("message_templates", {}),
    )
    return text_body


def _whatsapp_deliverable_for_booking(booking_row: sqlite3.Row) -> Tuple[bool, str]:
    """¿Se le puede escribir por WhatsApp a ESTE cliente?

    La disponibilidad general del tenant no basta. Un negocio puede estar
    atendiendo por el numero de demo compartido sin tener WhatsApp propio
    configurado: ahi la conversacion existe de verdad y hay que poder contestarla.
    Al reves tambien importa: si el negocio APAGO su WhatsApp, se respeta.

    Lo que nunca se salta: el plan (WhatsApp es de pago) y el token de envio.
    """
    cliente_id = booking_row["cliente_id"]
    if not clients._plan_feature(cliente_id, "whatsapp_enabled"):
        return False, "Necesitas un plan con WhatsApp."
    if not messaging._whatsapp_access_token_for_client(cliente_id):
        return False, "Falta el token de envio de WhatsApp en servidor."

    whatsapp_cfg = clients._get_client_config(cliente_id).get("whatsapp", {}) or {}
    propio = str(whatsapp_cfg.get("phone_number_id", "") or "").strip()
    if whatsapp_cfg.get("enabled") and propio:
        return True, "Disponible."

    entrada = inbox.inbound_number_for_phone(cliente_id, booking_row["telefono"] or "")
    if entrada and wa_demo.is_hub(entrada):
        return True, "Disponible (número de demo compartido)."
    return False, "Activa WhatsApp en el portal."


# Avisos de cita que se escriben para WhatsApp, no heredados del correo. El email
# lleva zona horaria, contacto y el enlace en crudo: en un movil todo eso sobra.
_WA_TITULOS = {
    "confirmed": "✅ *Cita confirmada*",
    "rescheduled": "🔄 *Cita cambiada*",
    "cancelled": "❌ *Cita cancelada*",
    "reminder_24h": "⏰ *Recordatorio de tu cita*",
    "reminder_2h": "⏰ *Tu cita es dentro de poco*",
}

# Cierre de cada aviso. El recordatorio pide respuesta porque lleva debajo los
# botones "Confirmo" / "Cancelar cita".
_WA_CIERRES = {
    "reminder_24h": "¿Nos confirmas que vienes?",
    "reminder_2h": "Te esperamos. Si no puedes venir, avísanos.",
}

WA_NOTICE_KINDS = ("confirmed", "rescheduled", "cancelled", "reminder_24h", "reminder_2h")


def _whatsapp_notice_text(booking_row: sqlite3.Row, kind: str = "confirmed") -> str:
    """Aviso corto de cita para WhatsApp.

    Cubre `WA_NOTICE_KINDS`. El correo lleva zona horaria, datos de contacto y el
    enlace en crudo; en un movil todo eso sobra y parte el mensaje en dos.
    """
    config = clients._get_client_config(booking_row["cliente_id"])
    cuando = booking_row["booking_date"] or ""
    try:
        cuando = textnorm._format_date_es(textnorm._parse_date(cuando).date())
    except Exception:  # noqa: BLE001 - si la fecha viene rara, se deja como esta
        pass
    hora = booking_row["booking_time"] or ""
    servicio = booking_row["servicio"] or "Tu cita"
    quien = (booking_row["employee_name"] if "employee_name" in booking_row.keys() else "") or ""
    codigo = (booking_row["booking_code"] if "booking_code" in booking_row.keys() else "") or ""

    if kind == "cancelled":
        # Sin número de reserva ni enlace: esa cita ya no existe y ofrecerselos
        # solo despista. Lo util es decirle como conseguir otra.
        telefono = str((config.get("contacto") or {}).get("telefono") or "").strip()
        lineas = [_WA_TITULOS["cancelled"], ""]
        lineas.append("Era el %s a las %s (%s)." % (cuando, hora, servicio))
        lineas.append("")
        lineas.append(
            "Si quieres buscar otro hueco, escríbeme por aquí y te lo miro"
            + (" o llámanos al %s." % telefono if telefono else ".")
        )
        return chr(10).join(lineas)

    lineas = [_WA_TITULOS.get(kind, _WA_TITULOS["confirmed"]), ""]
    lineas.append("🛍️ %s" % textnorm.nombre_de_servicio_publico(servicio))
    if quien:
        lineas.append("👨‍⚕️ %s" % quien)
    lineas.append("📅 %s · 🕐 %s" % (cuando, hora))
    if codigo:
        lineas.append("🔖 Número de reserva: *%s*" % codigo)
    aviso = textnorm._sanitize_text(
        str((config.get("booking") or {}).get("success_message") or ""), allow_multiline=True
    ).strip()
    if aviso and kind == "confirmed":
        lineas += ["", aviso]
    # El aviso del servicio ("ven con el pelo lavado") se repite en el recordatorio
    # de 24 h: es justo cuando al cliente le da tiempo a hacerle caso.
    nota = service_booking_note(booking_row["cliente_id"], booking_row)
    if nota and kind in ("confirmed", "reminder_24h"):
        lineas += ["", nota]
    cierre = _WA_CIERRES.get(kind, "")
    if cierre:
        lineas += ["", cierre]
    return chr(10).join(lineas)


async def _send_booking_whatsapp_reminder(
    booking_row: sqlite3.Row,
    kind: str,
    request: Optional[Request] = None,
) -> bool:
    config = clients._get_client_config(booking_row["cliente_id"])
    whatsapp_cfg = config.get("whatsapp", {}) or {}
    to_number = _booking_customer_phone_for_channel(booking_row, "whatsapp")
    # Se responde por el numero al que ESCRIBIO el cliente. Un negocio puede tener
    # varios (uno por centro, el numero de demo compartido) y salir por otro
    # significa escribirle desde un numero que no reconoce, o no poder escribirle.
    phone_number_id = inbox.inbound_number_for_phone(booking_row["cliente_id"], to_number) or str(
        whatsapp_cfg.get("phone_number_id", "") or ""
    ).strip()
    if not (phone_number_id and to_number):
        return False
    if kind in ("confirmed", "rescheduled"):
        # Texto corto + boton "Gestionar cita" (el enlace son ~80 caracteres que
        # nadie lee y que en el movil parten el mensaje en dos).
        enviado = await messaging._send_whatsapp_cta_url(
            cliente_id=booking_row["cliente_id"], phone_number_id=phone_number_id,
            to_number=to_number, body=_whatsapp_notice_text(booking_row, kind),
            button_label="Gestionar cita",
            url=_booking_row_manage_url(booking_row, request),
        )
        if enviado:
            return True
    if kind == "cancelled":
        # Sin boton: la cita ya no existe, no hay nada que gestionar.
        enviado = await messaging._send_whatsapp_text(
            cliente_id=booking_row["cliente_id"], phone_number_id=phone_number_id,
            to_number=to_number, text=_whatsapp_notice_text(booking_row, kind),
        )
        if enviado:
            return True
    # Los recordatorios tambien van en corto; lo que cambia es que llevan botones.
    message_text = (
        _whatsapp_notice_text(booking_row, kind)
        if kind in WA_NOTICE_KINDS
        else _booking_message_text_for_channel(booking_row, kind, request)
    )
    # Recordatorios: botones interactivos de confirmacion de asistencia.
    # La respuesta la procesa el webhook (bkok_/bkcancel_) y queda en booking_audit.
    if kind in ("reminder_24h", "reminder_2h") and booking_row["status"] in ("confirmed", "pending_review"):
        sent = await messaging._send_whatsapp_buttons(
            cliente_id=booking_row["cliente_id"],
            phone_number_id=phone_number_id,
            to_number=to_number,
            body=message_text,
            buttons=[
                (f"bkok_{booking_row['id']}", "✅ Confirmo"),
                (f"bkcancel_{booking_row['id']}", "❌ Cancelar cita"),
            ],
        )
        if sent:
            return True
        # Fallback a texto plano si la API rechaza el mensaje interactivo.
    return await messaging._send_whatsapp_text(
        cliente_id=booking_row["cliente_id"],
        phone_number_id=phone_number_id,
        to_number=to_number,
        text=message_text,
    )


async def _send_booking_sms_reminder(
    booking_row: sqlite3.Row,
    kind: str,
    request: Optional[Request] = None,
) -> bool:
    to_number = _booking_customer_phone_for_channel(booking_row, "sms")
    if not to_number:
        return False
    return await messaging._send_client_sms(
        booking_row["cliente_id"],
        to_number,
        _booking_message_text_for_channel(booking_row, kind, request),
    )


def _mark_booking_email_result(
    booking_id: str,
    *,
    status: str,
    sent_column: str = "",
    error: str = "",
) -> None:
    updates: Dict[str, Any] = {
        "customer_email_status": status,
        "customer_email_last_error": error,
    }
    if sent_column:
        updates[sent_column] = timeutils._utc_now_iso()
    _update_booking_record(booking_id, **updates)


def _generate_manage_token() -> str:
    return f"mg_{secrets.token_urlsafe(24)}"


def _booking_blank_tracking_fields() -> Dict[str, str]:
    """Campos de seguimiento vacios comunes a toda cita recien creada."""
    return {
        "rescheduled_at": "",
        "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "",
        "reminder_24h_sent_at": "",
        "reminder_2h_sent_at": "",
        "customer_email_status": "",
        "customer_email_last_error": "",
    }


def _generate_booking_code() -> str:
    # Solo digitos: mucho mas facil de dictar y oir por teléfono ("R, uno, dos, tres...").
    # 6 digitos mantienen un espacio amplio (1M) por cliente. Los codigos antiguos
    # alfanumericos siguen siendo validos (ver BOOKING_CODE_RE / _get_booking_row_by_code).
    suffix = "".join(secrets.choice("0123456789") for _ in range(6))
    return f"R-{suffix}"


def _unique_booking_code(connection: sqlite3.Connection, cliente_id: str) -> str:
    """Codigo de reserva unico por cliente. Reintenta ante colision (rarisima)."""
    for _ in range(12):
        code = _generate_booking_code()
        existing = connection.execute(
            "SELECT 1 FROM bookings WHERE cliente_id = ? AND booking_code = ? LIMIT 1",
            (cliente_id, code),
        ).fetchone()
        if not existing:
            return code
    return f"R-{secrets.token_hex(4).upper()}"


def _booking_contact_matches(row: sqlite3.Row, *, telefono: str = "", email: str = "") -> bool:
    """True si el teléfono o el email aportado coincide con el de la reserva.

    Verificacion para que la IA solo cancele/reprograme citas del propio titular.
    """
    tel_in = crm._normalize_phone_for_match(telefono)
    if tel_in and tel_in == crm._normalize_phone_for_match(row["telefono"] or ""):
        return True
    email_in = textnorm._sanitize_text(email).strip().lower()
    if email_in and email_in == (row["email"] or "").strip().lower():
        return True
    return False


def _get_booking_row_by_code(cliente_id: str, code: str) -> Optional[sqlite3.Row]:
    raw = textnorm._sanitize_text(code)
    normalized = raw.strip().upper().replace(" ", "")
    candidates = set()
    if normalized:
        candidates.add(normalized)
        # Tolera que dicten el codigo sin el prefijo "R-".
        if not normalized.startswith("R-"):
            candidates.add(f"R-{normalized.lstrip('R-')}")
    # Tolera formas dictadas raras (digitos deletreados, guiones entre cifras, 'erre',
    # solo el numero...): reutiliza el extractor robusto para reconstruir el codigo.
    extracted = _extract_booking_code_from_text(raw)
    if extracted:
        candidates.add(extracted)
    if not candidates:
        return None
    with db._get_db_connection() as connection:
        for candidate in candidates:
            row = connection.execute(
                "SELECT * FROM bookings WHERE cliente_id = ? AND booking_code = ? LIMIT 1",
                (cliente_id, candidate),
            ).fetchone()
            if row:
                return row
    return None


# Acepta el formato nuevo (R + 6 digitos) y el antiguo (R + 4 alfanumericos) para no
# romper enlaces/citas existentes.
BOOKING_CODE_RE = re.compile(r"\bR[\s-]?([0-9]{6}|[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4})\b", re.IGNORECASE)

# Numeros dictados por voz digito a digito ("dos dos ocho uno nueve seis" -> "228196").
_SPOKEN_DIGIT_WORDS = {
    "cero": "0", "uno": "1", "una": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9",
}


def _booking_code_normalize_spoken(text: str) -> str:
    """Pasa las formas habladas del número de reserva a algo que el regex entienda:
    'erre' -> 'r', 'guion' -> ' ', y cada palabra-digito ('dos','ocho'...) -> su cifra.
    Despues une las cifras pegadas separadas por espacios ('2 2 8 1 9 6' -> '228196')."""
    t = textnorm._sanitize_text(text or "").lower()
    t = re.sub(r"\berre\b", "r", t)
    t = re.sub(r"\bgui[oó]n\b", " ", t)
    tokens = re.split(r"(\W+)", t)
    t = "".join(_SPOKEN_DIGIT_WORDS.get(tok, tok) for tok in tokens)
    # une cifras sueltas separadas por espacios/puntos para reconstruir el numero completo.
    t = re.sub(r"(?<=\d)[\s.\-]+(?=\d)", "", t)
    return t


def _extract_booking_code_from_text(text: str) -> str:
    raw = str(text or "")
    # 1) Forma escrita con R explicita (R-228196 / R228196 / R 228196 / antiguo R-AB12).
    match = BOOKING_CODE_RE.search(raw.upper())
    if match:
        return f"R-{match.group(1).upper()}"
    # 2) Formas habladas: 'erre guion ...', digitos deletreados, etc.
    norm = _booking_code_normalize_spoken(raw)
    match = BOOKING_CODE_RE.search(norm.upper())
    if match:
        return f"R-{match.group(1).upper()}"
    # 3) Solo el numero (6 digitos sueltos): el cliente dice '228196' o 'mi codigo es 228196'.
    #    Un telefono (9 cifras) NO casa porque exigimos exactamente 6 entre limites de palabra.
    match = re.search(r"\b(\d{6})\b", norm)
    if match:
        return f"R-{match.group(1)}"
    return ""


async def _lookup_and_verify_booking_by_code(
    cliente_id: str,
    codigo_reserva: str,
    *,
    trusted_phone: str = "",
    telefono: str = "",
    email: str = "",
) -> Tuple[Optional[sqlite3.Row], Optional[Dict[str, Any]]]:
    codigo = textnorm._sanitize_text(codigo_reserva)
    if not codigo:
        return None, {"ok": False, "error": "Necesito el número de reserva (formato R-XXXX)."}
    row = _get_booking_row_by_code(cliente_id, codigo)
    if not row:
        return None, {"ok": False, "error": "No encuentro ninguna cita con ese número de reserva. Revísalo y vuelve a intentarlo."}
    verified = (
        _booking_contact_matches(row, telefono=trusted_phone)
        or _booking_contact_matches(row, telefono=telefono, email=email)
    )
    if not verified:
        return None, {
            "ok": False,
            "needs_verification": True,
            "error": (
                "Por seguridad necesito verificar la reserva. Indica el teléfono o el email "
                "con el que hiciste la cita."
            ),
        }
    return row, None


async def _cancel_booking_by_code(
    cliente_id: str,
    codigo_reserva: str,
    *,
    trusted_phone: str = "",
    telefono: str = "",
    email: str = "",
    motivo: str = "",
    source: str,
    request: Optional[Request] = None,
) -> Dict[str, Any]:
    row, error = await _lookup_and_verify_booking_by_code(
        cliente_id, codigo_reserva, trusted_phone=trusted_phone, telefono=telefono, email=email
    )
    if error:
        return error
    if row["status"] == "cancelled":
        return {"ok": True, "ya_cancelada": True, "mensaje": "Esa cita ya estaba cancelada."}
    if row["status"] == "completed":
        return {"ok": False, "error": "Esa cita ya se ha realizado y no se puede cancelar."}
    if row["status"] == "no_show":
        return {"ok": False, "error": "Esa cita esta marcada como no asistida y no se puede cancelar."}
    try:
        refreshed = await _cancel_booking_core(
            row,
            source=source,
            reason=textnorm._sanitize_text(motivo, allow_multiline=True),
            request=request,
            audit_extra={"channel": source, "trusted_phone": trusted_phone},
        )
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[%s] cancelacion por codigo fallo (%s): %s", source, cliente_id, exc)
        return {"ok": False, "error": "No se pudo cancelar la cita."}
    return {
        "ok": True,
        "codigo_reserva": refreshed["booking_code"] or "",
        "fecha": refreshed["booking_date"],
        "hora": refreshed["booking_time"],
        "mensaje": "Cita cancelada correctamente.",
    }


async def _reschedule_booking_by_code(
    cliente_id: str,
    codigo_reserva: str,
    fecha: str,
    hora: str,
    *,
    trusted_phone: str = "",
    telefono: str = "",
    email: str = "",
    source: str,
    request: Optional[Request] = None,
) -> Dict[str, Any]:
    row, error = await _lookup_and_verify_booking_by_code(
        cliente_id, codigo_reserva, trusted_phone=trusted_phone, telefono=telefono, email=email
    )
    if error:
        return error
    payload = _booking_update_payload_from_reschedule(
        row, BookingReschedulePayload(fecha=textnorm._sanitize_text(fecha), hora=textnorm._sanitize_text(hora))
    )
    try:
        response = await _update_booking_details(
            row,
            payload,
            request,
            source=source,
            audit_payload={"channel": source, "trusted_phone": trusted_phone},
        )
    except HTTPException as exc:
        return {
            "ok": False,
            "error": str(exc.detail),
            # Contexto para que el texto de fallo ofrezca alternativas REALES del
            # profesional de la cita (descontando sus citas y bloqueos).
            "booking_id": row["id"],
            "employee_id": row["employee_id"] or "",
        }
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[%s] reprogramacion por codigo fallo (%s): %s", source, cliente_id, exc)
        return {"ok": False, "error": "No se pudo reprogramar la cita."}
    return {
        "ok": True,
        "codigo_reserva": row["booking_code"] or "",
        "fecha": textnorm._sanitize_text(fecha),
        "hora": textnorm._sanitize_text(hora),
        "mensaje": response.mensaje or "Cita reprogramada correctamente.",
    }


# El cliente se echa atras de la gestion que habia pedido. Va SIN tildes: se
# compara contra el mensaje ya normalizado (ver tests/test_patrones_sin_tilde.py).
RETRACT_MANAGEMENT_RE = re.compile(
    r"\b(dejalo|dejarlo|olvidalo|olvidate|olvidemos|no importa|da igual|"
    r"mejor no|ya no|nada mas|nada gracias|no hace falta|no quiero|anulado no|"
    r"me he equivocado|era broma|perdon me confundi)\b"
)


def _message_retracts_management(message: str) -> bool:
    """¿Se esta echando atras? ("no, dejalo", "olvidalo", "da igual")

    Se pide ademas que el mensaje sea corto: en una frase larga estas palabras
    suelen ser parte de otra cosa ("me da igual el profesional, pero quiero
    cancelar la del martes").
    """
    # Sin puntuacion: "nada, gracias" tiene que casar igual que "nada gracias".
    text = re.sub(r"[^\w\s]+", " ", textnorm._strip_accents(str(message or "").lower()))
    text = " ".join(text.split())
    if not text or len(text.split()) > 6:
        return False
    return bool(RETRACT_MANAGEMENT_RE.search(text))


# ─── Pedir algo vs preguntar por ello ──────────────────────────────────────
# Los detectores casaban la palabra suelta, asi que "no quiero cancelar nada,
# solo preguntar" y "¿puedo cancelar si me surge algo?" recibian "necesito el
# número de reserva" en vez de una respuesta a lo que preguntaban. Estas dos
# reglas valen para cancelar y para cambiar, y van SIN tildes (se comparan
# contra el mensaje ya normalizado; lo vigila test_patrones_sin_tilde).

# "no quiero cancelar", "no voy a cambiarla": la negacion tiene que ir pegada al
# verbo. Con mas de dos palabras por medio suele ser otra frase ("no puedo ir el
# martes, quiero cancelar"), que SI es una peticion real.
MANAGE_NEGATION_RE = re.compile(
    r"\bno\s+(?:\w+\s+){0,2}(?:cancel|anul|borrar|cambi|mover|muev|reprogram|modific)"
)

# Preguntas SOBRE la gestion, no peticiones: "¿que pasa si cancelo?",
# "¿hasta cuando puedo cambiarla?", "¿cobrais por cancelar?".
MANAGE_QUESTION_RE = re.compile(
    r"\b(?:que\s+pasa\s+si|en\s+caso\s+de|hasta\s+cuando|con\s+cuanta\s+antelacion|"
    r"cuanto\s+antes|se\s+puede|hay\s+que\s+pagar|cobrais|cobran|penalizacion|"
    r"puedo\s+\w+(?:la|lo)?\s+si|tengo\s+que\s+\w+)\b"
)
# ...y las hipoteticas: "si me surge", "si al final", "si no puedo".
MANAGE_HYPOTHETICAL_RE = re.compile(r"\bsi\s+(?:me\s+|no\s+|al\s+final|acaso|luego|un\s+dia|tengo)")


def _message_is_question_about_management(text: str) -> bool:
    """¿Pregunta POR la gestion en vez de pedirla? (texto ya normalizado)"""
    return bool(MANAGE_QUESTION_RE.search(text) or MANAGE_HYPOTHETICAL_RE.search(text))


def _message_requests_cancel_booking(message: str) -> bool:
    """¿Está PIDIENDO cancelar? No basta con que aparezca la palabra."""
    text = textnorm._strip_accents(str(message or "").lower())
    if not any(word in text for word in ("cancelar", "anular", "cancela", "borrar cita")):
        return False

    # La negacion se mira ANTES que nada: "no quiero cancelar nada" contiene
    # literalmente "quiero cancelar".
    if MANAGE_NEGATION_RE.search(text):
        return False

    peticion_explicita = any(
        frase in text
        for frase in ("quiero cancelar", "necesito cancelar", "cancelar mi cita",
                      "anular mi cita", "borrar cita", "cancela mi cita")
    )
    if peticion_explicita:
        return True

    if any(frase in text for frase in ("condiciones de cancelacion", "politica de cancelacion",
                                       "politicas de cancelacion")):
        return False
    return not _message_is_question_about_management(text)


RESCHEDULE_INTENT_RE = re.compile(
    # verbo de cambio ... (cerca) ... objeto de cita/fecha/hora. Cubre variantes con
    # articulos ("cambiar LA fecha de UNA cita") que una lista de literales se pierde.
    r"\b(reprogramar|reprograma|cambiar|cambia|mover|mueve|modificar|modifica)\b"
    r".{0,40}?\b(cita|reserva|fecha|hora|dia)\b"
)


def _message_requests_reschedule_booking(message: str) -> bool:
    """¿Está PIDIENDO cambiar la cita? Mismo criterio que cancelar."""
    text = textnorm._strip_accents(str(message or "").lower())
    if MANAGE_NEGATION_RE.search(text):
        return False
    if any(word in text for word in ("reprogramala", "cambiarla", "cambiala", "muevela")):
        return True
    if not RESCHEDULE_INTENT_RE.search(text):
        return False
    if any(frase in text for frase in ("quiero cambiar", "necesito cambiar", "quiero mover",
                                       "necesito mover", "quiero reprogramar", "me gustaria cambiar")):
        return True
    return not _message_is_question_about_management(text)


# Preguntas SOBRE el pago, no peticiones de pagar. Mandar un enlace de cobro a
# quien pregunta "¿se puede pagar con tarjeta?" o dice "no quiero pagar ahora" es
# de las cosas que peor sientan.
PAYMENT_QUESTION_RE = re.compile(
    r"\b(?:se\s+puede|se\s+acepta|aceptais|admitis|hay\s+que\s+pagar|hace\s+falta\s+pagar|"
    r"cuanto\s+(?:hay\s+que\s+|se\s+)?paga|que\s+metodos?|con\s+que\s+se\s+paga|"
    r"puedo\s+pagar\s+(?:con|en|el\s+dia)|es\s+obligatorio|por\s+adelantado)\b"
)


def _message_requests_payment(message: str) -> bool:
    """¿Está PIDIENDO pagar? Preguntar por el pago no es lo mismo.

    Las frases van SIN tildes a proposito: se comparan contra el mensaje ya
    normalizado. Con tilde no casan nunca. Lo vigila test_patrones_sin_tilde.
    """
    text = textnorm._strip_accents(str(message or "").lower())
    if not any(
        word in text
        for word in (
            "pagar", "enlace de pago", "link de pago", "quiero pagar", "como pago",
            "abonar", "dejar una senal", "pagar la senal", "pagar el deposito", "metodo de pago",
        )
    ):
        return False

    if re.search(r"\bno\s+(?:\w+\s+){0,2}(?:pagar|abonar|pago)", text):
        return False
    # Solo las inequivocas: "pagar la senal" tambien aparece en "¿es obligatorio
    # pagar la senal?", que es una pregunta.
    if any(frase in text for frase in ("quiero pagar", "enlace de pago", "link de pago",
                                       "quiero abonar", "mandame el pago")):
        return True
    return not PAYMENT_QUESTION_RE.search(text)


CHAT_MANAGE_STATE_TTL_SECONDS = 15 * 60


def _chat_manage_state_get(session_id: str) -> Dict[str, Any]:
    """Memoria conversacional de gestion de citas: lo ya dicho en la sesion (intencion,
    codigo, contacto) para no volver a pedirlo. Efimera con TTL corto."""
    if not session_id:
        return {}
    with appstate.state_lock:
        state = appstate.chat_manage_state.get(session_id)
        if not state:
            return {}
        if time.time() - float(state.get("ts") or 0) > CHAT_MANAGE_STATE_TTL_SECONDS:
            appstate.chat_manage_state.pop(session_id, None)
            return {}
        return dict(state)


def _chat_manage_state_update(session_id: str, **values: Any) -> None:
    if not session_id:
        return
    with appstate.state_lock:
        ahora = time.time()
        # Purga oportunista: `_chat_manage_state_get` solo caduca la clave que se
        # consulta, asi que las sesiones que no vuelven se quedaban para siempre en
        # un proceso que vive semanas.
        if session_id not in appstate.chat_manage_state:
            for clave in [
                k for k, v in appstate.chat_manage_state.items()
                if ahora - float(v.get("ts") or 0) > CHAT_MANAGE_STATE_TTL_SECONDS
            ]:
                appstate.chat_manage_state.pop(clave, None)
        state = appstate.chat_manage_state.setdefault(session_id, {})
        state.update({k: v for k, v in values.items() if v})
        state["ts"] = ahora


def _chat_manage_state_clear(session_id: str) -> None:
    if not session_id:
        return
    with appstate.state_lock:
        appstate.chat_manage_state.pop(session_id, None)


async def _process_booking_management_message(
    *,
    cliente_id: str,
    message: str,
    request: Optional[Request],
    source: str,
    trusted_phone: str = "",
    session_id: str = "",
) -> Optional[Tuple[str, str]]:
    wants_cancel = _message_requests_cancel_booking(message)
    wants_reschedule = _message_requests_reschedule_booking(message)
    code_in_msg = _extract_booking_code_from_text(message)
    email_in_msg = textnorm._extract_email_from_text(message)
    phone_in_msg = textnorm._extract_phone_from_text(message)

    # El cliente se echa atras: se olvida la gestion pendiente. Sin esto, un
    # "quiero cancelar" seguido de "no, dejalo" seguia vivo 15 minutos, y el
    # siguiente mensaje que trajera un email o un codigo se procesaba como
    # cancelacion — aunque el cliente estuviera pidiendo justo lo contrario.
    if session_id and not (wants_cancel or wants_reschedule) and _message_retracts_management(message):
        _chat_manage_state_clear(session_id)
        return None

    remembered = _chat_manage_state_get(session_id)
    remembered_intent = str(remembered.get("intent") or "")

    # Una intencion NUEVA y contraria manda sobre la recordada: si pide reservar,
    # no puede seguir cancelando.
    if remembered_intent and not (wants_cancel or wants_reschedule) and _message_requests_booking_form(message):
        _chat_manage_state_clear(session_id)
        return None

    engaged_now = bool(wants_cancel or wants_reschedule or code_in_msg)
    # Con una gestion pendiente en la sesion, un mensaje que solo aporta el dato que
    # faltaba (codigo, telefono/email, o fecha/hora para el cambio) continua el flujo
    # sin exigir repetir la frase "quiero cancelar/cambiar".
    contributes_data = bool(code_in_msg or email_in_msg or phone_in_msg)
    if not contributes_data and remembered_intent == "reschedule":
        config_tmp = clients._get_client_config(cliente_id)
        tz_tmp = config_tmp.get("booking", {}).get("timezone") or settings.DEFAULT_TIMEZONE
        contributes_data = bool(
            textnorm._extract_date_from_text(message, tz_tmp) or textnorm._extract_time_from_text(message)
        )
    if not engaged_now and not (remembered_intent and contributes_data):
        return None

    config = clients._get_client_config(cliente_id)
    if not (bool(config.get("booking", {}).get("enabled")) and clients._client_booking_plan_enabled(cliente_id)):
        return (
            "booking_manage",
            "La gestión de citas online no está activa para este negocio. Contacta directamente con el equipo.",
        )

    # Mezcla: lo del mensaje manda; lo recordado completa lo que falte.
    code = code_in_msg or str(remembered.get("code") or "")
    email = email_in_msg or str(remembered.get("email") or "")
    phone = phone_in_msg or str(remembered.get("telefono") or "")
    if wants_cancel and wants_reschedule:
        # "Cancelar o cambiar": ambiguo. Guarda lo aportado y pregunta cual de las dos.
        _chat_manage_state_update(session_id, code=code_in_msg, email=email_in_msg, telefono=phone_in_msg)
        return (
            "booking_manage",
            "Puedo cancelarla o cambiarla de fecha. Dime cual de las dos quieres"
            + ("" if code else " y el número de reserva (R-XXXXXX)")
            + ".",
        )
    if not (wants_cancel or wants_reschedule):
        if remembered_intent == "cancel":
            wants_cancel = True
        elif remembered_intent == "reschedule":
            wants_reschedule = True
        elif remembered.get("code"):
            # Habia una gestion pendiente sin intencion clara ("cancelar o cambiar"):
            # un "cambiar" / "mover" suelto ya la resuelve.
            bare = textnorm._strip_accents(str(message or "").lower())
            if re.search(r"\b(cambiar|cambia|mover|mueve|reprogramar|reprograma)\b", bare):
                wants_reschedule = True

    # Persistir lo aprendido en este mensaje para los siguientes pasos.
    _chat_manage_state_update(
        session_id,
        intent=("cancel" if wants_cancel else ("reschedule" if wants_reschedule else "")),
        code=code_in_msg,
        email=email_in_msg,
        telefono=phone_in_msg,
    )

    if not (wants_cancel or wants_reschedule):
        return (
            "booking_manage",
            "Tengo el número de reserva. Dime si quieres cancelar o cambiar la cita.",
        )
    if not code:
        action = "cancelar" if wants_cancel else "cambiar"
        return (
            "booking_manage",
            f"Claro. Para {action} la cita necesito el número de reserva, con formato R-XXXX.",
        )
    if not trusted_phone and not (email or phone):
        return (
            "booking_manage",
            "Por seguridad, envíame también el teléfono o el email con el que hiciste la reserva.",
        )

    if wants_cancel:
        result = await _cancel_booking_by_code(
            cliente_id,
            code,
            trusted_phone=trusted_phone,
            telefono=phone,
            email=email,
            motivo="Solicitado por chat.",
            source=source,
            request=request,
        )
        if result.get("ok"):
            _chat_manage_state_clear(session_id)
            suffix = " Ya estaba cancelada." if result.get("ya_cancelada") else ""
            return ("booking_cancel", f"Listo, la cita {code} queda cancelada.{suffix}")
        return ("booking_cancel", result.get("error") or "No se pudo cancelar la cita.")

    tz = config.get("booking", {}).get("timezone") or settings.DEFAULT_TIMEZONE
    new_date = textnorm._extract_date_from_text(message, tz) or str(remembered.get("fecha") or "")
    new_time = textnorm._extract_time_from_text(message) or str(remembered.get("hora") or "")
    _chat_manage_state_update(session_id, fecha=new_date, hora=new_time)
    missing = []
    if not new_date:
        missing.append("la nueva fecha")
    if not new_time:
        missing.append("la nueva hora")
    if missing:
        return (
            "booking_reschedule",
            f"Perfecto. Para cambiar la cita {code}, dime {' y '.join(missing)}.",
        )
    result = await _reschedule_booking_by_code(
        cliente_id,
        code,
        new_date,
        new_time,
        trusted_phone=trusted_phone,
        telefono=phone,
        email=email,
        source=source,
        request=request,
    )
    if result.get("ok"):
        _chat_manage_state_clear(session_id)
        try:
            fecha_humana = textnorm._format_date_es(textnorm._parse_date(new_date).date())
        except Exception:
            fecha_humana = new_date
        return (
            "booking_reschedule",
            f"Listo, he cambiado la cita {code} al {fecha_humana} a las {new_time}. El número de reserva sigue siendo el mismo.",
        )
    # Hueco ocupado/cerrado: ofrece alternativas REALES del dia en vez de un error seco.
    # La hora fallida se olvida para que el siguiente mensaje ("pues a las cinco")
    # reintente esa nueva hora sin arrastrar la anterior.
    if session_id:
        with appstate.state_lock:
            _st = appstate.chat_manage_state.get(session_id)
            if _st:
                _st.pop("hora", None)
    error_text = await _reschedule_failure_text(cliente_id, result, new_date, new_time)
    return ("booking_reschedule", error_text)


async def _reschedule_failure_text(
    cliente_id: str, result: Dict[str, Any], new_date: str, new_time: str
) -> str:
    """Texto de fallo de reprogramacion COMPARTIDO por chat y WhatsApp: el error real +
    hasta 3 huecos libres reales del mismo dia como alternativa (nunca un error seco).
    Los huecos descuentan citas y bloqueos: si el resultado trae employee_id se usan los
    del profesional de la cita (excluyendo la propia cita); si no, los del negocio."""
    error_text = str(result.get("error") or "No se pudo reprogramar la cita.")
    if result.get("needs_verification"):
        return error_text
    # Una reprogramacion fallida es una cita a punto de perderse: aunque se ofrezcan
    # alternativas, el negocio puede cuadrar a mano lo que el sistema no puede.
    rescate = clients.call_us_line(cliente_id)
    employee_id = str(result.get("employee_id") or "")
    try:
        if employee_id:
            _all, available = await agenda._employee_slot_sets_for_day(
                cliente_id,
                new_date,
                employee_id=employee_id,
                exclude_booking_id=str(result.get("booking_id") or ""),
            )
        else:
            _all, available = await agenda._public_slot_sets_for_day(cliente_id, new_date)
        free_slots = sorted(available)
    except Exception:  # noqa: BLE001
        free_slots = []
    alternatives = [s for s in free_slots if s != new_time][:3]
    if alternatives:
        error_text += f" Ese día tengo libres: {', '.join(alternatives)}. ¿Te encaja alguna?"
    return error_text + rescate


async def _process_payment_request_message(
    *,
    cliente_id: str,
    message: str,
    request: Optional[Request],
    source: str,
    trusted_phone: str = "",
) -> Optional[Tuple[str, str]]:
    """Flujo de pago para el chat (web/WhatsApp). Si el cliente final pide pagar,
    localiza su cita y genera el enlace, enviado por el canal que toca segun el
    origen de la cita (web/WhatsApp -> email). Resuelve la cita por: numero de
    reserva en el mensaje; si no, telefono verificado del canal (WhatsApp) o
    email/teléfono que el cliente haya escrito. Devuelve (intent, texto) o None
    si el mensaje no es una peticion de pago."""
    if not _message_requests_payment(message):
        return None
    if not _ai_payment_sending_available(cliente_id):
        # Sin cobro online no se contesta con un portazo: se deja seguir el pipeline
        # para que respondan las Q&A del negocio o su informacion. Un salon que cobra
        # la señal por Bizum tiene escrito como se paga, y decirle al cliente "no
        # puedo gestionar el pago online" es tapar esa respuesta con un no.
        return None
    code = _extract_booking_code_from_text(message)
    booking = _get_booking_row_by_code(cliente_id, code) if code else None
    if code and not booking:
        return (
            "payment",
            "No encuentro ninguna cita con ese número de reserva. Revisa el código (formato R-XXXX).",
        )
    if not booking:
        # Sin codigo: intenta identificar al cliente por el telefono verificado del
        # canal (WhatsApp) o por el email/teléfono que haya escrito en el mensaje.
        msg_email = textnorm._extract_email_from_text(message)
        msg_phone = trusted_phone or textnorm._extract_phone_from_text(message)
        booking = _latest_booking_for_contact(cliente_id, phone=msg_phone, email=msg_email)
    if not booking:
        return (
            "payment",
            "Para enviarte el enlace de pago necesito el número de reserva de tu cita (formato R-XXXX), "
            "o el email o telefono con el que reservaste.",
        )
    result = await _ai_send_payment_link(
        cliente_id, booking, base_url=textnorm._preferred_public_base_url(request)
    )
    if not result.get("ok"):
        return ("payment", result.get("error") or "No se pudo generar el enlace de pago.")
    amount_label = result.get("amount_label", "")
    checkout_url = result.get("checkout_url", "")
    servicio = result.get("servicio", "tu cita")
    parts = [f"He generado el enlace para pagar {servicio} ({amount_label})."]
    if result.get("method") == "email" and result.get("sent"):
        parts.append("Te lo he enviado por email.")
    if checkout_url:
        parts.append(f"También puedes pagar aquí: {checkout_url}")
    return ("payment", " ".join(parts))


def _backfill_booking_codes() -> int:
    """Asigna número de reserva a citas activas previas sin codigo.

    One-shot idempotente: tras la primera pasada no encuentra filas y es no-op.
    Solo toca citas confirmadas o pendientes (las que un cliente podria querer
    gestionar); las pasadas/canceladas no necesitan codigo.
    """
    assigned = 0
    try:
        with db._get_db_connection() as connection:
            rows = connection.execute(
                "SELECT id, cliente_id FROM bookings "
                "WHERE booking_code = '' AND status IN ('confirmed', 'pending_review', 'pending_payment')"
            ).fetchall()
            for row in rows:
                code = _unique_booking_code(connection, row["cliente_id"])
                connection.execute(
                    "UPDATE bookings SET booking_code = ? WHERE id = ?",
                    (code, row["id"]),
                )
                assigned += 1
            connection.commit()
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Backfill de codigos de reserva fallo: %s", exc)
    if assigned:
        settings.logger.info("Backfill: asignados %s numeros de reserva a citas existentes.", assigned)
    return assigned


def _build_booking_manage_url(
    manage_token: str,
    request: Optional[Request] = None,
    *,
    viewer: str = "customer",
) -> str:
    if not manage_token:
        return ""
    base_url = textnorm._preferred_public_base_url(request)
    if not base_url:
        return ""
    suffix = "?viewer=client" if viewer == "client" else ""
    return f"{base_url}/booking/manage/{manage_token}{suffix}"


def build_booking_payment_url(manage_token: str, request: Optional[Request] = None) -> str:
    """Enlace corto de pago (reusa manage_token, como el de confirmar asistencia).

    La URL de un checkout de Stripe son ~300 caracteres: ilegible en WhatsApp y
    tres SMS de coste. Esta ocupa unos 60 y redirige a la de Stripe en el momento,
    asi que tampoco caduca cuando el checkout se renueva.
    """
    if not manage_token:
        return ""
    base_url = textnorm._preferred_public_base_url(request)
    return f"{base_url}/p/{manage_token}" if base_url else ""


def _build_booking_confirm_url(manage_token: str, request: Optional[Request] = None) -> str:
    """Enlace 1-clic de confirmacion de asistencia por email (reusa manage_token)."""
    if not manage_token:
        return ""
    base_url = textnorm._preferred_public_base_url(request)
    if not base_url:
        return ""
    return f"{base_url}/booking/confirm/{manage_token}"


def _booking_row_confirm_url(row: sqlite3.Row, request: Optional[Request] = None) -> str:
    try:
        token = row["manage_token"]
    except (KeyError, IndexError):
        return ""
    return _build_booking_confirm_url(token, request)


def _booking_confirm_result_page(
    company_name: str, *, state: str, when_text: str = "", manage_url: str = "", cliente_id: str = "",
) -> str:
    """Pagina que ve el cliente al abrir el enlace de confirmacion del email.

    Con `state="pending"` muestra el boton: abrir el enlace no confirma nada, lo
    hace el POST que dispara ese boton. Los demas estados son el resultado."""
    try:
        config = clients._get_client_config(cliente_id) if cliente_id else {}
    except Exception:  # noqa: BLE001
        config = {}
    marca = str(config.get("color") or "").strip()
    if not re.match(r"^#[0-9A-Fa-f]{6}$", marca):
        marca = "#111111"
    tinta = _brand_ink_for(marca)
    empresa = escape(str(config.get("empresa") or company_name or "").strip())

    textos = {
        "pending": ("¿Vas a venir?", "Confírmanoslo y dejamos tu cita apuntada."),
        "confirmed": ("Asistencia confirmada", "Gracias, hemos apuntado que vas a venir."),
        "already": ("Ya estaba confirmada", "No tienes que hacer nada más."),
        "cancelled": ("Esta cita está cancelada", "No es posible confirmar una cita cancelada."),
        "invalid": ("Enlace no válido", "Este enlace de confirmación no es válido o ha caducado."),
    }
    titulo, subtitulo = textos.get(state, textos["invalid"])

    boton = ""
    if state == "pending":
        boton = (
            '<button id="confirmar" type="button" style="width:100%;margin-top:1.4rem;padding:1rem;'
            f'border:0;border-radius:12px;background:{marca};color:{tinta};font-size:1rem;font-weight:700;'
            'cursor:pointer;min-height:52px;">Sí, confirmo que voy</button>'
        )
    gestionar = ""
    if manage_url:
        gestionar = (
            f'<a href="{escape(manage_url)}" style="display:block;margin-top:.7rem;padding:.9rem;'
            'border:1.5px solid #E4E6EC;border-radius:12px;color:#16181D;text-decoration:none;'
            'font-weight:600;min-height:52px;box-sizing:border-box;">Ver o cambiar mi cita</a>'
        )
    cuando = (
        f'<p style="margin:.9rem 0 0;font-size:1.05rem;font-weight:700;">{escape(when_text)}</p>'
        if when_text else ""
    )

    marca_ini = next((c for c in str(config.get("empresa") or company_name or "?") if c.isalnum()), "?").upper()
    logo_url = str(config.get("logo_url") or "").strip()
    logo = (
        f'<img src="{escape(logo_url)}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">'
        if logo_url.startswith("http") else escape(marca_ini)
    )

    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="robots" content="noindex,nofollow">'
        f'<title>{escape(titulo)} | {empresa}</title></head>'
        '<body style="margin:0;background:#F6F7F9;color:#16181D;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Arial,sans-serif;">'
        f'<div style="background:{marca};color:{tinta};padding:1.5rem 1rem;">'
        '<div style="max-width:26rem;margin:0 auto;display:flex;align-items:center;gap:.8rem;">'
        f'<div style="width:44px;height:44px;border-radius:50%;background:rgba(255,255,255,.16);'
        f'display:flex;align-items:center;justify-content:center;font-weight:800;">{logo}</div>'
        f'<div style="font-weight:700;">{empresa}</div></div></div>'
        '<div style="max-width:26rem;margin:0 auto;padding:0 1rem;">'
        '<div style="background:#fff;border-radius:16px;margin-top:-.9rem;padding:1.4rem 1.15rem 1.3rem;'
        'box-shadow:0 8px 28px rgba(20,24,35,.09);text-align:center;">'
        f'<h1 style="margin:0;font-size:1.35rem;">{escape(titulo)}</h1>'
        f'<p style="margin:.5rem 0 0;color:#5E6470;">{escape(subtitulo)}</p>'
        f'{cuando}{boton}{gestionar}'
        '<p id="aviso" style="margin:.9rem 0 0;color:#5E6470;font-size:.92rem;min-height:1.2rem;"></p>'
        '</div>'
        '<p style="text-align:center;margin:1.3rem 0;color:#9AA0AC;font-size:.74rem;">Gestionado con Vantelia</p>'
        '</div>'
        '<script>'
        'document.getElementById("confirmar")?.addEventListener("click", async function () {'
        '  const b = this, aviso = document.getElementById("aviso");'
        '  b.disabled = true; aviso.textContent = "Confirmando...";'
        '  try {'
        '    const r = await fetch(window.location.pathname, {method:"POST",headers:{"Accept":"application/json"}});'
        '    const d = await r.json();'
        '    if (!r.ok) throw new Error(d.detail || "No se pudo confirmar.");'
        '    b.style.display = "none";'
        '    document.querySelector("h1").textContent = "Asistencia confirmada";'
        '    aviso.textContent = d.mensaje || "Gracias.";'
        '  } catch (e) { b.disabled = false; aviso.textContent = e.message; }'
        '});'
        '</script>'
        '</body></html>'
    )


def _record_booking_audit(
    booking_id: str,
    cliente_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO booking_audit (booking_id, cliente_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                booking_id,
                cliente_id,
                event_type,
                json.dumps(payload or {}, ensure_ascii=False),
                timeutils._utc_now_iso(),
            ),
        )
        connection.commit()


def _mark_booking_confirmed_by_customer(
    booking_id: str, cliente_id: str, *, channel: str = "voice", via: str = ""
) -> bool:
    """El cliente confirma su asistencia (boton WhatsApp, llamada saliente, etc.).
    Registra auditoria y pasa pending_review -> confirmed. Idempotente."""
    row = _get_booking_row_by_id(booking_id)
    if not row or row["cliente_id"] != cliente_id or row["status"] == "cancelled":
        return False
    if row["status"] == "pending_review":
        _update_booking_record(booking_id, status="confirmed", confirmed_at=timeutils._utc_now_iso())
    elif not (row["confirmed_at"] or "").strip():
        _update_booking_record(booking_id, confirmed_at=timeutils._utc_now_iso())
    payload: Dict[str, Any] = {"channel": channel}
    if via:
        payload["via"] = via
    _record_booking_audit(booking_id, cliente_id, "attendance_confirmed_by_customer", payload)
    return True


def _list_booking_audit_rows(booking_id: str, *, limit: int = 80) -> List[sqlite3.Row]:
    with db._get_db_connection() as connection:
        return connection.execute(
            """
            SELECT id, booking_id, cliente_id, event_type, payload_json, created_at
            FROM booking_audit
            WHERE booking_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (booking_id, max(1, min(limit, 200))),
        ).fetchall()


def _booking_audit_source_label(source: str) -> str:
    normalized = textnorm._sanitize_text(source).lower()
    labels = {
        "admin": "Admin Vantelia",
        "portal": "Portal cliente",
        "customer": "Cliente final",
        "system": "Sistema",
    }
    return labels.get(normalized, normalized.replace("_", " ").title() if normalized else "")


def _booking_email_kind_label(kind: str) -> str:
    labels = {
        "received": "Solicitud recibida",
        "confirmed": "Confirmación",
        "cancelled": "Cancelación",
        "rescheduled": "Reprogramación",
        "reminder_24h": "Recordatorio 24h",
        "reminder_2h": "Recordatorio 2h",
    }
    normalized = textnorm._sanitize_text(kind).lower()
    return labels.get(normalized, normalized.replace("_", " ").title() if normalized else "Email")


def _booking_audit_datetime_label(fecha: str, hora: str) -> str:
    if not fecha:
        return ""
    return _booking_datetime_display({"booking_date": fecha, "booking_time": hora})


def _booking_audit_entry_from_row(row: sqlite3.Row) -> BookingAuditEntry:
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    event_type = str(row["event_type"] or "")
    source = _booking_audit_source_label(str(payload.get("source", "")))
    actor = source
    role_value = textnorm._sanitize_text(payload.get("role", "")).lower()
    if not actor and role_value == "admin":
        actor = "Administrador"
    elif not actor and role_value == "client":
        actor = "Cuenta cliente"
    if not actor and event_type in {"booking_confirmed", "booking_completed"}:
        actor = "Sistema"

    title = "Movimiento de cita"
    detail = ""

    if event_type == "booking_created":
        title = "Cita creada"
        status_value = textnorm._sanitize_text(payload.get("status", ""))
        provider_name = textnorm._sanitize_text(payload.get("provider_name", ""))
        parts = []
        if status_value:
            parts.append(f"Estado inicial: {status_value}.")
        if provider_name:
            parts.append(f"Proveedor: {provider_name}.")
        detail = " ".join(parts)
    elif event_type == "booking_rescheduled":
        title = "Cita reprogramada"
        date_label = _booking_audit_datetime_label(
            textnorm._sanitize_text(payload.get("fecha", "")),
            textnorm._sanitize_text(payload.get("hora", "")),
        )
        detail = f"Nuevo horario: {date_label}." if date_label else "Se ha actualizado la fecha u hora."
    elif event_type == "booking_updated":
        title = "Datos del asistente actualizados"
        date_label = _booking_audit_datetime_label(
            textnorm._sanitize_text(payload.get("fecha", "")),
            textnorm._sanitize_text(payload.get("hora", "")),
        )
        detail = (
            f"Se mantuvo el horario en {date_label} y se guardaron cambios en los datos."
            if date_label
            else "Se han guardado cambios en los datos de la cita."
        )
    elif event_type == "booking_cancelled":
        title = "Cita cancelada"
        reason = textnorm._sanitize_text(payload.get("reason", ""), allow_multiline=True)
        detail = "La cita ha quedado cancelada."
        if reason:
            detail += f" Motivo: {reason}"
    elif event_type == "booking_confirmed":
        title = "Cita confirmada"
        detail = "La cita paso a estado confirmado."
    elif event_type == "booking_completed":
        title = "Cita completada"
        detail = "La cita se marco como completada al superar su hora de fin."
    elif event_type == "booking_email_sent":
        title = "Email enviado"
        detail = f"Se envio la plantilla: {_booking_email_kind_label(str(payload.get('kind', '')))}."
    elif event_type == "booking_email_skipped":
        title = "Email omitido"
        reason = textnorm._sanitize_text(payload.get("reason", ""))
        detail = f"No se envio la plantilla {_booking_email_kind_label(str(payload.get('kind', '')))}."
        if reason:
            detail += f" Motivo: {reason}."
    elif event_type == "booking_email_failed":
        title = "Email fallido"
        detail = f"Fallo el envio de {_booking_email_kind_label(str(payload.get('kind', '')))}."
    elif event_type == "voice_otp_sent":
        title = "Código de verificación enviado"
        ch = {"sms": "SMS", "whatsapp": "WhatsApp", "email": "email"}.get(str(payload.get("channel", "")), "")
        detail = f"Se envió al cliente un código de verificación por {ch}." if ch else "Se envió al cliente un código de verificación."
    elif event_type == "voice_otp_verified":
        title = "Identidad verificada con código"
        detail = "El cliente confirmó su identidad con el código de verificación antes de cambiar o cancelar."
    elif event_type == "attendance_confirmed_by_customer":
        title = "Asistencia confirmada por el cliente"
        ch = {"voice": "llamada", "whatsapp": "WhatsApp", "email": "email"}.get(str(payload.get("channel", "")), "")
        detail = f"El cliente confirmo su asistencia por {ch}." if ch else "El cliente confirmo su asistencia."
    elif event_type == "review_request_sent":
        title = "Petición de reseña enviada"
        chs = [str(c) for c in (payload.get("channels") or [])]
        detail = ("Se invito al cliente a dejar una resena por " + ", ".join(chs) + ".") if chs else "Se procesó la petición de reseña."
    elif event_type == "ai_payment_link_sent":
        title = "Enlace de pago enviado por la IA"
        detail = "El asistente envio al cliente un enlace para pagar su cita."

    return BookingAuditEntry(
        audit_id=int(row["id"]),
        booking_id=str(row["booking_id"]),
        event_type=event_type,
        title=title,
        detail=detail.strip(),
        created_at=str(row["created_at"]),
        source=source,
        actor=actor,
    )


def _get_booking_row_by_id(booking_id: str) -> Optional[sqlite3.Row]:
    with db._get_db_connection() as connection:
        return connection.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()


def _get_booking_row_by_token(manage_token: str) -> Optional[sqlite3.Row]:
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM bookings WHERE manage_token = ?",
            (manage_token,),
        ).fetchone()


def _update_booking_record(booking_id: str, **updates: Any) -> None:
    if not updates:
        return
    assignments = ", ".join(f"{column} = ?" for column in updates)
    values = list(updates.values()) + [booking_id]
    with db._get_db_connection() as connection:
        connection.execute(f"UPDATE bookings SET {assignments} WHERE id = ?", values)
        connection.commit()


def _booking_row_manage_url(
    row: sqlite3.Row,
    request: Optional[Request] = None,
    *,
    viewer: str = "customer",
) -> str:
    return _build_booking_manage_url(row["manage_token"], request, viewer=viewer)


def _serialize_booking_row(
    row: sqlite3.Row,
    request: Optional[Request] = None,
    *,
    service_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    config = clients._get_client_config(row["cliente_id"])
    if service_meta is None:
        service_meta = agenda._booking_display_service_meta(row, row["cliente_id"])
    return {
        "booking_id": row["id"],
        "cliente_id": row["cliente_id"],
        "empresa": config["nombre"],
        "employee_id": row["employee_id"] or "",
        "employee_name": row["employee_name"] or "",
        "nombre": row["nombre"],
        "email": row["email"],
        "telefono": row["telefono"] or "",
        "servicio": row["servicio"] or "",
        "notas": row["notas"] or "",
        "fecha": row["booking_date"],
        "hora": row["booking_time"],
        "timezone": row["timezone"] or config["booking"]["timezone"],
        "estado": row["status"],
        "provider_name": row["provider_name"],
        "provider_status": row["provider_status"],
        "provider_booking_id": row["provider_booking_id"] or "",
        "provider_booking_url": row["provider_booking_url"] or "",
        "manage_url": _booking_row_manage_url(row, request),
        "booking_code": row["booking_code"] or "",
        "completed_source": row["completed_source"] or "",
        "service_id": service_meta["service_id"],
        "service_duration_minutes": int(service_meta["service_duration_minutes"] or 0),
        "service_price_cents": int(service_meta["service_price_cents"] or 0),
        "service_price_label": service_meta["service_price_label"],
        "start_at": row["start_at"] or "",
        "end_at": row["end_at"] or "",
        "created_at": row["created_at"],
        "confirmed_at": row["confirmed_at"] or "",
        "cancelled_at": row["cancelled_at"] or "",
        "rescheduled_at": row["rescheduled_at"] or "",
        "confirmation_email_sent_at": row["confirmation_email_sent_at"] or "",
        "reminder_24h_sent_at": row["reminder_24h_sent_at"] or "",
        "reminder_2h_sent_at": row["reminder_2h_sent_at"] or "",
        "customer_email_status": row["customer_email_status"] or "",
        "contact_email": config.get("contacto", {}).get("email", ""),
        "contact_phone": config.get("contacto", {}).get("telefono", ""),
    }


async def _cancel_provider_booking(booking_row: sqlite3.Row) -> None:
    _ = booking_row
    return None


async def _reschedule_provider_booking(
    booking_row: sqlite3.Row,
    *,
    fecha: str,
    hora: str,
) -> appstate.ProviderBookingResult:
    _ = (fecha, hora)
    return appstate.ProviderBookingResult(
        success=True,
        status="confirmed",
        provider_name="internal",
        provider_booking_id="",
        provider_booking_url="",
        message="Reserva reprogramada internamente.",
    )


def _store_booking(record: Dict[str, Any], *, skip_payment: bool = False) -> None:
    service = agenda._get_service_row(record["cliente_id"], record.get("service_id", "")) or agenda._find_service_by_name(
        record["cliente_id"], record.get("servicio", "")
    )
    # skip_payment: usado por el sembrado de demo. Mantiene el payment_status que trae
    # el record (valor visual) y NO crea checkouts Stripe reales. Sin esto, un servicio
    # con payment_required dispararia create_booking_payment_checkout por cada cita demo
    # (bloquea el worker sincrono -> 504).
    if not skip_payment:
        decision = resolve_payment_requirement(record["cliente_id"], service)
        record["payment_status"] = decision["payment_status"]
        if decision["payment_required"]:
            record["status"] = "pending_payment"
            record["confirmed_at"] = ""
    else:
        record.setdefault("payment_status", "not_required")
    # Los tramos de trabajo/espera del servicio se sellan aqui, que es por donde
    # pasan TODOS los canales (widget, WhatsApp, voz y panel).
    if service is not None and not record.get("gap_json"):
        try:
            record["gap_json"] = (service["gap_json"] if "gap_json" in service.keys() else "") or ""
        except (IndexError, KeyError):
            record["gap_json"] = ""
    location_id = record.get("location_id", "")
    if not location_id and record.get("employee_id"):
        employee_row = agenda._get_employee_row(record["employee_id"], cliente_id=record["cliente_id"])
        if employee_row is not None:
            location_id = employee_row["location_id"] or ""
    if not location_id:
        location_id = agenda._default_location_id(record["cliente_id"])
    record["location_id"] = location_id
    # Precio efectivo segun el centro (override por centro si existe).
    if service is not None and location_id:
        record["service_price_cents"] = agenda._service_price_cents_resolved(
            record["cliente_id"], service, location_id
        )
    # Sala generica: asignacion best-effort si el centro tiene salas configuradas.
    if not record.get("resource_id"):
        start_min = textnorm._time_to_min(record.get("booking_time", ""))
        if start_min is not None and location_id:
            duration = agenda._service_duration_minutes(
                record["cliente_id"],
                record.get("servicio", ""),
                agenda._get_employee_row(record.get("employee_id", ""), cliente_id=record["cliente_id"])
                if record.get("employee_id")
                else None,
            )
            record["resource_id"] = agenda._assign_free_resource(
                record["cliente_id"], location_id, record.get("booking_date", ""), start_min, start_min + duration
            )
    record.setdefault("resource_id", "")
    with db._get_db_connection() as connection:
        if not record.get("booking_code"):
            record["booking_code"] = _unique_booking_code(connection, record["cliente_id"])
        connection.execute(
            """
            INSERT INTO bookings (
                id, cliente_id, employee_id, employee_name, nombre, email, telefono, servicio,
                booking_date, booking_time, notas, status,
                provider_name, provider_status, provider_booking_id, provider_booking_url,
                manage_token, timezone, start_at, end_at,
                confirmed_at, cancelled_at, rescheduled_at, rescheduled_from_booking_id,
                confirmation_email_sent_at, reminder_24h_sent_at, reminder_2h_sent_at,
                customer_email_status, customer_email_last_error, booking_code,
                service_id, service_price_cents, payment_status, location_id, resource_id, source, gap_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["cliente_id"],
                record["employee_id"],
                record["employee_name"],
                record["nombre"],
                record["email"],
                record["telefono"],
                record["servicio"],
                record["booking_date"],
                record["booking_time"],
                record["notas"],
                record["status"],
                record["provider_name"],
                record["provider_status"],
                record["provider_booking_id"],
                record["provider_booking_url"],
                record["manage_token"],
                record["timezone"],
                record["start_at"],
                record["end_at"],
                record["confirmed_at"],
                record["cancelled_at"],
                record["rescheduled_at"],
                record["rescheduled_from_booking_id"],
                record["confirmation_email_sent_at"],
                record["reminder_24h_sent_at"],
                record["reminder_2h_sent_at"],
                record["customer_email_status"],
                record["customer_email_last_error"],
                record["booking_code"],
                record.get("service_id", ""),
                int(record.get("service_price_cents", 0) or 0),
                record.get("payment_status", "not_required"),
                record.get("location_id", ""),
                record.get("resource_id", ""),
                record["source"],
                # Tramos activo/espera copiados del servicio al reservar: si el
                # negocio los cambia luego, esta cita conserva los suyos.
                record.get("gap_json", ""),
                record["created_at"],
            ),
        )
        connection.commit()
    if not skip_payment:
        _booking_payment_after_store(record["id"])
    booking_status = "confirmado" if record.get("status") == "confirmed" else "cita_pendiente"
    crm._crm_upsert_contact(
        record["cliente_id"],
        name=record.get("nombre", ""),
        email=record.get("email", ""),
        phone=record.get("telefono", ""),
        source=record.get("source", "booking"),
        status=booking_status,
        entity_type="booking",
        entity_id=record["id"],
    )


async def _send_booking_to_webhook(cliente_id: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    config = clients._get_client_config(cliente_id)
    booking_cfg = config["booking"]
    webhook_url = booking_cfg.get("webhook_url", "").strip()

    if not webhook_url and booking_cfg.get("webhook_env"):
        webhook_url = os.getenv(booking_cfg["webhook_env"], "").strip()

    if not webhook_url:
        webhook_url = settings.WEBHOOK_DEFAULT

    if not webhook_url:
        return True, "not_configured"

    try:
        webhook_url = textnorm._normalize_optional_http_url(webhook_url)
    except RuntimeError as exc:
        settings.logger.error("Webhook invalido para %s: %s", cliente_id, exc)
        return False, "invalid_webhook_url"

    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=False) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"User-Agent": "Vantelia-Widget/1.0"},
            )
            response.raise_for_status()
        return True, "delivered"
    except httpx.HTTPError as exc:
        settings.logger.error("Error enviando lead de %s al webhook: %s", cliente_id, exc)
        return False, "delivery_failed"


def _booking_public_detail_from_row(
    row: sqlite3.Row,
    request: Optional[Request] = None,
) -> BookingDetailPublic:
    data = _serialize_booking_row(row, request)
    return BookingDetailPublic(
        booking_id=data["booking_id"],
        cliente_id=data["cliente_id"],
        empresa=data["empresa"],
        employee_id=data["employee_id"],
        employee_name=data["employee_name"],
        nombre=data["nombre"],
        email=data["email"],
        telefono=data["telefono"],
        servicio=data["servicio"],
        notas=data["notas"],
        fecha=data["fecha"],
        hora=data["hora"],
        timezone=data["timezone"],
        estado=data["estado"],
        provider_name=data["provider_name"],
        provider_booking_url=data["provider_booking_url"],
        manage_url=data["manage_url"],
        service_id=data.get("service_id", ""),
        service_duration_minutes=int(data.get("service_duration_minutes", 0) or 0),
        service_price_cents=int(data.get("service_price_cents", 0) or 0),
        service_price_label=data.get("service_price_label", ""),
        contact_email=data["contact_email"],
        contact_phone=data["contact_phone"],
        confirmed_by_customer=_booking_confirmed_by_customer(data["booking_id"]),
        available_services=agenda._services_for_employee(
            data["cliente_id"],
            agenda._get_employee_row(data["employee_id"], cliente_id=data["cliente_id"]) if data["employee_id"] else None,
        ),
    )


def _booking_admin_summary_from_row(
    row: sqlite3.Row,
    request: Optional[Request] = None,
) -> AdminBookingResumen:
    data = _serialize_booking_row(row, request)
    return AdminBookingResumen(
        booking_id=data["booking_id"],
        cliente_id=data["cliente_id"],
        empresa=data["empresa"],
        employee_id=data["employee_id"],
        employee_name=data["employee_name"],
        nombre=data["nombre"],
        email=data["email"],
        telefono=data["telefono"],
        servicio=data["servicio"],
        fecha=data["fecha"],
        hora=data["hora"],
        timezone=data["timezone"],
        estado=data["estado"],
        provider_name=data["provider_name"],
        provider_status=data["provider_status"],
        provider_booking_id=data["provider_booking_id"],
        provider_booking_url=data["provider_booking_url"],
        manage_url=data["manage_url"],
        created_at=data["created_at"],
        confirmed_at=data["confirmed_at"],
        cancelled_at=data["cancelled_at"],
        rescheduled_at=data["rescheduled_at"],
        confirmation_email_sent_at=data["confirmation_email_sent_at"],
        reminder_24h_sent_at=data["reminder_24h_sent_at"],
        reminder_2h_sent_at=data["reminder_2h_sent_at"],
        customer_email_status=data["customer_email_status"],
    )


_PAYMENT_UNSET = object()


def _latest_payments_for_bookings(
    cliente_id: str, booking_ids: List[str]
) -> Dict[str, sqlite3.Row]:
    """Ultimo customer_payment por booking_id en UNA query (batch para listados)."""
    out: Dict[str, sqlite3.Row] = {}
    ids = [bid for bid in booking_ids if bid]
    if not cliente_id or not ids:
        return out
    with db._get_db_connection() as connection:
        for start in range(0, len(ids), 400):
            chunk = ids[start:start + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"SELECT * FROM customer_payments WHERE cliente_id=? AND booking_id IN ({placeholders}) "
                "ORDER BY created_at ASC",
                (cliente_id, *chunk),
            ).fetchall()
            for payment in rows:
                out[payment["booking_id"]] = payment  # ASC -> ultimo gana = mas reciente
    return out


def _customer_confirmed_index(cliente_id: str, booking_ids: List[str]) -> set:
    """IDs de citas con confirmacion explicita del cliente final (audit
    ``attendance_confirmed_by_customer``), en UNA query batch para listados.
    Distinto del estado ``confirmed`` de la cita (hueco activo): aqui solo
    entran las que el cliente confirmo via recordatorio/llamada/email."""
    out: set = set()
    ids = [bid for bid in booking_ids if bid]
    if not cliente_id or not ids:
        return out
    with db._get_db_connection() as connection:
        for start in range(0, len(ids), 400):
            chunk = ids[start:start + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                f"SELECT DISTINCT booking_id FROM booking_audit "
                f"WHERE cliente_id=? AND event_type='attendance_confirmed_by_customer' "
                f"AND booking_id IN ({placeholders})",
                (cliente_id, *chunk),
            ).fetchall()
            for r in rows:
                out.add(r["booking_id"])
    return out


def _portal_booking_summaries(
    rows: List[sqlite3.Row],
    request: Optional[Request] = None,
    *,
    cliente_id: str = "",
) -> List[PortalBookingSummary]:
    """Construye los resumenes de un listado prefetcheando servicio + pago en
    batch (evita el N+1 de 2 conexiones SQLite por fila). Solo aplica el batch si
    todas las filas son del mismo ``cliente_id``; si no, cae al per-row."""
    if not rows:
        return []
    meta_index: Dict[str, Dict[str, Any]] = {}
    payments_index: Dict[str, sqlite3.Row] = {}
    if cliente_id:
        meta_index = agenda._booking_service_meta_index(cliente_id, rows)
        payments_index = _latest_payments_for_bookings(cliente_id, [row["id"] for row in rows])
        confirmed_index = _customer_confirmed_index(cliente_id, [row["id"] for row in rows])
        # Cobrado real por cita (reserva + mostrador), en batch: sin esto el listado
        # haria dos consultas por fila.
        paid_index = paystate.paid_cents_for_bookings(cliente_id, [row["id"] for row in rows])
        return [
            _portal_booking_summary_from_row(
                row,
                request,
                service_meta=meta_index.get(row["id"]),
                payment=payments_index.get(row["id"]),
                customer_confirmed=row["id"] in confirmed_index,
                paid_cents=paid_index.get(row["id"], 0),
            )
            for row in rows
        ]
    return [_portal_booking_summary_from_row(row, request) for row in rows]


def _work_intervals_of(row: sqlite3.Row, data: Dict[str, Any]) -> List[List[int]]:
    """Los ratos OCUPADOS de una cita, para que el panel no la pinte maciza.

    Un pack de 220 minutos con 20 y 90 de exposicion solo ocupa 110: entremedias la
    clienta espera con el producto puesto y la profesional PUEDE atender a otra. La
    agenda ya lo respetaba al dar hora, pero en la pantalla se veia un bloque de
    cuatro horas y el negocio creia tener la tarde entera cogida.

    Se devuelven en minutos desde medianoche. Vacio = la cita ocupa su duracion
    entera y el panel la pinta como siempre.
    """
    try:
        inicio = textnorm._time_to_min(data.get("hora") or row["booking_time"])
        if inicio is None:
            return []
        duracion = int(data.get("service_duration_minutes", 0) or 0)
        tramos = (row["gap_json"] if "gap_json" in row.keys() else "") or ""
        if duracion <= 0 or not tramos:
            return []
        ocupados = agenda._tramos_de_trabajo(tramos, inicio, duracion)
        if len(ocupados) <= 1:
            return []
        return [[int(a), int(b)] for a, b in ocupados]
    except Exception:  # noqa: BLE001 - nunca puede tumbar el listado de citas
        return []


def _portal_booking_summary_from_row(
    row: sqlite3.Row,
    request: Optional[Request] = None,
    *,
    service_meta: Optional[Dict[str, Any]] = None,
    payment: Any = _PAYMENT_UNSET,
    customer_confirmed: Optional[bool] = None,
    paid_cents: Optional[int] = None,
) -> PortalBookingSummary:
    data = _serialize_booking_row(row, request, service_meta=service_meta)
    status_value = data["estado"]
    start_at_dt = timeutils._from_utc_iso(data["start_at"])
    is_past = bool(start_at_dt and start_at_dt < timeutils._utc_now())
    can_edit = status_value not in {"cancelled", "completed", "no_show"} and not is_past
    # La asistencia se marca en citas pasadas no canceladas; permite tambien
    # corregir una completada-auto -> no_show (o viceversa) despues.
    can_mark_attendance = status_value != "cancelled" and (is_past or status_value in {"completed", "no_show"})
    if payment is _PAYMENT_UNSET:
        with db._get_db_connection() as connection:
            payment = connection.execute(
                "SELECT * FROM customer_payments WHERE cliente_id=? AND booking_id=? ORDER BY created_at DESC LIMIT 1",
                (row["cliente_id"], row["id"]),
            ).fetchone()
    if customer_confirmed is None:
        with db._get_db_connection() as connection:
            customer_confirmed = bool(connection.execute(
                "SELECT 1 FROM booking_audit WHERE booking_id=? "
                "AND event_type='attendance_confirmed_by_customer' LIMIT 1",
                (row["id"],),
            ).fetchone())
    cobro = paystate.summary_for_booking(
        row["cliente_id"], row,
        paid_cents=paid_cents,
        booking_payment_status=str((_booking_payment_row(row["id"]) or {}).get("status", ""))
        if paid_cents is None else "",
    )
    return PortalBookingSummary(
        booking_id=data["booking_id"],
        empresa=data["empresa"],
        employee_id=data["employee_id"],
        employee_name=data["employee_name"],
        nombre=data["nombre"],
        email=data["email"],
        telefono=data.get("telefono", ""),
        servicio=data["servicio"],
        notas=data.get("notas", ""),
        fecha=data["fecha"],
        hora=data["hora"],
        timezone=data["timezone"],
        estado=data["estado"],
        provider_name=data["provider_name"],
        provider_booking_url=data["provider_booking_url"],
        manage_url=_booking_row_manage_url(row, request, viewer="client"),
        contact_email=data["contact_email"],
        contact_phone=data["contact_phone"],
        booking_code=data.get("booking_code", ""),
        completed_source=data.get("completed_source", ""),
        service_id=data.get("service_id", ""),
        service_duration_minutes=int(data.get("service_duration_minutes", 0) or 0),
        service_price_cents=int(data.get("service_price_cents", 0) or 0),
        service_price_label=data.get("service_price_label", ""),
        payment_status=payment["status"] if payment else "",
        pay_state=(row["payment_status"] if "payment_status" in row.keys() else "") or "",
        payment_amount_cents=int(payment["amount_cents"] or 0) if payment else 0,
        pay_kind=cobro["kind"],
        pay_label=cobro["label"],
        pay_paid_cents=cobro["paid_cents"],
        pay_pending_cents=cobro["pending_cents"],
        payment_checkout_url=payment["checkout_url"] if payment else "",
        start_at=data["start_at"],
        end_at=data["end_at"],
        can_cancel=can_edit,
        can_reschedule=can_edit,
        can_mark_attendance=can_mark_attendance,
        customer_confirmed=bool(customer_confirmed),
    )


def _list_booking_rows(
    *,
    cliente_id: str = "",
    employee_id: str = "",
    location_id: str = "",
    status_filter: str = "",
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 100,
    offset: int = 0,
    scope: str = "all",
) -> Tuple[List[sqlite3.Row], int]:
    sql = "SELECT * FROM bookings"
    clauses: List[str] = []
    params: List[Any] = []
    if cliente_id:
        clauses.append("cliente_id = ?")
        params.append(cliente_id)
    if employee_id:
        clauses.append("employee_id = ?")
        params.append(employee_id)
    if location_id:
        clauses.append("location_id = ?")
        params.append(location_id)
    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter)
    if date_from:
        clauses.append("booking_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("booking_date <= ?")
        params.append(date_to)
    if search:
        like_search = f"%{search}%"
        clauses.append(
            "("
            "id LIKE ? OR cliente_id LIKE ? OR nombre LIKE ? OR email LIKE ? OR telefono LIKE ? "
            "OR servicio LIKE ? OR provider_booking_id LIKE ? OR employee_name LIKE ?"
            ")"
        )
        params.extend([like_search] * 8)
    now_iso = timeutils._utc_now_iso()
    if scope == "upcoming":
        clauses.append(
            "("
            "status IN ('confirmed', 'pending_review', 'pending_payment') "
            "AND (start_at = '' OR start_at >= ?)"
            ")"
        )
        params.append(now_iso)
    elif scope == "history":
        clauses.append(
            "("
            "status IN ('cancelled', 'completed') "
            "OR (start_at <> '' AND start_at < ?)"
            ")"
        )
        params.append(now_iso)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    count_sql = sql.replace("SELECT *", "SELECT COUNT(*)", 1)
    if scope == "upcoming":
        sql += (
            " ORDER BY booking_date ASC, booking_time ASC, "
            "CASE WHEN start_at = '' THEN created_at ELSE start_at END ASC"
        )
    elif scope == "history":
        sql += (
            " ORDER BY booking_date DESC, booking_time DESC, "
            "CASE WHEN start_at = '' THEN created_at ELSE start_at END DESC"
        )
    else:
        sql += " ORDER BY booking_date ASC, booking_time ASC, created_at ASC"
    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with db._get_db_connection() as connection:
        total = connection.execute(count_sql, tuple(params[:-2] if params else [])).fetchone()[0]
        rows = connection.execute(sql, tuple(params)).fetchall()
        return rows, total


def _portal_bookings_effective_cap(date_from: str, date_to: str) -> int:
    """Cap de filas para ``/auth/bookings``.

    Para listados normales devolvemos como mucho una pagina
    (``PORTAL_BOOKINGS_PAGE_CAP``). Cuando la consulta esta acotada por un rango
    de fechas corto (la vista calendario pide una ventana de ~6 semanas),
    elevamos el cap para no truncar las citas de los ultimos dias del rango, que
    de otro modo apareceria como dias vacios en el calendario.
    """
    if date_from and date_to:
        try:
            span = (
                datetime.strptime(date_to, "%Y-%m-%d")
                - datetime.strptime(date_from, "%Y-%m-%d")
            ).days
        except ValueError:
            span = None
        if span is not None and 0 <= span <= settings.PORTAL_BOOKINGS_RANGE_MAX_SPAN_DAYS:
            return settings.PORTAL_BOOKINGS_RANGE_CAP
    return settings.PORTAL_BOOKINGS_PAGE_CAP


def _load_booking_or_404(booking_id: str) -> sqlite3.Row:
    row = _get_booking_row_by_id(booking_id)
    if not row:
        raise HTTPException(status_code=404, detail="Reserva no encontrada.")
    return row


def _manage_token_still_valid(row: sqlite3.Row) -> bool:
    try:
        booking_date = (row["booking_date"] or "").strip()
        if booking_date:
            base = datetime.strptime(booking_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            cutoff = base + timedelta(days=settings.MANAGE_TOKEN_VALID_DAYS_AFTER_DATE)
        else:
            created_at = (row["created_at"] or "").strip()
            if not created_at:
                return True
            base = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            cutoff = base + timedelta(days=90)
        return timeutils._utc_now() <= cutoff
    except Exception:
        return True


def _load_booking_by_token_or_404(manage_token: str) -> sqlite3.Row:
    row = _get_booking_row_by_token(manage_token)
    if not row:
        raise HTTPException(status_code=404, detail="No se ha encontrado la reserva.")
    if not _manage_token_still_valid(row):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Este enlace de gestión ha caducado. Contacta con el negocio si necesitas modificar la cita.",
        )
    return row


def _booking_update_payload_from_reschedule(row: sqlite3.Row, data: BookingReschedulePayload) -> BookingUpdatePayload:
    return BookingUpdatePayload(
        nombre=row["nombre"],
        email=row["email"],
        telefono=row["telefono"] or "",
        servicio=row["servicio"] or "",
        employee_id=data.employee_id or (row["employee_id"] or ""),
        fecha=data.fecha,
        hora=data.hora,
        notas=row["notas"] or "",
    )


async def _update_booking_details(
    booking_row: sqlite3.Row,
    data: BookingUpdatePayload,
    request: Request,
    *,
    source: str,
    audit_payload: Optional[Dict[str, Any]] = None,
) -> BookingActionResponse:
    if booking_row["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="No se puede modificar una cita cancelada.")
    if booking_row["status"] == "completed":
        raise HTTPException(status_code=409, detail="No se puede modificar una cita completada.")
    if booking_row["status"] == "no_show":
        raise HTTPException(status_code=409, detail="No se puede modificar una cita marcada como no asistida.")

    booking_date_dt = textnorm._parse_date(data.fecha)
    agenda._validate_booking_window(booking_row["cliente_id"], booking_date_dt)
    booking_date = booking_date_dt.strftime("%Y-%m-%d")
    booking_time = textnorm._parse_time(data.hora).strftime("%H:%M")
    target_employee = agenda._resolve_employee_for_booking(
        booking_row["cliente_id"],
        data.employee_id or (booking_row["employee_id"] or ""),
        require_active=False,
    )
    if not agenda._service_name_allowed_for_employee(booking_row["cliente_id"], target_employee, data.servicio):
        raise HTTPException(
            status_code=400,
            detail="El servicio seleccionado no esta disponible para ese profesional.",
        )
    service_row = agenda._find_service_by_name(booking_row["cliente_id"], data.servicio)
    service_duration = agenda._service_duration_minutes(booking_row["cliente_id"], data.servicio, target_employee)
    service_id = service_row["slug"] if service_row else ""
    service_price = int(service_row["price_cents"]) if service_row else 0
    employee_changed = (target_employee["id"] or "") != (booking_row["employee_id"] or "")
    slot_changed = (
        booking_date != booking_row["booking_date"]
        or booking_time != booking_row["booking_time"]
        or employee_changed
    )

    if slot_changed and not await agenda._booking_slot_available_for_reschedule(
        booking_row["cliente_id"],
        booking_date,
        booking_time,
        employee_id=target_employee["id"],
        exclude_booking_id=booking_row["id"],
        duration_minutes=service_duration,
    ):
        raise HTTPException(status_code=409, detail="Ese horario ya no esta disponible. Elige otro tramo.")

    start_local, end_local = agenda._booking_start_end(
        booking_row["cliente_id"],
        booking_date,
        booking_time,
        employee_id=target_employee["id"],
        duration_minutes=service_duration,
    )
    provider_result = (
        await _reschedule_provider_booking(booking_row, fecha=booking_date, hora=booking_time)
        if slot_changed
        else appstate.ProviderBookingResult(
            success=True,
            status=booking_row["provider_status"] or "confirmed",
            provider_name=booking_row["provider_name"] or "internal",
            provider_booking_id=booking_row["provider_booking_id"] or "",
            provider_booking_url=booking_row["provider_booking_url"] or "",
            message="Reserva actualizada internamente.",
        )
    )

    updates: Dict[str, Any] = {
        "nombre": textnorm._sanitize_text(data.nombre),
        "email": str(data.email),
        "telefono": textnorm._sanitize_text(data.telefono),
        "servicio": textnorm._sanitize_text(data.servicio),
        "notas": textnorm._sanitize_text(data.notas, allow_multiline=True),
        "employee_id": target_employee["id"],
        "employee_name": target_employee["name"],
        "booking_date": booking_date,
        "booking_time": booking_time,
        "start_at": timeutils._to_utc_iso(start_local),
        "end_at": timeutils._to_utc_iso(end_local),
        "service_id": service_id,
        "service_price_cents": service_price,
        "status": "confirmed",
        "provider_status": provider_result.status,
        "provider_booking_id": provider_result.provider_booking_id,
        "provider_booking_url": provider_result.provider_booking_url,
    }
    if slot_changed:
        updates.update(
            {
                "rescheduled_at": timeutils._utc_now_iso(),
                "reminder_24h_sent_at": "",
                "reminder_2h_sent_at": "",
            }
        )

    # Igual que al crear: entre comprobar el hueco y guardar hay una llamada al
    # proveedor, o sea una ventana ancha en la que otra persona puede haberse
    # quedado ese tramo. Se re-comprueba con el lock cogido (excluyendo la propia
    # cita, que obviamente ocupa su hueco actual).
    with appstate.booking_insert_lock:
        if slot_changed and agenda.slot_pisa_otra_cita(
            booking_row["cliente_id"], booking_date, booking_time,
            employee_id=target_employee["id"], duration_minutes=service_duration,
            exclude_booking_id=booking_row["id"],
        ):
            raise HTTPException(
                status_code=409,
                detail="Ese horario acaba de ser reservado por otra persona. Elige otro tramo.",
            )
        _update_booking_record(booking_row["id"], **updates)
    event_type = "booking_rescheduled" if slot_changed else "booking_updated"
    _record_booking_audit(
        booking_row["id"],
        booking_row["cliente_id"],
        event_type,
        {
            "source": source,
            "fecha": booking_date,
            "hora": booking_time,
            "employee_id": target_employee["id"],
            "employee_name": target_employee["name"],
            **(audit_payload or {}),
        },
    )
    refreshed = _load_booking_or_404(booking_row["id"])
    crm._crm_upsert_contact(
        refreshed["cliente_id"], name=refreshed["nombre"], email=refreshed["email"],
        phone=refreshed["telefono"] or "", source=source, status="confirmado",
        entity_type="booking", entity_id=refreshed["id"],
    )
    try:
        await _send_booking_reminder_by_kind(refreshed, "rescheduled" if slot_changed else "confirmed", request)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("No se ha podido enviar el aviso de actualizacion %s: %s", refreshed["id"], exc)

    return BookingActionResponse(
        ok=True,
        booking_id=refreshed["id"],
        estado=refreshed["status"],
        mensaje="La cita se ha actualizado correctamente.",
        employee_id=refreshed["employee_id"] or "",
        employee_name=refreshed["employee_name"] or "",
        manage_url=_booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
    )


async def _create_booking_core(
    cliente_id: str,
    *,
    employee_row: sqlite3.Row,
    nombre: str,
    email: str,
    telefono: str,
    servicio: str,
    booking_date: str,
    booking_time: str,
    notas: str = "",
    source: str,
    webhook_source: str = "",
    send_confirmation: bool = True,
    request: Optional[Request] = None,
    audit_extra: Optional[Dict[str, Any]] = None,
) -> sqlite3.Row:
    """Crea una cita: fuente UNICA para todos los canales (widget, WhatsApp, voz,
    portal manual). Resuelve servicio/duracion/precio, valida hueco, llama al
    proveedor + webhook, guarda via _store_booking (que sella centro, codigo y
    politica de pago), audita y envia la confirmación.

    El canal resuelve ANTES el empleado (cada canal tiene su politica de
    resolucion) y traduce DESPUES los HTTPException a su medio (texto WhatsApp,
    respuesta de tool de voz, JSON del portal...). 409 = hueco ocupado.

    Devuelve la fila guardada (el estado final puede ser pending_payment si el
    servicio exige pago por adelantado)."""
    config = clients._get_client_config(cliente_id)
    service_row = agenda._find_service_by_name(cliente_id, servicio)
    service_duration = agenda._service_duration_minutes(cliente_id, servicio, employee_row)
    service_id = service_row["slug"] if service_row else ""
    service_price = agenda._service_price_cents_resolved(
        cliente_id, service_row, employee_row["location_id"] or ""
    )

    if not await agenda._booking_slot_available(
        cliente_id, booking_date, booking_time,
        employee_id=employee_row["id"], duration_minutes=service_duration,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese horario ya no esta disponible. Elige otro tramo.",
        )

    booking_id = f"bk_{secrets.token_urlsafe(10)}"
    manage_token = _generate_manage_token()
    created_at = timeutils._utc_now_iso()
    provider = _get_booking_provider(config)
    start_local, end_local = agenda._booking_start_end(
        cliente_id, booking_date, booking_time,
        employee_id=employee_row["id"], duration_minutes=service_duration,
    )
    booking_timezone = employee_row["timezone"] or config["booking"]["timezone"]

    payload_source = webhook_source or source
    provider_payload = {
        "booking_id": booking_id,
        "cliente_id": cliente_id,
        "empresa": config["nombre"],
        "employee_id": employee_row["id"],
        "employee_name": employee_row["name"],
        "nombre": nombre,
        "email": email,
        "telefono": telefono,
        "servicio": servicio,
        "fecha": booking_date,
        "hora": booking_time,
        "notas": notas,
        "source": payload_source,
        "created_at": created_at,
    }
    try:
        provider_result = await _create_provider_booking(cliente_id, provider_payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        settings.logger.error("Error creando cita externa para %s: %s", cliente_id, exc)
        raise HTTPException(
            status_code=502,
            detail="No se ha podido crear la cita en el proveedor de calendario.",
        ) from exc

    webhook_payload = dict(provider_payload)
    webhook_payload.update({
        "provider_name": provider_result.provider_name,
        "provider_booking_id": provider_result.provider_booking_id,
        "provider_booking_url": provider_result.provider_booking_url,
    })
    _, webhook_status = await _send_booking_to_webhook(cliente_id, webhook_payload)
    provider_status = webhook_status if provider == "internal" else provider_result.status

    record = {
        "id": booking_id,
        "cliente_id": cliente_id,
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
        "provider_name": provider_result.provider_name,
        "provider_status": provider_status,
        "provider_booking_id": provider_result.provider_booking_id,
        "provider_booking_url": provider_result.provider_booking_url,
        "manage_token": manage_token,
        "timezone": booking_timezone,
        "start_at": timeutils._to_utc_iso(start_local),
        "end_at": timeutils._to_utc_iso(end_local),
        "confirmed_at": created_at,
        "cancelled_at": "",
        **_booking_blank_tracking_fields(),
        "service_id": service_id,
        "service_price_cents": service_price,
        "source": source,
        "created_at": created_at,
    }
    # Comprobar-y-guardar, atomico. El indice unico de la BD para el choque exacto
    # de hora; el lock + esta re-comprobacion para los SOLAPES parciales, que dos
    # peticiones simultaneas se colaban las dos (medido en
    # tests/test_reserva_concurrente.py).
    try:
        with appstate.booking_insert_lock:
            if agenda.slot_pisa_otra_cita(
                cliente_id, booking_date, booking_time,
                employee_id=employee_row["id"], duration_minutes=service_duration,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ese horario acaba de ser reservado por otra persona. Elige otro tramo.",
                )
            _store_booking(record)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese horario acaba de ser reservado por otra persona. Elige otro tramo.",
        ) from exc

    _record_booking_audit(
        booking_id,
        cliente_id,
        "booking_created",
        {
            "status": "confirmed",
            "source": source,
            "provider_name": provider_result.provider_name,
            "provider_status": provider_status,
            "employee_id": employee_row["id"],
            "employee_name": employee_row["name"],
            **(audit_extra or {}),
        },
    )

    stored = _get_booking_row_by_id(booking_id)
    if stored is None:  # defensa: _store_booking acaba de insertar
        raise HTTPException(status_code=500, detail="No se pudo guardar la cita.")
    if send_confirmation and _booking_has_reminder_contact(email, telefono):
        # Con senal pendiente no se puede decir "cita confirmada": se manda el aviso
        # de pago, que ademas lleva el enlace. Al pagar llega la confirmación real.
        aviso = "pending_payment" if stored["status"] == "pending_payment" else "confirmed"
        try:
            await _send_booking_reminder_by_kind(
                stored, aviso, request, sent_column="confirmation_email_sent_at",
            )
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("No se ha podido enviar el aviso de booking %s: %s", booking_id, exc)
            _mark_booking_email_result(booking_id, status="failed", error=str(exc))
            _record_booking_audit(
                booking_id, cliente_id, "booking_email_failed",
                {"kind": "confirmed", "error": str(exc)},
            )
        stored = _get_booking_row_by_id(booking_id) or stored
    return stored


async def _cancel_booking_core(
    booking_row: sqlite3.Row,
    *,
    source: str,
    reason: str = "",
    request: Optional[Request] = None,
    audit_extra: Optional[Dict[str, Any]] = None,
) -> sqlite3.Row:
    """Cancela una cita (idempotente). Reutilizable por portal, voz, web publica y chat.

    Devuelve la fila actualizada. No lanza si ya estaba cancelada.
    """
    booking_id = booking_row["id"]
    if booking_row["status"] == "cancelled":
        return booking_row
    if booking_row["status"] == "completed":
        raise HTTPException(status_code=409, detail="Esa cita ya se ha realizado y no se puede cancelar.")
    if booking_row["status"] == "no_show":
        raise HTTPException(status_code=409, detail="Esa cita esta marcada como no asistida y no se puede cancelar.")
    cancel_reason = textnorm._sanitize_text(reason, allow_multiline=True)
    await _cancel_provider_booking(booking_row)
    _update_booking_record(
        booking_id,
        status="cancelled",
        cancelled_at=timeutils._utc_now_iso(),
        provider_status="cancelled",
    )
    _record_booking_audit(
        booking_id,
        booking_row["cliente_id"],
        "booking_cancelled",
        {
            "source": source,
            # Solo para el registro del negocio: al cliente no se le manda.
            "reason": cancel_reason,
            **(audit_extra or {}),
        },
    )
    # Aplica automaticamente la politica de cancelación (penalizacion/reembolso)
    # sobre el pago ya autorizado. No bloquea la cancelación si algo falla.
    try:
        apply_cancellation_policy(booking_row, kind="cancel", actor_source=source)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Politica de cancelación fallo %s: %s", booking_id, exc)
    refreshed = _load_booking_or_404(booking_id)
    crm._crm_upsert_contact(
        refreshed["cliente_id"], name=refreshed["nombre"], email=refreshed["email"],
        phone=refreshed["telefono"] or "", source=source, status="interesado",
        entity_type="booking", entity_id=refreshed["id"],
    )
    try:
        await _send_booking_reminder_by_kind(refreshed, "cancelled", request)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("No se pudo enviar aviso de cancelación %s: %s", booking_id, exc)
    return refreshed


_BOOKING_MANAGE_TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>__PAGE_TITLE__</title>
  <link rel="icon" type="image/png" href="__FAVICON__" />
  <meta name="robots" content="noindex,nofollow" />
  <style>
    :root {
      --marca: __BRAND__;
      --marca-ink: __BRAND_INK__;
      --marca-suave: __BRAND_SOFT__;
      --tinta: #16181D;
      --tinta-suave: #5E6470;
      --linea: #E4E6EC;
      --fondo: #F6F7F9;
      --tarjeta: #FFFFFF;
      --peligro: #C0392B;
      --peligro-suave: #FCEEEC;
      --ok: #2E7D53;
      --radio: 16px;
      --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      background: var(--fondo);
      color: var(--tinta);
      font-family: var(--sans);
      font-size: 16px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
      padding: 0 0 max(2rem, env(safe-area-inset-bottom));
    }
    .wrap { max-width: 34rem; margin: 0 auto; padding: 0 1rem; }

    /* --- cabecera de marca --- */
    .marca-bar { background: var(--marca); color: var(--marca-ink); padding: 1.5rem 0 1.6rem; }
    .marca-in { display: flex; align-items: center; gap: 0.85rem; }
    .marca-logo {
      width: 46px; height: 46px; border-radius: 50%; flex: none;
      background: rgba(255,255,255,.16); display: grid; place-items: center;
      font-weight: 800; font-size: 1.05rem; letter-spacing: .02em; overflow: hidden;
    }
    .marca-logo img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .marca-nombre { font-weight: 700; font-size: 1.05rem; line-height: 1.2; }
    .marca-sub { font-size: .82rem; opacity: .82; }

    /* --- tarjeta de la cita --- */
    .cita {
      background: var(--tarjeta); border-radius: var(--radio); margin-top: -0.9rem;
      box-shadow: 0 8px 28px rgba(20,24,35,.09); padding: 1.25rem 1.15rem 1.1rem;
    }
    .estado {
      display: inline-flex; align-items: center; gap: .4rem; font-size: .74rem; font-weight: 800;
      letter-spacing: .06em; text-transform: uppercase; padding: .3rem .7rem; border-radius: 999px;
      background: var(--marca-suave); color: var(--marca);
    }
    .estado.cancelada { background: var(--peligro-suave); color: var(--peligro); }
    .estado.hecha { background: #EAF4EE; color: var(--ok); }
    .cita h1 { font-size: 1.55rem; line-height: 1.15; margin: .7rem 0 .15rem; text-wrap: balance; }
    .cita .hora { font-size: 1.05rem; color: var(--tinta-suave); margin: 0 0 1rem; }
    .datos { display: grid; gap: .55rem; border-top: 1px solid var(--linea); padding-top: .9rem; }
    .dato { display: flex; gap: .8rem; align-items: baseline; font-size: .95rem; }
    .dato .k { color: var(--tinta-suave); min-width: 5.6rem; flex: none; font-size: .88rem; }
    .dato .v { font-weight: 600; }

    /* --- acciones --- */
    h2.tit { font-size: .78rem; letter-spacing: .1em; text-transform: uppercase; color: var(--tinta-suave); margin: 1.8rem 0 .7rem; }
    .acciones { display: grid; gap: .6rem; }
    .accion {
      display: flex; align-items: center; gap: .8rem; width: 100%; text-align: left;
      background: var(--tarjeta); border: 1.5px solid var(--linea); border-radius: 14px;
      padding: .95rem 1rem; font: inherit; color: var(--tinta); cursor: pointer;
      min-height: 56px; transition: border-color .15s ease, background .15s ease;
    }
    .accion:hover { border-color: var(--marca); }
    .accion.active { border-color: var(--marca); background: var(--marca-suave); }
    .accion .ico { width: 34px; height: 34px; border-radius: 10px; background: var(--marca-suave); color: var(--marca); display: grid; place-items: center; flex: none; }
    .accion .ico svg { width: 18px; height: 18px; }
    .accion b { display: block; font-size: .97rem; }
    .accion span { display: block; font-size: .82rem; color: var(--tinta-suave); }
    .accion.peligro .ico { background: var(--peligro-suave); color: var(--peligro); }
    .accion.peligro:hover, .accion.peligro.active { border-color: var(--peligro); background: var(--peligro-suave); }

    /* --- paneles --- */
    .section-card { display: none; background: var(--tarjeta); border: 1px solid var(--linea); border-radius: var(--radio); padding: 1.1rem 1rem; margin-top: .9rem; }
    .section-card.active { display: block; }
    .section-card h3 { margin: 0 0 .2rem; font-size: 1.02rem; }
    .muted { color: var(--tinta-suave); font-size: .88rem; margin: 0 0 .9rem; }
    label { display: block; font-size: .82rem; color: var(--tinta-suave); font-weight: 600; margin-bottom: .75rem; }
    input, select, textarea {
      display: block; width: 100%; margin-top: .3rem; font: inherit; font-size: 1rem; color: var(--tinta);
      background: #fff; border: 1.5px solid var(--linea); border-radius: 11px; padding: .7rem .8rem;
      min-height: 46px;
    }
    input:focus, select:focus, textarea:focus { outline: none; border-color: var(--marca); box-shadow: 0 0 0 3px var(--marca-suave); }
    input[readonly] { background: var(--fondo); color: var(--tinta-suave); }
    textarea { min-height: 88px; resize: vertical; }
    .notice { font-size: .86rem; color: var(--tinta-suave); background: var(--fondo); border-radius: 10px; padding: .6rem .75rem; }
    .slot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(84px, 1fr)); gap: .5rem; margin-top: .7rem; }

    /* --- botones --- */
    .botonera { display: grid; gap: .6rem; margin-top: 1.1rem; }
    button.primary, button.danger, .button-link {
      font: inherit; font-weight: 700; font-size: 1rem; border: 0; border-radius: 12px;
      padding: .95rem 1rem; min-height: 52px; cursor: pointer; text-align: center; text-decoration: none;
    }
    button.primary { background: var(--marca); color: var(--marca-ink); }
    button.danger { background: var(--peligro); color: #fff; }
    .button-link { display: block; background: var(--tarjeta); border: 1.5px solid var(--linea); color: var(--tinta); }
    button.primary:active, button.danger:active { transform: translateY(1px); }
    .hidden { display: none !important; }

    .status { margin-top: .9rem; font-size: .92rem; text-align: center; color: var(--tinta-suave); min-height: 1.2rem; }
    .contacto { margin-top: 1.6rem; text-align: center; font-size: .88rem; color: var(--tinta-suave); }
    .contacto a { color: var(--marca); font-weight: 600; text-decoration: none; }
    .pie { margin-top: 1.4rem; text-align: center; font-size: .74rem; color: #9AA0AC; }
    @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
  </style>
</head>
<body>
  <div class="marca-bar">
    <div class="wrap marca-in">
      <div class="marca-logo">__LOGO__</div>
      <div>
        <div class="marca-nombre">__EMPRESA__</div>
        <div class="marca-sub">Tu cita</div>
      </div>
    </div>
  </div>

  <div class="wrap">
    <div class="cita">
      <span class="estado __ESTADO_CLASE__">__ESTADO_TXT__</span>
      <h1 id="cita-fecha">__FECHA_LARGA__</h1>
      <p class="hora" id="cita-hora">__HORA_TXT__</p>
      <div class="datos">
        <div class="dato"><span class="k">Servicio</span><span class="v">__SERVICIO__</span></div>
        __PROFESIONAL_HTML__
        <div class="dato"><span class="k">A nombre de</span><span class="v">__NOMBRE__</span></div>
      </div>
    </div>

    <div class="action-chooser">
      <h2 class="tit">¿Qué quieres hacer?</h2>
      <div class="acciones">
        <button class="accion" type="button" id="confirm-btn" style="display:none">
          <span class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4L19 7"/></svg></span>
          <span><b>Confirmar la cita</b><span>Dinos que vas a venir</span></span>
        </button>
        <button class="accion" type="button" data-panel-target="schedule-section">
          <span class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/></svg></span>
          <span><b>Cambiar día u hora</b><span>Elige otro hueco disponible</span></span>
        </button>
        <button class="accion" type="button" data-panel-target="details-section">
          <span class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"/><path d="M4 20c0-3.3 3.6-6 8-6s8 2.7 8 6"/></svg></span>
          <span><b>Cambiar mis datos</b><span>Nombre, teléfono, servicio o notas</span></span>
        </button>
        <button class="accion peligro" type="button" data-panel-target="cancel-section">
          <span class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg></span>
          <span><b>Cancelar la cita</b><span>__CANCEL_SUB__</span></span>
        </button>
      </div>
    </div>

    <div id="reschedule-panel">
      <div class="section-card" id="schedule-section">
        <h3>Cambiar día u hora</h3>
        <p class="muted">Elige una fecha y te mostramos los huecos libres.</p>
        <label>Fecha<input id="reschedule-date" type="date" /></label>
        <label>Hora<select id="reschedule-time"></select></label>
        <div id="slot-status" class="notice">Selecciona una fecha para ver los horarios.</div>
        <div id="slot-grid" class="slot-grid"></div>
      </div>

      <div class="section-card" id="details-section">
        <h3>Cambiar mis datos</h3>
        <p class="muted">El email no se puede cambiar desde aquí, por seguridad.</p>
        <label>Nombre<input id="booking-name" type="text" maxlength="80" /></label>
        <label>Email<input id="booking-email" type="email" maxlength="120" readonly /></label>
        <label>Teléfono<input id="booking-phone" type="tel" inputmode="tel" maxlength="30" /></label>
        <label>Notas<textarea id="booking-notes" maxlength="500" placeholder="¿Algo que debamos saber?"></textarea></label>
        <p class="muted" style="margin:.2rem 0 0;">El servicio y el profesional no se cambian desde aquí. Si necesitas otro, escríbenos.</p>
      </div>

      <div class="section-card" id="cancel-section">
        <h3>Cancelar la cita</h3>
        <p class="muted">__CANCEL_COPY__</p>
      </div>

      <div class="botonera">
        <button class="primary" id="save-btn" type="button">Guardar cambios</button>
        <button class="danger hidden" id="cancel-btn" type="button">Sí, cancelar la cita</button>
        __BACK_BUTTON__
      </div>
    </div>

    <div class="status" id="status"></div>
    __CONTACTO_HTML__
    <p class="pie">__PIE__</p>
  </div>

  <script>
    const BOOKING = __BOOKING_JSON__;
    const statusEl = document.getElementById("status");
    const actionChooser = document.querySelector(".action-chooser");
    const reschedulePanel = document.getElementById("reschedule-panel");
    const saveBtn = document.getElementById("save-btn");
    const cancelBtn = document.getElementById("cancel-btn");
    const slotStatus = document.getElementById("slot-status");
    const slotGrid = document.getElementById("slot-grid");
    const sectionCards = Array.from(document.querySelectorAll(".section-card"));
    const chooserButtons = Array.from(document.querySelectorAll("[data-panel-target]"));

    if (BOOKING.estado === "cancelled" || BOOKING.estado === "completed" || BOOKING.estado === "no_show") {
      if (actionChooser) actionChooser.style.display = "none";
      reschedulePanel.style.display = "none";
      statusEl.textContent = BOOKING.estado === "cancelled"
        ? "Esta cita está cancelada y ya no admite cambios desde este enlace."
        : "Esta cita ya está cerrada y no admite cambios desde este enlace.";
    }

    function openPanel(panelId) {
      sectionCards.forEach((section) => section.classList.toggle("active", section.id === panelId));
      chooserButtons.forEach((button) => button.classList.toggle("active", button.dataset.panelTarget === panelId));
      if (saveBtn) saveBtn.classList.toggle("hidden", panelId === "cancel-section");
      if (cancelBtn) cancelBtn.classList.toggle("hidden", panelId !== "cancel-section");
    }
    chooserButtons.forEach((button) => {
      button.addEventListener("click", () => {
        openPanel(button.dataset.panelTarget || "details-section");
        document.getElementById(button.dataset.panelTarget)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    });

    document.getElementById("booking-name").value = BOOKING.nombre || "";
    document.getElementById("booking-email").value = BOOKING.email || "";
    document.getElementById("booking-phone").value = BOOKING.telefono || "";
    document.getElementById("booking-notes").value = BOOKING.notas || "";
    document.getElementById("reschedule-date").value = BOOKING.fecha;
    document.getElementById("reschedule-time").value = BOOKING.hora;

    function setTimeOptions(slots, fecha) {
      const timeSelect = document.getElementById("reschedule-time");
      const previousValue = timeSelect.value || (fecha === BOOKING.fecha ? BOOKING.hora : "");
      const available = slots
        .filter((slot) => slot.disponible || (fecha === BOOKING.fecha && slot.hora === BOOKING.hora))
        .map((slot) => String(slot.hora || ""))
        .filter(Boolean);
      if (fecha === BOOKING.fecha && BOOKING.hora && !available.includes(BOOKING.hora)) {
        available.unshift(BOOKING.hora);
      }
      timeSelect.innerHTML = "";
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = available.length ? "Elige una hora" : "Sin horarios disponibles";
      placeholder.disabled = true;
      placeholder.selected = !available.includes(previousValue);
      timeSelect.appendChild(placeholder);
      available.forEach((hora) => {
        const option = document.createElement("option");
        option.value = hora;
        option.textContent = hora;
        option.selected = hora === previousValue;
        timeSelect.appendChild(option);
      });
      timeSelect.disabled = !available.length;
      if (!available.includes(previousValue)) timeSelect.value = "";
      renderSlotChips(available, timeSelect.value);
      return available.length;
    }

    // Los huecos, ademas del desplegable, como botones grandes: en el movil un
    // <select> con veinte horas es incomodo.
    function renderSlotChips(horas, seleccionada) {
      slotGrid.innerHTML = "";
      horas.forEach((hora) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.textContent = hora;
        chip.className = "accion";
        chip.style.cssText = "min-height:46px;justify-content:center;padding:.6rem .4rem;font-weight:700;";
        if (hora === seleccionada) chip.classList.add("active");
        chip.addEventListener("click", () => {
          document.getElementById("reschedule-time").value = hora;
          renderSlotChips(horas, hora);
        });
        slotGrid.appendChild(chip);
      });
    }

    async function loadSlots() {
      const fecha = document.getElementById("reschedule-date").value;
      slotGrid.innerHTML = "";
      if (!fecha) { slotStatus.textContent = "Selecciona una fecha para ver los horarios."; return; }
      slotStatus.textContent = "Buscando horarios...";
      try {
        // Con el profesional Y el servicio: los huecos son los SUYOS y con la
        // duracion real de la cita (un servicio de tres horas no cabe en
        // cualquier tramo libre).
        const response = await fetch("/disponibilidad?cliente_id=" + encodeURIComponent(BOOKING.cliente_id)
          + "&employee_id=" + encodeURIComponent(BOOKING.employee_id || "")
          + "&servicio=" + encodeURIComponent(BOOKING.servicio || "")
          + "&fecha=" + encodeURIComponent(fecha), { headers: { "Accept": "application/json" } });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "No se pudo cargar la disponibilidad.");
        const slots = Array.isArray(data.slots) ? data.slots : [];
        const availableCount = setTimeOptions(slots, fecha);
        slotStatus.textContent = availableCount
          ? (availableCount === 1 ? "1 horario disponible" : availableCount + " horarios disponibles")
          : "No hay horarios disponibles ese día.";
      } catch (error) {
        slotStatus.textContent = error.message;
      }
    }

    async function action(url, body) {
      statusEl.textContent = "Procesando...";
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.message || "No se pudo completar la accion.");
      statusEl.textContent = data.mensaje || "Listo.";
      window.setTimeout(() => window.location.reload(), 1200);
    }

    cancelBtn?.addEventListener("click", async () => {
      if (!window.confirm("¿Seguro que quieres cancelar esta cita?")) return;
      try { await action(window.location.pathname + "/cancel"); }
      catch (error) { statusEl.textContent = error.message; }
    });

    saveBtn?.addEventListener("click", async () => {
      const fecha = document.getElementById("reschedule-date").value;
      const hora = document.getElementById("reschedule-time").value;
      const scheduleSection = document.getElementById("schedule-section");
      const isScheduleOpen = scheduleSection && scheduleSection.classList.contains("active");
      const payload = {
        nombre: document.getElementById("booking-name").value.trim(),
        email: BOOKING.email || "",
        telefono: document.getElementById("booking-phone").value.trim(),
        servicio: BOOKING.servicio || "",
        employee_id: BOOKING.employee_id || "",
        fecha: isScheduleOpen ? fecha : BOOKING.fecha,
        hora: isScheduleOpen ? hora : BOOKING.hora,
        notas: document.getElementById("booking-notes").value.trim(),
      };
      if (isScheduleOpen && (!fecha || !hora)) { statusEl.textContent = "Elige una fecha y una hora."; return; }
      try { await action(window.location.pathname + "/update", payload); }
      catch (error) { statusEl.textContent = error.message; }
    });

    const confirmBtn = document.getElementById("confirm-btn");
    const puedeConfirmar = !BOOKING.confirmed_by_customer
      && ["confirmed", "pending_review"].indexOf(BOOKING.estado) >= 0;
    if (confirmBtn && puedeConfirmar) {
      confirmBtn.style.display = "";
      confirmBtn.addEventListener("click", async () => {
        try { await action(window.location.pathname.replace("/manage/", "/confirm/")); }
        catch (error) { statusEl.textContent = error.message; }
      });
    }

    document.getElementById("reschedule-date")?.addEventListener("change", loadSlots);
    openPanel("schedule-section");
    loadSlots();
  </script>
</body>
</html>
"""


def _brand_ink_for(color: str) -> str:
    """Blanco o negro sobre el color de marca, segun su luminancia. Sin esto, una
    marca clara deja ilegible el texto de la cabecera."""
    raw = str(color or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    try:
        r, g, b = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return "#FFFFFF"
    luminancia = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#16181D" if luminancia > 0.68 else "#FFFFFF"


def _booking_manage_page(booking: BookingDetailPublic, *, viewer: str = "customer") -> str:
    """Pagina publica de gestion de la cita, con la marca del negocio.

    Solo presentacion: endpoints (/cancel, /update), payload e identificadores del
    DOM son los mismos de antes, para no cambiar el comportamiento."""
    serialized = json.dumps(booking.model_dump(), ensure_ascii=False).replace("</", "<\\/")
    es_negocio = viewer == "client"

    try:
        config = clients._get_client_config(booking.cliente_id)
    except Exception:  # noqa: BLE001
        config = {}
    marca = str(config.get("color") or "").strip()
    if not re.match(r"^#[0-9A-Fa-f]{6}$", marca):
        marca = "#111111"
    empresa = escape(str(config.get("empresa") or booking.empresa or "").strip())
    logo_url = str(config.get("logo_url") or "").strip()
    if logo_url.startswith("http"):
        logo_html = '<img src="' + escape(logo_url) + '" alt="" />'
    else:
        icono = str(config.get("icono") or "").strip()
        if icono and not icono.isascii():
            inicial = icono[:2]
        else:
            inicial = next((c for c in str(config.get("empresa") or booking.empresa or "?") if c.isalnum()), "?").upper()
        logo_html = escape(inicial)

    estados = {
        "confirmed": ("Confirmada", ""),
        "pending_review": ("Sin confirmar", ""),
        "pending_payment": ("Pendiente de pago", ""),
        "cancelled": ("Cancelada", "cancelada"),
        "completed": ("Realizada", "hecha"),
        "no_show": ("No asististe", "cancelada"),
    }
    estado_txt, estado_clase = estados.get(booking.estado, ("Reservada", ""))

    try:
        fecha_larga = textnorm._format_date_es(textnorm._parse_date(booking.fecha).date())
    except Exception:  # noqa: BLE001
        fecha_larga = booking.fecha
    fecha_larga = fecha_larga[:1].upper() + fecha_larga[1:]

    duracion = int(booking.service_duration_minutes or 0)
    hora_txt = "A las " + str(booking.hora)
    if duracion:
        hora_txt += " \u00b7 " + str(duracion) + " min"
    if booking.service_price_label:
        hora_txt += " \u00b7 " + booking.service_price_label

    profesional_html = ""
    if booking.employee_name:
        profesional_html = (
            '<div class="dato"><span class="k">Profesional</span><span class="v">'
            + escape(booking.employee_name) + "</span></div>"
        )

    contacto = []
    if booking.contact_phone:
        tel = escape(booking.contact_phone)
        contacto.append('<a href="tel:' + tel.replace(" ", "") + '">' + tel + "</a>")
    if booking.contact_email:
        mail = escape(booking.contact_email)
        contacto.append('<a href="mailto:' + mail + '">' + mail + "</a>")
    contacto_html = ""
    if contacto:
        contacto_html = '<p class="contacto">\u00bfPrefieres hablarlo? ' + " \u00b7 ".join(contacto) + "</p>"

    cancel_copy = (
        "Confirma la cancelación si finalmente no se va a atender esta cita."
        if es_negocio
        else "Si prefieres otro d\u00eda, usa antes \u00abCambiar d\u00eda u hora\u00bb: as\u00ed no pierdes la cita."
    )
    reemplazos = [
        ("__PAGE_TITLE__", "Gestionar cita | Vantelia" if es_negocio else "Tu cita | " + empresa),
        ("__FAVICON__", escape(textnorm._brand_asset_public_path("favicon.png"))),
        ("__BRAND__", marca),
        ("__BRAND_INK__", _brand_ink_for(marca)),
        ("__BRAND_SOFT__", "color-mix(in srgb, " + marca + " 12%, #ffffff)"),
        ("__LOGO__", logo_html),
        ("__EMPRESA__", empresa),
        ("__ESTADO_TXT__", estado_txt),
        ("__ESTADO_CLASE__", estado_clase),
        ("__FECHA_LARGA__", escape(fecha_larga)),
        ("__HORA_TXT__", escape(hora_txt)),
        ("__SERVICIO__", escape(booking.servicio or "Cita")),
        ("__PROFESIONAL_HTML__", profesional_html),
        ("__NOMBRE__", escape(booking.nombre or "")),
        ("__CANCEL_SUB__", "Ya no la atender\u00e9is" if es_negocio else "Si al final no puedes venir"),
        ("__CANCEL_COPY__", cancel_copy),
        ("__BACK_BUTTON__", '<a class="button-link" href="/portal">Volver al panel</a>' if es_negocio else ""),
        ("__CONTACTO_HTML__", contacto_html),
        ("__PIE__", "Gestionado con Vantelia"),
        ("__BOOKING_JSON__", serialized),
    ]
    pagina = _BOOKING_MANAGE_TEMPLATE
    for token, valor in reemplazos:
        pagina = pagina.replace(token, valor)
    return pagina


async def _send_booking_email_by_kind(
    booking_row: sqlite3.Row,
    kind: str,
    request: Optional[Request] = None,
    *,
    sent_column: str = "",
    respect_enabled: bool = True,
) -> None:
    if kind == "confirmed" and booking_row["status"] == "pending_payment":
        _record_booking_audit(
            booking_row["id"],
            booking_row["cliente_id"],
            "booking_email_skipped",
            {"kind": kind, "reason": "pending_payment"},
        )
        return
    if respect_enabled:
        config = clients._get_client_config(booking_row["cliente_id"])
        if not _booking_email_enabled(config, kind):
            if sent_column:
                _mark_booking_email_result(
                    booking_row["id"],
                    status=f"disabled:{kind}",
                    sent_column=sent_column,
                    error="",
                )
            _record_booking_audit(
                booking_row["id"],
                booking_row["cliente_id"],
                "booking_email_skipped",
                {"kind": kind, "reason": "disabled"},
            )
            return
    _send_booking_email(booking_row, kind, request)
    _mark_booking_email_result(
        booking_row["id"],
        status=kind,
        sent_column=sent_column,
        error="",
    )
    _record_booking_audit(
        booking_row["id"],
        booking_row["cliente_id"],
        "booking_email_sent",
        {"kind": kind},
    )


async def _send_booking_reminder_by_kind(
    booking_row: sqlite3.Row,
    kind: str,
    request: Optional[Request] = None,
    *,
    sent_column: str = "",
    respect_enabled: bool = True,
    raise_on_failure: bool = True,
    channel_override: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """Envia el aviso de la cita por los canales efectivos del tenant para ``kind``.

    Devuelve ``{"sent": [...], "failed": {canal: error}, "skipped": {canal: motivo}}``
    para que quien llama (p. ej. el reenvio manual de confirmacion) sepa exactamente
    que se entrego. Los callers automaticos pueden ignorar el retorno. Cuando no se
    entrega por ningún canal y ``raise_on_failure`` es True (comportamiento historico
    de los flujos automaticos) se lanza ``RuntimeError``; con False se devuelve el
    resultado con los errores en ``failed`` para que el caller los muestre."""
    if kind == "confirmed" and booking_row["status"] == "pending_payment":
        # Decirle "tu cita ha quedado confirmada" a quien todavia tiene que pagar la
        # senal es mentirle. Ya recibe el resumen y el boton de pago; la confirmación
        # sale sola cuando el pago entra (notify_booking_paid).
        _record_booking_audit(
            booking_row["id"], booking_row["cliente_id"],
            "booking_email_skipped", {"kind": kind, "reason": "pending_payment"},
        )
        return {"sent": [], "failed": {}, "skipped": {"all": "pending_payment"}}
    if kind not in settings.DEFAULT_MESSAGE_TEMPLATE_CHANNELS:
        await _send_booking_email_by_kind(
            booking_row,
            kind,
            request,
            sent_column=sent_column,
            respect_enabled=respect_enabled,
        )
        return {"sent": ["email"], "failed": {}, "skipped": {}}

    config = clients._get_client_config(booking_row["cliente_id"])
    if respect_enabled and not _booking_email_enabled(config, kind):
        if sent_column:
            _mark_booking_email_result(
                booking_row["id"],
                status=f"disabled:{kind}",
                sent_column=sent_column,
                error="",
            )
        _record_booking_audit(
            booking_row["id"],
            booking_row["cliente_id"],
            "booking_email_skipped",
            {"kind": kind, "reason": "disabled"},
        )
        return {"sent": [], "failed": {}, "skipped": {"all": "disabled"}}

    channels = (
        {name: bool(channel_override.get(name)) for name in ("email", "whatsapp", "sms")}
        if channel_override is not None
        else agenda._effective_followup_channels(booking_row["cliente_id"]).get(
            kind, {"email": True, "whatsapp": False, "sms": False}
        )
    )
    channels = _channels_reaching_customer(booking_row, channels)
    availability = agenda._reminder_channel_availability(booking_row["cliente_id"])
    sent_channels: List[str] = []
    failed_channels: Dict[str, str] = {}
    skipped_channels: Dict[str, str] = {}
    followup_cfg = _follow_up_config(booking_row["cliente_id"])
    delivery_priority = followup_cfg.get("delivery_priority") or list(_FOLLOWUP_DELIVERY_CHANNELS)
    prefer_single_delivery = respect_enabled and channel_override is None

    if not any(bool(channels.get(name)) for name in _FOLLOWUP_DELIVERY_CHANNELS):
        if sent_column:
            _mark_booking_email_result(
                booking_row["id"],
                status=f"disabled:{kind}",
                sent_column=sent_column,
                error="",
            )
        _record_booking_audit(
            booking_row["id"],
            booking_row["cliente_id"],
            "booking_email_skipped",
            {"kind": kind, "reason": "no_channels"},
        )
        return {"sent": [], "failed": {}, "skipped": {"all": "no_channels"}}

    async def _attempt_channel(channel_name: str) -> None:
        if channel_name == "email":
            if not (booking_row["email"] or "").strip():
                skipped_channels["email"] = "La cita no tiene email."
                return
            try:
                _send_booking_email(booking_row, kind, request)
                sent_channels.append("email")
            except Exception as exc:  # noqa: BLE001
                failed_channels["email"] = str(exc)
            return

        if channel_name == "whatsapp":
            entregable, motivo = _whatsapp_deliverable_for_booking(booking_row)
            if not entregable:
                skipped_channels["whatsapp"] = motivo
                return
            try:
                if await _send_booking_whatsapp_reminder(booking_row, kind, request):
                    sent_channels.append("whatsapp")
                else:
                    failed_channels["whatsapp"] = "No se pudo entregar WhatsApp o falta teléfono válido."
            except Exception as exc:  # noqa: BLE001
                failed_channels["whatsapp"] = str(exc)
            return

        if channel_name == "sms":
            if not availability.get("sms", {}).get("available"):
                skipped_channels["sms"] = str(availability.get("sms", {}).get("reason", "No disponible."))
                return
            try:
                if await _send_booking_sms_reminder(booking_row, kind, request):
                    sent_channels.append("sms")
                else:
                    failed_channels["sms"] = "No se pudo entregar SMS o falta teléfono válido."
            except Exception as exc:  # noqa: BLE001
                failed_channels["sms"] = str(exc)

    if prefer_single_delivery:
        # En produccion los canales activos son una lista de respaldo, no envios
        # duplicados: se intenta el orden elegido y se para al primer canal entregado.
        for channel_name in delivery_priority:
            if not channels.get(channel_name):
                continue
            await _attempt_channel(channel_name)
            if sent_channels:
                for skipped_name in _FOLLOWUP_DELIVERY_CHANNELS:
                    if channels.get(skipped_name) and skipped_name not in sent_channels and skipped_name not in failed_channels and skipped_name not in skipped_channels:
                        skipped_channels[skipped_name] = f"Ya se envio por {sent_channels[0]}."
                break
    else:
        for channel_name in _FOLLOWUP_DELIVERY_CHANNELS:
            if channels.get(channel_name):
                await _attempt_channel(channel_name)

    if sent_channels or skipped_channels:
        status_value = kind if sent_channels == ["email"] else f"{kind}:{','.join(sent_channels or ['skipped'])}"
        if sent_column:
            _mark_booking_email_result(
                booking_row["id"],
                status=status_value,
                sent_column=sent_column,
                error="; ".join(f"{name}: {err}" for name, err in failed_channels.items()),
            )
        _record_booking_audit(
            booking_row["id"],
            booking_row["cliente_id"],
            "booking_email_sent",
            {
                "kind": kind,
                "channels": sent_channels,
                "skipped": skipped_channels,
                "failed": failed_channels,
            },
        )
        return {"sent": sent_channels, "failed": failed_channels, "skipped": skipped_channels}

    # No se entrego por ningún canal: deja rastro y, segun el caller, lanza o devuelve.
    _record_booking_audit(
        booking_row["id"],
        booking_row["cliente_id"],
        "booking_email_failed",
        {"kind": kind, "failed": failed_channels},
    )
    if raise_on_failure:
        raise RuntimeError(
            "No se ha podido enviar el aviso por ningún canal: "
            + "; ".join(f"{name}: {err}" for name, err in failed_channels.items())
        )
    return {"sent": [], "failed": failed_channels, "skipped": skipped_channels}


_REMINDER_CHANNEL_LABELS = {"email": "email", "whatsapp": "WhatsApp", "sms": "SMS"}


async def _resend_booking_confirmation(
    booking_row: sqlite3.Row, request: Optional[Request] = None, *, by_user: str = ""
) -> Dict[str, Any]:
    """Reenvio MANUAL de la confirmación de una cita (boton del panel).

    A diferencia del flujo automatico, valida por adelantado que haya un canal con
    datos de contacto y devuelve/lanza un error concreto (email ausente, correo sin
    configurar, etc.) para que el panel lo muestre. Registra ``confirmation_resent``
    solo cuando se entrega de verdad."""
    cliente_id = booking_row["cliente_id"]
    if booking_row["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="No se puede enviar la confirmación de una cita cancelada.")
    channels = agenda._effective_followup_channels(cliente_id).get(
        "confirmed", {"email": True, "whatsapp": False, "sms": False}
    )
    has_email = bool((booking_row["email"] or "").strip())
    phone_sms = _booking_customer_phone_for_channel(booking_row, "sms")
    phone_wa = _booking_customer_phone_for_channel(booking_row, "whatsapp")
    wants_email, wants_wa, wants_sms = (
        bool(channels.get("email")),
        bool(channels.get("whatsapp")),
        bool(channels.get("sms")),
    )
    if not (wants_email or wants_wa or wants_sms):
        raise HTTPException(
            status_code=409,
            detail="No hay ningún canal activo para la confirmación. Actívalo en Seguimiento.",
        )
    deliverable = (wants_email and has_email) or (wants_wa and phone_wa) or (wants_sms and phone_sms)
    if not deliverable:
        if wants_email and not (wants_wa or wants_sms):
            raise HTTPException(
                status_code=409,
                detail="Esta cita no tiene email. Anade un email al cliente o activa WhatsApp/SMS en Seguimiento.",
            )
        raise HTTPException(
            status_code=409,
            detail="No hay datos de contacto válidos para los canales activos (email/teléfono).",
        )
    result = await _send_booking_reminder_by_kind(
        booking_row, "confirmed", request, respect_enabled=False, raise_on_failure=False
    )
    if not result["sent"]:
        detail = "; ".join(f"{name}: {err}" for name, err in result["failed"].items())
        raise HTTPException(status_code=409, detail=detail or "No se pudo enviar la confirmación.")
    _record_booking_audit(
        booking_row["id"], cliente_id, "confirmation_resent",
        {"by": by_user, "channels": result["sent"]},
    )
    return result


def _confirmation_channels_label(channels: List[str]) -> str:
    return ", ".join(_REMINDER_CHANNEL_LABELS.get(c, c) for c in channels)


def _booking_due_for_reminder(row: sqlite3.Row, now_utc: datetime, hours_before: int) -> bool:
    start_at = timeutils._from_utc_iso(row["start_at"])
    if not start_at or row["status"] != "confirmed":
        return False
    lower_bound = now_utc + timedelta(hours=hours_before)
    # Banda tolerante a una pasada perdida del worker: cubre >= 2 intervalos para
    # que un run retrasado no salte el recordatorio. No se ensancha hacia abajo
    # (mantiene el anclaje ~24h, asi el texto "manana" sigue siendo correcto).
    grace_minutes = max(45, settings.REMINDER_RUN_INTERVAL_MINUTES * 2)
    upper_bound = lower_bound + timedelta(minutes=grace_minutes)
    return lower_bound <= start_at <= upper_bound


def _bookings_due_for_reminders(now_utc: datetime, *, limit: int = 5000) -> List[sqlite3.Row]:
    """Citas candidatas de Seguimiento (recordatorio 24h/2h Y llamada de confirmacion),
    acotadas por FECHA (no por volumen total): confirmadas en la franja de los
    proximos ~2 dias. El gate exacto de cada accion lo aplican despues
    ``_booking_due_for_reminder`` / ``_call_due_for_booking``.

    Sustituye al antiguo ``_list_booking_rows(limit=500)`` que, ordenado por fecha
    ASC, en tenants con historico grande gastaba el cupo en citas viejas y nunca
    alcanzaba las futuras -> 0 recordatorios y 0 llamadas. No filtra por
    recordatorio-pendiente para que una cita ya recordada siga siendo candidata a
    la llamada de escalado.
    """
    today = now_utc.date()
    date_from = (today - timedelta(days=1)).isoformat()
    date_to = (today + timedelta(days=2)).isoformat()
    with db._get_db_connection() as connection:
        return connection.execute(
            """
            SELECT * FROM bookings
            WHERE status = 'confirmed'
              AND booking_date >= ?
              AND booking_date <= ?
            ORDER BY booking_date ASC, booking_time ASC
            LIMIT ?
            """,
            (date_from, date_to, limit),
        ).fetchall()


def _call_due_for_booking(row: sqlite3.Row, now_utc: datetime, hours_before: int) -> bool:
    """True si la cita entra en la ventana de la llamada de confirmacion (escalado):
    confirmada, futura y a <= ``hours_before`` (pero aun a mas de la ventana del 2h,
    para no llamar pegado a la cita). El "solo si no confirmada" lo decide el caller."""
    start_at = timeutils._from_utc_iso(row["start_at"])
    if not start_at or row["status"] != "confirmed":
        return False
    hours_until = (start_at - now_utc).total_seconds() / 3600.0
    floor = max(0, settings.REMINDER_2H_HOURS)
    return floor < hours_until <= hours_before


def _auto_complete_past_bookings() -> int:
    if settings.BOOKING_AUTO_COMPLETE_HOURS < 0:
        return 0

    threshold = (timeutils._utc_now() - timedelta(hours=settings.BOOKING_AUTO_COMPLETE_HOURS)).isoformat().replace("+00:00", "Z")
    completed = 0
    with db._get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, cliente_id
            FROM bookings
            WHERE status IN ('confirmed', 'pending_review')
              AND end_at <> ''
              AND end_at <= ?
            """,
            (threshold,),
        ).fetchall()
        for row in rows:
            connection.execute(
                "UPDATE bookings SET status = 'completed', completed_source = 'auto' WHERE id = ?",
                (row["id"],),
            )
            connection.execute(
                """
                INSERT INTO booking_audit (booking_id, cliente_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["cliente_id"],
                    "booking_completed",
                    json.dumps({"source": "automation"}, ensure_ascii=False),
                    timeutils._utc_now_iso(),
                ),
            )
            completed += 1
        connection.commit()
    for row in rows:
        booking = _get_booking_row_by_id(row["id"])
        if booking:
            crm._crm_upsert_contact(
                booking["cliente_id"], name=booking["nombre"], email=booking["email"],
                phone=booking["telefono"] or "", source="automation", status="cliente",
                entity_type="booking", entity_id=booking["id"],
            )
    return completed


def _auto_confirm_pending_bookings() -> int:
    confirmed_at = timeutils._utc_now_iso()
    confirmed = 0
    with db._get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, cliente_id
            FROM bookings
            WHERE status = 'pending_review'
              AND (end_at = '' OR end_at > ?)
            """,
            (confirmed_at,),
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                UPDATE bookings
                SET status = 'confirmed',
                    confirmed_at = CASE WHEN confirmed_at = '' THEN ? ELSE confirmed_at END
                WHERE id = ?
                """,
                (confirmed_at, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO booking_audit (booking_id, cliente_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["cliente_id"],
                    "booking_confirmed",
                    json.dumps({"source": "automation", "reason": "auto_confirm_pending_review"}, ensure_ascii=False),
                    confirmed_at,
                ),
            )
            confirmed += 1
        connection.commit()
    return confirmed


def _followup_global_channels(cliente_id: str) -> Dict[str, bool]:
    """Canales GLOBALES del Seguimiento (email/whatsapp/sms) aplicados por igual a TODOS
    los avisos, confirmaciones y la petición de reseña. Es la fuente unica que el negocio
    edita en una sola tira de canales (no por aviso).

    Por compatibilidad se sigue persistiendo en ``booking.message_template_channels`` (un
    valor identico por cada kind, escrito en abanico desde el PUT del Seguimiento), asi el
    motor de envio (``agenda._effective_followup_channels``) no cambia. Aqui leemos la union
    de los avisos de la escalera: si algun canal esta activo en alguno, lo damos por global.
    Todos a false = no se envia ningun recordatorio ni confirmacion (comportamiento querido)."""
    eff = agenda._effective_followup_channels(cliente_id)
    out = {"email": False, "whatsapp": False, "sms": False}
    for kind in ("confirmed", "reminder_24h", "reminder_2h"):
        chs = eff.get(kind, {}) or {}
        for name in out:
            if chs.get(name):
                out[name] = True
    return out


def _follow_up_config(cliente_id: str) -> Dict[str, Any]:
    """Config canonica del flujo de Seguimiento del tenant. Lee de config['reminders']
    (clave historica) y resuelve los campos nuevos con defaults conservadores.
    ``call_fallback`` se mantiene como alias de lectura/escritura de ``call_enabled``."""
    cfg = (appstate.CONFIG_CLIENTES.get(cliente_id) or {}).get("reminders") or {}
    try:
        cap = int(cfg.get("daily_call_cap") or 30)
    except (TypeError, ValueError):
        cap = 30
    try:
        call_hours = int(cfg.get("call_hours_before") or 5)
    except (TypeError, ValueError):
        call_hours = 5
    # call_enabled es el nombre nuevo; call_fallback el historico. Si el tenant nunca
    # lo guardo, default inteligente: ON solo si es Business CON numero de voz listo
    # (sin numero la llamada nunca se coloca, asi que es inocuo).
    if "call_enabled" in cfg or "call_fallback" in cfg:
        call_enabled = bool(cfg.get("call_enabled", cfg.get("call_fallback", False)))
    else:
        voice_ready = bool(clients._plan_feature(cliente_id, "voice_enabled")) and bool(
            (appstate.CONFIG_CLIENTES.get(cliente_id) or {}).get("voice", {}).get("twilio_phone_number")
        )
        call_enabled = voice_ready
    # Canales globales del Seguimiento (una sola tira para todos los avisos).
    channels = _followup_global_channels(cliente_id)
    # Verificacion por codigo (OTP de voz): on/off propio. Compat: si el tenant nunca guardo
    # el flag pero tenia canales OTP, lo inferimos de "habia algun canal activo".
    if "voice_otp_enabled" in cfg:
        voice_otp_enabled = bool(cfg.get("voice_otp_enabled"))
    else:
        legacy_otp = cfg.get("voice_otp_channels")
        voice_otp_enabled = bool(any((legacy_otp or {}).values())) if isinstance(legacy_otp, dict) else True
    # El codigo se entrega por los canales globales (no hay seleccion propia). Apagar el OTP
    # equivale a no tener canales: cae a verificacion por teléfono/email en su lugar.
    voice_otp_channels = dict(channels) if voice_otp_enabled else {"email": False, "whatsapp": False, "sms": False}
    return {
        "call_enabled": call_enabled,
        "call_fallback": call_enabled,  # alias de compat (lectura)
        "call_hours_before": max(1, min(24, call_hours)),
        "quiet_start": str(cfg.get("quiet_start") or "21:00"),
        "quiet_end": str(cfg.get("quiet_end") or "09:00"),
        "daily_call_cap": max(0, min(500, cap)),
        "email_confirm_button": bool(cfg.get("email_confirm_button", True)),
        "suppress_2h_if_confirmed": bool(cfg.get("suppress_2h_if_confirmed", True)),
        "delivery_priority": _normalize_followup_delivery_priority(cfg.get("delivery_priority")),
        "channels": channels,
        "voice_otp_enabled": voice_otp_enabled,
        # Compat para voice.py: derivado de los canales globales + el on/off del OTP.
        "voice_otp_channels": voice_otp_channels,
    }


def _reminders_config(cliente_id: str) -> Dict[str, Any]:
    """Compat: shape historico (call_fallback, quiet_start/end, daily_call_cap)."""
    fu = _follow_up_config(cliente_id)
    return {
        "call_fallback": fu["call_fallback"],
        "quiet_start": fu["quiet_start"],
        "quiet_end": fu["quiet_end"],
        "daily_call_cap": fu["daily_call_cap"],
    }


# Pasos temporizados de la escalera de avisos. Los canales son GLOBALES (una sola tira),
# asi que cada paso solo expone su on/off; la llamada IA es un canal propio (voz).
_FOLLOW_UP_STEP_DEFS = [
    ("confirmed", "message", "Confirmación de la cita", "Al reservar", 0,
     "Se envia al instante cuando el cliente reserva."),
    ("reminder_24h", "message", "Recordatorio 24 h", "24 h antes", 24,
     "Recordatorio con opción de confirmar o cancelar."),
    ("call", "call", "Llamada de confirmación IA", "", 0,
     "Solo si el cliente aun no ha confirmado por otros canales."),
    ("reminder_2h", "message", "Recordatorio 2 h", "2 h antes", 2,
     "Último aviso antes de la cita."),
]


def _follow_up_overview_dict(cliente_id: str) -> Dict[str, Any]:
    """Estado completo del Seguimiento para el portal: config + capacidades por plan +
    canales GLOBALES + pasos (cada uno con su on/off). Fuente de verdad backend.

    Modelo: una sola tira de canales (email/whatsapp/sms) que vale para todos los avisos,
    confirmaciones y la resena. Cada paso solo se puede encender/apagar; si no hay ningun
    canal global activo no se envia nada. La llamada IA es un paso aparte (canal de voz)."""
    fu = _follow_up_config(cliente_id)
    contacto = (appstate.CONFIG_CLIENTES.get(cliente_id) or {}).get("contacto", {}) or {}
    plan = clients._client_plan(cliente_id)
    plan_label = settings.PLAN_LIMITS.get(plan, {}).get("label", plan.title())
    avail = agenda._reminder_channel_availability(cliente_id)
    wa_plan = bool(clients._plan_feature(cliente_id, "whatsapp_enabled"))
    voice_plan = bool(clients._plan_feature(cliente_id, "voice_enabled"))
    sms_plan = bool(clients._plan_feature(cliente_id, "sms_enabled"))
    wa_available = bool(avail["whatsapp"]["available"])
    sms_available = bool(avail["sms"]["available"])
    voice_number = bool((appstate.CONFIG_CLIENTES.get(cliente_id) or {}).get("voice", {}).get("twilio_phone_number"))
    voice_available = voice_plan and voice_number
    voice_reason = "Disponible." if voice_available else ("Requiere plan Business." if not voice_plan else "Conecta un número en Asistente de voz.")

    booking_cfg = clients._get_client_config(cliente_id).get("booking", {}) or {}
    msg_enabled = textnorm._normalize_message_template_enabled(
        booking_cfg.get("message_template_enabled", {}), booking_cfg.get("message_templates", {})
    )

    # Canales GLOBALES: una sola tira para todos los avisos. ``active`` = encendido por el
    # negocio y disponible en su plan. ``recommended`` sugiere WhatsApp si lo tiene listo.
    g = fu["channels"]
    global_channels = [
        {"channel": "email", "label": "Email", "active": bool(g.get("email")),
         "available": True, "locked": False, "recommended": False, "plan_needed": "", "reason": "Disponible."},
        {"channel": "whatsapp", "label": "WhatsApp", "active": bool(g.get("whatsapp")) and wa_available,
         "available": wa_available, "locked": not wa_plan, "plan_needed": "" if wa_plan else "Pro",
         "recommended": wa_available and not bool(g.get("whatsapp")), "reason": avail["whatsapp"]["reason"]},
        {"channel": "sms", "label": "SMS", "active": bool(g.get("sms")) and sms_available,
         "available": sms_available, "locked": not sms_plan, "plan_needed": "" if sms_plan else "Business",
         "recommended": False, "reason": "Requiere plan Business." if not sms_plan else avail["sms"]["reason"]},
    ]
    any_global_active = any(c["active"] for c in global_channels)

    steps: List[Dict[str, Any]] = []
    for key, kind, label, when, offset, note in _FOLLOW_UP_STEP_DEFS:
        if kind == "call":
            when = f"{fu['call_hours_before']} h antes"
            offset = int(fu["call_hours_before"])
            enabled = bool(fu["call_enabled"])
            steps.append({
                "key": key, "kind": "call", "label": label, "when": when, "offset_hours": offset,
                "note": note, "enabled": enabled, "active": enabled and voice_available,
                "available": voice_available, "locked": not voice_plan,
                "plan_needed": "" if voice_plan else "Business", "reason": voice_reason,
                "channels": [{
                    "channel": "call", "label": "Llamada IA", "active": enabled and voice_available,
                    "available": voice_available, "locked": not voice_plan,
                    "plan_needed": "" if voice_plan else "Business", "recommended": False, "reason": voice_reason,
                }],
            })
        else:
            enabled = bool(msg_enabled.get(key, True))
            steps.append({
                "key": key, "kind": "message", "label": label, "when": when, "offset_hours": offset,
                "note": note, "enabled": enabled, "active": enabled and any_global_active, "channels": [],
            })

    # Paso final post-cita: petición de reseña (opt-in; usa los canales globales).
    rev = _reviews_config(cliente_id)
    rev_link_ok = _review_link_valid(rev["link"])
    rev_on = bool(rev["enabled"]) and rev_link_ok
    rev_delay = int(rev["delay_hours"])
    if rev_delay < 24:
        rev_when = f"{rev_delay} h después"
    else:
        rev_days = rev_delay // 24
        rev_when = f"{rev_days} día{'s' if rev_days > 1 else ''} después"
    steps.append({
        "key": "review", "kind": "review", "label": "Pide una reseña", "when": rev_when, "offset_hours": 0,
        "channels": [], "active": rev_on and any_global_active,
        "note": "Cuando la cita se completa, invita al cliente a dejarte una reseña en Google o donde elijas.",
        "enabled": bool(rev["enabled"]), "needs_setup": not rev_link_ok,
    })

    # Verificacion de identidad por codigo (OTP) al cambiar/cancelar por voz. Solo con plan
    # de voz. Usa los canales globales para entregar el codigo; su on/off es propio.
    if voice_plan:
        otp_enabled = bool(fu["voice_otp_enabled"])
        steps.append({
            "key": "voice_otp", "kind": "otp", "label": "Verificación por código (voz)",
            "when": "Al cambiar o cancelar", "offset_hours": 0, "channels": [],
            "note": ("Antes de cambiar o cancelar una cita por voz, el asistente envía al cliente un código "
                     "de 4 dígitos por los canales activos y le pide que lo lea. Apágalo para verificar por "
                     "teléfono o email en su lugar."),
            "enabled": otp_enabled, "active": otp_enabled and voice_available and any_global_active,
            "available": voice_available, "locked": not voice_plan,
        })

    return {
        "plan": plan, "plan_label": plan_label,
        "whatsapp_available": wa_available, "voice_available": voice_available,
        "channels": global_channels,
        "channel_availability": {
            "email": True, "whatsapp": wa_available, "sms": sms_available, "voice": voice_available,
            "whatsapp_reason": avail["whatsapp"]["reason"], "sms_reason": avail["sms"]["reason"],
            "voice_reason": voice_reason,
        },
        "call_enabled": fu["call_enabled"], "call_hours_before": fu["call_hours_before"],
        "quiet_start": fu["quiet_start"], "quiet_end": fu["quiet_end"],
        "daily_call_cap": fu["daily_call_cap"],
        "email_confirm_button": fu["email_confirm_button"],
        "suppress_2h_if_confirmed": fu["suppress_2h_if_confirmed"],
        "voice_otp_enabled": fu["voice_otp_enabled"],
        "delivery_priority": fu["delivery_priority"],
        "steps": steps,
        "default_test_email": str(contacto.get("email", "") or ""),
        "default_test_phone": str(contacto.get("telefono", "") or ""),
    }


# ---------------------------------------------------------------------------
# Probar el Seguimiento de verdad (botones de test de cada fase)
# ---------------------------------------------------------------------------


class _EphemeralBookingRow:
    """Cita en memoria para PROBAR una fase del Seguimiento sin tocar la agenda.

    Imita el acceso por nombre de columna de ``sqlite3.Row`` (devuelve '' si falta),
    asi el envio real (plantillas, canales, SMTP/WhatsApp/SMS/voz) corre igual que en
    produccion pero sin crear la cita, sin CRM y sin recordatorios persistidos."""

    def __init__(self, data: Dict[str, Any]):
        self._d = data

    def __getitem__(self, key: str) -> Any:
        return self._d.get(key, "")

    def get(self, key: str, default: Any = None) -> Any:
        return self._d.get(key, default)

    def keys(self):  # noqa: D401
        return self._d.keys()


def _format_test_channel_results(
    active: Dict[str, Any],
    sent: List[str],
    failed: Dict[str, str],
    skipped: Dict[str, str],
) -> List[Dict[str, str]]:
    """Resultado por canal de una prueba. Siempre incluye los 3 canales (email,
    WhatsApp, SMS): los activos en la fase se intentan (sent/failed/skipped) y los
    inactivos se reportan como ``inactive`` para que el negocio vea por que no salio."""
    labels = {"email": "Email", "whatsapp": "WhatsApp", "sms": "SMS"}
    out: List[Dict[str, str]] = []
    for ch in ("email", "whatsapp", "sms"):
        if not active.get(ch):
            out.append({
                "channel": ch, "label": labels[ch], "status": "inactive",
                "detail": "No esta activo en esta fase. Actívalo en la escalera y pulsa Guardar para enviarlo.",
            })
        elif ch in sent:
            out.append({"channel": ch, "label": labels[ch], "status": "sent", "detail": "Enviado correctamente."})
        elif ch in failed:
            out.append({"channel": ch, "label": labels[ch], "status": "failed", "detail": failed[ch]})
        elif ch in skipped:
            out.append({"channel": ch, "label": labels[ch], "status": "skipped", "detail": skipped[ch]})
        else:
            out.append({"channel": ch, "label": labels[ch], "status": "skipped", "detail": "No se intento."})
    return out


async def _run_follow_up_test(
    cliente_id: str, step: str, request: Optional[Request] = None, *, email: str = "", phone: str = "",
    channels: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """Ejecuta REALMENTE una fase del Seguimiento contra un destinatario de prueba.

    Usa una cita efimera (no se guarda nada en la agenda). Devuelve, por canal, si se
    entrego, fallo (con el motivo concreto) u omitio (no configurado / no disponible en
    el plan), para que el negocio compruebe su configuracion sin esperar a una cita real."""
    valid = {"confirmed", "reminder_24h", "reminder_2h", "call", "review", "voice_otp"}
    if step not in valid:
        raise HTTPException(status_code=400, detail="Fase de seguimiento desconocida.")
    config = clients._get_client_config(cliente_id)
    contacto = config.get("contacto", {}) or {}
    to_email = textnorm._sanitize_text(email or contacto.get("email", "") or "")
    to_phone = textnorm._sanitize_text(phone or contacto.get("telefono", "") or "")
    if step == "call" and not to_phone:
        raise HTTPException(status_code=400, detail="Indica un teléfono de prueba para la llamada.")
    if step != "call" and not (to_email or to_phone):
        raise HTTPException(status_code=400, detail="Indica un email o teléfono de prueba.")

    bid = f"futest_{secrets.token_hex(8)}"
    tz_name = (config.get("booking", {}) or {}).get("timezone") or settings.DEFAULT_TIMEZONE
    booking_date = (timeutils._utc_now() + timedelta(days=7)).strftime("%Y-%m-%d")
    booking_time = "10:00"
    try:
        start_local, end_local = agenda._booking_start_end(
            cliente_id, booking_date, booking_time, employee_id="", duration_minutes=30
        )
        start_at, end_at = timeutils._to_utc_iso(start_local), timeutils._to_utc_iso(end_local)
    except Exception:  # noqa: BLE001
        start_at = end_at = ""
    row = _EphemeralBookingRow({
        "id": bid, "cliente_id": cliente_id, "employee_id": "", "employee_name": "",
        "nombre": "Prueba de Seguimiento", "email": to_email, "telefono": to_phone,
        "servicio": "Cita de prueba", "booking_date": booking_date, "booking_time": booking_time,
        "notas": "", "status": "confirmed", "provider_name": "internal", "provider_status": "confirmed",
        "provider_booking_id": "", "provider_booking_url": "", "manage_token": f"mg_{bid}",
        "timezone": tz_name, "start_at": start_at, "end_at": end_at, "booking_code": "PRUEBA",
        "service_id": "", "service_price_cents": 0, "payment_status": "not_required",
        "location_id": agenda._default_location_id(cliente_id), "source": "followup_test",
    })
    base_url = textnorm._public_base_url(request) if request else ""
    try:
        if step == "call":
            from backend import voice as _voice  # late import: evita circular
            res = await timeutils._to_thread(
                _voice._voice_place_outbound_call, cliente_id, row, base_url=base_url
            )
            ok = bool(res.get("ok"))
            return {
                "ok": ok, "step": step, "to_email": "", "to_phone": to_phone,
                "results": [{
                    "channel": "call", "label": "Llamada IA",
                    "status": "sent" if ok else "failed",
                    "detail": "Llamada de prueba en curso." if ok else (res.get("error") or "No se pudo llamar."),
                }],
            }
        if step == "review":
            cfg = _reviews_config(cliente_id)
            if not _review_link_valid(cfg["link"]):
                raise HTTPException(status_code=409, detail="Configura primero el enlace de resenas en Seguimiento.")
            res = await _send_review_request(row, request, cfg=cfg, manual=True)
            sent = res.get("sent_channels", []) or []
            results = _format_test_channel_results(cfg["channels"], sent, res.get("failed", {}) or {}, {})
            return {"ok": bool(sent), "step": step, "to_email": to_email, "to_phone": to_phone, "results": results}
        if step == "voice_otp":
            # Prueba de entrega del código de verificación: envia un codigo de muestra a los
            # canales disponibles (no guarda OTP ni cita). Reusa los mismos senders del cliente.
            sample = f"{secrets.randbelow(10000):04d}"
            empresa = config.get("nombre", "")
            otp_body = (
                f"Tu código de verificación{(' de ' + empresa) if empresa else ''} es {sample}. "
                "Es una prueba del sistema de verificación por voz."
            )
            otp_avail = agenda._reminder_channel_availability(cliente_id)
            otp_cfg = _follow_up_config(cliente_id)["voice_otp_channels"]
            attempt = {
                "email": bool(to_email) and bool(otp_cfg.get("email")),
                "whatsapp": bool(to_phone) and bool(otp_avail["whatsapp"]["available"]) and bool(otp_cfg.get("whatsapp")),
                "sms": bool(to_phone) and bool(otp_avail["sms"]["available"]) and bool(otp_cfg.get("sms")),
            }
            otp_sent: List[str] = []
            otp_failed: Dict[str, str] = {}
            if attempt["email"]:
                try:
                    emailing._send_client_email(
                        cliente_id, to_email,
                        f"Código de verificación (prueba){(' - ' + empresa) if empresa else ''}", otp_body, "",
                    )
                    otp_sent.append("email")
                except Exception as exc:  # noqa: BLE001
                    otp_failed["email"] = str(exc)[:200]
            if attempt["whatsapp"]:
                wa_cfg = config.get("whatsapp", {}) or {}
                pnid = str(wa_cfg.get("phone_number_id", "") or "").strip()
                try:
                    if pnid and await messaging._send_whatsapp_text(
                        cliente_id=cliente_id, phone_number_id=pnid, to_number=to_phone, text=otp_body,
                    ):
                        otp_sent.append("whatsapp")
                    else:
                        otp_failed["whatsapp"] = "No se pudo entregar WhatsApp."
                except Exception as exc:  # noqa: BLE001
                    otp_failed["whatsapp"] = str(exc)[:200]
            if attempt["sms"]:
                try:
                    if await messaging._send_client_sms(cliente_id, to_phone, otp_body):
                        otp_sent.append("sms")
                    else:
                        otp_failed["sms"] = "No se pudo entregar SMS."
                except Exception as exc:  # noqa: BLE001
                    otp_failed["sms"] = str(exc)[:200]
            otp_skipped = {
                "email": ("Desactivado en Seguimiento." if not otp_cfg.get("email") else "Indica un email de prueba."),
                "whatsapp": ("Desactivado en Seguimiento." if not otp_cfg.get("whatsapp") else "Requiere teléfono y WhatsApp disponible."),
                "sms": ("Desactivado en Seguimiento." if not otp_cfg.get("sms") else "Requiere teléfono y SMS (plan Business)."),
            }
            otp_labels = {"email": "Email", "whatsapp": "WhatsApp", "sms": "SMS"}
            otp_results: List[Dict[str, str]] = []
            for ch in ("sms", "whatsapp", "email"):  # orden de preferencia real del OTP
                if ch in otp_sent:
                    status, detail = "sent", "Código de prueba enviado."
                elif ch in otp_failed:
                    status, detail = "failed", otp_failed[ch]
                else:
                    status, detail = "inactive", otp_skipped[ch] or "No disponible."
                otp_results.append({"channel": ch, "label": otp_labels[ch], "status": status, "detail": detail})
            return {"ok": bool(otp_sent), "step": step, "to_email": to_email, "to_phone": to_phone, "results": otp_results}
        # Mensajes de la escalera (confirmed / reminder_24h / reminder_2h).
        active = (
            {name: bool(channels.get(name)) for name in ("email", "whatsapp", "sms")}
            if channels is not None
            else agenda._effective_followup_channels(cliente_id).get(
                step, {"email": True, "whatsapp": False, "sms": False}
            )
        )
        res = await _send_booking_reminder_by_kind(
            row, step, request, respect_enabled=False, raise_on_failure=False, channel_override=active
        )
        results = _format_test_channel_results(active, res["sent"], res["failed"], res["skipped"])
        return {"ok": bool(res["sent"]), "step": step, "to_email": to_email, "to_phone": to_phone, "results": results}
    finally:
        # La cita es efimera, pero el envio deja auditoria/llamada bajo el id de prueba.
        try:
            with db._get_db_connection() as connection:
                connection.execute("DELETE FROM booking_audit WHERE booking_id = ?", (bid,))
                connection.execute("DELETE FROM voice_calls WHERE booking_id = ?", (bid,))
                connection.commit()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Seguimiento post-cita: petición de reseña (Google/Trustpilot/...)
# ---------------------------------------------------------------------------

_REVIEW_DEFAULT_MESSAGE = (
    "Gracias por tu visita a {empresa}. Esperamos que todo haya ido genial.\n\n"
    "Si te apetece, nos ayudarias muchisimo dejando una resena: {enlace}\n\n"
    "Solo te llevara un minuto. ¡Gracias y hasta pronto!"
)
# Al activar la funcion no queremos disparar peticiones a citas viejas: solo se
# consideran citas completadas dentro de esta ventana (tolera caidas del worker).
_REVIEW_MAX_LOOKBACK_HOURS = 14 * 24


def _review_link_valid(link: str) -> bool:
    low = (link or "").strip().lower()
    return low.startswith("http://") or low.startswith("https://")


def _review_platform_label(link: str, platform: str) -> str:
    """Texto del boton segun la plataforma (auto-detectada por la URL si no se fija)."""
    name = (platform or "").strip()
    if not name:
        low = (link or "").lower()
        if any(k in low for k in ("google", "g.page", "goo.gl", "maps.app")):
            name = "Google"
        elif "trustpilot" in low:
            name = "Trustpilot"
        elif "tripadvisor" in low:
            name = "Tripadvisor"
        elif "yelp" in low:
            name = "Yelp"
        elif "facebook" in low or "fb.com" in low:
            name = "Facebook"
    return f"Dejar resena en {name}" if name else "Dejar tu resena"


def _reviews_config(cliente_id: str) -> Dict[str, Any]:
    """Config canonica del seguimiento post-cita del tenant (clave config['reviews'])."""
    cfg = (appstate.CONFIG_CLIENTES.get(cliente_id) or {}).get("reviews") or {}
    try:
        delay = int(cfg.get("delay_hours", 3))
    except (TypeError, ValueError):
        delay = 3
    # La petición de reseña usa los canales GLOBALES del Seguimiento (sin seleccion propia).
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "link": str(cfg.get("link", "") or "").strip(),
        "platform": str(cfg.get("platform", "") or "").strip(),
        "delay_hours": max(1, min(168, delay)),
        "only_manual_attendance": bool(cfg.get("only_manual_attendance", False)),
        "message": str(cfg.get("message", "") or ""),
        "channels": _followup_global_channels(cliente_id),
    }


def _render_review_message(
    template: str, *, empresa: str = "", nombre: str = "", servicio: str = "", enlace: str = "",
) -> str:
    base = (template or "").strip() or _REVIEW_DEFAULT_MESSAGE
    rendered = (
        base.replace("{empresa}", empresa or "")
        .replace("{nombre}", nombre or "")
        .replace("{servicio}", servicio or "")
        .replace("{enlace}", enlace or "")
    )
    # Limpieza cuando {enlace} se elimina (version HTML con boton aparte).
    rendered = re.sub(r"[ \t]{2,}", " ", rendered)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered).strip()
    return rendered


def _review_email_bodies(
    cfg: Dict[str, Any], *, empresa: str, nombre: str, servicio: str,
) -> Tuple[str, str]:
    """(text_body, html_body) del email de petición de reseña."""
    link = cfg["link"]
    label = _review_platform_label(link, cfg["platform"])
    text_body = _render_review_message(
        cfg["message"], empresa=empresa, nombre=nombre, servicio=servicio, enlace=link,
    )
    # El HTML usa boton para el enlace -> renderiza el mensaje sin la URL inline.
    intro = _render_review_message(
        cfg["message"], empresa=empresa, nombre=nombre, servicio=servicio, enlace="",
    )
    intro_html = escape(intro).replace("\n", "<br>")
    button = (
        f'<a href="{escape(link)}" '
        f'style="display:inline-block;padding:14px 28px;border-radius:12px;'
        f'background:#f59e0b;color:#ffffff;text-decoration:none;font-weight:700;font-size:16px;">'
        f'&#9733; {escape(label)}</a>'
    )
    html_body = (
        f'<div style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;'
        f'padding:24px;background:#f5f8fb;color:#102033;">'
        f'<div style="background:#ffffff;border:1px solid #d8e2ee;border-radius:18px;'
        f'padding:28px 24px;text-align:center;">'
        f'<div style="font-size:34px;line-height:1;margin-bottom:10px;">'
        f'&#11088;&#11088;&#11088;&#11088;&#11088;</div>'
        f'<p style="margin:0 0 22px;line-height:1.6;font-size:15px;color:#33475b;">{intro_html}</p>'
        f'<p style="margin:0 0 8px;">{button}</p>'
        f'<p style="margin:18px 0 0;font-size:12px;color:#90a4b8;">{escape(empresa)}</p>'
        f"</div></div>"
    )
    return text_body, html_body


def _review_email_subject(empresa: str) -> str:
    return f"¿Que tal tu experiencia con {empresa}?"


def _review_requests_sent_30d(cliente_id: str) -> int:
    since = (timeutils._utc_now() - timedelta(days=30)).isoformat()
    with db._get_db_connection() as connection:
        return int(connection.execute(
            "SELECT COUNT(*) FROM booking_audit WHERE cliente_id=? AND event_type='review_request_sent' AND created_at>=?",
            (cliente_id, since),
        ).fetchone()[0])


def _reviews_overview_dict(cliente_id: str, request: Optional[Request] = None) -> Dict[str, Any]:
    """Estado del seguimiento post-cita para el portal: config + canales por plan +
    vista previa del email. Fuente de verdad backend (la UI solo refleja)."""
    cfg = _reviews_config(cliente_id)
    plan = clients._client_plan(cliente_id)
    plan_label = settings.PLAN_LIMITS.get(plan, {}).get("label", plan.title())
    avail = agenda._reminder_channel_availability(cliente_id)
    wa_plan = bool(clients._plan_feature(cliente_id, "whatsapp_enabled"))
    sms_plan = bool(clients._plan_feature(cliente_id, "sms_enabled"))
    wa_available = bool(avail["whatsapp"]["available"])
    sms_available = bool(avail["sms"]["available"])
    ch = cfg["channels"]
    channels = [
        {"channel": "email", "label": "Email", "active": bool(ch.get("email")),
         "available": True, "locked": False, "recommended": False, "plan_needed": "", "reason": "Disponible."},
        {"channel": "whatsapp", "label": "WhatsApp", "active": bool(ch.get("whatsapp")) and wa_available,
         "available": wa_available, "locked": not wa_plan, "plan_needed": "" if wa_plan else "Pro",
         "recommended": wa_available and not bool(ch.get("whatsapp")), "reason": avail["whatsapp"]["reason"]},
        {"channel": "sms", "label": "SMS", "active": bool(ch.get("sms")) and sms_available,
         "available": sms_available, "locked": not sms_plan, "plan_needed": "" if sms_plan else "Business",
         "recommended": False, "reason": "Requiere plan Business." if not sms_plan else avail["sms"]["reason"]},
    ]
    config = clients._get_client_config(cliente_id)
    empresa = config["nombre"]
    preview_text, preview_html = _review_email_bodies(
        cfg, empresa=empresa, nombre="Ana", servicio="tu cita",
    )
    return {
        "plan": plan, "plan_label": plan_label,
        "enabled": cfg["enabled"], "link": cfg["link"], "platform": cfg["platform"],
        "platform_label": _review_platform_label(cfg["link"], cfg["platform"]),
        "delay_hours": cfg["delay_hours"], "only_manual_attendance": cfg["only_manual_attendance"],
        "message": cfg["message"], "default_message": _REVIEW_DEFAULT_MESSAGE,
        "channels": channels,
        "channel_availability": {
            "email": True, "whatsapp": wa_available, "sms": sms_available, "voice": False,
            "whatsapp_reason": avail["whatsapp"]["reason"], "sms_reason": avail["sms"]["reason"],
            "voice_reason": "",
        },
        "sent_30d": _review_requests_sent_30d(cliente_id),
        "link_valid": _review_link_valid(cfg["link"]),
        "preview_subject": _review_email_subject(empresa),
        "preview_html": preview_html,
        "preview_text": preview_text,
    }


async def _send_review_request(
    booking_row: sqlite3.Row,
    request: Optional[Request] = None,
    *,
    cfg: Optional[Dict[str, Any]] = None,
    manual: bool = False,
) -> Dict[str, Any]:
    """Envia la petición de reseña por los canales activos. Marca la cita para no
    repetir (idempotente) y deja auditoria. Nunca lanza por canal: agrega resultados."""
    cliente_id = booking_row["cliente_id"]
    cfg = cfg or _reviews_config(cliente_id)
    if not _review_link_valid(cfg["link"]):
        return {"sent_channels": [], "skipped": "no_link"}
    config = clients._get_client_config(cliente_id)
    empresa = config["nombre"]
    nombre = (booking_row["nombre"] or "").split(" ")[0] if booking_row["nombre"] else ""
    servicio = booking_row["servicio"] or "tu cita"
    availability = agenda._reminder_channel_availability(cliente_id)
    ch = cfg["channels"]
    sent_channels: List[str] = []
    failed: Dict[str, str] = {}

    if ch.get("email") and (booking_row["email"] or "").strip():
        try:
            text_body, html_body = _review_email_bodies(cfg, empresa=empresa, nombre=nombre, servicio=servicio)
            emailing._send_client_email(
                cliente_id, booking_row["email"], _review_email_subject(empresa), text_body, html_body,
            )
            sent_channels.append("email")
        except Exception as exc:  # noqa: BLE001
            failed["email"] = str(exc)

    plain_text = _render_review_message(
        cfg["message"], empresa=empresa, nombre=nombre, servicio=servicio, enlace=cfg["link"],
    )
    if ch.get("whatsapp") and availability.get("whatsapp", {}).get("available"):
        whatsapp_cfg = config.get("whatsapp", {}) or {}
        phone_number_id = str(whatsapp_cfg.get("phone_number_id", "") or "").strip()
        to_number = _booking_customer_phone_for_channel(booking_row, "whatsapp")
        if phone_number_id and to_number:
            try:
                if await messaging._send_whatsapp_text(
                    cliente_id=cliente_id, phone_number_id=phone_number_id,
                    to_number=to_number, text=plain_text,
                ):
                    sent_channels.append("whatsapp")
                else:
                    failed["whatsapp"] = "No se pudo entregar WhatsApp."
            except Exception as exc:  # noqa: BLE001
                failed["whatsapp"] = str(exc)

    if ch.get("sms") and availability.get("sms", {}).get("available"):
        to_number = _booking_customer_phone_for_channel(booking_row, "sms")
        if to_number:
            try:
                if await messaging._send_client_sms(cliente_id, to_number, plain_text):
                    sent_channels.append("sms")
                else:
                    failed["sms"] = "No se pudo entregar SMS."
            except Exception as exc:  # noqa: BLE001
                failed["sms"] = str(exc)

    # Marca la cita aunque no se entregara nada: evita reprocesar en cada pasada.
    _update_booking_record(booking_row["id"], review_request_sent_at=timeutils._utc_now_iso())
    _record_booking_audit(
        booking_row["id"], cliente_id, "review_request_sent",
        {"channels": sent_channels, "failed": failed, "manual": manual},
    )
    return {"sent_channels": sent_channels, "failed": failed}


def _bookings_due_for_review(
    cliente_id: str, now_utc: datetime, cfg: Dict[str, Any], *, limit: int = 500,
) -> List[sqlite3.Row]:
    # end_at se guarda con sufijo "Z" (_to_utc_iso): normaliza los limites igual
    # para que la comparacion lexicografica sea correcta en el borde.
    upper = (now_utc - timedelta(hours=cfg["delay_hours"])).isoformat().replace("+00:00", "Z")
    lower = (now_utc - timedelta(hours=_REVIEW_MAX_LOOKBACK_HOURS)).isoformat().replace("+00:00", "Z")
    query = (
        "SELECT * FROM bookings WHERE cliente_id=? AND status='completed' "
        "AND review_request_sent_at='' AND end_at<>'' AND end_at<=? AND end_at>=? "
    )
    params: List[Any] = [cliente_id, upper, lower]
    if cfg["only_manual_attendance"]:
        query += "AND completed_source='manual' "
    query += "ORDER BY end_at ASC LIMIT ?"
    params.append(limit)
    with db._get_db_connection() as connection:
        return connection.execute(query, tuple(params)).fetchall()


async def _run_review_requests(
    now_utc: Optional[datetime] = None, request: Optional[Request] = None,
) -> int:
    now_utc = now_utc or timeutils._utc_now()
    total = 0
    for cliente_id in list(appstate.CONFIG_CLIENTES.keys()):
        cfg = _reviews_config(cliente_id)
        if not (cfg["enabled"] and _review_link_valid(cfg["link"])):
            continue
        if not any(cfg["channels"].get(name) for name in ("email", "whatsapp", "sms")):
            continue
        try:
            rows = _bookings_due_for_review(cliente_id, now_utc, cfg)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("Resenas: error listando citas de %s: %s", cliente_id, exc)
            continue
        for row in rows:
            try:
                res = await _send_review_request(row, request, cfg=cfg)
                if res.get("sent_channels"):
                    total += 1
            except Exception as exc:  # noqa: BLE001
                settings.logger.error("Resenas: error enviando %s: %s", row["id"], exc)
    return total


def _booking_confirmed_by_customer(booking_id: str) -> bool:
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT 1 FROM booking_audit WHERE booking_id=? AND event_type='attendance_confirmed_by_customer' LIMIT 1",
            (booking_id,),
        ).fetchone() is not None


def _confirm_call_already_placed(booking_id: str) -> bool:
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT 1 FROM booking_audit WHERE booking_id=? AND event_type='confirm_call_placed' LIMIT 1",
            (booking_id,),
        ).fetchone() is not None


def _recent_confirm_call_placed(booking_id: str, *, within_minutes: int = 15) -> bool:
    """True si ya se coloco una llamada de confirmacion para esta cita en los ultimos
    ``within_minutes``. Evita llamadas duplicadas accidentales (doble clic, reintentos)
    sin impedir un reintento legitimo pasado un rato."""
    cutoff = (timeutils._utc_now() - timedelta(minutes=within_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT 1 FROM booking_audit WHERE booking_id=? AND event_type='confirm_call_placed' "
            "AND created_at >= ? LIMIT 1",
            (booking_id, cutoff),
        ).fetchone() is not None


def _outbound_calls_today(cliente_id: str) -> int:
    start = timeutils._utc_now().strftime("%Y-%m-%dT00:00:00")
    with db._get_db_connection() as connection:
        return int(connection.execute(
            "SELECT COUNT(*) FROM voice_calls WHERE cliente_id=? AND direction='outbound' AND started_at>=?",
            (cliente_id, start),
        ).fetchone()[0])


def _reminder_calls_ok_now(cliente_id: str, rcfg: Optional[Dict[str, Any]] = None) -> bool:
    """True si se puede colocar una llamada de confirmacion ahora: hay numero + creds,
    estamos fuera de las quiet hours (hora local del tenant) y bajo el cap diario."""
    rcfg = rcfg or _reminders_config(cliente_id)
    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    voice_cfg = config.get("voice") or {}
    if not (voice_cfg.get("twilio_phone_number") and settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN):
        return False
    tz_name = (config.get("booking") or {}).get("timezone") or settings.DEFAULT_TIMEZONE
    try:
        now_local = datetime.now(ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001
        now_local = timeutils._utc_now()
    cur = now_local.hour * 60 + now_local.minute
    qs = textnorm._time_to_min(rcfg["quiet_start"]) or 1260
    qe = textnorm._time_to_min(rcfg["quiet_end"]) or 540
    quiet = (cur >= qs or cur < qe) if qs > qe else (qs <= cur < qe)
    if quiet:
        return False
    return _outbound_calls_today(cliente_id) < int(rcfg["daily_call_cap"])


async def _run_booking_reminders(request: Optional[Request] = None) -> AdminReminderRunResult:
    now_utc = timeutils._utc_now()
    _auto_confirm_pending_bookings()
    rows = _bookings_due_for_reminders(now_utc)
    processed = 0
    sent_24h = 0
    sent_2h = 0
    failed = 0

    for row in rows:
        processed += 1
        # La lista se cargo al empezar y enviar cada aviso hace I/O de red: con
        # muchas citas, el recorrido dura. Se relee la cita justo antes de tocarla
        # para no mandarle un recordatorio a quien acaba de cancelar, ni con la
        # hora vieja a quien acaba de reprogramar.
        fresca = _get_booking_row_by_id(row["id"])
        if fresca is None or fresca["status"] != "confirmed":
            continue
        row = fresca
        fu = _follow_up_config(row["cliente_id"])
        try:
            if not row["reminder_24h_sent_at"] and _booking_due_for_reminder(row, now_utc, settings.REMINDER_24H_HOURS):
                await _send_booking_reminder_by_kind(
                    row,
                    "reminder_24h",
                    request,
                    sent_column="reminder_24h_sent_at",
                )
                sent_24h += 1
            elif not row["reminder_2h_sent_at"] and _booking_due_for_reminder(row, now_utc, settings.REMINDER_2H_HOURS):
                # Escalera: no molestar con el 2h a quien ya confirmo (opt-in).
                if fu["suppress_2h_if_confirmed"] and _booking_confirmed_by_customer(row["id"]):
                    _mark_booking_email_result(
                        row["id"], status="skipped:confirmed", sent_column="reminder_2h_sent_at", error="",
                    )
                    _record_booking_audit(
                        row["id"], row["cliente_id"], "booking_email_skipped",
                        {"kind": "reminder_2h", "reason": "already_confirmed"},
                    )
                else:
                    await _send_booking_reminder_by_kind(
                        row,
                        "reminder_2h",
                        request,
                        sent_column="reminder_2h_sent_at",
                    )
                    sent_2h += 1

            # Llamada IA como ULTIMO escalon (T-call_hours_before), independiente de los
            # recordatorios y SOLO si el cliente sigue sin confirmar. Opt-in + Business.
            if (
                fu["call_enabled"]
                and _call_due_for_booking(row, now_utc, fu["call_hours_before"])
                and not _booking_confirmed_by_customer(row["id"])
                and not _confirm_call_already_placed(row["id"])
                and _reminder_calls_ok_now(row["cliente_id"])
            ):
                try:
                    from backend import voice as _voice  # late import: evita circular
                    await timeutils._to_thread(
                        _voice._voice_place_outbound_call, row["cliente_id"], row, purpose="confirm"
                    )
                except Exception as exc:  # noqa: BLE001
                    settings.logger.error("Llamada de confirmacion fallo %s: %s", row["id"], exc)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            settings.logger.error("No se ha podido enviar recordatorio de %s: %s", row["id"], exc)
            _mark_booking_email_result(
                row["id"],
                status="failed",
                error=str(exc),
            )
            _record_booking_audit(
                row["id"],
                row["cliente_id"],
                "booking_email_failed",
                {"kind": "reminder", "error": str(exc)},
            )

    return AdminReminderRunResult(
        processed=processed,
        sent_24h=sent_24h,
        sent_2h=sent_2h,
        failed=failed,
    )


async def _create_provider_booking(
    cliente_id: str,
    booking_payload: Dict[str, Any],
) -> appstate.ProviderBookingResult:
    _ = (cliente_id, booking_payload)
    return appstate.ProviderBookingResult(
        success=True,
        status="internal",
        provider_name="internal",
        message="Reserva registrada internamente.",
    )


def _connect_account_status(cliente_id: str, *, refresh: bool = False) -> ConnectAccountStatus:
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM client_payment_accounts WHERE cliente_id=?", (cliente_id,)
        ).fetchone()
    if not row:
        return ConnectAccountStatus()
    row_keys = row.keys()
    values = {
        "connected": bool(row["stripe_account_id"]),
        "stripe_account_id": row["stripe_account_id"] or "",
        "charges_enabled": bool(row["charges_enabled"]),
        "payouts_enabled": bool(row["payouts_enabled"]),
        "details_submitted": bool(row["details_submitted"]),
        "bizum_status": (row["bizum_status"] if "bizum_status" in row_keys else "") or "",
        "bizum_enabled": bool(row["bizum_enabled"]) if "bizum_enabled" in row_keys else True,
        "wallets_enabled": bool(row["wallets_enabled"]) if "wallets_enabled" in row_keys else True,
    }
    if refresh and values["stripe_account_id"] and stripe_gateway._stripe_configured():
        try:
            stripe_gateway._stripe_init()
            account = stripe_gateway.stripe.Account.retrieve(values["stripe_account_id"])
            capabilities = textnorm._object_get(account, "capabilities", {}) or {}
            bizum = str(capabilities.get("bizum_payments") or "")
            # Cuentas conectadas antes de que existiera Bizum: se pide aqui, una sola
            # vez (al pedirlo la clave ya aparece, aunque sea "inactive").
            if not bizum:
                bizum = stripe_gateway.request_bizum_capability(values["stripe_account_id"])
            # Stripe enciende por defecto una docena de metodos que aqui no pinta
            # nada (Klarna, Pix, tres coreanos...). Se reconcilia contra lo que el
            # negocio ha elegido en el panel, que es quien manda.
            stripe_gateway.sync_payment_methods(
                values["stripe_account_id"],
                bizum=bool(values["bizum_enabled"]) and bizum == "active",
                wallets=bool(values["wallets_enabled"]),
            )
            values.update({
                "charges_enabled": bool(textnorm._object_get(account, "charges_enabled", False)),
                "payouts_enabled": bool(textnorm._object_get(account, "payouts_enabled", False)),
                "details_submitted": bool(textnorm._object_get(account, "details_submitted", False)),
                "bizum_status": bizum,
            })
            with db._get_db_connection() as connection:
                connection.execute(
                    """
                    UPDATE client_payment_accounts SET charges_enabled=?, payouts_enabled=?,
                        details_submitted=?, bizum_status=?, updated_at=? WHERE cliente_id=?
                    """,
                    (
                        int(values["charges_enabled"]), int(values["payouts_enabled"]),
                        int(values["details_submitted"]), values["bizum_status"],
                        timeutils._utc_now_iso(), cliente_id,
                    ),
                )
                connection.commit()
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("No se pudo refrescar Stripe Connect para %s: %s", cliente_id, exc)
    return ConnectAccountStatus(**values)


def _payment_policy(cliente_id: str, service_id: str) -> Dict[str, Any]:
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM service_payment_policies WHERE cliente_id=? AND service_id=?",
            (cliente_id, service_id),
        ).fetchone()
    return {
        "mode": row["mode"] if row else "none",
        "deposit_value": int(row["deposit_value"] or 0) if row else 0,
        "confirm_booking_on_paid": bool(row["confirm_booking_on_paid"]) if row else True,
    }


def _ai_payment_sending_available(cliente_id: str) -> bool:
    """La IA puede enviar el enlace de pago de una cita si el negocio cobra con Stripe.

    Antes habia un interruptor aparte que nacia apagado, y nadie lo encontraba: un
    negocio conectaba Stripe, configuraba una señal y el asistente seguia sin poder
    mandar el enlace. No aportaba seguridad (el importe sale del servicio, va al
    contacto que ya figura en la cita, con dedup, limite y auditoria), asi que se
    retiro: si hay Stripe operativo, la IA puede enviarlo.
    """
    status = _connect_account_status(cliente_id)
    return bool(status.connected and status.charges_enabled)


def disconnect_stripe_account(cliente_id: str) -> ConnectAccountStatus:
    """Desvincula la cuenta de Stripe del negocio.

    La cuenta NO se borra en Stripe: es del negocio, con su dinero y su historial,
    y Vantelia no puede ni debe eliminarla. Lo que se hace es olvidarla: dejamos de
    cobrar por ella. Si hay OAuth configurado se revoca ademas el acceso.

    Consecuencia que el panel avisa antes: los servicios que exigian pago pasan a
    reservarse sin cobro hasta que se conecte otra cuenta.
    """
    estado = _connect_account_status(cliente_id)
    if not estado.stripe_account_id:
        return estado
    if settings.STRIPE_CONNECT_CLIENT_ID and stripe_gateway._stripe_configured():
        try:
            stripe_gateway._stripe_init()
            stripe_gateway.stripe.OAuth.deauthorize(
                client_id=settings.STRIPE_CONNECT_CLIENT_ID,
                stripe_user_id=estado.stripe_account_id,
            )
        except Exception as exc:  # noqa: BLE001 - desvincular en local es lo que manda
            settings.logger.warning("No se pudo revocar el acceso a %s: %s", estado.stripe_account_id, exc)
    with db._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE client_payment_accounts
            SET stripe_account_id='', charges_enabled=0, payouts_enabled=0,
                details_submitted=0, bizum_status='', updated_at=?
            WHERE cliente_id=?
            """,
            (timeutils._utc_now_iso(), cliente_id),
        )
        connection.commit()
    settings.logger.info("Stripe desconectado para %s (cuenta %s)", cliente_id, estado.stripe_account_id)
    return _connect_account_status(cliente_id)


def payment_method_prefs(cliente_id: str) -> Dict[str, bool]:
    """Que metodos quiere el negocio ademas de la tarjeta. Sin fila = los dos."""
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT bizum_enabled, wallets_enabled FROM client_payment_accounts WHERE cliente_id=?",
            (cliente_id,),
        ).fetchone()
    if not row:
        return {"bizum": True, "wallets": True}
    claves = row.keys()
    return {
        "bizum": bool(row["bizum_enabled"]) if "bizum_enabled" in claves else True,
        "wallets": bool(row["wallets_enabled"]) if "wallets_enabled" in claves else True,
    }


def save_payment_method_prefs(cliente_id: str, *, bizum: bool, wallets: bool) -> ConnectAccountStatus:
    """Guarda la eleccion del negocio y la aplica en Stripe."""
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_payment_accounts (cliente_id, bizum_enabled, wallets_enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id) DO UPDATE SET bizum_enabled=excluded.bizum_enabled,
                wallets_enabled=excluded.wallets_enabled, updated_at=excluded.updated_at
            """,
            (cliente_id, int(bool(bizum)), int(bool(wallets)), now, now),
        )
        connection.commit()
    estado = _connect_account_status(cliente_id)
    if estado.stripe_account_id:
        stripe_gateway.sync_payment_methods(estado.stripe_account_id, bizum=bizum, wallets=wallets)
    return _connect_account_status(cliente_id)


def _payment_amount_for_booking(booking: sqlite3.Row, override: Optional[int] = None) -> int:
    if override is not None:
        return int(override)
    price = int(booking["service_price_cents"] or 0)
    policy = _payment_policy(booking["cliente_id"], booking["service_id"] or "")
    if policy["mode"] == "full":
        return price
    if policy["mode"] == "deposit_fixed":
        return min(price, int(policy["deposit_value"])) if price else int(policy["deposit_value"])
    if policy["mode"] == "deposit_percent":
        return round(price * int(policy["deposit_value"]) / 100)
    return 0


def _payment_public(row: sqlite3.Row) -> CustomerPaymentPublic:
    return CustomerPaymentPublic(
        id=row["id"], contact_id=row["contact_id"] or "", booking_id=row["booking_id"] or "",
        service_id=row["service_id"] or "", service_name=row["service_name"] or "",
        amount_cents=int(row["amount_cents"] or 0), currency=row["currency"] or "eur",
        status=row["status"] or "pending", checkout_url=row["checkout_url"] or "",
        created_at=row["created_at"] or "", paid_at=row["paid_at"] or "", updated_at=row["updated_at"] or "",
    )


def _payment_contact_for_booking(booking: sqlite3.Row) -> str:
    with db._get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT contact_id FROM crm_contact_links
            WHERE cliente_id=? AND entity_type='booking' AND entity_id=? LIMIT 1
            """,
            (booking["cliente_id"], booking["id"]),
        ).fetchone()
    return row["contact_id"] if row else crm._crm_upsert_contact(
        booking["cliente_id"], name=booking["nombre"], email=booking["email"],
        phone=booking["telefono"] or "", source="payment", status="cita_pendiente",
        entity_type="booking", entity_id=booking["id"],
    )


def _ai_payment_delivery_available(cliente_id: str, method: str) -> bool:
    """Comprueba el canal efectivo antes de crear un Checkout que no se podra enviar."""
    channel_status = emailing._channel_settings_public(cliente_id)
    if method == "sms":
        return bool(channel_status.sms.available)

    settings = security._ensure_channel_settings(cliente_id)
    provider = settings["email_provider"] or "vantelia_smtp"
    if provider == "gmail_oauth":
        gmail = emailing._client_gmail_connection(cliente_id)
        if gmail and gmail["status"] == "active":
            return True
        return bool(settings["email_fallback_enabled"] and emailing._email_delivery_configured())
    if provider == "client_smtp":
        if emailing._client_smtp_configured(settings):
            return True
        return bool(settings["email_fallback_enabled"] and emailing._email_delivery_configured())
    return emailing._email_delivery_configured()


def _booking_payment_return_urls(base_url: str, manage_token: str) -> Tuple[str, str]:
    base = (base_url or textnorm._preferred_public_base_url()).rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="APP_BASE_URL no configurada para generar enlaces de pago.")
    token = textnorm._sanitize_text(manage_token or "")
    manage_url = f"{base}/booking/manage/{token}"
    return f"{manage_url}?payment=success", f"{manage_url}?payment=cancel"


def _create_customer_payment_link(
    cliente_id: str,
    booking: sqlite3.Row,
    *,
    base_url: str,
    override_cents: Optional[int] = None,
) -> sqlite3.Row:
    """Crea una sesion de Stripe Checkout sobre la cuenta Connect del negocio y
    persiste el customer_payment. Logica compartida por el portal (boton manual)
    y por la IA (web/WhatsApp/voz). Lanza HTTPException en cada error de negocio
    para que cada llamante mapee el detalle como prefiera. Sincrona (llama a
    Stripe): los llamantes async deben envolverla en timeutils._to_thread."""
    booking_id = booking["id"]
    with db._get_db_connection() as connection:
        # Dedup contra LOS DOS sistemas de pago: el pago directo (customer_payments)
        # y el pago de la reserva con depósito/retención (bookings.payment_status).
        # Sin esto, una cita ya pagada por depósito (sin fila customer_payments) pasaría
        # el dedup y permitiría un segundo cobro.
        paid = connection.execute(
            "SELECT 1 FROM customer_payments WHERE cliente_id=? AND booking_id=? AND status='paid' LIMIT 1",
            (cliente_id, booking_id),
        ).fetchone()
        bk = connection.execute(
            "SELECT payment_status FROM bookings WHERE cliente_id=? AND id=? LIMIT 1",
            (cliente_id, booking_id),
        ).fetchone()
    if paid or (bk and (bk["payment_status"] or "") == "paid"):
        raise HTTPException(status_code=409, detail="Esta cita ya tiene un pago completado.")
    account = _connect_account_status(cliente_id, refresh=True)
    if not account.connected or not account.charges_enabled:
        raise HTTPException(status_code=409, detail="Conecta y activa Stripe antes de solicitar pagos.")
    amount = _payment_amount_for_booking(booking, override_cents)
    if amount < 50:
        raise HTTPException(status_code=400, detail="Configura un precio o una señal minima de 0,50 EUR.")
    contact_id = _payment_contact_for_booking(booking)
    payment_id, now = "pay_" + secrets.token_hex(10), timeutils._utc_now_iso()
    metadata = {"source": "customer_payment", "payment_id": payment_id, "cliente_id": cliente_id, "booking_id": booking_id}
    success_url, cancel_url = _booking_payment_return_urls(base_url, booking["manage_token"])
    stripe_gateway._stripe_init()
    try:
        checkout_kwargs: Dict[str, Any] = dict(
            mode="payment",
            line_items=[{"price_data": {"currency": "eur", "unit_amount": amount, "product_data": {"name": booking["servicio"] or "Reserva"}}, "quantity": 1}],
            metadata=metadata,
            success_url=success_url,
            cancel_url=cancel_url,
            stripe_account=account.stripe_account_id,
        )
        if booking["email"]:
            checkout_kwargs["customer_email"] = booking["email"]
        session = stripe_gateway.stripe.checkout.Session.create(**checkout_kwargs)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("No se pudo crear checkout Connect %s: %s", booking_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo crear el enlace de pago.") from exc
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO customer_payments
                (id, cliente_id, contact_id, booking_id, service_id, service_name, stripe_account_id,
                 stripe_checkout_session_id, amount_cents, currency, status, checkout_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'eur', 'pending', ?, ?, ?)
            """,
            (
                payment_id, cliente_id, contact_id, booking_id, booking["service_id"] or "",
                booking["servicio"] or "", account.stripe_account_id, textnorm._object_get(session, "id", ""),
                amount, textnorm._object_get(session, "url", ""), now, now,
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
    return row


def _ai_payment_method_for_source(source: str) -> str:
    """Canal de envio del enlace segun el origen de la cita: voz -> SMS, resto -> email."""
    return "sms" if (source or "").strip().lower() == "voice" else "email"


async def _ai_send_payment_link(
    cliente_id: str,
    booking: sqlite3.Row,
    *,
    base_url: str = "",
) -> Dict[str, Any]:
    """Genera y ENVIA un enlace de pago al cliente final, en nombre del negocio.

    Canal automatico segun booking.source: 'voice' -> SMS al telefono de la cita,
    resto -> email al email de la cita. Aplica todas las reglas de seguridad:
    opt-in del negocio, Stripe conectado, importe NO manipulable por el cliente
    (sale de la politica/precio), dedup de pago ya pagado y rate limit. Devuelve
    un dict con `ok` y mensajes amigables para que el asistente los verbalice.
    Nunca lanza: cualquier fallo vuelve como {"ok": False, ...}.
    """
    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    nombre_negocio = config.get("nombre", "") or "el negocio"

    booking_id = booking["id"]
    source = (booking["source"] or "").strip().lower()
    method = _ai_payment_method_for_source(source)
    email = textnorm._sanitize_text(booking["email"] or "")
    phone = _booking_customer_phone_for_channel(booking, "sms")

    account = _connect_account_status(cliente_id, refresh=True)
    if not account.connected or not account.charges_enabled:
        return {"ok": False, "reason": "stripe_unavailable", "method": method,
                "error": "Conecta y activa Stripe antes de enviar enlaces de pago."}

    if method == "sms" and not phone:
        return {"ok": False, "reason": "no_phone", "method": method,
                "error": "La cita no tiene un teléfono al que enviar el SMS con el enlace de pago."}
    if method == "email" and not email:
        return {"ok": False, "reason": "no_email", "method": method,
                "error": "La cita no tiene un email al que enviar el enlace de pago."}
    if not _ai_payment_delivery_available(cliente_id, method):
        channel_label = "SMS" if method == "sms" else "email"
        return {"ok": False, "reason": "channel_unavailable", "method": method,
                "error": f"Configura un canal de {channel_label} antes de enviar enlaces de pago."}

    # Rate limit: maximo 2 enlaces por cita en la última hora (anti-spam/enumeracion).
    cutoff = (timeutils._utc_now() - timedelta(hours=1)).isoformat()
    with db._get_db_connection() as connection:
        recent = connection.execute(
            "SELECT COUNT(*) AS n FROM customer_payments WHERE cliente_id=? AND booking_id=? AND created_at>=?",
            (cliente_id, booking_id, cutoff),
        ).fetchone()
    if recent and int(recent["n"] or 0) >= 2:
        return {"ok": False, "reason": "rate_limited", "method": method,
                "error": "Ya se han enviado varios enlaces de pago de esta cita en la última hora."}

    base = base_url or textnorm._preferred_public_base_url()
    try:
        row = await timeutils._to_thread(
            _create_customer_payment_link, cliente_id, booking, base_url=base, override_cents=None
        )
    except HTTPException as exc:
        return {"ok": False, "reason": "link_error", "method": method, "error": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[ai-pay] no se pudo crear enlace para %s: %s", booking_id, exc)
        return {"ok": False, "reason": "link_error", "method": method,
                "error": "No se pudo generar el enlace de pago."}

    checkout_url = row["checkout_url"] or ""
    amount_cents = int(row["amount_cents"] or 0)
    amount_label = textnorm._format_price_cents(amount_cents)
    servicio = booking["servicio"] or "tu cita"
    code = booking["booking_code"] or ""

    sent = False
    if method == "sms":
        body = (
            f"{nombre_negocio}: para pagar {servicio} ({amount_label}) usa este enlace seguro: "
            f"{checkout_url}"
        )
        sent = await messaging._send_client_sms(cliente_id, phone, body)
    else:
        reply_to = (config.get("contacto", {}) or {}).get("email", "") or None
        subject = f"Enlace de pago de tu cita en {nombre_negocio}"
        text_body = (
            f"Hola,\n\nGracias por confiar en {nombre_negocio}. "
            f"Para completar el pago de {servicio} ({amount_label}) usa este enlace seguro:\n\n"
            f"{checkout_url}\n\n"
            "El pago se procesa de forma segura a traves de Stripe.\n\n"
            f"Un saludo,\n{nombre_negocio}"
        )
        html_body = (
            f"<p>Hola,</p><p>Gracias por confiar en <strong>{escape(nombre_negocio)}</strong>. "
            f"Para completar el pago de <strong>{escape(servicio)}</strong> ({escape(amount_label)}) "
            f"usa este enlace seguro:</p>"
            f'<p><a href="{escape(checkout_url)}">Pagar ahora</a></p>'
            "<p>El pago se procesa de forma segura a traves de Stripe.</p>"
            f"<p>Un saludo,<br>{escape(nombre_negocio)}</p>"
        )
        try:
            await timeutils._to_thread(emailing._send_client_email, cliente_id, email, subject, text_body, html_body, reply_to)
            sent = True
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("[ai-pay] email fallo %s: %s", booking_id, exc)
            sent = False

    _record_booking_audit(
        booking_id, cliente_id, "ai_payment_link_sent",
        {
            "source": source, "method": method, "amount_cents": amount_cents,
            "payment_id": row["id"], "sent": bool(sent),
            "recipient": (phone if method == "sms" else email),
        },
    )

    return {
        "ok": True, "method": method, "sent": bool(sent),
        "amount_cents": amount_cents, "amount_label": amount_label,
        "checkout_url": checkout_url, "booking_code": code, "servicio": servicio,
    }


def resolve_payment_requirement(
    cliente_id: str,
    service: Optional[sqlite3.Row],
    booking: Optional[sqlite3.Row] = None,
) -> Dict[str, Any]:
    mode = str(service["payment_mode"] or "payment_disabled") if service else "payment_disabled"
    payment_type = str(service["payment_type"] or "full") if service else "full"
    currency = str(service["currency"] or "eur").lower() if service else "eur"
    full_amount = int(
        (booking["service_price_cents"] if booking else service["price_cents"]) or 0
    ) if service else 0
    deposit = int(service["deposit_amount_cents"] or 0) if service else 0
    # preauth: retiene el deposito si esta configurado; si no, el importe completo.
    amount = deposit if payment_type in ("deposit", "preauth") and deposit > 0 else full_amount
    account = stripe_gateway._stripe_connected_account_row(cliente_id)
    stripe_active = bool(account and account["status"] == "active" and stripe_gateway._stripe_configured())
    available = stripe_active and amount > 0 and mode != "payment_disabled"
    return {
        "mode": mode,
        "payment_type": payment_type,
        "currency": currency,
        "amount_cents": amount if available else 0,
        "stripe_account_id": account["stripe_account_id"] if available else "",
        "payment_required": bool(available and mode == "payment_required"),
        "payment_optional": bool(available and mode == "payment_optional"),
        "payment_status": "pending" if available and mode == "payment_required" else "optional" if available else "not_required",
    }


def service_booking_note(cliente_id: str, booking_row: sqlite3.Row) -> str:
    """Lo que el negocio quiere contarle al cliente al confirmar ESTE servicio.

    Es texto suyo (como venir preparado, que traer) y solo aplica al servicio que
    lo tiene puesto: por eso no vale el mensaje de confirmacion general.
    """
    try:
        servicio = booking_row["servicio"]
        service_id = booking_row["service_id"] if "service_id" in booking_row.keys() else ""
    except (KeyError, IndexError):
        return ""
    row = agenda._get_service_row(cliente_id, service_id) or agenda._find_service_by_name(
        cliente_id, servicio
    )
    if row is None:
        return ""
    try:
        return str(row["booking_note"] or "").strip()
    except (KeyError, IndexError):  # base antigua sin la columna
        return ""


def payment_prompt_note(cliente_id: str, booking_row: sqlite3.Row, payment_row: Optional[sqlite3.Row]) -> str:
    """Explica QUE se esta pagando (senal, retencion o total) en una frase.

    Compartido por WhatsApp y chat: el enlace de pago a secas no dice si esos
    50 EUR son el precio del servicio o solo la señal.
    """
    if not payment_row:
        return ""
    service = agenda._get_service_row(cliente_id, booking_row["service_id"]) or agenda._find_service_by_name(
        cliente_id, booking_row["servicio"]
    )
    linea = paystate.checkout_line(
        booking_row["servicio"] or "Reserva",
        int(payment_row["amount_cents"] or 0),
        int(booking_row["service_price_cents"] or 0),
        str(service["payment_type"] or "full") if service else "full",
    )
    return linea["description"]


def _booking_payment_row(booking_id: str) -> Optional[sqlite3.Row]:
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM booking_payments WHERE booking_id = ?",
            (booking_id,),
        ).fetchone()


def _checkout_product_data(booking: sqlite3.Row, decision: Dict[str, Any]) -> Dict[str, str]:
    """Producto de Stripe con la señal explicada (Stripe rechaza description vacia)."""
    linea = paystate.checkout_line(
        booking["servicio"] or "Reserva",
        int(decision.get("amount_cents") or 0),
        int(booking["service_price_cents"] or 0),
        str(decision.get("payment_type") or "full"),
    )
    datos = {"name": linea["name"]}
    if linea["description"]:
        datos["description"] = linea["description"]
    return datos


def create_booking_payment_checkout(cliente_id: str, booking_id: str, request: Optional[Request] = None) -> str:
    booking = _load_booking_or_404(booking_id)
    if booking["cliente_id"] != cliente_id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    service = agenda._get_service_row(cliente_id, booking["service_id"]) or agenda._find_service_by_name(
        cliente_id, booking["servicio"]
    )
    decision = resolve_payment_requirement(cliente_id, service, booking)
    if not decision["payment_required"] and not decision["payment_optional"]:
        raise HTTPException(status_code=409, detail="Esta reserva no tiene un pago Stripe disponible.")
    existing = _booking_payment_row(booking_id)
    if existing and existing["status"] == "paid":
        return existing["checkout_url"] or ""
    if existing and existing["checkout_url"]:
        return existing["checkout_url"]
    stripe_gateway._stripe_init()
    base_url = textnorm._preferred_public_base_url(request).rstrip("/")
    success_url, cancel_url = _booking_payment_return_urls(base_url, booking["manage_token"])
    # preauth: retencion sin cobro inmediato (capture manual desde el panel).
    capture_method = "manual" if decision.get("payment_type") == "preauth" else "automatic"
    payment_intent_data: Dict[str, Any] = {
        "metadata": {
            "source": "booking_payment",
            "cliente_id": cliente_id,
            "booking_id": booking_id,
        },
    }
    if capture_method == "manual":
        payment_intent_data["capture_method"] = "manual"
    try:
        session = stripe_gateway.stripe.checkout.Session.create(
            stripe_account=decision["stripe_account_id"],
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": decision["currency"],
                    "product_data": _checkout_product_data(booking, decision),
                    "unit_amount": decision["amount_cents"],
                },
                "quantity": 1,
            }],
            customer_email=booking["email"] or None,
            success_url=success_url,
            cancel_url=cancel_url,
            expires_at=int(time.time()) + settings.BOOKING_PAYMENT_EXPIRY_MINUTES * 60,
            metadata={
                "source": "booking_payment",
                "cliente_id": cliente_id,
                "booking_id": booking_id,
            },
            payment_intent_data=payment_intent_data,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Stripe booking checkout fallo cliente=%s booking=%s: %s", cliente_id, booking_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo crear el enlace de pago.") from exc
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO booking_payments
                (id, cliente_id, booking_id, stripe_account_id, checkout_session_id,
                 amount_cents, currency, status, checkout_url, capture_method, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            ON CONFLICT(booking_id) DO UPDATE SET
                checkout_session_id=excluded.checkout_session_id,
                checkout_url=excluded.checkout_url,
                capture_method=excluded.capture_method,
                updated_at=excluded.updated_at
            """,
            (
                f"pay_{secrets.token_urlsafe(10)}", cliente_id, booking_id,
                decision["stripe_account_id"], session.id or "",
                decision["amount_cents"], decision["currency"], session.url or "",
                capture_method, now, now,
            ),
        )
        connection.execute(
            """
            UPDATE bookings
            SET payment_status = CASE WHEN status = 'pending_payment' THEN 'pending' ELSE 'optional' END
            WHERE id = ?
            """,
            (booking_id,),
        )
        connection.commit()
    return session.url or ""


def _booking_payment_after_store(booking_id: str, request: Optional[Request] = None) -> str:
    booking = _get_booking_row_by_id(booking_id)
    if not booking or booking["payment_status"] not in {"pending", "optional"}:
        return ""
    try:
        return create_booking_payment_checkout(booking["cliente_id"], booking_id, request)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("Pago opcional no disponible booking=%s: %s", booking_id, exc)
        if booking["status"] == "pending_payment":
            _update_booking_record(
                booking_id,
                status="confirmed",
                confirmed_at=timeutils._utc_now_iso(),
                payment_status="not_required",
            )
        return ""


def _booking_reply_channel(booking_row: sqlite3.Row) -> str:
    """Canal por el que este cliente hablo con el negocio ("" si fue por la web)."""
    origen = str(booking_row["source"] or "").strip().lower()
    if "whatsapp" in origen:
        return "whatsapp"
    if origen == "voice":
        return "sms"  # una llamada no tiene canal de vuelta
    return ""


def _channels_reaching_customer(booking_row: sqlite3.Row, channels: Dict[str, bool]) -> Dict[str, bool]:
    """Los canales elegidos por el negocio, corregidos para que LLEGUEN a este cliente.

    Regla unica de entrega: manda lo que el negocio ha configurado en Seguimiento;
    si con eso no se puede alcanzar al cliente, se usa el canal por el que el
    escribio. Nace de un caso real: por WhatsApp el email es opcional, asi que un
    cliente sin email no recibia NADA --ni confirmacion tras pagar la señal, ni
    recordatorio-- porque los canales por defecto son solo email.

    Nunca enciende un canal de pago por su cuenta si ya hay otro que sirve.
    """
    efectivos = dict(channels)
    llega_email = bool(channels.get("email")) and bool(str(booking_row["email"] or "").strip())
    if llega_email or channels.get("whatsapp") or channels.get("sms"):
        return efectivos  # con lo configurado se le alcanza: no se toca nada
    propio = _booking_reply_channel(booking_row)
    if propio:
        efectivos[propio] = True
    return efectivos


async def notify_booking_paid(booking_row: sqlite3.Row, request: Optional[Request] = None) -> None:
    """Confirma la cita cuando entra el pago.

    Antes salia solo por email, y en WhatsApp el email es OPCIONAL: el cliente
    pagaba la señal y no recibia nada. Ya no hace falta logica propia: la entrega
    la resuelve `_channels_reaching_customer` para todos los avisos por igual.
    """
    try:
        await _send_booking_reminder_by_kind(booking_row, "confirmed", request, raise_on_failure=False)
    except Exception as exc:  # noqa: BLE001 - el pago ya esta cobrado, no se puede fallar aqui
        settings.logger.warning(
            "No se pudo confirmar tras el pago booking=%s: %s", booking_row["id"], exc
        )


async def process_booking_payment_webhook(data_object: Dict[str, Any]) -> bool:
    metadata = data_object.get("metadata") or {}
    if metadata.get("source") != "booking_payment":
        return False
    booking_id = str(metadata.get("booking_id") or "")
    cliente_id = str(metadata.get("cliente_id") or "")
    if not booking_id or not cliente_id:
        return True
    now = timeutils._utc_now_iso()
    session_id = str(data_object.get("id") or "")
    payment_intent_id = str(data_object.get("payment_intent") or "")
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT status, capture_method FROM booking_payments WHERE booking_id = ?",
            (booking_id,),
        ).fetchone()
        if row and row["status"] in ("paid", "preauthorized"):
            return True
        # Retencion (capture manual): la tarjeta queda autorizada pero NO cobrada.
        is_preauth = bool(row and row["capture_method"] == "manual")
        new_status = "preauthorized" if is_preauth else "paid"
        connection.execute(
            """
            UPDATE booking_payments
            SET status=?, checkout_session_id=?, payment_intent_id=?,
                paid_at=?, updated_at=?
            WHERE booking_id=? AND cliente_id=?
            """,
            (new_status, session_id, payment_intent_id, "" if is_preauth else now, now, booking_id, cliente_id),
        )
        booking = connection.execute(
            "SELECT status FROM bookings WHERE id = ? AND cliente_id = ?",
            (booking_id, cliente_id),
        ).fetchone()
        connection.execute(
            """
            UPDATE bookings
            SET payment_status=?,
                status=CASE WHEN status IN ('pending_payment', 'confirmed') THEN 'confirmed' ELSE status END,
                confirmed_at=CASE
                    WHEN status IN ('pending_payment', 'confirmed') AND confirmed_at='' THEN ?
                    ELSE confirmed_at
                END
            WHERE id=? AND cliente_id=?
            """,
            (new_status, now, booking_id, cliente_id),
        )
        connection.commit()
    _record_booking_audit(
        booking_id, cliente_id,
        "booking_payment_preauthorized" if is_preauth else "booking_payment_paid",
        {"checkout_session_id": session_id},
    )
    refreshed = _get_booking_row_by_id(booking_id)
    if refreshed and refreshed["status"] == "confirmed" and booking and booking["status"] == "pending_payment":
        await notify_booking_paid(refreshed)
    return True


def process_booking_payment_expired_webhook(data_object: Dict[str, Any]) -> bool:
    metadata = data_object.get("metadata") or {}
    if metadata.get("source") != "booking_payment":
        return False
    booking_id = str(metadata.get("booking_id") or "")
    cliente_id = str(metadata.get("cliente_id") or "")
    if not booking_id or not cliente_id:
        return True
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        booking = connection.execute(
            "SELECT status, payment_status FROM bookings WHERE id = ? AND cliente_id = ?",
            (booking_id, cliente_id),
        ).fetchone()
        if not booking or booking["payment_status"] == "paid":
            return True
        connection.execute(
            "UPDATE booking_payments SET status='expired', updated_at=? WHERE booking_id=? AND cliente_id=?",
            (now, booking_id, cliente_id),
        )
        if booking["status"] == "pending_payment":
            connection.execute(
                "UPDATE bookings SET status='cancelled', payment_status='expired', cancelled_at=? WHERE id=?",
                (now, booking_id),
            )
        else:
            connection.execute(
                "UPDATE bookings SET payment_status='expired' WHERE id=?",
                (booking_id,),
            )
        connection.commit()
    _record_booking_audit(booking_id, cliente_id, "booking_payment_expired", {})
    return True


def _booking_payment_for_action(cliente_id: str, booking_id: str) -> sqlite3.Row:
    booking_row = _load_booking_or_404(booking_id)
    if booking_row["cliente_id"] != cliente_id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    payment = _booking_payment_row(booking_id)
    if not payment or not payment["payment_intent_id"]:
        raise HTTPException(status_code=409, detail="Esta reserva no tiene un pago Stripe asociado.")
    return payment


def capture_booking_payment(
    cliente_id: str, booking_id: str, *, amount_cents: Optional[int] = None, reason: str = ""
) -> Dict[str, Any]:
    """Cobra una retencion (pre-auth): captura total o parcial del PaymentIntent.

    Uso tipico: no-show o cancelacion fuera de plazo. La captura parcial libera
    automaticamente el resto de la retencion en Stripe."""
    payment = _booking_payment_for_action(cliente_id, booking_id)
    if payment["status"] != "preauthorized":
        raise HTTPException(status_code=409, detail="Solo se puede cobrar una retencion pendiente.")
    amount = int(amount_cents or payment["amount_cents"] or 0)
    if amount <= 0 or amount > int(payment["amount_cents"] or 0):
        raise HTTPException(status_code=400, detail="Importe de cobro invalido.")
    stripe_gateway._stripe_init()
    try:
        stripe_gateway.stripe.PaymentIntent.capture(
            payment["payment_intent_id"],
            amount_to_capture=amount,
            stripe_account=payment["stripe_account_id"] or None,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Stripe capture fallo booking=%s: %s", booking_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo cobrar la retencion en Stripe.") from exc
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE booking_payments SET status='paid', amount_cents=?, paid_at=?, updated_at=? WHERE booking_id=?",
            (amount, now, now, booking_id),
        )
        connection.execute(
            "UPDATE bookings SET payment_status='paid' WHERE id=? AND cliente_id=?",
            (booking_id, cliente_id),
        )
        connection.commit()
    _record_booking_audit(
        booking_id, cliente_id, "booking_payment_captured",
        {"amount_cents": amount, "reason": textnorm._sanitize_text(reason)},
    )
    return {"payment_status": "paid", "amount_cents": amount}


def release_booking_payment(cliente_id: str, booking_id: str, *, reason: str = "") -> Dict[str, Any]:
    """Libera una retencion sin cobrar (cancela el PaymentIntent pre-autorizado)."""
    payment = _booking_payment_for_action(cliente_id, booking_id)
    if payment["status"] != "preauthorized":
        raise HTTPException(status_code=409, detail="Solo se puede liberar una retencion pendiente.")
    stripe_gateway._stripe_init()
    try:
        stripe_gateway.stripe.PaymentIntent.cancel(
            payment["payment_intent_id"],
            stripe_account=payment["stripe_account_id"] or None,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Stripe release fallo booking=%s: %s", booking_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo liberar la retencion en Stripe.") from exc
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE booking_payments SET status='released', updated_at=? WHERE booking_id=?",
            (now, booking_id),
        )
        connection.execute(
            "UPDATE bookings SET payment_status='released' WHERE id=? AND cliente_id=?",
            (booking_id, cliente_id),
        )
        connection.commit()
    _record_booking_audit(
        booking_id, cliente_id, "booking_payment_released",
        {"reason": textnorm._sanitize_text(reason)},
    )
    return {"payment_status": "released", "amount_cents": 0}


def _refund_customer_payment_for_booking(
    cliente_id: str, booking_id: str, *, amount_cents: Optional[int] = None, reason: str = ""
) -> Dict[str, Any]:
    """Reembolsa el ultimo customer_payment cobrado de una cita (pago por enlace/POS).
    Fallback de ``refund_booking_payment`` cuando la cita no se pago por la reserva
    (booking_payments) sino por un enlace directo o POS (customer_payments)."""
    with db._get_db_connection() as connection:
        payment = connection.execute(
            "SELECT * FROM customer_payments WHERE cliente_id=? AND booking_id=? "
            "AND status IN ('paid','partially_refunded') ORDER BY created_at DESC LIMIT 1",
            (cliente_id, booking_id),
        ).fetchone()
    if not payment or not payment["stripe_payment_intent_id"]:
        raise HTTPException(status_code=409, detail="Esta cita no tiene un pago reembolsable.")
    total = int(payment["amount_cents"] or 0)
    amount = int(amount_cents or total)
    if amount <= 0 or amount > total:
        raise HTTPException(status_code=400, detail="Importe de reembolso invalido.")
    stripe_gateway._stripe_init()
    kwargs: Dict[str, Any] = {"payment_intent": payment["stripe_payment_intent_id"]}
    if payment["stripe_account_id"]:
        kwargs["stripe_account"] = payment["stripe_account_id"]
    if amount < total:
        kwargs["amount"] = amount
    try:
        stripe_gateway.stripe.Refund.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Stripe refund (customer_payment) fallo booking=%s: %s", booking_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo crear el reembolso en Stripe.") from exc
    new_status = "refunded" if amount >= total else "partially_refunded"
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE customer_payments SET status=?, updated_at=? WHERE id=?",
            (new_status, now, payment["id"]),
        )
        connection.execute(
            "UPDATE bookings SET payment_status=? WHERE id=? AND cliente_id=? AND payment_status='paid'",
            (new_status, booking_id, cliente_id),
        )
        connection.commit()
    _record_booking_audit(
        booking_id, cliente_id, "booking_payment_refunded",
        {"amount_cents": amount, "partial": amount < total, "reason": textnorm._sanitize_text(reason), "via": "customer_payment"},
    )
    return {"payment_status": new_status, "amount_cents": amount}


def refund_booking_payment(
    cliente_id: str, booking_id: str, *, amount_cents: Optional[int] = None, reason: str = ""
) -> Dict[str, Any]:
    """Reembolso total o parcial de un pago de cita ya cobrado. Cubre los DOS sistemas:
    pago de la reserva (booking_payments) y, como fallback, pago directo por enlace/POS
    (customer_payments). Asi el boton "Reembolsar" del detalle de cita funciona siempre."""
    booking_row = _load_booking_or_404(booking_id)
    if booking_row["cliente_id"] != cliente_id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    payment = _booking_payment_row(booking_id)
    if not payment or not payment["payment_intent_id"] or payment["status"] not in ("paid", "partially_refunded"):
        return _refund_customer_payment_for_booking(
            cliente_id, booking_id, amount_cents=amount_cents, reason=reason
        )
    total = int(payment["amount_cents"] or 0)
    amount = int(amount_cents or total)
    if amount <= 0 or amount > total:
        raise HTTPException(status_code=400, detail="Importe de reembolso invalido.")
    stripe_gateway._stripe_init()
    try:
        refund_kwargs: Dict[str, Any] = {"payment_intent": payment["payment_intent_id"]}
        if amount < total:
            refund_kwargs["amount"] = amount
        if payment["stripe_account_id"]:
            refund_kwargs["stripe_account"] = payment["stripe_account_id"]
        stripe_gateway.stripe.Refund.create(**refund_kwargs)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Stripe refund fallo booking=%s: %s", booking_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo crear el reembolso en Stripe.") from exc
    new_status = "refunded" if amount >= total else "partially_refunded"
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE booking_payments SET status=?, refunded_at=?, updated_at=? WHERE booking_id=?",
            (new_status, now, now, booking_id),
        )
        connection.execute(
            "UPDATE bookings SET payment_status=? WHERE id=? AND cliente_id=?",
            (new_status, booking_id, cliente_id),
        )
        connection.commit()
    _record_booking_audit(
        booking_id, cliente_id, "booking_payment_refunded",
        {"amount_cents": amount, "partial": amount < total, "reason": textnorm._sanitize_text(reason)},
    )
    return {"payment_status": new_status, "amount_cents": amount}


# ─────────────────────────────────────────────────────────────────────────────
# Politica de cancelación / no-show automatica y configurable (generica por tenant)
#
# El pliego exige que el sistema aplique automaticamente la politica de
# cancelacion (reembolsos o penalizaciones segun ventana temporal). Es opt-in:
# por defecto deshabilitada para no sorprender a tenants existentes. Cuando esta
# activa y auto_apply=1, al cancelar o marcar no-show se actua sobre el pago ya
# autorizado (captura penalizacion de una retencion, libera el resto o reembolsa
# la parte no penalizada de un pago ya cobrado). Nunca crea cargos nuevos: solo
# opera sobre dinero que el cliente ya autorizo en la reserva.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CANCELLATION_POLICY: Dict[str, Any] = {
    "enabled": False,
    "free_cancel_hours": 24,
    "late_cancel_fee_pct": 0,
    "no_show_fee_pct": 100,
    "auto_apply": True,
    "policy_text": "",
}


def _clamp_pct(value: Any, default: int = 0) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def get_cancellation_policy(cliente_id: str) -> Dict[str, Any]:
    """Politica de cancelación del tenant (con defaults si no hay fila)."""
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM cancellation_policies WHERE cliente_id=?",
            (cliente_id,),
        ).fetchone()
    if row is None:
        return dict(DEFAULT_CANCELLATION_POLICY)
    return {
        "enabled": bool(row["enabled"]),
        "free_cancel_hours": max(0, int(row["free_cancel_hours"] or 0)),
        "late_cancel_fee_pct": _clamp_pct(row["late_cancel_fee_pct"]),
        "no_show_fee_pct": _clamp_pct(row["no_show_fee_pct"], 100),
        "auto_apply": bool(row["auto_apply"]),
        "policy_text": str(row["policy_text"] or ""),
    }


def save_cancellation_policy(cliente_id: str, **fields: Any) -> Dict[str, Any]:
    """Crea/actualiza la politica del tenant. Valida y normaliza los valores."""
    current = get_cancellation_policy(cliente_id)
    merged = {**current, **{k: v for k, v in fields.items() if v is not None}}
    enabled = 1 if merged.get("enabled") else 0
    auto_apply = 1 if merged.get("auto_apply", True) else 0
    free_hours = max(0, int(merged.get("free_cancel_hours") or 0))
    late_pct = _clamp_pct(merged.get("late_cancel_fee_pct"))
    no_show_pct = _clamp_pct(merged.get("no_show_fee_pct"), 100)
    policy_text = textnorm._sanitize_text(str(merged.get("policy_text") or ""), allow_multiline=True)[:1200]
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO cancellation_policies
                (cliente_id, enabled, free_cancel_hours, late_cancel_fee_pct,
                 no_show_fee_pct, auto_apply, policy_text, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id) DO UPDATE SET
                enabled=excluded.enabled,
                free_cancel_hours=excluded.free_cancel_hours,
                late_cancel_fee_pct=excluded.late_cancel_fee_pct,
                no_show_fee_pct=excluded.no_show_fee_pct,
                auto_apply=excluded.auto_apply,
                policy_text=excluded.policy_text,
                updated_at=excluded.updated_at
            """,
            (cliente_id, enabled, free_hours, late_pct, no_show_pct, auto_apply, policy_text, now),
        )
        connection.commit()
    return get_cancellation_policy(cliente_id)


def _service_policy_overrides(cliente_id: str, slug: str) -> Dict[str, Optional[int]]:
    """Overrides de politica por servicio (NULL = hereda del tenant)."""
    if not slug:
        return {}
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT cancel_free_hours, cancel_late_fee_pct, no_show_fee_pct "
            "FROM services WHERE cliente_id=? AND slug=?",
            (cliente_id, slug),
        ).fetchone()
    if row is None:
        return {}
    out: Dict[str, Optional[int]] = {}
    if row["cancel_free_hours"] is not None:
        out["free_cancel_hours"] = max(0, int(row["cancel_free_hours"]))
    if row["cancel_late_fee_pct"] is not None:
        out["late_cancel_fee_pct"] = _clamp_pct(row["cancel_late_fee_pct"])
    if row["no_show_fee_pct"] is not None:
        out["no_show_fee_pct"] = _clamp_pct(row["no_show_fee_pct"])
    return out


def _resolve_cancellation_policy_for_booking(booking_row: sqlite3.Row) -> Dict[str, Any]:
    cliente_id = booking_row["cliente_id"]
    policy = get_cancellation_policy(cliente_id)
    try:
        slug = booking_row["service_id"] or ""
    except (KeyError, IndexError):
        slug = ""
    policy.update(_service_policy_overrides(cliente_id, slug))
    return policy


def _hours_until_booking(booking_row: sqlite3.Row, *, now: Optional[datetime] = None) -> Optional[float]:
    start_at = ""
    try:
        start_at = booking_row["start_at"] or ""
    except (KeyError, IndexError):
        start_at = ""
    if not start_at:
        return None
    start_dt = timeutils._from_utc_iso(start_at)
    if not start_dt:
        return None
    ref = now or timeutils._utc_now()
    return (start_dt - ref).total_seconds() / 3600.0


def compute_cancellation_outcome(
    booking_row: sqlite3.Row, *, kind: str = "cancel", now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Calcula penalizacion/reembolso segun la politica, sin tocar Stripe.

    kind: 'cancel' (aplica ventana de cortesia) o 'no_show' (siempre penaliza).
    """
    policy = _resolve_cancellation_policy_for_booking(booking_row)
    try:
        price_cents = int(booking_row["service_price_cents"] or 0)
    except (KeyError, IndexError, TypeError):
        price_cents = 0
    hours_until = _hours_until_booking(booking_row, now=now)
    within_free = False
    if kind == "no_show":
        fee_pct = int(policy["no_show_fee_pct"])
    else:
        within_free = (
            hours_until is None
            or hours_until >= float(policy["free_cancel_hours"])
        )
        fee_pct = 0 if within_free else int(policy["late_cancel_fee_pct"])
    fee_cents = round(price_cents * fee_pct / 100) if price_cents > 0 else 0
    refund_cents = max(0, price_cents - fee_cents) if price_cents > 0 else 0
    return {
        "enabled": bool(policy["enabled"]),
        "auto_apply": bool(policy["auto_apply"]),
        "kind": kind,
        "within_free_window": within_free,
        "free_cancel_hours": int(policy["free_cancel_hours"]),
        "hours_until": None if hours_until is None else round(hours_until, 1),
        "fee_pct": fee_pct,
        "fee_cents": fee_cents,
        "refund_cents": refund_cents,
        "price_cents": price_cents,
        "currency": "eur",
        "policy_text": str(policy["policy_text"] or ""),
    }


def apply_cancellation_policy(
    booking_row: sqlite3.Row, *, kind: str, actor_source: str = "system"
) -> Dict[str, Any]:
    """Aplica automaticamente la politica al cancelar o marcar no-show.

    Solo actua sobre el pago ya autorizado de la cita (retencion o cobro). Es
    idempotente y nunca bloquea el flujo de cancelación: si Stripe falla, deja
    constancia en auditoria y devuelve el calculo para gestion manual.
    """
    outcome = compute_cancellation_outcome(booking_row, kind=kind)
    cliente_id = booking_row["cliente_id"]
    booking_id = booking_row["id"]
    outcome["action"] = "none"
    if not outcome["enabled"]:
        return outcome
    # Registro informativo siempre que la politica este activa.
    _record_booking_audit(
        booking_id, cliente_id, "cancellation_policy_evaluated",
        {
            "kind": kind, "source": actor_source,
            "fee_pct": outcome["fee_pct"], "fee_cents": outcome["fee_cents"],
            "refund_cents": outcome["refund_cents"],
            "within_free_window": outcome["within_free_window"],
        },
    )
    if not outcome["auto_apply"]:
        return outcome
    payment = _booking_payment_row(booking_id)
    if payment is None:
        return outcome
    status = payment["status"]
    held_or_paid = int(payment["amount_cents"] or 0)
    fee = int(outcome["fee_cents"])
    try:
        if status == "preauthorized":
            if fee <= 0:
                release_booking_payment(cliente_id, booking_id, reason=f"politica:{kind}:cortesia")
                outcome["action"] = "released"
            else:
                charge = min(fee, held_or_paid)
                capture_booking_payment(cliente_id, booking_id, amount_cents=charge, reason=f"politica:{kind}")
                outcome["action"] = "charged"
                outcome["charged_cents"] = charge
        elif status in ("paid", "partially_refunded"):
            refund_amt = max(0, held_or_paid - fee)
            if refund_amt > 0:
                refund_booking_payment(cliente_id, booking_id, amount_cents=refund_amt, reason=f"politica:{kind}")
                outcome["action"] = "refunded"
                outcome["refunded_cents"] = refund_amt
        _record_booking_audit(
            booking_id, cliente_id, "cancellation_policy_applied",
            {"kind": kind, "source": actor_source, "action": outcome["action"],
             "fee_cents": fee, "fee_pct": outcome["fee_pct"]},
        )
    except HTTPException as exc:
        settings.logger.warning(
            "No se pudo aplicar politica de cancelación booking=%s: %s", booking_id, exc.detail
        )
        _record_booking_audit(
            booking_id, cliente_id, "cancellation_policy_failed",
            {"kind": kind, "source": actor_source, "error": str(getattr(exc, "detail", exc))},
        )
    return outcome


def _latest_booking_for_contact(
    cliente_id: str, *, phone: str = "", email: str = ""
) -> Optional[sqlite3.Row]:
    """Ultima cita activa (confirmada o pendiente) que coincide con un teléfono o
    email. Permite que la IA envie el enlace de pago sin pedir el número de reserva
    cuando ya conoce al cliente (telefono de la llamada/WhatsApp o contacto dado)."""
    norm_phone = crm._normalize_phone_for_match(phone)
    norm_email = textnorm._sanitize_text(email).strip().lower()
    if not norm_phone and not norm_email:
        return None
    with db._get_db_connection() as connection:
        rows = connection.execute(
            # `pending_payment` es imprescindible: es el estado de quien tiene un pago
            # pendiente, justo el que pide el enlace. Sin el, el asistente contestaba
            # "necesito tu número de reserva" a alguien cuyo telefono ya conocia.
            "SELECT * FROM bookings WHERE cliente_id=? "
            "AND status IN ('confirmed','pending_review','pending_payment') "
            "ORDER BY created_at DESC LIMIT 50",
            (cliente_id,),
        ).fetchall()
    for row in rows:
        if norm_phone and crm._normalize_phone_for_match(row["telefono"] or "") == norm_phone:
            return row
        if norm_email and (row["email"] or "").strip().lower() == norm_email:
            return row
    return None







# Cuanto catalogo cabe en el prompt. Un salon real tiene 186 servicios (~7.900
# caracteres, unos 2.000 tokens): entran de sobra y cuestan centimos. El tope
# existe solo para que un catalogo absurdo no reviente la ventana de contexto.
CATALOG_PROMPT_MAX_CHARS = 12000


def _service_catalog_prompt_block(
    cliente_id: str, location_id: str = "", max_chars: int = CATALOG_PROMPT_MAX_CHARS
) -> Tuple[str, bool]:
    """El catalogo para el prompt, y si ha entrado ENTERO.

    Antes se cortaba por las bravas a las 40 primeras lineas. Con 186 servicios
    eso dejaba 146 invisibles -entre ellos "Corte señora 20 €" o "Peinado de
    novia 90 €"- y el prompt ademas ordenaba no aceptar lo que no estuviera en la
    lista: el asistente negaba servicios reales, y llego a decir "15 €" por un
    corte de niño que cuesta 8. Por eso hace falta saber si la lista esta completa:
    cuando no lo esta, NO se puede afirmar que algo no existe.
    """
    lineas = _service_catalog_prompt_lines(cliente_id, location_id=location_id)
    if not lineas:
        return "", True
    incluidas: List[str] = []
    usados = 0
    for linea in lineas:
        if usados + len(linea) + 1 > max_chars:
            break
        incluidas.append(linea)
        usados += len(linea) + 1
    completo = len(incluidas) == len(lineas)
    texto = "\n".join(incluidas)
    if not completo:
        texto += "\n- (hay %d servicios mas que no caben en esta lista)" % (
            len(lineas) - len(incluidas)
        )
    return texto, completo


def _service_catalog_prompt_lines(cliente_id: str, location_id: str = "") -> List[str]:
    """Las lineas del catalogo AGRUPADAS por categoria, para el prompt.

    Sin la categoria, el modelo confunde familias: con 186 nombres seguidos, a una
    clienta que decia "se me cae mucho el pelo" le proponia un alisado. La
    categoria es el dato que separa "Tratamientos" de "Alisados".

    Si el negocio no ha categorizado su catalogo, salen planas como antes.
    """
    try:
        servicios = _public_services_for_booking(cliente_id, location_id=location_id)
    except Exception:  # noqa: BLE001
        servicios = []
    por_categoria: Dict[str, List[str]] = {}
    for servicio, linea in zip(servicios, _service_catalog_lines(cliente_id, location_id=location_id)):
        categoria = ""
        if isinstance(servicio, dict):
            categoria = textnorm._sanitize_text(str(servicio.get("category") or "")).strip()
        por_categoria.setdefault(categoria, []).append(linea)
    if len(por_categoria) <= 1:
        return _service_catalog_lines(cliente_id, location_id=location_id)
    salida: List[str] = []
    for categoria, lineas in por_categoria.items():
        salida.append("")
        salida.append("%s:" % (categoria or "Otros"))
        salida.extend(lineas)
    return [linea for linea in salida if linea != "" or salida.index(linea) > 0]


def _familias_que_exigen_valoracion(cliente_id: str) -> List[str]:
    """Familias de las que ESTE negocio no da precio: primero hay que ver al cliente.

    Sale de sus propias reglas (`business_rules`), no de codigo: familias con una
    regla activa para la intencion "precio" cuya accion es ofrecer cita. Otro
    negocio pone las suyas y esto cambia solo.

    Distingue de "pedir_foto": un alisado SI se puede presupuestar con una foto y
    reservar directamente; unas mechas no.
    """
    try:
        from backend import rules

        familias = []
        for regla in rules.listar(cliente_id, solo_activas=True):
            if regla["accion"] != "ofrecer_cita":
                continue
            if "precio" not in regla["intenciones"] and "presupuesto" not in regla["intenciones"]:
                continue
            familias.extend(regla["familias"])
        return sorted(set(f for f in familias if f))
    except Exception:  # noqa: BLE001
        return []


def precios_ocultos(cliente_id: str) -> bool:
    """Este negocio no da precios por mensaje. De NADA, no solo de unas familias.

    Lo pidio la duenya del salon: "es mas facil que no de precio de nada; quien
    quiera precio que nos llame, y si es un cambio de imagen, mechas o extensiones
    que coja cita para un diagnostico y le damos presupuesto". Su catalogo tiene
    191 servicios y aun no ha decidido cuales quiere publicar.

    Es opt-in por tenant (`booking.mostrar_precios`): quien no lo toque sigue
    ensenyando sus precios como siempre.
    """
    from backend import clients

    try:
        booking_cfg = clients._get_client_config(cliente_id).get("booking") or {}
    except Exception:  # noqa: BLE001 - nunca romper una respuesta por esto
        return False
    return booking_cfg.get("mostrar_precios") is False


def _exige_valoracion(nombre_servicio: str, familias: List[str]) -> bool:
    plano = textnorm._strip_accents(str(nombre_servicio or "").lower())
    return any(familia and familia in plano for familia in familias)


def _servicio_de_valoracion(cliente_id: str, location_id: str = "") -> Dict[str, Any]:
    """La cita corta y gratuita con la que el negocio valora antes de presupuestar.

    Se busca en SU catalogo (diagnostico / valoracion / presupuesto). Si no tiene
    ninguna, no se fuerza nada: se sigue como siempre.
    """
    for servicio in _public_services_for_booking(cliente_id, location_id=location_id):
        if not isinstance(servicio, dict):
            continue
        plano = textnorm._strip_accents(str(servicio.get("nombre") or "").lower())
        if any(p in plano for p in ("diagnostico", "valoracion", "presupuesto")):
            if "extension" not in plano:  # la generica, no la de un servicio suelto
                return servicio
    return {}


def _service_catalog_lines(cliente_id: str, location_id: str = "") -> List[str]:
    """Lineas "- Nombre · N min · precio" del catalogo REAL (tabla services), para los
    prompts de chat y voz: enumerar y presupuestar sin inventar precios ni duraciones.
    Fuente unica compartida (voice._voice_service_catalog delega aqui)."""
    services = _public_services_for_booking(cliente_id, location_id=location_id)
    # Si el negocio ha dicho que de estas familias no da precio, el precio NO se le
    # ensena al modelo. Con la cifra delante acababa soltandola a la clienta que
    # insistia cuatro veces ("las mechas tienen un precio de 80 EUR"), y ahi se
    # rompe una condicion del negocio. Lo que no tiene, no lo puede decir.
    sin_precio = _familias_que_exigen_valoracion(cliente_id)
    # Si el negocio no da precios por mensaje, el modelo NO ve ni uno: lo que no
    # tiene, no lo puede soltar.
    ninguno = precios_ocultos(cliente_id)
    lines: List[str] = []
    seen: set = set()
    for service in services:
        if not isinstance(service, dict):
            continue
        name = textnorm._sanitize_text(str(service.get("nombre") or service.get("name") or ""))
        if not name or name in seen:
            continue
        seen.add(name)
        # Sin la palabra "pack": para la clienta eso son sus mechas, no un
        # producto empaquetado. El nombre interno no cambia (los enlaces de las
        # citas ya cogidas dependen de el); solo lo que se le dice.
        parts = [textnorm.nombre_de_servicio_publico(name)]
        try:
            dur = int(service.get("duration_minutes") or 0)
        except (TypeError, ValueError):
            dur = 0
        if dur > 0:
            parts.append(f"{dur} min")
        try:
            price_cents = int(service.get("price_cents") or 0)
        except (TypeError, ValueError):
            price_cents = 0
        price_label = textnorm._sanitize_text(str(service.get("price_label") or ""))
        if ninguno:
            parts.append("precio: NO se da por mensaje")
        elif _exige_valoracion(name, sin_precio):
            parts.append("precio SOLO tras la cita de valoracion")
        elif price_cents > 0 and price_label:
            parts.append(price_label)
        elif price_cents <= 0:
            parts.append("a consultar")
        lines.append("- " + " · ".join(parts))
    return lines
