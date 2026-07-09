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
    textnorm,
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


