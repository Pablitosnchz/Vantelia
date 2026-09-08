# -*- coding: utf-8 -*-
"""Un servicio desactivado no puede dejar la agenda "sin huecos".

POR QUE EXISTE
--------------
Visto en produccion el 8-sep-2026, con la captura de la duenya delante:

    ELLA: mañana
    IA:   Mañana no tengo huecos disponibles para el alisado, cariño.
          Pero puedo ofrecerte cita para el jueves 10 o el martes 15.

Ese dia la agenda estaba **entera libre**: cero citas y seis profesionales. Lo que
pasaba es que el salon tiene los alisados sueltos DESACTIVADOS -son los que llevan
el precio- y reservables solo los "Pack". Al preguntar por el servicio
desactivado, ningun profesional lo "ofrece" (solo se listan los activos) y la
disponibilidad salia vacia. El asistente no mentia: le daban cero huecos.

Es de los fallos caros: la clienta se va creyendo que el salon esta lleno.

Curiosidad util para entenderlo: un nombre INVENTADO ya caia bien -se ignora el
filtro y se dan los huecos del dia-. El que mordia era el que EXISTE pero no se
puede reservar.
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CID = "demo"


@pytest.fixture
def catalogo_con_desactivado(api_module):  # noqa: F811
    """Un servicio desactivado y su equivalente activo, como en el salon real."""
    from backend import db

    with db._get_db_connection() as cx:
        cols = [r[1] for r in cx.execute("PRAGMA table_info(services)")]
        campo = "name" if "name" in cols else "nombre"
        cx.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, %s, duration_minutes, "
            "price_cents, is_active, created_at, updated_at) "
            "VALUES (?,?,?,?,?,0,datetime('now'),datetime('now'))" % campo,
            (CID, "keratina_premium_largo", "Keratina premium largo", 140, 24000))
        cx.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, %s, duration_minutes, "
            "price_cents, is_active, created_at, updated_at) "
            "VALUES (?,?,?,?,?,1,datetime('now'),datetime('now'))" % campo,
            (CID, "pack_keratina_premium_largo", "Pack keratina premium largo", 140, 0))
        cx.commit()
    yield
    with db._get_db_connection() as cx:
        cx.execute("DELETE FROM services WHERE cliente_id=? AND slug IN (?,?)",
                   (CID, "keratina_premium_largo", "pack_keratina_premium_largo"))
        cx.commit()


def test_el_desactivado_se_traduce_al_que_si_se_reserva(api_module, catalogo_con_desactivado):  # noqa: F811
    from backend import agenda

    assert agenda._servicio_reservable(CID, "Keratina premium largo") == "Pack keratina premium largo"


def test_un_servicio_activo_se_deja_como_esta(api_module, catalogo_con_desactivado):  # noqa: F811
    from backend import agenda

    assert agenda._servicio_reservable(CID, "Pack keratina premium largo") == "Pack keratina premium largo"


def test_sin_servicio_no_se_toca_nada(api_module):  # noqa: F811
    from backend import agenda

    assert agenda._servicio_reservable(CID, "") == ""


def test_un_nombre_inventado_sigue_su_curso(api_module):  # noqa: F811
    """Ese caso ya funcionaba: se ignora el filtro y se dan los huecos del dia."""
    from backend import agenda

    assert agenda._servicio_reservable(CID, "Servicio inventado 123") == "Servicio inventado 123"


def test_sin_equivalente_activo_se_dan_los_huecos_del_dia(api_module):  # noqa: F811
    """Mejor ofrecer el dia entero que decirle que no hay nada."""
    from backend import db, agenda

    with db._get_db_connection() as cx:
        cols = [r[1] for r in cx.execute("PRAGMA table_info(services)")]
        campo = "name" if "name" in cols else "nombre"
        cx.execute(
            "INSERT OR REPLACE INTO services (cliente_id, slug, %s, duration_minutes, "
            "price_cents, is_active, created_at, updated_at) "
            "VALUES (?,?,?,?,?,0,datetime('now'),datetime('now'))" % campo,
            (CID, "servicio_retirado", "Servicio retirado", 60, 1000))
        cx.commit()
    try:
        assert agenda._servicio_reservable(CID, "Servicio retirado") == ""
    finally:
        with db._get_db_connection() as cx:
            cx.execute("DELETE FROM services WHERE cliente_id=? AND slug=?",
                       (CID, "servicio_retirado"))
            cx.commit()


def test_la_agenda_ya_no_sale_vacia_por_un_desactivado(api_module, catalogo_con_desactivado):  # noqa: F811
    """El fallo tal y como lo vio la duenya: dia libre y "no hay huecos"."""
    import datetime

    from backend import agenda, timeutils

    dia = (timeutils._utc_now().date() + datetime.timedelta(days=1)).isoformat()
    _, libres = asyncio.run(agenda._public_slot_sets_for_day(CID, dia, servicio="Keratina premium largo"))
    _, sin_filtro = asyncio.run(agenda._public_slot_sets_for_day(CID, dia))
    if sin_filtro:  # si ese dia el negocio abre
        assert libres, "un servicio desactivado dejaba el dia sin huecos"
