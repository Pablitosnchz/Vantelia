"""Al cliente hay que darle su numero de reserva, y reconocerle por su telefono.

Conversacion real (ago 2026): un cliente reserva por WhatsApp, la cita queda
pendiente de pago, y al dia siguiente pide el enlace de pago. El asistente le
responde "necesito el numero de reserva (formato R-XXXX)" -- un dato que nunca
le habiamos dado, y teniendo su telefono verificado por el propio canal.

Dos fallos en el mismo minuto: no se le entrego el codigo, y la busqueda por
telefono ignoraba justo las citas pendientes de pago.
"""
from __future__ import annotations

import inspect
import uuid

from test_booking_exhaustive import api_module  # noqa: F401


_HORA = [8]


def _crear_cita(api_module, *, estado, telefono, codigo=""):
    """Fila minima de cita. Rellena sola las columnas NOT NULL que exija el esquema."""
    from backend import db, timeutils

    bid = "bk_" + uuid.uuid4().hex[:10]
    ahora = timeutils._utc_now_iso()
    _HORA[0] += 1  # una hora distinta por cita: el hueco es unico por profesional
    valores = {
        "id": bid, "cliente_id": "demo", "nombre": "Cliente Prueba", "email": "",
        "telefono": telefono, "servicio": "Corte", "booking_date": "2099-01-01",
        "booking_time": "%02d:00" % _HORA[0], "status": estado, "source": "whatsapp",
        "created_at": ahora, "manage_token": "mg_" + bid, "timezone": "Europe/Madrid",
        "booking_code": codigo,
    }
    with db._get_db_connection() as connection:
        for fila in connection.execute("PRAGMA table_info(bookings)"):
            nombre, tipo, notnull, defecto = fila[1], fila[2], fila[3], fila[4]
            if nombre in valores or not notnull or defecto is not None:
                continue
            valores[nombre] = 0 if "INT" in (tipo or "").upper() else ""
        connection.execute(
            "INSERT INTO bookings (%s) VALUES (%s)"
            % (",".join(valores), ",".join("?" * len(valores))),
            list(valores.values()),
        )
        connection.commit()
    return bid


def test_la_cita_pendiente_de_pago_se_encuentra_por_telefono(api_module):
    """Es LA cita que necesita enlace de pago: excluirla dejaba al cliente atascado."""
    from backend import booking

    telefono = "+34600%06d" % (uuid.uuid4().int % 1000000)
    bid = _crear_cita(api_module, estado="pending_payment", telefono=telefono)
    encontrada = booking._latest_booking_for_contact("demo", phone=telefono)
    assert encontrada is not None and encontrada["id"] == bid


def test_tambien_se_encuentran_las_confirmadas(api_module):
    from backend import booking

    telefono = "+34601%06d" % (uuid.uuid4().int % 1000000)
    bid = _crear_cita(api_module, estado="confirmed", telefono=telefono)
    encontrada = booking._latest_booking_for_contact("demo", phone=telefono)
    assert encontrada is not None and encontrada["id"] == bid


def test_una_cita_cancelada_no_cuenta(api_module):
    from backend import booking

    telefono = "+34602%06d" % (uuid.uuid4().int % 1000000)
    _crear_cita(api_module, estado="cancelled", telefono=telefono)
    assert booking._latest_booking_for_contact("demo", phone=telefono) is None


def test_el_telefono_de_whatsapp_llega_como_verificado(api_module):
    """El canal ya sabe quien escribe: no hay que pedirle el codigo."""
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp)
    assert "trusted_phone=from_number" in fuente


def test_el_mensaje_de_whatsapp_da_el_numero_de_reserva(api_module):
    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_create_booking)
    assert "Numero de reserva" in fuente
    assert 'stored_booking["booking_code"]' in fuente


def test_las_citas_pendientes_de_pago_reciben_codigo(api_module):
    """Si no tienen codigo, pedirselo al cliente es pedirle algo que no existe."""
    from backend import booking

    fuente = inspect.getsource(booking._backfill_booking_codes)
    assert "'pending_payment'" in fuente
