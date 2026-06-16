"""Stress test E2E — clinica de masajes REAL con 3 centros y mucha data.

Entorno AISLADO (config/storage/data en carpeta temporal dedicada, NO toca datos
reales). Monta un tenant "masajes" como una clinica de masajes de verdad:

  - 3 centros (Madrid / Barcelona / Valencia)
  - 5 profesionales por centro (15 en total), cada uno fijado a su centro
  - ~11 servicios de masaje con precio/duracion reales (sembrados de info.txt)
  - Miles de citas repartidas por centro/profesional en ~90 dias (pasado+futuro)
  - Clientes (CRM), productos + ventas, bonos + compras, tarjetas regalo, leads

Luego golpea los endpoints que mas sufren con volumen (Informes, Citas dia/semana,
Conversaciones, Clientes, Ventas, disponibilidad) y mide latencia para ver si el
backend aguanta. Con --serve, ademas levanta el portal en local para probar el
front-end a mano con todos esos datos.

Uso:
    python scripts/stress_seed_masajes.py                  # seed + checks con timing
    python scripts/stress_seed_masajes.py --bookings 9000  # mas volumen
    python scripts/stress_seed_masajes.py --serve          # seed + portal en :8000
"""
from __future__ import annotations

import argparse
import json
import os
import random
import secrets
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Stress seed clinica de masajes (aislado)")
parser.add_argument("--bookings", type=int, default=6000, help="Tope de citas a generar (default 6000)")
parser.add_argument("--days-back", type=int, default=60, help="Dias hacia atras (default 60)")
parser.add_argument("--days-fwd", type=int, default=30, help="Dias hacia delante (default 30)")
parser.add_argument("--serve", action="store_true", help="Tras sembrar, levanta el portal en :8000")
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--keep", action="store_true", help="No borrar el entorno previo (reutiliza)")
ARGS = parser.parse_args()

# ---------------------------------------------------------------------------
# Entorno aislado y persistente (carpeta temp dedicada, serveable)
# ---------------------------------------------------------------------------
runtime = Path(tempfile.gettempdir()) / "vantelia-stress-masajes"
if runtime.exists() and not ARGS.keep:
    import shutil
    shutil.rmtree(runtime, ignore_errors=True)
data_dir = runtime / "data"
storage_dir = runtime / "storage"
cfg_path = runtime / "config.json"
storage_dir.mkdir(parents=True, exist_ok=True)

CID = "masajes"

# ── Servicios de masaje (info.txt -> catalogo con precio/duracion) ──────────
SERVICES_TXT = [
    ("Masaje relajante", "45 €", "60 min"),
    ("Masaje descontracturante", "50 €", "60 min"),
    ("Masaje deportivo", "60 €", "75 min"),
    ("Drenaje linfatico", "55 €", "60 min"),
    ("Masaje con piedras calientes", "70 €", "90 min"),
    ("Masaje craneal", "25 €", "30 min"),
    ("Reflexologia podal", "35 €", "45 min"),
    ("Masaje en pareja", "90 €", "60 min"),
    ("Masaje prenatal", "55 €", "60 min"),
    ("Ritual spa premium", "120 €", "120 min"),
    ("Masaje express espalda", "20 €", "20 min"),
]
cdir = data_dir / CID
cdir.mkdir(parents=True, exist_ok=True)
_lines = ["===== CLINICA DE MASAJES Y BIENESTAR =====",
          "Centro de masajes terapeuticos y relajantes con 3 sedes.",
          "", "SERVICIOS Y PRECIOS:"]
for nombre, precio, dur in SERVICES_TXT:
    _lines.append(f"- Servicio: {nombre}")
    _lines.append(f"  - Precio: {precio}")
    _lines.append(f"  - Duracion: {dur}")
    _lines.append(f"  - Detalle: {nombre} realizado por profesionales titulados.")
(cdir / "info.txt").write_text("\n".join(_lines), encoding="utf-8")

