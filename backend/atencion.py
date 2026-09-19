"""Autoridad persistida de atención automática por tenant.

Esta fase solo conserva el estado; los canales todavía no consultan esta
autoridad. Una lectura es una foto, nunca una admisión de envío. La futura
admisión deberá leer y registrar su versión en una misma transacción.

El llamador resuelve el tenant y autentica al actor. Aquí no se copian reglas,
credenciales ni configuración de canales. Motivo es un código técnico y actor
una referencia interna: no se admiten textos libres, nombres ni correos.
"""
from contextlib import closing
import json
import logging
import re
import sqlite3

from backend import db, settings, timeutils


_ATENCION_LOG = logging.getLogger(__name__)
_ATENCION_MOTIVO_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_ATENCION_ACTOR_RE = re.compile(r"usr_[A-Za-z0-9_-]{16}\Z")
_ATENCION_VERSION_MAX = 9223372036854775807


class AtencionNoDisponible(RuntimeError):
    """No se ha podido conocer o persistir el estado; no autoriza atención."""


class AtencionVersionObsoleta(RuntimeError):
    """El llamador debe releer el estado antes de decidir otra transición."""

    def __init__(self, version_actual):
        self.version_actual = version_actual
        super().__init__("La versión de atención ha cambiado.")


def _validar_cliente_atencion(cliente_id):
    if not isinstance(cliente_id, str) or not settings.CLIENT_ID_PATTERN.fullmatch(cliente_id):
        raise ValueError("Identificador de tenant no válido.")


def _validar_datos_atencion(estado, version, motivo, actor):
    if not isinstance(estado, str) or estado not in ("activa", "pausada"):
        raise ValueError("Estado de atención no válido.")
    if type(version) is not int or not 0 <= version <= _ATENCION_VERSION_MAX:
        raise ValueError("Versión de atención no válida.")
    if not isinstance(motivo, str) or not _ATENCION_MOTIVO_RE.fullmatch(motivo):
        raise ValueError("El motivo debe ser un código técnico.")
    if not isinstance(actor, str) or not (
            actor == "sistema" or _ATENCION_ACTOR_RE.fullmatch(actor)):
        raise ValueError("El actor debe ser sistema o una referencia interna usr_.")


def _leer_atencion_en_transaccion(connection, cliente_id):
    """Sin caché ni conexión propia, para compartir la futura admisión atómica."""
    row = connection.execute(
        "SELECT cliente_id,estado,version,fecha_efectiva,motivo,actor "
        "FROM client_attention_state WHERE cliente_id=?", (cliente_id,)).fetchone()
    if row is None:
        return {"cliente_id": cliente_id, "estado": "activa", "version": 0,
                "fecha_efectiva": None, "motivo": None, "actor": None}
    snapshot = dict(row)
    try:
        _validar_datos_atencion(row["estado"], row["version"], row["motivo"], row["actor"])
        fecha = timeutils._from_utc_iso(row["fecha_efectiva"])
        if (row["version"] == 0 or not isinstance(row["fecha_efectiva"], str)
                or not row["fecha_efectiva"].endswith("Z")
                or fecha is None or fecha.utcoffset() is None
                or fecha.utcoffset().total_seconds() != 0):
            raise ValueError("Metadatos de atención inválidos.")
    except ValueError as exc:
        _ATENCION_LOG.error("atencion_estado_invalido")
        raise AtencionNoDisponible("No se puede verificar el estado de atención.") from exc
    return snapshot


def leer_atencion(cliente_id):
    """Lee el estado vigente. Ausencia de fila es activa v0; error nunca lo es."""
    _validar_cliente_atencion(cliente_id)
    try:
        with closing(db._get_db_connection()) as connection:
            return _leer_atencion_en_transaccion(connection, cliente_id)
    except sqlite3.Error as exc:
        _ATENCION_LOG.error("atencion_lectura_fallida tipo=%s", type(exc).__name__)
        raise AtencionNoDisponible("No se puede verificar el estado de atención.") from exc


def cambiar_atencion(cliente_id, estado, *, version_esperada, motivo, actor):
    """Transición CAS y auditoría atómicas; no expone un escritor HTTP.

    Incluso el mismo estado exige versión vigente. Un no-op conserva todos los
    metadatos y no escribe auditoría. La fecha efectiva procede del reloj común;
    esta operación es inmediata, no programa una pausa futura.
    """
    _validar_cliente_atencion(cliente_id)
    _validar_datos_atencion(estado, version_esperada, motivo, actor)
    try:
        with closing(db._get_db_connection()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            anterior = _leer_atencion_en_transaccion(connection, cliente_id)
            if anterior["version"] != version_esperada:
                raise AtencionVersionObsoleta(anterior["version"])
            if anterior["estado"] == estado:
                return anterior
            if version_esperada == _ATENCION_VERSION_MAX:
                raise AtencionNoDisponible("Se ha agotado la versión de atención.")
            ahora = timeutils._utc_now_iso()
            siguiente = {"cliente_id": cliente_id, "estado": estado,
                         "version": version_esperada + 1, "fecha_efectiva": ahora,
                         "motivo": motivo, "actor": actor}
            connection.execute(
                "INSERT INTO client_attention_state "
                "(cliente_id,estado,version,fecha_efectiva,motivo,actor) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(cliente_id) DO UPDATE SET estado=excluded.estado, "
                "version=excluded.version, fecha_efectiva=excluded.fecha_efectiva, "
                "motivo=excluded.motivo, actor=excluded.actor",
                (cliente_id, estado, siguiente["version"], ahora, motivo, actor))
            # El diario ya existente se escribe con ESTA conexión: el helper
            # security._channel_audit abriría otra y perdería la atomicidad.
            # Solo hechos técnicos; ningún dato de una conversación o clienta.
            detalle = json.dumps({"estado_anterior": anterior["estado"],
                                  "estado": estado, "version_anterior": version_esperada,
                                  "version": siguiente["version"],
                                  "motivo": motivo, "actor": actor}, sort_keys=True)
            connection.execute(
                "INSERT INTO client_channel_audit "
                "(cliente_id,channel,event_type,provider,success,detail,created_at) "
                "VALUES (?,'atencion','atencion_transicion','',1,?,?)",
                (cliente_id, detalle, ahora))
        return siguiente
    except sqlite3.Error as exc:
        _ATENCION_LOG.error("atencion_transicion_fallida tipo=%s", type(exc).__name__)
        raise AtencionNoDisponible("No se puede persistir el estado de atención.") from exc
