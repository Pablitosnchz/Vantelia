from __future__ import annotations

import asyncio
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
from html import escape
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlparse

import httpx
from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
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
DATA_DIR = BASE_DIR / "data"
STORAGE_DIR = BASE_DIR / "storage"
PROVIDER_SECRETS_DIR = STORAGE_DIR / "provider_secrets"
WIDGET_DIR = BASE_DIR / "widget"
ADMIN_UI_DIR = BASE_DIR / "admin_ui"
ACCESS_UI_DIR = BASE_DIR / "access_ui"
PORTAL_UI_DIR = BASE_DIR / "portal_ui"
BRAND_DIR = BASE_DIR / "brand_assets"
CONFIG_PATH = BASE_DIR / "config.json"
DB_PATH = STORAGE_DIR / "vantelia.db"

load_dotenv(BASE_DIR / ".env")

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
CALENDLY_API_TOKEN = os.getenv("CALENDLY_API_TOKEN", "").strip()
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
BOOKING_AUTO_COMPLETE_HOURS = int(os.getenv("BOOKING_AUTO_COMPLETE_HOURS", "6"))
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
        "booking": {
            "enabled": bool(booking.get("enabled", False)),
            "timezone": _sanitize_text(booking.get("timezone", DEFAULT_TIMEZONE)) or DEFAULT_TIMEZONE,
            "slot_minutes": int(booking.get("slot_minutes", 30)),
            "day_start": _sanitize_text(booking.get("day_start", "09:00")) or "09:00",
            "day_end": _sanitize_text(booking.get("day_end", "18:00")) or "18:00",
            "closed_weekdays": booking.get("closed_weekdays", [0]),
            "provider": _sanitize_text(booking.get("provider", "internal")) or "internal",
            "webhook_env": _sanitize_text(booking.get("webhook_env", "")),
            "webhook_url": _normalize_optional_http_url(booking.get("webhook_url", "")),
            "calendly_user_env": _sanitize_text(booking.get("calendly_user_env", "")),
            "calendly_event_type_env": _sanitize_text(booking.get("calendly_event_type_env", "")),
            "calendly_location_kind": _sanitize_text(booking.get("calendly_location_kind", "")),
            "calendly_location_value": _sanitize_text(
                booking.get("calendly_location_value", ""),
                allow_multiline=True,
            ),
            "google_calendar_id": _sanitize_text(booking.get("google_calendar_id", "")),
            "google_calendar_id_env": _sanitize_text(booking.get("google_calendar_id_env", "")),
            "google_service_account_path": _sanitize_text(
                booking.get("google_service_account_path", "")
            ),
            "google_service_account_env": _sanitize_text(booking.get("google_service_account_env", "")),
            "success_message": _sanitize_text(
                booking.get(
                    "success_message",
                    "Tu solicitud de cita ha quedado registrada correctamente.",
                ),
                allow_multiline=True,
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
        "booking": {
            "enabled": bool(config.get("booking", {}).get("enabled", False)),
            "timezone": config.get("booking", {}).get("timezone", DEFAULT_TIMEZONE),
            "slot_minutes": int(config.get("booking", {}).get("slot_minutes", 30)),
            "day_start": config.get("booking", {}).get("day_start", "09:00"),
            "day_end": config.get("booking", {}).get("day_end", "18:00"),
            "closed_weekdays": list(config.get("booking", {}).get("closed_weekdays", [0])),
            "provider": config.get("booking", {}).get("provider", "internal"),
            "webhook_env": config.get("booking", {}).get("webhook_env", ""),
            "webhook_url": config.get("booking", {}).get("webhook_url", ""),
            "calendly_user_env": config.get("booking", {}).get("calendly_user_env", ""),
            "calendly_event_type_env": config.get("booking", {}).get("calendly_event_type_env", ""),
            "calendly_location_kind": config.get("booking", {}).get("calendly_location_kind", ""),
            "calendly_location_value": config.get("booking", {}).get("calendly_location_value", ""),
            "google_calendar_id": config.get("booking", {}).get("google_calendar_id", ""),
            "google_calendar_id_env": config.get("booking", {}).get("google_calendar_id_env", ""),
            "google_service_account_path": config.get("booking", {}).get(
                "google_service_account_path", ""
            ),
            "google_service_account_env": config.get("booking", {}).get("google_service_account_env", ""),
            "success_message": config.get("booking", {}).get(
                "success_message",
                "Tu solicitud de cita ha quedado registrada correctamente.",
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
    PROVIDER_SECRETS_DIR.mkdir(exist_ok=True)
    WIDGET_DIR.mkdir(exist_ok=True)
    ADMIN_UI_DIR.mkdir(exist_ok=True)
    ACCESS_UI_DIR.mkdir(exist_ok=True)
    PORTAL_UI_DIR.mkdir(exist_ok=True)


def _init_database() -> None:
    _ensure_runtime_directories()
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY,
                cliente_id TEXT NOT NULL,
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
            ON bookings(cliente_id, booking_date, booking_time, status)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_unique_slot
            ON bookings(cliente_id, booking_date, booking_time)
            WHERE status IN ('confirmed', 'pending_review')
            """
        )
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


def _get_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def _validate_single_client_runtime(cliente_id: str, config: Dict[str, Any]) -> None:
    booking_cfg = config["booking"]
    provider = booking_cfg.get("provider", "internal")
    if not re.match(r"^#[0-9A-Fa-f]{6}$", str(config.get("color", ""))):
        raise RuntimeError(f"color invalido para {cliente_id}. Usa formato #RRGGBB.")
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
        if provider not in {"internal", "calendly", "google_calendar"}:
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
    fecha: str = Field(min_length=10, max_length=10)
    hora: str = Field(min_length=5, max_length=5)
    notas: str = Field(default="", max_length=500)


class RespuestaChat(BaseModel):
    respuesta: str
    mostrar_formulario: bool
    session_id: str


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
    slots: List[SlotDisponibilidad]


class RespuestaAgendado(BaseModel):
    ok: bool
    booking_id: str
    estado: str
    mensaje: str
    provider_name: str = "internal"
    provider_booking_id: str = ""
    provider_booking_url: str = ""
    manage_url: str = ""


class BookingDetailPublic(BaseModel):
    booking_id: str
    cliente_id: str
    empresa: str
    nombre: str
    email: str
    telefono: str
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


class BookingActionResponse(BaseModel):
    ok: bool
    booking_id: str
    estado: str
    mensaje: str
    manage_url: str = ""
    provider_booking_url: str = ""


class BookingReschedulePayload(BaseModel):
    fecha: str = Field(min_length=10, max_length=10)
    hora: str = Field(min_length=5, max_length=5)


class AdminBookingResumen(BaseModel):
    booking_id: str
    cliente_id: str
    empresa: str
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


class PortalBookingSummary(BaseModel):
    booking_id: str
    empresa: str
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


class PortalDashboardResponse(BaseModel):
    user: AuthUserPublic
    stats: Dict[str, Any]
    bookings_upcoming: List[PortalBookingSummary]


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
    allowed_origins: List[str]
    has_info_file: bool


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
        booking_enabled=bool(config.get("booking", {}).get("enabled", False)),
        booking_timezone=config.get("booking", {}).get("timezone", DEFAULT_TIMEZONE),
        booking_slot_minutes=int(config.get("booking", {}).get("slot_minutes", 30)),
        booking_day_start=config.get("booking", {}).get("day_start", "09:00"),
        booking_day_end=config.get("booking", {}).get("day_end", "18:00"),
        booking_closed_weekdays=list(config.get("booking", {}).get("closed_weekdays", [6])),
        booking_provider=config.get("booking", {}).get("provider", "internal"),
        booking_webhook_env=config.get("booking", {}).get("webhook_env", ""),
        booking_webhook_url=config.get("booking", {}).get("webhook_url", ""),
        booking_calendly_user_env=config.get("booking", {}).get("calendly_user_env", ""),
        booking_calendly_event_type_env=config.get("booking", {}).get("calendly_event_type_env", ""),
        booking_calendly_location_kind=config.get("booking", {}).get("calendly_location_kind", ""),
        booking_calendly_location_value=config.get("booking", {}).get("calendly_location_value", ""),
        booking_google_calendar_id=config.get("booking", {}).get("google_calendar_id", ""),
        booking_google_calendar_id_env=config.get("booking", {}).get("google_calendar_id_env", ""),
        booking_google_service_account_path=config.get("booking", {}).get(
            "google_service_account_path", ""
        ),
        booking_google_service_account_env=config.get("booking", {}).get(
            "google_service_account_env", ""
        ),
        booking_google_service_account_json="",
        booking_success_message=config.get("booking", {}).get(
            "success_message",
            "Tu solicitud de cita ha quedado registrada correctamente.",
        ),
        info_txt=info_txt,
        reindex_after_save=True,
    )


def _config_from_admin_payload(cliente_id: str, payload: AdminClientePayload) -> Dict[str, Any]:
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
            "booking": {
                "enabled": payload.booking_enabled,
                "timezone": payload.booking_timezone,
                "slot_minutes": payload.booking_slot_minutes,
                "day_start": payload.booking_day_start,
                "day_end": payload.booking_day_end,
                "closed_weekdays": payload.booking_closed_weekdays,
                "provider": payload.booking_provider,
                "webhook_env": payload.booking_webhook_env,
                "webhook_url": payload.booking_webhook_url,
                "calendly_user_env": payload.booking_calendly_user_env,
                "calendly_event_type_env": payload.booking_calendly_event_type_env,
                "calendly_location_kind": payload.booking_calendly_location_kind,
                "calendly_location_value": payload.booking_calendly_location_value,
                "google_calendar_id": payload.booking_google_calendar_id,
                "google_calendar_id_env": payload.booking_google_calendar_id_env,
                "google_service_account_path": payload.booking_google_service_account_path,
                "google_service_account_env": payload.booking_google_service_account_env,
                "success_message": payload.booking_success_message,
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


def _provider_secret_file(cliente_id: str, slug: str) -> Path:
    filename = f"{cliente_id}_{slug}.json"
    path = PROVIDER_SECRETS_DIR / filename
    _ensure_path_within(PROVIDER_SECRETS_DIR, path)
    return path


def _persist_google_service_account_secret(cliente_id: str, raw_json: str) -> str:
    if not raw_json.strip():
        return ""

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError("El JSON de la service account de Google no es valido.") from exc

    if not isinstance(parsed, dict) or parsed.get("type") != "service_account":
        raise RuntimeError("El JSON pegado no parece una service account valida de Google.")

    target_path = _provider_secret_file(cliente_id, "google_service_account")
    target_path.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    return str(target_path)


def _prepare_admin_payload(cliente_id: str, payload: AdminClientePayload) -> AdminClientePayload:
    updates: Dict[str, Any] = {}

    if payload.booking_google_service_account_json.strip():
        updates["booking_google_service_account_path"] = _persist_google_service_account_secret(
            cliente_id, payload.booking_google_service_account_json
        )

    if updates:
        return payload.model_copy(update=updates)

    return payload


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
            <span class="eyebrow">Demo privada de chatbox para cliente</span>
            <h1>{nombre}</h1>
            <p>{bienvenida}</p>
          </div>
        </div>
        <div class="hero-actions">
          <button type="button" id="openChatBtn">Abrir demo del chat</button>
          <a href="{escape(assets["api_base_url"])}/dashboard" target="_blank" rel="noreferrer">Abrir panel admin</a>
        </div>
      </section>

      <section class="grid">
        <article class="card">
          <h2>Como usar esta demo</h2>
          <p>
            Esta pagina sirve para validar el comportamiento del asistente antes de instalarlo en la web final.
            El chat se abre abajo a la derecha y ya esta conectado al cerebro de <strong>{nombre}</strong>.
          </p>
          <div class="list">
            <span>1. Prueba preguntas reales sobre servicios, precios, horarios y proceso comercial.</span>
            <span>2. Comprueba si deriva correctamente a contacto humano o a solicitud de cita.</span>
            <span>3. Si detectas respuestas flojas, vuelve al panel, edita el cerebro y reindexa.</span>
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
    return _sanitize_text(config.get("booking", {}).get("provider", "internal")) or "internal"


def _env_value(env_name: str) -> str:
    env_key = _sanitize_text(env_name)
    if not env_key:
        return ""
    return os.getenv(env_key, "").strip()


def _resolve_direct_or_env(value: str, env_name: str) -> str:
    direct_value = str(value or "").strip()
    if direct_value:
        return direct_value
    return _env_value(env_name)


def _load_json_secret_from_source(raw_value: str) -> Dict[str, Any]:
    if not raw_value:
        raise RuntimeError("No se ha encontrado ninguna credencial JSON configurada.")

    candidate_path = Path(raw_value)
    if candidate_path.exists():
        return json.loads(candidate_path.read_text(encoding="utf-8"))

    return json.loads(raw_value)


def _google_calendar_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"

    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message", "")).strip()
        errors = error.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                reason = str(first.get("reason", "")).strip()
                if reason and message:
                    return f"{reason}: {message}"
        if message:
            return message

    return response.text.strip() or f"HTTP {response.status_code}"


def _booking_email_subject(
    status_key: str,
    company_name: str,
    booking_row: sqlite3.Row,
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
    booking_row: sqlite3.Row,
    company_name: str,
    status_key: str,
    manage_url: str,
    contact_email: str,
    contact_phone: str,
) -> Tuple[str, str]:
    service_name = booking_row["servicio"] or "Consulta"
    when_text = _booking_datetime_display(booking_row)
    manage_line = f"\nGestiona tu cita aqui: {manage_url}\n" if manage_url else ""
    manage_html = (
        f'<p><a href="{escape(manage_url)}">Gestionar cita</a></p>' if manage_url else ""
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
        "confirmed": "Tu cita ha quedado confirmada correctamente.",
        "cancelled": "Tu cita ha sido cancelada.",
        "rescheduled": "Tu cita ha sido reprogramada correctamente.",
        "reminder_24h": "Te recordamos que manana tienes una cita programada.",
        "reminder_2h": "Te recordamos que tu cita empieza en breve.",
    }
    intro = intro_map.get(status_key, intro_map["confirmed"])

    text_body = (
        f"{intro}\n\n"
        f"Empresa: {company_name}\n"
        f"Servicio: {service_name}\n"
        f"Fecha y hora: {when_text}\n"
        f"Zona horaria: {booking_row['timezone']}\n"
        f"{manage_line}"
    )
    if contact_text:
        text_body += f"\nContacto:\n{contact_text}\n"

    html_body = (
        f"<p>{escape(intro)}</p>"
        f"<ul>"
        f"<li><strong>Empresa:</strong> {escape(company_name)}</li>"
        f"<li><strong>Servicio:</strong> {escape(service_name)}</li>"
        f"<li><strong>Fecha y hora:</strong> {escape(when_text)}</li>"
        f"<li><strong>Zona horaria:</strong> {escape(booking_row['timezone'])}</li>"
        f"</ul>"
        f"{manage_html}"
    )
    if contact_html:
        html_body += f"<p>Si necesitas ayuda, puedes escribirnos por:</p><ul>{contact_html}</ul>"

    return text_body.strip(), html_body


def _send_booking_email(booking_row: sqlite3.Row, status_key: str, request: Optional[Request] = None) -> None:
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
    )
    _send_email_message(booking_row["email"], subject, text_body, html_body)


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


def _booking_start_end(cliente_id: str, fecha: str, hora: str) -> Tuple[datetime, datetime]:
    config = _get_client_config(cliente_id)
    tzinfo = ZoneInfo(config["booking"]["timezone"])
    start_local = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=tzinfo)
    end_local = start_local + timedelta(minutes=int(config["booking"]["slot_minutes"]))
    return start_local, end_local


def _generate_manage_token() -> str:
    return f"mg_{secrets.token_urlsafe(24)}"


def _build_booking_manage_url(
    manage_token: str,
    request: Optional[Request] = None,
) -> str:
    if not manage_token:
        return ""
    base_url = _preferred_public_base_url(request)
    if not base_url:
        return ""
    return f"{base_url}/booking/manage/{manage_token}"


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


def _booking_row_manage_url(row: sqlite3.Row, request: Optional[Request] = None) -> str:
    return _build_booking_manage_url(row["manage_token"], request)


def _serialize_booking_row(row: sqlite3.Row, request: Optional[Request] = None) -> Dict[str, Any]:
    config = _get_client_config(row["cliente_id"])
    return {
        "booking_id": row["id"],
        "cliente_id": row["cliente_id"],
        "empresa": config["nombre"],
        "nombre": row["nombre"],
        "email": row["email"],
        "telefono": row["telefono"] or "",
        "servicio": row["servicio"] or "",
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


def _calendly_headers() -> Dict[str, str]:
    if not CALENDLY_API_TOKEN:
        raise RuntimeError("CALENDLY_API_TOKEN no esta configurado en el backend.")
    return {
        "Authorization": f"Bearer {CALENDLY_API_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _google_calendar_access_token(
    service_account_path: str,
    service_account_env: str,
) -> str:
    raw_value = _resolve_direct_or_env(service_account_path, service_account_env)
    if not raw_value:
        raise RuntimeError(
            "Falta configurar la service account de Google. Puedes pegar el JSON en el panel admin o indicar una variable de entorno."
        )

    service_account_info = _load_json_secret_from_source(raw_value)
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    credentials.refresh(GoogleAuthRequest())
    if not credentials.token:
        raise RuntimeError("No se ha podido obtener un access token de Google Calendar.")
    return credentials.token


async def _calendly_available_slots(cliente_id: str, fecha: str) -> List[str]:
    config = _get_client_config(cliente_id)
    booking_cfg = config["booking"]
    event_type_uri = _env_value(booking_cfg.get("calendly_event_type_env", ""))
    if not event_type_uri:
        raise RuntimeError(
            f"Falta configurar el event type de Calendly para {cliente_id}."
        )

    start_local = datetime.strptime(fecha, "%Y-%m-%d").replace(
        tzinfo=ZoneInfo(booking_cfg["timezone"])
    )
    end_local = start_local + timedelta(days=1)

    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(
            "https://api.calendly.com/event_type_available_times",
            headers=_calendly_headers(),
            params={
                "event_type": event_type_uri,
                "start_time": _to_utc_iso(start_local),
                "end_time": _to_utc_iso(end_local),
            },
        )
        response.raise_for_status()

    collection = response.json().get("collection", [])
    slots: Set[str] = set()
    tzinfo = ZoneInfo(booking_cfg["timezone"])
    for item in collection:
        raw_start = item.get("start_time")
        if not raw_start:
            continue
        start_dt = datetime.fromisoformat(raw_start.replace("Z", "+00:00")).astimezone(tzinfo)
        if start_dt.strftime("%Y-%m-%d") == fecha:
            slots.add(start_dt.strftime("%H:%M"))

    return sorted(slots)


async def _create_calendly_booking(
    cliente_id: str,
    booking_payload: Dict[str, Any],
) -> ProviderBookingResult:
    config = _get_client_config(cliente_id)
    booking_cfg = config["booking"]
    event_type_uri = _env_value(booking_cfg.get("calendly_event_type_env", ""))
    if not event_type_uri:
        raise RuntimeError(
            f"Falta configurar el event type de Calendly para {cliente_id}."
        )

    start_local, _ = _booking_start_end(
        cliente_id,
        booking_payload["fecha"],
        booking_payload["hora"],
    )
    request_body: Dict[str, Any] = {
        "event_type": event_type_uri,
        "start_time": _to_utc_iso(start_local),
        "invitee": {
            "name": booking_payload["nombre"],
            "email": booking_payload["email"],
            "timezone": booking_cfg["timezone"],
        },
        "tracking": {
            "utm_source": "vantelia_widget",
            "utm_campaign": cliente_id,
        },
    }

    if booking_cfg.get("calendly_location_kind"):
        request_body["location"] = {
            "kind": booking_cfg["calendly_location_kind"],
        }
        if booking_cfg.get("calendly_location_value"):
            request_body["location"]["location"] = booking_cfg["calendly_location_value"]

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "https://api.calendly.com/invitees",
            headers=_calendly_headers(),
            json=request_body,
        )
        response.raise_for_status()
        payload = response.json()

    event_uri = payload.get("event", "")
    cancel_url = payload.get("cancel_url", "") or payload.get("reschedule_url", "")
    provider_booking_id = event_uri.rsplit("/", 1)[-1] if event_uri else ""
    return ProviderBookingResult(
        success=True,
        status=payload.get("status", "confirmed"),
        provider_name="calendly",
        provider_booking_id=provider_booking_id,
        provider_booking_url=cancel_url,
        message="Reserva confirmada en Calendly.",
    )


async def _create_google_calendar_booking(
    cliente_id: str,
    booking_payload: Dict[str, Any],
) -> ProviderBookingResult:
    config = _get_client_config(cliente_id)
    booking_cfg = config["booking"]
    calendar_id = _resolve_direct_or_env(
        booking_cfg.get("google_calendar_id", ""),
        booking_cfg.get("google_calendar_id_env", ""),
    )
    if not calendar_id:
        raise RuntimeError(
            f"Falta configurar el calendar ID de Google para {cliente_id}. Puedes indicarlo directamente en el panel admin."
        )

    token = _google_calendar_access_token(
        booking_cfg.get("google_service_account_path", ""),
        booking_cfg.get("google_service_account_env", ""),
    )
    start_local, end_local = _booking_start_end(
        cliente_id,
        booking_payload["fecha"],
        booking_payload["hora"],
    )

    description_parts = [
        f"Reserva creada desde Vantelia para {config['nombre']}.",
        f"Cliente: {booking_payload['nombre']}",
        f"Email: {booking_payload['email']}",
    ]
    if booking_payload.get("telefono"):
        description_parts.append(f"Telefono: {booking_payload['telefono']}")
    if booking_payload.get("servicio"):
        description_parts.append(f"Servicio: {booking_payload['servicio']}")
    if booking_payload.get("notas"):
        description_parts.append(f"Notas:\n{booking_payload['notas']}")

    summary = booking_payload.get("servicio") or f"Cita con {booking_payload['nombre']}"
    event_body = {
        "summary": f"{config['nombre']} - {summary}",
        "description": "\n\n".join(description_parts),
        "start": {
            "dateTime": start_local.isoformat(),
            "timeZone": booking_cfg["timezone"],
        },
        "end": {
            "dateTime": end_local.isoformat(),
            "timeZone": booking_cfg["timezone"],
        },
        "extendedProperties": {
            "private": {
                "source": "vantelia_widget",
                "cliente_id": cliente_id,
            }
        },
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=event_body,
        )
        if response.is_error:
            detail = _google_calendar_error_detail(response)
            raise RuntimeError(
                f"Google Calendar ha rechazado la cita ({response.status_code}). Detalle: {detail}"
            )
        payload = response.json()

    return ProviderBookingResult(
        success=True,
        status=payload.get("status", "confirmed"),
        provider_name="google_calendar",
        provider_booking_id=payload.get("id", ""),
        provider_booking_url=payload.get("htmlLink", ""),
        message="Reserva confirmada en Google Calendar.",
    )


async def _cancel_google_calendar_booking(cliente_id: str, booking_row: sqlite3.Row) -> None:
    config = _get_client_config(cliente_id)
    booking_cfg = config["booking"]
    calendar_id = _resolve_direct_or_env(
        booking_cfg.get("google_calendar_id", ""),
        booking_cfg.get("google_calendar_id_env", ""),
    )
    event_id = booking_row["provider_booking_id"]
    if not calendar_id or not event_id:
        return

    token = _google_calendar_access_token(
        booking_cfg.get("google_service_account_path", ""),
        booking_cfg.get("google_service_account_env", ""),
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.delete(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        if response.status_code not in {200, 204, 404, 410} and response.is_error:
            detail = _google_calendar_error_detail(response)
            raise RuntimeError(
                f"Google Calendar no ha podido cancelar la cita ({response.status_code}). Detalle: {detail}"
            )


async def _reschedule_google_calendar_booking(
    cliente_id: str,
    booking_row: sqlite3.Row,
    *,
    fecha: str,
    hora: str,
) -> ProviderBookingResult:
    config = _get_client_config(cliente_id)
    booking_cfg = config["booking"]
    calendar_id = _resolve_direct_or_env(
        booking_cfg.get("google_calendar_id", ""),
        booking_cfg.get("google_calendar_id_env", ""),
    )
    event_id = booking_row["provider_booking_id"]
    if not calendar_id or not event_id:
        raise RuntimeError("No se ha encontrado el evento de Google Calendar que hay que reprogramar.")

    token = _google_calendar_access_token(
        booking_cfg.get("google_service_account_path", ""),
        booking_cfg.get("google_service_account_env", ""),
    )
    start_local, end_local = _booking_start_end(cliente_id, fecha, hora)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.patch(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "start": {
                    "dateTime": start_local.isoformat(),
                    "timeZone": booking_cfg["timezone"],
                },
                "end": {
                    "dateTime": end_local.isoformat(),
                    "timeZone": booking_cfg["timezone"],
                },
            },
        )
        if response.is_error:
            detail = _google_calendar_error_detail(response)
            raise RuntimeError(
                f"Google Calendar no ha podido reprogramar la cita ({response.status_code}). Detalle: {detail}"
            )
        payload = response.json()

    return ProviderBookingResult(
        success=True,
        status=payload.get("status", "confirmed"),
        provider_name="google_calendar",
        provider_booking_id=payload.get("id", event_id),
        provider_booking_url=payload.get("htmlLink", booking_row["provider_booking_url"] or ""),
        message="Reserva reprogramada en Google Calendar.",
    )


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


def _build_slots_for_day(cliente_id: str, fecha: str) -> List[str]:
    config = _get_client_config(cliente_id)
    booking_cfg = config["booking"]

    if not booking_cfg["enabled"]:
        return []

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


async def _available_slots_for_day(cliente_id: str, fecha: str) -> List[str]:
    config = _get_client_config(cliente_id)
    provider = _get_booking_provider(config)

    if provider == "calendly":
        return await _calendly_available_slots(cliente_id, fecha)

    return _build_slots_for_day(cliente_id, fecha)


def _booked_slots(cliente_id: str, fecha: str, *, exclude_booking_id: str = "") -> Set[str]:
    with _get_db_connection() as connection:
        if exclude_booking_id:
            rows = connection.execute(
                """
                SELECT booking_time
                FROM bookings
                WHERE cliente_id = ?
                  AND booking_date = ?
                  AND status IN ('confirmed', 'pending_review')
                  AND id <> ?
                """,
                (cliente_id, fecha, exclude_booking_id),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT booking_time
                FROM bookings
                WHERE cliente_id = ?
                  AND booking_date = ?
                  AND status IN ('confirmed', 'pending_review')
                """,
                (cliente_id, fecha),
            ).fetchall()

    occupied = {row["booking_time"] for row in rows}

    if CALENDLY_API_TOKEN:
        occupied.update(_booked_slots_from_calendly(cliente_id, fecha))

    return occupied


def _booked_slots_from_calendly(cliente_id: str, fecha: str) -> Set[str]:
    config = _get_client_config(cliente_id)
    booking_cfg = config["booking"]
    calendly_user_env = booking_cfg.get("calendly_user_env", "")
    calendly_user_uri = os.getenv(calendly_user_env, "").strip() if calendly_user_env else ""

    if not calendly_user_uri:
        return set()

    timezone_name = booking_cfg["timezone"]
    tzinfo = ZoneInfo(timezone_name)
    start_of_day = datetime.strptime(fecha, "%Y-%m-%d").replace(tzinfo=tzinfo)
    end_of_day = start_of_day + timedelta(days=1)

    occupied: Set[str] = set()

    try:
        response = httpx.get(
            "https://api.calendly.com/scheduled_events",
            headers={"Authorization": f"Bearer {CALENDLY_API_TOKEN}"},
            params={
                "user": calendly_user_uri,
                "min_start_time": start_of_day.astimezone(ZoneInfo("UTC")).isoformat(),
                "max_start_time": end_of_day.astimezone(ZoneInfo("UTC")).isoformat(),
                "status": "active",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        for event in response.json().get("collection", []):
            start_time = event.get("start_time")
            if not start_time:
                continue
            event_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")).astimezone(tzinfo)
            occupied.add(event_dt.strftime("%H:%M"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Calendly no disponible para %s: %s", cliente_id, exc)

    return occupied


async def _booking_slot_available(cliente_id: str, fecha: str, hora: str) -> bool:
    return hora in await _available_slots_for_day(cliente_id, fecha) and hora not in _booked_slots(
        cliente_id, fecha
    )


async def _booking_slot_available_for_reschedule(
    cliente_id: str,
    fecha: str,
    hora: str,
    *,
    exclude_booking_id: str,
) -> bool:
    return hora in await _available_slots_for_day(cliente_id, fecha) and hora not in _booked_slots(
        cliente_id,
        fecha,
        exclude_booking_id=exclude_booking_id,
    )


async def _cancel_provider_booking(booking_row: sqlite3.Row) -> None:
    provider_name = booking_row["provider_name"]
    if provider_name == "google_calendar":
        await _cancel_google_calendar_booking(booking_row["cliente_id"], booking_row)
        return
    if provider_name == "calendly":
        raise RuntimeError(
            "Las citas de Calendly deben cancelarse desde la URL del proveedor o desde Calendly."
        )


async def _reschedule_provider_booking(
    booking_row: sqlite3.Row,
    *,
    fecha: str,
    hora: str,
) -> ProviderBookingResult:
    provider_name = booking_row["provider_name"]
    if provider_name == "google_calendar":
        return await _reschedule_google_calendar_booking(
            booking_row["cliente_id"],
            booking_row,
            fecha=fecha,
            hora=hora,
        )
    if provider_name == "calendly":
        raise RuntimeError(
            "Las citas de Calendly deben reprogramarse desde la URL del proveedor o desde Calendly."
        )

    return ProviderBookingResult(
        success=True,
        status="confirmed",
        provider_name=provider_name or "internal",
        provider_booking_id=booking_row["provider_booking_id"] or "",
        provider_booking_url=booking_row["provider_booking_url"] or "",
        message="Reserva reprogramada internamente.",
    )


def _store_booking(record: Dict[str, Any]) -> None:
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO bookings (
                id, cliente_id, nombre, email, telefono, servicio,
                booking_date, booking_time, notas, status,
                provider_name, provider_status, provider_booking_id, provider_booking_url,
                manage_token, timezone, start_at, end_at,
                confirmed_at, cancelled_at, rescheduled_at, rescheduled_from_booking_id,
                confirmation_email_sent_at, reminder_24h_sent_at, reminder_2h_sent_at,
                customer_email_status, customer_email_last_error,
                source, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["cliente_id"],
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
        nombre=data["nombre"],
        email=data["email"],
        telefono=data["telefono"],
        servicio=data["servicio"],
        fecha=data["fecha"],
        hora=data["hora"],
        timezone=data["timezone"],
        estado=data["estado"],
        provider_name=data["provider_name"],
        provider_booking_url=data["provider_booking_url"],
        manage_url=data["manage_url"],
        contact_email=data["contact_email"],
        contact_phone=data["contact_phone"],
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
        nombre=data["nombre"],
        email=data["email"],
        servicio=data["servicio"],
        fecha=data["fecha"],
        hora=data["hora"],
        timezone=data["timezone"],
        estado=data["estado"],
        provider_name=data["provider_name"],
        provider_booking_url=data["provider_booking_url"],
        manage_url=data["manage_url"],
        contact_email=data["contact_email"],
        contact_phone=data["contact_phone"],
        start_at=data["start_at"],
        can_cancel=can_edit,
        can_reschedule=can_edit,
    )


def _list_booking_rows(
    *,
    cliente_id: str = "",
    status_filter: str = "",
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
    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter)
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
        sql += " ORDER BY CASE WHEN start_at = '' THEN created_at ELSE start_at END ASC"
    elif scope == "history":
        sql += " ORDER BY CASE WHEN start_at = '' THEN created_at ELSE start_at END DESC"
    else:
        sql += " ORDER BY created_at DESC"
    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with _get_db_connection() as connection:
        total = connection.execute(count_sql, tuple(params[:-2] if params else [])).fetchone()[0]
        rows = connection.execute(sql, tuple(params)).fetchall()
        return rows, total


def _portal_stats_for_user(user: sqlite3.Row) -> Dict[str, Any]:
    with _get_db_connection() as connection:
        if user["role"] == "admin":
            total_bookings = connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
            pending = connection.execute(
                "SELECT COUNT(*) FROM bookings WHERE status = 'pending_review'"
            ).fetchone()[0]
            total_users = connection.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]
            client_users = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'client' AND is_active = 1"
            ).fetchone()[0]
            return {
                "total_bookings": total_bookings,
                "pending_review": pending,
                "active_users": total_users,
                "client_users": client_users,
            }

        total_bookings = connection.execute(
            "SELECT COUNT(*) FROM bookings WHERE cliente_id = ?",
            (user["cliente_id"],),
        ).fetchone()[0]
        upcoming = connection.execute(
            """
            SELECT COUNT(*)
            FROM bookings
            WHERE cliente_id = ?
              AND status IN ('confirmed', 'pending_review')
              AND (start_at = '' OR start_at >= ?)
            """,
            (user["cliente_id"], _utc_now_iso()),
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
            (user["cliente_id"], _utc_now_iso()),
        ).fetchone()[0]
        return {
            "total_bookings": total_bookings,
            "upcoming": upcoming,
            "history": history,
            "empresa": _get_client_config(user["cliente_id"])["nombre"] if user["cliente_id"] else "",
        }


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


def _booking_manage_page(booking: BookingDetailPublic) -> str:
    serialized = json.dumps(booking.model_dump(), ensure_ascii=False)
    logo_url = escape(_brand_asset_public_path("Logo_1_sin_resplandor.png"))
    favicon_url = escape(_brand_asset_public_path("favicon.png"))
    fondo_url = escape(_brand_asset_public_path("Fondo_Web.png"))
    provider_note = ""
    if booking.provider_name == "calendly" and booking.provider_booking_url:
        provider_note = (
            f'<p>Esta cita se gestiona en Calendly. '
            f'<a href="{escape(booking.provider_booking_url)}" target="_blank" rel="noreferrer">Abrir gestion externa</a></p>'
        )
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Gestionar cita | Vantelia</title>
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
    .wrap {{ max-width:820px; margin:0 auto; }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:24px; padding:28px; box-shadow:var(--shadow); backdrop-filter: blur(18px); }}
    .hero {{ display:flex; align-items:center; gap:16px; margin-bottom:18px; }}
    .hero img {{ width:68px; height:68px; object-fit:contain; filter: drop-shadow(0 0 22px rgba(0,177,217,.3)); }}
    h1 {{ margin:0 0 8px; font-size:30px; font-family:var(--font-title); }}
    .muted {{ color:var(--soft); }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:20px 0; }}
    .field {{ background:rgba(8,20,48,.92); border:1px solid rgba(184,192,204,.14); border-radius:16px; padding:12px; }}
    .field strong {{ display:block; font-size:12px; text-transform:uppercase; color:#8dcfe0; margin-bottom:6px; }}
    .actions {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:20px; }}
    button {{ border:none; border-radius:999px; padding:12px 18px; font-weight:700; cursor:pointer; font-family:var(--font-body); }}
    .primary {{ background:linear-gradient(135deg, var(--accent), #008bad); color:#fff; }}
    .secondary {{ background:rgba(184,192,204,.12); color:var(--ink); }}
    .danger {{ background:var(--danger); color:#fff; }}
    .panel {{ margin-top:24px; padding-top:20px; border-top:1px solid rgba(184,192,204,.14); }}
    .status {{ margin-top:16px; min-height:22px; font-weight:600; }}
    input {{ width:100%; box-sizing:border-box; border:1px solid rgba(184,192,204,.16); border-radius:14px; padding:12px; font-family:var(--font-body); background:rgba(8,20,48,.92); color:var(--ink); }}
    @media (max-width: 720px) {{ .grid {{ grid-template-columns:1fr; }} body {{ padding:16px; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="hero">
        <img src="{logo_url}" alt="Vantelia" />
        <div>
          <h1>Gestionar cita</h1>
          <div class="muted">{escape(booking.empresa)}</div>
        </div>
      </div>
      <div class="grid">
        <div class="field"><strong>Nombre</strong>{escape(booking.nombre)}</div>
        <div class="field"><strong>Email</strong>{escape(booking.email)}</div>
        <div class="field"><strong>Servicio</strong>{escape(booking.servicio or "Consulta")}</div>
        <div class="field"><strong>Estado</strong>{escape(booking.estado)}</div>
        <div class="field"><strong>Fecha</strong>{escape(booking.fecha)}</div>
        <div class="field"><strong>Hora</strong>{escape(booking.hora)} ({escape(booking.timezone)})</div>
      </div>
      {provider_note}
      <div class="panel" id="reschedule-panel">
        <strong>Cambiar cita</strong>
        <div class="grid">
          <label>Fecha<input id="reschedule-date" type="date" /></label>
          <label>Hora<input id="reschedule-time" type="time" step="1800" /></label>
        </div>
        <div class="actions">
          <button class="primary" id="reschedule-btn" type="button">Guardar nuevo horario</button>
          <button class="danger" id="cancel-btn" type="button">Cancelar cita</button>
        </div>
      </div>
      <div class="status" id="status"></div>
    </div>
  </div>
  <script>
    const BOOKING = {serialized};
    const statusEl = document.getElementById("status");
    const reschedulePanel = document.getElementById("reschedule-panel");
    if (BOOKING.provider_name === "calendly" || BOOKING.estado === "cancelled") {{
      reschedulePanel.style.display = "none";
    }}
    document.getElementById("reschedule-date").value = BOOKING.fecha;
    document.getElementById("reschedule-time").value = BOOKING.hora;

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

    document.getElementById("reschedule-btn")?.addEventListener("click", async () => {{
      const fecha = document.getElementById("reschedule-date").value;
      const hora = document.getElementById("reschedule-time").value;
      if (!fecha || !hora) {{
        statusEl.textContent = "Elige una fecha y una hora.";
        return;
      }}
      try {{ await action(window.location.pathname + "/reschedule", {{ fecha, hora }}); }}
      catch (error) {{ statusEl.textContent = error.message; }}
    }});
  </script>
</body>
</html>"""


async def _send_booking_email_by_kind(
    booking_row: sqlite3.Row,
    kind: str,
    request: Optional[Request] = None,
    *,
    sent_column: str = "",
) -> None:
    _send_booking_email(booking_row, kind, request)
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
        {"kind": kind},
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
            WHERE status = 'confirmed'
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


async def _run_booking_reminders(request: Optional[Request] = None) -> AdminReminderRunResult:
    now_utc = _utc_now()
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
    config = _get_client_config(cliente_id)
    provider = _get_booking_provider(config)

    if provider == "calendly":
        return await _create_calendly_booking(cliente_id, booking_payload)

    if provider == "google_calendar":
        return await _create_google_calendar_booking(cliente_id, booking_payload)

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

        service_id = re.sub(r"[^a-z0-9_]+", "_", nombre.lower()).strip("_")
        if service_id:
            servicios.append({"id": service_id, "nombre": nombre})

    unique: Dict[str, Dict[str, str]] = {}
    for servicio in servicios:
        unique[servicio["id"]] = servicio

    return list(unique.values())


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


@app.get("/auth/dashboard", response_model=PortalDashboardResponse)
async def auth_dashboard_data(
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalDashboardResponse:
    cliente_id = "" if user["role"] == "admin" else user["cliente_id"]
    bookings, _ = _list_booking_rows(cliente_id=cliente_id, limit=6, scope="upcoming")
    return PortalDashboardResponse(
        user=_serialize_auth_user(user),
        stats=_portal_stats_for_user(user),
        bookings_upcoming=[_portal_booking_summary_from_row(row, request) for row in bookings],
    )


@app.get("/auth/bookings", response_model=PortalBookingsResponse)
async def auth_bookings(
    request: Request,
    estado: str = "",
    scope: str = "all",
    limit: int = 20,
    offset: int = 0,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalBookingsResponse:
    cliente_id = "" if user["role"] == "admin" else user["cliente_id"]
    normalized_scope = scope.strip().lower() or "all"
    if normalized_scope not in {"all", "upcoming", "history"}:
        raise HTTPException(status_code=400, detail="Scope invalido.")
    rows, total = _list_booking_rows(
        cliente_id=cliente_id,
        status_filter=estado.strip(),
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


@app.post("/auth/bookings/{booking_id}/cancel", response_model=BookingActionResponse)
async def auth_cancel_booking(
    booking_id: str,
    request: Request,
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
        {"source": "portal", "role": user["role"], "user_id": user["id"]},
    )
    refreshed = _load_booking_or_404(booking_id)
    try:
        await _send_booking_email_by_kind(refreshed, "cancelled", request)
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
    if booking_row["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="No se puede reprogramar una cita cancelada.")
    if not await _booking_slot_available_for_reschedule(
        booking_row["cliente_id"],
        data.fecha,
        data.hora,
        exclude_booking_id=booking_row["id"],
    ):
        raise HTTPException(status_code=409, detail="Ese horario ya no esta disponible. Elige otro tramo.")

    provider_result = await _reschedule_provider_booking(booking_row, fecha=data.fecha, hora=data.hora)
    start_local, end_local = _booking_start_end(booking_row["cliente_id"], data.fecha, data.hora)
    _update_booking_record(
        booking_id,
        booking_date=data.fecha,
        booking_time=data.hora,
        start_at=_to_utc_iso(start_local),
        end_at=_to_utc_iso(end_local),
        rescheduled_at=_utc_now_iso(),
        status="confirmed",
        provider_status=provider_result.status,
        provider_booking_id=provider_result.provider_booking_id,
        provider_booking_url=provider_result.provider_booking_url,
    )
    _record_booking_audit(
        booking_id,
        booking_row["cliente_id"],
        "booking_rescheduled",
        {"source": "portal", "role": user["role"], "user_id": user["id"], "fecha": data.fecha, "hora": data.hora},
    )
    refreshed = _load_booking_or_404(booking_id)
    try:
        await _send_booking_email_by_kind(refreshed, "rescheduled", request)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se ha podido enviar el email de reprogramacion %s: %s", refreshed["id"], exc)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado="confirmed",
        mensaje="La cita ha sido reprogramada correctamente.",
        manage_url=_booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
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
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
) -> Response:
    user = _get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso")
    if user["role"] == "admin":
        return RedirectResponse("/dashboard")

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


@app.get("/health")
async def healthcheck() -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": app.version,
        "openai_configured": bool(OPENAI_API_KEY),
        "clientes_configurados": len(CONFIG_CLIENTES),
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
    summaries: List[AdminClienteResumen] = []
    for cliente_id, config in sorted(CONFIG_CLIENTES.items(), key=lambda item: item[0].lower()):
        summaries.append(
            AdminClienteResumen(
                cliente_id=cliente_id,
                nombre=config["nombre"],
                booking_enabled=bool(config["booking"]["enabled"]),
                allowed_origins=list(config.get("allowed_origins", [])),
                has_info_file=_client_info_path(cliente_id).exists(),
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
    limit: int = 100,
) -> List[AdminBookingResumen]:
    rows, _ = _list_booking_rows(
        cliente_id=cliente_id.strip(),
        status_filter=estado.strip(),
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
    if booking_row["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="No se puede reprogramar una cita cancelada.")

    if not await _booking_slot_available_for_reschedule(
        booking_row["cliente_id"],
        data.fecha,
        data.hora,
        exclude_booking_id=booking_row["id"],
    ):
        raise HTTPException(status_code=409, detail="Ese horario ya no esta disponible. Elige otro tramo.")

    provider_result = await _reschedule_provider_booking(
        booking_row,
        fecha=data.fecha,
        hora=data.hora,
    )
    start_local, end_local = _booking_start_end(booking_row["cliente_id"], data.fecha, data.hora)
    _update_booking_record(
        booking_id,
        booking_date=data.fecha,
        booking_time=data.hora,
        start_at=_to_utc_iso(start_local),
        end_at=_to_utc_iso(end_local),
        rescheduled_at=_utc_now_iso(),
        status="confirmed",
        provider_status=provider_result.status,
        provider_booking_id=provider_result.provider_booking_id,
        provider_booking_url=provider_result.provider_booking_url,
    )
    _record_booking_audit(
        booking_id,
        booking_row["cliente_id"],
        "booking_rescheduled",
        {"source": "admin", "fecha": data.fecha, "hora": data.hora},
    )
    refreshed = _load_booking_or_404(booking_id)
    try:
        await _send_booking_email_by_kind(refreshed, "rescheduled", request)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se ha podido enviar el email de reprogramacion %s: %s", refreshed["id"], exc)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado="confirmed",
        mensaje="La cita ha sido reprogramada.",
        manage_url=_booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
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
    await _send_booking_email_by_kind(booking_row, kind, request)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado=booking_row["status"],
        mensaje="Correo reenviado correctamente.",
        manage_url=_booking_row_manage_url(booking_row, request),
        provider_booking_url=booking_row["provider_booking_url"] or "",
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
    return HTMLResponse(_booking_manage_page(booking))


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
    if booking_row["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="No se puede reprogramar una cita cancelada.")
    if not await _booking_slot_available_for_reschedule(
        booking_row["cliente_id"],
        data.fecha,
        data.hora,
        exclude_booking_id=booking_row["id"],
    ):
        raise HTTPException(status_code=409, detail="Ese horario ya no esta disponible. Elige otro tramo.")

    provider_result = await _reschedule_provider_booking(
        booking_row,
        fecha=data.fecha,
        hora=data.hora,
    )
    start_local, end_local = _booking_start_end(booking_row["cliente_id"], data.fecha, data.hora)
    rescheduled_at = _utc_now_iso()
    _update_booking_record(
        booking_row["id"],
        booking_date=data.fecha,
        booking_time=data.hora,
        start_at=_to_utc_iso(start_local),
        end_at=_to_utc_iso(end_local),
        rescheduled_at=rescheduled_at,
        status="confirmed",
        provider_status=provider_result.status,
        provider_booking_id=provider_result.provider_booking_id,
        provider_booking_url=provider_result.provider_booking_url,
    )
    _record_booking_audit(
        booking_row["id"],
        booking_row["cliente_id"],
        "booking_rescheduled",
        {"source": "customer", "fecha": data.fecha, "hora": data.hora},
    )
    refreshed = _load_booking_by_token_or_404(manage_token)
    try:
        await _send_booking_email_by_kind(refreshed, "rescheduled", request)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se ha podido enviar el email de reprogramacion %s: %s", refreshed["id"], exc)
    return BookingActionResponse(
        ok=True,
        booking_id=refreshed["id"],
        estado="confirmed",
        mensaje="Tu cita ha sido reprogramada correctamente.",
        manage_url=_booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
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
    session = _get_or_create_session(session_id, data.cliente_id)
    with state_lock:
        session.last_seen = time.time()
        session.message_count += 1

    if session.message_count > MAX_MESSAGES_PER_SESSION:
        return RespuestaChat(
            respuesta="Has alcanzado el limite temporal de mensajes. Si quieres, puedo derivarte al equipo humano.",
            mostrar_formulario=_get_client_config(data.cliente_id)["booking"]["enabled"],
            session_id=session_id,
        )

    client_config = _get_client_config(data.cliente_id)
    booking_enabled = bool(client_config["booking"]["enabled"])
    if booking_enabled and _message_requests_booking_form(message):
        return RespuestaChat(
            respuesta="Te muestro el formulario de solicitud de cita para que puedas elegir servicio, fecha y hora.",
            mostrar_formulario=True,
            session_id=session_id,
        )

    try:
        response = session.engine.chat(message)
        raw_text = response.response.strip()
        mostrar_formulario = BOOKING_SENTINEL in raw_text
        clean_text = raw_text.replace(BOOKING_SENTINEL, "").strip()
        if booking_enabled and not mostrar_formulario and _message_requests_booking_form(message):
            mostrar_formulario = True
            if not clean_text:
                clean_text = "Te muestro el formulario de solicitud de cita para continuar."

        logger.info(
            "Chat %s [%s] %s",
            data.cliente_id,
            session_id,
            message[:120],
        )

        return RespuestaChat(
            respuesta=clean_text or "No tengo una respuesta valida en este momento.",
            mostrar_formulario=mostrar_formulario and booking_enabled,
            session_id=session_id,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error procesando chat de %s: %s", data.cliente_id, exc)
        raise HTTPException(status_code=500, detail="No se pudo procesar el mensaje.") from exc


@app.get("/disponibilidad", response_model=RespuestaDisponibilidad)
async def disponibilidad(cliente_id: str, fecha: str, request: Request) -> RespuestaDisponibilidad:
    _assert_valid_client_id(cliente_id)
    _enforce_allowed_origin(request, cliente_id)
    config = _get_client_config(cliente_id)

    if not config["booking"]["enabled"]:
        raise HTTPException(status_code=404, detail="La reserva online no esta habilitada para este cliente.")

    selected_day = _parse_date(fecha)
    _validate_booking_window(cliente_id, selected_day)

    try:
        slots = await _available_slots_for_day(cliente_id, fecha)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.error("No se pudo consultar disponibilidad externa de %s: %s", cliente_id, exc)
        raise HTTPException(
            status_code=502,
            detail="No se ha podido consultar la disponibilidad del proveedor de calendario.",
        ) from exc
    occupied = _booked_slots(cliente_id, fecha)

    return RespuestaDisponibilidad(
        fecha=fecha,
        timezone=config["booking"]["timezone"],
        slots=[SlotDisponibilidad(hora=hora, disponible=hora not in occupied) for hora in slots],
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

    if not await _booking_slot_available(data.cliente_id, booking_date, booking_time):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese horario ya no esta disponible. Elige otro tramo.",
        )

    booking_id = f"bk_{secrets.token_urlsafe(10)}"
    manage_token = _generate_manage_token()
    created_at = _utc_now_iso()
    provider = _get_booking_provider(config)
    start_local, end_local = _booking_start_end(data.cliente_id, booking_date, booking_time)
    booking_timezone = config["booking"]["timezone"]

    booking_payload = {
        "booking_id": booking_id,
        "cliente_id": data.cliente_id,
        "empresa": config["nombre"],
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
        booking_status = "confirmed" if delivered else "pending_review"
        provider_status = webhook_status

    record = {
        "id": booking_id,
        "cliente_id": data.cliente_id,
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
        },
    )

    booking_row = _get_booking_row_by_id(booking_id)
    if booking_row:
        email_status_key = "received" if booking_status == "pending_review" else "confirmed"
        try:
            _send_booking_email(booking_row, email_status_key, request)
            _mark_booking_email_result(
                booking_id,
                status=email_status_key,
                sent_column="confirmation_email_sent_at",
                error="",
            )
            _record_booking_audit(
                booking_id,
                data.cliente_id,
                "booking_email_sent",
                {"kind": email_status_key},
            )
            booking_row = _get_booking_row_by_id(booking_id)
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

    if provider == "internal" and not delivered:
        payload = RespuestaAgendado(
            ok=True,
            booking_id=booking_id,
            estado="pending_review",
            mensaje=(
                "La solicitud se ha guardado correctamente y nuestro equipo la revisara manualmente "
                "antes de confirmarla."
            ),
            provider_name=provider_result.provider_name,
            provider_booking_id=provider_result.provider_booking_id,
            provider_booking_url=provider_result.provider_booking_url,
            manage_url=_build_booking_manage_url(manage_token, request),
        )
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload.model_dump())

    return RespuestaAgendado(
        ok=True,
        booking_id=booking_id,
        estado="confirmed" if provider != "internal" else booking_status,
        mensaje=config["booking"]["success_message"],
        provider_name=provider_result.provider_name,
        provider_booking_id=provider_result.provider_booking_id,
        provider_booking_url=provider_result.provider_booking_url,
        manage_url=_build_booking_manage_url(manage_token, request),
    )


@app.get("/servicios/{cliente_id}")
async def servicios(cliente_id: str, request: Request) -> Dict[str, List[Dict[str, str]]]:
    _assert_valid_client_id(cliente_id)
    _enforce_allowed_origin(request, cliente_id)
    return {"servicios": _extract_services_from_info(cliente_id)}


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
