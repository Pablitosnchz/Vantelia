# -*- coding: utf-8 -*-
"""«a las 15» sin horas consultadas se guarda y se resuelve al aceptar.

POR QUE EXISTE
--------------
13-sep-2026, caso crítico `dice-que-si-y-acaba-en-cita`, serie de 6 tiradas con
modelo real sobre 1fe7a3e: 0 al primer intento, 1 tras reintento, 5 fallos.
La oferta repetida ya contaba como oferta y el «si» escrito ya la aceptaba, pero:

    ella «el 2026-09-15»   (sin servicio elegido: nadie ha consultado horas)
    ella «a las 15»        -> estado.hora sigue vacía
    ella «si»              IA «De acuerdo, buscamos una cita de Diagnóstico para el martes 15»
                           IA «tengo 10:00, 12:45, 15:30 y 18:15»
    ella «me llamo Ana»    IA «Ana, tengo varias opciones: 14:00, 14:15, 15:00...»

`reserva._hora_coloquial` solo resuelve «a las 15» contra huecos reales, y con
`huecos` vacío devuelve "": no se anotaba nada. El arreglo anterior conservaba la
hora al aceptar, pero sus tests partían con `estado.hora = "15:00"` puesto a mano:
un estado que la conversación real nunca alcanzaba. Aquí el estado se construye
con los mismos mensajes que la clienta.
"""
from __future__ import annotations

import asyncio

from test_alternativa_de_precio import politica  # noqa: F401
from test_la_hora_dicha_sobrevive_a_aceptar import _canal, _libres


def _conversacion(*dichos):
    from backend import reserva

    estado = reserva.Estado(intencion="reservar")
    for dicho in dichos:
        reserva.anotar_lo_que_dice(estado, dicho, "Europe/Madrid")
    return estado


def _con_la_oferta(estado):
    from backend import booking, reserva

    actual = booking.alternativa_de_precio_vigente("salon", "Color")
    propuesta = reserva.preparar_propuesta_servicio(
        estado, servicio_id=actual["servicio_id"], nombre=actual["nombre"],
        origen=actual["origen"], revision_config=actual["revision"], servicio_origen="Color")
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje")
    return propuesta


def test_a_las_15_sin_huecos_no_se_pierde():
    estado = _conversacion("el 2030-01-08", "a las 15")

    assert estado.hora == "", "sin huecos no se valida: no puede darse por buena todavia"
    assert "15" in estado.hora_sin_hueco, "lo que dijo se ha perdido: al aceptar no hay hora"


def test_cambiar_de_dia_suelta_la_hora_pendiente():
    estado = _conversacion("el 2030-01-08", "a las 15", "mejor el 2030-01-09")

    assert estado.hora_sin_hueco == "", "la hora que dijo para otro dia no vale"


def test_con_hora_valida_no_queda_nada_pendiente():
    from backend import reserva

    estado = _conversacion("el 2030-01-08", "a las 15")
    estado.huecos, estado.fecha_de_los_huecos = ["15:00"], "2030-01-08"
    reserva.anotar_lo_que_dice(estado, "a las 15", "Europe/Madrid")

    assert estado.hora == "15:00"
    assert estado.hora_sin_hueco == ""


def test_aceptar_resuelve_la_hora_pendiente_con_los_huecos_del_aceptado(politica, monkeypatch):  # noqa: F811
    from backend import booking

    consultas = _libres(monkeypatch, {"14:45", "15:00"})
    estado = _conversacion("el 2030-01-08", "a las 15")
    propuesta = _con_la_oferta(estado)
    hora, del_codigo = estado.hora, estado.hora_del_codigo
    assert booking.contestar_alternativa_de_precio("salon", estado, propuesta.id, "acepta")

    assert asyncio.run(booking.conservar_la_hora_dicha(
        "salon", estado, hora, del_codigo=del_codigo)) is True

    assert estado.hora == "15:00"
    assert estado.hora_sin_hueco == ""
    assert consultas == [("salon", "2030-01-08", "Diagnóstico")]


def test_hora_pendiente_que_no_esta_libre_no_se_inventa(politica, monkeypatch):  # noqa: F811
    from backend import booking

    _libres(monkeypatch, {"10:00", "16:00"})
    estado = _conversacion("el 2030-01-08", "a las 15")
    propuesta = _con_la_oferta(estado)
    booking.contestar_alternativa_de_precio("salon", estado, propuesta.id, "acepta")

    assert asyncio.run(booking.conservar_la_hora_dicha("salon", estado, "")) is False
    assert estado.hora == ""


def test_el_recorrido_medido_llega_a_pedir_el_nombre_con_su_hora(politica, monkeypatch):  # noqa: F811
    """Botón o «si» escrito, con el estado que deja la conversación real."""
    from backend import whatsapp

    _libres(monkeypatch, {"15:00"})
    estado = _conversacion("quiero un alisado", "no lo tengo claro", "el 2030-01-08", "a las 15")
    propuesta = _con_la_oferta(estado)
    flow, anotado = _canal(monkeypatch, estado)

    asyncio.run(whatsapp._wa_contestar_propuesta(
        cliente_id="salon", phone_number_id="canal", from_number="persona",
        propuesta_id=propuesta.id, respuesta="acepta", flow=flow,
        incoming_text="", request=None))

    assert anotado["huecos"] == [], "ya dijo a las 15: volver a listar horas es el bucle medido"
    assert "15:00" in anotado["textos"][0]
    assert "apellidos" in anotado["textos"][0]
    assert estado.hora == "15:00" and flow.hora == "15:00"
