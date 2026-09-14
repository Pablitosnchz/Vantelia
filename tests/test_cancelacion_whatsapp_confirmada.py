"""Una cancelación requiere aceptar la cita concreta que el canal pudo enviar."""
import asyncio
import uuid

import pytest


@pytest.fixture
def gestion(api_module, monkeypatch):
    from backend import whatsapp, booking, messaging, inbox
    nucleo = booking._cancel_booking_by_code
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
    botones, textos, registros, canceladas = [], [], [], []
    async def lookup(tenant, code, **kw):
        fila = filas.get(code)
        if not fila or fila["cliente_id"] != tenant:
            return None, {"ok": False, "error": "Cita inexistente"}
        if not (kw.get("trusted_phone") == fila["telefono"] or
                (kw.get("email") and kw["email"] == fila["email"])):
            return None, {"ok": False, "needs_verification": True, "error": "Verifica la reserva"}
        return dict(fila), None
    async def cancelar(tenant, code, **kw):
        canceladas.append(code)
        filas[code]["status"] = "cancelled"
        return {"ok": True}
    async def enviar(**kw):
        botones.append(kw)
        return True
    async def texto(**kw):
        textos.append(kw["text"])
        return True
    monkeypatch.setattr(booking, "_lookup_and_verify_booking_by_code", lookup)
    monkeypatch.setattr(booking, "_cancel_booking_by_code", cancelar)
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(inbox, "bot_is_muted", lambda *a: False)
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **kw: registros.append(kw))
    def recibir(text="", iid=""):
        asyncio.run(whatsapp._handle_whatsapp_message(cliente_id="demo", phone_number_id="PN",
            from_number=numero, incoming_text=text, interactive_id=iid, request=None))
    def ofrecer(code="R-123456"):
        recibir("Cancelar " + code, "menu_cancelar_cita")
        return botones[-1]["buttons"][0][0] if botones else "cancel_yes"
    yield dict(numero=numero, filas=filas, botones=botones, textos=textos,
        registros=registros, canceladas=canceladas, recibir=recibir, ofrecer=ofrecer, nucleo=nucleo,
        nucleo_stub=cancelar)
    whatsapp._wa_clear_flow("demo", numero)


def test_codigo_verificado_ofrece_sin_cancelar(gestion):
    g = gestion
    boton = g["ofrecer"]()
    assert g["canceladas"] == []
    assert boton.startswith("cancel_yes:")
    assert "R-123456" in g["botones"][-1]["body"]


def test_boton_antiguo_no_autoriza_otra_cita(gestion):
    g = gestion
    viejo = g["ofrecer"]()
    nuevo = g["ofrecer"]("R-654321")
    g["recibir"](iid=viejo)
    assert g["canceladas"] == []
    g["recibir"](iid=nuevo)
    assert g["canceladas"] == ["R-654321"]


def test_reinicio_recupera_identidad_sin_usar_datos_del_worker(gestion, monkeypatch):
    from backend import appstate
    g = gestion
    boton = g["ofrecer"]()
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    g["recibir"](iid=boton)
    assert g["canceladas"] == ["R-123456"]


def test_si_sin_identidad_no_es_aceptacion(gestion):
    g = gestion
    g["ofrecer"]()
    g["recibir"]("sí")
    g["recibir"](iid="cancel_yes")
    assert g["canceladas"] == []


def test_cita_cambiada_desde_el_portal_exige_nueva_oferta(gestion):
    g = gestion
    boton = g["ofrecer"]()
    g["filas"]["R-123456"]["booking_time"] = "12:00"
    g["recibir"](iid=boton)
    assert g["canceladas"] == []
    assert any("cambi" in t.lower() for t in g["textos"])


def test_meta_rechaza_oferta_sin_historial_ni_autorizacion(gestion, monkeypatch):
    from backend import messaging
    g = gestion
    async def falla(**kw):
        g["botones"].append(kw)
        return False
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", falla)
    boton = g["ofrecer"]()
    assert g["registros"] == []
    g["recibir"](iid=boton)
    assert g["canceladas"] == []


