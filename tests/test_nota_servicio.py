"""Cada servicio puede llevar su propio aviso para el cliente.

Un salon manda el protocolo de "ven con el pelo lavado, 3 lavados y sin
mascarilla"... pero solo cuando la cita es de alisado. El mensaje de confirmacion
del negocio es uno para TODOS los servicios, asi que no habia donde poner algo
que cambia de un servicio a otro.

La nota sale con la CONFIRMACION (cuando la cita ya es suya), no antes: con una
senal pendiente la cita todavia puede caerse.
"""
from __future__ import annotations

import inspect
import pathlib
import uuid

from test_booking_exhaustive import api_module  # noqa: F401

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def _servicio_con_nota(api_module, nota):
    from backend import db, timeutils

    ahora = timeutils._utc_now_iso()
    slug = "svc_nota_" + uuid.uuid4().hex[:8]
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO services (cliente_id, slug, name, duration_minutes, price_cents,
                description, is_active, sort_order, booking_note, created_at, updated_at)
            VALUES ('demo', ?, ?, 60, 5000, '', 1, 0, ?, ?, ?)
            """,
            (slug, "Alisado " + slug[-4:], nota, ahora, ahora),
        )
        connection.commit()
    return slug


class _Cita(dict):
    def __getitem__(self, k):
        return self.get(k, "")

    def keys(self):
        return list(super().keys())


def test_la_nota_se_lee_del_servicio_de_la_cita(api_module):
    from backend import booking, db

    slug = _servicio_con_nota(api_module, "Ven con el pelo lavado y sin mascarilla.")
    try:
        with db._get_db_connection() as connection:
            nombre = connection.execute(
                "SELECT name FROM services WHERE cliente_id='demo' AND slug=?", (slug,)
            ).fetchone()["name"]
        cita = _Cita(cliente_id="demo", servicio=nombre, service_id=slug)
        assert booking.service_booking_note("demo", cita) == "Ven con el pelo lavado y sin mascarilla."
    finally:
        with db._get_db_connection() as connection:
            connection.execute("DELETE FROM services WHERE cliente_id='demo' AND slug=?", (slug,))
            connection.commit()


def test_un_servicio_sin_nota_no_anade_nada(api_module):
    from backend import booking, db

    slug = _servicio_con_nota(api_module, "")
    try:
        cita = _Cita(cliente_id="demo", servicio="", service_id=slug)
        assert booking.service_booking_note("demo", cita) == ""
    finally:
        with db._get_db_connection() as connection:
            connection.execute("DELETE FROM services WHERE cliente_id='demo' AND slug=?", (slug,))
            connection.commit()


def test_un_servicio_que_no_existe_no_rompe(api_module):
    from backend import booking

    assert booking.service_booking_note("demo", _Cita(cliente_id="demo", servicio="No existe")) == ""


def test_solo_sale_al_confirmar_no_al_pedir_la_senal(api_module):
    """Con la senal sin pagar la cita puede caerse: el protocolo llega despues."""
    from backend import booking

    fuente = inspect.getsource(booking._booking_email_bodies)
    assert 'if status_key == "confirmed" else ""' in fuente

    flujo = (RAIZ / "backend" / "whatsapp.py").read_text(encoding="utf-8")
    assert 'nota_servicio = "" if is_pending_payment else booking.service_booking_note' in flujo


def test_sale_por_los_tres_caminos_de_confirmacion(api_module):
    """Email (de ahi salen SMS y el WhatsApp largo), la confirmacion corta de
    WhatsApp, y el resumen del flujo cuando no hay senal."""
    from backend import booking

    assert "service_booking_note" in inspect.getsource(booking._booking_email_bodies)
    assert "service_booking_note" in inspect.getsource(booking._whatsapp_confirmation_text)
    assert "service_booking_note" in (RAIZ / "backend" / "whatsapp.py").read_text(encoding="utf-8")


def test_el_panel_deja_escribirla_y_la_anuncia(api_module):
    html = (RAIZ / "app_ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="svcBookingNote"' in html
    assert "Qué contarle al cliente al confirmar esta cita" in html
    # Va plegada en "Más opciones", pero el titulo avisa de que hay algo dentro.
    assert "'aviso al confirmar'" in html
    assert "booking_note });" in html


def test_viaja_en_el_modelo_publico(api_module):
    from api_models import ServicePayload, ServicePublic, ServiceUpdatePayload

    assert ServicePublic(id="x", nombre="X").booking_note == ""
    assert ServicePayload(nombre="X").booking_note == ""
    assert ServiceUpdatePayload().booking_note is None
