# -*- coding: utf-8 -*-
"""Vigilancia de calidad: encontrar las conversaciones malas sin que las cuente el cliente.

POR QUE EXISTE
--------------
Los ocho fallos del 25 y 26 de agosto de 2026 se descubrieron todos igual: el
duenyo del negocio pegando capturas de WhatsApp. Ninguno lo detecto el sistema.

Eso tiene dos problemas. Uno, que dependemos de que alguien pruebe. Y dos, el
grave: los fallos SILENCIOSOS son invisibles. La clienta a la que se le dijo "a las
10:30 ya tengo una cita" -era mentira, estaba libre para las cinco profesionales-
no se queja: no viene. Ese es el que mas caro sale y el que nunca se ve.

QUE ES Y QUE NO ES
------------------
Es un REPASO de lo que ya paso. Lee conversaciones guardadas y marca las
sospechosas. NO habla con nadie, NO cambia como responde el asistente y NO llama
al modelo: todas las senyales son deterministas y reutilizan los mismos detectores
que usan los guardarrailes. Cuesta cero euros y se puede explicar linea a linea.

COMO ESTA MONTADO
-----------------
Tres capas, separadas a proposito:

1. `Conversacion` -- los datos, sin saber de donde salen.
2. `SENYALES` -- cada una mira una `Conversacion` y devuelve un motivo o "".
   Son funciones PURAS: se prueban sin base de datos y sin red.
3. `cargar_conversaciones` / `revisar_dia` -- lo unico que toca SQLite.

Anyadir una senyal es una entrada mas en `SENYALES`. Si necesita un dato que la
`Conversacion` no tiene, se anyade al CARGADOR, no a la senyal: asi las senyales
siguen siendo puras y el coste de probarlas no sube.

LOS DOS FALLOS QUE PUEDE TENER ESTO
-----------------------------------
* Marcar de mas. Si sale ruido, el negocio deja de mirarlo y no sirve para nada.
  Por eso cada senyal exige un HECHO -contrastar con la agenda, con la cita, con
  la config del negocio-, nunca una impresion sobre como esta redactado.
* Marcar de menos. Por eso la prueba de aceptacion no es que compile: es correrlo
  sobre las conversaciones REALES que ya sabemos que estaban mal.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Dict, List

from backend import db, settings, timeutils

# ─── 1. Los datos ──────────────────────────────────────────────────────────


@dataclass
class Mensaje:
    """Un mensaje de la conversacion. `de_ella` = lo escribio el cliente."""

    de_ella: bool
    texto: str
    cuando: str = ""


@dataclass
class Conversacion:
    """Lo que hace falta para juzgar una conversacion, ya reunido.

    Se construye desde la base de datos (`cargar_conversaciones`) o a mano en los
    tests. Las senyales no saben de SQL: solo miran esto.
    """

    cliente_id: str
    session_id: str
    canal: str = "chat"                                  # chat | whatsapp
    mensajes: List[Mensaje] = field(default_factory=list)
    hubo_cita: bool = False                              # se creo, movio o cancelo
    dias_mencionados: List[str] = field(default_factory=list)
    precios_ocultos: bool = False
    # Las herramientas que se llamaron en cada turno (de `trazas`). Vacio cuando la
    # conversacion es anterior a que existieran las trazas: entonces las senyales
    # que dependen de esto se callan, en vez de inventarse un veredicto.
    herramientas_por_turno: List[List[str]] = field(default_factory=list)

    @property
    def suyos(self) -> List[str]:
        return [m.texto for m in self.mensajes if m.de_ella]

    @property
    def del_asistente(self) -> List[str]:
        return [m.texto for m in self.mensajes if not m.de_ella]

    @property
    def ultimo_del_asistente(self) -> str:
        for mensaje in reversed(self.mensajes):
            if not mensaje.de_ella:
                return mensaje.texto
        return ""


@dataclass
class Hallazgo:
    """Una senyal que ha saltado, con el porque en cristiano."""

    senyal: str
    gravedad: str                                        # alta | media
    motivo: str

    def dict(self) -> Dict[str, str]:
        return {"senyal": self.senyal, "gravedad": self.gravedad, "motivo": self.motivo}


# ─── 2. Las senyales (funciones puras, sin base de datos) ──────────────────


def _repite_lo_mismo(conv: Conversacion) -> str:
    """Dos respuestas seguidas que empiezan igual: para quien lee, un muro."""
    from backend import agent

    previos: List[Dict[str, str]] = []
    for mensaje in conv.mensajes:
        if mensaje.de_ella:
            previos.append({"role": "user", "content": mensaje.texto})
            continue
        if agent._ya_dijo_esto(previos, mensaje.texto):
            return "le contesto dos veces lo mismo, palabra por palabra"
        previos.append({"role": "assistant", "content": mensaje.texto})
    return ""


def _dijo_que_cerramos(conv: Conversacion) -> str:
    """"Estamos cerrados" un dia que se abre: suena a que no hay nada que hacer."""
    from backend import agent, voice

    for texto in conv.del_asistente:
        if not agent._dice_que_cierran(texto):
            continue
        for dia in conv.dias_mencionados:
            if not voice._dia_cerrado(conv.cliente_id, dia):
                return "dijo que estabais cerrados un dia que SI se abre (%s)" % dia
        if not conv.dias_mencionados:
            return "dijo que estabais cerrados; conviene comprobarlo"
    return ""


def _resumen_sin_cita(conv: Conversacion) -> str:
    """Llego al resumen y no acabo en cita: es donde mas se pierde."""
    if conv.hubo_cita:
        return ""
    for texto in conv.del_asistente:
        if "confirmamos la cita" in texto.lower():
            return "llego al resumen de la cita y no quedo nada reservado"
    return ""


def _dio_un_precio(conv: Conversacion) -> str:
    """Una cifra de dinero teniendo el negocio los precios ocultos."""
    if not conv.precios_ocultos:
        return ""
    from backend import agent

    for texto in conv.del_asistente:
        if agent._UNA_CIFRA_DE_DINERO.search(texto or ""):
            return "dio un precio por mensaje y este negocio no los da"
    return ""


def _lo_anuncio_y_no_volvio(conv: Conversacion) -> str:
    """"Un momento, te lo miro" y se acabo: ella espera un mensaje que no llega."""
    from backend import agent

    ultimo = conv.ultimo_del_asistente
    if ultimo and agent._lo_anuncia_en_vez_de_hacerlo(ultimo):
        return "se despidio diciendo que lo miraba y no volvio a escribir"
    return ""


def _larga_y_sin_nada(conv: Conversacion) -> str:
    """Muchos turnos suyos y ni cita ni gestion: o se atasco, o la mareo."""
    if conv.hubo_cita:
        return ""
    if len(conv.suyos) >= 8:
        return "%d mensajes suyos y no acabo en cita" % len(conv.suyos)
    return ""


def _afirmo_sin_mirar(conv: Conversacion) -> str:
    """Dijo algo de la agenda sin haberla consultado. Con hechos, no con palabras.

    Es la version exacta de lo que antes se adivinaba leyendo la frase: aqui se
    sabe que herramientas se llamaron en ese turno. El caso real: "a las 10:30 ya
    tengo una cita" cuando estaba libre para las cinco profesionales -y el turno no
    llamo a `consultar_disponibilidad` ni una vez-.
    """
    if not conv.herramientas_por_turno:
        return ""          # conversacion sin traza: no se afirma nada
    from backend import agent

    respuestas = conv.del_asistente
    for indice, texto in enumerate(respuestas):
        if not agent._afirma_sobre_la_agenda(texto):
            continue
        if indice >= len(conv.herramientas_por_turno):
            continue
        if "consultar_disponibilidad" not in conv.herramientas_por_turno[indice]:
            return "afirmo algo de la agenda sin haberla consultado en ese turno"
    return ""


@dataclass
class Senyal:
    """Una cosa que mirar, con su nombre y su gravedad."""

    id: str
    gravedad: str
    mira: Callable[[Conversacion], str]


SENYALES: List[Senyal] = [
    Senyal("afirmo_sin_mirar", "alta", _afirmo_sin_mirar),
    Senyal("dijo_que_cerramos", "alta", _dijo_que_cerramos),
    Senyal("resumen_sin_cita", "alta", _resumen_sin_cita),
    Senyal("dio_un_precio", "alta", _dio_un_precio),
    Senyal("repite_lo_mismo", "alta", _repite_lo_mismo),
    Senyal("lo_anuncio_y_no_volvio", "media", _lo_anuncio_y_no_volvio),
    Senyal("larga_y_sin_nada", "media", _larga_y_sin_nada),
]


def revisar(conv: Conversacion) -> List[Hallazgo]:
    """Todo lo que se le puede reprochar a esta conversacion. Vacio = bien.

    Una senyal que reviente NO puede tumbar el repaso entero: se registra en el log
    y se sigue con las demas.
    """
    hallazgos: List[Hallazgo] = []
    for senyal in SENYALES:
        try:
            motivo = senyal.mira(conv)
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("[calidad] la senyal %s ha fallado: %s", senyal.id, exc)
            continue
        if motivo:
            hallazgos.append(Hallazgo(senyal.id, senyal.gravedad, motivo))
    return hallazgos


# ─── 3. De donde salen los datos ───────────────────────────────────────────

_UNA_FECHA = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def _dias_mencionados(mensajes: List[Mensaje]) -> List[str]:
    """Los dias de los que se hablo, para poder contrastar lo que se dijo."""
    dias: List[str] = []
    for mensaje in mensajes:
        for encontrado in _UNA_FECHA.findall(mensaje.texto or ""):
            if encontrado not in dias:
                dias.append(encontrado)
    return dias[:5]


def _hubo_gestion(cliente_id: str, origen: str) -> bool:
    """Esa conversacion acabo tocando la agenda.

    Por WhatsApp la conversacion ES el telefono, asi que se mira si hay alguna cita
    suya creada en las ultimas 24 h. Por el chat web no hay telefono con el que
    cruzar, asi que no se afirma nada: se prefiere marcar de mas antes que dar por
    buena una conversacion que acabo en nada.
    """
    telefono = origen.split(":", 1)[1].strip() if origen.startswith("whatsapp:") else ""
    if len(telefono) < 6:
        return False
    with db._get_db_connection() as conexion:
        fila = conexion.execute(
            "SELECT 1 FROM bookings WHERE cliente_id = ? AND telefono LIKE ?"
            " AND created_at >= ? LIMIT 1",
            (cliente_id, "%" + telefono[-9:],
             (timeutils._utc_now() - timedelta(days=1)).isoformat()),
        ).fetchone()
    return fila is not None


def _herramientas_por_turno(cliente_id: str, session_id: str) -> List[List[str]]:
    """Lo que hizo el asistente en cada turno. Vacio si no hay traza."""
    try:
        from backend import trazas

        return trazas.uso_por_turno(cliente_id, session_id)
    except Exception as exc:  # noqa: BLE001 - sin traza se revisa igual, con menos
        settings.logger.warning("[calidad] sin trazas de %s: %s", session_id, exc)
        return []


def cargar_conversaciones(cliente_id: str, desde: str, hasta: str = "") -> List[Conversacion]:
    """Las conversaciones guardadas de ese negocio entre dos fechas (ISO)."""
    from backend import booking

    hasta = hasta or timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        sesiones = conexion.execute(
            "SELECT id, origin FROM chat_sessions WHERE cliente_id = ?"
            " AND last_message_at >= ? AND last_message_at <= ?"
            " ORDER BY last_message_at DESC LIMIT 500",
            (cliente_id, desde, hasta),
        ).fetchall()

    try:
        ocultos = booking.precios_ocultos(cliente_id)
    except Exception:  # noqa: BLE001 - el repaso nunca puede romperse por la config
        ocultos = False

    salida: List[Conversacion] = []
    for sesion in sesiones:
        session_id = str(sesion["id"])
        with db._get_db_connection() as conexion:
            filas = conexion.execute(
                "SELECT role, content, created_at FROM chat_messages"
                " WHERE cliente_id = ? AND session_id = ? ORDER BY id",
                (cliente_id, session_id),
            ).fetchall()
        if not filas:
            continue
        origen = str(sesion["origin"] or "")
        mensajes = [
            Mensaje(de_ella=str(fila["role"]) == "user",
                    texto=str(fila["content"] or ""),
                    cuando=str(fila["created_at"] or ""))
            for fila in filas
        ]
        salida.append(Conversacion(
            cliente_id=cliente_id,
            session_id=session_id,
            canal="whatsapp" if origen.startswith("whatsapp") else "chat",
            mensajes=mensajes,
            precios_ocultos=ocultos,
            dias_mencionados=_dias_mencionados(mensajes),
            hubo_cita=_hubo_gestion(cliente_id, origen),
            herramientas_por_turno=_herramientas_por_turno(cliente_id, session_id),
        ))
    return salida


# ─── 4. El repaso y lo que queda por atender ───────────────────────────────


def revisar_dia(cliente_id: str, desde: str = "", guardar: bool = True) -> Dict[str, Any]:
    """Repasa lo hablado desde `desde` (por defecto, 24 h) y devuelve el resumen."""
    desde = desde or (timeutils._utc_now() - timedelta(days=1)).isoformat()
    conversaciones = cargar_conversaciones(cliente_id, desde)
    marcadas: List[Dict[str, Any]] = []
    for conv in conversaciones:
        hallazgos = revisar(conv)
        if not hallazgos:
            continue
        marcadas.append({
            "session_id": conv.session_id,
            "canal": conv.canal,
            "mensajes": len(conv.mensajes),
            "senyales": [h.dict() for h in hallazgos],
        })
        if guardar:
            _guardar_revision(cliente_id, conv, hallazgos)
    return {
        "cliente_id": cliente_id,
        "desde": desde,
        "revisadas": len(conversaciones),
        "marcadas": len(marcadas),
        "items": marcadas,
    }


def _guardar_revision(cliente_id: str, conv: Conversacion, hallazgos: List[Hallazgo]) -> None:
    """Guarda el hallazgo SIN perder si el negocio ya la habia dado por atendida."""
    ahora = timeutils._utc_now_iso()
    gravedad = "alta" if any(h.gravedad == "alta" for h in hallazgos) else "media"
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO conversation_reviews"
            " (cliente_id, session_id, canal, senyales_json, gravedad, atendida, created_at)"
            " VALUES (?, ?, ?, ?, ?, 0, ?)"
            " ON CONFLICT(cliente_id, session_id) DO UPDATE SET"
            "   canal = excluded.canal,"
            "   senyales_json = excluded.senyales_json,"
            "   gravedad = excluded.gravedad,"
            "   created_at = excluded.created_at",
            (cliente_id, conv.session_id, conv.canal,
             json.dumps([h.dict() for h in hallazgos], ensure_ascii=False),
             gravedad, ahora),
        )
        conexion.commit()


def pendientes(cliente_id: str, limite: int = 50) -> List[Dict[str, Any]]:
    """Lo marcado y aun sin atender, lo mas grave primero."""
    with db._get_db_connection() as conexion:
        filas = conexion.execute(
            "SELECT session_id, canal, senyales_json, gravedad, created_at"
            " FROM conversation_reviews WHERE cliente_id = ? AND atendida = 0"
            " ORDER BY (gravedad = 'alta') DESC, created_at DESC LIMIT ?",
            (cliente_id, max(1, min(200, int(limite)))),
        ).fetchall()
    salida: List[Dict[str, Any]] = []
    for fila in filas:
        try:
            senyales = json.loads(fila["senyales_json"] or "[]")
        except (ValueError, TypeError):
            senyales = []
        salida.append({
            "session_id": fila["session_id"],
            "canal": fila["canal"],
            "gravedad": fila["gravedad"],
            "senyales": senyales,
            "cuando": fila["created_at"],
        })
    return salida


def marcar_atendida(cliente_id: str, session_id: str) -> bool:
    """El negocio ya la ha mirado: deja de salir en la lista."""
    with db._get_db_connection() as conexion:
        cursor = conexion.execute(
            "UPDATE conversation_reviews SET atendida = 1"
            " WHERE cliente_id = ? AND session_id = ?",
            (cliente_id, session_id),
        )
        conexion.commit()
    return cursor.rowcount > 0
