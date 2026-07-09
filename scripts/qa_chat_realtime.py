"""QA del asistente de CHAT contra el modelo real (barato: gpt-4o-mini via RAG).

Espejo ligero de los qa_voice_realtime_*: entorno AISLADO en temp (tenant qa_voice_calls
con servicios, 2 sedes y empleados reales; reutiliza el harness de voz), y una matriz de
situaciones sobre POST /chat. Los flujos DETERMINISTAS (disponibilidad, dia cerrado,
formulario, gestion con memoria) no gastan OpenAI; los de conversacion libre (precios,
servicio inexistente, fuera de ambito, ingles) usan el motor RAG real y requieren
OPENAI_API_KEY (coste: centimos).

Salida: JSON con {"ok": bool, "results": [...]}. Igual que en voz, exit code siempre 0:
hay que leer el "ok" raiz. Matriz documentada en docs/REQUISITOS_ASISTENTE_CHAT.md (8.2).
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import qa_voice_realtime_calls as qa  # noqa: E402  (harness de entorno aislado)

from fastapi.testclient import TestClient  # noqa: E402

Check = Callable[[List[Dict[str, Any]]], Tuple[bool, str]]


def _chat_client(api) -> TestClient:
    return TestClient(api.app)


def _say(client: TestClient, session_id: str, message: str) -> Dict[str, Any]:
    response = client.post(
        "/chat",
        json={"cliente_id": qa.CID, "mensaje": message, "session_id": session_id},
        headers={"Origin": "http://testserver"},
    )
    response.raise_for_status()
    return response.json()


def _run_scenario(
    client: TestClient,
    name: str,
    turns: List[str],
    checks: Dict[str, Check],
) -> Dict[str, Any]:
    session_id = f"qa_chat_{uuid.uuid4().hex[:10]}"
    replies: List[Dict[str, Any]] = []
    try:
        for turn in turns:
            replies.append(_say(client, session_id, turn))
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "ok": False, "error": repr(exc), "replies": replies}
    ok = True
    problems: List[Dict[str, Any]] = []
    for check_name, check_fn in checks.items():
        try:
            passed, detail = check_fn(replies)
        except Exception as exc:  # noqa: BLE001
            passed, detail = False, repr(exc)
        if not passed:
            ok = False
            problems.append({"check": check_name, "detail": detail})
    return {
        "name": name,
        "ok": ok,
        "problems": problems,
        "replies": [
            {"respuesta": r.get("respuesta", "")[:400], "intent": r.get("intent"), "form": r.get("mostrar_formulario")}
            for r in replies
        ],
    }


def _all_text(replies: List[Dict[str, Any]]) -> str:
    return " ".join(str(r.get("respuesta", "")) for r in replies).lower()


def _last_text(replies: List[Dict[str, Any]]) -> str:
    return str(replies[-1].get("respuesta", "")).lower() if replies else ""


def _text_any(words: List[str], *, last_only: bool = False) -> Check:
    def check(replies):
        text = _last_text(replies) if last_only else _all_text(replies)
        return any(w in text for w in words), text[:400]
    return check


def _no_form() -> Check:
    return lambda replies: (
        not any(r.get("mostrar_formulario") for r in replies),
        "abrio formulario indebidamente",
    )


def _form_shown() -> Check:
    return lambda replies: (
        any(r.get("mostrar_formulario") for r in replies),
        "no abrio el formulario",
    )


def _intent_sequence(expected: List[str]) -> Check:
    def check(replies):
        got = [str(r.get("intent") or "") for r in replies]
        return got == expected, f"intents={got} esperado={expected}"
    return check


def main() -> None:
    api, settings = qa._setup_runtime()
    seeded = qa._seed_business(api)
    client = _chat_client(api)
    has_openai = bool(settings.OPENAI_API_KEY)

    results: List[Dict[str, Any]] = []
    blocked_by_quota = False

    # --- Deterministas (sin OpenAI) -----------------------------------------
    results.append(_run_scenario(
        client, "menu_y_quick_actions", ["hola"],
        {
            "es_menu": lambda r: (r[0].get("intent") == "menu", str(r[0])[:200]),
            "quick_manage": lambda r: (
                any(a.get("label") == "Cancelar o cambiar mi cita" for a in (r[0].get("quick_actions") or [])),
                str(r[0].get("quick_actions")),
            ),
        },
    ))
    results.append(_run_scenario(
        client, "dia_cerrado_domingo", ["¿Teneis hueco el domingo?"],
        {
            "dice_cerrado": _text_any(["cerrado", "cerrados", "no abrimos", "cerramos"]),
            "sin_formulario": _no_form(),
        },
    ))
    results.append(_run_scenario(
        client, "disponibilidad_real_lunes", ["¿Que huecos teneis el lunes?"],
        {
            "da_horas": _text_any(["09:", "10:", "11:", "12:"]),
        },
    ))
    results.append(_run_scenario(
        client, "reserva_abre_formulario", ["Quiero reservar un masaje"],
        {"formulario": _form_shown()},
    ))
    results.append(_run_scenario(
        client, "cambiar_fecha_va_a_gestion",
        ["Quiero cambiar la fecha de una cita"],
        {
            "entra_en_gestion": _intent_sequence(["booking_manage"]),
            "pide_codigo": _text_any(["numero de reserva"], last_only=True),
            "no_dice_cerrado": lambda r: (
                "horario de atencion" not in _all_text(r), _last_text(r)[:200]
            ),
        },
    ))
    results.append(_run_scenario(
        client, "cancelacion_con_memoria",
        [
            "Quiero cancelar mi cita",
            f"Es la {seeded['existing_code']}",
            "Mi telefono es 675 802 001",
        ],
        {
            "flujo": _intent_sequence(["booking_manage", "booking_manage", "booking_cancel"]),
            "cancelada_en_bd": lambda r: (
                (api._get_booking_row_by_id(seeded["existing_id"]) or {"status": ""})["status"] == "cancelled",
                str(dict(api._get_booking_row_by_id(seeded["existing_id"]) or {}))[:200],
            ),
        },
    ))

    # --- Con modelo real (gpt-4o-mini, centimos) ----------------------------
    llm_scenarios = [
        (
            # Nota: el modelo puede ofrecer reservar (formulario) tras dar el precio; eso es
            # venta legitima, no un fallo. Lo exigible: datos EXACTOS del catalogo.
            "precio_desde_catalogo", ["¿Cuanto cuesta el masaje y cuanto dura?"],
            {
                "precio_real": _text_any(["10", "diez"]),
                "duracion_real": _text_any(["30", "media hora", "treinta"]),
            },
        ),
        (
            "servicio_inexistente", ["¿Haceis unas de gel?"],
            {
                "no_lo_acepta": _text_any(["no", "masaje", "sesion"]),
                "sin_formulario": _no_form(),
            },
        ),
        (
            "horario_semanal", ["¿Que horario teneis?"],
            {"horario_real": _text_any(["09:00", "9:00", "cerrado", "17:00", "nueve"])},
        ),
        (
            "fuera_de_ambito", ["¿Quien gano la liga este año?"],
            {"redirige": _text_any(["solo puedo", "ayudarte con", "clinica", "negocio", "no puedo ayudarte"])},
        ),
        (
            "ingles", ["What services do you offer and how much is the massage?"],
            {"responde_en_ingles": _text_any(["massage", "masaje"]), "con_precio": _text_any(["10", "ten euro", "€"])},
        ),
    ]
    for name, turns, checks in llm_scenarios:
        if not has_openai:
            results.append({"name": name, "ok": False, "blocked": "OPENAI_API_KEY no configurada"})
            continue
        item = _run_scenario(client, name, turns, checks)
        error_text = str(item.get("error", ""))
        if "rate_limit_exceeded" in error_text or "insufficient_quota" in error_text:
            item["blocked"] = True
            blocked_by_quota = True
        results.append(item)

    ran = [r for r in results if not r.get("blocked")]
    # ensure_ascii: la consola Windows (cp1252) no soporta emojis del widget.
    print(json.dumps({
        "ok": bool(ran) and all(r.get("ok") for r in ran),
        "blocked_by_quota": blocked_by_quota,
        "ran": len(ran),
        "passed": sum(1 for r in ran if r.get("ok")),
        "tenant": qa.CID,
        "results": results,
    }, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
