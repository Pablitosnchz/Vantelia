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
de mensajes y coste. En el diario común, tipo=envio mantiene ticket/canal/fragmento;
tipo=reserva usa tenant/acción/clave estable incluso al capturar otro ticket.
Solo `ejecutar_operacion=True` concede el primer efecto de esa operación.
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
_ATENCION_RESULT_REF_RE = re.compile(r"bk_[A-Za-z0-9_-]{1,100}\Z")
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


def _validar_identidad_operacion_atencion(tipo, canal, fragmento, clave_intento):
    _validar_fragmento_atencion(fragmento)
    if tipo == "envio":
        _validar_referencia_atencion(canal, _ATENCION_CANAL_RE, "canal")
        if clave_intento != "":
            raise ValueError("Un envío se identifica por su fragmento.")
    elif tipo == "reserva":
        if canal not in ("crear", "cancelar", "mover") or fragmento != 0:
            raise ValueError("Acción de reserva no válida.")
        _validar_referencia_atencion(clave_intento, _ATENCION_EVENTO_RE, "intento")
    else:
        raise ValueError("Tipo de operación de atención no válido.")


def _validar_resultado_referencia_atencion(tipo, estado, referencia):
    if not isinstance(referencia, str):
        raise ValueError("La referencia de resultado debe ser texto.")
    if tipo == "reserva" and estado == "aceptado":
        _validar_referencia_atencion(referencia, _ATENCION_RESULT_REF_RE, "resultado")
    elif referencia != "":
        raise ValueError("Solo una reserva aceptada tiene referencia de resultado.")


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
        _validar_identidad_operacion_atencion(envio["tipo"], envio["canal"],
                                             envio["fragmento"], envio["clave_intento"])
        _validar_resultado_referencia_atencion(envio["tipo"], envio["estado"], envio["result_ref"])
        _validar_referencia_atencion(envio["payload_hash"], _ATENCION_HASH_RE, "huella")
        _validar_referencia_atencion(envio["request_hash"], _ATENCION_HASH_RE, "solicitud")
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


