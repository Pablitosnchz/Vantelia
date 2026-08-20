# -*- coding: utf-8 -*-
"""Mientras actúa el producto, la profesional está libre.

Un pack de mechas dura 6-7 horas, pero de ese rato la profesional solo trabaja 4:
el resto la clienta espera a que el producto haga efecto y ella puede atender a
otra. Bloquear el rango entero le tira media jornada.

Con los números reales del salón (pack de mechas o balayage extra largo):

    MECHAS MUY LARGO   105 min de trabajo → 90 de espera
    MATIZ               30                → 30
    ELUMEN              30                → 20
    FLASH REPAIR        15                → 15
    BRUSING             60
    ────────────────────────────────────────────────────
    240 min trabajando + 155 esperando = 395 min (6,6 h)

El dato vive en `services.gap_json` y se copia a la cita al reservar (si el
negocio cambia el servicio después, las citas ya cogidas no se descolocan).

**Sin tramos, todo se comporta exactamente igual que antes**: es lo que hace que
esto no toque a ningún otro cliente.
"""
from __future__ import annotations

import json

import pytest

from backend import agenda
from test_booking_exhaustive import api_module, client  # noqa: F401

# Los tramos del pack real, tal y como salen de su Excel.
PACK_MECHAS = json.dumps([
    {"activo": 105, "espera": 90},
    {"activo": 30, "espera": 30},
    {"activo": 30, "espera": 20},
    {"activo": 15, "espera": 15},
    {"activo": 60, "espera": 0},
])


def test_sin_tramos_la_cita_ocupa_su_rango_entero():
    """El caso de siempre: un corte de 30 min bloquea 30 min."""
    assert agenda._tramos_de_trabajo("", 600, 30) == [(600, 630)]


@pytest.mark.parametrize("basura", ["no-es-json", "{}", "[]", "null", '[{"activo": "x"}]'])
def test_un_gap_json_ilegible_no_libera_nada(basura):
    """Ante la duda, bloquear entero: mejor perder un hueco que dar dos citas."""
    assert agenda._tramos_de_trabajo(basura, 600, 120) == [(600, 720)]


def test_los_ratos_de_espera_no_bloquean_a_la_profesional():
    tramos = agenda._tramos_de_trabajo(PACK_MECHAS, 600, 395)  # 10:00
    assert tramos == [
        (600, 705),   # 10:00-11:45  aplicando mechas
        (795, 825),   # 13:15-13:45  matiz    (esperando 11:45-13:15)
        (855, 885),   # 14:15-14:45  elumen   (esperando 13:45-14:15)
        (905, 920),   # 15:05-15:20  flash    (esperando 14:45-15:05)
        (935, 995),   # 15:35-16:35  brusing  (esperando 15:20-15:35)
    ]
    assert tramos[-1][1] - 600 == 395, "de que entra a que sale son 6,6 h" 
    ocupada = sum(fin - ini for ini, fin in tramos)
    assert ocupada == 240, "la profesional trabaja 4 h de las 6,6 que dura"


def test_el_hueco_de_espera_mas_largo_da_para_otra_clienta():
    """Los 90 minutos entre las mechas y el matiz: ahi entra un corte y un peinado."""
    tramos = agenda._tramos_de_trabajo(PACK_MECHAS, 600, 395)
    huecos = [(tramos[i][1], tramos[i + 1][0]) for i in range(len(tramos) - 1)]
    mayor = max(fin - ini for ini, fin in huecos)
    assert mayor == 90


def test_unos_tramos_que_no_cuadran_con_la_duracion_bloquean_entero():
    """Si alguien edita el servicio y los tramos suman de mas, no se libera nada:
    lo contrario dejaria entrar una cita encima del final de la anterior."""
    pasados = json.dumps([{"activo": 300, "espera": 300}])
    assert agenda._tramos_de_trabajo(pasados, 600, 60) == [(600, 660)]


def test_un_tramo_sin_trabajo_no_ocupa_nada():
    """Un paso que es solo espera (el producto actúa y ya) no bloquea."""
    solo_espera = json.dumps([{"activo": 0, "espera": 60}, {"activo": 30, "espera": 0}])
    assert agenda._tramos_de_trabajo(solo_espera, 600, 90) == [(660, 690)]


# ─── De punta a punta: otra clienta entra en el hueco ───────────────────────

