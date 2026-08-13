"""Tests del motor determinista de voz (backend/voice_engine.py).

Verifican la logica EXTRAIDA del puente Twilio (voice_media_stream) directamente, sin
WebSocket ni OpenAI: dedup de reservas, cuando forzar habla tras una tool y la frase de
ultimo recurso del watchdog anti-silencio. Antes esta logica solo se "testeaba" por substring
sobre el codigo fuente; aqui se ejercita de verdad."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend import voice, voice_engine


def test_new_call_state_is_fresh_per_call():
    a = voice_engine.new_call_state()
    b = voice_engine.new_call_state()
    # Cada llamada parte de cero y NO comparte el set de firmas (clave del anti-duplicado).
    assert a is not b
    assert a["created_signatures"] is not b["created_signatures"]
    a["created_signatures"].add("x")
    assert b["created_signatures"] == set()
    # Claves criticas presentes con su default.
    assert a["booked"] is False
    assert a["pending_mutation_code"] == ""
    assert a["outcome"] == ""


def test_booking_signature_stable_ignores_formatting():
    # La firma quita lo no-digito del telefono y normaliza espacios/mayusculas del servicio:
    # el MISMO numero escrito distinto y el servicio con mayusculas/espacios dan la misma firma.
    args1 = {"telefono": "+34 600-123-456", "servicio": "Masaje ", "fecha": "2099-01-02", "hora": "16:00"}
    args2 = {"telefono": "+34600123456", "servicio": "masaje", "fecha": "2099-01-02", "hora": "16:00"}
    sig1 = voice_engine.booking_signature(args1)
    sig2 = voice_engine.booking_signature(args2)
    assert sig1 == sig2  # mismo telefono/servicio/fecha/hora -> misma firma (dedup)
    assert "34600123456" in sig1


def test_booking_signature_empty_without_date_or_time():
    assert voice_engine.booking_signature({"telefono": "600123456", "servicio": "x"}) == ""
    assert voice_engine.booking_signature({"fecha": "2099-01-02"}) == ""
    assert voice_engine.booking_signature("nope") == ""


def test_booking_signature_distinguishes_slot_and_center():
    base = {"telefono": "600123456", "servicio": "masaje", "fecha": "2099-01-02", "hora": "16:00"}
    other_time = {**base, "hora": "17:00"}
    other_center = {**base, "centro": "norte"}
    assert voice_engine.booking_signature(base) != voice_engine.booking_signature(other_time)
    assert voice_engine.booking_signature(base) != voice_engine.booking_signature(other_center)


def test_should_force_tool_speech():
    assert voice_engine.should_force_tool_speech("crear_cita", {"mensaje_voz": "Hecho"}) is True
    assert voice_engine.should_force_tool_speech("cancelar_cita", {"error": "no"}) is True
    # Tool fuera del catalogo critico: su silencio no rompe el flujo de reserva.
    assert voice_engine.should_force_tool_speech("consultar_servicios", {"mensaje_voz": "x"}) is False
    # Sin mensaje no hay nada que forzar.
    assert voice_engine.should_force_tool_speech("crear_cita", {"ok": True}) is False
    assert voice_engine.should_force_tool_speech("", {"mensaje_voz": "x"}) is False
    assert voice_engine.should_force_tool_speech("crear_cita", "nope") is False


# --------------------------------------------------------------------------
# Harness de integracion del motor (VoiceCallEngine) SIN WebSocket: se le pasan
# eventos Realtime y se asierta lo que emite a OpenAI/Twilio y como deja el estado.
# Reemplaza el "test por substring": ejercita el bucle determinista de verdad.
# --------------------------------------------------------------------------

class FakeTransport:
    """Captura lo que el motor emite en vez de mandarlo por WebSocket."""

    def __init__(self):
        self.openai = []
        self.twilio = []

    async def send_openai(self, ev):
        self.openai.append(ev)

    async def send_twilio(self, ev):
        self.twilio.append(ev)

    async def clear_playback(self):
        return True

    async def truncate_interrupted(self):
        return True


class DispatchStub:
    """Sustituye voice._voice_dispatch_tool: devuelve resultados predefinidos por tool y
    registra las llamadas (para asertar dedup / que NO se ejecuta de mas)."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    async def __call__(self, cliente_id, name, arguments_json, *, from_number="", location_id=""):
        self.calls.append((name, json.loads(arguments_json or "{}")))
        return dict(self.mapping.get(name, {"ok": False, "error": "sin stub"}))