def test_fallo_del_nucleo_no_afirma_cancelacion(gestion, monkeypatch):
    from backend import booking, reserva
    g = gestion
    async def falla(*args, **kw):
        return {"ok": False, "error": "El proveedor no responde"}
    monkeypatch.setattr(booking, "_cancel_booking_by_code", falla)
    boton = g["ofrecer"]()
    g["recibir"](iid=boton)
    assert not reserva.cargar("demo", g["numero"]).hecho
    assert any("proveedor" in t for t in g["textos"])
    assert not any("queda cancelada" in r.get("respuesta", "") for r in g["registros"])


def test_resultado_no_enviado_no_se_registra(gestion, monkeypatch):
    from backend import messaging
    g = gestion
    boton = g["ofrecer"]()
    g["registros"].clear()
    async def falla(**kw): return False
    monkeypatch.setattr(messaging, "_send_whatsapp_text", falla)
    g["recibir"](iid=boton)
    assert g["canceladas"] == ["R-123456"]
    assert g["registros"] == []


def test_reinicio_tras_ejecutar_recupera_resultado_sin_repetir(gestion, monkeypatch):
    from backend import messaging, appstate, reserva
    g = gestion
    boton = g["ofrecer"]()
    async def falla(**kw): return False
    enviar = messaging._send_whatsapp_text
    monkeypatch.setattr(messaging, "_send_whatsapp_text", falla)
    g["recibir"](iid=boton)
    assert reserva.cargar("demo", g["numero"]).cancelada
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviar)
    g["recibir"](iid=boton)
    assert g["canceladas"] == ["R-123456"]
    assert "R-123456 está cancelada" in g["textos"][-1]


def test_aceptacion_se_persiste_antes_del_nucleo_y_repeticion_no_ejecuta(gestion, monkeypatch):
    from backend import whatsapp, booking, reserva
    g = gestion
    boton = g["ofrecer"]()
    async def cancelar(*args, **kw):
        p = reserva.leer_confirmacion_reserva(reserva.cargar("demo", g["numero"]))
        assert p["estado"] == "aceptada"
        g["canceladas"].append(args[1])
        await whatsapp._handle_whatsapp_message(cliente_id="demo", phone_number_id="PN",
            from_number=g["numero"], incoming_text="", interactive_id=boton, request=None)
        g["filas"]["R-123456"]["status"] = "cancelled"
        return {"ok": True}
    monkeypatch.setattr(booking, "_cancel_booking_by_code", cancelar)
    g["recibir"](iid=boton)
    assert g["canceladas"] == ["R-123456"]


def test_rechazar_descarta_la_propuesta_sin_cancelar(gestion):
    g = gestion
    boton = g["ofrecer"]()
    g["recibir"](iid=g["botones"][-1]["buttons"][1][0])
    g["recibir"](iid=boton)
    assert g["canceladas"] == []


def test_acuse_tardio_no_resucita_la_oferta(gestion, monkeypatch):
    from backend import messaging, reserva
    g = gestion
    async def enviar(**kw):
        g["botones"].append(kw)
        reserva.olvidar("demo", g["numero"])
        return True
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    boton = g["ofrecer"]()
    g["recibir"](iid=boton)
    assert g["canceladas"] == []


def test_contacto_revalidado_antes_de_cancelar(gestion):
    g = gestion
    boton = g["ofrecer"]()
    g["filas"]["R-123456"]["telefono"] = "34900000000"
    g["recibir"](iid=boton)
    assert g["canceladas"] == []


def test_verificacion_recuperada_tras_reinicio_no_cancela_hasta_aceptar(gestion, monkeypatch):
    from backend import appstate
    g = gestion
    g["filas"]["R-123456"].update(telefono="34900000000", email="qa@example.invalid")
    g["ofrecer"]()
    assert not g["botones"]
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    g["recibir"]("qa@example.invalid")
    assert g["canceladas"] == []
    g["recibir"](iid=g["botones"][-1]["buttons"][0][0])
    assert g["canceladas"] == ["R-123456"]


def test_excepcion_despues_de_aceptar_no_habilita_otro_intento(gestion, monkeypatch):
    from backend import booking
    g = gestion
    boton = g["ofrecer"]()
    async def incierta(*args, **kw):
        g["canceladas"].append(args[1])
        raise RuntimeError("resultado desconocido")
    monkeypatch.setattr(booking, "_cancel_booking_by_code", incierta)
    g["recibir"](iid=boton)
    g["recibir"](iid=boton)
    assert g["canceladas"] == ["R-123456"]
    assert not any("está cancelada" in t for t in g["textos"])


