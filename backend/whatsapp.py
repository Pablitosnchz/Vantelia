"""Flujos conversacionales de WhatsApp Cloud API (refactor F3).

Webhook (verificacion de challenge + firma con WHATSAPP_APP_SECRET
obligatoria), resolucion phone_number_id -> cliente, dedup de mensajes,
flujo interactivo de agendado (pickers de servicio/empleado/fecha/hora)
y puente con el orquestador de chat.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import HTTPException, Request, Response

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from api_models import AppWhatsAppResponse, WhatsAppWebhookStatus
from backend import agenda, appstate, booking, chat, clients, commerce, crm, db, inbox, keywords, messaging, rag, settings, textnorm, timeutils, wa_demo, wa_flows, wa_onboarding

def _app_whatsapp_response(cliente_id: str, request: Request) -> AppWhatsAppResponse:
    cfg = clients._get_client_config(cliente_id)
    wa = dict(cfg.get("whatsapp", {}) or {})
    webhook_url = f"{textnorm._public_base_url(request).rstrip('/')}/whatsapp/webhook/{cliente_id}"
    plan_allows = bool(clients._plan_feature(cliente_id, "whatsapp_enabled"))
    access_token = messaging._whatsapp_access_token_for_client(cliente_id)
    verify_token = _whatsapp_verify_token_for_client(cliente_id)
    enabled = bool(wa.get("enabled", False))
    phone_number_id = str(wa.get("phone_number_id", "") or "").strip()
    if enabled and plan_allows and phone_number_id and access_token:
        status_value = "ready"
        status_label = "Conectado"
    elif enabled and not plan_allows:
        status_value = "plan_required"
        status_label = "Requiere plan con WhatsApp"
    elif enabled and not phone_number_id:
        status_value = "missing_phone"
        status_label = "Falta Phone Number ID"
    elif enabled and not access_token:
        status_value = "missing_token"
        status_label = "Falta token de envio en servidor"
    else:
        status_value = "disabled"
        status_label = "Desactivado"
    cuenta = wa_onboarding.get_account(cliente_id)
    if cuenta:
        status_value, status_label = "ready", "Conectado"
    return AppWhatsAppResponse(
        cliente_id=cliente_id,
        enabled=enabled,
        phone_number_id=phone_number_id,
        embedded_signup_available=wa_onboarding.embedded_signup_available(),
        meta_app_id=settings.WHATSAPP_APP_ID,
        es_config_id=settings.WHATSAPP_ES_CONFIG_ID,
        connected_number=cuenta.get("display_phone_number", "") if cuenta else "",
        connected_mode=cuenta.get("mode", "") if cuenta else "",
        connected_via_signup=bool(cuenta),
        access_token_env=str(wa.get("access_token_env", "") or ""),
        verify_token_env=str(wa.get("verify_token_env", "") or ""),
        webhook_url=webhook_url,
        verify_token=verify_token,
        plan_allows_whatsapp=plan_allows,
        access_token_configured=bool(access_token),
        verify_token_configured=bool(verify_token),
        status=status_value,
        status_label=status_label,
    )


def _whatsapp_phone_client_map() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for item in settings.WHATSAPP_PHONE_CLIENT_MAP.split(","):
        if ":" not in item:
            continue
        phone_number_id, cliente_id = item.split(":", 1)
        phone_number_id = phone_number_id.strip()
        cliente_id = cliente_id.strip()
        if phone_number_id and cliente_id:
            mapping[phone_number_id] = cliente_id
    with appstate.state_lock:
        for cliente_id, config in appstate.CONFIG_CLIENTES.items():
            whatsapp_cfg = config.get("whatsapp", {})
            phone_number_id = str(whatsapp_cfg.get("phone_number_id", "")).strip()
            if whatsapp_cfg.get("enabled") and phone_number_id:
                mapping[phone_number_id] = cliente_id
    # Conexiones self-service (Embedded Signup): mandan sobre el config, que es
    # donde estan las altas manuales antiguas.
    mapping.update(wa_onboarding.phone_client_map())
    return mapping


def _resolve_whatsapp_client_id(phone_number_id: str, forced_cliente_id: str = "") -> str:
    if forced_cliente_id:
        textnorm._assert_valid_client_id(forced_cliente_id)
        config = clients._get_client_config(forced_cliente_id)
        if not config.get("whatsapp", {}).get("enabled", False):
            raise HTTPException(status_code=404, detail="WhatsApp no esta activo para este cliente.")
        clients._require_plan_feature(
            forced_cliente_id,
            "whatsapp_enabled",
            "WhatsApp esta disponible en el plan Business.",
        )
        return forced_cliente_id

    mapping = _whatsapp_phone_client_map()
    cliente_id = mapping.get(str(phone_number_id or "").strip()) or settings.WHATSAPP_DEFAULT_CLIENT_ID
    if not cliente_id:
        raise HTTPException(status_code=404, detail="No se pudo asociar este numero de WhatsApp a un cliente.")
    textnorm._assert_valid_client_id(cliente_id)
    config = clients._get_client_config(cliente_id)
    if not config.get("whatsapp", {}).get("enabled", False):
        raise HTTPException(status_code=404, detail="WhatsApp no esta activo para este cliente.")
    clients._require_plan_feature(
        cliente_id,
        "whatsapp_enabled",
        "WhatsApp esta disponible en el plan Business.",
    )
    return cliente_id


def _whatsapp_verify_token_for_client(cliente_id: str = "") -> str:
    if cliente_id:
        config = clients._get_client_config(cliente_id)
        configured_env = str(config.get("whatsapp", {}).get("verify_token_env", "")).strip()
        configured_token = messaging._whatsapp_env_value(configured_env)
        if configured_token:
            return configured_token
    return settings.WHATSAPP_VERIFY_TOKEN


def _whatsapp_session_id(cliente_id: str, from_number: str) -> str:
    digest = hashlib.sha256(f"{cliente_id}:{from_number}".encode("utf-8")).hexdigest()
    return f"wa_{digest[:40]}"


def _mark_whatsapp_message_if_new(
    *,
    message_id: str,
    cliente_id: str,
    phone_number_id: str,
    from_number: str,
) -> bool:
    cleaned_message_id = textnorm._sanitize_text(message_id)[:160]
    if not cleaned_message_id:
        return True
    with db._get_db_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM whatsapp_inbound_messages WHERE id = ?",
            (cleaned_message_id,),
        ).fetchone()
        if existing:
            return False
        connection.execute(
            """
            INSERT INTO whatsapp_inbound_messages (id, cliente_id, phone_number_id, from_number, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                cleaned_message_id,
                cliente_id,
                textnorm._sanitize_text(phone_number_id)[:120],
                textnorm._sanitize_text(from_number)[:80],
                timeutils._utc_now_iso(),
            ),
        )
        connection.commit()
    crm._crm_upsert_contact(
        cliente_id,
        phone=from_number,
        source="whatsapp",
        status="nuevo",
        entity_type="chat",
        entity_id=f"wa_{crm._normalize_crm_phone(from_number)}",
    )
    return True


def _verify_whatsapp_signature(raw_body: bytes, signature_header: str) -> None:
    if not settings.WHATSAPP_APP_SECRET:
        settings.logger.error(
            "WhatsApp webhook recibido pero WHATSAPP_APP_SECRET no esta configurado; "
            "rechazando por seguridad."
        )
        raise HTTPException(
            status_code=503,
            detail="WhatsApp webhook secret no configurado.",
        )
    if not signature_header:
        raise HTTPException(status_code=403, detail="Falta firma de WhatsApp.")
    expected = "sha256=" + hmac.new(
        settings.WHATSAPP_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=403, detail="Firma de WhatsApp invalida.")


async def _wa_send_service_picker(
    *, cliente_id: str, phone_number_id: str, to_number: str, location_id: str = "",
) -> bool:
    services = booking._public_services_for_booking(cliente_id, location_id=location_id)
    if not services:
        return False
    rows: List[Dict[str, Any]] = []
    for idx, svc in enumerate(services[:10]):
        nombre = str(svc.get("nombre") or svc.get("name") or "Servicio")[:24]
        descripcion = str(svc.get("descripcion") or svc.get("description") or "")[:72]
        rows.append({
            "id": f"svc_{idx}",
            "title": nombre,
            "description": descripcion or "Selecciona este servicio",
        })
    sections = [{"title": "Servicios disponibles", "rows": rows}]
    await messaging._send_whatsapp_list(
        cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=to_number,
        body="🛍️ Elige el servicio que necesitas:",
        button_text="Ver servicios", sections=sections, header="Agendar cita",
    )
    return True


async def _wa_send_location_picker(
    *, cliente_id: str, phone_number_id: str, to_number: str,
) -> bool:
    """Selector de CENTRO para negocios multi-centro con numero de WhatsApp generico
    (sin centro atado): el cliente elige sede antes del servicio, igual que en voz."""
    rows_db = agenda._list_location_rows(cliente_id, include_inactive=False)
    if len(rows_db) <= 1:
        return False
    rows: List[Dict[str, Any]] = []
    for loc in rows_db[:10]:
        rows.append({
            "id": f"loc_{loc['id']}",
            "title": str(loc["name"] or "Centro")[:24],
            "description": str(loc["address"] or "")[:72] or "Selecciona esta sede",
        })
    sections = [{"title": "Nuestros centros", "rows": rows}]
    await messaging._send_whatsapp_list(
        cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=to_number,
        body="🏢 ¿En que centro quieres la cita?",
        button_text="Ver centros", sections=sections, header="Agendar cita",
    )
    return True


