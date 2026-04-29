from __future__ import annotations

import asyncio
import copy
import csv
import hmac
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import smtplib
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlparse

import httpx
from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from llama_index.core import (
    Settings,
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
from pydantic import BaseModel, EmailStr, Field
from onboarding_utils import run_onboarding, slugify_company

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("VANTELIA_DATA_DIR", str(BASE_DIR / "data"))).resolve()
STORAGE_DIR = Path(os.getenv("VANTELIA_STORAGE_DIR", str(BASE_DIR / "storage"))).resolve()
WIDGET_DIR = BASE_DIR / "widget"
ADMIN_UI_DIR = BASE_DIR / "admin_ui"
ACCESS_UI_DIR = BASE_DIR / "access_ui"
PORTAL_UI_DIR = BASE_DIR / "portal_ui"
BRAND_DIR = BASE_DIR / "brand_assets"
LEGAL_DIR = BASE_DIR / "docs" / "legal"
CONFIG_PATH = Path(os.getenv("VANTELIA_CONFIG_PATH", str(BASE_DIR / "config.json"))).resolve()
DB_PATH = STORAGE_DIR / "vantelia.db"

BOOKING_SENTINEL = "[MOSTRAR_FORMULARIO]"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{12,128}$")
CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{2,80}$")
TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")

DEFAULT_CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Europe/Madrid")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
MAX_MESSAGES_PER_SESSION = int(os.getenv("MAX_MESSAGES_PER_SESSION", "40"))
CHAT_RATE_LIMIT = int(os.getenv("CHAT_RATE_LIMIT_PER_MINUTE", "30"))
BOOKING_RATE_LIMIT = int(os.getenv("BOOKING_RATE_LIMIT_PER_MINUTE", "10"))
MAX_BOOKING_ADVANCE_DAYS = int(os.getenv("MAX_BOOKING_ADVANCE_DAYS", "60"))
RATE_LIMIT_WINDOW_SECONDS = 60

logger = logging.getLogger("vantelia")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "").strip()
WEBHOOK_DEFAULT = os.getenv("WEBHOOK_DEFAULT", "").strip()
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "").strip()
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v22.0").strip() or "v22.0"
WHATSAPP_DEFAULT_CLIENT_ID = os.getenv("WHATSAPP_DEFAULT_CLIENT_ID", "").strip()
WHATSAPP_PHONE_CLIENT_MAP = os.getenv("WHATSAPP_PHONE_CLIENT_MAP", "").strip()
RAW_EXTRA_CORS_ORIGINS = os.getenv("EXTRA_CORS_ORIGINS", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "").strip()
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Vantelia").strip()
SMTP_REPLY_TO = os.getenv("SMTP_REPLY_TO", "").strip()
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").strip().lower() in {"1", "true", "yes", "on"}
REMINDER_24H_HOURS = int(os.getenv("REMINDER_24H_HOURS", "24"))
REMINDER_2H_HOURS = int(os.getenv("REMINDER_2H_HOURS", "2"))
REMINDER_RUN_INTERVAL_MINUTES = int(os.getenv("REMINDER_RUN_INTERVAL_MINUTES", "30"))
BOOKING_AUTO_COMPLETE_HOURS = int(os.getenv("BOOKING_AUTO_COMPLETE_HOURS", "24"))
PASSWORD_RESET_TOKEN_HOURS = int(os.getenv("PASSWORD_RESET_TOKEN_HOURS", "2"))
PASSWORD_RESET_RESEND_SECONDS = int(os.getenv("PASSWORD_RESET_RESEND_SECONDS", "60"))
PORTAL_COOKIE_NAME = os.getenv("PORTAL_COOKIE_NAME", "vantelia_portal_session").strip() or "vantelia_portal_session"
PORTAL_COOKIE_DOMAIN = os.getenv("PORTAL_COOKIE_DOMAIN", "").strip()
PORTAL_SESSION_HOURS = int(os.getenv("PORTAL_SESSION_HOURS", "72"))
PORTAL_ADMIN_EMAIL = os.getenv("PORTAL_ADMIN_EMAIL", "").strip().lower()
PORTAL_ADMIN_PASSWORD = os.getenv("PORTAL_ADMIN_PASSWORD", "").strip()
PORTAL_ADMIN_NAME = os.getenv("PORTAL_ADMIN_NAME", "Administrador Vantelia").strip()
MARKETING_SITE_URL = os.getenv("MARKETING_SITE_URL", "https://vantelia.es").strip()
PORTAL_SUPPORT_EMAIL = (
    os.getenv("PORTAL_SUPPORT_EMAIL", "").strip() or SMTP_REPLY_TO or SMTP_FROM_EMAIL or "soporte@vantelia.es"
)

DEFAULT_MESSAGE_TEMPLATES = {
    "confirmed": (
        "Tu cita ha quedado confirmada. Debajo tienes los detalles y tu enlace personal para gestionarla "
        "si necesitas hacer algun cambio."
    ),
    "reminder_24h": (
        "Te recordamos que manana tienes una cita programada. Si necesitas revisarla o ajustarla, "
        "puedes hacerlo desde tu enlace de gestion."
    ),
    "reminder_2h": (
        "Tu cita empieza en menos de 2 horas. Te dejamos los detalles y el acceso directo para gestionarla "
        "si lo necesitas."
    ),
    "cancelled": (
        "Tu cita ha sido cancelada. Debajo te dejamos la informacion y tu enlace de gestion por si "
        "necesitas revisarla."
    ),
    "rescheduled": (
        "Tu cita se ha actualizado correctamente. Revisa los nuevos datos y utiliza tu enlace personal "
        "si necesitas volver a modificarla."
    ),
}

DEFAULT_MESSAGE_TEMPLATE_ENABLED = {
    "confirmed": True,
    "reminder_24h": True,
    "reminder_2h": True,
    "cancelled": True,
    "rescheduled": True,
}


@dataclass
class SessionState:
    engine: Any
    cliente_id: str
    created_at: float
    last_seen: float
    message_count: int = 0


@dataclass
class ProviderBookingResult:
    success: bool
    status: str
    provider_name: str
    provider_booking_id: str = ""
    provider_booking_url: str = ""
    message: str = ""


indices: Dict[str, VectorStoreIndex] = {}
sesiones: Dict[str, SessionState] = {}
rate_limit_buckets: Dict[str, List[float]] = {}
last_cleanup_run = 0.0
state_lock = threading.RLock()
booking_reminder_stop = threading.Event()
booking_reminder_thread: Optional[threading.Thread] = None
STARTED_AT = datetime.now(timezone.utc)


def _normalize_origin_value(origin: str) -> str:
    raw_value = str(origin).strip().rstrip("/")
    if not raw_value:
        raise RuntimeError("Se ha recibido un origen vacio en la configuracion.")

    parsed = urlparse(raw_value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"Origen invalido en la configuracion: {origin}")

    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise RuntimeError(
            f"El origen debe incluir solo esquema y dominio, sin rutas ni query strings: {origin}"
        )

    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _normalize_optional_http_url(raw_url: str) -> str:
    value = str(raw_url).strip()
    if not value:
        return ""

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"URL HTTP invalida en la configuracion: {raw_url}")

    return value


def _normalize_message_templates(raw_templates: Any) -> Dict[str, str]:
    templates = dict(DEFAULT_MESSAGE_TEMPLATES)
    if isinstance(raw_templates, dict):
        for key in DEFAULT_MESSAGE_TEMPLATES:
            raw_value = raw_templates.get(key, "")
            if isinstance(raw_value, dict):
                raw_value = raw_value.get("body", raw_value.get("message", ""))
            value = _sanitize_text(raw_value, allow_multiline=True)
            if value:
                templates[key] = value[:500]
    return templates


def _normalize_message_template_enabled(
    raw_enabled: Any,
    raw_templates: Any = None,
) -> Dict[str, bool]:
    enabled = dict(DEFAULT_MESSAGE_TEMPLATE_ENABLED)
    if isinstance(raw_enabled, dict):
        for key in DEFAULT_MESSAGE_TEMPLATE_ENABLED:
            if key in raw_enabled:
                enabled[key] = bool(raw_enabled.get(key))
    if isinstance(raw_templates, dict):
        for key in DEFAULT_MESSAGE_TEMPLATE_ENABLED:
            nested_value = raw_templates.get(key)
            if isinstance(nested_value, dict) and "enabled" in nested_value:
                enabled[key] = bool(nested_value.get("enabled"))
    return enabled


def _sanitize_text(value: str, *, allow_multiline: bool = False) -> str:
    value = str(value or "")
    if allow_multiline:
        cleaned_lines = [" ".join(line.split()) for line in value.splitlines()]
        return "\n".join(line for line in cleaned_lines if line).strip()

    return " ".join(value.split()).strip()


def _ensure_path_within(base_dir: Path, target_dir: Path) -> None:
    base_resolved = base_dir.resolve()
    target_resolved = target_dir.resolve()
    if target_resolved != base_resolved and base_resolved not in target_resolved.parents:
        raise RuntimeError(f"Ruta fuera del directorio permitido: {target_dir}")


EXTRA_CORS_ORIGINS = [
    _normalize_origin_value(origin)
    for origin in RAW_EXTRA_CORS_ORIGINS.split(",")
    if origin.strip()
]


def _load_client_configs() -> Dict[str, Dict[str, Any]]:
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"No se encontro el archivo de configuracion: {CONFIG_PATH}")

    raw_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    normalized: Dict[str, Dict[str, Any]] = {}

    for cliente_id, payload in raw_config.items():
        normalized[cliente_id] = _normalize_client_config(cliente_id, payload)

    return normalized


def _normalize_client_config(cliente_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not CLIENT_ID_PATTERN.match(cliente_id):
        raise RuntimeError(f"cliente_id invalido en config.json: {cliente_id}")

    booking = payload.get("booking", {})
    allowed_origins = [
        _normalize_origin_value(origin)
        for origin in payload.get("allowed_origins", [])
        if isinstance(origin, str) and str(origin).strip()
    ]

    return {
        "nombre": _sanitize_text(payload.get("nombre", cliente_id)),
        "icono": _sanitize_text(payload.get("icono", "Chat"))[:12] or "Chat",
        "color": _sanitize_text(payload.get("color", "#00b1d9")) or "#00b1d9",
        "bienvenida": _sanitize_text(
            payload.get("bienvenida", "Hola, soy tu asistente virtual. En que puedo ayudarte?"),
            allow_multiline=True,
        ),
        "prompt_extra": _sanitize_text(payload.get("prompt_extra", ""), allow_multiline=True),
        "allowed_origins": allowed_origins,
        "contacto": {
            "email": _sanitize_text(str(payload.get("contacto", {}).get("email", ""))),
            "telefono": _sanitize_text(str(payload.get("contacto", {}).get("telefono", ""))),
        },
        "branding": {
            "powered_by": _sanitize_text(
                str(payload.get("branding", {}).get("powered_by", "Powered by Vantelia"))
            )
            or "Powered by Vantelia"
        },
        "whatsapp": {
            "enabled": bool(payload.get("whatsapp", {}).get("enabled", False)),
            "phone_number_id": _sanitize_text(
                str(payload.get("whatsapp", {}).get("phone_number_id", ""))
            )[:120],
            "access_token_env": _sanitize_text(
                str(payload.get("whatsapp", {}).get("access_token_env", ""))
            )[:120],
            "verify_token_env": _sanitize_text(
                str(payload.get("whatsapp", {}).get("verify_token_env", ""))
            )[:120],
        },
        "booking": {
            "enabled": bool(booking.get("enabled", False)),
            "timezone": _sanitize_text(booking.get("timezone", DEFAULT_TIMEZONE)) or DEFAULT_TIMEZONE,
            "slot_minutes": int(booking.get("slot_minutes", 30)),
            "day_start": _sanitize_text(booking.get("day_start", "09:00")) or "09:00",
            "day_end": _sanitize_text(booking.get("day_end", "18:00")) or "18:00",
            "closed_weekdays": booking.get("closed_weekdays", [0]),
            "provider": "internal",
            "webhook_env": _sanitize_text(booking.get("webhook_env", "")),
            "webhook_url": _normalize_optional_http_url(booking.get("webhook_url", "")),
            "calendly_user_env": "",
            "calendly_event_type_env": "",
            "calendly_location_kind": "",
            "calendly_location_value": "",
            "google_calendar_id": "",
            "google_calendar_id_env": "",
            "google_service_account_path": "",
            "google_service_account_env": "",
            "success_message": _sanitize_text(
                booking.get(
                    "success_message",
                    "Tu solicitud de cita ha quedado registrada correctamente.",
                ),
                allow_multiline=True,
            ),
            "message_templates": _normalize_message_templates(booking.get("message_templates", {})),
            "message_template_enabled": _normalize_message_template_enabled(
                booking.get("message_template_enabled", {}),
                booking.get("message_templates", {}),
            ),
        },
    }


def _serialize_client_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "nombre": config["nombre"],
        "icono": config["icono"],
        "color": config["color"],
        "bienvenida": config["bienvenida"],
        "prompt_extra": config.get("prompt_extra", ""),
        "allowed_origins": list(config.get("allowed_origins", [])),
        "contacto": {
            "email": config.get("contacto", {}).get("email", ""),
            "telefono": config.get("contacto", {}).get("telefono", ""),
        },
        "branding": {
            "powered_by": config.get("branding", {}).get("powered_by", "Powered by Vantelia"),
        },
        "whatsapp": {
            "enabled": bool(config.get("whatsapp", {}).get("enabled", False)),
            "phone_number_id": config.get("whatsapp", {}).get("phone_number_id", ""),
            "access_token_env": config.get("whatsapp", {}).get("access_token_env", ""),
            "verify_token_env": config.get("whatsapp", {}).get("verify_token_env", ""),
        },
        "booking": {
            "enabled": bool(config.get("booking", {}).get("enabled", False)),
            "timezone": config.get("booking", {}).get("timezone", DEFAULT_TIMEZONE),
            "slot_minutes": int(config.get("booking", {}).get("slot_minutes", 30)),
            "day_start": config.get("booking", {}).get("day_start", "09:00"),
            "day_end": config.get("booking", {}).get("day_end", "18:00"),
            "closed_weekdays": list(config.get("booking", {}).get("closed_weekdays", [0])),
            "provider": "internal",
            "webhook_env": config.get("booking", {}).get("webhook_env", ""),
            "webhook_url": config.get("booking", {}).get("webhook_url", ""),
            "calendly_user_env": "",
            "calendly_event_type_env": "",
            "calendly_location_kind": "",
            "calendly_location_value": "",
            "google_calendar_id": "",
            "google_calendar_id_env": "",
            "google_service_account_path": "",
            "google_service_account_env": "",
            "success_message": config.get("booking", {}).get(
                "success_message",
                "Tu solicitud de cita ha quedado registrada correctamente.",
            ),
            "message_templates": _normalize_message_templates(
                config.get("booking", {}).get("message_templates", {})
            ),
            "message_template_enabled": _normalize_message_template_enabled(
                config.get("booking", {}).get("message_template_enabled", {}),
                config.get("booking", {}).get("message_templates", {}),
            ),
        },
    }


CONFIG_CLIENTES = _load_client_configs()


def _collect_cors_origins() -> List[str]:
    origins = set(EXTRA_CORS_ORIGINS)
    with state_lock:
        for config in CONFIG_CLIENTES.values():
            origins.update(config.get("allowed_origins", []))
    return sorted(origin for origin in origins if origin)


def _update_runtime_configs(next_configs: Dict[str, Dict[str, Any]]) -> None:
    with state_lock:
        CONFIG_CLIENTES.clear()
        CONFIG_CLIENTES.update(next_configs)


def _ensure_runtime_directories() -> None:
    STORAGE_DIR.mkdir(exist_ok=True)
    WIDGET_DIR.mkdir(exist_ok=True)
    ADMIN_UI_DIR.mkdir(exist_ok=True)
    ACCESS_UI_DIR.mkdir(exist_ok=True)
    PORTAL_UI_DIR.mkdir(exist_ok=True)


EMPLOYEE_COLOR_PALETTE = [
    "#00b1d9",
    "#2e86ab",
    "#4caf50",
    "#ff8a65",
    "#f4b400",
    "#8e7dff",
]
DEFAULT_EMPLOYEE_ROLE_LABEL = "Agenda General"


def _normalize_employee_color(value: str, fallback: str = "#00b1d9") -> str:
    candidate = _sanitize_text(value) or fallback
    if not re.match(r"^#[0-9A-Fa-f]{6}$", candidate):
        return fallback
    return candidate


def _normalize_closed_weekdays_list(values: Any) -> List[int]:
    normalized: List[int] = []
    for value in values or []:
        try:
            day = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in normalized:
            normalized.append(day)
    return sorted(normalized)


def _employee_closed_weekdays_from_row(row: sqlite3.Row) -> List[int]:
    try:
        return _normalize_closed_weekdays_list(json.loads(row["closed_weekdays_json"] or "[]"))
    except json.JSONDecodeError:
        return []


