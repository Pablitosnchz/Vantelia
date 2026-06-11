"""Estado mutable compartido del backend (refactor F3).

Modulo HOJA: solo stdlib. Reglas de uso desde otros modulos:
- Acceso siempre cualificado: `appstate.sesiones`, `with appstate.state_lock:`.
- Mutaciones de dicts in-place bajo `state.state_lock`.
- Re-binds completos asignando al atributo del modulo
  (`appstate.CONFIG_CLIENTES = nuevo`), nunca via copia local, para que todos
  los lectores (y el proxy de api.py) vean el cambio.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class SessionState:
    engine: Any
    cliente_id: str
    created_at: float
    last_seen: float
    message_count: int = 0


@dataclass
class WAFlowState:
    cliente_id: str
    from_number: str
    flow: str = ""
    servicio: str = ""
    employee_id: str = ""
    employee_name: str = ""
    fecha: str = ""
    hora: str = ""
    nombre: str = ""
    email: str = ""
    notas: str = ""
    booking_code: str = ""
    verify_phone: str = ""
    verify_email: str = ""
    greeted: bool = False
    last_seen: float = 0.0


@dataclass
class ProviderBookingResult:
    success: bool
    status: str
    provider_name: str
    provider_booking_id: str = ""
    provider_booking_url: str = ""
    message: str = ""


whatsapp_flows: Dict[str, WAFlowState] = {}
# Indices RAG por cliente (valores VectorStoreIndex; Any para mantener este
# modulo libre de dependencias pesadas).
indices: Dict[str, Any] = {}
sesiones: Dict[str, SessionState] = {}
rate_limit_buckets: Dict[str, List[float]] = {}
last_cleanup_run = 0.0
state_lock = threading.RLock()
booking_reminder_stop = threading.Event()
booking_reminder_thread: Optional[threading.Thread] = None
outreach_imap_stop = threading.Event()
outreach_imap_thread: Optional[threading.Thread] = None
outreach_autopilot_stop = threading.Event()
outreach_autopilot_thread: Optional[threading.Thread] = None
STARTED_AT = datetime.now(timezone.utc)