cfg_path.write_text(json.dumps({CID: {
    "nombre": "Masajes Vantelia", "icono": "MV", "color": "#00b1d9", "accent_color": "#7c5cff",
    "bienvenida": "Hola, soy el asistente de Masajes Vantelia. Reserva tu masaje.",
    "prompt_extra": "", "allowed_origins": ["http://testserver", "http://localhost", "http://127.0.0.1"],
    "contacto": {"email": "info@masajes-vantelia.es", "telefono": "+34911234567"},
    "branding": {"powered_by": "Vantelia"}, "plan": "business",
    "subscription": {"plan": "business", "status": "active"},
    "whatsapp": {"enabled": True, "phone_number_id": "PH_masajes"},
    "booking": {"enabled": True, "timezone": "Europe/Madrid", "slot_minutes": 30,
                "day_start": "09:00", "day_end": "20:00", "closed_weekdays": [6],
                "provider": "internal", "success_message": "Cita registrada."},
}}, indent=2), encoding="utf-8")

OWNER_EMAIL = "owner@masajes-vantelia.es"
OWNER_PASS = "masajes-owner-123"
os.environ.update({
    "VANTELIA_DATA_DIR": str(data_dir), "VANTELIA_STORAGE_DIR": str(storage_dir),
    "VANTELIA_CONFIG_PATH": str(cfg_path), "OPENAI_API_KEY": "",
    "ADMIN_API_TOKEN": "stress-admin-token", "PORTAL_ADMIN_EMAIL": "admin@example.com",
    "PORTAL_ADMIN_PASSWORD": "stress-password-123", "APP_BASE_URL": f"http://localhost:{ARGS.port}",
    "PORTAL_COOKIE_NAME": "vantelia_portal_session", "PORTAL_COOKIE_DOMAIN": "",
    "REMINDER_RUN_INTERVAL_MINUTES": "0", "WEBHOOK_DEFAULT": "",
    "EXTRA_CORS_ORIGINS": "http://testserver,http://localhost,http://127.0.0.1",
    "EMAIL_SEND_PROVIDER": "smtp", "SMTP_HOST": "", "SMTP_USERNAME": "",
    "SMTP_PASSWORD": "", "SMTP_FROM_EMAIL": "", "SMTP_REPLY_TO": "",
    "WHATSAPP_VERIFY_TOKEN": "stress-wa", "WHATSAPP_ACCESS_TOKEN": "stress-token",
    "WHATSAPP_APP_SECRET": "stress-wa-secret", "WHATSAPP_PHONE_CLIENT_MAP": "PH_masajes:masajes",
    "STRIPE_SECRET_KEY": "sk_test_dummy", "STRIPE_WEBHOOK_SECRET": "",
    "STRIPE_PRICE_STARTER": "p", "STRIPE_PRICE_PRO": "p", "STRIPE_PRICE_BUSINESS": "p",
    "STRIPE_PRICE_STARTER_ANNUAL": "p", "STRIPE_PRICE_PRO_ANNUAL": "p", "STRIPE_PRICE_BUSINESS_ANNUAL": "p",
    "OUTREACH_DB_PATH": str(storage_dir / "outreach" / "outreach.db"),
    "OUTREACH_TRACKING_SECRET": "s", "OUTREACH_TRACKING_BASE_URL": f"http://localhost:{ARGS.port}",
    "OUTREACH_RESPECT_WINDOW": "false",
})

print("=" * 64)
print(" STRESS SEED — Clinica de masajes (3 centros) — entorno aislado")
print("=" * 64)
print(f" runtime: {runtime}")

t_import = time.perf_counter()
import api  # noqa: E402
from backend import agenda, booking, crm, db, timeutils  # noqa: E402
print(f" api import + startup: {time.perf_counter() - t_import:.2f}s")

# ---------------------------------------------------------------------------
# Owner + suscripcion business
# ---------------------------------------------------------------------------
owner = api._create_user(email=OWNER_EMAIL, password=OWNER_PASS, role="client",
                         display_name="Owner Masajes", cliente_id=CID)
api.db_set_client_owner(CID, owner["id"])
api.db_set_subscription_from_stripe(user_id=owner["id"], plan_slug="business", status="active")

NOW_ISO = timeutils._utc_now_iso()

