"""Configuracion y constantes de entorno de Vantelia (refactor F3).

Lee .env y expone rutas, limites, planes y plantillas por defecto. Se importa
al inicio de api.py; los valores se leen del entorno EN TIEMPO DE IMPORT (las
fixtures de tests reimportan api con env aislado y el purge de api.py fuerza
la relectura de este modulo).
"""
from __future__ import annotations

import logging
import os
import re
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Raiz del repo (este archivo vive en backend/).
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("VANTELIA_DATA_DIR", str(BASE_DIR / "data"))).resolve()
STORAGE_DIR = Path(os.getenv("VANTELIA_STORAGE_DIR", str(BASE_DIR / "storage"))).resolve()
WIDGET_DIR = BASE_DIR / "widget"
ADMIN_UI_DIR = BASE_DIR / "admin_ui"
ACCESS_UI_DIR = BASE_DIR / "access_ui"
ONBOARDING_UI_DIR = BASE_DIR / "onboarding_ui"
APP_UI_DIR = BASE_DIR / "app_ui"
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
AVAILABLE_CHAT_MODELS_BOOT = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"]
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Europe/Madrid")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
MAX_MESSAGES_PER_SESSION = int(os.getenv("MAX_MESSAGES_PER_SESSION", "40"))
CHAT_RATE_LIMIT = int(os.getenv("CHAT_RATE_LIMIT_PER_MINUTE", "30"))
BOOKING_RATE_LIMIT = int(os.getenv("BOOKING_RATE_LIMIT_PER_MINUTE", "10"))
MAX_BOOKING_ADVANCE_DAYS = int(os.getenv("MAX_BOOKING_ADVANCE_DAYS", "60"))
RATE_LIMIT_WINDOW_SECONDS = 60
# Cap por defecto para listados paginados de citas (tamano de pagina del portal).
PORTAL_BOOKINGS_PAGE_CAP = 100
# Cap ampliado para consultas acotadas por un rango de fechas corto (vista
# calendario): la ventana esta limitada de forma natural, asi que devolvemos
# todas las citas del rango en lugar de truncar a una pagina y dejar los ultimos
# dias del mes en blanco.
PORTAL_BOOKINGS_RANGE_CAP = int(os.getenv("PORTAL_BOOKINGS_RANGE_CAP", "5000"))
# Span maximo (en dias) que se considera "rango acotado" y obtiene el cap ampliado.
PORTAL_BOOKINGS_RANGE_MAX_SPAN_DAYS = 92

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
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_DEFAULT_PHONE_NUMBER = os.getenv("TWILIO_DEFAULT_PHONE_NUMBER", "").strip()
# Remitente SMS opcional. En ES el numero de voz no suele poder enviar SMS:
# usa aqui un numero SMS-capable o un Alphanumeric Sender ID (ej. "Vantelia").
# Vacio => usa el numero de voz del cliente / TWILIO_DEFAULT_PHONE_NUMBER.
TWILIO_SMS_SENDER = os.getenv("TWILIO_SMS_SENDER", "").strip()
try:
    VOICE_MAX_DURATION_SECONDS = int(os.getenv("VOICE_MAX_DURATION_SECONDS", "300"))
except ValueError:
    VOICE_MAX_DURATION_SECONDS = 300
VOICE_OPENAI_VOICE = os.getenv("VOICE_OPENAI_VOICE", "alloy").strip() or "alloy"
# Modelo Realtime GA por defecto: el mini es mas barato y sobra para recepcionista
# (citas, horarios, FAQs). Override por cliente con voice.realtime_model.
# (La API beta `gpt-4o-*-realtime-preview` fue retirada en mayo 2026.)
VOICE_REALTIME_MODEL = (
    os.getenv("VOICE_REALTIME_MODEL", "gpt-realtime-mini").strip()
    or "gpt-realtime-mini"
)
# Demo de voz en el navegador (llamada simulada, sin telefono): tope de duracion
# y rate limit por IP para acotar el gasto de minutos Realtime en una pagina publica.
try:
    DEMO_VOICE_MAX_SECONDS = int(os.getenv("DEMO_VOICE_MAX_SECONDS", "120"))
except ValueError:
    DEMO_VOICE_MAX_SECONDS = 120
