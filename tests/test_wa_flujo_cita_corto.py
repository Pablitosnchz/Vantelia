"""El flujo de cita por WhatsApp no debe ser un interrogatorio.

Era de hasta nueve interacciones (centro, servicio, profesional, dia, hora,
nombre, email, notas y confirmar) para pedir hora en una peluqueria. Se recorto:

- Al cliente que ya ha reservado se le reconoce por su TELEFONO (verificado por el
  canal) y no se le vuelve a pedir nombre ni email.
- El email pasa a ser opcional: la confirmacion ya le llega por WhatsApp.
- El paso de notas deja de ser obligatorio y se ofrece como boton en el resumen.
"""
from __future__ import annotations

import asyncio

from test_booking_exhaustive import api_module  # noqa: F401


def _contacto(api_module, cliente_id="demo", phone="34600123456", nombre="Pablo Sanchez", email="pablo@example.com"):
    from backend import crm

    crm._crm_upsert_contact(cliente_id, name=nombre, email=email, phone=phone, source="test")


def test_se_reconoce_al_cliente_por_su_telefono(api_module):
    from backend import crm

    _contacto(api_module, phone="34600123456")
    fila = crm.contact_by_phone("demo", "34600123456")
    assert fila is not None
    assert fila["name"] == "Pablo Sanchez"
    # El formato del numero no importa: se compara normalizado.
    assert crm.contact_by_phone("demo", "+34 600 123 456") is not None
    assert crm.contact_by_phone("demo", "600123456") is not None


def test_un_telefono_desconocido_no_devuelve_contacto(api_module):
    from backend import crm

    assert crm.contact_by_phone("demo", "34699999999") is None
    assert crm.contact_by_phone("demo", "") is None


def test_no_se_mezclan_contactos_entre_negocios(api_module):
    """Un telefono conocido en un tenant no puede reconocerse en otro."""
    from backend import crm

    _contacto(api_module, cliente_id="demo", phone="34600777888", nombre="Cliente Demo")
    assert crm.contact_by_phone("demo", "34600777888") is not None
    assert crm.contact_by_phone("van", "34600777888") is None


def test_el_resumen_ofrece_confirmar_corregir_o_anotar(api_module, monkeypatch):
    from backend import appstate, messaging, whatsapp

    enviados = []

    async def fake_buttons(**kwargs):
        enviados.append(kwargs)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", fake_buttons)

    flow = appstate.WAFlowState(cliente_id="demo", from_number="34600123456")
    flow.nombre, flow.email = "Pablo Sanchez", "pablo@example.com"
    flow.servicio, flow.employee_name = "Corte", "Alicia"
    flow.fecha, flow.hora = "2026-09-01", "12:30"

    # Reconocido: el tercer boton permite corregir los datos que hemos puesto nosotros.
    asyncio.run(whatsapp._wa_send_booking_summary(
        cliente_id="demo", phone_number_id="PN", to_number="34600123456", flow=flow, reconocido=True,
    ))
    ids = [b[0] for b in enviados[-1]["buttons"]]
    assert ids == ["confirm_yes", "confirm_no", "data_fix"]
    assert "Te he reconocido" in enviados[-1]["body"]
    assert flow.flow == "booking_confirm"

    # No reconocido: el tercer boton es anadir nota.
    asyncio.run(whatsapp._wa_send_booking_summary(
        cliente_id="demo", phone_number_id="PN", to_number="34600123456", flow=flow,
    ))
    ids = [b[0] for b in enviados[-1]["buttons"]]
    assert ids == ["confirm_yes", "confirm_no", "notes_write"]
    assert "Te he reconocido" not in enviados[-1]["body"]


def test_el_resumen_omite_el_email_si_no_lo_hay(api_module, monkeypatch):
    """El email es opcional: no debe aparecer una linea vacia en el resumen."""
    from backend import appstate, messaging, whatsapp

    enviados = []

    async def fake_buttons(**kwargs):
        enviados.append(kwargs)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", fake_buttons)

    flow = appstate.WAFlowState(cliente_id="demo", from_number="34600123456")
    flow.nombre, flow.email = "Pablo Sanchez", ""
    flow.servicio, flow.fecha, flow.hora = "Corte", "2026-09-01", "12:30"
    asyncio.run(whatsapp._wa_send_booking_summary(
        cliente_id="demo", phone_number_id="PN", to_number="34600123456", flow=flow,
    ))
    assert "📧" not in enviados[-1]["body"]
    assert "Pablo Sanchez" in enviados[-1]["body"]
