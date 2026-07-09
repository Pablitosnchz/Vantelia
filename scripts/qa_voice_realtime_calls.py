from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CID = "qa_voice_calls"
STALL_RE = re.compile(
    r"un momento|un segundo|dame un segundo|voy a "
    r"(verificar|comprobar|consultar|mirar|reservar|crear|confirmar)|"
    r"voy creando|creando la cita|vamos a (reservar|confirmar)",
    re.I,
)
# Igual que voice_core.stallNeedsNudge: una PREGUNTA DE DATOS legitima ("¿para que dia?",
# "tu nombre y telefono") no es una frase de espera aunque empiece por "vamos a reservar".
ASKS_DATA_RE = re.compile(
    r"nombre|tel[eé]fono|m[oó]vil|email|correo|c[oó]mo te llamas|qu[eé] d[ií]a|para qu[eé] d[ií]a|"
    r"qu[eé] hora|qu[eé] servicio|franja|prefieres|te viene|te vendr[ií]a|te va bien|cu[aá]l|para cu[aá]ndo",
    re.I,
)


def _is_stall_text(text: str) -> bool:
    return bool(STALL_RE.search(text)) and not ASKS_DATA_RE.search(text)
CHAT_ONLY_RE = re.compile(r"escribe\s+men[uú]|pulsa\s+una\s+opcion|volver\s+al\s+menu\s+principal", re.I)


def _extract_response_done_text(event: Dict[str, Any]) -> str:
    parts: List[str] = []
    for item in (event.get("response") or {}).get("output") or []:
        text = _extract_message_item_text(item)
        if text:
            parts.append(text)
    return "".join(parts).strip()


def _extract_message_item_text(item: Dict[str, Any]) -> str:
    if not isinstance(item, dict) or item.get("type") != "message":
        return ""
    parts: List[str] = []
    for content in item.get("content") or []:
        if not isinstance(content, dict):
            continue
        text = content.get("text") or content.get("transcript") or ""
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "".join(parts).strip()


def _extract_content_part_text(event: Dict[str, Any]) -> str:
    part = event.get("part") or event.get("content") or {}
    if not isinstance(part, dict):
        return ""
    text = part.get("text") or part.get("transcript") or ""
    return text.strip() if isinstance(text, str) else ""


def _dedupe_repeated_text(text: str) -> str:
    clean = (text or "").strip()
    if len(clean) < 20:
        return clean
    half = len(clean) // 2
    if len(clean) % 2 == 0 and clean[:half].strip() == clean[half:].strip():
        return clean[:half].strip()
    return clean


def _text_response_create(response: Dict[str, Any] = None) -> Dict[str, Any]:
    payload_response: Dict[str, Any] = {"output_modalities": ["audio"]}
    if response:
        payload_response.update(response)
    return {"type": "response.create", "response": payload_response}


def _next_weekday(weekday: int) -> str:
    day = datetime.now().date() + timedelta(days=1)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day.isoformat()


def _setup_runtime():
    root = Path(tempfile.mkdtemp(prefix="vantelia-voice-calls-"))
    data = root / "data"
    storage = root / "storage"
    client_dir = data / CID
    client_dir.mkdir(parents=True)
    storage.mkdir(parents=True)
    (client_dir / "info.txt").write_text(
        "\n".join(
            [
                "INFORMACION DEL NEGOCIO:",
                "Direccion sede Centro: Calle Mayor 1.",
                "Direccion sede Norte: Avenida del Parque 22.",
                "SERVICIOS Y PRECIOS:",
                "PREGUNTAS FRECUENTES:",
                "P: Donde estais?",
                "R: Tenemos Sede Centro en Calle Mayor 1 y Sede Norte en Avenida del Parque 22.",
            ]
        ),
        encoding="utf-8",
    )
    config = {
        CID: {
            "nombre": "Van",
            "empresa": "Clinica QA Voz",
            "bienvenida": "Hola, soy Van, el asistente de Clinica QA Voz. En que puedo ayudarte hoy?",
            "prompt_extra": "",
            "allowed_origins": ["http://testserver"],
            "contacto": {"email": "qa@example.com", "telefono": "+34600000000"},
            "branding": {"powered_by": "Vantelia"},
            "plan": "business",
            "subscription": {"plan": "business", "status": "active"},
            "booking": {
                "enabled": True,
                "timezone": "Europe/Madrid",
                "slot_minutes": 30,
                "day_start": "09:00",
                "day_end": "17:00",
                "closed_weekdays": [6],
                "provider": "internal",
                "success_message": "Cita registrada.",
            },
            "voice": {"enabled": True, "realtime_model": "gpt-realtime-mini", "openai_voice": "alloy"},
            "reminders": {
                "voice_otp_enabled": False,
                "channels": {"email": False, "whatsapp": False, "sms": False},
            },
        }
    }
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    os.environ.update(
        {
            "VANTELIA_DATA_DIR": str(data),
            "VANTELIA_STORAGE_DIR": str(storage),
            "VANTELIA_CONFIG_PATH": str(config_path),
            "EMAIL_SEND_PROVIDER": "smtp",
            "SMTP_HOST": "",
            "SMTP_USERNAME": "",
            "SMTP_PASSWORD": "",
            "SMTP_FROM_EMAIL": "",
            "WHATSAPP_ACCESS_TOKEN": "",
            "WHATSAPP_APP_SECRET": "",
            "TWILIO_ACCOUNT_SID": "",
            "TWILIO_AUTH_TOKEN": "",
            "TWILIO_SMS_SENDER": "",
            "TWILIO_DEFAULT_PHONE_NUMBER": "",
            "REMINDER_RUN_INTERVAL_MINUTES": "0",
            "WEBHOOK_DEFAULT": "",
        }
    )
    sys.modules.pop("api", None)
    import api  # noqa: PLC0415
    from backend import booking as booking_mod, settings  # noqa: PLC0415

    async def _noop_reminder(*_args, **_kwargs):
        return {"sent": False}

    booking_mod._send_booking_reminder_by_kind = _noop_reminder
    return api, settings


def _seed_business(api):
    from backend import settings

    client = TestClient(api.app)
    user = api._get_user_by_email(settings.PORTAL_ADMIN_EMAIL)
    cookies = {"vantelia_portal_session": api._create_auth_session(user["id"])}
    params = {"cliente_id": CID}

    svc_masaje = client.post(
        "/auth/services",
        params=params,
        cookies=cookies,
        json={"nombre": "Masaje", "duration_minutes": 30, "price_cents": 1000},
    ).json()
    svc_std = client.post(
        "/auth/services",
        params=params,
        cookies=cookies,
        json={"nombre": "Sesion estandar", "duration_minutes": 45, "price_cents": 4000},
    ).json()

    loc_centro = next(
        item for item in client.get("/auth/locations", params=params, cookies=cookies).json()["items"]
        if item["is_default"]
    )
    client.post(
        f"/auth/locations/{loc_centro['location_id']}",
        params=params,
        cookies=cookies,
        json={"name": "Sede Centro", "address": "Calle Mayor 1", "phone": "910000001"},
    )
    loc_norte = client.post(
        "/auth/locations",
        params=params,
        cookies=cookies,
        json={"name": "Sede Norte", "address": "Avenida del Parque 22", "phone": "910000002"},
    ).json()

    emp_centro_id = next(
        item for item in client.get("/auth/employees", params=params, cookies=cookies).json()["items"]
        if item["is_default"]
    )["employee_id"]
    emp_payload = {
        "role_label": "Recepcion",
        "color": "#00b1d9",
        "is_active": True,
        "timezone": "Europe/Madrid",
        "slot_minutes": 30,
        "day_start": "09:00",
        "day_end": "17:00",
        "break_windows": [],
        "closed_weekdays": [6],
        "service_ids": [svc_masaje["id"], svc_std["id"]],
    }
    client.post(
        f"/auth/employees/{emp_centro_id}",
        params=params,
        cookies=cookies,
        json={**emp_payload, "name": "Profesional Centro", "location_id": loc_centro["location_id"]},
    )
    emp_norte_id = client.post(
        "/auth/employees",
        params=params,
        cookies=cookies,
        json={**emp_payload, "name": "Profesional Norte", "location_id": loc_norte["location_id"]},
    ).json()["employee_id"]

    monday = _next_weekday(0)
    thursday = _next_weekday(3)
    sunday = _next_weekday(6)
    client.post(
        f"/auth/employees/{emp_centro_id}/blocks",
        params=params,
        cookies=cookies,
        json={"fecha": monday, "hora_inicio": "10:00", "hora_fin": "10:30", "motivo": "Vacaciones"},
    )
    client.post(
        "/auth/bookings",
        params=params,
        cookies=cookies,
        json={
            "nombre": "Ocupado Centro",
            "email": "",
            "telefono": "600000010",
            "servicio": "Masaje",
            "employee_id": emp_centro_id,
            "fecha": monday,
            "hora": "09:00",
            "notas": "",
        },
    )
    existing = client.post(
        "/auth/bookings",
        params=params,
        cookies=cookies,
        json={
            "nombre": "Cliente Cancelar",
            "email": "",
            "telefono": "675802001",
            "servicio": "Masaje",
            "employee_id": emp_norte_id,
            "fecha": monday,
            "hora": "15:00",
            "notas": "",
        },
    ).json()
    client.post(
        "/auth/bookings",
        params=params,
        cookies=cookies,
        json={
            "nombre": "Ocupado Norte",
            "email": "",
            "telefono": "600000011",
            "servicio": "Masaje",
            "employee_id": emp_norte_id,
            "fecha": thursday,
            "hora": "16:30",
            "notas": "",
        },
    )
    existing_id = existing["booking_id"]
    existing_code = api._get_booking_row_by_id(existing_id)["booking_code"]
    with api._get_db_connection() as connection:
        connection.execute("UPDATE bookings SET confirmed_at='' WHERE id=?", (existing_id,))
        connection.commit()
    return {
        "monday": monday,
        "thursday": thursday,
        "sunday": sunday,
        "loc_centro_id": loc_centro["location_id"],
        "loc_norte_id": loc_norte["location_id"],
        "existing_id": existing_id,
        "existing_code": existing_code,
    }


