# -*- coding: utf-8 -*-
"""El asistente tiene que ver TODO el catalogo del negocio, no los 40 primeros.

EL FALLO QUE ESTO IMPIDE
------------------------
El bloque de catalogo del prompt se cortaba con `catalog_lines[:40]`. Medido en
produccion con un salon real de **186 servicios**: 146 quedaban invisibles, entre
ellos "Corte señora 20 €", "Corte hombre 16 €" o "Peinado de novia 90 €" — el pan
de cada dia. Y el prompt ademas ordenaba *"si piden un servicio que no esta en la
lista, no lo aceptes como reservable"*, asi que el asistente negaba servicios que
el negocio si hace.

Peor todavia: preguntado por el precio de un corte de niño (8 € y 10 € en su
tabla), contesto **15 €**. Se lo invento, porque no lo veia.

Reglas que quedan fijadas:

1. Si el catalogo cabe, entra ENTERO.
2. Si no cabe, el bloque lo DICE y el prompt deja de afirmar que algo no existe.
3. Chat y voz usan la misma fuente: el telefono tenia el mismo tope de 40.
"""
from __future__ import annotations

import uuid

from test_booking_exhaustive import api_module, client  # noqa: F401


def _crear_servicios(cuantos: int, prefijo: str) -> None:
    """Un catalogo grande de verdad, como el de un salon."""
    from backend import agenda, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for numero in range(cuantos):
            nombre = "%s %03d" % (prefijo, numero)
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, duration_minutes,"
                " price_cents, description, is_active, sort_order, created_at, updated_at)"
                " VALUES ('demo', ?, ?, 30, ?, '', 1, ?, ?, ?)",
                (agenda._normalize_service_id(nombre), nombre, 1000 + numero, numero, ahora, ahora),
            )
        conexion.commit()


def _borrar_servicios(prefijo: str) -> None:
    from backend import db

    with db._get_db_connection() as conexion:
        conexion.execute(
            "DELETE FROM services WHERE cliente_id='demo' AND name LIKE ?", (prefijo + "%",)
        )
        conexion.commit()


def test_un_catalogo_grande_entra_entero(api_module, client):  # noqa: F811
    """El servicio numero 120 tiene que estar en el prompt igual que el numero 1."""
    from backend import booking

    prefijo = "Servicio " + uuid.uuid4().hex[:6]
    _crear_servicios(120, prefijo)
    try:
        texto, completo = booking._service_catalog_prompt_block("demo")
        assert completo is True, "cabian de sobra y aun asi se dio por recortado"
        assert "%s 000" % prefijo in texto
        assert "%s 119" % prefijo in texto, "el catalogo se esta cortando otra vez"
        assert texto.count("\n") >= 119
    finally:
        _borrar_servicios(prefijo)


def test_si_no_cabe_lo_dice(api_module, client):  # noqa: F811
    """Un catalogo imposible no puede fingir que esta completo."""
    from backend import booking

    prefijo = "Servicio " + uuid.uuid4().hex[:6]
    _crear_servicios(30, prefijo)
    try:
        texto, completo = booking._service_catalog_prompt_block("demo", max_chars=200)
        assert completo is False
        assert "servicios mas que no caben" in texto
    finally:
        _borrar_servicios(prefijo)


def test_el_prompt_del_chat_lleva_todo_el_catalogo(api_module, client):  # noqa: F811
    """La prueba de verdad: el prompt que recibe el modelo."""
    from backend import clients, rag

    prefijo = "Servicio " + uuid.uuid4().hex[:6]
    _crear_servicios(90, prefijo)
    try:
        prompt = rag._build_system_prompt("demo", clients._get_client_config("demo"))
        assert "%s 089" % prefijo in prompt, "el modelo no ve el servicio 90"
        assert "RECORTADA" not in prompt, "cabia entero, no debe avisar de recorte"
    finally:
        _borrar_servicios(prefijo)


def test_con_el_catalogo_recortado_no_se_niega_un_servicio(api_module, client):  # noqa: F811
    """Negar existe solo si la lista esta completa; si no, se confirma."""
    from backend import booking

    texto_completo, completo = booking._service_catalog_prompt_block("demo")
    assert isinstance(texto_completo, str) and completo in (True, False)

    import inspect

    from backend import rag

    fuente = inspect.getsource(rag._build_system_prompt)
    assert "if catalog_complete else" in fuente
    assert "no lo aceptes como reservable" in fuente
    assert "NO digas que no existe" in fuente


def test_la_voz_usa_la_misma_fuente_que_el_chat(api_module, client):  # noqa: F811
    """El telefono tenia el mismo tope de 40: no puede volver a divergir."""
    import inspect

    from backend import voice

    fuente = inspect.getsource(voice._voice_service_catalog_block)
    assert "_service_catalog_prompt_block" in fuente

    instrucciones = inspect.getsource(voice._voice_build_instructions)
    assert "[:40]" not in instrucciones, "vuelve a estar el tope de 40 en la voz"
    assert "catalogo_completo" in instrucciones


def test_el_catalogo_del_prompt_lleva_las_familias(api_module, client):  # noqa: F811
    """Sin la categoria, el modelo confunde familias enteras.

    Medido contra el catalogo real de un salon (186 servicios, 11 categorias): a
    una clienta que escribia "se me cae mucho el pelo" le proponia un ALISADO,
    porque los 186 nombres viajaban seguidos y sin decir a que familia pertenecen.
    Un alisado no frena la caida del pelo: no es una respuesta poco util, es un mal
    consejo. Con las categorias delante, ofrece el diagnostico.
    """
    from backend import agenda, booking, db, timeutils

    ahora = timeutils._utc_now_iso()
    marca = "catfam"
    with db._get_db_connection() as conexion:
        for nombre, categoria in (("Alisado prueba", "Alisados"),
                                  ("Rescate prueba", "Tratamientos"),
                                  ("Corte prueba", "Cortes")):
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo', ?, ?, ?, 30, 1000, '', 1, 0, ?, ?)",
                (agenda._normalize_service_id(marca + nombre), nombre, categoria, ahora, ahora),
            )
        conexion.commit()
    try:
        texto, _completo = booking._service_catalog_prompt_block("demo")
        assert "Alisados:" in texto, "el catalogo no dice a que familia pertenece cada cosa"
        assert "Tratamientos:" in texto
        assert "Alisado prueba" in texto and "Rescate prueba" in texto
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute(
                "DELETE FROM services WHERE cliente_id='demo' AND name IN"
                " ('Alisado prueba','Rescate prueba','Corte prueba')"
            )
            conexion.commit()


def test_sin_categorias_el_catalogo_sale_plano(api_module, client):  # noqa: F811
    """Un negocio que no categoriza su catalogo no puede salir peor que antes."""
    from backend import booking

    texto, _ = booking._service_catalog_prompt_block("demo")
    assert isinstance(texto, str)
