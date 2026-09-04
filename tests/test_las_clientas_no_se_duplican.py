# -*- coding: utf-8 -*-
"""El banco de clientas del simulador no tiene ids repetidos.

POR QUE EXISTE
--------------
4-sep-2026: anyadi una clienta `servicio-que-no-hacen` que YA existia, sin mirar
antes la lista. Con ella dentro, esa situacion pesaba el doble en el porcentaje y
el numero salia sesgado sin que nadie lo notara.

Un medidor con una clienta duplicada miente en silencio, que es la peor forma de
mentir: no falla, solo da un numero distinto del que deberia.
"""
from __future__ import annotations


def test_no_hay_ids_repetidos():
    from evals.clientas import PERSONAS

    ids = [p["id"] for p in PERSONAS]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})

    assert not repetidos, (
        "una clienta duplicada pesa el doble en el porcentaje: " + ", ".join(repetidos)
    )


def test_cada_clienta_tiene_lo_que_el_juez_necesita():
    from evals.clientas import PERSONAS

    objetivos = {"reservar", "cancelar", "reprogramar", "preguntar_precio",
                 "consejo", "informacion", "hablar_con_persona"}
    for p in PERSONAS:
        assert p.get("id"), p
        assert p.get("objetivo") in objetivos, (
            "%s tiene un objetivo que el juez no sabe valorar: %r"
            % (p["id"], p.get("objetivo"))
        )
        assert p.get("estilos"), "%s no tiene estilos" % p["id"]
        assert p.get("quiere"), "%s no dice que quiere" % p["id"]
