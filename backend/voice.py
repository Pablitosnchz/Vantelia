"""Canal de voz: Twilio Media Streams <-> OpenAI Realtime (refactor F3)."""
from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import httpx
from fastapi import BackgroundTasks, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from api_models import AppVoiceResponse, BookingReschedulePayload
from backend import agenda, appstate, booking, chat, clients, crm, db, demo_agenda, emailing, messaging, rag, security, settings, textnorm, timeutils

# Tareas en segundo plano (envios best-effort que no deben bloquear la respuesta de voz).
# Guardamos referencia para que asyncio no las recolecte antes de completarse.
_VOICE_BG_TASKS: set = set()


def _client_voice_plan_enabled(cliente_id: str) -> bool:
    """Whether the voice channel (phone) is available in the client's effective plan.

    Voz = solo Business. Para clientes con dueño se mira el plan de la suscripcion;
    si no, el flag voice_enabled del plan en config.
    """
    owner = db.db_get_client_owner(cliente_id)
    if owner:
        sub = db.db_get_subscription_for_user(owner)
        plan = settings._normalize_plan_slug(sub["plan"] if sub else settings.PLAN_DEFAULT)
        return "voice" in (settings._self_serve_plan(plan).get("features") or [])
    return bool(clients._plan_limits(clients._client_plan(cliente_id)).get("voice_enabled"))


def _voice_widget_enabled(cliente_id: str, config: Optional[Dict[str, Any]] = None) -> bool:
    """True si el negocio ha activado la voz EN EL WIDGET web (opt-in) y cumple los
    requisitos de voz (habilitada + plan Business). Permite que el cliente final pulse
    'hablar por voz' en el widget embebido."""
    config = config if config is not None else appstate.CONFIG_CLIENTES.get(cliente_id, {})
    voice_cfg = (config or {}).get("voice", {}) or {}
    return (
        bool(voice_cfg.get("enabled", False))
        and bool(voice_cfg.get("widget_enabled", False))
        and _client_voice_plan_enabled(cliente_id)
    )


def _app_voice_response(cliente_id: str, request: Request) -> "AppVoiceResponse":
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    voice_cfg = cfg.get("voice", {}) or {}
    plan_ok = _client_voice_plan_enabled(cliente_id)
    enabled = bool(voice_cfg.get("enabled", False)) and plan_ok
    webhook_url = f"{textnorm._public_base_url(request).rstrip('/')}/voice/{cliente_id}"
    if enabled:
        status_value, status_label = "active", "Activo"
    elif bool(voice_cfg.get("enabled", False)) and not plan_ok:
        status_value, status_label = "plan_required", "Requiere plan Business"
    else:
        status_value, status_label = "disabled", "Desactivado"
    return AppVoiceResponse(
        ok=True,
        cliente_id=cliente_id,
        enabled=enabled,
        twilio_phone_number=str(voice_cfg.get("twilio_phone_number", "") or ""),
        openai_voice=str(voice_cfg.get("openai_voice", "") or ""),
        webhook_url=webhook_url,
        plan_allows_voice=plan_ok,
        widget_enabled=bool(voice_cfg.get("widget_enabled", False)) and enabled,
        status=status_value,
        status_label=status_label,
    )


VOICE_NOISE_REDUCTION_TYPES = {"near_field", "far_field"}
VOICE_VAD_EAGERNESS_LEVELS = {"low", "medium", "high", "auto"}
VOICE_VAD_TYPES = {"server_vad", "semantic_vad"}
# Silencio (ms) que espera tras dejar de oir voz antes de responder. 650 ms sigue
# siendo agil, pero evita que respiraciones/eco corten al asistente con tanta facilidad.
VOICE_VAD_SILENCE_MS_DEFAULT = 650


def _voice_audio_input_config(voice_cfg: Dict[str, Any], *, default_noise: str = "far_field") -> Dict[str, Any]:
    """Bloque `audio.input` compartido por navegador (WebRTC) y telefono (Twilio).

    Centraliza turn detection + transcripcion + reduccion de ruido para que las dos
    rutas tengan exactamente el mismo comportamiento ante ruido e interrupciones.

    - server_vad (por defecto): detecta fin de turno por silencio con un tiempo EXACTO
      (`silence_duration_ms`), asi la respuesta llega rapido tras hablar/interrumpir
      (~0.6 s). `threshold` alto + `noise_reduction` evitan que el ruido abra turnos.
      Alternativa `semantic_vad` (voice_cfg.vad_type) si se prefiere robustez sobre
      velocidad.
    - noise_reduction: filtro nativo de OpenAI. far_field para sala/altavoz/linea,
      near_field para micro cercano/auriculares. Es la palanca directa contra el ruido.
    - interrupt_response=True: el llamante puede cortar (barge-in) como en una llamada real.
    """
    voice_cfg = voice_cfg or {}
    noise_type = str(voice_cfg.get("noise_reduction") or default_noise).strip().lower()
    if noise_type not in VOICE_NOISE_REDUCTION_TYPES:
        noise_type = default_noise
    vad_type = str(voice_cfg.get("vad_type") or "server_vad").strip().lower()
    if vad_type not in VOICE_VAD_TYPES:
        vad_type = "server_vad"

    if vad_type == "semantic_vad":
        eagerness = str(voice_cfg.get("vad_eagerness") or "high").strip().lower()
        if eagerness not in VOICE_VAD_EAGERNESS_LEVELS:
            eagerness = "high"
        turn_detection: Dict[str, Any] = {
            "type": "semantic_vad",
            "eagerness": eagerness,
            "create_response": True,
            "interrupt_response": True,
        }
    else:
        try:
            silence_ms = int(voice_cfg.get("vad_silence_ms") or VOICE_VAD_SILENCE_MS_DEFAULT)
        except (TypeError, ValueError):
            silence_ms = VOICE_VAD_SILENCE_MS_DEFAULT
        silence_ms = max(200, min(2000, silence_ms))
        try:
            threshold = float(voice_cfg.get("vad_threshold") or 0.72)
        except (TypeError, ValueError):
            threshold = 0.72
        threshold = max(0.0, min(1.0, threshold))
        try:
            prefix_ms = int(voice_cfg.get("vad_prefix_padding_ms") or 300)
        except (TypeError, ValueError):
            prefix_ms = 300
        prefix_ms = max(0, min(1000, prefix_ms))
        turn_detection = {
            "type": "server_vad",
            "threshold": threshold,
            "prefix_padding_ms": prefix_ms,
            "silence_duration_ms": silence_ms,
            "create_response": True,
            "interrupt_response": True,
        }
    return {
        "turn_detection": turn_detection,
        "noise_reduction": {"type": noise_type},
        # El cliente final siempre habla espanol: fijamos el idioma para que Whisper
        # no transcriba "si" como "see" ni mezcle otros idiomas en frases cortas.
        "transcription": {"model": "whisper-1", "language": "es"},
    }


def _voice_is_unintelligible(transcript: str) -> bool:
    """True si la transcripcion de un turno del llamante no aporta nada util (vacia, solo
    signos/ruido o demasiado corta). Sirve para la red de seguridad de reanudacion: cuando
    el llamante interrumpe pero no se entiende, pedimos confirmacion para continuar."""
    text = (transcript or "").strip()
    if not text:
        return True
    # Solo letras/numeros cuentan como contenido real.
    meaningful = re.sub(r"[^0-9a-záéíóúüñ]", "", text.lower())
    return len(meaningful) < 2


async def _mint_voice_session(
    cliente_id: str,
    config: Dict[str, Any],
    *,
    max_seconds: int,
    log_tag: str = "voice",
) -> Dict[str, Any]:
    """Mintea un client_secret EFIMERO de OpenAI Realtime para hablar por WebRTC desde
    el navegador. Reutiliza instructions/tools/voz/saludo del cliente (config.voice), por
    lo que telefono, test del panel y demo comparten el mismo cerebro. La OPENAI_API_KEY
    nunca sale del backend. Lanza HTTPException(502) si OpenAI falla.

    El llamador es responsable del gating (plan/rate limit) y de comprobar OPENAI_API_KEY.
    """
    voice_cfg = config.get("voice") or {}
    realtime_model = voice_cfg.get("realtime_model") or settings.VOICE_REALTIME_MODEL
    openai_voice = voice_cfg.get("openai_voice") or settings.VOICE_OPENAI_VOICE

    session_body = {
        "session": {
            "type": "realtime",
            "model": realtime_model,
            "instructions": _voice_build_instructions(cliente_id, config),
            "audio": {
                # Navegador WebRTC: micro cercano/auriculares => near_field por defecto.
                # En WebRTC OpenAI conoce el audio reproducido y trunca automaticamente la
                # parte que el usuario no llego a oir al interrumpir.
                "input": _voice_audio_input_config(voice_cfg, default_noise="near_field"),
                "output": {"voice": openai_voice},
            },
            "tools": _voice_booking_tools(cliente_id, config),
            "tool_choice": "auto",
        }
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=session_body,
            )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[%s] no se pudo mintear token (%s): %s", log_tag, cliente_id, exc)
        raise HTTPException(status_code=502, detail="No se pudo iniciar el asistente de voz.")

    if resp.status_code >= 300:
        settings.logger.error(
            "[%s] OpenAI client_secrets %s (%s): %s",
            log_tag, resp.status_code, cliente_id, resp.text[:400],
        )
        raise HTTPException(status_code=502, detail="No se pudo iniciar el asistente de voz.")

    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        data = {}
    # GA devuelve {"value": "ek_...", ...}; toleramos la forma anidada por compat.
    client_secret = (
        data.get("value")
        or (data.get("client_secret") or {}).get("value")
        or ""
    )
    if not client_secret:
        settings.logger.error("[%s] respuesta sin client_secret (%s): %s", log_tag, cliente_id, json.dumps(data)[:400])
        raise HTTPException(status_code=502, detail="No se pudo iniciar el asistente de voz.")

    return {
        "client_secret": client_secret,
        "model": realtime_model,
        "voice": openai_voice,
        "cliente_id": cliente_id,
        "greeting": textnorm._voice_default_greeting(config, voice_cfg),
        "max_duration_seconds": max_seconds,
    }


VOICE_BOOKING_KEYWORDS = (
    "cita", "reserva", "reservar", "agendar", "agenda", "appointment",
    "turno", "coger cita", "pedir cita", "concertar",
)


def _get_voice_config(cliente_id: str) -> Optional[Dict[str, Any]]:
    """Devuelve el bloque voice del cliente si existe, esta habilitado y el plan lo
    incluye (voz = solo Business). None en cualquier otro caso."""
    config = appstate.CONFIG_CLIENTES.get(cliente_id)
    if not config:
        return None
    voice_cfg = config.get("voice") or {}
    if not voice_cfg.get("enabled"):
        return None
    if not _client_voice_plan_enabled(cliente_id):
        return None
    return voice_cfg


async def _voice_form_params(request: Request) -> Dict[str, str]:
    """Parsea el cuerpo x-www-form-urlencoded de Twilio sin depender de
    python-multipart. Twilio siempre envia sus webhooks como urlencoded."""
    raw = await request.body()
    parsed = parse_qsl(raw.decode("utf-8", errors="ignore"), keep_blank_values=True)
    return {key: value for key, value in parsed}


def _voice_request_url(request: Request) -> str:
    """URL publica completa (incluyendo path y query) tal y como la firma Twilio."""
    base = textnorm._public_base_url(request).rstrip("/")
    url = f"{base}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    return url


def _voice_stream_ws_url(request: Request, cliente_id: str) -> str:
    base = textnorm._public_base_url(request).rstrip("/")
    ws_base = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return f"{ws_base}/voice/stream/{cliente_id}"


