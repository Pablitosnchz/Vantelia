"""Usuarios, sesiones, cookies, tokens y OAuth states (refactor F3).

Hash de secretos (PBKDF2), sesiones del portal con cookies, impersonacion
admin, tokens de reset, estados OAuth de Google/Gmail y claves Fernet para
cifrado de tokens de canal. Nunca registrar tokens en claro.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sqlite3
import time
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status

from api_models import AuthManagedUser, AuthUserPublic
from backend import appstate, clients, db, settings, textnorm, timeutils

def _compound_token_parts(raw_token: str, expected_prefix: str) -> Tuple[str, str]:
    token_value = str(raw_token or "").strip()
    if "." not in token_value:
        return "", ""
    token_id, secret = token_value.split(".", 1)
    if not token_id.startswith(f"{expected_prefix}_") or not secret:
        return "", ""
    return token_id, secret


def _hash_secret(raw_value: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw_value.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def _verify_secret(raw_value: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", raw_value.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return secrets.compare_digest(digest.hex(), expected)


PORTAL_ROLE_LEVELS = {"staff": 1, "manager": 2, "owner": 3}


def _portal_role(row: sqlite3.Row) -> str:
    """Rol granular dentro del negocio. El admin Vantelia siempre opera como owner."""
    if row["role"] == "admin":
        return "owner"
    try:
        value = (row["portal_role"] or "owner").strip().lower()
    except (IndexError, KeyError):
        value = "owner"
    return value if value in PORTAL_ROLE_LEVELS else "owner"


def _require_portal_min_role(user: sqlite3.Row, minimum: str) -> None:
    """403 si el rol del usuario no alcanza el minimo (staff < manager < owner)."""
    if PORTAL_ROLE_LEVELS.get(_portal_role(user), 0) < PORTAL_ROLE_LEVELS.get(minimum, 3):
        raise HTTPException(
            status_code=403,
            detail="Tu rol no permite esta accion. Pide acceso al propietario de la cuenta.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Permisos granulares por accion (estilo Square/Fresha/Mindbody)
#
# Los roles (owner > manager > staff) son PRESETS de permisos. El propietario
# puede afinar permiso a permiso por usuario (allow/deny) sobre ese preset.
# El owner (y el admin Vantelia) siempre tienen acceso total, no editable.
# Algunos permisos son "owner_only" (config sensible) y no se delegan.
# ─────────────────────────────────────────────────────────────────────────────

PORTAL_PERMISSIONS: List[Dict[str, Any]] = [
    {"key": "agenda.create", "module": "Agenda", "label": "Crear citas manuales"},
    {"key": "agenda.cancel", "module": "Agenda", "label": "Cancelar citas"},
    {"key": "agenda.attendance", "module": "Agenda", "label": "Marcar asistencia / no-show"},
    {"key": "payments.capture", "module": "Pagos", "label": "Cobrar o liberar retenciones"},
    {"key": "payments.refund", "module": "Pagos", "label": "Reembolsar pagos"},
    {"key": "commerce.sell", "module": "Mostrador", "label": "Vender y redimir (productos, bonos, gift cards)"},
    {"key": "catalog.manage", "module": "Catálogo", "label": "Gestionar servicios, productos, bonos y centros"},
    {"key": "clients.edit", "module": "Clientes", "label": "Editar fichas de cliente"},
    {"key": "reports.view", "module": "Informes", "label": "Ver informes"},
    {"key": "reports.export", "module": "Informes", "label": "Exportar informes"},
    {"key": "channels.manage", "module": "Configuración", "label": "Canales de envío", "owner_only": True},
    {"key": "billing.manage", "module": "Configuración", "label": "Pagos Stripe y facturación", "owner_only": True},
    {"key": "team.manage", "module": "Configuración", "label": "Equipo y permisos", "owner_only": True},
]

PORTAL_PERMISSION_KEYS = {p["key"] for p in PORTAL_PERMISSIONS}
_OWNER_ONLY_PERMISSIONS = {p["key"] for p in PORTAL_PERMISSIONS if p.get("owner_only")}

# Default por rol (el owner siempre tiene todo, se resuelve aparte).
PORTAL_ROLE_DEFAULT_PERMISSIONS: Dict[str, set] = {
    "manager": {
        "agenda.create", "agenda.cancel", "agenda.attendance",
        "payments.capture", "commerce.sell",
        "catalog.manage", "clients.edit", "reports.view", "reports.export",
    },
    "staff": {
        "agenda.create", "agenda.cancel", "agenda.attendance", "commerce.sell",
    },
}


def _role_default_permissions(role: str) -> set:
    if role == "owner":
        return set(PORTAL_PERMISSION_KEYS)
    return set(PORTAL_ROLE_DEFAULT_PERMISSIONS.get(role, set()))


def _user_permission_overrides(user_id: str) -> Dict[str, bool]:
    with db._get_db_connection() as connection:
        rows = connection.execute(
            "SELECT permission_key, allowed FROM user_permission_overrides WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {row["permission_key"]: bool(row["allowed"]) for row in rows}


def _effective_permissions(user: sqlite3.Row) -> Dict[str, bool]:
    """Permiso efectivo por clave para el usuario (default de rol + overrides)."""
    role = _portal_role(user)
    if role == "owner" or user["role"] == "admin":
        return {key: True for key in PORTAL_PERMISSION_KEYS}
    base = _role_default_permissions(role)
    effective = {key: (key in base) for key in PORTAL_PERMISSION_KEYS}
    for key, allowed in _user_permission_overrides(user["id"]).items():
        if key in PORTAL_PERMISSION_KEYS and key not in _OWNER_ONLY_PERMISSIONS:
            effective[key] = allowed
    return effective


def _user_has_permission(user: sqlite3.Row, permission_key: str) -> bool:
    if _portal_role(user) == "owner" or user["role"] == "admin":
        return True
    return _effective_permissions(user).get(permission_key, False)


def _require_portal_permission(user: sqlite3.Row, permission_key: str) -> None:
    """403 si el usuario no tiene el permiso de accion concreto."""
    if not _user_has_permission(user, permission_key):
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para esta accion. Pide acceso al propietario de la cuenta.",
        )


def _set_user_permission_override(
    cliente_id: str, user_id: str, permission_key: str, value: Optional[bool]
) -> None:
    """value True/False fija override; None lo elimina (vuelve al default del rol)."""
    if permission_key not in PORTAL_PERMISSION_KEYS or permission_key in _OWNER_ONLY_PERMISSIONS:
        return
    with db._get_db_connection() as connection:
        if value is None:
            connection.execute(
                "DELETE FROM user_permission_overrides WHERE user_id = ? AND permission_key = ?",
                (user_id, permission_key),
            )
        else:
            connection.execute(
                """
                INSERT INTO user_permission_overrides
                    (user_id, cliente_id, permission_key, allowed, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, permission_key) DO UPDATE SET
                    allowed = excluded.allowed, updated_at = excluded.updated_at
                """,
                (user_id, cliente_id, permission_key, 1 if value else 0, timeutils._utc_now_iso()),
            )
        connection.commit()


def _serialize_auth_user(row: sqlite3.Row) -> AuthUserPublic:
    cliente_id = row["cliente_id"] or ""
    plan = clients._client_plan(cliente_id) if cliente_id else settings.PLAN_DEFAULT
    limits = clients._plan_limits(plan)
    return AuthUserPublic(
        user_id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"],
        portal_role=_portal_role(row),
        cliente_id=cliente_id,
        plan=plan,
        plan_label=str(limits.get("label") or plan.title()),
        last_login_at=row["last_login_at"] or "",
        as_admin_session=_session_is_impersonated(row),
        impersonator_email=_session_impersonator_email(row),
        permissions=sorted(k for k, v in _effective_permissions(row).items() if v),
    )


def _serialize_managed_user(row: sqlite3.Row) -> AuthManagedUser:
    return AuthManagedUser(
        user_id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"],
        portal_role=_portal_role(row),
        cliente_id=row["cliente_id"] or "",
        is_active=bool(row["is_active"]),
        created_at=row["created_at"] or "",
        last_login_at=row["last_login_at"] or "",
    )


def _get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM users WHERE email = ?",
            (textnorm._normalize_email(email),),
        ).fetchone()


def _get_user_by_id(user_id: str) -> Optional[sqlite3.Row]:
    with db._get_db_connection() as connection:
        return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def _list_users(*, role: str = "", cliente_id: str = "", include_inactive: bool = True) -> List[sqlite3.Row]:
    sql = "SELECT * FROM users"
    clauses: List[str] = []
    params: List[Any] = []
    if role:
        clauses.append("role = ?")
        params.append(role)
    if cliente_id:
        clauses.append("cliente_id = ?")
        params.append(cliente_id)
    if not include_inactive:
        clauses.append("is_active = 1")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY role ASC, is_active DESC, display_name COLLATE NOCASE ASC, email COLLATE NOCASE ASC"
    with db._get_db_connection() as connection:
        return connection.execute(sql, tuple(params)).fetchall()


def _active_admin_count() -> int:
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
        ).fetchone()[0]


def _set_user_active(user_id: str, is_active: bool) -> None:
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id),
        )
        connection.commit()


def _update_user_password(user_id: str, new_password: str) -> None:
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash_secret(new_password), user_id),
        )
        connection.commit()


def _update_user_profile(user_id: str, *, email: str, display_name: str) -> sqlite3.Row:
    email_norm = textnorm._normalize_email(email)
    clean_name = textnorm._sanitize_text(display_name)
    if len(clean_name) < 2:
        raise HTTPException(status_code=400, detail="El nombre debe tener al menos 2 caracteres.")

    with db._get_db_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE email = ? AND id <> ?",
            (email_norm, user_id),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Ese email ya esta en uso por otro usuario.")

        connection.execute(
            "UPDATE users SET email = ?, display_name = ? WHERE id = ?",
            (email_norm, clean_name, user_id),
        )
        connection.commit()
        updated = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not updated:
            raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        return updated


def _create_user(
    *,
    email: str,
    password: str,
    role: str,
    display_name: str,
    cliente_id: str = "",
    portal_role: str = "owner",
) -> sqlite3.Row:
    user_id = f"usr_{secrets.token_urlsafe(12)}"
    email_norm = textnorm._normalize_email(email)
    now_iso = timeutils._utc_now_iso()
    password_hash = _hash_secret(password)
    portal_role_norm = portal_role if portal_role in PORTAL_ROLE_LEVELS else "owner"
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, email, password_hash, role, display_name, cliente_id, is_active,
                created_at, last_login_at, portal_role
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, '', ?)
            """,
            (
                user_id, email_norm, password_hash, role, display_name.strip(),
                cliente_id.strip(), now_iso, portal_role_norm,
            ),
        )
        connection.commit()
        return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def _get_user_by_google_sub(google_sub: str) -> Optional[sqlite3.Row]:
    sub = (google_sub or "").strip()
    if not sub:
        return None
    with db._get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM users WHERE google_sub = ?", (sub,)
        ).fetchone()


