# -*- coding: utf-8 -*-
"""«Nueva cita» del portal: cuando no sale ningún hueco, dice POR QUÉ con la verdad.

POR QUE EXISTE
--------------
Prueba de Alicia en su agenda, 17-sep-2026 a las 13:20: eligió «Pack grey blending medio» (7 h 20
min) con Lorena, que tenía la agenda vacía hasta las 20:30, y el portal contestó «La jornada de
hoy ya ha terminado». No había terminado: ese servicio ya no cabía antes del cierre. Un mensaje
falso sobre la agenda hace pensar que la herramienta está rota (su mensaje: «me dice que ya hemos
terminado la jornada cuando está la agenda vacía»).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


def _panel():
    return (Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")


def _mensaje(**datos):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node no disponible para ejecutar el JavaScript del portal")
    fuente = _panel()
    trozos = []
    for nombre in ("nbMinutos", "nbDuracionTexto", "nbPorQueNoHayHuecos"):
        encontrada = re.search(r"^function " + nombre + r"\(.*?^\}", fuente, re.S | re.M)
        assert encontrada, "no existe la funcion %s en el panel" % nombre
        trozos.append(encontrada.group())
    trozos.append("process.stdout.write(nbPorQueNoHayHuecos(%s));" % json.dumps(datos))
    salida = subprocess.run([node, "-e", "\n".join(trozos)], check=True, capture_output=True, text=True,
                            encoding="utf-8")
    return salida.stdout


JUEVES = {"start": "10:00", "end": "20:30"}


def test_un_servicio_largo_que_no_cabe_hoy_no_dice_que_la_jornada_ha_terminado():
    texto = _mensaje(fecha="2026-09-17", hoy="2026-09-17", ahoraMin=13 * 60 + 20, ventana=JUEVES, dur=440,
                     servicio="Pack grey blending medio", quien="Lorena", sinTramos=True)
    assert "jornada de hoy ya ha terminado" not in texto
    assert texto == "Pack grey blending medio dura 7 h 20 min y hoy ya no cabe antes del cierre de Lorena (20:30)."


def test_despues_del_cierre_si_ha_terminado():
    texto = _mensaje(fecha="2026-09-17", hoy="2026-09-17", ahoraMin=20 * 60 + 45, ventana=JUEVES, dur=20,
                     servicio="Corte señora", quien="Lorena", sinTramos=True)
    assert texto == "La jornada de hoy ya ha terminado."


def test_otro_dia_mas_corto_que_el_servicio():
    texto = _mensaje(fecha="2026-09-18", hoy="2026-09-17", ahoraMin=13 * 60, ventana={"start": "09:00", "end": "14:00"},
                     dur=440, servicio="Pack grey blending medio", quien="", sinTramos=True)
    assert texto == "Pack grey blending medio dura 7 h 20 min y no cabe en la jornada de ese día (09:00 a 14:00)."


def test_si_cabe_pero_esta_todo_ocupado_no_culpa_a_la_duracion():
    lleno = _mensaje(fecha="2026-09-22", hoy="2026-09-17", ahoraMin=13 * 60, ventana={"start": "10:00", "end": "18:30"},
                     dur=20, servicio="Corte señora", quien="Conchi", sinTramos=False)
    assert lleno == "No queda ningún hueco de 20 min ese día."
    sin_tramos = _mensaje(fecha="2026-09-22", hoy="2026-09-17", ahoraMin=13 * 60,
                          ventana={"start": "10:00", "end": "18:30"}, dur=20, servicio="Corte señora", quien="",
                          sinTramos=True)
    assert sin_tramos == "Ese día no queda ningún hueco de 20 min para este servicio."
    assert "no hay agenda" not in sin_tramos


def test_el_formulario_usa_la_explicacion():
    fuente = _panel()
    cargar = fuente.split("async function loadNbSlots(", 1)[1].split("\nfunction closeNewBookingDrawer", 1)[0]
    assert "nbPorQueNoHayHuecos(" in cargar
    assert "La jornada de hoy ya ha terminado." not in cargar, "el mensaje fijo sigue en el formulario"
