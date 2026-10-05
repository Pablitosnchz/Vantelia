# -*- coding: utf-8 -*-
"""Lo que salio de analizar las llamadas de Sara del 5-oct-2026 (24 llamadas, 9:32-13:18).

POR QUE EXISTE
--------------
- 7 de 12 conversaciones reales se cortaron justo tras "¿quien coge el telefono?", preguntado a
  la recepcion: ahora se le pide solo a donde mandar la demo para quien decide (los tests del
  guion estan en test_sara_centralitas.py y test_captacion_voz.py).
- "Para español, pulse 1" (Madrid Vascular): Sara colgaba en el menu. Ahora puede pulsar.
- Un ayuntamiento y un laboratorio de protesis en la lista, y sectores que eran la busqueda que
  los encontro, no lo que son ("Clinica Madrid Vascular" como clinica veterinaria).
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_captacion_voz import captacion  # noqa: F401
from test_lanzador_llamadas import MARTES_10_30, _prospecto, lanzador  # noqa: F401


# --- Menus de teclas ------------------------------------------------------------------

@pytest.mark.parametrize("entrada", [False, True])
def test_las_dos_saras_pueden_pulsar_una_tecla(captacion, entrada):  # noqa: F811
    config = captacion.agente_de_captacion("https://app.test", entrada=entrada)["conversation_config"]
    teclas = [t for t in config["agent"]["prompt"]["tools"] if t["name"] == "play_keypad_touch_tone"]
    assert teclas and teclas[0]["params"]["system_tool_type"] == "play_keypad_touch_tone"
    assert "una sola vez" in teclas[0]["description"]
    # Un "hola" suelto no corta a ninguna de las dos.
    assert "hola" in config["turn"]["interruption_ignore_terms"]


# --- A quien se llama -----------------------------------------------------------------

@pytest.mark.parametrize("negocio,sector,esperado", [
    ("Clínica Madrid Vascular", "clinica veterinaria", "clinica"),   # la busqueda la puso de veterinaria
    ("DST Clinic", "clinica dental", "clinica dental"),              # "clinic" a secas no tapa lo concreto
    ("Kenika Thai Massage", "centro de masajes", "centro de masajes"),
    ("Clínica Dental Reyes 9", "clinica estetica", "clinica dental"),
    ("Purificación Caballero", "peluqueria", "peluqueria"),          # sin pistas en el nombre: la captacion
    ("Fisio Henares", "clinica veterinaria", "fisioterapia"),
])
def test_el_sector_sale_del_nombre_si_lo_dice(lanzador, negocio, sector, esperado):  # noqa: F811
    assert lanzador.sector_real(negocio, sector) == esperado


@pytest.mark.parametrize("negocio,sector", [
    ("Centro de tratamiento de adicciones", "clinica veterinaria"),   # un ayuntamiento, 5-oct
    ("Laboratorio Prótesis Dentales Béticos SL", "clinica estetica"),  # no da citas, 5-oct
    ("Farmacia Central", "clinica"),
    ("Depósito Dental Madrid", "clinica dental"),
])
def test_lo_que_no_da_citas_no_se_llama_aunque_el_sector_diga_otra_cosa(lanzador, negocio, sector):  # noqa: F811
    assert lanzador.da_citas(negocio, sector) is False


def test_la_lista_de_llamadas_sale_limpia_y_con_el_sector_corregido(lanzador):  # noqa: F811
    _prospecto(lanzador, "lab@x.es", "954281145", negocio="Laboratorio Prótesis Dentales Béticos SL",
               sector="clinica estetica")
    _prospecto(lanzador, "plan@x.es", "916349465", negocio="Centro de tratamiento de adicciones",
               sector="clinica veterinaria")
    _prospecto(lanzador, "vascular@x.es", "910004960", negocio="Clínica Madrid Vascular",
               sector="clinica veterinaria")
    elegidos = lanzador.candidatos(MARTES_10_30)
    assert [c["negocio"] for c in elegidos] == ["Clínica Madrid Vascular"]
    assert elegidos[0]["sector"] == "clinica", "Sara no la trata de veterinaria"
