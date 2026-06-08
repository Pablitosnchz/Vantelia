from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Europe/Madrid")
PLAN_DEFAULT = "free"


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
    intent: str = ""
    quick_actions: List[Dict[str, str]] = Field(default_factory=list)


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
    accent_color: str = ""
    logo_url: str = ""
    launcher_shape: str = "circle"
    launcher_size: int = 60
    bienvenida: str
    booking_enabled: bool
    branding_text: str
    contact_email: str
    contact_phone: str
    starter_questions: List[str] = Field(default_factory=list)


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
    service_id: str = ""
    service_duration_minutes: int = 0
    service_price_cents: int = 0
    service_price_label: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    available_services: List[Dict[str, Any]] = Field(default_factory=list)


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


class BookingAttendancePayload(BaseModel):
    attended: bool


class ServicePublic(BaseModel):
    id: str
    nombre: str
    descripcion: str = ""
    duration_minutes: int = 30
    price_cents: int = 0
    price_label: str = ""
    is_active: bool = True


class ServicesResponse(BaseModel):
    items: List[ServicePublic]


class ServicePayload(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(default=30, ge=5, le=600)
    price_cents: int = Field(default=0, ge=0, le=10_000_000)
    descripcion: str = Field(default="", max_length=500)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=9999)


class ServiceUpdatePayload(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=120)
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=600)
    price_cents: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    descripcion: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = Field(default=None, ge=0, le=9999)


class StaffBookingCreatePayload(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    email: str = Field(default="", max_length=200)
    telefono: str = Field(default="", max_length=40)
    servicio: str = Field(default="", max_length=160)
    employee_id: str = Field(default="", max_length=80)
    fecha: str = Field(min_length=10, max_length=10)
    hora: str = Field(min_length=5, max_length=5)
    notas: str = Field(default="", max_length=1000)


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
    plan: str = PLAN_DEFAULT
    plan_label: str = "Free"
    last_login_at: str = ""
    as_admin_session: bool = False
    impersonator_email: str = ""


class AuthLoginResponse(BaseModel):
    ok: bool
    user: AuthUserPublic
    redirect_to: str


class AuthSimpleResponse(BaseModel):
    ok: bool
    message: str
    retry_after_seconds: int = 0


# --- Vantelia 2.0 self-serve signup + wizard onboarding (Sem 2) ---

class AuthSignupPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)
    marketing_optin: bool = False
    claim: Optional[str] = Field(default=None, max_length=120)


class AuthSignupResponse(BaseModel):
    ok: bool
    user: AuthUserPublic
    redirect_to: str


class OnboardingStartPayload(BaseModel):
    nombre: str = Field(min_length=1, max_length=120, description="Nombre del bot")


class OnboardingStartResponse(BaseModel):
    cliente_id: str
    nombre: str
    step: str = "learn"


class OnboardingLearnPayload(BaseModel):
    website_url: Optional[str] = Field(default=None, max_length=400)
    just_this_page: bool = False
    tono: str = "Profesional y cercano"
    idioma: str = "Espanol"
    max_paginas: int = Field(default=12, ge=1, le=30)


class OnboardingLearnResponse(BaseModel):
    ok: bool
    cliente_id: str
    detected_business_name: str = ""
    info_excerpt: str = ""
    suggested_welcome: str = ""
    suggested_prompt_extra: str = ""
    suggested_starters: List[str] = Field(default_factory=list)
    pages_indexed: int = 0


class OnboardingPersonalityPayload(BaseModel):
    bienvenida: str = Field(min_length=1, max_length=600)
    prompt_extra: str = Field(default="", max_length=4000)
    starter_questions: List[str] = Field(default_factory=list, max_length=8)


class OnboardingPersonalityResponse(BaseModel):
    ok: bool
    cliente_id: str
    bienvenida: str
    prompt_extra: str
    starter_questions: List[str]


class OnboardingFinalizeResponse(BaseModel):
    ok: bool
    cliente_id: str
    install_snippet: str
    widget_script_url: str
    demo_url: str
    share_link: str
    dashboard_url: str


