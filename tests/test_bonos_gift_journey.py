"""Viaje completo de bonos y tarjetas regalo (jul 2026):

- Consulta publica de saldo (/gift/{c}/saldo) con codigo tolerante (sin guiones,
  minusculas, sin prefijo GC).
- Wallet publica del bono (/bono/{c}/{wallet_token}) + email de venta con enlace.
- Canje ONLINE tras reservar en la central (manage_token autoriza): bono detectado
  por contacto de la reserva y tarjeta por codigo, con canje atomico (CAS).
- Reembolso que revierte el activo emitido (guard 'forzar' + revert idempotente).
"""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401


def _tomorrow(api_module) -> str:
    return (api_module._utc_now() + timedelta(days=1)).date().isoformat()


def _make_booking(api_module, suffix: str, *, email: str = "", phone: str = "",
                  price: int = 4000, service_slug: str = "consulta") -> tuple:
    booking_id = f"bk_journey_{suffix}"
    token = f"mg_journey_{suffix}"
    now = api_module._utc_now_iso()
    # Hora derivada del suffix: evita el UNIQUE (cliente, empleado, dia, hora).
    hora = f"{9 + int(suffix[:2], 16) % 8:02d}:{(int(suffix[2:4], 16) % 4) * 15:02d}"
    with api_module._get_db_connection() as conn:
        conn.execute(
            "INSERT INTO bookings (id, cliente_id, employee_id, employee_name, nombre, email, "
            "telefono, servicio, booking_date, booking_time, notas, status, provider_name, "
            "provider_status, manage_token, timezone, service_id, service_price_cents, "
            "payment_status, source, created_at) "
            "VALUES (?, 'demo', '', '', 'Cliente Journey', ?, ?, 'Consulta', ?, ?, '', "
            "'confirmed', 'internal', 'internal', ?, 'Europe/Madrid', ?, ?, '', 'test', ?)",
            (booking_id, email, phone, _tomorrow(api_module), hora, token, service_slug, price, now),
        )
        conn.commit()
    return booking_id, token


def _make_gift(api_module, suffix: str, *, initial: int = 5000, balance: int = None,
               payment_id: str = "") -> str:
    code = f"GC-{suffix[:4].upper()}-{suffix[4:8].upper()}"
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as conn:
        conn.execute(
            "INSERT INTO gift_cards (id, cliente_id, code, initial_cents, balance_cents, status, "
            "buyer_name, buyer_email, customer_payment_id, created_at, updated_at) "
            "VALUES (?, 'demo', ?, ?, ?, 'active', 'Regaladora', 'buyer@example.com', ?, ?, ?)",
            (f"gc_journey_{suffix}", code, initial,
             initial if balance is None else balance, payment_id, now, now),
        )
        conn.commit()
    return code


def _make_purchase(api_module, suffix: str, *, buyer_email: str = "", buyer_phone: str = "",
                   sessions: dict = None, payment_id: str = "", status: str = "active") -> str:
    purchase_id = f"pkp_journey_{suffix}"
    sessions = sessions or {"consulta": 2}
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as conn:
        conn.execute(
            "INSERT INTO package_purchases (id, cliente_id, package_id, package_name, buyer_name, "
            "buyer_email, buyer_phone, price_cents, remaining_json, initial_json, wallet_token, "
            "expires_at, status, payment_method, customer_payment_id, created_at, updated_at) "
            "VALUES (?, 'demo', 'pkgj', 'Bono Journey', 'Cliente Journey', ?, ?, 9000, ?, ?, ?, "
            "'', ?, 'cash', ?, ?, ?)",
            (purchase_id, buyer_email, buyer_phone, json.dumps(sessions), json.dumps(sessions),
             f"pw_journey_{suffix}", status, payment_id, now, now),
        )
        conn.commit()
    return purchase_id


def _make_customer_payment(api_module, suffix: str, *, kind: str, amount: int) -> str:
    payment_id = f"pay_journey_{suffix}"
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as conn:
        conn.execute(
            "INSERT INTO customer_payments (id, cliente_id, contact_id, booking_id, service_id, "
            "service_name, stripe_account_id, stripe_checkout_session_id, stripe_payment_intent_id, "
            "amount_cents, currency, status, checkout_url, kind, line_items_json, created_at, updated_at) "
            "VALUES (?, 'demo', '', '', '', '', 'acct_test', ?, ?, ?, 'eur', 'paid', '', ?, '{}', ?, ?)",
            (payment_id, f"cs_j_{suffix}", f"pi_j_{suffix}", amount, kind, now, now),
        )
        conn.commit()
    return payment_id


