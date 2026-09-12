"""El bucle real del agente sale de técnica/talla sin elegir un tratamiento."""
import asyncio
import json
import sys
import types

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("duda,falta,regla,valoracion,esperado", [
    ("no lo tengo claro", "tecnica", True, True, "Diagnostico"),
    ("no lo tengo claro", "tecnica", "declarada", True, ""),
    ("no lo tengo claro", "tecnica", "foto", True, ""),
    ("no lo tengo claro", "talla", True, True, "Diagnostico"),
    ("no lo se", "talla", True, True, "Diagnostico"),
    ("no lo tengo claro", "tecnica", False, True, ""),
    ("no lo tengo claro", "tecnica", True, False, ""),
    ("no lo se", "", True, True, "Keratina medio"),
    ("no lo se, no quiero diagnostico", "tecnica", True, True, ""),
    ("keratina", "talla", True, True, ""),
    ("keratina", "talla", False, True, ""),
    ("la keratina, pero no se si tengo el pelo medio o largo", "talla", True, True, ""),
])
def test_tercera_busqueda_del_agente(api_module, monkeypatch, duda, falta, regla, valoracion, esperado):
    from backend import agent, booking, reserva, settings

    estado = reserva.Estado(intencion="reservar", servicio_texto="quiero un alisado",
                            ultimo_falta="tecnica", veces_falta=1)
    estado.candidatos_pendientes = 4
    monkeypatch.setattr(reserva, "cargar", lambda *a: estado)
    monkeypatch.setattr(reserva, "guardar", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_historial", lambda *a: [
        {"role": "user", "content": "quiero un alisado"},
        {"role": "assistant", "content": "¿Qué técnica quieres?"},
        {"role": "user", "content": duda},
    ])
    monkeypatch.setattr(agent, "_lo_que_el_negocio_dice_al_recomendar",
                        lambda cid, config=None: "Se decide en persona." if regla else "")
    declarada = {"id": "orientacion", "accion": "ofrecer_cita", "texto": "Te orientamos en persona", "activa": True}
    if regla == "foto":
        declarada.update(accion="pedir_foto", texto="Envíanos una foto")
    monkeypatch.setattr(booking, "regla_de_orientacion_para", lambda *a: declarada if regla in ("declarada", "foto") else {})
    monkeypatch.setattr(booking, "_servicio_de_valoracion",
                        lambda *a, **k: {"id": "diag", "nombre": "Diagnostico", "duration_minutes": 20} if valoracion else None)
    def buscar(cid, args, **kwargs):
        if args["descripcion"] == "Diagnostico":
            return {"ok": True, "servicio": "Diagnostico", "servicio_en_agenda": "Diagnostico"}
        return {"ok": True, "servicio": "" if falta else "Keratina medio", "falta": falta, "total_candidatos": 2 if duda.startswith("la keratina") else 4}
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
    asyncio.run(agent.responder("demo", duda, session_id="prueba-duda",
                               telefono="34600777999", intencion="reservar"))
    if regla == "declarada":
        assert observados == []  # la oferta se devuelve sin ordenar seleccionar ni crear
        assert estado.servicio == ""
        propuesta = estado.propuesta_servicio
        assert propuesta.estado == "ofrecida"
        assert propuesta.origen == "orientacion:orientacion"
        asyncio.run(agent.responder("demo", duda, session_id="prueba-duda",
                                   telefono="34600777999", intencion="reservar"))
        assert estado.propuesta_servicio.id == propuesta.id

        from dataclasses import replace
        estado.propuesta_servicio = replace(estado.propuesta_servicio, creada=0)
        asyncio.run(agent.responder("demo", duda, session_id="prueba-duda",
                                   telefono="34600777999", intencion="reservar"))
        assert estado.propuesta_servicio.id != propuesta.id
        assert not booking.contestar_alternativa_de_precio("demo", estado, propuesta.id, "acepta")
        propuesta = estado.propuesta_servicio

        declarada["accion"] = "pedir_foto"
        assert not booking.contestar_alternativa_de_precio("demo", estado, propuesta.id, "acepta")
        assert estado.propuesta_servicio.estado == "invalidada"
        assert estado.servicio == ""
        return
    assert len(observados) == 1
    assert observados[0].get("servicio", "") == esperado
    assert estado.servicio == esperado
    if regla == "foto":
        assert estado.propuesta_servicio is None
        assert observados[0]["politica_orientacion"]["accion"] == "pedir_foto"
        assert "cogele la" not in observados[0]["nota"]
    if duda == "keratina":
        assert "nota" not in observados[0]
        assert estado.veces_falta == 0


@pytest.mark.parametrize("mensajes,obligatoria,esperado", [
    (["no lo tengo claro", "¿me puedes coger cita?", "directamente para mañana"], False, "Diagnostico"),
    (["no lo tengo claro", "no quiero diagnostico"], False, ""),
    (["no lo tengo claro", "no quiero diagnostico"], True, "Diagnostico"),
])
def test_renuncia_por_mensaje_y_respeta_obligatoriedad(api_module, monkeypatch, mensajes, obligatoria, esperado):
    from backend import agent, booking
    monkeypatch.setattr(agent, "_lo_que_el_negocio_dice_al_recomendar", lambda *a: "Se decide en persona.")
    monkeypatch.setattr(booking, "_servicio_de_valoracion", lambda *a: {"nombre": "Diagnostico"})
    monkeypatch.setattr(booking, "la_valoracion_es_obligatoria", lambda *a: obligatoria)
    assert agent._hay_que_cogerle_la_valoracion(
        "demo", [{"role": "user", "content": m} for m in mensajes], 2) == esperado


def test_familia_obligatoria_no_desaparece_al_superar_1500_caracteres(api_module, monkeypatch):
    from backend import agent, booking
    monkeypatch.setattr(agent, "_lo_que_el_negocio_dice_al_recomendar", lambda *a: "Se decide en persona.")
    monkeypatch.setattr(booking, "_servicio_de_valoracion", lambda *a: {"nombre": "Diagnostico"})
    monkeypatch.setattr(booking, "la_valoracion_es_obligatoria", lambda cid, texto: "extensiones" in texto)
    mensajes = [{"role": "user", "content": m} for m in
                ["quiero extensiones", "comentario " * 180, "no lo tengo claro, no quiero diagnostico"]]
    assert agent._hay_que_cogerle_la_valoracion("demo", mensajes, 2) == "Diagnostico"
