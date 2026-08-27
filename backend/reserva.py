# -*- coding: utf-8 -*-
"""Que sabemos de la cita que se esta cogiendo, y que falta para cogerla.

POR QUE EXISTE
--------------
El agente acabo con DOCE detectores que leian el texto del modelo ("¿esta
preguntando el dia?", "¿esta recitando el calendario?", "¿dice que ya esta
reservada?") y TRECE puntos de correccion que le hacian repetir el turno. Eso son
las seis capas de heuristicas de antes, reconstruidas dentro del agente un `if`
cada vez. Y hacian dano: uno forzaba `crear_cita` en plena reprogramacion y creaba
citas duplicadas.

El problema de fondo era el orden. El codigo miraba lo que el modelo YA habia
escrito e intentaba corregirlo a posteriori. Aqui el codigo lleva el estado de la
conversacion, decide QUE falta y se lo dice ANTES de que hable. El modelo pone las
palabras; la decision no es suya.

Es el mismo reparto que ya funciona en `catalog_pick` (el modelo extrae, el codigo
elige) y que no ha dado una sola regresion.

DE DONDE SALE EL ESTADO
-----------------------
Solo de los RESULTADOS DE LAS TOOLS, que son la verdad del servidor. Nunca de lo
que el modelo diga que ha entendido: si el servicio no lo ha confirmado
`buscar_servicio`, no esta elegido; si la hora no sale de `consultar_disponibilidad`,
no existe.

El estado vive por conversacion (`appstate`) y caduca con el mismo silencio que
cierra el historial: la charla de otro dia no cuenta.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

from backend import appstate, settings

# Una conversacion parada mas de esto ya es otra conversacion.
CADUCA_EN = settings.SESSION_TTL_SECONDS


@dataclass
class Estado:
    """Lo que se sabe de la cita en curso. Lo llena el codigo, no el modelo."""

    intencion: str = ""          # reservar | cancelar | reprogramar
    servicio: str = ""           # como se le dice a la clienta (sin "Pack")
    servicio_exacto: str = ""    # el nombre del catalogo con el que se crea la cita
    duracion: int = 0
    fecha: str = ""              # AAAA-MM-DD
    hora: str = ""               # HH:MM
    nombre: str = ""
    codigo: str = ""             # la cita que ya tiene, si gestiona una
    profesional: str = ""        # si ha pedido a alguien en concreto
    huecos: List[str] = field(default_factory=list)   # los que se le han ofrecido
    fecha_de_los_huecos: str = ""  # de que dia son esos huecos (no es "el dia elegido")
    dia_le_da_igual: bool = False
    hecho: bool = False          # la gestion se completo en esta conversacion
    recargo_dicho: bool = False  # ya se le explico lo que cuesta con esa profesional
    cancelada: bool = False      # su cita se anulo: ya no esta en pie
    ya_creada: bool = False      # ya se le cogio UNA cita en esta conversacion
    # Hay una cita lista y frenada esperando que ella pulse "Confirmar". Es la
    # senyal exacta que abre el resumen con botones: mas fiable que la intencion,
    # que a veces es "reprogramar" -cancelo la vieja y hay que crear la nueva- y
    # a veces no la ha declarado nadie porque la clienta escribio en su idioma.
    esperando_confirmacion: bool = False
    veces_sin_precio: int = 0    # cuantas veces se le ha dicho que no hay precio
    servicio_texto: str = ""    # todo lo que ha dicho sobre QUE quiere hacerse
    ultimo_falta: str = ""      # que dato del servicio se le pregunto la ultima vez
    ultimo_pedido: str = ""      # que se pidio en el turno anterior
    tocado: float = field(default_factory=time.time)

    def vigente(self) -> bool:
        return (time.time() - self.tocado) < CADUCA_EN


def _clave(cliente_id: str, telefono: str) -> str:
    return "%s|%s" % (cliente_id, telefono)


def cargar(cliente_id: str, telefono: str) -> Estado:
    """El estado de esta conversacion, o uno limpio si caduco."""
    guardados = getattr(appstate, "ESTADOS_DE_RESERVA", None)
    if guardados is None:
        guardados = {}
        appstate.ESTADOS_DE_RESERVA = guardados
    estado = guardados.get(_clave(cliente_id, telefono))
    if estado is None or not estado.vigente():
        estado = Estado()
        guardados[_clave(cliente_id, telefono)] = estado
    return estado


def guardar(cliente_id: str, telefono: str, estado: Estado, pedido: str = "") -> None:
    estado.tocado = time.time()
    estado.ultimo_pedido = pedido
    guardados = getattr(appstate, "ESTADOS_DE_RESERVA", None)
    if guardados is None:
        guardados = {}
        appstate.ESTADOS_DE_RESERVA = guardados
    guardados[_clave(cliente_id, telefono)] = estado
    if len(guardados) > 2000:  # no crecer sin limite en un proceso largo
        for clave in [k for k, v in guardados.items() if not v.vigente()]:
            guardados.pop(clave, None)


def marcar_hecha(cliente_id: str, telefono: str, codigo: str = "") -> None:
    """La cita ya esta cogida: que no se vuelva a montar sola.

    Olvidar el estado NO basta: el modelo relee la conversacion, ve que ella
    queria un corte el martes a las diez, lo vuelve a dar por pendiente y manda el
    resumen otra vez. La clienta dice que si por educacion y nace una SEGUNDA
    cita. Medido: cinco citas duplicadas y el "repite la misma pregunta" disparado
    de 14 a 38 conversaciones de cada 100.
    """
    estado = cargar(cliente_id, telefono)
    estado.hecho = True
    estado.esperando_confirmacion = False
    estado.codigo = codigo or estado.codigo
    guardar(cliente_id, telefono, estado)


def olvidar(cliente_id: str, telefono: str) -> None:
    guardados = getattr(appstate, "ESTADOS_DE_RESERVA", None) or {}
    guardados.pop(_clave(cliente_id, telefono), None)


# ─── Lo que dice la clienta ────────────────────────────────────────────────

# Las formas de decir "el dia me da igual, dame lo primero que tengas". Con
# cualquiera de estas se BUSCA el primer dia con hueco en vez de preguntarle otra
# vez que dia quiere: preguntarselo a quien acaba de decir que le da igual es
# justo lo que le hace abandonar.
#
# OJO: solo frases que hablen del CUANDO. "Me da igual" a secas tambien vale para
# el precio o para el profesional, y adelantarse ahi es meterle prisa.
_LE_DA_IGUAL = (
    "me da igual", "cualquier", "el que sea", "lo que tengas", "que tengas",
    "primer hueco", "primera hora", "cuando puedas", "lo antes posible",
    "cuanto antes", "me vale", "lo mas pronto", "ya mismo", "urgente",
    "da igual el dia", "da igual la hora", "da igual cuando", "cuando sea",
    "cuando te venga", "cuando mejor", "lo primero que", "la primera que",
    "sin preferencia", "como veas", "tu decides", "lo que mejor te venga",
    "me es igual", "me es indiferente", "lo primero libre", "el hueco mas cercano",
)


def _hora_coloquial(texto: str, huecos: List[str]) -> str:
    """La hora que dice en cristiano ("a las 14", "sobre las 5 de la tarde").

    El parser de siempre solo entiende "14:00", asi que "a las 14" se perdia: el
    estado se quedaba sin hora, no se montaba el resumen y la clienta se quedaba
    esperando despues de haber elegido.

    Se contrasta SIEMPRE con los huecos reales: si lo que dice no es uno de ellos,
    no se anota nada. Asi no se puede inventar una hora que no existe.
    """
    import re

    if not huecos:
        return ""
    plano = str(texto or "").lower()
    de_tarde = any(p in plano for p in ("tarde", "noche", "pm"))
    candidatas = []
    for cruda in re.findall(r"\b(\d{1,2})(?:[:.](\d{2}))?\b", plano):
        hora, minutos = int(cruda[0]), int(cruda[1] or 0)
        if hora > 23 or minutos > 59:
            continue
        candidatas.append("%02d:%02d" % (hora, minutos))
        if de_tarde and hora <= 12:  # "las 5 de la tarde" = 17:00
            candidatas.append("%02d:%02d" % (hora + 12, minutos))
    for candidata in candidatas:
        if candidata in huecos:
            return candidata
    # "a las 14" a secas: vale el primer hueco de esa hora.
    for candidata in candidatas:
        franja = candidata.split(":")[0] + ":"
        iguales = [h for h in huecos if h.startswith(franja)]
        if iguales:
            return iguales[0]
    return ""


def anotar_lo_que_dice(estado: Estado, mensaje: str, timezone_name: str = "",
                       cliente_id: str = "") -> None:
    """Lo que se puede sacar de su mensaje SIN preguntarle al modelo.

    Hace falta: si el estado solo se llenara con resultados de tools, un "el
    jueves" no quedaria anotado en ninguna parte y `que_falta` seguiria pidiendo el
    dia turno tras turno. Medido: repetir la misma pregunta se disparo de 3 a 15
    conversaciones de 40 cuando el estado no escuchaba lo que ella decia.

    Solo entra lo que se extrae de forma DETERMINISTA (los mismos parsers que usa
    el flujo por listas). Nada de deducciones.
    """
    from backend import catalog_pick, textnorm

    plano = catalog_pick._norm(mensaje or "")
    if any(pista in plano for pista in _LE_DA_IGUAL):
        estado.dia_le_da_igual = True

    # ¿Ha cambiado de idea? Entonces el servicio elegido ya no vale, ni la hora
    # que se aparto para el. Lo demas de ella -su nombre, lo que ya se le conto-
    # se conserva: eso no cambia porque quiera otra cosa.
    if cliente_id and not estado.hecho and cambia_de_servicio(cliente_id, estado, mensaje):
        estado.servicio = ""
        estado.servicio_exacto = ""
        estado.servicio_texto = ""
        estado.duracion = 0
        estado.hora = ""
        estado.huecos = []
        estado.ultimo_falta = ""

    # ¿Pide OTRA cita habiendo terminado ya una? Entonces se empieza de cero con
    # la nueva, en vez de quedarse describiendo la anterior una y otra vez.
    if estado.hecho and pide_otra_cita(mensaje):
        empezar_otra_gestion(estado)

    # Lo que dice del servicio se ACUMULA hasta que hay uno elegido. Sin esto, a
    # "quiero unas mechas" seguido de "lo tengo por los hombros" el catalogo solo
    # recibia lo ultimo -el largo- y volvia a preguntarle que servicio queria: la
    # clienta ya lo habia dicho dos mensajes antes.
    if not estado.servicio and not estado.hecho:
        trozo = " ".join(str(mensaje or "").split())[:120]
        if trozo and trozo.lower() not in estado.servicio_texto.lower():
            estado.servicio_texto = (estado.servicio_texto + " " + trozo).strip()[-300:]

    # Lo que pide en su mensaje declara la intencion, y eso es lo que obliga
    # despues a llamar a la herramienta que remata. Sin esto, a "quiero cancelar mi
    # cita" nadie forzaba nada: el modelo contestaba preguntandole que servicio
    # queria y la cita se quedaba en pie.
    if not estado.hecho and not estado.intencion:
        if pide_anular_y_solo_eso(mensaje):
            estado.intencion = "cancelar"
        elif pide_moverla_y_solo_eso(mensaje) and estado.codigo:
            estado.intencion = "reprogramar"

    if not estado.hecho:
        # La fecha que diga ELLA manda, aunque ya hubiera una: corregir un dato es
        # lo primero que hace quien ve un resumen equivocado, y no hacerle caso la
        # dejaba repitiendo "es el miercoles 26, no el jueves" hasta cansarse.
        fecha = textnorm._extract_date_from_text(mensaje or "", timezone_name or "Europe/Madrid")
        if fecha and fecha != estado.fecha:
            estado.fecha = fecha
            estado.hora = ""      # el hueco de otro dia no vale
            estado.huecos = []
        if not estado.hora:
            hora = textnorm._extract_time_from_text(mensaje or "")
            if not hora:
                hora = _hora_coloquial(mensaje or "", estado.huecos)
            if hora:
                estado.hora = hora
        # "la primera que tengas", "me da igual la hora": ELIGE EL CODIGO. Estaba
        # escrito como instruccion -"coge el primero"- y el modelo respondia
        # volviendo a ofrecerle la lista de horas, otra vez, y otra. Es el fallo
        # mas repetido de todas las mediciones, y en el caso mas simple que hay
        # (venir a cortarse el pelo) se llevaba la cita por delante.
        if not estado.hora and estado.dia_le_da_igual and estado.huecos:
            estado.hora = estado.huecos[0]
            if not estado.fecha and estado.fecha_de_los_huecos:
                estado.fecha = estado.fecha_de_los_huecos
        if not estado.codigo:
            codigo = _codigo_en(mensaje or "")
            if codigo:
                estado.codigo = codigo


def _codigo_en(texto: str) -> str:
    import re

    encontrado = re.search(r"R-?\s?(\d{3,})", texto or "", re.IGNORECASE)
    return ("R-" + encontrado.group(1)) if encontrado else ""


# ─── Lo que dicen las tools (la verdad del servidor) ───────────────────────

def anotar_resultado(estado: Estado, tool: str, argumentos: Dict[str, Any],
                     resultado: Dict[str, Any]) -> None:
    """Actualiza el estado con lo que ha DEVUELTO una herramienta."""
    if not isinstance(resultado, dict):
        return
    if resultado.get("pendiente_de_confirmacion"):
        # La creacion se ha frenado a proposito (la confirma la clienta con un
        # boton), pero los datos que traia la llamada son buenos y son los unicos
        # que hay: el nombre no lo devuelve ninguna herramienta. Sin recogerlos, el
        # resumen no se podia montar y la conversacion se quedaba colgada.
        for clave in ("servicio", "fecha", "hora", "nombre", "profesional"):
            valor = str(argumentos.get(clave) or "").strip()
            if valor and not getattr(estado, clave, ""):
                setattr(estado, clave, valor)
        # Y esto es RESERVAR, aunque nadie lo haya declarado. Sin ponerlo, la
        # conversacion no tenia salida: el agente juntaba servicio, dia, hora y
        # nombre, frenaba la creacion esperando el resumen con el boton... y el
        # resumen se negaba a salir porque `intencion` estaba vacia. La clienta
        # recibia "parece que no puedo reservar la cita" con todos sus datos sobre
        # la mesa. Pedir cita ES declarar la intencion.
        estado.intencion = estado.intencion or "reservar"
        estado.esperando_confirmacion = True
        return
    if not resultado.get("ok"):
        return

    if tool == "buscar_servicio" and resultado.get("servicio"):
        estado.servicio = str(resultado["servicio"])
        # El nombre de hablar y el de la agenda NO son el mismo, y confundirlos
        # sale caro: "Pack keratina premium medio" se dice "Keratina premium
        # medio"... que ES OTRO SERVICIO del catalogo, de 30 minutos. La cita se
        # cogio de media hora para un tratamiento de casi cuatro.
        estado.servicio_exacto = str(resultado.get("servicio_en_agenda")
                                     or resultado["servicio"])
        estado.duracion = int(resultado.get("duracion_minutos") or 0)

    elif tool == "consultar_disponibilidad":
        # OJO: mirar la agenda de un dia NO significa que ella lo haya elegido. El
        # modelo consulta varios seguidos para poder ofrecer, y el estado se
        # quedaba con el ULTIMO: decia "mañana miercoles 26" y el resumen ponia
        # "jueves 27". La clienta lo corrigio CUATRO veces y el resumen no cambio,
        # porque la fecha ya estaba puesta.
        fecha = str(argumentos.get("fecha") or resultado.get("fecha") or "")
        huecos = [str(h) for h in (resultado.get("huecos") or [])]
        if huecos:
            estado.huecos = huecos[:8]
            estado.fecha_de_los_huecos = fecha

    elif tool == "consultar_cita":
        estado.codigo = str(resultado.get("codigo_reserva") or estado.codigo)
        estado.servicio = str(resultado.get("servicio") or estado.servicio)
        estado.fecha = str(resultado.get("fecha") or estado.fecha)
        estado.hora = str(resultado.get("hora") or estado.hora)

    elif tool in ("crear_cita", "reprogramar_cita", "cancelar_cita"):
        estado.hecho = True
        # Aparte de `hecho`, que tambien lo pone cancelar y reprogramar: esto dice
        # que ya se COGIO una cita. Cancelar y poner otra en el mismo mensaje es
        # normal; coger dos seguidas sin que nadie lo pida, no.
        if tool == "crear_cita":
            estado.ya_creada = True
        # Que la cita esta ANULADA hay que recordarlo: al pedir "vuelvela a abrir"
        # el asistente contestaba "tu cita esta confirmada para manyana a las
        # 10:00" con la cita cancelada en la base de datos.
        estado.cancelada = tool == "cancelar_cita"
        estado.codigo = str(resultado.get("codigo_reserva") or estado.codigo)
        if tool != "cancelar_cita":
            estado.fecha = str(resultado.get("fecha") or estado.fecha)
            estado.hora = str(resultado.get("hora") or estado.hora)


# Pedir que le quiten la cita, o que se la muevan. Por RAIZ, no por frase exacta:
# "anula la cita" no casaba con "anular" y el freno no saltaba. Nadie escribe
# igual dos veces.
PIDE_ANULAR = ("cancel", "anul", "no voy a poder ir", "no podre ir",
               "no puedo ir", "quitar la cita", "quitame la cita", "borrar la cita",
               "eliminar la cita", "dar de baja la cita", "no la quiero")
PIDE_MOVER = ("cambiar", "mover", "reprogramar", "aplazar", "otro dia", "otra hora",
              "mas tarde", "mas temprano", "adelantar", "retrasar", "pasar la cita")


def pide_anular_y_solo_eso(dicho: str) -> bool:
    """Ha pedido cancelar, y no cambiar de dia.

    Si dice las dos cosas ("cancelar o cambiar") NO se decide por ella: eso se le
    pregunta.
    """
    from backend import catalog_pick

    plano = catalog_pick._norm(dicho or "")
    if not any(pista in plano for pista in PIDE_ANULAR):
        return False
    return not any(pista in plano for pista in PIDE_MOVER)


def pide_moverla_y_solo_eso(dicho: str) -> bool:
    """Ha pedido cambiarla de dia o de hora, y no anularla."""
    from backend import catalog_pick

    plano = catalog_pick._norm(dicho or "")
    if not any(pista in plano for pista in PIDE_MOVER):
        return False
    return not any(pista in plano for pista in PIDE_ANULAR)


# Pedir OTRA cita cuando ya se acaba de coger una. Hace falta distinguirlo de
# seguir hablando de la que ya tiene: al terminar una gestion el estado se queda
# "hecho" A PROPOSITO -para que el modelo no vuelva a montar la misma y salgan
# citas duplicadas-, pero eso dejaba a la clienta sin poder pedir una segunda.
PIDE_OTRA_CITA = ("otra cita", "una cita", "cita para", "cita de", "tambien quiero",
                  "tambien me gustaria", "ademas quiero", "aparte quiero",
                  "quiero reservar", "quiero agendar", "me gustaria reservar",
                  "quiero un ", "quiero una ", "me gustaria un ", "me gustaria una ",
                  "y para el", "y para la", "anyade", "anade")


def pide_otra_cita(dicho: str) -> bool:
    from backend import catalog_pick

    plano = catalog_pick._norm(dicho or "")
    if any(pista in plano for pista in PIDE_ANULAR + PIDE_MOVER):
        return False   # habla de la que ya tiene, no de una nueva
    return any(pista in plano for pista in PIDE_OTRA_CITA)


def empezar_otra_gestion(estado: Estado) -> None:
    """Borra la cita terminada para poder montar la siguiente.

    Lo que se sabe de ELLA se conserva (como se llama, si ya se le explico el
    recargo): repreguntarselo es justo lo que molesta. Lo que se borra es lo de la
    cita: servicio, dia, hora y el "ya esta hecha".

    Paso de verdad: cogio una cita, pidio otra para un alisado y el asistente le
    contesto tres veces seguidas describiendole la PRIMERA. La segunda no se
    creo nunca.
    """
    estado.intencion = "reservar"
    estado.servicio = ""
    estado.servicio_exacto = ""
    estado.servicio_texto = ""
    estado.duracion = 0
    estado.fecha = ""
    estado.hora = ""
    estado.codigo = ""
    estado.huecos = []
    estado.fecha_de_los_huecos = ""
    estado.dia_le_da_igual = False
    estado.hecho = False
    estado.cancelada = False
    estado.ya_creada = False
    estado.esperando_confirmacion = False
    estado.ultimo_falta = ""
    estado.ultimo_pedido = ""


PIDE_CITA = ("cita", "reserva", "reservar", "agendar", "apuntar", "apuntame",
             "coger hora", "cogerme hora", "pedir hora", "quiero ir", "me gustaria ir",
             "quiero hacerme", "me gustaria hacerme", "quiero ponerme", "hacerme un",
             "hacerme una", "puedo ir", "tenéis hueco", "teneis hueco", "hay hueco")


def ha_pedido_cita(dicho: str) -> bool:
    """Ha dicho, de alguna forma, que quiere venir.

    Medido: 3 de cada 100 conversaciones acababan con una cita en la agenda de
    alguien que solo habia preguntado el horario. Eso al negocio le deja un hueco
    ocupado por nadie, y a quien pregunto, una cita que no sabe que tiene.
    """
    from backend import catalog_pick

    plano = catalog_pick._norm(dicho or "")
    return any(pista in plano for pista in PIDE_CITA)


# Como se anuncia un cambio de idea. Sin una de estas, nombrar otra familia es
# describirse o preguntar, no cambiar: "lo tengo medio", "es que tengo color".
_SUENA_A_CAMBIO = (
    " mejor ", " al final ", " en vez ", " en lugar ", " prefiero ", " pues ",
    " cambio ", " cambia ", " mira ", " realmente ", " en realidad ", " ahora que ",
    " pensandolo ", " perdona ", " perdon ", " me he equivocado ", " queria decir ",
    " no, ", " mas bien ", " solo ", " solamente ", " unicamente ",
)


def cambia_de_servicio(cliente_id: str, estado: Estado, mensaje: str) -> bool:
    """Esta pidiendo OTRA cosa distinta de la que ya habia elegido.

    Medido: 4 de cada 100 conversaciones acababan con el servicio equivocado en la
    agenda porque la clienta empezaba pidiendo mechas y a mitad decia "mejor solo
    cortarme las puntas"... y se le cogia las mechas. Nadie vuelve a un salon al
    que le ha dicho dos veces lo que quiere.

    Se compara con las familias que tiene ESTE negocio en su catalogo, no con una
    lista escrita a mano.

    Y ADEMAS tiene que sonar a cambio ("mejor", "al final", "en vez de"). Nombrar
    otra familia no basta, y esto es lo que separa un arreglo de un desastre: entre
    las familias de este salon hay palabras como "medio" o "color", asi que "lo
    tengo medio" -la respuesta normal a "¿como tienes el pelo?"- le habria borrado
    el servicio que acababa de elegir. Cambiar de idea se ANUNCIA; describirse el
    pelo, no.
    """
    from backend import catalog_pick, intents

    if not estado.servicio:
        return False
    dicho = catalog_pick._norm(mensaje or "")
    if not dicho:
        return False
    if not any(senyal in " %s " % dicho for senyal in _SUENA_A_CAMBIO):
        return False
    actual = catalog_pick._norm(estado.servicio)
    try:
        familias = intents.familias_del_tenant(cliente_id)
    except Exception:  # noqa: BLE001 - sin catalogo no se cambia nada
        return False
    for familia in familias:
        limpia = catalog_pick._norm(familia)
        if len(limpia) < 4:
            continue   # trozos de dos o tres letras casan con cualquier cosa
        # Una familia que ella nombra y que NO es la del servicio elegido: ha
        # cambiado de idea.
        # Lo que ELLA dice se busca por la raiz -"cortarme", "mechitas"-; lo que
        # ya tiene elegido, ENTERO. Los nombres del catalogo llevan el largo
        # dentro ("Mechas californianas corto"), asi que buscar ahi por la raiz
        # daba "corte" por elegido y el cambio no se veia.
        if _nombra_por_la_raiz(dicho, limpia) and limpia not in actual:
            return True
    return False


def _nombra_por_la_raiz(texto: str, familia: str) -> bool:
    """¿Aparece esa familia en el texto, aunque venga conjugada o en diminutivo?

    "mejor solo CORTARME las puntas" y "mejor unas MECHITAS" son cambios de idea
    de manual y no casaban con "corte" ni con "mechas".
    """
    if familia in texto:
        return True
    if len(familia) < 5:
        return False
    return familia[:max(4, len(familia) - 2)] in texto


def anotar_intencion(estado: Estado, intencion: str) -> None:
    if intencion in ("reservar", "cancelar", "reprogramar") and not estado.hecho:
        estado.intencion = intencion


# ─── La decision: que toca ahora ───────────────────────────────────────────

def que_falta(estado: Estado, nombre_conocido: str = "") -> str:
    """El siguiente dato que hace falta. Cadena vacia si no falta nada.

    El ORDEN importa y lo decide el codigo, no el modelo: primero QUE se quiere
    hacer (de eso dependen la duracion y el precio), luego CUANDO, luego quien.
    Preguntar el dia sin saber el servicio fue un fallo real.
    """
    if estado.hecho:
        return ""
    if not estado.intencion:
        # Sin una intencion declarada NO se dirige nada: quien pregunta cuanto dura
        # unas mechas no esta cogiendo cita, y contestarle "dime que te quieres
        # hacer" es secuestrarle la pregunta. El canal la declara cuando la sabe
        # (ha pulsado "Agendar cita") y las tools la deducen al tocar una cita.
        return ""
    if estado.intencion in ("cancelar", "reprogramar"):
        if not estado.codigo:
            return "codigo"
        if estado.intencion == "reprogramar" and not estado.fecha:
            return "dia"
        if estado.intencion == "reprogramar" and not estado.hora:
            return "hora"
        return ""
    if not estado.servicio:
        return "servicio"
    if not estado.fecha:
        # Si solo se ha mirado un dia y tiene huecos, ese es el dia del que se esta
        # hablando: no hace falta volver a preguntarlo.
        if estado.fecha_de_los_huecos and estado.huecos:
            estado.fecha = estado.fecha_de_los_huecos
        else:
            return "dia"
    if not estado.hora:
        return "hora"
    if not (estado.nombre or nombre_conocido):
        return "nombre"
    return ""


_COMO_PEDIRLO = {
    "servicio": (
        "Aun no sabes QUE se quiere hacer, y de eso dependen la duracion y el "
        "precio. Preguntaselo con tus palabras. No propongas dias ni horas todavia, "
        "y NO elijas tu un servicio del catalogo."
    ),
    "dia": (
        "Ya sabes el servicio. Ahora pregunta QUE DIA le viene bien. No le "
        "enumeres los dias que abris ni le ofrezcas horas todavia."
    ),
    "hora": (
        "Ya tienes el dia. Ofrecele DOS O TRES de estos huecos (no la lista "
        "entera) y que elija: %s"
    ),
    "nombre": (
        "Solo falta su nombre para cerrarla. Pideselo. No le pidas el telefono "
        "(lo tienes) ni el email (no hace falta)."
    ),
    "codigo": (
        "Necesitas saber de que cita habla: pidele el numero de reserva (R-XXXX). "
        "Si no lo tiene, su telefono o su email valen."
    ),
}


def instruccion(estado: Estado, nombre_conocido: str = "") -> str:
    """Que tiene que hacer el modelo en este turno. Lo decide el codigo."""
    falta = que_falta(estado, nombre_conocido)
    if falta and falta == estado.ultimo_pedido:
        # Ya se lo pidio y sigue faltando: repetirle la misma frase es un muro.
        # Se le dice que lo pregunte de OTRA forma, o que ofrezca una salida.
        return (
            "Ya le has preguntado esto y sigue sin quedar claro. NO repitas la "
            "misma frase: preguntaselo de otra manera, mas concreta y con un "
            "ejemplo, o proponle tu una opcion para que solo tenga que decir si."
        )
    if not falta:
        if estado.hecho:
            return ("La gestion YA esta hecha. Confirmasela con naturalidad y no "
                    "vuelvas a tocarla: si te dice que si, es un acuse de recibo.")
        if estado.intencion == "cancelar":
            return ("Tienes la cita localizada. Confirma con ella que quiere "
                    "cancelarla y llama a `cancelar_cita`.")
        herramienta = "reprogramar_cita" if estado.intencion == "reprogramar" else "crear_cita"
        return ("Tienes todo lo que hace falta. Llama a `%s` AHORA; no vuelvas a "
                "preguntarle lo que ya te ha dicho." % herramienta)
    if falta == "hora":
        if estado.dia_le_da_igual and estado.huecos:
            return ("Le da igual la hora: coge el primero (%s) y remata la gestion "
                    "con la herramienta que toque." % estado.huecos[0])
        return _COMO_PEDIRLO["hora"] % ", ".join(estado.huecos[:6] or ["(consultalos)"])
    if falta == "dia" and estado.dia_le_da_igual:
        return ("Le da igual el dia: mira los huecos del primer dia que abris y "
                "ofrecele dos o tres horas. NO le preguntes que dia quiere.")
    return _COMO_PEDIRLO[falta]


def resumen(estado: Estado, nombre_conocido: str = "") -> str:
    """Lo que ya se sabe, para que el modelo no lo vuelva a preguntar."""
    lineas = []
    if not estado.servicio and estado.servicio_texto:
        # Sin esto le preguntaba OTRA VEZ que servicio queria a quien ya habia
        # dicho "unas mechas" y despues "lo tengo por los hombros": cada mensaje
        # suyo llegaba suelto, sin lo anterior.
        lineas.append("- Sobre el servicio ya te ha dicho: %s" % estado.servicio_texto)
        lineas.append("  (con eso, busca en el catalogo; NO le preguntes otra vez "
                      "que se quiere hacer, pregunta solo lo que FALTE)")
    if estado.servicio:
        detalle = estado.servicio
        if estado.duracion:
            detalle += " (%d min)" % estado.duracion
        lineas.append("- Servicio: %s" % detalle)
        # Ya lo ha elegido: describirselo otra vez en cada mensaje cansa. Visto en
        # una conversacion real, tres veces seguidas "te recomendaria las Mechas o
        # balayage, incluye matiz, elumen y un tratamiento..." cuando ya habia
        # dicho que si.
        lineas.append("  (YA esta elegido: no se lo vuelvas a recomendar ni a "
                      "describir, ve a lo que falta)")
    if estado.codigo:
        lineas.append("- Su cita: %s" % estado.codigo)
    if estado.fecha:
        lineas.append("- Dia: %s" % estado.fecha)
    if estado.hora:
        lineas.append("- Hora: %s" % estado.hora)
    if estado.nombre or nombre_conocido:
        lineas.append("- Se llama: %s" % (estado.nombre or nombre_conocido))
    if estado.profesional:
        lineas.append("- Quiere que la atienda: %s" % estado.profesional)
    if estado.dia_le_da_igual:
        lineas.append("- Le da igual el dia: no se lo preguntes")
    if not lineas:
        return ""
    return "LO QUE YA SABES (no lo vuelvas a preguntar):\n" + "\n".join(lineas)


def anotar_intencion_por_tool(estado: Estado, tool: str) -> None:
    """La intencion tambien se deduce de lo que el modelo ACABA de hacer.

    El canal no siempre la sabe: por texto libre ("necesito mover mi cita") no hay
    boton que pulsar. Si ha consultado o tocado una cita existente, esto va de
    gestionar, no de reservar.
    """
    if estado.hecho:
        return
    if tool in ("consultar_cita", "reprogramar_cita") and not estado.intencion:
        estado.intencion = "reprogramar"
    elif tool == "cancelar_cita":
        estado.intencion = "cancelar"
    elif tool == "crear_cita" and not estado.intencion:
        estado.intencion = "reservar"


def tool_que_remata(estado: Estado, nombre_conocido: str = "") -> str:
    """La herramienta que cierra la gestion cuando YA no falta ningun dato.

    Se devuelve para OBLIGAR al modelo a llamarla. Decirselo con enfasis no
    bastaba: con `tool_choice="required"` cumplia volviendo a consultar huecos y
    se escaqueaba de rematar turno tras turno, dejando la cita sin mover y a la
    clienta creyendo que ya estaba hecha.
    """
    if estado.hecho or que_falta(estado, nombre_conocido):
        return ""
    if estado.intencion == "cancelar":
        return "cancelar_cita"
    if estado.intencion == "reprogramar":
        return "reprogramar_cita"
    if estado.servicio and estado.fecha and estado.hora:
        return "crear_cita"
    return ""


def instruccion_de_cierre(estado: Estado, nombre_conocido: str = "") -> str:
    """Lo que hay que decirle SOLO cuando toca cerrar. Vacio el resto del tiempo.

    Medido en tres tiradas de cuarenta conversaciones:

    - Dirigiendole tambien la recogida de datos ("preguntale el dia", "pide su
      nombre"), repetir la misma pregunta paso de 3 a 15 conversaciones: cuando el
      codigo no se enteraba de que ella ya habia contestado, el modelo repetia la
      frase palabra por palabra. Un muro.
    - Sin instruccion ninguna, la reserva NO se cierra jamas: se queda ofreciendo
      horas en bucle aunque ella haya dicho "el primer hueco que tengas" y su
      nombre. Fallo critico, dos de dos.

    Asi que el reparto es: la CONVERSACION la lleva el modelo, que para eso sabe
    adaptarse; el CIERRE lo decide el codigo, que para eso no se despista.
    """
    if estado.hecho:
        # Muy explicito a proposito: con un "confirmasela con naturalidad" el
        # modelo seguia preguntando "¿me confirmas para proceder?" con la cita ya
        # cogida, y la clienta no sabia si tenia cita o no.
        return (
            "LA CITA YA ESTA COGIDA%s. No vuelvas a pedirle que confirme nada, no "
            "propongas horas y no llames a ninguna herramienta de reserva: solo "
            "despidete o contesta lo que te pregunte. Si te da las gracias o dice "
            "que si, es un acuse de recibo." % ((" (%s)" % estado.codigo) if estado.codigo else "")
        )
    if not estado.intencion:
        return ""
    falta = que_falta(estado, nombre_conocido)
    if not falta:
        if estado.intencion == "cancelar":
            return ("Tienes la cita localizada. Confirma con ella que quiere "
                    "cancelarla y llama a `cancelar_cita`.")
        herramienta = "reprogramar_cita" if estado.intencion == "reprogramar" else "crear_cita"
        return ("Tienes todo lo que hace falta. Llama a `%s` AHORA; no vuelvas a "
                "preguntarle lo que ya te ha dicho." % herramienta)
    # El PRIMER dato si se dirige: sin saber que se quiere hacer, ofrecer horas es
    # empezar la casa por el tejado (y de eso dependen la duracion y el precio).
    # Solo la primera vez: repetir la peticion palabra por palabra era el muro que
    # disparo "repite la misma pregunta" de 3 a 15 conversaciones de cada 40.
    if falta == "servicio" and estado.ultimo_pedido != "servicio":
        return ("Aun no sabes QUE se quiere hacer. Preguntaselo con tus palabras y "
                "no le ofrezcas dias ni horas todavia.")
    if falta == "hora" and estado.dia_le_da_igual and estado.huecos:
        return ("Le da igual la hora: coge el primero (%s) y remata la gestion con "
                "la herramienta que toque." % estado.huecos[0])
    if falta == "dia" and estado.dia_le_da_igual:
        return ("Le da igual el dia: mira los huecos del primer dia que abris y "
                "ofrecele dos o tres horas. NO le preguntes que dia quiere.")
    return ""