def _cleanup_journey(api_module):
    with api_module._get_db_connection() as conn:
        conn.execute("DELETE FROM bookings WHERE id LIKE 'bk_journey_%'")
        conn.execute("DELETE FROM gift_cards WHERE id LIKE 'gc_journey_%'")
        conn.execute("DELETE FROM gift_card_transactions WHERE gift_card_id LIKE 'gc_journey_%'")
        conn.execute("DELETE FROM package_purchases WHERE id LIKE 'pkp_journey_%'")
        conn.execute("DELETE FROM customer_payments WHERE id LIKE 'pay_journey_%'")
        conn.execute("DELETE FROM booking_audit WHERE booking_id LIKE 'bk_journey_%'")
        conn.commit()


# --- Consulta publica de saldo ------------------------------------------------------

def test_gift_balance_page_and_tolerant_code_lookup(client, api_module):
    suffix = uuid.uuid4().hex[:8]
    code = _make_gift(api_module, suffix, initial=5000, balance=4000)
    try:
        page = client.get("/gift/demo/saldo")
        assert page.status_code == 200
        assert "Consulta tu saldo" in page.text
        assert "Saldo disponible" in page.text

        # Codigo canonico, en minusculas, sin guiones y sin prefijo: mismos datos.
        compact = code.replace("-", "")
        for variant in (code, code.lower(), compact, compact[2:]):
            r = client.post("/gift/demo/saldo", json={"code": variant})
            assert r.status_code == 200, (variant, r.text)
            data = r.json()
            assert data["code"] == code
            assert data["balance_cents"] == 4000
            assert data["initial_cents"] == 5000
            assert data["status"] == "active"

        assert client.post("/gift/demo/saldo", json={"code": "GC-ZZZZ-9999"}).status_code == 404
    finally:
        _cleanup_journey(api_module)


# --- Wallet publica del bono --------------------------------------------------------

