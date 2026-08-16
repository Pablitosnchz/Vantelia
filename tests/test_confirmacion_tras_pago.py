"""Quien paga la senal recibe la confirmacion POR DONDE reservo.

Agujero real (ago 2026): tras cobrar, la confirmacion salia solo por email. Pero
en el flujo corto de WhatsApp el email es OPCIONAL, asi que el caso normal era:
el cliente reserva por WhatsApp sin email, paga la senal con Bizum, y no recibe
absolutamente nada. Pagaba y se quedaba sin saber si su cita existia.
"""
from __future__ import annotations

import asyncio
import uuid

from test_booking_exhaustive import api_module  # noqa: F401


class _CitaFalsa(dict):
    """Fila de cita con lo justo para decidir el canal."""

    def __getitem__(self, clave):
        return self.get(clave, "")

    def keys(self):  # noqa: D102 - lo usan los helpers de booking
        return list(super().keys())


def _canales_usados(api_module, monkeypatch, *, source, email):
    from backend import booking

    capturado = {}

    async def falso(booking_row, kind, request=None, **kwargs):
        capturado["kind"] = kind
        capturado["canales"] = kwargs.get("channel_override")
        return {"sent": [], "failed": {}, "skipped": {}}

    monkeypatch.setattr(booking, "_send_booking_reminder_by_kind", falso)
    cita = _CitaFalsa(id="bk_" + uuid.uuid4().hex[:6], cliente_id="demo", source=source, email=email)
    asyncio.run(booking.notify_booking_paid(cita))
    return capturado


def test_una_reserva_de_whatsapp_se_confirma_por_whatsapp(api_module, monkeypatch):
    capturado = _canales_usados(api_module, monkeypatch, source="whatsapp", email="")
    assert capturado["kind"] == "confirmed"
    assert capturado["canales"]["whatsapp"] is True
    assert capturado["canales"]["email"] is False


def test_con_email_ademas_de_whatsapp_van_los_dos(api_module, monkeypatch):
    capturado = _canales_usados(api_module, monkeypatch, source="whatsapp", email="cliente@example.com")
    assert capturado["canales"]["whatsapp"] is True
    assert capturado["canales"]["email"] is True


def test_una_reserva_por_telefono_se_confirma_por_sms(api_module, monkeypatch):
    """La voz no tiene canal de vuelta: SMS, igual que el enlace de pago."""
    capturado = _canales_usados(api_module, monkeypatch, source="voice", email="")
    assert capturado["canales"]["sms"] is True
    assert capturado["canales"]["whatsapp"] is False


def test_una_reserva_web_sigue_yendo_por_email(api_module, monkeypatch):
    capturado = _canales_usados(api_module, monkeypatch, source="widget", email="web@example.com")
    assert capturado["canales"]["email"] is True
    assert capturado["canales"]["whatsapp"] is False
    assert capturado["canales"]["sms"] is False


def test_sin_ningun_canal_claro_se_intenta_el_email(api_module, monkeypatch):
    capturado = _canales_usados(api_module, monkeypatch, source="", email="")
    assert capturado["canales"]["email"] is True


def test_un_fallo_de_envio_no_rompe_el_cobro(api_module, monkeypatch):
    """El dinero ya esta cobrado: aqui no se puede lanzar."""
    from backend import booking

    async def revienta(*_args, **_kwargs):
        raise RuntimeError("WhatsApp caido")

    monkeypatch.setattr(booking, "_send_booking_reminder_by_kind", revienta)
    cita = _CitaFalsa(id="bk_falla", cliente_id="demo", source="whatsapp", email="")
    asyncio.run(booking.notify_booking_paid(cita))  # no debe lanzar


def test_el_webhook_de_pago_avisa(api_module):
    import inspect

    from backend import booking

    fuente = inspect.getsource(booking.process_booking_payment_webhook)
    assert "notify_booking_paid" in fuente


def test_se_responde_desde_el_numero_al_que_escribio(api_module):
    """Un negocio puede tener varios numeros (por centro, o el de demo compartido):
    contestar desde otro es escribirle desde un numero que no reconoce."""
    import inspect

    from backend import booking

    fuente = inspect.getsource(booking._send_booking_whatsapp_reminder)
    assert "inbox.inbound_number_for_phone" in fuente


def test_el_numero_de_entrada_se_busca_por_telefono(api_module):
    from backend import db, inbox, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO chat_sessions
                (id, cliente_id, origin, user_agent, started_at, last_message_at, message_count, wa_phone_number_id)
            VALUES ('ses_wa_test', 'demo', 'whatsapp:34600111222', '', ?, ?, 1, '1003598042848216')
            """,
            (ahora, ahora),
        )
        connection.commit()

    assert inbox.inbound_number_for_phone("demo", "+34600111222") == "1003598042848216"
    assert inbox.inbound_number_for_phone("demo", "600111222") == "1003598042848216"
    # Otro tenant no hereda el numero de este.
    assert inbox.inbound_number_for_phone("otro", "+34600111222") == ""
    assert inbox.inbound_number_for_phone("demo", "") == ""
