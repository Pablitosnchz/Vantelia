# -*- coding: utf-8 -*-
"""Dos personas reservando el mismo hueco a la vez.

Hay dos protecciones y cubren cosas distintas:

- El indice unico `idx_bookings_unique_slot` (cliente + empleado + fecha + hora)
  para la MISMA hora exacta.
- `agenda._booking_slot_available` para los SOLAPES parciales: un alisado de 90
  minutos a las 10:00 choca con un corte a las 10:30 aunque la hora no coincida.

La segunda es "comprobar y luego insertar", y entre las dos cosas cabe otra
peticion. Con los servicios de un salon real (de 20 a 300 minutos) los solapes
son la norma, asi que conviene tenerlo medido: si esto falla, dos clientas se
presentan a la vez y alguien se queda sin su cita.
"""
from __future__ import annotations

import asyncio
import threading
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from test_booking_exhaustive import api_module, client  # noqa: F401

ORIGEN = {"Origin": "http://testserver"}


def _dia_util(desplazamiento: int = 4) -> str:
    """Cada prueba usa SU dia.

    Compartiendo dia, el 409 legitimo de un test parecia un fallo del otro en
    cuanto pytest cambiaba el orden.
    """
    dia = date.today() + timedelta(days=desplazamiento)
    while dia.weekday() == 6:  # el tenant de pruebas cierra los domingos
        dia += timedelta(days=1)
    return dia.isoformat()


@pytest.fixture(autouse=True)
def sin_rate_limit(api_module):  # noqa: F811
    from backend import appstate

    appstate.rate_limit_buckets.clear()
    yield
    appstate.rate_limit_buckets.clear()


@pytest.fixture
def servicio_largo(api_module):  # noqa: F811
    """Un servicio de 90 minutos, para provocar solapes parciales de verdad."""
    from backend import db, timeutils

    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO services "
            "(cliente_id, slug, name, duration_minutes, price_cents, is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            ("demo", "alisado_largo", "Alisado largo", 90, 15000,
             timeutils._utc_now().isoformat()),
        )
        conexion.commit()
    yield "Alisado largo"  # el canal manda el NOMBRE, como el widget


def _reservar(client: TestClient, hora: str, servicio: str, nombre: str, dia: int = 4) -> tuple:
    respuesta = client.post("/agendar", json={
        "cliente_id": "demo", "nombre": nombre, "email": "%s@ejemplo.com" % nombre.lower(),
        "telefono": "600111222", "fecha": _dia_util(dia), "hora": hora,
        "servicio": servicio, "notas": "",
    }, headers=ORIGEN)
    return respuesta.status_code, respuesta.text[:120]


def _a_la_vez(client: TestClient, peticiones, dia: int = 4) -> list:
    resultados = [None] * len(peticiones)

    def trabajo(indice, args):
        try:
            resultados[indice] = _reservar(client, *args, dia=dia)
        except Exception as exc:  # noqa: BLE001
            resultados[indice] = ("EXCEPCION", "%s: %s" % (type(exc).__name__, exc))

    hilos = [threading.Thread(target=trabajo, args=(i, p)) for i, p in enumerate(peticiones)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=60)
    return resultados


def test_dos_reservas_simultaneas_a_la_misma_hora_solo_dejan_una(client: TestClient):
    resultados = _a_la_vez(client, [
        ("09:00", "Consulta", "Ana"),
        ("09:00", "Consulta", "Bea"),
    ], dia=4)
    creadas = [r for r in resultados if r and r[0] == 200]
    assert len(creadas) == 1, "doble reserva del mismo hueco: %r" % (resultados,)
    # Y la que pierde debe recibir un conflicto limpio, no un error del servidor.
    perdedora = [r for r in resultados if r and r[0] != 200]
    assert perdedora and all(r[0] < 500 for r in perdedora), (
        "la peticion que pierde la carrera recibe un error feo: %r" % (perdedora,)
    )


def test_un_solape_parcial_secuencial_se_rechaza(client: TestClient, servicio_largo):
    """Control: la comprobacion de solapes funciona cuando no hay carrera."""
    assert _reservar(client, "11:00", servicio_largo, "Carla", dia=5)[0] == 200
    codigo, cuerpo = _reservar(client, "11:30", "Consulta", "Diana", dia=5)
    assert codigo == 409, "el alisado de 90 min ocupa las 11:30: %s" % cuerpo


