# -*- coding: utf-8 -*-
"""A quién le cae la cita cuando la clienta no pide a nadie: por niveles.

POR QUE EXISTE
--------------
El salón piloto lo pidió así (18-sep-2026): «cuando alguien pida una cita, primero Lorena o Conchi,
luego Lucía o José y por último, si no hay más hueco, Alicia». Antes había dos escalones -todos al
azar y la dueña como «última opción»- y Lucía y José recibían citas antes que Lorena y Conchi.

Lo mismo decide el orden del selector de «Nueva cita» en el panel: quien va primero en el reparto
sale primero, y la dueña la última.

Todos los canales (widget, WhatsApp, voz y el asistente) reparten con
`agenda._resolve_public_booking_employee`, así que probarlo ahí los cubre a todos.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_api_smoke import _portal_admin_cookies  # noqa: F401

HORA = "11:00"


def _dia_habil(dias=4):
    dia = datetime.utcnow().date() + timedelta(days=dias)
    while dia.weekday() in (5, 6):
        dia += timedelta(days=1)
    return dia.isoformat()


def _alta(client, cookies, nombre, reparto):
    r = client.post("/auth/employees", params={"cliente_id": "demo"}, cookies=cookies, json={
        "name": nombre, "day_start": "09:00", "day_end": "19:00", "reparto": reparto})
    assert r.status_code == 200, r.text
    assert r.json()["reparto"] == reparto, r.json()
    return r.json()["employee_id"]


@pytest.fixture
def equipo(client, api_module):
    """Dos de primera opción, uno de segunda y la dueña de última, como en el salón."""
    cookies = _portal_admin_cookies(api_module)
    ids = {
        "Lorena Prueba": _alta(client, cookies, "Lorena Prueba", 1),
        "Conchi Prueba": _alta(client, cookies, "Conchi Prueba", 1),
        "Lucia Prueba": _alta(client, cookies, "Lucia Prueba", 2),
        "Alicia Prueba": _alta(client, cookies, "Alicia Prueba", 3),
    }
    yield ids
    with sqlite3.connect(api_module.DB_PATH) as conn:
        for emp in ids.values():
            conn.execute("DELETE FROM bookings WHERE employee_id=?", (emp,))
            conn.execute("DELETE FROM employees WHERE id=?", (emp,))
        conn.commit()


def _a_quien(api_module, fecha, veces=12):
    return {
        asyncio.run(api_module._resolve_public_booking_employee("demo", fecha, HORA))["name"]
        for _ in range(veces)
    }


def _ocupar(client, cookies, employee_id, fecha):
    r = client.post("/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies, json={
        "nombre": "Ocupado Reparto", "email": "", "telefono": "600000001", "servicio": "",
        "employee_id": employee_id, "fecha": fecha, "hora": HORA, "notas": "", "duration_minutes": 30})
    assert r.status_code == 200, r.text


def test_primero_la_primera_opcion_y_entre_ellas_cualquiera(client: TestClient, api_module, equipo):
    fecha = _dia_habil()
    elegidas = _a_quien(api_module, fecha, veces=30)
    assert elegidas <= {"Lorena Prueba", "Conchi Prueba"}, (
        "se da la cita a alguien que no es primera opción: %s" % elegidas)


def test_si_la_primera_opcion_esta_llena_va_la_segunda_y_luego_la_ultima(
        client: TestClient, api_module, equipo):
    cookies = _portal_admin_cookies(api_module)
    fecha = _dia_habil(5)
    _ocupar(client, cookies, equipo["Lorena Prueba"], fecha)
    _ocupar(client, cookies, equipo["Conchi Prueba"], fecha)
    assert _a_quien(api_module, fecha) == {"Lucia Prueba"}, "con la primera opción llena no va la segunda"
    _ocupar(client, cookies, equipo["Lucia Prueba"], fecha)
    assert _a_quien(api_module, fecha) == {"Alicia Prueba"}, "la última opción no entra cuando ya no queda nadie"


def test_el_nivel_se_guarda_y_la_ultima_sigue_siendo_la_de_siempre(client: TestClient, api_module, equipo):
    """«Última opción» ya existía (`auto_assign_last`): el nivel 3 la deja puesta, y quitarlo la quita."""
    cookies = _portal_admin_cookies(api_module)
    emp = equipo["Lucia Prueba"]

    def en_bd():
        with sqlite3.connect(api_module.DB_PATH) as conn:
            return conn.execute("SELECT reparto_nivel, auto_assign_last FROM employees WHERE id=?",
                                (emp,)).fetchone()

    r = client.post("/auth/employees/%s" % emp, params={"cliente_id": "demo"}, cookies=cookies,
                    json={"name": "Lucia Prueba", "reparto": 3})
    assert r.status_code == 200 and r.json()["reparto"] == 3, r.text
    assert en_bd() == (3, 1)
    r = client.post("/auth/employees/%s" % emp, params={"cliente_id": "demo"}, cookies=cookies,
                    json={"name": "Lucia Prueba", "reparto": 1})
    assert r.json()["reparto"] == 1 and en_bd() == (1, 0)
    # Guardar otra cosa sin mandar el nivel no lo toca.
    client.post("/auth/employees/%s" % emp, params={"cliente_id": "demo"}, cookies=cookies,
                json={"name": "Lucia Prueba", "role_label": "Color"})
    assert en_bd() == (1, 0), "guardar el rol ha borrado el nivel de reparto"


def test_la_ultima_opcion_de_antes_sigue_siendo_la_ultima(api_module):
    """Una fila de antes de los niveles: `auto_assign_last` = 1 y sin nivel. Es la última."""
    fila = {"auto_assign_last": 1, "reparto_nivel": 0}

    class Fila(dict):
        def keys(self):
            return list(super().keys())

    assert api_module.nivel_de_reparto(Fila(fila)) == 3
    assert api_module.nivel_de_reparto(Fila({"auto_assign_last": 0, "reparto_nivel": 0})) == 1
    assert api_module.nivel_de_reparto(Fila({"auto_assign_last": 0, "reparto_nivel": 2})) == 2


# ─── El panel ──────────────────────────────────────────────────────────────

def _panel():
    return (Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")


def _funcion(fuente, nombre):
    encontrada = re.search(r"^function " + nombre + r"\(.*?^\}", fuente, re.S | re.M)
    assert encontrada, "no existe la funcion %s en el panel" % nombre
    return encontrada.group()


def test_el_selector_de_nueva_cita_sigue_el_orden_del_reparto():
    fuente = _panel()
    abrir = fuente.split("async function openNewBookingDrawer", 1)[1].split("\n}\n", 1)[0]
    assert ".sort(cdOrdenDeReparto)" in abrir, "el selector de «Nueva cita» no sigue el reparto"
    node = shutil.which("node")
    if not node:
        pytest.skip("Node no disponible para ejecutar el JavaScript del portal")
    salon = [
        {"name": "Alicia", "reparto": 3, "sort_order": 1},
        {"name": "Lorena", "reparto": 1, "sort_order": 2},
        {"name": "Conchi", "reparto": 1, "sort_order": 3},
        {"name": "Lucía", "reparto": 2, "sort_order": 4},
        {"name": "Jose", "reparto": 2, "sort_order": 5},
    ]
    guion = (_funcion(fuente, "cdOrdenDeReparto")
             + "\nprocess.stdout.write(JSON.stringify(%s.sort(cdOrdenDeReparto).map(e => e.name)));"
             % json.dumps(salon))
    salida = subprocess.run([node, "-e", guion], check=True, capture_output=True, text=True,
                            encoding="utf-8").stdout
    assert json.loads(salida) == ["Lorena", "Conchi", "Lucía", "Jose", "Alicia"], salida


def test_el_editor_del_profesional_guarda_el_nivel():
    fuente = _panel()
    assert 'id="equipoReparto"' in fuente, "no hay dónde decir el nivel de reparto"
    guardar = fuente.split("document.getElementById('equipoSaveBtn').addEventListener", 1)[1].split("\n});", 1)[0]
    assert "reparto: Number(document.getElementById('equipoReparto').value)" in guardar, (
        "el editor no manda el nivel de reparto")


def test_tocar_una_opcion_del_cuadro_apunta_la_cita():
    """Pablo, 18-sep-2026: al tocar el chip, que se cree la cita, sin volver a pulsar Enter."""
    caja = _funcion(_panel(), "cdNuevaEnLaAgenda")
    boton = caja.split("btn.addEventListener('mousedown', async (e) => {", 1)[1].split("\n      });", 1)[0]
    assert "elegido = opcion;" in boton and "guardar();" in boton, "tocar la opción no apunta la cita"
    assert "await entenderAhora(texto);" in boton, (
        "si ha seguido escribiendo, se apunta con lo entendido de otro texto")
