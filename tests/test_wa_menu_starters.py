"""El menu de WhatsApp refleja lo que el negocio configura en el panel.

Estaba escrito a fuego con nueve opciones genericas (recomendar, comparar,
estimar precio...) mientras el negocio configuraba sus preguntas sugeridas en
Tune AI y solo se aplicaban al widget web. Un cliente veia en su panel tres
sugerencias y sus clientes recibian nueve opciones que no habia elegido.

Lo que se valida:
- Que las sugerencias configuradas sustituyen al bloque generico.
- Que las acciones de agenda siguen apareciendo (abren flujos guiados propios,
  no son sugerencias) y no se duplican.
- Que al pulsar una sugerencia se procesa su texto COMPLETO, no el titulo
  recortado a 24 caracteres que impone WhatsApp.
- Que un negocio sin sugerencias propias mantiene el menu de siempre.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module, client  # noqa: F401


def _filas(secciones):
    return secciones[0]["rows"]


def test_las_sugerencias_del_negocio_sustituyen_al_bloque_generico(api_module, monkeypatch):
    from backend import settings, whatsapp

    monkeypatch.setattr(
        settings, "_resolve_widget_starters",
        lambda config, booking_enabled=None: [
            "Agendar cita",
            "¿Que tratamientos de color haceis?",
            "¿Donde estais y como aparco?",
        ],
    )
    filas = _filas(whatsapp._wa_main_menu_sections(True, "demo"))
    titulos = [f["title"] for f in filas]

    # Las genericas desaparecen...
    for generica in ("⭐ Recomendar", "⚖️ Comparar", "💶 Estimar precio"):
        assert generica not in titulos
    # ...y aparecen las suyas.
    assert "¿Que tratamientos de color hac" [:24] in titulos or any(
        t.startswith("¿Que tratamientos") for t in titulos
    )
    # Las acciones de agenda se mantienen y no se duplican con la sugerencia homonima.
    assert "📅 Agendar cita" in titulos
    assert titulos.count("Agendar cita") == 0


def test_sin_sugerencias_propias_se_mantiene_el_menu_de_siempre(api_module, monkeypatch):
    from backend import settings, whatsapp

    monkeypatch.setattr(settings, "_resolve_widget_starters", lambda config, booking_enabled=None: [])
    titulos = [f["title"] for f in _filas(whatsapp._wa_main_menu_sections(True, "demo"))]
    assert "💬 Preguntas frecuentes" in titulos
    assert "⭐ Recomendar" in titulos


def test_los_titulos_respetan_el_limite_de_whatsapp(api_module, monkeypatch):
    """WhatsApp corta a 24 caracteres: si nos pasamos, rechaza el mensaje entero."""
    from backend import settings, whatsapp

    monkeypatch.setattr(
        settings, "_resolve_widget_starters",
        lambda config, booking_enabled=None: ["Una pregunta larguisima que no cabe de ninguna manera en el titulo"],
    )
    for fila in _filas(whatsapp._wa_main_menu_sections(False, "demo")):
        assert len(fila["title"]) <= 24
        assert len(fila["description"]) <= 72


def test_al_pulsar_una_sugerencia_se_usa_su_texto_completo(api_module, monkeypatch):
    """El titulo va recortado; lo que se manda a la IA debe ser la pregunta entera."""
    from backend import settings, whatsapp

    pregunta = "¿Que tratamientos de color haceis y cuanto duran?"
    monkeypatch.setattr(
        settings, "_resolve_widget_starters",
        lambda config, booking_enabled=None: ["Agendar cita", pregunta],
    )
    assert whatsapp._wa_starter_message("demo", "menu_starter_1", True) == pregunta


def test_id_manipulado_no_rompe_el_canal(api_module, monkeypatch):
    from backend import settings, whatsapp

    monkeypatch.setattr(settings, "_resolve_widget_starters", lambda config, booking_enabled=None: ["Una"])
    assert whatsapp._wa_starter_message("demo", "menu_starter_99", True) == ""
    assert whatsapp._wa_starter_message("demo", "menu_starter_x", True) == ""


def test_el_menu_nunca_supera_las_10_filas(api_module, monkeypatch):
    """Limite duro de WhatsApp para listas interactivas."""
    from backend import settings, whatsapp

    monkeypatch.setattr(
        settings, "_resolve_widget_starters",
        lambda config, booking_enabled=None: [f"Pregunta numero {i}" for i in range(15)],
    )
    assert len(_filas(whatsapp._wa_main_menu_sections(True, "demo"))) <= 10
