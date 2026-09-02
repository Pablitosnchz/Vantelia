# -*- coding: utf-8 -*-
"""Que hacer cuando una clienta manda -o anuncia- una foto.

POR QUE EXISTE
--------------
El asistente no ve fotos. Hasta ahora eso no estaba escrito en ninguna parte: una
imagen entraba por el webhook, caia en la rama "esto no es texto" y al modelo se
le decia *"pidele que escriba su consulta"*. Resultado real, en el salon piloto:

    CLIENTA  Si te mando una foto y me ves, el cabello no es mejor
    IA       Para agendarte las mechas necesito saber como tienes el pelo de largo
    CLIENTA  [manda la foto]
    IA       Necesito saber como tienes el pelo de largo

La duenya lo resumio bien: entiende que la IA no pueda leer una foto, pero
entonces lo que tiene que decir es *"mandala, la vemos y te contestamos"*, no
seguir preguntando. Mandar una foto es justo el momento en el que hace falta una
persona, no mas conversacion.

QUE HACE
--------
- **Anuncia** la foto ("te mando una foto?"): se responde que si, que la mande.
  Vale para cualquier canal, asi que vive en `chat.decision_del_negocio`.
- **Llega** la foto: se responde que ya se ha recibido y, si el negocio lo quiere,
  la conversacion pasa a manos humanas (`inbox.claim`) para que el asistente NO
  hable por encima de quien va a mirarla. El silencio caduca solo, como cualquier
  intervencion humana, asi que nadie se queda sin respuesta para siempre.

Se apaga por tenant con `config['fotos']['enabled'] = false`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from backend import textnorm

# Lo que escribe la clienta antes de mandarla. Sin tildes a proposito: se compara
# sobre texto ya normalizado (ver tests/test_patrones_sin_tilde.py).
_ANUNCIA_RE = re.compile(
    # Un verbo de mandar, en cualquier forma y con el pronombre delante o pegado
    # detras ("te mando", "mandarte", "quieres que te mande"), y una palabra de
    # foto poco despues.
    r"\b(?:mand\w*|envi\w*|pas(?:o|a|ar\w*|amos)|adjunt\w*)\b"
    r"[^.?!]{0,40}?\b(?:foto|fotos|fotografia|fotografias|imagen|imagenes|captura)\b"
)

DEFECTO_ANUNCIO = (
    "Claro que si, mandanosla por aqui. En cuanto la veamos te contestamos "
    "personalmente."
)
DEFECTO_RECIBIDA = (
    "Gracias, ya nos ha llegado tu foto. La miramos y te contestamos "
    "personalmente en un momento."
)


def _config(cliente_id: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if config is None:
        from backend import clients

        try:
            config = clients._get_client_config(cliente_id)
        except Exception:  # noqa: BLE001 - nunca romper una respuesta por esto
            return {}
    seccion = (config or {}).get("fotos")
    return seccion if isinstance(seccion, dict) else {}


def activo(cliente_id: str, config: Optional[Dict[str, Any]] = None) -> bool:
    """Encendido salvo que el negocio lo apague. Ignorar una foto nunca es lo correcto."""
    return bool(_config(cliente_id, config).get("enabled", True))


def anuncia_foto(texto: str) -> bool:
    """La clienta dice que va a mandar una foto (todavia no la ha mandado)."""
    return bool(_ANUNCIA_RE.search(textnorm._strip_accents(str(texto or "").lower())))


def texto_al_anunciar(cliente_id: str, config: Optional[Dict[str, Any]] = None) -> str:
    return str(_config(cliente_id, config).get("texto_anuncio") or DEFECTO_ANUNCIO).strip()


def texto_al_recibir(cliente_id: str, config: Optional[Dict[str, Any]] = None) -> str:
    return str(_config(cliente_id, config).get("texto_recibida") or DEFECTO_RECIBIDA).strip()


def pasa_a_humano(cliente_id: str, config: Optional[Dict[str, Any]] = None) -> bool:
    """Tras recibir una foto, callar al asistente y dejarla a una persona.

    Por defecto SI: quien manda una foto espera que alguien la mire, y que el
    asistente siga hablando solo estorba. El silencio caduca solo.
    """
    return bool(_config(cliente_id, config).get("pasar_a_humano", True))
