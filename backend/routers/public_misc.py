"""Endpoints: seccion public_misc (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

from html import escape
from typing import Any, Dict

from fastapi import (
    HTTPException,
    Request,
)
from fastapi.responses import HTMLResponse


from api_models import *  # noqa: F401,F403
from backend import (
    appstate,
    clients,
    commerce,
    db,
    emailing,
    portal,
    security,
    settings,
    textnorm,
    timeutils,
)
from backend.main import app

@app.post("/analytics/event")
async def analytics_event(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Payload JSON invalido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload de analitica invalido.")
    return portal._record_analytics_event(payload, request)


@app.post("/consulta")
async def solicitar_consulta(data: ConsultaLeadPayload, request: Request) -> Dict[str, Any]:
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"consulta:{client_ip}", 5)

    servicio_texto = data.servicio or "No especificado"
    empresa_texto  = data.empresa  or "No especificada"
    telefono_texto = data.telefono or "No proporcionado"
    mensaje_texto  = data.mensaje  or "(sin mensaje)"

    fecha_utc = timeutils._utc_now().strftime('%Y-%m-%d %H:%M UTC')

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
    if emailing._email_delivery_configured():
        try:
            emailing._send_email_message(
                settings.CONSULTA_NOTIFICATION_EMAIL,
                asunto_admin,
                cuerpo_admin_text,
                cuerpo_admin_html,
                reply_to=str(data.email),
            )
            notif_sent = True
        except Exception as exc:
            settings.logger.error("Error enviando notificacion de consulta a %s: %s", settings.CONSULTA_NOTIFICATION_EMAIL, exc)
        try:
            emailing._send_email_message(
                str(data.email),
                asunto_cliente,
                cuerpo_cliente_text,
                cuerpo_cliente_html,
            )
            confirm_sent = True
        except Exception as exc:
            settings.logger.error("Error enviando confirmacion de consulta a %s: %s", data.email, exc)
    else:
        settings.logger.warning("Canal de email no configurado: no se han enviado emails de la consulta de %s", data.email)

    settings.logger.info(
        "Consulta recibida de %s <%s> (IP: %s) notif=%s confirm=%s",
        data.nombre, data.email, client_ip, notif_sent, confirm_sent,
    )
    return {"ok": True, "message": "Solicitud recibida. Te respondemos en menos de 24h."}


@app.get("/health")
async def healthcheck() -> Dict[str, Any]:
    checks: Dict[str, str] = {
        "config": "ok" if settings.CONFIG_PATH.exists() else "missing",
        "data_dir": "ok" if settings.DATA_DIR.exists() else "missing",
        "storage_dir": "ok" if settings.STORAGE_DIR.exists() else "missing",
        "database": "unknown",
        "widget_bundle": "ok" if (settings.WIDGET_DIR / "widget.min.js").exists() else "missing",
    }
    try:
        with db._get_db_connection() as connection:
            connection.execute("SELECT 1").fetchone()
            checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("Healthcheck database failed: %s", exc)
        checks["database"] = "error"

    critical_checks = ["config", "data_dir", "storage_dir", "database"]
    overall_status = "ok" if all(checks.get(name) == "ok" for name in critical_checks) else "degraded"
    return {
        "status": overall_status,
        "version": app.version,
        "openai_configured": bool(settings.OPENAI_API_KEY),
        "clientes_configurados": len(appstate.CONFIG_CLIENTES),
        "checks": checks,
        "runtime": {
            "started_at": appstate.STARTED_AT.isoformat(),
            "uptime_seconds": int((timeutils._utc_now() - appstate.STARTED_AT).total_seconds()),
            "data_dir": str(settings.DATA_DIR),
            "storage_dir": str(settings.STORAGE_DIR),
        },
    }




# --- Compra publica de tarjetas regalo (opt-in por tenant) -------------------------

@app.get("/reservas/{cliente_id}", include_in_schema=False)
@app.get("/central/{cliente_id}", include_in_schema=False)
async def central_public_page(cliente_id: str, request: Request) -> HTMLResponse:
    """Central publica del negocio: reservas como flujo principal y ventas anexas.

    Es una fachada de bajo riesgo: reutiliza /servicios, /disponibilidad, /agendar,
    /tienda y /gift en lugar de duplicar logica de reserva o checkout.
    """
    textnorm._assert_valid_client_id(cliente_id)
    cfg = clients._get_client_config(cliente_id)
    try:
        booking_enabled = bool((cfg.get("booking") or {}).get("enabled")) and clients._client_booking_plan_enabled(cliente_id)
    except Exception:  # noqa: BLE001
        booking_enabled = bool((cfg.get("booking") or {}).get("enabled"))
    shop_available = commerce.shop_public_available(cliente_id)
    gift_available = commerce.gift_public_available(cliente_id)
    if not (booking_enabled or shop_available.get("any") or gift_available):
        raise HTTPException(status_code=404, detail="La central publica no esta disponible.")
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"central_page:{cliente_id}:{client_ip}", 30)
    # ?embed=1: version sin hero/laterales para incrustar via iframe en la web del negocio.
    embed = (request.query_params.get("embed") or "").strip().lower() in ("1", "true", "si")
    response = HTMLResponse(commerce.central_public_page_html(cliente_id, embed=embed))
    if embed:
        # La pagina embebida debe poder cargarse en iframes de webs de terceros
        # (boton "Codigo para tu web"). CSP frame-ancestors prevalece sobre el
        # X-Frame-Options: DENY que aplica el middleware global via setdefault.
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@app.get("/gift/{cliente_id}", include_in_schema=False)
async def gift_public_page(cliente_id: str, request: Request) -> HTMLResponse:
    """Pagina publica de compra de tarjeta regalo del negocio. 404 si el tenant no
    tiene la funcion activa o no puede cobrar (sin Stripe Connect operativo)."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)  # 404 si el cliente no existe
    if not commerce.gift_public_available(cliente_id):
        raise HTTPException(status_code=404, detail="La compra de tarjetas regalo no esta disponible.")
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"gift_page:{cliente_id}:{client_ip}", 30)
    return HTMLResponse(commerce.gift_public_page_html(cliente_id))


