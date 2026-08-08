"""Endpoints: seccion auth_oauth (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional
from urllib.parse import quote, urlencode

import httpx
from fastapi import (
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field


from api_models import *  # noqa: F401,F403
from backend import (
    appstate,
    db,
    emailing,
    onboarding,
    portal,
    security,
    settings,
    textnorm,
    timeutils,
)
from backend.main import app

@app.post("/auth/login", response_model=AuthLoginResponse)
async def auth_login(data: AuthLoginPayload, request: Request) -> Response:
    client_ip = request.client.host if request.client else "unknown"
    email_norm = textnorm._normalize_email(data.email)
    security._check_rate_limit(f"login-ip:{client_ip}", 10)
    security._check_rate_limit(f"login-email:{email_norm}", 5)
    user = security._get_user_by_email(data.email)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No encontramos ninguna cuenta con ese correo.")
    # Cuenta ligada a un tenant que ya no existe (cliente borrado / demo expirada): no
    # puede entrar. Mismo criterio que la validacion de sesion (defensa en profundidad).
    if user["role"] == "client":
        _cid = (user["cliente_id"] or "").strip()
        if _cid and _cid not in appstate.CONFIG_CLIENTES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta cuenta pertenece a un negocio que ya no esta activo. Contacta con soporte.",
            )
    if not security._verify_secret(data.password, user["password_hash"]):
        if (user["google_sub"] or "").strip() and (user["signup_source"] or "").strip().lower() == "google":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esta cuenta se creo con Google. Inicia sesion usando Google.",
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Contraseña incorrecta.")

    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (timeutils._utc_now_iso(), user["id"]),
        )
        connection.commit()
    fresh_user = security._get_user_by_id(user["id"])
    raw_token = security._create_auth_session(user["id"])
    payload = AuthLoginResponse(
        ok=True,
        user=security._serialize_auth_user(fresh_user),
        redirect_to=security._redirect_for_role(fresh_user["role"]),
    )
    response = JSONResponse(payload.model_dump())
    security._clear_admin_return_cookie(response)
    security._set_portal_cookie(response, raw_token)
    return response


@app.post("/auth/logout")
async def auth_logout(
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
) -> Response:
    response = JSONResponse({"ok": True})
    if portal_session:
        security._delete_auth_session(portal_session)
    security._clear_portal_cookie(response)
    security._clear_admin_return_cookie(response)
    return response


# --- Vantelia 2.0 self-serve auth (Sem 2) ---

@app.post("/auth/signup", response_model=AuthSignupResponse)
async def auth_signup(data: AuthSignupPayload, request: Request) -> Response:
    if not settings.SIGNUP_ENABLED:
        raise HTTPException(status_code=403, detail="Registro deshabilitado.")
    email_norm = textnorm._normalize_email(data.email)
    if security._get_user_by_email(email_norm):
        raise HTTPException(status_code=409, detail="Ese email ya tiene cuenta. Inicia sesion.")
    new_user = security._create_user_self_serve(
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
            await timeutils._to_thread(
                onboarding._claim_cliente_id,
                data.claim,
                new_user["id"],
                source="claim_demo",
            )
            redirect_to = "/app"
            new_user = security._get_user_by_id(new_user["id"])
        except HTTPException as claim_exc:
            settings.logger.info("Signup claim %s rechazado: %s", data.claim, claim_exc.detail)
    raw_token = security._create_auth_session(new_user["id"])
    payload = AuthSignupResponse(
        ok=True,
        user=security._serialize_auth_user(new_user),
        redirect_to=redirect_to,
    )
    portal._try_record_analytics_event(
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
    portal._try_record_analytics_event(
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
    security._set_portal_cookie(response, raw_token)
    return response


@app.get("/auth/google/start", include_in_schema=False)
async def auth_google_start(intent: str = "login", claim: str = "") -> Response:
    if not security._google_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth no esta configurado.")
    intent_norm = intent if intent in {"login", "signup"} else "login"
    claim_norm = (claim or "").strip()
    if claim_norm and not settings.CLIENT_ID_PATTERN.match(claim_norm):
        claim_norm = ""
    state = security._oauth_create_state(intent=intent_norm, claim=claim_norm)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    return RedirectResponse(f"{settings.GOOGLE_OAUTH_AUTHORIZE_URL}?{query}")


@app.get("/auth/google/callback", include_in_schema=False)
async def auth_google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> Response:
    if not security._google_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth no esta configurado.")
    if error:
        return RedirectResponse(f"/acceso?google_error={quote(error)}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Faltan code o state.")
    state_payload = security._oauth_consume_state(state)
    if not state_payload:
        return RedirectResponse("/acceso?google_error=state_expired")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                settings.GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
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
                settings.GOOGLE_OAUTH_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            info = userinfo_resp.json()
    except httpx.HTTPError as exc:
        settings.logger.error("Google OAuth fallo: %s", exc)
        raise HTTPException(status_code=502, detail="No se pudo verificar con Google.") from exc

    google_sub = str(info.get("sub", "")).strip()
    email = textnorm._normalize_email(info.get("email", ""))
    name = str(info.get("name", "") or info.get("given_name", "") or email.split("@")[0])
    picture = str(info.get("picture", ""))
    if not google_sub or not email:
        raise HTTPException(status_code=400, detail="Google no devolvio identificadores.")

    user = security._get_user_by_google_sub(google_sub) or security._get_user_by_email(email)
    created_google_user = False
    if user and not user["google_sub"]:
        return RedirectResponse("/acceso?google_error=email_account")
    if not user:
        if not settings.SIGNUP_ENABLED:
            return RedirectResponse("/acceso?google_error=signup_disabled")
        user = security._create_user_self_serve(
            email=email,
            display_name=name,
            google_sub=google_sub,
            avatar_url=picture,
            signup_source="google",
            email_verified=True,
        )
        created_google_user = True

    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (timeutils._utc_now_iso(), user["id"]),
        )
        connection.commit()

    # Apply pending demo claim (carried through OAuth state from /signup?claim=...).
    claim_token = (state_payload.get("claim") or "").strip() if state_payload else ""
    if claim_token:
        try:
            await timeutils._to_thread(
                onboarding._claim_cliente_id,
                claim_token,
                user["id"],
                source="claim_demo",
            )
        except HTTPException as claim_exc:
            settings.logger.info("Google OAuth claim %s rechazado: %s", claim_token, claim_exc.detail)

    raw_token = security._create_auth_session(user["id"])
    # Decide redirect: if user has no cliente_id provisioned, send to onboarding.
    fresh = security._get_user_by_id(user["id"])
    redirect_target = "/onboarding" if not (fresh and fresh["cliente_id"]) else "/app"
    response = RedirectResponse(redirect_target)
    security._set_portal_cookie(response, raw_token)
    if created_google_user:
        portal._try_record_analytics_event(
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


@app.get("/admin/email-channels/status", dependencies=[Depends(security._require_admin_token)])
async def admin_email_channels_status() -> Dict[str, Any]:
    row = emailing._gmail_connection()
    smtp_settings = emailing._smtp_public_settings()
    gmail_ready = security._gmail_oauth_configured() and emailing._gmail_connected()
    if settings.EMAIL_SEND_PROVIDER == "gmail":
        active_provider = "gmail" if gmail_ready else "none"
    elif settings.EMAIL_SEND_PROVIDER == "smtp":
        active_provider = "smtp" if emailing._smtp_configured() else "none"
    else:
        active_provider = "gmail" if gmail_ready else "smtp" if emailing._smtp_configured() else "none"
    return {
        "provider": settings.EMAIL_SEND_PROVIDER,
        "active_provider": active_provider,
        "gmail": {
            "configured": security._gmail_oauth_configured(),
            "connected": bool(row and row["refresh_token_encrypted"]),
            "email": row["email"] if row else "",
            "scopes": (row["scopes"] if row else "").split(),
            "updated_at": row["updated_at"] if row else "",
            "last_used_at": row["last_used_at"] if row else "",
            "last_error": row["last_error"] if row else "",
            "redirect_uri": security._gmail_redirect_uri(),
        },
        "smtp": {
            "configured": emailing._smtp_configured(),
            "from_email": smtp_settings["from_email"],
            "from_name": smtp_settings["from_name"],
            "reply_to": smtp_settings["reply_to"],
        },
    }


class AdminEmailSmtpSettingsPayload(BaseModel):
    host: str = Field(default="", max_length=200)
    port: int = Field(default=587, ge=1, le=65535)
    username: str = Field(default="", max_length=200)
    password: str = Field(default="", max_length=500)
    starttls: bool = True
    from_email: EmailStr
    from_name: str = Field(default="Vantelia", max_length=80)
    reply_to: str = Field(default="", max_length=200)


@app.post("/admin/email-channels/smtp-settings", dependencies=[Depends(security._require_admin_token)])
async def admin_email_channels_smtp_settings(data: AdminEmailSmtpSettingsPayload) -> Dict[str, Any]:
    try:
        smtp_settings = emailing._smtp_update_public_settings(
            from_email=str(data.from_email),
            from_name=data.from_name,
            reply_to=data.reply_to,
            host=data.host,
            port=data.port,
            username=data.username,
            password=data.password,
            starttls=data.starttls,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "smtp": {"configured": emailing._smtp_configured(), **smtp_settings}}


@app.get("/admin/email-channels/gmail/connect", include_in_schema=False)
async def admin_email_channels_gmail_connect(
    identity: Dict[str, str] = Depends(portal._require_admin_identity),
) -> Response:
    if not security._gmail_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Configura Google OAuth, GOOGLE_GMAIL_REDIRECT_URI y la clave de cifrado antes de conectar Gmail.",
        )
    state = security._gmail_oauth_create_state(identity.get("user_id", ""))
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": security._gmail_redirect_uri(),
        "response_type": "code",
        "scope": settings.GOOGLE_GMAIL_SCOPES,
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent select_account",
    }
    return RedirectResponse(f"{settings.GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


@app.get("/auth/google/gmail/callback", include_in_schema=False)
async def auth_google_gmail_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> Response:
    if error:
        return RedirectResponse(f"/dashboard?gmail_error={quote(error)}")
    state_payload = security._gmail_oauth_consume_state(state or "")
    if not state_payload:
        return RedirectResponse("/dashboard?gmail_error=state_expired")
    if not code:
        return RedirectResponse("/dashboard?gmail_error=missing_code")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            token_response = await client.post(
                settings.GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": security._gmail_redirect_uri(),
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
                settings.GOOGLE_OAUTH_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_response.raise_for_status()
            email = textnorm._normalize_email(userinfo_response.json().get("email", ""))
        if not email:
            raise RuntimeError("Google no devolvio el email de la cuenta.")
        target_cliente_id = str(state_payload.get("cliente_id") or "")
        emailing._gmail_save_tokens(
            token_data,
            email,
            str(token_data.get("scope") or settings.GOOGLE_GMAIL_SCOPES),
            target_cliente_id,
        )
    except Exception as exc:
        settings.logger.error("Conexion Gmail fallo: %s", exc)
        return RedirectResponse(f"/dashboard?gmail_error={quote(str(exc)[:160])}")
    return RedirectResponse("/app?gmail_connected=1" if state_payload.get("cliente_id") else "/dashboard?gmail_connected=1")


@app.delete("/admin/email-channels/gmail", dependencies=[Depends(security._require_admin_token)])
async def admin_email_channels_gmail_disconnect() -> Dict[str, Any]:
    row = emailing._gmail_connection()
    if row and row["refresh_token_encrypted"]:
        try:
            refresh_token = emailing._gmail_decrypt(row["refresh_token_encrypted"])
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post("https://oauth2.googleapis.com/revoke", params={"token": refresh_token})
        except Exception as exc:
            settings.logger.warning("No se pudo revocar Gmail en Google; se eliminara la conexion local: %s", exc)
    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM gmail_connections WHERE id = 'default'")
        connection.commit()
    return {"ok": True}


@app.get("/auth/app/email-channel", response_model=GmailClientStateResponse)
async def app_email_channel_state(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> GmailClientStateResponse:
    cliente_id = str(user["cliente_id"] or "")
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Tu usuario no tiene un negocio asociado.")
    row = emailing._gmail_connection(cliente_id)
    connected = bool(row and row["refresh_token_encrypted"])
    return GmailClientStateResponse(
        configured=security._gmail_oauth_configured(),
        connected=connected,
        email=row["email"] if row else "",
        status="reconnect_required" if row and row["last_error"] else "active" if connected else "not_connected",
        last_error=row["last_error"] if row else "",
        smtp_fallback=emailing._smtp_configured(),
    )


@app.get("/auth/app/email-channel/gmail/connect", include_in_schema=False)
async def app_email_channel_gmail_connect(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Response:
    if security._session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Accion bloqueada en sesion de admin (impersonacion).")
    cliente_id = str(user["cliente_id"] or "")
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Tu usuario no tiene un negocio asociado.")
    if not security._gmail_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth para Gmail no esta configurado.")
    state = security._gmail_oauth_create_state(user["id"], cliente_id)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": security._gmail_redirect_uri(),
        "response_type": "code",
        "scope": settings.GOOGLE_GMAIL_SCOPES,
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent select_account",
    }
    return RedirectResponse(f"{settings.GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


@app.delete("/auth/app/email-channel/gmail")
async def app_email_channel_gmail_disconnect(
    user: sqlite3.Row = Depends(security._require_authenticated_portal_user),
) -> Dict[str, Any]:
    if security._session_is_impersonated(user):
        raise HTTPException(status_code=403, detail="Accion bloqueada en sesion de admin (impersonacion).")
    cliente_id = str(user["cliente_id"] or "")
    row = emailing._gmail_connection(cliente_id)
    if row and row["refresh_token_encrypted"]:
        try:
            refresh_token = emailing._gmail_decrypt(row["refresh_token_encrypted"])
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post("https://oauth2.googleapis.com/revoke", params={"token": refresh_token})
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("No se pudo revocar Gmail cliente=%s: %s", cliente_id, exc)
    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM gmail_connections WHERE id = ?", (cliente_id,))
        connection.commit()
    return {"ok": True}


# --- Vantelia 2.0 wizard onboarding (Sem 2) ---



