"""Lo que cita `docs/MAPA_DEL_CODIGO.md` tiene que existir de verdad.

Un mapa desactualizado es peor que no tener mapa: manda a abrir un fichero que
ya no esta o a llamar a una funcion que se renombro, y cuesta mas tiempo que
buscar a ciegas. Esto lo mantiene honesto sin esfuerzo: cada `modulo.funcion` y
cada ruta de fichero que aparezcan entre comillas invertidas se comprueban.

Si falla, la respuesta casi nunca es tocar el test: es que el codigo se movio y
el mapa se quedo atras.
"""
from __future__ import annotations

import ast
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[1]
DOCS = [RAIZ / "docs" / "MAPA_DEL_CODIGO.md", RAIZ / "tests" / "README.md"]

# `modulo.funcion` o `modulo.CONSTANTE`. El (?!py|md|json|js) evita casar el
# nombre de un fichero suelto ("`voice.py`") como si fuera un atributo.
REF = re.compile(r"`([a-z][a-z0-9_]*)\.(?!py`|md`|json`|js`|txt`)([A-Za-z_][A-Za-z0-9_]*)`")
# rutas de fichero citadas: `backend/algo.py`, `tests/algo.py`, `docs/algo.md`
RUTA = re.compile(r"`((?:backend|tests|docs|scripts|widget|app_ui)/[A-Za-z0-9_./-]+)`")

# Prefijos que parecen modulo pero no lo son (tablas, objetos de config, JS).
NO_SON_MODULOS = {
    "config", "row", "self", "app", "window", "data", "npm", "python", "git",
    "services", "bookings", "employees", "package_purchases", "gift_cards",
    "customer_payments", "booking_payments", "products", "packages", "locations",
    "resources", "users", "e", "i", "n", "x",
}


def _texto_docs():
    for ruta in DOCS:
        if ruta.exists():
            yield ruta, ruta.read_text(encoding="utf-8")


def _nombres_de_modulo(nombre):
    """Nombres de primer nivel definidos en backend/<nombre>.py, o None."""
    fichero = RAIZ / "backend" / ("%s.py" % nombre)
    if not fichero.exists():
        return None
    arbol = ast.parse(fichero.read_text(encoding="utf-8"))
    nombres = set()
    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nombres.add(nodo.name)
        elif isinstance(nodo, ast.Assign):
            for destino in nodo.targets:
                if isinstance(destino, ast.Name):
                    nombres.add(destino.id)
        elif isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
            nombres.add(nodo.target.id)
    return nombres


def test_las_funciones_que_cita_el_mapa_existen():
    fallos = []
    cache = {}
    for ruta, texto in _texto_docs():
        for modulo, atributo in REF.findall(texto):
            if modulo in NO_SON_MODULOS:
                continue
            if modulo not in cache:
                cache[modulo] = _nombres_de_modulo(modulo)
            nombres = cache[modulo]
            if nombres is None:
                continue  # no es un modulo de backend; puede ser cualquier otra cosa
            if atributo not in nombres:
                fallos.append("%s: `%s.%s` no existe en backend/%s.py"
                              % (ruta.name, modulo, atributo, modulo))
    assert not fallos, "El mapa cita codigo que ya no esta:\n  " + "\n  ".join(sorted(set(fallos)))


def test_los_docstrings_de_modulo_no_citan_funciones_fantasma():
    """Los indices que llevan los modulos grandes envejecen igual que el mapa.

    Solo se comprueban las referencias a OTRO modulo (`agenda._build_slots_for_day`
    citado desde `booking.py`): las que un modulo hace a lo suyo van sin prefijo y
    no hay forma barata de distinguirlas de un nombre cualquiera entre comillas.
    """
    fallos = []
    cache = {}
    for fichero in sorted((RAIZ / "backend").rglob("*.py")):
        doc = ast.get_docstring(ast.parse(fichero.read_text(encoding="utf-8"))) or ""
        for modulo, atributo in REF.findall(doc):
            if modulo in NO_SON_MODULOS or modulo == fichero.stem:
                continue
            if modulo not in cache:
                cache[modulo] = _nombres_de_modulo(modulo)
            nombres = cache[modulo]
            if nombres is not None and atributo not in nombres:
                fallos.append("%s cita `%s.%s`, que no existe" % (fichero.name, modulo, atributo))
    assert not fallos, "Docstrings desactualizados:\n  " + "\n  ".join(sorted(set(fallos)))


def test_los_ficheros_que_cita_el_mapa_existen():
    fallos = [
        "%s: `%s`" % (ruta.name, cita)
        for ruta, texto in _texto_docs()
        for cita in RUTA.findall(texto)
        if not (RAIZ / cita).exists() and "*" not in cita
    ]
    assert not fallos, "El mapa cita ficheros que no estan:\n  " + "\n  ".join(sorted(set(fallos)))


def test_todos_los_modulos_estan_en_la_tabla_de_arquitectura():
    """`docs/ARQUITECTURA.md` tiene que nombrar todo lo que hay en `backend/`.

    Su tabla se quedo con la foto del refactor y para cuando se reviso faltaban
    doce modulos, entre ellos `commerce` (el segundo mas grande) y `paystate`
    (la fuente unica del estado de cobro). Quien llegue nuevo lee esa tabla y da
    por hecho que lo que no sale, no existe.
    """
    doc = (RAIZ / "docs" / "ARQUITECTURA.md").read_text(encoding="utf-8")
    faltan = [
        fichero.stem
        for fichero in sorted((RAIZ / "backend").glob("*.py"))
        if fichero.stem != "__init__" and ("`%s.py`" % fichero.stem) not in doc
        and ("backend/%s.py" % fichero.stem) not in doc
    ]
    assert not faltan, (
        "Modulos de backend/ que no aparecen en la tabla de docs/ARQUITECTURA.md:\n  "
        + ", ".join(faltan)
    )


def test_claude_md_no_cita_ficheros_que_no_estan():
    """`CLAUDE.md` es lo primero que lee un agente: no puede mandar a un doc muerto.

    Citaba `docs/MANUAL_GOOGLE_CALENDAR.md`, borrado cuando la agenda paso a ser
    interna (de esa integracion solo quedan campos vacios en la config).
    """
    texto = (RAIZ / "CLAUDE.md").read_text(encoding="utf-8")
    citas = sorted(set(re.findall(
        r"`((?:docs|tests|scripts|deploy|backend|widget|app_ui|admin_ui)/[A-Za-z0-9_./-]+)`", texto
    )))
    faltan = [cita for cita in citas if not (RAIZ / cita).exists()]
    assert not faltan, "CLAUDE.md cita ficheros que no existen:\n  " + "\n  ".join(faltan)
