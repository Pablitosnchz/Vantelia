# -*- coding: utf-8 -*-
"""El negocio escribe sus propias reglas desde el panel, sin tocar el prompt.

Antes, "pide foto si preguntan el precio de un alisado" vivia en una instruccion
del system prompt: el modelo podia ignorarla y nadie del salon podia cambiarla.
Aqui se guarda como dato, se lista, se edita y se borra desde el portal.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401


def _limpiar(cliente_id="demo"):
    from backend import db

    with db._get_db_connection() as conexion:
        conexion.execute("DELETE FROM business_rules WHERE cliente_id = ?", (cliente_id,))
        conexion.commit()


def test_ciclo_completo_desde_el_panel(client, portal_cookies):  # noqa: F811
    _limpiar()
    try:
        vacio = client.get("/auth/app/business-rules", cookies=portal_cookies)
        assert vacio.status_code == 200, vacio.text
        assert vacio.json()["items"] == []
        # El panel necesita saber que puede ofrecer.
        assert "reservar" in vacio.json()["intenciones"]
        assert "pedir_foto" in vacio.json()["acciones"]

        creada = client.post(
            "/auth/app/business-rules",
            cookies=portal_cookies,
            json={
                "nombre": "Presupuesto de alisado",
                "intenciones": ["presupuesto"],
                "familias": ["alisado"],
                "accion": "pedir_foto",
                "texto": "Mandanos una foto por detras y te decimos precio.",
                "prioridad": 10,
            },
        )
        assert creada.status_code == 200, creada.text
        regla_id = creada.json()["id"]

        editada = client.put(
            "/auth/app/business-rules/%s" % regla_id,
            cookies=portal_cookies,
            json={
                "nombre": "Presupuesto de alisado",
                "intenciones": ["presupuesto", "precio"],
                "familias": ["alisado"],
                "accion": "pedir_foto",
                "texto": "Mandanos una foto por detras, porfa.",
                "prioridad": 10,
            },
        )
        assert editada.status_code == 200, editada.text
        assert editada.json()["texto"].endswith("porfa.")
        assert sorted(editada.json()["intenciones"]) == ["precio", "presupuesto"]

        borrada = client.delete(
            "/auth/app/business-rules/%s" % regla_id, cookies=portal_cookies
        )
        assert borrada.status_code == 200, borrada.text
        assert client.get(
            "/auth/app/business-rules", cookies=portal_cookies
        ).json()["items"] == []
    finally:
        _limpiar()


def test_una_accion_inventada_no_se_guarda(client, portal_cookies):  # noqa: F811
    _limpiar()
    try:
        respuesta = client.post(
            "/auth/app/business-rules",
            cookies=portal_cookies,
            json={"nombre": "Mala", "intenciones": ["reservar"], "accion": "hacer_magia"},
        )
        assert respuesta.status_code == 400, respuesta.text
    finally:
        _limpiar()


def test_borrar_algo_que_no_existe_es_404(client, portal_cookies):  # noqa: F811
    respuesta = client.delete(
        "/auth/app/business-rules/rule_inventada", cookies=portal_cookies
    )
    assert respuesta.status_code == 404


def test_editar_la_regla_de_otro_negocio_es_404(client, portal_cookies):  # noqa: F811
    """Multi-tenant: nadie puede tocar la configuracion de otro salon."""
    _limpiar()
    _limpiar("otro_negocio")
    try:
        from backend import rules

        ajena = rules.guardar("otro_negocio", nombre="Suya", intenciones=["reservar"],
                              accion="formulario")
        respuesta = client.put(
            "/auth/app/business-rules/%s" % ajena["id"],
            cookies=portal_cookies,
            json={"nombre": "Robada", "intenciones": ["reservar"], "accion": "responder",
                  "texto": "mia"},
        )
        assert respuesta.status_code == 404, respuesta.text
        assert rules.listar("otro_negocio")[0]["nombre"] == "Suya"
    finally:
        _limpiar()
        _limpiar("otro_negocio")


def test_el_interruptor_se_guarda_en_el_config(client, portal_cookies):  # noqa: F811
    """Opt-in por tenant: encenderlo en un salon no puede afectar a los demas."""
    from backend import clients, intents

    try:
        encendido = client.put(
            "/auth/app/business-rules/config",
            cookies=portal_cookies, json={"enabled": True},
        )
        assert encendido.status_code == 200, encendido.text
        assert clients._get_client_config("demo")["ai_intents"]["enabled"] is True
        assert intents.enabled_for("otro_negocio") is False
    finally:
        client.put("/auth/app/business-rules/config",
                   cookies=portal_cookies, json={"enabled": False})


def test_el_interruptor_no_se_apaga_solo_sin_clave_de_openai(client, portal_cookies, monkeypatch):  # noqa: F811
    """El panel refleja lo que el negocio guardo; la clave es otra cosa."""
    from backend import intents

    try:
        client.put("/auth/app/business-rules/config", cookies=portal_cookies,
                   json={"enabled": True})
        monkeypatch.setattr(intents.settings, "OPENAI_API_KEY", "")
        vista = client.get("/auth/app/business-rules", cookies=portal_cookies).json()
        assert vista["enabled"] is True, "el interruptor volveria a apagado solo"
        assert intents.enabled_for("demo") is False, "pero no se clasifica sin clave"
    finally:
        client.put("/auth/app/business-rules/config", cookies=portal_cookies,
                   json={"enabled": False})
