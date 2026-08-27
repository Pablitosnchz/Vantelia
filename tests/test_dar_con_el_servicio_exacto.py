# -*- coding: utf-8 -*-
"""Dar con el servicio EXACTO preguntando, y sin depender de que el modelo conteste.

Lo pidio el duenyo asi: *"si no sabe el servicio exacto que le haga preguntas para
saberlo, por ejemplo: el corte ¿de que seria, de hombre, mujer...?"*.

Dos mitades:

1. **La pregunta la escribe el catalogo**, no cada sitio la suya. `pregunta_para`
   es la unica fuente, y la usan por igual el flujo de reserva y la respuesta de
   "¿cuanto tarda?". Asi la clienta oye la misma pregunta venga por donde venga.

2. **Entender no puede depender del extractor.** El dato de la familia lo sacaba un
   modelo (`intents.extraer_datos_servicio`); cuando fallaba -cuota agotada,
   timeout, poca confianza- `elegir` se quedaba sin candidatos y la tool contestaba
   *"en este catalogo no hay nada que encaje"* a un "quiero un corte". Negar un
   servicio que SI existe es un fallo critico, y ocurria justo cuando el modelo iba
   mal, que es cuando menos se puede permitir.

Aqui el extractor esta CAIDO a proposito en todos los casos.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CATALOGO = [
    ("ex_corte_sra", "Corte senora", "Cortes", 20),
    ("ex_corte_hom", "Corte hombre", "Cortes", 30),
    ("ex_corte_nino", "Corte nino", "Cortes", 15),
    ("ex_mechas_cor", "Mechas corto", "Mechas", 90),
    ("ex_mechas_lar", "Mechas largo", "Mechas", 150),
]


@pytest.fixture()
def salon_sin_extractor(api_module, client, monkeypatch):  # noqa: F811
    """Catalogo puesto y el extractor del modelo caido."""
    from backend import appstate, db, intents, timeutils

    ahora = timeutils._utc_now().isoformat()
    with db._get_db_connection() as conexion:
        for slug, nombre, categoria, minutos in CATALOGO:
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo',?,?,?,?,0,'',1,0,?,?)",
                (slug, nombre, categoria, minutos, ahora, ahora))
        conexion.commit()
    with appstate.state_lock:
        appstate.intent_cache.clear()
    monkeypatch.setattr(intents, "extraer_datos_servicio", lambda *a, **k: None)
    try:
        yield "demo"
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute(
                "DELETE FROM services WHERE cliente_id='demo' AND slug LIKE 'ex_%'")
            conexion.commit()
        with appstate.state_lock:
            appstate.intent_cache.clear()


def test_con_el_extractor_caido_no_niega_un_servicio_que_existe(salon_sin_extractor):
    """El fallo critico: "quiero un corte" -> "aqui no hacemos eso"."""
    from backend import agent

    respuesta = agent._tool_buscar_servicio(salon_sin_extractor, {"descripcion": "quiero un corte"})
    assert respuesta.get("ok") is True, respuesta
    assert "no hay nada que encaje" not in str(respuesta.get("error") or "")


def test_pregunta_de_quien_es_el_corte(salon_sin_extractor):
    """El ejemplo textual del duenyo."""
    from backend import agent

    respuesta = agent._tool_buscar_servicio(salon_sin_extractor, {"descripcion": "quiero un corte"})
    assert respuesta.get("falta") == "para_quien"
    pregunta = respuesta.get("sugerencia") or ""
    assert "hombre" in pregunta and ("señora" in pregunta or "senora" in pregunta)


def test_si_ya_lo_ha_dicho_no_lo_repregunta(salon_sin_extractor):
    """Preguntarle lo que acaba de decir es lo que hace que se vaya."""
    from backend import agent

    respuesta = agent._tool_buscar_servicio(salon_sin_extractor, {"descripcion": "corte de senora"})
    assert respuesta.get("servicio") == "Corte senora", respuesta


def test_pregunta_el_largo_cuando_es_lo_que_falta(salon_sin_extractor):
    from backend import agent

    respuesta = agent._tool_buscar_servicio(salon_sin_extractor, {"descripcion": "unas mechas"})
    assert respuesta.get("falta") == "talla"
    assert "largo" in (respuesta.get("sugerencia") or "").lower()


def test_lo_que_de_verdad_no_existe_se_sigue_diciendo(salon_sin_extractor):
    """El respaldo no puede volverse un "si" a todo: seria peor."""
    from backend import agent

    respuesta = agent._tool_buscar_servicio(salon_sin_extractor, {"descripcion": "quiero un chiringuito"})
    assert respuesta.get("ok") is False


def test_la_pregunta_sale_del_catalogo_y_no_de_cada_sitio(api_module):  # noqa: F811
    """Una sola fuente: la reserva y la duracion preguntan lo mismo."""
    import inspect

    from backend import agent

    assert "pregunta_para" in inspect.getsource(agent._tool_buscar_servicio)
    assert "pregunta_para" in inspect.getsource(agent._cuanto_duran_juntos)
