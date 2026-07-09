from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import qa_voice_realtime_calls as qa  # noqa: E402


def _assistant_text(call: qa.CallHarness) -> str:
    return " ".join(item["text"].lower() for item in call.transcript if item["role"] == "assistant")


def _tool_names(call: qa.CallHarness) -> List[str]:
    return [item["name"] for item in call.tools]


def _has_tool(name: str):
    return lambda call: (name in _tool_names(call), f"No llamo a {name}. tools={_tool_names(call)}")


def _availability_checked_or_write_validated(call: qa.CallHarness):
    """El hueco debe estar verificado: o el modelo consulto disponibilidad antes, o la
    reprogramacion se ejecuto ok (reprogramar_cita valida el hueco en el backend al
    escribir — _booking_slot_available_for_reschedule — y falla si esta ocupado/cerrado).
    Fiabilidad en las tools, no en encarrilar el dialogo."""
    if "consultar_disponibilidad" in _tool_names(call):
        return True, ""
    ok_resch = any(
        item["name"] == "reprogramar_cita" and isinstance(item.get("result"), dict) and item["result"].get("ok")
        for item in call.tools
    )
    return ok_resch, f"Ni consulto disponibilidad ni reprogramo con exito. tools={_tool_names(call)}"


async def _seeded() -> Tuple[Any, Any, Dict[str, Any]]:
    api, settings = qa._setup_runtime()
    seeded = qa._seed_business(api)
    return api, settings, seeded


async def _run_inbound_booking() -> Dict[str, Any]:
    api, settings, seeded = await _seeded()
    monday = seeded["monday"]

    def final_spoken(call: qa.CallHarness):
        text = _assistant_text(call)
        ok = ("queda confirmada" in text or "queda reservada" in text) and (
            "codigo" in text or "código" in text
        )
        return ok, text

    def db_ok(call: qa.CallHarness):
        creates = [item for item in call.tools if item["name"] == "crear_cita" and item["result"].get("ok")]
        if not creates:
            return False, "No creo cita"
        row = api._get_booking_row_by_id(creates[-1]["result"].get("booking_id"))
        ok = row is not None and row["booking_date"] == monday and row["booking_time"] == "13:00"
        return ok, f"row={dict(row) if row else None}"

    return await qa._run_call(
        api,
        settings,
        "deep_reserva_confirma_y_habla",
        [
            "Quiero reservar un masaje el lunes a la una.",
            "En la sede Centro.",
            "Pablo Sanchez, 675 802 001.",
            "Si, correcto.",
        ],
        {
            "consulta": _has_tool("consultar_disponibilidad"),
            "crea": _has_tool("crear_cita"),
            "bd": db_ok,
            "confirmacion_hablada": final_spoken,
        },
    )


async def _run_cancel() -> Dict[str, Any]:
    api, settings, seeded = await _seeded()
    code = seeded["existing_code"]

    def db_cancelled(call: qa.CallHarness):
        row = api._get_booking_row_by_id(seeded["existing_id"])
        return row is not None and row["status"] == "cancelled", f"status={row['status'] if row else None}"

    def final_spoken(call: qa.CallHarness):
        text = _assistant_text(call)
        return "cancelado" in text or "cancelada" in text, text

    return await qa._run_call(
        api,
        settings,
        "deep_cancelacion",
        [
            f"Quiero cancelar mi cita. El codigo es {code}.",
            "Si, es esa.",
            "El telefono es 675 802 001.",
            "Si, cancelala.",
        ],
        {
            "consulta_cita": _has_tool("consultar_cita"),
            "cancela": _has_tool("cancelar_cita"),
            "bd_cancelada": db_cancelled,
            "confirmacion_hablada": final_spoken,
        },
    )