def _voice_twiml_unavailable() -> Response:
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Response><Say language="es-ES">Lo sentimos, este servicio no esta disponible.</Say>'
        "<Hangup/></Response>"
    )
    return Response(content=twiml, media_type="application/xml")


def _voice_twiml_connect_stream(ws_url: str, call_sid: str) -> Response:
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<Stream url="{escape(ws_url, quote=True)}">'
        f'<Parameter name="call_sid" value="{escape(call_sid or "", quote=True)}"/>'
        "</Stream></Connect></Response>"
    )
    return Response(content=twiml, media_type="application/xml")


def _voice_outbound_greeting(config: Dict[str, Any], booking_row: sqlite3.Row) -> str:
    nombre = (config.get("nombre") or "el negocio").strip()
    servicio = (booking_row["servicio"] or "su cita") if booking_row else "su cita"
    return (
        f"Hola, le llamo de {nombre} para confirmar su cita de {servicio}. "
        "¿Le sigue viniendo bien?"
    )


def _voice_outbound_confirm_instructions(cliente_id: str, config: Dict[str, Any], booking_row: sqlite3.Row) -> str:
    base = _voice_build_instructions(cliente_id, config)
    nombre = (booking_row["nombre"] or "el cliente") if booking_row else "el cliente"
    servicio = (booking_row["servicio"] or "su cita") if booking_row else "su cita"
    tz = config.get("booking", {}).get("timezone", settings.DEFAULT_TIMEZONE)
    fecha = booking_row["booking_date"] if booking_row else ""
    hora = booking_row["booking_time"] if booking_row else ""
    fecha_voz = _voice_say_date(fecha, tz) if fecha else "su proxima cita"
    hora_voz = _voice_say_time(hora) if hora else ""
    extra = (
        "\n\nLLAMADA SALIENTE DE CONFIRMACION (TU llamas al cliente; ya tienes su cita delante).\n"
        f"- Llamas a {nombre} para confirmar su cita: {servicio}, {fecha_voz} a {hora_voz}.\n"
        "- YA SABES cual es la cita. NO pidas el numero de reserva, NO uses consultar_cita y NO envies codigo "
        "de verificacion: el telefono ya esta verificado por ser una llamada a su propio numero.\n"
        "- Saluda, di de parte de que negocio llamas y pide que confirme la asistencia. Breve y cordial.\n"
        "- Si confirma (un 'si', 'vale', 'perfecto' o similar), llama de inmediato a confirmar_cita y despidete "
        "dando las gracias. No vuelvas a pedir datos ni repitas el proceso.\n"
        "- Si quiere cancelar, usa cancelar_cita; si quiere otra hora, mira huecos y usa reprogramar_cita. No "
        "pidas codigo de reserva (ya esta verificado).\n"
        "- Si pide que no le llamen, pide disculpas, toma nota y despidete sin insistir.\n"
        "- No alargues: es una llamada de cortesia para confirmar.\n"
    )
    return base + extra


def _voice_place_outbound_call(
    cliente_id: str, booking_row: sqlite3.Row, *, base_url: str = "", purpose: str = "confirm"
) -> Dict[str, Any]:
    """Lanza una llamada SALIENTE de IA (Twilio Calls API) que conecta con el puente
    Realtime en modo confirmacion. Sincrona (red): envolver en _to_thread desde async.
    Gating: plan Business + numero Twilio del negocio + telefono del cliente."""
    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    voice_cfg = config.get("voice") or {}
    if not _client_voice_plan_enabled(cliente_id):
        return {"ok": False, "error": "La voz requiere plan Business."}
    from_number = str(voice_cfg.get("twilio_phone_number") or settings.TWILIO_DEFAULT_PHONE_NUMBER or "").strip()
    to_number = str((booking_row["telefono"] if booking_row else "") or "").strip()
    sid, tok = settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN
    if not from_number:
        return {"ok": False, "error": "El negocio no tiene numero de voz configurado."}
    if not to_number:
        return {"ok": False, "error": "La cita no tiene telefono al que llamar."}
    if not (sid and tok):
        return {"ok": False, "error": "La telefonia no esta configurada."}
    base = (base_url or settings.APP_BASE_URL or "https://app.vantelia.es").rstrip("/")
    ws_base = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    # El contexto de la cita viaja en el query string ademas del id: asi el puente
    # arma la llamada SALIENTE de confirmacion aunque la cita no este en la agenda
    # (prueba del Seguimiento con cita efimera) o se borre entre el lanzamiento y la
    # conexion de Twilio, sin degradar a modo entrante.
    ws_url = (
        f"{ws_base}/voice/stream/{cliente_id}"
        f"?mode=confirm&booking_id={quote(str(booking_row['id']))}&to={quote(to_number)}"
        f"&b_nombre={quote(str(booking_row['nombre'] or ''))}"
        f"&b_servicio={quote(str(booking_row['servicio'] or ''))}"
        f"&b_fecha={quote(str(booking_row['booking_date'] or ''))}"
        f"&b_hora={quote(str(booking_row['booking_time'] or ''))}"
    )
    # El contexto va tambien como <Parameter> (customParameters en el evento 'start'):
    # redundancia con el query string por si algun proxy/Twilio no preserva la query.
    def _p(name: str, value: Any) -> str:
        return f'<Parameter name="{name}" value="{escape(str(value or ""), quote=True)}"/>'
    params_xml = (
        _p("mode", "confirm")
        + _p("booking_id", booking_row["id"])
        + _p("to", to_number)
        + _p("b_nombre", booking_row["nombre"])
        + _p("b_servicio", booking_row["servicio"])
        + _p("b_fecha", booking_row["booking_date"])
        + _p("b_hora", booking_row["booking_time"])
    )
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?><Response><Connect>'
        f'<Stream url="{escape(ws_url, quote=True)}">{params_xml}</Stream></Connect></Response>'
    )
    try:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"
        with httpx.Client(timeout=20) as client:
            resp = client.post(url, data={"To": to_number, "From": from_number, "Twiml": twiml}, auth=(sid, tok))
        if resp.status_code >= 300:
            settings.logger.error("[voice] Twilio call error (%s): %s", resp.status_code, resp.text[:300])
            return {"ok": False, "error": "No se pudo iniciar la llamada."}
        call_sid = str((resp.json() or {}).get("sid", ""))
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] outbound call exception (%s): %s", cliente_id, exc)
        return {"ok": False, "error": "No se pudo iniciar la llamada."}
    try:
        with db._get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO voice_calls (call_sid, cliente_id, from_number, to_number, started_at, status,
                                         direction, purpose, booking_id)
                VALUES (?, ?, ?, ?, ?, 'in_progress', 'outbound', ?, ?)
                ON CONFLICT(call_sid) DO UPDATE SET direction='outbound',
                    purpose=excluded.purpose, booking_id=excluded.booking_id
                """,
                (call_sid, cliente_id, from_number, to_number, timeutils._utc_now().isoformat(),
                 purpose, str(booking_row["id"])),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] no se pudo registrar llamada saliente %s: %s", call_sid, exc)
    booking._record_booking_audit(
        booking_row["id"], cliente_id, "confirm_call_placed", {"call_sid": call_sid, "purpose": purpose}
    )
    return {"ok": True, "call_sid": call_sid}


def _voice_call_register(call_sid: str, cliente_id: str, from_number: str, to_number: str) -> None:
    now_iso = timeutils._utc_now().isoformat()
    try:
        with db._get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO voice_calls (call_sid, cliente_id, from_number, to_number, started_at, status)
                VALUES (?, ?, ?, ?, ?, 'in_progress')
                ON CONFLICT(call_sid) DO UPDATE SET
                    cliente_id=excluded.cliente_id,
                    from_number=excluded.from_number,
                    to_number=excluded.to_number
                """,
                (call_sid, cliente_id, from_number, to_number, now_iso),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] no se pudo registrar llamada %s: %s", call_sid, exc)
    else:
        crm._crm_upsert_contact(
            cliente_id,
            phone=from_number,
            source="voice",
            status="nuevo",
            entity_type="voice",
            entity_id=call_sid,
        )


def _voice_call_from_number(call_sid: str) -> str:
    """Recupera el numero desde el que llaman, para verificar titularidad de citas."""
    if not call_sid:
        return ""
    try:
        with db._get_db_connection() as conn:
            row = conn.execute(
                "SELECT from_number FROM voice_calls WHERE call_sid = ? LIMIT 1",
                (call_sid,),
            ).fetchone()
            return (row[0] if row else "") or ""
    except Exception:  # noqa: BLE001
        return ""


def _voice_call_location_id(call_sid: str, cliente_id: str) -> str:
    """Centro asociado a la linea LLAMADA (un numero por centro). '' si no mapeado."""
    if not call_sid:
        return ""
    try:
        with db._get_db_connection() as conn:
            row = conn.execute(
                "SELECT to_number FROM voice_calls WHERE call_sid = ? LIMIT 1",
                (call_sid,),
            ).fetchone()
    except Exception:  # noqa: BLE001
        return ""
    to_number = (row[0] if row else "") or ""
    if not to_number:
        return ""
    return agenda._location_for_channel(cliente_id, voice_phone_number=to_number)


def _voice_load_knowledge(cliente_id: str, max_chars: int = 16000) -> str:
    """Lee los .txt del cliente para inyectar conocimiento en la sesion Realtime
    (la Realtime API no hace RAG; necesitamos el contexto en las instructions)."""
    try:
        data_dir = rag._client_data_dir(cliente_id)
    except Exception:  # noqa: BLE001
        return ""
    if not data_dir.exists():
        return ""
    parts: List[str] = []
    for path in sorted(data_dir.glob("*.txt")):
        try:
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:  # noqa: BLE001
            continue
    return "\n\n".join(parts).strip()[:max_chars]


def _voice_booking_enabled(cliente_id: str, config: Dict[str, Any]) -> bool:
    return bool(config.get("booking", {}).get("enabled")) and clients._client_booking_plan_enabled(cliente_id)


def _voice_service_options(cliente_id: str, location_id: str = "") -> List[str]:
    try:
        services = booking._public_services_for_booking(cliente_id, location_id=location_id)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[voice] no se pudieron cargar servicios (%s): %s", cliente_id, exc)
        return []
    names: List[str] = []
    for service in services:
        if not isinstance(service, dict):
            continue
        name = textnorm._sanitize_text(str(service.get("nombre") or service.get("name") or ""))
        if name and name not in names:
            names.append(name)
    return names


def _voice_service_catalog(cliente_id: str, location_id: str = "") -> List[str]:
    """Lineas 'Nombre · N min · precio' del catalogo real, para que el asistente pueda
    enumerar y presupuestar por voz sin inventarse precios ni duraciones."""
    try:
        services = booking._public_services_for_booking(cliente_id, location_id=location_id)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[voice] no se pudo cargar el catalogo (%s): %s", cliente_id, exc)
        return []
    lines: List[str] = []
    seen: set = set()
    for service in services:
        if not isinstance(service, dict):
            continue
        name = textnorm._sanitize_text(str(service.get("nombre") or service.get("name") or ""))
        if not name or name in seen:
            continue
        seen.add(name)
        parts = [name]
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
        if price_cents > 0 and price_label:
            parts.append(price_label)
        elif price_cents <= 0:
            parts.append("a consultar")
        lines.append("- " + " · ".join(parts))
    return lines


