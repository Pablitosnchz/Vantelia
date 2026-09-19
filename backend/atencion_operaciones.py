"""Tickets y admisiones duraderas; sin transportes ni reintentos de negocio.

Crear el ticket ANTES de preparar una respuesta. Sus fechas UTC y evento opaco
proceden del llamador; no se deduce un TTL ni se rejuvenece un evento repetido.
Una supresión no es una entrega ni un fallo de transporte.

Solo `ejecutar_red=True` permite iniciar la petición, con los mismos bytes que
se admitieron. La transacción ya terminó al retornar. El resto de respuestas
jamás autoriza red. Caídas, rechazos y resultados desconocidos no liberan la
identidad para repetir; notice_deliveries conserva sus propias decisiones.

El llamador autentica al tenant. No existe una excepción humana en el payload.
El owner_token solo se entrega al ganador y permite registrar su resultado,
incluida una reconciliación de desconocido a conocido, aun estando en pausa.
La consulta no recupera ese token: perder al proceso no acredita reconciliación
automática; la operación queda conservadora hasta una intervención con evidencia.
`puede_preparar` tampoco reclama un worker: las fronteras conservan la deduplicación
de mensajes y coste. Esta primitiva solo concede una admisión única de red.
"""
from contextlib import closing
import hashlib
import re
import sqlite3
import uuid

from backend import atencion, db, timeutils


_ATENCION_EVENTO_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_ATENCION_TOKEN_RE = re.compile(r"[a-f0-9]{32}\Z")
_ATENCION_CANAL_RE = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
_ATENCION_HASH_RE = re.compile(r"[a-f0-9]{64}\Z")
_ATENCION_SUPRESIONES = ("pausada", "version_obsoleta", "vencido", "evento_anterior")


class AtencionIdentidadEnConflicto(RuntimeError):
    """Una identidad persistida no puede cambiar de contenido o resultado conocido."""


class AtencionOperacionNoEncontrada(RuntimeError):
    """No existe esa operación para el tenant; no revela si pertenece a otro."""


class AtencionPropietarioInvalido(RuntimeError):
    """Solo el propietario de la admisión puede registrar su resultado."""


def _fecha_operacion_atencion(valor):
    if not isinstance(valor, str):
        raise ValueError("La fecha debe ser un instante UTC explícito.")
    fecha = timeutils._from_utc_iso(valor)
    if fecha is None or fecha.utcoffset() is None or fecha.utcoffset().total_seconds() != 0:
        raise ValueError("La fecha debe ser un instante UTC explícito.")
    return fecha


def _validar_referencia_atencion(valor, patron, nombre):
    if not isinstance(valor, str) or not patron.fullmatch(valor):
        raise ValueError("Referencia de %s no válida." % nombre)


def _validar_fragmento_atencion(fragmento):
    if type(fragmento) is not int or not 0 <= fragmento <= 2147483647:
        raise ValueError("Fragmento de atención no válido.")


def _ticket_operacion_atencion(row):
    if row is None:
        raise AtencionOperacionNoEncontrada("No existe el ticket de atención.")
    ticket = dict(row)
    try:
        atencion._validar_cliente_atencion(ticket["cliente_id"])
        _validar_referencia_atencion(ticket["evento_id"], _ATENCION_EVENTO_RE, "evento")
        _validar_referencia_atencion(ticket["ticket_id"], _ATENCION_TOKEN_RE, "ticket")
        if type(ticket["version"]) is not int or not 0 <= ticket["version"] <= atencion._ATENCION_VERSION_MAX:
            raise ValueError("Versión de ticket inválida.")
        evento = _fecha_operacion_atencion(ticket["event_at"])
        vence = _fecha_operacion_atencion(ticket["expires_at"])
        creado = _fecha_operacion_atencion(ticket["created_at"])
        if vence <= evento or evento > creado:
            raise ValueError("Vigencia de ticket inválida.")
        if ticket["estado"] == "vigente":
            if ticket["motivo"] or ticket["suprimido_at"]:
                raise ValueError("Supresión inconsistente.")
        elif ticket["estado"] == "suprimido":
            if ticket["motivo"] not in _ATENCION_SUPRESIONES:
                raise ValueError("Supresión desconocida.")
            _fecha_operacion_atencion(ticket["suprimido_at"])
        else:
            raise ValueError("Estado de ticket inválido.")
    except (ValueError, KeyError) as exc:
        atencion._ATENCION_LOG.error("atencion_ticket_invalido")
        raise atencion.AtencionNoDisponible("No se puede verificar el ticket de atención.") from exc
    return ticket


