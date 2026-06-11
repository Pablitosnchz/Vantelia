"""Endpoints: seccion admin_outreach (refactor F3).

Decoran directamente la app de backend.main para preservar el orden de
registro de rutas identico al monolito original.
"""
from __future__ import annotations

import asyncio
import copy
import base64
import csv
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import shutil
import sqlite3
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import httpx
from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

import onboarding_utils
from api_models import *  # noqa: F401,F403
from backend import (
    agenda,
    appstate,
    billing,
    booking,
    chat,
    clients,
    crm,
    db,
    demo_agenda,
    emailing,
    growth,
    instagram,
    messaging,
    onboarding,
    outreach,
    portal,
    rag,
    security,
    settings,
    stripe_gateway,
    textnorm,
    tiktok,
    timeutils,
    voice,
    wa_capture,
    whatsapp,
)
from backend.outreach import (  # noqa: F401
    OutreachProspect, outreach_build_message, outreach_demo_url_with_utm,
    outreach_fetch_candidates, outreach_render, outreach_smtp_settings,
)
from backend.main import app

@app.get("/admin/outreach/stats", dependencies=[Depends(security._require_admin_token)])
def outreach_stats():
    with outreach._outreach_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM prospects").fetchone()["c"]
        suppressed = conn.execute("SELECT COUNT(*) AS c FROM suppressions").fetchone()["c"]
        per_stage_rows = conn.execute(
            "SELECT stage, COUNT(*) AS c FROM sends WHERE mode='send' GROUP BY stage"
        ).fetchall()
        per_stage = {row["stage"]: int(row["c"]) for row in per_stage_rows}

        opens = conn.execute("SELECT COUNT(*) AS c FROM events WHERE type='open'").fetchone()["c"]
        clicks = conn.execute("SELECT COUNT(*) AS c FROM events WHERE type='click'").fetchone()["c"]
        unique_clicks = conn.execute(
            "SELECT COUNT(DISTINCT email) AS c FROM events WHERE type='click'"
        ).fetchone()["c"]
        vantelia_clicks = conn.execute(
            """SELECT COUNT(*) AS c FROM events
               WHERE type='click' AND (
                 lower(coalesce(url,'')) LIKE 'https://www.vantelia.es%'
                 OR lower(coalesce(url,'')) LIKE 'https://vantelia.es%'
               )"""
        ).fetchone()["c"]
        reply_intents = conn.execute("SELECT COUNT(*) AS c FROM events WHERE type='reply_intent'").fetchone()["c"]
        replies = conn.execute("SELECT COUNT(*) AS c FROM events WHERE type='reply'").fetchone()["c"]
        unique_opens = conn.execute(
            "SELECT COUNT(DISTINCT email) AS c FROM events WHERE type='open'"
        ).fetchone()["c"]
        unique_vantelia_clicks = conn.execute(
            """SELECT COUNT(DISTINCT email) AS c FROM events
               WHERE type='click' AND (
                 lower(coalesce(url,'')) LIKE 'https://www.vantelia.es%'
                 OR lower(coalesce(url,'')) LIKE 'https://vantelia.es%'
               )"""
        ).fetchone()["c"]
        unique_reply_intents = conn.execute(
            "SELECT COUNT(DISTINCT email) AS c FROM events WHERE type='reply_intent'"
        ).fetchone()["c"]
        unique_replies = conn.execute(
            "SELECT COUNT(DISTINCT email) AS c FROM events WHERE type='reply'"
        ).fetchone()["c"]

        sent_real = conn.execute(
            "SELECT COUNT(*) AS c FROM sends WHERE mode='send'"
        ).fetchone()["c"]
        sent_distinct = conn.execute(
            "SELECT COUNT(DISTINCT email) AS c FROM sends WHERE mode='send'"
        ).fetchone()["c"]

        today = timeutils._utc_now().date().isoformat()
        sent_today = conn.execute(
            "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]

        week_cutoff = (timeutils._utc_now() - timedelta(days=7)).isoformat(timespec="seconds")
        month_cutoff = (timeutils._utc_now() - timedelta(days=30)).isoformat(timespec="seconds")
        sent_week = conn.execute(
            "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND sent_at>=?",
            (week_cutoff,),
        ).fetchone()["c"]
        sent_month = conn.execute(
            "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND sent_at>=?",
            (month_cutoff,),
        ).fetchone()["c"]

        # serie diaria 30d
        daily_sends = conn.execute(
            """SELECT substr(sent_at,1,10) AS day, COUNT(*) AS c FROM sends
               WHERE mode='send' AND sent_at>=? GROUP BY day ORDER BY day""",
            (month_cutoff,),
        ).fetchall()
        daily_opens = conn.execute(
            """SELECT substr(ts,1,10) AS day, COUNT(*) AS c FROM events
               WHERE type='open' AND ts>=? GROUP BY day ORDER BY day""",
            (month_cutoff,),
        ).fetchall()
        daily_replies = conn.execute(
            """SELECT substr(ts,1,10) AS day, COUNT(*) AS c FROM events
               WHERE type='reply' AND ts>=? GROUP BY day ORDER BY day""",
            (month_cutoff,),
        ).fetchall()

        vantelia_click_rows = conn.execute(
            """SELECT e.email, p.business_name, p.niche, p.city,
                      COUNT(*) AS clicks, MAX(e.ts) AS last_clicked_at,
                      (SELECT e2.url FROM events e2
                         WHERE e2.email=e.email AND e2.type='click'
                           AND (lower(coalesce(e2.url,'')) LIKE 'https://www.vantelia.es%'
                                OR lower(coalesce(e2.url,'')) LIKE 'https://vantelia.es%')
                         ORDER BY e2.ts DESC LIMIT 1) AS last_url
               FROM events e
               LEFT JOIN prospects p ON p.email=e.email
               WHERE e.type='click' AND (
                 lower(coalesce(e.url,'')) LIKE 'https://www.vantelia.es%'
                 OR lower(coalesce(e.url,'')) LIKE 'https://vantelia.es%'
               )
               GROUP BY e.email
               ORDER BY last_clicked_at DESC
               LIMIT 20"""
        ).fetchall()

        # top niches por reply rate
        top_niches_rows = conn.execute(
            """SELECT p.niche AS niche, COUNT(DISTINCT p.email) AS prospects,
                      SUM(CASE WHEN EXISTS(SELECT 1 FROM events e WHERE e.email=p.email AND e.type='reply') THEN 1 ELSE 0 END) AS replies
               FROM prospects p WHERE p.niche<>'' GROUP BY p.niche ORDER BY replies DESC LIMIT 5"""
        ).fetchall()

        funnel = {
            stage: per_stage.get(stage, 0) for stage in outreach.OUTREACH_STAGES
        }

        sample_prospect = OutreachProspect(
            email="test@clinicadental.es",
            business_name="Clinica Dental Madrid",
            niche="clinica dental",
            city="Madrid",
            website="https://clinicadental.es",
        )
        primary_cta_url = outreach_demo_url_with_utm("cold", sample_prospect)
        parsed_cta = urlparse(primary_cta_url)
        parsed_tracking = urlparse(outreach.OUTREACH_TRACKING_BASE_URL)
        cta_path = (parsed_cta.path or "").lower()
        cta_destination = "demo" if parsed_cta.hostname in {"vantelia.es", "www.vantelia.es"} and cta_path.startswith("/demo") else "signup" if parsed_cta.hostname == "app.vantelia.es" and cta_path.startswith("/acceso") else "other"
        tracking_active = bool(outreach.OUTREACH_AVAILABLE and outreach.OUTREACH_TRACKING_SECRET and outreach.OUTREACH_TRACKING_BASE_URL and not outreach.OUTREACH_TRACKING_DISABLED)
        primary_cta_tracked = bool(tracking_active and not primary_cta_url.startswith(f"{outreach.OUTREACH_TRACKING_BASE_URL}/track/"))
        health_alerts = []
        if cta_destination != "demo":
            health_alerts.append({
                "level": "danger",
                "code": "cta_not_demo",
                "message": "El CTA principal de outreach no apunta a /demo/. Puede estar llevando prospects al registro antes de ver valor.",
            })
        if not tracking_active:
            health_alerts.append({
                "level": "warning",
                "code": "tracking_off",
                "message": "El tracking de aperturas/clicks no esta activo.",
            })
        elif not primary_cta_tracked:
            health_alerts.append({
                "level": "warning",
                "code": "cta_untracked",
                "message": "El CTA principal no se envolveria con tracking de click.",
            })

    open_rate = (unique_opens / sent_distinct * 100) if sent_distinct else 0.0
    reply_intent_rate = (unique_reply_intents / sent_distinct * 100) if sent_distinct else 0.0
    reply_rate = (unique_replies / sent_distinct * 100) if sent_distinct else 0.0
    click_rate = (unique_clicks / sent_distinct * 100) if sent_distinct else 0.0
    open_to_click_rate = (unique_clicks / unique_opens * 100) if unique_opens else 0.0

    return {
        "totals": {
            "prospects": total,
            "suppressed": suppressed,
            "sent_total": sent_real,
            "sent_distinct": sent_distinct,
            "sent_today": sent_today,
            "sent_week": sent_week,
            "sent_month": sent_month,
            "opens_total": opens,
            "opens_unique": unique_opens,
            "clicks_total": clicks,
            "clicks_unique": unique_clicks,
            "vantelia_clicks_total": vantelia_clicks,
            "vantelia_clicks_unique": unique_vantelia_clicks,
            "reply_intents_total": reply_intents,
            "reply_intents_unique": unique_reply_intents,
            "replies_total": replies,
            "replies_unique": unique_replies,
            "open_rate_pct": round(open_rate, 1),
            "click_rate_pct": round(click_rate, 1),
            "open_to_click_rate_pct": round(open_to_click_rate, 1),
            "reply_intent_rate_pct": round(reply_intent_rate, 1),
            "reply_rate_pct": round(reply_rate, 1),
        },
        "tracking": {
            "active": tracking_active,
            "base_url": outreach.OUTREACH_TRACKING_BASE_URL,
        },
        "primary_cta": {
            "url": primary_cta_url,
            "host": parsed_cta.hostname or "",
            "destination": cta_destination,
            "tracking_host": parsed_tracking.hostname or "",
            "tracked": primary_cta_tracked,
        },
        "health_alerts": health_alerts,
        "funnel": funnel,
        "daily": {
            "sends": [{"day": r["day"], "c": r["c"]} for r in daily_sends],
            "opens": [{"day": r["day"], "c": r["c"]} for r in daily_opens],
            "replies": [{"day": r["day"], "c": r["c"]} for r in daily_replies],
        },
        "top_niches": [
            {"niche": r["niche"], "prospects": r["prospects"], "replies": r["replies"]}
            for r in top_niches_rows
        ],
        "vantelia_clickers": [
            {
                "email": r["email"],
                "business_name": r["business_name"] or "",
                "niche": r["niche"] or "",
                "city": r["city"] or "",
                "clicks": r["clicks"],
                "last_clicked_at": r["last_clicked_at"],
                "last_url": r["last_url"] or "",
            }
            for r in vantelia_click_rows
        ],
    }


# ----- Hot leads (Fase 1) -----

@app.get("/admin/outreach/hot-leads", dependencies=[Depends(security._require_admin_token)])
def outreach_hot_leads(limit: int = 15, days: int = 14):
    """Devuelve prospects calientes ordenados por engagement reciente.

    Score compuesto: clicks*5 + opens*1 + bonus por actividad reciente.
    Excluye prospects con respuesta detectada (ya en pipeline) y bajas.
    """
    limit = max(1, min(100, int(limit or 15)))
    days = max(1, min(60, int(days or 14)))
    cutoff = (timeutils._utc_now() - timedelta(days=days)).isoformat(timespec="seconds")

    with outreach._outreach_db() as conn:
        rows = conn.execute(
            """
            SELECT p.email, p.business_name, p.contact_name, p.niche, p.city, p.phone,
                   p.website, COALESCE(p.status, 'new') AS status,
                   (SELECT stage FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_stage,
                   (SELECT sent_at FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_sent_at,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open'  AND e.ts>=?) AS opens_recent,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click' AND e.ts>=?) AS clicks_recent,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='demo_generated' AND e.ts>=?) AS demos_recent,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open')  AS opens_total,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks_total,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='demo_generated') AS demos_total,
                   (SELECT MAX(ts) FROM events e WHERE e.email=p.email AND e.type IN ('open','click','demo_generated')) AS last_event_at
            FROM prospects p
            WHERE NOT EXISTS (SELECT 1 FROM events ev WHERE ev.email=p.email AND ev.type='reply')
              AND COALESCE(p.status,'') NOT IN ('replied','client','lost')
              AND NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.email=p.email)
            """,
            (cutoff, cutoff, cutoff),
        ).fetchall()

    items = []
    for r in rows:
        opens_recent = int(r["opens_recent"] or 0)
        clicks_recent = int(r["clicks_recent"] or 0)
        demos_recent = int(r["demos_recent"] or 0)
        opens_total = int(r["opens_total"] or 0)
        clicks_total = int(r["clicks_total"] or 0)
        demos_total = int(r["demos_total"] or 0)
        if opens_recent + clicks_recent + demos_recent + opens_total + clicks_total + demos_total == 0:
            continue
        score = demos_recent * 12 + clicks_recent * 6 + opens_recent * 2 + demos_total * 6 + clicks_total * 3 + opens_total
        items.append({
            "email": r["email"],
            "business_name": r["business_name"],
            "contact_name": r["contact_name"] or "",
            "niche": r["niche"] or "",
            "city": r["city"] or "",
            "phone": r["phone"] or "",
            "website": r["website"] or "",
            "status": r["status"],
            "last_stage": r["last_stage"] or "",
            "last_sent_at": r["last_sent_at"] or "",
            "last_event_at": r["last_event_at"] or "",
            "opens_recent": opens_recent,
            "clicks_recent": clicks_recent,
            "demos_recent": demos_recent,
            "opens_total": opens_total,
            "clicks_total": clicks_total,
            "demos_total": demos_total,
            "score": score,
        })

    items.sort(key=lambda x: (x["score"], x["last_event_at"]), reverse=True)
    return {"window_days": days, "items": items[:limit]}




























@app.get("/admin/outreach/followup-queue", dependencies=[Depends(security._require_admin_token)])
def outreach_followup_queue(limit: int = 80, days: int = 45):
    limit = max(1, min(200, int(limit or 80)))
    days = max(1, min(365, int(days or 45)))
    cutoff = (timeutils._utc_now() - timedelta(days=days)).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        followup_days = outreach._outreach_config_followup_days(conn)
        rows = conn.execute(
            """
            SELECT p.email, p.business_name, p.contact_name, p.niche, p.service_hint, p.city,
                   p.phone, p.website, p.tags, p.source, COALESCE(p.status,'new') AS status,
                   (SELECT MAX(s.sent_at) FROM sends s WHERE s.email=p.email AND s.mode='send') AS last_sent_at,
                   (SELECT MAX(e.ts) FROM events e WHERE e.email=p.email) AS last_event_at,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open') AS opens,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='demo_generated') AS demos,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply_intent') AS reply_intents,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply') AS replies,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send') AS total_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu1') AS fu1_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu2') AS fu2_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='breakup') AS breakup_sent
            FROM prospects p
            WHERE NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.email=p.email)
              AND COALESCE(p.status,'') NOT IN ('client','lost')
              AND EXISTS (
                  SELECT 1 FROM sends s
                  WHERE s.email=p.email AND s.mode='send' AND s.sent_at>=?
              )
            ORDER BY COALESCE(last_event_at,last_sent_at,'') DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()

    items = [outreach._outreach_followup_item(row, followup_days) for row in rows]
    items.sort(
        key=lambda item: (
            -int(item["priority"]),
            item["signals"]["demos"],
            item["signals"]["reply_intents"],
            item["signals"]["clicks"],
            item["signals"]["opens"],
            item["last_event_at"] or item["last_sent_at"],
        ),
        reverse=True,
    )
    buckets = {
        "priority_1": [item for item in items if item["priority"] == 1],
        "priority_2": [item for item in items if item["priority"] == 2],
        "priority_3": [item for item in items if item["priority"] == 3],
    }
    return {
        "window_days": days,
        "followup_days": followup_days,
        "total": len(items),
        "counts": {key: len(value) for key, value in buckets.items()},
        "items": items,
        "buckets": buckets,
    }




@app.get("/admin/outreach/autopilot", dependencies=[Depends(security._require_admin_token)])
def outreach_autopilot_status(limit: int = 120, days: int = 60):
    queue = outreach_followup_queue(limit=limit, days=days)
    return outreach._outreach_autopilot_summary(queue)


@app.get("/admin/outreach/autopilot/next-action", dependencies=[Depends(security._require_admin_token)])
def outreach_autopilot_next_action():
    """Devuelve el único mejor prospect+stage para el botón 'Enviar ahora' del panel."""
    with outreach._outreach_db() as conn:
        stage_days = outreach._outreach_followup_stage_days(outreach._outreach_config_followup_days(conn))
        for stage, after_days in stage_days:
            cutoff = (timeutils._utc_now() - timedelta(days=after_days)).isoformat(timespec="seconds")
            prev_stage = outreach.OUTREACH_STAGES[outreach.OUTREACH_STAGES.index(stage) - 1]
            row = conn.execute(
                """
                SELECT p.email, p.business_name, p.contact_name, p.niche, p.city,
                       p.phone, p.website, p.service_hint,
                       COALESCE(p.status,'new') AS status,
                       COALESCE(p.score,0) AS score,
                       (SELECT MAX(s.sent_at) FROM sends s WHERE s.email=p.email AND s.mode='send') AS last_sent_at,
                       (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open') AS opens,
                       (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks,
                       (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply') AS replies
                FROM prospects p
                WHERE EXISTS (
                    SELECT 1 FROM sends s WHERE s.email=p.email AND s.stage=? AND s.sent_at<=? AND s.mode='send'
                )
                AND NOT EXISTS (
                    SELECT 1 FROM sends s2 WHERE s2.email=p.email AND s2.stage=? AND s2.mode='send'
                )
                AND NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.email=p.email)
                AND NOT EXISTS (SELECT 1 FROM events ev WHERE ev.email=p.email AND ev.type='reply')
                AND COALESCE(p.status,'') NOT IN ('replied','client','lost')
                ORDER BY
                    (COALESCE(p.score,0)
                     + (SELECT COUNT(*)*6 FROM events e WHERE e.email=p.email AND e.type='click')
                     + (SELECT COUNT(*)*2 FROM events e WHERE e.email=p.email AND e.type='open')
                    ) DESC
                LIMIT 1
                """,
                (prev_stage, cutoff, stage),
            ).fetchone()
            if row:
                return {
                    "found": True,
                    "stage": stage,
                    "after_days": after_days,
                    "email": row["email"],
                    "business_name": row["business_name"],
                    "contact_name": row["contact_name"],
                    "niche": row["niche"],
                    "city": row["city"],
                    "last_sent_at": row["last_sent_at"],
                    "opens": int(row["opens"] or 0),
                    "clicks": int(row["clicks"] or 0),
                    "score": int(row["score"] or 0),
                }
    return {"found": False}


@app.post("/admin/outreach/autopilot/run", dependencies=[Depends(security._require_admin_token)])
def outreach_autopilot_run(payload: OutreachAutopilotSendPayload):
    """Lanza un job real de follow-ups automáticos (fu1/fu2/breakup) hasta payload.max envíos."""
    max_send = max(1, min(50, int(payload.max or 10)))
    params = {
        "max": max_send,
        "send": bool(payload.send),
        "delay": float(payload.delay),
        "jitter": float(payload.jitter),
    }
    updated_engaged = 0
    with outreach._outreach_db() as conn:
        followup_days = outreach._outreach_config_followup_days(conn)
        params["followup_days"] = followup_days
        if payload.apply_status:
            cutoff = (timeutils._utc_now() - timedelta(days=max(1, int(payload.days or 60)))).isoformat(timespec="seconds")
            cur = conn.execute(
                """UPDATE prospects SET status='engaged', updated_at=?
                   WHERE status IN ('new','contacted')
                   AND EXISTS (
                       SELECT 1 FROM events e
                       WHERE e.email=prospects.email
                         AND e.type IN ('open','click','demo_generated','reply_intent')
                         AND e.ts >= ?
                   )""",
                (outreach._outreach_now(), cutoff),
            )
            updated_engaged = cur.rowcount
            conn.commit()
        cur = conn.execute(
            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
            ("autopilot", "queued", json.dumps(params), "", outreach._outreach_now()),
        )
        job_id = cur.lastrowid
        conn.commit()
    threading.Thread(target=outreach._outreach_run_autopilot_job, args=(job_id, params), daemon=True).start()
    return {"ok": True, "job_id": job_id, "max": max_send, "send": bool(payload.send), "updated_engaged": updated_engaged, "followup_days": followup_days}


class AutopilotConfigPayload(BaseModel):
    enabled: Optional[bool] = None
    targets: Optional[List[Dict[str, str]]] = None
    target_companies: Optional[int] = None
    daily_new_target: Optional[int] = None
    daily_cold_cap: Optional[int] = None
    auto_followups: Optional[bool] = None
    followup_days: Optional[Dict[str, int]] = None
    discovery_enabled: Optional[bool] = None




@app.get("/admin/outreach/autopilot-config", dependencies=[Depends(security._require_admin_token)])
def outreach_autopilot_config_get():
    with outreach._outreach_db() as conn:
        return outreach._autopilot_config_row(conn)


@app.put("/admin/outreach/autopilot-config", dependencies=[Depends(security._require_admin_token)])
def outreach_autopilot_config_put(payload: AutopilotConfigPayload):
    fields = []
    params: List[Any] = []
    prev_enabled = None
    with outreach._outreach_db() as conn:
        row = conn.execute("SELECT enabled FROM autopilot_config WHERE id=1").fetchone()
        prev_enabled = bool(row["enabled"]) if row else False
    if payload.enabled is not None:
        fields.append("enabled=?"); params.append(1 if payload.enabled else 0)
    if payload.targets is not None:
        clean_targets = []
        for t in payload.targets:
            s = (t.get("sector") or "").strip()
            c = (t.get("city") or "").strip()
            if s and c:
                clean_targets.append({"sector": s, "city": c})
        fields.append("targets_json=?"); params.append(json.dumps(clean_targets, ensure_ascii=False))
    if payload.target_companies is not None:
        target_companies = outreach._autopilot_target_companies(payload.target_companies)
        fields.append("daily_new_target=?"); params.append(target_companies)
        fields.append("daily_cold_cap=?"); params.append(target_companies)
    if payload.daily_new_target is not None and payload.target_companies is None:
        fields.append("daily_new_target=?"); params.append(max(1, min(200, int(payload.daily_new_target))))
    if payload.daily_cold_cap is not None and payload.target_companies is None:
        fields.append("daily_cold_cap=?"); params.append(max(1, min(200, int(payload.daily_cold_cap))))
    if payload.auto_followups is not None:
        fields.append("auto_followups=?"); params.append(1 if payload.auto_followups else 0)
    if payload.discovery_enabled is not None:
        fields.append("discovery_enabled=?"); params.append(1 if payload.discovery_enabled else 0)
    if payload.followup_days is not None:
        followup_days = outreach._outreach_normalize_followup_days(payload.followup_days)
        fields.append("followup_days_json=?"); params.append(json.dumps(followup_days, ensure_ascii=False))
    fields.append("updated_at=?"); params.append(outreach._outreach_now())
    with outreach._outreach_db() as conn:
        outreach._outreach_ensure_autopilot_config_columns(conn)
        conn.execute(f"UPDATE autopilot_config SET {', '.join(fields)} WHERE id=1", params)
        conn.commit()
        result = outreach._autopilot_config_row(conn)

    # Loggear cambios significativos.
    if payload.enabled is not None and payload.enabled != prev_enabled:
        if payload.enabled:
            outreach._autopilot_log("info", "enabled_via_panel",
                           "Modo automático activado desde el panel",
                           {"blockers": result.get("blockers", [])})
            # Dispara tick inmediato para feedback en log.
            result["tick_started"] = outreach._outreach_start_autonomous_tick(source="enabled_via_panel")
        else:
            outreach._autopilot_log("info", "disabled_via_panel",
                           "Modo automático pausado desde el panel")
    if payload.targets is not None:
        outreach._autopilot_log("info", "targets_updated",
                       f"Objetivos actualizados ({result.get('targets_count', 0)} combos)",
                       {"targets": result.get("targets", [])})
    if payload.target_companies is not None:
        outreach._autopilot_log("info", "target_companies_updated",
                       f"Objetivo actualizado: contactar {result.get('target_companies', 0)} empresas",
                       {"target_companies": result.get("target_companies", 0)})
    if payload.followup_days is not None:
        outreach._autopilot_log("info", "followup_days_updated",
                       "Tiempos de follow-up actualizados",
                       {"followup_days": result.get("followup_days", {})})
    if payload.discovery_enabled is not None:
        outreach._autopilot_log("info", "discovery_enabled_updated",
                       f"Discovery {'activado' if payload.discovery_enabled else 'desactivado'} desde el panel",
                       {"discovery_enabled": bool(payload.discovery_enabled)})
    return result


@app.post("/admin/outreach/autopilot-tick", dependencies=[Depends(security._require_admin_token)])
def outreach_autopilot_tick():
    """Fuerza una ronda del worker autónomo."""
    outreach._autopilot_log("info", "manual_run_requested",
                   "Ronda solicitada manualmente desde el panel")
    started = outreach._outreach_start_autonomous_tick(source="manual_panel", log_overlap=True)
    return {"ok": True, "started": started, "started_at": outreach._outreach_now()}


@app.get("/admin/outreach/autopilot-log", dependencies=[Depends(security._require_admin_token)])
def outreach_autopilot_log(limit: int = 100, level: str = "", since_id: int = 0):
    """Últimos eventos del modo automático. Ordenados por id desc."""
    limit = max(1, min(500, int(limit or 100)))
    where = []
    params: List[Any] = []
    if since_id:
        where.append("id > ?")
        params.append(int(since_id))
    lvl = (level or "").strip().lower()
    if lvl in {"info", "success", "warning", "error"}:
        where.append("level = ?")
        params.append(lvl)
    sql = "SELECT id, ts, level, event, message, detail FROM autopilot_activity_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with outreach._outreach_db() as conn:
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS autopilot_activity_log (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       ts TEXT NOT NULL,
                       level TEXT NOT NULL DEFAULT 'info',
                       event TEXT NOT NULL DEFAULT '',
                       message TEXT NOT NULL DEFAULT '',
                       detail TEXT DEFAULT ''
                   )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_autopilot_log_ts ON autopilot_activity_log(ts)")
            conn.commit()
            rows = conn.execute(sql, params).fetchall()
    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "ts": r["ts"],
            "level": r["level"],
            "event": r["event"],
            "message": r["message"],
            "detail": r["detail"] or "",
        })
    return {"items": items, "count": len(items)}


@app.get("/admin/outreach/prospects/{email}/followup-copy", dependencies=[Depends(security._require_admin_token)])
def outreach_prospect_followup_copy(email: str):
    email_l = email.lower().strip()
    with outreach._outreach_db() as conn:
        row = conn.execute(
            """
            SELECT p.email, p.business_name, p.contact_name, p.niche, p.service_hint, p.city,
                   p.phone, p.website, p.tags, p.source, COALESCE(p.status,'new') AS status,
                   (SELECT MAX(s.sent_at) FROM sends s WHERE s.email=p.email AND s.mode='send') AS last_sent_at,
                   (SELECT MAX(e.ts) FROM events e WHERE e.email=p.email) AS last_event_at,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open') AS opens,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='demo_generated') AS demos,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply_intent') AS reply_intents,
                   (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply') AS replies,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send') AS total_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu1') AS fu1_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu2') AS fu2_sent,
                   (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='breakup') AS breakup_sent
            FROM prospects p
            WHERE p.email=?
            """,
            (email_l,),
        ).fetchone()
        followup_days = outreach._outreach_config_followup_days(conn)
    if not row:
        raise HTTPException(status_code=404, detail="Prospect no encontrado.")
    return outreach._outreach_followup_item(row, followup_days)


@app.get("/admin/outreach/ab-stats", dependencies=[Depends(security._require_admin_token)])
def outreach_ab_stats(stage: str = "cold", days: int = 30):
    """A/B subjects: open rate y reply rate por variante (A vs B) en stage dado.

    Match opens/replies por email+stage para no contar eventos cruzados de stages
    siguientes. Solo cuenta envios reales (mode='send').
    """
    if stage not in outreach.OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    days = max(1, min(365, int(days or 30)))
    cutoff = (timeutils._utc_now() - timedelta(days=days)).isoformat(timespec="seconds")

    with outreach._outreach_db() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(NULLIF(s.subject_variant, ''), '?') AS variant,
                   COUNT(DISTINCT s.email) AS sent,
                   SUM(CASE WHEN EXISTS (
                     SELECT 1 FROM events e WHERE e.email = s.email AND e.type = 'open'
                       AND e.stage = s.stage AND e.ts >= s.sent_at
                   ) THEN 1 ELSE 0 END) AS opens_unique,
                   SUM(CASE WHEN EXISTS (
                     SELECT 1 FROM events e WHERE e.email = s.email AND e.type = 'click'
                       AND e.stage = s.stage AND e.ts >= s.sent_at
                   ) THEN 1 ELSE 0 END) AS clicks_unique,
                   SUM(CASE WHEN EXISTS (
                     SELECT 1 FROM events e WHERE e.email = s.email AND e.type = 'reply'
                       AND e.ts >= s.sent_at
                   ) THEN 1 ELSE 0 END) AS replies_unique
            FROM sends s
            WHERE s.stage = ? AND s.mode = 'send' AND s.sent_at >= ?
            GROUP BY variant
            ORDER BY variant
            """,
            (stage, cutoff),
        ).fetchall()

        sample_rows = conn.execute(
            """SELECT subject_variant, subject, COUNT(*) AS c FROM sends
               WHERE stage = ? AND mode = 'send' AND sent_at >= ?
               GROUP BY subject_variant, subject ORDER BY c DESC LIMIT 20""",
            (stage, cutoff),
        ).fetchall()

    items = []
    for r in rows:
        sent = int(r["sent"] or 0)
        opens = int(r["opens_unique"] or 0)
        clicks = int(r["clicks_unique"] or 0)
        replies = int(r["replies_unique"] or 0)
        items.append({
            "variant": r["variant"],
            "sent": sent,
            "opens": opens,
            "clicks": clicks,
            "replies": replies,
            "open_rate_pct": round(opens / sent * 100, 1) if sent else 0.0,
            "click_rate_pct": round(clicks / sent * 100, 1) if sent else 0.0,
            "reply_rate_pct": round(replies / sent * 100, 1) if sent else 0.0,
        })

    samples = [
        {"variant": r["subject_variant"] or "?", "subject": r["subject"], "count": int(r["c"])}
        for r in sample_rows
    ]
    return {"stage": stage, "window_days": days, "variants": items, "samples": samples}






@app.post("/admin/outreach/imap/poll", dependencies=[Depends(security._require_admin_token)])
def outreach_imap_poll_now():
    """Lanza una pasada del poller IMAP en modo sincrono (manual)."""
    if not outreach.OUTREACH_IMAP_AVAILABLE or outreach.outreach_imap_poll is None:
        raise HTTPException(status_code=503, detail="Modulo IMAP no disponible.")
    if not os.getenv("IMAP_HOST", "").strip():
        raise HTTPException(status_code=400, detail="IMAP_HOST no configurado en .env.")
    db_path = Path(os.getenv("OUTREACH_DB_PATH", str(outreach.OUTREACH_DEFAULT_DB)))
    stats = outreach.outreach_imap_poll(db_path)
    return {"ok": True, "stats": stats}


@app.get("/admin/outreach/ga4-stats", dependencies=[Depends(security._require_admin_token)])
def outreach_ga4_stats(days: int = 30):
    """Sesiones por campaña UTM desde GA4 (utm_medium=email, utm_source=outreach)."""
    if not outreach.GA4_PROPERTY_ID:
        return {"ok": False, "error": "outreach.GA4_PROPERTY_ID no configurado.", "sessions": []}
    if not outreach.GA4_SERVICE_ACCOUNT_JSON:
        return {"ok": False, "error": "outreach.GA4_SERVICE_ACCOUNT_JSON no configurado.", "sessions": []}
    try:
        from google.oauth2 import service_account as _sa
        from google.auth.transport.requests import Request as _GRequest
        import requests as _req

        creds = _sa.Credentials.from_service_account_file(
            outreach.GA4_SERVICE_ACCOUNT_JSON,
            scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )
        creds.refresh(_GRequest())
        days_safe = max(1, min(365, int(days)))
        url = f"https://analyticsdata.googleapis.com/v1beta/properties/{outreach.GA4_PROPERTY_ID}:runReport"
        body = {
            "dateRanges": [{"startDate": f"{days_safe}daysAgo", "endDate": "today"}],
            "dimensions": [{"name": "sessionCampaignName"}, {"name": "date"}],
            "metrics": [{"name": "sessions"}, {"name": "activeUsers"}],
            "dimensionFilter": {
                "andGroup": {
                    "expressions": [
                        {"filter": {"fieldName": "sessionSource", "stringFilter": {"value": "outreach", "matchType": "EXACT"}}},
                        {"filter": {"fieldName": "sessionMedium", "stringFilter": {"value": "email", "matchType": "EXACT"}}},
                    ]
                }
            },
        }
        resp = _req.post(url, json=body, headers={"Authorization": f"Bearer {creds.token}"}, timeout=10)
        if not resp.ok:
            return {"ok": False, "error": f"GA4 API {resp.status_code}: {resp.text[:200]}", "sessions": []}
        rows = resp.json().get("rows", [])
        by_campaign: dict[str, dict] = {}
        for row in rows:
            campaign = row["dimensionValues"][0]["value"]
            sessions = int(row["metricValues"][0]["value"])
            users = int(row["metricValues"][1]["value"])
            if campaign not in by_campaign:
                by_campaign[campaign] = {"campaign": campaign, "sessions": 0, "users": 0}
            by_campaign[campaign]["sessions"] += sessions
            by_campaign[campaign]["users"] += users
        result = sorted(by_campaign.values(), key=lambda x: x["sessions"], reverse=True)
        return {"ok": True, "sessions": result, "days": days_safe}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "sessions": []}


