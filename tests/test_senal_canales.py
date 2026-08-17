"""Un servicio con senal deja la cita "pendiente de pago": el enlace es obligatorio.

Mientras la cita esta en `pending_payment` el email de confirmacion NO sale (se
bloquea a proposito) y el hueco solo queda guardado hasta que Stripe cierra la
sesion de pago. Si el canal por el que reservo el cliente no le ensena el enlace,
el cliente cree que ha reservado, no recibe nada y la cita se cae sola.

El widget web se quedaba justo asi: /agendar devolvia `payment_url` y el widget
lo ignoraba.
"""
from __future__ import annotations

import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def _widget_fuente() -> str:
    return (RAIZ / "widget" / "form.js").read_text(encoding="utf-8")


def test_el_widget_ensena_el_enlace_de_pago():
    fuente = _widget_fuente()
    assert "response.payment_url" in fuente
    assert "pending_payment" in fuente


def test_el_widget_no_dice_reserva_hecha_cuando_falta_pagar():
    """Decir "Solicitud registrada" con el pago pendiente es mentirle al cliente."""
    fuente = _widget_fuente()
    assert "Reserva pendiente de pago" in fuente
    assert "Completa el pago para confirmar la cita." in fuente


def test_el_enlace_no_se_repite_en_el_chat():
    """Se mandaba dos veces por miedo a que la tarjeta desapareciera. No desaparece:
    se inserta DENTRO del hilo de mensajes (`msgs.appendChild(form)`) y nada limpia
    ese contenedor, asi que los mensajes nuevos se anaden debajo y la tarjeta sigue
    ahi con sus botones. Repetirlo solo anadia 300 caracteres de URL de Stripe."""
    fuente = _widget_fuente()
    assert "msgs.appendChild(form)" in fuente          # la tarjeta vive en el hilo
    assert "Paga aqui para confirmar" not in fuente    # y no se repite


def test_el_bundle_publicado_lleva_el_cambio():
    """Sin `npm run build` el arreglo no llega a ninguna web de cliente."""
    bundle = (RAIZ / "widget" / "widget.min.js").read_text(encoding="utf-8")
    assert "Reserva pendiente de pago" in bundle


def test_la_central_publica_tambien_lo_ensena():
    from backend import commerce

    plantilla = commerce._CENTRAL_PAGE_TEMPLATE
    assert "pending_payment" in plantilla
    assert "Completar pago para confirmar" in plantilla


def test_whatsapp_tambien_lo_ensena():
    fuente = (RAIZ / "backend" / "whatsapp.py").read_text(encoding="utf-8")
    assert "Reserva pendiente de pago" in fuente
    assert "checkout_url" in fuente
