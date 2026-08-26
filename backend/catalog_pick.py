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
from typing import Any, Dict, List, Optional, Tuple

from backend import agenda, settings


def _norm(texto: str) -> str:
    """Delega en `textnorm.normalizar`: una sola forma de normalizar en todo el codigo."""
    from backend import textnorm

    return textnorm.normalizar(texto)


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


def separar_alternativas(opcion: str) -> List[str]:
    """"Mechas o balayage" son DOS cosas para quien elige, aunque el catalogo las
    tenga en un servicio.

    Lo pidio la duenya: "si quieres separa el servicio de mechas o balayage en
    mechas y balayage". Solo se parte cuando el nombre es corto: "Cambio de color y
    mechas o balayage" partido en dos deja opciones que nadie sabria distinguir, y
    de cuatro se pasaria a siete.
    """
    limpio = " ".join(str(opcion or "").split())
    partes = [p.strip() for p in re.split(r"\s+o\s+", limpio) if p.strip()]
    if len(partes) != 2 or len(limpio.split()) > 3:
        return [limpio] if limpio else []
    if any(len(p.split()) > 1 for p in partes):
        return [limpio]
    return [p[:1].upper() + p[1:] for p in partes]


def _limpiar_para_ofrecer(nombre: str) -> str:
    """El nombre sin la talla, para ofrecerlo como opcion legible.

    "Keratina premium largo" -> "Keratina premium". Lo que se le ofrece es la
    TECNICA; el largo se pregunta despues si hace falta.
    """
    from backend import textnorm

    limpio = tecnica_de(nombre)
    limpio = limpio[:1].upper() + limpio[1:] if limpio else nombre
    return textnorm.nombre_de_servicio_publico(limpio)


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


def _packs_por_defecto(cliente_id: str) -> bool:
    """¿Este negocio vende sus tecnicos SIEMPRE como pack?

    Lo dijo la duenya de un salon: "cualquier servicio de mechas conlleva mas
    trabajos -matices, volumenes, tratamientos- y cualquier alisado conlleva poner
    el producto, dejarlo, secarlo y plancharlo". El pack es el que lleva la
    duracion real y los tiempos de espera; el suelto se queda corto y descuadra la
    agenda.
    """
    try:
        from backend import clients

        booking_cfg = clients._get_client_config(cliente_id).get("booking") or {}
        return bool(booking_cfg.get("preferir_packs"))
    except Exception:  # noqa: BLE001
        return False


