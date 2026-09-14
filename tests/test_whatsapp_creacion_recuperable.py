import asyncio
import uuid

import httpx
import pytest

from test_huecos_para_mover_la_cita import api_module, agenda_de_dos  # noqa: F401


@pytest.fixture
def canal(agenda_de_dos, monkeypatch):
    from backend import booking, db, inbox, messaging, whatsapp
    _, dia, profesionales, _ = agenda_de_dos
    numero = uuid.uuid4().hex
    flow = whatsapp._wa_get_flow("demo", numero)
    flow.nombre, flow.fecha, flow.hora = "Ana Prueba", dia, "10:00"
    flow.employee_id = profesionales[0]["id"]
    flow.employee_name = profesionales[0]["name"]
    botones, textos, proveedores = [], [], []
    async def no(**kw): return False
    async def si(**kw): return True
    async def boton(**kw):
        botones.append(kw)
        return True
    async def texto(**kw):
        textos.append(kw["text"])
        return True
    original = booking._create_provider_booking
    async def proveedor(*a, **kw):
        proveedores.append(1)
        return await original(*a, **kw)
    monkeypatch.setattr(booking, "_create_provider_booking", proveedor)
    monkeypatch.setattr(whatsapp, "_wa_freno_del_precio", no)
    monkeypatch.setattr(whatsapp, "_wa_explicar_el_recargo", si)
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **kw: None)
    monkeypatch.setattr(whatsapp, "_wa_cita_viva_distinta", lambda *a: {})
    monkeypatch.setattr(inbox, "bot_is_muted", lambda *a: False)
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", boton)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(messaging, "_send_whatsapp_cta_url", si)
    asyncio.run(whatsapp._wa_send_booking_summary(cliente_id="demo", phone_number_id="PN",
        to_number=numero, flow=flow))
    identidad = botones[-1]["buttons"][0][0]
    def responder():
        asyncio.run(whatsapp._handle_whatsapp_message(cliente_id="demo", phone_number_id="PN",
            from_number=numero, incoming_text="Confirmar", interactive_id=identidad, request=None))
    def citas():
        with db._get_db_connection() as conn:
            return conn.execute("SELECT * FROM bookings WHERE cliente_id='demo' AND telefono=?", (numero,)).fetchall()
    yield numero, responder, citas, textos, proveedores
    whatsapp._wa_clear_flow("demo", numero)
    with db._get_db_connection() as conn:
        conn.execute("DELETE FROM booking_operations WHERE cliente_id='demo' AND operation_key=?",
                     ("wa:" + identidad.partition(":")[2],))
        conn.execute("DELETE FROM bookings WHERE telefono=?", (numero,))
        conn.commit()


@pytest.mark.parametrize("estado_real", ["confirmed", "cancelled", "pending_payment"])
def test_reinicio_tras_commit_recupera_estado_real_sin_recrear(canal, monkeypatch, estado_real):
    from backend import agenda, appstate, booking, db, reserva
    numero, responder, citas, textos, proveedores = canal
    def caer(*a, **kw): raise RuntimeError("caida despues del commit")
    monkeypatch.setattr(booking, "_record_booking_audit", caer)
    responder()
    filas = citas()
    assert len(filas) == 1
    p = reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero))
    assert p and p.get("operacion"), "Perder la respuesta no debe borrar la identidad ejecutada"
    if estado_real != "confirmed":
        with db._get_db_connection() as conn:
            conn.execute("UPDATE bookings SET status=? WHERE id=?", (estado_real, filas[0]["id"]))
            conn.commit()
    def prohibido(*a, **kw): raise AssertionError("Recuperar no consulta huecos ni recrea")
    monkeypatch.setattr(agenda, "_resolve_employee_for_booking", prohibido)
    monkeypatch.setattr(booking, "_create_booking_core", prohibido)
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    textos.clear()
    responder()
    assert len(citas()) == 1 and len(proveedores) == 1
    if estado_real == "pending_payment":
        assert not any(filas[0]["booking_code"] in t for t in textos)
    else:
        assert any(filas[0]["booking_code"] in t for t in textos)
    etiqueta = {"confirmed": "confirmada", "cancelled": "cancelada", "pending_payment": "pendiente de pago"}
    assert any(etiqueta[estado_real] in t.lower() for t in textos)
    if estado_real != "confirmed":
        assert not any("cita confirmada" in t.lower() for t in textos)


def test_resultado_desconocido_no_ofrece_otro_hueco_ni_repite(canal, monkeypatch):
    from backend import appstate, booking, reserva
    numero, responder, citas, textos, _ = canal
    llamadas = []
    async def timeout(*a, **kw):
        llamadas.append(1)
        raise httpx.ReadTimeout("resultado desconocido")
    monkeypatch.setattr(booking, "_create_provider_booking", timeout)
    responder()
    assert reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero))
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    textos.clear()
    responder()
    assert len(llamadas) == 1 and not citas()
    assert any("verificar" in t.lower() for t in textos)
    assert not any("disponible" in t.lower() for t in textos)


