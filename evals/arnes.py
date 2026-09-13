# -*- coding: utf-8 -*-
"""Lo que necesita cualquier medida del asistente: una copia aislada y un canal.

Existe para que el banco de casos (`scripts/evaluar_asistente.py`) y el usuario
simulado (`scripts/simular_clientas.py`) trabajen sobre EXACTAMENTE el mismo
montaje. Si cada uno se hiciera el suyo, medirian cosas distintas y dirian
numeros distintos del mismo asistente.

Tres piezas:

    preparar_copia()   una copia de la base de datos, y COMPROBAR que se usa
    capturar_envios()  lo que el asistente manda por WhatsApp, sin mandarlo
    citas_de()         que ha quedado en la agenda, que es lo que de verdad cuenta

AISLAMIENTO (incidente real): `settings.DB_PATH` se calcula al IMPORTAR y no lee
la variable de entorno, asi que exportar DB_PATH no aisla nada; costo siete citas
de prueba metidas en la agenda de un salon real. Y la copia se hace con `backup()`
de SQLite, no con `copyfile`: en modo WAL los ultimos cambios viven en un fichero
aparte, asi que la copia traia citas ya borradas.
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
from typing import Any, Dict, List


def preparar_copia(origen: str, destino: str) -> None:
    """Deja el proceso trabajando sobre una copia de la base de datos."""
    from backend import settings

    for sufijo in ("", "-wal", "-shm"):
        try:
            os.remove(destino + sufijo)
        except OSError:
            pass
    origen_db = sqlite3.connect(origen)
    destino_db = sqlite3.connect(destino)
    with destino_db:
        origen_db.backup(destino_db)
    origen_db.close()
    destino_db.close()
    os.environ["DB_PATH"] = destino
    settings.DB_PATH = pathlib.Path(destino)
    _migrar_la_copia()


def _migrar_la_copia() -> None:
    """Pone la copia al dia con el esquema del codigo que se va a medir.

    La copia sale de PRODUCCION, que va por detras del candidato: si el candidato
    crea una tabla, la copia no la tiene y el instrumento mide un error de esquema
    en vez de medir al asistente. Paso el 13-sep-2026 con `conversation_states`:
    las 41 conversaciones del banco reventaron con "no such table" y el resultado
    fue 0 de 41, que parecia un producto roto cuando lo roto era la medida.

    En el servidor esto no ocurre porque `backend/main.py` migra al arrancar; aqui
    nadie importa `main`, asi que se migra a mano. `_init_database` usa
    CREATE TABLE IF NOT EXISTS y ALTER para las columnas nuevas: no toca los datos
    que traiga la copia (comprobado: 769 citas antes y despues).
    """
    from backend import db

    db._init_database()


def comprobar_aislamiento(destino: str) -> None:
    """Se niega a seguir si las escrituras irian a la base de datos de verdad."""
    from backend import db, settings

    efectiva = str(settings.DB_PATH)
    if os.path.abspath(efectiva) != os.path.abspath(destino):
        raise SystemExit(
            "NO se esta usando la copia (%s), sino %s. Se aborta para no tocar la "
            "agenda del negocio." % (destino, efectiva)
        )
    with db._get_db_connection() as conexion:
        fichero = conexion.execute("PRAGMA database_list").fetchone()[2]
    if os.path.abspath(fichero) != os.path.abspath(destino):
        raise SystemExit("las conexiones siguen abriendo %s. Se aborta." % fichero)


VERSION_INTERACCION = "botones-emitidos-v2"


class AccionNoDisponible(ValueError):
    """El guion pidio una accion que no se emitio para esta clienta."""


class InstrumentoNoCompatible(RuntimeError):
    """La frontera de transporte no se puede medir con este instrumento."""


class CapturaEnvios(list):
    """Conserva la lista de textos legacy y la evidencia de interaccion emitida."""

    def __init__(self):
        super().__init__()
        self.eventos = []
        self._pendientes = {}

    def registrar(self, texto, tipo, cliente_id, telefono, botones=(), *, enviado=True):
        evento = {"texto": texto, "tipo": tipo, "cliente_id": cliente_id,
                  "destinatario": telefono, "enviado": enviado,
                  "botones": [{"id": b[0], "titulo": b[1]} for b in botones]}
        self.eventos.append(evento)
        self._pendientes[(cliente_id, telefono)] = evento
        if enviado:
            self.append(texto)

    def opciones(self, cliente_id, telefono):
        evento = self._pendientes.get((cliente_id, telefono))
        if not evento or not evento["enviado"] or not evento["botones"]:
            return []
        return [dict(b) for b in evento["botones"]]


def preparar_entrada(captura, cliente_id, telefono, entrada):
    """Texto libre sigue siendo texto; solo una accion explicita puede pulsar."""
    opciones = captura.opciones(cliente_id, telefono) if isinstance(entrada, dict) else []
    captura._pendientes.pop((cliente_id, telefono), None)
    if isinstance(entrada, str):
        return entrada, ""
    if isinstance(entrada, dict):
        if (set(entrada) == {"accion", "indice"} and entrada["accion"] == "pulsar_boton"
                and type(entrada["indice"]) is int and 0 <= entrada["indice"] < len(opciones)):
            elegida = opciones[entrada["indice"]]
            return elegida["titulo"], elegida["id"]
        if set(entrada) == {"boton"}:
            # Repetir un boton ya emitido reproduce lo que permite el chat real.
            # Solo el producto puede decidir si sigue vigente o fue aceptado.
            for evento in reversed(captura.eventos):
                if (evento["enviado"] and evento["cliente_id"] == cliente_id
                        and evento["destinatario"] == telefono):
                    for opcion in evento["botones"]:
                        if entrada["boton"] == opcion["id"]:
                            return opcion["titulo"], opcion["id"]
    raise AccionNoDisponible("Accion sin boton emitido para esta clienta")


def capturar_envios() -> CapturaEnvios:
    """Sustituye envios, conserva textos e IDs y simula su aceptacion sin red."""
    from backend import messaging

    dichos = CapturaEnvios()
    botones_reales = getattr(messaging._send_whatsapp_buttons, "_arnes_original", messaging._send_whatsapp_buttons)

    def guardar(texto, tipo, kwargs, botones=(), enviado=True):
        resultado = enviado
        if kwargs.get("detailed"):
            tipo_resultado = getattr(messaging, "WhatsAppSendResult", None)
            if tipo_resultado is None:
                raise InstrumentoNoCompatible("NO MEDIDO: detailed requiere WhatsAppSendResult; frontera no soportada")
            resultado = tipo_resultado("aceptado" if enviado else "rechazado", motivo="captura_sin_red")
        dichos.registrar(texto, tipo, kwargs.get("cliente_id", ""),
                         kwargs.get("to_number") or (kwargs.get("payload") or {}).get("to", ""),
                         botones, enviado=enviado)
        return resultado

    async def texto(*, text="", **kwargs):
        return guardar(text, "texto", kwargs)

    async def lista(*, body="", sections=None, **kwargs):
        filas = [f["title"] for s in (sections or []) for f in s.get("rows", [])]
        return guardar("%s || %s" % (body, " / ".join(filas)), "lista", kwargs)

    async def botones(*, body="", buttons=None, **kwargs):
        return await botones_reales(body=body, buttons=buttons or (), **kwargs)

    async def cta(*, body="", **kwargs):
        return guardar(body, "cta", kwargs)

    async def formulario(**kwargs):
        # Frontera comun al transporte bool anterior y al tipado actual: el
        # builder del producto ya normalizo los botones; aqui no hay HTTP.
        payload = kwargs["payload"]
        interactive = payload.get("interactive") or {}
        if payload.get("type") == "interactive" and interactive.get("type") == "button":
            normalizados = [(b["reply"]["id"], b["reply"]["title"])
                            for b in interactive["action"]["buttons"]]
            return guardar(interactive["body"]["text"], "botones", kwargs, normalizados)
        # El formulario de reserva (WhatsApp Flows) sale por aqui, y sin esto iba a
        # Meta DE VERDAD con el token del .env (11-sep-2026, en el propio humo del
        # despliegue). El numero de pruebas no existe, Meta contestaba 400 y el
        # asistente seguia por mensajes: se da por rechazado sin salir de aqui, que
        # es el mismo camino, pero sin peticion a nadie.
        return guardar("", "formulario", kwargs, enviado=False)

    botones._arnes_original = botones_reales

    messaging._send_whatsapp_text = texto
    messaging._send_whatsapp_list = lista
    messaging._send_whatsapp_buttons = botones
    messaging._send_whatsapp_cta_url = cta
    messaging._send_whatsapp_payload = formulario
    return dichos


def cortar_el_mundo_exterior() -> None:
    """Nada de lo que haga una clienta de mentira puede salir de aqui.

    Medir no puede tener efectos: la primera tirada disparo el webhook de leads
    del salon (respondio 410, pero podria haber sido un 200 en el CRM de un
    cliente real) y una reserva con email habria mandado un correo de verdad.
    """
    from backend import booking, emailing, messaging

    async def webhook_mudo(cliente_id, payload):
        return True, "simulacion"

    def email_mudo(*args, **kwargs):
        return True

    async def sms_mudo(*args, **kwargs):
        return True

    booking._send_booking_to_webhook = webhook_mudo
    emailing._send_client_email = email_mudo
    messaging._send_client_sms = sms_mudo


def citas_de(cliente_id: str, telefono: str) -> List[Dict[str, Any]]:
    """Las citas de ese telefono. La agenda es la verdad, no lo que diga el chat."""
    from backend import db

    with db._get_db_connection() as conexion:
        filas = conexion.execute(
            "SELECT booking_code, status, booking_date, booking_time, service_id,"
            " servicio, nombre FROM bookings"
            " WHERE cliente_id=? AND REPLACE(REPLACE(telefono,' ',''),'+','') LIKE ?"
            " ORDER BY created_at", (cliente_id, "%" + telefono[-9:]),
        ).fetchall()
    return [dict(f) for f in filas]


def citas_vivas(cliente_id: str, telefono: str) -> List[Dict[str, Any]]:
    return [c for c in citas_de(cliente_id, telefono)
            if c["status"] in ("confirmed", "pending_review")]
