"""El mensaje final de WhatsApp no puede ser un muro con una URL de 300 caracteres.

Antes, al reservar un servicio con senal, llegaba un solo mensaje con el resumen,
el texto del salon, la URL entera del checkout de Stripe (~300 caracteres
ilegibles), la nota de la senal, el aviso del hueco y la coletilla del menu.

Ahora son dos: el resumen de la cita, y el pago aparte con un boton.
"""
from __future__ import annotations

import inspect
import pathlib

from test_booking_exhaustive import api_module  # noqa: F401


def test_el_pago_va_en_su_propio_mensaje(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_create_booking)
    assert "_wa_send_payment_request" in fuente
    # El resumen ya no interpola la URL del checkout dentro del texto.
    assert "{payment_row['checkout_url']}" not in fuente
    # Ni la coletilla del menu cuando lo que toca es pagar.
    resumen = fuente.split("hay_que_pagar =")[1].split("_wa_send_payment_request")[0]
    assert "menu principal" in resumen  # sigue estando en el caso SIN pago...
    assert resumen.count("menu principal") == 1  # ...y solo ahi


def test_el_enlace_se_esconde_tras_un_boton(api_module):
    from backend import messaging, whatsapp

    fuente = inspect.getsource(whatsapp._wa_send_payment_request)
    assert "_send_whatsapp_cta_url" in fuente
    assert "button_label" in fuente

    cta = inspect.getsource(messaging._send_whatsapp_cta_url)
    assert '"type": "cta_url"' in cta
    assert '"display_text"' in cta


def test_si_meta_rechaza_el_boton_se_manda_texto(api_module):
    """Un tipo de mensaje nuevo no puede dejar al cliente sin forma de pagar."""
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_send_payment_request)
    assert "_send_whatsapp_text" in fuente


def test_el_enlace_es_corto_y_propio(api_module):
    from backend import booking, whatsapp

    fuente = inspect.getsource(whatsapp._wa_send_payment_request)
    assert "build_booking_payment_url" in fuente

    url = booking.build_booking_payment_url("mg_" + "x" * 32)
    assert "/p/mg_" in url
    # Un checkout de Stripe ronda los 300; este tiene que ser mucho mas corto.
    assert len(url) < 100
    assert booking.build_booking_payment_url("") == ""


def test_el_enlace_corto_lleva_al_checkout(api_module, client=None):
    """La ruta publica /p/{token} redirige al pago de esa cita."""
    from backend.routers import public_booking

    fuente = inspect.getsource(public_booking.booking_payment_shortlink)
    assert "_booking_payment_row" in fuente
    assert "status_code=302" in fuente
    # Ya pagada o sin cobro pendiente: a la pagina de la cita, no a un error.
    assert "_build_booking_manage_url" in fuente
    assert '("paid", "preauthorized")' in fuente


def test_sin_email_no_se_imprime_el_emoji_suelto(api_module):
    """Llegaba una linea con "📧" y nada detras."""
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_create_booking)
    assert 'if flow.email else ""' in fuente


def test_ya_no_se_pide_el_email_por_whatsapp(api_module):
    """Costaba una interaccion a todo el mundo para que casi nadie lo diera, y la
    confirmacion ya sale por el propio chat."""
    fuente = (pathlib.Path(__file__).resolve().parents[1] / "backend" / "whatsapp.py").read_text(encoding="utf-8")
    assert "booking_email" not in fuente
    assert "email_skip" not in fuente
    assert "Sin email" not in fuente


def test_al_dar_el_nombre_se_va_directo_al_resumen(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_message)
    tras_nombre = fuente.split('if flow.flow == "booking_name":')[1].split("if flow.flow ==")[0]
    assert "_wa_send_booking_summary" in tras_nombre


def test_a_un_cliente_conocido_se_le_conserva_su_email(api_module):
    """Si ya esta en su ficha, se sigue usando: no se pide, pero no se pierde."""
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_message)
    assert "contact_by_phone" in fuente
    assert 'flow.email = str(conocido["email"] or "")' in fuente