def test_boton_caducado_no_cancela(gestion):
    import json
    from backend import reserva
    g = gestion
    boton = g["ofrecer"]()
    estado = reserva.cargar("demo", g["numero"])
    propuesta = json.loads(estado.confirmacion_reserva_json)
    propuesta["creada"] -= reserva.CADUCA_EN + 1
    estado.confirmacion_reserva_json = json.dumps(propuesta)
    reserva.guardar("demo", g["numero"], estado)
    g["recibir"](iid=boton)
    assert g["canceladas"] == []


def test_otro_tenant_o_telefono_no_reutiliza_la_aceptacion(gestion):
    from backend import whatsapp
    g = gestion
    boton = g["ofrecer"]()
    for tenant, numero in [("otro", g["numero"]), ("demo", "34900000000")]:
        asyncio.run(whatsapp._wa_responder_cancelacion(cliente_id=tenant, phone_number_id="PN",
            from_number=numero, iid=boton, request=None))
    assert g["canceladas"] == []


def test_confirmar_creacion_no_acepta_snapshot_de_cancelacion(gestion, monkeypatch):
    from backend import whatsapp, reserva
    g = gestion
    boton = g["ofrecer"]()
    llamadas = []
    async def crear(**kw): llamadas.append(kw)
    monkeypatch.setattr(whatsapp, "_wa_create_booking", crear)
    g["recibir"](iid=boton.replace("cancel_yes:", "confirm_yes:"))
    # Otro worker aún cree estar delante del resumen de creación.
    whatsapp._wa_get_flow("demo", g["numero"]).flow = "booking_confirm"
    g["recibir"]("sí")
    assert llamadas == []
    assert g["canceladas"] == []
    assert reserva.leer_confirmacion_reserva(reserva.cargar("demo", g["numero"]))["estado"] == "ofrecida"


def test_cancelar_no_acepta_snapshot_de_creacion(gestion):
    from backend import whatsapp, reserva
    g = gestion
    estado = reserva.cargar("demo", g["numero"])
    flow = whatsapp._wa_get_flow("demo", g["numero"])
    identidad = reserva.preparar_confirmacion_reserva(estado, whatsapp._wa_datos_del_resumen(flow))
    reserva.avanzar_confirmacion_reserva(estado, identidad, "ofrecida")
    reserva.guardar("demo", g["numero"], estado)
    g["recibir"](iid="cancel_yes:" + identidad)
    assert g["canceladas"] == []
    assert reserva.leer_confirmacion_reserva(reserva.cargar("demo", g["numero"]))["estado"] == "ofrecida"


@pytest.mark.parametrize("accion", ["reservar", "cancelar"])
def test_cancelacion_nueva_no_sustituye_operacion_aceptada_pendiente(gestion, accion):
    from backend import whatsapp, reserva
    g = gestion
    if accion == "cancelar":
        g["ofrecer"]()
    estado = reserva.cargar("demo", g["numero"])
    if accion == "reservar":
        estado.intencion = "reservar"
        flow = whatsapp._wa_get_flow("demo", g["numero"])
        identidad = reserva.preparar_confirmacion_reserva(estado, whatsapp._wa_datos_del_resumen(flow))
        reserva.avanzar_confirmacion_reserva(estado, identidad, "ofrecida")
    else:
        identidad = reserva.leer_confirmacion_reserva(estado)["id"]
    reserva.avanzar_confirmacion_reserva(estado, identidad, "aceptada")
    if accion == "reservar":
        reserva.vincular_operacion_confirmada(estado, identidad, "a" * 64)
    reserva.guardar("demo", g["numero"], estado)
    g["ofrecer"]("R-654321")
    actual = reserva.leer_confirmacion_reserva(reserva.cargar("demo", g["numero"]))
    assert actual["id"] == identidad
    assert actual["estado"] == "aceptada"
    assert g["canceladas"] == []
    assert "pendiente" in g["textos"][-1]


