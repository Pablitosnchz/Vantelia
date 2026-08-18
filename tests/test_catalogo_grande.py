"""Un salon con 185 servicios tiene que poder venderlos todos.

Caso real (ago 2026): una peluqueria entrego su tabla con 164 servicios y 28
packs. Una lista de WhatsApp admite 10 filas y el selector cortaba con
`services[:10]`, asi que el cliente no podia elegir el 90% del catalogo.

Ahora, cuando no cabe, se pregunta la categoria primero y se pagina dentro. Un
negocio con pocos servicios no nota ningun cambio.
"""
from __future__ import annotations

import inspect

from test_booking_exhaustive import api_module  # noqa: F401


def _servicios(n, categorias=("Color", "Cortes", "Peinados")):
    return [
        {"id": "svc%d" % i, "nombre": "Servicio %d" % i,
         "category": categorias[i % len(categorias)] if categorias else "",
         "duration_minutes": 30, "price_label": "20 €", "descripcion": ""}
        for i in range(n)
    ]


def test_las_categorias_salen_del_catalogo(api_module):
    from backend import whatsapp

    cats = whatsapp._wa_service_categories(_servicios(9))
    assert cats == ["Color", "Cortes", "Peinados"]
    # Sin categorias no se inventa ninguna.
    assert whatsapp._wa_service_categories(_servicios(3, categorias=None)) == []


def test_con_pocos_servicios_no_se_pregunta_categoria(api_module, monkeypatch):
    """El negocio pequeno tiene que seguir viendo la lista de siempre."""
    from backend import booking, messaging, whatsapp

    enviado = {}

    async def falso_list(**kwargs):
        enviado.update(kwargs)
        return True

    monkeypatch.setattr(booking, "_public_services_for_booking", lambda *a, **k: _servicios(6))
    monkeypatch.setattr(messaging, "_send_whatsapp_list", falso_list)
    import asyncio

    asyncio.run(whatsapp._wa_send_service_picker(
        cliente_id="demo", phone_number_id="1", to_number="34600"))
    filas = enviado["sections"][0]["rows"]
    assert len(filas) == 6
    assert all(f["id"].startswith("svc_") for f in filas)


def test_con_catalogo_grande_se_pregunta_la_categoria(api_module, monkeypatch):
    from backend import booking, messaging, whatsapp

    enviado = {}

    async def falso_list(**kwargs):
        enviado.update(kwargs)
        return True

    monkeypatch.setattr(booking, "_public_services_for_booking", lambda *a, **k: _servicios(185))
    monkeypatch.setattr(messaging, "_send_whatsapp_list", falso_list)
    import asyncio

    asyncio.run(whatsapp._wa_send_service_picker(
        cliente_id="demo", phone_number_id="1", to_number="34600"))
    filas = enviado["sections"][0]["rows"]
    assert all(f["id"].startswith("cat_") for f in filas)
    assert len(filas) == 3  # las tres categorias del catalogo
    assert "categorias" in enviado["button_text"].lower()


def test_dentro_de_una_categoria_se_pagina(api_module, monkeypatch):
    """Nunca mas de 10 filas, y la ultima deja seguir viendo."""
    from backend import booking, messaging, whatsapp

    enviado = {}

    async def falso_list(**kwargs):
        enviado.update(kwargs)
        return True

    monkeypatch.setattr(booking, "_public_services_for_booking", lambda *a, **k: _servicios(185))
    monkeypatch.setattr(messaging, "_send_whatsapp_list", falso_list)
    import asyncio

    asyncio.run(whatsapp._wa_send_service_picker(
        cliente_id="demo", phone_number_id="1", to_number="34600", categoria="Color"))
    filas = enviado["sections"][0]["rows"]
    assert len(filas) <= 10
    assert filas[-1]["id"].startswith("svcmas_")
    # La segunda pagina continua donde acabo la primera.
    asyncio.run(whatsapp._wa_send_service_picker(
        cliente_id="demo", phone_number_id="1", to_number="34600",
        categoria="Color", pagina=1))
    segundas = enviado["sections"][0]["rows"]
    assert segundas[0]["id"] != filas[0]["id"]


def test_el_servicio_se_identifica_por_su_id_no_por_la_posicion(api_module):
    """Con filtro por categoria y paginacion, la posicion ya no vale: elegiria otro."""
    from backend import whatsapp

    picker = inspect.getsource(whatsapp._wa_send_service_picker)
    assert '"svc_%s" % (svc.get("id")' in picker

    manejo = inspect.getsource(whatsapp._handle_whatsapp_message)
    assert 'if str(svc.get("id") or svc.get("slug") or "") == referencia:' in manejo
    # Y los listados antiguos (por posicion) siguen funcionando.
    assert "Compat: listados antiguos" in manejo


def test_la_fila_dice_duracion_y_precio(api_module):
    """En una lista de 185, elegir a ciegas por el nombre no vale."""
    from backend import whatsapp

    detalle = whatsapp._wa_service_detail(
        {"duration_minutes": 90, "price_label": "70 €", "descripcion": "con papel de plata"})
    assert "90 min" in detalle and "70" in detalle
    assert len(detalle) <= 72
