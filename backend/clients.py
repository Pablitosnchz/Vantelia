"""Config multi-tenant de clientes (refactor F3).

Carga/normaliza/serializa config.json, lo valida en runtime, y mantiene la
tabla `clientes` de SQLite en lockstep con el JSON (sync tras persistir).
appstate.CONFIG_CLIENTES es la fuente de verdad en memoria.
"""
from __future__ import annotations

import copy
import json
import shutil
import re
import sqlite3
from typing import Any, Dict, List, Tuple

from fastapi import HTTPException, Request

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from backend import appstate, db, settings, textnorm, timeutils

def _load_client_configs() -> Dict[str, Dict[str, Any]]:
    if not settings.CONFIG_PATH.exists():
        raise RuntimeError(f"No se encontro el archivo de configuracion: {settings.CONFIG_PATH}")

    raw_config = json.loads(settings.CONFIG_PATH.read_text(encoding="utf-8"))
    normalized: Dict[str, Dict[str, Any]] = {}

    for cliente_id, payload in raw_config.items():
        normalized[cliente_id] = _normalize_client_config(cliente_id, payload)

    return normalized


# Secciones de config que NO gestiona el normalizador pero que pertenecen al tenant y
# DEBEN sobrevivir a la carga y al guardado (antes la whitelist las descartaba en cada
# arranque: identidad "empresa", Seguimiento "reminders", resenas "reviews" y la compra
# publica de tarjetas "gift_cards_public" volvian a sus defaults en runtime).
# Ajustes de la seccion `booking` que se conservan tal cual al guardar. La
# serializacion enumera las claves una a una, asi que lo que no este aqui se
# descarta en silencio en cada guardado (paso de verdad con `estilo`). Si anades
# un ajuste de agenda, anadelo tambien aqui.
CONFIG_BOOKING_EXTRA_KEYS = (
    "estilo",            # "guiado" (listas) o "conversacional"
    "rescate_enabled",   # ofrecer llamar antes de perder una cita
    "rescate_texto",     # con {telefono}
    "preferir_packs",    # los tecnicos se reservan como pack, no sueltos
    "form_intro",        # texto al abrir la reserva
)


CONFIG_EXTRA_SECTIONS = (
    "empresa", "reminders", "reviews", "gift_cards_public", "shop_public", "negocio",
    "keyword_rules", "chat_menu", "ai_intents", "tono",
    # Por que canales sale cada aviso de cita (confirmada, cambiada, cancelada,
    # recordatorios). Sin registrarla, lo que el negocio marcaba en su portal se
    # perdia en el siguiente arranque y los avisos volvian a salir SOLO por email:
    # a un salon que trabaja por WhatsApp eso le deja al cliente sin enterarse de
    # que le han cancelado la cita.
    "message_template_channels", "message_templates",
)