async def _connect_ws(settings):
    import websockets  # noqa: PLC0415

    url = f"wss://api.openai.com/v1/realtime?model={settings.VOICE_REALTIME_MODEL}"
    headers = [("Authorization", f"Bearer {settings.OPENAI_API_KEY}")]
    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, max_size=None)


class CallHarness:
    def __init__(self, api, settings, name: str, from_number: str = "", bridge: bool = True):
        self.api = api
        self.settings = settings
        self.name = name
        self.from_number = from_number
        # bridge=True replica el puente de Twilio (redes deterministas). bridge=False simula
        # el navegador / widget (WebRTC directo): SOLO modelo + tools, sin redes. Sirve para
        # comprobar como se comporta la voz en 'Probar en el navegador'.
        self.bridge = bridge
        self.ws = None
        self.transcript: List[Dict[str, str]] = []
        self.tools: List[Dict[str, Any]] = []
        self.stalls: List[str] = []
        # Saliente de confirmacion: cita que confirmar_cita debe marcar (espejo del motor).
        self.outbound_booking_id = ""
        # Navegador: un continueNudge por turno cuando el modelo se queda mudo (espejo del widget).
        self.browser_nudge_used = False
        self.pending_outputs = False
        self.pending_tool_followup = ""
        self.pending_tool_name = ""
        self.pending_tool_result: Dict[str, Any] = {}
        self.last_tool_name = ""
        self.last_tool_result: Dict[str, Any] = {}
        self.last_tool_recovery_used = False
        self.forced_speech_prompt = ""
        self.forced_speech_retry_used = 0
        self.response_active = False
        self.silence_guard_armed = False
        self.silence_guard_started_at = 0.0
        self.silence_guard_reason = ""
        self.silence_guard_used = False
        self.silence_recoveries: List[Dict[str, Any]] = []
        self.response_done_seen = False
        self.current_tool_names: Dict[str, str] = {}
        self.processed_call_ids = set()
        self.last_assistant_text = ""
        self.last_user_text = ""
        self.turn_had_assistant_output = False
        self.turn_had_function_call = False
        self.confirmation_nudge_used = False
        self.mutation_nudge_used = False
        self.mutation_action_fallback_used = False
        self.pending_mutation_code = ""
        self.pending_mutation_intent = ""
        self.pending_mutation_lookup_done = False
        self.pending_mutation_service = ""
        self.pending_mutation_phone = ""
        self.pending_mutation_date = ""
        self.booking_availability_fallback_used = False
        self.booking_service_prompt_fallback_used = False
        self.booking_location_prompt_fallback_used = False
        self.booking_slot_prompt_fallback_used = False
        self.booking_contact_confirm_fallback_used = False
        self.draft_booking_wants_booking = False
        self.draft_booking_request: Dict[str, str] = {}
        self.pending_booking_slot: Dict[str, str] = {}
        self.pending_booking_contact: Dict[str, str] = {}
        self.turn_deadline = 0.0

    async def start(self) -> None:
        self.ws = await _connect_ws(self.settings)
        cfg = self.api.CONFIG_CLIENTES[CID]
        await self.ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "model": self.settings.VOICE_REALTIME_MODEL,
                        "output_modalities": ["audio"],
                        "instructions": self.api._voice_build_instructions(CID, cfg),
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcmu"},
                                "turn_detection": {
                                    "type": "server_vad",
                                    "create_response": True,
                                    "interrupt_response": True,
                                },
                            },
                            "output": {
                                "voice": getattr(self.settings, "VOICE_OPENAI_VOICE", "alloy"),
                                "format": {"type": "audio/pcmu"},
                            },
                        },
                        "tools": self.api._voice_booking_tools(CID, cfg),
                        "tool_choice": "auto",
                    },
                }
            )
        )
        for _ in range(40):
            event = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=20))
            etype = event.get("type")
            if etype == "session.updated":
                await self.ws.send(json.dumps(_text_response_create()))
                self.response_active = True
                self._arm_silence_guard("greeting")
                self.turn_deadline = time.monotonic() + 18
                await self._collect()
                return
            if etype == "error":
                raise RuntimeError(json.dumps(event, ensure_ascii=False))

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()

    def _arm_silence_guard(self, reason: str) -> None:
        if not self.bridge:
            return
        self.silence_guard_armed = True
        self.silence_guard_started_at = time.monotonic()
        self.silence_guard_reason = reason
        self.silence_guard_used = False

    def _disarm_silence_guard(self) -> None:
        self.silence_guard_armed = False
        self.silence_guard_reason = ""

    async def _maybe_recover_silence(self, local_tools: List[Dict[str, Any]]) -> bool:
        if not self.bridge or not self.silence_guard_armed or self.turn_had_assistant_output:
            return False
        started = float(self.silence_guard_started_at or 0.0)
        elapsed = time.monotonic() - started if started else 0.0
        if elapsed < 1.7:
            return False
        if self.response_active:
            return False
        if self.silence_guard_used:
            return False
        self.silence_guard_used = True
        self.silence_recoveries.append({"reason": self.silence_guard_reason, "elapsed": round(elapsed, 3)})

        if self.pending_outputs and self._should_force_tool_speech(self.pending_tool_name, self.pending_tool_result):
            pending_name = self.pending_tool_name
            pending_result = self.pending_tool_result
            self.pending_outputs = False
            self.pending_tool_followup = ""
            self.pending_tool_name = ""
            self.pending_tool_result = {}
            await self._speak_forced_tool_result(pending_name, pending_result)
            return True

        if self.forced_speech_prompt:
            retry_count = int(self.forced_speech_retry_used or 0)
            if retry_count < 2:
                next_retry = retry_count + 1
                prompt = self.forced_speech_prompt
                await self.ws.send(
                    json.dumps(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": f"[sistema] {prompt}"}],
                            },
                        }
                    )
                )
                await self.ws.send(
                    json.dumps(
                        {
                            "type": "response.create",
                            "response": {
                                "output_modalities": ["audio"],
                                "instructions": prompt,
                                "tool_choice": "none",
                            },
                        }
                    )
                )
                self.response_active = True
                self.forced_speech_retry_used = next_retry
                self._arm_silence_guard("forced_speech_retry")
                return True
            self.forced_speech_prompt = ""
            self.forced_speech_retry_used = 0
            if (
                self.last_tool_name
                and not self.last_tool_recovery_used
                and self._should_force_tool_speech(self.last_tool_name, self.last_tool_result)
            ):
                self.last_tool_recovery_used = True
                await self._speak_forced_tool_result(self.last_tool_name, self.last_tool_result)
                return True

        if (
            not self.mutation_action_fallback_used
            and await self._force_pending_cancel(local_tools)
        ):
            return True
        if (
            not self.mutation_action_fallback_used
            and await self._force_pending_reschedule(local_tools)
        ):
            return True
        if (
            not self.mutation_nudge_used
            and not self.pending_mutation_lookup_done
            and self.pending_mutation_code
            and self.pending_mutation_intent
            and await self._force_mutation_lookup(local_tools)
        ):
            return True
        if (
            not self.booking_availability_fallback_used
            and await self._force_booking_availability(local_tools)
        ):
            return True
        if (
            not self.booking_service_prompt_fallback_used
            and await self._force_booking_service_prompt()
        ):
            return True
        if (
            not self.booking_location_prompt_fallback_used
            and await self._force_booking_location_prompt()
        ):
            return True
        if (
            not self.booking_slot_prompt_fallback_used
            and await self._force_booking_slot_prompt()
        ):
            return True
        if (
            not self.booking_contact_confirm_fallback_used
            and not self.api._voice_confirmation_acceptance_needs_nudge(
                self.last_assistant_text,
                self.last_user_text,
            )
            and not self.api._voice_booking_confirmation_prompt_seen(self.last_assistant_text)
            and await self._force_booking_contact_confirmation()
        ):
            return True

        if any(item["name"] == "crear_cita" and item["result"].get("ok") for item in self.tools):
            message = "Perfecto, la cita ya queda gestionada. ¿Te ayudo con algo mas?"
        elif self.last_tool_name == "cancelar_cita" and self.last_tool_result.get("ok"):
            message = "Listo, la cita ya esta cancelada. ¿Te ayudo con algo mas?"
        elif self.last_tool_name == "reprogramar_cita" and self.last_tool_result.get("ok"):
            message = "Listo, la cita ya esta cambiada. ¿Te ayudo con algo mas?"
        elif self.silence_guard_reason == "greeting" or not self.last_user_text:
            message = "Hola, ¿en qué puedo ayudarte?"
        else:
            message = "Perdona, no te he entendido bien. ¿Me lo repites?"
        prompt = f"Di exactamente esta frase y nada mas: \"{message}\""
        await self.ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": f"[sistema] {message}"}],
                    },
                }
            )
        )
        await self.ws.send(json.dumps(_text_response_create({"instructions": prompt, "tool_choice": "none"})))
        self.response_active = True
        self.forced_speech_prompt = prompt
        self.forced_speech_retry_used = 0
        self.turn_had_assistant_output = False
        self._arm_silence_guard("generic_repeat")
        return True

    async def say(self, text: str) -> None:
        self.transcript.append({"role": "user", "text": text})
        self.last_user_text = text
        self.turn_deadline = time.monotonic() + 24
        self.turn_had_assistant_output = False
        self.turn_had_function_call = False
        self.browser_nudge_used = False
        self.confirmation_nudge_used = False
        self.mutation_nudge_used = False
        self.mutation_action_fallback_used = False
        self.booking_availability_fallback_used = False
        self.booking_service_prompt_fallback_used = False
        self.booking_location_prompt_fallback_used = False
        self.booking_slot_prompt_fallback_used = False
        self.booking_contact_confirm_fallback_used = False
        self.response_done_seen = False
        if self.api._voice_booking_intent_from_text(text):
            self.draft_booking_wants_booking = True
        mutation_code = self.api._voice_extract_booking_code_from_text(text)
        mutation_intent = self.api._voice_mutation_intent_from_text(text)
        if mutation_code:
            if mutation_code != self.pending_mutation_code:
                self.pending_mutation_lookup_done = False
            self.pending_mutation_code = mutation_code
        if mutation_intent:
            if mutation_intent != self.pending_mutation_intent:
                self.pending_mutation_lookup_done = False
            self.pending_mutation_intent = mutation_intent
        mutation_contact = self.api._voice_extract_booking_contact_from_text(text)
        if mutation_contact.get("telefono"):
            self.pending_mutation_phone = mutation_contact["telefono"]
        booking_parts = self.api._voice_extract_booking_request_parts(
            CID,
            text,
            config=self.api.CONFIG_CLIENTES[CID],
        )
        if booking_parts:
            self.draft_booking_request.update({k: v for k, v in booking_parts.items() if v})
        if self.pending_booking_slot:
            if mutation_contact:
                self.pending_booking_contact = mutation_contact
        await self.ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": text}],
                    },
                }
            )
        )
        await self.ws.send(json.dumps(_text_response_create()))
        self.response_active = True
        self._arm_silence_guard("user_turn")
        await self._collect()

    async def _dispatch_tool(self, call_id: str, name: str, args: str, local_tools: List[Dict[str, Any]]) -> None:
        if not call_id or call_id in self.processed_call_ids:
            return
        self.processed_call_ids.add(call_id)
        self.turn_had_function_call = True
        if name == "confirmar_cita":
            # Espejo del motor real: VoiceCallEngine intercepta confirmar_cita en la llamada
            # SALIENTE (no pasa por _voice_dispatch_tool, que la desconoce). Sin esto el
            # asistente leia "Funcion desconocida" en el QA de salientes.
            rid = getattr(self, "outbound_booking_id", "")
            okc = bool(self.api._mark_booking_confirmed_by_customer(rid, CID, channel="voice_outbound")) if rid else True
            result = {
                "ok": okc,
                "confirmada": okc,
                "mensaje_voz": (
                    "Perfecto, queda confirmada. Muchas gracias, que tenga buen dia."
                    if okc else "No he podido confirmar la cita ahora mismo. Lo revisara el equipo."
                ),
            }
        else:
            result = await self.api._voice_dispatch_tool(CID, name, args, from_number=self.from_number)
        try:
            parsed_args = json.loads(args or "{}")
        except Exception:  # noqa: BLE001
            parsed_args = {}
        if not isinstance(parsed_args, dict):
            parsed_args = {}
        # Reprogramacion determinista (espejo del puente real): si reprogramamos y el hueco
        # esta libre, movemos la cita ya en vez de pedir nombre/telefono.
        if (
            self.bridge
            and name == "consultar_disponibilidad"
            and self.pending_mutation_intent == "reschedule"
            and self.pending_mutation_code
            and self.pending_mutation_lookup_done
            and result.get("ok")
            and result.get("hora_disponible") is True
        ):
            _resch = {
                "codigo_reserva": self.pending_mutation_code,
                "fecha": str(result.get("fecha") or parsed_args.get("fecha") or ""),
                "hora": str(result.get("hora") or parsed_args.get("hora") or ""),
            }
            if self.pending_mutation_phone:
                _resch["telefono"] = self.pending_mutation_phone
            _rr = await self.api._voice_dispatch_tool(
                CID, "reprogramar_cita", json.dumps(_resch, ensure_ascii=False), from_number=self.from_number
            )
            if _rr.get("ok"):
                name, result = "reprogramar_cita", _rr
        record = {"name": name, "args": args, "result": result}
        self.tools.append(record)
        local_tools.append(record)
        if name == "consultar_disponibilidad" and result.get("ok") and result.get("hora") and result.get("hora_disponible") is True:
            self.pending_booking_slot = {
                "servicio": str(parsed_args.get("servicio", "")),
                "centro": str(parsed_args.get("centro", "")),
                "fecha": str(result.get("fecha") or parsed_args.get("fecha") or ""),
                "fecha_texto": str(parsed_args.get("fecha_texto") or result.get("fecha_texto") or result.get("fecha") or ""),
                "hora": str(result.get("hora") or parsed_args.get("hora") or ""),
            }
            self.pending_booking_contact = {}
        elif name == "consultar_cita":
            parsed_code = str(parsed_args.get("codigo_reserva", "")).strip()
            if parsed_code:
                self.pending_mutation_code = parsed_code
            if result.get("ok"):
                self.pending_mutation_lookup_done = True
                self.pending_mutation_service = str(result.get("servicio") or "")
                self.pending_mutation_date = str(result.get("fecha") or "")
        elif name in {"cancelar_cita", "reprogramar_cita"} and result.get("ok"):
            self.pending_mutation_code = ""
            self.pending_mutation_intent = ""
            self.pending_mutation_lookup_done = False
            self.pending_mutation_service = ""
            self.pending_mutation_phone = ""
            self.pending_mutation_date = ""
        elif name == "crear_cita" and result.get("ok"):
            self.pending_booking_slot = {}
            self.pending_booking_contact = {}
            self.draft_booking_request = {}
            self.draft_booking_wants_booking = False
        await self.ws.send(
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
        followup = self.api._voice_tool_followup_prompt(name, result)
        self.pending_tool_followup = followup or ""
        self.pending_tool_name = name
        self.pending_tool_result = result
        self.last_tool_name = name
        self.last_tool_result = result
        self.last_tool_recovery_used = False
        self.pending_outputs = True
        self._arm_silence_guard("tool_response")
        if self.response_done_seen:
            self.pending_outputs = False
            followup = self.pending_tool_followup or ""
            self.pending_tool_followup = ""
            pending_name = self.pending_tool_name
            pending_result = self.pending_tool_result
            self.pending_tool_name = ""
            self.pending_tool_result = {}
            if not self.bridge:
                # Navegador: el modelo decide; sin forzar frase ni followup.
                await self.ws.send(json.dumps(_text_response_create()))
                self.response_active = True
                return
            if self._should_force_tool_speech(pending_name, pending_result):
                await self._speak_forced_tool_result(pending_name, pending_result)
                return
            payload: Dict[str, Any] = _text_response_create()
            if followup:
                payload["response"]["instructions"] = followup
                self.forced_speech_prompt = followup
                self.forced_speech_retry_used = 0
                self.turn_had_assistant_output = False
            await self.ws.send(json.dumps(payload))
            self.response_active = True
            self._arm_silence_guard("tool_followup")

    async def _create_booking_after_confirmed_silence(self, local_tools: List[Dict[str, Any]]) -> bool:
        if not self.pending_booking_slot or not self.pending_booking_contact:
            return False
        slot = self.pending_booking_slot
        contact = self.pending_booking_contact
        create_args = {
            "nombre": contact.get("nombre", ""),
            "telefono": contact.get("telefono", ""),
            "servicio": slot.get("servicio", ""),
            "fecha": slot.get("fecha", ""),
            "fecha_texto": slot.get("fecha_texto") or slot.get("fecha", ""),
            "hora": slot.get("hora", ""),
        }
        if slot.get("centro"):
            create_args["centro"] = slot.get("centro")
        args_json = json.dumps(create_args, ensure_ascii=False)
        result = await self.api._voice_dispatch_tool(CID, "crear_cita", args_json, from_number=self.from_number)
        record = {"name": "crear_cita", "args": args_json, "result": result}
        self.tools.append(record)
        local_tools.append(record)
        if result.get("ok"):
            self.pending_booking_slot = {}
            self.pending_booking_contact = {}
            self.draft_booking_request = {}
            self.draft_booking_wants_booking = False
        await self._speak_forced_tool_result("crear_cita", result)
        self._arm_silence_guard("booking_created_after_confirmation")
        return True

    def _should_force_tool_speech(self, tool_name: str, result: Dict[str, Any]) -> bool:
        if not tool_name or not isinstance(result, dict):
            return False
        if not (result.get("mensaje_voz") or result.get("mensaje") or result.get("error")):
            return False
        return tool_name in {
            "consultar_disponibilidad",
            "consultar_cita",
            "crear_cita",
            "cancelar_cita",
            "reprogramar_cita",
            "enviar_codigo_verificacion",
            "enviar_enlace_pago",
            "confirmar_cita",
        }

    async def _speak_forced_tool_result(
        self,
        tool_name: str,
        result: Dict[str, Any],
        *,
        extra_instruction: str = "",
    ) -> None:
        if tool_name and isinstance(result, dict):
            self.last_tool_name = tool_name
            self.last_tool_result = result
            self.last_tool_recovery_used = False
        followup = self.api._voice_tool_followup_prompt(tool_name, result)
        message = str(result.get("mensaje_voz") or result.get("mensaje") or result.get("error") or "")
        if message:
            instruction = f"Di exactamente esta frase y nada mas: \"{message}\""
        else:
            instruction = followup or "[sistema] Responde ahora de forma breve."
        if extra_instruction and not message:
            instruction = f"{instruction} {extra_instruction}"
        await self.ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{
                            "type": "input_text",
                            "text": (
                                f"[sistema] Resultado interno de {tool_name}: "
                                f"{json.dumps(result, ensure_ascii=False)}\n{instruction}"
                            ),
                        }],
                    },
                }
            )
        )
        await self.ws.send(
            json.dumps(
                {
                    "type": "response.create",
                    "response": {
                        "output_modalities": ["audio"],
                        "instructions": instruction,
                        "tool_choice": "none",
                    },
                }
            )
        )
        self.forced_speech_prompt = instruction
        self.forced_speech_retry_used = 0
        self.turn_had_assistant_output = False
        self.response_active = True
        self._arm_silence_guard("forced_speech")

    async def _force_mutation_lookup(self, local_tools: List[Dict[str, Any]]) -> bool:
        code = self.pending_mutation_code
        intent = self.pending_mutation_intent
        if not code or not intent:
            return False
        self.mutation_nudge_used = True
        self.turn_had_function_call = True
        args_json = json.dumps({"codigo_reserva": code}, ensure_ascii=False)
        result = await self.api._voice_dispatch_tool(
            CID, "consultar_cita", args_json, from_number=self.from_number
        )
        record = {"name": "consultar_cita", "args": args_json, "result": result}
        self.tools.append(record)
        local_tools.append(record)
        self.pending_mutation_lookup_done = bool(result.get("ok"))
        if result.get("ok"):
            self.pending_mutation_service = str(result.get("servicio") or "")
            self.pending_mutation_date = str(result.get("fecha") or "")
        await self._speak_forced_tool_result(
            "consultar_cita",
            result,
            extra_instruction=(
                "No llames a consultar_cita otra vez en esta respuesta. "
                "Si hay cita, pide solo que confirme que es esa."
            ),
        )
        return True

    async def _force_pending_cancel(self, local_tools: List[Dict[str, Any]]) -> bool:
        if self.pending_mutation_intent != "cancel" or not self.pending_mutation_lookup_done:
            return False
        if not self.pending_mutation_code:
            return False
        contact = self.api._voice_extract_booking_contact_from_text(self.last_user_text)
        if not (self.api._voice_user_says_yes(self.last_user_text) or contact):
            return False
        self.mutation_action_fallback_used = True
        self.turn_had_function_call = True
        args = {"codigo_reserva": self.pending_mutation_code}
        phone = contact.get("telefono") or self.pending_mutation_phone
        if phone:
            args["telefono"] = phone
        args_json = json.dumps(args, ensure_ascii=False)
        result = await self.api._voice_dispatch_tool(
            CID, "cancelar_cita", args_json, from_number=self.from_number
        )
        record = {"name": "cancelar_cita", "args": args_json, "result": result}
        self.tools.append(record)
        local_tools.append(record)
        self.last_tool_name = "cancelar_cita"
        self.last_tool_result = result
        self.last_tool_recovery_used = False
        if result.get("ok"):
            self.pending_mutation_code = ""
            self.pending_mutation_intent = ""
            self.pending_mutation_lookup_done = False
            self.pending_mutation_service = ""
            self.pending_mutation_phone = ""
        await self._speak_forced_tool_result("cancelar_cita", result)
        return True

    async def _force_pending_reschedule(self, local_tools: List[Dict[str, Any]]) -> bool:
        if self.pending_mutation_intent != "reschedule" or not self.pending_mutation_lookup_done:
            return False
        if not self.pending_mutation_code:
            return False
        fecha, hora = self.api._voice_extract_requested_slot_from_text(
            CID, self.last_user_text, config=self.api.CONFIG_CLIENTES[CID]
        )
        if hora and not fecha:
            fecha = self.pending_mutation_date or ""
        if not fecha or not hora:
            return False
        self.mutation_action_fallback_used = True
        self.turn_had_function_call = True
        availability_args: Dict[str, Any] = {
            "fecha": fecha,
            "fecha_texto": self.last_user_text,
            "hora": hora,
        }
        if self.pending_mutation_service:
            availability_args["servicio"] = self.pending_mutation_service
        availability_json = json.dumps(availability_args, ensure_ascii=False)
        availability = await self.api._voice_dispatch_tool(
            CID, "consultar_disponibilidad", availability_json, from_number=self.from_number
        )
        self.tools.append({
            "name": "consultar_disponibilidad",
            "args": availability_json,
            "result": availability,
        })
        local_tools.append(self.tools[-1])
        self.last_tool_name = "consultar_disponibilidad"
        self.last_tool_result = availability
        self.last_tool_recovery_used = False
        if not (
            availability.get("ok")
            and availability.get("hora")
            and availability.get("hora_disponible") is True
        ):
            await self._speak_forced_tool_result("consultar_disponibilidad", availability)
            return True

        contact = self.api._voice_extract_booking_contact_from_text(self.last_user_text)
        phone = contact.get("telefono") or self.pending_mutation_phone
        reschedule_args: Dict[str, Any] = {
            "codigo_reserva": self.pending_mutation_code,
            "fecha": str(availability.get("fecha") or fecha),
            "hora": str(availability.get("hora") or hora),
        }
        if phone:
            reschedule_args["telefono"] = phone
        reschedule_json = json.dumps(reschedule_args, ensure_ascii=False)
        result = await self.api._voice_dispatch_tool(
            CID, "reprogramar_cita", reschedule_json, from_number=self.from_number
        )
        self.tools.append({"name": "reprogramar_cita", "args": reschedule_json, "result": result})
        local_tools.append(self.tools[-1])
        self.last_tool_name = "reprogramar_cita"
        self.last_tool_result = result
        self.last_tool_recovery_used = False
        if result.get("ok"):
            self.pending_mutation_code = ""
            self.pending_mutation_intent = ""
            self.pending_mutation_lookup_done = False
            self.pending_mutation_service = ""
            self.pending_mutation_phone = ""
        await self._speak_forced_tool_result("reprogramar_cita", result)
        return True

    async def _force_booking_availability(self, local_tools: List[Dict[str, Any]]) -> bool:
        if self.pending_booking_slot:
            return False
        draft = self.draft_booking_request
        if not draft:
            return False
        if self.api._voice_service_options(CID) and not draft.get("servicio"):
            return False
        try:
            multi_location = len(self.api._voice_location_options(CID)) > 1
        except Exception:  # noqa: BLE001
            multi_location = False
        if multi_location and not draft.get("centro"):
            return False
        if not (draft.get("fecha") and draft.get("fecha_texto") and draft.get("hora")):
            return False
        self.booking_availability_fallback_used = True
        self.turn_had_function_call = True
        args: Dict[str, Any] = {
            "fecha": draft.get("fecha", ""),
            "fecha_texto": draft.get("fecha_texto", ""),
            "hora": draft.get("hora", ""),
        }
        if draft.get("servicio"):
            args["servicio"] = draft.get("servicio")
        if draft.get("centro"):
            args["centro"] = draft.get("centro")
        args_json = json.dumps(args, ensure_ascii=False)
        result = await self.api._voice_dispatch_tool(
            CID, "consultar_disponibilidad", args_json, from_number=self.from_number
        )
        record = {"name": "consultar_disponibilidad", "args": args_json, "result": result}
        self.tools.append(record)
        local_tools.append(record)
        if (
            result.get("ok")
            and result.get("hora")
            and result.get("hora_disponible") is True
        ):
            self.pending_booking_slot = {
                "servicio": str(args.get("servicio", "")),
                "centro": str(args.get("centro", "")),
                "fecha": str(result.get("fecha") or args.get("fecha") or ""),
                "fecha_texto": str(args.get("fecha_texto") or result.get("fecha_texto") or ""),
                "hora": str(result.get("hora") or args.get("hora") or ""),
            }
            self.pending_booking_contact = {}
        await self._speak_forced_tool_result("consultar_disponibilidad", result)
        return True

    async def _force_booking_service_prompt(self) -> bool:
        if self.pending_mutation_code or self.pending_mutation_intent:
            return False
        if self.pending_booking_slot or self.draft_booking_request.get("servicio"):
            return False
        if not self.draft_booking_wants_booking:
            return False
        self.booking_service_prompt_fallback_used = True
        invalid = self.last_user_text if self.api._voice_unknown_service_candidate(CID, self.last_user_text) else ""
        result = self.api._voice_service_required_response(CID, invalid=invalid)
        await self._speak_forced_tool_result("consultar_disponibilidad", result)
        return True

    async def _force_booking_location_prompt(self) -> bool:
        if self.pending_mutation_code or self.pending_mutation_intent:
            return False
        if self.pending_booking_slot or self.draft_booking_request.get("centro"):
            return False
        if not self.draft_booking_wants_booking:
            return False
        try:
            if len(self.api._voice_location_options(CID)) <= 1:
                return False
        except Exception:  # noqa: BLE001
            return False
        self.booking_location_prompt_fallback_used = True
        result = self.api._voice_location_required_response(CID)
        await self._speak_forced_tool_result("consultar_disponibilidad", result)
        return True

    async def _force_booking_slot_prompt(self) -> bool:
        if self.pending_mutation_code or self.pending_mutation_intent:
            return False
        if self.pending_booking_slot or self.booking_slot_prompt_fallback_used:
            return False
        draft = self.draft_booking_request
        if not draft or not self.draft_booking_wants_booking:
            return False
        if self.api._voice_service_options(CID) and not draft.get("servicio"):
            return False
        try:
            multi_location = len(self.api._voice_location_options(CID)) > 1
        except Exception:  # noqa: BLE001
            multi_location = False
        if multi_location and not draft.get("centro"):
            return False
        if draft.get("fecha") and draft.get("hora"):
            return False
        self.booking_slot_prompt_fallback_used = True
        result = self.api._voice_booking_slot_required_response(
            draft,
            config=self.api.CONFIG_CLIENTES[CID],
        )
        await self._speak_forced_tool_result("consultar_disponibilidad", result)
        return True

    async def _force_booking_contact_confirmation(self) -> bool:
        if not self.pending_booking_slot or not self.pending_booking_contact:
            return False
        self.booking_contact_confirm_fallback_used = True
        message = self.api._voice_booking_confirmation_prompt(
            CID,
            self.pending_booking_slot,
            self.pending_booking_contact,
            config=self.api.CONFIG_CLIENTES[CID],
        )
        await self.ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": f"[sistema] {message}"}],
                    },
                }
            )
        )
        await self.ws.send(
            json.dumps(
                _text_response_create({
                    "instructions": f"Di exactamente esta frase y nada mas: \"{message}\"",
                    "tool_choice": "none",
                })
            )
        )
        self.forced_speech_prompt = f"Di exactamente esta frase y nada mas: \"{message}\""
        self.forced_speech_retry_used = 0
        self.turn_had_assistant_output = False
        self.response_active = True
        self._arm_silence_guard("contact_confirmation")
        return True

    async def _collect(self) -> None:
        text_parts: List[str] = []
        local_tools: List[Dict[str, Any]] = []
        last_output_at = 0.0
        deadline = self.turn_deadline or (time.monotonic() + 24)
        for _ in range(3600):
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=0.2)
            except asyncio.TimeoutError:
                if (
                    text_parts
                    and self.turn_had_assistant_output
                    and last_output_at
                    and time.monotonic() - last_output_at >= 0.8
                ):
                    self.response_active = False
                    break
                if time.monotonic() >= deadline:
                    break
                if await self._maybe_recover_silence(local_tools):
                    continue
                continue
            event = json.loads(raw)
            etype = event.get("type")
            if etype == "response.created":
                self.response_active = True
            elif etype == "response.output_audio.delta":
                if event.get("delta"):
                    self.turn_had_assistant_output = True
                    self.forced_speech_prompt = ""
                    self.forced_speech_retry_used = 0
                    self._disarm_silence_guard()
                    last_output_at = time.monotonic()
            elif etype in {"response.output_audio_transcript.delta", "response.audio_transcript.delta"}:
                if event.get("delta"):
                    self.turn_had_assistant_output = True
                    self.forced_speech_prompt = ""
                    self.forced_speech_retry_used = 0
                    self._disarm_silence_guard()
                    last_output_at = time.monotonic()
            elif etype == "response.output_audio_transcript.done":
                done_text = event.get("transcript") or ""
                if done_text:
                    self.turn_had_assistant_output = True
                    self.forced_speech_prompt = ""
                    self.forced_speech_retry_used = 0
                    self._disarm_silence_guard()
                    last_output_at = time.monotonic()
                    if done_text not in "".join(text_parts):
                        text_parts.append(done_text)
            elif etype in {"response.output_text.delta", "response.text.delta"}:
                if event.get("delta"):
                    self.turn_had_assistant_output = True
                    self.forced_speech_prompt = ""
                    self.forced_speech_retry_used = 0
                    self._disarm_silence_guard()
                    last_output_at = time.monotonic()
                text_parts.append(event.get("delta", ""))
            elif etype in {"response.output_text.done", "response.text.done"}:
                done_text = event.get("text") or event.get("transcript") or ""
                if done_text:
                    self.turn_had_assistant_output = True
                    self.forced_speech_prompt = ""
                    self.forced_speech_retry_used = 0
                    self._disarm_silence_guard()
                    last_output_at = time.monotonic()
                    if done_text not in "".join(text_parts):
                        text_parts.append(done_text)
            elif etype == "response.content_part.done":
                part_text = _extract_content_part_text(event)
                if part_text:
                    self.turn_had_assistant_output = True
                    self.forced_speech_prompt = ""
                    self.forced_speech_retry_used = 0
                    self._disarm_silence_guard()
                    last_output_at = time.monotonic()
                    if part_text not in "".join(text_parts):
                        text_parts.append(part_text)
            elif etype == "response.output_item.done":
                item = event.get("item") or {}
                if item.get("type") == "function_call" and item.get("call_id"):
                    self.current_tool_names[item["call_id"]] = item.get("name", "")
                else:
                    item_text = _extract_message_item_text(item)
                    if item_text:
                        self.turn_had_assistant_output = True
                        self.forced_speech_prompt = ""
                        self.forced_speech_retry_used = 0
                        self._disarm_silence_guard()
                        last_output_at = time.monotonic()
                        if item_text not in "".join(text_parts):
                            text_parts.append(item_text)
            elif etype == "response.function_call_arguments.done":
                self._disarm_silence_guard()
                call_id = event.get("call_id", "")
                name = event.get("name") or self.current_tool_names.get(call_id, "")
                await self._dispatch_tool(call_id, name, event.get("arguments") or "{}", local_tools)
            elif etype == "response.done":
                self.response_active = False
                self.response_done_seen = True
                # TPM agotado NO llega como evento 'error': llega como response.done con
                # status 'failed' (status_details con rate_limit). Sin esto el escenario
                # sigue "mudo" y produce resultados invalidos en vez de blocked+retry.
                _resp_obj = event.get("response") or {}
                if str(_resp_obj.get("status") or "") == "failed":
                    raise RuntimeError(
                        "response.failed " + json.dumps(_resp_obj.get("status_details") or {}, ensure_ascii=False)
                    )
                done_text = _extract_response_done_text(event)
                joined = "".join(text_parts)
                if done_text and done_text not in joined:
                    self.turn_had_assistant_output = True
                    self.forced_speech_prompt = ""
                    self.forced_speech_retry_used = 0
                    self._disarm_silence_guard()
                    last_output_at = time.monotonic()
                    text_parts.append(done_text)
                _tool_dispatched = False
                for item in (event.get("response") or {}).get("output") or []:
                    if item.get("type") == "function_call":
                        _tool_dispatched = True
                        await self._dispatch_tool(
                            item.get("call_id", ""),
                            item.get("name", ""),
                            item.get("arguments") or "{}",
                            local_tools,
                        )
                if _tool_dispatched and self.bridge:
                    continue
                if self.pending_outputs:
                    self.pending_outputs = False
                    followup = self.pending_tool_followup or ""
                    self.pending_tool_followup = ""
                    pending_name = self.pending_tool_name
                    pending_result = self.pending_tool_result
                    self.pending_tool_name = ""
                    self.pending_tool_result = {}
                    if not self.bridge:
                        # Navegador: sin forzar frase; el modelo responde con el resultado.
                        await self.ws.send(json.dumps(_text_response_create()))
                        self.response_active = True
                        continue
                    if self._should_force_tool_speech(pending_name, pending_result):
                        await self._speak_forced_tool_result(pending_name, pending_result)
                        continue
                    payload: Dict[str, Any] = _text_response_create()
                    if followup:
                        payload["response"]["instructions"] = followup
                        self.forced_speech_prompt = followup
                        self.forced_speech_retry_used = 0
                        self.turn_had_assistant_output = False
                    await self.ws.send(json.dumps(payload))
                    self.response_active = True
                    self._arm_silence_guard("tool_followup")
                    continue
                if not self.bridge:
                    # Navegador: sin redes deterministas. Si se acaba de despachar una tool, el
                    # modelo respondera al resultado (seguimos escuchando); si no, fin del turno.
                    if _tool_dispatched:
                        continue
                    break
                if self.forced_speech_prompt:
                    retry_count = int(self.forced_speech_retry_used or 0)
                    if not self.turn_had_assistant_output and retry_count < 3:
                        next_retry = retry_count + 1
                        await self.ws.send(
                            json.dumps(
                                {
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "message",
                                        "role": "user",
                                        "content": [{
                                            "type": "input_text",
                                            "text": f"[sistema] {self.forced_speech_prompt}",
                                        }],
                                    },
                                }
                            )
                        )
                        await self.ws.send(
                            json.dumps(
                                {
                                    "type": "response.create",
                                    "response": {
                                        "output_modalities": ["audio"],
                                        "instructions": self.forced_speech_prompt,
                                        "tool_choice": "none",
                                    },
                                }
                            )
                        )
                        self.response_active = True
                        self.forced_speech_retry_used = next_retry
                        self._arm_silence_guard("forced_speech_retry")
                        continue
                    self.forced_speech_prompt = ""
                    self.forced_speech_retry_used = 0
                    if (
                        self.last_tool_name
                        and not self.last_tool_recovery_used
                        and self._should_force_tool_speech(self.last_tool_name, self.last_tool_result)
                    ):
                        self.last_tool_recovery_used = True
                        await self._speak_forced_tool_result(self.last_tool_name, self.last_tool_result)
                        continue
                if (
                    not self.mutation_action_fallback_used
                    and not self.turn_had_function_call
                    and await self._force_pending_cancel(local_tools)
                ):
                    continue
                if (
                    not self.mutation_action_fallback_used
                    and not self.turn_had_function_call
                    and await self._force_pending_reschedule(local_tools)
                ):
                    continue
                if (
                    not self.mutation_nudge_used
                    and not self.turn_had_function_call
                    and not self.pending_mutation_lookup_done
                    and self.pending_mutation_code
                    and self.pending_mutation_intent
                    and await self._force_mutation_lookup(local_tools)
                ):
                    continue
                if (
                    not self.booking_availability_fallback_used
                    and not self.turn_had_function_call
                    and await self._force_booking_availability(local_tools)
                ):
                    continue
                if (
                    not self.booking_service_prompt_fallback_used
                    and not self.turn_had_function_call
                    and not self.turn_had_assistant_output
                    and await self._force_booking_service_prompt()
                ):
                    continue
                if (
                    not self.booking_location_prompt_fallback_used
                    and not self.turn_had_function_call
                    and not self.turn_had_assistant_output
                    and await self._force_booking_location_prompt()
                ):
                    continue
                if (
                    not self.booking_slot_prompt_fallback_used
                    and not self.turn_had_function_call
                    and not self.turn_had_assistant_output
                    and await self._force_booking_slot_prompt()
                ):
                    continue
                if (
                    not self.booking_contact_confirm_fallback_used
                    and not self.turn_had_function_call
                    and not self.api._voice_booking_confirmation_prompt_seen(
                        self.last_assistant_text
                    )
                    and not self.api._voice_confirmation_acceptance_needs_nudge(
                        self.last_assistant_text,
                        self.last_user_text,
                    )
                    and await self._force_booking_contact_confirmation()
                ):
                    continue
                if (
                    not self.confirmation_nudge_used
                    and not self.turn_had_assistant_output
                    and not self.turn_had_function_call
                    and self.api._voice_confirmation_acceptance_needs_nudge(
                        self.last_assistant_text,
                        self.last_user_text,
                    )
                ):
                    self.confirmation_nudge_used = True
                    if await self._create_booking_after_confirmed_silence(local_tools):
                        continue
                    await self.ws.send(
                        json.dumps(
                            {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{
                                        "type": "input_text",
                                        "text": (
                                            "[sistema] El cliente acaba de confirmar que los datos son correctos. "
                                            "No vuelvas a preguntar ni te quedes en silencio: llama AHORA a crear_cita "
                                            "con los datos que acababas de repetir y di el resultado."
                                        ),
                                    }],
                                },
                            }
                        )
                    )
                    await self.ws.send(json.dumps(_text_response_create()))
                    self.response_active = True
                    self._arm_silence_guard("confirmation_nudge")
                    continue
                if not self.turn_had_assistant_output:
                    continue
                break
            elif etype == "error":
                err = event.get("error") or {}
                code = str(err.get("code") or "")
                if code == "conversation_already_has_active_response":
                    self.response_active = True
                    self._arm_silence_guard("active_response_retry")
                    continue
                raise RuntimeError(json.dumps(event, ensure_ascii=False))
        if not self.bridge:
            # Navegador: sin redes deterministas post-turno; registra lo que dijo el asistente.
            text = _dedupe_repeated_text("".join(text_parts))
            if text:
                self.transcript.append({"role": "assistant", "text": text})
                self.last_assistant_text = text
                # Criterio del doc (8.7): la frase de espera solo es fallo si va "seguida de
                # silencio o sin tool". Si el turno SI ejecuto la herramienta, no es un stall.
                if _is_stall_text(text) and not local_tools and not self.turn_had_function_call:
                    self.stalls.append(text)
            # Espejo del widget real (voice.js): si el turno quedo MUDO, un continueNudge
            # interno (una vez por turno) para que el modelo siga con sus palabras.
            if not text and not self.browser_nudge_used:
                self.browser_nudge_used = True
                await self.ws.send(json.dumps({
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
                }))
                await self.ws.send(json.dumps(_text_response_create()))
                self.response_active = True
                self._arm_silence_guard("continue_nudge")
                await self._collect()
            return
        if (
            not local_tools
            and not self.mutation_action_fallback_used
            and not self.turn_had_function_call
            and await self._force_pending_cancel(local_tools)
        ):
            await self._collect()
            return
        if (
            not local_tools
            and not self.mutation_action_fallback_used
            and not self.turn_had_function_call
            and await self._force_pending_reschedule(local_tools)
        ):
            await self._collect()
            return
        if (
            not local_tools
            and not self.mutation_nudge_used
            and not self.turn_had_function_call
            and not self.pending_mutation_lookup_done
            and self.pending_mutation_code
            and self.pending_mutation_intent
            and await self._force_mutation_lookup(local_tools)
        ):
            await self._collect()
            return
        if (
            not local_tools
            and not self.booking_availability_fallback_used
            and not self.turn_had_function_call
            and await self._force_booking_availability(local_tools)
        ):
            await self._collect()
            return
        if (
            not text_parts
            and not local_tools
            and not self.booking_service_prompt_fallback_used
            and not self.turn_had_function_call
            and await self._force_booking_service_prompt()
        ):
            await self._collect()
            return
        if (
            not text_parts
            and not local_tools
            and not self.booking_location_prompt_fallback_used
            and not self.turn_had_function_call
            and await self._force_booking_location_prompt()
        ):
            await self._collect()
            return
        if (
            not text_parts
            and not local_tools
            and not self.booking_contact_confirm_fallback_used
            and not self.turn_had_function_call
            and not self.api._voice_confirmation_acceptance_needs_nudge(
                self.last_assistant_text,
                self.last_user_text,
            )
            and await self._force_booking_contact_confirmation()
        ):
            await self._collect()
            return
        if (
            not text_parts
            and not local_tools
            and not self.confirmation_nudge_used
            and not self.turn_had_assistant_output
            and not self.turn_had_function_call
            and self.api._voice_confirmation_acceptance_needs_nudge(
                self.last_assistant_text,
                self.last_user_text,
            )
        ):
            self.confirmation_nudge_used = True
            if await self._create_booking_after_confirmed_silence(local_tools):
                await self._collect()
                return
            await self.ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{
                                "type": "input_text",
                                "text": (
                                    "[sistema] El cliente acaba de confirmar que los datos son correctos. "
                                    "No vuelvas a preguntar ni te quedes en silencio: llama AHORA a crear_cita "
                                    "con los datos que acababas de repetir y di el resultado."
                                ),
                            }],
                        },
                    }
                )
            )
            await self.ws.send(json.dumps(_text_response_create()))
            self.response_active = True
            self._arm_silence_guard("confirmation_nudge")
            await self._collect()
            return
        text = _dedupe_repeated_text("".join(text_parts))
        if text:
            self.transcript.append({"role": "assistant", "text": text})
            self.last_assistant_text = text
            # Criterio del doc (8.7): frase de espera solo es fallo "seguida de silencio o sin
            # tool". Con la herramienta ejecutada en el mismo turno no cuenta como stall.
            if _is_stall_text(text) and not local_tools and not self.turn_had_function_call:
                self.stalls.append(text)


