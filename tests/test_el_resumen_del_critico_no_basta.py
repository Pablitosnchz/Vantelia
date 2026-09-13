# -*- coding: utf-8 -*-
"""El caso crítico no se aprueba con CUALQUIER resumen.

POR QUE EXISTE
--------------
13-sep-2026. Midiendo el mismo banco con el código de producción (bd7a6da) como
referencia, `dice-que-si-y-acaba-en-cita` salió «OK tras reintento». Leída la
conversación, el resumen aprobado era:

    🛍️ Acido lactico bio premium corto · ⏱️ 1 h 30 min · 👤 clienta · fianza 50 €

A una clienta que había dicho «no lo tengo claro» se le eligió la técnica (lo que
prohíbe `no-elige-la-tecnica-por-ella`) y, habiendo escrito «me llamo Ana Ruiz
Perez», el resumen iba a nombre de «clienta». El caso solo exigía que apareciera
«Resumen de tu cita»: un falso aprobado del instrumento. La decisión de Alicia
(confirmada el 13-sep) es que quien no sabe qué alisado quiere va a la cita de
diagnóstico, así que el resumen bueno es ese y a su nombre.
"""
from __future__ import annotations


def _caso():
    from evals.casos_asistente import CASOS

    return next(c for c in CASOS if c["id"] == "dice-que-si-y-acaba-en-cita")


def test_el_resumen_con_la_tecnica_elegida_por_ella_no_aprueba():
    from scripts.evaluar_asistente import _norm

    caso = _caso()
    assert caso.get("no_debe_en") == "ultima", "las tecnicas se nombran bien al principio"
    resumen_malo = ("📋 *Resumen de tu cita* | 👤 clienta | 🛍️ Acido lactico bio premium corto"
                    " | ⏱️ 1 h 30 min | ¿Confirmamos la cita?")
    assert any(_norm(p) in _norm(resumen_malo) for p in caso["no_debe"]), (
        "el falso aprobado de la referencia volveria a contar como OK")


def test_el_resumen_del_diagnostico_a_su_nombre_aprueba():
    from scripts.evaluar_asistente import _norm

    caso = _caso()
    resumen_bueno = ("📋 *Resumen de tu cita* | 👤 Ana Ruiz Perez | 🛍️ Diagnostico y presupuesto"
                     " | ⏱️ 15 min | 📅 martes 15 de septiembre | 🕐 15:00 | ¿Confirmamos la cita?")
    assert any(_norm(p) in _norm(resumen_bueno) for p in caso["debe"])
    assert not any(_norm(p) in _norm(resumen_bueno) for p in caso["no_debe"]), (
        "el resumen correcto quedaria castigado")
