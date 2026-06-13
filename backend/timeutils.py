"""Helpers de tiempo UTC (refactor F3).

`_utc_now` es el punto unico de "ahora" del backend: los tests lo
monkeypatchean (via el proxy de api.py) para viajar en el tiempo, asi que
cualquier codigo nuevo debe llamarlo en lugar de datetime.now(timezone.utc).
"""
from __future__ import annotations

import asyncio
from functools import partial
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from backend import settings


async def _to_thread(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Python 3.8-compatible equivalent of asyncio.to_thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _session_expires_at(hours: int = settings.PORTAL_SESSION_HOURS) -> str:
    return (_utc_now() + timedelta(hours=max(1, hours))).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _to_utc_iso(dt_value: datetime) -> str:
    return dt_value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _expires_at_in_hours(hours: int) -> str:
    safe_hours = max(1, hours)
    return (_utc_now() + timedelta(hours=safe_hours)).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _from_utc_iso(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