def _create_user_self_serve(
    *,
    email: str,
    display_name: str,
    password: str = "",
    google_sub: str = "",
    avatar_url: str = "",
    signup_source: str = "self_serve",
    email_verified: bool = False,
) -> sqlite3.Row:
    """Create a self-serve user with optional Google linkage. Password is optional
    if google_sub is set (OAuth-only account). Returns the new user row."""
    if not password and not google_sub:
        raise HTTPException(status_code=400, detail="Password o cuenta Google requerida.")
    if not settings.SIGNUP_ENABLED:
        raise HTTPException(status_code=403, detail="Registro deshabilitado.")
    user_id = f"usr_{secrets.token_urlsafe(12)}"
    email_norm = textnorm._normalize_email(email)
    now_iso = timeutils._utc_now_iso()
    password_hash = _hash_secret(password) if password else _hash_secret(secrets.token_urlsafe(32))
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, email, password_hash, role, display_name, cliente_id,
                is_active, created_at, last_login_at,
                google_sub, email_verified, signup_source, avatar_url
            ) VALUES (?, ?, ?, 'client', ?, '', 1, ?, '', ?, ?, ?, ?)
            """,
            (
                user_id,
                email_norm,
                password_hash,
                display_name.strip() or email_norm.split("@")[0],
                now_iso,
                google_sub.strip(),
                1 if (email_verified or google_sub) else 0,
                signup_source,
                avatar_url.strip(),
            ),
        )
        connection.commit()
        return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


_OAUTH_STATE_TTL_SECONDS = 600


def _oauth_create_state(intent: str = "login", claim: str = "") -> str:
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(16)
    now = time.time()
    cutoff = now - _OAUTH_STATE_TTL_SECONDS
    with db._get_db_connection() as conn:
        conn.execute(
            "INSERT INTO oauth_states (state, nonce, intent, claim, created_at) VALUES (?, ?, ?, ?, ?)",
            (state, nonce, intent, claim or "", now),
        )
        conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (cutoff,))
        conn.commit()
    return state


def _oauth_consume_state(state: str) -> Optional[Dict[str, Any]]:
    if not state:
        return None
    with db._get_db_connection() as conn:
        row = conn.execute(
            "SELECT nonce, intent, claim, created_at FROM oauth_states WHERE state = ?", (state,)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            conn.commit()
    if not row:
        return None
    if time.time() - row["created_at"] > _OAUTH_STATE_TTL_SECONDS:
        return None
    return {"nonce": row["nonce"], "intent": row["intent"], "claim": row["claim"], "created_at": row["created_at"]}


def _google_oauth_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_REDIRECT_URI)


def _gmail_oauth_create_state(admin_user_id: str = "", cliente_id: str = "") -> str:
    state = secrets.token_urlsafe(32)
    now = time.time()
    with db._get_db_connection() as conn:
        conn.execute(
            "INSERT INTO gmail_oauth_states (state, admin_user_id, cliente_id, created_at) VALUES (?, ?, ?, ?)",
            (state, admin_user_id, cliente_id, now),
        )
        conn.execute("DELETE FROM gmail_oauth_states WHERE created_at < ?", (now - _OAUTH_STATE_TTL_SECONDS,))
        conn.commit()
    return state


def _gmail_oauth_consume_state(state: str) -> Optional[Dict[str, Any]]:
    if not state:
        return None
    with db._get_db_connection() as conn:
        row = conn.execute(
            "SELECT admin_user_id, cliente_id, created_at FROM gmail_oauth_states WHERE state = ?",
            (state,),
        ).fetchone()
        if row:
            conn.execute("DELETE FROM gmail_oauth_states WHERE state = ?", (state,))
            conn.commit()
    if not row or time.time() - float(row["created_at"]) > _OAUTH_STATE_TTL_SECONDS:
        return None
    return {
        "admin_user_id": row["admin_user_id"],
        "cliente_id": row["cliente_id"],
        "created_at": row["created_at"],
    }


def _assign_client_user_to_cliente(user_id: str, cliente_id: str) -> sqlite3.Row:
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE users SET role = 'client', cliente_id = ?, is_active = 1 WHERE id = ?",
            (cliente_id.strip(), user_id),
        )
        connection.commit()
        return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def _delete_user(user_id: str) -> None:
    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        connection.commit()


def _ensure_default_portal_admin() -> None:
    if not settings.PORTAL_ADMIN_EMAIL or not settings.PORTAL_ADMIN_PASSWORD:
        return
    existing = _get_user_by_email(settings.PORTAL_ADMIN_EMAIL)
    if existing:
        return
    _create_user(
        email=settings.PORTAL_ADMIN_EMAIL,
        password=settings.PORTAL_ADMIN_PASSWORD,
        role="admin",
        display_name=settings.PORTAL_ADMIN_NAME,
    )
    settings.logger.info("Usuario admin inicial del portal creado para %s", settings.PORTAL_ADMIN_EMAIL)


def _create_auth_session(user_id: str) -> str:
    session_id = f"ses_{secrets.token_urlsafe(10)}"
    session_secret = secrets.token_urlsafe(32)
    now_iso = timeutils._utc_now_iso()
    expires_at = timeutils._session_expires_at()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO auth_sessions (id, user_id, session_token_hash, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, _hash_secret(session_secret), now_iso, expires_at, now_iso),
        )
        connection.commit()
    return f"{session_id}.{session_secret}"


ADMIN_IMPERSONATION_TTL_MINUTES = max(
    5, min(180, int(os.getenv("ADMIN_IMPERSONATION_TTL_MINUTES", "30")))
)


def _create_impersonation_session(
    *,
    target_user_id: str,
    admin_user_id: str,
    admin_email: str,
    ip: str = "",
) -> Tuple[str, str]:
    """Create a short-lived auth_sessions row that proxies as target_user_id.

    Returns (raw_token, session_id). Stamps impersonator_* columns so the
    session is identifiable as admin-impersonation and the portal banner can
    show it. Lifetime = ADMIN_IMPERSONATION_TTL_MINUTES.
    """
    session_id = f"ses_{secrets.token_urlsafe(10)}"
    session_secret = secrets.token_urlsafe(32)
    now = timeutils._utc_now()
    expires = now + timedelta(minutes=ADMIN_IMPERSONATION_TTL_MINUTES)
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO auth_sessions
                (id, user_id, session_token_hash, created_at, expires_at, last_seen_at,
                 impersonator_user_id, impersonator_email, impersonator_ip)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                target_user_id,
                _hash_secret(session_secret),
                now.isoformat(),
                expires.isoformat(),
                now.isoformat(),
                admin_user_id,
                admin_email,
                ip,
            ),
        )
        connection.commit()
    return f"{session_id}.{session_secret}", session_id


def _session_is_impersonated(user_row: Optional[sqlite3.Row]) -> bool:
    if not user_row:
        return False
    try:
        return bool((user_row["impersonator_user_id"] or "").strip())
    except (IndexError, KeyError):
        return False


def _session_impersonator_email(user_row: Optional[sqlite3.Row]) -> str:
    if not user_row:
        return ""
    try:
        return str(user_row["impersonator_email"] or "")
    except (IndexError, KeyError):
        return ""


def _delete_auth_session(raw_token: str) -> None:
    session_id, session_secret = _compound_token_parts(raw_token, "ses")
    with db._get_db_connection() as connection:
        if session_id and session_secret:
            row = connection.execute(
                "SELECT id, session_token_hash FROM auth_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row and _verify_secret(session_secret, row["session_token_hash"]):
                connection.execute("DELETE FROM auth_sessions WHERE id = ?", (session_id,))
                connection.commit()
                return

        rows = connection.execute("SELECT id, session_token_hash FROM auth_sessions").fetchall()
        for row in rows:
            if _verify_secret(raw_token, row["session_token_hash"]):
                connection.execute("DELETE FROM auth_sessions WHERE id = ?", (row["id"],))
                connection.commit()
                return


def _delete_user_auth_sessions(user_id: str, *, keep_session_id: str = "") -> None:
    with db._get_db_connection() as connection:
        if keep_session_id:
            connection.execute(
                "DELETE FROM auth_sessions WHERE user_id = ? AND id <> ?",
                (user_id, keep_session_id),
            )
        else:
            connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        connection.commit()


def _cleanup_password_reset_tokens() -> None:
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            "DELETE FROM password_reset_tokens WHERE used_at <> '' OR expires_at <= ?",
            (now_iso,),
        )
        connection.commit()


def _create_password_reset_token(user_id: str, requested_from_ip: str = "") -> str:
    reset_id = f"prt_{secrets.token_urlsafe(10)}"
    reset_secret = secrets.token_urlsafe(32)
    now_iso = timeutils._utc_now_iso()
    expires_at = timeutils._expires_at_in_hours(settings.PASSWORD_RESET_TOKEN_HOURS)
    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
        connection.execute(
            """
            INSERT INTO password_reset_tokens (
                id, user_id, token_hash, created_at, expires_at, used_at, requested_from_ip
            ) VALUES (?, ?, ?, ?, ?, '', ?)
            """,
            (
                reset_id,
                user_id,
                _hash_secret(reset_secret),
                now_iso,
                expires_at,
                requested_from_ip.strip(),
            ),
        )
        connection.commit()
    return f"{reset_id}.{reset_secret}"


def _consume_password_reset_token(public_token: str) -> sqlite3.Row:
    _cleanup_password_reset_tokens()
    reset_id, reset_secret = _compound_token_parts(public_token, "prt")
    if not reset_id or not reset_secret:
        raise HTTPException(status_code=400, detail="El enlace de recuperacion no es valido.")

    with db._get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT t.id AS reset_token_id, t.user_id, t.token_hash, t.expires_at, t.used_at, u.*
            FROM password_reset_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.id = ?
            """,
            (reset_id,),
        ).fetchone()
        if not row or not row["is_active"]:
            raise HTTPException(status_code=400, detail="El enlace de recuperacion ya no es valido.")
        if row["used_at"]:
            raise HTTPException(status_code=400, detail="Este enlace de recuperacion ya se ha usado.")
        if not _verify_secret(reset_secret, row["token_hash"]):
            raise HTTPException(status_code=400, detail="El enlace de recuperacion no es valido.")
        if row["expires_at"] <= timeutils._utc_now_iso():
            raise HTTPException(status_code=400, detail="El enlace de recuperacion ha caducado.")

        connection.execute(
            "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
            (timeutils._utc_now_iso(), reset_id),
        )
        connection.commit()
        return row