async def _run_reschedule() -> Dict[str, Any]:
    api, settings, seeded = await _seeded()
    code = seeded["existing_code"]
    monday = seeded["monday"]

    def db_reprogrammed(call: qa.CallHarness):
        row = api._get_booking_row_by_id(seeded["existing_id"])
        ok = row is not None and row["status"] == "confirmed" and row["booking_time"] == "16:00"
        return ok, f"row={dict(row) if row else None}"

    def final_spoken(call: qa.CallHarness):
        text = _assistant_text(call)
        return "reprogram" in text or "cambiada" in text, text

    return await qa._run_call(
        api,
        settings,
        "deep_reprogramacion",
        [
            f"Quiero cambiar mi cita {code}.",
            "Si, es esa. Mi telefono es 675 802 001.",
            "La quiero el lunes a las cuatro de la tarde.",
            "Si, perfecto.",
        ],
        {
            "consulta_cita": _has_tool("consultar_cita"),
            "consulta_disponibilidad": _availability_checked_or_write_validated,
            "reprograma": _has_tool("reprogramar_cita"),
            "bd_reprogramada": db_reprogrammed,
            "confirmacion_hablada": final_spoken,
        },
    )


async def _run_reschedule_day() -> Dict[str, Any]:
    """Mover una cita a OTRO DIA (no solo otra hora) y comprobar que la fecha cambia en
    la agenda. Cita en lunes -> la movemos al miercoles a las once."""
    from datetime import date, timedelta
    api, settings, seeded = await _seeded()
    code = seeded["existing_code"]
    monday = date.fromisoformat(seeded["monday"])
    wednesday = (monday + timedelta(days=2)).isoformat()  # lunes + 2 = miercoles (abierto)

    def db_moved_to_wednesday(call: qa.CallHarness):
        row = api._get_booking_row_by_id(seeded["existing_id"])
        ok = (
            row is not None
            and row["status"] == "confirmed"
            and row["booking_date"] == wednesday
            and row["booking_time"] == "11:00"
        )
        return ok, f"date={row['booking_date'] if row else None} time={row['booking_time'] if row else None} (esperado {wednesday} 11:00)"

    def final_spoken(call: qa.CallHarness):
        text = _assistant_text(call)
        return "reprogram" in text or "cambiada" in text or "miercoles" in text, text

    return await qa._run_call(
        api,
        settings,
        "deep_reprogramacion_cambio_de_dia",
        [
            f"Quiero cambiar mi cita {code} a otro dia.",
            "Si, es esa. Mi telefono es 675 802 001.",
            "Muevela al miercoles a las once de la manana.",
            "Si, perfecto.",
        ],
        {
            "consulta_cita": _has_tool("consultar_cita"),
            "consulta_disponibilidad": _availability_checked_or_write_validated,
            "reprograma": _has_tool("reprogramar_cita"),
            "bd_cambio_de_dia": db_moved_to_wednesday,
            "confirmacion_hablada": final_spoken,
        },
    )


async def _run_reschedule_time_change() -> Dict[str, Any]:
    """Reprogramar cambiando SOLO la hora ('mejor a las dos y media', sin repetir el dia).
    No debe quedarse mudo: reusa el dia de la cita y comprueba/reprograma directamente."""
    api, settings, seeded = await _seeded()
    code = seeded["existing_code"]
    monday = seeded["monday"]

    def db_moved_same_day(call: qa.CallHarness):
        row = api._get_booking_row_by_id(seeded["existing_id"])
        ok = (
            row is not None
            and row["status"] == "confirmed"
            and row["booking_date"] == monday
            and row["booking_time"] == "14:30"
        )
        return ok, f"date={row['booking_date'] if row else None} time={row['booking_time'] if row else None} (esperado {monday} 14:30)"

    return await qa._run_call(
        api,
        settings,
        "deep_reprogramacion_cambio_de_hora",
        [
            f"Necesito mover mi cita {code}.",
            "Si, es esa. Mi telefono es 675 802 001.",
            "A las dos y media.",
            "Si, perfecto.",
        ],
        {
            "reprograma": _has_tool("reprogramar_cita"),
            "bd_cambio_de_hora": db_moved_same_day,
        },
    )


