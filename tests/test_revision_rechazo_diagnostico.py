import asyncio
import copy
import types
from dataclasses import replace
import pytest

from test_alternativa_de_precio import politica, ofrecer
from conftest import DEFAULT_DEMO_CONFIG
from test_wa_flujo_cita_corto import poner_hueco_real_en_resumen


@pytest.fixture
def agenda_salon(vantelia_env_factory):
    config = {"salon": copy.deepcopy(DEFAULT_DEMO_CONFIG["demo"])}
    config["salon"]["booking"]["day_end"] = "18:00"
    return vantelia_env_factory(config)


@pytest.mark.parametrize("servicio", ["Pack mechas o balayage medio", "MECHAS O BALAYAGE MEDIO"])
def test_boton_no_no_reabre_diagnostico_al_llegar_al_resumen(agenda_salon, politica, monkeypatch, servicio):
    from backend import booking, reserva, whatsapp, messaging, appstate
    estado, propuesta = ofrecer()
    estado.servicio, estado.servicio_exacto = "Mechas o balayage medio", "Pack mechas o balayage medio"
    estado.propuesta_servicio = replace(estado.propuesta_servicio, servicio_origen="Mechas o balayage medio")
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    flow = appstate.WAFlowState(cliente_id="salon", from_number="persona")
    flow.flow, flow.servicio = "agente", servicio
    poner_hueco_real_en_resumen(flow)
    flow.nombre = "Ana Ruiz López"
    monkeypatch.setattr(whatsapp, "_wa_get_flow", lambda *a: flow)
    monkeypatch.setattr(whatsapp.inbox, "remember_inbound_number", lambda *a: None)
    monkeypatch.setattr(whatsapp.inbox, "bot_is_muted", lambda *a: False)
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **k: None)
    monkeypatch.setattr(booking, "renuncio_al_diagnostico_en_la_conversacion", lambda *a: False)
    async def enviar(**kw): return True
    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviar)
    resumenes = []
    async def botones(**kw): resumenes.append(kw); return True
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", botones)
    # Los dobles aceptan argumentos con nombre: el resumen les pasa los terminos
    # sellados (`minutos=`, `terms=`) y un `lambda *a` los rechazaba con TypeError,
    # que es un fallo del DOBLE, no del producto.
    monkeypatch.setattr(whatsapp, "_wa_duracion_del_servicio", lambda *a, **k: "")
    monkeypatch.setattr(whatsapp, "_wa_linea_de_recargo", lambda *a, **k: "")
    monkeypatch.setattr(booking, "aviso_de_fianza", lambda *a, **k: "")
    asyncio.run(whatsapp._handle_whatsapp_message(cliente_id="salon", phone_number_id="canal",
        from_number="persona", incoming_text="No, gracias", interactive_id="prop_rechaza_"+propuesta.id, request=None))
    assert estado.propuesta_servicio.estado == "rechazada", estado.propuesta_servicio
    estado.veces_sin_precio = 1
    asyncio.run(whatsapp._wa_send_booking_summary(cliente_id="salon", phone_number_id="canal",
        to_number="persona", flow=flow))
    assert any(b[0].startswith("confirm_yes") for mensaje in resumenes for b in mensaje["buttons"])
    assert estado.propuesta_servicio.id == propuesta.id
    assert estado.propuesta_servicio.estado == "rechazada"


@pytest.mark.parametrize("intencion", ["cancelar", "reprogramar"])
def test_cancelada_y_nueva_reserva_puede_ofrecer_sin_excepcion(politica, monkeypatch, intencion):
    from backend import reserva, whatsapp, messaging
    estado = reserva.Estado(intencion=intencion, cancelada=True, hecho=True, esperando_confirmacion=True,
                            servicio="Color", servicio_exacto="Color")
    async def enviar(**kw): return True
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    asyncio.run(whatsapp._wa_explicar_la_regla_del_precio(cliente_id="salon", phone_number_id="canal",
        to_number="persona", from_number="persona", estado=estado,
        freno={"reserva_esto_en_su_lugar":"Diagnóstico", "texto_del_negocio":"Te valoramos en persona"}))
    assert estado.intencion == "reservar"
    assert not estado.hecho
    assert estado.propuesta_servicio.estado == "ofrecida"
    assert estado.servicio_exacto == "Color"


def test_interactivo_rechazado_ofrece_texto_con_acuse(politica, monkeypatch):
    from backend import reserva, whatsapp, messaging
    estado = reserva.Estado(intencion="reservar", servicio="Color")
    async def botones(**kw): return False
    textos=[]
    async def texto(**kw): textos.append(kw["text"]); return True
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", botones)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    assert asyncio.run(whatsapp._wa_explicar_la_regla_del_precio(cliente_id="salon", phone_number_id="canal",
        to_number="persona", from_number="persona", estado=estado,
        freno={"reserva_esto_en_su_lugar":"Diagnóstico", "texto_del_negocio":"Te valoramos en persona"}))
    assert textos and "Diagnóstico" in textos[0]
    assert estado.propuesta_servicio.estado == "ofrecida"