def test_otra_clienta_cabe_en_el_rato_de_espera(api_module, client):  # noqa: F811
    """La prueba que importa: con un pack de 6,6 h reservado a las 10:00, ¿puede
    otra clienta coger cita a la hora en que la profesional está esperando?

    Antes se bloqueaban las 6,6 h enteras y la respuesta era no para todo el día.
    """
    from datetime import date, timedelta

    from backend import agenda, appstate, db, timeutils

    appstate.rate_limit_buckets.clear()
    dia = date.today() + timedelta(days=9)
    while dia.weekday() == 6:
        dia += timedelta(days=1)

    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, name, duration_minutes,"
            " price_cents, is_active, gap_json, created_at) VALUES (?,?,?,?,?,1,?,?)",
            ("demo", "pack_mechas", "Pack mechas", 395, 24400, PACK_MECHAS,
             timeutils._utc_now_iso()),
        )
        conexion.commit()

    origen = {"Origin": "http://testserver"}
    pack = client.post("/agendar", json={
        "cliente_id": "demo", "nombre": "Clienta Pack", "email": "pack@ejemplo.com",
        "telefono": "600111222", "fecha": dia.isoformat(), "hora": "10:00",
        "servicio": "Pack mechas", "notas": "",
    }, headers=origen)
    assert pack.status_code == 200, pack.text[:200]

    # 12:00 cae dentro de la espera de 11:45 a 13:15: la profesional está libre.
    hueco = client.post("/agendar", json={
        "cliente_id": "demo", "nombre": "Clienta Corte", "email": "corte@ejemplo.com",
        "telefono": "600333444", "fecha": dia.isoformat(), "hora": "12:00",
        "servicio": "Consulta", "notas": "",
    }, headers=origen)
    assert hueco.status_code == 200, (
        "el rato de espera tiene que quedar libre para otra clienta: %s" % hueco.text[:200]
    )

    # 10:30 cae mientras aplica las mechas: ahí NO cabe nadie.
    ocupado = client.post("/agendar", json={
        "cliente_id": "demo", "nombre": "Clienta Tarde", "email": "tarde@ejemplo.com",
        "telefono": "600555666", "fecha": dia.isoformat(), "hora": "10:30",
        "servicio": "Consulta", "notas": "",
    }, headers=origen)
    assert ocupado.status_code == 409, (
        "mientras trabaja no puede entrar otra cita: %s" % ocupado.text[:200]
    )


# ─── Los tramos se pueden crear y editar por API ───────────────────────────

def _sesion(api_module):
    """Cookie de portal, como el resto de tests del panel."""
    usuario = api_module._get_user_by_email("admin@example.com")
    return {"vantelia_portal_session": api_module._create_auth_session(usuario["id"])}


def test_un_servicio_con_tramos_se_crea_y_se_lee_igual(api_module, client):  # noqa: F811
    """Sin esto los tramos solo se podrian meter tocando la base de datos."""
    galletas = _sesion(api_module)
    parametros = {"cliente_id": "demo"}
    alta = client.post("/auth/services", params=parametros, cookies=galletas, json={
        "nombre": "Alisado con esperas",
        "duration_minutes": 195,
        "price_cents": 15000,
        "gaps": [{"activo": 105, "espera": 90}, {"activo": 0, "espera": 0}],
    })
    assert alta.status_code == 200, alta.text[:200]
    assert alta.json()["gaps"] == [{"activo": 105, "espera": 90}, {"activo": 0, "espera": 0}]

    # Y se pueden cambiar sin tocar el resto del servicio.
    slug = alta.json()["id"]
    cambio = client.patch("/auth/services/%s" % slug, params=parametros, cookies=galletas,
                          json={"gaps": [{"activo": 60, "espera": 30}]})
    assert cambio.status_code == 200, cambio.text[:200]
    assert cambio.json()["gaps"] == [{"activo": 60, "espera": 30}]
    assert cambio.json()["duration_minutes"] == 195, "no se toca lo que no se manda"


def test_un_servicio_normal_no_tiene_tramos(api_module, client):  # noqa: F811
    """El caso de siempre: sin tramos, ocupa su duracion entera."""
    alta = client.post("/auth/services", params={"cliente_id": "demo"},
                       cookies=_sesion(api_module), json={
        "nombre": "Corte sencillo", "duration_minutes": 30, "price_cents": 2000,
    })
    assert alta.status_code == 200, alta.text[:200]
    assert alta.json()["gaps"] == []
