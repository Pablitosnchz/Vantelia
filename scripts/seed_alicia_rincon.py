#!/usr/bin/env python3
"""Provisioning del tenant `alicia_rincon_estilistas` (Alicia Rincon Estilistas, Elche).

Deja el negocio listo para operar de verdad: usuario de portal (owner, plan
business), centro con la direccion real, equipo con el HORARIO REAL por dia de la
semana (lunes cerrado, mar-mie 10:00-18:30, jue-vie 10:00-20:30, sab 09:00-14:00)
y catalogo de servicios sembrado desde data/alicia_rincon_estilistas/info.txt.

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
    GiftCardIssuePayload,
    PackagePayload,
    PackageSellPayload,
    PortalEmployeePayload,
    PortalLocationPayload,
    ProductPayload,
    ProductSalePayload,
)

CID = "alicia_rincon_estilistas"
PORTAL_EMAIL = "aliciarinconweb@gmail.com"  # cuenta que la duenya se creo ella misma
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

# Venta en salon: productos tipicos de una peluqueria colorista.
PRODUCTOS = [
    {"name": "Champu sin sulfatos 300ml", "price_cents": 2200, "stock": 24},
    {"name": "Mascarilla reconstructora 250ml", "price_cents": 2800, "stock": 18},
    {"name": "Protector termico 200ml", "price_cents": 1900, "stock": 20},
    {"name": "Aceite de acabado 100ml", "price_cents": 2400, "stock": 15},
    {"name": "Champu matizador violeta 300ml", "price_cents": 2500, "stock": 12},
]

# Bonos: lo que mas encaja en color y mantenimiento.
BONOS = [
    {"name": "Bono 3 mantenimientos de color", "servicio": "coloracion_personalizada", "qty": 3,
     "price_cents": 14000, "validity_days": 365},
    {"name": "Bono 5 tratamientos capilares", "servicio": "tratamiento_capilar", "qty": 5,
     "price_cents": 16000, "validity_days": 365},
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
        # Comercio de ejemplo (productos, bonos y tarjetas): lo siembra este script
        # entero, asi que se limpia entero antes de volver a crearlo.
        for tabla in ("product_sales", "products", "package_purchases", "packages",
                      "gift_card_transactions", "gift_cards"):
            conn.execute(f"DELETE FROM {tabla} WHERE cliente_id=?", (CID,))
        conn.commit()
    print("· Purga previa completada.")


def ensure_portal_user() -> None:
    """La cuenta la creo la duenya (self-serve). NO se toca su contrasenya: solo se
    confirma que es la propietaria del tenant y se le deja el plan del piloto."""
    user = api._get_user_by_email(PORTAL_EMAIL)
    if not user:
        print(f"ERROR: no existe el usuario {PORTAL_EMAIL} en este entorno.", file=sys.stderr)
        sys.exit(1)
    if (user["cliente_id"] or "") != CID:
        with sqlite3.connect(api.DB_PATH) as conn:
            conn.execute("UPDATE users SET cliente_id=?, portal_role='owner', is_active=1 WHERE id=?", (CID, user["id"]))
            conn.commit()
    api.db_set_client_owner(CID, user["id"], source="seed_alicia_rincon")
    api.db_set_subscription_from_stripe(user_id=user["id"], plan_slug="business", status="active")
    print(f"· Cuenta de la duenya lista: {PORTAL_EMAIL} (owner, plan business). Contrasenya intacta.")


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
        # Solo horas en las que el servicio cabe ENTERO antes del cierre de ese dia.
        def _min(hhmm):
            h, m = hhmm.split(":")
            return int(h) * 60 + int(m)

        cierre = _min(window[1])
        horas_dia = [h for h in ("09:00", "10:00", "11:30", "13:00", "16:00", "17:30") if _min(window[0]) <= _min(h)]
        for emp in employees:
            if RNG.random() > 0.4:
                continue
            for hora in RNG.sample(horas_dia, k=min(len(horas_dia), RNG.randint(1, 2))):
                key = (emp["id"], day.isoformat(), hora)
                if key in used:
                    continue
                svc = RNG.choice(services)
                dur = int(svc.get("duration_minutes") or 60)
                if _min(hora) + dur > cierre:
                    continue  # el servicio no cabe antes del cierre de ese dia
                used.add(key)
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


def setup_comercio() -> None:
    for p in PRODUCTOS:
        api._create_product(CID, ProductPayload(name=p["name"], price_cents=p["price_cents"], stock=p["stock"], is_active=True))
    prods = api._list_products(CID)
    for prod in prods[:3]:
        cliente = RNG.choice(CLIENTAS_DEMO)
        api._sell_product(CID, prod["id"], ProductSalePayload(qty=RNG.randint(1, 2), payment_method="card", customer_name=cliente[0]))
    slugs = {s["id"] for s in api._catalog_services(CID, include_inactive=False)}
    creados = 0
    for bono in BONOS:
        if bono["servicio"] not in slugs:
            continue
        api._create_package(CID, PackagePayload(
            name=bono["name"], items=[{"service_slug": bono["servicio"], "qty": bono["qty"]}],
            price_cents=bono["price_cents"], validity_days=bono["validity_days"], is_active=True))
        creados += 1
    paquetes = api._list_packages(CID)
    if paquetes:
        cliente = CLIENTAS_DEMO[0]
        api._sell_package(CID, paquetes[0]["id"], PackageSellPayload(
            buyer_name=cliente[0], buyer_email=cliente[1], payment_method="card"))
    api._issue_gift_card(CID, GiftCardIssuePayload(
        amount_cents=6000, buyer_name="Rosa Antón", recipient_name="Marta Sempere", validity_days=365))
    vendidos = len(api._list_package_purchases(CID)) if hasattr(api, "_list_package_purchases") else (1 if paquetes else 0)
    print(f"· Comercio: {len(PRODUCTOS)} productos (3 vendidos), {creados} bonos ({vendidos} vendido/s), 1 tarjeta regalo.")


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
    setup_comercio()
    if args.with_agenda:
        seed_agenda(location_id)

    print("\n== LISTO ==")
    print(f"  Portal     : /acceso")
    print(f"  Usuario    : {PORTAL_EMAIL} (contrasenya suya)")
    print(f"  Central    : /central/{CID}")
    print(f"  Web        : /site/aliciarincon/")
    for svc in services:
        print(f"    - {svc['nombre']} ({svc.get('duration_minutes')} min)")


if __name__ == "__main__":
    main()
