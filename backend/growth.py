"""Plan de escala: metricas growth_* y revision semanal (refactor F3)."""
from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import httpx
from fastapi import BackgroundTasks, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from backports.zoneinfo import ZoneInfo

from backend import appstate, db, outreach, settings, textnorm, timeutils

GROWTH_STAGES = {
    "identificada", "contactada", "conversacion", "descubrimiento", "demo",
    "propuesta", "ganada", "perdida", "recurrente",
}


def _growth_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Fecha invalida; usa YYYY-MM-DD.") from exc


def _growth_stage(value: str) -> str:
    stage = textnorm._sanitize_text(value, allow_multiline=False).strip().lower()
    if stage not in GROWTH_STAGES:
        raise HTTPException(status_code=400, detail="Etapa de oportunidad invalida.")
    return stage


def _growth_daily_public(row: Optional[sqlite3.Row], activity_date: str) -> Dict[str, Any]:
    base: Dict[str, Any] = {"activity_date": activity_date}
    for key in (
        "researched", "contacts", "followups", "calls", "positive_replies",
        "conversations", "meetings", "proposals", "won", "new_recurring",
    ):
        base[key] = int(row[key] or 0) if row else 0
    for key in ("eur_sold", "delivery_hours"):
        base[key] = float(row[key] or 0) if row else 0.0
    for key in ("learning", "blocker", "next_action"):
        base[key] = str(row[key] or "") if row else ""
    base["created_at"] = str(row["created_at"] or "") if row else ""
    base["updated_at"] = str(row["updated_at"] or "") if row else ""
    return base


def _growth_summary(connection: sqlite3.Connection, days: int) -> Dict[str, Any]:
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    row = connection.execute(
        """
        SELECT COALESCE(SUM(researched),0) researched, COALESCE(SUM(contacts),0) contacts,
               COALESCE(SUM(followups),0) followups, COALESCE(SUM(calls),0) calls,
               COALESCE(SUM(positive_replies),0) positive_replies,
               COALESCE(SUM(conversations),0) conversations, COALESCE(SUM(meetings),0) meetings,
               COALESCE(SUM(proposals),0) proposals, COALESCE(SUM(won),0) won,
               COALESCE(SUM(eur_sold),0) eur_sold, COALESCE(SUM(new_recurring),0) new_recurring,
               COALESCE(SUM(delivery_hours),0) delivery_hours
        FROM growth_daily WHERE activity_date >= ?
        """,
        (since,),
    ).fetchone()
    result = {key: float(row[key] or 0) for key in row.keys()}
    for key in ("researched", "contacts", "followups", "calls", "positive_replies", "conversations", "meetings", "proposals", "won", "new_recurring"):
        result[key] = int(result[key])
    def rate(part: str, total: str) -> float:
        return round(result[part] * 100 / result[total], 1) if result[total] else 0.0
    result["positive_reply_rate"] = rate("positive_replies", "contacts")
    result["conversation_rate"] = rate("conversations", "contacts")
    result["meeting_rate"] = rate("meetings", "conversations")
    result["proposal_rate"] = rate("proposals", "meetings")
    result["close_rate"] = rate("won", "proposals")
    result["days"] = days
    return result


def _growth_metric_state(value: float, *, green: float, alert: float, denominator: float = 1, minimum: float = 0) -> str:
    if denominator < minimum:
        return "insufficient"
    if value >= green:
        return "green"
    if value >= alert:
        return "alert"
    return "stop"


def _growth_states(summary: Dict[str, Any]) -> Dict[str, str]:
    return {
        "positive_reply_rate": _growth_metric_state(summary["positive_reply_rate"], green=5, alert=2, denominator=summary["contacts"], minimum=100),
        "meeting_rate": _growth_metric_state(summary["meeting_rate"], green=50, alert=30, denominator=summary["conversations"], minimum=1),
        "proposal_rate": _growth_metric_state(summary["proposal_rate"], green=40, alert=20, denominator=summary["meetings"], minimum=1),
        "close_rate": _growth_metric_state(summary["close_rate"], green=25, alert=10, denominator=summary["proposals"], minimum=8),
    }


def _growth_overall_state(states: Dict[str, str]) -> str:
    values = set(states.values())
    if "stop" in values:
        return "stop"
    if "alert" in values:
        return "alert"
    if "green" in values:
        return "green"
    return "insufficient"


def _growth_opportunity_public(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row)


