"""Omitir email no convierte un rechazo de WhatsApp en un aviso enviado."""
import asyncio
import copy
from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest

from conftest import DEFAULT_DEMO_CONFIG


@pytest.fixture
def entorno(vantelia_env_factory, monkeypatch):
    vantelia_env_factory(copy.deepcopy(DEFAULT_DEMO_CONFIG))
    from backend import agenda, booking, db, timeutils, wa_plantillas

    inicio = timeutils._utc_now() + timedelta(hours=24, minutes=20)
    booking_id = "bk_recordatorio_" + uuid.uuid4().hex
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO bookings (id, cliente_id, nombre, email, telefono, servicio,"
            "booking_date, booking_time, status, provider_status, source, manage_token,"
            "booking_code, created_at, start_at, end_at, timezone) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (booking_id, "demo", "Clienta Sintetica", "", "600111222", "Consulta",
             inicio.date().isoformat(), inicio.strftime("%H:%M"), "confirmed", "internal",
             "test", "tok_" + uuid.uuid4().hex, "R-SINTETICA", timeutils._utc_now_iso(),
             inicio.isoformat(), (inicio + timedelta(minutes=30)).isoformat(), "Europe/Madrid"),
        )
        conexion.commit()
    monkeypatch.setattr(booking, "_booking_email_enabled", lambda *a: True)
    monkeypatch.setattr(agenda, "_effective_followup_channels", lambda *a: {
        "reminder_24h": {"email": True, "whatsapp": True, "sms": False}})
    monkeypatch.setattr(booking, "_whatsapp_deliverable_for_booking", lambda *a: (True, ""))
    async def sin_refresco(*a):
        pass
    monkeypatch.setattr(wa_plantillas, "refrescar_pendientes", sin_refresco)
    return SimpleNamespace(booking=booking, booking_id=booking_id)


@pytest.mark.parametrize("respuesta", [False, TimeoutError("timeout sintetico")])
def test_email_omitido_y_whatsapp_fallido_permiten_reintento(entorno, monkeypatch, respuesta):
    b, booking_id = entorno.booking, entorno.booking_id
    intentos = []
    async def enviar(*a, **kwargs):
        intentos.append(1)
        if len(intentos) > 1:
            return True
        if isinstance(respuesta, Exception):
            raise respuesta
        from backend import messaging
        return messaging.WhatsAppSendResult("rechazado", motivo="rechazo_explicito")
    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", enviar)
    primero = asyncio.run(b._run_booking_reminders())
    assert primero.failed == 1
    assert primero.sent_24h == 0
    assert not b._get_booking_row_by_id(booking_id)["reminder_24h_sent_at"]
    segundo = asyncio.run(b._run_booking_reminders())
    if isinstance(respuesta, Exception):
        assert len(intentos) == 1, "un timeout no autoriza repetir el aviso"
        assert not b._get_booking_row_by_id(booking_id)["reminder_24h_sent_at"]
        return
    assert segundo.sent_24h == 1
    assert b._get_booking_row_by_id(booking_id)["reminder_24h_sent_at"]
    asyncio.run(b._run_booking_reminders())
    assert len(intentos) == 2, "el envio ya aceptado no debe repetirse"


def test_caller_sin_excepcion_tambien_conserva_fallo_sin_marcar_enviado(entorno, monkeypatch):
    b = entorno.booking
    async def rechazado(*a, **kwargs):
        from backend import messaging
        return messaging.WhatsAppSendResult("rechazado", motivo="rechazo_explicito")
    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", rechazado)
    resultado = asyncio.run(b._send_booking_reminder_by_kind(
        b._get_booking_row_by_id(entorno.booking_id), "reminder_24h",
        sent_column="reminder_24h_sent_at", raise_on_failure=False))
    assert resultado["sent"] == []
    assert "email" in resultado["skipped"] and "whatsapp" in resultado["failed"]
    assert not b._get_booking_row_by_id(entorno.booking_id)["reminder_24h_sent_at"]


def test_todos_omitidos_se_cierran_sin_bucle(entorno, monkeypatch):
    b = entorno.booking
    comprobaciones = []
    def no_entregable(*a):
        comprobaciones.append(1)
        return False, "canal sin configurar"
    monkeypatch.setattr(b, "_whatsapp_deliverable_for_booking", no_entregable)
    asyncio.run(b._run_booking_reminders())
    fila = b._get_booking_row_by_id(entorno.booking_id)
    assert fila["reminder_24h_sent_at"]
    assert "skipped" in fila["customer_email_status"]
    asyncio.run(b._run_booking_reminders())
    assert len(comprobaciones) == 1


def test_aceptacion_parcial_no_repite_el_canal_ya_enviado(entorno, monkeypatch):
    b = entorno.booking
    b._update_booking_record(entorno.booking_id, email="sintetica@example.invalid")
    emails = []
    def email_aceptado(*a):
        emails.append(1)
        return True
    async def whatsapp_rechazado(*a, **kwargs):
        from backend import messaging
        return messaging.WhatsAppSendResult("rechazado", motivo="rechazo_explicito")
    monkeypatch.setattr(b, "_send_booking_email", email_aceptado)
    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", whatsapp_rechazado)
    resultado = asyncio.run(b._send_booking_reminder_by_kind(
        b._get_booking_row_by_id(entorno.booking_id), "reminder_24h",
        sent_column="reminder_24h_sent_at",
        channel_override={"email": True, "whatsapp": True, "sms": False}))
    assert resultado["sent"] == ["email"]
    assert "whatsapp" in resultado["failed"]
    assert b._get_booking_row_by_id(entorno.booking_id)["reminder_24h_sent_at"]
    asyncio.run(b._run_booking_reminders())
    assert len(emails) == 1


def test_dos_ejecutores_no_deben_enviar_el_mismo_recordatorio(entorno, monkeypatch):
    b = entorno.booking
    enviados = []
    async def carrera():
        primero_dentro = asyncio.Event()
        continuar = asyncio.Event()
        async def enviar(*a, **kwargs):
            enviados.append(1)
            primero_dentro.set()
            await asyncio.wait_for(continuar.wait(), timeout=3)
            return True
        monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", enviar)
        primero = asyncio.create_task(b._run_booking_reminders())
        await primero_dentro.wait()
        segundo = asyncio.create_task(b._run_booking_reminders())
        await asyncio.sleep(0)
        continuar.set()
        await asyncio.gather(primero, segundo)
    asyncio.run(carrera())
    assert len(enviados) == 1, "dos workers leen timestamp vacio antes del envio: %s" % len(enviados)
    assert b._get_booking_row_by_id(entorno.booking_id)["reminder_24h_sent_at"]
