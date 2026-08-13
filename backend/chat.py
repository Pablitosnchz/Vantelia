"""Orquestador del chat multi-canal (refactor F3).

_process_chat_message une RAG, NLU ligera (saludos, menu, disponibilidad,
intenciones comerciales y de pago), gestion de citas por codigo y cuota de
plan. Lo consumen el endpoint /chat (widget/portal) y el webhook WhatsApp.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from fastapi import Request

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from api_models import RespuestaChat
from backend import agenda, appstate, booking, clients, commerce, rag, settings, textnorm, timeutils

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


GIFT_CARD_INTENT_RE = re.compile(r"tarjeta[s]?\s+(de\s+)?regalo|gift\s*card|bono\s+regalo|cheque\s+regalo", re.IGNORECASE)
GIFT_CARD_PURCHASE_RE = re.compile(
    r"\b(comprar|compra|pagar|regalar|regalo|enlace|link|url|web|donde|d[oó]nde|"
    r"como\s+compro|c[oó]mo\s+compro|quiero|me\s+gustaria|me\s+gustar[ií]a)\b",
    re.IGNORECASE,
)
GIFT_CARD_INFO_RE = re.compile(
    r"\b(que|cual|tipos?|teneis|tienen|hay|incluye|condiciones|caduca|caducidad|validez|vale\s+para|sirve\s+para|"
    r"usar|uso|canjear|canje|transferir|transferible|cambiar|cambio|devolver|"
    r"devolucion|devoluci[oó]n|descuento|promocion|promoci[oó]n|familiar|amigo|"
    r"persona|centro|centros|tratamiento|tratamientos|masaje|precio|importe|"
    r"ocultar|mensaje|personalizar|email|correo|reservar|reserva)\b|\?",
    re.IGNORECASE,
)


def _message_requests_gift_card(message: str) -> bool:
    return bool(GIFT_CARD_INTENT_RE.search(textnorm._strip_accents(str(message or "").lower())))


def _message_requests_gift_card_purchase(message: str) -> bool:
    norm = textnorm._strip_accents(str(message or "").lower())
    if not GIFT_CARD_INTENT_RE.search(norm):
        return False
    if GIFT_CARD_INFO_RE.search(norm):
        return False
    return bool(GIFT_CARD_PURCHASE_RE.search(norm))


BOOKING_POLICY_INFO_RE = re.compile(
    r"\b(condiciones?|politicas?|politica|cancelacion|caducidad|devolucion|reembolso|"
    r"plazo|penalizacion|cambiar\s+la\s+reserva|cambio\s+de\s+reserva)\b",
    re.IGNORECASE,
)


def _message_requests_booking_policy_info(message: str) -> bool:
    norm = textnorm._strip_accents(str(message or "").lower())
    if not BOOKING_POLICY_INFO_RE.search(norm):
        return False
    return any(word in norm for word in ("reserva", "reservar", "cita", "cancelacion", "cancelar", "cambio", "cambiar"))


def _message_requests_menu(message: str) -> bool:
    norm = textnorm._strip_accents(str(message or "").lower())
    return any(p.search(norm) for p in MENU_RETURN_PATTERNS)


GREETING_FILLER_RE = re.compile(
    r"\b(hola+|holi|holis|hey|ey|ola|hello|hi|hallo|buenas|buenos|dias|tardes|noches|"
    r"saludos|que|tal|como|estas|esta|estais|muy|por|favor|gracias|una|un|el|la|los|las|"
    r"soy|yo|me|mi|te|os|somos|y|de|a)\b",
    re.IGNORECASE,
)


def _greeting_has_residual_content(message: str) -> bool:
    """True si tras quitar el saludo y las muletillas queda contenido real.

    Sin esto, cualquier pregunta abierta que empiece por "Hola" ("Hola, a que hora
    cerrais los sabados?") caia en el menu, porque los detectores de intencion solo
    cubren reservar/cancelar/pagar/disponibilidad. El menu solo debe ganar cuando el
    mensaje es SOLO un saludo."""
    norm = textnorm._strip_accents(str(message or "").lower())
    if "?" in norm or "¿" in norm:
        return True
    rest = GREETING_FILLER_RE.sub(" ", norm)
    words = [w for w in re.findall(r"[a-z0-9]{3,}", rest)]
    return len(words) >= 1


def _message_is_pure_greeting(message: str) -> bool:
    """Saludo 'puro' (solo saluda): responde con el menu. Si ADEMAS trae una intencion
    ("Hola, quiero cancelar mi cita R-123456") o cualquier pregunta real ("Hola, abris
    los lunes?"), eso manda: el menu no puede secuestrarla. Compartido con WhatsApp
    (misma regla en ambos canales)."""
    if not _message_is_greeting(message):
        return False
    if _greeting_has_residual_content(message):
        return False
    if booking._extract_booking_code_from_text(message):
        return False
    if booking._message_requests_cancel_booking(message) or booking._message_requests_reschedule_booking(message):
        return False
    if booking._message_requests_booking_form(message):
        return False
    if booking._message_requests_payment(message):
        return False
    if rag._message_requests_availability(message):
        return False
    if _detect_menu_option(message):
        return False
    if _detect_commercial_intent(message):
        return False
    return True


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
    booking_line = "· Agendar cita\n· Cancelar o cambiar mi cita\n" if booking_enabled else ""
    return (
        f"{saludo}"
        f"{booking_line}"
        f"· Informacion de servicios\n"
        f"· Preguntas frecuentes\n\n"
        f"Pulsa una opcion o escribe directamente tu consulta."
    )


def _main_menu_quick_actions(booking_enabled: bool, gift_available: bool = False) -> List[Dict[str, str]]:
    actions: List[Dict[str, str]] = []
    if booking_enabled:
        actions.append({"label": "Agendar cita", "message": "Quiero agendar una cita"})
        actions.append({"label": "Cancelar o cambiar mi cita", "message": "Quiero cancelar o cambiar mi cita"})
    if gift_available:
        actions.append({"label": "🎁 Tarjeta regalo", "message": "Quiero comprar una tarjeta regalo"})
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
        # Estado y horas de HOY desde la MISMA matriz semanal que el bloque HORARIO del
        # prompt (agenda._weekly_schedule_matrix, derivada de los profesionales publicos).
        # Antes salian de config['booking'] y podian contradecir al horario real en el
        # MISMO prompt (p.ej. horario por empleado distinto del base).
        try:
            matrix = agenda._weekly_schedule_matrix(cliente_id, config)
        except Exception:  # noqa: BLE001
            matrix = []
        today_row = matrix[now_local.weekday()] if len(matrix) == 7 else None
        if today_row is not None:
            if today_row["closed"]:
                lines.append("- Estado: CERRADO hoy (dia sin agenda).")
            else:
                now_hhmm = now_local.strftime("%H:%M")
                open_now = today_row["start"] <= now_hhmm <= today_row["end"]
                estado = "ABIERTO ahora" if open_now else "CERRADO ahora"
                lines.append(f"- Estado: {estado}. Horario hoy {today_row['start']}-{today_row['end']}.")
            closed_labels = [
                textnorm.DAY_LABELS_ES[item["weekday"]] for item in matrix if item["closed"]
            ]
            if closed_labels:
                lines.append(f"- Dias cerrados: {', '.join(closed_labels)}.")
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

    contacto = config.get("contacto", {}) or {}
    if contacto.get("telefono"):
        lines.append(f"- Telefono publicado: {contacto['telefono']}.")
    if contacto.get("email"):
        lines.append(f"- Email publicado: {contacto['email']}.")

    # El estado ABIERTO/CERRADO describe el local FISICO, no al asistente: el asistente
    # atiende 24/7 y las citas son para fechas futuras. Sin esta regla el modelo llegaba
    # a negarse a gestionar citas "porque ahora estamos cerrados".
    lines.append(
        "- TU (el asistente) atiendes 24/7: aunque el negocio este cerrado AHORA, reservas, "
        "cambias y cancelas citas para fechas futuras con total normalidad. NUNCA pidas al "
        "usuario que vuelva a contactar en horario de atencion para gestionar su cita."
    )

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
    on_user_message_persisted: Optional[Callable[[str], None]] = None,
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
    if on_user_message_persisted is not None:
        try:
            on_user_message_persisted(session_id)
        except Exception as exc:  # noqa: BLE001
            settings.logger.debug(
                "Callback posterior a persistencia de chat fallo para %s: %s",
                cliente_id,
                exc,
            )
    client_config = clients._get_client_config(cliente_id)
    booking_enabled = bool(client_config["booking"]["enabled"]) and clients._client_booking_plan_enabled(cliente_id)
    # Identidad de Apariencia: "empresa" = negocio (el menu se presenta en su nombre);
    # si esta vacio cae a "nombre" (compat con clientes con un solo campo).
    nombre_empresa = str(client_config.get("empresa") or "").strip() or client_config.get("nombre", "")

    if _message_is_pure_greeting(message) or _message_requests_menu(message):
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
            quick_actions=_main_menu_quick_actions(
                booking_enabled, gift_available=commerce.gift_public_available(cliente_id)
            ),
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
    # "mi reserva" en una frase de GESTION ("mover el dia de mi reserva") no es querer
    # agendar: cancelar/reprogramar mandan sobre el atajo del menu.
    wants_manage = booking._message_requests_cancel_booking(message) or booking._message_requests_reschedule_booking(message)
    policy_info = _message_requests_booking_policy_info(message)
    if menu_option == "agendar" and booking_enabled and not wants_manage and not policy_info:
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

    if _message_requests_gift_card_purchase(message) and commerce.gift_public_available(cliente_id):
        gift_url = f"{textnorm._preferred_public_base_url().rstrip('/')}/gift/{cliente_id}"
        gift_text = (
            "🎁 ¡Claro! Puedes comprar una tarjeta regalo online y llega por email al instante "
            f"(o el dia que elijas): {gift_url}"
            "\n\nSe canjea al reservar o directamente en recepcion."
        )
        gift_response = RespuestaChat(
            respuesta=gift_text,
            mostrar_formulario=False,
            session_id=session_id,
            intent="gift_card",
        )
        rag._record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=gift_text,
            intent="gift_card",
        )
        return gift_response

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
        trusted_phone=trusted_phone,
        session_id=session_id,
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

    if booking_enabled and booking._message_requests_booking_form(message) and not policy_info:
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

    if policy_info:
        context_blocks.append(
            "CONSULTA_INFORMATIVA_DE_RESERVAS_Y_CANCELACION: responde con las condiciones publicadas "
            "sobre como reservar, cambios y cancelaciones. No abras el formulario ni pidas numero de "
            "reserva salvo que el usuario diga claramente que quiere cancelar o cambiar una cita concreta."
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
    if policy_info:
        mostrar_formulario = False
    clean_text = raw_text.replace(settings.BOOKING_SENTINEL, "").strip()
    clean_text = textnorm._normalize_chat_response_text(clean_text)
    clean_text = _emphasize_structured_headings(clean_text)
    if booking_enabled and not mostrar_formulario and booking._message_requests_booking_form(message) and not policy_info:
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


