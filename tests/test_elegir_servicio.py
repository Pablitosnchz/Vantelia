# -*- coding: utf-8 -*-
"""Elegir el servicio es cosa del CODIGO, y por eso se puede probar.

La primera version le pedia al modelo entender Y decidir. Decidir se le daba mal y
de forma distinta en cada ejecucion: con el mismo mensaje unas veces preguntaba la
tecnica y otras la elegia sola (tres tipos de alisado, de 240 EUR a 260 EUR), unas
veces entendia "por los hombros" y otras volvia a preguntar el largo. Y una vez
llego a decir "te he reservado" cuando aun faltaba el dia.

Ahora el modelo solo EXTRAE lo que la clienta ha dicho y decide `catalog_pick`
mirando el catalogo. Estos tests no llaman a ningun modelo: con los mismos datos,
la misma decision, siempre.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CATALOGO = [
    # (nombre, categoria, minutos)
    ("Keratina premium corto", "Alisados", 15),
    ("Keratina premium medio", "Alisados", 30),
    ("Keratina premium largo", "Alisados", 30),
    ("Acido lactico bio premium-corto", "Alisados", 30),
    ("Acido lactico bio premium-medio", "Alisados", 30),
    ("Acido lactico bio premium-largo", "Alisados", 30),
    ("Mechas corto", "Trabajos de color", 60),
    ("Mechas medio", "Trabajos de color", 75),
    ("Mechas media cabeza medio", "Trabajos de color", 50),
    ("Mechas balayage largo", "Trabajos de color", 90),
    ("Pack mechas y corte medio", "Packs", 120),
    ("Corte senora", "Cortes", 20),
    ("Corte hombre", "Cortes", 30),
    ("Corte nino de 0 a 7", "Cortes", 15),
    ("Corte de nino de 8 a 12", "Cortes", 20),
]


@pytest.fixture
def catalogo(api_module, client):  # noqa: F811
    """Un catalogo con las trampas del real: variantes por talla y por tecnica."""
    from backend import agenda, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for nombre, categoria, minutos in CATALOGO:
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo', ?, ?, ?, ?, 1000, '', 1, 0, ?, ?)",
                (agenda._normalize_service_id(nombre), nombre, categoria, minutos, ahora, ahora),
            )
        conexion.commit()
    yield
    with db._get_db_connection() as conexion:
        conexion.execute(
            "DELETE FROM services WHERE cliente_id='demo' AND name IN (%s)"
            % ",".join("?" * len(CATALOGO)),
            [n for n, _c, _m in CATALOGO],
        )
        conexion.commit()


# ─── Entender el largo como lo dice una persona ────────────────────────────

@pytest.mark.parametrize("dicho,esperada", [
    ("lo tengo por los hombros", "medio"),
    ("media melena", "medio"),
    ("lo llevo muy corto", "muy corto"),
    ("por la cintura", "extra largo"),
    ("me llega por la barbilla", "corto"),
    ("no se", ""),
])
def test_el_largo_como_lo_dice_la_clienta(api_module, dicho, esperada):  # noqa: F811
    from backend import catalog_pick

    assert catalog_pick.talla_de(dicho) == esperada


def test_media_a_secas_no_es_una_talla(api_module):  # noqa: F811
    """Casaba dentro de "Mechas MEDIA cabeza" y elegia ese servicio."""
    from backend import catalog_pick

    assert catalog_pick.talla_de("mechas media cabeza") == ""


def test_el_nombre_sin_la_talla(api_module):  # noqa: F811
    """Es lo que distingue una tecnica de otra."""
    from backend import catalog_pick

    assert catalog_pick.tecnica_de("Keratina premium largo") == "keratina premium"
    assert catalog_pick.tecnica_de("Acido lactico bio premium-extra largo") == (
        "acido lactico bio premium"
    )
    # Y no puede quedar una conjuncion colgando.
    assert not catalog_pick.tecnica_de("Acido lactico chico o corto").endswith(" o")


# ─── Decidir ───────────────────────────────────────────────────────────────

def test_con_tecnica_y_talla_elige(catalogo, api_module):  # noqa: F811
    from backend import catalog_pick

    eleccion = catalog_pick.elegir("demo", {
        "familia": "alisado", "tecnica": "keratina", "talla": "corto",
    })
    assert eleccion.servicio == "Keratina premium corto"


def test_sin_tecnica_pregunta_cual_aunque_sepa_el_largo(catalogo, api_module):  # noqa: F811
    """Tres tipos de alisado son tratamientos distintos, no tallas: elige ella."""
    from backend import catalog_pick

    eleccion = catalog_pick.elegir("demo", {"familia": "alisado", "talla": "medio"})
    assert eleccion.falta == "tecnica", eleccion
    assert any("keratina" in o.lower() for o in eleccion.opciones)
    assert any("acido" in o.lower() for o in eleccion.opciones)
    assert "asesoramos" in catalog_pick.pregunta_para(eleccion)


def test_nunca_repregunta_un_dato_ya_dado(catalogo, api_module):  # noqa: F811
    """El fallo que traia el modelo: preguntar el largo que le acaban de decir."""
    from backend import catalog_pick

    con_talla = catalog_pick.elegir("demo", {
        "familia": "alisado", "tecnica": "keratina", "talla": "medio",
    })
    assert con_talla.falta != "talla", "le esta repreguntando el largo"

    con_tecnica = catalog_pick.elegir("demo", {"familia": "alisado", "tecnica": "keratina"})
    assert con_tecnica.falta != "tecnica", "le esta repreguntando la tecnica"


def test_sin_talla_pregunta_el_largo(catalogo, api_module):  # noqa: F811
    from backend import catalog_pick

    eleccion = catalog_pick.elegir("demo", {"familia": "alisado", "tecnica": "keratina"})
    assert eleccion.falta == "talla"
    assert "de largo" in catalog_pick.pregunta_para(eleccion)


def test_un_pack_no_es_lo_que_pide_quien_dice_mechas(catalogo, api_module):  # noqa: F811
    from backend import catalog_pick

    eleccion = catalog_pick.elegir("demo", {"familia": "mechas", "talla": "medio"})
    assert eleccion.servicio == "Mechas medio", eleccion


def test_la_tecnica_nombrada_manda(catalogo, api_module):  # noqa: F811
    """Quien dice "balayage" no puede acabar en un servicio que no lo lleva."""
    from backend import catalog_pick

    eleccion = catalog_pick.elegir("demo", {
        "familia": "mechas", "tecnica": "balayage", "talla": "largo",
    })
    assert eleccion.servicio == "Mechas balayage largo"


def test_para_quien_usa_las_palabras_del_catalogo(catalogo, api_module):  # noqa: F811
    """La clienta dice "mujer"; el catalogo pone "señora"."""
    from backend import catalog_pick

    assert catalog_pick.elegir("demo", {
        "familia": "corte", "para_quien": "mujer",
    }).servicio == "Corte senora"
    assert catalog_pick.elegir("demo", {
        "familia": "corte", "para_quien": "hombre",
    }).servicio == "Corte hombre"


@pytest.mark.parametrize("edad,esperado", [
    (5, "Corte nino de 0 a 7"),
    (10, "Corte de nino de 8 a 12"),
])
def test_la_edad_decide_sola(catalogo, api_module, edad, esperado):  # noqa: F811
    """"un corte para mi hijo de 5 años" no necesita mas preguntas."""
    from backend import catalog_pick

    eleccion = catalog_pick.elegir("demo", {
        "familia": "corte", "para_quien": "nino", "edad": edad,
    })
    assert eleccion.servicio == esperado


def test_lo_que_no_existe_no_se_inventa(catalogo, api_module):  # noqa: F811
    from backend import catalog_pick

    eleccion = catalog_pick.elegir("demo", {"familia": "manicura"})
    assert eleccion.servicio == "" and eleccion.falta == "nada"


def test_la_misma_peticion_da_siempre_lo_mismo(catalogo, api_module):  # noqa: F811
    """La razon de sacarle la decision al modelo."""
    from backend import catalog_pick

    datos = {"familia": "alisado", "talla": "medio"}
    resultados = {
        (catalog_pick.elegir("demo", dict(datos)).servicio,
         catalog_pick.elegir("demo", dict(datos)).falta)
        for _ in range(5)
    }
    assert len(resultados) == 1, "la decision cambia entre ejecuciones: %r" % resultados
