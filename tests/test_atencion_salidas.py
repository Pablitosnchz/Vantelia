"""Transportes reales con proveedores simulados: permiso, incertidumbre y no reenvío."""
import asyncio
from contextlib import closing
from email.message import EmailMessage
from urllib.parse import parse_qs

import httpx
import pytest

from test_atencion_persistida import autoridad_atencion  # noqa: F401
from test_atencion_operaciones import operaciones_atencion, _crear_ticket_prueba  # noqa: F401
from test_atencion_mutaciones import nucleo_atencion  # noqa: F401
from test_atencion_mutaciones import _invocacion_nucleo_prueba


def _pausar_salida_prueba(a):
    a.autoridad.cambiar_atencion("demo", "pausada", version_esperada=0, motivo="temporada", actor="sistema")


@pytest.fixture
def transporte_atencion(operaciones_atencion, monkeypatch):
    from backend import atencion_contexto, clients, emailing, messaging, security, settings

    a = operaciones_atencion
    a.ticket = _crear_ticket_prueba(a, tenant="demo")
    a.turno = lambda: atencion_contexto.turno_atencion("demo", a.ticket["ticket_id"], "intento_salida")
    a.config = dict(email_provider="client_smtp", email_fallback_enabled=1,
        email_smtp_host="smtp.invalid", email_smtp_port=587, email_smtp_username="",
        email_smtp_password_encrypted="", email_smtp_from_email="remitente@example.invalid",
        email_smtp_from_name="Negocio", email_smtp_reply_to="", email_smtp_starttls=0,
        sms_mode="vantelia_default")
    a.llamadas, a.fallback = [], []
    a.enviar_error = None
    a.cerrar_error = None
    a.despues = None
    class SMTP:
        def __init__(self, *args, **kwargs):
            a.llamadas.append(("conexion", args))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            if a.cerrar_error:
                raise a.cerrar_error
        def ehlo(self):
            pass
        def starttls(self):
            pass
        def login(self, *args):
            pass
        def send_message(self, message):
            a.llamadas.append(("send", message.as_bytes()))
            if a.enviar_error:
                raise a.enviar_error
            if a.despues:
                a.despues()
    monkeypatch.setattr(emailing.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(security, "_ensure_channel_settings", lambda *args: a.config)
    monkeypatch.setattr(security, "_channel_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(emailing, "_send_email_message", lambda *args, **kwargs: a.fallback.append(args))
    monkeypatch.setattr(clients, "_plan_feature", lambda *args: True)
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "account_prueba")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "token_falso_prueba")
    monkeypatch.setattr(settings, "TWILIO_SMS_SENDER", "+34911000000")
    monkeypatch.setattr(messaging, "_whatsapp_access_token_for_client", lambda *args: "token_falso_prueba")
    a.enviar_email = lambda texto="texto": emailing._send_client_email(
        "demo", "destino@example.invalid", "Asunto", texto, "<p>" + texto + "</p>")
    return a


def _cliente_http_simulado_salida(monkeypatch, accion, cerrar_error=None):
    from backend import messaging

    class ClienteHTTP:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            if cerrar_error:
                raise cerrar_error
        async def post(self, url, **kwargs):
            return accion(url, kwargs)
    monkeypatch.setattr(messaging.httpx, "AsyncClient", ClienteHTTP)


@pytest.mark.parametrize("canal", ["smtp", "sms", "whatsapp"])
def test_pausa_impide_conexion_y_fallback_de_transporte(transporte_atencion, monkeypatch, canal):
    from backend import atencion_contexto, messaging

    a = transporte_atencion
    _cliente_http_simulado_salida(monkeypatch, lambda *args: pytest.fail("No iniciar POST durante pausa"))
    _pausar_salida_prueba(a)
    with a.turno(), pytest.raises(atencion_contexto.AtencionDetenida):
        if canal == "smtp":
            a.enviar_email()
        elif canal == "sms":
            asyncio.run(messaging._send_client_sms("demo", "600 111 222", "Aviso"))
        else:
            asyncio.run(messaging._send_whatsapp_text(cliente_id="demo", phone_number_id="emisor",
                to_number="34600111222", text="Aviso"))
    assert a.llamadas == [] and a.fallback == []
    assert [r["estado"] for r in a.op.consultar_envios_atencion("demo")] == ["suprimido"]


