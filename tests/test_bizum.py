"""Bizum como metodo de pago de la senal (Stripe, ago 2026).

Una peluqueria cobra la senal por Bizum: es lo que su clienta espera (movil +
app del banco). Stripe lo soporta, pero hay que SOLICITAR la capability
`bizum_payments` cuenta por cuenta; sin eso no aparece en el checkout y el
negocio no entiende por que.

Dos trampas que estos tests fijan:
 1. La capability se pide por la API v1: la v2 Core con la que damos de alta la
    cuenta no lista `bizum_payments` (comprobado contra Stripe: 45 capabilities,
    ninguna Bizum).
 2. El checkout no debe fijar `payment_method_types`. Si alguien los enumera,
    Stripe deja de ofrecer Bizum aunque este activo.
"""
from __future__ import annotations

import inspect

from test_booking_exhaustive import api_module  # noqa: F401


def test_el_alta_pide_bizum(api_module):
    from backend import stripe_gateway

    fuente = inspect.getsource(stripe_gateway._create_stripe_connected_account)
    assert "request_bizum_capability" in fuente


def test_se_pide_por_la_api_v1(api_module):
    """La v2 Core no expone bizum_payments; usar Account.modify (v1) es a proposito."""
    from backend import stripe_gateway

    fuente = inspect.getsource(stripe_gateway.request_bizum_capability)
    assert "stripe.Account.modify" in fuente
    assert "bizum_payments" in fuente


def test_pedir_bizum_nunca_tumba_el_alta(api_module):
    """Si Stripe rechaza la peticion, el negocio debe seguir cobrando con tarjeta."""
    from backend import stripe_gateway

    llamadas = {"n": 0}

    class StripeFalso:
        class Account:
            @staticmethod
            def modify(*_args, **_kwargs):
                llamadas["n"] += 1
                raise RuntimeError("capability no disponible")

    original_stripe = stripe_gateway.stripe
    original_init = stripe_gateway._stripe_init
    original_conf = stripe_gateway._stripe_configured
    stripe_gateway.stripe = StripeFalso
    stripe_gateway._stripe_init = lambda: None
    stripe_gateway._stripe_configured = lambda: True
    try:
        assert stripe_gateway.request_bizum_capability("acct_test") == ""
        assert llamadas["n"] == 1
    finally:
        stripe_gateway.stripe = original_stripe
        stripe_gateway._stripe_init = original_init
        stripe_gateway._stripe_configured = original_conf


def test_sin_stripe_configurado_no_llama_a_nadie(api_module):
    from backend import stripe_gateway

    original = stripe_gateway._stripe_configured
    stripe_gateway._stripe_configured = lambda: False
    try:
        assert stripe_gateway.request_bizum_capability("acct_test") == ""
        assert stripe_gateway.request_bizum_capability("") == ""
    finally:
        stripe_gateway._stripe_configured = original


def test_una_cuenta_antigua_se_repara_sola_al_refrescar(api_module):
    """Las cuentas conectadas antes de Bizum lo piden al consultar su estado."""
    from backend import booking

    fuente = inspect.getsource(booking._connect_account_status)
    assert "request_bizum_capability" in fuente
    assert "bizum_status" in fuente


def test_activar_bizum_no_basta_hay_que_mostrarlo(api_module):
    """Comprobado en vivo: con la capability ya activa, el checkout devolvia
    ['card','bancontact','eps','klarna','link'] y Bizum solo aparecio tras
    encender la preferencia en la configuracion de la cuenta."""
    from backend import booking, stripe_gateway

    fuente = inspect.getsource(booking._connect_account_status)
    assert "enable_bizum_display" in fuente

    encender = inspect.getsource(stripe_gateway.enable_bizum_display)
    assert "display_preference" in encender
    # Solo las configuraciones por defecto: las que el negocio se haya creado a
    # mano son suyas.
    assert "is_default" in encender


def test_mostrar_bizum_es_idempotente_y_no_rompe(api_module):
    from backend import stripe_gateway

    modificadas = []

    class StripeFalso:
        class PaymentMethodConfiguration:
            @staticmethod
            def list(**_kwargs):
                return {"data": [
                    {"id": "pmc_ya_on", "is_default": True,
                     "bizum": {"display_preference": {"value": "on"}}},
                    {"id": "pmc_apagada", "is_default": True,
                     "bizum": {"display_preference": {"value": "off"}}},
                    {"id": "pmc_del_negocio", "is_default": False,
                     "bizum": {"display_preference": {"value": "off"}}},
                ]}

            @staticmethod
            def modify(pmc_id, **_kwargs):
                modificadas.append(pmc_id)
                return {}

    original_stripe = stripe_gateway.stripe
    original_init = stripe_gateway._stripe_init
    original_conf = stripe_gateway._stripe_configured
    stripe_gateway.stripe = StripeFalso
    stripe_gateway._stripe_init = lambda: None
    stripe_gateway._stripe_configured = lambda: True
    try:
        assert stripe_gateway.enable_bizum_display("acct_test") is True
        # Ni la que ya estaba encendida ni la que se creo el negocio.
        assert modificadas == ["pmc_apagada"]
    finally:
        stripe_gateway.stripe = original_stripe
        stripe_gateway._stripe_init = original_init
        stripe_gateway._stripe_configured = original_conf


def test_el_checkout_no_enumera_metodos_de_pago(api_module):
    """Enumerar payment_method_types apagaria Bizum sin que nadie se entere."""
    from backend import booking

    fuente = inspect.getsource(booking.create_booking_payment_checkout)
    assert "payment_method_types" not in fuente


def test_el_panel_explica_por_que_bizum_no_esta_activo(api_module):
    import pathlib

    html = (pathlib.Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="payBizumStatus"' in html
    assert "DNI o NIE" in html


def test_el_estado_de_bizum_viaja_al_panel(api_module):
    from api_models import ConnectAccountStatus

    assert ConnectAccountStatus().bizum_status == ""
    assert ConnectAccountStatus(bizum_status="active").bizum_status == "active"
