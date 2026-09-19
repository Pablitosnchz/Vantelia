# -*- coding: utf-8 -*-
"""Lo que se escribe a mano en la agenda, entendido: quien viene y que se le hace.

POR QUE EXISTE
--------------
En el salon piloto la cita se apunta escribiendo encima del cuadro, como en su programa de
siempre: «Carmen Calvo, pack mechas corto». Eso, tal cual, es una NOTA: la agenda aparta media
hora por defecto y el asistente ve libre el resto de la tarde aunque sean tres horas de trabajo.
Es el incidente que este producto no se puede permitir.

Aqui se traduce lo escrito a lo que el sistema entiende -nombre + servicio del catalogo- SIN
modelo: la coma parte el apunte y el servicio lo decide el mismo cerebro que ya elige en el chat,
la voz y WhatsApp (`catalog_pick`). Una sola forma de elegir servicio en todo el producto.

LO QUE NO HACE
--------------
No adivina por adivinar. Si no esta segura, no elige: devuelve las dos o tres opciones reales del
catalogo -con su duracion- para que quien coge la cita toque una. Lo escrito se guarda siempre tal
cual, se resuelva o no.

La regla de cuando se atreve a elegir sola sale de dos incidentes reales:

- «Bajar de gama sin preguntar» (ago-2026): a quien pedia «acido lactico bio premium» se le
  asignaba el de QUINCE minutos. Por eso, si la tecnica la pone el codigo y no quien escribe, se
  pregunta.
- «alisado largo» -> «Pack keratina premium largo» y «color y peinado» -> «Pack maquillaje y medio
  recogido» (medido el 18-sep-2026 sobre el catalogo real del salon, 186 servicios): el catalogo
  resuelve solo y acierta la familia equivocada. Por eso el servicio elegido tiene que cubrir
  lo ESCRITO; compartir solo una palabra permitia perder «balayage» al pedir mechas balayage.

Esa regla vive en UN sitio, `_por_que_no_aplicarlo`, y todo lo que se aplica solo pasa por ahi.
"""
from __future__ import annotations

from typing import Any, Dict, List

from backend import agenda
from backend import catalog_pick

# Palabras que no distinguen un servicio de otro: estan en media carta.
_VACIAS = {
    "con", "sin", "para", "del", "las", "los", "una", "uno",
    "mas", "menos", "por", "que", "the", "and",
}
# Cuantas opciones se ofrecen de un toque. Mas que esto ya no es un toque: es una lista.
MAX_CANDIDATOS = 4
# Cuanto puede durar otro servicio que tambien encaje con lo escrito antes de que haya que
# preguntar. Media vez mas ya es otra cosa: en el salon, «mechas medio» es la aplicacion de 75
# minutos y tambien el pack de SEIS HORAS. Equivocarse a la baja deja al asistente dando horas
# que no existen, asi que a partir de ahi (INCLUIDO: 60 frente a 90 pregunta) no se elige sola.
MARGEN_DE_DURACION = 1.5
# Palabras de la tecnica que no hace falta haber escrito. «pack» es la version completa de lo
# mismo: si se cuela, se aparta de MAS, que es la direccion que no rompe la agenda.
_TECNICA_SIN_EXIGIR = {"pack", "packs"}
_UNIONES = {"y", "e", "de", "del", "con", "para", "en", "a", "al", "la", "el"}
# Como se pregunta en el mostrador: corto y sin adornos. Quien atiende tiene a la clienta delante.
_PREGUNTAS = {
    "talla": "¿De qué largo?",
    "tecnica": "¿Cuál de estos?",
    "para_quien": "¿Para quién?",
}


def _minutos_del_catalogo(servicios: List[Dict[str, Any]]) -> Dict[str, int]:
    """Lo que dura cada servicio segun el catalogo, para comparar entre ellos sin ir a la BD."""
    return {catalog_pick._nombre(s): int(s.get("duration_minutes") or 0) for s in servicios}


def _forma(texto: str) -> str:
    """Como se compara: sin tildes ni mayusculas y por como SUENA.

    El catalogo del salon dice «Kitar extensiones» y en el mostrador se escribe «quitar
    extensiones». Sin igualar el sonido no casaba nada, y encima se ofrecia «Brusing-extensiones»
    por largo, que no tiene que ver (probado en la agenda real el 18-sep-2026). Se aplica a los
    DOS lados, asi que igualar de mas no descoloca nada.
    """
    return catalog_pick._mismo_sonido(catalog_pick._norm(texto))