@pytest.mark.parametrize("accion", ["cancelar", "mover"])
def test_reserva_ganadora_finaliza_politica_y_crm_antes_de_suprimir_aviso(nucleo_atencion, monkeypatch, accion):
    from backend import atencion_contexto, booking, crm

    a = nucleo_atencion
    ejecutar, fila, proveedor = _invocacion_nucleo_prueba(a, accion)
    ticket = _crear_ticket_prueba(a, tenant="demo")
    efectos = []
    original = getattr(booking, proveedor)
    async def proveedor_y_pausa(*args, **kwargs):
        efectos.append("proveedor")
        _pausar_salida_prueba(a)
        return await original(*args, **kwargs)
    monkeypatch.setattr(booking, proveedor, proveedor_y_pausa)
    monkeypatch.setattr(booking, "apply_cancellation_policy", lambda *args, **kwargs: efectos.append("politica"))
    monkeypatch.setattr(crm, "_crm_upsert_contact", lambda *args, **kwargs: efectos.append("crm"))
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "mutacion"), pytest.raises(atencion_contexto.AtencionDetenida) as corte:
        asyncio.run(ejecutar())
    assert efectos == (["proveedor", "politica", "crm"] if accion == "cancelar" else ["proveedor", "crm"])
    diario = a.op.consultar_operaciones_atencion("demo", tipo="reserva")[0]
    assert diario["estado"] == "aceptado" and diario["result_ref"] == fila["id"]
    assert corte.value.estado == "suprimido"  # Es el aviso, nunca una entrega aceptada.
    assert getattr(corte.value, "operacion_conocida", None) == {
        "tipo": "reserva", "estado": "aceptado", "result_ref": fila["id"]}
    actual = booking._get_booking_row_by_id(fila["id"])
    assert actual["status"] == ("cancelled" if accion == "cancelar" else "confirmed")
    assert not a.op.consultar_envios_atencion("demo")


def test_creacion_conserva_referencia_al_cortar_confirmacion(nucleo_atencion, monkeypatch):
    from backend import atencion_contexto, booking

    a = nucleo_atencion
    ticket = _crear_ticket_prueba(a, tenant="demo")
    original = booking._create_provider_booking
    async def crear_y_pausar(*args, **kwargs):
        resultado = await original(*args, **kwargs)
        _pausar_salida_prueba(a)
        return resultado
    monkeypatch.setattr(booking, "_create_provider_booking", crear_y_pausar)
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "crear"), pytest.raises(atencion_contexto.AtencionDetenida) as corte:
        asyncio.run(a.crear(email="destino@example.invalid", send_confirmation=True))
    diario = a.op.consultar_operaciones_atencion("demo", tipo="reserva")[0]
    assert diario["estado"] == "aceptado"
    assert corte.value.estado == "suprimido"
    assert corte.value.operacion_conocida == {
        "tipo": "reserva", "estado": "aceptado", "result_ref": diario["result_ref"]}
    assert booking._get_booking_row_by_id(diario["result_ref"])["status"] == "confirmed"


def test_smtp_timeout_no_hace_fallback_y_repetir_no_reabre(transporte_atencion):
    from backend import atencion_contexto

    a = transporte_atencion
    a.enviar_error = TimeoutError("respuesta perdida")
    with a.turno():
        for _ in range(2):
            with pytest.raises(atencion_contexto.AtencionDetenida) as exc:
                a.enviar_email()
            assert exc.value.estado == "desconocido"
        with pytest.raises(atencion_contexto.AtencionDetenida) as conflicto:
            a.enviar_email("distinto")
    assert conflicto.value.motivo == "identidad_en_conflicto"
    assert len(a.llamadas) == 2 and a.fallback == []
    assert a.op.consultar_envios_atencion("demo")[0]["estado"] == "desconocido"


