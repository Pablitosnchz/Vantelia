# -*- coding: utf-8 -*-
"""Por WhatsApp, cambiar la cita hablando con el asistente exige aceptar el cambio concreto.

POR QUE EXISTE
--------------
15-sep-2026. Crear y cancelar ya pedían aceptar un resumen guardado, pero el agente
conversacional (el que usa el salón de Alicia) movía la cita en cuanto llamaba a
`reprogramar_cita`: sin resumen, sin botón. Decisiones de Pablo: también cuando cambia el
servicio; se acepta con el botón o con un «sí» escrito a ese cambio; solo en WhatsApp (el chat
de la web y la voz siguen como estaban, que tampoco confirman al crear).

La herramienta comprueba la cita, el día, la hora y el hueco, pero no mueve: devuelve el cambio
pendiente. WhatsApp lo enseña con los mismos botones que el flujo guiado
(`_wa_ofrecer_reprogramacion`) y solo el botón o el «sí» a ese resumen lo ejecutan.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

FILA = dict(id="bk_agente_1", cliente_id="demo", booking_code="R-123456", nombre="Ana Ruiz Perez", email="",
            telefono="34600111222", servicio="Corte", notas="", booking_date="2099-09-15", booking_time="10:00",
            employee_id="", employee_name="", location_id="", status="confirmed", timezone="Europe/Madrid",
            start_at="", end_at="")


# ─── La herramienta ────────────────────────────────────────────────────────

@pytest.fixture
def agenda_simulada(api_module, monkeypatch):  # noqa: F811
    from backend import booking, voice

    fila = dict(FILA)
    guardados, libre = [], {"si": True}

    async def buscar(cliente_id, codigo, **kw):
        return dict(fila), None

    async def hueco(cliente_id, row, fecha, hora, **kw):
        return libre["si"]

    async def actualizar(row, payload, request, **kw):
        guardados.append((payload.fecha, payload.hora, payload.servicio))
        return {"ok": True}

    monkeypatch.setattr(voice, "_voice_lookup_for_mutation", buscar)
    monkeypatch.setattr(booking, "_reschedule_slot_is_free", hueco)
    monkeypatch.setattr(booking, "_update_booking_details", actualizar)
    return dict(fila=fila, guardados=guardados, libre=libre)


def _reprogramar(remate_manual, **argumentos):
    from backend import agent

    datos = {"codigo_reserva": "R-123456", "fecha": "2099-09-20", "hora": "12:00"}
    datos.update(argumentos)
    return asyncio.run(agent._ejecutar("demo", "reprogramar_cita", datos, telefono="34600111222",
                                       remate_manual=remate_manual))


def test_por_whatsapp_la_herramienta_no_mueve_la_cita(agenda_simulada):
    resultado = _reprogramar(True)
    assert agenda_simulada["guardados"] == [], "movio la cita sin que la clienta aceptara el cambio"
    assert resultado.get("pendiente_de_confirmacion") is True, resultado
    assert resultado["cambio"] == {"codigo": "R-123456", "fecha": "2099-09-20", "hora": "12:00",
                                   "servicio": "", "telefono": "", "email": ""}
    assert resultado.get("ok") is False, "un ok haria creer al agente que ya esta cambiada"


def test_el_cambio_de_servicio_tambien_queda_pendiente(agenda_simulada):
    resultado = _reprogramar(True, servicio="Mechas")
    assert agenda_simulada["guardados"] == []
    assert resultado["cambio"]["servicio"] == "Mechas", resultado


def test_sin_hueco_no_se_ofrece_el_cambio(agenda_simulada):
    agenda_simulada["libre"]["si"] = False
    resultado = _reprogramar(True)
    assert not resultado.get("pendiente_de_confirmacion") and resultado.get("ok") is False, resultado
    assert agenda_simulada["guardados"] == []


def test_mismo_dia_y_hora_no_es_un_cambio_que_ofrecer(agenda_simulada):
    resultado = _reprogramar(True, fecha="2099-09-15", hora="10:00")
    assert not resultado.get("pendiente_de_confirmacion"), resultado


def test_una_cita_cancelada_no_se_ofrece_mover(agenda_simulada):
    agenda_simulada["fila"]["status"] = "cancelled"
    resultado = _reprogramar(True)
    assert not resultado.get("pendiente_de_confirmacion"), resultado
    assert agenda_simulada["guardados"] == []


def test_el_chat_de_la_web_sigue_moviendola_como_antes(agenda_simulada):
    """Decisión de Pablo: solo WhatsApp. Sin `remate_manual` la herramienta mueve como siempre."""
    resultado = _reprogramar(False)
    assert resultado.get("ok") is True, resultado
    assert agenda_simulada["guardados"] == [("2099-09-20", "12:00", "Corte")]


def test_el_estado_guarda_el_cambio_aparte_de_la_creacion(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado()
    cambio = {"codigo": "R-123456", "fecha": "2099-09-20", "hora": "12:00", "servicio": "",
              "telefono": "", "email": ""}
    reserva.anotar_resultado(estado, "reprogramar_cita",
                             {"codigo_reserva": "R-123456", "fecha": "2099-09-20", "hora": "12:00"},
                             {"ok": False, "pendiente_de_confirmacion": True, "cambio": cambio})
    assert json.loads(estado.cambio_pendiente_json) == cambio
    assert estado.intencion == "reprogramar" and estado.codigo == "R-123456"
    assert not estado.esperando_confirmacion, "encenderia el resumen de CREAR una cita"
    assert reserva.tool_que_remata(estado) == "", "obligaria a llamar otra vez y repetir el resumen"


# ─── WhatsApp ──────────────────────────────────────────────────────────────

@pytest.fixture
def canal(api_module, monkeypatch):  # noqa: F811
    from backend import agent, appstate, booking, inbox, messaging, reserva, whatsapp

    numero = "346" + str(uuid.uuid4().int % 100000000).zfill(8)
    fila = dict(FILA, telefono=numero)
    botones, textos, registros, movidas, al_agente = [], [], [], [], []
    propone = {"cambio": None, "texto": "Te paso el cambio para que lo confirmes."}

    async def lookup(tenant, code, **kw):
        if code != fila["booking_code"] or kw.get("trusted_phone") != numero:
            return None, {"ok": False, "error": "Cita inexistente"}
        return dict(fila), None

    async def mover(tenant, code, fecha, hora, **kw):
        esperado = kw.get("expected_snapshot")
        if esperado is not None and (booking._booking_cancellation_snapshot(fila)
                                     != booking._booking_cancellation_snapshot(esperado)):
            return {"ok": False, "cita_cambiada": True, "error": "La cita ha cambiado desde el resumen."}
        movidas.append((code, fecha, hora, kw.get("servicio", "")))
        fila.update(booking_date=fecha, booking_time=hora)
        if kw.get("servicio"):
            fila["servicio"] = kw["servicio"]
        return {"ok": True, "codigo_reserva": code, "fecha": fecha, "hora": hora}

    async def hueco_libre(*a, **kw):
        return True

    async def enviar(**kw):
        botones.append(kw)
        return True

    async def texto(**kw):
        textos.append(kw["text"])
        return True

    def registrar(**kw):
        registros.append(kw)
        return "sesion-agente"

    def ultimo_enviado(cliente_id, session_id):
        # Lo mismo que lee la base de verdad: la etiqueta del ULTIMO mensaje del asistente.
        enviados = [r for r in registros if r.get("respuesta")]
        return str(enviados[-1].get("intent") or "") if enviados else ""

    async def responder(cliente_id, mensaje, **kw):
        # El agente de verdad llama a la tool y anota lo que devuelve: aqui se simula
        # solo el modelo, con el mismo resultado que da `agent._proponer_cambio_de_cita`.
        al_agente.append(mensaje)
        if propone["cambio"]:
            estado = reserva.cargar(cliente_id, numero)
            reserva.anotar_resultado(estado, "reprogramar_cita", {}, {
                "ok": False, "pendiente_de_confirmacion": True, "cambio": dict(propone["cambio"])})
            reserva.guardar(cliente_id, numero, estado)
            propone["cambio"] = None
        return propone["texto"], False

    async def sin_resumen(**kw):
        return False

    monkeypatch.setattr(booking, "_lookup_and_verify_booking_by_code", lookup)
    monkeypatch.setattr(booking, "_reschedule_booking_by_code", mover)
    monkeypatch.setattr(booking, "_reschedule_slot_is_free", hueco_libre)
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(inbox, "bot_is_muted", lambda *a: False)
    monkeypatch.setattr(whatsapp, "_wa_registrar", registrar)
    monkeypatch.setattr(whatsapp, "_wa_ultimo_intent_enviado", ultimo_enviado, raising=False)
    monkeypatch.setattr(whatsapp, "_wa_cita_recien_hecha", lambda *a, **k: "")
    monkeypatch.setattr(whatsapp, "_wa_resumen_para_confirmar", sin_resumen)
    monkeypatch.setattr(agent, "disponible", lambda cliente_id: True)
    monkeypatch.setattr(agent, "responder", responder)

    flow = appstate.WAFlowState(cliente_id="demo", from_number=numero)
    appstate.whatsapp_flows[whatsapp._wa_flow_key("demo", numero)] = flow

    def turno(dicho, cambio=None, respuesta="Te paso el cambio para que lo confirmes."):
        propone.update(cambio=cambio, texto=respuesta)
        return asyncio.run(whatsapp._wa_turno_del_agente(
            cliente_id="demo", phone_number_id="PN", from_number=numero,
            incoming_text=dicho, flow=flow, config={}, request=None))

    def pulsar(iid):
        asyncio.run(whatsapp._handle_whatsapp_message(cliente_id="demo", phone_number_id="PN",
            from_number=numero, incoming_text="", interactive_id=iid, request=None))

    def cambio(fecha="2099-09-20", hora="12:00", servicio=""):
        return {"codigo": "R-123456", "fecha": fecha, "hora": hora, "servicio": servicio,
                "telefono": "", "email": ""}

    yield dict(flow=flow, fila=fila, botones=botones, textos=textos, movidas=movidas, numero=numero,
               al_agente=al_agente, turno=turno, pulsar=pulsar, cambio=cambio)
    whatsapp._wa_clear_flow("demo", numero)


def _si_cambiar(c):
    return c["botones"][-1]["buttons"][0][0]


def test_el_cambio_del_agente_se_ensena_con_botones_y_no_mueve(canal):
    c = canal
    assert c["turno"]("¿me la pasas al 20 a las 12?", c["cambio"]()) is True
    assert c["movidas"] == [], "movio la cita sin que aceptara el cambio"
    assert c["botones"] and _si_cambiar(c).startswith("resched_yes:")
    cuerpo = c["botones"][-1]["body"]
    assert "R-123456" in cuerpo and "12:00" in cuerpo and "10:00" in cuerpo
    assert c["textos"] == ["Te paso el cambio para que lo confirmes."], "la frase del agente va antes del resumen"
    assert c["flow"].flow == "agente", "lo que escriba despues tiene que seguir llegando al agente"


def test_el_boton_mueve_la_cita_una_vez(canal):
    c = canal
    c["turno"]("¿me la pasas al 20 a las 12?", c["cambio"]())
    boton = _si_cambiar(c)
    c["pulsar"](boton)
    c["pulsar"](boton)
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00", "")]
    assert "✅" in c["textos"][-1]


def test_un_si_escrito_al_resumen_lo_acepta(canal):
    c = canal
    c["turno"]("¿me la pasas al 20 a las 12?", c["cambio"]())
    c["turno"]("Sí")
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00", "")]
    assert c["al_agente"] == ["¿me la pasas al 20 a las 12?"], "el sí lo tiene que aceptar el código, no el modelo"


def test_si_con_otra_hora_lo_lleva_el_agente(canal):
    c = canal
    c["turno"]("¿me la pasas al 20 a las 12?", c["cambio"]())
    c["turno"]("si, pero mejor a las 18")
    assert c["movidas"] == []
    assert c["al_agente"][-1] == "si, pero mejor a las 18"


def test_un_si_a_otra_cosa_no_acepta_el_cambio(canal):
    c = canal
    c["turno"]("¿me la pasas al 20 a las 12?", c["cambio"]())
    c["turno"]("¿y a qué hora cerráis?", respuesta="Cerramos a las 20:00. ¿Te ayudo con algo más?")
    c["turno"]("si")
    assert c["movidas"] == [], "acepto el cambio con un sí que respondía a otra pregunta"
    assert c["al_agente"][-1] == "si"


def test_otro_cambio_invalida_el_boton_anterior(canal):
    c = canal
    c["turno"]("¿me la pasas al 20 a las 12?", c["cambio"]())
    viejo = _si_cambiar(c)
    c["turno"]("mejor a las 18", c["cambio"](hora="18:00"))
    nuevo = _si_cambiar(c)
    c["pulsar"](viejo)
    assert c["movidas"] == []
    c["pulsar"](nuevo)
    assert c["movidas"] == [("R-123456", "2099-09-20", "18:00", "")]


def test_cambiar_el_servicio_se_ensena_y_se_guarda_al_aceptar(canal):
    c = canal
    c["turno"]("mejor unas mechas", c["cambio"](servicio="Mechas"))
    cuerpo = c["botones"][-1]["body"]
    assert "Corte" in cuerpo and "Mechas" in cuerpo, cuerpo
    assert c["movidas"] == []
    c["pulsar"](_si_cambiar(c))
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00", "Mechas")]


def test_mantener_no_mueve(canal):
    c = canal
    c["turno"]("¿me la pasas al 20 a las 12?", c["cambio"]())
    boton = _si_cambiar(c)
    c["pulsar"](c["botones"][-1]["buttons"][1][0])
    c["pulsar"](boton)
    assert c["movidas"] == []


# ─── Revisión de Codex a c3aae1c ───────────────────────────────────────────

def test_si_corrigiendo_el_servicio_lo_lleva_el_agente(canal):
    """«sí, solo corte» a un cambio Corte → Mechas pasaba por un sí y cambiaba la cita a Mechas."""
    c = canal
    c["turno"]("mejor unas mechas", c["cambio"](servicio="Mechas"))
    c["turno"]("sí, solo corte")
    assert c["movidas"] == [], "acepto el cambio de servicio que ella estaba corrigiendo"
    assert c["al_agente"][-1] == "sí, solo corte"


def test_un_si_que_elige_lo_ofrecido_tambien_acepta(canal):
    """Medido con modelo real sobre cf58f52: con solo el «sí» a secas, «vale, la primera opción que me
    has dicho» volvía al agente y la cita se quedaba sin mover."""
    c = canal
    c["turno"]("cualquier otro hueco que tengas me vale", c["cambio"]())
    c["turno"]("vale, la primera opcion que me has dicho")
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00", "")]


def test_ensenar_el_resumen_no_borra_lo_que_sabe_el_agente(canal):
    """Si contesta otra cosa y el agente vuelve a proponer el cambio, el freno del día que nadie ha
    pedido no puede saltar porque al enseñar el resumen se borró que le daba igual el día."""
    from backend import reserva

    c = canal
    estado = reserva.cargar("demo", c["numero"])
    estado.dia_le_da_igual = True
    reserva.guardar("demo", c["numero"], estado)
    c["turno"]("cualquier otro hueco que tengas me vale", c["cambio"]())
    assert c["botones"], "no se ofreció el cambio"
    despues = reserva.cargar("demo", c["numero"])
    assert despues.dia_le_da_igual is True
    assert (despues.fecha, despues.hora, despues.intencion) == ("2099-09-20", "12:00", "reprogramar")


def test_pulsar_tres_veces_sigue_diciendo_que_esta_hecho(canal):
    """La segunda pulsación ve la cita ya movida y borraba el acuse: la tercera decía «ya no vigente»."""
    c = canal
    c["turno"]("¿me la pasas al 20 a las 12?", c["cambio"]())
    boton = _si_cambiar(c)
    for _ in range(3):
        c["pulsar"](boton)
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00", "")]
    assert "✅" in c["textos"][-1], c["textos"][-1]


def test_un_resumen_guardado_antes_del_servicio_sigue_valiendo(canal):
    """Un cambio ofrecido antes de desplegar no lleva `nuevo_servicio`: se acepta conservando el suyo."""
    from backend import reserva

    c = canal
    c["turno"]("¿me la pasas al 20 a las 12?", c["cambio"]())
    boton = _si_cambiar(c)
    estado = reserva.cargar("demo", c["numero"])
    propuesta = json.loads(estado.confirmacion_reserva_json)
    del propuesta["datos"]["nuevo_servicio"]
    estado.confirmacion_reserva_json = json.dumps(propuesta, ensure_ascii=True, sort_keys=True)
    reserva.guardar("demo", c["numero"], estado)
    c["pulsar"](boton)
    assert c["movidas"] == [("R-123456", "2099-09-20", "12:00", "")]


def test_el_hueco_del_servicio_nuevo_usa_la_duracion_de_su_profesional(api_module, monkeypatch):  # noqa: F811
    """Proponer y guardar tienen que medir igual: con la profesional de la cita (y su centro)."""
    from backend import agenda, booking

    empleada = {"id": "emp_centro", "location_id": "loc_b"}
    visto = {}

    def duracion(cliente_id, servicio, empleado=None):
        visto["empleada"] = empleado
        return 45

    async def hueco(cliente_id, fecha, hora, **kw):
        visto["minutos"] = kw.get("duration_minutes")
        return True

    monkeypatch.setattr(agenda, "_get_employee_row", lambda employee_id, cliente_id=None: empleada)
    monkeypatch.setattr(agenda, "_service_duration_minutes", duracion)
    monkeypatch.setattr(agenda, "_booking_slot_available_for_reschedule", hueco)
    fila = dict(FILA, employee_id="emp_centro")
    assert asyncio.run(booking._reschedule_slot_is_free("demo", fila, "2099-09-20", "12:00", servicio="Mechas"))
    assert visto == {"empleada": empleada, "minutos": 45}
