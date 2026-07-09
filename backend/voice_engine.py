"""Motor determinista de la conversacion de voz (lado Twilio).

Toda la LOGICA que encarrila al modelo (anti-silencio, confirmacion, dedup de reservas,
fallbacks de fecha/servicio/centro, reanudacion tras barge-in, forzado de habla tras tool)
vive aqui, separada del TRANSPORTE WebSocket. El puente `voice_media_stream`
(backend/routers/voice_web.py) queda fino: lee frames de Twilio/OpenAI y delega en
`VoiceCallEngine`; la clase nunca toca el WebSocket directamente, solo emite eventos a traves
de callbacks de transporte inyectados (`bind_transport`). Asi el motor se testea de verdad
sin red ni audio (ver tests/test_voice_engine.py): se le pasan eventos Realtime y se asierta
lo que emite.

Comparte SPEC con el motor de navegador en widget/voice_core.js (mismo comportamiento, otro
runtime); no comparten codigo porque uno es Python sobre Twilio y el otro JS sobre WebRTC.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable, Dict, Set

from backend import booking, settings, textnorm, timeutils, voice

# Tools cuyo resultado (mensaje_voz/mensaje/error) SIEMPRE debe convertirse en habla: si el
# modelo se queda mudo tras ejecutarlas, el puente fuerza la frase. Las informativas/POS no
# entran aqui porque su silencio no rompe el flujo de reserva.
FORCE_SPEECH_TOOLS: Set[str] = {
    "consultar_disponibilidad",
    "consultar_cita",
    "crear_cita",
    "cancelar_cita",
    "reprogramar_cita",
    "enviar_codigo_verificacion",
    "enviar_enlace_pago",
    "confirmar_cita",
    "finalizar_llamada",
    "transferir_a_humano",
}


def new_call_state() -> Dict[str, Any]:
    """Estado inicial de UNA llamada de voz. Una sola definicion de la forma del estado
    (antes era un literal de ~70 lineas embebido en el puente). El puente sigue siendo el
    duenyo del dict; este factory solo lo construye."""
    return {
        "stream_sid": "",
        "call_sid": "",
        "booked": False,
        "mode": "",
        "outbound": False,
        # Solo las citas reales se marcan confirmadas; en la prueba queda vacio.
        "outbound_booking_id": "",
        "session_configured": False,
        "fn_names": {},
        "latest_media_timestamp": 0,
        "assistant_item_id": "",
        "assistant_audio_started_at": None,
        "assistant_audio_generated_ms": 0,
        # Reanudacion tras barge-in: el ultimo turno del asistente fue interrumpido.
        "was_interrupted": False,
        "pending_tool_followup_prompt": "",
        "pending_tool_name": "",
        "pending_tool_result": {},
        "current_response_done": False,
        "response_active": False,
        "response_active_started_at": 0.0,
        "response_cancel_pending": False,
        "response_cancel_started_at": 0.0,
        "pending_tool_response": False,
        "silence_guard_armed": False,
        "silence_guard_started_at": 0.0,
        "silence_guard_reason": "",
        "silence_guard_used": False,
        "silence_guard_recoveries": 0,
        "turn_had_assistant_output": False,
        "turn_had_function_call": False,
        "pending_mutation_code": "",
        "pending_mutation_intent": "",
        # Etiqueta de resultado de la llamada (para informes): se va sellando segun avanza
        # (reservada/cancelada/reprogramada/confirmada/transferida). Vacio = sin accion.
        "outcome": "",
        # Colgar limpio: el motor pide cerrar la llamada tras la ultima frase.
        "should_end_call": False,
        # Anti-duplicado: firmas de citas ya creadas en esta llamada (evita doble reserva
        # si el modelo y el puente intentan crear el mismo hueco).
        "created_signatures": set(),
    }


def should_force_tool_speech(tool_name: str, result: Dict[str, Any]) -> bool:
    """True si tras ejecutar `tool_name` con `result` el asistente DEBE decir algo (hay
    mensaje y la tool es de las que no pueden quedar en silencio)."""
    if not tool_name or not isinstance(result, dict):
        return False
    if not (result.get("mensaje_voz") or result.get("mensaje") or result.get("error")):
        return False
    return tool_name in FORCE_SPEECH_TOOLS


def booking_signature(args: Dict[str, Any]) -> str:
    """Firma estable de una cita (telefono/servicio/centro/fecha/hora) para deduplicar
    creaciones dentro de la misma llamada. Vacia si falta fecha u hora (sin firma no se
    deduplica)."""
    if not isinstance(args, dict):
        return ""
    parts = [
        re.sub(r"\D", "", str(args.get("telefono", ""))),
        str(args.get("servicio", "")).strip().lower(),
        str(args.get("centro", "")).strip().lower(),
        str(args.get("fecha", "")).strip(),
        str(args.get("hora", "")).strip(),
    ]
    return "|".join(parts) if (parts[3] and parts[4]) else ""


# Tipos de los callbacks de transporte que inyecta el puente (voice_web). El motor nunca toca
# el WebSocket: emite eventos a OpenAI / Twilio a traves de estas funciones.
SendEvent = Callable[[Dict[str, Any]], Awaitable[None]]
AsyncBool = Callable[[], Awaitable[bool]]


class VoiceCallEngine:
    """Motor de UNA llamada de voz. Posee el estado y toda la logica determinista; el puente
    le pasa los eventos Realtime (`on_openai_event`) y el tick del watchdog
    (`maybe_recover_silence`), y el motor responde emitiendo eventos por los callbacks de
    transporte. Sin WebSocket dentro: testeable con un transporte falso."""

    def __init__(self, cliente_id: str, config: Dict[str, Any], voice_cfg: Dict[str, Any]) -> None:
        self.cliente_id = cliente_id
        self.config = config
        self.voice_cfg = voice_cfg
        self.realtime_model = voice_cfg.get("realtime_model") or settings.VOICE_REALTIME_MODEL
        self.transfer_number = voice._voice_transfer_number(voice_cfg)
        self.state: Dict[str, Any] = new_call_state()
        self.transcript: list = []
        self.silence_guard_seconds = 1.7
        self.active_response_grace_seconds = 8.0
        # Transporte (lo inyecta el puente con bind_transport). Defaults no-op para tests.
        self._send_openai: SendEvent = self._noop_send
        self._send_twilio: SendEvent = self._noop_send
        self._clear_playback: AsyncBool = self._noop_bool
        self._truncate_interrupted: AsyncBool = self._noop_bool

    @staticmethod
    async def _noop_send(_event: Dict[str, Any]) -> None:
        return None

    @staticmethod
    async def _noop_bool() -> bool:
        return False

    def bind_transport(
        self,
        *,
        send_openai: SendEvent,
        send_twilio: SendEvent,
        clear_playback: AsyncBool,
        truncate_interrupted: AsyncBool,
    ) -> None:
        self._send_openai = send_openai
        self._send_twilio = send_twilio
        self._clear_playback = clear_playback
        self._truncate_interrupted = truncate_interrupted

    # --- estado / watchdog -------------------------------------------------
    def append_transcript(self, role: str, text: str) -> None:
        clean = (text or "").strip()
        if clean:
            self.transcript.append(
                {"role": role, "text": clean, "ts": timeutils._utc_now().isoformat()}
            )

    def arm_silence_guard(self, reason: str) -> None:
        self.state["silence_guard_armed"] = True
        self.state["silence_guard_started_at"] = time.monotonic()
        self.state["silence_guard_reason"] = reason
        self.state["silence_guard_used"] = False

    def disarm_silence_guard(self) -> None:
        self.state["silence_guard_armed"] = False
        self.state["silence_guard_reason"] = ""

    def mark_response_active(self) -> None:
        self.state["response_active"] = True
        self.state["response_active_started_at"] = time.monotonic()

    def mark_response_inactive(self) -> None:
        self.state["response_active"] = False
        self.state["response_active_started_at"] = 0.0

    async def cancel_active_response(self, reason: str) -> None:
        """Cancela una respuesta Realtime activa sin lanzar otra encima. Vacia el buffer de
        Twilio antes y espera el response.done (o el timeout del watchdog) antes de forzar
        una nueva frase."""
        if self.state.get("response_cancel_pending"):
            return
        try:
            await self._clear_playback()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self._send_openai({"type": "response.cancel"})
        except Exception:  # noqa: BLE001
            pass
        self.state["response_cancel_pending"] = True
        self.state["response_cancel_started_at"] = time.monotonic()
        self.mark_response_inactive()
        self.state["silence_guard_reason"] = reason or "active_response_silent"
        self.state["silence_guard_used"] = False

    async def stream_sid_ready(self, timeout_seconds: float = 3.0) -> str:
        deadline = time.time() + timeout_seconds
        while not self.state["stream_sid"] and time.time() < deadline:
            await asyncio.sleep(0.02)
        return self.state["stream_sid"]

    # --- configuracion de sesion ------------------------------------------
    async def configure_realtime_session(self, params: Dict[str, str]) -> None:
        """Configura la sesion Realtime (instrucciones, tools y saludo) en cuanto se conocen
        los parametros del Stream. Distingue ENTRANTE de SALIENTE de confirmacion. Idempotente."""
        if self.state["session_configured"]:
            return
        self.state["session_configured"] = True
        cliente_id = self.cliente_id
        config = self.config
        voice_cfg = self.voice_cfg
        call_mode = (params.get("mode") or "").strip().lower()
        outbound_booking = None
        if call_mode == "confirm":
            booking_id = (params.get("booking_id") or "").strip()
            if booking_id:
                try:
                    row = booking._get_booking_row_by_id(booking_id)
                    if row and row["cliente_id"] == cliente_id:
                        outbound_booking = row
                        self.state["outbound_booking_id"] = booking_id
                except Exception:  # noqa: BLE001
                    outbound_booking = None
            if outbound_booking is None:
                outbound_booking = booking._EphemeralBookingRow({
                    "id": booking_id or "outbound_test",
                    "cliente_id": cliente_id,
                    "nombre": (params.get("b_nombre") or "").strip(),
                    "servicio": (params.get("b_servicio") or "").strip(),
                    "booking_date": (params.get("b_fecha") or "").strip(),
                    "booking_time": (params.get("b_hora") or "").strip(),
                    "telefono": (params.get("to") or "").strip(),
                    "location_id": "",
                })
            self.state["mode"] = "confirm"
            self.state["outbound"] = True
            self.state["from_number"] = (params.get("to") or "").strip()
            self.state["location_id"] = outbound_booking["location_id"] or ""
            self.state["pending_mutation_code"] = (outbound_booking["booking_code"] or "")
            instructions_text = voice._voice_outbound_confirm_instructions(cliente_id, config, outbound_booking)
            tools_list = voice._voice_booking_tools(cliente_id, config, include_confirm=True)
            greeting_text = voice._voice_outbound_greeting(config, outbound_booking)
        else:
            instructions_text = voice._voice_build_instructions(cliente_id, config)
            tools_list = voice._voice_booking_tools(cliente_id, config)
            greeting_text = textnorm._voice_default_greeting(config, voice_cfg)
        settings.logger.info(
            "[voice] stream %s sesion configurada mode=%s outbound=%s",
            cliente_id, call_mode or "inbound", self.state["outbound"],
        )
        await self._send_openai({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": self.realtime_model,
                "output_modalities": ["audio"],
                "instructions": instructions_text,
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcmu"},
                        **voice._voice_audio_input_config(voice_cfg, default_noise="far_field"),
                    },
                    "output": {
                        "format": {"type": "audio/pcmu"},
                        "voice": voice_cfg.get("openai_voice") or settings.VOICE_OPENAI_VOICE,
                    },
                },
                "tools": tools_list,
                "tool_choice": "auto",
            },
        })
        await self._send_openai({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": f'Tu PRIMER mensaje debe ser, palabra por palabra y sin cambiar ningun nombre propio (di los nombres tal cual aparecen), EXACTAMENTE este y nada mas: "{greeting_text}"',
                }],
            },
        })
        await self._send_openai({
            "type": "response.create",
            "response": {
                "instructions": (
                    "Di exactamente esta frase y nada mas, sin llamar herramientas: "
                    f"\"{greeting_text}\""
                ),
                "tool_choice": "none",
            },
        })
        self.mark_response_active()
        self.arm_silence_guard("greeting")

    # --- forzado de habla / tools -----------------------------------------
    async def force_say(self, instruction: str, *, system_text: str = "") -> None:
        """Inyecta un turno [sistema] y obliga al modelo a hablar segun `instruction` (sin
        llamar tools). Centraliza el patron repetido del puente y arma el reintento anti-silencio."""
        await self._send_openai({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": system_text or f"[sistema] {instruction}"}],
            },
        })
        await self._send_openai({
            "type": "response.create",
            "response": {"instructions": instruction, "tool_choice": "none"},
        })
        self.state["turn_had_assistant_output"] = False
        self.mark_response_active()
        self.arm_silence_guard("forced_speech")

    async def speak_forced_tool_result(
        self, tool_name: str, result: Dict[str, Any], *, extra_instruction: str = ""
    ) -> None:
        # Guia NATURAL (no verbatim): el modelo transmite el resultado con sus palabras,
        # manteniendo exactos los datos. Antes se forzaba 'di exactamente esta frase'.
        followup_prompt = voice._voice_tool_followup_prompt(tool_name, result)
        instruction = followup_prompt or (
            "Di al cliente el resultado en una frase breve y natural, manteniendo exactos los "
            "datos (horas, fechas, precios, numero de reserva)."
        )
        if extra_instruction:
            instruction = f"{instruction} {extra_instruction}"
        await self.force_say(instruction, system_text=(
            f"[sistema] Resultado interno de {tool_name}: "
            f"{json.dumps(result, ensure_ascii=False)}\n{instruction}"
        ))

    async def create_booking_deduped(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Crea la cita salvo que una identica ya se haya creado en esta llamada (evita doble
        reserva si el modelo y el puente coinciden). Devuelve el resultado de la tool."""
        sig = booking_signature(args)
        if sig and sig in self.state["created_signatures"]:
            return {
                "ok": True, "duplicate": True,
                "mensaje_voz": "Esa cita ya esta creada, no la he duplicado.",
            }
        result = await voice._voice_dispatch_tool(
            self.cliente_id, "crear_cita", json.dumps(args, ensure_ascii=False),
            from_number=self.state.get("from_number", ""),
            location_id=self.state.get("location_id", ""),
        )
        if result.get("ok") and sig:
            self.state["created_signatures"].add(sig)
        return result

    async def _do_transfer(self) -> Dict[str, Any]:
        """Desvia la llamada telefonica a una persona (numero configurable del negocio). Twilio
        reescribe el TwiML a un <Dial> y cierra nuestro Stream; ademas pedimos colgar limpio."""
        number = self.transfer_number
        if not number:
            return {"ok": False, "mensaje_voz": "Ahora mismo no puedo pasarte con una persona, pero tomo nota y te llamamos."}
        pretty = number.lstrip("+")
        call_sid = str(self.state.get("call_sid") or "")
        if not call_sid:
            return {"ok": True, "mensaje_voz": f"Para hablar con una persona del equipo, llama al {pretty}."}
        ok = await timeutils._to_thread(voice._voice_transfer_call, self.cliente_id, call_sid, number)
        if ok:
            self.state["outcome"] = "transferida"
            self.state["should_end_call"] = True
            return {"ok": True, "transferred": True, "mensaje_voz": "Te paso con una persona, un momento."}
        return {"ok": False, "mensaje_voz": f"No he podido pasarte ahora mismo. Puedes llamar al {pretty}."}

    async def maybe_recover_silence(self) -> None:
        """Watchdog anti-silencio MINIMO. Si el modelo se queda mudo: cancela una respuesta que
        se quedo sin audio, dice un resultado de herramienta pendiente, o le da UN empujon
        INTERNO para que continue con sus palabras. No decide frases de cara al cliente ni
        ejecuta acciones deterministas: el modelo manda; las tools imponen la correccion."""
        state = self.state
        if not state.get("session_configured") or not state.get("silence_guard_armed"):
            return
        if state.get("turn_had_assistant_output"):
            self.disarm_silence_guard()
            return
        started = float(state.get("silence_guard_started_at") or 0.0)
        if not started or time.monotonic() - started < self.silence_guard_seconds:
            return
        if state.get("response_cancel_pending"):
            cancel_started = float(state.get("response_cancel_started_at") or 0.0)
            if cancel_started and time.monotonic() - cancel_started < 0.8:
                return
            state["response_cancel_pending"] = False
            state["response_cancel_started_at"] = 0.0
            self.mark_response_inactive()
        if state.get("silence_guard_used"):
            return
        if state.get("response_active"):
            active_started = float(state.get("response_active_started_at") or 0.0)
            if not active_started:
                self.mark_response_active()
                return
            if time.monotonic() - active_started < self.active_response_grace_seconds:
                return
            await self.cancel_active_response("active_response_silent")
            return
        state["silence_guard_used"] = True
        state["silence_guard_recoveries"] = int(state.get("silence_guard_recoveries") or 0) + 1
        settings.logger.info(
            "[voice] watchdog anti-silencio %s reason=%s recovery=%s",
            self.cliente_id, state.get("silence_guard_reason", ""), state["silence_guard_recoveries"],
        )
        if state["silence_guard_recoveries"] > 3:
            # No hay respuesta tras varios intentos: despedida cordial y colgar limpio (una vez).
            if not state.get("should_end_call"):
                state["should_end_call"] = True
                await self.force_say(
                    "Despidete brevemente porque no hay respuesta, por ejemplo 'parece que se ha cortado, "
                    "que tengas un buen dia'. Una sola frase, sin preguntar mas.",
                    system_text="[sistema] No hay respuesta del cliente tras varios intentos: despidete en una frase y termina.",
                )
            return
        pending_name = str(state.get("pending_tool_name") or "")
        pending_result = state.get("pending_tool_result") or {}
        if state.get("pending_tool_response") and should_force_tool_speech(pending_name, pending_result):
            state["pending_tool_response"] = False
            state["pending_tool_followup_prompt"] = ""
            state["pending_tool_name"] = ""
            state["pending_tool_result"] = {}
            await self.speak_forced_tool_result(pending_name, pending_result)
            return
        await self._nudge_continue()

    async def _nudge_continue(self) -> None:
        """Empujon INTERNO cuando el modelo se queda mudo: le recordamos el contexto y que siga,
        pero la frase la elige EL. tool_choice libre: puede hablar o llamar a una herramienta."""
        await self._send_openai({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "[sistema] Te has quedado en silencio y el cliente espera. Continua la "
                        "conversacion de forma natural, con tus palabras y sin decir 'un momento': "
                        "si esperabas un dato, vuelve a pedirlo; si acabas de usar una herramienta, "
                        "di su resultado; si el cliente pidio reservar, cancelar o cambiar una cita, "
                        "da el siguiente paso (identificar la cita, verificar la identidad o llamar "
                        "a la herramienta que toque). No repitas la misma frase de antes."
                    ),
                }],
            },
        })
        await self._send_openai({"type": "response.create"})
        self.mark_response_active()
        self.arm_silence_guard("continue_nudge")

    # --- evento Realtime entrante -----------------------------------------
    async def on_openai_event(self, event: Dict[str, Any]) -> None:
        """Procesa UN evento del WebSocket Realtime de OpenAI. Antes era el cuerpo del bucle
        `openai_to_twilio`; los `continue` del bucle son aqui `return`."""
        state = self.state
        cliente_id = self.cliente_id
        etype = event.get("type")
        if etype == "response.created":
            self.mark_response_active()
        elif etype == "error":
            err = event.get("error") or {}
            code = str(err.get("code") or "")
            if code == "conversation_already_has_active_response":
                self.mark_response_active()
                self.arm_silence_guard("active_response_retry")
            else:
                settings.logger.warning("[voice] error Realtime %s: %s", cliente_id, err)
        elif etype == "response.output_audio.delta" and event.get("delta"):
            state["response_cancel_pending"] = False
            state["response_cancel_started_at"] = 0.0
            state["turn_had_assistant_output"] = True
            self.disarm_silence_guard()
            stream_sid = state["stream_sid"] or await self.stream_sid_ready()
            if stream_sid:
                item_id = event.get("item_id", "")
                if item_id and item_id != state["assistant_item_id"]:
                    state["assistant_item_id"] = item_id
                    state["assistant_audio_started_at"] = state["latest_media_timestamp"]
                    state["assistant_audio_generated_ms"] = 0
                state["assistant_audio_generated_ms"] += voice._voice_pcmu_duration_ms(event["delta"])
                await self._send_twilio({
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": event["delta"]},
                })
        elif etype == "response.output_audio_transcript.done":
            assistant_text = event.get("transcript", "")
            self.append_transcript("assistant", assistant_text)
            if assistant_text:
                state["turn_had_assistant_output"] = True
        elif etype == "conversation.item.input_audio_transcription.completed":
            user_text = event.get("transcript", "")
            self.append_transcript("user", user_text)
            state["turn_had_assistant_output"] = False
            state["turn_had_function_call"] = False
            state["current_response_done"] = False
            self.arm_silence_guard("user_turn")
            user_unintelligible = voice._voice_is_unintelligible(user_text)
            if user_unintelligible:
                interrupted = bool(state.get("was_interrupted"))
                state["was_interrupted"] = False
                if interrupted:
                    # Interrumpio pero no se le entendio: disculpa breve y ofrecer retomar,
                    # en vez de dejar que el modelo interprete la transcripcion basura.
                    await self._send_openai({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{
                                "type": "input_text",
                                "text": (
                                    "[sistema] El llamante te interrumpio pero no se ha entendido lo que ha dicho. "
                                    "No inventes ni te quedes en silencio: discúlpate brevemente ('perdona, no te he "
                                    "pillado bien') y pregunta si quiere que continues con lo que le estabas explicando, "
                                    "nombrandolo y retomando justo donde lo dejaste."
                                ),
                            }],
                        },
                    })
                    await self._send_openai({"type": "response.create"})
                    self.mark_response_active()
                    self.arm_silence_guard("interruption_recovery")
                else:
                    self.arm_silence_guard("unintelligible_user")
                return
            mutation_code = voice._voice_extract_booking_code_from_text(user_text)
            mutation_intent = voice._voice_mutation_intent_from_text(user_text)
            if mutation_code:
                state["pending_mutation_code"] = mutation_code
            if mutation_intent:
                state["pending_mutation_intent"] = mutation_intent
            # Interrupcion con texto entendible: el modelo la atiende de forma natural.
            state["was_interrupted"] = False
        elif etype == "response.output_item.added":
            item = event.get("item", {}) or {}
            if item.get("type") == "function_call" and item.get("call_id"):
                state["fn_names"][item["call_id"]] = item.get("name", "")
        elif etype == "response.function_call_arguments.done":
            await self._handle_function_call(event)
        elif etype == "response.done":
            await self._handle_response_done()
        elif etype == "input_audio_buffer.speech_started":
            truncated = await self._truncate_interrupted()
            if truncated:
                state["was_interrupted"] = True

    async def _handle_function_call(self, event: Dict[str, Any]) -> None:
        state = self.state
        cliente_id = self.cliente_id
        self.disarm_silence_guard()
        state["turn_had_function_call"] = True
        call_id = event.get("call_id", "")
        fname = event.get("name") or state["fn_names"].get(call_id, "")
        arguments_json = event.get("arguments", "") or "{}"
        try:
            tool_args = json.loads(arguments_json)
        except Exception:  # noqa: BLE001
            tool_args = {}
        if not isinstance(tool_args, dict):
            tool_args = {}
        if fname == "confirmar_cita" and state.get("outbound"):
            rid = state.get("outbound_booking_id")
            if rid:
                ok = booking._mark_booking_confirmed_by_customer(rid, cliente_id, channel="voice_outbound")
            else:
                ok = True
            if ok:
                state["outcome"] = "confirmada"
            result = {
                "ok": bool(ok),
                "confirmada": bool(ok),
                "mensaje_voz": (
                    "Perfecto, queda confirmada. Muchas gracias, que tenga buen dia."
                    if ok else "No he podido confirmar la cita ahora mismo. Lo revisara el equipo."
                ),
            }
        elif fname == "transferir_a_humano":
            result = await self._do_transfer()
        elif fname == "finalizar_llamada":
            state["should_end_call"] = True
            result = {"ok": True, "mensaje_voz": "Gracias por llamar. Que tenga un buen dia."}
        elif fname == "crear_cita":
            result = await self.create_booking_deduped(tool_args)
        else:
            result = await voice._voice_dispatch_tool(
                cliente_id, fname, arguments_json,
                from_number=state.get("from_number", ""),
                location_id=state.get("location_id", ""),
            )
        # (Antes aqui el puente reprogramaba solo al ver hueco libre. Ahora el modelo decide:
        # el prompt le indica llamar a reprogramar_cita, y abajo le damos la guia para hacerlo.)
        if fname == "crear_cita" and result.get("ok"):
            state["booked"] = True
            state["outcome"] = "reservada"
        if fname == "consultar_cita":
            parsed_code = str(tool_args.get("codigo_reserva", "")).strip()
            if parsed_code:
                state["pending_mutation_code"] = parsed_code
        if fname in {"cancelar_cita", "reprogramar_cita"} and result.get("ok"):
            state["outcome"] = "cancelada" if fname == "cancelar_cita" else "reprogramada"
            state["pending_mutation_code"] = ""
            state["pending_mutation_intent"] = ""
        await self._send_openai({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result, ensure_ascii=False),
            },
        })
        followup_prompt = voice._voice_tool_followup_prompt(fname, result)
        if (
            fname == "consultar_disponibilidad"
            and (state.get("pending_mutation_intent") or "") == "reschedule"
            and state.get("pending_mutation_code")
            and result.get("ok")
            and result.get("hora_disponible") is True
        ):
            followup_prompt = (
                "[sistema] Estas REPROGRAMANDO la cita "
                f"{state.get('pending_mutation_code')}: el hueco esta libre. NO pidas nombre ni "
                "telefono (la cita y el titular ya estan). Llama AHORA a reprogramar_cita con ese "
                "numero de reserva, la fecha y la hora; despues di que la cita queda cambiada."
            )
        state["pending_tool_followup_prompt"] = followup_prompt or ""
        state["pending_tool_name"] = fname
        state["pending_tool_result"] = result
        self.arm_silence_guard("tool_response")
        state["pending_tool_response"] = True
        if state.get("current_response_done"):
            state["pending_tool_response"] = False
            followup_prompt = state.get("pending_tool_followup_prompt") or ""
            state["pending_tool_followup_prompt"] = ""
            pending_name = str(state.get("pending_tool_name") or "")
            pending_result = state.get("pending_tool_result") or {}
            state["pending_tool_name"] = ""
            state["pending_tool_result"] = {}
            if should_force_tool_speech(pending_name, pending_result):
                await self.speak_forced_tool_result(pending_name, pending_result)
                return
            payload: Dict[str, Any] = {"type": "response.create"}
            if followup_prompt:
                payload["response"] = {"instructions": followup_prompt}
                state["turn_had_assistant_output"] = False
            await self._send_openai(payload)
            self.mark_response_active()
            self.arm_silence_guard("tool_followup")

    async def _handle_response_done(self) -> None:
        state = self.state
        self.mark_response_inactive()
        state["response_cancel_pending"] = False
        state["response_cancel_started_at"] = 0.0
        state["current_response_done"] = True
        if state.get("pending_tool_response"):
            # Latch tecnico: la respuesta de la function_call ya cerro; ahora el modelo puede
            # hablar su resultado (o seguir). Le pasamos la guia NATURAL del followup, no verbatim.
            state["pending_tool_response"] = False
            followup_prompt = state.get("pending_tool_followup_prompt") or ""
            state["pending_tool_followup_prompt"] = ""
            pending_name = str(state.get("pending_tool_name") or "")
            pending_result = state.get("pending_tool_result") or {}
            state["pending_tool_name"] = ""
            state["pending_tool_result"] = {}
            if should_force_tool_speech(pending_name, pending_result):
                await self.speak_forced_tool_result(pending_name, pending_result)
                return
            payload: Dict[str, Any] = {"type": "response.create"}
            if followup_prompt:
                payload["response"] = {"instructions": followup_prompt}
                state["turn_had_assistant_output"] = False
            await self._send_openai(payload)
            self.mark_response_active()
            self.arm_silence_guard("tool_followup")
        # Si el turno cerro sin audio y sin tool pendiente, el watchdog dara UN empujon interno
        # (maybe_recover_silence). No hay cascada de fallbacks deterministas aqui: el modelo manda.