def _envio_operacion_atencion(row):
    if row is None:
        raise AtencionOperacionNoEncontrada("No existe la admisión de atención.")
    envio = dict(row)
    try:
        atencion._validar_cliente_atencion(envio["cliente_id"])
        _validar_referencia_atencion(envio["ticket_id"], _ATENCION_TOKEN_RE, "ticket")
        _validar_referencia_atencion(envio["canal"], _ATENCION_CANAL_RE, "canal")
        _validar_fragmento_atencion(envio["fragmento"])
        _validar_referencia_atencion(envio["payload_hash"], _ATENCION_HASH_RE, "huella")
        _fecha_operacion_atencion(envio["created_at"])
        if envio["estado"] == "suprimido":
            if envio["owner_token"] or envio["resultado_at"] or envio["motivo"] not in _ATENCION_SUPRESIONES:
                raise ValueError("Supresión de envío inconsistente.")
        elif envio["estado"] in ("en_transito", "aceptado", "rechazado", "desconocido"):
            _validar_referencia_atencion(envio["owner_token"], _ATENCION_TOKEN_RE, "propietario")
            if envio["motivo"]:
                raise ValueError("Un envío admitido no contiene una supresión.")
            if envio["estado"] == "en_transito":
                if envio["resultado_at"]:
                    raise ValueError("Resultado prematuro.")
            else:
                _fecha_operacion_atencion(envio["resultado_at"])
        else:
            raise ValueError("Estado de envío inválido.")
    except (ValueError, KeyError) as exc:
        atencion._ATENCION_LOG.error("atencion_envio_invalido")
        raise atencion.AtencionNoDisponible("No se puede verificar la admisión de atención.") from exc
    return envio


def _buscar_ticket_atencion(connection, cliente_id, ticket_id):
    return _ticket_operacion_atencion(connection.execute(
        "SELECT * FROM client_attention_tickets WHERE cliente_id=? AND ticket_id=?",
        (cliente_id, ticket_id)).fetchone())


def _motivo_ticket_atencion(ticket, autoridad, ahora):
    if ticket["estado"] == "suprimido":
        return ticket["motivo"]
    if autoridad["estado"] == "pausada":
        return "pausada"
    if ticket["version"] != autoridad["version"]:
        return "version_obsoleta"
    if ahora >= _fecha_operacion_atencion(ticket["expires_at"]):
        return "vencido"
    # Igualdad no acredita posterioridad: puede ser un evento de la pausa,
    # incluso cuando reaparece con otra identidad después de reactivar.
    if (autoridad["fecha_efectiva"] is not None
            and _fecha_operacion_atencion(ticket["event_at"]) <= _fecha_operacion_atencion(autoridad["fecha_efectiva"])):
        return "evento_anterior"
    return ""


def _suprimir_ticket_atencion(connection, ticket, motivo, ahora):
    if motivo and ticket["estado"] != "suprimido":
        connection.execute(
            "UPDATE client_attention_tickets SET estado='suprimido',motivo=?,suprimido_at=? "
            "WHERE cliente_id=? AND ticket_id=?", (motivo, ahora, ticket["cliente_id"], ticket["ticket_id"]))
        ticket.update(estado="suprimido", motivo=motivo, suprimido_at=ahora)
    return ticket


def _respuesta_envio_atencion(envio, ejecutar_red=False):
    respuesta = dict(envio)
    token = respuesta.pop("owner_token")
    respuesta["ejecutar_red"] = ejecutar_red
    if ejecutar_red:
        respuesta["owner_token"] = token
    return respuesta