@app.get("/gift/{cliente_id}/saldo", include_in_schema=False)
async def gift_balance_page(cliente_id: str, request: Request) -> HTMLResponse:
    """Consulta publica de saldo de tarjeta regalo. Disponible si el negocio ha
    emitido alguna tarjeta (mostrador u online) o tiene la venta publica activa."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"gift_balance_page:{cliente_id}:{client_ip}", 30)
    return HTMLResponse(commerce.gift_balance_page_html(cliente_id))


@app.post("/gift/{cliente_id}/saldo", include_in_schema=False)
async def gift_balance_lookup(cliente_id: str, data: GiftBalancePayload, request: Request) -> Dict[str, Any]:
    """Saldo de una tarjeta por su codigo (el codigo es el secreto; rate limit
    estricto por IP contra fuerza bruta)."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)
    if not commerce.gift_balance_available(cliente_id):
        raise HTTPException(status_code=404, detail="La consulta de saldo no esta disponible.")
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"gift_balance:{cliente_id}:{client_ip}", 10)
    return commerce.gift_card_balance_public(cliente_id, data.code)


@app.get("/bono/{cliente_id}/{wallet_token}", include_in_schema=False)
async def package_wallet_page(cliente_id: str, wallet_token: str, request: Request) -> HTMLResponse:
    """Wallet publica del bono: sesiones restantes, caducidad e historial. El
    wallet_token (secreto del email de compra) es la autorizacion."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"bono_wallet:{cliente_id}:{client_ip}", 30)
    return HTMLResponse(commerce.package_wallet_page_html(cliente_id, wallet_token))


@app.post("/central/{cliente_id}/redeem-options", include_in_schema=False)
async def central_redeem_options(
    cliente_id: str, data: CentralRedeemOptionsPayload, request: Request
) -> Dict[str, Any]:
    """Opciones de canje (bonos del contacto + tarjeta) para una cita recien creada
    en la central publica. El manage_token de la reserva es la autorizacion."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"central_redeem_opts:{cliente_id}:{client_ip}", 20)
    return commerce.booking_redeem_options(cliente_id, data.manage_token)


@app.post("/central/{cliente_id}/redeem", include_in_schema=False)
async def central_redeem_apply(
    cliente_id: str, data: CentralRedeemPayload, request: Request
) -> Dict[str, Any]:
    """Aplica un bono o tarjeta regalo a la cita del manage_token (canje online)."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"central_redeem:{cliente_id}:{client_ip}", 10)
    return commerce.booking_redeem_apply(
        cliente_id, data.manage_token,
        kind=data.kind, code=data.code, purchase_id=data.purchase_id,
    )


@app.post("/gift/{cliente_id}/checkout", include_in_schema=False)
async def gift_public_checkout(cliente_id: str, data: GiftCardPublicCheckoutPayload, request: Request) -> Dict[str, Any]:
    """Crea el Stripe Checkout de la tarjeta. La tarjeta se emite en el webhook al
    confirmarse el pago (nunca aqui)."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)
    if not commerce.gift_public_available(cliente_id):
        raise HTTPException(status_code=404, detail="La compra de tarjetas regalo no esta disponible.")
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"gift_checkout:{cliente_id}:{client_ip}", 5)
    return commerce.create_gift_card_payment_link(
        cliente_id,
        amount_cents=data.amount_cents,
        buyer_name=data.buyer_name,
        buyer_email=data.buyer_email,
        recipient_name=data.recipient_name,
        recipient_email=data.recipient_email,
        message=data.message,
        scheduled_send_at=data.scheduled_send_at,
        base_url=textnorm._preferred_public_base_url(),
        service_slug=data.service_slug,
        accent_color=data.accent_color,
        hide_value=data.hide_value,
        hide_expiry=data.hide_expiry,
    )


