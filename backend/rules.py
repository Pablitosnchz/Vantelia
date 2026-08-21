# -*- coding: utf-8 -*-
"""Reglas del negocio: cuando pase X, haz Y.

POR QUE EXISTE
--------------
Lo que diferencia al asistente de un negocio del de otro no es el motor: son sus
reglas. Un salon real las dicta asi:

    "Solo pide foto cuando quieran cita para alisado PERO quieran presupuesto:
     entonces se le pide la foto por detras y se le dice que en breve nos
     pondremos en contacto para darles el precio nosotros."

Hasta ahora eso vivia en dos sitios malos: una instruccion en el prompt (que el
modelo puede ignorar) y una Q&A con etiquetas escritas a mano, una por cada forma
de preguntarlo ("presupuesto de un alisado", "presupuesto para un alisado"...).

Aqui una regla es CUANDO -> ENTONCES, se guarda por tenant y se ejecuta siempre.
La intencion la pone `backend/intents.py`; esto solo decide que hacer con ella.

COMO SE EVALUA
--------------
Gana la primera regla activa, por `prioridad`, cuya condicion case. Si ninguna
casa no pasa nada: el chat sigue por donde iba. Una regla NUNCA deja al cliente
sin respuesta.

ACCIONES
--------
`responder`          contesta el texto de la regla y corta el turno
`formulario`         contesta y ademas abre el formulario de reserva
`ofrecer_cita`       contesta ofreciendo cita (el texto lo pone el negocio)
`pedir_foto`         contesta pidiendo la foto (la conversacion se ve en el
                     panel; NO silencia al asistente: hoy no hay aviso al negocio
                     y la clienta se quedaria esperando en el vacio)
`pasar_a_humano`     contesta y silencia al asistente en esa conversacion
`continuar`          no responde: solo deja constancia de que caso (util para
                     medir antes de activar una regla de verdad)
"""
from __future__ import annotations

import json
import sqlite3
import unicodedata
from typing import Any, Dict, List, Optional

from backend import db, timeutils

ACCIONES = ("responder", "formulario", "ofrecer_cita", "pedir_foto", "pasar_a_humano", "continuar")


def _norm(texto: str) -> str:
    limpio = unicodedata.normalize("NFKD", str(texto or "").lower())
    return " ".join("".join(c for c in limpio if not unicodedata.combining(c)).split())


def _fila_a_dict(row: sqlite3.Row) -> Dict[str, Any]:
    def _lista(valor: str) -> List[str]:
        try:
            datos = json.loads(valor or "[]")
        except (ValueError, TypeError):
            return []
        return [_norm(x) for x in datos if str(x).strip()] if isinstance(datos, list) else []

    return {
        "id": row["id"],
        "cliente_id": row["cliente_id"],
        "nombre": row["nombre"] or "",
        "intenciones": _lista(row["intenciones_json"]),
        "familias": _lista(row["familias_json"]),
        "accion": row["accion"] or "responder",
        "texto": row["texto"] or "",
        "prioridad": int(row["prioridad"] or 100),
        "activa": bool(row["activa"]),
        "veces": int(row["veces"] or 0),
    }


def listar(cliente_id: str, *, solo_activas: bool = False) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM business_rules WHERE cliente_id = ?"
    if solo_activas:
        sql += " AND activa = 1"
    sql += " ORDER BY prioridad ASC, id ASC"
    with db._get_db_connection() as conexion:
        return [_fila_a_dict(f) for f in conexion.execute(sql, (cliente_id,)).fetchall()]


def guardar(
    cliente_id: str, *, nombre: str, intenciones: List[str], accion: str, texto: str = "",
    familias: Optional[List[str]] = None, prioridad: int = 100, activa: bool = True,
    regla_id: str = "",
) -> Dict[str, Any]:
    """Crea o actualiza una regla. Devuelve la regla guardada."""
    import secrets

    if accion not in ACCIONES:
        raise ValueError("accion no valida: %s" % accion)
    ahora = timeutils._utc_now_iso()
    datos = (
        nombre[:120],
        json.dumps([_norm(i) for i in intenciones], ensure_ascii=False),
        json.dumps([_norm(f) for f in (familias or [])], ensure_ascii=False),
        accion, texto[:2000], int(prioridad), 1 if activa else 0, ahora,
    )
    with db._get_db_connection() as conexion:
        if regla_id:
            conexion.execute(
                "UPDATE business_rules SET nombre=?, intenciones_json=?, familias_json=?,"
                " accion=?, texto=?, prioridad=?, activa=?, updated_at=?"
                " WHERE id=? AND cliente_id=?",
                datos + (regla_id, cliente_id),
            )
        else:
            regla_id = "rule_%s" % secrets.token_urlsafe(8)
            conexion.execute(
                "INSERT INTO business_rules (id, cliente_id, nombre, intenciones_json,"
                " familias_json, accion, texto, prioridad, activa, updated_at, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (regla_id, cliente_id) + datos + (ahora,),
            )
        conexion.commit()
    return next((r for r in listar(cliente_id) if r["id"] == regla_id), {})


def borrar(cliente_id: str, regla_id: str) -> bool:
    with db._get_db_connection() as conexion:
        cursor = conexion.execute(
            "DELETE FROM business_rules WHERE id=? AND cliente_id=?", (regla_id, cliente_id)
        )
        conexion.commit()
        return cursor.rowcount > 0


def match(cliente_id: str, intencion: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Primera regla que case con lo que quiere el cliente.

    Una regla sin familias vale para cualquier servicio; con familias, solo si la
    detectada esta entre ellas. Asi conviven "para cualquier precio, ofrece cita"
    y "para el precio de un ALISADO, pide foto", ganando la mas especifica si el
    negocio le pone menos prioridad.
    """
    if not intencion:
        return None
    quiere = _norm(intencion.get("intencion"))
    familia = _norm(intencion.get("familia"))
    if not quiere:
        return None
    for regla in listar(cliente_id, solo_activas=True):
        if regla["intenciones"] and quiere not in regla["intenciones"]:
            continue
        if regla["familias"]:
            # Sin familia detectada NO puede ganar una regla que exige familia:
            # "cuanto cuesta?" a secas no es "cuanto cuesta un alisado".
            if not familia or not any(f in familia or familia in f
                                      for f in regla["familias"] if f):
                continue
        return regla
    return None


def contar_uso(regla_id: str) -> None:
    """Cuantas veces ha respondido esta regla. El negocio mide si le sirve."""
    try:
        with db._get_db_connection() as conexion:
            conexion.execute(
                "UPDATE business_rules SET veces = veces + 1, last_used_at = ? WHERE id = ?",
                (timeutils._utc_now_iso(), regla_id),
            )
            conexion.commit()
    except Exception:  # noqa: BLE001 - contar no puede romper una respuesta
        pass