def _password_reset_url(public_token: str, request: Optional[Request] = None) -> str:
    base_url = textnorm._preferred_public_base_url(request) or ""
    if not base_url:
        raise RuntimeError("No se ha podido construir la URL publica del portal.")
    return f"{base_url}/acceso?reset_token={quote(public_token, safe='')}"


def _platform_access_url(request: Optional[Request] = None) -> str:
    base_url = (textnorm._preferred_public_base_url(request) or settings.APP_BASE_URL or "https://app.vantelia.es").rstrip("/")
    return f"{base_url}/acceso"


def _cleanup_auth_sessions() -> None:
    now_iso = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now_iso,))
        connection.commit()


def _get_session_user(session_token: str) -> Optional[sqlite3.Row]:
    if not session_token:
        return None
    _cleanup_auth_sessions()
    session_id, session_secret = _compound_token_parts(session_token, "ses")
    with db._get_db_connection() as connection:
        if session_id and session_secret:
            row = connection.execute(
                """
                SELECT s.id AS session_id, s.session_token_hash, s.expires_at,
                       s.impersonator_user_id, s.impersonator_email, s.impersonator_ip, u.*
                FROM auth_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.id = ? AND u.is_active = 1
                """,
                (session_id,),
            ).fetchone()
            if row and _verify_secret(session_secret, row["session_token_hash"]):
                connection.execute(
                    "UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?",
                    (timeutils._utc_now_iso(), row["session_id"]),
                )
                connection.commit()
                return row

        rows = connection.execute(
            """
            SELECT s.id AS session_id, s.session_token_hash, s.expires_at,
                   s.impersonator_user_id, s.impersonator_email, s.impersonator_ip, u.*
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE u.is_active = 1
            """
        ).fetchall()
        for row in rows:
            if _verify_secret(session_token, row["session_token_hash"]):
                connection.execute(
                    "UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?",
                    (timeutils._utc_now_iso(), row["session_id"]),
                )
                connection.commit()
                return row
    return None


