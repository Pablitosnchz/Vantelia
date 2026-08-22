# -*- coding: utf-8 -*-
"""Reservar hablando, sin listas ni formularios.

Peticion del salon (21-ago-2026), literal:

    "No quiero el formulario para agendar cita, ese flujo. Quiero que la IA sea la
     que le guie a la hora de agendar una cita pero sin formulario: por ejemplo
     para los servicios, que la IA le diga que estilo quieres hacerte, el cliente
     dice 'mechas', y luego preguntarle vale, ¿como tienes el pelo, largo, corto?
     Tampoco quiero que salga nada del precio de los servicios de primeras."

Lo que NO cambia: el catalogo real, los huecos reales y el nucleo que crea la
cita. Solo cambia la piel. Y sigue siendo opcional: el resto de negocios pueden
querer sus listas, que se pulsan mas rapido y no fallan.
"""
from __future__ import annotations

import asyncio

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

TELEFONO = "34600777111"
NUMERO = "phone_demo"


@pytest.fixture
def salon_que_habla(api_module, client, monkeypatch):  # noqa: F811
    """Un negocio con catalogo y `booking.estilo = conversacional`."""
    from backend import agenda, clients, db, timeutils

    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as conexion:
        for nombre in ("Mechas medio", "Mechas largo", "Corte senora"):
            conexion.execute(
                "INSERT OR REPLACE INTO services (cliente_id, slug, name, duration_minutes,"
                " price_cents, description, is_active, sort_order, created_at, updated_at)"
                " VALUES ('demo', ?, ?, 60, 5000, '', 1, 0, ?, ?)",
                (agenda._normalize_service_id(nombre), nombre, ahora, ahora),
            )
        conexion.commit()

    config = clients._get_client_config("demo")
    previo = config["booking"].get("estilo")
    config["booking"]["estilo"] = "conversacional"
    yield config
    if previo is None:
        config["booking"].pop("estilo", None)
    else:
        config["booking"]["estilo"] = previo
    with db._get_db_connection() as conexion:
        conexion.execute(
            "DELETE FROM services WHERE cliente_id='demo' AND name IN"
            " ('Mechas medio','Mechas largo','Corte senora')"
        )
        conexion.commit()


@pytest.fixture
def conversacion(api_module, client, monkeypatch, salon_que_habla):  # noqa: F811
    """Manda mensajes por el webhook y devuelve lo que responde el asistente."""
    from backend import messaging, whatsapp

    dichos = []
    listas = []

    async def _texto(*, text="", **kwargs):
        dichos.append(text)
        return True

    async def _lista(*, body="", sections=None, **kwargs):
        listas.append(body)
        dichos.append("[LISTA] " + body)
        return True

    async def _botones(*, body="", **kwargs):
        dichos.append(body)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", _texto)
    monkeypatch.setattr(messaging, "_send_whatsapp_list", _lista)
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", _botones)
    whatsapp._wa_clear_flow("demo", TELEFONO)

    def enviar(texto):
        marca = len(dichos)
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id="demo", phone_number_id=NUMERO, from_number=TELEFONO,
            incoming_text=texto, interactive_id="", request=None,
        ))
        return dichos[marca:]

    enviar.listas = listas
    yield enviar
    whatsapp._wa_clear_flow("demo", TELEFONO)


def test_pedir_cita_pregunta_no_lista(conversacion, monkeypatch, api_module):  # noqa: F811
    """"Agendar cita" tiene que abrir una conversacion, no un listado."""
    from backend import whatsapp

    respuestas = conversacion("Agendar cita")
    assert respuestas, "el asistente se quedo callado"
    assert not any(r.startswith("[LISTA]") for r in respuestas), (
        "se ha mandado una lista y el salon no las quiere: %r" % respuestas
    )
    assert "?" in " ".join(respuestas), "tiene que preguntarle algo: %r" % respuestas
    assert whatsapp._wa_get_flow("demo", TELEFONO).flow == "booking_service"


def test_pregunta_lo_que_falta_y_luego_resuelve(conversacion, monkeypatch, api_module):  # noqa: F811
    """El caso que describio el salon: "mechas" -> "¿como lo tienes de largo?"."""
    from backend import intents, whatsapp

    respuestas_modelo = [
        {"servicio": "", "pregunta": "¿Cómo tienes el pelo de largo?", "opciones": []},
        {"servicio": "Mechas medio", "pregunta": "", "opciones": []},
    ]

    def _resolver(cliente_id, dicho, **kwargs):
        return respuestas_modelo.pop(0) if respuestas_modelo else None

    monkeypatch.setattr(intents, "resolver_servicio", _resolver)

    conversacion("Agendar cita")
    dice = conversacion("quiero mechas")
    assert any("de largo" in r for r in dice), "no pregunto por el largo: %r" % dice

    dice = conversacion("por los hombros")
    assert any("día" in r or "dia" in r for r in dice), (
        "con el largo ya dicho tenia que pasar al dia: %r" % dice
    )
    flujo = whatsapp._wa_get_flow("demo", TELEFONO)
    assert flujo.servicio == "Mechas medio"
    assert flujo.flow == "booking_date"


