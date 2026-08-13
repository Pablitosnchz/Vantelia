#!/usr/bin/env python3
"""Provisioning del tenant `aliciarincon` (Alicia Rincon Estilistas, Elche).

Deja el negocio listo para operar de verdad: usuario de portal (owner, plan
business), centro con la direccion real, equipo con el HORARIO REAL por dia de la
semana (lunes cerrado, mar-mie 10:00-18:30, jue-vie 10:00-20:30, sab 09:00-14:00)
y catalogo de servicios sembrado desde data/aliciarincon/info.txt.

Idempotente: se puede volver a lanzar; purga lo que sembro antes y lo recrea.
NO toca otros tenants ni borra citas que no haya creado este script.

Uso:
    python scripts/seed_aliciarincon.py
    python scripts/seed_aliciarincon.py --purge          # solo limpiar
    python scripts/seed_aliciarincon.py --with-agenda    # + citas de ejemplo
"""
from __future__ import annotations

import argparse
import random
import secrets
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import api  # noqa: E402  (carga config/storage reales)
from backend import textnorm  # noqa: E402
from api_models import (  # noqa: E402
    PortalEmployeePayload,
    PortalLocationPayload,
)

CID = "aliciarincon"
PORTAL_EMAIL = "info@aliciarinconestilistas.com"
PORTAL_PASSWORD = "AliciaRincon2026"
PORTAL_NAME = "Alicia Rincon Estilistas"

RNG = random.Random(20260813)

# Horario REAL publicado en aliciarinconestilistas.com (lunes=0 .. domingo=6).
WEEKLY_HOURS = {
    "0": {"closed": True},
    "1": {"start": "10:00", "end": "18:30"},
    "2": {"start": "10:00", "end": "18:30"},
    "3": {"start": "10:00", "end": "20:30"},
    "4": {"start": "10:00", "end": "20:30"},
    "5": {"start": "09:00", "end": "14:00"},
    "6": {"closed": True},
}

CENTRO = {
    "name": "Alicia Rincon Estilistas",
    "address": "Andreu Castillejos, 9 - 03201 Elche (Alicante)",
    "phone": "625 120 100",
}

# El salon muestra 6 profesionales en su web pero solo publica el nombre de
# Alicia. Los demas quedan como plazas nombradas para que el negocio las renombre
# desde el portal en 10 segundos (Equipo -> editar profesional).
EQUIPO = [
    {"name": "Alicia Rincon", "role_label": "Fundadora y directora creativa", "color": "#111111"},
    {"name": "Estilista 2", "role_label": "Estilista", "color": "#c9737d"},
    {"name": "Estilista 3", "role_label": "Estilista", "color": "#8e7dff"},
    {"name": "Estilista 4", "role_label": "Estilista", "color": "#6f8272"},
    {"name": "Estilista 5", "role_label": "Estilista", "color": "#b08968"},
    {"name": "Estilista 6", "role_label": "Estilista", "color": "#5dade2"},
]

CLIENTAS_DEMO = [
    ("Marta Sempere", "marta.sempere@example.com", "600110301"),
    ("Rosa Antón", "rosa.anton@example.com", "600110302"),
    ("Nuria Vicedo", "nuria.vicedo@example.com", "600110303"),
    ("Isabel Poveda", "isabel.poveda@example.com", "600110304"),
    ("Cristina Mas", "cristina.mas@example.com", "600110305"),
    ("Pilar Agulló", "pilar.agullo@example.com", "600110306"),
    ("Elena Quiles", "elena.quiles@example.com", "600110307"),
    ("Mavi Serrano", "mavi.serrano@example.com", "600110308"),
]


