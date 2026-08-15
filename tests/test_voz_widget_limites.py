"""La voz del widget de un cliente no puede usar los limites de la demo publica.

Caso real (ago 2026): en la web de una peluqueria, un visitante que abria y
cerraba el microfono un par de veces se topaba con "Demasiados intentos, espera
un minuto". El endpoint del widget reutilizaba el limite de `/demo/`, pensado
para una pagina publica anonima donde hay que acotar el gasto de minutos.

La demo sigue protegida; el widget de un negocio real es mas holgado.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def test_el_widget_tiene_su_propio_limite_y_es_mayor(api_module):
    from backend import settings

    assert settings.WIDGET_VOICE_RATE_LIMIT > settings.DEMO_VOICE_RATE_LIMIT
    assert settings.WIDGET_VOICE_RATE_LIMIT >= 10


def test_la_demo_publica_sigue_acotada(api_module):
    """Cualquiera con el enlace puede gastar minutos: ahi el limite es estrecho."""
    from backend import settings

    assert settings.DEMO_VOICE_RATE_LIMIT <= 5


def test_el_widget_permite_llamadas_mas_largas_que_la_demo(api_module):
    from backend import settings

    assert settings.WIDGET_VOICE_MAX_SECONDS > settings.DEMO_VOICE_MAX_SECONDS


def test_cada_endpoint_usa_el_limite_que_le_toca(api_module):
    """Si alguien vuelve a cruzar los limites, que salte aqui y no en la web de un cliente."""
    import inspect

    from backend.routers import ui_pages

    fuente = inspect.getsource(ui_pages)
    sesion_widget = fuente.split("async def widget_voice_session")[1].split("async def")[0]
    assert "WIDGET_VOICE_RATE_LIMIT" in sesion_widget
    assert "DEMO_VOICE_RATE_LIMIT" not in sesion_widget

    sesion_demo = fuente.split("async def demo_voice_session")[1].split("async def")[0]
    assert "DEMO_VOICE_RATE_LIMIT" in sesion_demo
