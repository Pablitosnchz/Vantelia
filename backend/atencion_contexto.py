"""Contexto interno capturado por el servidor, sin flags de fuente/modelo/HTTP.

No hay capturadores de canal en esta fase. Ausencia de contexto conserva el
recorrido actual, incluido portal manual; no es una autorización humana que
pueda solicitar el modelo. Las fronteras instalarán el ticket antes de preparar.
La clave del intento la conserva el servidor entre reintentos, nunca se genera
aquí. Objetos inmutables para que copy_context sea seguro entre tareas e hilos.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json

from backend import atencion, atencion_operaciones


@dataclass(frozen=True)
class TurnoAtencion:
    cliente_id: str
    ticket_id: str
    clave_intento: str


@dataclass(frozen=True)
class MutacionAtencion:
    cliente_id: str
    ticket_id: str
    accion: str
    clave_intento: str
    owner_token: str
    tipo: str = "reserva"


_TURNO_ATENCION = ContextVar("turno_atencion", default=None)
_MUTACION_ATENCION = ContextVar("mutacion_atencion", default=None)


class AtencionDetenida(Exception):
    """Control terminal para el adaptador: cero mensaje, fallback o reintento."""

    def __init__(self, motivo, estado="suprimido", result_ref=""):
        self.motivo = motivo
        self.estado = estado
        self.result_ref = result_ref
        super().__init__("La operación automática de atención se ha detenido.")


def contexto_atencion_actual():
    return _TURNO_ATENCION.get()


def _bytes_mutacion_atencion(datos):
    return json.dumps(datos, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def comprobar_intento_mutacion_atencion(cliente_id, accion, solicitud, *, tipo="reserva"):
    turno = _turno_validado_atencion(cliente_id)
    if turno is None:
        return
    try:
        operacion = atencion_operaciones.consultar_intento_operacion_atencion(
            cliente_id, turno.ticket_id, accion, turno.clave_intento, tipo=tipo)
    except (atencion.AtencionNoDisponible, atencion_operaciones.AtencionOperacionNoEncontrada) as exc:
        raise AtencionDetenida("atencion_no_verificable") from exc
    if operacion is not None:
        if operacion["request_hash"] != hashlib.sha256(_bytes_mutacion_atencion(solicitud)).hexdigest():
            raise AtencionDetenida("identidad_en_conflicto")
        raise AtencionDetenida(operacion["motivo"] or "operacion_ya_admitida",
                              operacion["estado"], operacion["result_ref"])
    verificar_turno_atencion(cliente_id)


def comprobar_intento_pago_atencion(cliente_id, solicitud):
    return comprobar_intento_mutacion_atencion(cliente_id, "crear_enlace", solicitud, tipo="pago")


@contextmanager
def turno_atencion(cliente_id, ticket_id, clave_intento):
    atencion._validar_cliente_atencion(cliente_id)
    atencion_operaciones._validar_referencia_atencion(
        ticket_id, atencion_operaciones._ATENCION_TOKEN_RE, "ticket")
    atencion_operaciones._validar_referencia_atencion(
        clave_intento, atencion_operaciones._ATENCION_EVENTO_RE, "intento")
    token = _TURNO_ATENCION.set(TurnoAtencion(cliente_id, ticket_id, clave_intento))
    try:
        yield _TURNO_ATENCION.get()
    finally:
        _TURNO_ATENCION.reset(token)


def _turno_validado_atencion(cliente_id):
    turno = _TURNO_ATENCION.get()
    if turno is None:
        return None
    if turno.cliente_id != cliente_id:
        raise AtencionDetenida("tenant_incorrecto")
    return turno


def verificar_turno_atencion(cliente_id):
    turno = _turno_validado_atencion(cliente_id)
    if turno is None:
        return None
    admitida = _MUTACION_ATENCION.get()
    if admitida is not None:
        if (admitida.cliente_id, admitida.ticket_id, admitida.clave_intento) != (
                turno.cliente_id, turno.ticket_id, turno.clave_intento):
            raise AtencionDetenida("contexto_incompatible")
        # Una admisión que ganó antes de la pausa sigue siendo un hecho en
        # tránsito. La pausa no convierte sus siguientes pasos en otra operación.
        return turno
    try:
        foto = atencion_operaciones.comprobar_ticket_atencion(cliente_id, turno.ticket_id)
    except (atencion.AtencionNoDisponible, atencion_operaciones.AtencionOperacionNoEncontrada) as exc:
        raise AtencionDetenida("atencion_no_verificable") from exc
    if not foto["puede_preparar"]:
        raise AtencionDetenida(foto["motivo_actual"])
    return turno


def exigir_mutacion_atencion(cliente_id):
    """Antes de claims/liberaciones: tener turno no equivale a haber ganado."""
    turno = verificar_turno_atencion(cliente_id)
    if turno is not None and _MUTACION_ATENCION.get() is None:
        raise AtencionDetenida("mutacion_sin_admision")


def _terminar_mutacion_atencion(admision, resultado, result_ref=""):
    return atencion_operaciones.registrar_resultado_operacion_atencion(
        admision.cliente_id, admision.ticket_id, tipo=admision.tipo, canal=admision.accion,
        clave_intento=admision.clave_intento, owner_token=admision.owner_token,
        resultado=resultado, result_ref=result_ref)


def _registrar_evidencia_mutacion_atencion(cliente_id, resultado, referencia=""):
    admitida = _MUTACION_ATENCION.get()
    if admitida is None:
        return
    if admitida.cliente_id != cliente_id:
        raise AtencionDetenida("tenant_incorrecto")
    try:
        _terminar_mutacion_atencion(admitida, resultado, result_ref=referencia)
    except atencion.AtencionNoDisponible:
        # El efecto ya existe. Un fallo de su diario no impide terminar pagos,
        # políticas o avisos del ganador ni convierte el fallo en otro permiso.
        atencion._ATENCION_LOG.error("atencion_mutacion_conocida_no_persistida")


def registrar_mutacion_conocida(cliente_id, booking_id):
    _registrar_evidencia_mutacion_atencion(cliente_id, "aceptado", booking_id)


def registrar_pago_conocido(cliente_id, payment_id):
    _registrar_evidencia_mutacion_atencion(cliente_id, "aceptado", payment_id)


def registrar_pago_rechazado(cliente_id):
    """Solo cuando el núcleo acredita que no llegó a crear Checkout."""
    _registrar_evidencia_mutacion_atencion(cliente_id, "rechazado")


def registrar_mutacion_rechazada(cliente_id):
    """Solo cuando el núcleo acredita que la operación no creó una reserva."""
    _registrar_evidencia_mutacion_atencion(cliente_id, "rechazado")


@contextmanager
def admitir_mutacion_atencion(cliente_id, accion, datos_efectivos, *, solicitud=None, tipo="reserva"):
    comprobar_intento_mutacion_atencion(
        cliente_id, accion, datos_efectivos if solicitud is None else solicitud, tipo=tipo)
    turno = verificar_turno_atencion(cliente_id)
    if turno is None:
        yield None
        return
    if _MUTACION_ATENCION.get() is not None:
        raise AtencionDetenida("mutacion_anidada")
    # Solo la huella entra en el diario; no nombres, teléfonos ni payloads.
    payload = _bytes_mutacion_atencion(datos_efectivos)
    try:
        admitida = atencion_operaciones.admitir_operacion_atencion(
            cliente_id, turno.ticket_id, tipo=tipo, canal=accion,
            clave_intento=turno.clave_intento, payload=payload,
            solicitud=_bytes_mutacion_atencion(datos_efectivos if solicitud is None else solicitud))
    except atencion_operaciones.AtencionIdentidadEnConflicto as exc:
        raise AtencionDetenida("identidad_en_conflicto") from exc
    except (atencion.AtencionNoDisponible, atencion_operaciones.AtencionOperacionNoEncontrada) as exc:
        raise AtencionDetenida("atencion_no_verificable") from exc
    if not admitida["ejecutar_operacion"]:
        raise AtencionDetenida(admitida["motivo"] or "operacion_ya_admitida",
                              admitida["estado"], admitida["result_ref"])
    admision = MutacionAtencion(cliente_id, turno.ticket_id, accion,
                               turno.clave_intento, admitida["owner_token"], tipo)
    token = _MUTACION_ATENCION.set(admision)
    try:
        yield admision
    finally:
        try:
            # Si se persistió, el diario conserva aceptado. Una caída posterior
            # no lo convierte en desconocido. Sin evidencia permanece incierto.
            _terminar_mutacion_atencion(admision, "desconocido")
        except atencion.AtencionNoDisponible:
            atencion._ATENCION_LOG.error("atencion_mutacion_resultado_no_persistido")
        finally:
            _MUTACION_ATENCION.reset(token)


def admitir_pago_atencion(cliente_id, datos_efectivos, *, solicitud=None):
    return admitir_mutacion_atencion(cliente_id, "crear_enlace", datos_efectivos,
                                    solicitud=solicitud, tipo="pago")