def comprobar_ticket_atencion(cliente_id, ticket_id):
    """Foto coherente previa a preparar; nunca reclama ni renueva un intento."""
    atencion._validar_cliente_atencion(cliente_id)
    _validar_referencia_atencion(ticket_id, _ATENCION_TOKEN_RE, "ticket")
    try:
        with closing(db._get_db_connection()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            autoridad = atencion._leer_atencion_en_transaccion(connection, cliente_id)
            ticket = _buscar_ticket_atencion(connection, cliente_id, ticket_id)
            ahora = timeutils._utc_now()
            motivo = _motivo_ticket_atencion(ticket, autoridad, ahora)
            _suprimir_ticket_atencion(connection, ticket, motivo, timeutils._to_utc_iso(ahora))
        return dict(ticket, puede_preparar=not motivo, motivo_actual=motivo)
    except sqlite3.Error as exc:
        raise atencion.AtencionNoDisponible("No se puede verificar el ticket de atención.") from exc


def _respuesta_operacion_atencion(operacion, ejecutar=False):
    respuesta = dict(operacion)
    token = respuesta.pop("owner_token")
    respuesta["ejecutar_operacion"] = ejecutar
    if ejecutar:
        respuesta["owner_token"] = token
    return respuesta


def _compat_respuesta_envio_atencion(respuesta):
    respuesta = dict(respuesta)
    respuesta["ejecutar_red"] = respuesta.pop("ejecutar_operacion")
    for nombre in ("tipo", "clave_intento", "result_ref", "request_hash"):
        respuesta.pop(nombre)
    return respuesta


def _buscar_identidad_operacion_atencion(connection, identidad):
    cliente_id, ticket_id, tipo, canal, fragmento, clave_intento = identidad
    if tipo == "reserva":
        # El intento de una mutación confirmada sobrevive a la captura de otro
        # turno. El ticket original sigue siendo su vínculo de admisión.
        return connection.execute(
            "SELECT * FROM client_attention_operations WHERE cliente_id=? AND tipo='reserva' "
            "AND canal=? AND clave_intento=?", (cliente_id, canal, clave_intento)).fetchone()
    return connection.execute(
        "SELECT * FROM client_attention_operations WHERE cliente_id=? AND ticket_id=? "
        "AND tipo=? AND canal=? AND fragmento=? AND clave_intento=?", identidad).fetchone()


def consultar_intento_reserva_atencion(cliente_id, ticket_id, accion, clave_intento):
    """Evidencia original sin permiso, incluso con otro ticket propio ya inválido."""
    atencion._validar_cliente_atencion(cliente_id)
    _validar_referencia_atencion(ticket_id, _ATENCION_TOKEN_RE, "ticket")
    _validar_identidad_operacion_atencion("reserva", accion, 0, clave_intento)
    try:
        with closing(db._get_db_connection()) as connection, connection:
            connection.execute("BEGIN")
            _buscar_ticket_atencion(connection, cliente_id, ticket_id)
            row = _buscar_identidad_operacion_atencion(connection,
                (cliente_id, ticket_id, "reserva", accion, 0, clave_intento))
            if row is None:
                return None
            _buscar_ticket_atencion(connection, cliente_id, row["ticket_id"])
            return _respuesta_operacion_atencion(_envio_operacion_atencion(row))
    except sqlite3.Error as exc:
        raise atencion.AtencionNoDisponible("No se puede consultar el intento de reserva.") from exc


def admitir_operacion_atencion(cliente_id, ticket_id, *, tipo, canal, fragmento=0,
                               clave_intento="", payload, solicitud=None):
    """Único permiso duradero para envío o reserva; solo el ganador ejecuta."""
    atencion._validar_cliente_atencion(cliente_id)
    _validar_referencia_atencion(ticket_id, _ATENCION_TOKEN_RE, "ticket")
    _validar_identidad_operacion_atencion(tipo, canal, fragmento, clave_intento)
    if not isinstance(payload, bytes):
        raise ValueError("El payload debe contener los bytes efectivos de la operación.")
    if solicitud is not None and not isinstance(solicitud, bytes):
        raise ValueError("La solicitud debe ser bytes normalizados por el núcleo.")
    huella = hashlib.sha256(payload).hexdigest()
    huella_solicitud = hashlib.sha256(payload if solicitud is None else solicitud).hexdigest()
    identidad = (cliente_id, ticket_id, tipo, canal, fragmento, clave_intento)
    try:
        with closing(db._get_db_connection()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            autoridad = atencion._leer_atencion_en_transaccion(connection, cliente_id)
            ticket = _buscar_ticket_atencion(connection, cliente_id, ticket_id)
            row = _buscar_identidad_operacion_atencion(connection, identidad)
            if row is not None:
                operacion = _envio_operacion_atencion(row)
                _buscar_ticket_atencion(connection, cliente_id, operacion["ticket_id"])
                if operacion["payload_hash"] != huella or operacion["request_hash"] != huella_solicitud:
                    raise AtencionIdentidadEnConflicto("La operación ya tiene otros datos efectivos.")
                return _respuesta_operacion_atencion(operacion)
            ahora = timeutils._utc_now()
            ahora_iso = timeutils._to_utc_iso(ahora)
            motivo = _motivo_ticket_atencion(ticket, autoridad, ahora)
            _suprimir_ticket_atencion(connection, ticket, motivo, ahora_iso)
            operacion = {"cliente_id": cliente_id, "ticket_id": ticket_id, "tipo": tipo,
                "canal": canal, "fragmento": fragmento, "clave_intento": clave_intento,
                "payload_hash": huella, "request_hash": huella_solicitud,
                "estado": "suprimido" if motivo else "en_transito",
                "owner_token": "" if motivo else uuid.uuid4().hex, "motivo": motivo,
                "created_at": ahora_iso, "resultado_at": "", "result_ref": ""}
            connection.execute(
                "INSERT INTO client_attention_operations "
                "(cliente_id,ticket_id,tipo,canal,fragmento,clave_intento,payload_hash,request_hash,estado,"
                "owner_token,motivo,created_at,resultado_at,result_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(operacion[k] for k in ("cliente_id", "ticket_id", "tipo", "canal", "fragmento",
                    "clave_intento", "payload_hash", "request_hash", "estado", "owner_token", "motivo", "created_at",
                    "resultado_at", "result_ref")))
        return _respuesta_operacion_atencion(operacion, ejecutar=not motivo)
    except sqlite3.Error as exc:
        atencion._ATENCION_LOG.error("atencion_admision_fallida tipo=%s", type(exc).__name__)
        raise atencion.AtencionNoDisponible("No se puede admitir la operación de atención.") from exc


