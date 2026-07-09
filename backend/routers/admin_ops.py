"""Endpoints: seccion admin_ops (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import (
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel, Field


import onboarding_utils
from api_models import *  # noqa: F401,F403
from backend import (
    appstate,
    agenda,
    booking,
    clients,
    commerce,
    db,
    demo_agenda,
    rag,
    security,
    settings,
    textnorm,
    timeutils,
)
from backend.main import app


@app.get("/admin/workers", dependencies=[Depends(security._require_admin_token)])
async def admin_workers() -> Dict[str, Any]:
    """Observabilidad de los hilos de fondo (P8): estado vivo/muerto de cada worker
    registrado en el lifespan + uptime del proceso. Solo admin."""
    return {
        "started_at": appstate.STARTED_AT.isoformat(),
        "uptime_seconds": int((timeutils._utc_now() - appstate.STARTED_AT).total_seconds()),
        "reminders_enabled": settings.REMINDER_RUN_INTERVAL_MINUTES > 0,
        "workers": appstate.worker_status(),
    }


@app.post("/admin/reindex/{cliente_id}", dependencies=[Depends(security._require_admin_token)])
async def reindexar(cliente_id: str) -> Dict[str, str]:
    textnorm._assert_valid_client_id(cliente_id)
    clients._get_client_config(cliente_id)

    rag._invalidate_client_runtime(cliente_id)
    rag.cargar_indice(cliente_id)
    return {"status": "ok", "mensaje": f"Indice reindexado para {cliente_id}"}




@app.post("/admin/gen-qa/{cliente_id}", dependencies=[Depends(security._require_admin_token)])
async def admin_gen_qa(cliente_id: str, max_pairs: int = 5) -> Dict[str, Any]:
    """Genera y persiste hasta `max_pairs` preguntas frecuentes para el cliente.

    Flujo:
    1. Parsea la sección P:/R: del info.txt existente.
    2. Si no hay pares, intenta extracción heurística del info.txt (sin OpenAI).
    3. Solo inserta pares nuevos (deduplica por pregunta en minúsculas).
    """
    textnorm._assert_valid_client_id(cliente_id)
    info_txt = rag._read_info_txt(cliente_id)
    source = "none"
    created = 0

    # Paso 1: sección P:/R: estructurada
    created = rag._autocreate_qa_from_info(cliente_id, info_txt, "", max_pairs=max_pairs)
    if created:
        source = "info_pr_format"
    else:
        # Paso 2: heurística libre
        heuristic_pairs = rag._gen_qa_from_info_heuristic(info_txt, max_pairs=max_pairs)
        if heuristic_pairs:
            created = rag._autocreate_qa_from_info(
                cliente_id, "", "", explicit_pairs=heuristic_pairs, max_pairs=max_pairs
            )
            if created:
                source = "info_heuristic"

    with db._get_db_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM kb_qa WHERE cliente_id=?", (cliente_id,)
        ).fetchone()[0]

    return {
        "ok": True,
        "cliente_id": cliente_id,
        "created": created,
        "source": source,
        "total_qa": total,
        "mensaje": f"Se han generado {created} nuevas preguntas frecuentes (fuente: {source}). Total en panel: {total}.",
    }


class AdminRebrainPayload(BaseModel):
    website_url: str = Field(default="", max_length=400)
    nombre_bot: str = Field(default="", max_length=40)
    tono: str = Field(default="Profesional y cercano", min_length=4, max_length=80)
    idioma: str = Field(default="Español", min_length=4, max_length=40)
    max_paginas: int = Field(default=12, ge=1, le=80)


class AdminRebrainResponse(BaseModel):
    status: str
    cliente_id: str
    website_url: str
    detected_business_name: str
    links_found: int
    info_txt_size: int
    reindexed: bool
    reindex_error: str = ""


@app.post(
    "/admin/rebrain/{cliente_id}",
    dependencies=[Depends(security._require_admin_token)],
    response_model=AdminRebrainResponse,
)
async def regenerar_cerebro(cliente_id: str, data: Optional[AdminRebrainPayload] = None) -> AdminRebrainResponse:
    textnorm._assert_valid_client_id(cliente_id)
    cfg = clients._get_client_config(cliente_id)

    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY no esta configurada en el backend.",
        )

    payload = data or AdminRebrainPayload()
    website_url = (payload.website_url or "").strip()
    if not website_url:
        origins = list(cfg.get("allowed_origins", []) or [])
        website_url = next((o for o in origins if o.startswith("http")), "")
    if not website_url:
        raise HTTPException(
            status_code=400,
            detail="No hay website_url configurada para este cliente. Pasa website_url en el body.",
        )

    nombre_bot = (payload.nombre_bot or cfg.get("nombre") or cliente_id).strip() or "Asistente"

    try:
        result = onboarding_utils.run_onboarding(
            website_url=website_url,
            api_key=settings.OPENAI_API_KEY,
            nombre_bot=nombre_bot,
            tono=payload.tono,
            idioma=payload.idioma,
            max_paginas=payload.max_paginas,
        )
    except Exception as exc:
        settings.logger.exception("Error regenerando cerebro de %s", cliente_id)
        raise HTTPException(status_code=502, detail=f"Fallo el scraper: {exc}") from exc

    rag._write_info_txt(cliente_id, result.info_txt)
    # Sembrar Q&A del panel desde las FAQ scrapeadas (run_onboarding las saca del info.txt).
    rag._seed_qa_from_onboarding(cliente_id, result)
    agenda._sync_services_from_info(cliente_id, result.info_txt, deactivate_missing=True)
    commerce._seed_commerce_from_info(cliente_id, result.info_txt)

    reindexed = False
    reindex_error = ""
    try:
        rag._invalidate_client_runtime(cliente_id)
        rag.cargar_indice(cliente_id)
        reindexed = True
    except Exception as exc:
        reindex_error = str(exc)
        settings.logger.warning("No se pudo reindexar tras rebrain de %s: %s", cliente_id, exc)

    return AdminRebrainResponse(
        status="ok",
        cliente_id=cliente_id,
        website_url=result.normalized_url,
        detected_business_name=result.detected_business_name,
        links_found=len(result.links or []),
        info_txt_size=len(result.info_txt or ""),
        reindexed=reindexed,
        reindex_error=reindex_error,
    )


class AdminStatsTopCliente(BaseModel):
    cliente_id: str
    owner_email: str = ""
    plan: str = ""
    messages_used: int = 0
    messages_quota: int = 0


class AdminStatsAlta(BaseModel):
    cliente_id: str
    nombre: str = ""
    owner_email: str = ""
    created_at: str = ""


class AdminStatsChurnRiesgo(BaseModel):
    cliente_id: str
    nombre: str = ""
    owner_email: str = ""
    last_login_at: str = ""
    dias_inactivo: int = 0


class AdminStatsOverview(BaseModel):
    clientes_total: int
    clientes_activos: int
    clientes_demo: int
    clientes_sin_owner: int
    mensajes_mes: int
    mensajes_quota_mes: int
    top_clientes: List[AdminStatsTopCliente]
    altas_recientes: List[AdminStatsAlta]
    churn_riesgo: List[AdminStatsChurnRiesgo]
    generated_at: str


@app.get(
    "/admin/stats/overview",
    dependencies=[Depends(security._require_admin_token)],
    response_model=AdminStatsOverview,
)
async def admin_stats_overview() -> AdminStatsOverview:
    """Compact dashboard summary for the admin Estadísticas view.

    Counts active subscriptions, monthly messages used/quota, top users,
    recent signups (7d) and churn risk (no login in 30d). One query pass.
    """
    now = timeutils._utc_now()
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    with db._get_db_connection() as connection:
        cliente_rows = connection.execute(
            """
            SELECT c.cliente_id AS cliente_id,
                   c.nombre AS cliente_nombre,
                   c.created_at AS cliente_created_at,
                   c.owner_user_id AS owner_user_id,
                   u.email AS owner_email,
                   u.last_login_at AS owner_last_login_at,
                   s.plan AS plan,
                   s.status AS sub_status,
                   s.messages_used_period AS messages_used,
                   s.messages_quota AS messages_quota
            FROM clientes c
            LEFT JOIN users u ON u.id = c.owner_user_id
            LEFT JOIN subscriptions s ON s.user_id = c.owner_user_id
            """
        ).fetchall()

    clientes_total = 0
    clientes_activos = 0
    clientes_demo = 0
    clientes_sin_owner = 0
    mensajes_mes = 0
    mensajes_quota_mes = 0
    top: List[AdminStatsTopCliente] = []
    altas: List[AdminStatsAlta] = []
    churn: List[AdminStatsChurnRiesgo] = []
    demo_registry = demo_agenda._load_demo_registry()

    for row in cliente_rows:
        cliente_id = row["cliente_id"]
        if cliente_id.startswith(demo_agenda.DEMO_TENANT_PREFIX) or cliente_id in demo_registry:
            clientes_demo += 1
            continue
        clientes_total += 1
        sub_status = (row["sub_status"] or "").lower()
        if sub_status in ("active", "trialing"):
            clientes_activos += 1
        if not (row["owner_user_id"] or "").strip():
            clientes_sin_owner += 1
        used = int(row["messages_used"] or 0)
        quota = int(row["messages_quota"] or 0)
        mensajes_mes += used
        mensajes_quota_mes += quota
        if used > 0:
            top.append(
                AdminStatsTopCliente(
                    cliente_id=cliente_id,
                    owner_email=row["owner_email"] or "",
                    plan=row["plan"] or "",
                    messages_used=used,
                    messages_quota=quota,
                )
            )
        created_at = row["cliente_created_at"] or ""
        if created_at and created_at >= seven_days_ago:
            altas.append(
                AdminStatsAlta(
                    cliente_id=cliente_id,
                    nombre=row["cliente_nombre"] or "",
                    owner_email=row["owner_email"] or "",
                    created_at=created_at,
                )
            )
        last_login = row["owner_last_login_at"] or ""
        if (row["owner_user_id"] or "").strip() and last_login and last_login < thirty_days_ago:
            try:
                ll_dt = datetime.fromisoformat(last_login.replace("Z", "+00:00"))
                dias = max(0, (now - ll_dt).days)
            except (TypeError, ValueError):
                dias = 0
            churn.append(
                AdminStatsChurnRiesgo(
                    cliente_id=cliente_id,
                    nombre=row["cliente_nombre"] or "",
                    owner_email=row["owner_email"] or "",
                    last_login_at=last_login,
                    dias_inactivo=dias,
                )
            )

    top.sort(key=lambda x: x.messages_used, reverse=True)
    altas.sort(key=lambda x: x.created_at, reverse=True)
    churn.sort(key=lambda x: x.dias_inactivo, reverse=True)

    return AdminStatsOverview(
        clientes_total=clientes_total,
        clientes_activos=clientes_activos,
        clientes_demo=clientes_demo,
        clientes_sin_owner=clientes_sin_owner,
        mensajes_mes=mensajes_mes,
        mensajes_quota_mes=mensajes_quota_mes,
        top_clientes=top[:10],
        altas_recientes=altas[:20],
        churn_riesgo=churn[:20],
        generated_at=now.isoformat(),
    )


@app.get("/admin/stats", dependencies=[Depends(security._require_admin_token)])
async def estadisticas() -> Dict[str, Any]:
    rag._cleanup_sessions(force=True)
    booking._auto_complete_past_bookings()
    with db._get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT cliente_id, COUNT(*) AS total
            FROM bookings
            GROUP BY cliente_id
            ORDER BY cliente_id
            """
        ).fetchall()
        status_rows = connection.execute(
            """
            SELECT status, COUNT(*) AS total
            FROM bookings
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()

    with appstate.state_lock:
        sesiones_activas = len(appstate.sesiones)
        indices_cargados = sorted(appstate.indices.keys())

    return {
        "version": app.version,
        "clientes_configurados": len(appstate.CONFIG_CLIENTES),
        "sesiones_activas": sesiones_activas,
        "indices_cargados": indices_cargados,
        "bookings_por_cliente": {row["cliente_id"]: row["total"] for row in rows},
        "bookings_por_estado": {row["status"]: row["total"] for row in status_rows},
    }


@app.get("/admin/analytics", dependencies=[Depends(security._require_admin_token)])
async def admin_analytics(days: int = 30, limit: int = 80) -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    limit = max(1, min(int(limit or 80), 300))
    since = timeutils._utc_now() - timedelta(days=days)
    since_iso = since.isoformat().replace("+00:00", "Z")

    with db._get_db_connection() as connection:
        total = int(
            connection.execute(
                "SELECT COUNT(*) FROM analytics_events WHERE created_at >= ?",
                (since_iso,),
            ).fetchone()[0]
        )
        by_event = connection.execute(
            """
            SELECT event_name, COUNT(*) AS total
            FROM analytics_events
            WHERE created_at >= ?
            GROUP BY event_name
            ORDER BY total DESC, event_name ASC
            """,
            (since_iso,),
        ).fetchall()
        by_client = connection.execute(
            """
            SELECT COALESCE(NULLIF(cliente_id, ''), 'sin_cliente') AS cliente_id, COUNT(*) AS total
            FROM analytics_events
            WHERE created_at >= ?
            GROUP BY COALESCE(NULLIF(cliente_id, ''), 'sin_cliente')
            ORDER BY total DESC, cliente_id ASC
            """,
            (since_iso,),
        ).fetchall()
        daily = connection.execute(
            """
            SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS total
            FROM analytics_events
            WHERE created_at >= ?
            GROUP BY substr(created_at, 1, 10)
            ORDER BY day ASC
            """,
            (since_iso,),
        ).fetchall()
        recent_rows = connection.execute(
            """
            SELECT id, event_name, event_source, cliente_id, session_id, page_path, page_url,
                   metadata_json, created_at
            FROM analytics_events
            WHERE created_at >= ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (since_iso, limit),
        ).fetchall()

    key_events = {row["event_name"]: int(row["total"]) for row in by_event}
    recent = []
    for row in recent_rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        recent.append(
            {
                "id": row["id"],
                "event_name": row["event_name"],
                "event_source": row["event_source"],
                "cliente_id": row["cliente_id"],
                "session_id": row["session_id"],
                "page_path": row["page_path"],
                "page_url": row["page_url"],
                "metadata": metadata,
                "created_at": row["created_at"],
            }
        )

    return {
        "days": days,
        "since": since_iso,
        "total_events": total,
        "kpis": {
            "landing_view": key_events.get("landing_view", 0),
            "signup_clicked": key_events.get("signup_clicked", 0),
            "signup_completed": key_events.get("signup_completed", 0),
            "bot_created": key_events.get("bot_created", 0),
            "first_chat_tested": key_events.get("first_chat_tested", 0),
            "pricing_viewed": key_events.get("pricing_viewed", 0),
            "upgrade_clicked": key_events.get("upgrade_clicked", 0),
            "demo_submits": key_events.get("demo_submit", 0),
            "demo_generated": key_events.get("demo_generated", 0),
            "checkout_started": key_events.get("checkout_started", 0),
            "checkout_redirect": key_events.get("checkout_redirect", 0),
            "checkout_completed": key_events.get("checkout_completed", 0),
            "lead_created": key_events.get("lead_created", 0),
            "widget_messages": key_events.get("widget_message_sent", 0),
            "booking_submitted": key_events.get("booking_submitted", 0),
            "booking_confirmed": key_events.get("booking_confirmed", 0),
            "consultation_clicks": key_events.get("consultation_cta_click", 0),
        },
        "events_by_name": [{"event_name": row["event_name"], "total": row["total"]} for row in by_event],
        "events_by_client": [{"cliente_id": row["cliente_id"], "total": row["total"]} for row in by_client],
        "daily": [{"day": row["day"], "total": row["total"]} for row in daily],
        "recent": recent,
    }


