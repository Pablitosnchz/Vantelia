# -*- coding: utf-8 -*-
"""Un pack de alisado ES un alisado, aunque este en la categoria "Packs".

Preguntando "¿cuanto tarda un alisado?" el asistente contestaba "de 15 a 30
minutos" en un salon cuyos alisados de verdad tardan entre dos horas y media y
cinco horas y media. No mentia: los packs -que son el servicio completo- viven en
la categoria "Packs" y no llevan la palabra "alisado" en el nombre, asi que al
preguntar por la FAMILIA no se veian. Solo aparecian las aplicaciones sueltas.

Las tecnicas de cada familia salen del catalogo del propio negocio: de "Acido
lactico bio premium-medio" y "Keratina premium xl" se deduce que "acido lactico" y
"keratina" son alisados, y con eso un "Pack acido lactico bio premium largo" se
reconoce como lo que es. Nada escrito a mano: otro negocio pone sus nombres y esto
sigue funcionando.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CATALOGO = [
    # (slug, nombre, categoria, minutos)  -- con la forma del catalogo real
    ("pk_ac_medio", "Acido lactico bio premium-medio", "Alisados", 30),
    ("pk_ke_corto", "Keratina premium corto medio", "Alisados", 30),
    ("pk_pack_ac", "Pack acido lactico bio premium largo", "Packs", 245),
    ("pk_pack_ke", "Pack keratina premium medio", "Packs", 220),
    ("pk_corte", "Corte senora", "Cortes", 20),
]


@pytest.fixture()
def salon(api_module, client):  # noqa: F811
    from backend import appstate, db, timeutils

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
    try:
        yield "demo"
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM services WHERE cliente_id='demo' AND slug LIKE 'pk_%'")
            conexion.commit()
        with appstate.state_lock:
            appstate.intent_cache.clear()


def test_las_tecnicas_salen_del_catalogo(salon):
    from backend import catalog_pick

    tecnicas = catalog_pick._tecnicas_de_la_familia(salon, "alisados")
    assert "acido lactico" in tecnicas
    assert "keratina premium" in tecnicas


def test_preguntar_por_la_familia_ve_tambien_los_packs(salon, monkeypatch):
    """Es la diferencia entre "de 15 a 30 minutos" y la verdad.

    Con `preferir_packs` -como lo tiene el salon piloto-, preguntar por la familia
    tiene que llegar a los packs. Antes ni siquiera eran candidatos, asi que la
    preferencia no tenia nada que preferir.
    """
    from backend import catalog_pick

    monkeypatch.setattr(catalog_pick, "_packs_por_defecto", lambda _c: True)
    eleccion = catalog_pick.elegir(salon, {"familia": "alisados"})
    vistos = [catalog_pick._norm(n) for n in (eleccion.candidatos or [])]
    if eleccion.servicio:
        vistos.append(catalog_pick._norm(eleccion.servicio))
    assert any("pack" in n for n in vistos), (
        "el pack no se reconoce como alisado: se contesta con las aplicaciones "
        "sueltas y el tiempo sale tres veces mas corto de lo que es"
    )
    assert not any(n.startswith("acido lactico bio") for n in vistos), (
        "con packs preferidos no puede quedarse con la aplicacion suelta"
    )


def test_sin_preferir_packs_el_negocio_manda(salon, monkeypatch):
    """Quien no los prefiere sigue como siempre: el pack solo si lo nombra."""
    from backend import catalog_pick

    monkeypatch.setattr(catalog_pick, "_packs_por_defecto", lambda _c: False)
    eleccion = catalog_pick.elegir(salon, {"familia": "alisados"})
    vistos = [catalog_pick._norm(n) for n in (eleccion.candidatos or [])]
    if eleccion.servicio:
        vistos.append(catalog_pick._norm(eleccion.servicio))
    assert vistos and not any(n.startswith("pack") for n in vistos)


def test_un_corte_no_se_cuela_entre_los_alisados(salon):
    """La otra mitad: si esto arrastrara medio catalogo, el rango no diria nada."""
    from backend import catalog_pick

    eleccion = catalog_pick.elegir(salon, {"familia": "alisados"})
    nombres = [catalog_pick._norm(n) for n in eleccion.candidatos]
    assert not any("corte" in n for n in nombres)


def test_sin_familia_no_arrastra_nada(salon):
    """Sin familia ni tecnica no hay candidatos: no se elige por deduccion."""
    from backend import catalog_pick

    assert catalog_pick._tecnicas_de_la_familia(salon, "") == []