def _voice_resolve_location_id(cliente_id: str, centro: str) -> str:
    """Resuelve el nombre de centro que dice el cliente a su location_id. '' si no encaja."""
    centro = textnorm._sanitize_text(centro or "").strip()
    if not centro:
        return ""
    try:
        rows = agenda._list_location_rows(cliente_id, include_inactive=False)
    except Exception:  # noqa: BLE001
        return ""

    def _norm(value: str) -> str:
        value = unicodedata.normalize("NFKD", (value or "").lower())
        return "".join(c for c in value if not unicodedata.combining(c)).strip()

    key = _norm(centro)
    if not key:
        return ""
    for row in rows:  # match exacto por nombre
        if _norm(str(row["name"])) == key:
            return str(row["id"])
    for row in rows:  # match parcial: "centro" -> "Sede Centro"
        nk = _norm(str(row["name"]))
        if nk and (key in nk or nk in key):
            return str(row["id"])
    return ""


def _voice_service_required_response(cliente_id: str, location_id: str = "", *, invalid: str = "") -> Dict[str, Any]:
    options = _voice_service_options(cliente_id, location_id)
    visible = options[:5]
    if invalid:
        prompt = "No encuentro ese servicio en la agenda. Pregunta cual quiere reservar"
    else:
        prompt = "Antes de reservar necesito saber que servicio quiere"
    if visible:
        prompt += ": " + ", ".join(visible[:3])
        if len(visible) > 3:
            prompt += ", u otro de la lista"
    prompt += "."
    return {
        "ok": False,
        "needs_service": True,
        "missing_field": "servicio",
        "servicios_disponibles": visible,
        "error": prompt,
        "mensaje_voz": prompt,
    }


def _voice_normalize_booking_phone(phone: str) -> str:
    """Telefono de cliente para una reserva de voz.

    En llamadas ES es comun dictar solo los 9 digitos. Si el modelo pierde un
    digito, devolvemos vacio para que pregunte otra vez antes de crear la cita.
    """
    return messaging._normalize_sms_recipient(phone)


# Espanol hablado para fechas y horas: evita que el modelo lea "2026-06-26" o
# "once cero cero". Queremos "el 26 de junio" y "las once de la manana".
_VOICE_HOUR_WORDS = {
    1: "la una", 2: "las dos", 3: "las tres", 4: "las cuatro", 5: "las cinco",
    6: "las seis", 7: "las siete", 8: "las ocho", 9: "las nueve", 10: "las diez",
    11: "las once", 12: "las doce",
}
_VOICE_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "octubre", "noviembre", "diciembre",
]
_VOICE_WEEKDAYS_ES = [
    "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
]


def _voice_time_period_es(hour24: int) -> str:
    if 5 <= hour24 < 13:
        return "de la manana"
    if 13 <= hour24 < 21:
        return "de la tarde"
    return "de la noche"


def _voice_say_time(hora: str, with_period: bool = True) -> str:
    """'11:00' -> 'las once de la manana'; '09:30' -> 'las nueve y media de la manana'.

    with_period=False omite 'de la manana/tarde/noche' (util al enumerar varias horas
    seguidas y decir el tramo una sola vez al final).
    """
    try:
        parts = str(hora).split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return str(hora)
    period_h = (h + 1) % 24 if m == 45 else h
    if period_h == 12 and m == 0:
        return "las doce del mediodia" if with_period else "las doce"
    if period_h == 0 and m == 0:
        return "las doce de la noche" if with_period else "las doce"
    h12 = period_h % 12 or 12
    base_h = _VOICE_HOUR_WORDS.get(h12, f"las {h12}")
    if m == 0:
        frac = ""
    elif m == 15:
        frac = " y cuarto"
    elif m == 30:
        frac = " y media"
    elif m == 45:
        frac = " menos cuarto"
    else:
        frac = f" y {m}"
    period = f" {_voice_time_period_es(period_h)}" if with_period else ""
    return f"{base_h}{frac}{period}"


