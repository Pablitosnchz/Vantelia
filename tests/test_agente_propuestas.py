"""El agente usa la propuesta actual, sin inferir aceptación del texto del bot."""
import asyncio
import json
import sys
import types

import pytest
from test_booking_exhaustive import api_module, client  # noqa: F401
from test_precio_que_no_se_negocia import salon_con_regla  # noqa: F401


@pytest.mark.parametrize("respuesta,esperado", [("acepta", "aceptada"), ("rechaza", "rechazada"),
                                               ("otra", "ofrecida"), ("ignora_esquema", "ofrecida")])
def test_respuesta_libre_pasa_por_la_transicion_compartida(api_module, monkeypatch, respuesta, esperado):
    from backend import agent, booking, reserva, settings
    estado = reserva.Estado(intencion="reservar", servicio="Color")
    propuesta = reserva.preparar_propuesta_servicio(
        estado, servicio_id="diag", nombre="Diagnóstico", origen="regla:precio",
        revision_config="v1", servicio_origen="Color")
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje")
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [])
    monkeypatch.setattr(booking, "alternativa_de_precio_vigente", lambda *a, **k:
                        {"servicio_id": "diag", "nombre": "Diagnóstico", "duracion": 20, "revision": "v1"})
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    resultados = []
    def modelo(**kwargs):
        tools = [m for m in kwargs["messages"] if m["role"] == "tool"]
        if tools:
            resultados.append(json.loads(tools[-1]["content"]))
            raise RuntimeError("fin de observación determinista")
        nombres = [t["function"]["name"] for t in kwargs["tools"]]
        assert "responder_propuesta" in nombres and "crear_cita" not in nombres
        llamada = types.SimpleNamespace(id="respuesta", function=types.SimpleNamespace(
            name="crear_cita" if respuesta == "ignora_esquema" else "responder_propuesta", arguments=json.dumps({"propuesta_id": propuesta.id,
                                                                "respuesta": respuesta})))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content="", tool_calls=[llamada]))])
    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)
    asyncio.run(agent.responder("demo", "esa opción me viene bien", session_id="propuesta-test",
                               telefono="34600999111", intencion="reservar"))
    assert len(resultados) == 1
    assert estado.propuesta_servicio.estado == esperado
    assert resultados[0]["ok"] == (respuesta in ("acepta", "rechaza"))
    assert estado.servicio == ("Diagnóstico" if respuesta == "acepta" else "Color")
    assert not estado.ya_creada


def test_historial_del_bot_no_autoriza_una_propuesta_rechazada(api_module):
    from backend import agent, reserva
    estado = reserva.Estado(intencion="reservar")
    propuesta = reserva.preparar_propuesta_servicio(
        estado, servicio_id="diag", nombre="Diagnóstico", origen="regla:precio", revision_config="v1")
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje")
    reserva.responder_propuesta_servicio(estado, propuesta.id, "rechaza", revision_config="v1")
    historial = [{"role": "assistant", "content": "¿Quieres una cita de diagnóstico?"}]
    assert not agent._acepta_la_valoracion("demo", historial, "sí", estado=estado)


def test_consulta_provisional_no_habilita_resumen(api_module):
    from backend import reserva
    estado = reserva.Estado(intencion="reservar", servicio="Color", nombre="Ana Ruiz",
                            fecha="2030-01-08", hora="10:00", esperando_confirmacion=True)
    propuesta = reserva.preparar_propuesta_servicio(
        estado, servicio_id="diag", nombre="Diagnóstico", origen="regla:precio", revision_config="v1")
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje")
    reserva.anotar_resultado(estado, "buscar_servicio", {}, {"ok": True, "servicio": "Diagnóstico"})
    assert estado.servicio == "Color"
    assert reserva.que_falta(estado) == "propuesta"
    assert reserva.tool_que_remata(estado) != "crear_cita"


def test_dos_sesiones_web_no_comparten_la_propuesta(api_module, monkeypatch):
    from backend import agent, appstate, reserva, settings
    monkeypatch.setattr(appstate, "ESTADOS_DE_RESERVA", {}, raising=False)
    # Antes todas las sesiones sin teléfono compartían esta clave.
    estado = reserva.cargar("demo", "")
    estado.intencion = "reservar"
    propuesta = reserva.preparar_propuesta_servicio(
        estado, servicio_id="diag", nombre="Diagnóstico", origen="regla:precio", revision_config="v1")
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje")
    monkeypatch.setattr(agent, "_historial", lambda *a: [])
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-prueba-sin-red")
    observados = []
    def modelo(**kwargs):
        observados.append([h["function"]["name"] for h in kwargs["tools"]])
        raise RuntimeError("fin de observación")
    modulo = types.ModuleType("openai")
    modulo.OpenAI = lambda **k: types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=modelo)))
    monkeypatch.setitem(sys.modules, "openai", modulo)
    asyncio.run(agent.responder("demo", "hola", session_id="segunda", telefono=""))
    assert observados and "responder_propuesta" not in observados[0]
    assert reserva.cargar("demo", "").propuesta_servicio == estado.propuesta_servicio
    assert reserva.cargar("demo", "web:segunda").propuesta_servicio is None


def test_editar_regla_persistida_invalida_oferta(salon_con_regla, api_module):
    from backend import booking, reserva, rules
    actual = booking.alternativa_de_precio_vigente("demo", "Mechas medio largo")
    assert actual
    estado = reserva.Estado(intencion="reservar", servicio="Mechas medio largo")
    propuesta = reserva.preparar_propuesta_servicio(
        estado, servicio_id=actual["servicio_id"], nombre=actual["nombre"],
        origen=actual["origen"], revision_config=actual["revision"], servicio_origen=estado.servicio)
    reserva.marcar_propuesta_ofrecida(estado, propuesta.id, "mensaje")
    regla = next(r for r in rules.listar("demo") if "regla:" + r["id"] == actual["origen"])
    rules.guardar("demo", regla_id=regla["id"], nombre=regla["nombre"],
                  intenciones=regla["intenciones"], familias=regla["familias"],
                  accion="pedir_foto", texto="Ahora pedimos foto para presupuestar.")
    assert not booking.contestar_alternativa_de_precio("demo", estado, propuesta.id, "acepta")
    assert estado.propuesta_servicio.estado == "invalidada"
    assert estado.servicio == "Mechas medio largo"
