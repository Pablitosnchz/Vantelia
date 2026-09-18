# -*- coding: utf-8 -*-
"""Entender lo que se escribe a mano en la agenda: «Carmen Calvo, pack mechas corto».

POR QUE EXISTE
--------------
El salón piloto apunta las citas escribiendo encima del cuadro de la agenda. Tal cual, eso es una
NOTA: media hora apartada aunque el trabajo sean seis. El asistente ve libre el resto de la tarde
y da horas que no existen, que es el incidente que este producto no se puede permitir.

Lo que se vigila aquí es la línea entre entender y adivinar:

- Lo claro se aplica solo (y la duración sale del catálogo, con sus pasos de pack).
- Lo dudoso NO se elige: se ofrecen las opciones reales con su duración, y toca quien atiende.
- Lo que no se reconoce se apunta igual, tal cual, como hasta ahora.

El caso que obliga a lo del medio es real: el salón tiene «Mechas medio» (75 min, solo la
aplicación) y «Pack mechas o balayage medio» (360). Elegir el primero por escribir «mechas medio»
sería apartar hora y cuarto para seis horas de trabajo.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_api_smoke import _portal_admin_cookies  # noqa: F401

# El negocio de pruebas no trae catalogo. Este copia la forma del salon real: packs por talla y,
# al lado, la aplicacion suelta que dura muchisimo menos. Ahi esta el peligro.
CATALOGO = [
    ("Pack mechas o balayage corto", 195),
    ("Pack mechas o balayage medio", 360),
    ("Pack mechas o balayage largo", 440),
    ("Pack mechas o balayage extra largo", 395),
    # La aplicacion suelta al lado del pack: la misma trampa que tiene el salon de verdad.
    ("Mechas balayage corto", 75),
    ("Corte caballero", 20),
]


def _poner_servicio(client, cookies, nombre, minutos):
    """Por la API, no a mano en la tabla: asi el slug es el de verdad y la duracion se resuelve
    como en produccion."""
    alta = client.post("/auth/services", params={"cliente_id": "demo"}, cookies=cookies,
                       json={"nombre": nombre, "duration_minutes": minutos, "price_cents": 0})
    assert alta.status_code == 200, alta.text[:300]
    return alta.json()["id"]


@pytest.fixture
def catalogo(client, api_module):
    cookies = _portal_admin_cookies(api_module)
    slugs = [_poner_servicio(client, cookies, nombre, minutos) for nombre, minutos in CATALOGO]
    yield slugs
    for slug in slugs:
        client.delete("/auth/services/%s" % slug, params={"cliente_id": "demo"}, cookies=cookies)


def _interpretar(client, cookies, texto):
    return client.post("/auth/app/interpretar-apunte", params={"cliente_id": "demo"},
                       cookies=cookies, json={"texto": texto})


def _panel():
    return (Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")


def _funcion(fuente, nombre):
    encontrada = re.search(r"^function " + nombre + r"\(.*?^\}", fuente, re.S | re.M)
    assert encontrada, "no existe la funcion %s en el panel" % nombre
    return encontrada.group()


def test_la_coma_parte_el_apunte_y_el_servicio_sale_del_catalogo(client: TestClient, api_module, catalogo):
    cookies = _portal_admin_cookies(api_module)
    r = _interpretar(client, cookies, "Carmen Calvo, pack mechas corto")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["nombre"] == "Carmen Calvo", "el nombre no se separa de lo que se le hace"
    assert data["servicio"] == "Pack mechas o balayage corto", data
    assert data["duracion"] == 195, "la duración no sale del catálogo"
    assert not data["candidatos"], "lo que está claro no se pregunta"


def test_lo_que_no_esta_claro_se_pregunta_con_las_duraciones_de_verdad(client: TestClient, api_module, catalogo):
    cookies = _portal_admin_cookies(api_module)
    data = _interpretar(client, cookies, "Ana, mechas").json()
    assert data["servicio"] == "", "elige un largo que nadie ha dicho"
    assert data["pregunta"], "no dice qué falta por saber"
    assert len(data["candidatos"]) >= 2, data
    servicios = {c["servicio"] for c in data["candidatos"]}
    assert len(servicios) == len(data["candidatos"]), "ofrece dos veces el mismo servicio"
    assert all(c["duracion"] > 0 for c in data["candidatos"]), "una opción sin duración no se puede elegir"


def test_dos_formas_de_resolver_que_no_coinciden_no_deciden(client: TestClient, api_module, catalogo):
    """El caso caro: el nombre exacto dice una cosa (la aplicación suelta) y el catálogo otra
    (el pack). Entre 75 minutos y tres horas no se apuesta: se pregunta."""
    cookies = _portal_admin_cookies(api_module)
    suelta = _poner_servicio(client, cookies, "Mechas medio", 75)
    try:
        data = _interpretar(client, cookies, "Ana, mechas medio").json()
        assert data["servicio"] == "", "ha elegido sola entre la aplicación suelta y el pack: %s" % data
        ofrecidos = {c["servicio"]: c["duracion"] for c in data["candidatos"]}
        assert "Mechas medio" in ofrecidos, ofrecidos
        assert "Pack mechas o balayage medio" in ofrecidos, ofrecidos
        assert ofrecidos["Pack mechas o balayage medio"] > ofrecidos["Mechas medio"], ofrecidos
    finally:
        client.delete("/auth/services/%s" % suelta, params={"cliente_id": "demo"}, cookies=cookies)


def test_lo_que_no_se_reconoce_se_apunta_igual(client: TestClient, api_module, catalogo):
    cookies = _portal_admin_cookies(api_module)
    data = _interpretar(client, cookies, "Rosa, tinte de raiz con henna").json()
    assert data["servicio"] == "" and not data["candidatos"], data
    assert data["nombre"] == "Rosa", "sin reconocer el servicio se pierde hasta el nombre"


def test_sin_coma_no_se_inventa_un_nombre(client: TestClient, api_module, catalogo):
    """Como escribía antes: «CARMEN ELUMEN Y…». Todo lo escrito hace de nombre, como hasta hoy."""
    cookies = _portal_admin_cookies(api_module)
    data = _interpretar(client, cookies, "Carmen pack mechas corto").json()
    assert data["nombre"] == "Carmen pack mechas corto", data


def test_interpretar_pide_sesion(client: TestClient, api_module):
    r = client.post("/auth/app/interpretar-apunte", params={"cliente_id": "demo"},
                    json={"texto": "Carmen Calvo, mechas corto"})
    assert r.status_code in (401, 403), r.text


# ─── Lo que hace el cuadro de la agenda con lo entendido ───────────────────

def test_el_cuadro_pregunta_al_servidor_lo_que_se_escribe():
    caja = _funcion(_panel(), "cdNuevaEnLaAgenda")
    assert "'/auth/app/interpretar-apunte'" in caja, "el cuadro no pregunta qué se ha entendido"
    assert "clearTimeout(temporizador)" in caja and "}, 400);" in caja, (
        "pregunta en cada tecla en vez de esperar a que termine de escribir")
    assert "if (mio !== consulta) return;" in caja, "una respuesta vieja puede pisar a la nueva"


def test_el_cuadro_guarda_el_servicio_entendido_y_lo_escrito():
    caja = _funcion(_panel(), "cdNuevaEnLaAgenda")
    assert "duration_minutes: servicio ? 0 : CD_NUEVA_MINUTOS," in caja, (
        "con servicio reconocido la duración tiene que ponerla el catálogo")
    assert "nombre: entendido.nombre || texto" in caja, "no guarda el nombre que se ha entendido"
    assert "notas: texto" in caja, "se pierde lo que escribió tal cual"


def test_lo_que_toca_ella_manda_sobre_lo_que_adivina_el_codigo():
    caja = _funcion(_panel(), "cdNuevaEnLaAgenda")
    assert "elegido = op;" in caja, "no se puede tocar una de las opciones ofrecidas"
    assert "(elegido ? elegido.servicio : entendido.servicio)" in caja, (
        "lo tocado no manda sobre lo adivinado")
    assert "if (elegido || !entendido.candidatos.length) return;" in caja, (
        "sigue preguntando después de que ella haya elegido")


def test_lo_que_se_enseña_es_lo_que_se_aparta(client: TestClient, api_module, catalogo):
    """El numero que ve quien coge la cita y el rato que se bloquea en la agenda tienen que ser el
    MISMO. Si se enseña «3 h 15» y se apartan 30 minutos, el asistente da esa hora a otra."""
    cookies = _portal_admin_cookies(api_module)
    entendido = _interpretar(client, cookies, "Carmen Prueba Apunte, pack mechas corto").json()
    assert entendido["servicio"] and entendido["duracion"], entendido

    dia = datetime.utcnow().date() + timedelta(days=5)
    while dia.weekday() in (5, 6):
        dia += timedelta(days=1)
    creada = client.post("/auth/bookings", params={"cliente_id": "demo"}, cookies=cookies, json={
        "nombre": entendido["nombre"], "email": "", "telefono": "", "notas": "pack mechas corto",
        "servicio": entendido["servicio"], "employee_id": "", "fecha": dia.isoformat(),
        "hora": "09:00", "duration_minutes": 0})
    assert creada.status_code == 200, creada.text
    bid = creada.json()["booking_id"]
    try:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            inicio, fin = conn.execute(
                "SELECT start_at, end_at FROM bookings WHERE id=?", (bid,)).fetchone()
        ocupa = (datetime.strptime(fin, "%Y-%m-%dT%H:%M:%SZ")
                 - datetime.strptime(inicio, "%Y-%m-%dT%H:%M:%SZ"))
        assert ocupa == timedelta(minutes=entendido["duracion"]), (
            "se enseñan %s min y se apartan %s" % (entendido["duracion"], ocupa))
    finally:
        with sqlite3.connect(api_module.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE id=?", (bid,))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (bid,))
            conn.commit()
