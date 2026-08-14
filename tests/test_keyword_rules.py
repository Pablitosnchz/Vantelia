"""Respuestas automaticas por palabra clave (opt-in por tenant).

Caso que lo motiva (hotel Cap Rocat, ago 2026): "si el huesped escribe spa o
masaje, responde exactamente este telefono", sin pasar por la IA. Lo critico que
se valida aqui:

1. Apagado por defecto: un tenant sin la seccion `keyword_rules` se comporta
   exactamente igual que antes (esta es la garantia de no romper a nadie).
2. Con la funcion activada, la regla gana a las heuristicas del chat (menu,
   disponibilidad, IA) y devuelve el texto VERBATIM.
3. El casado es literal y previsible: palabra completa, sin acentos ni
   mayusculas, plurales incluidos, y "spa" no debe casar dentro de otra palabra.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401

REPLY_SPA = "Para reservas o informacion sobre el Spa, por favor llame al 971 747 878."


def _set_enabled(client, portal_cookies, enabled: bool):
    res = client.put(
        "/auth/app/keyword-rules/config", cookies=portal_cookies, json={"enabled": enabled}
    )
    assert res.status_code == 200, res.text
    return res.json()


def _create_rule(client, portal_cookies, **payload):
    body = {
        "label": "Consultas de spa",
        "keywords": ["spa", "masaje"],
        "reply": REPLY_SPA,
        "match_mode": "any",
        "active": True,
    }
    body.update(payload)
    res = client.post("/auth/app/keyword-rules", cookies=portal_cookies, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _cleanup(client, portal_cookies):
    _set_enabled(client, portal_cookies, False)
    for rule in client.get("/auth/app/keyword-rules", cookies=portal_cookies).json()["items"]:
        client.delete(
            "/auth/app/keyword-rules/" + rule["id"], cookies=portal_cookies
        )


# --- Matching puro ---------------------------------------------------------


@pytest.mark.parametrize(
    "message, expected",
    [
        ("spa", True),
        ("Hola, informacion del SPA por favor", True),
        ("quiero un masaje", True),
        ("teneis masajes descontracturantes?", True),  # plural / derivado
        ("¿Cuánto cuesta el masaje?", True),           # acentos y signos
        ("necesito una toalla", False),
        ("llevo spandex a la piscina", False),         # 'spa' no casa dentro de otra palabra
        ("", False),
    ],
)
def test_keyword_matching_is_literal_and_predictable(api_module, message, expected):
    from backend import keywords

    rule = {"keywords": ["spa", "masaje"], "match_mode": "any"}
    assert keywords.rule_matches(rule, message) is expected


def test_match_mode_all_requires_every_keyword(api_module):
    from backend import keywords

    rule = {"keywords": ["factura", "empresa"], "match_mode": "all"}
    assert keywords.rule_matches(rule, "necesito la factura a nombre de mi empresa") is True
    assert keywords.rule_matches(rule, "necesito la factura") is False


def test_phrase_keyword_requires_full_sequence(api_module):
    from backend import keywords

    rule = {"keywords": ["circuito de aguas"], "match_mode": "any"}
    assert keywords.rule_matches(rule, "Que precio tiene el circuito de aguas?") is True
    assert keywords.rule_matches(rule, "hay circuito?") is False


# --- Aislamiento entre tenants (lo que pidio el negocio) -------------------


def test_disabled_by_default_does_not_touch_other_tenants(api_module, client, portal_cookies):
    """Sin activar la funcion, la regla existe pero NO se aplica."""
    from backend import keywords

    try:
        _create_rule(client, portal_cookies)
        assert keywords.rules_enabled("demo") is False
        assert keywords.match_reply("demo", "quiero informacion del spa") is None
        # Un tenant sin la seccion en config tampoco la tiene activada.
        assert keywords.rules_enabled("no-existe") is False
    finally:
        _cleanup(client, portal_cookies)


def test_enabled_tenant_gets_verbatim_reply_over_ai(api_module, client, portal_cookies):
    from backend import keywords

    try:
        _create_rule(client, portal_cookies)
        _set_enabled(client, portal_cookies, True)

        match = keywords.match_reply("demo", "Buenas, queria preguntar por el spa")
        assert match is not None
        assert match["reply"] == REPLY_SPA

        # El chat responde con el texto exacto y lo etiqueta como keyword_rule,
        # sin llamar a OpenAI (el entorno de test no tiene API key).
        res = client.post(
            "/chat",
            headers={"Origin": "http://testserver"},
            json={"cliente_id": "demo", "mensaje": "informacion sobre el spa", "session_id": ""},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["respuesta"] == REPLY_SPA
        assert body.get("intent") == "keyword_rule"
        assert body.get("mostrar_formulario") is False
    finally:
        _cleanup(client, portal_cookies)


def test_unmatched_message_keeps_normal_pipeline(api_module, client, portal_cookies):
    """Si no casa ninguna regla, el chat sigue con su comportamiento de siempre."""
    try:
        _create_rule(client, portal_cookies)
        _set_enabled(client, portal_cookies, True)
        res = client.post(
            "/chat",
            headers={"Origin": "http://testserver"},
            json={"cliente_id": "demo", "mensaje": "hola", "session_id": ""},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["respuesta"] != REPLY_SPA
        assert body.get("intent") == "menu"
    finally:
        _cleanup(client, portal_cookies)


def test_inactive_rule_is_skipped_and_hits_are_counted(api_module, client, portal_cookies):
    from backend import keywords

    try:
        rule = _create_rule(client, portal_cookies)
        _set_enabled(client, portal_cookies, True)

        assert keywords.match_reply("demo", "spa") is not None
        assert keywords.match_reply("demo", "spa") is not None
        assert keywords.get_rule("demo", rule["id"])["hits"] == 2

        res = client.patch(
            "/auth/app/keyword-rules/" + rule["id"],
            cookies=portal_cookies,
            json={"active": False},
        )
        assert res.status_code == 200, res.text
        assert keywords.match_reply("demo", "spa") is None
    finally:
        _cleanup(client, portal_cookies)


def test_rules_apply_in_order_first_match_wins(api_module, client, portal_cookies):
    from backend import keywords

    try:
        _create_rule(
            client, portal_cookies,
            label="Spa", keywords=["spa"], reply="Primera regla: spa.",
        )
        _create_rule(
            client, portal_cookies,
            label="General", keywords=["spa", "hotel"], reply="Segunda regla: general.",
        )
        _set_enabled(client, portal_cookies, True)
        match = keywords.match_reply("demo", "consulta sobre el spa")
        assert match["reply"] == "Primera regla: spa."
    finally:
        _cleanup(client, portal_cookies)


# --- API del portal --------------------------------------------------------


def test_portal_crud_validates_and_isolates(api_module, client, portal_cookies):
    try:
        # Sin palabras clave -> 400
        res = client.post(
            "/auth/app/keyword-rules",
            cookies=portal_cookies,
            json={"keywords": [], "reply": "algo"},
        )
        assert res.status_code == 400

        rule = _create_rule(client, portal_cookies)
        assert rule["keywords"] == ["spa", "masaje"]

        listing = client.get("/auth/app/keyword-rules", cookies=portal_cookies).json()
        assert listing["total"] == 1
        assert listing["enabled"] is False

        res = client.patch(
            "/auth/app/keyword-rules/" + rule["id"],
            cookies=portal_cookies,
            json={"reply": "Nuevo texto de spa.", "keywords": ["spa", "wellness"]},
        )
        assert res.status_code == 200
        assert res.json()["reply"] == "Nuevo texto de spa."
        assert res.json()["keywords"] == ["spa", "wellness"]

        # Sesion requerida
        assert client.get("/auth/app/keyword-rules").status_code in (401, 403)

        missing = client.patch(
            "/auth/app/keyword-rules/kwr_" + uuid.uuid4().hex[:10],
            cookies=portal_cookies,
            json={"active": False},
        )
        assert missing.status_code == 404

        assert client.delete(
            "/auth/app/keyword-rules/" + rule["id"], cookies=portal_cookies
        ).status_code == 200
        assert client.get("/auth/app/keyword-rules", cookies=portal_cookies).json()["total"] == 0
    finally:
        _cleanup(client, portal_cookies)


def test_config_flag_survives_config_reload(api_module, client, portal_cookies):
    """La seccion debe estar en CONFIG_EXTRA_SECTIONS o se pierde al recargar."""
    from backend import clients, keywords

    try:
        _set_enabled(client, portal_cookies, True)
        raw = clients._serialize_client_config(clients._get_client_config("demo"))
        reloaded = clients._normalize_client_config("demo", raw)
        assert reloaded.get(keywords.CONFIG_SECTION, {}).get("enabled") is True
    finally:
        _cleanup(client, portal_cookies)
