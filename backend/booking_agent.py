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
from typing import Any, Dict, List, Optional, Tuple

from backend import catalog_pick, clients, db, settings, textnorm

# Cuantas vueltas de tool se le permiten en un turno. Con 4 le sobra para buscar
# un servicio, mirar huecos y crear la cita; el tope existe para que un modelo
# atascado no deje a la clienta esperando.
MAX_VUELTAS = 4

# Cuanta conversacion se le recuerda. Suficiente para que "y el jueves?" tenga
# sentido, sin pagar por la conversacion entera.
MAX_HISTORIAL = 12


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


async def _ejecutar(
    cliente_id: str, nombre: str, argumentos: Dict[str, Any], *,
    telefono: str, location_id: str = "", ya_creadas: Optional[set] = None,
) -> Dict[str, Any]:
    """Ejecuta una tool. Nunca lanza: un fallo se devuelve como resultado."""
    if nombre == "buscar_servicio":
        return _tool_buscar_servicio(cliente_id, argumentos, location_id=location_id)

    if nombre == "crear_cita":
        # El modelo rellena "nombre" con cualquier cosa con tal de poder llamar a
        # la tool. Sin nombre de verdad, no hay cita.
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
        return {
            "ok": True,
            "servicio": "",
            "falta": eleccion.falta,
            "opciones": eleccion.opciones,
            "sugerencia": catalog_pick.pregunta_para(eleccion),
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


def _instrucciones(cliente_id: str, config: Dict[str, Any], hoy) -> str:
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
            "- Si no encuentras hueco que le encaje o la cosa se complica, ofrecele "
            "llamar al %s: en el salon pueden mirar la agenda a mano." % telefono
        )
    if catalogo:
        partes += ["", "SU CATALOGO%s:" % ("" if completo else " (recortado)"), catalogo]
    if tono:
        partes += ["", tono]
    return "\n".join(partes)


def _historial(session_id: str, cliente_id: str) -> List[Dict[str, str]]:
    """Las ultimas frases de la conversacion, para que "y el jueves?" tenga sentido."""
    try:
        with db._get_db_connection() as conexion:
            filas = conexion.execute(
                "SELECT role, content FROM chat_messages WHERE session_id = ? AND cliente_id = ?"
                " ORDER BY id DESC LIMIT ?",
                (session_id, cliente_id, MAX_HISTORIAL),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[agenda-agente] sin historial (%s): %s", cliente_id, exc)
        return []
    mensajes = []
    for fila in reversed(filas):
        rol = "assistant" if str(fila["role"]) == "assistant" else "user"
        contenido = str(fila["content"] or "").strip()
        if contenido:
            mensajes.append({"role": rol, "content": contenido[:1200]})
    return mensajes


# ─── El turno ──────────────────────────────────────────────────────────────

async def responder(
    cliente_id: str,
    mensaje: str,
    *,
    session_id: str,
    telefono: str,
    config: Optional[Dict[str, Any]] = None,
    location_id: str = "",
) -> Tuple[str, bool]:
    """Contesta a la clienta llevando la conversacion de la cita.

    Devuelve (texto, cita_creada). Si devuelve texto vacio, quien llama debe tirar
    de su plan B (el flujo con listas): quedarse sin respuesta no es una opcion.
    """
    if not settings.OPENAI_API_KEY:
        return "", False
    cfg = config if config is not None else clients._get_client_config(cliente_id)

    from backend import timeutils

    try:
        from zoneinfo import ZoneInfo

        hoy = timeutils._utc_now().astimezone(
            ZoneInfo(str((cfg.get("booking") or {}).get("timezone") or settings.DEFAULT_TIMEZONE))
        ).date()
    except Exception:  # noqa: BLE001
        hoy = timeutils._utc_now().date()

    mensajes: List[Dict[str, Any]] = [
        {"role": "system", "content": _instrucciones(cliente_id, cfg, hoy)},
    ]
    mensajes.extend(_historial(session_id, cliente_id))
    mensajes.append({"role": "user", "content": str(mensaje)[:1200]})

    cita_creada = False
    ya_creadas: set = set()
    try:
        from openai import OpenAI as OpenAISdkClient

        cliente = OpenAISdkClient(api_key=settings.OPENAI_API_KEY, timeout=25.0)
        for _vuelta in range(MAX_VUELTAS):
            respuesta = cliente.chat.completions.create(
                model=settings.DEFAULT_CHAT_MODEL,
                messages=mensajes,
                tools=_herramientas(),
                temperature=0.3,
                max_tokens=400,
            )
            elegido = respuesta.choices[0].message
            if not getattr(elegido, "tool_calls", None):
                return (elegido.content or "").strip(), cita_creada

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
                resultado = await _ejecutar(
                    cliente_id, llamada.function.name, argumentos,
                    telefono=telefono, location_id=location_id, ya_creadas=ya_creadas,
                )
                if llamada.function.name == "crear_cita" and resultado.get("ok"):
                    cita_creada = True
                mensajes.append({
                    "role": "tool", "tool_call_id": llamada.id,
                    "content": json.dumps(resultado, ensure_ascii=False)[:2000],
                })
        # Se le acabaron las vueltas: mejor una respuesta honesta que el silencio.
        return "", cita_creada
    except Exception as exc:  # noqa: BLE001 - nunca puede dejar a nadie sin respuesta
        settings.logger.warning("[agenda-agente] fallo con %s: %s", cliente_id, exc)
        return "", cita_creada
