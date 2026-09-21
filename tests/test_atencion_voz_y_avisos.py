# -*- coding: utf-8 -*-
"""Voz y avisos automáticos con la atención pausada (fase 3).

POR QUE EXISTE
--------------
La fase 1 dejó una autoridad de atención que nadie consultaba y la fase 2 cerró
la entrada de WhatsApp. Quedaban sueltos los dos caminos que hablan SOLOS con el
cliente final: la voz (teléfono y widget) y el worker que manda recordatorios,
reseñas y llamadas de confirmación cada pocos minutos. Un negocio de temporada
que cierra en noviembre no puede tener a la IA cogiendo el teléfono ni mandando
recordatorios de citas mientras está cerrado.

DONDE ESTA LA RAYA
------------------
La IA no sostiene conversaciones mientras la atención esté pausada, la arranque
quien la arranque: por eso la llamada de confirmación se frena también cuando la
pide el botón del panel. Lo que el equipo escribe o manda a mano sigue saliendo,
y lo que solo deja constancia de algo que ya pasó (el status callback de Twilio,
la transcripción al colgar) no se toca.

Y una supresión no marca nada: la cita no queda con el recordatorio "enviado",
así que al reactivar el aviso sale si todavía toca.
"""
from __future__ import annotations

import asyncio
import copy
import json
from datetime import timedelta
import uuid

import pytest

from conftest import DEFAULT_DEMO_CONFIG


DOS_NEGOCIOS = copy.deepcopy(DEFAULT_DEMO_CONFIG)
DOS_NEGOCIOS["vecino"] = copy.deepcopy(DEFAULT_DEMO_CONFIG["demo"])
DOS_NEGOCIOS["vecino"]["nombre"] = "Negocio de al lado"


@pytest.fixture
def entorno(vantelia_env_factory, monkeypatch):
    api = vantelia_env_factory(copy.deepcopy(DOS_NEGOCIOS))
    from backend import wa_plantillas

    async def sin_refresco(*a):
        pass

    monkeypatch.setattr(wa_plantillas, "refrescar_pendientes", sin_refresco)
    yield api
    for cliente_id in ("demo", "vecino"):
        _reactivar(cliente_id)


def _pausar(cliente_id):
    from backend import atencion

    estado = atencion.leer_atencion(cliente_id)
    return atencion.cambiar_atencion(cliente_id, "pausada", version_esperada=estado["version"],
                                     motivo="cierre_temporada", actor="sistema")


def _reactivar(cliente_id):
    from backend import atencion, db

    try:
        estado = atencion.leer_atencion(cliente_id)
        if estado["estado"] == "pausada":
            atencion.cambiar_atencion(cliente_id, "activa", version_esperada=estado["version"],
                                      motivo="reapertura", actor="sistema")
        return
    except Exception:  # noqa: BLE001
        pass
    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM client_attention_state WHERE cliente_id = ?", (cliente_id,))
        conexion.commit()


# ─── Teléfono ──────────────────────────────────────────────────────────────

def _peticion_twilio(params):
    from starlette.requests import Request
    from urllib.parse import urlencode

    cuerpo = urlencode(params).encode("utf-8")

    async def recibir():
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/voice/demo",
                    "query_string": b"", "server": ("app.test.local", 443), "scheme": "https",
                    "client": ("testclient", 50000),
                    "headers": [(b"content-type", b"application/x-www-form-urlencoded"),
                                (b"host", b"app.test.local")]}, recibir)


@pytest.fixture
def telefono_listo(entorno, monkeypatch):
    """Twilio configurado y firma válida: lo único en discusión es la atención."""
    from backend import messaging, voice
    from backend.routers import voice_web

    monkeypatch.setattr(messaging, "_voice_twilio_configured", lambda: True)
    monkeypatch.setattr(messaging, "_twilio_request_valid", lambda *a, **k: True)
    monkeypatch.setattr(voice, "_get_voice_config", lambda cid: {"enabled": True})
    registradas = []
    monkeypatch.setattr(voice, "_voice_call_register",
                        lambda *a, **k: registradas.append(a))
    return voice_web, registradas