def test_carrera_entre_reconsulta_y_nucleo_no_cancela_otra_version(gestion, monkeypatch):
    from backend import booking
    g = gestion
    boton = g["ofrecer"]()
    async def nucleo_con_cambio(*args, **kw):
        g["filas"]["R-123456"]["booking_time"] = "15:30"
        return await g["nucleo"](*args, **kw)
    async def ejecutar(*args, **kw):
        g["canceladas"].append(args[0]["booking_code"])
        return args[0]
    monkeypatch.setattr(booking, "_cancel_booking_by_code", nucleo_con_cambio)
    monkeypatch.setattr(booking, "_cancel_booking_core", ejecutar)
    g["recibir"](iid=boton)
    assert g["canceladas"] == []
    assert "ha cambiado" in g["textos"][-1]


@pytest.mark.parametrize("tipo_error", ["runtime", "http"])
@pytest.mark.parametrize("db_cancelada", [True, False])
def test_excepcion_del_nucleo_conserva_aceptacion_y_recupera_sin_repetir(
        gestion, monkeypatch, tipo_error, db_cancelada):
    from backend import booking, reserva
    from fastapi import HTTPException
    g = gestion
    boton = g["ofrecer"]()
    async def ejecutar(fila, **kw):
        # El proveedor pudo aceptar; la escritura posterior o el audit fallan.
        g["canceladas"].append(fila["booking_code"])
        if db_cancelada:
            g["filas"][fila["booking_code"]]["status"] = "cancelled"
        if tipo_error == "http":
            raise HTTPException(status_code=503, detail="Fallo después del proveedor")
        raise RuntimeError("Fallo después del proveedor")
    monkeypatch.setattr(booking, "_cancel_booking_by_code", g["nucleo"])
    monkeypatch.setattr(booking, "_cancel_booking_core", ejecutar)
    g["recibir"](iid=boton)
    propuesta = reserva.leer_confirmacion_reserva(reserva.cargar("demo", g["numero"]))
    assert propuesta and propuesta["estado"] == "aceptada"
    assert not any("está cancelada" in t for t in g["textos"])
    g["recibir"](iid=boton)
    assert g["canceladas"] == ["R-123456"]
    assert ("está cancelada" in g["textos"][-1]) == db_cancelada


@pytest.mark.parametrize("salida", ["menú", "hola"])
@pytest.mark.parametrize("otra_reserva", [False, True])
def test_salir_del_flujo_no_borra_cancelacion_de_resultado_desconocido(
        gestion, monkeypatch, salida, otra_reserva):
    from backend import booking, reserva, whatsapp
    g = gestion
    boton = g["ofrecer"]()
    async def incierta(*args, **kw):
        g["canceladas"].append(args[1])
        return {"ok": False, "resultado_desconocido": True}
    async def menu(**kw): return True
    monkeypatch.setattr(booking, "_cancel_booking_by_code", incierta)
    monkeypatch.setattr(whatsapp, "_wa_send_main_menu", menu)
    g["recibir"](iid=boton)
    g["recibir"](salida)
    if otra_reserva:
        g["recibir"]("Agendar cita", "menu_agendar")
        assert reserva.leer_confirmacion_reserva(reserva.cargar("demo", g["numero"]))["estado"] == "aceptada"
    g["ofrecer"]()
    g["recibir"](iid=g["botones"][-1]["buttons"][0][0])
    assert g["canceladas"] == ["R-123456"]
    assert reserva.leer_confirmacion_reserva(reserva.cargar("demo", g["numero"]))["estado"] == "aceptada"


@pytest.mark.parametrize("hecha", [False, True])
def test_saludo_tras_humano_solo_llega_al_agente_con_operacion_terminada(gestion, monkeypatch, hecha):
    from backend import reserva, whatsapp
    g = gestion
    boton = g["ofrecer"]()
    estado = reserva.cargar("demo", g["numero"])
    reserva.avanzar_confirmacion_reserva(estado, boton.split(":")[1], "aceptada")
    estado.hecho = hecha
    estado.cancelada = hecha
    reserva.guardar("demo", g["numero"], estado)
    turnos = []
    async def agente(**kw):
        turnos.append(kw["incoming_text"])
        return True
    monkeypatch.setattr(whatsapp, "_wa_modo_conversacional", lambda *args: True)
    monkeypatch.setattr(whatsapp, "_wa_la_ha_atendido_una_persona", lambda *args: True)
    monkeypatch.setattr(whatsapp, "_wa_turno_del_agente", agente)
    g["recibir"]("hola")
    assert turnos == (["hola"] if hecha else [])
    if not hecha:
        assert "pendiente" in g["textos"][-1]
        assert reserva.leer_confirmacion_reserva(reserva.cargar("demo", g["numero"]))["estado"] == "aceptada"


