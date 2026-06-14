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
    location_id: str = Field(default="", max_length=64)
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


class ConversationSummary(BaseModel):
    id: str
    kind: str = "chat"          # chat | voice
    channel: str = "web"        # web | whatsapp | voice
    contact: str = ""
    started_at: str = ""
    last_at: str = ""
    preview: str = ""
    message_count: int = 0
    duration_seconds: int = 0
    booking_created: bool = False
    intents: List[str] = Field(default_factory=list)


class ConversationsResponse(BaseModel):
    items: List[ConversationSummary] = Field(default_factory=list)


class ConversationMessage(BaseModel):
    role: str = "user"
    content: str = ""
    created_at: str = ""


class ConversationDetail(BaseModel):
    conversation: ConversationSummary
    messages: List[ConversationMessage] = Field(default_factory=list)
    summary_text: str = ""


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
    voice_widget_enabled: bool = False


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
    payment_status: str = "not_required"
    payment_url: str = ""


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
    payment_status: str = "not_required"
    payment_url: str = ""


class BookingReschedulePayload(BaseModel):
    employee_id: str = Field(default="", max_length=80)
    fecha: str = Field(min_length=10, max_length=10)
    hora: str = Field(min_length=5, max_length=5)


class BookingCancelPayload(BaseModel):
    motivo: str = Field(default="", max_length=500)


class BookingAttendancePayload(BaseModel):
    attended: bool


class CancellationPolicyPayload(BaseModel):
    enabled: Optional[bool] = None
    free_cancel_hours: Optional[int] = Field(default=None, ge=0, le=720)
    late_cancel_fee_pct: Optional[int] = Field(default=None, ge=0, le=100)
    no_show_fee_pct: Optional[int] = Field(default=None, ge=0, le=100)
    auto_apply: Optional[bool] = None
    policy_text: Optional[str] = Field(default=None, max_length=1200)


class CancellationPolicyResponse(BaseModel):
    enabled: bool = False
    free_cancel_hours: int = 24
    late_cancel_fee_pct: int = 0
    no_show_fee_pct: int = 100
    auto_apply: bool = True
    policy_text: str = ""


class CancellationOutcome(BaseModel):
    enabled: bool = False
    auto_apply: bool = True
    kind: str = "cancel"
    within_free_window: bool = False
    free_cancel_hours: int = 24
    hours_until: Optional[float] = None
    fee_pct: int = 0
    fee_cents: int = 0
    refund_cents: int = 0
    price_cents: int = 0
    currency: str = "eur"
    policy_text: str = ""


class CancellationPreviewResponse(BaseModel):
    booking_id: str
    cancel: CancellationOutcome
    no_show: CancellationOutcome


class ServicePublic(BaseModel):
    id: str
    nombre: str
    descripcion: str = ""
    duration_minutes: int = 30
    price_cents: int = 0
    price_label: str = ""
    is_active: bool = True
    payment_mode: str = "payment_disabled"
    payment_type: str = "full"
    deposit_amount_cents: int = 0
    currency: str = "eur"
    deposit_value: int = 0
    confirm_booking_on_paid: bool = True
    cancel_free_hours: Optional[int] = None
    cancel_late_fee_pct: Optional[int] = None
    no_show_fee_pct: Optional[int] = None


class ServicesResponse(BaseModel):
    items: List[ServicePublic]


class ServicePayload(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(default=30, ge=5, le=600)
    price_cents: int = Field(default=0, ge=0, le=10_000_000)
    descripcion: str = Field(default="", max_length=500)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=9999)
    payment_mode: str = Field(default="payment_disabled", pattern=r"^(payment_disabled|payment_optional|payment_required)$")
    payment_type: str = Field(default="full", pattern=r"^(full|deposit|preauth)$")
    deposit_amount_cents: int = Field(default=0, ge=0, le=10_000_000)
    currency: str = Field(default="eur", pattern=r"^[a-zA-Z]{3}$")
    cancel_free_hours: Optional[int] = Field(default=None, ge=0, le=720)
    cancel_late_fee_pct: Optional[int] = Field(default=None, ge=0, le=100)
    no_show_fee_pct: Optional[int] = Field(default=None, ge=0, le=100)