def _normalize_service_id(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", _sanitize_text(value).lower()).strip("_")


def _service_map_for_client(cliente_id: str) -> Dict[str, Dict[str, str]]:
    return {
        str(service["id"]): service
        for service in _extract_services_from_info(cliente_id)
        if isinstance(service, dict) and service.get("id") and service.get("nombre")
    }


def _normalize_service_ids_for_client(cliente_id: str, values: Any) -> List[str]:
    service_map = _service_map_for_client(cliente_id)
    normalized: List[str] = []
    for value in values or []:
        service_id = _normalize_service_id(str(value))
        if service_id and service_id in service_map and service_id not in normalized:
            normalized.append(service_id)
    return normalized


def _employee_service_ids_from_row(row: sqlite3.Row, cliente_id: str = "") -> List[str]:
    if not row:
        return []
    target_client_id = cliente_id or str(row["cliente_id"] or "")
    try:
        raw_values = json.loads(row["service_ids_json"] or "[]")
    except json.JSONDecodeError:
        return []
    return _normalize_service_ids_for_client(target_client_id, raw_values)


def _employee_defaults_for_client(cliente_id: str) -> Dict[str, Any]:
    config = CONFIG_CLIENTES.get(cliente_id, {})
    booking = config.get("booking", {})
    return {
        "timezone": booking.get("timezone", DEFAULT_TIMEZONE),
        "slot_minutes": int(booking.get("slot_minutes", 30)),
        "day_start": booking.get("day_start", "09:00"),
        "day_end": booking.get("day_end", "18:00"),
        "closed_weekdays": _normalize_closed_weekdays_list(booking.get("closed_weekdays", [])),
    }


def _default_employee_name(cliente_id: str) -> str:
    config = CONFIG_CLIENTES.get(cliente_id, {})
    company = _sanitize_text(config.get("nombre", cliente_id))
    return f"Agenda general {company}".strip()


def _ensure_default_employees_for_all_clients() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for index, cliente_id in enumerate(CONFIG_CLIENTES.keys()):
            row = connection.execute(
                "SELECT * FROM employees WHERE cliente_id = ? AND is_default = 1 LIMIT 1",
                (cliente_id,),
            ).fetchone()
            defaults = _employee_defaults_for_client(cliente_id)
            if not row:
                employee_id = f"emp_{secrets.token_urlsafe(8)}"
                connection.execute(
                    """
                    INSERT INTO employees (
                        id, cliente_id, name, role_label, color, is_active, is_default,
                        timezone, slot_minutes, day_start, day_end, closed_weekdays_json, service_ids_json,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        employee_id,
                        cliente_id,
                        _default_employee_name(cliente_id),
                        DEFAULT_EMPLOYEE_ROLE_LABEL,
                        EMPLOYEE_COLOR_PALETTE[index % len(EMPLOYEE_COLOR_PALETTE)],
                        1,
                        1,
                        defaults["timezone"],
                        defaults["slot_minutes"],
                        defaults["day_start"],
                        defaults["day_end"],
                        json.dumps(defaults["closed_weekdays"]),
                        "[]",
                        now_iso,
                        now_iso,
                    ),
                )
                row = connection.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
            if row:
                connection.execute(
                    """
                    UPDATE bookings
                    SET employee_id = ?, employee_name = ?
                    WHERE cliente_id = ?
                      AND (employee_id = '' OR employee_name = '')
                    """,
                    (row["id"], row["name"], cliente_id),
                )
        connection.commit()


def _init_database() -> None:
    _ensure_runtime_directories()
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                employee_id TEXT NOT NULL DEFAULT '',
                employee_name TEXT NOT NULL DEFAULT '',
                nombre TEXT NOT NULL,
                email TEXT NOT NULL,
                telefono TEXT,
                servicio TEXT,
                booking_date TEXT NOT NULL,
                booking_time TEXT NOT NULL,
                notas TEXT,
                status TEXT NOT NULL,
                provider_name TEXT NOT NULL DEFAULT 'internal',
                provider_status TEXT NOT NULL,
                provider_booking_id TEXT NOT NULL DEFAULT '',
                provider_booking_url TEXT NOT NULL DEFAULT '',
                manage_token TEXT NOT NULL DEFAULT '',
                timezone TEXT NOT NULL DEFAULT '',
                start_at TEXT NOT NULL DEFAULT '',
                end_at TEXT NOT NULL DEFAULT '',
                confirmed_at TEXT NOT NULL DEFAULT '',
                cancelled_at TEXT NOT NULL DEFAULT '',
                rescheduled_at TEXT NOT NULL DEFAULT '',
                rescheduled_from_booking_id TEXT NOT NULL DEFAULT '',
                confirmation_email_sent_at TEXT NOT NULL DEFAULT '',
                reminder_24h_sent_at TEXT NOT NULL DEFAULT '',
                reminder_2h_sent_at TEXT NOT NULL DEFAULT '',
                customer_email_status TEXT NOT NULL DEFAULT '',
                customer_email_last_error TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(bookings)").fetchall()
        }
        if "provider_name" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN provider_name TEXT NOT NULL DEFAULT 'internal'"
            )
        if "employee_id" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN employee_id TEXT NOT NULL DEFAULT ''")
        if "employee_name" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN employee_name TEXT NOT NULL DEFAULT ''")
        if "provider_booking_id" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN provider_booking_id TEXT NOT NULL DEFAULT ''"
            )
        if "provider_booking_url" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN provider_booking_url TEXT NOT NULL DEFAULT ''"
            )
        if "manage_token" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN manage_token TEXT NOT NULL DEFAULT ''")
        if "timezone" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN timezone TEXT NOT NULL DEFAULT ''")
        if "start_at" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN start_at TEXT NOT NULL DEFAULT ''")
        if "end_at" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN end_at TEXT NOT NULL DEFAULT ''")
        if "confirmed_at" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN confirmed_at TEXT NOT NULL DEFAULT ''")
        if "cancelled_at" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN cancelled_at TEXT NOT NULL DEFAULT ''")
        if "rescheduled_at" not in columns:
            connection.execute("ALTER TABLE bookings ADD COLUMN rescheduled_at TEXT NOT NULL DEFAULT ''")
        if "rescheduled_from_booking_id" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN rescheduled_from_booking_id TEXT NOT NULL DEFAULT ''"
            )
        if "confirmation_email_sent_at" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN confirmation_email_sent_at TEXT NOT NULL DEFAULT ''"
            )
        if "reminder_24h_sent_at" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN reminder_24h_sent_at TEXT NOT NULL DEFAULT ''"
            )
        if "reminder_2h_sent_at" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN reminder_2h_sent_at TEXT NOT NULL DEFAULT ''"
            )
        if "customer_email_status" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN customer_email_status TEXT NOT NULL DEFAULT ''"
            )
        if "customer_email_last_error" not in columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN customer_email_last_error TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bookings_lookup
            ON bookings(cliente_id, employee_id, booking_date, booking_time, status)
            """
        )
        connection.execute("DROP INDEX IF EXISTS idx_bookings_unique_slot")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_unique_slot
            ON bookings(cliente_id, employee_id, booking_date, booking_time)
            WHERE status IN ('confirmed', 'pending_review')
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS employees (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                name TEXT NOT NULL,
                role_label TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#00b1d9',
                is_active INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                timezone TEXT NOT NULL DEFAULT '',
                slot_minutes INTEGER NOT NULL DEFAULT 30,
                day_start TEXT NOT NULL DEFAULT '09:00',
                day_end TEXT NOT NULL DEFAULT '18:00',
                closed_weekdays_json TEXT NOT NULL DEFAULT '[]',
                service_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_employees_lookup
            ON employees(cliente_id, is_active, name)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_default
            ON employees(cliente_id, is_default)
            WHERE is_default = 1
            """
        )
        employee_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(employees)").fetchall()
        }
        if "service_ids_json" not in employee_columns:
            connection.execute("ALTER TABLE employees ADD COLUMN service_ids_json TEXT NOT NULL DEFAULT '[]'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS booking_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id TEXT NOT NULL,
                cliente_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_booking_audit_lookup
            ON booking_audit(booking_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agenda_blocks (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                employee_id TEXT NOT NULL DEFAULT '',
                block_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agenda_blocks_lookup
            ON agenda_blocks(cliente_id, employee_id, block_date, start_time)
            """
        )
        agenda_columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(agenda_blocks)").fetchall()
        }
        if "employee_id" not in agenda_columns:
            connection.execute("ALTER TABLE agenda_blocks ADD COLUMN employee_id TEXT NOT NULL DEFAULT ''")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_manage_token
            ON bookings(manage_token)
            WHERE manage_token <> ''
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_bookings_time_scope
            ON bookings(cliente_id, status, start_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                last_message_at TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                intents_json TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_lookup
            ON chat_sessions(cliente_id, last_message_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                cliente_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                intent TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session
            ON chat_messages(session_id, id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_inbound_messages (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
                phone_number_id TEXT NOT NULL,
                from_number TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_whatsapp_inbound_lookup
            ON whatsapp_inbound_messages(cliente_id, created_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                display_name TEXT NOT NULL,
                cliente_id TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user
            ON auth_sessions(user_id, expires_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT NOT NULL DEFAULT '',
                requested_from_ip TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user
            ON password_reset_tokens(user_id, expires_at)
            """
        )
        connection.commit()
    _ensure_default_employees_for_all_clients()


def _get_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def _validate_single_client_runtime(cliente_id: str, config: Dict[str, Any]) -> None:
    booking_cfg = config["booking"]
    provider = booking_cfg.get("provider", "internal")
    whatsapp_cfg = config.get("whatsapp", {})
    if not re.match(r"^#[0-9A-Fa-f]{6}$", str(config.get("color", ""))):
        raise RuntimeError(f"color invalido para {cliente_id}. Usa formato #RRGGBB.")
    if whatsapp_cfg.get("enabled") and not str(whatsapp_cfg.get("phone_number_id", "")).strip():
        raise RuntimeError(f"whatsapp.phone_number_id requerido para {cliente_id} si WhatsApp esta activo")
    if booking_cfg["enabled"]:
        try:
            ZoneInfo(booking_cfg["timezone"])
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"timezone invalida para {cliente_id}") from exc
        if not TIME_PATTERN.match(booking_cfg["day_start"]):
            raise RuntimeError(f"day_start invalido para {cliente_id}")
        if not TIME_PATTERN.match(booking_cfg["day_end"]):
            raise RuntimeError(f"day_end invalido para {cliente_id}")
        if booking_cfg["slot_minutes"] <= 0:
            raise RuntimeError(f"slot_minutes invalido para {cliente_id}")
        if not isinstance(booking_cfg["closed_weekdays"], list) or any(
            not isinstance(day, int) or day < 0 or day > 6 for day in booking_cfg["closed_weekdays"]
        ):
            raise RuntimeError(f"closed_weekdays invalido para {cliente_id}")
        if provider != "internal":
            raise RuntimeError(f"provider invalido para {cliente_id}")


def _validate_runtime_config() -> None:
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY no esta configurada. El chat quedara deshabilitado.")

    for cliente_id, config in CONFIG_CLIENTES.items():
        _validate_single_client_runtime(cliente_id, config)

    if WEBHOOK_DEFAULT:
        _normalize_optional_http_url(WEBHOOK_DEFAULT)


def _setup_llama_index() -> None:
    if not OPENAI_API_KEY:
        return

    Settings.llm = OpenAI(model=DEFAULT_CHAT_MODEL, temperature=0.1)
    Settings.embed_model = OpenAIEmbedding(model=DEFAULT_EMBEDDING_MODEL)


_ensure_runtime_directories()
_init_database()
_validate_runtime_config()
_setup_llama_index()


app = FastAPI(
    title="Vantelia Embedded Chat API",
    description="Backend multiempresa para chat embebible con RAG y flujo profesional de leads.",
    version="2.0.0",
)

app.mount("/widget", StaticFiles(directory=str(WIDGET_DIR)), name="widget")
if BRAND_DIR.exists():
    app.mount("/brand-assets", StaticFiles(directory=str(BRAND_DIR)), name="brand-assets")


def _brand_asset_public_path(filename: str) -> str:
    if not filename:
        return ""
    asset_path = BRAND_DIR / filename
    if not asset_path.exists():
        return ""
    return f"/brand-assets/{filename}"


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    favicon_candidates = [
        BRAND_DIR / "favicon.png",
        BRAND_DIR / "favicon_fondo.png",
    ]
    for candidate in favicon_candidates:
        if candidate.exists():
            return FileResponse(candidate)
    raise HTTPException(status_code=404, detail="Favicon no encontrado.")


LEGAL_DOCUMENTS = {
    "privacidad": "Politica de privacidad",
    "terminos": "Terminos de uso",
    "cookies": "Politica de cookies",
    "ia": "Aviso sobre IA",
}


def _render_legal_markdown(content: str) -> str:
    html_parts: List[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            html_parts.append(f"<h1>{escape(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            html_parts.append(f"<h2>{escape(line[3:].strip())}</h2>")
        elif line.startswith("- "):
            html_parts.append(f"<p class=\"bullet\">{escape(line[2:].strip())}</p>")
        else:
            html_parts.append(f"<p>{escape(line)}</p>")
    return "\n".join(html_parts)


def _legal_page_html(slug: str, title: str, content: str) -> str:
    nav = " ".join(
        f'<a class="{"active" if key == slug else ""}" href="/legal/{key}">{escape(label)}</a>'
        for key, label in LEGAL_DOCUMENTS.items()
    )
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)} - Vantelia</title>
  <style>
    :root {{ color-scheme: light; --ink: #111827; --muted: #667085; --line: #d8dee8; --brand: #00a3c7; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, Arial, sans-serif; color: var(--ink); background: #f7f9fc; line-height: 1.65; }}
    header {{ background: #101828; color: white; padding: 28px clamp(18px, 5vw, 56px); }}
    header strong {{ display: block; font-size: 20px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
    nav a {{ color: white; border: 1px solid rgba(255,255,255,.22); border-radius: 6px; padding: 8px 10px; text-decoration: none; font-size: 14px; }}
    nav a.active {{ background: var(--brand); border-color: var(--brand); }}
    main {{ max-width: 920px; margin: 0 auto; padding: 34px clamp(18px, 5vw, 56px) 54px; background: white; min-height: calc(100vh - 130px); }}
    h1 {{ margin: 0 0 16px; font-size: clamp(30px, 5vw, 48px); line-height: 1.05; }}
    h2 {{ margin: 30px 0 8px; font-size: 20px; }}
    p {{ margin: 8px 0; }}
    .bullet::before {{ content: "- "; color: var(--brand); font-weight: 700; }}
    .notice {{ border: 1px solid var(--line); border-left: 4px solid var(--brand); border-radius: 6px; padding: 12px 14px; color: var(--muted); background: #fbfdff; }}
  </style>
</head>
<body>
  <header>
    <strong>Vantelia</strong>
    <nav>{nav}</nav>
  </header>
  <main>
    <div class="notice">Plantilla operativa inicial. Revisar con asesoria legal antes de publicarla como version definitiva.</div>
    {_render_legal_markdown(content)}
  </main>
</body>
</html>"""


@app.get("/legal", include_in_schema=False)
async def legal_index() -> RedirectResponse:
    return RedirectResponse("/legal/privacidad", status_code=302)


@app.get("/legal/{documento}", include_in_schema=False)
async def legal_document(documento: str) -> HTMLResponse:
    slug = documento.strip().lower()
    title = LEGAL_DOCUMENTS.get(slug)
    if not title:
        raise HTTPException(status_code=404, detail="Documento legal no encontrado.")
    path = LEGAL_DIR / f"{slug}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Documento legal no configurado.")
    return HTMLResponse(_legal_page_html(slug, title, path.read_text(encoding="utf-8")))


def _booking_reminder_worker() -> None:
    interval_seconds = max(300, REMINDER_RUN_INTERVAL_MINUTES * 60)
    if REMINDER_RUN_INTERVAL_MINUTES <= 0:
        logger.info("Recordatorios automaticos desactivados por configuracion.")
        return

    logger.info(
        "Motor de recordatorios automaticos iniciado. Intervalo: %s minutos.",
        REMINDER_RUN_INTERVAL_MINUTES,
    )
    while not booking_reminder_stop.is_set():
        try:
            auto_confirmed = _auto_confirm_pending_bookings()
            if auto_confirmed:
                logger.info(
                    "Citas pendientes confirmadas automaticamente: %s",
                    auto_confirmed,
                )
            auto_completed = _auto_complete_past_bookings()
            if auto_completed:
                logger.info(
                    "Citas marcadas como completadas automaticamente: %s",
                    auto_completed,
                )
            if _smtp_configured():
                result = asyncio.run(_run_booking_reminders())
                if result.sent_24h or result.sent_2h or result.failed:
                    logger.info(
                        "Recordatorios procesados automaticamente. 24h=%s 2h=%s fallos=%s",
                        result.sent_24h,
                        result.sent_2h,
                        result.failed,
                    )
            else:
                logger.debug("Recordatorios automaticos omitidos: SMTP no configurado.")
        except Exception as exc:  # noqa: BLE001
            logger.error("Error en el motor automatico de recordatorios: %s", exc)

        booking_reminder_stop.wait(interval_seconds)


@app.on_event("startup")
async def startup_background_services() -> None:
    global booking_reminder_thread

    if REMINDER_RUN_INTERVAL_MINUTES <= 0:
        logger.info("Recordatorios automaticos desactivados (REMINDER_RUN_INTERVAL_MINUTES <= 0).")
        return

    if booking_reminder_thread and booking_reminder_thread.is_alive():
        return

    booking_reminder_stop.clear()
    booking_reminder_thread = threading.Thread(
        target=_booking_reminder_worker,
        name="vantelia-booking-reminders",
        daemon=True,
    )
    booking_reminder_thread.start()


@app.on_event("shutdown")
async def shutdown_background_services() -> None:
    booking_reminder_stop.set()


def _build_cors_headers(origin: str) -> Dict[str, str]:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
        "Vary": "Origin",
    }


@app.middleware("http")
async def dynamic_cors_middleware(request: Request, call_next: Any) -> Response:
    raw_origin = request.headers.get("origin", "").strip()
    normalized_origin = ""
    if raw_origin:
        try:
            normalized_origin = _normalize_origin_value(raw_origin)
        except RuntimeError:
            normalized_origin = ""

    is_preflight = request.method == "OPTIONS" and bool(
        request.headers.get("access-control-request-method", "").strip()
    )

    if is_preflight:
        response: Response = Response(status_code=204)
    else:
        response = await call_next(request)

    if normalized_origin and normalized_origin in _collect_cors_origins():
        for key, value in _build_cors_headers(normalized_origin).items():
            response.headers[key] = value

    return response


class MensajeChat(BaseModel):
    cliente_id: str = Field(min_length=2, max_length=80)
    mensaje: str = Field(min_length=1, max_length=2000)
    session_id: Optional[str] = Field(default=None, max_length=128)


class DatosCita(BaseModel):
    cliente_id: str = Field(min_length=2, max_length=80)
    nombre: str = Field(min_length=2, max_length=80)
    email: EmailStr
    telefono: str = Field(default="", max_length=30)
    servicio: str = Field(default="", max_length=120)
    employee_id: str = Field(default="", max_length=80)
    fecha: str = Field(min_length=10, max_length=10)
    hora: str = Field(min_length=5, max_length=5)
    notas: str = Field(default="", max_length=500)


class RespuestaChat(BaseModel):
    respuesta: str
    mostrar_formulario: bool
    session_id: str


class WhatsAppWebhookStatus(BaseModel):
    status: str
    processed: int = 0


class ChatSessionSummary(BaseModel):
    session_id: str
    cliente_id: str
    origin: str = ""
    started_at: str
    last_message_at: str
    message_count: int
    intents: List[str] = Field(default_factory=list)
    last_message: str = ""


class ChatMessagePublic(BaseModel):
    message_id: int
    role: str
    content: str
    intent: str = ""
    created_at: str


class ChatSessionDetail(BaseModel):
    session: ChatSessionSummary
    messages: List[ChatMessagePublic]


class ConfigPublicaCliente(BaseModel):
    nombre: str
    icono: str
    color: str
    bienvenida: str
    booking_enabled: bool
    branding_text: str
    contact_email: str
    contact_phone: str


class SlotDisponibilidad(BaseModel):
    hora: str
    disponible: bool


class RespuestaDisponibilidad(BaseModel):
    fecha: str
    timezone: str
    employee_id: str = ""
    slots: List[SlotDisponibilidad]


class RespuestaAgendado(BaseModel):
    ok: bool
    booking_id: str
    estado: str
    mensaje: str
    employee_id: str = ""
    employee_name: str = ""
    provider_name: str = "internal"
    provider_booking_id: str = ""
    provider_booking_url: str = ""
    manage_url: str = ""


class BookingDetailPublic(BaseModel):
    booking_id: str
    cliente_id: str
    empresa: str
    employee_id: str = ""
    employee_name: str = ""
    nombre: str
    email: str
    telefono: str
    servicio: str
    notas: str = ""
    fecha: str
    hora: str
    timezone: str
    estado: str
    provider_name: str
    provider_booking_url: str = ""
    manage_url: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    available_services: List[Dict[str, str]] = Field(default_factory=list)


class BookingActionResponse(BaseModel):
    ok: bool
    booking_id: str
    estado: str
    mensaje: str
    employee_id: str = ""
    employee_name: str = ""
    manage_url: str = ""
    provider_booking_url: str = ""


class BookingReschedulePayload(BaseModel):
    employee_id: str = Field(default="", max_length=80)
    fecha: str = Field(min_length=10, max_length=10)
    hora: str = Field(min_length=5, max_length=5)


class BookingCancelPayload(BaseModel):
    motivo: str = Field(default="", max_length=500)


class BookingUpdatePayload(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    email: EmailStr
    telefono: str = Field(default="", max_length=30)
    servicio: str = Field(default="", max_length=120)
    employee_id: str = Field(default="", max_length=80)
    fecha: str = Field(min_length=10, max_length=10)
    hora: str = Field(min_length=5, max_length=5)
    notas: str = Field(default="", max_length=500)


class AdminBookingResumen(BaseModel):
    booking_id: str
    cliente_id: str
    empresa: str
    employee_id: str = ""
    employee_name: str = ""
    nombre: str
    email: str
    telefono: str
    servicio: str
    fecha: str
    hora: str
    timezone: str
    estado: str
    provider_name: str
    provider_status: str
    provider_booking_id: str = ""
    provider_booking_url: str = ""
    manage_url: str = ""
    created_at: str
    confirmed_at: str = ""
    cancelled_at: str = ""
    rescheduled_at: str = ""
    confirmation_email_sent_at: str = ""
    reminder_24h_sent_at: str = ""
    reminder_2h_sent_at: str = ""
    customer_email_status: str = ""


class AdminReminderRunResult(BaseModel):
    processed: int
    sent_24h: int
    sent_2h: int
    failed: int


class AuthLoginPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class AuthUserPublic(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    cliente_id: str = ""
    last_login_at: str = ""


class AuthLoginResponse(BaseModel):
    ok: bool
    user: AuthUserPublic
    redirect_to: str


class AuthSimpleResponse(BaseModel):
    ok: bool
    message: str
    retry_after_seconds: int = 0


class ConsultaLeadPayload(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    email: EmailStr
    telefono: Optional[str] = Field(default=None, max_length=40)
    empresa: Optional[str] = Field(default=None, max_length=120)
    servicio: Optional[str] = Field(default=None, max_length=80)
    mensaje: Optional[str] = Field(default=None, max_length=2000)


class AuthManagedUser(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str
    cliente_id: str = ""
    is_active: bool
    created_at: str
    last_login_at: str = ""


class AuthManagedUsersResponse(BaseModel):
    items: List[AuthManagedUser]
    total: int


class AuthPasswordChangePayload(BaseModel):
    current_password: str = Field(min_length=8, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class AuthPasswordForgotPayload(BaseModel):
    email: EmailStr


class AuthPasswordResetPayload(BaseModel):
    token: str = Field(min_length=20, max_length=255)
    new_password: str = Field(min_length=8, max_length=200)


class AuthProfileUpdatePayload(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    email: EmailStr


class PortalAiConfigPayload(BaseModel):
    icono: str = Field(default="AI", max_length=12)
    bienvenida: str = Field(min_length=5, max_length=400)
    prompt_extra: str = Field(default="", max_length=2000)


class PortalAiConfigPublic(BaseModel):
    nombre: str
    icono: str
    bienvenida: str
    prompt_extra: str


class PortalBrainPayload(BaseModel):
    info_txt: str = Field(default="", max_length=120000)


class PortalBrainPublic(BaseModel):
    info_txt: str
    reindexed: bool = False
    reindex_error: str = ""


class PortalScheduleUpdatePayload(BaseModel):
    enabled: bool = True
    timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=80)
    slot_minutes: int = Field(default=30, ge=5, le=240)
    day_start: str = Field(default="09:00", min_length=5, max_length=5)
    day_end: str = Field(default="18:00", min_length=5, max_length=5)
    closed_weekdays: List[int] = Field(default_factory=list)
    message_templates: Dict[str, str] = Field(default_factory=dict)
    message_template_enabled: Dict[str, bool] = Field(default_factory=dict)


class PortalAgendaBlockPayload(BaseModel):
    fecha: str = Field(min_length=10, max_length=10)
    fecha_fin: str = Field(default="", max_length=10)
    hora_inicio: str = Field(min_length=5, max_length=5)
    hora_fin: str = Field(min_length=5, max_length=5)
    motivo: str = Field(default="", max_length=160)


class PortalAgendaBlock(BaseModel):
    block_id: str
    employee_id: str = ""
    fecha: str
    hora_inicio: str
    hora_fin: str
    motivo: str = ""
    created_at: str = ""


class PortalSchedulePublic(BaseModel):
    enabled: bool
    timezone: str
    slot_minutes: int
    day_start: str
    day_end: str
    closed_weekdays: List[int]
    message_templates: Dict[str, str]
    message_template_enabled: Dict[str, bool]
    blocks: List[PortalAgendaBlock]


class PortalAgendaBlockCreateResponse(BaseModel):
    items: List[PortalAgendaBlock]
    created_count: int
    skipped_count: int
    date_from: str
    date_to: str


class PortalBookingSummary(BaseModel):
    booking_id: str
    empresa: str
    employee_id: str = ""
    employee_name: str = ""
    nombre: str
    email: str
    servicio: str
    fecha: str
    hora: str
    timezone: str
    estado: str
    provider_name: str
    provider_booking_url: str = ""
    manage_url: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    start_at: str = ""
    can_cancel: bool = True
    can_reschedule: bool = True


class PortalBookingsResponse(BaseModel):
    items: List[PortalBookingSummary]
    total: int
    limit: int
    offset: int
    scope: str


class PortalEmployeePayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    role_label: str = Field(default="", max_length=80)
    color: str = Field(default="#00b1d9", min_length=7, max_length=7)
    is_active: bool = True
    timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=80)
    slot_minutes: int = Field(default=30, ge=5, le=240)
    day_start: str = Field(default="09:00", min_length=5, max_length=5)
    day_end: str = Field(default="18:00", min_length=5, max_length=5)
    closed_weekdays: List[int] = Field(default_factory=list)
    service_ids: List[str] = Field(default_factory=list)


class PortalEmployeePublic(BaseModel):
    employee_id: str
    cliente_id: str
    name: str
    role_label: str = ""
    color: str = "#00b1d9"
    is_active: bool = True
    is_default: bool = False
    timezone: str = DEFAULT_TIMEZONE
    slot_minutes: int = 30
    day_start: str = "09:00"
    day_end: str = "18:00"
    closed_weekdays: List[int] = Field(default_factory=list)
    service_ids: List[str] = Field(default_factory=list)
    allows_all_services: bool = True
    bookings_today: int = 0
    bookings_upcoming: int = 0
    blocks: List[PortalAgendaBlock] = Field(default_factory=list)


class PortalEmployeesResponse(BaseModel):
    items: List[PortalEmployeePublic]


class PortalDashboardResponse(BaseModel):
    user: AuthUserPublic
    stats: Dict[str, Any]
    bookings_upcoming: List[PortalBookingSummary]
    bookings_today: List[PortalBookingSummary] = Field(default_factory=list)
    today_blocks: List[PortalAgendaBlock] = Field(default_factory=list)


class PortalMessagePreviewPayload(BaseModel):
    kind: str = Field(min_length=3, max_length=40)
    schedule: PortalScheduleUpdatePayload
    target_email: Optional[EmailStr] = None


class PortalMessagePreviewResponse(BaseModel):
    kind: str
    subject: str
    text_body: str
    html_body: str
    target_email: str = ""
    enabled: bool


class BookingAuditEntry(BaseModel):
    audit_id: int
    booking_id: str
    event_type: str
    title: str
    detail: str = ""
    created_at: str
    source: str = ""
    actor: str = ""


class BookingAuditResponse(BaseModel):
    items: List[BookingAuditEntry]


class PortalCreateUserPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=2, max_length=120)
    cliente_id: str = Field(default="", max_length=80)
    role: str = Field(default="client", max_length=20)


class AdminClientePayload(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    icono: str = Field(default="AI", max_length=12)
    color: str = Field(default="#00b1d9", min_length=7, max_length=7)
    bienvenida: str = Field(min_length=5, max_length=400)
    prompt_extra: str = Field(default="", max_length=2000)
    allowed_origins: List[str] = Field(default_factory=list)
    contacto_email: str = Field(default="", max_length=120)
    contacto_telefono: str = Field(default="", max_length=40)
    branding_text: str = Field(default="Powered by Vantelia", max_length=120)
    whatsapp_enabled: bool = False
    whatsapp_phone_number_id: str = Field(default="", max_length=120)
    whatsapp_access_token_env: str = Field(default="", max_length=120)
    whatsapp_verify_token_env: str = Field(default="", max_length=120)
    booking_enabled: bool = True
    booking_timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=80)
    booking_slot_minutes: int = Field(default=30, ge=5, le=240)
    booking_day_start: str = Field(default="09:00", min_length=5, max_length=5)
    booking_day_end: str = Field(default="18:00", min_length=5, max_length=5)
    booking_closed_weekdays: List[int] = Field(default_factory=lambda: [6])
    booking_provider: str = Field(default="internal", max_length=40)
    booking_webhook_env: str = Field(default="", max_length=80)
    booking_webhook_url: str = Field(default="", max_length=400)
    booking_calendly_user_env: str = Field(default="", max_length=80)
    booking_calendly_event_type_env: str = Field(default="", max_length=80)
    booking_calendly_location_kind: str = Field(default="", max_length=60)
    booking_calendly_location_value: str = Field(default="", max_length=200)
    booking_google_calendar_id: str = Field(default="", max_length=200)
    booking_google_calendar_id_env: str = Field(default="", max_length=80)
    booking_google_service_account_path: str = Field(default="", max_length=400)
    booking_google_service_account_env: str = Field(default="", max_length=80)
    booking_google_service_account_json: str = Field(default="", max_length=20000)
    booking_success_message: str = Field(
        default="Tu solicitud de cita ha quedado registrada correctamente.",
        max_length=400,
    )
    info_txt: str = Field(default="", max_length=120000)
    reindex_after_save: bool = True


class AdminClienteResumen(BaseModel):
    cliente_id: str
    nombre: str
    booking_enabled: bool
    booking_provider: str = "internal"
    booking_timezone: str = DEFAULT_TIMEZONE
    booking_day_start: str = "09:00"
    booking_day_end: str = "18:00"
    allowed_origins: List[str]
    contacto_email: str = ""
    contacto_telefono: str = ""
    branding_text: str = ""
    whatsapp_enabled: bool = False
    whatsapp_phone_number_id: str = ""
    has_info_file: bool
    info_file_size: int = 0
    bookings_total: int = 0
    bookings_pending: int = 0


class AdminClienteDetalle(BaseModel):
    cliente_id: str
    config: AdminClientePayload
    install_snippet: str
    widget_script_url: str
    api_base_url: str
    demo_url: str


class AdminClienteSaveResult(BaseModel):
    status: str
    cliente_id: str
    reindexed: bool
    reindex_error: str
    install_snippet: str
    widget_script_url: str
    api_base_url: str
    demo_url: str


class AdminAltaExpressPayload(BaseModel):
    website_url: str = Field(min_length=4, max_length=400)
    cliente_id: str = Field(min_length=2, max_length=80)
    nombre_bot: str = Field(default="Clara", min_length=2, max_length=40)
    tono: str = Field(default="Profesional y cercano", min_length=4, max_length=80)
    idioma: str = Field(default="Español", min_length=4, max_length=40)
    max_paginas: int = Field(default=12, ge=1, le=30)
    color: str = Field(default="#00b1d9", min_length=7, max_length=7)
    booking_enabled: bool = True
    booking_timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=80)
    auto_save: bool = True
    reindex_after_save: bool = True


class AdminAltaExpressResponse(BaseModel):
    cliente_id: str
    detected_business_name: str
    normalized_url: str
    links_found: int
    config: AdminClientePayload
    saved: bool
    reindexed: bool
    reindex_error: str
    install_snippet: str
    widget_script_url: str
    api_base_url: str
    demo_url: str


def _list_employee_rows(cliente_id: str, *, include_inactive: bool = True) -> List[sqlite3.Row]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if not include_inactive:
        clauses.append("is_active = 1")
    sql = (
        "SELECT * FROM employees WHERE "
        + " AND ".join(clauses)
        + " ORDER BY is_default DESC, is_active DESC, name COLLATE NOCASE ASC"
    )
    with _get_db_connection() as connection:
        return connection.execute(sql, tuple(params)).fetchall()


def _list_public_employee_rows(cliente_id: str, *, include_inactive: bool = False) -> List[sqlite3.Row]:
    return [
        row
        for row in _list_employee_rows(cliente_id, include_inactive=include_inactive)
        if not bool(row["is_default"])
    ]


def _get_employee_row(employee_id: str, *, cliente_id: str = "") -> Optional[sqlite3.Row]:
    clauses = ["id = ?"]
    params: List[Any] = [employee_id]
    if cliente_id:
        clauses.append("cliente_id = ?")
        params.append(cliente_id)
    with _get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM employees WHERE " + " AND ".join(clauses) + " LIMIT 1",
            tuple(params),
        ).fetchone()


def _default_employee_row(cliente_id: str) -> sqlite3.Row:
    with _get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM employees WHERE cliente_id = ? AND is_default = 1 LIMIT 1",
            (cliente_id,),
        ).fetchone()
        if row:
            return row
        row = connection.execute(
            "SELECT * FROM employees WHERE cliente_id = ? ORDER BY is_active DESC, name COLLATE NOCASE ASC LIMIT 1",
            (cliente_id,),
        ).fetchone()
        if row:
            return row
    raise HTTPException(status_code=404, detail="No hay profesionales configurados para este cliente.")


def _resolve_employee_for_booking(
    cliente_id: str,
    employee_id: str = "",
    *,
    require_active: bool = True,
) -> sqlite3.Row:
    row = _get_employee_row(employee_id, cliente_id=cliente_id) if employee_id else None
    if row is None:
        row = _default_employee_row(cliente_id)
    if require_active and not bool(row["is_active"]):
        raise HTTPException(status_code=409, detail="El profesional seleccionado no esta activo.")
    return row


def _public_services_for_booking(cliente_id: str, employee_id: str = "") -> List[Dict[str, str]]:
    if employee_id:
        employee_row = _get_employee_row(employee_id, cliente_id=cliente_id)
        return _services_for_employee(cliente_id, employee_row)

    public_rows = _list_public_employee_rows(cliente_id, include_inactive=False)
    if not public_rows:
        return []

    all_services = _extract_services_from_info(cliente_id)
    if any(not _employee_service_ids_from_row(row, cliente_id) for row in public_rows):
        return all_services

    allowed_ids = {
        service_id
        for row in public_rows
        for service_id in _employee_service_ids_from_row(row, cliente_id)
    }
    return [service for service in all_services if str(service.get("id") or "") in allowed_ids]


def _employee_schedule_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "timezone": row["timezone"] or DEFAULT_TIMEZONE,
        "slot_minutes": int(row["slot_minutes"] or 30),
        "day_start": row["day_start"] or "09:00",
        "day_end": row["day_end"] or "18:00",
        "closed_weekdays": _employee_closed_weekdays_from_row(row),
    }


def _employee_booking_counters(cliente_id: str, employee_id: str) -> Dict[str, int]:
    employee_row = _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    timezone_name = _employee_schedule_from_row(employee_row)["timezone"]
    today = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    now_iso = _utc_now_iso()
    with _get_db_connection() as connection:
        today_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM bookings
            WHERE cliente_id = ?
              AND employee_id = ?
              AND booking_date = ?
              AND status IN ('confirmed', 'pending_review')
            """,
            (cliente_id, employee_id, today),
        ).fetchone()[0]
        upcoming_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM bookings
            WHERE cliente_id = ?
              AND employee_id = ?
              AND status IN ('confirmed', 'pending_review')
              AND (start_at = '' OR start_at >= ?)
            """,
            (cliente_id, employee_id, now_iso),
        ).fetchone()[0]
    return {"today": int(today_count), "upcoming": int(upcoming_count)}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _session_expires_at(hours: int = PORTAL_SESSION_HOURS) -> str:
    return (_utc_now() + timedelta(hours=max(1, hours))).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _expires_at_in_hours(hours: int) -> str:
    safe_hours = max(1, hours)
    return (_utc_now() + timedelta(hours=safe_hours)).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _compound_token_parts(raw_token: str, expected_prefix: str) -> Tuple[str, str]:
    token_value = str(raw_token or "").strip()
    if "." not in token_value:
        return "", ""
    token_id, secret = token_value.split(".", 1)
    if not token_id.startswith(f"{expected_prefix}_") or not secret:
        return "", ""
    return token_id, secret


def _normalize_email(email: str) -> str:
    return str(email).strip().lower()


def _hash_secret(raw_value: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw_value.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def _verify_secret(raw_value: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", raw_value.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return secrets.compare_digest(digest.hex(), expected)


def _serialize_auth_user(row: sqlite3.Row) -> AuthUserPublic:
    return AuthUserPublic(
        user_id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"],
        cliente_id=row["cliente_id"] or "",
        last_login_at=row["last_login_at"] or "",
    )


def _serialize_managed_user(row: sqlite3.Row) -> AuthManagedUser:
    return AuthManagedUser(
        user_id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"],
        cliente_id=row["cliente_id"] or "",
        is_active=bool(row["is_active"]),
        created_at=row["created_at"] or "",
        last_login_at=row["last_login_at"] or "",
    )


def _get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    with _get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM users WHERE email = ?",
            (_normalize_email(email),),
        ).fetchone()


def _get_user_by_id(user_id: str) -> Optional[sqlite3.Row]:
    with _get_db_connection() as connection:
        return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def _list_users(*, role: str = "", cliente_id: str = "", include_inactive: bool = True) -> List[sqlite3.Row]:
    sql = "SELECT * FROM users"
    clauses: List[str] = []
    params: List[Any] = []
    if role:
        clauses.append("role = ?")
        params.append(role)
    if cliente_id:
        clauses.append("cliente_id = ?")
        params.append(cliente_id)
    if not include_inactive:
        clauses.append("is_active = 1")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY role ASC, is_active DESC, display_name COLLATE NOCASE ASC, email COLLATE NOCASE ASC"
    with _get_db_connection() as connection:
        return connection.execute(sql, tuple(params)).fetchall()


def _active_admin_count() -> int:
    with _get_db_connection() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
        ).fetchone()[0]


def _set_user_active(user_id: str, is_active: bool) -> None:
    with _get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id),
        )
        connection.commit()


def _update_user_password(user_id: str, new_password: str) -> None:
    with _get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash_secret(new_password), user_id),
        )
        connection.commit()


def _update_user_profile(user_id: str, *, email: str, display_name: str) -> sqlite3.Row:
    email_norm = _normalize_email(email)
    clean_name = _sanitize_text(display_name)
    if len(clean_name) < 2:
        raise HTTPException(status_code=400, detail="El nombre debe tener al menos 2 caracteres.")

    with _get_db_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE email = ? AND id <> ?",
            (email_norm, user_id),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Ese email ya esta en uso por otro usuario.")

        connection.execute(
            "UPDATE users SET email = ?, display_name = ? WHERE id = ?",
            (email_norm, clean_name, user_id),
        )
        connection.commit()
        updated = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not updated:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        return updated


def _create_user(*, email: str, password: str, role: str, display_name: str, cliente_id: str = "") -> sqlite3.Row:
    user_id = f"usr_{secrets.token_urlsafe(12)}"
    email_norm = _normalize_email(email)
    now_iso = _utc_now_iso()
    password_hash = _hash_secret(password)
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, email, password_hash, role, display_name, cliente_id, is_active, created_at, last_login_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, '')
            """,
            (user_id, email_norm, password_hash, role, display_name.strip(), cliente_id.strip(), now_iso),
        )
        connection.commit()
        return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def _delete_user(user_id: str) -> None:
    with _get_db_connection() as connection:
        connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        connection.commit()


def _ensure_default_portal_admin() -> None:
    if not PORTAL_ADMIN_EMAIL or not PORTAL_ADMIN_PASSWORD:
        return
    existing = _get_user_by_email(PORTAL_ADMIN_EMAIL)
    if existing:
        return
    _create_user(
        email=PORTAL_ADMIN_EMAIL,
        password=PORTAL_ADMIN_PASSWORD,
        role="admin",
        display_name=PORTAL_ADMIN_NAME,
    )
    logger.info("Usuario admin inicial del portal creado para %s", PORTAL_ADMIN_EMAIL)


def _create_auth_session(user_id: str) -> str:
    session_id = f"ses_{secrets.token_urlsafe(10)}"
    session_secret = secrets.token_urlsafe(32)
    now_iso = _utc_now_iso()
    expires_at = _session_expires_at()
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO auth_sessions (id, user_id, session_token_hash, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, _hash_secret(session_secret), now_iso, expires_at, now_iso),
        )
        connection.commit()
    return f"{session_id}.{session_secret}"


def _delete_auth_session(raw_token: str) -> None:
    session_id, session_secret = _compound_token_parts(raw_token, "ses")
    with _get_db_connection() as connection:
        if session_id and session_secret:
            row = connection.execute(
                "SELECT id, session_token_hash FROM auth_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row and _verify_secret(session_secret, row["session_token_hash"]):
                connection.execute("DELETE FROM auth_sessions WHERE id = ?", (session_id,))
                connection.commit()
                return

        rows = connection.execute("SELECT id, session_token_hash FROM auth_sessions").fetchall()
        for row in rows:
            if _verify_secret(raw_token, row["session_token_hash"]):
                connection.execute("DELETE FROM auth_sessions WHERE id = ?", (row["id"],))
                connection.commit()
                return


def _delete_user_auth_sessions(user_id: str, *, keep_session_id: str = "") -> None:
    with _get_db_connection() as connection:
        if keep_session_id:
            connection.execute(
                "DELETE FROM auth_sessions WHERE user_id = ? AND id <> ?",
                (user_id, keep_session_id),
            )
        else:
            connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        connection.commit()


def _cleanup_password_reset_tokens() -> None:
    now_iso = _utc_now_iso()
    with _get_db_connection() as connection:
        connection.execute(
            "DELETE FROM password_reset_tokens WHERE used_at <> '' OR expires_at <= ?",
            (now_iso,),
        )
        connection.commit()


def _create_password_reset_token(user_id: str, requested_from_ip: str = "") -> str:
    reset_id = f"prt_{secrets.token_urlsafe(10)}"
    reset_secret = secrets.token_urlsafe(32)
    now_iso = _utc_now_iso()
    expires_at = _expires_at_in_hours(PASSWORD_RESET_TOKEN_HOURS)
    with _get_db_connection() as connection:
        connection.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
        connection.execute(
            """
            INSERT INTO password_reset_tokens (
                id, user_id, token_hash, created_at, expires_at, used_at, requested_from_ip
            ) VALUES (?, ?, ?, ?, ?, '', ?)
            """,
            (
                reset_id,
                user_id,
                _hash_secret(reset_secret),
                now_iso,
                expires_at,
                requested_from_ip.strip(),
            ),
        )
        connection.commit()
    return f"{reset_id}.{reset_secret}"


def _consume_password_reset_token(public_token: str) -> sqlite3.Row:
    _cleanup_password_reset_tokens()
    reset_id, reset_secret = _compound_token_parts(public_token, "prt")
    if not reset_id or not reset_secret:
        raise HTTPException(status_code=400, detail="El enlace de recuperacion no es valido.")

    with _get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT t.id AS reset_token_id, t.user_id, t.token_hash, t.expires_at, t.used_at, u.*
            FROM password_reset_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.id = ?
            """,
            (reset_id,),
        ).fetchone()
        if not row or not row["is_active"]:
            raise HTTPException(status_code=400, detail="El enlace de recuperacion ya no es valido.")
        if row["used_at"]:
            raise HTTPException(status_code=400, detail="Este enlace de recuperacion ya se ha usado.")
        if not _verify_secret(reset_secret, row["token_hash"]):
            raise HTTPException(status_code=400, detail="El enlace de recuperacion no es valido.")
        if row["expires_at"] <= _utc_now_iso():
            raise HTTPException(status_code=400, detail="El enlace de recuperacion ha caducado.")

        connection.execute(
            "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
            (_utc_now_iso(), reset_id),
        )
        connection.commit()
        return row


def _password_reset_url(public_token: str, request: Optional[Request] = None) -> str:
    base_url = _preferred_public_base_url(request) or ""
    if not base_url:
        raise RuntimeError("No se ha podido construir la URL publica del portal.")
    return f"{base_url}/acceso?reset_token={quote(public_token, safe='')}"


def _send_password_reset_email(user: sqlite3.Row, public_token: str, request: Optional[Request] = None) -> None:
    reset_url = _password_reset_url(public_token, request)
    expires_text = f"{max(1, PASSWORD_RESET_TOKEN_HOURS)} hora(s)"
    subject = "Restablece tu contrasena de Vantelia"
    text_body = (
        f"Hola {user['display_name']},\n\n"
        "Hemos recibido una solicitud para cambiar la contrasena de tu acceso al portal de Vantelia.\n\n"
        f"Abre este enlace para definir una nueva contrasena:\n{reset_url}\n\n"
        f"El enlace caduca en {expires_text}.\n"
        "Si no has pedido este cambio, puedes ignorar este correo.\n"
    )
    html_body = (
        f"<p>Hola {escape(user['display_name'])},</p>"
        "<p>Hemos recibido una solicitud para cambiar la contrasena de tu acceso al portal de Vantelia.</p>"
        f'<p><a href="{escape(reset_url)}">Restablecer contrasena</a></p>'
        f"<p>El enlace caduca en {escape(expires_text)}.</p>"
        "<p>Si no has pedido este cambio, puedes ignorar este correo.</p>"
    )
    _send_email_message(user["email"], subject, text_body, html_body)


