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


def capturar_envios() -> List[str]:
    """Sustituye los envios de WhatsApp y devuelve la lista donde caen.

    Las listas y los botones se aplanan a texto: para medir da igual como se
    presente, lo que cuenta es lo que lee la clienta.
    """
    from backend import messaging

    dichos: List[str] = []

    async def texto(*, text="", **kwargs):
        dichos.append(text)
        return True

    async def lista(*, body="", sections=None, **kwargs):
        filas = [f["title"] for s in (sections or []) for f in s.get("rows", [])]
        dichos.append("%s || %s" % (body, " / ".join(filas)))
        return True

    async def botones(*, body="", **kwargs):
        dichos.append(body)
        return True

    async def cta(*, body="", **kwargs):
        dichos.append(body)
        return True

    messaging._send_whatsapp_text = texto
    messaging._send_whatsapp_list = lista
    messaging._send_whatsapp_buttons = botones
    messaging._send_whatsapp_cta_url = cta
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

    async def email_mudo(*args, **kwargs):
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
