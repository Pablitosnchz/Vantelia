from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import qa_voice_realtime_calls as qa  # noqa: E402


CheckFn = Callable[[qa.CallHarness], Tuple[bool, str]]


def _assistant_text(call: qa.CallHarness) -> str:
    return " ".join(item["text"].lower() for item in call.transcript if item["role"] == "assistant")


def _has_tool(name: str) -> CheckFn:
    def check(call: qa.CallHarness) -> Tuple[bool, str]:
        tools = [item["name"] for item in call.tools]
        return name in tools, f"tools={tools}"

    return check


def _text_has(words: List[str]) -> CheckFn:
    def check(call: qa.CallHarness) -> Tuple[bool, str]:
        text = _assistant_text(call)
        return any(word in text for word in words), text

    return check


def _no_long_silence(call: qa.CallHarness) -> Tuple[bool, str]:
    bad = [item for item in call.silence_recoveries if float(item.get("elapsed") or 0) > 2.2]
    return not bad, f"recoveries={call.silence_recoveries}"


async def _run_case(
    api,
    settings,
    name: str,
    turns: List[str],
    checks: Dict[str, CheckFn],
    *,
    from_number: str = "",
) -> Dict[str, Any]:
    call = qa.CallHarness(api, settings, name, from_number=from_number, bridge=True)
    ok = True
    problems: List[Dict[str, Any]] = []
    turn_metrics: List[Dict[str, Any]] = []
    try:
        await call.start()
        for index, turn in enumerate(turns, start=1):
            before = len([item for item in call.transcript if item["role"] == "assistant"])
            started = time.monotonic()
            await call.say(turn)
            elapsed = round(time.monotonic() - started, 3)
            after = len([item for item in call.transcript if item["role"] == "assistant"])
            metric = {
                "turn": index,
                "elapsed": elapsed,
                "assistant_delta": after - before,
                "text": turn,
            }
            turn_metrics.append(metric)
            if after == before:
                ok = False
                problems.append({"check": "respuesta_por_turno", "detail": metric})
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
        return {
            "name": name,
            "ok": ok,
            "problems": problems,
            "turn_metrics": turn_metrics,
            "silence_recoveries": call.silence_recoveries,
            "tool_calls": [
                {
                    "name": item["name"],
                    "ok": item["result"].get("ok"),
                    "fecha": item["result"].get("fecha"),
                    "hora": item["result"].get("hora"),
                    "mensaje": item["result"].get("mensaje_voz") or item["result"].get("error"),
                }
                for item in call.tools
            ],
            "assistant": [item["text"] for item in call.transcript if item["role"] == "assistant"],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "ok": False,
            "error": repr(exc),
            "turn_metrics": turn_metrics,
            "silence_recoveries": call.silence_recoveries,
            "assistant": [item["text"] for item in call.transcript if item["role"] == "assistant"],
            "tool_calls": [{"name": item["name"], "args": item["args"]} for item in call.tools],
        }
    finally:
        await call.close()


async def _run() -> Dict[str, Any]:
    api, settings = qa._setup_runtime()
    if not settings.OPENAI_API_KEY:
        return {"ok": False, "blocked": "OPENAI_API_KEY no configurada"}
    seeded = qa._seed_business(api)
    monday = seeded["monday"]
    code = seeded["existing_code"]

    cases = [
        (
            "silencio_frase_ambigua",
            ["Eh... no se, eso de antes."],
            {
                "sin_silencio_largo": _no_long_silence,
                "pide_repetir_o_aclara": _text_has([
                    "repites",
                    "ayudarte",
                    "que necesitas",
                    "que necesites",
                    "no te he entendido",
                    "no te he pillado",
                    "a que te refieres",
                    "que te gustaria",
                    "cuentame",
                    "dime que",
                    # Retomar el contexto tambien es aclarar ("antes te estaba contando
                    # los servicios, quieres que te recuerde alguno?").
                    "te recuerde",
                    "te estaba contando",
                    "quieres que",
                ]),
            },
        ),
        (
            "silencio_reserva_completa",
            [
                "Quiero reservar un masaje el lunes a la una.",
                "En la sede Centro.",
                "Pablo Sanchez, 675 802 001.",
                "Si, correcto.",
            ],
            {
                "sin_silencio_largo": _no_long_silence,
                "consulta": _has_tool("consultar_disponibilidad"),
                "crea": _has_tool("crear_cita"),
                "final": _text_has(["queda confirmada", "queda reservada", "codigo"]),
            },
        ),
        (
            "silencio_bloqueo_agenda",
            ["Quiero reservar un masaje el lunes a las diez.", "En la sede Centro."],
            {
                "sin_silencio_largo": _no_long_silence,
                "consulta": _has_tool("consultar_disponibilidad"),
                "dice_bloqueo": _text_has(["bloqueada", "vacaciones"]),
            },
        ),
        (
            "silencio_servicio_inexistente",
            ["Quiero reservar un tratamiento de teletransportacion."],
            {
                "sin_silencio_largo": _no_long_silence,
                "ofrece_reales": _text_has(["masaje", "sesion", "servicio"]),
            },
        ),
        (
            "silencio_cancelacion",
            [
                f"Quiero cancelar mi cita. El codigo es {code}.",
                "Si, es esa. Mi telefono es 675 802 001.",
                "Si, cancelala.",
            ],
            {
                "sin_silencio_largo": _no_long_silence,
                "consulta": _has_tool("consultar_cita"),
                "cancela": _has_tool("cancelar_cita"),
                "final": _text_has(["cancelado", "cancelada"]),
            },
        ),
    ]
    results = []
    blocked_by_quota = False
    for name, turns, checks in cases:
        item = await _run_case(api, settings, name, turns, checks)
        error_text = str(item.get("error", ""))
        if "rate_limit_exceeded" in error_text or "insufficient_quota" in error_text:
            item["blocked"] = True
            blocked_by_quota = True
            results.append(item)
            break
        results.append(item)
    ran = [item for item in results if not item.get("blocked")]
    return {
        "ok": bool(ran) and all(item.get("ok") for item in ran),
        "blocked_by_quota": blocked_by_quota,
        "ran": len(ran),
        "passed": sum(1 for item in ran if item.get("ok")),
        "tenant": qa.CID,
        "lunes": monday,
        "results": results,
    }


async def main() -> None:
    print(json.dumps(await _run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
