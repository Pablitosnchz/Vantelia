"""Identidad y exclusión duraderas del aviso, separadas de la cita ya existente."""
import asyncio
import concurrent.futures
import importlib
import json
import threading

import test_recordatorio_omitido_y_fallido as avisos

entorno = avisos.entorno


def test_generacion_cambia_ida_vuelta_y_cancelacion_pero_no_por_tracking(entorno):
    b = entorno.booking
    original = b._get_booking_row_by_id(entorno.booking_id)
    generacion = original["reminder_generation"]
    b._update_booking_record(entorno.booking_id, customer_email_status="enviado",
                             reminder_24h_sent_at="2026-09-13T12:00:00Z")
    assert b._get_booking_row_by_id(entorno.booking_id)["reminder_generation"] == generacion
    nueva_hora = "11:30" if original["booking_time"] != "11:30" else "12:30"
    b._update_booking_record(entorno.booking_id, booking_time=nueva_hora)
    b._update_booking_record(entorno.booking_id, booking_time=original["booking_time"])
    assert b._get_booking_row_by_id(entorno.booking_id)["reminder_generation"] == generacion + 2
    b._update_booking_record(entorno.booking_id, status="cancelled")
    assert b._get_booking_row_by_id(entorno.booking_id)["reminder_generation"] == generacion + 3
    b._update_booking_record(entorno.booking_id, telefono=None)
    despues = b._get_booking_row_by_id(entorno.booking_id)["reminder_generation"]
    b._update_booking_record(entorno.booking_id, telefono=None)
    assert b._get_booking_row_by_id(entorno.booking_id)["reminder_generation"] == despues


def test_claim_dos_conexiones_y_actor_perdido_no_caduca(entorno):
    from backend import notice_deliveries

    fila = entorno.booking._get_booking_row_by_id(entorno.booking_id)
    argumentos = ("demo", entorno.booking_id, fila["reminder_generation"], "reminder_24h", "whatsapp")
    barrera = threading.Barrier(2)
    def reclamar():
        barrera.wait(timeout=3)
        return notice_deliveries.claim_notice_delivery(*argumentos)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(lambda _: reclamar(), range(2)))
    assert sorted(r["estado"] for r in resultados) == ["enviando", "reclamado"]
    importlib.reload(notice_deliveries)
    assert notice_deliveries.claim_notice_delivery(*argumentos)["estado"] == "enviando"
    # Una identidad de otro tenant nunca puede reclamar esta cita.
    assert notice_deliveries.claim_notice_delivery("ajeno", *argumentos[1:])["estado"] == "obsoleto"


def test_cancelacion_tras_claim_impide_la_salida(entorno, monkeypatch):
    from backend import notice_deliveries

    b = entorno.booking
    reclamar = notice_deliveries.claim_notice_delivery
    def cancelar_despues(*args, **kwargs):
        resultado = reclamar(*args, **kwargs)
        b._update_booking_record(entorno.booking_id, status="cancelled")
        return resultado
    monkeypatch.setattr(notice_deliveries, "claim_notice_delivery", cancelar_despues)
    enviados = []
    async def enviar(*a, **kwargs):
        enviados.append(1)
        return True
    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", enviar)
    asyncio.run(b._run_booking_reminders())
    assert enviados == []
    assert not b._get_booking_row_by_id(entorno.booking_id)["reminder_24h_sent_at"]


def test_reprogramacion_durante_io_no_sella_la_nueva_generacion(entorno, monkeypatch):
    b = entorno.booking
    original = b._get_booking_row_by_id(entorno.booking_id)
    async def enviar(*a, **kwargs):
        b._update_booking_record(entorno.booking_id, booking_time="12:30")
        b._update_booking_record(entorno.booking_id, booking_time=original["booking_time"])
        return True
    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", enviar)
    asyncio.run(b._run_booking_reminders())
    assert not b._get_booking_row_by_id(entorno.booking_id)["reminder_24h_sent_at"]


