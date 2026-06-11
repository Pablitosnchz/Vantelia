"""Endpoints: seccion public_base (refactor F3).

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

@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    favicon_candidates = [
        settings.BRAND_DIR / "favicon.png",
        settings.BRAND_DIR / "favicon_fondo.png",
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
    path = settings.LEGAL_DIR / f"{slug}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Documento legal no configurado.")
    return HTMLResponse(_legal_page_html(slug, title, path.read_text(encoding="utf-8")))














from api_models import (
    MensajeChat,
    DatosCita,
    RespuestaChat,
    WhatsAppWebhookStatus,
    ChatSessionSummary,
    ChatMessagePublic,
    ChatSessionDetail,
    ConfigPublicaCliente,
    SlotDisponibilidad,
    RespuestaDisponibilidad,
    RespuestaAgendado,
    BookingDetailPublic,
    BookingActionResponse,
    BookingReschedulePayload,
    BookingCancelPayload,
    BookingAttendancePayload,
    StaffBookingCreatePayload,
    ServicePublic,
    ServicesResponse,
    ServicePayload,
    ServiceUpdatePayload,
    ServicePaymentPolicyPayload,
    ConnectAccountStatus,
    AiSendTogglePayload,
    ConnectStartResponse,
    CustomerPaymentPublic,
    CustomerPaymentsResponse,
    PaymentLinkPayload,
    PaymentLinkResponse,
    PaymentRefundPayload,
    BookingUpdatePayload,
    AdminBookingResumen,
    AdminReminderRunResult,
    AuthLoginPayload,
    AuthUserPublic,
    AuthLoginResponse,
    AuthSimpleResponse,
    AuthSignupPayload,
    AuthSignupResponse,
    OnboardingStartPayload,
    OnboardingStartResponse,
    OnboardingLearnPayload,
    OnboardingLearnResponse,
    OnboardingPersonalityPayload,
    OnboardingPersonalityResponse,
    OnboardingFinalizeResponse,
    OnboardingStateResponse,
    AppOverviewSubscription,
    AppOverviewStats,
    AppOverviewChannels,
    AppOverviewResponse,
    AppDeployResponse,
    AppAppearancePayload,
    AppAppearanceResponse,
    AppLeadPublic,
    AppLeadPayload,
    AppLeadsListResponse,
    CRMContactPayload,
    CRMContactPublic,
    CRMContactListItem,
    CRMContactsListResponse,
    CRMContactActivity,
    CRMContactDetailResponse,
    ChannelEmailStatus,
    ChannelSmsStatus,
    ChannelSettingsResponse,
    ChannelConnectResponse,
    ChannelEmailSettingsPayload,
    ChannelSmsSettingsPayload,
    ChannelTestPayload,
    AppQAItem,
    AppQAPayload,
    AppQAUpdatePayload,
    AppQAListResponse,
    AppKnowledgeItem,
    AppKnowledgeListResponse,
    AppKnowledgeTextPayload,
    AppKnowledgeUrlPayload,
    AppKnowledgeReindexResponse,
    AppTunePayload,
    AppTuneResponse,
    AppServiceProduct,
    AppServicesResponse,
    AppServicesPayload,
    AppWhatsAppPayload,
    AppWhatsAppResponse,
    AppVoicePayload,
    AppVoiceResponse,
    AppLiveChatSession,
    BillingPlanTier,
    BillingSubscriptionPublic,
    BillingStateResponse,
    BillingCheckoutPayload,
    BillingCheckoutResponse,
    AppTrackEventPayload,
    BillingPortalResponse,
    StripeConnectStateResponse,
    StripeConnectStartResponse,
    BookingPaymentStateResponse,
    GmailClientStateResponse,
    ConsultaLeadPayload,
    DemoGeneratePayload,
    DemoGenerateResponse,
    SubscriptionUsage,
    SubscriptionFeatures,
    SubscriptionPublic,
    SubscriptionCheckoutPayload,
    SubscriptionCheckoutResponse,
    PublicCheckoutStatusResponse,
    SubscriptionPortalResponse,
    AuthManagedUser,
    AuthManagedUsersResponse,
    AuthPasswordChangePayload,
    AuthPasswordForgotPayload,
    AuthPasswordResetPayload,
    AuthProfileUpdatePayload,
    PortalAiConfigPayload,
    PortalAiConfigPublic,
    PortalBrainPayload,
    PortalBrainPublic,
    PortalScheduleUpdatePayload,
    PortalAgendaBlockPayload,
    PortalAgendaBlock,
    PortalSchedulePublic,
    PortalAgendaBlockCreateResponse,
    PortalBookingSummary,
    PortalBookingsResponse,
    PortalEmployeePayload,
    PortalEmployeePublic,
    PortalEmployeesResponse,
    PortalDashboardResponse,
    PortalMessagePreviewPayload,
    PortalMessagePreviewResponse,
    BookingAuditEntry,
    BookingAuditResponse,
    PortalCreateUserPayload,
    AdminClientePayload,
    AdminClienteResumen,
    AdminClienteDetalle,
    AdminClienteSaveResult,
    AdminClienteAuditEntry,
    AdminClienteAuditResponse,
    AdminImpersonateResponse,
    AdminImpersonateEndResponse,
    AdminAltaExpressPayload,
    AdminAltaExpressResponse,
    GrowthDailyPayload,
    GrowthOpportunityPayload,
    GrowthWeeklyReviewPayload,
    GrowthPlanTaskPayload,
)











# ---------------------------------------------------------------------------
# Catalogo de servicios (duracion + precio) por cliente
# ---------------------------------------------------------------------------

























































# --- Vantelia 2.0 self-serve helpers (Sem 2) ---







# --- Google OAuth helpers ---













# --- Onboarding state (transient, lives in user row's metadata or memory) ---
# We store wizard state in the clientes row's config_json as a `_onboarding_state`
# key while the user has not finalized. On finalize we strip it.














































































































































































































































































# Defaults de descripcion/servicios por sector cuando no hay scraping ni datos.
# El scraping de la web sobrescribe esto; el fallback generico cubre sectores no listados.














# Bloque de "llamada simulada" por voz para la pagina de demo. Se inyecta como VALOR
# en el f-string de _build_demo_page (por eso usa llaves simples sin escapar) y trae su
# propio <style>, el overlay tipo pantalla de llamada y el JS WebRTC. Placeholders:
# __VOICE_CFG__ (objeto JS con api/cliente), __NOMBRE__, __INITIAL__, __COLOR__.



























































































































COMMERCIAL_INTENT_LABELS = {
    "diagnostico": "diagnostico inteligente",
    "recomendador": "recomendador de servicios",
    "estimador": "calculadora o estimador",
    "comparador": "comparador de opciones",
    "booking": "agenda",
}








































































# Alfabeto sin caracteres ambiguos (sin 0/O, 1/I/L) para el numero de reserva
# que el cliente dicta por telefono o teclea en chat.


























































































































# ---------------------------------------------------------------------------
# Datos de demostracion para la agenda (solo admin)
# ---------------------------------------------------------------------------


















































































@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": app.title,
        "version": app.version,
        "clientes_activos": sorted(appstate.CONFIG_CLIENTES.keys()),
    }