def purge() -> None:
    with sqlite3.connect(api.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE cliente_id=? AND source='seed_demo'", (CID,))
        conn.execute("DELETE FROM employees WHERE cliente_id=? AND is_default=0", (CID,))
        conn.execute("DELETE FROM locations WHERE cliente_id=? AND is_default=0", (CID,))
        conn.commit()
    print("· Purga previa completada.")


def ensure_portal_user() -> None:
    existing = api._get_user_by_email(PORTAL_EMAIL)
    if existing:
        with sqlite3.connect(api.DB_PATH) as conn:
            conn.execute(
                "UPDATE users SET password_hash=?, role='client', cliente_id=?, portal_role='owner', "
                "is_active=1, display_name=? WHERE id=?",
                (api._hash_secret(PORTAL_PASSWORD), CID, PORTAL_NAME, existing["id"]),
            )
            conn.commit()
        user_id = existing["id"]
        print(f"· Usuario portal actualizado: {PORTAL_EMAIL}")
    else:
        created = api._create_user(
            email=PORTAL_EMAIL,
            password=PORTAL_PASSWORD,
            role="client",
            display_name=PORTAL_NAME,
            cliente_id=CID,
            portal_role="owner",
        )
        user_id = created["id"] if isinstance(created, dict) else created["id"]
        print(f"· Usuario portal creado: {PORTAL_EMAIL}")
    # Propietario del tenant + plan business (voz, WhatsApp, informes...).
    api.db_set_client_owner(CID, user_id, source="seed_aliciarincon")
    api.db_set_subscription_from_stripe(user_id=user_id, plan_slug="business", status="active")
    print("· Plan business asignado.")


def setup_centro() -> str:
    default_id = api._default_location_id(CID)
    payload = PortalLocationPayload(
        name=CENTRO["name"], address=CENTRO["address"], phone=CENTRO["phone"],
        timezone="Europe/Madrid", is_active=True,
    )
    if default_id:
        api._update_portal_location(CID, default_id, payload)
        location_id = default_id
    else:
        location_id = api._create_portal_location(CID, payload).location_id
    print(f"· Centro configurado: {CENTRO['name']}")
    return location_id


def setup_equipo(location_id: str) -> None:
    for miembro in EQUIPO:
        api._create_portal_employee(
            CID,
            PortalEmployeePayload(
                name=miembro["name"],
                role_label=miembro["role_label"],
                color=miembro["color"],
                is_active=True,
                location_id=location_id,
                service_ids=[],          # todas las profesionales atienden todo el catalogo
                day_start="09:00",       # envolvente; manda weekly_hours
                day_end="20:30",
                slot_minutes=30,
                closed_weekdays=[0, 6],
                weekly_hours=WEEKLY_HOURS,
            ),
            full_access=True,
        )
    print(f"· {len(EQUIPO)} profesionales creados con horario real por dia.")


def align_default_employee() -> None:
    """La agenda 'general' (empleado default) tambien debe respetar el horario real."""
    row = api._default_employee_row(CID)
    if not row:
        return
    with sqlite3.connect(api.DB_PATH) as conn:
        conn.execute(
            "UPDATE employees SET day_start='09:00', day_end='20:30', closed_weekdays_json=?, "
            "weekly_hours_json=?, timezone='Europe/Madrid' WHERE id=?",
            (api.json.dumps([0, 6]), api.json.dumps(WEEKLY_HOURS), row["id"]),
        )
        conn.commit()
    print("· Agenda general alineada con el horario real.")


def seed_agenda(location_id: str) -> None:
    services = api._catalog_services(CID, include_inactive=False)
    if not services:
        print("AVISO: catalogo vacio, sin agenda de ejemplo.", file=sys.stderr)
        return
    employees = [r for r in api._list_employee_rows(CID, include_inactive=False) if not r["is_default"]]
    today = api._utc_now().date()
    created = 0
    used = set()
    for offset in range(-14, 12):
        day = today + timedelta(days=offset)
        window = textnorm._weekday_hours(
            {"day_start": "09:00", "day_end": "20:30", "closed_weekdays": [0, 6], "weekly_hours": WEEKLY_HOURS},
            day.weekday(),
        )
        if window is None:
            continue
        horas = [h for h in ("10:00", "11:30", "13:00", "16:00", "17:30") if window[0] <= h < window[1]]
        for emp in employees:
            if RNG.random() > 0.4:
                continue
            for hora in RNG.sample(horas, k=min(len(horas), RNG.randint(1, 2))):
                key = (emp["id"], day.isoformat(), hora)
                if key in used:
                    continue
                used.add(key)
                svc = RNG.choice(services)
                dur = int(svc.get("duration_minutes") or 60)
                cliente = RNG.choice(CLIENTAS_DEMO)
                status = ("no_show" if RNG.random() < 0.08 else "completed") if offset < 0 else "confirmed"
                bid = f"bk_{secrets.token_urlsafe(8)}"
                start_local, end_local = api._booking_start_end(
                    CID, day.isoformat(), hora, employee_id=emp["id"], duration_minutes=dur
                )
                api._store_booking({
                    "id": bid, "cliente_id": CID, "employee_id": emp["id"], "employee_name": emp["name"],
                    "nombre": cliente[0], "email": cliente[1], "telefono": cliente[2],
                    "servicio": svc["nombre"], "booking_date": day.isoformat(), "booking_time": hora,
                    "notas": "", "status": status, "provider_name": "internal", "provider_status": "internal",
                    "provider_booking_id": "", "provider_booking_url": "", "manage_token": f"mg_{bid}",
                    "timezone": "Europe/Madrid", "start_at": api._to_utc_iso(start_local),
                    "end_at": api._to_utc_iso(end_local), "confirmed_at": api._to_utc_iso(start_local),
                    "cancelled_at": "", "rescheduled_at": "", "rescheduled_from_booking_id": "",
                    "confirmation_email_sent_at": "", "reminder_24h_sent_at": "", "reminder_2h_sent_at": "",
                    "customer_email_status": "", "customer_email_last_error": "",
                    "service_id": svc["id"], "service_price_cents": 0,
                    "completed_source": "manual" if status in ("completed", "no_show") else "",
                    "source": "seed_demo", "created_at": api._to_utc_iso(start_local),
                })
                created += 1
    print(f"· Agenda de ejemplo: {created} citas (-14 a +11 dias).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--purge", action="store_true", help="Solo limpiar")
    parser.add_argument("--with-agenda", action="store_true", help="Sembrar citas de ejemplo")
    args = parser.parse_args()

    if CID not in api.CONFIG_CLIENTES:
        print(f"ERROR: el tenant '{CID}' no existe en config.json", file=sys.stderr)
        sys.exit(1)

    print(f"== Provisioning {CID} ==")
    purge()
    if args.purge:
        return

    ensure_portal_user()
    api._ensure_services_seeded(CID)
    services = api._catalog_services(CID, include_inactive=False)
    print(f"· Catalogo: {len(services)} servicios sembrados desde info.txt.")
    location_id = setup_centro()
    setup_equipo(location_id)
    align_default_employee()
    if args.with_agenda:
        seed_agenda(location_id)

    print("\n== LISTO ==")
    print(f"  Portal     : /acceso")
    print(f"  Usuario    : {PORTAL_EMAIL}")
    print(f"  Contrasena : {PORTAL_PASSWORD}")
    print(f"  Central    : /central/{CID}")
    print(f"  Web        : /site/aliciarincon/")
    for svc in services:
        print(f"    - {svc['nombre']} ({svc.get('duration_minutes')} min)")


if __name__ == "__main__":
    main()