def _redirect_for_role(role: str) -> str:
    if role == "admin":
        return "/dashboard"
    return "/app"


def _set_portal_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        settings.PORTAL_COOKIE_NAME,
        raw_token,
        max_age=max(3600, settings.PORTAL_SESSION_HOURS * 3600),
        httponly=True,
        secure=settings.APP_BASE_URL.startswith("https://"),
        samesite="lax",
        domain=settings.PORTAL_COOKIE_DOMAIN or None,
        path="/",
    )


def _clear_portal_cookie(response: Response) -> None:
    response.delete_cookie(settings.PORTAL_COOKIE_NAME, path="/", samesite="lax", domain=settings.PORTAL_COOKIE_DOMAIN or None)


def _set_admin_return_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        settings.ADMIN_RETURN_COOKIE_NAME,
        raw_token,
        max_age=max(3600, settings.PORTAL_SESSION_HOURS * 3600),
        httponly=True,
        secure=settings.APP_BASE_URL.startswith("https://"),
        samesite="lax",
        domain=settings.PORTAL_COOKIE_DOMAIN or None,
        path="/",
    )


def _clear_admin_return_cookie(response: Response) -> None:
    response.delete_cookie(settings.ADMIN_RETURN_COOKIE_NAME, path="/", samesite="lax", domain=settings.PORTAL_COOKIE_DOMAIN or None)


