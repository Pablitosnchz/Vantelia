"""Admisión de transportes desde el contexto interno; no es permiso humano.

Sin contexto conserva legacy. Los capturadores de canales deben instalarlo antes
de preparar; la ausencia no acredita cobertura de ese canal. Fragmento procede de
la estructura estable del envío y no de un contador de reintentos.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import smtplib

import httpx

from backend import atencion, atencion_contexto, atencion_operaciones, settings


class SalidaAtencionNoEmitida(atencion_contexto.AtencionDetenida):
    """Supresión acreditada antes de iniciar este fragmento de transporte."""


@dataclass(frozen=True)
class _AvisoAtencion:
    cliente_id: str
    ticket_id: str
    clave_intento: str


_AVISO_ATENCION = ContextVar("aviso_atencion", default=None)


def _aviso_atencion_actual(turno):
    aviso = _AVISO_ATENCION.get()
    if aviso is not None and (turno is None or aviso.cliente_id != turno.cliente_id
                              or aviso.ticket_id != turno.ticket_id):
        raise atencion_contexto.AtencionDetenida("aviso_fuera_de_turno")
    return aviso


@contextmanager
def _ambito_aviso_atencion(cliente_id, identidad):
    turno = atencion_contexto.contexto_atencion_actual()
    tenant = tenant_salida_atencion(cliente_id)
    if tenant is None:
        yield None
        return
    clave = hashlib.sha256(json_salida_atencion([tenant] + identidad)).hexdigest()
    aviso = _AvisoAtencion(tenant, turno.ticket_id, clave)
    token = _AVISO_ATENCION.set(aviso)
    try:
        yield aviso
    finally:
        _AVISO_ATENCION.reset(token)


@contextmanager
def aviso_reserva_atencion(fila, kind):
    """Identidad de fila persistida; no crea generación ni concede permiso."""
    if atencion_contexto.contexto_atencion_actual() is None:
        _aviso_atencion_actual(None)
        yield None
        return
    tenant_salida_atencion(fila["cliente_id"])
    atencion_operaciones._validar_referencia_atencion(
        fila["id"], atencion_operaciones._ATENCION_RESULT_REF_RE, "reserva")
    atencion_operaciones._validar_referencia_atencion(
        kind, atencion_operaciones._ATENCION_CANAL_RE, "aviso")
    generation = fila["reminder_generation"]
    if type(generation) is not int or generation < 0:
        raise atencion_contexto.AtencionDetenida("generacion_aviso_no_verificable")
    with _ambito_aviso_atencion(fila["cliente_id"], ["reserva", fila["id"], generation, kind]) as aviso:
        yield aviso


@contextmanager
def aviso_pago_atencion(fila):
    """El pay_ ya persistido identifica el aviso, también desde otro ticket."""
    if atencion_contexto.contexto_atencion_actual() is None:
        _aviso_atencion_actual(None)
        yield None
        return
    tenant_salida_atencion(fila["cliente_id"])
    atencion_operaciones._validar_referencia_atencion(
        fila["id"], atencion_operaciones._ATENCION_PAYMENT_REF_RE, "pago")
    with _ambito_aviso_atencion(fila["cliente_id"], ["pago", fila["id"], "payment_link"]) as aviso:
        yield aviso


def tenant_salida_atencion(cliente_id=None):
    turno = atencion_contexto.contexto_atencion_actual()
    _aviso_atencion_actual(turno)
    if turno is None:
        return None
    if cliente_id and turno.cliente_id != cliente_id:
        raise atencion_contexto.AtencionDetenida("tenant_incorrecto")
    return turno.cliente_id


def payload_salida_atencion(destino, payload):
    if not isinstance(payload, bytes):
        raise ValueError("La salida requiere bytes efectivos.")
    return destino.encode("utf-8") + b"\n" + payload


def json_salida_atencion(datos):
    return json.dumps(datos, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def comprobar_salida_atencion(cliente_id):
    """Preparación de aviso: no hereda permiso de una reserva/pago ganador."""
    turno = atencion_contexto.contexto_atencion_actual()
    tenant = tenant_salida_atencion(cliente_id)
    if tenant is None:
        return
    try:
        ticket = atencion_operaciones.comprobar_ticket_atencion(tenant, turno.ticket_id)
    except (atencion.AtencionNoDisponible, atencion_operaciones.AtencionOperacionNoEncontrada) as exc:
        raise atencion_contexto.AtencionDetenida("atencion_no_verificable") from exc
    if not ticket["puede_preparar"]:
        raise atencion_contexto.AtencionDetenida(ticket["motivo_actual"])


def adjuntar_operacion_conocida_al_corte(exc, tipo, result_ref):
    """Dato de la operación persistida; no cambia el estado de su aviso."""
    exc.operacion_conocida = {"tipo": tipo, "estado": "aceptado", "result_ref": result_ref}


def admitir_salida_atencion(cliente_id, canal, fragmento, payload):
    tenant = tenant_salida_atencion(cliente_id)
    if tenant is None:
        return None
    turno = atencion_contexto.contexto_atencion_actual()
    aviso = _aviso_atencion_actual(turno)
    try:
        admision = atencion_operaciones.admitir_envio_atencion(
            tenant, turno.ticket_id, canal, fragmento, payload=payload,
            **({"clave_intento": aviso.clave_intento} if aviso is not None else {}))
    except atencion_operaciones.AtencionIdentidadEnConflicto as exc:
        raise atencion_contexto.AtencionDetenida("identidad_en_conflicto") from exc
    except (atencion.AtencionNoDisponible, atencion_operaciones.AtencionOperacionNoEncontrada) as exc:
        raise atencion_contexto.AtencionDetenida("atencion_no_verificable") from exc
    if not admision["ejecutar_red"]:
        if admision["estado"] == "suprimido":
            raise SalidaAtencionNoEmitida(admision["motivo"])
        raise atencion_contexto.AtencionDetenida(admision["motivo"] or "envio_ya_admitido", admision["estado"])
    return admision


def registrar_salida_atencion(admision, resultado):
    if admision is None:
        return resultado
    try:
        actual = atencion_operaciones.registrar_resultado_atencion(
            admision["cliente_id"], admision["ticket_id"], admision["canal"], admision["fragmento"],
            owner_token=admision["owner_token"], resultado=resultado,
            **({"clave_intento": admision["clave_intento"]} if admision.get("clave_intento") else {}))
        return actual["estado"]
    except atencion.AtencionNoDisponible:
        settings.logger.error("atencion_salida_resultado_no_persistido")
        return "desconocido"


def _rechazo_seguro_salida_atencion(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return 400 <= exc.response.status_code < 500 and exc.response.status_code != 408
    return isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused,
                            smtplib.SMTPAuthenticationError))


@contextmanager
def salida_red_atencion(cliente_id, canal, fragmento, payload):
    admision = admitir_salida_atencion(cliente_id, canal, fragmento, payload)
    try:
        yield admision
    except atencion_contexto.AtencionDetenida:
        raise
    except Exception as exc:
        if admision is None:
            raise
        estado = registrar_salida_atencion(admision,
            "rechazado" if _rechazo_seguro_salida_atencion(exc) else "desconocido")
        if estado != "rechazado":
            raise atencion_contexto.AtencionDetenida("envio_sin_nueva_admision", estado) from exc
        raise
    finally:
        if admision is not None:
            registrar_salida_atencion(admision, "desconocido")


def preparar_mime_atencion(message, canal):
    """Evita que un boundary aleatorio convierta el mismo MIME en otro payload."""
    turno = atencion_contexto.contexto_atencion_actual()
    aviso = _aviso_atencion_actual(turno)
    if turno is not None and message.is_multipart():
        if aviso is not None:
            # MIME limita el boundary a 70 caracteres; no incluir un ticket nuevo.
            identidad = hashlib.sha256(json_salida_atencion([aviso.clave_intento, canal])).hexdigest()
            message.set_boundary("vt_" + identidad)
        else:
            message.set_boundary("vantelia_" + turno.ticket_id + "_" + canal)
    return message.as_bytes()


def auditar_salida_conocida_atencion(cliente_id, callback, *args, **kwargs):
    try:
        callback(*args, **kwargs)
    except Exception:
        if tenant_salida_atencion(cliente_id) is None:
            raise
        settings.logger.error("atencion_salida_aceptada_auditoria_fallida")
