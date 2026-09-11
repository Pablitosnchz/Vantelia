# -*- coding: utf-8 -*-
"""Recordatorios de cita por WhatsApp fuera de la ventana de 24 h.

POR QUE EXISTE
--------------
Por WhatsApp solo se puede escribir texto libre DENTRO de las 24 h siguientes al
ultimo mensaje del cliente. Un recordatorio 24 h antes de la cita cae casi siempre
fuera, asi que Meta exige una **plantilla aprobada**. Antes de esto el codigo
mandaba igualmente el mensaje con botones: Meta lo rechazaba, el recordatorio no
llegaba y -lo peor- no quedaba constancia de por que.

REGLAS QUE VIGILA ESTE FICHERO (si uno falla, leelo antes de "arreglarlo")
-------------------------------------------------------------------------
1. Dentro de la ventana se sigue mandando con botones interactivos: es GRATIS y no
   hay que gastar una plantilla de pago.
2. Fuera de la ventana NO sale nada por WhatsApp sin plantilla aprobada.
3. Lo que no puede salir por WhatsApp acaba saliendo por email: un aviso no se
   pierde en silencio, y el motivo queda en `booking_audit`.
4. Los botones de la plantilla llevan el MISMO payload que los interactivos
   (`bkok_` / `bkcancel_`), para que la respuesta la procese el manejador de
   siempre (ver tests/test_boton_de_plantilla_de_whatsapp.py).
"""
from __future__ import annotations

import uuid

import pytest

from test_booking_exhaustive import _next_weekday, _run_async, api_module, client  # noqa: F401


@pytest.fixture
def cita(api_module):  # noqa: F811
    """Cita confirmada con telefono y email (para poder medir el respaldo)."""
    from backend import booking, db

    telefono = "34600888%03d" % (uuid.uuid4().int % 1000)
    record = {
        "id": "bk_plt_%s" % uuid.uuid4().hex[:8],
        "cliente_id": "demo", "employee_id": "", "employee_name": "",
        "nombre": "Ana Ruiz", "email": "ana@example.com", "telefono": telefono,
        "servicio": "Consulta", "booking_date": _next_weekday(1),
        "booking_time": "10:30", "notas": "", "status": "confirmed",
        "provider_name": "internal", "provider_status": "confirmed",
        "provider_booking_id": "", "provider_booking_url": "",
        "manage_token": "mg_plt_%s" % uuid.uuid4().hex[:8],
        "timezone": "Europe/Madrid", "start_at": "", "end_at": "",
        "confirmed_at": "", "cancelled_at": "",
        "rescheduled_at": "", "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "", "reminder_24h_sent_at": "",
        "reminder_2h_sent_at": "", "customer_email_status": "",
        "customer_email_last_error": "", "source": "whatsapp",
        "created_at": api_module._utc_now_iso(),
    }
    api_module._store_booking(record)
    fila = booking._get_booking_row_by_id(record["id"])
    try:
        yield fila
    finally:
        with db._get_db_connection() as connection:
            connection.execute("DELETE FROM bookings WHERE id = ?", (record["id"],))
            connection.execute("DELETE FROM booking_audit WHERE booking_id = ?", (record["id"],))
            connection.execute(
                "DELETE FROM wa_templates WHERE cliente_id = 'demo'"
            )
            connection.commit()


@pytest.fixture
def salida(api_module, monkeypatch):  # noqa: F811
    """Lo que sale por cada via, sin tocar la red."""
    from backend import messaging

    registro = {"botones": [], "plantillas": [], "textos": []}

    async def _botones(**kwargs):
        registro["botones"].append(kwargs)
        return True

    async def _payload(**kwargs):
        registro["plantillas"].append(kwargs["payload"])
        return True

    async def _texto(**kwargs):
        registro["textos"].append(kwargs.get("text"))
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", _botones)
    monkeypatch.setattr(messaging, "_send_whatsapp_payload", _payload)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", _texto)
    return registro


def _eventos(booking_id):
    from backend import db

    with db._get_db_connection() as connection:
        filas = connection.execute(
            "SELECT event_type, payload_json FROM booking_audit WHERE booking_id = ?",
            (booking_id,),
        ).fetchall()
    return [(f["event_type"], f["payload_json"]) for f in filas]


def _abrir_la_ventana(telefono):
    """Deja constancia de un mensaje ENTRANTE: eso abre las 24 h de Meta."""
    from backend import whatsapp

    whatsapp._wa_registrar(
        cliente_id="demo", from_number=telefono, request=None, entrante="hola",
    )


# --- Regla 1: dentro de la ventana, gratis ---------------------------------


