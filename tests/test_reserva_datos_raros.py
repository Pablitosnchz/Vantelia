# -*- coding: utf-8 -*-
"""Lo que se puede colar por el formulario de reserva.

`POST /agendar` es lo que usa el widget de la web del negocio: es el endpoint
publico que cualquiera puede llamar con lo que quiera. Se comprueban tres cosas:

- Ningun dato raro puede provocar un 500. Un error del servidor aqui deja al
  cliente sin cita y sin explicacion.
- Lo que NO debe entrar, no entra: fechas pasadas, horas fuera de horario,
  servicios inventados, contacto imposible.
- Lo que SI debe entrar, entra: un nombre con tilde o un apostrofe no pueden
  tumbar una reserva legitima.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from test_booking_exhaustive import api_module, client  # noqa: F401

ORIGEN = {"Origin": "http://testserver"}


@pytest.fixture(autouse=True)
def sin_rate_limit(api_module):  # noqa: F811
    """El limite por minuto es correcto, pero aqui se prueban muchas reservas
    seguidas desde la misma IP y taparia lo que se quiere ver."""
    from backend import appstate

    appstate.rate_limit_buckets.clear()
    yield
    appstate.rate_limit_buckets.clear()


def _manana() -> str:
    dia = date.today() + timedelta(days=1)
    if dia.weekday() == 6:  # el tenant de pruebas cierra los domingos
        dia += timedelta(days=1)
    return dia.isoformat()


def _cuerpo(**cambios):
    base = {
        "cliente_id": "demo",
        "nombre": "Cliente Prueba",
        "email": "prueba@ejemplo.com",
        "telefono": "600111222",
        "fecha": _manana(),
        "hora": "10:00",
        "servicio": "Consulta",
        "notas": "",
    }
    base.update(cambios)
    return base


# (etiqueta, cambios) — datos que NO deberian crear una cita
RECHAZABLES = [
    pytest.param({"fecha": (date.today() - timedelta(days=1)).isoformat()}, id="fecha-de-ayer"),
    pytest.param({"fecha": "1900-01-01"}, id="fecha-del-1900"),
    pytest.param({"fecha": "2026-02-31"}, id="fecha-imposible"),
    pytest.param({"fecha": "31/02/2026"}, id="formato-de-fecha-raro"),
    pytest.param({"hora": "25:00"}, id="hora-25"),
    pytest.param({"hora": "-1:00"}, id="hora-negativa"),
    pytest.param({"hora": "03:00"}, id="hora-fuera-de-horario"),
    pytest.param({"email": "no-es-un-email", "telefono": ""}, id="email-invalido-sin-telefono"),
    pytest.param({"email": "", "telefono": ""}, id="sin-forma-de-avisarle"),
    pytest.param({"cliente_id": "no_existe"}, id="cliente-inexistente"),
]


@pytest.mark.parametrize("cambios", RECHAZABLES)
def test_los_datos_imposibles_no_crean_cita(client: TestClient, cambios):
    respuesta = client.post("/agendar", json=_cuerpo(**cambios), headers=ORIGEN)
    assert respuesta.status_code < 500, "un dato raro no puede provocar un error del servidor"
    assert respuesta.status_code != 200, "no deberia haberse creado la cita: %s" % respuesta.text[:200]


# Datos legitimos que un validador demasiado estricto podria tumbar. Cada uno
# con SU hora: si compartieran hueco, el segundo recibiria un 409 legitimo y
# pareceria que el dato es el problema.
ACEPTABLES = [
    pytest.param("09:00", {"nombre": "José María Ñuño"}, id="nombre-con-tildes-y-ene"),
    pytest.param("09:30", {"nombre": "O'Connor"}, id="apostrofe"),
    pytest.param("10:30", {"nombre": "Anne-Marie"}, id="guion"),
    pytest.param("11:00", {"email": " prueba@ejemplo.com "}, id="email-con-espacios"),
    pytest.param("11:30", {"telefono": "+34 600 11 22 33"}, id="telefono-con-espacios"),
    pytest.param("12:00", {"notas": "Vengo con el pelo lavado"}, id="notas-normales"),
]


@pytest.mark.parametrize("hora,cambios", ACEPTABLES)
def test_los_datos_legitimos_no_se_rechazan(client: TestClient, hora, cambios):
    respuesta = client.post("/agendar", json=_cuerpo(hora=hora, **cambios), headers=ORIGEN)
    assert respuesta.status_code == 200, "reserva legitima rechazada: %s" % respuesta.text[:200]


def test_el_texto_peligroso_no_llega_crudo_a_la_cita(client: TestClient):
    """El nombre acaba en un email y en el panel: no puede viajar con etiquetas."""
    respuesta = client.post(
        "/agendar",
        json=_cuerpo(nombre="<script>alert(1)</script>", hora="16:00",
                     notas="'; DROP TABLE bookings;--"),
        headers=ORIGEN,
    )
    assert respuesta.status_code < 500
    if respuesta.status_code == 200:
        texto = respuesta.text
        assert "<script>" not in texto, "el nombre vuelve con la etiqueta intacta"


def test_dos_reservas_del_mismo_hueco_no_se_solapan(client: TestClient):
    """El segundo tiene que recibir 409, no quedarse con la cita del primero."""
    cuerpo = _cuerpo(hora="17:00")
    primera = client.post("/agendar", json=cuerpo, headers=ORIGEN)
    assert primera.status_code == 200, primera.text[:200]

    segunda = client.post("/agendar", json=_cuerpo(hora="17:00", nombre="Otro Cliente"),
                          headers=ORIGEN)
    assert segunda.status_code == 409, (
        "el hueco ya estaba ocupado y se ha aceptado igual: %s" % segunda.text[:200]
    )
