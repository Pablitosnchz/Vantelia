"""Endpoints: seccion ui_pages (refactor F3).

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

@app.get("/acceso", include_in_schema=False)
@app.get("/login", include_in_schema=False)
async def access_entry(
    request: Request,
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
) -> Response:
    if "reset_token" not in request.query_params:
        user = security._get_authenticated_portal_user_or_none(portal_session)
        if user:
            return RedirectResponse(security._redirect_for_role(user["role"]))

    index_path = settings.ACCESS_UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Acceso no disponible.")
    html = (
        index_path.read_text(encoding="utf-8")
        .replace("__MARKETING_SITE_URL__", escape(settings.MARKETING_SITE_URL))
        .replace("__SUPPORT_EMAIL__", escape(settings.PORTAL_SUPPORT_EMAIL))
    )
    return HTMLResponse(html)


@app.get("/onboarding", include_in_schema=False)
async def onboarding_entry(
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
) -> Response:
    user = security._get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso?next=/onboarding")
    index_path = settings.ONBOARDING_UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Wizard de onboarding no disponible.")
    html = (
        index_path.read_text(encoding="utf-8")
        .replace("__MARKETING_SITE_URL__", escape(settings.MARKETING_SITE_URL))
        .replace("__SUPPORT_EMAIL__", escape(settings.PORTAL_SUPPORT_EMAIL))
        .replace("__USER_EMAIL__", escape(user["email"]))
        .replace("__USER_NAME__", escape(user["display_name"]))
    )
    return HTMLResponse(html)


@app.get("/app", include_in_schema=False)
async def app_entry(
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
) -> Response:
    user = security._get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso?next=/app")
    # If no cliente_id yet, push to wizard.
    if not (user["cliente_id"] or "").strip():
        return RedirectResponse("/onboarding")
    index_path = settings.APP_UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Portal de cliente no disponible.")
    html = (
        index_path.read_text(encoding="utf-8")
        .replace("__MARKETING_SITE_URL__", escape(settings.MARKETING_SITE_URL))
        .replace("__SUPPORT_EMAIL__", escape(settings.PORTAL_SUPPORT_EMAIL))
        .replace("__USER_EMAIL__", escape(user["email"]))
        .replace("__USER_NAME__", escape(user["display_name"]))
        .replace("__CLIENTE_ID__", escape(user["cliente_id"]))
    )
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            # El panel incluye la prueba de voz (llamada simulada) que necesita el
            # microfono. El resto del sitio mantiene microphone=(); aqui lo permitimos
            # al propio origen. El middleware de seguridad usa setdefault y lo respeta.
            "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
        },
    )


@app.get("/signup", include_in_schema=False)
async def signup_entry() -> Response:
    return RedirectResponse("/acceso?signup=1")


@app.get("/portal", include_in_schema=False)
async def portal_entry(
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
) -> Response:
    user = security._get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso")
    return RedirectResponse("/dashboard")


@app.get("/dashboard", include_in_schema=False)
async def dashboard(
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
) -> Response:
    user = security._get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso")
    if user["role"] != "admin":
        return RedirectResponse("/app")
    index_path = settings.ADMIN_UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Panel admin no disponible.")
    return FileResponse(index_path)


@app.get("/demo/{cliente_id}", include_in_schema=False)
async def demo_cliente(cliente_id: str, request: Request) -> HTMLResponse:
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)
    response = HTMLResponse(demo_agenda._build_demo_page(cliente_id, request))
    # La "llamada simulada" necesita el microfono. El resto del sitio mantiene
    # microphone=() por seguridad, pero en esta pagina lo permitimos para el propio
    # origen (self) para que el navegador pueda pedir el permiso en cualquier
    # dispositivo. El middleware de seguridad usa setdefault, asi que respeta este valor.
    response.headers["Permissions-Policy"] = "microphone=(self), camera=(), geolocation=()"
    return response




@app.post("/demo/{cliente_id}/voice/session", include_in_schema=False)
async def demo_voice_session(cliente_id: str, request: Request) -> Dict[str, Any]:
    """Token efimero para la "llamada simulada" del demo. A diferencia de la voz
    telefonica (Twilio), aqui NO se aplica gating de plan: el demo siempre permite
    probar la voz. Al ser pagina publica, acotamos el gasto con rate limit por IP y un
    tope de duracion que el front respeta colgando solo.
    """
    textnorm._assert_valid_client_id(cliente_id)
    config = clients._get_client_config(cliente_id)  # 404 si el cliente no existe
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El asistente de voz no esta disponible ahora mismo.",
        )
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"demo_voice:{cliente_id}:{client_ip}", settings.DEMO_VOICE_RATE_LIMIT)
    voice_cfg = config.get("voice") or {}
    max_seconds = int(voice_cfg.get("max_duration_seconds") or 0) or settings.DEMO_VOICE_MAX_SECONDS
    return await voice._mint_voice_session(cliente_id, config, max_seconds=max_seconds, log_tag="demo-voice")


@app.post("/demo/{cliente_id}/voice/tool", include_in_schema=False)
async def demo_voice_tool(cliente_id: str, request: Request) -> Dict[str, Any]:
    """Ejecuta una tool de la voz en navegador (demo publica). El navegador habla directo con
    OpenAI por WebRTC; cuando el modelo pide una funcion, el front la reenvia aqui y devolvemos
    el resultado para que lo cuente en voz. Sin esto, el modelo se quedaria esperando un
    function_call_output que nadie produce (silencio largo). Solo lectura: ver _voice_dispatch_tool_demo."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)  # 404 si el cliente no existe
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"demo_voice_tool:{cliente_id}:{client_ip}", 30)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    name = str(body.get("name", ""))
    arguments = body.get("arguments", "")
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    return await voice._voice_dispatch_tool_demo(cliente_id, name, arguments)