class OnboardingStateResponse(BaseModel):
    cliente_id: str = ""
    nombre: str = ""
    website_url: str = ""
    step: str = "name"
    bienvenida: str = ""
    prompt_extra: str = ""
    starter_questions: List[str] = Field(default_factory=list)
    has_kb: bool = False


# --- Vantelia 2.0 dashboard nuevo (Sem 3) ---

class AppOverviewSubscription(BaseModel):
    plan: str = "free"
    status: str = "active"
    messages_quota: int = 50
    messages_used: int = 0
    cancel_at_period_end: bool = False
    current_period_end: str = ""


class AppOverviewStats(BaseModel):
    users_today: int = 0
    messages_today: int = 0
    messages_period: int = 0
    leads_generated: int = 0
    training_chars: int = 0
    chat_sessions_total: int = 0
    bookings_today: int = 0
    bookings_upcoming: int = 0
    countries: List[Dict[str, Any]] = Field(default_factory=list)


class AppOverviewChannels(BaseModel):
    web: bool = True
    whatsapp: bool = False
    voice: bool = False
    booking: bool = False


class AppOverviewResponse(BaseModel):
    cliente_id: str
    nombre: str
    color: str = "#00b1d9"
    icono: str = "AI"
    bienvenida: str = ""
    subscription: AppOverviewSubscription
    stats: AppOverviewStats
    channels: AppOverviewChannels = Field(default_factory=AppOverviewChannels)


class AppDeployResponse(BaseModel):
    cliente_id: str
    install_snippet: str
    widget_script_url: str
    api_base_url: str
    demo_url: str
    share_link: str
    qr_data_url: str = ""


class AppAppearancePayload(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=120)
    color: Optional[str] = Field(default=None, max_length=7)
    accent_color: Optional[str] = Field(default=None, max_length=7)
    icono: Optional[str] = Field(default=None, max_length=12)
    logo_url: Optional[str] = Field(default=None, max_length=2000000)
    launcher_shape: Optional[str] = Field(default=None, max_length=16)
    launcher_size: Optional[int] = Field(default=None, ge=48, le=320)
    bienvenida: Optional[str] = Field(default=None, max_length=600)
    prompt_extra: Optional[str] = Field(default=None, max_length=4000)
    starter_questions: Optional[List[str]] = None
    allowed_origins: Optional[List[str]] = None
    booking_enabled: Optional[bool] = None


class AppAppearanceResponse(BaseModel):
    ok: bool
    cliente_id: str
    nombre: str
    color: str
    accent_color: str = ""
    icono: str
    logo_url: str = ""
    launcher_shape: str = "circle"
    launcher_size: int = 60
    bienvenida: str
    prompt_extra: str
    starter_questions: List[str] = Field(default_factory=list)
    allowed_origins: List[str] = Field(default_factory=list)
    booking_enabled: bool = True


# --- Vantelia 2.0 dashboard - Sem 4 (Leads, Q&A, Knowledge, Tune AI, Live Chat) ---

class AppLeadPublic(BaseModel):
    id: str
    name: str = ""
    email: str = ""
    phone: str = ""
    message: str = ""
    source: str = "chat"
    session_id: str = ""
    created_at: str


class AppLeadPayload(BaseModel):
    name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=4000)
    source: str = Field(default="manual", max_length=40)
    session_id: str = Field(default="", max_length=200)


class AppLeadsListResponse(BaseModel):
    items: List[AppLeadPublic]
    total: int
    page: int
    page_size: int


class AppQAItem(BaseModel):
    id: str
    question: str
    answer: str
    tags: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class AppQAPayload(BaseModel):
    question: str = Field(min_length=2, max_length=400)
    answer: str = Field(min_length=2, max_length=4000)
    tags: List[str] = Field(default_factory=list, max_length=10)


class AppQAUpdatePayload(BaseModel):
    question: Optional[str] = Field(default=None, max_length=400)
    answer: Optional[str] = Field(default=None, max_length=4000)
    tags: Optional[List[str]] = Field(default=None, max_length=10)