class ServiceUpdatePayload(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=120)
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=600)
    price_cents: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    descripcion: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = Field(default=None, ge=0, le=9999)
    payment_mode: Optional[str] = Field(default=None, pattern=r"^(payment_disabled|payment_optional|payment_required)$")
    payment_type: Optional[str] = Field(default=None, pattern=r"^(full|deposit|preauth)$")
    deposit_amount_cents: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    currency: Optional[str] = Field(default=None, pattern=r"^[a-zA-Z]{3}$")
    cancel_free_hours: Optional[int] = Field(default=None, ge=-1, le=720)
    cancel_late_fee_pct: Optional[int] = Field(default=None, ge=-1, le=100)
    no_show_fee_pct: Optional[int] = Field(default=None, ge=-1, le=100)


class BookingPaymentActionPayload(BaseModel):
    amount_cents: Optional[int] = Field(default=None, ge=1, le=10_000_000)
    reason: str = Field(default="", max_length=300)


class BookingPaymentActionResponse(BaseModel):
    ok: bool = True
    booking_id: str
    payment_status: str = ""
    amount_cents: int = 0
    message: str = ""


class ServicePaymentPolicyPayload(BaseModel):
    mode: str = Field(default="none", max_length=40)
    deposit_value: int = Field(default=0, ge=0, le=10_000_000)
    confirm_booking_on_paid: bool = True


class ConnectAccountStatus(BaseModel):
    connected: bool = False
    stripe_account_id: str = ""
    charges_enabled: bool = False
    payouts_enabled: bool = False
    details_submitted: bool = False
    # Opt-in: permite que la IA (web, WhatsApp, voz) envie enlaces de pago en
    # nombre del negocio. Por defecto desactivado.
    ai_send_enabled: bool = False


class AiSendTogglePayload(BaseModel):
    enabled: bool


class ConnectStartResponse(BaseModel):
    url: str


class CustomerPaymentPublic(BaseModel):
    id: str
    contact_id: str = ""
    booking_id: str = ""
    service_id: str = ""
    service_name: str = ""
    amount_cents: int = 0
    currency: str = "eur"
    status: str = "pending"
    checkout_url: str = ""
    created_at: str = ""
    paid_at: str = ""
    updated_at: str = ""


class CustomerPaymentsResponse(BaseModel):
    items: List[CustomerPaymentPublic]
    total: int


class PaymentLinkPayload(BaseModel):
    amount_cents: Optional[int] = Field(default=None, ge=50, le=10_000_000)


class PaymentLinkResponse(BaseModel):
    payment: CustomerPaymentPublic
    checkout_url: str


class PaymentRefundPayload(BaseModel):
    amount_cents: Optional[int] = Field(default=None, ge=1, le=10_000_000)