@pytest.mark.parametrize("cambio", ["pausa", "cierre", "auditoria"])
def test_smtp_aceptado_no_se_borra_por_cierre_o_auxiliares(transporte_atencion, monkeypatch, cambio):
    from backend import atencion_contexto, security

    a = transporte_atencion
    if cambio == "pausa":
        a.despues = lambda: _pausar_salida_prueba(a)
    elif cambio == "cierre":
        a.cerrar_error = RuntimeError("fallo QUIT tras DATA aceptado")
    else:
        def fallar(*args, **kwargs):
            raise RuntimeError("auditoria caida")
        monkeypatch.setattr(security, "_channel_audit", fallar)
    with a.turno():
        if cambio == "cierre":
            with pytest.raises(atencion_contexto.AtencionDetenida) as exc:
                a.enviar_email()
            assert exc.value.estado == "aceptado"
        else:
            assert a.enviar_email() == "client_smtp"
    assert a.op.consultar_envios_atencion("demo")[0]["estado"] == "aceptado"
    assert a.fallback == [] and len(a.llamadas) == 2


@pytest.mark.parametrize("global_gmail", [False, True])
def test_gmail_pausado_no_refresca_oauth_antes_de_permiso(transporte_atencion, monkeypatch, global_gmail):
    from backend import atencion_contexto, emailing, security

    a = transporte_atencion
    _pausar_salida_prueba(a)
    def prohibido(*args, **kwargs):
        pytest.fail("No refrescar token ni emitir POST antes del permiso")
    monkeypatch.setattr(emailing, "_client_gmail_access_token", prohibido)
    monkeypatch.setattr(emailing, "_gmail_access_token", prohibido)
    monkeypatch.setattr(emailing.httpx, "post", prohibido)
    monkeypatch.setattr(emailing, "_gmail_connection", lambda *args: {"email": "remitente@example.invalid"})
    monkeypatch.setattr(security, "_gmail_oauth_configured", lambda: True)
    with a.turno(), pytest.raises(atencion_contexto.AtencionDetenida):
        if global_gmail:
            mensaje = EmailMessage()
            mensaje["From"], mensaje["To"] = "remitente@example.invalid", "destino@example.invalid"
            mensaje.set_content("Aviso")
            emailing._gmail_send_message(mensaje, "demo")
        else:
            emailing._send_gmail_message("demo", {"account_email": "remitente@example.invalid"},
                "destino@example.invalid", "Asunto", "Aviso")
    assert a.fallback == []


@pytest.mark.parametrize("global_gmail", [False, True])
def test_pausa_durante_refresh_no_autoriza_post_de_mensaje(transporte_atencion, monkeypatch, global_gmail):
    from backend import atencion_contexto, emailing, security

    a = transporte_atencion
    posts = []
    def post(url, **kwargs):
        posts.append(url)
        return httpx.Response(200, json={"id": "gmail_prueba"}, request=httpx.Request("POST", url))
    class ClienteGmail:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, **kwargs):
            return post(url, **kwargs)
    monkeypatch.setattr(emailing.httpx, "post", post)
    monkeypatch.setattr(emailing.httpx, "Client", ClienteGmail)
    monkeypatch.setattr(security, "_gmail_oauth_configured", lambda: True)
    monkeypatch.setattr(emailing, "_gmail_connection", lambda *args: {"email": "remitente@example.invalid"})
    def token_tras_pausa(*args):
        _pausar_salida_prueba(a)
        return ("token_prueba", {}) if global_gmail else "token_prueba"
    monkeypatch.setattr(emailing, "_gmail_access_token", token_tras_pausa)
    monkeypatch.setattr(emailing, "_client_gmail_access_token", token_tras_pausa)
    with a.turno(), pytest.raises(atencion_contexto.AtencionDetenida):
        if global_gmail:
            mensaje = EmailMessage()
            mensaje["From"], mensaje["To"] = "remitente@example.invalid", "destino@example.invalid"
            mensaje.set_content("Aviso")
            emailing._gmail_send_message(mensaje, "demo")
        else:
            emailing._send_gmail_message("demo", {"account_email": "remitente@example.invalid"},
                "destino@example.invalid", "Asunto", "Aviso")
    assert posts == []
    assert [r["estado"] for r in a.op.consultar_envios_atencion("demo")] == ["suprimido"]


