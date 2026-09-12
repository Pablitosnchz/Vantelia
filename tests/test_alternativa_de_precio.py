"""Oferta, envío y elección son hechos distintos también en el canal real."""
import asyncio
import types
from dataclasses import asdict

import pytest

from backend import booking, messaging, reserva, whatsapp


@pytest.fixture
def politica(monkeypatch):
    # La fixture histórica de api recarga módulos: parchear los actuales.
    global booking, messaging, reserva, whatsapp
    from backend import booking, messaging, reserva, whatsapp
    regla = {"id": "regla-precio", "accion": "ofrecer_cita", "texto": "Te valoramos en persona",
             "intenciones": ["precio"], "familias": ["color"], "activa": True}
    servicio = {"id": "diag", "nombre": "Diagnóstico", "duration_minutes": 20}
    monkeypatch.setattr(booking, "regla_de_precio_para", lambda cid, s: regla if cid == "salon" else {})
    monkeypatch.setattr(booking, "_servicio_de_valoracion", lambda *a, **k: servicio)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    return regla, servicio


@pytest.mark.parametrize("enviado", [False, True])
def test_oferta_whatsapp_no_cambia_seleccion_antes_de_aceptar(monkeypatch, politica, enviado):
    estado = reserva.Estado(intencion="reservar", servicio="Color", servicio_exacto="Color",
                            hora="15:00", huecos=["15:00"])
    antes = asdict(estado)
    envios = []
    async def enviar(**kwargs):
        envios.append(kwargs)
        return enviado
    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviar)
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    asyncio.run(whatsapp._wa_explicar_la_regla_del_precio(
        cliente_id="salon", phone_number_id="canal", to_number="persona", from_number="persona",
        estado=estado, freno={"reserva_esto_en_su_lugar": "Diagnóstico", "en_lugar_de": "Color",
                              "texto_del_negocio": "Te valoramos en persona"}))
    despues = asdict(estado)
    propuesta = despues.pop("propuesta_servicio")
    antes.pop("propuesta_servicio")
    despues.pop("tocado")
    antes.pop("tocado")
    assert despues == antes
    assert propuesta["estado"] == ("ofrecida" if enviado else "preparada")
    assert len(envios[0]["buttons"]) == 2


def ofrecer():
    estado = reserva.Estado(intencion="reservar", servicio="Color", hora="15:00", huecos=["15:00"])
    actual = booking.alternativa_de_precio_vigente("salon", "Color")
    propuesta = reserva.preparar_propuesta_servicio(
        estado, servicio_id=actual["servicio_id"], nombre=actual["nombre"],
        origen=actual["origen"], revision_config=actual["revision"], servicio_origen="Color")
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje")
    return estado, propuesta


def test_aceptacion_resuelve_servicio_y_descarta_huecos_del_anterior(politica):
    estado, propuesta = ofrecer()
    assert booking.contestar_alternativa_de_precio("salon", estado, propuesta.id, "acepta")
    assert estado.servicio_exacto == "Diagnóstico" and estado.duracion == 20
    assert not estado.hora and not estado.huecos and not estado.esperando_confirmacion
    assert not estado.hecho and not estado.ya_creada


@pytest.mark.parametrize("cambio", ["precio", "duracion", "desactivado", "politica", "otro_tenant"])
def test_cambios_del_portal_invalidan_una_oferta(politica, cambio):
    regla, servicio = politica
    estado, propuesta = ofrecer()
    tenant = "salon"
    if cambio == "precio":
        servicio["precio"] = 25
    elif cambio == "duracion":
        servicio["duration_minutes"] = 40
    elif cambio == "desactivado":
        servicio.clear()  # lectura pública actual ya no lo devuelve
    elif cambio == "politica":
        regla["accion"] = "pedir_foto"
    else:
        tenant = "otro"
    assert not booking.contestar_alternativa_de_precio(tenant, estado, propuesta.id, "acepta")
    assert estado.servicio == "Color"
    assert estado.propuesta_servicio.estado == "invalidada"


def test_rechazar_conserva_servicio_y_no_se_acepta_despues(politica):
    estado, propuesta = ofrecer()
    assert booking.contestar_alternativa_de_precio("salon", estado, propuesta.id, "rechaza")
    assert not booking.contestar_alternativa_de_precio("salon", estado, propuesta.id, "acepta")
    assert estado.servicio == "Color"


def test_pedir_foto_o_no_tener_regla_no_autoriza_alternativa(politica):
    regla, _ = politica
    regla["accion"] = "pedir_foto"
    assert not booking.alternativa_de_precio_vigente("salon", "Color")
    assert not booking.alternativa_de_precio_vigente("otro", "Color")


def test_boton_whatsapp_elige_una_vez_y_no_crea_cita(politica, monkeypatch):
    estado, propuesta = ofrecer()
    flow = types.SimpleNamespace(flow="", servicio="Color", hora="15:00", fecha="")
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(whatsapp.clients, "_get_client_config", lambda *a: {"booking": {"enabled": True}})
    monkeypatch.setattr(whatsapp, "_wa_get_flow", lambda *a: flow)
    monkeypatch.setattr(whatsapp.inbox, "remember_inbound_number", lambda *a: None)
    monkeypatch.setattr(whatsapp.inbox, "bot_is_muted", lambda *a: False)
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **k: None)
    async def enviar(**kwargs):
        return True
    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviar)
    for _ in range(2):
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="salon", phone_number_id="canal", from_number="persona",
            incoming_text="Sí, esa cita", interactive_id="prop_acepta_" + propuesta.id, request=None))
    assert estado.servicio == "Diagnóstico" and flow.servicio == "Diagnóstico"
    assert estado.propuesta_servicio.estado == "aceptada"
    assert not estado.ya_creada and not estado.hecho
