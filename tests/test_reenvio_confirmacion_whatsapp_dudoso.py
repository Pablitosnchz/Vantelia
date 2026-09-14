# -*- coding: utf-8 -*-
"""Reenviar a mano la confirmación con un WhatsApp dudoso: se avisa y decide la persona.

POR QUE EXISTE
--------------
Segunda revisión de Codex a los avisos (14-sep-2026): el botón «Enviar confirmación» del
panel no pasa por el registro de entregas. Si Meta no contestaba, el panel mostraba un
error genérico; el negocio volvía a pulsar y la clienta podía recibir dos WhatsApp. Ya
pasaba antes de ese día.

Decisión de Pablo del 14-sep-2026, «Avisar y dejar reenviar»: el resultado dudoso se
explica tal cual; el siguiente reenvío pide confirmación («puede que ya le haya llegado») y,
si la persona confirma, se reenvía.
"""
import asyncio
import pathlib

import pytest
from fastapi import HTTPException

import test_recordatorio_omitido_y_fallido as avisos

entorno = avisos.entorno


def _preparar(entorno, monkeypatch, resultados):
    from backend import agenda, messaging

    b = entorno.booking
    b._update_booking_record(entorno.booking_id, telefono="+34600111222")
    monkeypatch.setattr(agenda, "_effective_followup_channels",
                        lambda *a: {"confirmed": {"email": False, "whatsapp": True, "sms": False}})
    enviados = []

    async def whatsapp(*a, **k):
        estado = resultados[min(len(enviados), len(resultados) - 1)]
        enviados.append(estado)
        if not k.get("detailed"):
            return estado == "aceptado"  # como el real: sin detalle solo dice si o no
        return messaging.WhatsAppSendResult(
            estado, provider_message_id="wamid.sintetico" if estado == "aceptado" else "",
            motivo="sin_respuesta_de_meta" if estado == "desconocido" else "")

    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", whatsapp)
    return b, enviados


def _reenviar(b, booking_id, **k):
    return asyncio.run(b._resend_booking_confirmation(b._get_booking_row_by_id(booking_id), by_user="u_test", **k))


def test_un_whatsapp_dudoso_se_explica_y_el_siguiente_reenvio_pide_confirmacion(entorno, monkeypatch):
    b, enviados = _preparar(entorno, monkeypatch, ["desconocido", "aceptado"])

    with pytest.raises(HTTPException) as primero:
        _reenviar(b, entorno.booking_id)
    texto = str(primero.value.detail).lower()
    assert "puede que" in texto and "whatsapp" in texto, (
        "el panel da un error generico y el negocio vuelve a pulsar: %r" % primero.value.detail)

    with pytest.raises(HTTPException) as segundo:
        _reenviar(b, entorno.booking_id)
    assert segundo.value.status_code == 409
    assert isinstance(segundo.value.detail, dict), segundo.value.detail
    assert segundo.value.detail.get("code") == "WHATSAPP_SIN_CONFIRMAR"
    assert enviados == ["desconocido"], "sin confirmarlo no se vuelve a mandar"

    resultado = _reenviar(b, entorno.booking_id, force=True)
    assert resultado["sent"] == ["whatsapp"]
    assert enviados == ["desconocido", "aceptado"]


def test_tras_un_reenvio_entregado_no_se_pide_confirmacion(entorno, monkeypatch):
    b, enviados = _preparar(entorno, monkeypatch, ["desconocido", "aceptado", "aceptado"])

    with pytest.raises(HTTPException):
        _reenviar(b, entorno.booking_id)
    _reenviar(b, entorno.booking_id, force=True)
    _reenviar(b, entorno.booking_id)
    assert enviados == ["desconocido", "aceptado", "aceptado"]


def test_la_confirmacion_automatica_dudosa_tambien_avisa(entorno, monkeypatch):
    from backend import notice_deliveries

    b, enviados = _preparar(entorno, monkeypatch, ["aceptado"])
    fila = b._get_booking_row_by_id(entorno.booking_id)
    identidad = ("demo", entorno.booking_id, fila["reminder_generation"], "confirmed", "whatsapp")
    reclamado = notice_deliveries.claim_notice_delivery(*identidad)
    notice_deliveries.finish_notice_delivery(*identidad, reclamado["owner_token"], "desconocido")

    with pytest.raises(HTTPException) as exc:
        _reenviar(b, entorno.booking_id)
    assert isinstance(exc.value.detail, dict) and exc.value.detail.get("code") == "WHATSAPP_SIN_CONFIRMAR"
    assert enviados == []


def test_un_whatsapp_rechazado_no_pide_confirmacion(entorno, monkeypatch):
    """Control: si Meta dice que no, no puede haberle llegado."""
    b, enviados = _preparar(entorno, monkeypatch, ["rechazado", "aceptado"])

    with pytest.raises(HTTPException):
        _reenviar(b, entorno.booking_id)
    _reenviar(b, entorno.booking_id)
    assert enviados == ["rechazado", "aceptado"]


def test_el_panel_pregunta_antes_de_reenviar():
    html = (pathlib.Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")
    assert "WHATSAPP_SIN_CONFIRMAR" in html, "el panel no distingue el aviso del error"
    assert html.count("await sendBookingConfirmation(bid") == 3, "algun boton de reenviar no pasa por la pregunta"
    assert html.count("/send-confirmation") == 2, "queda un reenvio que no pregunta"


def test_un_reenvio_solo_por_email_no_tapa_el_whatsapp_dudoso(entorno, monkeypatch):
    """Tercera revisión de Codex (0b12b3c): el último evento se miraba sin fijarse en el canal."""
    from backend import agenda

    b, enviados = _preparar(entorno, monkeypatch, ["desconocido", "aceptado"])
    b._update_booking_record(entorno.booking_id, email="sintetica@example.invalid")
    with pytest.raises(HTTPException):
        _reenviar(b, entorno.booking_id)

    monkeypatch.setattr(agenda, "_effective_followup_channels",
                        lambda *a: {"confirmed": {"email": True, "whatsapp": False, "sms": False}})
    monkeypatch.setattr(b, "_send_booking_email", lambda *a: None)
    _reenviar(b, entorno.booking_id)

    monkeypatch.setattr(agenda, "_effective_followup_channels",
                        lambda *a: {"confirmed": {"email": False, "whatsapp": True, "sms": False}})
    with pytest.raises(HTTPException) as exc:
        _reenviar(b, entorno.booking_id)
    assert isinstance(exc.value.detail, dict) and exc.value.detail.get("code") == "WHATSAPP_SIN_CONFIRMAR", (
        "el email no resolvio si llego el WhatsApp: %r" % exc.value.detail)
    assert enviados == ["desconocido"]


def test_la_confirmacion_dudosa_tras_pagar_tambien_avisa(entorno, monkeypatch):
    """Tercera revisión de Codex (0b12b3c): la confirmación que sale al pagar no dejaba rastro."""
    b, enviados = _preparar(entorno, monkeypatch, ["desconocido", "aceptado"])

    asyncio.run(b.notify_booking_paid(b._get_booking_row_by_id(entorno.booking_id)))
    assert enviados == ["desconocido"]

    with pytest.raises(HTTPException) as exc:
        _reenviar(b, entorno.booking_id)
    assert isinstance(exc.value.detail, dict) and exc.value.detail.get("code") == "WHATSAPP_SIN_CONFIRMAR", (
        "el reenvio no sabe que el WhatsApp de tras pagar quedo dudoso: %r" % exc.value.detail)
    assert enviados == ["desconocido"]