def test_el_telefono_no_lo_coge_la_ia_con_la_atencion_pausada(telefono_listo):
    voice_web, registradas = telefono_listo
    params = {"CallSid": "CA" + uuid.uuid4().hex, "From": "+34600111222", "To": "+34910000000"}

    activa = asyncio.run(voice_web.voice_incoming_call("demo", _peticion_twilio(params)))
    assert b"<Connect>" in activa.body, "sin pausa la llamada se conecta como siempre"

    _pausar("demo")
    pausada = asyncio.run(voice_web.voice_incoming_call("demo", _peticion_twilio(params)))
    assert b"<Connect>" not in pausada.body, "se ha conectado el puente con la atención pausada"
    assert b"<Hangup/>" in pausada.body, pausada.body
    assert len(registradas) == 1, "se ha registrado una llamada que no se atiende"


class _WebSocketFalso:
    def __init__(self):
        self.cerrado = None
        self.aceptado = False
        self.query_params = {}

    async def close(self, code=1000):
        self.cerrado = code

    async def accept(self):
        self.aceptado = True


def test_el_puente_se_revalida_al_conectar(entorno, monkeypatch):
    """La pausa puede caer entre el TwiML y el WebSocket. Lo que se paga es abrir
    la sesión con OpenAI, así que se pregunta otra vez antes de eso."""
    from backend import settings, voice
    from backend.routers import voice_web

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-de-prueba")
    monkeypatch.setattr(voice, "_get_voice_config", lambda cid: {"enabled": True})
    abiertas = []

    async def _abrir(*a, **k):
        abiertas.append(a)
        raise RuntimeError("no se debe abrir Realtime en esta prueba")

    monkeypatch.setattr(voice, "_open_realtime_ws", _abrir)

    _pausar("demo")
    ws = _WebSocketFalso()
    asyncio.run(voice_web.voice_media_stream(ws, "demo"))
    assert ws.cerrado == 1008, "el puente ha seguido adelante con la atención pausada"
    assert ws.aceptado is False
    assert abiertas == [], "se ha abierto (y facturado) una sesión de Realtime"


# ─── Voz del widget ────────────────────────────────────────────────────────

def test_la_voz_del_widget_no_acuna_sesion_ni_ejecuta_tools_en_pausa(entorno, monkeypatch):
    from starlette.testclient import TestClient

    from backend import settings, voice

    client = TestClient(entorno.app)

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-de-prueba")
    monkeypatch.setattr(voice, "_voice_widget_enabled", lambda *a, **k: True)
    acunadas, ejecutadas = [], []

    async def _acunar(*a, **k):
        acunadas.append(a)
        return {"client_secret": "ef_prueba"}

    async def _tool(*a, **k):
        ejecutadas.append(a)
        return {"ok": True}

    monkeypatch.setattr(voice, "_mint_voice_session", _acunar)
    monkeypatch.setattr(voice, "_voice_dispatch_tool", _tool)

    desde_la_web = {"Origin": "http://testserver"}
    assert client.post("/voice/widget/demo/session", headers=desde_la_web).status_code == 200
    _pausar("demo")
    assert client.post("/voice/widget/demo/session", headers=desde_la_web).status_code == 409
    assert client.post("/voice/widget/demo/tool", headers=desde_la_web,
                       json={"name": "crear_cita", "arguments": "{}"}).status_code == 409
    assert len(acunadas) == 1, "se ha acuñado una sesión de voz con la atención pausada"
    assert ejecutadas == [], "se ha ejecutado una tool real con la atención pausada"


# ─── Llamadas salientes ────────────────────────────────────────────────────