def _gmail_redirect_uri() -> str:
    if settings.GOOGLE_GMAIL_REDIRECT_URI:
        return settings.GOOGLE_GMAIL_REDIRECT_URI
    if settings.APP_BASE_URL:
        return f"{settings.APP_BASE_URL}/auth/google/gmail/callback"
    return ""


def _gmail_oauth_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and _gmail_redirect_uri() and _gmail_fernet())


def _gmail_fernet() -> Optional[Fernet]:
    raw_key = settings.GMAIL_TOKEN_ENCRYPTION_KEY or settings.ADMIN_API_TOKEN
    if not raw_key:
        return None
    try:
        if settings.GMAIL_TOKEN_ENCRYPTION_KEY:
            return Fernet(settings.GMAIL_TOKEN_ENCRYPTION_KEY.encode("ascii"))
    except (ValueError, UnicodeError):
        settings.logger.error("GMAIL_TOKEN_ENCRYPTION_KEY no es una clave Fernet valida.")
        return None
    derived = base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode("utf-8")).digest())
    return Fernet(derived)


def _channel_fernet() -> Fernet:
    if not settings.OAUTH_TOKEN_ENCRYPTION_KEY:
        raise RuntimeError("OAUTH_TOKEN_ENCRYPTION_KEY no esta configurada.")
    try:
        return Fernet(settings.OAUTH_TOKEN_ENCRYPTION_KEY.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("OAUTH_TOKEN_ENCRYPTION_KEY no es una clave Fernet valida.") from exc


def _count_client_users(cliente_id: str) -> int:
    try:
        with db._get_db_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'client' AND cliente_id = ? AND is_active = 1",
                (cliente_id,),
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def _enforce_session_cookie_origin(request: Request, portal_session: Optional[str]) -> None:
    if not portal_session or request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    request_origin = textnorm._request_origin(request)
    if not request_origin:
        return
    app_origin = textnorm._normalize_origin_value(textnorm._public_base_url(request))
    if request_origin != app_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origen no autorizado para una accion autenticada.",
        )


