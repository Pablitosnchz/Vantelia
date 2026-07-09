from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi.testclient import TestClient

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import qa_voice_realtime_calls as qa  # noqa: E402


def _portal(api) -> Tuple[TestClient, Dict[str, str], Dict[str, str]]:
    from backend import settings

    user = api._get_user_by_email(settings.PORTAL_ADMIN_EMAIL)
    cookies = {"vantelia_portal_session": api._create_auth_session(user["id"])}
    return TestClient(api.app), cookies, {"cliente_id": qa.CID}


def _clear_agenda(api) -> None:
    with api._get_db_connection() as connection:
        connection.execute(
            "DELETE FROM booking_audit WHERE booking_id IN (SELECT id FROM bookings WHERE cliente_id=?)",
            (qa.CID,),
        )
        connection.execute("DELETE FROM bookings WHERE cliente_id=?", (qa.CID,))
        connection.execute("DELETE FROM agenda_blocks WHERE cliente_id=?", (qa.CID,))
        connection.commit()


def _employees(client: TestClient, cookies: Dict[str, str], params: Dict[str, str]) -> List[Dict[str, Any]]:
    response = client.get("/auth/employees", params=params, cookies=cookies)
    response.raise_for_status()
    return list(response.json()["items"])


def _employee_by_name(items: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    needle = text.lower()
    return next(item for item in items if needle in str(item.get("name", "")).lower())


def _set_employee_schedule(
    client: TestClient,
    cookies: Dict[str, str],
    params: Dict[str, str],
    employee_id: str,
    *,
    day_start: str = "09:00",
    day_end: str = "17:00",
    closed_weekdays: List[int],
    break_windows: Optional[List[Dict[str, str]]] = None,
) -> None:
    response = client.post(
        f"/auth/schedule/employee/{employee_id}",
        params=params,
        cookies=cookies,
        json={
            "enabled": True,
            "timezone": "Europe/Madrid",
            "slot_minutes": 30,
            "day_start": day_start,
            "day_end": day_end,
            "break_windows": break_windows or [],
            "closed_weekdays": closed_weekdays,
        },
    )
    response.raise_for_status()


def _set_all_employee_schedules(
    client: TestClient,
    cookies: Dict[str, str],
    params: Dict[str, str],
    *,
    day_start: str = "09:00",
    day_end: str = "17:00",
    closed_weekdays: List[int],
    break_windows: Optional[List[Dict[str, str]]] = None,
) -> None:
    for item in _employees(client, cookies, params):
        _set_employee_schedule(
            client,
            cookies,
            params,
            item["employee_id"],
            day_start=day_start,
            day_end=day_end,
            closed_weekdays=closed_weekdays,
            break_windows=break_windows,
        )


def _create_employee_block(
    client: TestClient,
    cookies: Dict[str, str],
    params: Dict[str, str],
    employee_id: str,
    *,
    fecha: str,
    hora_inicio: str,
    hora_fin: str,
    motivo: str,
) -> None:
    response = client.post(
        f"/auth/employees/{employee_id}/blocks",
        params=params,
        cookies=cookies,
        json={
            "fecha": fecha,
            "hora_inicio": hora_inicio,
            "hora_fin": hora_fin,
            "motivo": motivo,
        },
    )
    response.raise_for_status()


def _last_availability(call: qa.CallHarness) -> Dict[str, Any]:
    for item in reversed(call.tools):
        if item["name"] == "consultar_disponibilidad":
            return item["result"]
    return {}


def _has_availability(call: qa.CallHarness) -> Tuple[bool, str]:
    return bool(_last_availability(call)), f"tools={[item['name'] for item in call.tools]}"


def _no_create(call: qa.CallHarness) -> Tuple[bool, str]:
    creates = [item for item in call.tools if item["name"] == "crear_cita"]
    return not creates, f"crear_cita={creates}"


def _assistant_says_any(words: List[str]):
    def check(call: qa.CallHarness) -> Tuple[bool, str]:
        text = " ".join(item["text"].lower() for item in call.transcript if item["role"] == "assistant")
        return any(word in text for word in words), text

    return check


def _early_slot_refused(expected_date: str):
    """La peticion de las 10:00 con apertura 12:00-14:00 se puede resolver de dos formas
    correctas: consultando las 10:00 (hora_disponible False) o, MEJOR, sabiendo el horario
    por el prompt y ofreciendo directamente solo huecos desde las doce (visto en QA real)."""
    def check(call: qa.CallHarness) -> Tuple[bool, str]:
        result = _last_availability(call)
        if (
            result.get("fecha") == expected_date
            and result.get("hora") == "10:00"
            and result.get("hora_disponible") is False
        ):
            return True, "ok (hora consultada)"
        huecos = result.get("huecos") or []
        early = [h for h in huecos if str(h) < "12:00"]
        text = " ".join(item["text"].lower() for item in call.transcript if item["role"] == "assistant")
        if result.get("fecha") == expected_date and huecos and not early and ("doce" in text or "12" in text):
            return True, "ok (horario del prompt: solo ofrece desde las doce)"
        return False, f"availability={result}"

    return check


def _availability_at(expected_date: str, expected_time: str, available: bool):
    def check(call: qa.CallHarness) -> Tuple[bool, str]:
        result = _last_availability(call)
        ok = (
            result.get("fecha") == expected_date
            and result.get("hora") == expected_time
            and result.get("hora_disponible") is available
        )
        return ok, f"availability={result}"

    return check


async def _run() -> Dict[str, Any]:
    api, settings = qa._setup_runtime()
    if not settings.OPENAI_API_KEY:
        return {"ok": False, "blocked": "OPENAI_API_KEY no configurada"}
    seeded = qa._seed_business(api)
    _clear_agenda(api)
    client, cookies, params = _portal(api)
    employees = _employees(client, cookies, params)
    centro_employee = _employee_by_name(employees, "centro")

    monday = seeded["monday"]
    wednesday = qa._next_weekday(2)
    thursday = qa._next_weekday(3)
    sunday = seeded["sunday"]

    results: List[Dict[str, Any]] = []

    # El usuario cambia Horarios: cierra lunes y miercoles, pero abre domingos.
    _set_all_employee_schedules(
        client,
        cookies,
        params,
        day_start="09:00",
        day_end="17:00",
        closed_weekdays=[0, 2],
    )
    results.append(
        await qa._run_call(
            api,
            settings,
            "horarios_cierra_lunes",
            ["Quiero reservar un masaje el lunes a la una.", "En la sede Centro."],
            {
                "consulta": _has_availability,
                "no_crea": _no_create,
                "dice_cerrado": _assistant_says_any(["cerrado", "cerrados", "cerramos", "no abrimos", "no trabajamos", "no atendemos"]),
            },
        )
    )
    results.append(
        await qa._run_call(
            api,
            settings,
            "horarios_cierra_miercoles",
            ["Quiero reservar un masaje el miercoles a las diez.", "En la sede Centro."],
            {
                "consulta": _has_availability,
                "no_crea": _no_create,
                "dice_cerrado": _assistant_says_any(["cerrado", "cerrados", "cerramos", "no abrimos", "no trabajamos", "no atendemos"]),
            },
        )
    )
    results.append(
        await qa._run_call(
            api,
            settings,
            "horarios_domingo_abierto",
            ["Quiero reservar un masaje el domingo que viene a las diez.", "En la sede Centro."],
            {
                "consulta": _has_availability,
                "no_crea": _no_create,
                "domingo_10_libre": _availability_at(sunday, "10:00", True),
                "dice_hueco": _assistant_says_any(["hay hueco", "a esa hora hay hueco"]),
            },
        )
    )

    # El usuario vuelve a cambiar Horarios: abre solo de 12:00 a 14:00.
    _set_all_employee_schedules(
        client,
        cookies,
        params,
        day_start="12:00",
        day_end="14:00",
        closed_weekdays=[0, 2],
    )
    results.append(
        await qa._run_call(
            api,
            settings,
            "horarios_nuevo_rango_fuera",
            ["Quiero reservar un masaje el jueves a las diez.", "En la sede Centro."],
            {
                "consulta": _has_availability,
                "no_crea": _no_create,
                "jueves_10_no_libre": _early_slot_refused(thursday),
                "dice_cerrado": _assistant_says_any(["cerrado", "cerrados", "no tenemos hueco", "no hay hueco", "a partir de las doce", "abrimos a partir"]),
            },
        )
    )
    results.append(
        await qa._run_call(
            api,
            settings,
            "horarios_nuevo_rango_dentro",
            ["Quiero reservar un masaje el jueves a las doce.", "En la sede Centro."],
            {
                "consulta": _has_availability,
                "no_crea": _no_create,
                "jueves_12_libre": _availability_at(thursday, "12:00", True),
                "dice_hueco": _assistant_says_any(["hay hueco", "a esa hora hay hueco"]),
            },
        )
    )

    # El usuario crea un bloqueo nuevo desde Horarios para esa sede/profesional.
    _create_employee_block(
        client,
        cookies,
        params,
        centro_employee["employee_id"],
        fecha=thursday,
        hora_inicio="12:00",
        hora_fin="12:30",
        motivo="Formacion interna",
    )
    results.append(
        await qa._run_call(
            api,
            settings,
            "horarios_bloqueo_nuevo",
            ["Quiero reservar un masaje el jueves a las doce.", "En la sede Centro."],
            {
                "consulta": _has_availability,
                "no_crea": _no_create,
                "jueves_12_bloqueado": _availability_at(thursday, "12:00", False),
                "dice_bloqueo": _assistant_says_any(["formacion", "bloqueada", "bloqueado"]),
            },
        )
    )

    ok = all(item.get("ok") for item in results)
    return {
        "ok": ok,
        "tenant": qa.CID,
        "lunes": monday,
        "miercoles": wednesday,
        "jueves": thursday,
        "domingo": sunday,
        "results": results,
    }


async def main() -> None:
    print(json.dumps(await _run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
