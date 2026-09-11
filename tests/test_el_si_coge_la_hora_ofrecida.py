# -*- coding: utf-8 -*-
"""Un "si" a las horas que le acaban de ofrecer es elegirlas.

POR QUE EXISTE
--------------
Caso CRITICO del banco (`dice-que-si-y-acaba-en-cita`), medido contra una copia de
produccion el 11-sep-2026 y venido de una conversacion real del 9-sep:

    CLIENTA  quiero un alisado
    IA       Keratina premium o Acido lactico bio premium, ¿cual prefieres?
    CLIENTA  no lo tengo claro
    IA       Eso se decide viendo el pelo. ¿Que largo tienes?
    CLIENTA  manana
    IA       Manana tengo el diagnostico: 09:00, 09:15, 09:30...
    CLIENTA  a las 15
    IA       A las 15:00 no tengo; te puedo ofrecer por la manana
    CLIENTA  si
    IA       Tengo varias horas por la manana: 09:00, 09:15, 09:30...   <-- otra vez
    CLIENTA  me llamo Ana Ruiz
    IA       Ana, tengo varias horas manana: 09:00, 09:15...            <-- y otra

Se quedo sin cita. Es la misma familia que "la primera que tengas": si el codigo
no fija la hora, el modelo vuelve a recitar la lista. El "si" es el MISMO que
reconoce el canal (`whatsapp._wa_dice_que_si`), asi que "si, pero mejor a las 5"
no elige nada: eso es una peticion.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


def _con_horas_ofrecidas():
    """Le han ofrecido las horas de un dia y todavia no ha elegido ninguna."""
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Diagnóstico y presupuesto"
    estado.huecos = ["09:00", "09:15", "09:30"]
    estado.fecha_de_los_huecos = "2030-01-15"
    return estado


def test_un_si_coge_la_primera_hora_ofrecida(api_module):  # noqa: F811
    from backend import reserva

    estado = _con_horas_ofrecidas()

    reserva.anotar_lo_que_dice(estado, "si")

    assert (estado.fecha, estado.hora) == ("2030-01-15", "09:00")
    assert estado.hora_del_codigo is True


@pytest.mark.parametrize("dicho", [
    "si, pero mejor a las 5",   # es una peticion, no un si
    "no",
    "no, mejor otro dia",
    "¿y por la tarde?",
])
def test_lo_que_no_es_un_si_no_elige_hora(api_module, dicho):  # noqa: F811
    from backend import reserva

    estado = _con_horas_ofrecidas()

    reserva.anotar_lo_que_dice(estado, dicho)

    assert estado.hora == "", dicho


def test_la_hora_que_ya_eligio_no_se_pisa(api_module):  # noqa: F811
    from backend import reserva

    estado = _con_horas_ofrecidas()
    estado.hora = "09:30"

    reserva.anotar_lo_que_dice(estado, "si, perfecto")

    assert estado.hora == "09:30"


def test_con_la_hora_y_el_nombre_la_reserva_se_remata(api_module):  # noqa: F811
    """El final que pide el banco: resumen para confirmar, no otra lista de horas."""
    from backend import reserva

    estado = _con_horas_ofrecidas()
    reserva.anotar_lo_que_dice(estado, "si")
    reserva.anotar_lo_que_dice(estado, "me llamo Ana Ruiz")

    assert reserva.que_falta(estado) == ""
    assert reserva.tool_que_remata(estado) == "crear_cita"


def test_no_puede_ofrecer_una_hora_que_no_esta_en_los_huecos(api_module):  # noqa: F811
    """Le dijo que tenia las 15:00 teniendo solo la manana. Se quedo sin cita.

    Medido el 12-sep-2026 contra copia de produccion, el MISMO caso critico del
    banco pero roto por otro sitio: el estado no anoto las 15:00 (bien) y la cita
    imposible no nacio (bien), pero nadie contradijo al modelo cuando las ofrecio,
    asi que ella dijo que si a una hora que no existia y lo supo tres turnos
    despues.
    """
    from backend import agent, reserva

    estado = _con_horas_ofrecidas()

    # Lo que paso de verdad.
    assert agent._ofrece_una_hora_que_no_tiene(
        estado, "Mañana a las 15:00 tengo disponible la cita de Diagnóstico") == "15:00"
    assert agent._ofrece_una_hora_que_no_tiene(
        estado, "Solo necesito tus apellidos para reservarte mañana a las 15:00") == "15:00"

    # Lo que NO puede frenar: ofrecer una de las suyas, o decirle que no la tiene
    # (que es justo lo que queremos que acabe contestando).
    assert agent._ofrece_una_hora_que_no_tiene(
        estado, "Te reservo mañana a las 09:15, ¿te parece?") == ""
    assert agent._ofrece_una_hora_que_no_tiene(
        estado, "Las 15:00 no las tengo; tengo 09:00, 09:15 y 09:30") == ""
    # Sin huecos sobre la mesa no hay nada con lo que contrastar.
    assert agent._ofrece_una_hora_que_no_tiene(reserva.Estado(), "Te reservo a las 15:00") == ""


def test_el_freno_de_la_hora_inventada_esta_enchufado(api_module):  # noqa: F811
    """Un detector suelto no frena nada: tiene que mirarse en `responder`."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_ofrece_una_hora_que_no_tiene(estado, texto_final)" in fuente
    assert "ofrecio_una_hora_que_no_tiene" in fuente