def _cleanup_auth_sessions() -> None:
    now_iso = _utc_now_iso()
    with _get_db_connection() as connection:
        connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now_iso,))
        connection.commit()


def _get_session_user(session_token: str) -> Optional[sqlite3.Row]:
    if not session_token:
        return None
    _cleanup_auth_sessions()
    session_id, session_secret = _compound_token_parts(session_token, "ses")
    with _get_db_connection() as connection:
        if session_id and session_secret:
            row = connection.execute(
                """
                SELECT s.id AS session_id, s.session_token_hash, s.expires_at, u.*
                FROM auth_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.id = ? AND u.is_active = 1
                """,
                (session_id,),
            ).fetchone()
            if row and _verify_secret(session_secret, row["session_token_hash"]):
                connection.execute(
                    "UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?",
                    (_utc_now_iso(), row["session_id"]),
                )
                connection.commit()
                return row

        rows = connection.execute(
            """
            SELECT s.id AS session_id, s.session_token_hash, s.expires_at, u.*
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE u.is_active = 1
            """
        ).fetchall()
        for row in rows:
            if _verify_secret(session_token, row["session_token_hash"]):
                connection.execute(
                    "UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?",
                    (_utc_now_iso(), row["session_id"]),
                )
                connection.commit()
                return row
    return None


def _redirect_for_role(role: str) -> str:
    if role == "admin":
        return "/dashboard"
    return "/portal"


def _set_portal_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        PORTAL_COOKIE_NAME,
        raw_token,
        max_age=max(3600, PORTAL_SESSION_HOURS * 3600),
        httponly=True,
        secure=APP_BASE_URL.startswith("https://"),
        samesite="lax",
        domain=PORTAL_COOKIE_DOMAIN or None,
        path="/",
    )


def _clear_portal_cookie(response: Response) -> None:
    response.delete_cookie(PORTAL_COOKIE_NAME, path="/", samesite="lax", domain=PORTAL_COOKIE_DOMAIN or None)


_ensure_default_portal_admin()


def _from_utc_iso(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_FROM_EMAIL)


def _email_sender() -> str:
    if SMTP_FROM_NAME:
        return f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    return SMTP_FROM_EMAIL


def _send_email_message(to_email: str, subject: str, text_body: str, html_body: str = "") -> None:
    if not _smtp_configured():
        raise RuntimeError("El sistema de correo no esta configurado. Revisa SMTP_HOST y SMTP_FROM_EMAIL.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _email_sender()
    message["To"] = to_email
    if SMTP_REPLY_TO:
        message["Reply-To"] = SMTP_REPLY_TO
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
        smtp.ehlo()
        if SMTP_STARTTLS:
            smtp.starttls()
            smtp.ehlo()
        if SMTP_USERNAME:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)


def _preferred_public_base_url(request: Optional[Request] = None) -> str:
    if request is not None:
        return _public_base_url(request)
    return APP_BASE_URL


def _strip_origin(value: str) -> str:
    return _normalize_origin_value(value)


def _get_client_config(cliente_id: str) -> Dict[str, Any]:
    config = CONFIG_CLIENTES.get(cliente_id)
    if not config:
        raise HTTPException(status_code=404, detail="Cliente no configurado")
    return config


def _client_data_dir(cliente_id: str) -> Path:
    target_dir = DATA_DIR / cliente_id
    _ensure_path_within(DATA_DIR, target_dir)
    return target_dir


def _client_info_path(cliente_id: str) -> Path:
    return _client_data_dir(cliente_id) / "info.txt"


def _read_info_txt(cliente_id: str) -> str:
    info_path = _client_info_path(cliente_id)
    if not info_path.exists():
        return ""
    return info_path.read_text(encoding="utf-8")


def _write_info_txt(cliente_id: str, content: str) -> None:
    info_path = _client_info_path(cliente_id)
    info_path.parent.mkdir(parents=True, exist_ok=True)
    info_path.write_text(content.strip() + "\n", encoding="utf-8")


def _client_payload_from_config(config: Dict[str, Any], info_txt: str) -> AdminClientePayload:
    return AdminClientePayload(
        nombre=config["nombre"],
        icono=config["icono"],
        color=config["color"],
        bienvenida=config["bienvenida"],
        prompt_extra=config.get("prompt_extra", ""),
        allowed_origins=list(config.get("allowed_origins", [])),
        contacto_email=config.get("contacto", {}).get("email", ""),
        contacto_telefono=config.get("contacto", {}).get("telefono", ""),
        branding_text=config.get("branding", {}).get("powered_by", "Powered by Vantelia"),
        whatsapp_enabled=bool(config.get("whatsapp", {}).get("enabled", False)),
        whatsapp_phone_number_id=config.get("whatsapp", {}).get("phone_number_id", ""),
        whatsapp_access_token_env=config.get("whatsapp", {}).get("access_token_env", ""),
        whatsapp_verify_token_env=config.get("whatsapp", {}).get("verify_token_env", ""),
        booking_enabled=bool(config.get("booking", {}).get("enabled", False)),
        booking_timezone=config.get("booking", {}).get("timezone", DEFAULT_TIMEZONE),
        booking_slot_minutes=int(config.get("booking", {}).get("slot_minutes", 30)),
        booking_day_start=config.get("booking", {}).get("day_start", "09:00"),
        booking_day_end=config.get("booking", {}).get("day_end", "18:00"),
        booking_closed_weekdays=list(config.get("booking", {}).get("closed_weekdays", [6])),
        booking_provider="internal",
        booking_webhook_env=config.get("booking", {}).get("webhook_env", ""),
        booking_webhook_url=config.get("booking", {}).get("webhook_url", ""),
        booking_calendly_user_env="",
        booking_calendly_event_type_env="",
        booking_calendly_location_kind="",
        booking_calendly_location_value="",
        booking_google_calendar_id="",
        booking_google_calendar_id_env="",
        booking_google_service_account_path="",
        booking_google_service_account_env="",
        booking_google_service_account_json="",
        booking_success_message=config.get("booking", {}).get(
            "success_message",
            "Tu solicitud de cita ha quedado registrada correctamente.",
        ),
        info_txt=info_txt,
        reindex_after_save=True,
    )


def _config_from_admin_payload(cliente_id: str, payload: AdminClientePayload) -> Dict[str, Any]:
    existing_booking = CONFIG_CLIENTES.get(cliente_id, {}).get("booking", {})
    return _normalize_client_config(
        cliente_id,
        {
            "nombre": payload.nombre,
            "icono": payload.icono,
            "color": payload.color,
            "bienvenida": payload.bienvenida,
            "prompt_extra": payload.prompt_extra,
            "allowed_origins": payload.allowed_origins,
            "contacto": {
                "email": payload.contacto_email,
                "telefono": payload.contacto_telefono,
            },
            "branding": {"powered_by": payload.branding_text},
            "whatsapp": {
                "enabled": payload.whatsapp_enabled,
                "phone_number_id": payload.whatsapp_phone_number_id,
                "access_token_env": payload.whatsapp_access_token_env,
                "verify_token_env": payload.whatsapp_verify_token_env,
            },
            "booking": {
                "enabled": payload.booking_enabled,
                "timezone": payload.booking_timezone,
                "slot_minutes": payload.booking_slot_minutes,
                "day_start": payload.booking_day_start,
                "day_end": payload.booking_day_end,
                "closed_weekdays": payload.booking_closed_weekdays,
                "provider": "internal",
                "webhook_env": payload.booking_webhook_env,
                "webhook_url": payload.booking_webhook_url,
                "calendly_user_env": "",
                "calendly_event_type_env": "",
                "calendly_location_kind": "",
                "calendly_location_value": "",
                "google_calendar_id": "",
                "google_calendar_id_env": "",
                "google_service_account_path": "",
                "google_service_account_env": "",
                "success_message": payload.booking_success_message,
                "message_templates": existing_booking.get("message_templates", {}),
                "message_template_enabled": existing_booking.get("message_template_enabled", {}),
            },
        },
    )


def _persist_configs_to_disk(configs: Dict[str, Dict[str, Any]]) -> None:
    serialized = {
        cliente_id: _serialize_client_config(config)
        for cliente_id, config in sorted(configs.items(), key=lambda item: item[0].lower())
    }
    CONFIG_PATH.write_text(
        json.dumps(serialized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _serialize_agenda_block(row: sqlite3.Row) -> PortalAgendaBlock:
    return PortalAgendaBlock(
        block_id=row["id"],
        employee_id=row["employee_id"] or "",
        fecha=row["block_date"],
        hora_inicio=row["start_time"],
        hora_fin=row["end_time"],
        motivo=row["reason"] or "",
        created_at=row["created_at"] or "",
    )


def _list_agenda_blocks(
    cliente_id: str,
    *,
    employee_id: Optional[str] = None,
    include_general: bool = False,
    date_from: str = "",
    date_to: str = "",
) -> List[sqlite3.Row]:
    clauses = ["cliente_id = ?"]
    params: List[Any] = [cliente_id]
    if employee_id is None:
        pass
    elif employee_id:
        if include_general:
            clauses.append("(employee_id = ? OR employee_id = '')")
        else:
            clauses.append("employee_id = ?")
        params.append(employee_id)
    else:
        clauses.append("employee_id = ''")
    if date_from:
        clauses.append("block_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("block_date <= ?")
        params.append(date_to)
    sql = (
        "SELECT * FROM agenda_blocks WHERE "
        + " AND ".join(clauses)
        + " ORDER BY block_date ASC, start_time ASC"
    )
    with _get_db_connection() as connection:
        return connection.execute(sql, tuple(params)).fetchall()


def _agenda_block_date_range(date_from: str, date_to: str = "") -> List[str]:
    start_date = _parse_date(date_from).date()
    end_date = _parse_date(date_to or date_from).date()
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="La fecha final no puede ser anterior a la inicial.")
    total_days = (end_date - start_date).days + 1
    if total_days > 366:
        raise HTTPException(status_code=400, detail="El intervalo de bloqueo no puede superar 366 dias.")
    return [(start_date + timedelta(days=offset)).isoformat() for offset in range(total_days)]


def _create_agenda_blocks(
    cliente_id: str,
    data: PortalAgendaBlockPayload,
    *,
    employee_id: str = "",
) -> Tuple[List[sqlite3.Row], int, str, str]:
    selected_days = _agenda_block_date_range(data.fecha, data.fecha_fin)
    start_time = _parse_time(data.hora_inicio).strftime("%H:%M")
    end_time = _parse_time(data.hora_fin).strftime("%H:%M")
    if start_time >= end_time:
        raise HTTPException(status_code=400, detail="La hora de fin debe ser posterior a la hora de inicio.")
    if employee_id:
        _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    conflicts: List[sqlite3.Row] = []
    for selected_day in selected_days:
        conflicts.extend(
            _booking_conflicts_for_block(
                cliente_id,
                selected_day,
                start_time,
                end_time,
                employee_id=employee_id,
            )
        )
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail=_booking_conflict_message(
                conflicts,
                "Hay citas activas dentro del intervalo solicitado. Cancelalas o reprogramalas antes de bloquear la agenda.",
            ),
        )

    created_at = _utc_now_iso()
    reason = _sanitize_text(data.motivo)
    created_rows: List[sqlite3.Row] = []
    skipped_count = 0
    with _get_db_connection() as connection:
        for selected_day in selected_days:
            existing = connection.execute(
                """
                SELECT *
                FROM agenda_blocks
                WHERE cliente_id = ?
                  AND employee_id = ?
                  AND block_date = ?
                  AND start_time = ?
                  AND end_time = ?
                LIMIT 1
                """,
                (cliente_id, employee_id, selected_day, start_time, end_time),
            ).fetchone()
            if existing:
                skipped_count += 1
                continue

            block_id = f"blk_{secrets.token_urlsafe(10)}"
            connection.execute(
                """
                INSERT INTO agenda_blocks (id, cliente_id, employee_id, block_date, start_time, end_time, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    block_id,
                    cliente_id,
                    employee_id,
                    selected_day,
                    start_time,
                    end_time,
                    reason,
                    created_at,
                ),
            )
            row = connection.execute("SELECT * FROM agenda_blocks WHERE id = ?", (block_id,)).fetchone()
            if row:
                created_rows.append(row)
        connection.commit()
    return created_rows, skipped_count, selected_days[0], selected_days[-1]


def _delete_agenda_block(cliente_id: str, block_id: str, *, employee_id: Optional[str] = None) -> None:
    with _get_db_connection() as connection:
        clauses = ["id = ?", "cliente_id = ?"]
        params: List[Any] = [block_id, cliente_id]
        if employee_id is None:
            pass
        elif employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        else:
            clauses.append("employee_id = ''")
        row = connection.execute(
            "SELECT id FROM agenda_blocks WHERE " + " AND ".join(clauses),
            tuple(params),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Bloqueo no encontrado.")
        connection.execute("DELETE FROM agenda_blocks WHERE id = ?", (block_id,))
        connection.commit()


def _portal_schedule_from_config(cliente_id: str) -> PortalSchedulePublic:
    config = _get_client_config(cliente_id)
    booking = config["booking"]
    today = _utc_now().date().isoformat()
    future_limit = (_utc_now() + timedelta(days=180)).date().isoformat()
    return PortalSchedulePublic(
        enabled=bool(booking.get("enabled", False)),
        timezone=booking.get("timezone", DEFAULT_TIMEZONE),
        slot_minutes=int(booking.get("slot_minutes", 30)),
        day_start=booking.get("day_start", "09:00"),
        day_end=booking.get("day_end", "18:00"),
        closed_weekdays=list(booking.get("closed_weekdays", [])),
        message_templates=_normalize_message_templates(booking.get("message_templates", {})),
        message_template_enabled=_normalize_message_template_enabled(
            booking.get("message_template_enabled", {}),
            booking.get("message_templates", {}),
        ),
        blocks=[
            _serialize_agenda_block(row)
            for row in _list_agenda_blocks(cliente_id, employee_id="", date_from=today, date_to=future_limit)
        ],
    )


def _portal_ai_config_from_client_config(cliente_id: str) -> PortalAiConfigPublic:
    config = _get_client_config(cliente_id)
    return PortalAiConfigPublic(
        nombre=config.get("nombre", cliente_id),
        icono=config.get("icono", "AI"),
        bienvenida=config.get("bienvenida", ""),
        prompt_extra=config.get("prompt_extra", ""),
    )


def _update_portal_ai_config(cliente_id: str, data: PortalAiConfigPayload) -> PortalAiConfigPublic:
    next_configs = copy.deepcopy(CONFIG_CLIENTES)
    config = next_configs.get(cliente_id)
    if not config:
        raise HTTPException(status_code=404, detail="Cliente no configurado")

    config["icono"] = _sanitize_text(data.icono)[:12] or "AI"
    config["bienvenida"] = _sanitize_text(data.bienvenida, allow_multiline=True)[:400]
    config["prompt_extra"] = _sanitize_text(data.prompt_extra, allow_multiline=True)[:2000]

    _validate_single_client_runtime(cliente_id, config)
    _persist_configs_to_disk(next_configs)
    _update_runtime_configs(next_configs)
    return _portal_ai_config_from_client_config(cliente_id)


def _portal_brain_for_client(cliente_id: str) -> PortalBrainPublic:
    return PortalBrainPublic(
        info_txt=_read_info_txt(cliente_id),
        reindexed=False,
        reindex_error="",
    )


def _update_portal_brain(cliente_id: str, data: PortalBrainPayload) -> PortalBrainPublic:
    info_txt = str(data.info_txt or "").strip()
    if not info_txt:
        raise HTTPException(status_code=400, detail="El contenido del cerebro no puede estar vacio.")

    _write_info_txt(cliente_id, info_txt)
    _invalidate_client_runtime(cliente_id)

    reindexed = False
    reindex_error = ""
    try:
        cargar_indice(cliente_id)
        reindexed = True
    except Exception as exc:  # noqa: BLE001
        reindex_error = str(exc)
        logger.warning("No se pudo reindexar automaticamente %s desde el portal: %s", cliente_id, exc)

    return PortalBrainPublic(
        info_txt=_read_info_txt(cliente_id),
        reindexed=reindexed,
        reindex_error=reindex_error,
    )


def _update_client_schedule(cliente_id: str, data: PortalScheduleUpdatePayload) -> PortalSchedulePublic:
    start = _parse_time(data.day_start).strftime("%H:%M")
    end = _parse_time(data.day_end).strftime("%H:%M")
    if start >= end:
        raise HTTPException(status_code=400, detail="La hora de fin debe ser posterior a la hora de inicio.")
    closed_weekdays = sorted({int(day) for day in data.closed_weekdays if 0 <= int(day) <= 6})
    if len(closed_weekdays) != len(set(data.closed_weekdays)):
        closed_weekdays = sorted(set(closed_weekdays))

    next_configs = copy.deepcopy(CONFIG_CLIENTES)
    config = next_configs.get(cliente_id)
    if not config:
        raise HTTPException(status_code=404, detail="Cliente no configurado")
    previous_closed_weekdays = {
        int(day)
        for day in config.get("booking", {}).get("closed_weekdays", [])
        if isinstance(day, int) and 0 <= day <= 6
    }
    newly_closed_weekdays = set(closed_weekdays) - previous_closed_weekdays
    if newly_closed_weekdays:
        conflicts = _booking_conflicts_for_closed_weekdays(cliente_id, newly_closed_weekdays)
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail=_booking_conflict_message(
                    conflicts,
                    "Hay citas activas en los dias que quieres cerrar. Cancelalas o reprogramalas antes de guardar.",
                ),
            )
    booking = dict(config.get("booking", {}))
    booking.update(
        {
            "enabled": bool(data.enabled),
            "timezone": _sanitize_text(data.timezone) or DEFAULT_TIMEZONE,
            "slot_minutes": int(data.slot_minutes),
            "day_start": start,
            "day_end": end,
            "closed_weekdays": closed_weekdays,
            "message_templates": _normalize_message_templates(data.message_templates),
            "message_template_enabled": _normalize_message_template_enabled(
                data.message_template_enabled,
                data.message_templates,
            ),
        }
    )
    config["booking"] = booking
    _validate_single_client_runtime(cliente_id, config)
    _persist_configs_to_disk(next_configs)
    _update_runtime_configs(next_configs)
    return _portal_schedule_from_config(cliente_id)


def _serialize_portal_employee(row: sqlite3.Row) -> PortalEmployeePublic:
    counters = _employee_booking_counters(row["cliente_id"], row["id"])
    today = _utc_now().date().isoformat()
    future_limit = (_utc_now() + timedelta(days=180)).date().isoformat()
    schedule = _employee_schedule_from_row(row)
    is_default = bool(row["is_default"])
    service_ids = _employee_service_ids_from_row(row)
    return PortalEmployeePublic(
        employee_id=row["id"],
        cliente_id=row["cliente_id"],
        name=row["name"],
        role_label=DEFAULT_EMPLOYEE_ROLE_LABEL if is_default else (row["role_label"] or ""),
        color=_normalize_employee_color(row["color"] or "#00b1d9"),
        is_active=bool(row["is_active"]),
        is_default=is_default,
        timezone=schedule["timezone"],
        slot_minutes=schedule["slot_minutes"],
        day_start=schedule["day_start"],
        day_end=schedule["day_end"],
        closed_weekdays=schedule["closed_weekdays"],
        service_ids=service_ids,
        allows_all_services=not service_ids,
        bookings_today=counters["today"],
        bookings_upcoming=counters["upcoming"],
        blocks=[
            _serialize_agenda_block(block)
            for block in _list_agenda_blocks(
                row["cliente_id"],
                employee_id=row["id"],
                date_from=today,
                date_to=future_limit,
            )
        ],
    )


def _portal_employees_for_client(cliente_id: str) -> PortalEmployeesResponse:
    return PortalEmployeesResponse(
        items=[_serialize_portal_employee(row) for row in _list_employee_rows(cliente_id)]
    )


def _validate_employee_payload(cliente_id: str, data: PortalEmployeePayload) -> Dict[str, Any]:
    defaults = _employee_defaults_for_client(cliente_id)
    start = _parse_time(data.day_start).strftime("%H:%M")
    end = _parse_time(data.day_end).strftime("%H:%M")
    if start >= end:
        raise HTTPException(status_code=400, detail="La hora de fin debe ser posterior a la hora de inicio.")
    closed_weekdays = _normalize_closed_weekdays_list(data.closed_weekdays)
    service_ids = _normalize_service_ids_for_client(cliente_id, data.service_ids)
    return {
        "name": _sanitize_text(data.name),
        "role_label": _sanitize_text(data.role_label),
        "color": _normalize_employee_color(data.color, "#00b1d9"),
        "is_active": bool(data.is_active),
        "timezone": _sanitize_text(data.timezone) or defaults["timezone"],
        "slot_minutes": int(data.slot_minutes),
        "day_start": start,
        "day_end": end,
        "closed_weekdays_json": json.dumps(closed_weekdays),
        "closed_weekdays": closed_weekdays,
        "service_ids_json": json.dumps(service_ids),
        "service_ids": service_ids,
    }


def _create_portal_employee(cliente_id: str, data: PortalEmployeePayload) -> PortalEmployeePublic:
    payload = _validate_employee_payload(cliente_id, data)
    created_at = _utc_now_iso()
    employee_id = f"emp_{secrets.token_urlsafe(8)}"
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO employees (
                id, cliente_id, name, role_label, color, is_active, is_default,
                timezone, slot_minutes, day_start, day_end, closed_weekdays_json, service_ids_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                cliente_id,
                payload["name"],
                payload["role_label"],
                payload["color"],
                1 if payload["is_active"] else 0,
                payload["timezone"],
                payload["slot_minutes"],
                payload["day_start"],
                payload["day_end"],
                payload["closed_weekdays_json"],
                payload["service_ids_json"],
                created_at,
                created_at,
            ),
        )
        connection.commit()
    row = _get_employee_row(employee_id, cliente_id=cliente_id)
    if not row:
        raise HTTPException(status_code=500, detail="No se ha podido crear el profesional.")
    return _serialize_portal_employee(row)


def _active_future_bookings_for_employee(cliente_id: str, employee_id: str) -> int:
    with _get_db_connection() as connection:
        return int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM bookings
                WHERE cliente_id = ?
                  AND employee_id = ?
                  AND status IN ('confirmed', 'pending_review')
                  AND (start_at = '' OR start_at >= ?)
                """,
                (cliente_id, employee_id, _utc_now_iso()),
            ).fetchone()[0]
        )


def _update_portal_employee(cliente_id: str, employee_id: str, data: PortalEmployeePayload) -> PortalEmployeePublic:
    row = _get_employee_row(employee_id, cliente_id=cliente_id)
    if not row:
        raise HTTPException(status_code=404, detail="Profesional no encontrado.")
    payload = _validate_employee_payload(cliente_id, data)
    if row["is_default"]:
        payload["role_label"] = DEFAULT_EMPLOYEE_ROLE_LABEL
    if row["is_default"] and not payload["is_active"]:
        raise HTTPException(status_code=409, detail="La agenda principal no se puede desactivar.")
    if not payload["is_active"] and _active_future_bookings_for_employee(cliente_id, employee_id):
        raise HTTPException(
            status_code=409,
            detail="Este profesional tiene citas futuras activas. Reasignalas o reprogramalas antes de desactivarlo.",
        )
    with _get_db_connection() as connection:
        connection.execute(
            """
            UPDATE employees
            SET name = ?, role_label = ?, color = ?, is_active = ?, timezone = ?,
                slot_minutes = ?, day_start = ?, day_end = ?, closed_weekdays_json = ?, service_ids_json = ?, updated_at = ?
            WHERE id = ? AND cliente_id = ?
            """,
            (
                payload["name"],
                payload["role_label"],
                payload["color"],
                1 if payload["is_active"] else 0,
                payload["timezone"],
                payload["slot_minutes"],
                payload["day_start"],
                payload["day_end"],
                payload["closed_weekdays_json"],
                payload["service_ids_json"],
                _utc_now_iso(),
                employee_id,
                cliente_id,
            ),
        )
        connection.execute(
            """
            UPDATE bookings
            SET employee_name = ?
            WHERE cliente_id = ? AND employee_id = ?
            """,
            (payload["name"], cliente_id, employee_id),
        )
        connection.commit()
    refreshed = _get_employee_row(employee_id, cliente_id=cliente_id)
    if not refreshed:
        raise HTTPException(status_code=404, detail="Profesional no encontrado.")
    return _serialize_portal_employee(refreshed)


def _prepare_admin_payload(cliente_id: str, payload: AdminClientePayload) -> AdminClientePayload:
    _ = cliente_id
    return payload.model_copy(
        update={
            "booking_provider": "internal",
            "booking_calendly_user_env": "",
            "booking_calendly_event_type_env": "",
            "booking_calendly_location_kind": "",
            "booking_calendly_location_value": "",
            "booking_google_calendar_id": "",
            "booking_google_calendar_id_env": "",
            "booking_google_service_account_path": "",
            "booking_google_service_account_env": "",
            "booking_google_service_account_json": "",
        }
    )


def _save_admin_client_payload(
    cliente_id: str,
    data: AdminClientePayload,
    request: Request,
) -> AdminClienteSaveResult:
    if not data.info_txt.strip():
        raise HTTPException(status_code=400, detail="`info_txt` no puede estar vacio.")

    try:
        data = _prepare_admin_payload(cliente_id, data)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    next_config = _config_from_admin_payload(cliente_id, data)
    _validate_single_client_runtime(cliente_id, next_config)

    next_configs = dict(CONFIG_CLIENTES)
    next_configs[cliente_id] = next_config

    _persist_configs_to_disk(next_configs)
    _write_info_txt(cliente_id, data.info_txt)
    _update_runtime_configs(next_configs)
    _invalidate_client_runtime(cliente_id)

    reindexed = False
    reindex_error = ""
    if data.reindex_after_save:
        try:
            cargar_indice(cliente_id)
            reindexed = True
        except Exception as exc:  # noqa: BLE001
            reindex_error = str(exc)
            logger.warning("No se pudo reindexar automaticamente %s: %s", cliente_id, exc)

    snippet = _build_install_snippet(cliente_id, request)
    return AdminClienteSaveResult(
        status="ok",
        cliente_id=cliente_id,
        reindexed=reindexed,
        reindex_error=reindex_error,
        install_snippet=snippet["install_snippet"],
        widget_script_url=snippet["widget_script_url"],
        api_base_url=snippet["api_base_url"],
        demo_url=snippet["demo_url"],
    )


def _invalidate_client_runtime(cliente_id: str) -> None:
    with state_lock:
        indices.pop(cliente_id, None)
        for session_id in [sid for sid, session in sesiones.items() if session.cliente_id == cliente_id]:
            sesiones.pop(session_id, None)

    ruta_storage = STORAGE_DIR / cliente_id
    _ensure_path_within(STORAGE_DIR, ruta_storage)
    if ruta_storage.exists():
        shutil.rmtree(ruta_storage)


def _build_install_snippet(cliente_id: str, request: Request) -> Dict[str, str]:
    api_base = _public_base_url(request)
    widget_version = ""
    widget_path = WIDGET_DIR / "widget.min.js"
    if widget_path.exists():
        widget_version = f"?v={int(widget_path.stat().st_mtime)}"

    widget_script_url = f"{api_base}/widget/widget.min.js{widget_version}"
    demo_url = f"{api_base}/demo/{cliente_id}"
    snippet = (
        '<script\n'
        f'  src="{widget_script_url}"\n'
        f'  data-api="{api_base}"\n'
        f'  data-client="{cliente_id}"\n'
        '  data-position="right"></script>'
    )
    return {
        "install_snippet": snippet,
        "widget_script_url": widget_script_url,
        "api_base_url": api_base,
        "demo_url": demo_url,
    }


