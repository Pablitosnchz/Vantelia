import asyncio
import pytest
from test_booking_exhaustive import api_module, client  # noqa: F401
from test_servicio_retirado_no_es_hueco_ocupado import _servicio_retirado, _dia_con_hueco


def test_whatsapp_sin_profesional_rechaza_servicio_no_hora(api_module, monkeypatch):
    from backend import appstate, whatsapp, messaging
    nombre = _servicio_retirado(api_module, "Servicio retirado recorrido WA")
    flow = appstate.WAFlowState(cliente_id="demo", from_number="34600111333")
    flow.servicio, flow.fecha, flow.hora = nombre, _dia_con_hueco(), "10:00"
    flow.nombre = "Ana Ruiz Perez"
    enviados = []
    async def capturar(**kw):
        enviados.append(kw.get("text", ""))
        return True
    monkeypatch.setattr(messaging, "_send_whatsapp_text", capturar)
    assert not asyncio.run(whatsapp._wa_create_booking(cliente_id="demo", phone_number_id="test",
        to_number=flow.from_number, flow=flow, config={}, request=None))
    assert "servicio ya no está disponible" in " ".join(enviados)
    assert "se acaba de ocupar" not in " ".join(enviados)


def test_voz_real_no_ofrece_horas_si_el_servicio_se_retiro(api_module):
    from backend import voice
    nombre = _servicio_retirado(api_module, "Servicio retirado recorrido voz")
    resultado = asyncio.run(voice._voice_perform_booking("demo", nombre="Ana Ruiz Perez",
        telefono="34600111444", fecha=_dia_con_hueco(), hora="10:00", servicio=nombre))
    assert resultado.get("servicio_retirado") is True, resultado
    assert not resultado.get("huecos")


@pytest.mark.parametrize("empleado", ["", "inexistente"])
def test_resolucion_publica_distingue_retirado_antes_de_profesional(api_module, empleado):
    from backend import agenda, booking
    from fastapi import HTTPException
    nombre = _servicio_retirado(api_module, "Retirado resolución " + empleado)
    with pytest.raises(HTTPException) as error:
        asyncio.run(agenda._resolve_public_booking_employee("demo", _dia_con_hueco(), "10:00",
            servicio=nombre, employee_id=empleado))
    assert booking.es_servicio_retirado(error.value.detail)


from test_estirar_la_cita import una_cita, _payload  # noqa: F401


def test_reprogramar_no_cambia_a_servicio_retirado(api_module, una_cita):
    from backend import booking
    from fastapi import HTTPException
    nombre = _servicio_retirado(api_module, "Retirado cambio de servicio")
    with pytest.raises(HTTPException) as error:
        asyncio.run(booking._update_booking_details(una_cita, _payload(una_cita, servicio=nombre), None, source="voice"))
    assert booking.es_servicio_retirado(error.value.detail)
    assert booking._load_booking_or_404(una_cita["id"])["servicio"] == una_cita["servicio"]


def test_reprogramar_conserva_servicio_historico_retirado(api_module, una_cita):
    from backend import booking, db
    nombre = _servicio_retirado(api_module, "Retirado histórico")
    with db._get_db_connection() as cx:
        servicio = cx.execute("SELECT slug FROM services WHERE cliente_id=? AND name=?", ("demo", nombre)).fetchone()[0]
        cx.execute("UPDATE bookings SET servicio=?, service_id=? WHERE id=?", (nombre, servicio, una_cita["id"]))
        cx.commit()
    fila = booking._load_booking_or_404(una_cita["id"])
    asyncio.run(booking._update_booking_details(fila, _payload(fila, hora="11:00"), None, source="voice"))
    assert booking._load_booking_or_404(fila["id"])["booking_time"] == "11:00"


@pytest.mark.parametrize("con_profesional", [False, True])
def test_widget_real_conserva_motivo_retirado(client, api_module, con_profesional):
    from backend import agenda, booking
    nombre = _servicio_retirado(api_module, "Retirado widget " + str(con_profesional))
    empleado = agenda._resolve_employee_for_booking("demo", "", require_active=False)["id"] if con_profesional else ""
    respuesta = client.post("/agendar", headers={"Origin": "http://testserver"}, json={
        "cliente_id": "demo", "nombre": "Ana Ruiz Perez", "email": "panel@ejemplo.com",
        "telefono": "600111222", "fecha": _dia_con_hueco(), "hora": "10:00",
        "servicio": nombre, "employee_id": empleado, "notas": ""})
    assert respuesta.status_code == 409, respuesta.text
    assert booking.es_servicio_retirado(respuesta.json()["detail"])
