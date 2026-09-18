# -*- coding: utf-8 -*-
"""Apuntar la cita EN la agenda: pinchar el hueco, escribir encima y ya está.

POR QUE EXISTE
--------------
Alicia (salón piloto) enseñó cómo trabaja en su programa de siempre: pincha en la agenda, le sale
el cuadro de la cita y escribe encima («CARMEN ELUMEN Y…»). Nuestro portal abría un panel lateral
con servicio, cliente y datos, y eso la frenaba: «para el día a día no lo quiero». El panel sigue
estando para la cita con todos los datos; lo que cambia es que pinchar un hueco ya no lo abre.

Y lo que no se ve: una nota del mostrador NO es una clienta. Antes, cada cita apuntada así creaba
una ficha en Clientes con el texto entero como nombre, y esa lista dejaba de servir para nada.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from test_api_smoke import _portal_admin_cookies  # noqa: F401


def _dia_habil(dias=3):
    dia = datetime.utcnow().date() + timedelta(days=dias)
    while dia.weekday() in (5, 6):
        dia += timedelta(days=1)
    return dia.isoformat()


def _panel():
    return (Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")


def _funcion(fuente, nombre):
    encontrada = re.search(r"^function " + nombre + r"\(.*?^\}", fuente, re.S | re.M)
    assert encontrada, "no existe la funcion %s en el panel" % nombre
    return encontrada.group()


def _borrar(api_module, *ids):
    with sqlite3.connect(api_module.DB_PATH) as conn:
        for bid in ids:
            conn.execute("DELETE FROM bookings WHERE id=?", (bid,))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (bid,))
        conn.commit()


def _fichas(api_module, nombre):
    with sqlite3.connect(api_module.DB_PATH) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM crm_contacts WHERE cliente_id='demo' AND name=?", (nombre,)).fetchone()[0]


def test_una_nota_del_mostrador_no_crea_ficha_de_clienta(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    texto = "Carmen elumen y secado"
    creada = client.post("/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies,
                         json={"nombre": texto, "email": "", "telefono": "", "servicio": "",
                               "employee_id": "", "fecha": _dia_habil(), "hora": "09:00", "notas": "",
                               "duration_minutes": 30})
    assert creada.status_code == 200, creada.text
    bid = creada.json()["booking_id"]
    try:
        assert _fichas(api_module, texto) == 0, "la nota del mostrador ha creado una ficha en Clientes"
        with sqlite3.connect(api_module.DB_PATH) as conn:
            guardado = conn.execute("SELECT nombre FROM bookings WHERE id=?", (bid,)).fetchone()[0]
        assert guardado == texto, "en la agenda tiene que leerse lo que escribió"
    finally:
        _borrar(api_module, bid)


def test_con_telefono_si_se_guarda_la_clienta(client: TestClient, api_module):
    cookies = _portal_admin_cookies(api_module)
    nombre = "Marta Con Telefono"
    creada = client.post("/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies,
                         json={"nombre": nombre, "email": "", "telefono": "600999888", "servicio": "",
                               "employee_id": "", "fecha": _dia_habil(), "hora": "09:30", "notas": ""})
    assert creada.status_code == 200, creada.text
    bid = creada.json()["booking_id"]
    try:
        assert _fichas(api_module, nombre) >= 1, "con teléfono sí hay con qué reconocerla: la ficha se guarda"
    finally:
        _borrar(api_module, bid)
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM crm_contacts WHERE cliente_id='demo' AND name=?", (nombre,))
            conn.commit()


def test_pinchar_un_hueco_deja_el_cuadro_en_la_agenda_y_no_abre_el_panel():
    fuente = _panel()
    assert "function cdNuevaEnLaAgenda(" in fuente, "no existe el cuadro en la agenda"
    dia = fuente.split("function renderCitasDay(", 1)[1].split("\nfunction cdSelect(", 1)[0]
    hueco = dia.split("body.addEventListener('click'", 1)[1].split("});", 1)[0]
    assert "cdNuevaEnLaAgenda(" in hueco, "pinchar un hueco no deja el cuadro"
    assert "openNewBookingDrawer(" not in hueco, "pinchar un hueco sigue abriendo el panel lateral"


def test_el_cuadro_guarda_lo_escrito_con_media_hora_y_sin_datos():
    caja = _funcion(_panel(), "cdNuevaEnLaAgenda")
    assert "'/auth/bookings'" in caja and "duration_minutes: CD_NUEVA_MINUTOS" in caja, (
        "el cuadro no crea la cita con la duración de la agenda")
    assert "nombre: texto" in caja and "email: ''" in caja and "telefono: ''" in caja, (
        "el cuadro no guarda lo escrito tal cual, o inventa datos de contacto")
    assert "const CD_NUEVA_MINUTOS = 30;" in _panel(), "la cita rápida de la agenda no aparta media hora"
    assert "e.key === 'Enter'" in caja and "e.key === 'Escape'" in caja, "no se guarda con Enter ni se sale con Esc"
    assert "openNewBookingDrawer(" in caja, "no queda forma de ir a la cita con todos los datos"
