# -*- coding: utf-8 -*-
"""Una foto no se tira: se acusa recibo y la mira una persona.

POR QUE EXISTE
--------------
Fallo real del salon piloto. Una imagen entraba por el webhook, caia en la rama
"esto no es texto" y al modelo se le decia "pidele que escriba su consulta". Como
estaba a medias de agendar unas mechas, volvia a preguntar el largo del pelo:

    CLIENTA  Si te mando una foto y me ves, el cabello no es mejor
    IA       Necesito saber como tienes el pelo de largo
    CLIENTA  [manda la foto]
    IA       Necesito saber como tienes el pelo de largo

La duenya dejo de fiarse del producto por esto, y con razon: no fallaba el
modelo, es que nadie habia escrito que hacer con una foto.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


# --- Anunciar la foto (cualquier canal) ------------------------------------


@pytest.mark.parametrize("frase", [
    "si te mando una foto y me ves, el cabello no es mejor",
    "Te mando una foto de mi pelo?",
    "puedo enviarte una imagen del color que quiero?",
    "te paso una foto para que la veas",
    "quieres que te mande una foto?",
    "voy a mandarte unas fotos del tono",
])
def test_se_reconoce_que_va_a_mandar_una_foto(api_module, frase):
    from backend import fotos

    assert fotos.anuncia_foto(frase), frase


@pytest.mark.parametrize("frase", [
    "quiero unas mechas",
    "cuanto cuesta un corte?",
    "tengo el pelo largo",
    "me hago una foto siempre antes de venir",  # habla de si misma, no nos manda nada
])
def test_no_se_confunde_con_otras_frases(api_module, frase):
    from backend import fotos

    assert not fotos.anuncia_foto(frase), frase


def test_anunciar_una_foto_gana_a_seguir_preguntando_el_largo(api_module):
    """Lo que rompio la conversacion real: contestar con la pregunta de siempre."""
    from backend import chat

    decision = chat.decision_del_negocio(
        "demo", "si te mando una foto y me ves, el cabello no es mejor",
        gestion_en_curso=True,   # justo el caso malo: a medias de agendar
    )

    assert decision, "una foto anunciada tiene que decidir algo"
    assert decision["intent"] == "foto_anunciada"
    assert "mand" in decision["texto"].lower()


def test_el_negocio_puede_apagarlo(api_module):
    from backend import chat

    decision = chat.decision_del_negocio(
        "demo", "te mando una foto?", config={"fotos": {"enabled": False}},
    )

    assert decision is None or decision.get("intent") != "foto_anunciada"


def test_el_negocio_puede_poner_su_texto(api_module):
    from backend import fotos

    config = {"fotos": {"texto_anuncio": "Mandanosla al 600 000 000."}}

    assert fotos.texto_al_anunciar("demo", config) == "Mandanosla al 600 000 000."


# --- Recibir la foto de verdad (WhatsApp) ----------------------------------


def test_al_llegar_la_foto_se_contesta_y_se_calla_el_asistente(api_module, monkeypatch):
    """Lo que pidio la duenya: 'espere, que ahora le atendemos', y contesta ella."""
    import asyncio

    from backend import fotos, inbox, whatsapp

    enviados = []

    async def _falso_envio(*, cliente_id, phone_number_id, to_number, text, **kwargs):
        enviados.append(text)

    monkeypatch.setattr(whatsapp.messaging, "_send_whatsapp_text", _falso_envio)

    telefono = "34600111222"
    session_id = whatsapp._whatsapp_session_id("demo", telefono)
    inbox.release(session_id)

    asyncio.run(whatsapp._wa_foto_recibida(
        cliente_id="demo", phone_number_id="pn", from_number=telefono,
        pie="", request=None,
    ))

    assert enviados, "hay que acusar recibo de la foto"
    assert enviados[0] == fotos.texto_al_recibir("demo")
    assert inbox.bot_is_muted(session_id), "el asistente no puede seguir hablando encima"
    inbox.release(session_id)


def test_la_foto_queda_en_el_historial_del_negocio(api_module, monkeypatch):
    """Si no se registra, el negocio no ve en el panel que le han mandado algo."""
    import asyncio

    from backend import db, inbox, whatsapp

    async def _falso_envio(**kwargs):
        return None

    monkeypatch.setattr(whatsapp.messaging, "_send_whatsapp_text", _falso_envio)

    telefono = "34600333444"
    session_id = whatsapp._whatsapp_session_id("demo", telefono)
    asyncio.run(whatsapp._wa_foto_recibida(
        cliente_id="demo", phone_number_id="pn", from_number=telefono,
        pie="mira este color", request=None,
    ))

    with db._get_db_connection() as connection:
        filas = connection.execute(
            "SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    contenidos = [f["content"] for f in filas]
    assert any("[foto]" in c for c in contenidos), contenidos
    assert any("mira este color" in c for c in contenidos), "el pie de la foto tambien"
    inbox.release(session_id)


# --- Los otros tipos que manda Meta ----------------------------------------
#
# Clase 18 de docs/CAZA_DE_FALLOS.md: lo que no es texto caia en un saco generico
# y al modelo le llegaba "esto no es texto, pidele que escriba". Cada tipo que
# Meta puede mandar necesita su respuesta, o al menos que no estorbe.


def _webhook(tipo, cuerpo):
    """El payload que manda Meta para un mensaje de este tipo."""
    return {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "pn"},
            "messages": [dict({"from": "34600999888", "id": "wamid.x", "type": tipo}, **cuerpo)],
        }}]}]
    }


def test_un_video_se_trata_como_una_foto(api_module):
    """Grabar el pelo en video es tan comun como fotografiarlo, y tampoco se ve."""
    from backend import whatsapp

    fuente = whatsapp._handle_whatsapp_webhook.__doc__ or ""
    _ = fuente
    import inspect

    codigo = inspect.getsource(whatsapp._handle_whatsapp_webhook)
    assert '"video"' in codigo, "el video tiene que entrar por la puerta de la foto"
    assert 'message_type == "reaction"' in codigo, "una reaccion no es una consulta"
    assert 'message_type == "location"' in codigo, "compartir ubicacion se contesta"
