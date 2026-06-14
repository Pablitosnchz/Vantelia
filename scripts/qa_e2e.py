"""QA E2E del portal de cliente Vantelia — entorno AISLADO, como usuario real.

Levanta la API contra un config/storage/data TEMPORALES (no toca datos reales) y
recorre TODO lo que un cliente puede hacer en el portal: agenda (web widget,
portal manual, WhatsApp), servicios con precio/duracion, IA/cerebro/Q&A/tune,
apariencia, conocimiento, leads, WhatsApp config, billing, chats, equipo,
horarios, bloqueos, asistencia, demo-agenda, etc.

Uso:
    python scripts/qa_e2e.py

Salida: lista PASS / WARN / BUG y codigo de salida 1 si hay BUGs (500 o fallo real).
Pensado para ejecutarse sin contexto previo: es la "suite manual" del proyecto.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Entorno aislado
# ---------------------------------------------------------------------------
runtime = Path(tempfile.mkdtemp(prefix="vantelia-qa-"))
data_dir = runtime / "data"
storage_dir = runtime / "storage"
cfg_path = runtime / "config.json"
storage_dir.mkdir(parents=True)

CID = "qa"
SERVICES_TXT = [
    ("Primera consulta", "45 €", "45 min"),
    ("Revision", "25 €", "20 min"),
    ("Sesion completa", "1.250 €", "1 h"),
    ("Bono especial", "A consultar", ""),
]
cdir = data_dir / CID
cdir.mkdir(parents=True)
_lines = ["===== INFO QA =====", "SERVICIOS Y PRECIOS:"]
for nombre, precio, dur in SERVICES_TXT:
    _lines.append(f"- Servicio: {nombre}")
    _lines.append(f"  - Precio: {precio}")
    if dur:
        _lines.append(f"  - Duracion: {dur}")
    _lines.append(f"  - Detalle: {nombre} de prueba")
(cdir / "info.txt").write_text("\n".join(_lines), encoding="utf-8")

cfg_path.write_text(json.dumps({CID: {
    "nombre": "Clinica QA", "icono": "AI", "color": "#00b1d9", "accent_color": "#123456",
    "bienvenida": "Hola, soy el asistente QA.", "prompt_extra": "", "allowed_origins": ["http://testserver"],
    "contacto": {"email": "info@qa.es", "telefono": "+34600000000"},
    "branding": {"powered_by": "Vantelia"}, "plan": "business",
    "subscription": {"plan": "business", "status": "active"},
    "whatsapp": {"enabled": True, "phone_number_id": "PH_qa"},
    "booking": {"enabled": True, "timezone": "Europe/Madrid", "slot_minutes": 30,
                "day_start": "09:00", "day_end": "18:00", "closed_weekdays": [6],
                "provider": "internal", "success_message": "Cita registrada."},
}}, indent=2), encoding="utf-8")

os.environ.update({
    "VANTELIA_DATA_DIR": str(data_dir), "VANTELIA_STORAGE_DIR": str(storage_dir),
    "VANTELIA_CONFIG_PATH": str(cfg_path), "OPENAI_API_KEY": "",
    "ADMIN_API_TOKEN": "qa-admin-token", "PORTAL_ADMIN_EMAIL": "admin@example.com",
    "PORTAL_ADMIN_PASSWORD": "qa-password-123", "APP_BASE_URL": "https://app.test.local",
    "PORTAL_COOKIE_NAME": "vantelia_portal_session", "PORTAL_COOKIE_DOMAIN": "",
    "REMINDER_RUN_INTERVAL_MINUTES": "0", "WEBHOOK_DEFAULT": "",
    "EXTRA_CORS_ORIGINS": "http://testserver",
    "EMAIL_SEND_PROVIDER": "smtp", "SMTP_HOST": "", "SMTP_USERNAME": "",
    "SMTP_PASSWORD": "", "SMTP_FROM_EMAIL": "", "SMTP_REPLY_TO": "",
    "WHATSAPP_VERIFY_TOKEN": "qa-wa-verify", "WHATSAPP_ACCESS_TOKEN": "qa-token",
    "WHATSAPP_APP_SECRET": "qa-wa-secret", "WHATSAPP_PHONE_CLIENT_MAP": "PH_qa:qa",
    "STRIPE_SECRET_KEY": "sk_test_dummy", "STRIPE_WEBHOOK_SECRET": "",
    "STRIPE_PRICE_STARTER": "p", "STRIPE_PRICE_PRO": "p", "STRIPE_PRICE_BUSINESS": "p",
    "STRIPE_PRICE_STARTER_ANNUAL": "p", "STRIPE_PRICE_PRO_ANNUAL": "p", "STRIPE_PRICE_BUSINESS_ANNUAL": "p",
    "OUTREACH_DB_PATH": str(storage_dir / "outreach" / "outreach.db"),
    "OUTREACH_TRACKING_SECRET": "s", "OUTREACH_TRACKING_BASE_URL": "https://app.test.local",
    "OUTREACH_RESPECT_WINDOW": "false",
})

import api  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# Mock outbound WhatsApp (Graph API) — solo senders de bajo nivel.
async def _noop(*a, **k):
    return None
for _name in dir(api):
    if _name.startswith("_send_whatsapp"):
        try:
            setattr(api, _name, _noop)
        except Exception:
            pass

client = TestClient(api.app)
ORIGIN = {"Origin": "http://testserver"}
PASS, WARN, BUG = [], [], []


def db():
    c = sqlite3.connect(api.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def future_date(days=2):
    d = datetime.now().date() + timedelta(days=days)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d.isoformat()


def chk(label, resp, ok=(200,), soft=()):
    """Clasifica: ok->PASS, 500->BUG, soft(p.ej.422 payload/402 stripe)->WARN, resto->BUG."""
    code = getattr(resp, "status_code", resp)
    if code in ok:
        PASS.append(f"{label} [{code}]")
        return True
    body = (resp.text[:200] if hasattr(resp, "text") else "")
    if code == 500:
        BUG.append(f"{label} [500] {body}")
    elif code in soft:
        WARN.append(f"{label} [{code}] {body}")
    else:
        BUG.append(f"{label} [{code}] {body}")
    return False


def assert_true(label, cond, extra=""):
    (PASS if cond else BUG).append(f"{label}" + ("" if cond else f" :: {extra}"))


P = {"cliente_id": CID}
# Usuario CLIENTE real, dueño del bot "qa" (lo que usa el portal /auth/app/*).
owner = api._create_user(email="owner@qa.es", password="qa-owner-123", role="client",
                         display_name="Owner QA", cliente_id=CID)
try:
    api.db_set_client_owner(CID, owner["id"])
    api.db_set_subscription_from_stripe(user_id=owner["id"], plan_slug="business", status="active")
except Exception as exc:
    print("WARN setup subscription:", exc)
COOK = {"vantelia_portal_session": api._create_auth_session(owner["id"])}


def gp(path, **kw):
    return client.get(path, params=P, cookies=COOK, **kw)


def pp(path, body=None, **kw):
    return client.post(path, params=P, cookies=COOK, json=(body or {}), **kw)


print("=" * 60)
print(" QA E2E PORTAL VANTELIA (entorno aislado)")
print("=" * 60)

# ── CUENTA / SESION ────────────────────────────────────────────────
chk("auth: /auth/me", gp("/auth/me"))
chk("auth: actualizar perfil", client.post("/auth/profile", cookies=COOK,
    json={"display_name": "Owner QA 2", "email": "owner@qa.es"}), ok=(200,))

# ── OVERVIEW / DEPLOY / APARIENCIA ─────────────────────────────────
chk("overview: GET", gp("/auth/app/overview"))
chk("deploy: GET", gp("/auth/app/deploy"))
chk("apariencia: GET", gp("/auth/app/appearance"))
chk("apariencia: POST color/bienvenida", pp("/auth/app/appearance",
    {"color": "#ff8800", "bienvenida": "Bienvenido a QA"}), soft=(422,))
chk("track: POST evento", pp("/auth/app/track", {"event": "snippet_copied"}), ok=(200, 204), soft=(422,))

# ── CONOCIMIENTO (cerebro) ─────────────────────────────────────────
chk("conocimiento: GET", gp("/auth/app/knowledge"))
kb = pp("/auth/app/knowledge/text", {"title": "Nota QA", "content": "Horario ampliado en verano. Parking gratis."})
chk("conocimiento: add texto", kb, soft=(422,))
kb_id = kb.json().get("id") if kb.status_code == 200 else ""
chk("conocimiento: reindex (sin OpenAI -> 503 esperado)", pp("/auth/app/knowledge/reindex"), ok=(200,), soft=(503, 502, 400))
if kb_id:
    chk("conocimiento: borrar item", client.delete(f"/auth/app/knowledge/{kb_id}", params=P, cookies=COOK), ok=(200, 204))

# ── Q&A ────────────────────────────────────────────────────────────
chk("qa: GET", gp("/auth/app/qa"))
qa = pp("/auth/app/qa", {"question": "Teneis parking?", "answer": "Si, gratis para clientes.", "tags": ["faq"]})
chk("qa: crear", qa, soft=(422,))
qa_id = qa.json().get("id") if qa.status_code == 200 else ""
if qa_id:
    chk("qa: editar", client.patch(f"/auth/app/qa/{qa_id}", params=P, cookies=COOK, json={"answer": "Si, parking gratuito."}), soft=(422,))
    chk("qa: borrar", client.delete(f"/auth/app/qa/{qa_id}", params=P, cookies=COOK), ok=(200, 204))

# ── TUNE AI ────────────────────────────────────────────────────────
chk("tune: GET", gp("/auth/app/tune"))
chk("tune: POST", pp("/auth/app/tune", {"prompt_extra": "Tono cercano.", "temperature": 0.3}), soft=(422,))

# ── SERVICIOS (catalogo nuevo + editor info.txt) ───────────────────
sv = gp("/auth/services")
chk("servicios: GET catalogo", sv)
if sv.status_code == 200:
    items = sv.json()["items"]
    prim = next((s for s in items if s["nombre"] == "Primera consulta"), None)
    assert_true("servicios: precio scrapeado 45€", bool(prim) and prim["price_cents"] == 4500, str(prim))
    assert_true("servicios: duracion scrapeada 45min", bool(prim) and prim["duration_minutes"] == 45, str(prim))
    mil = next((s for s in items if s["nombre"] == "Sesion completa"), None)
    assert_true("servicios: '1.250 €' -> 125000 + 60min", bool(mil) and mil["price_cents"] == 125000 and mil["duration_minutes"] == 60, str(mil))
    bono = next((s for s in items if s["nombre"] == "Bono especial"), None)
    assert_true("servicios: 'A consultar' -> 0€ + default 30min", bool(bono) and bono["price_cents"] == 0 and bono["duration_minutes"] == 30, str(bono))
sc = pp("/auth/services", {"nombre": "Masaje QA", "duration_minutes": 50, "price_cents": 4000})
chk("servicios: crear", sc, soft=(422,))
slug = sc.json().get("id") if sc.status_code == 200 else ""
if slug:
    chk("servicios: editar precio", client.patch(f"/auth/services/{slug}", params=P, cookies=COOK, json={"price_cents": 4500}), soft=(422,))
chk("servicios(app): GET editor info.txt", gp("/auth/app/services"))

# ── WHATSAPP CONFIG ────────────────────────────────────────────────
chk("whatsapp-config: GET", gp("/auth/app/whatsapp"))
chk("whatsapp-config: POST", pp("/auth/app/whatsapp", {"enabled": True, "phone_number_id": "PH_qa"}), soft=(422,))

# ── LEADS ──────────────────────────────────────────────────────────
chk("leads: GET", gp("/auth/app/leads"))
ld = pp("/auth/app/leads", {"name": "Lead QA", "email": "lead@qa.com", "phone": "600", "message": "Quiero info"})
chk("leads: crear", ld, soft=(422,))
ld_id = ld.json().get("id") if ld.status_code == 200 else ""
chk("leads: export csv", gp("/auth/app/leads/export.csv"))
if ld_id:
    chk("leads: borrar", client.delete(f"/auth/app/leads/{ld_id}", params=P, cookies=COOK), ok=(200, 204))

# ── LIVECHAT / BILLING / SUBSCRIPTION ──────────────────────────────
chk("livechat: GET", gp("/auth/app/livechat"))
chk("billing: GET", gp("/auth/app/billing"))
chk("subscription: GET", gp("/auth/subscription"))

# ── IA CONFIG / BRAIN / SCHEDULE ───────────────────────────────────
chk("ai-config: GET", gp("/auth/ai-config"))
chk("ai-config: POST", pp("/auth/ai-config", {"icono": "QA", "bienvenida": "Hola, en que ayudo?", "prompt_extra": "Profesional."}), soft=(422,))
chk("brain: GET", gp("/auth/brain"))
chk("schedule: GET", gp("/auth/schedule"))
chk("schedule: POST", pp("/auth/schedule", {"enabled": True, "timezone": "Europe/Madrid", "slot_minutes": 30,
    "day_start": "09:00", "day_end": "18:00", "closed_weekdays": [6]}), soft=(422,))

# ── EQUIPO ─────────────────────────────────────────────────────────
chk("equipo: GET", gp("/auth/employees"))
emp = pp("/auth/employees", {"name": "Dra QA", "role_label": "Doctora", "color": "#00b1d9",
    "is_active": True, "timezone": "Europe/Madrid", "slot_minutes": 30, "day_start": "09:00",
    "day_end": "18:00", "closed_weekdays": [], "service_ids": []})
chk("equipo: crear profesional", emp, soft=(422,))
emp_id = emp.json().get("employee_id") if emp.status_code == 200 else ""

# ── BLOQUEOS DE AGENDA ─────────────────────────────────────────────
blk_date = future_date(5)
bl = pp("/auth/schedule/blocks", {"fecha": blk_date, "hora_inicio": "13:00", "hora_fin": "14:00", "motivo": "Comida"})
chk("bloqueos: crear (general)", bl, soft=(422,))
bl_id = ""
if bl.status_code == 200:
    js = bl.json()
    bl_id = (js.get("items") or [{}])[0].get("block_id", "") if isinstance(js.get("items"), list) else js.get("block_id", "")
if bl_id:
    chk("bloqueos: borrar", client.delete(f"/auth/schedule/blocks/{bl_id}", params=P, cookies=COOK), ok=(200, 204))

# ── CANAL WEB / WIDGET: agendar ────────────────────────────────────
fecha = future_date(2)
disp = client.get(f"/disponibilidad?cliente_id={CID}&fecha={fecha}&servicio=Primera consulta", headers=ORIGIN)
chk("web: /disponibilidad", disp)
slots = [s["hora"] for s in disp.json().get("slots", []) if s.get("disponible")] if disp.status_code == 200 else []
web_bid = ""
if slots:
    ag = client.post("/agendar", headers=ORIGIN, json={"cliente_id": CID, "nombre": "Cliente Web",
        "email": "web@cliente.com", "telefono": "600111222", "servicio": "Primera consulta",
        "fecha": fecha, "hora": slots[0], "notas": "via web"})
    chk("web: POST /agendar", ag)
    if ag.status_code == 200:
        web_bid = ag.json()["booking_id"]
        token = ag.json().get("manage_url", "").rsplit("/", 1)[-1].split("?")[0]
        chk("web: pagina gestion cliente", client.get(f"/booking/manage/{token}"))
        chk("web: overlap mismo hueco -> 409", client.post("/agendar", headers=ORIGIN, json={"cliente_id": CID,
            "nombre": "Otro", "email": "o@o.com", "telefono": "", "servicio": "Primera consulta",
            "fecha": fecha, "hora": slots[0], "notas": ""}), ok=(409,))
        chk("web: fecha pasada -> 400", client.post("/agendar", headers=ORIGIN, json={"cliente_id": CID,
            "nombre": "Cliente Pasado", "email": "x@x.com", "telefono": "", "servicio": "", "fecha": "2020-01-01",
            "hora": slots[0], "notas": ""}), ok=(400,))

# ── PORTAL: alta manual de cita ────────────────────────────────────
mb = pp("/auth/bookings", {"nombre": "Cliente Portal", "email": "portal@cliente.com", "telefono": "600",
    "servicio": "Masaje QA", "employee_id": emp_id, "fecha": future_date(3), "hora": "11:00", "notas": "manual"})
chk("portal: alta manual de cita", mb)
mbid = mb.json().get("booking_id") if mb.status_code == 200 else ""
if mbid:
    with db() as c:
        row = c.execute("SELECT service_price_cents, start_at, end_at FROM bookings WHERE id=?", (mbid,)).fetchone()
    dur = int((datetime.fromisoformat(row["end_at"].replace('Z', '+00:00')) - datetime.fromisoformat(row["start_at"].replace('Z', '+00:00'))).total_seconds() // 60) if row and row["end_at"] else 0
    assert_true("portal: snapshot precio 4500 + duracion 50", bool(row) and row["service_price_cents"] == 4500 and dur == 50, f"{row['service_price_cents'] if row else '?'}/{dur}")

# ── PORTAL: listar / reprogramar / timeline / cancelar ─────────────
chk("portal: listar citas", gp("/auth/bookings", params={**P, "limit": 100}) if False else client.get("/auth/bookings", params={**P, "limit": 100}, cookies=COOK))
if mbid:
    chk("portal: timeline cita", client.get(f"/auth/bookings/{mbid}/timeline", cookies=COOK))
    chk("portal: reprogramar", client.post(f"/auth/bookings/{mbid}/reschedule", cookies=COOK,
        json={"employee_id": emp_id, "fecha": future_date(3), "hora": "12:00"}), soft=(409,))

# ── PORTAL: asistencia (cita pasada) ───────────────────────────────
past_id = uuid.uuid4().hex
ps = datetime.utcnow() - timedelta(hours=3); pe = ps + timedelta(minutes=30)
api._store_booking({"id": past_id, "cliente_id": CID, "employee_id": emp_id, "employee_name": "Dra QA",
    "nombre": "Pasado", "email": "p@p.com", "telefono": "", "servicio": "Revision", "booking_date": ps.date().isoformat(),
    "booking_time": ps.strftime("%H:%M"), "notas": "", "status": "confirmed", "provider_name": "internal",
    "provider_status": "internal", "provider_booking_id": "", "provider_booking_url": "", "manage_token": "mg_" + past_id,
    "timezone": "Europe/Madrid", "start_at": ps.isoformat() + "Z", "end_at": pe.isoformat() + "Z", "confirmed_at": ps.isoformat() + "Z",
    "cancelled_at": "", "rescheduled_at": "", "rescheduled_from_booking_id": "", "confirmation_email_sent_at": "",
    "reminder_24h_sent_at": "", "reminder_2h_sent_at": "", "customer_email_status": "", "customer_email_last_error": "",
    "source": "test", "created_at": ps.isoformat() + "Z"})
a1 = client.post(f"/auth/bookings/{past_id}/attendance", cookies=COOK, json={"attended": False})
assert_true("portal: marcar no-show", a1.status_code == 200 and a1.json().get("estado") == "no_show", a1.text[:120])
a2 = client.post(f"/auth/bookings/{past_id}/attendance", cookies=COOK, json={"attended": True})
assert_true("portal: corregir a realizada", a2.status_code == 200 and a2.json().get("estado") == "completed", a2.text[:120])
dash = gp("/auth/dashboard")
st = dash.json().get("stats", {}) if dash.status_code == 200 else {}
assert_true("portal: dashboard con asistencia", all(k in st for k in ("completed", "no_show", "attendance_rate")), str(st))
if mbid:
    chk("portal: cancelar cita", client.post(f"/auth/bookings/{mbid}/cancel", cookies=COOK, json={}))

# ── ADMIN: agenda demo ─────────────────────────────────────────────
HDR = {"Authorization": "Bearer qa-admin-token"}
chk("admin: generar agenda demo", client.post(f"/admin/clientes/{CID}/demo-agenda", headers=HDR))
with db() as c:
    nd = c.execute("SELECT COUNT(*) FROM bookings WHERE cliente_id=? AND source='demo_seed'", (CID,)).fetchone()[0]
assert_true("admin: demo crea citas", nd > 0, f"n={nd}")
chk("admin: borrar agenda demo", client.delete(f"/admin/clientes/{CID}/demo-agenda", headers=HDR))

# ── WHATSAPP: verify + flujo agendar completo ──────────────────────
v = client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "qa-wa-verify", "hub.challenge": "42"})
assert_true("whatsapp: verify webhook", v.status_code == 200 and v.text.strip('"') == "42", f"{v.status_code}")


def wa_msg(text=None, list_id=None, button_id=None):
    msg = {"from": "34699333444", "id": "wamid." + uuid.uuid4().hex, "timestamp": "1700000000"}
    if text is not None:
        msg["type"] = "text"; msg["text"] = {"body": text}
    elif list_id is not None:
        msg["type"] = "interactive"; msg["interactive"] = {"type": "list_reply", "list_reply": {"id": list_id, "title": list_id}}
    elif button_id is not None:
        msg["type"] = "interactive"; msg["interactive"] = {"type": "button_reply", "button_reply": {"id": button_id, "title": button_id}}
    body = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "PH_qa"},
        "contacts": [{"profile": {"name": "Wa User"}, "wa_id": "34699333444"}], "messages": [msg]}}]}]}
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(b"qa-wa-secret", raw, hashlib.sha256).hexdigest()
    return client.post("/whatsapp/webhook", content=raw, headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})


assert_true("whatsapp: firma invalida -> 403", client.post("/whatsapp/webhook", content=b'{"x":1}',
    headers={"X-Hub-Signature-256": "sha256=bad", "Content-Type": "application/json"}).status_code == 403)
wfecha = future_date(4)
wa_steps = [dict(text="agendar"), dict(list_id="svc_0"), dict(list_id=f"date_{wfecha}"),
            dict(list_id="time_10:00"), dict(text="Maria Whatsapp"), dict(text="maria@wa.com"),
            dict(button_id="notes_skip"), dict(button_id="confirm_yes")]
wa_ok = all(wa_msg(**s).status_code == 200 for s in wa_steps)
assert_true("whatsapp: flujo agendar completo (8 pasos)", wa_ok)
with db() as c:
    wabk = c.execute("SELECT nombre, status FROM bookings WHERE cliente_id=? AND source='whatsapp'", (CID,)).fetchall()
assert_true("whatsapp: cita creada via flujo", len(wabk) >= 1 and wabk[0]["status"] == "confirmed", f"n={len(wabk)}")

# ── CHATS (via WhatsApp normal) ────────────────────────────────────
wa_msg(text="cuanto cuesta una revision?")
ch = gp("/auth/chats")
chk("chats: listar", ch)
if ch.status_code == 200 and ch.json():
    sid = ch.json()[0].get("session_id") or ch.json()[0].get("id")
    if sid:
        chk("chats: detalle", client.get(f"/auth/chats/{sid}", params=P, cookies=COOK))

# ── NUEVAS FUNCIONES (politica cancelacion, permisos, POS, conversaciones,
#    recordatorios/llamadas, voz widget, demo completa) ──────────────
# Politica de cancelacion/no-show
chk("cancelacion: GET politica", gp("/auth/app/cancellation-policy"))
chk("cancelacion: PUT politica", client.put("/auth/app/cancellation-policy", params=P, cookies=COOK,
    json={"enabled": True, "free_cancel_hours": 24, "late_cancel_fee_pct": 50, "no_show_fee_pct": 100}), soft=(422,))
mb2 = pp("/auth/bookings", {"nombre": "Cancel QA", "email": "c@qa.com", "telefono": "600111222",
    "servicio": "Masaje QA", "employee_id": emp_id, "fecha": future_date(2), "hora": "11:00", "notas": ""})
chk("cancelacion: alta cita para preview", mb2, soft=(409,))
if mb2.status_code == 200:
    cbid = mb2.json().get("booking_id")
    chk("cancelacion: preview", client.get(f"/auth/bookings/{cbid}/cancellation-preview", cookies=COOK))

# Recordatorios / llamadas de confirmacion
chk("recordatorios: GET config", gp("/auth/app/reminders"))
chk("recordatorios: PUT config", client.put("/auth/app/reminders", params=P, cookies=COOK,
    json={"call_fallback": False, "quiet_start": "21:00", "quiet_end": "09:00", "daily_call_cap": 20}), soft=(422,))
if mb2.status_code == 200 and cbid:
    # Sin numero Twilio -> confirm-call debe dar 409 controlado (no romper).
    chk("recordatorios: confirm-call sin numero -> 409", client.post(f"/auth/bookings/{cbid}/confirm-call", cookies=COOK), ok=(409,), soft=(403,))

# Permisos granulares
chk("permisos: catalogo", gp("/auth/app/permissions/catalog"))
stf = pp("/auth/app/team", {"email": f"staff{uuid.uuid4().hex[:6]}@qa.com", "password": "staffpass123",
    "display_name": "Recepcion QA", "portal_role": "staff"})
chk("permisos: crear staff", stf, soft=(403, 409))
if stf.status_code == 200:
    sid_user = stf.json().get("user_id")
    chk("permisos: GET de usuario", client.get(f"/auth/app/team/{sid_user}/permissions", params=P, cookies=COOK))
    chk("permisos: PUT override", client.put(f"/auth/app/team/{sid_user}/permissions", params=P, cookies=COOK,
        json={"overrides": {"reports.view": "allow", "agenda.cancel": "deny"}}), soft=(422,))

# Conversaciones unificadas
chk("conversaciones: listar", gp("/auth/conversations"))
chk("conversaciones: filtro voz", client.get("/auth/conversations", params={**P, "channel": "voice"}, cookies=COOK))

# Comercio (Ventas): producto + venta manual
prod = pp("/auth/products", {"name": "Aceite QA", "price_cents": 1500, "stock": 5})
chk("ventas: crear producto", prod, soft=(403, 422))
if prod.status_code == 200:
    pid = prod.json().get("id")
    chk("ventas: vender (efectivo)", client.post(f"/auth/products/{pid}/sell", params=P, cookies=COOK,
        json={"qty": 2, "payment_method": "cash"}))
    chk("ventas: POS charge sin Stripe -> 409", client.post("/auth/pos/charge", params=P, cookies=COOK,
        json={"items": [{"product_id": pid, "qty": 1}]}), ok=(409,), soft=(403,))

# Voz en el widget (gating publico)
cfgpub = client.get(f"/cliente/{CID}", headers={"Origin": "http://testserver"})
assert_true("voz widget: flag en config publica", cfgpub.status_code == 200 and "voice_widget_enabled" in cfgpub.json(), cfgpub.text[:120])
assert_true("voz widget: sesion sin opt-in -> 403",
    client.post(f"/voice/widget/{CID}/session", headers={"Origin": "http://testserver"}, json={}).status_code == 403)

# Demo completa (admin): agenda + comercio
chk("demo: generar completa", client.post(f"/admin/clientes/{CID}/demo-agenda", headers=HDR))
with db() as c:
    nloc = c.execute("SELECT COUNT(*) FROM locations WHERE cliente_id=? AND id LIKE 'locdemo_%'", (CID,)).fetchone()[0]
    nprod = c.execute("SELECT COUNT(*) FROM products WHERE cliente_id=? AND id LIKE 'proddemo_%'", (CID,)).fetchone()[0]
assert_true("demo: crea centros y productos", nloc > 0 and nprod > 0, f"loc={nloc} prod={nprod}")
chk("demo: borrar completa", client.delete(f"/admin/clientes/{CID}/demo-agenda", headers=HDR))
with db() as c:
    left = c.execute("SELECT COUNT(*) FROM products WHERE cliente_id=? AND id LIKE 'proddemo_%'", (CID,)).fetchone()[0]
assert_true("demo: purga deja cero productos demo", left == 0, f"left={left}")

# ── RESUMEN ────────────────────────────────────────────────────────
print(f"\nPASS: {len(PASS)}   WARN: {len(WARN)}   BUG: {len(BUG)}\n")
if BUG:
    print("---- BUGS / FALLOS ----")
    for b in BUG:
        print("  [BUG] " + b)
if WARN:
    print("\n---- WARN (payload/dep externa, revisar) ----")
    for w in WARN:
        print("  [warn] " + w)
print("\n---- OK ----")
for p in PASS:
    print("  + " + p)

sys.exit(1 if BUG else 0)
