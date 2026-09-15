# -*- coding: utf-8 -*-
"""En la agenda, un pack se ve como sus pasos: servicio + hueco + servicio (paso 2)...

POR QUE EXISTE
--------------
15-sep-2026, encargo de Pablo para el salón de Alicia: «deben aparecer todos los servicios,
incluidos los pasos de los packs, como servicios independientes, solo a nivel de agenda; a la
hora de tomar citas se seguirá cogiendo el pack». Hasta ahora la agenda pintaba el pack como un
bloque con «libre» encima de las esperas, y los pasos se guardaban solo en minutos, sin nombre.

Cada paso lleva su nombre en `gap_json` (`paso`), la cita lo copia al reservarse y la API del
panel devuelve `work_steps` para pintar un bloque por paso. Reservar, la disponibilidad y el
asistente no cambian: siguen con el pack entero.
"""
from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path

import pytest

from test_booking_exhaustive import admin_cookies, api_module, client  # noqa: F401

PASOS = [{"activo": 20, "espera": 45, "paso": "Aplicar producto"},
         {"activo": 10, "espera": 15, "paso": "Lavado"},
         {"activo": 60, "espera": 0, "paso": "Secado y plancha"}]
EMPLEADA = "emp_pasos_qa"
PACK = "Pack con pasos QA"


@pytest.fixture
def pack_con_pasos(api_module, client):  # noqa: F811
    from backend import agenda, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, category, duration_minutes, price_cents,"
            " description, is_active, sort_order, gap_json, created_at, updated_at)"
            " VALUES ('demo', ?, ?, '', 150, 9000, '', 1, 0, ?, ?, ?)",
            (agenda._normalize_service_id(PACK), PACK, json.dumps(PASOS), ahora, ahora))
        conexion.execute(
            "INSERT OR REPLACE INTO employees (id, cliente_id, name, is_active, is_default, service_ids_json,"
            " created_at, updated_at) VALUES (?, 'demo', 'Prueba pasos', 1, 0, '[]', ?, ?)",
            (EMPLEADA, ahora, ahora))
        conexion.commit()
    yield agenda._normalize_service_id(PACK)
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND name=?", (PACK,))
        conexion.execute("DELETE FROM bookings WHERE cliente_id='demo' AND employee_id=?", (EMPLEADA,))
        conexion.execute("DELETE FROM employees WHERE id=?", (EMPLEADA,))
        conexion.commit()


def _coger(servicio=PACK, hora="10:00"):
    from backend import agenda, booking, db, timeutils

    empleada = agenda._get_employee_row(EMPLEADA, cliente_id="demo")
    for salto in range(3, 13):
        dia = (timeutils._utc_now().date() + datetime.timedelta(days=salto)).isoformat()
        try:
            fila = asyncio.run(booking._create_booking_core(
                "demo", employee_row=empleada, nombre="Ana Ruiz Perez", telefono="34600111333", email="",
                servicio=servicio, booking_date=dia, booking_time=hora, notas="", source="qa",
                send_confirmation=False))
        except Exception:  # noqa: BLE001 - ese dia no vale, se prueba el siguiente
            continue
        with db._get_db_connection() as conexion:
            return conexion.execute("SELECT * FROM bookings WHERE id=?", (fila["id"],)).fetchone()
    raise AssertionError("no se pudo coger la cita ningun dia")


def _pasos_de(row):
    from backend import booking

    return booking._portal_booking_summary_from_row(row).work_steps


def test_la_agenda_recibe_cada_paso_con_su_nombre(pack_con_pasos):
    inicio = 10 * 60
    assert _pasos_de(_coger()) == [
        {"inicio": inicio, "fin": inicio + 20, "paso": "Aplicar producto", "n": 1, "total": 3},
        {"inicio": inicio + 65, "fin": inicio + 75, "paso": "Lavado", "n": 2, "total": 3},
        {"inicio": inicio + 90, "fin": inicio + 150, "paso": "Secado y plancha", "n": 3, "total": 3},
    ]


def test_una_cita_de_antes_toma_los_nombres_del_pack_actual(pack_con_pasos):
    """Las citas cogidas antes de poner nombres guardaron los pasos solo en minutos."""
    from backend import db

    row = _coger()
    sin_nombres = json.dumps([{"activo": p["activo"], "espera": p["espera"]} for p in PASOS])
    with db._get_db_connection() as conexion:
        conexion.execute("UPDATE bookings SET gap_json=? WHERE id=?", (sin_nombres, row["id"]))
        conexion.commit()
        row = conexion.execute("SELECT * FROM bookings WHERE id=?", (row["id"],)).fetchone()
    assert [p["paso"] for p in _pasos_de(row)] == ["Aplicar producto", "Lavado", "Secado y plancha"]


def test_si_el_pack_cambio_de_pasos_no_se_inventan_nombres(pack_con_pasos):
    """La cita se pinta con SUS pasos; los nombres de otro reparto no le valen."""
    from backend import db

    row = _coger()
    sin_nombres = json.dumps([{"activo": p["activo"], "espera": p["espera"]} for p in PASOS])
    with db._get_db_connection() as conexion:
        conexion.execute("UPDATE bookings SET gap_json=? WHERE id=?", (sin_nombres, row["id"]))
        conexion.execute("UPDATE services SET gap_json=? WHERE cliente_id='demo' AND slug=?",
                         (json.dumps(PASOS[:2]), pack_con_pasos))
        conexion.commit()
        row = conexion.execute("SELECT * FROM bookings WHERE id=?", (row["id"],)).fetchone()
    pasos = _pasos_de(row)
    assert len(pasos) == 3 and all(p["paso"] == "" for p in pasos), pasos


def test_una_cita_normal_no_trae_pasos(pack_con_pasos):
    assert _pasos_de(_coger(servicio="", hora="11:00")) == []


def test_el_nombre_de_cada_paso_se_guarda_y_se_lee(api_module, client, admin_cookies):  # noqa: F811
    parametros = {"cliente_id": "demo"}
    alta = client.post("/auth/services", params=parametros, cookies=admin_cookies, json={
        "nombre": "Pack pasos API", "duration_minutes": 150, "price_cents": 9000, "gaps": PASOS})
    assert alta.status_code == 200, alta.text[:300]
    assert alta.json()["gaps"] == PASOS
    slug = alta.json()["id"]
    try:
        cambio = client.patch("/auth/services/%s" % slug, params=parametros, cookies=admin_cookies,
                              json={"gaps": [{"activo": 30, "espera": 20, "paso": "Color"},
                                             {"activo": 30, "espera": 0}]})
        assert cambio.status_code == 200, cambio.text[:300]
        assert cambio.json()["gaps"] == [{"activo": 30, "espera": 20, "paso": "Color"},
                                         {"activo": 30, "espera": 0}], "sin nombre, el paso queda como antes"
    finally:
        client.delete("/auth/services/%s" % slug, params=parametros, cookies=admin_cookies)


def _panel():
    return (Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")


def test_la_agenda_pinta_un_bloque_por_paso():
    fuente = _panel()
    assert "work_steps" in fuente, "la agenda no lee los pasos de la cita"
    assert "cd-paso" in fuente, "no hay bloque de paso en la agenda"


def test_la_ficha_del_pack_edita_y_guarda_los_pasos():
    fuente = _panel()
    assert 'id="svcPasos"' in fuente, "la ficha del servicio no tiene editor de pasos"
    guardar = fuente.split("async function saveService()", 1)[1].split("\n}\n", 1)[0]
    assert "gaps" in guardar, "guardar el servicio no manda los pasos"