def _cancelacion_sin_resultado(g, monkeypatch):
    """Acepta la cancelación y el núcleo no sabe si se hizo: la cita sigue en pie."""
    from backend import booking
    boton = g["ofrecer"]()
    async def incierta(*args, **kw):
        g["canceladas"].append(args[1])
        return {"ok": False, "resultado_desconocido": True}
    monkeypatch.setattr(booking, "_cancel_booking_by_code", incierta)
    g["recibir"](iid=boton)
    assert g["filas"]["R-123456"]["status"] == "confirmed"
    return boton


def _pasan_minutos(monkeypatch, minutos):
    from backend import whatsapp
    reloj = whatsapp.time.time
    ahora = reloj()
    monkeypatch.setattr(whatsapp.time, "time", lambda: ahora + minutos * 60)


def test_cancelacion_sin_resultado_se_vuelve_a_ofrecer_pasado_el_margen(gestion, monkeypatch):
    """Fase 4, 14-sep-2026: el mismo atasco que tenía la creación. Pasados 15 min sin webhook la
    cita sigue en pie y la clienta se quedaba en «contacta con el negocio». Se le vuelve a enseñar
    la cita para que confirme; nunca se cancela sola."""
    from backend import booking, booking_operations
    g = gestion
    boton = _cancelacion_sin_resultado(g, monkeypatch)
    intentos = list(g["canceladas"])
    monkeypatch.setattr(booking_operations, "_booking_has_webhook", lambda *a: False)
    ofertas = len(g["botones"])
    _pasan_minutos(monkeypatch, 16)
    g["recibir"](iid=boton)
    assert g["canceladas"] == intentos, "no se cancela sola: vuelve a pedir confirmacion"
    assert len(g["botones"]) == ofertas + 1, "no volvio a ensenar la cita"
    nuevo = g["botones"][-1]["buttons"][0][0]
    assert nuevo.startswith("cancel_yes:") and nuevo != boton
    aviso = g["textos"][-1].lower()
    assert "no lleg" in aviso and "contacta con el negocio" not in aviso, g["textos"][-1]
    monkeypatch.setattr(booking, "_cancel_booking_by_code", g["nucleo_stub"])
    g["recibir"](iid=nuevo)
    assert g["filas"]["R-123456"]["status"] == "cancelled"


@pytest.mark.parametrize("minutos,webhook", [(10, False), (16, True)])
def test_cancelacion_sin_resultado_reciente_o_con_webhook_sigue_pendiente(gestion, monkeypatch, minutos, webhook):
    """Controles: antes del margen otro proceso podría estar terminándola; con webhook el resultado
    puede llegar tarde. En los dos casos no se vuelve a ofrecer."""
    from backend import booking_operations
    g = gestion
    boton = _cancelacion_sin_resultado(g, monkeypatch)
    monkeypatch.setattr(booking_operations, "_booking_has_webhook", lambda *a: webhook)
    ofertas = len(g["botones"])
    _pasan_minutos(monkeypatch, minutos)
    g["recibir"](iid=boton)
    assert len(g["botones"]) == ofertas
    assert any("contacta con el negocio" in t.lower() for t in g["textos"][-1:])


def test_volver_a_pedir_cancelar_pasado_el_margen_no_se_bloquea(gestion, monkeypatch):
    from backend import booking_operations
    g = gestion
    _cancelacion_sin_resultado(g, monkeypatch)
    monkeypatch.setattr(booking_operations, "_booking_has_webhook", lambda *a: False)
    ofertas = len(g["botones"])
    _pasan_minutos(monkeypatch, 16)
    g["recibir"]("Cancelar R-123456", "menu_cancelar_cita")
    assert len(g["botones"]) == ofertas + 1, "sigue bloqueada por la aceptacion antigua"
    assert not any("pendiente" in t for t in g["textos"][-1:])