def test_otra_regla_u_otro_tenant_no_heredan_la_negativa(politica):
    from backend import booking
    regla, _ = politica
    estado, propuesta = ofrecer()
    assert booking.contestar_alternativa_de_precio("salon", estado, propuesta.id, "rechaza")
    assert booking.rechazo_de_regla_de_precio("salon", estado, "Color")
    assert not booking.rechazo_de_regla_de_precio("otro", estado, "Color")
    regla["id"] = "otra-regla"
    assert not booking.rechazo_de_regla_de_precio("salon", estado, "Color")


def test_gestion_activa_no_se_convierte_en_reserva(politica, monkeypatch):
    from backend import reserva, whatsapp, messaging
    estado = reserva.Estado(intencion="reprogramar", servicio="Color", esperando_confirmacion=True)
    async def texto(**kw): return True
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    asyncio.run(whatsapp._wa_explicar_la_regla_del_precio(cliente_id="salon", phone_number_id="canal",
        to_number="persona", from_number="persona", estado=estado,
        freno={"reserva_esto_en_su_lugar":"Diagnóstico", "texto_del_negocio":"Te valoramos en persona"}))
    assert estado.intencion == "reprogramar"
    assert estado.propuesta_servicio is None


def test_sin_valoracion_en_el_centro_no_promete_otra_consulta(politica, monkeypatch):
    from backend import booking, reserva, whatsapp, messaging
    _, valoracion = politica
    consultas, textos = [], []
    def buscar(*a, **kw):
        centro = kw.get("location_id", "")
        consultas.append(centro)
        return {} if centro == "sur" else valoracion
    monkeypatch.setattr(booking, "_servicio_de_valoracion", buscar)
    monkeypatch.setattr(booking, "renuncio_al_diagnostico_en_la_conversacion", lambda *a: False)
    estado = reserva.Estado(intencion="reservar", servicio="Color", veces_sin_precio=1)
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    async def texto(**kw): textos.append(kw["text"]); return True
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    flow = types.SimpleNamespace(servicio="Color", from_number="persona", location_id="sur",
                                 fecha="2030-01-08", hora="10:00", flow="booking_confirm")
    assert asyncio.run(whatsapp._wa_freno_del_precio(cliente_id="salon", phone_number_id="canal",
        to_number="persona", flow=flow))
    assert consultas and set(consultas) == {"sur"}
    assert textos and "Voy a consultar" not in textos[-1]
    assert "centro" in textos[-1]
    assert estado.propuesta_servicio is None


@pytest.mark.parametrize("respuesta", ["acepta", "rechaza"])
def test_respuesta_con_datos_continua_sin_otro_turno(politica, monkeypatch, respuesta):
    from backend import booking, reserva, whatsapp, messaging, appstate
    estado, propuesta = ofrecer()
    estado.fecha, estado.hora, estado.nombre = "2030-01-08", "10:00", "Ana Ruiz López"
    estado.esperando_confirmacion = True
    flow = appstate.WAFlowState(cliente_id="salon", from_number="persona")
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(whatsapp.clients, "_get_client_config", lambda *a: {"booking":{"enabled":True}})
    monkeypatch.setattr(whatsapp, "_wa_get_flow", lambda *a: flow)
    monkeypatch.setattr(whatsapp.inbox, "remember_inbound_number", lambda *a: None)
    monkeypatch.setattr(whatsapp.inbox, "bot_is_muted", lambda *a: False)
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **k: None)
    textos, pasos = [], []
    async def texto(**kw): textos.append(kw["text"]); return True
    async def huecos(**kw): pasos.append(("huecos", kw["servicio"], kw["fecha_iso"])); return True
    async def resumen(**kw): pasos.append(("resumen", estado.servicio, estado.hora)); return True
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(whatsapp, "_wa_ofrecer_huecos_hablando", huecos)
    monkeypatch.setattr(whatsapp, "_wa_resumen_para_confirmar", resumen)
    asyncio.run(whatsapp._handle_whatsapp_message(cliente_id="salon", phone_number_id="canal",
        from_number="persona", incoming_text="respuesta", interactive_id="prop_"+respuesta+"_"+propuesta.id, request=None))
    assert pasos == ([("huecos", "Diagnóstico", "2030-01-08")] if respuesta == "acepta"
                     else [("resumen", "Color", "10:00")])
    assert not any("no selecciono" in t for t in textos)
