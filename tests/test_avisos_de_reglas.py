# -*- coding: utf-8 -*-
"""El editor de reglas avisa de lo que no va a funcionar, antes de que lo descubra una clienta.

POR QUE EXISTE
--------------
Fase 3 del plan de consolidación (docs/PLAN_CONSOLIDACION_IA.md): «indicar configuración
inválida/conflictiva». Gana la primera regla activa por prioridad cuyas intenciones y
familias casen (`rules.match`). Con eso, un negocio podía guardar, sin que nada se lo
dijera:

- una regla que NUNCA salta, porque otra con más prioridad cubre los mismos casos;
- dos reglas para lo mismo con la misma prioridad (desempata el orden de creación);
- una regla sin «qué te piden», que casa con cualquier mensaje;
- una respuesta vacía, una intención que no existe o una familia que no está en su catálogo;
- «ofrecer cita» sin ningún servicio de valoración al que llevar (la oferta no hace nada).

Lo imposible se rechaza al guardar; lo dudoso se avisa en cada regla.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401

CATALOGO = [{"name": "Keratina premium largo", "category": "Alisados"},
            {"name": "Mechas medio", "category": "Color"},
            {"name": "Diagnóstico y presupuesto", "category": "Valoracion"}]


def _regla(id_, *, intenciones, familias=(), accion="responder", texto="Hola", prioridad=100, activa=True):
    return {"id": id_, "nombre": id_, "intenciones": list(intenciones), "familias": list(familias),
            "accion": accion, "texto": texto, "prioridad": prioridad, "activa": activa, "veces": 0}


@pytest.fixture
def catalogo(api_module, monkeypatch):  # noqa: F811
    from backend import booking, catalog_pick, intents

    monkeypatch.setattr(catalog_pick, "_servicios", lambda cliente_id, location_id="": list(CATALOGO))
    monkeypatch.setattr(intents, "familias_del_tenant", lambda cliente_id, **k: ["alisado", "color", "valoracion"])
    valoracion = {"id": "diagnostico", "nombre": "Diagnóstico y presupuesto"}
    monkeypatch.setattr(booking, "_servicio_de_valoracion", lambda cliente_id, **k: dict(valoracion))
    return valoracion


def _avisos(reglas):
    from backend import rules

    return rules.avisos("demo", reglas=reglas)


def test_una_regla_bien_puesta_no_tiene_avisos(catalogo):
    avisos = _avisos([_regla("a", intenciones=["presupuesto"], familias=["alisado"], accion="pedir_foto")])

    assert avisos == {"a": []}


def test_una_regla_tapada_por_otra_nunca_salta(catalogo):
    avisos = _avisos([
        _regla("general", intenciones=["precio", "presupuesto"], prioridad=10),
        _regla("alisado", intenciones=["precio"], familias=["alisado"], prioridad=50),
    ])

    assert any("nunca" in a.lower() and "general" in a for a in avisos["alisado"]), avisos
    assert avisos["general"] == []


def test_la_especifica_antes_que_la_general_no_esta_tapada(catalogo):
    """Control: así se hace bien, la más concreta con menos prioridad."""
    avisos = _avisos([
        _regla("alisado", intenciones=["precio"], familias=["alisado"], prioridad=10),
        _regla("general", intenciones=["precio"], prioridad=50),
    ])

    assert avisos == {"alisado": [], "general": []}


def test_misma_prioridad_para_los_mismos_casos(catalogo):
    avisos = _avisos([
        _regla("una", intenciones=["precio"], familias=["color"], prioridad=20),
        _regla("otra", intenciones=["precio", "presupuesto"], familias=["color"], prioridad=20),
    ])

    assert any("prioridad" in a.lower() for a in avisos["otra"]), avisos


def test_una_regla_desactivada_no_compite(catalogo):
    avisos = _avisos([
        _regla("vieja", intenciones=["precio"], prioridad=10, activa=False),
        _regla("nueva", intenciones=["precio"], familias=["color"], prioridad=50),
    ])

    assert avisos["nueva"] == []


@pytest.mark.parametrize("regla,pista", [
    (_regla("sin", intenciones=[]), "cualquier"),
    (_regla("rara", intenciones=["precio", "teletransporte"]), "teletransporte"),
    (_regla("muda", intenciones=["precio"], accion="responder", texto=""), "vac"),
    (_regla("uñas", intenciones=["precio"], familias=["manicura"]), "manicura"),
])
def test_lo_que_no_va_a_funcionar(catalogo, regla, pista):
    avisos = _avisos([regla])

    assert any(pista in a.lower() for a in avisos[regla["id"]]), avisos


def test_una_tecnica_del_catalogo_no_es_una_familia_desconocida(catalogo):
    """«keratina» no es una familia del negocio, pero está en el nombre de un servicio."""
    assert _avisos([_regla("k", intenciones=["orientacion"], familias=["keratina"], accion="ofrecer_cita")]) == {"k": []}


def test_ofrecer_cita_sin_valoracion_no_hace_nada(catalogo, monkeypatch):
    from backend import booking

    monkeypatch.setattr(booking, "_servicio_de_valoracion", lambda cliente_id, **k: {})
    avisos = _avisos([_regla("o", intenciones=["orientacion"], familias=["alisado"], accion="ofrecer_cita")])

    assert any("valoraci" in a.lower() for a in avisos["o"]), avisos


def test_continuar_sin_texto_es_valido(catalogo):
    """«continuar» no contesta: medir antes de activar una regla de verdad."""
    assert _avisos([_regla("medir", intenciones=["precio"], accion="continuar", texto="")]) == {"medir": []}


# ─── En el portal ─────────────────────────────────────────────────────────

def _limpiar():
    from backend import db

    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM business_rules WHERE cliente_id = 'demo'")
        conexion.commit()


@pytest.mark.parametrize("cuerpo,pista", [
    ({"intenciones": [], "accion": "responder", "texto": "Hola"}, "te piden"),
    ({"intenciones": ["teletransporte"], "accion": "responder", "texto": "Hola"}, "teletransporte"),
    ({"intenciones": ["precio"], "accion": "responder", "texto": "  "}, "texto"),
])
def test_lo_imposible_no_se_guarda(client, portal_cookies, cuerpo, pista):  # noqa: F811
    _limpiar()
    try:
        respuesta = client.post("/auth/app/business-rules", cookies=portal_cookies,
                                json=dict({"nombre": "mal"}, **cuerpo))
        assert respuesta.status_code == 400, respuesta.text
        assert pista in respuesta.json()["detail"].lower()
    finally:
        _limpiar()


def test_el_listado_trae_los_avisos_de_cada_regla(client, portal_cookies):  # noqa: F811
    _limpiar()
    try:
        for nombre, cuerpo in (("General", {"intenciones": ["precio"], "prioridad": 10}),
                               ("Color", {"intenciones": ["precio"], "familias": ["color"], "prioridad": 50})):
            creada = client.post("/auth/app/business-rules", cookies=portal_cookies,
                                 json=dict({"nombre": nombre, "accion": "responder", "texto": "Hola"}, **cuerpo))
            assert creada.status_code == 200, creada.text
        listado = client.get("/auth/app/business-rules", cookies=portal_cookies).json()
        por_nombre = {r["nombre"]: r for r in listado["items"]}
        assert por_nombre["General"]["avisos"] == []
        assert any("nunca" in a.lower() for a in por_nombre["Color"]["avisos"]), por_nombre["Color"]
    finally:
        _limpiar()


def test_el_panel_ensena_los_avisos(api_module):  # noqa: F811
    import pathlib

    html = (pathlib.Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")
    assert "regla.avisos" in html, "el listado de reglas no pinta los avisos"
