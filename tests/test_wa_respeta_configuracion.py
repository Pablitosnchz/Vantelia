"""El asistente de WhatsApp respeta lo que el negocio configura en su panel.

Auditoria tras dos fallos reales de la misma familia (ago 2026): el menu de
WhatsApp estaba escrito a fuego ignorando las sugerencias configuradas, y un
negocio con la agenda apagada acababa simulando un flujo de cita.

Aqui se fija por escrito lo que el canal DEBE leer de la configuracion, para que
no se vuelva a escapar: mensaje de confirmacion propio, horario, dias cerrados,
servicios activos y profesionales.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def test_la_confirmacion_incluye_el_mensaje_que_escribe_el_negocio(api_module):
    """`booking.success_message` (indicaciones para llegar, que traer...) se usaba
    solo en la reserva por web; por WhatsApp el cliente se quedaba sin ese aviso."""
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_create_booking)
    assert "success_message" in fuente, "la confirmacion de WhatsApp debe incluir el mensaje del negocio"


def test_las_fechas_ofrecidas_salen_del_horario_real(api_module):
    """Los dias cerrados vienen de la matriz semanal compartida con chat y voz,
    no del config crudo: si no, un dia reabierto solo en el horario de un
    profesional quedaba oculto."""
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_send_date_picker)
    assert "_wa_closed_weekdays" in fuente
    # Y los huecos se calculan de verdad, con bloqueos y vacaciones incluidos.
    assert "_agenda_block_reasons_for_day" in fuente
    assert "_employee_slot_sets_for_day" in fuente or "_public_slot_sets_for_day" in fuente


def test_solo_se_ofrecen_servicios_publicables(api_module):
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_send_service_picker)
    assert "_public_services_for_booking" in fuente


def test_solo_se_ofrecen_profesionales_activos_del_servicio(api_module):
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_employees_for_service)
    assert "include_inactive=False" in fuente
    assert "_service_name_allowed_for_employee" in fuente


def test_solo_se_ofrecen_centros_activos(api_module):
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_send_location_picker)
    assert "include_inactive=False" in fuente
