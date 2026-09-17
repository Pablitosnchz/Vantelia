# -*- coding: utf-8 -*-
"""«Nueva cita» del portal: lo que la dueña del salón encontró incómodo o engañoso.

POR QUE EXISTE
--------------
Vídeo de Alicia del 17-sep-2026 comparando nuestro portal con su programa de siempre
(PeluGest, agenda de pinchar y escribir). Tres cosas, y dos eran fallos nuestros:

* El formulario se quedaba con el servicio de la cita ANTERIOR y había que borrarlo cada vez:
  `openNewBookingDrawer` limpiaba nombre, email, teléfono y notas, pero no el servicio.
* «No me salen todos»: con 169 servicios, la lista enseñaba OCHO sin decir que había más.
* Al abrir la ficha, el cursor saltaba al servicio con la lista desplegada. No lo quiere.

Y uno que no se veía: si lo escrito encajaba con VARIOS servicios («elumen» encaja con seis),
`nbSvcResuelto` devolvía vacío y la cita se creaba SIN servicio, de 30 minutos por defecto. Una
cita de dos horas apuntada como media hora es justo lo que descuadra la agenda.
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


def _funcion(fuente, nombre):
    encontrada = re.search(r"^function " + nombre + r"\(.*?^\}", fuente, re.S | re.M)
    assert encontrada, "no existe la funcion %s en el panel" % nombre
    return encontrada.group()


def _node(trozos, prueba):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node no disponible para ejecutar el JavaScript del portal")
    salida = subprocess.run([node, "-e", "\n".join(trozos + [prueba])], check=True, capture_output=True,
                            text=True, encoding="utf-8")
    return salida.stdout


def test_al_abrir_la_ficha_no_queda_el_servicio_de_la_cita_anterior():
    abrir = _panel().split("async function openNewBookingDrawer", 1)[1].split("\n}\n", 1)[0]
    limpiados = re.search(r"\[([^\]]*)\]\.forEach\(id => \{ document\.getElementById\(id\)\.value = ''", abrir)
    assert limpiados and "nbServicio" in limpiados.group(1), "el servicio anterior se queda puesto"


def test_al_abrir_la_ficha_el_cursor_no_salta_al_servicio():
    abrir = _panel().split("async function openNewBookingDrawer", 1)[1].split("\n}\n", 1)[0]
    assert "nbServicio').focus()" not in abrir.replace('"', "'"), "el foco salta al servicio"
    assert "campoSvc.focus()" not in abrir, "el foco salta al servicio"


def test_la_lista_ofrece_todo_el_catalogo_y_dice_cuantos_quedan():
    fuente = _panel()
    # Un catálogo del tamaño del suyo: con ocho no se nota que la lista se quedaba corta.
    catalogo = ([{"nombre": "Elumen %s" % t, "cat": "Trabajos de color", "dur": 15}
                 for t in ("corto", "corto-medio", "medio", "largo", "extra largo", "frontal")]
                + [{"nombre": "Pack elumen %s" % t, "cat": "Packs", "dur": 95}
                   for t in ("corto", "medio", "largo", "extra largo")]
                + [{"nombre": "Pack color raiz y elumen %s" % t, "cat": "Packs", "dur": 120}
                   for t in ("corto", "medio", "largo", "extra largo")]
                + [{"nombre": "Corte %s" % t, "cat": "Cortes", "dur": 20}
                   for t in ("señora", "hombre", "niño", "flequillo", "puntas", "mecha")])
    trozos = ["const nbServicios = %s;" % json.dumps(catalogo, ensure_ascii=False),
              _funcion(fuente, "nbSvcNorm"), _funcion(fuente, "nbSvcSugerencias")]
    salida = _node(trozos, "process.stdout.write(JSON.stringify(["
                           "nbSvcSugerencias('elumen').map(s => s.nombre),"
                           "nbSvcSugerencias('').length]));")
    elumen, vacio = json.loads(salida)
    assert len(elumen) == 14, "se pierden servicios que encajan (%d de 14): %s" % (len(elumen), elumen)
    assert vacio == len(catalogo), "con el campo vacío no se ofrece el catálogo entero"
    assert "NB_SVC_VISIBLES" in fuente and "más: escribe alguna letra" in fuente, "no dice cuántos quedan"
    assert re.search(r"\.nb-ac\.open \{[^}]*overflow-y:auto", fuente), "la lista larga no se puede recorrer"


@pytest.mark.parametrize("caso, espera", [
    ({"hora": "10:00", "nombre": "Ana Ruiz Perez", "completo": True,
      "svc": {"escrito": "elumen", "resuelto": "", "coincidencias": 6}},
     "Hay 6 servicios que encajan con «elumen»: elige uno en la lista."),
    ({"hora": "10:00", "nombre": "Ana Ruiz Perez", "completo": True,
      "svc": {"escrito": "masaje", "resuelto": "", "coincidencias": 0}},
     "No hay ningún servicio que se llame «masaje». Elígelo en la lista, o déjalo vacío para apuntarla sin servicio."),
    ({"hora": "", "nombre": "Ana", "completo": True, "svc": {"escrito": "", "resuelto": "", "coincidencias": 0}},
     "Elige una hora libre."),
    ({"hora": "10:00", "nombre": "", "completo": False, "svc": {"escrito": "", "resuelto": "", "coincidencias": 0}},
     "Falta el nombre del cliente."),
    ({"hora": "10:00", "nombre": "Ana Ruiz Perez", "completo": True,
      "svc": {"escrito": "Corte señora", "resuelto": "Corte señora", "coincidencias": 1}}, ""),
])
def test_dice_por_que_no_se_puede_crear(caso, espera):
    trozos = [_funcion(_panel(), "nbPorQueNoSePuedeCrear")]
    salida = _node(trozos, "process.stdout.write(nbPorQueNoSePuedeCrear(%s));" % json.dumps(caso, ensure_ascii=False))
    assert salida == espera


def test_con_el_servicio_a_medias_no_se_crea_una_cita_de_media_hora():
    """«elumen» encaja con catorce servicios: antes se mandaba servicio vacío y la cita salía de
    30 min sin avisar. El botón espera a que elija uno."""
    sync = _funcion(_panel(), "nbSyncConfirm")
    assert "nbPorQueNoSePuedeCrear(" in sync and "disabled = !!falta" in sync, (
        "el botón no depende de lo que falta: con un servicio a medias se crearía la cita")
    caso = {"hora": "10:00", "nombre": "Ana Ruiz Perez", "completo": True,
            "svc": {"escrito": "elumen", "resuelto": "", "coincidencias": 14},
            "rapida": False, "duracion": 0, "servicioRapido": ""}
    salida = _node([_funcion(_panel(), "nbPorQueNoSePuedeCrear")],
                   "process.stdout.write(nbPorQueNoSePuedeCrear(%s));" % json.dumps(caso, ensure_ascii=False))
    assert salida.startswith("Hay 14 servicios que encajan"), salida