def _get_authenticated_portal_user_or_none(
    portal_session: Optional[str],
) -> Optional[sqlite3.Row]:
    if not portal_session:
        return None
    user = _get_session_user(portal_session)
    if user is None:
        return None
    # Defensa en profundidad: si el tenant del usuario ya no existe (cliente borrado o
    # demo expirada), la sesion deja de valer YA. Sin esto, un usuario huerfano podia
    # seguir entrando a un panel a medias. Los self-serve sin bot (cliente_id vacio,
    # wizard pendiente) y los admin siguen entrando con normalidad.
    if user["role"] == "client":
        cliente_id = (user["cliente_id"] or "").strip()
        if cliente_id and cliente_id not in appstate.CONFIG_CLIENTES:
            settings.logger.warning(
                "Sesion rechazada: usuario %s apunta a tenant inexistente %s", user["email"], cliente_id
            )
            return None
    return user


def _require_authenticated_portal_user(
    request: Request,
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
) -> sqlite3.Row:
    _enforce_session_cookie_origin(request, portal_session)
    user = _get_authenticated_portal_user_or_none(portal_session)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesion no valida o expirada.")
    return user


def _require_authenticated_admin_user(
    user: sqlite3.Row = Depends(_require_authenticated_portal_user),
) -> sqlite3.Row:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso solo para administradores.")
    return user