def test_claim_bloquea_respaldo_incierto_y_recupera_otro_canal_aceptado(entorno):
    from backend import notice_deliveries

    fila = entorno.booking._get_booking_row_by_id(entorno.booking_id)
    identidad = ("demo", entorno.booking_id, fila["reminder_generation"], "reminder_24h")
    wa = notice_deliveries.claim_notice_delivery(*identidad, "whatsapp", single_delivery=True)
    assert notice_deliveries.claim_notice_delivery(*identidad, "email", single_delivery=True)["estado"] == "enviando"
    notice_deliveries.finish_notice_delivery(*identidad, "whatsapp", wa["owner_token"], "desconocido")
    assert notice_deliveries.claim_notice_delivery(*identidad, "email", single_delivery=True)["estado"] == "desconocido"
    # Otra generación empieza sin reutilizar la identidad antigua.
    entorno.booking._update_booking_record(entorno.booking_id, booking_time="14:30")
    fila = entorno.booking._get_booking_row_by_id(entorno.booking_id)
    siguiente = ("demo", entorno.booking_id, fila["reminder_generation"], "reminder_24h")
    email = notice_deliveries.claim_notice_delivery(*siguiente, "email", single_delivery=True)
    notice_deliveries.finish_notice_delivery(*siguiente, "email", email["owner_token"], "aceptado", provider_message_id="id-sintetico")
    recuperada = notice_deliveries.claim_notice_delivery(*siguiente, "whatsapp", single_delivery=True)
    assert recuperada["estado"] == "aceptado" and recuperada["canal"] == "email"
    assert recuperada["provider_message_id"] == "id-sintetico"


def test_aceptacion_se_recupera_si_se_pierde_la_marca_global(entorno, monkeypatch):
    from backend import notice_deliveries, messaging

    b = entorno.booking
    enviados = []
    async def enviar(*args, **kwargs):
        enviados.append(1)
        return messaging.WhatsAppSendResult("aceptado", provider_message_id="wamid.sintetico")
    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", enviar)
    marcar = notice_deliveries.mark_notice_complete
    marcas = []
    def perder_primera_marca(*args, **kwargs):
        marcas.append(1)
        if len(marcas) == 1:
            raise OSError("fallo sintetico tras aceptacion")
        return marcar(*args, **kwargs)
    monkeypatch.setattr(notice_deliveries, "mark_notice_complete", perder_primera_marca)
    asyncio.run(b._run_booking_reminders())
    assert not b._get_booking_row_by_id(entorno.booking_id)["reminder_24h_sent_at"]
    asyncio.run(b._run_booking_reminders())
    assert enviados == [1]
    assert b._get_booking_row_by_id(entorno.booking_id)["reminder_24h_sent_at"]


def test_incierto_con_ids_parciales_no_repite_ni_cambia_de_canal(entorno, monkeypatch):
    from backend import db, messaging

    b = entorno.booking
    b._update_booking_record(entorno.booking_id, email="sintetica@example.invalid")
    configuracion = b._follow_up_config("demo")
    monkeypatch.setattr(b, "_follow_up_config", lambda *a: dict(configuracion, delivery_priority=["whatsapp", "email", "sms"]))
    enviados = []
    async def enviar(*args, **kwargs):
        enviados.append("whatsapp")
        return messaging.WhatsAppSendResult("desconocido", message_ids=("wamid.parcial",))
    def email(*args):
        enviados.append("email")
        return True
    monkeypatch.setattr(b, "_send_booking_whatsapp_reminder", enviar)
    monkeypatch.setattr(b, "_send_booking_email", email)
    asyncio.run(b._run_booking_reminders())
    asyncio.run(b._run_booking_reminders())
    assert enviados == ["whatsapp"]
    with db._get_db_connection() as conn:
        fila = conn.execute("SELECT state,provider_message_ids_json FROM booking_notice_deliveries WHERE booking_id=? AND channel='whatsapp'", (entorno.booking_id,)).fetchone()
    assert fila["state"] == "desconocido"
    assert json.loads(fila["provider_message_ids_json"]) == ["wamid.parcial"]
    assert not b._get_booking_row_by_id(entorno.booking_id)["reminder_24h_sent_at"]