# ---------------------------------------------------------------------------
# 3 centros (reusa el default que crea el startup como primero)
# ---------------------------------------------------------------------------
CENTERS = [
    ("Centro Goya", "Calle de Goya 45, Madrid", "Europe/Madrid"),
    ("Centro Diagonal", "Av. Diagonal 405, Barcelona", "Europe/Madrid"),
    ("Centro Ruzafa", "Carrer de Cadis 22, Valencia", "Europe/Madrid"),
]
loc_ids: list[str] = []
with db._get_db_connection() as conn:
    # Renombra el default auto-creado al primer centro.
    default_row = conn.execute(
        "SELECT id FROM locations WHERE cliente_id=? AND is_default=1 LIMIT 1", (CID,)
    ).fetchone()
    if default_row:
        conn.execute("UPDATE locations SET name=?, address=?, sort_order=0, updated_at=? WHERE id=?",
                     (CENTERS[0][0], CENTERS[0][1], NOW_ISO, default_row["id"]))
        loc_ids.append(default_row["id"])
    else:
        lid = "loc_" + secrets.token_urlsafe(6)
        conn.execute("INSERT INTO locations (id, cliente_id, name, address, phone, timezone, is_active, "
                     "is_default, sort_order, whatsapp_phone_number_id, voice_phone_number, created_at, updated_at) "
                     "VALUES (?, ?, ?, ?, '', ?, 1, 1, 0, '', '', ?, ?)",
                     (lid, CID, CENTERS[0][0], CENTERS[0][1], CENTERS[0][2], NOW_ISO, NOW_ISO))
        loc_ids.append(lid)
    for idx, (name, addr, tz) in enumerate(CENTERS[1:], start=1):
        lid = "loc_" + secrets.token_urlsafe(6)
        conn.execute("INSERT INTO locations (id, cliente_id, name, address, phone, timezone, is_active, "
                     "is_default, sort_order, whatsapp_phone_number_id, voice_phone_number, created_at, updated_at) "
                     "VALUES (?, ?, ?, ?, '', ?, 1, 0, ?, '', '', ?, ?)",
                     (lid, CID, name, addr, tz, idx, NOW_ISO, NOW_ISO))
        loc_ids.append(lid)
    conn.commit()

# ---------------------------------------------------------------------------
# 5 profesionales por centro (15), fijados a su centro
# ---------------------------------------------------------------------------
FIRST = ["Laura", "Carlos", "Marta", "Sergio", "Nuria", "David", "Elena", "Javier",
         "Cristina", "Ruben", "Patricia", "Hugo", "Beatriz", "Adrian", "Raquel",
         "Pablo", "Sara", "Miguel", "Lucia", "Daniel"]
LAST = ["Fernandez", "Ruiz", "Gomez", "Torres", "Diaz", "Romero", "Jimenez", "Moreno",
        "Ortega", "Navarro", "Castro", "Gil", "Vidal", "Ramos", "Santos"]
COLORS = ["#00b1d9", "#7c5cff", "#f4795b", "#22c55e", "#eab308", "#ec4899", "#06b6d4", "#f97316"]

emp_by_loc: dict[str, list[dict]] = {lid: [] for lid in loc_ids}
all_emps: list[dict] = []
name_iter = iter([f"{f} {l}" for f in FIRST for l in LAST])
with db._get_db_connection() as conn:
    for li, lid in enumerate(loc_ids):
        for k in range(5):
            eid = "emp_" + secrets.token_urlsafe(8)
            ename = next(name_iter)
            conn.execute(
                "INSERT INTO employees (id, cliente_id, name, role_label, color, is_active, is_default, "
                "timezone, slot_minutes, day_start, day_end, break_start, break_end, break_windows_json, "
                "closed_weekdays_json, service_ids_json, location_id, created_at, updated_at) "
                "VALUES (?, ?, ?, 'Masajista', ?, 1, 0, 'Europe/Madrid', 30, '09:00', '20:00', '', '', '[]', ?, '[]', ?, ?, ?)",
                (eid, CID, ename, COLORS[(li * 5 + k) % len(COLORS)],
                 json.dumps([6]), lid, NOW_ISO, NOW_ISO),
            )
            rec = {"id": eid, "name": ename, "location_id": lid}
            emp_by_loc[lid].append(rec)
            all_emps.append(rec)
    conn.commit()

# ---------------------------------------------------------------------------
# Catalogo de servicios (sembrado de info.txt)
# ---------------------------------------------------------------------------
services = agenda._catalog_services(CID)
SVC = [{
    "id": s.get("id") or s.get("slug"),
    "nombre": s.get("nombre") or s.get("name"),
    "dur": int(s.get("duration_minutes") or 60),
    "price": int(s.get("price_cents") or 0),
} for s in services if (s.get("nombre") or s.get("name"))]
if not SVC:
    raise SystemExit("BUG: catalogo de servicios vacio (info.txt no sembrado)")

