import asyncio
import uuid

import pytest

from test_huecos_para_mover_la_cita import api_module, agenda_de_dos  # noqa: F401


@pytest.fixture
def conversacion(agenda_de_dos, monkeypatch):
    from backend import whatsapp, messaging, reserva, appstate, inbox
    numero = uuid.uuid4().hex
    flow = whatsapp._wa_get_flow("demo", numero)
    flow.nombre, flow.servicio = "Ana Prueba", "Corte"
    # El resumen ahora consulta la agenda real; esta fixture abre ese día incluso
    # en fin de semana y aporta un profesional libre a las 10 y a las 11.
    _, dia, empleados, _ = agenda_de_dos
    flow.fecha, flow.hora = dia, "10:00"
    flow.employee_id, flow.employee_name = empleados[0]["id"], empleados[0]["name"]
    botones, creadas, textos = [], [], []
    async def sin_freno(**kw): return False
    async def nada(**kw): return True
    async def enviar(**kw):
        botones.append(kw)
        return True
    async def texto(**kw):
        textos.append(kw["text"])
        return True
    async def crear(**kw):
        creadas.append(kw["flow"].hora)
        return True
    monkeypatch.setattr(whatsapp, "_wa_freno_del_precio", sin_freno)
    monkeypatch.setattr(whatsapp, "_wa_explicar_el_recargo", nada)
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **kw: None)
    monkeypatch.setattr(whatsapp, "_wa_cita_viva_distinta", lambda *a: {})
    monkeypatch.setattr(whatsapp, "_wa_create_booking", crear)
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(inbox, "bot_is_muted", lambda *a: False)
    def ofrecer():
        asyncio.run(whatsapp._wa_send_booking_summary(cliente_id="demo", phone_number_id="PN",
            to_number=numero, flow=flow))
        return botones[-1]["buttons"][0][0] if botones else "confirm_yes"
    def responder(iid="", text="Confirmar"):
        asyncio.run(whatsapp._handle_whatsapp_message(cliente_id="demo", phone_number_id="PN",
            from_number=numero, incoming_text=text, interactive_id=iid, request=None))
    yield flow, ofrecer, responder, creadas, textos, numero
    whatsapp._wa_clear_flow("demo", numero)


def test_un_boton_del_resumen_anterior_no_confirma_el_nuevo(conversacion):
    flow, ofrecer, responder, creadas, _, _ = conversacion
    viejo = ofrecer()
    flow.hora = "11:00"
    nuevo = ofrecer()
    responder(viejo)
    assert creadas == []
    responder(nuevo)
    assert creadas == ["11:00"]


def test_resumen_no_enviado_no_autoriza_un_si(conversacion, monkeypatch):
    from backend import messaging
    _, ofrecer, responder, creadas, _, _ = conversacion
    async def rechazado(**kw): return False
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", rechazado)
    ofrecer()
    responder(text="sí")
    assert creadas == []


def test_reinicio_recupera_el_resumen_ofrecido(conversacion, monkeypatch):
    from backend import appstate
    _, ofrecer, responder, creadas, _, _ = conversacion
    boton = ofrecer()
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    responder(boton)
    assert creadas == ["10:00"]


def test_boton_generico_antiguo_no_acredita_la_oferta_actual(conversacion):
    _, ofrecer, responder, creadas, _, _ = conversacion
    ofrecer()
    responder("confirm_yes")
    assert creadas == []


def test_corregir_datos_invalida_el_boton_anterior(conversacion):
    _, ofrecer, responder, creadas, _, _ = conversacion
    boton = ofrecer()
    responder("data_fix", "Otros datos")
    responder(boton)
    assert creadas == []


def test_datos_del_worker_no_sustituyen_el_resumen_al_decir_si(conversacion):
    flow, ofrecer, responder, creadas, _, _ = conversacion
    ofrecer()
    flow.hora = "11:00"
    responder(text="sí")
    assert creadas == []


def test_aceptacion_publicada_antes_de_ejecutar_y_sin_segunda_llamada(conversacion, monkeypatch):
    from backend import whatsapp, reserva
    _, ofrecer, responder, creadas, _, numero = conversacion
    boton = ofrecer()
    async def ejecutar(**kw):
        p = reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero))
        assert p["estado"] == "aceptada"
        creadas.append(kw["flow"].hora)
        await whatsapp._handle_whatsapp_message(cliente_id="demo", phone_number_id="PN",
            from_number=numero, incoming_text="Confirmar", interactive_id=boton, request=None)
        return True
    monkeypatch.setattr(whatsapp, "_wa_create_booking", ejecutar)
    responder(boton)
    assert creadas == ["10:00"]


def test_acuse_tardio_no_resucita_un_resumen_descartado(conversacion, monkeypatch):
    from backend import messaging, reserva
    _, ofrecer, responder, creadas, _, numero = conversacion
    enviados = []
    async def enviar(**kw):
        p = reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero))
        assert p["estado"] == "preparada"
        enviados.append(kw["buttons"][0][0])
        reserva.olvidar("demo", numero)
        return True
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    ofrecer()
    responder(enviados[0])
    assert creadas == []
    assert reserva.leer_confirmacion_reserva(reserva.cargar("demo", numero)) is None


def test_otro_tenant_no_tiene_la_confirmacion(conversacion):
    from backend import reserva
    _, ofrecer, _, _, _, numero = conversacion
    ofrecer()
    assert reserva.leer_confirmacion_reserva(reserva.cargar("otro", numero)) is None


def test_gestion_terminada_no_reutiliza_el_resumen(conversacion):
    from backend import reserva
    _, ofrecer, responder, creadas, _, numero = conversacion
    boton = ofrecer()
    reserva.marcar_hecha("demo", numero)
    responder(boton)
    assert creadas == []
