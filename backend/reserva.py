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
    servicio: str = ""           # nombre EXACTO del catalogo
    duracion: int = 0
    fecha: str = ""              # AAAA-MM-DD
    hora: str = ""               # HH:MM
    nombre: str = ""
    codigo: str = ""             # la cita que ya tiene, si gestiona una
    huecos: List[str] = field(default_factory=list)   # los que se le han ofrecido
    dia_le_da_igual: bool = False
    hecho: bool = False          # la gestion se completo en esta conversacion
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


def olvidar(cliente_id: str, telefono: str) -> None:
    guardados = getattr(appstate, "ESTADOS_DE_RESERVA", None) or {}
    guardados.pop(_clave(cliente_id, telefono), None)


# ─── Lo que dice la clienta ────────────────────────────────────────────────

_LE_DA_IGUAL = (
    "me da igual", "cualquier", "el que sea", "lo que tengas", "que tengas",
    "primer hueco", "primera hora", "cuando puedas", "lo antes posible",
    "cuanto antes", "me vale", "lo mas pronto", "ya mismo", "urgente",
)


def anotar_lo_que_dice(estado: Estado, mensaje: str, timezone_name: str = "") -> None:
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

    if not estado.hecho:
        if not estado.fecha:
            fecha = textnorm._extract_date_from_text(mensaje or "", timezone_name or "Europe/Madrid")
            if fecha:
                estado.fecha = fecha
        if not estado.hora:
            hora = textnorm._extract_time_from_text(mensaje or "")
            if hora:
                estado.hora = hora
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
    if not isinstance(resultado, dict) or not resultado.get("ok"):
        return

    if tool == "buscar_servicio" and resultado.get("servicio"):
        estado.servicio = str(resultado["servicio"])
        estado.duracion = int(resultado.get("duracion_minutos") or 0)

    elif tool == "consultar_disponibilidad":
        fecha = str(argumentos.get("fecha") or resultado.get("fecha") or "")
        huecos = [str(h) for h in (resultado.get("huecos") or [])]
        if huecos:
            estado.fecha = fecha
            estado.huecos = huecos[:8]

    elif tool == "consultar_cita":
        estado.codigo = str(resultado.get("codigo_reserva") or estado.codigo)
        estado.servicio = str(resultado.get("servicio") or estado.servicio)
        estado.fecha = str(resultado.get("fecha") or estado.fecha)
        estado.hora = str(resultado.get("hora") or estado.hora)

    elif tool in ("crear_cita", "reprogramar_cita", "cancelar_cita"):
        estado.hecho = True
        estado.codigo = str(resultado.get("codigo_reserva") or estado.codigo)
        if tool != "cancelar_cita":
            estado.fecha = str(resultado.get("fecha") or estado.fecha)
            estado.hora = str(resultado.get("hora") or estado.hora)


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
    if estado.servicio:
        detalle = estado.servicio
        if estado.duracion:
            detalle += " (%d min)" % estado.duracion
        lineas.append("- Servicio: %s" % detalle)
    if estado.codigo:
        lineas.append("- Su cita: %s" % estado.codigo)
    if estado.fecha:
        lineas.append("- Dia: %s" % estado.fecha)
    if estado.hora:
        lineas.append("- Hora: %s" % estado.hora)
    if estado.nombre or nombre_conocido:
        lineas.append("- Se llama: %s" % (estado.nombre or nombre_conocido))
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
        return ("La gestion YA esta hecha. Confirmasela con naturalidad y no vuelvas "
                "a tocarla: si te dice que si, es un acuse de recibo.")
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
    if falta == "hora" and estado.dia_le_da_igual and estado.huecos:
        return ("Le da igual la hora: coge el primero (%s) y remata la gestion con "
                "la herramienta que toque." % estado.huecos[0])
    if falta == "dia" and estado.dia_le_da_igual:
        return ("Le da igual el dia: mira los huecos del primer dia que abris y "
                "ofrecele dos o tres horas. NO le preguntes que dia quiere.")
    return ""