def test_package_wallet_page_and_sale_email_with_link(client, api_module, monkeypatch, portal_cookies):
    suffix = uuid.uuid4().hex[:8]
    pkg_id = f"pkgj_{suffix}"
    now = api_module._utc_now_iso()
    with api_module._get_db_connection() as conn:
        conn.execute(
            "INSERT INTO packages (cliente_id, id, name, description, items_json, price_cents, "
            "validity_days, is_active, sort_order, created_at, updated_at) "
            "VALUES ('demo', ?, 'Bono Wallet Test', '', ?, 12000, 90, 1, 0, ?, ?)",
            (pkg_id, json.dumps([{"service_slug": "consulta", "qty": 3}]), now, now),
        )
        conn.commit()
    sent = []
    monkeypatch.setattr(
        api_module, "_send_client_email",
        lambda cliente_id, to, subject, text, html=None, **kw: sent.append((to, subject, text)),
    )
    try:
        r = client.post(
            f"/auth/packages/{pkg_id}/sell", cookies=portal_cookies,
            json={"buyer_name": "Ana Wallet", "buyer_email": "wallet@example.com"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # La venta expone la wallet publica y el snapshot inicial.
        assert data["wallet_url"] and "/bono/demo/" in data["wallet_url"]
        assert data["remaining_total"] == 3 and data["initial_total"] == 3 and data["used_total"] == 0
        # El comprador recibe su bono digital con el enlace.
        assert sent and sent[-1][0] == "wallet@example.com"
        assert data["wallet_url"] in sent[-1][2]

        wallet_path = data["wallet_url"].split("://", 1)[-1].split("/", 1)[1]
        page = client.get("/" + wallet_path)
        assert page.status_code == 200
        assert "Bono Wallet Test" in page.text
        assert "sesiones disponibles" in page.text
        assert "quedan 3 de 3" in page.text

        assert client.get("/bono/demo/pw_no_existe").status_code == 404
    finally:
        with api_module._get_db_connection() as conn:
            conn.execute("DELETE FROM packages WHERE cliente_id='demo' AND id=?", (pkg_id,))
            conn.execute("DELETE FROM package_purchases WHERE cliente_id='demo' AND package_id=?", (pkg_id,))
            conn.commit()


# --- Canje online tras reservar (central) -------------------------------------------

def test_central_redeem_package_marks_booking_paid(client, api_module):
    suffix = uuid.uuid4().hex[:8]
    booking_id, token = _make_booking(api_module, suffix, email="bono.central@example.com", price=4000)
    purchase_id = _make_purchase(api_module, suffix, buyer_email="bono.central@example.com",
                                 sessions={"consulta": 2})
    try:
        r = client.post("/central/demo/redeem-options", json={"manage_token": token})
        assert r.status_code == 200, r.text
        opts = r.json()
        assert opts["can_redeem"] is True
        assert opts["price_cents"] == 4000
        assert len(opts["packages"]) == 1
        assert opts["packages"][0]["purchase_id"] == purchase_id
        assert opts["packages"][0]["sessions_left"] == 2

        r2 = client.post("/central/demo/redeem",
                         json={"manage_token": token, "kind": "package", "purchase_id": purchase_id})
        assert r2.status_code == 200, r2.text
        assert r2.json()["covered"] is True and r2.json()["sessions_left"] == 1

        with api_module._get_db_connection() as conn:
            row = conn.execute("SELECT payment_status FROM bookings WHERE id=?", (booking_id,)).fetchone()
            assert row["payment_status"] == "paid"
            purch = conn.execute("SELECT remaining_json FROM package_purchases WHERE id=?", (purchase_id,)).fetchone()
            assert json.loads(purch["remaining_json"]) == {"consulta": 1}

        # Cita ya pagada: no hay mas canje.
        assert client.post("/central/demo/redeem-options", json={"manage_token": token}).json()["can_redeem"] is False
        r3 = client.post("/central/demo/redeem",
                         json={"manage_token": token, "kind": "package", "purchase_id": purchase_id})
        assert r3.status_code == 409
    finally:
        _cleanup_journey(api_module)


def test_central_redeem_rejects_foreign_package_and_bad_token(client, api_module):
    suffix = uuid.uuid4().hex[:8]
    _, token = _make_booking(api_module, suffix, email="titular@example.com")
    foreign = _make_purchase(api_module, suffix, buyer_email="otra.persona@example.com")
    try:
        # El bono de otra persona ni aparece ni se puede canjear.
        opts = client.post("/central/demo/redeem-options", json={"manage_token": token}).json()
        assert opts["packages"] == []
        r = client.post("/central/demo/redeem",
                        json={"manage_token": token, "kind": "package", "purchase_id": foreign})
        assert r.status_code == 404
        # manage_token invalido -> 404.
        assert client.post("/central/demo/redeem-options",
                           json={"manage_token": "mg_no_existe_123"}).status_code == 404
    finally:
        _cleanup_journey(api_module)


def test_central_redeem_gift_partial_and_full(client, api_module):
    suffix = uuid.uuid4().hex[:8]
    booking_id, token = _make_booking(api_module, suffix, email="gift.central@example.com", price=5000)
    code = _make_gift(api_module, suffix, initial=3000)
    try:
        r = client.post("/central/demo/redeem",
                        json={"manage_token": token, "kind": "gift", "code": code.lower()})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["covered"] is False
        assert data["charged_cents"] == 3000 and data["remaining_due_cents"] == 2000
        with api_module._get_db_connection() as conn:
            assert conn.execute("SELECT payment_status FROM bookings WHERE id=?", (booking_id,)).fetchone()[0] != "paid"
            card = conn.execute("SELECT balance_cents, status FROM gift_cards WHERE code=? AND cliente_id='demo'", (code,)).fetchone()
            assert card["balance_cents"] == 0 and card["status"] == "redeemed"

        # Cobertura total en otra cita: cita pagada y saldo descontado.
        suffix2 = uuid.uuid4().hex[:8]
        booking2, token2 = _make_booking(api_module, suffix2, email="gift2@example.com", price=4000)
        code2 = _make_gift(api_module, suffix2, initial=10000)
        r2 = client.post("/central/demo/redeem",
                         json={"manage_token": token2, "kind": "gift", "code": code2})
        assert r2.status_code == 200
        assert r2.json()["covered"] is True and r2.json()["balance_after_cents"] == 6000
        with api_module._get_db_connection() as conn:
            assert conn.execute("SELECT payment_status FROM bookings WHERE id=?", (booking2,)).fetchone()[0] == "paid"
    finally:
        _cleanup_journey(api_module)


# --- Reembolso que revierte el activo -----------------------------------------------

def test_refund_guard_and_revert_gift_card(api_module):
    suffix = uuid.uuid4().hex[:8]
    payment_id = _make_customer_payment(api_module, suffix, kind="gift_card", amount=5000)
    code = _make_gift(api_module, suffix, initial=5000, payment_id=payment_id)
    try:
        with api_module._get_db_connection() as conn:
            payment = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
        # Sin consumo: el reembolso completo pasa sin 'forzar'.
        api_module._guard_refundable_asset(payment, None, False)

        # Revert total: tarjeta anulada a saldo 0 con movimiento 'refund'.
        now = api_module._utc_now_iso()
        with api_module._get_db_connection() as conn:
            api_module._revert_assets_after_refund(conn, payment, 5000, now)
            conn.commit()
        with api_module._get_db_connection() as conn:
            card = conn.execute("SELECT * FROM gift_cards WHERE code=? AND cliente_id='demo'", (code,)).fetchone()
            assert card["balance_cents"] == 0 and card["status"] == "disabled"
            txs = conn.execute(
                "SELECT COUNT(*) FROM gift_card_transactions WHERE gift_card_id=? AND kind='refund'",
                (card["id"],),
            ).fetchone()[0]
            assert txs == 1
        # Idempotente (reintento del webhook): sin doble retirada.
        with api_module._get_db_connection() as conn:
            api_module._revert_assets_after_refund(conn, payment, 5000, api_module._utc_now_iso())
            conn.commit()
        with api_module._get_db_connection() as conn:
            card = conn.execute("SELECT * FROM gift_cards WHERE code=? AND cliente_id='demo'", (code,)).fetchone()
            assert conn.execute(
                "SELECT COUNT(*) FROM gift_card_transactions WHERE gift_card_id=? AND kind='refund'",
                (card["id"],),
            ).fetchone()[0] == 1
    finally:
        _cleanup_journey(api_module)


def test_refund_guard_requires_force_when_gift_spent(api_module):
    import pytest
    from fastapi import HTTPException

    suffix = uuid.uuid4().hex[:8]
    payment_id = _make_customer_payment(api_module, suffix, kind="gift_card", amount=5000)
    _make_gift(api_module, suffix, initial=5000, balance=2000, payment_id=payment_id)
    try:
        with api_module._get_db_connection() as conn:
            payment = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
        with pytest.raises(HTTPException) as exc:
            api_module._guard_refundable_asset(payment, None, False)
        assert exc.value.status_code == 409
        assert "forzar" in exc.value.detail
        # Con force pasa; y un reembolso parcial <= saldo tampoco exige force.
        api_module._guard_refundable_asset(payment, None, True)
        api_module._guard_refundable_asset(payment, 2000, False)
    finally:
        _cleanup_journey(api_module)


def test_refund_partial_gift_reduces_balance_to_target(api_module):
    suffix = uuid.uuid4().hex[:8]
    payment_id = _make_customer_payment(api_module, suffix, kind="gift_card", amount=5000)
    code = _make_gift(api_module, suffix, initial=5000, payment_id=payment_id)
    try:
        with api_module._get_db_connection() as conn:
            payment = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
            api_module._revert_assets_after_refund(conn, payment, 1500, api_module._utc_now_iso())
            conn.commit()
        with api_module._get_db_connection() as conn:
            card = conn.execute("SELECT * FROM gift_cards WHERE code=? AND cliente_id='demo'", (code,)).fetchone()
            assert card["balance_cents"] == 3500 and card["status"] == "active"
    finally:
        _cleanup_journey(api_module)


def test_refund_full_cancels_online_package(api_module):
    import pytest
    from fastapi import HTTPException

    suffix = uuid.uuid4().hex[:8]
    payment_id = _make_customer_payment(api_module, suffix, kind="shop_package", amount=9000)
    purchase_id = _make_purchase(api_module, suffix, buyer_email="rf@example.com", payment_id=payment_id)
    try:
        with api_module._get_db_connection() as conn:
            payment = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment_id,)).fetchone()
        api_module._guard_refundable_asset(payment, None, False)  # sin sesiones usadas
        with api_module._get_db_connection() as conn:
            api_module._revert_assets_after_refund(conn, payment, 9000, api_module._utc_now_iso())
            conn.commit()
        with api_module._get_db_connection() as conn:
            assert conn.execute(
                "SELECT status FROM package_purchases WHERE id=?", (purchase_id,)
            ).fetchone()[0] == "cancelled"

        # Bono con consumo: el guard exige 'forzar'.
        suffix2 = uuid.uuid4().hex[:8]
        payment2 = _make_customer_payment(api_module, suffix2, kind="shop_package", amount=9000)
        _make_purchase(api_module, suffix2, buyer_email="rf2@example.com",
                       payment_id=payment2, sessions={"consulta": 2})
        with api_module._get_db_connection() as conn:
            conn.execute(
                "UPDATE package_purchases SET remaining_json=? WHERE customer_payment_id=?",
                (json.dumps({"consulta": 1}), payment2),
            )
            conn.commit()
            payment_row = conn.execute("SELECT * FROM customer_payments WHERE id=?", (payment2,)).fetchone()
        with pytest.raises(HTTPException) as exc:
            api_module._guard_refundable_asset(payment_row, None, False)
        assert exc.value.status_code == 409 and "forzar" in exc.value.detail
        api_module._guard_refundable_asset(payment_row, None, True)
    finally:
        _cleanup_journey(api_module)