def _build_engine(dispatch_mapping):
    tx = FakeTransport()
    engine = voice_engine.VoiceCallEngine("demo", {}, {})
    engine.bind_transport(
        send_openai=tx.send_openai,
        send_twilio=tx.send_twilio,
        clear_playback=tx.clear_playback,
        truncate_interrupted=tx.truncate_interrupted,
    )
    return engine, tx, DispatchStub(dispatch_mapping)


def _instructions_sent(tx):
    return [
        (ev.get("response") or {}).get("instructions") or ""
        for ev in tx.openai
        if ev.get("type") == "response.create"
    ]


def _function_call_outputs(tx):
    return [
        ev["item"]
        for ev in tx.openai
        if ev.get("type") == "conversation.item.create"
        and (ev.get("item") or {}).get("type") == "function_call_output"
    ]


def test_engine_create_booking_then_forced_speech():
    engine, tx, stub = _build_engine({
        "crear_cita": {"ok": True, "mensaje_voz": "Perfecto, tu cita queda reservada el martes a las cuatro."},
    })
    original = voice._voice_dispatch_tool
    voice._voice_dispatch_tool = stub
    try:
        async def scenario():
            await engine.on_openai_event({
                "type": "response.function_call_arguments.done",
                "call_id": "call_1",
                "name": "crear_cita",
                "arguments": json.dumps({
                    "nombre": "Ana", "telefono": "600123456",
                    "servicio": "masaje", "fecha": "2099-01-02", "hora": "16:00",
                }),
            })
            # La respuesta de la function_call sigue activa: el resultado se habla al response.done.
            await engine.on_openai_event({"type": "response.done"})
        asyncio.run(scenario())
    finally:
        voice._voice_dispatch_tool = original

    outputs = _function_call_outputs(tx)
    assert len(outputs) == 1
    assert json.loads(outputs[0]["output"])["ok"] is True
    assert engine.state["booked"] is True
    assert any("Perfecto, tu cita queda reservada" in ins for ins in _instructions_sent(tx))
    assert len(stub.calls) == 1 and stub.calls[0][0] == "crear_cita"


def test_engine_dedupes_double_booking():
    engine, tx, stub = _build_engine({
        "crear_cita": {"ok": True, "mensaje_voz": "Cita reservada."},
    })
    original = voice._voice_dispatch_tool
    voice._voice_dispatch_tool = stub
    args = json.dumps({
        "nombre": "Ana", "telefono": "600123456",
        "servicio": "masaje", "fecha": "2099-01-02", "hora": "16:00",
    })
    try:
        async def scenario():
            for _ in range(2):
                await engine.on_openai_event({
                    "type": "response.function_call_arguments.done",
                    "call_id": "c", "name": "crear_cita", "arguments": args,
                })
                await engine.on_openai_event({"type": "response.done"})
        asyncio.run(scenario())
    finally:
        voice._voice_dispatch_tool = original

    # La tool real solo se ejecuto UNA vez; la segunda fue deduplicada por el motor.
    assert len(stub.calls) == 1
    outputs = [json.loads(o["output"]) for o in _function_call_outputs(tx)]
    assert outputs[0].get("duplicate") is not True
    assert outputs[1].get("duplicate") is True
    assert any("ya esta creada" in ins for ins in _instructions_sent(tx))


