# -*- coding: utf-8 -*-
"""Una oferta que el negocio retira a mitad de conversación no acaba en su cita.

POR QUE EXISTE
--------------
13-sep-2026, escenario «regla apagada después de ofrecer» medido con modelo real sobre
copia de producción (0bca1eb). Se le ofreció a la clienta la cita de Diagnóstico y
presupuesto (regla de orientación de Alicia) y, antes de que contestara, el negocio
apagó la regla desde el portal:

    ella «a las 15» / «si»
    IA   «Esta opción ya no está vigente. Dime qué servicio quieres...»     (bien)
    ella «me llamo Ana Ruiz Perez»
    IA   📋 Resumen de tu cita · Diagnostico y presupuesto · 15:00           <-- mal

Al revalidar, la propuesta queda `invalidada`, pero la guarda de `crear_cita` solo miraba
las propuestas `preparada`/`ofrecida`: con la invalidada, el modelo volvía a pedir la
cita del servicio retirado y se le montaba el resumen. Ella nunca pidió un diagnóstico:
lo había ofrecido una regla que ya no existe.

Si después lo pide ELLA por su nombre, se le coge: el servicio sigue en el catálogo.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

from test_booking_exhaustive import api_module  # noqa: F401


def _turno(monkeypatch, *, mensaje, historial):
    """El modelo llama a crear_cita con el servicio de la oferta retirada."""
    from backend import agent, reserva, settings

    estado = reserva.Estado(intencion="reservar", servicio="Keratina premium", fecha="2030-01-08",
                            hora="15:00", nombre="Ana Ruiz Perez")
    propuesta = reserva.preparar_propuesta_servicio(
        estado, servicio_id="diagnostico_y_presupuesto", nombre="Diagnóstico y presupuesto",
        origen="orientacion:regla", revision_config="v1", servicio_origen="quiero un alisado")
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje")
    reserva.invalidar_propuesta_servicio(estado)   # el negocio apaga la regla
    assert estado.propuesta_servicio.estado == "invalidada"

    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: list(historial))
    ejecutadas = []

    async def ejecutar(cliente_id, nombre, argumentos, **kwargs):
        ejecutadas.append(nombre)
        return {"ok": False, "pendiente_de_confirmacion": True}

    monkeypatch.setattr(agent, "_ejecutar", ejecutar)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    llamadas = []

    def modelo(**kwargs):
        llamadas.append(kwargs)
        if len(llamadas) == 1:
            llamada = types.SimpleNamespace(id="crea", function=types.SimpleNamespace(
                name="crear_cita", arguments=json.dumps({
                    "servicio": "Diagnóstico y presupuesto", "fecha": "2030-01-08",
                    "hora": "15:00", "nombre": "Ana Ruiz Perez"})))
            respuesta = types.SimpleNamespace(content="", tool_calls=[llamada])
        else:
            respuesta = types.SimpleNamespace(content="¿Qué servicio te gustaría, cariño?", tool_calls=None)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=respuesta)])

    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)

    asyncio.run(agent.responder("demo", mensaje, session_id="oferta-retirada", telefono="34600970031"))
    return ejecutadas


HISTORIAL = [
    {"role": "user", "content": "quiero un alisado"},
    {"role": "user", "content": "no lo tengo claro"},
    {"role": "assistant", "content": ("Sin ver tu cabello no te puedo decir cual te conviene, cariño. "
                                      "¿Quieres una cita de Diagnostico y presupuesto?")},
    {"role": "user", "content": "a las 15"},
    {"role": "user", "content": "si"},
    {"role": "assistant", "content": "Esta opción ya no está vigente. Dime qué servicio quieres."},
]


def test_el_servicio_de_la_oferta_retirada_no_se_coge(api_module, monkeypatch):  # noqa: F811
    ejecutadas = _turno(monkeypatch, mensaje="me llamo Ana Ruiz Perez", historial=HISTORIAL)

    assert "crear_cita" not in ejecutadas, "se ha pedido la cita de una oferta que el negocio retiro"


def test_si_lo_pide_ella_se_le_coge(api_module, monkeypatch):  # noqa: F811
    """Control: el servicio sigue en el catálogo y ella puede pedirlo por su nombre."""
    ejecutadas = _turno(monkeypatch, mensaje="vale, pues quiero la cita de diagnóstico", historial=HISTORIAL)

    assert ejecutadas == ["crear_cita"]
