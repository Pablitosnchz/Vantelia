# -*- coding: utf-8 -*-
""""La primera que tengas" tiene que acabar en cita, no en otra lista de horas.

POR QUE EXISTE
--------------
El caso mas simple del humo (`corte-acaba-en-cita`) salia rojo de vez en cuando.
Reproducido el 11-sep-2026 contra una copia de produccion, a ultima hora de la
tarde, imprimiendo el estado de la reserva tras cada mensaje:

    CLIENTA  hola, quiero cita para un corte de senora
    IA       ¿Que dia? Martes 15, miercoles 16, jueves 17...
    CLIENTA  la primera que tengas
             (el codigo elige HOY a las 17:45, a diez minutos vista)
    IA       Para el martes 15 tengo 10:00, 10:15, 10:30... ¿cual te viene mejor?
             (el modelo ha mirado el martes: el estado y lo que ella lee ya no casan)
    CLIENTA  me llamo Ana Ruiz
             (el nombre no se anotaba: solo entraba con la llamada a crear_cita)
    IA       Para el martes 15 tengo... ¿cual te viene mejor?
    CLIENTA  si, confirmo  ->  "solo me falta la hora"  ->  y sin cita

En las otras cinco tiradas salio bien solo porque el guion lleva un "si, confirmo"
de sobra: a "la primera que tengas" le volvia a ensenar la lista de horas.

Arreglado en el codigo: la hora que elige el codigo sigue al dia que el modelo le
ensena, el nombre entra en cuanto lo dice, el primer hueco de hoy deja margen, y
con el hueco ya elegido se le dice al modelo que lo proponga y pida el nombre.
"""
from __future__ import annotations

import datetime

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


def _eligiendo_el_codigo():
    """Pide cita, dice "la primera que tengas" y el codigo le coge hoy 17:45."""
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Corte señora"
    estado.huecos = ["17:45"]
    estado.fecha_de_los_huecos = "2026-09-11"
    reserva.anotar_lo_que_dice(estado, "la primera que tengas")
    return estado


def test_si_el_modelo_le_ensena_otro_dia_la_hora_del_codigo_le_sigue(api_module):  # noqa: F811
    """El caso real: el codigo tenia hoy 17:45 y ella leia el martes 15."""
    from backend import reserva

    estado = _eligiendo_el_codigo()
    assert (estado.fecha, estado.hora) == ("2026-09-11", "17:45")

    reserva.anotar_resultado(estado, "consultar_disponibilidad",
                             {"fecha": "2026-09-15", "servicio": "Corte señora"},
                             {"ok": True, "huecos": ["10:00", "10:15", "10:30"]})

    assert (estado.fecha, estado.hora) == ("2026-09-15", "10:00"), (
        "el estado tiene que hablar del mismo dia que lo que ella esta leyendo")


