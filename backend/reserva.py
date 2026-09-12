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

El estado vive en SQLite por tenant, canal y conversación. Caduca con el mismo
silencio que cierra el historial. Una escritura compara su versión para que otro
proceso no pueda deshacer una decisión más reciente.
"""
from __future__ import annotations

import time
import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any, Dict, List, Optional
from uuid import uuid4

from backend import settings

# Una conversacion parada mas de esto ya es otra conversacion.
CADUCA_EN = settings.SESSION_TTL_SECONDS


@dataclass(frozen=True)
class PropuestaServicio:
    """Alternativa validada por una regla/tool; no es una reserva ni una elección.

    El adaptador acredita el envío y la interpretación del usuario referencia el
    id vigente. No contiene disponibilidad: el núcleo debe consultarla de nuevo.
    """

    id: str
    servicio_id: str
    nombre: str
    origen: str
    revision_config: str
    creada: float
    estado: str = "preparada"
    mensaje_id: str = ""
    servicio_origen: str = ""
    location_id: str = ""


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
    hora_del_codigo: bool = False  # la hora la eligio el codigo ("la primera que tengas"), no ella
    fecha_de_ella: bool = False    # el dia lo ha dicho ella (o viene en la cita que va a confirmar)
    hecho: bool = False          # la gestion se completo en esta conversacion
    recargo_dicho: bool = False  # ya se le explico lo que cuesta con esa profesional
    cancelada: bool = False      # su cita se anulo: ya no esta en pie
    ya_creada: bool = False      # ya se le cogio UNA cita en esta conversacion
    # Veces que se le ha MOVIDO la cita aqui. A partir de la tercera se le
    # ofrece llamar: lo dejo dicho la duenya del salon el 5-sep-2026.
    veces_movida: int = 0
    # Hay una cita lista y frenada esperando que ella pulse "Confirmar". Es la
    # senyal exacta que abre el resumen con botones: mas fiable que la intencion,
    # que a veces es "reprogramar" -cancelo la vieja y hay que crear la nueva- y
    # a veces no la ha declarado nadie porque la clienta escribio en su idioma.
    esperando_confirmacion: bool = False
    # Turnos que le quedan a un "¿cuanto tarda?" sin contestar. Preguntar es
    # correcto -"¿como tienes el pelo?"-, pero al llegar la respuesta hay que
    # VOLVER a la pregunta: si no, la duracion no se dice nunca.
    duracion_pendiente: int = 0
    veces_sin_precio: int = 0    # cuantas veces se le ha dicho que no hay precio
    servicio_texto: str = ""    # todo lo que ha dicho sobre QUE quiere hacerse
    ultimo_falta: str = ""      # que dato del servicio se le pregunto la ultima vez
    candidatos_pendientes: int = 0  # cantidad de candidatos en la búsqueda anterior
    veces_falta: int = 0        # repeticiones sin concretar el servicio (técnica/talla/destinatario)
    veces_sin_pedirla: int = 0  # veces que el freno de "cita sin pedir" ha saltado
    ultimo_pedido: str = ""      # que se pidio en el turno anterior
    tocado: float = field(default_factory=time.time)
    propuesta_servicio: Optional[PropuestaServicio] = None
    # Resumen exacto ofrecido por el canal, distinto de elegir un servicio.
    confirmacion_reserva_json: str = ""

    def vigente(self) -> bool:
        return (time.time() - self.tocado) < CADUCA_EN


def leer_confirmacion_reserva(estado: Estado):
    """Un snapshot malformado o vencido no acredita que se ofreciera una cita."""
    if estado.hecho:
        return None
    try:
        p = json.loads(estado.confirmacion_reserva_json)
        if (not isinstance(p, dict) or not isinstance(p.get("id"), str) or not p["id"]
                or p.get("estado") not in ("preparada", "ofrecida", "aceptada")
                or type(p.get("creada")) not in (int, float)
                or not math.isfinite(p["creada"])
                or not 0 <= time.time() - p["creada"] < CADUCA_EN
                or not isinstance(p.get("datos"), dict)
                or not p["datos"]
                or any(not isinstance(k, str) or not isinstance(v, str)
                       for k, v in p["datos"].items())):
            return None
        return p
    except (ValueError, TypeError):
        return None


def preparar_confirmacion_reserva(estado: Estado, datos):
    if not datos or any(not isinstance(k, str) or not isinstance(v, str) for k, v in datos.items()):
        raise ValueError("Los datos del resumen deben ser textos")
    propuesta = {"id": uuid4().hex, "creada": time.time(), "estado": "preparada", "datos": dict(datos)}
    estado.confirmacion_reserva_json = json.dumps(propuesta, ensure_ascii=True, sort_keys=True)
    return propuesta["id"]


def avanzar_confirmacion_reserva(estado: Estado, identidad: str, siguiente: str) -> bool:
    propuesta = leer_confirmacion_reserva(estado)
    anterior = {"ofrecida": "preparada", "aceptada": "ofrecida"}.get(siguiente)
    if not propuesta or propuesta["id"] != identidad or propuesta["estado"] != anterior:
        return False
    propuesta["estado"] = siguiente
    estado.confirmacion_reserva_json = json.dumps(propuesta, ensure_ascii=True, sort_keys=True)
    return True


def contexto_para_ofrecer_reserva(estado: Estado) -> bool:
    """Solo abre reserva nueva desde una cancelación ejecutada y una creación pendiente."""
    if estado.intencion not in ("", "reservar") and not (
            estado.cancelada and estado.esperando_confirmacion):
        return False
    estado.intencion = "reservar"
    if estado.cancelada and estado.esperando_confirmacion:
        estado.hecho = False  # la cancelación terminó; la reserva nueva aún no
    return True


def preparar_propuesta_servicio(estado: Estado, *, servicio_id: str, nombre: str,
                               origen: str, revision_config: str,
                               servicio_origen: str = "", location_id: str = "") -> PropuestaServicio:
    """Registra una alternativa que el llamador YA autorizó para este tenant.

    Primera pieza de la migración: aún no conectada al recorrido conversacional.
    No interpreta Q&A, no selecciona servicio y no confirma una operación.
    La revisión debe representar servicio y política actuales, leídos por código.
    """
    if estado.intencion != "reservar":
        raise ValueError("La alternativa requiere una reserva en curso")
    if not all(isinstance(v, str) and v.strip()
               for v in (servicio_id, nombre, origen, revision_config)):
        raise ValueError("La propuesta requiere servicio, origen y revisión")
    propuesta = PropuestaServicio(
        id=uuid4().hex, servicio_id=servicio_id, nombre=nombre,
        origen=origen, revision_config=revision_config, creada=time.time(),
        servicio_origen=servicio_origen, location_id=location_id)
    if estado.propuesta_servicio is not None:
        invalidar_propuesta_servicio(estado)
    estado.propuesta_servicio = propuesta
    return propuesta


def invalidar_propuesta_servicio(estado: Estado) -> None:
    """Un cambio de servicio/gestión descarta también su resumen pendiente."""
    if estado.propuesta_servicio is not None:
        estado.propuesta_servicio = replace(estado.propuesta_servicio, estado="invalidada")
        estado.esperando_confirmacion = False


def _propuesta_servicio_vigente(estado: Estado, propuesta_id: str) -> Optional[PropuestaServicio]:
    propuesta = estado.propuesta_servicio
    if propuesta is None or propuesta.id != propuesta_id:
        return None
    if estado.intencion != "reservar" or not estado.vigente() or (
            time.time() - propuesta.creada >= CADUCA_EN):
        invalidar_propuesta_servicio(estado)
        return None
    return propuesta


def marcar_propuesta_ofrecida(estado: Estado, propuesta_id: str, mensaje_id: str) -> bool:
    """Solo lo llama el canal después de aceptar la salida que ofrece este id.

    Meta aporta su referencia cuando esté disponible; web/voz pueden usar la
    referencia del turno entregado. Un fallo de envío no llama a esta transición.
    Devuelve True solo si hubo transición, para que una reentrega sea inerte.
    """
    propuesta = _propuesta_servicio_vigente(estado, propuesta_id)
    if propuesta is None or propuesta.estado != "preparada" or not mensaje_id:
        return False
    estado.propuesta_servicio = replace(propuesta, estado="ofrecida", mensaje_id=mensaje_id)
    return True


def responder_propuesta_servicio(estado: Estado, propuesta_id: str, respuesta: str,
                                *, revision_config: str) -> bool:
    """Recibe acepta/rechaza explícitos; fecha o respuesta ambigua no autorizan.

    La revisión actual la aporta el código, nunca un argumento libre del modelo.
    Aceptar conserva el hecho: resolver el servicio y reservar son pasos distintos.
    """
    propuesta = _propuesta_servicio_vigente(estado, propuesta_id)
    if propuesta is None:
        return False
    if propuesta.revision_config != revision_config:
        invalidar_propuesta_servicio(estado)
        return False
    if propuesta.estado != "ofrecida" or respuesta not in ("acepta", "rechaza"):
        return False
    estado.propuesta_servicio = replace(
        propuesta, estado="aceptada" if respuesta == "acepta" else "rechazada")
    return True


def _identidad_persistida(cliente_id: str, telefono: str):
    for canal in ("web", "whatsapp", "voice", "turno"):
        if telefono.startswith(canal + ":"):
            return cliente_id, canal, telefono[len(canal) + 1:]
    # Los adaptadores existentes de WhatsApp llaman con el teléfono sin prefijo.
    return cliente_id, "whatsapp", telefono


def _estado_desde_snapshot(row) -> Estado:
    if row is None or row["formato"] != 1 or row["expires_at"] <= time.time():
        return Estado()
    try:
        data = json.loads(row["payload_json"])
        if not isinstance(data, dict):
            return Estado()
        defaults = Estado()
        valores = {}
        for f in fields(Estado):
            value = data.get(f.name, getattr(defaults, f.name))
            default = getattr(defaults, f.name)
            if f.name == "propuesta_servicio":
                if value is not None:
                    value = PropuestaServicio(**value)
                    if (value.estado not in ("preparada", "ofrecida", "aceptada", "rechazada", "invalidada")
                            or not isinstance(value.creada, (int, float)) or not math.isfinite(value.creada)
                            or any(not isinstance(getattr(value, p.name), str)
                                   for p in fields(PropuestaServicio) if p.name != "creada")):
                        return Estado()
            elif isinstance(default, float):
                if type(value) not in (float, int) or not math.isfinite(value):
                    return Estado()
            elif type(value) is not type(default):
                return Estado()
            elif isinstance(value, list) and any(not isinstance(v, str) for v in value):
                return Estado()
            valores[f.name] = value
        return Estado(**valores)
    except (ValueError, TypeError, KeyError):
        # Un registro incompleto o de otra versión nunca acredita autorización.
        return Estado()


def cargar(cliente_id: str, telefono: str) -> Estado:
    """Lee hechos persistidos; la memoria del worker no decide su vigencia."""
    from backend import conversation_state
    identidad = _identidad_persistida(cliente_id, telefono)
    row = conversation_state.read_conversation_state(*identidad)
    estado = _estado_desde_snapshot(row)
    estado._persistencia = (identidad, int(row["revision"]) if row else 0, time.time())
    return estado


def guardar(cliente_id: str, telefono: str, estado: Estado, pedido: str = "") -> None:
    from backend import conversation_state
    now = time.time()
    identidad = _identidad_persistida(cliente_id, telefono)
    origen, revision, cargado = getattr(estado, "_persistencia", (identidad, 0, now))
    if origen != identidad or now - cargado >= CADUCA_EN:
        raise conversation_state.ConversationStateConflict("El contexto ya no está vigente")
    estado.tocado = now
    estado.ultimo_pedido = pedido
    siguiente = conversation_state.write_conversation_state(
        *identidad, revision=revision, payload=asdict(estado), expires_at=now + CADUCA_EN)
    estado._persistencia = (identidad, siguiente, cargado)
    # Los escritores cargados hace una sesión ya no pueden publicar. Con este
    # margen se pueden retirar snapshots y lápidas vencidos sin resucitarlos.
    try:
        conversation_state.purge_conversation_states(before=now - CADUCA_EN)
    except sqlite3.Error:
        settings.logger.warning("No se pudo limpiar el estado de conversación vencido")


def persistir_respuesta_de_propuesta(cliente_id: str, estado: Estado) -> bool:
    """Publica selección y respuesta juntas antes de devolver aceptación al canal."""
    from backend import conversation_state
    contexto = getattr(estado, "_persistencia", None)
    if contexto is None:
        # Objetos transitorios de las primitivas; no pertenecen a una conversación.
        return True
    identidad, _, _ = contexto
    if identidad[0] != cliente_id:
        return False
    clave = identidad[1] + ":" + identidad[2]
    try:
        guardar(cliente_id, clave, estado, pedido=estado.ultimo_pedido)
    except conversation_state.ConversationStateConflict:
        vigente = cargar(cliente_id, clave)
        estado.__dict__.clear()
        estado.__dict__.update(vigente.__dict__)
        return False
    return True


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
    from backend import conversation_state
    conversation_state.forget_conversation_state(*_identidad_persistida(cliente_id, telefono), now=time.time())


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
        invalidar_propuesta_servicio(estado)
        estado.servicio = ""
        estado.servicio_exacto = ""
        estado.servicio_texto = ""
        estado.duracion = 0
        estado.hora = ""
        estado.hora_del_codigo = False
        estado.huecos = []
        estado.candidatos_pendientes = 0
        estado.ultimo_falta = ""
        estado.veces_falta = 0

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
        if fecha:
            estado.fecha_de_ella = True
        if fecha and fecha != estado.fecha:
            estado.fecha = fecha
            estado.hora = ""      # el hueco de otro dia no vale
            estado.hora_del_codigo = False
            estado.huecos = []
        if not estado.hora:
            hora = textnorm._extract_time_from_text(mensaje or "")
            if not hora:
                hora = _hora_coloquial(mensaje or "", estado.huecos)
            if hora:
                estado.hora = hora
                estado.hora_del_codigo = False
        # "la primera que tengas", "me da igual la hora": ELIGE EL CODIGO. Estaba
        # escrito como instruccion -"coge el primero"- y el modelo respondia
        # volviendo a ofrecerle la lista de horas, otra vez, y otra. Es el fallo
        # mas repetido de todas las mediciones, y en el caso mas simple que hay
        # (venir a cortarse el pelo) se llevaba la cita por delante.
        if not estado.hora and estado.dia_le_da_igual and estado.huecos:
            # Lo que empieza dentro de nada no es "la primera que tengas".
            validos = huecos_con_margen(estado.fecha_de_los_huecos, estado.huecos,
                                        ahora_local(timezone_name))
            if validos:
                estado.hora = validos[0]
                estado.hora_del_codigo = True
                if not estado.fecha and estado.fecha_de_los_huecos:
                    estado.fecha = estado.fecha_de_los_huecos
            else:
                # Los de ese dia ya no dan tiempo: sin huecos sobre la mesa, el
                # agente busca el siguiente de verdad (con margen).
                estado.huecos = []
        # Un "si" a las horas que le ACABAN de ofrecer es elegirlas. Banco de casos
        # `dice-que-si-y-acaba-en-cita` (conversacion real del 9-sep-2026): le
        # ofrecieron la manana, dijo "si", y el modelo volvio a recitar la lista
        # -otra vez mas despues de que ella diera su nombre- y se quedo sin cita.
        if not estado.hora and estado.huecos and _dice_que_si(mensaje):
            validos = huecos_con_margen(estado.fecha_de_los_huecos, estado.huecos,
                                        ahora_local(timezone_name))
            if validos:
                estado.hora = validos[0]
                estado.hora_del_codigo = True
                if not estado.fecha and estado.fecha_de_los_huecos:
                    estado.fecha = estado.fecha_de_los_huecos
        # "me llamo Ana Ruiz": el nombre entra en cuanto lo dice. Antes solo llegaba
        # con la llamada a `crear_cita`, asi que con dia y hora ya puestos seguia
        # "faltando el nombre", el codigo no forzaba el cierre y el modelo volvia a
        # ofrecerle horas (humo `corte-acaba-en-cita`, 11-sep-2026: sin cita).
        if not estado.nombre:
            nombre = nombre_que_dice(mensaje or "")
            if nombre:
                estado.nombre = nombre
        if not estado.codigo:
            codigo = _codigo_en(mensaje or "")
            if codigo:
                estado.codigo = codigo


def _dice_que_si(mensaje: str) -> bool:
    """El MISMO "si" que reconoce el canal, no uno propio.

    `whatsapp._wa_dice_que_si` ya distingue un si de un "si, pero mejor a las 5".
    Tener aqui otra lista seria tener dos criterios y arreglar el mismo caso raro
    en dos sitios.
    """
    from backend import catalog_pick, whatsapp

    try:
        return bool(whatsapp._wa_dice_que_si(catalog_pick._norm(mensaje or "")))
    except Exception:  # noqa: BLE001 - reconocer un si no puede tumbar la conversacion
        return False


def _codigo_en(texto: str) -> str:
    import re

    encontrado = re.search(r"R-?\s?(\d{3,})", texto or "", re.IGNORECASE)
    return ("R-" + encontrado.group(1)) if encontrado else ""


# Donde acaba un nombre dicho de corrido: "me llamo Ana y quiero un corte".
_CORTA_EL_NOMBRE = {"y", "e", "para", "que", "quiero", "pero", "porque", "por",
                    "gracias", "vale", "si", "no"}
_NO_EMPIEZA_UN_NOMBRE = {"el", "la", "los", "las", "un", "una"}


def nombre_que_dice(texto: str) -> str:
    """El nombre, si lo dice con todas las letras ("me llamo Ana Ruiz").

    Solo la formula, nada de adivinar: "soy de Elche" o "soy alergica" no son
    nombres, asi que "soy" no cuenta. Si no hay formula, el nombre sigue llegando
    como antes, en la llamada a `crear_cita`.
    """
    import re

    from backend import agent, textnorm

    encontrado = re.search(
        r"\b(?:me llamo|mi nombre es)\s+([^\W\d_][\w'-]*(?:\s+[^\W\d_][\w'-]*){0,5})",
        str(texto or ""), re.IGNORECASE,
    )
    if not encontrado:
        return ""
    palabras = []
    for palabra in encontrado.group(1).split():
        if textnorm._strip_accents(palabra.lower()) in _CORTA_EL_NOMBRE:
            break
        palabras.append(palabra)
    if not palabras or palabras[0].lower() in _NO_EMPIEZA_UN_NOMBRE:
        return ""
    nombre = " ".join(palabras[:4])
    if not agent._nombre_de_verdad(nombre):
        return ""
    if nombre == nombre.lower():
        nombre = nombre.title()
    return nombre[:80]


def _fecha_hablada(fecha_iso: str) -> str:
    """"martes 15 de septiembre", no el ISO crudo."""
    from backend import textnorm

    try:
        return textnorm._format_date_es(textnorm._parse_date(fecha_iso).date())
    except Exception:  # noqa: BLE001
        return fecha_iso


# "La primera que tengas" no puede ser dentro de diez minutos: entre el nombre y la
# confirmacion pasan varios, y el hueco se pasa o no da tiempo a llegar.
MARGEN_PRIMER_HUECO_MIN = 60


def ahora_local(timezone_name: str = ""):
    """La hora de ahora en la zona del negocio. None si no se sabe la zona.

    Sin zona no se recorta nada: mejor no poner margen que ponerlo mal.
    """
    if not timezone_name:
        return None
    from backend import timeutils

    try:
        try:
            from zoneinfo import ZoneInfo
        except ImportError:  # Python 3.8
            from backports.zoneinfo import ZoneInfo
        return timeutils._utc_now().astimezone(ZoneInfo(timezone_name))
    except Exception:  # noqa: BLE001
        return None


def huecos_con_margen(dia: str, huecos: List[str], ahora,
                      minutos: int = MARGEN_PRIMER_HUECO_MIN) -> List[str]:
    """Los huecos de HOY que aun dan tiempo; los de otro dia, tal cual.

    Medido el 11-sep-2026 (humo `corte-acaba-en-cita`): a las 17:35, a "la primera
    que tengas" se le elegia hoy a las 17:45, y a las 17:55 hoy a las 18:00.
    """
    from datetime import timedelta

    if not dia or ahora is None or dia != ahora.date().isoformat():
        return list(huecos)
    limite = ahora + timedelta(minutes=minutos)
    if limite.date() != ahora.date():
        return []
    corte = limite.strftime("%H:%M")
    return [h for h in huecos if str(h)[:5] >= corte]


def dia_cambiado_con_la_hora_elegida(estado: Estado, argumentos: Dict[str, Any]) -> bool:
    """¿La cita que va a crear el modelo mezcla la hora elegida con OTRO dia?

    Solo cuando la hora la eligio el codigo ("la primera que tengas"), el dia no
    lo ha dicho ella y la llamada trae ESA hora con un dia distinto: una mezcla,
    no otra eleccion. Si cambia la hora, o el dia lo dijo ella, no se toca.
    """
    if not (estado.hora_del_codigo and estado.dia_le_da_igual and not estado.fecha_de_ella):
        return False
    fecha = str(argumentos.get("fecha") or "").strip()
    hora = str(argumentos.get("hora") or "").strip()[:5]
    return bool(estado.fecha and estado.hora and fecha and fecha != estado.fecha
                and hora == estado.hora[:5])


# ─── Lo que dicen las tools (la verdad del servidor) ───────────────────────

def _es_otro_servicio(guardado: str, pedido: str) -> bool:
    """¿Son dos servicios DISTINTOS, o el mismo dicho de otra forma?

    Uno dentro del otro es el mismo: el catalogo guarda "Pack keratina premium
    medio" y al hablar se dice "keratina premium medio". Confundirlos sale caro en
    la otra direccion -esos dos SI son servicios distintos en el catalogo, de 30
    minutos y de casi cuatro horas-, por eso aqui solo se decide "es otro" cuando
    ninguno contiene al otro.
    """
    from backend import textnorm

    # Sin palabras de enlace: "Corte de señora" es "Corte señora" (11-sep-2026).
    a = textnorm.clave_sin_conectores(guardado or "")
    b = textnorm.clave_sin_conectores(pedido or "")
    if not a or not b:
        return bool(b) and not a
    return a not in b and b not in a


def _amplia_el_nombre(viejo: str, nuevo: str) -> bool:
    """¿`nuevo` es `viejo` con algo mas detras? ("Ana Ruiz" -> "Ana Ruiz Pérez")"""
    from backend import textnorm

    antes = textnorm.normalizar(viejo).split()
    despues = textnorm.normalizar(nuevo).split()
    return len(despues) > len(antes) and despues[:len(antes)] == antes


def anotar_resultado(estado: Estado, tool: str, argumentos: Dict[str, Any],
                     resultado: Dict[str, Any], ahora: Any = None) -> None:
    """Actualiza el estado con lo que ha DEVUELTO una herramienta.

    `ahora` es la hora del negocio (`ahora_local`): con ella no se elige por la
    clienta un hueco de hoy que ya no da tiempo.
    """
    if not isinstance(resultado, dict):
        return
    if (estado.propuesta_servicio is not None
            and estado.propuesta_servicio.estado in ("preparada", "ofrecida")
            and tool in ("buscar_servicio", "consultar_disponibilidad", "crear_cita")):
        # Consultar una alternativa no es elegirla. Los datos provisionales se
        # devuelven al modelo, pero no pisan la reserva ni habilitan su resumen.
        return
    if resultado.get("pendiente_de_confirmacion"):
        # La creacion se ha frenado a proposito (la confirma la clienta con un
        # boton), pero los datos que traia la llamada son buenos y son los unicos
        # que hay: el nombre no lo devuelve ninguna herramienta. Sin recogerlos, el
        # resumen no se podia montar y la conversacion se quedaba colgada.
        # El SERVICIO que trae la llamada MANDA sobre el que hubiera guardado: es lo
        # que la clienta va a ver en el resumen y confirmar, y el estado no puede
        # contradecirlo.
        #
        # Paso de verdad: la clienta empezo diciendo "unas mechas y cortarme... el
        # corte es para mi, de senyora", y ahi se guardo "Corte senora". Veinte
        # mensajes despues estaba eligiendo un alisado -pregunto por la queratina,
        # por el acido lactico bio premium, pidio hora con Alicia-, y el resumen
        # final decia "Servicio: Corte senora". Rellenar solo los huecos hacia que
        # ganase siempre lo primero que se dijo.
        pedido = str(argumentos.get("servicio") or "").strip()
        if pedido and _es_otro_servicio(estado.servicio_exacto or estado.servicio, pedido):
            estado.servicio = pedido
            # El nombre exacto del catalogo era el del servicio ANTERIOR: se suelta
            # para que se vuelva a resolver con el nuevo.
            estado.servicio_exacto = ""
            estado.duracion = 0
        # El DIA y la HORA de la llamada mandan igual que el servicio, y por lo
        # mismo: es lo que ella va a leer en el resumen y confirmar.
        #
        # Medido: la clienta pidio "el martes 2 a las 11:15" TRES veces y el resumen
        # decia "martes 1 de septiembre, 10:00" -el primer dia que se habia
        # consultado-. Al confirmar, ese hueco ya estaba ocupado y la conversacion
        # se fue al garete. Rellenar solo los huecos hace que gane siempre lo
        # primero que se miro, no lo ultimo que ella dijo.
        for clave in ("fecha", "hora"):
            valor = str(argumentos.get(clave) or "").strip()
            if valor:
                setattr(estado, clave, valor)
        # Lo que trae la cita que va a confirmar es suyo, no una eleccion del codigo.
        if str(argumentos.get("fecha") or "").strip():
            estado.fecha_de_ella = True
        if str(argumentos.get("hora") or "").strip():
            estado.hora_del_codigo = False
        # Si le faltaban apellidos y los ha dado, el nombre mas completo manda: el
        # resumen tiene que salir con ellos (dos apellidos a clientas nuevas).
        nombre_nuevo = str(argumentos.get("nombre") or "").strip()
        if nombre_nuevo and estado.nombre and _amplia_el_nombre(estado.nombre, nombre_nuevo):
            estado.nombre = nombre_nuevo
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
        # Una llamada RECHAZADA puede traer datos buenos. Pasa cuando se frena por
        # haber pedido varias cosas: la cita no se crea -y bien-, pero el nombre, el
        # dia y la hora son los que ella acaba de dar. Tirarlos obligaba a
        # preguntarselo todo otra vez justo en el ultimo paso, y ahi se iba.
        #
        # Solo se rellena lo que este VACIO: un rechazo no puede pisar lo que ya se
        # sabia. Y no se enciende `esperando_confirmacion`: no hay nada que
        # confirmar todavia.
        if resultado.get("conserva_los_datos"):
            for clave in ("fecha", "hora", "nombre", "profesional"):
                valor = str(argumentos.get(clave) or "").strip()
                if valor and not getattr(estado, clave, ""):
                    setattr(estado, clave, valor)
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
            # "La primera que tengas" con la hora puesta por el CODIGO: si el modelo
            # acaba de mirar otro dia, lo que ella va a leer son las horas de ESE
            # dia, y el estado tiene que decir lo mismo. Medido el 11-sep-2026: el
            # codigo habia elegido hoy a las 17:45, el modelo le ofrecio el martes
            # 15, y la conversacion acabo sin cita porque cada uno hablaba de un
            # dia distinto. Lo que haya dicho ella -un dia, una hora- no se toca.
            validos = huecos_con_margen(fecha, huecos, ahora)
            if (validos and fecha and estado.dia_le_da_igual and estado.intencion == "reservar"
                    and not estado.hecho and not estado.fecha_de_ella
                    and (not estado.hora or estado.hora_del_codigo)):
                estado.fecha = fecha
                estado.hora = validos[0]
                estado.hora_del_codigo = True

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
    invalidar_propuesta_servicio(estado)
    estado.confirmacion_reserva_json = ""
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
    estado.hora_del_codigo = False
    estado.fecha_de_ella = False
    estado.hecho = False
    estado.cancelada = False
    estado.ya_creada = False
    estado.esperando_confirmacion = False
    estado.ultimo_falta = ""
    estado.candidatos_pendientes = 0
    estado.veces_falta = 0
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
        if intencion != estado.intencion:
            invalidar_propuesta_servicio(estado)
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
    if (estado.propuesta_servicio is not None
            and estado.propuesta_servicio.estado in ("preparada", "ofrecida")):
        return "propuesta"
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


def instruccion_de_cierre(estado: Estado, nombre_conocido: str = "", cliente_id: str = "") -> str:
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
    # El hueco ya lo ha elegido el codigo y solo falta su nombre. Sin decirselo, el
    # modelo miraba otro dia y le volvia a ensenar la lista de horas.
    if (falta == "nombre" and estado.dia_le_da_igual and estado.hora_del_codigo
            and estado.fecha and estado.hora):
        from backend import clients

        identificacion = ("nombre y sus dos apellidos" if cliente_id and clients.exige_dos_apellidos(cliente_id)
                          else "nombre y apellidos")
        return ("Le da igual el dia y ya tienes el primer hueco que hay: el %s a las "
                "%s. Proponselo tal cual y pidele su %s para "
                "apuntarla. NO mires "
                "otros dias ni le ofrezcas una lista de horas."
                % (_fecha_hablada(estado.fecha), estado.hora, identificacion))
    return ""