def _wa_location_id(cliente_id: str, phone_number_id: str) -> str:
    """Centro asociado al numero de WhatsApp entrante (un numero por centro).
    '' si el numero no esta mapeado: el flujo se comporta como mono-centro."""
    if not phone_number_id:
        return ""
    return agenda._location_for_channel(cliente_id, whatsapp_phone_number_id=phone_number_id)


def _wa_employees_for_service(
    cliente_id: str, servicio: str, phone_number_id: str = "", location_id: str = ""
) -> List[sqlite3.Row]:
    location_id = location_id or _wa_location_id(cliente_id, phone_number_id)
    rows = agenda._list_public_employee_rows(
        cliente_id, include_inactive=False, location_id=location_id
    )
    if not servicio:
        return [r for r in rows if not bool(r["is_default"])]
    return [
        r for r in rows
        if not bool(r["is_default"]) and agenda._service_name_allowed_for_employee(cliente_id, r, servicio)
    ]


async def _wa_send_employee_picker(
    *, cliente_id: str, phone_number_id: str, to_number: str, servicio: str, location_id: str = "",
) -> List[sqlite3.Row]:
    employees = _wa_employees_for_service(cliente_id, servicio, phone_number_id, location_id=location_id)
    if len(employees) <= 1:
        return employees
    rows: List[Dict[str, Any]] = []
    for emp in employees[:10]:
        rows.append({
            "id": f"emp_{emp['id']}",
            "title": str(emp["name"])[:24],
            "description": str(emp["role_label"] or "Profesional")[:72],
        })
    sections = [{"title": "Profesionales", "rows": rows}]
    await messaging._send_whatsapp_list(
        cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=to_number,
        body=f"👨‍⚕️ Elige profesional para *{servicio}*:",
        button_text="Ver profesionales", sections=sections, header="Agendar cita",
    )
    return employees


def _wa_fecha_humana(fecha_iso: str) -> str:
    """Fecha hablada para confirmaciones ("lunes 6 de julio"), no ISO crudo."""
    try:
        return textnorm._format_date_es(textnorm._parse_date(fecha_iso).date())
    except Exception:  # noqa: BLE001
        return fecha_iso


def _wa_flow_key(cliente_id: str, from_number: str) -> str:
    return f"{cliente_id}:{from_number}"


def _wa_get_flow(cliente_id: str, from_number: str) -> appstate.WAFlowState:
    key = _wa_flow_key(cliente_id, from_number)
    flow = appstate.whatsapp_flows.get(key)
    if not flow:
        flow = appstate.WAFlowState(cliente_id=cliente_id, from_number=from_number, last_seen=time.time())
        appstate.whatsapp_flows[key] = flow
    flow.last_seen = time.time()
    return flow


def _wa_clear_flow(cliente_id: str, from_number: str) -> None:
    appstate.whatsapp_flows.pop(_wa_flow_key(cliente_id, from_number), None)


def _wa_reset_booking_fields(flow: appstate.WAFlowState) -> None:
    flow.location_id = ""
    flow.servicio = ""
    flow.employee_id = ""
    flow.employee_name = ""
    flow.fecha = ""
    flow.hora = ""
    flow.nombre = ""
    flow.email = ""
    flow.notas = ""
    flow.booking_code = ""
    flow.verify_phone = ""
    flow.verify_email = ""


# WhatsApp corta los titulos de fila a 24 caracteres y las descripciones a 72.
_WA_ROW_TITLE_MAX = 24
_WA_ROW_DESC_MAX = 72


def _wa_row_key(titulo: str) -> str:
    """Clave para comparar filas del menu ignorando emojis, acentos y mayusculas."""
    limpio = textnorm._strip_accents(str(titulo or "").lower())
    return re.sub(r"[^a-z0-9 ]+", "", limpio).strip()


def _wa_starter_rows(cliente_id: str, booking_enabled: bool) -> List[Dict[str, Any]]:
    """Filas del menu tomadas de las preguntas sugeridas que configura el negocio.

    El menu de WhatsApp estaba escrito a fuego con nueve opciones genericas
    (recomendar, comparar, estimar precio...) mientras el negocio configuraba las
    suyas en Tune AI y solo se aplicaban al widget web. Lo que se configura en el
    panel es lo que debe ver el cliente final, en cualquier canal.
    """
    try:
        config = clients._get_client_config(cliente_id)
        starters = settings._resolve_widget_starters(config, booking_enabled=booking_enabled)
    except Exception as exc:  # noqa: BLE001 - el menu nunca debe romper el canal
        settings.logger.warning("No se pudieron leer las sugerencias de %s: %s", cliente_id, exc)
        return []
    rows: List[Dict[str, Any]] = []
    for index, texto in enumerate(starters):
        limpio = textnorm._sanitize_text(texto).strip()
        if not limpio:
            continue
        rows.append({
            "id": f"menu_starter_{index}",
            "title": limpio[:_WA_ROW_TITLE_MAX],
            "description": limpio[:_WA_ROW_DESC_MAX] if len(limpio) > _WA_ROW_TITLE_MAX else "",
        })
    return rows


def _wa_starter_message(cliente_id: str, interactive_id: str, booking_enabled: bool) -> str:
    """Texto real detras de una fila `menu_starter_N` (lo que el cliente 'escribe')."""
    try:
        index = int(str(interactive_id).rsplit("_", 1)[1])
        config = clients._get_client_config(cliente_id)
        starters = settings._resolve_widget_starters(config, booking_enabled=booking_enabled)
        return str(starters[index])
    except Exception:  # noqa: BLE001 - id manipulado o sugerencias cambiadas entre medias
        return ""


def _wa_main_menu_sections(booking_enabled: bool, cliente_id: str = "") -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    # Las acciones de agenda no son sugerencias: abren flujos guiados propios.
    if booking_enabled:
        rows.append({"id": "menu_agendar", "title": "📅 Agendar cita", "description": "Reserva tu cita en pocos pasos"})
        rows.append({"id": "menu_disponibilidad", "title": "🕐 Ver disponibilidad", "description": "Consulta huecos libres"})
        rows.append({"id": "menu_cancelar_cita", "title": "Cancelar cita", "description": "Anula una reserva con tu codigo"})
        rows.append({"id": "menu_cambiar_cita", "title": "Cambiar cita", "description": "Reprograma fecha u hora"})

    configuradas = _wa_starter_rows(cliente_id, booking_enabled) if cliente_id else []
    if configuradas:
        # Las sugerencias del negocio sustituyen al bloque generico. Se descartan las
        # que dupliquen una accion de agenda ya listada arriba: la comparacion ignora
        # emojis y acentos, o "📅 Agendar cita" y "Agendar cita" pasarian por distintas.
        titulos = {_wa_row_key(r["title"]) for r in rows}
        rows.extend(r for r in configuradas if _wa_row_key(r["title"]) not in titulos)
    else:
        rows.append({"id": "menu_faq", "title": "💬 Preguntas frecuentes", "description": "Dudas habituales"})
        rows.append({"id": "menu_productos", "title": "🛍️ Productos / servicios", "description": "Catalogo del negocio"})
        rows.append({"id": "menu_recomendar", "title": "⭐ Recomendar", "description": "Te ayudo a elegir"})
        rows.append({"id": "menu_comparar", "title": "⚖️ Comparar", "description": "Comparativa de opciones"})
        rows.append({"id": "menu_estimar", "title": "💶 Estimar precio", "description": "Calcula coste aproximado"})
    return [{"title": "Opciones", "rows": rows[:10]}]


async def _wa_send_main_menu(
    *, cliente_id: str, phone_number_id: str, to_number: str, nombre_empresa: str, booking_enabled: bool, greeting: bool = False,
) -> None:
    # Menu apagado por el negocio (config `chat_menu`): saludo llano, sin lista de
    # opciones. Se centraliza aqui para cubrir TODOS los puntos que abren el menu.
    if not chat._menu_enabled(cliente_id):
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id,
            phone_number_id=phone_number_id,
            to_number=to_number,
            text=chat._simple_greeting_text(clients._get_client_config(cliente_id), nombre_empresa),
        )
        return
    body = (
        f"👋 ¡Hola! Soy el asistente de *{nombre_empresa}*. ¿En que puedo ayudarte hoy?"
        if greeting else f"📋 Menu principal de *{nombre_empresa}*. Elige una opcion:"
    )
    await messaging._send_whatsapp_list(
        cliente_id=cliente_id,
        phone_number_id=phone_number_id,
        to_number=to_number,
        body=body,
        button_text="Ver opciones",
        sections=_wa_main_menu_sections(booking_enabled, cliente_id),
    )