class StaffBookingCreatePayload(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    email: str = Field(default="", max_length=200)
    telefono: str = Field(default="", max_length=40)
    servicio: str = Field(default="", max_length=160)
    employee_id: str = Field(default="", max_length=80)
    location_id: str = Field(default="", max_length=64)
    fecha: str = Field(min_length=10, max_length=10)
    hora: str = Field(min_length=5, max_length=5)
    notas: str = Field(default="", max_length=1000)


class BookingUpdatePayload(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    # str (no EmailStr): las citas de mostrador/walk-in no tienen email; reprogramarlas
    # (incluido el drag&drop) no debe fallar por validacion. El flujo publico sobreescribe
    # este campo con el email guardado de la reserva.
    email: str = Field(default="", max_length=200)
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
    portal_role: str = "owner"
    cliente_id: str = ""
    plan: str = PLAN_DEFAULT
    plan_label: str = "Free"
    last_login_at: str = ""
    as_admin_session: bool = False
    impersonator_email: str = ""
    permissions: List[str] = Field(default_factory=list)


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


class CRMContactPayload(BaseModel):
    name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=80)
    status: str = Field(default="nuevo", max_length=40)
    notes: str = Field(default="", max_length=8000)
    tags: List[str] = Field(default_factory=list, max_length=30)
    owner: str = Field(default="", max_length=200)
    next_action: str = Field(default="", max_length=500)
    next_action_at: str = Field(default="", max_length=40)
    source: str = Field(default="manual", max_length=40)


class CRMContactPublic(BaseModel):
    id: str
    cliente_id: str
    name: str = ""
    email: str = ""
    phone: str = ""
    status: str = "nuevo"
    notes: str = ""
    tags: List[str] = Field(default_factory=list)
    owner: str = ""
    next_action: str = ""
    next_action_at: str = ""
    source_first: str = ""
    source_last: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    leads_count: int = 0
    bookings_count: int = 0
    chats_count: int = 0
    voice_calls_count: int = 0


class CRMContactListItem(BaseModel):
    id: str
    name: str = ""
    email: str = ""
    phone: str = ""
    status: str = "nuevo"
    tags: List[str] = Field(default_factory=list)
    owner: str = ""
    next_action: str = ""
    next_action_at: str = ""
    source_first: str = ""
    source_last: str = ""
    last_seen_at: str = ""
    created_at: str = ""
    leads_count: int = 0
    bookings_count: int = 0
    chats_count: int = 0
    voice_calls_count: int = 0


class CRMContactsListResponse(BaseModel):
    items: List[CRMContactListItem]
    total: int
    page: int
    page_size: int
    pages: int = 0


class CRMContactActivity(BaseModel):
    kind: str
    reference_id: str = ""
    title: str = ""
    detail: str = ""
    status: str = ""
    occurred_at: str = ""
    source: str = ""


class CRMContactDetailResponse(BaseModel):
    contact: CRMContactPublic
    activity: List[CRMContactActivity] = Field(default_factory=list)


class ChannelEmailStatus(BaseModel):
    provider: str = "vantelia_smtp"
    fallback_enabled: bool = True
    connected: bool = False
    account_email: str = ""
    account_name: str = ""
    status: str = "not_connected"
    last_error: str = ""
    google_configured: bool = False


class ChannelSmsStatus(BaseModel):
    mode: str = "vantelia_default"
    sender: str = ""
    sender_status: str = "not_configured"
    available: bool = False
    last_error: str = ""


class ChannelSettingsResponse(BaseModel):
    email: ChannelEmailStatus
    sms: ChannelSmsStatus


class ChannelConnectResponse(BaseModel):
    url: str


class ChannelEmailSettingsPayload(BaseModel):
    provider: str = Field(default="vantelia_smtp", max_length=40)
    fallback_enabled: bool = True


class ChannelSmsSettingsPayload(BaseModel):
    mode: str = Field(default="vantelia_default", max_length=40)
    sender: str = Field(default="", max_length=32)


class ChannelTestPayload(BaseModel):
    target: str = Field(min_length=3, max_length=320)
    audit: List[Dict[str, Any]] = Field(default_factory=list)


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
    widget_enabled: Optional[bool] = None


class AppVoiceResponse(BaseModel):
    ok: bool = True
    cliente_id: str
    enabled: bool = False
    twilio_phone_number: str = ""
    openai_voice: str = ""
    webhook_url: str = ""
    plan_allows_voice: bool = False
    widget_enabled: bool = False
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


class BookingPaymentStateResponse(BaseModel):
    booking_id: str
    payment_required: bool = False
    payment_optional: bool = False
    payment_status: str = "not_required"
    amount_cents: int = 0
    currency: str = "eur"
    checkout_url: str = ""


class GmailClientStateResponse(BaseModel):
    configured: bool = False
    connected: bool = False
    email: str = ""
    status: str = "not_connected"
    last_error: str = ""
    smtp_fallback: bool = False


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
    portal_role: str = "owner"
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
    payment_status: str = ""
    payment_amount_cents: int = 0
    payment_checkout_url: str = ""
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
    location_id: str = Field(default="", max_length=64)


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
    location_id: str = ""
    allows_all_services: bool = True
    bookings_today: int = 0
    bookings_upcoming: int = 0
    blocks: List[PortalAgendaBlock] = Field(default_factory=list)


class PortalEmployeesResponse(BaseModel):
    items: List[PortalEmployeePublic]


class PortalLocationPayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    address: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=60)
    timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=80)
    is_active: bool = True
    whatsapp_phone_number_id: str = Field(default="", max_length=60)
    voice_phone_number: str = Field(default="", max_length=40)


