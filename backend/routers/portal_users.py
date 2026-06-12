"""Endpoints: seccion portal_users (refactor F3).

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

@app.post("/auth/users", response_model=AuthManagedUser)
async def auth_create_user_managed(
    data: PortalCreateUserPayload,
    user: sqlite3.Row = Depends(security._require_authenticated_admin_user),
) -> AuthManagedUser:
    _ = user
    role = data.role.strip().lower() or "client"
    if role not in {"admin", "client"}:
        raise HTTPException(status_code=400, detail="Rol invalido.")
    cliente_id = ""
    if role == "client":
        cliente_id = onboarding_utils.slugify_company(data.cliente_id)
        textnorm._assert_valid_client_id(cliente_id)
        clients._get_client_config(cliente_id)
        max_users = clients._plan_feature(cliente_id, "max_users")
        if max_users is not None and security._count_client_users(cliente_id) >= int(max_users):
            limits = clients._plan_limits(clients._client_plan(cliente_id))
            raise HTTPException(
                status_code=403,
                detail=f"Tu plan {limits.get('label')} permite hasta {max_users} usuario(s). Sube de plan para añadir más."
            )
    if security._get_user_by_email(data.email):
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese email.")
    created = security._create_user(
        email=data.email,
        password=data.password,
        role=role,
        display_name=data.display_name,
        cliente_id=cliente_id,
    )
    return security._serialize_managed_user(created)


@app.post("/auth/users/{user_id}/deactivate", response_model=AuthSimpleResponse)
async def auth_deactivate_user(
    user_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_admin_user),
) -> AuthSimpleResponse:
    target_user = security._load_managed_user_or_404(user_id)
    if not target_user["is_active"]:
        return AuthSimpleResponse(ok=True, message="El usuario ya estaba desactivado.")
    security._assert_admin_can_manage_user(user, target_user, "desactivar")
    security._set_user_active(user_id, False)
    security._delete_user_auth_sessions(user_id)
    return AuthSimpleResponse(ok=True, message="Usuario desactivado correctamente.")


@app.post("/auth/users/{user_id}/activate", response_model=AuthSimpleResponse)
async def auth_activate_user(
    user_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_admin_user),
) -> AuthSimpleResponse:
    _ = user
    target_user = security._load_managed_user_or_404(user_id)
    if target_user["is_active"]:
        return AuthSimpleResponse(ok=True, message="El usuario ya estaba activo.")
    security._set_user_active(user_id, True)
    return AuthSimpleResponse(ok=True, message="Usuario activado correctamente.")


@app.post("/auth/users/{user_id}/reset-link", response_model=AuthSimpleResponse)
async def auth_send_user_reset_link(
    user_id: str,
    request: Request,
    user: sqlite3.Row = Depends(security._require_authenticated_admin_user),
) -> AuthSimpleResponse:
    _ = user
    if not emailing._email_delivery_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La recuperacion por correo no esta disponible todavia. Configura SMTP en el servidor.",
        )
    target_user = security._load_managed_user_or_404(user_id)
    if not target_user["is_active"]:
        raise HTTPException(status_code=400, detail="No puedes enviar reset a un usuario desactivado.")
    public_token = security._create_password_reset_token(
        target_user["id"],
        requested_from_ip=(request.client.host if request.client else "admin"),
    )
    try:
        emailing._send_password_reset_email(target_user, public_token, request)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("No se ha podido enviar el reset al usuario %s: %s", target_user["email"], exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se ha podido enviar el correo de recuperacion.",
        ) from exc
    return AuthSimpleResponse(ok=True, message="Enlace de recuperacion enviado correctamente.")


@app.delete("/auth/users/{user_id}", response_model=AuthSimpleResponse)
async def auth_delete_user(
    user_id: str,
    user: sqlite3.Row = Depends(security._require_authenticated_admin_user),
) -> AuthSimpleResponse:
    target_user = security._load_managed_user_or_404(user_id)
    security._assert_admin_can_manage_user(user, target_user, "eliminar")
    security._delete_user(user_id)
    return AuthSimpleResponse(ok=True, message="Usuario eliminado correctamente.")