def test_engine_reschedule_slot_free_guides_model_to_reprogram():
    # Version flexible: el motor YA NO reprograma solo al ver hueco. Ejecuta la tool que pidio
    # el modelo (consultar_disponibilidad) y le pasa una GUIA para que llame el a reprogramar_cita.
    engine, tx, stub = _build_engine({
        "consultar_disponibilidad": {"ok": True, "hora": "17:00", "hora_disponible": True, "fecha": "2099-01-03"},
        "reprogramar_cita": {"ok": True, "mensaje_voz": "Listo, tu cita queda cambiada."},
    })
    engine.state["pending_mutation_intent"] = "reschedule"
    engine.state["pending_mutation_code"] = "AB12CD"
    original = voice._voice_dispatch_tool
    voice._voice_dispatch_tool = stub
    try:
        async def scenario():
            await engine.on_openai_event({
                "type": "response.function_call_arguments.done",
                "call_id": "c", "name": "consultar_disponibilidad",
                "arguments": json.dumps({"fecha": "2099-01-03", "hora": "17:00"}),
            })
        asyncio.run(scenario())
    finally:
        voice._voice_dispatch_tool = original

    called = [c[0] for c in stub.calls]
    # Solo se ejecuto la tool del modelo; el motor NO llamo a reprogramar por su cuenta.
    assert called == ["consultar_disponibilidad"]
    # Pero deja la guia para que el modelo reprograme (via followup en el estado).
    assert "REPROGRAMANDO" in (engine.state.get("pending_tool_followup_prompt") or "")


def test_engine_silence_gives_internal_nudge_not_fixed_phrase():
    # Repro del bug: cita identificada, cliente dice "quiero cancelar esa cita" (ni si ni tel),
    # el modelo se queda mudo. El watchdog NO dice "no te he entendido": da un empujon INTERNO
    # (mensaje de sistema) para que el modelo continue con sus palabras.
    import time as _time
    engine, tx, _stub = _build_engine({})
    st = engine.state
    st["session_configured"] = True
    st["pending_mutation_intent"] = "cancel"
    st["pending_mutation_code"] = "R-481523"
    st["silence_guard_armed"] = True
    st["silence_guard_started_at"] = _time.monotonic() - 10
    st["silence_guard_used"] = False
    st["turn_had_assistant_output"] = False
    st["response_active"] = False
    st["response_cancel_pending"] = False

    asyncio.run(engine.maybe_recover_silence())

    # Se envio un mensaje de sistema (empujon interno) y un response.create, sin frase fija.
    sys_msgs = [
        ev for ev in tx.openai
        if ev.get("type") == "conversation.item.create"
        and (ev.get("item") or {}).get("type") == "message"
    ]
    joined = json.dumps(tx.openai, ensure_ascii=False).lower()
    assert sys_msgs, "deberia inyectar un empujon interno de sistema"
    assert "no te he entendido" not in joined
    assert "continua la conversacion" in joined
    assert any(ev.get("type") == "response.create" for ev in tx.openai)


def test_engine_user_turn_resets_flags_and_records_transcript():
    engine, _tx, _stub = _build_engine({})
    engine.state["turn_had_function_call"] = True
    engine.state["turn_had_assistant_output"] = True

    async def scenario():
        await engine.on_openai_event({
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "Hola, quiero reservar una cita para un masaje",
        })
    asyncio.run(scenario())

    # Nuevo turno del cliente: resetea las banderas de turno y rearma el watchdog.
    assert engine.state["turn_had_function_call"] is False
    assert engine.state["turn_had_assistant_output"] is False
    assert engine.state["silence_guard_armed"] is True
    assert engine.transcript and engine.transcript[-1]["role"] == "user"


def test_engine_outbound_confirm_marks_booking():
    engine, tx, _stub = _build_engine({})
    engine.state["outbound"] = True
    engine.state["outbound_booking_id"] = ""  # prueba de Seguimiento: no hay cita real que marcar

    async def scenario():
        await engine.on_openai_event({
            "type": "response.function_call_arguments.done",
            "call_id": "c", "name": "confirmar_cita", "arguments": "{}",
        })
        await engine.on_openai_event({"type": "response.done"})
    asyncio.run(scenario())

    outputs = [json.loads(o["output"]) for o in _function_call_outputs(tx)]
    assert outputs and outputs[0]["confirmada"] is True
    assert any("queda confirmada" in ins for ins in _instructions_sent(tx))