# --- IA + worker de retencion ------------------------------------------------------


def test_ai_package_lookup_and_auto_redeem_by_verified_phone(api_module):
    suffix = uuid.uuid4().hex[:8]
    phone = "+34 600 111 222"
    booking_id, _token = _make_booking(api_module, suffix, phone=phone, price=4000)
    _make_purchase(api_module, suffix, buyer_phone="600111222", sessions={"consulta": 2})
    try:
        assert api_module._message_requests_package_balance("cuantas sesiones me quedan del bono")

        summary = api_module.packages_summary_for_contact("demo", phone=phone)
        assert summary["count"] == 1
        assert "2 de 2 sesiones" in summary["mensaje"]

        voice_result = api_module._voice_lookup_packages("demo", from_number=phone)
        assert voice_result["ok"] is True
        assert voice_result["count"] == 1

        redeemed = api_module.auto_redeem_package_for_booking("demo", booking_id, extra_phone=phone)
        assert redeemed["sessions_left"] == 1
        with api_module._get_db_connection() as conn:
            row = conn.execute("SELECT payment_status FROM bookings WHERE id=?", (booking_id,)).fetchone()
            assert row["payment_status"] == "paid"
            purchase = conn.execute(
                "SELECT remaining_json FROM package_purchases WHERE id LIKE 'pkp_journey_%'"
            ).fetchone()
            assert json.loads(purchase["remaining_json"]) == {"consulta": 1}

        # Idempotente en reservas ya pagadas: no descuenta otra sesion.
        assert api_module.auto_redeem_package_for_booking("demo", booking_id, extra_phone=phone) is None
    finally:
        _cleanup_journey(api_module)


