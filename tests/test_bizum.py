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
    assert "sync_payment_methods" in fuente

    sync = inspect.getsource(stripe_gateway.sync_payment_methods)
    assert "display_preference" in sync
    # Solo las configuraciones por defecto: las que el negocio se haya creado a
    # mano son suyas.
    assert "is_default" in sync


def _stripe_falso(metodos):
    """Doble de Stripe que recuerda que preferencias se han escrito."""
    escrito = {}

    class StripeFalso:
        class PaymentMethodConfiguration:
            @staticmethod
            def list(**_kwargs):
                filas = {k: {"display_preference": {"value": v}} for k, v in metodos.items()}
                filas.update({"id": "pmc_1", "is_default": True})
                return {"data": [filas]}

            @staticmethod
            def modify(_pmc_id, **kwargs):
                for clave, valor in kwargs.items():
                    if isinstance(valor, dict) and "display_preference" in valor:
                        escrito[clave] = valor["display_preference"]["preference"]
                return {}

    return StripeFalso, escrito


def _con_stripe_falso(metodos, **kwargs):
    from backend import stripe_gateway

    falso, escrito = _stripe_falso(metodos)
    originales = (stripe_gateway.stripe, stripe_gateway._stripe_init, stripe_gateway._stripe_configured)
    stripe_gateway.stripe = falso
    stripe_gateway._stripe_init = lambda: None
    stripe_gateway._stripe_configured = lambda: True
    try:
        stripe_gateway.sync_payment_methods("acct_test", **kwargs)
    finally:
        (stripe_gateway.stripe, stripe_gateway._stripe_init, stripe_gateway._stripe_configured) = originales
    return escrito


def test_solo_quedan_tarjeta_bizum_y_carteras(api_module):
    """Stripe enciende por defecto Klarna, Pix, EPS y tres coreanos. Fuera."""
    escrito = _con_stripe_falso(
        {"card": "on", "bizum": "off", "apple_pay": "on", "google_pay": "off",
         "klarna": "on", "pix": "on", "kakao_pay": "on", "link": "on", "eps": "on"},
        bizum=True, wallets=True,
    )
    assert escrito["bizum"] == "on"
    assert escrito["google_pay"] == "on"
    for sobra in ("klarna", "pix", "kakao_pay", "link", "eps"):
        assert escrito[sobra] == "off", sobra
    # Lo que ya estaba bien no se reescribe.
    assert "card" not in escrito and "apple_pay" not in escrito


def test_si_el_negocio_apaga_bizum_se_queda_apagado(api_module):
    """El bug de la primera version: lo reencendiamos en cada refresco."""
    escrito = _con_stripe_falso({"card": "on", "bizum": "on", "apple_pay": "on"},
                                bizum=False, wallets=True)
    assert escrito["bizum"] == "off"


def test_apagar_las_carteras_no_toca_la_tarjeta(api_module):
    escrito = _con_stripe_falso({"card": "on", "apple_pay": "on", "google_pay": "on", "bizum": "on"},
                                bizum=True, wallets=False)
    assert escrito["apple_pay"] == "off" and escrito["google_pay"] == "off"
    assert "card" not in escrito


def test_la_tarjeta_nunca_se_puede_apagar(api_module):
    escrito = _con_stripe_falso({"card": "off", "bizum": "off"}, bizum=False, wallets=False)
    assert escrito["card"] == "on"


def test_si_stripe_falla_no_rompe_la_pantalla(api_module):
    from backend import stripe_gateway

    class StripeRoto:
        class PaymentMethodConfiguration:
            @staticmethod
            def list(**_kwargs):
                raise RuntimeError("Stripe caido")

    originales = (stripe_gateway.stripe, stripe_gateway._stripe_init, stripe_gateway._stripe_configured)
    stripe_gateway.stripe = StripeRoto
    stripe_gateway._stripe_init = lambda: None
    stripe_gateway._stripe_configured = lambda: True
    try:
        assert stripe_gateway.sync_payment_methods("acct_test", bizum=True, wallets=True) == {"bizum": True}
    finally:
        (stripe_gateway.stripe, stripe_gateway._stripe_init, stripe_gateway._stripe_configured) = originales


