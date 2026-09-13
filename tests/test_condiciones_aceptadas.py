"""Los términos aceptados sobreviven a catálogo cambiante y respuestas perdidas."""
import json
import uuid
from types import SimpleNamespace

import pytest

from test_formulario_confirmacion_compartida import api_module, agenda_de_dos, formulario  # noqa: F401


@pytest.fixture
def condiciones(formulario, monkeypatch):
    from backend import db, stripe_gateway, timeutils
    f = formulario
    slug = "cond_" + uuid.uuid4().hex
    with db._get_db_connection() as cx:
        cx.execute("""INSERT INTO services(cliente_id,slug,name,duration_minutes,price_cents,
            payment_mode,payment_type,deposit_amount_cents,created_at)
            VALUES('demo',?,?,30,10000,'payment_required','deposit',2000,?)""",
                   (slug, slug, timeutils._utc_now_iso()))
        cx.commit()
    checkouts = []
    monkeypatch.setattr(stripe_gateway, "_stripe_connected_account_row",
                        lambda *a: {"status": "active", "stripe_account_id": "acct_sintetica"})
    monkeypatch.setattr(stripe_gateway, "_stripe_configured", lambda: True)
    monkeypatch.setattr(stripe_gateway, "_stripe_init", lambda: None)
    def checkout(**kw):
        checkouts.append(kw)
        return SimpleNamespace(id="cs_sintetica", url="https://stripe.test.invalid/pago")
    monkeypatch.setattr(stripe_gateway.stripe.checkout.Session, "create", checkout)
    def cambiar(**valores):
        with db._get_db_connection() as cx:
            for campo, valor in valores.items():
                assert campo in {"duration_minutes", "price_cents", "deposit_amount_cents", "is_active", "description"}
                cx.execute("UPDATE services SET " + campo + "=? WHERE cliente_id='demo' AND slug=?", (valor, slug))
            cx.commit()
    f.update(slug=slug, cambiar=cambiar, checkouts=checkouts)
    f["recibir"](servicio=slug)
    yield f
    with db._get_db_connection() as cx:
        cx.execute("DELETE FROM booking_payments WHERE booking_id IN (SELECT id FROM bookings WHERE telefono=?)", (f["numero"],))
        cx.execute("DELETE FROM services WHERE slug=?", (slug,))
        cx.commit()


@pytest.mark.parametrize("campo,valor", [("duration_minutes", 60), ("price_cents", 12000), ("deposit_amount_cents", 5000)])
def test_cambio_tras_oferta_exige_otra_aceptacion(condiciones, campo, valor):
    from backend import reserva
    f = condiciones
    viejo = f["botones"][-1]["buttons"][0][0]
    f["cambiar"](**{campo: valor})
    f["confirmar"](viejo)
    assert not f["citas"]() and not f["proveedores"] and not f["checkouts"]
    nuevo = f["botones"][-1]["buttons"][0][0]
    assert nuevo != viejo
    assert reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]))["estado"] == "ofrecida"
    f["confirmar"](viejo)
    assert not f["citas"]()
    f["confirmar"](nuevo)
    assert len(f["citas"]()) == len(f["proveedores"]) == len(f["checkouts"]) == 1


def test_durante_proveedor_no_recalcula_precio_ni_fianza(condiciones, monkeypatch):
    from backend import booking
    f = condiciones
    original = booking._create_provider_booking
    async def cambiar(*a, **kw):
        resultado = await original(*a, **kw)
        f["cambiar"](price_cents=16000, deposit_amount_cents=5000, duration_minutes=60)
        return resultado
    monkeypatch.setattr(booking, "_create_provider_booking", cambiar)
    f["confirmar"]()
    assert len(f["citas"]()) == 1
    assert f["citas"]()[0]["service_price_cents"] == 10000
    assert f["checkouts"][0]["line_items"][0]["price_data"]["unit_amount"] == 2000


def test_fallo_checkout_no_borra_obligacion_aceptada(condiciones, monkeypatch):
    from backend import stripe_gateway
    f = condiciones
    def fallo(**kw): raise RuntimeError("Stripe no disponible")
    monkeypatch.setattr(stripe_gateway.stripe.checkout.Session, "create", fallo)
    f["confirmar"]()
    fila = f["citas"]()[0]
    assert fila["status"] == "pending_payment"
    assert fila["payment_status"] == "pending"