def _growth_generate_review(connection: sqlite3.Connection, week_start: str) -> Dict[str, Any]:
    start = date.fromisoformat(_growth_date(week_start))
    end = (start + timedelta(days=6)).isoformat()
    rows = connection.execute(
        "SELECT * FROM growth_daily WHERE activity_date BETWEEN ? AND ? ORDER BY activity_date",
        (start.isoformat(), end),
    ).fetchall()
    totals = {key: 0.0 for key in ("researched", "contacts", "followups", "calls", "positive_replies", "conversations", "meetings", "proposals", "won", "eur_sold", "new_recurring", "delivery_hours")}
    for row in rows:
        for key in totals:
            totals[key] += float(row[key] or 0)
    contacts = totals["contacts"]
    positive_rate = totals["positive_replies"] * 100 / contacts if contacts else 0
    worked = []
    missed = []
    if totals["contacts"] >= 75:
        worked.append("Se cumplio el objetivo semanal de contactos.")
    else:
        missed.append(f"Faltaron {max(0, 75-int(totals['contacts']))} contactos para el objetivo semanal.")
    if totals["conversations"] >= 6:
        worked.append("Se alcanzo el objetivo de conversaciones.")
    else:
        missed.append("No se alcanzo el objetivo de 6 conversaciones.")
    if totals["proposals"] >= 2:
        worked.append("Se alcanzo el objetivo de propuestas.")
    else:
        missed.append("No se alcanzo el objetivo de 2 propuestas.")
    if not rows:
        missed = ["No hay actividad registrada para esta semana."]
    bottleneck = "Faltan datos para identificar un cuello de botella."
    if contacts >= 20 and positive_rate < 2:
        bottleneck = "Lista o mensaje: la respuesta positiva esta por debajo del 2 %."
    elif totals["conversations"] >= 3 and totals["meetings"] / totals["conversations"] < 0.3:
        bottleneck = "Dolor o CTA: pocas conversaciones avanzan a reunion."
    elif totals["meetings"] >= 3 and totals["proposals"] / totals["meetings"] < 0.2:
        bottleneck = "Cualificacion: pocas reuniones justifican propuesta."
    elif totals["proposals"] >= 3 and totals["won"] / totals["proposals"] < 0.1:
        bottleneck = "Oferta o confianza: pocas propuestas se convierten en pago."
    priorities = [
        "Completar contactos y follow-ups antes de tareas tecnicas.",
        "Resolver todas las proximas acciones vencidas.",
        "Pedir decision en propuestas abiertas.",
        "Registrar aprendizaje y bloqueo cada dia.",
        "Cambiar una sola variable segun el cuello de botella.",
    ]
    return {
        "week_start": start.isoformat(), "week_end": end, "has_data": bool(rows),
        "worked": worked, "missed": missed, "bottleneck": bottleneck,
        "campaign_decision": "Mantener mientras no se alcance un umbral STOP; modificar una sola variable si hay alerta.",
        "priorities": priorities, "totals": totals,
    }


def _growth_audit(connection: sqlite3.Connection, opportunity_id: str, event_type: str, payload: Dict[str, Any]) -> None:
    connection.execute(
        "INSERT INTO growth_opportunity_audit (opportunity_id,event_type,payload_json,created_at) VALUES (?,?,?,?)",
        (opportunity_id, event_type, json.dumps(payload, ensure_ascii=False), timeutils._utc_now_iso()),
    )




GROWTH_ACTIVE_STAGES = GROWTH_STAGES - {"ganada", "perdida", "recurrente"}

GROWTH_STAGE_WEIGHTS = {
    "identificada": 0.05, "contactada": 0.10, "conversacion": 0.20,
    "descubrimiento": 0.35, "demo": 0.50, "propuesta": 0.75,
    "ganada": 1.0, "recurrente": 1.0, "perdida": 0.0,
}

GROWTH_PLAN_START = date(2026, 6, 8)

GROWTH_DAILY_TARGETS = {"researched": 10, "contacts": 20, "followups": 10, "calls": 3}

GROWTH_PLAN_TASKS = [
    {"key": "d1_pipeline", "label": "Día 1 · Preparar pipeline"},
    {"key": "d1_select", "label": "Día 1 · Seleccionar 20 empresas Campaña 1"},
    {"key": "d1_contact", "label": "Día 1 · Enviar 20 contactos manuales"},
    {"key": "d1_calls", "label": "Día 1 · Realizar 10 llamadas"},
    {"key": "d2_campaign1", "label": "Día 2 · Repetir Campaña 1"},
    {"key": "d3_campaign2", "label": "Día 3 · Ejecutar Campaña 2"},
    {"key": "d4_demos", "label": "Día 4 · Preparar y realizar demos"},
    {"key": "d5_proposal", "label": "Día 5 · Enviar primera propuesta"},
    {"key": "w1_review", "label": "Semana 1 · Completar dashboard y decisión"},
]

