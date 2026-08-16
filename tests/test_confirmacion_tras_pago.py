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


def _canales(api_module, *, source, email, configurados=None):
    """Canales con los que se acabaria entregando un aviso a esta cita."""
    from backend import booking

    base = configurados or {"email": True, "whatsapp": False, "sms": False}
    cita = _CitaFalsa(id="bk_x", cliente_id="demo", source=source, email=email)
    return booking._channels_reaching_customer(cita, base)


def test_lo_que_el_negocio_configura_manda(api_module):
    """Con email en la ficha, se entrega por donde el negocio dijo."""
    canales = _canales(api_module, source="whatsapp", email="cliente@example.com")
    assert canales == {"email": True, "whatsapp": False, "sms": False}


def test_sin_email_se_usa_el_canal_por_el_que_escribio(api_module):
    """El agujero real: por WhatsApp el email es opcional y los canales por
    defecto son solo email, asi que no llegaba NADA."""
    canales = _canales(api_module, source="whatsapp", email="")
    assert canales["whatsapp"] is True
    # El email se deja marcado a proposito: asi el panel sigue explicando por que
    # no se pudo entregar por ahi ("La cita no tiene email") en vez de callarselo.
    assert canales["email"] is True


def test_una_reserva_por_telefono_cae_a_sms(api_module):
    canales = _canales(api_module, source="voice", email="")
    assert canales["sms"] is True


def test_una_reserva_web_sin_email_no_inventa_canal(api_module):
    """Por la web no hay canal de vuelta: no se enciende SMS por su cuenta."""
    canales = _canales(api_module, source="widget", email="")
    assert canales == {"email": True, "whatsapp": False, "sms": False}


def test_no_se_pisa_un_canal_ya_elegido(api_module):
    """Si el negocio ya manda por WhatsApp, la regla no toca nada."""
    canales = _canales(api_module, source="whatsapp", email="",
                       configurados={"email": False, "whatsapp": True, "sms": False})
    assert canales == {"email": False, "whatsapp": True, "sms": False}


def test_la_regla_se_aplica_a_TODOS_los_avisos(api_module):
    """Recordatorio, cancelacion y reprogramacion pasan por el mismo sitio."""
    import inspect

    from backend import booking

    fuente = inspect.getsource(booking._send_booking_reminder_by_kind)
    assert "_channels_reaching_customer(booking_row, channels)" in fuente


def test_confirmar_tras_pagar_no_tiene_logica_propia(api_module):
    """Una sola regla de entrega: si hay dos, se desincronizan."""
    import inspect

    from backend import booking

    fuente = inspect.getsource(booking.notify_booking_paid)
    assert "channel_override" not in fuente


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


# ── Poder escribirle por WhatsApp no es lo mismo que "el tenant tiene WhatsApp" ──

def _cita_wa(api_module, telefono="+34600111222"):
    return _CitaFalsa(id="bk_wa", cliente_id="demo", source="whatsapp", telefono=telefono, email="")


def test_un_negocio_sin_plan_no_puede_escribir_por_whatsapp(api_module, monkeypatch):
    from backend import booking, clients

    monkeypatch.setattr(clients, "_plan_feature", lambda cid, f: False)
    ok, motivo = booking._whatsapp_deliverable_for_booking(_cita_wa(api_module))
    assert ok is False and "plan" in motivo.lower()


def test_sin_token_tampoco(api_module, monkeypatch):
    from backend import booking, clients, messaging

    monkeypatch.setattr(clients, "_plan_feature", lambda cid, f: True)
    monkeypatch.setattr(messaging, "_whatsapp_access_token_for_client", lambda cid: "")
    ok, motivo = booking._whatsapp_deliverable_for_booking(_cita_wa(api_module))
    assert ok is False and "token" in motivo.lower()


def test_con_numero_propio_configurado_si(api_module, monkeypatch):
    from backend import booking, clients, messaging

    monkeypatch.setattr(clients, "_plan_feature", lambda cid, f: True)
    monkeypatch.setattr(messaging, "_whatsapp_access_token_for_client", lambda cid: "tok")
    monkeypatch.setattr(clients, "_get_client_config",
                        lambda cid: {"whatsapp": {"enabled": True, "phone_number_id": "123"}})
    ok, _ = booking._whatsapp_deliverable_for_booking(_cita_wa(api_module))
    assert ok is True


def test_por_el_numero_de_demo_compartido_tambien(api_module, monkeypatch):
    """Un negocio puede estar atendiendo por el numero de demo sin tener el suyo:
    la conversacion existe y hay que poder contestarla."""
    from backend import booking, clients, inbox, messaging, wa_demo

    monkeypatch.setattr(clients, "_plan_feature", lambda cid, f: True)
    monkeypatch.setattr(messaging, "_whatsapp_access_token_for_client", lambda cid: "tok")
    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {"whatsapp": {}})
    monkeypatch.setattr(inbox, "inbound_number_for_phone", lambda cid, tel: "hub_123")
    monkeypatch.setattr(wa_demo, "is_hub", lambda pid: pid == "hub_123")
    ok, _ = booking._whatsapp_deliverable_for_booking(_cita_wa(api_module))
    assert ok is True


def test_si_el_negocio_apago_su_whatsapp_se_respeta(api_module, monkeypatch):
    from backend import booking, clients, inbox, messaging, wa_demo

    monkeypatch.setattr(clients, "_plan_feature", lambda cid, f: True)
    monkeypatch.setattr(messaging, "_whatsapp_access_token_for_client", lambda cid: "tok")
    monkeypatch.setattr(clients, "_get_client_config",
                        lambda cid: {"whatsapp": {"enabled": False, "phone_number_id": "123"}})
    monkeypatch.setattr(inbox, "inbound_number_for_phone", lambda cid, tel: "otro_numero")
    monkeypatch.setattr(wa_demo, "is_hub", lambda pid: False)
    ok, _ = booking._whatsapp_deliverable_for_booking(_cita_wa(api_module))
    assert ok is False
