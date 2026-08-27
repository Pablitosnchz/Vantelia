# -*- coding: utf-8 -*-
"""Cobrar la señal sin contarle el precio a quien no debe saberlo.

El mensaje de pago decia:

    Falta el pago para confirmar la cita: *1 €*.
    Señal de 1 € para reservar. Los 2 € restantes se abonan en el centro.

En un salon que NO da precios por mensaje -su norma, y el asistente la respeta en
todo lo demas- esa segunda frase le cuenta el precio por la puerta de atras: 1 + 2
son 3. Justo a quien se le acaba de explicar que el presupuesto se da en persona.

Se apaga POR NEGOCIO, no para todos: donde los precios estan publicados, saber lo
que queda por pagar es util y no filtra nada.

Los tres sitios donde se decia -el mensaje de WhatsApp, el email y la propia
pagina de Stripe- salen de las mismas dos funciones, asi que se arregla una vez.
La de Stripe es la que mas se mira: si ahi pone el resto, da igual lo que se calle
el chat.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module, client  # noqa: F401


def test_sin_precios_publicados_no_se_dice_lo_que_queda(api_module):  # noqa: F811
    from backend import paystate

    linea = paystate.checkout_line("Alisado", 5000, 26000, "deposit", ocultar_precio=True)
    assert "50" in linea["description"]
    assert "210" not in linea["description"], "le esta contando el precio"
    assert "resto se abona" in linea["description"]

    cliente = paystate.customer_line(
        {"kind": paystate.SENAL, "paid_cents": 5000, "pending_cents": 21000},
        ocultar_precio=True)
    assert "50" in cliente and "210" not in cliente


def test_con_precios_publicados_si_se_dice(api_module):  # noqa: F811
    """La otra mitad: quitarlo a todos seria empeorar a los demas negocios."""
    from backend import paystate

    linea = paystate.checkout_line("Alisado", 5000, 26000, "deposit")
    assert "210" in linea["description"]
    cliente = paystate.customer_line(
        {"kind": paystate.SENAL, "paid_cents": 5000, "pending_cents": 21000})
    assert "210" in cliente


def test_se_sigue_diciendo_que_es_una_senal_y_no_el_precio(api_module):  # noqa: F811
    """Lo que NO puede pasar es que crea que la señal es el precio total.

    Por eso la linea existe: sin ella, quien paga 50 € de un alisado de 260 ve
    "Alisado — 50,00 €" en Stripe y cree que ese es el precio.
    """
    from backend import paystate

    linea = paystate.checkout_line("Alisado", 5000, 26000, "deposit", ocultar_precio=True)
    assert "señal" in linea["name"].lower()
    assert linea["description"], "Stripe rechaza una descripcion vacia"


def test_la_retencion_no_cambia(api_module):  # noqa: F811
    """Una preautorizacion no es un cobro y ahi no hay resto que contar."""
    from backend import paystate

    linea = paystate.checkout_line("Alisado", 5000, 26000, "preauth", ocultar_precio=True)
    assert "garantía" in linea["description"]
    assert "No es un cobro" in linea["description"]


def test_los_tres_caminos_consultan_la_norma_del_negocio(api_module):  # noqa: F811
    """Si uno se queda sin preguntar, vuelve a filtrarse por ahi."""
    import inspect

    from backend import booking

    for funcion in (booking.payment_prompt_note, booking._checkout_product_data):
        fuente = inspect.getsource(funcion)
        assert "ocultar_precio" in fuente, funcion.__name__
    # Y el email de confirmacion.
    assert "ocultar_precio=precios_ocultos(" in inspect.getsource(booking)
