"""Un negocio SIN agenda no debe simular reservas.

Bug real (ago 2026, hotel Cap Rocat, con `booking.enabled = false`): el asistente
guio al cliente por un flujo de cita completo — le pidio fecha, hora y nombre y
prometio abrir un formulario que no existe.

La causa no era el prompt, que ya tenia la regla de derivar, sino el bloque de
contexto `FLUJO_DE_MENU_ACTIVO (agendar)`: se inyectaba SIEMPRE que se detectaba
intencion de cita, sin mirar si el negocio tenia agenda, y un bloque de contexto
manda sobre las reglas generales.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

MENSAJES_DE_CITA = [
    "quiero agendar una cita",
    "quiero reservar",
    "quiero pedir cita",
]


@pytest.mark.parametrize("mensaje", MENSAJES_DE_CITA)
def test_esos_mensajes_se_detectan_como_intencion_de_cita(api_module, mensaje):
    from backend import chat

    assert chat._detect_menu_option(mensaje) == "agendar"


def test_sin_agenda_el_contexto_prohibe_pedir_fecha_hora_y_nombre(api_module):
    from backend import chat

    bloque = chat._menu_flow_context_block("agendar", booking_enabled=False)
    assert "FLUJO_DE_MENU_ACTIVO" not in bloque
    assert "PETICION_DE_CITA_SIN_AGENDA" in bloque
    assert "NO preguntes fecha, hora ni nombre" in bloque


def test_con_agenda_el_flujo_de_cita_sigue_intacto(api_module):
    """La correccion no puede romper a los negocios que SI reservan."""
    from backend import chat

    bloque = chat._menu_flow_context_block("agendar", booking_enabled=True)
    assert "FLUJO_DE_MENU_ACTIVO (agendar)" in bloque
    assert "fecha" in bloque and "hora" in bloque


@pytest.mark.parametrize("opcion", ["faq", "productos", "recomendar", "comparar", "estimar"])
def test_las_opciones_que_no_dependen_de_la_agenda_no_se_ven_afectadas(api_module, opcion):
    from backend import chat

    bloque = chat._menu_flow_context_block(opcion, booking_enabled=False)
    assert f"FLUJO_DE_MENU_ACTIVO ({opcion})" in bloque


def test_sin_opcion_no_hay_bloque(api_module):
    from backend import chat

    assert chat._menu_flow_context_block("", booking_enabled=True) == ""
    assert chat._menu_flow_context_block("desconocida", booking_enabled=True) == ""
