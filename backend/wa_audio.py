# -*- coding: utf-8 -*-
"""Escuchar los audios que manda la clienta por WhatsApp.

POR QUE EXISTE
--------------
Mucha gente no escribe: manda una nota de voz. Hasta ahora el asistente contestaba
"puedes contarme tu consulta por escrito" y ahi se acababa la conversacion, o el
negocio tenia que oirlo y contestar a mano. Un salon lo pregunto el primer dia.

COMO FUNCIONA
-------------
WhatsApp no manda el audio: manda un identificador. Hay que pedirle la URL a Meta,
descargar el fichero con el token del negocio y transcribirlo. El texto entra por
el MISMO camino que si lo hubiera escrito, asi que todo lo demas -coger la cita,
cancelarla, los precios- funciona igual sin tocar nada.

LO QUE NO SE FIA DE UNA TRANSCRIPCION
-------------------------------------
Un nombre o un numero de reserva mal transcritos crean una cita a nombre de otra
persona o cancelan la que no es. Por eso `AVISO_DE_AUDIO` acompanya al texto: el
asistente puede usarlo para conversar, pero confirma por escrito lo que no puede
equivocarse.

COSTE Y APAGADO
---------------
Se transcribe con OpenAI (unos 0,006 $ por minuto: un audio de 30 segundos son
0,3 centimos). Se apaga con `WHATSAPP_AUDIO_ENABLED=false`, y sin clave de OpenAI
ni token de WhatsApp se comporta como antes.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import httpx

from backend import settings

# Un audio mas largo que esto casi nunca es una consulta: es alguien contando su
# vida o un reenvio. Se corta para no pagar de mas ni hacer esperar.
MAX_SEGUNDOS = int(os.getenv("WHATSAPP_AUDIO_MAX_SECONDS", "120"))
MAX_BYTES = int(os.getenv("WHATSAPP_AUDIO_MAX_BYTES", str(16 * 1024 * 1024)))
MODELO = os.getenv("WHATSAPP_AUDIO_MODEL", "gpt-4o-mini-transcribe")

# Lo que se le dice al asistente junto al texto transcrito. No lo lee la clienta.
AVISO_DE_AUDIO = (
    "[La clienta ha mandado un AUDIO y esto es la transcripcion, que puede tener "
    "errores. Uala para entenderla, pero si de ahi sale un nombre, un numero de "
    "reserva, un telefono o un email, repiteselo y pidele que te lo confirme por "
    "escrito antes de darlo por bueno.]"
)


def activado() -> bool:
    """¿Este despliegue escucha los audios?"""
    if str(os.getenv("WHATSAPP_AUDIO_ENABLED", "true")).strip().lower() in ("0", "false", "no"):
        return False
    return bool(settings.OPENAI_API_KEY)


async def _bajar_de_whatsapp(media_id: str, token: str) -> Tuple[bytes, str]:
    """El fichero de audio, tal cual lo guarda Meta. (bytes, tipo)."""
    cabeceras = {"Authorization": "Bearer %s" % token}
    async with httpx.AsyncClient(timeout=20.0) as cliente:
        ficha = await cliente.get(
            "https://graph.facebook.com/v22.0/%s" % media_id, headers=cabeceras,
        )
        ficha.raise_for_status()
        datos = ficha.json()
        url = str(datos.get("url") or "")
        tipo = str(datos.get("mime_type") or "audio/ogg")
        tamano = int(datos.get("file_size") or 0)
        if not url:
            raise ValueError("Meta no ha dado la URL del audio")
        if tamano and tamano > MAX_BYTES:
            raise ValueError("audio demasiado grande (%d bytes)" % tamano)
        # La URL de descarga TAMBIEN pide el token: sin el devuelve 401.
        fichero = await cliente.get(url, headers=cabeceras)
        fichero.raise_for_status()
        return fichero.content, tipo


def _transcribir(audio: bytes, tipo: str) -> str:
    from openai import OpenAI

    extension = "ogg"
    if "mp4" in tipo or "m4a" in tipo:
        extension = "m4a"
    elif "mpeg" in tipo or "mp3" in tipo:
        extension = "mp3"
    elif "wav" in tipo:
        extension = "wav"

    cliente = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)
    try:
        respuesta = cliente.audio.transcriptions.create(
            model=MODELO,
            file=("nota.%s" % extension, audio),
            language="es",
        )
    except Exception:  # noqa: BLE001 - modelo no disponible en esta cuenta
        respuesta = cliente.audio.transcriptions.create(
            model="whisper-1",
            file=("nota.%s" % extension, audio),
            language="es",
        )
    return str(getattr(respuesta, "text", "") or "").strip()


async def escuchar(cliente_id: str, media_id: str) -> Optional[str]:
    """Lo que dice la nota de voz. None si no se ha podido escuchar.

    Nunca lanza: si algo falla, quien llama sigue con el mensaje de siempre
    ("escribemelo") y la clienta no se queda sin respuesta.
    """
    if not (activado() and media_id):
        return None
    try:
        from backend import messaging

        token = messaging._whatsapp_access_token_for_client(cliente_id)
        if not token:
            return None
        audio, tipo = await _bajar_de_whatsapp(media_id, token)
        if not audio:
            return None
        import asyncio

        texto = await asyncio.to_thread(_transcribir, audio, tipo)
        if not texto:
            return None
        settings.logger.info(
            "[wa-audio] %s: transcritos %d caracteres de %d bytes",
            cliente_id, len(texto), len(audio),
        )
        return texto[:1200]
    except Exception as exc:  # noqa: BLE001 - un audio ilegible no puede tumbar el canal
        settings.logger.warning("[wa-audio] no se ha podido escuchar (%s): %s", cliente_id, exc)
        return None
