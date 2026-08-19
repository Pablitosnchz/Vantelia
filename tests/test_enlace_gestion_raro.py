# -*- coding: utf-8 -*-
"""El enlace de gestion que recibe el cliente final por email.

`/booking/manage/{token}` y `/p/{token}` son publicos: basta con tener el enlace.
Se comprueba que ningun token raro provoque un 500 (un error del servidor en la
pagina que el cliente abre desde su email es de las peores caras que podemos
poner), que no se filtren citas de otro y que cancelar dos veces no rompa nada.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from test_booking_exhaustive import api_module, client  # noqa: F401

ORIGEN = {"Origin": "http://testserver"}

TOKENS_RAROS = [
    pytest.param("", id="vacio"),
    pytest.param("   ", id="espacios"),
    pytest.param("a", id="una-letra"),
    pytest.param("x" * 500, id="larguisimo"),
    pytest.param("../../etc/passwd", id="path-traversal"),
    pytest.param("..%2f..%2fetc%2fpasswd", id="path-traversal-codificado"),
    pytest.param("'; DROP TABLE bookings;--", id="inyeccion-sql"),
    pytest.param("<script>alert(1)</script>", id="script"),
    pytest.param("NULL", id="null"),
    pytest.param("0", id="cero"),
    pytest.param("%00", id="byte-nulo"),
    pytest.param("token con espacios", id="con-espacios"),
    pytest.param("🔥", id="emoji"),
]


@pytest.fixture(autouse=True)
def sin_rate_limit(api_module):  # noqa: F811
    from backend import appstate

    appstate.rate_limit_buckets.clear()
    yield
    appstate.rate_limit_buckets.clear()


@pytest.mark.parametrize("token", TOKENS_RAROS)
def test_un_token_raro_no_rompe_la_pagina_de_gestion(client: TestClient, token):
    respuesta = client.get("/booking/manage/%s" % token, headers=ORIGEN)
    assert respuesta.status_code < 500, (
        "token %r provoca un error del servidor: %s" % (token[:40], respuesta.text[:160])
    )


@pytest.mark.parametrize("token", TOKENS_RAROS)
def test_un_token_raro_no_rompe_el_enlace_corto_de_pago(client: TestClient, token):
    respuesta = client.get("/p/%s" % token, headers=ORIGEN, follow_redirects=False)
    assert respuesta.status_code < 500, (
        "token %r provoca un error del servidor: %s" % (token[:40], respuesta.text[:160])
    )


def _crear_cita(client: TestClient, hora: str) -> dict:
    dia = date.today() + timedelta(days=2)
    if dia.weekday() == 6:
        dia += timedelta(days=1)
    respuesta = client.post("/agendar", json={
        "cliente_id": "demo", "nombre": "Cliente Enlace", "email": "enlace@ejemplo.com",
        "telefono": "600333444", "fecha": dia.isoformat(), "hora": hora,
        "servicio": "Consulta", "notas": "",
    }, headers=ORIGEN)
    assert respuesta.status_code == 200, respuesta.text[:200]
    return respuesta.json()


def test_el_enlace_real_abre_la_pagina(client: TestClient):
    datos = _crear_cita(client, "13:00")
    url = datos.get("manage_url") or ""
    assert url, "la reserva no devolvio enlace de gestion: %s" % datos
    token = url.rstrip("/").rsplit("/", 1)[-1]
    respuesta = client.get("/booking/manage/%s" % token, headers=ORIGEN)
    assert respuesta.status_code == 200
    assert "Cliente Enlace" in respuesta.text or "Consulta" in respuesta.text


def test_cancelar_dos_veces_por_el_enlace_no_rompe(client: TestClient):
    """El cliente pulsa "cancelar", recarga y vuelve a pulsar."""
    from backend import booking

    datos = _crear_cita(client, "13:30")
    token = (datos.get("manage_url") or "").rstrip("/").rsplit("/", 1)[-1]
    fila = booking._load_booking_by_token_or_404(token)

    import asyncio

    primera = asyncio.run(booking._cancel_booking_core(fila, source="manage_link"))
    assert primera is not None

    fila2 = booking._load_booking_by_token_or_404(token)
    segunda = asyncio.run(booking._cancel_booking_core(fila2, source="manage_link"))
    assert segunda is not None, "cancelar dos veces tiene que ser idempotente, no reventar"