class AppQAListResponse(BaseModel):
    items: List[AppQAItem]
    total: int


class AppKnowledgeItem(BaseModel):
    id: str
    source: str
    filename: str = ""
    source_url: str = ""
    size_bytes: int = 0
    indexed_at: str = ""
    uploaded_at: str
    qa_created: int = 0


class AppKnowledgeListResponse(BaseModel):
    items: List[AppKnowledgeItem]
    info_chars: int = 0
    info_excerpt: str = ""
    info_full: str = ""


class AppKnowledgeTextPayload(BaseModel):
    title: str = Field(default="", max_length=200)
    content: str = Field(min_length=2, max_length=20000)


class AppKnowledgeUrlPayload(BaseModel):
    url: str = Field(min_length=4, max_length=400)
    just_this_page: bool = False
    replace: bool = False  # if true, replace info.txt; if false, append


class AppKnowledgeReindexResponse(BaseModel):
    ok: bool
    cliente_id: str
    info_chars: int


class AppTunePayload(BaseModel):
    prompt_extra: Optional[str] = Field(default=None, max_length=8000)
    chat_model: Optional[str] = Field(default=None, max_length=80)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)


class AppTuneResponse(BaseModel):
    cliente_id: str
    prompt_extra: str
    chat_model: str
    temperature: float
    available_models: List[str] = Field(default_factory=list)


class AppServiceProduct(BaseModel):
    id: str = ""
    nombre: str = Field(min_length=1, max_length=160)
    descripcion: str = Field(default="", max_length=800)


class AppServicesResponse(BaseModel):
    cliente_id: str
    items: List[AppServiceProduct] = Field(default_factory=list)
    info_chars: int = 0


class AppServicesPayload(BaseModel):
    items: List[AppServiceProduct] = Field(default_factory=list, max_length=80)


class AppWhatsAppPayload(BaseModel):
    enabled: Optional[bool] = None
    phone_number_id: Optional[str] = Field(default=None, max_length=120)
    access_token_env: Optional[str] = Field(default=None, max_length=120)
    verify_token_env: Optional[str] = Field(default=None, max_length=120)


class AppWhatsAppResponse(BaseModel):
    ok: bool = True
    cliente_id: str
    enabled: bool = False
    phone_number_id: str = ""
    access_token_env: str = ""
    verify_token_env: str = ""
    webhook_url: str = ""
    verify_token: str = ""
    plan_allows_whatsapp: bool = False
    access_token_configured: bool = False
    verify_token_configured: bool = False
    status: str = "disabled"
    status_label: str = "Desactivado"


class AppVoicePayload(BaseModel):
    enabled: Optional[bool] = None
    twilio_phone_number: Optional[str] = Field(default=None, max_length=32)
    openai_voice: Optional[str] = Field(default=None, max_length=40)


class AppVoiceResponse(BaseModel):
    ok: bool = True
    cliente_id: str
    enabled: bool = False
    twilio_phone_number: str = ""
    openai_voice: str = ""
    webhook_url: str = ""
    plan_allows_voice: bool = False
    status: str = "disabled"
    status_label: str = "Desactivado"


class AppLiveChatSession(BaseModel):
    id: str
    chat_session_id: str
    status: str
    started_at: str
    claimed_at: str = ""
    agent_user_id: str = ""


# --- Vantelia 2.0 billing (Sem 5) ---

class BillingPlanTier(BaseModel):
    slug: str
    label: str
    price_monthly_eur: int
    price_annual_eur: int
    messages_quota: int
    bookings_quota: Optional[int] = None
    features: List[str]
    has_monthly_price_id: bool = False
    has_annual_price_id: bool = False
    is_current: bool = False


class BillingSubscriptionPublic(BaseModel):
    plan: str
    status: str
    messages_quota: int
    messages_used: int
    messages_remaining: int
    cancel_at_period_end: bool
    current_period_start: str = ""
    current_period_end: str = ""
    stripe_customer_id: str = ""


class BillingStateResponse(BaseModel):
    subscription: BillingSubscriptionPublic
    plans: List[BillingPlanTier]
    portal_available: bool = False