def test_sms_normaliza_destinatario_y_deduplica_payload_efectivo(transporte_atencion, monkeypatch):
    from backend import atencion_contexto, messaging

    a = transporte_atencion
    posts = []
    def aceptar(url, kwargs):
        posts.append(kwargs["content"])
        return httpx.Response(201, json={"sid": "sms_prueba"}, request=httpx.Request("POST", url))
    _cliente_http_simulado_salida(monkeypatch, aceptar)
    with a.turno():
        assert asyncio.run(messaging._send_client_sms("demo", "600 111 222", "ñ" * 1500 + "A"))
        with pytest.raises(atencion_contexto.AtencionDetenida) as exc:
            asyncio.run(messaging._send_client_sms("demo", "+34600111222", "ñ" * 1500 + "B"))
    assert exc.value.estado == "aceptado" and exc.value.motivo != "identidad_en_conflicto"
    assert len(posts) == 1
    assert parse_qs(posts[0].decode()) == {"To": ["+34600111222"], "From": ["+34911000000"], "Body": ["ñ" * 1500]}


@pytest.mark.parametrize("respuesta", ["timeout", "5xx", "4xx", "cierre"])
def test_sms_incertidumbre_terminal_y_aceptacion_antes_del_cierre(transporte_atencion, monkeypatch, respuesta):
    from backend import atencion_contexto, messaging

    a = transporte_atencion
    posts = []
    def responder(url, kwargs):
        posts.append(1)
        if respuesta == "timeout":
            raise httpx.ReadTimeout("sin respuesta")
        return httpx.Response({"5xx": 503, "4xx": 400}.get(respuesta, 201),
            json={"sid": "sms_prueba"}, request=httpx.Request("POST", url))
    _cliente_http_simulado_salida(monkeypatch, responder,
        RuntimeError("cierre fallido") if respuesta == "cierre" else None)
    esperado = {"4xx": "rechazado", "cierre": "aceptado"}.get(respuesta, "desconocido")
    with a.turno():
        if respuesta == "4xx":
            assert asyncio.run(messaging._send_client_sms("demo", "600111222", "Aviso")) is False
        else:
            with pytest.raises(atencion_contexto.AtencionDetenida) as exc:
                asyncio.run(messaging._send_client_sms("demo", "600111222", "Aviso"))
            assert exc.value.estado == esperado
        with pytest.raises(atencion_contexto.AtencionDetenida):
            asyncio.run(messaging._send_client_sms("demo", "600111222", "Aviso"))
    assert posts == [1] and a.op.consultar_envios_atencion("demo")[0]["estado"] == esperado


