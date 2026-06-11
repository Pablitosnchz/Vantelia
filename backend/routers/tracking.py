"""Endpoints: seccion tracking (refactor F3).

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
from backend.outreach import outreach_verify_token  # noqa: F401
from backend.main import app

@app.get("/track/open/{token}.gif", include_in_schema=False)
def outreach_track_open(token: str, request: Request):
    if not outreach.OUTREACH_AVAILABLE or not outreach.OUTREACH_TRACKING_SECRET:
        return Response(content=outreach.OUTREACH_PIXEL_GIF, media_type="image/gif")
    parsed = outreach_verify_token(token, outreach.OUTREACH_TRACKING_SECRET)
    if parsed:
        email, stage = parsed
        try:
            with outreach._outreach_db() as conn:
                conn.execute(
                    "INSERT INTO events (email, type, stage, ts, ua, ip) VALUES (?,?,?,?,?,?)",
                    (email, "open", stage, outreach._outreach_now(),
                     request.headers.get("user-agent", "")[:300],
                     (request.client.host if request.client else "")[:64]),
                )
                conn.commit()
        except Exception:
            settings.logger.exception("Outreach open track error")
    return Response(
        content=outreach.OUTREACH_PIXEL_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/track/click/{token}", include_in_schema=False)
def outreach_track_click(token: str, request: Request, u: str = ""):
    if not outreach.OUTREACH_AVAILABLE or not outreach.OUTREACH_TRACKING_SECRET:
        if u:
            return RedirectResponse(url=u, status_code=302)
        raise HTTPException(status_code=404, detail="not found")
    parsed = outreach_verify_token(token, outreach.OUTREACH_TRACKING_SECRET)
    if not parsed or not u:
        raise HTTPException(status_code=404, detail="not found")
    target = u
    try:
        host = urlparse(target).hostname or ""
    except Exception:
        host = ""
    if host and host.lower() not in outreach.OUTREACH_TRACKING_ALLOWED_HOSTS:
        # Permitir solo dominios propios para evitar open redirect.
        target = "https://www.vantelia.es"
    email, stage = parsed
    try:
        with outreach._outreach_db() as conn:
            conn.execute(
                "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,?,?)",
                (email, "click", stage, target[:500], outreach._outreach_now(),
                 request.headers.get("user-agent", "")[:300],
                 (request.client.host if request.client else "")[:64]),
            )
            conn.commit()
    except Exception:
        settings.logger.exception("Outreach click track error")
    return RedirectResponse(url=target, status_code=302)


@app.get("/track/reply/{token}", include_in_schema=False)
def outreach_track_reply_intent(token: str, request: Request, u: str = ""):
    if not u.lower().startswith("mailto:"):
        raise HTTPException(status_code=404, detail="not found")
    if not outreach.OUTREACH_AVAILABLE or not outreach.OUTREACH_TRACKING_SECRET:
        return RedirectResponse(url=u, status_code=302)
    parsed = outreach_verify_token(token, outreach.OUTREACH_TRACKING_SECRET)
    if not parsed:
        raise HTTPException(status_code=404, detail="not found")
    email, stage = parsed
    try:
        with outreach._outreach_db() as conn:
            conn.execute(
                "INSERT INTO events (email, type, stage, url, ts, ua, ip) VALUES (?,?,?,?,?,?,?)",
                (email, "reply_intent", stage, u[:500], outreach._outreach_now(),
                 request.headers.get("user-agent", "")[:300],
                 (request.client.host if request.client else "")[:64]),
            )
            conn.execute(
                """UPDATE prospects SET status='engaged', updated_at=?
                   WHERE email=? AND status IN ('new','contacted')""",
                (outreach._outreach_now(), email),
            )
            conn.commit()
    except Exception:
        settings.logger.exception("Outreach reply intent track error")
    return RedirectResponse(url=u, status_code=302)




