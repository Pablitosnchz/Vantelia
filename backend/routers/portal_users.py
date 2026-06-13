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



# ---------------------------------------------------------------------------
# Equipo de acceso self-serve (F6): el owner del negocio gestiona sus usuarios
# ---------------------------------------------------------------------------


def _team_member_or_404(cliente_id: str, member_id: str) -> sqlite3.Row:
    target = security._get_user_by_id(member_id)
    if not target or target["role"] != "client" or (target["cliente_id"] or "") != cliente_id:
        raise HTTPException(status_code=404, detail="Usuario no encontrado en tu equipo.")
    return target


def _count_active_owners(cliente_id: str, *, exclude_user_id: str = "") -> int:
    rows = security._list_users(role="client", cliente_id=cliente_id, include_inactive=False)
    return sum(
        1
        for row in rows
        if security._portal_role(row) == "owner" and row["id"] != exclude_user_id
    )


@app.get("/auth/app/team", response_model=AuthManagedUsersResponse)
async def auth_app_team_list(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthManagedUsersResponse:
    security._require_portal_min_role(user, "owner")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    rows = security._list_users(role="client", cliente_id=target_client_id, include_inactive=True)
    return AuthManagedUsersResponse(
        items=[security._serialize_managed_user(row) for row in rows],
        total=len(rows),
    )


@app.post("/auth/app/team", response_model=AuthManagedUser)
async def auth_app_team_create(
    data: PortalTeamMemberPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthManagedUser:
    security._require_portal_min_role(user, "owner")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    max_users = clients._plan_feature(target_client_id, "max_users")
    if max_users is not None and security._count_client_users(target_client_id) >= int(max_users):
        limits = clients._plan_limits(clients._client_plan(target_client_id))
        raise HTTPException(
            status_code=403,
            detail=f"Tu plan {limits.get('label')} permite hasta {max_users} usuario(s). Sube de plan para ampliar el equipo.",
        )
    if security._get_user_by_email(data.email):
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese email.")
    created = security._create_user(
        email=data.email,
        password=data.password,
        role="client",
        display_name=data.display_name or data.email.split("@")[0],
        cliente_id=target_client_id,
        portal_role=data.portal_role,
    )
    return security._serialize_managed_user(created)


@app.post("/auth/app/team/{member_id}", response_model=AuthManagedUser)
async def auth_app_team_update(
    member_id: str,
    data: PortalTeamMemberUpdatePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthManagedUser:
    security._require_portal_min_role(user, "owner")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    target = _team_member_or_404(target_client_id, member_id)
    fields_set = set(getattr(data, "model_fields_set", set()))

    new_role = data.portal_role if "portal_role" in fields_set and data.portal_role else ""
    deactivating = "is_active" in fields_set and data.is_active is False
    demoting = bool(new_role) and new_role != "owner" and security._portal_role(target) == "owner"
    if (demoting or deactivating) and not _count_active_owners(target_client_id, exclude_user_id=target["id"]):
        raise HTTPException(
            status_code=409,
            detail="El negocio necesita al menos un propietario activo.",
        )
    with db._get_db_connection() as connection:
        if "display_name" in fields_set and data.display_name:
            connection.execute(
                "UPDATE users SET display_name = ? WHERE id = ?",
                (data.display_name.strip(), target["id"]),
            )
        if new_role:
            connection.execute(
                "UPDATE users SET portal_role = ? WHERE id = ?", (new_role, target["id"])
            )
        if "is_active" in fields_set and data.is_active is not None:
            connection.execute(
                "UPDATE users SET is_active = ? WHERE id = ?",
                (1 if data.is_active else 0, target["id"]),
            )
        connection.commit()
    if deactivating:
        security._delete_user_auth_sessions(target["id"])
    return security._serialize_managed_user(security._get_user_by_id(target["id"]))


@app.delete("/auth/app/team/{member_id}", response_model=AuthSimpleResponse)
async def auth_app_team_delete(
    member_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> AuthSimpleResponse:
    security._require_portal_min_role(user, "owner")
    target_client_id = portal._portal_client_id_or_403(user, cliente_id)
    target = _team_member_or_404(target_client_id, member_id)
    if (
        security._portal_role(target) == "owner"
        and bool(target["is_active"])
        and not _count_active_owners(target_client_id, exclude_user_id=target["id"])
    ):
        raise HTTPException(status_code=409, detail="El negocio necesita al menos un propietario activo.")
    security._delete_user(target["id"])
    return AuthSimpleResponse(ok=True, message="Usuario eliminado del equipo.")
