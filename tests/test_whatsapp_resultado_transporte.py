"""La aceptación HTTP con identidad no equivale a entrega al teléfono."""
import asyncio

import httpx
import pytest


@pytest.fixture
def transporte(api_module, monkeypatch):
    from backend import messaging
    respuestas, llamadas = [], []
    class Cliente:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kw):
            llamadas.append(kw["json"])
            resultado = respuestas.pop(0)
            if isinstance(resultado, Exception):
                raise resultado
            return resultado
    monkeypatch.setattr(messaging, "_whatsapp_access_token_for_client", lambda *a: "token-sintetico")
    monkeypatch.setattr(messaging.httpx, "AsyncClient", Cliente)
    return respuestas, llamadas


@pytest.mark.parametrize("status,body", [(200, {}), (503, {"error": {"code": 2, "message": "Unavailable"}})])
def test_respuesta_ambigua_no_es_exito_ni_false_que_dispare_fallback(transporte, status, body):
    from backend import messaging
    respuestas, llamadas = transporte
    respuestas.append(httpx.Response(status, json=body))
    with pytest.raises(RuntimeError):
        asyncio.run(messaging._send_whatsapp_payload(cliente_id="demo", phone_number_id="PN",
            payload={"messaging_product": "whatsapp", "to": "34600000000", "type": "text"}))
    assert len(llamadas) == 1


def test_texto_no_sigue_enviando_fragmentos_tras_rechazo(transporte):
    from backend import messaging
    respuestas, llamadas = transporte
    respuestas.extend([httpx.Response(400, json={"error": {"code": 100, "message": "Invalid parameter"}})] * 4)
    resultado = asyncio.run(messaging._send_whatsapp_text(cliente_id="demo", phone_number_id="PN",
        to_number="34600000000", text="palabra " * 1200))
    assert resultado is False
    assert len(llamadas) == 1


def _aceptacion(message_id="wamid.sintetico"):
    return httpx.Response(200, json={"messaging_product": "whatsapp",
        "contacts": [{"input": "34600000000", "wa_id": "34600000000"}],
        "messages": [{"id": message_id}]})


@pytest.mark.parametrize("emisor", ["payload", "text", "buttons", "cta_url", "list"])
def test_todos_los_builders_comparten_transporte_y_conservan_id(transporte, emisor):
    from backend import messaging
    respuestas, llamadas = transporte
    respuestas.append(_aceptacion())
    campos = {
        "payload": {"payload": {"messaging_product": "whatsapp", "to": "34600000000", "type": "template"}},
        "text": {"to_number": "34600000000", "text": "Hola"},
        "buttons": {"to_number": "34600000000", "body": "Hola", "buttons": [("id", "Sí")]},
        "cta_url": {"to_number": "34600000000", "body": "Hola", "button_label": "Ver", "url": "https://example.invalid"},
        "list": {"to_number": "34600000000", "body": "Hola", "button_text": "Ver", "sections": []},
    }
    resultado = asyncio.run(getattr(messaging, "_send_whatsapp_" + emisor)(
        cliente_id="demo", phone_number_id="PN", detailed=True, **campos[emisor]))
    assert resultado.estado == "aceptado"
    assert resultado.provider_message_id == "wamid.sintetico"
    assert resultado.message_ids == ("wamid.sintetico",)
    assert len(llamadas) == 1


@pytest.mark.parametrize("respuesta", [
    httpx.Response(200, json={}),
    httpx.Response(200, json={"messages": [{"id": "wamid.x"}], "error": {"code": 100, "message": "Error"}}),
    httpx.Response(200, json={"messages": [{"id": "wamid.x"}], "error": {}}),
    httpx.Response(200, json={"messages": [{"id": 123}]}),
    httpx.Response(200, json={"messages": [{"id": ""}]}),
    httpx.Response(200, json={"messages": [{"id": "uno"}, {"id": "dos"}]}),
    httpx.Response(200, content=b"no es JSON"),
    httpx.Response(400, content=b"proxy error"),
    httpx.Response(408, json={"error": {"code": 2, "message": "Timeout"}}),
    httpx.Response(500, json={"error": {"code": 2, "message": "Transient"}}),
    httpx.Response(502, content=b"gateway"),
    httpx.ReadTimeout("respuesta perdida"),
    httpx.WriteTimeout("escritura parcial"),
    httpx.RemoteProtocolError("conexion perdida"),
])
def test_resultado_ambiguo_detallado_no_permite_fallback(transporte, respuesta):
    from backend import messaging
    respuestas, llamadas = transporte
    respuestas.append(respuesta)
    resultado = asyncio.run(messaging._send_whatsapp_buttons(cliente_id="demo", phone_number_id="PN",
        to_number="34600000000", body="¿Vienes?", buttons=[("id", "Sí")], detailed=True))
    assert resultado.estado == "desconocido"
    assert not resultado.provider_message_id
    assert len(llamadas) == 1
    with pytest.raises(TypeError):
        bool(resultado)