def _wa_closed_weekdays(cliente_id: str, config: Dict[str, Any]) -> set:
    """Dias cerrados REALES desde la matriz semanal compartida (empleados publicos, con
    fallback a config['booking']). Antes se leia config crudo y un dia reabierto solo en
    los horarios de empleados quedaba oculto en los pickers."""
    try:
        matrix = agenda._weekly_schedule_matrix(cliente_id, config)
    except Exception:  # noqa: BLE001
        matrix = []
    if len(matrix) == 7:
        return {item["weekday"] for item in matrix if item["closed"]}
    booking_cfg = config.get("booking", {}) or {}
    return set(int(x) for x in (booking_cfg.get("closed_weekdays") or []) if isinstance(x, (int, str)) and str(x).isdigit())


async def _wa_send_date_picker(
    *, cliente_id: str, phone_number_id: str, to_number: str, config: Dict[str, Any], header: str, body: str,
    employee_id: str = "", servicio: str = "", location_id: str = "",
) -> None:
    booking_cfg = config.get("booking", {}) or {}
    tz_name = booking_cfg.get("timezone") or settings.DEFAULT_TIMEZONE
    closed = _wa_closed_weekdays(cliente_id, config)
    try:
        today = datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        today = timeutils._utc_now().date()

    rows: List[Dict[str, Any]] = []
    offset = 0
    while len(rows) < 10 and offset < 30:
        candidate = today + timedelta(days=offset)
        offset += 1
        if candidate.weekday() in closed:
            continue

        try:
            if employee_id:
                _, available = await agenda._employee_slot_sets_for_day(
                    cliente_id,
                    candidate.isoformat(),
                    employee_id=employee_id,
                    servicio=servicio,
                )
            else:
                _, available = await agenda._public_slot_sets_for_day(
                    cliente_id,
                    candidate.isoformat(),
                    servicio=servicio,
                    location_id=location_id or _wa_location_id(cliente_id, phone_number_id),
                )
        except Exception:
            available = set()

        descripcion = candidate.strftime("%d/%m/%Y")
        if not available:
            block_reasons = agenda._agenda_block_reasons_for_day(cliente_id, candidate.isoformat())
            if block_reasons:
                first_reason = block_reasons[0].split(" (")[0][:40]
                descripcion = f"🚫 Bloqueado: {first_reason}"[:72]
            else:
                descripcion = "❌ Sin huecos"
        else:
            descripcion = f"✅ {len(available)} huecos · {descripcion}"[:72]

        label = textnorm._format_date_es(candidate).capitalize()[:24]
        if candidate == today:
            title = f"Hoy · {label}"
        elif candidate == today + timedelta(days=1):
            title = f"Manana · {label}"
        else:
            title = label
        rows.append({
            "id": f"date_{candidate.isoformat()}",
            "title": title[:24],
            "description": descripcion,
        })

    sections = [{"title": "Proximas fechas", "rows": rows}]
    await messaging._send_whatsapp_list(
        cliente_id=cliente_id,
        phone_number_id=phone_number_id,
        to_number=to_number,
        body=body,
        button_text="Elegir fecha",
        sections=sections,
        header=header,
    )


async def _wa_send_time_picker(
    *, cliente_id: str, phone_number_id: str, to_number: str, fecha_iso: str, fecha_humana: str,
    employee_id: str = "", servicio: str = "", location_id: str = "",
) -> bool:
    try:
        if employee_id:
            all_slots, available = await agenda._employee_slot_sets_for_day(
                cliente_id,
                fecha_iso,
                employee_id=employee_id,
                servicio=servicio,
            )
        else:
            all_slots, available = await agenda._public_slot_sets_for_day(
                cliente_id,
                fecha_iso,
                servicio=servicio,
                location_id=location_id or _wa_location_id(cliente_id, phone_number_id),
            )
    except HTTPException as exc:
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id,
            phone_number_id=phone_number_id,
            to_number=to_number,
            text=f"⚠️ {exc.detail}\n\nEscribe *menu* para volver al menu principal.",
        )
        return False
    except Exception:
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id,
            phone_number_id=phone_number_id,
            to_number=to_number,
            text="No he podido consultar la agenda ahora mismo. Intentalo en unos minutos.",
        )
        return False

    if not all_slots:
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id,
            phone_number_id=phone_number_id,
            to_number=to_number,
            text=rag._day_unavailable_explanation(cliente_id, fecha_iso, fecha_humana),
        )
        return False

    if not available:
        explicacion = rag._day_unavailable_explanation(cliente_id, fecha_iso, fecha_humana)
        # Diferenciar bloqueo vs lleno por reservas
        if "bloqueada" not in explicacion:
            booked_count = 0
            try:
                booked_count = len(agenda._booked_slots(cliente_id, fecha_iso))
            except Exception:
                pass
            if booked_count >= len(all_slots):
                explicacion = (
                    f"😔 El {fecha_humana} la agenda esta completa, no quedan huecos.\n\n"
                    f"Escribe *agendar* para elegir otra fecha o *menu* para volver."
                )
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id,
            phone_number_id=phone_number_id,
            to_number=to_number,
            text=explicacion,
        )
        return False

    sorted_slots = sorted(available)[:10]
    rows = [{"id": f"time_{slot}", "title": slot, "description": f"{fecha_humana[:60]}"} for slot in sorted_slots]
    sections = [{"title": "Huecos libres", "rows": rows}]
    await messaging._send_whatsapp_list(
        cliente_id=cliente_id,
        phone_number_id=phone_number_id,
        to_number=to_number,
        body=f"🕐 Huecos disponibles para *{fecha_humana}*. Elige hora:",
        button_text="Elegir hora",
        sections=sections,
    )
    return True


async def _wa_send_availability_overview(
    *, cliente_id: str, phone_number_id: str, to_number: str, config: Dict[str, Any],
) -> None:
    booking_cfg = config.get("booking", {}) or {}
    tz_name = booking_cfg.get("timezone") or settings.DEFAULT_TIMEZONE
    closed = _wa_closed_weekdays(cliente_id, config)
    try:
        today = datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        today = timeutils._utc_now().date()

    lines = ["🕐 *Disponibilidad proximos dias:*", ""]
    found = 0
    offset = 0
    while found < 7 and offset < 21:
        candidate = today + timedelta(days=offset)
        offset += 1
        if candidate.weekday() in closed:
            continue
        try:
            _, available = await agenda._public_slot_sets_for_day(
                cliente_id,
                candidate.isoformat(),
                location_id=_wa_location_id(cliente_id, phone_number_id),
            )
        except Exception:
            continue
        emoji = "✅" if available else "❌"
        label = textnorm._format_date_es(candidate)
        lines.append(f"{emoji} {label}: {len(available)} huecos")
        found += 1

    lines.append("")
    lines.append("Para agendar escribe *agendar*. Para volver al menu escribe *menu*.")
    await messaging._send_whatsapp_text(
        cliente_id=cliente_id,
        phone_number_id=phone_number_id,
        to_number=to_number,
        text="\n".join(lines),
    )


async def _wa_send_booking_summary(
    *, cliente_id: str, phone_number_id: str, to_number: str,
    flow: appstate.WAFlowState, reconocido: bool = False,
) -> None:
    """Resumen final con botones de confirmar, corregir datos o anadir nota.

    Punto UNICO donde termina el flujo, venga el cliente de escribir sus datos o de
    ser reconocido por su telefono. Los pasos de nota y de email dejaron de ser
    obligatorios: costaban una interaccion a todo el mundo para algo que casi nadie
    usaba.
    """
    flow.flow = "booking_confirm"
    fecha_humana = textnorm._format_date_es(textnorm._parse_date(flow.fecha).date())
    nombre_corto = flow.nombre.split()[0] if flow.nombre else ""
    lineas: List[str] = []
    if reconocido and nombre_corto:
        lineas.append(f"👋 Te he reconocido por tu numero, {nombre_corto}.")
        lineas.append("")
    lineas.append("📋 *Resumen de tu cita*")
    lineas.append("")
    lineas.append(f"👤 {flow.nombre}")
    if flow.email:
        lineas.append(f"📧 {flow.email}")
    lineas.append(f"📞 {flow.from_number}")
    lineas.append(f"🛍️ {flow.servicio or 'Servicio general'}")
    lineas.append(f"👨‍⚕️ {flow.employee_name or 'Asignacion automatica'}")
    lineas.append(f"📅 {fecha_humana}")
    lineas.append(f"🕐 {flow.hora}")
    if flow.notas:
        lineas.append(f"📝 Notas: {flow.notas}")
    lineas.append("")
    lineas.append("¿Confirmamos la cita?")
    botones = [("confirm_yes", "✅ Confirmar"), ("confirm_no", "❌ Cancelar")]
    # WhatsApp solo admite 3 botones: el tercero es corregir datos si le reconocimos
    # por el telefono, y anadir nota en el resto de casos.
    botones.append(
        ("data_fix", "✏️ Otros datos") if reconocido else ("notes_write", "✍️ Anadir nota")
    )
    await messaging._send_whatsapp_buttons(
        cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=to_number,
        header="Confirmar cita", body=chr(10).join(lineas), buttons=botones,
    )


