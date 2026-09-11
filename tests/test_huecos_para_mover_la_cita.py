# -*- coding: utf-8 -*-
"""Lo que se ofrece para mover una cita debe aceptarlo el núcleo de esa cita.

Con dos profesionales, la unión pública ofrecía las horas de B aunque la cita
seguía siendo de A. Aceptar la primera opción acababa en un rechazo de horario.
Datos sintéticos: sin modelo, agenda real de prueba y sin salidas al exterior.
"""
import asyncio
import copy
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import DEFAULT_DEMO_CONFIG


@pytest.fixture(scope="module")
def api_module(vantelia_env_factory):
    config = copy.deepcopy(DEFAULT_DEMO_CONFIG)
    config["demo"]["booking"].update(day_end="18:00", closed_weekdays=[])
    return vantelia_env_factory(config)


@pytest.fixture
def agenda_de_dos(api_module):
    from api_models import PortalEmployeePayload
    from backend import agenda, booking, db, reserva

    reserva.olvidar("demo", "600111222")

    profesionales = []
    for nombre in ("Profesional A", "Profesional B"):
        persona = agenda._create_portal_employee("demo", PortalEmployeePayload(
            name=nombre, day_start="09:00", day_end="18:00", slot_minutes=30,
            closed_weekdays=[], service_ids=[]), full_access=True)
        profesionales.append(agenda._get_employee_row(persona.employee_id, cliente_id="demo"))
    dia = (date.today() + timedelta(days=7)).isoformat()
    citas = []

    def crear(hora, telefono, employee=0):
        cita = asyncio.run(booking._create_booking_core(
            "demo", employee_row=profesionales[employee], nombre="Ana Prueba",
            telefono=telefono, email="", servicio="", booking_date=dia,
            booking_time=hora, source="test", send_confirmation=False))
        citas.append(cita["id"])
        return cita

    propia = crear("12:00", "600111222")
    crear("09:00", "600333444")
    yield propia, dia, profesionales, crear
    reserva.olvidar("demo", "600111222")
    with db._get_db_connection() as cx:
        for bid in citas:
            cx.execute("DELETE FROM bookings WHERE id=?", (bid,))
        for persona in profesionales:
            cx.execute("DELETE FROM employees WHERE id=?", (persona["id"],))
        cx.commit()


def consultar(cita, dia, **cambios):
    from backend import voice

    args = {"fecha": dia, "hora": "09:00", "codigo_reserva": cita["booking_code"]}
    args.update(cambios)
    return asyncio.run(voice._voice_dispatch_tool(
        "demo", "consultar_disponibilidad", json.dumps(args), from_number="600111222"))


def test_no_ofrece_la_hora_de_otra_profesional(agenda_de_dos):
    from backend import booking

    propia, dia, _, _ = agenda_de_dos
    # El rechazo al mover es legítimo: su profesional tiene otra cita a las 9.
    rechazo = asyncio.run(booking._reschedule_booking_by_code(
        "demo", propia["booking_code"], dia, "09:00",
        trusted_phone="600111222", source="whatsapp"))
    assert not rechazo["ok"]
    oferta = consultar(propia, dia)
    assert oferta["ok"], oferta
    assert not oferta["hora_disponible"], oferta
    assert "09:00" not in oferta["huecos"], oferta
    # Elegir la primera opción ofrecida mueve ESA cita a la primera.
    resultado = asyncio.run(booking._reschedule_booking_by_code(
        "demo", propia["booking_code"], dia, oferta["huecos"][0],
        trusted_phone="600111222", source="whatsapp"))
    assert resultado["ok"], resultado
    movida = booking._load_booking_or_404(propia["id"])
    assert movida["employee_id"] == propia["employee_id"]
    assert movida["booking_time"] == oferta["huecos"][0]


def test_para_una_cita_nueva_siguen_valiendo_las_dos(agenda_de_dos):
    propia, dia, _, _ = agenda_de_dos
    oferta = consultar(propia, dia, codigo_reserva="")
    assert oferta["hora_disponible"], oferta


