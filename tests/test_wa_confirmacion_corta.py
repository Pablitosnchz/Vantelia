"""Al reservar por WhatsApp no se manda un muro de texto, ni se miente.

Caso real (ago 2026): al reservar un servicio con senal llegaban TRES mensajes.
El primero era el correo entero convertido a texto y empezaba diciendo "Tu cita
ha quedado confirmada"... cuando la cita estaba pendiente de pago. Ademas daba
ya el numero de reserva y el enlace de gestion de una cita que todavia podia
caerse si no pagaba.

Ahora: mientras falte el pago, resumen + boton de pagar. El numero de reserva y
el enlace de gestion llegan cuando la cita es suya de verdad.
"""
from __future__ import annotations

import inspect

from test_booking_exhaustive import api_module  # noqa: F401


def test_no_se_confirma_una_cita_que_no_esta_pagada(api_module):
    """Decir "confirmada" a quien tiene que pagar la senal es mentirle."""
    from backend import booking

    fuente = inspect.getsource(booking._send_booking_reminder_by_kind)
    assert 'kind == "confirmed" and booking_row["status"] == "pending_payment"' in fuente
    assert '"pending_payment"' in fuente


def test_el_numero_de_reserva_espera_al_pago(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_create_booking)
    assert "if codigo and not is_pending_payment:" in fuente


def test_sin_senal_se_da_el_codigo_y_el_boton_de_gestion(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_create_booking)
    assert "if not hay_que_pagar and stored_booking:" in fuente
    assert "Gestionar cita" in fuente
    assert "_booking_row_manage_url" in fuente


def test_la_confirmacion_por_whatsapp_es_corta(api_module):
    """El correo entero (zona horaria, contacto, URL cruda) aqui no pinta nada."""
    from backend import booking

    fuente = inspect.getsource(booking._send_booking_whatsapp_reminder)
    assert "_whatsapp_confirmation_text" in fuente
    assert "Gestionar cita" in fuente
    # Si el boton falla, sigue saliendo el texto largo: nadie se queda sin aviso.
    assert "_booking_message_text_for_channel" in fuente


def test_el_texto_corto_lleva_lo_imprescindible(api_module):
    from backend import booking, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO chat_sessions (id, cliente_id, origin, user_agent,
                started_at, last_message_at, message_count)
            VALUES ('ses_dummy_conf', 'demo', 'whatsapp:1', '', ?, ?, 1)
            """,
            (ahora, ahora),
        )
        connection.commit()

    class _Cita(dict):
        def __getitem__(self, k):
            return self.get(k, "")

        def keys(self):
            return list(super().keys())

    texto = booking._whatsapp_confirmation_text(_Cita(
        cliente_id="demo", servicio="Corte y color", employee_name="Alicia",
        booking_date="2099-03-04", booking_time="10:00", booking_code="R-1234",
    ))
    assert "Cita confirmada" in texto
    assert "Corte y color" in texto and "Alicia" in texto and "10:00" in texto
    assert "R-1234" in texto
    # Nada de lo que sobra en WhatsApp.
    assert "Zona horaria" not in texto
    assert "http" not in texto  # el enlace va en el boton
    assert len(texto) < 400
