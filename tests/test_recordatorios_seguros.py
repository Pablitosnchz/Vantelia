# -*- coding: utf-8 -*-
"""Los recordatorios por WhatsApp arrancan solos y nunca escriben a quien no es.

POR QUE EXISTE
--------------
Al revisar el primer montaje de los recordatorios con plantilla (11-sep-2026):

- La plantilla no se daba de alta en ninguna parte: `wa_plantillas.asegurar`
  existia pero nadie la llamaba, asi que no habia plantilla que aprobar y ningun
  recordatorio salia fuera de la ventana de 24 h.
- Las citas de DEMO entraban en el reparto de recordatorios (y de llamadas de
  confirmacion). La cuenta de revision de Meta tiene 191 con moviles inventados
  que pueden ser de personas reales, y el +31 conectado: con WhatsApp activado en
  sus avisos, se les habria escrito a todos.
"""
from __future__ import annotations

import asyncio
import datetime
import uuid

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


def _cita(api_module, source, hora):  # noqa: F811
    manana = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    record = {
        "id": "bk_rec_%s" % uuid.uuid4().hex[:10],
        "cliente_id": "demo", "employee_id": "", "employee_name": "",
        "nombre": "Ana Ruiz Pérez", "email": "", "telefono": "34600999111",
        "servicio": "Consulta", "booking_date": manana,
        "booking_time": hora, "notas": "", "status": "confirmed",
        "provider_name": "internal", "provider_status": "confirmed",
        "provider_booking_id": "", "provider_booking_url": "",
        "manage_token": "mg_rec_%s" % uuid.uuid4().hex[:10],
        "timezone": "Europe/Madrid", "start_at": "", "end_at": "",
        "confirmed_at": api_module._utc_now_iso(), "cancelled_at": "",
        "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": "",
        "reminder_2h_sent_at": "", "customer_email_status": "",
        "customer_email_last_error": "", "source": source,
        "created_at": api_module._utc_now_iso(),
    }
    api_module._store_booking(record)
    return record["id"]


def test_las_citas_de_demo_no_reciben_recordatorios(api_module):  # noqa: F811
    from backend import booking, timeutils

    de_verdad = _cita(api_module, "whatsapp", "10:00")
    de_demo = _cita(api_module, "demo_seed", "11:00")

    ids = {fila["id"] for fila in booking._bookings_due_for_reminders(timeutils._utc_now())}

    assert de_verdad in ids
    assert de_demo not in ids, "una cita de demo no puede avisar ni llamar a nadie"


@pytest.fixture
def conectada(api_module, monkeypatch):  # noqa: F811
    """El negocio `demo` con su WhatsApp conectado y `asegurar` sin salir a Meta."""
    from backend import db, wa_onboarding, wa_plantillas

    monkeypatch.setattr(wa_onboarding, "phone_client_map", lambda: {"pn_demo": "demo"})
    llamadas = []

    async def asegurar(cliente_id, **kwargs):
        llamadas.append(cliente_id)
        return {}

    monkeypatch.setattr(wa_plantillas, "asegurar", asegurar)
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM wa_templates WHERE cliente_id = 'demo'")
        conexion.commit()
    return llamadas


def _estado_hace(status, horas):
    from backend import db, timeutils, wa_plantillas

    wa_plantillas.guardar_estado("demo", status=status)
    antes = timeutils._to_utc_iso(timeutils._utc_now() - datetime.timedelta(hours=horas))
    with db._get_db_connection() as conexion:
        conexion.execute("UPDATE wa_templates SET updated_at = ? WHERE cliente_id = 'demo'", (antes,))
        conexion.commit()


def test_la_plantilla_se_da_de_alta_sola(conectada):
    from backend import wa_plantillas

    asyncio.run(wa_plantillas.refrescar_pendientes())

    assert conectada == ["demo"], "sin alta no hay plantilla que aprobar"


@pytest.mark.parametrize("status,horas,pregunta", [
    ("PENDING", 0, False),     # recien consultada: no se machaca a Meta
    ("PENDING", 2, True),      # en revision: cada hora
    ("APPROVED", 2, False),    # aprobada: una vez al dia
    ("APPROVED", 25, True),
    ("REJECTED", 25, True),
])
def test_se_pregunta_por_la_aprobacion_sin_machacar_a_meta(conectada, status, horas, pregunta):
    from backend import wa_plantillas

    _estado_hace(status, horas)
    asyncio.run(wa_plantillas.refrescar_pendientes())

    assert (conectada == ["demo"]) is pregunta


def test_el_worker_de_recordatorios_refresca_las_plantillas(api_module, monkeypatch):  # noqa: F811
    from backend import booking, wa_plantillas

    llamadas = []

    async def refrescar(ahora=None):
        llamadas.append(ahora)
        return 0

    monkeypatch.setattr(wa_plantillas, "refrescar_pendientes", refrescar)
    asyncio.run(booking._run_booking_reminders())

    assert llamadas, "el worker tiene que dar de alta y consultar las plantillas"