@pytest.mark.parametrize("hora,aceptado", [("09:00", False), ("09:30", True)])
def test_boton_mover_cuenta_el_resultado_real(agenda_de_dos, monkeypatch, hora, aceptado):
    from backend import booking, messaging, whatsapp

    propia, dia, _, _ = agenda_de_dos
    enviados = []

    async def enviar(*, text, **kwargs):
        enviados.append(text)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviar)
    whatsapp._wa_clear_flow("demo", "600111222")
    flow = whatsapp._wa_get_flow("demo", "600111222")
    flow.flow = "booking_confirm"
    flow.booking_code = propia["booking_code"]
    flow.fecha, flow.hora = dia, hora
    try:
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id="1234567890", from_number="600111222",
            incoming_text="Mover la que tengo", interactive_id="dup_mover", request=None))
        assert booking._load_booking_or_404(propia["id"])["booking_time"] == (hora if aceptado else "12:00")
        assert enviados
        if aceptado:
            assert any("reprogramada correctamente" in texto.lower() for texto in enviados), enviados
        else:
            assert not any("te he cambiado" in texto.lower() for texto in enviados), enviados
            assert any("disponible" in texto.lower() for texto in enviados), enviados
    finally:
        whatsapp._wa_clear_flow("demo", "600111222")


def test_primer_hueco_conserva_la_profesional(agenda_de_dos):
    from backend import agenda

    propia, dia, _, _ = agenda_de_dos
    fecha, horas = asyncio.run(agenda.primer_dia_con_hueco(
        "demo", desde=dia, dias=1, booking_row=propia))
    assert fecha == dia
    assert horas[0] == "09:30", horas
    assert "12:00" not in horas, "dejar la cita igual no es moverla"


def test_el_agente_pasa_la_cita_de_su_estado(agenda_de_dos):
    from backend import agent

    propia, dia, _, _ = agenda_de_dos
    resultado = asyncio.run(agent._ejecutar(
        "demo", "consultar_disponibilidad", {"fecha": dia, "hora": "09:00"},
        telefono="600111222", codigo_reprogramar=propia["booking_code"]))
    assert resultado["ok"], resultado
    assert not resultado["hora_disponible"], resultado


def test_la_busqueda_automatica_del_agente_usa_su_cita(agenda_de_dos, monkeypatch):
    import sys
    import types

    from backend import agent, reserva, settings, timeutils

    propia, dia, _, _ = agenda_de_dos
    monkeypatch.setattr(timeutils, "_utc_now", lambda: datetime.fromisoformat(dia).replace(tzinfo=timezone.utc))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    observado = []

    def recibir(**kwargs):
        estado = reserva.cargar("demo", "600111222")
        observado.append((estado.codigo, estado.fecha_de_los_huecos, list(estado.huecos)))
        # Basta observar los huecos calculados ANTES del modelo; no se simula
        # que una conversación con un modelo real haya pasado el humo.
        raise RuntimeError("fin de la observación local")

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **kwargs: types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=recibir)))
    monkeypatch.setitem(sys.modules, "openai", modulo)
    asyncio.run(agent.responder(
        "demo", "cualquier otro hueco que tengas me vale", session_id="huecos-test",
        telefono="600111222", intencion="reprogramar"))
    assert observado
    codigo, fecha, horas = observado[0]
    assert codigo == propia["booking_code"]
    assert fecha == dia
    assert horas[0] == "09:30", horas


