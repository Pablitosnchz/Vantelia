"""El error de la tool no debe dejar lista otra creación del mismo servicio."""
import pytest

from test_booking_exhaustive import api_module  # noqa: F401


def test_retirada_invalida_cierre_y_conserva_contacto(api_module):
    from backend import booking, reserva
    estado = reserva.Estado(intencion="reservar", servicio="Masaje", servicio_exacto="Masaje",
        servicio_texto="quiero un masaje", duracion=60, nombre="Ana Prueba",
        fecha="2030-01-08", hora="10:00", profesional="Laura", esperando_confirmacion=True)
    reserva.preparar_confirmacion_reserva(estado, {"servicio": "Masaje"})
    reserva.anotar_resultado(estado, "crear_cita", {"servicio": "Masaje"}, booking.respuesta_servicio_retirado())
    assert reserva.tool_que_remata(estado) != "crear_cita"
    assert not estado.servicio and not estado.servicio_exacto and not estado.servicio_texto
    assert not estado.duracion and not estado.hora and not estado.profesional
    assert not estado.esperando_confirmacion and not estado.confirmacion_reserva_json
    assert estado.nombre == "Ana Prueba"
    assert estado.fecha == "2030-01-08"


@pytest.mark.parametrize("tool", ["buscar_servicio", "crear_cita"])
def test_error_al_consultar_otra_alternativa_no_borra_la_reserva(api_module, tool):
    from backend import booking, reserva
    estado = reserva.Estado(intencion="reservar", servicio="Corte", servicio_exacto="Corte", hora="10:00")
    reserva.anotar_resultado(estado, tool, {"servicio": "Masaje", "descripcion": "Masaje"}, booking.respuesta_servicio_retirado())
    assert estado.servicio == "Corte" and estado.hora == "10:00"


@pytest.mark.parametrize("enviado", [False, True])
def test_aviso_whatsapp_solo_se_registra_si_se_entrega(api_module, monkeypatch, enviado):
    import asyncio
    from backend import appstate, booking, messaging, whatsapp
    historial = []
    async def texto(**kw): return enviado
    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(booking, "_public_services_for_booking", lambda *a, **k: [])
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **kw: historial.append(kw))
    flow = appstate.WAFlowState(cliente_id="demo", from_number="34600111499", servicio="Masaje")
    asyncio.run(whatsapp._wa_servicio_retirado(cliente_id="demo", phone_number_id="PN",
        to_number=flow.from_number, flow=flow, config={}, request=None))
    assert bool(historial) is enviado


def test_cita_ya_creada_no_se_reabre_por_otro_error(api_module):
    from backend import booking, reserva
    estado = reserva.Estado(intencion="reservar", servicio="Corte", hecho=True, ya_creada=True, codigo="ABC")
    reserva.anotar_resultado(estado, "crear_cita", {"servicio": "Corte"}, booking.respuesta_servicio_retirado())
    assert estado.hecho and estado.ya_creada and estado.servicio == "Corte" and estado.codigo == "ABC"
