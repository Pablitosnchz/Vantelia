# -*- coding: utf-8 -*-
"""Lo que el negocio no hace se dice claro, lo extraiga el modelo como técnica o como familia.

POR QUE EXISTE
--------------
14-sep-2026, banco del segundo negocio (metareview, sin manicura en el catálogo) medido con
modelo real sobre copia de producción (ed94be1), 2 de 2 intentos, leído en agent_turns:

    ella «hola, me quiero hacer la manicura»
         buscar_servicio -> {"ok": false, "error": "En este catalogo no hay nada que encaje con eso."}
    IA   «¿Qué tipo de manicura te gustaría hacerte?»          <-- como si la hicieran

El día anterior, con el mismo código de elección, contestaba «no tenemos ese servicio»: la
herramienta decía «no hay ningún servicio de manicura» con parecidos y la orden de no
inventar. La diferencia la ponía el extractor (un modelo): esa comprobación solo miraba la
TÉCNICA, y hoy «manicura» vino como FAMILIA. Misma clase que el pack del 13-sep: la
decisión no puede depender de en qué campo apunte el modelo lo que ha dicho.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

CATALOGO = [{"name": "Sesion estandar", "category": "Sesiones"},
            {"name": "Corte señora", "category": "Peluqueria"}]


def _buscar(monkeypatch, extraido):
    from backend import agent, catalog_pick, intents

    monkeypatch.setattr(catalog_pick, "_servicios", lambda cliente_id, location_id="": list(CATALOGO))
    monkeypatch.setattr(intents, "familias_del_tenant", lambda cliente_id, **k: ["sesiones", "corte"])
    monkeypatch.setattr(intents, "extraer_datos_servicio", lambda cliente_id, dicho, **k: dict(extraido))
    monkeypatch.setattr(agent, "_es_el_nombre_de_un_servicio", lambda *a, **k: "")
    return agent._tool_buscar_servicio("demo", {"descripcion": "hola, me quiero hacer la manicura"})


@pytest.mark.parametrize("extraido", [
    {"familia": "manicura", "tecnica": "", "talla": "", "para_quien": "", "edad": None,
     "texto": "hola, me quiero hacer la manicura"},                       # lo de hoy
    {"familia": "", "tecnica": "manicura", "talla": "", "para_quien": "", "edad": None,
     "texto": "hola, me quiero hacer la manicura"},                       # lo de ayer
])
def test_lo_que_no_se_hace_se_nombra(api_module, monkeypatch, extraido):  # noqa: F811
    resultado = _buscar(monkeypatch, extraido)

    assert resultado.get("ok") is False
    assert "manicura" in str(resultado.get("error") or ""), (
        "respuesta generica: el modelo acaba preguntando que tipo de manicura quiere. %r" % resultado)
    assert resultado.get("no_inventes")


def test_una_familia_del_negocio_no_se_niega(api_module, monkeypatch):  # noqa: F811
    """Control: pedir algo de una familia que el negocio SÍ tiene no dice que no se hace."""
    resultado = _buscar(monkeypatch, {"familia": "corte", "tecnica": "", "talla": "", "para_quien": "",
                                      "edad": None, "texto": "quiero un corte"})

    assert "ningun servicio de" not in str(resultado.get("error") or ""), resultado