def test_la_llamada_de_confirmacion_no_sale_ni_pidiendola_el_panel(entorno, monkeypatch):
    """Una llamada es una conversación que sostiene la IA: no hay excepción humana.
    El panel recibe el motivo para poder explicarlo."""
    from backend import atencion_voz, voice

    llamadas = []
    monkeypatch.setattr(voice, "_client_voice_plan_enabled", lambda cid: llamadas.append(cid) or True)

    _pausar("demo")
    resultado = voice._voice_place_outbound_call("demo", None, purpose="confirm")
    assert resultado["ok"] is False
    assert resultado["error"] == atencion_voz.MOTIVO_PARA_EL_PANEL
    assert llamadas == [], "se ha seguido evaluando (y llamando) con la atención pausada"


# ─── Avisos automáticos ────────────────────────────────────────────────────

def _cita_para_recordatorio(cliente_id, horas=24, minutos=20):
    from backend import db, timeutils

    inicio = timeutils._utc_now() + timedelta(hours=horas, minutes=minutos)
    booking_id = "bk_" + uuid.uuid4().hex
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO bookings (id, cliente_id, nombre, email, telefono, servicio,"
            "booking_date, booking_time, status, provider_status, source, manage_token,"
            "booking_code, created_at, start_at, end_at, timezone) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (booking_id, cliente_id, "Clienta Sintetica", "clienta@example.com", "600111222",
             "Consulta", inicio.date().isoformat(), inicio.strftime("%H:%M"), "confirmed",
             "internal", "test", "tok_" + uuid.uuid4().hex, "R-" + uuid.uuid4().hex[:6].upper(),
             timeutils._utc_now_iso(), inicio.isoformat(),
             (inicio + timedelta(minutes=30)).isoformat(), "Europe/Madrid"),
        )
        conexion.commit()
    return booking_id


@pytest.fixture
def avisos_listos(entorno, monkeypatch):
    """Canal email activo y transporte interceptado: solo se mide quién sale."""
    from backend import agenda, booking

    monkeypatch.setattr(booking, "_booking_email_enabled", lambda *a: True)
    monkeypatch.setattr(agenda, "_effective_followup_channels", lambda *a: {
        "reminder_24h": {"email": True, "whatsapp": False, "sms": False},
        "reminder_2h": {"email": True, "whatsapp": False, "sms": False},
    })
    enviados = []

    def _enviar(booking_row, kind, *a, **k):
        enviados.append((booking_row["cliente_id"], booking_row["id"], kind))
        return True

    monkeypatch.setattr(booking, "_send_booking_email", _enviar)
    return enviados


def test_el_recordatorio_no_sale_en_pausa_y_no_queda_marcado(avisos_listos):
    """Marcarlo sería peor que no mandarlo: la cita se quedaría sin recordatorio
    para siempre, también después de reactivar.

    Y que salga al reactivar, aunque su ventana se abriera durante la pausa, es
    una decisión de Pablo del 21-sep (PAUSA_TEMPORADA_DISENO.md): la cita sigue en
    pie y el negocio vuelve a estar abierto. Si esta prueba molesta, no se
    «arregla» usando el origen del aviso sin volver a preguntárselo."""
    from backend import booking

    enviados = avisos_listos
    booking_id = _cita_para_recordatorio("demo")

    _pausar("demo")
    asyncio.run(booking._run_booking_reminders())
    assert enviados == [], "ha salido un recordatorio con la atención pausada"
    assert not booking._get_booking_row_by_id(booking_id)["reminder_24h_sent_at"], (
        "la cita ha quedado marcada como avisada sin haber avisado")

    _reactivar("demo")
    asyncio.run(booking._run_booking_reminders())
    assert [b for _, b, _ in enviados] == [booking_id], (
        "al reactivar, el recordatorio pendiente tiene que salir")
    assert booking._get_booking_row_by_id(booking_id)["reminder_24h_sent_at"]


