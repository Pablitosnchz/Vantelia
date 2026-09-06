# -*- coding: utf-8 -*-
"""Con una cita a medias, las Q&A y las reglas del negocio no contestan encima.

POR QUE EXISTE
--------------
Medido el 6-sep-2026 sobre 100 conversaciones: 5 de los 18 fallos eran el mismo
bucle. La clienta preguntaba el precio, aceptaba la cita de diagnostico, elegia
dia y hora, daba su nombre... y al cerrar:

    ELLA: si, me llamo Laura. me la reservas, por favor?
    IA:   [le ofrece las horas]
    ELLA: la cita ya la tengo, es para el 8 a las 10. me confirmas?
    IA:   "Te lo digo con sinceridad, carino: el precio depende mucho de tu
           pelo..."      <- la regla del PRECIO, otra vez, encima de la reserva

El chat web ya se protegia de esto (`gestion_en_curso`), pero WhatsApp no pasaba
el aviso: su recorrido es propio y ahi la capa del negocio volvia a entrar en
cada mensaje. La clienta se iba sin cita despues de haberla elegido.

`reserva.hay_gestion_a_medias` es la fuente unica de "esta conversacion esta a
mitad de algo", para que los dos canales lo miren igual.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CID = "demo"
TEL = "34600444555"


@pytest.fixture(autouse=True)
def _limpio(api_module):  # noqa: F811
    from backend import reserva

    reserva.olvidar(CID, TEL) if hasattr(reserva, "olvidar") else None
    yield
    reserva.olvidar(CID, TEL) if hasattr(reserva, "olvidar") else None


def test_sin_nada_empezado_no_hay_gestion(api_module):  # noqa: F811
    from backend import reserva

    assert not reserva.hay_gestion_a_medias(CID, TEL)


@pytest.mark.parametrize("campo,valor", [
    ("intencion", "reservar"),
    ("servicio", "Diagnostico y presupuesto"),
    ("fecha", "2026-09-08"),
    ("hora", "10:00"),
    ("codigo", "R-123456"),
    ("esperando_confirmacion", True),
])
def test_con_algo_empezado_si_hay_gestion(api_module, campo, valor):  # noqa: F811
    from backend import reserva

    estado = reserva.cargar(CID, TEL)
    setattr(estado, campo, valor)
    reserva.guardar(CID, TEL, estado)
    assert reserva.hay_gestion_a_medias(CID, TEL), campo


def test_una_gestion_terminada_ya_no_cuenta(api_module):  # noqa: F811
    """Cerrada la cita, el negocio vuelve a poder contestar lo suyo."""
    from backend import reserva

    estado = reserva.cargar(CID, TEL)
    estado.intencion = "reservar"
    estado.fecha = "2026-09-08"
    estado.hecho = True
    reserva.guardar(CID, TEL, estado)
    assert not reserva.hay_gestion_a_medias(CID, TEL)


def test_whatsapp_avisa_a_la_capa_del_negocio(api_module):  # noqa: F811
    """El aviso tiene que VIAJAR: el chat web ya lo pasaba y WhatsApp no."""
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_message)
    assert "gestion_en_curso=" in fuente
    assert "hay_gestion_a_medias" in fuente


def test_la_capa_del_negocio_se_calla_con_gestion_a_medias(api_module):  # noqa: F811
    from backend import chat

    decision = chat.decision_del_negocio(
        CID, "la cita ya la tengo, es para el 8 a las 10. me confirmas?",
        gestion_en_curso=True,
    )
    assert decision is None or not (decision or {}).get("texto")