class BillingCheckoutPayload(BaseModel):
    plan: str = Field(min_length=2, max_length=40)
    billing_period: str = Field(default="monthly", pattern=r"^(monthly|annual)$")
    coupon: Optional[str] = Field(default=None, max_length=80)


class BillingCheckoutResponse(BaseModel):
    ok: bool
    checkout_url: str


class AppTrackEventPayload(BaseModel):
    event: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BillingPortalResponse(BaseModel):
    ok: bool
    portal_url: str


class StripeConnectStateResponse(BaseModel):
    configured: bool = False
    connected: bool = False
    stripe_account_id: str = ""
    status: str = "not_connected"
    requirements_due: int = 0
    last_error: str = ""


class StripeConnectStartResponse(BaseModel):
    ok: bool
    onboarding_url: str


class ConsultaLeadPayload(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    email: EmailStr
    telefono: Optional[str] = Field(default=None, max_length=40)
    empresa: Optional[str] = Field(default=None, max_length=120)
    servicio: Optional[str] = Field(default=None, max_length=80)
    mensaje: Optional[str] = Field(default=None, max_length=2000)


_DEMO_SECTOR_DEFAULTS: dict[str, tuple[str, str]] = {
    "Clínica / Salud": (
        "Centro médico especializado en atención a pacientes.",
        "Primera consulta\nRevisión general\nTratamientos especializados",
    ),
    "Restaurante / Hostelería": (
        "Restaurante con cocina de calidad y atención personalizada.",
        "Menú del día\nCarta a la carta\nReservas de grupo",
    ),
    "Inmobiliaria": (
        "Agencia inmobiliaria con amplia cartera de pisos y locales.",
        "Compra de vivienda\nAlquiler\nAsesoramiento hipotecario",
    ),
    "Servicios profesionales": (
        "Empresa de servicios profesionales con equipo experto.",
        "Consulta inicial\nAsesoramiento\nGestión de proyectos",
    ),
    "Belleza y estética": (
        "Centro de belleza y estética con tratamientos personalizados.",
        "Corte y peinado\nTratamientos faciales\nManicura y pedicura",
    ),
    "Talleres y reparación": (
        "Taller especializado en reparación y mantenimiento.",
        "Diagnóstico\nReparación\nMantenimiento preventivo",
    ),
    "Educación / Academias": (
        "Academia con cursos presenciales y online.",
        "Clases particulares\nCursos grupales\nPreparación de exámenes",
    ),
    "Comercio / Retail": (
        "Comercio con amplia selección de productos.",
        "Productos disponibles\nEnvíos y devoluciones\nAtención al cliente",
    ),
    "Tecnología / SaaS": (
        "Empresa de tecnología con soluciones digitales.",
        "Demo del producto\nPlanes y precios\nSoporte técnico",
    ),
}


class DemoGeneratePayload(BaseModel):
    nombre_empresa: str = Field(min_length=1, max_length=120)
    sector: str = Field(min_length=1, max_length=60)
    email: EmailStr
    descripcion: Optional[str] = Field(default=None, max_length=1500)
    servicios: Optional[str] = Field(default=None, max_length=1500)
    horario: Optional[str] = Field(default=None, max_length=200)
    color: Optional[str] = Field(default=None, max_length=20)
    website_url: Optional[str] = Field(default=None, max_length=300)


class DemoGenerateResponse(BaseModel):
    ok: bool = True
    cliente_id: str
    demo_url: str
    expires_at: str
    expires_in_seconds: int


class SubscriptionUsage(BaseModel):
    conversations: int = 0
    conversations_limit: Optional[int] = None
    bookings: int = 0
    bookings_limit: Optional[int] = None
    period_start: str = ""
    period_end: str = ""


class SubscriptionFeatures(BaseModel):
    branding_customization: bool = False
    whatsapp_enabled: bool = False
    csv_export: bool = False
    multi_branch: bool = False
    crm_integration: bool = False
    show_powered_by: bool = True
    max_professionals: Optional[int] = 1
    max_users: Optional[int] = 1
    max_extra_documents: Optional[int] = 0


class SubscriptionPublic(BaseModel):
    plan: str
    plan_label: str
    effective_plan: str = ""
    effective_plan_label: str = ""
    admin_override: bool = False
    status: str
    price_eur: int
    lifetime: bool = False
    renews_at: str = ""
    started_at: str = ""
    canceled_at: str = ""
    stripe_customer_id: str = ""
    stripe_subscription_id: str = ""
    features: SubscriptionFeatures
    usage: SubscriptionUsage
    available_plans: List[Dict[str, Any]] = Field(default_factory=list)


class SubscriptionCheckoutPayload(BaseModel):
    plan: str = Field(min_length=1, max_length=20)
    billing_period: str = Field(default="monthly", max_length=20)
    success_url: Optional[str] = Field(default=None, max_length=500)
    cancel_url: Optional[str] = Field(default=None, max_length=500)


class SubscriptionCheckoutResponse(BaseModel):
    url: str
    session_id: str = ""


class PublicCheckoutStatusResponse(BaseModel):
    status: str
    message: str = ""
    cliente_id: str = ""
    portal_enter_url: str = ""


class SubscriptionPortalResponse(BaseModel):
    url: str


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
    nombre: Optional[str] = Field(default=None, max_length=120)
    color: Optional[str] = Field(default=None, max_length=7)
    accent_color: Optional[str] = Field(default=None, max_length=7)
    branding_text: Optional[str] = Field(default=None, max_length=120)
    logo_url: Optional[str] = Field(default=None, max_length=2000000)


class PortalAiConfigPublic(BaseModel):
    nombre: str
    icono: str
    color: str
    accent_color: str = ""
    logo_url: str = ""
    bienvenida: str
    prompt_extra: str
    branding_text: str = "Powered by Vantelia"


class PortalBrainPayload(BaseModel):
    info_txt: str = Field(default="", max_length=120000)


class PortalBrainPublic(BaseModel):
    info_txt: str
    reindexed: bool = False
    reindex_error: str = ""


class PortalScheduleBreakWindow(BaseModel):
    start: str = Field(min_length=5, max_length=5)
    end: str = Field(min_length=5, max_length=5)
    reason: str = Field(default="Descanso", max_length=80)


class PortalScheduleUpdatePayload(BaseModel):
    enabled: bool = True
    timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=80)
    slot_minutes: int = Field(default=30, ge=5, le=240)
    day_start: str = Field(default="09:00", min_length=5, max_length=5)
    day_end: str = Field(default="18:00", min_length=5, max_length=5)
    break_start: str = Field(default="", max_length=5)
    break_end: str = Field(default="", max_length=5)
    break_windows: List[PortalScheduleBreakWindow] = Field(default_factory=list)
    closed_weekdays: List[int] = Field(default_factory=list)
    message_templates: Optional[Dict[str, str]] = None
    message_template_enabled: Optional[Dict[str, bool]] = None
    message_template_channels: Optional[Dict[str, Dict[str, bool]]] = None


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
    break_start: str = ""
    break_end: str = ""
    break_windows: List[PortalScheduleBreakWindow] = Field(default_factory=list)
    closed_weekdays: List[int]
    message_templates: Dict[str, str]
    message_template_enabled: Dict[str, bool]
    message_template_channels: Dict[str, Dict[str, bool]]
    reminder_channel_availability: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
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
    telefono: str = ""
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
    booking_code: str = ""
    completed_source: str = ""
    service_id: str = ""
    service_duration_minutes: int = 0
    service_price_cents: int = 0
    service_price_label: str = ""
    start_at: str = ""
    end_at: str = ""
    can_cancel: bool = True
    can_reschedule: bool = True
    can_mark_attendance: bool = False


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
    break_start: str = Field(default="", max_length=5)
    break_end: str = Field(default="", max_length=5)
    break_windows: List[PortalScheduleBreakWindow] = Field(default_factory=list)
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
    break_start: str = ""
    break_end: str = ""
    break_windows: List[PortalScheduleBreakWindow] = Field(default_factory=list)
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
    install_snippet: str = ""
    widget_script_url: str = ""
    api_base_url: str = ""
    demo_url: str = ""


