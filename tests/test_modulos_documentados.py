"""Los modulos grandes de backend llevan un indice en su docstring.

No es cosmetica: en un fichero de 5.000 lineas, saber por que funcion se entra
es la diferencia entre tocar el sitio correcto y reimplementar algo que ya
existe (cosa que ya ha pasado con los cores de reserva).

El umbral es alto a proposito. Un modulo pequeno se lee entero; uno de 700
lineas ya no.
"""
from __future__ import annotations

import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1] / "backend"

LINEAS_MINIMAS = 600      # a partir de aqui el modulo no se lee de una sentada
DOC_MINIMO = 3            # lineas de docstring: un titulo suelto no orienta


def _modulos():
    for ruta in sorted(RAIZ.rglob("*.py")):
        if ruta.name == "__init__.py":
            continue
        src = ruta.read_text(encoding="utf-8")
        if len(src.splitlines()) < LINEAS_MINIMAS:
            continue
        yield ruta, ast.get_docstring(ast.parse(src)) or ""


def test_los_modulos_grandes_dicen_por_donde_entrar():
    faltan = [
        "%s (%d lineas de codigo, %d de docstring)"
        % (ruta.relative_to(RAIZ.parent), len(ruta.read_text(encoding="utf-8").splitlines()),
           len(doc.splitlines()))
        for ruta, doc in _modulos()
        if len(doc.splitlines()) < DOC_MINIMO
    ]
    assert not faltan, (
        "Modulos grandes sin indice en el docstring. Escribe que hace el modulo y "
        "una tabla de 'quiero hacer X -> esta funcion':\n  " + "\n  ".join(faltan)
    )
