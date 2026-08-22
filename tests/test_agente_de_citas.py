# -*- coding: utf-8 -*-
"""El modelo lleva la conversacion; las tools no le dejan mentir.

Peticion del salon: que la IA sea inteligente, que recomiende y guie, pero que
sepa lo que necesita para agendar. Las dos primeras versiones fallaron cada una
por un lado -una maquina de pasos que no recomienda, o un prompt que decidia
distinto cada vez y llego a decir "te he reservado" sin cita-.

Esta es la arquitectura que ya usa el asistente de VOZ: el modelo decide que decir
y las TOOLS ponen la fiabilidad. Aqui se comprueba lo segundo, que es lo que no
puede depender de como venga el modelo ese dia:

* No puede ofrecer un servicio que no exista en el catalogo.
* No puede ofrecer un hueco que no este libre.
* No puede dar una cita por hecha: el numero de reserva solo sale de `crear_cita`.
* Si el modelo falla, el canal tiene que poder seguir por su cuenta.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def catalogo(api_module, client):  # noqa: F811
    from backend import agenda, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for nombre, categoria in (("Mechas medio", "Color"), ("Corte senora", "Cortes")):
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo', ?, ?, ?, 30, 1000, '', 1, 0, ?, ?)",
                (agenda._normalize_service_id(nombre), nombre, categoria, ahora, ahora),
            )
        conexion.commit()
    yield
    with db._get_db_connection() as conexion:
        conexion.execute(
            "DELETE FROM services WHERE cliente_id='demo' AND name IN ('Mechas medio','Corte senora')"
        )
        conexion.commit()


# ─── Las tools son la barrera ──────────────────────────────────────────────

def test_solo_devuelve_servicios_que_existen(catalogo, api_module, monkeypatch):  # noqa: F811
    """El modelo no puede inventarse un nombre: los saca de aqui."""
    from backend import booking_agent, intents

    monkeypatch.setattr(intents, "extraer_datos_servicio", lambda *a, **k: {
        "familia": "mechas", "tecnica": "", "talla": "medio",
        "para_quien": "", "edad": None, "texto": "mechas medias",
    })
    resultado = booking_agent._tool_buscar_servicio("demo", {"descripcion": "mechas"})
    assert resultado["ok"] is True
    assert resultado["servicio"] == "Mechas medio"


def test_lo_que_no_existe_se_dice_con_alternativas(catalogo, api_module, monkeypatch):  # noqa: F811
    from backend import booking_agent, intents

    monkeypatch.setattr(intents, "extraer_datos_servicio", lambda *a, **k: {
        "familia": "manicura", "tecnica": "", "talla": "",
        "para_quien": "", "edad": None, "texto": "manicura",
    })
    resultado = booking_agent._tool_buscar_servicio("demo", {"descripcion": "manicura"})
    assert resultado["ok"] is False
    assert "servicios_parecidos" in resultado


def test_cuando_falta_un_dato_lo_dice_en_vez_de_elegir(catalogo, api_module, monkeypatch):  # noqa: F811
    """Elegir por la clienta entre tecnicas distintas no es cosa del modelo."""
    from backend import agenda, booking_agent, db, intents, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for nombre in ("Keratina premium medio", "Acido lactico bio premium-medio"):
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, category,"
                " duration_minutes, price_cents, description, is_active, sort_order,"
                " created_at, updated_at) VALUES ('demo', ?, ?, 'Alisados', 30, 1000, '', 1, 0, ?, ?)",
                (agenda._normalize_service_id(nombre), nombre, ahora, ahora),
            )
        conexion.commit()
    monkeypatch.setattr(intents, "extraer_datos_servicio", lambda *a, **k: {
        "familia": "alisado", "tecnica": "", "talla": "medio",
        "para_quien": "", "edad": None, "texto": "un alisado",
    })
    try:
        resultado = booking_agent._tool_buscar_servicio("demo", {"descripcion": "un alisado"})
        assert resultado["servicio"] == ""
        assert resultado["falta"] == "tecnica"
        assert len(resultado["opciones"]) >= 2
    finally:
        with db._get_db_connection() as conexion:
            conexion.execute(
                "DELETE FROM services WHERE cliente_id='demo' AND name IN"
                " ('Keratina premium medio','Acido lactico bio premium-medio')"
            )
            conexion.commit()


# ─── El agente no puede quedarse sin plan B ────────────────────────────────

def test_sin_clave_no_se_intenta(api_module, monkeypatch):  # noqa: F811
    from backend import booking_agent

    monkeypatch.setattr(booking_agent.settings, "OPENAI_API_KEY", "")
    assert booking_agent.disponible("demo") is False
    texto, creada = asyncio.run(booking_agent.responder(
        "demo", "quiero cita", session_id="s", telefono="34600000000",
    ))
    assert texto == "" and creada is False


def test_si_el_modelo_falla_devuelve_vacio(api_module, monkeypatch):  # noqa: F811
    """Vacio = "sigue tu": el canal tira de sus listas y nadie se queda colgado."""
    import sys
    import types

    from backend import booking_agent

    monkeypatch.setattr(booking_agent.settings, "OPENAI_API_KEY", "sk-test")

    class ClienteRoto:
        def __init__(self, *a, **k):
            raise RuntimeError("OpenAI caido")

    modulo = types.ModuleType("openai")
    modulo.OpenAI = ClienteRoto
    monkeypatch.setitem(sys.modules, "openai", modulo)

    texto, creada = asyncio.run(booking_agent.responder(
        "demo", "quiero cita", session_id="s", telefono="34600000000",
    ))
    assert texto == "" and creada is False


def test_las_instrucciones_le_prohiben_dar_la_cita_por_hecha(api_module):  # noqa: F811
    from backend import booking_agent, clients

    import datetime

    texto = booking_agent._instrucciones(
        "demo", clients._get_client_config("demo"), datetime.date(2026, 9, 1),
    )
    assert "crear_cita" in texto
    assert "NUNCA digas que esta reservada" in texto
    assert "Inventarte un servicio" in texto
    # Y las fechas se le dan hechas: calcularlas de cabeza le sale mal ("el jueves
    # que viene, 29 de agosto" siendo el jueves el 27).
    assert "no calcules fechas de cabeza" in texto
    assert "martes 1 de septiembre" in texto


def test_las_tres_herramientas_estan(api_module):  # noqa: F811
    from backend import booking_agent

    nombres = {h["function"]["name"] for h in booking_agent._herramientas()}
    assert nombres == {"buscar_servicio", "consultar_disponibilidad", "crear_cita"}


def test_la_cita_la_crea_el_mismo_despachador_que_la_voz(api_module):  # noqa: F811
    """Una sola forma de crear una cita en todo el producto."""
    import inspect

    from backend import booking_agent

    fuente = inspect.getsource(booking_agent._ejecutar)
    assert "_voice_dispatch_tool" in fuente


def test_whatsapp_cae_a_las_listas_si_el_agente_no_puede(api_module):  # noqa: F811
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_turno_del_agente)
    assert "return False" in fuente, "tiene que poder decir que no ha podido"
    manejo = inspect.getsource(whatsapp._handle_whatsapp_message)
    assert "_wa_send_service_picker" in manejo
