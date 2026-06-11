from __future__ import annotations

import sys as _sys

# Refactor F3: si api se reimporta con otro entorno (fixtures de tests hacen
# sys.modules.pop("api") + import), purgar backend.* para que los modulos del
# paquete relean el entorno igual que lo hace este archivo. En produccion
# (primer import) es un no-op.
for _stale in [_m for _m in list(_sys.modules) if _m == "backend" or _m.startswith("backend.")]:
    del _sys.modules[_stale]

import asyncio
import base64
import copy
import csv
import hmac
import hashlib
import json
import logging
import os
import random
import re
import secrets
import shutil
import sqlite3
import smtplib
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
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

try:
    import stripe as _stripe_module
    stripe: Any = _stripe_module
except ImportError:
    stripe = None
from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
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
from onboarding_utils import run_onboarding, slugify_company, normalize_url as normalize_onboarding_url

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo


from backend import settings
from backend.settings import (  # noqa: F401  (transicion F3: copias re-exportadas)
    BASE_DIR,
    DATA_DIR,
    STORAGE_DIR,
    WIDGET_DIR,
    ADMIN_UI_DIR,
    ACCESS_UI_DIR,
    ONBOARDING_UI_DIR,
    APP_UI_DIR,
    BRAND_DIR,
    LEGAL_DIR,
    CONFIG_PATH,
    DB_PATH,
    BOOKING_SENTINEL,
    SESSION_ID_PATTERN,
    CLIENT_ID_PATTERN,
    TIME_PATTERN,
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    AVAILABLE_CHAT_MODELS_BOOT,
    DEFAULT_TIMEZONE,
    SESSION_TTL_SECONDS,
    MAX_MESSAGES_PER_SESSION,
    CHAT_RATE_LIMIT,
    BOOKING_RATE_LIMIT,
    MAX_BOOKING_ADVANCE_DAYS,
    RATE_LIMIT_WINDOW_SECONDS,
    PORTAL_BOOKINGS_PAGE_CAP,
    PORTAL_BOOKINGS_RANGE_CAP,
    PORTAL_BOOKINGS_RANGE_MAX_SPAN_DAYS,
    logger,
    OPENAI_API_KEY,
    ADMIN_API_TOKEN,
    WEBHOOK_DEFAULT,
    WHATSAPP_VERIFY_TOKEN,
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_APP_SECRET,
    WHATSAPP_API_VERSION,
    WHATSAPP_DEFAULT_CLIENT_ID,
    WHATSAPP_PHONE_CLIENT_MAP,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_DEFAULT_PHONE_NUMBER,
    TWILIO_SMS_SENDER,
    VOICE_MAX_DURATION_SECONDS,
    VOICE_OPENAI_VOICE,
    VOICE_REALTIME_MODEL,
    DEMO_VOICE_MAX_SECONDS,
    DEMO_VOICE_RATE_LIMIT,
    APP_VOICE_RATE_LIMIT,
    RAW_EXTRA_CORS_ORIGINS,
    APP_BASE_URL,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    ALLOWED_VANTELIA_SENDER_EMAILS,
    DEFAULT_VANTELIA_FROM_EMAIL,
    DEFAULT_VANTELIA_SUPPORT_EMAIL,
    _allowed_vantelia_email,
    SMTP_FROM_EMAIL,
    SMTP_FROM_NAME,
    SMTP_REPLY_TO,
    SMTP_STARTTLS,
    EMAIL_SEND_PROVIDER,
    GMAIL_TOKEN_ENCRYPTION_KEY,
    REMINDER_24H_HOURS,
    REMINDER_2H_HOURS,
    REMINDER_RUN_INTERVAL_MINUTES,
    BOOKING_AUTO_COMPLETE_HOURS,
    MANAGE_TOKEN_VALID_DAYS_AFTER_DATE,
    PASSWORD_RESET_TOKEN_HOURS,
    PASSWORD_RESET_RESEND_SECONDS,
    PORTAL_COOKIE_NAME,
    ADMIN_RETURN_COOKIE_NAME,
    PORTAL_COOKIE_DOMAIN,
    PORTAL_SESSION_HOURS,
    PORTAL_ADMIN_EMAIL,
    PORTAL_ADMIN_PASSWORD,
    PORTAL_ADMIN_NAME,
    MARKETING_SITE_URL,
    PORTAL_SUPPORT_EMAIL,
    CONSULTA_NOTIFICATION_EMAIL,
    SIGNUP_ENABLED,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    GOOGLE_GMAIL_REDIRECT_URI,
    GOOGLE_OAUTH_AUTHORIZE_URL,
    GOOGLE_OAUTH_TOKEN_URL,
    GOOGLE_OAUTH_USERINFO_URL,
    GOOGLE_GMAIL_SEND_URL,
    GOOGLE_GMAIL_SCOPES,
    GOOGLE_OAUTH_REVOKE_URL,
    GOOGLE_GMAIL_CLIENT_ID,
    GOOGLE_GMAIL_CLIENT_SECRET,
    GOOGLE_GMAIL_REDIRECT_URL,
    OAUTH_TOKEN_ENCRYPTION_KEY,
    GOOGLE_GMAIL_SEND_SCOPE,
    DEFAULT_FREE_QUOTA,
    ONBOARDING_MAX_PAGES_DEFAULT,
    BASE_STARTERS,
    MAX_EXTRA_STARTERS,
    MAX_TOTAL_STARTERS,
    BASE_STARTERS_LOWER,
    _strip_base_from_extras,
    _resolve_widget_starters,
    PLAN_DEFAULT,
    _PLAN_LEGACY_ALIASES,
    _normalize_plan_slug,
    STRIPE_SECRET_KEY,
    STRIPE_PUBLISHABLE_KEY,
    STRIPE_WEBHOOK_SECRET,
    STRIPE_CONNECT_WEBHOOK_SECRET,
    STRIPE_CONNECT_API_VERSION,
    STRIPE_CONNECT_BASE_URL,
    STRIPE_CONNECT_COUNTRY,
    BOOKING_PAYMENT_EXPIRY_MINUTES,
    STRIPE_CONNECT_CLIENT_ID,
    STRIPE_CONNECT_RETURN_URL,
    STRIPE_CONNECT_REFRESH_URL,
    STRIPE_PRICE_STARTER,
    STRIPE_PRICE_PRO,
    STRIPE_PRICE_BUSINESS,
    STRIPE_PRICE_STARTER_ANNUAL,
    STRIPE_PRICE_PRO_ANNUAL,
    STRIPE_PRICE_BUSINESS_ANNUAL,
    SELF_SERVE_PLANS,
    PLAN_VALID,
    PLAN_LIMITS,
    _self_serve_plan,
    DEFAULT_MESSAGE_TEMPLATES,
    DEFAULT_MESSAGE_TEMPLATE_ENABLED,
    DEFAULT_MESSAGE_TEMPLATE_CHANNELS,
    MESSAGE_KIND_ALIASES,
)


from backend.security import _channel_audit, _decrypt_channel_secret, _encrypt_channel_secret, _ensure_channel_settings  # noqa: F401
from backend.emailing import _channel_settings_public  # noqa: F401
from backend.security import _check_rate_limit, _enforce_allowed_origin  # noqa: F401
from backend import security
from backend.security import (  # noqa: F401  (transicion F3)
    ADMIN_IMPERSONATION_TTL_MINUTES,
    _OAUTH_STATE_TTL_SECONDS,
    _active_admin_count,
    _assert_admin_can_manage_user,
    _assign_client_user_to_cliente,
    _channel_fernet,
    _cleanup_auth_sessions,
    _cleanup_password_reset_tokens,
    _clear_admin_return_cookie,
    _clear_portal_cookie,
    _compound_token_parts,
    _consume_password_reset_token,
    _count_client_users,
    _create_auth_session,
    _create_impersonation_session,
    _create_password_reset_token,
    _create_user,
    _create_user_self_serve,
    _delete_auth_session,
    _delete_user,
    _delete_user_auth_sessions,
    _enforce_session_cookie_origin,
    _ensure_default_portal_admin,
    _get_authenticated_portal_user_or_none,
    _get_session_user,
    _get_user_by_email,
    _get_user_by_google_sub,
    _get_user_by_id,
    _gmail_fernet,
    _gmail_oauth_configured,
    _gmail_oauth_consume_state,
    _gmail_oauth_create_state,
    _gmail_redirect_uri,
    _google_oauth_configured,
    _hash_secret,
    _link_google_to_user,
    _list_users,
    _load_managed_user_or_404,
    _oauth_consume_state,
    _oauth_create_state,
    _password_reset_url,
    _period_start_iso_for_user,
    _platform_access_url,
    _redirect_for_role,
    _require_admin_token,
    _require_authenticated_admin_user,
    _require_authenticated_portal_user,
    _require_self_serve_user,
    _resolve_cliente_for_self_serve_user,
    _serialize_auth_user,
    _serialize_managed_user,
    _session_impersonator_email,
    _session_is_impersonated,
    _set_admin_return_cookie,
    _set_portal_cookie,
    _set_user_active,
    _update_user_password,
    _update_user_profile,
    _user_plan,
    _verify_secret,
)
from backend import emailing
from backend.emailing import _client_gmail_access_token, _client_gmail_connection, _email_delivery_configured, _email_sender, _gmail_access_token, _gmail_channel_configured, _gmail_channel_state_consume, _gmail_channel_state_create, _gmail_connected, _gmail_connection, _gmail_decrypt, _gmail_encrypt, _gmail_save_tokens, _gmail_send_message, _send_checkout_welcome_email, _send_client_email, _send_email_message, _send_email_object, _send_gmail_message, _send_password_reset_email, _send_payment_failed_emails, _smtp_configured, _smtp_send_message, send_client_email  # noqa: F401
from backend import messaging
from backend.messaging import _send_client_sms, _send_twilio_sms, _send_whatsapp_buttons, _send_whatsapp_list, _send_whatsapp_payload, _send_whatsapp_text, _twilio_request_valid, _voice_twilio_configured, _whatsapp_access_token_for_client, _whatsapp_chunks, _whatsapp_env_value  # noqa: F401
from backend.stripe_gateway import _save_connect_account  # noqa: F401
from backend import stripe_gateway
from backend.stripe_gateway import _STRIPE_SESSIONS_FILE, _STRIPE_SESSIONS_LOCK, _claim_stripe_session, _construct_stripe_webhook_event, _create_stripe_connected_account, _find_client_by_stripe_id, _load_stripe_sessions, _mark_stripe_session, _save_stripe_connected_account, _save_stripe_sessions, _stripe_configured, _stripe_connect_account_id, _stripe_connect_account_status, _stripe_connect_configured, _stripe_connect_display_name, _stripe_connect_headers, _stripe_connect_onboarding_url, _stripe_connect_request, _stripe_connect_requirement_count, _stripe_connected_account_row, _stripe_custom_field_values, _stripe_init, _stripe_onboarding_custom_fields, _stripe_price_for_plan  # noqa: F401
from backend.booking import _set_ai_send_enabled  # noqa: F401
from backend import booking
from backend.booking import BOOKING_CODE_RE, BOOKING_INTENT_PATTERNS, _BOOKING_CODE_ALPHABET, _ai_payment_delivery_available, _ai_payment_method_for_source, _ai_payment_sending_available, _ai_send_enabled_for_client, _ai_send_payment_link, _auto_complete_past_bookings, _auto_confirm_pending_bookings, _backfill_booking_codes, _booking_action_summary, _booking_admin_summary_from_row, _booking_audit_datetime_label, _booking_audit_entry_from_row, _booking_audit_source_label, _booking_blank_tracking_fields, _booking_conflicts_for_break_window, _booking_contact_matches, _booking_customer_phone_for_channel, _booking_datetime_display, _booking_due_for_reminder, _booking_email_bodies, _booking_email_enabled, _booking_email_kind_label, _booking_email_subject, _booking_manage_page, _booking_message_preview, _booking_message_text_for_channel, _booking_payment_after_store, _booking_payment_row, _booking_plan_unavailable_error, _booking_preview_context, _booking_public_detail_from_row, _booking_reminder_worker, _booking_row_manage_url, _booking_update_payload_from_reschedule, _build_booking_manage_url, _cancel_booking_by_code, _cancel_booking_core, _cancel_provider_booking, _connect_account_status, _count_bookings_this_month, _create_customer_payment_link, _create_provider_booking, _extract_booking_code_from_text, _generate_booking_code, _generate_manage_token, _get_booking_provider, _get_booking_row_by_code, _get_booking_row_by_id, _get_booking_row_by_token, _latest_booking_for_contact, _list_booking_audit_rows, _list_booking_rows, _load_booking_by_token_or_404, _load_booking_or_404, _lookup_and_verify_booking_by_code, _manage_token_still_valid, _mark_booking_email_result, _message_requests_booking_form, _message_requests_cancel_booking, _message_requests_payment, _message_requests_reschedule_booking, _normalize_message_kind, _payment_amount_for_booking, _payment_contact_for_booking, _payment_policy, _payment_public, _portal_booking_summary_from_row, _portal_bookings_effective_cap, _process_booking_management_message, _process_payment_request_message, _public_services_for_booking, _record_booking_audit, _reschedule_booking_by_code, _reschedule_provider_booking, _run_booking_reminders, _send_booking_email, _send_booking_email_by_kind, _send_booking_reminder_by_kind, _send_booking_sms_reminder, _send_booking_to_webhook, _send_booking_whatsapp_reminder, _serialize_booking_row, _store_booking, _unique_booking_code, _update_booking_details, _update_booking_record, create_booking_payment_checkout, process_booking_payment_expired_webhook, process_booking_payment_webhook, resolve_payment_requirement  # noqa: F401
from backend import demo_agenda
from backend.demo_agenda import DEMO_BOOKING_SOURCE, DEMO_EMPLOYEE_ID_PREFIX, DEMO_TENANT_PREFIX, DEMO_TTL_SECONDS, VOICE_DEMO_TEMPLATE, _DEMO_CUSTOMER_NAMES, _DEMO_FALLBACK_SERVICES, _DEMO_PROFESSIONALS, _build_demo_page, _create_demo_employees, _demo_registry_path, _demo_service_names, _demo_services, _is_bookable_demo_service, _load_demo_registry, _purge_demo_agenda, _purge_expired_demos, _register_demo_tenant, _save_demo_registry, _seed_demo_agenda, _sync_demo_bookings_for_service  # noqa: F401
from backend.agenda import _is_open_now  # noqa: F401
from backend import chat
from backend.chat import COMMERCIAL_INTENT_INSTRUCTIONS, GREETING_PATTERNS, MENU_OPTION_INSTRUCTIONS, MENU_OPTION_PATTERNS, MENU_RETURN_PATTERNS, _build_faq_response_from_panel, _build_intent_enhanced_message, _build_live_context_block, _build_main_menu_text, _detect_commercial_intent, _detect_menu_option, _emphasize_structured_headings, _main_menu_quick_actions, _message_is_greeting, _message_requests_menu, _process_chat_message  # noqa: F401
from backend import whatsapp
from backend.whatsapp import _app_whatsapp_response, _handle_whatsapp_message, _handle_whatsapp_webhook, _mark_whatsapp_message_if_new, _resolve_whatsapp_client_id, _verify_whatsapp_signature, _verify_whatsapp_webhook_challenge, _wa_clear_flow, _wa_create_booking, _wa_employees_for_service, _wa_flow_key, _wa_get_flow, _wa_main_menu_sections, _wa_reset_booking_fields, _wa_send_availability_overview, _wa_send_date_picker, _wa_send_employee_picker, _wa_send_main_menu, _wa_send_service_picker, _wa_send_time_picker, _whatsapp_phone_client_map, _whatsapp_public_booking_text, _whatsapp_session_id, _whatsapp_verify_token_for_client  # noqa: F401
from backend.chat import COMMERCIAL_INTENT_PATTERNS  # noqa: F401
from backend import onboarding
from backend.onboarding import _claim_cliente_id, _generate_unique_cliente_id, _provision_self_serve_cliente, _read_onboarding_state, _slugify_cliente_id, _unique_cliente_id, _write_onboarding_state  # noqa: F401
from backend.outreach import OUTREACH_DEFAULT_FOLLOWUP_DAYS  # noqa: F401
from backend import outreach
from backend.outreach import (  # noqa: F401  (aliases de scripts/)
    OUTREACH_AVAILABLE, OUTREACH_IMAP_AVAILABLE, outreach_imap_poll, OUTREACH_DEFAULT_DB,
    outreach_connect, outreach_smtp_settings, outreach_build_message, outreach_fetch_candidates,
    outreach_normalize_email, outreach_row_to_prospect, OUTREACH_STAGES, OutreachProspect,
    outreach_render, outreach_verify_token, outreach_apply_tracking, outreach_demo_url_with_utm,
)
from backend.outreach import OUTREACH_AUTONOMOUS_CHAIN_KEYWORDS, OUTREACH_AUTONOMOUS_GENERIC_PREFIXES, OUTREACH_AUTOPILOT_CITIES, OUTREACH_AUTOPILOT_SECTORS, OUTREACH_MAX_TOUCHES_PER_PROSPECT, OUTREACH_TRACKING_BASE_URL, OUTREACH_TRACKING_DISABLED, OUTREACH_TRACKING_SECRET, _TRACKING_ENABLED_EXPLICIT, _autonomous_company_score, _autonomous_email_is_personal, _autonomous_is_chain, _autonomous_within_window, _autopilot_config_row, _autopilot_generated_targets, _autopilot_log, _autopilot_target_companies, _autopilot_targets_for_run, _growth_automatic_outreach, _job_finish, _job_log, _manual_email_html_document, _mark_outreach_prospect_as_client_for_cliente, _outreach_action_for_item, _outreach_admin_preview_html, _outreach_autocapture_is_paused, _outreach_autonomous_tick, _outreach_autonomous_tick_inner, _outreach_autonomous_worker, _outreach_autopilot_gate, _outreach_autopilot_summary, _outreach_autopilot_worker, _outreach_backfill_orphan_send_campaigns, _outreach_campaign_metrics, _outreach_campaign_summary, _outreach_config_followup_days, _outreach_create_campaign, _outreach_db, _outreach_ensure_autopilot_config_columns, _outreach_filter_new_discoveries, _outreach_followup_body, _outreach_followup_item, _outreach_followup_stage_days, _outreach_followup_subject, _outreach_imap_worker, _outreach_next_stage, _outreach_norm_domain, _outreach_norm_phone, _outreach_norm_text, _outreach_normalize_followup_days, _outreach_now, _outreach_parse_dt, _outreach_pause_autocapture_for_smtp_limit, _outreach_preflight_auth_status, _outreach_prospect_from_row, _outreach_run_autonomous_tick_locked, _outreach_run_autopilot_job, _outreach_run_discovery_job, _outreach_run_send_job, _outreach_smtp_ratelimit_reason, _outreach_start_autonomous_tick, _outreach_tick_state_finish, _outreach_tick_state_snapshot, _outreach_tick_state_start, _outreach_tick_state_update, _outreach_unfilled_vars, outreach_autonomous_stop, outreach_autonomous_tick_lock, outreach_autonomous_tick_state_lock  # noqa: F401
from backend import instagram
from backend.instagram import (  # noqa: F401  (aliases de scripts/)
    IG_AVAILABLE, IG_REPLIES_AVAILABLE, ig_replies_poll, IG_DEFAULT_DB, ig_connect, IG_STAGES,
    ig_fetch_candidates, ig_create_draft, ig_upsert_profile, ig_is_autosend_enabled, ig_now_iso,
    IGProspect, ig_render, ig_deep_link, IGProfile, ig_discover_usernames, ig_normalize_username,
)
from backend.instagram import IG_STAGE_ALIASES, _ig_autopilot_run_once, _ig_autopilot_worker, _ig_campaign_create_draft, _ig_campaign_fetch_eligible_prospects, _ig_campaign_insert_candidates, _ig_campaign_migrate, _ig_campaign_render_dm, _ig_campaign_run_iteration, _ig_campaign_should_run, _ig_campaign_state, _ig_campaign_update, _ig_campaign_worker, _ig_dm_default, _ig_dm_templates_ensure, _ig_env_bool, _ig_followup_queue_items, _ig_in_window, _ig_next_followup, _ig_normalize_manual_stage, _ig_parse_ts, _ig_prospect_from_row, _ig_replies_worker, _ig_resolve_username, _ig_row_dict, _ig_stage_from_history, _instagram_db, _instagram_db_path, _instagram_now, ig_autopilot_stop, ig_campaign_stop, ig_replies_stop  # noqa: F401
from backend import tiktok
from backend.tiktok import TK_AVAILABLE, TK_DEFAULT_DB, _tk_campaign_iteration, _tk_campaign_state, _tk_campaign_update, _tk_campaign_worker, _tk_create_draft, _tk_db, _tk_dm_default, _tk_env_bool, _tk_fetch_eligible_prospects, _tk_insert_candidates, _tk_last_autosend_error, _tk_migrate, _tk_now, _tk_render_dm, _tk_resolve_username, _tk_row_dict, tk_campaign_stop, tk_is_autosend_enabled  # noqa: F401
from backend import wa_capture
from backend.wa_capture import wa_outreach, WA_AVAILABLE  # noqa: F401
from backend.wa_capture import _wa_autosend_enabled, _wa_send_lock, _wa_send_progress, _wa_session_info, _whatsapp_db  # noqa: F401
from backend import voice
from backend.voice import VOICE_BOOKING_KEYWORDS, _app_voice_response, _client_voice_plan_enabled, _get_voice_config, _mint_voice_session, _open_realtime_ws, _voice_booking_enabled, _voice_booking_tools, _voice_build_instructions, _voice_call_from_number, _voice_call_register, _voice_cancel_booking, _voice_check_availability, _voice_detect_booking_intent, _voice_dispatch_tool, _voice_dispatch_tool_demo, _voice_finalize_call, _voice_form_params, _voice_interruption_audio_end_ms, _voice_load_knowledge, _voice_lookup_and_verify_booking, _voice_pcmu_duration_ms, _voice_perform_booking, _voice_request_url, _voice_reschedule_booking, _voice_reset_assistant_playback, _voice_safe_close, _voice_send_payment_link, _voice_stats, _voice_stream_ws_url, _voice_summarize, _voice_truncate_interrupted_response, _voice_twiml_connect_stream, _voice_twiml_unavailable  # noqa: F401
from backend import growth
from backend.growth import GROWTH_STAGES, _growth_audit, _growth_daily_public, _growth_date, _growth_generate_review, _growth_metric_state, _growth_opportunity_public, _growth_overall_state, _growth_stage, _growth_states, _growth_summary  # noqa: F401
from backend import billing
from backend.billing import _build_plan_tiers, _build_subscription_public, _count_conversations_this_month, _create_client_from_public_checkout, _portal_user_for_checkout_client, _public_checkout_customer_details, _public_checkout_session_state, _refresh_subscription_from_stripe, _require_active_subscription, _require_pro_plan, _retrieve_public_checkout_session, _send_checkout_admin_notification, _serialize_billing_subscription, _set_client_subscription, _timestamp_to_iso  # noqa: F401
from backend import portal
from backend.portal import _ANALYTICS_ALLOWED_KEYS, _analytics_client_id, _client_payload_from_config, _compute_dashboard_stats, _config_from_admin_payload, _default_admin_payload, _is_admin_client_portal_override, _payload_from_alta_express, _portal_ai_config_from_client_config, _portal_client_id_or_403, _portal_stats_for_user, _portal_today_dashboard, _prepare_admin_payload, _record_analytics_event, _replace_services_section, _require_admin_identity, _safe_analytics_value, _save_admin_client_payload, _services_info_section, _try_record_analytics_event, _update_portal_ai_config  # noqa: F401
from backend import agenda
from backend.agenda import DEFAULT_EMPLOYEE_ROLE_LABEL, EMPLOYEE_COLOR_PALETTE, _active_booking_rows_for_day, _active_future_bookings_for_employee, _agenda_block_date_range, _agenda_block_reasons_for_day, _available_slots_for_day, _blocked_intervals, _blocked_slots, _booked_intervals, _booked_slots, _booking_catalog_service_row, _booking_conflict_items, _booking_conflict_message, _booking_conflicts_for_block, _booking_conflicts_for_break_windows, _booking_conflicts_for_closed_weekdays, _booking_display_service_meta, _booking_row_duration_min, _booking_slot_available, _booking_slot_available_for_reschedule, _booking_start_end, _break_intervals_from_windows, _build_slots_for_day, _catalog_services, _create_agenda_blocks, _create_portal_employee, _default_employee_name, _default_employee_row, _delete_agenda_block, _delete_portal_employee, _employee_booking_counters, _employee_closed_weekdays_from_row, _employee_defaults_for_client, _employee_schedule_from_row, _employee_service_ids_from_row, _employee_slot_sets_for_day, _ensure_default_employees_for_all_clients, _ensure_services_seeded, _extract_services_from_info, _find_service_by_name, _get_employee_row, _get_service_row, _interval_overlaps, _list_agenda_blocks, _list_employee_rows, _list_public_employee_rows, _list_service_rows, _normalize_closed_weekdays_list, _normalize_employee_color, _normalize_service_id, _normalize_service_ids_for_client, _portal_employees_for_client, _portal_schedule_from_config, _portal_schedule_from_employee, _public_slot_sets_for_day, _reminder_channel_availability, _resolve_employee_for_booking, _resolve_public_booking_employee, _sample_booking_preview_slot, _schedule_conflict_detail, _schedule_preview_payload_from_config, _serialize_agenda_block, _serialize_portal_employee, _service_duration_minutes, _service_map_for_client, _service_match_key, _service_name_allowed_for_employee, _service_row_to_public, _services_count, _services_for_employee, _update_client_schedule, _update_employee_schedule, _update_portal_employee, _validate_booking_window, _validate_employee_payload  # noqa: F401
from backend.rag import _kb_row_to_public  # noqa: F401
from backend import rag
from backend.rag import AUTO_QA_MAX_PAIRS, AVAILABILITY_INTENT_PATTERNS, QA_USE_INFO_MARKER, _AUTO_QA_BAD_TEXT_RE, _AUTO_QA_QUESTION_START_RE, _FAQ_SECTION_RE, _KB_QA_BLOCK_MARKER, _QA_MATCH_PUNCT_RE, _answer_is_info_txt_instruction, _autocreate_qa_from_info, _availability_dates_from_message, _availability_snapshot_for_day, _availability_time_period, _booking_disabled_availability_answer, _build_availability_context, _build_chat_availability_answer, _build_system_prompt, _canonical_knowledge_url, _chat_message_from_row, _chat_session_summary_from_row, _cleanup_orphan_starter_qa, _cleanup_sessions, _client_data_dir, _client_info_path, _client_qa_pairs_for_chat, _day_unavailable_explanation, _ensure_chat_session_record, _extract_faq_pairs_from_info, _find_next_available_snapshot, _format_slot_lines, _gen_qa_from_info_heuristic, _generate_starter_questions, _get_or_create_session, _info_path, _invalidate_client_runtime, _list_chat_session_rows, _load_chat_message_rows, _load_chat_session_or_404, _looks_like_auto_qa_pair, _match_qa_answer, _maybe_regenerate_info_with_qa, _message_is_only_holiday_query, _message_requests_availability, _message_requests_week_availability, _message_requests_weekend_availability, _normalize_for_qa_match, _normalize_session_id, _portal_brain_for_client, _qa_row_to_public, _read_info, _read_info_txt, _record_chat_message, _seed_qa_from_onboarding, _setup_llama_index, _slot_matches_period, _update_portal_brain, _vacation_blocks_summary, _write_info, _write_info_txt, cargar_indice  # noqa: F401
from backend.crm import _crm_backfill_client, _crm_contact_activity, _crm_contact_filters, _crm_contact_list_item, _crm_contact_or_404, _crm_contact_public, _crm_contacts_query, _crm_json_list, _lead_row_to_public  # noqa: F401
from backend import crm
from backend.crm import CRM_CONTACT_STATUSES, CRM_STATUS_PRIORITY, _crm_audit, _crm_link, _crm_search_text, _crm_upsert_contact, _normalize_crm_email, _normalize_crm_phone, _normalize_crm_search, _normalize_phone_for_match  # noqa: F401
from backend import appstate
from backend.appstate import (  # noqa: F401  (clases: excepcion permitida)
    ProviderBookingResult,
    SessionState,
    WAFlowState,
)


from backend.timeutils import _expires_at_in_hours, _from_utc_iso  # noqa: F401
from backend import timeutils
from backend.timeutils import (  # noqa: F401  (transicion F3)
    _session_expires_at,
    _to_utc_iso,
    _utc_now,
    _utc_now_iso,
)
from backend.textnorm import _configured_public_base_url, _forwarded_header_value, _normalize_email, _preferred_public_base_url, _public_base_url, _request_origin, _strip_origin  # noqa: F401
from backend.textnorm import _format_price_cents, _parse_date, _parse_duration_minutes_text, _parse_price_to_cents, _parse_time, _time_to_min  # noqa: F401
from backend.textnorm import DAY_LABELS_ES, MONTH_LABELS_ES, MONTH_NAMES_ES, WEEKDAY_NAMES_ES, _format_date_es, _resolve_relative_date_es, _safe_json_list, _strip_accents  # noqa: F401
from backend.textnorm import _assert_valid_client_id, _brand_asset_public_path, _extract_date_from_text, _extract_email_from_text, _extract_phone_from_text, _extract_time_from_text, _object_get  # noqa: F401
from backend.textnorm import EMAIL_RE  # noqa: F401
from backend import textnorm
from backend.textnorm import (  # noqa: F401  (transicion F3)
    EXTRA_CORS_ORIGINS,
    VOICE_ALLOWED_OPENAI_VOICES,
    _break_window_values,
    _ensure_path_within,
    _first_break_pair,
    _normalize_break_window,
    _normalize_break_windows,
    _normalize_chat_response_text,
    _normalize_message_template_channels,
    _normalize_message_template_enabled,
    _normalize_message_templates,
    _normalize_optional_http_url,
    _normalize_optional_time_value,
    _normalize_origin_value,
    _normalize_required_time_value,
    _normalize_voice_config,
    _sanitize_text,
    _voice_default_greeting,
)


from backend.clients import _client_plan, _client_subscription, _plan_limits  # noqa: F401
from backend.clients import _get_client_config  # noqa: F401
from backend.clients import _plan_feature  # noqa: F401
from backend.clients import _client_booking_plan_enabled  # noqa: F401
from backend.clients import _build_install_snippet, _current_billing_period, _delete_client_everywhere  # noqa: F401
from backend.clients import _require_plan_feature  # noqa: F401
from backend import clients
from backend.clients import (  # noqa: F401  (transicion F3)
    _collect_cors_origins,
    _load_client_configs,
    _normalize_client_config,
    _persist_configs_to_disk,
    _serialize_client_config,
    _sync_clientes_table_after_persist,
    _sync_clientes_table_from_config,
    _update_runtime_configs,
    _validate_runtime_config,
    _validate_single_client_runtime,
)
from backend import db
from backend.db import (  # noqa: F401  (transicion F3)
    _ensure_runtime_directories,
    _get_db_connection,
    _init_database,
    _maybe_reset_subscription_period,
    _subscription_period_start_now,
    db_check_self_serve_quota,
    db_ensure_free_subscription,
    db_get_client_owner,
    db_get_client_row,
    db_get_subscription_for_user,
    db_increment_message_usage,
    db_list_clientes_for_owner,
    db_set_client_owner,
    db_set_subscription_from_stripe,
    db_subscription_for_cliente,
)


























from backend import main
from backend.main import (  # noqa: F401  (transicion F3)
    app,
    _build_cors_headers,
    _ig_shutdown_workers,
    _ig_startup_workers,
    _no_cache_widget_bundle,
    _tk_shutdown_workers,
    _tk_startup_workers,
    _voice_startup_log,
    dynamic_cors_middleware,
    security_headers_middleware,
    shutdown_background_services,
    startup_background_services,
)












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
_DEMO_SECTOR_DEFAULTS: Dict[str, tuple] = {
    "centro de masajes": ("Centro de masajes y bienestar.", "Masajes terapeuticos, relajantes y descontracturantes. Reserva de sesiones."),
    "clinica dental": ("Clinica dental.", "Revisiones, limpiezas, ortodoncia, implantes y estetica dental."),
    "clinica estetica": ("Centro de estetica y belleza.", "Tratamientos faciales, corporales y de belleza."),
    "fisioterapia": ("Clinica de fisioterapia.", "Fisioterapia, rehabilitacion y recuperacion de lesiones."),
    "peluqueria": ("Peluqueria y salon de belleza.", "Corte, color, peinado y tratamientos capilares."),
    "centro veterinario": ("Centro veterinario.", "Consultas, vacunaciones, cirugia y urgencias veterinarias."),
}














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


@app.post("/auth/login", response_model=AuthLoginResponse)
async def auth_login(data: AuthLoginPayload, request: Request) -> Response:
    client_ip = request.client.host if request.client else "unknown"
    email_norm = _normalize_email(data.email)
    _check_rate_limit(f"login-ip:{client_ip}", 10)
    _check_rate_limit(f"login-email:{email_norm}", 5)
    user = _get_user_by_email(data.email)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ninguna cuenta con ese correo.")
    if not _verify_secret(data.password, user["password_hash"]):
        if (user["google_sub"] or "").strip() and (user["signup_source"] or "").strip().lower() == "google":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esta cuenta se creo con Google. Inicia sesion usando Google.",
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Contraseña incorrecta.")

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
    _clear_admin_return_cookie(response)
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
    _clear_admin_return_cookie(response)
    return response


# --- Vantelia 2.0 self-serve auth (Sem 2) ---

@app.post("/auth/signup", response_model=AuthSignupResponse)
async def auth_signup(data: AuthSignupPayload, request: Request) -> Response:
    if not SIGNUP_ENABLED:
        raise HTTPException(status_code=403, detail="Registro deshabilitado.")
    email_norm = _normalize_email(data.email)
    if _get_user_by_email(email_norm):
        raise HTTPException(status_code=409, detail="Ese email ya tiene cuenta. Inicia sesion.")
    new_user = _create_user_self_serve(
        email=email_norm,
        password=data.password,
        display_name=data.display_name,
        signup_source="email",
        email_verified=False,
    )
    # Optional: bridge from /demo/{cliente_id} CTA → claim that bot.
    redirect_to = "/onboarding"
    if data.claim:
        try:
            _claim_cliente_id(data.claim, new_user["id"], source="claim_demo")
            redirect_to = "/app"
            new_user = _get_user_by_id(new_user["id"])
        except HTTPException as claim_exc:
            logger.info("Signup claim %s rechazado: %s", data.claim, claim_exc.detail)
    raw_token = _create_auth_session(new_user["id"])
    payload = AuthSignupResponse(
        ok=True,
        user=_serialize_auth_user(new_user),
        redirect_to=redirect_to,
    )
    _try_record_analytics_event(
        {
            "event": "selfserve_signup",
            "event_source": "vantelia_app",
            "signup_source": "email",
            "user_id": new_user["id"],
            "widget_client_id": new_user["cliente_id"] or "",
            "cliente_id": new_user["cliente_id"] or "",
            "status": "claimed" if redirect_to == "/app" else "new",
        },
        request,
    )
    _try_record_analytics_event(
        {
            "event": "signup_completed",
            "event_source": "vantelia_app",
            "signup_source": "email",
            "user_id": new_user["id"],
            "widget_client_id": new_user["cliente_id"] or "",
            "cliente_id": new_user["cliente_id"] or "",
            "status": "claimed" if redirect_to == "/app" else "new",
        },
        request,
    )
    response = JSONResponse(payload.model_dump())
    _set_portal_cookie(response, raw_token)
    return response


@app.get("/auth/google/start", include_in_schema=False)
async def auth_google_start(intent: str = "login", claim: str = "") -> Response:
    if not _google_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth no esta configurado.")
    intent_norm = intent if intent in {"login", "signup"} else "login"
    claim_norm = (claim or "").strip()
    if claim_norm and not CLIENT_ID_PATTERN.match(claim_norm):
        claim_norm = ""
    state = _oauth_create_state(intent=intent_norm, claim=claim_norm)
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    return RedirectResponse(f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{query}")


@app.get("/auth/google/callback", include_in_schema=False)
async def auth_google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> Response:
    if not _google_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth no esta configurado.")
    if error:
        return RedirectResponse(f"/acceso?google_error={quote(error)}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Faltan code o state.")
    state_payload = _oauth_consume_state(state)
    if not state_payload:
        return RedirectResponse("/acceso?google_error=state_expired")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            access_token = token_data.get("access_token", "")
            if not access_token:
                raise HTTPException(status_code=502, detail="Google no devolvio access_token.")
            userinfo_resp = await client.get(
                GOOGLE_OAUTH_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            info = userinfo_resp.json()
    except httpx.HTTPError as exc:
        logger.error("Google OAuth fallo: %s", exc)
        raise HTTPException(status_code=502, detail="No se pudo verificar con Google.") from exc

    google_sub = str(info.get("sub", "")).strip()
    email = _normalize_email(info.get("email", ""))
    name = str(info.get("name", "") or info.get("given_name", "") or email.split("@")[0])
    picture = str(info.get("picture", ""))
    if not google_sub or not email:
        raise HTTPException(status_code=400, detail="Google no devolvio identificadores.")

    user = _get_user_by_google_sub(google_sub) or _get_user_by_email(email)
    created_google_user = False
    if user and not user["google_sub"]:
        return RedirectResponse("/acceso?google_error=email_account")
    if not user:
        if not SIGNUP_ENABLED:
            return RedirectResponse("/acceso?google_error=signup_disabled")
        user = _create_user_self_serve(
            email=email,
            display_name=name,
            google_sub=google_sub,
            avatar_url=picture,
            signup_source="google",
            email_verified=True,
        )
        created_google_user = True

    with _get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (_utc_now_iso(), user["id"]),
        )
        connection.commit()

    # Apply pending demo claim (carried through OAuth state from /signup?claim=...).
    claim_token = (state_payload.get("claim") or "").strip() if state_payload else ""
    if claim_token:
        try:
            _claim_cliente_id(claim_token, user["id"], source="claim_demo")
        except HTTPException as claim_exc:
            logger.info("Google OAuth claim %s rechazado: %s", claim_token, claim_exc.detail)

    raw_token = _create_auth_session(user["id"])
    # Decide redirect: if user has no cliente_id provisioned, send to onboarding.
    fresh = _get_user_by_id(user["id"])
    redirect_target = "/onboarding" if not (fresh and fresh["cliente_id"]) else "/app"
    response = RedirectResponse(redirect_target)
    _set_portal_cookie(response, raw_token)
    if created_google_user:
        _try_record_analytics_event(
            {
                "event": "signup_completed",
                "event_source": "vantelia_app",
                "signup_source": "google",
                "user_id": user["id"],
                "widget_client_id": (fresh["cliente_id"] if fresh else "") or "",
                "cliente_id": (fresh["cliente_id"] if fresh else "") or "",
                "status": "claimed" if redirect_target == "/app" else "new",
            },
            request,
        )
    return response


@app.get("/admin/email-channels/status", dependencies=[Depends(_require_admin_token)])
async def admin_email_channels_status() -> Dict[str, Any]:
    row = _gmail_connection()
    gmail_ready = _gmail_oauth_configured() and _gmail_connected()
    if EMAIL_SEND_PROVIDER == "gmail":
        active_provider = "gmail" if gmail_ready else "none"
    elif EMAIL_SEND_PROVIDER == "smtp":
        active_provider = "smtp" if _smtp_configured() else "none"
    else:
        active_provider = "gmail" if gmail_ready else "smtp" if _smtp_configured() else "none"
    return {
        "provider": EMAIL_SEND_PROVIDER,
        "active_provider": active_provider,
        "gmail": {
            "configured": _gmail_oauth_configured(),
            "connected": bool(row and row["refresh_token_encrypted"]),
            "email": row["email"] if row else "",
            "scopes": (row["scopes"] if row else "").split(),
            "updated_at": row["updated_at"] if row else "",
            "last_used_at": row["last_used_at"] if row else "",
            "last_error": row["last_error"] if row else "",
            "redirect_uri": _gmail_redirect_uri(),
        },
        "smtp": {
            "configured": _smtp_configured(),
            "from_email": SMTP_FROM_EMAIL if _smtp_configured() else "",
        },
    }


@app.get("/admin/email-channels/gmail/connect", include_in_schema=False)
async def admin_email_channels_gmail_connect(
    identity: Dict[str, str] = Depends(_require_admin_identity),
) -> Response:
    if not _gmail_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Configura Google OAuth, GOOGLE_GMAIL_REDIRECT_URI y la clave de cifrado antes de conectar Gmail.",
        )
    state = _gmail_oauth_create_state(identity.get("user_id", ""))
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": _gmail_redirect_uri(),
        "response_type": "code",
        "scope": GOOGLE_GMAIL_SCOPES,
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent select_account",
    }
    return RedirectResponse(f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


@app.get("/auth/google/gmail/callback", include_in_schema=False)
async def auth_google_gmail_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> Response:
    if error:
        return RedirectResponse(f"/dashboard?gmail_error={quote(error)}")
    state_payload = _gmail_oauth_consume_state(state or "")
    if not state_payload:
        return RedirectResponse("/dashboard?gmail_error=state_expired")
    if not code:
        return RedirectResponse("/dashboard?gmail_error=missing_code")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_response = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": _gmail_redirect_uri(),
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            token_data = token_response.json()
            access_token = str(token_data.get("access_token") or "")
            if not access_token:
                raise RuntimeError("Google no devolvio access_token.")
            userinfo_response = await client.get(
                GOOGLE_OAUTH_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_response.raise_for_status()
            email = _normalize_email(userinfo_response.json().get("email", ""))
        if not email:
            raise RuntimeError("Google no devolvio el email de la cuenta.")
        target_cliente_id = str(state_payload.get("cliente_id") or "")
        _gmail_save_tokens(
            token_data,
            email,
            str(token_data.get("scope") or GOOGLE_GMAIL_SCOPES),
            target_cliente_id,
        )
    except Exception as exc:
        logger.error("Conexion Gmail fallo: %s", exc)
        return RedirectResponse(f"/dashboard?gmail_error={quote(str(exc)[:160])}")
    return RedirectResponse("/app?gmail_connected=1" if state_payload.get("cliente_id") else "/dashboard?gmail_connected=1")


@app.delete("/admin/email-channels/gmail", dependencies=[Depends(_require_admin_token)])
async def admin_email_channels_gmail_disconnect() -> Dict[str, Any]:
    row = _gmail_connection()
    if row and row["refresh_token_encrypted"]:
        try:
            refresh_token = _gmail_decrypt(row["refresh_token_encrypted"])
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post("https://oauth2.googleapis.com/revoke", params={"token": refresh_token})
        except Exception as exc:
            logger.warning("No se pudo revocar Gmail en Google; se eliminara la conexion local: %s", exc)
    with _get_db_connection() as connection:
        connection.execute("DELETE FROM gmail_connections WHERE id = 'default'")
        connection.commit()
    return {"ok": True}


@app.get("/auth/app/email-channel", response_model=GmailClientStateResponse)
async def app_email_channel_state(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> GmailClientStateResponse:
    cliente_id = str(user["cliente_id"] or "")
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Tu usuario no tiene un negocio asociado.")
    row = _gmail_connection(cliente_id)
    connected = bool(row and row["refresh_token_encrypted"])
    return GmailClientStateResponse(
        configured=_gmail_oauth_configured(),
        connected=connected,
        email=row["email"] if row else "",
        status="reconnect_required" if row and row["last_error"] else "active" if connected else "not_connected",
        last_error=row["last_error"] if row else "",
        smtp_fallback=_smtp_configured(),
    )


@app.get("/auth/app/email-channel/gmail/connect", include_in_schema=False)
async def app_email_channel_gmail_connect(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Response:
    if _session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Accion bloqueada en sesion de admin (impersonacion).")
    cliente_id = str(user["cliente_id"] or "")
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Tu usuario no tiene un negocio asociado.")
    if not _gmail_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth para Gmail no esta configurado.")
    state = _gmail_oauth_create_state(user["id"], cliente_id)
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": _gmail_redirect_uri(),
        "response_type": "code",
        "scope": GOOGLE_GMAIL_SCOPES,
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent select_account",
    }
    return RedirectResponse(f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


@app.delete("/auth/app/email-channel/gmail")
async def app_email_channel_gmail_disconnect(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Dict[str, Any]:
    if _session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Accion bloqueada en sesion de admin (impersonacion).")
    cliente_id = str(user["cliente_id"] or "")
    row = _gmail_connection(cliente_id)
    if row and row["refresh_token_encrypted"]:
        try:
            refresh_token = _gmail_decrypt(row["refresh_token_encrypted"])
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post("https://oauth2.googleapis.com/revoke", params={"token": refresh_token})
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo revocar Gmail cliente=%s: %s", cliente_id, exc)
    with _get_db_connection() as connection:
        connection.execute("DELETE FROM gmail_connections WHERE id = ?", (cliente_id,))
        connection.commit()
    return {"ok": True}


# --- Vantelia 2.0 wizard onboarding (Sem 2) ---



@app.get("/onboarding/state", response_model=OnboardingStateResponse)
async def onboarding_state(
    user: sqlite3.Row = Depends(_require_self_serve_user),
) -> OnboardingStateResponse:
    cliente_id = (user["cliente_id"] or "").strip()
    if not cliente_id:
        return OnboardingStateResponse(step="name")
    state = _read_onboarding_state(cliente_id)
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    info_path = DATA_DIR / cliente_id / "info.txt"
    has_kb = info_path.exists() and info_path.stat().st_size > 200
    return OnboardingStateResponse(
        cliente_id=cliente_id,
        nombre=cfg.get("nombre", ""),
        website_url=state.get("website_url", ""),
        step=state.get("step", "learn"),
        bienvenida=cfg.get("bienvenida", ""),
        prompt_extra=cfg.get("prompt_extra", ""),
        starter_questions=state.get("starter_questions", []) or [],
        has_kb=has_kb,
    )


@app.post("/onboarding/start", response_model=OnboardingStartResponse)
async def onboarding_start(
    data: OnboardingStartPayload,
    request: Request,
    user: sqlite3.Row = Depends(_require_self_serve_user),
) -> OnboardingStartResponse:
    existing_cliente = (user["cliente_id"] or "").strip()
    if existing_cliente and existing_cliente in appstate.CONFIG_CLIENTES:
        # already provisioned; reuse and bounce wizard step forward
        state = _read_onboarding_state(existing_cliente)
        return OnboardingStartResponse(
            cliente_id=existing_cliente,
            nombre=appstate.CONFIG_CLIENTES[existing_cliente].get("nombre", ""),
            step=state.get("step", "learn"),
        )
    cliente_id = _provision_self_serve_cliente(owner_user_id=user["id"], nombre=data.nombre)
    _try_record_analytics_event(
        {
            "event": "bot_created",
            "event_source": "vantelia_app",
            "widget_client_id": cliente_id,
            "cliente_id": cliente_id,
            "user_id": user["id"],
            "bot_name": data.nombre,
            "source": "self_serve",
        },
        request,
    )
    return OnboardingStartResponse(cliente_id=cliente_id, nombre=data.nombre, step="learn")


@app.post("/onboarding/learn", response_model=OnboardingLearnResponse)
async def onboarding_learn(
    data: OnboardingLearnPayload,
    user: sqlite3.Row = Depends(_require_self_serve_user),
) -> OnboardingLearnResponse:
    cliente_id = (user["cliente_id"] or "").strip()
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Inicia el wizard primero (paso name).")
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY no configurada en el servidor.")
    if not data.website_url:
        raise HTTPException(status_code=400, detail="Por ahora solo se soporta URL de web.")

    try:
        max_pages = 1 if data.just_this_page else min(data.max_paginas, ONBOARDING_MAX_PAGES_DEFAULT)
        result = run_onboarding(
            website_url=data.website_url,
            api_key=OPENAI_API_KEY,
            nombre_bot=appstate.CONFIG_CLIENTES.get(cliente_id, {}).get("nombre", cliente_id),
            tono=data.tono,
            idioma=data.idioma,
            max_paginas=max_pages,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Onboarding learn fallo para %s: %s", cliente_id, exc)
        raise HTTPException(status_code=502, detail=f"No se pudo analizar la web: {exc}") from exc

    cliente_data_dir = DATA_DIR / cliente_id
    cliente_data_dir.mkdir(parents=True, exist_ok=True)
    (cliente_data_dir / "info.txt").write_text(result.info_txt, encoding="utf-8")

    try:
        explicit_pairs = list(getattr(result, "faq_pairs", []) or [])
        faq_source = str(getattr(result, "faq_source", "") or "").lower()
        _autocreate_qa_from_info(
            cliente_id,
            result.info_txt,
            user["id"],
            explicit_pairs=explicit_pairs,
            max_pairs=AUTO_QA_MAX_PAIRS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Auto-Q&A en onboarding fallo para %s: %s", cliente_id, exc)

    # update config with detected business name + allowed origin
    try:
        parsed = urlparse(data.website_url)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    except Exception:  # noqa: BLE001
        origin = ""
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        if result.detected_business_name and not cfg.get("nombre"):
            cfg["nombre"] = result.detected_business_name
        if origin and origin not in cfg.get("allowed_origins", []):
            cfg.setdefault("allowed_origins", []).append(origin)
        cfg["bienvenida"] = cfg.get("bienvenida") or result.suggested_welcome
        next_configs[cliente_id] = cfg
        _update_runtime_configs(next_configs)
    _persist_configs_to_disk(next_configs)

    # invalidate llama-index cache so next chat reindexes
    try:
        with appstate.state_lock:
            appstate.indices.pop(cliente_id, None)
    except NameError:
        pass

    # No generamos preguntas sugeridas con IA: el widget muestra las 3 fijas y
    # solo anade las extras que el cliente escriba manualmente.
    starters: List[str] = []
    suggested_prompt_extra = (
        "Habla con tono profesional y cercano. Responde solo con informacion del negocio. "
        "Si no sabes algo, ofrece contactar con el equipo humano."
    )
    state = _read_onboarding_state(cliente_id)
    state.update({
        "step": "personality",
        "website_url": data.website_url,
        "tono": data.tono,
        "idioma": data.idioma,
        "starter_questions": starters,
        "suggested_prompt_extra": suggested_prompt_extra,
        "learned_at": _utc_now_iso(),
    })
    _write_onboarding_state(cliente_id, state)
    return OnboardingLearnResponse(
        ok=True,
        cliente_id=cliente_id,
        detected_business_name=result.detected_business_name,
        info_excerpt=result.info_txt[:1200],
        suggested_welcome=result.suggested_welcome,
        suggested_prompt_extra=suggested_prompt_extra,
        suggested_starters=starters,
        pages_indexed=len(result.links),
    )


@app.post("/onboarding/personality", response_model=OnboardingPersonalityResponse)
async def onboarding_personality(
    data: OnboardingPersonalityPayload,
    user: sqlite3.Row = Depends(_require_self_serve_user),
) -> OnboardingPersonalityResponse:
    cliente_id = (user["cliente_id"] or "").strip()
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Inicia el wizard primero.")
    sanitized = [
        _sanitize_text(q)[:140] for q in (data.starter_questions or []) if _sanitize_text(q)
    ]
    cleaned_starters = _strip_base_from_extras(sanitized)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        cfg["bienvenida"] = _sanitize_text(data.bienvenida, allow_multiline=True)[:600]
        cfg["prompt_extra"] = _sanitize_text(data.prompt_extra, allow_multiline=True)[:4000]
        cfg["starter_questions"] = cleaned_starters
        next_configs[cliente_id] = cfg
        _update_runtime_configs(next_configs)
    _persist_configs_to_disk(next_configs)
    state = _read_onboarding_state(cliente_id)
    state.update({"step": "try", "starter_questions": cleaned_starters})
    _write_onboarding_state(cliente_id, state)
    return OnboardingPersonalityResponse(
        ok=True,
        cliente_id=cliente_id,
        bienvenida=cfg["bienvenida"],
        prompt_extra=cfg["prompt_extra"],
        starter_questions=cleaned_starters,
    )


@app.post("/onboarding/finalize", response_model=OnboardingFinalizeResponse)
async def onboarding_finalize(
    request: Request,
    user: sqlite3.Row = Depends(_require_self_serve_user),
) -> OnboardingFinalizeResponse:
    cliente_id = (user["cliente_id"] or "").strip()
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Inicia el wizard primero.")
    assets = _build_install_snippet(cliente_id, request)
    api_base = assets["api_base_url"]
    share_link = f"{api_base}/demo/{cliente_id}"
    state = _read_onboarding_state(cliente_id)
    state.update({"step": "use", "finalized_at": _utc_now_iso()})
    _write_onboarding_state(cliente_id, state)
    return OnboardingFinalizeResponse(
        ok=True,
        cliente_id=cliente_id,
        install_snippet=assets["install_snippet"],
        widget_script_url=assets["widget_script_url"],
        demo_url=assets["demo_url"],
        share_link=share_link,
        dashboard_url=f"{api_base}/app",
    )


@app.post("/auth/password/change", response_model=AuthSimpleResponse)
async def auth_change_password(
    data: AuthPasswordChangePayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Response:
    if _session_is_impersonated(user):
        raise HTTPException(
            status_code=403,
            detail="Acción bloqueada en sesión de admin (impersonación). Cierra la sesión admin para cambiar la contraseña.",
        )
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
    if not _email_delivery_configured():
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
    install_assets = _build_install_snippet(target_client_id, request) if target_client_id else {}
    return PortalDashboardResponse(
        user=_serialize_auth_user(user),
        stats=_portal_stats_for_user(user, target_client_id),
        bookings_upcoming=[_portal_booking_summary_from_row(row, request) for row in bookings],
        bookings_today=today_bookings,
        today_blocks=today_blocks,
        install_snippet=install_assets.get("install_snippet", ""),
        widget_script_url=install_assets.get("widget_script_url", ""),
        api_base_url=install_assets.get("api_base_url", ""),
        demo_url=install_assets.get("demo_url", ""),
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
    date_from_clean = date_from.strip()
    date_to_clean = date_to.strip()
    cap = _portal_bookings_effective_cap(date_from_clean, date_to_clean)
    effective_limit = max(1, min(limit, cap))
    rows, total = _list_booking_rows(
        cliente_id=target_client_id,
        employee_id=employee_id.strip(),
        status_filter=estado.strip(),
        search=q.strip(),
        date_from=date_from_clean,
        date_to=date_to_clean,
        limit=effective_limit,
        offset=max(0, offset),
        scope=normalized_scope,
    )
    return PortalBookingsResponse(
        items=[_portal_booking_summary_from_row(row, request) for row in rows],
        total=total,
        limit=effective_limit,
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
    if target_client_id and not _is_admin_client_portal_override(user, cliente_id):
        _require_plan_feature(
            target_client_id,
            "csv_export",
            "La exportacion CSV esta disponible desde el plan Starter.",
        )
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


# --- Vantelia 2.0 dashboard endpoints (Sem 3) ---







@app.get("/auth/app/overview", response_model=AppOverviewResponse)
async def app_overview(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppOverviewResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    sub_row = db_get_subscription_for_user(user["id"]) or db_ensure_free_subscription(user["id"], cliente_id=cliente_id)
    period_start = _period_start_iso_for_user(user["id"])
    stats = _compute_dashboard_stats(cliente_id, period_start)
    subscription = AppOverviewSubscription(
        plan=sub_row["plan"],
        status=sub_row["status"],
        messages_quota=int(sub_row["messages_quota"]),
        messages_used=int(sub_row["messages_used_period"]) or stats.messages_period,
        cancel_at_period_end=bool(sub_row["cancel_at_period_end"]),
        current_period_end=sub_row["current_period_end"] or "",
    )
    channels = AppOverviewChannels(
        web=True,
        whatsapp=bool(cfg.get("whatsapp", {}).get("enabled", False)),
        voice=bool(cfg.get("voice", {}).get("enabled", False)),
        booking=bool(cfg.get("booking", {}).get("enabled", False)),
    )
    return AppOverviewResponse(
        cliente_id=cliente_id,
        nombre=cfg.get("nombre", cliente_id),
        color=cfg.get("color", "#00b1d9"),
        icono=cfg.get("icono", "AI"),
        bienvenida=cfg.get("bienvenida", ""),
        subscription=subscription,
        stats=stats,
        channels=channels,
    )


@app.get("/auth/app/deploy", response_model=AppDeployResponse)
async def app_deploy(
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppDeployResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    assets = _build_install_snippet(cliente_id, request)
    api_base = assets["api_base_url"]
    share_link = f"{api_base}/demo/{cliente_id}"
    return AppDeployResponse(
        cliente_id=cliente_id,
        install_snippet=assets["install_snippet"],
        widget_script_url=assets["widget_script_url"],
        api_base_url=api_base,
        demo_url=assets["demo_url"],
        share_link=share_link,
        qr_data_url="",
    )


@app.post("/auth/app/track")
async def app_track_event(
    data: AppTrackEventPayload,
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Dict[str, Any]:
    cliente_id = (user["cliente_id"] or "").strip()
    allowed_events = {
        "bot_preview_message",
        "first_chat_tested",
        "snippet_copied",
        "share_link_copied",
        "demo_url_copied",
        "install_tab_opened",
        "pricing_viewed",
        "upgrade_clicked",
    }
    if data.event not in allowed_events:
        raise HTTPException(status_code=400, detail="Evento de app no permitido.")
    metadata = {
        key: value
        for key, value in (data.metadata or {}).items()
        if key in _ANALYTICS_ALLOWED_KEYS
    }
    payload: Dict[str, Any] = {
        "event": data.event,
        "event_source": "vantelia_app",
        "widget_client_id": cliente_id,
        "cliente_id": cliente_id,
        "user_id": user["id"],
        **metadata,
    }
    return _record_analytics_event(payload, request)


@app.get("/auth/app/appearance", response_model=AppAppearanceResponse)
async def app_appearance_get(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppAppearanceResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    state = _read_onboarding_state(cliente_id)
    launcher_shape = str(cfg.get("launcher_shape", "circle") or "circle").lower()
    if launcher_shape not in ("circle", "bar"):
        launcher_shape = "circle"
    try:
        launcher_size = int(cfg.get("launcher_size", 60) or 60)
    except (TypeError, ValueError):
        launcher_size = 60
    starters = cfg.get("starter_questions")
    if not starters:
        starters = state.get("starter_questions", []) or []
    return AppAppearanceResponse(
        ok=True,
        cliente_id=cliente_id,
        nombre=cfg.get("nombre", ""),
        color=cfg.get("color", "#00b1d9"),
        accent_color=cfg.get("accent_color", ""),
        icono=cfg.get("icono", "AI"),
        logo_url=cfg.get("logo_url", ""),
        launcher_shape=launcher_shape,
        launcher_size=launcher_size,
        bienvenida=cfg.get("bienvenida", ""),
        prompt_extra=cfg.get("prompt_extra", ""),
        starter_questions=list(starters),
        allowed_origins=list(cfg.get("allowed_origins", [])),
        booking_enabled=bool(cfg.get("booking", {}).get("enabled", True)),
    )


@app.post("/auth/app/appearance", response_model=AppAppearanceResponse)
async def app_appearance_post(
    data: AppAppearancePayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppAppearanceResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        if data.nombre is not None:
            cfg["nombre"] = _sanitize_text(data.nombre)[:120] or cliente_id
        if data.color is not None:
            color = _sanitize_text(data.color)
            if re.match(r"^#[0-9A-Fa-f]{6}$", color):
                cfg["color"] = color
        if data.accent_color is not None:
            ac = _sanitize_text(data.accent_color)
            cfg["accent_color"] = ac if (not ac or re.match(r"^#[0-9A-Fa-f]{6}$", ac)) else cfg.get("accent_color", "")
        if data.icono is not None:
            cfg["icono"] = _sanitize_text(data.icono)[:12] or "AI"
        if data.logo_url is not None:
            cfg["logo_url"] = _sanitize_text(data.logo_url)
        if data.launcher_shape is not None:
            shape = _sanitize_text(data.launcher_shape).lower()
            cfg["launcher_shape"] = shape if shape in ("circle", "bar") else "circle"
        if data.launcher_size is not None:
            try:
                size_val = int(data.launcher_size)
            except (TypeError, ValueError):
                size_val = 60
            current_shape = cfg.get("launcher_shape", "circle")
            if current_shape == "circle":
                cfg["launcher_size"] = max(48, min(96, size_val))
            else:
                cfg["launcher_size"] = max(120, min(280, size_val))
        if data.bienvenida is not None:
            cfg["bienvenida"] = _sanitize_text(data.bienvenida, allow_multiline=True)[:600]
        if data.prompt_extra is not None:
            cfg["prompt_extra"] = _sanitize_text(data.prompt_extra, allow_multiline=True)[:4000]
        if data.allowed_origins is not None:
            cleaned = []
            for origin in data.allowed_origins:
                normalized = _normalize_optional_http_url(origin)
                if normalized and normalized not in cleaned:
                    cleaned.append(normalized)
            cfg["allowed_origins"] = cleaned
        if data.starter_questions is not None:
            sanitized = [
                _sanitize_text(q)[:140] for q in data.starter_questions if _sanitize_text(q)
            ]
            cfg["starter_questions"] = _strip_base_from_extras(sanitized)
        if data.booking_enabled is not None:
            if not isinstance(cfg.get("booking"), dict):
                cfg["booking"] = {}
            cfg["booking"]["enabled"] = bool(data.booking_enabled)
        next_configs[cliente_id] = cfg
        _update_runtime_configs(next_configs)
    _persist_configs_to_disk(next_configs)
    if data.starter_questions is not None:
        state = _read_onboarding_state(cliente_id)
        state["starter_questions"] = cfg.get("starter_questions", [])
        _write_onboarding_state(cliente_id, state)
        try:
            _cleanup_orphan_starter_qa(cliente_id, cfg.get("starter_questions", []))
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo limpiar Q&A huerfanas de starters %s: %s", cliente_id, exc)
    # Invalidate llama-index cache and active sessions so the next chat rebuilds the prompt.
    try:
        with appstate.state_lock:
            appstate.indices.pop(cliente_id, None)
            stale = [sid for sid, s in appstate.sesiones.items() if s.cliente_id == cliente_id]
            for sid in stale:
                appstate.sesiones.pop(sid, None)
    except NameError:
        pass
    return await app_appearance_get(user)


# --- CRM ligero ------------------------------------------------------------

CRM_CONTACT_SORTS = {
    "last_activity_desc": "c.last_seen_at DESC, c.id DESC",
    "last_activity_asc": "c.last_seen_at ASC, c.id ASC",
    "created_desc": "c.created_at DESC, c.id DESC",
    "created_asc": "c.created_at ASC, c.id ASC",
    "name_asc": "c.name COLLATE NOCASE ASC, c.id ASC",
    "name_desc": "c.name COLLATE NOCASE DESC, c.id DESC",
    "next_action_asc": "CASE WHEN c.next_action_at = '' THEN 1 ELSE 0 END, c.next_action_at ASC, c.id ASC",
    "next_action_desc": "CASE WHEN c.next_action_at = '' THEN 1 ELSE 0 END, c.next_action_at DESC, c.id DESC",
}
































@app.get("/auth/app/contacts", response_model=CRMContactsListResponse)
async def app_contacts_list(
    page: int = 1,
    page_size: int = 50,
    q: str = "",
    status_filter: str = "",
    tag: str = "",
    owner: str = "",
    source: str = "",
    next_action_filter: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "last_activity_desc",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> CRMContactsListResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    _crm_backfill_client(cliente_id)
    page, page_size = max(1, page), max(1, min(page_size, 200))
    where, params = _crm_contact_filters(
        cliente_id, q=q, status_filter=status_filter, tag=tag, owner=owner, source=source,
        next_action_filter=next_action_filter, date_from=date_from, date_to=date_to,
    )
    order_by = CRM_CONTACT_SORTS.get(sort, CRM_CONTACT_SORTS["last_activity_desc"])
    with _get_db_connection() as connection:
        total = connection.execute(f"SELECT COUNT(*) FROM crm_contacts c WHERE {where}", tuple(params)).fetchone()[0]
        rows = _crm_contacts_query(
            connection, where, params, order_by=order_by,
            limit=page_size, offset=(page - 1) * page_size,
        )
        items = [_crm_contact_list_item(row) for row in rows]
    pages = (int(total or 0) + page_size - 1) // page_size
    return CRMContactsListResponse(items=items, total=int(total or 0), page=page, page_size=page_size, pages=pages)


@app.get("/auth/app/contacts/export.csv")
async def app_contacts_export(
    q: str = "",
    status_filter: str = "",
    tag: str = "",
    owner: str = "",
    source: str = "",
    next_action_filter: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "last_activity_desc",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Response:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    _crm_backfill_client(cliente_id)
    where, params = _crm_contact_filters(
        cliente_id, q=q, status_filter=status_filter, tag=tag, owner=owner, source=source,
        next_action_filter=next_action_filter, date_from=date_from, date_to=date_to,
    )
    order_by = CRM_CONTACT_SORTS.get(sort, CRM_CONTACT_SORTS["last_activity_desc"])
    with _get_db_connection() as connection:
        rows = connection.execute(
            f"SELECT c.* FROM crm_contacts c WHERE {where} ORDER BY {order_by}",
            tuple(params),
        ).fetchall()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "name", "email", "phone", "status", "tags", "owner", "source_first", "source_last",
        "next_action", "next_action_at", "last_seen_at", "created_at", "notes",
    ])
    for row in rows:
        writer.writerow([
            row["name"], row["email"], row["phone"], row["status"],
            ", ".join(_crm_json_list(row["tags_json"])), row["owner"], row["source_first"],
            row["source_last"], row["next_action"], row["next_action_at"], row["last_seen_at"],
            row["created_at"], (row["notes"] or "").replace("\r", " ").replace("\n", " "),
        ])
    filename = f"contactos_{cliente_id}_{_utc_now().strftime('%Y%m%d')}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/auth/app/contacts", response_model=CRMContactPublic)
async def app_contact_create(
    data: CRMContactPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> CRMContactPublic:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    contact_id = _crm_upsert_contact(
        cliente_id, name=data.name, email=data.email, phone=data.phone,
        source=data.source or "manual", status=data.status, actor=f"user:{user['id']}",
    )
    if not contact_id:
        raise HTTPException(status_code=400, detail="Indica al menos nombre, email o telefono.")
    return await app_contact_update(contact_id, data, user)


@app.put("/auth/app/contacts/{contact_id}", response_model=CRMContactPublic)
async def app_contact_update(
    contact_id: str,
    data: CRMContactPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> CRMContactPublic:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    status_value = data.status if data.status in CRM_CONTACT_STATUSES else "nuevo"
    tags = list(dict.fromkeys(_sanitize_text(tag)[:80] for tag in data.tags if _sanitize_text(tag)))[:30]
    email_norm, phone_norm = _normalize_crm_email(data.email), _normalize_crm_phone(data.phone)
    with _get_db_connection() as connection:
        _crm_contact_or_404(connection, cliente_id, contact_id)
        for column, value in (("email_normalized", email_norm), ("phone_normalized", phone_norm)):
            if value and connection.execute(
                f"SELECT 1 FROM crm_contacts WHERE cliente_id = ? AND {column} = ? AND id <> ? LIMIT 1",
                (cliente_id, value, contact_id),
            ).fetchone():
                raise HTTPException(status_code=409, detail="Ese email o telefono ya pertenece a otro contacto.")
        connection.execute(
            """
            UPDATE crm_contacts SET name=?, email=?, email_normalized=?, phone=?, phone_normalized=?, search_text=?,
                status=?, notes=?, tags_json=?, owner=?, next_action=?, next_action_at=?, updated_at=?
            WHERE id=? AND cliente_id=?
            """,
            (
                _sanitize_text(data.name)[:200], _sanitize_text(data.email)[:200], email_norm,
                _sanitize_text(data.phone)[:80], phone_norm, _crm_search_text(data.name, data.email, data.phone), status_value,
                _sanitize_text(data.notes, allow_multiline=True)[:8000], json.dumps(tags, ensure_ascii=False),
                _sanitize_text(data.owner)[:200], _sanitize_text(data.next_action)[:500],
                _sanitize_text(data.next_action_at)[:40], _utc_now_iso(), contact_id, cliente_id,
            ),
        )
        _crm_audit(connection, cliente_id, contact_id, "contact_updated", {"status": status_value}, actor=f"user:{user['id']}")
        connection.commit()
        row = _crm_contact_or_404(connection, cliente_id, contact_id)
        return _crm_contact_public(row, connection)


@app.get("/auth/app/contacts/{contact_id}", response_model=CRMContactDetailResponse)
async def app_contact_detail(
    contact_id: str,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> CRMContactDetailResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with _get_db_connection() as connection:
        row = _crm_contact_or_404(connection, cliente_id, contact_id)
        audit_rows = connection.execute(
            "SELECT event_type, actor, payload_json, created_at FROM crm_contact_audit WHERE cliente_id = ? AND contact_id = ? ORDER BY id DESC LIMIT 100",
            (cliente_id, contact_id),
        ).fetchall()
        audit = [
            {"event_type": item["event_type"], "actor": item["actor"], "payload": json.loads(item["payload_json"] or "{}"), "created_at": item["created_at"]}
            for item in audit_rows
        ]
        return CRMContactDetailResponse(
            contact=_crm_contact_public(row, connection),
            activity=_crm_contact_activity(connection, cliente_id, contact_id),
            audit=audit,
        )


# --- Pagos de clientes finales / Stripe Connect ----------------------------

PAYMENT_POLICY_MODES = {"none", "full", "deposit_fixed", "deposit_percent"}
PAYMENT_STATUSES = {"pending", "paid", "failed", "refunded", "partially_refunded"}






























@app.get("/auth/app/channels", response_model=ChannelSettingsResponse)
async def app_channels_get(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ChannelSettingsResponse:
    return _channel_settings_public(_resolve_cliente_for_self_serve_user(user))


@app.post("/auth/app/channels/email/settings", response_model=ChannelSettingsResponse)
async def app_channels_email_settings(
    data: ChannelEmailSettingsPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ChannelSettingsResponse:
    if data.provider not in {"vantelia_smtp", "gmail_oauth"}:
        raise HTTPException(status_code=400, detail="Proveedor de email no valido.")
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    if data.provider == "gmail_oauth" and not _client_gmail_connection(cliente_id):
        raise HTTPException(status_code=400, detail="Conecta primero una cuenta de Google.")
    _ensure_channel_settings(cliente_id)
    with _get_db_connection() as connection:
        connection.execute(
            "UPDATE client_channel_settings SET email_provider=?, email_fallback_enabled=?, updated_at=? WHERE cliente_id=?",
            (data.provider, int(data.fallback_enabled), _utc_now_iso(), cliente_id),
        )
        connection.commit()
    return _channel_settings_public(cliente_id)


@app.post("/auth/app/channels/email/google/connect", response_model=ChannelConnectResponse)
async def app_channels_google_connect(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ChannelConnectResponse:
    if not _gmail_channel_configured():
        raise HTTPException(status_code=503, detail="La conexion con Gmail no esta configurada.")
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    _ensure_channel_settings(cliente_id)
    state, verifier = _gmail_channel_state_create(cliente_id, user["id"])
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {
        "client_id": GOOGLE_GMAIL_CLIENT_ID,
        "redirect_uri": GOOGLE_GMAIL_REDIRECT_URL,
        "response_type": "code",
        "scope": f"openid email {GOOGLE_GMAIL_SEND_SCOPE}",
        "state": state,
        "access_type": "offline",
        "prompt": "consent select_account",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return ChannelConnectResponse(url=f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


@app.get("/auth/app/channels/email/google/callback", include_in_schema=False)
async def app_channels_google_callback(
    code: str = "", state: str = "", error: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> RedirectResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    if error:
        return RedirectResponse(url=f"/app?channels_error={quote(error)}", status_code=303)
    verifier = _gmail_channel_state_consume(state, cliente_id, user["id"])
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_response = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "code": code, "client_id": GOOGLE_GMAIL_CLIENT_ID,
                    "client_secret": GOOGLE_GMAIL_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_GMAIL_REDIRECT_URL,
                    "grant_type": "authorization_code", "code_verifier": verifier,
                },
            )
            token_response.raise_for_status()
            token = token_response.json()
            access_token = str(token.get("access_token", ""))
            info_response = await client.get(
                GOOGLE_OAUTH_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
            info_response.raise_for_status()
            info = info_response.json()
    except Exception as exc:  # noqa: BLE001
        _channel_audit(cliente_id, "email", "connect_failed", "gmail_oauth", False, str(exc))
        raise HTTPException(status_code=502, detail="No se pudo conectar la cuenta de Google.") from exc
    granted = set(str(token.get("scope", "")).split())
    if GOOGLE_GMAIL_SEND_SCOPE not in granted:
        raise HTTPException(status_code=400, detail="Google no concedio permiso para enviar correo.")
    now, expires = _utc_now_iso(), _utc_now() + timedelta(seconds=int(token.get("expires_in", 3600)))
    existing = _client_gmail_connection(cliente_id)
    refresh_token = str(token.get("refresh_token", "")) or (
        _decrypt_channel_secret(existing["refresh_token_encrypted"]) if existing else ""
    )
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_oauth_connections
                (cliente_id, provider, account_email, account_name, scopes_json,
                 access_token_encrypted, refresh_token_encrypted, expires_at, status, created_at, updated_at)
            VALUES (?, 'gmail_oauth', ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(cliente_id, provider) DO UPDATE SET
                account_email=excluded.account_email, account_name=excluded.account_name,
                scopes_json=excluded.scopes_json, access_token_encrypted=excluded.access_token_encrypted,
                refresh_token_encrypted=excluded.refresh_token_encrypted, expires_at=excluded.expires_at,
                status='active', last_error='', updated_at=excluded.updated_at
            """,
            (
                cliente_id, _normalize_email(info.get("email", "")), str(info.get("name", "")),
                json.dumps(sorted(granted)), _encrypt_channel_secret(access_token),
                _encrypt_channel_secret(refresh_token), expires.isoformat(), now, now,
            ),
        )
        connection.execute(
            "UPDATE client_channel_settings SET email_provider='gmail_oauth', updated_at=? WHERE cliente_id=?",
            (now, cliente_id),
        )
        connection.commit()
    _channel_audit(cliente_id, "email", "connected", "gmail_oauth", True)
    return RedirectResponse(url="/app?channels=connected", status_code=303)


@app.post("/auth/app/channels/email/google/disconnect", response_model=ChannelSettingsResponse)
async def app_channels_google_disconnect(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ChannelSettingsResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    gmail = _client_gmail_connection(cliente_id)
    if gmail and _gmail_channel_configured():
        try:
            token = (
                _decrypt_channel_secret(gmail["refresh_token_encrypted"])
                or _decrypt_channel_secret(gmail["access_token_encrypted"])
            )
            if token:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        GOOGLE_OAUTH_REVOKE_URL,
                        data={"token": token},
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
        except Exception:  # noqa: BLE001
            _channel_audit(
                cliente_id, "email", "revoke_failed", "gmail_oauth", False,
                "Google no confirmo la revocacion; la conexion local se elimino.",
            )
    with _get_db_connection() as connection:
        connection.execute(
            "DELETE FROM client_oauth_connections WHERE cliente_id=? AND provider='gmail_oauth'", (cliente_id,)
        )
        connection.execute(
            "UPDATE client_channel_settings SET email_provider='vantelia_smtp', updated_at=? WHERE cliente_id=?",
            (_utc_now_iso(), cliente_id),
        )
        connection.commit()
    _channel_audit(cliente_id, "email", "disconnected", "gmail_oauth", True)
    return _channel_settings_public(cliente_id)


@app.post("/auth/app/channels/email/test", response_model=AuthSimpleResponse)
async def app_channels_email_test(
    data: ChannelTestPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AuthSimpleResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    _check_rate_limit(f"channel-email-test:{cliente_id}", 3)
    target = _normalize_email(data.target)
    if not target:
        raise HTTPException(status_code=400, detail="Indica un email valido.")
    provider = _send_client_email(
        cliente_id, target, "Prueba de canal de Vantelia",
        "El canal de email de tu negocio esta configurado correctamente.",
    )
    return AuthSimpleResponse(ok=True, message=f"Correo de prueba enviado mediante {provider}.")


@app.post("/auth/app/channels/sms/settings", response_model=ChannelSettingsResponse)
async def app_channels_sms_settings(
    data: ChannelSmsSettingsPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ChannelSettingsResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    if data.mode not in {"vantelia_default", "twilio_alphanumeric_sender", "twilio_dedicated_number"}:
        raise HTTPException(status_code=400, detail="Modo SMS no valido.")
    settings = _ensure_channel_settings(cliente_id)
    sender, sender_status = "", "not_configured"
    if data.mode == "twilio_alphanumeric_sender":
        sender = data.sender.strip().upper()
        if not re.fullmatch(r"(?=.*[A-Z])[A-Z0-9 ]{3,11}", sender):
            raise HTTPException(status_code=400, detail="El Sender ID debe tener 3-11 caracteres y alguna letra.")
        sender_status = "pending_registration"
    elif data.mode == "twilio_dedicated_number":
        if settings["sms_mode"] != data.mode or settings["sms_sender_status"] != "active":
            raise HTTPException(status_code=400, detail="El numero dedicado debe provisionarlo soporte antes de activarlo.")
        sender, sender_status = settings["sms_sender"], "active"
    with _get_db_connection() as connection:
        connection.execute(
            """
            UPDATE client_channel_settings
            SET sms_mode=?, sms_sender=?, sms_sender_status=?, updated_at=?
            WHERE cliente_id=?
            """,
            (data.mode, sender, sender_status, _utc_now_iso(), cliente_id),
        )
        connection.commit()
    _channel_audit(cliente_id, "sms", "settings_updated", data.mode, True, sender_status)
    return _channel_settings_public(cliente_id)


@app.post("/auth/app/channels/sms/test", response_model=AuthSimpleResponse)
async def app_channels_sms_test(
    data: ChannelTestPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AuthSimpleResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    _check_rate_limit(f"channel-sms-test:{cliente_id}", 3)
    target = _booking_customer_phone_for_channel({"telefono": data.target}, "sms")
    if not target:
        raise HTTPException(status_code=400, detail="Indica un telefono valido.")
    if not await _send_client_sms(cliente_id, target, "Prueba de canal SMS de Vantelia."):
        raise HTTPException(status_code=502, detail="No se pudo enviar el SMS de prueba.")
    return AuthSimpleResponse(ok=True, message="SMS de prueba enviado.")


@app.get("/auth/app/payments/connect/status", response_model=ConnectAccountStatus)
async def app_connect_status(
    refresh: bool = False,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ConnectAccountStatus:
    return _connect_account_status(_resolve_cliente_for_self_serve_user(user), refresh=refresh)


@app.post("/auth/app/payments/ai-send", response_model=ConnectAccountStatus)
async def app_payments_ai_send_toggle(
    data: AiSendTogglePayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ConnectAccountStatus:
    """Opt-in del negocio: permite que la IA envie enlaces de pago en su nombre."""
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    _set_ai_send_enabled(cliente_id, data.enabled)
    return _connect_account_status(cliente_id)


@app.post("/auth/app/payments/connect/start", response_model=ConnectStartResponse)
async def app_connect_start(
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ConnectStartResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    if STRIPE_CONNECT_CLIENT_ID:
        state = _oauth_create_state("stripe_connect", f"{cliente_id}:{user['id']}")
        redirect_uri = STRIPE_CONNECT_RETURN_URL or f"{_public_base_url(request)}/auth/app/payments/connect/callback"
        url = "https://connect.stripe.com/oauth/authorize?" + urlencode({
            "response_type": "code", "client_id": STRIPE_CONNECT_CLIENT_ID,
            "scope": "read_write", "state": state, "redirect_uri": redirect_uri,
        })
        return ConnectStartResponse(url=url)

    _stripe_init()
    base_url = _public_base_url(request)
    try:
        with _get_db_connection() as connection:
            row = connection.execute(
                "SELECT stripe_account_id FROM client_payment_accounts WHERE cliente_id=?",
                (cliente_id,),
            ).fetchone()
        account_id = str(row["stripe_account_id"] or "") if row else ""
        if account_id:
            account = stripe.Account.retrieve(account_id)
        else:
            account = stripe.Account.create(
                type="standard",
                metadata={"vantelia_cliente_id": cliente_id},
            )
        account_id = _save_connect_account(cliente_id, account)
        account_link = stripe.AccountLink.create(
            account=account_id,
            refresh_url=STRIPE_CONNECT_REFRESH_URL or f"{base_url}/app?payments=refresh",
            return_url=f"{base_url}/app?payments=connected",
            type="account_onboarding",
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error iniciando Stripe Connect Onboarding para %s: %s", cliente_id, exc)
        if "signed up for Connect" in str(exc):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Stripe Connect aun no esta activado para Vantelia. "
                    "El administrador debe completar el perfil de plataforma en "
                    "https://dashboard.stripe.com/connect antes de conectar empresas."
                ),
            ) from exc
        raise HTTPException(status_code=502, detail="No se pudo iniciar Stripe Connect.") from exc
    return ConnectStartResponse(url=str(_object_get(account_link, "url", "") or ""))


@app.get("/auth/app/payments/connect/callback")
async def app_connect_callback(
    request: Request,
    code: str = "",
    state: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> RedirectResponse:
    state_data = _oauth_consume_state(state)
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    if not state_data or state_data["intent"] != "stripe_connect" or state_data["claim"] != f"{cliente_id}:{user['id']}":
        raise HTTPException(status_code=400, detail="Estado OAuth invalido o caducado.")
    if not code:
        raise HTTPException(status_code=400, detail="Stripe no devolvio un codigo de autorizacion.")
    _stripe_init()
    try:
        token = stripe.OAuth.token(grant_type="authorization_code", code=code)
        account_id = _object_get(token, "stripe_user_id", "")
        account = stripe.Account.retrieve(account_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="No se pudo conectar la cuenta Stripe.") from exc
    _save_connect_account(cliente_id, account)
    return RedirectResponse(url="/app?payments=connected", status_code=303)


@app.put("/auth/app/services/{service_id}/payment-policy", response_model=ServicePublic)
async def app_service_payment_policy(
    service_id: str,
    data: ServicePaymentPolicyPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ServicePublic:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    _ensure_services_seeded(cliente_id)
    service = _get_service_row(cliente_id, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    if data.mode not in PAYMENT_POLICY_MODES:
        raise HTTPException(status_code=400, detail="Politica de pago invalida.")
    if data.mode == "deposit_percent" and not 1 <= data.deposit_value <= 100:
        raise HTTPException(status_code=400, detail="El porcentaje debe estar entre 1 y 100.")
    now = _utc_now_iso()
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO service_payment_policies
                (cliente_id, service_id, mode, deposit_value, confirm_booking_on_paid, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id, service_id) DO UPDATE SET mode=excluded.mode,
                deposit_value=excluded.deposit_value, confirm_booking_on_paid=excluded.confirm_booking_on_paid,
                updated_at=excluded.updated_at
            """,
            (cliente_id, service_id, data.mode, data.deposit_value, int(data.confirm_booking_on_paid), now, now),
        )
        connection.commit()
    return ServicePublic(**_service_row_to_public(service))


@app.get("/auth/app/payments", response_model=CustomerPaymentsResponse)
async def app_customer_payments(
    booking_id: str = "", contact_id: str = "", limit: int = 100,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> CustomerPaymentsResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    clauses, params = ["cliente_id=?"], [cliente_id]
    if booking_id:
        clauses.append("booking_id=?"); params.append(booking_id)
    if contact_id:
        clauses.append("contact_id=?"); params.append(contact_id)
    with _get_db_connection() as connection:
        total = connection.execute(f"SELECT COUNT(*) FROM customer_payments WHERE {' AND '.join(clauses)}", tuple(params)).fetchone()[0]
        rows = connection.execute(
            f"SELECT * FROM customer_payments WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ?",
            (*params, max(1, min(limit, 500))),
        ).fetchall()
    return CustomerPaymentsResponse(items=[_payment_public(row) for row in rows], total=int(total or 0))




@app.post("/auth/app/bookings/{booking_id}/payment-link", response_model=PaymentLinkResponse)
async def app_booking_payment_link(
    booking_id: str,
    data: PaymentLinkPayload,
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PaymentLinkResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    booking = _load_booking_or_404(booking_id)
    if booking["cliente_id"] != cliente_id:
        raise HTTPException(status_code=404, detail="Cita no encontrada.")
    row = _create_customer_payment_link(
        cliente_id, booking, base_url=_public_base_url(request), override_cents=data.amount_cents
    )
    return PaymentLinkResponse(payment=_payment_public(row), checkout_url=row["checkout_url"])






@app.post("/auth/app/payments/{payment_id}/refund", response_model=CustomerPaymentPublic)
async def app_payment_refund(
    payment_id: str,
    data: PaymentRefundPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> CustomerPaymentPublic:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with _get_db_connection() as connection:
        payment = connection.execute(
            "SELECT * FROM customer_payments WHERE id=? AND cliente_id=?", (payment_id, cliente_id)
        ).fetchone()
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado.")
    if payment["status"] not in {"paid", "partially_refunded"} or not payment["stripe_payment_intent_id"]:
        raise HTTPException(status_code=409, detail="Este pago no se puede reembolsar.")
    kwargs: Dict[str, Any] = {
        "payment_intent": payment["stripe_payment_intent_id"],
        "stripe_account": payment["stripe_account_id"],
    }
    if data.amount_cents is not None:
        kwargs["amount"] = int(data.amount_cents)
    _stripe_init()
    try:
        stripe.Refund.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="No se pudo solicitar el reembolso.") from exc
    with _get_db_connection() as connection:
        row = connection.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
    return _payment_public(row)


# --- Sem 4: Leads ----------------------------------------------------------



@app.get("/auth/app/leads", response_model=AppLeadsListResponse)
async def app_leads_list(
    page: int = 1,
    page_size: int = 50,
    q: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppLeadsListResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    offset = (page - 1) * page_size
    q_clean = (q or "").strip()
    with _get_db_connection() as connection:
        if q_clean:
            like = f"%{q_clean.lower()}%"
            total = connection.execute(
                """
                SELECT COUNT(*) FROM bot_leads
                WHERE cliente_id = ?
                  AND (LOWER(name) LIKE ? OR LOWER(email) LIKE ? OR LOWER(phone) LIKE ? OR LOWER(message) LIKE ?)
                """,
                (cliente_id, like, like, like, like),
            ).fetchone()[0]
            rows = connection.execute(
                """
                SELECT * FROM bot_leads
                WHERE cliente_id = ?
                  AND (LOWER(name) LIKE ? OR LOWER(email) LIKE ? OR LOWER(phone) LIKE ? OR LOWER(message) LIKE ?)
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (cliente_id, like, like, like, like, page_size, offset),
            ).fetchall()
        else:
            total = connection.execute(
                "SELECT COUNT(*) FROM bot_leads WHERE cliente_id = ?", (cliente_id,)
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM bot_leads WHERE cliente_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (cliente_id, page_size, offset),
            ).fetchall()
    return AppLeadsListResponse(
        items=[_lead_row_to_public(r) for r in rows],
        total=int(total or 0),
        page=page,
        page_size=page_size,
    )


@app.post("/auth/app/leads", response_model=AppLeadPublic)
async def app_lead_create(
    data: AppLeadPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppLeadPublic:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    name = _sanitize_text(data.name)[:200]
    email = _sanitize_text(data.email)[:200]
    phone = _sanitize_text(data.phone)[:80]
    message = _sanitize_text(data.message, allow_multiline=True)[:4000]
    if not (name or email or phone or message):
        raise HTTPException(status_code=400, detail="Indica al menos nombre, email, telefono o mensaje.")
    lead_id = "lead_" + secrets.token_hex(10)
    now_iso = _utc_now_iso()
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO bot_leads
                (id, cliente_id, session_id, name, email, phone, message, source, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)
            """,
            (
                lead_id,
                cliente_id,
                _sanitize_text(data.session_id)[:200],
                name,
                email,
                phone,
                message,
                _sanitize_text(data.source)[:40] or "manual",
                now_iso,
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM bot_leads WHERE id = ?", (lead_id,)).fetchone()
    contact_id = _crm_upsert_contact(
        cliente_id,
        name=name,
        email=email,
        phone=phone,
        source=_sanitize_text(data.source)[:40] or "manual",
        status="interesado",
        entity_type="lead",
        entity_id=lead_id,
        actor=f"user:{user['id']}",
    )
    if contact_id and data.session_id:
        with _get_db_connection() as connection:
            _crm_link(connection, cliente_id, contact_id, "chat", _sanitize_text(data.session_id)[:200], "chat")
            connection.commit()
    return _lead_row_to_public(row)


@app.delete("/auth/app/leads/{lead_id}")
async def app_lead_delete(
    lead_id: str,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Dict[str, bool]:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with _get_db_connection() as connection:
        cur = connection.execute(
            "DELETE FROM bot_leads WHERE id = ? AND cliente_id = ?",
            (lead_id, cliente_id),
        )
        connection.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Lead no encontrado.")
    return {"ok": True}


@app.get("/auth/app/leads/export.csv")
async def app_leads_export(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Response:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with _get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM bot_leads WHERE cliente_id = ? ORDER BY created_at DESC",
            (cliente_id,),
        ).fetchall()
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["created_at", "name", "email", "phone", "message", "source", "session_id"])
    for r in rows:
        writer.writerow([
            r["created_at"], r["name"] or "", r["email"] or "", r["phone"] or "",
            (r["message"] or "").replace("\n", " ").replace("\r", " "),
            r["source"] or "", r["session_id"] or "",
        ])
    filename = f"leads_{cliente_id}_{_utc_now().strftime('%Y%m%d')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Sem 4: Q&A -------------------------------------------------------------



@app.get("/auth/app/qa", response_model=AppQAListResponse)
async def app_qa_list(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppQAListResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with _get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM kb_qa WHERE cliente_id = ? ORDER BY created_at DESC",
            (cliente_id,),
        ).fetchall()
    items = [_qa_row_to_public(r) for r in rows]
    return AppQAListResponse(items=items, total=len(items))


@app.post("/auth/app/qa", response_model=AppQAItem)
async def app_qa_create(
    data: AppQAPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppQAItem:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    qa_id = "qa_" + secrets.token_hex(10)
    now_iso = _utc_now_iso()
    tags = [_sanitize_text(t)[:40] for t in (data.tags or []) if _sanitize_text(t)][:10]
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO kb_qa (id, cliente_id, question, answer, tags_json,
                               created_at, updated_at, created_by_user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                qa_id,
                cliente_id,
                _sanitize_text(data.question, allow_multiline=True)[:400],
                _sanitize_text(data.answer, allow_multiline=True)[:4000],
                json.dumps(tags, ensure_ascii=False),
                now_iso,
                now_iso,
                user["id"],
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_qa WHERE id = ?", (qa_id,)).fetchone()
    _maybe_regenerate_info_with_qa(cliente_id)
    return _qa_row_to_public(row)


@app.patch("/auth/app/qa/{qa_id}", response_model=AppQAItem)
async def app_qa_update(
    qa_id: str,
    data: AppQAUpdatePayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppQAItem:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with _get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM kb_qa WHERE id = ? AND cliente_id = ?",
            (qa_id, cliente_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Q&A no encontrada.")
        next_q = _sanitize_text(data.question, allow_multiline=True)[:400] if data.question is not None else row["question"]
        next_a = _sanitize_text(data.answer, allow_multiline=True)[:4000] if data.answer is not None else row["answer"]
        if data.tags is not None:
            tags = [_sanitize_text(t)[:40] for t in data.tags if _sanitize_text(t)][:10]
            tags_json = json.dumps(tags, ensure_ascii=False)
        else:
            tags_json = row["tags_json"]
        connection.execute(
            "UPDATE kb_qa SET question = ?, answer = ?, tags_json = ?, updated_at = ? WHERE id = ?",
            (next_q, next_a, tags_json, _utc_now_iso(), qa_id),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_qa WHERE id = ?", (qa_id,)).fetchone()
    _maybe_regenerate_info_with_qa(cliente_id)
    return _qa_row_to_public(row)


@app.delete("/auth/app/qa/{qa_id}")
async def app_qa_delete(
    qa_id: str,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Dict[str, bool]:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with _get_db_connection() as connection:
        cur = connection.execute(
            "DELETE FROM kb_qa WHERE id = ? AND cliente_id = ?",
            (qa_id, cliente_id),
        )
        connection.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Q&A no encontrada.")
    _maybe_regenerate_info_with_qa(cliente_id)
    return {"ok": True}


# --- Sem 4: Knowledge (text snippets + URLs) -----------------------------

_KB_BLOCK_MARKER = "===== AÑADIDO DESDE PANEL ====="


























@app.get("/auth/app/knowledge", response_model=AppKnowledgeListResponse)
async def app_knowledge_list(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppKnowledgeListResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with _get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM kb_documents WHERE cliente_id = ? ORDER BY uploaded_at DESC",
            (cliente_id,),
        ).fetchall()
    info = _read_info(cliente_id)
    return AppKnowledgeListResponse(
        items=[_kb_row_to_public(r) for r in rows],
        info_chars=len(info),
        info_excerpt=info[:1200],
        info_full=info,
    )


@app.post("/auth/app/knowledge/text", response_model=AppKnowledgeItem)
async def app_knowledge_add_text(
    data: AppKnowledgeTextPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppKnowledgeItem:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    title = _sanitize_text(data.title)[:200] or "Nota manual"
    content = _sanitize_text(data.content, allow_multiline=True)[:20000]
    now_iso = _utc_now_iso()
    kb_id = "kb_" + secrets.token_hex(10)
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO kb_documents
                (id, cliente_id, filename, mime_type, size_bytes, sha256,
                 source, source_url, storage_path, indexed_at, uploaded_at, uploaded_by_user_id)
            VALUES (?, ?, ?, 'text/plain', ?, '', 'text', '', '', ?, ?, ?)
            """,
            (kb_id, cliente_id, title, len(content.encode("utf-8")), now_iso, now_iso, user["id"]),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_documents WHERE id = ?", (kb_id,)).fetchone()
    info = _read_info(cliente_id)
    block = f"\n\n{_KB_BLOCK_MARKER}\n[{title}]\n{content}\n"
    if _KB_QA_BLOCK_MARKER in info:
        before, after = info.split(_KB_QA_BLOCK_MARKER, 1)
        info = before.rstrip() + block + "\n" + _KB_QA_BLOCK_MARKER + after
    else:
        info = info.rstrip() + block
    _write_info(cliente_id, info)
    return _kb_row_to_public(row)


@app.post("/auth/app/knowledge/url", response_model=AppKnowledgeItem)
async def app_knowledge_add_url(
    data: AppKnowledgeUrlPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppKnowledgeItem:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    url = _sanitize_text(data.url)
    if not re.match(r"^https?://", url):
        raise HTTPException(status_code=400, detail="URL invalida (https:// requerido).")
    canonical_url = _canonical_knowledge_url(url)
    with _get_db_connection() as connection:
        existing_url_rows = connection.execute(
            """
            SELECT source_url
            FROM kb_documents
            WHERE cliente_id = ? AND source = 'url'
            """,
            (cliente_id,),
        ).fetchall()
    if any(_canonical_knowledge_url(row["source_url"] or "") == canonical_url for row in existing_url_rows):
        raise HTTPException(
            status_code=409,
            detail="Esta fuente ya esta añadida al conocimiento. Quita la fuente existente antes de volver a indexarla.",
        )
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY no configurada.")
    try:
        max_pages = 1 if data.just_this_page else ONBOARDING_MAX_PAGES_DEFAULT
        result = run_onboarding(
            website_url=canonical_url,
            api_key=OPENAI_API_KEY,
            nombre_bot=appstate.CONFIG_CLIENTES.get(cliente_id, {}).get("nombre", cliente_id),
            tono="Profesional y cercano",
            idioma="Espanol",
            max_paginas=max_pages,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("KB URL ingest fallo %s: %s", cliente_id, exc)
        raise HTTPException(status_code=502, detail=f"No se pudo analizar la URL: {exc}") from exc

    now_iso = _utc_now_iso()
    kb_id = "kb_" + secrets.token_hex(10)
    info_chars = len(result.info_txt.encode("utf-8"))
    stored_url = canonical_url
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO kb_documents
                (id, cliente_id, filename, mime_type, size_bytes, sha256,
                 source, source_url, storage_path, indexed_at, uploaded_at, uploaded_by_user_id)
            VALUES (?, ?, ?, 'text/html', ?, '', 'url', ?, '', ?, ?, ?)
            """,
            (
                kb_id, cliente_id,
                result.detected_business_name or stored_url,
                info_chars,
                stored_url,
                now_iso, now_iso, user["id"],
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM kb_documents WHERE id = ?", (kb_id,)).fetchone()

    if data.replace:
        new_info = result.info_txt
    else:
        existing = _read_info(cliente_id)
        block = f"\n\n{_KB_BLOCK_MARKER}\n[Web: {stored_url}]\n{result.info_txt}\n"
        if _KB_QA_BLOCK_MARKER in existing:
            before, after = existing.split(_KB_QA_BLOCK_MARKER, 1)
            new_info = before.rstrip() + block + "\n" + _KB_QA_BLOCK_MARKER + after
        else:
            new_info = existing.rstrip() + block
    _write_info(cliente_id, new_info)
    qa_created = 0
    try:
        explicit_pairs = list(getattr(result, "faq_pairs", []) or [])
        faq_source = str(getattr(result, "faq_source", "") or "").lower()
        qa_created = _autocreate_qa_from_info(
            cliente_id,
            result.info_txt,
            user["id"],
            explicit_pairs=explicit_pairs,
            max_pairs=AUTO_QA_MAX_PAIRS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Auto-Q&A extraction failed for %s: %s", cliente_id, exc)
    public = _kb_row_to_public(row)
    public.qa_created = qa_created
    return public


@app.delete("/auth/app/knowledge/{kb_id}")
async def app_knowledge_delete(
    kb_id: str,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Dict[str, bool]:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with _get_db_connection() as connection:
        cur = connection.execute(
            "DELETE FROM kb_documents WHERE id = ? AND cliente_id = ?",
            (kb_id, cliente_id),
        )
        connection.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Recurso no encontrado.")
    # NOTE: we intentionally do NOT auto-truncate info.txt — text was merged in
    # at ingest time and cannot be cleanly de-merged. User can use /reindex.
    return {"ok": True}


@app.post("/auth/app/knowledge/reindex", response_model=AppKnowledgeReindexResponse)
async def app_knowledge_reindex(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppKnowledgeReindexResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    try:
        with appstate.state_lock:
            appstate.indices.pop(cliente_id, None)
    except NameError:
        pass
    info = _read_info(cliente_id)
    return AppKnowledgeReindexResponse(ok=True, cliente_id=cliente_id, info_chars=len(info))


# --- Sem 4: Tune AI -------------------------------------------------------

AVAILABLE_CHAT_MODELS = AVAILABLE_CHAT_MODELS_BOOT


@app.get("/auth/app/tune", response_model=AppTuneResponse)
async def app_tune_get(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppTuneResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    cfg = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    return AppTuneResponse(
        cliente_id=cliente_id,
        prompt_extra=cfg.get("prompt_extra", ""),
        chat_model=cfg.get("chat_model", DEFAULT_CHAT_MODEL),
        temperature=float(cfg.get("temperature", 0.2)),
        available_models=AVAILABLE_CHAT_MODELS,
    )


@app.post("/auth/app/tune", response_model=AppTuneResponse)
async def app_tune_post(
    data: AppTunePayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppTuneResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        if data.prompt_extra is not None:
            cfg["prompt_extra"] = _sanitize_text(data.prompt_extra, allow_multiline=True)[:8000]
        if data.chat_model is not None and data.chat_model.strip() in AVAILABLE_CHAT_MODELS:
            cfg["chat_model"] = data.chat_model.strip()
        if data.temperature is not None:
            cfg["temperature"] = max(0.0, min(2.0, float(data.temperature)))
        next_configs[cliente_id] = cfg
        _update_runtime_configs(next_configs)
    _persist_configs_to_disk(next_configs)
    try:
        with appstate.state_lock:
            appstate.indices.pop(cliente_id, None)
    except NameError:
        pass
    return await app_tune_get(user)


@app.get("/auth/app/services", response_model=AppServicesResponse)
async def app_services_get(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppServicesResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    info_txt = _read_info(cliente_id)
    items = [
        AppServiceProduct(
            id=item.get("id", ""),
            nombre=item.get("nombre", ""),
            descripcion=item.get("descripcion", ""),
        )
        for item in _extract_services_from_info(cliente_id)
    ]
    return AppServicesResponse(cliente_id=cliente_id, items=items, info_chars=len(info_txt))


@app.post("/auth/app/services", response_model=AppServicesResponse)
async def app_services_post(
    data: AppServicesPayload,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppServicesResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    unique: Dict[str, Dict[str, str]] = {}
    for item in data.items:
        nombre = _sanitize_text(item.nombre)[:160]
        if not nombre:
            continue
        service_id = _normalize_service_id(nombre)
        if not service_id:
            continue
        unique[service_id] = {
            "nombre": nombre,
            "descripcion": _sanitize_text(item.descripcion, allow_multiline=True)[:800],
        }
    info_txt = _replace_services_section(_read_info(cliente_id), list(unique.values()))
    _write_info(cliente_id, info_txt)
    return await app_services_get(user)




@app.get("/auth/app/whatsapp", response_model=AppWhatsAppResponse)
async def app_whatsapp_get(
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppWhatsAppResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    return _app_whatsapp_response(cliente_id, request)


@app.post("/auth/app/whatsapp", response_model=AppWhatsAppResponse)
async def app_whatsapp_post(
    data: AppWhatsAppPayload,
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppWhatsAppResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        wa = dict(cfg.get("whatsapp", {}) or {})
        if data.phone_number_id is not None:
            wa["phone_number_id"] = _sanitize_text(data.phone_number_id)[:120]
        if data.access_token_env is not None:
            wa["access_token_env"] = _sanitize_text(data.access_token_env)[:120]
        if data.verify_token_env is not None:
            wa["verify_token_env"] = _sanitize_text(data.verify_token_env)[:120]
        if data.enabled is not None:
            if data.enabled:
                if not _plan_feature(cliente_id, "whatsapp_enabled"):
                    raise HTTPException(
                        status_code=403,
                        detail="WhatsApp esta disponible en el plan Business.",
                    )
                if not str(wa.get("phone_number_id", "") or "").strip():
                    raise HTTPException(status_code=400, detail="Indica el Phone Number ID de WhatsApp.")
            wa["enabled"] = bool(data.enabled)
        cfg["whatsapp"] = wa
        next_configs[cliente_id] = cfg
        _validate_single_client_runtime(cliente_id, _normalize_client_config(cliente_id, cfg))
        _update_runtime_configs(next_configs)
    _persist_configs_to_disk(next_configs)
    return _app_whatsapp_response(cliente_id, request)




@app.get("/auth/app/voice", response_model=AppVoiceResponse)
async def app_voice_get(
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppVoiceResponse:
    return _app_voice_response(_resolve_cliente_for_self_serve_user(user), request)


@app.post("/auth/app/voice", response_model=AppVoiceResponse)
async def app_voice_post(
    data: AppVoicePayload,
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AppVoiceResponse:
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        voice = dict(cfg.get("voice", {}) or {})
        if data.enabled is not None:
            if data.enabled and not _client_voice_plan_enabled(cliente_id):
                raise HTTPException(status_code=403, detail="El asistente de voz está disponible en el plan Business.")
            voice["enabled"] = bool(data.enabled)
        if data.twilio_phone_number is not None:
            voice["twilio_phone_number"] = _sanitize_text(data.twilio_phone_number)[:32]
        if data.openai_voice is not None:
            v = _sanitize_text(data.openai_voice).lower()
            voice["openai_voice"] = v if v in VOICE_ALLOWED_OPENAI_VOICES else (voice.get("openai_voice") or "alloy")
        cfg["voice"] = voice
        next_configs[cliente_id] = cfg
        _update_runtime_configs(next_configs)
    _persist_configs_to_disk(next_configs)
    return _app_voice_response(cliente_id, request)


@app.post("/auth/app/voice/session", include_in_schema=False)
async def app_voice_session(
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Token efimero para probar el asistente de voz en el navegador desde el panel del
    cliente (misma llamada simulada que la demo). Requiere plan Business; reutiliza la
    config de voz del cliente, asi que suena igual que el telefono."""
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    config = _get_client_config(cliente_id)
    if not _client_voice_plan_enabled(cliente_id):
        raise HTTPException(status_code=403, detail="El asistente de voz está disponible en el plan Business.")
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El asistente de voz no esta disponible ahora mismo.",
        )
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"app_voice:{cliente_id}:{client_ip}", APP_VOICE_RATE_LIMIT)
    voice_cfg = config.get("voice") or {}
    max_seconds = int(voice_cfg.get("max_duration_seconds") or 0) or DEMO_VOICE_MAX_SECONDS
    return await _mint_voice_session(cliente_id, config, max_seconds=max_seconds, log_tag="app-voice")


@app.post("/auth/app/voice/tool", include_in_schema=False)
async def app_voice_tool(
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> Dict[str, Any]:
    """Ejecuta una tool de la voz en navegador desde el panel del cliente. A diferencia de la
    demo publica, aqui SI se reserva/cancela de verdad sobre la agenda del propio cliente
    (es el dueno probando su sistema). Reusa _voice_dispatch_tool (la misma logica que el
    telefono). Sin esto el modelo se queda esperando el function_call_output (silencio)."""
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    if not _client_voice_plan_enabled(cliente_id):
        raise HTTPException(status_code=403, detail="El asistente de voz está disponible en el plan Business.")
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"app_voice_tool:{cliente_id}:{client_ip}", 60)
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
    return await _voice_dispatch_tool(cliente_id, name, arguments, from_number="")


# --- Sem 4: Live Chat (Pro gate stub) --------------------------------------





@app.get("/auth/app/livechat", response_model=List[AppLiveChatSession])
async def app_livechat_list(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> List[AppLiveChatSession]:
    _require_pro_plan(user)
    cliente_id = _resolve_cliente_for_self_serve_user(user)
    with _get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM live_chat_sessions WHERE cliente_id = ? ORDER BY started_at DESC LIMIT 50",
            (cliente_id,),
        ).fetchall()
    return [
        AppLiveChatSession(
            id=r["id"],
            chat_session_id=r["chat_session_id"] or "",
            status=r["status"] or "pending",
            started_at=r["started_at"] or "",
            claimed_at=r["claimed_at"] or "",
            agent_user_id=r["agent_user_id"] or "",
        )
        for r in rows
    ]


# --- Sem 5: Billing (Stripe checkout + portal + plan state) ---



























@app.get("/auth/app/stripe-connect", response_model=StripeConnectStateResponse)
async def app_stripe_connect_state(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> StripeConnectStateResponse:
    cliente_id = str(user["cliente_id"] or "")
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Tu usuario no tiene un negocio asociado.")
    row = _stripe_connected_account_row(cliente_id)
    if not row:
        return StripeConnectStateResponse(configured=_stripe_connect_configured())
    status_value = str(row["status"] or "pending")
    requirements_due = int(row["requirements_due"] or 0)
    last_error = ""
    if _stripe_connect_configured():
        try:
            account = _stripe_connect_request(
                "GET",
                f"/accounts/{row['stripe_account_id']}?include[0]=configuration.merchant&include[1]=requirements",
            )
            status_value, requirements_due = _stripe_connect_account_status(account)
            _save_stripe_connected_account(
                cliente_id,
                user["id"],
                row["stripe_account_id"],
                status_value=status_value,
                requirements_due=requirements_due,
            )
        except HTTPException as exc:
            last_error = str(exc.detail)
            _save_stripe_connected_account(
                cliente_id,
                user["id"],
                row["stripe_account_id"],
                status_value=status_value,
                requirements_due=requirements_due,
                last_error=last_error,
            )
    return StripeConnectStateResponse(
        configured=_stripe_connect_configured(),
        connected=True,
        stripe_account_id=row["stripe_account_id"],
        status=status_value,
        requirements_due=requirements_due,
        last_error=last_error,
    )


@app.post("/auth/app/stripe-connect/start", response_model=StripeConnectStartResponse)
async def app_stripe_connect_start(
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> StripeConnectStartResponse:
    if _session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Accion bloqueada en sesion de admin (impersonacion).")
    return StripeConnectStartResponse(ok=True, onboarding_url=_stripe_connect_onboarding_url(user, request))


@app.get("/auth/app/stripe-connect/refresh")
async def app_stripe_connect_refresh(
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> RedirectResponse:
    if _session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Accion bloqueada en sesion de admin (impersonacion).")
    return RedirectResponse(_stripe_connect_onboarding_url(user, request), status_code=303)


@app.get("/auth/app/stripe-connect/return")
async def app_stripe_connect_return(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> RedirectResponse:
    return RedirectResponse("/app?stripe_connect=returned", status_code=303)














@app.get("/auth/bookings/{booking_id}/payment", response_model=BookingPaymentStateResponse)
async def auth_booking_payment_state(
    booking_id: str,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> BookingPaymentStateResponse:
    booking = _load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    service = _get_service_row(booking["cliente_id"], booking["service_id"]) or _find_service_by_name(
        booking["cliente_id"], booking["servicio"]
    )
    decision = resolve_payment_requirement(booking["cliente_id"], service, booking)
    payment = _booking_payment_row(booking_id)
    return BookingPaymentStateResponse(
        booking_id=booking_id,
        payment_required=decision["payment_required"],
        payment_optional=decision["payment_optional"],
        payment_status=payment["status"] if payment else booking["payment_status"],
        amount_cents=int(payment["amount_cents"] if payment else decision["amount_cents"]),
        currency=payment["currency"] if payment else decision["currency"],
        checkout_url=payment["checkout_url"] if payment else "",
    )


@app.post("/auth/bookings/{booking_id}/payment/checkout", response_model=BookingPaymentStateResponse)
async def auth_booking_payment_checkout(
    booking_id: str,
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> BookingPaymentStateResponse:
    booking = _load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    checkout_url = create_booking_payment_checkout(booking["cliente_id"], booking_id, request)
    payment = _booking_payment_row(booking_id)
    service = _get_service_row(booking["cliente_id"], booking["service_id"]) or _find_service_by_name(
        booking["cliente_id"], booking["servicio"]
    )
    decision = resolve_payment_requirement(booking["cliente_id"], service, booking)
    return BookingPaymentStateResponse(
        booking_id=booking_id,
        payment_required=decision["payment_required"],
        payment_optional=decision["payment_optional"],
        payment_status=payment["status"] if payment else booking["payment_status"],
        amount_cents=int(payment["amount_cents"] if payment else 0),
        currency=payment["currency"] if payment else "eur",
        checkout_url=checkout_url,
    )


@app.get("/auth/app/billing", response_model=BillingStateResponse)
async def app_billing_state(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> BillingStateResponse:
    sub = db_get_subscription_for_user(user["id"]) or db_ensure_free_subscription(user["id"])
    sub = _maybe_reset_subscription_period(sub)
    current_plan = (sub["plan"] or "free").lower()
    return BillingStateResponse(
        subscription=_serialize_billing_subscription(sub),
        plans=_build_plan_tiers(current_plan),
        portal_available=bool(sub["stripe_customer_id"]) and _stripe_configured(),
    )


@app.post("/auth/app/billing/checkout", response_model=BillingCheckoutResponse)
async def app_billing_checkout(
    data: BillingCheckoutPayload,
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> BillingCheckoutResponse:
    if _session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Acción bloqueada en sesión de admin (impersonación).")
    if not _stripe_configured():
        raise HTTPException(status_code=503, detail="Stripe no configurado en el servidor.")
    plan = _self_serve_plan(data.plan)
    if plan["slug"] == "free":
        raise HTTPException(status_code=400, detail="El plan Free no requiere checkout.")
    price_id = plan["stripe_price_annual"] if data.billing_period == "annual" else plan["stripe_price_monthly"]
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"STRIPE_PRICE_{plan['slug'].upper()}{'_ANNUAL' if data.billing_period == 'annual' else ''} no configurado.",
        )
    stripe.api_key = STRIPE_SECRET_KEY
    api_base = _public_base_url(request)
    sub = db_get_subscription_for_user(user["id"]) or db_ensure_free_subscription(user["id"])
    customer_kwargs: Dict[str, Any] = {}
    if sub["stripe_customer_id"]:
        customer_kwargs["customer"] = sub["stripe_customer_id"]
    else:
        customer_kwargs["customer_email"] = user["email"]
    session_kwargs: Dict[str, Any] = {
        "mode": "subscription",
        # Si el total recurrente queda en 0 (p.ej. cupon 100% forever), Stripe
        # no pide tarjeta. Para planes de pago normales sigue exigiendola.
        "payment_method_collection": "if_required",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": f"{api_base}/app?billing=success&plan={plan['slug']}",
        "cancel_url": f"{api_base}/app?billing=cancel",
        "client_reference_id": f"self_serve:{user['id']}",
        "metadata": {
            "source": "self_serve",
            "user_id": user["id"],
            "cliente_id": user["cliente_id"] or "",
            "plan": plan["slug"],
            "billing_period": data.billing_period,
        },
        **customer_kwargs,
    }
    coupon_id = (data.coupon or "").strip()
    if coupon_id:
        # Direct coupon injection (server-side). Stripe rejects invalid coupons with 400.
        # `allow_promotion_codes` and `discounts` are mutually exclusive in Checkout.
        session_kwargs["discounts"] = [{"coupon": coupon_id}]
    else:
        session_kwargs["allow_promotion_codes"] = True
    try:
        session = stripe.checkout.Session.create(**session_kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.error("Stripe checkout self-serve fallo user=%s plan=%s: %s", user["id"], plan["slug"], exc)
        raise HTTPException(status_code=502, detail="No se pudo iniciar el checkout.") from exc
    _try_record_analytics_event(
        {
            "event": "checkout_started",
            "event_source": "vantelia_app",
            "widget_client_id": user["cliente_id"] or "",
            "cliente_id": user["cliente_id"] or "",
            "user_id": user["id"],
            "plan": plan["slug"],
            "billing_period": data.billing_period,
            "checkout_session_id": session.id or "",
            "source": "self_serve",
        },
        request,
    )
    _try_record_analytics_event(
        {
            "event": "upgrade_started",
            "event_source": "vantelia_app",
            "widget_client_id": user["cliente_id"] or "",
            "cliente_id": user["cliente_id"] or "",
            "user_id": user["id"],
            "plan": plan["slug"],
            "billing_period": data.billing_period,
            "checkout_session_id": session.id or "",
            "source": "self_serve",
        },
        request,
    )
    return BillingCheckoutResponse(ok=True, checkout_url=session.url or "")


@app.post("/auth/app/billing/portal", response_model=BillingPortalResponse)
async def app_billing_portal(
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> BillingPortalResponse:
    if _session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Acción bloqueada en sesión de admin (impersonación).")
    if not _stripe_configured():
        raise HTTPException(status_code=503, detail="Stripe no configurado.")
    sub = db_get_subscription_for_user(user["id"])
    if not sub or not sub["stripe_customer_id"]:
        raise HTTPException(status_code=400, detail="No tienes una suscripcion de pago activa.")
    stripe.api_key = STRIPE_SECRET_KEY
    api_base = _public_base_url(request)
    try:
        portal = stripe.billing_portal.Session.create(
            customer=sub["stripe_customer_id"],
            return_url=f"{api_base}/app",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Stripe portal fallo user=%s: %s", user["id"], exc)
        raise HTTPException(status_code=502, detail="No se pudo abrir el portal.") from exc
    return BillingPortalResponse(ok=True, portal_url=portal.url or "")


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
    return _update_portal_ai_config(
        _portal_client_id_or_403(user, cliente_id),
        data,
        full_access=_is_admin_client_portal_override(user, cliente_id),
    )


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


@app.get("/auth/schedule/employee/{employee_id}", response_model=PortalSchedulePublic)
async def auth_employee_schedule(
    employee_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalSchedulePublic:
    return _portal_schedule_from_employee(_portal_client_id_or_403(user, cliente_id), employee_id)


@app.post("/auth/schedule/employee/{employee_id}", response_model=PortalSchedulePublic)
async def auth_update_employee_schedule(
    employee_id: str,
    data: PortalScheduleUpdatePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalSchedulePublic:
    return _update_employee_schedule(_portal_client_id_or_403(user, cliente_id), employee_id, data)


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
    target_email = str(data.target_email or data.test_email or user["email"] or "").strip()
    if not target_email:
        raise HTTPException(status_code=400, detail="Indica un email donde enviar la prueba.")
    _send_email_message(target_email, preview.subject, preview.text_body, preview.html_body, cliente_id=target_client_id)
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


@app.get("/auth/services", response_model=ServicesResponse)
async def auth_list_services(
    cliente_id: str = "",
    include_inactive: bool = True,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ServicesResponse:
    target_client_id = _portal_client_id_or_403(user, cliente_id)
    return ServicesResponse(
        items=[ServicePublic(**svc) for svc in _catalog_services(target_client_id, include_inactive=include_inactive)]
    )


@app.post("/auth/employees", response_model=PortalEmployeePublic)
async def auth_create_employee(
    data: PortalEmployeePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalEmployeePublic:
    return _create_portal_employee(
        _portal_client_id_or_403(user, cliente_id),
        data,
        full_access=_is_admin_client_portal_override(user, cliente_id),
    )


@app.post("/auth/employees/{employee_id}", response_model=PortalEmployeePublic)
async def auth_update_employee(
    employee_id: str,
    data: PortalEmployeePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> PortalEmployeePublic:
    return _update_portal_employee(
        _portal_client_id_or_403(user, cliente_id),
        employee_id,
        data,
        full_access=_is_admin_client_portal_override(user, cliente_id),
    )


@app.delete("/auth/employees/{employee_id}", response_model=AuthSimpleResponse)
async def auth_delete_employee(
    employee_id: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AuthSimpleResponse:
    _delete_portal_employee(_portal_client_id_or_403(user, cliente_id), employee_id)
    return AuthSimpleResponse(ok=True, message="Profesional eliminado correctamente.")


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


@app.post("/auth/bookings", response_model=BookingActionResponse)
async def auth_create_booking(
    data: StaffBookingCreatePayload,
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> BookingActionResponse:
    """Alta manual de cita desde el portal (walk-in / cita por telefono)."""
    target_client_id = _portal_client_id_or_403(user, cliente_id)
    config = _get_client_config(target_client_id)
    if not config["booking"]["enabled"]:
        raise HTTPException(status_code=409, detail="La agenda no esta activada para este cliente.")

    booking_date_dt = _parse_date(data.fecha)
    _validate_booking_window(target_client_id, booking_date_dt)
    booking_date = booking_date_dt.strftime("%Y-%m-%d")
    booking_time = _parse_time(data.hora).strftime("%H:%M")
    nombre = _sanitize_text(data.nombre)
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre del cliente es obligatorio.")
    email = _sanitize_text(data.email)
    telefono = _sanitize_text(data.telefono)
    servicio = _sanitize_text(data.servicio)
    notas = _sanitize_text(data.notas, allow_multiline=True)

    employee_row = _resolve_employee_for_booking(target_client_id, data.employee_id, require_active=False)
    service_row = _find_service_by_name(target_client_id, servicio)
    service_duration = _service_duration_minutes(target_client_id, servicio, employee_row)
    service_id = service_row["slug"] if service_row else ""
    service_price = int(service_row["price_cents"]) if service_row else 0

    # Limites de plan (salvo override admin del portal).
    if not _is_admin_client_portal_override(user, cliente_id):
        _require_active_subscription(target_client_id)
        booking_limit = _plan_limits(_client_plan(target_client_id)).get("monthly_bookings")
        if booking_limit is not None and _count_bookings_this_month(target_client_id) >= int(booking_limit):
            raise HTTPException(
                status_code=429,
                detail="Se ha alcanzado el limite mensual de citas del plan.",
            )

    if not await _booking_slot_available(
        target_client_id, booking_date, booking_time,
        employee_id=employee_row["id"], duration_minutes=service_duration,
    ):
        raise HTTPException(
            status_code=409,
            detail="Ese horario no esta disponible para el profesional seleccionado.",
        )

    booking_id = f"bk_{secrets.token_urlsafe(10)}"
    manage_token = _generate_manage_token()
    created_at = _utc_now_iso()
    start_local, end_local = _booking_start_end(
        target_client_id, booking_date, booking_time,
        employee_id=employee_row["id"], duration_minutes=service_duration,
    )
    booking_timezone = employee_row["timezone"] or config["booking"]["timezone"]

    record = {
        "id": booking_id,
        "cliente_id": target_client_id,
        "employee_id": employee_row["id"],
        "employee_name": employee_row["name"],
        "nombre": nombre,
        "email": email,
        "telefono": telefono,
        "servicio": servicio,
        "booking_date": booking_date,
        "booking_time": booking_time,
        "notas": notas,
        "status": "confirmed",
        "provider_name": "internal",
        "provider_status": "internal",
        "provider_booking_id": "",
        "provider_booking_url": "",
        "manage_token": manage_token,
        "timezone": booking_timezone,
        "start_at": _to_utc_iso(start_local),
        "end_at": _to_utc_iso(end_local),
        "confirmed_at": created_at,
        "cancelled_at": "",
        **_booking_blank_tracking_fields(),
        "service_id": service_id,
        "service_price_cents": service_price,
        "source": "portal_manual",
        "created_at": created_at,
    }
    try:
        _store_booking(record)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese horario acaba de ocuparse. Elige otro tramo.",
        ) from exc
    _record_booking_audit(
        booking_id,
        target_client_id,
        "booking_created",
        {
            "status": "confirmed",
            "source": "portal_manual",
            "role": user["role"],
            "user_id": user["id"],
            "employee_id": employee_row["id"],
            "employee_name": employee_row["name"],
        },
    )

    booking_row = _get_booking_row_by_id(booking_id)
    if booking_row and email:
        try:
            await _send_booking_reminder_by_kind(
                booking_row,
                "confirmed",
                request,
                sent_column="confirmation_email_sent_at",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("No se ha podido enviar el aviso de la cita manual %s: %s", booking_id, exc)
            _mark_booking_email_result(booking_id, status="failed", error=str(exc))

    payment_row = _booking_payment_row(booking_id)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado=booking_row["status"] if booking_row else "confirmed",
        mensaje="Cita creada correctamente.",
        employee_id=employee_row["id"],
        employee_name=employee_row["name"],
        manage_url=_build_booking_manage_url(manage_token, request),
        payment_status=booking_row["payment_status"] if booking_row else "not_required",
        payment_url=payment_row["checkout_url"] if payment_row else "",
    )


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
        await _send_booking_reminder_by_kind(
            refreshed,
            "cancelled",
            request,
            extra_message=cancel_reason,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("No se ha podido enviar el aviso de cancelacion %s: %s", refreshed["id"], exc)
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado="cancelled",
        mensaje="La cita ha sido cancelada correctamente.",
        manage_url=_booking_row_manage_url(refreshed, request),
        provider_booking_url=refreshed["provider_booking_url"] or "",
    )


@app.post("/auth/bookings/{booking_id}/attendance", response_model=BookingActionResponse)
async def auth_mark_booking_attendance(
    booking_id: str,
    data: BookingAttendancePayload,
    request: Request,
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> BookingActionResponse:
    booking_row = _load_booking_or_404(booking_id)
    if user["role"] != "admin" and booking_row["cliente_id"] != user["cliente_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reserva.")
    if booking_row["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="No se puede marcar la asistencia de una cita cancelada.")
    start_at = booking_row["start_at"] or ""
    if start_at:
        start_dt = _from_utc_iso(start_at)
        if start_dt and start_dt > _utc_now():
            raise HTTPException(status_code=409, detail="La cita aun no ha ocurrido; no se puede marcar la asistencia.")
    new_status = "completed" if data.attended else "no_show"
    _update_booking_record(booking_id, status=new_status, completed_source="manual")
    _record_booking_audit(
        booking_id,
        booking_row["cliente_id"],
        "booking_completed" if data.attended else "booking_no_show",
        {
            "source": "portal",
            "role": user["role"],
            "user_id": user["id"],
            "attended": bool(data.attended),
        },
    )
    refreshed = _load_booking_or_404(booking_id)
    _crm_upsert_contact(
        refreshed["cliente_id"], name=refreshed["nombre"], email=refreshed["email"],
        phone=refreshed["telefono"] or "", source="portal",
        status="cliente" if data.attended else "interesado",
        entity_type="booking", entity_id=refreshed["id"], actor=f"user:{user['id']}",
    )
    return BookingActionResponse(
        ok=True,
        booking_id=booking_id,
        estado=new_status,
        mensaje="Cita marcada como realizada." if data.attended else "Cita marcada como no asistida.",
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


# ─── Suscripciones / Pagos ────────────────────────────────────────────

@app.get("/auth/subscription", response_model=SubscriptionPublic)
async def auth_subscription(
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> SubscriptionPublic:
    return _build_subscription_public(
        _portal_client_id_or_403(user, cliente_id),
        admin_override=_is_admin_client_portal_override(user, cliente_id),
    )


@app.post("/auth/subscription/checkout", response_model=SubscriptionCheckoutResponse)
async def auth_subscription_checkout(
    data: SubscriptionCheckoutPayload,
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> SubscriptionCheckoutResponse:
    cid = _portal_client_id_or_403(user, cliente_id)
    plan = data.plan.strip().lower()
    price_id, billing_period = _stripe_price_for_plan(plan, data.billing_period)
    _stripe_init()

    base_url = _public_base_url(request)
    success_url = data.success_url or f"{base_url}/portal?subscription=success"
    cancel_url = data.cancel_url or f"{base_url}/portal?subscription=cancel"

    sub = _client_subscription(cid)
    customer_kwargs: Dict[str, Any] = {}
    if sub.get("stripe_customer_id"):
        customer_kwargs["customer"] = sub["stripe_customer_id"]
    else:
        customer_kwargs["customer_email"] = str(user["email"])

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=cid,
            metadata={"cliente_id": cid, "plan": plan, "billing_period": billing_period},
            subscription_data={"metadata": {"cliente_id": cid, "plan": plan, "billing_period": billing_period}},
            billing_address_collection="required",
            phone_number_collection={"enabled": True},
            tax_id_collection={"enabled": True},
            payment_method_collection="if_required",
            allow_promotion_codes=True,
            **customer_kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error creando Stripe Checkout para %s: %s", cid, exc)
        raise HTTPException(status_code=502, detail="No se pudo iniciar el proceso de pago.") from exc

    return SubscriptionCheckoutResponse(url=session.url, session_id=session.id)


@app.post("/subscription/checkout", response_model=SubscriptionCheckoutResponse)
async def public_subscription_checkout(
    data: SubscriptionCheckoutPayload,
    request: Request,
) -> SubscriptionCheckoutResponse:
    plan = data.plan.strip().lower()
    price_id, billing_period = _stripe_price_for_plan(plan, data.billing_period)
    _stripe_init()

    marketing_url = MARKETING_SITE_URL.rstrip("/") or "https://www.vantelia.es"
    success_url = (
        f"{marketing_url}/bienvenido/?plan={quote(plan)}&period={quote(billing_period)}"
        "&session={CHECKOUT_SESSION_ID}"
    )
    cancel_url = f"{marketing_url}/planes/?checkout=cancel&plan={quote(plan)}"

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=f"public:{plan}:{billing_period}",
            metadata={"source": "public_plans", "plan": plan, "billing_period": billing_period},
            subscription_data={
                "metadata": {"source": "public_plans", "plan": plan, "billing_period": billing_period},
            },
            custom_fields=_stripe_onboarding_custom_fields(),
            billing_address_collection="required",
            phone_number_collection={"enabled": True},
            tax_id_collection={"enabled": True},
            payment_method_collection="if_required",
            allow_promotion_codes=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error creando Stripe Checkout publico para plan=%s: %s", plan, exc)
        raise HTTPException(status_code=502, detail="No se pudo iniciar el proceso de pago.") from exc

    return SubscriptionCheckoutResponse(url=session.url, session_id=session.id)


@app.get("/subscription/checkout/status", response_model=PublicCheckoutStatusResponse)
async def public_subscription_checkout_status(
    request: Request,
    session_id: str = "",
    session: str = "",
) -> PublicCheckoutStatusResponse:
    checkout_session_id = session_id or session
    session_object = _retrieve_public_checkout_session(checkout_session_id)
    state_value, cliente_id, message = _public_checkout_session_state(session_object)
    base_url = _public_base_url(request)
    portal_enter_url = (
        f"{base_url}/subscription/checkout/enter?session_id={quote(checkout_session_id, safe='')}"
        if state_value == "ready"
        else ""
    )
    return PublicCheckoutStatusResponse(
        status=state_value,
        message=message,
        cliente_id=cliente_id,
        portal_enter_url=portal_enter_url,
    )


@app.get("/subscription/checkout/enter", include_in_schema=False)
async def public_subscription_checkout_enter(
    session_id: str = "",
    session: str = "",
) -> Response:
    checkout_session_id = session_id or session
    session_object = _retrieve_public_checkout_session(checkout_session_id)
    state_value, cliente_id, _ = _public_checkout_session_state(session_object)
    if state_value != "ready" or not cliente_id:
        return RedirectResponse(url=f"/acceso?checkout_status={quote(state_value)}", status_code=303)
    user = _portal_user_for_checkout_client(cliente_id, session_object)
    with _get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (_utc_now_iso(), user["id"]),
        )
        connection.commit()
    raw_token = _create_auth_session(user["id"])
    response = RedirectResponse(url="/portal?welcome=1", status_code=303)
    _set_portal_cookie(response, raw_token)
    return response


@app.post("/auth/subscription/portal", response_model=SubscriptionPortalResponse)
async def auth_subscription_portal(
    request: Request,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> SubscriptionPortalResponse:
    cid = _portal_client_id_or_403(user, cliente_id)
    sub = _client_subscription(cid)
    if not sub.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="Aún no tienes una suscripción activa con pago.")
    _stripe_init()
    base_url = _public_base_url(request)
    try:
        session = stripe.billing_portal.Session.create(
            customer=sub["stripe_customer_id"],
            return_url=f"{base_url}/portal",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error creando Stripe Billing Portal para %s: %s", cid, exc)
        raise HTTPException(status_code=502, detail="No se pudo abrir el portal de facturación.") from exc
    return SubscriptionPortalResponse(url=session.url)




@app.post("/stripe/connect/webhook", include_in_schema=False)
async def stripe_connect_webhook(request: Request) -> Dict[str, Any]:
    if not _stripe_configured() or not STRIPE_CONNECT_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe Connect webhook no configurado.")
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, signature, STRIPE_CONNECT_WEBHOOK_SECRET)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Webhook Connect invalido.") from exc
    event_id = str(_object_get(event, "id", "") or "")
    event_type = str(_object_get(event, "type", "") or "")
    account_id = str(_object_get(event, "account", "") or "")
    data = _object_get(_object_get(event, "data", {}), "object", {}) or {}
    metadata = _object_get(data, "metadata", {}) or {}
    payment_id = str(_object_get(metadata, "payment_id", "") or "")
    session_id = str(_object_get(data, "id", "") or "") if event_type.startswith("checkout.session.") else ""
    with _get_db_connection() as connection:
        account_row = connection.execute(
            "SELECT cliente_id FROM client_payment_accounts WHERE stripe_account_id=?", (account_id,)
        ).fetchone()
        if not account_row:
            raise HTTPException(status_code=404, detail="Cuenta Connect no reconocida.")
        cliente_id = account_row["cliente_id"]
        if connection.execute("SELECT 1 FROM customer_payment_events WHERE stripe_event_id=?", (event_id,)).fetchone():
            return {"received": True, "duplicate": True}
        payment = None
        if payment_id:
            payment = connection.execute(
                "SELECT * FROM customer_payments WHERE id=? AND cliente_id=?", (payment_id, cliente_id)
            ).fetchone()
        if not payment and session_id:
            payment = connection.execute(
                "SELECT * FROM customer_payments WHERE stripe_checkout_session_id=? AND cliente_id=?",
                (session_id, cliente_id),
            ).fetchone()
        if not payment and event_type == "charge.refunded":
            payment_intent_id = str(_object_get(data, "payment_intent", "") or "")
            if payment_intent_id:
                payment = connection.execute(
                    "SELECT * FROM customer_payments WHERE stripe_payment_intent_id=? AND cliente_id=?",
                    (payment_intent_id, cliente_id),
                ).fetchone()
        connection.execute(
            """
            INSERT INTO customer_payment_events (stripe_event_id, cliente_id, payment_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, cliente_id, payment["id"] if payment else payment_id, event_type, json.dumps(data, ensure_ascii=False, default=str), _utc_now_iso()),
        )
        if event_type == "account.updated":
            connection.execute(
                """
                UPDATE client_payment_accounts SET charges_enabled=?, payouts_enabled=?,
                    details_submitted=?, updated_at=? WHERE cliente_id=?
                """,
                (
                    int(bool(_object_get(data, "charges_enabled", False))),
                    int(bool(_object_get(data, "payouts_enabled", False))),
                    int(bool(_object_get(data, "details_submitted", False))),
                    _utc_now_iso(), cliente_id,
                ),
            )
        if payment:
            now = _utc_now_iso()
            new_status = payment["status"]
            paid_at = payment["paid_at"] or ""
            payment_intent = payment["stripe_payment_intent_id"] or ""
            if event_type == "checkout.session.completed" and str(_object_get(data, "payment_status", "")) == "paid":
                new_status, paid_at = "paid", now
                payment_intent = str(_object_get(data, "payment_intent", "") or "")
            elif event_type in {"checkout.session.expired", "payment_intent.payment_failed"}:
                new_status = "failed"
            elif event_type == "charge.refunded":
                refunded = int(_object_get(data, "amount_refunded", 0) or 0)
                total = int(_object_get(data, "amount", 0) or payment["amount_cents"])
                new_status = "refunded" if refunded >= total else "partially_refunded"
            connection.execute(
                "UPDATE customer_payments SET status=?, paid_at=?, stripe_payment_intent_id=?, updated_at=? WHERE id=?",
                (new_status, paid_at, payment_intent, now, payment["id"]),
            )
            if new_status == "paid" and payment["booking_id"]:
                booking = connection.execute("SELECT * FROM bookings WHERE id=? AND cliente_id=?", (payment["booking_id"], cliente_id)).fetchone()
                if booking:
                    policy = _payment_policy(cliente_id, payment["service_id"] or "")
                    if policy["confirm_booking_on_paid"] and booking["status"] == "pending_review":
                        connection.execute(
                            "UPDATE bookings SET status='confirmed', confirmed_at=? WHERE id=?",
                            (now, booking["id"]),
                        )
                        connection.execute(
                            "INSERT INTO booking_audit (booking_id, cliente_id, event_type, payload_json, created_at) VALUES (?, ?, 'booking_confirmed_by_payment', ?, ?)",
                            (booking["id"], cliente_id, json.dumps({"payment_id": payment["id"]}), now),
                        )
            connection.commit()
        else:
            connection.commit()
    return {"received": True}


@app.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    if not _stripe_configured():
        raise HTTPException(status_code=503, detail="Stripe no configurado.")
    if not STRIPE_WEBHOOK_SECRET and not STRIPE_CONNECT_WEBHOOK_SECRET:
        logger.error("Stripe webhook recibido pero STRIPE_WEBHOOK_SECRET no está configurado; rechazando por seguridad.")
        raise HTTPException(status_code=503, detail="Stripe webhook secret no configurado.")
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    if not sig_header:
        logger.warning("Stripe webhook recibido sin cabecera stripe-signature; rechazando.")
        raise HTTPException(status_code=400, detail="Falta firma del webhook.")
    try:
        event = _construct_stripe_webhook_event(payload, sig_header)
    except stripe.error.SignatureVerificationError as exc:
        logger.warning("Stripe webhook firma inválida: %s", exc)
        raise HTTPException(status_code=400, detail="Firma del webhook inválida.") from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("Stripe webhook payload error: %s", exc)
        raise HTTPException(status_code=400, detail="Webhook payload inválido.") from exc

    event_type = event.get("type") if isinstance(event, dict) else event["type"]
    data_object = (event.get("data") if isinstance(event, dict) else event["data"]).get("object", {})

    try:
        if event_type == "checkout.session.completed":
            if process_booking_payment_webhook(data_object):
                return {"received": True}
            cid = (data_object.get("metadata") or {}).get("cliente_id") or data_object.get("client_reference_id")
            plan = (data_object.get("metadata") or {}).get("plan") or PLAN_DEFAULT
            billing_period = (data_object.get("metadata") or {}).get("billing_period") or "monthly"
            customer_id = data_object.get("customer") or ""
            sub_id = data_object.get("subscription") or ""
            source = (data_object.get("metadata") or {}).get("source") or ""
            if source == "self_serve":
                user_id = (data_object.get("metadata") or {}).get("user_id") or ""
                ref = str(data_object.get("client_reference_id") or "")
                if not user_id and ref.startswith("self_serve:"):
                    user_id = ref.split(":", 1)[1]
                if user_id and plan in SELF_SERVE_PLANS and plan != "free":
                    db_set_subscription_from_stripe(
                        user_id=user_id,
                        plan_slug=plan,
                        stripe_customer_id=customer_id,
                        stripe_subscription_id=sub_id,
                        status="active",
                        current_period_start=_utc_now().isoformat(),
                    )
                    logger.info("Self-serve subscription activada user=%s plan=%s", user_id, plan)
                else:
                    logger.warning(
                        "Self-serve checkout completed sin user_id/plan validos: user=%s plan=%s",
                        user_id, plan,
                    )
                return {"received": True}
            if source == "public_plans" and str(cid or "").startswith("public:"):
                session_id = str(data_object.get("id") or "").strip()
                existing_cid = _find_client_by_stripe_id(
                    customer_id=customer_id, subscription_id=sub_id, session_id=session_id
                )
                if existing_cid:
                    logger.info(
                        "checkout.session.completed duplicado ignorado: cliente=%s session=%s",
                        existing_cid, session_id,
                    )
                elif not _claim_stripe_session(session_id):
                    logger.info(
                        "checkout.session.completed en curso, reintento ignorado: session=%s",
                        session_id,
                    )
                else:
                    # Onboarding lento (scrape + indexado): correr en background y
                    # responder 200 a Stripe para evitar reintentos que generan duplicados.
                    def _run_onboarding_bg(
                        data_object=data_object, plan=plan, billing_period=billing_period,
                        customer_id=customer_id, sub_id=sub_id, session_id=session_id, request=request,
                    ) -> None:
                        try:
                            new_cid = _create_client_from_public_checkout(
                                data_object,
                                request=request,
                                plan=plan,
                                billing_period=billing_period,
                                customer_id=customer_id,
                                subscription_id=sub_id,
                            )
                            _mark_stripe_session(session_id, status="done", cliente_id=new_cid or "")
                            _try_record_analytics_event(
                                {
                                    "event": "checkout_completed",
                                    "event_source": "stripe_webhook",
                                    "cliente_id": new_cid or "",
                                    "plan": plan,
                                    "billing_period": billing_period,
                                    "checkout_session_id": session_id,
                                    "checkout_status": "completed",
                                },
                                request,
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.exception(
                                "Onboarding async fallido session=%s: %s", session_id, exc
                            )
                            _mark_stripe_session(session_id, status="failed", error=str(exc))
                    background_tasks.add_task(_run_onboarding_bg)
            elif cid and cid in appstate.CONFIG_CLIENTES:
                _set_client_subscription(
                    cid,
                    plan=plan,
                    status="active",
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=sub_id,
                    billing_period=billing_period,
                    started_at=_utc_now().isoformat(),
                )
                _try_record_analytics_event(
                    {
                        "event": "checkout_completed",
                        "event_source": "stripe_webhook",
                        "cliente_id": cid,
                        "plan": plan,
                        "billing_period": billing_period,
                        "checkout_session_id": str(data_object.get("id") or ""),
                        "checkout_status": "completed",
                    },
                    request,
                )
                logger.info("Suscripción activada para %s · plan=%s", cid, plan)
        elif event_type == "checkout.session.expired":
            if process_booking_payment_expired_webhook(data_object):
                return {"received": True}
        elif event_type in {"customer.subscription.updated", "customer.subscription.created"}:
            sub_id = data_object.get("id", "")
            status_str = data_object.get("status", "")
            current_period_end = data_object.get("current_period_end")
            current_period_start = data_object.get("current_period_start")
            cancel_at_period_end_flag = bool(data_object.get("cancel_at_period_end"))
            cid = (data_object.get("metadata") or {}).get("cliente_id")
            plan = (data_object.get("metadata") or {}).get("plan")
            # Self-serve first: match by stripe_subscription_id in subscriptions table.
            with _get_db_connection() as _conn_ss:
                _conn_ss.row_factory = sqlite3.Row
                _ss_row = _conn_ss.execute(
                    "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?", (sub_id,)
                ).fetchone()
            if _ss_row:
                period_end_iso = (
                    datetime.fromtimestamp(int(current_period_end), tz=timezone.utc).isoformat()
                    if current_period_end else (_ss_row["current_period_end"] or "")
                )
                period_start_iso = (
                    datetime.fromtimestamp(int(current_period_start), tz=timezone.utc).isoformat()
                    if current_period_start else (_ss_row["current_period_start"] or "")
                )
                ss_plan = plan if plan in SELF_SERVE_PLANS else (_ss_row["plan"] or "free")
                db_set_subscription_from_stripe(
                    user_id=_ss_row["user_id"],
                    plan_slug=ss_plan,
                    stripe_customer_id=_ss_row["stripe_customer_id"] or "",
                    stripe_subscription_id=sub_id,
                    status=status_str or "active",
                    current_period_start=period_start_iso,
                    current_period_end=period_end_iso,
                    cancel_at_period_end=cancel_at_period_end_flag,
                )
                logger.info("Self-serve subscription %s user=%s status=%s", event_type, _ss_row["user_id"], status_str)
                return {"received": True}
            if not cid:
                # Buscar por subscription_id
                for candidate_cid, cfg in appstate.CONFIG_CLIENTES.items():
                    if (cfg.get("subscription") or {}).get("stripe_subscription_id") == sub_id:
                        cid = candidate_cid
                        break
            if cid and cid in appstate.CONFIG_CLIENTES:
                renews_at = ""
                if current_period_end:
                    renews_at = datetime.fromtimestamp(int(current_period_end), tz=timezone.utc).isoformat()
                fields = {"status": status_str or "active", "stripe_subscription_id": sub_id}
                if renews_at:
                    fields["renews_at"] = renews_at
                if plan and _normalize_plan_slug(plan) in PLAN_VALID:
                    fields["plan"] = _normalize_plan_slug(plan)
                _set_client_subscription(cid, **fields)
                logger.info("Suscripción actualizada %s · status=%s", cid, status_str)
        elif event_type == "customer.subscription.deleted":
            sub_id = data_object.get("id", "")
            with _get_db_connection() as _conn_ss:
                _conn_ss.row_factory = sqlite3.Row
                _ss_row = _conn_ss.execute(
                    "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?", (sub_id,)
                ).fetchone()
            if _ss_row:
                db_set_subscription_from_stripe(
                    user_id=_ss_row["user_id"],
                    plan_slug="free",
                    stripe_customer_id=_ss_row["stripe_customer_id"] or "",
                    stripe_subscription_id="",
                    status="canceled",
                )
                logger.info("Self-serve subscription cancelada user=%s", _ss_row["user_id"])
                return {"received": True}
            cid_target = None
            for candidate_cid, cfg in appstate.CONFIG_CLIENTES.items():
                if (cfg.get("subscription") or {}).get("stripe_subscription_id") == sub_id:
                    cid_target = candidate_cid
                    break
            if cid_target:
                _set_client_subscription(
                    cid_target,
                    status="canceled",
                    canceled_at=_utc_now().isoformat(),
                )
                logger.info("Suscripción cancelada %s", cid_target)
        elif event_type == "invoice.payment_failed":
            sub_id = str(data_object.get("subscription") or "")
            customer_id = str(data_object.get("customer") or "")
            customer_email = str(data_object.get("customer_email") or "")
            attempt_count = int(data_object.get("attempt_count") or 1)
            next_payment_attempt = data_object.get("next_payment_attempt")
            hosted_invoice_url = str(data_object.get("hosted_invoice_url") or "")
            amount_due_cents = int(data_object.get("amount_due") or 0)
            amount_due_eur = f"{amount_due_cents / 100:.2f}" if amount_due_cents else "-"
            next_iso = ""
            if next_payment_attempt:
                next_iso = datetime.fromtimestamp(int(next_payment_attempt), tz=timezone.utc).isoformat()
            cid_target = _find_client_by_stripe_id(customer_id=customer_id, subscription_id=sub_id)
            if cid_target and cid_target in appstate.CONFIG_CLIENTES:
                cfg = appstate.CONFIG_CLIENTES.get(cid_target) or {}
                sub_cfg = cfg.get("subscription") or {}
                _set_client_subscription(
                    cid_target,
                    status="past_due",
                    last_payment_failed_at=_utc_now().isoformat(),
                    last_payment_failed_invoice_url=hosted_invoice_url,
                )
                _send_payment_failed_emails(
                    cliente_id=cid_target,
                    customer_email=customer_email or sub_cfg.get("contacto_email", "") or "",
                    company_name=cfg.get("nombre", "") or cid_target,
                    plan=sub_cfg.get("plan", "") or cfg.get("plan", "") or PLAN_DEFAULT,
                    amount_due_eur=amount_due_eur,
                    attempt_count=attempt_count,
                    next_attempt_iso=next_iso,
                    hosted_invoice_url=hosted_invoice_url,
                    customer_id=customer_id,
                    subscription_id=sub_id,
                )
                logger.warning(
                    "invoice.payment_failed cliente=%s sub=%s intento=%s importe=%s",
                    cid_target, sub_id, attempt_count, amount_due_eur,
                )
            else:
                logger.warning(
                    "invoice.payment_failed sin cliente asociado: customer=%s sub=%s",
                    customer_id, sub_id,
                )
    except Exception as exc:  # noqa: BLE001
        logger.error("Error procesando evento Stripe %s: %s", event_type, exc)

    return {"received": True}


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
        max_users = _plan_feature(cliente_id, "max_users")
        if max_users is not None and _count_client_users(cliente_id) >= int(max_users):
            limits = _plan_limits(_client_plan(cliente_id))
            raise HTTPException(
                status_code=403,
                detail=f"Tu plan {limits.get('label')} permite hasta {max_users} usuario(s). Sube de plan para añadir más."
            )
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
    if not _email_delivery_configured():
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


@app.get("/onboarding", include_in_schema=False)
async def onboarding_entry(
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
) -> Response:
    user = _get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso?next=/onboarding")
    index_path = ONBOARDING_UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Wizard de onboarding no disponible.")
    html = (
        index_path.read_text(encoding="utf-8")
        .replace("__MARKETING_SITE_URL__", escape(MARKETING_SITE_URL))
        .replace("__SUPPORT_EMAIL__", escape(PORTAL_SUPPORT_EMAIL))
        .replace("__USER_EMAIL__", escape(user["email"]))
        .replace("__USER_NAME__", escape(user["display_name"]))
    )
    return HTMLResponse(html)


@app.get("/app", include_in_schema=False)
async def app_entry(
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
) -> Response:
    user = _get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso?next=/app")
    # If no cliente_id yet, push to wizard.
    if not (user["cliente_id"] or "").strip():
        return RedirectResponse("/onboarding")
    index_path = APP_UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Portal de cliente no disponible.")
    html = (
        index_path.read_text(encoding="utf-8")
        .replace("__MARKETING_SITE_URL__", escape(MARKETING_SITE_URL))
        .replace("__SUPPORT_EMAIL__", escape(PORTAL_SUPPORT_EMAIL))
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
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
) -> Response:
    user = _get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso")
    return RedirectResponse("/dashboard")


@app.get("/dashboard", include_in_schema=False)
async def dashboard(
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
) -> Response:
    user = _get_authenticated_portal_user_or_none(portal_session)
    if not user:
        return RedirectResponse("/acceso")
    if user["role"] != "admin":
        return RedirectResponse("/app")
    index_path = ADMIN_UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Panel admin no disponible.")
    return FileResponse(index_path)


@app.get("/demo/{cliente_id}", include_in_schema=False)
async def demo_cliente(cliente_id: str, request: Request) -> HTMLResponse:
    _assert_valid_client_id(cliente_id)
    _get_client_config(cliente_id)
    response = HTMLResponse(_build_demo_page(cliente_id, request))
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
    _assert_valid_client_id(cliente_id)
    config = _get_client_config(cliente_id)  # 404 si el cliente no existe
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El asistente de voz no esta disponible ahora mismo.",
        )
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"demo_voice:{cliente_id}:{client_ip}", DEMO_VOICE_RATE_LIMIT)
    voice_cfg = config.get("voice") or {}
    max_seconds = int(voice_cfg.get("max_duration_seconds") or 0) or DEMO_VOICE_MAX_SECONDS
    return await _mint_voice_session(cliente_id, config, max_seconds=max_seconds, log_tag="demo-voice")


@app.post("/demo/{cliente_id}/voice/tool", include_in_schema=False)
async def demo_voice_tool(cliente_id: str, request: Request) -> Dict[str, Any]:
    """Ejecuta una tool de la voz en navegador (demo publica). El navegador habla directo con
    OpenAI por WebRTC; cuando el modelo pide una funcion, el front la reenvia aqui y devolvemos
    el resultado para que lo cuente en voz. Sin esto, el modelo se quedaria esperando un
    function_call_output que nadie produce (silencio largo). Solo lectura: ver _voice_dispatch_tool_demo."""
    _assert_valid_client_id(cliente_id)
    _get_client_config(cliente_id)  # 404 si el cliente no existe
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"demo_voice_tool:{cliente_id}:{client_ip}", 30)
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
    return await _voice_dispatch_tool_demo(cliente_id, name, arguments)


@app.post("/demo/generate", response_model=DemoGenerateResponse)
async def demo_generate(data: DemoGeneratePayload, request: Request) -> DemoGenerateResponse:
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"demo:{client_ip}", 3)

    _purge_expired_demos()
    registry = _load_demo_registry()
    email_lower = str(data.email).lower()
    now_ts = time.time()
    for existing_id, created_ts in registry.items():
        cfg = appstate.CONFIG_CLIENTES.get(existing_id, {})
        contacto_existing = cfg.get("contacto", {})
        if (
            str(contacto_existing.get("email", "")).lower() == email_lower
            and now_ts - created_ts < DEMO_TTL_SECONDS
        ):
            existing_url = f"{_public_base_url(request)}/demo/{existing_id}"
            expires_dt = datetime.fromtimestamp(created_ts + DEMO_TTL_SECONDS, tz=timezone.utc)
            remaining = max(0, int(created_ts + DEMO_TTL_SECONDS - now_ts))
            return DemoGenerateResponse(
                ok=True,
                cliente_id=existing_id,
                demo_url=existing_url,
                expires_at=expires_dt.isoformat(),
                expires_in_seconds=remaining,
            )

    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de demos no esta disponible en este momento.",
        )

    base_slug = slugify_company(data.nombre_empresa).lower()[:30] or "empresa"
    token = secrets.token_hex(3)
    cliente_id = f"{DEMO_TENANT_PREFIX}{base_slug}_{token}"
    _assert_valid_client_id(cliente_id)

    sector_clean = data.sector.strip()
    _sector_defaults = _DEMO_SECTOR_DEFAULTS.get(sector_clean, (
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

    base_app = (APP_BASE_URL or "https://app.vantelia.es").rstrip("/")
    allowed_origins.append(base_app)
    for origin in ("https://www.vantelia.es", "https://vantelia.es"):
        if origin not in allowed_origins:
            allowed_origins.append(origin)

    if data.website_url:
        try:
            scrape_result = await asyncio.to_thread(
                run_onboarding,
                website_url=data.website_url,
                api_key=OPENAI_API_KEY,
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
            logger.warning("Demo scraping fallo para %s: %s", data.website_url, exc)

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
        info_txt=info_txt[:120000],
        reindex_after_save=True,
    )

    try:
        await asyncio.to_thread(_save_admin_client_payload, cliente_id, payload, request)
        if scrape_result is not None:
            _seed_qa_from_onboarding(cliente_id, scrape_result)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Error guardando demo %s: %s", cliente_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se ha podido generar la demo. Intentalo de nuevo en unos minutos.",
        ) from exc

    _register_demo_tenant(cliente_id)

    expires_dt = _utc_now() + timedelta(seconds=DEMO_TTL_SECONDS)
    demo_url = f"{_public_base_url(request)}/demo/{cliente_id}"

    try:
        if globals().get("OUTREACH_AVAILABLE"):
            with _outreach_db() as outreach_conn:
                outreach_conn.execute(
                    "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,?,?)",
                    (
                        email_lower,
                        "demo_generated",
                        "cold",
                        demo_url,
                        _utc_now().isoformat(timespec="seconds"),
                        request.headers.get("user-agent", "")[:200],
                        client_ip[:64],
                    ),
                )
                outreach_conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("No se pudo registrar demo_generated en outreach: %s", exc)

    if _email_delivery_configured() and CONSULTA_NOTIFICATION_EMAIL:
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
            _send_email_message(
                CONSULTA_NOTIFICATION_EMAIL,
                asunto,
                cuerpo_text,
                cuerpo_html,
                reply_to=str(data.email),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo notificar lead de demo: %s", exc)

    logger.info(
        "Demo creada %s para %s desde IP %s (expira en %ss)",
        cliente_id, data.email, client_ip, DEMO_TTL_SECONDS,
    )

    return DemoGenerateResponse(
        ok=True,
        cliente_id=cliente_id,
        demo_url=demo_url,
        expires_at=expires_dt.isoformat(),
        expires_in_seconds=DEMO_TTL_SECONDS,
    )












@app.post("/analytics/event")
async def analytics_event(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Payload JSON invalido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload de analitica invalido.")
    return _record_analytics_event(payload, request)


@app.post("/consulta")
async def solicitar_consulta(data: ConsultaLeadPayload, request: Request) -> Dict[str, Any]:
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(f"consulta:{client_ip}", 5)

    servicio_texto = data.servicio or "No especificado"
    empresa_texto  = data.empresa  or "No especificada"
    telefono_texto = data.telefono or "No proporcionado"
    mensaje_texto  = data.mensaje  or "(sin mensaje)"

    fecha_utc = _utc_now().strftime('%Y-%m-%d %H:%M UTC')

    asunto_admin = "Nueva consulta recibida"
    cuerpo_admin_text = (
        f"Tienes una nueva consulta desde la web.\n\n"
        f"Nombre:   {data.nombre}\n"
        f"Email:    {data.email}\n"
        f"Teléfono: {telefono_texto}\n"
        f"Empresa:  {empresa_texto}\n"
        f"Servicio: {servicio_texto}\n\n"
        f"Mensaje:\n{mensaje_texto}\n\n"
        f"---\nIP de origen: {client_ip}\n"
        f"Fecha: {fecha_utc}\n"
    )
    cuerpo_admin_html = f"""
<div style="font-family:sans-serif;max-width:560px;margin:0 auto;color:#1a1a2e">
  <h2 style="color:#00b1d9">Nueva consulta recibida</h2>
  <p style="color:#333">Tienes una nueva consulta desde la web.</p>
  <table style="width:100%;border-collapse:collapse">
    <tr><td style="padding:6px 0;color:#666;width:110px">Nombre</td><td style="padding:6px 0;font-weight:600">{escape(data.nombre)}</td></tr>
    <tr><td style="padding:6px 0;color:#666">Email</td><td style="padding:6px 0"><a href="mailto:{escape(data.email)}">{escape(data.email)}</a></td></tr>
    <tr><td style="padding:6px 0;color:#666">Teléfono</td><td style="padding:6px 0">{escape(telefono_texto)}</td></tr>
    <tr><td style="padding:6px 0;color:#666">Empresa</td><td style="padding:6px 0">{escape(empresa_texto)}</td></tr>
    <tr><td style="padding:6px 0;color:#666">Servicio</td><td style="padding:6px 0">{escape(servicio_texto)}</td></tr>
  </table>
  <p style="margin-top:16px;color:#333"><strong>Mensaje:</strong><br>{escape(mensaje_texto).replace(chr(10), '<br>')}</p>
  <hr style="margin:20px 0;border:none;border-top:1px solid #eee">
  <p style="font-size:12px;color:#999">IP: {escape(client_ip)} · {fecha_utc}</p>
</div>"""

    asunto_cliente = "Hemos recibido tu consulta"
    cuerpo_cliente_text = (
        f"Hola {data.nombre},\n\n"
        "Hemos recibido tu consulta correctamente. Nos pondremos en contacto contigo "
        "lo antes posible (normalmente en menos de 24 horas).\n\n"
        "Resumen de tu solicitud:\n"
        f"  · Servicio: {servicio_texto}\n"
        f"  · Empresa:  {empresa_texto}\n"
        f"  · Mensaje:  {mensaje_texto}\n\n"
        "Si necesitas añadir información, responde directamente a este correo.\n\n"
        "Un saludo,\nEquipo Vantelia\nhttps://www.vantelia.es\n"
    )
    cuerpo_cliente_html = f"""
<div style="font-family:sans-serif;max-width:560px;margin:0 auto;color:#1a1a2e">
  <h2 style="color:#00b1d9">Hemos recibido tu consulta</h2>
  <p style="color:#333">Hola <strong>{escape(data.nombre)}</strong>,</p>
  <p style="color:#333;line-height:1.55">
    Hemos recibido tu consulta correctamente. Nos pondremos en contacto contigo lo antes
    posible (normalmente en menos de 24 horas).
  </p>
  <table style="width:100%;border-collapse:collapse;margin-top:12px">
    <tr><td style="padding:6px 0;color:#666;width:110px">Servicio</td><td style="padding:6px 0">{escape(servicio_texto)}</td></tr>
    <tr><td style="padding:6px 0;color:#666">Empresa</td><td style="padding:6px 0">{escape(empresa_texto)}</td></tr>
    <tr><td style="padding:6px 0;color:#666;vertical-align:top">Mensaje</td><td style="padding:6px 0">{escape(mensaje_texto).replace(chr(10), '<br>')}</td></tr>
  </table>
  <p style="margin-top:18px;color:#333">
    Si necesitas añadir información, responde directamente a este correo.
  </p>
  <p style="margin-top:24px;color:#333">Un saludo,<br><strong>Equipo Vantelia</strong></p>
  <hr style="margin:20px 0;border:none;border-top:1px solid #eee">
  <p style="font-size:12px;color:#999">Este es un mensaje automático desde info@vantelia.es · <a href="https://www.vantelia.es" style="color:#00b1d9">vantelia.es</a></p>
</div>"""

    notif_sent = False
    confirm_sent = False
    if _email_delivery_configured():
        try:
            _send_email_message(
                CONSULTA_NOTIFICATION_EMAIL,
                asunto_admin,
                cuerpo_admin_text,
                cuerpo_admin_html,
                reply_to=str(data.email),
            )
            notif_sent = True
        except Exception as exc:
            logger.error("Error enviando notificacion de consulta a %s: %s", CONSULTA_NOTIFICATION_EMAIL, exc)
        try:
            _send_email_message(
                str(data.email),
                asunto_cliente,
                cuerpo_cliente_text,
                cuerpo_cliente_html,
            )
            confirm_sent = True
        except Exception as exc:
            logger.error("Error enviando confirmacion de consulta a %s: %s", data.email, exc)
    else:
        logger.warning("Canal de email no configurado: no se han enviado emails de la consulta de %s", data.email)

    logger.info(
        "Consulta recibida de %s <%s> (IP: %s) notif=%s confirm=%s",
        data.nombre, data.email, client_ip, notif_sent, confirm_sent,
    )
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
        "clientes_configurados": len(appstate.CONFIG_CLIENTES),
        "checks": checks,
        "runtime": {
            "started_at": appstate.STARTED_AT.isoformat(),
            "uptime_seconds": int((_utc_now() - appstate.STARTED_AT).total_seconds()),
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
        _seed_qa_from_onboarding(cliente_id, result)

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
    owners_by_cliente: Dict[str, Dict[str, Any]] = {}
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
        owner_rows = connection.execute(
            """
            SELECT c.cliente_id AS cliente_id,
                   c.owner_user_id AS owner_user_id,
                   c.created_at AS cliente_created_at,
                   u.email AS owner_email,
                   u.display_name AS owner_display_name,
                   u.last_login_at AS owner_last_login_at,
                   u.created_at AS owner_created_at
            FROM clientes c
            LEFT JOIN users u ON u.id = c.owner_user_id
            """
        ).fetchall()
        owners_by_cliente = {
            row["cliente_id"]: {
                "owner_user_id": row["owner_user_id"] or "",
                "owner_email": row["owner_email"] or "",
                "owner_display_name": row["owner_display_name"] or "",
                "owner_last_login_at": row["owner_last_login_at"] or "",
                "owner_created_at": row["owner_created_at"] or "",
                "cliente_created_at": row["cliente_created_at"] or "",
            }
            for row in owner_rows
        }

    demo_registry = _load_demo_registry()
    now_ts = time.time()

    for cliente_id, config in sorted(appstate.CONFIG_CLIENTES.items(), key=lambda item: item[0].lower()):
        owner_uid_early = (owners_by_cliente.get(cliente_id) or {}).get("owner_user_id") or ""
        booking_cfg = config.get("booking", {})
        whatsapp_cfg = config.get("whatsapp", {})
        voice_cfg = config.get("voice", {})
        contacto = config.get("contacto", {})
        branding = config.get("branding", {})
        info_path = _client_info_path(cliente_id)
        client_counts = booking_counts.get(cliente_id, {})

        # Reclamado (con dueño) => cliente real, no demo, aunque conserve el prefijo.
        is_demo = (
            cliente_id.startswith(DEMO_TENANT_PREFIX) or cliente_id in demo_registry
        ) and not owner_uid_early
        demo_expires_at = ""
        demo_remaining = 0
        if is_demo and cliente_id in demo_registry:
            created_ts = demo_registry[cliente_id]
            expires_ts = created_ts + DEMO_TTL_SECONDS
            demo_remaining = max(0, int(expires_ts - now_ts))
            demo_expires_at = datetime.fromtimestamp(expires_ts, tz=timezone.utc).isoformat()

        sub = _client_subscription(cliente_id) if not is_demo else {
            "plan": "", "status": "", "stripe_subscription_id": "",
            "messages_quota": 0, "messages_used_period": 0,
        }
        owner_info = owners_by_cliente.get(cliente_id, {})
        owner_uid = (owner_info.get("owner_user_id") or "").strip()
        if owner_uid:
            ss_sub = db_get_subscription_for_user(owner_uid)
            if ss_sub:
                sub = dict(sub)
                sub["plan"] = ss_sub["plan"] or sub.get("plan") or "free"
                sub["status"] = ss_sub["status"] or sub.get("status") or "active"
                sub["messages_quota"] = int(ss_sub["messages_quota"] or 0)
                sub["messages_used_period"] = int(ss_sub["messages_used_period"] or 0)

        summaries.append(
            AdminClienteResumen(
                cliente_id=cliente_id,
                nombre=config["nombre"],
                owner_user_id=owner_info.get("owner_user_id", ""),
                owner_email=owner_info.get("owner_email", ""),
                owner_display_name=owner_info.get("owner_display_name", ""),
                owner_last_login_at=owner_info.get("owner_last_login_at", ""),
                owner_created_at=owner_info.get("owner_created_at", ""),
                cliente_created_at=owner_info.get("cliente_created_at", ""),
                plan=str(sub.get("plan") or "free") if (owner_info.get("owner_user_id") or sub.get("plan")) else "",
                messages_used=int(sub.get("messages_used_period") or 0),
                messages_quota=int(sub.get("messages_quota") or 0),
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
                voice_enabled=bool(voice_cfg.get("enabled", False)),
                voice_phone_number=str(voice_cfg.get("twilio_phone_number", "")),
                has_info_file=info_path.exists(),
                info_file_size=(info_path.stat().st_size if info_path.exists() else 0),
                bookings_total=int(client_counts.get("total", 0)),
                bookings_pending=int(client_counts.get("pending", 0)),
                is_demo=is_demo,
                demo_expires_at=demo_expires_at,
                demo_expires_in_seconds=demo_remaining,
                subscription_plan=str(sub.get("plan") or ""),
                subscription_status=str(sub.get("status") or ""),
                stripe_subscription_id=str(sub.get("stripe_subscription_id") or ""),
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


@app.get(
    "/admin/clientes/{cliente_id}/audit",
    dependencies=[Depends(_require_admin_token)],
    response_model=AdminClienteAuditResponse,
)
async def admin_cliente_audit(cliente_id: str) -> AdminClienteAuditResponse:
    _assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")

    def _duration_seconds(started_at: str, ended_at: str) -> Optional[int]:
        if not started_at or not ended_at:
            return None
        try:
            start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            return max(0, int((end_dt - start_dt).total_seconds()))
        except ValueError:
            return None

    with _get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT admin_email, started_at, ended_at, ip, user_agent
            FROM admin_impersonations
            WHERE target_cliente_id = ?
            ORDER BY started_at DESC
            LIMIT 50
            """,
            (cliente_id,),
        ).fetchall()

    return AdminClienteAuditResponse(
        cliente_id=cliente_id,
        items=[
            AdminClienteAuditEntry(
                admin_email=row["admin_email"] or "",
                started_at=row["started_at"] or "",
                ended_at=row["ended_at"] or "",
                ip=row["ip"] or "",
                user_agent=row["user_agent"] or "",
                duration_seconds=_duration_seconds(row["started_at"] or "", row["ended_at"] or ""),
            )
            for row in rows
        ],
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


@app.delete(
    "/admin/clientes/{cliente_id}",
    dependencies=[Depends(_require_admin_token)],
    response_model=AuthSimpleResponse,
)
async def admin_eliminar_cliente(cliente_id: str) -> AuthSimpleResponse:
    _delete_client_everywhere(cliente_id)
    return AuthSimpleResponse(ok=True, message=f"Cliente {cliente_id} eliminado correctamente.")


@app.post(
    "/admin/clientes/{cliente_id}/demo-agenda",
    dependencies=[Depends(_require_admin_token)],
    response_model=AuthSimpleResponse,
)
async def admin_generar_demo_agenda(cliente_id: str) -> AuthSimpleResponse:
    """Genera datos de demostracion en la agenda del cliente (~1 mes de citas
    repartidas entre varios profesionales) para que vea como luce su calendario.
    Es idempotente: regenera limpiando los datos demo anteriores."""
    _assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    result = _seed_demo_agenda(cliente_id)
    return AuthSimpleResponse(
        ok=True,
        message=(
            f"Agenda demo generada: {result['bookings_created']} citas en "
            f"{result['employees_created']} profesionales."
        ),
    )


@app.delete(
    "/admin/clientes/{cliente_id}/demo-agenda",
    dependencies=[Depends(_require_admin_token)],
    response_model=AuthSimpleResponse,
)
async def admin_borrar_demo_agenda(cliente_id: str) -> AuthSimpleResponse:
    """Borra todos los datos de demostracion de la agenda del cliente
    (citas con source='demo_seed' y profesionales demo 'empdemo_*')."""
    _assert_valid_client_id(cliente_id)
    result = _purge_demo_agenda(cliente_id)
    return AuthSimpleResponse(
        ok=True,
        message=(
            f"Agenda demo eliminada: {result['bookings_removed']} citas y "
            f"{result['employees_removed']} profesionales demo."
        ),
    )


class AdminServicePatchPayload(BaseModel):
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=600)
    price_cents: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


@app.patch(
    "/admin/services/{cliente_id}/{slug}",
    dependencies=[Depends(_require_admin_token)],
)
async def admin_patch_service(
    cliente_id: str,
    slug: str,
    data: AdminServicePatchPayload,
) -> Dict[str, Any]:
    """Actualiza duración, precio o estado de un servicio del catálogo sin requerir sesión portal."""
    _assert_valid_client_id(cliente_id)
    updates: Dict[str, Any] = {}
    if data.duration_minutes is not None:
        updates["duration_minutes"] = int(data.duration_minutes)
    if data.price_cents is not None:
        updates["price_cents"] = int(data.price_cents)
    if data.is_active is not None:
        updates["is_active"] = 1 if data.is_active else 0
    if not updates:
        raise HTTPException(status_code=400, detail="Nada que actualizar.")
    updates["updated_at"] = _utc_now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _get_db_connection() as conn:
        row = conn.execute(
            "SELECT slug FROM services WHERE cliente_id = ? AND slug = ?", (cliente_id, slug)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Servicio '{slug}' no encontrado para {cliente_id}.")
        conn.execute(
            f"UPDATE services SET {set_clause} WHERE cliente_id = ? AND slug = ?",
            (*updates.values(), cliente_id, slug),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT slug, name, duration_minutes, price_cents, is_active FROM services WHERE cliente_id = ? AND slug = ?",
            (cliente_id, slug),
        ).fetchone()
    return {"ok": True, "slug": updated["slug"], "name": updated["name"],
            "duration_minutes": updated["duration_minutes"], "price_cents": updated["price_cents"],
            "is_active": bool(updated["is_active"])}


class AdminVoicePayload(BaseModel):
    enabled: Optional[bool] = None
    twilio_phone_number: Optional[str] = Field(default=None, max_length=32)
    openai_voice: Optional[str] = Field(default=None, max_length=40)
    greeting: Optional[str] = Field(default=None, max_length=600)


@app.post("/admin/clientes/{cliente_id}/voice", dependencies=[Depends(_require_admin_token)])
async def admin_set_voice(cliente_id: str, data: AdminVoicePayload) -> Dict[str, Any]:
    """Activa/configura el canal de voz de un cliente sin requerir sesión portal.

    Persiste el cambio en config.json (duradero: el deploy preserva el config de
    producción). Devuelve también diagnóstico del gate de plan y de las credenciales
    Twilio del backend para depurar por qué una llamada podría no entrar.
    """
    _assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail=f"Cliente '{cliente_id}' no encontrado.")
    with appstate.state_lock:
        next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
        cfg = next_configs.get(cliente_id, {})
        voice = dict(cfg.get("voice", {}) or {})
        if data.enabled is not None:
            if data.enabled and not _client_voice_plan_enabled(cliente_id):
                raise HTTPException(
                    status_code=403,
                    detail="El asistente de voz requiere plan Business para este cliente.",
                )
            voice["enabled"] = bool(data.enabled)
        if data.twilio_phone_number is not None:
            voice["twilio_phone_number"] = _sanitize_text(data.twilio_phone_number)[:32]
        if data.openai_voice is not None:
            v = _sanitize_text(data.openai_voice).lower()
            voice["openai_voice"] = v if v in VOICE_ALLOWED_OPENAI_VOICES else (voice.get("openai_voice") or "alloy")
        if data.greeting is not None:
            voice["greeting"] = _sanitize_text(data.greeting, allow_multiline=True)[:600]
        cfg["voice"] = voice
        next_configs[cliente_id] = cfg
        _update_runtime_configs(next_configs)
    _persist_configs_to_disk(next_configs)
    resolved = _get_voice_config(cliente_id)
    return {
        "ok": True,
        "cliente_id": cliente_id,
        "voice_enabled": bool(voice.get("enabled")),
        "twilio_phone_number": voice.get("twilio_phone_number", ""),
        "plan_allows_voice": _client_voice_plan_enabled(cliente_id),
        "twilio_backend_configured": _voice_twilio_configured(),
        "openai_configured": bool(OPENAI_API_KEY),
        "webhook_active": resolved is not None,
        "webhook_url": f"{APP_BASE_URL.rstrip('/')}/voice/{cliente_id}" if APP_BASE_URL else f"/voice/{cliente_id}",
    }


class AdminClienteAssignOwnerPayload(BaseModel):
    email: EmailStr
    plan: str = Field(default="free", max_length=40)


@app.post(
    "/admin/clientes/{cliente_id}/assign-owner",
    dependencies=[Depends(_require_admin_token)],
    response_model=AuthSimpleResponse,
)
async def admin_assign_cliente_owner(
    cliente_id: str,
    data: AdminClienteAssignOwnerPayload,
) -> AuthSimpleResponse:
    """Admin path for migrating legacy clientes into the self-serve model.

    Looks up (or rejects if missing) a user by email, binds them as the
    owner_user_id of cliente_id, and seeds a subscription. Used to migrate
    existing config.json clients into Vantelia 2.0 without forcing them to
    re-register through the wizard."""
    _assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    target_email = _normalize_email(data.email)
    user = _get_user_by_email(target_email)
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"No existe usuario con email {target_email}. Crealo primero (POST /auth/users) o usa /auth/signup.",
        )
    existing_cid = (user["cliente_id"] or "").strip()
    if existing_cid and existing_cid != cliente_id:
        raise HTTPException(
            status_code=409,
            detail=f"El usuario ya tiene asignado el bot {existing_cid}.",
        )
    db_set_client_owner(cliente_id, user["id"], source="admin_migration")
    with _get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET cliente_id = ? WHERE id = ?",
            (cliente_id, user["id"]),
        )
        connection.commit()
    # Seed subscription with the requested plan (default free).
    plan_slug = (data.plan or "free").lower()
    if plan_slug not in SELF_SERVE_PLANS:
        plan_slug = "free"
    if plan_slug == "free":
        db_ensure_free_subscription(user["id"], cliente_id=cliente_id)
    else:
        db_set_subscription_from_stripe(
            user_id=user["id"],
            plan_slug=plan_slug,
            status="active",
        )
    return AuthSimpleResponse(
        ok=True,
        message=f"Cliente {cliente_id} asignado a {target_email} (plan {plan_slug}).",
    )


@app.post(
    "/admin/clientes/{cliente_id}/impersonate",
    response_model=AdminImpersonateResponse,
)
async def admin_impersonate_cliente(
    cliente_id: str,
    request: Request,
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
    admin: Dict[str, str] = Depends(_require_admin_identity),
) -> Response:
    """Admin opens cliente's portal as the cliente owner.

    Creates a short-lived auth_sessions row stamped with impersonator_* fields,
    sets the portal cookie, and audits the action in admin_impersonations.
    The portal banner picks up the impersonation flag via /auth/me.
    """
    _assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no encontrado.")
    with _get_db_connection() as connection:
        row = connection.execute(
            "SELECT owner_user_id FROM clientes WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchone()
    target_user_id = (row["owner_user_id"] if row else "") or ""
    if not target_user_id:
        raise HTTPException(
            status_code=409,
            detail="El cliente no tiene un owner asignado. Usa /admin/clientes/{id}/assign-owner primero.",
        )
    target_user = _get_user_by_id(target_user_id)
    if not target_user or not target_user["is_active"]:
        raise HTTPException(status_code=409, detail="El owner del cliente no está activo.")
    if target_user["role"] == "admin":
        raise HTTPException(status_code=403, detail="No se puede impersonar a otro admin.")

    ip = request.client.host if request.client else ""
    user_agent = (request.headers.get("user-agent") or "")[:512]
    raw_token, session_id = _create_impersonation_session(
        target_user_id=target_user["id"],
        admin_user_id=admin["user_id"],
        admin_email=admin["email"],
        ip=ip,
    )
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO admin_impersonations
                (id, admin_user_id, admin_email, target_user_id, target_cliente_id,
                 session_id, started_at, ip, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"imp_{secrets.token_hex(8)}",
                admin["user_id"],
                admin["email"],
                target_user["id"],
                cliente_id,
                session_id,
                _utc_now_iso(),
                ip,
                user_agent,
            ),
        )
        connection.commit()

    logger.info(
        "[admin] impersonate admin=%s cliente=%s target=%s ttl_min=%s",
        admin["email"], cliente_id, target_user["email"], ADMIN_IMPERSONATION_TTL_MINUTES,
    )

    response = JSONResponse(
        AdminImpersonateResponse(
            ok=True,
            cliente_id=cliente_id,
            target_user_id=target_user["id"],
            target_email=target_user["email"],
            expires_in_minutes=ADMIN_IMPERSONATION_TTL_MINUTES,
            redirect_url="/app?as_admin=1",
        ).model_dump()
    )
    response.headers["Cache-Control"] = "no-store"
    if portal_session and admin.get("via") == "session":
        _set_admin_return_cookie(response, portal_session)
    else:
        _clear_admin_return_cookie(response)
    _set_portal_cookie(response, raw_token)
    return response


@app.post(
    "/admin/impersonate/end",
    response_model=AdminImpersonateEndResponse,
)
async def admin_impersonate_end(
    portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_COOKIE_NAME),
    admin_return_session: Optional[str] = Cookie(default=None, alias=ADMIN_RETURN_COOKIE_NAME),
) -> Response:
    """Closes the impersonated session and returns the admin to the dashboard.

    Safe to call without admin auth: the cookie itself proves ownership of
    the impersonation. If the cookie is not an impersonation, behaves as a
    plain logout for that token.
    """
    user_row = _get_authenticated_portal_user_or_none(portal_session)
    was_impersonated = _session_is_impersonated(user_row)
    if was_impersonated:
        admin_email = _session_impersonator_email(user_row)
        with _get_db_connection() as connection:
            connection.execute(
                "UPDATE admin_impersonations SET ended_at = ? WHERE session_id = ? AND ended_at = ''",
                (_utc_now_iso(), user_row["session_id"]),
            )
            connection.commit()
        logger.info("[admin] impersonate end admin=%s session=%s", admin_email, user_row["session_id"])
    if portal_session:
        _delete_auth_session(portal_session)
    admin_redirect_url = "/acceso"
    admin_row = _get_authenticated_portal_user_or_none(admin_return_session) if was_impersonated else None
    response = JSONResponse(
        AdminImpersonateEndResponse(
            ok=True,
            admin_redirect_url="/dashboard" if admin_row and admin_row["role"] == "admin" else admin_redirect_url,
        ).model_dump()
    )
    response.headers["Cache-Control"] = "no-store"
    if admin_row and admin_row["role"] == "admin":
        _set_portal_cookie(response, admin_return_session or "")
    else:
        _clear_portal_cookie(response)
    _clear_admin_return_cookie(response)
    return response


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
        await _send_booking_reminder_by_kind(refreshed, "cancelled", request)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se ha podido enviar el aviso de cancelacion %s: %s", booking_id, exc)
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
        await _send_booking_reminder_by_kind(refreshed, "cancelled", request)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se ha podido enviar el aviso de cancelacion %s: %s", refreshed["id"], exc)
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

    launcher_shape = str(config.get("launcher_shape", "circle") or "circle").lower()
    if launcher_shape not in ("circle", "bar"):
        launcher_shape = "circle"
    try:
        launcher_size = int(config.get("launcher_size", 60) or 60)
    except (TypeError, ValueError):
        launcher_size = 60
    if launcher_shape == "circle":
        launcher_size = max(48, min(96, launcher_size))
    else:
        launcher_size = max(120, min(280, launcher_size))

    booking_enabled = bool(config["booking"]["enabled"]) and _client_booking_plan_enabled(cliente_id)
    starter_questions = _resolve_widget_starters(config, booking_enabled=booking_enabled)

    return ConfigPublicaCliente(
        nombre=config["nombre"],
        icono=config["icono"],
        color=config["color"],
        accent_color=config.get("accent_color", ""),
        logo_url=config.get("logo_url", ""),
        launcher_shape=launcher_shape,
        launcher_size=launcher_size,
        bienvenida=config["bienvenida"],
        booking_enabled=booking_enabled,
        branding_text=branding.get("powered_by", "Powered by Vantelia"),
        contact_email=contacto.get("email", ""),
        contact_phone=contacto.get("telefono", ""),
        starter_questions=starter_questions,
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

    # Self-serve quota (Sem 5): only applies to clientes owned by a self-serve user.
    # Legacy clients fall through to the original public-plan checks below.
    self_serve_sub = db_check_self_serve_quota(data.cliente_id)

    if not self_serve_sub:
        # Plan legacy: bloquear si suscripción cancelada o se supera límite mensual
        _require_active_subscription(data.cliente_id)
        sub = _client_subscription(data.cliente_id)
        if sub.get("status") in {"canceled", "past_due"}:
            raise HTTPException(status_code=402, detail="La suscripción de este asistente no está activa.")
        conv_limit = _plan_limits(sub["plan"]).get("monthly_conversations")
        if conv_limit is not None and _count_conversations_this_month(data.cliente_id) >= int(conv_limit):
            raise HTTPException(
                status_code=429,
                detail="Se ha alcanzado el límite mensual de conversaciones del plan. Contacta con la empresa para ampliar el plan.",
            )

    session_id = _normalize_session_id(data.session_id)
    try:
        response = await _process_chat_message(
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

    # Count this bot reply against the owner's monthly quota (only for self-serve).
    if self_serve_sub:
        try:
            db_increment_message_usage(data.cliente_id, count=1, kind="bot_reply")
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo incrementar usage en %s: %s", data.cliente_id, exc)
    return response


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
    if not _client_booking_plan_enabled(cliente_id):
        raise _booking_plan_unavailable_error()

    selected_day = _parse_date(fecha)
    _validate_booking_window(cliente_id, selected_day)

    try:
        if employee_id:
            employee_row = _resolve_employee_for_booking(cliente_id, employee_id)
            slots, available_slots = await _employee_slot_sets_for_day(
                cliente_id,
                fecha,
                employee_row=employee_row,
                servicio=servicio,
            )

            return RespuestaDisponibilidad(
                fecha=fecha,
                timezone=employee_row["timezone"] or config["booking"]["timezone"],
                employee_id=employee_row["id"],
                slots=[
                    SlotDisponibilidad(hora=hora, disponible=hora in available_slots)
                    for hora in sorted(slots)
                ],
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
    if not _client_booking_plan_enabled(data.cliente_id):
        raise _booking_plan_unavailable_error()

    # Plan: límite mensual de citas
    _require_active_subscription(data.cliente_id)
    booking_limit = _plan_limits(_client_plan(data.cliente_id)).get("monthly_bookings")
    if booking_limit is not None and _count_bookings_this_month(data.cliente_id) >= int(booking_limit):
        raise HTTPException(
            status_code=429,
            detail="Se ha alcanzado el límite mensual de citas del plan. Contacta con la empresa para ampliar el plan.",
        )

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

    service_row = _find_service_by_name(data.cliente_id, servicio)
    service_duration = _service_duration_minutes(data.cliente_id, servicio, employee_row)
    service_id = service_row["slug"] if service_row else ""
    service_price = int(service_row["price_cents"]) if service_row else 0

    if not await _booking_slot_available(
        data.cliente_id, booking_date, booking_time,
        employee_id=employee_row["id"], duration_minutes=service_duration,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese horario ya no esta disponible. Elige otro tramo.",
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
        duration_minutes=service_duration,
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
        **_booking_blank_tracking_fields(),
        "service_id": service_id,
        "service_price_cents": service_price,
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
            await _send_booking_reminder_by_kind(
                booking_row,
                email_status_key,
                request,
                sent_column="confirmation_email_sent_at",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("No se ha podido enviar el aviso de booking %s: %s", booking_id, exc)
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

    stored_booking = _get_booking_row_by_id(booking_id)
    payment_row = _booking_payment_row(booking_id)
    return RespuestaAgendado(
        ok=True,
        booking_id=booking_id,
        estado=stored_booking["status"] if stored_booking else booking_status,
        mensaje=config["booking"]["success_message"],
        employee_id=employee_row["id"],
        employee_name=employee_row["name"],
        provider_name=provider_result.provider_name,
        provider_booking_id=provider_result.provider_booking_id,
        provider_booking_url=provider_result.provider_booking_url,
        manage_url=_build_booking_manage_url(manage_token, request),
        payment_status=stored_booking["payment_status"] if stored_booking else "not_required",
        payment_url=payment_row["checkout_url"] if payment_row else "",
    )


@app.get("/servicios/{cliente_id}")
async def servicios(cliente_id: str, request: Request, employee_id: str = "") -> Dict[str, List[Dict[str, Any]]]:
    _assert_valid_client_id(cliente_id)
    _enforce_allowed_origin(request, cliente_id)
    return {"servicios": _public_services_for_booking(cliente_id, employee_id)}


@app.post("/auth/services", response_model=ServicePublic)
async def auth_create_service(
    data: ServicePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ServicePublic:
    target_client_id = _portal_client_id_or_403(user, cliente_id)
    _ensure_services_seeded(target_client_id)
    name = _sanitize_text(data.nombre)
    slug = _normalize_service_id(name)
    if not name or not slug:
        raise HTTPException(status_code=400, detail="Nombre de servicio invalido.")
    if _get_service_row(target_client_id, slug):
        raise HTTPException(status_code=409, detail="Ya existe un servicio con ese nombre.")
    now = _utc_now_iso()
    with _get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO services
            (cliente_id, slug, name, duration_minutes, price_cents, description, is_active, sort_order,
             payment_mode, payment_type, deposit_amount_cents, currency, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_client_id, slug, name, int(data.duration_minutes), int(data.price_cents),
                _sanitize_text(data.descripcion, allow_multiline=True),
                1 if data.is_active else 0, int(data.sort_order),
                data.payment_mode, data.payment_type, int(data.deposit_amount_cents),
                data.currency.lower(), now, now,
            ),
        )
        connection.commit()
    return ServicePublic(**_service_row_to_public(_get_service_row(target_client_id, slug)))


@app.patch("/auth/services/{slug}", response_model=ServicePublic)
async def auth_update_service(
    slug: str,
    data: ServiceUpdatePayload,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> ServicePublic:
    target_client_id = _portal_client_id_or_403(user, cliente_id)
    row = _get_service_row(target_client_id, slug)
    if not row:
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    updates: Dict[str, Any] = {}
    if data.nombre is not None:
        name = _sanitize_text(data.nombre)
        if not name:
            raise HTTPException(status_code=400, detail="Nombre de servicio invalido.")
        updates["name"] = name
    if data.duration_minutes is not None:
        updates["duration_minutes"] = int(data.duration_minutes)
    if data.price_cents is not None:
        updates["price_cents"] = int(data.price_cents)
    if data.descripcion is not None:
        updates["description"] = _sanitize_text(data.descripcion, allow_multiline=True)
    if data.is_active is not None:
        updates["is_active"] = 1 if data.is_active else 0
    if data.sort_order is not None:
        updates["sort_order"] = int(data.sort_order)
    if data.payment_mode is not None:
        updates["payment_mode"] = data.payment_mode
    if data.payment_type is not None:
        updates["payment_type"] = data.payment_type
    if data.deposit_amount_cents is not None:
        updates["deposit_amount_cents"] = int(data.deposit_amount_cents)
    if data.currency is not None:
        updates["currency"] = data.currency.lower()
    if updates:
        updates["updated_at"] = _utc_now_iso()
        assignments = ", ".join(f"{col} = ?" for col in updates)
        with _get_db_connection() as connection:
            connection.execute(
                f"UPDATE services SET {assignments} WHERE cliente_id = ? AND slug = ?",
                (*updates.values(), target_client_id, slug),
            )
            connection.commit()
        updated_row = _get_service_row(target_client_id, slug)
        if updated_row is not None:
            _sync_demo_bookings_for_service(
                target_client_id,
                old_slug=slug,
                old_name=row["name"] or "",
                service_row=updated_row,
            )
    return ServicePublic(**_service_row_to_public(_get_service_row(target_client_id, slug)))


@app.delete("/auth/services/{slug}", response_model=AuthSimpleResponse)
async def auth_delete_service(
    slug: str,
    cliente_id: str = "",
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> AuthSimpleResponse:
    target_client_id = _portal_client_id_or_403(user, cliente_id)
    if not _get_service_row(target_client_id, slug):
        raise HTTPException(status_code=404, detail="Servicio no encontrado.")
    with _get_db_connection() as connection:
        connection.execute(
            "DELETE FROM services WHERE cliente_id = ? AND slug = ?", (target_client_id, slug)
        )
        connection.execute(
            "DELETE FROM service_payment_policies WHERE cliente_id = ? AND service_id = ?", (target_client_id, slug)
        )
        connection.commit()
    return AuthSimpleResponse(ok=True, message="Servicio eliminado.")








































































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




@app.post("/admin/gen-qa/{cliente_id}", dependencies=[Depends(_require_admin_token)])
async def admin_gen_qa(cliente_id: str, max_pairs: int = 5) -> Dict[str, Any]:
    """Genera y persiste hasta `max_pairs` preguntas frecuentes para el cliente.

    Flujo:
    1. Parsea la sección P:/R: del info.txt existente.
    2. Si no hay pares, intenta extracción heurística del info.txt (sin OpenAI).
    3. Solo inserta pares nuevos (deduplica por pregunta en minúsculas).
    """
    _assert_valid_client_id(cliente_id)
    info_txt = _read_info_txt(cliente_id)
    source = "none"
    created = 0

    # Paso 1: sección P:/R: estructurada
    created = _autocreate_qa_from_info(cliente_id, info_txt, "", max_pairs=max_pairs)
    if created:
        source = "info_pr_format"
    else:
        # Paso 2: heurística libre
        heuristic_pairs = _gen_qa_from_info_heuristic(info_txt, max_pairs=max_pairs)
        if heuristic_pairs:
            created = _autocreate_qa_from_info(
                cliente_id, "", "", explicit_pairs=heuristic_pairs, max_pairs=max_pairs
            )
            if created:
                source = "info_heuristic"

    with _get_db_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM kb_qa WHERE cliente_id=?", (cliente_id,)
        ).fetchone()[0]

    payment_row = _booking_payment_row(booking_id)
    stored_booking = _get_booking_row_by_id(booking_id)
    return {
        "ok": True,
        "cliente_id": cliente_id,
        "created": created,
        "source": source,
        "total_qa": total,
        "mensaje": f"Se han generado {created} nuevas preguntas frecuentes (fuente: {source}). Total en panel: {total}.",
    }


class AdminRebrainPayload(BaseModel):
    website_url: str = Field(default="", max_length=400)
    nombre_bot: str = Field(default="", max_length=40)
    tono: str = Field(default="Profesional y cercano", min_length=4, max_length=80)
    idioma: str = Field(default="Español", min_length=4, max_length=40)
    max_paginas: int = Field(default=12, ge=1, le=30)


class AdminRebrainResponse(BaseModel):
    status: str
    cliente_id: str
    website_url: str
    detected_business_name: str
    links_found: int
    info_txt_size: int
    reindexed: bool
    reindex_error: str = ""


@app.post(
    "/admin/rebrain/{cliente_id}",
    dependencies=[Depends(_require_admin_token)],
    response_model=AdminRebrainResponse,
)
async def regenerar_cerebro(cliente_id: str, data: Optional[AdminRebrainPayload] = None) -> AdminRebrainResponse:
    _assert_valid_client_id(cliente_id)
    cfg = _get_client_config(cliente_id)

    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY no esta configurada en el backend.",
        )

    payload = data or AdminRebrainPayload()
    website_url = (payload.website_url or "").strip()
    if not website_url:
        origins = list(cfg.get("allowed_origins", []) or [])
        website_url = next((o for o in origins if o.startswith("http")), "")
    if not website_url:
        raise HTTPException(
            status_code=400,
            detail="No hay website_url configurada para este cliente. Pasa website_url en el body.",
        )

    nombre_bot = (payload.nombre_bot or cfg.get("nombre") or cliente_id).strip() or "Asistente"

    try:
        result = run_onboarding(
            website_url=website_url,
            api_key=OPENAI_API_KEY,
            nombre_bot=nombre_bot,
            tono=payload.tono,
            idioma=payload.idioma,
            max_paginas=payload.max_paginas,
        )
    except Exception as exc:
        logger.exception("Error regenerando cerebro de %s", cliente_id)
        raise HTTPException(status_code=502, detail=f"Fallo el scraper: {exc}") from exc

    _write_info_txt(cliente_id, result.info_txt)
    # Sembrar Q&A del panel desde las FAQ scrapeadas (run_onboarding las saca del info.txt).
    _seed_qa_from_onboarding(cliente_id, result)

    reindexed = False
    reindex_error = ""
    try:
        _invalidate_client_runtime(cliente_id)
        cargar_indice(cliente_id)
        reindexed = True
    except Exception as exc:
        reindex_error = str(exc)
        logger.warning("No se pudo reindexar tras rebrain de %s: %s", cliente_id, exc)

    return AdminRebrainResponse(
        status="ok",
        cliente_id=cliente_id,
        website_url=result.normalized_url,
        detected_business_name=result.detected_business_name,
        links_found=len(result.links or []),
        info_txt_size=len(result.info_txt or ""),
        reindexed=reindexed,
        reindex_error=reindex_error,
    )


class AdminStatsTopCliente(BaseModel):
    cliente_id: str
    owner_email: str = ""
    plan: str = ""
    messages_used: int = 0
    messages_quota: int = 0


class AdminStatsAlta(BaseModel):
    cliente_id: str
    nombre: str = ""
    owner_email: str = ""
    created_at: str = ""


class AdminStatsChurnRiesgo(BaseModel):
    cliente_id: str
    nombre: str = ""
    owner_email: str = ""
    last_login_at: str = ""
    dias_inactivo: int = 0


class AdminStatsOverview(BaseModel):
    clientes_total: int
    clientes_activos: int
    clientes_demo: int
    clientes_sin_owner: int
    mensajes_mes: int
    mensajes_quota_mes: int
    top_clientes: List[AdminStatsTopCliente]
    altas_recientes: List[AdminStatsAlta]
    churn_riesgo: List[AdminStatsChurnRiesgo]
    generated_at: str


@app.get(
    "/admin/stats/overview",
    dependencies=[Depends(_require_admin_token)],
    response_model=AdminStatsOverview,
)
async def admin_stats_overview() -> AdminStatsOverview:
    """Compact dashboard summary for the admin Estadísticas view.

    Counts active subscriptions, monthly messages used/quota, top users,
    recent signups (7d) and churn risk (no login in 30d). One query pass.
    """
    now = _utc_now()
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    with _get_db_connection() as connection:
        cliente_rows = connection.execute(
            """
            SELECT c.cliente_id AS cliente_id,
                   c.nombre AS cliente_nombre,
                   c.created_at AS cliente_created_at,
                   c.owner_user_id AS owner_user_id,
                   u.email AS owner_email,
                   u.last_login_at AS owner_last_login_at,
                   s.plan AS plan,
                   s.status AS sub_status,
                   s.messages_used_period AS messages_used,
                   s.messages_quota AS messages_quota
            FROM clientes c
            LEFT JOIN users u ON u.id = c.owner_user_id
            LEFT JOIN subscriptions s ON s.user_id = c.owner_user_id
            """
        ).fetchall()

    clientes_total = 0
    clientes_activos = 0
    clientes_demo = 0
    clientes_sin_owner = 0
    mensajes_mes = 0
    mensajes_quota_mes = 0
    top: List[AdminStatsTopCliente] = []
    altas: List[AdminStatsAlta] = []
    churn: List[AdminStatsChurnRiesgo] = []
    demo_registry = _load_demo_registry()

    for row in cliente_rows:
        cliente_id = row["cliente_id"]
        if cliente_id.startswith(DEMO_TENANT_PREFIX) or cliente_id in demo_registry:
            clientes_demo += 1
            continue
        clientes_total += 1
        sub_status = (row["sub_status"] or "").lower()
        if sub_status in ("active", "trialing"):
            clientes_activos += 1
        if not (row["owner_user_id"] or "").strip():
            clientes_sin_owner += 1
        used = int(row["messages_used"] or 0)
        quota = int(row["messages_quota"] or 0)
        mensajes_mes += used
        mensajes_quota_mes += quota
        if used > 0:
            top.append(
                AdminStatsTopCliente(
                    cliente_id=cliente_id,
                    owner_email=row["owner_email"] or "",
                    plan=row["plan"] or "",
                    messages_used=used,
                    messages_quota=quota,
                )
            )
        created_at = row["cliente_created_at"] or ""
        if created_at and created_at >= seven_days_ago:
            altas.append(
                AdminStatsAlta(
                    cliente_id=cliente_id,
                    nombre=row["cliente_nombre"] or "",
                    owner_email=row["owner_email"] or "",
                    created_at=created_at,
                )
            )
        last_login = row["owner_last_login_at"] or ""
        if (row["owner_user_id"] or "").strip() and last_login and last_login < thirty_days_ago:
            try:
                ll_dt = datetime.fromisoformat(last_login.replace("Z", "+00:00"))
                dias = max(0, (now - ll_dt).days)
            except (TypeError, ValueError):
                dias = 0
            churn.append(
                AdminStatsChurnRiesgo(
                    cliente_id=cliente_id,
                    nombre=row["cliente_nombre"] or "",
                    owner_email=row["owner_email"] or "",
                    last_login_at=last_login,
                    dias_inactivo=dias,
                )
            )

    top.sort(key=lambda x: x.messages_used, reverse=True)
    altas.sort(key=lambda x: x.created_at, reverse=True)
    churn.sort(key=lambda x: x.dias_inactivo, reverse=True)

    return AdminStatsOverview(
        clientes_total=clientes_total,
        clientes_activos=clientes_activos,
        clientes_demo=clientes_demo,
        clientes_sin_owner=clientes_sin_owner,
        mensajes_mes=mensajes_mes,
        mensajes_quota_mes=mensajes_quota_mes,
        top_clientes=top[:10],
        altas_recientes=altas[:20],
        churn_riesgo=churn[:20],
        generated_at=now.isoformat(),
    )


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

    with appstate.state_lock:
        sesiones_activas = len(appstate.sesiones)
        indices_cargados = sorted(appstate.indices.keys())

    return {
        "version": app.version,
        "clientes_configurados": len(appstate.CONFIG_CLIENTES),
        "sesiones_activas": sesiones_activas,
        "indices_cargados": indices_cargados,
        "bookings_por_cliente": {row["cliente_id"]: row["total"] for row in rows},
        "bookings_por_estado": {row["status"]: row["total"] for row in status_rows},
    }


@app.get("/admin/analytics", dependencies=[Depends(_require_admin_token)])
async def admin_analytics(days: int = 30, limit: int = 80) -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    limit = max(1, min(int(limit or 80), 300))
    since = _utc_now() - timedelta(days=days)
    since_iso = since.isoformat().replace("+00:00", "Z")

    with _get_db_connection() as connection:
        total = int(
            connection.execute(
                "SELECT COUNT(*) FROM analytics_events WHERE created_at >= ?",
                (since_iso,),
            ).fetchone()[0]
        )
        by_event = connection.execute(
            """
            SELECT event_name, COUNT(*) AS total
            FROM analytics_events
            WHERE created_at >= ?
            GROUP BY event_name
            ORDER BY total DESC, event_name ASC
            """,
            (since_iso,),
        ).fetchall()
        by_client = connection.execute(
            """
            SELECT COALESCE(NULLIF(cliente_id, ''), 'sin_cliente') AS cliente_id, COUNT(*) AS total
            FROM analytics_events
            WHERE created_at >= ?
            GROUP BY COALESCE(NULLIF(cliente_id, ''), 'sin_cliente')
            ORDER BY total DESC, cliente_id ASC
            """,
            (since_iso,),
        ).fetchall()
        daily = connection.execute(
            """
            SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS total
            FROM analytics_events
            WHERE created_at >= ?
            GROUP BY substr(created_at, 1, 10)
            ORDER BY day ASC
            """,
            (since_iso,),
        ).fetchall()
        recent_rows = connection.execute(
            """
            SELECT id, event_name, event_source, cliente_id, session_id, page_path, page_url,
                   metadata_json, created_at
            FROM analytics_events
            WHERE created_at >= ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (since_iso, limit),
        ).fetchall()

    key_events = {row["event_name"]: int(row["total"]) for row in by_event}
    recent = []
    for row in recent_rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        recent.append(
            {
                "id": row["id"],
                "event_name": row["event_name"],
                "event_source": row["event_source"],
                "cliente_id": row["cliente_id"],
                "session_id": row["session_id"],
                "page_path": row["page_path"],
                "page_url": row["page_url"],
                "metadata": metadata,
                "created_at": row["created_at"],
            }
        )

    return {
        "days": days,
        "since": since_iso,
        "total_events": total,
        "kpis": {
            "landing_view": key_events.get("landing_view", 0),
            "signup_clicked": key_events.get("signup_clicked", 0),
            "signup_completed": key_events.get("signup_completed", 0),
            "bot_created": key_events.get("bot_created", 0),
            "first_chat_tested": key_events.get("first_chat_tested", 0),
            "pricing_viewed": key_events.get("pricing_viewed", 0),
            "upgrade_clicked": key_events.get("upgrade_clicked", 0),
            "demo_submits": key_events.get("demo_submit", 0),
            "demo_generated": key_events.get("demo_generated", 0),
            "checkout_started": key_events.get("checkout_started", 0),
            "checkout_redirect": key_events.get("checkout_redirect", 0),
            "checkout_completed": key_events.get("checkout_completed", 0),
            "lead_created": key_events.get("lead_created", 0),
            "widget_messages": key_events.get("widget_message_sent", 0),
            "booking_submitted": key_events.get("booking_submitted", 0),
            "booking_confirmed": key_events.get("booking_confirmed", 0),
            "consultation_clicks": key_events.get("consultation_cta_click", 0),
        },
        "events_by_name": [{"event_name": row["event_name"], "total": row["total"]} for row in by_event],
        "events_by_client": [{"cliente_id": row["cliente_id"], "total": row["total"]} for row in by_client],
        "daily": [{"day": row["day"], "total": row["total"]} for row in daily],
        "recent": recent,
    }


@app.get("/admin/self-service-funnel", dependencies=[Depends(_require_admin_token)])
async def admin_self_service_funnel(days: int = 30) -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    since = _utc_now() - timedelta(days=days)
    since_iso = since.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"

    def pct(part: int, total: int) -> int:
        return int(round((part / total) * 100)) if total else 0

    with _get_db_connection() as connection:
        events = connection.execute(
            """
            SELECT event_name, event_source, cliente_id, session_id, page_path,
                   page_url, metadata_json, created_at
            FROM analytics_events
            WHERE created_at >= ?
            ORDER BY id DESC
            """,
            (since_iso,),
        ).fetchall()
        signups = int(
            connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'client' AND created_at >= ?",
                (since_iso,),
            ).fetchone()[0]
        )
        bots_created = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM clientes
                WHERE owner_user_id <> '' AND created_at >= ?
                """,
                (since_iso,),
            ).fetchone()[0]
        )
        activated_by_chat = int(
            connection.execute(
                """
                SELECT COUNT(DISTINCT c.cliente_id)
                FROM clientes c
                JOIN chat_messages m ON m.cliente_id = c.cliente_id
                WHERE c.owner_user_id <> ''
                  AND m.role IN ('assistant', 'bot')
                  AND m.created_at >= ?
                """,
                (since_iso,),
            ).fetchone()[0]
        )
        paid_subscriptions = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM subscriptions
                WHERE plan <> 'free'
                  AND status IN ('active', 'trialing')
                  AND (created_at >= ? OR updated_at >= ?)
                """,
                (since_iso, since_iso),
            ).fetchone()[0]
        )
        sources = connection.execute(
            """
            SELECT COALESCE(NULLIF(signup_source, ''), 'unknown') AS source, COUNT(*) AS total
            FROM users
            WHERE role = 'client' AND created_at >= ?
            GROUP BY COALESCE(NULLIF(signup_source, ''), 'unknown')
            ORDER BY total DESC, source ASC
            LIMIT 8
            """,
            (since_iso,),
        ).fetchall()
        bot_sources = connection.execute(
            """
            SELECT COALESCE(NULLIF(source, ''), 'unknown') AS source, COUNT(*) AS total
            FROM clientes
            WHERE owner_user_id <> '' AND created_at >= ?
            GROUP BY COALESCE(NULLIF(source, ''), 'unknown')
            ORDER BY total DESC, source ASC
            LIMIT 8
            """,
            (since_iso,),
        ).fetchall()
        recent_signups = connection.execute(
            """
            SELECT u.email, u.display_name, u.signup_source, u.cliente_id, u.created_at,
                   c.nombre AS bot_name, c.website_url
            FROM users u
            LEFT JOIN clientes c ON c.cliente_id = u.cliente_id
            WHERE u.role = 'client' AND u.created_at >= ?
            ORDER BY u.created_at DESC
            LIMIT 8
            """,
            (since_iso,),
        ).fetchall()
        recent_bots = connection.execute(
            """
            SELECT c.cliente_id, c.nombre, c.website_url, c.plan, c.source, c.created_at,
                   u.email AS owner_email
            FROM clientes c
            LEFT JOIN users u ON u.id = c.owner_user_id
            WHERE c.owner_user_id <> '' AND c.created_at >= ?
            ORDER BY c.created_at DESC
            LIMIT 8
            """,
            (since_iso,),
        ).fetchall()

    event_counts: Dict[str, int] = {}
    site_visit_keys = set()
    cta_clicks = 0
    registered_clicks = 0
    snippet_copied = 0
    preview_messages = 0
    preview_client_ids = set()
    upgrades_started = 0
    checkout_completed_events = 0
    campaign_clicks: Dict[str, int] = {}
    for row in events:
        name = row["event_name"]
        event_counts[name] = event_counts.get(name, 0) + 1
        if row["event_source"] == "vantelia_site" or name in {"landing_view", "pricing_viewed"}:
            visit_key = row["session_id"] or row["page_url"] or row["page_path"] or str(row["created_at"])
            site_visit_keys.add(visit_key)
        try:
            meta = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        cta_href = str(meta.get("cta_href") or row["page_url"] or "")
        source = str(meta.get("utm_source") or meta.get("source") or row["event_source"] or "direct")
        if name in {"signup_clicked", "plan_signup_clicked", "plan_cta_click", "portal_access_click", "create_bot_cta_click", "free_bot_cta_click"}:
            cta_clicks += 1
            campaign_clicks[source] = campaign_clicks.get(source, 0) + 1
            if "/acceso" in cta_href or "app.vantelia.es" in cta_href:
                registered_clicks += 1
        if name in {"signup_completed", "selfserve_signup"}:
            signups = max(signups, event_counts[name])
        if name in {"first_chat_tested", "bot_preview_message"}:
            preview_messages += 1
            if row["cliente_id"]:
                preview_client_ids.add(row["cliente_id"])
        if name == "snippet_copied":
            snippet_copied += 1
        if name in {"upgrade_clicked", "upgrade_started", "checkout_started", "checkout_redirect"}:
            upgrades_started += 1
        if name == "checkout_completed":
            checkout_completed_events += 1

    upgrades_started = max(
        event_counts.get("upgrade_clicked", 0),
        event_counts.get("upgrade_started", 0),
        event_counts.get("checkout_started", 0),
        event_counts.get("checkout_redirect", 0),
    )
    website_visits = len(site_visit_keys) or sum(
        total for event, total in event_counts.items() if event in {"landing_view", "page_view", "site_page_view"}
    )
    free_bot_clicks = registered_clicks or cta_clicks
    activated_bots = max(activated_by_chat, len(preview_client_ids))
    upgrades_completed = max(paid_subscriptions, checkout_completed_events)
    funnel = [
        {"key": "visits", "label": "Visitas web", "value": website_visits},
        {"key": "cta_clicks", "label": "Clicks Crea tu bot gratis", "value": free_bot_clicks},
        {"key": "signups", "label": "Registros", "value": signups},
        {"key": "bots_created", "label": "Bots creados", "value": bots_created},
        {"key": "activated", "label": "Primer chat probado", "value": activated_bots},
        {"key": "snippet_copied", "label": "Snippet copiado", "value": snippet_copied},
        {"key": "upgrades_started", "label": "Upgrade iniciado", "value": upgrades_started},
        {"key": "upgrades_completed", "label": "Pago completado", "value": upgrades_completed},
    ]
    for idx, step in enumerate(funnel):
        previous = funnel[idx - 1]["value"] if idx else step["value"]
        step["conversion_from_previous_pct"] = pct(int(step["value"]), int(previous))
        step["conversion_from_visit_pct"] = pct(int(step["value"]), website_visits)

    actions: List[Dict[str, str]] = []
    if website_visits and free_bot_clicks < max(1, int(website_visits * 0.08)):
        actions.append({
            "title": "Subir clicks al registro",
            "detail": "Revisa CTAs visibles y repite 'Crea tu bot gratis en 2 minutos' en las paginas con mas trafico.",
        })
    if signups and bots_created < signups:
        actions.append({
            "title": "Recuperar registros sin bot",
            "detail": "Envia un email corto llevando al wizard: pega tu URL y termina el bot gratis.",
        })
    if bots_created and activated_bots < bots_created:
        actions.append({
            "title": "Empujar la primera prueba",
            "detail": "Prioriza onboarding y emails que pidan probar una pregunta real del negocio.",
        })
    if activated_bots and snippet_copied < activated_bots:
        actions.append({
            "title": "Acelerar instalacion",
            "detail": "Haz mas visible el boton de copiar codigo y ofrece guia rapida por CMS.",
        })
    if snippet_copied and upgrades_completed == 0:
        actions.append({
            "title": "Convertir activacion en pago",
            "detail": "Muestra limites del plan gratis y CTA de upgrade justo despues de instalar.",
        })
    if not actions:
        actions.append({
            "title": "Escalar lo que ya funciona",
            "detail": "Duplica las campanas que traen registros y mejora el paso con peor conversion.",
        })

    campaign_rows = [
        {"source": source, "clicks": total}
        for source, total in sorted(campaign_clicks.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]

    return {
        "days": days,
        "since": since_iso,
        "funnel": funnel,
        "kpis": {
            "website_visits": website_visits,
            "free_bot_clicks": free_bot_clicks,
            "signups": signups,
            "bots_created": bots_created,
            "activated_bots": activated_bots,
            "snippet_copied": snippet_copied,
            "upgrades_started": upgrades_started,
            "upgrades_completed": upgrades_completed,
            "visit_to_signup_pct": pct(signups, website_visits),
            "signup_to_bot_pct": pct(bots_created, signups),
            "bot_to_activation_pct": pct(activated_bots, bots_created),
            "activation_to_install_pct": pct(snippet_copied, activated_bots),
            "install_to_paid_pct": pct(upgrades_completed, snippet_copied),
        },
        "sources": [{"source": row["source"], "total": row["total"]} for row in sources],
        "bot_sources": [{"source": row["source"], "total": row["total"]} for row in bot_sources],
        "campaigns": campaign_rows,
        "recent_signups": [dict(row) for row in recent_signups],
        "recent_bots": [dict(row) for row in recent_bots],
        "actions": actions,
        "tracking": {
            "landing_view": event_counts.get("landing_view", 0) > 0,
            "signup_clicked": event_counts.get("signup_clicked", 0) > 0 or cta_clicks > 0,
            "signup_completed": event_counts.get("signup_completed", 0) > 0 or signups > 0,
            "bot_created": event_counts.get("bot_created", 0) > 0 or bots_created > 0,
            "first_chat_tested": event_counts.get("first_chat_tested", 0) > 0 or preview_messages > 0,
            "pricing_viewed": event_counts.get("pricing_viewed", 0) > 0,
            "upgrade_clicked": event_counts.get("upgrade_clicked", 0) > 0 or upgrades_started > 0,
            "checkout_started": event_counts.get("checkout_started", 0) > 0,
            "checkout_completed": event_counts.get("checkout_completed", 0) > 0 or upgrades_completed > 0,
            "snippet_copied": snippet_copied > 0,
            "preview_messages": preview_messages > 0,
            "upgrade_started": upgrades_started > 0,
        },
    }


# =====================================================================
# === PLAN DE ESCALA ==================================================
# Centro diario de actividad, pipeline y revision comercial.
# =====================================================================

GROWTH_ACTIVE_STAGES = GROWTH_STAGES - {"ganada", "perdida", "recurrente"}
GROWTH_STAGE_WEIGHTS = {
    "identificada": 0.05, "contactada": 0.10, "conversacion": 0.20,
    "descubrimiento": 0.35, "demo": 0.50, "propuesta": 0.75,
    "ganada": 1.0, "recurrente": 1.0, "perdida": 0.0,
}
GROWTH_PLAN_START = date(2026, 6, 8)
GROWTH_DAILY_TARGETS = {"researched": 10, "contacts": 20, "followups": 10, "calls": 3}
GROWTH_PLAN_TASKS = [
    {"key": "d1_pipeline", "label": "Día 1 · Preparar pipeline"},
    {"key": "d1_select", "label": "Día 1 · Seleccionar 20 empresas Campaña 1"},
    {"key": "d1_contact", "label": "Día 1 · Enviar 20 contactos manuales"},
    {"key": "d1_calls", "label": "Día 1 · Realizar 10 llamadas"},
    {"key": "d2_campaign1", "label": "Día 2 · Repetir Campaña 1"},
    {"key": "d3_campaign2", "label": "Día 3 · Ejecutar Campaña 2"},
    {"key": "d4_demos", "label": "Día 4 · Preparar y realizar demos"},
    {"key": "d5_proposal", "label": "Día 5 · Enviar primera propuesta"},
    {"key": "w1_review", "label": "Semana 1 · Completar dashboard y decisión"},
]






















@app.get("/admin/growth/overview", dependencies=[Depends(_require_admin_token)])
async def admin_growth_overview() -> Dict[str, Any]:
    today = date.today().isoformat()
    with _get_db_connection() as connection:
        daily_row = connection.execute("SELECT * FROM growth_daily WHERE activity_date = ?", (today,)).fetchone()
        summaries = {str(days): _growth_summary(connection, days) for days in (7, 30, 90)}
        opportunities = connection.execute("SELECT * FROM growth_opportunities ORDER BY updated_at DESC").fetchall()
        weekly_rows = connection.execute(
            """
            SELECT strftime('%Y-W%W', activity_date) AS week,
                   SUM(contacts) contacts, SUM(conversations) conversations,
                   SUM(proposals) proposals, SUM(won) won, SUM(eur_sold) eur_sold
            FROM growth_daily WHERE activity_date >= ?
            GROUP BY strftime('%Y-W%W', activity_date) ORDER BY week
            """,
            ((date.today() - timedelta(days=89)).isoformat(),),
        ).fetchall()
        task_rows = {row["task_key"]: bool(row["completed"]) for row in connection.execute("SELECT * FROM growth_plan_tasks").fetchall()}
        latest_review = connection.execute("SELECT * FROM growth_weekly_reviews ORDER BY week_start DESC LIMIT 1").fetchone()
    summary_30 = summaries["30"]
    states = _growth_states(summary_30)
    active = [row for row in opportunities if row["stage"] in GROWTH_ACTIVE_STAGES]
    weighted = sum(float(row["value_eur"] or 0) * GROWTH_STAGE_WEIGHTS.get(row["stage"], 0) for row in active)
    missing_next = sum(1 for row in active if not str(row["next_action"] or "").strip())
    overdue = sum(1 for row in active if row["next_action_date"] and row["next_action_date"] < today)
    plan_path = BASE_DIR / "docs" / "PLAN_ESCALA_AGENCIA_IA.md"
    def breakdown(key: str) -> List[Dict[str, Any]]:
        values: Dict[str, Dict[str, Any]] = {}
        for row in opportunities:
            name = str(row[key] or "").strip() or "sin_asignar"
            entry = values.setdefault(name, {"name": name, "count": 0, "active": 0, "won": 0, "value_eur": 0.0})
            entry["count"] += 1
            entry["active"] += int(row["stage"] in GROWTH_ACTIVE_STAGES)
            entry["won"] += int(row["stage"] in {"ganada", "recurrente"})
            entry["value_eur"] += float(row["value_eur"] or 0)
        return list(values.values())
    return {
        "today": _growth_daily_public(daily_row, today),
        "targets": GROWTH_DAILY_TARGETS,
        "summaries": summaries,
        "states": states,
        "overall_state": _growth_overall_state(states),
        "plan": {"start_date": GROWTH_PLAN_START.isoformat(), "day": max(1, (date.today() - GROWTH_PLAN_START).days + 1), "horizon_days": 90},
        "pipeline": {"active": len(active), "total": len(opportunities), "weighted_value_eur": round(weighted, 2), "missing_next_action": missing_next, "overdue": overdue},
        "breakdown": {"campaigns": breakdown("campaign"), "offers": breakdown("offer")},
        "weekly": [dict(row) for row in weekly_rows],
        "opportunities": [_growth_opportunity_public(row) for row in opportunities],
        "tasks": [{**task, "completed": task_rows.get(task["key"], False)} for task in GROWTH_PLAN_TASKS],
        "latest_review": dict(latest_review) if latest_review else None,
        "automatic_outreach": _growth_automatic_outreach(),
        "plan_markdown": plan_path.read_text(encoding="utf-8") if plan_path.exists() else "",
    }


@app.put("/admin/growth/daily/{activity_date}", dependencies=[Depends(_require_admin_token)])
async def admin_growth_daily_save(activity_date: str, data: GrowthDailyPayload) -> Dict[str, Any]:
    activity_date = _growth_date(activity_date)
    now = _utc_now_iso()
    values = data.model_dump()
    with _get_db_connection() as connection:
        exists = connection.execute("SELECT 1 FROM growth_daily WHERE activity_date = ?", (activity_date,)).fetchone()
        connection.execute(
            """
            INSERT INTO growth_daily (
                activity_date, researched, contacts, followups, calls, positive_replies,
                conversations, meetings, proposals, won, eur_sold, new_recurring,
                delivery_hours, learning, blocker, next_action, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(activity_date) DO UPDATE SET
                researched=excluded.researched, contacts=excluded.contacts, followups=excluded.followups,
                calls=excluded.calls, positive_replies=excluded.positive_replies,
                conversations=excluded.conversations, meetings=excluded.meetings,
                proposals=excluded.proposals, won=excluded.won, eur_sold=excluded.eur_sold,
                new_recurring=excluded.new_recurring, delivery_hours=excluded.delivery_hours,
                learning=excluded.learning, blocker=excluded.blocker, next_action=excluded.next_action,
                updated_at=excluded.updated_at
            """,
            (activity_date, values["researched"], values["contacts"], values["followups"], values["calls"],
             values["positive_replies"], values["conversations"], values["meetings"], values["proposals"],
             values["won"], values["eur_sold"], values["new_recurring"], values["delivery_hours"],
             values["learning"], values["blocker"], values["next_action"], now, now),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM growth_daily WHERE activity_date = ?", (activity_date,)).fetchone()
    return {"ok": True, "created": not bool(exists), "item": _growth_daily_public(row, activity_date)}


@app.get("/admin/growth/opportunities", dependencies=[Depends(_require_admin_token)])
async def admin_growth_opportunities(stage: str = "", campaign: str = "", offer: str = "", overdue: bool = False) -> Dict[str, Any]:
    clauses, params = [], []
    if stage:
        clauses.append("stage = ?"); params.append(_growth_stage(stage))
    if campaign:
        clauses.append("campaign = ?"); params.append(campaign)
    if offer:
        clauses.append("offer = ?"); params.append(offer)
    if overdue:
        clauses.append("stage NOT IN ('ganada','perdida','recurrente') AND next_action_date <> '' AND next_action_date < ?"); params.append(date.today().isoformat())
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with _get_db_connection() as connection:
        rows = connection.execute("SELECT * FROM growth_opportunities" + where + " ORDER BY updated_at DESC", tuple(params)).fetchall()
    return {"items": [_growth_opportunity_public(row) for row in rows]}




@app.post("/admin/growth/opportunities", dependencies=[Depends(_require_admin_token)])
async def admin_growth_opportunity_create(data: GrowthOpportunityPayload) -> Dict[str, Any]:
    item = data.model_dump()
    item["stage"] = _growth_stage(item["stage"])
    opportunity_id, now = uuid.uuid4().hex, _utc_now_iso()
    with _get_db_connection() as connection:
        connection.execute(
            """INSERT INTO growth_opportunities
            (id,company,campaign,offer,stage,value_eur,decision_maker,contact,problem,next_action,next_action_date,decision_date,notes,lost_reason,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (opportunity_id, item["company"], item["campaign"], item["offer"], item["stage"], item["value_eur"],
             item["decision_maker"], item["contact"], item["problem"], item["next_action"], item["next_action_date"],
             item["decision_date"], item["notes"], item["lost_reason"], now, now),
        )
        _growth_audit(connection, opportunity_id, "created", item)
        connection.commit()
        row = connection.execute("SELECT * FROM growth_opportunities WHERE id = ?", (opportunity_id,)).fetchone()
    return {"ok": True, "item": _growth_opportunity_public(row)}


@app.patch("/admin/growth/opportunities/{opportunity_id}", dependencies=[Depends(_require_admin_token)])
async def admin_growth_opportunity_update(opportunity_id: str, data: GrowthOpportunityPayload) -> Dict[str, Any]:
    item = data.model_dump()
    item["stage"] = _growth_stage(item["stage"])
    with _get_db_connection() as connection:
        before = connection.execute("SELECT * FROM growth_opportunities WHERE id = ?", (opportunity_id,)).fetchone()
        if not before:
            raise HTTPException(status_code=404, detail="Oportunidad no encontrada.")
        connection.execute(
            """UPDATE growth_opportunities SET company=?,campaign=?,offer=?,stage=?,value_eur=?,decision_maker=?,contact=?,
            problem=?,next_action=?,next_action_date=?,decision_date=?,notes=?,lost_reason=?,updated_at=? WHERE id=?""",
            (item["company"], item["campaign"], item["offer"], item["stage"], item["value_eur"], item["decision_maker"],
             item["contact"], item["problem"], item["next_action"], item["next_action_date"], item["decision_date"],
             item["notes"], item["lost_reason"], _utc_now_iso(), opportunity_id),
        )
        _growth_audit(connection, opportunity_id, "updated", {"before": dict(before), "after": item})
        connection.commit()
        row = connection.execute("SELECT * FROM growth_opportunities WHERE id = ?", (opportunity_id,)).fetchone()
    return {"ok": True, "item": _growth_opportunity_public(row)}


@app.delete("/admin/growth/opportunities/{opportunity_id}", dependencies=[Depends(_require_admin_token)])
async def admin_growth_opportunity_delete(opportunity_id: str) -> Dict[str, Any]:
    with _get_db_connection() as connection:
        row = connection.execute("SELECT * FROM growth_opportunities WHERE id = ?", (opportunity_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Oportunidad no encontrada.")
        _growth_audit(connection, opportunity_id, "deleted", dict(row))
        connection.execute("DELETE FROM growth_opportunities WHERE id = ?", (opportunity_id,))
        connection.commit()
    return {"ok": True}


@app.get("/admin/growth/opportunities/{opportunity_id}/history", dependencies=[Depends(_require_admin_token)])
async def admin_growth_opportunity_history(opportunity_id: str) -> Dict[str, Any]:
    with _get_db_connection() as connection:
        rows = connection.execute("SELECT * FROM growth_opportunity_audit WHERE opportunity_id = ? ORDER BY id DESC", (opportunity_id,)).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/admin/growth/review/generate", dependencies=[Depends(_require_admin_token)])
async def admin_growth_review_generate(week_start: str = "") -> Dict[str, Any]:
    target = week_start or (date.today() - timedelta(days=date.today().weekday())).isoformat()
    with _get_db_connection() as connection:
        return _growth_generate_review(connection, target)


@app.put("/admin/growth/review", dependencies=[Depends(_require_admin_token)])
async def admin_growth_review_save(data: GrowthWeeklyReviewPayload) -> Dict[str, Any]:
    week_start, now = _growth_date(data.week_start), _utc_now_iso()
    with _get_db_connection() as connection:
        generated = _growth_generate_review(connection, week_start)
        connection.execute(
            """INSERT INTO growth_weekly_reviews (week_start,generated_json,decision,notes,created_at,updated_at)
            VALUES (?,?,?,?,?,?) ON CONFLICT(week_start) DO UPDATE SET generated_json=excluded.generated_json,
            decision=excluded.decision,notes=excluded.notes,updated_at=excluded.updated_at""",
            (week_start, json.dumps(generated, ensure_ascii=False), data.decision, data.notes, now, now),
        )
        connection.commit()
    return {"ok": True, "generated": generated}


@app.put("/admin/growth/tasks", dependencies=[Depends(_require_admin_token)])
async def admin_growth_task_save(data: GrowthPlanTaskPayload) -> Dict[str, Any]:
    if data.task_key not in {item["key"] for item in GROWTH_PLAN_TASKS}:
        raise HTTPException(status_code=400, detail="Tarea del plan invalida.")
    now = _utc_now_iso()
    with _get_db_connection() as connection:
        connection.execute(
            """INSERT INTO growth_plan_tasks (task_key,completed,completed_at,updated_at) VALUES (?,?,?,?)
            ON CONFLICT(task_key) DO UPDATE SET completed=excluded.completed,completed_at=excluded.completed_at,updated_at=excluded.updated_at""",
            (data.task_key, int(data.completed), now if data.completed else "", now),
        )
        connection.commit()
    return {"ok": True}


# =====================================================================
# === OUTREACH ========================================================
# Panel de captacion B2B. SQLite separado en storage/outreach/outreach.db.
# Reusa scripts/outreach_campaign.py + scripts/outreach_templates.py.
# =====================================================================


# Tracking desactivado por defecto. Requiere OUTREACH_TRACKING_ENABLED=true para activar.
OUTREACH_TRACKING_ALLOWED_HOSTS = {"vantelia.es", "www.vantelia.es", "app.vantelia.es"}

GA4_PROPERTY_ID = os.getenv("GA4_PROPERTY_ID", "").strip()
GA4_SERVICE_ACCOUNT_JSON = (
    os.getenv("GA4_SERVICE_ACCOUNT_JSON", "").strip()
    or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_VANTELIA", "").strip()
)
OUTREACH_PIXEL_GIF = bytes.fromhex("47494638396101000100800000ffffff00000021f90401000000002c00000000010001000002024401003b")


















# ----- Pydantic models -----

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


class OutreachPreflightRequest(BaseModel):
    stage: str = "cold"
    emails: List[str] = Field(default_factory=list)
    max: int = 20
    after_days: int = 4


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


class OutreachSuppressRequest(BaseModel):
    email: EmailStr
    reason: str = "manual"


class OutreachDiscoverRequest(BaseModel):
    sector: str = Field(..., min_length=2)
    ciudad: str = Field(..., min_length=2)
    max: int = 30
    extract_emails: bool = True
    import_direct: bool = False
    source: str = Field(default="auto", pattern="^(auto|places|osm)$")


class OutreachTemplateOverride(BaseModel):
    stage: str
    subject_pool: str = ""
    body_text: str = ""
    body_html: str = ""


class OutreachAutopilotRun(BaseModel):
    days: int = 60
    limit: int = 120
    apply_status: bool = True


class OutreachAutopilotSendPayload(BaseModel):
    max: int = 10
    send: bool = True
    delay: float = 70.0
    jitter: float = 25.0
    days: int = 60
    limit: int = 120
    apply_status: bool = False


class OutreachManualEmailPayload(BaseModel):
    recipient: EmailStr
    subject: str = Field(..., min_length=1, max_length=180)
    text: str = Field(default="", max_length=50000)
    html: str = Field(default="", max_length=200000)
    css: str = Field(default="", max_length=50000)


# ----- Stats -----

@app.get("/admin/outreach/stats", dependencies=[Depends(_require_admin_token)])
def outreach_stats():
    with _outreach_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM prospects").fetchone()["c"]
        suppressed = conn.execute("SELECT COUNT(*) AS c FROM suppressions").fetchone()["c"]
        per_stage_rows = conn.execute(
            "SELECT stage, COUNT(*) AS c FROM sends WHERE mode='send' GROUP BY stage"
        ).fetchall()
        per_stage = {row["stage"]: int(row["c"]) for row in per_stage_rows}

        opens = conn.execute("SELECT COUNT(*) AS c FROM events WHERE type='open'").fetchone()["c"]
        clicks = conn.execute("SELECT COUNT(*) AS c FROM events WHERE type='click'").fetchone()["c"]
        unique_clicks = conn.execute(
            "SELECT COUNT(DISTINCT email) AS c FROM events WHERE type='click'"
        ).fetchone()["c"]
        vantelia_clicks = conn.execute(
            """SELECT COUNT(*) AS c FROM events
               WHERE type='click' AND (
                 lower(coalesce(url,'')) LIKE 'https://www.vantelia.es%'
                 OR lower(coalesce(url,'')) LIKE 'https://vantelia.es%'
               )"""
        ).fetchone()["c"]
        reply_intents = conn.execute("SELECT COUNT(*) AS c FROM events WHERE type='reply_intent'").fetchone()["c"]
        replies = conn.execute("SELECT COUNT(*) AS c FROM events WHERE type='reply'").fetchone()["c"]
        unique_opens = conn.execute(
            "SELECT COUNT(DISTINCT email) AS c FROM events WHERE type='open'"
        ).fetchone()["c"]
        unique_vantelia_clicks = conn.execute(
            """SELECT COUNT(DISTINCT email) AS c FROM events
               WHERE type='click' AND (
                 lower(coalesce(url,'')) LIKE 'https://www.vantelia.es%'
                 OR lower(coalesce(url,'')) LIKE 'https://vantelia.es%'
               )"""
        ).fetchone()["c"]
        unique_reply_intents = conn.execute(
            "SELECT COUNT(DISTINCT email) AS c FROM events WHERE type='reply_intent'"
        ).fetchone()["c"]
        unique_replies = conn.execute(
            "SELECT COUNT(DISTINCT email) AS c FROM events WHERE type='reply'"
        ).fetchone()["c"]

        sent_real = conn.execute(
            "SELECT COUNT(*) AS c FROM sends WHERE mode='send'"
        ).fetchone()["c"]
        sent_distinct = conn.execute(
            "SELECT COUNT(DISTINCT email) AS c FROM sends WHERE mode='send'"
        ).fetchone()["c"]

        today = _utc_now().date().isoformat()
        sent_today = conn.execute(
            "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]

        week_cutoff = (_utc_now() - timedelta(days=7)).isoformat(timespec="seconds")
        month_cutoff = (_utc_now() - timedelta(days=30)).isoformat(timespec="seconds")
        sent_week = conn.execute(
            "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND sent_at>=?",
            (week_cutoff,),
        ).fetchone()["c"]
        sent_month = conn.execute(
            "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND sent_at>=?",
            (month_cutoff,),
        ).fetchone()["c"]

        # serie diaria 30d
        daily_sends = conn.execute(
            """SELECT substr(sent_at,1,10) AS day, COUNT(*) AS c FROM sends
               WHERE mode='send' AND sent_at>=? GROUP BY day ORDER BY day""",
            (month_cutoff,),
        ).fetchall()
        daily_opens = conn.execute(
            """SELECT substr(ts,1,10) AS day, COUNT(*) AS c FROM events
               WHERE type='open' AND ts>=? GROUP BY day ORDER BY day""",
            (month_cutoff,),
        ).fetchall()
        daily_replies = conn.execute(
            """SELECT substr(ts,1,10) AS day, COUNT(*) AS c FROM events
               WHERE type='reply' AND ts>=? GROUP BY day ORDER BY day""",
            (month_cutoff,),
        ).fetchall()

        vantelia_click_rows = conn.execute(
            """SELECT e.email, p.business_name, p.niche, p.city,
                      COUNT(*) AS clicks, MAX(e.ts) AS last_clicked_at,
                      (SELECT e2.url FROM events e2
                         WHERE e2.email=e.email AND e2.type='click'
                           AND (lower(coalesce(e2.url,'')) LIKE 'https://www.vantelia.es%'
                                OR lower(coalesce(e2.url,'')) LIKE 'https://vantelia.es%')
                         ORDER BY e2.ts DESC LIMIT 1) AS last_url
               FROM events e
               LEFT JOIN prospects p ON p.email=e.email
               WHERE e.type='click' AND (
                 lower(coalesce(e.url,'')) LIKE 'https://www.vantelia.es%'
                 OR lower(coalesce(e.url,'')) LIKE 'https://vantelia.es%'
               )
               GROUP BY e.email
               ORDER BY last_clicked_at DESC
               LIMIT 20"""
        ).fetchall()

        # top niches por reply rate
        top_niches_rows = conn.execute(
            """SELECT p.niche AS niche, COUNT(DISTINCT p.email) AS prospects,
                      SUM(CASE WHEN EXISTS(SELECT 1 FROM events e WHERE e.email=p.email AND e.type='reply') THEN 1 ELSE 0 END) AS replies
               FROM prospects p WHERE p.niche<>'' GROUP BY p.niche ORDER BY replies DESC LIMIT 5"""
        ).fetchall()

        funnel = {
            stage: per_stage.get(stage, 0) for stage in OUTREACH_STAGES
        }

        sample_prospect = OutreachProspect(
            email="test@clinicadental.es",
            business_name="Clinica Dental Madrid",
            niche="clinica dental",
            city="Madrid",
            website="https://clinicadental.es",
        )
        primary_cta_url = outreach_demo_url_with_utm("cold", sample_prospect)
        parsed_cta = urlparse(primary_cta_url)
        parsed_tracking = urlparse(OUTREACH_TRACKING_BASE_URL)
        cta_path = (parsed_cta.path or "").lower()
        cta_destination = "demo" if parsed_cta.hostname in {"vantelia.es", "www.vantelia.es"} and cta_path.startswith("/demo") else "signup" if parsed_cta.hostname == "app.vantelia.es" and cta_path.startswith("/acceso") else "other"
        tracking_active = bool(OUTREACH_AVAILABLE and OUTREACH_TRACKING_SECRET and OUTREACH_TRACKING_BASE_URL and not OUTREACH_TRACKING_DISABLED)
        primary_cta_tracked = bool(tracking_active and not primary_cta_url.startswith(f"{OUTREACH_TRACKING_BASE_URL}/track/"))
        health_alerts = []
        if cta_destination != "demo":
            health_alerts.append({
                "level": "danger",
                "code": "cta_not_demo",
                "message": "El CTA principal de outreach no apunta a /demo/. Puede estar llevando prospects al registro antes de ver valor.",
            })
        if not tracking_active:
            health_alerts.append({
                "level": "warning",
                "code": "tracking_off",
                "message": "El tracking de aperturas/clicks no esta activo.",
            })
        elif not primary_cta_tracked:
            health_alerts.append({
                "level": "warning",
                "code": "cta_untracked",
                "message": "El CTA principal no se envolveria con tracking de click.",
            })

    open_rate = (unique_opens / sent_distinct * 100) if sent_distinct else 0.0
    reply_intent_rate = (unique_reply_intents / sent_distinct * 100) if sent_distinct else 0.0
    reply_rate = (unique_replies / sent_distinct * 100) if sent_distinct else 0.0
    click_rate = (unique_clicks / sent_distinct * 100) if sent_distinct else 0.0
    open_to_click_rate = (unique_clicks / unique_opens * 100) if unique_opens else 0.0

    return {
        "totals": {
            "prospects": total,
            "suppressed": suppressed,
            "sent_total": sent_real,
            "sent_distinct": sent_distinct,
            "sent_today": sent_today,
            "sent_week": sent_week,
            "sent_month": sent_month,
            "opens_total": opens,
            "opens_unique": unique_opens,
            "clicks_total": clicks,
            "clicks_unique": unique_clicks,
            "vantelia_clicks_total": vantelia_clicks,
            "vantelia_clicks_unique": unique_vantelia_clicks,
            "reply_intents_total": reply_intents,
            "reply_intents_unique": unique_reply_intents,
            "replies_total": replies,
            "replies_unique": unique_replies,
            "open_rate_pct": round(open_rate, 1),
            "click_rate_pct": round(click_rate, 1),
            "open_to_click_rate_pct": round(open_to_click_rate, 1),
            "reply_intent_rate_pct": round(reply_intent_rate, 1),
            "reply_rate_pct": round(reply_rate, 1),
        },
        "tracking": {
            "active": tracking_active,
            "base_url": OUTREACH_TRACKING_BASE_URL,
        },
        "primary_cta": {
            "url": primary_cta_url,
            "host": parsed_cta.hostname or "",
            "destination": cta_destination,
            "tracking_host": parsed_tracking.hostname or "",
            "tracked": primary_cta_tracked,
        },
        "health_alerts": health_alerts,
        "funnel": funnel,
        "daily": {
            "sends": [{"day": r["day"], "c": r["c"]} for r in daily_sends],
            "opens": [{"day": r["day"], "c": r["c"]} for r in daily_opens],
            "replies": [{"day": r["day"], "c": r["c"]} for r in daily_replies],
        },
        "top_niches": [
            {"niche": r["niche"], "prospects": r["prospects"], "replies": r["replies"]}
            for r in top_niches_rows
        ],
        "vantelia_clickers": [
            {
                "email": r["email"],
                "business_name": r["business_name"] or "",
                "niche": r["niche"] or "",
                "city": r["city"] or "",
                "clicks": r["clicks"],
                "last_clicked_at": r["last_clicked_at"],
                "last_url": r["last_url"] or "",
            }
            for r in vantelia_click_rows
        ],
    }


# ----- Hot leads (Fase 1) -----

@app.get("/admin/outreach/hot-leads", dependencies=[Depends(_require_admin_token)])
def outreach_hot_leads(limit: int = 15, days: int = 14):
    """Devuelve prospects calientes ordenados por engagement reciente.

    Score compuesto: clicks*5 + opens*1 + bonus por actividad reciente.
    Excluye prospects con respuesta detectada (ya en pipeline) y bajas.
    """
    limit = max(1, min(100, int(limit or 15)))
    days = max(1, min(60, int(days or 14)))
    cutoff = (_utc_now() - timedelta(days=days)).isoformat(timespec="seconds")

    with _outreach_db() as conn:
        rows = conn.execute(
            """
            SELECT p.email, p.business_name, p.contact_name, p.niche, p.city, p.phone,
                   p.website, COALESCE(p.status, 'new') AS status,
                   (SELECT stage FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_stage,
                   (SELECT sent_at FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_sent_at,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open'  AND e.ts>=?) AS opens_recent,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click' AND e.ts>=?) AS clicks_recent,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='demo_generated' AND e.ts>=?) AS demos_recent,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open')  AS opens_total,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks_total,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='demo_generated') AS demos_total,
                   (SELECT MAX(ts) FROM events e WHERE e.email=p.email AND e.type IN ('open','click','demo_generated')) AS last_event_at
            FROM prospects p
            WHERE NOT EXISTS (SELECT 1 FROM events ev WHERE ev.email=p.email AND ev.type='reply')
              AND COALESCE(p.status,'') NOT IN ('replied','client','lost')
              AND NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.email=p.email)
            """,
            (cutoff, cutoff, cutoff),
        ).fetchall()

    items = []
    for r in rows:
        opens_recent = int(r["opens_recent"] or 0)
        clicks_recent = int(r["clicks_recent"] or 0)
        demos_recent = int(r["demos_recent"] or 0)
        opens_total = int(r["opens_total"] or 0)
        clicks_total = int(r["clicks_total"] or 0)
        demos_total = int(r["demos_total"] or 0)
        if opens_recent + clicks_recent + demos_recent + opens_total + clicks_total + demos_total == 0:
            continue
        score = demos_recent * 12 + clicks_recent * 6 + opens_recent * 2 + demos_total * 6 + clicks_total * 3 + opens_total
        items.append({
            "email": r["email"],
            "business_name": r["business_name"],
            "contact_name": r["contact_name"] or "",
            "niche": r["niche"] or "",
            "city": r["city"] or "",
            "phone": r["phone"] or "",
            "website": r["website"] or "",
            "status": r["status"],
            "last_stage": r["last_stage"] or "",
            "last_sent_at": r["last_sent_at"] or "",
            "last_event_at": r["last_event_at"] or "",
            "opens_recent": opens_recent,
            "clicks_recent": clicks_recent,
            "demos_recent": demos_recent,
            "opens_total": opens_total,
            "clicks_total": clicks_total,
            "demos_total": demos_total,
            "score": score,
        })

    items.sort(key=lambda x: (x["score"], x["last_event_at"]), reverse=True)
    return {"window_days": days, "items": items[:limit]}




























@app.get("/admin/outreach/followup-queue", dependencies=[Depends(_require_admin_token)])
def outreach_followup_queue(limit: int = 80, days: int = 45):
    limit = max(1, min(200, int(limit or 80)))
    days = max(1, min(365, int(days or 45)))
    cutoff = (_utc_now() - timedelta(days=days)).isoformat(timespec="seconds")
    with _outreach_db() as conn:
        followup_days = _outreach_config_followup_days(conn)
        rows = conn.execute(
            """
            SELECT p.email, p.business_name, p.contact_name, p.niche, p.service_hint, p.city,
                   p.phone, p.website, p.tags, p.source, COALESCE(p.status,'new') AS status,
                   (SELECT MAX(s.sent_at) FROM sends s WHERE s.email=p.email AND s.mode='send') AS last_sent_at,
                   (SELECT MAX(e.ts) FROM events e WHERE e.email=p.email) AS last_event_at,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open') AS opens,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='demo_generated') AS demos,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply_intent') AS reply_intents,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply') AS replies,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send') AS total_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu1') AS fu1_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu2') AS fu2_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='breakup') AS breakup_sent
            FROM prospects p
            WHERE NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.email=p.email)
              AND COALESCE(p.status,'') NOT IN ('client','lost')
              AND EXISTS (
                  SELECT 1 FROM sends s
                  WHERE s.email=p.email AND s.mode='send' AND s.sent_at>=?
              )
            ORDER BY COALESCE(last_event_at,last_sent_at,'') DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()

    items = [_outreach_followup_item(row, followup_days) for row in rows]
    items.sort(
        key=lambda item: (
            -int(item["priority"]),
            item["signals"]["demos"],
            item["signals"]["reply_intents"],
            item["signals"]["clicks"],
            item["signals"]["opens"],
            item["last_event_at"] or item["last_sent_at"],
        ),
        reverse=True,
    )
    buckets = {
        "priority_1": [item for item in items if item["priority"] == 1],
        "priority_2": [item for item in items if item["priority"] == 2],
        "priority_3": [item for item in items if item["priority"] == 3],
    }
    return {
        "window_days": days,
        "followup_days": followup_days,
        "total": len(items),
        "counts": {key: len(value) for key, value in buckets.items()},
        "items": items,
        "buckets": buckets,
    }




@app.get("/admin/outreach/autopilot", dependencies=[Depends(_require_admin_token)])
def outreach_autopilot_status(limit: int = 120, days: int = 60):
    queue = outreach_followup_queue(limit=limit, days=days)
    return _outreach_autopilot_summary(queue)


@app.get("/admin/outreach/autopilot/next-action", dependencies=[Depends(_require_admin_token)])
def outreach_autopilot_next_action():
    """Devuelve el único mejor prospect+stage para el botón 'Enviar ahora' del panel."""
    with _outreach_db() as conn:
        stage_days = _outreach_followup_stage_days(_outreach_config_followup_days(conn))
        for stage, after_days in stage_days:
            cutoff = (_utc_now() - timedelta(days=after_days)).isoformat(timespec="seconds")
            prev_stage = OUTREACH_STAGES[OUTREACH_STAGES.index(stage) - 1]
            row = conn.execute(
                """
                SELECT p.email, p.business_name, p.contact_name, p.niche, p.city,
                       p.phone, p.website, p.service_hint,
                       COALESCE(p.status,'new') AS status,
                       COALESCE(p.score,0) AS score,
                       (SELECT MAX(s.sent_at) FROM sends s WHERE s.email=p.email AND s.mode='send') AS last_sent_at,
                       (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open') AS opens,
                       (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks,
                       (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply') AS replies
                FROM prospects p
                WHERE EXISTS (
                    SELECT 1 FROM sends s WHERE s.email=p.email AND s.stage=? AND s.sent_at<=? AND s.mode='send'
                )
                AND NOT EXISTS (
                    SELECT 1 FROM sends s2 WHERE s2.email=p.email AND s2.stage=? AND s2.mode='send'
                )
                AND NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.email=p.email)
                AND NOT EXISTS (SELECT 1 FROM events ev WHERE ev.email=p.email AND ev.type='reply')
                AND COALESCE(p.status,'') NOT IN ('replied','client','lost')
                ORDER BY
                    (COALESCE(p.score,0)
                     + (SELECT COUNT(*)*6 FROM events e WHERE e.email=p.email AND e.type='click')
                     + (SELECT COUNT(*)*2 FROM events e WHERE e.email=p.email AND e.type='open')
                    ) DESC
                LIMIT 1
                """,
                (prev_stage, cutoff, stage),
            ).fetchone()
            if row:
                return {
                    "found": True,
                    "stage": stage,
                    "after_days": after_days,
                    "email": row["email"],
                    "business_name": row["business_name"],
                    "contact_name": row["contact_name"],
                    "niche": row["niche"],
                    "city": row["city"],
                    "last_sent_at": row["last_sent_at"],
                    "opens": int(row["opens"] or 0),
                    "clicks": int(row["clicks"] or 0),
                    "score": int(row["score"] or 0),
                }
    return {"found": False}


@app.post("/admin/outreach/autopilot/run", dependencies=[Depends(_require_admin_token)])
def outreach_autopilot_run(payload: OutreachAutopilotSendPayload):
    """Lanza un job real de follow-ups automáticos (fu1/fu2/breakup) hasta payload.max envíos."""
    max_send = max(1, min(50, int(payload.max or 10)))
    params = {
        "max": max_send,
        "send": bool(payload.send),
        "delay": float(payload.delay),
        "jitter": float(payload.jitter),
    }
    updated_engaged = 0
    with _outreach_db() as conn:
        followup_days = _outreach_config_followup_days(conn)
        params["followup_days"] = followup_days
        if payload.apply_status:
            cutoff = (_utc_now() - timedelta(days=max(1, int(payload.days or 60)))).isoformat(timespec="seconds")
            cur = conn.execute(
                """UPDATE prospects SET status='engaged', updated_at=?
                   WHERE status IN ('new','contacted')
                   AND EXISTS (
                       SELECT 1 FROM events e
                       WHERE e.email=prospects.email
                         AND e.type IN ('open','click','demo_generated','reply_intent')
                         AND e.ts >= ?
                   )""",
                (_outreach_now(), cutoff),
            )
            updated_engaged = cur.rowcount
            conn.commit()
        cur = conn.execute(
            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
            ("autopilot", "queued", json.dumps(params), "", _outreach_now()),
        )
        job_id = cur.lastrowid
        conn.commit()
    threading.Thread(target=_outreach_run_autopilot_job, args=(job_id, params), daemon=True).start()
    return {"ok": True, "job_id": job_id, "max": max_send, "send": bool(payload.send), "updated_engaged": updated_engaged, "followup_days": followup_days}


class AutopilotConfigPayload(BaseModel):
    enabled: Optional[bool] = None
    targets: Optional[List[Dict[str, str]]] = None
    target_companies: Optional[int] = None
    daily_new_target: Optional[int] = None
    daily_cold_cap: Optional[int] = None
    auto_followups: Optional[bool] = None
    followup_days: Optional[Dict[str, int]] = None
    discovery_enabled: Optional[bool] = None




@app.get("/admin/outreach/autopilot-config", dependencies=[Depends(_require_admin_token)])
def outreach_autopilot_config_get():
    with _outreach_db() as conn:
        return _autopilot_config_row(conn)


@app.put("/admin/outreach/autopilot-config", dependencies=[Depends(_require_admin_token)])
def outreach_autopilot_config_put(payload: AutopilotConfigPayload):
    fields = []
    params: List[Any] = []
    prev_enabled = None
    with _outreach_db() as conn:
        row = conn.execute("SELECT enabled FROM autopilot_config WHERE id=1").fetchone()
        prev_enabled = bool(row["enabled"]) if row else False
    if payload.enabled is not None:
        fields.append("enabled=?"); params.append(1 if payload.enabled else 0)
    if payload.targets is not None:
        clean_targets = []
        for t in payload.targets:
            s = (t.get("sector") or "").strip()
            c = (t.get("city") or "").strip()
            if s and c:
                clean_targets.append({"sector": s, "city": c})
        fields.append("targets_json=?"); params.append(json.dumps(clean_targets, ensure_ascii=False))
    if payload.target_companies is not None:
        target_companies = _autopilot_target_companies(payload.target_companies)
        fields.append("daily_new_target=?"); params.append(target_companies)
        fields.append("daily_cold_cap=?"); params.append(target_companies)
    if payload.daily_new_target is not None and payload.target_companies is None:
        fields.append("daily_new_target=?"); params.append(max(1, min(200, int(payload.daily_new_target))))
    if payload.daily_cold_cap is not None and payload.target_companies is None:
        fields.append("daily_cold_cap=?"); params.append(max(1, min(200, int(payload.daily_cold_cap))))
    if payload.auto_followups is not None:
        fields.append("auto_followups=?"); params.append(1 if payload.auto_followups else 0)
    if payload.discovery_enabled is not None:
        fields.append("discovery_enabled=?"); params.append(1 if payload.discovery_enabled else 0)
    if payload.followup_days is not None:
        followup_days = _outreach_normalize_followup_days(payload.followup_days)
        fields.append("followup_days_json=?"); params.append(json.dumps(followup_days, ensure_ascii=False))
    fields.append("updated_at=?"); params.append(_outreach_now())
    with _outreach_db() as conn:
        _outreach_ensure_autopilot_config_columns(conn)
        conn.execute(f"UPDATE autopilot_config SET {', '.join(fields)} WHERE id=1", params)
        conn.commit()
        result = _autopilot_config_row(conn)

    # Loggear cambios significativos.
    if payload.enabled is not None and payload.enabled != prev_enabled:
        if payload.enabled:
            _autopilot_log("info", "enabled_via_panel",
                           "Modo automático activado desde el panel",
                           {"blockers": result.get("blockers", [])})
            # Dispara tick inmediato para feedback en log.
            result["tick_started"] = _outreach_start_autonomous_tick(source="enabled_via_panel")
        else:
            _autopilot_log("info", "disabled_via_panel",
                           "Modo automático pausado desde el panel")
    if payload.targets is not None:
        _autopilot_log("info", "targets_updated",
                       f"Objetivos actualizados ({result.get('targets_count', 0)} combos)",
                       {"targets": result.get("targets", [])})
    if payload.target_companies is not None:
        _autopilot_log("info", "target_companies_updated",
                       f"Objetivo actualizado: contactar {result.get('target_companies', 0)} empresas",
                       {"target_companies": result.get("target_companies", 0)})
    if payload.followup_days is not None:
        _autopilot_log("info", "followup_days_updated",
                       "Tiempos de follow-up actualizados",
                       {"followup_days": result.get("followup_days", {})})
    if payload.discovery_enabled is not None:
        _autopilot_log("info", "discovery_enabled_updated",
                       f"Discovery {'activado' if payload.discovery_enabled else 'desactivado'} desde el panel",
                       {"discovery_enabled": bool(payload.discovery_enabled)})
    return result


@app.post("/admin/outreach/autopilot-tick", dependencies=[Depends(_require_admin_token)])
def outreach_autopilot_tick():
    """Fuerza una ronda del worker autónomo."""
    _autopilot_log("info", "manual_run_requested",
                   "Ronda solicitada manualmente desde el panel")
    started = _outreach_start_autonomous_tick(source="manual_panel", log_overlap=True)
    return {"ok": True, "started": started, "started_at": _outreach_now()}


@app.get("/admin/outreach/autopilot-log", dependencies=[Depends(_require_admin_token)])
def outreach_autopilot_log(limit: int = 100, level: str = "", since_id: int = 0):
    """Últimos eventos del modo automático. Ordenados por id desc."""
    limit = max(1, min(500, int(limit or 100)))
    where = []
    params: List[Any] = []
    if since_id:
        where.append("id > ?")
        params.append(int(since_id))
    lvl = (level or "").strip().lower()
    if lvl in {"info", "success", "warning", "error"}:
        where.append("level = ?")
        params.append(lvl)
    sql = "SELECT id, ts, level, event, message, detail FROM autopilot_activity_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _outreach_db() as conn:
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS autopilot_activity_log (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       ts TEXT NOT NULL,
                       level TEXT NOT NULL DEFAULT 'info',
                       event TEXT NOT NULL DEFAULT '',
                       message TEXT NOT NULL DEFAULT '',
                       detail TEXT DEFAULT ''
                   )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_autopilot_log_ts ON autopilot_activity_log(ts)")
            conn.commit()
            rows = conn.execute(sql, params).fetchall()
    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "ts": r["ts"],
            "level": r["level"],
            "event": r["event"],
            "message": r["message"],
            "detail": r["detail"] or "",
        })
    return {"items": items, "count": len(items)}


@app.get("/admin/outreach/prospects/{email}/followup-copy", dependencies=[Depends(_require_admin_token)])
def outreach_prospect_followup_copy(email: str):
    email_l = email.lower().strip()
    with _outreach_db() as conn:
        row = conn.execute(
            """
            SELECT p.email, p.business_name, p.contact_name, p.niche, p.service_hint, p.city,
                   p.phone, p.website, p.tags, p.source, COALESCE(p.status,'new') AS status,
                   (SELECT MAX(s.sent_at) FROM sends s WHERE s.email=p.email AND s.mode='send') AS last_sent_at,
                   (SELECT MAX(e.ts) FROM events e WHERE e.email=p.email) AS last_event_at,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open') AS opens,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='demo_generated') AS demos,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply_intent') AS reply_intents,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply') AS replies,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send') AS total_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu1') AS fu1_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu2') AS fu2_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='breakup') AS breakup_sent
            FROM prospects p
            WHERE p.email=?
            """,
            (email_l,),
        ).fetchone()
        followup_days = _outreach_config_followup_days(conn)
    if not row:
        raise HTTPException(status_code=404, detail="Prospect no encontrado.")
    return _outreach_followup_item(row, followup_days)


@app.get("/admin/outreach/ab-stats", dependencies=[Depends(_require_admin_token)])
def outreach_ab_stats(stage: str = "cold", days: int = 30):
    """A/B subjects: open rate y reply rate por variante (A vs B) en stage dado.

    Match opens/replies por email+stage para no contar eventos cruzados de stages
    siguientes. Solo cuenta envios reales (mode='send').
    """
    if stage not in OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    days = max(1, min(365, int(days or 30)))
    cutoff = (_utc_now() - timedelta(days=days)).isoformat(timespec="seconds")

    with _outreach_db() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(NULLIF(s.subject_variant, ''), '?') AS variant,
                   COUNT(DISTINCT s.email) AS sent,
                   SUM(CASE WHEN EXISTS (
                     SELECT 1 FROM events e WHERE e.email = s.email AND e.type = 'open'
                       AND e.stage = s.stage AND e.ts >= s.sent_at
                   ) THEN 1 ELSE 0 END) AS opens_unique,
                   SUM(CASE WHEN EXISTS (
                     SELECT 1 FROM events e WHERE e.email = s.email AND e.type = 'click'
                       AND e.stage = s.stage AND e.ts >= s.sent_at
                   ) THEN 1 ELSE 0 END) AS clicks_unique,
                   SUM(CASE WHEN EXISTS (
                     SELECT 1 FROM events e WHERE e.email = s.email AND e.type = 'reply'
                       AND e.ts >= s.sent_at
                   ) THEN 1 ELSE 0 END) AS replies_unique
            FROM sends s
            WHERE s.stage = ? AND s.mode = 'send' AND s.sent_at >= ?
            GROUP BY variant
            ORDER BY variant
            """,
            (stage, cutoff),
        ).fetchall()

        sample_rows = conn.execute(
            """SELECT subject_variant, subject, COUNT(*) AS c FROM sends
               WHERE stage = ? AND mode = 'send' AND sent_at >= ?
               GROUP BY subject_variant, subject ORDER BY c DESC LIMIT 20""",
            (stage, cutoff),
        ).fetchall()

    items = []
    for r in rows:
        sent = int(r["sent"] or 0)
        opens = int(r["opens_unique"] or 0)
        clicks = int(r["clicks_unique"] or 0)
        replies = int(r["replies_unique"] or 0)
        items.append({
            "variant": r["variant"],
            "sent": sent,
            "opens": opens,
            "clicks": clicks,
            "replies": replies,
            "open_rate_pct": round(opens / sent * 100, 1) if sent else 0.0,
            "click_rate_pct": round(clicks / sent * 100, 1) if sent else 0.0,
            "reply_rate_pct": round(replies / sent * 100, 1) if sent else 0.0,
        })

    samples = [
        {"variant": r["subject_variant"] or "?", "subject": r["subject"], "count": int(r["c"])}
        for r in sample_rows
    ]
    return {"stage": stage, "window_days": days, "variants": items, "samples": samples}






@app.post("/admin/outreach/imap/poll", dependencies=[Depends(_require_admin_token)])
def outreach_imap_poll_now():
    """Lanza una pasada del poller IMAP en modo sincrono (manual)."""
    if not OUTREACH_IMAP_AVAILABLE or outreach_imap_poll is None:
        raise HTTPException(status_code=503, detail="Modulo IMAP no disponible.")
    if not os.getenv("IMAP_HOST", "").strip():
        raise HTTPException(status_code=400, detail="IMAP_HOST no configurado en .env.")
    db_path = Path(os.getenv("OUTREACH_DB_PATH", str(OUTREACH_DEFAULT_DB)))
    stats = outreach_imap_poll(db_path)
    return {"ok": True, "stats": stats}


@app.get("/admin/outreach/ga4-stats", dependencies=[Depends(_require_admin_token)])
def outreach_ga4_stats(days: int = 30):
    """Sesiones por campaña UTM desde GA4 (utm_medium=email, utm_source=outreach)."""
    if not GA4_PROPERTY_ID:
        return {"ok": False, "error": "GA4_PROPERTY_ID no configurado.", "sessions": []}
    if not GA4_SERVICE_ACCOUNT_JSON:
        return {"ok": False, "error": "GA4_SERVICE_ACCOUNT_JSON no configurado.", "sessions": []}
    try:
        from google.oauth2 import service_account as _sa
        from google.auth.transport.requests import Request as _GRequest
        import requests as _req

        creds = _sa.Credentials.from_service_account_file(
            GA4_SERVICE_ACCOUNT_JSON,
            scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )
        creds.refresh(_GRequest())
        days_safe = max(1, min(365, int(days)))
        url = f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY_ID}:runReport"
        body = {
            "dateRanges": [{"startDate": f"{days_safe}daysAgo", "endDate": "today"}],
            "dimensions": [{"name": "sessionCampaignName"}, {"name": "date"}],
            "metrics": [{"name": "sessions"}, {"name": "activeUsers"}],
            "dimensionFilter": {
                "andGroup": {
                    "expressions": [
                        {"filter": {"fieldName": "sessionSource", "stringFilter": {"value": "outreach", "matchType": "EXACT"}}},
                        {"filter": {"fieldName": "sessionMedium", "stringFilter": {"value": "email", "matchType": "EXACT"}}},
                    ]
                }
            },
        }
        resp = _req.post(url, json=body, headers={"Authorization": f"Bearer {creds.token}"}, timeout=10)
        if not resp.ok:
            return {"ok": False, "error": f"GA4 API {resp.status_code}: {resp.text[:200]}", "sessions": []}
        rows = resp.json().get("rows", [])
        by_campaign: dict[str, dict] = {}
        for row in rows:
            campaign = row["dimensionValues"][0]["value"]
            sessions = int(row["metricValues"][0]["value"])
            users = int(row["metricValues"][1]["value"])
            if campaign not in by_campaign:
                by_campaign[campaign] = {"campaign": campaign, "sessions": 0, "users": 0}
            by_campaign[campaign]["sessions"] += sessions
            by_campaign[campaign]["users"] += users
        result = sorted(by_campaign.values(), key=lambda x: x["sessions"], reverse=True)
        return {"ok": True, "sessions": result, "days": days_safe}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "sessions": []}


# ----- Prospects list/detail/CRUD -----

@app.get("/admin/outreach/prospects", dependencies=[Depends(_require_admin_token)])
def outreach_list_prospects(
    q: str = "",
    status: str = "",
    niche: str = "",
    city: str = "",
    source: str = "",
    stage: str = "",
    clicked_vantelia: bool = False,
    days: int = 0,
    page: int = 1,
    page_size: int = 50,
):
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    offset = (page - 1) * page_size

    where = []
    params: list = []
    if q:
        where.append("(p.business_name LIKE ? OR p.email LIKE ? OR p.contact_name LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if status:
        where.append("p.status = ?")
        params.append(status)
    if niche:
        where.append("p.niche LIKE ?")
        params.append(f"%{niche}%")
    if city:
        where.append("p.city LIKE ?")
        params.append(f"%{city}%")
    if source:
        where.append("p.source LIKE ?")
        params.append(f"%{source}%")
    if days and days > 0:
        cutoff = (_utc_now() - timedelta(days=int(days))).isoformat(timespec="seconds")
        where.append("p.updated_at >= ?")
        params.append(cutoff)
    if clicked_vantelia:
        where.append(
            """EXISTS (
                SELECT 1 FROM events ev
                WHERE ev.email=p.email AND ev.type='click'
                  AND (lower(coalesce(ev.url,'')) LIKE 'https://www.vantelia.es%'
                       OR lower(coalesce(ev.url,'')) LIKE 'https://vantelia.es%')
            )"""
        )

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    with _outreach_db() as conn:
        sql = f"""
        SELECT p.*,
               (SELECT stage FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_stage,
               (SELECT sent_at FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_sent_at,
               (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='cold') AS cold_sent,
               (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu1') AS fu1_sent,
               (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu2') AS fu2_sent,
               (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='breakup') AS breakup_sent,
               (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open') AS opens,
               (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks,
               (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click'
                  AND (lower(coalesce(e.url,'')) LIKE 'https://www.vantelia.es%'
                       OR lower(coalesce(e.url,'')) LIKE 'https://vantelia.es%')) AS vantelia_clicks,
               (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply_intent') AS reply_intents,
               (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply') AS replies,
               (SELECT 1 FROM suppressions x WHERE x.email=p.email) AS suppressed
        FROM prospects p
        {where_sql}
        """
        if stage:
            sql += " AND last_stage = ? "
            params.append(stage)
        sql += " ORDER BY p.updated_at DESC LIMIT ? OFFSET ?"
        params.extend([page_size, offset])

        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(f"SELECT COUNT(*) AS c FROM prospects p {where_sql}", params[:-2]).fetchone()["c"]

    items = []
    for r in rows:
        items.append({
            "email": r["email"],
            "business_name": r["business_name"],
            "contact_name": r["contact_name"],
            "niche": r["niche"],
            "website": r["website"],
            "service_hint": r["service_hint"],
            "city": r["city"],
            "phone": r["phone"],
            "tags": r["tags"],
            "source": r["source"],
            "status": r["status"] if "status" in r.keys() else "new",
            "notes": r["notes"] if "notes" in r.keys() else "",
            "score": r["score"] if "score" in r.keys() else 0,
            "last_stage": r["last_stage"],
            "last_sent_at": r["last_sent_at"],
            "cold_sent": r["cold_sent"],
            "fu1_sent": r["fu1_sent"],
            "fu2_sent": r["fu2_sent"],
            "breakup_sent": r["breakup_sent"],
            "opens": r["opens"],
            "clicks": r["clicks"],
            "vantelia_clicks": r["vantelia_clicks"],
            "reply_intents": r["reply_intents"],
            "replies": r["replies"],
            "suppressed": bool(r["suppressed"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/admin/outreach/prospects/{email}", dependencies=[Depends(_require_admin_token)])
def outreach_prospect_detail(email: str):
    email_l = email.lower().strip()
    with _outreach_db() as conn:
        row = conn.execute("SELECT * FROM prospects WHERE email=?", (email_l,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Prospect no encontrado.")
        sends = conn.execute(
            "SELECT id, stage, subject, body_text, body_html, sent_at, mode, message_id FROM sends WHERE email=? ORDER BY id ASC",
            (email_l,),
        ).fetchall()
        events = conn.execute(
            "SELECT id, type, stage, url, ts, ua FROM events WHERE email=? ORDER BY id ASC",
            (email_l,),
        ).fetchall()
        suppression = conn.execute("SELECT reason, added_at FROM suppressions WHERE email=?", (email_l,)).fetchone()
    return {
        "prospect": {k: row[k] for k in row.keys()},
        "sends": [dict(r) for r in sends],
        "events": [dict(r) for r in events],
        "suppression": dict(suppression) if suppression else None,
    }


class OutreachProspectsBulkIn(BaseModel):
    items: List[OutreachProspectIn]
    upsert: bool = False


@app.post("/admin/outreach/prospects/bulk", dependencies=[Depends(_require_admin_token)])
def outreach_bulk_prospects(payload: OutreachProspectsBulkIn):
    added = updated = skipped = 0
    now = _outreach_now()
    with _outreach_db() as conn:
        for item in payload.items:
            email = str(item.email).lower().strip()
            if not email:
                skipped += 1
                continue
            existing = conn.execute("SELECT email FROM prospects WHERE email=?", (email,)).fetchone()
            if existing:
                if payload.upsert:
                    conn.execute(
                        """UPDATE prospects SET business_name=?, contact_name=?, niche=?, website=?,
                           service_hint=?, city=?, phone=?, tags=?, source=?, updated_at=? WHERE email=?""",
                        (item.business_name, item.contact_name, item.niche, item.website,
                         item.service_hint, item.city or "Torrejon de Ardoz", item.phone,
                         item.tags, item.source, now, email),
                    )
                    updated += 1
                else:
                    skipped += 1
                continue
            conn.execute(
                """INSERT INTO prospects (email, business_name, contact_name, niche, website,
                   service_hint, city, phone, tags, source, status, notes, score, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (email, item.business_name, item.contact_name, item.niche, item.website,
                 item.service_hint, item.city or "Torrejon de Ardoz", item.phone, item.tags,
                 item.source, item.status, item.notes, int(item.score or 0), now, now),
            )
            added += 1
        conn.commit()
    return {"ok": True, "added": added, "updated": updated, "skipped": skipped}


@app.post("/admin/outreach/prospects", dependencies=[Depends(_require_admin_token)])
def outreach_create_prospect(payload: OutreachProspectIn):
    email = str(payload.email).lower().strip()
    now = _outreach_now()
    with _outreach_db() as conn:
        existing = conn.execute("SELECT email FROM prospects WHERE email=?", (email,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Ya existe.")
        conn.execute(
            """INSERT INTO prospects (email, business_name, contact_name, niche, website,
               service_hint, city, phone, tags, source, status, notes, score, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (email, payload.business_name, payload.contact_name, payload.niche, payload.website,
             payload.service_hint, payload.city or "Torrejon de Ardoz", payload.phone, payload.tags,
             payload.source, payload.status, payload.notes, int(payload.score or 0), now, now),
        )
        conn.commit()
    return {"ok": True, "email": email}


@app.patch("/admin/outreach/prospects/{email}", dependencies=[Depends(_require_admin_token)])
def outreach_update_prospect(email: str, payload: OutreachProspectPatch):
    email_l = email.lower().strip()
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not fields:
        return {"ok": True, "updated": 0}
    fields["updated_at"] = _outreach_now()
    set_sql = ", ".join(f"{k}=?" for k in fields.keys())
    with _outreach_db() as conn:
        cur = conn.execute(f"UPDATE prospects SET {set_sql} WHERE email=?", (*fields.values(), email_l))
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Prospect no encontrado.")
    return {"ok": True, "updated": cur.rowcount}


@app.delete("/admin/outreach/prospects/{email}", dependencies=[Depends(_require_admin_token)])
def outreach_delete_prospect(email: str):
    email_l = email.lower().strip()
    with _outreach_db() as conn:
        cur = conn.execute("DELETE FROM prospects WHERE email=?", (email_l,))
        conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


# ----- Import CSV -----

@app.post("/admin/outreach/import", dependencies=[Depends(_require_admin_token)])
async def outreach_import_csv(request: Request):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="CSV vacio.")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = body.decode("latin-1", errors="replace")
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV sin cabecera.")
    added = updated = skipped = 0
    now = _outreach_now()
    with _outreach_db() as conn:
        for row in reader:
            email = (row.get("email") or "").strip().lower()
            business = (row.get("business_name") or "").strip()
            if not email or "@" not in email or not business:
                skipped += 1
                continue
            payload = {
                "email": email,
                "business_name": business,
                "contact_name": (row.get("contact_name") or "").strip(),
                "niche": (row.get("niche") or "").strip(),
                "website": (row.get("website") or "").strip(),
                "service_hint": (row.get("service_hint") or "").strip(),
                "city": (row.get("city") or "").strip() or "Torrejon de Ardoz",
                "phone": (row.get("phone") or "").strip(),
                "tags": (row.get("tags") or "").strip(),
                "source": (row.get("source") or "csv-upload").strip(),
                "now": now,
            }
            existing = conn.execute("SELECT email FROM prospects WHERE email=?", (email,)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE prospects SET business_name=:business_name, contact_name=:contact_name,
                       niche=:niche, website=:website, service_hint=:service_hint, city=:city,
                       phone=:phone, tags=:tags, source=:source,
                       updated_at=:now WHERE email=:email""",
                    payload,
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO prospects (email, business_name, contact_name, niche, website,
                       service_hint, city, phone, tags, source, created_at, updated_at)
                       VALUES (:email, :business_name, :contact_name, :niche, :website,
                       :service_hint, :city, :phone, :tags, :source, :now, :now)""",
                    payload,
                )
                added += 1
        conn.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


@app.get("/admin/outreach/export.csv", dependencies=[Depends(_require_admin_token)])
def outreach_export_csv():
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "email", "business_name", "contact_name", "niche", "website", "service_hint",
        "city", "phone", "tags", "source", "status", "score", "last_stage", "last_sent_at",
        "opens", "clicks", "reply_intents", "replies", "suppressed",
    ])
    with _outreach_db() as conn:
        rows = conn.execute(
            """SELECT p.*,
                  (SELECT stage FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_stage,
                  (SELECT sent_at FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_sent_at,
                  (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open') AS opens,
                  (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks,
                  (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply_intent') AS reply_intents,
                  (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply') AS replies,
                  (SELECT 1 FROM suppressions x WHERE x.email=p.email) AS suppressed
                FROM prospects p ORDER BY p.created_at ASC"""
        ).fetchall()
    for r in rows:
        writer.writerow([
            r["email"], r["business_name"], r["contact_name"], r["niche"], r["website"],
            r["service_hint"], r["city"], r["phone"], r["tags"], r["source"],
            r["status"] if "status" in r.keys() else "new",
            r["score"] if "score" in r.keys() else 0,
            r["last_stage"] or "", r["last_sent_at"] or "",
            r["opens"], r["clicks"], r["reply_intents"], r["replies"], "1" if r["suppressed"] else "0",
        ])
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="outreach_prospects.csv"'},
    )


# ----- Suppressions -----

@app.post("/admin/outreach/suppress", dependencies=[Depends(_require_admin_token)])
def outreach_suppress(payload: OutreachSuppressRequest):
    email = str(payload.email).lower().strip()
    with _outreach_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO suppressions (email, reason, added_at) VALUES (?,?,?)",
            (email, payload.reason or "manual", _outreach_now()),
        )
        conn.commit()
    return {"ok": True}


@app.delete("/admin/outreach/suppress/{email}", dependencies=[Depends(_require_admin_token)])
def outreach_unsuppress(email: str):
    with _outreach_db() as conn:
        cur = conn.execute("DELETE FROM suppressions WHERE email=?", (email.lower().strip(),))
        conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


@app.get("/admin/outreach/suppressions", dependencies=[Depends(_require_admin_token)])
def outreach_list_suppressions():
    with _outreach_db() as conn:
        rows = conn.execute("SELECT email, reason, added_at FROM suppressions ORDER BY added_at DESC").fetchall()
    return {"items": [dict(r) for r in rows]}


# ----- Templates overrides -----

@app.get("/admin/outreach/templates", dependencies=[Depends(_require_admin_token)])
def outreach_get_templates():
    with _outreach_db() as conn:
        rows = conn.execute("SELECT * FROM templates_overrides").fetchall()
    overrides = {r["stage"]: dict(r) for r in rows}

    # Render defaults with placeholder variables so the panel can pre-populate the form
    defaults: dict = {}
    if OUTREACH_AVAILABLE:
        _placeholder = OutreachProspect(
            email="demo@example.com",
            business_name="{business}",
            contact_name="{first_name}",
            niche="{niche}",
            city="{city}",
            service_hint="{service_hint}",
            website="{website}",
        )
        for _stage in OUTREACH_STAGES:
            try:
                _subj, _text, _html = outreach_render(_stage, _placeholder, "{unsubscribe}")
                defaults[_stage] = {
                    "subject_pool": _subj,
                    "body_text": _text,
                    "body_html": _html,
                }
            except Exception:
                pass

    return {"stages": OUTREACH_STAGES, "overrides": overrides, "defaults": defaults}


@app.put("/admin/outreach/templates", dependencies=[Depends(_require_admin_token)])
def outreach_put_template(payload: OutreachTemplateOverride):
    if payload.stage not in OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    with _outreach_db() as conn:
        conn.execute(
            """INSERT INTO templates_overrides (stage, subject_pool, body_text, body_html, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(stage) DO UPDATE SET subject_pool=excluded.subject_pool,
                   body_text=excluded.body_text, body_html=excluded.body_html, updated_at=excluded.updated_at""",
            (payload.stage, payload.subject_pool, payload.body_text, payload.body_html, _outreach_now()),
        )
        conn.commit()
    return {"ok": True}


@app.delete("/admin/outreach/templates/{stage}", dependencies=[Depends(_require_admin_token)])
def outreach_delete_template(stage: str):
    if stage not in OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    with _outreach_db() as conn:
        conn.execute("DELETE FROM templates_overrides WHERE stage=?", (stage,))
        conn.commit()
    return {"ok": True}


class OutreachTemplatePreview(BaseModel):
    stage: str
    subject_pool: str = ""
    body_text: str = ""
    body_html: str = ""
    sample_business: str = "Dental Smile"
    sample_first_name: str = "Maria"
    sample_niche: str = "clinica dental"
    sample_city: str = "Torrejon de Ardoz"
    sample_website: str = "https://dentalsmile.es"
    sample_email: str = "maria@dentalsmile.es"




@app.get("/admin/outreach/prospects/{email}/render", dependencies=[Depends(_require_admin_token)])
def outreach_render_prospect_email(email: str, stage: str = "cold", send_id: int = 0):
    if not OUTREACH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Outreach no disponible.")
    email = email.lower().strip()
    from outreach_campaign import render_with_override, load_template_overrides  # type: ignore
    with _outreach_db() as conn:
        if send_id:
            send_row = conn.execute(
                "SELECT id, email, stage, subject, body_text, body_html FROM sends WHERE id=? AND email=?",
                (send_id, email),
            ).fetchone()
            if not send_row:
                raise HTTPException(status_code=404, detail="Envio no encontrado.")
            if send_row["body_text"] or send_row["body_html"]:
                return {
                    "subject": send_row["subject"] or "",
                    "text": send_row["body_text"] or "",
                    "html": _outreach_admin_preview_html(send_row["body_html"] or ""),
                    "stage": send_row["stage"] or stage,
                    "email": email,
                    "send_id": send_id,
                    "snapshot": True,
                }
        if stage not in OUTREACH_STAGES:
            raise HTTPException(status_code=400, detail="Stage invalido.")
        row = conn.execute("SELECT * FROM prospects WHERE email=?", (email,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Prospect no encontrado.")
        overrides = load_template_overrides(conn)
    p = OutreachProspect(
        email=row["email"],
        business_name=row["business_name"] or "",
        contact_name=row["contact_name"] or "",
        niche=row["niche"] or "",
        service_hint=row["service_hint"] or "",
        city=row["city"] or "",
        website=row["website"] or "",
        phone=row["phone"] or "",
        tags=row["tags"] or "",
        source=row["source"] or "",
    )
    unsub = os.getenv("OUTREACH_UNSUBSCRIBE_EMAIL", "baja@vantelia.es").strip() or "baja@vantelia.es"
    subject, text, html = render_with_override(stage, p, unsub, overrides)
    return {"subject": subject, "text": text, "html": _outreach_admin_preview_html(html), "stage": stage, "email": email}


@app.post("/admin/outreach/templates/preview", dependencies=[Depends(_require_admin_token)])
def outreach_preview_template(payload: OutreachTemplatePreview):
    if not OUTREACH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Outreach no disponible.")
    if payload.stage not in OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    from outreach_campaign import render_with_override  # type: ignore
    p = OutreachProspect(
        email=payload.sample_email,
        business_name=payload.sample_business,
        contact_name=payload.sample_first_name,
        niche=payload.sample_niche,
        service_hint=payload.sample_niche,
        city=payload.sample_city,
        website=payload.sample_website,
    )
    unsub = os.getenv("OUTREACH_UNSUBSCRIBE_EMAIL", "baja@vantelia.es").strip() or "baja@vantelia.es"
    overrides = {payload.stage: {
        "subject_pool": payload.subject_pool,
        "body_text": payload.body_text,
        "body_html": payload.body_html,
    }}
    subject, text, html = render_with_override(payload.stage, p, unsub, overrides)
    return {"subject": subject, "text": text, "html": html}














@app.get("/admin/outreach/campaigns", dependencies=[Depends(_require_admin_token)])
def outreach_list_campaigns(limit: int = 50):
    limit = max(1, min(200, int(limit)))
    with _outreach_db() as conn:
        _outreach_backfill_orphan_send_campaigns(conn)
        rows = conn.execute(
            "SELECT * FROM campaigns ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"items": [_outreach_campaign_summary(conn, r) for r in rows]}


@app.post("/admin/outreach/campaigns", dependencies=[Depends(_require_admin_token)])
def outreach_create_campaign(payload: OutreachCampaignCreate):
    if payload.stage not in OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    emails = [str(email).lower().strip() for email in payload.emails if str(email).strip()]
    with _outreach_db() as conn:
        campaign_id = _outreach_create_campaign(
            conn,
            name=payload.name,
            stage=payload.stage,
            emails=emails,
            settings=outreach_smtp_settings(),
            delay=payload.delay,
            jitter=payload.jitter,
            force_window=payload.force_window,
            status="draft",
        )
        conn.commit()
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        return _outreach_campaign_summary(conn, row)


@app.get("/admin/outreach/campaigns/{campaign_id}", dependencies=[Depends(_require_admin_token)])
def outreach_campaign_detail(campaign_id: int):
    with _outreach_db() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Campana no encontrada.")
        members = conn.execute(
            """SELECT cm.*, p.business_name, p.website, p.phone
               FROM campaign_members cm
               LEFT JOIN prospects p ON p.email=cm.email
               WHERE cm.campaign_id=?
               ORDER BY cm.id ASC""",
            (campaign_id,),
        ).fetchall()
        return {
            "campaign": _outreach_campaign_summary(conn, row),
            "members": [dict(r) for r in members],
        }


@app.patch("/admin/outreach/campaigns/{campaign_id}", dependencies=[Depends(_require_admin_token)])
def outreach_patch_campaign(campaign_id: int, payload: OutreachCampaignPatch):
    allowed = {"draft", "running", "paused", "completed", "archived"}
    fields = []
    values: List[Any] = []
    if payload.status is not None:
        if payload.status not in allowed:
            raise HTTPException(status_code=400, detail="Estado invalido.")
        fields.append("status=?")
        values.append(payload.status)
    if payload.name is not None:
        fields.append("name=?")
        values.append(payload.name.strip()[:180] or "Campana")
    if not fields:
        raise HTTPException(status_code=400, detail="Sin cambios.")
    fields.append("updated_at=?")
    values.append(_outreach_now())
    values.append(campaign_id)
    with _outreach_db() as conn:
        cur = conn.execute(f"UPDATE campaigns SET {', '.join(fields)} WHERE id=?", values)
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Campana no encontrada.")
        conn.commit()
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        return _outreach_campaign_summary(conn, row)


@app.post("/admin/outreach/campaigns/{campaign_id}/duplicate", dependencies=[Depends(_require_admin_token)])
def outreach_duplicate_campaign(campaign_id: int):
    with _outreach_db() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Campana no encontrada.")
        emails = [r["email"] for r in conn.execute("SELECT email FROM campaign_members WHERE campaign_id=? ORDER BY id ASC", (campaign_id,))]
        new_id = _outreach_create_campaign(
            conn,
            name=f"{row['name']} copia",
            stage=row["stage"],
            emails=emails,
            settings={"from_email": row["sender"]},
            delay=float(row["delay"] or 70),
            jitter=float(row["jitter"] or 25),
            force_window=bool(row["force_window"]),
            status="draft",
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM campaigns WHERE id=?", (new_id,)).fetchone()
        return _outreach_campaign_summary(conn, new_row)


@app.post("/admin/outreach/campaigns/{campaign_id}/resume", dependencies=[Depends(_require_admin_token)])
def outreach_resume_campaign(campaign_id: int):
    with _outreach_db() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Campana no encontrada.")
        if row["status"] == "archived":
            raise HTTPException(status_code=400, detail="No se puede reanudar una campana archivada.")
        emails = [
            r["email"] for r in conn.execute(
                "SELECT email FROM campaign_members WHERE campaign_id=? AND status='pending' ORDER BY id ASC",
                (campaign_id,),
            )
        ]
        if not emails:
            conn.execute("UPDATE campaigns SET status='completed', updated_at=? WHERE id=?", (_outreach_now(), campaign_id))
            conn.commit()
            return {"ok": True, "campaign_id": campaign_id, "job_id": 0, "message": "Sin pendientes; campana completada."}
        params = {
            "stage": row["stage"] or "cold",
            "max": len(emails),
            "send": True,
            "test_to": "",
            "email": "",
            "emails": emails,
            "campaign_name": row["name"],
            "campaign_id": campaign_id,
            "after_days": 4,
            "delay": float(row["delay"] or 70),
            "jitter": float(row["jitter"] or 25),
            "force_window": bool(row["force_window"]),
            "dry_run": False,
        }
        cur = conn.execute(
            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
            ("send", "queued", json.dumps(params), "", _outreach_now()),
        )
        job_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE campaigns SET status='running', job_id=?, updated_at=? WHERE id=?",
            (job_id, _outreach_now(), campaign_id),
        )
        conn.commit()
    threading.Thread(target=_outreach_run_send_job, args=(job_id, params), daemon=True).start()
    return {"ok": True, "campaign_id": campaign_id, "job_id": job_id}


@app.post("/admin/outreach/campaigns/{campaign_id}/prepare-followup", dependencies=[Depends(_require_admin_token)])
def outreach_prepare_campaign_followup(campaign_id: int):
    with _outreach_db() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Campana no encontrada.")
        stage = row["stage"] or "cold"
        try:
            next_stage = OUTREACH_STAGES[OUTREACH_STAGES.index(stage) + 1]
        except Exception:
            raise HTTPException(status_code=400, detail="Esta campana ya esta en la ultima etapa.")
        suppressed = 0
        replied = 0
        already_sent = 0
        eligible: List[str] = []
        for member in conn.execute("SELECT email FROM campaign_members WHERE campaign_id=? ORDER BY id ASC", (campaign_id,)):
            email = member["email"]
            if conn.execute("SELECT 1 FROM suppressions WHERE email=?", (email,)).fetchone():
                suppressed += 1
            elif conn.execute("SELECT 1 FROM events WHERE email=? AND type='reply'", (email,)).fetchone():
                replied += 1
            elif conn.execute("SELECT 1 FROM sends WHERE email=? AND stage=? AND mode='send'", (email, next_stage)).fetchone():
                already_sent += 1
            elif conn.execute("SELECT 1 FROM sends WHERE email=? AND stage=? AND mode='send'", (email, stage)).fetchone():
                eligible.append(email)
        return {
            "campaign_id": campaign_id,
            "campaign_name": row["name"],
            "from_stage": stage,
            "next_stage": next_stage,
            "eligible_emails": eligible,
            "counts": {
                "eligible": len(eligible),
                "suppressed": suppressed,
                "replied": replied,
                "already_sent": already_sent,
            },
        }


@app.post("/admin/outreach/preflight", dependencies=[Depends(_require_admin_token)])
def outreach_preflight(payload: OutreachPreflightRequest):
    if not OUTREACH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Outreach no disponible.")
    if payload.stage not in OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")

    selected_emails = [
        str(email).lower().strip()
        for email in payload.emails
        if str(email).strip()
    ]
    settings = outreach_smtp_settings()
    unsub = str(settings["unsubscribe_mailto"]) or "baja@vantelia.es"

    with _outreach_db() as conn:
        try:
            from outreach_campaign import render_with_override, load_template_overrides  # type: ignore
            overrides = load_template_overrides(conn)
        except Exception:
            overrides = {}

        rows = []
        if selected_emails:
            placeholders = ",".join("?" for _ in selected_emails)
            rows = conn.execute(
                f"SELECT * FROM prospects WHERE email IN ({placeholders}) ORDER BY created_at ASC",
                selected_emails,
            ).fetchall()
        else:
            candidates = outreach_fetch_candidates(
                conn,
                payload.stage,
                after_days=int(payload.after_days or 4),
                limit=int(payload.max or 20),
                only_email=None,
            )
            rows = []
            for p in candidates:
                row = conn.execute("SELECT * FROM prospects WHERE email=?", (p.email,)).fetchone()
                if row:
                    rows.append(row)

        missing_requested = max(0, len(set(selected_emails)) - len(rows)) if selected_emails else 0
        suppressed = 0
        missing_email = 0
        already_contacted = 0
        already_in_campaign = 0
        real_rows = []
        skipped_samples = []
        for row in rows:
            email = (row["email"] or "").strip().lower()
            reason = ""
            if not email or "@" not in email:
                missing_email += 1
                reason = "sin email"
            elif conn.execute("SELECT 1 FROM suppressions WHERE email=?", (email,)).fetchone():
                suppressed += 1
                reason = "baja"
            elif conn.execute("SELECT 1 FROM campaign_members WHERE email=?", (email,)).fetchone():
                already_in_campaign += 1
                reason = "ya en otra campana"
            elif payload.stage == "cold" and conn.execute("SELECT 1 FROM sends WHERE email=? AND mode='send'", (email,)).fetchone():
                already_contacted += 1
                reason = "ya contactado"
            elif payload.stage != "cold" and conn.execute("SELECT 1 FROM sends WHERE email=? AND stage=? AND mode='send'", (email, payload.stage)).fetchone():
                already_contacted += 1
                reason = "stage ya enviado"
            if reason:
                if len(skipped_samples) < 8:
                    skipped_samples.append({"email": email or "-", "reason": reason})
                continue
            real_rows.append(row)

        real_count = len(real_rows)
        first = real_rows[0] if real_rows else (rows[0] if rows else None)
        subject = ""
        text = ""
        html = ""
        if first:
            preview_prospect = OutreachProspect(
                email=first["email"] or "test@example.com",
                business_name=first["business_name"] or "Prospect de prueba",
                contact_name=first["contact_name"] or "",
                niche=first["niche"] or "",
                service_hint=first["service_hint"] or "",
                city=first["city"] or "",
                website=first["website"] or "",
                phone=first["phone"] or "",
                tags=first["tags"] or "",
                source=first["source"] or "",
            )
        else:
            # El wizard puede llegar a preflight con emails descubiertos pero aun no
            # importados. Seguimos marcando 0 candidatos reales, pero renderizamos
            # una muestra para validar HTML/variables sin mostrar "solo texto plano".
            preview_prospect = OutreachProspect(
                email=(selected_emails[0] if selected_emails else "test@example.com"),
                business_name="Prospect de prueba",
                contact_name="",
                niche="",
                service_hint="",
                city="Madrid",
                website="",
                phone="",
                tags="",
                source="preflight",
            )
        if preview_prospect:
            if overrides:
                subject, text, html = render_with_override(payload.stage, preview_prospect, unsub, overrides)
            else:
                subject, text, html = outreach_render(payload.stage, preview_prospect, unsub)

    warnings = {
        "empty_href": bool(re.search(r'href=(["\'])\s*\1', html or "", re.IGNORECASE)),
        "code_fence": "```" in (html or "") or "```" in (text or ""),
        "unfilled_variables": _outreach_unfilled_vars(subject, text, html),
    }
    html_active = bool(html)
    tracking_active = bool((not OUTREACH_TRACKING_DISABLED) and OUTREACH_TRACKING_SECRET and OUTREACH_TRACKING_BASE_URL)
    return {
        "stage": payload.stage,
        "counts": {
            "requested": len(selected_emails) if selected_emails else int(payload.max or 20),
            "found": len(rows),
            "real_candidates": real_count,
            "skipped": {
                "suppressed": suppressed,
                "missing_email": missing_email + missing_requested,
                "already_contacted": already_contacted,
                "already_in_campaign": already_in_campaign,
                "total": suppressed + missing_email + missing_requested + already_contacted + already_in_campaign,
            },
        },
        "skipped_samples": skipped_samples,
        "subject": subject,
        "text": text,
        "html": html,
        "html_active": html_active,
        "tracking_active": tracking_active,
        "warnings": warnings,
        "auth": _outreach_preflight_auth_status(settings),
        "sender": {
            "from_email": settings.get("from_email"),
            "from_name": settings.get("from_name"),
            "smtp_host": settings.get("host"),
        },
    }


# ----- Send/jobs -----

OUTREACH_JOB_LOCK = threading.Lock()

















































@app.post("/admin/outreach/manual-email/send", dependencies=[Depends(_require_admin_token)])
def sendManualAcquisitionEmail(payload: OutreachManualEmailPayload):
    recipient = str(payload.recipient).strip().lower()
    subject = payload.subject.strip()
    text_body = payload.text.strip()
    html_body = payload.html.strip()
    css_body = payload.css.strip()
    if not subject:
        raise HTTPException(status_code=400, detail="El asunto es obligatorio.")
    if not text_body and not html_body:
        raise HTTPException(status_code=400, detail="Anade texto plano o HTML antes de enviar.")

    final_html = _manual_email_html_document(html_body, css_body) if html_body or css_body else ""
    now = _outreach_now()
    message_id = ""

    if OUTREACH_AVAILABLE:
        with _outreach_db() as conn:
            suppressed = conn.execute("SELECT reason FROM suppressions WHERE email=?", (recipient,)).fetchone()
            if suppressed:
                raise HTTPException(status_code=409, detail=f"El destinatario esta en bajas: {suppressed['reason'] or 'manual'}")

    try:
        if OUTREACH_AVAILABLE:
            settings = outreach_smtp_settings()
            msg = outreach_build_message(recipient, subject, text_body or " ", final_html, settings)
            _send_email_object(msg)
            message_id = msg["Message-ID"] or ""
        else:
            _send_email_message(recipient, subject, text_body or " ", final_html)
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo enviar email manual de captacion a %s: %s", recipient, exc)
        raise HTTPException(status_code=502, detail=f"No se pudo enviar el email: {exc}") from exc

    recorded = False
    if OUTREACH_AVAILABLE:
        with _outreach_db() as conn:
            conn.execute(
                """INSERT INTO sends (email, stage, subject, body_text, body_html, sent_at, mode, message_id)
                   VALUES (?, 'manual', ?, ?, ?, ?, 'send', ?)""",
                (recipient, subject, text_body, final_html, now, message_id),
            )
            prospect = conn.execute("SELECT email FROM prospects WHERE email=?", (recipient,)).fetchone()
            if prospect:
                conn.execute(
                    "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?, 'manual_email', 'manual', ?, ?, '', '')",
                    (recipient, subject[:500], now),
                )
                conn.execute(
                    "UPDATE prospects SET status=CASE WHEN status='new' THEN 'contacted' ELSE status END, updated_at=? WHERE email=?",
                    (now, recipient),
                )
                recorded = True
            conn.commit()

    return {"ok": True, "message_id": message_id, "recorded": recorded, "sent_at": now}


@app.post("/admin/outreach/send", dependencies=[Depends(_require_admin_token)])
def outreach_send(payload: OutreachSendRequest):
    if payload.stage not in OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    test_to_clean = "" if payload.dry_run else (payload.test_to or "")
    selected_emails = [str(email).lower().strip() for email in payload.emails if str(email).strip()]
    params = {
        "stage": payload.stage,
        "max": payload.max,
        "send": (not payload.dry_run) and not test_to_clean,
        "test_to": test_to_clean,
        "email": payload.email or "",
        "emails": selected_emails,
        "campaign_name": payload.campaign_name,
        "campaign_id": 0,
        "after_days": payload.after_days,
        "delay": payload.delay,
        "jitter": payload.jitter,
        "force_window": payload.force_window,
        "dry_run": bool(payload.dry_run),
        "autopilot": bool(payload.autopilot),
    }
    with _outreach_db() as conn:
        campaign_id = 0
        if params["send"] and selected_emails and payload.stage == "cold":
            campaign_id = _outreach_create_campaign(
                conn,
                name=payload.campaign_name or f"Campana {payload.stage} {_outreach_now()[:10]}",
                stage=payload.stage,
                emails=selected_emails,
                settings=outreach_smtp_settings(),
                delay=payload.delay,
                jitter=payload.jitter,
                force_window=payload.force_window,
                status="running",
            )
            params["campaign_id"] = campaign_id
        cur = conn.execute(
            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
            ("send", "queued", json.dumps(params), "", _outreach_now()),
        )
        job_id = cur.lastrowid
        if campaign_id:
            conn.execute("UPDATE campaigns SET job_id=?, updated_at=? WHERE id=?", (job_id, _outreach_now(), campaign_id))
        conn.commit()

    threading.Thread(target=_outreach_run_send_job, args=(job_id, params), daemon=True).start()
    return {"ok": True, "job_id": job_id, "campaign_id": params.get("campaign_id") or 0}


@app.get("/admin/outreach/jobs", dependencies=[Depends(_require_admin_token)])
def outreach_list_jobs(limit: int = 30):
    limit = max(1, min(200, int(limit)))
    with _outreach_db() as conn:
        rows = conn.execute(
            "SELECT id, kind, status, params_json, started_at, finished_at FROM jobs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.get("/admin/outreach/jobs/{job_id}", dependencies=[Depends(_require_admin_token)])
def outreach_job_detail(job_id: int):
    with _outreach_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return dict(row)


# ----- Discovery -----











@app.post("/admin/outreach/discover", dependencies=[Depends(_require_admin_token)])
def outreach_discover_endpoint(payload: OutreachDiscoverRequest):
    if not OUTREACH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Outreach no disponible.")
    if payload.source == "places" and not os.getenv("GOOGLE_PLACES_API_KEY", "").strip():
        raise HTTPException(status_code=400, detail="Falta GOOGLE_PLACES_API_KEY en .env para source=places.")
    params = payload.model_dump()
    with _outreach_db() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
            ("discover", "queued", json.dumps(params), "", _outreach_now()),
        )
        job_id = cur.lastrowid
        conn.commit()
    threading.Thread(target=_outreach_run_discovery_job, args=(job_id, params), daemon=True).start()
    return {"ok": True, "job_id": job_id}


# ----- Public tracking endpoints (sin auth) -----

@app.get("/track/open/{token}.gif", include_in_schema=False)
def outreach_track_open(token: str, request: Request):
    if not OUTREACH_AVAILABLE or not OUTREACH_TRACKING_SECRET:
        return Response(content=OUTREACH_PIXEL_GIF, media_type="image/gif")
    parsed = outreach_verify_token(token, OUTREACH_TRACKING_SECRET)
    if parsed:
        email, stage = parsed
        try:
            with _outreach_db() as conn:
                conn.execute(
                    "INSERT INTO events (email, type, stage, ts, ua, ip) VALUES (?,?,?,?,?,?)",
                    (email, "open", stage, _outreach_now(),
                     request.headers.get("user-agent", "")[:300],
                     (request.client.host if request.client else "")[:64]),
                )
                conn.commit()
        except Exception:
            logger.exception("Outreach open track error")
    return Response(
        content=OUTREACH_PIXEL_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/track/click/{token}", include_in_schema=False)
def outreach_track_click(token: str, request: Request, u: str = ""):
    if not OUTREACH_AVAILABLE or not OUTREACH_TRACKING_SECRET:
        if u:
            return RedirectResponse(url=u, status_code=302)
        raise HTTPException(status_code=404, detail="not found")
    parsed = outreach_verify_token(token, OUTREACH_TRACKING_SECRET)
    if not parsed or not u:
        raise HTTPException(status_code=404, detail="not found")
    target = u
    try:
        host = urlparse(target).hostname or ""
    except Exception:
        host = ""
    if host and host.lower() not in OUTREACH_TRACKING_ALLOWED_HOSTS:
        # Permitir solo dominios propios para evitar open redirect.
        target = "https://www.vantelia.es"
    email, stage = parsed
    try:
        with _outreach_db() as conn:
            conn.execute(
                "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,?,?)",
                (email, "click", stage, target[:500], _outreach_now(),
                 request.headers.get("user-agent", "")[:300],
                 (request.client.host if request.client else "")[:64]),
            )
            conn.commit()
    except Exception:
        logger.exception("Outreach click track error")
    return RedirectResponse(url=target, status_code=302)


@app.get("/track/reply/{token}", include_in_schema=False)
def outreach_track_reply_intent(token: str, request: Request, u: str = ""):
    if not u.lower().startswith("mailto:"):
        raise HTTPException(status_code=404, detail="not found")
    if not OUTREACH_AVAILABLE or not OUTREACH_TRACKING_SECRET:
        return RedirectResponse(url=u, status_code=302)
    parsed = outreach_verify_token(token, OUTREACH_TRACKING_SECRET)
    if not parsed:
        raise HTTPException(status_code=404, detail="not found")
    email, stage = parsed
    try:
        with _outreach_db() as conn:
            conn.execute(
                "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,?,?)",
                (email, "reply_intent", stage, u[:500], _outreach_now(),
                 request.headers.get("user-agent", "")[:300],
                 (request.client.host if request.client else "")[:64]),
            )
            conn.execute(
                """UPDATE prospects SET status='engaged', updated_at=?
                   WHERE email=? AND status IN ('new','contacted')""",
                (_outreach_now(), email),
            )
            conn.commit()
    except Exception:
        logger.exception("Outreach reply intent track error")
    return RedirectResponse(url=u, status_code=302)


class OutreachReplyPayload(BaseModel):
    email: EmailStr
    stage: str = ""
    note: str = ""


@app.post("/admin/outreach/replies", dependencies=[Depends(_require_admin_token)])
def outreach_record_reply(payload: OutreachReplyPayload):
    email = str(payload.email).lower().strip()
    with _outreach_db() as conn:
        conn.execute(
            "INSERT INTO events (email, type, stage, ts) VALUES (?,?,?,?)",
            (email, "reply", payload.stage, _outreach_now()),
        )
        conn.execute(
            "UPDATE prospects SET status='replied', updated_at=? WHERE email=?",
            (_outreach_now(), email),
        )
        conn.commit()
    return {"ok": True}


# === END OUTREACH ====================================================


# =====================================================================
# === INSTAGRAM =======================================================
# Captacion via Instagram DMs. Modo hibrido compliant por defecto:
# discovery + drafts + envio manual 1-clic via ig.me deep link.
# Autosend automatizado opt-in via IG_AUTOSEND_ENABLED (riesgo ban Meta).
# =====================================================================















# ----- Pydantic -----


class InstagramProspectIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    full_name: str = ""
    bio: str = ""
    business_category: str = ""
    niche: str = ""
    city: str = ""
    followers_count: int = 0
    following_count: int = 0
    posts_count: int = 0
    website: str = ""
    public_email: str = ""
    public_phone: str = ""
    profile_url: str = ""
    avatar_url: str = ""
    is_business_account: int = 0
    is_verified: int = 0
    score: int = 0
    status: str = "new"
    notes: str = ""
    tags: str = ""
    source: str = "manual"
    service_hint: str = ""


class InstagramProspectPatch(BaseModel):
    full_name: Optional[str] = None
    bio: Optional[str] = None
    business_category: Optional[str] = None
    niche: Optional[str] = None
    city: Optional[str] = None
    followers_count: Optional[int] = None
    following_count: Optional[int] = None
    posts_count: Optional[int] = None
    website: Optional[str] = None
    public_email: Optional[str] = None
    public_phone: Optional[str] = None
    is_business_account: Optional[int] = None
    is_verified: Optional[int] = None
    score: Optional[int] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[str] = None
    source: Optional[str] = None
    service_hint: Optional[str] = None


class InstagramDiscoverRequest(BaseModel):
    usernames: List[str] = Field(default_factory=list)
    niche: str = ""
    city: str = ""
    source: str = "discover"
    min_followers: int = 0
    max_followers: int = 0
    has_website: bool = False
    is_business: bool = False
    use_graph: bool = True


class InstagramDraftRequest(BaseModel):
    stage: str = "cold"
    max: int = 20
    after_days: int = 5


class InstagramSendRequest(BaseModel):
    stage: str = "cold"
    max: int = 10
    dry_run: bool = True


class InstagramSessionCookies(BaseModel):
    sessionid: str = Field(..., min_length=10)
    csrftoken: str = Field(..., min_length=10)
    ds_user_id: str = Field(..., min_length=1)
    mid: str = ""
    rur: str = ""


class InstagramSuppressRequest(BaseModel):
    username: str = Field(..., min_length=1)
    reason: str = "manual"


class InstagramTemplateOverride(BaseModel):
    stage: str
    opener: str = ""
    body: str = ""


class InstagramAutopilotPayload(BaseModel):
    enabled: Optional[bool] = None
    targets: Optional[List[Dict[str, Any]]] = None
    daily_new_target: Optional[int] = None
    daily_outreach_cap: Optional[int] = None
    auto_followups: Optional[bool] = None


class InstagramReplyPayload(BaseModel):
    username: str
    stage: str = ""
    note: str = ""


class InstagramManualContactPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    full_name: str = ""
    message_text: str = Field(..., min_length=1, max_length=2000)
    stage: str = ""
    contacted_at: str = ""
    notes: str = ""
    profile_url: str = ""
    city: str = ""
    niche: str = ""


# ----- Helpers de row -> dict -----


















# ----- Stats -----


@app.get("/admin/instagram/stats", dependencies=[Depends(_require_admin_token)])
def instagram_stats():
    with _instagram_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM ig_prospects").fetchone()["c"]
        suppressed = conn.execute("SELECT COUNT(*) AS c FROM ig_suppressions").fetchone()["c"]
        replied = conn.execute(
            "SELECT COUNT(DISTINCT username) AS c FROM ig_events WHERE type='reply'"
        ).fetchone()["c"]
        clients = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_prospects WHERE status='client'"
        ).fetchone()["c"]
        drafts_pending = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode='draft' AND ready=1"
        ).fetchone()["c"]
        sent_total = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto')"
        ).fetchone()["c"]
        sent_distinct = conn.execute(
            "SELECT COUNT(DISTINCT username) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto')"
        ).fetchone()["c"]
        today = _utc_now().date().isoformat()
        sent_today = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto') AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]
        per_stage_rows = conn.execute(
            "SELECT stage, COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto') GROUP BY stage"
        ).fetchall()
        per_stage = {row["stage"]: int(row["c"]) for row in per_stage_rows}
        funnel = {stage: per_stage.get(stage, 0) for stage in IG_STAGES}

    reply_rate = (replied / sent_distinct * 100) if sent_distinct else 0.0
    return {
        "totals": {
            "prospects": total,
            "suppressed": suppressed,
            "drafts_pending": drafts_pending,
            "sent_total": sent_total,
            "sent_distinct": sent_distinct,
            "sent_today": sent_today,
            "replies_unique": replied,
            "clients": clients,
        },
        "funnel": funnel,
        "reply_rate": round(reply_rate, 2),
        "autosend_enabled": bool(IG_AVAILABLE and ig_is_autosend_enabled()),
        "in_window": _ig_in_window(),
    }


# ----- Prospects CRUD -----


@app.get("/admin/instagram/prospects", dependencies=[Depends(_require_admin_token)])
def instagram_list_prospects(
    q: str = "",
    status: str = "",
    niche: str = "",
    city: str = "",
    source: str = "",
    page: int = 1,
    page_size: int = 50,
):
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    where = []
    params: List[Any] = []
    if q:
        where.append("(username LIKE ? OR full_name LIKE ? OR bio LIKE ?)")
        like = f"%{q.strip()}%"
        params.extend([like, like, like])
    if status:
        where.append("status=?"); params.append(status)
    if niche:
        where.append("niche LIKE ?"); params.append(f"%{niche}%")
    if city:
        where.append("city LIKE ?"); params.append(f"%{city}%")
    if source:
        where.append("source LIKE ?"); params.append(f"%{source}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    with _instagram_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM ig_prospects {where_sql}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"""SELECT * FROM ig_prospects {where_sql}
                ORDER BY score DESC, updated_at DESC
                LIMIT ? OFFSET ?""",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_ig_row_dict(r) for r in rows],
    }


@app.get("/admin/instagram/prospects/{username}", dependencies=[Depends(_require_admin_token)])
def instagram_get_prospect(username: str):
    user = _ig_resolve_username(username)
    with _instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_prospects WHERE username=?", (user,)).fetchone()
        if not row:
            raise HTTPException(404, "Prospect no encontrado")
        sends = conn.execute(
            "SELECT * FROM ig_sends WHERE username=? ORDER BY drafted_at DESC LIMIT 50",
            (user,),
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM ig_events WHERE username=? ORDER BY ts DESC LIMIT 50",
            (user,),
        ).fetchall()
    return {
        "prospect": _ig_row_dict(row),
        "sends": [_ig_row_dict(s) for s in sends],
        "events": [_ig_row_dict(e) for e in events],
    }




@app.post("/admin/instagram/manual-contact", dependencies=[Depends(_require_admin_token)])
def instagram_manual_contact(payload: InstagramManualContactPayload):
    user = _ig_resolve_username(payload.username)
    if not user:
        raise HTTPException(400, "username invalido")
    now = _ig_parse_ts(payload.contacted_at)
    stage = _ig_normalize_manual_stage(payload.stage)
    with _instagram_db() as conn:
        existing = conn.execute("SELECT * FROM ig_prospects WHERE username=?", (user,)).fetchone()
        if not stage:
            stage = _ig_stage_from_history(conn, user) if existing else "cold"
        if stage not in set(IG_STAGES) | {"reply", "interested", "lost", "client", "demo"}:
            raise HTTPException(400, "stage invalido")
        if not existing:
            conn.execute(
                """INSERT INTO ig_prospects
                     (username, full_name, niche, city, profile_url, status, notes, source,
                      created_at, updated_at, last_contacted_at, next_followup_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user,
                    payload.full_name.strip(),
                    payload.niche.strip(),
                    payload.city.strip(),
                    payload.profile_url.strip() or f"https://www.instagram.com/{user}/",
                    "new",
                    payload.notes.strip(),
                    "manual",
                    now,
                    now,
                    "",
                    "",
                ),
            )
        else:
            conn.execute(
                """UPDATE ig_prospects
                   SET full_name=CASE WHEN COALESCE(full_name,'')='' THEN ? ELSE full_name END,
                       niche=CASE WHEN COALESCE(niche,'')='' THEN ? ELSE niche END,
                       city=CASE WHEN COALESCE(city,'')='' THEN ? ELSE city END,
                       profile_url=CASE WHEN COALESCE(profile_url,'')='' THEN ? ELSE profile_url END,
                       notes=CASE WHEN ?<>'' THEN TRIM(COALESCE(notes,'') || CASE WHEN COALESCE(notes,'')='' THEN '' ELSE char(10) END || ?) ELSE notes END,
                       updated_at=?
                   WHERE username=?""",
                (
                    payload.full_name.strip(),
                    payload.niche.strip(),
                    payload.city.strip(),
                    payload.profile_url.strip() or f"https://www.instagram.com/{user}/",
                    payload.notes.strip(),
                    payload.notes.strip(),
                    now,
                    user,
                ),
            )

        event_data = {"message_text": payload.message_text.strip(), "notes": payload.notes.strip(), "manual": True}
        next_info = {"next_stage": "", "next_followup_at": ""}
        if stage in IG_STAGES:
            conn.execute(
                """INSERT INTO ig_sends (username, stage, variant, message_text, mode, ready, sent_at, drafted_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (user, stage, "manual", payload.message_text.strip(), "sent", 0, now, now),
            )
            conn.execute(
                "INSERT INTO ig_events (username, type, stage, data_json, ts) VALUES (?,?,?,?,?)",
                (user, "sent", stage, json.dumps(event_data, ensure_ascii=False), now),
            )
            next_info = _ig_next_followup(stage, now)
            conn.execute(
                """UPDATE ig_prospects
                   SET status=CASE WHEN status IN ('replied','client','lost','dnc') THEN status ELSE 'contacted' END,
                       last_contacted_at=?, next_followup_at=?, updated_at=?
                   WHERE username=?""",
                (now, next_info["next_followup_at"], now, user),
            )
        else:
            event_type = {"reply": "reply", "interested": "interest", "lost": "lost", "client": "client", "demo": "demo"}.get(stage, "note")
            status = {"reply": "replied", "interested": "replied", "lost": "lost", "client": "client", "demo": "replied"}.get(stage, "contacted")
            conn.execute(
                "INSERT INTO ig_events (username, type, stage, data_json, ts) VALUES (?,?,?,?,?)",
                (user, event_type, stage, json.dumps(event_data, ensure_ascii=False), now),
            )
            conn.execute(
                "UPDATE ig_prospects SET status=?, next_followup_at='', updated_at=? WHERE username=?",
                (status, now, user),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM ig_prospects WHERE username=?", (user,)).fetchone()
    return {
        "ok": True,
        "username": user,
        "stage": stage,
        "next_stage": next_info["next_stage"],
        "next_followup_at": next_info["next_followup_at"],
        "prospect": _ig_row_dict(row) if row else None,
    }


@app.get("/admin/instagram/followup-queue", dependencies=[Depends(_require_admin_token)])
def instagram_followup_queue(limit: int = 50, include_upcoming: bool = False):
    with _instagram_db() as conn:
        return {"items": _ig_followup_queue_items(conn, limit, include_upcoming)}


@app.get("/admin/instagram/prospects/{username}/timeline", dependencies=[Depends(_require_admin_token)])
def instagram_prospect_timeline(username: str):
    user = _ig_resolve_username(username)
    with _instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_prospects WHERE username=?", (user,)).fetchone()
        if not row:
            raise HTTPException(404, "Prospect no encontrado")
        sends = [_ig_row_dict(r) for r in conn.execute(
            "SELECT id, username, 'send' AS kind, stage, mode AS type, message_text AS text, sent_at AS ts, drafted_at FROM ig_sends WHERE username=?",
            (user,),
        ).fetchall()]
        events = [_ig_row_dict(r) for r in conn.execute(
            "SELECT id, username, 'event' AS kind, stage, type, data_json AS text, ts, '' AS drafted_at FROM ig_events WHERE username=?",
            (user,),
        ).fetchall()]
    items = sorted(sends + events, key=lambda x: x.get("ts") or x.get("drafted_at") or "", reverse=True)
    return {"prospect": _ig_row_dict(row), "items": items}


@app.get("/admin/instagram/ops-summary", dependencies=[Depends(_require_admin_token)])
def instagram_ops_summary():
    today = _utc_now().date().isoformat()
    week_cutoff = (_utc_now() - timedelta(days=7)).isoformat(timespec="seconds")
    with _instagram_db() as conn:
        sent_today = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto') AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]
        sent_week = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto') AND sent_at>=?",
            (week_cutoff,),
        ).fetchone()["c"]
        replies = conn.execute(
            "SELECT COUNT(DISTINCT username) AS c FROM ig_events WHERE type IN ('reply','interest','demo')"
        ).fetchone()["c"]
        interested = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_prospects WHERE status IN ('replied','client')"
        ).fetchone()["c"]
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM ig_prospects GROUP BY status"
        ).fetchall()
        recent_rows = conn.execute(
            """SELECT username, type, stage, data_json, ts
               FROM ig_events
               ORDER BY ts DESC, id DESC
               LIMIT 12"""
        ).fetchall()
        queue_due = _ig_followup_queue_items(conn, 20, False)
        queue_all = _ig_followup_queue_items(conn, 20, True)
    response_rate = round((replies / sent_week * 100), 2) if sent_week else 0.0
    return {
        "totals": {
            "sent_today": sent_today,
            "sent_week": sent_week,
            "replies": replies,
            "interested": interested,
            "followups_due": len(queue_due),
            "followups_upcoming": max(0, len(queue_all) - len(queue_due)),
            "response_rate": response_rate,
        },
        "status_counts": {r["status"] or "new": int(r["c"]) for r in status_rows},
        "followups_due": queue_due[:8],
        "recent_activity": [_ig_row_dict(r) for r in recent_rows],
    }


@app.post("/admin/instagram/prospects", dependencies=[Depends(_require_admin_token)])
def instagram_create_prospect(payload: InstagramProspectIn):
    user = _ig_resolve_username(payload.username)
    if not user:
        raise HTTPException(400, "username invalido")
    data = payload.model_dump()
    data["username"] = user
    data["now"] = _instagram_now()
    with _instagram_db() as conn:
        exists = conn.execute("SELECT 1 FROM ig_prospects WHERE username=?", (user,)).fetchone()
        if exists:
            raise HTTPException(409, "Prospect ya existe")
        conn.execute(
            """INSERT INTO ig_prospects
                 (username, full_name, bio, business_category, niche, city,
                  followers_count, following_count, posts_count, website,
                  public_email, public_phone, profile_url, avatar_url,
                  is_business_account, is_verified, score, status,
                  notes, tags, source, service_hint, created_at, updated_at)
               VALUES
                 (:username, :full_name, :bio, :business_category, :niche, :city,
                  :followers_count, :following_count, :posts_count, :website,
                  :public_email, :public_phone, :profile_url, :avatar_url,
                  :is_business_account, :is_verified, :score, :status,
                  :notes, :tags, :source, :service_hint, :now, :now)""",
            data,
        )
        conn.commit()
    return {"ok": True, "username": user}


@app.patch("/admin/instagram/prospects/{username}", dependencies=[Depends(_require_admin_token)])
def instagram_patch_prospect(username: str, payload: InstagramProspectPatch):
    user = _ig_resolve_username(username)
    fields = []
    params: List[Any] = []
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "Sin cambios")
    for key, value in data.items():
        fields.append(f"{key}=?")
        params.append(value)
    fields.append("updated_at=?"); params.append(_instagram_now())
    params.append(user)
    with _instagram_db() as conn:
        cur = conn.execute(
            f"UPDATE ig_prospects SET {', '.join(fields)} WHERE username=?",
            params,
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Prospect no encontrado")
        conn.commit()
    return {"ok": True, "username": user}


@app.delete("/admin/instagram/prospects/{username}", dependencies=[Depends(_require_admin_token)])
def instagram_delete_prospect(username: str):
    user = _ig_resolve_username(username)
    with _instagram_db() as conn:
        cur = conn.execute("DELETE FROM ig_prospects WHERE username=?", (user,))
        conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


# ----- Import / Export -----


@app.post("/admin/instagram/import", dependencies=[Depends(_require_admin_token)])
async def instagram_import_csv(request: Request):
    raw = (await request.body()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(StringIO(raw))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV vacio o sin cabecera")
    added = updated = skipped = 0
    with _instagram_db() as conn:
        for row in reader:
            user = _ig_resolve_username(row.get("username", ""))
            if not user:
                skipped += 1
                continue
            profile = IGProfile(
                username=user,
                full_name=(row.get("full_name") or "").strip(),
                bio=(row.get("bio") or "").strip(),
                business_category=(row.get("business_category") or "").strip(),
                niche=(row.get("niche") or "").strip(),
                city=(row.get("city") or "").strip(),
                followers_count=int(row.get("followers_count") or 0),
                following_count=int(row.get("following_count") or 0),
                posts_count=int(row.get("posts_count") or 0),
                website=(row.get("website") or "").strip(),
                public_email=(row.get("public_email") or "").strip(),
                public_phone=(row.get("public_phone") or "").strip(),
                profile_url=(row.get("profile_url") or "").strip(),
                avatar_url=(row.get("avatar_url") or "").strip(),
                is_business_account=int(row.get("is_business_account") or 0),
                is_verified=int(row.get("is_verified") or 0),
                tags=(row.get("tags") or "").strip(),
                source=(row.get("source") or "csv").strip(),
            )
            a, u = ig_upsert_profile(conn, profile)
            if a:
                added += 1
            elif u:
                updated += 1
            else:
                skipped += 1
        conn.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


@app.get("/admin/instagram/export.csv", dependencies=[Depends(_require_admin_token)])
def instagram_export_csv():
    with _instagram_db() as conn:
        rows = conn.execute("SELECT * FROM ig_prospects ORDER BY created_at DESC").fetchall()
    buf = StringIO()
    if rows:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(_ig_row_dict(r))
    return Response(content=buf.getvalue(), media_type="text/csv")


# ----- Discovery -----


@app.post("/admin/instagram/discover", dependencies=[Depends(_require_admin_token)])
def instagram_discover(payload: InstagramDiscoverRequest, background_tasks: BackgroundTasks):
    if not IG_AVAILABLE:
        raise HTTPException(503, "Modulo IG no disponible")
    if not payload.usernames:
        raise HTTPException(400, "usernames requerido")
    params_json = json.dumps(payload.model_dump(), ensure_ascii=False)
    with _instagram_db() as conn:
        cur = conn.execute(
            "INSERT INTO ig_jobs (kind, status, params_json, started_at) VALUES (?,?,?,?)",
            ("discover", "queued", params_json, _instagram_now()),
        )
        job_id = cur.lastrowid
        conn.commit()

    def _run() -> None:
        try:
            with _instagram_db() as conn2:
                conn2.execute("UPDATE ig_jobs SET status='running' WHERE id=?", (job_id,))
                conn2.commit()
            profiles = ig_discover_usernames(
                payload.usernames,
                niche=payload.niche,
                city=payload.city,
                source_label=payload.source or "discover",
                use_graph=payload.use_graph,
                min_followers=payload.min_followers,
                max_followers=payload.max_followers,
                has_website=payload.has_website,
                is_business=payload.is_business,
            )
            added = updated = 0
            with _instagram_db() as conn2:
                for p in profiles:
                    a, u = ig_upsert_profile(conn2, p)
                    if a:
                        added += 1
                    elif u:
                        updated += 1
                conn2.execute(
                    "UPDATE ig_jobs SET status='done', log=?, finished_at=? WHERE id=?",
                    (
                        json.dumps({"profiles": len(profiles), "added": added, "updated": updated}),
                        _instagram_now(),
                        job_id,
                    ),
                )
                conn2.commit()
        except Exception as exc:  # noqa: BLE001
            try:
                with _instagram_db() as conn2:
                    conn2.execute(
                        "UPDATE ig_jobs SET status='error', log=?, finished_at=? WHERE id=?",
                        (f"error: {exc}", _instagram_now(), job_id),
                    )
                    conn2.commit()
            except Exception:
                pass

    background_tasks.add_task(_run)
    return {"ok": True, "job_id": job_id}


@app.get("/admin/instagram/jobs", dependencies=[Depends(_require_admin_token)])
def instagram_jobs(limit: int = 50):
    with _instagram_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ig_jobs ORDER BY id DESC LIMIT ?",
            (max(1, min(200, limit)),),
        ).fetchall()
    return {"items": [_ig_row_dict(r) for r in rows]}


@app.get("/admin/instagram/jobs/{job_id}", dependencies=[Depends(_require_admin_token)])
def instagram_job(job_id: int):
    with _instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Job no encontrado")
    return _ig_row_dict(row)


# ----- Drafts -----


@app.post("/admin/instagram/draft", dependencies=[Depends(_require_admin_token)])
def instagram_generate_drafts(payload: InstagramDraftRequest):
    if payload.stage not in IG_STAGES:
        raise HTTPException(400, "stage invalido")
    created: List[Dict[str, Any]] = []
    with _instagram_db() as conn:
        rows = ig_fetch_candidates(conn, payload.stage, max(1, payload.max), max(1, payload.after_days))
        for r in rows:
            draft = ig_create_draft(conn, r, payload.stage)
            created.append(draft)
        conn.commit()
    return {"created": len(created), "drafts": created}


@app.get("/admin/instagram/drafts", dependencies=[Depends(_require_admin_token)])
def instagram_drafts_queue(stage: str = "", niche: str = "", city: str = "", limit: int = 100):
    # Single-touch: con follow-ups desactivados, descarta cualquier draft no-cold
    # que quedara en cola (de versiones anteriores) para que no se envie ni se vea.
    if not _ig_env_bool("IG_AUTONOMOUS_FOLLOWUPS", False):
        with _instagram_db() as conn:
            conn.execute(
                "UPDATE ig_sends SET mode='skipped', ready=0, skip_reason='followups_off' "
                "WHERE mode='draft' AND ready=1 AND stage<>'cold'"
            )
            conn.commit()
    where = ["s.mode='draft'", "s.ready=1"]
    params: List[Any] = []
    if stage:
        where.append("s.stage=?"); params.append(stage)
    if niche:
        where.append("p.niche LIKE ?"); params.append(f"%{niche}%")
    if city:
        where.append("p.city LIKE ?"); params.append(f"%{city}%")
    where_sql = " AND ".join(where)
    params.append(max(1, min(500, limit)))
    with _instagram_db() as conn:
        rows = conn.execute(
            f"""SELECT s.id AS send_id, s.username, s.stage, s.variant, s.message_text,
                       s.drafted_at, p.full_name, p.bio, p.niche, p.city,
                       p.followers_count, p.avatar_url, p.score, p.business_category
                FROM ig_sends s
                LEFT JOIN ig_prospects p ON p.username=s.username
                WHERE {where_sql}
                ORDER BY p.score DESC, s.id ASC
                LIMIT ?""",
            params,
        ).fetchall()
    items: List[Dict[str, Any]] = []
    for r in rows:
        d = _ig_row_dict(r)
        d["deep_link"] = ig_deep_link(r["username"], r["message_text"])
        items.append(d)
    return {"items": items, "count": len(items)}


class InstagramDraftEditPayload(BaseModel):
    message_text: str = Field(..., min_length=1, max_length=1000)


@app.patch("/admin/instagram/drafts/{send_id}", dependencies=[Depends(_require_admin_token)])
def instagram_edit_draft(send_id: int, payload: InstagramDraftEditPayload):
    with _instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_sends WHERE id=? AND mode='draft'", (send_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Draft no encontrado")
        conn.execute(
            "UPDATE ig_sends SET message_text=? WHERE id=?",
            (payload.message_text.strip(), send_id),
        )
        conn.commit()
    return {"ok": True, "deep_link": ig_deep_link(row["username"], payload.message_text.strip())}


@app.post("/admin/instagram/drafts/{send_id}/mark-sent", dependencies=[Depends(_require_admin_token)])
def instagram_mark_draft_sent(send_id: int):
    with _instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_sends WHERE id=?", (send_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Draft no encontrado")
        if row["mode"] not in ("draft", "preview"):
            raise HTTPException(409, "El draft ya fue marcado como enviado")
        now = _instagram_now()
        conn.execute(
            "UPDATE ig_sends SET mode='sent', ready=0, sent_at=? WHERE id=?",
            (now, send_id),
        )
        conn.execute(
            "INSERT INTO ig_events (username, type, stage, ts) VALUES (?,?,?,?)",
            (row["username"], "sent", row["stage"], now),
        )
        next_info = _ig_next_followup(row["stage"], now)
        conn.execute(
            """UPDATE ig_prospects
               SET status=CASE WHEN status IN ('replied','client','lost','dnc') THEN status ELSE 'contacted' END,
                   last_contacted_at=?, next_followup_at=?, updated_at=?
               WHERE username=?""",
            (now, next_info["next_followup_at"], now, row["username"]),
        )
        conn.commit()
    return {"ok": True}


@app.post("/admin/instagram/drafts/{send_id}/skip", dependencies=[Depends(_require_admin_token)])
def instagram_skip_draft(send_id: int, reason: str = "skip"):
    with _instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_sends WHERE id=?", (send_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Draft no encontrado")
        conn.execute(
            "UPDATE ig_sends SET mode='skipped', ready=0, skip_reason=? WHERE id=?",
            (reason[:120], send_id),
        )
        conn.commit()
    return {"ok": True}


# ----- Autosend opt-in -----


@app.post("/admin/instagram/send", dependencies=[Depends(_require_admin_token)])
def instagram_autosend(payload: InstagramSendRequest, background_tasks: BackgroundTasks):
    if not ig_is_autosend_enabled():
        raise HTTPException(412, "IG_AUTOSEND_ENABLED=false. Usa /draft + envio manual.")
    try:
        from instagram_autosend import autosend_drafts  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/instagram_autosend.py no disponible. Instala playwright.")
    if payload.stage not in IG_STAGES:
        raise HTTPException(400, "stage invalido")
    with _instagram_db() as conn:
        rows = ig_fetch_candidates(conn, payload.stage, max(1, payload.max), 5)
        drafts = [ig_create_draft(conn, r, payload.stage) for r in rows]
        conn.commit()

    def _run() -> None:
        try:
            autosend_drafts(drafts, dry_run=payload.dry_run)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"IG autosend error: {exc}")

    background_tasks.add_task(_run)
    return {"ok": True, "queued": len(drafts), "dry_run": payload.dry_run}


# ----- Sesion Instagram (cookies pegadas desde navegador) -----


@app.get("/admin/instagram/autosend/status", dependencies=[Depends(_require_admin_token)])
def instagram_autosend_status():
    try:
        from instagram_autosend import session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/instagram_autosend.py no disponible.")
    return {
        "autosend_enabled": ig_is_autosend_enabled(),
        "autonomous_autosend": _ig_env_bool("IG_AUTONOMOUS_AUTOSEND", False),
        "session": session_info(),
    }


@app.post("/admin/instagram/autosend/connect", dependencies=[Depends(_require_admin_token)])
def instagram_autosend_connect(payload: InstagramSessionCookies):
    try:
        from instagram_autosend import save_session_from_cookies, session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/instagram_autosend.py no disponible.")
    try:
        path = save_session_from_cookies(
            sessionid=payload.sessionid,
            csrftoken=payload.csrftoken,
            ds_user_id=payload.ds_user_id,
            mid=payload.mid,
            rur=payload.rur,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "saved_at": str(path), "session": session_info()}


@app.post("/admin/instagram/autosend/disconnect", dependencies=[Depends(_require_admin_token)])
def instagram_autosend_disconnect():
    try:
        from instagram_autosend import clear_session  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/instagram_autosend.py no disponible.")
    removed = clear_session()
    return {"ok": True, "removed": removed}


@app.post("/admin/instagram/autosend/test", dependencies=[Depends(_require_admin_token)])
def instagram_autosend_test():
    """Comprueba si la sesion guardada sigue valida pidiendo /accounts/edit/ a IG."""
    try:
        from instagram_autosend import session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/instagram_autosend.py no disponible.")
    info = session_info()
    if not info.get("connected"):
        return {"ok": False, "reason": "sin_sesion"}
    sessionid = ""
    csrftoken = ""
    ds_user_id = info.get("ds_user_id") or ""
    try:
        state_path = Path(info.get("path") or "")
        if state_path.exists():
            data = json.loads(state_path.read_text(encoding="utf-8"))
            for c in data.get("cookies", []):
                if c.get("name") == "sessionid":
                    sessionid = c.get("value") or ""
                elif c.get("name") == "csrftoken":
                    csrftoken = c.get("value") or ""
    except Exception as exc:
        raise HTTPException(500, f"No se pudo leer sesion: {exc}")
    if not sessionid:
        return {"ok": False, "reason": "sin_sessionid"}
    cookies = {"sessionid": sessionid, "csrftoken": csrftoken, "ds_user_id": ds_user_id}
    headers = {
        "User-Agent": os.getenv("IG_AUTOSEND_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept-Language": "es-ES,es;q=0.9",
        "X-IG-App-ID": "936619743392459",
    }
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            r = client.get("https://www.instagram.com/api/v1/accounts/edit/web_form_data/",
                           cookies=cookies, headers=headers)
        ok = r.status_code == 200 and "username" in (r.text or "")
        return {"ok": ok, "status_code": r.status_code,
                "session": info,
                "hint": "Cookies validas" if ok else "Cookies caducadas o cuenta bloqueada. Reconecta."}
    except Exception as exc:
        return {"ok": False, "reason": f"http_error: {exc}", "session": info}


# ----- Suppressions -----


@app.post("/admin/instagram/suppress", dependencies=[Depends(_require_admin_token)])
def instagram_suppress(payload: InstagramSuppressRequest):
    user = _ig_resolve_username(payload.username)
    if not user:
        raise HTTPException(400, "username invalido")
    with _instagram_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO ig_suppressions (username, reason, added_at) VALUES (?,?,?)",
            (user, payload.reason or "manual", _instagram_now()),
        )
        conn.execute(
            "UPDATE ig_prospects SET status='dnc', updated_at=? WHERE username=?",
            (_instagram_now(), user),
        )
        conn.commit()
    return {"ok": True, "username": user}


@app.delete("/admin/instagram/suppress/{username}", dependencies=[Depends(_require_admin_token)])
def instagram_remove_suppress(username: str):
    user = _ig_resolve_username(username)
    with _instagram_db() as conn:
        conn.execute("DELETE FROM ig_suppressions WHERE username=?", (user,))
        conn.commit()
    return {"ok": True}


@app.get("/admin/instagram/suppressions", dependencies=[Depends(_require_admin_token)])
def instagram_list_suppressions(limit: int = 200):
    with _instagram_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ig_suppressions ORDER BY added_at DESC LIMIT ?",
            (max(1, min(1000, limit)),),
        ).fetchall()
    return {"items": [_ig_row_dict(r) for r in rows]}


# ----- Templates overrides -----


@app.get("/admin/instagram/templates", dependencies=[Depends(_require_admin_token)])
def instagram_templates():
    with _instagram_db() as conn:
        rows = conn.execute("SELECT * FROM ig_templates_overrides").fetchall()
    return {"overrides": [_ig_row_dict(r) for r in rows], "stages": IG_STAGES}


@app.put("/admin/instagram/templates", dependencies=[Depends(_require_admin_token)])
def instagram_save_template(payload: InstagramTemplateOverride):
    if payload.stage not in IG_STAGES:
        raise HTTPException(400, "stage invalido")
    with _instagram_db() as conn:
        conn.execute(
            """INSERT INTO ig_templates_overrides (stage, opener, body, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(stage) DO UPDATE SET opener=excluded.opener, body=excluded.body, updated_at=excluded.updated_at""",
            (payload.stage, payload.opener, payload.body, _instagram_now()),
        )
        conn.commit()
    return {"ok": True}


# ----- Hot leads + AB stats -----


@app.get("/admin/instagram/hot-leads", dependencies=[Depends(_require_admin_token)])
def instagram_hot_leads(limit: int = 15):
    with _instagram_db() as conn:
        rows = conn.execute(
            """SELECT p.* FROM ig_prospects p
               WHERE p.status IN ('contacted','queued')
               AND EXISTS (SELECT 1 FROM ig_sends s WHERE s.username=p.username AND s.mode IN ('sent','sent_auto'))
               AND NOT EXISTS (SELECT 1 FROM ig_events e WHERE e.username=p.username AND e.type='reply')
               ORDER BY p.score DESC, p.updated_at DESC
               LIMIT ?""",
            (max(1, min(50, limit)),),
        ).fetchall()
    items: List[Dict[str, Any]] = []
    for r in rows:
        d = _ig_row_dict(r)
        d["deep_link"] = ig_deep_link(r["username"], "")
        items.append(d)
    return {"items": items}


@app.get("/admin/instagram/ab-stats", dependencies=[Depends(_require_admin_token)])
def instagram_ab_stats(stage: str = "cold", days: int = 30):
    if stage not in IG_STAGES:
        raise HTTPException(400, "stage invalido")
    cutoff = (_utc_now() - timedelta(days=max(1, days))).isoformat(timespec="seconds")
    with _instagram_db() as conn:
        rows = conn.execute(
            """SELECT variant,
                      COUNT(*) AS sent,
                      SUM(CASE WHEN EXISTS(SELECT 1 FROM ig_events e WHERE e.username=ig_sends.username AND e.type='reply' AND e.ts>=ig_sends.sent_at) THEN 1 ELSE 0 END) AS replies
                FROM ig_sends
                WHERE stage=? AND mode IN ('sent','sent_auto') AND sent_at>=?
                GROUP BY variant""",
            (stage, cutoff),
        ).fetchall()
    out = []
    for r in rows:
        sent = int(r["sent"] or 0)
        replies = int(r["replies"] or 0)
        out.append({
            "variant": r["variant"] or "?",
            "sent": sent,
            "replies": replies,
            "reply_rate": round(replies / sent * 100, 2) if sent else 0.0,
        })
    return {"stage": stage, "days": days, "variants": out}


# ----- Autopilot config -----


@app.get("/admin/instagram/autopilot-config", dependencies=[Depends(_require_admin_token)])
def instagram_autopilot_get():
    with _instagram_db() as conn:
        row = conn.execute("SELECT * FROM ig_autopilot_config WHERE id=1").fetchone()
        if not row:
            return {"config": None}
        cfg = _ig_row_dict(row)
        try:
            cfg["targets"] = json.loads(cfg.get("targets_json") or "[]")
        except Exception:
            cfg["targets"] = []
        # contadores diarios
        today = _utc_now().date().isoformat()
        cfg["sent_today"] = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto') AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]
        cfg["autosent_today"] = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode='sent_auto' AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]
        cfg["drafts_pending"] = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode='draft' AND ready=1"
        ).fetchone()["c"]
    db_cap = int(cfg.get("daily_outreach_cap") or 0)
    env_cap = int(os.getenv("IG_AUTOSEND_DAILY_CAP", "20") or 20)
    cfg["effective_daily_cap"] = db_cap if db_cap > 0 else env_cap
    return {"config": cfg, "autosend_enabled": ig_is_autosend_enabled(),
            "autonomous_enabled": _ig_env_bool("IG_AUTONOMOUS_ENABLED", False),
            "autonomous_autosend": _ig_env_bool("IG_AUTONOMOUS_AUTOSEND", False)}


@app.put("/admin/instagram/autopilot-config", dependencies=[Depends(_require_admin_token)])
def instagram_autopilot_put(payload: InstagramAutopilotPayload):
    fields: List[str] = []
    params: List[Any] = []
    data = payload.model_dump(exclude_unset=True)
    if "enabled" in data:
        fields.append("enabled=?"); params.append(1 if data["enabled"] else 0)
    if "targets" in data:
        fields.append("targets_json=?"); params.append(json.dumps(data["targets"] or [], ensure_ascii=False))
    if "daily_new_target" in data:
        fields.append("daily_new_target=?"); params.append(int(data["daily_new_target"] or 0))
    if "daily_outreach_cap" in data:
        fields.append("daily_outreach_cap=?"); params.append(int(data["daily_outreach_cap"] or 0))
    if "auto_followups" in data:
        fields.append("auto_followups=?"); params.append(1 if data["auto_followups"] else 0)
    if not fields:
        raise HTTPException(400, "Sin cambios")
    fields.append("updated_at=?"); params.append(_instagram_now())
    with _instagram_db() as conn:
        conn.execute(f"UPDATE ig_autopilot_config SET {', '.join(fields)} WHERE id=1", params)
        conn.commit()
    return {"ok": True}




@app.post("/admin/instagram/autopilot-tick", dependencies=[Depends(_require_admin_token)])
def instagram_autopilot_tick():
    stats = _ig_autopilot_run_once()
    return {"ok": True, "stats": stats, "ts": _instagram_now()}


# =====================================================================
# === CAMPAIGN v2: discovery real + DMs naturales + 1 boton Empezar  ==
# =====================================================================

_IG_CAMPAIGN_STATUSES = {"idle", "discovering", "sending", "paused", "completed"}


class InstagramCampaignStart(BaseModel):
    target_count: int = Field(30, ge=1, le=200)






















@app.get("/admin/instagram/campaign", dependencies=[Depends(_require_admin_token)])
def instagram_campaign_get():
    state = _ig_campaign_state()
    try:
        from instagram_autosend import session_info  # type: ignore
        session = session_info()
    except Exception:
        session = {"connected": False}
    return {"campaign": state, "session": session,
            "autosend_enabled": ig_is_autosend_enabled() if IG_AVAILABLE else False,
            "autonomous_autosend": _ig_env_bool("IG_AUTONOMOUS_AUTOSEND", False)}


@app.post("/admin/instagram/campaign/start", dependencies=[Depends(_require_admin_token)])
def instagram_campaign_start(payload: InstagramCampaignStart):
    if not IG_AVAILABLE:
        raise HTTPException(503, "Modulo instagram no disponible")
    if not ig_is_autosend_enabled():
        raise HTTPException(412, "IG_AUTOSEND_ENABLED=false en env")
    try:
        from instagram_autosend import session_info  # type: ignore
        if not session_info().get("connected"):
            raise HTTPException(412, "Sesion IG no conectada. Pega cookies primero.")
    except HTTPException:
        raise
    except Exception:
        pass
    _ig_campaign_migrate()
    _ig_campaign_update(
        target_count=int(payload.target_count),
        status="discovering",
        error_msg="",
        started_at=_instagram_now(),
        completed_at="",
    )
    return {"ok": True, "state": _ig_campaign_state()}


@app.post("/admin/instagram/campaign/pause", dependencies=[Depends(_require_admin_token)])
def instagram_campaign_pause():
    _ig_campaign_migrate()
    _ig_campaign_update(status="paused")
    return {"ok": True, "state": _ig_campaign_state()}


class InstagramDmTemplatesPayload(BaseModel):
    variant_a: Optional[str] = None
    variant_b: Optional[str] = None
    variant_c: Optional[str] = None






@app.get("/admin/instagram/dm-templates", dependencies=[Depends(_require_admin_token)])
def instagram_dm_templates_get():
    _ig_dm_templates_ensure()
    out = {"A": "", "B": "", "C": ""}
    with _instagram_db() as conn:
        rows = conn.execute("SELECT variant, body FROM ig_dm_templates_v2").fetchall()
        for r in rows:
            v = (r["variant"] or "").upper()
            if v in out:
                out[v] = r["body"] or ""
    defaults = {v: _ig_dm_default(v) for v in ("A", "B", "C")}
    placeholders_help = ""
    try:
        from instagram_templates_v2 import PLACEHOLDERS_HELP  # type: ignore
        placeholders_help = PLACEHOLDERS_HELP
    except Exception:
        pass
    return {"templates": out, "defaults": defaults, "placeholders_help": placeholders_help}


@app.put("/admin/instagram/dm-templates", dependencies=[Depends(_require_admin_token)])
def instagram_dm_templates_put(payload: InstagramDmTemplatesPayload):
    _ig_dm_templates_ensure()
    now = _instagram_now()
    data = {"A": payload.variant_a, "B": payload.variant_b, "C": payload.variant_c}
    saved: List[str] = []
    with _instagram_db() as conn:
        for variant, body in data.items():
            if body is None:
                continue
            body_clean = body.strip()
            if body_clean:
                conn.execute(
                    """INSERT INTO ig_dm_templates_v2 (variant, body, updated_at)
                       VALUES (?,?,?)
                       ON CONFLICT(variant) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at""",
                    (variant, body_clean, now),
                )
                saved.append(variant)
            else:
                conn.execute("DELETE FROM ig_dm_templates_v2 WHERE variant=?", (variant,))
                saved.append(variant + " (reset)")
        conn.commit()
    return {"ok": True, "saved": saved}


@app.post("/admin/instagram/dm-templates/preview", dependencies=[Depends(_require_admin_token)])
def instagram_dm_templates_preview(variant: str = "A",
                                    business_name: str = "Clinica Sonrisa",
                                    niche: str = "clinica dental",
                                    city: str = "Madrid"):
    try:
        from instagram_templates_v2 import render_natural  # type: ignore
    except ImportError:
        raise HTTPException(503, "templates_v2 no disponible")
    text = render_natural(
        username=f"preview_{variant.lower()}",
        business_name=business_name,
        niche=niche,
        city=city,
        variant=variant.upper(),
        db_path=str(_instagram_db_path()),
    )
    return {"variant": variant.upper(), "text": text}


@app.post("/admin/instagram/campaign/resume", dependencies=[Depends(_require_admin_token)])
def instagram_campaign_resume():
    if not ig_is_autosend_enabled():
        raise HTTPException(412, "IG_AUTOSEND_ENABLED=false en env")
    _ig_campaign_migrate()
    # Resume: si hay drafts pendientes, va directo a sending; si no, discovering.
    state = _ig_campaign_state()
    next_status = "sending" if (state.get("pending_drafts") or 0) > 0 else "discovering"
    _ig_campaign_update(status=next_status, error_msg="")
    return {"ok": True, "state": _ig_campaign_state()}


# ----- Manual reply mark -----


@app.post("/admin/instagram/replies", dependencies=[Depends(_require_admin_token)])
def instagram_record_reply(payload: InstagramReplyPayload):
    user = _ig_resolve_username(payload.username)
    if not user:
        raise HTTPException(400, "username invalido")
    with _instagram_db() as conn:
        conn.execute(
            "INSERT INTO ig_events (username, type, stage, data_json, ts) VALUES (?,?,?,?,?)",
            (user, "reply", payload.stage, json.dumps({"note": payload.note}, ensure_ascii=False), _instagram_now()),
        )
        conn.execute(
            "UPDATE ig_prospects SET status='replied', updated_at=? WHERE username=?",
            (_instagram_now(), user),
        )
        conn.commit()
    return {"ok": True}


@app.post("/admin/instagram/replies/poll", dependencies=[Depends(_require_admin_token)])
def instagram_replies_poll_now():
    if not IG_REPLIES_AVAILABLE or ig_replies_poll is None:
        raise HTTPException(503, "Poller IG no disponible (falta IG_GRAPH_TOKEN o httpx)")
    db_path = _instagram_db_path()
    stats = ig_replies_poll(db_path)
    return {"ok": True, "stats": stats}


# ----- Workers -----










# === END INSTAGRAM ===================================================


# =====================================================================
# === WHATSAPP OUTREACH ===============================================
# Cold outbound por WhatsApp Web (Playwright, tu propio numero). Coge los
# telefonos de los prospects de Captacion (outreach.db) — NO hace discovery
# propio. Un unico mensaje por telefono (dedup). Envio automatico opt-in via
# WA_AUTOSEND_ENABLED + numero vinculado por QR. Riesgo ban Meta: numero 2ario.
# =====================================================================



class WhatsAppMessagePayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class WhatsAppSendPayload(BaseModel):
    count: int = Field(20, ge=1, le=200)
    dry_run: bool = False










@app.get("/admin/whatsapp/stats", dependencies=[Depends(_require_admin_token)])
def whatsapp_stats():
    with _whatsapp_db() as conn:
        s = wa_outreach.stats(conn)
    return {"stats": s, "autosend_enabled": _wa_autosend_enabled(),
            "session": _wa_session_info(), "progress": _wa_send_progress()}


@app.get("/admin/whatsapp/recent", dependencies=[Depends(_require_admin_token)])
def whatsapp_recent(limit: int = 30):
    with _whatsapp_db() as conn:
        return {"items": wa_outreach.recent(conn, limit)}


@app.get("/admin/whatsapp/message", dependencies=[Depends(_require_admin_token)])
def whatsapp_message_get():
    with _whatsapp_db() as conn:
        tpl = wa_outreach.get_message_template(conn)
    return {"message": tpl, "default": wa_outreach.DEFAULT_MESSAGE,
            "placeholders_help": wa_outreach.PLACEHOLDERS_HELP}


@app.put("/admin/whatsapp/message", dependencies=[Depends(_require_admin_token)])
def whatsapp_message_put(payload: WhatsAppMessagePayload):
    with _whatsapp_db() as conn:
        wa_outreach.set_message_template(conn, payload.message)
    return {"ok": True}


@app.post("/admin/whatsapp/send", dependencies=[Depends(_require_admin_token)])
def whatsapp_send(payload: WhatsAppSendPayload, background_tasks: BackgroundTasks):
    if not WA_AVAILABLE:
        raise HTTPException(503, "Modulo whatsapp no disponible")
    if not payload.dry_run:
        if not _wa_autosend_enabled():
            raise HTTPException(412, "WA_AUTOSEND_ENABLED=false en el .env del servidor")
        if not _wa_session_info().get("connected"):
            raise HTTPException(412, "WhatsApp no conectado. Vincula tu numero (QR) en Configuracion.")
    target_count = int(payload.count)
    candidate_limit = min(500, max(target_count, target_count * 4))
    with _whatsapp_db() as conn:
        # Rellena una bolsa extra de candidatos: los numero_invalido no cuentan
        # contra el objetivo de enviados reales.
        existing = len(wa_outreach.fetch_queued(conn, candidate_limit))
        need = max(0, candidate_limit - existing)
        if need:
            wa_outreach.enqueue(conn, need)
        items = [{"phone": q["phone"], "message": q["message"]}
                 for q in wa_outreach.fetch_queued(conn, candidate_limit)]
    if not items:
        return {"ok": True, "queued": 0, "detail": "No quedan telefonos nuevos por contactar."}

    if not _wa_send_job_lock.acquire(blocking=False):
        raise HTTPException(409, "Ya hay un envio WhatsApp en curso. Espera a que termine antes de lanzar otro.")

    with _wa_send_lock:
        _wa_send_state.update({
            "running": True,
            "phase": "queued",
            "requested": target_count,
            "queued": target_count,
            "candidates": len(items),
            "attempted": 0,
            "sent": 0,
            "skipped": 0,
            "current_phone": "",
            "last_reason": "",
            "dry_run": bool(payload.dry_run),
            "started_at": _utc_now().isoformat(),
            "finished_at": "",
        })

    def _run() -> None:
        try:
            from whatsapp_autosend import autosend_messages  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("wa autosend no disponible: %s", exc)
            with _wa_send_lock:
                _wa_send_state.update({
                    "running": False,
                    "phase": "error",
                    "last_reason": str(exc)[:160],
                    "finished_at": _utc_now().isoformat(),
                })
            try:
                _wa_send_job_lock.release()
            except RuntimeError:
                pass
            return

        def _attempt(phone: str) -> None:
            with _wa_send_lock:
                _wa_send_state.update({"phase": "sending", "current_phone": phone, "last_reason": ""})
            try:
                with wa_outreach.connect() as c:
                    wa_outreach.mark_sending(c, phone)
            except Exception:
                pass

        def _mark(phone: str, ok: bool, reason: str) -> None:
            with _wa_send_lock:
                _wa_send_state["attempted"] = int(_wa_send_state.get("attempted") or 0) + 1
                if ok:
                    _wa_send_state["sent"] = int(_wa_send_state.get("sent") or 0) + 1
                else:
                    _wa_send_state["skipped"] = int(_wa_send_state.get("skipped") or 0) + 1
                _wa_send_state.update({
                    "phase": "skipping" if reason == "numero_invalido" else "pausing",
                    "current_phone": phone,
                    "last_reason": "" if ok else (reason or ""),
                })
            try:
                with wa_outreach.connect() as c:
                    if ok:
                        wa_outreach.mark_sent(c, phone)
                    else:
                        wa_outreach.mark_skipped(c, phone, reason)
            except Exception as exc:  # noqa: BLE001
                logger.warning("wa mark %s: %s", phone, exc)

        try:
            autosend_messages(
                items,
                dry_run=payload.dry_run,
                on_result=_mark,
                on_attempt=_attempt,
                target_ok=target_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("wa autosend error: %s", exc)
            with _wa_send_lock:
                _wa_send_state.update({"phase": "error", "last_reason": str(exc)[:160]})
        finally:
            with _wa_send_lock:
                if _wa_send_state.get("phase") not in ("error",):
                    _wa_send_state["phase"] = "done"
                _wa_send_state.update({
                    "running": False,
                    "current_phone": "",
                    "finished_at": _utc_now().isoformat(),
                })
            try:
                _wa_send_job_lock.release()
            except RuntimeError:
                pass

    background_tasks.add_task(_run)
    return {"ok": True, "queued": target_count, "target": target_count, "candidates": len(items), "dry_run": payload.dry_run}


@app.get("/admin/whatsapp/session", dependencies=[Depends(_require_admin_token)])
def whatsapp_session():
    return {"session": _wa_session_info(),
            "autosend_enabled": _wa_autosend_enabled(),
            "login_running": bool(_wa_login_state.get("running")),
            "login_status": _wa_login_state.get("status", ""),
            "login_result": _wa_login_state.get("result")}


@app.post("/admin/whatsapp/connect", dependencies=[Depends(_require_admin_token)])
def whatsapp_connect():
    if not WA_AVAILABLE:
        raise HTTPException(503, "Modulo whatsapp no disponible")
    try:
        from whatsapp_autosend import start_login_session  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"whatsapp_autosend no disponible: {exc}")
    with _wa_login_lock:
        if _wa_login_state.get("running"):
            return {"ok": True, "already_running": True}
        _wa_login_state.update({"running": True, "result": None, "status": "arrancando"})

    def _login() -> None:
        def _status(msg: str) -> None:
            _wa_login_state["status"] = msg
        try:
            res = start_login_session(timeout_sec=180, headless=True, on_status=_status)
            _wa_login_state["result"] = res
        except Exception as exc:  # noqa: BLE001
            _wa_login_state["result"] = {"connected": False, "reason": str(exc)[:200]}
        finally:
            _wa_login_state["running"] = False

    threading.Thread(target=_login, name="wa-login", daemon=True).start()
    return {"ok": True, "started": True}


@app.get("/admin/whatsapp/qr", dependencies=[Depends(_require_admin_token)])
def whatsapp_qr():
    try:
        from whatsapp_autosend import latest_qr_bytes  # type: ignore
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "whatsapp_autosend no disponible")
    data = latest_qr_bytes()
    if not data:
        raise HTTPException(404, "QR aun no disponible")
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/admin/whatsapp/debug-shot", dependencies=[Depends(_require_admin_token)])
def whatsapp_debug_shot():
    """Ultima captura del navegador headless (diagnostico de envio)."""
    try:
        from whatsapp_autosend import latest_debug_bytes  # type: ignore
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "whatsapp_autosend no disponible")
    data = latest_debug_bytes()
    if not data:
        raise HTTPException(404, "Sin captura de debug todavia")
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.post("/admin/whatsapp/disconnect", dependencies=[Depends(_require_admin_token)])
def whatsapp_disconnect():
    try:
        from whatsapp_autosend import clear_session  # type: ignore
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "whatsapp_autosend no disponible")
    removed = clear_session()
    _wa_login_state.update({"running": False, "result": None, "status": ""})
    return {"ok": True, "removed": removed}


@app.post("/admin/whatsapp/test", dependencies=[Depends(_require_admin_token)])
def whatsapp_test():
    try:
        from whatsapp_autosend import verify_session  # type: ignore
    except Exception:  # noqa: BLE001
        raise HTTPException(503, "whatsapp_autosend no disponible")
    return verify_session(timeout_sec=40)


# === END WHATSAPP ====================================================


# =====================================================================
# === TIKTOK ==========================================================
# Captacion via TikTok DMs. Mismo flujo que IG campaign:
# discovery (Places + web scrape handle) → drafts → autosend Playwright.
# =====================================================================
















class TKCampaignStart(BaseModel):
    target_count: int = Field(30, ge=1, le=200)


class TKSessionCookies(BaseModel):
    sessionid: str = Field(..., min_length=10)
    sessionid_ss: str = ""
    tt_csrf_token: str = ""
    ms_token: str = ""
    ttwid: str = ""


class TKDmTemplatesPayload(BaseModel):
    variant_a: Optional[str] = None
    variant_b: Optional[str] = None
    variant_c: Optional[str] = None


class TKSuppressRequest(BaseModel):
    username: str = Field(..., min_length=1)
    reason: str = "manual"






















# ----- Endpoints campaign -----

@app.get("/admin/tiktok/campaign", dependencies=[Depends(_require_admin_token)])
def tiktok_campaign_get():
    state = _tk_campaign_state()
    try:
        from tiktok_autosend import session_info  # type: ignore
        session = session_info()
    except Exception:
        session = {"connected": False}
    return {"campaign": state, "session": session,
            "autosend_enabled": tk_is_autosend_enabled() if TK_AVAILABLE else False,
            "autonomous_autosend": _tk_env_bool("TK_AUTONOMOUS_AUTOSEND", False)}


@app.post("/admin/tiktok/campaign/start", dependencies=[Depends(_require_admin_token)])
def tiktok_campaign_start(payload: TKCampaignStart):
    if not TK_AVAILABLE:
        raise HTTPException(503, "Modulo TikTok no disponible")
    if not tk_is_autosend_enabled():
        raise HTTPException(412, "TK_AUTOSEND_ENABLED=false en env")
    try:
        from tiktok_autosend import session_info  # type: ignore
        if not session_info().get("connected"):
            raise HTTPException(412, "Sesion TikTok no conectada. Pega cookies primero.")
    except HTTPException:
        raise
    except Exception:
        pass
    _tk_migrate()
    _tk_campaign_update(
        target_count=int(payload.target_count),
        status="discovering",
        error_msg="",
        started_at=_tk_now(),
        completed_at="",
    )
    return {"ok": True, "state": _tk_campaign_state()}


@app.post("/admin/tiktok/campaign/pause", dependencies=[Depends(_require_admin_token)])
def tiktok_campaign_pause():
    _tk_migrate()
    _tk_campaign_update(status="paused")
    return {"ok": True, "state": _tk_campaign_state()}


@app.post("/admin/tiktok/campaign/resume", dependencies=[Depends(_require_admin_token)])
def tiktok_campaign_resume():
    if not tk_is_autosend_enabled():
        raise HTTPException(412, "TK_AUTOSEND_ENABLED=false en env")
    _tk_migrate()
    state = _tk_campaign_state()
    next_status = "sending" if (state.get("pending_drafts") or 0) > 0 else "discovering"
    _tk_campaign_update(status=next_status, error_msg="")
    return {"ok": True, "state": _tk_campaign_state()}


# ----- Sesion / cookies -----

@app.get("/admin/tiktok/autosend/status", dependencies=[Depends(_require_admin_token)])
def tiktok_autosend_status():
    try:
        from tiktok_autosend import session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/tiktok_autosend.py no disponible")
    return {
        "autosend_enabled": tk_is_autosend_enabled(),
        "autonomous_autosend": _tk_env_bool("TK_AUTONOMOUS_AUTOSEND", False),
        "session": session_info(),
    }


@app.post("/admin/tiktok/autosend/connect", dependencies=[Depends(_require_admin_token)])
def tiktok_autosend_connect(payload: TKSessionCookies):
    try:
        from tiktok_autosend import save_session_from_cookies, session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/tiktok_autosend.py no disponible")
    try:
        path = save_session_from_cookies(
            sessionid=payload.sessionid,
            sessionid_ss=payload.sessionid_ss,
            tt_csrf_token=payload.tt_csrf_token,
            ms_token=payload.ms_token,
            ttwid=payload.ttwid,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "saved_at": str(path), "session": session_info()}


@app.post("/admin/tiktok/autosend/disconnect", dependencies=[Depends(_require_admin_token)])
def tiktok_autosend_disconnect():
    try:
        from tiktok_autosend import clear_session  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/tiktok_autosend.py no disponible")
    removed = clear_session()
    return {"ok": True, "removed": removed}


@app.post("/admin/tiktok/autosend/test", dependencies=[Depends(_require_admin_token)])
def tiktok_autosend_test():
    try:
        from tiktok_autosend import session_info  # type: ignore
    except ImportError:
        raise HTTPException(503, "scripts/tiktok_autosend.py no disponible")
    info = session_info()
    if not info.get("connected"):
        return {"ok": False, "reason": "sin_sesion"}
    sessionid = ""
    try:
        state_path = Path(info.get("path") or "")
        if state_path.exists():
            data = json.loads(state_path.read_text(encoding="utf-8"))
            for c in data.get("cookies", []):
                if c.get("name") == "sessionid":
                    sessionid = c.get("value") or ""
                    break
    except Exception as exc:
        raise HTTPException(500, f"No se pudo leer sesion: {exc}")
    if not sessionid:
        return {"ok": False, "reason": "sin_sessionid"}
    cookies = {"sessionid": sessionid}
    headers = {
        "User-Agent": os.getenv("TK_AUTOSEND_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept-Language": "es-ES,es;q=0.9",
    }
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            r = client.get("https://www.tiktok.com/foryou", cookies=cookies, headers=headers)
        ok = r.status_code == 200 and ("tiktok" in (r.text or "").lower())
        return {"ok": ok, "status_code": r.status_code, "session": info,
                "hint": "Cookies validas" if ok else "Cookies caducadas. Reconecta."}
    except Exception as exc:
        return {"ok": False, "reason": f"http_error: {exc}", "session": info}


# ----- DM templates editor -----



@app.get("/admin/tiktok/dm-templates", dependencies=[Depends(_require_admin_token)])
def tiktok_dm_templates_get():
    _tk_migrate()
    out = {"A": "", "B": "", "C": ""}
    with _tk_db() as conn:
        rows = conn.execute("SELECT variant, body FROM tk_dm_templates_v2").fetchall()
        for r in rows:
            v = (r["variant"] or "").upper()
            if v in out:
                out[v] = r["body"] or ""
    defaults = {v: _tk_dm_default(v) for v in ("A", "B", "C")}
    placeholders_help = ""
    try:
        from tiktok_templates_v2 import PLACEHOLDERS_HELP  # type: ignore
        placeholders_help = PLACEHOLDERS_HELP
    except Exception:
        pass
    return {"templates": out, "defaults": defaults, "placeholders_help": placeholders_help}


@app.put("/admin/tiktok/dm-templates", dependencies=[Depends(_require_admin_token)])
def tiktok_dm_templates_put(payload: TKDmTemplatesPayload):
    _tk_migrate()
    now = _tk_now()
    data = {"A": payload.variant_a, "B": payload.variant_b, "C": payload.variant_c}
    saved: List[str] = []
    with _tk_db() as conn:
        for variant, body in data.items():
            if body is None:
                continue
            body_clean = body.strip()
            if body_clean:
                conn.execute(
                    """INSERT INTO tk_dm_templates_v2 (variant, body, updated_at)
                       VALUES (?,?,?)
                       ON CONFLICT(variant) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at""",
                    (variant, body_clean, now),
                )
                saved.append(variant)
            else:
                conn.execute("DELETE FROM tk_dm_templates_v2 WHERE variant=?", (variant,))
                saved.append(variant + " (reset)")
        conn.commit()
    return {"ok": True, "saved": saved}


@app.post("/admin/tiktok/dm-templates/preview", dependencies=[Depends(_require_admin_token)])
def tiktok_dm_templates_preview(variant: str = "A",
                                 business_name: str = "Clinica Sonrisa",
                                 niche: str = "clinica dental",
                                 city: str = "Madrid"):
    try:
        from tiktok_templates_v2 import render_natural  # type: ignore
    except ImportError:
        raise HTTPException(503, "tiktok_templates_v2 no disponible")
    text = render_natural(
        username=f"preview_{variant.lower()}",
        business_name=business_name,
        niche=niche,
        city=city,
        variant=variant.upper(),
        db_path=str(TK_DEFAULT_DB),
    )
    return {"variant": variant.upper(), "text": text}


# ----- Suppressions / stats / prospects -----

@app.get("/admin/tiktok/stats", dependencies=[Depends(_require_admin_token)])
def tiktok_stats():
    _tk_migrate()
    today = _utc_now().date().isoformat()
    with _tk_db() as conn:
        sent_today = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_sends WHERE mode='sent_auto' AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]
        sent_total = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_sends WHERE mode='sent_auto'"
        ).fetchone()["c"]
        replies = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_prospects WHERE status='replied'"
        ).fetchone()["c"]
        drafts = conn.execute(
            "SELECT COUNT(*) AS c FROM tk_sends WHERE mode='draft' AND ready=1"
        ).fetchone()["c"]
        prospects = conn.execute("SELECT COUNT(*) AS c FROM tk_prospects").fetchone()["c"]
    return {"totals": {"prospects": prospects, "sent_today": sent_today,
                       "sent_total": sent_total, "replies_unique": replies,
                       "drafts_pending": drafts}}


@app.post("/admin/tiktok/suppress", dependencies=[Depends(_require_admin_token)])
def tiktok_suppress(payload: TKSuppressRequest):
    user = _tk_resolve_username(payload.username)
    if not user:
        raise HTTPException(400, "username invalido")
    _tk_migrate()
    with _tk_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tk_suppressions (username, reason, added_at) VALUES (?,?,?)",
            (user, payload.reason or "manual", _tk_now()),
        )
        conn.execute(
            "UPDATE tk_prospects SET status='dnc', updated_at=? WHERE username=?",
            (_tk_now(), user),
        )
        conn.commit()
    return {"ok": True, "username": user}


@app.delete("/admin/tiktok/suppress/{username}", dependencies=[Depends(_require_admin_token)])
def tiktok_remove_suppress(username: str):
    user = _tk_resolve_username(username)
    _tk_migrate()
    with _tk_db() as conn:
        conn.execute("DELETE FROM tk_suppressions WHERE username=?", (user,))
        conn.commit()
    return {"ok": True}


@app.get("/admin/tiktok/suppressions", dependencies=[Depends(_require_admin_token)])
def tiktok_list_suppressions(limit: int = 200):
    _tk_migrate()
    with _tk_db() as conn:
        rows = conn.execute(
            "SELECT username, reason, added_at FROM tk_suppressions ORDER BY added_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.get("/admin/tiktok/prospects", dependencies=[Depends(_require_admin_token)])
def tiktok_prospects(limit: int = 100, status: str = ""):
    _tk_migrate()
    q = "SELECT * FROM tk_prospects"
    params: List[Any] = []
    if status:
        q += " WHERE status=?"
        params.append(status)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _tk_db() as conn:
        rows = conn.execute(q, params).fetchall()
    return {"items": [dict(r) for r in rows]}


# ----- Worker startup/shutdown -----





# === END TIKTOK ======================================================


# ─── VOICE / TWILIO ──────────────────────────────────────────────────────────
# Canal de voz (Nivel 1: desvio de llamada -> numero Twilio -> Media Streams ->
# OpenAI Realtime API). El cliente configura en su operadora un desvio hacia el
# numero Twilio asignado. Twilio llama a POST /voice/{cliente_id}, recibe TwiML
# con <Connect><Stream> y abre un WebSocket de audio bidireccional contra
# /voice/stream/{cliente_id}, que hace de puente con OpenAI Realtime.


try:  # validador oficial Twilio si esta instalado; si no, fallback nativo HMAC-SHA1
    from twilio.request_validator import RequestValidator as _TwilioRequestValidator
except Exception:  # noqa: BLE001
    _TwilioRequestValidator = None




































































@app.post("/voice/{cliente_id}")
async def voice_incoming_call(cliente_id: str, request: Request) -> Response:
    """Webhook Twilio para una llamada entrante. Devuelve TwiML con Media Stream."""
    if not CLIENT_ID_PATTERN.match(cliente_id):
        return _voice_twiml_unavailable()
    if not _voice_twilio_configured():
        raise HTTPException(status_code=503, detail="Voice not configured")

    params = await _voice_form_params(request)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not _twilio_request_valid(_voice_request_url(request), params, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    voice_cfg = _get_voice_config(cliente_id)
    if not voice_cfg:
        return _voice_twiml_unavailable()

    call_sid = params.get("CallSid", "")
    if call_sid:
        _voice_call_register(call_sid, cliente_id, params.get("From", ""), params.get("To", ""))

    return _voice_twiml_connect_stream(_voice_stream_ws_url(request, cliente_id), call_sid)


@app.post("/voice/status/{cliente_id}")
async def voice_status_callback(cliente_id: str, request: Request) -> Response:
    """Status callback de Twilio (completed/failed/busy/no-answer)."""
    if not _voice_twilio_configured():
        raise HTTPException(status_code=503, detail="Voice not configured")
    params = await _voice_form_params(request)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not _twilio_request_valid(_voice_request_url(request), params, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    call_sid = params.get("CallSid", "")
    call_status = (params.get("CallStatus", "") or "").lower()
    mapping = {
        "completed": "completed",
        "busy": "no_answer",
        "no-answer": "no_answer",
        "failed": "failed",
        "canceled": "failed",
    }
    new_status = mapping.get(call_status)
    if call_sid and new_status:
        try:
            with _get_db_connection() as conn:
                conn.execute(
                    "UPDATE voice_calls SET status=? WHERE call_sid=? AND status != 'completed'",
                    (new_status, call_sid),
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("[voice] status callback fallo para %s: %s", call_sid, exc)
    return Response(status_code=204)


@app.websocket("/voice/stream/{cliente_id}")
async def voice_media_stream(websocket: WebSocket, cliente_id: str) -> None:
    """Puente bidireccional Twilio Media Streams <-> OpenAI Realtime API."""
    if not CLIENT_ID_PATTERN.match(cliente_id):
        await websocket.close(code=1008)
        return
    config = appstate.CONFIG_CLIENTES.get(cliente_id)
    voice_cfg = _get_voice_config(cliente_id)
    if not config or not voice_cfg:
        await websocket.close(code=1008)
        return
    if not OPENAI_API_KEY:
        await websocket.close(code=1011)
        return

    await websocket.accept()

    state: Dict[str, Any] = {
        "stream_sid": "",
        "call_sid": "",
        "booked": False,
        "fn_names": {},
        "latest_media_timestamp": 0,
        "assistant_item_id": "",
        "assistant_audio_started_at": None,
        "assistant_audio_generated_ms": 0,
    }
    transcript: List[Dict[str, str]] = []
    started_monotonic = time.time()
    max_duration = int(voice_cfg.get("max_duration_seconds") or 0) or VOICE_MAX_DURATION_SECONDS
    status_value = "completed"

    def _append_transcript(role: str, text: str) -> None:
        clean = (text or "").strip()
        if clean:
            transcript.append(
                {"role": role, "text": clean, "ts": _utc_now().isoformat()}
            )

    realtime_model = voice_cfg.get("realtime_model") or VOICE_REALTIME_MODEL
    try:
        openai_ws = await _open_realtime_ws(realtime_model)
    except Exception as exc:  # noqa: BLE001
        logger.error("[voice] no se pudo conectar a OpenAI Realtime (%s): %s", cliente_id, exc)
        await websocket.close(code=1011)
        return

    try:
        await openai_ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "model": realtime_model,
                        "output_modalities": ["audio"],
                        "instructions": _voice_build_instructions(cliente_id, config),
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcmu"},
                                # semantic_vad en vez de server_vad: en telefonia no hay
                                # AEC y el eco de la linea se colaba como inbound; con un
                                # VAD por amplitud eso disparaba una respuesta al propio
                                # audio (se corta + repite). El VAD semantico solo abre
                                # turno cuando de verdad habla el llamante, asi que ignora
                                # eco/ruido de la linea. eagerness=low es conservador;
                                # interrupt_response=True permite un barge-in natural. Al
                                # detectar habla truncamos manualmente el audio pendiente de
                                # Twilio para que el modelo no repita la frase completa.
                                "turn_detection": {
                                    "type": "semantic_vad",
                                    "eagerness": "low",
                                    "create_response": True,
                                    "interrupt_response": True,
                                },
                                "transcription": {"model": "whisper-1"},
                            },
                            "output": {
                                "format": {"type": "audio/pcmu"},
                                "voice": voice_cfg.get("openai_voice") or VOICE_OPENAI_VOICE,
                            },
                        },
                        "tools": _voice_booking_tools(cliente_id, config),
                        "tool_choice": "auto",
                    },
                }
            )
        )

        # Prioridad del saludo: greeting de voz especifico -> mensaje de bienvenida
        # de "Apariencia" (bienvenida) -> default con el nombre del asistente de voz.
        # Compartido con el test del panel y la demo via _voice_default_greeting.
        greeting = _voice_default_greeting(config, voice_cfg)
        await openai_ws.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": f'Inicia la llamada saludando exactamente con: "{greeting}"',
                            }
                        ],
                    },
                }
            )
        )
        await openai_ws.send(json.dumps({"type": "response.create"}))

        async def twilio_to_openai() -> None:
            try:
                async for raw in websocket.iter_text():
                    message = json.loads(raw)
                    event = message.get("event")
                    if event == "media":
                        try:
                            state["latest_media_timestamp"] = int(
                                message.get("media", {}).get("timestamp", 0)
                            )
                        except (TypeError, ValueError):
                            pass
                        await openai_ws.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": message["media"]["payload"],
                                }
                            )
                        )
                    elif event == "start":
                        start = message.get("start", {})
                        state["stream_sid"] = start.get("streamSid", "")
                        state["call_sid"] = start.get("callSid", "") or start.get(
                            "customParameters", {}
                        ).get("call_sid", "")
                        state["from_number"] = _voice_call_from_number(state["call_sid"])
                    elif event == "stop":
                        break
            except WebSocketDisconnect:
                pass
            finally:
                await _voice_safe_close(openai_ws)

        async def openai_to_twilio() -> None:
            async def _stream_sid_ready(timeout_seconds: float = 3.0) -> str:
                deadline = time.time() + timeout_seconds
                while not state["stream_sid"] and time.time() < deadline:
                    await asyncio.sleep(0.02)
                return state["stream_sid"]

            async for raw in openai_ws:
                event = json.loads(raw)
                etype = event.get("type")
                if etype == "response.output_audio.delta" and event.get("delta"):
                    stream_sid = state["stream_sid"] or await _stream_sid_ready()
                    if stream_sid:
                        item_id = event.get("item_id", "")
                        if item_id and item_id != state["assistant_item_id"]:
                            state["assistant_item_id"] = item_id
                            state["assistant_audio_started_at"] = state["latest_media_timestamp"]
                            state["assistant_audio_generated_ms"] = 0
                        state["assistant_audio_generated_ms"] += _voice_pcmu_duration_ms(
                            event["delta"]
                        )
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": event["delta"]},
                                }
                            )
                        )
                elif etype == "response.output_audio_transcript.done":
                    _append_transcript("assistant", event.get("transcript", ""))
                elif etype == "conversation.item.input_audio_transcription.completed":
                    _append_transcript("user", event.get("transcript", ""))
                elif etype == "response.output_item.added":
                    item = event.get("item", {}) or {}
                    if item.get("type") == "function_call" and item.get("call_id"):
                        state["fn_names"][item["call_id"]] = item.get("name", "")
                elif etype == "response.function_call_arguments.done":
                    call_id = event.get("call_id", "")
                    fname = event.get("name") or state["fn_names"].get(call_id, "")
                    result = await _voice_dispatch_tool(
                        cliente_id, fname, event.get("arguments", ""),
                        from_number=state.get("from_number", ""),
                    )
                    if fname == "crear_cita" and result.get("ok"):
                        state["booked"] = True
                    await openai_ws.send(
                        json.dumps(
                            {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": json.dumps(result, ensure_ascii=False),
                                },
                            }
                        )
                    )
                    await openai_ws.send(json.dumps({"type": "response.create"}))
                elif etype == "input_audio_buffer.speech_started":
                    await _voice_truncate_interrupted_response(openai_ws, websocket, state)
                elif etype == "error":
                    logger.warning("[voice] OpenAI error %s: %s", cliente_id, event.get("error"))

        tasks = [
            asyncio.create_task(twilio_to_openai()),
            asyncio.create_task(openai_to_twilio()),
        ]
        _done, pending = await asyncio.wait(
            tasks, timeout=max_duration, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[voice] error en stream de %s: %s", cliente_id, exc)
        status_value = "failed"
    finally:
        await _voice_safe_close(openai_ws)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
        await _voice_finalize_call(
            cliente_id=cliente_id,
            config=config,
            voice_cfg=voice_cfg,
            call_sid=state["call_sid"],
            transcript=transcript,
            duration_seconds=int(time.time() - started_monotonic),
            status_value=status_value,
            booking_done=bool(state.get("booked")),
        )




@app.get("/admin/voice/calls", dependencies=[Depends(_require_admin_token)])
async def admin_voice_calls(
    cliente_id: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    where: List[str] = []
    params: List[Any] = []
    if cliente_id:
        where.append("cliente_id=?")
        params.append(cliente_id)
    if status:
        where.append("status=?")
        params.append(status)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    offset = (page - 1) * page_size
    with _get_db_connection() as conn:
        total = int(
            conn.execute(f"SELECT COUNT(*) AS c FROM voice_calls{clause}", params).fetchone()["c"]
        )
        rows = conn.execute(
            f"""
            SELECT id, call_sid, cliente_id, from_number, started_at,
                   duration_seconds, status, summary, booking_created
            FROM voice_calls{clause}
            ORDER BY id DESC LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()
        stats = _voice_stats(conn, cliente_id)
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "stats": stats,
    }


@app.get("/admin/voice/calls/{call_sid}", dependencies=[Depends(_require_admin_token)])
async def admin_voice_call_detail(call_sid: str) -> Dict[str, Any]:
    with _get_db_connection() as conn:
        row = conn.execute("SELECT * FROM voice_calls WHERE call_sid=?", (call_sid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Llamada no encontrada")
    data = dict(row)
    try:
        data["transcript"] = json.loads(data.get("transcript_json") or "[]")
    except Exception:  # noqa: BLE001
        data["transcript"] = []
    return data




# ============================================================================
# Epilogo de compatibilidad (refactor F3).
#
# A medida que el monolito se extrae a backend/, este proxy mantiene el
# contrato historico del modulo `api`:
#   - `api.simbolo` lee EN VIVO del modulo home en backend/ (via __getattr__).
#   - `monkeypatch.setattr(api, "simbolo", ...)` parchea el modulo home (y la
#     copia transitoria importada en api, si existe), de modo que TODOS los
#     llamadores ven el parche (__setattr__).
#   - `dir(api)` incluye los simbolos extraidos (scripts/qa_e2e.py itera
#     dir(api) para anular _send_whatsapp*).
# ============================================================================
import types as _types

# Modulos home ya extraidos, de mas especifico a mas generico (el primero que
# define un nombre gana). Crece con cada sub-commit de la fase 3.
_HOME_MODULES: tuple = (appstate, main, voice, wa_capture, instagram, tiktok, outreach, growth, billing, portal, onboarding, whatsapp, chat, booking, demo_agenda, agenda, rag, crm, security, emailing, messaging, stripe_gateway, clients, db, timeutils, textnorm, settings)

_EXPORT_MAP: Dict[str, Any] = {}
for _home_mod in _HOME_MODULES:
    for _exported, _val in vars(_home_mod).items():
        # Los alias de submodulos backend (chat, db, agenda...) no son simbolos
        # exportables: contaminarian el mapa y pisarian defs propias de api.
        # OJO: modulos de terceros como `stripe` SI se exportan (los tests los
        # parchean con fakes via este proxy).
        if not _exported.startswith("__") and not (
            isinstance(_val, _types.ModuleType) and _val.__name__.startswith("backend")
        ):
            _EXPORT_MAP.setdefault(_exported, _home_mod)


class _ApiCompatModule(_types.ModuleType):
    def __getattr__(self, name: str):
        home = _EXPORT_MAP.get(name)
        if home is None:
            raise AttributeError(f"module 'api' has no attribute {name!r}")
        return getattr(home, name)

    def __setattr__(self, name: str, value: Any) -> None:
        home = _EXPORT_MAP.get(name)
        if home is not None:
            setattr(home, name, value)
            # Mantener en sync la copia transitoria solo si api ya la tiene;
            # si el simbolo vive solo en backend, no crear una sombra estatica.
            if name in self.__dict__:
                super().__setattr__(name, value)
            return
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in self.__dict__:
            super().__delattr__(name)
            return
        home = _EXPORT_MAP.get(name)
        if home is not None:
            delattr(home, name)
            return
        super().__delattr__(name)

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(_EXPORT_MAP))


_sys.modules[__name__].__class__ = _ApiCompatModule


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
