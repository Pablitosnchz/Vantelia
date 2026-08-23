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
    quien: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Ejecuta una tool. Nunca lanza: un fallo se devuelve como resultado."""
    argumentos = _normalizar_argumentos(argumentos)
    if nombre == "buscar_servicio":
        return _tool_buscar_servicio(cliente_id, argumentos, location_id=location_id)

    if nombre == "consultar_horario":
        return _tool_consultar_horario(cliente_id, argumentos)

    if nombre == "politica_del_negocio":
        return _tool_politica_del_negocio(cliente_id, argumentos)

    if nombre == "crear_cita":
        # El modelo rellena "nombre" con cualquier cosa con tal de poder llamar a
        # la tool. Sin nombre de verdad, no hay cita.
        # De una clienta conocida ya se sabe el nombre: lo pone el codigo antes de
        # dar por incompleta la cita, en vez de hacersela repetir.
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
        return {"ok": True, "servicio": eleccion.servicio, **detalle}
    if eleccion.falta in ("tecnica", "talla"):
        # Con DURACION de cada candidato: a "¿cuanto tiempo tengo que estar ahi?"
        # se le puede contestar el abanico ("de 45 a 75 minutos segun el largo") sin
        # obligarla a concretar. Sin este dato el agente preguntaba dos veces.
        detalle = []
        for nombre in eleccion.candidatos[:8]:
            datos_servicio = _detalle_servicio(cliente_id, nombre)
            minutos = datos_servicio.get("duracion_minutos") or 0
            detalle.append({"servicio": nombre, "duracion_minutos": minutos})
        return {
            "ok": True,
            "servicio": "",
            "falta": eleccion.falta,
            "opciones": eleccion.opciones,
            "candidatos": detalle,
            "sugerencia": catalog_pick.pregunta_para(eleccion),
            "nota": ("Si solo pregunta cuanto dura o cuanto cuesta, contesta con estos "
                     "candidatos y sus datos; no la obligues a concretar."),
        }
    return {
        "ok": False,
        "error": "En este catalogo no hay nada que encaje con eso.",
        "servicios_parecidos": _parecidos(cliente_id, descripcion),
    }


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
            salida.append(nombre)
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


# Lo que solo se puede decir habiendo mirado la agenda.
_HABLA_DE_AGENDA = (
    "cerrado", "cerramos", "no abrimos", "no tengo hueco", "no hay hueco",
    "no tengo disponib", "no hay disponib", "tengo libre", "puedo ofrecerte",
    "estas horas", "estos horarios",
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

    quien = _quien_escribe(cliente_id, telefono)
    historial = _historial(session_id, cliente_id)

    estado = reserva.cargar(cliente_id, telefono)
    reserva.anotar_intencion(estado, intencion)
    reserva.anotar_lo_que_dice(
        estado, mensaje,
        str((cfg.get("booking") or {}).get("timezone") or settings.DEFAULT_TIMEZONE),
    )
    conocido = quien.get("nombre", "")

    mensajes: List[Dict[str, Any]] = [
        {"role": "system", "content": _instrucciones(cliente_id, cfg, hoy, quien)},
    ]
    mensajes.extend(historial)
    mensajes.append({"role": "user", "content": str(mensaje)[:1200]})

    cita_creada = False
    consultada = False  # se ha mirado la agenda en este turno
    dias_mirados = 0
    ya_creadas: set = set()
    try:
        from openai import OpenAI as OpenAISdkClient

        cliente = OpenAISdkClient(api_key=settings.OPENAI_API_KEY, timeout=25.0)
        obligar = False
        for vuelta in range(MAX_VUELTAS):
            # Lo que el codigo sabe y lo que toca hacer, delante del modelo en CADA
            # vuelta: asi no hay nada que corregirle despues.
            # El estado INFORMA (lo que ya sabe, para que no lo repregunte) pero
            # no DIRIGE: dictarle la frase le quitaba lo unico que hace bien
            # -adaptarse- y cuando el codigo se equivocaba, se equivocaba en bucle.
            # Medido: repetir la misma pregunta paso de 3 a 15 conversaciones de 40.
            guia = [t for t in (reserva.resumen(estado, conocido),
                                reserva.instruccion_de_cierre(estado, conocido)) if t]
            turno = list(mensajes)
            if guia:
                turno.append({"role": "system", "content": "\n\n".join(guia)})

            # Con todos los datos en la mano, la herramienta que cierra la gestion
            # no se sugiere: se obliga. Pedirselo "con enfasis" seguia siendo
            # prompt, y el modelo se escaqueaba volviendo a consultar huecos.
            remate = reserva.tool_que_remata(estado, conocido)
            if remate and not obligar:
                eleccion = {"type": "function", "function": {"name": remate}}
            elif obligar:
                eleccion = "required"
            else:
                eleccion = "auto"

            respuesta = cliente.chat.completions.create(
                model=settings.DEFAULT_CHAT_MODEL,
                messages=turno,
                tools=_herramientas(),
                tool_choice=eleccion,
                temperature=0.3,
                max_tokens=400,
            )
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
                    mensajes.append({
                        "role": "system",
                        "content": ("Antes de decir nada sobre dias u horas, consulta "
                                    "`consultar_disponibilidad`. No afirmes que un dia "
                                    "esta cerrado ni que no hay hueco sin haberlo mirado."),
                    })
                    continue
                # 3) Y decir que la cita existe cuando no existe es el fallo mas
                #    caro: la clienta se planta en el salon y no hay hueco.
                if (_da_la_cita_por_hecha(texto_final) and not estado.hecho
                        and vuelta + 1 < MAX_VUELTAS):
                    mensajes.append({
                        "role": "system",
                        "content": ("NO hay ninguna cita creada todavia. No digas que "
                                    "esta reservada, apuntada ni confirmada: dilo como "
                                    "una propuesta y pregunta si le viene bien."),
                    })
                    continue
                reserva.guardar(cliente_id, telefono, estado,
                                pedido=reserva.que_falta(estado, conocido))
                return _con_el_telefono_si_hace_falta(
                    cliente_id, mensaje, texto_final, cita_creada,
                ), cita_creada
            obligar = False

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
                        quien=quien,
                    )
                if llamada.function.name == "consultar_disponibilidad":
                    consultada = True
                    dias_mirados += 1
                if llamada.function.name == "crear_cita" and resultado.get("ok"):
                    cita_creada = True
                # El estado se llena SOLO con lo que DEVUELVEN las tools: es la
                # verdad del servidor, no lo que el modelo crea haber entendido.
                reserva.anotar_resultado(estado, llamada.function.name, argumentos, resultado)
                reserva.anotar_intencion_por_tool(estado, llamada.function.name)
                mensajes.append({
                    "role": "tool", "tool_call_id": llamada.id,
                    "content": json.dumps(resultado, ensure_ascii=False)[:2000],
                })
        # Se le acabaron las vueltas. Antes se devolvia vacio y la conversacion se
        # caia al flujo de listas a media frase. Se le pide UNA respuesta final con
        # todo lo que ya ha averiguado, sin mas herramientas.
        cierre = cliente.chat.completions.create(
            model=settings.DEFAULT_CHAT_MODEL,
            messages=mensajes + [{
                "role": "system",
                "content": ("Contesta ya con lo que sabes, en una o dos frases, y dile "
                            "que te falta para seguir. No inventes datos que no tengas."),
            }],
            temperature=0.3,
            max_tokens=300,
        )
        reserva.guardar(cliente_id, telefono, estado,
                        pedido=reserva.que_falta(estado, conocido))
        return (cierre.choices[0].message.content or "").strip(), cita_creada
    except Exception as exc:  # noqa: BLE001 - nunca puede dejar a nadie sin respuesta
        settings.logger.warning("[agenda-agente] fallo con %s: %s", cliente_id, exc)
        return "", cita_creada
