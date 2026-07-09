"""Envio de email transaccional: SMTP Vantelia y Gmail OAuth por cliente (refactor F3).

_send_client_email selecciona Gmail OAuth del negocio o SMTP global segun
canal configurado. Tokens Gmail SIEMPRE cifrados (Fernet); no registrar
tokens en claro. No enviar emails reales en tests.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import secrets
import smtplib
import sqlite3
import time
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from html import escape
from urllib.parse import urlparse
from typing import Any, Dict, Optional, Tuple

import httpx
from cryptography.fernet import InvalidToken
from fastapi import HTTPException, Request

from api_models import ChannelEmailStatus, ChannelSettingsResponse, ChannelSmsStatus
from backend import appstate, clients, db, security, settings, textnorm, timeutils

def _send_password_reset_email(user: sqlite3.Row, public_token: str, request: Optional[Request] = None) -> None:
    reset_url = security._password_reset_url(public_token, request)
    base_url = (textnorm._preferred_public_base_url(request) or settings.APP_BASE_URL or "https://app.vantelia.es").rstrip("/")
    logo_url = f"{base_url}/brand-assets/Logo_1_sin_resplandor.png"
    display_name = str(user["display_name"] or "").strip()
    greeting_text = f"Hola {display_name}," if display_name else "Hola,"
    greeting_html = f"Hola {escape(display_name)}," if display_name else "Hola,"
    expires_minutes = max(1, settings.PASSWORD_RESET_TOKEN_HOURS * 60)
    expires_text = f"{expires_minutes} minuto{'s' if expires_minutes != 1 else ''}"
    reset_domain = urlparse(reset_url).netloc or "app.vantelia.es"
    support_email = settings.PORTAL_SUPPORT_EMAIL or settings.DEFAULT_VANTELIA_SUPPORT_EMAIL
    current_year = timeutils._utc_now().year
    subject = "Restablece tu contraseña de Vantelia"
    text_body = (
        f"{greeting_text}\n\n"
        "Hemos recibido una solicitud para restablecer la contraseña de tu acceso a Vantelia.\n\n"
        "Para crear una nueva contraseña, abre este enlace seguro:\n"
        f"{reset_url}\n\n"
        f"Dominio seguro: {reset_domain}\n"
        f"Este enlace expirará en {expires_text}.\n\n"
        "Si no has solicitado este cambio, puedes ignorar este mensaje. Tu cuenta seguirá protegida.\n\n"
        f"Si tienes problemas, contacta con soporte: {support_email}\n\n"
        "Vantelia\n"
        f"(c) {current_year} Vantelia. Todos los derechos reservados.\n"
    )
    html_body = f"""<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <meta name="supported-color-schemes" content="light">
    <title>Restablece tu contraseña de Vantelia</title>
  </head>
  <body style="margin:0;padding:0;background:#0B132B;font-family:Inter,Segoe UI,Arial,sans-serif;color:#F0F4F8;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
      Hemos recibido una solicitud para restablecer tu contraseña de Vantelia. El enlace expira en {escape(expires_text)}.
    </div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="width:100%;background:#0B132B;">
      <tr>
        <td align="center" style="padding:28px 14px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="width:100%;max-width:640px;border-collapse:separate;border-spacing:0;">
            <tr>
              <td style="padding:0 0 18px;text-align:center;">
                <img src="{escape(logo_url)}" width="148" alt="Vantelia" style="display:inline-block;width:148px;max-width:60%;height:auto;border:0;outline:none;text-decoration:none;">
              </td>
            </tr>
            <tr>
              <td style="border:1px solid rgba(0,209,255,0.22);border-radius:24px;overflow:hidden;background:#08102A;box-shadow:0 28px 70px rgba(0,0,0,0.38);">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td style="padding:34px 30px 22px;background:linear-gradient(135deg,rgba(0,209,255,0.18),rgba(0,245,212,0.08) 46%,rgba(8,16,42,0.92));">
                      <div style="display:inline-block;padding:7px 12px;border:1px solid rgba(0,209,255,0.30);border-radius:999px;background:rgba(0,209,255,0.10);color:#00D1FF;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;">
                        Acceso seguro
                      </div>
                      <h1 style="margin:18px 0 0;font-family:'Space Grotesk',Inter,Segoe UI,Arial,sans-serif;font-size:30px;line-height:1.12;color:#FFFFFF;font-weight:700;">
                        Restablece tu contraseña
                      </h1>
                      <p style="margin:12px 0 0;color:#D4E3EE;font-size:16px;line-height:1.65;">
                        {greeting_html} hemos recibido una solicitud para cambiar la contraseña de tu acceso a Vantelia.
                      </p>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:30px;">
                      <p style="margin:0 0 22px;color:#D4E3EE;font-size:16px;line-height:1.7;">
                        Si has sido tú, puedes crear una nueva contraseña desde el botón inferior. Por seguridad, el enlace solo funciona una vez y durante un tiempo limitado.
                      </p>
                      <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 0 24px;">
                        <tr>
                          <td style="border-radius:999px;background:linear-gradient(135deg,#00D1FF,#00F5D4);box-shadow:0 12px 34px rgba(0,209,255,0.32);">
                            <a href="{escape(reset_url)}" style="display:inline-block;padding:15px 26px;border-radius:999px;color:#04101C;font-size:15px;font-weight:800;text-decoration:none;font-family:'Space Grotesk',Inter,Segoe UI,Arial,sans-serif;">
                              Restablecer contraseña
                            </a>
                          </td>
                        </tr>
                      </table>
                      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 22px;border:1px solid rgba(255,255,255,0.08);border-radius:16px;background:rgba(255,255,255,0.04);">
                        <tr>
                          <td style="padding:16px 18px;">
                            <p style="margin:0 0 8px;color:#F0F4F8;font-size:14px;font-weight:700;">Detalles de seguridad</p>
                            <p style="margin:0;color:#8FA3B4;font-size:14px;line-height:1.65;">
                              Este enlace expirará en <strong style="color:#F0F4F8;">{escape(expires_text)}</strong>.<br>
                              Dominio seguro: <strong style="color:#00D1FF;">{escape(reset_domain)}</strong>
                            </p>
                          </td>
                        </tr>
                      </table>
                      <p style="margin:0 0 16px;color:#8FA3B4;font-size:14px;line-height:1.7;">
                        Si no has solicitado este cambio, puedes ignorar este mensaje. Tu contraseña actual no se modificará.
                      </p>
                      <p style="margin:0;color:#8FA3B4;font-size:14px;line-height:1.7;">
                        Si tienes problemas, contacta con soporte en
                        <a href="mailto:{escape(support_email)}" style="color:#00D1FF;text-decoration:none;font-weight:700;">{escape(support_email)}</a>.
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 8px 0;text-align:center;color:#637C8E;font-size:12px;line-height:1.6;">
                <p style="margin:0 0 6px;">Vantelia · IA y automatización para empresas</p>
                <p style="margin:0;">(c) {current_year} Vantelia. Todos los derechos reservados.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
    _send_email_message(user["email"], subject, text_body, html_body)


