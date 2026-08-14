"""Alta self-service de WhatsApp por Embedded Signup, con Coexistence (ago 2026).

Hasta ahora cada numero se daba de alta a mano por la Graph API (pedir codigo,
verificar, registrar, suscribir la WABA). Eso no escala y, sobre todo, obligaba
al negocio a SACAR su numero de la app del movil.

Meta lanzo **Coexistence** (mayo 2025, global desde mayo 2026): el mismo numero
puede estar a la vez en la app de WhatsApp Business y en la Cloud API. El equipo
sigue atendiendo desde el movil, el asistente responde por la API, y cada lado ve
lo que escribe el otro. Se activa por Embedded Signup, no por el alta manual.

Este modulo cubre la parte del servidor: cambiar el `code` que devuelve el flujo
por un token permanente del negocio, suscribir su WABA a nuestra app y guardar
las credenciales cifradas por tenant.

Requisitos en Meta (fuera del codigo, ver docs/WHATSAPP_EMBEDDED_SIGNUP.md):
verificacion del negocio, la app configurada como Tech Provider y una Login
configuration cuyo id va en WHATSAPP_ES_CONFIG_ID.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

import httpx

from backend import db, security, settings, textnorm, timeutils

GRAPH = "https://graph.facebook.com"

MODE_COEXISTENCE = "coexistence"
MODE_API = "api"


def embedded_signup_available() -> bool:
    """La UI solo ofrece el boton si Meta esta configurado de verdad."""
    return bool(
        getattr(settings, "WHATSAPP_APP_ID", "")
        and getattr(settings, "WHATSAPP_APP_SECRET", "")
        and getattr(settings, "WHATSAPP_ES_CONFIG_ID", "")
    )


# --- Persistencia ----------------------------------------------------------


def _row_to_account(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    if not row:
        return {}
    return {
        "cliente_id": row["cliente_id"],
        "waba_id": row["waba_id"] or "",
        "phone_number_id": row["phone_number_id"] or "",
        "display_phone_number": row["display_phone_number"] or "",
        "verified_name": row["verified_name"] or "",
        "mode": row["mode"] or MODE_API,
        "status": row["status"] or "connected",
        "last_error": row["last_error"] or "",
        "connected_at": row["connected_at"] or "",
        "has_token": bool(row["access_token_encrypted"]),
    }


def get_account(cliente_id: str) -> Dict[str, Any]:
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM client_whatsapp_accounts WHERE cliente_id = ?", (cliente_id,)
        ).fetchone()
    return _row_to_account(row)


def account_token(cliente_id: str) -> str:
    """Token propio del negocio (vacio si no hay conexion self-service)."""
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT access_token_encrypted FROM client_whatsapp_accounts WHERE cliente_id = ? AND status = 'connected'",
            (cliente_id,),
        ).fetchone()
    if not row or not row["access_token_encrypted"]:
        return ""
    try:
        return security._decrypt_channel_secret(row["access_token_encrypted"])
    except Exception as exc:  # noqa: BLE001 - token ilegible no debe tumbar el envio
        settings.logger.error("Token de WhatsApp ilegible para %s: %s", cliente_id, exc)
        return ""


def phone_client_map() -> Dict[str, str]:
    """phone_number_id -> cliente_id de las conexiones self-service."""
    mapping: Dict[str, str] = {}
    try:
        with db._get_db_connection() as connection:
            rows = connection.execute(
                "SELECT cliente_id, phone_number_id FROM client_whatsapp_accounts WHERE status = 'connected'"
            ).fetchall()
    except Exception:  # noqa: BLE001 - antes de la migracion la tabla puede no existir
        return mapping
    for row in rows:
        pnid = str(row["phone_number_id"] or "").strip()
        if pnid:
            mapping[pnid] = row["cliente_id"]
    return mapping


def save_account(
    cliente_id: str,
    *,
    waba_id: str,
    phone_number_id: str,
    token: str,
    display_phone_number: str = "",
    verified_name: str = "",
    mode: str = MODE_API,
) -> Dict[str, Any]:
    now_iso = timeutils._utc_now_iso()
    encrypted = security._encrypt_channel_secret(token) if token else ""
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_whatsapp_accounts
                (cliente_id, waba_id, phone_number_id, display_phone_number, verified_name,
                 mode, access_token_encrypted, status, last_error, connected_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'connected', '', ?, ?)
            ON CONFLICT(cliente_id) DO UPDATE SET
                waba_id = excluded.waba_id,
                phone_number_id = excluded.phone_number_id,
                display_phone_number = excluded.display_phone_number,
                verified_name = excluded.verified_name,
                mode = excluded.mode,
                access_token_encrypted = excluded.access_token_encrypted,
                status = 'connected',
                last_error = '',
                updated_at = excluded.updated_at
            """,
            (
                cliente_id,
                textnorm._sanitize_text(waba_id)[:80],
                textnorm._sanitize_text(phone_number_id)[:80],
                textnorm._sanitize_text(display_phone_number)[:40],
                textnorm._sanitize_text(verified_name)[:120],
                mode if mode in (MODE_API, MODE_COEXISTENCE) else MODE_API,
                encrypted,
                now_iso,
                now_iso,
            ),
        )
        connection.commit()
    return get_account(cliente_id)


