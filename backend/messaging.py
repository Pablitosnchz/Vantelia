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
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Tuple, Union

try:
    from twilio.request_validator import RequestValidator as _TwilioRequestValidator
except ImportError:  # twilio es opcional en dev
    _TwilioRequestValidator = None

import httpx

from backend import appstate, atencion_contexto, atencion_salidas, clients, security, settings, textnorm


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
    atencion_salidas.tenant_salida_atencion(cliente_id)
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
    if sent:
        atencion_salidas.auditar_salida_conocida_atencion(
            cliente_id, security._channel_audit, cliente_id, "sms", "send", mode, True)
    else:
        security._channel_audit(cliente_id, "sms", "send_failed", mode, False)
    return sent


def _whatsapp_env_value(env_name: str, fallback: str = "") -> str:
    return os.getenv(str(env_name or "").strip(), "").strip() if env_name else fallback.strip()


def _whatsapp_access_token_for_client(cliente_id: str) -> str:
    # 1) Token PROPIO del negocio (alta self-service por Embedded Signup): manda
    # sobre el global, porque su numero vive en SU cuenta de Meta, no en la nuestra.
    if cliente_id:
        try:
            from backend import wa_onboarding

            propio = wa_onboarding.account_token(cliente_id)
            if propio:
                return propio
        except Exception as exc:  # noqa: BLE001 - nunca debe impedir el envio
            settings.logger.debug("No se pudo leer el token propio de %s: %s", cliente_id, exc)
    # El numero de demo compartido responde antes de saber con que tenant habla el
    # prospecto (mensaje de ayuda sin codigo): ahi se cae al token global.
    try:
        config = clients._get_client_config(cliente_id)
    except Exception:  # noqa: BLE001
        return settings.WHATSAPP_ACCESS_TOKEN.strip()
    configured_env = str(config.get("whatsapp", {}).get("access_token_env", "")).strip()
    return _whatsapp_env_value(configured_env, settings.WHATSAPP_ACCESS_TOKEN)


def _whatsapp_chunks(text: str, *, max_length: int = 3500) -> List[str]:
    # Punto unico de salida de texto a WhatsApp: aqui se traduce el Markdown del
    # modelo (`**negrita**`) al formato de WhatsApp (`*negrita*`).
    cleaned = textnorm._markdown_to_whatsapp(textnorm._sanitize_text(text, allow_multiline=True))
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


@dataclass(frozen=True)
class WhatsAppSendResult:
    """Aceptación del proveedor, nunca acreditación de entrega al teléfono.

    message_ids conserva fragmentos aceptados aunque después se pierda otro.
    El consumidor detallado debe decidir por estado, nunca por truthiness.
    """

    estado: str
    provider_message_id: str = ""
    motivo: str = ""
    http_status: int = 0
    message_ids: Tuple[str, ...] = ()
    error_code: str = ""
    template_name: str = ""

    def __bool__(self):
        raise TypeError("Consulta el estado del resultado de WhatsApp explícitamente")


class WhatsAppDeliveryUnknown(RuntimeError):
    """Compatibilidad booleana: desconocido no puede activar un fallback por False."""

    def __init__(self, resultado: WhatsAppSendResult):
        self.resultado = resultado
        super().__init__(resultado.motivo or "Resultado de WhatsApp desconocido")


def _whatsapp_result_for_caller(resultado: WhatsAppSendResult, detailed: bool):
    if detailed:
        return resultado
    if resultado.estado == "desconocido":
        raise WhatsAppDeliveryUnknown(resultado)
    return resultado.estado == "aceptado"