def test_la_pausa_de_un_negocio_no_calla_los_avisos_del_otro(avisos_listos):
    from backend import booking

    enviados = avisos_listos
    mio = _cita_para_recordatorio("demo")
    suyo = _cita_para_recordatorio("vecino")

    _pausar("demo")
    asyncio.run(booking._run_booking_reminders())
    assert [b for _, b, _ in enviados] == [suyo], (
        "la pausa de un negocio ha alcanzado los avisos del de al lado: %r" % enviados)
    assert not booking._get_booking_row_by_id(mio)["reminder_24h_sent_at"]


def test_una_pausa_a_mitad_de_tanda_frena_lo_que_aun_no_ha_salido(avisos_listos):
    """Por eso se pregunta por aviso y no una vez por pasada: entre el primero y
    el último hay red de por medio."""
    from backend import booking

    enviados = avisos_listos
    primera = _cita_para_recordatorio("demo", minutos=10)
    segunda = _cita_para_recordatorio("demo", minutos=20)
    original = booking._send_booking_email

    def _enviar_y_pausar(booking_row, kind, *a, **k):
        resultado = original(booking_row, kind, *a, **k)
        _pausar("demo")
        return resultado

    booking._send_booking_email = _enviar_y_pausar
    try:
        asyncio.run(booking._run_booking_reminders())
    finally:
        booking._send_booking_email = original

    salidas = [b for _, b, _ in enviados]
    assert len(salidas) == 1, "la pausa no ha frenado el resto de la tanda: %r" % salidas
    pendiente = segunda if salidas == [primera] else primera
    assert not booking._get_booking_row_by_id(pendiente)["reminder_24h_sent_at"]


def test_la_peticion_de_resena_no_sale_en_pausa(entorno, monkeypatch):
    from backend import booking, db, timeutils

    cfg = {"enabled": True, "link": "https://g.page/r/prueba/review", "platform": "google",
           "delay_hours": 2, "only_manual_attendance": False, "message": "",
           "channels": {"email": True, "whatsapp": False, "sms": False}}
    monkeypatch.setattr(booking, "_reviews_config", lambda cid: dict(cfg))
    pedidas = []

    async def _pedir(row, request=None, cfg=None):
        pedidas.append(row["id"])
        return {"sent_channels": ["email"]}

    monkeypatch.setattr(booking, "_send_review_request", _pedir)
    fin = timeutils._utc_now() - timedelta(hours=4)
    booking_id = "bk_" + uuid.uuid4().hex
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO bookings (id, cliente_id, nombre, email, telefono, servicio,"
            "booking_date, booking_time, status, provider_status, source, manage_token,"
            "booking_code, created_at, start_at, end_at, timezone, completed_source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (booking_id, "demo", "Clienta Sintetica", "clienta@example.com", "600111222",
             "Consulta", fin.date().isoformat(), fin.strftime("%H:%M"), "completed", "internal",
             "test", "tok_" + uuid.uuid4().hex, "R-RESENA", timeutils._utc_now_iso(),
             (fin - timedelta(minutes=30)).isoformat(), fin.isoformat(), "Europe/Madrid", "manual"),
        )
        conexion.commit()

    _pausar("demo")
    asyncio.run(booking._run_review_requests())
    assert pedidas == [], "se ha pedido una reseña con la atención pausada"

    _reactivar("demo")
    asyncio.run(booking._run_review_requests())
    assert pedidas == [booking_id], "al reactivar, la reseña pendiente tiene que salir"


# ─── Los otros dos automatismos del mismo worker ───────────────────────────

def test_el_rebooking_por_ia_no_escribe_a_nadie_en_pausa(entorno, monkeypatch):
    """Escribir a quien no espera nada es lo primero que sobra con el negocio
    cerrado: el rebooking manda WhatsApp a clientes inactivos por su cuenta."""
    from backend import booking, messaging

    monkeypatch.setattr(booking, "_ai_rebooking_enabled_for_client", lambda cid: True)
    monkeypatch.setattr(booking, "_ai_rebooking_candidates",
                        lambda cid: [{"phone": "600111222", "servicio": "Corte"}])
    monkeypatch.setattr(booking, "_log_ai_rebooking", lambda *a, **k: None)
    escritos = []

    async def _mandar(*, cliente_id, **kwargs):
        escritos.append(cliente_id)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", _mandar)

    _pausar("demo")
    asyncio.run(booking._run_ai_rebooking_pass())
    assert "demo" not in escritos, "el rebooking ha escrito con la atención pausada"
    assert "vecino" in escritos, "la pausa de un negocio ha frenado el rebooking del otro"