def _load_managed_user_or_404(user_id: str) -> sqlite3.Row:
    row = _get_user_by_id(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    return row


def _assert_admin_can_manage_user(current_user: sqlite3.Row, target_user: sqlite3.Row, action: str) -> None:
    if current_user["id"] == target_user["id"]:
        raise HTTPException(status_code=400, detail=f"No puedes {action} tu propio usuario desde este menu.")
    if target_user["role"] == "admin" and _active_admin_count() <= 1:
        raise HTTPException(
            status_code=400,
            detail="No puedes dejar el portal sin ningun administrador activo.",
        )


def _require_admin_token(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
) -> None:
    portal_user = _get_authenticated_portal_user_or_none(portal_session)
    if portal_user and portal_user["role"] == "admin":
        return

    if not settings.ADMIN_API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Los endpoints de administracion no estan habilitados.",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta token admin o sesion valida.")

    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, settings.ADMIN_API_TOKEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token admin invalido")


def _require_self_serve_user(
    portal_session: Optional[str] = Cookie(default=None, alias=settings.PORTAL_COOKIE_NAME),
) -> sqlite3.Row:
    user = _get_authenticated_portal_user_or_none(portal_session)
    if not user:
        raise HTTPException(status_code=401, detail="Sesion requerida.")
    return user


