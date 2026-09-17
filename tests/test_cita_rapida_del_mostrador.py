# -*- coding: utf-8 -*-
"""La cita rápida del mostrador: apuntar como en su programa de siempre, sin descuadrar la agenda.

POR QUE EXISTE
--------------
Alicia (salón piloto) compara nuestro portal con PeluGest: allí pincha en la agenda y escribe
«CARMEN ELUMEN Y…» como una nota. Aquí se le pedía servicio del catálogo, y eso la frenaba.
Apuntarla sin servicio ya se podía, pero la cita se guardaba con la duración POR DEFECTO (30 min):
un trabajo de tres horas ocupando media hora deja al asistente ofreciendo un hueco que no existe,
que es justo el incidente que este producto no se puede permitir.

Por eso el mostrador puede decir CUÁNTO DURA (`duration_minutes` en el alta manual y `duracion` al
consultar huecos), y esa duración es la que se guarda, la que bloquea la agenda y la que se
comprueba contra las demás citas.
"""
from __future__ import annotations

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


ORIGEN = {"Origin": "http://testserver"}


def _dia_habil(dias=3):
    dia = datetime.utcnow().date() + timedelta(days=dias)
    while dia.weekday() in (5, 6):
        dia += timedelta(days=1)
    return dia.isoformat()


def _crear(client, cookies, **extra):
    cuerpo = {"nombre": "Carmen Prueba Rapida", "email": "", "telefono": "600444111",
              "servicio": "", "employee_id": "", "fecha": _dia_habil(), "hora": "09:00", "notas": ""}
    cuerpo.update(extra)
    return client.post("/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies, json=cuerpo)


def _borrar(api_module, *ids):
    with sqlite3.connect(api_module.DB_PATH) as conn:
        for bid in ids:
            conn.execute("DELETE FROM bookings WHERE id=?", (bid,))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (bid,))
        conn.commit()