def _voice_say_date(fecha: str, tz: str = "") -> str:
    """'2026-06-26' -> 'hoy' / 'manana' / 'el viernes 26 de junio'."""
    try:
        d = datetime.strptime(str(fecha), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return str(fecha)
    if tz:
        try:
            today = datetime.now(ZoneInfo(tz)).date()
            delta = (d - today).days
            if delta == 0:
                return "hoy"
            if delta == 1:
                return "manana"
        except Exception:  # noqa: BLE001
            pass
    return f"el {_VOICE_WEEKDAYS_ES[d.weekday()]} {d.day} de {_VOICE_MONTHS_ES[d.month - 1]}"


def _voice_join_es(items: List[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " y " + items[-1]


def _voice_build_instructions(cliente_id: str, config: Dict[str, Any]) -> str:
    base = rag._build_system_prompt(cliente_id, config)
    # En una llamada de voz no existe el formulario del chat: quita cualquier
    # instruccion del sentinel [MOSTRAR_FORMULARIO] para que el modelo no lo narre
    # ni se quede esperando a "mostrar" nada. En voz se reserva con herramientas.
    base = "\n".join(
        line for line in base.split("\n") if settings.BOOKING_SENTINEL not in line
    )
    service_catalog = _voice_service_catalog(cliente_id)
    if service_catalog:
        listed_services = "\n".join(service_catalog[:40])
        services_block = (
            "\nCATALOGO REAL DE SERVICIOS (nombre, duracion y precio) PARA RESERVAR, ENUMERAR Y PRESUPUESTAR:\n"
            f"{listed_services}\n"
            "- Si el cliente pregunta que servicios hay, cuanto cuestan o cuanto duran, responde SOLO con los datos "
            "de esta lista. No uses ejemplos, categorias ni precios de la base de conocimiento si no estan aqui.\n"
            "- Di los precios y las duraciones en palabras naturales ('cuarenta euros', 'una hora', 'cuarenta y cinco "
            "minutos'). Si un servicio aparece 'a consultar', no inventes una cifra: dilo y ofrece confirmarlo.\n"
            "- Si el cliente pide un servicio que no esta en esta lista, no lo aceptes como sinonimo ni lo confirmes. "
            "Dile que no lo encuentras y ofrece 2 o 3 servicios reales de la lista.\n"
            "- Para reservar, el parametro servicio de las herramientas debe ser uno de estos nombres, exactamente.\n"
        )
    else:
        services_block = ""

    voice_rules = (
        "\n\nCANAL: LLAMADA TELEFONICA POR VOZ. Eres la recepcionista del negocio, una persona real, no un robot.\n"
        "TONO Y FORMA (habla como una persona):\n"
        "- Habla SIEMPRE en espanol de Espana, con tono calido y cercano, como alguien que coge el telefono en recepcion.\n"
        "- Frases cortas, UNA idea por turno. Nada de parrafos ni listas largas leidas de un tiron.\n"
        "- Usa con naturalidad y moderacion expresiones como 'vale', 'perfecto', 'claro', 'un momento', 'a ver'.\n"
        "- Di numeros, horas, fechas y precios SIEMPRE en palabras naturales de Espana: 'las cinco y media', "
        "'a las diez de la manana', 'cuarenta euros', 'el 26 de junio'. NUNCA leas una hora como '09:00' ni digas "
        "'cero cero' (di 'las nueve', no 'nueve cero cero'); NUNCA leas una fecha tipo '2026-06-26' (di el dia y el "
        "mes, o 'manana'/'hoy').\n"
        "- Mantente humana y directa: una frase natural por turno, con palabras como 'vale', 'perfecto' o 'listo' "
        "cuando encajen. No seas seca ni telegrafica, pero no expliques el proceso interno.\n"
        "- No leas en voz alta URLs, simbolos, markdown, asteriscos ni emojis.\n"
        "- NUNCA digas que eres una IA, un asistente virtual, un modelo o un sistema; ni menciones herramientas internas, "
        "ni codigos, ni etiquetas entre corchetes como [MOSTRAR_FORMULARIO].\n"
        "- Empieza saludando breve y preguntando en que puedes ayudar. Saluda UNA sola vez al "
        "principio de la llamada: no vuelvas a presentarte ni a repetir el saludo despues.\n"
        "INFORMACION POR TROZOS (clave para sonar humana):\n"
        "- Cuando enumeres servicios, horarios o precios, da solo DOS o TRES y haz una pausa preguntando "
        "'¿quieres que te siga contando?' o '¿te cuento mas?'. No sueltes la lista entera de golpe.\n"
        "- Asi el llamante puede pararte cuando ya tiene lo que necesita, como en una conversacion real.\n"
        "INTERRUPCIONES (comportate como un humano al que cortan):\n"
        "- No te cortes por ruidos, respiraciones, toses o monosilabos accidentales. Solo cedes el turno "
        "si el llamante habla de verdad y claro.\n"
        "- Si te interrumpe y le entiendes: NO reinicies ni repitas la frase desde el principio. Atiende "
        "primero lo que te ha dicho y, si aun falta algo util, retoma desde la siguiente idea que no habias dicho.\n"
        "- Si te interrumpe y NO entiendes lo que ha dicho (te llego ruido o algo confuso): no adivines ni "
        "te quedes mudo. Discúlpate breve ('perdona, no te he pillado bien') y pregunta si quieres que "
        "continues con lo que le estabas explicando, NOMBRANDOLO. Por ejemplo, si ibas por los servicios: "
        "'¿sigo contandote los servicios?'. Recuerda siempre por donde ibas y ofrece retomarlo justo ahi.\n"
        "- Si te pide que sigas, continua exactamente desde donde lo dejaste, sin repetir lo ya dicho.\n"
        "- Si no entiendes una peticion normal, pide con amabilidad que la repita.\n"
        "SILENCIO Y RUIDO:\n"
        "- NUNCA repitas la misma frase dos veces seguidas. Si solo oyes silencio, ruido de fondo "
        "o un eco de tu propia voz, NO respondas ni te repitas: espera en silencio a que la persona "
        "hable. Si tras una pausa larga no dice nada, pregunta una sola vez '¿Sigue ahi?' y vuelve a esperar.\n"
    )

    tz = config.get("booking", {}).get("timezone", settings.DEFAULT_TIMEZONE)
    try:
        now_local = datetime.now(ZoneInfo(tz))
    except Exception:  # noqa: BLE001
        now_local = timeutils._utc_now()
    fecha_hoy = now_local.strftime("%Y-%m-%d")
    dia_semana = now_local.strftime("%A")

    if _voice_booking_enabled(cliente_id, config):
        booking_block = (
            "\nAGENDA DE CITAS POR VOZ (puedes reservar tu misma en la llamada):\n"
            f"- Hoy es {fecha_hoy} ({dia_semana}), zona horaria {tz}. Calcula fechas relativas "
            "('manana', 'el lunes que viene') a partir de hoy y pasalas SIEMPRE como YYYY-MM-DD.\n"
            "- Consultar la agenda es instantaneo. Puedes decir una frase muy breve como 'un momento' "
            "justo antes de mirar la disponibilidad, pero NO te quedes esperando sin mas: llama a la "
            "herramienta en el mismo turno. Nunca prometas que 'ahora lo miras' sin usar la herramienta.\n"
            "- Si el cliente quiere una cita y no ha dicho el servicio, preguntale primero que servicio quiere. "
            "No consultes disponibilidad ni crees la cita con un servicio generico o vacio.\n"
            "- Para ver huecos libres usa la herramienta consultar_disponibilidad(fecha). Ofrece 2 o 3 horas "
            "concretas pero DEJA CLARO que hay mas si las hay (por ejemplo 'y tambien me quedan por la tarde' o "
            "'tengo mas horas ese dia'); no des a entender que solo quedan esas tres ni leas la lista entera. Si el "
            "cliente pide una franja ('por la tarde', 'a partir de las cinco') o que le digas mas, ofrece huecos de "
            "esa franja a partir de la lista de la herramienta.\n"
            "- REGLA DE ORO DE LA HORA: solo puedes ofrecer, aceptar o confirmar una hora que consultar_disponibilidad "
            "acabe de devolver como libre. Esa lista de huecos es la UNICA fuente de horas reservables: no te inventes "
            "horas ni propongas una hora que no este en ella.\n"
            "- Si el cliente pide o propone una hora concreta (por ejemplo 'a las tres'), comprueba si esta en la ultima "
            "lista de huecos. Si esta, sigue. Si NO esta, es de otro dia, o tienes cualquier duda, vuelve a llamar a "
            "consultar_disponibilidad ANTES de responder y solo aceptala si aparece libre. NUNCA digas 'si, sin problema' "
            "ni 'reservamos a las X' a una hora que no acabas de ver libre en la herramienta.\n"
            "- Si esa hora no esta libre, dilo con tacto y ofrece 2 o 3 horas reales de la lista. La confirmacion "
            "definitiva la da crear_cita: hasta que no devuelva ok, la cita NO esta hecha (no la des por reservada).\n"
            "- Antes de reservar confirma en voz alta: nombre, telefono, servicio, dia y hora (y el centro "
            "si el negocio tiene varios).\n"
            "- Pide el telefono y repitelo para asegurarte de que lo has cogido bien. En Espana debe tener 9 digitos "
            "(o +34 seguido de 9 digitos). Si no estas segura de todos los digitos, no confirmes: pide que lo repita.\n"
            "- El email no es obligatorio por telefono. Si el cliente lo da o dice que prefiere recibir avisos por email, "
            "pidelo y pasalo en crear_cita; si no, continua solo con telefono.\n"
            "- Crea la reserva con la herramienta crear_cita. Despues de usar una herramienta, responde SIEMPRE en "
            "voz alta de forma breve. Si el resultado trae mensaje_voz, dilo casi literal y no anadas explicaciones.\n"
            "- En cuanto el cliente confirme los datos, LLAMA a crear_cita en ESE MISMO turno. Como mucho di "
            "'un momento' UNA vez; no anuncies dos veces que vas a crearla, no describas el proceso interno y no "
            "esperes entre turnos: crear la cita es inmediato. Cuando la herramienta responda, da una sola frase "
            "de confirmacion.\n"
            "- Si crear_cita devuelve ok, confirma claramente que la cita queda confirmada. Si devuelve error, "
            "explica el motivo con tacto y ofrece otra hora.\n"
            "- crear_cita devuelve un numero de reserva (formato R y seis digitos, por ejemplo R-481523). "
            "Diselo al cliente digito a digito y pidele que lo apunte porque le servira "
            "para cambiar o cancelar la cita.\n"
            "- CAMBIAR O CANCELAR UNA CITA: pide el numero de reserva (formato R y seis digitos) y llama a "
            "consultar_cita DE INMEDIATO, en el mismo turno y SIN anunciarlo (no digas 'un momento, lo compruebo': "
            "la consulta es instantanea). Cuando devuelva ok, di en voz alta que cita has encontrado (servicio, dia "
            "y hora) y pide que confirme que es esa. Si no la encuentra, dilo enseguida y pide que repita el numero; "
            "NO sigas como si la cita existiera.\n"
            "- VERIFICACION DE IDENTIDAD (antes de cambiar o cancelar): una vez confirmada la cita, usa "
            "enviar_codigo_verificacion para mandarle un codigo de 4 digitos a su telefono o email registrado; dile "
            "por que medio se lo has enviado (NUNCA leas tu el codigo). Pide que te lo lea y validalo con "
            "verificar_codigo. Solo si verificar_codigo devuelve ok puedes continuar. Si el codigo no llega o no "
            "tiene contacto registrado, puedes verificar pidiendo el telefono o el email de la reserva.\n"
            "- Tras verificar: para CANCELAR usa cancelar_cita con ese mismo numero; para REPROGRAMAR pide la nueva "
            "fecha/hora, comprueba huecos con consultar_disponibilidad y usa reprogramar_cita.\n"
            "- No narres pasos internos. Evita frases como 'voy a proceder', 'espera un segundo', 'la cancelo ahora' "
            "o 'ya puedo proceder'. Si el codigo se verifica y ya sabes que quiere cancelar o reprogramar, ejecuta "
            "la accion directamente y da UNA sola frase final humana: por ejemplo, 'Listo, he verificado el codigo "
            "y he cancelado la cita.'\n"
            "- Seguridad: estas herramientas solo funcionan si el telefono desde el que llaman coincide con el de la "
            "reserva. Si devuelven needs_verification, pide con tacto el telefono o el email con el que reservaron y "
            "vuelve a intentarlo pasando ese dato. No confirmes una cancelacion o cambio sin que la herramienta "
            "devuelva ok.\n"
            "- No inventes huecos ni confirmes una cita sin haber llamado a crear_cita con exito.\n"
        )
        if booking._ai_payment_sending_available(cliente_id):
            booking_block += (
                "- COBRO: si el cliente quiere pagar o dejar una senal de su cita, confirmale en voz alta el "
                "importe (lo fija el negocio segun el servicio; nunca lo decide el cliente) y usa la herramienta "
                "enviar_enlace_pago. Le llegara un SMS con un enlace seguro. No leas la URL en voz alta: solo di "
                "que le envias el enlace por mensaje. Si devuelve error, explicalo con tacto.\n"
            )
        try:
            if len(agenda._list_location_rows(cliente_id, include_inactive=False)) > 1:
                booking_block += (
                    "- CENTRO (este negocio tiene VARIOS centros): pregunta SIEMPRE en que centro quiere la cita "
                    "ANTES de mirar disponibilidad, y pasa ese centro en el parametro 'centro' de "
                    "consultar_disponibilidad y de crear_cita. La disponibilidad y la reserva seran de ese centro.\n"
                )
        except Exception:  # noqa: BLE001
            pass
    else:
        booking_block = (
            "\nAGENDA: la reserva online no esta activa para este negocio. Si piden cita, recoge nombre, "
            "telefono y motivo, y di que el equipo les llamara para confirmar.\n"
        )

    # Si el negocio desactivo la verificacion por codigo (todos los canales OFF en Seguimiento),
    # el asistente verifica por telefono/email en vez de enviar un OTP.
    try:
        _otp_on = any((booking._follow_up_config(cliente_id).get("voice_otp_channels") or {}).values())
    except Exception:  # noqa: BLE001
        _otp_on = True
    if not _otp_on:
        booking_block = booking_block.replace(
            "- VERIFICACION DE IDENTIDAD (antes de cambiar o cancelar): una vez confirmada la cita, usa "
            "enviar_codigo_verificacion para mandarle un codigo de 4 digitos a su telefono o email registrado; dile "
            "por que medio se lo has enviado (NUNCA leas tu el codigo). Pide que te lo lea y validalo con "
            "verificar_codigo. Solo si verificar_codigo devuelve ok puedes continuar. Si el codigo no llega o no "
            "tiene contacto registrado, puedes verificar pidiendo el telefono o el email de la reserva.\n",
            "- VERIFICACION DE IDENTIDAD (antes de cambiar o cancelar): por seguridad pide el telefono o el email "
            "con el que se hizo la reserva y solo continua si coincide. No uses enviar_codigo_verificacion.\n",
        )

    knowledge = _voice_load_knowledge(cliente_id)
    knowledge_block = (
        f"\n\nBASE DE CONOCIMIENTO DEL NEGOCIO (para datos generales como direccion, condiciones o FAQs. "
        f"Si hay CATALOGO REAL DE SERVICIOS arriba, ese catalogo manda para nombres de servicios y reservas):\n{knowledge}\n"
        if knowledge
        else ""
    )
    return base + voice_rules + services_block + booking_block + knowledge_block


def _voice_booking_tools(
    cliente_id: str, config: Dict[str, Any], *, include_confirm: bool = False
) -> List[Dict[str, Any]]:
    """Herramientas Realtime para agendar en vivo. Vacio si el cliente no tiene reserva.
    include_confirm=True anade `confirmar_cita` (llamadas salientes de confirmacion)."""
    if not _voice_booking_enabled(cliente_id, config):
        return []
    service_required = bool(_voice_service_options(cliente_id))
    tools: List[Dict[str, Any]] = [
        {
            "type": "function",
            "name": "consultar_disponibilidad",
            "description": (
                "Devuelve las horas libres de un dia concreto. Llamala antes de proponer horas. "
                "La fecha debe ir en formato YYYY-MM-DD. Si hay catalogo de servicios, pregunta "
                "primero el servicio y pasalo aqui."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fecha": {"type": "string", "description": "Fecha en formato YYYY-MM-DD"},
                    "servicio": {"type": "string", "description": "Servicio solicitado por el cliente"},
                },
                "required": ["fecha", "servicio"] if service_required else ["fecha"],
            },
        },
        {
            "type": "function",
            "name": "crear_cita",
            "description": (
                "Crea y confirma una cita. Llamala solo despues de haber confirmado con el cliente nombre, "
                "telefono, servicio, fecha (YYYY-MM-DD) y hora (HH:MM en 24h), y tras comprobar disponibilidad. "
                "El servicio debe ser el que el cliente ha elegido, no una etiqueta generica. Devuelve un numero "
                "de reserva (formato R-XXXXXX): comunicaselo al cliente y pidele que lo guarde."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string"},
                    "telefono": {"type": "string"},
                    "servicio": {"type": "string", "description": "Servicio exacto elegido por el cliente"},
                    "fecha": {"type": "string", "description": "YYYY-MM-DD"},
                    "hora": {"type": "string", "description": "HH:MM en 24h"},
                    "email": {"type": "string", "description": "Email (opcional)"},
                },
                "required": ["nombre", "telefono", "servicio", "fecha", "hora"]
                if service_required else ["nombre", "telefono", "fecha", "hora"],
            },
        },
        {
            "type": "function",
            "name": "consultar_cita",
            "description": (
                "Busca una cita por su numero de reserva (formato R-XXXX) y devuelve sus datos: "
                "servicio, fecha, hora, profesional y estado. USALA SIEMPRE LA PRIMERA cuando el "
                "cliente quiera cancelar o cambiar una cita: sirve para confirmar que la reserva EXISTE "
                "y es suya ANTES de pedir cualquier otro dato. Si el telefono de la llamada no coincide "
                "con el de la reserva, pide el telefono o el email con el que reservo y pasalo en "
                "'telefono' o 'email'. No continues con el cambio o la cancelacion hasta que devuelva ok."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo_reserva": {"type": "string", "description": "Numero de reserva, formato R-XXXX"},
                    "telefono": {"type": "string", "description": "Telefono de la reserva, si el cliente lo facilita (opcional)"},
                    "email": {"type": "string", "description": "Email de la reserva, si el cliente lo facilita (opcional)"},
                },
                "required": ["codigo_reserva"],
            },
        },
        {
            "type": "function",
            "name": "cancelar_cita",
            "description": (
                "Cancela una cita existente a partir de su numero de reserva (formato R-XXXX). "
                "Por seguridad solo se cancela si el telefono desde el que llama coincide con el de la reserva; "
                "si no coincide, pide al cliente el telefono o el email con el que reservo y pasalo en 'telefono' o 'email'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo_reserva": {"type": "string", "description": "Numero de reserva, formato R-XXXX"},
                    "telefono": {"type": "string", "description": "Telefono de la reserva, si el cliente lo facilita (opcional)"},
                    "email": {"type": "string", "description": "Email de la reserva, si el cliente lo facilita (opcional)"},
                    "motivo": {"type": "string", "description": "Motivo de cancelacion (opcional)"},
                },
                "required": ["codigo_reserva"],
            },
        },
        {
            "type": "function",
            "name": "reprogramar_cita",
            "description": (
                "Reprograma una cita existente a una nueva fecha y hora, a partir de su numero de reserva (R-XXXX). "
                "Comprueba disponibilidad con consultar_disponibilidad antes de proponer la nueva hora. "
                "Por seguridad solo se reprograma si el telefono desde el que llama coincide con el de la reserva; "
                "si no, pide el telefono o el email con el que reservo y pasalo en 'telefono' o 'email'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo_reserva": {"type": "string", "description": "Numero de reserva, formato R-XXXX"},
                    "fecha": {"type": "string", "description": "Nueva fecha YYYY-MM-DD"},
                    "hora": {"type": "string", "description": "Nueva hora HH:MM en 24h"},
                    "telefono": {"type": "string", "description": "Telefono de la reserva, si el cliente lo facilita (opcional)"},
                    "email": {"type": "string", "description": "Email de la reserva, si el cliente lo facilita (opcional)"},
                },
                "required": ["codigo_reserva", "fecha", "hora"],
            },
        },
        {
            "type": "function",
            "name": "enviar_codigo_verificacion",
            "description": (
                "Envia al cliente un codigo de verificacion de 4 digitos por SMS, WhatsApp o email "
                "(al telefono o email REGISTRADO en la cita) para confirmar su identidad ANTES de "
                "cancelar o reprogramar. Usala despues de consultar_cita. Luego pide al cliente que te "
                "lea el codigo y validalo con verificar_codigo. NUNCA leas tu el codigo en voz alta; "
                "solo di por que medio se lo has enviado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo_reserva": {"type": "string", "description": "Numero de reserva (R y 6 digitos)"},
                },
                "required": ["codigo_reserva"],
            },
        },
        {
            "type": "function",
            "name": "verificar_codigo",
            "description": (
                "Comprueba el codigo de 4 digitos que el cliente lee tras enviar_codigo_verificacion. "
                "Si devuelve ok, ya puedes cancelar o reprogramar esa cita."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "codigo_reserva": {"type": "string", "description": "Numero de reserva (R y 6 digitos)"},
                    "codigo": {"type": "string", "description": "Codigo de 4 digitos leido por el cliente"},
                },
                "required": ["codigo_reserva", "codigo"],
            },
        },
    ]
    if booking._ai_payment_sending_available(cliente_id):
        tools.append(
            {
                "type": "function",
                "name": "enviar_enlace_pago",
                "description": (
                    "Envia por SMS al telefono de la llamada un enlace seguro para que el cliente pague su cita. "
                    "Usala SOLO si el cliente quiere pagar o dejar una senal y tras confirmarle en voz alta el importe. "
                    "El importe lo fija el negocio segun el servicio: NUNCA lo decide el cliente. Pasa el numero de "
                    "reserva (R-XXXX) si lo tienes; si no, se usa la ultima cita de este telefono. No leas la URL en "
                    "voz alta: solo confirma que le llega el enlace por SMS."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "codigo_reserva": {"type": "string", "description": "Numero de reserva, formato R-XXXX (opcional)"},
                    },
                    "required": [],
                },
            }
        )
    if include_confirm:
        tools.append(
            {
                "type": "function",
                "name": "confirmar_cita",
                "description": (
                    "Marca como CONFIRMADA la cita por la que llamas cuando el cliente confirma su asistencia. "
                    "No necesita parametros."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            }
        )
    # Multi-centro: el cliente debe decir EN QUE centro quiere la cita. Anadimos el
    # parametro `centro` (obligatorio) a consultar_disponibilidad y crear_cita para que
    # la disponibilidad y la reserva se acoten a ese centro. Solo si hay >1 centro.
    try:
        multi_location = len(agenda._list_location_rows(cliente_id, include_inactive=False)) > 1
    except Exception:  # noqa: BLE001
        multi_location = False
    if multi_location:
        centro_prop = {
            "type": "string",
            "description": (
                "Centro o sede del negocio donde quiere la cita (uno de los centros listados en el "
                "prompt). Preguntalo antes si el cliente no lo ha dicho."
            ),
        }
        for tool in tools:
            if tool.get("name") in ("consultar_disponibilidad", "crear_cita"):
                tool["parameters"]["properties"]["centro"] = centro_prop
                required = tool["parameters"].get("required") or []
                if "centro" not in required:
                    tool["parameters"]["required"] = required + ["centro"]
    return tools


async def _voice_check_availability(
    cliente_id: str, fecha: str, servicio: str = "", location_id: str = ""
) -> Dict[str, Any]:
    config = appstate.CONFIG_CLIENTES.get(cliente_id)
    if not config or not _voice_booking_enabled(cliente_id, config):
        return {"ok": False, "error": "La reserva online no esta habilitada."}
    try:
        day = textnorm._parse_date(fecha)
        agenda._validate_booking_window(cliente_id, day)
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}
    try:
        _all_slots, available = await agenda._public_slot_sets_for_day(
            cliente_id,
            fecha,
            servicio=textnorm._sanitize_text(servicio or ""),
            location_id=location_id,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] disponibilidad fallo (%s): %s", cliente_id, exc)
        return {"ok": False, "error": "No se pudo consultar la disponibilidad."}
    slots = sorted(available)
    visible_slots = slots[:3]
    if visible_slots:
        # Enumera 2-3 horas "desnudas" y di el tramo (manana/tarde) una sola vez al final.
        spoken = _voice_join_es([_voice_say_time(s, with_period=False) for s in visible_slots])
        try:
            last_visible_h = int(visible_slots[-1].split(":")[0])
            spoken = f"{spoken} {_voice_time_period_es(last_visible_h)}"
        except (ValueError, IndexError):
            last_visible_h = 0
        later = slots[len(visible_slots):]
        if later:
            # Deja claro que hay MAS horas (no solo estas 3). Si las siguientes caen por la
            # tarde y estas eran de manana, nombra la tarde; si no, hint generico.
            try:
                has_afternoon_later = any(int(s.split(":")[0]) >= 14 for s in later)
            except (ValueError, IndexError):
                has_afternoon_later = False
            extra = (
                "y tambien me quedan horas por la tarde"
                if (has_afternoon_later and last_visible_h < 14)
                else "y tengo mas horas libres ese dia"
            )
            voice_message = f"Vale, para empezar tengo {spoken}, {extra}. ¿Que franja te viene mejor, o te digo mas?"
        else:
            voice_message = f"Vale, tengo {spoken}. ¿Cual te encaja?"
    else:
        voice_message = "No veo huecos libres ese dia, puedo mirarte otro."
    return {
        "ok": True,
        "fecha": fecha,
        "huecos": slots[:20],
        "hay_huecos": bool(slots),
        "mensaje_voz": voice_message,
    }


