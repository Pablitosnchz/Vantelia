# -*- coding: utf-8 -*-
"""Que el asistente este mudo tiene que VERSE.

Incidente del 26-ago-2026: se agotaron los creditos de OpenAI, el asistente dejo
de contestar a todos los clientes, y `/health` seguia diciendo
"openai_configured: true" porque solo miraba que la clave estuviera puesta. Se
descubrio probando el chat a mano. Un negocio que vende por WhatsApp no puede
enterarse de eso por un cliente enfadado.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module, client  # noqa: F401


def test_reconoce_los_fallos_que_dejan_mudo_al_asistente(api_module):  # noqa: F811
    from backend import rag

    assert rag._es_fallo_de_cuenta(
        "Error code: 429 - insufficient_quota: You have no credits remaining")
    assert rag._es_fallo_de_cuenta("401 invalid_api_key")
    assert rag._es_fallo_de_cuenta("Your credit balance is too low")

    # Un tropiezo normal NO es una caida de cuenta: reintentar lo arregla.
    assert not rag._es_fallo_de_cuenta("Request timed out")
    assert not rag._es_fallo_de_cuenta("Connection reset by peer")


def test_una_llamada_real_fallida_deja_constancia(api_module):  # noqa: F811
    """No hace falta preguntar aparte: si una conversacion fallo, eso ya es el check."""
    from backend import rag

    rag._ia_marcar(False, "insufficient_quota")
    assert rag._ia_health_cached()["ok"] is False
    rag._ia_marcar(True)
    assert rag._ia_health_cached()["ok"] is True


def test_el_health_publica_el_estado_del_modelo(api_module, client):  # noqa: F811
    from backend import rag

    rag._ia_marcar(False, "insufficient_quota")
    checks = client.get("/health").json()["checks"]
    assert checks.get("ia") == "fail", "la caida del modelo no se ve en /health"

    rag._ia_marcar(True)
    assert client.get("/health").json()["checks"].get("ia") == "ok"


def test_el_agente_avisa_cuando_se_queda_sin_saldo(api_module):  # noqa: F811
    import inspect

    from backend import agent

    fuente = inspect.getsource(agent.responder)
    assert "_es_fallo_de_cuenta" in fuente, (
        "el agente se come el error y nadie se entera de que esta mudo"
    )


def test_si_cae_la_cuenta_se_avisa_a_pablo_una_vez(api_module, monkeypatch):  # noqa: F811
    """5-oct-2026: sin credito entre las 14:50 y las 16:15 y nadie se entero hasta que fallo el
    humo de un despliegue; mientras, las demos de los prospectos tampoco contestaban. Ahora llega
    un correo, y uno solo aunque cada conversacion vuelva a ver la caida."""
    from backend import outreach, rag

    avisos = []
    monkeypatch.setattr(outreach, "_outreach_notify_admin", lambda asunto, texto, html="": avisos.append(asunto))
    monkeypatch.setattr(rag, "_ia_ultimo_aviso", [0.0])
    rag._ia_marcar(False, "Error code: 429 - insufficient_quota: You have no credits remaining")
    rag._ia_hilo_aviso[0].join(5)
    rag._ia_marcar(False, "Error code: 429 - insufficient_quota")
    assert avisos == ["⚠️ El asistente no responde: falla la cuenta de OpenAI"]
    # Un tropiezo normal no avisa, ni que falte la clave en un entorno de pruebas.
    monkeypatch.setattr(rag, "_ia_ultimo_aviso", [0.0])
    rag._ia_marcar(False, "Request timed out")
    rag._ia_marcar(False, "sin OPENAI_API_KEY")
    assert len(avisos) == 1
    rag._ia_marcar(True)
