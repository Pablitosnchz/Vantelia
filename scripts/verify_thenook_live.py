"""Verificacion en vivo del tenant `thenook` sobre la DB real.

Ejercita los flujos criticos como lo haria un usuario real y comprueba que TODO
se sincroniza al momento y sin colisiones: login real, agenda multi-centro,
disponibilidad, doble reserva bloqueada, aislamiento entre centros, aforo de
salas, ventas (producto/bono/tarjeta regalo) reflejadas en informes, y refresco
en tiempo real de los KPIs.

Crea y LIMPIA sus propios datos de prueba (no toca las 238 citas del seeder).

Uso (con el seeder ya ejecutado):
    python scripts/verify_thenook_live.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import api  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

CID = "thenook"
EMAIL = "demo@thenook.es"
PASSWORD = "TheNookDemo2025!"

PASS = 0
FAIL = 0
created_booking_ids = []


def check(label: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}  {extra}")


def main() -> int:
    client = TestClient(api.app)

    # 1) LOGIN real con email/clave (valida que la contrasena funciona)
    r = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    check("login con email/clave reales -> 200", r.status_code == 200, r.text[:160])
    check("login redirige al panel", r.json().get("redirect_to", "") != "")
    # La cookie de sesion es Secure; sobre http el jar de TestClient la descarta.
    # Para el resto de llamadas autenticadas inyectamos una sesion valida (igual
    # que hace la suite). El login real ya quedo verificado arriba.
    user = api._get_user_by_email(EMAIL)
    cookie_name = getattr(api, "PORTAL_COOKIE_NAME", "vantelia_portal_session")
    client.cookies.set(cookie_name, api._create_auth_session(user["id"]))
    me = client.get("/auth/me").json()
    check("rol del usuario = owner", me.get("portal_role") == "owner", str(me.get("portal_role")))

    # 2) Catalogo y centros cargan
    locs = client.get("/auth/locations").json()["items"]
    check("3 centros visibles", len(locs) == 3, str(len(locs)))
    svcs = client.get("/auth/services").json()["items"]
    check("catalogo de servicios > 0", len(svcs) > 0, str(len(svcs)))
    emps = client.get("/auth/employees").json()["items"]
    real_emps = [e for e in emps if not e.get("is_default")]
    check("masajistas creados (7)", len(real_emps) == 7, str(len(real_emps)))

    loc_a = next(l for l in locs if l["is_default"])
    loc_b = next(l for l in locs if not l["is_default"])
    emp_a = next(e for e in real_emps if e["location_id"] == loc_a["location_id"])
    emp_b = next(e for e in real_emps if e["location_id"] == loc_b["location_id"])

    # fecha futura laborable
    target = api._utc_now().date() + timedelta(days=5)
    while target.weekday() == 6:
        target += timedelta(days=1)
    fecha = target.isoformat()
    hoy = api._utc_now().date().isoformat()
    # Rango de informe que INCLUYE la fecha de prueba (para ver el refresco en vivo).
    rango = {"date_from": hoy, "date_to": fecha}

    # 3) Informes ANTES (snapshot para comparar sync en vivo)
    ov0 = client.get("/auth/analytics/overview", params=rango).json()
    rev0 = ov0["kpis"]["revenue_cents"]
    cnt0 = ov0["kpis"]["bookings_total"]
    check("informe overview responde con KPIs", "revenue_cents" in ov0["kpis"])

    def book(emp_id, hora, loc_id):
        r = client.post("/auth/bookings", json={
            "nombre": "Cliente Verif", "email": "verif@example.com", "telefono": "600999000",
            "servicio": "", "employee_id": emp_id, "location_id": loc_id, "fecha": fecha, "hora": hora, "notas": "verif",
        })
        if r.status_code == 200:
            created_booking_ids.append(r.json()["booking_id"])
        return r

    # 4) Crear cita y verificar que aparece YA en agenda + informes
    rb = book(emp_a["employee_id"], "12:00", loc_a["location_id"])
    check("alta de cita -> 200", rb.status_code == 200, rb.text[:160])
    day = client.get("/auth/bookings", params={"date_from": fecha, "date_to": fecha}).json()
    items = day if isinstance(day, list) else day.get("items", [])
    check("cita aparece al instante en la agenda del dia",
          any(b.get("booking_id") == rb.json()["booking_id"] or b.get("id") == rb.json()["booking_id"] for b in items))

    # marcar pagada y comprobar que el informe sube en vivo
    with sqlite3.connect(api.DB_PATH) as conn:
        conn.execute("UPDATE bookings SET payment_status='paid', service_price_cents=6000 WHERE id=?", (rb.json()["booking_id"],))
        conn.commit()
    ov1 = client.get("/auth/analytics/overview", params=rango).json()
    check("informe: nº de citas sube al crear (sync en vivo)", ov1["kpis"]["bookings_total"] == cnt0 + 1,
          f"{cnt0}->{ov1['kpis']['bookings_total']}")
    check("informe: ingresos suben al marcar pagada (sync en vivo)", ov1["kpis"]["revenue_cents"] == rev0 + 6000,
          f"{rev0}->{ov1['kpis']['revenue_cents']}")

    # 5) COLISION: mismo masajista, mismo hueco -> 409
    rc = book(emp_a["employee_id"], "12:00", loc_a["location_id"])
    check("doble reserva mismo profesional/hueco -> 409 (sin colision)", rc.status_code == 409, str(rc.status_code))

    # 6) AISLAMIENTO: mismo hueco en OTRO centro/profesional -> OK
    rd = book(emp_b["employee_id"], "12:00", loc_b["location_id"])
    check("mismo hueco en otro centro -> 200 (agendas independientes)", rd.status_code == 200, rd.text[:120])

    # 7) Disponibilidad publica del centro refleja el hueco ocupado
    disp = client.get("/disponibilidad", params={"cliente_id": CID, "fecha": fecha, "employee_id": emp_a["employee_id"]},
                      headers={"Origin": "https://app.vantelia.es"}).json()
    libres = {s["hora"]: s["disponible"] for s in disp.get("slots", [])}
    check("disponibilidad marca 12:00 ocupado para ese profesional", libres.get("12:00") is False, str(libres.get("12:00")))

    # 8) AFORO de salas: centro temporal aislado con 1 sala + 2 masajistas.
    #    2 citas solapadas: la 1ª entra, la 2ª no cabe (1 sala).
    from api_models import PortalEmployeePayload, PortalLocationPayload, PortalResourcePayload
    tmp_loc = api._create_portal_location(CID, PortalLocationPayload(
        name="ZZ Verif Aforo", address="tmp", phone="", timezone="Europe/Madrid", is_active=True))
    tmp_loc_id = tmp_loc.location_id
    try:
        api._create_portal_resource(CID, tmp_loc_id, PortalResourcePayload(name="Única", is_active=True))
        e1 = api._create_portal_employee(CID, PortalEmployeePayload(
            name="Aforo Uno", location_id=tmp_loc_id, service_ids=[], day_start="10:00", day_end="19:00",
            slot_minutes=30, closed_weekdays=[6]), full_access=True)
        e2 = api._create_portal_employee(CID, PortalEmployeePayload(
            name="Aforo Dos", location_id=tmp_loc_id, service_ids=[], day_start="10:00", day_end="19:00",
            slot_minutes=30, closed_weekdays=[6]), full_access=True)
        r1 = book(e1.employee_id, "15:00", tmp_loc_id)
        r2 = book(e2.employee_id, "15:00", tmp_loc_id)
        check("aforo: con 1 sala, 1ª cita entra (200) y 2ª solapada se bloquea (409)",
              r1.status_code == 200 and r2.status_code == 409, f"r1={r1.status_code} r2={r2.status_code}")
    finally:
        with sqlite3.connect(api.DB_PATH) as conn:
            conn.execute("DELETE FROM bookings WHERE cliente_id=? AND location_id=?", (CID, tmp_loc_id))
            conn.execute("DELETE FROM resources WHERE cliente_id=? AND location_id=?", (CID, tmp_loc_id))
            conn.execute("DELETE FROM employees WHERE cliente_id=? AND location_id=?", (CID, tmp_loc_id))
            conn.execute("DELETE FROM locations WHERE cliente_id=? AND id=?", (CID, tmp_loc_id))
            conn.commit()

    # 9) Venta de producto refleja en product-sales
    prods = client.get("/auth/products").json()["items"]
    if prods:
        before_sales = len(client.get("/auth/product-sales").json()["items"])
        rs = client.post(f"/auth/products/{prods[0]['id']}/sell", json={"qty": 1, "payment_method": "cash"})
        check("vender producto -> 200", rs.status_code == 200, rs.text[:120])
        after_sales = len(client.get("/auth/product-sales").json()["items"])
        check("la venta aparece en el listado al instante", after_sales == before_sales + 1)

    # 10) Bono: vender y redimir sobre una cita -> queda pagada
    pkgs = client.get("/auth/packages").json()["items"]
    if pkgs:
        rsell = client.post(f"/auth/packages/{pkgs[0]['id']}/sell",
                            json={"buyer_name": "Verif", "buyer_email": "verif@example.com"})
        check("vender bono -> 200", rsell.status_code == 200, rsell.text[:120])
        # cita nueva del servicio del bono para redimir
        slug = pkgs[0]["items"][0]["service_slug"]
        svc_name = next((s["nombre"] for s in svcs if s["id"] == slug), "")
        rbk = client.post("/auth/bookings", json={
            "nombre": "Bono Cliente", "email": "verif@example.com", "telefono": "600999111",
            "servicio": svc_name, "employee_id": emp_a["employee_id"], "location_id": loc_a["location_id"],
            "fecha": fecha, "hora": "18:00", "notas": "bono",
        })
        if rbk.status_code == 200:
            created_booking_ids.append(rbk.json()["booking_id"])
            purchase = client.get("/auth/package-purchases", params={"q": "verif@example.com"}).json()["items"][0]
            rr = client.post(f"/auth/package-purchases/{purchase['purchase_id']}/redeem",
                             json={"booking_id": rbk.json()["booking_id"]})
            check("redimir bono sobre cita -> 200", rr.status_code == 200, rr.text[:120])
            with sqlite3.connect(api.DB_PATH) as conn:
                ps = conn.execute("SELECT payment_status FROM bookings WHERE id=?", (rbk.json()["booking_id"],)).fetchone()
            check("la cita queda pagada tras redimir el bono", ps and ps[0] == "paid", str(ps))

    # 11) Tarjeta regalo: emitir y redimir total sobre una cita
    rgift = client.post("/auth/gift-cards", json={"amount_cents": 9000, "buyer_name": "Verif"})
    check("emitir tarjeta regalo -> 200", rgift.status_code == 200, rgift.text[:120])
    if rgift.status_code == 200:
        code = rgift.json()["code"]
        rbk2 = client.post("/auth/bookings", json={
            "nombre": "Gift Cliente", "email": "verif@example.com", "telefono": "600999222",
            "servicio": "", "employee_id": emp_b["employee_id"], "location_id": loc_b["location_id"],
            "fecha": fecha, "hora": "18:00", "notas": "gift",
        })
        if rbk2.status_code == 200:
            bid2 = rbk2.json()["booking_id"]
            created_booking_ids.append(bid2)
            with sqlite3.connect(api.DB_PATH) as conn:
                conn.execute("UPDATE bookings SET service_price_cents=6000 WHERE id=?", (bid2,))
                conn.commit()
            rr = client.post("/auth/gift-cards/redeem", json={"code": code, "booking_id": bid2})
            check("redimir tarjeta regalo (cubre total) -> 200 + cita pagada",
                  rr.status_code == 200 and rr.json().get("covered") is True, rr.text[:120])

    # 12) Export CSV de informes
    rcsv = client.get("/auth/analytics/export.csv")
    check("export CSV de informes -> 200", rcsv.status_code == 200 and "fecha;citas" in rcsv.text)

    # LIMPIEZA: borrar solo lo creado por el verificador
    if created_booking_ids:
        with sqlite3.connect(api.DB_PATH) as conn:
            conn.executemany("DELETE FROM bookings WHERE id=?", [(b,) for b in created_booking_ids])
            conn.execute("DELETE FROM product_sales WHERE cliente_id=? AND customer_name=''", (CID,))
            conn.execute("DELETE FROM package_purchases WHERE cliente_id=? AND buyer_email='verif@example.com'", (CID,))
            conn.execute("DELETE FROM gift_cards WHERE cliente_id=? AND buyer_name='Verif'", (CID,))
            conn.commit()
    print(f"\n== RESULTADO: {PASS} OK, {FAIL} FAIL ==")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