def test_meta_fragmento_aceptado_pausa_detiene_el_siguiente(transporte_atencion, monkeypatch):
    from backend import atencion_contexto, messaging

    a = transporte_atencion
    posts = []
    monkeypatch.setattr(messaging, "_whatsapp_chunks", lambda texto: ["primero", "segundo"])
    def aceptar(url, kwargs):
        posts.append(kwargs["content"])
        _pausar_salida_prueba(a)
        return httpx.Response(200, json={"messages": [{"id": "wamid_prueba"}]}, request=httpx.Request("POST", url))
    _cliente_http_simulado_salida(monkeypatch, aceptar)
    with a.turno(), pytest.raises(atencion_contexto.AtencionDetenida):
        asyncio.run(messaging._send_whatsapp_text(cliente_id="demo", phone_number_id="emisor",
            to_number="34600111222", text="dos partes"))
    assert len(posts) == 1
    assert [(r["fragmento"], r["estado"]) for r in a.op.consultar_envios_atencion("demo")] == [
        (0, "aceptado"), (1, "suprimido")]


def test_tenant_ajeno_rechazado_y_manual_conserva_recorrido(transporte_atencion):
    from backend import atencion_contexto, emailing

    a = transporte_atencion
    with a.turno(), pytest.raises(atencion_contexto.AtencionDetenida) as exc:
        emailing._send_client_email("otro_tenant", "destino@example.invalid", "Asunto", "Aviso")
    assert exc.value.motivo == "tenant_incorrecto" and a.llamadas == []
    _pausar_salida_prueba(a)
    assert a.enviar_email() == "client_smtp"
    assert len(a.llamadas) == 2 and a.op.consultar_envios_atencion("demo") == []


def test_aviso_no_marca_entregado_ni_pasa_al_siguiente_al_suprimirse(nucleo_atencion, monkeypatch):
    from backend import agenda, atencion_contexto, booking

    a = nucleo_atencion
    fila = asyncio.run(a.crear(email="destino@example.invalid"))
    # La fixture devuelve una fila real del núcleo; no se simulan permisos.
    if not hasattr(fila, "keys"):
        fila = booking._get_booking_row_by_id(fila["id"])
    ticket = _crear_ticket_prueba(a, tenant="demo")
    monkeypatch.setattr(agenda, "_reminder_channel_availability", lambda *args: {
        "email": {"available": True}, "sms": {"available": True}})
    monkeypatch.setattr(booking, "_send_booking_email", lambda *args: (_ for _ in ()).throw(
        atencion_contexto.AtencionDetenida("pausada")))
    async def sms_prohibido(*args, **kwargs):
        pytest.fail("No probar SMS tras suprimir email")
    monkeypatch.setattr(booking, "_send_booking_sms_reminder", sms_prohibido)
    with atencion_contexto.turno_atencion("demo", ticket["ticket_id"], "aviso"), pytest.raises(atencion_contexto.AtencionDetenida):
        asyncio.run(booking._send_booking_reminder_by_kind(fila, "reminder_24h", None,
            channel_override={"email": True, "sms": True}, respect_enabled=False))
    with closing(a.db._get_db_connection()) as conn:
        assert conn.execute("SELECT count(*) FROM booking_audit WHERE event_type='booking_email_sent'").fetchone()[0] == 0


