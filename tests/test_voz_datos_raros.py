# -*- coding: utf-8 -*-
"""Las tools de voz reciben lo que rellena un MODELO, no un formulario.

Un formulario web valida en el navegador; aqui los argumentos los inventa
gpt-realtime a partir de lo que oye por telefono, que incluye ruido, cortes y
malentendidos. Si una tool acepta "2020-01-01" o "25:99", la cita queda mal en la
agenda del negocio sin que nadie lo note hasta que el cliente no aparece.

Se comprueba que ninguna entrada rara reviente (una excepcion en mitad de una
llamada deja al cliente escuchando silencio) y que lo imposible se rechaza.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

ORIGEN = {"Origin": "http://testserver"}


@pytest.fixture(autouse=True)
def sin_rate_limit(api_module):  # noqa: F811
    from backend import appstate

    appstate.rate_limit_buckets.clear()
    yield
    appstate.rate_limit_buckets.clear()


_HUECOS = iter(["09:%02d" % m for m in (0, 30)] + ["1%d:%02d" % (h, m)
                                                  for h in range(0, 8) for m in (0, 30)])


@pytest.fixture
def cita(client):
    """Una cita real sobre la que operar. Cada test coge SU hueco: si compartieran
    hora, el 409 legitimo del segundo pareceria un fallo del caso probado."""
    dia = date.today() + timedelta(days=6)
    while dia.weekday() == 6:
        dia += timedelta(days=1)
    respuesta = client.post("/agendar", json={
        "cliente_id": "demo", "nombre": "Cliente Voz", "email": "voz@ejemplo.com",
        "telefono": "600999888", "fecha": dia.isoformat(), "hora": next(_HUECOS),
        "servicio": "Consulta", "notas": "",
    }, headers=ORIGEN)
    assert respuesta.status_code == 200, respuesta.text[:200]
    return respuesta.json()


CODIGOS_RAROS = [
    pytest.param("", id="vacio"),
    pytest.param("   ", id="espacios"),
    pytest.param("R-", id="prefijo-suelto"),
    pytest.param("null", id="null"),
    pytest.param("undefined", id="undefined"),
    pytest.param("0", id="cero"),
    pytest.param("'; DROP TABLE bookings;--", id="inyeccion"),
    pytest.param("🔥", id="emoji"),
    pytest.param("x" * 300, id="larguisimo"),
]


@pytest.mark.parametrize("codigo", CODIGOS_RAROS)
def test_cancelar_por_voz_con_un_codigo_raro_no_revienta(api_module, codigo):  # noqa: F811
    from backend import voice

    resultado = asyncio.run(voice._voice_cancel_booking("demo", codigo))
    assert resultado.get("ok") is False
    assert resultado.get("error"), "hay que decirle algo al cliente: %r" % resultado


FECHAS_HORAS_IMPOSIBLES = [
    pytest.param("2020-01-01", "10:00", id="fecha-del-pasado"),
    pytest.param("2026-02-31", "10:00", id="fecha-que-no-existe"),
    pytest.param("manana", "10:00", id="fecha-en-palabras"),
    pytest.param("", "10:00", id="fecha-vacia"),
    pytest.param("2030-09-01", "25:99", id="hora-imposible"),
    pytest.param("2030-09-01", "", id="hora-vacia"),
    pytest.param("null", "null", id="ambas-null"),
    pytest.param("2030-09-01", "03:00", id="fuera-de-horario"),
]


def _tool(nombre, **argumentos):
    """Se llama por donde se llama de verdad: el dispatcher, con JSON del modelo."""
    import json

    from backend import voice

    return asyncio.run(voice._voice_dispatch_tool(
        "demo", nombre, json.dumps(argumentos, ensure_ascii=False), from_number="600999888",
    ))


@pytest.mark.parametrize("fecha,hora", FECHAS_HORAS_IMPOSIBLES)
def test_reprogramar_por_voz_rechaza_lo_imposible(api_module, cita, fecha, hora):  # noqa: F811
    """El modelo puede proponer cualquier cosa; la tool es el guardarrail.

    Y sobre todo: NO puede lanzar una excepcion. El puente la captura, marca la
    llamada como fallida y cuelga — el cliente se queda hablando solo.
    """
    resultado = _tool("reprogramar_cita", codigo_reserva=cita["booking_code"],
                      fecha=fecha, hora=hora, telefono="600999888")
    assert isinstance(resultado, dict), "la tool tiene que devolver un resultado, no reventar"
    assert resultado.get("ok") is not True, (
        "reprogramada a %r %r, que es imposible: %r" % (fecha, hora, resultado)
    )
    assert resultado.get("error") or resultado.get("mensaje_voz"), (
        "sin nada que decirle al cliente: %r" % resultado
    )


@pytest.mark.parametrize("nombre,argumentos", [
    pytest.param("crear_cita", {"fecha": "manana", "hora": "xx:xx"}, id="crear-con-basura"),
    pytest.param("cancelar_cita", {"codigo_reserva": None}, id="codigo-null"),
    pytest.param("reprogramar_cita", {}, id="sin-argumentos"),
    pytest.param("consultar_disponibilidad", {"fecha": 12345}, id="fecha-numerica"),
    pytest.param("tool_que_no_existe", {"x": 1}, id="tool-inventada"),
])
def test_ninguna_tool_puede_tumbar_la_llamada(api_module, nombre, argumentos):  # noqa: F811
    resultado = _tool(nombre, **argumentos)
    assert isinstance(resultado, dict), "%s reventó con %r" % (nombre, argumentos)


def test_reprogramar_por_voz_a_un_hueco_valido_funciona(api_module, cita):  # noqa: F811
    """Control: el guardarrail no puede bloquear lo legitimo."""
    from backend import voice

    dia = date.today() + timedelta(days=7)
    while dia.weekday() == 6:
        dia += timedelta(days=1)
    resultado = asyncio.run(voice._voice_reschedule_booking(
        "demo", cita["booking_code"], dia.isoformat(), "16:00", telefono="600999888",
    ))
    assert resultado.get("ok") is True, "reprogramacion legitima rechazada: %r" % resultado
