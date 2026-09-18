# -*- coding: utf-8 -*-
"""Una nota del mostrador no es una clienta, la toque quien la toque después.

POR QUE EXISTE
--------------
El salón piloto apunta citas escribiendo en la agenda («Carmen - ELUMEN Y SECADOS»). Sin email ni
teléfono eso es una NOTA: no hay con qué reconocer a la persona ni a dónde escribirle. El 17-sep se
dejó de crear ficha en Clientes AL CREAR la cita, pero el 18-sep, en la agenda real, las fichas
seguían saliendo: «paula p», «carmen calvo, elumen» y «Maria Prados» aparecieron al CANCELAR, y
«Carmen - ELUMEN Y SECADOS» salió como «confirmado» del relleno del CRM que se hace tras cada
reinicio. El guardia estaba en un camino y había siete.

Ahora el guardia está en `crm._crm_upsert_contact`, por donde pasan todos. Aquí se recorre cada
camino, y uno de control con teléfono para probar que no se ha cerrado el grifo entero.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from test_api_smoke import _portal_admin_cookies  # noqa: F401


def _dia_habil(dias=3):
    dia = datetime.utcnow().date() + timedelta(days=dias)
    while dia.weekday() in (5, 6):
        dia += timedelta(days=1)
    return dia.isoformat()


def _apuntar(client, cookies, nombre, hora="09:00", telefono=""):
    creada = client.post("/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies, json={
        "nombre": nombre, "email": "", "telefono": telefono, "servicio": "", "employee_id": "",
        "fecha": _dia_habil(), "hora": hora, "notas": nombre, "duration_minutes": 30})
    assert creada.status_code == 200, creada.text
    return creada.json()["booking_id"], creada.json().get("employee_id", "")


def _fichas(api_module, nombre):
    with sqlite3.connect(api_module.DB_PATH) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM crm_contacts WHERE cliente_id='demo' AND name=?", (nombre,)).fetchone()[0]


def _limpiar(api_module, bid, nombre):
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE id=?", (bid,))
        conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (bid,))
        conn.execute("DELETE FROM crm_contacts WHERE cliente_id='demo' AND name=?", (nombre,))
        conn.commit()


def _al_pasado(api_module, bid):
    """La cita ya ha pasado: como estará mañana en la agenda del salón."""
    ayer = datetime.utcnow() - timedelta(days=1)
    with sqlite3.connect(api_module.DB_PATH) as conn:
        conn.execute("UPDATE bookings SET start_at=?, end_at=? WHERE id=?", (
            (ayer - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ayer.strftime("%Y-%m-%dT%H:%M:%SZ"), bid))
        conn.commit()


def test_cancelar_la_nota_no_crea_ficha(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    nombre = "Nota Cancelada Mostrador"
    bid, _ = _apuntar(client, cookies, nombre)
    try:
        r = client.post("/auth/bookings/%s/cancel" % bid, params={"cliente_id": "demo"},
                        cookies=cookies, json={"motivo": ""})
        assert r.status_code == 200, r.text
        assert _fichas(api_module, nombre) == 0, "cancelar la nota la ha metido en Clientes"
    finally:
        _limpiar(api_module, bid, nombre)


def test_mover_la_nota_no_crea_ficha(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    nombre = "Nota Movida Mostrador"
    bid, empleado = _apuntar(client, cookies, nombre)
    try:
        r = client.post("/auth/bookings/%s/reschedule" % bid, cookies=cookies,
                        json={"employee_id": empleado, "fecha": _dia_habil(12), "hora": "09:00"})
        assert r.status_code == 200, r.text
        assert _fichas(api_module, nombre) == 0, "mover la nota la ha metido en Clientes"
    finally:
        _limpiar(api_module, bid, nombre)


def test_cerrarse_sola_o_marcar_asistencia_no_crea_ficha(client: TestClient, api_module):
    """Al pasar la hora se cierra sola (y pasaba a «cliente»); luego se marca si vino."""
    cookies = _portal_admin_cookies(api_module)
    nombre = "Nota Pasada Mostrador"
    bid, _ = _apuntar(client, cookies, nombre, hora="10:00")
    try:
        _al_pasado(api_module, bid)
        api_module._auto_complete_past_bookings()
        assert _fichas(api_module, nombre) == 0, "al cerrarse sola la nota ha entrado en Clientes"
        r = client.post("/auth/bookings/%s/attendance" % bid, params={"cliente_id": "demo"},
                        cookies=cookies, json={"attended": True})
        assert r.status_code == 200, r.text
        assert _fichas(api_module, nombre) == 0, "marcar la asistencia la ha metido en Clientes"
    finally:
        _limpiar(api_module, bid, nombre)


def test_el_relleno_del_crm_no_mete_las_notas(client: TestClient, api_module):
    """El que sacó «Carmen - ELUMEN Y SECADOS» como «confirmado» en la agenda real: se hace una
    vez por negocio y arranque, así que cada despliegue volvía a meter todas las notas."""
    from backend import crm

    cookies = _portal_admin_cookies(api_module)
    nombre = "Nota Relleno Mostrador"
    bid, _ = _apuntar(client, cookies, nombre, hora="10:30")
    try:
        crm.CRM_BACKFILLED_CLIENTS.discard("demo")
        crm._crm_backfill_client("demo")
        assert _fichas(api_module, nombre) == 0, "el relleno del CRM ha metido la nota en Clientes"
    finally:
        _limpiar(api_module, bid, nombre)


def test_con_telefono_si_es_clienta_en_todos_los_caminos(client: TestClient, api_module):
    """Control: el guardia es para las notas. Con teléfono sí hay a quién reconocer."""
    cookies = _portal_admin_cookies(api_module)
    nombre = "Clienta Con Telefono Mostrador"
    bid, _ = _apuntar(client, cookies, nombre, hora="11:00", telefono="600111222")
    try:
        r = client.post("/auth/bookings/%s/cancel" % bid, params={"cliente_id": "demo"},
                        cookies=cookies, json={"motivo": ""})
        assert r.status_code == 200, r.text
        assert _fichas(api_module, nombre) >= 1, "con teléfono tiene que quedar su ficha"
    finally:
        _limpiar(api_module, bid, nombre)
