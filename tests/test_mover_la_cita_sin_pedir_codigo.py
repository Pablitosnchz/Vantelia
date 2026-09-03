# -*- coding: utf-8 -*-
"""Para mover SU cita no se le pide un codigo que ya sabemos.

POR QUE EXISTE
--------------
3-sep-2026, medido contra datos de PRODUCCION. La clienta quiere mover su cita y
la conversacion no cierra nunca:

    ELLA  Me viene bien a las 14:00.
    IA    ... el 8 de septiembre a las 14:00. Confirmas esta cita?
    ELLA  Confirmo.
    IA    ... Confirmas esta cita?
    ELLA  Confirmo.                      (seis veces)

Instrumentando el estado turno a turno se ve la causa en una linea:

    [estado] intencion=cancelar codigo= fecha=2026-09-08 hora=14:00 FALTA='codigo'

`que_falta` devuelve 'codigo' SIEMPRE, asi que `instruccion_de_cierre` -la unica
que dice "llama a reprogramar_cita AHORA"- no sale nunca y el modelo se queda
pidiendo una confirmacion que no lleva a ninguna parte.

Y pedirle el codigo no tenia sentido: tiene UNA sola cita y el telefono viene
verificado por el canal. Las propias tools ya buscan por telefono sin codigo; el
unico que lo exigia era este estado.

SOLO PARA REPROGRAMAR. Con `cancelar` esto es peligrosisimo, y se probo: a
"Hola! Queria hablar sobre mi cita" -que el canal habia marcado como cancelar- le
contesto "he cancelado tu cita del 5 de septiembre" en el PRIMER mensaje. Anular
es destructivo; mover no rompe nada que no se pueda volver a mover.

MEDIDO con `--persona cambiar-hora`, 8 conversaciones, datos de produccion:

    base                                    50,0 %  (4 atascadas sin mover la cita)
    + freno del dia que nadie pidio         37,5 %  (3 citas duplicadas) -> retirado
    sin ese freno, con el codigo automatico 87,5 %  (0 atascadas)
"""
from __future__ import annotations

import inspect

from test_booking_exhaustive import api_module  # noqa: F401


def test_el_codigo_se_rellena_solo_al_reprogramar(api_module):
    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "citas_vivas_del_telefono" in fuente, (
        "sin esto `que_falta` devuelve 'codigo' para siempre y la cita no se mueve"
    )


def test_cancelar_NO_se_autocompleta(api_module):
    """Probado: autocompletarlo cancelaba la cita en el primer mensaje."""
    from backend import agent

    fuente = inspect.getsource(agent.responder)
    i = fuente.index("citas_vivas_del_telefono")
    trozo = fuente[max(0, i - 700):i]

    assert 'estado.intencion == "reprogramar"' in trozo, (
        "tiene que ser SOLO para reprogramar: con cancelar, a 'queria hablar "
        "sobre mi cita' le contesto 'he cancelado tu cita' de entrada"
    )
    assert '"cancelar", "reprogramar"' not in trozo, (
        "si vuelve a incluir cancelar, esto cancela citas de verdad"
    )


def test_solo_si_tiene_UNA_cita(api_module):
    from backend import agent

    fuente = inspect.getsource(agent.responder)
    i = fuente.index("citas_vivas_del_telefono")
    trozo = fuente[i:i + 400]

    assert "len(" in trozo and "== 1" in trozo, (
        "con varias citas no se puede adivinar cual quiere mover"
    )
