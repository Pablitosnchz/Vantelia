"""El builder real de plantilla conserva el resultado de Meta en el ledger."""
import asyncio
import json

import pytest

import test_recordatorio_omitido_y_fallido as avisos

entorno = avisos.entorno


@pytest.mark.parametrize("estado", ["aceptado", "desconocido"])
def test_plantilla_real_persiste_resultado_y_auditoria(entorno, monkeypatch, estado):
    from backend import db, messaging, wa_plantillas

    b = entorno.booking
    llamadas = []
    monkeypatch.setattr(b, "_wa_ventana_abierta", lambda *a: False)
    monkeypatch.setattr(wa_plantillas, "estado", lambda *a: {
        "status": wa_plantillas.APROBADA, "name": wa_plantillas.NOMBRE_RECORDATORIO})
    monkeypatch.setattr(messaging, "_whatsapp_access_token_for_client", lambda *a: "token-sintetico")
    async def post_aislado(*args, **kwargs):
        llamadas.append(1)
        return messaging.WhatsAppSendResult(
            estado, provider_message_id="wamid.sintetico" if estado == "aceptado" else "")
    monkeypatch.setattr(messaging, "_post_whatsapp_message", post_aislado)
    asyncio.run(b._run_booking_reminders())
    asyncio.run(b._run_booking_reminders())
    assert llamadas == [1]
    fila = b._get_booking_row_by_id(entorno.booking_id)
    assert bool(fila["reminder_24h_sent_at"]) == (estado == "aceptado")
    with db._get_db_connection() as conn:
        registro = conn.execute(
            "SELECT state,provider_message_id FROM booking_notice_deliveries "
            "WHERE booking_id=? AND channel='whatsapp'", (entorno.booking_id,)).fetchone()
        auditorias = conn.execute(
            "SELECT COUNT(*) FROM booking_audit WHERE booking_id=? "
            "AND event_type='reminder_whatsapp_template_sent'", (entorno.booking_id,)).fetchone()[0]
    assert registro["state"] == estado
    assert registro["provider_message_id"] == ("wamid.sintetico" if estado == "aceptado" else "")
    assert auditorias == (1 if estado == "aceptado" else 0)
    if estado == "aceptado":
        assert b._wa_recordatorios_hoy("demo") == 1


def test_caida_tras_aceptacion_conserva_tope_y_plantilla_sin_reenvio(entorno, monkeypatch):
    from backend import db, messaging, notice_deliveries, wa_plantillas

    b = entorno.booking
    llamadas = []
    monkeypatch.setattr(b, "_wa_ventana_abierta", lambda *a: False)
    monkeypatch.setattr(wa_plantillas, "estado", lambda *a: {
        "status": wa_plantillas.APROBADA, "name": "recordatorio_version_real"})
    monkeypatch.setattr(messaging, "_whatsapp_access_token_for_client", lambda *a: "token-sintetico")

    async def post_aislado(*args, **kwargs):
        llamadas.append(kwargs["payload"]["template"]["name"])
        return messaging.WhatsAppSendResult("aceptado", provider_message_id="wamid.sintetico")

    monkeypatch.setattr(messaging, "_post_whatsapp_message", post_aislado)
    finalizar = notice_deliveries.finish_notice_delivery

    def interrumpir_despues_de_persistir(*args, **kwargs):
        resultado = finalizar(*args, **kwargs)
        if args[4] == "whatsapp":
            raise KeyboardInterrupt("caida despues del commit de aceptacion")
        return resultado

    monkeypatch.setattr(notice_deliveries, "finish_notice_delivery", interrumpir_despues_de_persistir)
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(b._run_booking_reminders())
    assert b._wa_recordatorios_hoy("demo") == 1
    monkeypatch.setattr(notice_deliveries, "finish_notice_delivery", finalizar)
    asyncio.run(b._run_booking_reminders())
    assert llamadas == [wa_plantillas.NOMBRE_RECORDATORIO]
    assert b._get_booking_row_by_id(entorno.booking_id)["reminder_24h_sent_at"]
    with db._get_db_connection() as conn:
        eventos = conn.execute(
            "SELECT payload_json FROM booking_audit WHERE booking_id=? "
            "AND event_type='reminder_whatsapp_template_sent'", (entorno.booking_id,)).fetchall()
    assert len(eventos) == 1
    assert json.loads(eventos[0]["payload_json"])["template"] == llamadas[0]
