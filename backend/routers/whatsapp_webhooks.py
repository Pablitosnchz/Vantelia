"""Endpoints: seccion whatsapp_webhooks (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations


from fastapi import (
    Request,
    Response,
)


from api_models import *  # noqa: F401,F403
from backend import (
    settings,
    textnorm,
    wa_flows,
    whatsapp,
)
from backend.main import app

@app.get("/whatsapp/webhook", include_in_schema=False)
async def whatsapp_webhook_verify(request: Request) -> Response:
    return whatsapp._verify_whatsapp_webhook_challenge(request)


@app.post("/whatsapp/webhook", response_model=WhatsAppWebhookStatus)
async def whatsapp_webhook(request: Request) -> WhatsAppWebhookStatus:
    return await whatsapp._handle_whatsapp_webhook(request)


@app.get("/whatsapp/webhook/{cliente_id}", include_in_schema=False)
async def whatsapp_client_webhook_verify(cliente_id: str, request: Request) -> Response:
    textnorm._assert_valid_client_id(cliente_id)
    return whatsapp._verify_whatsapp_webhook_challenge(request, cliente_id)


@app.post("/whatsapp/webhook/{cliente_id}", response_model=WhatsAppWebhookStatus)
async def whatsapp_client_webhook(cliente_id: str, request: Request) -> WhatsAppWebhookStatus:
    textnorm._assert_valid_client_id(cliente_id)
    return await whatsapp._handle_whatsapp_webhook(request, forced_cliente_id=cliente_id)


@app.post("/whatsapp/flow", include_in_schema=False)
async def whatsapp_flow_endpoint(request: Request) -> Response:
    """Endpoint de datos del formulario de reserva dentro de WhatsApp (Flows).

    Meta manda el cuerpo cifrado y espera la respuesta cifrada con la misma clave
    AES y el vector invertido. Un fallo al descifrar debe responder 421 para que
    el cliente refresque nuestra clave publica, no 500.
    """
    body = await request.json()
    try:
        payload, aes_key, iv = wa_flows.decrypt_request(body)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[flow] no se pudo descifrar la peticion: %s", exc)
        return Response(status_code=421)
    try:
        respuesta = await wa_flows.handle_data_exchange(payload)
    except Exception as exc:  # noqa: BLE001 - nunca dejar el formulario colgado
        settings.logger.exception("[flow] error resolviendo la pantalla: %s", exc)
        respuesta = {"screen": wa_flows.SCREEN_SERVICE, "data": {
            "servicios": [], "aviso": "No hemos podido cargar la agenda. Intentalo en unos minutos.",
            "hay_aviso": True,
        }}
    return Response(
        content=wa_flows.encrypt_response(respuesta, aes_key, iv),
        media_type="text/plain",
    )


