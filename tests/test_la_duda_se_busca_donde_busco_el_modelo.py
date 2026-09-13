# -*- coding: utf-8 -*-
"""La familia de la duda se busca en lo que buscó el modelo, no solo en lo acumulado.

POR QUE EXISTE
--------------
13-sep-2026. Con la regla de orientación de Alicia declarada (a quien no sabe qué
alisado quiere se le ofrece la cita de diagnóstico), el banco daba 0 de 6. Se
repitió la conversación turno a turno instrumentando cada paso, y en el turno en
que tocaba ofrecer el diagnóstico la regla se consultaba con este texto:

    "no lo tengo claro el 2026-09-15 a las 15"

Sin la palabra «alisado». El primer mensaje -«quiero un alisado»- lo atendió el
flujo de WhatsApp, no el agente, así que `estado.servicio_texto` empezaba en el
segundo. Sin familia, la regla no casaba, la propuesta no se preparaba y la
clienta seguía oyendo «¿Keratina o Ácido láctico?» hasta irse.

Mientras tanto, la `descripcion` con la que el modelo llamaba a `buscar_servicio`
sí decía «quiero un alisado no lo tengo claro»: era la misma búsqueda que
respondía que faltaba la técnica.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def test_la_duda_incluye_lo_que_busco_el_modelo(api_module):  # noqa: F811
    """El caso medido: lo acumulado perdió el servicio; la búsqueda lo conserva."""
    from backend import agent, reserva

    estado = reserva.Estado()
    estado.servicio_texto = "no lo tengo claro el 2026-09-15 a las 15"

    texto = agent._texto_de_la_duda(estado, {"descripcion": "quiero un alisado no lo tengo claro"})

    assert "alisado" in texto, "la regla se consultaría sin la familia y no casaría"
    assert "no lo tengo claro" in texto


def test_sin_busqueda_se_usa_lo_que_ella_ha_dicho(api_module):  # noqa: F811
    from backend import agent, reserva

    estado = reserva.Estado()
    estado.servicio_texto = "quiero unas mechas"

    assert agent._texto_de_la_duda(estado, {}) == "quiero unas mechas"
    assert agent._texto_de_la_duda(reserva.Estado(), {}) == ""


def test_con_el_primer_mensaje_perdido_la_propuesta_se_prepara(api_module, monkeypatch):  # noqa: F811
    """El recorrido que falló, de verdad: `responder` con el modelo simulado.

    El test que ya había (`test_salida_de_la_duda`) no podía verlo: sustituía la
    regla por una que se aplicaba siempre, pasara el texto que pasara, y empezaba
    con `servicio_texto` conteniendo ya «alisado». Aquí el doble de la regla solo
    casa si el texto que recibe DICE alisado, que es lo que hace la de verdad.
    """
    import asyncio
    import json
    import sys
    import types

    from backend import agent, booking, reserva, settings

    estado = reserva.Estado(intencion="reservar",
                            servicio_texto="no lo tengo claro el 2026-09-15 a las 15",
                            ultimo_falta="tecnica", veces_falta=1)
    estado.candidatos_pendientes = 4
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [
        {"role": "user", "content": "quiero un alisado"},
        {"role": "assistant", "content": "¿Keratina premium o Ácido láctico bio premium?"},
        {"role": "user", "content": "no lo tengo claro"},
    ])
    consultados = []
    declarada = {"id": "orientacion", "accion": "ofrecer_cita",
                 "texto": "Lo vemos en la cita de diagnóstico.", "activa": True}

    def regla_real(cliente_id, texto):
        consultados.append(texto)
        return dict(declarada) if "alisado" in (texto or "") else {}

    monkeypatch.setattr(booking, "regla_de_orientacion_para", regla_real)
    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda *a, **k: {"id": "diag", "nombre": "Diagnostico y presupuesto",
                                         "duration_minutes": 20})
    monkeypatch.setattr(agent, "_tool_buscar_servicio", lambda cid, args, **k: {
        "ok": True, "servicio": "", "falta": "tecnica", "total_candidatos": 4})
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")

    def modelo(**kwargs):
        # El modelo busca con lo que ella ha pedido en toda la conversacion.
        llamada = types.SimpleNamespace(id="busqueda", function=types.SimpleNamespace(
            name="buscar_servicio",
            arguments=json.dumps({"descripcion": "quiero un alisado no lo tengo claro"})))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content="", tool_calls=[llamada]))])

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)

    asyncio.run(agent.responder("demo", "no lo tengo claro", session_id="duda-perdida",
                                telefono="34600777111", intencion="reservar"))

    assert consultados, "la rama de orientacion ni siquiera consulto la regla"
    assert "alisado" in consultados[-1], (
        "la regla se consulto con %r, sin la familia: no casara nunca" % consultados[-1])
    assert estado.propuesta_servicio is not None, (
        "sin propuesta, a la clienta se le sigue preguntando la tecnica hasta que se va")
    assert estado.propuesta_servicio.origen.startswith("orientacion:")
    assert estado.servicio == "", "ofrecer la alternativa no puede elegir el servicio por ella"


def test_la_rama_de_orientacion_consulta_ese_texto(api_module):  # noqa: F811
    """Un helper correcto no sirve si la rama sigue mirando solo lo acumulado."""
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_texto_de_la_duda(estado, argumentos)" in fuente
    assert 'original = str(estado.servicio_texto or argumentos.get("descripcion")' not in fuente, (
        "la rama sigue prefiriendo el texto acumulado, que pierde el primer mensaje")
