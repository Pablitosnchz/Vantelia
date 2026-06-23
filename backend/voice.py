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
from backend import agenda, appstate, booking, chat, clients, crm, db, demo_agenda, messaging, rag, security, settings, textnorm, timeutils

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
# Silencio (ms) que espera tras dejar de oir voz antes de responder. El cliente
# quiere ~0.5-1 s: por defecto 500 ms (respuesta rapida tras interrumpir).
VOICE_VAD_SILENCE_MS_DEFAULT = 500


def _voice_audio_input_config(voice_cfg: Dict[str, Any], *, default_noise: str = "far_field") -> Dict[str, Any]:
    """Bloque `audio.input` compartido por navegador (WebRTC) y telefono (Twilio).

    Centraliza turn detection + transcripcion + reduccion de ruido para que las dos
    rutas tengan exactamente el mismo comportamiento ante ruido e interrupciones.

    - server_vad (por defecto): detecta fin de turno por silencio con un tiempo EXACTO
      (`silence_duration_ms`), asi la respuesta llega rapido tras hablar/interrumpir
      (~0.5 s). `threshold` alto + `noise_reduction` evitan que el ruido abra turnos.
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
            threshold = float(voice_cfg.get("vad_threshold") or 0.6)
        except (TypeError, ValueError):
            threshold = 0.6
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
        "transcription": {"model": "whisper-1"},
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
    fecha = booking_row["booking_date"] if booking_row else ""
    hora = booking_row["booking_time"] if booking_row else ""
    extra = (
        "\n\nLLAMADA SALIENTE DE CONFIRMACION (tu llamas al cliente, no al reves).\n"
        f"- Llamas a {nombre} para confirmar su cita: {servicio} el {fecha} a las {hora}.\n"
        "- Saluda, di de parte de que negocio llamas y pide que confirme la asistencia. Se breve y cordial.\n"
        "- Si confirma, llama a la herramienta confirmar_cita y despidete dando las gracias.\n"
        "- Si quiere cancelar o cambiar la hora, usa cancelar_cita o reprogramar_cita (el telefono ya esta "
        "verificado por ser una llamada a su numero; no pidas codigo de reserva).\n"
        "- Si pide que no le llamen, discref pide disculpas, dile que tomas nota y despidete sin insistir.\n"
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


def _voice_build_instructions(cliente_id: str, config: Dict[str, Any]) -> str:
    base = rag._build_system_prompt(cliente_id, config)

    voice_rules = (
        "\n\nCANAL: LLAMADA TELEFONICA POR VOZ. Eres la recepcionista del negocio, una persona real, no un robot.\n"
        "TONO Y FORMA (habla como una persona):\n"
        "- Habla SIEMPRE en espanol de Espana, con tono calido y cercano, como alguien que coge el telefono en recepcion.\n"
        "- Frases cortas, UNA idea por turno. Nada de parrafos ni listas largas leidas de un tiron.\n"
        "- Usa con naturalidad y moderacion expresiones como 'vale', 'perfecto', 'claro', 'un momento', 'a ver'.\n"
        "- Di numeros, horas y precios en palabras naturales: 'las cinco y media', 'a las diez de la manana', 'cuarenta euros'.\n"
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
            "- Para ver huecos libres usa la herramienta consultar_disponibilidad(fecha). Ofrece solo 2 o 3 "
            "horas concretas, no leas la lista entera.\n"
            "- Antes de reservar confirma en voz alta: nombre, telefono, servicio, dia y hora.\n"
            "- Pide el telefono y repitelo para asegurarte de que lo has cogido bien.\n"
            "- Crea la reserva con la herramienta crear_cita. Si devuelve ok, confirma con naturalidad que la "
            "cita queda hecha y que recibira un SMS con los detalles. Si devuelve error, explica el motivo con "
            "tacto y ofrece otra hora.\n"
            "- crear_cita devuelve un numero de reserva (formato R y cuatro caracteres, por ejemplo R-7F4K). "
            "Diselo al cliente deletreado, letra a letra y digito a digito, y pidele que lo apunte porque le servira "
            "para cambiar o cancelar la cita.\n"
            "- CANCELAR: si piden cancelar, pide su numero de reserva y usa la herramienta cancelar_cita. "
            "REPROGRAMAR: pide el numero de reserva y la nueva fecha/hora (comprueba antes huecos con "
            "consultar_disponibilidad) y usa reprogramar_cita.\n"
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
    else:
        booking_block = (
            "\nAGENDA: la reserva online no esta activa para este negocio. Si piden cita, recoge nombre, "
            "telefono y motivo, y di que el equipo les llamara para confirmar.\n"
        )

    knowledge = _voice_load_knowledge(cliente_id)
    knowledge_block = (
        f"\n\nBASE DE CONOCIMIENTO DEL NEGOCIO (es tu unica fuente para datos concretos como servicios, "
        f"precios, horarios o direccion; si algo no esta aqui, dilo y ofrece que el equipo lo confirme):\n{knowledge}\n"
        if knowledge
        else ""
    )
    return base + voice_rules + booking_block + knowledge_block


def _voice_booking_tools(
    cliente_id: str, config: Dict[str, Any], *, include_confirm: bool = False
) -> List[Dict[str, Any]]:
    """Herramientas Realtime para agendar en vivo. Vacio si el cliente no tiene reserva.
    include_confirm=True anade `confirmar_cita` (llamadas salientes de confirmacion)."""
    if not _voice_booking_enabled(cliente_id, config):
        return []
    tools: List[Dict[str, Any]] = [
        {
            "type": "function",
            "name": "consultar_disponibilidad",
            "description": (
                "Devuelve las horas libres de un dia concreto. Llamala antes de proponer horas. "
                "La fecha debe ir en formato YYYY-MM-DD."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fecha": {"type": "string", "description": "Fecha en formato YYYY-MM-DD"},
                    "servicio": {"type": "string", "description": "Servicio solicitado (opcional)"},
                },
                "required": ["fecha"],
            },
        },
        {
            "type": "function",
            "name": "crear_cita",
            "description": (
                "Crea y confirma una cita. Llamala solo despues de haber confirmado con el cliente nombre, "
                "telefono, servicio, fecha (YYYY-MM-DD) y hora (HH:MM en 24h), y tras comprobar disponibilidad. "
                "Devuelve un numero de reserva (formato R-XXXX): comunicaselo al cliente y pidele que lo guarde."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre": {"type": "string"},
                    "telefono": {"type": "string"},
                    "servicio": {"type": "string"},
                    "fecha": {"type": "string", "description": "YYYY-MM-DD"},
                    "hora": {"type": "string", "description": "HH:MM en 24h"},
                    "email": {"type": "string", "description": "Email (opcional)"},
                },
                "required": ["nombre", "telefono", "fecha", "hora"],
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
    return {"ok": True, "fecha": fecha, "huecos": slots[:20], "hay_huecos": bool(slots)}


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

    service_row = agenda._find_service_by_name(cliente_id, servicio)
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
        return {"ok": False, "error": "Ese horario ya no esta disponible. Ofrece otra hora."}

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
    return {
        "ok": True,
        "booking_id": booking_id,
        "codigo_reserva": record.get("booking_code", ""),
        "fecha": booking_date,
        "hora": booking_time,
        "servicio": servicio or "cita",
        "empleado": employee_row["name"],
        "manage_url": booking._build_booking_manage_url(manage_token),
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


async def _voice_cancel_booking(
    cliente_id: str,
    codigo_reserva: str,
    *,
    from_number: str = "",
    telefono: str = "",
    email: str = "",
    motivo: str = "",
) -> Dict[str, Any]:
    row, error = await _voice_lookup_and_verify_booking(
        cliente_id, codigo_reserva, from_number=from_number, telefono=telefono, email=email
    )
    if error:
        return error
    if row["status"] == "cancelled":
        return {"ok": True, "ya_cancelada": True, "mensaje": "Esa cita ya estaba cancelada."}
    if row["status"] == "completed":
        return {"ok": False, "error": "Esa cita ya se ha realizado y no se puede cancelar."}
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
    row, error = await _voice_lookup_and_verify_booking(
        cliente_id, codigo_reserva, from_number=from_number, telefono=telefono, email=email
    )
    if error:
        return error
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
    return {
        "ok": True,
        "codigo_reserva": row["booking_code"] or "",
        "fecha": textnorm._sanitize_text(fecha),
        "hora": textnorm._sanitize_text(hora),
        "mensaje": "Cita reprogramada correctamente. El numero de reserva sigue siendo el mismo.",
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
    if name == "consultar_disponibilidad":
        return await _voice_check_availability(
            cliente_id, str(args.get("fecha", "")), str(args.get("servicio", "")), location_id
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
            location_id=location_id,
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
    if name in {"crear_cita", "cancelar_cita", "reprogramar_cita"}:
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
        "contact": (row["from_number"] or "").strip() or "Llamada",
        "started_at": row["started_at"] or "",
        "last_at": row["ended_at"] or row["started_at"] or "",
        "preview": preview,
        "message_count": len(transcript),
        "duration_seconds": int(row["duration_seconds"] or 0),
        "booking_created": bool(row["booking_created"]),
        "intents": [],
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


