"""Una aceptación histórica deja de autorizar al cambiar sus condiciones."""
from dataclasses import replace
import asyncio

import pytest

from test_alternativa_de_precio import politica, ofrecer  # noqa: F401


@pytest.mark.parametrize("cambio", ["ninguno", "caducidad", "politica", "catalogo"])
def test_aceptacion_revalidada_antes_de_reutilizarla(politica, cambio):
    from backend import agent, booking

    regla, servicio = politica
    estado, propuesta = ofrecer()
    assert booking.contestar_alternativa_de_precio("salon", estado, propuesta.id, "acepta")
    if cambio == "caducidad":
        estado.propuesta_servicio = replace(estado.propuesta_servicio, creada=0)
    elif cambio == "politica":
        regla["accion"] = "pedir_foto"
    elif cambio == "catalogo":
        servicio["duration_minutes"] = 40

    historial = [{"role": "assistant", "content": "¿Quieres una cita de diagnóstico?"}]
    assert agent._acepta_la_valoracion("salon", historial, "sí", estado=estado) is (cambio == "ninguno")
    if cambio != "ninguno":
        assert estado.propuesta_servicio.estado == "invalidada"
    assert not estado.hecho


def test_whatsapp_no_envia_botones_de_una_propuesta_caducada(politica, monkeypatch):
    from backend import booking, reserva, whatsapp, messaging

    estado = reserva.Estado(intencion="reservar")
    actual = booking.alternativa_de_precio_vigente("salon", "Color")
    propuesta = reserva.preparar_propuesta_servicio(
        estado, servicio_id=actual["servicio_id"], nombre=actual["nombre"],
        origen=actual["origen"], revision_config=actual["revision"], servicio_origen="Color")
    estado.propuesta_servicio = replace(propuesta, creada=0)
    botones = []
    textos = []
    async def enviar_botones(**kw):
        botones.append(kw)
        return True
    async def enviar_texto(**kw):
        textos.append(kw)
        return True
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar_botones)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviar_texto)
    enviado, _ = asyncio.run(whatsapp._wa_enviar_propuesta_de_precio(
        cliente_id="salon", phone_number_id="prueba", to_number="prueba",
        from_number="prueba", estado=estado))
    assert enviado
    assert not botones
    assert len(textos) == 1
    assert estado.propuesta_servicio.estado == "invalidada"