def _tokens(texto: str) -> List[str]:
    """Las palabras que de verdad distinguen, ya normalizadas."""
    return [p for p in _palabras_del_nombre(texto) if len(p) >= 3 and p not in _VACIAS]


def _texto_del_apunte_canonico(texto: str) -> str:
    """La misma talla del catalogo tambien al buscar los rivales del apunte.

    Si «media melena» no casa con «medio», el resolvedor puede elegir 75 minutos
    mientras el guardia no ve el pack de 360. Reutiliza sus alias, sin otra lista.
    """
    talla = catalog_pick.talla_de(texto)
    return (catalog_pick.tecnica_de(texto) + " " + talla) if talla else texto


def partir(texto: str) -> Dict[str, str]:
    """La coma parte el apunte: nombre a la izquierda, servicio a la derecha.

    Sin coma no se inventa nada: todo lo escrito hace de nombre (como hasta ahora) y ademas se
    intenta reconocer el servicio, que para eso hace falta mucho acierto y por eso se exige
    coincidencia clara. El nombre contamina: «Rosa», «Flor» o «Carmen» son palabras que tambien
    estan en las cartas de servicios.
    """
    escrito = str(texto or "").strip()
    if "," in escrito:
        nombre, _, servicio = escrito.partition(",")
        return {"nombre": nombre.strip(), "servicio_texto": servicio.strip()}
    return {"nombre": escrito, "servicio_texto": escrito}


def _catalogo(cliente_id: str, location_id: str = "") -> List[Dict[str, Any]]:
    return catalog_pick._servicios(cliente_id, location_id)


def _por_nombre_exacto(servicios: List[Dict[str, Any]], texto: str) -> str:
    objetivo = _forma(texto)
    if not objetivo:
        return ""
    for servicio in servicios:
        if _forma(catalog_pick._nombre(servicio)) == objetivo:
            return catalog_pick._nombre(servicio)
    return ""


def _palabras_del_nombre(nombre: str) -> List[str]:
    return [p for p in _forma(_texto_del_apunte_canonico(nombre)).replace("-", " ").replace("(", " ").replace(")", " ").split()
            if p]


def _palabras_del_apunte_cubiertas(palabras: List[str], partes: List[str]) -> bool:
    """Compartir «mechas» no permite perder el «balayage» que tambien escribio."""
    return bool(palabras) and all(
        any(parte.startswith(palabra) for parte in partes) for palabra in palabras
    )


def _los_que_encajan(servicios: List[Dict[str, Any]], texto: str) -> List[str]:
    """Todos los del catalogo que contienen TODO lo escrito, del que mejor ajusta al que peor.

    Cada palabra escrita tiene que empezar una palabra del nombre, con los alias de talla
    del catalogo normalizados en ambos. Se devuelven TODOS a proposito: quedarse con el primero
    es como se apartaban 75 minutos para un trabajo de seis horas.

    Ajuste = cuanto del nombre del servicio explica lo que ella ha escrito. «mechas medio» explica
    entero «Mechas medio» y solo un trozo de «Pack mechas o balayage medio», asi que ese va antes.
    """
    palabras = _tokens(texto)
    if not palabras:
        return []
    encajan = []
    for servicio in servicios:
        nombre = catalog_pick._nombre(servicio)
        partes = _palabras_del_nombre(nombre)
        if not partes:
            continue
        if _palabras_del_apunte_cubiertas(palabras, partes):
            cubiertas = sum(1 for parte in partes if any(parte.startswith(p) for p in palabras))
            encajan.append((cubiertas / float(len(partes)), nombre))
    encajan.sort(key=lambda par: (-par[0], par[1]))
    return [nombre for _, nombre in encajan]


