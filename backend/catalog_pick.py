# -*- coding: utf-8 -*-
"""Elegir el servicio que pide el cliente. Decide el CODIGO, no el modelo.

POR QUE EXISTE
--------------
La primera version le pedia al modelo que hiciera dos cosas a la vez: entender lo
que dice la clienta Y decidir que servicio es o que preguntar. Medido contra el
catalogo real de un salon (186 servicios), decidir se le daba mal y de forma
INCONSISTENTE entre ejecuciones:

* "un alisado. corto"      -> a veces elegia la tecnica el solo (hay TRES tipos,
                              con precios de 240 EUR a 260 EUR y procesos distintos)
* "quiero keratina. corto" -> a veces volvia a preguntar el largo, ya dicho
* "mechas. por los hombros"-> a veces no reconocia que eso es un largo

Arreglar un caso por prompt rompia otro. Y una vez llego a decir "te he
reservado" cuando aun faltaba el dia.

QUIEN HACE QUE
--------------
* El MODELO solo EXTRAE lo que la clienta ha dicho (`intents.extraer_datos_servicio`):
  familia, tecnica, largo, para quien. Eso se le da bien: es entender palabras.
* Este modulo DECIDE, mirando el catalogo real. Con los mismos datos siempre sale
  lo mismo, y es imposible que pregunte algo que ya le han dicho: se comprueba
  contra los datos, no contra la memoria del modelo.

El resultado es un `Eleccion`: o el servicio, o exactamente que falta por preguntar.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from backend import agenda, settings


def _norm(texto: str) -> str:
    limpio = unicodedata.normalize("NFKD", str(texto or "").lower())
    return " ".join("".join(c for c in limpio if not unicodedata.combining(c)).split())


# Tallas ordenadas de menos a mas. Cada una con las formas en que aparece en el
# NOMBRE de un servicio y en que la dice una clienta ("por los hombros").
_TALLAS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("muy corto", ("muy corto", "chico", "corto chico")),
    ("corto", ("corto", "corta", "por la barbilla", "a la altura de la barbilla", "bob")),
    ("corto medio", ("corto medio", "corto-medio")),
    # OJO: "media" a secas NO vale como talla. Casaba dentro de "Mechas MEDIA
    # cabeza" y elegia ese servicio para quien solo habia dicho "media melena".
    ("medio", ("medio", "media melena", "por los hombros", "a los hombros",
               "hasta los hombros")),
    ("medio largo", ("medio largo", "medio-largo", "ml")),
    ("largo", ("largo", "larga", "por el pecho", "xl")),
    ("extra largo", ("extra largo", "extralargo", "xxl", "por la cintura",
                     "muy largo", "extra extra largo")),
)

_TALLAS_ORDEN = [nombre for nombre, _ in _TALLAS]

# Lo que queda pegado al quitar una talla ("extra largo" deja "extra") y las
# marcas de tamaño sueltas que no dicen que servicio es.
_RESTOS_DE_TALLA = {"extra", "xl", "xxl", "ml", "1 1", "fleq"}

# Como lo dice la clienta -> como aparece en el catalogo. Un salon escribe
# "Corte señora", nadie escribe "Corte mujer".
_PARA_QUIEN = {
    "mujer": ("senora", "señora", "mujer", "chica", "dama"),
    "hombre": ("hombre", "caballero", "chico", "masculino"),
    "nino": ("nino", "niño", "nina", "niña", "infantil", "junior"),
}


def talla_de(texto: str) -> str:
    """La talla que menciona un texto, en su forma canonica. "" si ninguna.

    Se recorren de la mas especifica a la mas general ("corto medio" antes que
    "corto") para que "corto medio" no se lea como "corto".
    """
    limpio = _norm(texto)
    candidatas = []
    for canonica, formas in _TALLAS:
        for forma in formas:
            if re.search(r"\b%s\b" % re.escape(forma), limpio):
                candidatas.append((len(forma), canonica))
    if not candidatas:
        return ""
    candidatas.sort(reverse=True)  # gana la coincidencia mas larga
    return candidatas[0][1]


def tecnica_de(nombre: str) -> str:
    """El nombre del servicio SIN la talla: lo que lo distingue de otra familia.

    "Keratina premium largo" -> "keratina premium"
    "Acido lactico bio premium-extra largo" -> "acido lactico bio premium"
    """
    limpio = _norm(nombre).replace("-", " ")
    todas = sorted(
        {forma for _canonica, formas in _TALLAS for forma in formas} | _RESTOS_DE_TALLA,
        key=len, reverse=True,
    )
    anterior = None
    while limpio != anterior:  # "extra extra largo" deja "extra" suelto: se repite
        anterior = limpio
        for forma in todas:
            limpio = re.sub(r"\b%s\b" % re.escape(forma), " ", limpio)
        limpio = " ".join(limpio.split())
    # Al quitar la talla quedan conjunciones colgando: "Acido lactico chico o
    # corto" -> "acido lactico o".
    limpio = re.sub(r"\b(o|y|de|del|con|para|en|a)\b\s*$", "", limpio).strip()
    return " ".join(limpio.split())


class Eleccion:
    """O el servicio elegido, o exactamente que falta por saber."""

    def __init__(self, servicio: str = "", falta: str = "", opciones: Optional[List[str]] = None,
                 candidatos: Optional[List[str]] = None):
        self.servicio = servicio
        # "tecnica", "talla", "nada" (no hay nada que encaje) o "" (resuelto)
        self.falta = falta
        self.opciones = opciones or []
        self.candidatos = candidatos or []

    def __repr__(self) -> str:  # pragma: no cover - ayuda al depurar
        return "Eleccion(servicio=%r, falta=%r, opciones=%r)" % (
            self.servicio, self.falta, self.opciones,
        )


def _servicios(cliente_id: str, location_id: str = "") -> List[Dict[str, Any]]:
    try:
        return [s for s in agenda._catalog_services(cliente_id) if isinstance(s, dict)]
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[catalogo] no se pudo leer (%s): %s", cliente_id, exc)
        return []


def _nombre(servicio: Dict[str, Any]) -> str:
    return str(servicio.get("nombre") or servicio.get("name") or "").strip()


def _limpiar_para_ofrecer(nombre: str) -> str:
    """El nombre sin la talla, para ofrecerlo como opcion legible.

    "Keratina premium largo" -> "Keratina premium". Lo que se le ofrece es la
    TECNICA; el largo se pregunta despues si hace falta.
    """
    limpio = tecnica_de(nombre)
    return limpio[:1].upper() + limpio[1:] if limpio else nombre


def _entero(valor) -> Optional[int]:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


_TRAMO_RE = re.compile(r"\bde\s*(\d{1,2})\s*a\s*(\d{1,2})\b")


def _tramo_incluye(nombre: str, edad: int) -> bool:
    """¿El nombre lleva un tramo de edad que incluya esta? ("de 0 a 7")."""
    encontrado = _TRAMO_RE.search(_norm(nombre))
    if not encontrado:
        return False
    desde, hasta = int(encontrado.group(1)), int(encontrado.group(2))
    return desde <= edad <= hasta


def elegir(cliente_id: str, datos: Dict[str, Any], location_id: str = "") -> Eleccion:
    """Decide con el catalogo real y los datos que la clienta ya ha dado.

    `datos` viene de `intents.extraer_datos_servicio`:
        {"familia": "alisado", "tecnica": "keratina", "talla": "corto",
         "para_quien": "mujer", "texto": "lo que dijo, por si acaso"}

    Con los mismos datos, siempre la misma decision. Y no puede preguntar algo que
    ya este en `datos`, porque cada pregunta nace de mirar que falta AQUI.
    """
    servicios = _servicios(cliente_id, location_id)
    if not servicios:
        return Eleccion(falta="nada")

    familia = _norm(datos.get("familia"))
    tecnica = _norm(datos.get("tecnica"))
    talla = _norm(datos.get("talla"))
    para_quien = _norm(datos.get("para_quien"))

    # 1. Candidatos: los que encajan con la familia o la tecnica que ha dicho.
    def _encaja(servicio: Dict[str, Any]) -> bool:
        nombre = _norm(_nombre(servicio))
        categoria = _norm(servicio.get("category"))
        if tecnica and tecnica in nombre:
            return True
        if familia and (familia in nombre or familia in categoria):
            return True
        if familia and categoria.startswith(familia[:6]):
            return True
        return False

    candidatos = [s for s in servicios if _encaja(s)] if (familia or tecnica) else []
    if not candidatos:
        return Eleccion(falta="nada")

    # 2. Si ha dicho para quien es, se filtra por ahi (corte de señora / hombre).
    if para_quien:
        formas = _PARA_QUIEN.get(para_quien, (para_quien,))
        acotado = [
            s for s in candidatos
            if any(f in _norm(_nombre(s)) for f in formas)
        ]
        if acotado:
            candidatos = acotado
        else:
            # No hay version para esa persona: al menos se descartan las de OTRAS
            # (un "corte de señora" no vale para el niño de 5 años).
            otras = {f for clave, fs in _PARA_QUIEN.items() if clave != para_quien for f in fs}
            resto = [s for s in candidatos if not any(f in _norm(_nombre(s)) for f in otras)]
            if resto:
                candidatos = resto

    # 3. Si ha dicho la talla, se filtra por ahi.
    if talla:
        acotado = [s for s in candidatos if talla_de(_nombre(s)) == talla]
        if acotado:
            candidatos = acotado

    # Si ha dicho la edad, no hay nada que preguntar: el catalogo lleva el tramo
    # en el nombre ("Corte niño de 0 a 7").
    edad = _entero(datos.get("edad"))
    if edad is not None:
        acotado = [s for s in candidatos if _tramo_incluye(_nombre(s), edad)]
        if acotado:
            candidatos = acotado

    # La tecnica que ha NOMBRADO manda: si dijo "balayage", no puede acabar en un
    # servicio que no lo lleva en el nombre.
    if tecnica:
        acotado = [s for s in candidatos if tecnica in _norm(_nombre(s))]
        if acotado:
            candidatos = acotado

    # Quien dice "mechas" pide unas mechas, no un "Pack mechas y corte". Si hay
    # servicios cuyo nombre EMPIEZA por lo que ha dicho, esos van primero.
    cabeza = tecnica or familia
    if cabeza:
        directos = [s for s in candidatos if _norm(_nombre(s)).startswith(cabeza)]
        if directos:
            candidatos = directos

    if len(candidatos) == 1:
        return Eleccion(servicio=_nombre(candidatos[0]))

    # 4. ¿Los que quedan son para PERSONAS distintas y no ha dicho para quien?
    #    Eso se pregunta antes que nada: entre "Corte señora", "Corte hombre" y
    #    "Corte niño de 0 a 7" lo que decide no es una tecnica, es para quien es.
    #    Recitandole los nombres del catalogo -y encima solo cuatro de nueve- se
    #    le hacia elegir a ella lo que tiene que preguntar el asistente.
    if not para_quien:
        personas = []
        for servicio in candidatos:
            for clave, formas in _PARA_QUIEN.items():
                if any(f in _norm(_nombre(servicio)) for f in formas):
                    if clave not in personas:
                        personas.append(clave)
        if len(personas) > 1:
            return Eleccion(
                falta="para_quien",
                opciones=personas,
                candidatos=[_nombre(s) for s in candidatos],
            )

    # 5. ¿Quedan TECNICAS distintas y no ha dicho cual? Se pregunta: son
    #    tratamientos con precio y proceso propios, no variantes de tamaño.
    representantes: Dict[str, Dict[str, Any]] = {}
    for servicio in candidatos:
        clave = tecnica_de(_nombre(servicio))
        if clave and clave not in representantes:
            representantes[clave] = servicio
    # "acido lactico" y "acido lactico bio premium" no son dos tecnicas: una es el
    # nombre corto de la otra. Se queda la mas completa.
    for clave in sorted(representantes, key=len, reverse=True):
        if any(otra != clave and clave.startswith(otra) for otra in representantes):
            representantes.pop(clave, None)

    if representantes:
        # Si no, el paso final elegiria de entre TODOS los candidatos y se colaba
        # una variante de otra tecnica ("Mechas media cabeza" para quien pidio
        # unas mechas normales).
        vivas = set(representantes)
        acotado = [s for s in candidatos if tecnica_de(_nombre(s)) in vivas]
        if acotado:
            candidatos = acotado

    if len(representantes) > 1 and not tecnica:
        # Se le ofrece el nombre REAL de un servicio de cada tecnica, no mi clave
        # interna: "Keratina premium" se entiende, "mechas balayage 1 1" no.
        elegidas = sorted(representantes.values(), key=lambda s: len(_nombre(s)))
        return Eleccion(
            falta="tecnica",
            opciones=[_limpiar_para_ofrecer(_nombre(s)) for s in elegidas[:4]],
            candidatos=[_nombre(s) for s in candidatos],
        )

    # 6. Misma tecnica en varias tallas y no sabemos su largo: se le pregunta.
    tallas = []
    for servicio in candidatos:
        clave = talla_de(_nombre(servicio))
        if clave and clave not in tallas:
            tallas.append(clave)
    if len(tallas) > 1 and not talla:
        tallas.sort(key=lambda x: _TALLAS_ORDEN.index(x) if x in _TALLAS_ORDEN else 99)
        return Eleccion(
            falta="talla",
            opciones=tallas,
            candidatos=[_nombre(s) for s in candidatos],
        )

    # 6. Ya no falta ningun dato: se coge el mas sencillo (el mas corto) y se sigue.
    #    Marear con una tercera pregunta es peor que empezar por lo basico.
    candidatos.sort(key=lambda s: (int(s.get("duration_minutes") or 0), _nombre(s)))
    return Eleccion(servicio=_nombre(candidatos[0]))


_COMO_SE_PREGUNTA = {
    "para_quien": "para quien es (hombre, señora o niño)",
    "talla": "como tiene el pelo de largo",
    "tecnica": "cual de estos tratamientos quiere",
    "edad": "que edad tiene",
}


def sobre_que_preguntar(eleccion: Eleccion) -> str:
    """QUE hay que preguntarle, en lenguaje humano. Lo redacta quien hable."""
    return _COMO_SE_PREGUNTA.get(eleccion.falta, "")


def pregunta_para(eleccion: Eleccion) -> str:
    """La pregunta que toca, escrita con los datos REALES del catalogo."""
    if eleccion.falta == "para_quien":
        return "¿Es para ti o para otra persona? ¿Corte de hombre, de señora o de niño? 😊"
    if eleccion.falta == "tecnica":
        opciones = list(eleccion.opciones)
        if len(opciones) == 2:
            cuales = "%s o %s" % (opciones[0], opciones[1])
        else:
            cuales = ", ".join(opciones[:-1]) + " o " + opciones[-1]
        return ("¿Cuál prefieres, %s? Si no lo tienes claro, en la cita te asesoramos 😊"
                % cuales)
    if eleccion.falta == "talla":
        return "¿Cómo tienes el pelo de largo? 😊"
    return ""