def test_la_duracion_que_dice_el_mostrador_es_la_que_ocupa(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    creada = _crear(client, cookies, duration_minutes=180, notas="Carmen elumen y secado")
    assert creada.status_code == 200, creada.text
    bid = creada.json()["booking_id"]
    try:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            fila = conn.execute("SELECT start_at, end_at, service_id, notas FROM bookings WHERE id=?", (bid,)).fetchone()
        inicio = datetime.strptime(fila[0], "%Y-%m-%dT%H:%M:%SZ")
        fin = datetime.strptime(fila[1], "%Y-%m-%dT%H:%M:%SZ")
        assert (fin - inicio) == timedelta(minutes=180), "la cita no ocupa lo que dijo el mostrador"
        assert not fila[2], "se apuntó sin servicio: no se inventa uno"
        assert "Carmen elumen y secado" in (fila[3] or ""), "lo que escribió se guarda tal cual"
    finally:
        _borrar(api_module, bid)


def test_otra_cita_no_se_cuela_dentro_de_la_cita_rapida(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    fecha = _dia_habil()

    def libres(duracion, empleado):
        r = client.get("/disponibilidad", params={
            "cliente_id": "demo", "fecha": fecha, "employee_id": empleado, "duracion": duracion}, headers=ORIGEN)
        assert r.status_code == 200, r.text
        return {s["hora"] for s in r.json()["slots"] if s["disponible"]}

    larga = _crear(client, cookies, duration_minutes=180, hora="09:00")
    assert larga.status_code == 200, larga.text
    bid = larga.json()["booking_id"]
    empleado = larga.json().get("employee_id", "")
    try:
        # Encima de la cita larga no entra nadie, aunque sean solo 30 min.
        encima = _crear(client, cookies, hora="10:00", employee_id=empleado, telefono="600444222")
        assert encima.status_code == 409, encima.text
        cortas = libres(30, empleado)
        assert "09:00" not in cortas and "10:00" not in cortas, "ofrece huecos dentro de la cita larga"
        # Y lo que se ofrece depende de lo que va a durar: lo que cabe en media hora no
        # tiene por qué caber en tres.
        assert libres(180, empleado) <= cortas, "con más duración se ofrecen más huecos"
    finally:
        _borrar(api_module, bid)


def test_la_duracion_consultada_acota_los_huecos(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    fecha = _dia_habil(4)
    emps = client.get("/profesionales/demo", headers=ORIGEN).json()
    lista = emps if isinstance(emps, list) else emps.get("items", [])
    empleado = (lista[0].get("employee_id") or lista[0].get("id")) if lista else ""
    assert empleado, "el negocio de pruebas no tiene profesionales"

    def libres(duracion):
        r = client.get("/disponibilidad", params={
            "cliente_id": "demo", "fecha": fecha, "employee_id": empleado, "duracion": duracion}, headers=ORIGEN)
        assert r.status_code == 200, r.text
        return {s["hora"] for s in r.json()["slots"] if s["disponible"]}

    cortas, largas = libres(30), libres(180)
    assert cortas, "sin huecos no se puede comparar"
    assert largas < cortas, "la duración no cambia los huecos que se ofrecen"


@pytest.mark.parametrize("duracion", [7, 3, 601])
def test_una_duracion_rara_se_rechaza(client: TestClient, api_module, duracion):
    cookies = _portal_admin_cookies(api_module)
    r = _crear(client, cookies, duration_minutes=duracion)
    assert r.status_code in (400, 422), r.text
    if r.status_code == 200:  # pragma: no cover - solo si alguien relaja la validación
        _borrar(api_module, r.json()["booking_id"])


def test_consultar_huecos_por_duracion_necesita_profesional(client: TestClient, api_module):
    r = client.get("/disponibilidad", params={"cliente_id": "demo", "fecha": _dia_habil(), "duracion": 60},
                   headers=ORIGEN)
    assert r.status_code == 400 and "profesional" in r.json()["detail"].lower()
    malo = client.get("/disponibilidad", params={"cliente_id": "demo", "fecha": _dia_habil(),
                                                 "employee_id": "x", "duracion": 7}, headers=ORIGEN)
    assert malo.status_code == 400


# ─── Lo que ve quien coge la cita ──────────────────────────────────────────

def _panel():
    return (Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")


def _funcion(fuente, nombre):
    encontrada = re.search(r"^function " + nombre + r"\(.*?^\}", fuente, re.S | re.M)
    assert encontrada, "no existe la funcion %s en el panel" % nombre
    return encontrada.group()


def test_el_portal_abre_en_cita_rapida_con_media_hora_puesta():
    """Decisión de Pablo (17-sep-2026): que no le pregunte nada. Media hora de salida, a un toque
    de cambiarla, y si el trabajo dura más se estira la cita en la agenda."""
    fuente = _panel()
    assert 'id="nbRapQue"' in fuente and 'id="nbRapDur"' in fuente, "no existe la cita rápida"
    assert "let nbModo = 'rapida'" in fuente, "el portal no abre en cita rápida"
    assert "const NB_DURACION_POR_DEFECTO = 30;" in fuente, "no hay duración de salida"
    assert "let nbRapDuracion = NB_DURACION_POR_DEFECTO;" in fuente, "la duración no viene puesta"
    abrir = fuente.split("async function openNewBookingDrawer", 1)[1].split("\n}\n", 1)[0]
    assert "nbRapDuracion = NB_DURACION_POR_DEFECTO;" in abrir, "al abrir otra cita no vuelve a media hora"
    node = shutil.which("node")
    if not node:
        pytest.skip("Node no disponible para ejecutar el JavaScript del portal")
    caso = {"hora": "10:00", "nombre": "Carmen Prueba Rapida", "completo": True,
            "svc": {"escrito": "", "resuelto": "", "coincidencias": 0},
            "rapida": True, "duracion": 30, "servicioRapido": ""}
    salida = subprocess.run([node, "-e", _funcion(fuente, "nbPorQueNoSePuedeCrear")
                             + "\nprocess.stdout.write(nbPorQueNoSePuedeCrear(%s));" % json.dumps(caso)],
                            check=True, capture_output=True, text=True, encoding="utf-8").stdout
    assert salida == "", "con la duración puesta no falta nada"
    sin_duracion = dict(caso, duracion=0)
    salida2 = subprocess.run([node, "-e", _funcion(fuente, "nbPorQueNoSePuedeCrear")
                              + "\nprocess.stdout.write(nbPorQueNoSePuedeCrear(%s));" % json.dumps(sin_duracion)],
                             check=True, capture_output=True, text=True, encoding="utf-8").stdout
    assert salida2 == "Toca cuánto dura: la agenda aparta ese rato.", salida2


def test_el_portal_manda_la_duracion_y_guarda_lo_escrito():
    fuente = _panel()
    boton = fuente.split("document.getElementById('nbConfirmBtn').addEventListener", 1)[1].split("});", 1)[0]
    assert "duration_minutes: nbRapDuracionEfectiva()" in boton, "el alta no manda la duración"
    assert "rapQue" in boton and "notas," in boton, "lo escrito no viaja como nota"
    huecos = fuente.split("async function loadNbSlots(", 1)[1].split("\nfunction closeNewBookingDrawer", 1)[0]
    assert "&duracion=${duracion}" in huecos, "los huecos no se piden con la duración elegida"
    efectiva = _funcion(fuente, "nbRapDuracionEfectiva")
    assert "if (nbRapServicio) return 0;" in efectiva, "con servicio del catálogo manda el catálogo"
