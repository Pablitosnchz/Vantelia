import asyncio
import pytest
from test_booking_exhaustive import api_module  # noqa: F401

@pytest.mark.parametrize("enviado", [False, True])
def test_orientacion_whatsapp_comparte_oferta_y_aceptacion(api_module, monkeypatch, enviado):
    from backend import booking, reserva, messaging, whatsapp
    monkeypatch.setattr(booking, "regla_de_orientacion_para", lambda cid, texto:
        {"id": "r", "accion": "ofrecer_cita", "activa": True} if cid == "demo" else {})
    monkeypatch.setattr(booking, "_servicio_de_valoracion", lambda *a, **k:
        {"id": "diag", "nombre": "Diagnóstico", "duration_minutes": 20})
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    async def enviar(**kw):
        return enviado
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", enviar)
    estado = reserva.Estado(intencion="reservar", servicio="Alisado", hora="15:00")
    actual = booking.alternativa_de_orientacion_vigente("demo", "alisado")
    assert booking.alternativa_de_orientacion_vigente("vecino", "alisado") == {}
    propuesta = reserva.preparar_propuesta_servicio(estado, servicio_id=actual["servicio_id"],
        nombre=actual["nombre"], origen=actual["origen"], revision_config=actual["revision"], servicio_origen="alisado")
    asyncio.run(whatsapp._wa_enviar_propuesta_de_precio(cliente_id="demo", phone_number_id="test",
        to_number="600123123", from_number="600123123", estado=estado))
    assert estado.servicio == "Alisado"
    assert booking.contestar_alternativa_de_precio("demo", estado, propuesta.id, "acepta") is enviado
    assert estado.servicio == ("Diagnóstico" if enviado else "Alisado")
    assert not estado.hecho
    assert not booking.contestar_alternativa_de_precio("demo", estado, propuesta.id, "acepta")


def test_politica_de_orientacion_guardada_se_resuelve_sin_inferir_qa(api_module, monkeypatch):
    from backend import booking, rules, appstate
    monkeypatch.setitem(appstate.CONFIG_CLIENTES["demo"], "ai_intents", {"enabled": True})
    regla = rules.guardar("demo", nombre="Orientar", intenciones=["orientacion"],
                          familias=[], accion="pedir_foto", texto="Envíanos una foto")
    try:
        assert booking.regla_de_orientacion_para("demo", "alisado")["id"] == regla["id"]
        assert booking.alternativa_de_orientacion_vigente("demo", "alisado") == {}
        monkeypatch.setitem(appstate.CONFIG_CLIENTES["demo"], "ai_intents", {"enabled": False})
        assert booking.regla_de_orientacion_para("demo", "alisado") == {}
    finally:
        rules.borrar("demo", regla["id"])