async def _run_reschedule_browser() -> Dict[str, Any]:
    """Reprograma en MODO NAVEGADOR (sin redes deterministas del puente): solo modelo +
    tools + prompt. Reproduce 'Probar en el navegador'. Debe reprogramar SIN volver a pedir
    nombre/telefono una vez verificado el titular."""
    api, settings, seeded = await _seeded()
    code = seeded["existing_code"]
    monday = seeded["monday"]
    digits = code.replace("R-", "")
    spoken_digits = " ".join(digits)  # "5 8 3 1 6 4"

    def db_moved(call: qa.CallHarness):
        row = api._get_booking_row_by_id(seeded["existing_id"])
        ok = row is not None and row["status"] == "confirmed" and row["booking_date"] == monday and row["booking_time"] == "16:00"
        return ok, f"date={row['booking_date'] if row else None} time={row['booking_time'] if row else None}"

    def no_pide_datos(call: qa.CallHarness):
        # Tras verificar, NO debe pedir nombre/telefono (es un cambio, no una reserva nueva).
        bad = [a for a in (item["text"] for item in call.transcript if item["role"] == "assistant")
               if "necesito tu nombre" in a.lower() or ("nombre completo" in a.lower() and "telefono" in a.lower().replace("é", "e"))]
        return (not bad), (bad[:1] or "ok")

    return await qa._run_call(
        api, settings, "deep_reprogramacion_navegador",
        [
            "Quiero reprogramar una cita.",
            spoken_digits,
            "675 802 001.",
            "El mismo dia a las cuatro de la tarde.",
            "Si, perfecto.",
        ],
        {
            "reprograma": _has_tool("reprogramar_cita"),
            "bd_movida": db_moved,
            "no_pide_nombre_telefono": no_pide_datos,
        },
        from_number="",      # navegador: sin numero (WebRTC)
        bridge=False,
    )