# --- Gaps: transferir a humano, colgar limpio, etiquetado de resultado ------

def test_engine_finalizar_llamada_requests_hangup():
    engine, tx, _stub = _build_engine({})
    async def scenario():
        await engine.on_openai_event({
            "type": "response.function_call_arguments.done",
            "call_id": "c", "name": "finalizar_llamada", "arguments": "{}",
        })
    asyncio.run(scenario())
    assert engine.state["should_end_call"] is True
    # Se devolvio una despedida hablada.
    outputs = [json.loads(o["output"]) for o in _function_call_outputs(tx)]
    assert outputs and "buen dia" in outputs[0].get("mensaje_voz", "").lower()


def test_engine_transfer_redirects_and_ends(monkeypatch=None):
    engine, tx, _stub = _build_engine({})
    engine.transfer_number = "+34600000000"
    engine.state["call_sid"] = "CA_test"
    calls = []
    def fake_transfer(cliente_id, call_sid, number):
        calls.append((cliente_id, call_sid, number))
        return True
    original = voice._voice_transfer_call
    voice._voice_transfer_call = fake_transfer
    try:
        async def scenario():
            await engine.on_openai_event({
                "type": "response.function_call_arguments.done",
                "call_id": "c", "name": "transferir_a_humano", "arguments": "{}",
            })
        asyncio.run(scenario())
    finally:
        voice._voice_transfer_call = original
    assert calls == [("demo", "CA_test", "+34600000000")]
    assert engine.state["outcome"] == "transferida"
    assert engine.state["should_end_call"] is True


def test_engine_transfer_without_number_takes_message():
    engine, tx, _stub = _build_engine({})
    engine.transfer_number = ""
    async def scenario():
        await engine.on_openai_event({
            "type": "response.function_call_arguments.done",
            "call_id": "c", "name": "transferir_a_humano", "arguments": "{}",
        })
    asyncio.run(scenario())
    outputs = [json.loads(o["output"]) for o in _function_call_outputs(tx)]
    assert outputs and outputs[0]["ok"] is False
    assert engine.state["should_end_call"] is False


def test_engine_outcome_labels():
    # crear -> reservada
    e1, _t, s1 = _build_engine({"crear_cita": {"ok": True, "mensaje_voz": "Reservada."}})
    orig = voice._voice_dispatch_tool
    voice._voice_dispatch_tool = s1
    try:
        asyncio.run(e1.on_openai_event({
            "type": "response.function_call_arguments.done", "call_id": "c",
            "name": "crear_cita", "arguments": json.dumps({
                "nombre": "Ana", "telefono": "600123456", "servicio": "masaje",
                "fecha": "2099-01-02", "hora": "16:00"}),
        }))
        assert e1.state["outcome"] == "reservada"
        # cancelar -> cancelada
        e2, _t2, s2 = _build_engine({"cancelar_cita": {"ok": True, "mensaje_voz": "Cancelada."}})
        voice._voice_dispatch_tool = s2
        asyncio.run(e2.on_openai_event({
            "type": "response.function_call_arguments.done", "call_id": "c",
            "name": "cancelar_cita", "arguments": json.dumps({"codigo_reserva": "R-1"}),
        }))
        assert e2.state["outcome"] == "cancelada"
    finally:
        voice._voice_dispatch_tool = orig


