# -*- coding: utf-8 -*-
"""Cambiar de servicio es CAMBIAR la cita, no coger otra.

POR QUE EXISTE
--------------
Medido en la simulacion del 2-sep-2026. La clienta ya tenia cita y cambiaba de
idea a mitad de conversacion:

    ELLA  solo quiero cortarme las puntas, podemos cambiar la cita a eso?
    IA    confirmame que todo esta correcto
    ELLA  Confirmo.
    IA    confirmame que todo esta correcto
    ELLA  Confirmo.
    IA    parece que hay un pequenyo problema tecnico, llama al 625 120 100

No habia forma de cambiar el servicio: `reprogramar_cita` movia dia y hora y
nada mas. El asistente lo intentaba, se atascaba y la mandaba a llamar. Tres de
treinta conversaciones se fueron sin cita asi.

El nucleo YA sabia hacerlo (`_update_booking_details` acepta servicio); lo que
faltaba era que la herramienta lo ofreciera.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


class _Fila(dict):
    def __getitem__(self, k):
        return self.get(k, "")


def test_el_payload_cambia_el_servicio(api_module):
    from api_models import BookingReschedulePayload
    from backend import booking

    fila = _Fila(nombre="Laura", email="l@example.com", telefono="34600700021",
                 servicio="Mechas medio", employee_id="emp1", notas="")

    payload = booking._booking_update_payload_from_reschedule(
        fila, BookingReschedulePayload(fecha="2026-09-03", hora="11:00"),
        servicio="Corte de puntas",
    )

    assert payload.servicio == "Corte de puntas"
    assert payload.fecha == "2026-09-03" and payload.hora == "11:00"


def test_sin_servicio_se_conserva_el_que_tenia(api_module):
    from api_models import BookingReschedulePayload
    from backend import booking

    fila = _Fila(nombre="Laura", email="", telefono="", servicio="Mechas medio",
                 employee_id="emp1", notas="")

    payload = booking._booking_update_payload_from_reschedule(
        fila, BookingReschedulePayload(fecha="2026-09-04", hora="12:00"),
    )

    assert payload.servicio == "Mechas medio"


def test_la_herramienta_ofrece_cambiar_de_servicio(api_module):
    """Sin esto el modelo no sabe que puede hacerlo, y acaba creando otra cita."""
    from backend import voice

    herramientas = voice._voice_tools("demo") if hasattr(voice, "_voice_tools") else None
    if herramientas is None:
        import inspect

        fuente = inspect.getsource(voice)
        assert '"servicio": {' in fuente and "CAMBIAR de servicio" in fuente
        return
    repro = [h for h in herramientas if h.get("name") == "reprogramar_cita"][0]
    assert "servicio" in repro["parameters"]["properties"]