def _build_demo_page(cliente_id: str, request: Request) -> str:
    config = _get_client_config(cliente_id)
    assets = _build_install_snippet(cliente_id, request)
    nombre = escape(config["nombre"])
    bienvenida = escape(config["bienvenida"])
    color = escape(config["color"])
    contacto_email = escape(config.get("contacto", {}).get("email", ""))
    contacto_telefono = escape(config.get("contacto", {}).get("telefono", ""))
    booking_label = "Reserva online activa" if config["booking"]["enabled"] else "Chat informativo activo"
    powered_by = escape(config.get("branding", {}).get("powered_by", "Powered by Vantelia"))
    script_url = escape(assets["widget_script_url"])
    api_base_url = escape(assets["api_base_url"])
    install_snippet = escape(assets["install_snippet"])
    cliente_safe = escape(cliente_id)
    logo_url = escape(_brand_asset_public_path("Logo_1_sin_resplandor.png"))
    favicon_url = escape(_brand_asset_public_path("favicon.png"))
    fondo_url = escape(_brand_asset_public_path("Fondo_Web.png"))

    contact_chunks: List[str] = []
    if contacto_telefono:
        contact_chunks.append(f"<span>Telefono: {contacto_telefono}</span>")
    if contacto_email:
        contact_chunks.append(f"<span>Email: {contacto_email}</span>")

    contact_html = "\n".join(contact_chunks) if contact_chunks else "<span>Contacto humano configurable desde el panel admin.</span>"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Demo de {nombre} | Vantelia</title>
  <meta name="robots" content="noindex, nofollow" />
  <link rel="icon" type="image/png" href="{favicon_url}" />
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700;800&family=Poppins:wght@400;500;600;700&display=swap');
    :root {{
      color-scheme: dark;
      --accent: {color};
      --accent-2: #00b1d9;
      --bg: #000b29;
      --ink: #f0f4f8;
      --soft: #b8c0cc;
      --line: rgba(184, 192, 204, 0.14);
      --card: rgba(5, 14, 38, 0.88);
      --shadow: 0 28px 80px rgba(0, 0, 0, 0.36);
      --radius-xl: 28px;
      --radius-lg: 20px;
      --font-title: "Montserrat", "Segoe UI", sans-serif;
      --font: "Poppins", "Segoe UI", sans-serif;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: var(--font);
      color: var(--ink);
      background:
        linear-gradient(180deg, rgba(0, 11, 41, 0.88), rgba(0, 11, 41, 0.96)),
        radial-gradient(circle at top right, rgba(0, 177, 217, 0.2), transparent 24%),
        radial-gradient(circle at top left, rgba(184, 192, 204, 0.08), transparent 28%),
        url("{fondo_url}") center top / cover fixed no-repeat;
    }}

    .page {{
      min-height: 100vh;
      padding: 32px 18px 120px;
    }}

    .shell {{
      max-width: 1120px;
      margin: 0 auto;
      display: grid;
      gap: 18px;
    }}

    .hero {{
      padding: 34px;
      border-radius: var(--radius-xl);
      background:
        radial-gradient(circle at top right, rgba(0, 177, 217, 0.22), transparent 30%),
        linear-gradient(145deg, #00163f, #000b29 58%, #00344f);
      color: #fff;
      box-shadow: var(--shadow);
      display: grid;
      gap: 18px;
      position: relative;
      overflow: hidden;
    }}

    .hero::after {{
      content: "";
      position: absolute;
      width: 360px;
      height: 360px;
      right: -120px;
      bottom: -160px;
      background: radial-gradient(circle, rgba(0, 177, 217, 0.34), transparent 70%);
      pointer-events: none;
    }}

    .hero-brand {{
      display: flex;
      align-items: center;
      gap: 18px;
      position: relative;
      z-index: 1;
    }}

    .hero-brand img {{
      width: 72px;
      height: 72px;
      object-fit: contain;
      filter: drop-shadow(0 0 22px rgba(0, 177, 217, 0.32));
      flex: 0 0 auto;
    }}

    .hero-copy {{
      display: grid;
      gap: 10px;
    }}

    .eyebrow {{
      display: inline-flex;
      width: fit-content;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(0, 177, 217, 0.14);
      font-size: 13px;
      letter-spacing: 0.02em;
    }}

    .hero h1 {{
      margin: 0;
      font-family: var(--font-title);
      font-size: clamp(2rem, 4vw, 3.4rem);
      line-height: 0.98;
    }}

    .hero p {{
      margin: 0;
      font-size: 1.05rem;
      line-height: 1.7;
      max-width: 760px;
      color: rgba(240, 244, 248, 0.9);
    }}

    .hero-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}

    .hero-actions a,
    .hero-actions button {{
      appearance: none;
      border: 0;
      text-decoration: none;
      cursor: pointer;
      border-radius: 999px;
      padding: 12px 18px;
      font: inherit;
      font-weight: 800;
    }}

    .hero-actions a {{
      background: rgba(0, 177, 217, 0.12);
      color: #f0f4f8;
      border: 1px solid rgba(184, 192, 204, 0.18);
    }}

    .hero-actions button {{
      background: rgba(0, 177, 217, 0.16);
      color: #fff;
      border: 1px solid rgba(0, 177, 217, 0.24);
    }}

    .grid {{
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 18px;
    }}

    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow);
      padding: 24px;
      backdrop-filter: blur(18px);
    }}

    .card h2 {{
      margin: 0 0 12px;
      font-size: 1.1rem;
      font-family: var(--font-title);
    }}

    .card p {{
      margin: 0;
      color: var(--soft);
      line-height: 1.7;
    }}

    .meta {{
      display: grid;
      gap: 12px;
    }}

    .pill {{
      display: inline-flex;
      width: fit-content;
      align-items: center;
      gap: 10px;
      border-radius: 999px;
      background: rgba(0, 177, 217, 0.12);
      padding: 10px 14px;
      color: var(--accent);
      font-weight: 700;
    }}

    .pill::before {{
      content: "";
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 6px rgba(0, 177, 217, 0.12);
    }}

    .list {{
      display: grid;
      gap: 10px;
      margin-top: 18px;
    }}

    .list span {{
      display: block;
      color: var(--soft);
      line-height: 1.6;
    }}

    .note {{
      font-size: 14px;
      color: var(--soft);
    }}

    .footer {{
      text-align: center;
      color: var(--soft);
      font-size: 13px;
      padding-top: 6px;
    }}

    code {{
      font-family: Consolas, monospace;
      background: rgba(184, 192, 204, 0.08);
      border-radius: 8px;
      padding: 3px 7px;
      color: #d9f8ff;
    }}

    pre {{
      overflow: auto;
      white-space: pre-wrap;
      background: rgba(2, 8, 23, 0.82);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px;
      color: #d9f8ff;
      line-height: 1.5;
    }}

    @media (max-width: 900px) {{
      .grid {{
        grid-template-columns: 1fr;
      }}

      .hero {{
        padding: 24px;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <div class="shell">
      <section class="hero">
        <div class="hero-brand">
          <img src="{logo_url}" alt="Vantelia" />
          <div class="hero-copy">
            <span class="eyebrow">Validacion previa a instalacion</span>
            <h1>{nombre}</h1>
            <p>{bienvenida}</p>
          </div>
        </div>
        <div class="hero-actions">
          <button type="button" id="openChatBtn">Probar chat</button>
          <a href="{escape(assets["api_base_url"])}/dashboard" target="_blank" rel="noreferrer">Abrir panel admin</a>
        </div>
      </section>

      <section class="grid">
        <article class="card">
          <h2>Checklist de validacion</h2>
          <p>
            Usa esta pagina como control final antes de instalar el widget en la web del cliente.
            El chat esta conectado al cerebro de <strong>{nombre}</strong> y sirve para validar respuestas, tono y reserva online.
          </p>
          <div class="list">
            <span>1. Prueba servicios, precios, horarios, objeciones y dudas frecuentes.</span>
            <span>2. Comprueba que no inventa datos y que deriva a humano cuando toca.</span>
            <span>3. Lanza una solicitud de cita y revisa emails, estado y enlace de gestion.</span>
            <span>4. Si algo falla, vuelve al panel, ajusta info.txt, guarda y reindexa.</span>
          </div>
        </article>

        <aside class="card meta">
          <h2>Estado de la demo</h2>
          <span class="pill">{escape(booking_label)}</span>
          <span class="note">Cliente interno: <code>{cliente_safe}</code></span>
          <div class="list">
            {contact_html}
            <span>URL base API: <code>{escape(assets["api_base_url"])}</code></span>
            <span>Marca visible: {powered_by}</span>
          </div>
        </aside>
      </section>

      <section class="card">
        <h2>Snippet de instalacion</h2>
        <p>Pega este bloque antes de cerrar el <code>body</code> de la web final cuando la demo este validada.</p>
        <pre><code id="snippetCode">{install_snippet}</code></pre>
        <div class="hero-actions">
          <button type="button" id="copySnippetBtn">Copiar snippet</button>
          <a href="{escape(assets["demo_url"])}" target="_blank" rel="noreferrer">Abrir esta demo</a>
        </div>
      </section>

      <div class="footer">
        Esta demo esta servida desde Vantelia para validacion previa a instalacion.
      </div>
    </div>
  </main>

  <script>
    window.IA_WIDGET_API = "{api_base_url}";
    window.IA_WIDGET_CLIENTE = "{cliente_safe}";
    window.IA_WIDGET_OPEN_ON_LOAD = true;
  </script>
  <script
    src="{script_url}"
    data-api="{api_base_url}"
    data-client="{cliente_safe}"
    data-position="right"></script>
  <script>
    function openDemoChat() {{
      let attempts = 0;

      function tryOpen() {{
        const button = document.getElementById("ia-w-btn");
        if (button) {{
          if (button.getAttribute("aria-expanded") !== "true") {{
            button.click();
          }}
          return;
        }}

        attempts += 1;
        if (attempts < 20) {{
          window.setTimeout(tryOpen, 200);
        }}
      }}

      tryOpen();
    }}

    document.getElementById("openChatBtn")?.addEventListener("click", openDemoChat);
    document.getElementById("copySnippetBtn")?.addEventListener("click", async function () {{
      await navigator.clipboard.writeText(document.getElementById("snippetCode")?.textContent || "");
      this.textContent = "Snippet copiado";
    }});
    window.addEventListener("load", function () {{
      window.setTimeout(openDemoChat, 300);
    }});
  </script>
</body>
</html>
"""


def _default_admin_payload(cliente_id: str) -> AdminClientePayload:
    display_name = cliente_id.replace("_", " ").strip() or "Nuevo cliente"
    return AdminClientePayload(
        nombre=display_name.title(),
        icono="AI",
        color="#00b1d9",
        bienvenida=f"Hola, soy el asistente de {display_name.title()}. En que puedo ayudarte hoy?",
        prompt_extra=(
            "Habla con tono profesional, mantente dentro del contexto del negocio y "
            "deriva al equipo humano cuando falte informacion."
        ),
        allowed_origins=["https://www.vantelia.es"],
        contacto_email="",
        contacto_telefono="",
        branding_text="Powered by Vantelia",
        booking_enabled=True,
        booking_timezone=DEFAULT_TIMEZONE,
        booking_slot_minutes=30,
        booking_day_start="09:00",
        booking_day_end="18:00",
        booking_closed_weekdays=[6],
        booking_provider="internal",
        booking_webhook_env="WEBHOOK_DEFAULT",
        booking_webhook_url="",
        booking_calendly_user_env="",
        booking_calendly_event_type_env="",
        booking_calendly_location_kind="",
        booking_calendly_location_value="",
        booking_google_calendar_id_env="",
        booking_google_service_account_env="",
        booking_success_message="Tu solicitud de cita ha quedado registrada correctamente.",
        info_txt=(
            f"===== INFORMACION DE {display_name.upper()} =====\n\n"
            "DATOS GENERALES:\n"
            f"- Nombre: {display_name.title()}\n"
            "- Tipo de negocio: No especificado\n"
            "- Descripcion: No especificado\n"
            "- Eslogan: No especificado\n"
        ),
        reindex_after_save=True,
    )


def _payload_from_alta_express(
    *,
    cliente_id: str,
    result: Any,
    nombre_bot: str,
    tono: str,
    idioma: str,
    color: str,
    booking_enabled: bool,
    booking_timezone: str,
) -> AdminClientePayload:
    website_variants = []
    parsed = urlparse(result.normalized_url)
    base_domain = parsed.netloc.replace("www.", "")
    primary_origin = f"{parsed.scheme}://{parsed.netloc}"
    website_variants.append(primary_origin)
    if "." in base_domain and not re.match(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$", parsed.netloc):
        if parsed.netloc.startswith("www."):
            website_variants.append(f"{parsed.scheme}://{base_domain}")
        else:
            website_variants.append(f"{parsed.scheme}://www.{base_domain}")

    allowed_origins = []
    for origin in website_variants:
        if origin not in allowed_origins:
            allowed_origins.append(origin)

    company_name = _sanitize_text(result.detected_business_name) or cliente_id.replace("_", " ").title()

    return AdminClientePayload(
        nombre=company_name,
        icono=nombre_bot[:2].upper() or "AI",
        color=color,
        bienvenida=result.suggested_welcome,
        prompt_extra=(
            f"Habla con tono {tono.lower()}, mantente dentro del contexto del negocio, "
            "responde solo con informacion apoyada en la base documental y deriva al equipo humano "
            "cuando falten datos."
        ),
        allowed_origins=allowed_origins,
        contacto_email="",
        contacto_telefono="",
        branding_text="Powered by Vantelia",
        booking_enabled=booking_enabled,
        booking_timezone=booking_timezone,
        booking_slot_minutes=30,
        booking_day_start="09:00",
        booking_day_end="18:00",
        booking_closed_weekdays=[6],
        booking_provider="internal",
        booking_webhook_env="WEBHOOK_DEFAULT",
        booking_webhook_url="",
        booking_calendly_user_env="",
        booking_calendly_event_type_env="",
        booking_calendly_location_kind="",
        booking_calendly_location_value="",
        booking_google_calendar_id_env="",
        booking_google_service_account_env="",
        booking_success_message="Tu solicitud de cita ha quedado registrada correctamente.",
        info_txt=result.info_txt,
        reindex_after_save=True,
    )


def _assert_valid_client_id(cliente_id: str) -> None:
    if not CLIENT_ID_PATTERN.match(cliente_id):
        raise HTTPException(status_code=400, detail="cliente_id invalido")


def _normalize_session_id(session_id: Optional[str]) -> str:
    if session_id and SESSION_ID_PATTERN.match(session_id):
        return session_id
    return f"s_{secrets.token_urlsafe(24)}"


def _cleanup_sessions(force: bool = False) -> None:
    global last_cleanup_run

    now = time.time()
    with state_lock:
        if not force and now - last_cleanup_run < 60:
            return

        expired_ids = [
            session_id
            for session_id, session in sesiones.items()
            if now - session.last_seen > SESSION_TTL_SECONDS
        ]
        for session_id in expired_ids:
            sesiones.pop(session_id, None)

        stale_buckets = [
            bucket_key
            for bucket_key, timestamps in rate_limit_buckets.items()
            if not any(now - timestamp < RATE_LIMIT_WINDOW_SECONDS for timestamp in timestamps)
        ]
        for bucket_key in stale_buckets:
            rate_limit_buckets.pop(bucket_key, None)

        last_cleanup_run = now

    if expired_ids:
        logger.info("Sesiones expiradas eliminadas: %s", len(expired_ids))


def _check_rate_limit(bucket_key: str, limit: int) -> None:
    now = time.time()
    with state_lock:
        bucket = rate_limit_buckets.setdefault(bucket_key, [])
        bucket[:] = [timestamp for timestamp in bucket if now - timestamp < RATE_LIMIT_WINDOW_SECONDS]
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Se ha alcanzado el limite temporal de peticiones.",
            )
        bucket.append(now)


def _request_origin(request: Request) -> str:
    origin = request.headers.get("origin", "").strip()
    if origin:
        try:
            return _strip_origin(origin)
        except RuntimeError:
            return ""

    referer = request.headers.get("referer", "").strip()
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            try:
                return _strip_origin(f"{parsed.scheme}://{parsed.netloc}")
            except RuntimeError:
                return ""

    return ""


def _forwarded_header_value(raw_value: str) -> str:
    return str(raw_value or "").split(",", 1)[0].strip()


def _public_base_url(request: Request) -> str:
    forwarded_proto = _forwarded_header_value(request.headers.get("x-forwarded-proto", ""))
    forwarded_host = _forwarded_header_value(request.headers.get("x-forwarded-host", ""))
    forwarded_port = _forwarded_header_value(request.headers.get("x-forwarded-port", ""))

    scheme = forwarded_proto or request.url.scheme or "http"
    host = forwarded_host or request.headers.get("host", "").strip() or request.url.netloc

    if not host:
        return str(request.base_url).rstrip("/")

    if forwarded_port and ":" not in host:
        is_default_port = (scheme == "http" and forwarded_port == "80") or (
            scheme == "https" and forwarded_port == "443"
        )
        if not is_default_port:
            host = f"{host}:{forwarded_port}"

    return f"{scheme}://{host}".rstrip("/")


def _enforce_allowed_origin(request: Request, cliente_id: str) -> None:
    config = _get_client_config(cliente_id)
    allowed_origins = set(config.get("allowed_origins", []))
    app_origin = _normalize_origin_value(_public_base_url(request))
    allowed_origins.add(app_origin)
    request_origin = _request_origin(request)

    if allowed_origins and not request_origin:
        raise HTTPException(
            status_code=403,
            detail="No se ha podido verificar el dominio de origen de la peticion.",
        )

    if request_origin and allowed_origins and request_origin not in allowed_origins:
        raise HTTPException(status_code=403, detail="Dominio no autorizado para este cliente")


def _get_authenticated_portal_user_or_none(
    portal_session: Optional[str],
) -> Optional[sqlite3.Row]:
    if not portal_session:
        return None
    return _get_session_user(portal_session)


def _require_authenticated_portal_user(
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
) -> sqlite3.Row:
    user = _get_authenticated_portal_user_or_none(portal_session)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesion no valida o expirada.")
    return user


def _require_authenticated_admin_user(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> sqlite3.Row:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso solo para administradores.")
    return user


def _load_managed_user_or_404(user_id: str) -> sqlite3.Row:
    row = _get_user_by_id(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    return row


def _assert_admin_can_manage_user(current_user: sqlite3.Row, target_user: sqlite3.Row, action: str) -> None:
    if current_user["id"] == target_user["id"]:
        raise HTTPException(status_code=400, detail=f"No puedes {action} tu propio usuario desde este menu.")
    if target_user["role"] == "admin" and _active_admin_count() <= 1:
        raise HTTPException(
            status_code=400,
            detail="No puedes dejar el portal sin ningun administrador activo.",
        )


def _portal_client_id_or_403(user: sqlite3.Row, cliente_id: str = "") -> str:
    requested_client_id = str(cliente_id or "").strip()
    if user["role"] == "admin":
        if not requested_client_id:
            raise HTTPException(status_code=403, detail="Indica el cliente que quieres abrir en el portal.")
        _get_client_config(requested_client_id)
        return requested_client_id
    user_client_id = user["cliente_id"] or ""
    if not user_client_id:
        raise HTTPException(status_code=403, detail="Tu usuario no tiene cliente asociado.")
    if requested_client_id and requested_client_id != user_client_id:
        raise HTTPException(status_code=403, detail="No tienes acceso a ese cliente.")
    _get_client_config(user_client_id)
    return user_client_id


def _require_admin_token(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
) -> None:
    portal_user = _get_authenticated_portal_user_or_none(portal_session)
    if portal_user and portal_user["role"] == "admin":
        return

    if not ADMIN_API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Los endpoints de administracion no estan habilitados.",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta token admin o sesion valida.")

    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, ADMIN_API_TOKEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token admin invalido")


def _build_system_prompt(cliente_id: str, config: Dict[str, Any]) -> str:
    nombre_empresa = config["nombre"]
    prompt_extra = config.get("prompt_extra", "")
    booking_enabled = config["booking"]["enabled"]
    contacto = config.get("contacto", {})
    contact_lines = []
    if contacto.get("telefono"):
        contact_lines.append(f"- Telefono del negocio: {contacto['telefono']}")
    if contacto.get("email"):
        contact_lines.append(f"- Email del negocio: {contacto['email']}")
    booking_rule = (
        f"5. Si el usuario pide claramente reservar, agendar o solicitar una cita, "
        f"anade al final {BOOKING_SENTINEL}."
        if booking_enabled
        else "5. No ofrezcas reserva automatica porque este cliente no la tiene habilitada."
    )

    return f"""
Eres el asistente virtual oficial de {nombre_empresa}.
{prompt_extra}

Datos de contacto verificados:
{chr(10).join(contact_lines) if contact_lines else "- No se han configurado datos de contacto publicos."}

Reglas obligatorias:
1. Solo puedes responder con informacion apoyada en los documentos del cliente.
2. Si la consulta se sale del contexto del negocio, di con claridad que solo ayudas sobre {nombre_empresa}.
3. No inventes datos, promociones, horarios, politicas ni precios.
4. Si no encuentras la informacion, responde: "No tengo esa informacion disponible ahora mismo, pero puedo derivarte al equipo humano."
{booking_rule}
6. Si el usuario pide contacto humano y existen telefono o email configurados, compartelos.
7. Si el usuario pide ver el formulario, reservar, pedir cita, escoger hora o iniciar una solicitud de cita, debes anadir {BOOKING_SENTINEL}.
8. No anadas {BOOKING_SENTINEL} en consultas informativas normales.
9. Responde con tono profesional, claro y breve.
10. Puedes actuar como diagnostico inteligente, recomendador de servicios, estimador o comparador cuando el usuario lo pida.
11. En diagnosticos, estimaciones y comparativas, haz preguntas si faltan datos y evita conclusiones absolutas.
12. En recomendaciones, usa solo servicios, precios, condiciones y politicas presentes en la base documental.
""".strip()


BOOKING_INTENT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\b(agendar|agenda|reservar|reserva|pedir cita|solicitar cita|quiero una cita)\b",
        r"\b(formulario|mostrar formulario|ensename el formulario|enséñame el formulario)\b",
        r"\b(coger cita|quiero agendar|quiero reservar|quiero pedir cita)\b",
    ]
]


def _message_requests_booking_form(message: str) -> bool:
    normalized = " ".join(str(message or "").lower().split())
    return any(pattern.search(normalized) for pattern in BOOKING_INTENT_PATTERNS)


COMMERCIAL_INTENT_LABELS = {
    "diagnostico": "diagnostico inteligente",
    "recomendador": "recomendador de servicios",
    "estimador": "calculadora o estimador",
    "comparador": "comparador de opciones",
    "booking": "agenda",
}


COMMERCIAL_INTENT_PATTERNS: Dict[str, List[re.Pattern[str]]] = {
    "diagnostico": [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\b(diagnostico|diagnóstico|test|orientame|oriÃ©ntame|evaluacion|evaluaciÃ³n)\b",
            r"\b(que necesito|qu[eé] necesito|analiza mi caso|mi caso)\b",
        ]
    ],
    "recomendador": [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\b(recomienda|recomiendame|recomi[eé]ndame|recomendacion|recomendaciÃ³n)\b",
            r"\b(que servicio|qu[eé] servicio|mejor opcion|mejor opciÃ³n|cual me conviene|cu[aá]l me conviene)\b",
        ]
    ],
    "estimador": [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\b(calcula|calculadora|estimacion|estimaciÃ³n|estimar|presupuesto|precio|coste|cuanto cuesta|cu[aá]nto cuesta)\b",
            r"\b(rango de precio|desde cuanto|desde cu[aá]nto|aproximado)\b",
        ]
    ],
    "comparador": [
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\b(compara|comparar|comparador|diferencia|diferencias|versus| vs )\b",
            r"\b(entre .+ y .+|mejor .+ o .+)\b",
        ]
    ],
}


COMMERCIAL_INTENT_INSTRUCTIONS = {
    "diagnostico": (
        "Modo diagnostico inteligente: orienta al usuario con 3-5 preguntas breves si faltan datos. "
        "Despues entrega una recomendacion prudente, explica por que encaja y ofrece siguiente paso. "
        "No diagnostiques temas medicos, legales o financieros de forma concluyente; deriva a revision humana."
    ),
    "recomendador": (
        "Modo recomendador de servicios: identifica objetivo, urgencia, presupuesto aproximado y contexto. "
        "Recomienda solo servicios presentes en la base documental, da alternativas y termina con una accion clara."
    ),
    "estimador": (
        "Modo calculadora o estimador: pide las variables necesarias para estimar. "
        "Si hay precios documentados, usa rangos o condiciones verificadas. Si no los hay, dilo y calcula solo una orientacion cualitativa."
    ),
    "comparador": (
        "Modo comparador de opciones: compara en tabla o bullets criterios como objetivo, plazo, coste, dificultad, encaje y siguiente paso. "
        "No inventes diferencias si la base documental no las respalda."
    ),
}


def _detect_commercial_intent(message: str) -> str:
    normalized = f" {' '.join(str(message or '').lower().split())} "
    if _message_requests_booking_form(normalized):
        return "booking"
    for intent, patterns in COMMERCIAL_INTENT_PATTERNS.items():
        if any(pattern.search(normalized) for pattern in patterns):
            return intent
    return ""


def _build_intent_enhanced_message(message: str, intent: str) -> str:
    instruction = COMMERCIAL_INTENT_INSTRUCTIONS.get(intent)
    if not instruction:
        return message
    return f"{instruction}\n\nMensaje del usuario: {message}"


def _safe_json_list(raw_value: str) -> List[str]:
    try:
        parsed = json.loads(raw_value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _ensure_chat_session_record(
    session_id: str,
    cliente_id: str,
    request: Request,
    *,
    origin_override: str = "",
    user_agent_override: str = "",
) -> None:
    now_iso = _utc_now_iso()
    origin = origin_override or _request_origin(request)
    user_agent = user_agent_override or _sanitize_text(request.headers.get("user-agent", ""), allow_multiline=False)[:500]
    with _get_db_connection() as connection:
        row = connection.execute(
            "SELECT id FROM chat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row:
            return
        connection.execute(
            """
            INSERT INTO chat_sessions (
                id, cliente_id, origin, user_agent, started_at, last_message_at, message_count, intents_json
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, '[]')
            """,
            (session_id, cliente_id, origin, user_agent, now_iso, now_iso),
        )
        connection.commit()


def _record_chat_message(
    *,
    session_id: str,
    cliente_id: str,
    role: str,
    content: str,
    intent: str = "",
) -> None:
    cleaned_content = _sanitize_text(content, allow_multiline=True)
    if not cleaned_content:
        return
    now_iso = _utc_now_iso()
    normalized_intent = str(intent or "").strip()
    with _get_db_connection() as connection:
        row = connection.execute(
            "SELECT intents_json FROM chat_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        intents = _safe_json_list(row["intents_json"] if row else "[]")
        if normalized_intent and normalized_intent not in intents:
            intents.append(normalized_intent)
        connection.execute(
            """
            INSERT INTO chat_messages (session_id, cliente_id, role, content, intent, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, cliente_id, role, cleaned_content, normalized_intent, now_iso),
        )
        connection.execute(
            """
            UPDATE chat_sessions
            SET last_message_at = ?,
                message_count = message_count + 1,
                intents_json = ?
            WHERE id = ?
            """,
            (now_iso, json.dumps(intents, ensure_ascii=False), session_id),
        )
        connection.commit()


def _chat_session_summary_from_row(row: sqlite3.Row) -> ChatSessionSummary:
    return ChatSessionSummary(
        session_id=row["id"],
        cliente_id=row["cliente_id"],
        origin=row["origin"] or "",
        started_at=row["started_at"],
        last_message_at=row["last_message_at"],
        message_count=int(row["message_count"] or 0),
        intents=_safe_json_list(row["intents_json"] or "[]"),
        last_message=row["last_message"] or "",
    )


def _chat_message_from_row(row: sqlite3.Row) -> ChatMessagePublic:
    return ChatMessagePublic(
        message_id=int(row["id"]),
        role=row["role"],
        content=row["content"],
        intent=row["intent"] or "",
        created_at=row["created_at"],
    )


def _list_chat_session_rows(
    *,
    cliente_id: str = "",
    limit: int = 50,
    offset: int = 0,
) -> List[sqlite3.Row]:
    clauses = []
    params: List[Any] = []
    if cliente_id:
        clauses.append("s.cliente_id = ?")
        params.append(cliente_id)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([max(1, min(limit, 200)), max(0, offset)])
    with _get_db_connection() as connection:
        return connection.execute(
            f"""
            SELECT s.*,
                   COALESCE((
                       SELECT m.content
                       FROM chat_messages m
                       WHERE m.session_id = s.id
                       ORDER BY m.id DESC
                       LIMIT 1
                   ), '') AS last_message
            FROM chat_sessions s
            {where_sql}
            ORDER BY s.last_message_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()


def _load_chat_session_or_404(session_id: str, *, cliente_id: str = "") -> sqlite3.Row:
    clauses = ["s.id = ?"]
    params: List[Any] = [session_id]
    if cliente_id:
        clauses.append("s.cliente_id = ?")
        params.append(cliente_id)
    with _get_db_connection() as connection:
        row = connection.execute(
            f"""
            SELECT s.*,
                   COALESCE((
                       SELECT m.content
                       FROM chat_messages m
                       WHERE m.session_id = s.id
                       ORDER BY m.id DESC
                       LIMIT 1
                   ), '') AS last_message
            FROM chat_sessions s
            WHERE {' AND '.join(clauses)}
            LIMIT 1
            """,
            params,
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversacion no encontrada.")
    return row


def _load_chat_message_rows(session_id: str) -> List[sqlite3.Row]:
    with _get_db_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        ).fetchall()


def cargar_indice(cliente_id: str) -> VectorStoreIndex:
    with state_lock:
        if cliente_id in indices:
            return indices[cliente_id]

    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El chat no esta disponible porque falta OPENAI_API_KEY.",
        )

    ruta_datos = DATA_DIR / cliente_id
    ruta_storage = STORAGE_DIR / cliente_id

    if not ruta_datos.exists():
        raise HTTPException(status_code=404, detail=f"No hay datos configurados para {cliente_id}")

    if ruta_storage.exists():
        try:
            storage_context = StorageContext.from_defaults(persist_dir=str(ruta_storage))
            indice = load_index_from_storage(storage_context)
            with state_lock:
                indices[cliente_id] = indice
            logger.info("Indice cargado desde storage para %s", cliente_id)
            return indice
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo cargar el indice persistido de %s: %s", cliente_id, exc)

    documentos = SimpleDirectoryReader(str(ruta_datos)).load_data()
    if not documentos:
        raise HTTPException(status_code=400, detail=f"No hay documentos utiles para {cliente_id}")

    indice = VectorStoreIndex.from_documents(documentos)
    ruta_storage.mkdir(parents=True, exist_ok=True)
    indice.storage_context.persist(persist_dir=str(ruta_storage))
    with state_lock:
        indices[cliente_id] = indice
    logger.info("Indice recreado para %s", cliente_id)
    return indice


def _get_or_create_session(session_id: str, cliente_id: str) -> SessionState:
    config = _get_client_config(cliente_id)
    now = time.time()

    with state_lock:
        session = sesiones.get(session_id)
        if session and session.cliente_id == cliente_id:
            session.last_seen = now
            return session

    indice = cargar_indice(cliente_id)
    engine = indice.as_chat_engine(
        chat_mode="condense_plus_context",
        similarity_top_k=4,
        system_prompt=_build_system_prompt(cliente_id, config),
    )

    session = SessionState(
        engine=engine,
        cliente_id=cliente_id,
        created_at=now,
        last_seen=now,
        message_count=0,
    )
    with state_lock:
        sesiones[session_id] = session
    return session


def _parse_date(date_text: str) -> datetime:
    try:
        return datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Fecha invalida. Usa formato YYYY-MM-DD.") from exc


def _parse_time(time_text: str) -> datetime:
    if not TIME_PATTERN.match(time_text):
        raise HTTPException(status_code=400, detail="Hora invalida. Usa formato HH:MM.")
    try:
        return datetime.strptime(time_text, "%H:%M")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Hora invalida.") from exc


def _get_booking_provider(config: Dict[str, Any]) -> str:
    _ = config
    return "internal"


def _normalize_message_kind(kind: str) -> str:
    normalized = _sanitize_text(kind).lower()
    if normalized not in DEFAULT_MESSAGE_TEMPLATES:
        raise HTTPException(status_code=400, detail="Tipo de plantilla no valido.")
    return normalized


def _sample_booking_preview_slot(schedule: PortalScheduleUpdatePayload) -> Tuple[str, str]:
    timezone_name = _sanitize_text(schedule.timezone) or DEFAULT_TIMEZONE
    today = datetime.now(ZoneInfo(timezone_name)).date()
    closed_days = {
        int(day)
        for day in schedule.closed_weekdays
        if isinstance(day, int) and 0 <= int(day) <= 6
    }
    for offset in range(1, 15):
        candidate = today + timedelta(days=offset)
        if candidate.weekday() not in closed_days:
            return candidate.isoformat(), schedule.day_start
    fallback = today + timedelta(days=1)
    return fallback.isoformat(), schedule.day_start


def _booking_preview_context(
    cliente_id: str,
    schedule: PortalScheduleUpdatePayload,
    request: Optional[Request] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    config = _get_client_config(cliente_id)
    message_templates = _normalize_message_templates(schedule.message_templates)
    message_enabled = _normalize_message_template_enabled(
        schedule.message_template_enabled,
        schedule.message_templates,
    )
    fecha, hora = _sample_booking_preview_slot(schedule)
    booking_row = {
        "cliente_id": cliente_id,
        "servicio": "Revision profesional",
        "booking_date": fecha,
        "booking_time": hora,
        "timezone": _sanitize_text(schedule.timezone) or DEFAULT_TIMEZONE,
        "email": config.get("contacto", {}).get("email", ""),
    }
    manage_url = _build_booking_manage_url("preview-demo-link", request)
    return booking_row, {
        "message_templates": message_templates,
        "message_template_enabled": message_enabled,
        "contact_email": config.get("contacto", {}).get("email", ""),
        "contact_phone": config.get("contacto", {}).get("telefono", ""),
        "company_name": config["nombre"],
    }, manage_url


def _booking_email_subject(
    status_key: str,
    company_name: str,
    booking_row: Any,
) -> str:
    service_name = booking_row["servicio"] or "tu cita"
    if status_key == "received":
        return f"Hemos recibido tu solicitud con {company_name}"
    if status_key == "cancelled":
        return f"Tu cita con {company_name} ha sido cancelada"
    if status_key == "rescheduled":
        return f"Tu cita con {company_name} ha cambiado de fecha"
    if status_key == "reminder_24h":
        return f"Recordatorio: manana tienes {service_name} con {company_name}"
    if status_key == "reminder_2h":
        return f"Recordatorio: tu cita con {company_name} empieza pronto"
    return f"Tu cita con {company_name} ha sido confirmada"


def _booking_datetime_display(booking_row: sqlite3.Row) -> str:
    try:
        selected = datetime.strptime(
            f"{booking_row['booking_date']} {booking_row['booking_time']}",
            "%Y-%m-%d %H:%M",
        )
        return selected.strftime("%d/%m/%Y a las %H:%M")
    except ValueError:
        return f"{booking_row['booking_date']} {booking_row['booking_time']}"


def _booking_email_bodies(
    booking_row: Any,
    company_name: str,
    status_key: str,
    manage_url: str,
    contact_email: str,
    contact_phone: str,
    message_templates: Optional[Dict[str, str]] = None,
    extra_message: str = "",
) -> Tuple[str, str]:
    service_name = booking_row["servicio"] or "Consulta"
    when_text = _booking_datetime_display(booking_row)
    manage_line = f"\nGestiona tu cita aqui: {manage_url}\n" if manage_url else ""
    manage_html = (
        (
            f'<p style="margin:20px 0;">'
            f'<a href="{escape(manage_url)}" '
            f'style="display:inline-block;padding:12px 18px;border-radius:12px;'
            f'background:#0b6b8a;color:#ffffff;text-decoration:none;font-weight:700;">'
            f'Gestionar cita'
            f"</a></p>"
        )
        if manage_url
        else ""
    )
    contact_lines = []
    if contact_phone:
        contact_lines.append(f"Telefono: {contact_phone}")
    if contact_email:
        contact_lines.append(f"Email: {contact_email}")
    contact_text = "\n".join(contact_lines)
    contact_html = "".join(f"<li>{escape(item)}</li>" for item in contact_lines)

    intro_map = {
        "received": "Hemos recibido tu solicitud de cita y la estamos revisando.",
        "confirmed": DEFAULT_MESSAGE_TEMPLATES["confirmed"],
        "cancelled": DEFAULT_MESSAGE_TEMPLATES["cancelled"],
        "rescheduled": DEFAULT_MESSAGE_TEMPLATES["rescheduled"],
        "reminder_24h": DEFAULT_MESSAGE_TEMPLATES["reminder_24h"],
        "reminder_2h": DEFAULT_MESSAGE_TEMPLATES["reminder_2h"],
    }
    templates = _normalize_message_templates(message_templates or {})
    intro_map.update(
        {
            "confirmed": templates["confirmed"],
            "cancelled": templates["cancelled"],
            "rescheduled": templates["rescheduled"],
            "reminder_24h": templates["reminder_24h"],
            "reminder_2h": templates["reminder_2h"],
        }
    )
    intro = intro_map.get(status_key, intro_map["confirmed"])
    extra_message_clean = _sanitize_text(extra_message, allow_multiline=True)

    text_body = (
        f"{intro}\n\n"
        f"Empresa: {company_name}\n"
        f"Servicio: {service_name}\n"
        f"Fecha y hora: {when_text}\n"
        f"Zona horaria: {booking_row['timezone']}\n"
        f"{manage_line}"
    )
    if extra_message_clean and status_key == "cancelled":
        text_body += f"\nMotivo de cancelacion:\n{extra_message_clean}\n"
    if contact_text:
        text_body += f"\nContacto:\n{contact_text}\n"

    html_body = (
        f'<div style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;'
        f'padding:24px;background:#f5f8fb;color:#102033;">'
        f'<div style="background:#ffffff;border:1px solid #d8e2ee;border-radius:18px;'
        f'padding:24px 24px 12px;">'
        f'<p style="margin:0 0 16px;line-height:1.6;">{escape(intro)}</p>'
        f'<ul style="margin:0 0 12px;padding-left:20px;line-height:1.8;">'
        f"<li><strong>Empresa:</strong> {escape(company_name)}</li>"
        f"<li><strong>Servicio:</strong> {escape(service_name)}</li>"
        f"<li><strong>Fecha y hora:</strong> {escape(when_text)}</li>"
        f"<li><strong>Zona horaria:</strong> {escape(booking_row['timezone'])}</li>"
        f"</ul>"
        f"{manage_html}"
    )
    if extra_message_clean and status_key == "cancelled":
        extra_message_html = escape(extra_message_clean).replace("\n", "<br>")
        html_body += (
            f'<p style="line-height:1.6;"><strong>Motivo de cancelacion:</strong><br>{extra_message_html}</p>'
        )
    if contact_html:
        html_body += (
            f'<p style="margin-top:18px;">Si necesitas ayuda, puedes escribirnos por:</p>'
            f'<ul style="line-height:1.8;">{contact_html}</ul>'
        )
    html_body += "</div></div>"

    return text_body.strip(), html_body


def _booking_message_preview(
    cliente_id: str,
    payload: PortalMessagePreviewPayload,
    request: Optional[Request] = None,
) -> PortalMessagePreviewResponse:
    kind = _normalize_message_kind(payload.kind)
    booking_row, context, manage_url = _booking_preview_context(cliente_id, payload.schedule, request)
    subject = _booking_email_subject(kind, context["company_name"], booking_row)
    text_body, html_body = _booking_email_bodies(
        booking_row,
        context["company_name"],
        kind,
        manage_url,
        context["contact_email"],
        context["contact_phone"],
        context["message_templates"],
    )
    return PortalMessagePreviewResponse(
        kind=kind,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        target_email=str(payload.target_email or ""),
        enabled=bool(context["message_template_enabled"].get(kind, True)),
    )


def _send_booking_email(
    booking_row: sqlite3.Row,
    status_key: str,
    request: Optional[Request] = None,
    *,
    extra_message: str = "",
) -> None:
    config = _get_client_config(booking_row["cliente_id"])
    company_name = config["nombre"]
    manage_url = _booking_row_manage_url(booking_row, request)
    contact_email = config.get("contacto", {}).get("email", "")
    contact_phone = config.get("contacto", {}).get("telefono", "")
    subject = _booking_email_subject(status_key, company_name, booking_row)
    text_body, html_body = _booking_email_bodies(
        booking_row,
        company_name,
        status_key,
        manage_url,
        contact_email,
        contact_phone,
        config.get("booking", {}).get("message_templates", {}),
        extra_message,
    )
    _send_email_message(booking_row["email"], subject, text_body, html_body)


def _booking_email_enabled(config: Dict[str, Any], kind: str) -> bool:
    enabled_map = _normalize_message_template_enabled(
        config.get("booking", {}).get("message_template_enabled", {}),
        config.get("booking", {}).get("message_templates", {}),
    )
    return enabled_map.get(kind, True)


def _mark_booking_email_result(
    booking_id: str,
    *,
    status: str,
    sent_column: str = "",
    error: str = "",
) -> None:
    updates: Dict[str, Any] = {
        "customer_email_status": status,
        "customer_email_last_error": error,
    }
    if sent_column:
        updates[sent_column] = _utc_now_iso()
    _update_booking_record(booking_id, **updates)


def _booking_start_end(
    cliente_id: str,
    fecha: str,
    hora: str,
    *,
    employee_id: str = "",
) -> Tuple[datetime, datetime]:
    employee_row = _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    schedule = _employee_schedule_from_row(employee_row)
    tzinfo = ZoneInfo(schedule["timezone"])
    start_local = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=tzinfo)
    end_local = start_local + timedelta(minutes=int(schedule["slot_minutes"]))
    return start_local, end_local


def _generate_manage_token() -> str:
    return f"mg_{secrets.token_urlsafe(24)}"


def _build_booking_manage_url(
    manage_token: str,
    request: Optional[Request] = None,
    *,
    viewer: str = "customer",
) -> str:
    if not manage_token:
        return ""
    base_url = _preferred_public_base_url(request)
    if not base_url:
        return ""
    suffix = "?viewer=client" if viewer == "client" else ""
    return f"{base_url}/booking/manage/{manage_token}{suffix}"


def _record_booking_audit(
    booking_id: str,
    cliente_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO booking_audit (booking_id, cliente_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                booking_id,
                cliente_id,
                event_type,
                json.dumps(payload or {}, ensure_ascii=False),
                _utc_now_iso(),
            ),
        )
        connection.commit()


def _list_booking_audit_rows(booking_id: str, *, limit: int = 80) -> List[sqlite3.Row]:
    with _get_db_connection() as connection:
        return connection.execute(
            """
            SELECT id, booking_id, cliente_id, event_type, payload_json, created_at
            FROM booking_audit
            WHERE booking_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (booking_id, max(1, min(limit, 200))),
        ).fetchall()


def _booking_audit_source_label(source: str) -> str:
    normalized = _sanitize_text(source).lower()
    labels = {
        "admin": "Admin Vantelia",
        "portal": "Portal cliente",
        "customer": "Cliente final",
        "system": "Sistema",
    }
    return labels.get(normalized, normalized.replace("_", " ").title() if normalized else "")


def _booking_email_kind_label(kind: str) -> str:
    labels = {
        "received": "Solicitud recibida",
        "confirmed": "Confirmacion",
        "cancelled": "Cancelacion",
        "rescheduled": "Reprogramacion",
        "reminder_24h": "Recordatorio 24h",
        "reminder_2h": "Recordatorio 2h",
    }
    normalized = _sanitize_text(kind).lower()
    return labels.get(normalized, normalized.replace("_", " ").title() if normalized else "Email")


def _booking_audit_datetime_label(fecha: str, hora: str) -> str:
    if not fecha:
        return ""
    return _booking_datetime_display({"booking_date": fecha, "booking_time": hora})


def _booking_audit_entry_from_row(row: sqlite3.Row) -> BookingAuditEntry:
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    event_type = str(row["event_type"] or "")
    source = _booking_audit_source_label(str(payload.get("source", "")))
    actor = source
    role_value = _sanitize_text(payload.get("role", "")).lower()
    if not actor and role_value == "admin":
        actor = "Administrador"
    elif not actor and role_value == "client":
        actor = "Cuenta cliente"
    if not actor and event_type in {"booking_confirmed", "booking_completed"}:
        actor = "Sistema"

    title = "Movimiento de cita"
    detail = ""

    if event_type == "booking_created":
        title = "Cita creada"
        status_value = _sanitize_text(payload.get("status", ""))
        provider_name = _sanitize_text(payload.get("provider_name", ""))
        parts = []
        if status_value:
            parts.append(f"Estado inicial: {status_value}.")
        if provider_name:
            parts.append(f"Proveedor: {provider_name}.")
        detail = " ".join(parts)
    elif event_type == "booking_rescheduled":
        title = "Cita reprogramada"
        date_label = _booking_audit_datetime_label(
            _sanitize_text(payload.get("fecha", "")),
            _sanitize_text(payload.get("hora", "")),
        )
        detail = f"Nuevo horario: {date_label}." if date_label else "Se ha actualizado la fecha u hora."
    elif event_type == "booking_updated":
        title = "Datos del asistente actualizados"
        date_label = _booking_audit_datetime_label(
            _sanitize_text(payload.get("fecha", "")),
            _sanitize_text(payload.get("hora", "")),
        )
        detail = (
            f"Se mantuvo el horario en {date_label} y se guardaron cambios en los datos."
            if date_label
            else "Se han guardado cambios en los datos de la cita."
        )
    elif event_type == "booking_cancelled":
        title = "Cita cancelada"
        reason = _sanitize_text(payload.get("reason", ""), allow_multiline=True)
        detail = "La cita ha quedado cancelada."
        if reason:
            detail += f" Motivo: {reason}"
    elif event_type == "booking_confirmed":
        title = "Cita confirmada"
        detail = "La cita paso a estado confirmado."
    elif event_type == "booking_completed":
        title = "Cita completada"
        detail = "La cita se marco como completada al superar su hora de fin."
    elif event_type == "booking_email_sent":
        title = "Email enviado"
        detail = f"Se envio la plantilla: {_booking_email_kind_label(str(payload.get('kind', '')))}."
    elif event_type == "booking_email_skipped":
        title = "Email omitido"
        reason = _sanitize_text(payload.get("reason", ""))
        detail = f"No se envio la plantilla {_booking_email_kind_label(str(payload.get('kind', '')))}."
        if reason:
            detail += f" Motivo: {reason}."
    elif event_type == "booking_email_failed":
        title = "Email fallido"
        detail = f"Fallo el envio de {_booking_email_kind_label(str(payload.get('kind', '')))}."

    return BookingAuditEntry(
        audit_id=int(row["id"]),
        booking_id=str(row["booking_id"]),
        event_type=event_type,
        title=title,
        detail=detail.strip(),
        created_at=str(row["created_at"]),
        source=source,
        actor=actor,
    )


def _get_booking_row_by_id(booking_id: str) -> Optional[sqlite3.Row]:
    with _get_db_connection() as connection:
        return connection.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()


def _get_booking_row_by_token(manage_token: str) -> Optional[sqlite3.Row]:
    with _get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM bookings WHERE manage_token = ?",
            (manage_token,),
        ).fetchone()


def _update_booking_record(booking_id: str, **updates: Any) -> None:
    if not updates:
        return
    assignments = ", ".join(f"{column} = ?" for column in updates)
    values = list(updates.values()) + [booking_id]
    with _get_db_connection() as connection:
        connection.execute(f"UPDATE bookings SET {assignments} WHERE id = ?", values)
        connection.commit()


def _booking_row_manage_url(
    row: sqlite3.Row,
    request: Optional[Request] = None,
    *,
    viewer: str = "customer",
) -> str:
    return _build_booking_manage_url(row["manage_token"], request, viewer=viewer)


def _serialize_booking_row(row: sqlite3.Row, request: Optional[Request] = None) -> Dict[str, Any]:
    config = _get_client_config(row["cliente_id"])
    return {
        "booking_id": row["id"],
        "cliente_id": row["cliente_id"],
        "empresa": config["nombre"],
        "employee_id": row["employee_id"] or "",
        "employee_name": row["employee_name"] or "",
        "nombre": row["nombre"],
        "email": row["email"],
        "telefono": row["telefono"] or "",
        "servicio": row["servicio"] or "",
        "notas": row["notas"] or "",
        "fecha": row["booking_date"],
        "hora": row["booking_time"],
        "timezone": row["timezone"] or config["booking"]["timezone"],
        "estado": row["status"],
        "provider_name": row["provider_name"],
        "provider_status": row["provider_status"],
        "provider_booking_id": row["provider_booking_id"] or "",
        "provider_booking_url": row["provider_booking_url"] or "",
        "manage_url": _booking_row_manage_url(row, request),
        "start_at": row["start_at"] or "",
        "end_at": row["end_at"] or "",
        "created_at": row["created_at"],
        "confirmed_at": row["confirmed_at"] or "",
        "cancelled_at": row["cancelled_at"] or "",
        "rescheduled_at": row["rescheduled_at"] or "",
        "confirmation_email_sent_at": row["confirmation_email_sent_at"] or "",
        "reminder_24h_sent_at": row["reminder_24h_sent_at"] or "",
        "reminder_2h_sent_at": row["reminder_2h_sent_at"] or "",
        "customer_email_status": row["customer_email_status"] or "",
        "contact_email": config.get("contacto", {}).get("email", ""),
        "contact_phone": config.get("contacto", {}).get("telefono", ""),
    }


def _to_utc_iso(dt_value: datetime) -> str:
    return dt_value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_booking_window(cliente_id: str, selected_day: datetime) -> None:
    config = _get_client_config(cliente_id)
    timezone_name = config["booking"]["timezone"]
    today = datetime.now(ZoneInfo(timezone_name)).date()

    if selected_day.date() < today:
        raise HTTPException(status_code=400, detail="No se permiten reservas en fechas pasadas.")

    max_day = today + timedelta(days=MAX_BOOKING_ADVANCE_DAYS)
    if selected_day.date() > max_day:
        raise HTTPException(
            status_code=400,
            detail=f"Solo se admiten reservas con hasta {MAX_BOOKING_ADVANCE_DAYS} dias de antelacion.",
        )


def _build_slots_for_day(cliente_id: str, fecha: str, *, employee_id: str = "") -> List[str]:
    config = _get_client_config(cliente_id)
    if not config["booking"]["enabled"]:
        return []

    employee_row = _resolve_employee_for_booking(cliente_id, employee_id)
    booking_cfg = _employee_schedule_from_row(employee_row)
    selected_day = _parse_date(fecha)
    _validate_booking_window(cliente_id, selected_day)
    if selected_day.weekday() in booking_cfg["closed_weekdays"]:
        return []

    start_dt = datetime.combine(selected_day.date(), _parse_time(booking_cfg["day_start"]).time())
    end_dt = datetime.combine(selected_day.date(), _parse_time(booking_cfg["day_end"]).time())
    slot_minutes = booking_cfg["slot_minutes"]

    if end_dt <= start_dt:
        raise HTTPException(status_code=500, detail="Configuracion horaria invalida para este cliente")

    slots: List[str] = []
    current = start_dt
    while current + timedelta(minutes=slot_minutes) <= end_dt:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=slot_minutes)

    return slots


async def _available_slots_for_day(cliente_id: str, fecha: str, *, employee_id: str = "") -> List[str]:
    return _build_slots_for_day(cliente_id, fecha, employee_id=employee_id)


def _booked_slots(
    cliente_id: str,
    fecha: str,
    *,
    employee_id: str = "",
    exclude_booking_id: str = "",
) -> Set[str]:
    with _get_db_connection() as connection:
        clauses = [
            "cliente_id = ?",
            "booking_date = ?",
            "status IN ('confirmed', 'pending_review')",
        ]
        params: List[Any] = [cliente_id, fecha]
        if employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        if exclude_booking_id:
            clauses.append("id <> ?")
            params.append(exclude_booking_id)
        rows = connection.execute(
            "SELECT booking_time FROM bookings WHERE " + " AND ".join(clauses),
            tuple(params),
        ).fetchall()

    occupied = {row["booking_time"] for row in rows}

    return occupied


def _active_booking_rows_for_day(cliente_id: str, fecha: str, *, employee_id: str = "") -> List[sqlite3.Row]:
    with _get_db_connection() as connection:
        clauses = [
            "cliente_id = ?",
            "booking_date = ?",
            "status IN ('confirmed', 'pending_review')",
        ]
        params: List[Any] = [cliente_id, fecha]
        if employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        return connection.execute(
            "SELECT * FROM bookings WHERE " + " AND ".join(clauses) + " ORDER BY booking_time ASC",
            tuple(params),
        ).fetchall()


def _booking_conflict_message(rows: List[sqlite3.Row], prefix: str) -> str:
    examples = ", ".join(
        f"{row['booking_date']} {row['booking_time']} ({row['nombre'] or row['email'] or row['id']})"
        for row in rows[:3]
    )
    suffix = f" Citas afectadas: {examples}." if examples else ""
    if len(rows) > 3:
        suffix += f" Y {len(rows) - 3} mas."
    return f"{prefix}{suffix}"


def _booking_conflicts_for_block(
    cliente_id: str,
    fecha: str,
    start_time: str,
    end_time: str,
    *,
    employee_id: str = "",
) -> List[sqlite3.Row]:
    timezone_name = (
        _employee_schedule_from_row(_resolve_employee_for_booking(cliente_id, employee_id, require_active=False))["timezone"]
        if employee_id
        else _get_client_config(cliente_id)["booking"]["timezone"]
    )
    tzinfo = ZoneInfo(timezone_name)
    block_start = datetime.strptime(f"{fecha} {start_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tzinfo)
    block_end = datetime.strptime(f"{fecha} {end_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tzinfo)
    conflicts: List[sqlite3.Row] = []
    for row in _active_booking_rows_for_day(cliente_id, fecha, employee_id=employee_id):
        booking_start, booking_end = _booking_start_end(
            cliente_id,
            row["booking_date"],
            row["booking_time"],
            employee_id=row["employee_id"] or employee_id,
        )
        if booking_start < block_end and booking_end > block_start:
            conflicts.append(row)
    return conflicts


def _booking_conflicts_for_closed_weekdays(
    cliente_id: str,
    weekdays: Set[int],
    *,
    employee_id: str = "",
) -> List[sqlite3.Row]:
    if not weekdays:
        return []
    today = _utc_now().date().isoformat()
    with _get_db_connection() as connection:
        clauses = [
            "cliente_id = ?",
            "booking_date >= ?",
            "status IN ('confirmed', 'pending_review')",
        ]
        params: List[Any] = [cliente_id, today]
        if employee_id:
            clauses.append("employee_id = ?")
            params.append(employee_id)
        rows = connection.execute(
            "SELECT * FROM bookings WHERE " + " AND ".join(clauses) + " ORDER BY booking_date ASC, booking_time ASC",
            tuple(params),
        ).fetchall()
    conflicts: List[sqlite3.Row] = []
    for row in rows:
        try:
            weekday = datetime.strptime(row["booking_date"], "%Y-%m-%d").weekday()
        except ValueError:
            continue
        if weekday in weekdays:
            conflicts.append(row)
    return conflicts


def _blocked_slots(cliente_id: str, fecha: str, *, employee_id: str = "") -> Set[str]:
    available_slots = _build_slots_for_day(cliente_id, fecha, employee_id=employee_id)
    if not available_slots:
        return set()
    employee_row = _resolve_employee_for_booking(cliente_id, employee_id, require_active=False)
    slot_minutes = int(_employee_schedule_from_row(employee_row)["slot_minutes"])
    blocked: Set[str] = set()
    rows = _list_agenda_blocks(
        cliente_id,
        employee_id=employee_id or "",
        include_general=bool(employee_id),
        date_from=fecha,
        date_to=fecha,
    )
    for row in rows:
        block_start = _parse_time(row["start_time"])
        block_end = _parse_time(row["end_time"])
        for slot in available_slots:
            slot_start = _parse_time(slot)
            slot_end = slot_start + timedelta(minutes=slot_minutes)
            if slot_start < block_end and slot_end > block_start:
                blocked.add(slot)
    return blocked


async def _booking_slot_available(cliente_id: str, fecha: str, hora: str, *, employee_id: str = "") -> bool:
    return (
        hora in await _available_slots_for_day(cliente_id, fecha, employee_id=employee_id)
        and hora not in _booked_slots(cliente_id, fecha, employee_id=employee_id)
        and hora not in _blocked_slots(cliente_id, fecha, employee_id=employee_id)
    )


async def _booking_slot_available_for_reschedule(
    cliente_id: str,
    fecha: str,
    hora: str,
    *,
    employee_id: str = "",
    exclude_booking_id: str,
) -> bool:
    booked = _booked_slots(
        cliente_id,
        fecha,
        employee_id=employee_id,
        exclude_booking_id=exclude_booking_id,
    )
    return (
        hora in await _available_slots_for_day(cliente_id, fecha, employee_id=employee_id)
        and hora not in booked
        and hora not in _blocked_slots(cliente_id, fecha, employee_id=employee_id)
    )


async def _cancel_provider_booking(booking_row: sqlite3.Row) -> None:
    _ = booking_row
    return None


async def _reschedule_provider_booking(
    booking_row: sqlite3.Row,
    *,
    fecha: str,
    hora: str,
) -> ProviderBookingResult:
    _ = (fecha, hora)
    return ProviderBookingResult(
        success=True,
        status="confirmed",
        provider_name="internal",
        provider_booking_id="",
        provider_booking_url="",
        message="Reserva reprogramada internamente.",
    )


def _store_booking(record: Dict[str, Any]) -> None:
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO bookings (
                id, cliente_id, employee_id, employee_name, nombre, email, telefono, servicio,
                booking_date, booking_time, notas, status,
                provider_name, provider_status, provider_booking_id, provider_booking_url,
                manage_token, timezone, start_at, end_at,
                confirmed_at, cancelled_at, rescheduled_at, rescheduled_from_booking_id,
                confirmation_email_sent_at, reminder_24h_sent_at, reminder_2h_sent_at,
                customer_email_status, customer_email_last_error,
                source, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["cliente_id"],
                record["employee_id"],
                record["employee_name"],
                record["nombre"],
                record["email"],
                record["telefono"],
                record["servicio"],
                record["booking_date"],
                record["booking_time"],
                record["notas"],
                record["status"],
                record["provider_name"],
                record["provider_status"],
                record["provider_booking_id"],
                record["provider_booking_url"],
                record["manage_token"],
                record["timezone"],
                record["start_at"],
                record["end_at"],
                record["confirmed_at"],
                record["cancelled_at"],
                record["rescheduled_at"],
                record["rescheduled_from_booking_id"],
                record["confirmation_email_sent_at"],
                record["reminder_24h_sent_at"],
                record["reminder_2h_sent_at"],
                record["customer_email_status"],
                record["customer_email_last_error"],
                record["source"],
                record["created_at"],
            ),
        )
        connection.commit()


async def _send_booking_to_webhook(cliente_id: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    config = _get_client_config(cliente_id)
    booking_cfg = config["booking"]
    webhook_url = booking_cfg.get("webhook_url", "").strip()

    if not webhook_url and booking_cfg.get("webhook_env"):
        webhook_url = os.getenv(booking_cfg["webhook_env"], "").strip()

    if not webhook_url:
        webhook_url = WEBHOOK_DEFAULT

    if not webhook_url:
        return True, "not_configured"

    try:
        webhook_url = _normalize_optional_http_url(webhook_url)
    except RuntimeError as exc:
        logger.error("Webhook invalido para %s: %s", cliente_id, exc)
        return False, "invalid_webhook_url"

    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=False) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"User-Agent": "Vantelia-Widget/1.0"},
            )
            response.raise_for_status()
        return True, "delivered"
    except httpx.HTTPError as exc:
        logger.error("Error enviando lead de %s al webhook: %s", cliente_id, exc)
        return False, "delivery_failed"


