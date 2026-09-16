# -*- coding: utf-8 -*-
"""Lo que devuelve el modelo tiene la forma esperada antes de usarse.

POR QUE EXISTE
--------------
Bloque B de COMPARATIVA_IA_Y_PLAN_DE_BAJO_COSTE.md (16-sep-2026). Un JSON válido no garantiza
la forma: el parser de herramientas del agente hacía `argumentos.get` sobre lo que devolviera
`json.loads` (una lista o `null` tumbaba el turno entero y la clienta se quedaba sin respuesta
del asistente), y `intents` hacía `datos.get` fuera de su `try`, y convertía `NaN` en confianza
1.0 (`min(1.0, nan)` devuelve 1.0). Validación local, sin otra llamada al modelo.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


def _modelo_falso(monkeypatch, respuestas):
    """Cada llamada devuelve la siguiente respuesta: texto (str) o una tool con argumentos crudos."""
    llamadas = []

    def crear(**kwargs):
        llamadas.append(kwargs)
        siguiente = respuestas[min(len(llamadas) - 1, len(respuestas) - 1)]
        if isinstance(siguiente, tuple):
            nombre, crudo = siguiente
            llamada = types.SimpleNamespace(id="t%d" % len(llamadas), function=types.SimpleNamespace(
                name=nombre, arguments=crudo))
            mensaje = types.SimpleNamespace(content="", tool_calls=[llamada])
        else:
            mensaje = types.SimpleNamespace(content=siguiente, tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=mensaje)], usage=None)

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=crear)))
    monkeypatch.setitem(sys.modules, "openai", modulo)
    return llamadas


def _turno_del_agente(monkeypatch, crudo, nombre="buscar_servicio"):
    from backend import agent, reserva, settings

    estado = reserva.Estado()
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [])
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    ejecutadas = []

    async def ejecutar(cliente_id, herramienta, argumentos, **kwargs):
        ejecutadas.append((herramienta, argumentos))
        return {"ok": True}

    monkeypatch.setattr(agent, "_ejecutar", ejecutar)
    llamadas = _modelo_falso(monkeypatch, [(nombre, crudo), "¿Qué te gustaría hacerte?"])
    texto, _ = asyncio.run(agent.responder("demo", "hola", session_id="contratos-json", telefono="34600970080"))
    vistos = [str(m.get("content") or "") for k in llamadas for m in (k.get("messages") or [])
              if isinstance(m, dict) and m.get("role") == "tool"]
    return texto, ejecutadas, vistos


@pytest.mark.parametrize("crudo", ["[]", "null", '"mechas"', '{"descripcion": ["mechas"]}',
                                   '{"descripcion": NaN}', '{"descripcion": {"a": 1}}', "{no es json"])
def test_argumentos_con_otra_forma_no_se_ejecutan_ni_tumban_el_turno(api_module, monkeypatch, crudo):  # noqa: F811
    texto, ejecutadas, vistos = _turno_del_agente(monkeypatch, crudo)
    assert texto == "¿Qué te gustaría hacerte?", "el turno se ha caído: %r" % texto
    assert not ejecutadas, "se ejecutó una herramienta con argumentos inválidos: %r" % ejecutadas
    assert any('"ok": false' in v for v in vistos), vistos


@pytest.mark.parametrize("crudo", ['{"descripcion": "mechas"}', '{"descripcion": "mechas", "extra": 1}'])
def test_argumentos_correctos_se_ejecutan_como_siempre(api_module, monkeypatch, crudo):  # noqa: F811
    texto, ejecutadas, _ = _turno_del_agente(monkeypatch, crudo)
    assert ejecutadas and ejecutadas[0][0] == "buscar_servicio", ejecutadas
    assert texto == "¿Qué te gustaría hacerte?"


def test_un_alias_de_argumento_sigue_valiendo(api_module, monkeypatch):  # noqa: F811
    """«codigo» no está en el esquema pero es alias de codigo_reserva: no se rechaza."""
    _, ejecutadas, _ = _turno_del_agente(monkeypatch, '{"codigo": "R-123456"}', nombre="consultar_cita")
    assert ejecutadas and ejecutadas[0][0] == "consultar_cita", ejecutadas


def _con_modelo_de_intents(monkeypatch, contenido):
    from backend import intents, settings

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    monkeypatch.setattr(intents, "enabled_for", lambda *a, **k: True)
    _modelo_falso(monkeypatch, [contenido])
    return intents


@pytest.mark.parametrize("contenido", ["[]", "null", '{"intencion": ["reservar"], "confianza": 0.9}',
                                       '{"intencion": "reservar", "confianza": NaN}',
                                       '{"intencion": "reservar", "confianza": Infinity}'])
def test_clasificar_con_otra_forma_no_revienta_ni_se_da_por_segura(api_module, monkeypatch, contenido):  # noqa: F811
    intents = _con_modelo_de_intents(monkeypatch, contenido)
    assert intents.classify("demo", "quiero una cita para el viernes %s" % json.dumps(contenido)) is None


def test_clasificar_bien_formado_sigue_funcionando(api_module, monkeypatch):  # noqa: F811
    intents = _con_modelo_de_intents(monkeypatch, '{"intencion": "reservar", "familia": "", "confianza": 0.9}')
    resultado = intents.classify("demo", "quiero una cita para el viernes, bien formado")
    assert resultado and resultado["intencion"] == "reservar" and resultado["confianza"] == 0.9


@pytest.mark.parametrize("contenido", ["[]", "null", '{"familia": ["mechas"], "talla": {"x": 1}}'])
def test_extraer_datos_con_otra_forma_no_revienta(api_module, monkeypatch, contenido):  # noqa: F811
    intents = _con_modelo_de_intents(monkeypatch, contenido)
    datos = intents.extraer_datos_servicio("demo", "quiero unas mechas %s" % json.dumps(contenido))
    assert datos is None or all(isinstance(datos[k], str) for k in ("familia", "tecnica", "talla", "para_quien"))


@pytest.mark.parametrize("contenido", ['{"intencion": "reservar", "confianza": true}',
                                       '{"intencion": "reservar", "confianza": 0.9, "pregunta": 1e309}',
                                       '{"intencion": "reservar", "confianza": 1e309}'])
def test_numeros_que_no_lo_son_no_dan_confianza_ni_revientan(api_module, monkeypatch, contenido):  # noqa: F811
    """Revisión de Astra a cb46dae: `true` daba confianza 1.0 y `1e309` (que no es NaN ni Infinity
    para parse_constant) llegaba como infinito y hacía saltar OverflowError fuera de classify."""
    intents = _con_modelo_de_intents(monkeypatch, contenido)
    assert intents.classify("demo", "quiero una cita para el viernes %s" % json.dumps(contenido)) is None


@pytest.mark.parametrize("confianza", ['0.9', '"0.9"'])
def test_una_confianza_numerica_o_en_texto_sigue_valiendo(api_module, monkeypatch, confianza):  # noqa: F811
    intents = _con_modelo_de_intents(monkeypatch, '{"intencion": "reservar", "confianza": %s}' % confianza)
    resultado = intents.classify("demo", "quiero una cita para el viernes, confianza %s" % confianza)
    assert resultado and resultado["confianza"] == 0.9
