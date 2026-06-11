"""Normalizacion de textos, origenes, horarios y plantillas (refactor F3).

Funciones puras de validacion/normalizacion usadas por la carga de config
multi-tenant y los endpoints. Levantan HTTPException(400) ante entrada
invalida (contrato historico del monolito).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from fastapi import HTTPException

from backend import settings

def _normalize_origin_value(origin: str) -> str:
    raw_value = str(origin).strip().rstrip("/")
    if not raw_value:
        raise RuntimeError("Se ha recibido un origen vacio en la configuracion.")

    parsed = urlparse(raw_value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"Origen invalido en la configuracion: {origin}")

    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise RuntimeError(
            f"El origen debe incluir solo esquema y dominio, sin rutas ni query strings: {origin}"
        )

    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _normalize_optional_http_url(raw_url: str) -> str:
    value = str(raw_url).strip()
    if not value:
        return ""

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"URL HTTP invalida en la configuracion: {raw_url}")

    return value


def _normalize_message_templates(raw_templates: Any) -> Dict[str, str]:
    templates = dict(settings.DEFAULT_MESSAGE_TEMPLATES)
    if isinstance(raw_templates, dict):
        for key in settings.DEFAULT_MESSAGE_TEMPLATES:
            raw_value = raw_templates.get(key, "")
            if isinstance(raw_value, dict):
                raw_value = raw_value.get("body", raw_value.get("message", ""))
            value = _sanitize_text(raw_value, allow_multiline=True)
            if value:
                templates[key] = value[:500]
    return templates


def _normalize_message_template_enabled(
    raw_enabled: Any,
    raw_templates: Any = None,
) -> Dict[str, bool]:
    enabled = dict(settings.DEFAULT_MESSAGE_TEMPLATE_ENABLED)
    if isinstance(raw_enabled, dict):
        for key in settings.DEFAULT_MESSAGE_TEMPLATE_ENABLED:
            if key in raw_enabled:
                enabled[key] = bool(raw_enabled.get(key))
    if isinstance(raw_templates, dict):
        for key in settings.DEFAULT_MESSAGE_TEMPLATE_ENABLED:
            nested_value = raw_templates.get(key)
            if isinstance(nested_value, dict) and "enabled" in nested_value:
                enabled[key] = bool(nested_value.get("enabled"))
    return enabled


def _normalize_message_template_channels(raw_channels: Any) -> Dict[str, Dict[str, bool]]:
    channels = {key: dict(value) for key, value in settings.DEFAULT_MESSAGE_TEMPLATE_CHANNELS.items()}
    if not isinstance(raw_channels, dict):
        return channels
    for kind in settings.DEFAULT_MESSAGE_TEMPLATE_CHANNELS:
        raw_value = raw_channels.get(kind)
        if not isinstance(raw_value, dict):
            for raw_key, target_key in settings.MESSAGE_KIND_ALIASES.items():
                if target_key == kind and isinstance(raw_channels.get(raw_key), dict):
                    raw_value = raw_channels.get(raw_key)
                    break
        if not isinstance(raw_value, dict):
            continue
        channels[kind] = {
            "email": bool(raw_value.get("email", channels[kind]["email"])),
            "whatsapp": bool(raw_value.get("whatsapp", channels[kind]["whatsapp"])),
            "sms": bool(raw_value.get("sms", channels[kind]["sms"])),
        }
    return channels


def _sanitize_text(value: str, *, allow_multiline: bool = False) -> str:
    # Normalizamos a NFC para que el texto que llega de cualquier canal (web,
    # WhatsApp, voz) sea canonico. Sin esto, una tilde descompuesta (NFD) no
    # casa con la misma tilde compuesta (NFC) guardada en BD y rompe busquedas
    # como la del catalogo de servicios.
    value = unicodedata.normalize("NFC", str(value or ""))
    if allow_multiline:
        cleaned_lines = [" ".join(line.split()) for line in value.splitlines()]
        return "\n".join(line for line in cleaned_lines if line).strip()

    return " ".join(value.split()).strip()


def _normalize_chat_response_text(value: str) -> str:
    text = str(value or "").replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    text = re.sub(
        r"_Escribe\s+\*\*men[uú]\*\*\s+para\s+volver\s+al\s+menu\s+principal\._",
        "Escribe **menú** para volver al menú principal.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"_Escribe\s+men[uú]\s+para\s+volver\s+al\s+menu\s+principal\._",
        "Escribe **menú** para volver al menú principal.",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ensure_path_within(base_dir: Path, target_dir: Path) -> None:
    base_resolved = base_dir.resolve()
    target_resolved = target_dir.resolve()
    if target_resolved != base_resolved and base_resolved not in target_resolved.parents:
        raise RuntimeError(f"Ruta fuera del directorio permitido: {target_dir}")


EXTRA_CORS_ORIGINS = [
    _normalize_origin_value(origin)
    for origin in settings.RAW_EXTRA_CORS_ORIGINS.split(",")
    if origin.strip()
]


VOICE_ALLOWED_OPENAI_VOICES = {
    "alloy", "echo", "shimmer", "ash", "ballad", "coral", "sage", "verse", "marin", "cedar",
}


def _normalize_voice_config(payload: Any) -> Dict[str, Any]:
    """Normaliza el bloque opcional `voice` de un cliente.

    Tolera ausencia total del bloque (cliente sin canal de voz). El numero
    Twilio por cliente es opcional: si falta, el handler usa
    TWILIO_DEFAULT_PHONE_NUMBER. El routing Twilio->cliente_id se hace por la
    URL del webhook, no por el numero.
    """
    data = payload if isinstance(payload, dict) else {}
    voice_value = _sanitize_text(str(data.get("openai_voice", ""))).lower()
    if voice_value not in VOICE_ALLOWED_OPENAI_VOICES:
        voice_value = ""
    try:
        max_duration = int(data.get("max_duration_seconds", 0))
    except (TypeError, ValueError):
        max_duration = 0
    if max_duration <= 0:
        max_duration = 0  # 0 => usar VOICE_MAX_DURATION_SECONDS global
    max_duration = min(max_duration, 3600)
    return {
        "enabled": bool(data.get("enabled", False)),
        "twilio_phone_number": _sanitize_text(str(data.get("twilio_phone_number", "")))[:32],
        "openai_voice": voice_value,
        "realtime_model": _sanitize_text(str(data.get("realtime_model", "")))[:80],
        "greeting": _sanitize_text(str(data.get("greeting", "")), allow_multiline=True)[:600],
        "max_duration_seconds": max_duration,
        "sms_confirmation": bool(data.get("sms_confirmation", False)),
    }


def _voice_default_greeting(config: Dict[str, Any], voice_cfg: Dict[str, Any]) -> str:
    """Saludo con el que 'descuelga' el asistente de voz. Usa el mensaje de bienvenida
    de Apariencia (config.bienvenida) para que sea el MISMO agente que web y WhatsApp.
    Orden: saludo de voz especifico (solo via admin) -> bienvenida de Apariencia ->
    default. Compartido por telefono, test del panel y demo."""
    explicit = _sanitize_text(str(voice_cfg.get("greeting", "") or ""), allow_multiline=True)
    if explicit:
        return explicit
    bienvenida = _sanitize_text(str(config.get("bienvenida", "") or ""), allow_multiline=True)
    if bienvenida:
        return bienvenida
    nombre = config.get("nombre", "") or "la empresa"
    return f"Hola, soy el asistente de {nombre}. En que puedo ayudarte?"


def _normalize_optional_time_value(value: Any) -> str:
    candidate = _sanitize_text(str(value or ""))
    return candidate if settings.TIME_PATTERN.match(candidate) else ""


def _normalize_required_time_value(value: Any, field_label: str) -> str:
    candidate = _sanitize_text(str(value or ""))
    if not settings.TIME_PATTERN.match(candidate):
        raise HTTPException(status_code=400, detail=f"{field_label} invalida. Usa formato HH:MM.")
    return datetime.strptime(candidate, "%H:%M").strftime("%H:%M")


def _break_window_values(raw: Any) -> Tuple[str, str, str]:
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    elif hasattr(raw, "dict"):
        raw = raw.dict()
    if isinstance(raw, dict):
        start = raw.get("start", raw.get("hora_inicio", raw.get("break_start", "")))
        end = raw.get("end", raw.get("hora_fin", raw.get("break_end", "")))
        reason = raw.get("reason", raw.get("motivo", "Descanso"))
        return str(start or ""), str(end or ""), str(reason or "Descanso")
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        reason = raw[2] if len(raw) > 2 else "Descanso"
        return str(raw[0] or ""), str(raw[1] or ""), str(reason or "Descanso")
    return "", "", "Descanso"


def _normalize_break_windows(
    day_start: str,
    day_end: str,
    windows: Any = None,
    legacy_start: Any = "",
    legacy_end: Any = "",
) -> List[Dict[str, str]]:
    start = _normalize_required_time_value(day_start, "Hora de inicio")
    end = _normalize_required_time_value(day_end, "Hora de fin")
    if start >= end:
        raise HTTPException(status_code=400, detail="La hora de fin debe ser posterior a la hora de inicio.")

    raw_windows = windows if isinstance(windows, list) else []
    normalized: List[Dict[str, str]] = []
    for raw in raw_windows:
        pausa_inicio_raw, pausa_fin_raw, reason_raw = _break_window_values(raw)
        if not pausa_inicio_raw and not pausa_fin_raw:
            continue
        if not pausa_inicio_raw or not pausa_fin_raw:
            raise HTTPException(
                status_code=400,
                detail="Cada descanso debe tener inicio y fin, o quedar vacio.",
            )
        pausa_inicio = _normalize_required_time_value(pausa_inicio_raw, "Inicio del descanso")
        pausa_fin = _normalize_required_time_value(pausa_fin_raw, "Fin del descanso")
        if not (start < pausa_inicio < pausa_fin < end):
            raise HTTPException(
                status_code=400,
                detail="Cada descanso debe estar dentro del horario y tener inicio anterior al fin.",
            )
        normalized.append(
            {
                "start": pausa_inicio,
                "end": pausa_fin,
                "reason": (_sanitize_text(reason_raw) or "Descanso")[:80],
            }
        )

    if not normalized:
        legacy_pair = _normalize_break_window(start, end, legacy_start, legacy_end)
        if legacy_pair != ("", ""):
            normalized.append({"start": legacy_pair[0], "end": legacy_pair[1], "reason": "Descanso"})

    normalized.sort(key=lambda item: (item["start"], item["end"]))
    for idx in range(1, len(normalized)):
        previous = normalized[idx - 1]
        current = normalized[idx]
        if current["start"] < previous["end"]:
            raise HTTPException(status_code=400, detail="Los descansos diarios no pueden solaparse.")
    return normalized


def _first_break_pair(windows: Any) -> Tuple[str, str]:
    if isinstance(windows, list) and windows:
        first = windows[0]
        if isinstance(first, dict):
            return str(first.get("start", "") or ""), str(first.get("end", "") or "")
    return "", ""


def _normalize_break_window(
    day_start: str,
    day_end: str,
    break_start: Any = "",
    break_end: Any = "",
) -> Tuple[str, str]:
    pausa_inicio = _sanitize_text(str(break_start or ""))
    pausa_fin = _sanitize_text(str(break_end or ""))
    if not pausa_inicio and not pausa_fin:
        return "", ""
    if not pausa_inicio or not pausa_fin:
        raise HTTPException(
            status_code=400,
            detail="Indica inicio y fin del descanso, o deja ambos vacios.",
        )

    start = _normalize_required_time_value(day_start, "Hora de inicio")
    end = _normalize_required_time_value(day_end, "Hora de fin")
    pausa_inicio = _normalize_required_time_value(pausa_inicio, "Inicio del descanso")
    pausa_fin = _normalize_required_time_value(pausa_fin, "Fin del descanso")
    if start >= end:
        raise HTTPException(status_code=400, detail="La hora de fin debe ser posterior a la hora de inicio.")
    if not (start < pausa_inicio < pausa_fin < end):
        raise HTTPException(
            status_code=400,
            detail="El descanso debe estar dentro del horario y tener inicio anterior al fin.",
        )
    return pausa_inicio, pausa_fin



def _normalize_email(email: str) -> str:
    return str(email).strip().lower()


def _preferred_public_base_url(request: Optional[Request] = None) -> str:
    return _configured_public_base_url() or (_public_base_url(request) if request is not None else "")


def _configured_public_base_url() -> str:
    if not settings.APP_BASE_URL:
        return ""
    try:
        return _normalize_origin_value(settings.APP_BASE_URL)
    except RuntimeError:
        settings.logger.warning("APP_BASE_URL invalida; se usara la URL de la peticion.")
        return ""


def _strip_origin(value: str) -> str:
    return _normalize_origin_value(value)


def _request_origin(request: Request) -> str:
    origin = request.headers.get("origin", "").strip()
    if origin:
        try:
            return _strip_origin(origin)
        except RuntimeError:
            return ""

    referer = request.headers.get("referer", "").strip()
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            try:
                return _strip_origin(f"{parsed.scheme}://{parsed.netloc}")
            except RuntimeError:
                return ""

    return ""


def _forwarded_header_value(raw_value: str) -> str:
    return str(raw_value or "").split(",", 1)[0].strip()


def _public_base_url(request: Request) -> str:
    configured_base_url = _configured_public_base_url()
    if configured_base_url:
        return configured_base_url

    forwarded_proto = _forwarded_header_value(request.headers.get("x-forwarded-proto", ""))
    forwarded_host = _forwarded_header_value(request.headers.get("x-forwarded-host", ""))
    forwarded_port = _forwarded_header_value(request.headers.get("x-forwarded-port", ""))

    scheme = forwarded_proto or request.url.scheme or "http"
    host = forwarded_host or request.headers.get("host", "").strip() or request.url.netloc

    if not host:
        return str(request.base_url).rstrip("/")

    if forwarded_port and ":" not in host:
        is_default_port = (scheme == "http" and forwarded_port == "80") or (
            scheme == "https" and forwarded_port == "443"
        )
        if not is_default_port:
            host = f"{host}:{forwarded_port}"

    return f"{scheme}://{host}".rstrip("/")


