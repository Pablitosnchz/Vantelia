"""Frontera /chat: emitir por ASGI no acredita que el navegador haya leído.

Vigencia técnica explícita de 120 s al no existir timeout global de /chat.
Cada petición captura identidad interna nueva: sin ID estable del cliente no se
promete deduplicación entre peticiones HTTP diferentes. Ninguna supresión o caída
reutiliza la admisión de la petición original. Sin interceptores globales de RAG.
"""
import asyncio
from contextlib import closing
from datetime import timedelta
import json
import uuid

from fastapi import HTTPException
from starlette.responses import JSONResponse

from backend import atencion, atencion_contexto, atencion_operaciones, db, rag, settings, timeutils


CHAT_HTTP_VIGENCIA_SEGUNDOS = 120
_CHAT_HTTP_SCOPE = "vantelia.atencion_chat"
_CHAT_HTTP_LOCKS = {}


class ReciboChatHttp:
    """Estado de una petición en su scope ASGI; nunca se comparte por ContextVar."""

    def __init__(self):
        self.cliente_id = ""
        self.session_id = ""
        self.ticket_id = ""
        self.clave_intento = uuid.uuid4().hex
        self.historial = ()
        self.borrador = None
        self.contar_uso = False
        self.lock_key = None
        self.lock = None
        self.admision = None
        self.emitido = False

    def diferir_assistant(self, **datos):
        if datos["cliente_id"] != self.cliente_id or datos["session_id"] != self.session_id:
            raise atencion_contexto.AtencionDetenida("tenant_incorrecto")
        self.borrador = dict(datos)

    def motor_rag_del_turno(self):
        return rag._crear_motor_chat_aislado(self.cliente_id, self.historial)


def error_atencion_chat(exc):
    no_disponible = isinstance(exc, (atencion.AtencionNoDisponible,
        atencion_operaciones.AtencionOperacionNoEncontrada)) or (
        isinstance(exc, atencion_contexto.AtencionDetenida) and exc.motivo == "atencion_no_verificable")
    if no_disponible:
        return HTTPException(status_code=503, detail={"code": "ATTENTION_UNAVAILABLE",
            "message": "No se puede verificar el estado de atención en este momento."})
    return HTTPException(status_code=409, detail={"code": "ATTENTION_STOPPED",
        "message": "La atención automática está detenida para esta solicitud."})


async def preparar_recibo_chat_http(request, cliente_id, session_id, message, on_user_message_persisted, *, intent=""):
    recibo = request.scope[_CHAT_HTTP_SCOPE]
    recibo.cliente_id, recibo.session_id = cliente_id, session_id
    # Capturar antes del primer await: esperar una sesión nunca rejuvenece trabajo.
    ahora = timeutils._utc_now()
    error_captura = None
    try:
        ticket = atencion_operaciones.crear_ticket_atencion(cliente_id, recibo.clave_intento,
            event_at=ahora.isoformat(),
            expires_at=(ahora + timedelta(seconds=CHAT_HTTP_VIGENCIA_SEGUNDOS)).isoformat())
        recibo.ticket_id = ticket["ticket_id"]
    except atencion.AtencionNoDisponible as exc:
        # Aun sin permiso, conservar la entrada para el equipo cuando la DB permita.
        error_captura = exc
    # Orden local por sesión; el aislamiento entre workers procede del motor
    # efímero y del historial persistido, no de este lock en memoria.
    key = (asyncio.get_running_loop(), cliente_id, session_id)
    entrada = _CHAT_HTTP_LOCKS.setdefault(key, [asyncio.Lock(), 0])
    entrada[1] += 1
    recibo.lock_key = key
    try:
        await entrada[0].acquire()
    except BaseException:
        entrada[1] -= 1
        if not entrada[1]:
            _CHAT_HTTP_LOCKS.pop(key, None)
        recibo.lock_key = None
        raise
    recibo.lock = entrada[0]
    rag._ensure_chat_session_record(session_id, cliente_id, request, validar_propietario=True)
    with closing(db._get_db_connection()) as conn:
        recibo.historial = tuple((r["role"], r["content"]) for r in conn.execute(
            "SELECT role,content FROM chat_messages WHERE cliente_id=? AND session_id=? "
            "AND role IN ('user','assistant') ORDER BY id", (cliente_id, session_id)))
    # La entrada queda disponible para el equipo incluso cuando se suprime al bot.
    rag._record_chat_message(session_id=session_id, cliente_id=cliente_id, role="user", content=message,
        intent=intent, validar_propietario=True)
    try:
        on_user_message_persisted(session_id)
    except Exception:
        settings.logger.debug("atencion_chat_callback_entrada_fallido")
    try:
        if error_captura is not None:
            raise error_captura
        ticket = atencion_operaciones.comprobar_ticket_atencion(cliente_id, recibo.ticket_id)
        if not ticket["puede_preparar"]:
            raise atencion_contexto.AtencionDetenida(ticket["motivo_actual"])
    except (atencion.AtencionNoDisponible, atencion_operaciones.AtencionOperacionNoEncontrada,
            atencion_contexto.AtencionDetenida) as exc:
        raise error_atencion_chat(exc) from exc
    return recibo