def test_dentro_de_la_ventana_sigue_saliendo_con_botones(api_module, cita, salida):  # noqa: F811
    """Lo de siempre: si la clienta escribio hace poco, no se gasta una plantilla."""
    from backend import booking

    _abrir_la_ventana(cita["telefono"])

    assert _run_async(booking._send_booking_whatsapp_reminder(cita, "reminder_24h")) is True
    assert salida["botones"], "dentro de la ventana debe salir con botones interactivos"
    assert not salida["plantillas"], "no hay que gastar una plantilla de pago"


# --- Regla 2: fuera de la ventana hace falta plantilla aprobada -------------


def test_fuera_de_ventana_sin_plantilla_no_sale_por_whatsapp(api_module, cita, salida):  # noqa: F811
    """Lo que fallaba: se mandaba igual, Meta lo rechazaba y nadie se enteraba."""
    from backend import booking

    assert _run_async(booking._send_booking_whatsapp_reminder(cita, "reminder_24h")) is False
    assert not salida["botones"], "fuera de la ventana Meta no entrega texto libre"
    assert not salida["plantillas"]
    motivos = [p for e, p in _eventos(cita["id"]) if e == "reminder_whatsapp_skipped"]
    assert motivos, "el motivo tiene que quedar en la auditoria, no perderse"
    assert "sin_alta" in motivos[0]


def test_una_plantilla_en_revision_tampoco_vale(api_module, cita, salida):  # noqa: F811
    """PENDING no es APPROVED: hasta que Meta la apruebe, por WhatsApp no sale."""
    from backend import booking, wa_plantillas

    wa_plantillas.guardar_estado("demo", status="PENDING")

    assert _run_async(booking._send_booking_whatsapp_reminder(cita, "reminder_24h")) is False
    assert not salida["plantillas"]
    motivos = [p for e, p in _eventos(cita["id"]) if e == "reminder_whatsapp_skipped"]
    assert motivos and "pending" in motivos[0]


def test_una_plantilla_rechazada_deja_dicho_por_que(api_module, cita, salida):  # noqa: F811
    """El negocio tiene que poder saber que arreglar."""
    from backend import booking, wa_plantillas

    wa_plantillas.guardar_estado("demo", status="REJECTED", motivo_rechazo="INVALID_FORMAT")

    assert _run_async(booking._send_booking_whatsapp_reminder(cita, "reminder_24h")) is False
    motivos = [p for e, p in _eventos(cita["id"]) if e == "reminder_whatsapp_skipped"]
    assert motivos and "INVALID_FORMAT" in motivos[0]


def test_fuera_de_ventana_con_plantilla_aprobada_sale_la_plantilla(api_module, cita, salida):  # noqa: F811
    """El caso bueno: plantilla aprobada, con los datos de la cita y sus botones."""
    from backend import booking, wa_plantillas

    wa_plantillas.guardar_estado("demo", status="APPROVED", meta_id="123")

    assert _run_async(booking._send_booking_whatsapp_reminder(cita, "reminder_24h")) is True
    assert len(salida["plantillas"]) == 1, salida
    enviado = salida["plantillas"][0]

    assert enviado["type"] == "template"
    assert enviado["template"]["name"] == wa_plantillas.NOMBRE_RECORDATORIO
    assert enviado["template"]["language"] == {"code": "es"}

    cuerpo = [c for c in enviado["template"]["components"] if c["type"] == "body"][0]
    textos = [p["text"] for p in cuerpo["parameters"]]
    assert textos[0] == "Ana", "el saludo va por el nombre de pila"
    assert "10:30" in textos, textos
    assert len(textos) == len(wa_plantillas.EJEMPLO), "el numero de variables tiene que cuadrar"

    botones = [c for c in enviado["template"]["components"] if c["type"] == "button"]
    payloads = [b["parameters"][0]["payload"] for b in botones]
    assert payloads == ["bkok_%s" % cita["id"], "bkcancel_%s" % cita["id"]], payloads

    tipos = [e for e, _ in _eventos(cita["id"])]
    assert "reminder_whatsapp_template_sent" in tipos


def test_el_tope_diario_frena_las_plantillas(api_module, cita, salida):  # noqa: F811
    """Cada plantilla fuera de ventana la paga el negocio: el tope se respeta."""
    from backend import appstate, booking, wa_plantillas

    wa_plantillas.guardar_estado("demo", status="APPROVED")
    config = appstate.CONFIG_CLIENTES["demo"]
    previo = config.get("reminders")
    config["reminders"] = dict(previo or {}, whatsapp_cap_dia=1)
    try:
        assert _run_async(booking._send_booking_whatsapp_reminder(cita, "reminder_24h")) is True
        # La segunda ya pasa del tope.
        assert _run_async(booking._send_booking_whatsapp_reminder(cita, "reminder_2h")) is False
    finally:
        if previo is None:
            config.pop("reminders", None)
        else:
            config["reminders"] = previo

    assert len(salida["plantillas"]) == 1, salida
    motivos = [p for e, p in _eventos(cita["id"]) if e == "reminder_whatsapp_skipped"]
    assert motivos and "tope_diario" in motivos[0]


