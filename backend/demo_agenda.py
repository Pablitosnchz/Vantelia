"""Demos: crear un tenant de prueba y llenarlo de datos de ejemplo.

Dos cosas distintas conviven aqui:

1. **Demo de captacion** — `build_demo_tenant(...)`: a partir de la WEB de un
   prospect monta un tenant temporal con su contenido (rastrea la web con
   `onboarding_utils.run_onboarding`), lo registra con TTL y lo deja listo para
   ensenarselo. Es la FUENTE UNICA: la usan tanto `POST /demo/generate` como la
   pre-generacion al abrir el email de captacion. `_purge_expired_demos` los
   caduca.
2. **Demo dentro de un tenant real** — `_seed_demo_agenda` + `_seed_demo_commerce`:
   llenan la agenda y el mostrador de un cliente que ya existe para poder
   ensenarle el panel con algo dentro. Reversible del todo.

Todo lo sembrado se reconoce por PREFIJO de id, y de ahi que la purga sea
fiable: citas con `source='demo_seed'`, empleados `empdemo_*`, centros
`locdemo_*`, productos `proddemo_*`, bonos `pkgdemo_*`, tarjetas `gcdemo_*`,
ventas `saledemo_*`, compras `ppdemo_*`. Los `_seed_*` son idempotentes: vuelven
a sembrar limpiando antes lo suyo, y NUNCA tocan datos reales del cliente.

Endpoints: `POST/DELETE /admin/clientes/{id}/demo-agenda`.
"""
from __future__ import annotations

import json
import math
import os
import random
import re as _re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote as _urlquote, urlparse as _urlparse

from fastapi import HTTPException, Request, status

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from backend import agenda, appstate, booking, clients, db, settings, textnorm, timeutils

DEMO_TENANT_PREFIX = "demo_auto_"
_DEMO_REGISTRY_MIGRATION_KEY = "json_migrated_v2"


DEMO_TTL_SECONDS = int(os.getenv("DEMO_TENANT_TTL_SECONDS", "3600"))


# El registro y las reservas viven en SQLite: es la fuente compartida entre
# workers. El lock de fichero protege ademas las escrituras de config.json,
# que siguen siendo un recurso de filesystem compartido.
_DEMO_GENERATION_LOCKS = tuple(threading.Lock() for _ in range(64))
_DEMO_REGISTRY_LOCK = threading.RLock()
_DEMO_LIFECYCLE_LOCAL = threading.local()
_DEMO_GENERATION_LEASE_SECONDS = max(
    300, int(os.getenv("DEMO_GENERATION_LEASE_SECONDS", "900"))
)
_DEMO_GENERATION_WAIT_SECONDS = max(
    10, int(os.getenv("DEMO_GENERATION_WAIT_SECONDS", "180"))
)


def _demo_generation_lock_for_email(email: str) -> threading.Lock:
    email_key = (email or "").strip().lower()
    return _DEMO_GENERATION_LOCKS[hash(email_key) % len(_DEMO_GENERATION_LOCKS)]


def _acquire_demo_filesystem_lock():
    lock_path = settings.STORAGE_DIR / "locks" / "demo_lifecycle.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(0.05)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _release_demo_filesystem_lock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@contextmanager
def _demo_lifecycle_guard() -> Iterator[None]:
    """Lock reentrante local + advisory lock compartido por el bind mount."""
    with _DEMO_REGISTRY_LOCK:
        depth = int(getattr(_DEMO_LIFECYCLE_LOCAL, "depth", 0))
        if depth == 0:
            _DEMO_LIFECYCLE_LOCAL.handle = _acquire_demo_filesystem_lock()
        _DEMO_LIFECYCLE_LOCAL.depth = depth + 1
        try:
            yield
        finally:
            next_depth = int(getattr(_DEMO_LIFECYCLE_LOCAL, "depth", 1)) - 1
            _DEMO_LIFECYCLE_LOCAL.depth = next_depth
            if next_depth == 0:
                handle = getattr(_DEMO_LIFECYCLE_LOCAL, "handle", None)
                _DEMO_LIFECYCLE_LOCAL.handle = None
                if handle is not None:
                    _release_demo_filesystem_lock(handle)


def _canonical_demo_url(cliente_id: str) -> str:
    """URL publica controlada por configuracion, nunca por Host de la request."""
    textnorm._assert_valid_client_id(cliente_id)
    base_url = (settings.APP_BASE_URL or "https://app.vantelia.es").rstrip("/")
    return f"{base_url}/demo/{cliente_id}"


def _demo_registry_path() -> Path:
    return settings.DATA_DIR / "demo_tenants.json"


