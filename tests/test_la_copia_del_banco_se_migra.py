# -*- coding: utf-8 -*-
"""La copia sobre la que se mide tiene que llevar el esquema del codigo medido.

POR QUE EXISTE
--------------
13-sep-2026. El banco de casos se lanzo contra una copia de produccion para medir
el candidato de la consolidacion y dio **0 de 41**: las cuarenta y una
conversaciones reventaron con `OperationalError: no such table:
conversation_states`. Parecia un producto roto de arriba abajo.

No lo estaba. La copia sale de PRODUCCION, que va por detras del candidato: el
candidato crea esa tabla y la copia no la tenia. El instrumento estaba midiendo un
error de esquema en vez de medir al asistente.

Consecuencias que tuvo, y por las que esto se vigila:
  · Una medida en cero se lee como "el producto esta roto" y manda a arreglar lo
    que no falla. Es la trampa del instrumento, otra vez.
  · El humo del DESPLIEGUE trabaja igual, sobre una copia: el candidato no se
    habria podido desplegar nunca, con el humo en rojo por una tabla que en el
    servidor se crea sola al arrancar (`backend/main.py` llama a
    `db._init_database()`; los instrumentos no importan `main`).
"""
from __future__ import annotations

import pathlib
import sqlite3

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


def _copia_vieja(tmp_path: pathlib.Path) -> str:
    """Produccion ANTES del candidato: el esquema entero MENOS la tabla nueva.

    Se genera con el propio migrador y se le quita la tabla, en vez de escribir a
    mano cuatro columnas: asi el escenario es el de verdad -una base completa que
    se ha quedado una version por detras- y no una base de juguete.
    """
    from backend import db, settings

    origen = tmp_path / "produccion_vieja.db"
    anterior = settings.DB_PATH
    settings.DB_PATH = origen
    try:
        db._init_database()
    finally:
        settings.DB_PATH = anterior
    conexion = sqlite3.connect(str(origen))
    with conexion:
        conexion.execute("DROP TABLE IF EXISTS conversation_states")
        # Un dato cualquiera para comprobar que migrar no vacia lo copiado.
        conexion.execute("CREATE TABLE marca_de_la_copia (que TEXT)")
        conexion.execute("INSERT INTO marca_de_la_copia VALUES ('agenda del negocio')")
    conexion.close()
    return str(origen)


def _tablas(ruta: str):
    conexion = sqlite3.connect(ruta)
    try:
        return {f[0] for f in conexion.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conexion.close()


@pytest.fixture
def db_path_restaurado(api_module):  # noqa: F811
    """`preparar_copia` reapunta `settings.DB_PATH` global: hay que devolverlo."""
    from backend import settings

    anterior = settings.DB_PATH
    yield
    settings.DB_PATH = anterior


def test_la_copia_recibe_el_esquema_del_codigo_que_se_mide(tmp_path, db_path_restaurado):
    """Sin esto, medir un candidato con una tabla nueva da cero y miente."""
    from evals import arnes

    origen = _copia_vieja(tmp_path)
    destino = str(tmp_path / "copia.db")
    assert "conversation_states" not in _tablas(origen), "la base de partida ya la tenia"

    arnes.preparar_copia(origen, destino)

    tablas = _tablas(destino)
    assert "conversation_states" in tablas, (
        "la copia no lleva el esquema del codigo medido: el banco medira errores "
        "de esquema y el humo del despliegue se caera por lo mismo")
    # Y lo que traia la copia sigue ahi: migrar no puede vaciar la agenda copiada.
    conexion = sqlite3.connect(destino)
    try:
        assert list(conexion.execute("SELECT COUNT(*) FROM marca_de_la_copia"))[0][0] == 1
    finally:
        conexion.close()


def test_el_banco_migra_su_copia_igual_que_el_humo(tmp_path, db_path_restaurado):
    """Los dos instrumentos comparten la razon, asi que comparten el arreglo."""
    import importlib.util

    from evals import arnes

    ruta = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "evaluar_asistente.py"
    especificacion = importlib.util.spec_from_file_location("evaluar_asistente_medida", ruta)
    banco = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(banco)

    origen = _copia_vieja(tmp_path)
    destino = str(tmp_path / "copia_banco.db")
    banco._preparar_copia(origen, destino)

    assert "conversation_states" in _tablas(destino)
    assert hasattr(arnes, "_migrar_la_copia"), "el arreglo tiene que vivir en un solo sitio"