class PortalMessagePreviewPayload(BaseModel):
    kind: str = Field(default="", max_length=40)
    schedule: Optional[PortalScheduleUpdatePayload] = None
    target_email: Optional[EmailStr] = None
    template_key: str = Field(default="", max_length=40)
    content: str = Field(default="", max_length=500)
    test_email: Optional[EmailStr] = None


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
    accent_color: Optional[str] = Field(default=None, max_length=7)
    logo_url: Optional[str] = Field(default=None, max_length=2000000)
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
    owner_user_id: str = ""
    owner_email: str = ""
    owner_display_name: str = ""
    owner_last_login_at: str = ""
    owner_created_at: str = ""
    cliente_created_at: str = ""
    plan: str = ""
    messages_used: int = 0
    messages_quota: int = 0
    booking_enabled: bool = False
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
    voice_enabled: bool = False
    voice_phone_number: str = ""
    has_info_file: bool
    info_file_size: int = 0
    bookings_total: int = 0
    bookings_pending: int = 0
    is_demo: bool = False
    demo_expires_at: str = ""
    demo_expires_in_seconds: int = 0
    subscription_plan: str = ""
    subscription_status: str = ""
    stripe_subscription_id: str = ""


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


class AdminClienteAuditEntry(BaseModel):
    admin_email: str
    started_at: str
    ended_at: str = ""
    ip: str = ""
    user_agent: str = ""
    duration_seconds: Optional[int] = None


