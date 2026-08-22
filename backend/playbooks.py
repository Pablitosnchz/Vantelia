# -*- coding: utf-8 -*-
"""Situaciones tipicas de un negocio, listas para activar y personalizar.

POR QUE EXISTE
--------------
Las doce condiciones que pidio un salon real ("no des precios de mechas sin verlas",
"pide una foto si quieren presupuesto de alisado", "ofrece llamar antes de perder
la cita") se montaron a mano, con un script por cliente. Eso no escala: el
siguiente negocio pide otras doce distintas y alguien tiene que volver a escribir
codigo.

Aqui esas situaciones son PLANTILLAS genericas. El negocio elige las que le valen y
cambia el texto; el asistente se comporta distinto sin tocar una linea. Una clinica
puede decir "no doy precios de implantes sin radiografia" con la misma plantilla
con la que un salon dice "no doy precios de mechas sin ver el pelo".

COMO ENCAJA
-----------
Cada plantilla se convierte en una fila de `business_rules` (backend/rules.py), que
es lo que ya consulta el asistente. Esto no es un mecanismo nuevo: es la forma
comoda de rellenar el que ya hay.

    playbooks.CATALOGO          -> las situaciones disponibles
    playbooks.aplicar(...)      -> crea/actualiza la regla de ese negocio
    playbooks.estado(cliente)   -> cuales tiene activas

Las variables del texto ({telefono}, {servicio}) se sustituyen al aplicar.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend import clients, rules

# Cada plantilla: que situacion cubre, que hace el asistente y un texto de partida
# que el negocio puede reescribir entero.
CATALOGO: List[Dict[str, Any]] = [
    {
        "id": "sin_precio_sin_verlo",
        "titulo": "No dar precio sin ver al cliente",
        "explicacion": (
            "Para trabajos donde el precio depende de cada persona. En vez de una "
            "cifra, se ofrece una cita de valoracion."
        ),
        "ejemplo": "Mechas, balayage, cambios de color, implantes, presupuestos a medida.",
        "intenciones": ["precio", "presupuesto"],
        "accion": "ofrecer_cita",
        "prioridad": 50,
        "pide_familias": True,
        "texto": (
            "Te lo digo con sinceridad: el precio depende mucho de cada caso, así que "
            "no queremos darte una cifra a ciegas 😊\n\n"
            "Lo vemos en una valoración sin compromiso y te lo decimos cerrado. "
            "¿Te busco un hueco{telefono_o}?"
        ),
    },
    {
        "id": "pedir_foto",
        "titulo": "Pedir una foto para poder presupuestar",
        "explicacion": (
            "Cuando SI se puede presupuestar a distancia, pero hace falta ver algo. "
            "El asistente pide la foto y avisa de que contestareis vosotros."
        ),
        "ejemplo": "Presupuesto de alisado con una foto del pelo por detras.",
        "intenciones": ["presupuesto", "precio"],
        "accion": "pedir_foto",
        "prioridad": 10,
        "pide_familias": True,
        "texto": (
            "¡Claro que sí! 😊 Para darte un precio afinado necesitamos verlo: "
            "¿nos mandas una foto?\n\n"
            "En cuanto la veamos nos ponemos en contacto contigo para decirte el "
            "presupuesto personalmente 💛"
        ),
    },
    {
        "id": "derivar_a_valoracion",
        "titulo": "Derivar un servicio a valoración",
        "explicacion": (
            "Para servicios que no se pueden cerrar por mensaje. Se explica por que y "
            "se ofrece cita para verlo."
        ),
        "ejemplo": "Extensiones, tratamientos que dependen del diagnostico.",
        "intenciones": ["precio", "presupuesto", "info"],
        "accion": "ofrecer_cita",
        "prioridad": 20,
        "pide_familias": True,
        "texto": (
            "¡Claro que sí! Esto depende mucho de cada caso, así que lo ideal es verlo "
            "en persona: te aconsejamos qué necesitas y te damos presupuesto sin "
            "compromiso.\n\n¿Te busco un hueco para la valoración? 😊"
        ),
    },
    {
        "id": "pasar_a_persona",
        "titulo": "Pasar la conversación a una persona",
        "explicacion": (
            "Para temas delicados. El asistente contesta y deja de responder en esa "
            "conversacion hasta que alguien la atienda desde el panel."
        ),
        "ejemplo": "Quejas, reclamaciones, incidencias con un servicio ya hecho.",
        "intenciones": ["queja"],
        "accion": "pasar_a_humano",
        "prioridad": 5,
        "pide_familias": False,
        "texto": (
            "Siento mucho lo que me cuentas. Prefiero que te atienda una compañera "
            "directamente: le paso ahora mismo tu mensaje y te contesta enseguida."
        ),
    },
    {
        "id": "solo_informar",
        "titulo": "Responder algo concreto y nada más",
        "explicacion": (
            "Una respuesta fija para una situacion concreta, sin ofrecer cita ni "
            "seguir la conversacion por ahi."
        ),
        "ejemplo": "Formas de pago, si hay parking, politica de acompañantes.",
        "intenciones": ["info"],
        "accion": "responder",
        "prioridad": 60,
        "pide_familias": True,
        "texto": "",
    },
    {
        "id": "medir_sin_responder",
        "titulo": "Solo contarlo, sin responder nada",
        "explicacion": (
            "Para saber cuanta gente pregunta algo antes de decidir que contestar. El "
            "asistente sigue como siempre y solo se apunta el contador."
        ),
        "ejemplo": "Cuantas preguntan por un servicio que estais pensando ofrecer.",
        "intenciones": ["info"],
        "accion": "continuar",
        "prioridad": 90,
        "pide_familias": True,
        "texto": "",
    },
]

_POR_ID = {p["id"]: p for p in CATALOGO}


def catalogo() -> List[Dict[str, Any]]:
    """Las situaciones disponibles, para pintarlas en el panel."""
    return [dict(p) for p in CATALOGO]


def _telefono(cliente_id: str) -> str:
    try:
        contacto = clients._get_client_config(cliente_id).get("contacto") or {}
        return str(contacto.get("telefono") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _rellenar(texto: str, cliente_id: str) -> str:
    """Sustituye las variables del texto por los datos del negocio."""
    telefono = _telefono(cliente_id)
    return (
        str(texto or "")
        .replace("{telefono_o}", (" o prefieres llamarnos al %s" % telefono) if telefono else "")
        .replace("{telefono}", telefono)
    )


def aplicar(
    cliente_id: str,
    playbook_id: str,
    *,
    familias: Optional[List[str]] = None,
    texto: str = "",
    prioridad: Optional[int] = None,
    activa: bool = True,
    nombre: str = "",
) -> Dict[str, Any]:
    """Convierte una plantilla en una regla de ESTE negocio.

    Idempotente por nombre: aplicarla dos veces actualiza, no duplica (renombrar una
    regla y dejar viva la vieja ya costo un incidente).
    """
    plantilla = _POR_ID.get(playbook_id)
    if not plantilla:
        raise ValueError("no existe la situacion %r" % playbook_id)

    titulo = nombre.strip() or plantilla["titulo"]
    cuerpo = _rellenar(texto.strip() or plantilla["texto"], cliente_id)
    if not cuerpo and plantilla["accion"] != "continuar":
        raise ValueError("esta situacion necesita un texto de respuesta")

    existente = next(
        (r for r in rules.listar(cliente_id) if r["nombre"] == titulo), None
    )
    return rules.guardar(
        cliente_id,
        regla_id=existente["id"] if existente else "",
        nombre=titulo,
        intenciones=list(plantilla["intenciones"]),
        familias=list(familias or []),
        accion=plantilla["accion"],
        texto=cuerpo,
        prioridad=plantilla["prioridad"] if prioridad is None else int(prioridad),
        activa=activa,
    )


def estado(cliente_id: str) -> List[Dict[str, Any]]:
    """Que situaciones tiene montadas este negocio, y con que texto."""
    activas = rules.listar(cliente_id)
    por_titulo = {r["nombre"]: r for r in activas}
    salida = []
    for plantilla in CATALOGO:
        regla = por_titulo.get(plantilla["titulo"])
        salida.append({
            "id": plantilla["id"],
            "titulo": plantilla["titulo"],
            "explicacion": plantilla["explicacion"],
            "ejemplo": plantilla["ejemplo"],
            "pide_familias": plantilla["pide_familias"],
            "activa": bool(regla and regla["activa"]),
            "familias": regla["familias"] if regla else [],
            "texto": regla["texto"] if regla else _rellenar(plantilla["texto"], cliente_id),
            "veces": regla["veces"] if regla else 0,
        })
    return salida
