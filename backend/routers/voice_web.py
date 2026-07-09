"""Endpoints: seccion voice_web (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List

from fastapi import (
    Depends,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)


from api_models import *  # noqa: F401,F403
from backend import (
    appstate,
    booking,
    db,
    messaging,
    security,
    settings,
    textnorm,
    voice,
    voice_engine,
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
        # El webhook de Twilio puede apuntar a un cliente_id antiguo/borrado. Resolvemos por
        # el numero destino (To) contra el twilio_phone_number configurado de cada cliente.
        resolved_cid = voice._voice_client_for_twilio_number(params.get("To", ""))
        if resolved_cid:
            cliente_id = resolved_cid
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

    # El contexto de una llamada SALIENTE de confirmacion (mode/booking_id + datos de la
    # cita) llega en los customParameters del evento 'start': Twilio NO preserva el query
    # string del Stream (verificado en produccion). Por eso la sesion de OpenAI se configura
    # al recibir ese 'start', no al aceptar. El query string se conserva como FALLBACK por si
    # algun entorno si lo reenvia.
    qp_fallback = dict(websocket.query_params)

    # Motor determinista de la llamada (estado + toda la logica de encarrilado: anti-silencio,
    # confirmacion, dedup de reserva, fallbacks) vive en backend/voice_engine.py. Este puente
    # solo transporta audio/eventos Twilio<->OpenAI y delega cada decision en el motor, que se
    # testea sin WebSocket (tests/test_voice_engine.py).
    engine = voice_engine.VoiceCallEngine(cliente_id, config, voice_cfg)
    state = engine.state
    started_monotonic = time.time()
    max_duration = int(voice_cfg.get("max_duration_seconds") or 0) or settings.VOICE_MAX_DURATION_SECONDS
    status_value = "completed"

    try:
        openai_ws = await voice._open_realtime_ws(engine.realtime_model)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] no se pudo conectar a OpenAI Realtime (%s): %s", cliente_id, exc)
        await websocket.close(code=1011)
        return

    # El motor emite a OpenAI/Twilio a traves de estos callbacks (no conoce el WebSocket).
    engine.bind_transport(
        send_openai=lambda ev: openai_ws.send(json.dumps(ev)),
        send_twilio=lambda ev: websocket.send_text(json.dumps(ev)),
        clear_playback=lambda: voice._voice_clear_twilio_playback(websocket, engine.state),
        truncate_interrupted=lambda: voice._voice_truncate_interrupted_response(openai_ws, websocket, engine.state),
    )

    try:
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
                        custom = start.get("customParameters", {}) or {}
                        state["stream_sid"] = start.get("streamSid", "")
                        state["call_sid"] = start.get("callSid", "") or custom.get("call_sid", "")
                        # customParameters mandan; el query string es solo fallback.
                        params = {**qp_fallback, **custom}
                        await engine.configure_realtime_session(params)
                        if not state["outbound"]:
                            # Entrante: resolvemos numero/centro por el call_sid (el saliente
                            # ya los fijo desde los parametros de la cita).
                            state["from_number"] = voice._voice_call_from_number(state["call_sid"])
                            state["location_id"] = voice._voice_call_location_id(state["call_sid"], cliente_id)
                    elif event == "stop":
                        break
            except WebSocketDisconnect:
                pass
            finally:
                await voice._voice_safe_close(openai_ws)

        async def openai_to_twilio() -> None:
            while True:
                try:
                    raw = await asyncio.wait_for(openai_ws.recv(), timeout=0.2)
                except asyncio.TimeoutError:
                    await engine.maybe_recover_silence()
                    if _should_hang_up():
                        break
                    continue
                event = json.loads(raw)
                await engine.on_openai_event(event)
                # Colgar limpio: el motor pidio terminar (finalizar_llamada / transferencia /
                # sin respuesta) y ya se dijo la ultima frase (respuesta cerrada, sin activa).
                if _should_hang_up():
                    break

        def _should_hang_up() -> bool:
            return bool(
                state.get("should_end_call")
                and not state.get("response_active")
                and state.get("turn_had_assistant_output")
            )

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
            transcript=engine.transcript,
            duration_seconds=int(time.time() - started_monotonic),
            status_value=status_value,
            booking_done=bool(state.get("booked")),
            outcome=str(state.get("outcome") or ""),
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
                   duration_seconds, status, summary, booking_created, outcome, direction, purpose
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
