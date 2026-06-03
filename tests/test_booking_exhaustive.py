"""
Tests exhaustivos de agenda: disponibilidad, solapamientos, descansos, bloqueos,
dias cerrados, horarios por profesional, cancelacion, reprogramacion y flujos
multicanal (web/WhatsApp/voz).

Todos los tests son idempotentes: crean sus propios datos y los limpian al final.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _run_async(coro):
    """Ejecuta una coroutine en un thread separado para evitar conflictos con el event loop del TestClient."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result(timeout=30)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Fixtures — compartidas con test_api_smoke.py via conftest, pero aquí
# se redefinen autónomas para que el módulo sea independiente.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def api_module(tmp_path_factory: pytest.TempPathFactory):
    runtime_dir = tmp_path_factory.mktemp("vantelia-booking-exhaustive")
    data_dir = runtime_dir / "data"
    storage_dir = runtime_dir / "storage"
    config_path = runtime_dir / "config.json"
    client_dir = data_dir / "demo"
    client_dir.mkdir(parents=True)
    storage_dir.mkdir(parents=True)

    (client_dir / "info.txt").write_text(
        "===== DEMO =====\nSERVICIOS Y PRECIOS:\n- Consulta\n  - Precio: 50 EUR\n",
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps({
            "demo": {
                "nombre": "Demo Booking",
                "icono": "DB",
                "color": "#00b1d9",
                "bienvenida": "Hola.",
                "prompt_extra": "",
                "allowed_origins": ["http://testserver"],
                "contacto": {"email": "test@demo.es", "telefono": "+34600000000"},
                "branding": {"powered_by": "Vantelia"},
                "plan": "business",
                "subscription": {"plan": "business", "status": "active"},
                "whatsapp": {"enabled": True, "phone_number_id": "WA_NUM_ID"},
                "booking": {
                    "enabled": True,
                    "timezone": "Europe/Madrid",
                    "slot_minutes": 30,
                    "day_start": "09:00",
                    "day_end": "18:00",
                    "closed_weekdays": [6],   # domingo cerrado
                    "provider": "internal",
                    "success_message": "Cita confirmada.",
                },
            }
        }, indent=2),
        encoding="utf-8",
    )

    os.environ.update({
        "VANTELIA_DATA_DIR": str(data_dir),
        "VANTELIA_STORAGE_DIR": str(storage_dir),
        "VANTELIA_CONFIG_PATH": str(config_path),
        "OPENAI_API_KEY": "",
        "ADMIN_API_TOKEN": "test-admin-token",
        "PORTAL_ADMIN_EMAIL": "admin@example.com",
        "PORTAL_ADMIN_PASSWORD": "admin-password-123",
        "APP_BASE_URL": "https://app.test.local",
        "PORTAL_COOKIE_NAME": "vantelia_portal_session",
        "PORTAL_COOKIE_DOMAIN": "",
        "REMINDER_RUN_INTERVAL_MINUTES": "0",
        "WEBHOOK_DEFAULT": "",
        "EXTRA_CORS_ORIGINS": "http://testserver",
        "WHATSAPP_VERIFY_TOKEN": "wa-verify-token",
        "WHATSAPP_ACCESS_TOKEN": "",
        "WHATSAPP_APP_SECRET": "",
        "STRIPE_SECRET_KEY": "sk_test_dummy",
        "STRIPE_WEBHOOK_SECRET": "",
        "STRIPE_PRICE_STARTER": "price_test_starter",
        "STRIPE_PRICE_PRO": "price_test_pro",
        "STRIPE_PRICE_BUSINESS": "price_test_business",
        "STRIPE_PRICE_STARTER_ANNUAL": "price_test_starter_annual",
        "STRIPE_PRICE_PRO_ANNUAL": "price_test_pro_annual",
        "STRIPE_PRICE_BUSINESS_ANNUAL": "price_test_business_annual",
        "OUTREACH_DB_PATH": str(storage_dir / "outreach" / "outreach.db"),
        "OUTREACH_TRACKING_SECRET": "test-outreach-secret",
        "OUTREACH_TRACKING_BASE_URL": "https://app.test.local",
        "OUTREACH_RESPECT_WINDOW": "false",
        "MAX_BOOKING_ADVANCE_DAYS": "60",
    })
    sys.modules.pop("api", None)
    return importlib.import_module("api")


@pytest.fixture(scope="module")
def client(api_module):
    return TestClient(api_module.app)