async def _wa_create_booking(
    *, cliente_id: str, phone_number_id: str, to_number: str, flow: appstate.WAFlowState, config: Dict[str, Any],
    request: Request,
) -> bool:
    try:
        booking_dt = textnorm._parse_date(flow.fecha)
        agenda._validate_booking_window(cliente_id, booking_dt)

        wa_location_id = flow.location_id or _wa_location_id(cliente_id, phone_number_id)
        if flow.employee_id:
            employee_row = agenda._resolve_employee_for_booking(cliente_id, flow.employee_id)
        else:
            # Sin preferencia: elegir entre los profesionales del centro del numero entrante.
            employee_row = await agenda._resolve_public_booking_employee(
                cliente_id,
                flow.fecha,
                flow.hora,
                servicio=flow.servicio,
                location_id=wa_location_id,
            )
        service_duration = agenda._service_duration_minutes(cliente_id, flow.servicio, employee_row)
        if not await agenda._booking_slot_available(
            cliente_id, flow.fecha, flow.hora, employee_id=employee_row["id"], duration_minutes=service_duration
        ):
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=to_number,
                text="⚠️ Ese hueco ya no esta disponible. Escribe *agendar* para empezar de nuevo.",
            )
            return False

        try:
            stored_booking = await booking._create_booking_core(
                cliente_id,
                employee_row=employee_row,
                nombre=flow.nombre,
                email=flow.email,
                telefono=flow.from_number,
                servicio=flow.servicio,
                booking_date=flow.fecha,
                booking_time=flow.hora,
                notas=flow.notas or "",
                source="whatsapp",
                request=request,
                audit_extra={"channel": "whatsapp"},
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                await messaging._send_whatsapp_text(
                    cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=to_number,
                    text="⚠️ Ese horario acaba de ser reservado por otra persona. Escribe *agendar* para elegir otro tramo.",
                )
            else:
                await messaging._send_whatsapp_text(
                    cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=to_number,
                    text="No he podido confirmar la cita en el calendario. Intentalo en unos minutos.",
                )
            return False
        booking_id = stored_booking["id"]

    except HTTPException as exc:
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=to_number,
            text=f"⚠️ {exc.detail}",
        )
        return False
    except Exception as exc:  # noqa: BLE001
        settings.logger.exception("Error creando booking WhatsApp para %s: %s", cliente_id, exc)
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=to_number,
            text="No he podido registrar la cita. Intentalo en unos minutos.",
        )
        return False

    fecha_humana = textnorm._format_date_es(textnorm._parse_date(flow.fecha).date())
    is_pending_payment = bool(stored_booking and stored_booking["status"] == "pending_payment")
    title = "🟡 *Reserva pendiente de pago*" if is_pending_payment else "✅ *Cita confirmada*"
    confirmacion = (
        f"{title}\n\n"
        f"👤 {flow.nombre}\n"
        f"📧 {flow.email}\n"
        f"📞 {flow.from_number}\n"
        f"🛍️ {flow.servicio or 'Servicio general'}\n"
        f"👨‍⚕️ {flow.employee_name or 'Asignacion automatica'}\n"
        f"📅 {fecha_humana}\n"
        f"🕐 {flow.hora}\n"
    )
    if flow.notas:
        confirmacion += f"📝 Notas: {flow.notas}\n"
    # Mensaje de confirmacion que el negocio escribe en su panel (indicaciones para
    # llegar, que traer, etc.). Se usaba solo en la reserva por web: por WhatsApp el
    # cliente se quedaba sin ese aviso.
    mensaje_negocio = textnorm._sanitize_text(
        str((config.get("booking") or {}).get("success_message") or ""), allow_multiline=True
    ).strip()
    if mensaje_negocio:
        confirmacion += f"\n{mensaje_negocio}\n"
    # Auto-canje de bono (numero verificado del canal): descuenta 1 sesion y deja la
    # cita pagada. Best-effort; si la cita exige pago previo, el helper no toca nada.
    bono_redeemed = commerce.auto_redeem_package_for_booking(
        cliente_id, booking_id, extra_phone=flow.from_number
    )
    if bono_redeemed:
        left = int(bono_redeemed.get("sessions_left") or 0)
        confirmacion += (
            f"\n🎟 He descontado 1 sesion de tu bono *{bono_redeemed['package_name']}*: la cita queda pagada"
            + (f" (te quedan {left} sesiones).\n" if left > 0 else " (era tu ultima sesion).\n")
        )
    payment_row = booking._booking_payment_row(booking_id)
    if not bono_redeemed and payment_row and payment_row["checkout_url"]:
        payment_label = "Completa el pago para confirmar la cita" if is_pending_payment else "Pago opcional"
        # Sin esta nota, una senal de 50 EUR sobre un servicio de 120 parece el precio total.
        nota_pago = booking.payment_prompt_note(cliente_id, stored_booking, payment_row)
        confirmacion += f"\n💳 *{payment_label}:* {payment_row['checkout_url']}\n"
        if nota_pago:
            confirmacion += f"_{nota_pago}_\n"
    if is_pending_payment:
        confirmacion += (
            "\nEl hueco queda reservado de forma provisional hasta completar el pago. "
            "Si necesitas ayuda, responde a este WhatsApp.\n\n"
            "Escribe *menu* para volver al menu principal."
        )
    else:
        confirmacion += (
            "\nGuarda este mensaje con los datos de tu cita. "
            "Si necesitas cancelar o cambiarla, responde *cancelar*.\n\n"
            "Escribe *menu* para volver al menu principal."
        )
    await messaging._send_whatsapp_text(
        cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=to_number, text=confirmacion,
    )
    return True


async def _wa_send_booking_form(
    *, cliente_id: str, phone_number_id: str, to_number: str, location_id: str = "",
) -> bool:
    """Manda la reserva como FORMULARIO dentro de WhatsApp (Flows).

    Un solo mensaje: el cliente elige servicio, profesional y hora sin salir de la
    pantalla, en lugar de encadenar cuatro listas. Devuelve False si la funcion no
    esta configurada, y entonces el canal usa el flujo por mensajes de siempre.
    """
    if not wa_flows.enabled():
        return False
    config = clients._get_client_config(cliente_id)
    empresa = str(config.get("empresa") or "").strip() or config.get("nombre", "")
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": "Pedir cita"},
            "body": {"text": f"Reserva tu cita en {empresa} en menos de un minuto."},
            "footer": {"text": "Elige servicio, profesional y hora"},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token": wa_flows.make_flow_token(cliente_id, to_number),
                    "flow_id": wa_flows.flow_id(),
                    "flow_cta": "Pedir cita",
                    "flow_action": "data_exchange",
                    **({"mode": "draft"} if getattr(settings, "WHATSAPP_FLOW_DRAFT", False) else {}),
                },
            },
        },
    }
    enviado = await messaging._send_whatsapp_payload(
        cliente_id=cliente_id, phone_number_id=phone_number_id, payload=payload,
    )
    if not enviado:
        settings.logger.warning(
            "[flow] Meta rechazo el formulario de %s; se usa el flujo por mensajes.", cliente_id
        )
    return enviado


async def _wa_handle_flow_reply(
    *, cliente_id: str, phone_number_id: str, from_number: str,
    response_json: str, request: Request,
) -> bool:
    """Crea la cita con lo que devuelve el formulario.

    Reutiliza el mismo `_wa_create_booking` que el flujo por mensajes: el
    formulario solo cambia COMO se recogen los datos, no como se reserva.
    """
    datos = wa_flows.parse_flow_response(response_json)
    contexto = wa_flows.read_flow_token(datos.get("flow_token", ""))
    if not contexto or contexto.get("cliente_id") != cliente_id:
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text="Esa solicitud ha caducado. Escribe *cita* para empezar de nuevo.",
        )
        return False
    if not (datos.get("fecha") and datos.get("hora")):
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text="No he podido leer la hora elegida. Escribe *cita* para intentarlo otra vez.",
        )
        return False

    flow = _wa_get_flow(cliente_id, from_number)
    _wa_reset_booking_fields(flow)
    flow.servicio = datos["servicio"]
    flow.employee_id = datos["employee_id"]
    flow.fecha = datos["fecha"]
    flow.hora = datos["hora"]
    flow.nombre = datos["nombre"] or ""
    flow.email = datos["email"] or ""
    flow.notas = datos["notas"] or ""
    flow.location_id = flow.location_id or _wa_location_id(cliente_id, phone_number_id)
    if flow.employee_id:
        empleado = agenda._resolve_employee_for_booking(cliente_id, flow.employee_id)
        flow.employee_name = str(empleado["name"]) if empleado is not None else ""
    if not flow.nombre:
        conocido = crm.contact_by_phone(cliente_id, from_number)
        flow.nombre = str(conocido["name"]).strip() if conocido else "Cliente WhatsApp"

    config = clients._get_client_config(cliente_id)
    creada = await _wa_create_booking(
        cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
        flow=flow, config=config, request=request,
    )
    _wa_clear_flow(cliente_id, from_number)
    return creada