class PortalLocationPublic(BaseModel):
    location_id: str
    cliente_id: str
    name: str
    address: str = ""
    phone: str = ""
    timezone: str = DEFAULT_TIMEZONE
    is_active: bool = True
    is_default: bool = False
    sort_order: int = 0
    employee_count: int = 0
    resource_count: int = 0
    whatsapp_phone_number_id: str = ""
    voice_phone_number: str = ""


class PortalLocationsResponse(BaseModel):
    items: List[PortalLocationPublic]


class ServiceLocationOverridePayload(BaseModel):
    is_available: bool = True
    price_cents: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=600)


class ServiceLocationOverrideItem(BaseModel):
    location_id: str
    location_name: str = ""
    is_default_location: bool = False
    is_available: bool = True
    has_override: bool = False
    price_cents: Optional[int] = None
    duration_minutes: Optional[int] = None
    effective_price_cents: int = 0
    effective_price_label: str = ""
    effective_duration_minutes: int = 0


class ServiceLocationsResponse(BaseModel):
    service_slug: str
    items: List[ServiceLocationOverrideItem]


class PortalResourcePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_active: bool = True


class PortalResourcePublic(BaseModel):
    resource_id: str
    cliente_id: str
    location_id: str
    name: str
    is_active: bool = True
    sort_order: int = 0


class PortalResourcesResponse(BaseModel):
    items: List[PortalResourcePublic]


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


class OutreachAutopilotSendPayload(BaseModel):
    max: int = 10
    send: bool = True
    delay: float = 70.0
    jitter: float = 25.0
    days: int = 60
    limit: int = 120
    apply_status: bool = False


class OutreachCampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=180)
    stage: str = "cold"
    emails: List[str] = Field(default_factory=list)
    delay: float = 70.0
    jitter: float = 25.0
    force_window: bool = False


class OutreachCampaignPatch(BaseModel):
    status: Optional[str] = None
    name: Optional[str] = None


class OutreachDiscoverRequest(BaseModel):
    sector: str = Field(..., min_length=2)
    ciudad: str = Field(..., min_length=2)
    max: int = 30
    extract_emails: bool = True
    import_direct: bool = False
    source: str = Field(default="auto", pattern="^(auto|places|osm)$")


class OutreachManualEmailPayload(BaseModel):
    recipient: EmailStr
    subject: str = Field(..., min_length=1, max_length=180)
    text: str = Field(default="", max_length=50000)
    html: str = Field(default="", max_length=200000)
    css: str = Field(default="", max_length=50000)


class OutreachPreflightRequest(BaseModel):
    stage: str = "cold"
    emails: List[str] = Field(default_factory=list)
    max: int = 20
    after_days: int = 4


class OutreachProspectIn(BaseModel):
    email: EmailStr
    business_name: str = Field(..., min_length=1, max_length=200)
    contact_name: str = ""
    niche: str = ""
    website: str = ""
    service_hint: str = ""
    city: str = ""
    phone: str = ""
    tags: str = ""
    source: str = "manual"
    status: str = "new"
    notes: str = ""
    score: int = 0


class OutreachProspectPatch(BaseModel):
    business_name: Optional[str] = None
    contact_name: Optional[str] = None
    niche: Optional[str] = None
    website: Optional[str] = None
    service_hint: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    tags: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    score: Optional[int] = None


class OutreachReplyPayload(BaseModel):
    email: EmailStr
    stage: str = ""
    note: str = ""


class OutreachSendRequest(BaseModel):
    stage: str = "cold"
    campaign_name: str = ""
    max: int = 20
    dry_run: bool = True
    test_to: str = ""
    email: str = ""
    emails: List[str] = Field(default_factory=list)
    after_days: int = 4
    delay: float = 70.0
    jitter: float = 25.0
    force_window: bool = False
    autopilot: bool = False


class OutreachSuppressRequest(BaseModel):
    email: EmailStr
    reason: str = "manual"


class OutreachTemplateOverride(BaseModel):
    stage: str
    subject_pool: str = ""
    body_text: str = ""
    body_html: str = ""


