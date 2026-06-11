"""Endpoints: seccion voice_web (refactor F3).

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

@app.post("/voice/{cliente_id}")
async def voice_incoming_call(cliente_id: str, request: Request) -> Response:
    """Webhook Twilio para una llamada entrante. Devuelve TwiML con Media Stream."""
    if not settings.CLIENT_ID_PATTERN.match(cliente_id):
        return voice._voice_twiml_unavailable()
    if not messaging._voice_twilio_configured():
        raise HTTPException(status_code=503, detail="Voice not configured")

    params = await voice._voice_form_params(request)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not messaging._twilio_request_valid(voice._voice_request_url(request), params, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    voice_cfg = voice._get_voice_config(cliente_id)
    if not voice_cfg:
        return voice._voice_twiml_unavailable()

    call_sid = params.get("CallSid", "")
    if call_sid:
        voice._voice_call_register(call_sid, cliente_id, params.get("From", ""), params.get("To", ""))

    return voice._voice_twiml_connect_stream(voice._voice_stream_ws_url(request, cliente_id), call_sid)


@app.post("/voice/status/{cliente_id}")
async def voice_status_callback(cliente_id: str, request: Request) -> Response:
    """Status callback de Twilio (completed/failed/busy/no-answer)."""
    if not messaging._voice_twilio_configured():
        raise HTTPException(status_code=503, detail="Voice not configured")
    params = await voice._voice_form_params(request)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not messaging._twilio_request_valid(voice._voice_request_url(request), params, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    call_sid = params.get("CallSid", "")
    call_status = (params.get("CallStatus", "") or "").lower()
    mapping = {
        "completed": "completed",
        "busy": "no_answer",
        "no-answer": "no_answer",
        "failed": "failed",
        "canceled": "failed",
    }
    new_status = mapping.get(call_status)
    if call_sid and new_status:
        try:
            with db._get_db_connection() as conn:
                conn.execute(
                    "UPDATE voice_calls SET status=? WHERE call_sid=? AND status != 'completed'",
                    (new_status, call_sid),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("[voice] status callback fallo para %s: %s", call_sid, exc)
    return Response(status_code=204)


@app.websocket("/voice/stream/{cliente_id}")
async def voice_media_stream(websocket: WebSocket, cliente_id: str) -> None:
    """Puente bidireccional Twilio Media Streams <-> OpenAI Realtime API."""
    if not settings.CLIENT_ID_PATTERN.match(cliente_id):
        await websocket.close(code=1008)
        return
    config = appstate.CONFIG_CLIENTES.get(cliente_id)
    voice_cfg = voice._get_voice_config(cliente_id)
    if not config or not voice_cfg:
        await websocket.close(code=1008)
        return
    if not settings.OPENAI_API_KEY:
        await websocket.close(code=1011)
        return

    await websocket.accept()

    state: Dict[str, Any] = {
        "stream_sid": "",
        "call_sid": "",
        "booked": False,
        "fn_names": {},
        "latest_media_timestamp": 0,
        "assistant_item_id": "",
        "assistant_audio_started_at": None,
        "assistant_audio_generated_ms": 0,
    }
    transcript: List[Dict[str, str]] = []
    started_monotonic = time.time()
    max_duration = int(voice_cfg.get("max_duration_seconds") or 0) or settings.VOICE_MAX_DURATION_SECONDS
    status_value = "completed"

    def _append_transcript(role: str, text: str) -> None:
        clean = (text or "").strip()
        if clean:
            transcript.append(
                {"role": role, "text": clean, "ts": timeutils._utc_now().isoformat()}
            )

    realtime_model = voice_cfg.get("realtime_model") or settings.VOICE_REALTIME_MODEL
    try:
        openai_ws = await voice._open_realtime_ws(realtime_model)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] no se pudo conectar a OpenAI Realtime (%s): %s", cliente_id, exc)
        await websocket.close(code=1011)
        return

    try:
        await openai_ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "model": realtime_model,
                        "output_modalities": ["audio"],
                        "instructions": voice._voice_build_instructions(cliente_id, config),
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcmu"},
                                # semantic_vad en vez de server_vad: en telefonia no hay
                                # AEC y el eco de la linea se colaba como inbound; con un
                                # VAD por amplitud eso disparaba una respuesta al propio
                                # audio (se corta + repite). El VAD semantico solo abre
                                # turno cuando de verdad habla el llamante, asi que ignora
                                # eco/ruido de la linea. eagerness=low es conservador;
                                # interrupt_response=True permite un barge-in natural. Al
                                # detectar habla truncamos manualmente el audio pendiente de
                                # Twilio para que el modelo no repita la frase completa.
                                "turn_detection": {
                                    "type": "semantic_vad",
                                    "eagerness": "low",
                                    "create_response": True,
                                    "interrupt_response": True,
                                },
                                "transcription": {"model": "whisper-1"},
                            },
                            "output": {
                                "format": {"type": "audio/pcmu"},
                                "voice": voice_cfg.get("openai_voice") or settings.VOICE_OPENAI_VOICE,
                            },
                        },
                        "tools": voice._voice_booking_tools(cliente_id, config),
                        "tool_choice": "auto",
                    },
                }
            )
        )

        # Prioridad del saludo: greeting de voz especifico -> mensaje de bienvenida
        # de "Apariencia" (bienvenida) -> default con el nombre del asistente de voz.
        # Compartido con el test del panel y la demo via _voice_default_greeting.
        greeting = textnorm._voice_default_greeting(config, voice_cfg)
        await openai_ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": f'Inicia la llamada saludando exactamente con: "{greeting}"',
                            }
                        ],
                    },
                }
            )
        )
        await openai_ws.send(json.dumps({"type": "response.create"}))

        async def twilio_to_openai() -> None:
            try:
                async for raw in websocket.iter_text():
                    message = json.loads(raw)
                    event = message.get("event")
                    if event == "media":
                        try:
                            state["latest_media_timestamp"] = int(
                                message.get("media", {}).get("timestamp", 0)
                            )
                        except (TypeError, ValueError):
                            pass
                        await openai_ws.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": message["media"]["payload"],
                                }
                            )
                        )
                    elif event == "start":
                        start = message.get("start", {})
                        state["stream_sid"] = start.get("streamSid", "")
                        state["call_sid"] = start.get("callSid", "") or start.get(
                            "customParameters", {}
                        ).get("call_sid", "")
                        state["from_number"] = voice._voice_call_from_number(state["call_sid"])
                    elif event == "stop":
                        break
            except WebSocketDisconnect:
                pass
            finally:
                await voice._voice_safe_close(openai_ws)

        async def openai_to_twilio() -> None:
            async def _stream_sid_ready(timeout_seconds: float = 3.0) -> str:
                deadline = time.time() + timeout_seconds
                while not state["stream_sid"] and time.time() < deadline:
                    await asyncio.sleep(0.02)
                return state["stream_sid"]

            async for raw in openai_ws:
                event = json.loads(raw)
                etype = event.get("type")
                if etype == "response.output_audio.delta" and event.get("delta"):
                    stream_sid = state["stream_sid"] or await _stream_sid_ready()
                    if stream_sid:
                        item_id = event.get("item_id", "")
                        if item_id and item_id != state["assistant_item_id"]:
                            state["assistant_item_id"] = item_id
                            state["assistant_audio_started_at"] = state["latest_media_timestamp"]
                            state["assistant_audio_generated_ms"] = 0
                        state["assistant_audio_generated_ms"] += voice._voice_pcmu_duration_ms(
                            event["delta"]
                        )
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": event["delta"]},
                                }
                            )
                        )
                elif etype == "response.output_audio_transcript.done":
                    _append_transcript("assistant", event.get("transcript", ""))
                elif etype == "conversation.item.input_audio_transcription.completed":
                    _append_transcript("user", event.get("transcript", ""))
                elif etype == "response.output_item.added":
                    item = event.get("item", {}) or {}
                    if item.get("type") == "function_call" and item.get("call_id"):
                        state["fn_names"][item["call_id"]] = item.get("name", "")
                elif etype == "response.function_call_arguments.done":
                    call_id = event.get("call_id", "")
                    fname = event.get("name") or state["fn_names"].get(call_id, "")
                    result = await voice._voice_dispatch_tool(
                        cliente_id, fname, event.get("arguments", ""),
                        from_number=state.get("from_number", ""),
                    )
                    if fname == "crear_cita" and result.get("ok"):
                        state["booked"] = True
                    await openai_ws.send(
                        json.dumps(
                            {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": json.dumps(result, ensure_ascii=False),
                                },
                            }
                        )
                    )
                    await openai_ws.send(json.dumps({"type": "response.create"}))
                elif etype == "input_audio_buffer.speech_started":
                    await voice._voice_truncate_interrupted_response(openai_ws, websocket, state)
                elif etype == "error":
                    settings.logger.warning("[voice] OpenAI error %s: %s", cliente_id, event.get("error"))

        tasks = [
            asyncio.create_task(twilio_to_openai()),
            asyncio.create_task(openai_to_twilio()),
        ]
        _done, pending = await asyncio.wait(
            tasks, timeout=max_duration, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except Exception as exc:  # noqa: BLE001
        settings.logger.exception("[voice] error en stream de %s: %s", cliente_id, exc)
        status_value = "failed"
    finally:
        await voice._voice_safe_close(openai_ws)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
        await voice._voice_finalize_call(
            cliente_id=cliente_id,
            config=config,
            voice_cfg=voice_cfg,
            call_sid=state["call_sid"],
            transcript=transcript,
            duration_seconds=int(time.time() - started_monotonic),
            status_value=status_value,
            booking_done=bool(state.get("booked")),
        )




@app.get("/admin/voice/calls", dependencies=[Depends(security._require_admin_token)])
async def admin_voice_calls(
    cliente_id: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    where: List[str] = []
    params: List[Any] = []
    if cliente_id:
        where.append("cliente_id=?")
        params.append(cliente_id)
    if status:
        where.append("status=?")
        params.append(status)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    offset = (page - 1) * page_size
    with db._get_db_connection() as conn:
        total = int(
            conn.execute(f"SELECT COUNT(*) AS c FROM voice_calls{clause}", params).fetchone()["c"]
        )
        rows = conn.execute(
            f"""
            SELECT id, call_sid, cliente_id, from_number, started_at,
                   duration_seconds, status, summary, booking_created
            FROM voice_calls{clause}
            ORDER BY id DESC LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()
        stats = voice._voice_stats(conn, cliente_id)
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "stats": stats,
    }


@app.get("/admin/voice/calls/{call_sid}", dependencies=[Depends(security._require_admin_token)])
async def admin_voice_call_detail(call_sid: str) -> Dict[str, Any]:
    with db._get_db_connection() as conn:
        row = conn.execute("SELECT * FROM voice_calls WHERE call_sid=?", (call_sid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Llamada no encontrada")
    data = dict(row)
    try:
        data["transcript"] = json.loads(data.get("transcript_json") or "[]")
    except Exception:  # noqa: BLE001
        data["transcript"] = []
    return data