def test_junta_lo_que_dice_en_varios_mensajes(conversacion, monkeypatch, api_module):  # noqa: F811
    """"mechas" y "por los hombros" solo tienen sentido juntos."""
    from backend import intents, whatsapp

    vistos = []

    def _resolver(cliente_id, dicho, **kwargs):
        vistos.append(dicho)
        return {"servicio": "", "pregunta": "¿Y de largo?", "opciones": []}

    monkeypatch.setattr(intents, "resolver_servicio", _resolver)
    conversacion("Agendar cita")
    conversacion("quiero mechas")
    conversacion("por los hombros")
    assert "mechas" in vistos[-1] and "hombros" in vistos[-1], (
        "el resolutor tiene que ver todo lo dicho, no solo el ultimo mensaje: %r" % vistos
    )


def test_si_el_modelo_no_responde_no_se_queda_colgada(conversacion, monkeypatch, api_module):  # noqa: F811
    """Sin modelo se vuelve a las listas: quedarse sin respuesta no es opcion."""
    from backend import intents

    monkeypatch.setattr(intents, "resolver_servicio", lambda *a, **k: None)
    conversacion("Agendar cita")
    dice = conversacion("quiero algo bonito")
    assert any(r.startswith("[LISTA]") for r in dice), (
        "sin modelo hay que caer a las listas de siempre: %r" % dice
    )


def test_los_huecos_se_dicen_no_se_listan(api_module, client, monkeypatch):  # noqa: F811
    """Tres o cuatro horas en una frase, no veinte botones."""
    from backend import agenda, messaging, whatsapp

    dichos = []

    async def _texto(*, text="", **kwargs):
        dichos.append(text)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", _texto)

    async def _huecos(*a, **k):
        horas = ["09:00", "09:30", "10:00", "11:00", "12:00", "13:00", "17:00", "18:00"]
        return (horas, horas)

    monkeypatch.setattr(agenda, "_employee_slot_sets_for_day", _huecos)
    monkeypatch.setattr(agenda, "_public_slot_sets_for_day", _huecos)

    ok = asyncio.run(whatsapp._wa_ofrecer_huecos_hablando(
        cliente_id="demo", phone_number_id="p", to_number=TELEFONO,
        fecha_iso="2026-09-10", fecha_humana="jueves 10 de septiembre",
    ))
    assert ok
    texto = dichos[-1]
    assert texto.count(":") <= 5, "le esta recitando la agenda entera: %r" % texto
    assert "09:00" in texto and "18:00" in texto, (
        "las horas ofrecidas tienen que repartirse por el dia: %r" % texto
    )


def test_dia_completo_ofrece_llamar(api_module, client, monkeypatch):  # noqa: F811
    """Un dia sin huecos es una cita a punto de perderse."""
    from backend import agenda, clients, messaging, whatsapp

    config = clients._get_client_config("demo")
    previo = dict(config.get("contacto") or {})
    config.setdefault("contacto", {})["telefono"] = "966 670 924"
    dichos = []

    async def _texto(*, text="", **kwargs):
        dichos.append(text)
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", _texto)

    async def _sin_huecos(*a, **k):
        return (["09:00"], [])

    monkeypatch.setattr(agenda, "_employee_slot_sets_for_day", _sin_huecos)
    monkeypatch.setattr(agenda, "_public_slot_sets_for_day", _sin_huecos)
    try:
        ok = asyncio.run(whatsapp._wa_ofrecer_huecos_hablando(
            cliente_id="demo", phone_number_id="p", to_number=TELEFONO,
            fecha_iso="2026-09-10", fecha_humana="jueves 10 de septiembre",
        ))
        assert ok is False
        assert "966 670 924" in dichos[-1], "no le ofrecio llamar: %r" % dichos[-1]
    finally:
        config["contacto"] = previo


def test_por_defecto_nadie_cambia(api_module, client):  # noqa: F811
    """Los demas negocios siguen con sus listas mientras no lo pidan."""
    from backend import clients, whatsapp

    config = clients._get_client_config("demo")
    assert whatsapp._wa_modo_conversacional(config) is False
    assert whatsapp._wa_modo_conversacional({"booking": {"estilo": "guiado"}}) is False
    assert whatsapp._wa_modo_conversacional({"booking": {"estilo": "conversacional"}}) is True


def test_se_elige_desde_el_portal(client, api_module):  # noqa: F811
    """El negocio lo cambia solo, sin que nadie toque el config a mano."""
    from test_crm_light import portal_cookies  # noqa: F401

    import test_crm_light

    email = "estilo-%s@example.com" % __import__("uuid").uuid4().hex[:8]
    api_module._create_user(email=email, password="estilo-test-123", role="client",
                            display_name="Estilo", cliente_id="demo")
    login = client.post("/auth/login", json={"email": email, "password": "estilo-test-123"})
    cookies = {"vantelia_portal_session": login.cookies["vantelia_portal_session"]}

    from backend import clients, whatsapp

    try:
        vista = client.get("/auth/app/tone", cookies=cookies).json()
        assert vista["reserva"] == "guiado", "por defecto, listas"

        guardado = client.put("/auth/app/tone", cookies=cookies, json={
            "estilo": "cercano", "emojis": "muchos", "tratamiento": "tu",
            "notas": "", "reserva": "conversacional",
        })
        assert guardado.status_code == 200, guardado.text
        assert guardado.json()["reserva"] == "conversacional"
        assert whatsapp._wa_modo_conversacional(clients._get_client_config("demo")) is True
    finally:
        client.put("/auth/app/tone", cookies=cookies, json={
            "estilo": "", "emojis": "", "tratamiento": "", "notas": "", "reserva": "guiado",
        })