def test_pausa_tras_claim_aviso_es_omision_conocida_y_no_revive(
        nucleo_atencion, transporte_atencion, monkeypatch):
    from datetime import timedelta
    from backend import agenda, atencion_contexto, booking, notice_deliveries

    a = transporte_atencion
    fila = asyncio.run(nucleo_atencion.crear(email="destino@example.invalid"))
    monkeypatch.setattr(agenda, "_reminder_channel_availability", lambda *args: {
        "email": {"available": True}, "sms": {"available": True}})
    monkeypatch.setattr(booking, "_send_booking_email", lambda *args: a.enviar_email())
    async def sms_prohibido(*args, **kwargs):
        pytest.fail("Un aviso suprimido no pasa a otro canal")
    monkeypatch.setattr(booking, "_send_booking_sms_reminder", sms_prohibido)
    reclamar = notice_deliveries.claim_notice_delivery
    def reclamar_y_pausar(*args, **kwargs):
        resultado = reclamar(*args, **kwargs)
        _pausar_salida_prueba(a)
        return resultado
    monkeypatch.setattr(notice_deliveries, "claim_notice_delivery", reclamar_y_pausar)
    async def avisar():
        return await booking._send_booking_reminder_by_kind(fila, "reminder_24h", None,
            sent_column="reminder_24h_sent_at", channel_override={"email": True, "sms": True},
            respect_enabled=False)
    with a.turno(), pytest.raises(atencion_contexto.AtencionDetenida):
        asyncio.run(avisar())
    with closing(a.db._get_db_connection()) as conn:
        estado = conn.execute("SELECT state,reason FROM booking_notice_deliveries").fetchone()
        assert tuple(estado) == ("omitido", "atencion_suprimida")
        assert not conn.execute("SELECT reminder_24h_sent_at FROM bookings WHERE id=?", (fila["id"],)).fetchone()[0]
    assert a.llamadas == [] and a.fallback == []
    assert a.op.consultar_envios_atencion("demo")[0]["estado"] == "suprimido"
    monkeypatch.setattr(notice_deliveries, "claim_notice_delivery", reclamar)
    a.autoridad.cambiar_atencion("demo", "activa", version_esperada=1, motivo="temporada", actor="sistema")
    a.reloj["ahora"] += timedelta(microseconds=1)
    nuevo = _crear_ticket_prueba(a, evento="evento_nuevo", tenant="demo")
    with atencion_contexto.turno_atencion("demo", nuevo["ticket_id"], "aviso_nuevo"), pytest.raises(atencion_contexto.AtencionDetenida):
        asyncio.run(avisar())
    assert a.llamadas == [] and a.fallback == []


def test_aviso_parcial_conserva_ids_y_no_se_marca_omitido(
        nucleo_atencion, transporte_atencion, monkeypatch):
    from backend import agenda, atencion_contexto, booking, messaging

    a = transporte_atencion
    fila = asyncio.run(nucleo_atencion.crear())
    monkeypatch.setattr(agenda, "_reminder_channel_availability", lambda *args: {
        "whatsapp": {"available": True}, "sms": {"available": True}})
    monkeypatch.setattr(booking, "_whatsapp_deliverable_for_booking", lambda *args: (True, ""))
    monkeypatch.setattr(messaging, "_whatsapp_chunks", lambda texto: ["primero", "segundo"])
    posts = []
    def aceptar(url, kwargs):
        posts.append(kwargs["content"])
        _pausar_salida_prueba(a)
        return httpx.Response(200, json={"messages": [{"id": "wamid_parcial"}]}, request=httpx.Request("POST", url))
    _cliente_http_simulado_salida(monkeypatch, aceptar)
    async def enviar_meta(*args, **kwargs):
        return await messaging._send_whatsapp_text(cliente_id="demo", phone_number_id="emisor",
            to_number="34600111222", text="dos partes", detailed=True)
    async def sms_prohibido(*args, **kwargs):
        pytest.fail("No probar otro canal tras aceptación parcial")
    monkeypatch.setattr(booking, "_send_booking_whatsapp_reminder", enviar_meta)
    monkeypatch.setattr(booking, "_send_booking_sms_reminder", sms_prohibido)
    with a.turno(), pytest.raises(atencion_contexto.AtencionDetenida) as corte:
        asyncio.run(booking._send_booking_reminder_by_kind(fila, "reminder_24h", None,
            sent_column="reminder_24h_sent_at", channel_override={"whatsapp": True, "sms": True},
            respect_enabled=False))
    assert corte.value.estado == "desconocido" and len(posts) == 1
    with closing(a.db._get_db_connection()) as conn:
        aviso = conn.execute("SELECT state,reason,provider_message_ids_json FROM booking_notice_deliveries").fetchone()
        assert tuple(aviso) == ("desconocido", "aceptacion_parcial", '["wamid_parcial"]')
        assert not conn.execute("SELECT reminder_24h_sent_at FROM bookings WHERE id=?", (fila["id"],)).fetchone()[0]