def _resolve_cliente_for_self_serve_user(user: sqlite3.Row) -> str:
    cliente_id = (user["cliente_id"] or "").strip()
    if not cliente_id:
        raise HTTPException(status_code=400, detail="Aun no has creado un bot. Completa el wizard.")
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Bot no encontrado.")
    return cliente_id


def _period_start_iso_for_user(user_id: str) -> str:
    sub = db.db_get_subscription_for_user(user_id)
    if sub and sub["current_period_start"]:
        return sub["current_period_start"]
    # Default: start of current calendar month UTC
    now = timeutils._utc_now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _user_plan(user: sqlite3.Row) -> str:
    sub = db.db_get_subscription_for_user(user["id"])
    return (sub["plan"] if sub else "free").lower()




def _encrypt_channel_secret(value: str) -> str:
    return _channel_fernet().encrypt(str(value or "").encode("utf-8")).decode("ascii") if value else ""


def _decrypt_channel_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _channel_fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("No se pudo descifrar la credencial del canal.") from exc


def _ensure_channel_settings(cliente_id: str) -> sqlite3.Row:
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_channel_settings (cliente_id, created_at, updated_at)
            VALUES (?, ?, ?) ON CONFLICT(cliente_id) DO NOTHING
            """,
            (cliente_id, now, now),
        )
        connection.commit()
        return connection.execute(
            "SELECT * FROM client_channel_settings WHERE cliente_id=?", (cliente_id,)
        ).fetchone()


def _channel_audit(
    cliente_id: str, channel: str, event_type: str, provider: str, success: bool, detail: str = ""
) -> None:
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_channel_audit
                (cliente_id, channel, event_type, provider, success, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (cliente_id, channel, event_type, provider, int(success), textnorm._sanitize_text(detail)[:500], timeutils._utc_now_iso()),
        )
        connection.commit()








def _check_rate_limit(bucket_key: str, limit: int) -> None:
    now = time.time()
    with appstate.state_lock:
        bucket = appstate.rate_limit_buckets.setdefault(bucket_key, [])
        bucket[:] = [timestamp for timestamp in bucket if now - timestamp < settings.RATE_LIMIT_WINDOW_SECONDS]
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Se ha alcanzado el limite temporal de peticiones.",
            )
        bucket.append(now)


def _enforce_allowed_origin(request: Request, cliente_id: str) -> None:
    config = clients._get_client_config(cliente_id)
    allowed_origins = set(config.get("allowed_origins", []))
    app_origin = textnorm._normalize_origin_value(textnorm._public_base_url(request))
    allowed_origins.add(app_origin)
    request_origin = textnorm._request_origin(request)

    if allowed_origins and not request_origin:
        raise HTTPException(
            status_code=403,
            detail="No se ha podido verificar el dominio de origen de la peticion.",
        )

    if request_origin and allowed_origins and request_origin not in allowed_origins:
        raise HTTPException(status_code=403, detail="Dominio no autorizado para este cliente")


