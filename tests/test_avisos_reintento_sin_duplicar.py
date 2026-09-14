# -*- coding: utf-8 -*-
"""Un fallo claro se reintenta; un WhatsApp dudoso no se repite, pero no deja a la clienta sin aviso.

POR QUE EXISTE
--------------
Decisión de Pablo del 14-sep-2026, «Reintentar sin duplicar WhatsApp»:

- Un fallo de email o SMS se reintenta en la siguiente vuelta y deja pasar al
  siguiente canal. Antes quedaba «desconocido» para siempre: el aviso no volvía a
  salir ni por ese canal ni por ningún otro.
- Un WhatsApp dudoso (Meta no contestó) no se repite, pero pasados 30 minutos sale
  por el siguiente canal.
- Un envío que sigue «enviando» más de 30 minutos (el proceso se cayó a medias)
  cuenta como dudoso: tampoco se repite por ese canal.

Riesgo aceptado: rara vez, un email repetido si el servidor lo entregó y se perdió
la respuesta. Lo que sigue vigente, en tests/test_entregas_recordatorios.py: dentro
de la media hora, un dudoso bloquea también el respaldo.
"""
import asyncio
from datetime import timedelta

import pytest

import test_recordatorio_omitido_y_fallido as avisos

entorno = avisos.entorno


def _canales(b, monkeypatch, orden, activos):
    from backend import agenda

    configuracion = b._follow_up_config("demo")
    monkeypatch.setattr(b, "_follow_up_config", lambda *a: dict(configuracion, delivery_priority=list(orden)))
    monkeypatch.setattr(agenda, "_effective_followup_channels", lambda *a: {"reminder_24h": dict(activos)})
    monkeypatch.setattr(agenda, "_reminder_channel_availability",
                        lambda *a: {"sms": {"available": True, "reason": ""}})


def _envejecer(booking_id, canal, minutos):
    from backend import db, timeutils

    hace = (timeutils._utc_now() - timedelta(minutes=minutos)).replace(tzinfo=None)
    with db._get_db_connection() as conn:
        conn.execute("UPDATE booking_notice_deliveries SET updated_at=? WHERE booking_id=? AND channel=?",
                     (hace.isoformat(timespec="seconds") + "Z", booking_id, canal))
        conn.commit()


def _sellado(entorno):
    return bool(entorno.booking._get_booking_row_by_id(entorno.booking_id)["reminder_24h_sent_at"])


@pytest.mark.parametrize("canal", ["email", "sms"])
def test_un_fallo_de_email_o_sms_se_reintenta_en_la_siguiente_vuelta(entorno, monkeypatch, canal):
    b = entorno.booking
    b._update_booking_record(entorno.booking_id, email="sintetica@example.invalid")
    _canales(b, monkeypatch, [canal], {"email": canal == "email", "whatsapp": False, "sms": canal == "sms"})
    intentos = []

    def email(*a):
        intentos.append("email")
        if len(intentos) == 1:
            raise ConnectionRefusedError("servidor de correo caido (sintetico)")

    async def sms(*a, **k):
        intentos.append("sms")
        return len(intentos) > 1

    monkeypatch.setattr(b, "_send_booking_email", email)
    monkeypatch.setattr(b, "_send_booking_sms_reminder", sms)

    asyncio.run(b._run_booking_reminders())
    assert intentos == [canal] and not _sellado(entorno)
    asyncio.run(b._run_booking_reminders())
    assert intentos == [canal, canal], "el fallo del canal dejo el aviso bloqueado para siempre"
    assert _sellado(entorno)
    asyncio.run(b._run_booking_reminders())
    assert intentos == [canal, canal], "un aviso ya entregado no se repite"


def test_un_fallo_de_email_pasa_al_siguiente_canal_en_la_misma_vuelta(entorno, monkeypatch):
    from backend import messaging

    b = entorno.booking
    b._update_booking_record(entorno.booking_id, email="sintetica@example.invalid")
    _canales(b, monkeypatch, ["email", "whatsapp"], {"email": True, "whatsapp": True, "sms": False})
    enviados = []

    def email(*a):
        enviados.append("email")
        raise ConnectionRefusedError("servidor de correo caido (sintetico)")

    async def whatsapp(*a, **k):
        enviados.append("whatsapp")
        return messaging.WhatsAppSendResult("aceptado", provider_message_id="wamid.sintetico")

    monkeypatch.setattr(b, "_send_booking_email", email)
    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", whatsapp)

    asyncio.run(b._run_booking_reminders())
    assert enviados == ["email", "whatsapp"]
    assert _sellado(entorno)


@pytest.mark.parametrize("minutos,sale_por_email", [(29, False), (31, True)])
def test_whatsapp_dudoso_sale_por_email_pasada_media_hora_sin_repetirse(entorno, monkeypatch, minutos,
                                                                        sale_por_email):
    from backend import messaging

    b = entorno.booking
    b._update_booking_record(entorno.booking_id, email="sintetica@example.invalid")
    _canales(b, monkeypatch, ["whatsapp", "email"], {"email": True, "whatsapp": True, "sms": False})
    enviados = []

    async def whatsapp(*a, **k):
        enviados.append("whatsapp")
        return messaging.WhatsAppSendResult("desconocido", motivo="sin_respuesta_de_meta")

    def email(*a):
        enviados.append("email")

    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", whatsapp)
    monkeypatch.setattr(b, "_send_booking_email", email)

    asyncio.run(b._run_booking_reminders())
    assert enviados == ["whatsapp"]
    _envejecer(entorno.booking_id, "whatsapp", minutos)
    asyncio.run(b._run_booking_reminders())
    asyncio.run(b._run_booking_reminders())
    assert enviados == (["whatsapp", "email"] if sale_por_email else ["whatsapp"])
    assert _sellado(entorno) is sale_por_email


@pytest.mark.parametrize("minutos,sale_por_email", [(29, False), (31, True)])
def test_un_envio_colgado_cuenta_como_dudoso(entorno, monkeypatch, minutos, sale_por_email):
    from backend import notice_deliveries

    b = entorno.booking
    b._update_booking_record(entorno.booking_id, email="sintetica@example.invalid")
    _canales(b, monkeypatch, ["whatsapp", "email"], {"email": True, "whatsapp": True, "sms": False})
    fila = b._get_booking_row_by_id(entorno.booking_id)
    reclamado = notice_deliveries.claim_notice_delivery(
        "demo", entorno.booking_id, fila["reminder_generation"], "reminder_24h", "whatsapp", single_delivery=True)
    assert reclamado["estado"] == "reclamado"  # y el proceso se cae aquí, sin terminar el envío
    _envejecer(entorno.booking_id, "whatsapp", minutos)
    enviados = []

    async def whatsapp(*a, **k):
        enviados.append("whatsapp")
        return True

    def email(*a):
        enviados.append("email")

    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", whatsapp)
    monkeypatch.setattr(b, "_send_booking_email", email)

    asyncio.run(b._run_booking_reminders())
    assert "whatsapp" not in enviados, "un envio a medias no se repite por el mismo canal"
    assert enviados == (["email"] if sale_por_email else [])
    assert _sellado(entorno) is sale_por_email
