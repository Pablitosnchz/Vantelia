# -*- coding: utf-8 -*-
"""Ningun modulo usa un nombre que no ha importado.

POR QUE EXISTE
--------------
2-sep-2026. El freno que impide soltar la duracion sin que la pidan -la queja
literal de la duenya del salon: "no le he preguntado nada del tiempo que dura,
todo eso no tiene que decirlo"- se escribio, se probo y se dio por bueno.

Pero llamaba a `booking.pidio_la_duracion_en_la_conversacion(...)` dentro de
`agent.responder`, y esa funcion importa `reserva, timeutils, trazas, agenda`.
`booking` NO. En cuanto el freno tenia que actuar, `NameError`.

Es decir: el freno no fallaba a veces. No funciono NUNCA, y encima reventaba
justo en el caso que venia a arreglar. Los tests no lo vieron porque ninguno
llegaba a esa rama con las dos condiciones a la vez.

`python -m pyflakes backend/ api.py` lo cantaba desde el primer dia. Estaba en la
lista de comprobaciones minimas del CLAUDE.md y no lo corria nadie. Una
comprobacion que hay que acordarse de lanzar no es una comprobacion.

ACOTADO: solo nombres SIN DEFINIR, que son los que revientan en produccion. Los
otros ~750 avisos de pyflakes (imports sin usar, sobre todo) no se vigilan aqui:
meter ruido en un test es la forma mas rapida de que acabe desactivado.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def test_pyflakes_no_encuentra_nombres_sin_definir():
    try:
        salida = subprocess.run(
            [sys.executable, "-m", "pyflakes", "backend", "api.py"],
            cwd=str(RAIZ), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        ).stdout.decode("utf-8", "replace")
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("pyflakes no instalado")

    if "No module named" in salida and "pyflakes" in salida:  # pragma: no cover
        pytest.skip("pyflakes no instalado")

    # "unable to detect undefined names" es el aviso de los `import *` de los
    # routers, no un nombre roto. Se distingue por la comilla del nombre.
    rotos = [ln for ln in salida.splitlines() if "undefined name '" in ln]

    assert not rotos, (
        "hay nombres usados sin importar; revientan en cuanto se ejecuta esa "
        "rama:\n  " + "\n  ".join(rotos)
    )


def test_ningun_patron_lleva_un_backspace_dentro():
    """Un regex con un backspace compila, no casa nada, y nadie se entera.

    Esto ha pasado CUATRO veces en una sola noche (3-sep-2026). Al generar
    codigo, `chr(92) + "b"` acaba dentro de una cadena SIN el prefijo `r`:

        re.compile("BORDE(dejalo|lo dejo|...)")     <- BORDE = backslash + b

    Python lo lee como el caracter de retroceso (0x08), el modulo importa sin una
    sola queja, `pyflakes` no dice nada, y el freno que depende de ese patron
    simplemente no salta nunca. Uno de ellos -el que impide soltar la duracion sin
    que la pidan- llego asi a produccion.

    Un `` de verdad se escribe `r"..."`. Este test mira el BYTE, que es lo unico
    que no se puede fingir.
    """
    sospechosos = []
    for ruta in sorted(RAIZ.joinpath("backend").rglob("*.py")):
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        for numero, linea in enumerate(texto.splitlines(), 1):
            if "" in linea:
                sospechosos.append("%s:%d" % (ruta.name, numero))

    assert not sospechosos, (
        "hay un caracter de retroceso (0x08) en el codigo; casi seguro es un "
        "regex que perdio el prefijo r. Ficheros y lineas: "
        + ", ".join(sospechosos))
