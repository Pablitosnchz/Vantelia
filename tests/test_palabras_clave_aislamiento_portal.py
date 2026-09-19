"""Dos negocios comparten palabras, pero nunca sus respuestas ni su editor.

Regresión de la frontera del portal para las respuestas ES/EN de 38e9698.
Datos inventados, dos sesiones autenticadas y chat HTTP sin modelo ni Meta.
"""
from __future__ import annotations

import copy
import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import DEFAULT_DEMO_CONFIG


@pytest.fixture(scope="module")
def api_module(vantelia_env_factory):
    configs = {}
    for cid, con_agenda in (("salon_prueba", True), ("hotel_prueba", False)):
        cfg = copy.deepcopy(DEFAULT_DEMO_CONFIG["demo"])
        cfg["nombre"] = cid
        cfg["booking"]["enabled"] = con_agenda
        cfg["whatsapp"] = {"enabled": False}
        cfg["contacto"] = {"email": cid + "@example.invalid"}
        configs[cid] = cfg
    return vantelia_env_factory(config=configs)


@pytest.fixture()
def negocios(api_module):
    datos = {}
    for tipo, es, en in (
        ("salon", "El spa capilar del salón se consulta en recepción.",
         "Ask the salon reception about the hair spa."),
        ("hotel", "El spa del hotel abre de nueve a seis.",
         "The hotel spa opens from nine to six."),
    ):
        cid = tipo + "_prueba"
        # EmailStr rechaza .invalid incluso con los transportes interceptados.
        email = tipo + "-" + uuid.uuid4().hex[:10] + "@example.com"
        api_module._create_user(email=email, password="prueba-aislamiento-123",
                                role="client", display_name=tipo, cliente_id=cid)
        # La cookie del portal es Secure; reproducimos el acceso HTTPS real.
        portal = TestClient(api_module.app, base_url="https://testserver")
        login = portal.post("/auth/login", json={
            "email": email, "password": "prueba-aislamiento-123"})
        assert login.status_code == 200, login.text
        activado = portal.put("/auth/app/keyword-rules/config", json={"enabled": True})
        assert activado.status_code == 200, activado.text
        creada = portal.post("/auth/app/keyword-rules", json={
            "label": "Spa", "keywords": ["spa"], "reply": es, "reply_en": en,
            "match_mode": "any", "active": True})
        assert creada.status_code == 200, creada.text
        datos[tipo] = {"portal": portal, "cid": cid, "regla": creada.json(),
                       "es": es, "en": en, "session_id": ""}
    try:
        yield datos
    finally:
        for negocio in datos.values():
            portal = negocio["portal"]
            portal.delete("/auth/app/keyword-rules/" + negocio["regla"]["id"])
            portal.put("/auth/app/keyword-rules/config", json={"enabled": False})
            portal.close()


def _preguntar(negocio, idioma):
    mensaje = "¿Tienen spa?" if idioma == "es" else "Do you have a spa?"
    res = negocio["portal"].post("/chat", headers={"Origin": "http://testserver"}, json={
        "cliente_id": negocio["cid"], "mensaje": mensaje,
        "session_id": negocio["session_id"]})
    assert res.status_code == 200, res.text
    negocio["session_id"] = res.json()["session_id"]
    return res.json()["respuesta"]


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_misma_palabra_responde_con_el_texto_de_cada_negocio(negocios, idioma):
    for negocio in negocios.values():
        assert _preguntar(negocio, idioma) == negocio[idioma]
        listado = negocio["portal"].get("/auth/app/keyword-rules")
        assert listado.status_code == 200, listado.text
        assert [r["id"] for r in listado.json()["items"]] == [negocio["regla"]["id"]]


def test_editar_desde_un_portal_cambia_su_conversacion_y_conserva_la_otra(negocios):
    salon, hotel = negocios["salon"], negocios["hotel"]
    for idioma in ("es", "en"):
        assert _preguntar(salon, idioma) == salon[idioma]
        assert _preguntar(hotel, idioma) == hotel[idioma]
    sesiones = {tipo: n["session_id"] for tipo, n in negocios.items()}

    cambio = {"reply": "El spa capilar se atiende ahora los martes.",
              "reply_en": "The hair spa is now available on Tuesdays."}
    res = salon["portal"].patch("/auth/app/keyword-rules/" + salon["regla"]["id"], json=cambio)
    assert res.status_code == 200, res.text
    for idioma, campo in (("es", "reply"), ("en", "reply_en")):
        assert _preguntar(salon, idioma) == cambio[campo]
        assert _preguntar(hotel, idioma) == hotel[idioma]
    assert {tipo: n["session_id"] for tipo, n in negocios.items()} == sesiones
    guardado_hotel = hotel["portal"].get("/auth/app/keyword-rules").json()["items"]
    assert [(r["reply"], r["reply_en"]) for r in guardado_hotel] == [(hotel["es"], hotel["en"])]


@pytest.mark.parametrize("intruso, titular", [("salon", "hotel"), ("hotel", "salon")])
def test_el_portal_no_lee_edita_ni_borra_la_regla_ajena(negocios, intruso, titular):
    propio, ajeno = negocios[intruso], negocios[titular]
    portal = propio["portal"]
    params = {"cliente_id": ajeno["cid"]}
    # Este endpoint usa la sesión: añadir el tenant ajeno no cambia a quién se lee.
    listado = portal.get("/auth/app/keyword-rules", params=params)
    assert listado.status_code == 200, listado.text
    assert [r["id"] for r in listado.json()["items"]] == [propio["regla"]["id"]]

    ruta_ajena = "/auth/app/keyword-rules/" + ajeno["regla"]["id"]
    editado = portal.patch(ruta_ajena, params=params, json={
        "reply": "Texto intruso", "reply_en": "Foreign text"})
    assert editado.status_code == 404, editado.text
    borrado = portal.delete(ruta_ajena, params=params)
    assert borrado.status_code == 404, borrado.text
    for negocio in (propio, ajeno):
        for idioma in ("es", "en"):
            assert _preguntar(negocio, idioma) == negocio[idioma]