@pytest.fixture(scope="module")
def admin_cookies(client: TestClient):
    r = client.post("/auth/login", json={"email": "admin@example.com", "password": "admin-password-123"})
    assert r.status_code == 200, r.text
    return {"vantelia_portal_session": r.cookies["vantelia_portal_session"]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_weekday(offset: int = 1, skip_weekdays: tuple = (6,)) -> str:
    """Devuelve la fecha del próximo día hábil (no cerrado) a partir de hoy+offset."""
    d = datetime.utcnow().date() + timedelta(days=offset)
    while d.weekday() in skip_weekdays:
        d += timedelta(days=1)
    return d.isoformat()


def _make_employee(client: TestClient, cookies: dict, **overrides) -> str:
    """Crea un profesional de prueba y devuelve su employee_id."""
    payload = {
        "name": f"Prof {uuid.uuid4().hex[:6]}",
        "role_label": "Pruebas",
        "color": "#00b1d9",
        "is_active": True,
        "timezone": "Europe/Madrid",
        "slot_minutes": 30,
        "day_start": "09:00",
        "day_end": "18:00",
        "break_windows": [],
        "closed_weekdays": [],
        "service_ids": [],
    }
    payload.update(overrides)
    r = client.post("/auth/employees", params={"cliente_id": "demo"}, cookies=cookies, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["employee_id"]


def _delete_employee(client: TestClient, cookies: dict, employee_id: str):
    client.delete(f"/auth/employees/{employee_id}", params={"cliente_id": "demo"}, cookies=cookies)


def _slots_map(client: TestClient, fecha: str, employee_id: str, servicio: str = "") -> dict:
    """Devuelve {hora: disponible} para la fecha y profesional dados."""
    r = client.get(
        "/disponibilidad",
        params={"cliente_id": "demo", "fecha": fecha, "employee_id": employee_id, "servicio": servicio},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200, r.text
    return {s["hora"]: s["disponible"] for s in r.json()["slots"]}


def _book(client: TestClient, cookies: dict, fecha: str, hora: str, employee_id: str = "",
          servicio: str = "", nombre: str = "Test") -> dict:
    r = client.post(
        "/auth/bookings",
        params={"cliente_id": "demo"},
        cookies=cookies,
        json={"nombre": nombre, "email": "test@test.es", "telefono": "", "servicio": servicio,
              "employee_id": employee_id, "fecha": fecha, "hora": hora, "notas": ""},
    )
    return r


def _cleanup_booking(api_module, booking_id: str):
    with api_module._get_db_connection() as conn:
        conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conn.commit()


# ===========================================================================
# 1. DÍAS CERRADOS
# ===========================================================================

def test_closed_weekday_returns_no_available_slots(client: TestClient, api_module, admin_cookies: dict):
    """El domingo (weekday=6) está cerrado: /disponibilidad no debe devolver huecos disponibles."""
    # Encontrar próximo domingo.
    d = datetime.utcnow().date() + timedelta(days=1)
    while d.weekday() != 6:
        d += timedelta(days=1)
    fecha = d.isoformat()

    r = client.get(
        "/disponibilidad",
        params={"cliente_id": "demo", "fecha": fecha},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200
    payload = r.json()
    available = [s for s in payload["slots"] if s["disponible"]]
    assert available == [], f"No debería haber huecos el domingo, pero hay {len(available)}"


def test_closed_weekday_rejects_booking(client: TestClient, api_module, admin_cookies: dict):
    """Intentar crear una cita en domingo vía portal debe devolver 409."""
    d = datetime.utcnow().date() + timedelta(days=1)
    while d.weekday() != 6:
        d += timedelta(days=1)
    fecha = d.isoformat()

    r = _book(client, admin_cookies, fecha, "10:00")
    assert r.status_code == 409, f"Esperaba 409 en día cerrado, obtuvo {r.status_code}"


# ===========================================================================
# 2. FUERA DE HORARIO
# ===========================================================================

def test_slot_before_day_start_not_offered(client: TestClient, api_module, admin_cookies: dict):
    """Las 08:00 están antes del day_start (09:00) y no deben aparecer disponibles."""
    fecha = _next_weekday(2)
    employee_id = _make_employee(client, admin_cookies, day_start="09:00", day_end="18:00")
    try:
        slots = _slots_map(client, fecha, employee_id)
        assert "08:00" not in slots, "Slot antes de day_start no debe aparecer"
        assert "08:30" not in slots
        assert slots.get("09:00") is True, "El primer slot válido debe ser 09:00"
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_slot_at_or_after_day_end_not_offered(client: TestClient, api_module, admin_cookies: dict):
    """Los slots que empiezan en day_end o después no deben aparecer."""
    fecha = _next_weekday(2)
    employee_id = _make_employee(client, admin_cookies, day_start="09:00", day_end="11:00", slot_minutes=30)
    try:
        slots = _slots_map(client, fecha, employee_id)
        assert "11:00" not in slots, "day_end mismo no debe ser hueco (no cabe servicio de 30 min)"
        assert "11:30" not in slots
        assert slots.get("10:30") is True, "El último slot válido es day_end - slot = 10:30"
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_booking_before_day_start_rejected(client: TestClient, api_module, admin_cookies: dict):
    """Intentar reservar a las 07:00 cuando day_start=09:00 debe devolver 409."""
    fecha = _next_weekday(3)
    employee_id = _make_employee(client, admin_cookies, day_start="09:00", day_end="18:00")
    try:
        r = _book(client, admin_cookies, fecha, "07:00", employee_id=employee_id)
        assert r.status_code == 409
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_booking_at_day_end_rejected(client: TestClient, api_module, admin_cookies: dict):
    """Reservar exactamente en day_end debe rechazarse (el servicio no cabe)."""
    fecha = _next_weekday(3)
    employee_id = _make_employee(client, admin_cookies, day_start="09:00", day_end="11:00", slot_minutes=30)
    try:
        r = _book(client, admin_cookies, fecha, "11:00", employee_id=employee_id)
        assert r.status_code == 409
    finally:
        _delete_employee(client, admin_cookies, employee_id)


# ===========================================================================
# 3. BLOQUEOS DE AGENDA (schedule blocks)
# ===========================================================================

def test_full_day_agenda_block_makes_all_slots_unavailable(client: TestClient, api_module, admin_cookies: dict):
    """Un bloqueo sin horas (todo el día) elimina todos los huecos disponibles."""
    fecha = _next_weekday(5)
    employee_id = _make_employee(client, admin_cookies)
    try:
        # Verificar que hay huecos antes del bloqueo.
        slots_before = _slots_map(client, fecha, employee_id)
        assert any(v for v in slots_before.values()), "Debe haber huecos antes del bloqueo"

        # Crear bloqueo de todo el día.
        r = client.post(
            f"/auth/employees/{employee_id}/blocks",
            params={"cliente_id": "demo"},
            cookies=admin_cookies,
            json={"fecha": fecha, "fecha_fin": fecha, "hora_inicio": "00:00", "hora_fin": "23:59",
                  "motivo": "Formación"},
        )
        assert r.status_code == 200, r.text

        slots_after = _slots_map(client, fecha, employee_id)
        available_after = [h for h, v in slots_after.items() if v]
        assert available_after == [], f"Con bloqueo total no debe haber huecos, pero hay: {available_after}"
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_partial_agenda_block_only_affects_covered_slots(client: TestClient, api_module, admin_cookies: dict):
    """Un bloqueo 11:00-12:00 marca como no disponibles los slots cubiertos; antes y después siguen disponibles."""
    fecha = _next_weekday(5)
    employee_id = _make_employee(client, admin_cookies, day_start="09:00", day_end="14:00")
    try:
        r = client.post(
            f"/auth/employees/{employee_id}/blocks",
            params={"cliente_id": "demo"},
            cookies=admin_cookies,
            json={"fecha": fecha, "fecha_fin": fecha, "hora_inicio": "11:00", "hora_fin": "12:00",
                  "motivo": "Reunión"},
        )
        assert r.status_code == 200, r.text

        slots = _slots_map(client, fecha, employee_id)
        assert slots.get("09:00") is True
        assert slots.get("10:30") is True
        # Los slots dentro del bloqueo aparecen en la respuesta pero como no disponibles
        assert slots.get("11:00") is False, "11:00 está bloqueado"
        assert slots.get("11:30") is False, "11:30 solapa el bloqueo"
        assert slots.get("12:00") is True
        assert slots.get("13:30") is True
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_booking_during_agenda_block_rejected(client: TestClient, api_module, admin_cookies: dict):
    """Crear una cita en horario bloqueado debe devolver 409."""
    fecha = _next_weekday(6)
    employee_id = _make_employee(client, admin_cookies, day_start="09:00", day_end="14:00")
    try:
        client.post(
            f"/auth/employees/{employee_id}/blocks",
            params={"cliente_id": "demo"},
            cookies=admin_cookies,
            json={"fecha": fecha, "fecha_fin": fecha, "hora_inicio": "10:00", "hora_fin": "12:00",
                  "motivo": "Bloqueo test"},
        )
        r = _book(client, admin_cookies, fecha, "10:00", employee_id=employee_id)
        assert r.status_code == 409
        r2 = _book(client, admin_cookies, fecha, "11:30", employee_id=employee_id)
        assert r2.status_code == 409
    finally:
        _delete_employee(client, admin_cookies, employee_id)


# ===========================================================================
# 4. DESCANSOS (break_windows)
# ===========================================================================

def test_break_window_slots_absent_from_availability(client: TestClient, api_module, admin_cookies: dict):
    """Slots dentro de un break_window no deben aparecer en /disponibilidad."""
    fecha = _next_weekday(4)
    employee_id = _make_employee(
        client, admin_cookies,
        day_start="09:00", day_end="18:00",
        break_windows=[{"start": "13:00", "end": "14:00", "reason": "Comida"}],
    )
    try:
        slots = _slots_map(client, fecha, employee_id)
        assert "13:00" not in slots
        assert "13:30" not in slots
        assert slots.get("12:30") is True
        assert slots.get("14:00") is True
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_multiple_break_windows_all_blocked(client: TestClient, api_module, admin_cookies: dict):
    """Dos descansos distintos: ambos bloquean sus slots; los intervalos entre ellos están libres."""
    fecha = _next_weekday(4)
    employee_id = _make_employee(
        client, admin_cookies,
        day_start="09:00", day_end="18:00",
        break_windows=[
            {"start": "10:30", "end": "11:00", "reason": "Pausa mañana"},
            {"start": "14:00", "end": "15:00", "reason": "Comida"},
        ],
    )
    try:
        slots = _slots_map(client, fecha, employee_id)
        # Primera pausa
        assert "10:30" not in slots
        # Entre pausas: libre
        assert slots.get("11:00") is True
        assert slots.get("13:30") is True
        # Segunda pausa
        assert "14:00" not in slots
        assert "14:30" not in slots
        # Después: libre
        assert slots.get("15:00") is True
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_booking_during_break_rejected(client: TestClient, api_module, admin_cookies: dict):
    """Intentar crear una cita manual en pleno descanso debe devolver 409."""
    fecha = _next_weekday(4)
    employee_id = _make_employee(
        client, admin_cookies,
        day_start="09:00", day_end="18:00",
        break_windows=[{"start": "13:00", "end": "14:00", "reason": "Comida"}],
    )
    try:
        r = _book(client, admin_cookies, fecha, "13:00", employee_id=employee_id)
        assert r.status_code == 409
        r2 = _book(client, admin_cookies, fecha, "13:30", employee_id=employee_id)
        assert r2.status_code == 409
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_long_service_blocked_before_break_starts(client: TestClient, api_module, admin_cookies: dict):
    """Un servicio de 60 min no debe poder empezar 30 min antes del descanso (solaparía)."""
    fecha = _next_weekday(5)
    employee_id = _make_employee(
        client, admin_cookies,
        day_start="09:00", day_end="18:00", slot_minutes=30,
        break_windows=[{"start": "13:00", "end": "14:00", "reason": "Comida"}],
    )
    svc_r = client.post("/auth/services", params={"cliente_id": "demo"}, cookies=admin_cookies,
                        json={"nombre": f"Larga {uuid.uuid4().hex[:6]}", "duration_minutes": 60, "price_cents": 0})
    assert svc_r.status_code == 200, svc_r.text
    svc_slug = svc_r.json()["id"]
    svc_name = svc_r.json()["nombre"]
    try:
        slots = _slots_map(client, fecha, employee_id, servicio=svc_name)
        # Las 12:30 empezaría a las 12:30 y terminaría a las 13:30 → solapa descanso
        assert "12:30" not in slots, "12:30 con servicio de 60 min solapa el descanso de 13:00"
        # Las 12:00 terminaría a las 13:00 → borde exacto del descanso, debe estar disponible
        assert slots.get("12:00") is True
    finally:
        _delete_employee(client, admin_cookies, employee_id)
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM services WHERE cliente_id='demo' AND slug=?", (svc_slug,))
            conn.commit()


# ===========================================================================
# 5. SOLAPAMIENTOS Y LIBERACIÓN DE HUECOS
# ===========================================================================

def test_cancel_releases_slot_for_new_booking(client: TestClient, api_module, admin_cookies: dict):
    """Cancelar una cita libera el hueco, que puede volver a reservarse."""
    fecha = _next_weekday(7)
    employee_id = _make_employee(client, admin_cookies)
    try:
        r1 = _book(client, admin_cookies, fecha, "10:00", employee_id=employee_id)
        assert r1.status_code == 200, r1.text
        booking_id = r1.json()["booking_id"]

        # El hueco está ocupado: otro booking en el mismo slot → 409
        r_conflict = _book(client, admin_cookies, fecha, "10:00", employee_id=employee_id)
        assert r_conflict.status_code == 409

        # Cancelar la cita original
        r_cancel = client.post(
            f"/auth/bookings/{booking_id}/cancel",
            params={"cliente_id": "demo"},
            cookies=admin_cookies,
        )
        assert r_cancel.status_code == 200

        # Ahora el hueco debe estar disponible de nuevo
        slots = _slots_map(client, fecha, employee_id)
        assert slots.get("10:00") is True, "El slot debe estar libre tras cancelar"

        # Y se puede reservar de nuevo
        r2 = _book(client, admin_cookies, fecha, "10:00", employee_id=employee_id)
        assert r2.status_code == 200, r2.text
        _cleanup_booking(api_module, r2.json()["booking_id"])
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_overlapping_services_of_different_durations(client: TestClient, api_module, admin_cookies: dict):
    """Cita A de 60 min a las 10:00 bloquea también las 10:30; cita B de 30 min a las 11:00 es válida."""
    fecha = _next_weekday(8)
    employee_id = _make_employee(client, admin_cookies, day_start="09:00", day_end="18:00", slot_minutes=30)
    svc_r = client.post("/auth/services", params={"cliente_id": "demo"}, cookies=admin_cookies,
                        json={"nombre": f"Sesion60 {uuid.uuid4().hex[:6]}", "duration_minutes": 60, "price_cents": 0})
    assert svc_r.status_code == 200
    svc_name = svc_r.json()["nombre"]
    svc_slug = svc_r.json()["id"]
    booking_a_id = ""
    booking_b_id = ""
    try:
        ra = _book(client, admin_cookies, fecha, "10:00", employee_id=employee_id, servicio=svc_name)
        assert ra.status_code == 200, ra.text
        booking_a_id = ra.json()["booking_id"]

        # 10:30 solapa con A (que termina a las 11:00)
        r_overlap = _book(client, admin_cookies, fecha, "10:30", employee_id=employee_id)
        assert r_overlap.status_code == 409

        # 11:00 es adyacente (no solapa) → OK
        rb = _book(client, admin_cookies, fecha, "11:00", employee_id=employee_id)
        assert rb.status_code == 200, rb.text
        booking_b_id = rb.json()["booking_id"]
    finally:
        for bid in (booking_a_id, booking_b_id):
            if bid:
                _cleanup_booking(api_module, bid)
        _delete_employee(client, admin_cookies, employee_id)
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM services WHERE cliente_id='demo' AND slug=?", (svc_slug,))
            conn.commit()


# ===========================================================================
# 6. LÍMITE DE ANTELACIÓN
# ===========================================================================

def test_booking_beyond_advance_limit_rejected(client: TestClient, api_module, admin_cookies: dict):
    """Reservar más allá de MAX_BOOKING_ADVANCE_DAYS (60 en el fixture) debe devolver 409."""
    d = datetime.utcnow().date() + timedelta(days=90)  # 30 días más allá del límite
    while d.weekday() == 6:
        d += timedelta(days=1)
    fecha = d.isoformat()

    r = _book(client, admin_cookies, fecha, "10:00")
    assert r.status_code in (400, 409), f"Esperaba 400/409 por límite de antelación, obtuvo {r.status_code}: {r.text}"


# ===========================================================================
# 7. HORARIO ESPECÍFICO POR PROFESIONAL vs GLOBAL
# ===========================================================================

def test_employee_specific_schedule_overrides_global(client: TestClient, api_module, admin_cookies: dict):
    """El profesional con day_start=10:00/day_end=13:00 no debe ofrecer el slot de las 09:00
    aunque el horario global lo permita."""
    fecha = _next_weekday(3)
    employee_id = _make_employee(
        client, admin_cookies,
        day_start="10:00", day_end="13:00", slot_minutes=30,
    )
    try:
        slots = _slots_map(client, fecha, employee_id)
        assert "09:00" not in slots, "Fuera del horario del profesional"
        assert "09:30" not in slots
        assert slots.get("10:00") is True
        assert slots.get("12:30") is True
        assert "13:00" not in slots
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_employee_slot_minutes_determines_grid(client: TestClient, api_module, admin_cookies: dict):
    """Un profesional con slot_minutes=45 muestra huecos cada 45 min, no cada 30."""
    fecha = _next_weekday(3)
    employee_id = _make_employee(
        client, admin_cookies,
        day_start="09:00", day_end="12:00", slot_minutes=45,
    )
    try:
        slots = _slots_map(client, fecha, employee_id)
        hora_keys = list(slots.keys())
        # Con slot=45 los huecos deben ser 09:00, 09:45, 10:30, 11:15
        assert "09:00" in hora_keys
        assert "09:30" not in hora_keys, "Con slot=45 no debe haber 09:30"
        assert "09:45" in hora_keys
        assert "10:30" in hora_keys
        assert "11:15" in hora_keys
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_employee_closed_weekday_independent_of_global(client: TestClient, api_module, admin_cookies: dict):
    """Un profesional con lunes cerrado no ofrece slots el lunes aunque el global sí lo haga."""
    # Encontrar próximo lunes (weekday=0)
    d = datetime.utcnow().date() + timedelta(days=1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    fecha = d.isoformat()

    employee_id = _make_employee(client, admin_cookies, closed_weekdays=[0])
    try:
        slots = _slots_map(client, fecha, employee_id)
        available = [h for h, v in slots.items() if v]
        assert available == [], f"Profesional tiene lunes cerrado; no debe haber huecos: {available}"
    finally:
        _delete_employee(client, admin_cookies, employee_id)


# ===========================================================================
# 8. CANCELAR Y REPROGRAMAR VÍA manage_token (enlace público)
# ===========================================================================

def test_public_manage_token_cancel(client: TestClient, api_module, admin_cookies: dict):
    """Cancelar una cita a través del manage_token público cambia el estado a cancelled."""
    fecha = _next_weekday(5)
    r = _book(client, admin_cookies, fecha, "09:00")
    assert r.status_code == 200, r.text
    booking_id = r.json()["booking_id"]
    manage_url = r.json()["manage_url"]
    token = manage_url.rsplit("/", 1)[-1].split("?")[0]
    try:
        cancel_r = client.post(f"/booking/manage/{token}/cancel")
        assert cancel_r.status_code == 200, cancel_r.text
        with api_module._get_db_connection() as conn:
            row = conn.execute("SELECT status FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        assert row[0] == "cancelled"
    finally:
        _cleanup_booking(api_module, booking_id)


def test_public_manage_token_reschedule(client: TestClient, api_module, admin_cookies: dict):
    """Reprogramar vía manage_token actualiza la cita in-place con la nueva fecha/hora."""
    fecha_orig = _next_weekday(5)
    nueva_fecha = _next_weekday(10)
    r = _book(client, admin_cookies, fecha_orig, "09:00")
    assert r.status_code == 200, r.text
    booking_id = r.json()["booking_id"]
    manage_url = r.json()["manage_url"]
    token = manage_url.rsplit("/", 1)[-1].split("?")[0]
    try:
        resched_r = client.post(
            f"/booking/manage/{token}/reschedule",
            json={"fecha": nueva_fecha, "hora": "10:00"},
        )
        assert resched_r.status_code == 200, resched_r.text
        data = resched_r.json()
        assert data.get("ok") is True
        # La misma cita se actualiza in-place: mismo booking_id, nueva fecha
        with api_module._get_db_connection() as conn:
            row = conn.execute("SELECT booking_date, booking_time, status FROM bookings WHERE id = ?",
                               (booking_id,)).fetchone()
        assert row[0] == nueva_fecha, f"La fecha debe haberse actualizado a {nueva_fecha}"
        assert row[1] == "10:00"
        assert row[2] == "confirmed"
    finally:
        _cleanup_booking(api_module, booking_id)


def test_public_manage_token_invalid_token_returns_404(client: TestClient):
    """Un token inválido debe devolver 404 o 400, no 500."""
    r = client.post("/booking/manage/token-completamente-invalido/cancel")
    assert r.status_code in (400, 404)


def test_cancelled_booking_cancel_is_idempotent(client: TestClient, api_module, admin_cookies: dict):
    """Cancelar dos veces la misma cita es idempotente: la segunda devuelve ok=True indicando que ya estaba cancelada."""
    fecha = _next_weekday(5)
    r = _book(client, admin_cookies, fecha, "09:30")
    assert r.status_code == 200, r.text
    booking_id = r.json()["booking_id"]
    manage_url = r.json()["manage_url"]
    token = manage_url.rsplit("/", 1)[-1].split("?")[0]
    try:
        r1 = client.post(f"/booking/manage/{token}/cancel")
        assert r1.status_code == 200
        assert r1.json()["estado"] == "cancelled"

        r2 = client.post(f"/booking/manage/{token}/cancel")
        assert r2.status_code == 200, "Segunda cancelación debe ser idempotente"
        assert r2.json()["ok"] is True
        assert r2.json()["estado"] == "cancelled"
    finally:
        _cleanup_booking(api_module, booking_id)


# ===========================================================================
# 9. CANAL WHATSAPP — reserva, cancelación, reprogramación
# ===========================================================================

def test_whatsapp_cancel_via_handle_message(api_module, monkeypatch):
    """El handler de WhatsApp cancela una cita cuando el usuario envía el código."""
    wa_responses: list[str] = []

    async def _fake_send(*, cliente_id, phone_number_id, to_number, text):
        wa_responses.append(text)
        return True

    async def _noop_cancel(_row):
        return None

    async def _noop_email(*_a, **_kw):
        return True

    monkeypatch.setattr(api_module, "_send_whatsapp_text", _fake_send)
    monkeypatch.setattr(api_module, "_cancel_provider_booking", _noop_cancel)
    monkeypatch.setattr(api_module, "_send_booking_email_by_kind", _noop_email)

    phone = "34601000001"
    record = {
        "id": f"bk_wa_cancel_{uuid.uuid4().hex[:8]}",
        "cliente_id": "demo", "employee_id": "", "employee_name": "",
        "nombre": "WA Cancel", "email": "", "telefono": phone,
        "servicio": "Consulta", "booking_date": _next_weekday(20),
        "booking_time": "10:00", "notas": "", "status": "confirmed",
        "provider_name": "internal", "provider_status": "confirmed",
        "provider_booking_id": "", "provider_booking_url": "",
        "manage_token": f"mg_wac_{uuid.uuid4().hex[:8]}",
        "timezone": "Europe/Madrid", "start_at": "", "end_at": "",
        "confirmed_at": api_module._utc_now_iso(), "cancelled_at": "",
        "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": "",
        "reminder_2h_sent_at": "", "customer_email_status": "",
        "customer_email_last_error": "", "source": "whatsapp",
        "created_at": api_module._utc_now_iso(),
    }
    api_module._store_booking(record)
    code = record["booking_code"]
    try:
        _run_async(api_module._handle_whatsapp_message(
            cliente_id="demo",
            phone_number_id="WA_NUM_ID",
            from_number=phone,
            incoming_text=f"Cancelar cita {code}",
            interactive_id="",
            request=None,
        ))
        assert any("cancelada" in m.lower() for m in wa_responses), \
            f"Respuesta de cancelación esperada, obtuvo: {wa_responses}"
        with api_module._get_db_connection() as conn:
            status = conn.execute("SELECT status FROM bookings WHERE id = ?", (record["id"],)).fetchone()[0]
        assert status == "cancelled"
    finally:
        api_module._wa_clear_flow("demo", phone)
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_whatsapp_reschedule_booking_by_code(api_module, monkeypatch):
    """El usuario de WhatsApp puede reprogramar su cita enviando el código y los nuevos datos."""
    wa_responses: list[str] = []
    reschedule_calls: list[dict] = []

    async def _fake_send(*, cliente_id, phone_number_id, to_number, text):
        wa_responses.append(text)
        return True

    async def _fake_update(row, payload, request, *, source, audit_payload=None):
        reschedule_calls.append({
            "booking_id": row["id"],
            "fecha": payload.fecha,
            "hora": payload.hora,
            "source": source,
        })
        return api_module.BookingActionResponse(
            ok=True,
            booking_id=row["id"],
            estado="confirmed",
            mensaje="Cita reprogramada.",
            employee_id="", employee_name="", manage_url="", provider_booking_url="",
        )

    monkeypatch.setattr(api_module, "_send_whatsapp_text", _fake_send)
    monkeypatch.setattr(api_module, "_update_booking_details", _fake_update)

    record = {
        "id": f"bk_wa_resched_{uuid.uuid4().hex[:8]}",
        "cliente_id": "demo", "employee_id": "", "employee_name": "",
        "nombre": "Usuario WA", "email": "usuario.wa@test.es", "telefono": "34600222333",
        "servicio": "Consulta", "booking_date": _next_weekday(15),
        "booking_time": "09:00", "notas": "", "status": "confirmed",
        "provider_name": "internal", "provider_status": "confirmed",
        "provider_booking_id": "", "provider_booking_url": "",
        "manage_token": f"mg_wa_{uuid.uuid4().hex[:8]}",
        "timezone": "Europe/Madrid", "start_at": "", "end_at": "",
        "confirmed_at": api_module._utc_now_iso(), "cancelled_at": "",
        "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": "",
        "reminder_2h_sent_at": "", "customer_email_status": "",
        "customer_email_last_error": "", "source": "whatsapp",
        "created_at": api_module._utc_now_iso(),
    }
    api_module._store_booking(record)
    code = record["booking_code"]

    try:
        _run_async(api_module._handle_whatsapp_message(
            cliente_id="demo",
            phone_number_id="WA_NUM_ID",
            from_number="34600222333",
            incoming_text=f"Quiero cambiar la cita {code} al {_next_weekday(20)} a las 11:00",
            interactive_id="",
            request=None,
        ))
        assert reschedule_calls, "Debe haberse llamado a _update_booking_details"
        assert reschedule_calls[0]["hora"] == "11:00"
        assert reschedule_calls[0]["source"] == "whatsapp"
        assert any(any(w in m.lower() for w in ("reprogramad", "actualizad", "cambiad", "listo"))
                   for m in wa_responses), f"Respuesta WA inesperada: {wa_responses}"
    finally:
        api_module._wa_clear_flow("demo", "34600222333")
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


def test_whatsapp_booking_disabled_no_booking_created(api_module, monkeypatch):
    """Sin agenda activa, el handler de WhatsApp no debe crear citas aunque llegue un código."""
    wa_responses: list[str] = []

    async def _fake_send(*, cliente_id, phone_number_id, to_number, text):
        wa_responses.append(text)
        return True

    async def _noop_cancel(_row):
        return None

    async def _noop_email(*_a, **_kw):
        return True

    monkeypatch.setattr(api_module, "_send_whatsapp_text", _fake_send)
    monkeypatch.setattr(api_module, "_cancel_provider_booking", _noop_cancel)
    monkeypatch.setattr(api_module, "_send_booking_email_by_kind", _noop_email)

    # Crear una cita real, luego desactivar booking e intentar cancelarla por WA
    phone = "34602000001"
    record = {
        "id": f"bk_wa_dis_{uuid.uuid4().hex[:8]}",
        "cliente_id": "demo", "employee_id": "", "employee_name": "",
        "nombre": "WA Disabled", "email": "", "telefono": phone,
        "servicio": "Consulta", "booking_date": _next_weekday(25),
        "booking_time": "10:00", "notas": "", "status": "confirmed",
        "provider_name": "internal", "provider_status": "confirmed",
        "provider_booking_id": "", "provider_booking_url": "",
        "manage_token": f"mg_wad_{uuid.uuid4().hex[:8]}",
        "timezone": "Europe/Madrid", "start_at": "", "end_at": "",
        "confirmed_at": api_module._utc_now_iso(), "cancelled_at": "",
        "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": "",
        "reminder_2h_sent_at": "", "customer_email_status": "",
        "customer_email_last_error": "", "source": "whatsapp",
        "created_at": api_module._utc_now_iso(),
    }
    api_module._store_booking(record)
    code = record["booking_code"]

    original = api_module.CONFIG_CLIENTES["demo"]["booking"]["enabled"]
    api_module.CONFIG_CLIENTES["demo"]["booking"]["enabled"] = False
    try:
        _run_async(api_module._handle_whatsapp_message(
            cliente_id="demo",
            phone_number_id="WA_NUM_ID",
            from_number=phone,
            incoming_text=f"Cancelar {code}",
            interactive_id="",
            request=None,
        ))
        # La cita NO debe haberse cancelado porque booking está desactivado
        with api_module._get_db_connection() as conn:
            status = conn.execute("SELECT status FROM bookings WHERE id = ?", (record["id"],)).fetchone()[0]
        assert status == "confirmed", "Con booking desactivado, la cita no debe cancelarse por WA"
    finally:
        api_module.CONFIG_CLIENTES["demo"]["booking"]["enabled"] = original
        api_module._wa_clear_flow("demo", phone)
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            conn.commit()


# ===========================================================================
# 10. CANAL VOZ — disponibilidad y reserva con restricciones de agenda
# ===========================================================================

def test_voice_availability_excludes_break_windows(api_module, client, admin_cookies):
    """_voice_check_availability no ofrece horas dentro del break_window del profesional por defecto."""
    fecha = _next_weekday(3)
    # Actualizar el horario general para incluir un descanso
    r = client.post(
        "/auth/schedule",
        params={"cliente_id": "demo"},
        cookies=admin_cookies,
        json={
            "enabled": True,
            "timezone": "Europe/Madrid",
            "slot_minutes": 30,
            "day_start": "09:00",
            "day_end": "18:00",
            "break_windows": [{"start": "12:00", "end": "13:00", "reason": "Comida"}],
            "closed_weekdays": [6],
        },
    )
    assert r.status_code == 200, r.text
    try:
        result = _run_async(api_module._voice_check_availability("demo", fecha))
        assert result["ok"] is True, result
        huecos = result.get("huecos", [])
        assert "12:00" not in huecos, "El descanso no debe aparecer en huecos de voz"
        assert "12:30" not in huecos
        assert any(h < "12:00" for h in huecos), "Debe haber huecos de mañana"
        assert any(h >= "13:00" for h in huecos), "Debe haber huecos de tarde"
    finally:
        # Restaurar horario sin descanso
        client.post(
            "/auth/schedule",
            params={"cliente_id": "demo"},
            cookies=admin_cookies,
            json={"enabled": True, "timezone": "Europe/Madrid", "slot_minutes": 30,
                  "day_start": "09:00", "day_end": "18:00", "break_windows": [], "closed_weekdays": [6]},
        )


def test_voice_availability_empty_on_closed_day(api_module):
    """_voice_check_availability devuelve hay_huecos=False en día cerrado (domingo)."""
    d = datetime.utcnow().date() + timedelta(days=1)
    while d.weekday() != 6:
        d += timedelta(days=1)
    fecha = d.isoformat()

    result = _run_async(api_module._voice_check_availability("demo", fecha))
    assert result["ok"] is True, result
    assert result["hay_huecos"] is False, f"Domingo cerrado debe tener hay_huecos=False: {result}"


def test_voice_booking_outside_hours_fails(api_module):
    """_voice_perform_booking con hora fuera del horario global devuelve ok=False sin excepción."""
    fecha = _next_weekday(4)
    # El horario global es 09:00-18:00; las 22:00 están fuera.
    result = _run_async(api_module._voice_perform_booking(
        "demo",
        nombre="Test Voz FueraHora",
        telefono="+34600999000",
        fecha=fecha,
        hora="22:00",
        servicio="",
    ))
    assert result["ok"] is False, f"Esperaba fallo por hora fuera de horario: {result}"


def test_voice_booking_on_closed_weekday_fails(api_module):
    """_voice_perform_booking en domingo (cerrado) devuelve ok=False."""
    d = datetime.utcnow().date() + timedelta(days=1)
    while d.weekday() != 6:
        d += timedelta(days=1)
    fecha = d.isoformat()
    result = _run_async(api_module._voice_perform_booking(
        "demo",
        nombre="Test Voz Domingo",
        telefono="+34600999002",
        fecha=fecha,
        hora="10:00",
        servicio="",
    ))
    assert result["ok"] is False, f"Domingo cerrado debe fallar: {result}"


def test_voice_booking_sets_source_voice(api_module):
    """Una cita creada por voz debe guardar source='voice' en la BD."""
    fecha = _next_weekday(4)
    avail = _run_async(api_module._voice_check_availability("demo", fecha))
    result = _run_async(api_module._voice_perform_booking(
        "demo",
        nombre="Paciente Voz Source",
        telefono="+34600777888",
        fecha=fecha,
        hora=avail["huecos"][0],
        servicio="",
    ))
    assert result["ok"] is True, result
    booking_id = result["booking_id"]
    try:
        with api_module._get_db_connection() as conn:
            row = conn.execute("SELECT source, status FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        assert row[0] == "voice"
        assert row[1] == "confirmed"
    finally:
        _cleanup_booking(api_module, booking_id)


# ===========================================================================
# 11. PORTAL — cancelar y reprogramar desde autenticación
# ===========================================================================

def test_portal_cancel_booking(client: TestClient, api_module, admin_cookies: dict):
    """POST /auth/bookings/{id}/cancel cambia el estado a cancelled."""
    fecha = _next_weekday(5)
    r = _book(client, admin_cookies, fecha, "10:30")
    assert r.status_code == 200, r.text
    booking_id = r.json()["booking_id"]
    try:
        cancel = client.post(
            f"/auth/bookings/{booking_id}/cancel",
            params={"cliente_id": "demo"},
            cookies=admin_cookies,
        )
        assert cancel.status_code == 200, cancel.text
        with api_module._get_db_connection() as conn:
            row = conn.execute("SELECT status FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        assert row[0] == "cancelled"
    finally:
        _cleanup_booking(api_module, booking_id)


def test_portal_reschedule_booking(client: TestClient, api_module, admin_cookies: dict):
    """Reprogramar vía portal actualiza la cita in-place con la nueva fecha/hora."""
    fecha_orig = _next_weekday(5)
    nueva_fecha = _next_weekday(12)
    r = _book(client, admin_cookies, fecha_orig, "10:00")
    assert r.status_code == 200, r.text
    booking_id = r.json()["booking_id"]
    try:
        resched = client.post(
            f"/auth/bookings/{booking_id}/reschedule",
            params={"cliente_id": "demo"},
            cookies=admin_cookies,
            json={"fecha": nueva_fecha, "hora": "11:00"},
        )
        assert resched.status_code == 200, resched.text
        data = resched.json()
        assert data.get("ok") is True
        # La misma cita se actualiza in-place: misma ID, nueva fecha/hora, sigue confirmed
        with api_module._get_db_connection() as conn:
            row = conn.execute("SELECT booking_date, booking_time, status FROM bookings WHERE id = ?",
                               (booking_id,)).fetchone()
        assert row[0] == nueva_fecha
        assert row[1] == "11:00"
        assert row[2] == "confirmed"
    finally:
        _cleanup_booking(api_module, booking_id)


def test_portal_reschedule_to_occupied_slot_rejected(client: TestClient, api_module, admin_cookies: dict):
    """Reprogramar a un hueco ya ocupado por otra cita debe devolver 409."""
    fecha = _next_weekday(6)
    employee_id = _make_employee(client, admin_cookies)
    booking_a_id = ""
    booking_b_id = ""
    try:
        ra = _book(client, admin_cookies, fecha, "09:00", employee_id=employee_id)
        assert ra.status_code == 200
        booking_a_id = ra.json()["booking_id"]

        rb = _book(client, admin_cookies, fecha, "10:00", employee_id=employee_id)
        assert rb.status_code == 200
        booking_b_id = rb.json()["booking_id"]

        # Intentar mover B al slot de A (ocupado)
        resched = client.post(
            f"/auth/bookings/{booking_b_id}/reschedule",
            params={"cliente_id": "demo"},
            cookies=admin_cookies,
            json={"fecha": fecha, "hora": "09:00"},
        )
        assert resched.status_code == 409, f"Esperaba 409 por slot ocupado, obtuvo {resched.status_code}"
    finally:
        for bid in (booking_a_id, booking_b_id):
            if bid:
                _cleanup_booking(api_module, bid)
        _delete_employee(client, admin_cookies, employee_id)


# ===========================================================================
# 12. MÚLTIPLES PROFESIONALES — asignación correcta
# ===========================================================================

def test_two_employees_same_slot_no_conflict(client: TestClient, api_module, admin_cookies: dict):
    """Dos profesionales distintos pueden tener citas al mismo tiempo sin conflicto."""
    fecha = _next_weekday(4)
    emp1 = _make_employee(client, admin_cookies, name="Prof A")
    emp2 = _make_employee(client, admin_cookies, name="Prof B")
    b1_id = b2_id = ""
    try:
        r1 = _book(client, admin_cookies, fecha, "10:00", employee_id=emp1)
        assert r1.status_code == 200, r1.text
        b1_id = r1.json()["booking_id"]

        r2 = _book(client, admin_cookies, fecha, "10:00", employee_id=emp2)
        assert r2.status_code == 200, r2.text
        b2_id = r2.json()["booking_id"]
    finally:
        for bid in (b1_id, b2_id):
            if bid:
                _cleanup_booking(api_module, bid)
        _delete_employee(client, admin_cookies, emp1)
        _delete_employee(client, admin_cookies, emp2)


def test_booking_assigned_to_correct_employee(client: TestClient, api_module, admin_cookies: dict):
    """La cita se asigna al profesional solicitado, no al primero de la lista."""
    fecha = _next_weekday(4)
    emp1 = _make_employee(client, admin_cookies, name="Primero")
    emp2 = _make_employee(client, admin_cookies, name="Segundo")
    booking_id = ""
    try:
        r = _book(client, admin_cookies, fecha, "10:00", employee_id=emp2)
        assert r.status_code == 200, r.text
        booking_id = r.json()["booking_id"]
        with api_module._get_db_connection() as conn:
            row = conn.execute("SELECT employee_id FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        assert row[0] == emp2
    finally:
        if booking_id:
            _cleanup_booking(api_module, booking_id)
        _delete_employee(client, admin_cookies, emp1)
        _delete_employee(client, admin_cookies, emp2)


# ===========================================================================
# 13. CANAL WEB — el formulario público también respeta restricciones
# ===========================================================================

def test_public_agendar_endpoint_respects_break_windows(client: TestClient, api_module, admin_cookies: dict):
    """El endpoint público /agendar rechaza horas dentro de un descanso del profesional."""
    fecha = _next_weekday(3)
    employee_id = _make_employee(
        client, admin_cookies,
        day_start="09:00", day_end="18:00",
        break_windows=[{"start": "13:00", "end": "14:00", "reason": "Comida web"}],
    )
    try:
        r = client.post(
            "/agendar",
            json={
                "cliente_id": "demo",
                "nombre": "Cliente Web",
                "email": "web@test.es",
                "telefono": "",
                "servicio": "",
                "employee_id": employee_id,
                "fecha": fecha,
                "hora": "13:00",
                "notas": "",
            },
            headers={"Origin": "http://testserver"},
        )
        assert r.status_code == 409, f"Booking en descanso vía /agendar debe ser 409, obtuvo {r.status_code}"
    finally:
        _delete_employee(client, admin_cookies, employee_id)


def test_public_agendar_endpoint_respects_closed_day(client: TestClient, admin_cookies: dict):
    """El endpoint público /agendar rechaza días cerrados."""
    d = datetime.utcnow().date() + timedelta(days=1)
    while d.weekday() != 6:
        d += timedelta(days=1)
    fecha = d.isoformat()

    r = client.post(
        "/agendar",
        json={
            "cliente_id": "demo",
            "nombre": "Cliente Web",
            "email": "web@test.es",
            "telefono": "",
            "servicio": "",
            "employee_id": "",
            "fecha": fecha,
            "hora": "10:00",
            "notas": "",
        },
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 409


def test_public_disponibilidad_reflects_existing_bookings(client: TestClient, api_module, admin_cookies: dict):
    """/disponibilidad marca como no disponible un slot ya reservado."""
    fecha = _next_weekday(4)
    employee_id = _make_employee(client, admin_cookies)
    booking_id = ""
    try:
        r = _book(client, admin_cookies, fecha, "11:00", employee_id=employee_id)
        assert r.status_code == 200
        booking_id = r.json()["booking_id"]

        slots = _slots_map(client, fecha, employee_id)
        assert slots.get("11:00") is False, "Slot ocupado debe aparecer como no disponible"
        assert slots.get("11:30") is True
    finally:
        if booking_id:
            _cleanup_booking(api_module, booking_id)
        _delete_employee(client, admin_cookies, employee_id)
