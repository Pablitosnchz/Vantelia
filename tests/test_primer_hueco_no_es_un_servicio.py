# -*- coding: utf-8 -*-
"""«El primer hueco que tengas» no es pedir la «Primera sesión con depósito».

POR QUE EXISTE
--------------
Medido el 16-sep-2026 con modelo real en el segundo negocio del cierre de Alicia
(metareview, caso crítico `reserva-completa-de-verdad`, también con el código de
producción): las familias de servicio salen de la primera palabra de cada nombre, así
que «Primera sesion con deposito» daba la familia «primera». A «quiero cita para una
sesion estandar» + «el primer hueco que tengas», el freno de varios servicios veía dos
familias, frenaba la cita y ofrecía la sesión con fianza de 30 € a quien había pedido
la estándar. El resumen llegaba un turno tarde y la clienta se quedaba sin cita.
Cualquier negocio con «Primera visita» o «Primera consulta» tenía el mismo fallo.

Revisión de Codex a 78d931e: saltarse el ordinal y quedarse con la palabra de detrás
creaba otra familia falsa («Primera consulta dermatologica» → «consulta», y «consultar el
precio del láser» frenaba la cita del láser). Un nombre que empieza por ordinal no da
familia; su categoría sí.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

CLIENTE = "demo"
CATALOGO = [("Sesion estandar QA", "Sesiones QA", 60), ("Primera sesion con deposito QA", "Sesiones QA", 60),
            ("Primera visita QA", "Primeras visitas QA", 30),
            ("Primera consulta dermatologica QA", "Dermatologia QA", 30), ("Laser facial QA", "Laser QA", 30)]


@pytest.fixture
def catalogo(api_module):  # noqa: F811
    from backend import agenda, appstate, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for nombre, categoria, minutos in CATALOGO:
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, duration_minutes, price_cents, description,"
                " is_active, sort_order, category, created_at, updated_at) VALUES (?, ?, ?, ?, 1000, '', 1, 0, ?, ?, ?)",
                (CLIENTE, agenda._normalize_service_id(nombre), nombre, minutos, categoria, ahora, ahora))
        conexion.commit()
    with appstate.state_lock:
        appstate.intent_cache.clear()
    yield
    with db._get_db_connection() as conexion:
        for nombre, _categoria, _minutos in CATALOGO:
            conexion.execute("DELETE FROM services WHERE cliente_id=? AND name=?", (CLIENTE, nombre))
        conexion.commit()
    with appstate.state_lock:
        appstate.intent_cache.clear()


def test_un_ordinal_no_es_una_familia_de_servicio(catalogo):
    from backend import intents

    familias = intents.familias_del_tenant(CLIENTE)
    assert "primera" not in familias and not any(f.startswith("primeras") for f in familias), familias
    assert "visitas qa" in familias, familias
    assert "consulta" not in familias, familias


@pytest.mark.parametrize("hueco", ["el primer hueco que tengas", "la primera que tengas", "primero quiero saber la hora"])
def test_pedir_el_primer_hueco_no_frena_la_cita(catalogo, hueco):
    from backend import agent

    mensajes = [{"role": "user", "content": t}
                for t in ("hola quiero cita para una sesion estandar", hueco, "me llamo Marta Ruiz Gomez")]
    freno = agent._freno_de_varios_servicios(CLIENTE, mensajes, {"servicio": "Sesion estandar QA"})
    assert freno is None, freno and freno["error"]


def test_la_palabra_detras_del_ordinal_no_es_una_familia(catalogo):
    """Revisión de Codex a 78d931e: con «Primera consulta dermatologica» en el catálogo, «consultar el
    precio del láser» contaba como pedir una consulta y un láser, y frenaba la cita del láser."""
    from backend import agent

    mensajes = [{"role": "user", "content": "quiero consultar el precio del laser y reservarlo"}]
    freno = agent._freno_de_varios_servicios(CLIENTE, mensajes, {"servicio": "Laser facial QA"})
    assert freno is None, freno and freno["error"]