def test_se_descuenta_la_cita_propia_y_se_respeta_su_duracion(agenda_de_dos):
    from backend import booking, db, timeutils

    propia, dia, _, _ = agenda_de_dos
    # Una cita de una hora: 11:30 solapa con su hueco viejo, que debe excluirse;
    # 17:30 no cabe, aunque otro profesional admita una reserva corta.
    with db._get_db_connection() as cx:
        cx.execute(
            "INSERT INTO services (cliente_id,slug,name,duration_minutes,price_cents,is_active,created_at) "
            "VALUES ('demo','corte_prueba_largo','Corte de prueba largo',60,3000,1,?)",
            (timeutils._utc_now_iso(),))
        cx.commit()
    try:
        booking._update_booking_record(propia["id"], servicio="Corte de prueba largo")
        oferta = consultar(propia, dia, hora="11:30")
        assert oferta["hora_disponible"], oferta
        assert "17:30" not in oferta["huecos"]
        movida = asyncio.run(booking._reschedule_booking_by_code(
            "demo", propia["booking_code"], dia, "11:30",
            trusted_phone="600111222", source="whatsapp"))
        assert movida["ok"], movida
    finally:
        with db._get_db_connection() as cx:
            cx.execute("DELETE FROM services WHERE cliente_id='demo' AND slug='corte_prueba_largo'")
            cx.commit()


def test_el_nombre_publico_conserva_el_pack_de_la_cita(agenda_de_dos):
    from backend import booking, db, timeutils, voice

    propia, dia, _, _ = agenda_de_dos
    with db._get_db_connection() as cx:
        for slug, nombre, duracion, activo in (
            ("prueba_suelto", "Prueba largo", 30, 0),
            ("prueba_pack", "Pack Prueba largo", 60, 1),
        ):
            cx.execute(
                "INSERT INTO services (cliente_id,slug,name,duration_minutes,price_cents,is_active,created_at) "
                "VALUES ('demo',?,?,?,?,?,?)",
                (slug, nombre, duracion, 3000, activo, timeutils._utc_now_iso()))
        cx.commit()
    try:
        booking._update_booking_record(propia["id"], servicio="Pack Prueba largo")
        oferta = consultar(propia, dia, hora="11:30", servicio="Prueba largo")
        assert oferta["hora_disponible"], oferta
        cambio = asyncio.run(voice._voice_reschedule_booking(
            "demo", propia["booking_code"], dia, "11:30", servicio="Prueba largo",
            from_number="600111222"))
        assert cambio["ok"], cambio
        assert booking._load_booking_or_404(propia["id"])["servicio"] == "Pack Prueba largo"
    finally:
        with db._get_db_connection() as cx:
            cx.execute("DELETE FROM services WHERE cliente_id='demo' AND slug IN ('prueba_suelto','prueba_pack')")
            cx.commit()


def test_llamada_desde_otro_numero_admite_contacto_verificado(agenda_de_dos):
    from backend import voice

    propia, dia, _, _ = agenda_de_dos
    args = {"fecha": dia, "hora": "09:00", "codigo_reserva": propia["booking_code"],
            "telefono": "600111222"}
    respuesta = asyncio.run(voice._voice_dispatch_tool(
        "demo", "consultar_disponibilidad", json.dumps(args), from_number="600555555"))
    assert respuesta["ok"], respuesta
    assert not respuesta["hora_disponible"]


def test_el_modelo_puede_aportar_contacto_en_la_consulta(api_module):
    from backend import clients, voice

    herramienta = next(t for t in voice._voice_booking_tools(
        "demo", clients._get_client_config("demo")) if t["name"] == "consultar_disponibilidad")
    propiedades = herramienta["parameters"]["properties"]
    assert "telefono" in propiedades and "email" in propiedades


@pytest.mark.parametrize("ajeno", [False, True], ids=["codigo-inexistente", "codigo-ajeno"])
def test_codigo_invalido_no_devuelve_huecos_generales(agenda_de_dos, ajeno):
    propia, dia, _, crear = agenda_de_dos
    codigo = crear("14:00", "600999888")["booking_code"] if ajeno else "R-000000"
    oferta = consultar(propia, dia, codigo_reserva=codigo)
    assert not oferta["ok"], oferta
    assert "huecos" not in oferta