async def _wa_start_booking_flow(
    *, cliente_id: str, phone_number_id: str, from_number: str,
    flow: appstate.WAFlowState, config: Dict[str, Any],
) -> None:
    """Arranque COMUN del flujo de reserva (opcion de menu, texto libre e intencion IA):
    centro (solo si el negocio tiene varios y el numero no esta atado a uno) -> servicio
    -> profesional -> dia. Una sola definicion del orden de pasos."""
    effective_location = flow.location_id or _wa_location_id(cliente_id, phone_number_id)
    # Formulario dentro de WhatsApp: un solo mensaje en lugar de cuatro listas. Si no
    # esta configurado, o Meta lo rechaza, se sigue con el flujo por mensajes de
    # siempre sin que el cliente note nada.
    if await _wa_send_booking_form(
        cliente_id=cliente_id, phone_number_id=phone_number_id,
        to_number=from_number, location_id=effective_location,
    ):
        flow.flow = ""
        flow.location_id = effective_location
        return
    if not effective_location:
        flow.flow = "booking_location"
        if await _wa_send_location_picker(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
        ):
            return
        flow.flow = ""  # mono-centro: no hay nada que elegir
    services = booking._public_services_for_booking(cliente_id, location_id=effective_location)
    if services:
        flow.flow = "booking_service"
        await _wa_send_service_picker(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            location_id=effective_location,
        )
        return
    employees = _wa_employees_for_service(cliente_id, "", phone_number_id, location_id=effective_location)
    if len(employees) > 1:
        flow.flow = "booking_employee"
        await _wa_send_employee_picker(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            servicio="", location_id=effective_location,
        )
        return
    if employees:
        flow.employee_id = employees[0]["id"]
        flow.employee_name = employees[0]["name"]
    flow.flow = "booking_date"
    await _wa_send_date_picker(
        cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
        config=config, header="Agendar cita", body="📅 Elige el dia para tu cita:",
        employee_id=flow.employee_id, location_id=effective_location,
    )


async def _wa_handle_reminder_reply(
    *,
    cliente_id: str,
    phone_number_id: str,
    from_number: str,
    interactive_id: str,
    request: Request,
) -> None:
    """Procesa los botones del recordatorio: bkok_<id> confirma asistencia,
    bkcancel_<id> cancela la cita. Toda respuesta queda en booking_audit."""
    confirming = interactive_id.startswith("bkok_")
    booking_id = interactive_id.split("_", 1)[1] if "_" in interactive_id else ""
    booking_row = booking._get_booking_row_by_id(booking_id) if booking_id else None
    phone_norm = crm._normalize_phone_for_match(from_number)
    row_phone_norm = crm._normalize_phone_for_match(booking_row["telefono"] or "") if booking_row else ""
    if (
        not booking_row
        or booking_row["cliente_id"] != cliente_id
        or not phone_norm
        or phone_norm != row_phone_norm
    ):
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text="No he podido localizar esa cita. Escribe *menu* si necesitas ayuda.",
        )
        return
    if booking_row["status"] == "cancelled":
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text="Esa cita ya estaba cancelada. Escribe *menu* si quieres reservar otra.",
        )
        return
    if confirming:
        booking._mark_booking_confirmed_by_customer(
            booking_row["id"], cliente_id, channel="whatsapp", via="reminder_button",
        )
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text="✅ ¡Gracias! Tu asistencia queda confirmada. Te esperamos.",
        )
        return
    result = await booking._cancel_booking_by_code(
        cliente_id,
        booking_row["booking_code"] or "",
        trusted_phone=from_number,
        source="whatsapp_reminder_button",
        request=request,
    )
    if result.get("ok"):
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text="✅ Tu cita queda cancelada. Escribe *menu* si quieres reservar de nuevo.",
        )
    else:
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text=str(result.get("message") or "No se ha podido cancelar la cita. Escribe *menu* para gestionar tus citas."),
        )


