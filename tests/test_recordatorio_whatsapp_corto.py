"""El recordatorio por WhatsApp va en corto, no con el cuerpo del correo.

Hasta ahora la confirmacion y el cambio de cita ya se escribian para el movil,
pero el recordatorio de 24 h seguia mandando el email entero convertido a texto:
zona horaria, contacto, el enlace de gestion en crudo... y debajo los botones
"Confirmo" / "Cancelar cita", que quedaban a tres pantallas de scroll.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


class _Cita(dict):
    def __getitem__(self, k):
        return self.get(k, "")

    def keys(self):
        return list(super().keys())


def _cita(**extra):
    base = dict(cliente_id="demo", servicio="Corte señora", employee_name="Alicia",
                booking_date="2099-08-19", booking_time="12:30", booking_code="R-1234",
                status="confirmed")
    base.update(extra)
    return _Cita(**base)


def test_el_recordatorio_de_24h_es_corto(api_module):
    from backend import booking

    texto = booking._whatsapp_notice_text(_cita(), "reminder_24h")
    assert "Recordatorio" in texto
    assert "Corte señora" in texto and "12:30" in texto and "agosto" in texto
    # Nada de lo que arrastraba del correo.
    assert "Zona horaria" not in texto
    assert "http" not in texto
    assert len(texto) < 400


def test_el_recordatorio_pide_respuesta_porque_lleva_botones(api_module):
    from backend import booking

    texto = booking._whatsapp_notice_text(_cita(), "reminder_24h")
    assert "confirmas" in texto.lower()


def test_el_recordatorio_de_2h_no_pide_confirmacion_de_asistencia(api_module):
    """A dos horas ya no se pide "¿vienes?": se avisa y se ofrece cancelar."""
    from backend import booking

    texto = booking._whatsapp_notice_text(_cita(), "reminder_2h")
    assert "dentro de poco" in texto.lower()
    assert "confirmas" not in texto.lower()


def test_el_aviso_del_servicio_se_repite_a_24h(api_module, monkeypatch):
    """"Ven con el pelo lavado" importa el dia antes, no solo al reservar."""
    from backend import booking

    monkeypatch.setattr(booking, "service_booking_note", lambda *a, **k: "Ven con el pelo lavado.")
    assert "pelo lavado" in booking._whatsapp_notice_text(_cita(), "reminder_24h")
    # A dos horas ya no sirve de nada.
    assert "pelo lavado" not in booking._whatsapp_notice_text(_cita(), "reminder_2h")


def test_el_envio_usa_el_texto_corto_en_los_recordatorios(api_module):
    """Que el builder exista no basta: el envio tiene que llamarlo."""
    import inspect

    from backend import booking

    fuente = inspect.getsource(booking._send_booking_whatsapp_reminder)
    assert "WA_NOTICE_KINDS" in fuente
    assert "reminder_24h" in booking.WA_NOTICE_KINDS
