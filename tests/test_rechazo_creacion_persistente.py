"""Un rechazo no se cura por pasar de turno; una propuesta validada sí lo resuelve."""
import asyncio

import pytest

from test_whatsapp_creacion_recuperable import api_module, agenda_de_dos, canal  # noqa: F401


def test_emisor_real_bloquea_y_una_aclaracion_validada_crea_una_sola_cita(canal, monkeypatch, request):
    from backend import db, messaging, reserva, whatsapp
    numero, responder_antiguo, citas, textos, proveedores = canal
    flow = whatsapp._wa_get_flow("demo", numero)
    estado = reserva.cargar("demo", numero)
    reserva.anotar_resultado(estado, "crear_cita", {},
                            {"ok": False, "error": "Falta aclarar el servicio"})
    reserva.guardar("demo", numero, estado)
    botones = []

    async def enviar(**kw):
        botones.append(kw)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)

    def resumen():
        return asyncio.run(whatsapp._wa_send_booking_summary(
            cliente_id="demo", phone_number_id="PN", to_number=numero, flow=flow))

    assert resumen() is False
    assert not botones and not citas() and not proveedores
    responder_antiguo()  # Tampoco vale una oferta anterior al rechazo.
    assert not citas() and not proveedores
    estado = reserva.cargar("demo", numero)
    reserva.anotar_resultado(estado, "crear_cita", {
        "nombre": flow.nombre, "fecha": flow.fecha, "hora": flow.hora,
        "servicio": flow.servicio,
    }, {"ok": False, "pendiente_de_confirmacion": True})
    reserva.guardar("demo", numero, estado)
    assert resumen() is True
    identidad = botones[-1]["buttons"][0][0]
    def limpiar_operacion():
        with db._get_db_connection() as conn:
            conn.execute("DELETE FROM booking_operations WHERE cliente_id='demo' AND operation_key=?",
                         ("wa:" + identidad.partition(":")[2],))
            conn.commit()
    request.addfinalizer(limpiar_operacion)
    for _ in range(2):
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id="PN", from_number=numero,
            incoming_text="Confirmar", interactive_id=identidad, request=None))
    assert len(citas()) == 1 and len(proveedores) == 1


def test_aclaracion_con_estado_antiguo_no_borra_un_rechazo_nuevo(api_module):
    import uuid
    from backend import conversation_state, reserva
    numero = uuid.uuid4().hex
    viejo = reserva.cargar("demo", numero)
    actual = reserva.cargar("demo", numero)
    reserva.anotar_resultado(actual, "crear_cita", {}, {"ok": False})
    reserva.guardar("demo", numero, actual)
    try:
        reserva.anotar_resultado(viejo, "crear_cita", {}, {"pendiente_de_confirmacion": True})
        with pytest.raises(conversation_state.ConversationStateConflict):
            reserva.guardar("demo", numero, viejo)
        assert reserva.cargar("demo", numero).creacion_rechazada_en > 0
    finally:
        reserva.olvidar("demo", numero)


def test_gestion_nueva_limpia_rechazo_pero_no_inventa_confirmacion(api_module):
    from backend import reserva
    estado = reserva.Estado()
    reserva.anotar_resultado(estado, "crear_cita", {}, {"ok": False})
    reserva.empezar_otra_gestion(estado)
    assert estado.creacion_rechazada_en == 0
    assert not estado.esperando_confirmacion
    assert not estado.confirmacion_reserva_json


def test_rechazo_no_borra_una_operacion_ya_aceptada(api_module):
    from backend import reserva
    estado = reserva.Estado()
    identidad = reserva.preparar_confirmacion_reserva(estado, {"servicio": "Corte"})
    assert reserva.avanzar_confirmacion_reserva(estado, identidad, "ofrecida")
    assert reserva.avanzar_confirmacion_reserva(estado, identidad, "aceptada")
    anterior = estado.confirmacion_reserva_json
    reserva.anotar_resultado(estado, "crear_cita", {}, {"ok": False})
    assert estado.confirmacion_reserva_json == anterior
    assert reserva.creacion_requiere_aclaracion(estado)


