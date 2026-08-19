"""Estado mutable compartido del backend (refactor F3).

Modulo HOJA: solo stdlib. Reglas de uso desde otros modulos:
- Acceso siempre cualificado: `sesiones`, `with state_lock:`.
- Mutaciones de dicts in-place bajo `state.state_lock`.
- Re-binds completos asignando al atributo del modulo
  (`CONFIG_CLIENTES = nuevo`), nunca via copia local, para que todos
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
    # Centro elegido en el flujo (negocios multi-centro con numero generico).
    location_id: str = ""
    servicio: str = ""
    # Categoria elegida cuando el negocio tiene demasiados servicios para una sola
    # lista de WhatsApp (10 filas como maximo): primero categoria, luego servicio.
    categoria: str = ""
    servicios_pagina: int = 0
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


# Config multi-tenant en memoria; poblada al importar api (transicion F3).
# Re-bind siempre via CONFIG_CLIENTES = ...
CONFIG_CLIENTES: Dict[str, Dict[str, Any]] = {}

whatsapp_flows: Dict[str, WAFlowState] = {}
# Indices RAG por cliente (valores VectorStoreIndex; Any para mantener este
# modulo libre de dependencias pesadas).
indices: Dict[str, Any] = {}
sesiones: Dict[str, SessionState] = {}
rate_limit_buckets: Dict[str, List[float]] = {}
# OTP de verificacion del asistente de voz (cancelar/reprogramar). Clave
# "cliente_id:booking_id" -> {code, expires_at, attempts, verified, channel}.
# En memoria a proposito: efimero (TTL corto), no necesita persistencia.
voice_otp: Dict[str, Dict[str, Any]] = {}
# Memoria conversacional de GESTION de citas del chat (cancelar/reprogramar por pasos
# sin repetir datos). Clave session_id -> {intent, code, telefono, email, ts}. Efimera
# (TTL corto en booking._process_booking_management_message); no se persiste.
chat_manage_state: Dict[str, Dict[str, Any]] = {}
last_cleanup_run = 0.0
state_lock = threading.RLock()

# Serializa "comprobar el hueco" + "insertar la cita". El indice unico de la BD
# cubre la MISMA hora exacta, pero no los SOLAPES parciales (un alisado de 90
# minutos a las 10:00 y un corte a las 10:30), que dependen de una comprobacion
# previa: entre comprobar e insertar cabia otra peticion y se colaban dos citas
# pisandose. La seccion protegida no hace I/O ni espera a nadie.
booking_insert_lock = threading.Lock()
booking_reminder_stop = threading.Event()
booking_reminder_thread: Optional[threading.Thread] = None
ai_rebooking_last_run = ""  # ISO del ultimo pase de rebooking IA (guard 1/dia)
outreach_imap_stop = threading.Event()
outreach_imap_thread: Optional[threading.Thread] = None
outreach_autopilot_stop = threading.Event()
outreach_autopilot_thread: Optional[threading.Thread] = None
STARTED_AT = datetime.now(timezone.utc)

# --- Observabilidad de workers de fondo (P8) ---------------------------------
# Registro central de hilos daemon arrancados en el lifespan, para poder
# inspeccionar su estado (vivo/started_at) desde GET /admin/workers sin tener
# que tocar el bucle interno de cada worker.
worker_registry: Dict[str, threading.Thread] = {}
worker_registry_lock = threading.Lock()


def register_worker(name: str, thread: threading.Thread) -> None:
    """Registra (o re-registra) un worker de fondo por nombre."""
    with worker_registry_lock:
        worker_registry[name] = thread


def worker_status() -> List[Dict[str, Any]]:
    """Estado de los workers registrados: nombre + si el hilo sigue vivo."""
    with worker_registry_lock:
        return [
            {"name": name, "alive": bool(thread and thread.is_alive())}
            for name, thread in sorted(worker_registry.items())
        ]
