# -*- coding: utf-8 -*-
"""El tope de citas del plan mide al asistente, no la agenda del salon.

POR QUE EXISTE
--------------
El plan Pro tiene un tope de 500 citas al mes. Contaba TODAS las citas y
bloqueaba tambien el alta manual del panel: al llegar al tope, el equipo no
podia apuntar ni una cita mas en su propia agenda. Para un salon que usa nuestra
agenda como la suya de siempre (Alicia, cinco profesionales) eso podia pasar a
mitad de mes. Pablo decidio el 22-sep-2026 que el tope cuente solo lo que coge el
asistente y que nunca bloquee lo que apunta el equipo.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

# Arnes compartido, no el `client` de conftest: el shim de api.py recarga
# `backend.*` en cada runtime, y con el otro arnes el parche del tope caia en una
# copia del modulo que la app no usa (pasaba en aislado y fallaba en la suite).
from test_booking_exhaustive import api_module, client  # noqa: F401

ORIGEN = {"Origin": "http://testserver"}


def _dia_habil(dias=4):
    dia = datetime.utcnow().date() + timedelta(days=dias)
    while dia.weekday() in (5, 6):
        dia += timedelta(days=1)
    return dia.isoformat()


def _sembrar(api_module, *fuentes):
    """Citas creadas HOY con el origen indicado. Devuelve sus ids."""
    ids = []
    ahora = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    with sqlite3.connect(api_module.DB_PATH) as conn:
        for indice, fuente in enumerate(fuentes):
            bid = "bk_tope_" + uuid.uuid4().hex[:10]
            # Cada una en su hora: la base no admite dos citas en el mismo hueco.
            minuto = (uuid.uuid4().int % 50000) + indice
            dia = (datetime(2030, 1, 1) + timedelta(minutes=minuto * 30))
            conn.execute(
                "INSERT INTO bookings (id, cliente_id, nombre, email, telefono, servicio, booking_date, "
                "booking_time, status, provider_status, source, manage_token, booking_code, created_at, "
                "start_at, end_at, timezone) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (bid, "demo", "Clienta Tope", "", "600000000", "Consulta", dia.date().isoformat(),
                 dia.strftime("%H:%M"), "confirmed", "internal", fuente, "tok_" + uuid.uuid4().hex, "",
                 ahora, dia.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 (dia + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"), "Europe/Madrid"))
            ids.append(bid)
        conn.commit()
    return ids


def _borrar(api_module, ids):
    with sqlite3.connect(api_module.DB_PATH) as conn:
        for bid in ids:
            conn.execute("DELETE FROM bookings WHERE id=?", (bid,))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (bid,))
        conn.commit()


@pytest.fixture
def tope_de_una(api_module, monkeypatch):
    """Plan con tope de UNA cita del asistente al mes, y esa ya cogida."""
    from backend import clients

    original = clients._plan_limits
    monkeypatch.setattr(clients, "_plan_limits",
                        lambda plan: {**original(plan), "monthly_bookings": 1})
    sembradas = _sembrar(api_module, "widget")
    creadas = []
    yield creadas
    _borrar(api_module, sembradas + creadas)


def _panel_del_negocio(api_module):
    """Un usuario del NEGOCIO, no el admin: el admin se salta los topes."""
    email = "tope-" + uuid.uuid4().hex[:10] + "@example.com"
    api_module._create_user(email=email, password="prueba-tope-123", role="client",
                            display_name="Recepcion", cliente_id="demo", portal_role="owner")
    sesion = TestClient(api_module.app, base_url="https://testserver")
    assert sesion.post("/auth/login", json={"email": email, "password": "prueba-tope-123"}).status_code == 200
    return sesion


def test_el_equipo_apunta_aunque_el_asistente_haya_llegado_al_tope(api_module, tope_de_una):
    sesion = _panel_del_negocio(api_module)
    respuesta = sesion.post("/auth/bookings", json={
        "nombre": "Carmen Mostrador", "email": "", "telefono": "600444222", "servicio": "",
        "employee_id": "", "fecha": _dia_habil(), "hora": "09:00", "notas": "apuntada a mano",
        "duration_minutes": 30})
    assert respuesta.status_code == 200, (
        "el tope del plan ha bloqueado la agenda del propio salon: %s" % respuesta.text)
    tope_de_una.append(respuesta.json()["booking_id"])


def test_el_asistente_si_se_para_en_el_tope(client, api_module, tope_de_una):
    respuesta = client.post("/agendar", headers=ORIGEN, json={
        "cliente_id": "demo", "nombre": "Ana Web", "email": "ana@example.com", "telefono": "600444333",
        "servicio": "Consulta", "fecha": _dia_habil(), "hora": "09:30", "notas": ""})
    if respuesta.status_code == 200:
        tope_de_una.append(respuesta.json()["booking_id"])
    assert respuesta.status_code == 429, respuesta.text


def test_lo_que_apunta_el_equipo_no_gasta_el_cupo(api_module):
    from backend import booking

    antes = booking._count_bookings_this_month("demo")
    ids = _sembrar(api_module, "portal_manual", "portal_manual", "admin", "demo_seed", "test", "widget", "whatsapp")
    try:
        assert booking._count_bookings_this_month("demo") - antes == 2, (
            "el cupo cuenta citas del equipo o de pruebas")
    finally:
        _borrar(api_module, ids)