def disconnect(cliente_id: str) -> bool:
    with db._get_db_connection() as connection:
        cur = connection.execute(
            "DELETE FROM client_whatsapp_accounts WHERE cliente_id = ?", (cliente_id,)
        )
        connection.commit()
        return cur.rowcount > 0


# --- Graph API -------------------------------------------------------------


async def _graph_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get(f"{GRAPH}/{settings.WHATSAPP_API_VERSION}/{path}", params=params)
        data = response.json() if response.content else {}
    if response.status_code >= 300 or "error" in data:
        raise RuntimeError(str((data.get("error") or {}).get("message") or response.text)[:300])
    return data


async def _graph_post(path: str, data: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(f"{GRAPH}/{settings.WHATSAPP_API_VERSION}/{path}", data=data)
        payload = response.json() if response.content else {}
    if response.status_code >= 300 or "error" in payload:
        raise RuntimeError(str((payload.get("error") or {}).get("message") or response.text)[:300])
    return payload


async def exchange_code(code: str) -> str:
    """Cambia el `code` del Embedded Signup por el token permanente del negocio."""
    data = await _graph_get(
        "oauth/access_token",
        {
            "client_id": settings.WHATSAPP_APP_ID,
            "client_secret": settings.WHATSAPP_APP_SECRET,
            "code": code,
        },
    )
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Meta no devolvio ningun token.")
    return token


async def token_waba_ids(token: str) -> List[str]:
    """WABAs a las que da acceso el token (vienen en los granular_scopes)."""
    data = await _graph_get("debug_token", {"input_token": token, "access_token": token})
    scopes = ((data.get("data") or {}).get("granular_scopes") or [])
    ids: List[str] = []
    for scope in scopes:
        if scope.get("scope") in ("whatsapp_business_management", "whatsapp_business_messaging"):
            for target in scope.get("target_ids") or []:
                if target not in ids:
                    ids.append(str(target))
    return ids


async def waba_phone_numbers(waba_id: str, token: str) -> List[Dict[str, Any]]:
    data = await _graph_get(
        f"{waba_id}/phone_numbers",
        {
            "fields": "id,display_phone_number,verified_name,platform_type,status,code_verification_status",
            "access_token": token,
        },
    )
    return list(data.get("data") or [])


async def subscribe_app(waba_id: str, token: str) -> None:
    """Sin esto los mensajes del cliente no llegan a nuestro webhook."""
    await _graph_post(f"{waba_id}/subscribed_apps", {"access_token": token})


async def register_phone(phone_number_id: str, token: str, pin: str) -> None:
    """Registra el numero en Cloud API. En Coexistence el propio flujo de Meta
    puede haberlo hecho ya: si responde que esta registrado, no es un error."""
    try:
        await _graph_post(
            f"{phone_number_id}/register",
            {"messaging_product": "whatsapp", "pin": pin, "access_token": token},
        )
    except RuntimeError as exc:
        texto = str(exc).lower()
        if "already" in texto or "registered" in texto:
            settings.logger.info("Numero %s ya estaba registrado en Cloud API.", phone_number_id)
            return
        raise


# Evento que devuelve el flujo cuando el negocio conecta su app del movil.
COEXISTENCE_EVENT = "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"


async def complete_signup(
    cliente_id: str,
    *,
    code: str,
    waba_id: str = "",
    phone_number_id: str = "",
    pin: str = "",
    event: str = "",
) -> Dict[str, Any]:
    """Cierra el alta: token -> WABA -> suscripcion -> credenciales guardadas.

    `waba_id` y `phone_number_id` los devuelve el flujo del navegador; si no
    llegan se deducen del propio token.
    """
    token = await exchange_code(code)

    if not waba_id:
        ids = await token_waba_ids(token)
        if not ids:
            raise RuntimeError("El token no da acceso a ninguna cuenta de WhatsApp.")
        waba_id = ids[0]

    numeros = await waba_phone_numbers(waba_id, token)
    elegido: Dict[str, Any] = {}
    for numero in numeros:
        if not phone_number_id or str(numero.get("id")) == str(phone_number_id):
            elegido = numero
            break
    if not elegido:
        raise RuntimeError("No se encontro ningun numero de telefono en esa cuenta de WhatsApp.")

    phone_number_id = str(elegido.get("id"))
    await subscribe_app(waba_id, token)

    # El propio flujo dice si el negocio conecto su app del movil. En ese caso el
    # numero YA esta registrado y Meta pide expresamente saltarse el registro.
    coexistence = str(event or "").upper() == COEXISTENCE_EVENT
    if pin and not coexistence:
        await register_phone(phone_number_id, token, pin)

    mode = MODE_COEXISTENCE if coexistence else MODE_API
    return save_account(
        cliente_id,
        waba_id=waba_id,
        phone_number_id=phone_number_id,
        token=token,
        display_phone_number=str(elegido.get("display_phone_number") or ""),
        verified_name=str(elegido.get("verified_name") or ""),
        mode=mode,
    )