def _familias_hermanas(cliente_id: str, familia: str) -> List[str]:
    """Las familias que ESTE negocio trata como la misma cosa.

    Sale de sus propias reglas: si tiene una que agrupa "mechas, balayage, grey
    blending, cambio de color...", entonces quien pide mechas tiene que ver
    tambien el grey blending. Sin esto, sus packs de Grey Blending existian,
    estaban activos y NO se le ofrecian a nadie que pidiera unas mechas, porque el
    nombre no lleva la palabra "mechas".

    Es del negocio, no nuestro: otro salon agrupa lo suyo y esto cambia solo.
    """
    if not familia:
        return []
    try:
        from backend import rules

        for regla in rules.listar(cliente_id, solo_activas=True):
            familias = [_norm(f) for f in (regla.get("familias") or [])]
            if _norm(familia) in familias:
                return [f for f in familias if f]
    except Exception:  # noqa: BLE001 - sin reglas se sigue como siempre
        return []
    return []


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
    #    Y con lo que el NEGOCIO considera la misma familia: sus packs de Grey
    #    Blending no llevan la palabra "mechas" en el nombre, asi que a quien
    #    pedia mechas no se le ofrecian nunca.
    hermanas = _familias_hermanas(cliente_id, familia) if familia else []

    def _encaja(servicio: Dict[str, Any]) -> bool:
        nombre = _norm(_nombre(servicio))
        categoria = _norm(servicio.get("category"))
        if tecnica and tecnica in nombre:
            return True
        if familia and (familia in nombre or familia in categoria):
            return True
        if familia and categoria.startswith(familia[:6]):
            return True
        # Las hermanas solo valen a nombre COMPLETO ("grey blending"), no por
        # trozos: "color" casaria con medio catalogo.
        return any(h in nombre for h in hermanas if len(h) > 6)

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

    # Los PACKS. Hay negocios donde un servicio tecnico NO se vende suelto: unas
    # mechas llevan matiz, volumen y tratamiento, y un alisado lleva producto,
    # espera, secado y plancha. El pack es el que tiene la duracion REAL y los
    # tiempos de exposicion, asi que reservar el servicio suelto descuadra la
    # agenda y se queda corto de tiempo.
    #
    # Con `booking.preferir_packs` (opt-in del negocio), si para lo que pide existe
    # un pack, se coge el pack. Sin el flag manda lo de siempre: el pack solo si lo
    # nombra.
    dicho = _norm(str(datos.get("texto") or ""))
    quiere_pack = "pack" in dicho.split() or dicho.startswith("pack")
    packs = [s for s in candidatos if _norm(_nombre(s)).startswith("pack")]
    if packs and (quiere_pack or _packs_por_defecto(cliente_id)):
        candidatos = packs
    elif not quiere_pack and packs and len(packs) < len(candidatos):
        # Y al reves: quien dice "mechas" no pide un "Pack mechas y corte".
        candidatos = [s for s in candidatos if s not in packs]

    if len(candidatos) == 1:
        return Eleccion(servicio=_nombre(candidatos[0]))

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

    # Lo que ELLA ha dicho puede identificar ya una de las tecnicas aunque no sea
    # su nombre entero. Paso al separar "Mechas o balayage" en dos opciones: se le
    # ofrecia "mechas", contestaba "mechas"... y como "mechas" es la FAMILIA y no
    # la tecnica, se le volvia a preguntar lo mismo. Bucle hasta que se cansaba.
    if len(representantes) > 1 and not tecnica:
        dicho = _norm(str(datos.get("texto") or ""))

        def _partes(clave: str) -> List[str]:
            # Sin el "pack" -que es de cocina- y separando las alternativas: de
            # "pack mechas o balayage" salen "mechas" y "balayage".
            limpio = clave[5:] if clave.startswith("pack ") else clave
            return [p.strip() for p in limpio.split(" o ") if p.strip()]

        def _cuanto_encaja(clave: str) -> int:
            """El trozo mas largo de esa tecnica que ella ha dicho. 0 si ninguno."""
            return max([len(p) for p in _partes(clave) if p in dicho] or [0])

        casan = [clave for clave in representantes if clave and _cuanto_encaja(clave)]
        # Gana lo MAS ESPECIFICO que haya dicho: "cambio de color y mechas" tiene
        # que llevar a su servicio, no al de mechas a secas solo porque tambien
        # contiene la palabra. Y a igualdad -"balayage" vale para dos- gana el
        # sencillo: quien contesta "balayage" a una lista quiere el balayage.
        if casan:
            casan.sort(key=lambda c: (-_cuanto_encaja(c), len(c.split())))
            elegida_clave = casan[0]
            elegida = representantes[elegida_clave]
            acotado = [s for s in candidatos if tecnica_de(_nombre(s)) == elegida_clave]
            candidatos = acotado or [elegida]
            representantes = {elegida_clave: elegida}

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

    # 6. Ya no falta ningun dato, pero puede quedar mas de uno. Se queda el que
    #    MENOS anyade sobre lo que ella ha pedido.
    #
    #    Paso de verdad y es caro: se le ofrecio elegir entre "Mechas o balayage" y
    #    "Cambio de color y mechas o balayage", ella repitio "mechas o balayage" y
    #    se le asigno el segundo -otro servicio, mas largo y mas caro- sin
    #    preguntarle. Quien pide unas mechas no esta pidiendo tambien un cambio de
    #    color: subirle el servicio por su cuenta es justo lo que el salon no
    #    quiere que pase.
    dicho = set(_norm(str(datos.get("texto") or "")).split())
    dicho |= set(_norm(tecnica).split()) | set(_norm(familia).split())

    def _palabras_de_mas(servicio: Dict[str, Any]) -> int:
        from backend import textnorm

        propias = set(_norm(textnorm.nombre_de_servicio_publico(_nombre(servicio))).split())
        for marca in _TALLAS_ORDEN:
            propias -= set(marca.split())
        propias -= _RESTOS_DE_TALLA
        return len(propias - dicho)

    #    Y a igualdad, el mas sencillo (el mas corto): marear con una tercera
    #    pregunta es peor que empezar por lo basico.
    candidatos.sort(key=lambda s: (_palabras_de_mas(s),
                                   int(s.get("duration_minutes") or 0), _nombre(s)))
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
