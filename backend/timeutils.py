"""Helpers de tiempo UTC (refactor F3).

`_utc_now` es el punto unico de "ahora" del backend: los tests lo
monkeypatchean (via el proxy de api.py) para viajar en el tiempo, asi que
cualquier codigo nuevo debe llamarlo en lugar de datetime.now(timezone.utc).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend import settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _session_expires_at(hours: int = settings.PORTAL_SESSION_HOURS) -> str:
    return (_utc_now() + timedelta(hours=max(1, hours))).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _to_utc_iso(dt_value: datetime) -> str:
    return dt_value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
