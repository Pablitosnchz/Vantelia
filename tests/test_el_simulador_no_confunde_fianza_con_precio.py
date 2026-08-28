# -*- coding: utf-8 -*-
"""La fianza no es un precio, y el medidor tiene que saberlo.

El salon prohibe dar precios de mechas y EXIGE avisar de la fianza antes de
reservar. Son dos cosas distintas, pero las dos llevan una cifra en euros, y el
detector de mentiras del simulador solo miraba eso: si aparecia "€" cerca de la
palabra "mechas", lo daba por precio prohibido.

Resultado medido el 28-ago-2026: 14 de 100 conversaciones marcadas como fallo
CRITICO, y las 14 estaban bien -decian exactamente lo que la duenya pidio que
dijeran-. Seis de ellas habrian salido "bien" del todo, asi que la tirada entera
salio cuatro puntos por debajo de la realidad.

Un medidor que castiga el comportamiento correcto es peor que no tener medidor:
lleva a "arreglar" lo que funciona.
"""
from __future__ import annotations

import importlib.util
import sys

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture()
def salon_sin_precios(api_module, client):  # noqa: F811
    """Un negocio con la regla de "de mechas no se da precio", como el piloto.

    Se monta aqui a proposito: la suite corre sobre una base aislada donde las
    reglas del salon real no existen, y sin regla el detector no marca nada, asi
    que el test pasaba en solitario y fallaba en la suite.
    """
    from backend import rules

    regla = rules.guardar("demo", nombre="Mechas: precio tras valoracion",
                          intenciones=["precio", "presupuesto"],
                          familias=["mechas", "balayage"], accion="ofrecer_cita",
                          texto="De mechas no damos precio sin ver el pelo.")
    try:
        yield "demo"
    finally:
        rules.borrar("demo", regla["id"])


def _simulador():
    """Importa el script sin que se lleve por delante la salida de pytest.

    `simular_clientas.py` envuelve `sys.stdout` al importarse para poder escribir
    acentos en la consola de Windows. Si lo hace sobre la salida capturada por
    pytest, al recogerse el envoltorio cierra el fichero y revienta la sesion
    entera. Se le da un stdout de mentira para que envuelva ese.
    """
    import io as _io

    spec = importlib.util.spec_from_file_location("sim_para_test", "scripts/simular_clientas.py")
    modulo = importlib.util.module_from_spec(spec)
    verdadero = sys.stdout
    sys.stdout = _io.TextIOWrapper(_io.BytesIO(), encoding="utf-8")
    try:
        spec.loader.exec_module(modulo)
    finally:
        sys.stdout = verdadero
    return modulo


AVISOS_DE_FIANZA = [
    "💫 Para reservar este servicio se abona una fianza de 50 €, que se descuenta del total. ¿Te cojo las mechas?",
    "Ah, y recuerda que este servicio lleva una fianza de 50 €. Mechas o balayage medio.",
    "La señal son 50 € y se descuenta el día de tu cita. ¿Confirmamos las mechas?",
]


@pytest.mark.parametrize("texto", AVISOS_DE_FIANZA)
def test_avisar_de_la_fianza_no_es_dar_un_precio(salon_sin_precios, texto):
    modulo = _simulador()
    assert "da_un_precio_que_no_debe" not in modulo._mentiras(
        salon_sin_precios, [texto], []), (
        "el medidor castiga justo lo que el negocio pidio que se dijera"
    )


def test_un_precio_de_mechas_se_sigue_cazando(salon_sin_precios):
    """La otra mitad: si esto se relaja, el fallo caro deja de verse."""
    modulo = _simulador()
    assert "da_un_precio_que_no_debe" in modulo._mentiras(
        salon_sin_precios, ["Las mechas te salen por 145 €."], [])


def test_la_fianza_no_tapa_un_precio_dicho_en_la_misma_respuesta(salon_sin_precios):
    """Colar el precio detrás de la palabra "fianza" no puede funcionar."""
    modulo = _simulador()
    assert "da_un_precio_que_no_debe" in modulo._mentiras(
        salon_sin_precios,
        ["La señal son 50 €. Las mechas cuestan 145 €."], [])


def test_una_cita_imposible_se_juzga_por_la_salida_que_se_ofrece():
    """Hay una clienta del banco que SOLO puede venir cuando el salon esta cerrado.

    Exigirle una cita era castigar la respuesta correcta: las cuatro veces que
    salio, el asistente le habia dado horas reales de otros dias Y el telefono del
    salon, y las cuatro contaron como atasco.
    """
    from evals import clientas

    caso = [c for c in clientas.PERSONAS if c["id"] == "sin-hueco"]
    assert caso and caso[0].get("acepta_sin_cita") is True, (
        "el caso imposible tiene que estar declarado como tal"
    )
    modulo = _simulador()
    dichos = ["Ese dia no tengo hueco, cariño. Tengo el jueves a las 10:15 y 11:00."]
    assert modulo._ofrecio_una_salida("demo", dichos) is True


def test_despedirla_sin_nada_sigue_siendo_un_atasco():
    """La otra mitad: si no se le ofrece nada, es un fallo aunque la cita fuera imposible."""
    modulo = _simulador()
    assert modulo._ofrecio_una_salida(
        "demo", ["Lo siento, no tenemos hueco. Un saludo."]) is False


def test_reensenyar_el_resumen_no_es_repetirse():
    """Cuando ella corrige un dato hay que volver a ensenyarle el resumen."""
    modulo = _simulador()
    resumen = "📋 *Resumen de tu cita*\n\n👤 Laura\n🛍️ Corte señora\n\n¿Confirmamos la cita?"
    assert modulo._se_repite([resumen, "¿A nombre de quien?", resumen]) is False