def _copy_extra_sections(source: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    for key in CONFIG_EXTRA_SECTIONS:
        if key in source and source.get(key) is not None:
            value = source[key]
            if isinstance(value, dict):
                target[key] = json.loads(json.dumps(value))
            elif isinstance(value, str):
                target[key] = textnorm._sanitize_text(value)[:300]
    return target


def _normalize_client_config(cliente_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not settings.CLIENT_ID_PATTERN.match(cliente_id):
        raise RuntimeError(f"cliente_id invalido en config.json: {cliente_id}")

    booking_row = payload.get("booking", {})
    booking_day_start = textnorm._sanitize_text(booking_row.get("day_start", "09:00")) or "09:00"
    booking_day_end = textnorm._sanitize_text(booking_row.get("day_end", "18:00")) or "18:00"
    booking_break_windows = textnorm._normalize_break_windows(
        booking_day_start,
        booking_day_end,
        booking_row.get("break_windows", []),
        booking_row.get("break_start", ""),
        booking_row.get("break_end", ""),
    )
    booking_break_start, booking_break_end = textnorm._first_break_pair(booking_break_windows)
    allowed_origins = [
        textnorm._normalize_origin_value(origin)
        for origin in payload.get("allowed_origins", [])
        if isinstance(origin, str) and str(origin).strip()
    ]

    incoming_subscription = payload.get("subscription") if isinstance(payload.get("subscription"), dict) else {}
    explicit_plan = payload.get("plan") or incoming_subscription.get("plan")
    plan = settings._normalize_plan_slug(explicit_plan or settings.PLAN_DEFAULT)
    if plan not in settings.PLAN_VALID:
        plan = settings.PLAN_DEFAULT
    subscription = dict(incoming_subscription)
    subscription["plan"] = plan

    chat_model_value = textnorm._sanitize_text(payload.get("chat_model", ""))
    if chat_model_value and chat_model_value not in settings.AVAILABLE_CHAT_MODELS_BOOT:
        chat_model_value = ""
    try:
        temperature_value = float(payload.get("temperature", 0.2))
    except (TypeError, ValueError):
        temperature_value = 0.2
    temperature_value = max(0.0, min(2.0, temperature_value))

    normalized = {
        "nombre": textnorm._sanitize_text(payload.get("nombre", cliente_id)),
        "plan": plan,
        "subscription": subscription,
        "icono": textnorm._sanitize_text(payload.get("icono", "Chat"))[:12] or "Chat",
        "color": textnorm._sanitize_text(payload.get("color", "#00b1d9")) or "#00b1d9",
        "accent_color": textnorm._sanitize_text(payload.get("accent_color", "")),
        "logo_url": textnorm._sanitize_text(payload.get("logo_url", "")),
        "bienvenida": textnorm._sanitize_text(
            payload.get("bienvenida", "Hola, soy tu asistente virtual. En que puedo ayudarte?"),
            allow_multiline=True,
        ),
        "prompt_extra": textnorm._sanitize_text(payload.get("prompt_extra", ""), allow_multiline=True),
        "chat_model": chat_model_value,
        "temperature": temperature_value,
        "allowed_origins": allowed_origins,
        "contacto": {
            "email": textnorm._sanitize_text(str(payload.get("contacto", {}).get("email", ""))),
            "telefono": textnorm._sanitize_text(str(payload.get("contacto", {}).get("telefono", ""))),
            # DONDE esta el negocio. Sin guardarlo, el asistente no la tiene y se
            # inventa la ubicacion ("estamos en el centro de la ciudad"), y encima
            # se perdia en cada despliegue: es la misma whitelist que ya se comio
            # los canales de aviso.
            "direccion": textnorm._sanitize_text(str(payload.get("contacto", {}).get("direccion", ""))),
            "mapa": textnorm._sanitize_text(str(payload.get("contacto", {}).get("mapa", ""))),
        },
        "branding": {
            "powered_by": textnorm._sanitize_text(
                str(payload.get("branding", {}).get("powered_by", "Powered by Vantelia"))
            )
            or "Powered by Vantelia"
        },
        "whatsapp": {
            "enabled": bool(payload.get("whatsapp", {}).get("enabled", False)),
            "phone_number_id": textnorm._sanitize_text(
                str(payload.get("whatsapp", {}).get("phone_number_id", ""))
            )[:120],
            "access_token_env": textnorm._sanitize_text(
                str(payload.get("whatsapp", {}).get("access_token_env", ""))
            )[:120],
            "verify_token_env": textnorm._sanitize_text(
                str(payload.get("whatsapp", {}).get("verify_token_env", ""))
            )[:120],
        },
        "voice": textnorm._normalize_voice_config(payload.get("voice", {})),
        # Permite que un demo creado a mano (no demo_auto_*) muestre el banner de
        # "reclamar/activar" y sea reclamable publicamente. Opt-in: por defecto False,
        # asi los clientes reales (ej. "van") nunca quedan expuestos.
        "demo_claimable": bool(payload.get("demo_claimable", False)),
        "booking": {
            "enabled": bool(booking_row.get("enabled", False)),
            "timezone": textnorm._sanitize_text(booking_row.get("timezone", settings.DEFAULT_TIMEZONE)) or settings.DEFAULT_TIMEZONE,
            "slot_minutes": int(booking_row.get("slot_minutes", 30)),
            "day_start": booking_day_start,
            "day_end": booking_day_end,
            "break_start": booking_break_start,
            "break_end": booking_break_end,
            "break_windows": booking_break_windows,
            "closed_weekdays": booking_row.get("closed_weekdays", [6]),
            "weekly_hours": textnorm._normalize_weekly_hours(booking_row.get("weekly_hours", {})),
            "provider": "internal",
            "webhook_env": textnorm._sanitize_text(booking_row.get("webhook_env", "")),
            "webhook_url": textnorm._normalize_optional_http_url(booking_row.get("webhook_url", "")),
            "calendly_user_env": "",
            "calendly_event_type_env": "",
            "calendly_location_kind": "",
            "calendly_location_value": "",
            "google_calendar_id": "",
            "google_calendar_id_env": "",
            "google_service_account_path": "",
            "google_service_account_env": "",
            "success_message": textnorm._sanitize_text(
                booking_row.get(
                    "success_message",
                    "Tu solicitud de cita ha quedado registrada correctamente.",
                ),
                allow_multiline=True,
            ),
            "message_templates": textnorm._normalize_message_templates(booking_row.get("message_templates", {})),
            "message_template_enabled": textnorm._normalize_message_template_enabled(
                booking_row.get("message_template_enabled", {}),
                booking_row.get("message_templates", {}),
            ),
            "message_template_channels": textnorm._normalize_message_template_channels(
                booking_row.get("message_template_channels", {})
            ),
        },
    }
    # Al CARGAR pasa lo mismo que al guardar: lo que no se enumere aqui se pierde
    # en cada arranque, aunque este escrito en el config.json.
    for clave in CONFIG_BOOKING_EXTRA_KEYS:
        if clave in booking_row:
            normalized["booking"][clave] = booking_row[clave]
    return _copy_extra_sections(payload, normalized)


def _serialize_client_config(config: Dict[str, Any]) -> Dict[str, Any]:
    booking_cfg = config.get("booking", {})
    break_windows = textnorm._normalize_break_windows(
        booking_cfg.get("day_start", "09:00"),
        booking_cfg.get("day_end", "18:00"),
        booking_cfg.get("break_windows", []),
        booking_cfg.get("break_start", ""),
        booking_cfg.get("break_end", ""),
    )
    break_start, break_end = textnorm._first_break_pair(break_windows)
    serialized = {
        "nombre": config["nombre"],
        "plan": config.get("plan", settings.PLAN_DEFAULT),
        "subscription": dict(config.get("subscription") or {"plan": config.get("plan", settings.PLAN_DEFAULT)}),
        "icono": config["icono"],
        "color": config["color"],
        "accent_color": config.get("accent_color", ""),
        "logo_url": config.get("logo_url", ""),
        "bienvenida": config["bienvenida"],
        "prompt_extra": config.get("prompt_extra", ""),
        "chat_model": config.get("chat_model", ""),
        "temperature": float(config.get("temperature", 0.2)),
        "allowed_origins": list(config.get("allowed_origins", [])),
        "contacto": {
            "email": config.get("contacto", {}).get("email", ""),
            "telefono": config.get("contacto", {}).get("telefono", ""),
            "direccion": config.get("contacto", {}).get("direccion", ""),
            "mapa": config.get("contacto", {}).get("mapa", ""),
        },
        "branding": {
            "powered_by": config.get("branding", {}).get("powered_by", "Powered by Vantelia"),
        },
        "whatsapp": {
            "enabled": bool(config.get("whatsapp", {}).get("enabled", False)),
            "phone_number_id": config.get("whatsapp", {}).get("phone_number_id", ""),
            "access_token_env": config.get("whatsapp", {}).get("access_token_env", ""),
            "verify_token_env": config.get("whatsapp", {}).get("verify_token_env", ""),
        },
        "voice": textnorm._normalize_voice_config(config.get("voice", {})),
        "demo_claimable": bool(config.get("demo_claimable", False)),
        "booking": {
            "enabled": bool(config.get("booking", {}).get("enabled", False)),
            "timezone": config.get("booking", {}).get("timezone", settings.DEFAULT_TIMEZONE),
            "slot_minutes": int(config.get("booking", {}).get("slot_minutes", 30)),
            "day_start": config.get("booking", {}).get("day_start", "09:00"),
            "day_end": config.get("booking", {}).get("day_end", "18:00"),
            "break_start": break_start,
            "break_end": break_end,
            "break_windows": break_windows,
            "closed_weekdays": list(config.get("booking", {}).get("closed_weekdays", [6])),
            "weekly_hours": dict(config.get("booking", {}).get("weekly_hours", {}) or {}),
            "provider": "internal",
            "webhook_env": config.get("booking", {}).get("webhook_env", ""),
            "webhook_url": config.get("booking", {}).get("webhook_url", ""),
            "calendly_user_env": "",
            "calendly_event_type_env": "",
            "calendly_location_kind": "",
            "calendly_location_value": "",
            "google_calendar_id": "",
            "google_calendar_id_env": "",
            "google_service_account_path": "",
            "google_service_account_env": "",
            "success_message": config.get("booking", {}).get(
                "success_message",
                "Tu solicitud de cita ha quedado registrada correctamente.",
            ),
            "message_templates": textnorm._normalize_message_templates(
                config.get("booking", {}).get("message_templates", {})
            ),
            "message_template_enabled": textnorm._normalize_message_template_enabled(
                config.get("booking", {}).get("message_template_enabled", {}),
                config.get("booking", {}).get("message_templates", {}),
            ),
            "message_template_channels": textnorm._normalize_message_template_channels(
                config.get("booking", {}).get("message_template_channels", {})
            ),
        },
    }
    for clave in CONFIG_BOOKING_EXTRA_KEYS:
        if clave in booking_cfg:
            serialized["booking"][clave] = booking_cfg[clave]
    return _copy_extra_sections(config, serialized)


appstate.CONFIG_CLIENTES = _load_client_configs()


def _collect_cors_origins() -> List[str]:
    origins = set(textnorm.EXTRA_CORS_ORIGINS)
    with appstate.state_lock:
        for config in appstate.CONFIG_CLIENTES.values():
            origins.update(config.get("allowed_origins", []))
    return sorted(origin for origin in origins if origin)


def _update_runtime_configs(next_configs: Dict[str, Dict[str, Any]]) -> None:
    with appstate.state_lock:
        appstate.CONFIG_CLIENTES.clear()
        appstate.CONFIG_CLIENTES.update(next_configs)


def _reload_runtime_configs_from_disk() -> Dict[str, Dict[str, Any]]:
    """Recarga el snapshot compartido; usar bajo el lock de escritura cross-worker."""
    latest_configs = _load_client_configs()
    _update_runtime_configs(latest_configs)
    return latest_configs


def _sync_clientes_table_from_config() -> None:
    """Mirror in-memory CONFIG_CLIENTES into the clientes table.

    Called on startup after _load_client_configs. Idempotent: existing rows
    keep their owner_user_id, plan and source fields; only nombre/config_json
    are refreshed from the JSON snapshot.
    """
    try:
        with appstate.state_lock:
            snapshot = {cid: copy.deepcopy(cfg) for cid, cfg in appstate.CONFIG_CLIENTES.items()}
    except Exception:  # noqa: BLE001
        snapshot = {}
    if not snapshot:
        return
    now_iso = timeutils._utc_now().isoformat()
    with db._get_db_connection() as connection:
        existing_ids = {
            row["cliente_id"]
            for row in connection.execute("SELECT cliente_id FROM clientes").fetchall()
        }
        for cliente_id, config in snapshot.items():
            serialized = _serialize_client_config(config)
            config_json = json.dumps(serialized, ensure_ascii=False)
            nombre = serialized.get("nombre") or cliente_id
            plan = serialized.get("plan") or settings.PLAN_DEFAULT
            if cliente_id in existing_ids:
                connection.execute(
                    """
                    UPDATE clientes
                    SET nombre = ?, config_json = ?, updated_at = ?
                    WHERE cliente_id = ?
                    """,
                    (nombre, config_json, now_iso, cliente_id),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO clientes
                        (cliente_id, owner_user_id, plan, nombre, website_url,
                         config_json, created_at, updated_at, source)
                    VALUES (?, '', ?, ?, '', ?, ?, ?, 'legacy')
                    """,
                    (cliente_id, plan, nombre, config_json, now_iso, now_iso),
                )
        connection.commit()


def _sync_clientes_table_after_persist(configs: Dict[str, Dict[str, Any]]) -> None:
    """Apply incremental updates to the clientes table after _persist_configs_to_disk.

    Handles inserts, updates and deletes so DB stays in lockstep with JSON.
    Preserves owner_user_id and source columns for existing rows.
    """
    now_iso = timeutils._utc_now().isoformat()
    try:
        with db._get_db_connection() as connection:
            existing = {
                row["cliente_id"]: row
                for row in connection.execute(
                    "SELECT cliente_id, owner_user_id, source FROM clientes"
                ).fetchall()
            }
            incoming_ids = set(configs.keys())
            for cliente_id, config in configs.items():
                serialized = _serialize_client_config(config)
                config_json = json.dumps(serialized, ensure_ascii=False)
                nombre = serialized.get("nombre") or cliente_id
                plan = serialized.get("plan") or settings.PLAN_DEFAULT
                if cliente_id in existing:
                    connection.execute(
                        """
                        UPDATE clientes
                        SET nombre = ?, plan = ?, config_json = ?, updated_at = ?
                        WHERE cliente_id = ?
                        """,
                        (nombre, plan, config_json, now_iso, cliente_id),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO clientes
                            (cliente_id, owner_user_id, plan, nombre, website_url,
                             config_json, created_at, updated_at, source)
                        VALUES (?, '', ?, ?, '', ?, ?, ?, 'legacy')
                        """,
                        (cliente_id, plan, nombre, config_json, now_iso, now_iso),
                    )
            stale = set(existing.keys()) - incoming_ids
            for cliente_id in stale:
                connection.execute("DELETE FROM clientes WHERE cliente_id = ?", (cliente_id,))
            connection.commit()
    except sqlite3.Error as exc:
        settings.logger.error("Fallo sync clientes table tras persist JSON: %s", exc)


def _validate_single_client_runtime(cliente_id: str, config: Dict[str, Any]) -> None:
    booking_cfg = config["booking"]
    provider = booking_cfg.get("provider", "internal")
    whatsapp_cfg = config.get("whatsapp", {})
    if not re.match(r"^#[0-9A-Fa-f]{6}$", str(config.get("color", ""))):
        raise RuntimeError(f"color invalido para {cliente_id}. Usa formato #RRGGBB.")
    accent_color = str(config.get("accent_color", "")).strip()
    if accent_color and not re.match(r"^#[0-9A-Fa-f]{6}$", accent_color):
        raise RuntimeError(f"accent_color invalido para {cliente_id}. Usa formato #RRGGBB.")
    if whatsapp_cfg.get("enabled") and not str(whatsapp_cfg.get("phone_number_id", "")).strip():
        raise RuntimeError(f"whatsapp.phone_number_id requerido para {cliente_id} si WhatsApp esta activo")
    if booking_cfg["enabled"]:
        try:
            ZoneInfo(booking_cfg["timezone"])
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"timezone invalida para {cliente_id}") from exc
        if not settings.TIME_PATTERN.match(booking_cfg["day_start"]):
            raise RuntimeError(f"day_start invalido para {cliente_id}")
        if not settings.TIME_PATTERN.match(booking_cfg["day_end"]):
            raise RuntimeError(f"day_end invalido para {cliente_id}")
        try:
            textnorm._normalize_break_windows(
                booking_cfg["day_start"],
                booking_cfg["day_end"],
                booking_cfg.get("break_windows", []),
                booking_cfg.get("break_start", ""),
                booking_cfg.get("break_end", ""),
            )
        except HTTPException as exc:
            raise RuntimeError(f"descansos invalidos para {cliente_id}: {exc.detail}") from exc
        if booking_cfg["slot_minutes"] <= 0:
            raise RuntimeError(f"slot_minutes invalido para {cliente_id}")
        if not isinstance(booking_cfg["closed_weekdays"], list) or any(
            not isinstance(day, int) or day < 0 or day > 6 for day in booking_cfg["closed_weekdays"]
        ):
            raise RuntimeError(f"closed_weekdays invalido para {cliente_id}")
        if provider != "internal":
            raise RuntimeError(f"provider invalido para {cliente_id}")


def _validate_runtime_config() -> None:
    if not settings.OPENAI_API_KEY:
        settings.logger.warning("OPENAI_API_KEY no esta configurada. El chat quedara deshabilitado.")

    for cliente_id, config in appstate.CONFIG_CLIENTES.items():
        _validate_single_client_runtime(cliente_id, config)

    if settings.WEBHOOK_DEFAULT:
        textnorm._normalize_optional_http_url(settings.WEBHOOK_DEFAULT)


def _persist_configs_to_disk(configs: Dict[str, Dict[str, Any]]) -> None:
    serialized = {
        cliente_id: _serialize_client_config(config)
        for cliente_id, config in sorted(configs.items(), key=lambda item: item[0].lower())
    }
    settings.CONFIG_PATH.write_text(
        json.dumps(serialized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _sync_clientes_table_after_persist(configs)




def _client_subscription(cliente_id: str) -> Dict[str, Any]:
    config = appstate.CONFIG_CLIENTES.get(cliente_id) or {}
    sub = config.get("subscription") or {}

    # Self-serve users store their plan in the DB. DB takes precedence over config.json.
    db_sub = db.db_subscription_for_cliente(cliente_id)
    if db_sub:
        db_plan = settings._normalize_plan_slug(db_sub["plan"] or settings.PLAN_DEFAULT)
        if db_plan not in settings.PLAN_VALID:
            db_plan = settings.PLAN_DEFAULT
        return {
            "plan": db_plan,
            "status": str(db_sub["status"] or "active"),
            "started_at": str(db_sub["current_period_start"] or ""),
            "renews_at": str(db_sub["current_period_end"] or ""),
            "canceled_at": "",
            "stripe_customer_id": str(db_sub["stripe_customer_id"] or ""),
            "stripe_subscription_id": str(db_sub["stripe_subscription_id"] or ""),
            "billing_period": "monthly",
            "lifetime": bool(db_sub["cancel_at_period_end"] == 0 and (db_sub["stripe_subscription_id"] or "") == "" and db_plan != "free"),
        }

    plan = settings._normalize_plan_slug(sub.get("plan") or config.get("plan") or settings.PLAN_DEFAULT)
    if plan not in settings.PLAN_VALID:
        plan = settings.PLAN_DEFAULT
    return {  # noqa: RET504
        "plan": plan,
        "status": str(sub.get("status") or "active"),
        "started_at": str(sub.get("started_at") or ""),
        "renews_at": str(sub.get("renews_at") or ""),
        "canceled_at": str(sub.get("canceled_at") or ""),
        "stripe_customer_id": str(sub.get("stripe_customer_id") or ""),
        "stripe_subscription_id": str(sub.get("stripe_subscription_id") or ""),
        "billing_period": str(sub.get("billing_period") or "monthly"),
        "lifetime": bool(sub.get("lifetime") or str(sub.get("billing_period") or "").lower() == "lifetime"),
    }


def _client_plan(cliente_id: str) -> str:
    return _client_subscription(cliente_id)["plan"]


def _plan_limits(plan: str) -> Dict[str, Any]:
    normalized = settings._normalize_plan_slug(plan)
    return settings.PLAN_LIMITS.get(normalized) or settings.PLAN_LIMITS[settings.PLAN_DEFAULT]




def _get_client_config(cliente_id: str) -> Dict[str, Any]:
    # Las auto-demos se crean y purgan en caliente. En multiproceso, el snapshot
    # Python de otro worker puede estar obsoleto aunque SQLite/config.json ya
    # contengan el estado correcto, asi que para ellas SQLite es autoritativo.
    if cliente_id.startswith("demo_auto_"):
        row = None
        lookup_failed = False
        try:
            with db._get_db_connection() as connection:
                row = connection.execute(
                    "SELECT config_json FROM clientes WHERE cliente_id=?",
                    (cliente_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            lookup_failed = True
            settings.logger.warning(
                "No se pudo refrescar config de auto-demo %s: %s", cliente_id, exc
            )
        if lookup_failed:
            config = appstate.CONFIG_CLIENTES.get(cliente_id)
            if config:
                return config
        fresh_config = None
        if row:
            try:
                raw_config = json.loads(str(row["config_json"] or "{}"))
                fresh_config = _normalize_client_config(cliente_id, raw_config)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                settings.logger.error(
                    "Config SQLite invalida para auto-demo %s: %s", cliente_id, exc
                )
        with appstate.state_lock:
            if fresh_config:
                appstate.CONFIG_CLIENTES[cliente_id] = fresh_config
            else:
                appstate.CONFIG_CLIENTES.pop(cliente_id, None)
        if fresh_config:
            return fresh_config
    config = appstate.CONFIG_CLIENTES.get(cliente_id)
    if not config:
        raise HTTPException(status_code=404, detail="Cliente no configurado")
    return config




def _plan_feature(cliente_id: str, feature: str) -> Any:
    return _plan_limits(_client_plan(cliente_id)).get(feature)




def _client_booking_plan_enabled(cliente_id: str) -> bool:
    """Whether booking is available in the client's effective plan."""
    owner = db.db_get_client_owner(cliente_id)
    if owner:
        sub = db.db_get_subscription_for_user(owner)
        plan = settings._normalize_plan_slug(sub["plan"] if sub else settings.PLAN_DEFAULT)
        return "booking" in (settings._self_serve_plan(plan).get("features") or [])

    booking_limit = _plan_limits(_client_plan(cliente_id)).get("monthly_bookings")
    if booking_limit is None:
        return True
    try:
        return int(booking_limit) > 0
    except (TypeError, ValueError):
        return False




def _current_billing_period() -> Tuple[str, str]:
    now = timeutils._utc_now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.isoformat(), end.isoformat()


def _delete_client_everywhere(
    cliente_id: str, *, skip_demo_registry_cleanup: bool = False
) -> None:
    textnorm._assert_valid_client_id(cliente_id)
    if cliente_id not in appstate.CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no configurado")

    next_configs = copy.deepcopy(appstate.CONFIG_CLIENTES)
    next_configs.pop(cliente_id, None)
    _persist_configs_to_disk(next_configs)
    _update_runtime_configs(next_configs)
    _purge_client_data(
        cliente_id, skip_demo_registry_cleanup=skip_demo_registry_cleanup
    )


def _purge_client_data(
    cliente_id: str, *, skip_demo_registry_cleanup: bool = False
) -> None:
    """Limpieza de BD, sesiones e indices/ficheros de UN tenant, SIN exigir que siga en
    config: tambien vale para huerfanos (demo expirada cuyo config ya no existe pero cuyos
    usuarios podian seguir entrando). Borra usuarios del tenant y sus sesiones: nadie
    puede volver a entrar."""
    textnorm._assert_valid_client_id(cliente_id)
    with db._get_db_connection() as connection:
        user_rows = connection.execute(
            "SELECT id FROM users WHERE role = 'client' AND cliente_id = ?",
            (cliente_id,),
        ).fetchall()
        user_ids = [row["id"] for row in user_rows]
        if user_ids:
            placeholders = ",".join("?" for _ in user_ids)
            params = tuple(user_ids)
            connection.execute(f"DELETE FROM auth_sessions WHERE user_id IN ({placeholders})", params)
            connection.execute(f"DELETE FROM password_reset_tokens WHERE user_id IN ({placeholders})", params)
            connection.execute(f"DELETE FROM subscriptions WHERE user_id IN ({placeholders})", params)
            connection.execute(f"DELETE FROM message_usage_events WHERE user_id IN ({placeholders})", params)
            connection.execute(f"DELETE FROM admin_impersonations WHERE target_user_id IN ({placeholders})", params)
            connection.execute(f"DELETE FROM user_permission_overrides WHERE user_id IN ({placeholders})", params)
        connection.execute("DELETE FROM users WHERE role = 'client' AND cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM subscriptions WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM message_usage_events WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM admin_impersonations WHERE target_cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM booking_audit WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM bookings WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM agenda_blocks WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM employees WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM chat_messages WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM chat_sessions WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM live_chat_sessions WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM analytics_events WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM whatsapp_inbound_messages WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM kb_qa WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM kb_documents WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM bot_leads WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM crm_contact_audit WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM crm_contact_links WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM crm_contacts WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM customer_payment_events WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM customer_payments WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM service_payment_policies WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM client_payment_accounts WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM client_channel_audit WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM client_channel_oauth_states WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM client_oauth_connections WHERE cliente_id = ?", (cliente_id,))
        connection.execute("DELETE FROM client_channel_settings WHERE cliente_id = ?", (cliente_id,))
        # Catalogo, comercio, centros y voz (tablas posteriores al borrado original):
        for extra_table in (
            "service_location_overrides", "services", "resources", "locations",
            "cancellation_policies", "voice_calls",
            "product_sales", "products",
            "package_purchases", "packages",
            "gift_card_transactions", "gift_cards",
        ):
            try:
                connection.execute(f"DELETE FROM {extra_table} WHERE cliente_id = ?", (cliente_id,))
            except Exception as exc:  # noqa: BLE001 - tabla opcional segun version de schema
                settings.logger.warning("Borrado de %s para %s fallo: %s", extra_table, cliente_id, exc)
        connection.execute("DELETE FROM clientes WHERE cliente_id = ?", (cliente_id,))
        connection.commit()

    with appstate.state_lock:
        appstate.indices.pop(cliente_id, None)
        for session_id in [sid for sid, session in appstate.sesiones.items() if session.cliente_id == cliente_id]:
            appstate.sesiones.pop(session_id, None)

    for base_dir in (settings.DATA_DIR, settings.STORAGE_DIR):
        target_dir = base_dir / cliente_id
        textnorm._ensure_path_within(base_dir, target_dir)
        if target_dir.exists():
            shutil.rmtree(target_dir)

    if not skip_demo_registry_cleanup:
        try:
            from backend import demo_agenda  # lazy: evita ciclo clients<->demo
            demo_agenda._unregister_demo_tenant(cliente_id)
        except Exception as exc:  # noqa: BLE001
            settings.logger.warning("No se pudo limpiar demo registry para %s: %s", cliente_id, exc)


def _build_install_snippet(cliente_id: str, request: Request) -> Dict[str, str]:
    api_base = textnorm._public_base_url(request)
    widget_version = ""
    widget_path = settings.WIDGET_DIR / "widget.min.js"
    if widget_path.exists():
        widget_version = f"?v={int(widget_path.stat().st_mtime)}"

    widget_script_url = f"{api_base}/widget/widget.min.js{widget_version}"
    demo_url = f"{api_base}/demo/{cliente_id}"
    central_url = f"{api_base}/reservas/{cliente_id}"
    snippet = (
        '<script\n'
        f'  src="{widget_script_url}"\n'
        f'  data-api="{api_base}"\n'
        f'  data-client="{cliente_id}"\n'
        '  data-position="right"></script>'
    )
    return {
        "install_snippet": snippet,
        "widget_script_url": widget_script_url,
        "api_base_url": api_base,
        "demo_url": demo_url,
        "central_url": central_url,
    }




def _require_plan_feature(cliente_id: str, feature: str, error_message: str) -> None:
    if not _plan_feature(cliente_id, feature):
        raise HTTPException(status_code=403, detail=error_message)


def call_us_line(cliente_id: str) -> str:
    """Salida humana cuando la agenda no da: que llamen y el negocio lo cuadra.

    Un salon puede hacer hueco moviendo cosas que el sistema no sabe (juntar dos
    clientas, alargar un rato, repartirse el trabajo). Sin esta linea, quien no
    encuentra hueco simplemente se va. Si el negocio no tiene telefono publicado,
    no se inventa nada.
    """
    try:
        config = _get_client_config(cliente_id)
    except Exception:  # noqa: BLE001 - el mensaje nunca debe romperse por esto
        return ""
    booking_cfg = config.get("booking") or {}
    if booking_cfg.get("rescate_enabled") is False:  # el negocio lo ha apagado
        return ""
    telefono = str((config.get("contacto") or {}).get("telefono") or "").strip()
    if not telefono:
        return ""
    plantilla = str(booking_cfg.get("rescate_texto") or "").strip()
    if plantilla:
        return "\n\n" + plantilla.replace("{telefono}", telefono)
    return (
        f"\n\nSi ninguna opcion te encaja, puedes llamarnos al {telefono}. A veces podemos "
        f"revisar la agenda personalmente y encontrar una alternativa."
    )
