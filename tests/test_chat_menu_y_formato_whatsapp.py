"""Dos ajustes pedidos por el hotel Cap Rocat (ago 2026), ambos genericos:

1. **Menu de opciones opt-out** (`config['chat_menu']['enabled']`): un negocio que
   solo quiere respuestas directas puede apagar la lista de opciones; al saludar
   responde con su bienvenida y punto. Por defecto el menu sigue encendido, que es
   como funciona para todos los demas.
2. **Markdown -> formato WhatsApp**: WhatsApp marca negrita con UN asterisco, asi
   que el `**negrita**` del modelo se veia como "*negrita*" con los asteriscos a
   la vista. La traduccion vive en el punto unico de salida de texto a WhatsApp.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401


def _set_menu(client, portal_cookies, enabled: bool):
    res = client.put("/auth/app/chat-menu", cookies=portal_cookies, json={"enabled": enabled})
    assert res.status_code == 200, res.text
    return res.json()


def _chat(client, mensaje: str):
    res = client.post(
        "/chat",
        headers={"Origin": "http://testserver"},
        json={"cliente_id": "demo", "mensaje": mensaje, "session_id": ""},
    )
    assert res.status_code == 200, res.text
    return res.json()


# --- Menu opt-out ----------------------------------------------------------


def test_menu_enabled_by_default(api_module):
    from backend import chat

    assert chat._menu_enabled("demo") is True
    # Un tenant que no existe no revienta y mantiene el comportamiento por defecto.
    assert chat._menu_enabled("no-existe") is True


def test_greeting_shows_menu_when_enabled(api_module, client, portal_cookies):
    body = _chat(client, "hola")
    assert body["intent"] == "menu"
    assert body["quick_actions"]


def test_greeting_without_menu_uses_bienvenida(api_module, client, portal_cookies):
    from backend import chat, clients

    try:
        _set_menu(client, portal_cookies, False)
        assert chat._menu_enabled("demo") is False

        body = _chat(client, "hola")
        assert body["intent"] == "greeting"
        assert body["quick_actions"] == []
        bienvenida = str(clients._get_client_config("demo").get("bienvenida") or "").strip()
        assert body["respuesta"] == bienvenida
        assert "Preguntas frecuentes" not in body["respuesta"]

        # "menu" escrito a mano tampoco resucita la lista.
        assert _chat(client, "menu")["intent"] == "greeting"
    finally:
        _set_menu(client, portal_cookies, True)


def test_menu_flag_survives_config_reload(api_module, client, portal_cookies):
    from backend import chat, clients

    try:
        _set_menu(client, portal_cookies, False)
        raw = clients._serialize_client_config(clients._get_client_config("demo"))
        reloaded = clients._normalize_client_config("demo", raw)
        assert reloaded.get(chat.MENU_CONFIG_SECTION, {}).get("enabled") is False
    finally:
        _set_menu(client, portal_cookies, True)


def test_whatsapp_menu_sender_sends_plain_text_when_disabled(api_module, client, portal_cookies):
    """El corte esta en `_wa_send_main_menu`, que es por donde pasan TODOS los
    puntos que abren el menu en WhatsApp."""
    import asyncio

    from backend import messaging, whatsapp

    enviados = []

    async def fake_text(*, cliente_id, phone_number_id, to_number, text):
        enviados.append(("text", text))
        return True

    async def fake_list(**kwargs):
        enviados.append(("list", kwargs.get("body", "")))
        return True

    original_text, original_list = messaging._send_whatsapp_text, messaging._send_whatsapp_list
    messaging._send_whatsapp_text, messaging._send_whatsapp_list = fake_text, fake_list
    try:
        _set_menu(client, portal_cookies, False)
        asyncio.run(
            whatsapp._wa_send_main_menu(
                cliente_id="demo", phone_number_id="123", to_number="34600000000",
                nombre_empresa="Demo", booking_enabled=True, greeting=True,
            )
        )
        assert [kind for kind, _ in enviados] == ["text"]

        enviados.clear()
        _set_menu(client, portal_cookies, True)
        asyncio.run(
            whatsapp._wa_send_main_menu(
                cliente_id="demo", phone_number_id="123", to_number="34600000000",
                nombre_empresa="Demo", booking_enabled=True, greeting=True,
            )
        )
        assert [kind for kind, _ in enviados] == ["list"]
    finally:
        messaging._send_whatsapp_text, messaging._send_whatsapp_list = original_text, original_list
        _set_menu(client, portal_cookies, True)


# --- Markdown -> WhatsApp --------------------------------------------------


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("**Doble Fortaleza:** Habitacion", "*Doble Fortaleza:* Habitacion"),
        ("__Spa__ abierto", "*Spa* abierto"),
        ("### Nuestros servicios", "*Nuestros servicios*"),
        ("* Sea Club\n* La Fortaleza", "• Sea Club\n• La Fortaleza"),
        ("[Reservar](https://caprocat.com)", "Reservar: https://caprocat.com"),
        ("Usa `codigo` aqui", "Usa codigo aqui"),
        # Idempotente: lo que ya viene en formato WhatsApp no se toca.
        ("*Ya en negrita*", "*Ya en negrita*"),
        ("Texto sin formato", "Texto sin formato"),
        ("", ""),
    ],
)
def test_markdown_to_whatsapp(api_module, entrada, esperado):
    from backend import textnorm

    assert textnorm._markdown_to_whatsapp(entrada) == esperado


def test_whatsapp_chunks_translate_markdown(api_module):
    """La traduccion tiene que estar en el punto de salida, no en cada llamada."""
    from backend import messaging

    chunks = messaging._whatsapp_chunks("Le presento el **Spa Cap Rocat** y el **Sea Club**.")
    assert chunks == ["Le presento el *Spa Cap Rocat* y el *Sea Club*."]
    assert "**" not in chunks[0]


def test_el_negocio_puede_quitar_opciones_del_menu(api_module, client):  # noqa: F811
    """Las tres base son una sugerencia, no una imposicion.

    Un salon pidio quitar "Preguntas frecuentes" de su menu: se hace desde su
    portal (`chat_menu.ocultas`), no tocando el codigo, y sin afectar a los demas
    negocios.
    """
    from backend import settings

    base = {"booking": {"enabled": True}}
    assert "Preguntas frecuentes" in settings._resolve_widget_starters(base)

    suyo = dict(base, chat_menu={"ocultas": ["preguntas frecuentes"]})
    opciones = settings._resolve_widget_starters(suyo)
    assert "Preguntas frecuentes" not in opciones
    assert "Agendar cita" in opciones, "no puede llevarse por delante el resto"


def test_las_opciones_del_menu_no_llevan_coletilla(api_module, client):  # noqa: F811
    """"Agendar cita / Reserva tu cita en pocos pasos" es decir dos veces lo mismo."""
    from backend import whatsapp

    for _accion, descripcion in whatsapp._WA_MENU_ACCIONES.values():
        assert descripcion == "", "las filas del menu no llevan subtitulo"
