import asyncio

import pytest


@pytest.fixture
def oferta_persistible(api_module, monkeypatch):
    from backend import reserva, booking
    numero = "snapshot-canal"
    estado = reserva.cargar("demo", numero)
    estado.intencion = "reservar"
    p = reserva.preparar_propuesta_servicio(estado, servicio_id="diag", nombre="Diagnóstico",
        origen="regla:prueba", revision_config="v1")
    monkeypatch.setattr(booking, "alternativa_vigente_de_propuesta", lambda *a: {
        "servicio_id": "diag", "nombre": "Diagnóstico", "revision": "v1", "texto": "Te orientamos"})
    yield numero, estado, p
    reserva.olvidar("demo", numero)


@pytest.mark.parametrize("resultado", [True, False, "timeout"])
def test_identidad_guardada_antes_del_envio_y_acuse_despues(oferta_persistible, monkeypatch, resultado):
    from backend import reserva, whatsapp, messaging
    numero, estado, p = oferta_persistible
    async def enviar(**kw):
        guardado = reserva.cargar("demo", numero).propuesta_servicio
        assert guardado.id == p.id
        assert guardado.estado == "preparada"
        if resultado == "timeout":
            raise TimeoutError("simulado")
        return resultado
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    coro = whatsapp._wa_enviar_propuesta_de_precio(cliente_id="demo", phone_number_id="prueba",
        to_number=numero, from_number=numero, estado=estado)
    if resultado == "timeout":
        with pytest.raises(TimeoutError):
            asyncio.run(coro)
    else:
        assert asyncio.run(coro)[0] is resultado
    guardado = reserva.cargar("demo", numero).propuesta_servicio
    assert guardado.id == p.id
    assert guardado.estado == ("ofrecida" if resultado is True else "preparada")


@pytest.mark.parametrize("terminada", [False, True])
def test_flujo_recuperado_de_la_propuesta_no_vuelve_al_menu(oferta_persistible, monkeypatch, terminada):
    from backend import reserva, whatsapp, appstate
    numero, estado, p = oferta_persistible
    estado.hecho = terminada
    reserva.marcar_propuesta_ofrecida(estado, p.id, "acuse")
    reserva.guardar("demo", numero, estado)
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    recuperado = whatsapp._wa_get_flow("demo", numero)
    assert recuperado.flow == ("" if terminada else "agente")
    assert recuperado.servicio == ""  # ofrecida aún no es seleccionada