def crear_ticket_atencion(cliente_id, evento_id, *, event_at, expires_at):
    """Antes de preparar: captura versión fresca sin renovar nunca el evento."""
    atencion._validar_cliente_atencion(cliente_id)
    _validar_referencia_atencion(evento_id, _ATENCION_EVENTO_RE, "evento")
    evento, vence = _fecha_operacion_atencion(event_at), _fecha_operacion_atencion(expires_at)
    if vence <= evento:
        raise ValueError("La vigencia debe terminar después del evento.")
    event_at, expires_at = timeutils._to_utc_iso(evento), timeutils._to_utc_iso(vence)
    try:
        with closing(db._get_db_connection()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            autoridad = atencion._leer_atencion_en_transaccion(connection, cliente_id)
            ahora = timeutils._utc_now()
            if evento > ahora:
                raise ValueError("El evento no puede proceder del futuro.")
            ahora_iso = timeutils._to_utc_iso(ahora)
            row = connection.execute(
                "SELECT * FROM client_attention_tickets WHERE cliente_id=? AND evento_id=?",
                (cliente_id, evento_id)).fetchone()
            if row is None:
                ticket = {"cliente_id": cliente_id, "evento_id": evento_id, "ticket_id": uuid.uuid4().hex,
                          "version": autoridad["version"], "event_at": event_at, "expires_at": expires_at,
                          "created_at": ahora_iso, "estado": "vigente", "motivo": "", "suprimido_at": ""}
                motivo = _motivo_ticket_atencion(ticket, autoridad, ahora)
                if motivo:
                    ticket.update(estado="suprimido", motivo=motivo, suprimido_at=ahora_iso)
                connection.execute(
                    "INSERT INTO client_attention_tickets "
                    "(cliente_id,evento_id,ticket_id,version,event_at,expires_at,created_at,estado,motivo,suprimido_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", tuple(ticket[k] for k in (
                        "cliente_id", "evento_id", "ticket_id", "version", "event_at", "expires_at",
                        "created_at", "estado", "motivo", "suprimido_at")))
            else:
                ticket = _ticket_operacion_atencion(row)
                if ticket["event_at"] != event_at or ticket["expires_at"] != expires_at:
                    raise AtencionIdentidadEnConflicto("El evento ya tiene otras fechas de vigencia.")
                _suprimir_ticket_atencion(connection, ticket, _motivo_ticket_atencion(ticket, autoridad, ahora), ahora_iso)
        ticket["puede_preparar"] = ticket["estado"] == "vigente"
        return ticket
    except sqlite3.Error as exc:
        atencion._ATENCION_LOG.error("atencion_ticket_fallido tipo=%s", type(exc).__name__)
        raise atencion.AtencionNoDisponible("No se puede registrar el ticket de atención.") from exc


def admitir_envio_atencion(cliente_id, ticket_id, canal, fragmento, *, payload):
    """Admite una sola petición por fragmento. Repetir nunca permite red."""
    atencion._validar_cliente_atencion(cliente_id)
    _validar_referencia_atencion(ticket_id, _ATENCION_TOKEN_RE, "ticket")
    _validar_referencia_atencion(canal, _ATENCION_CANAL_RE, "canal")
    _validar_fragmento_atencion(fragmento)
    if not isinstance(payload, bytes):
        raise ValueError("El payload debe contener los bytes exactos del envío.")
    huella = hashlib.sha256(payload).hexdigest()
    identidad = (cliente_id, ticket_id, canal, fragmento)
    try:
        with closing(db._get_db_connection()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            autoridad = atencion._leer_atencion_en_transaccion(connection, cliente_id)
            ticket = _buscar_ticket_atencion(connection, cliente_id, ticket_id)
            row = connection.execute(
                "SELECT * FROM client_attention_sends WHERE cliente_id=? AND ticket_id=? AND canal=? AND fragmento=?",
                identidad).fetchone()
            if row is not None:
                envio = _envio_operacion_atencion(row)
                if envio["payload_hash"] != huella:
                    raise AtencionIdentidadEnConflicto("El fragmento ya tiene otro payload.")
                return _respuesta_envio_atencion(envio)
            ahora = timeutils._utc_now()
            ahora_iso = timeutils._to_utc_iso(ahora)
            motivo = _motivo_ticket_atencion(ticket, autoridad, ahora)
            _suprimir_ticket_atencion(connection, ticket, motivo, ahora_iso)
            envio = {"cliente_id": cliente_id, "ticket_id": ticket_id, "canal": canal, "fragmento": fragmento,
                     "payload_hash": huella, "estado": "suprimido" if motivo else "en_transito",
                     "owner_token": "" if motivo else uuid.uuid4().hex, "motivo": motivo,
                     "created_at": ahora_iso, "resultado_at": ""}
            connection.execute(
                "INSERT INTO client_attention_sends "
                "(cliente_id,ticket_id,canal,fragmento,payload_hash,estado,owner_token,motivo,created_at,resultado_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", tuple(envio[k] for k in (
                    "cliente_id", "ticket_id", "canal", "fragmento", "payload_hash", "estado",
                    "owner_token", "motivo", "created_at", "resultado_at")))
        return _respuesta_envio_atencion(envio, ejecutar_red=not motivo)
    except sqlite3.Error as exc:
        atencion._ATENCION_LOG.error("atencion_admision_fallida tipo=%s", type(exc).__name__)
        raise atencion.AtencionNoDisponible("No se puede admitir el envío de atención.") from exc


def registrar_resultado_atencion(cliente_id, ticket_id, canal, fragmento, *, owner_token, resultado):
    """Registra el resultado real aun durante la pausa. Nunca concede otra red."""
    atencion._validar_cliente_atencion(cliente_id)
    _validar_referencia_atencion(ticket_id, _ATENCION_TOKEN_RE, "ticket")
    _validar_referencia_atencion(canal, _ATENCION_CANAL_RE, "canal")
    _validar_fragmento_atencion(fragmento)
    _validar_referencia_atencion(owner_token, _ATENCION_TOKEN_RE, "propietario")
    if not isinstance(resultado, str) or resultado not in ("aceptado", "rechazado", "desconocido"):
        raise ValueError("Resultado de atención no válido.")
    identidad = (cliente_id, ticket_id, canal, fragmento)
    try:
        with closing(db._get_db_connection()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            _buscar_ticket_atencion(connection, cliente_id, ticket_id)
            envio = _envio_operacion_atencion(connection.execute(
                "SELECT * FROM client_attention_sends WHERE cliente_id=? AND ticket_id=? AND canal=? AND fragmento=?",
                identidad).fetchone())
            if envio["estado"] == "suprimido" or envio["owner_token"] != owner_token:
                raise AtencionPropietarioInvalido("No es el propietario de esta admisión.")
            if envio["estado"] == resultado or (
                    envio["estado"] in ("aceptado", "rechazado") and resultado == "desconocido"):
                return _respuesta_envio_atencion(envio)
            if envio["estado"] in ("aceptado", "rechazado"):
                raise AtencionIdentidadEnConflicto("La admisión ya tiene otro resultado conocido.")
            ahora = timeutils._to_utc_iso(timeutils._utc_now())
            connection.execute(
                "UPDATE client_attention_sends SET estado=?,resultado_at=? "
                "WHERE cliente_id=? AND ticket_id=? AND canal=? AND fragmento=? AND owner_token=?",
                (resultado, ahora) + identidad + (owner_token,))
            envio.update(estado=resultado, resultado_at=ahora)
        return _respuesta_envio_atencion(envio)
    except sqlite3.Error as exc:
        atencion._ATENCION_LOG.error("atencion_resultado_fallido tipo=%s", type(exc).__name__)
        raise atencion.AtencionNoDisponible("No se puede registrar el resultado de atención.") from exc


def consultar_envios_atencion(cliente_id, *, ticket_id=None):
    """Diario técnico del tenant, incluidos en tránsito/desconocidos; sin tokens."""
    atencion._validar_cliente_atencion(cliente_id)
    if ticket_id is not None:
        _validar_referencia_atencion(ticket_id, _ATENCION_TOKEN_RE, "ticket")
    try:
        with closing(db._get_db_connection()) as connection, connection:
            # Snapshot coherente de tickets y envíos, sin reservar el escritor.
            connection.execute("BEGIN")
            if ticket_id is not None:
                _buscar_ticket_atencion(connection, cliente_id, ticket_id)
            query = "SELECT * FROM client_attention_sends WHERE cliente_id=?"
            args = (cliente_id,)
            if ticket_id is not None:
                query += " AND ticket_id=?"
                args += (ticket_id,)
            envios = []
            for row in connection.execute(query + " ORDER BY created_at,ticket_id,canal,fragmento", args):
                _buscar_ticket_atencion(connection, cliente_id, row["ticket_id"])
                envios.append(_respuesta_envio_atencion(_envio_operacion_atencion(row)))
        return envios
    except sqlite3.Error as exc:
        atencion._ATENCION_LOG.error("atencion_diario_fallido tipo=%s", type(exc).__name__)
        raise atencion.AtencionNoDisponible("No se puede consultar el diario de atención.") from exc