def test_la_hora_que_dice_ella_no_se_mueve(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Corte señora"
    reserva.anotar_lo_que_dice(estado, "me da igual el dia, a las 11:00")
    assert estado.dia_le_da_igual and estado.hora == "11:00"

    reserva.anotar_resultado(estado, "consultar_disponibilidad",
                             {"fecha": "2026-09-15"}, {"ok": True, "huecos": ["10:00", "11:00"]})

    assert estado.hora == "11:00"


def test_el_dia_que_dice_ella_no_se_cambia(api_module):  # noqa: F811
    """Si ella ha dicho el 16, mirar el 15 para ofrecer no se lo cambia."""
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Corte señora"
    estado.dia_le_da_igual = True
    estado.fecha = "2026-09-16"
    estado.fecha_de_ella = True

    reserva.anotar_resultado(estado, "consultar_disponibilidad",
                             {"fecha": "2026-09-15"}, {"ok": True, "huecos": ["10:00"]})

    assert (estado.fecha, estado.hora) == ("2026-09-16", "")


def test_el_nombre_entra_en_cuanto_lo_dice_y_la_cita_se_cierra(api_module):  # noqa: F811
    """Con dia y hora puestos, "me llamo Ana Ruiz" ya es todo lo que hace falta."""
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Corte señora"
    estado.fecha = "2026-09-15"
    estado.hora = "10:00"

    reserva.anotar_lo_que_dice(estado, "me llamo Ana Ruiz")

    assert estado.nombre == "Ana Ruiz"
    assert reserva.que_falta(estado) == ""
    assert reserva.tool_que_remata(estado) == "crear_cita"


@pytest.mark.parametrize("texto,nombre", [
    ("me llamo Ana Ruiz", "Ana Ruiz"),
    ("Me llamo ana ruiz", "Ana Ruiz"),
    ("hola, mi nombre es María José García", "María José García"),
    ("me llamo Ana y quiero un corte", "Ana"),
    ("me llamo Lucía, gracias", "Lucía"),
    ("me llamo Ana de la Fuente", "Ana de la Fuente"),
])
def test_se_saca_el_nombre_cuando_lo_dice(api_module, texto, nombre):  # noqa: F811
    from backend import reserva

    assert reserva.nombre_que_dice(texto) == nombre


@pytest.mark.parametrize("texto", [
    "soy de Elche",
    "soy alergica al tinte",
    "la primera que tengas",
    "mi hija se llama Ana",
    "me llamo",
    "me llamo la clienta",
])
def test_no_se_inventa_un_nombre(api_module, texto):  # noqa: F811
    from backend import reserva

    assert reserva.nombre_que_dice(texto) == "", texto


def test_el_primer_hueco_de_hoy_deja_margen(api_module):  # noqa: F811
    """A las 17:35, las 17:45 no son "la primera que tengas": no da tiempo."""
    from backend import reserva

    ahora = datetime.datetime(2026, 9, 11, 17, 35)
    assert reserva.huecos_con_margen("2026-09-11", ["17:45", "18:30", "19:00"], ahora) == ["19:00"]
    assert reserva.huecos_con_margen("2026-09-15", ["10:00"], ahora) == ["10:00"]
    tarde = datetime.datetime(2026, 9, 11, 23, 30)
    assert reserva.huecos_con_margen("2026-09-11", ["23:45"], tarde) == []


def test_si_el_modelo_mira_hoy_no_se_le_coge_lo_que_no_da_tiempo(api_module):  # noqa: F811
    """Con el arreglo a medias, a las 17:55 se le proponia hoy a las 18:00."""
    from backend import reserva

    ahora = datetime.datetime(2026, 9, 11, 17, 55)
    estado = _eligiendo_el_codigo()
    reserva.anotar_resultado(estado, "consultar_disponibilidad", {"fecha": "2026-09-11"},
                             {"ok": True, "huecos": ["18:00", "18:30", "19:00"]}, ahora=ahora)
    assert (estado.fecha, estado.hora) == ("2026-09-11", "19:00")

    estado = _eligiendo_el_codigo()
    antes = (estado.fecha, estado.hora)
    reserva.anotar_resultado(estado, "consultar_disponibilidad", {"fecha": "2026-09-11"},
                             {"ok": True, "huecos": ["18:00", "18:30"]}, ahora=ahora)
    assert (estado.fecha, estado.hora) == antes, "nada de hoy da tiempo: no se cambia"


def test_la_primera_de_hoy_que_ya_no_da_tiempo_no_se_coge(api_module, monkeypatch):  # noqa: F811
    """Si lo que hay sobre la mesa empieza ya, el agente busca el siguiente de verdad."""
    from backend import reserva

    monkeypatch.setattr(reserva, "ahora_local",
                        lambda zona="": datetime.datetime(2026, 9, 11, 17, 55))
    estado = reserva.Estado()
    reserva.anotar_intencion(estado, "reservar")
    estado.servicio = "Corte señora"
    estado.huecos = ["18:00", "18:30"]
    estado.fecha_de_los_huecos = "2026-09-11"

    reserva.anotar_lo_que_dice(estado, "la primera que tengas", "Europe/Madrid")

    assert estado.hora == ""
    assert estado.huecos == [], "sin huecos sobre la mesa, el agente busca el primero con margen"


def test_con_el_hueco_elegido_se_propone_y_se_pide_el_nombre(api_module):  # noqa: F811
    """Sin decirselo, el modelo miraba otro dia y le volvia a ensenar horas."""
    from backend import reserva

    estado = _eligiendo_el_codigo()
    texto = reserva.instruccion_de_cierre(estado)

    assert "17:45" in texto and "11 de septiembre" in texto
    assert "nombre" in texto and "NO mires otros dias" in texto
