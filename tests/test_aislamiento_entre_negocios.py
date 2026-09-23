# -*- coding: utf-8 -*-
"""Un negocio no puede leer ni tocar nada de otro negocio desde el portal.

POR QUE EXISTE
--------------
La guarda de tenant del portal (`portal._portal_client_id_or_403`) decide DE QUE
negocio es la peticion. Pero casi todas las rutas reciben ademas un id en la URL
o en el cuerpo (una cita, un producto, una tarjeta regalo...), y si la ruta carga
esa fila solo por su id, la guarda no sirve de nada: el negocio A opera sobre la
cita del negocio B. Con clientas reales en dos negocios (Alicia, Cap Rocat), es
el fallo mas caro que puede tener Vantelia.

COMO MIDE
---------
- B siembra datos por SU portal, marcados con SECRETOB.
- A ataca cada ruta con los ids de B (en la URL y en el cuerpo).
- Fuga: ninguna respuesta a A contiene la marca de B.
- Mutacion: todas las filas de B en TODAS las tablas con `cliente_id` son
  identicas antes y despues de los ataques, y ninguna fila de A apunta a un id
  de B.
- Control: la misma peticion hecha por B (o por A con sus propios ids) pasa la
  comprobacion de dueno. Sin eso, un 422 o un 403 por otro motivo daria el
  caso por bueno sin haber probado nada.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import DEFAULT_DEMO_CONFIG

A, B = "negocio_a", "negocio_b"
NEGADO = (401, 403, 404)


def _dia(dias=3):
    d = date.today() + timedelta(days=dias)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


DIA = _dia()


@pytest.fixture(scope="module")
def api(vantelia_env_factory):
    configs = {}
    for cid in (A, B):
        cfg = copy.deepcopy(DEFAULT_DEMO_CONFIG["demo"])
        cfg["nombre"] = cid
        cfg["whatsapp"] = {"enabled": False}
        cfg["contacto"] = {"email": cid + "@example.com"}
        cfg["booking"]["day_start"] = "09:00"
        cfg["booking"]["day_end"] = "19:00"
        configs[cid] = cfg
    return vantelia_env_factory(config=configs)


def _ok(res, que):
    assert res.status_code == 200, "%s -> %s %s" % (que, res.status_code, res.text[:300])
    return res.json()


def _sembrar(api, cid, marca):
    """Crea por el portal del propio negocio un objeto de cada tipo."""
    owner = api._create_user(email="%s-%s@example.com" % (marca.lower(), uuid.uuid4().hex[:6]),
                             password="aislamiento-123", role="client",
                             display_name="Dueno " + marca, cliente_id=cid)
    api.db_set_client_owner(cid, owner["id"])
    api.db_set_subscription_from_stripe(user_id=owner["id"], plan_slug="business", status="active")
    web = TestClient(api.app, base_url="https://testserver")
    web.cookies.set("vantelia_portal_session", api._create_auth_session(owner["id"]))
    s = {"web": web, "cid": cid, "marca": marca, "email": marca.lower() + "@example.com"}

    serv = _ok(web.post("/auth/services", json={
        "nombre": "Servicio " + marca, "duration_minutes": 30, "price_cents": 2000}), "servicio")
    s["slug"] = serv["id"]
    loc = _ok(web.post("/auth/locations", json={"name": "Centro " + marca}), "centro")
    s["loc"] = loc["location_id"]
    s["res"] = _ok(web.post("/auth/locations/%s/resources" % s["loc"],
                            json={"name": "Sala " + marca}), "sala")["resource_id"]
    emp = _ok(web.post("/auth/employees", json={
        "name": "Empleada " + marca, "service_ids": [s["slug"]]}), "empleada")
    s["emp"] = emp["employee_id"]
    s["emp_block"] = _ok(web.post("/auth/employees/%s/blocks" % s["emp"], json={
        "fecha": DIA, "hora_inicio": "18:00", "hora_fin": "18:30", "motivo": "Bloqueo " + marca}),
        "bloqueo empleada")["items"][0]["block_id"]
    s["block"] = _ok(web.post("/auth/schedule/blocks", json={
        "fecha": _dia(4), "hora_inicio": "18:00", "hora_fin": "18:30", "motivo": "Cierre " + marca}),
        "bloqueo general")["items"][0]["block_id"]

    citas = []
    for hora in ("10:00", "11:00", "12:00"):
        citas.append(_ok(web.post("/auth/bookings", json={
            "nombre": "Clienta " + marca, "email": s["email"], "telefono": "+34600000111",
            "servicio": s["slug"], "employee_id": s["emp"], "fecha": DIA, "hora": hora,
            "notas": "Nota " + marca}), "cita " + hora)["booking_id"])
    s["bk"], s["bk2"], s["bk3"] = citas

    s["contact"] = _ok(web.post("/auth/app/contacts", json={
        "name": "Contacto " + marca, "email": "c-" + s["email"]}), "contacto")["id"]
    s["lead"] = _ok(web.post("/auth/app/leads", json={
        "name": "Lead " + marca, "email": "l-" + s["email"]}), "lead")["id"]
    s["qa"] = _ok(web.post("/auth/app/qa", json={
        "question": "Pregunta " + marca, "answer": "Respuesta " + marca}), "qa")["id"]
    s["kb"] = _ok(web.post("/auth/app/knowledge/text", json={
        "title": "Nota " + marca, "content": "Contenido " + marca}), "conocimiento")["id"]
    s["kw"] = _ok(web.post("/auth/app/keyword-rules", json={
        "label": "Regla " + marca, "keywords": ["spa"], "reply": "Respuesta " + marca}),
        "palabra clave")["id"]
    s["rule"] = _ok(web.post("/auth/app/business-rules", json={
        "nombre": "Regla " + marca, "intenciones": ["reservar"], "accion": "responder",
        "texto": "Texto " + marca}), "regla negocio")["id"]
    s["prod"] = _ok(web.post("/auth/products", json={
        "name": "Producto " + marca, "price_cents": 1500, "stock": 10}), "producto")["id"]
    s["pkg"] = _ok(web.post("/auth/packages", json={
        "name": "Bono " + marca, "price_cents": 5000,
        "items": [{"service_slug": s["slug"], "qty": 5}]}), "bono")["id"]
    s["purchase"] = _ok(web.post("/auth/packages/%s/sell" % s["pkg"], json={
        "buyer_name": "Compradora " + marca, "buyer_email": s["email"]}), "venta bono")["purchase_id"]
    gc = _ok(web.post("/auth/gift-cards", json={
        "amount_cents": 3000, "buyer_name": "Regala " + marca, "recipient_name": "Recibe " + marca}),
        "tarjeta")
    s["gc"], s["gc_code"] = gc["gift_card_id"], gc["code"]
    s["member"] = _ok(web.post("/auth/app/team", json={
        "email": "staff-%s-%s@example.com" % (marca.lower(), uuid.uuid4().hex[:6]),
        "password": "aislamiento-123", "display_name": "Staff " + marca, "portal_role": "staff"}),
        "equipo")["user_id"]

    # Conversacion de WhatsApp (sin OpenAI no hay /chat): como la guarda el canal.
    from backend import rag
    s["session"] = "wa_" + uuid.uuid4().hex[:12]
    rag._ensure_chat_session_record(s["session"], cid, None, origin_override="whatsapp:+34600000111",
                                    user_agent_override="whatsapp")
    rag._record_chat_message(session_id=s["session"], cliente_id=cid, role="user",
                             content="Hola, soy de " + marca)

    # Pagos: sin Stripe no se crean por la API; se siembran como los dejaria el webhook.
    ahora = "2026-09-23T10:00:00+00:00"
    s["pay"] = "cp_" + uuid.uuid4().hex[:12]
    with sqlite3.connect(str(api.DB_PATH)) as c:
        c.execute("INSERT INTO customer_payments (id, cliente_id, booking_id, service_name, amount_cents, "
                  "status, created_at, updated_at, kind) VALUES (?,?,?,?,?,?,?,?,?)",
                  (s["pay"], cid, s["bk"], "Servicio " + marca, 2000, "paid", ahora, ahora, "pos"))
        c.execute("INSERT INTO booking_payments (id, cliente_id, booking_id, amount_cents, status, "
                  "created_at, updated_at, capture_method) VALUES (?,?,?,?,?,?,?,?)",
                  ("bp_" + uuid.uuid4().hex[:12], cid, s["bk2"], 2000, "preauthorized", ahora, ahora,
                   "manual"))
    return s


@pytest.fixture(scope="module")
def negocios(api):
    return _sembrar(api, A, "SECRETOA"), _sembrar(api, B, "SECRETOB")


def _casos(a, b):
    """(metodo, ruta, cuerpo, quien_hace_el_control, ruta_control, cuerpo_control).

    Rutas con id en la URL: A ataca con los ids de B; el control lo hace B con
    los suyos. Rutas con id en el CUERPO: A usa su propia ruta con un id de B; el
    control lo hace A con sus propios ids.
    """
    otro_dia = _dia(5)
    en_url = [
        ("GET", "/auth/app/contacts/{contact}", None),
        ("PUT", "/auth/app/contacts/{contact}", {"name": "Hackeado"}),
        ("GET", "/auth/bookings/{bk}/cancellation-preview", None),
        ("GET", "/auth/bookings/{bk}/payment", None),
        ("GET", "/auth/bookings/{bk}/timeline", None),
        ("GET", "/auth/chats/{session}", None),
        ("GET", "/auth/conversations/chat/{session}", None),
        ("GET", "/auth/inbox/{session}/takeover", None),
        ("POST", "/auth/inbox/{session}/reply", {"text": "Hackeado"}),
        ("GET", "/auth/locations/{loc}/resources", None),
        ("POST", "/auth/locations/{loc}/resources", {"name": "Sala hackeada"}),
        ("POST", "/auth/locations/{loc}", {"name": "Hackeado"}),
        ("GET", "/auth/schedule/employee/{emp}", None),
        ("POST", "/auth/schedule/employee/{emp}", {"day_start": "06:00"}),
        ("POST", "/auth/employees/{emp}", {"name": "Hackeada"}),
        ("POST", "/auth/employees/{emp}/blocks",
         {"fecha": otro_dia, "hora_inicio": "15:00", "hora_fin": "16:00", "motivo": "Hackeo"}),
        ("POST", "/auth/resources/{res}", {"name": "Hackeada"}),
        ("GET", "/auth/services/{slug}/locations", None),
        ("PUT", "/auth/services/{slug}/locations/{loc}", {"is_available": False}),
        ("PATCH", "/auth/services/{slug}", {"nombre": "Hackeado"}),
        ("PUT", "/auth/app/services/{slug}/payment-policy", {"mode": "none"}),
        ("POST", "/auth/app/bookings/{bk}/payment-link", {}),
        ("POST", "/auth/app/payments/{pay}/refund", {}),
        ("POST", "/auth/bookings/{bk}/confirm-call", {}),
        ("POST", "/auth/bookings/{bk}/payment/checkout", {}),
        ("POST", "/auth/bookings/{bk2}/payment/capture", {}),
        ("POST", "/auth/bookings/{bk2}/payment/refund", {}),
        ("POST", "/auth/bookings/{bk2}/payment/release", {}),
        ("POST", "/auth/bookings/{bk}/review-request", {}),
        ("POST", "/auth/bookings/{bk}/send-confirmation", {}),
        ("POST", "/auth/bookings/{bk}/update",
         {"nombre": "Hackeada", "fecha": DIA, "hora": "10:00"}),
        ("POST", "/auth/bookings/{bk3}/reschedule", {"fecha": otro_dia, "hora": "13:00"}),
        ("POST", "/auth/bookings/{bk3}/attendance", {"attended": False}),
        ("POST", "/auth/bookings/{bk3}/cancel", {}),
        ("POST", "/auth/packages/{pkg}", {"name": "Hackeado"}),
        ("POST", "/auth/packages/{pkg}/sell", {"buyer_name": "X", "buyer_email": "x@example.com"}),
        ("POST", "/auth/products/{prod}", {"name": "Hackeado"}),
        ("POST", "/auth/products/{prod}/sell", {"qty": 1}),
        ("GET", "/auth/gift-cards/{gc}", None),
        ("POST", "/auth/gift-cards/{gc}/status", {"enabled": False}),
        ("GET", "/auth/pos/charge/{pay}", None),
        ("PUT", "/auth/app/business-rules/{rule}", {"nombre": "Hackeada", "texto": "Hackeada"}),
        ("PATCH", "/auth/app/keyword-rules/{kw}", {"reply": "Hackeada"}),
        ("PATCH", "/auth/app/qa/{qa}", {"answer": "Hackeada"}),
        ("GET", "/auth/app/team/{member}/permissions", None),
        ("PUT", "/auth/app/team/{member}/permissions", {"overrides": {"agenda.cancel": "allow"}}),
        ("POST", "/auth/app/team/{member}", {"display_name": "Hackeado"}),
        ("POST", "/auth/inbox/{session}/takeover", {}),
        ("DELETE", "/auth/inbox/{session}/takeover", None),
        # Destructivas al final: el control de B las ejecuta de verdad.
        ("DELETE", "/auth/employees/{emp}/blocks/{emp_block}", None),
        ("DELETE", "/auth/schedule/blocks/{block}", None),
        ("DELETE", "/auth/services/{slug}/locations/{loc}", None),
        ("DELETE", "/auth/resources/{res}", None),
        ("DELETE", "/auth/app/business-rules/{rule}", None),
        ("DELETE", "/auth/app/keyword-rules/{kw}", None),
        ("DELETE", "/auth/app/qa/{qa}", None),
        ("DELETE", "/auth/app/knowledge/{kb}", None),
        ("DELETE", "/auth/app/leads/{lead}", None),
        ("DELETE", "/auth/products/{prod}", None),
        ("DELETE", "/auth/packages/{pkg}", None),
        ("DELETE", "/auth/app/team/{member}", None),
        ("DELETE", "/auth/employees/{emp}", None),
        ("DELETE", "/auth/locations/{loc}", None),
        ("DELETE", "/auth/services/{slug}", None),
    ]
    casos = []
    for metodo, ruta, cuerpo in en_url:
        casos.append((metodo, ruta.format(**b), cuerpo, "b", ruta.format(**b), cuerpo))

    en_cuerpo = [
        ("POST", "/auth/products/{prod}/sell", {"qty": 1, "booking_id": "@bk"}),
        ("POST", "/auth/pos/charge", {"items": [{"product_id": "{prod}", "qty": 1}], "booking_id": "@bk"}),
        ("POST", "/auth/pos/charge", {"items": [{"product_id": "@prod", "qty": 1}]}),
        ("POST", "/auth/package-purchases/{purchase}/redeem", {"booking_id": "@bk"}),
        ("POST", "/auth/package-purchases/@purchase/redeem", {"booking_id": "{bk}"}),
        ("POST", "/auth/gift-cards/redeem", {"code": "@gc_code", "booking_id": "{bk}"}),
        ("POST", "/auth/gift-cards/redeem", {"code": "{gc_code}", "booking_id": "@bk"}),
        ("POST", "/auth/gift-cards/assign", {"gift_card_id": "@gc", "recipient_name": "X"}),
        ("POST", "/auth/bookings", {"nombre": "Intrusa", "fecha": otro_dia, "hora": "16:00",
                                    "servicio": "{slug}", "employee_id": "@emp"}),
        ("POST", "/auth/bookings", {"nombre": "Intrusa", "fecha": otro_dia, "hora": "16:30",
                                    "servicio": "{slug}", "location_id": "@loc"}),
        ("POST", "/auth/bookings/{bk3}/reschedule", {"fecha": otro_dia, "hora": "17:00",
                                                     "employee_id": "@emp"}),
        ("POST", "/auth/employees", {"name": "Intrusa", "location_id": "@loc"}),
        ("POST", "/auth/employees", {"name": "Intrusa", "service_ids": ["@slug"]}),
        ("POST", "/auth/app/leads", {"name": "Intrusa", "session_id": "@session"}),
    ]

    def rellenar(valor, de_b):
        if isinstance(valor, dict):
            return {k: rellenar(v, de_b) for k, v in valor.items()}
        if isinstance(valor, list):
            return [rellenar(v, de_b) for v in valor]
        if isinstance(valor, str):
            for k, v in a.items():
                if isinstance(v, str):
                    valor = valor.replace("@" + k, (b if de_b else a)[k]).replace("{%s}" % k, v)
        return valor

    for metodo, ruta, cuerpo in en_cuerpo:
        casos.append((metodo, rellenar(ruta, True), rellenar(cuerpo, True),
                      "a", rellenar(ruta, False), rellenar(cuerpo, False)))
    return casos


def _filas_de(api, cid):
    """Todas las filas del negocio en TODAS las tablas que llevan cliente_id."""
    out = {}
    with sqlite3.connect(str(api.DB_PATH)) as c:
        tablas = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tablas:
            cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t)]
            if "cliente_id" not in cols:
                continue
            filas = c.execute("SELECT * FROM %s WHERE cliente_id=?" % t, (cid,)).fetchall()
            out[t] = sorted(json.dumps(f, default=str) for f in filas)
    return out


def _pedir(web, metodo, ruta, cuerpo):
    if metodo in ("GET", "DELETE"):
        return web.request(metodo, ruta)
    return web.request(metodo, ruta, json=cuerpo)


PANTALLAS_DE_A = [
    "/auth/me", "/auth/dashboard", "/auth/bookings?limit=200", "/auth/chats", "/auth/conversations",
    "/auth/employees", "/auth/locations", "/auth/services", "/auth/schedule", "/auth/app/leads",
    "/auth/app/overview", "/auth/app/alerts", "/auth/products", "/auth/product-sales",
    "/auth/packages", "/auth/package-purchases", "/auth/gift-cards", "/auth/app/team",
    "/auth/app/central/summary", "/auth/analytics/overview", "/auth/app/qa", "/auth/app/knowledge",
    "/auth/app/keyword-rules", "/auth/app/business-rules", "/auth/app/payments",
]


# Tablas donde un intento rechazado deja rastro legitimo (limites de uso, auditoria
# de accesos del propio atacante). Vacio mientras nadie demuestre que hace falta.
TABLAS_QUE_PUEDEN_CAMBIAR = set()


def test_un_negocio_no_puede_leer_ni_tocar_lo_de_otro(api, negocios):
    a, b = negocios
    casos = _casos(a, b)
    antes = _filas_de(api, B)
    ids_de_b = [v for k, v in b.items() if isinstance(v, str) and k not in ("cid", "marca", "email")]

    fugas, aceptados = [], []
    for metodo, ruta, cuerpo, _q, _r, _c in casos:
        res = _pedir(a["web"], metodo, ruta, cuerpo)
        if res.status_code >= 500:
            fugas.append("%s %s -> %s (500 con ids ajenos)" % (metodo, ruta, res.status_code))
        if "SECRETOB" in res.text or b["email"] in res.text:
            fugas.append("%s %s -> %s devuelve datos de B: %s"
                         % (metodo, ruta, res.status_code, res.text[:160]))
        if 200 <= res.status_code < 300:
            aceptados.append("%s %s %s" % (metodo, ruta, json.dumps(cuerpo)[:80]))

    despues = _filas_de(api, B)
    cambiadas = {t: (sorted(set(antes.get(t, [])) ^ set(despues.get(t, []))))[:2]
                 for t in set(antes) | set(despues)
                 if antes.get(t) != despues.get(t) and t not in TABLAS_QUE_PUEDEN_CAMBIAR}

    filas_a = _filas_de(api, A)
    apunta_a_b = sorted({"%s -> %s" % (t, i) for t, filas in filas_a.items()
                         for f in filas for i in ids_de_b if i in f})

    # Lo que A haya dejado apuntando a B no puede ensenarle nada de B en SUS pantallas.
    for ruta in PANTALLAS_DE_A:
        res = a["web"].get(ruta)
        if "SECRETOB" in res.text or b["email"] in res.text:
            fugas.append("pantalla de A %s ensena datos de B: %s" % (ruta, res.text[:160]))
    contactos = a["web"].get("/auth/app/contacts").json()
    for item in (contactos.get("items") if isinstance(contactos, dict) else contactos) or []:
        res = a["web"].get("/auth/app/contacts/" + item["id"])
        if "SECRETOB" in res.text or b["email"] in res.text:
            fugas.append("ficha de contacto de A ensena datos de B: %s" % res.text[:160])

    assert not fugas, "FUGA entre negocios:\n" + "\n".join(fugas)
    assert not cambiadas, (
        "el negocio A ha modificado datos del negocio B:\n%s\nPeticiones que A vio aceptadas:\n%s"
        % (json.dumps(cambiadas, indent=1)[:3000], "\n".join(aceptados)))
    assert not apunta_a_b, "filas del negocio A que apuntan a objetos de B: %s" % apunta_a_b


def test_cada_caso_llega_a_la_comprobacion_de_dueno(api, negocios):
    """Sin esto el test de arriba podria pasar porque todo da 422 o 403 por otra
    razon. La misma peticion hecha por quien SI es dueno tiene que pasar."""
    a, b = negocios
    sin_control = []
    for metodo, ruta, cuerpo, quien, ruta_c, cuerpo_c in _casos(a, b):
        web = (b if quien == "b" else a)["web"]
        res = _pedir(web, metodo, ruta_c, cuerpo_c)
        if res.status_code in NEGADO + (422,):
            sin_control.append("%s %s (%s) -> %s %s" % (metodo, ruta_c, quien, res.status_code,
                                                        res.text[:140]))
    assert not sin_control, "casos que no prueban nada:\n" + "\n".join(sin_control)


def test_el_inicio_del_portal_abre_con_una_cita_pagada_con_tarjeta(api, negocios):
    """Encontrado por este mismo test (23-sep): desde el 15-ago el inicio del
    portal daba 500 si alguna de las proximas citas tenia pago con tarjeta
    (senal, retencion o cobro Stripe). `sqlite3.Row` no tiene `.get()`."""
    a, _b = negocios
    with sqlite3.connect(str(api.DB_PATH)) as c:
        con_tarjeta = c.execute("SELECT COUNT(*) FROM booking_payments WHERE cliente_id=?", (A,)).fetchone()[0]
    assert con_tarjeta, "el negocio A tiene que tener una cita con pago con tarjeta"
    res = a["web"].get("/auth/dashboard")
    assert res.status_code == 200, res.text[:300]
