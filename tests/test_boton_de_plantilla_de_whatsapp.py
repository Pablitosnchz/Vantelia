# -*- coding: utf-8 -*-
"""El boton de una PLANTILLA de WhatsApp confirma o cancela la cita, como el de
un mensaje interactivo.

POR QUE EXISTE
--------------
Un recordatorio 24 h antes de la cita cae casi siempre FUERA de la ventana de 24 h
de Meta, asi que tiene que salir como plantilla. Y los botones de una plantilla no
llegan igual que los de un mensaje interactivo: Meta manda

    {"type": "button", "button": {"payload": "bkok_<id>", "text": "Confirmo"}}

y no un `interactive.button_reply`. Sin la rama de `type: "button"` en el webhook,
ese mensaje caia en el cajon de lo ilegible: la clienta pulsaba "Confirmo" en el
recordatorio y se le contestaba *"no me ha llegado bien tu mensaje"*, la cita se
quedaba sin confirmar y el negocio no se enteraba.

El payload de los botones de la plantilla es EL MISMO id que ya usan los botones
interactivos (`bkok_` / `bkcancel_`), asi que a partir de la rama nueva el camino
es el de siempre: `_wa_handle_reminder_reply`, que verifica el telefono.

Los tests ejecutan el webhook entero, firmado como lo firma Meta.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid

import pytest

from test_booking_exhaustive import _next_weekday, api_module, client  # noqa: F401

SECRETO = "secreto-de-prueba"


def _peticion(payload):
    from starlette.requests import Request

    cuerpo = json.dumps(payload).encode("utf-8")
    firma = "sha256=" + hmac.new(SECRETO.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()

    async def recibir():
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    scope = {
        "type": "http", "method": "POST", "path": "/whatsapp/webhook/demo",
        "query_string": b"", "client": ("testclient", 50000),
        "headers": [(b"x-hub-signature-256", firma.encode("ascii"))],
    }
    return Request(scope, recibir)


def _boton_de_plantilla(telefono, payload_boton, texto):
    """Lo que manda Meta cuando se pulsa el boton de una plantilla."""
    mensaje = {
        "from": telefono,
        "id": "wamid.%s" % uuid.uuid4().hex,
        "type": "button",
        "button": {"payload": payload_boton, "text": texto},
    }
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "WA_NUM_ID"},
        "messages": [mensaje],
    }}]}]}


def _recibir(payload):
    from backend import whatsapp

    return asyncio.run(whatsapp._handle_whatsapp_webhook(_peticion(payload), forced_cliente_id="demo"))


@pytest.fixture
def enviados(api_module, monkeypatch):  # noqa: F811
    """Lo que el asistente le manda a la clienta."""
    from backend import messaging, settings

    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", SECRETO)
    salida = []

    async def _texto(*, text, **kwargs):
        salida.append(text)
        return True

    async def _otro(**kwargs):
        salida.append(kwargs)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", _texto)
    for nombre in ("_send_whatsapp_buttons", "_send_whatsapp_list",
                   "_send_whatsapp_cta_url", "_send_whatsapp_payload"):
        monkeypatch.setattr(messaging, nombre, _otro)
    return salida


@pytest.fixture
def cita(api_module):  # noqa: F811
    """Una cita confirmada de una clienta que tiene telefono."""
    from backend import db

    telefono = "34600777%03d" % (uuid.uuid4().int % 1000)
    record = {
        "id": "bk_plantilla_%s" % uuid.uuid4().hex[:8],
        "cliente_id": "demo", "employee_id": "", "employee_name": "",
        "nombre": "Clienta Plantilla", "email": "", "telefono": telefono,
        "servicio": "Consulta", "booking_date": _next_weekday(1),
        "booking_time": "10:00", "notas": "", "status": "confirmed",
        "provider_name": "internal", "provider_status": "confirmed",
        "provider_booking_id": "", "provider_booking_url": "",
        "manage_token": "mg_pl_%s" % uuid.uuid4().hex[:8],
        "timezone": "Europe/Madrid", "start_at": "", "end_at": "",
        "confirmed_at": "", "cancelled_at": "",
        "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": "",
        "reminder_2h_sent_at": "", "customer_email_status": "",
        "customer_email_last_error": "", "source": "whatsapp",
        "created_at": api_module._utc_now_iso(),
    }
    api_module._store_booking(record)
    try:
        yield record
    finally:
        with db._get_db_connection() as connection:
            connection.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            connection.execute("DELETE FROM booking_audit WHERE booking_id = ?", (record["id"],))
            connection.commit()


def _eventos(booking_id):
    from backend import db

    with db._get_db_connection() as connection:
        filas = connection.execute(
            "SELECT event_type FROM booking_audit WHERE booking_id = ?", (booking_id,)
        ).fetchall()
    return [f["event_type"] for f in filas]


def test_confirmo_desde_una_plantilla_confirma_la_cita(enviados, cita):
    """Lo que falla sin la rama: la clienta pulsa "Confirmo" y no pasa nada."""
    _recibir(_boton_de_plantilla(cita["telefono"], "bkok_%s" % cita["id"], "✅ Confirmo"))

    assert "attendance_confirmed_by_customer" in _eventos(cita["id"]), \
        "el boton de la plantilla no ha confirmado la asistencia"
    assert any("confirmada" in str(m).lower() for m in enviados), enviados
    assert not any("no me ha llegado bien" in str(m).lower() for m in enviados), \
        "se le ha contestado que el mensaje era ilegible"


def test_cancelar_desde_una_plantilla_cancela_la_cita(enviados, cita, monkeypatch):
    """bkcancel identifica una cita, pero pudo cambiar desde el recordatorio.

    Se muestra la versión actual y solo su aceptación permite cancelarla.
    """
    from backend import booking, db

    async def _sin_proveedor(*args, **kwargs):
        return None

    monkeypatch.setattr(booking, "_cancel_provider_booking", _sin_proveedor)

    _recibir(_boton_de_plantilla(cita["telefono"], "bkcancel_%s" % cita["id"], "❌ Cancelar cita"))

    with db._get_db_connection() as connection:
        assert connection.execute("SELECT status FROM bookings WHERE id = ?",
            (cita["id"],)).fetchone()["status"] == "confirmed"
    oferta = next(m for m in enviados if isinstance(m, dict) and m.get("header") == "Cancelar cita")
    boton = oferta["buttons"][0][0]
    assert boton.startswith("cancel_yes:")
    _recibir(_boton_de_plantilla(cita["telefono"], boton, "Sí, cancelar cita"))

    with db._get_db_connection() as connection:
        estado = connection.execute(
            "SELECT status FROM bookings WHERE id = ?", (cita["id"],)
        ).fetchone()["status"]
    assert estado == "cancelled", "el boton de la plantilla no ha cancelado la cita"
    assert any("cancelada" in str(m).lower() for m in enviados), enviados


def test_el_boton_de_otro_telefono_no_toca_la_cita(enviados, cita):
    """La verificacion de siempre sigue en pie: el payload no basta, hay que ser ella.

    Un payload es adivinable (`bkcancel_` + el id de la cita); el telefono lo
    verifica el canal. Sin esto, cualquiera podria cancelar citas ajenas.
    """
    _recibir(_boton_de_plantilla("34600999111", "bkcancel_%s" % cita["id"], "❌ Cancelar cita"))

    from backend import db

    with db._get_db_connection() as connection:
        estado = connection.execute(
            "SELECT status FROM bookings WHERE id = ?", (cita["id"],)
        ).fetchone()["status"]
    assert estado == "confirmed", "una cita ajena se ha cancelado desde otro telefono"
    assert any("no he podido localizar" in str(m).lower() for m in enviados), enviados


def test_cancelacion_del_recordatorio_revalida_cita_reprogramada(enviados, cita):
    """La identidad del recordatorio sobrevive a una reprogramación del portal.

    Ni el recordatorio antiguo ni aceptar un resumen anterior cancelan la nueva hora.
    """
    from backend import db
    with db._get_db_connection() as connection:
        connection.execute("UPDATE bookings SET booking_time='11:30' WHERE id=?", (cita["id"],))
        connection.commit()
    _recibir(_boton_de_plantilla(cita["telefono"], "bkcancel_%s" % cita["id"], "Cancelar cita"))
    oferta = next(m for m in enviados if isinstance(m, dict) and m.get("header") == "Cancelar cita")
    assert "11:30" in oferta["body"]
    with db._get_db_connection() as connection:
        connection.execute("UPDATE bookings SET booking_time='12:30' WHERE id=?", (cita["id"],))
        connection.commit()
    _recibir(_boton_de_plantilla(cita["telefono"], oferta["buttons"][0][0], "Sí, cancelar cita"))
    with db._get_db_connection() as connection:
        assert connection.execute("SELECT status FROM bookings WHERE id=?",
            (cita["id"],)).fetchone()["status"] == "confirmed"
    assert any("ha cambiado" in str(m) for m in enviados)