async def _handle_whatsapp_message(
    *,
    cliente_id: str,
    phone_number_id: str,
    from_number: str,
    incoming_text: str,
    interactive_id: str,
    request: Request,
) -> None:
    config = clients._get_client_config(cliente_id)
    booking_enabled = bool(config["booking"]["enabled"])
    # Igual que chat/voz: el menu se presenta en nombre del NEGOCIO (Apariencia "empresa"),
    # con fallback al nombre del bot si el campo esta vacio.
    nombre_empresa = str(config.get("empresa") or "").strip() or config.get("nombre", "")
    flow = _wa_get_flow(cliente_id, from_number)

    # Conversacion tomada por una persona del negocio: el asistente se calla y solo
    # se guarda el mensaje, para que el equipo lo lea y conteste desde el panel.
    # Va lo PRIMERO: ni menu, ni flujos, ni reglas deben hablar por encima del humano.
    session_id = _whatsapp_session_id(cliente_id, from_number)
    # El numero por el que entra manda: es por el que hay que contestar.
    inbox.remember_inbound_number(session_id, phone_number_id)
    if inbox.bot_is_muted(session_id):
        rag._ensure_chat_session_record(
            session_id, cliente_id, request,
            origin_override=f"whatsapp:{from_number}",
            user_agent_override="WhatsApp Cloud API",
        )
        rag._record_chat_message(
            session_id=session_id, cliente_id=cliente_id,
            role="user", content=incoming_text, intent="human_takeover",
        )
        return

    iid = (interactive_id or "").strip()
    text_norm = textnorm._strip_accents((incoming_text or "").lower().strip())

    # Respuesta a los botones del recordatorio (confirmo / cancelar cita).
    if iid.startswith("bkok_") or iid.startswith("bkcancel_"):
        await _wa_handle_reminder_reply(
            cliente_id=cliente_id,
            phone_number_id=phone_number_id,
            from_number=from_number,
            interactive_id=iid,
            request=request,
        )
        return

    # Comando "menu" siempre rompe flujo y muestra menu
    if iid in ("menu_main", "back_menu") or text_norm in ("menu", "menu principal", "inicio", "opciones", "principal"):
        _wa_clear_flow(cliente_id, from_number)
        await _wa_send_main_menu(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            nombre_empresa=nombre_empresa, booking_enabled=booking_enabled,
        )
        return

    # Saludo PURO: responder con menu. Si el saludo trae una intencion ("Hola, quiero
    # cancelar mi cita R-1234"), la intencion manda (misma regla que el chat web).
    # Solo si NO hay flujo activo (para no romper paso a paso de agendar).
    if not flow.flow and chat._message_is_pure_greeting(incoming_text):
        await _wa_send_main_menu(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            nombre_empresa=nombre_empresa, booking_enabled=booking_enabled, greeting=True,
        )
        return

    # Reglas por palabra clave del negocio (opt-in, backend/keywords.py): configuracion
    # explicita del cliente, manda sobre las heuristicas de abajo. Solo sin flujo activo
    # (no secuestra un paso de agendado en curso). Sin la funcion activada no consulta nada.
    if not flow.flow:
        keyword_rule = keywords.match_reply(cliente_id, incoming_text)
        if keyword_rule:
            session_id = _whatsapp_session_id(cliente_id, from_number)
            rag._ensure_chat_session_record(
                session_id, cliente_id, request,
                origin_override=f"whatsapp:{from_number}",
                user_agent_override="WhatsApp Cloud API",
            )
            rag._record_chat_message(
                session_id=session_id, cliente_id=cliente_id,
                role="user", content=incoming_text,
            )
            rag._record_chat_message(
                session_id=session_id, cliente_id=cliente_id,
                role="assistant", content=keyword_rule["reply"], intent="keyword_rule",
            )
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text=keyword_rule["reply"],
            )
            return

    # Consulta de bono ("cuantas sesiones me quedan"): respuesta determinista con los
    # bonos del NUMERO VERIFICADO del canal (el remitente). Solo sin flujo activo.
    if not flow.flow and commerce._message_requests_package_balance(incoming_text):
        summary = commerce.packages_summary_for_contact(cliente_id, phone=from_number)
        texto = summary["mensaje"]
        if summary["count"]:
            texto += "\n\nAl reservar una cita del servicio incluido, la sesion se descuenta sola del bono."
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text=texto,
        )
        return

    # Trigger desde menu o texto
    trigger_agendar = iid == "menu_agendar" or text_norm in ("agendar", "agendar cita", "reservar", "reservar cita", "cita")
    trigger_disp = iid == "menu_disponibilidad" or text_norm in ("disponibilidad", "ver disponibilidad", "horarios", "huecos")
    trigger_cancel = iid == "menu_cancelar_cita" or booking._message_requests_cancel_booking(incoming_text)
    trigger_reschedule = iid == "menu_cambiar_cita" or booking._message_requests_reschedule_booking(incoming_text)

    if trigger_cancel and booking_enabled:
        _wa_reset_booking_fields(flow)
        flow.flow = "manage_cancel_code"
        code = booking._extract_booking_code_from_text(incoming_text)
        if code:
            flow.booking_code = code
            flow.flow = "manage_cancel_verify"
            result = await booking._cancel_booking_by_code(
                cliente_id,
                code,
                trusted_phone=from_number,
                source="whatsapp",
                request=request,
            )
            if result.get("ok"):
                _wa_clear_flow(cliente_id, from_number)
                await messaging._send_whatsapp_text(
                    cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                    text=f"✅ Listo, la cita {code} queda cancelada. Escribe *menu* para volver.",
                )
                return
            if not result.get("needs_verification"):
                _wa_clear_flow(cliente_id, from_number)
                await messaging._send_whatsapp_text(
                    cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                    text=f"⚠️ {result.get('error') or 'No se pudo cancelar la cita.'}",
                )
                return
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text=(
                "Para cancelar tu cita necesito el numero de reserva (formato *R-XXXX*)."
                if not flow.booking_code else
                "Por seguridad necesito verificar la reserva. Enviame el telefono o el email con el que hiciste la cita."
            ),
        )
        return

    if trigger_reschedule and booking_enabled:
        _wa_reset_booking_fields(flow)
        flow.flow = "manage_reschedule_code"
        flow.booking_code = booking._extract_booking_code_from_text(incoming_text)
        flow.verify_email = textnorm._extract_email_from_text(incoming_text)
        flow.verify_phone = textnorm._extract_phone_from_text(incoming_text)
        tz = config.get("booking", {}).get("timezone") or settings.DEFAULT_TIMEZONE
        flow.fecha = textnorm._extract_date_from_text(incoming_text, tz)
        flow.hora = textnorm._extract_time_from_text(incoming_text)
        if not flow.booking_code:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="Para cambiar tu cita necesito el numero de reserva (formato *R-XXXX*).",
            )
            return
        if not flow.fecha:
            flow.flow = "manage_reschedule_date"
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text=f"Perfecto. Indica la nueva fecha para la cita {flow.booking_code}.",
            )
            return
        if not flow.hora:
            flow.flow = "manage_reschedule_time"
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text=f"Indica la nueva hora para la cita {flow.booking_code}.",
            )
            return
        flow.flow = "manage_reschedule_verify"
        result = await booking._reschedule_booking_by_code(
            cliente_id,
            flow.booking_code,
            flow.fecha,
            flow.hora,
            trusted_phone=from_number,
            telefono=flow.verify_phone,
            email=flow.verify_email,
            source="whatsapp",
            request=request,
        )
        if result.get("ok"):
            _wa_clear_flow(cliente_id, from_number)
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text=f"✅ Listo, he cambiado la cita {flow.booking_code} al {_wa_fecha_humana(flow.fecha)} a las {flow.hora}. El numero de reserva sigue siendo el mismo.",
            )
            return
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text=(
                "Por seguridad necesito verificar la reserva. Enviame el telefono o el email con el que hiciste la cita."
                if result.get("needs_verification")
                else f"⚠️ {await booking._reschedule_failure_text(cliente_id, result, flow.fecha, flow.hora)}"
            ),
        )
        if not result.get("needs_verification"):
            _wa_clear_flow(cliente_id, from_number)
        return

    if trigger_agendar and booking_enabled:
        flow.flow = ""
        _wa_reset_booking_fields(flow)
        await _wa_start_booking_flow(
            cliente_id=cliente_id, phone_number_id=phone_number_id, from_number=from_number,
            flow=flow, config=config,
        )
        return

    if trigger_disp and booking_enabled:
        await _wa_send_availability_overview(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number, config=config,
        )
        return

    if flow.flow == "manage_cancel_code":
        code = booking._extract_booking_code_from_text(incoming_text)
        if not code:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="No he reconocido el numero de reserva. Debe tener formato *R-XXXX*.",
            )
            return
        flow.booking_code = code
        result = await booking._cancel_booking_by_code(
            cliente_id,
            code,
            trusted_phone=from_number,
            source="whatsapp",
            request=request,
        )
        if result.get("ok"):
            _wa_clear_flow(cliente_id, from_number)
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text=f"✅ Listo, la cita {code} queda cancelada. Escribe *menu* para volver.",
            )
            return
        if result.get("needs_verification"):
            flow.flow = "manage_cancel_verify"
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="Por seguridad necesito verificar la reserva. Enviame el telefono o el email con el que hiciste la cita.",
            )
            return
        _wa_clear_flow(cliente_id, from_number)
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text=f"⚠️ {result.get('error') or 'No se pudo cancelar la cita.'}",
        )
        return

    if flow.flow == "manage_cancel_verify":
        email = textnorm._extract_email_from_text(incoming_text)
        phone = textnorm._extract_phone_from_text(incoming_text)
        if not (email or phone):
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="Enviame el telefono o el email usado en la reserva para poder verificarla.",
            )
            return
        result = await booking._cancel_booking_by_code(
            cliente_id,
            flow.booking_code,
            trusted_phone=from_number,
            telefono=phone,
            email=email,
            source="whatsapp",
            request=request,
        )
        if result.get("ok"):
            _wa_clear_flow(cliente_id, from_number)
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text=f"✅ Listo, la cita {flow.booking_code} queda cancelada. Escribe *menu* para volver.",
            )
            return
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text=f"⚠️ {result.get('error') or 'No se pudo cancelar la cita.'}",
        )
        if not result.get("needs_verification"):
            _wa_clear_flow(cliente_id, from_number)
        return

    if flow.flow == "manage_reschedule_code":
        code = booking._extract_booking_code_from_text(incoming_text)
        if not code:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="No he reconocido el numero de reserva. Debe tener formato *R-XXXX*.",
            )
            return
        flow.booking_code = code
        flow.flow = "manage_reschedule_date"
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text=f"Indica la nueva fecha para la cita {flow.booking_code}.",
        )
        return

    if flow.flow == "manage_reschedule_date":
        tz = config.get("booking", {}).get("timezone") or settings.DEFAULT_TIMEZONE
        fecha = textnorm._extract_date_from_text(incoming_text, tz)
        if not fecha:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="No he reconocido la fecha. Puedes escribir, por ejemplo, *mañana* o *2026-06-15*.",
            )
            return
        flow.fecha = fecha
        flow.flow = "manage_reschedule_time"
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text=f"Indica la nueva hora para la cita {flow.booking_code}.",
        )
        return

    if flow.flow == "manage_reschedule_time":
        hora = textnorm._extract_time_from_text(incoming_text)
        if not hora:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="No he reconocido la hora. Escribela en formato *HH:MM*, por ejemplo *10:30*.",
            )
            return
        flow.hora = hora
        result = await booking._reschedule_booking_by_code(
            cliente_id,
            flow.booking_code,
            flow.fecha,
            flow.hora,
            trusted_phone=from_number,
            source="whatsapp",
            request=request,
        )
        if result.get("ok"):
            _wa_clear_flow(cliente_id, from_number)
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text=f"✅ Listo, he cambiado la cita {flow.booking_code} al {_wa_fecha_humana(flow.fecha)} a las {flow.hora}. El numero de reserva sigue siendo el mismo.",
            )
            return
        if result.get("needs_verification"):
            flow.flow = "manage_reschedule_verify"
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="Por seguridad necesito verificar la reserva. Enviame el telefono o el email con el que hiciste la cita.",
            )
            return
        _wa_clear_flow(cliente_id, from_number)
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text=f"⚠️ {await booking._reschedule_failure_text(cliente_id, result, flow.fecha, flow.hora)}",
        )
        return

    if flow.flow == "manage_reschedule_verify":
        email = textnorm._extract_email_from_text(incoming_text)
        phone = textnorm._extract_phone_from_text(incoming_text)
        if not (email or phone):
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="Enviame el telefono o el email usado en la reserva para poder verificarla.",
            )
            return
        result = await booking._reschedule_booking_by_code(
            cliente_id,
            flow.booking_code,
            flow.fecha,
            flow.hora,
            trusted_phone=from_number,
            telefono=phone,
            email=email,
            source="whatsapp",
            request=request,
        )
        if result.get("ok"):
            _wa_clear_flow(cliente_id, from_number)
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text=f"✅ Listo, he cambiado la cita {flow.booking_code} al {_wa_fecha_humana(flow.fecha)} a las {flow.hora}. El numero de reserva sigue siendo el mismo.",
            )
            return
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text=f"⚠️ {await booking._reschedule_failure_text(cliente_id, result, flow.fecha, flow.hora)}",
        )
        if not result.get("needs_verification"):
            _wa_clear_flow(cliente_id, from_number)
        return

    # FLUJO BOOKING - Centro (solo multi-centro con numero generico)
    if flow.flow == "booking_location":
        chosen = ""
        if iid.startswith("loc_"):
            chosen = iid[len("loc_"):]
        elif incoming_text.strip():
            for loc in agenda._list_location_rows(cliente_id, include_inactive=False):
                if textnorm._strip_accents(str(loc["name"] or "").lower()) == textnorm._strip_accents(incoming_text.lower().strip()):
                    chosen = loc["id"]
                    break
        row_loc = agenda._get_location_row(chosen, cliente_id=cliente_id) if chosen else None
        if not row_loc:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="No he reconocido el centro. Pulsa una opcion del listado o escribe *menu*.",
            )
            return
        flow.location_id = row_loc["id"]
        await _wa_start_booking_flow(
            cliente_id=cliente_id, phone_number_id=phone_number_id, from_number=from_number,
            flow=flow, config=config,
        )
        return

    # FLUJO BOOKING - Servicio
    if flow.flow == "booking_service":
        services = booking._public_services_for_booking(cliente_id, location_id=flow.location_id)
        chosen = ""
        if iid.startswith("svc_"):
            try:
                idx = int(iid[len("svc_"):])
                if 0 <= idx < len(services):
                    chosen = str(services[idx].get("nombre") or services[idx].get("name") or "")
            except ValueError:
                pass
        if not chosen and incoming_text.strip():
            for svc in services:
                nombre_svc = str(svc.get("nombre") or svc.get("name") or "")
                if textnorm._strip_accents(nombre_svc.lower()) == textnorm._strip_accents(incoming_text.lower().strip()):
                    chosen = nombre_svc
                    break
        if not chosen:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="No he reconocido el servicio. Pulsa una opcion del listado o escribe *menu*.",
            )
            return
        flow.servicio = chosen

        employees = _wa_employees_for_service(cliente_id, flow.servicio, phone_number_id, location_id=flow.location_id)
        if not employees:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text=f"⚠️ No hay profesionales disponibles para *{flow.servicio}*. Prueba con otro servicio.",
            )
            await _wa_send_service_picker(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                location_id=flow.location_id,
            )
            return
        if len(employees) == 1:
            flow.employee_id = employees[0]["id"]
            flow.employee_name = employees[0]["name"]
            flow.flow = "booking_date"
            await _wa_send_date_picker(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                config=config, header="Agendar cita", body=f"📅 Elige el dia para *{flow.servicio}* con *{flow.employee_name}*:",
                employee_id=flow.employee_id, servicio=flow.servicio, location_id=flow.location_id,
            )
        else:
            flow.flow = "booking_employee"
            await _wa_send_employee_picker(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                servicio=flow.servicio, location_id=flow.location_id,
            )
        return

    if flow.flow == "booking_employee":
        emp_id = ""
        if iid.startswith("emp_"):
            emp_id = iid[len("emp_"):]
        else:
            for emp in _wa_employees_for_service(cliente_id, flow.servicio, phone_number_id, location_id=flow.location_id):
                if textnorm._strip_accents(str(emp["name"]).lower()) == textnorm._strip_accents(incoming_text.lower().strip()):
                    emp_id = emp["id"]
                    break
        if not emp_id:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="No he reconocido el profesional. Pulsa una opcion del listado o escribe *menu*.",
            )
            return
        try:
            employee_row = agenda._resolve_employee_for_booking(cliente_id, emp_id)
        except HTTPException as exc:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text=f"⚠️ {exc.detail}",
            )
            return
        flow.employee_id = employee_row["id"]
        flow.employee_name = employee_row["name"]
        flow.flow = "booking_date"
        await _wa_send_date_picker(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            config=config, header="Agendar cita",
            body=f"📅 Elige el dia con *{flow.employee_name}*:",
            employee_id=flow.employee_id, servicio=flow.servicio, location_id=flow.location_id,
        )
        return

    if flow.flow == "booking_date":
        fecha_iso = ""
        if iid.startswith("date_"):
            fecha_iso = iid[len("date_"):]
        else:
            target = textnorm._resolve_relative_date_es(incoming_text, config["booking"]["timezone"])
            if target:
                fecha_iso = target.isoformat()
        if not fecha_iso:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="No he reconocido la fecha. Pulsa una opcion del listado o escribe *menu* para volver.",
            )
            return
        try:
            target_dt = textnorm._parse_date(fecha_iso)
            agenda._validate_booking_window(cliente_id, target_dt)
        except HTTPException as exc:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text=f"⚠️ {exc.detail}",
            )
            return
        flow.fecha = fecha_iso
        flow.flow = "booking_time"
        fecha_humana = textnorm._format_date_es(target_dt.date())
        ok = await _wa_send_time_picker(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            fecha_iso=fecha_iso, fecha_humana=fecha_humana,
            employee_id=flow.employee_id, servicio=flow.servicio, location_id=flow.location_id,
        )
        if not ok:
            flow.flow = "booking_date"
            flow.fecha = ""
            await _wa_send_date_picker(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                config=config, header="Elegir otra fecha", body="📅 Elige otra fecha disponible:",
                employee_id=flow.employee_id, servicio=flow.servicio, location_id=flow.location_id,
            )
        return

    if flow.flow == "booking_time":
        hora = ""
        if iid.startswith("time_"):
            hora = iid[len("time_"):]
        elif settings.TIME_PATTERN.match(incoming_text.strip()):
            hora = incoming_text.strip()
        if not hora:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="No he reconocido la hora. Pulsa un hueco del listado o escribe *menu*.",
            )
            return
        flow.hora = hora
        # Cliente que ya ha reservado antes: su telefono viene VERIFICADO por el canal,
        # asi que no tiene sentido volver a pedirle nombre y email. Se salta directo al
        # resumen, donde puede corregir los datos si hace falta.
        conocido = crm.contact_by_phone(cliente_id, from_number)
        if conocido and str(conocido["name"] or "").strip():
            flow.nombre = str(conocido["name"]).strip()[:80]
            flow.email = str(conocido["email"] or "").strip()[:120]
            await _wa_send_booking_summary(
                cliente_id=cliente_id, phone_number_id=phone_number_id,
                to_number=from_number, flow=flow, reconocido=True,
            )
            return
        flow.flow = "booking_name"
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text="👤 Perfecto. ¿Cual es tu *nombre completo*?",
        )
        return

    if flow.flow == "booking_name":
        nombre = (incoming_text or "").strip()
        if len(nombre) < 2:
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="Necesito un nombre valido (minimo 2 caracteres).",
            )
            return
        flow.nombre = nombre[:80]
        flow.flow = "booking_email"
        await messaging._send_whatsapp_buttons(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            body=(
                "📧 Si quieres la confirmacion tambien por email, escribelo ahora. "
                "Si no, pulsa *Sin email*: te la mando por aqui."
            ),
            buttons=[("email_skip", "🚫 Sin email")],
        )
        return

    if flow.flow == "booking_email":
        if iid == "email_skip" or text_norm in ("no", "sin email", "ninguno", "saltar", "omitir", "skip"):
            flow.email = ""
        else:
            email = (incoming_text or "").strip().lower()
            if not textnorm.EMAIL_RE.match(email):
                await messaging._send_whatsapp_text(
                    cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                    text="❌ Ese email no es valido. Escribelo como nombre@dominio.com o pulsa *Sin email*.",
                )
                return
            flow.email = email[:120]
        # El paso de notas se elimino del camino obligatorio: casi nadie lo usaba y
        # costaba una interaccion a todo el mundo. Ahora se ofrece en el resumen.
        await _wa_send_booking_summary(
            cliente_id=cliente_id, phone_number_id=phone_number_id,
            to_number=from_number, flow=flow,
        )
        return

    if flow.flow == "booking_notes":
        # Solo se llega aqui si el cliente pulso "Anadir nota" en el resumen: el paso
        # dejo de ser obligatorio porque casi nadie lo usaba y costaba una interaccion
        # a todos.
        flow.notas = (incoming_text or "").strip()[:500]
        await _wa_send_booking_summary(
            cliente_id=cliente_id, phone_number_id=phone_number_id,
            to_number=from_number, flow=flow,
        )
        return

    if flow.flow == "booking_confirm":
        # Los dos botones opcionales del resumen: anadir una nota o corregir los datos
        # que hemos rellenado nosotros al reconocer el telefono.
        if iid == "notes_write":
            flow.flow = "booking_notes"
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="✍️ Escribe tu nota o comentario para la cita:",
            )
            return
        if iid == "data_fix":
            flow.flow = "booking_name"
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="👤 Sin problema. ¿A nombre de quien hago la cita?",
            )
            return
        if iid == "confirm_yes" or text_norm in ("si", "confirmar", "confirmo", "ok", "vale"):
            ok = await _wa_create_booking(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                flow=flow, config=config, request=request,
            )
            _wa_clear_flow(cliente_id, from_number)
            if not ok:
                await _wa_send_main_menu(
                    cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                    nombre_empresa=nombre_empresa, booking_enabled=booking_enabled,
                )
            return
        if iid == "confirm_no" or text_norm in ("no", "cancelar", "cancela"):
            _wa_clear_flow(cliente_id, from_number)
            await messaging._send_whatsapp_text(
                cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
                text="Cita descartada. Escribe *menu* para volver al menu principal.",
            )
            return
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text="Pulsa Confirmar o Cancelar.",
        )
        return

    # Otras opciones del menu → delega a IA con flujo del prompt
    if iid in ("menu_faq", "menu_productos", "menu_recomendar", "menu_comparar", "menu_estimar"):
        intent_msg_map = {
            "menu_faq": "Muestrame las preguntas frecuentes principales.",
            "menu_productos": "Quiero informacion sobre productos o servicios disponibles.",
            "menu_recomendar": "Quiero que me recomiendes el producto o servicio que mejor encaja en mi caso.",
            "menu_comparar": "Quiero comparar productos o servicios.",
            "menu_estimar": "Ayudame a estimar precio aproximado.",
        }
        incoming_text = intent_msg_map.get(iid, incoming_text)

    # Sugerencia configurada por el negocio: el texto real de la pregunta es lo que
    # el cliente "escribe". El titulo de la fila viene recortado a 24 caracteres por
    # WhatsApp, asi que no sirve como mensaje.
    if iid.startswith("menu_starter_"):
        texto_sugerencia = _wa_starter_message(cliente_id, iid, booking_enabled)
        if texto_sugerencia:
            incoming_text = texto_sugerencia

    # Sin texto: pedir input
    if not incoming_text.strip():
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text="No he recibido texto. Escribe tu consulta o pulsa *menu*.",
        )
        return

    # Delegar al motor IA
    chat_response = await chat._process_chat_message(
        cliente_id=cliente_id,
        message=incoming_text,
        session_id=_whatsapp_session_id(cliente_id, from_number),
        request=request,
        origin_override=f"whatsapp:{from_number}",
        user_agent_override="WhatsApp Cloud API",
        trusted_phone=from_number,
    )

    if chat_response.mostrar_formulario and booking_enabled:
        # IA detecto intencion de agendar -> mismo arranque comun que el menu
        # (centro si hace falta -> servicio -> profesional -> dia).
        _wa_reset_booking_fields(flow)
        await messaging._send_whatsapp_text(
            cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
            text=chat_response.respuesta,
        )
        await _wa_start_booking_flow(
            cliente_id=cliente_id, phone_number_id=phone_number_id, from_number=from_number,
            flow=flow, config=config,
        )
        return

    await messaging._send_whatsapp_text(
        cliente_id=cliente_id, phone_number_id=phone_number_id, to_number=from_number,
        text=chat_response.respuesta,
    )