async def _voice_perform_booking(
    cliente_id: str,
    *,
    nombre: str,
    telefono: str,
    fecha: str,
    hora: str,
    servicio: str = "",
    email: str = "",
    location_id: str = "",
) -> Dict[str, Any]:
    """Crea una cita real reutilizando el motor de booking del widget. source='voice'."""
    config = appstate.CONFIG_CLIENTES.get(cliente_id)
    if not config or not _voice_booking_enabled(cliente_id, config):
        return {"ok": False, "error": "La reserva online no esta habilitada."}

    nombre = textnorm._sanitize_text(nombre)
    telefono = textnorm._sanitize_text(telefono)
    servicio = textnorm._sanitize_text(servicio or "")
    email = textnorm._sanitize_text(email or "")
    if not nombre or not telefono:
        return {"ok": False, "error": "Faltan el nombre o el telefono del cliente."}
    telefono_normalizado = _voice_normalize_booking_phone(telefono)
    if not telefono_normalizado:
        msg = "No he cogido bien el telefono. Repitemelo con los nueve digitos, por favor."
        return {
            "ok": False,
            "needs_phone": True,
            "missing_field": "telefono",
            "error": msg,
            "mensaje_voz": msg,
        }
    telefono = telefono_normalizado
    service_options = _voice_service_options(cliente_id, location_id)
    service_row = None
    if service_options:
        if not servicio:
            return _voice_service_required_response(cliente_id, location_id)
        service_row = agenda._find_service_by_name(cliente_id, servicio)
        if service_row is None:
            return _voice_service_required_response(cliente_id, location_id, invalid=servicio)
        servicio = service_row["name"] or servicio

    try:
        booking_date_dt = textnorm._parse_date(fecha)
        agenda._validate_booking_window(cliente_id, booking_date_dt)
        booking_date = booking_date_dt.strftime("%Y-%m-%d")
        booking_time = textnorm._parse_time(hora).strftime("%H:%M")
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}

    try:
        employee_row = await agenda._resolve_public_booking_employee(
            cliente_id, booking_date, booking_time, servicio=servicio, location_id=location_id
        )
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}

    service_duration = agenda._service_duration_minutes(cliente_id, servicio, employee_row)
    service_id = service_row["slug"] if service_row else ""
    service_price = agenda._service_price_cents_resolved(
        cliente_id, service_row, employee_row["location_id"] or ""
    )

    if not await agenda._booking_slot_available(
        cliente_id,
        booking_date,
        booking_time,
        employee_id=employee_row["id"],
        duration_minutes=service_duration,
    ):
        # Devolvemos alternativas reales del mismo dia para que el asistente las ofrezca
        # tal cual (sin inventarse horas) en vez de un "ofrece otra hora" a ciegas.
        alt = await _voice_check_availability(cliente_id, booking_date, servicio=servicio, location_id=location_id)
        huecos = alt.get("huecos") or []
        if huecos:
            visibles = huecos[:3]
            spoken = _voice_join_es([_voice_say_time(s, with_period=False) for s in visibles])
            try:
                spoken = f"{spoken} {_voice_time_period_es(int(visibles[-1].split(':')[0]))}"
            except (ValueError, IndexError):
                pass
            msg = f"Vaya, esa hora se acaba de ocupar. Para ese dia me quedan {spoken}. ¿Cual te encaja?"
        else:
            msg = "Vaya, esa hora ya no esta disponible y no me quedan huecos ese dia. ¿Probamos otro dia?"
        return {"ok": False, "no_disponible": True, "huecos": huecos[:20], "error": msg, "mensaje_voz": msg}

    booking_id = f"bk_{secrets.token_urlsafe(10)}"
    manage_token = booking._generate_manage_token()
    created_at = timeutils._utc_now_iso()
    booking_timezone = employee_row["timezone"] or config["booking"]["timezone"]
    try:
        start_local, end_local = agenda._booking_start_end(
            cliente_id,
            booking_date,
            booking_time,
            employee_id=employee_row["id"],
            duration_minutes=service_duration,
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] booking start/end fallo (%s): %s", cliente_id, exc)
        return {"ok": False, "error": "No se pudo calcular el horario de la cita."}

    booking_payload = {
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
        "notas": "Cita creada por el asistente de voz.",
        "source": "voice",
        "created_at": created_at,
    }
    try:
        provider_result = await booking._create_provider_booking(cliente_id, booking_payload)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] provider booking fallo (%s): %s", cliente_id, exc)
        return {"ok": False, "error": "No se pudo registrar la cita."}

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
        "notas": "Cita creada por el asistente de voz.",
        "status": "confirmed",
        "provider_name": provider_result.provider_name,
        "provider_status": provider_result.status,
        "provider_booking_id": provider_result.provider_booking_id,
        "provider_booking_url": provider_result.provider_booking_url,
        "manage_token": manage_token,
        "timezone": booking_timezone,
        "start_at": timeutils._to_utc_iso(start_local),
        "end_at": timeutils._to_utc_iso(end_local),
        "confirmed_at": created_at,
        "cancelled_at": "",
        **booking._booking_blank_tracking_fields(),
        "service_id": service_id,
        "service_price_cents": service_price,
        "source": "voice",
        "created_at": created_at,
    }
    try:
        booking._store_booking(record)
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "Ese horario acaba de ocuparse. Ofrece otra hora."}
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] store booking fallo (%s): %s", cliente_id, exc)
        return {"ok": False, "error": "No se pudo guardar la cita."}

    booking._record_booking_audit(
        booking_id,
        cliente_id,
        "booking_created",
        {"status": "confirmed", "source": "voice", "employee_id": employee_row["id"]},
    )
    stored_booking = booking._get_booking_row_by_id(booking_id)
    payment_row = booking._booking_payment_row(booking_id)
    booking_status = stored_booking["status"] if stored_booking else record.get("status", "confirmed")
    booking_code = record.get("booking_code", "")
    service_label = servicio or "cita"
    fecha_voz = _voice_say_date(booking_date, booking_timezone)
    hora_voz = _voice_say_time(booking_time)
    if booking_status == "pending_payment":
        voice_message = (
            f"Perfecto, la cita queda reservada para {fecha_voz} a {hora_voz}, pendiente de pago. "
            f"Codigo {booking_code}."
        )
    else:
        voice_message = (
            f"Perfecto, la cita queda confirmada para {fecha_voz} a {hora_voz}. Codigo {booking_code}."
        )

    # Confirmacion transaccional (email/SMS/WhatsApp) con nº de reserva + enlace de gestion,
    # igual que una reserva web. La enviamos EN SEGUNDO PLANO para no anadir latencia a la voz
    # (el asistente confirma de viva voz al instante; el envio SMTP/SMS puede tardar segundos).
    # El canal anunciado se calcula con una comprobacion rapida de config (sin red), respetando
    # la prioridad de entrega. Best-effort: la cita ya esta creada aunque el envio falle.
    confirmacion_canal = ""
    if booking_status != "pending_payment" and stored_booking is not None:
        try:
            fu = booking._follow_up_config(cliente_id)
            enabled = agenda._effective_followup_channels(cliente_id).get("confirmed", {}) or {}
            avail = agenda._reminder_channel_availability(cliente_id)
            for ch in (fu.get("delivery_priority") or ["email", "whatsapp", "sms"]):
                if enabled.get(ch) and (ch == "email" or avail.get(ch, {}).get("available")):
                    confirmacion_canal = ch
                    break
        except Exception:  # noqa: BLE001
            confirmacion_canal = ""
        try:
            _task = asyncio.create_task(
                booking._send_booking_reminder_by_kind(
                    stored_booking, "confirmed", None,
                    sent_column="confirmation_email_sent_at", raise_on_failure=False,
                )
            )
            _VOICE_BG_TASKS.add(_task)
            _task.add_done_callback(_VOICE_BG_TASKS.discard)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("[voice] confirmacion no programada (%s): %s", cliente_id, exc)
    if confirmacion_canal == "email":
        voice_message += " Te envio la confirmacion por correo."
    elif confirmacion_canal in ("sms", "whatsapp"):
        voice_message += " Te envio la confirmacion por mensaje."

    return {
        "ok": True,
        "booking_id": booking_id,
        "codigo_reserva": booking_code,
        "fecha": booking_date,
        "hora": booking_time,
        "servicio": service_label,
        "empleado": employee_row["name"],
        "manage_url": booking._build_booking_manage_url(manage_token),
        "estado": booking_status,
        "mensaje_voz": voice_message,
        "confirmacion_canal": confirmacion_canal,
        "payment_status": stored_booking["payment_status"] if stored_booking else "not_required",
        "payment_url": payment_row["checkout_url"] if payment_row else "",
        "mensaje_pago": (
            "Envia este enlace seguro por SMS, WhatsApp o email; nunca pidas datos bancarios por telefono."
            if payment_row and payment_row["checkout_url"] else ""
        ),
    }