def _booking_public_detail_from_row(
    row: sqlite3.Row,
    request: Optional[Request] = None,
) -> BookingDetailPublic:
    data = _serialize_booking_row(row, request)
    return BookingDetailPublic(
        booking_id=data["booking_id"],
        cliente_id=data["cliente_id"],
        empresa=data["empresa"],
        employee_id=data["employee_id"],
        employee_name=data["employee_name"],
        nombre=data["nombre"],
        email=data["email"],
        telefono=data["telefono"],
        servicio=data["servicio"],
        notas=data["notas"],
        fecha=data["fecha"],
        hora=data["hora"],
        timezone=data["timezone"],
        estado=data["estado"],
        provider_name=data["provider_name"],
        provider_booking_url=data["provider_booking_url"],
        manage_url=data["manage_url"],
        contact_email=data["contact_email"],
        contact_phone=data["contact_phone"],
        available_services=_services_for_employee(
            data["cliente_id"],
            _get_employee_row(data["employee_id"], cliente_id=data["cliente_id"]) if data["employee_id"] else None,
        ),
    )


def _booking_admin_summary_from_row(
    row: sqlite3.Row,
    request: Optional[Request] = None,
) -> AdminBookingResumen:
    data = _serialize_booking_row(row, request)
    return AdminBookingResumen(
        booking_id=data["booking_id"],
        cliente_id=data["cliente_id"],
        empresa=data["empresa"],
        employee_id=data["employee_id"],
        employee_name=data["employee_name"],
        nombre=data["nombre"],
        email=data["email"],
        telefono=data["telefono"],
        servicio=data["servicio"],
        fecha=data["fecha"],
        hora=data["hora"],
        timezone=data["timezone"],
        estado=data["estado"],
        provider_name=data["provider_name"],
        provider_status=data["provider_status"],
        provider_booking_id=data["provider_booking_id"],
        provider_booking_url=data["provider_booking_url"],
        manage_url=data["manage_url"],
        created_at=data["created_at"],
        confirmed_at=data["confirmed_at"],
        cancelled_at=data["cancelled_at"],
        rescheduled_at=data["rescheduled_at"],
        confirmation_email_sent_at=data["confirmation_email_sent_at"],
        reminder_24h_sent_at=data["reminder_24h_sent_at"],
        reminder_2h_sent_at=data["reminder_2h_sent_at"],
        customer_email_status=data["customer_email_status"],
    )


def _portal_booking_summary_from_row(
    row: sqlite3.Row,
    request: Optional[Request] = None,
) -> PortalBookingSummary:
    data = _serialize_booking_row(row, request)
    status_value = data["estado"]
    start_at_dt = _from_utc_iso(data["start_at"])
    is_past = bool(start_at_dt and start_at_dt < _utc_now())
    can_edit = status_value not in {"cancelled", "completed"} and not is_past
    return PortalBookingSummary(
        booking_id=data["booking_id"],
        empresa=data["empresa"],
        employee_id=data["employee_id"],
        employee_name=data["employee_name"],
        nombre=data["nombre"],
        email=data["email"],
        servicio=data["servicio"],
        fecha=data["fecha"],
        hora=data["hora"],
        timezone=data["timezone"],
        estado=data["estado"],
        provider_name=data["provider_name"],
        provider_booking_url=data["provider_booking_url"],
        manage_url=_booking_row_manage_url(row, request, viewer="client"),
        contact_email=data["contact_email"],
        contact_phone=data["contact_phone"],
        start_at=data["start_at"],
        can_cancel=can_edit,
        can_reschedule=can_edit,
    )


def _list_booking_rows(
    *,
    cliente_id: str = "",
    employee_id: str = "",
    status_filter: str = "",
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 100,
    offset: int = 0,
    scope: str = "all",
) -> Tuple[List[sqlite3.Row], int]:
    sql = "SELECT * FROM bookings"
    clauses: List[str] = []
    params: List[Any] = []
    if cliente_id:
        clauses.append("cliente_id = ?")
        params.append(cliente_id)
    if employee_id:
        clauses.append("employee_id = ?")
        params.append(employee_id)
    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter)
    if date_from:
        clauses.append("booking_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("booking_date <= ?")
        params.append(date_to)
    if search:
        like_search = f"%{search}%"
        clauses.append(
            "("
            "id LIKE ? OR cliente_id LIKE ? OR nombre LIKE ? OR email LIKE ? OR telefono LIKE ? "
            "OR servicio LIKE ? OR provider_booking_id LIKE ? OR employee_name LIKE ?"
            ")"
        )
        params.extend([like_search] * 8)
    now_iso = _utc_now_iso()
    if scope == "upcoming":
        clauses.append(
            "("
            "status IN ('confirmed', 'pending_review') "
            "AND (start_at = '' OR start_at >= ?)"
            ")"
        )
        params.append(now_iso)
    elif scope == "history":
        clauses.append(
            "("
            "status IN ('cancelled', 'completed') "
            "OR (start_at <> '' AND start_at < ?)"
            ")"
        )
        params.append(now_iso)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    count_sql = sql.replace("SELECT *", "SELECT COUNT(*)", 1)
    if scope == "upcoming":
        sql += (
            " ORDER BY booking_date ASC, booking_time ASC, "
            "CASE WHEN start_at = '' THEN created_at ELSE start_at END ASC"
        )
    elif scope == "history":
        sql += (
            " ORDER BY booking_date DESC, booking_time DESC, "
            "CASE WHEN start_at = '' THEN created_at ELSE start_at END DESC"
        )
    else:
        sql += " ORDER BY booking_date ASC, booking_time ASC, created_at ASC"
    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with _get_db_connection() as connection:
        total = connection.execute(count_sql, tuple(params[:-2] if params else [])).fetchone()[0]
        rows = connection.execute(sql, tuple(params)).fetchall()
        return rows, total


def _portal_stats_for_user(user: sqlite3.Row, cliente_id_override: str = "") -> Dict[str, Any]:
    with _get_db_connection() as connection:
        if user["role"] == "admin" and not cliente_id_override:
            total_bookings = connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
            pending = connection.execute(
                "SELECT COUNT(*) FROM bookings WHERE status = 'pending_review'"
            ).fetchone()[0]
            upcoming = connection.execute(
                """
                SELECT COUNT(*)
                FROM bookings
                WHERE status = 'confirmed'
                  AND (start_at = '' OR start_at >= ?)
                """,
                (_utc_now_iso(),),
            ).fetchone()[0]
            total_users = connection.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]
            client_users = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'client' AND is_active = 1"
            ).fetchone()[0]
            return {
                "total_bookings": total_bookings,
                "pending_review": pending,
                "upcoming": upcoming,
                "active_users": total_users,
                "client_users": client_users,
            }

        target_client_id = cliente_id_override or (user["cliente_id"] or "")
        total_bookings = connection.execute(
            "SELECT COUNT(*) FROM bookings WHERE cliente_id = ?",
            (target_client_id,),
        ).fetchone()[0]
        upcoming = connection.execute(
            """
            SELECT COUNT(*)
            FROM bookings
            WHERE cliente_id = ?
              AND status IN ('confirmed', 'pending_review')
              AND (start_at = '' OR start_at >= ?)
            """,
            (target_client_id, _utc_now_iso()),
        ).fetchone()[0]
        history = connection.execute(
            """
            SELECT COUNT(*)
            FROM bookings
            WHERE cliente_id = ?
              AND (
                status IN ('cancelled', 'completed')
                OR (start_at <> '' AND start_at < ?)
              )
            """,
            (target_client_id, _utc_now_iso()),
        ).fetchone()[0]
        return {
            "total_bookings": total_bookings,
            "upcoming": upcoming,
            "history": history,
            "empresa": _get_client_config(target_client_id)["nombre"] if target_client_id else "",
        }


