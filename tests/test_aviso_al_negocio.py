# -*- coding: utf-8 -*-
"""Cuando alguien pide una persona, el negocio se entera.

POR QUE EXISTE
--------------
El asistente ya sabia callarse al pedirle hablar con una persona, pero nadie
avisaba al negocio: la conversacion se quedaba esperando en el panel y la clienta
esperando delante del movil. Estaba escrito como pendiente en el repo desde
ago-2026 ("no hay aviso al negocio; hoy hay que estar mirando el panel").

Con un salon que mira el panel a ratos se nota poco. Con un hotel que no lo mira
nunca, es la diferencia entre un asistente y un contestador: es lo que faltaba
para poder ponerlo delante de un cliente que no esta encima.

Reglas que se vigilan aqui: se avisa una sola vez por conversacion, se puede
apagar por negocio, y NUNCA rompe la conversacion aunque el email falle.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CID = "demo"


@pytest.fixture
def correos(api_module, monkeypatch):  # noqa: F811
    """Captura los emails en vez de mandarlos."""
    from backend import appstate, avisos, clients, emailing

    enviados = []
    monkeypatch.setattr(emailing, "_send_client_email",
                        lambda cid, to, subject, text, html="", reply_to=None:
                        enviados.append({"to": to, "subject": subject, "text": text}) or "ok")
    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "nombre": "Peluqueria Demo", "contacto": {"email": "salon@example.com"}})
    appstate.AVISOS_ENVIADOS = {}
    return enviados


def test_se_avisa_con_lo_que_ha_escrito(api_module, correos):  # noqa: F811
    from backend import avisos

    assert avisos.pide_una_persona(
        CID, session_id="wa_1", de_quien="34600111222",
        mensaje="quiero hablar con una persona por favor")
    assert len(correos) == 1
    aviso = correos[0]
    assert aviso["to"] == "salon@example.com"
    assert "34600111222" in aviso["text"]
    assert "persona" in aviso["text"].lower()


def test_no_se_avisa_veinte_veces_por_la_misma_conversacion(api_module, correos):  # noqa: F811
    """Veinte mensajes seguidos no pueden ser veinte correos."""
    from backend import avisos

    for _ in range(5):
        avisos.pide_una_persona(CID, session_id="wa_2", de_quien="34600111222",
                                mensaje="ponme con alguien")
    assert len(correos) == 1


def test_conversaciones_distintas_avisan_por_separado(api_module, correos):  # noqa: F811
    from backend import avisos

    avisos.pide_una_persona(CID, session_id="wa_3", de_quien="34600111222", mensaje="hola")
    avisos.pide_una_persona(CID, session_id="wa_4", de_quien="34600333444", mensaje="hola")
    assert len(correos) == 2


def test_el_negocio_puede_apagarlo(api_module, monkeypatch, correos):  # noqa: F811
    from backend import avisos, clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"email": "salon@example.com"}, "avisos": {"pedir_persona": False}})
    assert not avisos.pide_una_persona(CID, session_id="wa_5", de_quien="600", mensaje="hola")
    assert correos == []


def test_esta_encendido_por_defecto(api_module, monkeypatch):  # noqa: F811
    """Enterarse es lo de serie: sin la seccion en config, se avisa."""
    from backend import avisos, clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {"contacto": {}})
    assert avisos.esta_activado(CID)


def test_sin_email_no_se_inventa_destinatario(api_module, monkeypatch, correos):  # noqa: F811
    from backend import avisos, clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {"contacto": {"email": ""}})
    monkeypatch.setattr(avisos, "_correo_del_negocio", lambda cid, config=None: "")
    assert not avisos.pide_una_persona(CID, session_id="wa_6", de_quien="600", mensaje="hola")
    assert correos == []


def test_si_el_email_falla_la_conversacion_sigue(api_module, monkeypatch, correos):  # noqa: F811
    """Quedarse sin avisar es malo; tumbar la conversacion de la clienta, peor."""
    from backend import avisos, emailing

    def revienta(*a, **k):
        raise RuntimeError("smtp caido")

    monkeypatch.setattr(emailing, "_send_client_email", revienta)
    assert avisos.pide_una_persona(CID, session_id="wa_7", de_quien="600", mensaje="hola") is False


def test_whatsapp_avisa_al_pasar_a_una_persona(api_module):  # noqa: F811
    """El aviso tiene que estar ENCHUFADO, no solo existir."""
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._handle_whatsapp_message)
    assert "avisos.pide_una_persona" in fuente