def _handle_whatsapp_echoes(
    phone_number_id: str,
    echoes: List[Dict[str, Any]],
    forced_cliente_id: str = "",
) -> None:
    """Mensajes que el equipo del negocio escribio desde SU app (Coexistence).

    Dos efectos: quedan en el historial del panel (para que el resto del equipo
    vea la conversacion completa) y ponen el chat en manos humanas, de forma que
    el asistente deja de responder ahi sin que nadie tenga que pulsar nada.
    """
    try:
        cliente_id = _resolve_whatsapp_client_id(phone_number_id, forced_cliente_id)
    except Exception as exc:  # noqa: BLE001 - un eco no resoluble no debe romper el webhook
        settings.logger.warning("Eco de WhatsApp sin cliente (%s): %s", phone_number_id, exc)
        return
    for echo in echoes:
        to_number = str(echo.get("to") or "").strip()
        if not to_number:
            continue
        texto = ""
        if str(echo.get("type") or "") == "text":
            texto = str((echo.get("text") or {}).get("body") or "").strip()
        if not texto:
            texto = "[mensaje enviado desde la app del negocio]"
        session_id = _whatsapp_session_id(cliente_id, to_number)
        inbox.remember_inbound_number(session_id, phone_number_id)
        rag._record_chat_message(
            session_id=session_id, cliente_id=cliente_id,
            role="assistant", content=texto, intent="human_reply_app",
        )
        inbox.claim(
            session_id, cliente_id,
            agent_user_id="", agent_name="Equipo (WhatsApp)",
        )