# ---------------------------------------------------------------------------
# Comercio del portal (F4): productos, bonos y tarjetas regalo
# ---------------------------------------------------------------------------


class ProductPayload(BaseModel):
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=600)
    price_cents: int = Field(default=0, ge=0, le=10_000_000)
    stock: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    is_active: bool = True


class ProductSalePayload(BaseModel):
    qty: int = Field(default=1, ge=1, le=999)
    booking_id: str = Field(default="", max_length=80)
    customer_name: str = Field(default="", max_length=120)
    customer_email: str = Field(default="", max_length=200)
    payment_method: str = Field(default="cash", max_length=20)
    location_id: str = Field(default="", max_length=64)
    notes: str = Field(default="", max_length=500)


class PosItemPayload(BaseModel):
    product_id: str = Field(min_length=1, max_length=80)
    qty: int = Field(default=1, ge=1, le=999)


class PosChargePayload(BaseModel):
    items: List[PosItemPayload] = Field(default_factory=list)
    booking_id: str = Field(default="", max_length=80)
    customer_name: str = Field(default="", max_length=120)
    customer_email: str = Field(default="", max_length=200)


class PosChargeResponse(BaseModel):
    payment_id: str
    url: str = ""
    amount_cents: int = 0
    currency: str = "eur"
    status: str = "pending"
    qr_svg: str = ""


class PosChargeStatusResponse(BaseModel):
    payment_id: str
    status: str = "pending"
    amount_cents: int = 0
    paid: bool = False
    url: str = ""


class PackageItemPayload(BaseModel):
    service_slug: str = Field(min_length=1, max_length=120)
    qty: int = Field(default=1, ge=1, le=100)


class PackagePayload(BaseModel):
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=600)
    items: List[PackageItemPayload] = Field(default_factory=list)
    price_cents: int = Field(default=0, ge=0, le=10_000_000)
    validity_days: int = Field(default=365, ge=1, le=3650)
    is_active: bool = True


class PackageSellPayload(BaseModel):
    buyer_name: str = Field(default="", max_length=120)
    buyer_email: str = Field(default="", max_length=200)
    buyer_phone: str = Field(default="", max_length=40)
    payment_method: str = Field(default="cash", max_length=20)
    location_id: str = Field(default="", max_length=64)


class PackageRedeemPayload(BaseModel):
    booking_id: str = Field(min_length=3, max_length=80)


class GiftCardIssuePayload(BaseModel):
    amount_cents: int = Field(ge=100, le=10_000_000)
    buyer_name: str = Field(default="", max_length=120)
    buyer_email: str = Field(default="", max_length=200)
    recipient_name: str = Field(default="", max_length=120)
    recipient_email: str = Field(default="", max_length=200)
    validity_days: int = Field(default=0, ge=0, le=3650)
    location_id: str = Field(default="", max_length=64)
    notes: str = Field(default="", max_length=500)


class GiftCardRedeemPayload(BaseModel):
    code: str = Field(min_length=4, max_length=20)
    booking_id: str = Field(min_length=3, max_length=80)
    amount_cents: Optional[int] = Field(default=None, ge=1, le=10_000_000)


class GiftCardStatusPayload(BaseModel):
    enabled: bool = True


class PortalTeamMemberPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)
    portal_role: str = Field(default="staff", pattern="^(owner|manager|staff)$")


class PortalTeamMemberUpdatePayload(BaseModel):
    display_name: str = Field(default="", max_length=120)
    portal_role: str = Field(default="", pattern="^(owner|manager|staff)$|^$")
    is_active: Optional[bool] = None


class PortalPermissionItem(BaseModel):
    key: str
    module: str
    label: str
    owner_only: bool = False
    default: bool = False
    effective: bool = False
    override: str = "default"  # default | allow | deny


class PortalUserPermissionsResponse(BaseModel):
    user_id: str
    portal_role: str
    is_owner: bool = False
    items: List[PortalPermissionItem] = Field(default_factory=list)


class PortalPermissionUpdatePayload(BaseModel):
    # Mapa permiso -> "default" | "allow" | "deny"
    overrides: Dict[str, str] = Field(default_factory=dict)