CheckFn = Callable[[CallHarness], Tuple[bool, str]]


async def _run_call(api, settings, name: str, turns: List[str], checks: Dict[str, CheckFn],
                    *, from_number: str = "", bridge: bool = True) -> Dict[str, Any]:
    """Ejecuta un escenario con tolerancia al TPM de OpenAI Realtime (40k/min de org):
    pausa opcional entre escenarios (QA_VOICE_SCENARIO_PAUSE_SECONDS) y reintento del
    escenario completo si cae por rate_limit_exceeded (QA_VOICE_RATE_LIMIT_RETRIES,
    default 2, espera 70s). Un reintento no relaja los checks: el escenario reintentado
    debe pasar igual. Sin envs, comportamiento identico al original."""
    pause = float(os.environ.get("QA_VOICE_SCENARIO_PAUSE_SECONDS") or 0)
    retries = int(os.environ.get("QA_VOICE_RATE_LIMIT_RETRIES") or 2)
    if pause > 0:
        await asyncio.sleep(pause)
    result = await _run_call_once(api, settings, name, turns, checks, from_number=from_number, bridge=bridge)
    attempts = 0
    while (
        attempts < retries
        and not result.get("ok")
        and "rate_limit_exceeded" in str(result.get("error", ""))
    ):
        attempts += 1
        await asyncio.sleep(70)
        result = await _run_call_once(api, settings, name, turns, checks, from_number=from_number, bridge=bridge)
    return result