def test_commerce_lifecycle_notices_send_expiry_and_rebuy(api_module, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    old = (api_module._utc_now() - timedelta(days=20)).isoformat()
    soon = (api_module._utc_now() + timedelta(days=5)).isoformat()
    recent = api_module._utc_now_iso()
    package_expiring = _make_purchase(
        api_module, suffix, buyer_email="expiring@example.com",
        sessions={"consulta": 2},
    )
    package_used = _make_purchase(
        api_module, "u" + suffix[:7], buyer_email="rebuy@example.com",
        sessions={"consulta": 0}, status="used",
    )
    gift_code = _make_gift(api_module, suffix, initial=7000)
    sent = []
    monkeypatch.setattr(
        api_module, "_send_client_email",
        lambda cliente_id, to, subject, text, html=None, **kw: sent.append((to, subject, text)) or True,
    )
    try:
        with api_module._get_db_connection() as conn:
            conn.execute(
                "UPDATE package_purchases SET created_at=?, expires_at=? WHERE id=?",
                (old, soon, package_expiring),
            )
            conn.execute(
                "UPDATE package_purchases SET created_at=?, updated_at=? WHERE id=?",
                (old, recent, package_used),
            )
            conn.execute(
                "UPDATE gift_cards SET recipient_email='gift-expiring@example.com', created_at=?, expires_at=? "
                "WHERE code=? AND cliente_id='demo'",
                (old, soon, gift_code),
            )
            conn.commit()

        result = api_module._run_commerce_lifecycle_notices()
        assert result == {"package_expiry": 1, "gift_expiry": 1, "package_rebuy": 1}
        assert {to for to, _subject, _text in sent} == {
            "expiring@example.com", "gift-expiring@example.com", "rebuy@example.com",
        }
        with api_module._get_db_connection() as conn:
            assert conn.execute(
                "SELECT expiry_notice_sent_at FROM package_purchases WHERE id=?", (package_expiring,)
            ).fetchone()[0]
            assert conn.execute(
                "SELECT rebuy_notice_sent_at FROM package_purchases WHERE id=?", (package_used,)
            ).fetchone()[0]
            assert conn.execute(
                "SELECT expiry_notice_sent_at FROM gift_cards WHERE code=? AND cliente_id='demo'", (gift_code,)
            ).fetchone()[0]

        # Idempotente: no reenvia si ya esta sellado.
        sent.clear()
        assert api_module._run_commerce_lifecycle_notices() == {
            "package_expiry": 0, "gift_expiry": 0, "package_rebuy": 0,
        }
        assert sent == []
    finally:
        _cleanup_journey(api_module)
