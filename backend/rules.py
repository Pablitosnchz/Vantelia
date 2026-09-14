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
from typing import Any, Dict, List, Optional

from backend import db, timeutils

ACCIONES = ("responder", "formulario", "ofrecer_cita", "pedir_foto", "pasar_a_humano", "continuar")


def _norm(texto: str) -> str:
    """Delega en `textnorm.normalizar`: una sola forma de normalizar en todo el codigo."""
    from backend import textnorm

    return textnorm.normalizar(texto)


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
        # De que situacion tipica salio, si salio de una (backend/playbooks.py).
        "playbook_id": (row["playbook_id"] if "playbook_id" in row.keys() else "") or "",
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
    regla_id: str = "", playbook_id: str = "",
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
        str(playbook_id or "")[:60],
    )
    with db._get_db_connection() as conexion:
        if regla_id:
            conexion.execute(
                "UPDATE business_rules SET nombre=?, intenciones_json=?, familias_json=?,"
                " accion=?, texto=?, prioridad=?, activa=?, updated_at=?, playbook_id=?"
                " WHERE id=? AND cliente_id=?",
                datos + (regla_id, cliente_id),
            )
        else:
            regla_id = "rule_%s" % secrets.token_urlsafe(8)
            conexion.execute(
                "INSERT INTO business_rules (id, cliente_id, nombre, intenciones_json,"
                " familias_json, accion, texto, prioridad, activa, updated_at, playbook_id,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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


# Las acciones que CONTESTAN a la clienta: sin texto le llegaria un mensaje vacio.
_CONTESTAN = ("responder", "formulario", "ofrecer_cita", "pedir_foto", "pasar_a_humano")


def errores_al_guardar(intenciones: List[str], accion: str, texto: str) -> str:
    """Lo que hace IMPOSIBLE que una regla funcione. Cadena vacia si se puede guardar.

    El formulario del portal ya pedia intenciones y texto, pero la API no: una regla
    sin intenciones casa con CUALQUIER mensaje, y una sin texto contesta en blanco.
    """
    from backend import intents

    marcadas = [_norm(i) for i in (intenciones or []) if str(i).strip()]
    if not marcadas:
        return "Marca al menos qué te piden para que salte la regla."
    desconocidas = [i for i in marcadas if i not in intents.INTENCIONES]
    if desconocidas:
        return "«%s» no es un tipo de petición que el asistente reconozca." % ", ".join(desconocidas)
    if accion in _CONTESTAN and not str(texto or "").strip():
        return "Escribe el texto que debe responder la regla."
    return ""


def _casan_familias(a: str, b: str) -> bool:
    """Igual que `match`: una familia casa con otra si una contiene a la otra."""
    return bool(a) and bool(b) and (a in b or b in a)


def _cubre(antes: Dict[str, Any], despues: Dict[str, Any]) -> bool:
    """¿La regla de `antes` casa con todo lo que casaria la de `despues`?"""
    if antes["intenciones"]:
        if not despues["intenciones"] or not set(despues["intenciones"]) <= set(antes["intenciones"]):
            return False
    if antes["familias"]:
        if not despues["familias"]:
            return False
        return all(any(_casan_familias(fa, fd) for fa in antes["familias"]) for fd in despues["familias"])
    return True


def _se_pisan(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """¿Hay algun mensaje con el que casarian las dos?"""
    intenciones = (not a["intenciones"] or not b["intenciones"]
                   or bool(set(a["intenciones"]) & set(b["intenciones"])))
    familias = (not a["familias"] or not b["familias"]
                or any(_casan_familias(fa, fb) for fa in a["familias"] for fb in b["familias"]))
    return intenciones and familias


def avisos(cliente_id: str, reglas: Optional[List[Dict[str, Any]]] = None) -> Dict[str, List[str]]:
    """Por cada regla, lo que va a hacer que no funcione como el negocio espera.

    Fase 3 del plan de consolidacion: «indicar configuracion invalida/conflictiva».
    Gana la primera regla activa por prioridad cuyas intenciones y familias casen
    (`match`), asi que se avisa de: una regla tapada por otra que va antes; dos
    reglas que se pisan con la MISMA prioridad (gana la que se creo antes, que el
    negocio no ve); sin intenciones (casa con todo); intencion que no existe; texto
    vacio en una accion que contesta; familia que no esta en su catalogo; y ofrecer
    cita sin ningun servicio de valoracion al que llevar (la oferta no hace nada).

    No bloquea nada: lo imposible se rechaza al guardar (`errores_al_guardar`).
    """
    from backend import intents

    reglas = listar(cliente_id) if reglas is None else list(reglas)
    salida: Dict[str, List[str]] = {str(r["id"]): [] for r in reglas}
    normalizadas = []
    for regla in reglas:
        normalizadas.append(dict(regla,
                                 intenciones=[_norm(i) for i in regla.get("intenciones") or [] if str(i).strip()],
                                 familias=[_norm(f) for f in regla.get("familias") or [] if str(f).strip()],
                                 prioridad=int(regla.get("prioridad") or 100)))

    familias_del_negocio: set = set()
    del_catalogo: List[str] = []
    catalogo_leido = False
    try:
        from backend import catalog_pick

        familias_del_negocio = {_norm(f) for f in intents.familias_del_tenant(cliente_id)}
        del_catalogo = [_norm("%s %s" % (catalog_pick._nombre(s), s.get("category") or ""))
                        for s in catalog_pick._servicios(cliente_id, "")]
        catalogo_leido = bool(familias_del_negocio or del_catalogo)
    except Exception:  # noqa: BLE001 - sin catalogo no se avisa de familias
        catalogo_leido = False
    hay_valoracion = None

    for regla in normalizadas:
        lista = salida[str(regla["id"])]
        if not regla["intenciones"]:
            lista.append("Sin «qué te piden»: casaría con cualquier mensaje, también con quien "
                         "solo saluda o quiere reservar.")
        raras = [i for i in regla["intenciones"] if i not in intents.INTENCIONES]
        if raras:
            lista.append("«%s» no es un tipo de petición que el asistente reconozca: esa parte "
                         "no casará nunca." % ", ".join(raras))
        if regla.get("accion") in _CONTESTAN and not str(regla.get("texto") or "").strip():
            lista.append("No tiene texto: la clienta recibiría un mensaje vacío.")
        if catalogo_leido:
            for familia in regla["familias"]:
                if familia not in familias_del_negocio and not any(familia in t for t in del_catalogo):
                    lista.append("«%s» no aparece en tu catálogo: con esa familia la regla no "
                                 "saltará." % familia)
        if regla.get("accion") == "ofrecer_cita":
            if hay_valoracion is None:
                try:
                    from backend import booking

                    hay_valoracion = bool((booking._servicio_de_valoracion(cliente_id) or {}).get("id"))
                except Exception:  # noqa: BLE001 - ante la duda no se avisa
                    hay_valoracion = True
            if not hay_valoracion:
                lista.append("Para ofrecer cita hace falta un servicio de valoración o diagnóstico en "
                             "tu catálogo, y no hay ninguno: la regla no ofrecerá nada.")

    activas = sorted([r for r in normalizadas if r.get("activa")],
                     key=lambda r: (r["prioridad"], str(r["id"])))
    for indice, despues in enumerate(activas):
        for antes in activas[:indice]:
            if antes["prioridad"] < despues["prioridad"] and _cubre(antes, despues):
                salida[str(despues["id"])].append(
                    "Nunca saltará: «%s» (prioridad %d) cubre los mismos casos y va antes."
                    % (antes.get("nombre") or antes["id"], antes["prioridad"]))
                break
        for otra in activas:
            if (otra["id"] != despues["id"] and otra["prioridad"] == despues["prioridad"]
                    and _se_pisan(otra, despues)):
                salida[str(despues["id"])].append(
                    "Comparte la prioridad %d con «%s» para casos que se pisan: gana la que se creó "
                    "antes. Dale a cada una su prioridad." % (despues["prioridad"], otra.get("nombre") or otra["id"]))
                break
    return salida


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
