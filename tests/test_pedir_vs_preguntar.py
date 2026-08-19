# -*- coding: utf-8 -*-
"""Preguntar POR cancelar no es pedir cancelar.

Encontrado con un fuzzer de entradas raras (`docs/CAZA_DE_FALLOS.md`). Los
detectores casaban la palabra suelta, asi que estas dos frases recibian
"Para cancelar tu cita necesito el número de reserva":

    > no quiero cancelar nada, solo preguntar
    > ¿puedo cancelar si me surge algo?

La primera dice literalmente que NO. La segunda pregunta por la politica del
negocio, que es justo lo que el negocio ha escrito en su Q&A o en su info.txt y
lo que deberia contestar el cerebro. Responder con el formulario de cancelacion
es peor que no entender: parece que vamos a cancelarle la cita.

El detector de reprogramar tenia el mismo fallo en los seis casos equivalentes.
"""
from __future__ import annotations

import pytest

from backend import booking

# Peticiones REALES: tienen que seguir funcionando. Si una de estas se rompe, el
# cliente que quiere cancelar de verdad se queda sin poder hacerlo.
PIDE_CANCELAR = [
    "quiero cancelar mi cita",
    "necesito cancelar",
    "cancelar mi cita R-123456",
    "anular mi cita",
    "cancela mi cita del martes",
    "quiero anular la reserva",
    "cancelar",
    "borrar cita",
    "me gustaria cancelar la cita de mañana",
    # La negacion es de OTRA cosa ("no puedo ir"), no de cancelar.
    "no puedo ir el martes, quiero cancelar",
]

PREGUNTA_POR_CANCELAR = [
    "no quiero cancelar nada, solo preguntar",
    "no voy a cancelar",
    "no pienso cancelar",
    "¿puedo cancelar si me surge algo?",
    "¿que pasa si cancelo?",
    "¿hasta cuando puedo cancelar?",
    "¿me cobrais si cancelo?",
    "¿con cuanta antelacion hay que cancelar?",
    "¿hay penalizacion por cancelar?",
    "¿se puede cancelar por aqui?",
    "cuales son las condiciones de cancelacion",
]

PIDE_CAMBIAR = [
    "quiero cambiar mi cita",
    "necesito mover la cita",
    "cambiar la fecha de mi reserva",
    "reprogramar cita",
    "cambiala al viernes",
    "quiero cambiar la hora de mi cita",
]

PREGUNTA_POR_CAMBIAR = [
    "no quiero cambiar la cita",
    "¿puedo cambiar la cita si me surge algo?",
    "¿que pasa si tengo que cambiar la fecha?",
    "¿hasta cuando puedo cambiar la cita?",
    "¿se puede cambiar la hora despues?",
    "¿cobrais por cambiar la cita?",
]


@pytest.mark.parametrize("mensaje", PIDE_CANCELAR)
def test_una_peticion_real_de_cancelar_se_detecta(mensaje):
    assert booking._message_requests_cancel_booking(mensaje), mensaje


@pytest.mark.parametrize("mensaje", PREGUNTA_POR_CANCELAR)
def test_preguntar_por_cancelar_no_es_pedirlo(mensaje):
    assert not booking._message_requests_cancel_booking(mensaje), mensaje


@pytest.mark.parametrize("mensaje", PIDE_CAMBIAR)
def test_una_peticion_real_de_cambiar_se_detecta(mensaje):
    assert booking._message_requests_reschedule_booking(mensaje), mensaje


@pytest.mark.parametrize("mensaje", PREGUNTA_POR_CAMBIAR)
def test_preguntar_por_cambiar_no_es_pedirlo(mensaje):
    assert not booking._message_requests_reschedule_booking(mensaje), mensaje


def test_la_negacion_tiene_que_ir_pegada_al_verbo():
    """"no puedo ir el martes, quiero cancelar" SI es una peticion.

    Por eso la negacion solo cuenta con dos palabras como mucho por medio: si no,
    cualquier "no" en la frase anularia una peticion legitima.
    """
    assert booking._message_requests_cancel_booking("no puedo ir el martes, quiero cancelar")
    assert not booking._message_requests_cancel_booking("no quiero cancelar")


# ─── Pago: pedir el enlace vs preguntar por el pago ────────────────────────
# Mandar un enlace de cobro a quien solo pregunta "¿se puede pagar con tarjeta?"
# —o a quien dice "no quiero pagar ahora"— es de las cosas que peor sientan.

PIDE_PAGAR = [
    "quiero pagar",
    "mandame el enlace de pago",
    "quiero pagar la señal",
    "como pago la señal",
    "pagar",
    "quiero abonar la señal",
    "pagar la señal",
]

PREGUNTA_POR_EL_PAGO = [
    "¿hay que pagar algo por adelantado?",
    "¿se puede pagar con tarjeta?",
    "¿cuanto hay que pagar de señal?",
    "no quiero pagar ahora",
    "¿que metodos de pago aceptais?",
    "¿es obligatorio pagar la señal?",
    "¿puedo pagar el dia de la cita?",
    "¿hace falta pagar antes?",
]


@pytest.mark.parametrize("mensaje", PIDE_PAGAR)
def test_pedir_pagar_se_detecta(mensaje):
    assert booking._message_requests_payment(mensaje), mensaje


@pytest.mark.parametrize("mensaje", PREGUNTA_POR_EL_PAGO)
def test_preguntar_por_el_pago_no_manda_un_cobro(mensaje):
    assert not booking._message_requests_payment(mensaje), mensaje


# ─── "¿Cuándo tenéis libre?" es pedir hueco ────────────────────────────────

PIDE_HUECO = [
    "¿cuando teneis libre?",
    "¿cuando podeis?",
    "¿cuando os viene bien?",
    "¿cuando hay hueco?",
    "cuando tienen sitio",
]


@pytest.mark.parametrize("mensaje", PIDE_HUECO)
def test_preguntar_cuando_hay_hueco_consulta_disponibilidad(mensaje):
    """La forma mas natural de pedir cita, y no la reconocia ningun patron."""
    from backend import rag

    assert rag._message_requests_availability(mensaje), mensaje
