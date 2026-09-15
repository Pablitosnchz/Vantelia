# -*- coding: utf-8 -*-
"""Cambiar una cita por el flujo guiado de WhatsApp exige aceptar el cambio concreto.

POR QUE EXISTE
--------------
Fase 4 del plan de consolidación. Cancelar por WhatsApp ya pedía aceptar un resumen guardado
con identidad (tests/test_cancelacion_whatsapp_confirmada.py), pero el flujo guiado de
reprogramar movía la cita en cuanto tenía día y hora: sin resumen, sin botón y sin poder
recuperar un resultado perdido. Decisión de Pablo del 14-sep-2026: «Solo el flujo de
listas». Desde el 15-sep-2026 el agente conversacional (el que usa Alicia) usa este mismo
resumen: ver tests/test_reprogramar_desde_el_agente.py.
"""
import asyncio
import uuid

import pytest


@pytest.fixture
def cambio(api_module, monkeypatch):
    from backend import booking, inbox, messaging, whatsapp

    numero = "346" + str(uuid.uuid4().int % 100000000).zfill(8)
    filas = {
        "R-123456": dict(id="primera", cliente_id="demo", booking_code="R-123456",
            telefono=numero, email="", servicio="Consulta", booking_date="2099-09-15",
            booking_time="10:00", employee_id="", employee_name="", location_id="",
            status="confirmed"),
        "R-654321": dict(id="segunda", cliente_id="demo", booking_code="R-654321",
            telefono=numero, email="", servicio="Corte", booking_date="2099-09-16",
            booking_time="11:00", employee_id="", employee_name="", location_id="",
            status="confirmed"),
    }
    botones, textos, registros, movidas = [], [], [], []
    libre = {"si": True}

    async def lookup(tenant, code, **kw):
        fila = filas.get(code)
        if not fila or fila["cliente_id"] != tenant:
            return None, {"ok": False, "error": "Cita inexistente"}
        if not (kw.get("trusted_phone") == fila["telefono"]
                or (kw.get("email") and kw["email"] == fila["email"])):
            return None, {"ok": False, "needs_verification": True, "error": "Verifica la reserva"}
        return dict(fila), None

    async def mover(tenant, code, fecha, hora, **kw):
        fila = filas[code]
        esperado = kw.get("expected_snapshot")
        if esperado is not None and (booking._booking_cancellation_snapshot(fila)
                                     != booking._booking_cancellation_snapshot(esperado)):
            return {"ok": False, "cita_cambiada": True, "error": "La cita ha cambiado desde el resumen."}
        movidas.append((code, fecha, hora))
        fila.update(booking_date=fecha, booking_time=hora)
        return {"ok": True, "codigo_reserva": code, "fecha": fecha, "hora": hora}

    async def hueco_libre(tenant, fila, fecha, hora):
        return libre["si"]

    async def fallo(tenant, resultado, fecha, hora):
        return "Ese hueco no está libre."

    async def enviar(**kw):
        botones.append(kw)
        return True

    async def texto(**kw):
        textos.append(kw["text"])
        return True

    monkeypatch.setattr(booking, "_lookup_and_verify_booking_by_code", lookup)
    monkeypatch.setattr(booking, "_reschedule_booking_by_code", mover)
    monkeypatch.setattr(booking, "_reschedule_slot_is_free", hueco_libre, raising=False)
    monkeypatch.setattr(booking, "_reschedule_failure_text", fallo)
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(inbox, "bot_is_muted", lambda *a: False)
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **kw: registros.append(kw))

    def recibir(text="", iid=""):
        asyncio.run(whatsapp._handle_whatsapp_message(cliente_id="demo", phone_number_id="PN",
            from_number=numero, incoming_text=text, interactive_id=iid, request=None))

    def ofrecer(code="R-123456", fecha="2099-09-20", hora="12:00"):
        recibir("Cambiar mi cita %s al %s a las %s" % (code, fecha, hora), "menu_cambiar_cita")
        return botones[-1]["buttons"][0][0] if botones else ""

    yield dict(numero=numero, filas=filas, botones=botones, textos=textos, registros=registros,
               movidas=movidas, libre=libre, recibir=recibir, ofrecer=ofrecer)
    whatsapp._wa_clear_flow("demo", numero)


def test_pedir_el_cambio_lo_ofrece_sin_mover(cambio):
    c = cambio
    boton = c["ofrecer"]()
    assert c["movidas"] == [], "movio la cita sin que aceptara el cambio"
    assert boton.startswith("resched_yes:")
    cuerpo = c["botones"][-1]["body"]
    assert "R-123456" in cuerpo and "12:00" in cuerpo and "10:00" in cuerpo


def test_aceptar_mueve_una_vez_al_dia_y_hora_ofrecidos(cambio):
    c = cambio
    boton = c["ofrecer"]()
    c["recibir"](iid=boton)
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00")]
    assert "✅" in c["textos"][-1] and "12:00" in c["textos"][-1]


def test_si_escrito_sin_identidad_no_mueve(cambio):
    c = cambio
    c["ofrecer"]()
    c["recibir"]("sí")
    c["recibir"](iid="resched_yes")
    assert c["movidas"] == []