def _tecnica_escrita(servicio: str, texto: str) -> bool:
    """¿Ha escrito lo que distingue a este servicio de sus hermanos?

    «alisado largo» encajaba LITERALMENTE con «Alisado keratina largo», y como era el unico se
    aplicaba: la keratina no la habia dicho nadie (revision de Astra, 19-sep-2026). Cada palabra
    de la tecnica (`catalog_pick.tecnica_de`, el nombre sin la talla) tiene que estar escrita;
    las alternativas del propio nombre («mechas o balayage») cuentan como una, y basta con una.
    """
    escritas = _tokens(texto)
    grupos: List[List[str]] = []
    unir = False
    for palabra in _palabras_del_nombre(catalog_pick.tecnica_de(servicio)):
        if palabra == "o":
            unir = bool(grupos)
            continue
        if (palabra in _UNIONES or palabra in _VACIAS or palabra in _TECNICA_SIN_EXIGIR
                or len(palabra) < 3):
            unir = False
            continue
        if unir:
            grupos[-1].append(palabra)
        else:
            grupos.append([palabra])
        unir = False
    return all(
        any(p.startswith(e) or e.startswith(p) for p in grupo for e in escritas)
        for grupo in grupos
    )


def _por_que_no_aplicarlo(servicio: str, texto: str, rivales: List[str], minutos: Dict[str, int]) -> str:
    """La UNICA autoridad que decide si un servicio se aplica solo. «» = se puede.

    Por aqui pasa TODA salida automatica, venga de donde venga (el unico que encaja, el nombre
    escrito tal cual o el cerebro del catalogo). Antes cada camino llevaba sus comprobaciones y
    el de «solo encaja uno» no llevaba ninguna: con un catalogo que solo tiene «Mechas corto»,
    «mechas» elegia el corto sin que nadie dijera el largo (revision de Astra, 19-sep-2026).

    `rivales` son los otros servicios que tambien encajan con lo escrito.
    """
    talla = catalog_pick.talla_de(servicio)
    if talla and talla != catalog_pick.talla_de(texto):
        # El largo lo pone quien lo dice. Tambien cuando dice OTRO: sin «extra largo» en el
        # catalogo, el cerebro se quedaba con la talla mas corta y se aplicaba igual.
        return "talla"
    if not _tecnica_escrita(servicio, texto):
        return "tecnica"
    if not _palabras_del_apunte_cubiertas(_tokens(texto), _palabras_del_nombre(servicio)):
        return "contenido"        # no descartar tecnica, talla u otro servicio que ha escrito
    propio = minutos.get(servicio, 0)
    if any(minutos.get(otro, 0) >= propio * MARGEN_DE_DURACION for otro in rivales if otro != servicio):
        return "duracion"         # otro que encaja igual dura vez y media o mas
    return ""


def _datos(texto: str, cliente_id: str, **extra: str) -> Dict[str, Any]:
    familias = catalog_pick.familias_pedidas(cliente_id, texto)
    datos = {
        "familia": familias[0] if familias else "",
        # `elegir` separa la talla de la tecnica y busca lo escrito en los nombres del catalogo.
        "tecnica": texto,
        "talla": catalog_pick.talla_de(texto),
        "texto": texto,
    }
    datos.update({k: v for k, v in extra.items() if v})
    return datos


def duracion_de(cliente_id: str, servicio: str) -> int:
    return agenda._service_duration_minutes(cliente_id, servicio) if servicio else 0


class _Pregunta:
    """Lo que falta por saber, para poder pedirle al catalogo una opcion por cada respuesta.

    Tiene la forma justa que usa `_candidatos`: `catalog_pick.Eleccion` es la de verdad, pero aqui
    la pregunta nace de mirar el catalogo, no de una eleccion a medias.
    """

    def __init__(self, falta: str, opciones: List[str]):
        self.falta = falta
        self.opciones = opciones
        self.candidatos: List[str] = []
        self.servicio = ""


def _tallas_de(nombres: List[str]) -> List[str]:
    """Que largos aparecen entre los servicios que encajan, de menos a mas rato."""
    vistas: List[str] = []
    for nombre in nombres:
        talla = catalog_pick.talla_de(nombre)
        if talla and talla not in vistas:
            vistas.append(talla)
    return vistas


def _candidatos(cliente_id: str, texto: str, eleccion, location_id: str = "") -> List[Dict[str, Any]]:
    """Las opciones que faltan, convertidas en servicios de verdad con su duracion.

    `catalog_pick` devuelve «corto, medio, largo»; en el mostrador eso no sirve de nada si no se
    ve lo que ocupa cada uno. Se vuelve a preguntar al catalogo con esa opcion puesta.
    """
    salida: List[Dict[str, Any]] = []
    for opcion in (eleccion.opciones or [])[:MAX_CANDIDATOS]:
        datos = _datos(texto, cliente_id, **{eleccion.falta: opcion})
        otra = catalog_pick.elegir(cliente_id, datos, location_id)
        if not otra.servicio:
            continue
        salida.append({
            "etiqueta": opcion,
            "servicio": otra.servicio,
            "duracion": duracion_de(cliente_id, otra.servicio),
        })
    return salida