@app.get("/admin/self-service-funnel", dependencies=[Depends(security._require_admin_token)])
async def admin_self_service_funnel(days: int = 30) -> Dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    since = timeutils._utc_now() - timedelta(days=days)
    since_iso = since.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"

    def pct(part: int, total: int) -> int:
        return int(round((part / total) * 100)) if total else 0

    with db._get_db_connection() as connection:
        events = connection.execute(
            """
            SELECT event_name, event_source, cliente_id, session_id, page_path,
                   page_url, metadata_json, created_at
            FROM analytics_events
            WHERE created_at >= ?
            ORDER BY id DESC
            """,
            (since_iso,),
        ).fetchall()
        signups = int(
            connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'client' AND created_at >= ?",
                (since_iso,),
            ).fetchone()[0]
        )
        bots_created = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM clientes
                WHERE owner_user_id <> '' AND created_at >= ?
                """,
                (since_iso,),
            ).fetchone()[0]
        )
        activated_by_chat = int(
            connection.execute(
                """
                SELECT COUNT(DISTINCT c.cliente_id)
                FROM clientes c
                JOIN chat_messages m ON m.cliente_id = c.cliente_id
                WHERE c.owner_user_id <> ''
                  AND m.role IN ('assistant', 'bot')
                  AND m.created_at >= ?
                """,
                (since_iso,),
            ).fetchone()[0]
        )
        paid_subscriptions = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM subscriptions
                WHERE plan <> 'free'
                  AND status IN ('active', 'trialing')
                  AND (created_at >= ? OR updated_at >= ?)
                """,
                (since_iso, since_iso),
            ).fetchone()[0]
        )
        sources = connection.execute(
            """
            SELECT COALESCE(NULLIF(signup_source, ''), 'unknown') AS source, COUNT(*) AS total
            FROM users
            WHERE role = 'client' AND created_at >= ?
            GROUP BY COALESCE(NULLIF(signup_source, ''), 'unknown')
            ORDER BY total DESC, source ASC
            LIMIT 8
            """,
            (since_iso,),
        ).fetchall()
        bot_sources = connection.execute(
            """
            SELECT COALESCE(NULLIF(source, ''), 'unknown') AS source, COUNT(*) AS total
            FROM clientes
            WHERE owner_user_id <> '' AND created_at >= ?
            GROUP BY COALESCE(NULLIF(source, ''), 'unknown')
            ORDER BY total DESC, source ASC
            LIMIT 8
            """,
            (since_iso,),
        ).fetchall()
        recent_signups = connection.execute(
            """
            SELECT u.email, u.display_name, u.signup_source, u.cliente_id, u.created_at,
                   c.nombre AS bot_name, c.website_url
            FROM users u
            LEFT JOIN clientes c ON c.cliente_id = u.cliente_id
            WHERE u.role = 'client' AND u.created_at >= ?
            ORDER BY u.created_at DESC
            LIMIT 8
            """,
            (since_iso,),
        ).fetchall()
        recent_bots = connection.execute(
            """
            SELECT c.cliente_id, c.nombre, c.website_url, c.plan, c.source, c.created_at,
                   u.email AS owner_email
            FROM clientes c
            LEFT JOIN users u ON u.id = c.owner_user_id
            WHERE c.owner_user_id <> '' AND c.created_at >= ?
            ORDER BY c.created_at DESC
            LIMIT 8
            """,
            (since_iso,),
        ).fetchall()

    event_counts: Dict[str, int] = {}
    site_visit_keys = set()
    cta_clicks = 0
    registered_clicks = 0
    snippet_copied = 0
    preview_messages = 0
    preview_client_ids = set()
    upgrades_started = 0
    checkout_completed_events = 0
    campaign_clicks: Dict[str, int] = {}
    for row in events:
        name = row["event_name"]
        event_counts[name] = event_counts.get(name, 0) + 1
        if row["event_source"] == "vantelia_site" or name in {"landing_view", "pricing_viewed"}:
            visit_key = row["session_id"] or row["page_url"] or row["page_path"] or str(row["created_at"])
            site_visit_keys.add(visit_key)
        try:
            meta = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        cta_href = str(meta.get("cta_href") or row["page_url"] or "")
        source = str(meta.get("utm_source") or meta.get("source") or row["event_source"] or "direct")
        if name in {"signup_clicked", "plan_signup_clicked", "plan_cta_click", "portal_access_click", "create_bot_cta_click", "free_bot_cta_click"}:
            cta_clicks += 1
            campaign_clicks[source] = campaign_clicks.get(source, 0) + 1
            if "/acceso" in cta_href or "app.vantelia.es" in cta_href:
                registered_clicks += 1
        if name in {"signup_completed", "selfserve_signup"}:
            signups = max(signups, event_counts[name])
        if name in {"first_chat_tested", "bot_preview_message"}:
            preview_messages += 1
            if row["cliente_id"]:
                preview_client_ids.add(row["cliente_id"])
        if name == "snippet_copied":
            snippet_copied += 1
        if name in {"upgrade_clicked", "upgrade_started", "checkout_started", "checkout_redirect"}:
            upgrades_started += 1
        if name == "checkout_completed":
            checkout_completed_events += 1

    upgrades_started = max(
        event_counts.get("upgrade_clicked", 0),
        event_counts.get("upgrade_started", 0),
        event_counts.get("checkout_started", 0),
        event_counts.get("checkout_redirect", 0),
    )
    website_visits = len(site_visit_keys) or sum(
        total for event, total in event_counts.items() if event in {"landing_view", "page_view", "site_page_view"}
    )
    free_bot_clicks = registered_clicks or cta_clicks
    activated_bots = max(activated_by_chat, len(preview_client_ids))
    upgrades_completed = max(paid_subscriptions, checkout_completed_events)
    funnel = [
        {"key": "visits", "label": "Visitas web", "value": website_visits},
        {"key": "cta_clicks", "label": "Clicks Crea tu bot gratis", "value": free_bot_clicks},
        {"key": "signups", "label": "Registros", "value": signups},
        {"key": "bots_created", "label": "Bots creados", "value": bots_created},
        {"key": "activated", "label": "Primer chat probado", "value": activated_bots},
        {"key": "snippet_copied", "label": "Snippet copiado", "value": snippet_copied},
        {"key": "upgrades_started", "label": "Upgrade iniciado", "value": upgrades_started},
        {"key": "upgrades_completed", "label": "Pago completado", "value": upgrades_completed},
    ]
    for idx, step in enumerate(funnel):
        previous = funnel[idx - 1]["value"] if idx else step["value"]
        step["conversion_from_previous_pct"] = pct(int(step["value"]), int(previous))
        step["conversion_from_visit_pct"] = pct(int(step["value"]), website_visits)

    actions: List[Dict[str, str]] = []
    if website_visits and free_bot_clicks < max(1, int(website_visits * 0.08)):
        actions.append({
            "title": "Subir clicks al registro",
            "detail": "Revisa CTAs visibles y repite 'Crea tu bot gratis en 2 minutos' en las paginas con mas trafico.",
        })
    if signups and bots_created < signups:
        actions.append({
            "title": "Recuperar registros sin bot",
            "detail": "Envia un email corto llevando al wizard: pega tu URL y termina el bot gratis.",
        })
    if bots_created and activated_bots < bots_created:
        actions.append({
            "title": "Empujar la primera prueba",
            "detail": "Prioriza onboarding y emails que pidan probar una pregunta real del negocio.",
        })
    if activated_bots and snippet_copied < activated_bots:
        actions.append({
            "title": "Acelerar instalacion",
            "detail": "Haz mas visible el boton de copiar codigo y ofrece guia rapida por CMS.",
        })
    if snippet_copied and upgrades_completed == 0:
        actions.append({
            "title": "Convertir activacion en pago",
            "detail": "Muestra limites del plan gratis y CTA de upgrade justo despues de instalar.",
        })
    if not actions:
        actions.append({
            "title": "Escalar lo que ya funciona",
            "detail": "Duplica las campanas que traen registros y mejora el paso con peor conversion.",
        })

    campaign_rows = [
        {"source": source, "clicks": total}
        for source, total in sorted(campaign_clicks.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]

    return {
        "days": days,
        "since": since_iso,
        "funnel": funnel,
        "kpis": {
            "website_visits": website_visits,
            "free_bot_clicks": free_bot_clicks,
            "signups": signups,
            "bots_created": bots_created,
            "activated_bots": activated_bots,
            "snippet_copied": snippet_copied,
            "upgrades_started": upgrades_started,
            "upgrades_completed": upgrades_completed,
            "visit_to_signup_pct": pct(signups, website_visits),
            "signup_to_bot_pct": pct(bots_created, signups),
            "bot_to_activation_pct": pct(activated_bots, bots_created),
            "activation_to_install_pct": pct(snippet_copied, activated_bots),
            "install_to_paid_pct": pct(upgrades_completed, snippet_copied),
        },
        "sources": [{"source": row["source"], "total": row["total"]} for row in sources],
        "bot_sources": [{"source": row["source"], "total": row["total"]} for row in bot_sources],
        "campaigns": campaign_rows,
        "recent_signups": [dict(row) for row in recent_signups],
        "recent_bots": [dict(row) for row in recent_bots],
        "actions": actions,
        "tracking": {
            "landing_view": event_counts.get("landing_view", 0) > 0,
            "signup_clicked": event_counts.get("signup_clicked", 0) > 0 or cta_clicks > 0,
            "signup_completed": event_counts.get("signup_completed", 0) > 0 or signups > 0,
            "bot_created": event_counts.get("bot_created", 0) > 0 or bots_created > 0,
            "first_chat_tested": event_counts.get("first_chat_tested", 0) > 0 or preview_messages > 0,
            "pricing_viewed": event_counts.get("pricing_viewed", 0) > 0,
            "upgrade_clicked": event_counts.get("upgrade_clicked", 0) > 0 or upgrades_started > 0,
            "checkout_started": event_counts.get("checkout_started", 0) > 0,
            "checkout_completed": event_counts.get("checkout_completed", 0) > 0 or upgrades_completed > 0,
            "snippet_copied": snippet_copied > 0,
            "preview_messages": preview_messages > 0,
            "upgrade_started": upgrades_started > 0,
        },
    }


# =====================================================================
# === PLAN DE ESCALA ==================================================
# Centro diario de actividad, pipeline y revision comercial.
# =====================================================================























