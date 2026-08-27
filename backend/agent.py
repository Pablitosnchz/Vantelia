# -*- coding: utf-8 -*-
"""Coger una cita conversando: el modelo decide, las tools no le dejan mentir.

POR QUE ESTE MODULO
-------------------
Un salon real pidio que su asistente NO usara listas ni formulario: "que la IA le
guie, que le diga que estilo quiere hacerse, y si dice mechas que le pregunte como
tiene el pelo". Y que recomiende, como una companera del mostrador.

Dos intentos anteriores se quedaron cortos, cada uno por un lado:

* Un maquina de estados con listas: fiable, pero no recomienda ni se adapta.
* Un prompt que decidia el servicio: recomendaba, pero decidia distinto en cada
  ejecucion, elegia tecnicas por la clienta (tres alisados de 240 a 260 EUR) y una
  vez dijo "te he reservado" cuando aun faltaba el dia.

Esta es la tercera, y es la que ya usa el asistente de VOZ desde hace meses:
**el modelo lleva la conversacion y las TOOLS ponen la fiabilidad**. El modelo
puede recomendar, explicar y adaptarse todo lo que quiera; lo que no puede es
inventarse un servicio, un hueco ni una cita, porque eso no lo escribe: lo pide.

QUE GARANTIZAN LAS TOOLS
------------------------
* `buscar_servicio` solo devuelve servicios que existen en SU catalogo.
* `consultar_disponibilidad` solo devuelve huecos reales de su agenda.
* `crear_cita` exige TODOS los datos y comprueba el hueco; si falta algo o el
  hueco ya no esta, responde que no y por que. La cita la crea el mismo nucleo que
  el resto de canales (`booking._create_booking_core`).

Es decir: el modelo no puede decir "te he reservado" y que sea mentira, porque el
numero de reserva solo existe si `crear_cita` lo devuelve.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from backend import catalog_pick, clients, db, settings, textnorm, timeutils

# Cuantas vueltas de tool se le permiten en un turno. Con 4 le sobra para buscar
# un servicio, mirar huecos y crear la cita; el tope existe para que un modelo
# atascado no deje a la clienta esperando.
MAX_VUELTAS = 6

# Cuanta conversacion se le recuerda. Suficiente para que "y el jueves?" tenga
# sentido, sin pagar por la conversacion entera.
MAX_HISTORIAL = 12

# Cuanto silencio convierte lo hablado en "otra conversacion". Media hora es lo
# que ya usa el resto del producto para dar una sesion por cerrada.
SILENCIO_QUE_CIERRA = settings.SESSION_TTL_SECONDS


def disponible(cliente_id: str) -> bool:
    """¿Se puede conversar con el modelo para este negocio?"""
    return bool(settings.OPENAI_API_KEY)


# ─── Las herramientas que se le ofrecen ────────────────────────────────────

def _herramientas() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "buscar_servicio",
                "description": (
                    "Busca en el catalogo REAL del negocio el servicio que describe la "
                    "clienta. Devuelve el servicio exacto, o que dato falta para poder "
                    "concretarlo (la tecnica o el largo del pelo). Usala SIEMPRE antes "
                    "de dar por elegido un servicio: no te inventes nombres."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "descripcion": {
                            "type": "string",
                            "description": "Todo lo que ha dicho sobre lo que quiere hacerse.",
                        },
                    },
                    "required": ["descripcion"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_horario",
                "description": (
                    "El horario REAL del negocio: si esta abierto ahora mismo, a que "
                    "hora abre y cierra un dia concreto, y que dias libra. Usala "
                    "siempre que pregunten por horarios: no te lo sepas de memoria."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fecha": {
                            "type": "string",
                            "description": "AAAA-MM-DD. Vacio = hoy y la semana.",
                        },
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "politica_del_negocio",
                "description": (
                    "Lo que ESTE negocio tiene decidido sobre un tema: precios, "
                    "señales y fianzas, cancelaciones, como venir preparada, formas de "
                    "pago, promociones... Devuelve el texto que ha escrito el propio "
                    "negocio. Usala antes de contestar nada que dependa de sus normas: "
                    "no te inventes politicas y no supongas lo que hace otro salon."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tema": {
                            "type": "string",
                            "description": "Sobre que pregunta, con sus palabras.",
                        },
                    },
                    "required": ["tema"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_cita",
                "description": (
                    "Busca la cita de quien escribe. Con el numero de reserva si lo "
                    "da; si no, por su telefono. Usala antes de cancelar o cambiar."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "codigo_reserva": {"type": "string", "description": "R-XXXX si lo dice"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cancelar_cita",
                "description": (
                    "Cancela una cita. Necesita el numero de reserva. La cita solo "
                    "queda cancelada si esta tool lo confirma."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "codigo_reserva": {"type": "string"},
                        "motivo": {"type": "string"},
                    },
                    "required": ["codigo_reserva"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "reprogramar_cita",
                "description": (
                    "Mueve una cita a otro dia u hora. Comprueba que el hueco nuevo "
                    "este libre; si no lo esta, te lo dice y no cambia nada."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "codigo_reserva": {"type": "string"},
                        "fecha": {"type": "string", "description": "AAAA-MM-DD"},
                        "hora": {"type": "string", "description": "HH:MM"},
                    },
                    "required": ["codigo_reserva", "fecha", "hora"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_profesionales",
                "description": (
                    "Quien puede atenderla y si con alguien cuesta mas. Usala cuando "
                    "pregunte por una profesional concreta, cuando pida elegir, o "
                    "antes de cerrar la cita si el negocio tiene varias."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "servicio": {"type": "string", "description": "para filtrar quien lo hace"},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "consultar_disponibilidad",
                "description": (
                    "Huecos REALES de la agenda para un dia. Usala antes de ofrecer "
                    "ninguna hora: no te inventes horarios."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fecha": {"type": "string", "description": "AAAA-MM-DD"},
                        "servicio": {"type": "string"},
                    },
                    "required": ["fecha"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "crear_cita",
                "description": (
                    "Crea la cita DE VERDAD. Solo cuando tengas servicio, fecha, hora y "
                    "el nombre de la clienta. Si falta algo o el hueco ya no esta, te lo "
                    "dira y no se creara nada. El numero de reserva que devuelve es el "
                    "unico que puedes darle."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "servicio": {"type": "string"},
                        "fecha": {"type": "string", "description": "AAAA-MM-DD"},
                        "hora": {"type": "string", "description": "HH:MM"},
                        "nombre": {"type": "string"},
                        "email": {"type": "string"},
                        "notas": {"type": "string"},
                        "profesional": {
                            "type": "string",
                            "description": (
                                "Solo si ha pedido a alguien en concreto. Vacio = la "
                                "que este libre."
                            ),
                        },
                    },
                    "required": ["servicio", "fecha", "hora", "nombre"],
                },
            },
        },
    ]


# Lo que escribe un modelo cuando le falta el nombre y la tool se lo exige. No son
# nombres: son un hueco relleno para poder llamar a la tool.
_NOMBRES_QUE_NO_LO_SON = {
    "clienta", "cliente", "la clienta", "el cliente", "sin nombre", "nombre",
    "desconocido", "anonimo", "n/a", "na", "-", "usuario", "invitado", "señora",
    "senora", "sra", "sr", "chica",
}


def _es_una_profesional(cliente_id: str, valor: str) -> bool:
    """¿Ese "nombre de la clienta" es en realidad el de quien la va a atender?

    Paso de verdad: a "un corte de señora con Alicia" le cogio la cita a nombre de
    "Alicia". El modelo toma el primer nombre propio que ve.
    """
    from backend import agenda

    limpio = textnorm._strip_accents(str(valor or "").strip().lower())
    if not limpio:
        return False
    try:
        for fila in agenda._list_public_employee_rows(cliente_id):
            nombre = textnorm._strip_accents(str(fila["name"] or "").strip().lower())
            if nombre and (nombre == limpio or nombre.split()[0] == limpio):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


# Formas en que una clienta pide a alguien en concreto. Hace falta el CONTEXTO:
# el salon se llama "Alicia Rincon Estilistas", asi que buscar solo el nombre
# saltaria con "quiero cita en Alicia Rincon" -que no pide a nadie- y le soltaria
# a todo el mundo el texto del 25 %.
_PIDE_A_ALGUIEN = (
    r"\bcon\s+(?:la\s+)?(?:propia\s+)?%s\b",
    r"\b(?:atienda|atiende|me\s+lo\s+haga|me\s+la\s+haga|lo\s+haga|quiero\s+a|pido\s+a|"
    r"prefiero\s+a|sea)\s+(?:la\s+)?(?:propia\s+)?%s\b",
    r"\b%s\s+(?:personalmente|en\s+persona|misma)\b",
)


def _aviso_de_recargo(cliente_id: str, dicho: str, servicio: str = "") -> str:
    """Si ha pedido a una profesional que cuesta mas, lo que el negocio quiere decirle.

    NO se deja en manos del modelo. Antes dependia de que llamase a
    `consultar_profesionales`, y en una prueba real la clienta pidio mechas "con
    Alicia", pregunto el precio dos turnos despues, y el 25 % no salio ni una vez:
    o el negocio se come la diferencia, o queda como que se lo callo hasta el final.

    El texto lo escribe el salon, no nosotros: es su explicacion de por que cuesta
    mas, y la quiere distinta segun el servicio.
    """
    from backend import agenda

    plano = textnorm._strip_accents(str(dicho or "").lower())
    if not plano:
        return ""
    try:
        filas = agenda._list_public_employee_rows(cliente_id)
    except Exception:  # noqa: BLE001
        return ""
    for fila in filas:
        pct = agenda.recargo_pct(fila)
        if not pct:
            continue
        nombre = str(fila["name"] or "").strip()
        pila = textnorm._strip_accents(nombre.lower())
        primero = re.escape(pila.split()[0]) if pila else ""
        if not primero:
            continue
        if not any(re.search(patron % primero, plano) for patron in _PIDE_A_ALGUIEN):
            continue
        texto = agenda.texto_del_recargo(fila, servicio)
        if not texto:
            return ""
        return (
            "HA PEDIDO QUE LA ATIENDA %s, y con ella el servicio cuesta un %d%% mas. "
            "Dile ESTO, tal cual, con sus mismas palabras (puedes saludar antes, pero "
            "no lo resumas ni te lo inventes):\n\n%s\n\n"
            "Si ya se lo has dicho antes en esta conversacion, no lo repitas: sigue "
            "con la cita." % (nombre.upper(), pct, texto)
        )
    return ""


def _nombre_de_verdad(valor: str) -> bool:
    """¿Esto es el nombre de una persona o un hueco relleno?"""
    limpio = " ".join(str(valor or "").split())
    if len(limpio) < 2:
        return False
    return catalog_pick._norm(limpio) not in _NOMBRES_QUE_NO_LO_SON


def _firma(argumentos: Dict[str, Any]) -> str:
    """Que cita es esta, para no crearla dos veces en la misma conversacion."""
    from backend import voice_engine

    try:
        return voice_engine.booking_signature(argumentos) or ""
    except Exception:  # noqa: BLE001
        return "|".join(str(argumentos.get(k) or "") for k in ("servicio", "fecha", "hora"))


def _cita_identica(cliente_id: str, telefono: str, argumentos: Dict[str, Any]) -> str:
    """El numero de una cita viva identica de este telefono, si ya existe.

    Evita la doble reserva ENTRE turnos: el modelo puede volver a llamar a
    `crear_cita` cuando la clienta le da un dato mas, y crear otra igual.
    """
    from backend import crm

    fecha = str(argumentos.get("fecha") or "").strip()
    hora = str(argumentos.get("hora") or "").strip()[:5]
    if not (fecha and hora and telefono):
        return ""
    try:
        buscado = crm._normalize_phone_for_match(telefono)
        with db._get_db_connection() as conexion:
            filas = conexion.execute(
                "SELECT booking_code, telefono FROM bookings WHERE cliente_id = ?"
                " AND booking_date = ? AND booking_time = ?"
                " AND status NOT IN ('cancelled', 'no_show')",
                (cliente_id, fecha, hora),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - comprobar no puede romper la reserva
        settings.logger.warning("[agenda-agente] no se pudo comprobar duplicado: %s", exc)
        return ""
    for fila in filas:
        try:
            if crm._normalize_phone_for_match(str(fila["telefono"] or "")) == buscado:
                return str(fila["booking_code"] or "")
        except Exception:  # noqa: BLE001
            continue
    return ""


# El modelo escribe el nombre del argumento que le parece ("codigo" en vez de
# "codigo_reserva", "nueva_fecha" en vez de "fecha"). El despachador solo lee el
# suyo, asi que la llamada se perdia en silencio: consultar, cancelar y cambiar una
# cita por su numero NO funcionaban desde el chat ni desde WhatsApp, y el asistente
# contestaba "no encuentro ninguna cita con ese numero" con la cita delante.
_ALIAS_DE_ARGUMENTO = {
    "codigo": "codigo_reserva",
    "codigo_de_reserva": "codigo_reserva",
    "numero_reserva": "codigo_reserva",
    "numero_de_reserva": "codigo_reserva",
    "reserva": "codigo_reserva",
    "booking_code": "codigo_reserva",
    "nueva_fecha": "fecha",
    "nueva_hora": "hora",
    "telefono_contacto": "telefono",
    "nombre_cliente": "nombre",
}


def _normalizar_argumentos(argumentos: Dict[str, Any]) -> Dict[str, Any]:
    """Traduce los nombres de argumento que el modelo se inventa a los de verdad."""
    salida = {}
    for clave, valor in (argumentos or {}).items():
        destino = _ALIAS_DE_ARGUMENTO.get(str(clave).strip().lower(), clave)
        if destino not in salida or (salida.get(destino) in ("", None)):
            salida[destino] = valor
    return salida


async def _ejecutar(
    cliente_id: str, nombre: str, argumentos: Dict[str, Any], *,
    telefono: str, location_id: str = "", ya_creadas: Optional[set] = None,
    quien: Optional[Dict[str, str]] = None, remate_manual: bool = False,
) -> Dict[str, Any]:
    """Ejecuta una tool. Nunca lanza: un fallo se devuelve como resultado."""
    argumentos = _normalizar_argumentos(argumentos)
    if nombre == "buscar_servicio":
        return _tool_buscar_servicio(cliente_id, argumentos, location_id=location_id)

    if nombre == "consultar_horario":
        return _tool_consultar_horario(cliente_id, argumentos)

    if nombre == "politica_del_negocio":
        return _tool_politica_del_negocio(cliente_id, argumentos)

    if nombre == "consultar_profesionales":
        return _tool_consultar_profesionales(cliente_id, argumentos, location_id=location_id)

    if nombre == "crear_cita" and remate_manual and _es_una_profesional(
        cliente_id, argumentos.get("nombre")
    ):
        argumentos["profesional"] = argumentos.get("profesional") or argumentos["nombre"]
        argumentos["nombre"] = ""

    if nombre == "crear_cita" and remate_manual and _nombre_de_verdad(
        argumentos.get("nombre") or (quien or {}).get("nombre", "")
    ):
        # El canal quiere que la cita la confirme la clienta con un boton. No basta
        # con no forzar la herramienta: el modelo la llamaba igual y la cita nacia
        # antes de que ella confirmase nada. Aqui se le impide de verdad.
        return {
            "ok": False,
            "pendiente_de_confirmacion": True,
            "error": "Todavia no se puede crear: lo confirma la clienta.",
            # OJO a como se le pide: con "dile que se lo pasas para confirmar"
            # contestaba "voy a pasar esto para que lo confirmen", que suena a que
            # se lo manda a una persona y deja a la clienta esperando. Justo
            # despues le llega el resumen con los botones: no hay que anunciar nada.
            "que_hacer": ("Confirma en UNA frase corta lo que teneis (servicio, dia y "
                          "hora) y di que le pasas el resumen para que lo confirme "
                          "ella. NO digas que se lo pasas a nadie, ni que esta "
                          "reservada, ni le des ningun numero de reserva."),
        }

    # OJO al orden: si el freno fuera lo PRIMERO, un nombre inventado se colaria
    # sin pasar por la comprobacion de abajo y la cita saldria a nombre de
    # "cliente". Paso: el resumen decia "👤 cliente".

    if nombre == "crear_cita":
        # El modelo rellena "nombre" con cualquier cosa con tal de poder llamar a
        # la tool. Sin nombre de verdad, no hay cita.
        # De una clienta conocida ya se sabe el nombre: lo pone el codigo antes de
        # dar por incompleta la cita, en vez de hacersela repetir.
        if _es_una_profesional(cliente_id, argumentos.get("nombre")):
            # Se ha quedado con el nombre de la peluquera: eso no es la clienta.
            argumentos["profesional"] = argumentos.get("profesional") or argumentos["nombre"]
            argumentos["nombre"] = ""
        if not _nombre_de_verdad(argumentos.get("nombre")) and (quien or {}).get("nombre"):
            argumentos["nombre"] = quien["nombre"]
        if not _nombre_de_verdad(argumentos.get("nombre")):
            return {
                "ok": False,
                "error": "Falta el nombre de la clienta.",
                "que_hacer": "Preguntale como se llama antes de crear la cita.",
            }
        firma = _firma(argumentos)
        if ya_creadas is not None and firma and firma in ya_creadas:
            return {
                "ok": True, "duplicada": True,
                "mensaje": "Esa cita ya estaba creada; no se ha duplicado.",
            }
        # El duplicado real ocurrio ENTRE turnos (creo una sin nombre y otra con
        # el nombre), asi que la memoria del turno no basta: se mira la agenda.
        existente = _cita_identica(cliente_id, telefono, argumentos)
        if existente:
            return {
                "ok": True, "duplicada": True, "booking_code": existente,
                "mensaje": "Esa cita ya estaba creada (%s); no se ha duplicado." % existente,
            }

    # Disponibilidad y creacion de cita reusan el despachador que ya usa la voz:
    # es agnostico del canal (nombre de tool + argumentos -> resultado) y asi no
    # hay dos formas distintas de crear una cita.
    from backend import voice

    resultado = await voice._voice_dispatch_tool(
        cliente_id, nombre, json.dumps(argumentos, ensure_ascii=False),
        from_number=telefono, location_id=location_id,
    )
    if nombre == "crear_cita" and resultado.get("ok") and ya_creadas is not None:
        firma = _firma(argumentos)
        if firma:
            ya_creadas.add(firma)
    return resultado


def _tool_consultar_profesionales(
    cliente_id: str, argumentos: Dict[str, Any], *, location_id: str = "",
) -> Dict[str, Any]:
    """Quien atiende y con quien cuesta mas.

    Existe porque el asistente cerraba todas las citas con "Asignacion automatica"
    y nadie podia pedir a alguien en concreto. Y hay negocios donde elegir a la
    duenya cuesta un porcentaje mas: eso hay que DECIRLO antes de coger la cita,
    no en el mostrador.
    """
    from backend import agenda

    servicio = str(argumentos.get("servicio") or "").strip()
    try:
        empleados = agenda._list_public_employee_rows(cliente_id)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[agente] sin profesionales (%s): %s", cliente_id, exc)
        return {"ok": False, "error": "No he podido mirar quien atiende."}

    fila_servicio = agenda._find_service_by_name(cliente_id, servicio) if servicio else None
    base = int(fila_servicio["price_cents"] or 0) if fila_servicio is not None else 0

    gente = []
    for empleado in empleados:
        if location_id and (empleado["location_id"] or "") and empleado["location_id"] != location_id:
            continue
        if fila_servicio is not None:
            suyos = agenda._employee_service_ids_from_row(empleado, cliente_id)
            if suyos and fila_servicio["slug"] not in suyos:
                continue
        pct = agenda.recargo_pct(empleado)
        ficha = {"nombre": empleado["name"], "recargo_pct": pct}
        if pct:
            # El texto lo escribe el negocio, no nosotros: es su explicacion de por
            # que cuesta mas, y la quiere distinta segun el servicio.
            ficha["que_decirle"] = agenda.texto_del_recargo(empleado, servicio)
            if base > 0:
                ficha["precio_con_ella"] = textnorm._format_price_cents(
                    agenda.precio_con_recargo(base, empleado)
                )
        gente.append(ficha)

    con_recargo = [g for g in gente if g["recargo_pct"]]
    return {
        "ok": True,
        "profesionales": gente,
        "hay_recargo": bool(con_recargo),
        "nota": (
            ("NO le preguntes con quien quiere: se le asigna sola. Solo si ELLA "
             "nombra a %s, mandale su texto (`que_decirle`) tal cual, porque con "
             "ella cuesta un %d%% mas. Con el resto del equipo vale lo mismo."
             % (con_recargo[0]["nombre"], con_recargo[0]["recargo_pct"]))
            if con_recargo else
            "Todas cobran lo mismo. NO le preguntes con quien quiere: se asigna sola."
        ),
    }


def _tool_consultar_horario(cliente_id: str, argumentos: Dict[str, Any]) -> Dict[str, Any]:
    """El horario real, y si esta abierto AHORA.

    Existe porque "¿estais abiertos ahora?" no se responde con el horario semanal
    escrito hace meses: a las 21:15 de un sabado, "abrimos de 9 a 14" no dice si
    puedes ir.
    """
    from datetime import datetime

    from backend import agenda, timeutils

    config = clients._get_client_config(cliente_id)
    zona = str((config.get("booking") or {}).get("timezone") or settings.DEFAULT_TIMEZONE)
    try:
        from zoneinfo import ZoneInfo

        ahora = datetime.now(ZoneInfo(zona))
    except Exception:  # noqa: BLE001
        ahora = timeutils._utc_now()

    try:
        matriz = agenda._weekly_schedule_matrix(cliente_id, config)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[agente] sin horario (%s): %s", cliente_id, exc)
        return {"ok": False, "error": "No he podido consultar el horario."}

    dias = []
    for fila in matriz or []:
        if not isinstance(fila, dict):
            continue
        dias.append({
            "dia": _DIAS[int(fila.get("weekday", 0))],
            "cerrado": bool(fila.get("closed")),
            # La matriz las llama start/end, no open/close: leerlas mal dejaba el
            # horario vacio y el modelo lo rellenaba de memoria.
            "abre": fila.get("start") or "",
            "cierra": fila.get("end") or "",
        })

    hoy = next((d for d in dias if d["dia"] == _DIAS[ahora.weekday()]), None)
    abierto_ahora = False
    if hoy and not hoy["cerrado"] and hoy["abre"] and hoy["cierra"]:
        abierto_ahora = hoy["abre"] <= ahora.strftime("%H:%M") < hoy["cierra"]
    return {
        "ok": True,
        "ahora": ahora.strftime("%H:%M"),
        "hoy": hoy or {},
        "abierto_ahora": abierto_ahora,
        "semana": dias,
    }


def _tool_politica_del_negocio(cliente_id: str, argumentos: Dict[str, Any]) -> Dict[str, Any]:
    """Lo que ESTE negocio ha decidido sobre un tema, con sus propias palabras.

    Es la pieza que hace que el asistente sirva para cualquier negocio: las normas
    (no dar precios sin ver el pelo, pedir foto, la fianza...) son DATOS del tenant,
    no codigo. Otro negocio pone las suyas y el asistente se comporta distinto sin
    tocar una linea.
    """
    from backend import rag, rules

    tema = str(argumentos.get("tema") or "").strip()
    if not tema:
        return {"ok": False, "error": "Dime sobre que tema."}

    respuestas = []
    # 1. Lo que ha escrito palabra por palabra.
    literal = rag._match_qa_answer(cliente_id, tema)
    if literal:
        respuestas.append({"fuente": "respuesta escrita por el negocio", "texto": literal})
    else:
        palabras = {p for p in catalog_pick._norm(tema).split() if len(p) > 3}
        try:
            for fila in rag._list_qa_rows(cliente_id)[:60]:
                pregunta = str(fila["question"] if "question" in fila.keys() else "")
                if palabras & set(catalog_pick._norm(pregunta).split()):
                    respuestas.append({
                        "fuente": "respuesta escrita por el negocio",
                        "pregunta": pregunta,
                        "texto": str(fila["answer"] if "answer" in fila.keys() else ""),
                    })
                if len(respuestas) >= 3:
                    break
        except Exception:  # noqa: BLE001
            pass

    # 2. Sus reglas activas ("cuando pidan X, haz Y").
    try:
        for regla in rules.listar(cliente_id, solo_activas=True)[:12]:
            texto_regla = catalog_pick._norm(regla["nombre"] + " " + (regla["texto"] or ""))
            if {p for p in catalog_pick._norm(tema).split() if len(p) > 3} & set(texto_regla.split()):
                respuestas.append({
                    "fuente": "regla del negocio",
                    "cuando": regla["intenciones"],
                    "texto": regla["texto"],
                })
    except Exception:  # noqa: BLE001
        pass

    if not respuestas:
        return {
            "ok": True, "hay_politica": False,
            "aviso": ("El negocio no tiene nada escrito sobre eso. No te inventes una "
                      "politica: dilo y ofrece preguntarlo o dar el telefono."),
        }
    return {"ok": True, "hay_politica": True, "politicas": respuestas[:4]}


def _valoracion_en_lugar_del_tratamiento(
    cliente_id: str, servicio: str, *, location_id: str = "",
) -> Dict[str, Any]:
    """La cita de valoracion que se ofrece a quien pide PRESUPUESTO.

    OJO: esto NO se aplica al reservar. Se hizo, y estaba mal leida la regla del
    salon: "para coger unas mechas la cita hay que cogersela directamente
    preguntandole como tiene el pelo de largo; lo del diagnostico es simplemente
    para las clientas que pidan presupuesto". Quien viene a reservar se lleva su
    cita de mechas; quien pregunta el precio se lleva la valoracion, y de eso se
    encargan las reglas de negocio del propio salon.
    """
    from backend import booking

    familias = booking._familias_que_exigen_valoracion(cliente_id)
    if not familias or not booking._exige_valoracion(servicio, familias):
        return {}
    valoracion = booking._servicio_de_valoracion(cliente_id, location_id=location_id)
    nombre = str((valoracion or {}).get("nombre") or "").strip()
    if not nombre:
        return {}
    detalle = _detalle_servicio(cliente_id, nombre)
    # Con el nombre CRUDO se le colaba la palabra "pack" a la clienta ("el servicio
    # que mencionas es el Pack cambio de color y mechas..."). El salon lo pidio
    # expreso: "no digas que es un pack, es como si fuese el servicio". La etiqueta
    # es de su catalogo interno, no algo que la clienta tenga que entender.
    hablado = textnorm.nombre_de_servicio_publico(servicio)
    return {
        "ok": True,
        "servicio": textnorm.nombre_de_servicio_publico(nombre),
        "servicio_en_agenda": nombre,
        "en_lugar_de": hablado,
        "motivo": ("De %s no se da precio ni se coge cita sin ver antes a la "
                   "clienta. La cita que se reserva es la de valoracion." % hablado),
        "nota": ("Explicaselo con naturalidad: le vas a coger la cita de valoracion, "
                 "que es corta y sin compromiso, y ahi le dicen el precio. NUNCA le "
                 "des una cifra de %s." % hablado),
        **detalle,
    }


def _tool_buscar_servicio(
    cliente_id: str, argumentos: Dict[str, Any], *, location_id: str = "",
) -> Dict[str, Any]:
    """El catalogo real, filtrado con lo que ha dicho. Nunca inventa un nombre."""
    from backend import intents

    descripcion = str(argumentos.get("descripcion") or "").strip()
    if not descripcion:
        return {"ok": False, "error": "Dime que te quieres hacer."}

    datos = intents.extraer_datos_servicio(cliente_id, descripcion) or {
        "familia": "", "tecnica": "", "talla": catalog_pick.talla_de(descripcion),
        "para_quien": "", "edad": None, "texto": descripcion,
    }
    eleccion = catalog_pick.elegir(cliente_id, datos, location_id=location_id)
    if eleccion.servicio:
        detalle = _detalle_servicio(cliente_id, eleccion.servicio)
        return {
            "ok": True,
            # El nombre para HABLAR va sin "Pack": la clienta pide unas mechas, no
            # un paquete. El de la agenda se mantiene aparte para crear la cita.
            "servicio": textnorm.nombre_de_servicio_publico(eleccion.servicio),
            "servicio_en_agenda": eleccion.servicio,
            **detalle,
        }
    if eleccion.falta in ("tecnica", "talla", "para_quien"):
        # Con DURACION de cada candidato: a "¿cuanto tiempo tengo que estar ahi?"
        # se le puede contestar el abanico ("de 45 a 75 minutos segun el largo") sin
        # obligarla a concretar. Sin este dato el agente preguntaba dos veces.
        detalle = []
        for nombre in eleccion.candidatos[:12]:
            datos_servicio = _detalle_servicio(cliente_id, nombre)
            minutos = datos_servicio.get("duracion_minutos") or 0
            detalle.append({
                "servicio": textnorm.nombre_de_servicio_publico(nombre),
                "duracion_minutos": minutos,
            })
        # Los nombres que se le ofrecen, y nada mas. "Mechas o balayage" son dos
        # cosas para quien elige, aunque el catalogo las tenga en un servicio.
        nombres = []
        for opcion in eleccion.opciones[:4]:
            for parte in catalog_pick.separar_alternativas(opcion):
                if parte not in nombres:
                    nombres.append(parte)

        return {
            "ok": True,
            "servicio": "",
            "falta": eleccion.falta,
            "preguntale_por": catalog_pick.sobre_que_preguntar(eleccion),
            "opciones": nombres,
            "candidatos": detalle,
            "total_candidatos": len(eleccion.candidatos),
            "sugerencia": catalog_pick.pregunta_para(eleccion),
            # Dos cosas que se hacian mal y le costaban la cita al negocio: recitarle
            # media lista del catalogo en vez de preguntar lo que la separa, y
            # rematar con "no hay mas opciones" teniendo nueve.
            "nota": (
                "PREGUNTALE POR %s con tus palabras, como lo haria una peluquera. NO "
                "le sueltes una lista con lo que incluye cada opcion: nombralas "
                "en UNA FRASE natural ('¿te gustaria hacerte mechas, balayage, grey "
                "blending o un cambio de color con mechas?') y ya esta. NO cuentes "
                "que lleva cada una: el negocio no lo quiere. Hay %d servicios "
                "que encajan, asi que NUNCA digas que no hay mas opciones. Y si solo "
                "pregunta cuanto dura o cuanto cuesta, contestale con estos datos sin "
                "obligarla a concretar."
                % ((catalog_pick.sobre_que_preguntar(eleccion) or "lo que falta").upper(),
                   len(eleccion.candidatos))
            ),
        }
    return {
        "ok": False,
        "error": "En este catalogo no hay nada que encaje con eso.",
        "servicios_parecidos": _parecidos(cliente_id, descripcion),
    }


_HORA_SUELTA = re.compile(r"\b(\d{1,2})(?:[:.h](\d{2}))?\b")


def _horas_que_ha_dicho(dicho: str) -> set:
    """Las horas que ha nombrado ella, en HH:MM. "a las 11" -> {"11:00"}."""
    horas = set()
    for cruda, minutos in _HORA_SUELTA.findall(catalog_pick._norm(dicho or "")):
        try:
            h = int(cruda)
        except ValueError:
            continue
        if not 0 <= h <= 23:
            continue
        horas.add("%02d:%s" % (h, minutos or "00"))
        if h <= 12:  # "a las 5" en una peluqueria son las cinco de la tarde
            horas.add("%02d:%s" % (h + 12, minutos or "00"))
    return horas


def _horas_ya_ofrecidas(historial: List[Dict[str, str]]) -> set:
    """Las horas que el ASISTENTE le ha ofrecido en esta conversacion.

    Elegir una de las que le acaban de ofrecer es lo mas normal del mundo -"vale,
    la primera que me has dicho"- y el freno de las horas inventadas la rechazaba
    porque no estaba en el estado: la cita no se movia y el asistente contestaba
    "no puedo moverla a la hora que te he ofrecido", que no hay por donde cogerlo.
    """
    horas = set()
    for mensaje in (historial or [])[-6:]:
        if mensaje.get("role") == "assistant":
            horas |= _horas_que_ha_dicho(str(mensaje.get("content") or ""))
    return horas


def _hora_que_nadie_ha_pedido(estado: Any, dicho: str, hora: str) -> bool:
    """¿Se esta moviendo la cita a una hora que ni ha pedido ni se le ha ofrecido?

    Paso de verdad: con la cita intacta, a "vuelvela a abrir" el modelo movio la
    cita de las 10:00 a las 11:00. Nadie hablo de las once. Mover la cita de
    alguien a un hueco que se ha sacado de la manga es de las cosas que mas caras
    salen, porque el cliente se presenta a su hora.
    """
    limpia = str(hora or "").strip()
    if not limpia:
        return False
    if limpia in _horas_que_ha_dicho(dicho):
        return False
    ofrecidos = set()
    for hueco in (getattr(estado, "huecos", None) or []):
        if isinstance(hueco, str):
            ofrecidos.add(hueco.strip())
        elif isinstance(hueco, dict):
            ofrecidos.add(str(hueco.get("hora") or hueco.get("time") or "").strip())
    return limpia not in ofrecidos


def _pide_anular_y_solo_eso(dicho: str) -> bool:
    """Delega en `reserva`: una sola forma de leer lo que pide."""
    from backend import reserva

    return reserva.pide_anular_y_solo_eso(dicho)


# Claves cuyo valor es un NOMBRE DE SERVICIO y acaba en boca del asistente.
# "servicio_en_agenda" queda fuera a proposito: ese es el nombre exacto con el que
# se crea la cita.
_CLAVES_DE_SERVICIO = ("servicio", "servicios", "nombre", "name", "opciones",
                       "candidatos", "servicios_parecidos", "en_lugar_de")

# Datos internos que el modelo no necesita y de los que copiaba la palabra "pack".
# El codigo SI los conserva: viajan en el resultado, solo se ocultan al hablar.
_NO_SE_LE_ENSENYAN = ("servicio_en_agenda", "categoria", "slug", "service_slug")


def _sin_la_palabra_pack(dato: Any) -> Any:
    """Lo que el modelo lee de una tool, con los nombres tal y como se dicen.

    Sanear tool por tool no funciono: se tapo en `buscar_servicio` y siguio
    saliendo por `consultar_disponibilidad` ("vamos a reservarte el pack de mechas
    o balayage largo"). El salon lo pidio expreso -"no digas que es un pack, es
    como si fuese el servicio"-, asi que se limpia en el UNICO sitio por el que
    pasa todo: justo antes de ponerselo delante.

    La agenda no cambia: el nombre exacto viaja aparte y el catalogo sabe volver
    de uno a otro (`_find_service_by_name`).
    """
    if isinstance(dato, dict):
        salida = {}
        for clave, valor in dato.items():
            if clave in _NO_SE_LE_ENSENYAN:
                # El nombre exacto del catalogo y su categoria son de cocina. Se lo
                # estaba copiando literal: "vamos a reservarte el Pack mechas o
                # balayage largo", con la palabra que el salon no quiere oir.
                continue
            if clave in _CLAVES_DE_SERVICIO:
                salida[clave] = _sin_la_palabra_pack(valor)
            else:
                salida[clave] = _sin_la_palabra_pack(valor) if isinstance(
                    valor, (dict, list)) else valor
        return salida
    if isinstance(dato, list):
        return [_sin_la_palabra_pack(x) for x in dato]
    if isinstance(dato, str):
        return textnorm.nombre_de_servicio_publico(dato)
    return dato
def _detalle_servicio(cliente_id: str, nombre: str) -> Dict[str, Any]:
    from backend import agenda

    for servicio in agenda._catalog_services(cliente_id):
        if not isinstance(servicio, dict):
            continue
        if str(servicio.get("nombre") or servicio.get("name") or "") == nombre:
            return {
                "duracion_minutos": int(servicio.get("duration_minutes") or 0),
                "categoria": str(servicio.get("category") or ""),
            }
    return {}


def _parecidos(cliente_id: str, descripcion: str, limite: int = 4) -> List[str]:
    """Que SI tiene el negocio, para no cerrarle la puerta a la clienta."""
    from backend import agenda

    palabras = {p for p in catalog_pick._norm(descripcion).split() if len(p) > 3}
    salida = []
    for servicio in agenda._catalog_services(cliente_id):
        if not isinstance(servicio, dict):
            continue
        nombre = str(servicio.get("nombre") or servicio.get("name") or "")
        if palabras & set(catalog_pick._norm(nombre).split()):
            # Se los va a leer a la clienta, asi que van sin "Pack".
            salida.append(textnorm.nombre_de_servicio_publico(nombre))
        if len(salida) >= limite:
            break
    return salida


# ─── El prompt: objetivos, no guion ────────────────────────────────────────

_DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")


def _calendario(cliente_id: str, config: Dict[str, Any], desde, dias: int = 14) -> str:
    """Los proximos dias con su fecha y si se abre. Para que no calcule: lea.

    Se marca el dia cerrado para que tampoco ofrezca un lunes en un salon que
    libra los lunes.
    """
    from datetime import timedelta

    from backend import agenda

    try:
        matriz = agenda._weekly_schedule_matrix(cliente_id, config)
    except Exception:  # noqa: BLE001
        matriz = []
    cerrados = set()
    for fila in matriz or []:
        if isinstance(fila, dict) and fila.get("closed"):
            try:
                cerrados.add(int(fila.get("weekday")))
            except (TypeError, ValueError):
                continue

    lineas = []
    for salto in range(dias):
        dia = desde + timedelta(days=salto)
        etiqueta = "%s %d de %s (%s)" % (
            _DIAS[dia.weekday()], dia.day, _MESES[dia.month - 1], dia.isoformat(),
        )
        if salto == 0:
            etiqueta += " — HOY"
        elif salto == 1:
            etiqueta += " — mañana"
        if dia.weekday() in cerrados:
            etiqueta += " — CERRADO"
        lineas.append("- " + etiqueta)
    return "\n".join(lineas)


_PIDE_CONTACTO = (
    "tu numero de telefono", "tu numero de movil", "tu telefono", "me lo puedes dar",
    "necesito tu numero", "dame tu numero", "facilitame tu numero", "tu movil",
    "tu correo", "tu email", "tu e-mail", "necesito tu correo",
)


_FECHAS = re.compile(
    r"\b(lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo)\b",
    re.IGNORECASE,
)


# Formas de decir "el dia me da igual". Faltando "el primer hueco que tengas", el
# guardarraíl de abajo le impedia ofrecer horas a quien ya habia dicho que le
# valia cualquiera, y la reserva no salia nunca.
_CUANDO_LO_DICE_ELLA = (
    "hoy", "manana", "pasado manana", "esta semana", "semana que viene",
    "proxima semana", "cuanto antes", "lo antes posible", "cualquier dia",
    "el que sea", "me da igual", "urgente", "ya mismo", "fin de semana",
    "primer hueco", "primera hora", "lo primero que tengas", "cuando puedas",
    "el hueco que sea", "me vale cualquiera", "lo mas pronto",
    # Sin encerrarse en frases exactas: "cualquier OTRO hueco que tengas me vale"
    # no casaba con "cualquier hueco" y volvia a preguntarle el dia.
    "que tengas", "que tenga", "me vale", "cualquier",
)
_HORAS = re.compile(r"\d{1,2}[:.]\d{2}")


_LA_DA_POR_HECHA = (
    "esta reservad", "queda reservad", "ya esta reservad", "esta confirmad",
    "queda confirmad", "esta agendad", "queda agendad", "esta apuntad",
    "queda apuntad", "te he apuntad", "te he reservad", "te la he reservad",
    "te he agendad", "ya tienes la cita", "ya tienes cita", "cita confirmada",
    "he reservado", "he agendado", "he apuntado",
)
_NIEGA = ("aun no", "todavia no", "no esta", "no queda", "no la he", "no te he")


def _da_la_cita_por_hecha(texto: str) -> bool:
    """¿Esta diciendo que la cita existe?

    Ojo con las negaciones: "aun no esta reservada" es justo la respuesta
    CORRECTA, y contiene la misma frase.
    """
    plano = catalog_pick._norm(texto or "")
    for pista in _LA_DA_POR_HECHA:
        desde = 0
        while True:
            donde = plano.find(pista, desde)
            if donde < 0:
                break
            antes = plano[max(0, donde - 30):donde]
            if not any(negacion in antes for negacion in _NIEGA):
                return True
            desde = donde + 1
    return False


# Decir que ACABAS de hacer algo en la agenda. Distinto de decir que la cita
# existe: "tienes cita el martes" puede ser verdad porque se acaba de consultar;
# "te la he reabierto" solo es verdad si una tool lo ha hecho EN ESTE TURNO.
_ACABO_DE_HACERLO = (
    "te he apuntad", "te he reservad", "te la he reservad", "te he agendad",
    "he reservado", "he agendado", "he apuntado", "te la he cogid", "te he cogid",
    "he cancelado", "la he cancelado", "he anulado", "la he anulado",
    "he reprogramado", "la he reprogramado", "he movido", "la he movido",
    "he cambiado tu cita", "he cambiado la cita",
    # Reabrir una cita cancelada NO existe como operacion, asi que decirlo es
    # SIEMPRE mentira. Paso de verdad: "vuelvela a abrir" -> "tu cita esta de
    # nuevo abierta", y en la agenda no habia nada.
    "he vuelto a abrir", "la he reabierto", "he reabierto", "he reactivado",
    "la he reactivado", "de nuevo abierta", "de nuevo activa", "vuelve a estar activa",
    "queda reabierta", "esta reabierta", "restaurad",
)


def _dice_que_acaba_de_hacerlo(texto: str) -> bool:
    """¿Afirma haber tocado la agenda ahora mismo?"""
    plano = catalog_pick._norm(texto or "")
    for pista in _ACABO_DE_HACERLO:
        desde = 0
        while True:
            donde = plano.find(pista, desde)
            if donde < 0:
                break
            antes = plano[max(0, donde - 30):donde]
            if not any(negacion in antes for negacion in _NIEGA):
                return True
            desde = donde + 1
    return False

_CODIGO = re.compile(r"R-?\s?\d{3,}", re.IGNORECASE)
_GESTIONA = ("cancelar", "anular", "cambiar mi cita", "cambiar la cita", "mover",
             "reprogramar", "aplazar", "mi cita", "la cita que tengo")


_PREGUNTA_EL_DIA = (
    "que dia", "para que dia", "cuando te", "que fecha", "que dia te",
    "para cuando", "algun dia en concreto", "tienes algun dia",
)
# Preguntarle la HORA a quien ha dicho "el primer hueco que tengas" es repreguntar
# lo que ya ha contestado. Se quedaba dando vueltas -"¿a las 10:00, 10:15 o
# 10:30?"- turno tras turno, y la cita no se creaba nunca.
_PREGUNTA_LA_HORA = (
    "que hora", "a que hora", "cual prefieres", "cual te viene", "prefieres las",
    "te gustaria la cita a las", "confirmar el horario",
)


_ACEPTA = (
    "vale", "si", "perfecto", "genial", "de acuerdo", "me viene bien", "esa misma",
    "esa hora", "la primera", "la segunda", "la ultima", "confirmo", "adelante",
    "esa me vale", "me vale", "ok", "okey", "venga",
)


_UNA_CIFRA_DE_DINERO = re.compile(
    r"(\d{1,4}\s*(?:€|eur|euros)|(?:€|eur|euros)\s*\d{1,4}|entre\s+\d{1,4}\s+y\s+\d{1,4})",
    re.IGNORECASE,
)


_DICE_QUE_CIERRAN = ("estamos cerrados", "estamos cerrado", "cerramos ese dia",
                     "ese dia cerramos", "no abrimos", "no abrimos ese dia",
                     "manana estamos cerrados", "ese dia esta cerrado")


def _dice_que_cierran(texto: str) -> bool:
    plano = catalog_pick._norm(texto or "")
    return any(pista in plano for pista in _DICE_QUE_CIERRAN)


# Anunciar en vez de hacer. Paso de verdad: "vamos a ver las horas disponibles
# para el viernes. Un momento, por favor" -y ahi se quedaba-. La clienta espera un
# mensaje que no llega nunca y se va.
_LO_ANUNCIA = (
    "un momento", "un segundo", "dame un minuto", "enseguida te", "ahora te digo",
    "ahora mismo lo miro", "voy a mirar", "voy a comprobar", "voy a consultar",
    "voy a revisar", "dejame ver", "permiteme", "te confirmo en", "ya te digo",
    "espera un", "en breve te",
)


def _lo_anuncia_en_vez_de_hacerlo(texto: str) -> bool:
    plano = catalog_pick._norm(texto or "")
    return any(pista in plano for pista in _LO_ANUNCIA)


def _da_un_precio_prohibido(cliente_id: str, texto: str, contexto: str) -> bool:
    """¿Ha soltado una cifra de algo cuyo precio este negocio no da por mensaje?

    Quitarle el precio del prompt no basta: aguanta seis negativas y a la septima
    se lo INVENTA ("el rango de precios generalmente..."). Y un precio inventado es
    peor que uno real. Esto no juzga como redacta: comprueba un hecho -el negocio
    tiene una regla para esa familia y el ha escrito una cifra-.
    """
    if not _UNA_CIFRA_DE_DINERO.search(texto or ""):
        return False
    from backend import booking

    # El negocio que no da precios por mensaje no da NINGUNO: cualquier cifra que
    # escriba esta de mas, hable de lo que hable.
    if booking.precios_ocultos(cliente_id):
        return True
    familias = booking._familias_que_exigen_valoracion(cliente_id)
    if not familias:
        return False
    hablando_de = catalog_pick._norm((texto or "") + " " + (contexto or ""))
    return any(familia and familia in hablando_de for familia in familias)


PREGUNTA_EL_PRECIO = ("precio", "precios", "cuanto cuesta", "cuanto vale",
                      "cuanto me costaria", "cuanto seria", "tarifa", "tarifas",
                      "presupuesto", "cuanto sale", "que vale", "coste")
# Como INSISTE quien ya se ha llevado una negativa. Sin esto el segundo aviso -el
# que manda cerrar- no llegaba a saltar nunca: la clienta no repite la palabra
# "precio", dice "ya pero dime un aproximado".
INSISTE_CON_EL_PRECIO = ("aproximad", "mas o menos", "una idea", "un rango",
                         "orientativ", "por encima", "dime algo", "aunque sea",
                         "caro", "barato", "me sale por", "cuanto me va a")


def _pregunta_el_precio(dicho: str, ya_negado: bool = False) -> bool:
    plano = catalog_pick._norm(dicho or "")
    if any(pista in plano for pista in PREGUNTA_EL_PRECIO):
        return True
    return ya_negado and any(pista in plano for pista in INSISTE_CON_EL_PRECIO)


def _salida_para_quien_pregunta_el_precio(cliente_id: str, estado: Any, mensaje: str) -> str:
    """Que hacer cuando pregunta el precio y este negocio no los da.

    Negarse no basta: medido en 100 conversaciones, las de precio eran las PEORES
    -6 de 17 acababan bien- y no por callarse la cifra, sino porque el asistente
    repetia la negativa con otras palabras hasta que la clienta se cansaba y se
    iba. La segunda vez hay que CERRAR: o le coge el diagnostico, o le da el
    telefono. Lo que no puede es volver a explicarlo.
    """
    from backend import booking, clients

    ya_negado = bool(getattr(estado, "veces_sin_precio", 0))
    if (not _pregunta_el_precio(mensaje, ya_negado)
            or not booking.precios_ocultos(cliente_id)):
        return ""
    estado.veces_sin_precio += 1
    telefono = str((clients._get_client_config(cliente_id).get("contacto") or {})
                   .get("telefono") or "").strip()
    si_llama = (" Si prefiere saberlo antes de venir, que llame al %s." % telefono
                if telefono else "")
    if estado.veces_sin_precio == 1:
        return (
            "AQUI NO SE DAN PRECIOS. Diselo en UNA frase, sin rodeos y sin cifras, y "
            "en el mismo mensaje ofrecele la salida: cogerle una cita de valoracion "
            "(corta y sin compromiso, ahi le dan el presupuesto).%s No te quedes en "
            "la explicacion: termina proponiendo algo concreto." % si_llama
        )
    return (
        "YA se lo has explicado %d veces y sigue preguntando. NO se lo vuelvas a "
        "explicar ni repitas la misma frase: CIERRA. Mira la agenda de verdad y "
        "ofrecele dos o tres horas concretas para la valoracion, y si aun asi no le "
        "vale, dale el telefono para que llamen.%s"
        % (estado.veces_sin_precio - 1, si_llama)
    )


_ENTRECOMILLADO = re.compile(r'["\u201c\u201d\u00ab\u00bb]([^"\u201c\u201d\u00ab\u00bb]{3,60})["\u201c\u201d\u00ab\u00bb]')


def _sin_comillas_en_los_servicios(cliente_id: str, texto: str) -> str:
    """Los nombres de servicio se dicen, no se citan.

    Lo dijo el duenyo del negocio: 'que no ponga los servicios entre comillas, es
    muy poco natural'. Y tiene razon: una peluquera no dice te hago unas "Mechas o
    balayage largo", dice te hago unas mechas.

    Solo se quitan las comillas de lo que ES un servicio del catalogo: si estan
    citando otra cosa -el nombre de un producto, algo que dijo la clienta- se
    quedan.
    """
    if not texto or '"' not in texto and "\u201c" not in texto and "\u00ab" not in texto:
        return texto
    from backend import agenda

    try:
        catalogo = set()
        for s in agenda._catalog_services(cliente_id):
            if not isinstance(s, dict):
                continue
            crudo = str(s.get("nombre") or s.get("name") or "")
            # Los dos nombres: el que se dice y el interno. Si se le escapa el
            # interno, tampoco tiene que ir entre comillas.
            catalogo.add(catalog_pick._norm(crudo))
            catalogo.add(catalog_pick._norm(textnorm.nombre_de_servicio_publico(crudo)))
    except Exception:  # noqa: BLE001 - nunca romper la respuesta por esto
        return texto
    catalogo.discard("")

    def _quitar(encontrado):
        dentro = catalog_pick._norm(encontrado.group(1))
        if not dentro:
            return encontrado.group(0)
        # Vale el nombre entero y tambien como se le ofrece sin la talla ("Mechas
        # o balayage" de "Mechas o balayage largo"): es lo que mas cita.
        if dentro in catalogo or any(n.startswith(dentro) for n in catalogo):
            return encontrado.group(1)
        return encontrado.group(0)

    return _ENTRECOMILLADO.sub(_quitar, texto)


def _modelo_del_negocio(config: Dict[str, Any]) -> str:
    """El modelo que el negocio ha elegido en su panel, o el de la casa.

    Estaba en su config, validado y guardado desde la pestanya del asistente...
    y no lo leia NADIE: el agente -que hoy es el cerebro del chat y de WhatsApp-
    llamaba siempre al modelo por defecto. Quien pagaba por uno mejor no lo tenia.
    """
    elegido = str((config or {}).get("chat_model") or "").strip()
    if elegido and elegido in settings.AVAILABLE_CHAT_MODELS_BOOT:
        return elegido
    return settings.DEFAULT_CHAT_MODEL


def _temperatura_del_negocio(config: Dict[str, Any]) -> float:
    """Lo mismo con la temperatura: si la ha tocado, se respeta."""
    try:
        valor = float((config or {}).get("temperature", 0.3))
    except (TypeError, ValueError):
        return 0.3
    return max(0.0, min(1.5, valor))


def _quien_escribe(cliente_id: str, telefono: str) -> Dict[str, str]:
    """Lo que YA se sabe de quien escribe, sin preguntarle nada.

    Por WhatsApp el numero viene verificado por el canal, y si ya ha reservado
    antes tambien se sabe como se llama. Pedirselo otra vez es tratar como
    desconocida a una clienta de siempre; y pedir el telefono POR WHATSAPP es
    directamente absurdo: el asistente se quedaba en bucle pidiendolo y la cita no
    llegaba a crearse nunca.
    """
    datos = {"telefono": str(telefono or "").strip(), "nombre": ""}
    if not datos["telefono"]:
        return datos
    try:
        from backend import crm

        contacto = crm.contact_by_phone(cliente_id, datos["telefono"])
    except Exception:  # noqa: BLE001
        contacto = None
    if contacto is not None:
        nombre = str(contacto["name"] if "name" in contacto.keys() else "").strip()
        if _nombre_de_verdad(nombre):
            datos["nombre"] = nombre
    return datos


def _instrucciones(cliente_id: str, config: Dict[str, Any], hoy,
                   quien: Optional[Dict[str, str]] = None) -> str:
    from backend import booking

    empresa = str(config.get("empresa") or config.get("nombre") or "el salon").strip()
    catalogo, completo = booking._service_catalog_prompt_block(cliente_id)
    tono = textnorm._tono_prompt_block(config)
    telefono = str((config.get("contacto") or {}).get("telefono") or "").strip()

    partes = [
        "Eres quien coge las citas en %s. Hablas por WhatsApp con una clienta." % empresa,
        "Hoy es %s %d de %s (%s)." % (
            _DIAS[hoy.weekday()], hoy.day, _MESES[hoy.month - 1], hoy.isoformat(),
        ),
        "",
        "LOS PROXIMOS DIAS (usalos TAL CUAL: no calcules fechas de cabeza):",
        _calendario(cliente_id, config, hoy),
        "",
        "TU OBJETIVO: que salga de la conversacion con su cita cogida, sintiendose",
        "bien atendida. Guiala tu: pregunta lo que falte, recomienda con criterio y",
        "explicale lo que le vas a hacer. No eres un formulario.",
        "",
        "COMO COGES UNA CITA:",
        "- Para crear la cita necesitas CUATRO cosas: servicio, fecha, hora y su nombre.",
        "  Ve consiguiendolas conversando, de una en una y sin agobiar.",
        "- Su telefono YA lo tienes (te escribe por WhatsApp): no se lo pidas NUNCA.",
        "  El email tampoco hace falta para reservar.",
        "- El servicio SIEMPRE lo confirmas con la tool `buscar_servicio`. Si te dice",
        "  que falta la tecnica o el largo, preguntaselo con tus palabras.",
        "- Las horas SIEMPRE salen de `consultar_disponibilidad`. Ofrece dos o tres,",
        "  repartidas, no una lista larga.",
        "- Las fechas SIEMPRE salen de la lista de dias de arriba. Si dice \"el jueves\",",
        "  busca el jueves en esa lista y usa su fecha exacta. Nunca la calcules tu.",
        "- No ofrezcas un dia marcado CERRADO.",
        "- La cita solo existe cuando `crear_cita` te devuelve el numero de reserva.",
        "  NUNCA digas que esta reservada, apuntada o confirmada antes de eso.",
        "",
        "LO QUE NO PUEDES HACER:",
        "- Inventarte un servicio, un precio, una duracion o un hueco.",
        "- Dar por hecha una cita que no ha creado `crear_cita`.",
        "- Insistir con un servicio que no tienen: dilo y ofrece lo que si haya.",
    ]
    if telefono:
        partes.append(
            "- Si no encuentras hueco que le encaje, si te dice que NINGUNA opcion le "
            "va bien, o si la conversacion se complica, ofrecele llamar al %s: en el "
            "salon pueden mirar la agenda a mano y cuadrar lo que el sistema no puede. "
            "No lo ofrezcas a la primera de cambio, solo cuando la cita se pueda "
            "perder." % telefono
        )
    # DONDE ESTA EL NEGOCIO. Sin esto el modelo se lo inventaba: a "¿donde estais
    # ubicados?" contesto "en el centro de la ciudad, en una zona muy accesible",
    # que no lo dice ningun dato suyo. Un cliente que se fia de eso no llega.
    contacto = config.get("contacto") or {}
    direccion = textnorm._sanitize_text(str(contacto.get("direccion") or "")).strip()
    mapa = textnorm._sanitize_text(str(contacto.get("mapa") or "")).strip()
    if direccion or mapa:
        donde = ["", "DONDE ESTAIS (dilo TAL CUAL, no lo adornes):"]
        if direccion:
            donde.append("- Direccion: %s" % direccion)
        if mapa:
            donde.append("- Como llegar: %s" % mapa)
        partes += donde
    else:
        partes.append(
            "- NO tienes la direccion del negocio: si te preguntan donde estais, "
            "dilo y dales el telefono. No te inventes una zona ni una calle."
        )
    if (quien or {}).get("nombre"):
        partes += [
            "",
            "YA HA ESTADO AQUI: se llama %s. Saludala por su nombre y NO se lo "
            "preguntes otra vez." % quien["nombre"],
        ]
    if catalogo:
        partes += ["", "SU CATALOGO%s:" % ("" if completo else " (recortado)"), catalogo]
    if tono:
        partes += ["", tono]
    return "\n".join(partes)


def _ya_dijo_esto(historial: List[Dict[str, str]], texto: str) -> bool:
    """¿Es esta respuesta la MISMA que la anterior, palabra por palabra?

    Medido en tres tiradas de 100 conversaciones: repetir la misma frase es el
    fallo mas frecuente con diferencia (33-35 de cada 100), y tres de cada cuatro
    veces pasa cuando el negocio tiene que decir que NO -no damos precios, no
    puedo aconsejarte sin verte, eso no lo hacemos-. La clienta insiste, y recibe
    el mismo parrafo copiado. Para quien escribe, eso es un muro.

    Se compara el principio de la frase, sin tildes ni mayusculas: lo que nota
    quien lee es que empieza igual.
    """
    limpio = catalog_pick._norm(texto or "")[:90]
    if len(limpio) < 25:
        return False   # "vale", "perfecto": repetirlos no molesta a nadie
    for mensaje in reversed(historial or []):
        if mensaje.get("role") != "assistant":
            continue
        return catalog_pick._norm(str(mensaje.get("content") or ""))[:90] == limpio
    return False


def _historial(session_id: str, cliente_id: str) -> List[Dict[str, str]]:
    """Las ultimas frases de ESTA conversacion, para que "y el jueves?" tenga sentido.

    En WhatsApp la conversacion es el numero de telefono: no se cierra nunca. Sin
    cortar por tiempo, lo hablado hace dias sigue contando, y paso: dias despues de
    preguntar por un corte, al saludar de nuevo y pulsar "Agendar cita" contesto
    "para el corte, ¿que tipo prefieres?" a alguien que no habia dicho nada.

    Se corta en el primer silencio largo hacia atras: una charla seguida se
    mantiene entera, y la de otro dia no se cuela.
    """
    try:
        with db._get_db_connection() as conexion:
            filas = conexion.execute(
                "SELECT role, content, created_at FROM chat_messages"
                " WHERE session_id = ? AND cliente_id = ?"
                " ORDER BY id DESC LIMIT ?",
                (session_id, cliente_id, MAX_HISTORIAL),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[agenda-agente] sin historial (%s): %s", cliente_id, exc)
        return []

    mensajes = []
    siguiente = None  # el mensaje posterior, yendo hacia atras
    for fila in filas:  # de mas reciente a mas antiguo
        momento = timeutils._from_utc_iso(str(fila["created_at"] or ""))
        if siguiente is not None and momento is not None:
            if (siguiente - momento).total_seconds() > SILENCIO_QUE_CIERRA:
                break  # a partir de aqui ya es otra conversacion
        if momento is not None:
            siguiente = momento
        contenido = str(fila["content"] or "").strip()
        if contenido:
            rol = "assistant" if str(fila["role"]) == "assistant" else "user"
            mensajes.append({"role": rol, "content": contenido[:1200]})
    return list(reversed(mensajes))


# ─── El turno ──────────────────────────────────────────────────────────────

# Palabras que significan que la respuesta depende de DATOS (que servicios hay,
# que huecos quedan): si aparecen, contestar de memoria es inventar.
_PIDE_DATOS = (
    "cita", "hueco", "reserv", "agenda", "dia", "hora", "lunes", "martes",
    "miercoles", "jueves", "viernes", "sabado", "domingo", "mañana", "manana",
    "semana", "corte", "mechas", "alisado", "color", "peinado", "recogido",
    "tratamiento", "maquillaje", "extension", "permanente", "depilacion",
    "cuanto dura", "cuanto tarda", "disponib",
)


def _necesita_consultar(mensaje: str) -> bool:
    """¿La respuesta a esto depende de datos que hay que mirar?"""
    limpio = catalog_pick._norm(mensaje)
    return any(palabra in limpio for palabra in _PIDE_DATOS)


# Preguntas por una NORMA del negocio: como preparar el pelo, la fianza, que pasa
# si cancela... Son cosas que el negocio ha escrito con sus palabras, y de memoria
# se contestan mal. Paso de verdad: a "¿hay algun protocolo?" antes de un alisado
# contesto "ven con el pelo limpio y seco y evita gel o spray", cuando el suyo dice
# tres lavados con champu y NADA despues -ni mascarilla, ni acondicionador, ni
# serum-. Una clienta que siga la version inventada se lleva un alisado peor.
_PREGUNTA_POR_UNA_NORMA = (
    "protocolo", "preparar", "preparacion", "como tengo que venir", "como vengo",
    "como voy", "antes de la cita", "antes de venir", "el dia antes", "me lavo",
    "lavarme", "lavado", "puedo venir con", "tengo que traer", "recomendacion previa",
    "fianza", "senyal", "deposito", "anticipo", "politica", "cancelacion",
    "cuidados", "despues del tratamiento", "mantenimiento", "retoque", "garantia",
)


def _nota_del_servicio(cliente_id: str, resultado: Dict[str, Any]) -> str:
    """Las indicaciones que el negocio quiere dar al reservar ESE servicio."""
    from backend import booking, db

    codigo = str(resultado.get("codigo_reserva") or "").strip()
    if not codigo:
        return ""
    try:
        with db._get_db_connection() as conexion:
            fila = conexion.execute(
                "SELECT * FROM bookings WHERE cliente_id = ? AND booking_code = ? LIMIT 1",
                (cliente_id, codigo),
            ).fetchone()
        return booking.service_booking_note(cliente_id, fila) if fila is not None else ""
    except Exception:  # noqa: BLE001 - nunca romper una reserva por esto
        return ""


def _pregunta_por_una_norma(mensaje: str) -> bool:
    limpio = catalog_pick._norm(mensaje)
    return any(pista in limpio for pista in _PREGUNTA_POR_UNA_NORMA)


# Lo que solo se puede decir habiendo mirado la agenda.
_HABLA_DE_AGENDA = (
    "cerrado", "cerramos", "no abrimos", "no tengo hueco", "no hay hueco",
    "no tengo disponib", "no hay disponib", "tengo libre", "puedo ofrecerte",
    "estas horas", "estos horarios",
    # Decir que una hora concreta esta pillada tambien es hablar de la agenda, y
    # se colaba: a "¿puede ser a las 10:30?" contesto "lo siento, a esa hora ya
    # tengo una cita" SIN mirar. Estaba libre para las cinco profesionales.
    "ya tengo una cita", "tengo una cita a esa", "esa hora esta ocupada",
    "esta ocupada", "esta cogida", "ya esta cogida", "no me queda",
    "no tengo ese hueco", "esa hora no la tengo", "no puedo a esa hora",
)


def _afirma_sobre_la_agenda(texto: str) -> bool:
    """¿Esta respuesta afirma algo de la agenda (que cierran, que no hay hueco)?"""
    limpio = catalog_pick._norm(texto)
    return any(frase in limpio for frase in _HABLA_DE_AGENDA)


# Como dice una clienta que ninguna opcion le sirve. El salon pidio que en ese
# momento -y solo en ese- se le ofrezca llamar, porque ellas pueden cuadrar a mano
# lo que el sistema no puede.
_RECHAZA_LAS_OPCIONES = (
    "no me va bien", "no me viene bien", "ninguna", "ningun hueco", "no puedo a esa",
    "no me encaja", "no me sirve", "imposible", "no puedo ir", "solo puedo",
)


def _rechaza_las_opciones(mensaje: str) -> bool:
    limpio = catalog_pick._norm(mensaje)
    return any(frase in limpio for frase in _RECHAZA_LAS_OPCIONES)


def _con_el_telefono_si_hace_falta(
    cliente_id: str, mensaje: str, respuesta: str, cita_creada: bool,
) -> str:
    """Añade el telefono cuando la clienta rechaza las opciones y no hay cita.

    Es una condicion del salon, asi que no puede quedar a lo que decida el modelo:
    "no me va bien ninguna" y despedirse sin ofrecer el telefono es perder la cita.
    """
    if cita_creada or not respuesta or not _rechaza_las_opciones(mensaje):
        return respuesta
    linea = clients.call_us_line(cliente_id)
    if not linea or catalog_pick._norm(linea)[:40] in catalog_pick._norm(respuesta):
        return respuesta
    return respuesta.rstrip() + linea


async def responder(
    cliente_id: str,
    mensaje: str,
    *,
    session_id: str,
    telefono: str,
    config: Optional[Dict[str, Any]] = None,
    location_id: str = "",
    intencion: str = "",
    remate_manual: bool = False,
) -> Tuple[str, bool]:
    """Contesta a la clienta llevando la conversacion de la cita.

    EL CODIGO DECIDE, EL MODELO HABLA. Antes habia doce detectores leyendo lo que
    el modelo escribia para corregirlo DESPUES, y dos de ellos llegaron a crear
    citas duplicadas. Ahora `backend/reserva.py` lleva el estado (que servicio,
    que dia, que hora, que cita), decide QUE falta y se lo dice ANTES de que
    hable. Solo quedan las comprobaciones que contrastan con DATOS, no con prosa.

    Devuelve (texto, cita_creada). Si devuelve texto vacio, quien llama debe tirar
    de su plan B (el flujo con listas): quedarse sin respuesta no es una opcion.
    """
    if not settings.OPENAI_API_KEY:
        return "", False
    cfg = config if config is not None else clients._get_client_config(cliente_id)

    from backend import reserva, timeutils

    try:
        from zoneinfo import ZoneInfo

        hoy = timeutils._utc_now().astimezone(
            ZoneInfo(str((cfg.get("booking") or {}).get("timezone") or settings.DEFAULT_TIMEZONE))
        ).date()
    except Exception:  # noqa: BLE001
        hoy = timeutils._utc_now().date()

    from backend import trazas

    # El cuaderno de bitacora del turno. Nunca puede tumbar la conversacion: todo
    # lo suyo esta envuelto, y si falla se registra y se sigue.
    traza = trazas.Traza(cliente_id, session_id, canal="whatsapp" if telefono else "chat")

    quien = _quien_escribe(cliente_id, telefono)
    historial = _historial(session_id, cliente_id)
    # Las que ya se le han ofrecido cuentan como pedidas: elegir de la lista que
    # acaba de darle el asistente es lo mas normal del mundo.
    ofrecidas = _horas_ya_ofrecidas(historial)

    dicho_de_ella = " ".join(
        [str(mensaje)] + [m.get("content", "") for m in historial if m.get("role") == "user"]
    )
    estado = reserva.cargar(cliente_id, telefono)
    reserva.anotar_intencion(estado, intencion)
    reserva.anotar_lo_que_dice(
        estado, mensaje,
        str((cfg.get("booking") or {}).get("timezone") or settings.DEFAULT_TIMEZONE),
        cliente_id=cliente_id,
    )
    conocido = quien.get("nombre", "")

    mensajes: List[Dict[str, Any]] = [
        {"role": "system", "content": _instrucciones(cliente_id, cfg, hoy, quien)},
    ]
    mensajes.extend(historial)
    mensajes.append({"role": "user", "content": str(mensaje)[:1200]})

    cita_creada = False
    consultada = False  # se ha mirado la agenda en este turno
    # OJO: `estado.hecho` dura toda la conversacion, asi que NO sirve para saber si
    # se acaba de tocar la agenda. Con el se colaron dos mentiras seguidas: cancelo
    # una cita y al pedirle "vuelvela a abrir" dijo que la habia reabierto (no
    # existe esa operacion), y en otra dijo "te he agendado" sin crear nada.
    mutada = False      # una tool ha cambiado la agenda en este turno
    mirada_la_cita = False  # se ha consultado su cita en este turno
    dias_mirados = 0
    ya_creadas: set = set()
    try:
        from openai import OpenAI as OpenAISdkClient

        cliente = OpenAISdkClient(api_key=settings.OPENAI_API_KEY, timeout=25.0)
        obligar = False
        sin_precio = ""
        catalogo_mirado = False
        norma_mirada = False
        dias_abiertos_vistos = False   # se ha consultado un dia que SI abre
        for vuelta in range(MAX_VUELTAS):
            # Lo que el codigo sabe y lo que toca hacer, delante del modelo en CADA
            # vuelta: asi no hay nada que corregirle despues.
            # El estado INFORMA (lo que ya sabe, para que no lo repregunte) pero
            # no DIRIGE: dictarle la frase le quitaba lo unico que hace bien
            # -adaptarse- y cuando el codigo se equivocaba, se equivocaba en bucle.
            # Medido: repetir la misma pregunta paso de 3 a 15 conversaciones de 40.
            # Se lo explica UNA vez. Repetirle parrafo y medio en cada mensaje
            # es lo que hacia y ademas le hacia perder el hilo: venia de ofrecerle
            # tres horas y volvia a preguntarle que dia queria.
            # Le da igual el dia y no hay huecos sobre la mesa: se BUSCA el
            # primero que tenga, en vez de contestar "no tengo huecos" habiendo
            # mirado uno solo. Se hace una vez por turno.
            if (estado.dia_le_da_igual and not estado.huecos and not estado.hora
                    and vuelta == 0 and estado.intencion in ("reservar", "reprogramar")):
                from backend import agenda

                try:
                    dia, libres = await agenda.primer_dia_con_hueco(
                        cliente_id, servicio=estado.servicio_exacto or estado.servicio,
                        location_id=location_id)
                except Exception as exc:  # noqa: BLE001
                    settings.logger.warning("[agente] sin primer hueco (%s): %s", cliente_id, exc)
                    dia, libres = "", []
                if dia:
                    estado.fecha_de_los_huecos = dia
                    estado.huecos = libres[:8]
                    consultada = True
                    if not estado.fecha:
                        estado.fecha = dia
                    if not estado.hora:
                        estado.hora = libres[0]

            aviso = ("" if estado.recargo_dicho
                     else _aviso_de_recargo(cliente_id, dicho_de_ella, estado.servicio))
            # Solo en la PRIMERA vuelta: si no, cada llamada a una tool contaria
            # como una negativa mas y se saltaria directo al cierre.
            sin_precio = (_salida_para_quien_pregunta_el_precio(cliente_id, estado, mensaje)
                          if vuelta == 0 else sin_precio)
            guia = [t for t in (reserva.resumen(estado, conocido), aviso, sin_precio,
                                reserva.instruccion_de_cierre(estado, conocido)) if t]
            turno = list(mensajes)
            if guia:
                turno.append({"role": "system", "content": "\n\n".join(guia)})

            # Con todos los datos en la mano, la herramienta que cierra la gestion
            # no se sugiere: se obliga. Pedirselo "con enfasis" seguia siendo
            # prompt, y el modelo se escaqueaba volviendo a consultar huecos.
            remate = reserva.tool_que_remata(estado, conocido)
            # Ha dicho que se quiere hacer, pero aun no hay servicio elegido: lo
            # primero es MIRAR EL CATALOGO con lo que ha dicho. Preguntarle de
            # nuevo sin haberlo mirado es como se repetia la misma pregunta turno
            # tras turno (26 conversaciones de 100).
            if (not remate and not estado.servicio and estado.servicio_texto
                    and not catalogo_mirado):
                remate = "buscar_servicio"
            # Pregunta por una norma del negocio: se mira lo que ESTE negocio ha
            # escrito, no lo que el modelo recuerde de otras peluquerias.
            if not remate and not norma_mirada and _pregunta_por_una_norma(mensaje):
                remate = "politica_del_negocio"
            # El canal puede querer que la cita la confirme la clienta con un
            # boton, no el modelo por su cuenta: un resumen con "¿Confirmamos?"
            # antes de tocar la agenda. Cancelar y reprogramar siguen igual.
            if remate == "crear_cita" and remate_manual:
                remate = ""
            if remate and not obligar:
                eleccion = {"type": "function", "function": {"name": remate}}
            elif obligar:
                eleccion = "required"
            else:
                eleccion = "auto"

            respuesta = cliente.chat.completions.create(
                model=_modelo_del_negocio(cfg),
                messages=turno,
                tools=_herramientas(),
                tool_choice=eleccion,
                temperature=_temperatura_del_negocio(cfg),
                max_tokens=400,
            )
            traza.vuelta()
            try:
                uso = getattr(respuesta, "usage", None)
                if uso is not None:
                    traza.modelo(_modelo_del_negocio(cfg),
                                 prompt=getattr(uso, "prompt_tokens", 0) or 0,
                                 salida=getattr(uso, "completion_tokens", 0) or 0)
            except Exception:  # noqa: BLE001 - una metrica no frena nada
                pass
            elegido = respuesta.choices[0].message
            if not getattr(elegido, "tool_calls", None):
                texto_final = (elegido.content or "").strip()
                # Las tres que quedan comprueban HECHOS, no como lo redacta.

                # 1) Contestar de memoria a algo que depende de datos es inventar.
                if vuelta == 0 and not obligar and _necesita_consultar(mensaje):
                    obligar = True
                    continue
                # 2) Afirmar algo de la agenda sin haberla mirado: "el jueves
                #    estamos cerrados" era falso.
                if (_afirma_sobre_la_agenda(texto_final) and not consultada
                        and vuelta + 1 < MAX_VUELTAS):
                    obligar = True
                    traza.freno("afirmo_sin_mirar_la_agenda")
                    mensajes.append({
                        "role": "system",
                        "content": ("Antes de decir nada sobre dias u horas, consulta "
                                    "`consultar_disponibilidad`. No afirmes que un dia "
                                    "esta cerrado ni que no hay hueco sin haberlo mirado."),
                    })
                    continue
                # 2ter) Lo anuncia y no lo hace: si va a mirar la agenda, que la
                #       mire en este mismo turno.
                if (_lo_anuncia_en_vez_de_hacerlo(texto_final) and not consultada
                        and vuelta + 1 < MAX_VUELTAS):
                    obligar = True
                    traza.freno("lo_anuncio_sin_hacerlo")
                    mensajes.append({
                        "role": "system",
                        "content": ("No anuncies que vas a mirarlo: MIRALO AHORA y "
                                    "contesta con el resultado. Nada de 'un momento' "
                                    "ni 'enseguida te digo': ella no recibe nada "
                                    "despues, se queda esperando y se va."),
                    })
                    continue
                # 2bis) "Estamos cerrados" cuando el negocio SI abre. Quedarse
                #       sin hueco no es cerrar, y para el cliente no es lo mismo:
                #       uno se va a otro sitio y el otro pregunta por otro dia.
                if (_dice_que_cierran(texto_final) and dias_abiertos_vistos
                        and vuelta + 1 < MAX_VUELTAS):
                    traza.freno("dijo_cerrado_estando_abierto")
                    mensajes.append({
                        "role": "system",
                        "content": ("Ese dia el negocio SI ABRE: lo has consultado y "
                                    "lo que pasa es que no queda hueco para ese "
                                    "servicio. No digas que estamos cerrados -es "
                                    "falso y suena a que no hay nada que hacer-: "
                                    "dile que ese dia lo tienes completo y ofrecele "
                                    "el siguiente con hueco."),
                    })
                    continue
                # 3) Un precio que el negocio no da: da igual que lo haya leido o
                #    se lo haya inventado, la condicion es que no sale de aqui.
                if (_da_un_precio_prohibido(cliente_id, texto_final, dicho_de_ella)
                        and vuelta + 1 < MAX_VUELTAS):
                    traza.freno("precio_que_no_se_da")
                    mensajes.append({
                        "role": "system",
                        "content": ("NO tienes ese precio y no puedes inventartelo ni "
                                    "dar un rango aproximado: este negocio lo dice en "
                                    "la cita de valoracion. Reescribe tu respuesta sin "
                                    "ninguna cifra, explicandole por que y ofreciendole "
                                    "esa cita."),
                    })
                    continue
                # 4) Y decir que la cita existe cuando no existe es el fallo mas
                #    caro: la clienta se planta en el salon y no hay hueco.
                # 0) Lo mismo que ya le dijiste, otra vez, no.
                if (_ya_dijo_esto(historial, texto_final)
                        and vuelta + 1 < MAX_VUELTAS):
                    traza.freno("se_repetia")
                    mensajes.append({
                        "role": "system",
                        "content": ("ESO YA SE LO HAS DICHO con esas mismas palabras y "
                                    "ella ha vuelto a escribir: repetirlo es un muro. "
                                    "Da un paso ADELANTE: si es algo que aqui no se "
                                    "hace o no se dice por mensaje, reconocele que "
                                    "insiste, dilo en una linea y ofrecele la salida "
                                    "concreta (una cita, o que llame). Y no empieces "
                                    "igual que antes."),
                    })
                    continue
                if (_dice_que_acaba_de_hacerlo(texto_final) and not mutada
                        and vuelta + 1 < MAX_VUELTAS):
                    traza.freno("dijo_haberlo_hecho_sin_hacerlo")
                    mensajes.append({
                        "role": "system",
                        "content": ("NO has tocado la agenda en este turno: no digas "
                                    "que acabas de reservar, cancelar, cambiar ni "
                                    "reabrir nada, porque no ha pasado. Si hace falta "
                                    "hacerlo, LLAMA A LA HERRAMIENTA. Y una cita "
                                    "cancelada NO se puede reabrir: lo que se hace es "
                                    "cogerle una NUEVA a esa misma hora si sigue libre, "
                                    "asi que compruebalo y diselo tal cual."),
                    })
                    continue
                # Su cita esta anulada: decir que sigue en pie es mandarla al
                # salon a una hora que ya no existe.
                if (estado.cancelada and not mutada
                        and _da_la_cita_por_hecha(texto_final)
                        and vuelta + 1 < MAX_VUELTAS):
                    traza.freno("daba_por_viva_una_cita_cancelada")
                    traza.freno("daba_la_cita_por_hecha")
                    mensajes.append({
                        "role": "system",
                        "content": ("Su cita esta CANCELADA: no digas que sigue en "
                                    "pie ni que esta confirmada. Una cita anulada no "
                                    "se puede reabrir; si la quiere recuperar, mira "
                                    "si ese hueco sigue libre y cogele una NUEVA."),
                    })
                    continue
                if (_da_la_cita_por_hecha(texto_final)
                        and not (mutada or mirada_la_cita or estado.hecho)
                        and vuelta + 1 < MAX_VUELTAS):
                    mensajes.append({
                        "role": "system",
                        "content": ("NO hay ninguna cita creada todavia. No digas que "
                                    "esta reservada, apuntada ni confirmada: dilo como "
                                    "una propuesta y pregunta si le viene bien."),
                    })
                    continue
                # Solo cuenta como dicho si de verdad ha salido en su respuesta.
                if aviso and "25" in texto_final:
                    estado.recargo_dicho = True
                reserva.guardar(cliente_id, telefono, estado,
                                pedido=reserva.que_falta(estado, conocido))
                final = _con_el_telefono_si_hace_falta(
                    cliente_id, mensaje,
                    _sin_comillas_en_los_servicios(cliente_id, texto_final),
                    cita_creada,
                )
                traza.guardar(mensaje=mensaje, respuesta=final)
                return final, cita_creada
            obligar = False

            # Lo que acaba de ofrecerle en ESTE turno tambien cuenta como ofrecido:
            # suele listar las horas y reprogramar justo despues.
            ofrecidas |= _horas_que_ha_dicho(elegido.content or "")
            mensajes.append({
                "role": "assistant",
                "content": elegido.content or "",
                "tool_calls": [
                    {
                        "id": t.id, "type": "function",
                        "function": {"name": t.function.name, "arguments": t.function.arguments},
                    }
                    for t in elegido.tool_calls
                ],
            })
            for llamada in elegido.tool_calls:
                try:
                    argumentos = json.loads(llamada.function.arguments or "{}")
                except (ValueError, TypeError):
                    argumentos = {}
                # Nadie acaba con una cita que no ha pedido. Paso con quien solo
                # preguntaba el horario: se iba con una cita que no sabia que
                # tenia, y el negocio con un hueco ocupado por nadie.
                if (llamada.function.name == "crear_cita"
                        and estado.intencion != "reservar"
                        and not reserva.ha_pedido_cita(dicho_de_ella)):
                    resultado = {
                        "ok": False,
                        "error": ("No te ha pedido ninguna cita: solo esta preguntando. "
                                  "No le cojas nada. Contesta lo que pregunta y, si "
                                  "acaso, ofrecele coger cita y ESPERA a que lo diga."),
                    }
                    mensajes.append({
                        "role": "tool", "tool_call_id": llamada.id,
                        "content": json.dumps(resultado, ensure_ascii=False),
                    })
                    traza.freno("cita_sin_pedirla")
                    continue
                # Vino preguntando el PRECIO de algo que aqui no se presupuesta
                # por mensaje: lo que se le coge es la cita de valoracion, no el
                # tratamiento de cuatro horas. Es la regla del propio salon
                # ("primero te vemos el pelo") y estaba escrita en una funcion que
                # no llamaba nadie. Ojo al matiz que corrigio la duenya: quien
                # viene a RESERVAR unas mechas se lleva sus mechas; esto solo vale
                # para quien ha venido a preguntar cuanto cuesta.
                if (llamada.function.name == "crear_cita" and estado.veces_sin_precio
                        and argumentos.get("servicio")):
                    from backend import booking as _bk

                    regla = _bk.regla_de_precio_para(cliente_id, str(argumentos["servicio"]))
                    cambio = _valoracion_en_lugar_del_tratamiento(
                        cliente_id, str(argumentos["servicio"]), location_id=location_id)
                    if not cambio.get("servicio") and regla:
                        # La regla no es "coger cita de valoracion" sino otra cosa
                        # (para los alisados, pedirle una foto). Se sigue LA SUYA,
                        # pero lo que no se hace es cogerle el tratamiento entero a
                        # quien solo ha preguntado el precio.
                        resultado = {
                            "ok": False,
                            "error": ("Ha preguntado el precio: aqui no se coge esa cita "
                                      "sin verlo antes."),
                            "lo_que_hace_el_negocio": regla.get("texto") or "",
                            "que_hacer": ("Haz lo que dice `lo_que_hace_el_negocio` (por "
                                          "ejemplo pedirle una foto) y espera. NO le "
                                          "cojas la cita del tratamiento todavia."),
                        }
                        mensajes.append({
                            "role": "tool", "tool_call_id": llamada.id,
                            "content": json.dumps(resultado, ensure_ascii=False),
                        })
                        continue
                    if cambio.get("servicio"):
                        resultado = {
                            "ok": False,
                            "error": ("De %s no se coge cita sin ver antes el pelo: lo "
                                      "que se reserva es %s."
                                      % (cambio.get("en_lugar_de") or "eso",
                                         cambio["servicio"])),
                            "reserva_esto_en_su_lugar": cambio["servicio"],
                            "que_hacer": ("Explicaselo en una linea -es corta, sin "
                                          "compromiso, y ahi le dan el presupuesto- y "
                                          "vuelve a llamar a crear_cita con ese "
                                          "servicio."),
                        }
                        mensajes.append({
                            "role": "tool", "tool_call_id": llamada.id,
                            "content": json.dumps(resultado, ensure_ascii=False),
                        })
                        continue
                # La cita se crea con el nombre EXACTO del catalogo. El modelo
                # habla con el nombre publico -sin "Pack"- y ese puede ser OTRO
                # servicio: paso de verdad, cogio media hora para un tratamiento
                # de 220 minutos porque existen los dos nombres.
                if (llamada.function.name == "crear_cita" and estado.servicio_exacto
                        and argumentos.get("servicio")):
                    dicho = catalog_pick._norm(str(argumentos["servicio"]))
                    publico = catalog_pick._norm(estado.servicio)
                    if dicho == publico:
                        argumentos["servicio"] = estado.servicio_exacto
                # Ha pedido que le anulen la cita: moverla no es eso. Paso de
                # verdad -"quiero cancelar mi cita"- y el modelo llamo a
                # reprogramar con el MISMO dia y la MISMA hora, dijo "listo,
                # reprogramada" y la clienta se quedo con la cita puesta.
                if (llamada.function.name == "reprogramar_cita"
                        and str(argumentos.get("hora") or "") not in ofrecidas
                        and _hora_que_nadie_ha_pedido(
                            estado, dicho_de_ella, str(argumentos.get("hora") or ""))):
                    resultado = {
                        "ok": False,
                        "error": ("Esa hora no la ha pedido ella ni se la has ofrecido: "
                                  "no le muevas la cita a un hueco que te has sacado "
                                  "tu. Mira que huecos hay de verdad, ofreceselos y "
                                  "espera a que elija."),
                    }
                    mensajes.append({
                        "role": "tool", "tool_call_id": llamada.id,
                        "content": json.dumps(resultado, ensure_ascii=False),
                    })
                    continue
                if (llamada.function.name in ("reprogramar_cita", "crear_cita")
                        and _pide_anular_y_solo_eso(mensaje)):
                    resultado = {
                        "ok": False,
                        "error": ("Ha pedido CANCELAR la cita, no cambiarla ni coger "
                                  "otra. Usa cancelar_cita."),
                    }
                    mensajes.append({
                        "role": "tool", "tool_call_id": llamada.id,
                        "content": json.dumps(resultado, ensure_ascii=False),
                    })
                    continue
                # Al buscar el servicio va TODO lo que ha dicho, no solo su
                # ultimo mensaje: quien dijo "unas mechas" y luego "lo tengo por
                # los hombros" ya ha dado los dos datos, y preguntarle otra vez
                # que servicio quiere es el fallo que mas se repite.
                if llamada.function.name == "buscar_servicio" and estado.servicio_texto:
                    dicho = str(argumentos.get("descripcion") or "").strip()
                    if catalog_pick._norm(dicho) not in catalog_pick._norm(estado.servicio_texto):
                        dicho = (estado.servicio_texto + " " + dicho).strip()
                    else:
                        dicho = estado.servicio_texto
                    argumentos["descripcion"] = dicho[-300:]
                # "cualquier hueco que tengas me vale" le hacia pedir el calendario
                # dia a dia (ocho de una tacada) hasta agotar el turno.
                if (llamada.function.name == "consultar_disponibilidad"
                        and dias_mirados >= 3):
                    resultado = {
                        "ok": True, "suficiente": True,
                        "mensaje": ("Ya has mirado varios dias y tienes huecos de "
                                    "sobra. Elige el primero que le encaje y remata "
                                    "la gestion; no consultes mas dias."),
                    }
                else:
                    resultado = await _ejecutar(
                        cliente_id, llamada.function.name, argumentos,
                        telefono=telefono, location_id=location_id, ya_creadas=ya_creadas,
                        quien=quien, remate_manual=remate_manual,
                    )
                traza.tool(llamada.function.name, argumentos,
                           ok=bool(resultado.get("ok", True)),
                           nota=str(resultado.get("error") or "")[:120])
                if llamada.function.name == "politica_del_negocio":
                    norma_mirada = True
                if llamada.function.name == "buscar_servicio":
                    catalogo_mirado = True
                    falta = str(resultado.get("falta") or "")
                    if falta and falta == estado.ultimo_falta:
                        # Ya se lo preguntaste y no lo ha elegido. Repetirle la
                        # misma lista es EL fallo mas repetido de la medicion:
                        # se cansa y se va. Se le pide otra cosa, o se moja.
                        resultado = dict(resultado)
                        resultado["nota"] = (
                            "OJO: esto ya se lo preguntaste en el mensaje anterior y "
                            "no se ha decidido. NO le repitas la misma lista. Haz una "
                            "de estas dos: preguntale otro dato que falte (por "
                            "ejemplo como tiene el pelo de largo), o mojate y "
                            "recomiendale UNA explicandole en una linea por que, y "
                            "dile que en la cita se puede cambiar."
                        )
                    estado.ultimo_falta = falta
                if llamada.function.name == "consultar_disponibilidad":
                    consultada = True
                    dias_mirados += 1
                    if resultado.get("ok") and not resultado.get("dia_cerrado", False):
                        dias_abiertos_vistos = True
                if llamada.function.name == "crear_cita" and resultado.get("ok"):
                    cita_creada = True
                    # Lo que hay que contarle SIN que pregunte: como venir
                    # preparada. "Aunque no pregunte por el protocolo, si se hace
                    # un alisado tenemos que decirselo" (el salon). Por WhatsApp
                    # ya iba en la confirmacion; por chat se perdia.
                    aviso_servicio = _nota_del_servicio(cliente_id, resultado)
                    if aviso_servicio:
                        resultado = dict(resultado)
                        resultado["avisale_de"] = aviso_servicio
                        resultado["nota"] = (
                            "IMPORTANTE: copiale `avisale_de` tal cual al confirmarle "
                            "la cita, aunque no haya preguntado. Son las indicaciones "
                            "del negocio para venir preparada."
                        )
                if resultado.get("ok"):
                    if llamada.function.name in ("crear_cita", "cancelar_cita",
                                                 "reprogramar_cita"):
                        mutada = True
                    elif llamada.function.name == "consultar_cita":
                        mirada_la_cita = True
                # El estado se llena SOLO con lo que DEVUELVEN las tools: es la
                # verdad del servidor, no lo que el modelo crea haber entendido.
                reserva.anotar_resultado(estado, llamada.function.name, argumentos, resultado)
                reserva.anotar_intencion_por_tool(estado, llamada.function.name)
                mensajes.append({
                    "role": "tool", "tool_call_id": llamada.id,
                    "content": json.dumps(
                        _sin_la_palabra_pack(resultado), ensure_ascii=False)[:2000],
                })
        # Se le acabaron las vueltas. Antes se devolvia vacio y la conversacion se
        # caia al flujo de listas a media frase. Se le pide UNA respuesta final con
        # todo lo que ya ha averiguado, sin mas herramientas.
        cierre = cliente.chat.completions.create(
            model=_modelo_del_negocio(cfg),
            messages=mensajes + [{
                "role": "system",
                "content": ("Contesta ya con lo que sabes, en una o dos frases, y dile "
                            "que te falta para seguir. No inventes datos que no tengas."),
            }],
            temperature=_temperatura_del_negocio(cfg),
            max_tokens=300,
        )
        reserva.guardar(cliente_id, telefono, estado,
                        pedido=reserva.que_falta(estado, conocido))
        remate_final = (cierre.choices[0].message.content or "").strip()
        traza.freno("se_acabaron_las_vueltas")
        traza.guardar(mensaje=mensaje, respuesta=remate_final)
        return remate_final, cita_creada
    except Exception as exc:  # noqa: BLE001 - nunca puede dejar a nadie sin respuesta
        settings.logger.warning("[agenda-agente] fallo con %s: %s", cliente_id, exc)
        # Si el modelo no contesta por saldo o credenciales, que se SEPA: se
        # quedaron sin creditos y el asistente dejo de responder a todo el mundo
        # mientras `/health` seguia diciendo que todo iba bien.
        from backend import rag

        if rag._es_fallo_de_cuenta(exc):
            rag._ia_marcar(False, str(exc))
        traza.freno("revento")
        traza.guardar(mensaje=mensaje, respuesta="[fallo] %s" % str(exc)[:200])
        return "", cita_creada
