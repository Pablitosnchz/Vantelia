"""Endpoints: seccion admin_growth (refactor F3).

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
from backend.main import app

@app.get("/admin/growth/overview", dependencies=[Depends(security._require_admin_token)])
async def admin_growth_overview() -> Dict[str, Any]:
    today = date.today().isoformat()
    with db._get_db_connection() as connection:
        daily_row = connection.execute("SELECT * FROM growth_daily WHERE activity_date = ?", (today,)).fetchone()
        summaries = {str(days): growth._growth_summary(connection, days) for days in (7, 30, 90)}
        opportunities = connection.execute("SELECT * FROM growth_opportunities ORDER BY updated_at DESC").fetchall()
        weekly_rows = connection.execute(
            """
            SELECT strftime('%Y-W%W', activity_date) AS week,
                   SUM(contacts) contacts, SUM(conversations) conversations,
                   SUM(proposals) proposals, SUM(won) won, SUM(eur_sold) eur_sold
            FROM growth_daily WHERE activity_date >= ?
            GROUP BY strftime('%Y-W%W', activity_date) ORDER BY week
            """,
            ((date.today() - timedelta(days=89)).isoformat(),),
        ).fetchall()
        task_rows = {row["task_key"]: bool(row["completed"]) for row in connection.execute("SELECT * FROM growth_plan_tasks").fetchall()}
        latest_review = connection.execute("SELECT * FROM growth_weekly_reviews ORDER BY week_start DESC LIMIT 1").fetchone()
    summary_30 = summaries["30"]
    states = growth._growth_states(summary_30)
    active = [row for row in opportunities if row["stage"] in growth.GROWTH_ACTIVE_STAGES]
    weighted = sum(float(row["value_eur"] or 0) * growth.GROWTH_STAGE_WEIGHTS.get(row["stage"], 0) for row in active)
    missing_next = sum(1 for row in active if not str(row["next_action"] or "").strip())
    overdue = sum(1 for row in active if row["next_action_date"] and row["next_action_date"] < today)
    plan_path = settings.BASE_DIR / "docs" / "PLAN_ESCALA_AGENCIA_IA.md"
    def breakdown(key: str) -> List[Dict[str, Any]]:
        values: Dict[str, Dict[str, Any]] = {}
        for row in opportunities:
            name = str(row[key] or "").strip() or "sin_asignar"
            entry = values.setdefault(name, {"name": name, "count": 0, "active": 0, "won": 0, "value_eur": 0.0})
            entry["count"] += 1
            entry["active"] += int(row["stage"] in growth.GROWTH_ACTIVE_STAGES)
            entry["won"] += int(row["stage"] in {"ganada", "recurrente"})
            entry["value_eur"] += float(row["value_eur"] or 0)
        return list(values.values())
    return {
        "today": growth._growth_daily_public(daily_row, today),
        "targets": growth.GROWTH_DAILY_TARGETS,
        "summaries": summaries,
        "states": states,
        "overall_state": growth._growth_overall_state(states),
        "plan": {"start_date": growth.GROWTH_PLAN_START.isoformat(), "day": max(1, (date.today() - growth.GROWTH_PLAN_START).days + 1), "horizon_days": 90},
        "pipeline": {"active": len(active), "total": len(opportunities), "weighted_value_eur": round(weighted, 2), "missing_next_action": missing_next, "overdue": overdue},
        "breakdown": {"campaigns": breakdown("campaign"), "offers": breakdown("offer")},
        "weekly": [dict(row) for row in weekly_rows],
        "opportunities": [growth._growth_opportunity_public(row) for row in opportunities],
        "tasks": [{**task, "completed": task_rows.get(task["key"], False)} for task in growth.GROWTH_PLAN_TASKS],
        "latest_review": dict(latest_review) if latest_review else None,
        "automatic_outreach": outreach._growth_automatic_outreach(),
        "plan_markdown": plan_path.read_text(encoding="utf-8") if plan_path.exists() else "",
    }


@app.put("/admin/growth/daily/{activity_date}", dependencies=[Depends(security._require_admin_token)])
async def admin_growth_daily_save(activity_date: str, data: GrowthDailyPayload) -> Dict[str, Any]:
    activity_date = growth._growth_date(activity_date)
    now = timeutils._utc_now_iso()
    values = data.model_dump()
    with db._get_db_connection() as connection:
        exists = connection.execute("SELECT 1 FROM growth_daily WHERE activity_date = ?", (activity_date,)).fetchone()
        connection.execute(
            """
            INSERT INTO growth_daily (
                activity_date, researched, contacts, followups, calls, positive_replies,
                conversations, meetings, proposals, won, eur_sold, new_recurring,
                delivery_hours, learning, blocker, next_action, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(activity_date) DO UPDATE SET
                researched=excluded.researched, contacts=excluded.contacts, followups=excluded.followups,
                calls=excluded.calls, positive_replies=excluded.positive_replies,
                conversations=excluded.conversations, meetings=excluded.meetings,
                proposals=excluded.proposals, won=excluded.won, eur_sold=excluded.eur_sold,
                new_recurring=excluded.new_recurring, delivery_hours=excluded.delivery_hours,
                learning=excluded.learning, blocker=excluded.blocker, next_action=excluded.next_action,
                updated_at=excluded.updated_at
            """,
            (activity_date, values["researched"], values["contacts"], values["followups"], values["calls"],
             values["positive_replies"], values["conversations"], values["meetings"], values["proposals"],
             values["won"], values["eur_sold"], values["new_recurring"], values["delivery_hours"],
             values["learning"], values["blocker"], values["next_action"], now, now),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM growth_daily WHERE activity_date = ?", (activity_date,)).fetchone()
    return {"ok": True, "created": not bool(exists), "item": growth._growth_daily_public(row, activity_date)}


@app.get("/admin/growth/opportunities", dependencies=[Depends(security._require_admin_token)])
async def admin_growth_opportunities(stage: str = "", campaign: str = "", offer: str = "", overdue: bool = False) -> Dict[str, Any]:
    clauses, params = [], []
    if stage:
        clauses.append("stage = ?"); params.append(growth._growth_stage(stage))
    if campaign:
        clauses.append("campaign = ?"); params.append(campaign)
    if offer:
        clauses.append("offer = ?"); params.append(offer)
    if overdue:
        clauses.append("stage NOT IN ('ganada','perdida','recurrente') AND next_action_date <> '' AND next_action_date < ?"); params.append(date.today().isoformat())
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db._get_db_connection() as connection:
        rows = connection.execute("SELECT * FROM growth_opportunities" + where + " ORDER BY updated_at DESC", tuple(params)).fetchall()
    return {"items": [growth._growth_opportunity_public(row) for row in rows]}




@app.post("/admin/growth/opportunities", dependencies=[Depends(security._require_admin_token)])
async def admin_growth_opportunity_create(data: GrowthOpportunityPayload) -> Dict[str, Any]:
    item = data.model_dump()
    item["stage"] = growth._growth_stage(item["stage"])
    opportunity_id, now = uuid.uuid4().hex, timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """INSERT INTO growth_opportunities
            (id,company,campaign,offer,stage,value_eur,decision_maker,contact,problem,next_action,next_action_date,decision_date,notes,lost_reason,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (opportunity_id, item["company"], item["campaign"], item["offer"], item["stage"], item["value_eur"],
             item["decision_maker"], item["contact"], item["problem"], item["next_action"], item["next_action_date"],
             item["decision_date"], item["notes"], item["lost_reason"], now, now),
        )
        growth._growth_audit(connection, opportunity_id, "created", item)
        connection.commit()
        row = connection.execute("SELECT * FROM growth_opportunities WHERE id = ?", (opportunity_id,)).fetchone()
    return {"ok": True, "item": growth._growth_opportunity_public(row)}


@app.patch("/admin/growth/opportunities/{opportunity_id}", dependencies=[Depends(security._require_admin_token)])
async def admin_growth_opportunity_update(opportunity_id: str, data: GrowthOpportunityPayload) -> Dict[str, Any]:
    item = data.model_dump()
    item["stage"] = growth._growth_stage(item["stage"])
    with db._get_db_connection() as connection:
        before = connection.execute("SELECT * FROM growth_opportunities WHERE id = ?", (opportunity_id,)).fetchone()
        if not before:
            raise HTTPException(status_code=404, detail="Oportunidad no encontrada.")
        connection.execute(
            """UPDATE growth_opportunities SET company=?,campaign=?,offer=?,stage=?,value_eur=?,decision_maker=?,contact=?,
            problem=?,next_action=?,next_action_date=?,decision_date=?,notes=?,lost_reason=?,updated_at=? WHERE id=?""",
            (item["company"], item["campaign"], item["offer"], item["stage"], item["value_eur"], item["decision_maker"],
             item["contact"], item["problem"], item["next_action"], item["next_action_date"], item["decision_date"],
             item["notes"], item["lost_reason"], timeutils._utc_now_iso(), opportunity_id),
        )
        growth._growth_audit(connection, opportunity_id, "updated", {"before": dict(before), "after": item})
        connection.commit()
        row = connection.execute("SELECT * FROM growth_opportunities WHERE id = ?", (opportunity_id,)).fetchone()
    return {"ok": True, "item": growth._growth_opportunity_public(row)}


@app.delete("/admin/growth/opportunities/{opportunity_id}", dependencies=[Depends(security._require_admin_token)])
async def admin_growth_opportunity_delete(opportunity_id: str) -> Dict[str, Any]:
    with db._get_db_connection() as connection:
        row = connection.execute("SELECT * FROM growth_opportunities WHERE id = ?", (opportunity_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Oportunidad no encontrada.")
        growth._growth_audit(connection, opportunity_id, "deleted", dict(row))
        connection.execute("DELETE FROM growth_opportunities WHERE id = ?", (opportunity_id,))
        connection.commit()
    return {"ok": True}


@app.get("/admin/growth/opportunities/{opportunity_id}/history", dependencies=[Depends(security._require_admin_token)])
async def admin_growth_opportunity_history(opportunity_id: str) -> Dict[str, Any]:
    with db._get_db_connection() as connection:
        rows = connection.execute("SELECT * FROM growth_opportunity_audit WHERE opportunity_id = ? ORDER BY id DESC", (opportunity_id,)).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/admin/growth/review/generate", dependencies=[Depends(security._require_admin_token)])
async def admin_growth_review_generate(week_start: str = "") -> Dict[str, Any]:
    target = week_start or (date.today() - timedelta(days=date.today().weekday())).isoformat()
    with db._get_db_connection() as connection:
        return growth._growth_generate_review(connection, target)


@app.put("/admin/growth/review", dependencies=[Depends(security._require_admin_token)])
async def admin_growth_review_save(data: GrowthWeeklyReviewPayload) -> Dict[str, Any]:
    week_start, now = growth._growth_date(data.week_start), timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        generated = growth._growth_generate_review(connection, week_start)
        connection.execute(
            """INSERT INTO growth_weekly_reviews (week_start,generated_json,decision,notes,created_at,updated_at)
            VALUES (?,?,?,?,?,?) ON CONFLICT(week_start) DO UPDATE SET generated_json=excluded.generated_json,
            decision=excluded.decision,notes=excluded.notes,updated_at=excluded.updated_at""",
            (week_start, json.dumps(generated, ensure_ascii=False), data.decision, data.notes, now, now),
        )
        connection.commit()
    return {"ok": True, "generated": generated}


@app.put("/admin/growth/tasks", dependencies=[Depends(security._require_admin_token)])
async def admin_growth_task_save(data: GrowthPlanTaskPayload) -> Dict[str, Any]:
    if data.task_key not in {item["key"] for item in growth.GROWTH_PLAN_TASKS}:
        raise HTTPException(status_code=400, detail="Tarea del plan invalida.")
    now = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """INSERT INTO growth_plan_tasks (task_key,completed,completed_at,updated_at) VALUES (?,?,?,?)
            ON CONFLICT(task_key) DO UPDATE SET completed=excluded.completed,completed_at=excluded.completed_at,updated_at=excluded.updated_at""",
            (data.task_key, int(data.completed), now if data.completed else "", now),
        )
        connection.commit()
    return {"ok": True}


# =====================================================================
# === OUTREACH ========================================================
# Panel de captacion B2B. SQLite separado en storage/outreach/outreach.db.
# Reusa scripts/outreach_campaign.py + scripts/outreach_templates.py.
# =====================================================================


# Tracking desactivado por defecto. Requiere OUTREACH_TRACKING_ENABLED=true para activar.



















# ----- Pydantic models -----



















class OutreachAutopilotRun(BaseModel):
    days: int = 60
    limit: int = 120
    apply_status: bool = True






# ----- Stats -----