@app.post("/demo/generate", response_model=DemoGenerateResponse)
async def demo_generate(data: DemoGeneratePayload, request: Request) -> DemoGenerateResponse:
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"demo:{client_ip}", 3)

    demo_agenda._purge_expired_demos()
    registry = demo_agenda._load_demo_registry()
    email_lower = str(data.email).lower()
    now_ts = time.time()
    for existing_id, created_ts in registry.items():
        cfg = appstate.CONFIG_CLIENTES.get(existing_id, {})
        contacto_existing = cfg.get("contacto", {})
        if (
            str(contacto_existing.get("email", "")).lower() == email_lower
            and now_ts - created_ts < demo_agenda.DEMO_TTL_SECONDS
        ):
            existing_url = f"{textnorm._public_base_url(request)}/demo/{existing_id}"
            expires_dt = datetime.fromtimestamp(created_ts + demo_agenda.DEMO_TTL_SECONDS, tz=timezone.utc)
            remaining = max(0, int(created_ts + demo_agenda.DEMO_TTL_SECONDS - now_ts))
            return DemoGenerateResponse(
                ok=True,
                cliente_id=existing_id,
                demo_url=existing_url,
                expires_at=expires_dt.isoformat(),
                expires_in_seconds=remaining,
            )

    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de demos no esta disponible en este momento.",
        )

    base_slug = onboarding_utils.slugify_company(data.nombre_empresa).lower()[:30] or "empresa"
    token = secrets.token_hex(3)
    cliente_id = f"{demo_agenda.DEMO_TENANT_PREFIX}{base_slug}_{token}"
    textnorm._assert_valid_client_id(cliente_id)

    sector_clean = data.sector.strip()
    _sector_defaults = demo_agenda._DEMO_SECTOR_DEFAULTS.get(sector_clean, (
        f"Negocio del sector {sector_clean}.",
        "Servicios disponibles. Consultar para más información.",
    ))
    descripcion_clean = (data.descripcion or "").strip() or _sector_defaults[0]
    servicios_clean = (data.servicios or "").strip() or _sector_defaults[1]
    horario_clean = (data.horario or "").strip()
    empresa_clean = data.nombre_empresa.strip()

    manual_info = (
        f"Empresa: {empresa_clean}\n"
        f"Sector: {sector_clean}\n\n"
        f"Descripcion del negocio:\n{descripcion_clean}\n\n"
        f"Servicios principales:\n{servicios_clean}\n"
    )
    if horario_clean:
        manual_info += f"\nHorario:\n{horario_clean}\n"
    manual_info += f"\nContacto comercial: {data.email}\n"

    detected_business_name = empresa_clean
    info_txt = manual_info
    allowed_origins: List[str] = []
    scrape_result = None

    base_app = (settings.APP_BASE_URL or "https://app.vantelia.es").rstrip("/")
    allowed_origins.append(base_app)
    for origin in ("https://www.vantelia.es", "https://vantelia.es"):
        if origin not in allowed_origins:
            allowed_origins.append(origin)

    if data.website_url:
        try:
            scrape_result = await timeutils._to_thread(
                run_onboarding,
                website_url=data.website_url,
                api_key=settings.OPENAI_API_KEY,
                nombre_bot="Asistente",
                tono="profesional",
                idioma="es",
                max_paginas=4,
            )
            if scrape_result.detected_business_name:
                detected_business_name = scrape_result.detected_business_name
            if scrape_result.info_txt:
                info_txt = (
                    manual_info
                    + "\n--- Informacion extraida de la web ---\n"
                    + scrape_result.info_txt
                )
            parsed = urlparse(scrape_result.normalized_url)
            if parsed.netloc:
                origin_url = f"{parsed.scheme}://{parsed.netloc}"
                if origin_url not in allowed_origins:
                    allowed_origins.append(origin_url)
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("Demo scraping fallo para %s: %s", data.website_url, exc)

    color_val = (data.color or "#0EA5E9").strip()
    if not re.match(r"^#[0-9A-Fa-f]{6}$", color_val):
        color_val = "#0EA5E9"

    icono = "".join(ch for ch in detected_business_name if ch.isalnum())[:2].upper() or "AI"

    payload = AdminClientePayload(
        nombre=detected_business_name[:120] or empresa_clean[:120] or "Empresa",
        icono=icono,
        color=color_val,
        bienvenida=(
            f"Hola, soy el asistente virtual de {detected_business_name}. "
            "Cuentame en que puedo ayudarte."
        )[:400],
        prompt_extra=(
            "Habla con tono profesional y cercano, mantente dentro del contexto del negocio, "
            "responde solo con informacion apoyada en la base documental y deriva al equipo "
            "humano cuando falten datos. Si te preguntan precios concretos, indica que estos "
            "son orientativos y deben confirmarse con el equipo."
        ),
        allowed_origins=allowed_origins,
        contacto_email=str(data.email),
        contacto_telefono="",
        branding_text="Powered by Vantelia",
        booking_enabled=False,
        booking_timezone=settings.DEFAULT_TIMEZONE,
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
        info_txt=info_txt[:120000],
        reindex_after_save=True,
    )

    try:
        await timeutils._to_thread(portal._save_admin_client_payload, cliente_id, payload, request)
        if scrape_result is not None:
            rag._seed_qa_from_onboarding(cliente_id, scrape_result)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Error guardando demo %s: %s", cliente_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se ha podido generar la demo. Intentalo de nuevo en unos minutos.",
        ) from exc

    demo_agenda._register_demo_tenant(cliente_id)

    expires_dt = timeutils._utc_now() + timedelta(seconds=demo_agenda.DEMO_TTL_SECONDS)
    demo_url = f"{textnorm._public_base_url(request)}/demo/{cliente_id}"

    try:
        if globals().get("OUTREACH_AVAILABLE"):
            with outreach._outreach_db() as outreach_conn:
                outreach_conn.execute(
                    "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,?,?)",
                    (
                        email_lower,
                        "demo_generated",
                        "cold",
                        demo_url,
                        timeutils._utc_now().isoformat(timespec="seconds"),
                        request.headers.get("user-agent", "")[:200],
                        client_ip[:64],
                    ),
                )
                outreach_conn.commit()
    except Exception as exc:  # noqa: BLE001
        settings.logger.debug("No se pudo registrar demo_generated en outreach: %s", exc)

    if emailing._email_delivery_configured() and settings.CONSULTA_NOTIFICATION_EMAIL:
        try:
            asunto = f"Nueva demo generada: {empresa_clean}"
            cuerpo_text = (
                f"Se ha generado una demo desde la web publica.\n\n"
                f"Empresa: {empresa_clean}\n"
                f"Sector: {sector_clean}\n"
                f"Email: {data.email}\n"
                f"Web: {data.website_url or '(no proporcionada)'}\n"
                f"IP: {client_ip}\n"
                f"Demo URL: {demo_url}\n"
                f"Cliente ID: {cliente_id}\n"
                f"Expira: {expires_dt.isoformat()}\n\n"
                f"Descripcion:\n{descripcion_clean}\n\n"
                f"Servicios:\n{servicios_clean}\n"
            )
            cuerpo_html = (
                '<div style="font-family:sans-serif;max-width:600px;color:#1a1a2e">'
                '<h2 style="color:#00b1d9">Nueva demo generada</h2>'
                '<table style="width:100%;border-collapse:collapse">'
                f'<tr><td style="padding:6px 0;color:#666;width:120px">Empresa</td><td style="padding:6px 0;font-weight:600">{escape(empresa_clean)}</td></tr>'
                f'<tr><td style="padding:6px 0;color:#666">Sector</td><td style="padding:6px 0">{escape(sector_clean)}</td></tr>'
                f'<tr><td style="padding:6px 0;color:#666">Email</td><td style="padding:6px 0"><a href="mailto:{escape(str(data.email))}">{escape(str(data.email))}</a></td></tr>'
                f'<tr><td style="padding:6px 0;color:#666">Web</td><td style="padding:6px 0">{escape(data.website_url or "(no proporcionada)")}</td></tr>'
                f'<tr><td style="padding:6px 0;color:#666">Demo URL</td><td style="padding:6px 0"><a href="{escape(demo_url)}">{escape(demo_url)}</a></td></tr>'
                f'<tr><td style="padding:6px 0;color:#666">Cliente ID</td><td style="padding:6px 0"><code>{escape(cliente_id)}</code></td></tr>'
                f'<tr><td style="padding:6px 0;color:#666">Expira</td><td style="padding:6px 0">{escape(expires_dt.isoformat())}</td></tr>'
                '</table>'
                f'<p style="margin-top:16px"><strong>Descripcion:</strong><br>{escape(descripcion_clean).replace(chr(10), "<br>")}</p>'
                f'<p><strong>Servicios:</strong><br>{escape(servicios_clean).replace(chr(10), "<br>")}</p>'
                '<hr style="margin:20px 0;border:none;border-top:1px solid #eee">'
                f'<p style="font-size:12px;color:#999">IP: {escape(client_ip)} - lead automatico desde /demo/</p>'
                '</div>'
            )
            emailing._send_email_message(
                settings.CONSULTA_NOTIFICATION_EMAIL,
                asunto,
                cuerpo_text,
                cuerpo_html,
                reply_to=str(data.email),
            )
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("No se pudo notificar lead de demo: %s", exc)

    settings.logger.info(
        "Demo creada %s para %s desde IP %s (expira en %ss)",
        cliente_id, data.email, client_ip, demo_agenda.DEMO_TTL_SECONDS,
    )

    return DemoGenerateResponse(
        ok=True,
        cliente_id=cliente_id,
        demo_url=demo_url,
        expires_at=expires_dt.isoformat(),
        expires_in_seconds=demo_agenda.DEMO_TTL_SECONDS,
    )












