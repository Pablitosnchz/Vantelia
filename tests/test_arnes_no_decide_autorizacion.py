"""El boton emitido llega al producto incluso cuando este debe rechazarlo."""
import asyncio
import json

import pytest

import test_arnes_boton_crea_cita as prueba
from evals import arnes

entorno = prueba.entorno


@pytest.mark.parametrize("situacion", ["vieja", "preparada", "aceptada"])
def test_el_producto_decide_sobre_boton_emitido(entorno, situacion):
    from backend import reserva, whatsapp
    numero = "34600111007"
    captura = arnes.capturar_envios()
    parametros = dict(cliente_id="demo", phone_number_id="PN", from_number=numero, request=None)
    asyncio.run(whatsapp._handle_whatsapp_message(
        **parametros, incoming_text="preparar oferta sintetica", interactive_id=""))
    boton = captura.eventos[-1]["botones"][0]["id"]
    if situacion == "vieja":
        asyncio.run(whatsapp._handle_whatsapp_message(
            **parametros, incoming_text="preparar oferta sintetica", interactive_id=""))
        assert captura.eventos[-1]["botones"][0]["id"] != boton
    else:
        estado = reserva.cargar("demo", numero)
        propuesta = json.loads(estado.confirmacion_reserva_json)
        propuesta["estado"] = situacion
        estado.confirmacion_reserva_json = json.dumps(propuesta)
        reserva.guardar("demo", numero, estado)
    texto, enviado = arnes.preparar_entrada(captura, "demo", numero, {"boton": boton})
    assert enviado == boton
    marca = len(captura)
    asyncio.run(whatsapp._handle_whatsapp_message(**parametros, incoming_text=texto, interactive_id=enviado))
    assert arnes.citas_de("demo", numero) == []
    assert len(captura) > marca  # Respondio el producto; el arnes no intercepto la accion.
    assert any("vigente" in t or "verificar" in t for t in captura[marca:])
    assert entorno.post == []


def test_botones_legacy_sin_api_nueva_de_estado_ni_transporte(entorno, monkeypatch):
    from backend import messaging, reserva
    def prohibido(*a, **kw):
        raise AssertionError("el instrumento no puede consultar el estado del producto")
    monkeypatch.setattr(reserva, "leer_confirmacion_reserva", prohibido)
    monkeypatch.delattr(messaging, "_post_whatsapp_message")
    monkeypatch.delattr(messaging, "WhatsAppSendResult")
    captura = arnes.capturar_envios()
    assert asyncio.run(messaging._send_whatsapp_buttons(
        cliente_id="demo", phone_number_id="PN", to_number="600", body="Elegir",
        buttons=[("confirm_yes", "Confirmar"), ("otra_accion", "Otra")])) is True
    assert captura.opciones("demo", "600") == [
        {"id": "confirm_yes", "titulo": "Confirmar"}, {"id": "otra_accion", "titulo": "Otra"}]
    assert arnes.preparar_entrada(captura, "demo", "600", {"boton": "confirm_yes"}) == ("Confirmar", "confirm_yes")
    assert entorno.post == []


def test_frontera_detailed_no_soportada_es_no_medida(entorno, monkeypatch):
    from backend import messaging
    monkeypatch.delattr(messaging, "WhatsAppSendResult")
    captura = arnes.capturar_envios()
    with pytest.raises(arnes.InstrumentoNoCompatible, match="NO MEDIDO"):
        asyncio.run(messaging._send_whatsapp_payload(
            cliente_id="demo", phone_number_id="PN", payload={}, detailed=True))
    assert captura.eventos == []
    assert entorno.post == []
