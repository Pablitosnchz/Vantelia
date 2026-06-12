"""Captacion WhatsApp Web (Playwright, single-touch) (refactor F3)."""
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

from backend import appstate, db, outreach, security, settings, textnorm, timeutils

try:
    import whatsapp_outreach as wa_outreach  # type: ignore
    WA_AVAILABLE = True
except Exception as _wa_err:  # noqa: BLE001
    settings.logger.warning(f"Modulo whatsapp_outreach no disponible: {_wa_err}")
    wa_outreach = None  # type: ignore
    WA_AVAILABLE = False

_wa_login_lock = threading.Lock()
_wa_login_state: Dict[str, Any] = {"running": False, "result": None, "status": ""}
_wa_send_job_lock = threading.Lock()
_wa_send_state: Dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "requested": 0,
    "queued": 0,
    "candidates": 0,
    "attempted": 0,
    "sent": 0,
    "skipped": 0,
    "current_phone": "",
    "last_reason": "",
    "dry_run": False,
    "started_at": "",
    "finished_at": "",
}

_wa_send_lock = threading.Lock()


def _whatsapp_db():
    if not WA_AVAILABLE:
        raise HTTPException(503, "Modulo whatsapp no disponible.")
    return wa_outreach.connect()


def _wa_autosend_enabled() -> bool:
    try:
        from whatsapp_autosend import is_autosend_enabled  # type: ignore
        return is_autosend_enabled()
    except Exception:
        return False


def _wa_session_info() -> Dict[str, Any]:
    try:
        from whatsapp_autosend import session_info  # type: ignore
        return session_info()
    except Exception:
        return {"connected": False}


def _wa_send_progress() -> Dict[str, Any]:
    with _wa_send_lock:
        progress = dict(_wa_send_state)
    total = int(progress.get("requested") or progress.get("queued") or 0)
    done = int(progress.get("sent") or 0)
    progress["total"] = total
    progress["done"] = done
    progress["percent"] = int(round((done / total) * 100)) if total else (100 if progress.get("phase") == "done" else 0)
    return progress


