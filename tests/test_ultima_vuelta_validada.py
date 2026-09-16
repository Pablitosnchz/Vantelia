# -*- coding: utf-8 -*-
"""La respuesta final se comprueba también cuando no quedan vueltas.

POR QUE EXISTE
--------------
Bloque A de COMPARATIVA_IA_Y_PLAN_DE_BAJO_COSTE.md (16-sep-2026). Los frenos que comprueban
hechos (un precio que el negocio no da, una cita que no existe) solo actuaban si quedaba otra
vuelta (`vuelta + 1 < MAX_VUELTAS`) para que el modelo la corrigiera. En la última vuelta, y en
la llamada de cierre que se hace al agotarlas, la respuesta salía sin comprobar.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

from test_booking_exhaustive import api_module  # noqa: F401

PRECIO = "Perfecto, las mechas son 80 €. ¿Qué día te viene bien?"
CITA_FALSA = "¡Listo! Tu cita está confirmada para el jueves a las 10:00."
BUENA = "Perfecto. ¿Qué día te viene bien?"


def _turno(monkeypatch, respuesta, *, en_el_cierre, herramienta="consultar_horario"):
    """Consulta el horario en cada vuelta y contesta `respuesta` en la última (o en el cierre)."""
    from backend import agent, booking, reserva, settings

    estado = reserva.Estado()
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [])
    monkeypatch.setattr(booking, "precios_ocultos", lambda *a, **k: True)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")

    async def ejecutar(cliente_id, nombre, argumentos, **kwargs):
        if nombre == "crear_cita":
            return {"ok": True, "codigo_reserva": "R-123456", "fecha": "2099-01-08", "hora": "10:00"}
        return {"ok": True, "horario": "de 10:00 a 19:00"}

    monkeypatch.setattr(agent, "_ejecutar", ejecutar)
    llamadas = []

    def modelo(**kwargs):
        mensajes = kwargs.get("messages") or []
        llamadas.append(1)
        es_cierre = any(isinstance(m, dict) and m.get("role") == "system"
                        and "Contesta ya con lo que sabes" in str(m.get("content") or "") for m in mensajes)
        vueltas_hechas = sum(1 for m in mensajes if isinstance(m, dict) and m.get("role") == "tool")
        if es_cierre or (not en_el_cierre and vueltas_hechas >= agent.MAX_VUELTAS - 1):
            mensaje = types.SimpleNamespace(content=respuesta, tool_calls=None)
        else:
            llamada = types.SimpleNamespace(id="h%d" % vueltas_hechas, function=types.SimpleNamespace(
                name=herramienta, arguments=json.dumps({})))
            mensaje = types.SimpleNamespace(content="", tool_calls=[llamada])
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=mensaje)])

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)
    texto, _ = asyncio.run(agent.responder("demo", "quiero unas mechas", session_id="ultima-vuelta",
                                           telefono="34600970079"))
    return texto, len(llamadas)


@pytest.mark.parametrize("en_el_cierre", [False, True], ids=["ultima-vuelta", "cierre"])
def test_un_precio_que_no_se_da_no_sale_sin_vueltas(api_module, monkeypatch, en_el_cierre):  # noqa: F811
    from backend import agent

    texto, llamadas = _turno(monkeypatch, PRECIO, en_el_cierre=en_el_cierre)
    assert "80" not in texto, texto
    assert llamadas <= agent.MAX_VUELTAS + 1, "no puede costar más llamadas que antes"


@pytest.mark.parametrize("en_el_cierre", [False, True], ids=["ultima-vuelta", "cierre"])
def test_una_cita_que_no_existe_no_se_da_por_hecha_sin_vueltas(api_module, monkeypatch, en_el_cierre):  # noqa: F811
    from backend import agent

    texto, llamadas = _turno(monkeypatch, CITA_FALSA, en_el_cierre=en_el_cierre)
    assert not agent._da_la_cita_por_hecha(texto) and not agent._afirma_que_hay_cita_confirmada(texto), texto
    assert llamadas <= agent.MAX_VUELTAS + 1


@pytest.mark.parametrize("en_el_cierre", [False, True], ids=["ultima-vuelta", "cierre"])
def test_una_respuesta_correcta_sale_igual(api_module, monkeypatch, en_el_cierre):  # noqa: F811
    texto, _ = _turno(monkeypatch, BUENA, en_el_cierre=en_el_cierre)
    assert texto == BUENA


@pytest.mark.parametrize("en_el_cierre", [False, True], ids=["ultima-vuelta", "cierre"])
def test_una_cita_creada_de_verdad_se_confirma_igual(api_module, monkeypatch, en_el_cierre):  # noqa: F811
    """Sin vueltas no se puede negar lo que SI se ha hecho: si la herramienta creó la cita en este
    turno, la confirmación sale tal cual."""
    texto, _ = _turno(monkeypatch, CITA_FALSA, en_el_cierre=en_el_cierre, herramienta="crear_cita")
    assert texto == CITA_FALSA or "confirmada" in texto, texto


@pytest.mark.parametrize("en_el_cierre", [False, True], ids=["ultima-vuelta", "cierre"])
def test_precio_y_cita_inexistente_a_la_vez_se_corrigen_los_dos(api_module, monkeypatch, en_el_cierre):  # noqa: F811
    """Revisión de Astra a 437325d: se quitaba el precio y salía la confirmación falsa."""
    from backend import agent

    texto, llamadas = _turno(monkeypatch, "Las mechas son 80 €. Tu cita está confirmada para el jueves a las 10:00.",
                             en_el_cierre=en_el_cierre)
    assert not agent._afirma_que_hay_cita_confirmada(texto) and not agent._da_la_cita_por_hecha(texto), texto
    assert "80" not in texto, texto
    assert llamadas <= agent.MAX_VUELTAS + 1


FIANZA = ("La fianza se abona para confirmar y asegurar tu cita, y se descuenta del importe total el día de tu "
          "tratamiento. Lo más cómodo es que, cuando tu cita quede pendiente de pago, te enviamos un enlace seguro "
          "para pagar con tarjeta. Así, solo tienes que abrirlo y pagar en un minuto, y la cita queda confirmada "
          "automáticamente. Si prefieres, también puedes hacerlo por Bizum o transferencia. Si eliges Bizum, el "
          "número es 670 387 625 y solo necesitas poner tu nombre y apellido como concepto.")


@pytest.mark.parametrize("en_el_cierre", [False, True], ids=["ultima-vuelta", "cierre"])
def test_quitar_lo_que_incumple_no_tira_la_respuesta_entera(api_module, monkeypatch, en_el_cierre):  # noqa: F811
    """Medido con modelo real el 17-sep-2026 (banco de Alicia, f2a9696, caso crítico
    digresion-fianza-a-media-reserva, 2 de 2): «la cita queda confirmada automáticamente» al
    explicar la fianza se tomaba por una cita dada por hecha, y la salida segura sustituía la
    respuesta entera por «Todavía no tienes la cita cogida», perdiendo cómo se paga. Se quitan
    solo las frases que incumplen; lo demás se conserva."""
    from backend import agent

    texto, _ = _turno(monkeypatch, FIANZA, en_el_cierre=en_el_cierre)
    assert "Bizum" in texto and "670 387 625" in texto, texto
    assert not agent._afirma_que_hay_cita_confirmada(texto) and not agent._da_la_cita_por_hecha(texto), texto
