"""El menu de WhatsApp refleja lo que el negocio configura en el panel.

Estaba escrito a fuego con nueve opciones genericas (recomendar, comparar,
estimar precio...) mientras el negocio configuraba sus preguntas sugeridas en el
panel y solo se aplicaban al widget web. Un cliente veia en su panel tres
sugerencias y sus clientes recibian nueve opciones que no habia elegido.

El arreglo se quedo a medias: las sugerencias entraban, pero DEBAJO de cuatro
filas de agenda que se seguian anteponiendo. Un salon con tres sugerencias
recibia seis opciones, y ninguna de las pantallas (panel, chat web, WhatsApp)
coincidia con las otras. Ahora la lista sale entera de `chat.menu_entries`.

Lo que se valida:
- Que el menu es EXACTAMENTE lo configurado, sin anadidos nuestros.
- Que una sugerencia que coincide con una accion conocida ("Agendar cita") abre
  su flujo guiado en vez de irse a la IA.
- Que al pulsar una sugerencia se procesa su texto COMPLETO, no el titulo
  recortado a 24 caracteres que impone WhatsApp.
- Que sin ninguna opcion no se manda una lista vacia (WhatsApp la rechaza).
"""
from __future__ import annotations

from test_booking_exhaustive import api_module, client  # noqa: F401


def _filas(secciones):
    return secciones[0]["rows"]


def _con_starters(monkeypatch, textos):
    from backend import settings

    monkeypatch.setattr(
        settings, "_resolve_widget_starters", lambda config, booking_enabled=None: list(textos)
    )


def test_el_menu_es_exactamente_lo_configurado(api_module, monkeypatch):
    from backend import whatsapp

    _con_starters(monkeypatch, [
        "Agendar cita",
        "¿Que tratamientos de color haceis?",
        "¿Donde estais y como aparco?",
    ])
    titulos = [f["title"] for f in _filas(whatsapp._wa_main_menu_sections(True, "demo"))]

    assert len(titulos) == 3, "no se anade ninguna opcion que el negocio no haya puesto"
    assert titulos[0] == "Agendar cita"
    for generica in ("⭐ Recomendar", "⚖️ Comparar", "💶 Estimar precio", "Ver disponibilidad"):
        assert generica not in titulos


def test_una_sugerencia_conocida_abre_su_flujo_guiado(api_module, monkeypatch):
    """"Agendar cita" no puede tratarse como texto libre: abre el flujo de reserva."""
    from backend import whatsapp

    _con_starters(monkeypatch, ["Agendar cita", "¿Donde estais?"])
    filas = _filas(whatsapp._wa_main_menu_sections(True, "demo"))
    assert filas[0]["id"] == "menu_agendar"
    assert filas[1]["id"].startswith("menu_starter_")


def test_sin_ninguna_opcion_no_se_manda_una_lista_vacia(api_module, monkeypatch):
    """Una lista interactiva sin filas es un mensaje invalido: WhatsApp lo rechaza
    entero y el cliente se queda sin respuesta. Se cae al saludo llano."""
    from backend import messaging, whatsapp

    _con_starters(monkeypatch, [])
    assert _filas(whatsapp._wa_main_menu_sections(True, "demo")) == []

    enviados = {"texto": 0, "lista": 0}

    async def _texto(**kwargs):
        enviados["texto"] += 1
        return True

    async def _lista(**kwargs):
        enviados["lista"] += 1
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", _texto)
    monkeypatch.setattr(messaging, "_send_whatsapp_list", _lista)

    import asyncio

    asyncio.run(whatsapp._wa_send_main_menu(
        cliente_id="demo", phone_number_id="1", to_number="34600000000",
        nombre_empresa="Demo", booking_enabled=True, greeting=True,
    ))
    assert enviados == {"texto": 1, "lista": 0}


def test_los_titulos_respetan_el_limite_de_whatsapp(api_module, monkeypatch):
    """WhatsApp corta a 24 caracteres: si nos pasamos, rechaza el mensaje entero."""
    from backend import whatsapp

    _con_starters(monkeypatch, ["Una pregunta larguisima que no cabe de ninguna manera en el titulo"])
    for fila in _filas(whatsapp._wa_main_menu_sections(False, "demo")):
        assert len(fila["title"]) <= whatsapp._WA_ROW_TITLE_MAX
        assert len(fila["description"]) <= whatsapp._WA_ROW_DESC_MAX


def test_al_pulsar_una_sugerencia_se_usa_su_texto_completo(api_module, monkeypatch):
    """El titulo va recortado; lo que se manda a la IA debe ser la pregunta entera."""
    from backend import whatsapp

    pregunta = "¿Que tratamientos de color haceis y cuanto duran?"
    _con_starters(monkeypatch, ["Agendar cita", pregunta])
    assert whatsapp._wa_starter_message("demo", "menu_starter_1", True) == pregunta


def test_id_manipulado_no_rompe_el_canal(api_module, monkeypatch):
    from backend import whatsapp

    _con_starters(monkeypatch, ["Una"])
    assert whatsapp._wa_starter_message("demo", "menu_starter_99", True) == ""
    assert whatsapp._wa_starter_message("demo", "menu_starter_x", True) == ""


def test_el_menu_nunca_supera_las_10_filas(api_module, monkeypatch):
    """Limite duro de WhatsApp para listas interactivas."""
    from backend import whatsapp

    _con_starters(monkeypatch, [f"Pregunta numero {i}" for i in range(15)])
    assert len(_filas(whatsapp._wa_main_menu_sections(True, "demo"))) <= whatsapp._WA_MAX_FILAS
