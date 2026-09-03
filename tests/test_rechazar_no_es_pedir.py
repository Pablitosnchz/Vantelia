# -*- coding: utf-8 -*-
"""Nombrar algo para decir que NO lo quieres no es pedirlo.

POR QUE EXISTE
--------------
3-sep-2026, reportado probando la demo. Justo antes de cerrar la cita:

    ELLA  no quiero cita para diagnostico quiero que me cojas cita para las
          mechas solo
    ...
    ELLA  a las 10
    IA    Pablo, para poder reservar las mechas, necesito que elijas solo un
          servicio. Si quieres hacerte las mechas, no podemos incluir el
          diagnostico en la misma cita. [...] tambien puedes llamarnos al
          625 120 100 para que te ayuden a cuadrar todo.

`_freno_de_varios_servicios` leia en la conversacion "mechas" Y "diagnostico" y
decidia que habia pedido DOS cosas. El freno existe por un incidente real -una
cita de 20 minutos para cuatro servicios- y hace falta, pero aqui contaba como
pedido justo lo que ella acababa de rechazar.

Medido sobre la conversacion entera:

    familias que veia         ['mechas', 'diagnostico']  -> saltaba
    quitando lo rechazado     ['mechas']                 -> no salta
    varios servicios de verdad ['secado', 'cortes']      -> sigue saltando
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401

CID = "demo"


def _catalogo(monkeypatch, familias_por_texto, valoracion="Diagnostico y presupuesto"):
    """Catalogo de mentira: el test mide la LOGICA, no los datos de un salon.

    La primera version leia el catalogo real de la BD local, que no es fiel a
    produccion, y fallaba por los datos y no por el codigo.
    """
    from backend import booking, catalog_pick

    monkeypatch.setattr(catalog_pick, "familias_pedidas",
                        lambda c, texto: familias_por_texto.get(texto, []))
    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda c, **k: {"nombre": valoracion})


def test_el_diagnostico_rechazado_no_cuenta(api_module, monkeypatch):
    from backend import agent

    pedido = ("quiero hacerme las mechas y tengo el cabello largo "
              "no quiero cita para diagnostico quiero que me cojas cita "
              "para las mechas solo")
    _catalogo(monkeypatch, {pedido: ["mechas", "diagnostico"],
                            "Diagnostico y presupuesto": ["diagnostico"]})

    quedan = agent._sin_lo_que_ha_rechazado(CID, pedido, ["mechas", "diagnostico"])

    assert quedan == ["mechas"], (
        "con dos familias el freno le dice que no se pueden juntar y la manda a "
        "llamar por telefono, cuando solo habia pedido las mechas"
    )


def test_pedir_varias_cosas_de_verdad_sigue_frenando(api_module, monkeypatch):
    """El incidente que dio origen al freno: 4 servicios en 20 minutos."""
    from backend import agent

    pedido = "quiero corte y secado y tambien tinte"
    _catalogo(monkeypatch, {pedido: ["cortes", "secado", "color"],
                            "Diagnostico y presupuesto": ["diagnostico"]})

    assert agent._sin_lo_que_ha_rechazado(CID, pedido, ["cortes", "secado", "color"]) == [
        "cortes", "secado", "color"], "aqui NO ha rechazado nada"


def test_sin_rechazo_no_se_toca_nada(api_module, monkeypatch):
    from backend import agent

    pedido = "quiero unas mechas y tambien el diagnostico"
    _catalogo(monkeypatch, {pedido: ["mechas", "diagnostico"],
                            "Diagnostico y presupuesto": ["diagnostico"]})

    assert agent._sin_lo_que_ha_rechazado(CID, pedido, ["mechas", "diagnostico"]) == [
        "mechas", "diagnostico"], (
        "si lo QUIERE, cuenta: son dos citas y hay que cuadrarlas"
    )


def test_reservar_la_valoracion_no_dispara_el_freno(api_module, monkeypatch):
    """Aceptar el diagnostico tampoco es pedir dos servicios.

    Reportado el 3-sep-2026, el caso contrario al de arriba: acepto el
    diagnostico y justo antes del resumen le salio

        necesitamos decidir si solo quieres el diagnostico o si tambien quieres
        hacerte las mechas en la misma cita. Que prefieres hacer?

    ...y el mensaje siguiente ya era el resumen del diagnostico. Sobraba.

    La valoracion es el PRIMER PASO del negocio hacia el tratamiento, no un
    segundo servicio: si lo que se reserva es ella, este freno no pinta nada.
    """
    from backend import agent, booking

    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda c, **k: {"nombre": "Diagnostico y presupuesto"})

    assert agent._es_la_valoracion(CID, "Diagnostico y presupuesto")
    assert agent._es_la_valoracion(CID, "diagnostico y presupuesto"), "sin tildes ni mayusculas"
    assert not agent._es_la_valoracion(CID, "Mechas o balayage largo")
    assert not agent._es_la_valoracion(CID, "")


def test_el_freno_se_salta_ANTES_de_mirar_familias(api_module):
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent._freno_de_varios_servicios)
    i = fuente.index("_es_la_valoracion(")
    j = fuente.index("familias_pedidas(")
    assert i < j, (
        "si se mira despues, ya ha decidido que hay dos familias y el mensaje sale igual"
    )
