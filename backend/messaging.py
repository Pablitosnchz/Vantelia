"""Envio SMS (Twilio) y WhatsApp Cloud API de bajo nivel (refactor F3).

Solo primitivas de envio + validacion de firma Twilio. La logica
conversacional de WhatsApp (flujos/pickers) vive en el dominio de chat.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from typing import Any, Dict, List, Tuple

try:
    from twilio.request_validator import RequestValidator as _TwilioRequestValidator
except ImportError:  # twilio es opcional en dev
    _TwilioRequestValidator = None

import httpx

from backend import appstate, clients, security, settings, textnorm


def _normalize_sms_recipient(to_number: str, *, default_country_code: str = "34") -> str:
    """Normaliza destinatarios SMS a E.164.

    En voz es normal que el cliente dicte un movil nacional sin prefijo ("600...").
    Twilio espera E.164, asi que por defecto asumimos Espana para numeros nacionales
    de 9 digitos que empiezan por 6/7/8/9.
    """
    raw = textnorm._sanitize_text(to_number or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return "+" + digits
    if digits.startswith("00") and len(digits) > 4:
        return "+" + digits[2:]
    if len(digits) == 9 and digits[0] in {"6", "7", "8", "9"}:
        return f"+{default_country_code}{digits}"
    if digits.startswith(default_country_code) and len(digits) >= 11:
        return "+" + digits
    if len(digits) >= 10:
        return "+" + digits
    return ""


async def _send_client_sms(cliente_id: str, to_number: str, body: str) -> bool:
    to_number = _normalize_sms_recipient(to_number)
    if not to_number:
        security._channel_audit(cliente_id, "sms", "send_rejected", "invalid_recipient", False, "Telefono SMS invalido.")
        return False
    # SMS gateado a plan Business (canal de pago Twilio). Defensa en profundidad.
    if not clients._plan_feature(cliente_id, "sms_enabled"):
        security._channel_audit(cliente_id, "sms", "send_rejected", "plan", False, "Plan sin SMS.")
        return False
    channel_settings = security._ensure_channel_settings(cliente_id)
    mode = channel_settings["sms_mode"] or "vantelia_default"
    sender = ""
    account_sid, auth_token = settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN
    if mode in {"twilio_dedicated_number", "twilio_alphanumeric_sender"}:
        if channel_settings["sms_sender_status"] != "active":
            security._channel_audit(cliente_id, "sms", "send_rejected", mode, False, "Remitente no activo.")
            return False
        sender = channel_settings["sms_sender"] or ""
        account_sid = security._decrypt_channel_secret(channel_settings["sms_twilio_account_sid_encrypted"]) or account_sid
        auth_token = security._decrypt_channel_secret(channel_settings["sms_twilio_auth_token_encrypted"]) or auth_token
    else:
        config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
        sender = settings.TWILIO_SMS_SENDER or (config.get("voice", {}) or {}).get("twilio_phone_number") or settings.TWILIO_DEFAULT_PHONE_NUMBER
    if mode == "vantelia_default":
        sent = await _send_twilio_sms(to_number, sender, body)
    else:
        sent = await _send_twilio_sms(to_number, sender, body, account_sid=account_sid, auth_token=auth_token)
    security._channel_audit(cliente_id, "sms", "send" if sent else "send_failed", mode, sent)
    return sent


def _whatsapp_env_value(env_name: str, fallback: str = "") -> str:
    return os.getenv(str(env_name or "").strip(), "").strip() if env_name else fallback.strip()


def _whatsapp_access_token_for_client(cliente_id: str) -> str:
    config = clients._get_client_config(cliente_id)
    configured_env = str(config.get("whatsapp", {}).get("access_token_env", "")).strip()
    return _whatsapp_env_value(configured_env, settings.WHATSAPP_ACCESS_TOKEN)


def _whatsapp_chunks(text: str, *, max_length: int = 3500) -> List[str]:
    cleaned = textnorm._sanitize_text(text, allow_multiline=True)
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


async def _send_whatsapp_payload(
    *,
    cliente_id: str,
    phone_number_id: str,
    payload: Dict[str, Any],
) -> bool:
    access_token = _whatsapp_access_token_for_client(cliente_id)
    if not access_token:
        settings.logger.warning("WhatsApp sin token configurado para %s; respuesta no enviada.", cliente_id)
        return False
    url = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 300:
            settings.logger.error(
                "Error enviando WhatsApp interactive a %s (%s): %s",
                cliente_id,
                response.status_code,
                response.text[:500],
            )
            return False
    return True


async def _send_whatsapp_buttons(
    *,
    cliente_id: str,
    phone_number_id: str,
    to_number: str,
    body: str,
    buttons: List[Tuple[str, str]],
    header: str = "",
    footer: str = "",
) -> bool:
    btns = []
    for btn_id, btn_label in buttons[:3]:
        btns.append({
            "type": "reply",
            "reply": {"id": btn_id[:256], "title": btn_label[:20]},
        })
    interactive: Dict[str, Any] = {
        "type": "button",
        "body": {"text": body[:1024]},
        "action": {"buttons": btns},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    if footer:
        interactive["footer"] = {"text": footer[:60]}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "interactive",
        "interactive": interactive,
    }
    return await _send_whatsapp_payload(
        cliente_id=cliente_id, phone_number_id=phone_number_id, payload=payload,
    )


async def _send_whatsapp_list(
    *,
    cliente_id: str,
    phone_number_id: str,
    to_number: str,
    body: str,
    button_text: str,
    sections: List[Dict[str, Any]],
    header: str = "",
    footer: str = "",
) -> bool:
    interactive: Dict[str, Any] = {
        "type": "list",
        "body": {"text": body[:1024]},
        "action": {"button": button_text[:20], "sections": sections},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    if footer:
        interactive["footer"] = {"text": footer[:60]}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "interactive",
        "interactive": interactive,
    }
    return await _send_whatsapp_payload(
        cliente_id=cliente_id, phone_number_id=phone_number_id, payload=payload,
    )


async def _send_whatsapp_text(
    *,
    cliente_id: str,
    phone_number_id: str,
    to_number: str,
    text: str,
) -> bool:
    access_token = _whatsapp_access_token_for_client(cliente_id)
    if not access_token:
        settings.logger.warning("WhatsApp sin token configurado para %s; respuesta no enviada.", cliente_id)
        return False

    url = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{phone_number_id}/messages"
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
                settings.logger.error(
                    "Error enviando WhatsApp a %s (%s): %s",
                    cliente_id,
                    response.status_code,
                    response.text[:500],
                )
    return delivered


def _voice_twilio_configured() -> bool:
    return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN)


def _twilio_request_valid(url: str, params: Dict[str, str], signature: str) -> bool:
    """Valida X-Twilio-Signature. Usa la libreria twilio si esta disponible;
    si no, replica el algoritmo (HMAC-SHA1 sobre url + params ordenados)."""
    token = settings.TWILIO_AUTH_TOKEN
    if not token or not signature:
        return False
    if _TwilioRequestValidator is not None:
        try:
            return bool(_TwilioRequestValidator(token).validate(url, params, signature))
        except Exception:  # noqa: BLE001
            pass
    data = url + "".join(f"{key}{params[key]}" for key in sorted(params.keys()))
    digest = hmac.new(token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode("ascii")
    try:
        return hmac.compare_digest(expected, signature)
    except Exception:  # noqa: BLE001
        return False


async def _send_twilio_sms(
    to_number: str,
    from_number: str,
    body: str,
    *,
    account_sid: str = "",
    auth_token: str = "",
) -> bool:
    account_sid = account_sid or settings.TWILIO_ACCOUNT_SID
    auth_token = auth_token or settings.TWILIO_AUTH_TOKEN
    if not (account_sid and auth_token and from_number and to_number):
        return False
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                url,
                data={"To": to_number, "From": from_number, "Body": body[:1500]},
                auth=(account_sid, auth_token),
            )
        if resp.status_code >= 300:
            settings.logger.error("[voice] Twilio SMS error (%s): %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[voice] Twilio SMS exception: %s", exc)
        return False


