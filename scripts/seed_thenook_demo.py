"""Seeder de datos de demostracion para el tenant `thenook`.

Monta un entorno COMPLETO y realista para pruebas manuales / entrega a cliente:
usuario de portal (owner), 3 centros, masajistas por centro, catalogo de
servicios con precios por centro, salas, productos, bonos, tarjetas regalo y una
agenda con citas pasadas (asistencia + pagos) y futuras (sin colisiones).

Idempotente: purga lo que sembro antes (bookings source='seed_demo', empleados y
centros no-default, comercio) y lo vuelve a crear desde cero. NO toca otros tenants.

Uso:
    python scripts/seed_thenook_demo.py
    python scripts/seed_thenook_demo.py --purge   # solo limpiar

Imprime al final el usuario/clave para entrar en /acceso.
"""
from __future__ import annotations

import argparse
import random
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import api  # noqa: E402  (carga config/storage reales locales)
from api_models import (  # noqa: E402
    GiftCardIssuePayload,
    PackagePayload,
    PackageSellPayload,
    PortalEmployeePayload,
    PortalLocationPayload,
    PortalResourcePayload,
    ProductPayload,
    ServiceLocationOverridePayload,
)

CID = "thenook"
PORTAL_EMAIL = "demo@thenook.es"
PORTAL_PASSWORD = "TheNookDemo2025!"

RNG = random.Random(20260613)

CENTROS = [
    {"name": "The Nook Zurbarán", "address": "C/ Zurbarán 10, Madrid", "phone": "910 481 474",
     "rooms": ["Sala Zen", "Sala Aroma", "Sala Bambú"],
     "staff": ["Lucía Fernández", "Marco Rossi", "Elena Prieto"]},
    {"name": "The Nook Príncipe de Vergara", "address": "C/ Príncipe de Vergara 204, Madrid", "phone": "910 000 102",
     "rooms": ["Sala Loto", "Sala Jade"],
     "staff": ["David Soto", "Nadia Karim"]},
    {"name": "The Nook Goya", "address": "C/ Goya 47, Madrid", "phone": "910 000 103",
     "rooms": ["Sala Coral", "Sala Ámbar"],
     "staff": ["Paula Gómez", "Hugo Martín"]},
]

EMP_COLORS = ["#00b1d9", "#8e7dff", "#2ecc71", "#f4b400", "#ff8a65", "#e74c3c", "#5dade2", "#16a085"]

PRODUCTOS = [
    {"name": "Aceite esencial lavanda 100ml", "price_cents": 1800, "stock": 40},
    {"name": "Vela aromática relax", "price_cents": 1500, "stock": 25},
    {"name": "Crema corporal karité", "price_cents": 2200, "stock": 30},
    {"name": "Set bienestar (aceite + vela)", "price_cents": 3000, "stock": 15},
]

GIFT_CARDS = [
    {"amount_cents": 6000, "buyer_name": "Carmen Ortiz", "recipient_name": "Sofía Ortiz"},
    {"amount_cents": 10000, "buyer_name": "Acme SL", "recipient_name": "Equipo Acme"},
]

CLIENTES_DEMO = [
    ("Ana López", "ana.lopez@example.com", "600111201"),
    ("Javier Ruiz", "javier.ruiz@example.com", "600111202"),
    ("María Sanz", "maria.sanz@example.com", "600111203"),
    ("Pedro Gil", "pedro.gil@example.com", "600111204"),
    ("Laura Vega", "laura.vega@example.com", "600111205"),
    ("Carlos Mora", "carlos.mora@example.com", "600111206"),
    ("Nuria Díaz", "nuria.diaz@example.com", "600111207"),
    ("Sergio Peña", "sergio.pena@example.com", "600111208"),
    ("Elena Cano", "elena.cano@example.com", "600111209"),
    ("Raúl Ibáñez", "raul.ibanez@example.com", "600111210"),
]

SLOT_TIMES = ["10:00", "11:30", "13:00", "16:00", "17:30"]


def purge() -> None:
    with sqlite3.connect(api.DB_PATH) as conn:
        conn.execute("DELETE FROM bookings WHERE cliente_id=? AND source='seed_demo'", (CID,))
        conn.execute("DELETE FROM product_sales WHERE cliente_id=?", (CID,))
        conn.execute("DELETE FROM products WHERE cliente_id=?", (CID,))
        conn.execute("DELETE FROM package_purchases WHERE cliente_id=?", (CID,))
        conn.execute("DELETE FROM packages WHERE cliente_id=?", (CID,))
        conn.execute("DELETE FROM gift_card_transactions WHERE cliente_id=?", (CID,))
        conn.execute("DELETE FROM gift_cards WHERE cliente_id=?", (CID,))
        conn.execute("DELETE FROM resources WHERE cliente_id=?", (CID,))
        conn.execute("DELETE FROM service_location_overrides WHERE cliente_id=?", (CID,))
        conn.execute("DELETE FROM employees WHERE cliente_id=? AND is_default=0", (CID,))
        conn.execute("DELETE FROM locations WHERE cliente_id=? AND is_default=0", (CID,))
        conn.commit()
    print("· Purga completada (datos seed previos eliminados).")