# --- Regla 3: el aviso no se pierde ----------------------------------------


def test_si_no_sale_por_whatsapp_el_aviso_acaba_en_el_email(api_module, cita, salida, monkeypatch):  # noqa: F811
    """La regla que mas importa: sin plantilla, el recordatorio sale por email."""
    from backend import appstate, booking, messaging

    correos = []
    monkeypatch.setattr(booking, "_send_booking_email",
                        lambda row, kind, request=None: correos.append(kind))
    # Sin token el canal se descarta antes de llegar a la plantilla, y el test
    # pasaria por el motivo equivocado.
    monkeypatch.setattr(messaging, "_whatsapp_access_token_for_client", lambda cliente_id: "tok")

    config = appstate.CONFIG_CLIENTES["demo"]
    previo_rec, previo_ch = config.get("reminders"), config["booking"].get("message_template_channels")
    config["reminders"] = dict(previo_rec or {}, delivery_priority=["whatsapp", "email"])
    config["booking"]["message_template_channels"] = {
        "reminder_24h": {"email": True, "whatsapp": True, "sms": False},
    }
    try:
        resultado = _run_async(booking._send_booking_reminder_by_kind(cita, "reminder_24h"))
    finally:
        if previo_rec is None:
            config.pop("reminders", None)
        else:
            config["reminders"] = previo_rec
        if previo_ch is None:
            config["booking"].pop("message_template_channels", None)
        else:
            config["booking"]["message_template_channels"] = previo_ch

    assert correos == ["reminder_24h"], "el recordatorio se ha perdido: no salio por ningun canal"
    assert "email" in resultado["sent"], resultado
    assert not salida["plantillas"] and not salida["botones"]


# --- El texto que se le manda a Meta ---------------------------------------


def test_los_parametros_no_llevan_saltos_de_linea(api_module):  # noqa: F811
    """Meta rechaza el envio ENTERO si un parametro trae saltos o 4 espacios."""
    from backend import wa_plantillas

    payload = wa_plantillas.payload_recordatorio(
        to_number="34600000000", booking_id="bk1",
        nombre="Ana\nRuiz", servicio="Corte    señora", dia="lunes", hora="10:00",
        negocio="Peluqueria\tAlicia",
    )
    for parametro in payload["template"]["components"][0]["parameters"]:
        assert "\n" not in parametro["text"] and "\t" not in parametro["text"], parametro
        assert "    " not in parametro["text"], parametro


def test_la_plantilla_declara_tantos_ejemplos_como_variables(api_module):  # noqa: F811
    """Meta rechaza la plantilla si los ejemplos no cuadran con las {{n}}."""
    from backend import wa_plantillas

    cuerpo = [c for c in wa_plantillas.componentes() if c["type"] == "BODY"][0]
    variables = {t for t in cuerpo["text"].split("{{")[1:]}
    assert len(variables) == len(wa_plantillas.EJEMPLO)
    assert cuerpo["example"]["body_text"] == [wa_plantillas.EJEMPLO]
    assert len(wa_plantillas.BOTONES) == 2


# --- Alta de la plantilla en la WABA del negocio ---------------------------


@pytest.fixture
def meta_falsa(api_module, monkeypatch):  # noqa: F811
    """La Graph API, simulada. Devuelve lo que le digas y apunta lo que le piden."""
    from backend import db, wa_onboarding, wa_plantillas

    estado = {"existentes": [], "creada": {"id": "tpl_1", "status": "PENDING"}, "creaciones": []}

    monkeypatch.setattr(wa_plantillas, "_waba_y_token", lambda cliente_id: ("WABA1", "tok"))

    async def _get(path, params):
        return {"data": list(estado["existentes"])}

    async def _post(path, token, body):
        estado["creaciones"].append(body)
        return dict(estado["creada"])

    monkeypatch.setattr(wa_onboarding, "_graph_get", _get)
    monkeypatch.setattr(wa_plantillas, "_graph_post_json", _post)
    try:
        yield estado
    finally:
        with db._get_db_connection() as connection:
            connection.execute("DELETE FROM wa_templates WHERE cliente_id = 'demo'")
            connection.commit()


