# -*- coding: utf-8 -*-
"""Una regla de orientación escrita como la escribe el negocio tiene que aplicarse.

POR QUE EXISTE
--------------
13-sep-2026, preparando la regla que Alicia confirmó: a quien no sabe qué alisado
quiere se le ofrece la cita de diagnóstico. En el portal la escribiría así, con la
familia «alisado». Y NO se habría aplicado nunca: para «Keratina premium largo» el
detector de familias devuelve `keratina` (la primera palabra del servicio), no
`alisados`, que es su categoría en el catálogo.

La regla parecería bien puesta y no haría nada, en silencio. Es de las cosas que
hacen desconfiar del producto.

Las reglas de PRECIO ya lo resolvían buscando también en la categoría del servicio
(`booking._categoria_del_servicio`). La de orientación no. Aquí se vigila que las
dos casen igual.
"""
from __future__ import annotations

import uuid

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

CID = "demo"


@pytest.fixture
def catalogo_con_alisados(api_module, monkeypatch):  # noqa: F811
    """Un servicio de la categoría Alisados cuyo nombre NO dice «alisado»."""
    from backend import db, intents, rules

    monkeypatch.setattr(intents, "config_enabled", lambda cliente_id, config=None: True)
    sufijo = uuid.uuid4().hex[:6]
    slugs = ["keratina_prueba_%s" % sufijo, "corte_prueba_%s" % sufijo]
    ahora = "2026-01-01T00:00:00Z"
    with db._get_db_connection() as cx:
        cx.execute(
            "INSERT INTO services (cliente_id, slug, name, category, duration_minutes,"
            " price_cents, is_active, created_at, updated_at) VALUES (?,?,?,?,?,?,1,?,?)",
            (CID, slugs[0], "Keratina premium largo %s" % sufijo, "Alisados", 180, 0, ahora, ahora))
        cx.execute(
            "INSERT INTO services (cliente_id, slug, name, category, duration_minutes,"
            " price_cents, is_active, created_at, updated_at) VALUES (?,?,?,?,?,?,1,?,?)",
            (CID, slugs[1], "Corte prueba %s" % sufijo, "Cortes", 30, 0, ahora, ahora))
        cx.commit()
    regla = rules.guardar(
        CID, nombre="Alisado: no sabe cuál", intenciones=["orientacion"],
        familias=["alisado"], accion="ofrecer_cita",
        texto="Lo vemos en la cita de diagnóstico.", prioridad=15)
    yield sufijo
    with db._get_db_connection() as cx:
        cx.execute("DELETE FROM services WHERE cliente_id = ? AND slug IN (?, ?)",
                   (CID, slugs[0], slugs[1]))
        cx.execute("DELETE FROM business_rules WHERE id = ?", (regla["id"],))
        cx.commit()


def test_la_regla_escrita_alisado_casa_con_la_keratina(catalogo_con_alisados):
    """El caso de Alicia: la escribe «alisado» y la clienta duda con una keratina."""
    from backend import booking

    sufijo = catalogo_con_alisados
    regla = booking.regla_de_orientacion_para(CID, "Keratina premium largo %s" % sufijo)

    assert regla.get("accion") == "ofrecer_cita", (
        "la regla de orientación escrita con la familia del negocio no se aplica: "
        "el asistente seguiría preguntando qué técnica quiere")


def test_no_se_aplica_a_lo_que_no_es_de_esa_familia(catalogo_con_alisados):
    """Casar por categoría no puede volverla una regla para todo."""
    from backend import booking

    sufijo = catalogo_con_alisados
    assert booking.regla_de_orientacion_para(CID, "Corte prueba %s" % sufijo) == {}


def test_orientacion_y_precio_casan_igual(catalogo_con_alisados):
    """La misma familia no puede significar dos cosas según qué regla se mire."""
    from backend import booking, rules

    sufijo = catalogo_con_alisados
    precio = rules.guardar(
        CID, nombre="Alisado: precio con foto", intenciones=["precio"],
        familias=["alisado"], accion="pedir_foto", texto="Mándanos una foto.", prioridad=10)
    try:
        servicio = "Keratina premium largo %s" % sufijo
        assert booking.regla_de_precio_para(CID, servicio).get("accion") == "pedir_foto"
        assert booking.regla_de_orientacion_para(CID, servicio).get("accion") == "ofrecer_cita"
    finally:
        from backend import db

        with db._get_db_connection() as cx:
            cx.execute("DELETE FROM business_rules WHERE id = ?", (precio["id"],))
            cx.commit()
