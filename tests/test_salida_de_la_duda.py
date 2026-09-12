"""El bucle real del agente sale de técnica/talla sin elegir un tratamiento."""
import asyncio
import json
import sys
import types

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("duda,falta,regla,valoracion,esperado", [
    ("no lo tengo claro", "tecnica", True, True, "Diagnostico"),
    ("no lo tengo claro", "talla", True, True, "Diagnostico"),
    ("no lo se", "talla", True, True, "Diagnostico"),
    ("no lo tengo claro", "tecnica", False, True, ""),
    ("no lo tengo claro", "tecnica", True, False, ""),
    ("no lo se", "", True, True, "Keratina medio"),
    ("no lo se, no quiero diagnostico", "tecnica", True, True, ""),
])
def test_tercera_busqueda_del_agente(api_module, monkeypatch, duda, falta, regla, valoracion, esperado):
    from backend import agent, booking, reserva, settings

    estado = reserva.Estado(intencion="reservar", servicio_texto="quiero un alisado",
                            ultimo_falta="tecnica", veces_falta=1)
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [
        {"role": "user", "content": "quiero un alisado"},
        {"role": "assistant", "content": "¿Qué técnica quieres?"},
        {"role": "user", "content": duda},
    ])
    monkeypatch.setattr(agent, "_lo_que_el_negocio_dice_al_recomendar",
                        lambda cid, config=None: "Se decide en persona." if regla else "")
    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda *a, **k: {"nombre": "Diagnostico"} if valoracion else None)
    def buscar(cid, args, **kwargs):
        if args["descripcion"] == "Diagnostico":
            return {"ok": True, "servicio": "Diagnostico", "servicio_en_agenda": "Diagnostico"}
        return {"ok": True, "servicio": "" if falta else "Keratina medio", "falta": falta}
    monkeypatch.setattr(agent, "_tool_buscar_servicio", buscar)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    observados = []
    def modelo(**kwargs):
        resultados = [m for m in kwargs["messages"] if m["role"] == "tool"]
        if resultados:
            observados.append(json.loads(resultados[-1]["content"]))
            raise RuntimeError("fin de la observación determinista")
        llamada = types.SimpleNamespace(id="busqueda", function=types.SimpleNamespace(
            name="buscar_servicio", arguments=json.dumps({"descripcion": "alisado"})))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content="", tool_calls=[llamada]))])
    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)
    asyncio.run(agent.responder("demo", "mañana", session_id="prueba-duda",
                               telefono="34600777999", intencion="reservar"))
    assert len(observados) == 1
    assert observados[0].get("servicio", "") == esperado
    assert estado.servicio == esperado