@pytest.mark.parametrize("accion", ["cancelar", "reprogramar"])
def test_rechazo_de_creacion_no_invalida_otra_gestion_ofrecida(api_module, accion):
    from backend import reserva
    estado = reserva.Estado()
    identidad = reserva.preparar_confirmacion_reserva(estado, {"accion": accion, "codigo": "R-prueba"})
    assert reserva.avanzar_confirmacion_reserva(estado, identidad, "ofrecida")
    anterior = estado.confirmacion_reserva_json
    reserva.anotar_resultado(estado, "crear_cita", {}, {"ok": False})
    assert estado.confirmacion_reserva_json == anterior


def test_rechazo_durante_consulta_de_agenda_impide_publicar_resumen(canal, monkeypatch):
    from backend import booking, messaging, reserva, whatsapp
    numero, responder, citas, textos, proveedores = canal
    preparar = booking._prepare_booking_creation
    botones = []

    async def rechazar_durante_consulta(*args, **kwargs):
        preparada = await preparar(*args, **kwargs)
        estado = reserva.cargar("demo", numero)
        reserva.anotar_resultado(estado, "crear_cita", {}, {"ok": False})
        reserva.guardar("demo", numero, estado)
        return preparada

    async def enviar(**kwargs):
        botones.append(kwargs)
        return True

    monkeypatch.setattr(booking, "_prepare_booking_creation", rechazar_durante_consulta)
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    assert not asyncio.run(whatsapp._wa_send_booking_summary(
        cliente_id="demo", phone_number_id="PN", to_number=numero,
        flow=whatsapp._wa_get_flow("demo", numero)))
    responder()
    assert not botones and not citas() and not proveedores


@pytest.mark.parametrize("como", ["lista", "hablado"])
def test_elegir_servicio_en_la_lista_resuelve_el_rechazo_anterior(canal, monkeypatch, como):
    """Revisión de Claude a 952ae99. Si el asistente frena la cita y la conversación sigue por las
    listas (negocio guiado, o el agente no contesta y se pregunta a mano), la clienta elige el
    servicio, el día y la hora y, al dar su nombre, no le llegaba nada: el resumen seguía bloqueado
    por el rechazo anterior y el canal se callaba. Elegir el servicio en ese paso es la aclaración."""
    from backend import booking, messaging, reserva, whatsapp
    numero, responder, citas, textos, proveedores = canal
    flow = whatsapp._wa_get_flow("demo", numero)
    elegido = dict(fecha=flow.fecha, hora=flow.hora, employee_id=flow.employee_id,
                   employee_name=flow.employee_name)
    estado = reserva.cargar("demo", numero)
    reserva.anotar_resultado(estado, "crear_cita", {}, {"ok": False, "error": "Falta aclarar el servicio"})
    reserva.guardar("demo", numero, estado)
    servicios = booking._public_services_for_booking("demo")
    assert servicios, "el negocio de prueba no tiene servicios que elegir"
    servicio = servicios[0]
    botones = []

    async def enviar(**kw):
        botones.append(kw)
        return True

    async def lista(**kw):
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    monkeypatch.setattr(messaging, "_send_whatsapp_list", lista)

    def escribe(texto, iid=""):
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id="PN", from_number=numero,
            incoming_text=texto, interactive_id=iid, request=None))

    nombre_servicio = servicio.get("nombre") or servicio.get("name")
    flow.flow = "booking_service"
    if como == "lista":
        escribe(nombre_servicio, "svc_%s" % (servicio.get("id") or servicio.get("slug")))
    else:
        # Conversacional con el agente sin contestar: se pregunta a mano y lo resuelve el catálogo.
        from backend import intents
        monkeypatch.setattr(whatsapp, "_wa_modo_conversacional", lambda config: True)
        monkeypatch.setattr(intents, "resolver_servicio", lambda *a, **k: {
            "servicio": nombre_servicio, "pregunta": "", "confirmacion": ""})
        escribe(nombre_servicio)
    flow = whatsapp._wa_get_flow("demo", numero)
    assert flow.servicio, "la lista no dejó elegido el servicio"
    # Profesional, día y hora salen de las listas siguientes; se dejan como las dejan ellas.
    for clave, valor in elegido.items():
        setattr(flow, clave, valor)
    flow.flow = "booking_name"
    escribe("Ana Prueba Ruiz")
    assert botones, "eligió todo en las listas y no le llegó el resumen: %s" % textos[-2:]