def _ensure_demo_registry_schema(connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS demo_tenants_registry (
               email TEXT PRIMARY KEY,
               cliente_id TEXT NOT NULL DEFAULT '',
               created_ts REAL NOT NULL DEFAULT 0,
               state TEXT NOT NULL DEFAULT 'generating',
               lease_owner TEXT NOT NULL DEFAULT '',
               lease_expires_ts REAL NOT NULL DEFAULT 0,
               updated_ts REAL NOT NULL DEFAULT 0
           )"""
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_demo_registry_cliente "
        "ON demo_tenants_registry(cliente_id) WHERE cliente_id <> ''"
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS demo_registry_meta (
               key TEXT PRIMARY KEY,
               value TEXT NOT NULL DEFAULT ''
           )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS demo_tenant_cleanup_queue (
               cliente_id TEXT PRIMARY KEY,
               email TEXT NOT NULL DEFAULT '',
               created_ts REAL NOT NULL DEFAULT 0,
               reason TEXT NOT NULL DEFAULT '',
               state TEXT NOT NULL DEFAULT 'queued',
               lease_owner TEXT NOT NULL DEFAULT '',
               lease_expires_ts REAL NOT NULL DEFAULT 0,
               updated_ts REAL NOT NULL DEFAULT 0
           )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_demo_cleanup_state "
        "ON demo_tenant_cleanup_queue(state, lease_expires_ts)"
    )
    connection.commit()


def _queue_demo_cleanup_row(
    connection,
    *,
    cliente_id: str,
    email: str,
    created_ts: float,
    reason: str,
) -> None:
    if not cliente_id or not settings.CLIENT_ID_PATTERN.match(cliente_id):
        raise ValueError(f"cliente_id de demo invalido para cleanup: {cliente_id!r}")
    connection.execute(
        """INSERT INTO demo_tenant_cleanup_queue
           (cliente_id, email, created_ts, reason, state, lease_owner,
            lease_expires_ts, updated_ts)
           VALUES (?,?,?,?,'queued','',0,?)
           ON CONFLICT(cliente_id) DO UPDATE SET
               email=excluded.email,
               created_ts=excluded.created_ts,
               reason=excluded.reason,
               state=CASE
                   WHEN demo_tenant_cleanup_queue.state='purging' THEN 'purging'
                   ELSE 'queued'
               END,
               updated_ts=excluded.updated_ts""",
        (
            cliente_id,
            (email or "").strip().lower(),
            float(created_ts),
            (reason or "cleanup")[:80],
            time.time(),
        ),
    )


def _validated_legacy_demo_registry(path: Path) -> Dict[str, float]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Registro JSON de demos corrupto; corrige el archivo para reintentar la migracion."
        ) from exc
    if not isinstance(raw, dict):
        raise RuntimeError("Registro JSON de demos invalido: se esperaba un objeto.")
    legacy: Dict[str, float] = {}
    for raw_cliente_id, raw_created_ts in raw.items():
        cliente_id = str(raw_cliente_id or "").strip()
        if not settings.CLIENT_ID_PATTERN.match(cliente_id):
            raise RuntimeError(
                f"Registro JSON de demos invalido: cliente_id {cliente_id!r}."
            )
        try:
            created_ts = float(raw_created_ts)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Registro JSON de demos invalido para {cliente_id}: timestamp."
            ) from exc
        if not math.isfinite(created_ts) or created_ts < 0:
            raise RuntimeError(
                f"Registro JSON de demos invalido para {cliente_id}: timestamp."
            )
        legacy[cliente_id] = created_ts
    return legacy


def _ensure_demo_registry_migrated(connection) -> None:
    _ensure_demo_registry_schema(connection)
    migrated = connection.execute(
        "SELECT 1 FROM demo_registry_meta WHERE key=?",
        (_DEMO_REGISTRY_MIGRATION_KEY,),
    ).fetchone()
    if migrated:
        return
    connection.execute("BEGIN IMMEDIATE")
    try:
        migrated = connection.execute(
            "SELECT 1 FROM demo_registry_meta WHERE key=?",
            (_DEMO_REGISTRY_MIGRATION_KEY,),
        ).fetchone()
        if not migrated:
            path = _demo_registry_path()
            legacy = _validated_legacy_demo_registry(path) if path.exists() else {}
            now_ts = time.time()
            grouped: Dict[str, List[Tuple[str, float]]] = {}
            for cliente_id, created_ts in legacy.items():
                config = appstate.CONFIG_CLIENTES.get(cliente_id, {})
                email = str(
                    (config.get("contacto") or {}).get("email") or ""
                ).strip().lower()
                email_key = email or f"legacy:{cliente_id}"
                grouped.setdefault(email_key, []).append((cliente_id, created_ts))

            for email_key, candidates in grouped.items():
                candidates.sort(key=lambda item: (item[1], item[0]), reverse=True)
                existing = connection.execute(
                    """SELECT cliente_id, created_ts, state
                       FROM demo_tenants_registry WHERE email=?""",
                    (email_key,),
                ).fetchone()
                existing_id = str(existing["cliente_id"] or "") if existing else ""
                choices = list(candidates)
                if existing_id:
                    choices.append((existing_id, float(existing["created_ts"] or 0)))
                canonical_id, canonical_ts = max(
                    choices, key=lambda item: (item[1], item[0])
                )
                if (
                    existing
                    and existing_id
                    and str(existing["state"] or "") in {"generating", "purging"}
                ):
                    canonical_id = existing_id
                    canonical_ts = float(existing["created_ts"] or canonical_ts)
                elif not existing:
                    connection.execute(
                        """INSERT INTO demo_tenants_registry
                           (email, cliente_id, created_ts, state, lease_owner,
                            lease_expires_ts, updated_ts)
                           VALUES (?,?,?,'active','',0,?)""",
                        (email_key, canonical_id, canonical_ts, now_ts),
                    )
                elif canonical_id != existing_id:
                    if existing_id:
                        _queue_demo_cleanup_row(
                            connection,
                            cliente_id=existing_id,
                            email=email_key,
                            created_ts=float(existing["created_ts"] or 0),
                            reason="migration_duplicate_email",
                        )
                    connection.execute(
                        """UPDATE demo_tenants_registry
                           SET cliente_id=?, created_ts=?, state='active',
                               lease_owner='', lease_expires_ts=0, updated_ts=?
                           WHERE email=?""",
                        (canonical_id, canonical_ts, now_ts, email_key),
                    )
                for discarded_id, discarded_ts in candidates:
                    if discarded_id == canonical_id:
                        continue
                    _queue_demo_cleanup_row(
                        connection,
                        cliente_id=discarded_id,
                        email=email_key,
                        created_ts=discarded_ts,
                        reason="migration_duplicate_email",
                    )
                    settings.logger.warning(
                        "Demo legacy duplicada para %s: se conserva %s y se encola %s para cleanup.",
                        email_key,
                        canonical_id,
                        discarded_id,
                    )
            connection.execute(
                "INSERT OR REPLACE INTO demo_registry_meta (key, value) VALUES (?, '1')",
                (_DEMO_REGISTRY_MIGRATION_KEY,),
            )
        connection.commit()
    except Exception as exc:
        connection.rollback()
        settings.logger.error("Migracion del registro JSON de demos fallida: %s", exc)
        raise


def _demo_registry_email(cliente_id: str, email: str = "") -> str:
    email_clean = (email or "").strip().lower()
    if email_clean:
        return email_clean
    config = appstate.CONFIG_CLIENTES.get(cliente_id, {})
    configured = str((config.get("contacto") or {}).get("email") or "").strip().lower()
    return configured or f"legacy:{cliente_id}"


def _load_demo_registry() -> Dict[str, float]:
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        rows = connection.execute(
            """SELECT cliente_id, created_ts FROM demo_tenants_registry
               WHERE state='active' AND cliente_id<>''"""
        ).fetchall()
    return {str(row["cliente_id"]): float(row["created_ts"]) for row in rows}



def _register_demo_tenant(
    cliente_id: str,
    email: str = "",
    *,
    created_ts: Optional[float] = None,
    lease_owner: str = "",
) -> bool:
    email_key = _demo_registry_email(cliente_id, email)
    timestamp = float(created_ts if created_ts is not None else time.time())
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        if lease_owner:
            cursor = connection.execute(
                """UPDATE demo_tenants_registry
                   SET created_ts=?, state='active', lease_owner='',
                       lease_expires_ts=0, updated_ts=?
                   WHERE email=? AND cliente_id=? AND state='generating'
                     AND lease_owner=? AND lease_expires_ts>?""",
                (
                    timestamp,
                    time.time(),
                    email_key,
                    cliente_id,
                    lease_owner,
                    time.time(),
                ),
            )
        else:
            cursor = connection.execute(
                """INSERT INTO demo_tenants_registry
                   (email, cliente_id, created_ts, state, lease_owner,
                    lease_expires_ts, updated_ts)
                   VALUES (?,?,?,'active','',0,?)
                   ON CONFLICT(email) DO UPDATE SET
                       cliente_id=excluded.cliente_id,
                       created_ts=excluded.created_ts,
                       state='active', lease_owner='', lease_expires_ts=0,
                       updated_ts=excluded.updated_ts""",
                (email_key, cliente_id, timestamp, time.time()),
            )
        connection.commit()
        return cursor.rowcount == 1


def _unregister_demo_tenant(
    cliente_id: str, *, expected_created_ts: Optional[float] = None
) -> bool:
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        if expected_created_ts is None:
            cursor = connection.execute(
                "DELETE FROM demo_tenants_registry WHERE cliente_id=?", (cliente_id,)
            )
        else:
            cursor = connection.execute(
                """DELETE FROM demo_tenants_registry
                   WHERE cliente_id=? AND created_ts=?""",
                (cliente_id, float(expected_created_ts)),
            )
        cleanup_cursor = connection.execute(
            "DELETE FROM demo_tenant_cleanup_queue WHERE cliente_id=?",
            (cliente_id,),
        )
        connection.commit()
        return cursor.rowcount == 1 or cleanup_cursor.rowcount == 1


def _demo_registry_row_for_cliente(cliente_id: str):
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        return connection.execute(
            "SELECT * FROM demo_tenants_registry WHERE cliente_id=?", (cliente_id,)
        ).fetchone()


def _demo_is_active_unclaimed(cliente_id: str) -> bool:
    if not cliente_id.startswith(DEMO_TENANT_PREFIX):
        return False
    row = _demo_registry_row_for_cliente(cliente_id)
    if not row or row["state"] != "active":
        return False
    if time.time() - float(row["created_ts"] or 0) > DEMO_TTL_SECONDS:
        return False
    return not bool(db.db_get_client_owner(cliente_id))


def _reserve_demo_generation(
    email: str, lease_owner: str, proposed_cliente_id: str
) -> Tuple[str, str, float]:
    """Reserva email+cliente antes del build.

    Devuelve acquired|takeover|wait|reused, cliente_id reservado, created_ts.
    """
    email_key = (email or "").strip().lower()
    if not email_key:
        raise ValueError("email requerido para generar demo")
    textnorm._assert_valid_client_id(proposed_cliente_id)
    if not proposed_cliente_id.startswith(DEMO_TENANT_PREFIX):
        raise ValueError("cliente_id reservado invalido para auto-demo")
    now_ts = time.time()
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT * FROM demo_tenants_registry WHERE email=?", (email_key,)
            ).fetchone()
            if row:
                state_value = str(row["state"] or "")
                created_ts = float(row["created_ts"] or 0)
                if (
                    state_value == "active"
                    and row["cliente_id"]
                    and now_ts - created_ts < DEMO_TTL_SECONDS
                ):
                    connection.commit()
                    return "reused", str(row["cliente_id"]), created_ts
                if (
                    state_value == "generating"
                    and float(row["lease_expires_ts"] or 0) > now_ts
                ) or state_value == "purging":
                    connection.commit()
                    return "wait", str(row["cliente_id"] or ""), created_ts
                if state_value == "generating":
                    reserved_id = str(row["cliente_id"] or proposed_cliente_id)
                    connection.execute(
                        """UPDATE demo_tenants_registry
                           SET cliente_id=?, created_ts=?, state='generating',
                               lease_owner=?, lease_expires_ts=?, updated_ts=?
                           WHERE email=?""",
                        (
                            reserved_id,
                            now_ts,
                            lease_owner,
                            now_ts + _DEMO_GENERATION_LEASE_SECONDS,
                            now_ts,
                            email_key,
                        ),
                    )
                    connection.commit()
                    return "takeover", reserved_id, now_ts

                old_cliente_id = str(row["cliente_id"] or "")
                if old_cliente_id:
                    owner_row = connection.execute(
                        "SELECT owner_user_id FROM clientes WHERE cliente_id=?",
                        (old_cliente_id,),
                    ).fetchone()
                    if not owner_row or not str(owner_row["owner_user_id"] or ""):
                        _queue_demo_cleanup_row(
                            connection,
                            cliente_id=old_cliente_id,
                            email=email_key,
                            created_ts=created_ts,
                            reason="expired_replaced",
                        )
                connection.execute(
                    """UPDATE demo_tenants_registry
                       SET cliente_id=?, created_ts=?, state='generating',
                           lease_owner=?, lease_expires_ts=?, updated_ts=?
                       WHERE email=?""",
                    (
                        proposed_cliente_id,
                        now_ts,
                        lease_owner,
                        now_ts + _DEMO_GENERATION_LEASE_SECONDS,
                        now_ts,
                        email_key,
                    ),
                )
                connection.commit()
                return "acquired", proposed_cliente_id, now_ts
            connection.execute(
                """INSERT INTO demo_tenants_registry
                   (email, cliente_id, created_ts, state, lease_owner,
                    lease_expires_ts, updated_ts)
                   VALUES (?,?,?,'generating',?,?,?)""",
                (
                    email_key,
                    proposed_cliente_id,
                    now_ts,
                    lease_owner,
                    now_ts + _DEMO_GENERATION_LEASE_SECONDS,
                    now_ts,
                ),
            )
            connection.commit()
            return "acquired", proposed_cliente_id, now_ts
        except Exception:
            connection.rollback()
            raise


def _release_demo_generation(email: str, lease_owner: str) -> None:
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        connection.execute(
            """DELETE FROM demo_tenants_registry
               WHERE email=? AND state='generating' AND lease_owner=?""",
            ((email or "").strip().lower(), lease_owner),
        )
        connection.commit()


def _expire_demo_generation(email: str, lease_owner: str) -> None:
    """Deja una reserva fallida visible para takeover/purga inmediata."""
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        connection.execute(
            """UPDATE demo_tenants_registry
               SET lease_expires_ts=0, updated_ts=?
               WHERE email=? AND state='generating' AND lease_owner=?""",
            (time.time(), (email or "").strip().lower(), lease_owner),
        )
        connection.commit()


def _renew_demo_generation(email: str, lease_owner: str) -> bool:
    now_ts = time.time()
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        cursor = connection.execute(
            """UPDATE demo_tenants_registry
               SET lease_expires_ts=?, updated_ts=?
               WHERE email=? AND state='generating' AND lease_owner=?""",
            (
                now_ts + _DEMO_GENERATION_LEASE_SECONDS,
                now_ts,
                (email or "").strip().lower(),
                lease_owner,
            ),
        )
        connection.commit()
        return cursor.rowcount == 1


@contextmanager
def _demo_generation_heartbeat(email: str, lease_owner: str) -> Iterator[None]:
    """Renueva el lease mientras scraping/indexado mantienen vivo el build."""
    if not _renew_demo_generation(email, lease_owner):
        raise RuntimeError("La reserva de generacion de demo ya no pertenece al worker.")
    stop_event = threading.Event()
    interval = max(0.1, min(30.0, _DEMO_GENERATION_LEASE_SECONDS / 3.0))

    def _heartbeat_worker() -> None:
        while not stop_event.wait(interval):
            try:
                if not _renew_demo_generation(email, lease_owner):
                    return
            except Exception as exc:  # noqa: BLE001
                settings.logger.warning(
                    "No se pudo renovar lease de demo para %s: %s", email, exc
                )

    heartbeat_thread = threading.Thread(
        target=_heartbeat_worker,
        name="vantelia-demo-generation-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        yield
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=max(1.0, interval + 0.5))


def _demo_generation_reservation_owned(
    email: str, lease_owner: str, cliente_id: str = ""
) -> bool:
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        params: List[Any] = [
            (email or "").strip().lower(),
            lease_owner,
            time.time(),
        ]
        cliente_clause = ""
        if cliente_id:
            cliente_clause = " AND cliente_id=?"
            params.append(cliente_id)
        row = connection.execute(
            """SELECT 1 FROM demo_tenants_registry
               WHERE email=? AND state='generating' AND lease_owner=?
                 AND lease_expires_ts>?"""
            + cliente_clause,
            tuple(params),
        ).fetchone()
    return bool(row)


def _synthetic_request():
    """Request minimo para reutilizar helpers que exigen Request en generacion
    en segundo plano (pre-generacion al abrir el email). _public_base_url usa
    APP_BASE_URL configurado, asi que no lee cabeceras reales."""
    from starlette.requests import Request

    base = (settings.APP_BASE_URL or "https://app.vantelia.es").rstrip("/")
    parsed = _urlparse(base)
    scheme = parsed.scheme or "https"
    host = parsed.hostname or "app.vantelia.es"
    port = parsed.port or (443 if scheme == "https" else 80)
    scope = {
        "type": "http", "method": "POST", "path": "/demo/generate",
        "headers": [(b"host", host.encode())], "scheme": scheme,
        "server": (host, port), "query_string": b"", "client": ("127.0.0.1", 0),
    }
    return Request(scope)


def _existing_demo_for_email(email: str):
    """(cliente_id, created_ts) de una demo viva para ese email, o (None, None)."""
    email_lower = (email or "").strip().lower()
    if not email_lower:
        return None, None
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        row = connection.execute(
            """SELECT cliente_id, created_ts FROM demo_tenants_registry
               WHERE email=? AND state='active' AND cliente_id<>''""",
            (email_lower,),
        ).fetchone()
    if row and time.time() - float(row["created_ts"] or 0) < DEMO_TTL_SECONDS:
        return str(row["cliente_id"]), float(row["created_ts"])
    return None, None


def _new_demo_cliente_id(nombre_empresa: str) -> str:
    import onboarding_utils

    base_slug = (
        onboarding_utils.slugify_company((nombre_empresa or "Empresa").strip()).lower()[:30]
        or "empresa"
    )
    cliente_id = f"{DEMO_TENANT_PREFIX}{base_slug}_{secrets.token_hex(3)}"
    textnorm._assert_valid_client_id(cliente_id)
    return cliente_id


def _cleanup_reserved_demo_tenant(cliente_id: str) -> bool:
    """Compensa efectos parciales conservando la fila registry hasta terminar."""
    if not cliente_id or db.db_get_client_owner(cliente_id):
        return False
    registry_row = _demo_registry_row_for_cliente(cliente_id)
    if registry_row and str(registry_row["state"] or "") == "active":
        # Un sucesor pudo completar la misma reserva entre la perdida del lease
        # y esta compensacion; nunca borrar un tenant ya activado.
        return True
    try:
        clients._reload_runtime_configs_from_disk()
        if cliente_id in appstate.CONFIG_CLIENTES:
            clients._delete_client_everywhere(
                cliente_id, skip_demo_registry_cleanup=True
            )
        else:
            clients._purge_client_data(
                cliente_id, skip_demo_registry_cleanup=True
            )
        return True
    except Exception as exc:  # noqa: BLE001
        settings.logger.error(
            "No se pudo compensar tenant parcial %s: %s", cliente_id, exc
        )
        return False


def build_demo_tenant(
    *,
    nombre_empresa: str,
    sector: str,
    email: str,
    website_url: str = "",
    descripcion: str = "",
    servicios: str = "",
    horario: str = "",
    color: str = "",
    request=None,
) -> Dict[str, Any]:
    """Fuente unica idempotente entre threads y workers para un mismo email."""
    email_clean = (email or "").strip().lower()
    lease_owner = secrets.token_urlsafe(24)
    proposed_cliente_id = _new_demo_cliente_id(nombre_empresa)
    reserved_cliente_id = proposed_cliente_id
    takeover = False
    with _demo_generation_lock_for_email(email):
        deadline = time.time() + _DEMO_GENERATION_WAIT_SECONDS
        while True:
            reservation, reused_id, reused_ts = _reserve_demo_generation(
                email_clean, lease_owner, proposed_cliente_id
            )
            if reservation == "reused":
                # Otro worker pudo crearla: sincroniza el snapshot local una vez
                # liberado el write lock antes de devolver la URL reutilizada.
                with _demo_lifecycle_guard():
                    clients._reload_runtime_configs_from_disk()
                return {
                    "cliente_id": reused_id,
                    "demo_url": _canonical_demo_url(reused_id),
                    "expires_in_seconds": max(
                        0, int(reused_ts + DEMO_TTL_SECONDS - time.time())
                    ),
                    "reused": True,
                }
            if reservation in {"acquired", "takeover"}:
                reserved_cliente_id = reused_id or proposed_cliente_id
                takeover = reservation == "takeover"
                break
            if time.time() >= deadline:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="La demo ya se esta generando. Intentalo de nuevo en unos instantes.",
                )
            time.sleep(0.15)

        try:
            # El heartbeat empieza antes de esperar el lock global: otro build
            # largo no puede hacer caducar esta reserva mientras espera turno.
            with _demo_generation_heartbeat(email_clean, lease_owner):
                # Serializa la mutacion de config.json entre workers del mismo bind mount.
                with _demo_lifecycle_guard():
                    # Nunca construir desde un snapshot anterior al ultimo write de
                    # otro worker: _save_admin_client_payload persiste el mapa completo.
                    clients._reload_runtime_configs_from_disk()
                    if not _demo_generation_reservation_owned(
                        email_clean, lease_owner, reserved_cliente_id
                    ):
                        raise RuntimeError("La reserva de generacion de demo ha expirado.")
                    if takeover and not _cleanup_reserved_demo_tenant(reserved_cliente_id):
                        raise RuntimeError("No se pudo limpiar la demo parcial anterior.")
                    result = _build_demo_tenant_unlocked(
                        cliente_id=reserved_cliente_id,
                        nombre_empresa=nombre_empresa,
                        sector=sector,
                        email=email_clean,
                        website_url=website_url,
                        descripcion=descripcion,
                        servicios=servicios,
                        horario=horario,
                        color=color,
                        request=request,
                    )
                    cliente_id = str(result["cliente_id"])
                    if cliente_id != reserved_cliente_id:
                        raise RuntimeError("El builder no respeto el cliente reservado.")
                    if not _register_demo_tenant(
                        cliente_id,
                        email_clean,
                        lease_owner=lease_owner,
                    ):
                        raise RuntimeError("No se pudo activar la reserva de la demo.")
                    return result
        except Exception:
            with _demo_lifecycle_guard():
                cleanup_ok = _cleanup_reserved_demo_tenant(reserved_cliente_id)
            if cleanup_ok:
                _release_demo_generation(email_clean, lease_owner)
            else:
                _expire_demo_generation(email_clean, lease_owner)
            raise


def _build_demo_tenant_unlocked(
    *,
    cliente_id: str = "",
    nombre_empresa: str,
    sector: str,
    email: str,
    website_url: str = "",
    descripcion: str = "",
    servicios: str = "",
    horario: str = "",
    color: str = "",
    request=None,
) -> Dict[str, Any]:
    """Crea (o reutiliza) un tenant demo personalizado. SINCRONO: pensado para
    correr en un hilo. Rastrea la web del prospecto (run_onboarding) y siembra
    RAG. Fuente UNICA usada por POST /demo/generate y por la pre-generacion al
    abrir el email. Devuelve {cliente_id, demo_url, expires_at, reused, ...}."""
    import onboarding_utils
    from api_models import AdminClientePayload
    from backend import portal, rag

    empresa_clean = (nombre_empresa or "").strip()[:120] or "Empresa"
    sector_clean = (sector or "").strip() or "Otro"
    email_clean = (email or "").strip()
    req = request or _synthetic_request()

    cliente_id = cliente_id or _new_demo_cliente_id(empresa_clean)
    textnorm._assert_valid_client_id(cliente_id)
    if not cliente_id.startswith(DEMO_TENANT_PREFIX):
        raise ValueError("cliente_id invalido para auto-demo")

    defaults = _DEMO_SECTOR_DEFAULTS.get(sector_clean, (
        f"Negocio del sector {sector_clean}.",
        "Servicios disponibles. Consultar para mas informacion.",
    ))
    descripcion_clean = (descripcion or "").strip() or defaults[0]
    servicios_clean = (servicios or "").strip() or defaults[1]
    horario_clean = (horario or "").strip()

    manual_info = (
        f"Empresa: {empresa_clean}\n"
        f"Sector: {sector_clean}\n\n"
        f"Descripcion del negocio:\n{descripcion_clean}\n\n"
        f"Servicios principales:\n{servicios_clean}\n"
    )
    if horario_clean:
        manual_info += f"\nHorario:\n{horario_clean}\n"
    manual_info += f"\nContacto comercial: {email_clean}\n"

    detected_business_name = empresa_clean
    info_txt = manual_info
    base_app = (settings.APP_BASE_URL or "https://app.vantelia.es").rstrip("/")
    allowed_origins = [base_app]
    for origin in ("https://www.vantelia.es", "https://vantelia.es"):
        if origin not in allowed_origins:
            allowed_origins.append(origin)

    scrape_result = None
    if website_url:
        try:
            scrape_result = onboarding_utils.run_onboarding(
                website_url=website_url,
                api_key=settings.OPENAI_API_KEY,
                nombre_bot="Asistente",
                tono="profesional",
                idioma="es",
                max_paginas=4,
            )
            if scrape_result.detected_business_name:
                detected_business_name = scrape_result.detected_business_name
            if scrape_result.info_txt:
                info_txt = manual_info + "\n--- Informacion extraida de la web ---\n" + scrape_result.info_txt
            parsed = _urlparse(scrape_result.normalized_url)
            if parsed.netloc:
                origin_url = f"{parsed.scheme}://{parsed.netloc}"
                if origin_url not in allowed_origins:
                    allowed_origins.append(origin_url)
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("Demo scraping fallo para %s: %s", website_url, exc)

    color_val = (color or "#0EA5E9").strip()
    if not _re.match(r"^#[0-9A-Fa-f]{6}$", color_val):
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
        contacto_email=email_clean,
        contacto_telefono="",
        branding_text="Powered by Vantelia",
        booking_enabled=False,
        booking_timezone=settings.DEFAULT_TIMEZONE,
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

    portal._save_admin_client_payload(cliente_id, payload, req)
    if scrape_result is not None:
        try:
            rag._seed_qa_from_onboarding(cliente_id, scrape_result)
        except Exception as exc:  # noqa: BLE001
            settings.logger.debug("No se pudo sembrar Q&A demo %s: %s", cliente_id, exc)
    expires_dt = timeutils._utc_now() + timedelta(seconds=DEMO_TTL_SECONDS)
    return {
        "cliente_id": cliente_id,
        "demo_url": _canonical_demo_url(cliente_id),
        "expires_at": expires_dt.isoformat(),
        "expires_in_seconds": DEMO_TTL_SECONDS,
        "detected_business_name": detected_business_name,
        "reused": False,
    }


def _demo_purge_candidates() -> List[Tuple[str, float]]:
    cutoff = time.time() - DEMO_TTL_SECONDS
    now_ts = time.time()
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        rows = connection.execute(
            """SELECT cliente_id, created_ts FROM demo_tenants_registry
               WHERE cliente_id<>'' AND (
                   (state='active' AND created_ts<?)
                   OR (state='generating' AND lease_expires_ts<=?)
                   OR state='purging'
               )""",
            (cutoff, now_ts),
        ).fetchall()
    return [(str(row["cliente_id"]), float(row["created_ts"])) for row in rows]


def _reserve_demo_purge(
    cliente_id: str, created_ts: float, purge_owner: str
) -> bool:
    now_ts = time.time()
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT * FROM demo_tenants_registry WHERE cliente_id=?",
                (cliente_id,),
            ).fetchone()
            if not row or float(row["created_ts"]) != float(created_ts):
                connection.commit()
                return False
            owner_row = connection.execute(
                "SELECT owner_user_id FROM clientes WHERE cliente_id=?",
                (cliente_id,),
            ).fetchone()
            if owner_row and str(owner_row["owner_user_id"] or ""):
                connection.execute(
                    "DELETE FROM demo_tenants_registry WHERE cliente_id=? AND created_ts=?",
                    (cliente_id, created_ts),
                )
                connection.commit()
                return False
            state_value = str(row["state"] or "")
            if state_value == "active":
                if now_ts - float(row["created_ts"] or 0) <= DEMO_TTL_SECONDS:
                    connection.commit()
                    return False
            elif state_value == "generating":
                if float(row["lease_expires_ts"] or 0) > now_ts:
                    connection.commit()
                    return False
            elif state_value == "purging":
                if (
                    row["lease_owner"] != purge_owner
                    and float(row["lease_expires_ts"] or 0) > now_ts
                ):
                    connection.commit()
                    return False
            else:
                connection.commit()
                return False
            cursor = connection.execute(
                """UPDATE demo_tenants_registry
                   SET state='purging', lease_owner=?, lease_expires_ts=?, updated_ts=?
                   WHERE cliente_id=? AND created_ts=?""",
                (
                    purge_owner,
                    now_ts + 300,
                    now_ts,
                    cliente_id,
                    created_ts,
                ),
            )
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            connection.rollback()
            raise


def _finish_demo_purge(
    cliente_id: str, created_ts: float, purge_owner: str, *, success: bool
) -> None:
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        if success:
            connection.execute(
                """DELETE FROM demo_tenants_registry
                   WHERE cliente_id=? AND created_ts=? AND state='purging'
                     AND lease_owner=?""",
                (cliente_id, created_ts, purge_owner),
            )
        else:
            connection.execute(
                """UPDATE demo_tenants_registry
                   SET state='purging', lease_owner='', lease_expires_ts=0,
                       updated_ts=?
                   WHERE cliente_id=? AND created_ts=? AND state='purging'
                     AND lease_owner=?""",
                (time.time(), cliente_id, created_ts, purge_owner),
            )
        connection.commit()


def _demo_cleanup_candidates() -> List[Tuple[str, float]]:
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        rows = connection.execute(
            """SELECT cliente_id, created_ts
               FROM demo_tenant_cleanup_queue
               WHERE state IN ('queued','purging')"""
        ).fetchall()
    return [(str(row["cliente_id"]), float(row["created_ts"])) for row in rows]


def _reserve_demo_cleanup(
    cliente_id: str, created_ts: float, purge_owner: str
) -> bool:
    now_ts = time.time()
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT * FROM demo_tenant_cleanup_queue WHERE cliente_id=?",
                (cliente_id,),
            ).fetchone()
            if not row or float(row["created_ts"]) != float(created_ts):
                connection.commit()
                return False
            live_registry = connection.execute(
                """SELECT 1 FROM demo_tenants_registry
                   WHERE cliente_id=? AND state IN ('active','generating')""",
                (cliente_id,),
            ).fetchone()
            owner_row = connection.execute(
                "SELECT owner_user_id FROM clientes WHERE cliente_id=?",
                (cliente_id,),
            ).fetchone()
            if live_registry or (owner_row and str(owner_row["owner_user_id"] or "")):
                connection.execute(
                    "DELETE FROM demo_tenant_cleanup_queue WHERE cliente_id=?",
                    (cliente_id,),
                )
                connection.commit()
                return False
            if (
                str(row["state"] or "") == "purging"
                and str(row["lease_owner"] or "") != purge_owner
                and float(row["lease_expires_ts"] or 0) > now_ts
            ):
                connection.commit()
                return False
            cursor = connection.execute(
                """UPDATE demo_tenant_cleanup_queue
                   SET state='purging', lease_owner=?, lease_expires_ts=?,
                       updated_ts=?
                   WHERE cliente_id=? AND created_ts=?""",
                (purge_owner, now_ts + 300, now_ts, cliente_id, created_ts),
            )
            connection.commit()
            return cursor.rowcount == 1
        except Exception:
            connection.rollback()
            raise


def _finish_demo_cleanup(
    cliente_id: str, created_ts: float, purge_owner: str, *, success: bool
) -> None:
    with db._get_db_connection() as connection:
        _ensure_demo_registry_migrated(connection)
        if success:
            connection.execute(
                """DELETE FROM demo_tenant_cleanup_queue
                   WHERE cliente_id=? AND created_ts=? AND state='purging'
                     AND lease_owner=?""",
                (cliente_id, created_ts, purge_owner),
            )
        else:
            connection.execute(
                """UPDATE demo_tenant_cleanup_queue
                   SET state='purging', lease_owner='', lease_expires_ts=0,
                       updated_ts=?
                   WHERE cliente_id=? AND created_ts=? AND state='purging'
                     AND lease_owner=?""",
                (time.time(), cliente_id, created_ts, purge_owner),
            )
        connection.commit()


def _purge_expired_demos() -> int:
    purged = 0
    for cliente_id, created_ts in _demo_purge_candidates():
        purge_owner = secrets.token_urlsafe(18)
        try:
            if not _reserve_demo_purge(cliente_id, created_ts, purge_owner):
                continue
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("No se pudo reservar purga de demo %s: %s", cliente_id, exc)
            continue

        success = False
        try:
            with _demo_lifecycle_guard():
                # El delete tambien persiste el mapa completo; partir siempre del
                # ultimo snapshot evita borrar tenants creados por otro worker.
                clients._reload_runtime_configs_from_disk()
                if cliente_id in appstate.CONFIG_CLIENTES:
                    clients._delete_client_everywhere(
                        cliente_id, skip_demo_registry_cleanup=True
                    )
                else:
                    clients._purge_client_data(
                        cliente_id, skip_demo_registry_cleanup=True
                    )
            success = True
            purged += 1
            settings.logger.info("Demo expirada eliminada: %s", cliente_id)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error("No se pudo eliminar demo expirada %s: %s", cliente_id, exc)
        finally:
            _finish_demo_purge(
                cliente_id, created_ts, purge_owner, success=success
            )
    for cliente_id, created_ts in _demo_cleanup_candidates():
        purge_owner = secrets.token_urlsafe(18)
        try:
            if not _reserve_demo_cleanup(cliente_id, created_ts, purge_owner):
                continue
        except Exception as exc:  # noqa: BLE001
            settings.logger.error(
                "No se pudo reservar cleanup de demo %s: %s", cliente_id, exc
            )
            continue

        success = False
        try:
            with _demo_lifecycle_guard():
                clients._reload_runtime_configs_from_disk()
                if cliente_id in appstate.CONFIG_CLIENTES:
                    clients._delete_client_everywhere(
                        cliente_id, skip_demo_registry_cleanup=True
                    )
                else:
                    clients._purge_client_data(
                        cliente_id, skip_demo_registry_cleanup=True
                    )
            success = True
            purged += 1
            settings.logger.info("Cleanup de demo completado: %s", cliente_id)
        except Exception as exc:  # noqa: BLE001
            settings.logger.error(
                "No se pudo completar cleanup de demo %s: %s", cliente_id, exc
            )
        finally:
            _finish_demo_cleanup(
                cliente_id, created_ts, purge_owner, success=success
            )
    return purged


VOICE_DEMO_TEMPLATE = """
<style>
  .cta-voice {
    background: linear-gradient(135deg, #10b981, #06b6d4);
    color: #04121a;
  }
  #vdemoOverlay {
    position: fixed; inset: 0; z-index: 60;
    display: none; align-items: center; justify-content: center;
    padding: 24px;
    background: radial-gradient(1200px 700px at 50% -10%, rgba(0,245,212,0.12), transparent 60%),
                rgba(5, 10, 24, 0.92);
    backdrop-filter: blur(8px);
  }
  #vdemoOverlay.open { display: flex; animation: vdemoFade 0.25s ease both; }
  @keyframes vdemoFade { from { opacity: 0; } to { opacity: 1; } }
  .vdemo-card {
    width: 100%; max-width: 360px;
    background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 24px;
    padding: 34px 26px 28px;
    text-align: center;
    box-shadow: 0 30px 80px rgba(0,0,0,0.5);
  }
  .vdemo-avatar {
    width: 104px; height: 104px; margin: 0 auto 18px;
    border-radius: 999px;
    display: grid; place-items: center;
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: 2.2rem; color: #04121a;
    background: linear-gradient(135deg, __COLOR__, #00F5D4);
    position: relative;
  }
  .vdemo-avatar::after {
    content: ""; position: absolute; inset: -8px;
    border-radius: 999px; border: 2px solid rgba(0,245,212,0.45);
    opacity: 0; transform: scale(0.9);
  }
  .vdemo-card.speaking .vdemo-avatar::after { animation: vdemoRing 1.1s ease-out infinite; }
  @keyframes vdemoRing {
    0% { opacity: 0.8; transform: scale(0.92); }
    100% { opacity: 0; transform: scale(1.25); }
  }
  .vdemo-name { font-family: "Space Grotesk", sans-serif; font-weight: 700; font-size: 1.3rem; color: #fff; }
  .vdemo-status { margin-top: 6px; color: rgba(255,255,255,0.66); font-size: 0.96rem; min-height: 22px; }
  .vdemo-timer { margin-top: 12px; font-variant-numeric: tabular-nums; font-size: 1.5rem; font-weight: 600; color: #fff; letter-spacing: 0.04em; }
  .vdemo-actions { display: flex; gap: 14px; justify-content: center; margin-top: 24px; }
  .vdemo-btn {
    appearance: none; cursor: pointer; font: inherit; font-weight: 600; font-size: 0.92rem;
    border: 1px solid rgba(255,255,255,0.16); color: #fff;
    background: rgba(255,255,255,0.06);
    padding: 12px 18px; border-radius: 999px; transition: all 0.16s ease;
  }
  .vdemo-btn:hover { background: rgba(255,255,255,0.12); }
  .vdemo-btn.on { background: rgba(255,255,255,0.2); }
  .vdemo-btn.hang { background: #ef4444; border-color: #ef4444; color: #fff; }
  .vdemo-btn.hang:hover { background: #dc2626; }
  .vdemo-hint { margin-top: 18px; color: rgba(255,255,255,0.5); font-size: 0.84rem; line-height: 1.5; }
</style>
<div id="vdemoOverlay" role="dialog" aria-modal="true" aria-label="Llamada con el asistente">
  <div class="vdemo-card" id="vdemoCard">
    <div class="vdemo-avatar">__INITIAL__</div>
    <div class="vdemo-name">__NOMBRE__</div>
    <div class="vdemo-status" id="vdemoStatus">Llamando…</div>
    <div class="vdemo-timer" id="vdemoTimer">00:00</div>
    <div class="vdemo-actions">
      <button type="button" class="vdemo-btn" id="vdemoMute">Silenciar</button>
      <button type="button" class="vdemo-btn hang" id="vdemoHang">Colgar</button>
    </div>
    <div class="vdemo-hint" id="vdemoHint">Habla con normalidad, como en una llamada real.</div>
  </div>
  <audio id="vdemoAudio" autoplay playsinline></audio>
</div>
<script>
(function(){
  var CFG = __VOICE_CFG__;
  var btn = document.getElementById('vdemoCallBtn');
  if(!btn) return;
  var overlay = document.getElementById('vdemoOverlay');
  var card = document.getElementById('vdemoCard');
  var statusEl = document.getElementById('vdemoStatus');
  var timerEl = document.getElementById('vdemoTimer');
  var hintEl = document.getElementById('vdemoHint');
  var audioEl = document.getElementById('vdemoAudio');
  var muteBtn = document.getElementById('vdemoMute');
  var hangBtn = document.getElementById('vdemoHang');

  var pc=null, dc=null, micStream=null, timerId=null, maxId=null, speakId=null;
  var seconds=0, muted=false, active=false, ended=false, MAXS=120;

  function setStatus(t){ if(statusEl) statusEl.textContent=t; }
  function setHint(t){ if(hintEl) hintEl.textContent=t; }
  function fmt(s){ var m=Math.floor(s/60), x=s%60; return (m<10?'0':'')+m+':'+(x<10?'0':'')+x; }
  function speaking(on){ if(card) card.classList.toggle('speaking', !!on); }

  function cleanup(){
    active=false;
    if(timerId){ clearInterval(timerId); timerId=null; }
    if(maxId){ clearTimeout(maxId); maxId=null; }
    if(speakId){ clearTimeout(speakId); speakId=null; }
    speaking(false);
    try{ if(dc) dc.close(); }catch(e){}
    try{ if(pc) pc.close(); }catch(e){}
    try{ if(micStream) micStream.getTracks().forEach(function(t){ t.stop(); }); }catch(e){}
    pc=null; dc=null; micStream=null;
    if(audioEl){ try{ audioEl.srcObject=null; }catch(e){} }
  }
  function resetCallUI(){
    ended=false;
    if(muteBtn){ muteBtn.style.display=''; muteBtn.textContent='Silenciar'; muteBtn.classList.remove('on'); }
    if(hangBtn){ hangBtn.textContent='Colgar'; hangBtn.classList.add('hang'); }
    if(overlay) overlay.classList.remove('ended');
  }
  function closeOverlay(){ cleanup(); resetCallUI(); if(overlay) overlay.classList.remove('open'); document.body.style.overflow=''; }
  // Fin de llamada NO solicitado por el usuario: deja el overlay abierto como un pop-up
  // que explica el motivo, y convierte "Colgar" en "Cerrar". Asi el usuario siempre ve
  // por que se ha cortado.
  function endCall(reason, detail){
    if(ended) return;
    ended=true; active=false;
    cleanup();
    setStatus(reason || 'Llamada finalizada');
    setHint(detail || 'La llamada ha terminado.');
    if(muteBtn) muteBtn.style.display='none';
    if(hangBtn){ hangBtn.textContent='Cerrar'; hangBtn.classList.remove('hang'); }
    if(overlay) overlay.classList.add('ended');
  }
  function fail(msg, hint){ endCall(msg || 'No se pudo conectar', hint || 'Revisa los permisos e inténtalo de nuevo.'); }

  function isSecure(){
    return window.isSecureContext === true
      || location.protocol === 'https:'
      || location.hostname === 'localhost'
      || location.hostname === '127.0.0.1';
  }
  // Pide el microfono de forma universal: API moderna y, si no existe, los nombres
  // antiguos por navegador. Rechaza con un nombre claro si no se puede ni intentar.
  // Forzamos cancelacion de eco/ruido: sin esto el mic recaptura la voz del propio
  // asistente (audioEl) y el server_vad la toma como habla del usuario -> corta la
  // frase a medias y entra en bucle volviendo a saludar/responder.
  var MIC_AUDIO = { echoCancellation:true, noiseSuppression:true, autoGainControl:true };
  function getMic(){
    if(!isSecure()) return Promise.reject({ name:'InsecureContext' });
    var md = navigator.mediaDevices;
    if(md && md.getUserMedia) return md.getUserMedia({ audio:MIC_AUDIO });
    var legacy = navigator.getUserMedia || navigator.webkitGetUserMedia || navigator.mozGetUserMedia || navigator.msGetUserMedia;
    if(legacy) return new Promise(function(res, rej){ legacy.call(navigator, { audio:MIC_AUDIO }, res, rej); });
    return Promise.reject({ name:'Unsupported' });
  }
  function micError(e){
    var n = (e && e.name) || '';
    if(n==='InsecureContext') fail('Necesita conexión segura', 'Abre el demo con https:// para poder hablar.');
    else if(n==='NotAllowedError' || n==='SecurityError' || n==='PermissionDeniedError') fail('Micrófono bloqueado', 'Toca el candado/ajustes del navegador y permite el micrófono para esta web.');
    else if(n==='NotFoundError' || n==='DevicesNotFoundError') fail('No se detecta micrófono', 'Conecta o activa un micrófono y vuelve a intentarlo.');
    else if(n==='NotReadableError' || n==='TrackStartError') fail('Micrófono ocupado', 'Otra app está usando el micrófono. Ciérrala e inténtalo de nuevo.');
    else if(n==='Unsupported') fail('Navegador no compatible', 'Prueba con Chrome o Safari actualizados.');
    else fail('No se pudo abrir el micrófono', 'Revisa los permisos del navegador e inténtalo de nuevo.');
  }

  function handleEvent(ev){
    var type = (ev && ev.type) || '';
    if(type.indexOf('output_audio.delta')>=0 || type.indexOf('audio.delta')>=0){
      setStatus('Hablando…'); speaking(true);
      if(speakId) clearTimeout(speakId);
      speakId=setTimeout(function(){ speaking(false); if(active) setStatus('En llamada'); }, 650);
    } else if(type==='response.done' || type.indexOf('output_audio.done')>=0){
      speaking(false); if(active) setStatus('En llamada');
    } else if(type==='input_audio_buffer.speech_started'){
      if(active) setHint('Te escucho…');
    } else if(type==='response.function_call_arguments.done'){
      runTool(ev);
    } else if(type==='error'){
      var em = (ev && ev.error && (ev.error.message || ev.error.code)) || '';
      endCall('La llamada terminó', em ? ('Motivo: '+em) : 'El asistente devolvió un error. Vuelve a intentarlo.');
    }
  }

  // El navegador habla directo con OpenAI; cuando el modelo pide una funcion (consultar
  // disponibilidad, agendar...), la ejecutamos contra el backend y devolvemos el resultado
  // por el data channel. Sin esto el modelo se quedaria esperando -> silencio largo.
  async function runTool(ev){
    var name = ev && ev.name;
    var callId = ev && ev.call_id;
    var argsStr = (ev && ev.arguments) || '{}';
    if(!name || !callId || !dc) return;
    if(active) setHint('Un momento, lo compruebo…');
    var result;
    try{
      var base = (CFG.api||'').replace(/\\/$/,'');
      var r = await fetch(base + '/demo/' + encodeURIComponent(CFG.cliente) + '/voice/tool', {
        method:'POST', headers:{ 'Content-Type':'application/json' },
        body: JSON.stringify({ name:name, arguments:argsStr })
      });
      result = r.ok ? await r.json() : { ok:false, error:'No se pudo consultar ahora mismo.' };
    }catch(e){ result = { ok:false, error:'No se pudo consultar ahora mismo.' }; }
    try{
      dc.send(JSON.stringify({ type:'conversation.item.create', item:{ type:'function_call_output', call_id:callId, output: JSON.stringify(result) } }));
      dc.send(JSON.stringify({ type:'response.create' }));
      // Colgado suave: el asistente pidio terminar (se ha despedido); cerramos tras dejarle hablar.
      if(result && result.end_call){ setTimeout(function(){ if(active) endCall('Llamada finalizada','El asistente ha terminado la llamada.'); }, 6000); }
    }catch(_){}
  }

  async function postSDP(model, sdp, secret){
    var endpoints = [
      'https://api.openai.com/v1/realtime/calls?model='+model,
      'https://api.openai.com/v1/realtime?model='+model
    ];
    var lastErr;
    for(var i=0;i<endpoints.length;i++){
      try{
        var r = await fetch(endpoints[i], { method:'POST', body:sdp, headers:{ 'Authorization':'Bearer '+secret, 'Content-Type':'application/sdp' } });
        if(r.ok) return await r.text();
        lastErr = new Error('sdp http '+r.status);
      }catch(e){ lastErr=e; }
    }
    throw lastErr || new Error('sdp failed');
  }

  async function call(){
    if(active) return;
    resetCallUI();
    active=true;
    overlay.classList.add('open'); document.body.style.overflow='hidden';
    setStatus('Pidiendo micrófono…'); timerEl.textContent='00:00';
    setHint('Permite el micrófono para empezar a hablar.');
    muted=false;

    try{
      micStream = await getMic();
    }catch(e){ micError(e); return; }

    var sess;
    setStatus('Conectando…');
    try{
      var base = (CFG.api||'').replace(/\\/$/,'');
      var r = await fetch(base + '/demo/' + encodeURIComponent(CFG.cliente) + '/voice/session', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:'{}' });
      if(r.status===429){ fail('Demasiados intentos', 'Has iniciado varias llamadas seguidas. Espera un minuto y vuelve a probar.'); return; }
      if(r.status===503){ fail('Voz no disponible', 'El asistente de voz no está configurado ahora mismo.'); return; }
      if(!r.ok) throw new Error('http '+r.status);
      sess = await r.json();
    }catch(e){ fail('No se pudo iniciar la voz', 'Hubo un problema al conectar con el asistente. Inténtalo de nuevo.'); return; }
    MAXS = sess.max_duration_seconds || 120;

    try{
      pc = new RTCPeerConnection();
      pc.ontrack = function(e){ try{ audioEl.srcObject = e.streams[0]; audioEl.play().catch(function(){}); }catch(_){} };
      pc.onconnectionstatechange = function(){
        if(!pc) return;
        var s = pc.connectionState;
        if(s==='connected'){ if(active && !ended) setStatus('En llamada'); }
        else if(s==='failed'){ endCall('Se cortó la llamada', 'Se perdió la conexión con el asistente. Comprueba tu internet y vuelve a llamar.'); }
        else if(s==='disconnected'){ if(active && !ended) setStatus('Reconectando…'); }
      };
      pc.oniceconnectionstatechange = function(){
        if(pc && pc.iceConnectionState==='failed'){ endCall('Se cortó la llamada', 'No se pudo mantener la conexión de audio (red o firewall). Vuelve a intentarlo.'); }
      };
      micStream.getTracks().forEach(function(t){ pc.addTrack(t, micStream); });
      dc = pc.createDataChannel('oai-events');
      dc.onmessage = function(m){ try{ handleEvent(JSON.parse(m.data)); }catch(_){} };
      dc.onclose = function(){ if(active && !ended) endCall('La llamada se cerró', 'El asistente cerró la sesión. Vuelve a llamar para seguir probando.'); };
      dc.onopen = function(){
        try{
          var g = sess.greeting || '';
          if(g){
            dc.send(JSON.stringify({ type:'conversation.item.create', item:{ type:'message', role:'user', content:[{ type:'input_text', text:'Inicia la llamada saludando exactamente con: "'+g+'"' }] } }));
            dc.send(JSON.stringify({ type:'response.create' }));
          }
        }catch(_){}
      };
      var offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      var sdpAnswer = await postSDP(encodeURIComponent(sess.model||''), offer.sdp, sess.client_secret);
      await pc.setRemoteDescription({ type:'answer', sdp:sdpAnswer });
    }catch(e){ fail('No se pudo establecer la llamada', 'No se pudo abrir el canal de audio con el asistente. Inténtalo de nuevo.'); return; }

    setStatus('En llamada');
    setHint('Habla con normalidad. Pulsa Colgar para terminar.');
    seconds=0; timerEl.textContent='00:00';
    timerId=setInterval(function(){ seconds++; timerEl.textContent=fmt(seconds); }, 1000);
    maxId=setTimeout(function(){
      endCall('Tiempo de demo agotado', 'Esta demo de voz dura '+MAXS+' segundos. Pulsa "Llamar al asistente" para hablar otra vez.');
    }, MAXS*1000);
  }

  btn.addEventListener('click', call);
  if(muteBtn) muteBtn.addEventListener('click', function(){
    muted=!muted;
    if(micStream) micStream.getAudioTracks().forEach(function(t){ t.enabled=!muted; });
    muteBtn.textContent = muted ? 'Activar micro' : 'Silenciar';
    muteBtn.classList.toggle('on', muted);
  });
  if(hangBtn) hangBtn.addEventListener('click', closeOverlay);
})();
</script>
"""


def _build_demo_page(cliente_id: str, request: Request) -> str:
    from backend import outreach

    config = clients._get_client_config(cliente_id)
    assets = clients._build_install_snippet(cliente_id, request)
    nombre = escape(config["nombre"])
    color = escape(config["color"])
    booking_enabled = bool(config["booking"]["enabled"])
    api_base_url = escape(assets["api_base_url"])
    cliente_safe = escape(cliente_id)
    script_url = escape(assets["widget_script_url"])
    favicon_url = escape(textnorm._brand_asset_public_path("favicon.png"))
    og_image_url = escape((settings.APP_BASE_URL or "https://app.vantelia.es") + "/uploads/og-demo.png")
    fondo_url = escape(textnorm._brand_asset_public_path("fondo-desktop.png") or textnorm._brand_asset_public_path("Fondo_Web.png"))
    fondo_movil_url = escape(textnorm._brand_asset_public_path("fondo-movil.png") or fondo_url)
    is_auto_demo = cliente_id.startswith(DEMO_TENANT_PREFIX)
    demo_session_id = f"demo_{secrets.token_hex(16)}"
    demo_signal_tokens: Dict[str, str] = {}
    if is_auto_demo and _demo_is_active_unclaimed(cliente_id):
        for event_name in (
            "demo_chat_started",
            "demo_contact_clicked",
            "demo_whatsapp_clicked",
            "demo_claim_clicked",
        ):
            signal_token = outreach._outreach_demo_signal_token(
                cliente_id, event_name, demo_session_id
            )
            if signal_token:
                demo_signal_tokens[event_name] = signal_token
    demo_signal_tokens_json = json.dumps(
        demo_signal_tokens, ensure_ascii=True, separators=(",", ":")
    ).replace("</", "<\\/")

    contact_subject = _urlquote(f"Duda sobre la demo de {config['nombre']}")
    contact_body = _urlquote(
        f"Hola, he probado la demo de {config['nombre']} y tengo una duda."
    )
    whatsapp_text = _urlquote(
        f"Hola, he probado la demo de {config['nombre']} y prefiero seguir por WhatsApp."
    )
    demo_contact_actions = (
        '<section class="demo-contact-bar" aria-label="Contactar con Vantelia">'
        '<div class="demo-contact-copy"><strong>¿Quieres comentarlo?</strong>'
        '<span>Escríbenos por el canal que te resulte más cómodo.</span></div>'
        f'<a class="demo-contact-link" data-demo-contact-cta="1" '
        f'href="mailto:info@vantelia.es?subject={contact_subject}&amp;body={contact_body}">Tengo una duda</a>'
        f'<a class="demo-contact-link demo-contact-whatsapp" data-demo-whatsapp-cta="1" '
        f'href="https://wa.me/34675802001?text={whatsapp_text}" target="_blank" rel="noopener noreferrer">'
        'Prefiero seguir por WhatsApp</a>'
        '</section>'
        if is_auto_demo else ""
    )

    hero_lead = (
        "Habla con el asistente como lo harían tus clientes y descubre cómo gestiona consultas y citas automáticamente."
        if booking_enabled
        else "Habla con el asistente como lo harían tus clientes y comprueba cómo responde sus dudas automáticamente."
    )
    og_description = (
        f"Asistente con los servicios reales de {nombre}: responde consultas y gestiona citas 24/7. Demo de Vantelia."
        if booking_enabled
        else f"Asistente con los servicios reales de {nombre}: responde consultas 24/7. Demo de Vantelia."
    )

    booking_example = (
        '<button type="button" class="ex-chip" data-msg="¿Tenéis disponibilidad mañana?">'
        '<span class="ex-icon">📅</span><span>¿Tenéis disponibilidad mañana?</span></button>'
        if booking_enabled else ""
    )
    booking_request_example = (
        '<button type="button" class="ex-chip" data-msg="Quiero reservar una cita">'
        '<span class="ex-icon">✅</span><span>Quiero reservar una cita</span></button>'
        if booking_enabled else ""
    )
    booking_value_card = (
        '<article class="value-card">'
        '<div class="v-icon">📅</div>'
        '<h3>Gestiona citas</h3>'
        '<p>Comprueba disponibilidad, agenda y confirma reservas sin intervención humana.</p>'
        '</article>'
        if booking_enabled else
        '<article class="value-card">'
        '<div class="v-icon">💬</div>'
        '<h3>Convierte consultas</h3>'
        '<p>Resuelve dudas frecuentes y facilita que cada visitante dé el siguiente paso.</p>'
        '</article>'
    )

    # Self-serve bridge: only auto demos (demo_auto_*) without an owner can be claimed.
    is_claimable_demo = (
        (cliente_id.startswith(DEMO_TENANT_PREFIX) or bool(config.get("demo_claimable")))
        and not db.db_get_client_owner(cliente_id)
    )
    claim_banner = (
        f'<section class="claim-banner">'
        f'  <div class="claim-banner-inner">'
        f'    <div class="claim-text">'
        f'      <strong>Tu asistente ya esta listo</strong>'
        f'      <span>Guardalo en tu cuenta, copia el snippet e instalalo en tu web. Sin tarjeta.</span>'
        f'    </div>'
        f'    <a class="claim-cta" data-claim-cta="1" href="/acceso?mode=signup&amp;claim={cliente_safe}">'
        f'      Activar gratis e instalar'
        f'    </a>'
        f'  </div>'
        f'</section>'
        if is_claimable_demo else ""
    )
    booking_step = (
        '<article class="step">'
        '<div class="step-num">1</div>'
        '<h3>Pide una cita</h3>'
        '<p>Reserva como lo haría tu cliente. La IA muestra huecos y agenda en tiempo real.</p>'
        '</article>'
        if booking_enabled else
        '<article class="step">'
        '<div class="step-num">1</div>'
        '<h3>Haz una consulta</h3>'
        '<p>Pregunta lo que un cliente real preguntaría. La IA responde al instante.</p>'
        '</article>'
    )

    # Llamada simulada por voz (browser WebRTC, sin telefono): boton en el hero +
    # bloque overlay/JS inyectado como valor (llaves literales, no las parsea el f-string).
    voice_initial = escape((config.get("icono") or config["nombre"][:2] or "IA").upper())
    voice_js_cfg = json.dumps(
        {"api": assets["api_base_url"], "cliente": cliente_id}
    ).replace("</", "<\\/")
    voice_cta_button = (
        '<button type="button" id="vdemoCallBtn" class="cta cta-voice">'
        '📞 Llamar al asistente</button>'
    )
    voice_call_block = (
        VOICE_DEMO_TEMPLATE
        .replace("__VOICE_CFG__", voice_js_cfg)
        .replace("__NOMBRE__", nombre)
        .replace("__INITIAL__", voice_initial)
        .replace("__COLOR__", color)
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Prueba la IA de {nombre} | Vantelia</title>
  <meta name="robots" content="noindex, nofollow" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="Vantelia" />
  <meta property="og:title" content="Prueba la IA de {nombre}" />
  <meta property="og:description" content="{og_description}" />
  <meta property="og:image" content="{og_image_url}" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="Prueba la IA de {nombre}" />
  <meta name="twitter:image" content="{og_image_url}" />
  <link rel="icon" type="image/png" href="{favicon_url}" />
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      color-scheme: dark;
      --bg-1: #0B132B;
      --bg-2: #091028;
      --bg-3: #060c1e;
      --ink: #ffffff;
      --soft: rgba(255,255,255,0.72);
      --muted: rgba(255,255,255,0.55);
      --primary: {color};
      --accent: #00F5D4;
      --line: rgba(255,255,255,0.08);
      --card: rgba(255,255,255,0.04);
      --card-hover: rgba(255,255,255,0.07);
      --radius-lg: 20px;
      --radius-md: 14px;
      --shadow: 0 30px 80px rgba(0,0,0,0.45);
      --font: "Inter", "Segoe UI", system-ui, sans-serif;
      --font-display: "Space Grotesk", "Inter", sans-serif;
    }}

    * {{ box-sizing: border-box; }}

    html, body {{ margin: 0; padding: 0; }}

    body {{
      font-family: var(--font);
      color: var(--ink);
      background:
        linear-gradient(180deg, rgba(11,19,43,0.78) 0%, rgba(9,16,40,0.85) 60%, rgba(6,12,30,0.92) 100%),
        url("{fondo_url}") center top / cover fixed no-repeat,
        var(--bg-1);
      min-height: 100vh;
      overflow-x: hidden;
    }}

    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      background:
        radial-gradient(1200px 700px at 80% -10%, rgba(0,245,212,0.18), transparent 60%),
        radial-gradient(900px 600px at -10% 30%, rgba(0,177,217,0.18), transparent 60%);
      pointer-events: none;
      z-index: 0;
    }}

    .page {{
      position: relative;
      z-index: 1;
      max-width: 1180px;
      margin: 0 auto;
      padding: 56px 24px 140px;
    }}

    /* HERO */
    .hero {{
      text-align: center;
      padding: 40px 16px 24px;
      animation: fadeUp 0.7s ease both;
    }}

    .badge-live {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 14px;
      border-radius: 999px;
      background: rgba(0,245,212,0.08);
      border: 1px solid rgba(0,245,212,0.25);
      font-size: 13px;
      font-weight: 600;
      color: var(--accent);
      margin-bottom: 22px;
    }}

    .claim-banner {{
      max-width: 880px;
      margin: 0 auto 28px;
      animation: fadeUp 0.7s ease both;
    }}
    .claim-banner-inner {{
      background: linear-gradient(135deg, rgba(0,245,212,0.17), rgba(0,177,217,0.12));
      border: 1px solid rgba(0,245,212,0.46);
      border-radius: var(--radius-md);
      padding: 18px 20px;
      display: flex; flex-wrap: wrap; align-items: center; gap: 14px;
      justify-content: space-between;
      box-shadow: 0 18px 44px rgba(0,209,255,0.2);
    }}
    .claim-text {{ flex: 1 1 320px; min-width: 0; line-height: 1.5; }}
    .claim-text strong {{ display: block; font-size: 16px; color: var(--ink); }}
    .claim-text span {{ display: block; color: var(--soft); font-size: 13.5px; margin-top: 2px; }}
    .claim-cta {{
      display: inline-flex; align-items: center; gap: 8px;
      padding: 11px 18px;
      background: var(--accent);
      color: #07101f;
      border-radius: 12px;
      text-decoration: none;
      font-weight: 700; font-size: 14px;
      transition: transform .15s ease, box-shadow .15s ease;
      white-space: nowrap;
    }}
    .claim-cta:hover {{ transform: translateY(-1px); box-shadow: 0 10px 24px rgba(0,245,212,0.35); }}

    .demo-contact-bar {{
      position: sticky;
      top: 12px;
      z-index: 30;
      max-width: 940px;
      margin: 0 auto 10px;
      padding: 12px 14px;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
      border: 1px solid rgba(143,181,214,0.25);
      border-radius: 16px;
      background: rgba(9,18,40,0.9);
      box-shadow: 0 14px 36px rgba(0,0,0,0.24);
      backdrop-filter: blur(16px);
    }}
    .demo-contact-copy {{ margin-right: auto; min-width: 190px; }}
    .demo-contact-copy strong {{ display: block; color: var(--ink); font-size: 14px; }}
    .demo-contact-copy span {{ display: block; color: var(--soft); font-size: 12px; margin-top: 2px; }}
    .demo-contact-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      padding: 9px 14px;
      border: 1px solid rgba(0,245,212,0.34);
      border-radius: 11px;
      color: var(--ink);
      text-decoration: none;
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
      transition: border-color .15s ease, background .15s ease, transform .15s ease;
    }}
    .demo-contact-link:hover {{
      transform: translateY(-1px);
      border-color: var(--accent);
      background: rgba(0,245,212,0.09);
    }}
    .demo-contact-whatsapp {{
      border-color: rgba(37,211,102,0.5);
      background: rgba(37,211,102,0.1);
    }}

    .badge-live .dot {{
      width: 8px; height: 8px; border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 0 rgba(0,245,212,0.6);
      animation: pulse 1.8s infinite;
    }}

    .hero h1 {{
      font-family: var(--font-display);
      font-weight: 700;
      font-size: clamp(2.2rem, 5vw, 4rem);
      line-height: 1.05;
      margin: 0 0 18px;
      letter-spacing: -0.02em;
      background: linear-gradient(135deg, #ffffff 0%, #b8e8ff 60%, var(--accent) 100%);
      -webkit-background-clip: text;
      background-clip: text;
      -webkit-text-fill-color: transparent;
    }}

    .hero p.lead {{
      max-width: 720px;
      margin: 0 auto 30px;
      font-size: clamp(1rem, 1.4vw, 1.18rem);
      line-height: 1.6;
      color: var(--soft);
    }}

    .cta {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 14px 28px;
      border: 0;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      font-size: 1rem;
      color: #001018;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      border-radius: 999px;
      box-shadow: 0 12px 30px rgba(0,245,212,0.22);
      transition: transform 0.18s ease, box-shadow 0.18s ease;
    }}

    .cta:hover {{
      transform: translateY(-2px);
      box-shadow: 0 18px 40px rgba(0,245,212,0.32);
    }}

    .cta svg {{ width: 18px; height: 18px; }}

    .hero-ctas {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: center;
      align-items: center;
      max-width: 480px;
      margin: 0 auto;
    }}
    .hero-ctas .cta {{ flex: 0 1 auto; }}

    /* STEPS */
    .section {{
      margin-top: 80px;
      animation: fadeUp 0.7s ease both;
    }}

    .section-head {{
      text-align: center;
      margin-bottom: 36px;
    }}

    .section-head h2 {{
      font-family: var(--font-display);
      font-size: clamp(1.5rem, 2.4vw, 2.1rem);
      font-weight: 700;
      margin: 0 0 10px;
      letter-spacing: -0.01em;
    }}

    .section-head p {{
      margin: 0;
      color: var(--muted);
      font-size: 1rem;
    }}

    .steps {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 18px;
    }}

    .step {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      padding: 26px 22px;
      transition: transform 0.2s ease, background 0.2s ease, border-color 0.2s ease;
    }}

    .step:hover {{
      transform: translateY(-4px);
      background: var(--card-hover);
      border-color: rgba(0,245,212,0.3);
    }}

    .step-num {{
      width: 38px; height: 38px;
      border-radius: 12px;
      display: grid; place-items: center;
      font-family: var(--font-display);
      font-weight: 700;
      font-size: 1.05rem;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      color: #001018;
      margin-bottom: 16px;
    }}

    .step h3 {{
      font-family: var(--font-display);
      margin: 0 0 8px;
      font-size: 1.1rem;
      font-weight: 600;
    }}

    .step p {{
      margin: 0;
      color: var(--soft);
      font-size: 0.94rem;
      line-height: 1.55;
    }}

    /* EXAMPLES */
    .examples {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: center;
      max-width: 880px;
      margin: 0 auto;
    }}

    .ex-chip {{
      appearance: none;
      cursor: pointer;
      font: inherit;
      font-weight: 500;
      font-size: 0.95rem;
      padding: 12px 18px;
      border-radius: 999px;
      background: rgba(255,255,255,0.05);
      color: var(--ink);
      border: 1px solid var(--line);
      display: inline-flex;
      align-items: center;
      gap: 10px;
      transition: all 0.18s ease;
    }}

    .ex-chip:hover {{
      transform: translateY(-2px);
      border-color: var(--accent);
      background: rgba(0,245,212,0.08);
      color: var(--accent);
    }}

    .ex-icon {{ font-size: 1.1rem; }}

    /* VALUE */
    .value {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 18px;
    }}

    .value-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      padding: 28px 24px;
      text-align: left;
    }}

    .value-card .v-icon {{
      width: 44px; height: 44px;
      border-radius: 12px;
      display: grid; place-items: center;
      background: rgba(0,245,212,0.10);
      color: var(--accent);
      margin-bottom: 16px;
      font-size: 1.4rem;
    }}

    .value-card h3 {{
      font-family: var(--font-display);
      margin: 0 0 8px;
      font-size: 1.05rem;
      font-weight: 600;
    }}

    .value-card p {{
      margin: 0;
      color: var(--soft);
      line-height: 1.55;
      font-size: 0.94rem;
    }}

    /* WIDGET POINTER */
    .widget-pointer {{
      position: fixed;
      right: 110px;
      bottom: 36px;
      z-index: 5;
      display: flex;
      align-items: center;
      gap: 10px;
      pointer-events: none;
      animation: fadeIn 0.6s ease 0.8s both;
    }}

    .widget-pointer .tooltip {{
      background: linear-gradient(135deg, var(--primary), var(--accent));
      color: #001018;
      font-weight: 700;
      padding: 10px 16px;
      border-radius: 12px;
      font-size: 0.92rem;
      box-shadow: 0 12px 30px rgba(0,0,0,0.4);
      white-space: nowrap;
      animation: bobX 1.6s ease-in-out infinite;
    }}

    .widget-pointer .arrow {{
      font-size: 1.6rem;
      color: var(--accent);
      animation: bobX 1.6s ease-in-out infinite;
      filter: drop-shadow(0 0 10px rgba(0,245,212,0.6));
    }}

    .widget-pointer.hidden {{
      opacity: 0;
      transition: opacity 0.4s ease;
    }}

    /* WIDGET GLOW */
    #ia-w-btn {{
      animation: widgetGlow 2.2s ease-in-out infinite;
    }}

    .footer {{
      margin-top: 80px;
      text-align: center;
      color: var(--muted);
      font-size: 13px;
    }}

    .footer a {{ color: var(--accent); text-decoration: none; }}

    /* ANIMATIONS */
    @keyframes pulse {{
      0% {{ box-shadow: 0 0 0 0 rgba(0,245,212,0.5); }}
      70% {{ box-shadow: 0 0 0 10px rgba(0,245,212,0); }}
      100% {{ box-shadow: 0 0 0 0 rgba(0,245,212,0); }}
    }}

    @keyframes bobX {{
      0%, 100% {{ transform: translateX(0); }}
      50% {{ transform: translateX(8px); }}
    }}

    @keyframes widgetGlow {{
      0%, 100% {{ box-shadow: 0 10px 30px rgba(0,177,217,0.35), 0 0 0 0 rgba(0,245,212,0.5); }}
      50% {{ box-shadow: 0 10px 30px rgba(0,177,217,0.55), 0 0 0 14px rgba(0,245,212,0); }}
    }}

    @keyframes fadeUp {{
      from {{ opacity: 0; transform: translateY(20px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    @keyframes fadeIn {{
      from {{ opacity: 0; }}
      to {{ opacity: 1; }}
    }}

    .reveal {{ opacity: 0; transform: translateY(24px); transition: opacity 0.7s ease, transform 0.7s ease; }}
    .reveal.in {{ opacity: 1; transform: translateY(0); }}

    /* RESPONSIVE */
    @media (max-width: 900px) {{
      .steps {{ grid-template-columns: repeat(2, 1fr); }}
      .value {{ grid-template-columns: 1fr; }}
      .widget-pointer {{ right: 96px; bottom: 30px; }}
      .widget-pointer .tooltip {{ font-size: 0.84rem; padding: 8px 12px; }}
    }}

    @media (max-width: 540px) {{
      .page {{ padding: 36px 18px 120px; }}
      .demo-contact-bar {{ top: 8px; padding: 10px; flex-wrap: wrap; }}
      .demo-contact-copy {{ flex: 1 0 100%; }}
      .demo-contact-link {{ flex: 1 1 140px; white-space: normal; text-align: center; }}
      .steps {{ grid-template-columns: 1fr; }}
      .widget-pointer .tooltip {{ display: none; }}
      .hero {{ padding: 28px 4px 18px; }}
      .hero-ctas {{ flex-direction: column; align-items: stretch; max-width: 360px; }}
      .hero-ctas .cta {{ width: 100%; justify-content: center; padding: 15px 20px; }}
    }}

    @media (max-width: 768px) {{
      body {{
        background:
          linear-gradient(180deg, rgba(11,19,43,0.78) 0%, rgba(9,16,40,0.85) 60%, rgba(6,12,30,0.92) 100%),
          url("{fondo_movil_url}") center top / cover fixed no-repeat,
          var(--bg-1);
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    {demo_contact_actions}
    <section class="hero">
      {claim_banner}
      <span class="badge-live"><span class="dot"></span>Demo en vivo · {nombre}</span>
      <h1>Prueba la IA de Vantelia en directo</h1>
      <p class="lead">{hero_lead}</p>
      <div class="hero-ctas">
        <button type="button" id="ctaProbar" class="cta">
          Probar ahora
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 5l7 7-7 7"/></svg>
        </button>
        {voice_cta_button}
      </div>
    </section>

    <section class="section reveal">
      <div class="section-head">
        <h2>Cómo probar la demo</h2>
        <p>Cuatro formas de comprobar lo que la IA puede hacer por tu negocio.</p>
      </div>
      <div class="steps">
        {booking_step}
        <article class="step">
          <div class="step-num">2</div>
          <h3>Pregunta por servicios</h3>
          <p>Descubre qué ofrece, precios, horarios, ubicación. La IA conoce el negocio.</p>
        </article>
        <article class="step">
          <div class="step-num">3</div>
          <h3>Simula ser un cliente</h3>
          <p>Plantea dudas reales, objeciones, comparativas. Mira cómo gestiona la conversación.</p>
        </article>
        <article class="step">
          <div class="step-num">4</div>
          <h3>Cualquier consulta</h3>
          <p>Pregunta lo que quieras. La IA responde con la información del negocio en segundos.</p>
        </article>
      </div>
    </section>

    <section class="section reveal">
      <div class="section-head">
        <h2>Empieza con un ejemplo</h2>
        <p>Pulsa cualquier sugerencia y se enviará al chat automáticamente.</p>
      </div>
      <div class="examples">
        {booking_example}
        <button type="button" class="ex-chip" data-msg="¿Qué servicios ofrecéis?"><span class="ex-icon">💼</span><span>¿Qué servicios ofrecéis?</span></button>
        <button type="button" class="ex-chip" data-msg="¿Cuánto cuesta?"><span class="ex-icon">💶</span><span>¿Cuánto cuesta?</span></button>
        {booking_request_example}
        <button type="button" class="ex-chip" data-msg="¿Cómo funciona vuestro servicio?"><span class="ex-icon">🤔</span><span>¿Cómo funciona?</span></button>
      </div>
    </section>

    <section class="section reveal">
      <div class="section-head">
        <h2>¿Qué está pasando?</h2>
        <p>Detrás de cada respuesta del chat hay un asistente trabajando 24/7.</p>
      </div>
      <div class="value">
        <article class="value-card">
          <div class="v-icon">⚡</div>
          <h3>Responde automáticamente</h3>
          <p>Sin esperas. La IA atiende cualquier consulta en segundos con información actualizada del negocio.</p>
        </article>
        {booking_value_card}
        <article class="value-card">
          <div class="v-icon">🌙</div>
          <h3>Atiende 24/7</h3>
          <p>Trabaja noches, fines de semana y festivos. No se cansa, no falta y nunca pierde un cliente.</p>
        </article>
      </div>
    </section>

    <div class="footer">
      Tecnología de <a href="https://www.vantelia.es" target="_blank" rel="noreferrer">Vantelia</a> · Asistentes IA para empresas B2B.
    </div>
  </main>

  <div class="widget-pointer" id="widgetPointer" aria-hidden="true">
    <div class="tooltip">Empieza aquí</div>
    <div class="arrow">➜</div>
  </div>

  <script>
    window.IA_WIDGET_API = "{api_base_url}";
    window.IA_WIDGET_CLIENTE = "{cliente_safe}";
  </script>
  <script
    src="{script_url}"
    data-api="{api_base_url}"
    data-client="{cliente_safe}"
    data-position="right"></script>
  <script>
    (function () {{
      const demoSessionId = "{demo_session_id}";
      const demoSignalTokens = {demo_signal_tokens_json};

      function widgetReady() {{
        return !!document.getElementById("ia-w-btn");
      }}

      function whenWidgetReady(cb) {{
        let attempts = 0;
        (function check() {{
          if (widgetReady()) return cb();
          if (attempts++ < 40) setTimeout(check, 150);
        }})();
      }}

      function openWidget() {{
        const btn = document.getElementById("ia-w-btn");
        if (!btn) return false;
        if (btn.getAttribute("aria-expanded") !== "true") btn.click();
        return true;
      }}

      function trackDemoEvent(event, payload) {{
        try {{
          const body = Object.assign({{
            event: event,
            event_source: "demo_page",
            page_path: window.location.pathname,
            page_url: window.location.href,
            cliente_id: "{cliente_safe}",
            session_id: demoSessionId
          }}, payload || {{}});
          const signalToken = demoSignalTokens[event] || "";
          if (signalToken) body.demo_signal_token = signalToken;
          fetch("/analytics/event", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            keepalive: true,
            body: JSON.stringify(body)
          }}).catch(function () {{}});
        }} catch (_) {{}}
      }}

      trackDemoEvent("demo_viewed", {{ booking_enabled: {str(booking_enabled).lower()} }});

      let demoChatStarted = false;
      function trackDemoChatStarted(source) {{
        if (demoChatStarted) return;
        demoChatStarted = true;
        trackDemoEvent("demo_chat_started", {{ source: source || "demo_chat" }});
      }}

      function sendToWidget(message) {{
        whenWidgetReady(function () {{
          openWidget();
          setTimeout(function () {{
            const input = document.getElementById("ia-w-input");
            const send = document.getElementById("ia-w-send");
            if (!input || !send) return;
            input.value = message;
            input.dispatchEvent(new Event("input", {{ bubbles: true }}));
            send.click();
          }}, 380);
        }});
      }}

      function flashWidget() {{
        const btn = document.getElementById("ia-w-btn");
        if (!btn) return;
        btn.style.transition = "transform 0.4s ease";
        btn.style.transform = "scale(1.18)";
        setTimeout(function () {{ btn.style.transform = ""; }}, 420);
      }}

      function hidePointer() {{
        const p = document.getElementById("widgetPointer");
        if (p) p.classList.add("hidden");
      }}

      document.getElementById("ctaProbar")?.addEventListener("click", function () {{
        trackDemoChatStarted("primary_cta");
        whenWidgetReady(function () {{
          openWidget();
          flashWidget();
          hidePointer();
        }});
      }});

      document.querySelector("[data-claim-cta]")?.addEventListener("click", function (ev) {{
        trackDemoEvent("demo_claim_clicked", {{
          cta_label: "Activar gratis e instalar",
          cta_href: ev.currentTarget.href
        }});
      }});

      document.querySelector("[data-demo-contact-cta]")?.addEventListener("click", function () {{
        trackDemoEvent("demo_contact_clicked", {{ cta_label: "Tengo una duda" }});
      }});

      document.querySelector("[data-demo-whatsapp-cta]")?.addEventListener("click", function () {{
        trackDemoEvent("demo_whatsapp_clicked", {{ cta_label: "Prefiero seguir por WhatsApp" }});
      }});

      document.querySelectorAll(".ex-chip").forEach(function (chip) {{
        chip.addEventListener("click", function () {{
          const msg = chip.getAttribute("data-msg") || "";
          if (!msg) return;
          sendToWidget(msg);
          hidePointer();
        }});
      }});

      whenWidgetReady(function () {{
        const btn = document.getElementById("ia-w-btn");
        btn?.addEventListener("click", function () {{
          hidePointer();
          trackDemoChatStarted("widget_button");
        }});
      }});

      const io = new IntersectionObserver(function (entries) {{
        entries.forEach(function (e) {{
          if (e.isIntersecting) {{
            e.target.classList.add("in");
            io.unobserve(e.target);
          }}
        }});
      }}, {{ threshold: 0.12 }});
      document.querySelectorAll(".reveal").forEach(function (el) {{ io.observe(el); }});
    }})();
  </script>
  {voice_call_block}
</body>
</html>
"""


DEMO_EMPLOYEE_ID_PREFIX = "empdemo_"


DEMO_BOOKING_SOURCE = "demo_seed"

# Prefijos de id para los datos demo de comercio/centros (purga limpia sin tocar
# datos reales del cliente).
DEMO_LOCATION_ID_PREFIX = "locdemo_"
DEMO_PRODUCT_ID_PREFIX = "proddemo_"
DEMO_PACKAGE_ID_PREFIX = "pkgdemo_"
DEMO_PACKAGE_PURCHASE_ID_PREFIX = "ppdemo_"
DEMO_GIFTCARD_ID_PREFIX = "gcdemo_"
DEMO_SALE_ID_PREFIX = "saledemo_"
DEMO_SERVICE_SLUG_PREFIX = "svcdemo_"

# Servicios demo que cubren TODAS las casuisticas de pago/politica para enseñar
# al cliente cada caso posible. Genericos (validos para cualquier negocio).
#   payment_mode: payment_disabled (sin Stripe) | payment_optional | payment_required
#   payment_type: full | deposit | preauth
_DEMO_SERVICE_SPECS = [
    # nombre, duracion, precio_cents, mode, type, deposito_cents, cancel_free_h, late_pct, noshow_pct, activo
    ("Consulta de valoracion", 20, 0, "payment_disabled", "full", 0, None, None, None, True),
    ("Sesion estandar", 45, 4000, "payment_disabled", "full", 0, None, None, None, True),
    ("Sesion premium", 60, 7500, "payment_optional", "full", 0, None, None, None, True),
    ("Tratamiento completo", 75, 12000, "payment_required", "full", 0, None, None, None, True),
    ("Primera sesion con deposito", 60, 9000, "payment_required", "deposit", 3000, None, None, None, True),
    ("Reserva garantizada", 50, 6000, "payment_required", "preauth", 0, None, None, None, True),
    ("Sesion con politica estricta", 60, 8000, "payment_required", "full", 0, 48, 50, 100, True),
    ("Servicio fuera de catalogo", 30, 3000, "payment_disabled", "full", 0, None, None, None, False),
]

_DEMO_LOCATIONS = [
    ("Sede Centro (demo)", "Calle Mayor 1"),
    ("Sede Norte (demo)", "Av. del Parque 22"),
]

_DEMO_PRODUCTS = [
    ("Aceite esencial de lavanda (demo)", 1500, 30),
    ("Crema hidratante premium (demo)", 2400, 20),
    ("Vela aromatica (demo)", 1200, 40),
    ("Pack bienestar regalo (demo)", 3900, 15),
]


def _sync_demo_bookings_for_service(
    cliente_id: str,
    *,
    old_slug: str,
    old_name: str,
    service_row: sqlite3.Row,
) -> int:
    duration = int(service_row["duration_minutes"] or 0)
    if duration <= 0:
        return 0
    service_slug = service_row["slug"] or old_slug
    service_name = service_row["name"] or old_name
    service_price = int(service_row["price_cents"] or 0)
    updated = 0
    with db._get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM bookings
            WHERE cliente_id = ? AND source = ?
              AND (service_id IN (?, ?) OR servicio IN (?, ?))
            """,
            (cliente_id, DEMO_BOOKING_SOURCE, old_slug, service_slug, old_name, service_name),
        ).fetchall()
        # `cita`, no `booking`: ese nombre es el del modulo importado arriba y
        # taparlo deja el modulo inaccesible dentro del bucle.
        for cita in rows:
            timezone_name = cita["timezone"] or clients._get_client_config(cliente_id)["booking"]["timezone"]
            try:
                tzinfo = ZoneInfo(timezone_name)
            except Exception:  # noqa: BLE001
                tzinfo = ZoneInfo(settings.DEFAULT_TIMEZONE)
                timezone_name = settings.DEFAULT_TIMEZONE
            start_local = datetime.fromisoformat(
                f"{cita['booking_date']}T{cita['booking_time']}:00"
            ).replace(tzinfo=tzinfo)
            end_local = start_local + timedelta(minutes=duration)
            connection.execute(
                """
                UPDATE bookings
                SET servicio = ?, service_id = ?, service_price_cents = ?,
                    timezone = ?, start_at = ?, end_at = ?
                WHERE id = ?
                """,
                (
                    service_name,
                    service_slug,
                    service_price,
                    timezone_name,
                    timeutils._to_utc_iso(start_local),
                    timeutils._to_utc_iso(end_local),
                    cita["id"],
                ),
            )
            updated += 1
        connection.commit()
    return updated


_DEMO_PROFESSIONALS = [
    {"name": "Laura Fernandez", "role_label": "Profesional", "color": "#00b1d9"},
    {"name": "Carlos Ruiz", "role_label": "Profesional", "color": "#7c5cff"},
    {"name": "Marta Gomez", "role_label": "Profesional", "color": "#f4795b"},
    {"name": "Javier Moreno", "role_label": "Profesional", "color": "#2ecc71"},
    {"name": "Elena Navarro", "role_label": "Profesional", "color": "#e84393"},
    {"name": "David Castro", "role_label": "Profesional", "color": "#0984e3"},
    {"name": "Sara Iglesias", "role_label": "Profesional", "color": "#00cec9"},
    {"name": "Pablo Ortega", "role_label": "Profesional", "color": "#fdcb6e"},
    {"name": "Nuria Vidal", "role_label": "Profesional", "color": "#d63031"},
    {"name": "Sergio Ramos", "role_label": "Profesional", "color": "#6c5ce7"},
    {"name": "Andrea Soler", "role_label": "Profesional", "color": "#e17055"},
    {"name": "Hugo Marin", "role_label": "Profesional", "color": "#16a085"},
]

# Profesionales por centro en la demo. El pool de arriba es mayor para que cada centro
# tenga gente DISTINTA (nombres y colores no se repiten entre centros).
_DEMO_TEAM_SIZE = 3


_DEMO_CUSTOMER_NAMES = [
    "Ana Martinez", "Javier Lopez", "Lucia Sanchez", "Miguel Torres",
    "Elena Diaz", "Pablo Romero", "Sara Jimenez", "David Moreno",
    "Carmen Ortega", "Sergio Navarro", "Marina Castro", "Alberto Gil",
    "Raquel Vidal", "Hugo Ramos", "Patricia Iglesias", "Daniel Santos",
    "Cristina Molina", "Adrian Herrera", "Beatriz Flores", "Ruben Cano",
]


_DEMO_FALLBACK_SERVICES = [
    "Primera consulta", "Revision", "Sesion de seguimiento", "Consulta general",
]


def _is_bookable_demo_service(service: Dict[str, Any]) -> bool:
    nombre = str(service.get("nombre") or service.get("name") or "").strip().lower()
    descripcion = str(service.get("descripcion") or service.get("description") or "").strip().lower()
    text = f"{nombre} {descripcion}"
    if not nombre:
        return False
    discount_markers = ("bono", "bonos", "descuento", "dto", "%")
    return not any(marker in text for marker in discount_markers)


def _seed_demo_services(cliente_id: str) -> List[Dict[str, Any]]:
    """Crea servicios demo (slug ``svcdemo_*``) cubriendo cada caso de pago/politica.
    Idempotente (INSERT OR REPLACE). Devuelve los activos en forma de catalogo para
    poder reservar contra ellos. No toca los servicios reales del tenant."""
    now = timeutils._utc_now_iso()
    out: List[Dict[str, Any]] = []
    with db._get_db_connection() as connection:
        for order, spec in enumerate(_DEMO_SERVICE_SPECS):
            name, dur, price, mode, ptype, deposit, free_h, late_pct, noshow_pct, active = spec
            slug = DEMO_SERVICE_SLUG_PREFIX + agenda._normalize_service_id(name)
            connection.execute(
                """
                INSERT OR REPLACE INTO services (
                    cliente_id, slug, name, duration_minutes, price_cents, description,
                    is_active, sort_order, payment_mode, payment_type, deposit_amount_cents,
                    currency, created_at, updated_at, cancel_free_hours, cancel_late_fee_pct, no_show_fee_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'eur', ?, ?, ?, ?, ?)
                """,
                (
                    cliente_id, slug, name, int(dur), int(price), "Servicio de demostracion.",
                    1 if active else 0, 900 + order, mode, ptype, int(deposit),
                    now, now, free_h, late_pct, noshow_pct,
                ),
            )
            if active:
                out.append({
                    "id": slug, "nombre": name, "duration_minutes": int(dur),
                    "price_cents": int(price), "payment_mode": mode, "payment_type": ptype,
                })
        connection.commit()
    return out


def _purge_demo_services(cliente_id: str) -> int:
    """Borra los servicios demo (slug ``svcdemo_*``) + sus overrides por centro."""
    like = DEMO_SERVICE_SLUG_PREFIX + "%"
    with db._get_db_connection() as connection:
        try:
            connection.execute(
                "DELETE FROM service_location_overrides WHERE cliente_id = ? AND service_slug LIKE ?",
                (cliente_id, like),
            )
        except Exception:  # noqa: BLE001 - tabla opcional
            pass
        removed = connection.execute(
            "DELETE FROM services WHERE cliente_id = ? AND slug LIKE ?",
            (cliente_id, like),
        ).rowcount
        connection.commit()
    return removed


def _demo_services(cliente_id: str) -> List[Dict[str, Any]]:
    services: List[Dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for service in agenda._catalog_services(cliente_id):
            nombre = str(service.get("nombre") or "").strip()
            if nombre and nombre not in seen and _is_bookable_demo_service(service):
                services.append(service)
                seen.add(nombre)
    except Exception:  # noqa: BLE001
        services = []
        seen = set()
    if services:
        return services[:12]
    try:
        for service in agenda._extract_services_from_info(cliente_id):
            nombre = str(service.get("nombre") or "").strip()
            if nombre and nombre not in seen and _is_bookable_demo_service(service):
                services.append(service)
                seen.add(nombre)
    except Exception:  # noqa: BLE001
        services = []
    if not services:
        services = [
            {"id": agenda._normalize_service_id(name), "nombre": name, "duration_minutes": 0, "price_cents": 0}
            for name in _DEMO_FALLBACK_SERVICES
        ]
    return services[:12]


def _purge_demo_agenda(cliente_id: str) -> Dict[str, int]:
    """Borra todos los datos demo (bookings + empleados demo) de un cliente."""
    emp_like = f"{DEMO_EMPLOYEE_ID_PREFIX}%"
    with db._get_db_connection() as connection:
        # Las citas demo varian el source (canal), pero SIEMPRE estan en empleados demo.
        # Identificamos por source historico OR por empleado demo (cubre ambos casos).
        booking_ids = [
            row["id"]
            for row in connection.execute(
                "SELECT id FROM bookings WHERE cliente_id = ? AND (source = ? OR employee_id LIKE ?)",
                (cliente_id, DEMO_BOOKING_SOURCE, emp_like),
            ).fetchall()
        ]
        if booking_ids:
            placeholders = ",".join("?" for _ in booking_ids)
            connection.execute(
                f"DELETE FROM booking_audit WHERE cliente_id = ? AND booking_id IN ({placeholders})",
                (cliente_id, *booking_ids),
            )
        bookings_removed = connection.execute(
            "DELETE FROM bookings WHERE cliente_id = ? AND (source = ? OR employee_id LIKE ?)",
            (cliente_id, DEMO_BOOKING_SOURCE, emp_like),
        ).rowcount
        employees_removed = connection.execute(
            "DELETE FROM employees WHERE cliente_id = ? AND id LIKE ?",
            (cliente_id, emp_like),
        ).rowcount
        connection.execute(
            "DELETE FROM agenda_blocks WHERE cliente_id = ? AND employee_id LIKE ?",
            (cliente_id, emp_like),
        )
        connection.commit()
    services_removed = _purge_demo_services(cliente_id)
    commerce_removed = _purge_demo_commerce(cliente_id)
    return {
        "bookings_removed": int(bookings_removed or 0),
        "employees_removed": int(employees_removed or 0),
        "services_removed": int(services_removed or 0),
        "commerce": commerce_removed,
    }


def _purge_demo_commerce(cliente_id: str) -> Dict[str, int]:
    """Borra centros, productos, bonos, gift cards y ventas demo (por prefijo de id)."""
    like = lambda p: p + "%"
    with db._get_db_connection() as connection:
        connection.execute(
            "DELETE FROM gift_card_transactions WHERE cliente_id=? AND gift_card_id LIKE ?",
            (cliente_id, like(DEMO_GIFTCARD_ID_PREFIX)),
        )
        gift = connection.execute(
            "DELETE FROM gift_cards WHERE cliente_id=? AND id LIKE ?",
            (cliente_id, like(DEMO_GIFTCARD_ID_PREFIX)),
        ).rowcount
        sales = connection.execute(
            "DELETE FROM product_sales WHERE cliente_id=? AND (id LIKE ? OR product_id LIKE ?)",
            (cliente_id, like(DEMO_SALE_ID_PREFIX), like(DEMO_PRODUCT_ID_PREFIX)),
        ).rowcount
        products = connection.execute(
            "DELETE FROM products WHERE cliente_id=? AND id LIKE ?",
            (cliente_id, like(DEMO_PRODUCT_ID_PREFIX)),
        ).rowcount
        connection.execute(
            "DELETE FROM package_purchases WHERE cliente_id=? AND (id LIKE ? OR package_id LIKE ?)",
            (cliente_id, like(DEMO_PACKAGE_PURCHASE_ID_PREFIX), like(DEMO_PACKAGE_ID_PREFIX)),
        )
        packages = connection.execute(
            "DELETE FROM packages WHERE cliente_id=? AND id LIKE ?",
            (cliente_id, like(DEMO_PACKAGE_ID_PREFIX)),
        ).rowcount
        locations = connection.execute(
            "DELETE FROM locations WHERE cliente_id=? AND id LIKE ?",
            (cliente_id, like(DEMO_LOCATION_ID_PREFIX)),
        ).rowcount
        connection.commit()
    return {
        "locations_removed": int(locations or 0),
        "products_removed": int(products or 0),
        "packages_removed": int(packages or 0),
        "gift_cards_removed": int(gift or 0),
        "sales_removed": int(sales or 0),
    }


def _seed_demo_locations(cliente_id: str) -> List[str]:
    """Crea los centros demo (locdemo_*) y devuelve sus ids. Se siembra ANTES que la agenda
    para que los empleados y las citas demo se repartan tambien en estos centros (si no,
    nacerian vacios)."""
    now = timeutils._utc_now_iso()
    loc_ids: List[str] = []
    with db._get_db_connection() as connection:
        for idx, (name, addr) in enumerate(_DEMO_LOCATIONS):
            lid = DEMO_LOCATION_ID_PREFIX + secrets.token_urlsafe(6)
            connection.execute(
                "INSERT INTO locations (id, cliente_id, name, address, phone, timezone, is_active, is_default, "
                "sort_order, whatsapp_phone_number_id, voice_phone_number, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, '', '', 1, 0, ?, '', '', ?, ?)",
                (lid, cliente_id, name, addr, 10 + idx, now, now),
            )
            loc_ids.append(lid)
        connection.commit()
    return loc_ids


def _seed_demo_commerce(cliente_id: str) -> Dict[str, int]:
    """Siembra centros, productos, bonos, gift cards y ventas demo para enseñar al
    cliente como luce su negocio con todo en marcha. Todo con id 'demo' para poder
    borrarlo despues sin tocar datos reales."""
    now = timeutils._utc_now_iso()
    today = datetime.now().date()
    rng = random.Random(f"{cliente_id}:commerce:{today.isoformat()}")
    counts = {"locations": 0, "products": 0, "packages": 0, "gift_cards": 0, "sales": 0}

    # Servicio de referencia para los bonos (real si existe; si no, generico).
    svc = None
    try:
        catalog = agenda._catalog_services(cliente_id)
        if catalog:
            svc = catalog[0]
    except Exception:  # noqa: BLE001
        svc = None
    svc_slug = str((svc or {}).get("id") or (svc or {}).get("slug") or "sesion")
    svc_name = str((svc or {}).get("nombre") or (svc or {}).get("name") or "Sesion")
    try:
        svc_price = int((svc or {}).get("price_cents") or 0) or 5000
    except (TypeError, ValueError):
        svc_price = 5000

    products: List[Tuple[str, str, int]] = []
    packages: List[Tuple[str, str, int, int]] = []
    with db._get_db_connection() as connection:
        # Los centros demo ya se crearon ANTES de la agenda (_seed_demo_locations) para que
        # tengan profesionales y citas. Aqui solo los leemos para asociar ventas/bonos.
        loc_ids = [
            str(row["id"]) for row in connection.execute(
                "SELECT id FROM locations WHERE cliente_id=? AND id LIKE ?",
                (cliente_id, DEMO_LOCATION_ID_PREFIX + "%"),
            ).fetchall()
        ]
        if not loc_ids:
            # Llamada directa (sin _seed_demo_agenda): creamos los centros demo aqui mismo.
            for idx, (name, addr) in enumerate(_DEMO_LOCATIONS):
                lid = DEMO_LOCATION_ID_PREFIX + secrets.token_urlsafe(6)
                connection.execute(
                    "INSERT INTO locations (id, cliente_id, name, address, phone, timezone, is_active, is_default, "
                    "sort_order, whatsapp_phone_number_id, voice_phone_number, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, '', '', 1, 0, ?, '', '', ?, ?)",
                    (lid, cliente_id, name, addr, 10 + idx, now, now),
                )
                loc_ids.append(lid)
        counts["locations"] = len(loc_ids)
        for name, price, stock in _DEMO_PRODUCTS:
            pid = DEMO_PRODUCT_ID_PREFIX + secrets.token_urlsafe(6)
            connection.execute(
                "INSERT INTO products (cliente_id, id, name, description, price_cents, currency, stock, "
                "is_active, sort_order, created_at, updated_at) VALUES (?, ?, ?, '', ?, 'eur', ?, 1, 0, ?, ?)",
                (cliente_id, pid, name, price, stock, now, now),
            )
            products.append((pid, name, price))
            counts["products"] += 1
        for sessions, discount in ((5, 0.10), (10, 0.15)):
            pid = DEMO_PACKAGE_ID_PREFIX + secrets.token_urlsafe(6)
            price = int(svc_price * sessions * (1 - discount))
            items = json.dumps([{"service_slug": svc_slug, "qty": sessions}], ensure_ascii=False)
            pname = f"Bono {sessions} {svc_name} (demo)"
            connection.execute(
                "INSERT INTO packages (cliente_id, id, name, description, items_json, price_cents, currency, "
                "validity_days, is_active, sort_order, created_at, updated_at) VALUES (?, ?, ?, '', ?, ?, 'eur', 180, 1, 0, ?, ?)",
                (cliente_id, pid, pname, items, price, now, now),
            )
            packages.append((pid, pname, price, sessions))
            counts["packages"] += 1
        for amount in (5000, 10000, 3000):
            gid = DEMO_GIFTCARD_ID_PREFIX + secrets.token_urlsafe(6)
            code = "GC-DEMO-" + secrets.token_hex(2).upper()
            connection.execute(
                "INSERT INTO gift_cards (id, cliente_id, code, initial_cents, balance_cents, currency, status, "
                "buyer_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'eur', 'active', ?, ?, ?)",
                (gid, cliente_id, code, amount, amount, rng.choice(_DEMO_CUSTOMER_NAMES), now, now),
            )
            connection.execute(
                "INSERT INTO gift_card_transactions (cliente_id, gift_card_id, kind, amount_cents, "
                "balance_after_cents, created_at) VALUES (?, ?, 'issue', ?, ?, ?)",
                (cliente_id, gid, amount, amount, now),
            )
            counts["gift_cards"] += 1
        # Ventas de producto (~3 semanas) para que Ventas e Informes muestren datos.
        for _ in range(rng.randint(16, 26)):
            pid, pname, price = rng.choice(products)
            qty = rng.randint(1, 3)
            day = today - timedelta(days=rng.randint(0, 27))
            sid = DEMO_SALE_ID_PREFIX + secrets.token_urlsafe(6)
            connection.execute(
                "INSERT INTO product_sales (id, cliente_id, location_id, product_id, product_name, qty, "
                "unit_price_cents, total_cents, booking_id, customer_name, customer_email, payment_method, "
                "notes, status, customer_payment_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, '', ?, 'demo', 'paid', '', ?)",
                (sid, cliente_id, rng.choice(loc_ids + [""]), pid, pname, qty, price, price * qty,
                 rng.choice(_DEMO_CUSTOMER_NAMES), rng.choice(["cash", "card", "card", "transfer"]),
                 day.isoformat() + "T12:00:00Z"),
            )
            counts["sales"] += 1
        # Bonos vendidos (package_purchases).
        for pid, pname, price, sessions in packages:
            day = today - timedelta(days=rng.randint(1, 20))
            ppid = DEMO_PACKAGE_PURCHASE_ID_PREFIX + secrets.token_urlsafe(6)
            remaining = json.dumps({svc_slug: sessions}, ensure_ascii=False)
            connection.execute(
                "INSERT INTO package_purchases (id, cliente_id, package_id, package_name, buyer_name, buyer_email, "
                "buyer_phone, price_cents, remaining_json, expires_at, status, payment_method, location_id, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, '', 'active', 'card', '', ?, ?)",
                (ppid, cliente_id, pid, pname, rng.choice(_DEMO_CUSTOMER_NAMES),
                 f"demo+{secrets.token_hex(3)}@example.com", price, remaining, day.isoformat() + "T12:00:00Z", now),
            )
        connection.commit()
    return counts


def _create_demo_employees(cliente_id: str) -> List[Dict[str, Any]]:
    defaults = agenda._employee_defaults_for_client(cliente_id)
    created_at = timeutils._utc_now_iso()
    closed_json = json.dumps(defaults["closed_weekdays"])
    break_windows_json = json.dumps(defaults.get("break_windows", []))
    # Reparte los profesionales demo entre TODOS los centros del negocio (>=1 por centro)
    # para que la demo muestre agenda en cada local. _store_booking sella la cita al centro
    # del empleado, asi que basta con asignar location_id aqui.
    try:
        loc_rows = agenda._list_location_rows(cliente_id, include_inactive=False)
    except Exception:  # noqa: BLE001
        loc_rows = []
    loc_ids = [str(row["id"]) for row in loc_rows] or [""]
    # Equipo por centro (_DEMO_TEAM_SIZE profesionales en cada local) tomando perfiles
    # DISTINTOS del pool con un contador global: asi cada centro tiene gente diferente
    # (nombres y colores no se repiten entre centros mientras alcance el pool).
    plan = []
    k = 0
    for loc_id in loc_ids:
        for _ in range(_DEMO_TEAM_SIZE):
            plan.append((loc_id, _DEMO_PROFESSIONALS[k % len(_DEMO_PROFESSIONALS)]))
            k += 1
    employees: List[Dict[str, Any]] = []
    with db._get_db_connection() as connection:
        for location_id, profile in plan:
            employee_id = f"{DEMO_EMPLOYEE_ID_PREFIX}{secrets.token_urlsafe(6)}"
            connection.execute(
                """
                INSERT INTO employees (
                    id, cliente_id, name, role_label, color, is_active, is_default,
                    timezone, slot_minutes, day_start, day_end, break_start, break_end,
                    break_windows_json, closed_weekdays_json, service_ids_json, location_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)
                """,
                (
                    employee_id, cliente_id, profile["name"], profile["role_label"], profile["color"],
                    defaults["timezone"], int(defaults["slot_minutes"]),
                    defaults["day_start"], defaults["day_end"],
                    defaults["break_start"], defaults["break_end"], break_windows_json, closed_json,
                    location_id,
                    created_at, created_at,
                ),
            )
            employees.append({
                "id": employee_id, "name": profile["name"], "color": profile["color"],
                "location_id": location_id,
            })
        connection.commit()
    return employees


def _seed_demo_agenda(cliente_id: str) -> Dict[str, Any]:
    """Genera ~1 mes de citas demo repartidas entre varios profesionales.

    Idempotente: limpia datos demo previos antes de regenerar. Todas las citas
    quedan con source='demo_seed' y en profesionales 'empdemo_*' para poder
    borrarlas despues sin tocar datos reales. Cubre todos los estados (confirmada,
    pendiente, completada auto/manual, no-show, cancelada), confirmacion del cliente
    y siembra servicios demo (svcdemo_*) con todas las casuisticas de pago/politica.
    """
    _purge_demo_agenda(cliente_id)
    # Crea los centros demo ANTES de sembrar empleados/citas, para que la agenda (equipo +
    # citas) se reparta tambien en ellos. Si no, los centros demo quedarian sin agenda.
    _seed_demo_locations(cliente_id)

    defaults = agenda._employee_defaults_for_client(cliente_id)
    tz_name = defaults["timezone"] or settings.DEFAULT_TIMEZONE
    slot_minutes = max(10, int(defaults["slot_minutes"] or 30))
    closed_weekdays = set(defaults["closed_weekdays"] or [])
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
        tz_name = "UTC"

    start_dt = textnorm._parse_time(defaults["day_start"] or "09:00")
    end_dt = textnorm._parse_time(defaults["day_end"] or "18:00")
    break_intervals = agenda._break_intervals_from_windows(defaults.get("break_windows", []))
    day_slots: List[str] = []
    cursor = start_dt
    while cursor + timedelta(minutes=slot_minutes) <= end_dt:
        slot = cursor.strftime("%H:%M")
        slot_start_min = textnorm._time_to_min(slot)
        slot_end_min = (slot_start_min + slot_minutes) if slot_start_min is not None else None
        if (
            slot_start_min is not None
            and slot_end_min is not None
            and not agenda._interval_overlaps(slot_start_min, slot_end_min, break_intervals)
        ):
            day_slots.append(slot)
        cursor += timedelta(minutes=slot_minutes)
    if not day_slots:
        day_slots = ["10:00", "11:00", "12:00", "16:00", "17:00"]

    employees = _create_demo_employees(cliente_id)
    # Servicios demo (todas las casuisticas de pago/politica) + catalogo real, deduplicado.
    # Garantiza que cada caso aparezca reservado en la agenda. El perfil de pago se deriva
    # del propio servicio (payment_mode/payment_type), no de un round-robin artificial.
    demo_svcs = _seed_demo_services(cliente_id)
    demo_ids = {d["id"] for d in demo_svcs}
    services = demo_svcs + [
        s for s in _demo_services(cliente_id)
        if str(s.get("id") or s.get("slug") or "") not in demo_ids
    ]
    services = services[:16]
    today = datetime.now(tz).date()
    rng = random.Random(f"{cliente_id}:{today.isoformat()}")
    created_at = timeutils._utc_now_iso()
    bookings_created = 0
    # Escala el volumen con el nº de empleados para que cada centro quede poblado
    # (~120 citas/profesional, como el demo original de 3 profesionales), con techo.
    max_bookings = min(120 * max(1, len(employees)), 1500)
    end_day_min = textnorm._time_to_min(end_dt.strftime("%H:%M")) or (24 * 60)
    occupied_by_employee_day: Dict[Tuple[str, str], List[Tuple[int, int]]] = {}

    for offset in range(-7, 29):  # ~5 semanas alrededor de hoy
        day = today + timedelta(days=offset)
        if day.weekday() in closed_weekdays:
            continue
        is_past = day < today
        for emp in employees:
            sample_size = max(1, int(len(day_slots) * rng.uniform(0.25, 0.55)))
            chosen = rng.sample(day_slots, min(sample_size, len(day_slots)))
            for hora in chosen:
                if bookings_created >= max_bookings:
                    break
                service = rng.choice(services)
                service_name = str(service.get("nombre") or service.get("name") or "Consulta general").strip()
                service_id = str(service.get("id") or service.get("slug") or agenda._normalize_service_id(service_name))
                try:
                    service_duration = int(service.get("duration_minutes") or 0)
                except (TypeError, ValueError):
                    service_duration = 0
                if service_duration <= 0:
                    # Si el servicio no tiene duración definida, asignar una duración
                    # realista y variada para que el demo no quede monótono.
                    _DEMO_DURATION_POOL = [30, 45, 60, 45, 75, 30, 60, 90, 45, 60]
                    service_duration = _DEMO_DURATION_POOL[
                        hash(service_name) % len(_DEMO_DURATION_POOL)
                    ]
                try:
                    service_price = int(service.get("price_cents") or 0)
                except (TypeError, ValueError):
                    service_price = 0
                start_min = textnorm._time_to_min(hora)
                if start_min is None:
                    continue
                end_min = start_min + service_duration
                if end_min > end_day_min:
                    continue
                if agenda._interval_overlaps(start_min, end_min, break_intervals):
                    continue
                occupied_key = (emp["id"], day.isoformat())
                occupied = occupied_by_employee_day.setdefault(occupied_key, [])
                if any(start_min < busy_end and end_min > busy_start for busy_start, busy_end in occupied):
                    continue
                start_local = datetime.fromisoformat(f"{day.isoformat()}T{hora}:00").replace(tzinfo=tz)
                end_local = start_local + timedelta(minutes=service_duration)
                # Estado: pasado -> completada (auto/manual) / no-show / cancelada;
                # futuro -> pendiente de revision / confirmada. Cubre todas las casuisticas.
                if is_past:
                    r = rng.random()
                    status_value = "cancelled" if r < 0.15 else "no_show" if r < 0.30 else "completed"
                    completed_source = ("auto" if rng.random() < 0.4 else "manual") if status_value == "completed" else ""
                else:
                    status_value = "pending_review" if rng.random() < 0.2 else "confirmed"
                    completed_source = ""
                # Perfil de pago derivado del PROPIO servicio (con/sin Stripe, deposito, retencion).
                svc_mode = str(service.get("payment_mode") or "payment_disabled")
                svc_ptype = str(service.get("payment_type") or "full")
                if service_price <= 0 or svc_mode == "payment_disabled":
                    pay_profile = "none"
                elif svc_ptype == "preauth":
                    pay_profile = "preauth"
                else:
                    pay_profile = "full"
                if pay_profile == "none" or status_value == "cancelled":
                    pay_status = "not_required"
                elif status_value in ("completed", "no_show"):
                    pay_status = "paid" if rng.random() < 0.8 else "not_required"
                elif pay_profile == "preauth":
                    pay_status = "preauthorized" if rng.random() < 0.7 else "pending"
                else:  # full / optional
                    pay_status = "paid" if rng.random() < 0.55 else "pending"
                booking_id = secrets.token_urlsafe(16)
                record = {
                    "id": booking_id,
                    "cliente_id": cliente_id,
                    "employee_id": emp["id"],
                    "employee_name": emp["name"],
                    "nombre": rng.choice(_DEMO_CUSTOMER_NAMES),
                    "email": f"demo+{booking_id[:8].lower()}@example.com",
                    "telefono": f"+34 6{rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(100, 999)}",
                    "servicio": service_name,
                    "booking_date": day.isoformat(),
                    "booking_time": hora,
                    "notas": "Cita de demostracion",
                    "status": status_value,
                    "provider_name": "internal",
                    "provider_status": status_value,
                    "provider_booking_id": "",
                    "provider_booking_url": "",
                    "manage_token": booking._generate_manage_token(),
                    "timezone": tz_name,
                    "start_at": timeutils._to_utc_iso(start_local),
                    "end_at": timeutils._to_utc_iso(end_local),
                    "confirmed_at": created_at if status_value in ("confirmed", "completed") else "",
                    "cancelled_at": created_at if status_value == "cancelled" else "",
                    **booking._booking_blank_tracking_fields(),
                    "service_id": service_id,
                    "service_price_cents": service_price,
                    "payment_status": pay_status,
                    "source": DEMO_BOOKING_SOURCE,
                    "created_at": created_at,
                }
                try:
                    # skip_payment=True: cita demo VISUAL, sin crear checkouts Stripe reales.
                    booking._store_booking(record, skip_payment=True)
                except sqlite3.IntegrityError:
                    continue
                # completed_source no lo escribe el INSERT base; lo ajustamos por UPDATE.
                if completed_source:
                    with db._get_db_connection() as _conn:
                        _conn.execute(
                            "UPDATE bookings SET completed_source=? WHERE id=?",
                            (completed_source, booking_id),
                        )
                        _conn.commit()
                # Para que la demo enseñe la distinción "cita confirmada" (hueco activo)
                # vs "cliente confirmó asistencia", sembramos confirmación explícita del
                # cliente en ~55% de las citas futuras confirmadas (audit -> marca ✓).
                if not is_past and status_value == "confirmed" and rng.random() < 0.55:
                    booking._record_booking_audit(
                        booking_id,
                        cliente_id,
                        "attendance_confirmed_by_customer",
                        {"channel": rng.choice(["whatsapp", "voice", "email"]), "source": "demo_seed"},
                    )
                occupied.append((start_min, end_min))
                bookings_created += 1
        if bookings_created >= max_bookings:
            break

    commerce = _seed_demo_commerce(cliente_id)

    return {
        "employees_created": len(employees),
        "bookings_created": bookings_created,
        "timezone": tz_name,
        "commerce": commerce,
    }




_DEMO_SECTOR_DEFAULTS: Dict[str, tuple] = {
    "centro de masajes": ("Centro de masajes y bienestar.", "Masajes terapeuticos, relajantes y descontracturantes. Reserva de sesiones."),
    "clinica dental": ("Clinica dental.", "Revisiones, limpiezas, ortodoncia, implantes y estetica dental."),
    "clinica estetica": ("Centro de estetica y belleza.", "Tratamientos faciales, corporales y de belleza."),
    "fisioterapia": ("Clinica de fisioterapia.", "Fisioterapia, rehabilitacion y recuperacion de lesiones."),
    "peluqueria": ("Peluqueria y salon de belleza.", "Corte, color, peinado y tratamientos capilares."),
    "centro veterinario": ("Centro veterinario.", "Consultas, vacunaciones, cirugia y urgencias veterinarias."),
}