class AdminClienteAuditResponse(BaseModel):
    cliente_id: str
    items: List[AdminClienteAuditEntry]


class AdminImpersonateResponse(BaseModel):
    ok: bool
    cliente_id: str
    target_user_id: str
    target_email: str
    expires_in_minutes: int
    redirect_url: str


class AdminImpersonateEndResponse(BaseModel):
    ok: bool
    admin_redirect_url: str = "/dashboard"


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


class GrowthDailyPayload(BaseModel):
    researched: int = Field(default=0, ge=0, le=100000)
    contacts: int = Field(default=0, ge=0, le=100000)
    followups: int = Field(default=0, ge=0, le=100000)
    calls: int = Field(default=0, ge=0, le=100000)
    positive_replies: int = Field(default=0, ge=0, le=100000)
    conversations: int = Field(default=0, ge=0, le=100000)
    meetings: int = Field(default=0, ge=0, le=100000)
    proposals: int = Field(default=0, ge=0, le=100000)
    won: int = Field(default=0, ge=0, le=100000)
    eur_sold: float = Field(default=0, ge=0, le=100000000)
    new_recurring: int = Field(default=0, ge=0, le=100000)
    delivery_hours: float = Field(default=0, ge=0, le=10000)
    learning: str = Field(default="", max_length=2000)
    blocker: str = Field(default="", max_length=2000)
    next_action: str = Field(default="", max_length=1000)


class GrowthOpportunityPayload(BaseModel):
    company: str = Field(min_length=1, max_length=180)
    campaign: str = Field(default="", max_length=120)
    offer: str = Field(default="", max_length=120)
    stage: str = Field(default="identificada", max_length=40)
    value_eur: float = Field(default=0, ge=0, le=100000000)
    decision_maker: str = Field(default="", max_length=180)
    contact: str = Field(default="", max_length=240)
    problem: str = Field(default="", max_length=2000)
    next_action: str = Field(default="", max_length=1000)
    next_action_date: str = Field(default="", max_length=10)
    decision_date: str = Field(default="", max_length=10)
    notes: str = Field(default="", max_length=4000)
    lost_reason: str = Field(default="", max_length=1000)


class GrowthWeeklyReviewPayload(BaseModel):
    week_start: str = Field(min_length=10, max_length=10)
    decision: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=4000)


class GrowthPlanTaskPayload(BaseModel):
    task_key: str = Field(min_length=1, max_length=120)
    completed: bool = False