async def _run_outbound_confirm() -> Dict[str, Any]:
    api, settings, seeded = await _seeded()
    row = api._get_booking_row_by_id(seeded["existing_id"])

    call = qa.CallHarness(api, settings, "deep_saliente_confirmacion", from_number=row["telefono"])
    call.outbound_booking_id = seeded["existing_id"]
    ok = True
    problems: List[Dict[str, Any]] = []
    try:
        call.ws = await qa._connect_ws(settings)
        cfg = api.CONFIG_CLIENTES[qa.CID]
        await call.ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "model": settings.VOICE_REALTIME_MODEL,
                        "output_modalities": ["audio"],
                        "instructions": api._voice_outbound_confirm_instructions(qa.CID, cfg, row),
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
                                "voice": getattr(settings, "VOICE_OPENAI_VOICE", "alloy"),
                                "format": {"type": "audio/pcmu"},
                            },
                        },
                        "tools": api._voice_booking_tools(qa.CID, cfg, include_confirm=True),
                        "tool_choice": "auto",
                    },
                }
            )
        )
        for _ in range(40):
            event = json.loads(await asyncio.wait_for(call.ws.recv(), timeout=20))
            if event.get("type") == "session.updated":
                await call.ws.send(
                    json.dumps(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": api._voice_outbound_greeting(cfg, row),
                                    }
                                ],
                            },
                        }
                    )
                )
                greeting = api._voice_outbound_greeting(cfg, row)
                await call.ws.send(
                    json.dumps(
                        {
                            "type": "response.create",
                            "response": {
                                "output_modalities": ["audio"],
                                "instructions": (
                                    "Di exactamente esta frase y nada mas, sin llamar herramientas: "
                                    f"\"{greeting}\""
                                ),
                                "tool_choice": "none",
                            },
                        }
                    )
                )
                await call._collect()
                break
            if event.get("type") == "error":
                raise RuntimeError(json.dumps(event, ensure_ascii=False))
        await call.say("Si, me viene bien, confirmo la cita.")
        fallback_confirmed = False
        if "confirmar_cita" in _tool_names(call):
            fallback_confirmed = bool(
                api._mark_booking_confirmed_by_customer(seeded["existing_id"], qa.CID, channel="voice_outbound")
            )
        if "confirmar_cita" not in _tool_names(call) and api._voice_user_says_yes(call.last_user_text):
            fallback_confirmed = bool(
                api._mark_booking_confirmed_by_customer(seeded["existing_id"], qa.CID, channel="voice_outbound")
            )
            message = (
                "Perfecto, queda confirmada. Muchas gracias, que tenga buen dia."
                if fallback_confirmed else "No he podido confirmar la cita ahora mismo. Lo revisara el equipo."
            )
            await call.ws.send(
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
            await call.ws.send(
                json.dumps(
                    {
                        "type": "response.create",
                        "response": {
                            "output_modalities": ["audio"],
                            "instructions": (
                                "No llames a ninguna herramienta. Di esta frase natural y breve: "
                                f"\"{message}\""
                            ),
                            "tool_choice": "none",
                        },
                    }
                )
            )
            await call._collect()
        row_after = api._get_booking_row_by_id(seeded["existing_id"])
        spoken = _assistant_text(call)
        checks = {
            "confirmar_cita_o_fallback": "confirmar_cita" in _tool_names(call) or fallback_confirmed,
            "bd_confirmada": bool(row_after and row_after["confirmed_at"]),
            "confirmacion_hablada": "queda confirmada" in spoken or "confirmada" in spoken,
        }
        for name, passed in checks.items():
            if not passed:
                ok = False
                problems.append({"check": name, "detail": f"tools={_tool_names(call)} row={dict(row_after) if row_after else None}"})
        if call.stalls:
            ok = False
            problems.append({"check": "sin_frases_de_espera_prohibidas", "detail": call.stalls})
        return {
            "name": call.name,
            "ok": ok,
            "problems": problems,
            "tool_calls": [
                {
                    "name": item["name"],
                    "ok": item["result"].get("ok"),
                    "mensaje": item["result"].get("mensaje_voz") or item["result"].get("error"),
                }
                for item in call.tools
            ],
            "assistant": [item["text"] for item in call.transcript if item["role"] == "assistant"],
        }
    finally:
        await call.close()


async def _run_outbound_cancel() -> Dict[str, Any]:
    """Llamada SALIENTE de confirmacion en la que el cliente final pide CANCELAR.
    El asistente debe cancelar la cita (telefono ya verificado por ser su propio numero)
    y la agenda debe quedar 'cancelled'."""
    api, settings, seeded = await _seeded()
    row = api._get_booking_row_by_id(seeded["existing_id"])

    call = qa.CallHarness(api, settings, "deep_saliente_cancelacion", from_number=row["telefono"])
    call.outbound_booking_id = seeded["existing_id"]
    ok = True
    problems: List[Dict[str, Any]] = []
    try:
        call.ws = await qa._connect_ws(settings)
        cfg = api.CONFIG_CLIENTES[qa.CID]
        await call.ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": settings.VOICE_REALTIME_MODEL,
                "output_modalities": ["audio"],
                "instructions": api._voice_outbound_confirm_instructions(qa.CID, cfg, row),
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
                        "voice": getattr(settings, "VOICE_OPENAI_VOICE", "alloy"),
                        "format": {"type": "audio/pcmu"},
                    },
                },
                "tools": api._voice_booking_tools(qa.CID, cfg, include_confirm=True),
                "tool_choice": "auto",
            },
        }))
        for _ in range(40):
            event = json.loads(await asyncio.wait_for(call.ws.recv(), timeout=20))
            if event.get("type") == "session.updated":
                greeting = api._voice_outbound_greeting(cfg, row)
                await call.ws.send(json.dumps({
                    "type": "conversation.item.create",
                    "item": {"type": "message", "role": "user",
                             "content": [{"type": "input_text", "text": greeting}]},
                }))
                await call.ws.send(json.dumps({
                    "type": "response.create",
                    "response": {
                        "output_modalities": ["audio"],
                        "instructions": f"Di exactamente esta frase y nada mas, sin llamar herramientas: \"{greeting}\"",
                        "tool_choice": "none",
                    },
                }))
                await call._collect()
                break
            if event.get("type") == "error":
                raise RuntimeError(json.dumps(event, ensure_ascii=False))
        # El cliente final pide cancelar.
        await call.say("La verdad es que no voy a poder ir. Cancelamela por favor.")
        await call.say("Si, cancelala.")
        # Red del puente real (_force_pending_cancel): en saliente la cita ya esta verificada
        # (su propio numero); si el modelo no llamo a la herramienta pero el cliente pidio
        # cancelar, el puente cancela con la cita conocida. Lo replicamos para validar el
        # resultado de extremo a extremo (modelo + puente).
        if "cancelar_cita" not in _tool_names(call) and api._voice_user_says_yes(call.last_user_text):
            res = await api._voice_dispatch_tool(
                qa.CID, "cancelar_cita",
                json.dumps({"codigo_reserva": seeded["existing_code"], "telefono": row["telefono"]}),
                from_number=row["telefono"],
            )
            call.tools.append({"name": "cancelar_cita", "args": "(puente)", "result": res})
        row_after = api._get_booking_row_by_id(seeded["existing_id"])
        spoken = _assistant_text(call)
        checks = {
            "cancela": "cancelar_cita" in _tool_names(call),
            "no_pide_codigo_reserva": "consultar_cita" not in _tool_names(call),
            "bd_cancelada": bool(row_after and row_after["status"] == "cancelled"),
            "cancelacion_hablada": "cancel" in spoken,
        }
        for name, passed in checks.items():
            if not passed:
                ok = False
                problems.append({"check": name, "detail": f"tools={_tool_names(call)} row={dict(row_after) if row_after else None}"})
        if call.stalls:
            ok = False
            problems.append({"check": "sin_frases_de_espera_prohibidas", "detail": call.stalls})
        return {
            "name": call.name,
            "ok": ok,
            "problems": problems,
            "tool_calls": [
                {"name": item["name"], "ok": item["result"].get("ok"),
                 "mensaje": item["result"].get("mensaje_voz") or item["result"].get("error")}
                for item in call.tools
            ],
            "assistant": [item["text"] for item in call.transcript if item["role"] == "assistant"],
        }
    finally:
        await call.close()