def _send_checkout_welcome_email(
    *,
    to_email: str,
    display_name: str,
    company_name: str,
    cliente_id: str,
    ai_name: str,
    plan: str,
    billing_period: str,
    subscription_id: str,
    temporary_password: str,
    request: Optional[Request] = None,
) -> None:
    access_url = security._platform_access_url(request)
    base_url = (textnorm._preferred_public_base_url(request) or settings.APP_BASE_URL or "https://app.vantelia.es").rstrip("/")
    logo_url = f"{base_url}/brand-assets/Logo_1_sin_resplandor.png"
    support_email = settings.PORTAL_SUPPORT_EMAIL or settings.DEFAULT_VANTELIA_SUPPORT_EMAIL
    current_year = timeutils._utc_now().year
    clean_name = textnorm._sanitize_text(display_name) or textnorm._sanitize_text(company_name) or "Cliente"
    clean_company = textnorm._sanitize_text(company_name) or clean_name
    clean_ai_name = textnorm._sanitize_text(ai_name) or "Asistente Vantelia"
    plan_label = clients._plan_limits(plan).get("label") or plan.title()
    period_label = "mensual" if billing_period == "monthly" else "anual"
    subject = "Tu alta en Vantelia esta lista"

    text_body = (
        f"Hola {clean_name},\n\n"
        "Gracias por contratar Vantelia. Hemos creado tu cliente y tu acceso a la plataforma.\n\n"
        "Resumen de la compra:\n"
        f"- Empresa: {clean_company}\n"
        f"- Cliente interno: {cliente_id}\n"
        f"- IA: {clean_ai_name}\n"
        f"- Plan: {plan_label} ({period_label})\n"
        f"- Suscripcion Stripe: {subscription_id or '-'}\n\n"
        "Acceso a la plataforma:\n"
        f"- Email: {to_email}\n"
        f"- Contrasena temporal: {temporary_password}\n"
        f"- URL: {access_url}\n\n"
        "Te recomendamos cambiar la contrasena despues del primer acceso.\n\n"
        f"Soporte: {support_email}\n\n"
        "Vantelia\n"
        f"(c) {current_year} Vantelia. Todos los derechos reservados.\n"
    )
    html_body = f"""<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <meta name="supported-color-schemes" content="light">
    <title>Tu alta en Vantelia esta lista</title>
  </head>
  <body bgcolor="#0B132B" style="margin:0;padding:0;background-color:#0B132B;background:#0B132B;font-family:Inter,Segoe UI,Arial,sans-serif;color:#F0F4F8;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#0B132B" style="width:100%;background-color:#0B132B;background:#0B132B;">
      <tr>
        <td align="center" bgcolor="#0B132B" style="padding:28px 14px;background-color:#0B132B;background:#0B132B;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#0B132B" style="width:100%;max-width:660px;border-collapse:separate;border-spacing:0;background-color:#0B132B;background:#0B132B;">
            <tr>
              <td style="padding:0 0 18px;text-align:center;">
                <img src="{escape(logo_url)}" width="148" alt="Vantelia" style="display:inline-block;width:148px;max-width:60%;height:auto;border:0;">
              </td>
            </tr>
            <tr>
              <td style="border:1px solid rgba(0,209,255,0.22);border-radius:24px;overflow:hidden;background:#08102A;box-shadow:0 28px 70px rgba(0,0,0,0.38);">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                  <tr>
                    <td style="padding:34px 30px 22px;background:linear-gradient(135deg,rgba(0,209,255,0.18),rgba(0,245,212,0.08) 46%,rgba(8,16,42,0.92));">
                      <div style="display:inline-block;padding:7px 12px;border:1px solid rgba(0,209,255,0.30);border-radius:999px;background:rgba(0,209,255,0.10);color:#00D1FF;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;">
                        Alta completada
                      </div>
                      <h1 style="margin:18px 0 0;font-family:'Space Grotesk',Inter,Segoe UI,Arial,sans-serif;font-size:30px;line-height:1.12;color:#FFFFFF;font-weight:700;">
                        Tu acceso a Vantelia esta listo
                      </h1>
                      <p style="margin:12px 0 0;color:#D4E3EE;font-size:16px;line-height:1.65;">
                        Hola {escape(clean_name)}, hemos creado el cliente de {escape(clean_company)} y ya puedes entrar en la plataforma.
                      </p>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:30px;">
                      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 22px;border:1px solid rgba(255,255,255,0.08);border-radius:16px;background:rgba(255,255,255,0.04);">
                        <tr>
                          <td style="padding:16px 18px;">
                            <p style="margin:0 0 10px;color:#F0F4F8;font-size:15px;font-weight:800;">Resumen de la compra</p>
                            <p style="margin:0;color:#D4E3EE;font-size:14px;line-height:1.75;">
                              Empresa: <strong style="color:#FFFFFF;">{escape(clean_company)}</strong><br>
                              IA: <strong style="color:#FFFFFF;">{escape(clean_ai_name)}</strong><br>
                              Plan: <strong style="color:#FFFFFF;">{escape(str(plan_label))} ({escape(period_label)})</strong><br>
                              Cliente interno: <strong style="color:#00D1FF;">{escape(cliente_id)}</strong><br>
                              Suscripcion: <strong style="color:#FFFFFF;">{escape(subscription_id or "-")}</strong>
                            </p>
                          </td>
                        </tr>
                      </table>
                      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 24px;border:1px solid rgba(0,209,255,0.20);border-radius:16px;background:rgba(0,209,255,0.07);">
                        <tr>
                          <td style="padding:16px 18px;">
                            <p style="margin:0 0 10px;color:#F0F4F8;font-size:15px;font-weight:800;">Credenciales temporales</p>
                            <p style="margin:0;color:#D4E3EE;font-size:14px;line-height:1.75;">
                              Email: <strong style="color:#FFFFFF;">{escape(to_email)}</strong><br>
                              Contrasena temporal: <strong style="color:#00D1FF;">{escape(temporary_password)}</strong>
                            </p>
                          </td>
                        </tr>
                      </table>
                      <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 0 22px;">
                        <tr>
                          <td style="border-radius:999px;background:linear-gradient(135deg,#00D1FF,#00F5D4);box-shadow:0 12px 34px rgba(0,209,255,0.32);">
                            <a href="{escape(access_url)}" style="display:inline-block;padding:15px 26px;border-radius:999px;color:#04101C;font-size:15px;font-weight:800;text-decoration:none;font-family:'Space Grotesk',Inter,Segoe UI,Arial,sans-serif;">
                              Acceder a la plataforma
                            </a>
                          </td>
                        </tr>
                      </table>
                      <p style="margin:0 0 16px;color:#8FA3B4;font-size:14px;line-height:1.7;">
                        Por seguridad, cambia la contrasena despues del primer acceso.
                      </p>
                      <p style="margin:0;color:#8FA3B4;font-size:14px;line-height:1.7;">
                        Soporte:
                        <a href="mailto:{escape(support_email)}" style="color:#00D1FF;text-decoration:none;font-weight:700;">{escape(support_email)}</a>.
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 8px 0;text-align:center;color:#637C8E;font-size:12px;line-height:1.6;">
                <p style="margin:0 0 6px;">Vantelia - IA y automatizacion para empresas</p>
                <p style="margin:0;">(c) {current_year} Vantelia. Todos los derechos reservados.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
    _send_email_message(to_email, subject, text_body, html_body)


def _send_payment_failed_emails(
    *,
    cliente_id: str,
    customer_email: str,
    company_name: str,
    plan: str,
    amount_due_eur: str,
    attempt_count: int,
    next_attempt_iso: str,
    hosted_invoice_url: str,
    customer_id: str,
    subscription_id: str,
) -> None:
    plan_label = clients._plan_limits(plan).get("label") or plan.title() or "-"
    next_attempt_label = next_attempt_iso or "Sin nuevo intento programado"
    invoice_link = hosted_invoice_url or "https://app.vantelia.es/portal"
    support_email = settings.PORTAL_SUPPORT_EMAIL or settings.DEFAULT_VANTELIA_SUPPORT_EMAIL or "soporte@vantelia.es"

    if customer_email:
        subject_c = "Vantelia: tu pago no se ha podido procesar"
        text_c = (
            f"Hola,\n\n"
            f"Hemos intentado cobrar la cuota del plan {plan_label} de Vantelia y la operacion no se ha podido completar.\n\n"
            f"Importe: {amount_due_eur} EUR\n"
            f"Intento numero: {attempt_count}\n"
            f"Proximo reintento: {next_attempt_label}\n\n"
            f"Para evitar la suspension del servicio, actualiza el metodo de pago desde el portal de facturacion:\n"
            f"{invoice_link}\n\n"
            f"Si tienes dudas, escribenos a {support_email}.\n\n"
            f"Vantelia\n"
        )
        html_c = (
            f"<h2>Pago no completado</h2>"
            f"<p>Hemos intentado cobrar la cuota del plan <strong>{escape(str(plan_label))}</strong> y la operacion no se ha podido completar.</p>"
            f"<table cellpadding='6' style='border-collapse:collapse'>"
            f"<tr><td><strong>Importe</strong></td><td>{escape(amount_due_eur)} EUR</td></tr>"
            f"<tr><td><strong>Intento</strong></td><td>{escape(str(attempt_count))}</td></tr>"
            f"<tr><td><strong>Proximo reintento</strong></td><td>{escape(next_attempt_label)}</td></tr>"
            f"</table>"
            f"<p>Para evitar la suspension del servicio, actualiza el metodo de pago desde el portal de facturacion:</p>"
            f"<p><a href='{escape(invoice_link)}'>Actualizar pago</a></p>"
            f"<p>Si tienes dudas, escribenos a <a href='mailto:{escape(support_email)}'>{escape(support_email)}</a>.</p>"
        )
        try:
            _send_email_message(customer_email, subject_c, text_c, html_c)
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("No se pudo enviar aviso de pago fallido a %s: %s", customer_email, exc)

    if settings.CONSULTA_NOTIFICATION_EMAIL:
        subject_a = f"Pago fallido Vantelia: {company_name or cliente_id} ({plan_label})"
        text_a = (
            f"Pago fallido en Stripe.\n\n"
            f"Cliente: {company_name or cliente_id} ({cliente_id})\n"
            f"Email contacto: {customer_email or '-'}\n"
            f"Plan: {plan_label}\n"
            f"Importe: {amount_due_eur} EUR\n"
            f"Intento: {attempt_count}\n"
            f"Proximo reintento: {next_attempt_label}\n"
            f"Stripe customer: {customer_id or '-'}\n"
            f"Stripe subscription: {subscription_id or '-'}\n"
            f"Hosted invoice: {invoice_link}\n"
        )
        html_a = (
            f"<h2>Pago fallido Stripe</h2>"
            f"<table cellpadding='6' style='border-collapse:collapse'>"
            f"<tr><td><strong>Cliente</strong></td><td>{escape(company_name or cliente_id)} ({escape(cliente_id)})</td></tr>"
            f"<tr><td><strong>Email contacto</strong></td><td>{escape(customer_email or '-')}</td></tr>"
            f"<tr><td><strong>Plan</strong></td><td>{escape(str(plan_label))}</td></tr>"
            f"<tr><td><strong>Importe</strong></td><td>{escape(amount_due_eur)} EUR</td></tr>"
            f"<tr><td><strong>Intento</strong></td><td>{escape(str(attempt_count))}</td></tr>"
            f"<tr><td><strong>Proximo reintento</strong></td><td>{escape(next_attempt_label)}</td></tr>"
            f"<tr><td><strong>Stripe customer</strong></td><td>{escape(customer_id or '-')}</td></tr>"
            f"<tr><td><strong>Stripe subscription</strong></td><td>{escape(subscription_id or '-')}</td></tr>"
            f"<tr><td><strong>Hosted invoice</strong></td><td><a href='{escape(invoice_link)}'>{escape(invoice_link)}</a></td></tr>"
            f"</table>"
        )
        try:
            _send_email_message(settings.CONSULTA_NOTIFICATION_EMAIL, subject_a, text_a, html_a)
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("No se pudo enviar aviso pago fallido admin: %s", exc)


def _smtp_configured() -> bool:
    return bool(_smtp_host() and _smtp_from_email())


def _system_setting_get(key: str, default: str = "") -> str:
    try:
        with db._get_db_connection() as connection:
            row = connection.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"] or "") if row else default
    except Exception:  # noqa: BLE001
        return default


def _system_setting_set(key: str, value: str) -> None:
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO system_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, now),
        )
        connection.commit()


def _normalize_sender_email(value: str, fallback: str = "") -> str:
    return textnorm._normalize_email(parseaddr(str(value or "").strip())[1] or fallback)


def _smtp_from_email() -> str:
    return _normalize_sender_email(
        _system_setting_get("smtp_from_email", settings.SMTP_FROM_EMAIL),
        settings.DEFAULT_VANTELIA_FROM_EMAIL,
    )


def _smtp_from_name() -> str:
    return textnorm._sanitize_text(
        _system_setting_get("smtp_from_name", settings.SMTP_FROM_NAME),
    ) or "Vantelia"


def _smtp_reply_to() -> str:
    return _normalize_sender_email(
        _system_setting_get("smtp_reply_to", settings.SMTP_REPLY_TO),
        settings.DEFAULT_VANTELIA_SUPPORT_EMAIL,
    )


def _smtp_host() -> str:
    return textnorm._sanitize_text(_system_setting_get("smtp_host", settings.SMTP_HOST))


def _smtp_port() -> int:
    raw = textnorm._sanitize_text(_system_setting_get("smtp_port", str(settings.SMTP_PORT)))
    try:
        port = int(raw)
    except (TypeError, ValueError):
        port = settings.SMTP_PORT
    return max(1, min(65535, port))


def _smtp_username() -> str:
    return textnorm._sanitize_text(_system_setting_get("smtp_username", settings.SMTP_USERNAME))


def _smtp_password_encrypted() -> str:
    return _system_setting_get("smtp_password_encrypted", "")


def _smtp_password() -> str:
    encrypted = _smtp_password_encrypted()
    if encrypted:
        return security._decrypt_channel_secret(encrypted)
    return settings.SMTP_PASSWORD


def _smtp_starttls() -> bool:
    raw = textnorm._sanitize_text(_system_setting_get("smtp_starttls", "1" if settings.SMTP_STARTTLS else "0")).lower()
    return raw in {"1", "true", "yes", "on"}


def _smtp_public_settings() -> Dict[str, str]:
    return {
        "host": _smtp_host(),
        "port": str(_smtp_port()),
        "username": _smtp_username(),
        "starttls": "1" if _smtp_starttls() else "0",
        "from_email": _smtp_from_email(),
        "from_name": _smtp_from_name(),
        "reply_to": _smtp_reply_to(),
        "password_configured": "1" if bool(_smtp_password_encrypted() or settings.SMTP_PASSWORD) else "0",
    }


def _smtp_update_public_settings(
    *,
    from_email: str,
    from_name: str = "",
    reply_to: str = "",
    host: str = "",
    port: int = 587,
    username: str = "",
    password: str = "",
    starttls: bool = True,
) -> Dict[str, str]:
    clean_from = _normalize_sender_email(from_email, "")
    if not clean_from:
        raise ValueError("Indica un email remitente valido.")
    clean_host = textnorm._sanitize_text(host or settings.SMTP_HOST)
    if not clean_host:
        raise ValueError("Indica el servidor SMTP de respaldo.")
    clean_port = max(1, min(65535, int(port or settings.SMTP_PORT)))
    clean_username = textnorm._sanitize_text(username)
    if clean_username and not (password or _smtp_password_encrypted() or settings.SMTP_PASSWORD):
        raise ValueError("Indica la contrasena SMTP para ese usuario.")
    clean_name = textnorm._sanitize_text(from_name or settings.SMTP_FROM_NAME) or "Vantelia"
    clean_reply = _normalize_sender_email(reply_to, clean_from)
    _system_setting_set("smtp_host", clean_host)
    _system_setting_set("smtp_port", str(clean_port))
    _system_setting_set("smtp_username", clean_username)
    _system_setting_set("smtp_starttls", "1" if starttls else "0")
    _system_setting_set("smtp_from_email", clean_from)
    _system_setting_set("smtp_from_name", clean_name)
    _system_setting_set("smtp_reply_to", clean_reply)
    if password:
        _system_setting_set("smtp_password_encrypted", security._encrypt_channel_secret(password))
    return _smtp_public_settings()


def _gmail_encrypt(value: str) -> str:
    fernet = security._gmail_fernet()
    if not fernet:
        raise RuntimeError("Configura GMAIL_TOKEN_ENCRYPTION_KEY o ADMIN_API_TOKEN para cifrar tokens Gmail.")
    return fernet.encrypt(str(value or "").encode("utf-8")).decode("ascii")


def _gmail_decrypt(value: str) -> str:
    if not value:
        return ""
    fernet = security._gmail_fernet()
    if not fernet:
        raise RuntimeError("No se puede descifrar la conexion Gmail: falta la clave de cifrado.")
    try:
        return fernet.decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise RuntimeError("No se puede descifrar la conexion Gmail con la clave actual.") from exc


def _gmail_connection(cliente_id: str = "") -> Optional[sqlite3.Row]:
    connection_id = cliente_id or "default"
    with db._get_db_connection() as connection:
        return connection.execute("SELECT * FROM gmail_connections WHERE id = ?", (connection_id,)).fetchone()


def _gmail_connected(cliente_id: str = "") -> bool:
    row = _gmail_connection(cliente_id)
    return bool(row and row["refresh_token_encrypted"])


def _email_delivery_configured(cliente_id: str = "") -> bool:
    client_gmail_connected = bool(cliente_id and _gmail_connected(cliente_id))
    global_gmail_connected = _gmail_connected()
    gmail_ready = security._gmail_oauth_configured() and (client_gmail_connected or global_gmail_connected)
    if settings.EMAIL_SEND_PROVIDER == "gmail":
        return gmail_ready
    if settings.EMAIL_SEND_PROVIDER == "smtp":
        return _smtp_configured()
    return gmail_ready or _smtp_configured()


def _gmail_save_tokens(token_data: Dict[str, Any], email: str, scopes: str = "", cliente_id: str = "") -> None:
    connection_id = cliente_id or "default"
    current = _gmail_connection(cliente_id)
    access_token = str(token_data.get("access_token") or "").strip()
    refresh_token = str(token_data.get("refresh_token") or "").strip()
    if not refresh_token and current:
        refresh_token_encrypted = current["refresh_token_encrypted"]
    elif refresh_token:
        refresh_token_encrypted = _gmail_encrypt(refresh_token)
    else:
        raise RuntimeError("Google no devolvio refresh_token. Revoca el acceso y vuelve a conectar Gmail.")
    expires_in = max(60, int(token_data.get("expires_in") or 3600))
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO gmail_connections (
                id, cliente_id, email, access_token_encrypted, refresh_token_encrypted, expires_at,
                scopes, created_at, updated_at, last_used_at, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', '')
            ON CONFLICT(id) DO UPDATE SET
                email=excluded.email,
                access_token_encrypted=excluded.access_token_encrypted,
                refresh_token_encrypted=excluded.refresh_token_encrypted,
                expires_at=excluded.expires_at,
                scopes=excluded.scopes,
                updated_at=excluded.updated_at,
                last_error=''
            """,
            (
                connection_id,
                cliente_id,
                textnorm._normalize_email(email),
                _gmail_encrypt(access_token),
                refresh_token_encrypted,
                time.time() + expires_in,
                scopes or str(token_data.get("scope") or ""),
                now_iso,
                now_iso,
            ),
        )
        connection.commit()


