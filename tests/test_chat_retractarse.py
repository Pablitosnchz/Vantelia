# -*- coding: utf-8 -*-
"""Echarse atras tiene que borrar la gestion pendiente.

Encontrado auditando con `docs/CAZA_DE_FALLOS.md` (clase 3: estado que nadie
caduca; clase 2: no hay forma de salir).

`chat_manage_state` recuerda 15 minutos la intencion de cancelar para no pedir
los datos dos veces. Pero no habia forma de retractarse: tras

    > quiero cancelar mi cita
    > no, dejalo, mejor no
    > mi email es cliente@ejemplo.com y quiero reservar

el tercer mensaje entraba en la gestion de citas COMO CANCELACION, con el email
del cliente — es decir, pidiendo reservar se podia acabar cancelando. Es la clase
de fallo que borra datos de un cliente real, asi que se cubre con test.

Las dos reglas: retractarse limpia el estado, y una intencion nueva y contraria
(reservar) pisa a la recordada.
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


def _turno(booking, sesion, mensaje):
    return asyncio.run(booking._process_booking_management_message(
        cliente_id="demo", message=mensaje, request=None, source="chat", session_id=sesion,
    ))


@pytest.fixture
def sesion(api_module):
    from backend import booking

    identificador = "s_retract_test"
    booking._chat_manage_state_clear(identificador)
    yield identificador
    booking._chat_manage_state_clear(identificador)


RETRACTACIONES = ["no, dejalo", "olvidalo", "da igual", "mejor no", "nada, gracias", "no hace falta"]


@pytest.mark.parametrize("retractacion", RETRACTACIONES)
def test_retractarse_borra_la_gestion_pendiente(api_module, sesion, retractacion):
    from backend import booking

    _turno(booking, sesion, "quiero cancelar mi cita")
    assert booking._chat_manage_state_get(sesion).get("intent") == "cancel"

    _turno(booking, sesion, retractacion)
    assert not booking._chat_manage_state_get(sesion), (
        "tras %r no puede quedar una cancelacion pendiente" % retractacion
    )


def test_tras_retractarse_un_codigo_suelto_no_cancela(api_module, sesion):
    """El caso peligroso: el codigo llega despues y reactivaria la cancelacion."""
    from backend import booking

    _turno(booking, sesion, "quiero cancelar mi cita")
    _turno(booking, sesion, "nada, olvidalo")
    assert _turno(booking, sesion, "R-1234") is None


def test_pedir_reservar_pisa_una_cancelacion_recordada(api_module, sesion):
    from backend import booking

    _turno(booking, sesion, "quiero cancelar mi cita")
    resultado = _turno(booking, sesion, "mi email es cliente@ejemplo.com y quiero reservar")
    assert resultado is None, "pidiendo reservar no se puede acabar cancelando"
    assert not booking._chat_manage_state_get(sesion)


def test_la_gestion_normal_sigue_funcionando(api_module, sesion):
    """La memoria conversacional es util: no se puede romper por arreglar lo otro."""
    from backend import booking

    _turno(booking, sesion, "quiero cancelar mi cita")
    resultado = _turno(booking, sesion, "R-123456")
    assert resultado is not None, "dar el codigo despues tiene que seguir la gestion"
    assert booking._chat_manage_state_get(sesion).get("code") == "R-123456"


def test_una_frase_larga_con_da_igual_no_es_retractarse(api_module, sesion):
    """"me da igual el profesional pero quiero cancelar la del martes" NO es
    echarse atras. Por eso la retractacion exige un mensaje corto."""
    from backend import booking

    _turno(booking, sesion, "quiero cancelar mi cita")
    _turno(booking, sesion, "me da igual el profesional pero quiero cancelar la del martes")
    assert booking._chat_manage_state_get(sesion).get("intent") == "cancel"


def test_retractarse_sin_nada_pendiente_no_hace_nada(api_module, sesion):
    from backend import booking

    assert _turno(booking, sesion, "da igual") is None
    assert not booking._chat_manage_state_get(sesion)
