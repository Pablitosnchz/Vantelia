"""App FastAPI de Vantelia: creacion, middlewares, mounts y ciclo de vida (refactor F3).

Importar este modulo inicializa el runtime (directorios, esquema SQLite,
empleados por defecto, sync de clientes, validacion y llama-index) y crea
`app`. api.py lo re-exporta para mantener `uvicorn api:app`.

El ciclo de vida usa un unico `lifespan` (no `@app.on_event`, deprecado): al
arrancar lanza los hilos de fondo y los registra en appstate para observabilidad
(GET /admin/workers); al apagar les pide parar.
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

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

db._ensure_runtime_directories()


db._init_database()


agenda._ensure_default_employees_for_all_clients()


agenda._ensure_default_locations_for_all_clients()


clients._sync_clientes_table_from_config()


clients._validate_runtime_config()


rag._setup_llama_index()


def _start_background_workers() -> None:
    """Arranca los hilos daemon de fondo. Idempotente (no duplica si ya viven) y
    registra cada uno en appstate.worker_registry para GET /admin/workers.

    Mismos gates que antes: disponibilidad de dependencias (IMAP/IG/TK), credenciales
    y, para recordatorios, REMINDER_RUN_INTERVAL_MINUTES > 0."""
    try:
        purged_at_boot = demo_agenda._purge_expired_demos()
        if purged_at_boot:
            settings.logger.info("Demos expiradas purgadas al arranque: %s", purged_at_boot)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Error purgando demos al arranque: %s", exc)

    try:
        booking._backfill_booking_codes()
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Error en backfill de codigos de reserva al arranque: %s", exc)

    if outreach.OUTREACH_IMAP_AVAILABLE and (not appstate.outreach_imap_thread or not appstate.outreach_imap_thread.is_alive()):
        appstate.outreach_imap_stop.clear()
        appstate.outreach_imap_thread = threading.Thread(
            target=outreach._outreach_imap_worker, name="vantelia-outreach-imap", daemon=True,
        )
        appstate.outreach_imap_thread.start()
        appstate.register_worker("outreach-imap", appstate.outreach_imap_thread)

    if not appstate.outreach_autopilot_thread or not appstate.outreach_autopilot_thread.is_alive():
        appstate.outreach_autopilot_stop.clear()
        appstate.outreach_autopilot_thread = threading.Thread(
            target=outreach._outreach_autopilot_worker, name="vantelia-outreach-autopilot", daemon=True,
        )
        appstate.outreach_autopilot_thread.start()
        appstate.register_worker("outreach-autopilot", appstate.outreach_autopilot_thread)

    if not outreach.outreach_autonomous_thread or not outreach.outreach_autonomous_thread.is_alive():
        outreach.outreach_autonomous_stop.clear()
        outreach.outreach_autonomous_thread = threading.Thread(
            target=outreach._outreach_autonomous_worker, name="vantelia-outreach-autonomous", daemon=True,
        )
        outreach.outreach_autonomous_thread.start()
        appstate.register_worker("outreach-autonomous", outreach.outreach_autonomous_thread)

    if instagram.IG_REPLIES_AVAILABLE and (not instagram.ig_replies_thread or not instagram.ig_replies_thread.is_alive()):
        instagram.ig_replies_stop.clear()
        instagram.ig_replies_thread = threading.Thread(target=instagram._ig_replies_worker, name="vantelia-ig-replies", daemon=True)
        instagram.ig_replies_thread.start()
        appstate.register_worker("ig-replies", instagram.ig_replies_thread)
    if instagram.IG_AVAILABLE and (not instagram.ig_autopilot_thread or not instagram.ig_autopilot_thread.is_alive()):
        instagram.ig_autopilot_stop.clear()
        instagram.ig_autopilot_thread = threading.Thread(target=instagram._ig_autopilot_worker, name="vantelia-ig-autopilot", daemon=True)
        instagram.ig_autopilot_thread.start()
        appstate.register_worker("ig-autopilot", instagram.ig_autopilot_thread)
    if instagram.IG_AVAILABLE and (not instagram.ig_campaign_thread or not instagram.ig_campaign_thread.is_alive()):
        try:
            instagram._ig_campaign_migrate()
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("ig_campaign migrate fallo: %s", exc)
        instagram.ig_campaign_stop.clear()
        instagram.ig_campaign_thread = threading.Thread(target=instagram._ig_campaign_worker, name="vantelia-ig-campaign", daemon=True)
        instagram.ig_campaign_thread.start()
        appstate.register_worker("ig-campaign", instagram.ig_campaign_thread)

    if tiktok.TK_AVAILABLE:
        try:
            tiktok._tk_migrate()
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("tk_campaign migrate fallo: %s", exc)
        if not tiktok.tk_campaign_thread or not tiktok.tk_campaign_thread.is_alive():
            tiktok.tk_campaign_stop.clear()
            tiktok.tk_campaign_thread = threading.Thread(target=tiktok._tk_campaign_worker, name="vantelia-tk-campaign", daemon=True)
            tiktok.tk_campaign_thread.start()
            appstate.register_worker("tk-campaign", tiktok.tk_campaign_thread)

    if settings.REMINDER_RUN_INTERVAL_MINUTES <= 0:
        settings.logger.info("Recordatorios automaticos desactivados (REMINDER_RUN_INTERVAL_MINUTES <= 0).")
    elif not (appstate.booking_reminder_thread and appstate.booking_reminder_thread.is_alive()):
        appstate.booking_reminder_stop.clear()
        appstate.booking_reminder_thread = threading.Thread(
            target=booking._booking_reminder_worker, name="vantelia-booking-reminders", daemon=True,
        )
        appstate.booking_reminder_thread.start()
        appstate.register_worker("booking-reminders", appstate.booking_reminder_thread)

    if messaging._voice_twilio_configured():
        settings.logger.info("Voice channel enabled (Twilio configurado).")
    else:
        settings.logger.info("Voice channel DISABLED - missing Twilio credentials.")


def _stop_background_workers() -> None:
    """Senala a todos los workers de fondo que paren (idempotente)."""
    appstate.booking_reminder_stop.set()
    appstate.outreach_imap_stop.set()
    appstate.outreach_autopilot_stop.set()
    outreach.outreach_autonomous_stop.set()
    instagram.ig_replies_stop.set()
    instagram.ig_autopilot_stop.set()
    instagram.ig_campaign_stop.set()
    tiktok.tk_campaign_stop.set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_background_workers()
    try:
        yield
    finally:
        _stop_background_workers()


app = FastAPI(
    title="Vantelia Embedded Chat API",
    description="Backend multiempresa para chat embebible con RAG y flujo profesional de leads.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def _no_cache_widget_bundle(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/widget/widget.min.js":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # La central publica de reservas esta disenyada para incrustarse via iframe
    # (modo embed) en la web del negocio o en su sitio Vantelia. Es publica y sin
    # sesion, asi que permitimos enmarcarla (frame-ancestors) en vez de DENY.
    # El resto del sitio mantiene X-Frame-Options: DENY (anti-clickjacking).
    if request.url.path.startswith("/central/"):
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https:"
        if "X-Frame-Options" in response.headers:
            del response.headers["X-Frame-Options"]
    else:
        response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if textnorm._configured_public_base_url().startswith("https://"):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


app.mount("/widget", StaticFiles(directory=str(settings.WIDGET_DIR)), name="widget")


if settings.BRAND_DIR.exists():
    app.mount("/brand-assets", StaticFiles(directory=str(settings.BRAND_DIR)), name="brand-assets")


# Imagenes subidas por el tenant desde el portal (catalogo: servicios/productos/
# bonos + hero). Viven en storage/uploads/<cliente_id>/ (por entorno, incluido en
# el backup). Se sirven publicamente porque el catalogo publico las referencia.
_UPLOADS_DIR = settings.STORAGE_DIR / "uploads"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_UPLOADS_DIR)), name="uploads")


# Webs de escaparate por cliente (client_sites/<carpeta>/index.html), servidas en
# /site/<carpeta>/. Estaticas puras: para ensenyar al cliente su web nueva conectada
# a Vantelia antes de moverla a su dominio definitivo.
_CLIENT_SITES_DIR = Path(__file__).resolve().parents[1] / "client_sites"
if _CLIENT_SITES_DIR.exists():
    app.mount("/site", StaticFiles(directory=str(_CLIENT_SITES_DIR), html=True), name="client-sites")


def _build_cors_headers(origin: str) -> Dict[str, str]:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


@app.middleware("http")
async def dynamic_cors_middleware(request: Request, call_next: Any) -> Response:
    raw_origin = request.headers.get("origin", "").strip()
    normalized_origin = ""
    if raw_origin:
        try:
            normalized_origin = textnorm._normalize_origin_value(raw_origin)
        except RuntimeError:
            normalized_origin = ""

    is_preflight = request.method == "OPTIONS" and bool(
        request.headers.get("access-control-request-method", "").strip()
    )

    if is_preflight:
        response: Response = Response(status_code=204)
    else:
        response = await call_next(request)

    if normalized_origin and normalized_origin in clients._collect_cors_origins():
        for key, value in _build_cors_headers(normalized_origin).items():
            response.headers[key] = value

    return response


security._ensure_default_portal_admin()


# Registrar endpoints: el orden de import preserva el orden de rutas del monolito.
from backend.routers import (  # noqa: E402,F401
    public_base,
    auth_oauth,
    onboarding_web,
    portal_app,
    portal_content,
    billing_web,
    portal_users,
    ui_pages,
    public_misc,
    admin_core,
    public_booking,
    whatsapp_webhooks,
    admin_ops,
    admin_growth,
    admin_outreach,
    tracking,
    admin_captacion,
    voice_web,
    portal_commerce,
)