def _gmail_access_token(cliente_id: str = "") -> Tuple[str, sqlite3.Row]:
    row = _gmail_connection(cliente_id)
    if not row or not row["refresh_token_encrypted"]:
        raise RuntimeError("Gmail no esta conectado.")
    if row["access_token_encrypted"] and float(row["expires_at"] or 0) > time.time() + 60:
        return _gmail_decrypt(row["access_token_encrypted"]), row
    refresh_token = _gmail_decrypt(row["refresh_token_encrypted"])
    with httpx.Client(timeout=20.0) as client:
        response = client.post(
            settings.GOOGLE_OAUTH_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        token_data = response.json()
    _gmail_save_tokens(token_data, row["email"], row["scopes"], cliente_id)
    fresh = _gmail_connection(cliente_id)
    if not fresh:
        raise RuntimeError("No se pudo guardar el token renovado de Gmail.")
    return _gmail_decrypt(fresh["access_token_encrypted"]), fresh


def _gmail_send_message(message: EmailMessage, cliente_id: str = "") -> None:
    if not security._gmail_oauth_configured():
        raise RuntimeError("Google OAuth para Gmail no esta configurado.")
    access_token, connection_row = _gmail_access_token(cliente_id)
    connected_email = textnorm._normalize_email(connection_row["email"])
    from_name, from_email = parseaddr(str(message.get("From") or ""))
    if connected_email and textnorm._normalize_email(from_email) != connected_email:
        if message.get("From"):
            message.replace_header("From", formataddr((from_name or settings.SMTP_FROM_NAME or "Vantelia", connected_email)))
        else:
            message["From"] = formataddr((settings.SMTP_FROM_NAME or "Vantelia", connected_email))
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    try:
        with httpx.Client(timeout=25.0) as client:
            response = client.post(
                settings.GOOGLE_GMAIL_SEND_URL,
                json={"raw": raw},
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            response.raise_for_status()
    except Exception as exc:
        with db._get_db_connection() as db_row:
            db_row.execute(
                "UPDATE gmail_connections SET last_error = ?, updated_at = ? WHERE id = ?",
                (str(exc)[:500], timeutils._utc_now_iso(), cliente_id or "default"),
            )
            db_row.commit()
        raise
    with db._get_db_connection() as db_row:
        db_row.execute(
            "UPDATE gmail_connections SET last_used_at = ?, last_error = '' WHERE id = ?",
            (timeutils._utc_now_iso(), cliente_id or "default"),
        )
        db_row.commit()


def _smtp_send_message(message: EmailMessage) -> None:
    if not _smtp_configured():
        raise RuntimeError("El sistema SMTP no esta configurado. Revisa SMTP_HOST y SMTP_FROM_EMAIL.")
    with smtplib.SMTP(_smtp_host(), _smtp_port(), timeout=20) as smtp:
        smtp.ehlo()
        if _smtp_starttls():
            smtp.starttls()
            smtp.ehlo()
        username = _smtp_username()
        if username:
            smtp.login(username, _smtp_password())
        smtp.send_message(message)


def _send_email_object(message: EmailMessage, cliente_id: str = "") -> None:
    if settings.EMAIL_SEND_PROVIDER not in {"auto", "gmail", "smtp"}:
        raise RuntimeError("EMAIL_SEND_PROVIDER debe ser auto, gmail o smtp.")
    client_gmail_connected = bool(cliente_id and _gmail_connected(cliente_id))
    gmail_ready = security._gmail_oauth_configured() and (client_gmail_connected or _gmail_connected())
    gmail_target = cliente_id if client_gmail_connected else ""
    if settings.EMAIL_SEND_PROVIDER == "gmail" and not gmail_ready:
        raise RuntimeError("EMAIL_SEND_PROVIDER=gmail pero Gmail no esta conectado.")
    if settings.EMAIL_SEND_PROVIDER in {"auto", "gmail"} and gmail_ready:
        try:
            if gmail_target:
                _gmail_send_message(copy.deepcopy(message), gmail_target)
            else:
                _gmail_send_message(copy.deepcopy(message))
            return
        except Exception as exc:
            if settings.EMAIL_SEND_PROVIDER == "gmail" or not _smtp_configured():
                raise
            settings.logger.warning("Envio Gmail fallo; usando respaldo SMTP: %s", exc)
    _smtp_send_message(message)


def _email_sender() -> str:
    from_name = _smtp_from_name()
    from_email = _smtp_from_email()
    if from_name:
        return formataddr((from_name, from_email))
    return from_email


def _send_email_message(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str = "",
    reply_to: Optional[str] = None,
    cliente_id: str = "",
) -> None:
    if not _email_delivery_configured(cliente_id):
        raise RuntimeError("El sistema de correo no esta configurado. Conecta Gmail o configura SMTP.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _email_sender()
    message["To"] = to_email
    reply_addr = (reply_to or _smtp_reply_to() or "").strip()
    if reply_addr:
        message["Reply-To"] = reply_addr
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    _send_email_object(message, cliente_id)


def _client_gmail_connection(cliente_id: str) -> Optional[sqlite3.Row]:
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM client_oauth_connections WHERE cliente_id=? AND provider='gmail_oauth'",
            (cliente_id,),
        ).fetchone()


def _client_gmail_access_token(cliente_id: str, connection_row: sqlite3.Row) -> str:
    access_token = security._decrypt_channel_secret(connection_row["access_token_encrypted"])
    expires_at = timeutils._from_utc_iso(connection_row["expires_at"] or "")
    if access_token and expires_at and expires_at > timeutils._utc_now() + timedelta(seconds=60):
        return access_token
    refresh_token = security._decrypt_channel_secret(connection_row["refresh_token_encrypted"])
    if not refresh_token:
        raise RuntimeError("Google requiere volver a conectar la cuenta.")
    response = httpx.post(
        settings.GOOGLE_OAUTH_TOKEN_URL,
        data={
            "client_id": settings.GOOGLE_GMAIL_CLIENT_ID,
            "client_secret": settings.GOOGLE_GMAIL_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    response.raise_for_status()
    token_data = response.json()
    access_token = str(token_data.get("access_token", ""))
    if not access_token:
        raise RuntimeError("Google no devolvio un token de acceso.")
    expires = timeutils._utc_now() + timedelta(seconds=int(token_data.get("expires_in", 3600)))
    with db._get_db_connection() as connection:
        connection.execute(
            """
            UPDATE client_oauth_connections
            SET access_token_encrypted=?, expires_at=?, status='active', last_error='', updated_at=?
            WHERE cliente_id=? AND provider='gmail_oauth'
            """,
            (security._encrypt_channel_secret(access_token), expires.isoformat(), timeutils._utc_now_iso(), cliente_id),
        )
        connection.commit()
    return access_token


def _send_gmail_message(
    cliente_id: str, connection_row: sqlite3.Row, to_email: str, subject: str,
    text_body: str, html_body: str = "", reply_to: Optional[str] = None,
) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = connection_row["account_email"]
    message["To"] = to_email
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
    response = httpx.post(
        settings.GOOGLE_GMAIL_SEND_URL,
        json={"raw": raw},
        headers={"Authorization": f"Bearer {_client_gmail_access_token(cliente_id, connection_row)}"},
        timeout=20,
    )
    response.raise_for_status()


def _client_smtp_configured(channel_settings: sqlite3.Row) -> bool:
    return bool(
        str(channel_settings["email_smtp_host"] or "").strip()
        and str(channel_settings["email_smtp_from_email"] or "").strip()
    )


def _client_smtp_password(channel_settings: sqlite3.Row) -> str:
    encrypted = str(channel_settings["email_smtp_password_encrypted"] or "")
    return security._decrypt_channel_secret(encrypted) if encrypted else ""


def _send_client_smtp_message(
    cliente_id: str,
    channel_settings: sqlite3.Row,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str = "",
    reply_to: Optional[str] = None,
) -> None:
    if not _client_smtp_configured(channel_settings):
        raise RuntimeError("El SMTP propio del cliente no esta configurado.")
    host = str(channel_settings["email_smtp_host"] or "").strip()
    port = int(channel_settings["email_smtp_port"] or 587)
    username = str(channel_settings["email_smtp_username"] or "").strip()
    password = _client_smtp_password(channel_settings)
    from_email = _normalize_sender_email(channel_settings["email_smtp_from_email"], "")
    from_name = textnorm._sanitize_text(channel_settings["email_smtp_from_name"] or "") or from_email
    reply_addr = (reply_to or _normalize_sender_email(channel_settings["email_smtp_reply_to"], "") or from_email).strip()

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((from_name, from_email))
    message["To"] = to_email
    if reply_addr:
        message["Reply-To"] = reply_addr
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        if bool(channel_settings["email_smtp_starttls"]):
            smtp.starttls()
            smtp.ehlo()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE client_channel_settings SET last_error='', updated_at=? WHERE cliente_id=?",
            (timeutils._utc_now_iso(), cliente_id),
        )
        connection.commit()


def _send_client_email(
    cliente_id: str, to_email: str, subject: str, text_body: str,
    html_body: str = "", reply_to: Optional[str] = None,
) -> str:
    channel_settings = security._ensure_channel_settings(cliente_id)
    provider = channel_settings["email_provider"] or "vantelia_smtp"
    if provider == "gmail_oauth":
        connection_row = _client_gmail_connection(cliente_id)
        if connection_row and connection_row["status"] == "active":
            try:
                _send_gmail_message(cliente_id, connection_row, to_email, subject, text_body, html_body, reply_to)
                security._channel_audit(cliente_id, "email", "send", provider, True)
                return provider
            except Exception as exc:  # noqa: BLE001
                error = str(exc)[:500]
                with db._get_db_connection() as connection:
                    connection.execute(
                        "UPDATE client_oauth_connections SET status='error', last_error=?, updated_at=? WHERE cliente_id=? AND provider='gmail_oauth'",
                        (error, timeutils._utc_now_iso(), cliente_id),
                    )
                    connection.commit()
                security._channel_audit(cliente_id, "email", "send_failed", provider, False, error)
                if not channel_settings["email_fallback_enabled"]:
                    raise
        elif not channel_settings["email_fallback_enabled"]:
            raise RuntimeError("La cuenta de Google remitente no esta disponible.")
    elif provider == "client_smtp":
        if _client_smtp_configured(channel_settings):
            try:
                _send_client_smtp_message(cliente_id, channel_settings, to_email, subject, text_body, html_body, reply_to)
                security._channel_audit(cliente_id, "email", "send", provider, True)
                return provider
            except Exception as exc:  # noqa: BLE001
                error = str(exc)[:500]
                with db._get_db_connection() as connection:
                    connection.execute(
                        "UPDATE client_channel_settings SET last_error=?, updated_at=? WHERE cliente_id=?",
                        (error, timeutils._utc_now_iso(), cliente_id),
                    )
                    connection.commit()
                security._channel_audit(cliente_id, "email", "send_failed", provider, False, error)
                if not channel_settings["email_fallback_enabled"]:
                    raise
        elif not channel_settings["email_fallback_enabled"]:
            raise RuntimeError("El SMTP propio del cliente no esta configurado.")
    _send_email_message(to_email, subject, text_body, html_body, reply_to)
    security._channel_audit(cliente_id, "email", "send", "vantelia_smtp", True)
    return "vantelia_smtp"


def _gmail_channel_configured() -> bool:
    return bool(
        settings.GOOGLE_GMAIL_CLIENT_ID and settings.GOOGLE_GMAIL_CLIENT_SECRET
        and settings.GOOGLE_GMAIL_REDIRECT_URL and settings.OAUTH_TOKEN_ENCRYPTION_KEY
    )


def _gmail_channel_state_create(cliente_id: str, user_id: str) -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    raw_state = secrets.token_urlsafe(32)
    signature = hmac.new(
        settings.OAUTH_TOKEN_ENCRYPTION_KEY.encode("utf-8"), raw_state.encode("ascii"), hashlib.sha256
    ).hexdigest()
    state = f"{raw_state}.{signature}"
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_channel_oauth_states
                (state_hash, cliente_id, user_id, provider, code_verifier_encrypted, created_at)
            VALUES (?, ?, ?, 'gmail_oauth', ?, ?)
            """,
            (hashlib.sha256(state.encode()).hexdigest(), cliente_id, user_id, security._encrypt_channel_secret(verifier), time.time()),
        )
        connection.execute("DELETE FROM client_channel_oauth_states WHERE created_at < ?", (time.time() - 600,))
        connection.commit()
    return state, verifier


def _gmail_channel_state_consume(state: str, cliente_id: str, user_id: str) -> str:
    parts = str(state or "").rsplit(".", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Estado OAuth invalido o caducado.")
    expected = hmac.new(
        settings.OAUTH_TOKEN_ENCRYPTION_KEY.encode("utf-8"), parts[0].encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not secrets.compare_digest(parts[1], expected):
        raise HTTPException(status_code=400, detail="Estado OAuth invalido o caducado.")
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM client_channel_oauth_states WHERE state_hash=?", (state_hash,)
        ).fetchone()
        if row:
            connection.execute("DELETE FROM client_channel_oauth_states WHERE state_hash=?", (state_hash,))
            connection.commit()
    if (
        not row or row["cliente_id"] != cliente_id or row["user_id"] != user_id
        or time.time() - float(row["created_at"]) > 600
    ):
        raise HTTPException(status_code=400, detail="Estado OAuth invalido o caducado.")
    return security._decrypt_channel_secret(row["code_verifier_encrypted"])




def _channel_settings_public(cliente_id: str) -> ChannelSettingsResponse:
    channel_settings = security._ensure_channel_settings(cliente_id)
    gmail = _client_gmail_connection(cliente_id)
    sms_mode = channel_settings["sms_mode"] or "vantelia_default"
    if sms_mode == "vantelia_default":
        config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
        sender = settings.TWILIO_SMS_SENDER or (config.get("voice", {}) or {}).get("twilio_phone_number") or settings.TWILIO_DEFAULT_PHONE_NUMBER
        sms_available = bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and sender)
    else:
        sender = channel_settings["sms_sender"] or ""
        sms_available = channel_settings["sms_sender_status"] == "active"
    # SMS es canal de pago (Twilio): gateado a plan Business, como la llamada IA.
    if not clients._plan_feature(cliente_id, "sms_enabled"):
        sms_available = False
    return ChannelSettingsResponse(
        email=ChannelEmailStatus(
            provider=channel_settings["email_provider"] or "vantelia_smtp",
            fallback_enabled=bool(channel_settings["email_fallback_enabled"]),
            connected=bool(gmail and gmail["status"] == "active"),
            account_email=str(gmail["account_email"] or "") if gmail else "",
            account_name=str(gmail["account_name"] or "") if gmail else "",
            status=str(gmail["status"] or "not_connected") if gmail else "not_connected",
            last_error=str(gmail["last_error"] or "") if gmail else "",
            google_configured=_gmail_channel_configured(),
            smtp_configured=_client_smtp_configured(channel_settings),
            smtp_host=str(channel_settings["email_smtp_host"] or ""),
            smtp_port=int(channel_settings["email_smtp_port"] or 587),
            smtp_username=str(channel_settings["email_smtp_username"] or ""),
            smtp_from_email=str(channel_settings["email_smtp_from_email"] or ""),
            smtp_from_name=str(channel_settings["email_smtp_from_name"] or ""),
            smtp_reply_to=str(channel_settings["email_smtp_reply_to"] or ""),
            smtp_starttls=bool(channel_settings["email_smtp_starttls"]),
            smtp_password_configured=bool(channel_settings["email_smtp_password_encrypted"]),
        ),
        sms=ChannelSmsStatus(
            mode=sms_mode,
            sender=str(sender or ""),
            sender_status=str(channel_settings["sms_sender_status"] or "not_configured"),
            available=sms_available,
            last_error=str(channel_settings["last_error"] or ""),
        ),
    )