# ---------------------------------------------------------------------------
# Pool de clientes (CRM realista: repetidores)
# ---------------------------------------------------------------------------
CUST_FIRST = ["Ana", "Javier", "Lucia", "Miguel", "Elena", "Pablo", "Sara", "David",
              "Carmen", "Sergio", "Marina", "Alberto", "Raquel", "Hugo", "Patricia",
              "Daniel", "Cristina", "Adrian", "Beatriz", "Ruben", "Sofia", "Mario",
              "Irene", "Alvaro", "Noelia", "Ivan", "Clara", "Oscar", "Julia", "Marcos"]
CUST_LAST = ["Garcia", "Martinez", "Lopez", "Sanchez", "Perez", "Gonzalez", "Rodriguez",
             "Fernandez", "Diaz", "Moreno", "Alvarez", "Romero", "Alonso", "Gutierrez",
             "Navarro", "Torres", "Dominguez", "Vazquez", "Ramos", "Gil"]
rng = random.Random("masajes-stress-v1")
N_CUST = 500
customers = []
for i in range(N_CUST):
    nm = f"{rng.choice(CUST_FIRST)} {rng.choice(CUST_LAST)} {rng.choice(CUST_LAST)}"
    customers.append({
        "nombre": nm,
        "email": f"cliente{i:04d}@clientes-masajes.es",
        "telefono": f"+34 6{rng.randint(10,99)} {rng.randint(100,999)} {rng.randint(100,999)}",
    })