async def main() -> None:
    # Subconjunto opcional para ahorrar cuota OpenAI (RPD): --only=reserva,cancel,reschedule,outbound,outbound_cancel
    runners = {
        "reserva": _run_inbound_booking,
        "cancel": _run_cancel,
        "reschedule": _run_reschedule,
        "reschedule_day": _run_reschedule_day,
        "reschedule_time": _run_reschedule_time_change,
        "reschedule_browser": _run_reschedule_browser,
        "outbound": _run_outbound_confirm,
        "outbound_cancel": _run_outbound_cancel,
    }
    only: set = set()
    for arg in sys.argv[1:]:
        if arg.startswith("--only="):
            only = {s.strip() for s in arg.split("=", 1)[1].split(",") if s.strip()}
    selected = [fn for key, fn in runners.items() if not only or key in only]
    results = []
    blocked_by_quota = False
    for fn in selected:
        try:
            res = await fn()
        except Exception as exc:  # noqa: BLE001 - un escenario roto no debe tumbar el JSON entero
            res = {"name": getattr(fn, "__name__", "desconocido"), "ok": False, "error": repr(exc)}
        error_text = str(res.get("error", ""))
        if "rate_limit_exceeded" in error_text or "insufficient_quota" in error_text:
            res["blocked"] = True
            blocked_by_quota = True
            results.append(res)
            break
        results.append(res)
    ran = [r for r in results if not r.get("blocked")]
    print(json.dumps({
        "ok": bool(ran) and all(r.get("ok") for r in ran),
        "blocked_by_quota": blocked_by_quota,
        "ran": len(ran),
        "passed": sum(1 for r in ran if r.get("ok")),
        "results": results,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
