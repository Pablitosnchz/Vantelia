# -*- coding: utf-8 -*-
"""Las respuestas por palabra clave, en el idioma de quien pregunta.

POR QUE EXISTE
--------------
El hotel Cap Rocat probó la demo y su única petición fue esta (18-sep-2026): «si el huésped envía un
mensaje en inglés, que la respuesta automática se envíe en el mismo idioma». Hasta entonces la
respuesta salía siempre en español, aunque la pregunta llegara en inglés.

Lo que se vigila:

- La versión en inglés que escribe el negocio sale TAL CUAL a quien escribe en inglés.
- Otro idioma (en Mallorca, sobre todo alemán) se traduce; si traducir falla, sale la inglesa y, si
  no la hay, la de siempre. Nadie se queda sin respuesta.
- Lo dudoso («spa?») sale en español, la lengua del negocio.
- El idioma se decide sin modelo y siempre igual.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401

ES = "Para reservas o información sobre el Spa, por favor llame al (+34) 971 74 78 78."
EN = "For Spa bookings or information, please call (+34) 971 74 78 78."


def _preparar(client, portal_cookies, reply_en=EN):
    res = client.put("/auth/app/keyword-rules/config", cookies=portal_cookies, json={"enabled": True})
    assert res.status_code == 200, res.text
    res = client.post("/auth/app/keyword-rules", cookies=portal_cookies, json={
        "label": "Spa", "keywords": ["spa", "masaje", "massage"], "reply": ES, "reply_en": reply_en,
        "match_mode": "any", "active": True})
    assert res.status_code == 200, res.text
    assert res.json()["reply_en"] == reply_en
    return res.json()


def _limpiar(client, portal_cookies):
    client.put("/auth/app/keyword-rules/config", cookies=portal_cookies, json={"enabled": False})
    for regla in client.get("/auth/app/keyword-rules", cookies=portal_cookies).json()["items"]:
        client.delete("/auth/app/keyword-rules/" + regla["id"], cookies=portal_cookies)


@pytest.mark.parametrize("mensaje, idioma", [
    ("Hola, ¿tenéis spa?", "es"),
    ("Do you have a spa?", "en"),
    ("Is there parking at the hotel?", "en"),
    ("Hola, do you have a spa?", "en"),
    ("Haben Sie ein Spa?", "de"),
    ("Bonjour, avez-vous un spa ?", "fr"),
    ("Vorrei prenotare un massaggio", "it"),
    ("Hebben jullie een spa?", "nl"),
    ("spa", ""),
    ("", ""),
])
def test_el_idioma_se_decide_sin_modelo(api_module, mensaje, idioma):
    from backend import keywords

    assert keywords.idioma_de(mensaje) == idioma


def test_en_ingles_sale_su_texto_en_ingles_y_en_espanol_el_de_siempre(
        api_module, client, portal_cookies, monkeypatch):
    from backend import keywords

    pedidas = []
    monkeypatch.setattr(keywords, "_traducir", lambda texto, idioma: pedidas.append(idioma) or "")
    try:
        _preparar(client, portal_cookies)
        assert keywords.match_reply("demo", "Do you have a spa?")["reply"] == EN
        assert pedidas == [], "su texto en inglés se manda tal cual: no se le pide al modelo que lo reescriba"
        assert keywords.match_reply("demo", "Hola, ¿tenéis spa?")["reply"] == ES
        assert keywords.match_reply("demo", "spa?")["reply"] == ES, "lo dudoso sale en la lengua del negocio"
        # Por el chat web, de principio a fin.
        res = client.post("/chat", headers={"Origin": "http://testserver"},
                          json={"cliente_id": "demo", "mensaje": "Do you have a spa?", "session_id": ""})
        assert res.status_code == 200, res.text
        assert res.json()["respuesta"] == EN
    finally:
        _limpiar(client, portal_cookies)


def test_otro_idioma_se_traduce(api_module, client, portal_cookies, monkeypatch):
    from backend import keywords

    pedidas = []

    def traducir(texto, idioma):
        pedidas.append((texto, idioma))
        return "Für Spa-Buchungen rufen Sie bitte (+34) 971 74 78 78 an."

    monkeypatch.setattr(keywords, "_traducir", traducir)
    try:
        _preparar(client, portal_cookies)
        respuesta = keywords.match_reply("demo", "Haben Sie ein Spa?")["reply"]
        assert respuesta.startswith("Für Spa-Buchungen"), respuesta
        assert pedidas == [(EN, "de")], "se traduce desde la inglesa, pensada para huéspedes de fuera"
    finally:
        _limpiar(client, portal_cookies)


def test_si_traducir_falla_nadie_se_queda_sin_respuesta(api_module, client, portal_cookies, monkeypatch):
    from backend import keywords

    monkeypatch.setattr(keywords, "_traducir", lambda texto, idioma: "")
    try:
        _preparar(client, portal_cookies)
        assert keywords.match_reply("demo", "Haben Sie ein Spa?")["reply"] == EN, (
            "sin traducción tiene que salir la inglesa")
    finally:
        _limpiar(client, portal_cookies)
    try:
        _preparar(client, portal_cookies, reply_en="")
        assert keywords.match_reply("demo", "Do you have a spa?")["reply"] == ES, (
            "sin inglesa ni traducción tiene que salir la de siempre")
    finally:
        _limpiar(client, portal_cookies)


def test_la_version_en_ingles_se_guarda_y_se_puede_borrar(api_module, client, portal_cookies):
    try:
        regla = _preparar(client, portal_cookies)
        res = client.patch("/auth/app/keyword-rules/" + regla["id"], cookies=portal_cookies,
                           json={"reply_en": "For the Spa, please call us."})
        assert res.status_code == 200 and res.json()["reply_en"] == "For the Spa, please call us.", res.text
        res = client.patch("/auth/app/keyword-rules/" + regla["id"], cookies=portal_cookies,
                           json={"reply_en": ""})
        assert res.status_code == 200 and res.json()["reply_en"] == "", "no se puede quitar la inglesa"
        assert res.json()["reply"] == ES, "tocar la inglesa ha cambiado la de siempre"
    finally:
        _limpiar(client, portal_cookies)


def test_el_editor_del_panel_manda_la_version_en_ingles():
    from pathlib import Path

    fuente = (Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="kwrReplyEn"' in fuente, "no hay dónde escribir la respuesta en inglés"
    guardar = fuente.split("document.getElementById('kwrSaveBtn')?.addEventListener", 1)[1].split("\n});", 1)[0]
    assert "reply_en: document.getElementById('kwrReplyEn').value.trim()" in guardar, (
        "el editor no manda la respuesta en inglés")