def registrar_resultado_operacion_atencion(cliente_id, ticket_id, *, tipo, canal, fragmento=0,
        clave_intento="", owner_token, resultado, result_ref=""):
    """Resultado del propietario, aun en pausa; ninguna respuesta concede permiso."""
    atencion._validar_cliente_atencion(cliente_id)
    _validar_referencia_atencion(ticket_id, _ATENCION_TOKEN_RE, "ticket")
    _validar_identidad_operacion_atencion(tipo, canal, fragmento, clave_intento)
    _validar_referencia_atencion(owner_token, _ATENCION_TOKEN_RE, "propietario")
    if not isinstance(resultado, str) or resultado not in ("aceptado", "rechazado", "desconocido"):
        raise ValueError("Resultado de atención no válido.")
    _validar_resultado_referencia_atencion(tipo, resultado, result_ref)
    identidad = (cliente_id, ticket_id, tipo, canal, fragmento, clave_intento)
    try:
        with closing(db._get_db_connection()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            _buscar_ticket_atencion(connection, cliente_id, ticket_id)
            operacion = _envio_operacion_atencion(connection.execute(
                "SELECT * FROM client_attention_operations WHERE cliente_id=? AND ticket_id=? "
                "AND tipo=? AND canal=? AND fragmento=? AND clave_intento=?", identidad).fetchone())
            if operacion["estado"] == "suprimido" or operacion["owner_token"] != owner_token:
                raise AtencionPropietarioInvalido("No es el propietario de esta admisión.")
            if result_ref and operacion["result_ref"] and operacion["result_ref"] != result_ref:
                raise AtencionIdentidadEnConflicto("La operación ya tiene otra referencia de resultado.")
            if operacion["estado"] == resultado or (
                    operacion["estado"] in ("aceptado", "rechazado") and resultado == "desconocido"):
                return _respuesta_operacion_atencion(operacion)
            if operacion["estado"] in ("aceptado", "rechazado"):
                raise AtencionIdentidadEnConflicto("La operación ya tiene otro resultado conocido.")
            ahora = timeutils._to_utc_iso(timeutils._utc_now())
            connection.execute(
                "UPDATE client_attention_operations SET estado=?,resultado_at=?,result_ref=? "
                "WHERE cliente_id=? AND ticket_id=? AND tipo=? AND canal=? AND fragmento=? "
                "AND clave_intento=? AND owner_token=?", (resultado, ahora, result_ref) + identidad + (owner_token,))
            operacion.update(estado=resultado, resultado_at=ahora, result_ref=result_ref)
        return _respuesta_operacion_atencion(operacion)
    except sqlite3.Error as exc:
        atencion._ATENCION_LOG.error("atencion_resultado_fallido tipo=%s", type(exc).__name__)
        raise atencion.AtencionNoDisponible("No se puede registrar el resultado de atención.") from exc


def consultar_operaciones_atencion(cliente_id, *, ticket_id=None, tipo=None):
    """Distingue reservas de entregas; diario técnico sin propietarios ni permiso."""
    atencion._validar_cliente_atencion(cliente_id)
    if ticket_id is not None:
        _validar_referencia_atencion(ticket_id, _ATENCION_TOKEN_RE, "ticket")
    if tipo not in (None, "envio", "reserva"):
        raise ValueError("Tipo de operación no válido.")
    try:
        with closing(db._get_db_connection()) as connection, connection:
            connection.execute("BEGIN")
            if ticket_id is not None:
                _buscar_ticket_atencion(connection, cliente_id, ticket_id)
            query = "SELECT * FROM client_attention_operations WHERE cliente_id=?"
            args = (cliente_id,)
            if ticket_id is not None:
                query += " AND ticket_id=?"
                args += (ticket_id,)
            if tipo is not None:
                query += " AND tipo=?"
                args += (tipo,)
            operaciones = []
            for row in connection.execute(query + " ORDER BY created_at,ticket_id,tipo,canal,fragmento,clave_intento", args):
                _buscar_ticket_atencion(connection, cliente_id, row["ticket_id"])
                operaciones.append(_respuesta_operacion_atencion(_envio_operacion_atencion(row)))
        return operaciones
    except sqlite3.Error as exc:
        atencion._ATENCION_LOG.error("atencion_diario_fallido tipo=%s", type(exc).__name__)
        raise atencion.AtencionNoDisponible("No se puede consultar el diario de atención.") from exc


def admitir_envio_atencion(cliente_id, ticket_id, canal, fragmento, *, payload):
    """Compatibilidad de fase2a: el permiso común conserva la API de envíos."""
    return _compat_respuesta_envio_atencion(admitir_operacion_atencion(cliente_id, ticket_id,
        tipo="envio", canal=canal, fragmento=fragmento, payload=payload))


def registrar_resultado_atencion(cliente_id, ticket_id, canal, fragmento, *, owner_token, resultado):
    return _compat_respuesta_envio_atencion(registrar_resultado_operacion_atencion(cliente_id, ticket_id,
        tipo="envio", canal=canal, fragmento=fragmento, owner_token=owner_token, resultado=resultado))


def consultar_envios_atencion(cliente_id, *, ticket_id=None):
    return [_compat_respuesta_envio_atencion(r) for r in
            consultar_operaciones_atencion(cliente_id, ticket_id=ticket_id, tipo="envio")]
