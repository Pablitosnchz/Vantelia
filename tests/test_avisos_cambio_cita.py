"""Cancelar y cambiar una cita se avisan como la confirmacion, no con el correo.

Caso real (ago 2026): a una clienta que reservo por WhatsApp le llegaba, al
cambiarle o cancelarle la cita, el cuerpo del email convertido a texto: "Zona
horaria: Europe/Madrid", la URL de gestion en crudo, el contacto repetido y la
fecha como 19/08/2026 en vez de "miercoles 19 de agosto". Justo lo que ya se
habia quitado de la confirmacion.

Y se le mandaba el MOTIVO de la cancelacion, que escribe el salon en su panel
para su propio registro.
"""
from __future__ import annotations

import inspect

from test_booking_exhaustive import api_module  # noqa: F401


class _Cita(dict):
    def __getitem__(self, k):
        return self.get(k, "")

    def keys(self):
        return list(super().keys())


def _cita(**extra):
    base = dict(cliente_id="demo", servicio="Corte señora", employee_name="Alicia",
                booking_date="2099-08-19", booking_time="12:30", booking_code="R-1234")
    base.update(extra)
    return _Cita(**base)


def test_la_cita_cambiada_se_avisa_en_corto(api_module):
    from backend import booking

    texto = booking._whatsapp_notice_text(_cita(), "rescheduled")
    assert "Cita cambiada" in texto
    assert "Corte señora" in texto and "12:30" in texto
    assert "R-1234" in texto
    # Nada del correo.
    assert "Zona horaria" not in texto
    assert "http" not in texto          # el enlace va en el boton
    assert "Contacto:" not in texto
    assert len(texto) < 300


def test_la_fecha_se_dice_en_humano(api_module):
    """El correo decia 19/08/2026; la confirmacion ya decia "19 de agosto"."""
    from backend import booking

    texto = booking._whatsapp_notice_text(_cita(), "rescheduled")
    assert "agosto" in texto
    assert "19/08" not in texto


def test_la_cancelacion_no_ofrece_gestionar_una_cita_que_no_existe(api_module):
    from backend import booking

    texto = booking._whatsapp_notice_text(_cita(), "cancelled")
    assert "Cita cancelada" in texto
    assert "12:30" in texto              # se recuerda cual era
    assert "R-1234" not in texto         # ya no sirve de nada
    assert "http" not in texto
    assert "otro hueco" in texto         # se le dice como conseguir otra

    fuente = inspect.getsource(booking._send_booking_whatsapp_reminder)
    assert "Sin boton: la cita ya no existe" in fuente


def test_el_motivo_de_cancelacion_no_llega_al_cliente(api_module):
    """Lo escribe el salon para su registro; acababa leyendolo la clienta."""
    from backend import booking

    fuente = inspect.getsource(booking._booking_email_bodies)
    assert "Motivo de cancelacion" not in fuente
    assert "acababa leyendolo" in fuente  # queda explicado por que


def test_los_tres_avisos_salen_del_mismo_sitio(api_module):
    from backend import booking

    fuente = inspect.getsource(booking._send_booking_whatsapp_reminder)
    assert '_whatsapp_notice_text(booking_row, kind)' in fuente
    assert 'kind in ("confirmed", "rescheduled")' in fuente


def test_si_el_boton_falla_sigue_saliendo_el_texto_largo(api_module):
    """Meta puede rechazar el interactivo: nadie se queda sin aviso."""
    from backend import booking

    fuente = inspect.getsource(booking._send_booking_whatsapp_reminder)
    assert "_booking_message_text_for_channel" in fuente
