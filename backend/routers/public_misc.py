"""Endpoints: seccion public_misc (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

import asyncio
import copy
import base64
import csv
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import shutil
import sqlite3
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import httpx
from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

import onboarding_utils
from api_models import *  # noqa: F401,F403
from backend import (
    agenda,
    appstate,
    billing,
    booking,
    chat,
    clients,
    crm,
    db,
    demo_agenda,
    emailing,
    growth,
    instagram,
    messaging,
    onboarding,
    outreach,
    portal,
    rag,
    security,
    settings,
    stripe_gateway,
    textnorm,
    tiktok,
    timeutils,
    voice,
    wa_capture,
    whatsapp,
)
from backend.main import app

@app.post("/analytics/event")
async def analytics_event(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Payload JSON invalido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload de analitica invalido.")
    return portal._record_analytics_event(payload, request)


@app.post("/consulta")
async def solicitar_consulta(data: ConsultaLeadPayload, request: Request) -> Dict[str, Any]:
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"consulta:{client_ip}", 5)

    servicio_texto = data.servicio or "No especificado"
    empresa_texto  = data.empresa  or "No especificada"
    telefono_texto = data.telefono or "No proporcionado"
    mensaje_texto  = data.mensaje  or "(sin mensaje)"

    fecha_utc = timeutils._utc_now().strftime('%Y-%m-%d %H:%M UTC')

    asunto_admin = "Nueva consulta recibida"
    cuerpo_admin_text = (
        f"Tienes una nueva consulta desde la web.\n\n"
        f"Nombre:   {data.nombre}\n"
        f"Email:    {data.email}\n"
        f"Teléfono: {telefono_texto}\n"
        f"Empresa:  {empresa_texto}\n"
        f"Servicio: {servicio_texto}\n\n"
        f"Mensaje:\n{mensaje_texto}\n\n"
        f"---\nIP de origen: {client_ip}\n"
        f"Fecha: {fecha_utc}\n"
    )
    cuerpo_admin_html = f"""
<div style="font-family:sans-serif;max-width:560px;margin:0 auto;color:#1a1a2e">
  <h2 style="color:#00b1d9">Nueva consulta recibida</h2>
  <p style="color:#333">Tienes una nueva consulta desde la web.</p>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="padding:6px 0;color:#666;width:110px">Nombre</td><td style="padding:6px 0;font-weight:600">{escape(data.nombre)}</td></tr>
    <tr><td style="padding:6px 0;color:#666">Email</td><td style="padding:6px 0"><a href="mailto:{escape(data.email)}">{escape(data.email)}</a></td></tr>
    <tr><td style="padding:6px 0;color:#666">Teléfono</td><td style="padding:6px 0">{escape(telefono_texto)}</td></tr>
    <tr><td style="padding:6px 0;color:#666">Empresa</td><td style="padding:6px 0">{escape(empresa_texto)}</td></tr>
    <tr><td style="padding:6px 0;color:#666">Servicio</td><td style="padding:6px 0">{escape(servicio_texto)}</td></tr>
  </table>
  <p style="margin-top:16px;color:#333"><strong>Mensaje:</strong><br>{escape(mensaje_texto).replace(chr(10), '<br>')}</p>
  <hr style="margin:20px 0;border:none;border-top:1px solid #eee">
  <p style="font-size:12px;color:#999">IP: {escape(client_ip)} · {fecha_utc}</p>
</div>"""

    asunto_cliente = "Hemos recibido tu consulta"
    cuerpo_cliente_text = (
        f"Hola {data.nombre},\n\n"
        "Hemos recibido tu consulta correctamente. Nos pondremos en contacto contigo "
        "lo antes posible (normalmente en menos de 24 horas).\n\n"
        "Resumen de tu solicitud:\n"
        f"  · Servicio: {servicio_texto}\n"
        f"  · Empresa:  {empresa_texto}\n"
        f"  · Mensaje:  {mensaje_texto}\n\n"
        "Si necesitas añadir información, responde directamente a este correo.\n\n"
        "Un saludo,\nEquipo Vantelia\nhttps://www.vantelia.es\n"
    )
    cuerpo_cliente_html = f"""