def test_asegurar_crea_la_plantilla_si_no_existe(api_module, meta_falsa):  # noqa: F811
    from backend import wa_plantillas

    resultado = _run_async(wa_plantillas.asegurar("demo"))

    assert len(meta_falsa["creaciones"]) == 1
    creada = meta_falsa["creaciones"][0]
    assert creada["category"] == "UTILITY", "UTILITY o Meta la cobra como marketing"
    assert creada["language"] == "es"
    assert resultado["status"] == "PENDING"
    assert wa_plantillas.aprobada("demo") is False


def test_asegurar_no_duplica_una_plantilla_que_ya_existe(api_module, meta_falsa):  # noqa: F811
    """Se llama al dar de alta el numero, desde el portal y desde el worker."""
    from backend import wa_plantillas

    meta_falsa["existentes"] = [{
        "id": "tpl_ya", "status": "APPROVED", "language": "es", "category": "UTILITY",
        "name": wa_plantillas.NOMBRE_RECORDATORIO,
    }]

    resultado = _run_async(wa_plantillas.asegurar("demo"))

    assert meta_falsa["creaciones"] == [], "no se puede crear dos veces la misma plantilla"
    assert resultado["status"] == "APPROVED" and resultado["meta_id"] == "tpl_ya"
    assert wa_plantillas.aprobada("demo") is True


def test_asegurar_guarda_el_motivo_del_rechazo(api_module, meta_falsa):  # noqa: F811
    from backend import wa_plantillas

    meta_falsa["existentes"] = [{
        "id": "tpl_no", "status": "REJECTED", "language": "es",
        "rejected_reason": "PROMOTIONAL", "name": wa_plantillas.NOMBRE_RECORDATORIO,
    }]

    resultado = _run_async(wa_plantillas.asegurar("demo"))

    assert resultado["status"] == "REJECTED"
    assert resultado["motivo_rechazo"] == "PROMOTIONAL"
    assert wa_plantillas.aprobada("demo") is False


def test_si_meta_falla_no_revienta_y_la_plantilla_no_queda_aprobada(api_module, meta_falsa, monkeypatch):  # noqa: F811
    """Un fallo de Meta no puede tumbar el alta ni el worker de recordatorios."""
    from backend import wa_onboarding, wa_plantillas

    async def _revienta(path, params):
        raise RuntimeError("(#100) Tried accessing nonexisting field")

    monkeypatch.setattr(wa_onboarding, "_graph_get", _revienta)

    resultado = _run_async(wa_plantillas.asegurar("demo"))

    assert "nonexisting" in resultado["last_error"]
    assert wa_plantillas.aprobada("demo") is False


def test_sin_cuenta_conectada_lo_dice_en_vez_de_intentarlo(api_module, monkeypatch):  # noqa: F811
    """Las plantillas viven en la WABA del negocio: sin su cuenta no hay nada que crear."""
    from backend import db, wa_plantillas

    monkeypatch.setattr(wa_plantillas, "_waba_y_token", lambda cliente_id: ("", ""))
    try:
        resultado = _run_async(wa_plantillas.asegurar("demo"))
        assert "conectada" in resultado["last_error"]
        assert wa_plantillas.aprobada("demo") is False
    finally:
        with db._get_db_connection() as connection:
            connection.execute("DELETE FROM wa_templates WHERE cliente_id = 'demo'")
            connection.commit()


def test_el_estado_lo_actualiza_el_webhook_de_meta(api_module):  # noqa: F811
    """Meta avisa de la aprobacion; sin esto habria que preguntarle todo el rato."""
    from backend import db, wa_plantillas

    try:
        wa_plantillas.actualizar_desde_webhook("demo", {
            "event": "APPROVED",
            "message_template_id": "tpl_9",
            "message_template_name": wa_plantillas.NOMBRE_RECORDATORIO,
            "message_template_language": "es",
        })
        assert wa_plantillas.aprobada("demo") is True

        wa_plantillas.actualizar_desde_webhook("demo", {
            "event": "REJECTED",
            "message_template_name": wa_plantillas.NOMBRE_RECORDATORIO,
            "message_template_language": "es",
            "reason": "INCORRECT_CATEGORY",
        })
        assert wa_plantillas.aprobada("demo") is False
        assert wa_plantillas.estado("demo")["motivo_rechazo"] == "INCORRECT_CATEGORY"
        assert wa_plantillas.estado("demo")["meta_id"] == "tpl_9", "el id no se pierde al rechazar"
    finally:
        with db._get_db_connection() as connection:
            connection.execute("DELETE FROM wa_templates WHERE cliente_id = 'demo'")
            connection.commit()