def ensure_portal_user() -> None:
    existing = api._get_user_by_email(PORTAL_EMAIL)
    if existing:
        with sqlite3.connect(api.DB_PATH) as conn:
            conn.execute(
                "UPDATE users SET password_hash=?, role='client', cliente_id=?, portal_role='owner', is_active=1, display_name=? WHERE id=?",
                (api._hash_secret(PORTAL_PASSWORD), CID, "The Nook (demo)", existing["id"]),
            )
            conn.commit()
        print(f"· Usuario portal actualizado: {PORTAL_EMAIL}")
    else:
        api._create_user(
            email=PORTAL_EMAIL, password=PORTAL_PASSWORD, role="client",
            display_name="The Nook (demo)", cliente_id=CID, portal_role="owner",
        )
        print(f"· Usuario portal creado: {PORTAL_EMAIL}")


def setup_centros() -> list:
    default_id = api._default_location_id(CID)
    location_ids = []
    for idx, centro in enumerate(CENTROS):
        payload = PortalLocationPayload(
            name=centro["name"], address=centro["address"], phone=centro["phone"],
            timezone="Europe/Madrid", is_active=True,
        )
        if idx == 0 and default_id:
            api._update_portal_location(CID, default_id, payload)
            location_ids.append(default_id)
        else:
            location_ids.append(api._create_portal_location(CID, payload).location_id)
        for room in centro["rooms"]:
            api._create_portal_resource(CID, location_ids[idx], PortalResourcePayload(name=room, is_active=True))
    print(f"· {len(location_ids)} centros + salas configurados.")
    return location_ids


def setup_employees(location_ids: list) -> None:
    color_i = 0
    for idx, centro in enumerate(CENTROS):
        for name in centro["staff"]:
            # Cada masajista atiende todos los servicios (service_ids vacio).
            api._create_portal_employee(
                CID,
                PortalEmployeePayload(
                    name=name, role_label="Masajista", color=EMP_COLORS[color_i % len(EMP_COLORS)],
                    is_active=True, location_id=location_ids[idx], service_ids=[],
                    day_start="10:00", day_end="19:00", slot_minutes=30, closed_weekdays=[6],
                ),
                full_access=True,
            )
            color_i += 1
    print(f"· {sum(len(c['staff']) for c in CENTROS)} masajistas creados.")


def setup_service_overrides(location_ids: list, services: list) -> None:
    # Demostrar precios por centro: Goya (idx 2) sube un par de servicios.
    goya = location_ids[2]
    bumped = 0
    for svc in services[:2]:
        base = int(svc["price_cents"] or 0)
        api._set_service_location_override(
            CID, svc["id"], goya,
            ServiceLocationOverridePayload(is_available=True, price_cents=base + 1000),
        )
        bumped += 1
    print(f"· {bumped} overrides de precio por centro (Goya +10€).")


def setup_commerce() -> None:
    for p in PRODUCTOS:
        api._create_product(CID, ProductPayload(name=p["name"], price_cents=p["price_cents"], stock=p["stock"], is_active=True))
    # Vender algunos productos (ingresos en Informes).
    prods = api._list_products(CID)
    for prod in prods[:3]:
        from api_models import ProductSalePayload
        api._sell_product(CID, prod["id"], ProductSalePayload(qty=RNG.randint(1, 3), payment_method="card",
                                                              customer_name=RNG.choice(CLIENTES_DEMO)[0]))
    # Bonos.
    svcs = api._list_service_rows(CID)
    if svcs:
        slug = svcs[0]["slug"]
        api._create_package(CID, PackagePayload(name="Bono 5 sesiones (-12%)",
                                                items=[{"service_slug": slug, "qty": 5}],
                                                price_cents=26400, validity_days=180, is_active=True))
        api._create_package(CID, PackagePayload(name="Bono 10 sesiones (-15%)",
                                                items=[{"service_slug": slug, "qty": 10}],
                                                price_cents=51000, validity_days=365, is_active=True))
        pkgs = api._list_packages(CID)
        if pkgs:
            api._sell_package(CID, pkgs[0]["id"], PackageSellPayload(
                buyer_name="Ana López", buyer_email="ana.lopez@example.com", payment_method="card"))
    # Tarjetas regalo.
    for g in GIFT_CARDS:
        api._issue_gift_card(CID, GiftCardIssuePayload(amount_cents=g["amount_cents"], buyer_name=g["buyer_name"],
                                                       recipient_name=g["recipient_name"], validity_days=365))
    print(f"· Comercio: {len(PRODUCTOS)} productos, 2 bonos, {len(GIFT_CARDS)} tarjetas regalo.")


