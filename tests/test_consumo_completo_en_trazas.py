# -*- coding: utf-8 -*-
"""Todo lo que se gasta en un turno queda en su traza, y lo que no se sabe se dice.

POR QUE EXISTE
--------------
Bloque C de COMPARATIVA_IA_Y_PLAN_DE_BAJO_COSTE.md (16-sep-2026). La llamada de cierre (al
agotar las vueltas) y las de `intents` no sumaban su consumo a la traza; una respuesta sin
`usage` o un modelo sin tarifa contaban como coste 0, que en el informe parece gratis. Sin otra
plataforma: la misma tabla `agent_turns` y el mismo `resumen_del_dia`.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
import uuid

from test_booking_exhaustive import api_module  # noqa: F401


def _uso(entrada, salida):
    return types.SimpleNamespace(prompt_tokens=entrada, completion_tokens=salida)


def _fila(session_id):
    from backend import db

    with db._get_db_connection() as conexion:
        return conexion.execute("SELECT * FROM agent_turns WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                                (session_id,)).fetchone()


def _openai_falso(monkeypatch, crear):
    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=crear)))
    monkeypatch.setitem(sys.modules, "openai", modulo)


def test_la_llamada_de_cierre_suma_su_consumo(api_module, monkeypatch):  # noqa: F811
    from backend import agent, reserva, settings

    estado = reserva.Estado()
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [])
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")

    async def ejecutar(cliente_id, nombre, argumentos, **kwargs):
        return {"ok": True, "horario": "de 10:00 a 19:00"}

    monkeypatch.setattr(agent, "_ejecutar", ejecutar)

    def crear(**kwargs):
        mensajes = kwargs.get("messages") or []
        if any(isinstance(m, dict) and "Contesta ya con lo que sabes" in str(m.get("content") or "")
               for m in mensajes):
            mensaje = types.SimpleNamespace(content="Abrimos de 10:00 a 19:00.", tool_calls=None)
        else:
            llamada = types.SimpleNamespace(id=uuid.uuid4().hex, function=types.SimpleNamespace(
                name="consultar_horario", arguments="{}"))
            mensaje = types.SimpleNamespace(content="", tool_calls=[llamada])
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=mensaje)], usage=_uso(100, 10))

    _openai_falso(monkeypatch, crear)
    session_id = "consumo-cierre-" + uuid.uuid4().hex[:6]
    asyncio.run(agent.responder("demo", "a que hora abris?", session_id=session_id, telefono="34600970081"))
    fila = _fila(session_id)
    llamadas = agent.MAX_VUELTAS + 1
    assert fila["tokens_entrada"] == 100 * llamadas and fila["tokens_salida"] == 10 * llamadas, dict(fila)
    assert fila["llamadas_modelo"] == llamadas and fila["llamadas_sin_uso"] == 0
    assert not fila["coste_desconocido"]


def test_sin_uso_o_sin_tarifa_el_coste_es_desconocido_no_gratis(api_module):  # noqa: F811
    from backend import trazas

    sin_uso = "consumo-sin-uso-" + uuid.uuid4().hex[:6]
    traza = trazas.Traza("demo", sin_uso)
    traza.respuesta_del_modelo("gpt-4o-mini", types.SimpleNamespace(usage=None))
    traza.guardar(mensaje="hola", respuesta="hola")
    fila = _fila(sin_uso)
    assert fila["llamadas_modelo"] == 1 and fila["llamadas_sin_uso"] == 1 and fila["coste_desconocido"]

    sin_tarifa = "consumo-sin-tarifa-" + uuid.uuid4().hex[:6]
    traza = trazas.Traza("demo", sin_tarifa)
    traza.respuesta_del_modelo("modelo-que-no-conocemos", types.SimpleNamespace(usage=_uso(500, 50)))
    traza.guardar(mensaje="hola", respuesta="hola")
    assert _fila(sin_tarifa)["coste_desconocido"]


def test_varios_modelos_en_un_turno_suman_cada_uno_con_su_tarifa(api_module):  # noqa: F811
    from backend import trazas

    session_id = "consumo-mixto-" + uuid.uuid4().hex[:6]
    traza = trazas.Traza("demo", session_id)
    traza.respuesta_del_modelo("gpt-4o", types.SimpleNamespace(usage=_uso(1_000_000, 0)))
    traza.respuesta_del_modelo("gpt-4o-mini", types.SimpleNamespace(usage=_uso(1_000_000, 0)))
    traza.guardar()
    assert abs(_fila(session_id)["coste_euros"] - (2.50 + 0.15)) < 1e-6


def test_la_interpretacion_dentro_del_turno_cuenta_una_vez(api_module, monkeypatch):  # noqa: F811
    from backend import intents, settings, trazas

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    monkeypatch.setattr(intents, "enabled_for", lambda *a, **k: True)

    def crear(**kwargs):
        mensaje = types.SimpleNamespace(content=json.dumps({"intencion": "info", "confianza": 0.9}))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=mensaje)], usage=_uso(40, 4))

    _openai_falso(monkeypatch, crear)
    session_id = "consumo-intents-" + uuid.uuid4().hex[:6]
    traza = trazas.Traza("demo", session_id)
    traza.activar()
    texto = "donde estais exactamente %s" % uuid.uuid4().hex[:6]
    intents.classify("demo", texto)
    intents.classify("demo", texto)  # de la caché: no llama al modelo ni suma otra vez
    traza.guardar()
    fila = _fila(session_id)
    assert fila["tokens_entrada"] == 40 and fila["llamadas_modelo"] == 1, dict(fila)
    # Fuera de un turno no se apunta en ningún sitio ni revienta.
    intents.classify("demo", "otra pregunta distinta %s" % uuid.uuid4().hex[:6])


def test_el_informe_dice_la_cobertura_la_latencia_y_las_vueltas(api_module):  # noqa: F811
    from backend import trazas

    cliente = "cobertura_" + uuid.uuid4().hex[:6]
    buena = trazas.Traza(cliente, "s1")
    buena.respuesta_del_modelo("gpt-4o-mini", types.SimpleNamespace(usage=_uso(100, 10)))
    buena.vuelta()
    buena.guardar()
    sin_uso = trazas.Traza(cliente, "s2")
    sin_uso.respuesta_del_modelo("gpt-4o-mini", types.SimpleNamespace(usage=None))
    sin_uso.vuelta()
    sin_uso.vuelta()
    sin_uso.guardar()
    resumen = trazas.resumen_del_dia(cliente)
    assert resumen["turnos_con_coste_desconocido"] == 1
    assert resumen["cobertura_de_consumo"] == 0.5
    assert resumen["llamadas_sin_uso"] == 1
    assert "ms_p95" in resumen
    assert resumen["vueltas"] == {"1": 1, "2": 1}


def test_la_consulta_del_turno_dice_que_el_coste_es_desconocido(api_module):  # noqa: F811
    """Revisión de Astra a c057e3b: se guardaba como desconocido, pero `del_turno` (GET /admin/traza)
    devolvía coste_euros 0.0 sin decirlo. Frontera BD → consulta."""
    from backend import trazas

    session_id = "consulta-sin-uso-" + uuid.uuid4().hex[:6]
    traza = trazas.Traza("demo", session_id)
    traza.respuesta_del_modelo("gpt-4o-mini", types.SimpleNamespace(usage=None))
    traza.guardar(mensaje="hola", respuesta="hola")
    vista = trazas.del_turno("demo", session_id)[-1]
    assert vista["coste_desconocido"] is True, vista
    assert vista["llamadas_modelo"] == 1 and vista["llamadas_sin_uso"] == 1, vista
    assert "coste_euros" in vista  # compatibilidad: el campo sigue estando

    conocido = "consulta-con-uso-" + uuid.uuid4().hex[:6]
    traza = trazas.Traza("demo", conocido)
    traza.respuesta_del_modelo("gpt-4o-mini", types.SimpleNamespace(usage=_uso(10, 1)))
    traza.guardar()
    assert trazas.del_turno("demo", conocido)[-1]["coste_desconocido"] is False