def test_rechazo_explicito_conserva_error_y_legacy_false(transporte):
    from backend import messaging
    respuestas, llamadas = transporte
    rechazo = httpx.Response(400, json={"error": {"code": 131009, "message": "Parameter value is not valid"}})
    respuestas.extend([rechazo, rechazo])
    campos = dict(cliente_id="demo", phone_number_id="PN",
        payload={"messaging_product": "whatsapp", "to": "34600000000", "type": "text"})
    resultado = asyncio.run(messaging._send_whatsapp_payload(detailed=True, **campos))
    assert resultado.estado == "rechazado"
    assert resultado.error_code == "131009"
    assert resultado.http_status == 400
    assert asyncio.run(messaging._send_whatsapp_payload(**campos)) is False


def test_legacy_aceptado_sigue_siendo_bool_true(transporte):
    from backend import messaging
    respuestas, llamadas = transporte
    respuestas.append(_aceptacion())
    assert asyncio.run(messaging._send_whatsapp_text(cliente_id="demo", phone_number_id="PN",
        to_number="34600000000", text="Hola")) is True


def test_sin_token_es_omitido_sin_ningun_post(transporte, monkeypatch):
    from backend import messaging
    _, llamadas = transporte
    monkeypatch.setattr(messaging, "_whatsapp_access_token_for_client", lambda *a: "")
    resultado = asyncio.run(messaging._send_whatsapp_text(cliente_id="demo", phone_number_id="PN",
        to_number="34600000000", text="Hola", detailed=True))
    assert resultado.estado == "omitido"
    assert llamadas == []


@pytest.mark.parametrize("fallo", [httpx.ReadTimeout("perdida"),
    httpx.Response(400, json={"error": {"code": 100, "message": "Bad request"}})])
def test_fragmento_aceptado_se_conserva_si_el_siguiente_falla(transporte, fallo):
    from backend import messaging
    respuestas, llamadas = transporte
    respuestas.extend([_aceptacion(), fallo, _aceptacion("wamid.no-debe-enviarse")])
    resultado = asyncio.run(messaging._send_whatsapp_text(cliente_id="demo", phone_number_id="PN",
        to_number="34600000000", text="palabra " * 1200, detailed=True))
    assert resultado.estado == "desconocido"
    assert resultado.message_ids == ("wamid.sintetico",)
    assert len(llamadas) == 2


def test_legacy_timeout_no_ejecuta_fallback(transporte):
    from backend import messaging
    respuestas, llamadas = transporte
    respuestas.extend([httpx.ReadTimeout("perdida"), _aceptacion("wamid.duplicado")])
    async def flujo():
        if not await messaging._send_whatsapp_buttons(cliente_id="demo", phone_number_id="PN",
                to_number="34600000000", body="¿Vienes?", buttons=[("id", "Sí")]):
            await messaging._send_whatsapp_text(cliente_id="demo", phone_number_id="PN",
                to_number="34600000000", text="¿Vienes?")
    with pytest.raises(messaging.WhatsAppDeliveryUnknown) as error:
        asyncio.run(flujo())
    assert error.value.resultado.estado == "desconocido"
    assert len(llamadas) == 1


def test_fallo_al_cerrar_cliente_no_borra_aceptacion_recibida(transporte, monkeypatch):
    from backend import messaging
    respuestas, llamadas = transporte
    respuestas.append(_aceptacion())
    async def cerrar(*args):
        raise OSError("fallo local al cerrar cliente")
    monkeypatch.setattr(messaging.httpx.AsyncClient, "__aexit__", cerrar)
    resultado = asyncio.run(messaging._send_whatsapp_payload(cliente_id="demo", phone_number_id="PN",
        payload={"messaging_product": "whatsapp", "to": "34600000000", "type": "text"}, detailed=True))
    assert resultado.estado == "aceptado"
    assert resultado.provider_message_id == "wamid.sintetico"
    assert len(llamadas) == 1
