"""Orquestador del chat multi-canal (refactor F3).

_process_chat_message une RAG, NLU ligera (saludos, menu, disponibilidad,
intenciones comerciales y de pago), gestion de citas por codigo y cuota de
plan. Lo consumen el endpoint /chat (widget/portal) y el webhook WhatsApp.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from api_models import RespuestaChat
from backend import agenda, appstate, booking, clients, crm, db, emailing, messaging, rag, security, settings, textnorm, timeutils

GREETING_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^\s*(hola|holaa+|holi|holis|holaaa)\b",
        r"^\s*(buenas|buenos\s+dias|buenas\s+tardes|buenas\s+noches)\b",
        r"^\s*(hey|ey|ola|hello|hi|hallo)\b",
        r"^\s*(saludos|que\s+tal|qu[eé]\s+tal|como\s+estas|c[oó]mo\s+est[aá]s)\b",
        r"^\s*(empezar|empieza|inicio|menu|men[uú]\s+principal|opciones)\b",
    ]
]


MENU_RETURN_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(menu|men[uú]\s+principal|volver\s+al\s+menu|volver\s+atras|volver\s+atr[aá]s)\b",
        r"^\s*(opciones|inicio|empezar|empieza|principal)\s*$",
    ]
]


MENU_OPTION_PATTERNS = {
    "agendar": [
        re.compile(p, re.IGNORECASE)
        for p in [
            r"^\s*1\b",
            r"\b(agendar|agenda|reservar|reserva|pedir\s+cita|coger\s+cita)\b",
        ]
    ],
    "faq": [
        re.compile(p, re.IGNORECASE)
        for p in [
            r"^\s*2\b",
            r"\b(faq|preguntas\s+frecuentes|dudas\s+frecuentes)\b",
        ]
    ],
    "productos": [
        re.compile(p, re.IGNORECASE)
        for p in [
            r"^\s*3\b",
            r"\b(informacion\s+productos|info\s+productos|catalogo|cat[aá]logo|que\s+ofreceis|qu[eé]\s+ofrec[eé]is|servicios\s+disponibles)\b",
        ]
    ],
    "recomendar": [
        re.compile(p, re.IGNORECASE)
        for p in [
            r"^\s*4\b",
            r"\b(recomienda|recomiendame|recomi[eé]ndame|que\s+me\s+recomiendas|qu[eé]\s+me\s+recomiendas)\b",
        ]
    ],
    "comparar": [
        re.compile(p, re.IGNORECASE)
        for p in [
            r"^\s*5\b",
            r"\b(comparar|comparacion|comparaci[oó]n|diferencias\s+entre)\b",
        ]
    ],
    "estimar": [
        re.compile(p, re.IGNORECASE)
        for p in [
            r"^\s*6\b",
            r"\b(estimar\s+precio|presupuesto|cuanto\s+costaria|cu[aá]nto\s+costar[ií]a|calcula\s+precio)\b",
        ]
    ],
}


def _message_is_greeting(message: str) -> bool:
    norm = textnorm._strip_accents(str(message or "").lower())
    if len(norm.strip()) > 80:
        return False
    return any(p.search(norm) for p in GREETING_PATTERNS)


def _message_requests_menu(message: str) -> bool:
    norm = textnorm._strip_accents(str(message or "").lower())
    return any(p.search(norm) for p in MENU_RETURN_PATTERNS)


def _detect_menu_option(message: str) -> str:
    norm = textnorm._strip_accents(str(message or "").lower().strip())
    for option, patterns in MENU_OPTION_PATTERNS.items():
        if any(p.search(norm) for p in patterns):
            return option
    return ""


def _build_main_menu_text(nombre_empresa: str, booking_enabled: bool, *, greeting: bool = False) -> str:
    saludo = (
        f"Hola. Soy el asistente de **{nombre_empresa}**. ¿En qué puedo ayudarte?\n\n"
        if greeting else
        f"**Menu principal de {nombre_empresa}**\n\n"
    )
    booking_line = "· Agendar cita\n" if booking_enabled else ""
    return (
        f"{saludo}"
        f"{booking_line}"
        f"· Informacion de servicios\n"
        f"· Preguntas frecuentes\n\n"
        f"Pulsa una opcion o escribe directamente tu consulta."
    )


def _main_menu_quick_actions(booking_enabled: bool) -> List[Dict[str, str]]:
    actions: List[Dict[str, str]] = []
    if booking_enabled:
        actions.append({"label": "Agendar cita", "message": "Quiero agendar una cita"})
    actions.extend(
        [
            {"label": "Informacion servicios", "message": "Quiero informacion sobre servicios disponibles"},
            {"label": "Preguntas frecuentes", "message": "Muestrame las preguntas frecuentes principales"},
        ]
    )
    return actions


MENU_OPTION_INSTRUCTIONS = {
    "agendar": (
        "El usuario quiere agendar una cita. Guialo paso a paso, una pregunta por mensaje, en este orden: "
        "1) fecha deseada, 2) hora, 3) nombre completo. Tras tener los tres datos, confirma resumen y "
        f"añade {settings.BOOKING_SENTINEL} para abrir el formulario. Si pide ver disponibilidad, listara los huecos "
        "del bloque DATOS_EN_TIEMPO_REAL_DISPONIBILIDAD. Cierra siempre ofreciendo volver al menu principal."
    ),
    "faq": (
        "El usuario quiere ver preguntas frecuentes. Usa solo las Q&A configuradas en el panel del cliente "
        "y muestra como maximo 4. No inventes FAQs ni extraigas otras de la base documental. "
        "Incluye cada pregunta y una respuesta breve de 1-2 frases. "
        "Usa formato compacto con punto medio: \"· **Pregunta:** respuesta breve\". "
        "Invitalo a pedir ampliar una por numero o a escribir su duda libre. "
        "Cierra ofreciendo volver al menu principal."
    ),
    "productos": (
        "El usuario quiere informacion de productos o servicios. Lista las categorias o productos principales "
        "del negocio (max 6) con bullet point, nombre y 1 frase de beneficio clave. Pregunta cual quiere ampliar. "
        "Cierra ofreciendo volver al menu principal."
    ),
    "recomendar": (
        "Modo recomendador. Haz 2-3 preguntas breves para entender necesidad, presupuesto y urgencia. "
        "Tras las respuestas, recomienda 1-2 productos con justificacion clara. "
        "Cierra ofreciendo volver al menu principal."
    ),
    "comparar": (
        "Modo comparador. Pide al usuario que indique 2 o 3 productos a comparar. Cuando los tenga, "
        "muestra comparacion en formato breve (precio, caracteristicas, ventajas, ideal para). "
        "Cierra ofreciendo volver al menu principal."
    ),
    "estimar": (
        "Modo estimador. Pide los datos necesarios para estimar (tipo, alcance, caracteristicas). "
        "Da rango aproximado con margen, basandote solo en precios documentados. "
        "Si no hay precio fijo, ofrece reservar valoracion. Cierra ofreciendo volver al menu principal."
    ),
}


def _build_faq_response_from_panel(cliente_id: str) -> str:
    pairs = rag._client_qa_pairs_for_chat(cliente_id, limit=4)
    if not pairs:
        return (
            "Todavia no hay preguntas frecuentes configuradas. "
            "Puedes escribirme tu duda concreta y la respondere con la informacion disponible del negocio.\n\n"
            "Escribe **menu** para volver al menu principal."
        )
    lines = ["Estas son las preguntas frecuentes principales:"]
    for question, answer in pairs:
        clean_answer = answer
        if rag._answer_is_info_txt_instruction(clean_answer):
            clean_answer = "La IA la respondera usando la informacion disponible del negocio."
        lines.append(f"· **{question}:** {clean_answer}")
    lines.append("")
    lines.append("Puedes pedirme ampliar cualquiera o escribir tu duda libre.")
    lines.append("Escribe **menu** para volver al menu principal.")
    return "\n".join(lines)


def _build_live_context_block(cliente_id: str, config: Dict[str, Any]) -> str:
    booking_cfg = config.get("booking", {}) or {}
    tz_name = booking_cfg.get("timezone") or settings.DEFAULT_TIMEZONE
    try:
        now_local = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now_local = timeutils._utc_now()
        tz_name = "UTC"

    fecha_humana = textnorm._format_date_es(now_local.date())
    hora_humana = now_local.strftime("%H:%M")
    lines = [
        f"- Fecha actual: {fecha_humana} ({now_local.date().isoformat()}).",
        f"- Hora local del negocio: {hora_humana} ({tz_name}).",
    ]

    if booking_cfg.get("enabled"):
        open_now = agenda._is_open_now(booking_cfg, now_local)
        if open_now is True:
            lines.append(
                f"- Estado: ABIERTO ahora. Horario hoy {booking_cfg.get('day_start','09:00')}-{booking_cfg.get('day_end','18:00')}."
            )
        elif open_now is False:
            lines.append(
                f"- Estado: CERRADO ahora. Horario habitual {booking_cfg.get('day_start','09:00')}-{booking_cfg.get('day_end','18:00')}."
            )
        break_windows = textnorm._normalize_break_windows(
            booking_cfg.get("day_start", "09:00"),
            booking_cfg.get("day_end", "18:00"),
            booking_cfg.get("break_windows", []),
            booking_cfg.get("break_start", ""),
            booking_cfg.get("break_end", ""),
        )
        if break_windows:
            descanso_txt = ", ".join(f"{item['start']}-{item['end']}" for item in break_windows)
            lines.append(
                f"- Descansos diarios: {descanso_txt}."
            )
        closed = booking_cfg.get("closed_weekdays") or []
        if closed:
            dias_cerrados = ", ".join(textnorm.DAY_LABELS_ES[i] for i in closed if 0 <= int(i) <= 6)
            if dias_cerrados:
                lines.append(f"- Dias cerrados: {dias_cerrados}.")

    contacto = config.get("contacto", {}) or {}
    if contacto.get("telefono"):
        lines.append(f"- Telefono publicado: {contacto['telefono']}.")
    if contacto.get("email"):
        lines.append(f"- Email publicado: {contacto['email']}.")

    return "DATOS_EN_VIVO_DEL_NEGOCIO:\n" + "\n".join(lines)


COMMERCIAL_INTENT_INSTRUCTIONS = {
    "diagnostico": (
        "Modo diagnostico inteligente: orienta al usuario con 3-5 preguntas breves si faltan datos. "
        "Despues entrega una recomendacion prudente, explica por que encaja y ofrece siguiente paso. "
        "No diagnostiques temas medicos, legales o financieros de forma concluyente; deriva a revision humana."
    ),
    "recomendador": (
        "Modo recomendador de servicios: identifica objetivo, urgencia, presupuesto aproximado y contexto. "
        "Recomienda solo servicios presentes en la base documental, da alternativas y termina con una accion clara."
    ),
    "estimador": (
        "Modo calculadora o estimador: pide las variables necesarias para estimar. "
        "Si hay precios documentados, usa rangos o condiciones verificadas. Si no los hay, dilo y calcula solo una orientacion cualitativa."
    ),
    "comparador": (
        "Modo comparador de opciones: compara en tabla o bullets criterios como objetivo, plazo, coste, dificultad, encaje y siguiente paso. "
        "No inventes diferencias si la base documental no las respalda."
    ),
}


def _detect_commercial_intent(message: str) -> str:
    normalized = f" {' '.join(str(message or '').lower().split())} "
    if booking._message_requests_booking_form(normalized):
        return "booking"
    for intent, patterns in COMMERCIAL_INTENT_PATTERNS.items():
        if any(pattern.search(normalized) for pattern in patterns):
            return intent
    return ""


def _build_intent_enhanced_message(message: str, intent: str) -> str:
    instruction = COMMERCIAL_INTENT_INSTRUCTIONS.get(intent)
    if not instruction:
        return message
    return f"{instruction}\n\nMensaje del usuario: {message}"


def _emphasize_structured_headings(text: str) -> str:
    lines = str(text or "").splitlines()
    if not lines:
        return text

    detail_pattern = re.compile(
        r"^\s*(precio|encaja\s+para|incluye|ideal\s+para|soporte|conversaciones|profesionales|cuentas)\s*:",
        re.IGNORECASE,
    )
    skip_pattern = re.compile(r"^(\s*(·|-|\*|\d+\.)\s*)?\*\*.+\*\*")
    sentence_end_pattern = re.compile(r"[.!?…:]$")
    result: List[str] = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if (
            stripped
            and next_line
            and detail_pattern.match(next_line)
            and not detail_pattern.match(stripped)
            and not skip_pattern.match(stripped)
            and not sentence_end_pattern.search(stripped)
            and len(stripped) <= 90
        ):
            prefix = line[: len(line) - len(line.lstrip())]
            result.append(f"{prefix}**{stripped}**")
            continue
        result.append(line)

    return "\n".join(result)


async def _process_chat_message(
    *,
    cliente_id: str,
    message: str,
    session_id: str,
    request: Request,
    origin_override: str = "",
    user_agent_override: str = "",
    trusted_phone: str = "",
) -> RespuestaChat:
    commercial_intent = _detect_commercial_intent(message)
    rag._ensure_chat_session_record(
        session_id,
        cliente_id,
        request,
        origin_override=origin_override,
        user_agent_override=user_agent_override,
    )
    rag._record_chat_message(
        session_id=session_id,
        cliente_id=cliente_id,
        role="user",
        content=message,
        intent=commercial_intent,
    )
    client_config = clients._get_client_config(cliente_id)
    booking_enabled = bool(client_config["booking"]["enabled"]) and clients._client_booking_plan_enabled(cliente_id)
    nombre_empresa = client_config.get("nombre", "")

    if _message_is_greeting(message) or _message_requests_menu(message):
        menu_text = _build_main_menu_text(
            nombre_empresa,
            booking_enabled,
            greeting=_message_is_greeting(message),
        )
        menu_response = RespuestaChat(
            respuesta=menu_text,
            mostrar_formulario=False,
            session_id=session_id,
            intent="menu",
            quick_actions=_main_menu_quick_actions(booking_enabled),
        )
        rag._record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=menu_text,
            intent="menu",
        )
        return menu_response

    menu_option = _detect_menu_option(message)
    if rag._message_requests_availability(message):
        availability_text = await rag._build_chat_availability_answer(cliente_id, message, client_config)
        availability_text = textnorm._normalize_chat_response_text(availability_text)
        availability_response = RespuestaChat(
            respuesta=availability_text,
            mostrar_formulario=False,
            session_id=session_id,
            intent="availability",
        )
        rag._record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=availability_response.respuesta,
            intent="availability",
        )
        return availability_response
    if menu_option == "agendar" and booking_enabled:
        booking_response = RespuestaChat(
            respuesta="📅 Te muestro el formulario para agendar tu cita. Elige servicio, fecha y hora.",
            mostrar_formulario=True,
            session_id=session_id,
        )
        rag._record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=booking_response.respuesta,
            intent="agendar",
        )
        return booking_response

    if menu_option == "faq":
        faq_text = _build_faq_response_from_panel(cliente_id)
        faq_response = RespuestaChat(
            respuesta=faq_text,
            mostrar_formulario=False,
            session_id=session_id,
            intent="faq",
        )
        rag._record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=faq_response.respuesta,
            intent="faq",
        )
        return faq_response

    qa_exact_answer = rag._match_qa_answer(cliente_id, message)
    if qa_exact_answer:
        qa_response = RespuestaChat(
            respuesta=qa_exact_answer,
            mostrar_formulario=False,
            session_id=session_id,
            intent="qa_exact",
        )
        rag._record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=qa_exact_answer,
            intent="qa_exact",
        )
        return qa_response

    # El pago se evalua antes que la gestion de cita: una peticion de pago suele
    # incluir el numero de reserva y, sin esto, la gestion la interceptaria.
    payment_flow = await booking._process_payment_request_message(
        cliente_id=cliente_id,
        message=message,
        request=request,
        source="chat",
        trusted_phone=trusted_phone,
    )
    if payment_flow:
        payment_intent, payment_text = payment_flow
        payment_response = RespuestaChat(
            respuesta=payment_text,
            mostrar_formulario=False,
            session_id=session_id,
            intent=payment_intent,
        )
        rag._record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=payment_response.respuesta,
            intent=payment_intent,
        )
        return payment_response

    management = await booking._process_booking_management_message(
        cliente_id=cliente_id,
        message=message,
        request=request,
        source="chat",
    )
    if management:
        management_intent, management_text = management
        management_response = RespuestaChat(
            respuesta=management_text,
            mostrar_formulario=False,
            session_id=session_id,
            intent=management_intent,
        )
        rag._record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=management_response.respuesta,
            intent=management_intent,
        )
        return management_response

    if booking_enabled and booking._message_requests_booking_form(message):
        booking_response = RespuestaChat(
            respuesta="📅 Te muestro el formulario de solicitud de cita para que puedas elegir servicio, fecha y hora.",
            mostrar_formulario=True,
            session_id=session_id,
        )
        rag._record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=booking_response.respuesta,
            intent=commercial_intent,
        )
        return booking_response

    session = rag._get_or_create_session(session_id, cliente_id)
    with appstate.state_lock:
        session.last_seen = time.time()
        session.message_count += 1

    if session.message_count > settings.MAX_MESSAGES_PER_SESSION:
        limit_response = RespuestaChat(
            respuesta="Has alcanzado el limite temporal de mensajes. Si quieres, puedo derivarte al equipo humano.",
            mostrar_formulario=booking_enabled,
            session_id=session_id,
        )
        rag._record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=limit_response.respuesta,
            intent=commercial_intent,
        )
        return limit_response

    enhanced_message = _build_intent_enhanced_message(message, commercial_intent)

    context_blocks: List[str] = []
    try:
        context_blocks.append(_build_live_context_block(cliente_id, client_config))
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudo construir contexto en vivo para %s: %s", cliente_id, exc)

    if menu_option and menu_option in MENU_OPTION_INSTRUCTIONS:
        context_blocks.append(
            f"FLUJO_DE_MENU_ACTIVO ({menu_option}): {MENU_OPTION_INSTRUCTIONS[menu_option]} "
            "Cierra siempre con una linea separada: Escribe **menú** para volver al menú principal."
        )

    if booking_enabled and rag._message_requests_availability(message):
        target_date = textnorm._resolve_relative_date_es(message, client_config["booking"]["timezone"])
        if target_date is None:
            try:
                target_date = datetime.now(ZoneInfo(client_config["booking"]["timezone"])).date()
            except Exception:
                target_date = timeutils._utc_now().date()
        availability_context = await rag._build_availability_context(cliente_id, target_date)
        if availability_context:
            context_blocks.append(availability_context)

    if context_blocks:
        joined = "\n\n".join(f"[CONTEXTO DEL SISTEMA - {block}]" for block in context_blocks)
        enhanced_message = f"{joined}\n\nMensaje del usuario: {message}"
        if commercial_intent:
            enhanced_message = (
                f"{joined}\n\n{_build_intent_enhanced_message(message, commercial_intent)}"
            )

    response = session.engine.chat(enhanced_message)
    raw_text = response.response.strip()
    mostrar_formulario = settings.BOOKING_SENTINEL in raw_text
    clean_text = raw_text.replace(settings.BOOKING_SENTINEL, "").strip()
    clean_text = textnorm._normalize_chat_response_text(clean_text)
    clean_text = _emphasize_structured_headings(clean_text)
    if booking_enabled and not mostrar_formulario and booking._message_requests_booking_form(message):
        mostrar_formulario = True
        if not clean_text:
            clean_text = "Te muestro el formulario de solicitud de cita para continuar."

    settings.logger.info(
        "Chat %s [%s] %s",
        cliente_id,
        session_id,
        message[:120],
    )

    chat_response = RespuestaChat(
        respuesta=clean_text or "No tengo una respuesta valida en este momento.",
        mostrar_formulario=mostrar_formulario and booking_enabled,
        session_id=session_id,
    )
    rag._record_chat_message(
        session_id=session_id,
        cliente_id=cliente_id,
        role="assistant",
        content=chat_response.respuesta,
        intent=commercial_intent,
    )
    return chat_response




COMMERCIAL_INTENT_PATTERNS: Dict[str, List[re.Pattern[str]]] = {
    "diagnostico": [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\b(diagnostico|diagnóstico|test|orientame|oriÃ©ntame|evaluacion|evaluaciÃ³n)\b",
            r"\b(que necesito|qu[eé] necesito|analiza mi caso|mi caso)\b",
        ]
    ],
    "recomendador": [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\b(recomienda|recomiendame|recomi[eé]ndame|recomendacion|recomendaciÃ³n)\b",
            r"\b(que servicio|qu[eé] servicio|mejor opcion|mejor opciÃ³n|cual me conviene|cu[aá]l me conviene)\b",
        ]
    ],
    "estimador": [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\b(calcula|calculadora|estimacion|estimaciÃ³n|estimar|presupuesto|precio|coste|cuanto cuesta|cu[aá]nto cuesta)\b",
            r"\b(rango de precio|desde cuanto|desde cu[aá]nto|aproximado)\b",
        ]
    ],
    "comparador": [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\b(compara|comparar|comparador|diferencia|diferencias|versus| vs )\b",
            r"\b(entre .+ y .+|mejor .+ o .+)\b",
        ]
    ],
}