async def _handle_whatsapp_webhook(
    request: Request,
    *,
    forced_cliente_id: str = "",
) -> WhatsAppWebhookStatus:
    raw_body = await request.body()
    _verify_whatsapp_signature(raw_body, request.headers.get("x-hub-signature-256", ""))
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Payload de WhatsApp invalido.") from exc

    processed = 0
    entries = payload.get("entry", []) if isinstance(payload, dict) else []
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {}) if isinstance(change, dict) else {}
            metadata = value.get("metadata", {}) if isinstance(value, dict) else {}
            phone_number_id = str(metadata.get("phone_number_id", "")).strip()

            # Coexistence: el negocio sigue usando la app del movil y Meta nos manda
            # un ECO de lo que escribe su equipo desde ahi. Se guarda en la
            # conversacion y el asistente se calla solo: si hay una persona
            # respondiendo, no debe hablar por encima de ella.
            # El campo de la app de WhatsApp Business es `smb_message_echoes`;
            # `message_echoes` se acepta por si Meta lo manda con el nombre generico.
            echoes = []
            if isinstance(value, dict):
                echoes = value.get("smb_message_echoes") or value.get("message_echoes") or []
            if echoes:
                _handle_whatsapp_echoes(phone_number_id, echoes, forced_cliente_id)
                processed += len(echoes)
                continue

            messages = value.get("messages", []) if isinstance(value, dict) else []
            if not messages:
                continue
            # Numero de demo compartido: el tenant no sale del numero, sale del
            # codigo que trae el prospecto (se resuelve mas abajo, con el texto).
            demo_hub = wa_demo.is_hub(phone_number_id) and not forced_cliente_id
            cliente_id = "" if demo_hub else _resolve_whatsapp_client_id(phone_number_id, forced_cliente_id)
            for message_payload in messages:
                from_number = str(message_payload.get("from", "")).strip()
                message_id = str(message_payload.get("id", "")).strip()
                if not from_number:
                    continue
                if not _mark_whatsapp_message_if_new(
                    message_id=message_id,
                    cliente_id=cliente_id or "wa_demo_hub",
                    phone_number_id=phone_number_id,
                    from_number=from_number,
                ):
                    continue

                message_type = str(message_payload.get("type", "")).strip()
                interactive_id = ""
                if message_type == "text":
                    incoming_text = str(message_payload.get("text", {}).get("body", "")).strip()
                elif message_type == "interactive":
                    interactive_block = message_payload.get("interactive", {}) or {}
                    itype = interactive_block.get("type", "")
                    if itype == "button_reply":
                        reply = interactive_block.get("button_reply", {}) or {}
                        interactive_id = str(reply.get("id", "")).strip()
                        incoming_text = str(reply.get("title", "")).strip()
                    elif itype == "list_reply":
                        reply = interactive_block.get("list_reply", {}) or {}
                        interactive_id = str(reply.get("id", "")).strip()
                        incoming_text = str(reply.get("title", "")).strip()
                    elif itype == "nfm_reply":
                        # Respuesta del formulario de reserva (Flows): trae la cita
                        # entera, asi que se crea aqui y no pasa por el orquestador.
                        reply = interactive_block.get("nfm_reply", {}) or {}
                        try:
                            await _wa_handle_flow_reply(
                                cliente_id=cliente_id, phone_number_id=phone_number_id,
                                from_number=from_number,
                                response_json=str(reply.get("response_json") or ""),
                                request=request,
                            )
                            processed += 1
                        except Exception as exc:  # noqa: BLE001
                            settings.logger.exception("[flow] error creando la cita: %s", exc)
                            await messaging._send_whatsapp_text(
                                cliente_id=cliente_id, phone_number_id=phone_number_id,
                                to_number=from_number,
                                text="No he podido registrar la cita. Escribe *cita* para intentarlo de nuevo.",
                            )
                        continue
                    else:
                        incoming_text = ""
                else:
                    incoming_text = (
                        "El usuario ha enviado un mensaje que no es texto. "
                        "Responde de forma breve indicando que puede ayudarte si escribe su consulta."
                    )

                if demo_hub:
                    routing = wa_demo.resolve_incoming(phone_number_id, from_number, incoming_text)
                    cliente_id = routing["cliente_id"]
                    if not cliente_id:
                        # Sin codigo valido no se molesta a ningun asistente.
                        await messaging._send_whatsapp_text(
                            cliente_id="", phone_number_id=phone_number_id,
                            to_number=from_number, text=routing["help_text"],
                        )
                        processed += 1
                        continue
                    if routing["just_bound"]:
                        # El mensaje era el codigo, no una consulta: se abre la demo
                        # con la MISMA entrada que veria un cliente real de ese negocio.
                        # Se delega en `_wa_send_main_menu`, que ya decide entre menu de
                        # opciones y bienvenida a secas segun `config['chat_menu']`: si no,
                        # un negocio con agenda perdia justo los botones de agendar cita.
                        demo_config = clients._get_client_config(cliente_id)
                        await _wa_send_main_menu(
                            cliente_id=cliente_id,
                            phone_number_id=phone_number_id,
                            to_number=from_number,
                            nombre_empresa=(
                                str(demo_config.get("empresa") or "").strip()
                                or demo_config.get("nombre", "")
                            ),
                            booking_enabled=bool(demo_config["booking"]["enabled"]),
                            greeting=True,
                        )
                        processed += 1
                        continue

                try:
                    await _handle_whatsapp_message(
                        cliente_id=cliente_id,
                        phone_number_id=phone_number_id,
                        from_number=from_number,
                        incoming_text=incoming_text,
                        interactive_id=interactive_id,
                        request=request,
                    )
                    processed += 1
                except Exception as exc:  # noqa: BLE001
                    settings.logger.exception("Error procesando WhatsApp para %s: %s", cliente_id, exc)
                    await messaging._send_whatsapp_text(
                        cliente_id=cliente_id,
                        phone_number_id=phone_number_id,
                        to_number=from_number,
                        text="Ahora mismo no he podido procesar tu mensaje. Intentalo de nuevo en unos minutos.",
                    )
    return WhatsAppWebhookStatus(status="ok", processed=processed)


def _verify_whatsapp_webhook_challenge(request: Request, cliente_id: str = "") -> Response:
    params = request.query_params
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")
    expected_token = _whatsapp_verify_token_for_client(cliente_id)
    if mode == "subscribe" and expected_token and hmac.compare_digest(token, expected_token):
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verificacion de WhatsApp rechazada.")


