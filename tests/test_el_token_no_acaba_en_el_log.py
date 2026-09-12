# -*- coding: utf-8 -*-
"""Un token en un log es un token filtrado.

POR QUE EXISTE
--------------
12-sep-2026. Consultando a Meta el estado de la plantilla de recordatorio salio
esto en los logs del VPS, en una linea, entero:

    INFO httpx HTTP Request: GET https://graph.facebook.com/v22.0/<waba>/
    message_templates?name=vantelia_recordatorio_cita&access_token=EAAimXEGITY8...

`httpx` registra la URL completa de cada peticion, asi que cualquier credencial
que viaje en la query string queda escrita en claro: la tiene quien entre al
servidor, quien abra un backup y quien lea un volcado. Y el token de WhatsApp de
un negocio permite escribir a sus clientas en su nombre.

Dos capas, porque una no llega:
  · El `access_token` va en la CABECERA (Meta acepta `Authorization: Bearer`).
  · Lo que Meta obliga a llevar en la URL de todas formas -`input_token` al
    inspeccionar un token, `client_secret` al canjear el code del alta- lo tapa un
    filtro enganchado al handler raiz, que cubre tambien a las librerias de
    terceros.
"""
from __future__ import annotations

import asyncio
import logging

from test_booking_exhaustive import api_module  # noqa: F401


class _RespuestaFalsa:
    status_code = 200
    content = b"{}"
    text = "{}"

    @staticmethod
    def json():
        return {"data": []}


class _ClienteFalso:
    """Se queda con lo que se le pidio, sin salir a la red."""

    ultimo: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None, headers=None):
        _ClienteFalso.ultimo = {"url": url, "params": dict(params or {}),
                                "headers": dict(headers or {})}
        return _RespuestaFalsa()

    async def post(self, url, data=None, headers=None, json=None):
        _ClienteFalso.ultimo = {"url": url, "data": dict(data or {}),
                                "headers": dict(headers or {})}
        return _RespuestaFalsa()


def test_el_token_viaja_en_la_cabecera_y_no_en_la_url(api_module, monkeypatch):  # noqa: F811
    import httpx

    from backend import wa_onboarding

    monkeypatch.setattr(httpx, "AsyncClient", _ClienteFalso)
    asyncio.run(wa_onboarding._graph_get(
        "waba_x/message_templates",
        {"name": "vantelia_recordatorio_cita", "access_token": "EAAsecreto123"},
    ))

    pedido = _ClienteFalso.ultimo
    assert "access_token" not in pedido["params"], "el token sigue viajando en la URL"
    assert "EAAsecreto123" not in str(pedido["url"])
    assert pedido["headers"].get("Authorization") == "Bearer EAAsecreto123"
    # El resto de la consulta no se pierde por el camino.
    assert pedido["params"].get("name") == "vantelia_recordatorio_cita"


def test_la_consulta_de_la_plantilla_pasa_por_ahi(api_module, monkeypatch):  # noqa: F811
    """El caso real que lo destapo: buscar la plantilla de un negocio."""
    import httpx

    from backend import wa_plantillas

    monkeypatch.setattr(httpx, "AsyncClient", _ClienteFalso)
    asyncio.run(wa_plantillas._buscar("waba_x", "EAAotrosecreto", "vantelia_recordatorio_cita"))

    pedido = _ClienteFalso.ultimo
    assert "EAAotrosecreto" not in str(pedido["url"])
    assert "access_token" not in pedido["params"]
    assert pedido["headers"].get("Authorization") == "Bearer EAAotrosecreto"


def test_el_filtro_tapa_lo_que_meta_obliga_a_llevar_en_la_url(api_module):  # noqa: F811
    """`input_token` y `client_secret` no se pueden mover: se tapan al escribir."""
    from backend import settings

    filtro = settings._SinSecretosEnElLog()
    registro = logging.LogRecord(
        "httpx", logging.INFO, __file__, 1,
        'HTTP Request: GET https://graph.facebook.com/v22.0/debug_token'
        '?input_token=EAAsecreto&access_token=EAAsecreto&client_secret=abc123 "200 OK"',
        (), None,
    )

    assert filtro.filter(registro) is True
    escrito = registro.getMessage()
    assert "EAAsecreto" not in escrito, "el token se sigue escribiendo en el log"
    assert "abc123" not in escrito, "el secreto de la app se sigue escribiendo"
    assert "[oculto]" in escrito
    # Lo que no es una credencial se conserva, o el log deja de servir.
    assert "debug_token" in escrito and "200 OK" in escrito


def test_el_filtro_esta_enchufado_al_handler(api_module):  # noqa: F811
    """Un filtro suelto no tapa nada: tiene que estar en el handler raiz.

    Se engancha al HANDLER y no al logger de Vantelia porque quien escribe la URL
    es `httpx`, que tiene el suyo propio.
    """
    from backend import settings

    handlers = logging.getLogger().handlers
    assert handlers, "no hay handler raiz donde enganchar el filtro"
    assert any(isinstance(f, settings._SinSecretosEnElLog)
               for h in handlers for f in h.filters), "el filtro no esta puesto"


def test_un_log_normal_no_se_toca(api_module):  # noqa: F811
    """Tapar de mas hace inservible el log: solo se tocan las credenciales."""
    from backend import settings

    filtro = settings._SinSecretosEnElLog()
    registro = logging.LogRecord(
        "vantelia", logging.INFO, __file__, 1,
        "cita R-1234 creada para el 2026-09-15 a las 10:00 (status_code=200)",
        (), None,
    )
    filtro.filter(registro)

    assert registro.getMessage() == (
        "cita R-1234 creada para el 2026-09-15 a las 10:00 (status_code=200)")
