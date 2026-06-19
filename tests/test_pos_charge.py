from __future__ import annotations

import uuid
from types import SimpleNamespace

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies, _seed_connect_account  # noqa: F401


def _patch_stripe(api_module, monkeypatch, suffix: str) -> None:
    monkeypatch.setattr(api_module, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(
        api_module.stripe.Account, "retrieve",
        lambda account_id: SimpleNamespace(charges_enabled=True, payouts_enabled=True, details_submitted=True),
    )
    monkeypatch.setattr(
        api_module.stripe.checkout.Session, "create",
        lambda **kwargs: SimpleNamespace(id=f"cs_{suffix}", url=f"https://checkout.test/{suffix}"),
    )


def _make_product(api_module, pid: str, *, price: int, stock=None) -> None:
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO products (cliente_id, id, name, price_cents, currency, stock, is_active, sort_order, created_at, updated_at)
            VALUES ('demo', ?, ?, ?, 'eur', ?, 1, 0, ?, ?)
            """,
            (pid, f"Producto {pid}", price, stock, now, now),
        )
        connection.commit()


def test_pos_charge_product_creates_link_and_finalizes(client, api_module, monkeypatch, portal_cookies):
    suffix = uuid.uuid4().hex[:8]
    pid = f"prod_{suffix}"
    _seed_connect_account(api_module)
    _patch_stripe(api_module, monkeypatch, suffix)
    _make_product(api_module, pid, price=1500, stock=5)
    try:
        # Crea el cobro: 2 uds * 1500 = 3000.
        r = client.post("/auth/pos/charge", params={"cliente_id": "demo"}, cookies=portal_cookies,
                        json={"items": [{"product_id": pid, "qty": 2}]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["amount_cents"] == 3000 and body["payment_id"].startswith("pay_")
        assert body["url"].startswith("https://checkout.test/")
        payment_id = body["payment_id"]

        # En BD: pago POS pendiente, aun sin venta materializada.
        with api_module._get_db_connection() as conn:
            pay = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            assert pay["kind"] == "pos" and pay["status"] == "pending"
            assert conn.execute("SELECT COUNT(*) FROM product_sales WHERE customer_payment_id=?", (payment_id,)).fetchone()[0] == 0

        # Estado por endpoint: pendiente.
        st = client.get(f"/auth/pos/charge/{payment_id}", params={"cliente_id": "demo"}, cookies=portal_cookies)
        assert st.status_code == 200 and st.json()["paid"] is False

        # Webhook -> finaliza: registra venta (stripe) + descuenta stock.
        now = api_module._utc_now_iso()
        with api_module._get_db_connection() as conn:
            pay = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            api_module._finalize_pos_payment(conn, pay, now)
            conn.commit()
        with api_module._get_db_connection() as conn:
            sales = conn.execute("SELECT * FROM product_sales WHERE customer_payment_id=?", (payment_id,)).fetchall()
            assert len(sales) == 1 and sales[0]["qty"] == 2 and sales[0]["total_cents"] == 3000
            assert sales[0]["payment_method"] == "stripe" and sales[0]["status"] == "paid"
            stock = conn.execute("SELECT stock FROM products WHERE cliente_id='demo' AND id=?", (pid,)).fetchone()["stock"]
            assert stock == 3

        # Idempotente: re-finalizar no duplica ni vuelve a descontar.
        with api_module._get_db_connection() as conn:
            pay = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            api_module._finalize_pos_payment(conn, pay, api_module._utc_now_iso())
            conn.commit()
        with api_module._get_db_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM product_sales WHERE customer_payment_id=?", (payment_id,)).fetchone()[0] == 1
            assert conn.execute("SELECT stock FROM products WHERE cliente_id='demo' AND id=?", (pid,)).fetchone()["stock"] == 3
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM product_sales WHERE cliente_id='demo' AND product_id=?", (pid,))
            conn.execute("DELETE FROM products WHERE cliente_id='demo' AND id=?", (pid,))
            conn.execute("DELETE FROM customer_payments WHERE cliente_id='demo' AND kind='pos'")
            conn.execute("DELETE FROM client_payment_accounts WHERE cliente_id='demo'")
            conn.commit()


def test_qr_svg_generates_scannable_png_when_segno_available():
    """El QR se entrega como <img> PNG (data-URI): el SVG de segno usa strokes que
    al escalar quedan ilegibles. Verifica img + PNG base64 + clase para el CSS."""
    try:
        import segno  # noqa: F401
    except Exception:  # pragma: no cover
        import pytest
        pytest.skip("segno no instalado en este entorno")
    import base64
    from backend import commerce
    out = commerce._qr_svg("https://checkout.stripe.com/c/pay/cs_live_" + "x" * 120)
    assert out.startswith('<img class="vqr"')
    assert 'src="data:image/png;base64,' in out
    b64 = out.split("base64,", 1)[1].split('"', 1)[0]
    raw = base64.b64decode(b64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"  # firma PNG valida
    assert len(raw) > 200
    assert commerce._qr_svg("") == ""


def test_pos_charge_on_booking_marks_paid(client, api_module, monkeypatch, portal_cookies):
    suffix = uuid.uuid4().hex[:8]
    booking_id = f"bk_pos_{suffix}"
    _seed_connect_account(api_module)
    _patch_stripe(api_module, monkeypatch, suffix)
    now = api_module._utc_now_iso()
    base = api_module.datetime.now() + api_module.timedelta(days=10)
    api_module._store_booking({
        "id": booking_id, "cliente_id": "demo", "employee_id": "", "employee_name": "",
        "nombre": "POS Cliente", "email": "pos@example.com", "telefono": "",
        "servicio": "Masaje", "booking_date": base.strftime("%Y-%m-%d"), "booking_time": "12:00",
        "notas": "", "status": "confirmed", "provider_name": "internal", "provider_status": "confirmed",
        "provider_booking_id": "", "provider_booking_url": "", "manage_token": f"mg_{booking_id}",
        "timezone": "Europe/Madrid", "start_at": "", "end_at": "", "confirmed_at": now, "cancelled_at": "",
        "rescheduled_at": "", "rescheduled_from_booking_id": "", "confirmation_email_sent_at": "",
        "reminder_24h_sent_at": "", "reminder_2h_sent_at": "", "customer_email_status": "",
        "customer_email_last_error": "", "service_id": "masaje", "service_price_cents": 5000,
        "source": "test", "created_at": now,
    })
    try:
        r = client.post("/auth/pos/charge", params={"cliente_id": "demo"}, cookies=portal_cookies,
                        json={"items": [], "booking_id": booking_id})
        assert r.status_code == 200, r.text
        assert r.json()["amount_cents"] == 5000  # solo el servicio
        payment_id = r.json()["payment_id"]

        now2 = api_module._utc_now_iso()
        with api_module._get_db_connection() as conn:
            pay = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            api_module._finalize_pos_payment(conn, pay, now2)
            conn.commit()
        row = api_module._get_booking_row_by_id(booking_id)
        assert row["payment_status"] == "paid"
        events = [r2["event_type"] for r2 in api_module._list_booking_audit_rows(booking_id)]
        assert "booking_paid_pos" in events
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
            conn.execute("DELETE FROM booking_audit WHERE booking_id=?", (booking_id,))
            conn.execute("DELETE FROM customer_payments WHERE cliente_id='demo' AND kind='pos'")
            conn.execute("DELETE FROM client_payment_accounts WHERE cliente_id='demo'")
            conn.commit()