async def _post_whatsapp_message(
    *,
    cliente_id: str,
    phone_number_id: str,
    payload: Dict[str, Any],
    _atencion_fragmento: int = 0,
) -> WhatsAppSendResult:
    """Único POST de mensajes Meta. La respuesta ambigua no autoriza reenvío.

    Esquema de aceptación: POST /messages, messages[].id, colección oficial Meta:
    https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api
    Los recibos de entrega son otro contrato.
    """
    access_token = _whatsapp_access_token_for_client(cliente_id)
    if not access_token:
        return WhatsAppSendResult("omitido", motivo="WhatsApp sin token configurado")
    if not phone_number_id or not payload.get("to"):
        return WhatsAppSendResult("omitido", motivo="Falta número emisor o destinatario de WhatsApp")
    url = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    wire = atencion_salidas.json_salida_atencion(payload)
    # Los tipos de payload separan un template rechazado de su texto de respaldo;
    # los fragmentos de texto conservan su índice al reintentar el mismo envío.
    base_fragmento = {"text": 0, "template": 1000000, "interactive": 2000000}.get(payload.get("type"), 3000000)
    with atencion_salidas.salida_red_atencion(cliente_id, "whatsapp", base_fragmento + _atencion_fragmento,
            atencion_salidas.payload_salida_atencion(url, wire)) as admision:
        def finalizar_meta_atencion(resultado):
            atencion_salidas.registrar_salida_atencion(admision, resultado.estado)
            if admision is not None and resultado.estado == "desconocido":
                raise atencion_contexto.AtencionDetenida("envio_sin_nueva_admision", "desconocido")
            return resultado

        response = None
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                kwargs = {"json": payload} if admision is None else {"content": wire}
                response = await client.post(url, headers=headers, **kwargs)
        except atencion_contexto.AtencionDetenida:
            raise
        except Exception as exc:  # No sabemos si el proveedor llegó a aceptar el POST.
            if response is None:
                return finalizar_meta_atencion(WhatsAppSendResult("desconocido", motivo="Sin respuesta concluyente: " + type(exc).__name__))
            # Un fallo al cerrar el cliente no borra una respuesta ya recibida.
        status = response.status_code
        try:
            body = response.json()
        except (ValueError, TypeError):
            body = None
        if isinstance(body, dict) and 200 <= status < 300 and "error" not in body:
            messages = body.get("messages")
            if (isinstance(messages, list) and len(messages) == 1
                    and isinstance(messages[0], dict)
                    and isinstance(messages[0].get("id"), str) and messages[0]["id"].strip()):
                message_id = messages[0]["id"].strip()
                return finalizar_meta_atencion(WhatsAppSendResult("aceptado", provider_message_id=message_id,
                    http_status=status, message_ids=(message_id,)))
        error = body.get("error") if isinstance(body, dict) else None
        # Solo una negativa explícita de cliente es un rechazo seguro. Un 5xx,
        # timeout HTTP o cuerpo contradictorio se conserva como desconocido.
        if (400 <= status < 500 and status != 408 and isinstance(error, dict)
                and type(error.get("code")) is int and isinstance(error.get("message"), str)
                and error["message"] and not body.get("messages")):
            return finalizar_meta_atencion(WhatsAppSendResult("rechazado", motivo=error["message"][:300],
                http_status=status, error_code=str(error["code"])))
        return finalizar_meta_atencion(WhatsAppSendResult("desconocido", motivo="Respuesta Meta sin aceptación o rechazo concluyente",
            http_status=status))


async def _send_whatsapp_payload(
    *, cliente_id: str, phone_number_id: str, payload: Dict[str, Any], detailed: bool = False,
) -> Union[bool, WhatsAppSendResult]:
    resultado = await _post_whatsapp_message(cliente_id=cliente_id,
        phone_number_id=phone_number_id, payload=payload)
    return _whatsapp_result_for_caller(resultado, detailed)


async def _send_whatsapp_buttons(
    *,
    cliente_id: str,
    phone_number_id: str,
    to_number: str,
    body: str,
    buttons: List[Tuple[str, str]],
    header: str = "",
    footer: str = "",
    detailed: bool = False,
) -> Union[bool, WhatsAppSendResult]:
    # Se admiten (id, texto) y {"id":..., "title":...}: un sitio los pasaba como
    # diccionario, al iterarlo salian las CLAVES, los dos botones se quedaban con
    # el id "id" y Meta devolvia 400 "Duplicate button id". El mensaje no llegaba,
    # la rama cortaba y la clienta pulsaba Confirmar sin que pasara nada.
    # Normalizar aqui, que es por donde salen TODOS, mata la clase entera.
    btns = []
    vistos = set()
    for boton in list(buttons)[:3]:
        if isinstance(boton, dict):
            btn_id = str(boton.get("id") or "")
            btn_label = str(boton.get("title") or boton.get("label") or "")
        else:
            btn_id, btn_label = str(boton[0]), str(boton[1])
        if not btn_id or btn_id in vistos:
            # Meta rechaza el mensaje ENTERO por un id repetido. Mejor mandar los
            # que sirven que perder la conversacion.
            settings.logger.error(
                "[whatsapp] boton descartado por id vacio o repetido (%r) en %s",
                btn_id, cliente_id,
            )
            continue
        vistos.add(btn_id)
        btns.append({
            "type": "reply",
            "reply": {"id": btn_id[:256], "title": btn_label[:20]},
        })
    if not btns:
        settings.logger.error("[whatsapp] sin botones validos para %s", cliente_id)
        return _whatsapp_result_for_caller(WhatsAppSendResult("omitido", motivo="Sin botones válidos"), detailed)
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
        **({"detailed": True} if detailed else {}),
    )