def seed_agenda(location_ids: list, services: list) -> None:
    today = api._utc_now().date()
    employees_by_loc = {
        loc: [r for r in api._list_employee_rows(CID, location_id=loc, include_inactive=False) if not r["is_default"]]
        for loc in location_ids
    }
    used = set()  # (employee_id, date, time)
    created = 0
    paid_ids = []
    for day_offset in range(-28, 15):
        day = today + timedelta(days=day_offset)
        if day.weekday() == 6:  # domingo cerrado
            continue
        is_past = day_offset < 0
        for loc in location_ids:
            for emp in employees_by_loc[loc]:
                # densidad: ~45% de los dias este masajista tiene huecos ocupados
                if RNG.random() > 0.45:
                    continue
                for hora in RNG.sample(SLOT_TIMES, k=RNG.randint(1, 3)):
                    key = (emp["id"], day.isoformat(), hora)
                    if key in used:
                        continue
                    used.add(key)
                    svc = RNG.choice(services)
                    dur = int(svc.get("duration_minutes") or 60)
                    price = api._service_price_cents_resolved(CID, api._get_service_row(CID, svc["id"]), loc)
                    cliente = RNG.choice(CLIENTES_DEMO)
                    if is_past:
                        status = "no_show" if RNG.random() < 0.12 else "completed"
                    else:
                        status = "confirmed"
                    bid = f"bk_{secrets.token_urlsafe(8)}"
                    start_local, end_local = api._booking_start_end(
                        CID, day.isoformat(), hora, employee_id=emp["id"], duration_minutes=dur)
                    record = {
                        "id": bid, "cliente_id": CID, "employee_id": emp["id"], "employee_name": emp["name"],
                        "nombre": cliente[0], "email": cliente[1], "telefono": cliente[2],
                        "servicio": svc["nombre"], "booking_date": day.isoformat(), "booking_time": hora,
                        "notas": "", "status": status, "provider_name": "internal", "provider_status": "internal",
                        "provider_booking_id": "", "provider_booking_url": "", "manage_token": f"mg_{bid}",
                        "timezone": "Europe/Madrid", "start_at": api._to_utc_iso(start_local),
                        "end_at": api._to_utc_iso(end_local),
                        "confirmed_at": api._to_utc_iso(start_local), "cancelled_at": "",
                        "rescheduled_at": "", "rescheduled_from_booking_id": "", "confirmation_email_sent_at": "",
                        "reminder_24h_sent_at": "", "reminder_2h_sent_at": "", "customer_email_status": "",
                        "customer_email_last_error": "", "service_id": svc["id"], "service_price_cents": price,
                        "completed_source": "manual" if status in ("completed", "no_show") else "",
                        "source": "seed_demo", "created_at": api._to_utc_iso(start_local),
                    }
                    api._store_booking(record)
                    # Pago: las realizadas pagan ~88%; algunas futuras tambien prepagan.
                    if (status == "completed" and RNG.random() < 0.88) or (status == "confirmed" and RNG.random() < 0.25):
                        paid_ids.append(bid)
                    created += 1
    if paid_ids:
        with sqlite3.connect(api.DB_PATH) as conn:
            conn.executemany("UPDATE bookings SET payment_status='paid' WHERE id=?", [(b,) for b in paid_ids])
            conn.commit()
    print(f"· Agenda: {created} citas ({len(paid_ids)} pagadas) repartidas en 3 centros, -28 a +14 dias.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--purge", action="store_true", help="Solo limpiar datos seed")
    args = parser.parse_args()

    if CID not in api.CONFIG_CLIENTES:
        print(f"ERROR: el tenant '{CID}' no existe en config.json", file=sys.stderr)
        sys.exit(1)

    print(f"== Seed demo The Nook ({CID}) ==")
    purge()
    if args.purge:
        print("Purga only. Hecho.")
        return

    ensure_portal_user()
    api._ensure_services_seeded(CID)
    services = api._catalog_services(CID, include_inactive=False)
    if not services:
        print("AVISO: sin servicios en el catalogo; revisar data/thenook/info.txt", file=sys.stderr)
    location_ids = setup_centros()
    setup_employees(location_ids)
    if services:
        setup_service_overrides(location_ids, services)
    setup_commerce()
    if services:
        seed_agenda(location_ids, services)

    print("\n== LISTO ==")
    print(f"  URL portal : /acceso  (arranca con: uvicorn api:app --port 8000  ->  http://localhost:8000/acceso)")
    print(f"  Usuario    : {PORTAL_EMAIL}")
    print(f"  Contraseña : {PORTAL_PASSWORD}")
    print(f"  Centros    : {len(location_ids)}  ·  Servicios: {len(services)}")


if __name__ == "__main__":
    main()