async def _voice_lookup_and_verify_booking(
    cliente_id: str,
    codigo_reserva: str,
    *,
    from_number: str = "",
    telefono: str = "",
    email: str = "",
) -> Tuple[Optional[sqlite3.Row], Optional[Dict[str, Any]]]:
    """Busca una cita por codigo y verifica titularidad (telefono que llama o aportado / email).

    Devuelve (row, None) si todo ok, o (None, error_dict) para responder a la IA.
    """
    codigo = textnorm._sanitize_text(codigo_reserva)
    if not codigo:
        return None, {"ok": False, "error": "Pide al cliente su numero de reserva (formato R-XXXX)."}
    row = booking._get_booking_row_by_code(cliente_id, codigo)
    if not row:
        return None, {"ok": False, "error": "No encuentro ninguna cita con ese numero de reserva. Pide que lo repita."}
    verified = (
        booking._booking_contact_matches(row, telefono=from_number)
        or booking._booking_contact_matches(row, telefono=telefono, email=email)
    )
    if not verified:
        return None, {
            "ok": False,
            "needs_verification": True,
            "error": (
                "Por seguridad no puedo continuar sin verificar la identidad. "
                "Pide al cliente el telefono o el email con el que hizo la reserva."
            ),
        }
    return row, None


_VOICE_STATUS_ES = {
    "confirmed": "confirmada",
    "pending_review": "pendiente de confirmar",
    "cancelled": "cancelada",
    "completed": "ya realizada",
    "no_show": "marcada como no presentada",
}


async def _voice_lookup_booking(
    cliente_id: str,
    codigo_reserva: str,
    *,
    from_number: str = "",
    telefono: str = "",
    email: str = "",
) -> Dict[str, Any]:
    """Tool de voz: localiza una cita por numero de reserva y devuelve su resumen para que el
    asistente confirme DE QUE cita se trata. El numero de reserva actua de clave de busqueda;
    la titularidad para CAMBIAR/CANCELAR se exige aparte (telefono de la llamada o codigo OTP)."""
    row = booking._get_booking_row_by_code(cliente_id, codigo_reserva)
    if not row:
        return {"ok": False, "error": "No encuentro ninguna cita con ese numero de reserva. Pide que lo repita."}
    return {
        "ok": True,
        "codigo_reserva": row["booking_code"] or "",
        "servicio": row["servicio"] or "",
        "fecha": row["booking_date"] or "",
        "hora": row["booking_time"] or "",
        "profesional": row["employee_name"] or "",
        "estado": _VOICE_STATUS_ES.get(row["status"], row["status"] or ""),
        "mensaje_voz": (
            f"Vale, tengo una cita de {row['servicio'] or 'consulta'} "
            f"{_voice_say_date(row['booking_date'], row['timezone'] or settings.DEFAULT_TIMEZONE)} "
            f"a {_voice_say_time(row['booking_time'])}. ¿Es esa?"
        ),
    }


# ── Verificacion por codigo OTP (SMS / WhatsApp / email del contacto de la cita) ──
VOICE_OTP_TTL_SECONDS = 300       # el codigo caduca a los 5 minutos
VOICE_OTP_MAX_ATTEMPTS = 3        # intentos de lectura antes de invalidar


def _voice_otp_key(cliente_id: str, booking_id: str) -> str:
    return f"{cliente_id}:{booking_id}"


def _voice_mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return ("***" + digits[-3:]) if len(digits) >= 3 else "***"


def _voice_mask_email(email: str) -> str:
    email = (email or "").strip()
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    return f"{(local[:1] or '*')}***@{domain}"


def _voice_pick_otp_channel(cliente_id: str, booking_row: sqlite3.Row) -> Tuple[str, str, str]:
    """Mejor canal para enviar el OTP al contacto REGISTRADO de la cita, segun plan y config
    del cliente (reusa _reminder_channel_availability): SMS > WhatsApp > email. Devuelve
    (canal, destino, enmascarado) o ('', '', '') si no hay contacto/canal."""
    avail = agenda._reminder_channel_availability(cliente_id)
    allowed = booking._follow_up_config(cliente_id).get("voice_otp_channels", {}) or {}
    phone = (booking_row["telefono"] or "").strip()
    sms_phone = messaging._normalize_sms_recipient(phone)
    whatsapp_phone = booking._booking_customer_phone_for_channel(booking_row, "whatsapp")
    email = (booking_row["email"] or "").strip()
    if sms_phone and allowed.get("sms") and avail.get("sms", {}).get("available"):
        return "sms", sms_phone, _voice_mask_phone(sms_phone)
    if whatsapp_phone and allowed.get("whatsapp") and avail.get("whatsapp", {}).get("available"):
        return "whatsapp", whatsapp_phone, _voice_mask_phone(whatsapp_phone)
    if email and allowed.get("email"):
        return "email", email, _voice_mask_email(email)
    return "", "", ""


async def _voice_send_verification_code(
    cliente_id: str, codigo_reserva: str, *, from_number: str = "",
) -> Dict[str, Any]:
    """Tool de voz: envia un codigo OTP de 4 digitos al contacto registrado de la cita para
    verificar identidad antes de cancelar/reprogramar. Reusa los canales del cliente
    (_send_client_email / _send_client_sms / _send_whatsapp_text) con su remitente configurado,
    o el de Vantelia como soporte. No expone el codigo al asistente para leerlo en voz alta."""
    row = booking._get_booking_row_by_code(cliente_id, codigo_reserva)
    if not row:
        return {"ok": False, "error": "No encuentro ninguna cita con ese numero de reserva."}
    if row["status"] in ("cancelled", "completed", "no_show"):
        return {"ok": False, "error": "Esa cita no se puede modificar."}
    allowed = booking._follow_up_config(cliente_id).get("voice_otp_channels", {}) or {}
    if not any(allowed.values()):
        return {"ok": False, "disabled": True,
                "error": "La verificación por código está desactivada para este negocio."}
    try:
        security._check_rate_limit(f"voice_otp:{cliente_id}:{row['id']}", 3)
    except HTTPException:
        return {"ok": False, "error": "Se han enviado demasiados codigos. Espera un momento."}
    channel, dest, masked = _voice_pick_otp_channel(cliente_id, row)
    if not channel:
        return {
            "ok": False, "no_contact": True,
            "error": "La cita no tiene telefono ni email registrado, no puedo enviar el codigo.",
        }
    code = f"{secrets.randbelow(10000):04d}"
    empresa = (clients._get_client_config(cliente_id) or {}).get("nombre", "")
    body = (
        f"Tu codigo de verificacion{(' de ' + empresa) if empresa else ''} es {code}. "
        "Lo necesitas para confirmar el cambio o la cancelacion de tu cita. Caduca en 5 minutos."
    )
    sent = False
    try:
        if channel == "email":
            emailing._send_client_email(
                cliente_id, dest,
                f"Codigo de verificacion{(' - ' + empresa) if empresa else ''}", body, "",
            )
            sent = True
        elif channel == "sms":
            sent = await messaging._send_client_sms(cliente_id, dest, body)
        elif channel == "whatsapp":
            whatsapp_cfg = (clients._get_client_config(cliente_id).get("whatsapp", {}) or {})
            pnid = str(whatsapp_cfg.get("phone_number_id", "") or "").strip()
            wa_to = booking._booking_customer_phone_for_channel(row, "whatsapp")
            if pnid and wa_to:
                sent = await messaging._send_whatsapp_text(
                    cliente_id=cliente_id, phone_number_id=pnid, to_number=wa_to, text=body,
                )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] envio de OTP fallo (%s): %s", cliente_id, exc)
        sent = False
    if not sent:
        return {"ok": False, "error": "No se pudo enviar el codigo. Prueba a verificar por otro medio."}
    with appstate.state_lock:
        appstate.voice_otp[_voice_otp_key(cliente_id, row["id"])] = {
            "code": code, "expires_at": time.time() + VOICE_OTP_TTL_SECONDS,
            "attempts": 0, "verified": False, "channel": channel,
        }
    booking._record_booking_audit(row["id"], cliente_id, "voice_otp_sent", {"channel": channel})
    channel_label = {"sms": "SMS", "whatsapp": "WhatsApp", "email": "email"}.get(channel, channel)
    return {
        "ok": True,
        "canal": channel,
        "destino": masked,
        "mensaje_voz": (
            f"Te he enviado el codigo por {channel_label} a {masked}; dimelo cuando lo tengas."
        ),
    }


