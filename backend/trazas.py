# -*- coding: utf-8 -*-
"""Que hizo el asistente en cada turno: herramientas, frenos, tiempo y coste.

POR QUE EXISTE
--------------
El 26 de agosto de 2026, para saber por que el asistente dijo "a las 10:30 ya
tengo una cita" -era mentira, estaba libre para las cinco profesionales- hubo que
escribir tres scripts desechables: uno que consultara la agenda, otro que llamara
a la herramienta a mano y otro que espiara que tools se ejecutaban. Ese dia se
escribieron DOCE scripts asi.

Con esto, la misma pregunta se contesta mirando una fila: "en ese turno no llamo a
`consultar_disponibilidad`". Diez segundos.

Y hay un dato que no estaba en ningun sitio: lo que cuesta cada conversacion. Nos
enteramos de que se acababa el saldo de OpenAI porque **se cayo produccion**.

QUE GUARDA Y QUE NO
-------------------
Guarda lo que hizo el asistente: que herramientas llamo, con que argumentos, si
salieron bien, cuanto tardo, cuantos tokens gasto y QUE FRENOS saltaron. El texto
de la conversacion ya se guarda en `chat_messages` desde siempre; aqui solo va
recortado, para poder leer una traza sin cruzar tablas.

Todo se queda en NUESTRA base de datos. No sale nada a ningun servicio externo.

REGLA DE ORO
------------
Esto es un cuaderno de bitacora: **jamas puede tumbar una conversacion**. Cada
punto de escritura va envuelto y, si falla, se registra y se sigue. Un cliente no
se puede quedar sin respuesta porque no se pudo apuntar una metrica.

COMO SE USA
-----------
    traza = trazas.Traza(cliente_id, session_id)
    traza.tool("consultar_disponibilidad", {"fecha": "..."}, ok=True, ms=120)
    traza.freno("no_repetirse")
    traza.modelo("gpt-4o-mini", prompt=1200, salida=180)
    traza.guardar(mensaje="...", respuesta="...")
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List

from backend import db, settings, timeutils

# Cuanto cuesta cada modelo, en euros por millon de tokens (entrada, salida).
# Aproximado a proposito: sirve para saber si una conversacion cuesta centimos o
# euros, no para la contabilidad. Si cambian las tarifas, se cambia aqui.
PRECIO_POR_MILLON: Dict[str, tuple] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
}

# Cuanto tiempo se guardan las trazas. Son para depurar y medir, no un archivo
# historico: a los 30 dias ya no dicen nada que no sepamos.
DIAS_QUE_SE_GUARDAN = 30


def coste_euros(modelo: str, tokens_entrada: int, tokens_salida: int) -> float:
    """Lo que ha costado ese turno, en euros. 0 si no conocemos el modelo."""
    tarifa = PRECIO_POR_MILLON.get(str(modelo or "").strip())
    if not tarifa:
        return 0.0
    entrada, salida = tarifa
    return round(
        (max(0, int(tokens_entrada)) * entrada + max(0, int(tokens_salida)) * salida) / 1_000_000.0,
        6,
    )


@dataclass
class Traza:
    """Lo que va pasando en UN turno. Se rellena mientras corre y se guarda al final."""

    cliente_id: str
    session_id: str
    canal: str = ""
    _tools: List[Dict[str, Any]] = field(default_factory=list)
    _frenos: List[str] = field(default_factory=list)
    _modelo: str = ""
    _tokens_entrada: int = 0
    _tokens_salida: int = 0
    _vueltas: int = 0
    _arranque: float = field(default_factory=time.time)

    # ─── Lo que se va apuntando ────────────────────────────────────────────

    def tool(self, nombre: str, argumentos: Any = None, *, ok: bool = True,
             ms: int = 0, nota: str = "") -> None:
        """Una herramienta ejecutada. Los argumentos se recortan: son para leerlos."""
        self._tools.append({
            "nombre": str(nombre or "")[:60],
            "args": json.dumps(argumentos, ensure_ascii=False)[:300] if argumentos else "",
            "ok": bool(ok),
            "ms": max(0, int(ms)),
            "nota": str(nota or "")[:200],
        })

    def freno(self, cual: str) -> None:
        """Un guardarrail que ha saltado. Es lo mas util para entender una respuesta."""
        limpio = str(cual or "").strip()[:60]
        if limpio and limpio not in self._frenos:
            self._frenos.append(limpio)

    def modelo(self, nombre: str, *, prompt: int = 0, salida: int = 0) -> None:
        """Suma lo gastado. Un turno puede llamar al modelo varias veces."""
        self._modelo = str(nombre or "")[:40] or self._modelo
        self._tokens_entrada += max(0, int(prompt or 0))
        self._tokens_salida += max(0, int(salida or 0))

    def vuelta(self) -> None:
        self._vueltas += 1

    # ─── Consultas en caliente ─────────────────────────────────────────────

    def uso(self, nombre: str) -> bool:
        """Se ha llamado a esa herramienta en este turno.

        Lo usa la vigilancia de calidad para saber si el asistente AFIRMO algo de la
        agenda sin haberla mirado. Antes eso se adivinaba por las palabras.
        """
        return any(t["nombre"] == nombre for t in self._tools)

    @property
    def herramientas(self) -> List[str]:
        return [t["nombre"] for t in self._tools]

    @property
    def frenos(self) -> List[str]:
        return list(self._frenos)

    # ─── Guardar ───────────────────────────────────────────────────────────

    def guardar(self, *, mensaje: str = "", respuesta: str = "") -> None:
        """Escribe la traza. Nunca levanta: es un cuaderno, no la conversacion."""
        try:
            ms = int((time.time() - self._arranque) * 1000)
            with db._get_db_connection() as conexion:
                conexion.execute(
                    "INSERT INTO agent_turns (cliente_id, session_id, canal, mensaje,"
                    " respuesta, tools_json, frenos_json, vueltas, ms, modelo,"
                    " tokens_entrada, tokens_salida, coste_euros, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        self.cliente_id, self.session_id, self.canal,
                        str(mensaje or "")[:500], str(respuesta or "")[:1000],
                        json.dumps(self._tools, ensure_ascii=False)[:4000],
                        json.dumps(self._frenos, ensure_ascii=False)[:600],
                        self._vueltas, ms, self._modelo,
                        self._tokens_entrada, self._tokens_salida,
                        coste_euros(self._modelo, self._tokens_entrada, self._tokens_salida),
                        timeutils._utc_now_iso(),
                    ),
                )
                conexion.commit()
        except Exception as exc:  # noqa: BLE001 - jamas puede tumbar una conversacion
            settings.logger.warning("[trazas] no se pudo guardar el turno: %s", exc)


# ─── Leerlas ───────────────────────────────────────────────────────────────


def del_turno(cliente_id: str, session_id: str, limite: int = 20) -> List[Dict[str, Any]]:
    """Los ultimos turnos de una conversacion, para entender que hizo y por que."""
    with db._get_db_connection() as conexion:
        filas = conexion.execute(
            "SELECT * FROM agent_turns WHERE cliente_id = ? AND session_id = ?"
            " ORDER BY id DESC LIMIT ?",
            (cliente_id, session_id, max(1, min(100, int(limite)))),
        ).fetchall()
    return [_fila_a_dict(f) for f in reversed(filas)]


def _fila_a_dict(fila) -> Dict[str, Any]:
    def _lista(bruto: str) -> Any:
        try:
            return json.loads(bruto or "[]")
        except (ValueError, TypeError):
            return []

    return {
        "cuando": fila["created_at"],
        "canal": fila["canal"],
        "mensaje": fila["mensaje"],
        "respuesta": fila["respuesta"],
        "herramientas": _lista(fila["tools_json"]),
        "frenos": _lista(fila["frenos_json"]),
        "vueltas": fila["vueltas"],
        "ms": fila["ms"],
        "modelo": fila["modelo"],
        "tokens": {"entrada": fila["tokens_entrada"], "salida": fila["tokens_salida"]},
        "coste_euros": fila["coste_euros"],
    }


def uso_por_turno(cliente_id: str, session_id: str) -> List[List[str]]:
    """Las herramientas de cada turno, en orden. Para la vigilancia de calidad."""
    with db._get_db_connection() as conexion:
        filas = conexion.execute(
            "SELECT tools_json FROM agent_turns WHERE cliente_id = ? AND session_id = ?"
            " ORDER BY id",
            (cliente_id, session_id),
        ).fetchall()
    salida: List[List[str]] = []
    for fila in filas:
        try:
            tools = json.loads(fila["tools_json"] or "[]")
        except (ValueError, TypeError):
            tools = []
        salida.append([str(t.get("nombre") or "") for t in tools])
    return salida


def llamadas_por_turno(cliente_id: str, session_id: str) -> List[List[Dict[str, str]]]:
    """Las llamadas de cada turno CON sus argumentos, en orden.

    Con solo el nombre no se distingue avanzar de dar vueltas: preguntar tres veces
    al catalogo mientras la clienta va dando datos es lo normal; preguntarle tres
    veces LO MISMO es un bucle.
    """
    with db._get_db_connection() as conexion:
        filas = conexion.execute(
            "SELECT tools_json FROM agent_turns WHERE cliente_id = ? AND session_id = ?"
            " ORDER BY id",
            (cliente_id, session_id),
        ).fetchall()
    salida: List[List[Dict[str, str]]] = []
    for fila in filas:
        try:
            tools = json.loads(fila["tools_json"] or "[]")
        except (ValueError, TypeError):
            tools = []
        salida.append([{"nombre": str(t.get("nombre") or ""), "args": str(t.get("args") or "")}
                       for t in tools])
    return salida


def resumen_del_dia(cliente_id: str = "", horas: int = 24) -> Dict[str, Any]:
    """Cuanto se ha hablado, cuanto ha costado y que frenos han saltado.

    Sin `cliente_id` sale el total de la casa, que es lo que dice si el saldo de
    OpenAI aguanta el mes.
    """
    desde = (timeutils._utc_now() - timedelta(hours=max(1, int(horas)))).isoformat()
    donde = "created_at >= ?"
    parametros: List[Any] = [desde]
    if cliente_id:
        donde += " AND cliente_id = ?"
        parametros.append(cliente_id)

    with db._get_db_connection() as conexion:
        fila = conexion.execute(
            "SELECT COUNT(*) turnos, COUNT(DISTINCT session_id) conversaciones,"
            " COALESCE(SUM(coste_euros), 0) coste, COALESCE(AVG(ms), 0) ms_medio,"
            " COALESCE(SUM(tokens_entrada + tokens_salida), 0) tokens"
            " FROM agent_turns WHERE " + donde,
            parametros,
        ).fetchone()
        frenos_filas = conexion.execute(
            "SELECT frenos_json FROM agent_turns WHERE " + donde + " AND frenos_json != '[]'",
            parametros,
        ).fetchall()
        por_cliente = conexion.execute(
            "SELECT cliente_id, COUNT(*) turnos, COALESCE(SUM(coste_euros), 0) coste"
            " FROM agent_turns WHERE " + donde + " GROUP BY cliente_id"
            " ORDER BY coste DESC LIMIT 20",
            parametros,
        ).fetchall()

    frenos: Dict[str, int] = {}
    for f in frenos_filas:
        try:
            for freno in json.loads(f["frenos_json"] or "[]"):
                frenos[freno] = frenos.get(freno, 0) + 1
        except (ValueError, TypeError):
            continue

    turnos = int(fila["turnos"] or 0)
    coste = float(fila["coste"] or 0.0)
    return {
        "desde": desde,
        "turnos": turnos,
        "conversaciones": int(fila["conversaciones"] or 0),
        "coste_euros": round(coste, 4),
        "coste_por_conversacion": round(coste / max(1, int(fila["conversaciones"] or 1)), 4),
        "ms_medio": int(fila["ms_medio"] or 0),
        "tokens": int(fila["tokens"] or 0),
        "frenos": sorted(frenos.items(), key=lambda x: -x[1]),
        "por_cliente": [
            {"cliente_id": r["cliente_id"], "turnos": r["turnos"],
             "coste_euros": round(float(r["coste"] or 0), 4)}
            for r in por_cliente
        ],
    }


def limpiar_viejas(dias: int = DIAS_QUE_SE_GUARDAN) -> int:
    """Borra las trazas antiguas: son para depurar, no un archivo historico."""
    corte = (timeutils._utc_now() - timedelta(days=max(1, int(dias)))).isoformat()
    with db._get_db_connection() as conexion:
        cursor = conexion.execute("DELETE FROM agent_turns WHERE created_at < ?", (corte,))
        conexion.commit()
    return cursor.rowcount