# ----- Prospects list/detail/CRUD -----

@app.get("/admin/outreach/prospects", dependencies=[Depends(security._require_admin_token)])
def outreach_list_prospects(
    q: str = "",
    status: str = "",
    niche: str = "",
    city: str = "",
    source: str = "",
    stage: str = "",
    clicked_vantelia: bool = False,
    days: int = 0,
    page: int = 1,
    page_size: int = 50,
):
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    offset = (page - 1) * page_size

    where = []
    params: list = []
    if q:
        where.append("(p.business_name LIKE ? OR p.email LIKE ? OR p.contact_name LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if status:
        where.append("p.status = ?")
        params.append(status)
    if niche:
        where.append("p.niche LIKE ?")
        params.append(f"%{niche}%")
    if city:
        where.append("p.city LIKE ?")
        params.append(f"%{city}%")
    if source:
        where.append("p.source LIKE ?")
        params.append(f"%{source}%")
    if days and days > 0:
        cutoff = (timeutils._utc_now() - timedelta(days=int(days))).isoformat(timespec="seconds")
        where.append("p.updated_at >= ?")
        params.append(cutoff)
    if clicked_vantelia:
        where.append(
            """EXISTS (
                SELECT 1 FROM events ev
                WHERE ev.email=p.email AND ev.type='click'
                  AND (lower(coalesce(ev.url,'')) LIKE 'https://www.vantelia.es%'
                       OR lower(coalesce(ev.url,'')) LIKE 'https://vantelia.es%')
            )"""
        )

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    with outreach._outreach_db() as conn:
        sql = f"""
        SELECT p.*,
               (SELECT stage FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_stage,
               (SELECT sent_at FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_sent_at,
               (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='cold') AS cold_sent,
               (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu1') AS fu1_sent,
               (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='fu2') AS fu2_sent,
               (SELECT COUNT(*) FROM sends s WHERE s.email=p.email AND s.mode='send' AND s.stage='breakup') AS breakup_sent,
               (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open') AS opens,
               (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks,
               (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click'
                  AND (lower(coalesce(e.url,'')) LIKE 'https://www.vantelia.es%'
                       OR lower(coalesce(e.url,'')) LIKE 'https://vantelia.es%')) AS vantelia_clicks,
               (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply_intent') AS reply_intents,
               (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply') AS replies,
               (SELECT 1 FROM suppressions x WHERE x.email=p.email) AS suppressed
        FROM prospects p
        {where_sql}
        """
        if stage:
            sql += " AND last_stage = ? "
            params.append(stage)
        sql += " ORDER BY p.updated_at DESC LIMIT ? OFFSET ?"
        params.extend([page_size, offset])

        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(f"SELECT COUNT(*) AS c FROM prospects p {where_sql}", params[:-2]).fetchone()["c"]

    items = []
    for r in rows:
        items.append({
            "email": r["email"],
            "business_name": r["business_name"],
            "contact_name": r["contact_name"],
            "niche": r["niche"],
            "website": r["website"],
            "service_hint": r["service_hint"],
            "city": r["city"],
            "phone": r["phone"],
            "tags": r["tags"],
            "source": r["source"],
            "status": r["status"] if "status" in r.keys() else "new",
            "notes": r["notes"] if "notes" in r.keys() else "",
            "score": r["score"] if "score" in r.keys() else 0,
            "last_stage": r["last_stage"],
            "last_sent_at": r["last_sent_at"],
            "cold_sent": r["cold_sent"],
            "fu1_sent": r["fu1_sent"],
            "fu2_sent": r["fu2_sent"],
            "breakup_sent": r["breakup_sent"],
            "opens": r["opens"],
            "clicks": r["clicks"],
            "vantelia_clicks": r["vantelia_clicks"],
            "reply_intents": r["reply_intents"],
            "replies": r["replies"],
            "suppressed": bool(r["suppressed"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/admin/outreach/prospects/{email}", dependencies=[Depends(security._require_admin_token)])
def outreach_prospect_detail(email: str):
    email_l = email.lower().strip()
    with outreach._outreach_db() as conn:
        row = conn.execute("SELECT * FROM prospects WHERE email=?", (email_l,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Prospect no encontrado.")
        sends = conn.execute(
            "SELECT id, stage, subject, body_text, body_html, sent_at, mode, message_id FROM sends WHERE email=? ORDER BY id ASC",
            (email_l,),
        ).fetchall()
        events = conn.execute(
            "SELECT id, type, stage, url, ts, ua FROM events WHERE email=? ORDER BY id ASC",
            (email_l,),
        ).fetchall()
        suppression = conn.execute("SELECT reason, added_at FROM suppressions WHERE email=?", (email_l,)).fetchone()
    return {
        "prospect": {k: row[k] for k in row.keys()},
        "sends": [dict(r) for r in sends],
        "events": [dict(r) for r in events],
        "suppression": dict(suppression) if suppression else None,
    }


class OutreachProspectsBulkIn(BaseModel):
    items: List[OutreachProspectIn]
    upsert: bool = False


@app.post("/admin/outreach/prospects/bulk", dependencies=[Depends(security._require_admin_token)])
def outreach_bulk_prospects(payload: OutreachProspectsBulkIn):
    added = updated = skipped = 0
    now = outreach._outreach_now()
    with outreach._outreach_db() as conn:
        for item in payload.items:
            email = str(item.email).lower().strip()
            if not email:
                skipped += 1
                continue
            existing = conn.execute("SELECT email FROM prospects WHERE email=?", (email,)).fetchone()
            if existing:
                if payload.upsert:
                    conn.execute(
                        """UPDATE prospects SET business_name=?, contact_name=?, niche=?, website=?,
                           service_hint=?, city=?, phone=?, tags=?, source=?, updated_at=? WHERE email=?""",
                        (item.business_name, item.contact_name, item.niche, item.website,
                         item.service_hint, item.city or "Torrejon de Ardoz", item.phone,
                         item.tags, item.source, now, email),
                    )
                    updated += 1
                else:
                    skipped += 1
                continue
            conn.execute(
                """INSERT INTO prospects (email, business_name, contact_name, niche, website,
                   service_hint, city, phone, tags, source, status, notes, score, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (email, item.business_name, item.contact_name, item.niche, item.website,
                 item.service_hint, item.city or "Torrejon de Ardoz", item.phone, item.tags,
                 item.source, item.status, item.notes, int(item.score or 0), now, now),
            )
            added += 1
        conn.commit()
    return {"ok": True, "added": added, "updated": updated, "skipped": skipped}


@app.post("/admin/outreach/prospects", dependencies=[Depends(security._require_admin_token)])
def outreach_create_prospect(payload: OutreachProspectIn):
    email = str(payload.email).lower().strip()
    now = outreach._outreach_now()
    with outreach._outreach_db() as conn:
        existing = conn.execute("SELECT email FROM prospects WHERE email=?", (email,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Ya existe.")
        conn.execute(
            """INSERT INTO prospects (email, business_name, contact_name, niche, website,
               service_hint, city, phone, tags, source, status, notes, score, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (email, payload.business_name, payload.contact_name, payload.niche, payload.website,
             payload.service_hint, payload.city or "Torrejon de Ardoz", payload.phone, payload.tags,
             payload.source, payload.status, payload.notes, int(payload.score or 0), now, now),
        )
        conn.commit()
    return {"ok": True, "email": email}


@app.patch("/admin/outreach/prospects/{email}", dependencies=[Depends(security._require_admin_token)])
def outreach_update_prospect(email: str, payload: OutreachProspectPatch):
    email_l = email.lower().strip()
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not fields:
        return {"ok": True, "updated": 0}
    fields["updated_at"] = outreach._outreach_now()
    set_sql = ", ".join(f"{k}=?" for k in fields.keys())
    with outreach._outreach_db() as conn:
        cur = conn.execute(f"UPDATE prospects SET {set_sql} WHERE email=?", (*fields.values(), email_l))
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Prospect no encontrado.")
    return {"ok": True, "updated": cur.rowcount}


@app.delete("/admin/outreach/prospects/{email}", dependencies=[Depends(security._require_admin_token)])
def outreach_delete_prospect(email: str):
    email_l = email.lower().strip()
    with outreach._outreach_db() as conn:
        cur = conn.execute("DELETE FROM prospects WHERE email=?", (email_l,))
        conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


# ----- Import CSV -----

@app.post("/admin/outreach/import", dependencies=[Depends(security._require_admin_token)])
async def outreach_import_csv(request: Request):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="CSV vacio.")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = body.decode("latin-1", errors="replace")
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV sin cabecera.")
    added = updated = skipped = 0
    now = outreach._outreach_now()
    with outreach._outreach_db() as conn:
        for row in reader:
            email = (row.get("email") or "").strip().lower()
            business = (row.get("business_name") or "").strip()
            if not email or "@" not in email or not business:
                skipped += 1
                continue
            payload = {
                "email": email,
                "business_name": business,
                "contact_name": (row.get("contact_name") or "").strip(),
                "niche": (row.get("niche") or "").strip(),
                "website": (row.get("website") or "").strip(),
                "service_hint": (row.get("service_hint") or "").strip(),
                "city": (row.get("city") or "").strip() or "Torrejon de Ardoz",
                "phone": (row.get("phone") or "").strip(),
                "tags": (row.get("tags") or "").strip(),
                "source": (row.get("source") or "csv-upload").strip(),
                "now": now,
            }
            existing = conn.execute("SELECT email FROM prospects WHERE email=?", (email,)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE prospects SET business_name=:business_name, contact_name=:contact_name,
                       niche=:niche, website=:website, service_hint=:service_hint, city=:city,
                       phone=:phone, tags=:tags, source=:source,
                       updated_at=:now WHERE email=:email""",
                    payload,
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO prospects (email, business_name, contact_name, niche, website,
                       service_hint, city, phone, tags, source, created_at, updated_at)
                       VALUES (:email, :business_name, :contact_name, :niche, :website,
                       :service_hint, :city, :phone, :tags, :source, :now, :now)""",
                    payload,
                )
                added += 1
        conn.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


@app.get("/admin/outreach/export.csv", dependencies=[Depends(security._require_admin_token)])
def outreach_export_csv():
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "email", "business_name", "contact_name", "niche", "website", "service_hint",
        "city", "phone", "tags", "source", "status", "score", "last_stage", "last_sent_at",
        "opens", "clicks", "reply_intents", "replies", "suppressed",
    ])
    with outreach._outreach_db() as conn:
        rows = conn.execute(
            """SELECT p.*,
                  (SELECT stage FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_stage,
                  (SELECT sent_at FROM sends s WHERE s.email=p.email ORDER BY id DESC LIMIT 1) AS last_sent_at,
                  (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='open') AS opens,
                  (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='click') AS clicks,
                  (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply_intent') AS reply_intents,
                  (SELECT COUNT(*) FROM events e WHERE e.email=p.email AND e.type='reply') AS replies,
                  (SELECT 1 FROM suppressions x WHERE x.email=p.email) AS suppressed
                FROM prospects p ORDER BY p.created_at ASC"""
        ).fetchall()
    for r in rows:
        writer.writerow([
            r["email"], r["business_name"], r["contact_name"], r["niche"], r["website"],
            r["service_hint"], r["city"], r["phone"], r["tags"], r["source"],
            r["status"] if "status" in r.keys() else "new",
            r["score"] if "score" in r.keys() else 0,
            r["last_stage"] or "", r["last_sent_at"] or "",
            r["opens"], r["clicks"], r["reply_intents"], r["replies"], "1" if r["suppressed"] else "0",
        ])
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="outreach_prospects.csv"'},
    )


# ----- Suppressions -----

@app.post("/admin/outreach/suppress", dependencies=[Depends(security._require_admin_token)])
def outreach_suppress(payload: OutreachSuppressRequest):
    email = str(payload.email).lower().strip()
    with outreach._outreach_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO suppressions (email, reason, added_at) VALUES (?,?,?)",
            (email, payload.reason or "manual", outreach._outreach_now()),
        )
        conn.commit()
    return {"ok": True}


@app.delete("/admin/outreach/suppress/{email}", dependencies=[Depends(security._require_admin_token)])
def outreach_unsuppress(email: str):
    with outreach._outreach_db() as conn:
        cur = conn.execute("DELETE FROM suppressions WHERE email=?", (email.lower().strip(),))
        conn.commit()
    return {"ok": True, "deleted": cur.rowcount}


@app.get("/admin/outreach/suppressions", dependencies=[Depends(security._require_admin_token)])
def outreach_list_suppressions():
    with outreach._outreach_db() as conn:
        rows = conn.execute("SELECT email, reason, added_at FROM suppressions ORDER BY added_at DESC").fetchall()
    return {"items": [dict(r) for r in rows]}


# ----- Templates overrides -----

@app.get("/admin/outreach/templates", dependencies=[Depends(security._require_admin_token)])
def outreach_get_templates():
    with outreach._outreach_db() as conn:
        rows = conn.execute("SELECT * FROM templates_overrides").fetchall()
    overrides = {r["stage"]: dict(r) for r in rows}

    # Render defaults with placeholder variables so the panel can pre-populate the form
    defaults: dict = {}
    if outreach.OUTREACH_AVAILABLE:
        _placeholder = OutreachProspect(
            email="demo@example.com",
            business_name="{business}",
            contact_name="{first_name}",
            niche="{niche}",
            city="{city}",
            service_hint="{service_hint}",
            website="{website}",
        )
        for _stage in outreach.OUTREACH_STAGES:
            try:
                _subj, _text, _html = outreach_render(_stage, _placeholder, "{unsubscribe}")
                defaults[_stage] = {
                    "subject_pool": _subj,
                    "body_text": _text,
                    "body_html": _html,
                }
            except Exception:
                pass

    return {"stages": outreach.OUTREACH_STAGES, "overrides": overrides, "defaults": defaults}


@app.put("/admin/outreach/templates", dependencies=[Depends(security._require_admin_token)])
def outreach_put_template(payload: OutreachTemplateOverride):
    if payload.stage not in outreach.OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    with outreach._outreach_db() as conn:
        conn.execute(
            """INSERT INTO templates_overrides (stage, subject_pool, body_text, body_html, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(stage) DO UPDATE SET subject_pool=excluded.subject_pool,
                   body_text=excluded.body_text, body_html=excluded.body_html, updated_at=excluded.updated_at""",
            (payload.stage, payload.subject_pool, payload.body_text, payload.body_html, outreach._outreach_now()),
        )
        conn.commit()
    return {"ok": True}


@app.delete("/admin/outreach/templates/{stage}", dependencies=[Depends(security._require_admin_token)])
def outreach_delete_template(stage: str):
    if stage not in outreach.OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    with outreach._outreach_db() as conn:
        conn.execute("DELETE FROM templates_overrides WHERE stage=?", (stage,))
        conn.commit()
    return {"ok": True}


class OutreachTemplatePreview(BaseModel):
    stage: str
    subject_pool: str = ""
    body_text: str = ""
    body_html: str = ""
    sample_business: str = "Dental Smile"
    sample_first_name: str = "Maria"
    sample_niche: str = "clinica dental"
    sample_city: str = "Torrejon de Ardoz"
    sample_website: str = "https://dentalsmile.es"
    sample_email: str = "maria@dentalsmile.es"




@app.get("/admin/outreach/prospects/{email}/render", dependencies=[Depends(security._require_admin_token)])
def outreach_render_prospect_email(email: str, stage: str = "cold", send_id: int = 0):
    if not outreach.OUTREACH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Outreach no disponible.")
    email = email.lower().strip()
    from outreach_campaign import render_with_override, load_template_overrides  # type: ignore
    with outreach._outreach_db() as conn:
        if send_id:
            send_row = conn.execute(
                "SELECT id, email, stage, subject, body_text, body_html FROM sends WHERE id=? AND email=?",
                (send_id, email),
            ).fetchone()
            if not send_row:
                raise HTTPException(status_code=404, detail="Envio no encontrado.")
            if send_row["body_text"] or send_row["body_html"]:
                return {
                    "subject": send_row["subject"] or "",
                    "text": send_row["body_text"] or "",
                    "html": outreach._outreach_admin_preview_html(send_row["body_html"] or ""),
                    "stage": send_row["stage"] or stage,
                    "email": email,
                    "send_id": send_id,
                    "snapshot": True,
                }
        if stage not in outreach.OUTREACH_STAGES:
            raise HTTPException(status_code=400, detail="Stage invalido.")
        row = conn.execute("SELECT * FROM prospects WHERE email=?", (email,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Prospect no encontrado.")
        overrides = load_template_overrides(conn)
    p = OutreachProspect(
        email=row["email"],
        business_name=row["business_name"] or "",
        contact_name=row["contact_name"] or "",
        niche=row["niche"] or "",
        service_hint=row["service_hint"] or "",
        city=row["city"] or "",
        website=row["website"] or "",
        phone=row["phone"] or "",
        tags=row["tags"] or "",
        source=row["source"] or "",
    )
    unsub = os.getenv("OUTREACH_UNSUBSCRIBE_EMAIL", "baja@vantelia.es").strip() or "baja@vantelia.es"
    subject, text, html = render_with_override(stage, p, unsub, overrides)
    return {"subject": subject, "text": text, "html": outreach._outreach_admin_preview_html(html), "stage": stage, "email": email}


@app.post("/admin/outreach/templates/preview", dependencies=[Depends(security._require_admin_token)])
def outreach_preview_template(payload: OutreachTemplatePreview):
    if not outreach.OUTREACH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Outreach no disponible.")
    if payload.stage not in outreach.OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    from outreach_campaign import render_with_override  # type: ignore
    p = OutreachProspect(
        email=payload.sample_email,
        business_name=payload.sample_business,
        contact_name=payload.sample_first_name,
        niche=payload.sample_niche,
        service_hint=payload.sample_niche,
        city=payload.sample_city,
        website=payload.sample_website,
    )
    unsub = os.getenv("OUTREACH_UNSUBSCRIBE_EMAIL", "baja@vantelia.es").strip() or "baja@vantelia.es"
    overrides = {payload.stage: {
        "subject_pool": payload.subject_pool,
        "body_text": payload.body_text,
        "body_html": payload.body_html,
    }}
    subject, text, html = render_with_override(payload.stage, p, unsub, overrides)
    return {"subject": subject, "text": text, "html": html}














@app.get("/admin/outreach/campaigns", dependencies=[Depends(security._require_admin_token)])
def outreach_list_campaigns(limit: int = 50):
    limit = max(1, min(200, int(limit)))
    with outreach._outreach_db() as conn:
        outreach._outreach_backfill_orphan_send_campaigns(conn)
        rows = conn.execute(
            "SELECT * FROM campaigns ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {"items": [outreach._outreach_campaign_summary(conn, r) for r in rows]}


@app.post("/admin/outreach/campaigns", dependencies=[Depends(security._require_admin_token)])
def outreach_create_campaign(payload: OutreachCampaignCreate):
    if payload.stage not in outreach.OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    emails = [str(email).lower().strip() for email in payload.emails if str(email).strip()]
    with outreach._outreach_db() as conn:
        campaign_id = outreach._outreach_create_campaign(
            conn,
            name=payload.name,
            stage=payload.stage,
            emails=emails,
            settings=outreach_smtp_settings(),
            delay=payload.delay,
            jitter=payload.jitter,
            force_window=payload.force_window,
            status="draft",
        )
        conn.commit()
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        return outreach._outreach_campaign_summary(conn, row)


@app.get("/admin/outreach/campaigns/{campaign_id}", dependencies=[Depends(security._require_admin_token)])
def outreach_campaign_detail(campaign_id: int):
    with outreach._outreach_db() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Campana no encontrada.")
        members = conn.execute(
            """SELECT cm.*, p.business_name, p.website, p.phone
               FROM campaign_members cm
               LEFT JOIN prospects p ON p.email=cm.email
               WHERE cm.campaign_id=?
               ORDER BY cm.id ASC""",
            (campaign_id,),
        ).fetchall()
        return {
            "campaign": outreach._outreach_campaign_summary(conn, row),
            "members": [dict(r) for r in members],
        }


@app.patch("/admin/outreach/campaigns/{campaign_id}", dependencies=[Depends(security._require_admin_token)])
def outreach_patch_campaign(campaign_id: int, payload: OutreachCampaignPatch):
    allowed = {"draft", "running", "paused", "completed", "archived"}
    fields = []
    values: List[Any] = []
    if payload.status is not None:
        if payload.status not in allowed:
            raise HTTPException(status_code=400, detail="Estado invalido.")
        fields.append("status=?")
        values.append(payload.status)
    if payload.name is not None:
        fields.append("name=?")
        values.append(payload.name.strip()[:180] or "Campana")
    if not fields:
        raise HTTPException(status_code=400, detail="Sin cambios.")
    fields.append("updated_at=?")
    values.append(outreach._outreach_now())
    values.append(campaign_id)
    with outreach._outreach_db() as conn:
        cur = conn.execute(f"UPDATE campaigns SET {', '.join(fields)} WHERE id=?", values)
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Campana no encontrada.")
        conn.commit()
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        return outreach._outreach_campaign_summary(conn, row)


@app.post("/admin/outreach/campaigns/{campaign_id}/duplicate", dependencies=[Depends(security._require_admin_token)])
def outreach_duplicate_campaign(campaign_id: int):
    with outreach._outreach_db() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Campana no encontrada.")
        emails = [r["email"] for r in conn.execute("SELECT email FROM campaign_members WHERE campaign_id=? ORDER BY id ASC", (campaign_id,))]
        new_id = outreach._outreach_create_campaign(
            conn,
            name=f"{row['name']} copia",
            stage=row["stage"],
            emails=emails,
            settings={"from_email": row["sender"]},
            delay=float(row["delay"] or 70),
            jitter=float(row["jitter"] or 25),
            force_window=bool(row["force_window"]),
            status="draft",
        )
        conn.commit()
        new_row = conn.execute("SELECT * FROM campaigns WHERE id=?", (new_id,)).fetchone()
        return outreach._outreach_campaign_summary(conn, new_row)


@app.post("/admin/outreach/campaigns/{campaign_id}/resume", dependencies=[Depends(security._require_admin_token)])
def outreach_resume_campaign(campaign_id: int):
    with outreach._outreach_db() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Campana no encontrada.")
        if row["status"] == "archived":
            raise HTTPException(status_code=400, detail="No se puede reanudar una campana archivada.")
        emails = [
            r["email"] for r in conn.execute(
                "SELECT email FROM campaign_members WHERE campaign_id=? AND status='pending' ORDER BY id ASC",
                (campaign_id,),
            )
        ]
        if not emails:
            conn.execute("UPDATE campaigns SET status='completed', updated_at=? WHERE id=?", (outreach._outreach_now(), campaign_id))
            conn.commit()
            return {"ok": True, "campaign_id": campaign_id, "job_id": 0, "message": "Sin pendientes; campana completada."}
        params = {
            "stage": row["stage"] or "cold",
            "max": len(emails),
            "send": True,
            "test_to": "",
            "email": "",
            "emails": emails,
            "campaign_name": row["name"],
            "campaign_id": campaign_id,
            "after_days": 4,
            "delay": float(row["delay"] or 70),
            "jitter": float(row["jitter"] or 25),
            "force_window": bool(row["force_window"]),
            "dry_run": False,
        }
        cur = conn.execute(
            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
            ("send", "queued", json.dumps(params), "", outreach._outreach_now()),
        )
        job_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE campaigns SET status='running', job_id=?, updated_at=? WHERE id=?",
            (job_id, outreach._outreach_now(), campaign_id),
        )
        conn.commit()
    threading.Thread(target=outreach._outreach_run_send_job, args=(job_id, params), daemon=True).start()
    return {"ok": True, "campaign_id": campaign_id, "job_id": job_id}


@app.post("/admin/outreach/campaigns/{campaign_id}/prepare-followup", dependencies=[Depends(security._require_admin_token)])
def outreach_prepare_campaign_followup(campaign_id: int):
    with outreach._outreach_db() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Campana no encontrada.")
        stage = row["stage"] or "cold"
        try:
            next_stage = outreach.OUTREACH_STAGES[outreach.OUTREACH_STAGES.index(stage) + 1]
        except Exception:
            raise HTTPException(status_code=400, detail="Esta campana ya esta en la ultima etapa.")
        suppressed = 0
        replied = 0
        already_sent = 0
        eligible: List[str] = []
        for member in conn.execute("SELECT email FROM campaign_members WHERE campaign_id=? ORDER BY id ASC", (campaign_id,)):
            email = member["email"]
            if conn.execute("SELECT 1 FROM suppressions WHERE email=?", (email,)).fetchone():
                suppressed += 1
            elif conn.execute("SELECT 1 FROM events WHERE email=? AND type='reply'", (email,)).fetchone():
                replied += 1
            elif conn.execute("SELECT 1 FROM sends WHERE email=? AND stage=? AND mode='send'", (email, next_stage)).fetchone():
                already_sent += 1
            elif conn.execute("SELECT 1 FROM sends WHERE email=? AND stage=? AND mode='send'", (email, stage)).fetchone():
                eligible.append(email)
        return {
            "campaign_id": campaign_id,
            "campaign_name": row["name"],
            "from_stage": stage,
            "next_stage": next_stage,
            "eligible_emails": eligible,
            "counts": {
                "eligible": len(eligible),
                "suppressed": suppressed,
                "replied": replied,
                "already_sent": already_sent,
            },
        }


@app.post("/admin/outreach/preflight", dependencies=[Depends(security._require_admin_token)])
def outreach_preflight(payload: OutreachPreflightRequest):
    if not outreach.OUTREACH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Outreach no disponible.")
    if payload.stage not in outreach.OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")

    selected_emails = [
        str(email).lower().strip()
        for email in payload.emails
        if str(email).strip()
    ]
    settings_row = outreach_smtp_settings()
    unsub = str(settings_row["unsubscribe_mailto"]) or "baja@vantelia.es"

    with outreach._outreach_db() as conn:
        try:
            from outreach_campaign import render_with_override, load_template_overrides  # type: ignore
            overrides = load_template_overrides(conn)
        except Exception:
            overrides = {}

        rows = []
        if selected_emails:
            placeholders = ",".join("?" for _ in selected_emails)
            rows = conn.execute(
                f"SELECT * FROM prospects WHERE email IN ({placeholders}) ORDER BY created_at ASC",
                selected_emails,
            ).fetchall()
        else:
            candidates = outreach_fetch_candidates(
                conn,
                payload.stage,
                after_days=int(payload.after_days or 4),
                limit=int(payload.max or 20),
                only_email=None,
            )
            rows = []
            for p in candidates:
                row = conn.execute("SELECT * FROM prospects WHERE email=?", (p.email,)).fetchone()
                if row:
                    rows.append(row)

        missing_requested = max(0, len(set(selected_emails)) - len(rows)) if selected_emails else 0
        suppressed = 0
        missing_email = 0
        already_contacted = 0
        already_in_campaign = 0
        real_rows = []
        skipped_samples = []
        for row in rows:
            email = (row["email"] or "").strip().lower()
            reason = ""
            if not email or "@" not in email:
                missing_email += 1
                reason = "sin email"
            elif conn.execute("SELECT 1 FROM suppressions WHERE email=?", (email,)).fetchone():
                suppressed += 1
                reason = "baja"
            elif conn.execute("SELECT 1 FROM campaign_members WHERE email=?", (email,)).fetchone():
                already_in_campaign += 1
                reason = "ya en otra campana"
            elif payload.stage == "cold" and conn.execute("SELECT 1 FROM sends WHERE email=? AND mode='send'", (email,)).fetchone():
                already_contacted += 1
                reason = "ya contactado"
            elif payload.stage != "cold" and conn.execute("SELECT 1 FROM sends WHERE email=? AND stage=? AND mode='send'", (email, payload.stage)).fetchone():
                already_contacted += 1
                reason = "stage ya enviado"
            if reason:
                if len(skipped_samples) < 8:
                    skipped_samples.append({"email": email or "-", "reason": reason})
                continue
            real_rows.append(row)

        real_count = len(real_rows)
        first = real_rows[0] if real_rows else (rows[0] if rows else None)
        subject = ""
        text = ""
        html = ""
        if first:
            preview_prospect = OutreachProspect(
                email=first["email"] or "test@example.com",
                business_name=first["business_name"] or "Prospect de prueba",
                contact_name=first["contact_name"] or "",
                niche=first["niche"] or "",
                service_hint=first["service_hint"] or "",
                city=first["city"] or "",
                website=first["website"] or "",
                phone=first["phone"] or "",
                tags=first["tags"] or "",
                source=first["source"] or "",
            )
        else:
            # El wizard puede llegar a preflight con emails descubiertos pero aun no
            # importados. Seguimos marcando 0 candidatos reales, pero renderizamos
            # una muestra para validar HTML/variables sin mostrar "solo texto plano".
            preview_prospect = OutreachProspect(
                email=(selected_emails[0] if selected_emails else "test@example.com"),
                business_name="Prospect de prueba",
                contact_name="",
                niche="",
                service_hint="",
                city="Madrid",
                website="",
                phone="",
                tags="",
                source="preflight",
            )
        if preview_prospect:
            if overrides:
                subject, text, html = render_with_override(payload.stage, preview_prospect, unsub, overrides)
            else:
                subject, text, html = outreach_render(payload.stage, preview_prospect, unsub)

    warnings = {
        "empty_href": bool(re.search(r'href=(["\'])\s*\1', html or "", re.IGNORECASE)),
        "code_fence": "```" in (html or "") or "```" in (text or ""),
        "unfilled_variables": outreach._outreach_unfilled_vars(subject, text, html),
    }
    html_active = bool(html)
    tracking_active = bool((not outreach.OUTREACH_TRACKING_DISABLED) and outreach.OUTREACH_TRACKING_SECRET and outreach.OUTREACH_TRACKING_BASE_URL)
    return {
        "stage": payload.stage,
        "counts": {
            "requested": len(selected_emails) if selected_emails else int(payload.max or 20),
            "found": len(rows),
            "real_candidates": real_count,
            "skipped": {
                "suppressed": suppressed,
                "missing_email": missing_email + missing_requested,
                "already_contacted": already_contacted,
                "already_in_campaign": already_in_campaign,
                "total": suppressed + missing_email + missing_requested + already_contacted + already_in_campaign,
            },
        },
        "skipped_samples": skipped_samples,
        "subject": subject,
        "text": text,
        "html": html,
        "html_active": html_active,
        "tracking_active": tracking_active,
        "warnings": warnings,
        "auth": outreach._outreach_preflight_auth_status(settings_row),
        "sender": {
            "from_email": settings_row.get("from_email"),
            "from_name": settings_row.get("from_name"),
            "smtp_host": settings_row.get("host"),
        },
    }


# ----- Send/jobs -----

OUTREACH_JOB_LOCK = threading.Lock()

















































@app.post("/admin/outreach/manual-email/send", dependencies=[Depends(security._require_admin_token)])
def sendManualAcquisitionEmail(payload: OutreachManualEmailPayload):
    recipient = str(payload.recipient).strip().lower()
    subject = payload.subject.strip()
    text_body = payload.text.strip()
    html_body = payload.html.strip()
    css_body = payload.css.strip()
    if not subject:
        raise HTTPException(status_code=400, detail="El asunto es obligatorio.")
    if not text_body and not html_body:
        raise HTTPException(status_code=400, detail="Anade texto plano o HTML antes de enviar.")

    final_html = outreach._manual_email_html_document(html_body, css_body) if html_body or css_body else ""
    now = outreach._outreach_now()
    message_id = ""

    if outreach.OUTREACH_AVAILABLE:
        with outreach._outreach_db() as conn:
            suppressed = conn.execute("SELECT reason FROM suppressions WHERE email=?", (recipient,)).fetchone()
            if suppressed:
                raise HTTPException(status_code=409, detail=f"El destinatario esta en bajas: {suppressed['reason'] or 'manual'}")

    try:
        if outreach.OUTREACH_AVAILABLE:
            settings_row = outreach_smtp_settings()
            msg = outreach_build_message(recipient, subject, text_body or " ", final_html, settings_row)
            emailing._send_email_object(msg)
            message_id = msg["Message-ID"] or ""
        else:
            emailing._send_email_message(recipient, subject, text_body or " ", final_html)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudo enviar email manual de captacion a %s: %s", recipient, exc)
        raise HTTPException(status_code=502, detail=f"No se pudo enviar el email: {exc}") from exc

    recorded = False
    if outreach.OUTREACH_AVAILABLE:
        with outreach._outreach_db() as conn:
            conn.execute(
                """INSERT INTO sends (email, stage, subject, body_text, body_html, sent_at, mode, message_id)
                   VALUES (?, 'manual', ?, ?, ?, ?, 'send', ?)""",
                (recipient, subject, text_body, final_html, now, message_id),
            )
            prospect = conn.execute("SELECT email FROM prospects WHERE email=?", (recipient,)).fetchone()
            if prospect:
                conn.execute(
                    "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?, 'manual_email', 'manual', ?, ?, '', '')",
                    (recipient, subject[:500], now),
                )
                conn.execute(
                    "UPDATE prospects SET status=CASE WHEN status='new' THEN 'contacted' ELSE status END, updated_at=? WHERE email=?",
                    (now, recipient),
                )
                recorded = True
            conn.commit()

    return {"ok": True, "message_id": message_id, "recorded": recorded, "sent_at": now}


@app.post("/admin/outreach/send", dependencies=[Depends(security._require_admin_token)])
def outreach_send(payload: OutreachSendRequest):
    if payload.stage not in outreach.OUTREACH_STAGES:
        raise HTTPException(status_code=400, detail="Stage invalido.")
    test_to_clean = "" if payload.dry_run else (payload.test_to or "")
    selected_emails = [str(email).lower().strip() for email in payload.emails if str(email).strip()]
    params = {
        "stage": payload.stage,
        "max": payload.max,
        "send": (not payload.dry_run) and not test_to_clean,
        "test_to": test_to_clean,
        "email": payload.email or "",
        "emails": selected_emails,
        "campaign_name": payload.campaign_name,
        "campaign_id": 0,
        "after_days": payload.after_days,
        "delay": payload.delay,
        "jitter": payload.jitter,
        "force_window": payload.force_window,
        "dry_run": bool(payload.dry_run),
        "autopilot": bool(payload.autopilot),
    }
    with outreach._outreach_db() as conn:
        campaign_id = 0
        if params["send"] and selected_emails and payload.stage == "cold":
            campaign_id = outreach._outreach_create_campaign(
                conn,
                name=payload.campaign_name or f"Campana {payload.stage} {outreach._outreach_now()[:10]}",
                stage=payload.stage,
                emails=selected_emails,
                settings=outreach_smtp_settings(),
                delay=payload.delay,
                jitter=payload.jitter,
                force_window=payload.force_window,
                status="running",
            )
            params["campaign_id"] = campaign_id
        cur = conn.execute(
            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
            ("send", "queued", json.dumps(params), "", outreach._outreach_now()),
        )
        job_id = cur.lastrowid
        if campaign_id:
            conn.execute("UPDATE campaigns SET job_id=?, updated_at=? WHERE id=?", (job_id, outreach._outreach_now(), campaign_id))
        conn.commit()

    threading.Thread(target=outreach._outreach_run_send_job, args=(job_id, params), daemon=True).start()
    return {"ok": True, "job_id": job_id, "campaign_id": params.get("campaign_id") or 0}


@app.get("/admin/outreach/jobs", dependencies=[Depends(security._require_admin_token)])
def outreach_list_jobs(limit: int = 30):
    limit = max(1, min(200, int(limit)))
    with outreach._outreach_db() as conn:
        rows = conn.execute(
            "SELECT id, kind, status, params_json, started_at, finished_at FROM jobs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.get("/admin/outreach/jobs/{job_id}", dependencies=[Depends(security._require_admin_token)])
def outreach_job_detail(job_id: int):
    with outreach._outreach_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return dict(row)


# ----- Discovery -----











@app.post("/admin/outreach/discover", dependencies=[Depends(security._require_admin_token)])
def outreach_discover_endpoint(payload: OutreachDiscoverRequest):
    if not outreach.OUTREACH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Outreach no disponible.")
    if payload.source == "places" and not os.getenv("GOOGLE_PLACES_API_KEY", "").strip():
        raise HTTPException(status_code=400, detail="Falta GOOGLE_PLACES_API_KEY en .env para source=places.")
    params = payload.model_dump()
    with outreach._outreach_db() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES (?,?,?,?,?)",
            ("discover", "queued", json.dumps(params), "", outreach._outreach_now()),
        )
        job_id = cur.lastrowid
        conn.commit()
    threading.Thread(target=outreach._outreach_run_discovery_job, args=(job_id, params), daemon=True).start()
    return {"ok": True, "job_id": job_id}


# ----- Public tracking endpoints (sin auth) -----

