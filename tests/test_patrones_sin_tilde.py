"""Los patrones que casan lo que ESCRIBE el cliente no pueden llevar tildes.

Trampa real: al acentuar los textos del asistente se acentuo tambien la lista de
frases de `_message_requests_payment` ("pagar la senal" -> "pagar la señal").
Esa lista se compara contra el mensaje pasado por `textnorm._strip_accents`, o
sea SIN tildes, asi que la frase con tilde no casa nunca y el cliente que pedia
pagar dejaba de recibir su enlace. En silencio: sin error, sin log.

La regla: si una funcion normaliza el mensaje con `_strip_accents`, sus literales
de comparacion van sin tildes.
"""
from __future__ import annotations

import ast
import pathlib
import re
import unicodedata

REPO = pathlib.Path(__file__).resolve().parents[1]
RAIZ = REPO / "backend"

# Funciones que normalizan la entrada y ademas comparan contra literales. Se
# detectan solas; esto solo excluye lo que compara contra datos, no contra frases.
IGNORAR_LITERALES = {"", " ", ",", ".", "-", "_", "/"}


def _tiene_tilde(texto: str) -> bool:
    return any(unicodedata.category(c) == "Mn" for c in unicodedata.normalize("NFD", texto))


def _funciones_que_normalizan(ruta: pathlib.Path):
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        fuente = ast.dump(nodo)
        if "_strip_accents" not in fuente:
            continue
        yield nodo


def _cadenas(nodo):
    for sub in ast.walk(nodo):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield sub.lineno, sub.value


def _literales_comparados(nodo):
    """Solo los literales que actuan de PATRON, no los que se devuelven.

    Dos formas: `"frase" in text` (el literal es el lado izquierdo de un `in`) y
    `any(f in text for f in ("frase", ...))` (el literal esta en el iterable de
    una comprehension). Una tupla suelta como `return ("clave", "texto largo")`
    no entra, que es texto de respuesta y ahi las tildes SI van.
    """
    for hijo in ast.walk(nodo):
        if isinstance(hijo, ast.Compare) and any(
            isinstance(op, (ast.In, ast.NotIn)) for op in hijo.ops
        ):
            for linea, valor in _cadenas(hijo.left):
                yield linea, valor
        elif isinstance(hijo, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
            for gen in hijo.generators:
                if isinstance(gen.iter, (ast.Tuple, ast.List, ast.Set)):
                    for elem in gen.iter.elts:
                        for linea, valor in _cadenas(elem):
                            yield linea, valor


def test_ningun_patron_de_intencion_lleva_tilde():
    fallos = []
    for ruta in sorted(RAIZ.glob("*.py")):
        for nodo in _funciones_que_normalizan(ruta):
            for linea, valor in _literales_comparados(nodo):
                if valor in IGNORAR_LITERALES or not _tiene_tilde(valor):
                    continue
                fallos.append("%s:%d  %s()  %r" % (ruta.name, linea, nodo.name, valor))
    assert not fallos, (
        "Patrones con tilde comparados contra texto ya normalizado sin tildes; "
        "no casaran nunca:\n  " + "\n  ".join(sorted(set(fallos)))
    )


def test_la_intencion_comercial_entiende_las_tildes():
    """El cliente escribe "recomendación", no "recomendacion".

    `COMMERCIAL_INTENT_PATTERNS` llevaba texto con doble codificacion y la
    entrada no se normalizaba, asi que la unica forma de activar el recomendador
    era escribirlo SIN tilde.
    """
    from backend import chat

    assert chat._detect_commercial_intent("quiero una recomendación") == "recomendador"
    assert chat._detect_commercial_intent("hazme una estimación") == "estimador"
    assert chat._detect_commercial_intent("¿cuánto cuesta?") == "estimador"
    assert chat._detect_commercial_intent("hola buenas") == ""


# "Ã"/"Â" seguidos de un simbolo: firma de UTF-8 leido como latin-1 y reguardado.
MOJIBAKE = re.compile("[ÃÂ][-¿]")

# Unica excepcion: el comentario que ilustra el mojibake que esa funcion REPARA.
MOJIBAKE_PERMITIDO = {"backend/voice.py"}


def test_no_hay_texto_con_doble_codificacion():
    """Una tilde doblemente codificada no casa nada y se ve rota al mostrarla.

    Aparecio en cuatro patrones de intencion comercial, en un error del panel
    (el error de plan del asistente de voz) y en el manual de admin.
    """
    fallos = []
    for carpeta in ("backend", "tests", "scripts", "docs", "app_ui", "admin_ui", "widget"):
        base = REPO / carpeta
        if not base.exists():
            continue
        for fichero in base.rglob("*"):
            if fichero.suffix not in (".py", ".js", ".html", ".md", ".json"):
                continue
            if "__pycache__" in str(fichero):
                continue
            relativo = fichero.relative_to(REPO).as_posix()
            if relativo in MOJIBAKE_PERMITIDO:
                continue
            try:
                texto = fichero.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for numero, linea in enumerate(texto.splitlines(), 1):
                if MOJIBAKE.search(linea):
                    fallos.append("%s:%d  %s" % (relativo, numero, linea.strip()[:80]))
    assert not fallos, "Texto con doble codificacion UTF-8:\n  " + "\n  ".join(fallos[:20])