def test_engine_interrupted_and_unintelligible_recovers():
    # Barge-in + transcripcion basura: el motor inyecta la recuperacion ('no te he pillado
    # bien') en vez de dejar que el modelo interprete el ruido o quedarse mudo.
    engine, tx, _stub = _build_engine({})
    engine.state["was_interrupted"] = True

    async def scenario():
        await engine.on_openai_event({
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "Subtítulos realizados por la comunidad de Amara",
        })
    asyncio.run(scenario())

    joined = json.dumps(tx.openai, ensure_ascii=False).lower()
    assert "no te he pillado" in joined
    assert any(ev.get("type") == "response.create" for ev in tx.openai)
    assert engine.state["was_interrupted"] is False
    # Interrupcion entendible: no inyecta nada, el modelo la atiende solo.
    engine2, tx2, _s2 = _build_engine({})
    engine2.state["was_interrupted"] = True
    asyncio.run(engine2.on_openai_event({
        "type": "conversation.item.input_audio_transcription.completed",
        "transcript": "quiero reservar un masaje",
    }))
    assert not any(ev.get("type") == "response.create" for ev in tx2.openai)
    assert engine2.state["was_interrupted"] is False


def test_engine_silence_giveup_says_goodbye_and_hangs_up():
    import time as _time
    engine, tx, _stub = _build_engine({})
    st = engine.state
    st["session_configured"] = True
    st["silence_guard_armed"] = True
    st["silence_guard_started_at"] = _time.monotonic() - 10
    st["silence_guard_used"] = False
    st["turn_had_assistant_output"] = False
    st["response_active"] = False
    st["response_cancel_pending"] = False
    st["silence_guard_recoveries"] = 4  # ya se paso el limite -> despedida + colgar
    asyncio.run(engine.maybe_recover_silence())
    assert engine.state["should_end_call"] is True
    joined = json.dumps(tx.openai, ensure_ascii=False).lower()
    assert "despidete" in joined or "que tengas un buen dia" in joined


# --- Silencio conversacional (nadie habla) ----------------------------------------
# El watchdog clasico solo vigila el turno del asistente: si el cliente interrumpe a
# mitad de frase y despues no dice nada, se desarma y la llamada se queda muerta.


def test_idle_recovery_nudges_when_nobody_speaks():
    """Tras el umbral de silencio, el motor reengancha con un empujon INTERNO."""
    engine, transport, _ = _build_engine({})
    engine.state["session_configured"] = True
    engine.mark_activity()
    engine.state["last_activity_at"] -= engine.idle_silence_seconds + 1

    asyncio.run(engine.maybe_recover_idle())

    enviados = json.dumps(transport.openai, ensure_ascii=False)
    assert "sin decir nada" in enviados
    assert any(e.get("type") == "response.create" for e in transport.openai)
    assert engine.state["idle_nudges"] == 1


def test_idle_recovery_stays_quiet_while_assistant_talks_or_tool_pending():
    engine, transport, _ = _build_engine({})
    engine.state["session_configured"] = True
    engine.mark_activity()
    engine.state["last_activity_at"] -= engine.idle_silence_seconds + 1

    engine.state["response_active"] = True
    asyncio.run(engine.maybe_recover_idle())
    assert transport.openai == []

    engine.state["response_active"] = False
    engine.state["pending_tool_response"] = True
    asyncio.run(engine.maybe_recover_idle())
    assert transport.openai == []


def test_idle_recovery_says_goodbye_after_max_nudges():
    engine, transport, _ = _build_engine({})
    engine.state["session_configured"] = True
    engine.mark_activity()
    engine.state["idle_nudges"] = engine.idle_max_nudges
    engine.state["last_activity_at"] -= engine.idle_silence_seconds + 1

    asyncio.run(engine.maybe_recover_idle())

    assert engine.state["should_end_call"] is True
    assert "despidete" in json.dumps(transport.openai, ensure_ascii=False).lower()


def test_customer_speech_resets_idle_counter():
    engine, _, _ = _build_engine({})
    engine.state["session_configured"] = True
    engine.state["idle_nudges"] = 2
    asyncio.run(engine.on_openai_event({"type": "input_audio_buffer.speech_started"}))
    assert engine.state["idle_nudges"] == 0
    assert engine.state["last_activity_at"] > 0