try:
    DEMO_VOICE_RATE_LIMIT = int(os.getenv("DEMO_VOICE_RATE_LIMIT_PER_MINUTE", "3"))
except ValueError:
    DEMO_VOICE_RATE_LIMIT = 3
# El test del panel lo lanza el propio cliente autenticado sobre su bot: limite mas
# holgado que el demo publico para no cortar al probar varias veces seguidas.
try:
    APP_VOICE_RATE_LIMIT = int(os.getenv("APP_VOICE_RATE_LIMIT_PER_MINUTE", "10"))
except ValueError:
    APP_VOICE_RATE_LIMIT = 10
RAW_EXTRA_CORS_ORIGINS = os.getenv("EXTRA_CORS_ORIGINS", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
DEFAULT_VANTELIA_FROM_EMAIL = "info@vantelia.es"
DEFAULT_VANTELIA_SUPPORT_EMAIL = "soporte@vantelia.es"


def _email_or_fallback(value: str, fallback: str) -> str:
    parsed = parseaddr(str(value or "").strip())[1].lower()
    return parsed or fallback


SMTP_FROM_EMAIL = _email_or_fallback(
    os.getenv("SMTP_FROM_EMAIL", "").strip(),
    DEFAULT_VANTELIA_FROM_EMAIL,
)
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Vantelia").strip()
SMTP_REPLY_TO = _email_or_fallback(
    os.getenv("SMTP_REPLY_TO", "").strip(),
    DEFAULT_VANTELIA_SUPPORT_EMAIL,
)
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").strip().lower() in {"1", "true", "yes", "on"}
EMAIL_SEND_PROVIDER = os.getenv("EMAIL_SEND_PROVIDER", "auto").strip().lower() or "auto"
GMAIL_TOKEN_ENCRYPTION_KEY = os.getenv("GMAIL_TOKEN_ENCRYPTION_KEY", "").strip()
REMINDER_24H_HOURS = int(os.getenv("REMINDER_24H_HOURS", "24"))
REMINDER_2H_HOURS = int(os.getenv("REMINDER_2H_HOURS", "2"))
REMINDER_RUN_INTERVAL_MINUTES = int(os.getenv("REMINDER_RUN_INTERVAL_MINUTES", "30"))
BOOKING_AUTO_COMPLETE_HOURS = int(os.getenv("BOOKING_AUTO_COMPLETE_HOURS", "24"))
MANAGE_TOKEN_VALID_DAYS_AFTER_DATE = int(os.getenv("MANAGE_TOKEN_VALID_DAYS_AFTER_DATE", "30"))
PASSWORD_RESET_TOKEN_HOURS = int(os.getenv("PASSWORD_RESET_TOKEN_HOURS", "2"))
PASSWORD_RESET_RESEND_SECONDS = int(os.getenv("PASSWORD_RESET_RESEND_SECONDS", "60"))
PORTAL_COOKIE_NAME = os.getenv("PORTAL_COOKIE_NAME", "vantelia_portal_session").strip() or "vantelia_portal_session"
ADMIN_RETURN_COOKIE_NAME = (
    os.getenv("ADMIN_RETURN_COOKIE_NAME", "vantelia_admin_session").strip()
    or "vantelia_admin_session"
)
PORTAL_COOKIE_DOMAIN = os.getenv("PORTAL_COOKIE_DOMAIN", "").strip()
PORTAL_SESSION_HOURS = int(os.getenv("PORTAL_SESSION_HOURS", "72"))
PORTAL_ADMIN_EMAIL = os.getenv("PORTAL_ADMIN_EMAIL", "").strip().lower()
PORTAL_ADMIN_PASSWORD = os.getenv("PORTAL_ADMIN_PASSWORD", "").strip()
PORTAL_ADMIN_NAME = os.getenv("PORTAL_ADMIN_NAME", "Administrador Vantelia").strip()
MARKETING_SITE_URL = os.getenv("MARKETING_SITE_URL", "https://vantelia.es").strip()
PORTAL_SUPPORT_EMAIL = (
    _email_or_fallback(os.getenv("PORTAL_SUPPORT_EMAIL", "").strip(), SMTP_REPLY_TO)
)
CONSULTA_NOTIFICATION_EMAIL = (
    parseaddr(os.getenv("CONSULTA_NOTIFICATION_EMAIL", "").strip())[1]
    or "vanteliadigital@gmail.com"
)

# ─── Self-serve signup + Google OAuth (Vantelia 2.0) ──────────────────
SIGNUP_ENABLED = os.getenv("SIGNUP_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
GOOGLE_GMAIL_REDIRECT_URI = os.getenv("GOOGLE_GMAIL_REDIRECT_URI", "").strip()
GOOGLE_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GOOGLE_GMAIL_SCOPES = "openid email profile https://www.googleapis.com/auth/gmail.send"
GOOGLE_OAUTH_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_GMAIL_CLIENT_ID = os.getenv("GOOGLE_GMAIL_CLIENT_ID", "").strip()
GOOGLE_GMAIL_CLIENT_SECRET = os.getenv("GOOGLE_GMAIL_CLIENT_SECRET", "").strip()
GOOGLE_GMAIL_REDIRECT_URL = os.getenv("GOOGLE_GMAIL_REDIRECT_URL", "").strip()
OAUTH_TOKEN_ENCRYPTION_KEY = os.getenv("OAUTH_TOKEN_ENCRYPTION_KEY", "").strip()
GOOGLE_GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DEFAULT_FREE_QUOTA = int(os.getenv("DEFAULT_FREE_QUOTA", "50"))
ONBOARDING_MAX_PAGES_DEFAULT = int(os.getenv("ONBOARDING_MAX_PAGES", "12"))

# Starter questions: 3 base fijas + hasta 5 extras escritos por el cliente (cap 8 total).
BASE_STARTERS: List[Dict[str, Any]] = [
    {"text": "Agendar cita", "needs_booking": True},
    {"text": "Información servicios", "needs_booking": False},
    {"text": "Preguntas frecuentes", "needs_booking": False},
]
MAX_EXTRA_STARTERS = 5
MAX_TOTAL_STARTERS = 8
BASE_STARTERS_LOWER = {b["text"].strip().lower() for b in BASE_STARTERS}


def _strip_base_from_extras(items: Any) -> List[str]:
    """Drop entries matching BASE_STARTERS (case-insensitive) and dedupe."""
    if not isinstance(items, (list, tuple)):
        return []
    seen = set(BASE_STARTERS_LOWER)
    out: List[str] = []
    for raw in items:
        if not isinstance(raw, (str, int, float)):
            continue
        text = str(raw).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= MAX_EXTRA_STARTERS:
            break
    return out


def _resolve_widget_starters(config: Dict[str, Any], *, booking_enabled: Optional[bool] = None) -> List[str]:
    """Fuse BASE_STARTERS with cliente's manual extras.

    Returns base first (filtered by booking_enabled), then dedup-extras.
    Cap MAX_TOTAL_STARTERS. Single source of truth for what widget renders
    and what the IA expects in its system prompt.
    """
    if booking_enabled is None:
        booking_cfg = config.get("booking") if isinstance(config, dict) else None
        booking_enabled = bool(booking_cfg.get("enabled")) if isinstance(booking_cfg, dict) else False

    base = [b["text"] for b in BASE_STARTERS if booking_enabled or not b["needs_booking"]]
    extras = _strip_base_from_extras(config.get("starter_questions"))

    seen = {t.lower() for t in base}
    fused = list(base)
    for e in extras:
        key = e.lower()
        if key in seen:
            continue
        seen.add(key)
        fused.append(e)
        if len(fused) >= MAX_TOTAL_STARTERS:
            break
    return fused

# ─── Planes y suscripciones ───────────────────────────────────────────
PLAN_DEFAULT = "free"

# Aliases de planes legacy → self-serve actuales
_PLAN_LEGACY_ALIASES: Dict[str, str] = {
    "web": "starter", "esencial": "free",
    "whatsapp": "pro", "pro": "pro",
    "completo": "business", "empresa": "business",
}


def _normalize_plan_slug(plan: str) -> str:
    p = (plan or "").strip().lower()
    return _PLAN_LEGACY_ALIASES.get(p, p)


# Stripe
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_CONNECT_WEBHOOK_SECRET = os.getenv("STRIPE_CONNECT_WEBHOOK_SECRET", "").strip()
STRIPE_CONNECT_API_VERSION = os.getenv("STRIPE_CONNECT_API_VERSION", "2026-05-27.preview").strip()
STRIPE_CONNECT_BASE_URL = "https://api.stripe.com/v2/core"
STRIPE_CONNECT_COUNTRY = os.getenv("STRIPE_CONNECT_COUNTRY", "es").strip().lower()
BOOKING_PAYMENT_EXPIRY_MINUTES = min(24 * 60, max(30, int(os.getenv("BOOKING_PAYMENT_EXPIRY_MINUTES", "30"))))
STRIPE_CONNECT_CLIENT_ID = os.getenv("STRIPE_CONNECT_CLIENT_ID", "").strip()
STRIPE_CONNECT_RETURN_URL = os.getenv("STRIPE_CONNECT_RETURN_URL", "").strip()
STRIPE_CONNECT_REFRESH_URL = os.getenv("STRIPE_CONNECT_REFRESH_URL", "").strip()

# Self-serve plans (Vantelia 2.0)
STRIPE_PRICE_STARTER = os.getenv("STRIPE_PRICE_STARTER", "").strip()
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "").strip()
STRIPE_PRICE_BUSINESS = os.getenv("STRIPE_PRICE_BUSINESS", "").strip()
STRIPE_PRICE_STARTER_ANNUAL = os.getenv("STRIPE_PRICE_STARTER_ANNUAL", "").strip()
STRIPE_PRICE_PRO_ANNUAL = os.getenv("STRIPE_PRICE_PRO_ANNUAL", "").strip()
STRIPE_PRICE_BUSINESS_ANNUAL = os.getenv("STRIPE_PRICE_BUSINESS_ANNUAL", "").strip()

# Plan definitions for self-serve.
# Features: chat=always, booking=free+, whatsapp=business, livechat=pro+, custom_branding=starter+.
SELF_SERVE_PLANS: Dict[str, Dict[str, Any]] = {
    "free": {
        "slug": "free",
        "label": "Free",
        "price_monthly_eur": 0,
        "price_annual_eur": 0,
        "messages_quota": int(os.getenv("PLAN_FREE_QUOTA", "50")),
        "features": ["chat", "booking"],
        "stripe_price_monthly": "",
        "stripe_price_annual": "",
    },
    "starter": {
        "slug": "starter",
        "label": "Starter",
        "price_monthly_eur": int(os.getenv("PLAN_STARTER_PRICE_EUR", "19")),
        "price_annual_eur": int(os.getenv("PLAN_STARTER_PRICE_ANNUAL_EUR", "190")),
        "messages_quota": int(os.getenv("PLAN_STARTER_QUOTA", "1000")),
        "features": ["chat", "uploads", "branding", "leads_export", "booking"],
        "stripe_price_monthly": STRIPE_PRICE_STARTER,
        "stripe_price_annual": STRIPE_PRICE_STARTER_ANNUAL,
    },
    "pro": {
        "slug": "pro",
        "label": "Pro",
        "price_monthly_eur": int(os.getenv("PLAN_PRO_PRICE_EUR", "49")),
        "price_annual_eur": int(os.getenv("PLAN_PRO_PRICE_ANNUAL_EUR", "490")),
        "messages_quota": int(os.getenv("PLAN_PRO_QUOTA", "5000")),
        "features": ["chat", "uploads", "branding", "leads_export", "booking", "qa", "tune", "whatsapp"],
        "stripe_price_monthly": STRIPE_PRICE_PRO,
        "stripe_price_annual": STRIPE_PRICE_PRO_ANNUAL,
    },
    "business": {
        "slug": "business",
        "label": "Business",
        "price_monthly_eur": int(os.getenv("PLAN_BUSINESS_PRICE_EUR", "149")),
        "price_annual_eur": int(os.getenv("PLAN_BUSINESS_PRICE_ANNUAL_EUR", "1490")),
        "messages_quota": int(os.getenv("PLAN_BUSINESS_QUOTA", "25000")),
        "features": ["chat", "uploads", "branding", "leads_export", "booking", "qa", "tune", "whatsapp", "voice"],
        "stripe_price_monthly": STRIPE_PRICE_BUSINESS,
        "stripe_price_annual": STRIPE_PRICE_BUSINESS_ANNUAL,
    },
}


PLAN_VALID: set = set(SELF_SERVE_PLANS.keys())

# Límites operativos por plan (fusiona con SELF_SERVE_PLANS)
PLAN_LIMITS: Dict[str, Dict[str, Any]] = {
    "free": {
        "label": "Free",
        "monthly_conversations": int(os.getenv("PLAN_FREE_QUOTA", "50")),
        "monthly_bookings": 10,
        "max_professionals": 1,
        "max_users": 1,
        "max_extra_documents": 0,
        "branding_customization": False,
        "whatsapp_enabled": False,
        "voice_enabled": False,
        "voice_minutes": 0,
        "sms_enabled": False,
        "csv_export": False,
        "multi_branch": False,
        "crm_integration": False,
        "show_powered_by": True,
        "price_eur": 0,
    },
    "starter": {
        "label": "Starter",
        "monthly_conversations": int(os.getenv("PLAN_STARTER_QUOTA", "1000")),
        "monthly_bookings": 100,
        "max_professionals": 1,
        "max_users": 1,
        "max_extra_documents": 5,
        "branding_customization": True,
        "whatsapp_enabled": False,
        "voice_enabled": False,
        "voice_minutes": 0,
        "sms_enabled": False,
        "csv_export": True,
        "multi_branch": False,
        "crm_integration": False,
        "show_powered_by": False,
        "price_eur": int(os.getenv("PLAN_STARTER_PRICE_EUR", "19")),
    },
    "pro": {
        "label": "Pro",
        "monthly_conversations": int(os.getenv("PLAN_PRO_QUOTA", "5000")),
        "monthly_bookings": 500,
        "max_professionals": 3,
        "max_users": 2,
        "max_extra_documents": 20,
        "branding_customization": True,
        "whatsapp_enabled": True,
        "voice_enabled": False,
        "voice_minutes": 0,
        "sms_enabled": False,
        "csv_export": True,
        "multi_branch": False,
        "crm_integration": False,
        "show_powered_by": False,
        "price_eur": int(os.getenv("PLAN_PRO_PRICE_EUR", "49")),
    },
    "business": {
        "label": "Business",
        "monthly_conversations": int(os.getenv("PLAN_BUSINESS_QUOTA", "25000")),
        "monthly_bookings": None,
        "max_professionals": None,
        "max_users": None,
        "max_extra_documents": None,
        "branding_customization": True,
        "whatsapp_enabled": True,
        "voice_enabled": True,
        "voice_minutes": int(os.getenv("PLAN_BUSINESS_VOICE_MINUTES", "300")),
        "sms_enabled": True,
        "csv_export": True,
        "multi_branch": False,
        "crm_integration": False,
        "show_powered_by": False,
        "price_eur": int(os.getenv("PLAN_BUSINESS_PRICE_EUR", "149")),
    },
}


def _self_serve_plan(slug: str) -> Dict[str, Any]:
    return SELF_SERVE_PLANS.get((slug or "").lower(), SELF_SERVE_PLANS["free"])

DEFAULT_MESSAGE_TEMPLATES = {
    "confirmed": (
        "Tu cita ha quedado confirmada. Debajo tienes los detalles y tu enlace personal para gestionarla "
        "si necesitas hacer algun cambio."
    ),
    "reminder_24h": (
        "Te recordamos que mañana tienes una cita programada. Si necesitas revisarla o ajustarla, "
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

DEFAULT_MESSAGE_TEMPLATE_CHANNELS = {
    "confirmed": {"email": True, "whatsapp": False, "sms": False},
    "reminder_24h": {"email": True, "whatsapp": False, "sms": False},
    "reminder_2h": {"email": True, "whatsapp": False, "sms": False},
    "cancelled": {"email": True, "whatsapp": False, "sms": False},
    "rescheduled": {"email": True, "whatsapp": False, "sms": False},
}

MESSAGE_KIND_ALIASES = {
    "confirmacion": "confirmed",
    "confirmación": "confirmed",
    "recordatorio_24h": "reminder_24h",
    "recordatorio_2h": "reminder_2h",
    "cancelada": "cancelled",
    "reprogramada": "rescheduled",
}