def test_boton_antiguo_no_autoriza_otra_cita(cambio):
    c = cambio
    viejo = c["ofrecer"]()
    nuevo = c["ofrecer"]("R-654321", "2099-09-21", "13:00")
    c["recibir"](iid=viejo)
    assert c["movidas"] == []
    c["recibir"](iid=nuevo)
    assert c["movidas"] == [("R-654321", "2099-09-21", "13:00")]


def test_cita_cambiada_desde_el_portal_exige_nueva_oferta(cambio):
    c = cambio
    boton = c["ofrecer"]()
    c["filas"]["R-123456"]["booking_time"] = "10:30"
    c["recibir"](iid=boton)
    assert c["movidas"] == []
    assert any("cambi" in t.lower() for t in c["textos"])


def test_reinicio_recupera_el_cambio_sin_datos_del_worker(cambio, monkeypatch):
    from backend import appstate

    c = cambio
    boton = c["ofrecer"]()
    assert c["movidas"] == [] and boton.startswith("resched_yes:")
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    c["recibir"](iid=boton)
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00")]


def test_mantener_descarta_sin_mover(cambio):
    c = cambio
    boton = c["ofrecer"]()
    c["recibir"](iid=c["botones"][-1]["buttons"][1][0])
    c["recibir"](iid=boton)
    assert c["movidas"] == []


def test_hueco_ocupado_no_se_ofrece(cambio):
    c = cambio
    c["libre"]["si"] = False
    c["ofrecer"]()
    assert c["botones"] == [] and c["movidas"] == []
    assert any("no está libre" in t for t in c["textos"])


def test_boton_de_cancelar_no_acepta_un_cambio(cambio):
    c = cambio
    boton = c["ofrecer"]()
    c["recibir"](iid=boton.replace("resched_yes:", "cancel_yes:"))
    assert c["movidas"] == []
    assert c["filas"]["R-123456"]["status"] == "confirmed"


def test_pulsar_dos_veces_no_vuelve_a_mover(cambio):
    c = cambio
    boton = c["ofrecer"]()
    c["recibir"](iid=boton)
    c["recibir"](iid=boton)
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00")]
    assert "✅" in c["textos"][-1]


def test_resultado_desconocido_se_puede_volver_a_pulsar(cambio, monkeypatch):
    """Mover no rompe nada que no se pueda volver a mover: no se deja en «contacta con el negocio»."""
    from backend import booking

    c = cambio
    boton = c["ofrecer"]()
    mover = booking._reschedule_booking_by_code
    async def incierto(*a, **k):
        raise RuntimeError("se corto la conexion")
    monkeypatch.setattr(booking, "_reschedule_booking_by_code", incierto)
    c["recibir"](iid=boton)
    assert c["movidas"] == [] and not any("✅" in t for t in c["textos"])
    assert "contacta con el negocio" not in c["textos"][-1].lower()
    monkeypatch.setattr(booking, "_reschedule_booking_by_code", mover)
    c["recibir"](iid=boton)
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00")]
    assert "✅" in c["textos"][-1]


def test_por_pasos_tampoco_mueve_hasta_aceptar(cambio):
    c = cambio
    c["recibir"]("quiero cambiar mi cita", "menu_cambiar_cita")
    c["recibir"]("R-123456")
    c["recibir"]("2099-09-20")
    c["recibir"]("12:00")
    assert c["movidas"] == [], "el flujo por pasos movio la cita al tener la hora"
    assert c["botones"] and c["botones"][-1]["buttons"][0][0].startswith("resched_yes:")
    c["recibir"](iid=c["botones"][-1]["buttons"][0][0])
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00")]


def test_verificacion_antes_de_ofrecer(cambio):
    c = cambio
    c["filas"]["R-123456"].update(telefono="34900000000", email="qa@example.invalid")
    c["ofrecer"]()
    assert c["botones"] == [] and c["movidas"] == []
    c["recibir"]("qa@example.invalid")
    assert c["movidas"] == []
    assert c["botones"] and c["botones"][-1]["buttons"][0][0].startswith("resched_yes:")
    c["recibir"](iid=c["botones"][-1]["buttons"][0][0])
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00")]


def test_el_contacto_del_primer_mensaje_verifica_aunque_falten_dia_y_hora(cambio):
    """Revisión de Astra a e44886b: el email del primer mensaje no llegaba a la oferta si
    el día y la hora venían después, y se le pedía verificar otra vez."""
    c = cambio
    c["filas"]["R-123456"].update(telefono="34900000000", email="qa@example.invalid")
    c["recibir"]("Quiero cambiar mi cita R-123456, mi email es qa@example.invalid", "menu_cambiar_cita")
    c["recibir"]("2099-09-20")
    c["recibir"]("12:00")
    assert not any("verificar" in t.lower() for t in c["textos"]), c["textos"]
    assert c["botones"] and c["botones"][-1]["buttons"][0][0].startswith("resched_yes:")
    assert c["movidas"] == []