def _portal_today_dashboard(
    cliente_id: str,
    request: Optional[Request] = None,
) -> Tuple[List[PortalBookingSummary], List[PortalAgendaBlock]]:
    today = datetime.now(ZoneInfo(_get_client_config(cliente_id)["booking"]["timezone"])).date().isoformat()
    rows, _ = _list_booking_rows(
        cliente_id=cliente_id,
        date_from=today,
        date_to=today,
        limit=30,
        scope="all",
    )
    today_bookings = [_portal_booking_summary_from_row(row, request) for row in rows]
    blocks = [
        _serialize_agenda_block(row)
        for row in _list_agenda_blocks(cliente_id, date_from=today, date_to=today)
    ]
    return today_bookings, blocks


def _load_booking_or_404(booking_id: str) -> sqlite3.Row:
    row = _get_booking_row_by_id(booking_id)
    if not row:
        raise HTTPException(status_code=404, detail="Reserva no encontrada.")
    return row


def _load_booking_by_token_or_404(manage_token: str) -> sqlite3.Row:
    row = _get_booking_row_by_token(manage_token)
    if not row:
        raise HTTPException(status_code=404, detail="No se ha encontrado la reserva.")
    return row


def _booking_update_payload_from_reschedule(row: sqlite3.Row, data: BookingReschedulePayload) -> BookingUpdatePayload:
    return BookingUpdatePayload(
        nombre=row["nombre"],
        email=row["email"],
        telefono=row["telefono"] or "",
        servicio=row["servicio"] or "",
        employee_id=data.employee_id or (row["employee_id"] or ""),
        fecha=data.fecha,
        hora=data.hora,
        notas=row["notas"] or "",
    )