def _resultado_emision_chat(recibo, estado):
    try:
        atencion_operaciones.registrar_resultado_atencion(recibo.cliente_id, recibo.ticket_id,
            "chat_http", 0, owner_token=recibo.admision["owner_token"], resultado=estado)
    except (atencion.AtencionNoDisponible, atencion_operaciones.AtencionOperacionNoEncontrada):
        settings.logger.error("atencion_chat_resultado_no_persistido")


def _registrar_chat_emitido(recibo, cuerpo):
    # Registrar exactamente la respuesta serializada, también si el procesador
    # fue sustituido y no llamó al callback de borradores.
    contenido = cuerpo["respuesta"]
    intent = cuerpo.get("intent") or ""
    if recibo.borrador is not None and recibo.borrador["content"] == contenido:
        intent = recibo.borrador.get("intent") or intent
    try:
        rag._record_chat_message(session_id=recibo.session_id, cliente_id=recibo.cliente_id,
            role="assistant", content=contenido, intent=intent, validar_propietario=True)
    except Exception:
        settings.logger.error("atencion_chat_historial_emitido_no_persistido")
    if recibo.contar_uso:
        try:
            db.db_increment_message_usage(recibo.cliente_id, count=1, kind="bot_reply")
        except Exception:
            settings.logger.error("atencion_chat_uso_emitido_no_persistido")


class AtencionChatASGI:
    """Exterior a BaseHTTPMiddleware: observa el send real del servidor."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/chat" or scope.get("method") != "POST":
            return await self.app(scope, receive, send)
        recibo = ReciboChatHttp()
        scope[_CHAT_HTTP_SCOPE] = recibo
        mensajes = []
        status = None

        async def enviar_chat_admitido(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            if status != 200:
                await send(message)
                return
            mensajes.append(message)
            if message["type"] != "http.response.body" or message.get("more_body", False):
                return
            payload = b"".join(m.get("body", b"") for m in mensajes)
            try:
                if not recibo.ticket_id:
                    raise atencion.AtencionNoDisponible("La respuesta carece de ticket interno.")
                cuerpo = json.loads(payload)
                if not isinstance(cuerpo.get("respuesta"), str):
                    raise atencion.AtencionNoDisponible("Respuesta no verificable.")
                recibo.admision = atencion_operaciones.admitir_envio_atencion(
                    recibo.cliente_id, recibo.ticket_id, "chat_http", 0, payload=payload)
                if not recibo.admision["ejecutar_red"]:
                    raise atencion_contexto.AtencionDetenida(recibo.admision["motivo"] or "envio_ya_admitido")
            except (atencion.AtencionNoDisponible, atencion_operaciones.AtencionOperacionNoEncontrada,
                    atencion_contexto.AtencionDetenida) as exc:
                error = error_atencion_chat(exc)
                respuesta = JSONResponse({"detail": error.detail}, status_code=error.status_code)
                respuesta.raw_headers.extend((k, v) for k, v in mensajes[0].get("headers", [])
                    if k.lower() not in (b"content-length", b"content-type"))
                await respuesta(scope, receive, send)
                return
            # No await entre la admisión y el primer send, ni transacción durante red.
            for mensaje in mensajes:
                await send(mensaje)
            recibo.emitido = True
            _resultado_emision_chat(recibo, "aceptado")
            _registrar_chat_emitido(recibo, cuerpo)

        try:
            await self.app(scope, receive, enviar_chat_admitido)
        finally:
            if recibo.admision is not None and recibo.admision.get("ejecutar_red") and not recibo.emitido:
                _resultado_emision_chat(recibo, "desconocido")
            recibo.borrador = None
            recibo.historial = ()
            if recibo.lock is not None:
                recibo.lock.release()
            if recibo.lock_key is not None:
                entrada = _CHAT_HTTP_LOCKS[recibo.lock_key]
                entrada[1] -= 1
                if not entrada[1]:
                    _CHAT_HTTP_LOCKS.pop(recibo.lock_key, None)