def _voice_verify_code(cliente_id: str, codigo_reserva: str, codigo: str) -> Dict[str, Any]:
    """Tool de voz: valida el OTP que el cliente lee en voz alta. Un solo uso, con TTL y
    maximo de intentos. Si es correcto marca la cita como verificada para esta sesion."""
    row = booking._get_booking_row_by_code(cliente_id, codigo_reserva)
    if not row:
        return {"ok": False, "error": "No encuentro esa reserva."}
    key = _voice_otp_key(cliente_id, row["id"])
    digits = re.sub(r"\D", "", codigo or "")
    with appstate.state_lock:
        entry = appstate.voice_otp.get(key)
        if not entry:
            return {"ok": False, "error": "No hay ningun codigo pendiente. Envia uno nuevo."}
        if time.time() > entry["expires_at"]:
            appstate.voice_otp.pop(key, None)
            return {"ok": False, "expired": True, "error": "El codigo ha caducado. Envia uno nuevo."}
        if entry["attempts"] >= VOICE_OTP_MAX_ATTEMPTS:
            appstate.voice_otp.pop(key, None)
            return {"ok": False, "too_many": True, "error": "Demasiados intentos. Envia un codigo nuevo."}
        entry["attempts"] += 1
        if not secrets.compare_digest(digits, str(entry["code"])):
            return {"ok": False, "error": "El codigo no coincide. Pide que lo repita."}
        entry["verified"] = True
    booking._record_booking_audit(row["id"], cliente_id, "voice_otp_verified", {})
    return {
        "ok": True,
        "mensaje_voz": "Perfecto, codigo verificado.",
    }


def _voice_booking_otp_verified(cliente_id: str, booking_id: str) -> bool:
    with appstate.state_lock:
        entry = appstate.voice_otp.get(_voice_otp_key(cliente_id, booking_id))
        if not entry or not entry.get("verified"):
            return False
        if time.time() > entry["expires_at"]:
            appstate.voice_otp.pop(_voice_otp_key(cliente_id, booking_id), None)
            return False
        return True


async def _voice_lookup_for_mutation(
    cliente_id: str, codigo_reserva: str, *, from_number: str = "", telefono: str = "", email: str = "",
) -> Tuple[Optional[sqlite3.Row], Optional[Dict[str, Any]]]:
    """Como _voice_lookup_and_verify_booking pero acepta TAMBIEN un OTP verificado como prueba
    de titularidad (ademas del telefono de la llamada o el telefono/email aportado). Asi un
    cliente que llama desde otro numero puede verificarse con el codigo que recibe."""
    row, error = await _voice_lookup_and_verify_booking(
        cliente_id, codigo_reserva, from_number=from_number, telefono=telefono, email=email,
    )
    if not error:
        return row, None
    candidate = booking._get_booking_row_by_code(cliente_id, codigo_reserva)
    if candidate and _voice_booking_otp_verified(cliente_id, candidate["id"]):
        return candidate, None
    return None, error


async def _voice_cancel_booking(
    cliente_id: str,
    codigo_reserva: str,
    *,
    from_number: str = "",
    telefono: str = "",
    email: str = "",
    motivo: str = "",
) -> Dict[str, Any]:
    row, error = await _voice_lookup_for_mutation(
        cliente_id, codigo_reserva, from_number=from_number, telefono=telefono, email=email
    )
    if error:
        return error
    if row["status"] == "cancelled":
        return {
            "ok": True,
            "ya_cancelada": True,
            "mensaje": "Esa cita ya estaba cancelada.",
            "mensaje_voz": "Esa cita ya estaba cancelada.",
        }
    if row["status"] == "completed":
        return {"ok": False, "error": "Esa cita ya se ha realizado y no se puede cancelar."}
    verified_by_code = _voice_booking_otp_verified(cliente_id, row["id"])
    try:
        await booking._cancel_booking_core(
            row, source="voice", reason=textnorm._sanitize_text(motivo, allow_multiline=True),
            audit_extra={"channel": "voice", "from_number": from_number},
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] cancelacion fallo (%s): %s", cliente_id, exc)
        return {"ok": False, "error": "No se pudo cancelar la cita."}
    return {
        "ok": True,
        "codigo_reserva": row["booking_code"] or "",
        "fecha": row["booking_date"],
        "hora": row["booking_time"],
        "mensaje": "Cita cancelada correctamente.",
        "mensaje_voz": (
            "Listo, he verificado el codigo y he cancelado la cita."
            if verified_by_code else "Listo, he cancelado la cita."
        ),
    }


async def _voice_reschedule_booking(
    cliente_id: str,
    codigo_reserva: str,
    fecha: str,
    hora: str,
    *,
    from_number: str = "",
    telefono: str = "",
    email: str = "",
) -> Dict[str, Any]:
    row, error = await _voice_lookup_for_mutation(
        cliente_id, codigo_reserva, from_number=from_number, telefono=telefono, email=email
    )
    if error:
        return error
    verified_by_code = _voice_booking_otp_verified(cliente_id, row["id"])
    payload = booking._booking_update_payload_from_reschedule(
        row, BookingReschedulePayload(fecha=textnorm._sanitize_text(fecha), hora=textnorm._sanitize_text(hora))
    )
    try:
        await booking._update_booking_details(row, payload, None, source="voice")
    except HTTPException as exc:
        return {"ok": False, "error": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] reprogramacion fallo (%s): %s", cliente_id, exc)
        return {"ok": False, "error": "No se pudo reprogramar la cita."}
    tz = row["timezone"] or settings.DEFAULT_TIMEZONE
    fecha_voz = _voice_say_date(textnorm._sanitize_text(fecha), tz)
    hora_voz = _voice_say_time(textnorm._sanitize_text(hora))
    return {
        "ok": True,
        "codigo_reserva": row["booking_code"] or "",
        "fecha": textnorm._sanitize_text(fecha),
        "hora": textnorm._sanitize_text(hora),
        "mensaje": "Cita reprogramada correctamente. El numero de reserva sigue siendo el mismo.",
        "mensaje_voz": (
            f"Listo, he verificado el codigo y he reprogramado la cita para {fecha_voz} a {hora_voz}."
            if verified_by_code
            else f"Listo, he reprogramado la cita para {fecha_voz} a {hora_voz}."
        ),
    }


async def _voice_send_payment_link(
    cliente_id: str, codigo_reserva: str, *, from_number: str = ""
) -> Dict[str, Any]:
    """Tool de voz: envia por SMS el enlace de pago de la cita. Resuelve la cita por
    numero de reserva (verificando que el telefono de la llamada coincide) o, si no
    se da codigo, por el telefono de la llamada."""
    if not booking._ai_payment_sending_available(cliente_id):
        return {"ok": False, "error": "El cobro con tarjeta no esta disponible en este momento."}
    code = textnorm._sanitize_text(codigo_reserva)
    if code:
        booking_row = booking._get_booking_row_by_code(cliente_id, code)
        if not booking_row:
            return {"ok": False, "error": "No encuentro ninguna cita con ese numero de reserva."}
        if from_number and not booking._booking_contact_matches(booking_row, telefono=from_number):
            return {
                "ok": False,
                "needs_verification": True,
                "error": "Por seguridad solo puedo enviar el enlace al telefono con el que se reservo.",
            }
    else:
        booking_row = booking._latest_booking_for_contact(cliente_id, phone=from_number)
        if not booking_row:
            return {
                "ok": False,
                "error": "No encuentro ninguna cita asociada a este telefono. Pide el numero de reserva.",
            }
    result = await booking._ai_send_payment_link(cliente_id, booking_row, base_url=textnorm._preferred_public_base_url())
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "No se pudo enviar el enlace de pago."}
    amount_label = result.get("amount_label", "")
    return {
        "ok": True,
        "importe": amount_label,
        "enviado": bool(result.get("sent")),
        "mensaje": f"Enviado un SMS con el enlace para pagar {amount_label}.",
    }


async def _voice_dispatch_tool(
    cliente_id: str, name: str, arguments_json: str, *, from_number: str = "", location_id: str = ""
) -> Dict[str, Any]:
    try:
        args = json.loads(arguments_json or "{}")
    except Exception:  # noqa: BLE001
        args = {}
    if not isinstance(args, dict):
        args = {}
    # Centro efectivo: si la linea/numero ya esta atada a un centro (location_id), manda esa;
    # si no (numero generico o widget), usamos el centro que el cliente eligio (arg `centro`).
    effective_location = location_id or _voice_resolve_location_id(cliente_id, str(args.get("centro", "")))
    if name == "consultar_disponibilidad":
        return await _voice_check_availability(
            cliente_id, str(args.get("fecha", "")), str(args.get("servicio", "")), effective_location
        )
    if name == "crear_cita":
        return await _voice_perform_booking(
            cliente_id,
            nombre=str(args.get("nombre", "")),
            telefono=str(args.get("telefono", "")),
            fecha=str(args.get("fecha", "")),
            hora=str(args.get("hora", "")),
            servicio=str(args.get("servicio", "")),
            email=str(args.get("email", "")),
            location_id=effective_location,
        )
    if name == "consultar_cita":
        return await _voice_lookup_booking(
            cliente_id,
            str(args.get("codigo_reserva", "")),
            from_number=from_number,
            telefono=str(args.get("telefono", "")),
            email=str(args.get("email", "")),
        )
    if name == "enviar_codigo_verificacion":
        return await _voice_send_verification_code(
            cliente_id, str(args.get("codigo_reserva", "")), from_number=from_number,
        )
    if name == "verificar_codigo":
        return _voice_verify_code(
            cliente_id, str(args.get("codigo_reserva", "")), str(args.get("codigo", "")),
        )
    if name == "cancelar_cita":
        return await _voice_cancel_booking(
            cliente_id,
            str(args.get("codigo_reserva", "")),
            from_number=from_number,
            telefono=str(args.get("telefono", "")),
            email=str(args.get("email", "")),
            motivo=str(args.get("motivo", "")),
        )
    if name == "reprogramar_cita":
        return await _voice_reschedule_booking(
            cliente_id,
            str(args.get("codigo_reserva", "")),
            str(args.get("fecha", "")),
            str(args.get("hora", "")),
            from_number=from_number,
            telefono=str(args.get("telefono", "")),
            email=str(args.get("email", "")),
        )
    if name == "enviar_enlace_pago":
        return await _voice_send_payment_link(
            cliente_id,
            str(args.get("codigo_reserva", "")),
            from_number=from_number,
        )
    return {"ok": False, "error": "Funcion desconocida."}