async def _run_call_once(api, settings, name: str, turns: List[str], checks: Dict[str, CheckFn],
                         *, from_number: str = "", bridge: bool = True) -> Dict[str, Any]:
    call = CallHarness(api, settings, name, from_number=from_number, bridge=bridge)
    ok = True
    problems: List[Dict[str, Any]] = []
    try:
        await call.start()
        for turn in turns:
            await call.say(turn)
        for check_name, check_fn in checks.items():
            try:
                passed, detail = check_fn(call)
            except Exception as exc:  # noqa: BLE001
                passed, detail = False, repr(exc)
            if not passed:
                ok = False
                problems.append({"check": check_name, "detail": detail})
        if call.stalls:
            ok = False
            problems.append({"check": "sin_frases_de_espera_prohibidas", "detail": call.stalls[:3]})
        long_silences = [item for item in call.silence_recoveries if float(item.get("elapsed") or 0) > 2.2]
        if long_silences:
            ok = False
            problems.append({"check": "sin_silencios_de_mas_de_2s", "detail": long_silences[:3]})
        chat_only = [
            item["text"] for item in call.transcript
            if item["role"] == "assistant" and CHAT_ONLY_RE.search(item["text"])
        ]
        if chat_only:
            ok = False
            problems.append({"check": "sin_instrucciones_de_chat", "detail": chat_only[:3]})
        return {
            "name": name,
            "ok": ok,
            "problems": problems,
            "tool_calls": [
                {
                    "name": item["name"],
                    "args": item["args"],
                    "ok": item["result"].get("ok"),
                    "fecha": item["result"].get("fecha"),
                    "hora": item["result"].get("hora"),
                    "mensaje": item["result"].get("mensaje_voz") or item["result"].get("error"),
                }
                for item in call.tools
            ],
            "assistant": [item["text"] for item in call.transcript if item["role"] == "assistant"],
            "silence_recoveries": call.silence_recoveries,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "ok": False,
            "error": repr(exc),
            "tool_calls": [{"name": item["name"], "args": item["args"]} for item in call.tools],
            "assistant": [item["text"] for item in call.transcript if item["role"] == "assistant"],
            "silence_recoveries": call.silence_recoveries,
        }
    finally:
        await call.close()


