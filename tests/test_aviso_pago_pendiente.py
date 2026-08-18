"""Al reservar un servicio con senal, el cliente recibe el enlace de pago.

Antes no recibia nada: la confirmacion se saltaba (correcto, la cita no estaba
confirmada) pero no habia nada en su lugar. En WhatsApp el enlace se queda en el
chat; en la web, si cerraba la pestana, lo perdia y no tenia forma de recuperarlo.

Va con su propio aviso ("pending_payment"), asi que el negocio puede editar el
texto y elegir canales igual que con los demas -- email y SMS incluidos.
"""
from __future__ import annotations

import inspect
import pathlib

from test_booking_exhaustive import api_module  # noqa: F401

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def test_el_aviso_existe_como_uno_mas(api_module):
    """Estar en los defaults es lo que le da plantilla, on/off y canales."""
    from backend import settings

    assert "pending_payment" in settings.DEFAULT_MESSAGE_TEMPLATES
    assert settings.DEFAULT_MESSAGE_TEMPLATE_ENABLED["pending_payment"] is True
    assert settings.DEFAULT_MESSAGE_TEMPLATE_CHANNELS["pending_payment"]["email"] is True


def test_los_canales_globales_lo_alcanzan(api_module):
    """El Seguimiento escribe los canales en abanico sobre todos los avisos: si el
    negocio activa SMS, este tambien sale por SMS."""
    from backend import textnorm

    canales = textnorm._normalize_message_template_channels({})
    assert "pending_payment" in canales


def test_al_reservar_se_manda_el_aviso_que_toca(api_module):
    from backend import booking

    fuente = inspect.getsource(booking._create_booking_core)
    assert 'aviso = "pending_payment" if stored["status"] == "pending_payment" else "confirmed"' in fuente


def test_el_aviso_lleva_el_enlace_de_pago(api_module):
    """Sin enlace el aviso no sirve para nada."""
    from backend import booking

    fuente = inspect.getsource(booking._booking_email_bodies)
    assert "build_booking_payment_url" in fuente
    assert "Pagar y confirmar la cita" in fuente  # boton del email


def test_no_se_da_el_numero_de_reserva_antes_de_pagar(api_module):
    """Mismo criterio que en WhatsApp y en el widget: la cita aun puede caerse."""
    from backend import booking

    fuente = inspect.getsource(booking._booking_email_bodies)
    assert 'if status_key == "pending_payment":' in fuente
    assert 'booking_code = ""' in fuente


def test_el_asunto_no_dice_que_esta_confirmada(api_module):
    from backend import booking

    fuente = inspect.getsource(booking._booking_email_subject)
    assert "Falta el pago para confirmar tu cita" in fuente


def test_hay_tiempo_real_para_pagar(api_module):
    """Con 30 minutos el email llegaba cuando la cita ya se habia cancelado."""
    from backend import settings

    assert settings.BOOKING_PAYMENT_EXPIRY_MINUTES >= 120


def test_un_enlace_caducado_no_lleva_a_un_error_de_stripe(api_module):
    from backend.routers import public_booking

    fuente = inspect.getsource(public_booking.booking_payment_shortlink)
    assert '"expired"' in fuente


def test_el_negocio_puede_editar_el_texto(api_module):
    html = (RAIZ / "app_ui" / "index.html").read_text(encoding="utf-8")
    assert "{ key:'pending_payment', label:'Falta el pago para confirmar' }" in html


def test_el_aviso_no_llama_senal_a_un_cobro_entero(api_module):
    """Salta con los TRES modos que exigen pagar para confirmar (senal, pago
    completo y retencion), asi que el texto base no puede decir "senal"."""
    from backend import settings

    base = settings.DEFAULT_MESSAGE_TEMPLATES["pending_payment"].lower()
    assert "senal" not in base and "señal" not in base
    assert "no esta confirmada" in base.replace("está", "esta")


def test_el_detalle_lo_pone_el_helper_compartido(api_module):
    """`payment_prompt_note` ya distingue senal / retencion / total: se reusa en vez
    de escribir otra version del mismo texto."""
    from backend import booking

    fuente = inspect.getsource(booking._booking_email_bodies)
    assert "payment_prompt_note(" in fuente

    # Senal: dice cuanto queda por pagar en el centro.
    linea = booking.paystate.checkout_line("Corte", 5000, 12000, "deposit")
    assert "50" in linea["description"] and "70" in linea["description"]
    # Retencion: deja claro que NO es un cobro.
    retencion = booking.paystate.checkout_line("Corte", 5000, 12000, "preauth")
    assert "no es un cobro" in retencion["description"].lower()