def _voice_tool_followup_prompt(tool_name: str, result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    message = textnorm._sanitize_text(str(
        result.get("mensaje_voz") or result.get("mensaje") or result.get("error") or ""
    ))
    if not message:
        return ""
    if result.get("needs_service"):
        return (
            "[sistema] Falta el servicio. Pregunta esto en una sola frase natural, sin anadir pasos: "
            f"\"{message}\""
        )
    if tool_name == "crear_cita" and result.get("ok"):
        return (
            "[sistema] Di esta confirmacion en una sola frase natural. No anadas pasos ni explicaciones: "
            f"\"{message}\""
        )
    if tool_name == "verificar_codigo" and result.get("ok"):
        return (
            "[sistema] El codigo ya esta verificado. Si el cliente ya habia pedido cancelar o reprogramar, "
            "llama ahora a la herramienta correspondiente sin hablar todavia. Si no hay accion pendiente, "
            f"di una sola frase natural: \"{message}\""
        )
    if tool_name in {
        "consultar_disponibilidad", "consultar_cita", "enviar_codigo_verificacion",
        "cancelar_cita", "reprogramar_cita", "enviar_enlace_pago",
    } and result.get("ok"):
        return (
            "[sistema] Di esta idea en una sola frase natural, sin anadir pasos ni explicaciones: "
            f"\"{message}\""
        )
    if not result.get("ok"):
        return (
            "[sistema] Di este problema de forma breve y, si procede, pregunta el siguiente dato minimo: "
            f"\"{message}\""
        )
    if message:
        return f"[sistema] Responde ahora en voz alta con este resultado: \"{message}\""
    return ""


async def _voice_dispatch_tool_demo(cliente_id: str, name: str, arguments_json: str) -> Dict[str, Any]:
    """Ejecucion de tools para la voz EN NAVEGADOR de la demo publica. Solo lectura real:
    consultar_disponibilidad se ejecuta de verdad (util para mostrar huecos), pero las tools
    de escritura NO tocan la agenda real (cualquiera puede abrir la demo). Devuelven un
    resultado honesto que el asistente puede leer en voz alta."""
    if name == "consultar_disponibilidad":
        try:
            args = json.loads(arguments_json or "{}")
        except Exception:  # noqa: BLE001
            args = {}
        if not isinstance(args, dict):
            args = {}
        return await _voice_check_availability(
            cliente_id, str(args.get("fecha", "")), str(args.get("servicio", ""))
        )
    if name in {
        "crear_cita", "cancelar_cita", "reprogramar_cita", "consultar_cita",
        "enviar_codigo_verificacion", "verificar_codigo",
    }:
        return {
            "ok": False,
            "demo": True,
            "error": "Esto es una demostracion: la cita no se guarda. En la version real "
            "quedaria agendada al instante y el cliente recibiria la confirmacion.",
        }
    return {"ok": False, "error": "Funcion desconocida."}


def _voice_detect_booking_intent(transcript_text: str) -> bool:
    low = (transcript_text or "").lower()
    return any(keyword in low for keyword in VOICE_BOOKING_KEYWORDS)


def _voice_summarize(transcript_text: str) -> str:
    if not settings.OPENAI_API_KEY or not transcript_text.strip():
        return ""
    try:
        from openai import OpenAI as OpenAISdkClient  # local import, evita choque de nombres

        client = OpenAISdkClient(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.DEFAULT_CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Resume en 2 frases, en espanol, esta llamada telefonica entre un "
                        "asistente virtual y un cliente. Indica el motivo y si pidio cita."
                    ),
                },
                {"role": "user", "content": transcript_text[:6000]},
            ],
            temperature=0.3,
            max_tokens=160,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[voice] resumen fallo: %s", exc)
        return ""


async def _open_realtime_ws(model: str = ""):
    """Abre la conexion WebSocket cliente contra OpenAI Realtime API (GA).

    GA (mayo 2026): sin header OpenAI-Beta; modelos gpt-realtime / gpt-realtime-mini.
    """
    import websockets  # import diferido: solo necesario en llamadas reales

    url = f"wss://api.openai.com/v1/realtime?model={model or settings.VOICE_REALTIME_MODEL}"
    headers = [("Authorization", f"Bearer {settings.OPENAI_API_KEY}")]
    try:  # websockets >=13 usa additional_headers; <=12 usa extra_headers
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, max_size=None)


async def _voice_safe_close(ws) -> None:
    try:
        await ws.close()
    except Exception:  # noqa: BLE001
        pass


def _voice_pcmu_duration_ms(audio_b64: str) -> int:
    """Duracion aproximada de audio PCMU: 8 kHz, un byte por muestra."""
    try:
        return max(0, len(base64.b64decode(audio_b64 or "", validate=True)) // 8)
    except Exception:  # noqa: BLE001
        return 0


def _list_voice_calls(cliente_id: str = "", *, limit: int = 160) -> List[sqlite3.Row]:
    """Llamadas de voz para el historial unificado de conversaciones."""
    clauses: List[str] = []
    params: List[Any] = []
    if cliente_id:
        clauses.append("cliente_id = ?")
        params.append(cliente_id)
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, min(limit, 300)))
    with db._get_db_connection() as connection:
        return connection.execute(
            f"SELECT * FROM voice_calls {where_sql} ORDER BY started_at DESC LIMIT ?", params
        ).fetchall()


def _voice_call_transcript(row: sqlite3.Row) -> List[Dict[str, Any]]:
    try:
        return json.loads(row["transcript_json"] or "[]") or []
    except (ValueError, TypeError):
        return []


def _voice_conversation_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Resumen de conversacion unificado para una llamada de voz."""
    transcript = _voice_call_transcript(row)
    purpose = (row["purpose"] or "").strip() if "purpose" in row.keys() else ""
    is_app_test = purpose == "app_test"
    preview = ""
    for item in reversed(transcript):
        text = (item.get("text") or "").strip()
        if text:
            preview = text
            break
    return {
        "id": str(row["id"]),
        "kind": "voice",
        "channel": "voice",
        "contact": "Prueba del panel" if is_app_test else ((row["from_number"] or "").strip() or "Llamada"),
        "started_at": row["started_at"] or "",
        "last_at": row["ended_at"] or row["started_at"] or "",
        "preview": preview,
        "message_count": len(transcript),
        "duration_seconds": int(row["duration_seconds"] or 0),
        "booking_created": bool(row["booking_created"]),
        "intents": ["prueba"] if is_app_test else [],
    }


def _voice_call_detail_dict(conv_id: str, *, cliente_id: str = "") -> Dict[str, Any]:
    """Detalle (transcripcion + resumen) de una llamada para el panel de conversaciones."""
    try:
        numeric_id = int(str(conv_id).strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Llamada no encontrada.")
    clauses = ["id = ?"]
    params: List[Any] = [numeric_id]
    if cliente_id:
        clauses.append("cliente_id = ?")
        params.append(cliente_id)
    with db._get_db_connection() as connection:
        row = connection.execute(
            f"SELECT * FROM voice_calls WHERE {' AND '.join(clauses)} LIMIT 1", params
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Llamada no encontrada.")
    messages = [
        {
            "role": (item.get("role") or "user"),
            "content": (item.get("text") or ""),
            "created_at": (item.get("ts") or ""),
        }
        for item in _voice_call_transcript(row)
    ]
    return {
        "conversation": _voice_conversation_dict(row),
        "messages": messages,
        "summary_text": row["summary"] or "",
    }


def _voice_interruption_audio_end_ms(state: Dict[str, Any]) -> int:
    started_at = state.get("assistant_audio_started_at")
    if started_at is None:
        return 0
    elapsed = max(0, int(state.get("latest_media_timestamp", 0)) - int(started_at))
    generated = max(0, int(state.get("assistant_audio_generated_ms", 0)))
    return min(elapsed, generated) if generated else elapsed


def _voice_reset_assistant_playback(state: Dict[str, Any]) -> None:
    state["assistant_item_id"] = ""
    state["assistant_audio_started_at"] = None
    state["assistant_audio_generated_ms"] = 0


async def _voice_truncate_interrupted_response(openai_ws, twilio_ws, state: Dict[str, Any]) -> bool:
    """Detiene el audio pendiente y conserva solo la parte que el llamante ya oyo."""
    item_id = state.get("assistant_item_id", "")
    stream_sid = state.get("stream_sid", "")
    if not item_id or not stream_sid:
        return False

    audio_end_ms = _voice_interruption_audio_end_ms(state)
    await twilio_ws.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))
    await openai_ws.send(
        json.dumps(
            {
                "type": "conversation.item.truncate",
                "item_id": item_id,
                "content_index": 0,
                "audio_end_ms": audio_end_ms,
            }
        )
    )
    _voice_reset_assistant_playback(state)
    return True


async def _voice_finalize_call(
    *,
    cliente_id: str,
    config: Dict[str, Any],
    voice_cfg: Dict[str, Any],
    call_sid: str,
    transcript: List[Dict[str, str]],
    duration_seconds: int,
    status_value: str,
    booking_done: bool = False,
) -> None:
    transcript_text = "\n".join(f"{item['role']}: {item['text']}" for item in transcript)
    # booking_created refleja una cita realmente creada por voz; si no, caemos a
    # deteccion de intencion por palabras clave (lead sin reserva confirmada).
    booking_intent = booking_done or _voice_detect_booking_intent(transcript_text)
    summary = await timeutils._to_thread(_voice_summarize, transcript_text)

    from_number = ""
    if call_sid:
        try:
            with db._get_db_connection() as conn:
                row = conn.execute(
                    "SELECT from_number FROM voice_calls WHERE call_sid=?", (call_sid,)
                ).fetchone()
                if row:
                    from_number = row["from_number"] or ""
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("[voice] no se pudo leer from_number de %s: %s", call_sid, exc)

    sms_sent = 0
    if voice_cfg.get("sms_confirmation") and booking_intent and from_number:
        twilio_from = (
            settings.TWILIO_SMS_SENDER
            or voice_cfg.get("twilio_phone_number")
            or settings.TWILIO_DEFAULT_PHONE_NUMBER
        )
        base = (settings.APP_BASE_URL or "https://app.vantelia.es").rstrip("/")
        link = f"{base}/demo/{cliente_id}"
        body = (
            f"Hola, gracias por llamar a {config['nombre']}. "
            f"Para gestionar tu cita entra aqui: {link}"
        )
        if await messaging._send_twilio_sms(from_number, twilio_from, body):
            sms_sent = 1

    now_iso = timeutils._utc_now().isoformat()
    if not call_sid:
        settings.logger.warning("[voice] llamada sin call_sid; no se persiste finalizacion")
        return
    try:
        with db._get_db_connection() as conn:
            conn.execute(
                """
                UPDATE voice_calls
                SET ended_at=?, duration_seconds=?, status=?, transcript_json=?,
                    summary=?, booking_created=?, sms_sent=?
                WHERE call_sid=?
                """,
                (
                    now_iso,
                    int(duration_seconds),
                    status_value,
                    json.dumps(transcript, ensure_ascii=False),
                    summary,
                    1 if booking_intent else 0,
                    sms_sent,
                    call_sid,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] no se pudo finalizar llamada %s: %s", call_sid, exc)


def _voice_stats(conn: sqlite3.Connection, cliente_id: str) -> Dict[str, int]:
    params: List[Any] = []
    cond = ""
    if cliente_id:
        cond = " WHERE cliente_id=?"
        params = [cliente_id]
    connector = " AND" if cond else " WHERE"
    today = timeutils._utc_now().date().isoformat()
    week_ago = (timeutils._utc_now().date() - timedelta(days=7)).isoformat()

    def count(extra: str, extra_params: List[Any]) -> int:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM voice_calls{cond}{extra}", params + extra_params
        ).fetchone()
        return int(row["c"] if row else 0)

    avg_row = conn.execute(
        f"SELECT AVG(duration_seconds) AS a FROM voice_calls{cond}{connector} duration_seconds>0",
        params,
    ).fetchone()
    return {
        "today": count(f"{connector} substr(started_at,1,10)=?", [today]),
        "week": count(f"{connector} substr(started_at,1,10)>=?", [week_ago]),
        "with_booking": count(f"{connector} booking_created=1", []),
        "avg_duration": int((avg_row["a"] if avg_row and avg_row["a"] else 0) or 0),
    }


