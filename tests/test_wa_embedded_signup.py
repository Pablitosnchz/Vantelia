"""Alta self-service de WhatsApp (Embedded Signup) y Coexistence.

Coexistence (Meta, mayo 2025) permite que el numero siga en la app del movil del
negocio Y responda por la Cloud API. Lo que se valida aqui:

- Que el token que se guarda es el DEL NEGOCIO (cifrado) y que se usa para enviar
  por delante del token global de Vantelia: su numero vive en su cuenta de Meta.
- Que su `phone_number_id` resuelve a su tenant.
- Que el ECO de lo que escribe su equipo desde el movil entra en el historial y
  **calla al asistente**, sin que nadie tenga que pulsar nada en el panel.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture(autouse=True)
def _clave_de_cifrado(api_module, monkeypatch):
    """El cifrado de credenciales exige una clave Fernet; en CI no hay .env."""
    from backend import settings

    monkeypatch.setattr(settings, "OAUTH_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture(autouse=True)
def _limpiar(api_module):
    from backend import db

    yield
    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM client_whatsapp_accounts")
        connection.execute("DELETE FROM chat_takeovers")
        connection.commit()


# --- Credenciales por tenant ------------------------------------------------


def test_token_del_negocio_se_guarda_cifrado_y_manda_sobre_el_global(api_module, monkeypatch):
    from backend import db, messaging, settings, wa_onboarding

    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "TOKEN_GLOBAL_VANTELIA", raising=False)
    wa_onboarding.save_account(
        "demo", waba_id="WABA1", phone_number_id="PN1", token="TOKEN_DEL_NEGOCIO",
        display_phone_number="+34 600 11 22 33", mode=wa_onboarding.MODE_COEXISTENCE,
    )
    # En la base de datos no puede quedar el token en claro.
    with db._get_db_connection() as connection:
        guardado = connection.execute(
            "SELECT access_token_encrypted FROM client_whatsapp_accounts WHERE cliente_id = 'demo'"
        ).fetchone()["access_token_encrypted"]
    assert guardado and "TOKEN_DEL_NEGOCIO" not in guardado

    assert wa_onboarding.account_token("demo") == "TOKEN_DEL_NEGOCIO"
    assert messaging._whatsapp_access_token_for_client("demo") == "TOKEN_DEL_NEGOCIO"
    # Un tenant sin conexion propia sigue con el token global.
    assert messaging._whatsapp_access_token_for_client("van") == "TOKEN_GLOBAL_VANTELIA"


def test_el_numero_conectado_resuelve_a_su_tenant(api_module):
    from backend import wa_onboarding, whatsapp

    wa_onboarding.save_account("demo", waba_id="WABA1", phone_number_id="PN_DEMO", token="t")
    assert whatsapp._whatsapp_phone_client_map().get("PN_DEMO") == "demo"
    assert whatsapp._resolve_whatsapp_client_id("PN_DEMO") == "demo"


def test_desconectar_borra_las_credenciales(api_module):
    from backend import wa_onboarding

    wa_onboarding.save_account("demo", waba_id="W", phone_number_id="PN", token="t")
    assert wa_onboarding.disconnect("demo") is True
    assert wa_onboarding.get_account("demo") == {}
    assert wa_onboarding.account_token("demo") == ""


def test_boton_solo_si_meta_esta_configurado(api_module, monkeypatch):
    from backend import settings, wa_onboarding

    monkeypatch.setattr(settings, "WHATSAPP_APP_ID", "", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_ES_CONFIG_ID", "", raising=False)
    assert wa_onboarding.embedded_signup_available() is False

    monkeypatch.setattr(settings, "WHATSAPP_APP_ID", "123", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "sec", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_ES_CONFIG_ID", "cfg", raising=False)
    assert wa_onboarding.embedded_signup_available() is True


# --- Coexistence: el eco de la app del movil --------------------------------


def test_el_eco_del_movil_entra_en_el_historial_y_calla_al_bot(api_module):
    """Si el equipo contesta desde su WhatsApp, el asistente no debe hablar encima."""
    from backend import db, inbox, wa_onboarding, whatsapp

    wa_onboarding.save_account(
        "demo", waba_id="WABA1", phone_number_id="PN_COEX", token="t",
        mode=wa_onboarding.MODE_COEXISTENCE,
    )
    cliente_final = "34600999111"
    session_id = whatsapp._whatsapp_session_id("demo", cliente_final)

    whatsapp._handle_whatsapp_echoes(
        "PN_COEX",
        [{"to": cliente_final, "type": "text", "text": {"body": "Le subimos la botella ahora mismo."}}],
    )

    assert inbox.bot_is_muted(session_id) is True
    assert inbox.takeover_state(session_id)["agent_name"] == "Equipo (WhatsApp)"
    with db._get_db_connection() as connection:
        filas = connection.execute(
            "SELECT role, content FROM chat_messages WHERE session_id = ?", (session_id,)
        ).fetchall()
    assert any(f["role"] == "assistant" and "botella" in f["content"] for f in filas)


def test_eco_de_un_numero_desconocido_no_rompe_el_webhook(api_module):
    from backend import whatsapp

    # No debe lanzar: un eco que no se puede atribuir se ignora.
    whatsapp._handle_whatsapp_echoes(
        "PN_QUE_NO_EXISTE",
        [{"to": "34600000000", "type": "text", "text": {"body": "hola"}}],
    )


def test_eco_no_textual_deja_rastro_igualmente(api_module):
    from backend import db, wa_onboarding, whatsapp

    wa_onboarding.save_account("demo", waba_id="W", phone_number_id="PN_COEX2", token="t")
    whatsapp._handle_whatsapp_echoes("PN_COEX2", [{"to": "34600999222", "type": "image"}])
    session_id = whatsapp._whatsapp_session_id("demo", "34600999222")
    with db._get_db_connection() as connection:
        filas = connection.execute(
            "SELECT content FROM chat_messages WHERE session_id = ?", (session_id,)
        ).fetchall()
    assert filas and "app del negocio" in filas[0]["content"]


# --- Endpoint --------------------------------------------------------------


def test_connect_sin_configuracion_de_meta_responde_503(api_module, client, monkeypatch):
    import uuid

    from backend import security, settings

    monkeypatch.setattr(settings, "WHATSAPP_ES_CONFIG_ID", "", raising=False)
    email = f"wa-owner-{uuid.uuid4().hex[:8]}@example.com"
    security._create_user(
        email=email, password="wa-test-password-123", role="client",
        display_name="Owner WA", cliente_id="demo", portal_role="owner",
    )
    login = client.post("/auth/login", json={"email": email, "password": "wa-test-password-123"})
    cookies = {"vantelia_portal_session": login.cookies["vantelia_portal_session"]}
    res = client.post(
        "/auth/app/whatsapp/connect",
        cookies=cookies,
        json={"code": "AQD-codigo-de-prueba", "waba_id": "", "phone_number_id": ""},
    )
    assert res.status_code == 503


# --- Vuelta del registro insertado ALOJADO POR META -------------------------
#
# El flujo del navegador devuelve el `code` por JavaScript; el alojado por Meta
# navega de vuelta a /whatsapp/signup/callback. Un `code` caduca en minutos, asi
# que cada forma de fallar tiene que explicarse en pantalla: dejar al negocio en
# una pagina en blanco significa perder el alta sin que nadie sepa por que.


def _crear_owner(client, cliente_id="demo"):
    import uuid

    from backend import security

    email = f"wa-cb-{uuid.uuid4().hex[:8]}@example.com"
    security._create_user(
        email=email, password="wa-test-password-123", role="client",
        display_name="Owner WA", cliente_id=cliente_id, portal_role="owner",
    )
    login = client.post("/auth/login", json={"email": email, "password": "wa-test-password-123"})
    return {"vantelia_portal_session": login.cookies["vantelia_portal_session"]}


def test_la_vuelta_de_meta_conecta_el_numero_del_negocio(api_module, client, monkeypatch):
    from backend import wa_onboarding
    from backend.routers import portal_app

    llamadas = {}

    async def _falso_completar(cliente_id, **kwargs):
        llamadas["cliente_id"] = cliente_id
        llamadas.update(kwargs)
        return {"phone_number_id": "999", "display_phone_number": "+34 600 000 000"}

    monkeypatch.setattr(wa_onboarding, "complete_signup", _falso_completar)
    cookies = _crear_owner(client)

    res = client.get(
        "/whatsapp/signup/callback",
        params={"code": "AQD-codigo-de-meta"},
        cookies=cookies,
        follow_redirects=False,
    )

    assert res.status_code == 200
    assert "WhatsApp conectado" in res.text
    # El tenant sale de la SESION: la URL de Meta no lo trae.
    assert llamadas["cliente_id"] == "demo"
    assert llamadas["code"] == "AQD-codigo-de-meta"
    _ = portal_app  # el endpoint vive ahi


def test_sin_sesion_no_se_conecta_nada_y_se_explica(api_module, client, monkeypatch):
    """Sin sesion no hay forma de saber a QUE negocio conectar el numero."""
    from backend import wa_onboarding

    async def _no_debe_llamarse(*a, **k):
        raise AssertionError("no se puede completar un alta sin saber el tenant")

    monkeypatch.setattr(wa_onboarding, "complete_signup", _no_debe_llamarse)

    res = client.get("/whatsapp/signup/callback", params={"code": "AQD-x"}, follow_redirects=False)

    assert res.status_code == 400
    assert "Inicia sesion" in res.text


def test_si_meta_devuelve_error_se_dice_y_no_se_toca_el_canal(api_module, client, monkeypatch):
    from backend import wa_onboarding

    async def _no_debe_llamarse(*a, **k):
        raise AssertionError("Meta ha rechazado el alta: no hay nada que completar")

    monkeypatch.setattr(wa_onboarding, "complete_signup", _no_debe_llamarse)
    cookies = _crear_owner(client)

    res = client.get(
        "/whatsapp/signup/callback",
        params={"error": "access_denied", "error_description": "El usuario cancelo"},
        cookies=cookies,
        follow_redirects=False,
    )

    assert res.status_code == 400
    assert "No se ha conectado" in res.text


def test_sin_codigo_no_se_queda_en_blanco(api_module, client):
    cookies = _crear_owner(client)

    res = client.get("/whatsapp/signup/callback", cookies=cookies, follow_redirects=False)

    assert res.status_code == 400
    assert "Falta informacion" in res.text