def test_los_avisos_de_caducidad_no_salen_en_pausa_y_no_sellan(entorno, monkeypatch):
    """Caducidad de un bono, caducidad de tarjeta y recompra comparten el mismo
    permiso; se comprueba el camino entero con uno y el permiso con los tres."""
    from backend import commerce, db, timeutils

    ahora = timeutils._utc_now()
    compra_id = "pp_" + uuid.uuid4().hex
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO package_purchases (id, cliente_id, package_id, package_name,"
            "buyer_name, buyer_email, buyer_phone, price_cents, remaining_json, expires_at,"
            "status, payment_method, location_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (compra_id, "demo", "pk_1", "Bono de 5", "Clienta", "clienta@example.com", "",
             5000, '{"corte": 2}', (ahora + timedelta(days=3)).isoformat(), "active", "cash",
             "", (ahora - timedelta(days=40)).isoformat(), (ahora - timedelta(days=40)).isoformat()),
        )
        conexion.commit()
    mandados = []
    monkeypatch.setattr(commerce, "_send_package_expiry_email",
                        lambda cid, row: mandados.append(row["id"]) or True)

    _pausar("demo")
    assert commerce._lifecycle_notices_ok_now("demo") is False
    assert commerce._lifecycle_notices_ok_now("vecino") is True
    commerce._run_commerce_lifecycle_notices()
    assert mandados == [], "ha salido un aviso de caducidad con la atención pausada"

    _reactivar("demo")
    commerce._run_commerce_lifecycle_notices()
    assert mandados == [compra_id], "al reactivar, el aviso pendiente tiene que salir"
    with db._get_db_connection() as conexion:
        sellado = conexion.execute(
            "SELECT expiry_notice_sent_at FROM package_purchases WHERE id = ?",
            (compra_id,)).fetchone()[0]
    assert sellado, "el aviso que sí salió tiene que quedar sellado"


# ─── Una llamada que ya estaba en curso cuando se pulso la pausa ───────────
#
# El puente solo miraba la pausa al CONECTAR, y las herramientas de la llamada
# no la consultaban: una llamada en curso seguia pudiendo crear, cancelar o
# mover citas. El motor se construye aqui dentro, con los modulos de ESTE
# entorno; el arnes de test_voice_engine apunta a los de otro runtime.

def _motor_de_llamada(monkeypatch, resultado=None, antes=None):
    from backend import voice, voice_engine

    emitidos, llamadas = [], []

    async def _a_openai(evento):
        emitidos.append(evento)

    async def _nada(*args, **kwargs):
        return True

    async def _despacho(cliente_id, nombre, argumentos, *, from_number="", location_id=""):
        llamadas.append(nombre)
        if antes:
            antes()
        return dict(resultado or {"ok": True, "mensaje_voz": "Hecho."})

    monkeypatch.setattr(voice, "_voice_dispatch_tool", _despacho)
    motor = voice_engine.VoiceCallEngine("demo", {}, {})
    motor.bind_transport(send_openai=_a_openai, send_twilio=_nada,
                         clear_playback=_nada, truncate_interrupted=_nada)
    return motor, emitidos, llamadas


def _herramienta(motor, nombre, argumentos=None):
    asyncio.run(motor.on_openai_event({
        "type": "response.function_call_arguments.done", "call_id": "c_" + uuid.uuid4().hex[:6],
        "name": nombre, "arguments": json.dumps(argumentos or {})}))