# ---------------------------------------------------------------------------
# Citas masivas — insert directo en una sola conexion (rapido)
# ---------------------------------------------------------------------------
print(f"\n Sembrando hasta {ARGS.bookings} citas en {ARGS.days_back + ARGS.days_fwd} dias...")
SLOTS = [f"{h:02d}:{m:02d}" for h in range(9, 20) for m in (0, 30)]  # 09:00..19:30
today = datetime.now().date()
seq = 0
t_seed = time.perf_counter()
occupied: dict[tuple, list[tuple]] = {}
rows_buffer = []
used_customers: dict[str, dict] = {}
INSERT_SQL = (
    "INSERT INTO bookings (id, cliente_id, employee_id, employee_name, nombre, email, telefono, servicio, "
    "booking_date, booking_time, notas, status, provider_name, provider_status, provider_booking_id, "
    "provider_booking_url, manage_token, timezone, start_at, end_at, confirmed_at, cancelled_at, "
    "rescheduled_at, rescheduled_from_booking_id, confirmation_email_sent_at, reminder_24h_sent_at, "
    "reminder_2h_sent_at, customer_email_status, customer_email_last_error, booking_code, service_id, "
    "service_price_cents, payment_status, location_id, resource_id, source, created_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)
SOURCES = ["portal_manual", "web", "web", "whatsapp", "voice"]
done = False
for offset in range(-ARGS.days_back, ARGS.days_fwd + 1):
    if done:
        break
    day = today + timedelta(days=offset)
    if day.weekday() == 6:  # domingo cerrado
        continue
    is_past = day < today
    for emp in all_emps:
        # cada masajista llena ~35-65% de su dia
        fill = rng.uniform(0.35, 0.65)
        chosen = rng.sample(SLOTS, int(len(SLOTS) * fill))
        for hora in chosen:
            if seq >= ARGS.bookings:
                done = True
                break
            svc = rng.choice(SVC)
            h, m = int(hora[:2]), int(hora[3:])
            start_min = h * 60 + m
            end_min = start_min + svc["dur"]
            if end_min > 20 * 60:
                continue
            key = (emp["id"], day.isoformat())
            busy = occupied.setdefault(key, [])
            if any(start_min < be and end_min > bs for bs, be in busy):
                continue
            busy.append((start_min, end_min))
            cust = rng.choice(customers)
            used_customers[cust["email"]] = cust
            start_local = f"{day.isoformat()}T{hora}:00+02:00"
            end_h = end_min // 60
            end_local = f"{day.isoformat()}T{end_h:02d}:{end_min % 60:02d}:00+02:00"
            if is_past:
                r = rng.random()
                status = "no_show" if r < 0.08 else ("cancelled" if r < 0.20 else "completed")
            else:
                status = "pending_review" if rng.random() < 0.18 else "confirmed"
            bid = secrets.token_urlsafe(16)
            seq += 1
            rows_buffer.append((
                bid, CID, emp["id"], emp["name"], cust["nombre"], cust["email"], cust["telefono"],
                svc["nombre"], day.isoformat(), hora, "", status, "internal", status, "", "",
                "mg_" + secrets.token_urlsafe(12), "Europe/Madrid", start_local, end_local,
                NOW_ISO if status in ("confirmed", "completed") else "",
                NOW_ISO if status == "cancelled" else "", "", "", "", "", "", "", "",
                f"M{seq:06d}", svc["id"], svc["price"], "not_required", emp["location_id"], "",
                rng.choice(SOURCES), NOW_ISO,
            ))
        if done:
            break

with db._get_db_connection() as conn:
    conn.executemany(INSERT_SQL, rows_buffer)
    conn.commit()
print(f" {seq} citas insertadas en {time.perf_counter() - t_seed:.2f}s "
      f"({len(used_customers)} clientes unicos usados)")

# CRM: alta de contactos para los clientes usados (una vez por cliente)
t_crm = time.perf_counter()
for cust in used_customers.values():
    crm._crm_upsert_contact(CID, name=cust["nombre"], email=cust["email"],
                            phone=cust["telefono"], source="booking", status="confirmado",
                            entity_type="booking", entity_id="")
print(f" {len(used_customers)} contactos CRM en {time.perf_counter() - t_crm:.2f}s")

# ---------------------------------------------------------------------------
# Comercio: productos + ventas, bonos + compras, gift cards, leads
# ---------------------------------------------------------------------------
PRODUCTS = [
    ("Aceite esencial lavanda", 1500, 80),
    ("Crema hidratante premium", 2400, 60),
    ("Vela aromatica", 1200, 120),
    ("Pack bienestar regalo", 3900, 40),
    ("Gel de masaje arnica", 1800, 70),
    ("Toalla spa bordada", 2200, 50),
]
with db._get_db_connection() as conn:
    prod_ids = []
    for name, price, stock in PRODUCTS:
        pid = "prod_" + secrets.token_urlsafe(6)
        conn.execute("INSERT INTO products (cliente_id, id, name, description, price_cents, currency, stock, "
                     "is_active, sort_order, created_at, updated_at) VALUES (?, ?, ?, '', ?, 'eur', ?, 1, 0, ?, ?)",
                     (CID, pid, name, price, stock, NOW_ISO, NOW_ISO))
        prod_ids.append((pid, name, price))
    # ~400 ventas de producto repartidas en 60 dias
    n_sales = 0
    for _ in range(400):
        pid, pname, price = rng.choice(prod_ids)
        qty = rng.randint(1, 3)
        day = today - timedelta(days=rng.randint(0, 60))
        sid = "sale_" + secrets.token_urlsafe(6)
        cust = rng.choice(customers)
        conn.execute("INSERT INTO product_sales (id, cliente_id, location_id, product_id, product_name, qty, "
                     "unit_price_cents, total_cents, booking_id, customer_name, customer_email, payment_method, "
                     "notes, status, customer_payment_id, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, '', 'paid', '', ?)",
                     (sid, CID, rng.choice(loc_ids), pid, pname, qty, price, price * qty,
                      cust["nombre"], cust["email"], rng.choice(["cash", "card", "card", "stripe"]),
                      day.isoformat() + "T12:00:00Z"))
        n_sales += 1
    # Bonos
    pkg_specs = [("Bono 5 masajes relajantes", "masaje-relajante", 5, 20000),
                 ("Bono 10 sesiones", "masaje-descontracturante", 10, 40000)]
    pkg_ids = []
    for pname, slug, sessions, price in pkg_specs:
        pid = "pkg_" + secrets.token_urlsafe(6)
        items = json.dumps([{"service_slug": slug, "qty": sessions}], ensure_ascii=False)
        conn.execute("INSERT INTO packages (cliente_id, id, name, description, items_json, price_cents, currency, "
                     "validity_days, is_active, sort_order, created_at, updated_at) "
                     "VALUES (?, ?, ?, '', ?, ?, 'eur', 180, 1, 0, ?, ?)",
                     (CID, pid, pname, items, price, NOW_ISO, NOW_ISO))
        pkg_ids.append((pid, pname, slug, sessions, price))
    n_pp = 0
    for _ in range(60):
        pid, pname, slug, sessions, price = rng.choice(pkg_ids)
        cust = rng.choice(customers)
        day = today - timedelta(days=rng.randint(1, 90))
        ppid = "pp_" + secrets.token_urlsafe(6)
        remaining = json.dumps({slug: rng.randint(1, sessions)}, ensure_ascii=False)
        conn.execute("INSERT INTO package_purchases (id, cliente_id, package_id, package_name, buyer_name, "
                     "buyer_email, buyer_phone, price_cents, remaining_json, expires_at, status, payment_method, "
                     "location_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, '', 'active', 'card', ?, ?, ?)",
                     (ppid, CID, pid, pname, cust["nombre"], cust["email"], price, remaining,
                      rng.choice(loc_ids), day.isoformat() + "T12:00:00Z", NOW_ISO))
        n_pp += 1
    # Gift cards
    n_gc = 0
    for _ in range(40):
        gid = "gc_" + secrets.token_urlsafe(6)
        code = "GC-" + secrets.token_hex(2).upper() + "-" + secrets.token_hex(2).upper()
        amount = rng.choice([3000, 5000, 7500, 10000])
        cust = rng.choice(customers)
        conn.execute("INSERT INTO gift_cards (id, cliente_id, code, initial_cents, balance_cents, currency, status, "
                     "buyer_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'eur', 'active', ?, ?, ?)",
                     (gid, CID, code, amount, amount, cust["nombre"], NOW_ISO, NOW_ISO))
        conn.execute("INSERT INTO gift_card_transactions (cliente_id, gift_card_id, kind, amount_cents, "
                     "balance_after_cents, created_at) VALUES (?, ?, 'issue', ?, ?, ?)",
                     (CID, gid, amount, amount, NOW_ISO))
        n_gc += 1
    conn.commit()
print(f" comercio: {n_sales} ventas, {n_pp} bonos vendidos, {n_gc} gift cards")

# ---------------------------------------------------------------------------
# Resumen de volumen
# ---------------------------------------------------------------------------
with db._get_db_connection() as conn:
    nb = conn.execute("SELECT COUNT(*) FROM bookings WHERE cliente_id=?", (CID,)).fetchone()[0]
    ne = conn.execute("SELECT COUNT(*) FROM employees WHERE cliente_id=?", (CID,)).fetchone()[0]
    nl = conn.execute("SELECT COUNT(*) FROM locations WHERE cliente_id=?", (CID,)).fetchone()[0]
    nc = conn.execute("SELECT COUNT(*) FROM crm_contacts WHERE cliente_id=?", (CID,)).fetchone()[0]
    by_status = dict(conn.execute("SELECT status, COUNT(*) FROM bookings WHERE cliente_id=? GROUP BY status", (CID,)).fetchall())
    by_loc = conn.execute(
        "SELECT l.name, COUNT(b.id) FROM locations l LEFT JOIN bookings b ON b.location_id=l.id "
        "WHERE l.cliente_id=? GROUP BY l.id ORDER BY l.sort_order", (CID,)).fetchall()
print("\n" + "-" * 64)
print(f" VOLUMEN: {nb} citas | {ne} profesionales | {nl} centros | {nc} contactos CRM")
print(f" por estado: {by_status}")
print(" por centro: " + " | ".join(f"{n}={c}" for n, c in by_loc))
print("-" * 64)

# ---------------------------------------------------------------------------
# CHECKS de endpoints bajo carga, con timing
# ---------------------------------------------------------------------------
from fastapi.testclient import TestClient  # noqa: E402
client = TestClient(api.app)
COOK = {"vantelia_portal_session": api._create_auth_session(owner["id"])}
P = {"cliente_id": CID}
PASS, BUG, SLOW = [], [], []


def timed(label, method, path, *, params=None, ok=(200,), warn_ms=1500):
    p = dict(P)
    if params:
        p.update(params)
    t0 = time.perf_counter()
    resp = client.request(method, path, params=p, cookies=COOK)
    ms = (time.perf_counter() - t0) * 1000
    code = resp.status_code
    tag = f"{label} [{code}] {ms:.0f}ms"
    if code not in ok:
        BUG.append(tag + " " + resp.text[:160])
    elif ms > warn_ms:
        SLOW.append(tag)
        PASS.append(tag)
    else:
        PASS.append(tag)
    return resp


print("\n CHECKS bajo carga (latencia real con todos los datos):")
# Informes (el que mas CPU consume: recorre miles de citas)
timed("informes: overview 30d global", "GET", "/auth/analytics/overview", warn_ms=2500)
timed("informes: overview 1 ano global", "GET", "/auth/analytics/overview",
      params={"date_from": (today - timedelta(days=365)).isoformat(), "date_to": today.isoformat()}, warn_ms=3500)
timed("informes: overview por centro", "GET", "/auth/analytics/overview",
      params={"location_id": loc_ids[1], "date_from": (today - timedelta(days=90)).isoformat(),
              "date_to": today.isoformat()}, warn_ms=3000)
timed("informes: export csv", "GET", "/auth/analytics/export.csv", warn_ms=3500)
# Citas: listado grande, vista semana, vista dia
timed("citas: listado 200", "GET", "/auth/bookings", params={"limit": 200}, warn_ms=2000)
mon = today - timedelta(days=today.weekday())
timed("citas: vista semana (7d)", "GET", "/auth/bookings",
      params={"date_from": mon.isoformat(), "date_to": (mon + timedelta(days=6)).isoformat(), "limit": 500}, warn_ms=2500)
timed("citas: vista dia hoy", "GET", "/auth/bookings",
      params={"date_from": today.isoformat(), "date_to": today.isoformat(), "limit": 200}, warn_ms=1500)
timed("citas: filtro por centro", "GET", "/auth/bookings",
      params={"location_id": loc_ids[2], "limit": 200}, warn_ms=2000)
# Clientes (CRM)
timed("clientes: listado", "GET", "/auth/app/contacts", params={"limit": 100}, warn_ms=2000)
timed("clientes: busqueda", "GET", "/auth/app/contacts", params={"q": "Garcia", "limit": 50}, warn_ms=2000)
timed("clientes: export csv", "GET", "/auth/app/contacts/export.csv", warn_ms=2500)
# Conversaciones, alerts, overview, dashboard
timed("conversaciones: listar", "GET", "/auth/conversations", warn_ms=2000)
timed("avisos: bandeja alerts", "GET", "/auth/app/alerts", warn_ms=2000)
timed("overview portal", "GET", "/auth/app/overview", warn_ms=1500)
timed("dashboard", "GET", "/auth/dashboard", warn_ms=2000)
# Ventas
timed("ventas: product-sales", "GET", "/auth/product-sales", params={"limit": 200}, warn_ms=2000)
timed("ventas: productos", "GET", "/auth/products", warn_ms=1000)
# Publico: disponibilidad (3 centros)
ORI = {"Origin": "http://testserver"}
for li, lid in enumerate(loc_ids):
    t0 = time.perf_counter()
    r = client.get(f"/disponibilidad?cliente_id={CID}&fecha={(today + timedelta(days=1)).isoformat()}"
                   f"&servicio=Masaje relajante&location_id={lid}", headers=ORI)
    ms = (time.perf_counter() - t0) * 1000
    (PASS if r.status_code == 200 else BUG).append(f"disponibilidad centro {li+1} [{r.status_code}] {ms:.0f}ms")

# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------
print("\n" + "=" * 64)
print(f" RESULTADO: PASS={len(PASS)}  SLOW={len(SLOW)}  BUG={len(BUG)}")
print("=" * 64)
if BUG:
    print("\n ---- BUGS / FALLOS ----")
    for b in BUG:
        print("  [BUG] " + b)
if SLOW:
    print("\n ---- LENTOS (>umbral, revisar front) ----")
    for s in SLOW:
        print("  [slow] " + s)
print("\n ---- OK (con latencia) ----")
for p in PASS:
    print("  + " + p)

if ARGS.serve:
    print("\n" + "=" * 64)
    print(" PORTAL EN LOCAL para probar el front-end a mano:")
    print(f"   URL:   http://localhost:{ARGS.port}/acceso")
    print(f"   Email: {OWNER_EMAIL}")
    print(f"   Pass:  {OWNER_PASS}")
    print("   (Ctrl+C para parar)")
    print("=" * 64)
    import uvicorn
    uvicorn.run(api.app, host="127.0.0.1", port=ARGS.port, log_level="warning")
else:
    print(f"\n Para probar el FRONT-END a mano con estos datos:")
    print(f"   python scripts/stress_seed_masajes.py --serve --keep")
    sys.exit(1 if BUG else 0)
