# -*- coding: utf-8 -*-
"""Nada construido y sin enchufar.

POR QUE EXISTE
--------------
El 25 y 26 de agosto de 2026 aparecieron CUATRO cosas escritas, probadas a mano y
desconectadas. Ninguna daba error: el codigo compilaba y los tests pasaban.

  * `_work_intervals_of` calculaba los ratos libres de un pack... y no la llamaba
    nadie. El panel pintaba los packs macizos y el salon creia tener la tarde
    entera cogida.
  * `work_intervals` estaba declarado en el modelo equivocado.
  * `_valoracion_en_lugar_del_tratamiento` evitaba coger un tratamiento de cuatro
    horas a quien preguntaba el precio... y tampoco la llamaba nadie.
  * El modelo que el negocio elige en su panel no lo leia nadie.

Cuatro veces la misma clase de fallo, y las cuatro se encontraron por casualidad.
Este test las encuentra sola.

QUE NO CUENTA COMO MUERTO: lo que llama el framework (endpoints de FastAPI,
middlewares, fixtures de pytest, manejadores de arranque). Que nadie los llame por
su nombre es lo normal.

SI TE FALLA: o enchufas la funcion donde tenia que ir, o la borras. Dejarla es lo
que ha costado los cuatro incidentes.
"""
from __future__ import annotations

import collections
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[1]
LLAMA_EL_FRAMEWORK = re.compile(
    r"@(app|router|pytest|asynccontextmanager|contextmanager|staticmethod|property)")


def _ficheros():
    fuentes = sorted(p for p in (RAIZ / "backend").rglob("*.py"))
    for suelto in ("api.py", "api_models.py"):
        if (RAIZ / suelto).exists():
            fuentes.append(RAIZ / suelto)
    mirones = []
    for carpeta in ("tests", "scripts", "evals"):
        mirones.extend(sorted((RAIZ / carpeta).rglob("*.py")))
    return fuentes, mirones


def test_no_hay_funciones_construidas_y_sin_enchufar():
    fuentes, mirones = _ficheros()
    textos = {p: p.read_text(encoding="utf-8", errors="replace") for p in fuentes + mirones}

    usos = collections.Counter()
    for texto in textos.values():
        usos.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", texto))

    sueltas = []
    for p in fuentes:
        lineas = textos[p].split(chr(10))
        for i, linea in enumerate(lineas):
            encontrado = re.match(r"^(?:async )?def ([a-z_][A-Za-z0-9_]*)\(", linea)
            if not encontrado:
                continue
            nombre = encontrado.group(1)
            if LLAMA_EL_FRAMEWORK.search(chr(10).join(lineas[max(0, i - 6):i])):
                continue
            if usos[nombre] <= 1:   # solo su propia definicion
                sueltas.append("%s (%s:%d)" % (nombre, p.relative_to(RAIZ), i + 1))

    assert not sueltas, (
        "Construido y sin enchufar. O va a algun sitio, o sobra:" + chr(10)
        + chr(10).join("  - " + s for s in sueltas)
    )


def test_una_sola_forma_de_normalizar_texto():
    """`_norm` estaba COPIADA identica en tres modulos.

    Tres sitios donde arreglar el mismo caso raro, y de ahi salen los "aqui si
    funciona y alli no". Ahora los tres delegan en `textnorm.normalizar`.
    """
    from backend import catalog_pick, intents, rules, textnorm

    raro = "  MECHAS   Balayage  ÑOÑO  "
    esperado = textnorm.normalizar(raro)
    assert esperado == "mechas balayage nono"
    assert catalog_pick._norm(raro) == esperado
    assert intents._norm(raro) == esperado
    assert rules._norm(raro) == esperado