def interpretar(cliente_id: str, texto: str, location_id: str = "") -> Dict[str, Any]:
    """Que se ha entendido de lo escrito. Nunca falla: como mucho, no entiende nada.

    Devuelve el nombre, el servicio si esta claro, lo que ocupa, y -si no lo esta- la pregunta y
    las opciones reales para tocar una.
    """
    partes = partir(texto)
    escrito = partes["servicio_texto"]
    resultado: Dict[str, Any] = {
        "nombre": partes["nombre"],
        "servicio_texto": escrito,
        "servicio": "",
        "duracion": 0,
        "pregunta": "",
        "candidatos": [],
    }
    if not escrito:
        return resultado

    servicios = _catalogo(cliente_id, location_id)
    if not servicios:
        return resultado

    minutos = _minutos_del_catalogo(servicios)

    def preguntar(pregunta, nombres, hechos=None):
        resultado["pregunta"] = pregunta
        resultado["candidatos"] = hechos[:MAX_CANDIDATOS] if hechos else [
            {"etiqueta": nombre, "servicio": nombre, "duracion": duracion_de(cliente_id, nombre)}
            for nombre in nombres[:MAX_CANDIDATOS]
        ]
        return resultado

    def resuelto(nombre, rivales):
        """Aplicar un servicio solo: SIEMPRE pasando por la autoridad. Si no pasa, se ofrece."""
        if _por_que_no_aplicarlo(nombre, escrito, rivales, minutos):
            opciones = [nombre] + [otro for otro in rivales if otro != nombre]
            return preguntar("¿Es esto?" if len(opciones) == 1 else "¿Cuál de estos?", opciones)
        resultado["servicio"] = nombre
        resultado["duracion"] = duracion_de(cliente_id, nombre)
        return resultado

    # 1. Lo que encaja con TODO lo escrito, del que mejor ajusta al que peor. El nombre escrito
    #    tal cual manda en el orden: si se molesta en escribirlo entero, va primero.
    encajan = _los_que_encajan(servicios, escrito)
    exacto = _por_nombre_exacto(servicios, escrito)
    if exacto and exacto in encajan:
        encajan = [exacto] + [n for n in encajan if n != exacto]

    if len(encajan) == 1:
        return resuelto(encajan[0], [])

    if 1 < len(encajan) <= MAX_CANDIDATOS:
        # 2. Varios encajan. Solo se intenta aplicar el mejor si lo escribio tal cual; y aun asi
        #    decide la autoridad: «mechas medio» son 75 minutos de aplicacion y seis horas de
        #    pack, y apartar los 75 es el incidente que no nos podemos permitir.
        if exacto == encajan[0]:
            return resuelto(exacto, encajan[1:])
        return preguntar("¿Cuál de estos?", encajan)

    # 3. Sin decir el largo, no se elige largo. Si lo escrito encaja con servicios de varias
    #    tallas, se pregunta: escribir «mechas» a secas acababa en el servicio mas corto de la
    #    familia -75 minutos- para un trabajo que puede ser de seis horas (medido el 18-sep-2026).
    if not catalog_pick.talla_de(escrito):
        tallas = _tallas_de(encajan)
        if len(tallas) > 1:
            porTalla = _candidatos(cliente_id, escrito, _Pregunta("talla", tallas), location_id)
            if len(porTalla) > 1:
                return preguntar(_PREGUNTAS["talla"], [], porTalla)

    # 4. Decide el cerebro del catalogo, que sabe de familias, tecnicas y packs.
    eleccion = catalog_pick.elegir(cliente_id, _datos(escrito, cliente_id), location_id)
    if eleccion.servicio:
        # Tambien lo que elige el catalogo pasa por la autoridad, con todo lo que encaja con lo
        # escrito como rivales: si nadie ha nombrado eso, se ofrece en vez de aplicarse.
        return resuelto(eleccion.servicio, encajan)

    candidatos = _candidatos(cliente_id, escrito, eleccion, location_id)
    if candidatos:
        resultado["pregunta"] = _PREGUNTAS.get(eleccion.falta, "¿Cuál de estos?")
        resultado["candidatos"] = candidatos
    return resultado