async def _update_booking_details(
    booking_row: sqlite3.Row,
    data: BookingUpdatePayload,
    request: Request,
    *,
    source: str,
    audit_payload: Optional[Dict[str, Any]] = None,
) -> BookingActionResponse:
    if booking_row["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="No se puede modificar una cita cancelada.")
    if booking_row["status"] == "completed":
        raise HTTPException(status_code=409, detail="No se puede modificar una cita completada.")

    booking_date_dt = _parse_date(data.fecha)
    _validate_booking_window(booking_row["cliente_id"], booking_date_dt)
    booking_date = booking_date_dt.strftime("%Y-%m-%d")
    booking_time = _parse_time(data.hora).strftime("%H:%M")
    target_employee = _resolve_employee_for_booking(
        booking_row["cliente_id"],
        data.employee_id or (booking_row["employee_id"] or ""),
        require_active=False,
    )
    if not _service_name_allowed_for_employee(booking_row["cliente_id"], target_employee, data.servicio):
        raise HTTPException(
            status_code=400,
            detail="El servicio seleccionado no esta disponible para ese profesional.",
        )
    employee_changed = (target_employee["id"] or "") != (booking_row["employee_id"] or "")
    slot_changed = (
        booking_date != booking_row["booking_date"]
        or booking_time != booking_row["booking_time"]
        or employee_changed
    )

    if slot_changed and not await _booking_slot_available_for_reschedule(
        booking_row["cliente_id"],
        booking_date,
        booking_time,
        employee_id=target_employee["id"],
        exclude_booking_id=booking_row["id"],
    ):
        raise HTTPException(status_code=409, detail="Ese horario ya no esta disponible. Elige otro tramo.")

    start_local, end_local = _booking_start_end(
        booking_row["cliente_id"],
        booking_date,
        booking_time,
        employee_id=target_employee["id"],
    )
    provider_result = (
        await _reschedule_provider_booking(booking_row, fecha=booking_date, hora=booking_time)
        if slot_changed
        else ProviderBookingResult(
            success=True,
            status=booking_row["provider_status"] or "confirmed",
            provider_name=booking_row["provider_name"] or "internal",
            provider_booking_id=booking_row["provider_booking_id"] or "",
            provider_booking_url=booking_row["provider_booking_url"] or "",
            message="Reserva actualizada internamente.",
        )
    )

    updates: Dict[str, Any] = {
        "nombre": _sanitize_text(data.nombre),
        "email": str(data.email),
        "telefono": _sanitize_text(data.telefono),
        "servicio": _sanitize_text(data.servicio),
        "notas": _sanitize_text(data.notas, allow_multiline=True),
        "employee_id": target_employee["id"],
        "employee_name": target_employee["name"],
        "booking_date": booking_date,
        "booking_time": booking_time,
        "start_at": _to_utc_iso(start_local),
        "end_at": _to_utc_iso(end_local),
        "status": "confirmed",
        "provider_status": provider_result.status,
        "provider_booking_id": provider_result.provider_booking_id,
        "provider_booking_url": provider_result.provider_booking_url,
    }
    if slot_changed:
        updates.update(
            {
                "rescheduled_at": _utc_now_iso(),
                "reminder_24h_sent_at": "",
                "reminder_2h_sent_at": "",
            }
        )

    _update_booking_record(booking_row["id"], **updates)
    event_type = "booking_rescheduled" if slot_changed else "booking_updated"
    _record_booking_audit(
        booking_row["id"],
        booking_row["cliente_id"],
        event_type,
        {
            "source": source,
            "fecha": booking_date,
            "hora": booking_time,
            "employee_id": target_employee["id"],
            "employee_name": target_employee["name"],
            **(audit_payload or {}),
        },
    )
    refreshed = _load_booking_or_404(booking_row["id"])
    try:
        await _send_booking_email_by_kind(refreshed, "rescheduled" if slot_changed else "confirmed", request)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se ha podido enviar el email de actualizacion %s: %s", refreshed["id"], exc)

    return BookingActionResponse(
        ok=True,
        booking_id=refreshed["id"],
        estado=refreshed["status"],
        mensaje="La cita se ha actualizado correctamente.",
        employee_id=refreshed["employee_id"] or "",
        employee_name=refreshed["employee_name"] or "",
        manage_url=_booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
    )


def _booking_manage_page(booking: BookingDetailPublic, *, viewer: str = "customer") -> str:
    serialized = json.dumps(booking.model_dump(), ensure_ascii=False)
    logo_url = escape(_brand_asset_public_path("Logo_1_sin_resplandor.png"))
    favicon_url = escape(_brand_asset_public_path("favicon.png"))
    fondo_url = escape(_brand_asset_public_path("Fondo_Web.png"))
    provider_note = ""
    is_client_viewer = viewer == "client"
    company_name = escape(booking.empresa)
    page_title = "Gestionar cita | Vantelia" if is_client_viewer else f"Gestionar cita | {company_name}"
    hero_logo_html = f'<img src="{logo_url}" alt="Vantelia" />' if is_client_viewer else ""
    hero_title = "Gestionar cita" if is_client_viewer else f"Gestiona tu cita con {company_name}"
    hero_subtitle = company_name if is_client_viewer else "Consulta los detalles y gestiona la reserva de forma sencilla."
    action_intro = (
        "Elige la accion que necesitas sobre la cita de tu cliente. Puedes cambiar la fecha, actualizar los datos del asistente o cancelarla. El email del asistente no se puede modificar desde este enlace."
        if is_client_viewer
        else "Elige la accion que necesitas. Puedes cambiar la fecha, actualizar los datos del asistente o cancelar la reserva. El email del asistente no se puede modificar desde este enlace."
    )
    cancel_helper = (
        "Quieres cancelar esta cita?"
        if is_client_viewer
        else "Si ya no vais a asistir, puedes cancelar la reserva desde aqui. Si prefieres otra fecha, usa antes la seccion de cambio de horario."
    )
    cancel_card_copy = (
        "Confirma la cancelacion si finalmente no se va a atender esta cita."
        if is_client_viewer
        else "Confirma la cancelacion si ya no vais a asistir."
    )
    back_button_html = (
        '<a class="button-link secondary" href="/portal">Volver al panel</a>'
        if is_client_viewer
        else ""
    )
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{page_title}</title>
  <link rel="icon" type="image/png" href="{favicon_url}" />
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700;800&family=Poppins:wght@400;500;600;700&display=swap');
    :root {{
      --bg:#000b29;
      --ink:#f0f4f8;
      --soft:#b8c0cc;
      --line:rgba(184, 192, 204, .14);
      --panel:rgba(5,14,38,.88);
      --shadow:0 28px 80px rgba(0, 0, 0, .36);
      --accent:#00b1d9;
      --danger:#b42318;
      --font-title:"Montserrat","Segoe UI",sans-serif;
      --font-body:"Poppins","Segoe UI",sans-serif;
    }}
    body {{
      font-family: var(--font-body);
      background:
        linear-gradient(180deg, rgba(0,11,41,.88), rgba(0,11,41,.96)),
        radial-gradient(circle at top right, rgba(0,177,217,.2), transparent 24%),
        url("{fondo_url}") center top / cover fixed no-repeat;
      margin:0;
      padding:24px;
      color:var(--ink);
    }}
    .wrap {{ max-width:980px; margin:0 auto; }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:28px; box-shadow:var(--shadow); backdrop-filter: blur(18px); }}
    .hero {{ display:flex; align-items:center; gap:16px; margin-bottom:18px; }}
    .hero img {{ width:68px; height:68px; object-fit:contain; filter: drop-shadow(0 0 22px rgba(0,177,217,.3)); }}
    h1 {{ margin:0 0 8px; font-size:30px; font-family:var(--font-title); }}
    .muted {{ color:var(--soft); }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:20px 0; }}
    .field {{ background:rgba(8,20,48,.92); border:1px solid rgba(184,192,204,.14); border-radius:8px; padding:12px; }}
    .field strong {{ display:block; font-size:12px; text-transform:uppercase; color:#8dcfe0; margin-bottom:6px; }}
    .actions {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:20px; }}
    button, .button-link {{ border:none; border-radius:8px; padding:12px 18px; font-weight:700; cursor:pointer; font-family:var(--font-body); }}
    .button-link {{ display:inline-block; text-decoration:none; box-sizing:border-box; }}
    .primary {{ background:linear-gradient(135deg, var(--accent), #008bad); color:#fff; }}
    .secondary {{ background:rgba(184,192,204,.12); color:var(--ink); }}
    .danger {{ background:var(--danger); color:#fff; }}
    .panel {{ margin-top:24px; padding-top:20px; border-top:1px solid rgba(184,192,204,.14); }}
    .status {{ margin-top:16px; min-height:22px; font-weight:600; }}
    label {{ display:grid; gap:8px; font-weight:700; }}
    input, select, textarea {{ width:100%; box-sizing:border-box; border:1px solid rgba(184,192,204,.16); border-radius:8px; padding:12px; font-family:var(--font-body); background:rgba(8,20,48,.92); color:var(--ink); outline:none; }}
    textarea {{ min-height:92px; resize:vertical; line-height:1.5; }}
    input:focus, select:focus, textarea:focus {{ border-color:rgba(0,177,217,.46); box-shadow:0 0 0 4px rgba(0,177,217,.12); }}
    .slot-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(96px, 1fr)); gap:10px; margin-top:12px; }}
    .slot-grid button {{ background:rgba(184,192,204,.12); color:var(--ink); }}
    .slot-grid button.selected {{ background:linear-gradient(135deg, var(--accent), #008bad); color:#fff; }}
    .slot-grid button:disabled {{ cursor:not-allowed; opacity:.45; }}
    .notice {{ border:1px solid var(--line); border-radius:8px; padding:12px; color:var(--soft); background:rgba(255,255,255,.03); }}
    input[readonly] {{ opacity:.82; cursor:not-allowed; }}
    .action-chooser {{ display:grid; gap:14px; margin:22px 0 6px; }}
    .action-chooser-grid {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:14px; }}
    .action-card {{ border:1px solid var(--line); border-radius:8px; background:rgba(8,20,48,.92); padding:16px; text-align:left; color:var(--ink); }}
    .action-card.active {{ border-color:rgba(0,177,217,.48); background:rgba(0,177,217,.12); box-shadow:0 0 0 1px rgba(0,177,217,.18) inset; }}
    .action-card strong {{ display:block; margin-bottom:6px; font-size:1rem; }}
    .action-card span {{ color:var(--soft); line-height:1.6; font-weight:500; }}
    .section-card {{ margin-top:18px; padding:18px; border:1px solid var(--line); border-radius:8px; background:rgba(255,255,255,.03); }}
    .section-card {{ display:none; }}
    .section-card.active {{ display:block; }}
    .section-card h2 {{ margin:0 0 6px; font-size:1.1rem; font-family:var(--font-title); }}
    .section-card .muted {{ margin-bottom:8px; }}
    .danger-note {{ border-left:3px solid rgba(180,35,24,.65); padding-left:12px; }}
    .hidden {{ display:none !important; }}
    @media (max-width: 720px) {{ .grid, .action-chooser-grid {{ grid-template-columns:1fr; }} body {{ padding:16px; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="hero">
        {hero_logo_html}
        <div>
          <h1>{hero_title}</h1>
          <div class="muted">{hero_subtitle}</div>
        </div>
      </div>
      <div class="grid">
        <div class="field"><strong>Estado</strong>{escape(booking.estado)}</div>
        <div class="field"><strong>Zona horaria</strong>{escape(booking.timezone)}</div>
      </div>
      {provider_note}
      <div class="action-chooser">
        <strong>Que quieres hacer con esta cita?</strong>
        <div class="muted">{action_intro}</div>
        <div class="action-chooser-grid">
          <button class="action-card" type="button" data-panel-target="schedule-section">
            <strong>Cambiar fecha u hora</strong>
            <span>Consulta disponibilidad y mueve la cita a otro tramo si sigue libre.</span>
          </button>
          <button class="action-card" type="button" data-panel-target="details-section">
            <strong>Cambiar datos del asistente</strong>
            <span>Actualiza nombre, telefono, servicio o notas de la persona asistente.</span>
          </button>
          <button class="action-card" type="button" data-panel-target="cancel-section">
            <strong>Cancelar cita</strong>
            <span>{cancel_card_copy}</span>
          </button>
        </div>
      </div>
      <div class="panel" id="reschedule-panel">
        <div class="section-card" id="details-section">
          <h2>Cambiar datos del asistente</h2>
          <p class="muted">Actualiza los datos de la persona que asistira a la cita. El email se mantiene bloqueado por seguridad.</p>
        <div class="grid">
          <label>Nombre<input id="booking-name" type="text" maxlength="80" /></label>
          <label>Email<input id="booking-email" type="email" maxlength="120" readonly /></label>
          <label>Telefono<input id="booking-phone" type="text" maxlength="30" /></label>
          <label>Servicio<select id="booking-service"></select></label>
        </div>
        <label>Notas<textarea id="booking-notes" maxlength="500"></textarea></label>
        </div>
        <div class="section-card" id="schedule-section">
          <h2>Cambiar fecha u hora</h2>
          <p class="muted">Selecciona un nuevo horario. El cambio solo se guardara si el tramo sigue disponible.</p>
        <div class="grid">
          <label>Fecha<input id="reschedule-date" type="date" /></label>
          <label>Hora seleccionada<select id="reschedule-time"></select></label>
        </div>
        <div id="slot-status" class="notice">Selecciona una fecha para cargar disponibilidad.</div>
        <div id="slot-grid" class="slot-grid"></div>
        </div>
        <div class="section-card" id="cancel-section">
          <h2>Cancelar cita</h2>
          <p class="muted danger-note">{cancel_helper}</p>
        </div>
        <div class="actions">
          <button class="primary" id="save-btn" type="button">Guardar cambios</button>
          <button class="danger" id="cancel-btn" type="button">Cancelar cita</button>
          {back_button_html}
        </div>
      </div>
      <div class="status" id="status"></div>
    </div>
  </div>
  <script>
    const BOOKING = {serialized};
    const statusEl = document.getElementById("status");
    const actionChooser = document.querySelector(".action-chooser");
    const reschedulePanel = document.getElementById("reschedule-panel");
    const saveBtn = document.getElementById("save-btn");
    const cancelBtn = document.getElementById("cancel-btn");
    const serviceSelect = document.getElementById("booking-service");
    const slotStatus = document.getElementById("slot-status");
    const slotGrid = document.getElementById("slot-grid");
    const sectionCards = Array.from(document.querySelectorAll(".section-card"));
    const chooserButtons = Array.from(document.querySelectorAll("[data-panel-target]"));
    if (BOOKING.estado === "cancelled" || BOOKING.estado === "completed") {{
      if (actionChooser) actionChooser.style.display = "none";
      reschedulePanel.style.display = "none";
      statusEl.textContent = BOOKING.estado === "cancelled"
        ? "Esta cita ya esta cancelada y no admite cambios desde este enlace."
        : "Esta cita ya esta completada y no admite cambios desde este enlace.";
    }}
    function openPanel(panelId) {{
      sectionCards.forEach((section) => {{
        section.classList.toggle("active", section.id === panelId);
      }});
      chooserButtons.forEach((button) => {{
        button.classList.toggle("active", button.dataset.panelTarget === panelId);
      }});
      if (saveBtn) saveBtn.classList.toggle("hidden", panelId === "cancel-section");
      if (cancelBtn) cancelBtn.classList.toggle("hidden", panelId !== "cancel-section");
    }}
    chooserButtons.forEach((button) => {{
      button.addEventListener("click", () => openPanel(button.dataset.panelTarget || "details-section"));
    }});
    document.getElementById("booking-name").value = BOOKING.nombre || "";
    document.getElementById("booking-email").value = BOOKING.email || "";
    document.getElementById("booking-phone").value = BOOKING.telefono || "";
    document.getElementById("booking-notes").value = BOOKING.notas || "";
    document.getElementById("reschedule-date").value = BOOKING.fecha;
    document.getElementById("reschedule-time").value = BOOKING.hora;

    function renderServiceOptions() {{
      const services = Array.isArray(BOOKING.available_services) ? BOOKING.available_services : [];
      const currentService = String(BOOKING.servicio || "").trim();
      serviceSelect.innerHTML = "";

      const seen = new Set();
      services.forEach((service) => {{
        const value = String(service?.nombre || "").trim();
        if (!value || seen.has(value)) return;
        seen.add(value);
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        option.selected = value === currentService;
        serviceSelect.appendChild(option);
      }});

      if (!seen.size || (currentService && !seen.has(currentService))) {{
        const fallback = document.createElement("option");
        fallback.value = currentService || "Consulta";
        fallback.textContent = currentService || "Consulta";
        fallback.selected = true;
        serviceSelect.appendChild(fallback);
      }}
    }}

    function setTimeOptions(slots, fecha) {{
      const timeSelect = document.getElementById("reschedule-time");
      const previousValue = timeSelect.value || (fecha === BOOKING.fecha ? BOOKING.hora : "");
      const available = slots
        .filter((slot) => slot.disponible || (fecha === BOOKING.fecha && slot.hora === BOOKING.hora))
        .map((slot) => String(slot.hora || ""))
        .filter(Boolean);
      if (fecha === BOOKING.fecha && BOOKING.hora && !available.includes(BOOKING.hora)) {{
        available.unshift(BOOKING.hora);
      }}

      timeSelect.innerHTML = "";
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = available.length ? "Elige una hora" : "Sin horarios disponibles";
      placeholder.disabled = true;
      placeholder.selected = !available.includes(previousValue);
      timeSelect.appendChild(placeholder);

      available.forEach((hora) => {{
        const option = document.createElement("option");
        option.value = hora;
        option.textContent = hora;
        option.selected = hora === previousValue;
        timeSelect.appendChild(option);
      }});
      timeSelect.disabled = !available.length;
      if (!available.includes(previousValue)) {{
        timeSelect.value = "";
      }}
      return available.length;
    }}

    async function loadSlots() {{
      const fecha = document.getElementById("reschedule-date").value;
      slotGrid.innerHTML = "";
      if (!fecha) {{
        slotStatus.textContent = "Selecciona una fecha para cargar disponibilidad.";
        return;
      }}
      slotStatus.textContent = "Consultando disponibilidad...";
      try {{
        const response = await fetch(`/disponibilidad?cliente_id=${{encodeURIComponent(BOOKING.cliente_id)}}&employee_id=${{encodeURIComponent(BOOKING.employee_id || "")}}&fecha=${{encodeURIComponent(fecha)}}`, {{
          headers: {{ "Accept": "application/json" }},
        }});
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "No se pudo cargar la disponibilidad.");
        const slots = Array.isArray(data.slots) ? data.slots : [];
        const availableCount = setTimeOptions(slots, fecha);
        slotStatus.textContent = availableCount ? `${{availableCount}} horarios disponibles` : "No hay horarios disponibles para esta fecha.";
      }} catch (error) {{
        slotStatus.textContent = error.message;
      }}
    }}

    async function action(url, body) {{
      statusEl.textContent = "Procesando...";
      const response = await fetch(url, {{
        method: "POST",
        headers: {{ "Content-Type": "application/json", "Accept": "application/json" }},
        body: body ? JSON.stringify(body) : undefined,
      }});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.message || "No se pudo completar la accion.");
      statusEl.textContent = data.mensaje || "Accion completada.";
      window.setTimeout(() => window.location.reload(), 1200);
    }}

    document.getElementById("cancel-btn")?.addEventListener("click", async () => {{
      if (!window.confirm("¿Seguro que quieres cancelar esta cita?")) return;
      try {{ await action(window.location.pathname + "/cancel"); }}
      catch (error) {{ statusEl.textContent = error.message; }}
    }});

    document.getElementById("save-btn")?.addEventListener("click", async () => {{
      const fecha = document.getElementById("reschedule-date").value;
      const hora = document.getElementById("reschedule-time").value;
      const scheduleSection = document.getElementById("schedule-section");
      const isScheduleOpen = scheduleSection?.classList.contains("active");
      const payload = {{
        nombre: document.getElementById("booking-name").value.trim(),
        email: BOOKING.email || "",
        telefono: document.getElementById("booking-phone").value.trim(),
        servicio: serviceSelect.value.trim(),
        employee_id: BOOKING.employee_id || "",
        fecha: isScheduleOpen ? fecha : BOOKING.fecha,
        hora: isScheduleOpen ? hora : BOOKING.hora,
        notas: document.getElementById("booking-notes").value.trim(),
      }};
      if (isScheduleOpen && (!fecha || !hora)) {{
        statusEl.textContent = "Elige una fecha y una hora.";
        return;
      }}
      try {{ await action(window.location.pathname + "/update", payload); }}
      catch (error) {{ statusEl.textContent = error.message; }}
    }});
    document.getElementById("reschedule-date")?.addEventListener("change", loadSlots);
    renderServiceOptions();
    openPanel("details-section");
    loadSlots();
  </script>
</body>
</html>"""


async def _send_booking_email_by_kind(
    booking_row: sqlite3.Row,
    kind: str,
    request: Optional[Request] = None,
    *,
    sent_column: str = "",
    extra_message: str = "",
    respect_enabled: bool = True,
) -> None:
    if respect_enabled:
        config = _get_client_config(booking_row["cliente_id"])
        if not _booking_email_enabled(config, kind):
            if sent_column:
                _mark_booking_email_result(
                    booking_row["id"],
                    status=f"disabled:{kind}",
                    sent_column=sent_column,
                    error="",
                )
            _record_booking_audit(
                booking_row["id"],
                booking_row["cliente_id"],
                "booking_email_skipped",
                {"kind": kind, "reason": "disabled"},
            )
            return
    _send_booking_email(booking_row, kind, request, extra_message=extra_message)
    _mark_booking_email_result(
        booking_row["id"],
        status=kind,
        sent_column=sent_column,
        error="",
    )
    _record_booking_audit(
        booking_row["id"],
        booking_row["cliente_id"],
        "booking_email_sent",
        {"kind": kind, "extra_message": bool(extra_message)},
    )


def _booking_due_for_reminder(row: sqlite3.Row, now_utc: datetime, hours_before: int) -> bool:
    start_at = _from_utc_iso(row["start_at"])
    if not start_at or row["status"] != "confirmed":
        return False
    lower_bound = now_utc + timedelta(hours=hours_before)
    upper_bound = lower_bound + timedelta(minutes=45)
    return lower_bound <= start_at <= upper_bound


def _auto_complete_past_bookings() -> int:
    if BOOKING_AUTO_COMPLETE_HOURS < 0:
        return 0

    threshold = (_utc_now() - timedelta(hours=BOOKING_AUTO_COMPLETE_HOURS)).isoformat().replace("+00:00", "Z")
    completed = 0
    with _get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, cliente_id
            FROM bookings
            WHERE status IN ('confirmed', 'pending_review')
              AND end_at <> ''
              AND end_at <= ?
            """,
            (threshold,),
        ).fetchall()
        for row in rows:
            connection.execute(
                "UPDATE bookings SET status = 'completed' WHERE id = ?",
                (row["id"],),
            )
            connection.execute(
                """
                INSERT INTO booking_audit (booking_id, cliente_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["cliente_id"],
                    "booking_completed",
                    json.dumps({"source": "automation"}, ensure_ascii=False),
                    _utc_now_iso(),
                ),
            )
            completed += 1
        connection.commit()
    return completed


def _auto_confirm_pending_bookings() -> int:
    confirmed_at = _utc_now_iso()
    confirmed = 0
    with _get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, cliente_id
            FROM bookings
            WHERE status = 'pending_review'
              AND (end_at = '' OR end_at > ?)
            """,
            (confirmed_at,),
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                UPDATE bookings
                SET status = 'confirmed',
                    confirmed_at = CASE WHEN confirmed_at = '' THEN ? ELSE confirmed_at END
                WHERE id = ?
                """,
                (confirmed_at, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO booking_audit (booking_id, cliente_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["cliente_id"],
                    "booking_confirmed",
                    json.dumps({"source": "automation", "reason": "auto_confirm_pending_review"}, ensure_ascii=False),
                    confirmed_at,
                ),
            )
            confirmed += 1
        connection.commit()
    return confirmed


async def _run_booking_reminders(request: Optional[Request] = None) -> AdminReminderRunResult:
    now_utc = _utc_now()
    _auto_confirm_pending_bookings()
    rows, _ = _list_booking_rows(limit=500)
    processed = 0
    sent_24h = 0
    sent_2h = 0
    failed = 0

    for row in rows:
        processed += 1
        try:
            if not row["reminder_24h_sent_at"] and _booking_due_for_reminder(row, now_utc, REMINDER_24H_HOURS):
                await _send_booking_email_by_kind(
                    row,
                    "reminder_24h",
                    request,
                    sent_column="reminder_24h_sent_at",
                )
                sent_24h += 1
                continue

            if not row["reminder_2h_sent_at"] and _booking_due_for_reminder(row, now_utc, REMINDER_2H_HOURS):
                await _send_booking_email_by_kind(
                    row,
                    "reminder_2h",
                    request,
                    sent_column="reminder_2h_sent_at",
                )
                sent_2h += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.error("No se ha podido enviar recordatorio de %s: %s", row["id"], exc)
            _mark_booking_email_result(
                row["id"],
                status="failed",
                error=str(exc),
            )
            _record_booking_audit(
                row["id"],
                row["cliente_id"],
                "booking_email_failed",
                {"kind": "reminder", "error": str(exc)},
            )

    return AdminReminderRunResult(
        processed=processed,
        sent_24h=sent_24h,
        sent_2h=sent_2h,
        failed=failed,
    )


async def _create_provider_booking(
    cliente_id: str,
    booking_payload: Dict[str, Any],
) -> ProviderBookingResult:
    _ = (cliente_id, booking_payload)
    return ProviderBookingResult(
        success=True,
        status="internal",
        provider_name="internal",
        message="Reserva registrada internamente.",
    )


def _extract_services_from_info(cliente_id: str) -> List[Dict[str, str]]:
    ruta_info = DATA_DIR / cliente_id / "info.txt"
    if not ruta_info.exists():
        return []

    contenido = ruta_info.read_text(encoding="utf-8")
    servicios: List[Dict[str, str]] = []
    en_seccion = False

    for linea in contenido.splitlines():
        valor = linea.strip()
        lower = valor.lower()

        if not valor:
            continue

        if lower.startswith("servicios y precios"):
            en_seccion = True
            continue

        if en_seccion and valor.endswith(":") and valor.upper() == valor and len(valor) > 3:
            break

        if not en_seccion:
            continue

        if valor.startswith("- ") and valor.endswith(":"):
            nombre = valor[2:-1].strip()
        elif valor.startswith("- Servicio:"):
            nombre = valor.split(":", 1)[1].strip()
        else:
            continue

        service_id = _normalize_service_id(nombre)
        if service_id:
            servicios.append({"id": service_id, "nombre": nombre})

    unique: Dict[str, Dict[str, str]] = {}
    for servicio in servicios:
        unique[servicio["id"]] = servicio

    return list(unique.values())


def _services_for_employee(cliente_id: str, employee_row: Optional[sqlite3.Row]) -> List[Dict[str, str]]:
    services = _extract_services_from_info(cliente_id)
    if not employee_row:
        return services
    service_ids = _employee_service_ids_from_row(employee_row, cliente_id)
    if not service_ids:
        return services
    allowed = set(service_ids)
    return [service for service in services if str(service.get("id") or "") in allowed]


def _service_name_allowed_for_employee(cliente_id: str, employee_row: sqlite3.Row, service_name: str) -> bool:
    normalized_name = _sanitize_text(service_name)
    if not normalized_name:
        return True
    allowed_services = _services_for_employee(cliente_id, employee_row)
    if not allowed_services:
        return not _extract_services_from_info(cliente_id)
    return any(_sanitize_text(service.get("nombre")) == normalized_name for service in allowed_services)


async def _public_slot_sets_for_day(
    cliente_id: str,
    fecha: str,
    *,
    servicio: str = "",
) -> Tuple[Set[str], Set[str]]:
    all_slots: Set[str] = set()
    available_slots: Set[str] = set()
    for employee_row in _list_public_employee_rows(cliente_id, include_inactive=False):
        if servicio and not _service_name_allowed_for_employee(cliente_id, employee_row, servicio):
            continue
        employee_slots = await _available_slots_for_day(cliente_id, fecha, employee_id=employee_row["id"])
        occupied = _booked_slots(cliente_id, fecha, employee_id=employee_row["id"])
        occupied.update(_blocked_slots(cliente_id, fecha, employee_id=employee_row["id"]))
        all_slots.update(employee_slots)
        available_slots.update(slot for slot in employee_slots if slot not in occupied)
    return all_slots, available_slots


async def _resolve_public_booking_employee(
    cliente_id: str,
    fecha: str,
    hora: str,
    *,
    employee_id: str = "",
    servicio: str = "",
) -> sqlite3.Row:
    if employee_id:
        employee_row = _resolve_employee_for_booking(cliente_id, employee_id)
        if bool(employee_row["is_default"]):
            raise HTTPException(status_code=400, detail="La agenda general no se puede seleccionar desde el formulario.")
        if servicio and not _service_name_allowed_for_employee(cliente_id, employee_row, servicio):
            raise HTTPException(
                status_code=400,
                detail="El servicio seleccionado no esta disponible para ese profesional.",
            )
        return employee_row

    candidates = [
        row
        for row in _list_public_employee_rows(cliente_id, include_inactive=False)
        if not servicio or _service_name_allowed_for_employee(cliente_id, row, servicio)
    ]
    if not candidates:
        raise HTTPException(
            status_code=409,
            detail="No hay profesionales disponibles para ese servicio en este momento.",
        )

    available_candidates: List[sqlite3.Row] = []
    for row in candidates:
        if await _booking_slot_available(cliente_id, fecha, hora, employee_id=row["id"]):
            available_candidates.append(row)

    if not available_candidates:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese horario ya no esta disponible. Elige otro tramo.",
        )

    return secrets.choice(available_candidates)


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": app.title,
        "version": app.version,
        "clientes_activos": sorted(CONFIG_CLIENTES.keys()),
    }


@app.post("/auth/login", response_model=AuthLoginResponse)
async def auth_login(data: AuthLoginPayload) -> Response:
    user = _get_user_by_email(data.email)
    if not user or not user["is_active"] or not _verify_secret(data.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales invalidas.")

    with _get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (_utc_now_iso(), user["id"]),
        )
        connection.commit()
    fresh_user = _get_user_by_id(user["id"])
    raw_token = _create_auth_session(user["id"])
    payload = AuthLoginResponse(
        ok=True,
        user=_serialize_auth_user(fresh_user),
        redirect_to=_redirect_for_role(fresh_user["role"]),
    )
    response = JSONResponse(payload.model_dump())
    _set_portal_cookie(response, raw_token)
    return response


@app.post("/auth/logout")
async def auth_logout(
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
) -> Response:
    response = JSONResponse({"ok": True})
    if portal_session:
        _delete_auth_session(portal_session)
    _clear_portal_cookie(response)
    return response


@app.post("/auth/password/change", response_model=AuthSimpleResponse)
async def auth_change_password(
    data: AuthPasswordChangePayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Response:
    if not _verify_secret(data.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="La contrasena actual no es correcta.")
    if data.current_password == data.new_password:
        raise HTTPException(status_code=400, detail="La nueva contrasena debe ser distinta a la actual.")

    _update_user_password(user["id"], data.new_password)
    _delete_user_auth_sessions(user["id"])
    raw_token = _create_auth_session(user["id"])
    response = JSONResponse(
        AuthSimpleResponse(ok=True, message="Contrasena actualizada correctamente.").model_dump()
    )
    _set_portal_cookie(response, raw_token)
    return response


@app.post("/auth/password/forgot", response_model=AuthSimpleResponse)
async def auth_forgot_password(
    data: AuthPasswordForgotPayload,
    request: Request,
) -> AuthSimpleResponse:
    if not _smtp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La recuperacion por correo no esta disponible todavia. Configura SMTP en el servidor.",
        )

    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"password-reset:{client_ip}", 5)

    user = _get_user_by_email(data.email)
    if user and user["is_active"]:
        public_token = _create_password_reset_token(user["id"], requested_from_ip=client_ip)
        try:
            _send_password_reset_email(user, public_token, request)
        except Exception as exc:  # noqa: BLE001
            logger.error("No se ha podido enviar el email de reset a %s: %s", user["email"], exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No se ha podido enviar el correo de recuperacion. Revisa la configuracion SMTP.",
            ) from exc

    return AuthSimpleResponse(
        ok=True,
        message="Si el correo esta registrado, se te enviara un enlace para cambiar la contrasena.",
        retry_after_seconds=max(0, PASSWORD_RESET_RESEND_SECONDS),
    )


@app.post("/auth/password/reset", response_model=AuthSimpleResponse)
async def auth_reset_password(data: AuthPasswordResetPayload) -> AuthSimpleResponse:
    reset_row = _consume_password_reset_token(data.token)
    if _verify_secret(data.new_password, reset_row["password_hash"]):
        raise HTTPException(status_code=400, detail="La nueva contrasena debe ser distinta a la actual.")

    _update_user_password(reset_row["user_id"], data.new_password)
    _delete_user_auth_sessions(reset_row["user_id"])
    return AuthSimpleResponse(ok=True, message="Contrasena restablecida correctamente. Ya puedes iniciar sesion.")


@app.get("/auth/me", response_model=AuthUserPublic)
async def auth_me(user: sqlite3.Row = Depends(_require_authenticated_portal_user)) -> AuthUserPublic:
    return _serialize_auth_user(user)


@app.post("/auth/profile", response_model=AuthUserPublic)
async def auth_update_profile(
    data: AuthProfileUpdatePayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AuthUserPublic:
    updated = _update_user_profile(
        user["id"],
        email=str(data.email),
        display_name=data.display_name,
    )
    return _serialize_auth_user(updated)


@app.get("/auth/dashboard", response_model=PortalDashboardResponse)
async def auth_dashboard_data(
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalDashboardResponse:
    _auto_confirm_pending_bookings()
    _auto_complete_past_bookings()
    target_client_id = _portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    bookings, _ = _list_booking_rows(cliente_id=target_client_id, limit=6, scope="upcoming")
    today_bookings: List[PortalBookingSummary] = []
    today_blocks: List[PortalAgendaBlock] = []
    if target_client_id:
        today_bookings, today_blocks = _portal_today_dashboard(target_client_id, request)
    return PortalDashboardResponse(
        user=_serialize_auth_user(user),
        stats=_portal_stats_for_user(user, target_client_id),
        bookings_upcoming=[_portal_booking_summary_from_row(row, request) for row in bookings],
        bookings_today=today_bookings,
        today_blocks=today_blocks,
    )


@app.get("/auth/bookings", response_model=PortalBookingsResponse)
async def auth_bookings(
    request: Request,
    cliente_id: str = "",
    estado: str = "",
    employee_id: str = "",
    scope: str = "all",
    q: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 20,
    offset: int = 0,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalBookingsResponse:
    _auto_confirm_pending_bookings()
    _auto_complete_past_bookings()
    target_client_id = _portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    normalized_scope = scope.strip().lower() or "all"
    if normalized_scope not in {"all", "upcoming", "history"}:
        raise HTTPException(status_code=400, detail="Scope invalido.")
    rows, total = _list_booking_rows(
        cliente_id=target_client_id,
        employee_id=employee_id.strip(),
        status_filter=estado.strip(),
        search=q.strip(),
        date_from=date_from.strip(),
        date_to=date_to.strip(),
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        scope=normalized_scope,
    )
    return PortalBookingsResponse(
        items=[_portal_booking_summary_from_row(row, request) for row in rows],
        total=total,
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        scope=normalized_scope,
    )


@app.get("/auth/bookings/export")
async def auth_export_bookings(
    cliente_id: str = "",
    date_from: str = "",
    date_to: str = "",
    estado: str = "",
    employee_id: str = "",
    q: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Response:
    target_client_id = _portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    rows, _ = _list_booking_rows(
        cliente_id=target_client_id,
        employee_id=employee_id.strip(),
        status_filter=estado.strip(),
        search=q.strip(),
        date_from=date_from.strip(),
        date_to=date_to.strip(),
        limit=5000,
        scope="all",
    )
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Fecha", "Hora", "Profesional", "Estado", "Nombre", "Email", "Telefono", "Servicio", "Notas"])
    for row in rows:
        writer.writerow(
            [
                row["id"],
                row["booking_date"],
                row["booking_time"],
                row["employee_name"] or "",
                row["status"],
                row["nombre"],
                row["email"],
                row["telefono"] or "",
                row["servicio"] or "",
                row["notas"] or "",
            ]
        )
    filename = f"citas_{date_from or 'inicio'}_{date_to or 'fin'}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/auth/chats", response_model=List[ChatSessionSummary])
async def auth_chats(
    cliente_id: str = "",
    limit: int = 50,
    offset: int = 0,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> List[ChatSessionSummary]:
    target_client_id = _portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    return [
        _chat_session_summary_from_row(row)
        for row in _list_chat_session_rows(
            cliente_id=target_client_id,
            limit=limit,
            offset=offset,
        )
    ]


@app.get("/auth/chats/{session_id}", response_model=ChatSessionDetail)
async def auth_chat_detail(
    session_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ChatSessionDetail:
    target_client_id = _portal_client_id_or_403(user, cliente_id) if (user["role"] != "admin" or cliente_id) else ""
    session_row = _load_chat_session_or_404(session_id, cliente_id=target_client_id)
    return ChatSessionDetail(
        session=_chat_session_summary_from_row(session_row),
        messages=[_chat_message_from_row(row) for row in _load_chat_message_rows(session_id)],
    )


@app.get("/auth/schedule", response_model=PortalSchedulePublic)
async def auth_schedule(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalSchedulePublic:
    return _portal_schedule_from_config(_portal_client_id_or_403(user, cliente_id))


@app.get("/auth/ai-config", response_model=PortalAiConfigPublic)
async def auth_ai_config(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalAiConfigPublic:
    return _portal_ai_config_from_client_config(_portal_client_id_or_403(user, cliente_id))


@app.post("/auth/ai-config", response_model=PortalAiConfigPublic)
async def auth_update_ai_config(
    data: PortalAiConfigPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalAiConfigPublic:
    return _update_portal_ai_config(_portal_client_id_or_403(user, cliente_id), data)


@app.get("/auth/brain", response_model=PortalBrainPublic)
async def auth_brain(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalBrainPublic:
    return _portal_brain_for_client(_portal_client_id_or_403(user, cliente_id))


@app.post("/auth/brain", response_model=PortalBrainPublic)
async def auth_update_brain(
    data: PortalBrainPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalBrainPublic:
    return _update_portal_brain(_portal_client_id_or_403(user, cliente_id), data)


@app.post("/auth/schedule", response_model=PortalSchedulePublic)
async def auth_update_schedule(
    data: PortalScheduleUpdatePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalSchedulePublic:
    return _update_client_schedule(_portal_client_id_or_403(user, cliente_id), data)


@app.post("/auth/schedule/message-preview", response_model=PortalMessagePreviewResponse)
async def auth_schedule_message_preview(
    data: PortalMessagePreviewPayload,
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalMessagePreviewResponse:
    return _booking_message_preview(_portal_client_id_or_403(user, cliente_id), data, request)


@app.post("/auth/schedule/message-test", response_model=AuthSimpleResponse)
async def auth_schedule_message_test(
    data: PortalMessagePreviewPayload,
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AuthSimpleResponse:
    target_client_id = _portal_client_id_or_403(user, cliente_id)
    preview = _booking_message_preview(target_client_id, data, request)
    target_email = str(data.target_email or user["email"] or "").strip()
    if not target_email:
        raise HTTPException(status_code=400, detail="Indica un email donde enviar la prueba.")
    _send_email_message(target_email, preview.subject, preview.text_body, preview.html_body)
    return AuthSimpleResponse(ok=True, message=f"Correo de prueba enviado a {target_email}.")


@app.post("/auth/schedule/blocks", response_model=PortalAgendaBlockCreateResponse)
async def auth_create_schedule_block(
    data: PortalAgendaBlockPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalAgendaBlockCreateResponse:
    rows, skipped_count, date_from, date_to = _create_agenda_blocks(_portal_client_id_or_403(user, cliente_id), data)
    return PortalAgendaBlockCreateResponse(
        items=[_serialize_agenda_block(row) for row in rows],
        created_count=len(rows),
        skipped_count=skipped_count,
        date_from=date_from,
        date_to=date_to,
    )


@app.delete("/auth/schedule/blocks/{block_id}", response_model=AuthSimpleResponse)
async def auth_delete_schedule_block(
    block_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AuthSimpleResponse:
    _delete_agenda_block(_portal_client_id_or_403(user, cliente_id), block_id, employee_id="")
    return AuthSimpleResponse(ok=True, message="Bloqueo eliminado correctamente.")


@app.get("/auth/employees", response_model=PortalEmployeesResponse)
async def auth_list_employees(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalEmployeesResponse:
    return _portal_employees_for_client(_portal_client_id_or_403(user, cliente_id))


@app.get("/auth/services")
async def auth_list_services(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Dict[str, List[Dict[str, str]]]:
    return {"items": _extract_services_from_info(_portal_client_id_or_403(user, cliente_id))}


@app.post("/auth/employees", response_model=PortalEmployeePublic)
async def auth_create_employee(
    data: PortalEmployeePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalEmployeePublic:
    return _create_portal_employee(_portal_client_id_or_403(user, cliente_id), data)


@app.post("/auth/employees/{employee_id}", response_model=PortalEmployeePublic)
async def auth_update_employee(
    employee_id: str,
    data: PortalEmployeePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalEmployeePublic:
    return _update_portal_employee(_portal_client_id_or_403(user, cliente_id), employee_id, data)


@app.post("/auth/employees/{employee_id}/blocks", response_model=PortalAgendaBlockCreateResponse)
async def auth_create_employee_blocks(
    employee_id: str,
    data: PortalAgendaBlockPayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalAgendaBlockCreateResponse:
    target_client_id = _portal_client_id_or_403(user, cliente_id)
    _resolve_employee_for_booking(target_client_id, employee_id, require_active=False)
    rows, skipped_count, date_from, date_to = _create_agenda_blocks(
        target_client_id,
        data,
        employee_id=employee_id,
    )
    return PortalAgendaBlockCreateResponse(
        items=[_serialize_agenda_block(row) for row in rows],
        created_count=len(rows),
        skipped_count=skipped_count,
        date_from=date_from,
        date_to=date_to,
    )


@app.delete("/auth/employees/{employee_id}/blocks/{block_id}", response_model=AuthSimpleResponse)
async def auth_delete_employee_block(
    employee_id: str,
    block_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AuthSimpleResponse:
    target_client_id = _portal_client_id_or_403(user, cliente_id)
    _resolve_employee_for_booking(target_client_id, employee_id, require_active=False)
    _delete_agenda_block(target_client_id, block_id, employee_id=employee_id)
    return AuthSimpleResponse(ok=True, message="Bloqueo del profesional eliminado correctamente.")


@app.post("/auth/bookings/{booking_id}/cancel", response_model=BookingActionResponse)
async def auth_cancel_booking(
    booking_id: str,
    request: Request,
    data: Optional[BookingCancelPayload] = None,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> BookingActionResponse:
    booking_row = _load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")

    if booking_row["status"] == "cancelled":
        return BookingActionResponse(
            ok=True,
            booking_id=booking_id,
            estado="cancelled",
            mensaje="La cita ya estaba cancelada.",
            manage_url=_booking_row_manage_url(booking_row, request),
            provider_booking_url=booking_row["provider_booking_url"] or "",
        )

    cancel_reason = _sanitize_text((data.motivo if data else ""), allow_multiline=True)
    await _cancel_provider_booking(booking_row)
    _update_booking_record(
        booking_id,
        status="cancelled",
        cancelled_at=_utc_now_iso(),
        provider_status="cancelled",
    )
    _record_booking_audit(
        booking_id,
        booking_row["cliente_id"],
        "booking_cancelled",
        {
            "source": "portal",
            "role": user["role"],
            "user_id": user["id"],
            "reason": cancel_reason,
            "reason_sent_to_customer": bool(cancel_reason),
        },
    )
    refreshed = _load_booking_or_404(booking_id)
    try:
        await _send_booking_email_by_kind(
            refreshed,
            "cancelled",
            request,
            extra_message=cancel_reason,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("No se ha podido enviar el email de cancelacion %s: %s", refreshed["id"], exc)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado="cancelled",
        mensaje="La cita ha sido cancelada correctamente.",
        manage_url=_booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
    )


@app.get("/auth/bookings/{booking_id}/timeline", response_model=BookingAuditResponse)
async def auth_booking_timeline(
    booking_id: str,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> BookingAuditResponse:
    booking_row = _load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    return BookingAuditResponse(items=[_booking_audit_entry_from_row(row) for row in _list_booking_audit_rows(booking_id)])


@app.post("/auth/bookings/{booking_id}/reschedule", response_model=BookingActionResponse)
async def auth_reschedule_booking(
    booking_id: str,
    data: BookingReschedulePayload,
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> BookingActionResponse:
    booking_row = _load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    return await _update_booking_details(
        booking_row,
        _booking_update_payload_from_reschedule(booking_row, data),
        request,
        source="portal",
        audit_payload={"role": user["role"], "user_id": user["id"]},
    )


@app.post("/auth/bookings/{booking_id}/update", response_model=BookingActionResponse)
async def auth_update_booking(
    booking_id: str,
    data: BookingUpdatePayload,
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> BookingActionResponse:
    booking_row = _load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    return await _update_booking_details(
        booking_row,
        data,
        request,
        source="portal",
        audit_payload={"role": user["role"], "user_id": user["id"]},
    )


@app.get("/auth/clientes", response_model=List[AdminClienteResumen])
async def auth_clientes(user: sqlite3.Row = Depends(_require_authenticated_admin_user)) -> List[AdminClienteResumen]:
    _ = user
    return await admin_clientes()


@app.get("/auth/users", response_model=AuthManagedUsersResponse)
async def auth_list_users(
    role: str = "",
    cliente_id: str = "",
    include_inactive: bool = True,
    user: sqlite3.Row = Depends(_require_authenticated_admin_user),
) -> AuthManagedUsersResponse:
    _ = user
    normalized_role = role.strip().lower()
    if normalized_role and normalized_role not in {"admin", "client"}:
        raise HTTPException(status_code=400, detail="Rol invalido.")
    normalized_cliente_id = slugify_company(cliente_id) if cliente_id.strip() else ""
    if normalized_cliente_id:
        _get_client_config(normalized_cliente_id)
    rows = _list_users(role=normalized_role, cliente_id=normalized_cliente_id, include_inactive=include_inactive)
    return AuthManagedUsersResponse(
        items=[_serialize_managed_user(row) for row in rows],
        total=len(rows),
    )


@app.post("/auth/users", response_model=AuthManagedUser)
async def auth_create_user_managed(
    data: PortalCreateUserPayload,
    user: sqlite3.Row = Depends(_require_authenticated_admin_user),
) -> AuthManagedUser:
    _ = user
    role = data.role.strip().lower() or "client"
    if role not in {"admin", "client"}:
        raise HTTPException(status_code=400, detail="Rol invalido.")
    cliente_id = ""
    if role == "client":
        cliente_id = slugify_company(data.cliente_id)
        _assert_valid_client_id(cliente_id)
        _get_client_config(cliente_id)
    if _get_user_by_email(data.email):
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese email.")
    created = _create_user(
        email=data.email,
        password=data.password,
        role=role,
        display_name=data.display_name,
        cliente_id=cliente_id,
    )
    return _serialize_managed_user(created)


@app.post("/auth/users/{user_id}/deactivate", response_model=AuthSimpleResponse)
async def auth_deactivate_user(
    user_id: str,
    user: sqlite3.Row = Depends(_require_authenticated_admin_user),
) -> AuthSimpleResponse:
    target_user = _load_managed_user_or_404(user_id)
    if not target_user["is_active"]:
        return AuthSimpleResponse(ok=True, message="El usuario ya estaba desactivado.")
    _assert_admin_can_manage_user(user, target_user, "desactivar")
    _set_user_active(user_id, False)
    _delete_user_auth_sessions(user_id)
    return AuthSimpleResponse(ok=True, message="Usuario desactivado correctamente.")


@app.post("/auth/users/{user_id}/activate", response_model=AuthSimpleResponse)
async def auth_activate_user(
    user_id: str,
    user: sqlite3.Row = Depends(_require_authenticated_admin_user),
) -> AuthSimpleResponse:
    _ = user
    target_user = _load_managed_user_or_404(user_id)
    if target_user["is_active"]:
        return AuthSimpleResponse(ok=True, message="El usuario ya estaba activo.")
    _set_user_active(user_id, True)
    return AuthSimpleResponse(ok=True, message="Usuario activado correctamente.")


@app.post("/auth/users/{user_id}/reset-link", response_model=AuthSimpleResponse)
async def auth_send_user_reset_link(
    user_id: str,
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_admin_user),
) -> AuthSimpleResponse:
    _ = user
    if not _smtp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La recuperacion por correo no esta disponible todavia. Configura SMTP en el servidor.",
        )
    target_user = _load_managed_user_or_404(user_id)
    if not target_user["is_active"]:
        raise HTTPException(status_code=400, detail="No puedes enviar reset a un usuario desactivado.")
    public_token = _create_password_reset_token(
        target_user["id"],
        requested_from_ip=(request.client.host if request.client else "admin"),
    )
    try:
        _send_password_reset_email(target_user, public_token, request)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se ha podido enviar el reset al usuario %s: %s", target_user["email"], exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se ha podido enviar el correo de recuperacion.",
        ) from exc
    return AuthSimpleResponse(ok=True, message="Enlace de recuperacion enviado correctamente.")


@app.delete("/auth/users/{user_id}", response_model=AuthSimpleResponse)
async def auth_delete_user(
    user_id: str,
    user: sqlite3.Row = Depends(_require_authenticated_admin_user),
) -> AuthSimpleResponse:
    target_user = _load_managed_user_or_404(user_id)
    _assert_admin_can_manage_user(user, target_user, "eliminar")
    _delete_user(user_id)
    return AuthSimpleResponse(ok=True, message="Usuario eliminado correctamente.")


@app.get("/acceso", include_in_schema=False)
@app.get("/login", include_in_schema=False)
async def access_entry(
    request: Request,
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
) -> Response:
    if "reset_token" not in request.query_params:
        user = _get_authenticated_portal_user_or_none(portal_session)
        if user:
            return RedirectResponse(_redirect_for_role(user["role"]))

    index_path = ACCESS_UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Acceso no disponible.")
    html = (
        index_path.read_text(encoding="utf-8")
        .replace("__MARKETING_SITE_URL__", escape(MARKETING_SITE_URL))
        .replace("__SUPPORT_EMAIL__", escape(PORTAL_SUPPORT_EMAIL))
    )
    return HTMLResponse(html)


@app.get("/portal", include_in_schema=False)
async def portal_entry(
    request: Request,
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
) -> Response:
    user = _get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso")
    requested_client_id = str(request.query_params.get("cliente_id", "")).strip()
    if user["role"] == "admin" and not requested_client_id:
        return RedirectResponse("/dashboard")
    if user["role"] == "admin" and requested_client_id:
        _get_client_config(requested_client_id)

    index_path = PORTAL_UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Portal no disponible.")
    html = (
        index_path.read_text(encoding="utf-8")
        .replace("__MARKETING_SITE_URL__", escape(MARKETING_SITE_URL))
        .replace("__SUPPORT_EMAIL__", escape(PORTAL_SUPPORT_EMAIL))
    )
    return HTMLResponse(html)


@app.get("/dashboard", include_in_schema=False)
async def dashboard(
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
) -> Response:
    user = _get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso")
    if user["role"] != "admin":
        return RedirectResponse("/portal")
    index_path = ADMIN_UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Panel admin no disponible.")
    return FileResponse(index_path)


@app.get("/demo/{cliente_id}", include_in_schema=False)
async def demo_cliente(cliente_id: str, request: Request) -> HTMLResponse:
    _assert_valid_client_id(cliente_id)
    _get_client_config(cliente_id)
    return HTMLResponse(_build_demo_page(cliente_id, request))


@app.post("/consulta")
async def solicitar_consulta(data: ConsultaLeadPayload, request: Request) -> Dict[str, Any]:
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"consulta:{client_ip}", 5)

    servicio_texto = data.servicio or "No especificado"
    empresa_texto  = data.empresa  or "No especificada"
    telefono_texto = data.telefono or "No proporcionado"
    mensaje_texto  = data.mensaje  or "(sin mensaje)"

    asunto = f"[Vantelia] Nueva consulta gratuita de {escape(data.nombre)}"
    cuerpo_text = (
        f"Nueva solicitud de consulta gratuita recibida desde vantelia.es\n\n"
        f"Nombre:   {data.nombre}\n"
        f"Email:    {data.email}\n"
        f"Teléfono: {telefono_texto}\n"
        f"Empresa:  {empresa_texto}\n"
        f"Servicio: {servicio_texto}\n\n"
        f"Mensaje:\n{mensaje_texto}\n\n"
        f"---\nIP de origen: {client_ip}\n"
        f"Fecha: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    )
    cuerpo_html = f"""
<div style="font-family:sans-serif;max-width:560px;margin:0 auto;color:#1a1a2e">
  <h2 style="color:#00b1d9">Nueva consulta gratuita — Vantelia</h2>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="padding:6px 0;color:#666;width:110px">Nombre</td><td style="padding:6px 0;font-weight:600">{escape(data.nombre)}</td></tr>
    <tr><td style="padding:6px 0;color:#666">Email</td><td style="padding:6px 0"><a href="mailto:{escape(data.email)}">{escape(data.email)}</a></td></tr>
    <tr><td style="padding:6px 0;color:#666">Teléfono</td><td style="padding:6px 0">{escape(telefono_texto)}</td></tr>
    <tr><td style="padding:6px 0;color:#666">Empresa</td><td style="padding:6px 0">{escape(empresa_texto)}</td></tr>
    <tr><td style="padding:6px 0;color:#666">Servicio</td><td style="padding:6px 0">{escape(servicio_texto)}</td></tr>
  </table>
  <p style="margin-top:16px;color:#333"><strong>Mensaje:</strong><br>{escape(mensaje_texto).replace(chr(10), '<br>')}</p>
  <hr style="margin:20px 0;border:none;border-top:1px solid #eee">
  <p style="font-size:12px;color:#999">IP: {escape(client_ip)} · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</div>"""

    if _smtp_configured():
        try:
            _send_email_message(PORTAL_SUPPORT_EMAIL, asunto, cuerpo_text, cuerpo_html)
        except Exception as exc:
            logger.error("Error enviando notificacion de consulta: %s", exc)

    logger.info("Consulta recibida de %s <%s> (IP: %s)", data.nombre, data.email, client_ip)
    return {"ok": True, "message": "Solicitud recibida. Te respondemos en menos de 24h."}


@app.get("/health")
async def healthcheck() -> Dict[str, Any]:
    checks: Dict[str, str] = {
        "config": "ok" if CONFIG_PATH.exists() else "missing",
        "data_dir": "ok" if DATA_DIR.exists() else "missing",
        "storage_dir": "ok" if STORAGE_DIR.exists() else "missing",
        "database": "unknown",
        "widget_bundle": "ok" if (WIDGET_DIR / "widget.min.js").exists() else "missing",
    }
    try:
        with _get_db_connection() as connection:
            connection.execute("SELECT 1").fetchone()
            checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.error("Healthcheck database failed: %s", exc)
        checks["database"] = "error"

    critical_checks = ["config", "data_dir", "storage_dir", "database"]
    overall_status = "ok" if all(checks.get(name) == "ok" for name in critical_checks) else "degraded"
    return {
        "status": overall_status,
        "version": app.version,
        "openai_configured": bool(OPENAI_API_KEY),
        "clientes_configurados": len(CONFIG_CLIENTES),
        "checks": checks,
        "runtime": {
            "started_at": STARTED_AT.isoformat(),
            "uptime_seconds": int((datetime.now(timezone.utc) - STARTED_AT).total_seconds()),
            "data_dir": str(DATA_DIR),
            "storage_dir": str(STORAGE_DIR),
        },
    }


@app.get("/admin/template/{cliente_id}", dependencies=[Depends(_require_admin_token)])
async def admin_template(cliente_id: str, request: Request) -> AdminClienteDetalle:
    _assert_valid_client_id(cliente_id)
    payload = _default_admin_payload(cliente_id)
    snippet = _build_install_snippet(cliente_id, request)
    return AdminClienteDetalle(
        cliente_id=cliente_id,
        config=payload,
        install_snippet=snippet["install_snippet"],
        widget_script_url=snippet["widget_script_url"],
        api_base_url=snippet["api_base_url"],
        demo_url=snippet["demo_url"],
    )


@app.post(
    "/admin/alta-express",
    dependencies=[Depends(_require_admin_token)],
    response_model=AdminAltaExpressResponse,
)
async def admin_alta_express(
    data: AdminAltaExpressPayload,
    request: Request,
) -> AdminAltaExpressResponse:
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY no esta configurada en el backend.",
        )

    cliente_id = slugify_company(data.cliente_id)
    _assert_valid_client_id(cliente_id)

    try:
        result = run_onboarding(
            website_url=data.website_url,
            api_key=OPENAI_API_KEY,
            nombre_bot=data.nombre_bot,
            tono=data.tono,
            idioma=data.idioma,
            max_paginas=data.max_paginas,
        )
        payload = _payload_from_alta_express(
            cliente_id=cliente_id,
            result=result,
            nombre_bot=data.nombre_bot,
            tono=data.tono,
            idioma=data.idioma,
            color=data.color,
            booking_enabled=data.booking_enabled,
            booking_timezone=data.booking_timezone,
        )
        payload.reindex_after_save = data.reindex_after_save
        _validate_single_client_runtime(cliente_id, _config_from_admin_payload(cliente_id, payload))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se ha podido completar el alta express: {exc}",
        ) from exc

    snippet = _build_install_snippet(cliente_id, request)
    save_result = None
    if data.auto_save:
        save_result = _save_admin_client_payload(cliente_id, payload, request)

    return AdminAltaExpressResponse(
        cliente_id=cliente_id,
        detected_business_name=result.detected_business_name,
        normalized_url=result.normalized_url,
        links_found=len(result.links),
        config=payload,
        saved=bool(save_result),
        reindexed=save_result.reindexed if save_result else False,
        reindex_error=save_result.reindex_error if save_result else "",
        install_snippet=(save_result.install_snippet if save_result else snippet["install_snippet"]),
        widget_script_url=(save_result.widget_script_url if save_result else snippet["widget_script_url"]),
        api_base_url=(save_result.api_base_url if save_result else snippet["api_base_url"]),
        demo_url=(save_result.demo_url if save_result else snippet["demo_url"]),
    )


@app.get(
    "/admin/clientes",
    dependencies=[Depends(_require_admin_token)],
    response_model=List[AdminClienteResumen],
)
async def admin_clientes() -> List[AdminClienteResumen]:
    _auto_confirm_pending_bookings()
    summaries: List[AdminClienteResumen] = []
    booking_counts: Dict[str, Dict[str, int]] = {}
    with _get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT cliente_id,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status IN ('confirmed', 'pending_review') THEN 1 ELSE 0 END) AS pending
            FROM bookings
            GROUP BY cliente_id
            """
        ).fetchall()
        booking_counts = {
            row["cliente_id"]: {
                "total": int(row["total"] or 0),
                "pending": int(row["pending"] or 0),
            }
            for row in rows
        }

    for cliente_id, config in sorted(CONFIG_CLIENTES.items(), key=lambda item: item[0].lower()):
        booking_cfg = config.get("booking", {})
        whatsapp_cfg = config.get("whatsapp", {})
        contacto = config.get("contacto", {})
        branding = config.get("branding", {})
        info_path = _client_info_path(cliente_id)
        client_counts = booking_counts.get(cliente_id, {})
        summaries.append(
            AdminClienteResumen(
                cliente_id=cliente_id,
                nombre=config["nombre"],
                booking_enabled=bool(booking_cfg.get("enabled")),
                booking_provider=str(booking_cfg.get("provider", "internal")),
                booking_timezone=str(booking_cfg.get("timezone", DEFAULT_TIMEZONE)),
                booking_day_start=str(booking_cfg.get("day_start", "09:00")),
                booking_day_end=str(booking_cfg.get("day_end", "18:00")),
                allowed_origins=list(config.get("allowed_origins", [])),
                contacto_email=str(contacto.get("email", "")),
                contacto_telefono=str(contacto.get("telefono", "")),
                branding_text=str(branding.get("powered_by", "")),
                whatsapp_enabled=bool(whatsapp_cfg.get("enabled", False)),
                whatsapp_phone_number_id=str(whatsapp_cfg.get("phone_number_id", "")),
                has_info_file=info_path.exists(),
                info_file_size=(info_path.stat().st_size if info_path.exists() else 0),
                bookings_total=int(client_counts.get("total", 0)),
                bookings_pending=int(client_counts.get("pending", 0)),
            )
        )
    return summaries


@app.get(
    "/admin/clientes/{cliente_id}",
    dependencies=[Depends(_require_admin_token)],
    response_model=AdminClienteDetalle,
)
async def admin_cliente_detalle(cliente_id: str, request: Request) -> AdminClienteDetalle:
    _assert_valid_client_id(cliente_id)
    config = _get_client_config(cliente_id)
    payload = _client_payload_from_config(config, _read_info_txt(cliente_id))
    snippet = _build_install_snippet(cliente_id, request)
    return AdminClienteDetalle(
        cliente_id=cliente_id,
        config=payload,
        install_snippet=snippet["install_snippet"],
        widget_script_url=snippet["widget_script_url"],
        api_base_url=snippet["api_base_url"],
        demo_url=snippet["demo_url"],
    )


@app.put(
    "/admin/clientes/{cliente_id}",
    dependencies=[Depends(_require_admin_token)],
    response_model=AdminClienteSaveResult,
)
async def admin_guardar_cliente(
    cliente_id: str,
    data: AdminClientePayload,
    request: Request,
) -> AdminClienteSaveResult:
    _assert_valid_client_id(cliente_id)
    return _save_admin_client_payload(cliente_id, data, request)


@app.get(
    "/admin/bookings",
    dependencies=[Depends(_require_admin_token)],
    response_model=List[AdminBookingResumen],
)
async def admin_bookings(
    request: Request,
    cliente_id: str = "",
    estado: str = "",
    q: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
    limit: int = 100,
) -> List[AdminBookingResumen]:
    _auto_confirm_pending_bookings()
    _auto_complete_past_bookings()
    rows, _ = _list_booking_rows(
        cliente_id=cliente_id.strip(),
        status_filter=estado.strip(),
        search=q.strip(),
        date_from=fecha_desde.strip(),
        date_to=fecha_hasta.strip(),
        limit=max(1, min(limit, 500)),
    )
    return [_booking_admin_summary_from_row(row, request) for row in rows]


@app.post(
    "/admin/bookings/{booking_id}/cancel",
    dependencies=[Depends(_require_admin_token)],
    response_model=BookingActionResponse,
)
async def admin_cancel_booking(booking_id: str, request: Request) -> BookingActionResponse:
    booking_row = _load_booking_or_404(booking_id)
    if booking_row["status"] == "cancelled":
        return BookingActionResponse(
            ok=True,
            booking_id=booking_id,
            estado="cancelled",
            mensaje="La cita ya estaba cancelada.",
            manage_url=_booking_row_manage_url(booking_row, request),
            provider_booking_url=booking_row["provider_booking_url"] or "",
        )

    await _cancel_provider_booking(booking_row)
    cancelled_at = _utc_now_iso()
    _update_booking_record(
        booking_id,
        status="cancelled",
        cancelled_at=cancelled_at,
        provider_status="cancelled",
    )
    _record_booking_audit(booking_id, booking_row["cliente_id"], "booking_cancelled", {"source": "admin"})
    refreshed = _load_booking_or_404(booking_id)
    try:
        await _send_booking_email_by_kind(refreshed, "cancelled", request)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se ha podido enviar el email de cancelacion %s: %s", booking_id, exc)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado="cancelled",
        mensaje="La cita ha sido cancelada.",
        manage_url=_booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
    )


@app.post(
    "/admin/bookings/{booking_id}/reschedule",
    dependencies=[Depends(_require_admin_token)],
    response_model=BookingActionResponse,
)
async def admin_reschedule_booking(
    booking_id: str,
    data: BookingReschedulePayload,
    request: Request,
) -> BookingActionResponse:
    booking_row = _load_booking_or_404(booking_id)
    return await _update_booking_details(
        booking_row,
        _booking_update_payload_from_reschedule(booking_row, data),
        request,
        source="admin",
    )


@app.post(
    "/admin/bookings/{booking_id}/resend-email",
    dependencies=[Depends(_require_admin_token)],
    response_model=BookingActionResponse,
)
async def admin_resend_booking_email(booking_id: str, request: Request) -> BookingActionResponse:
    booking_row = _load_booking_or_404(booking_id)
    kind = "received" if booking_row["status"] == "pending_review" else "confirmed"
    if booking_row["status"] == "cancelled":
        kind = "cancelled"
    await _send_booking_email_by_kind(booking_row, kind, request, respect_enabled=False)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado=booking_row["status"],
        mensaje="Correo reenviado correctamente.",
        manage_url=_booking_row_manage_url(booking_row, request),
        provider_booking_url=booking_row["provider_booking_url"] or "",
    )


@app.get(
    "/admin/bookings/{booking_id}/timeline",
    dependencies=[Depends(_require_admin_token)],
    response_model=BookingAuditResponse,
)
async def admin_booking_timeline(booking_id: str) -> BookingAuditResponse:
    _load_booking_or_404(booking_id)
    return BookingAuditResponse(items=[_booking_audit_entry_from_row(row) for row in _list_booking_audit_rows(booking_id)])


@app.get(
    "/admin/chats",
    dependencies=[Depends(_require_admin_token)],
    response_model=List[ChatSessionSummary],
)
async def admin_chats(
    cliente_id: str = "",
    limit: int = 50,
    offset: int = 0,
) -> List[ChatSessionSummary]:
    if cliente_id:
        _get_client_config(cliente_id)
    return [
        _chat_session_summary_from_row(row)
        for row in _list_chat_session_rows(
            cliente_id=cliente_id.strip(),
            limit=limit,
            offset=offset,
        )
    ]


@app.get(
    "/admin/chats/{session_id}",
    dependencies=[Depends(_require_admin_token)],
    response_model=ChatSessionDetail,
)
async def admin_chat_detail(session_id: str, cliente_id: str = "") -> ChatSessionDetail:
    if cliente_id:
        _get_client_config(cliente_id)
    session_row = _load_chat_session_or_404(session_id, cliente_id=cliente_id.strip())
    return ChatSessionDetail(
        session=_chat_session_summary_from_row(session_row),
        messages=[_chat_message_from_row(row) for row in _load_chat_message_rows(session_id)],
    )


@app.post(
    "/admin/bookings/reminders/run",
    dependencies=[Depends(_require_admin_token)],
    response_model=AdminReminderRunResult,
)
async def admin_run_booking_reminders(request: Request) -> AdminReminderRunResult:
    return await _run_booking_reminders(request)


@app.get("/booking/manage/{manage_token}", include_in_schema=False)
async def booking_manage_page(manage_token: str, request: Request) -> HTMLResponse:
    booking_row = _load_booking_by_token_or_404(manage_token)
    booking = _booking_public_detail_from_row(booking_row, request)
    viewer = str(request.query_params.get("viewer", "customer")).strip().lower()
    if viewer not in {"customer", "client"}:
        viewer = "customer"
    return HTMLResponse(_booking_manage_page(booking, viewer=viewer))


@app.get("/booking/manage/{manage_token}/data", response_model=BookingDetailPublic)
async def booking_manage_data(manage_token: str, request: Request) -> BookingDetailPublic:
    booking_row = _load_booking_by_token_or_404(manage_token)
    return _booking_public_detail_from_row(booking_row, request)


@app.post("/booking/manage/{manage_token}/cancel", response_model=BookingActionResponse)
async def booking_manage_cancel(manage_token: str, request: Request) -> BookingActionResponse:
    booking_row = _load_booking_by_token_or_404(manage_token)
    if booking_row["status"] == "cancelled":
        return BookingActionResponse(
            ok=True,
            booking_id=booking_row["id"],
            estado="cancelled",
            mensaje="La cita ya estaba cancelada.",
            manage_url=_booking_row_manage_url(booking_row, request),
            provider_booking_url=booking_row["provider_booking_url"] or "",
        )
    await _cancel_provider_booking(booking_row)
    _update_booking_record(
        booking_row["id"],
        status="cancelled",
        cancelled_at=_utc_now_iso(),
        provider_status="cancelled",
    )
    _record_booking_audit(
        booking_row["id"],
        booking_row["cliente_id"],
        "booking_cancelled",
        {"source": "customer"},
    )
    refreshed = _load_booking_by_token_or_404(manage_token)
    try:
        await _send_booking_email_by_kind(refreshed, "cancelled", request)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se ha podido enviar el email de cancelacion %s: %s", refreshed["id"], exc)
    return BookingActionResponse(
        ok=True,
        booking_id=refreshed["id"],
        estado="cancelled",
        mensaje="Tu cita ha sido cancelada correctamente.",
        manage_url=_booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
    )


@app.post("/booking/manage/{manage_token}/reschedule", response_model=BookingActionResponse)
async def booking_manage_reschedule(
    manage_token: str,
    data: BookingReschedulePayload,
    request: Request,
) -> BookingActionResponse:
    booking_row = _load_booking_by_token_or_404(manage_token)
    return await _update_booking_details(
        booking_row,
        _booking_update_payload_from_reschedule(booking_row, data),
        request,
        source="customer",
    )


@app.post("/booking/manage/{manage_token}/update", response_model=BookingActionResponse)
async def booking_manage_update(
    manage_token: str,
    data: BookingUpdatePayload,
    request: Request,
) -> BookingActionResponse:
    booking_row = _load_booking_by_token_or_404(manage_token)
    protected_payload = data.model_copy(update={"email": booking_row["email"]})
    return await _update_booking_details(
        booking_row,
        protected_payload,
        request,
        source="customer",
    )


@app.get("/cliente/{cliente_id}", response_model=ConfigPublicaCliente)
async def info_cliente(cliente_id: str, request: Request) -> ConfigPublicaCliente:
    _assert_valid_client_id(cliente_id)
    _enforce_allowed_origin(request, cliente_id)
    config = _get_client_config(cliente_id)

    contacto = config.get("contacto", {})
    branding = config.get("branding", {})

    return ConfigPublicaCliente(
        nombre=config["nombre"],
        icono=config["icono"],
        color=config["color"],
        bienvenida=config["bienvenida"],
        booking_enabled=config["booking"]["enabled"],
        branding_text=branding.get("powered_by", "Powered by Vantelia"),
        contact_email=contacto.get("email", ""),
        contact_phone=contacto.get("telefono", ""),
    )


@app.get("/profesionales/{cliente_id}")
async def public_employees(cliente_id: str, request: Request) -> Dict[str, List[Dict[str, Any]]]:
    _assert_valid_client_id(cliente_id)
    _enforce_allowed_origin(request, cliente_id)
    return {
        "items": [
            {
                "employee_id": row["id"],
                "name": row["name"],
                "role_label": row["role_label"] or "",
                "color": _normalize_employee_color(row["color"] or "#00b1d9"),
                "is_default": bool(row["is_default"]),
                "service_ids": _employee_service_ids_from_row(row, cliente_id),
                "allows_all_services": not _employee_service_ids_from_row(row, cliente_id),
            }
            for row in _list_public_employee_rows(cliente_id, include_inactive=False)
        ]
    }


@app.post("/chat", response_model=RespuestaChat)
async def chat(data: MensajeChat, request: Request) -> RespuestaChat:
    _assert_valid_client_id(data.cliente_id)
    _enforce_allowed_origin(request, data.cliente_id)
    _cleanup_sessions()

    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"chat:{data.cliente_id}:{client_ip}", CHAT_RATE_LIMIT)

    message = _sanitize_text(data.mensaje, allow_multiline=True)
    if not message:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacio.")

    session_id = _normalize_session_id(data.session_id)
    try:
        return await _process_chat_message(
            cliente_id=data.cliente_id,
            message=message,
            session_id=session_id,
            request=request,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error procesando chat de %s: %s", data.cliente_id, exc)
        raise HTTPException(status_code=500, detail="No se pudo procesar el mensaje.") from exc


@app.get("/disponibilidad", response_model=RespuestaDisponibilidad)
async def disponibilidad(
    cliente_id: str,
    fecha: str,
    request: Request,
    employee_id: str = "",
    servicio: str = "",
) -> RespuestaDisponibilidad:
    _assert_valid_client_id(cliente_id)
    _enforce_allowed_origin(request, cliente_id)
    config = _get_client_config(cliente_id)

    if not config["booking"]["enabled"]:
        raise HTTPException(status_code=404, detail="La reserva online no esta habilitada para este cliente.")

    selected_day = _parse_date(fecha)
    _validate_booking_window(cliente_id, selected_day)

    try:
        if employee_id:
            employee_row = _resolve_employee_for_booking(cliente_id, employee_id)
            slots = await _available_slots_for_day(cliente_id, fecha, employee_id=employee_row["id"])
            occupied = _booked_slots(cliente_id, fecha, employee_id=employee_row["id"])
            occupied.update(_blocked_slots(cliente_id, fecha, employee_id=employee_row["id"]))
            return RespuestaDisponibilidad(
                fecha=fecha,
                timezone=employee_row["timezone"] or config["booking"]["timezone"],
                employee_id=employee_row["id"],
                slots=[SlotDisponibilidad(hora=hora, disponible=hora not in occupied) for hora in slots],
            )

        all_slots, available_slots = await _public_slot_sets_for_day(
            cliente_id,
            fecha,
            servicio=_sanitize_text(servicio),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.error("No se pudo consultar disponibilidad externa de %s: %s", cliente_id, exc)
        raise HTTPException(
            status_code=502,
            detail="No se ha podido consultar la disponibilidad del proveedor de calendario.",
        ) from exc

    return RespuestaDisponibilidad(
        fecha=fecha,
        timezone=config["booking"]["timezone"],
        employee_id="",
        slots=[
            SlotDisponibilidad(hora=hora, disponible=hora in available_slots)
            for hora in sorted(all_slots)
        ],
    )


@app.post("/agendar", response_model=RespuestaAgendado)
async def agendar(data: DatosCita, request: Request) -> RespuestaAgendado:
    _assert_valid_client_id(data.cliente_id)
    _enforce_allowed_origin(request, data.cliente_id)
    config = _get_client_config(data.cliente_id)

    if not config["booking"]["enabled"]:
        raise HTTPException(status_code=404, detail="La reserva online no esta habilitada para este cliente.")

    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"booking:{data.cliente_id}:{client_ip}", BOOKING_RATE_LIMIT)

    booking_date_dt = _parse_date(data.fecha)
    _validate_booking_window(data.cliente_id, booking_date_dt)
    booking_date = booking_date_dt.strftime("%Y-%m-%d")
    booking_time = _parse_time(data.hora).strftime("%H:%M")
    nombre = _sanitize_text(data.nombre)
    telefono = _sanitize_text(data.telefono)
    servicio = _sanitize_text(data.servicio)
    notas = _sanitize_text(data.notas, allow_multiline=True)
    employee_row = await _resolve_public_booking_employee(
        data.cliente_id,
        booking_date,
        booking_time,
        employee_id=data.employee_id,
        servicio=servicio,
    )

    booking_id = f"bk_{secrets.token_urlsafe(10)}"
    manage_token = _generate_manage_token()
    created_at = _utc_now_iso()
    provider = _get_booking_provider(config)
    start_local, end_local = _booking_start_end(
        data.cliente_id,
        booking_date,
        booking_time,
        employee_id=employee_row["id"],
    )
    booking_timezone = employee_row["timezone"] or config["booking"]["timezone"]

    booking_payload = {
        "booking_id": booking_id,
        "cliente_id": data.cliente_id,
        "empresa": config["nombre"],
        "employee_id": employee_row["id"],
        "employee_name": employee_row["name"],
        "nombre": nombre,
        "email": str(data.email),
        "telefono": telefono,
        "servicio": servicio,
        "fecha": booking_date,
        "hora": booking_time,
        "notas": notas,
        "source": "vantelia_widget",
        "created_at": created_at,
    }

    webhook_payload = {
        "booking_id": booking_id,
        "cliente_id": data.cliente_id,
        "empresa": config["nombre"],
        "employee_id": employee_row["id"],
        "employee_name": employee_row["name"],
        "nombre": nombre,
        "email": str(data.email),
        "telefono": telefono,
        "servicio": servicio,
        "fecha": booking_date,
        "hora": booking_time,
        "notas": notas,
        "source": "vantelia_widget",
        "created_at": created_at,
    }

    try:
        provider_result = await _create_provider_booking(data.cliente_id, booking_payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.error("Error creando cita externa para %s: %s", data.cliente_id, exc)
        raise HTTPException(
            status_code=502,
            detail="No se ha podido crear la cita en el proveedor de calendario.",
        ) from exc

    webhook_payload.update(
        {
            "provider_name": provider_result.provider_name,
            "provider_booking_id": provider_result.provider_booking_id,
            "provider_booking_url": provider_result.provider_booking_url,
        }
    )

    delivered, webhook_status = await _send_booking_to_webhook(data.cliente_id, webhook_payload)
    booking_status = "confirmed"
    provider_status = provider_result.status

    if provider == "internal":
        booking_status = "confirmed"
        provider_status = webhook_status

    record = {
        "id": booking_id,
        "cliente_id": data.cliente_id,
        "employee_id": employee_row["id"],
        "employee_name": employee_row["name"],
        "nombre": nombre,
        "email": str(data.email),
        "telefono": telefono,
        "servicio": servicio,
        "booking_date": booking_date,
        "booking_time": booking_time,
        "notas": notas,
        "status": booking_status,
        "provider_name": provider_result.provider_name,
        "provider_status": provider_status,
        "provider_booking_id": provider_result.provider_booking_id,
        "provider_booking_url": provider_result.provider_booking_url,
        "manage_token": manage_token,
        "timezone": booking_timezone,
        "start_at": _to_utc_iso(start_local),
        "end_at": _to_utc_iso(end_local),
        "confirmed_at": created_at if booking_status == "confirmed" else "",
        "cancelled_at": "",
        "rescheduled_at": "",
        "rescheduled_from_booking_id": "",
        "confirmation_email_sent_at": "",
        "reminder_24h_sent_at": "",
        "reminder_2h_sent_at": "",
        "customer_email_status": "",
        "customer_email_last_error": "",
        "source": "widget",
        "created_at": created_at,
    }
    try:
        _store_booking(record)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese horario acaba de ser reservado por otra persona. Elige otro tramo.",
        ) from exc
    _record_booking_audit(
        booking_id,
        data.cliente_id,
        "booking_created",
        {
            "status": booking_status,
            "provider_name": provider_result.provider_name,
            "provider_status": provider_status,
            "employee_id": employee_row["id"],
            "employee_name": employee_row["name"],
        },
    )

    booking_row = _get_booking_row_by_id(booking_id)
    if booking_row:
        email_status_key = "confirmed"
        try:
            await _send_booking_email_by_kind(
                booking_row,
                email_status_key,
                request,
                sent_column="confirmation_email_sent_at",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("No se ha podido enviar el email de booking %s: %s", booking_id, exc)
            _mark_booking_email_result(
                booking_id,
                status="failed",
                error=str(exc),
            )
            _record_booking_audit(
                booking_id,
                data.cliente_id,
                "booking_email_failed",
                {"kind": email_status_key, "error": str(exc)},
            )

    return RespuestaAgendado(
        ok=True,
        booking_id=booking_id,
        estado=booking_status,
        mensaje=config["booking"]["success_message"],
        employee_id=employee_row["id"],
        employee_name=employee_row["name"],
        provider_name=provider_result.provider_name,
        provider_booking_id=provider_result.provider_booking_id,
        provider_booking_url=provider_result.provider_booking_url,
        manage_url=_build_booking_manage_url(manage_token, request),
    )


@app.get("/servicios/{cliente_id}")
async def servicios(cliente_id: str, request: Request, employee_id: str = "") -> Dict[str, List[Dict[str, str]]]:
    _assert_valid_client_id(cliente_id)
    _enforce_allowed_origin(request, cliente_id)
    return {"servicios": _public_services_for_booking(cliente_id, employee_id)}


async def _process_chat_message(
    *,
    cliente_id: str,
    message: str,
    session_id: str,
    request: Request,
    origin_override: str = "",
    user_agent_override: str = "",
) -> RespuestaChat:
    commercial_intent = _detect_commercial_intent(message)
    _ensure_chat_session_record(
        session_id,
        cliente_id,
        request,
        origin_override=origin_override,
        user_agent_override=user_agent_override,
    )
    _record_chat_message(
        session_id=session_id,
        cliente_id=cliente_id,
        role="user",
        content=message,
        intent=commercial_intent,
    )
    client_config = _get_client_config(cliente_id)
    booking_enabled = bool(client_config["booking"]["enabled"])
    if booking_enabled and _message_requests_booking_form(message):
        booking_response = RespuestaChat(
            respuesta="Te muestro el formulario de solicitud de cita para que puedas elegir servicio, fecha y hora.",
            mostrar_formulario=True,
            session_id=session_id,
        )
        _record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=booking_response.respuesta,
            intent=commercial_intent,
        )
        return booking_response

    session = _get_or_create_session(session_id, cliente_id)
    with state_lock:
        session.last_seen = time.time()
        session.message_count += 1

    if session.message_count > MAX_MESSAGES_PER_SESSION:
        limit_response = RespuestaChat(
            respuesta="Has alcanzado el limite temporal de mensajes. Si quieres, puedo derivarte al equipo humano.",
            mostrar_formulario=booking_enabled,
            session_id=session_id,
        )
        _record_chat_message(
            session_id=session_id,
            cliente_id=cliente_id,
            role="assistant",
            content=limit_response.respuesta,
            intent=commercial_intent,
        )
        return limit_response

    response = session.engine.chat(_build_intent_enhanced_message(message, commercial_intent))
    raw_text = response.response.strip()
    mostrar_formulario = BOOKING_SENTINEL in raw_text
    clean_text = raw_text.replace(BOOKING_SENTINEL, "").strip()
    if booking_enabled and not mostrar_formulario and _message_requests_booking_form(message):
        mostrar_formulario = True
        if not clean_text:
            clean_text = "Te muestro el formulario de solicitud de cita para continuar."

    logger.info(
        "Chat %s [%s] %s",
        cliente_id,
        session_id,
        message[:120],
    )

    chat_response = RespuestaChat(
        respuesta=clean_text or "No tengo una respuesta valida en este momento.",
        mostrar_formulario=mostrar_formulario and booking_enabled,
        session_id=session_id,
    )
    _record_chat_message(
        session_id=session_id,
        cliente_id=cliente_id,
        role="assistant",
        content=chat_response.respuesta,
        intent=commercial_intent,
    )
    return chat_response


def _whatsapp_env_value(env_name: str, fallback: str = "") -> str:
    return os.getenv(str(env_name or "").strip(), "").strip() if env_name else fallback.strip()


def _whatsapp_phone_client_map() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for item in WHATSAPP_PHONE_CLIENT_MAP.split(","):
        if ":" not in item:
            continue
        phone_number_id, cliente_id = item.split(":", 1)
        phone_number_id = phone_number_id.strip()
        cliente_id = cliente_id.strip()
        if phone_number_id and cliente_id:
            mapping[phone_number_id] = cliente_id
    with state_lock:
        for cliente_id, config in CONFIG_CLIENTES.items():
            whatsapp_cfg = config.get("whatsapp", {})
            phone_number_id = str(whatsapp_cfg.get("phone_number_id", "")).strip()
            if whatsapp_cfg.get("enabled") and phone_number_id:
                mapping[phone_number_id] = cliente_id
    return mapping


def _resolve_whatsapp_client_id(phone_number_id: str, forced_cliente_id: str = "") -> str:
    if forced_cliente_id:
        _assert_valid_client_id(forced_cliente_id)
        config = _get_client_config(forced_cliente_id)
        if not config.get("whatsapp", {}).get("enabled", False):
            raise HTTPException(status_code=404, detail="WhatsApp no esta activo para este cliente.")
        return forced_cliente_id

    mapping = _whatsapp_phone_client_map()
    cliente_id = mapping.get(str(phone_number_id or "").strip()) or WHATSAPP_DEFAULT_CLIENT_ID
    if not cliente_id:
        raise HTTPException(status_code=404, detail="No se pudo asociar este numero de WhatsApp a un cliente.")
    _assert_valid_client_id(cliente_id)
    config = _get_client_config(cliente_id)
    if not config.get("whatsapp", {}).get("enabled", False):
        raise HTTPException(status_code=404, detail="WhatsApp no esta activo para este cliente.")
    return cliente_id


def _whatsapp_verify_token_for_client(cliente_id: str = "") -> str:
    if cliente_id:
        config = _get_client_config(cliente_id)
        configured_env = str(config.get("whatsapp", {}).get("verify_token_env", "")).strip()
        configured_token = _whatsapp_env_value(configured_env)
        if configured_token:
            return configured_token
    return WHATSAPP_VERIFY_TOKEN


def _whatsapp_access_token_for_client(cliente_id: str) -> str:
    config = _get_client_config(cliente_id)
    configured_env = str(config.get("whatsapp", {}).get("access_token_env", "")).strip()
    return _whatsapp_env_value(configured_env, WHATSAPP_ACCESS_TOKEN)


def _whatsapp_session_id(cliente_id: str, from_number: str) -> str:
    digest = hashlib.sha256(f"{cliente_id}:{from_number}".encode("utf-8")).hexdigest()
    return f"wa_{digest[:40]}"


def _whatsapp_public_booking_text(cliente_id: str, request: Request) -> str:
    config = _get_client_config(cliente_id)
    first_origin = next((origin for origin in config.get("allowed_origins", []) if origin), "")
    base_url = first_origin or _preferred_public_base_url(request)
    if not base_url:
        return "Para completar la cita, dime el servicio, dia y hora que prefieres y el equipo humano lo revisara."
    return f"Para completar la cita con formulario, entra aqui: {base_url.rstrip('/')}"


def _whatsapp_chunks(text: str, *, max_length: int = 3500) -> List[str]:
    cleaned = _sanitize_text(text, allow_multiline=True)
    if not cleaned:
        return ["Ahora mismo no tengo una respuesta valida."]
    chunks: List[str] = []
    while cleaned:
        if len(cleaned) <= max_length:
            chunks.append(cleaned)
            break
        split_at = cleaned.rfind("\n", 0, max_length)
        if split_at < 800:
            split_at = cleaned.rfind(" ", 0, max_length)
        if split_at < 800:
            split_at = max_length
        chunks.append(cleaned[:split_at].strip())
        cleaned = cleaned[split_at:].strip()
    return chunks


def _mark_whatsapp_message_if_new(
    *,
    message_id: str,
    cliente_id: str,
    phone_number_id: str,
    from_number: str,
) -> bool:
    cleaned_message_id = _sanitize_text(message_id)[:160]
    if not cleaned_message_id:
        return True
    with _get_db_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM whatsapp_inbound_messages WHERE id = ?",
            (cleaned_message_id,),
        ).fetchone()
        if existing:
            return False
        connection.execute(
            """
            INSERT INTO whatsapp_inbound_messages (id, cliente_id, phone_number_id, from_number, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                cleaned_message_id,
                cliente_id,
                _sanitize_text(phone_number_id)[:120],
                _sanitize_text(from_number)[:80],
                _utc_now_iso(),
            ),
        )
        connection.commit()
        return True


def _verify_whatsapp_signature(raw_body: bytes, signature_header: str) -> None:
    if not WHATSAPP_APP_SECRET:
        return
    expected = "sha256=" + hmac.new(
        WHATSAPP_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not signature_header or not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=403, detail="Firma de WhatsApp invalida.")


async def _send_whatsapp_text(
    *,
    cliente_id: str,
    phone_number_id: str,
    to_number: str,
    text: str,
) -> bool:
    access_token = _whatsapp_access_token_for_client(cliente_id)
    if not access_token:
        logger.warning("WhatsApp sin token configurado para %s; respuesta no enviada.", cliente_id)
        return False

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    delivered = True
    async with httpx.AsyncClient(timeout=20) as client:
        for chunk in _whatsapp_chunks(text):
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_number,
                "type": "text",
                "text": {"preview_url": True, "body": chunk},
            }
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 300:
                delivered = False
                logger.error(
                    "Error enviando WhatsApp a %s (%s): %s",
                    cliente_id,
                    response.status_code,
                    response.text[:500],
                )
    return delivered


async def _handle_whatsapp_webhook(
    request: Request,
    *,
    forced_cliente_id: str = "",
) -> WhatsAppWebhookStatus:
    raw_body = await request.body()
    _verify_whatsapp_signature(raw_body, request.headers.get("x-hub-signature-256", ""))
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Payload de WhatsApp invalido.") from exc

    processed = 0
    entries = payload.get("entry", []) if isinstance(payload, dict) else []
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {}) if isinstance(change, dict) else {}
            metadata = value.get("metadata", {}) if isinstance(value, dict) else {}
            phone_number_id = str(metadata.get("phone_number_id", "")).strip()
            messages = value.get("messages", []) if isinstance(value, dict) else []
            if not messages:
                continue
            cliente_id = _resolve_whatsapp_client_id(phone_number_id, forced_cliente_id)
            for message_payload in messages:
                from_number = str(message_payload.get("from", "")).strip()
                message_id = str(message_payload.get("id", "")).strip()
                if not from_number:
                    continue
                if not _mark_whatsapp_message_if_new(
                    message_id=message_id,
                    cliente_id=cliente_id,
                    phone_number_id=phone_number_id,
                    from_number=from_number,
                ):
                    continue

                message_type = str(message_payload.get("type", "")).strip()
                if message_type == "text":
                    incoming_text = str(message_payload.get("text", {}).get("body", "")).strip()
                else:
                    incoming_text = (
                        "El usuario ha enviado un mensaje que no es texto. "
                        "Responde de forma breve indicando que puede ayudarte si escribe su consulta."
                    )

                try:
                    chat_response = await _process_chat_message(
                        cliente_id=cliente_id,
                        message=incoming_text,
                        session_id=_whatsapp_session_id(cliente_id, from_number),
                        request=request,
                        origin_override=f"whatsapp:{from_number}",
                        user_agent_override="WhatsApp Cloud API",
                    )
                    response_text = chat_response.respuesta
                    if chat_response.mostrar_formulario:
                        response_text = f"{response_text}\n\n{_whatsapp_public_booking_text(cliente_id, request)}"
                    await _send_whatsapp_text(
                        cliente_id=cliente_id,
                        phone_number_id=phone_number_id,
                        to_number=from_number,
                        text=response_text,
                    )
                    processed += 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Error procesando WhatsApp para %s: %s", cliente_id, exc)
                    await _send_whatsapp_text(
                        cliente_id=cliente_id,
                        phone_number_id=phone_number_id,
                        to_number=from_number,
                        text="Ahora mismo no he podido procesar tu mensaje. Intentalo de nuevo en unos minutos.",
                    )
    return WhatsAppWebhookStatus(status="ok", processed=processed)


def _verify_whatsapp_webhook_challenge(request: Request, cliente_id: str = "") -> Response:
    params = request.query_params
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")
    expected_token = _whatsapp_verify_token_for_client(cliente_id)
    if mode == "subscribe" and expected_token and hmac.compare_digest(token, expected_token):
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verificacion de WhatsApp rechazada.")


@app.get("/whatsapp/webhook", include_in_schema=False)
async def whatsapp_webhook_verify(request: Request) -> Response:
    return _verify_whatsapp_webhook_challenge(request)


@app.post("/whatsapp/webhook", response_model=WhatsAppWebhookStatus)
async def whatsapp_webhook(request: Request) -> WhatsAppWebhookStatus:
    return await _handle_whatsapp_webhook(request)


@app.get("/whatsapp/webhook/{cliente_id}", include_in_schema=False)
async def whatsapp_client_webhook_verify(cliente_id: str, request: Request) -> Response:
    _assert_valid_client_id(cliente_id)
    return _verify_whatsapp_webhook_challenge(request, cliente_id)


@app.post("/whatsapp/webhook/{cliente_id}", response_model=WhatsAppWebhookStatus)
async def whatsapp_client_webhook(cliente_id: str, request: Request) -> WhatsAppWebhookStatus:
    _assert_valid_client_id(cliente_id)
    return await _handle_whatsapp_webhook(request, forced_cliente_id=cliente_id)


@app.post("/admin/reindex/{cliente_id}", dependencies=[Depends(_require_admin_token)])
async def reindexar(cliente_id: str) -> Dict[str, str]:
    _assert_valid_client_id(cliente_id)
    _get_client_config(cliente_id)

    _invalidate_client_runtime(cliente_id)
    cargar_indice(cliente_id)
    return {"status": "ok", "mensaje": f"Indice reindexado para {cliente_id}"}


@app.get("/admin/stats", dependencies=[Depends(_require_admin_token)])
async def estadisticas() -> Dict[str, Any]:
    _cleanup_sessions(force=True)
    _auto_complete_past_bookings()
    with _get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT cliente_id, COUNT(*) AS total
            FROM bookings
            GROUP BY cliente_id
            ORDER BY cliente_id
            """
        ).fetchall()
        status_rows = connection.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM bookings
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()

    with state_lock:
        sesiones_activas = len(sesiones)
        indices_cargados = sorted(indices.keys())

    return {
        "version": app.version,
        "clientes_configurados": len(CONFIG_CLIENTES),
        "sesiones_activas": sesiones_activas,
        "indices_cargados": indices_cargados,
        "bookings_por_cliente": {row["cliente_id"]: row["total"] for row in rows},
        "bookings_por_estado": {row["status"]: row["total"] for row in status_rows},
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