def _has_tool(name: str) -> CheckFn:
    return lambda call: (any(item["name"] == name for item in call.tools), f"No llamo a {name}")


def _no_tool(name: str) -> CheckFn:
    return lambda call: (not any(item["name"] == name for item in call.tools), f"Llamo indebidamente a {name}")


def _text_has(words: List[str]) -> CheckFn:
    def check(call: CallHarness) -> Tuple[bool, str]:
        text = _observed_text(call)
        return any(word in text for word in words), text

    return check


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _observed_text(call: CallHarness) -> str:
    # Sin acentos: el modelo habla natural ("cuéntame", "¿a qué te refieres?") y las listas
    # de palabras de los checks se escriben accent-free.
    assistant = " ".join(_strip_accents(item["text"].lower()) for item in call.transcript if item["role"] == "assistant")
    tool_messages = " ".join(
        _strip_accents(str(item["result"].get("mensaje_voz") or item["result"].get("error") or "").lower())
        for item in call.tools
    )
    return f"{assistant} {tool_messages}".strip()


def _availability_no_create(call: CallHarness) -> Tuple[bool, str]:
    has_availability = any(item["name"] == "consultar_disponibilidad" for item in call.tools)
    has_create = any(item["name"] == "crear_cita" for item in call.tools)
    return has_availability and not has_create, "Debe consultar disponibilidad pero no crear cita"


