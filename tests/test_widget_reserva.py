"""El widget web no repite el aviso ni ensena identificadores internos.

Caso real (ago 2026): al reservar un servicio con senal desde el widget salian
DOS avisos -- la tarjeta de exito (con sus botones de pagar y gestionar) y, justo
debajo, un mensaje en el chat repitiendo el texto con la URL entera de Stripe,
unos 300 caracteres. Ademas la tarjeta mostraba "ID: bk_sAg-BxTKMF6XIw", el
identificador interno de la cita, que al cliente no le sirve para nada.
"""
from __future__ import annotations

import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1]
FUENTE = (RAIZ / "widget" / "form.js").read_text(encoding="utf-8")
BUNDLE = (RAIZ / "widget" / "widget.min.js").read_text(encoding="utf-8")


def test_no_se_repite_el_enlace_de_pago_en_el_chat():
    """La tarjeta ya lleva el boton: repetir la URL de Stripe solo estorba."""
    assert "Paga aqui para confirmar" not in FUENTE
    assert 'if (!pendingPayment) agregarMensaje(successText, "bot");' in FUENTE


def test_el_bundle_esta_reconstruido():
    """Sin `npm run build` el cambio no llega a ninguna web."""
    assert "Paga aqui para confirmar" not in BUNDLE
    assert "Numero de reserva" in BUNDLE


def test_no_se_ensena_el_id_interno_de_la_cita():
    assert "<strong>ID:</strong>" not in FUENTE
    assert "escapeHtml(response.booking_id)" not in FUENTE


def test_el_numero_de_reserva_espera_al_pago():
    """Con la senal sin pagar la cita aun puede caerse: darle el codigo confunde.
    Mismo criterio que en WhatsApp."""
    assert "response.booking_code && !pendingPayment" in FUENTE


def test_la_tarjeta_conserva_sus_botones():
    """Quitar el mensaje duplicado no puede dejar al cliente sin forma de pagar."""
    assert "Completar pago para confirmar" in FUENTE
    assert "Gestionar cita" in FUENTE