def test_resultado_perdido_antiguo_sin_webhook_pide_confirmar_de_nuevo(canal, monkeypatch):
    from backend import appstate, booking, db, reserva, timeutils
    from datetime import timedelta
    numero, responder, citas, textos, proveedores = canal
    async def timeout(*a, **k):
        raise httpx.ReadTimeout("resultado desconocido")
    monkeypatch.setattr(booking, "_create_provider_booking", timeout)
    responder()
    propuesta = reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero))
    assert propuesta and propuesta.get("operacion")
    with db._get_db_connection() as conn:
        conn.execute("UPDATE booking_operations SET created_at=? WHERE cliente_id='demo' AND operation_key=?",
                     ((timeutils._utc_now() - timedelta(minutes=16)).replace(tzinfo=None).isoformat() + "Z",
                      propuesta["operacion"]["clave"]))
        conn.commit()
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    textos.clear()
    responder()
    actual = reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero))
    assert not citas() and not proveedores
    assert actual and actual["estado"] == "ofrecida" and not actual.get("operacion")
    assert any("no lleg" in texto.lower() and "registr" in texto.lower() for texto in textos)


def test_conflicto_al_liberar_recarga_y_vuelve_a_pedir_confirmacion(canal, monkeypatch):
    from backend import appstate, booking, reserva, timeutils, whatsapp
    from backend.conversation_state import ConversationStateConflict
    from datetime import timedelta
    numero, responder, citas, textos, proveedores = canal
    async def timeout(*a, **k):
        raise httpx.ReadTimeout("resultado desconocido")
    monkeypatch.setattr(booking, "_create_provider_booking", timeout)
    responder()
    propuesta = reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero))
    assert propuesta and propuesta.get("operacion")
    ahora = timeutils._utc_now()
    monkeypatch.setattr(timeutils, "_utc_now", lambda: ahora + timedelta(minutes=16))
    original = reserva.guardar
    llamadas = []
    def conflicto_una_vez(*args, **kwargs):
        if not llamadas:
            llamadas.append(1)
            raise ConversationStateConflict("otro turno")
        return original(*args, **kwargs)
    monkeypatch.setattr(reserva, "guardar", conflicto_una_vez)
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    textos.clear()
    responder()
    actual = reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero))
    assert llamadas and not citas() and not proveedores
    assert actual and actual["estado"] == "ofrecida" and not actual.get("operacion")
    assert any("no lleg" in texto.lower() for texto in textos)


def test_operacion_ausente_antigua_reabre_pero_reciente_sigue_pendiente(canal, monkeypatch):
    from backend import appstate, booking, db, reserva, whatsapp
    numero, responder, citas, textos, proveedores = canal
    async def timeout(*a, **k):
        raise httpx.ReadTimeout("resultado desconocido")
    monkeypatch.setattr(booking, "_create_provider_booking", timeout)
    responder()
    propuesta = reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero))
    with db._get_db_connection() as conn:
        conn.execute("DELETE FROM booking_operations WHERE cliente_id='demo' AND operation_key=?",
                     (propuesta["operacion"]["clave"],))
        conn.commit()
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    textos.clear()
    responder()
    assert not citas() and not proveedores
    assert any("verificar" in texto.lower() for texto in textos)
    monkeypatch.setattr(whatsapp.time, "time", lambda: propuesta["creada"] + 16 * 60)
    textos.clear()
    responder()
    actual = reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero))
    assert actual and actual["estado"] == "ofrecida" and not actual.get("operacion")
    assert any("no lleg" in texto.lower() for texto in textos)


def test_confirmacion_no_entregada_se_recupera_sin_repetir_creacion(canal, monkeypatch):
    from backend import appstate, messaging, reserva
    numero, responder, citas, textos, proveedores = canal
    async def rechazado(**kw): return False
    monkeypatch.setattr(messaging, "_send_whatsapp_text", rechazado)
    responder()
    assert len(citas()) == 1
    assert not reserva.cargar("demo", numero).hecho
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    async def enviado(**kw):
        textos.append(kw["text"])
        return True
    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviado)
    responder()
    assert len(citas()) == 1 and len(proveedores) == 1
    assert any(citas()[0]["booking_code"] in t for t in textos)
    assert reserva.cargar("demo", numero).hecho


def test_resumen_cambiado_durante_consulta_no_ejecuta_ni_borra_el_nuevo(canal, monkeypatch):
    from backend import agenda, reserva
    numero, responder, citas, _, proveedores = canal
    original = agenda._booking_slot_available
    nuevos = []
    async def cambiar(*a, **kw):
        estado = reserva.cargar("demo", numero)
        datos = reserva.leer_confirmacion_reserva(estado)["datos"]
        datos["hora"] = "11:00"
        nuevo = reserva.preparar_confirmacion_reserva(estado, datos)
        reserva.avanzar_confirmacion_reserva(estado, nuevo, "ofrecida")
        reserva.guardar("demo", numero, estado)
        nuevos.append(nuevo)
        return await original(*a, **kw)
    monkeypatch.setattr(agenda, "_booking_slot_available", cambiar)
    responder()
    assert not citas() and not proveedores
    actual = reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero))
    assert actual and actual["id"] == nuevos[-1] and actual["estado"] == "ofrecida"


def test_rechazo_antes_de_ejecutar_no_deja_operacion_bloqueada(canal, monkeypatch):
    from backend import booking, reserva
    from fastapi import HTTPException
    numero, responder, citas, textos, _ = canal
    async def rechazar(*a, **kw):
        raise HTTPException(status_code=409, detail="Ese horario ya no esta disponible")
    monkeypatch.setattr(booking, "_create_booking_core", rechazar)
    responder()
    assert not citas()
    assert reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero)) is None
    assert not any("verificar" in t.lower() for t in textos)
