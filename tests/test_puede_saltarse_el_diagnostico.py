# -*- coding: utf-8 -*-
"""Se le sugiere el diagnostico, pero si dice que no, se le coge lo que pide.

POR QUE EXISTE
--------------
3-sep-2026, reportado probando la demo. Pidio unas mechas, se le ofrecio el
diagnostico -bien, es la politica del salon- y a partir de ahi no hubo manera:

    ELLA  vale y puedo coger las mechas directamente? sin el diagnostico
    ELLA  pero no quiero cita para el diagnostico quiero cita para hacermelas
    ELLA  quiero cita para las mechas directamente
    ELLA  a las 10
    IA    Te lo digo con sinceridad, carino: el precio depende mucho de tu pelo...
          Te busco un hueco para el diagnostico?          (otra vez, y otra)

Se quedo SIN CITA. La regla del salon, en sus palabras, es justo la contraria:
"para coger unas mechas la cita hay que cogersela directamente preguntandole como
tiene el pelo de largo; lo del diagnostico es simplemente para las clientas que
pidan presupuesto".

DOS causas, las dos medidas con la traza de frenos puesta:

1. Haber preguntado el precio UNA vez se quedaba pegado a la conversacion para
   siempre, asi que el freno del precio volvia a saltar en cada intento de cerrar
   aunque ella ya hubiera rechazado el diagnostico cuatro veces.

2. El freno del abandono leia "no quiero cita" en "no quiero cita PARA EL
   DIAGNOSTICO" y se despedia de alguien que acababa de pedir una cita.

La segunda es la mas fea: un guardarrail escrito la noche anterior comiendose una
peticion de cita. Por eso ahora, si en el MISMO mensaje pide algo, no se le trata
como que se va.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def test_reconoce_que_rechaza_el_diagnostico(api_module):
    from backend import booking

    for m in ("puedo coger las mechas directamente? sin el diagnostico",
              "no quiero cita para el diagnostico quiero cita para hacermelas",
              "quiero cita para las mechas directamente",
              "sin diagnostico por favor"):
        assert booking.renuncio_al_diagnostico(m), m


def test_pedir_presupuesto_NO_es_rechazarlo(api_module):
    """Ofrecerselo la primera vez es la politica del salon y sigue igual."""
    from backend import booking

    for m in ("cuanto cuestan unas mechas?", "quiero cita para unas mechas",
              "vale, agendame el diagnostico"):
        assert not booking.renuncio_al_diagnostico(m), m


def test_rechazar_una_cita_y_pedir_otra_no_es_irse(api_module):
    from backend import agent

    empuja = "Entiendo, pero necesito saber el largo de tu cabello."

    assert not agent._sigue_insistiendo_tras_dejarlo(
        "no quiero cita para el diagnostico, quiero cita para hacermelas", empuja), (
        "se despedia de alguien que acababa de pedir una cita"
    )
    assert not agent._sigue_insistiendo_tras_dejarlo(
        "no quiero el diagnostico, cogeme las mechas", empuja)

    # Irse de verdad sigue frenando.
    for m in ("no quiero cita, gracias", "no necesito cita",
              "dejalo, ya lo miro luego", "solo pregunte por los horarios"):
        assert agent._sigue_insistiendo_tras_dejarlo(m, empuja), m


def test_el_freno_del_precio_se_aparta_si_lo_rechazo(api_module):
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_freno_del_precio)
    assert "renuncio_al_diagnostico_en_la_conversacion" in fuente, (
        "sin esto, cada vez que llega al resumen le vuelve a salir el diagnostico"
    )
    i = fuente.index("renuncio_al_diagnostico_en_la_conversacion")
    assert "pidio_precio" not in fuente[:i], (
        "tiene que apartarse ANTES de calcular el bloqueo"
    )