def _salidas(emitidos):
    return [json.loads(e["item"]["output"]) for e in emitidos
            if e.get("type") == "conversation.item.create"
            and (e.get("item") or {}).get("type") == "function_call_output"]


def test_una_llamada_en_curso_no_toca_la_agenda_tras_la_pausa(entorno, monkeypatch):
    motor, emitidos, llamadas = _motor_de_llamada(monkeypatch)
    _pausar("demo")
    _herramienta(motor, "cancelar_cita", {"codigo_reserva": "R-1234", "telefono": "600111222"})

    assert llamadas == [], "una llamada en curso ha tocado la agenda con la atencion pausada"
    salida = _salidas(emitidos)[-1]
    assert salida["atencion_pausada"] is True and salida["ok"] is False, salida
    assert motor.state["should_end_call"] is True, (
        "la llamada sigue abierta: la IA seguiria hablando en nombre del negocio")


def test_colgar_y_pasar_con_una_persona_siguen_funcionando(entorno, monkeypatch):
    """Sin estas dos, la IA ni siquiera podria despedirse ni pasar la llamada."""
    motor, emitidos, _ = _motor_de_llamada(monkeypatch)
    _pausar("demo")
    _herramienta(motor, "finalizar_llamada")
    salida = _salidas(emitidos)[-1]
    assert salida["ok"] is True and "atencion_pausada" not in salida, salida


def test_con_la_atencion_activa_la_llamada_reserva_como_siempre(entorno, monkeypatch):
    motor, emitidos, llamadas = _motor_de_llamada(monkeypatch)
    _herramienta(motor, "cancelar_cita", {"codigo_reserva": "R-1234"})
    assert llamadas == ["cancelar_cita"]
    assert motor.state["should_end_call"] is False


def test_la_pausa_que_cae_durante_la_herramienta_la_frena_el_nucleo(entorno, monkeypatch):
    """Una foto previa no basta: la pausa puede caer entre la comprobacion y la
    reserva. Con el turno puesto, el nucleo lo vuelve a comprobar al mutar
    (`verificar_turno_atencion`, lo que llaman crear/cancelar/mover)."""
    from backend import atencion_contexto

    def _pausa_y_muta():
        _pausar("demo")
        atencion_contexto.verificar_turno_atencion("demo")

    motor, emitidos, llamadas = _motor_de_llamada(monkeypatch, antes=_pausa_y_muta)
    _herramienta(motor, "reprogramar_cita", {"codigo_reserva": "R-1234"})
    assert llamadas == ["reprogramar_cita"]
    salida = _salidas(emitidos)[-1]
    assert salida.get("atencion_pausada") is True, (
        "la herramienta no llevaba turno: la mutacion habria seguido adelante: %r" % salida)
    assert motor.state["should_end_call"] is True


def test_en_el_widget_la_pausa_durante_la_herramienta_tambien_se_frena(entorno, monkeypatch):
    """La foto previa del endpoint no ve una pausa que cae despues de ella. Con
    el turno puesto, el nucleo la ve al mutar y la reserva no sigue."""
    from starlette.testclient import TestClient

    from backend import atencion_contexto, settings, voice

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-de-prueba")
    monkeypatch.setattr(voice, "_voice_widget_enabled", lambda *a, **k: True)
    mutadas = []

    async def _pausa_y_muta(cliente_id, nombre, argumentos, **kwargs):
        _pausar("demo")
        atencion_contexto.verificar_turno_atencion("demo")   # lo que hacen crear/cancelar/mover
        mutadas.append(nombre)
        return {"ok": True}

    monkeypatch.setattr(voice, "_voice_dispatch_tool", _pausa_y_muta)
    respuesta = TestClient(entorno.app).post(
        "/voice/widget/demo/tool", headers={"Origin": "http://testserver"},
        json={"name": "crear_cita", "arguments": "{}"})
    assert respuesta.status_code == 409, respuesta.text
    assert mutadas == [], "la reserva ha seguido adelante tras pausar a mitad de la herramienta"