def test_recovery_antes_de_revalidar_catalogo_retirado(condiciones, monkeypatch):
    from backend import appstate, booking, reserva
    f = condiciones
    def fallo(*a, **kw): raise RuntimeError("caida tras commit")
    monkeypatch.setattr(booking, "_record_booking_audit", fallo)
    f["confirmar"]()
    p = reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]))
    assert p and p.get("operacion")
    f["cambiar"](is_active=0, price_cents=19000)
    monkeypatch.setattr(appstate, "whatsapp_flows", {})
    f["recibir"](servicio=f["slug"])
    assert len(f["citas"]()) == len(f["proveedores"]) == len(f["checkouts"]) == 1
    actual = reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]), incluir_hecha=True)
    assert actual["operacion"] == p["operacion"]


def test_cambio_irrelevante_no_invalida_ni_duplica(condiciones):
    f = condiciones
    f["cambiar"](description="Descripción informativa nueva")
    f["confirmar"]()
    f["confirmar"]()
    assert len(f["citas"]()) == len(f["proveedores"]) == len(f["checkouts"]) == 1


def test_oferta_antigua_sin_terminos_se_reofrece(condiciones):
    from backend import reserva
    f = condiciones
    estado = reserva.cargar("demo", f["numero"])
    p = json.loads(estado.confirmacion_reserva_json)
    p.pop("terms", None)
    estado.confirmacion_reserva_json = json.dumps(p)
    reserva.guardar("demo", f["numero"], estado)
    f["confirmar"]()
    assert not f["citas"]() and not f["proveedores"]


def test_cambio_entre_aceptacion_y_reclamacion_no_ejecuta(condiciones, monkeypatch):
    from backend import reserva, whatsapp
    f = condiciones
    original = whatsapp._wa_create_booking
    async def cambiar(**kw):
        f["cambiar"](deposit_amount_cents=5000)
        return await original(**kw)
    monkeypatch.setattr(whatsapp, "_wa_create_booking", cambiar)
    f["confirmar"]()
    assert not f["citas"]() and not f["proveedores"] and not f["checkouts"]
    p = reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]))
    assert p["estado"] == "ofrecida" and not p.get("operacion")


@pytest.mark.parametrize("corrupto", [False, True, "importe", "modo"])
def test_checkout_no_reutiliza_terminos_corruptos_o_cita_modificada(condiciones, corrupto):
    from backend import booking, db
    from fastapi import HTTPException
    f = condiciones
    f["confirmar"]()
    fila = f["citas"]()[0]
    with db._get_db_connection() as cx:
        if corrupto in ("importe", "modo"):
            sellado = json.loads(fila["creation_terms_json"])
            if corrupto == "importe":
                sellado["terms"]["payment_decision"]["amount_cents"] = 1
            else:
                sellado["terms"]["payment"]["payment_mode"] = "payment_optional"
            cx.execute("UPDATE bookings SET creation_terms_json=? WHERE id=?", (json.dumps(sellado), fila["id"]))
        elif corrupto:
            cx.execute("UPDATE bookings SET creation_terms_json='{}' WHERE id=?", (fila["id"],))
        else:
            cx.execute("UPDATE bookings SET booking_time='11:00' WHERE id=?", (fila["id"],))
        cx.commit()
    with pytest.raises(HTTPException) as error:
        booking.create_booking_payment_checkout("demo", fila["id"])
    assert error.value.status_code == 409
    assert len(f["checkouts"]) == 1
    # Un pago ya hecho nunca se vuelve a cobrar por esa discrepancia.
    with db._get_db_connection() as cx:
        cx.execute("UPDATE booking_payments SET status='paid' WHERE booking_id=?", (fila["id"],))
        cx.commit()
    assert booking.create_booking_payment_checkout("demo", fila["id"]) == "https://stripe.test.invalid/pago"
    assert len(f["checkouts"]) == 1


def test_aceptada_antigua_sin_vinculo_no_acredita_ausencia_de_efecto(condiciones):
    from backend import reserva
    f = condiciones
    estado = reserva.cargar("demo", f["numero"])
    p = json.loads(estado.confirmacion_reserva_json)
    p.pop("terms")
    p["estado"] = "aceptada"
    estado.confirmacion_reserva_json = json.dumps(p)
    reserva.guardar("demo", f["numero"], estado)
    f["confirmar"]()
    assert not f["citas"]() and not f["proveedores"]
    actual = reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]))
    assert actual["id"] == p["id"] and actual["estado"] == "aceptada"


def test_recargo_informativo_no_aumenta_cobro_y_precio_oculto_se_conserva(condiciones, monkeypatch):
    from backend import appstate, db, textnorm
    f = condiciones
    monkeypatch.setitem(appstate.CONFIG_CLIENTES["demo"]["booking"], "mostrar_precios", False)
    with db._get_db_connection() as cx:
        cx.execute("UPDATE employees SET price_surcharge_pct=25 WHERE id=?", (f["empleado"],))
        cx.commit()
    f["confirmar"]()  # Cambio de recargo exige otra oferta.
    assert not f["citas"]()
    assert "25%" in f["botones"][-1]["body"]
    f["confirmar"]()
    assert f["citas"]()[0]["service_price_cents"] == 10000
    assert f["checkouts"][0]["line_items"][0]["price_data"]["unit_amount"] == 2000
    textos = " ".join(f["textos"]) + " ".join(b["body"] for b in f["botones"])
    assert textnorm._format_price_cents(10000) not in textos
    assert textnorm._format_price_cents(10000) not in json.dumps(f["checkouts"][0]["line_items"][0]["price_data"]["product_data"])


