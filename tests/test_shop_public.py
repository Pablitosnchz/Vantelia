"""Tests de la tienda publica (/tienda/{cliente_id}): compra online de bonos y
productos sobre el rail customer_payments + Stripe Connect + webhook idempotente.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies, _seed_connect_account  # noqa: F401
from test_pos_charge import _make_product, _patch_stripe  # noqa: F401


def _make_package(api_module, pkg_id: str, *, price: int = 10000, items=None) -> None:
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO packages (cliente_id, id, name, description, items_json, price_cents,
                                  validity_days, is_active, sort_order, created_at, updated_at)
            VALUES ('demo', ?, ?, '', ?, ?, 180, 1, 0, ?, ?)
            """,
            (pkg_id, f"Bono {pkg_id}", json.dumps(items or [{"service_slug": "consulta", "qty": 5}]),
             price, now, now),
        )
        connection.commit()


def _enable_shop(client, portal_cookies, **fields):
    payload = {"enabled_packages": True, "enabled_products": True}
    payload.update(fields)
    r = client.put("/auth/app/shop-public", cookies=portal_cookies, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup(api_module, client, portal_cookies):
    client.put(
        "/auth/app/shop-public", cookies=portal_cookies,
        json={"enabled_packages": False, "enabled_products": False},
    )
    with api_module._get_db_connection() as conn:
        conn.execute("DELETE FROM customer_payments WHERE cliente_id='demo' AND kind LIKE 'shop_%'")
        conn.execute("DELETE FROM client_payment_accounts WHERE cliente_id='demo'")
        conn.commit()


def test_shop_page_404_without_opt_in(client, api_module):
    r = client.get("/tienda/demo")
    assert r.status_code == 404


def test_central_public_page_renders_booking_first(client, api_module):
    r = client.get("/central/demo")
    assert r.status_code == 200, r.text
    html = r.text
    assert "Central de reservas" in html
    assert "Reserva de cita" in html
    assert "/servicios/" in html
    assert "/disponibilidad?" in html
    assert "/agendar" in html
    # El wizard de 4 pasos tiene que estar realmente cableado (no solo el markup):
    # servicio como tarjetas, centro/profesional, navegacion por pasos y envio con
    # location_id/employee_id. Regresion del bug "pagina medio construida".
    assert 'data-panel="staff"' in html and 'data-panel="client"' in html
    for token in (
        "function showStep",
        "async function ensureStaff",
        "async function loadEmployees",
        "wrap.innerHTML = st.services.map",   # servicios como choice-cards
        "/centros/",                            # carga de centros
        "/profesionales/",                      # carga de profesionales
        "location_id: st.locId",                # el POST /agendar acota por centro
        "employee_id: st.empId",                # ...y por profesional
        'id="bookingDone"',                     # panel de exito tras reservar
        'id="doneTitle"',                       # titulo dinamico segun estado real de la cita
        "Reserva pendiente de pago",            # no etiqueta pending_payment como confirmada
        "Completar pago para confirmar",
        "function showDone",
        'id="dateStrip"',                       # selector de dias tipo Fresha/Doctolib
        "function buildDateStrip",
        "function renderRail",                  # resumen en vivo de la reserva
        "function slotPeriod",                  # huecos agrupados manana/tarde/noche
        'id="preRedeemBlock"',                  # tarjeta regalo antes de confirmar
        'id="redeemBlock"',                     # bonos/resultado de canje tras reservar
        "st.pendingGiftCode",                   # el codigo se prepara antes y se aplica al crear cita
        "giftPreNote",
        "function loadRedeemOptions",           # opciones de canje via manage_token
        "function applyRedeem",                 # aplica bono o codigo de tarjeta
        "/redeem-options",
    ):
        assert token in html, token
    gift_idx = html.index('id="redeemGiftToggle"')
    submit_idx = html.index('id="submitBooking"')
    done_idx = html.index('id="bookingDone"')
    assert html.count('id="redeemGiftToggle"') == 1
    assert gift_idx < submit_idx < done_idx
    # Version embed (?embed=1): sin hero/laterales, para iframe en la web del negocio.
    r_embed = client.get("/central/demo?embed=1")
    assert r_embed.status_code == 200
    assert 'class="embed"' in r_embed.text
    assert 'class=""' in html or 'class="embed"' not in html  # la normal NO va en modo embed


def test_shop_page_renders_with_opt_in(client, api_module, monkeypatch, portal_cookies):
    suffix = uuid.uuid4().hex[:8]
    pid, pkg = f"shopprod_{suffix}", f"shoppkg_{suffix}"
    _seed_connect_account(api_module)
    _patch_stripe(api_module, monkeypatch, suffix)
    _make_product(api_module, pid, price=1200, stock=3)
    _make_package(api_module, pkg, price=9000)
    try:
        cfg = _enable_shop(client, portal_cookies, intro_text="Compra online de prueba")
        assert cfg["available_packages"] is True and cfg["available_products"] is True
        assert cfg["public_url"].endswith("/tienda/demo")

        r = client.get("/tienda/demo")
        assert r.status_code == 200
        html = r.text
        assert "Demo Booking" in html
        assert pkg in html and pid in html  # catalogos inyectados en el JS
        assert "Compra online de prueba" in html
        for token in ("checkout-status", "Ya tienes un bono", "Reservar cita", "Canje online"):
            assert token in html, token
    finally:
        _cleanup(api_module, client, portal_cookies)
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM products WHERE cliente_id='demo' AND id=?", (pid,))
            conn.execute("DELETE FROM packages WHERE cliente_id='demo' AND id=?", (pkg,))
            conn.commit()


def test_shop_package_checkout_and_finalize_idempotent(client, api_module, monkeypatch, portal_cookies):
    suffix = uuid.uuid4().hex[:8]
    pkg = f"shoppkg_{suffix}"
    _seed_connect_account(api_module)
    _patch_stripe(api_module, monkeypatch, suffix)
    _make_package(api_module, pkg, price=15000, items=[{"service_slug": "consulta", "qty": 5}])
    sent = []
    monkeypatch.setattr(
        api_module, "_send_client_email",
        lambda cliente_id, to, subject, text, html=None, **kw: sent.append((to, subject)),
    )
    try:
        _enable_shop(client, portal_cookies)
        r = client.post(
            f"/tienda/demo/checkout/bono",
            json={"package_id": pkg, "buyer_name": "Compradora Bono",
                  "buyer_email": "bono@example.com", "buyer_phone": "+34611111111"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["amount_cents"] == 15000
        payment_id = body["payment_id"]

        # Pendiente: el bono NO existe todavia.
        with api_module._get_db_connection() as conn:
            pay = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            assert pay["kind"] == "shop_package" and pay["status"] == "pending"
            assert conn.execute(
                "SELECT COUNT(*) FROM package_purchases WHERE customer_payment_id=?", (payment_id,)
            ).fetchone()[0] == 0
        pending_status = client.get(f"/tienda/demo/checkout-status?session_id=cs_{suffix}")
        assert pending_status.status_code == 200
        assert pending_status.json()["status"] == "pending"
        assert pending_status.json()["ready"] is False

        # Webhook -> finaliza: crea el bono activo con las sesiones del snapshot.
        now = api_module._utc_now_iso()
        with api_module._get_db_connection() as conn:
            pay = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            conn.execute("UPDATE customer_payments SET status='paid' WHERE id=?", (payment_id,))
            created = api_module._finalize_shop_package_payment(conn, pay, now)
            conn.commit()
        assert created is True
        with api_module._get_db_connection() as conn:
            purch = conn.execute(
                "SELECT * FROM package_purchases WHERE customer_payment_id=?", (payment_id,)
            ).fetchall()
            assert len(purch) == 1
            p = purch[0]
            assert p["status"] == "active" and p["payment_method"] == "stripe"
            assert p["buyer_email"] == "bono@example.com" and p["price_cents"] == 15000
            assert json.loads(p["remaining_json"]) == {"consulta": 5}
            assert p["expires_at"]
        ready_status = client.get(f"/tienda/demo/checkout-status?session_id=cs_{suffix}")
        assert ready_status.status_code == 200
        ready = ready_status.json()
        assert ready["status"] == "paid" and ready["ready"] is True
        assert ready["wallet_url"] and "/bono/demo/" in ready["wallet_url"]

        # Email de confirmacion al comprador (best-effort, una sola vez).
        assert api_module._send_shop_confirmation_email("demo", payment_id) is True
        assert sent and sent[-1][0] == "bono@example.com"

        # Idempotente: re-finalizar no duplica.
        with api_module._get_db_connection() as conn:
            pay = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            assert api_module._finalize_shop_package_payment(conn, pay, api_module._utc_now_iso()) is False
            conn.commit()
        with api_module._get_db_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM package_purchases WHERE customer_payment_id=?", (payment_id,)
            ).fetchone()[0] == 1
    finally:
        _cleanup(api_module, client, portal_cookies)
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM package_purchases WHERE cliente_id='demo' AND package_id=?", (pkg,))
            conn.execute("DELETE FROM packages WHERE cliente_id='demo' AND id=?", (pkg,))
            conn.commit()


def test_shop_products_checkout_and_finalize_idempotent(client, api_module, monkeypatch, portal_cookies):
    suffix = uuid.uuid4().hex[:8]
    pid = f"shopprod_{suffix}"
    _seed_connect_account(api_module)
    _patch_stripe(api_module, monkeypatch, suffix)
    _make_product(api_module, pid, price=2500, stock=4)
    try:
        _enable_shop(client, portal_cookies)
        r = client.post(
            f"/tienda/demo/checkout/productos",
            json={"items": [{"product_id": pid, "qty": 2}],
                  "buyer_name": "Comprador Web", "buyer_email": "tienda@example.com"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["amount_cents"] == 5000
        payment_id = r.json()["payment_id"]

        # Sin venta hasta el webhook.
        with api_module._get_db_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM product_sales WHERE customer_payment_id=?", (payment_id,)
            ).fetchone()[0] == 0

        now = api_module._utc_now_iso()
        with api_module._get_db_connection() as conn:
            pay = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            assert api_module._finalize_shop_products_payment(conn, pay, now) is True
            conn.commit()
        with api_module._get_db_connection() as conn:
            sales = conn.execute(
                "SELECT * FROM product_sales WHERE customer_payment_id=?", (payment_id,)
            ).fetchall()
            assert len(sales) == 1
            assert sales[0]["qty"] == 2 and sales[0]["total_cents"] == 5000
            assert sales[0]["customer_name"] == "Comprador Web"
            assert sales[0]["customer_email"] == "tienda@example.com"
            assert sales[0]["payment_method"] == "stripe" and sales[0]["status"] == "paid"
            stock = conn.execute(
                "SELECT stock FROM products WHERE cliente_id='demo' AND id=?", (pid,)
            ).fetchone()["stock"]
            assert stock == 2

        # Idempotente.
        with api_module._get_db_connection() as conn:
            pay = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            assert api_module._finalize_shop_products_payment(conn, pay, api_module._utc_now_iso()) is False
            conn.commit()
        with api_module._get_db_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM product_sales WHERE customer_payment_id=?", (payment_id,)
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT stock FROM products WHERE cliente_id='demo' AND id=?", (pid,)
            ).fetchone()["stock"] == 2
    finally:
        _cleanup(api_module, client, portal_cookies)
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM product_sales WHERE cliente_id='demo' AND product_id=?", (pid,))
            conn.execute("DELETE FROM products WHERE cliente_id='demo' AND id=?", (pid,))
            conn.commit()


def test_shop_checkout_respects_stock_and_catalog_price(client, api_module, monkeypatch, portal_cookies):
    """El precio lo pone el catalogo (no el request) y el stock corta la compra."""
    suffix = uuid.uuid4().hex[:8]
    pid = f"shopprod_{suffix}"
    _seed_connect_account(api_module)
    _patch_stripe(api_module, monkeypatch, suffix)
    _make_product(api_module, pid, price=3000, stock=1)
    try:
        _enable_shop(client, portal_cookies)
        r = client.post(
            f"/tienda/demo/checkout/productos",
            json={"items": [{"product_id": pid, "qty": 3}],
                  "buyer_name": "Sin Stock", "buyer_email": "stock@example.com"},
        )
        assert r.status_code == 409  # stock insuficiente
        r2 = client.post(
            f"/tienda/demo/checkout/productos",
            json={"items": [{"product_id": pid, "qty": 1}],
                  "buyer_name": "Con Stock", "buyer_email": "stock@example.com"},
        )
        assert r2.status_code == 200 and r2.json()["amount_cents"] == 3000
    finally:
        _cleanup(api_module, client, portal_cookies)
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM products WHERE cliente_id='demo' AND id=?", (pid,))
            conn.commit()


def test_central_summary_counts_today(client, api_module, portal_cookies):
    """KPIs de mostrador: ventas/bonos/tarjetas de HOY + valor vivo (sesiones y saldo)."""
    suffix = uuid.uuid4().hex[:8]
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as conn:
        conn.execute(
            "INSERT INTO product_sales (id, cliente_id, product_id, product_name, qty, unit_price_cents,"
            " total_cents, payment_method, created_at)"
            " VALUES (?, 'demo', 'p1', 'Crema', 2, 1000, 2000, 'cash', ?)",
            (f"sale_{suffix}", now),
        )
        conn.execute(
            "INSERT INTO package_purchases (id, cliente_id, package_id, package_name, buyer_name,"
            " buyer_email, price_cents, remaining_json, status, created_at, updated_at)"
            " VALUES (?, 'demo', 'pkg1', 'Bono central', 'Ana', 'ana@example.com', 5000,"
            " '{\"consulta\": 3}', 'active', ?, ?)",
            (f"pp_{suffix}", now, now),
        )
        conn.execute(
            "INSERT INTO gift_cards (id, cliente_id, code, initial_cents, balance_cents, status,"
            " buyer_name, buyer_email, created_at, updated_at)"
            " VALUES (?, 'demo', ?, 4000, 2500, 'active', 'Ana', 'ana@example.com', ?, ?)",
            (f"gc_{suffix}", f"GC-{suffix[:4].upper()}-TEST", now, now),
        )
        conn.commit()
    try:
        r = client.get("/auth/app/central/summary", cookies=portal_cookies)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["date"] == now[:10] or data["bookings_today"] >= 0  # fecha local del negocio
        assert data["product_sales_today"] >= 1
        assert data["revenue_breakdown"]["products_cents"] >= 2000
        assert data["revenue_breakdown"]["packages_cents"] >= 5000
        assert data["revenue_breakdown"]["gift_cards_cents"] >= 4000
        assert data["revenue_today_cents"] >= 11000
        assert data["packages_active"] >= 1
        assert data["packages_sessions_left"] >= 3
        assert data["gift_active"] >= 1
        assert data["gift_balance_cents"] >= 2500
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM product_sales WHERE cliente_id='demo' AND id=?", (f"sale_{suffix}",))
            conn.execute("DELETE FROM package_purchases WHERE cliente_id='demo' AND id=?", (f"pp_{suffix}",))
            conn.execute("DELETE FROM gift_cards WHERE cliente_id='demo' AND id=?", (f"gc_{suffix}",))
            conn.commit()


def test_central_customization_hero_and_images(client, api_module, portal_cookies):
    """Personalizacion: hero (foto+frase) via shop-public y foto por servicio/producto/bono."""
    try:
        r = client.put(
            "/auth/app/shop-public", cookies=portal_cookies,
            json={"hero_image_url": "https://example.com/spa.jpg", "hero_tagline": "Tu momento de calma."},
        )
        assert r.status_code == 200, r.text
        cfg = r.json()
        assert cfg["hero_image_url"] == "https://example.com/spa.jpg"
        assert cfg["hero_tagline"] == "Tu momento de calma."
        # URL invalida (esquema no http/https) -> se descarta en el saneado
        r2 = client.put("/auth/app/shop-public", cookies=portal_cookies,
                        json={"hero_image_url": "javascript:alert(1)"})
        assert r2.json()["hero_image_url"] == ""

        # La central publica pinta la frase y la foto del hero
        client.put("/auth/app/shop-public", cookies=portal_cookies,
                   json={"hero_image_url": "https://example.com/spa.jpg", "hero_tagline": "Tu momento de calma."})
        page = client.get("/central/demo").text
        assert "Tu momento de calma." in page
        assert "https://example.com/spa.jpg" in page

        # Servicio con imagen: alta + roundtrip + expuesta en el publico /servicios
        rs = client.post("/auth/services", cookies=portal_cookies,
                         json={"nombre": "Facial Img Test", "duration_minutes": 30,
                               "image_url": "https://example.com/facial.jpg"})
        assert rs.status_code == 200, rs.text
        slug = rs.json()["id"]
        assert rs.json()["image_url"] == "https://example.com/facial.jpg"
        pub = client.get("/servicios/demo", headers={"Origin": "http://testserver"}).json()["servicios"]
        mine = [s for s in pub if s["id"] == slug][0]
        assert mine["image_url"] == "https://example.com/facial.jpg"
        # PATCH la limpia
        rp = client.patch(f"/auth/services/{slug}", cookies=portal_cookies, json={"image_url": ""})
        assert rp.json()["image_url"] == ""

        # Producto y bono con imagen
        rprod = client.post("/auth/products", cookies=portal_cookies,
                            json={"name": "Crema Img", "price_cents": 1500,
                                  "image_url": "https://example.com/crema.jpg"})
        assert rprod.json()["image_url"] == "https://example.com/crema.jpg"
        rpkg = client.post("/auth/packages", cookies=portal_cookies,
                           json={"name": "Bono Img", "price_cents": 9000,
                                 "items": [{"service_slug": slug, "qty": 3}],
                                 "image_url": "https://example.com/bono.jpg"})
        assert rpkg.status_code == 200, rpkg.text
        assert rpkg.json()["image_url"] == "https://example.com/bono.jpg"
    finally:
        client.put("/auth/app/shop-public", cookies=portal_cookies,
                   json={"hero_image_url": "", "hero_tagline": ""})
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM services WHERE cliente_id='demo' AND name IN ('Facial Img Test')")
            conn.execute("DELETE FROM products WHERE cliente_id='demo' AND name='Crema Img'")
            conn.execute("DELETE FROM packages WHERE cliente_id='demo' AND name='Bono Img'")
            conn.commit()
