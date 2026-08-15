"""La sesion del portal caduca por INACTIVIDAD, no a plazo fijo desde el login.

Antes `expires_at` se fijaba al iniciar sesion y no se movia: un negocio con la
agenda abierta todo el dia se encontraba la pantalla de login a mitad de jornada,
estuviera trabajando o no. Ahora cada peticion autenticada renueva el plazo.
"""
from __future__ import annotations

import uuid

from test_booking_exhaustive import api_module, client  # noqa: F401


def _usuario(api_module):
    from backend import security

    email = f"sesion-{uuid.uuid4().hex[:8]}@example.com"
    security._create_user(
        email=email, password="sesion-test-password-123", role="client",
        display_name="Sesion Test", cliente_id="demo",
    )
    return email, "sesion-test-password-123"


def _caducidad(api_module, session_token):
    from backend import db, security

    session_id, _ = security._compound_token_parts(session_token, "ses")
    with db._get_db_connection() as connection:
        fila = connection.execute(
            "SELECT expires_at FROM auth_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return fila["expires_at"] if fila else ""


def test_usar_el_panel_renueva_la_sesion(api_module, client):
    from backend import db, security

    email, password = _usuario(api_module)
    token = client.post("/auth/login", json={"email": email, "password": password}).cookies[
        "vantelia_portal_session"
    ]
    cookies = {"vantelia_portal_session": token}
    session_id, _ = security._compound_token_parts(token, "ses")

    # Se simula una sesion a punto de caducar (menos de la mitad del plazo).
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE id = ?",
            ("2099-01-01T00:00:00Z", session_id),
        )
        connection.commit()
    lejana = _caducidad(api_module, token)

    # Con margen de sobra NO se reescribe: no queremos un UPDATE por peticion.
    assert client.get("/auth/me", cookies=cookies).status_code == 200
    assert _caducidad(api_module, token) == lejana

    # Con poco margen (viva, pero a punto de caducar), la peticion la renueva.
    from backend import timeutils

    justa = timeutils._expires_at_in_hours(1)
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE id = ?", (justa, session_id)
        )
        connection.commit()
    assert client.get("/auth/me", cookies=cookies).status_code == 200
    assert _caducidad(api_module, token) > justa


def test_una_sesion_caducada_sigue_sin_valer(api_module, client):
    """La renovacion no puede resucitar sesiones ya muertas."""
    from backend import db, security

    email, password = _usuario(api_module)
    token = client.post("/auth/login", json={"email": email, "password": password}).cookies[
        "vantelia_portal_session"
    ]
    session_id, _ = security._compound_token_parts(token, "ses")
    with db._get_db_connection() as connection:
        connection.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00Z", session_id),
        )
        connection.commit()

    respuesta = client.get("/auth/me", cookies={"vantelia_portal_session": token})
    assert respuesta.status_code == 401


def test_la_ventana_de_inactividad_es_de_al_menos_una_semana(api_module):
    """Un puente con el negocio cerrado no debe echar al equipo."""
    from backend import settings

    assert settings.PORTAL_SESSION_HOURS >= 168


def test_la_cookie_dura_mas_que_la_ventana_de_inactividad(api_module, client):
    """Quien manda es el servidor. Si la cookie caducase a la vez que la sesion,
    un negocio que usa el panel a diario se quedaria fuera al cumplirse el plazo
    desde el login, con la sesion viva en el servidor."""
    from backend import settings

    email, password = _usuario(api_module)
    respuesta = client.post("/auth/login", json={"email": email, "password": password})
    # El login manda DOS cookies: la de admin se borra (Max-Age=0) y se pone la del
    # portal. Hay que quedarse con la del portal, no con la primera del listado.
    cabeceras = [
        valor.decode() for clave, valor in respuesta.headers.raw
        if clave.decode().lower() == "set-cookie"
    ]
    cabecera = next(c for c in cabeceras if c.startswith("vantelia_portal_session="))

    max_age = int(cabecera.split("Max-Age=")[1].split(";")[0])
    assert max_age > settings.PORTAL_SESSION_HOURS * 3600
    assert max_age >= 90 * 24 * 3600
