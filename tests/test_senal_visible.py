"""Una senal de 50 EUR sobre un servicio de 120 tiene que verse como senal.

Caso real (ago 2026): una peluqueria cobra 50 EUR por adelantado en algunos
servicios y el resto en el salon. La cita aparecia como "Pagado" en el panel y
el cliente recibia un email identico al de quien habia pagado los 120 EUR.
Nadie sabia cuanto faltaba por cobrar.

Aqui se fija que el importe pendiente sale por los cuatro sitios que lo miran:
panel, Stripe Checkout, email de confirmacion y WhatsApp.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def test_el_panel_dice_cuanto_falta(api_module):
    from backend import paystate

    resumen = paystate.summary(12000, 5000)
    assert resumen["kind"] == paystate.SENAL
    assert resumen["pending_cents"] == 7000
    assert "50" in resumen["label"] and "70" in resumen["label"]


def test_pagar_del_todo_no_deja_pendiente(api_module):
    from backend import paystate

    resumen = paystate.summary(12000, 12000)
    assert resumen["kind"] == paystate.PAGADO
    assert resumen["pending_cents"] == 0


def test_un_servicio_sin_cobro_online_no_inventa_estado(api_module):
    from backend import paystate

    resumen = paystate.summary(12000, 0)
    assert resumen["kind"] == paystate.SIN_COBRO
    assert resumen["label"] == ""


def test_la_retencion_no_se_anuncia_como_cobro(api_module):
    """Retener no es cobrar: si se dice mal, el cliente reclama el cargo."""
    from backend import paystate

    resumen = paystate.summary(12000, 5000, payment_status="preauthorized")
    assert resumen["kind"] == paystate.RETENIDO
    assert "no es un cobro" in paystate.customer_line(resumen).lower()


def test_la_linea_de_stripe_explica_la_senal(api_module):
    from backend import paystate

    linea = paystate.checkout_line("Corte y color", 5000, 12000, "deposit")
    assert "señal" in linea["name"].lower()
    assert "50" in linea["description"] and "70" in linea["description"]

    # Pago completo: nada que explicar, la descripcion sobra.
    entero = paystate.checkout_line("Corte y color", 12000, 12000, "full")
    assert entero["description"] == ""


def test_lo_que_se_le_dice_al_cliente_es_una_sola_frase(api_module):
    from backend import paystate

    frase = paystate.customer_line(paystate.summary(12000, 5000))
    assert "50" in frase and "70" in frase
    assert frase.count(".") <= 2


def test_el_email_de_confirmacion_lleva_el_pendiente(api_module):
    """Fuente unica: si alguien quita la linea del email, salta aqui."""
    import inspect

    from backend import booking

    fuente = inspect.getsource(booking._booking_email_bodies)
    assert "paystate.customer_line" in fuente
    assert "_cobro_line" in fuente and "_cobro_texto" in fuente


def test_whatsapp_explica_que_paga_el_cliente(api_module):
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp)
    assert "booking.payment_prompt_note" in fuente


def test_stripe_recibe_el_producto_explicado(api_module):
    import inspect

    from backend import booking

    fuente = inspect.getsource(booking.create_booking_payment_checkout)
    assert "_checkout_product_data(booking, decision)" in fuente


def test_una_senal_se_puede_reembolsar_desde_el_panel(api_module):
    """Una cita con senal NO esta "pagada", pero tiene dinero cobrado que se puede
    devolver. Confundir las dos cosas escondia el boton justo en las senales."""
    import pathlib as _p

    html = (_p.Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")
    assert "function payHasMoney(b)" in html
    assert "b.pay_kind === 'senal'" in html
    # Y es esa condicion la que gobierna el boton, en las dos vistas.
    assert html.count("payHasMoney(b) && hasPerm('payments.refund')") == 2


def test_el_backend_admite_reembolsar_una_senal(api_module):
    """El cobro de la senal queda como `paid` en booking_payments: reembolsable."""
    import inspect

    from backend import booking

    fuente = inspect.getsource(booking.refund_booking_payment)
    assert '("paid", "partially_refunded")' in fuente
