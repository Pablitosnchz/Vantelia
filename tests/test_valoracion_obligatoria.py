# -*- coding: utf-8 -*-
"""Hay familias en las que el diagnostico NO se puede saltar.

POR QUE EXISTE
--------------
3-sep-2026, la duenya del salon, en sus palabras:

    "En caso de extensiones siempre tiene que haber un diagnostico para que
    podamos pedir las extensiones, ver cuantas son las que quiere y demas [...]
    Ademas tengo que ver a la clienta, su pelo, el color, para poder pedir las
    extensiones. O sea que ese servicio si o si tiene que pasar por el salon."

Y sobre la fianza:

    "La fianza para las extensiones no tiene que pedirla ahi. Depende de si quiere
    un paquete, dos o tres [...] cuando le hago el diagnostico le doy un
    presupuesto y ya le pido la mitad. Eso ya tengo que ser yo en persona."

Ese segundo punto se cumple SOLO: si las extensiones no se pueden reservar
directamente, el resumen de esa cita no llega a salir y su fianza -100 EUR en el
catalogo- no se menciona nunca.

NO ES LO MISMO que `_familias_que_exigen_valoracion`: ahi caen las familias de
las que no se da precio por mensaje, y de esas la clienta SI puede saltarse el
diagnostico si insiste. Unas mechas se cogen directamente -eso se arreglo esta
misma manyana y no puede romperse-. Las extensiones no.

Va en la config del negocio (`booking.valoracion_obligatoria`), vacia por
defecto: otro salon pondra las suyas o ninguna, y sin configurarla nada cambia.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401

CID = "demo"


def _con_obligatoria(monkeypatch, familias):
    from backend import clients

    monkeypatch.setattr(clients, "_get_client_config",
                        lambda c, **k: {"booking": {"valoracion_obligatoria": familias}})


def test_las_extensiones_no_admiten_atajo(api_module, monkeypatch):
    from backend import booking

    _con_obligatoria(monkeypatch, ["extensiones"])

    for dicho in ("quiero extensiones sin diagnostico",
                  "quiero cita para extensiones directamente",
                  "no quiero diagnostico, quiero las extensiones ya"):
        assert not booking.puede_saltarse_la_valoracion(CID, dicho), dicho


def test_las_mechas_siguen_pudiendo(api_module, monkeypatch):
    """Arreglado esta misma manyana: no puede romperse."""
    from backend import booking

    _con_obligatoria(monkeypatch, ["extensiones"])

    for dicho in ("quiero las mechas directamente, sin diagnostico",
                  "no quiero cita para diagnostico quiero cita para hacermelas"):
        assert booking.puede_saltarse_la_valoracion(CID, dicho), dicho


def test_sin_configurar_nada_cambia(api_module, monkeypatch):
    from backend import booking

    _con_obligatoria(monkeypatch, [])

    assert booking.puede_saltarse_la_valoracion(
        CID, "quiero extensiones sin diagnostico"), (
        "sin la lista, el comportamiento tiene que ser el de siempre"
    )