def test_dos_solapes_parciales_simultaneos_solo_dejan_uno(client: TestClient, servicio_largo):
    """El caso que el indice unico NO cubre: horas distintas que se pisan.

    Si este test falla, el salon acaba con dos clientas a la vez y hay que
    proteger la insercion (transaccion o re-comprobacion dentro del insert), no
    relajar el test.
    """
    resultados = _a_la_vez(client, [
        ("14:00", servicio_largo, "Eva"),
        ("14:30", "Consulta", "Fina"),
    ], dia=6)
    creadas = [r for r in resultados if r and r[0] == 200]
    assert len(creadas) <= 1, "dos citas solapadas creadas a la vez: %r" % (resultados,)
    assert all(r[0] < 500 for r in resultados if r), "error del servidor: %r" % (resultados,)


def test_dos_reprogramaciones_al_mismo_hueco_solo_dejan_una(client: TestClient):
    """Reprogramar tiene la MISMA estructura de riesgo: comprobar, llamar al
    proveedor, guardar.

    HASTA EL 14-sep-2026 ESTE TEST NO PROBABA NADA. Construia el cambio con
    `BookingReschedulePayload`, que no tiene `nombre` ni `servicio` (Pydantic 2 los
    descarta), y llamaba a `_update_booking_details` sin el `source` obligatorio: los
    dos hilos acababan SIEMPRE en excepcion, `count(200) <= 1` se cumplia solo, y por
    eso "pasaba con y sin la proteccion". Ademas las dos citas se creaban a horas
    fijas de un dia fijo y con profesional asignado al azar: en la suite completa,
    con huecos ocupados por otros tests, la creacion fallaba (rojo que dependia del
    orden) o caian en profesionales distintos y ya no competian por nada.

    Ahora las dos citas son del MISMO profesional, en un dia en que las dos caben,
    se mueven con el payload de verdad, y se exige que gane una y la otra reciba el
    409 limpio. Sin la re-comprobacion con el lock, este test falla.
    """
    from backend import agenda, booking

    def _crear(nombre, telefono, dia, hora):
        # Sin `employee_id`: la agenda general no se puede elegir desde el formulario
        # (400), asi que se comprueba DESPUES que las dos hayan caido en la misma.
        return client.post("/agendar", json={
            "cliente_id": "demo", "nombre": nombre, "email": "%s@ejemplo.com" % nombre.lower(),
            "telefono": telefono, "fecha": dia, "hora": hora, "servicio": "Consulta", "notas": "",
        }, headers=ORIGEN)

    destino = "16:30"   # las dos intentan moverse ahi a la vez
    creadas = None
    for desplazamiento in range(7, 30):
        dia = _dia_util(desplazamiento)
        primera = _crear("Gema", "600111222", dia, "15:00")
        if primera.status_code != 200:
            continue
        empleado = primera.json()["employee_id"]
        segunda = _crear("Hilda", "600333444", dia, "15:30")
        if (segunda.status_code == 200 and segunda.json()["employee_id"] == empleado
                and asyncio.run(agenda._booking_slot_available(
                    "demo", dia, destino, duration_minutes=30, employee_id=empleado))):
            creadas = (primera, segunda, dia, empleado)
            break
    assert creadas, "no se ha encontrado un dia con los tres huecos libres para el mismo profesional"
    primera, segunda, dia, empleado = creadas
    assert segunda.json()["employee_id"] == empleado

    tokens = [r.json()["manage_url"].rstrip("/").rsplit("/", 1)[-1] for r in (primera, segunda)]
    resultados = [None, None]

    def mover(indice):
        from api_models import BookingUpdatePayload

        fila = booking._get_booking_row_by_token(tokens[indice])
        datos = BookingUpdatePayload(
            nombre=fila["nombre"], email=fila["email"], telefono=fila["telefono"],
            servicio=fila["servicio"], employee_id=empleado, fecha=dia, hora=destino, notas="",
        )
        try:
            asyncio.run(booking._update_booking_details(fila, datos, None, source="test"))
            resultados[indice] = 200
        except Exception as exc:  # noqa: BLE001
            resultados[indice] = getattr(exc, "status_code", type(exc).__name__)

    hilos = [threading.Thread(target=mover, args=(i,)) for i in (0, 1)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=60)

    assert sorted(resultados, key=str) == [200, 409], (
        "tienen que competir de verdad: gana una y la otra recibe 409, no %r" % (resultados,))
    from backend import db

    with db._get_db_connection() as conexion:
        en_destino = conexion.execute(
            "SELECT COUNT(*) FROM bookings WHERE cliente_id='demo' AND employee_id=? AND booking_date=?"
            " AND booking_time=? AND status NOT IN ('cancelled')", (empleado, dia, destino)).fetchone()[0]
    assert en_destino == 1, "dos citas del mismo profesional en el mismo hueco: %d" % en_destino
