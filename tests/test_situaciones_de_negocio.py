# -*- coding: utf-8 -*-
"""Las situaciones de un negocio son plantillas, no codigo por cliente.

Las doce condiciones de un salon real se montaron con un script propio. Eso no
escala: el siguiente negocio pide otras doce y hay que volver a escribir codigo.

Con las plantillas, una clinica dice "no doy precios de implantes sin radiografia"
usando la MISMA situacion con la que el salon dice "no doy precios de mechas sin
ver el pelo". Aqui se comprueba justo eso: que dos negocios distintos se comportan
distinto sin tocar una linea.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


@pytest.fixture
def limpio(api_module, client):  # noqa: F811
    from backend import db

    def borrar():
        with db._get_db_connection() as conexion:
            conexion.execute(
                "DELETE FROM business_rules WHERE cliente_id IN ('demo', 'otro_negocio')"
            )
            conexion.commit()

    borrar()
    yield
    borrar()


def test_el_catalogo_de_situaciones_esta_disponible(limpio, api_module):  # noqa: F811
    from backend import playbooks

    ids = {p["id"] for p in playbooks.catalogo()}
    assert "sin_precio_sin_verlo" in ids
    assert "pedir_foto" in ids
    assert "derivar_a_valoracion" in ids
    for plantilla in playbooks.catalogo():
        assert plantilla["titulo"] and plantilla["explicacion"] and plantilla["ejemplo"]


def test_aplicar_una_situacion_crea_la_regla(limpio, api_module):  # noqa: F811
    from backend import playbooks, rules

    playbooks.aplicar("demo", "sin_precio_sin_verlo", familias=["mechas", "balayage"])
    regla = rules.match("demo", {"intencion": "precio", "familia": "mechas"})
    assert regla is not None
    assert regla["accion"] == "ofrecer_cita"


def test_dos_negocios_se_comportan_distinto(limpio, api_module):  # noqa: F811
    """La razon de ser de todo esto."""
    from backend import playbooks, rules

    # Un salon: nada de precios de color sin ver el pelo.
    playbooks.aplicar("demo", "sin_precio_sin_verlo", familias=["mechas"],
                      texto="Eso lo vemos en persona, guapa.")
    # Otro negocio: para lo mismo, pasa a una persona.
    playbooks.aplicar("otro_negocio", "pasar_a_persona",
                      texto="Te paso con un compañero ahora mismo.")

    salon = rules.match("demo", {"intencion": "precio", "familia": "mechas"})
    assert salon["accion"] == "ofrecer_cita"
    assert "guapa" in salon["texto"]

    otro = rules.match("otro_negocio", {"intencion": "queja", "familia": ""})
    assert otro["accion"] == "pasar_a_humano"
    # Y lo de uno no se cuela en el otro.
    assert rules.match("otro_negocio", {"intencion": "precio", "familia": "mechas"}) is None


def test_aplicarla_dos_veces_no_duplica(limpio, api_module):  # noqa: F811
    """Renombrar una regla y dejar viva la vieja ya costo un incidente."""
    from backend import playbooks, rules

    playbooks.aplicar("demo", "pedir_foto", familias=["alisado"])
    playbooks.aplicar("demo", "pedir_foto", familias=["alisado"], texto="Mandanos una foto.")
    reglas = [r for r in rules.listar("demo") if r["nombre"] == "Pedir una foto para poder presupuestar"]
    assert len(reglas) == 1
    assert reglas[0]["texto"] == "Mandanos una foto."


def test_el_telefono_del_negocio_se_sustituye(limpio, api_module):  # noqa: F811
    from backend import clients, playbooks

    config = clients._get_client_config("demo")
    previo = dict(config.get("contacto") or {})
    config.setdefault("contacto", {})["telefono"] = "966 670 924"
    try:
        regla = playbooks.aplicar("demo", "sin_precio_sin_verlo", familias=["mechas"])
        assert "966 670 924" in regla["texto"]
        assert "{telefono" not in regla["texto"]
    finally:
        config["contacto"] = previo


def test_sin_telefono_no_queda_un_hueco_raro(limpio, api_module):  # noqa: F811
    from backend import clients, playbooks

    config = clients._get_client_config("demo")
    previo = dict(config.get("contacto") or {})
    config.setdefault("contacto", {})["telefono"] = ""
    try:
        regla = playbooks.aplicar("demo", "sin_precio_sin_verlo", familias=["mechas"])
        assert "{telefono" not in regla["texto"]
        assert "llamarnos al ." not in regla["texto"]
    finally:
        config["contacto"] = previo


def test_el_estado_dice_que_tiene_montado(limpio, api_module):  # noqa: F811
    from backend import playbooks

    playbooks.aplicar("demo", "pedir_foto", familias=["alisado"])
    estado = {p["id"]: p for p in playbooks.estado("demo")}
    assert estado["pedir_foto"]["activa"] is True
    assert estado["pedir_foto"]["familias"] == ["alisado"]
    assert estado["sin_precio_sin_verlo"]["activa"] is False


def test_una_situacion_inventada_no_se_aplica(limpio, api_module):  # noqa: F811
    from backend import playbooks

    with pytest.raises(ValueError):
        playbooks.aplicar("demo", "hacer_magia")


def test_una_respuesta_vacia_no_se_guarda(limpio, api_module):  # noqa: F811
    """Salvo "solo contarlo", que a proposito no responde."""
    from backend import playbooks

    with pytest.raises(ValueError):
        playbooks.aplicar("demo", "solo_informar", familias=["parking"], texto="")
    # Esta si: existe para medir, no para contestar.
    playbooks.aplicar("demo", "medir_sin_responder", familias=["uñas"])


# ─── Desde el panel ────────────────────────────────────────────────────────

def test_ciclo_desde_el_panel(client, limpio, api_module):  # noqa: F811
    """Un negocio las activa solo, sin que nadie le monte un script."""
    import uuid

    from test_crm_light import portal_cookies  # noqa: F401

    email = "pb-%s@example.com" % uuid.uuid4().hex[:8]
    api_module._create_user(email=email, password="pb-test-password-123", role="client",
                            display_name="Playbooks", cliente_id="demo")
    login = client.post("/auth/login", json={"email": email, "password": "pb-test-password-123"})
    cookies = {"vantelia_portal_session": login.cookies["vantelia_portal_session"]}

    vista = client.get("/auth/app/playbooks", cookies=cookies)
    assert vista.status_code == 200, vista.text
    ids = {p["id"] for p in vista.json()["items"]}
    assert "sin_precio_sin_verlo" in ids
    assert all(p["activa"] is False for p in vista.json()["items"])

    guardado = client.put("/auth/app/playbooks/sin_precio_sin_verlo", cookies=cookies, json={
        "familias": ["mechas"], "texto": "Eso lo vemos en persona.", "activa": True,
    })
    assert guardado.status_code == 200, guardado.text
    activa = next(p for p in guardado.json()["items"] if p["id"] == "sin_precio_sin_verlo")
    assert activa["activa"] is True
    assert activa["familias"] == ["mechas"]

    from backend import rules

    regla = rules.match("demo", {"intencion": "precio", "familia": "mechas"})
    assert regla and "en persona" in regla["texto"]


def test_una_situacion_inventada_da_400(client, limpio, api_module):  # noqa: F811
    import uuid

    email = "pb2-%s@example.com" % uuid.uuid4().hex[:8]
    api_module._create_user(email=email, password="pb-test-password-123", role="client",
                            display_name="Playbooks", cliente_id="demo")
    login = client.post("/auth/login", json={"email": email, "password": "pb-test-password-123"})
    cookies = {"vantelia_portal_session": login.cookies["vantelia_portal_session"]}
    respuesta = client.put("/auth/app/playbooks/hacer_magia", cookies=cookies,
                           json={"familias": [], "texto": "x", "activa": True})
    assert respuesta.status_code == 400


def test_una_clinica_dental_con_sus_propias_normas(limpio, api_module):  # noqa: F811
    """La prueba de fondo: otro negocio, otras normas, mismo mecanismo.

    Si esto pasa, el asistente no esta hecho para un salon de peluqueria: esta
    hecho para cualquier negocio que atienda con cita.
    """
    from backend import playbooks, rules

    CLINICA = "clinica_prueba"
    # Sus tres situaciones, con SUS palabras y SUS servicios.
    playbooks.aplicar(
        CLINICA, "sin_precio_sin_verlo", familias=["implante", "ortodoncia"],
        texto="El precio depende de tu caso: lo vemos con una radiografia, sin coste.",
    )
    playbooks.aplicar(
        CLINICA, "derivar_a_valoracion", familias=["blanqueamiento"],
        texto="El blanqueamiento necesita una revision previa. ¿Te busco hueco?",
    )
    playbooks.aplicar(
        CLINICA, "pasar_a_persona",
        texto="Siento lo ocurrido. Te paso con la responsable de la clinica.",
    )
    try:
        precio = rules.match(CLINICA, {"intencion": "precio", "familia": "implante"})
        assert "radiografia" in precio["texto"]
        assert precio["accion"] == "ofrecer_cita"

        blanqueo = rules.match(CLINICA, {"intencion": "info", "familia": "blanqueamiento"})
        assert "revision previa" in blanqueo["texto"]

        queja = rules.match(CLINICA, {"intencion": "queja", "familia": ""})
        assert queja["accion"] == "pasar_a_humano"

        # Y una limpieza dental, que no esta en ninguna regla, no se toca.
        assert rules.match(CLINICA, {"intencion": "precio", "familia": "limpieza"}) is None
    finally:
        from backend import db

        with db._get_db_connection() as conexion:
            conexion.execute("DELETE FROM business_rules WHERE cliente_id = ?", (CLINICA,))
            conexion.commit()


def test_el_administrador_configura_cualquier_negocio(client, limpio, api_module):  # noqa: F811
    """Quien da de alta a un cliente le deja el asistente listo desde SU panel,
    sin tener que impersonarle."""
    from test_booking_exhaustive import admin_cookies  # noqa: F401

    login = client.post("/auth/login", json={
        "email": "admin@example.com", "password": "admin-password-123",
    })
    assert login.status_code == 200, login.text
    cookies = {"vantelia_portal_session": login.cookies["vantelia_portal_session"]}

    # Sin decir el cliente, el admin no puede: no se sabe sobre cual configura.
    a_ciegas = client.get("/auth/app/playbooks", cookies=cookies)
    assert a_ciegas.status_code == 403

    vista = client.get("/auth/app/playbooks?cliente_id=demo", cookies=cookies)
    assert vista.status_code == 200, vista.text

    guardado = client.put("/auth/app/playbooks/derivar_a_valoracion?cliente_id=demo",
                          cookies=cookies, json={
                              "familias": ["extensiones"],
                              "texto": "Esto lo vemos en persona.",
                              "activa": True,
                          })
    assert guardado.status_code == 200, guardado.text

    from backend import rules

    regla = rules.match("demo", {"intencion": "precio", "familia": "extensiones"})
    assert regla and "en persona" in regla["texto"]


def test_el_negocio_no_puede_tocar_a_otro(client, limpio, api_module):  # noqa: F811
    """Multi-tenant: pasar otro cliente_id no puede dar acceso."""
    import uuid

    email = "pb3-%s@example.com" % uuid.uuid4().hex[:8]
    api_module._create_user(email=email, password="pb-test-password-123", role="client",
                            display_name="Playbooks", cliente_id="demo")
    login = client.post("/auth/login", json={"email": email, "password": "pb-test-password-123"})
    cookies = {"vantelia_portal_session": login.cookies["vantelia_portal_session"]}

    ajeno = client.get("/auth/app/playbooks?cliente_id=otro_negocio", cookies=cookies)
    assert ajeno.status_code == 403