@pytest.mark.parametrize("sin_centro", [False, True])
def test_fianza_y_cobro_comparten_precio_efectivo_del_centro(condiciones, sin_centro):
    from backend import agenda, db, reserva, textnorm
    f = condiciones
    centro = agenda._default_location_id("demo")
    f["cambiar"](price_cents=1000, deposit_amount_cents=5000)
    with db._get_db_connection() as cx:
        cx.execute("UPDATE employees SET location_id=? WHERE id=?", ("" if sin_centro else centro, f["empleado"]))
        cx.execute("INSERT INTO service_location_overrides(cliente_id,service_slug,location_id,price_cents) VALUES('demo',?,?,1800)", (f["slug"], centro))
        cx.commit()
    try:
        f["confirmar"]()  # Cambiaron las condiciones: solo vuelve a ofrecer.
        assert not f["citas"]()
        p = reserva.leer_confirmacion_reserva(reserva.cargar("demo", f["numero"]))
        assert p["terms"]["service_price_cents"] == 1800
        assert p["terms"]["deposit_display_cents"] == 1800
        assert p["datos"]["location_id"] == centro
        assert textnorm._format_price_cents(1800) in f["botones"][-1]["body"]
        f["confirmar"]()
        assert len(f["citas"]()) == len(f["checkouts"]) == 1
        assert f["citas"]()[0]["service_price_cents"] == 1800
        assert f["checkouts"][0]["line_items"][0]["price_data"]["unit_amount"] == 1800
    finally:
        with db._get_db_connection() as cx:
            cx.execute("DELETE FROM service_location_overrides WHERE service_slug=?", (f["slug"],))
            cx.commit()


def test_perdida_de_stripe_tras_oferta_no_degrada_obligacion(condiciones, monkeypatch):
    from backend import stripe_gateway
    f = condiciones
    monkeypatch.setattr(stripe_gateway, "_stripe_connected_account_row", lambda *a: None)
    f["confirmar"]()
    assert len(f["citas"]()) == 1
    assert f["citas"]()[0]["status"] == "pending_payment"
    assert f["citas"]()[0]["payment_status"] == "pending"
    assert not f["checkouts"]


def test_oferta_offline_no_se_convierte_en_pago_al_aparecer_stripe(condiciones, monkeypatch):
    from backend import stripe_gateway
    f = condiciones
    cuenta = stripe_gateway._stripe_connected_account_row
    monkeypatch.setattr(stripe_gateway, "_stripe_connected_account_row", lambda *a: None)
    f["recibir"](f["abrir"](), servicio=f["slug"])
    monkeypatch.setattr(stripe_gateway, "_stripe_connected_account_row", cuenta)
    f["confirmar"]()
    assert len(f["citas"]()) == 1
    assert f["citas"]()[0]["status"] == "confirmed"
    assert f["citas"]()[0]["payment_status"] == "not_required"
    assert not f["checkouts"]


def test_perdida_de_stripe_durante_proveedor_conserva_pending(condiciones, monkeypatch):
    from backend import booking, stripe_gateway
    f = condiciones
    original = booking._create_provider_booking
    async def caer(*a, **kw):
        resultado = await original(*a, **kw)
        monkeypatch.setattr(stripe_gateway, "_stripe_connected_account_row", lambda *a: None)
        return resultado
    monkeypatch.setattr(booking, "_create_provider_booking", caer)
    f["confirmar"]()
    assert len(f["citas"]()) == 1
    assert f["citas"]()[0]["status"] == "pending_payment"
    assert f["citas"]()[0]["payment_status"] == "pending"
    assert not f["checkouts"]


def test_aceptar_minutos_despues_conserva_oferta_sin_cambio(condiciones, monkeypatch):
    from backend import reserva
    f = condiciones
    reloj = reserva.time.time()
    monkeypatch.setattr(reserva, "time", SimpleNamespace(time=lambda: reloj + 120))
    iid = f["botones"][-1]["buttons"][0][0]
    f["confirmar"](iid)
    assert f["botones"][-1]["buttons"][0][0] == iid
    assert len(f["citas"]()) == len(f["proveedores"]) == len(f["checkouts"]) == 1