def test_la_ia_puede_enviar_el_enlace_sin_opt_in(api_module):
    """El interruptor nacia apagado y nadie lo encontraba: se retiro. Basta con
    tener Stripe operativo."""
    from backend import booking

    fuente = inspect.getsource(booking._ai_payment_sending_available)
    assert "charges_enabled" in fuente
    assert not hasattr(booking, "_ai_send_enabled_for_client")
    assert not hasattr(booking, "_set_ai_send_enabled")


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


def test_el_estado_de_bizum_se_guarda(api_module):
    """Se consultaba solo al refrescar, asi que al abrir la pantalla llegaba vacio
    y el interruptor salia bloqueado sin motivo."""
    import inspect

    from backend import booking, db

    fuente = inspect.getsource(booking._connect_account_status)
    assert "bizum_status=?" in fuente  # se persiste al refrescar
    assert 'row["bizum_status"]' in fuente  # y se lee al cargar

    with db._get_db_connection() as connection:
        columnas = {r[1] for r in connection.execute("PRAGMA table_info(client_payment_accounts)")}
    assert "bizum_status" in columnas
    assert {"bizum_enabled", "wallets_enabled"} <= columnas


def test_no_se_bloquea_el_interruptor_a_ciegas(api_module):
    """Si Stripe no responde, el estado llega vacio: bloquear entonces deja al
    negocio sin poder tocar nada."""
    import pathlib as _p

    html = (_p.Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")
    assert "bizumToggle.disabled = !!status.bizum_status && status.bizum_status !== 'active';" in html
    # Y la pestana se abre refrescando, para que el estado no dependa de un boton.
    assert "if (tab === 'payments')   loadPayments(true);" in html


def test_desconectar_no_borra_la_cuenta_en_stripe(api_module):
    """La cuenta es del negocio (su dinero, su historial). Solo la olvidamos."""
    import inspect

    from backend import booking

    fuente = inspect.getsource(booking.disconnect_stripe_account)
    assert "stripe_account_id=''" in fuente
    assert "Account.delete" not in fuente
    # Si hay OAuth configurado, ademas se revoca el acceso.
    assert "OAuth.deauthorize" in fuente


def test_desconectar_deja_el_negocio_sin_cobros(api_module):
    from backend import booking, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO client_payment_accounts (cliente_id, stripe_account_id, charges_enabled,
                payouts_enabled, details_submitted, bizum_status, created_at, updated_at)
            VALUES ('demo', 'acct_desconectar', 1, 1, 1, 'active', ?, ?)
            ON CONFLICT(cliente_id) DO UPDATE SET stripe_account_id='acct_desconectar',
                charges_enabled=1, bizum_status='active', updated_at=excluded.updated_at
            """,
            (ahora, ahora),
        )
        connection.commit()
    assert booking._connect_account_status("demo").connected is True

    estado = booking.disconnect_stripe_account("demo")
    assert estado.connected is False
    assert estado.stripe_account_id == ""
    assert estado.charges_enabled is False
    assert estado.bizum_status == ""
    # Sin cuenta, la IA no puede mandar enlaces de pago.
    assert booking._ai_payment_sending_available("demo") is False


def test_desconectar_sin_cuenta_no_falla(api_module):
    from backend import booking, db

    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM client_payment_accounts WHERE cliente_id='demo'")
        connection.commit()
    assert booking.disconnect_stripe_account("demo").connected is False


def test_el_panel_avisa_de_lo_que_implica_desconectar(api_module):
    import pathlib as _p

    html = (_p.Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="payDisconnectBtn"' in html
    assert "sin cobro" in html