@app.get("/gift/{cliente_id}/checkout-status", include_in_schema=False)
async def gift_public_checkout_status(cliente_id: str, session_id: str, request: Request) -> Dict[str, Any]:
    """Estado post-Stripe para pintar codigo/saldo cuando el webhook ya materializo la tarjeta."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"gift_checkout_status:{cliente_id}:{client_ip}", 20)
    return commerce.public_checkout_status(cliente_id, session_id)


# --- Tienda publica: bonos y productos (opt-in por tenant) --------------------------

@app.get("/tienda/{cliente_id}", include_in_schema=False)
async def shop_public_page(cliente_id: str, request: Request) -> HTMLResponse:
    """Pagina publica de la tienda del negocio (bonos y/o productos). 404 si el tenant
    no tiene ninguna seccion activa o no puede cobrar (sin Stripe Connect operativo)."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)  # 404 si el cliente no existe
    availability = commerce.shop_public_available(cliente_id)
    if not availability["any"]:
        raise HTTPException(status_code=404, detail="La tienda online no esta disponible.")
    # ?solo=bonos | ?solo=productos: pagina dedicada a una sola seccion (enlace separado).
    solo = (request.query_params.get("solo") or "").strip().lower()
    if solo not in ("bonos", "productos"):
        solo = ""
    if solo == "bonos" and not availability["packages"]:
        raise HTTPException(status_code=404, detail="La venta online de bonos no esta disponible.")
    if solo == "productos" and not availability["products"]:
        raise HTTPException(status_code=404, detail="La venta online de productos no esta disponible.")
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"shop_page:{cliente_id}:{client_ip}", 30)
    return HTMLResponse(commerce.shop_public_page_html(cliente_id, section=solo))


@app.post("/tienda/{cliente_id}/checkout/bono", include_in_schema=False)
async def shop_public_checkout_package(
    cliente_id: str, data: ShopPackageCheckoutPayload, request: Request
) -> Dict[str, Any]:
    """Checkout Stripe de un bono. El bono se crea en el webhook al confirmarse el pago."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)
    if not commerce.shop_public_available(cliente_id)["packages"]:
        raise HTTPException(status_code=404, detail="La compra online de bonos no esta disponible.")
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"shop_checkout:{cliente_id}:{client_ip}", 5)
    return commerce.create_shop_package_payment_link(
        cliente_id,
        package_id=data.package_id,
        buyer_name=data.buyer_name,
        buyer_email=data.buyer_email,
        buyer_phone=data.buyer_phone,
        base_url=textnorm._preferred_public_base_url(),
    )


@app.post("/tienda/{cliente_id}/checkout/productos", include_in_schema=False)
async def shop_public_checkout_products(
    cliente_id: str, data: ShopProductsCheckoutPayload, request: Request
) -> Dict[str, Any]:
    """Checkout Stripe de productos (recogida en el centro). Las ventas se registran
    en el webhook al confirmarse el pago."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)
    if not commerce.shop_public_available(cliente_id)["products"]:
        raise HTTPException(status_code=404, detail="La compra online de productos no esta disponible.")
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"shop_checkout:{cliente_id}:{client_ip}", 5)
    return commerce.create_shop_products_payment_link(
        cliente_id,
        items=data.items,
        buyer_name=data.buyer_name,
        buyer_email=data.buyer_email,
        buyer_phone=data.buyer_phone,
        base_url=textnorm._preferred_public_base_url(),
    )


@app.get("/tienda/{cliente_id}/checkout-status", include_in_schema=False)
async def shop_public_checkout_status(cliente_id: str, session_id: str, request: Request) -> Dict[str, Any]:
    """Estado post-Stripe para mostrar wallet del bono o confirmacion de pedido."""
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)
    client_ip = request.client.host if request.client else "unknown"
    security._check_rate_limit(f"shop_checkout_status:{cliente_id}:{client_ip}", 20)
    return commerce.public_checkout_status(cliente_id, session_id)