async def _send_whatsapp_cta_url(
    *,
    cliente_id: str,
    phone_number_id: str,
    to_number: str,
    body: str,
    button_label: str,
    url: str,
    footer: str = "",
    detailed: bool = False,
) -> Union[bool, WhatsAppSendResult]:
    """Mensaje con un boton que abre un enlace, sin ensenar la URL.

    Un checkout de Stripe son ~300 caracteres ilegibles en el movil. Con el boton
    el cliente ve "Pagar 1 EUR" y ya. Requiere la ventana de 24h abierta, que es
    justo el caso (acaba de escribir); si Meta lo rechaza, quien llama cae a texto.
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "cta_url",
            "body": {"text": body[:1024]},
            "action": {
                "name": "cta_url",
                "parameters": {"display_text": button_label[:20], "url": url},
            },
        },
    }
    if footer:
        payload["interactive"]["footer"] = {"text": footer[:60]}
    return await _send_whatsapp_payload(
        cliente_id=cliente_id, phone_number_id=phone_number_id, payload=payload,
        **({"detailed": True} if detailed else {}),
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
    detailed: bool = False,
) -> Union[bool, WhatsAppSendResult]:
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
        **({"detailed": True} if detailed else {}),
    )


async def _send_whatsapp_text(
    *,
    cliente_id: str,
    phone_number_id: str,
    to_number: str,
    text: str,
    detailed: bool = False,
) -> Union[bool, WhatsAppSendResult]:
    aceptados: List[str] = []
    for fragmento, chunk in enumerate(_whatsapp_chunks(text)):
        try:
            resultado = await _post_whatsapp_message(cliente_id=cliente_id, phone_number_id=phone_number_id,
                payload={"messaging_product": "whatsapp", "recipient_type": "individual",
                    "to": to_number, "type": "text", "text": {"preview_url": True, "body": chunk}},
                **({"_atencion_fragmento": fragmento} if atencion_contexto.contexto_atencion_actual() is not None else {}))
        except atencion_contexto.AtencionDetenida as exc:
            if aceptados:
                parcial = atencion_contexto.AtencionDetenida("texto_aceptado_parcialmente", "desconocido")
                parcial.resultado = WhatsAppSendResult("desconocido", provider_message_id=aceptados[0],
                    message_ids=tuple(aceptados), motivo="Texto aceptado parcialmente; no reenviar automáticamente")
                raise parcial from exc
            raise
        if resultado.estado != "aceptado":
            if aceptados:
                # Aunque este fragmento fuese rechazado, False autorizaría
                # reenviar el texto entero y duplicar los que ya aceptó Meta.
                resultado = replace(resultado, estado="desconocido", message_ids=tuple(aceptados),
                    motivo="Texto aceptado parcialmente; no reenviar automáticamente")
            return _whatsapp_result_for_caller(resultado, detailed)
        aceptados.extend(resultado.message_ids)
    resultado = replace(resultado, provider_message_id=aceptados[0], message_ids=tuple(aceptados))
    return _whatsapp_result_for_caller(resultado, detailed)


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
    datos = {"To": to_number, "From": from_number, "Body": body[:1500]}
    wire = httpx.Request("POST", url, data=datos).content
    with atencion_salidas.salida_red_atencion(None, "twilio_sms", 0,
            atencion_salidas.payload_salida_atencion(url, wire)) as admision:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                kwargs = {"data": datos} if admision is None else {
                    "content": wire, "headers": {"Content-Type": "application/x-www-form-urlencoded"}}
                resp = await client.post(url, auth=(account_sid, auth_token), **kwargs)
                if 200 <= resp.status_code < 300:
                    # El cierre del cliente no borra una respuesta ya recibida.
                    atencion_salidas.registrar_salida_atencion(admision, "aceptado")
            if resp.status_code >= 300:
                estado = "rechazado" if 400 <= resp.status_code < 500 and resp.status_code != 408 else "desconocido"
                atencion_salidas.registrar_salida_atencion(admision, estado)
                if admision is not None and estado == "desconocido":
                    raise atencion_contexto.AtencionDetenida("envio_sin_nueva_admision", estado)
                settings.logger.error("[voice] Twilio SMS error (%s): %s", resp.status_code, resp.text[:300])
                return False
            atencion_salidas.registrar_salida_atencion(admision, "aceptado")
            return True
        except atencion_contexto.AtencionDetenida:
            raise
        except Exception as exc:  # noqa: BLE001
            if admision is not None:
                raise
            settings.logger.error("[voice] Twilio SMS exception: %s", exc)
            return False