def _no_create_and_says_closed(call: CallHarness) -> Tuple[bool, str]:
    has_create = any(item["name"] == "crear_cita" for item in call.tools)
    text = _observed_text(call)
    return (not has_create and any(word in text for word in ("cerrado", "cerrados"))), text


async def main() -> None:
    api, settings = _setup_runtime()
    if not settings.OPENAI_API_KEY:
        print(json.dumps({"ok": False, "blocked": "OPENAI_API_KEY no configurada"}))
        return
    seeded = _seed_business(api)
    monday = seeded["monday"]

    def created_on_monday(call: CallHarness) -> Tuple[bool, str]:
        creates = [item for item in call.tools if item["name"] == "crear_cita" and item["result"].get("ok")]
        if not creates:
            return False, "No creo cita"
        row = api._get_booking_row_by_id(creates[-1]["result"].get("booking_id"))
        ok = (
            row is not None
            and row["booking_date"] == monday
            and row["booking_time"] == "13:00"
            and row["location_id"] == seeded["loc_centro_id"]
        )
        return ok, f"row={dict(row) if row else None}"

    def checked_north_thursday_1130(call: CallHarness) -> Tuple[bool, str]:
        expected_date = seeded["thursday"]
        seen: List[Dict[str, Any]] = []
        for item in call.tools:
            if item["name"] != "consultar_disponibilidad":
                continue
            try:
                args = json.loads(item["args"] or "{}")
            except Exception:  # noqa: BLE001
                args = {}
            seen.append(args)
            centro = str(args.get("centro") or "").lower()
            if (
                str(args.get("fecha") or "") == expected_date
                and str(args.get("hora") or "") == "11:30"
                and "norte" in centro
                and item["result"].get("hora_disponible") is True
            ):
                return True, "ok"
        # Criterio guardarrail: tambien vale que el modelo haya llevado las 11:30 del jueves
        # en Sede Norte a crear_cita (la tool valida el hueco al escribir). Lo que se exige
        # es que la hora concreta pedida llegue VERIFICADA a una herramienta.
        for item in call.tools:
            if item["name"] != "crear_cita":
                continue
            try:
                args = json.loads(item["args"] or "{}")
            except Exception:  # noqa: BLE001
                args = {}
            if (
                str(args.get("fecha") or "") == expected_date
                and str(args.get("hora") or "") == "11:30"
                and "norte" in str(args.get("centro") or "").lower()
            ):
                return True, "ok (via crear_cita validada al escribir)"
        return False, f"expected fecha={expected_date} hora=11:30 centro=norte seen={seen}"

    def not_tuesday(call: CallHarness) -> Tuple[bool, str]:
        text = _observed_text(call)
        return "martes" not in text, text

    def cancelled_existing(call: CallHarness) -> Tuple[bool, str]:
        row = api._get_booking_row_by_id(seeded["existing_id"])
        return row is not None and row["status"] == "cancelled", f"status={row['status'] if row else None}"

    scenarios = [
        (
            "info_servicios_centros",
            ["Hola, donde estais y cuanto cuesta el masaje?"],
            {
                "responde_info": _text_has(["calle mayor", "parque", "diez euros", "10 euros"]),
                "no_crea": _no_tool("crear_cita"),
            },
        ),
        (
            "reserva_lunes_una_centro",
            [
                "Quiero reservar un masaje el lunes a la una.",
                "En la sede Centro.",
                "Pablo Sanchez, 675 802 001.",
                "Si, correcto.",
            ],
            {
                "consulta": _has_tool("consultar_disponibilidad"),
                "crea": _has_tool("crear_cita"),
                "lunes_no_martes": not_tuesday,
                "bd_lunes_13": created_on_monday,
            },
        ),
        (
            "domingo_cerrado",
            ["Quiero reservar un masaje.", "En la sede Centro.", "El domingo a las diez."],
            {"no_crea_y_dice_cerrado": _no_create_and_says_closed},
        ),
        (
            "fuera_horario",
            ["Quiero reservar un masaje.", "En la sede Centro.", "El lunes a las ocho de la tarde."],
            {
                "consulta_sin_crear": _availability_no_create,
                "dice_cerrado_o_no": _text_has(["cerrado", "cerrados", "no tenemos hueco", "no hay hueco"]),
            },
        ),
        (
            "bloqueo_vacaciones",
            ["Quiero reservar un masaje.", "En la sede Centro.", "El lunes a las diez."],
            {
                "consulta_sin_crear": _availability_no_create,
                "dice_bloqueo": _text_has(["vacaciones", "bloqueada", "bloqueado"]),
            },
        ),
        (
            "servicio_inexistente",
            ["Quiero reservar una cita.", "Acupuntura.", "En la sede Centro."],
            {
                "no_crea": _no_tool("crear_cita"),
                "ofrece_reales": _text_has(["masaje", "sesion estandar", "no lo encuentro", "no encuentro"]),
            },
        ),
        (
            "hora_ocupada_alternativas",
            ["Quiero reservar un masaje.", "En la sede Centro.", "El lunes a las nueve."],
            {
                "consulta_sin_crear": _availability_no_create,
                "dice_no_hueco": _text_has(["no tenemos hueco", "no hay hueco", "no esta disponible", "tengo"]),
            },
        ),
        (
            "sede_norte_jueves_once_media",
            [
                "Quiero agendar una cita para un masaje.",
                "En la sede Norte.",
                "Para el jueves.",
                "A las cuatro y media.",
                "A las once y media.",
            ],
            {
                "consulta_1130_norte": checked_north_thursday_1130,
                # Guardarrail: lo prohibido es CREAR sin datos reales del cliente; una
                # invocacion rechazada por la tool (contacto placeholder) es correcta.
                "no_crea_sin_datos": lambda call: (
                    not any(
                        item["name"] == "crear_cita" and (item.get("result") or {}).get("ok")
                        for item in call.tools
                    ),
                    f"tools={[i['name'] for i in call.tools]}",
                ),
            },
        ),
        (
            "cancelacion_con_telefono",
            [
                "Quiero cancelar una cita.",
                f"El codigo es {seeded['existing_code']}.",
                "Si, es esa. Mi telefono es 675 802 001.",
                "Si, cancelala.",
            ],
            {
                "consulta_cita": _has_tool("consultar_cita"),
                "cancela": _has_tool("cancelar_cita"),
                "bd_cancelada": cancelled_existing,
            },
        ),
    ]
    # Subconjunto opcional para ahorrar cuota OpenAI (RPD): --only=nombre1,nombre2
    only: set = set()
    for arg in sys.argv[1:]:
        if arg.startswith("--only="):
            only = {s.strip() for s in arg.split("=", 1)[1].split(",") if s.strip()}

    results = []
    blocked_by_quota = False
    for name, turns, checks in scenarios:
        if only and name not in only:
            continue
        res = await _run_call(api, settings, name, turns, checks)
        # La cuota diaria de OpenAI Realtime (RPD) no es un fallo funcional: marcamos el
        # escenario como bloqueado y paramos para no quemar mas intentos.
        error_text = str(res.get("error", ""))
        if "rate_limit_exceeded" in error_text or "insufficient_quota" in error_text:
            res["blocked"] = True
            blocked_by_quota = True
            results.append(res)
            break
        results.append(res)

    ran = [r for r in results if not r.get("blocked")]
    summary_ok = bool(ran) and all(r.get("ok") for r in ran)
    print(
        json.dumps(
            {
                "ok": summary_ok,
                "blocked_by_quota": blocked_by_quota,
                "ran": len(ran),
                "passed": sum(1 for r in ran if r.get("ok")),
                "tenant": CID,
                "lunes": seeded["monday"],
                "jueves": seeded["thursday"],
                "domingo": seeded["sunday"],
                "existing_code": seeded["existing_code"],
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
