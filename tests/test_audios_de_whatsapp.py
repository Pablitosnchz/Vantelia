# -*- coding: utf-8 -*-
"""Escuchar las notas de voz que manda la clienta.

Mucha gente no escribe: manda un audio. El asistente contestaba "puedes contarme
tu consulta por escrito" y ahi moria la conversacion. Lo pregunto un salon el
primer dia.

El texto transcrito entra por el MISMO camino que uno escrito, asi que todo lo
demas -coger la cita, cancelarla, los precios- funciona sin tocar nada.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


def test_sin_clave_no_se_intenta(api_module, monkeypatch):  # noqa: F811
    """Sin OpenAI no se escucha nada, y no se rompe: se pide por escrito."""
    import asyncio

    from backend import settings, wa_audio

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    assert wa_audio.activado() is False
    assert asyncio.run(wa_audio.escuchar("demo", "media_123")) is None


def test_se_puede_apagar(api_module, monkeypatch):  # noqa: F811
    """Un negocio (o el despliegue entero) puede no querer transcribir."""
    from backend import settings, wa_audio

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-de-prueba")
    monkeypatch.setenv("WHATSAPP_AUDIO_ENABLED", "false")
    assert wa_audio.activado() is False
    monkeypatch.setenv("WHATSAPP_AUDIO_ENABLED", "true")
    assert wa_audio.activado() is True


def test_un_audio_ilegible_no_tumba_el_canal(api_module, monkeypatch):  # noqa: F811
    """Si Meta falla o el audio no se entiende, la clienta recibe respuesta igual."""
    import asyncio

    from backend import settings, wa_audio

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-de-prueba")

    async def revienta(*args, **kwargs):
        raise RuntimeError("Meta dice que no")

    monkeypatch.setattr(wa_audio, "_bajar_de_whatsapp", revienta)
    assert asyncio.run(wa_audio.escuchar("demo", "media_123")) is None


def test_el_texto_transcrito_avisa_de_que_venia_en_audio(api_module):  # noqa: F811
    """Un nombre mal transcrito crea una cita a nombre de otra persona.

    Por eso el aviso pide confirmar por escrito lo que no puede equivocarse.
    """
    from backend import wa_audio

    assert "confirm" in wa_audio.AVISO_DE_AUDIO.lower()
    assert "numero de reserva" in wa_audio.AVISO_DE_AUDIO


def test_el_webhook_entiende_los_audios(api_module):  # noqa: F811
    """El tipo `audio` deja de caer en "esto no es texto"."""
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp)
    assert 'message_type == "audio"' in fuente
    assert "wa_audio.escuchar" in fuente
