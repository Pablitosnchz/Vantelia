"""Onboarding y provisioning self-serve de clientes (refactor F3)."""
from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import copy
import httpx
from fastapi import BackgroundTasks, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from onboarding_utils import run_onboarding, slugify_company
from backend import agenda, appstate, clients, db, demo_agenda, outreach, rag, security, settings, textnorm, timeutils

def _read_onboarding_state(cliente_id: str) -> Dict[str, Any]:
    row = db.db_get_client_row(cliente_id)
    if not row:
        return {}
    try:
        cfg = json.loads(row["config_json"] or "{}")
    except json.JSONDecodeError:
        return {}
    return cfg.get("_onboarding_state", {}) or {}


def _write_onboarding_state(cliente_id: str, state: Dict[str, Any]) -> None:
    row = db.db_get_client_row(cliente_id)
    if not row:
        return
    try:
        cfg = json.loads(row["config_json"] or "{}")
    except json.JSONDecodeError:
        cfg = {}
    cfg["_onboarding_state"] = state
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE clientes SET config_json = ?, updated_at = ? WHERE cliente_id = ?",
            (json.dumps(cfg, ensure_ascii=False), now_iso, cliente_id),
        )
        connection.commit()


def _slugify_cliente_id(value: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", textnorm._sanitize_text(value).lower()).strip("_")
    return base[:50] or "bot"


def _generate_unique_cliente_id(name: str) -> str:
    base = _slugify_cliente_id(name)
    candidate = base
    suffix = 0
    with appstate.state_lock:
        existing = set(appstate.CONFIG_CLIENTES.keys())
    while candidate in existing or db.db_get_client_row(candidate) is not None:
        suffix += 1
        candidate = f"{base}_{secrets.token_hex(3)}"
        if suffix > 10:
            candidate = f"{base}_{secrets.token_hex(6)}"
            break
    return candidate


def _provision_self_serve_cliente(
    *,
    owner_user_id: str,
    nombre: str,
) -> str:
    """Provision a brand-new cliente_id owned by the user. Returns cliente_id."""
    cliente_id = _generate_unique_cliente_id(nombre)
    color_default = "#1F6FEB"
    icon_default = (nombre.strip()[:2] or "AI").upper()
    base_config = {
        "nombre": textnorm._sanitize_text(nombre)[:120] or cliente_id,
        "icono": icon_default,
        "color": color_default,
        "bienvenida": f"Hola, soy el asistente de {textnorm._sanitize_text(nombre)[:80]}. En que puedo ayudarte?",
        "prompt_extra": "",
        "allowed_origins": [],
        "contacto": {"email": "", "telefono": ""},
        "branding": {"powered_by": "Powered by Vantelia"},
        "whatsapp": {"enabled": False},
        "booking": {"enabled": True},
        "plan": "free",
    }
    normalized = clients._normalize_client_config(cliente_id, base_config)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        next_configs[cliente_id] = normalized
        clients._update_runtime_configs(next_configs)
    clients._persist_configs_to_disk(next_configs)
    # ensure data dir exists for RAG indexing later
    cliente_data_dir = settings.DATA_DIR / cliente_id
    cliente_data_dir.mkdir(parents=True, exist_ok=True)
    info_path = cliente_data_dir / "info.txt"
    if not info_path.exists():
        info_path.write_text(
            f"===== INFORMACION DE {nombre.upper()} =====\n\n(Pendiente de completar)\n",
            encoding="utf-8",
        )
    # bind ownership in DB
    db.db_set_client_owner(cliente_id, owner_user_id, source="self_serve")
    # ensure free subscription
    db.db_ensure_free_subscription(owner_user_id, cliente_id=cliente_id)
    # link user.cliente_id 1:1
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET cliente_id = ? WHERE id = ?",
            (cliente_id, owner_user_id),
        )
        connection.commit()
    agenda._ensure_default_employees_for_all_clients()
    # init wizard state
    _write_onboarding_state(cliente_id, {"step": "learn", "started_at": timeutils._utc_now_iso()})
    return cliente_id


def _claim_cliente_id(claim_token: str, user_id: str, *, source: str = "claim_demo") -> str:
    """Transfer ownership of a claimable cliente to user_id.

    A claimable cliente_id is one that:
      - is a self-serve auto demo (starts with DEMO_TENANT_PREFIX), or
      - exists in CONFIG_CLIENTES with empty owner_user_id (no other user claimed it yet).

    Side effects:
      - Sets db owner + source.
      - Removes TTL from the demo registry so it survives _purge_expired_demos.
      - Links user.cliente_id 1:1 (errors if the user already owns another bot).
      - Ensures the user has a free subscription bound to the claimed cliente_id.
      - Best-effort marks any matching outreach prospect as status='client'.

    Returns the cliente_id on success. Raises HTTPException(400/404/409) otherwise.
    """
    cliente_id = (claim_token or "").strip()
    if not cliente_id or not settings.CLIENT_ID_PATTERN.match(cliente_id):
        raise HTTPException(status_code=400, detail="Claim token invalido.")
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Bot no encontrado.")

    existing_owner = db.db_get_client_owner(cliente_id)
    if existing_owner and existing_owner != user_id:
        raise HTTPException(status_code=409, detail="Este bot ya esta reclamado por otra cuenta.")

    # Check the user doesn't already own a different bot (one-bot-per-account model).
    user_row = security._get_user_by_id(user_id)
    if not user_row:
        raise HTTPException(status_code=400, detail="Usuario invalido.")
    existing_cid = (user_row["cliente_id"] or "").strip()
    if existing_cid and existing_cid != cliente_id:
        raise HTTPException(
            status_code=409,
            detail="Ya tienes un bot creado. Solo se permite un bot por cuenta en planes free.",
        )

    is_demo_tenant = (
        cliente_id.startswith(demo_agenda.DEMO_TENANT_PREFIX)
        or bool(appstate.CONFIG_CLIENTES.get(cliente_id, {}).get("demo_claimable"))
    )
    if not is_demo_tenant and not existing_owner:
        # Allow claiming legacy unowned clients only via admin path; reject here to
        # avoid letting any signed-in user grab a production cliente_id.
        raise HTTPException(
            status_code=403,
            detail="Este bot no se puede reclamar publicamente. Contacta con soporte.",
        )

    db.db_set_client_owner(cliente_id, user_id, source=source)
    db.db_ensure_free_subscription(user_id, cliente_id=cliente_id)
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET cliente_id = ? WHERE id = ?",
            (cliente_id, user_id),
        )
        connection.commit()

    # Remove TTL so _purge_expired_demos no longer kills it.
    try:
        registry = demo_agenda._load_demo_registry()
        if cliente_id in registry:
            registry.pop(cliente_id)
            demo_agenda._save_demo_registry(registry)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudo limpiar TTL para demo reclamada %s: %s", cliente_id, exc)

    # Best-effort: mark the outreach prospect linked to this demo as client.
    try:
        outreach._mark_outreach_prospect_as_client_for_cliente(cliente_id, user_row["email"])
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudo marcar prospect como client en outreach: %s", exc)

    return cliente_id


def _unique_cliente_id(seed: str) -> str:
    base = (slugify_company(seed) or "cliente").lower()
    base = base[:64].strip("_") or "cliente"
    candidate = base
    index = 2
    while candidate in appstate.CONFIG_CLIENTES:
        suffix = f"_{index}"
        candidate = f"{base[:80 - len(suffix)]}{suffix}"
        index += 1
    textnorm._assert_valid_client_id(candidate)
    return candidate


