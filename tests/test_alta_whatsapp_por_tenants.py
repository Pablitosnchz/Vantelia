# -*- coding: utf-8 -*-
"""El boton de conectar WhatsApp se abre a UNO antes que a todos.

POR QUE EXISTE
--------------
8-sep-2026: Meta aprueba la revision de la app (todo menos `manage_app_solution`,
que no usamos). En cuanto se ponen las variables en el VPS, el boton "Conectar mi
WhatsApp" aparece en el portal de TODOS los tenants... y el alta todavia no se ha
probado nunca con un numero real.

El riesgo no es que falle: es DONDE falla. Si el alta se queda a medias, el
numero del negocio -el que usa para trabajar todos los dias- se queda a medio
configurar. Por eso `WHATSAPP_ES_TENANTS` deja abrirlo primero al numero de
pruebas y solo despues a todos (vacio = a todos, que es como quedara).
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.fixture
def meta_configurado(api_module, monkeypatch):  # noqa: F811
    from backend import settings

    monkeypatch.setattr(settings, "WHATSAPP_APP_ID", "123", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "secreto", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_ES_CONFIG_ID", "456", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_ES_TENANTS", "", raising=False)


def test_sin_lista_se_ofrece_a_todos(api_module, meta_configurado):  # noqa: F811
    from backend import wa_onboarding

    assert wa_onboarding.embedded_signup_available("cualquiera")
    assert wa_onboarding.embedded_signup_available()


def test_con_lista_solo_a_los_de_la_lista(api_module, meta_configurado, monkeypatch):  # noqa: F811
    from backend import settings, wa_onboarding

    monkeypatch.setattr(settings, "WHATSAPP_ES_TENANTS", "pruebas, otro", raising=False)
    assert wa_onboarding.embedded_signup_available("pruebas")
    assert wa_onboarding.embedded_signup_available("otro")
    assert not wa_onboarding.embedded_signup_available("alicia_rincon_estilistas")
    assert not wa_onboarding.embedded_signup_available()


def test_sin_meta_configurado_no_hay_boton(api_module, monkeypatch):  # noqa: F811
    from backend import settings, wa_onboarding

    monkeypatch.setattr(settings, "WHATSAPP_ES_CONFIG_ID", "", raising=False)
    assert not wa_onboarding.embedded_signup_available("pruebas")


def test_el_enlace_de_alta_respeta_la_lista(api_module, meta_configurado, monkeypatch):  # noqa: F811
    """No basta con esconder el boton: el enlace tampoco se genera."""
    from backend import settings, wa_onboarding

    monkeypatch.setattr(settings, "WHATSAPP_ES_TENANTS", "pruebas", raising=False)
    assert wa_onboarding.hosted_signup_url("pruebas", base_url="https://app.vantelia.es")
    assert not wa_onboarding.hosted_signup_url("alicia_rincon_estilistas",
                                               base_url="https://app.vantelia.es")


def test_el_endpoint_de_alta_tambien_lo_mira(api_module):  # noqa: F811
    """La UI solo esconde; quien decide es el backend."""
    import inspect

    from backend.routers import portal_app

    fuente = inspect.getsource(portal_app)
    assert "embedded_signup_available(cliente_id)" in fuente