<div style="font-family:sans-serif;max-width:560px;margin:0 auto;color:#1a1a2e">
  <h2 style="color:#00b1d9">Hemos recibido tu consulta</h2>
  <p style="color:#333">Hola <strong>{escape(data.nombre)}</strong>,</p>
  <p style="color:#333;line-height:1.55">
    Hemos recibido tu consulta correctamente. Nos pondremos en contacto contigo lo antes
    posible (normalmente en menos de 24 horas).
  </p>
  <table style="width:100%;border-collapse:collapse;margin-top:12px">
    <tr><td style="padding:6px 0;color:#666;width:110px">Servicio</td><td style="padding:6px 0">{escape(servicio_texto)}</td></tr>
    <tr><td style="padding:6px 0;color:#666">Empresa</td><td style="padding:6px 0">{escape(empresa_texto)}</td></tr>
    <tr><td style="padding:6px 0;color:#666;vertical-align:top">Mensaje</td><td style="padding:6px 0">{escape(mensaje_texto).replace(chr(10), '<br>')}</td></tr>
  </table>
  <p style="margin-top:18px;color:#333">
    Si necesitas añadir información, responde directamente a este correo.
  </p>
  <p style="margin-top:24px;color:#333">Un saludo,<br><strong>Equipo Vantelia</strong></p>
  <hr style="margin:20px 0;border:none;border-top:1px solid #eee">
  <p style="font-size:12px;color:#999">Este es un mensaje automático desde info@vantelia.es · <a href="https://www.vantelia.es" style="color:#00b1d9">vantelia.es</a></p>
</div>"""

    notif_sent = False
    confirm_sent = False
    if emailing._email_delivery_configured():
        try:
            emailing._send_email_message(
                settings.CONSULTA_NOTIFICATION_EMAIL,
                asunto_admin,
                cuerpo_admin_text,
                cuerpo_admin_html,
                reply_to=str(data.email),
            )
            notif_sent = True
        except Exception as exc:
            settings.logger.error("Error enviando notificacion de consulta a %s: %s", settings.CONSULTA_NOTIFICATION_EMAIL, exc)
        try:
            emailing._send_email_message(
                str(data.email),
                asunto_cliente,
                cuerpo_cliente_text,
                cuerpo_cliente_html,
            )
            confirm_sent = True
        except Exception as exc:
            settings.logger.error("Error enviando confirmacion de consulta a %s: %s", data.email, exc)
    else:
        settings.logger.warning("Canal de email no configurado: no se han enviado emails de la consulta de %s", data.email)

    settings.logger.info(
        "Consulta recibida de %s <%s> (IP: %s) notif=%s confirm=%s",
        data.nombre, data.email, client_ip, notif_sent, confirm_sent,
    )
    return {"ok": True, "message": "Solicitud recibida. Te respondemos en menos de 24h."}


@app.get("/health")
async def healthcheck() -> Dict[str, Any]:
    checks: Dict[str, str] = {
        "config": "ok" if settings.CONFIG_PATH.exists() else "missing",
        "data_dir": "ok" if settings.DATA_DIR.exists() else "missing",
        "storage_dir": "ok" if settings.STORAGE_DIR.exists() else "missing",
        "database": "unknown",
        "widget_bundle": "ok" if (settings.WIDGET_DIR / "widget.min.js").exists() else "missing",
    }
    try:
        with db._get_db_connection() as connection:
            connection.execute("SELECT 1").fetchone()
            checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Healthcheck database failed: %s", exc)
        checks["database"] = "error"

    critical_checks = ["config", "data_dir", "storage_dir", "database"]
    overall_status = "ok" if all(checks.get(name) == "ok" for name in critical_checks) else "degraded"
    return {
        "status": overall_status,
        "version": app.version,
        "openai_configured": bool(settings.OPENAI_API_KEY),
        "clientes_configurados": len(appstate.CONFIG_CLIENTES),
        "checks": checks,
        "runtime": {
            "started_at": appstate.STARTED_AT.isoformat(),
            "uptime_seconds": int((timeutils._utc_now() - appstate.STARTED_AT).total_seconds()),
            "data_dir": str(settings.DATA_DIR),
            "storage_dir": str(settings.STORAGE_DIR),
        },
    }


