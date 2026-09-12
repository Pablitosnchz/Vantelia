# -*- coding: utf-8 -*-
"""Lo que el negocio cambia en el panel manda en la consulta SIGUIENTE.

EL PROBLEMA QUE RESUELVE
------------------------
`backend/intents.py` guarda en memoria tres cosas por tenant: las familias de su
catálogo, las preguntas que tiene respondidas y la clasificación de cada mensaje
—y esta última se lleva dentro la RESPUESTA de la Q&A que reconoció—. Nada de eso
se revisaba: se daba por bueno cinco o diez minutos. Consecuencias medibles:

* borrar una Q&A desde el panel y seguir contestándola durante diez minutos;
* desactivar o renombrar un servicio y que el asistente siguiera nombrando la
  familia vieja;
* y lo que no arregla vaciar un diccionario: el POST del panel lo atiende UN
  worker y el mensaje siguiente de la clienta puede caerle a OTRO, que no se ha
  enterado de nada.

Por eso lo cacheado lleva el SELLO del tenant (`intents.sellos_del_tenant`),
derivado de la base de datos que comparten todos los workers. El vaciado local
del CRUD es solo el atajo del worker que recibe el POST.

Contrato: `docs/NORMAS_AGENTE_IA.md` ("invalidar cachés por tenant... no prometer
un dato obsoleto"). Fase 1 de `docs/PLAN_CONSOLIDACION_IA.md`.
"""
from __future__ import annotations

import sys
import types

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401

CONTROL = "otro_negocio"  # el tenant de control: nada de lo de "demo" le afecta


def _limpiar(*clientes):
    from backend import appstate, db

    with db._get_db_connection() as conexion:
        for cliente_id in clientes:
            conexion.execute("DELETE FROM kb_qa WHERE cliente_id = ?", (cliente_id,))
        conexion.commit()
    with appstate.state_lock:
        appstate.intent_cache.clear()


def _crear_qa(client, portal_cookies, pregunta, respuesta):  # noqa: F811
    creada = client.post(
        "/auth/app/qa", cookies=portal_cookies,
        json={"question": pregunta, "answer": respuesta},
    )
    assert creada.status_code == 200, creada.text
    return creada.json()["id"]


def _respuestas(cliente_id):
    from backend import intents

    return {q["question"]: q["answer"] for q in intents.preguntas_del_tenant(cliente_id)}


# ─── Q&A: editar y borrar desde el panel ───────────────────────────────────

def test_borrar_una_qa_deja_de_ofrecerse(client, portal_cookies):  # noqa: F811
    """Lo borrado no se sigue contestando: era lo que pasaba hasta que vencía el TTL."""
    _limpiar("demo")
    try:
        qa_id = _crear_qa(client, portal_cookies, "Tenéis parking?", "Sí, gratuito.")
        assert "Tenéis parking?" in _respuestas("demo"), "no se ve lo recién creado"

        borrada = client.delete("/auth/app/qa/%s" % qa_id, cookies=portal_cookies)
        assert borrada.status_code == 200, borrada.text
        assert "Tenéis parking?" not in _respuestas("demo")
    finally:
        _limpiar("demo")


def test_editar_una_qa_se_ve_en_la_siguiente_consulta(client, portal_cookies):  # noqa: F811
    _limpiar("demo")
    try:
        qa_id = _crear_qa(client, portal_cookies, "Tenéis parking?", "Sí, gratuito.")
        assert _respuestas("demo")["Tenéis parking?"] == "Sí, gratuito."

        editada = client.patch(
            "/auth/app/qa/%s" % qa_id, cookies=portal_cookies,
            json={"answer": "Ya no tenemos parking propio, hay uno público al lado."},
        )
        assert editada.status_code == 200, editada.text
        assert _respuestas("demo")["Tenéis parking?"].startswith("Ya no tenemos")
    finally:
        _limpiar("demo")


def test_el_otro_worker_tambien_se_entera(client, portal_cookies):  # noqa: F811
    """La prueba de fuego: el cambio entra por la BD, sin pasar por este proceso.

    Es lo que ocurre de verdad con varios workers: el POST del panel lo atiende
    uno y el mensaje siguiente le cae a otro. Aquí se escribe directamente en la
    tabla —como habría hecho ese otro proceso— y NADIE vacía este diccionario.
    """
    from backend import db

    _limpiar("demo")
    try:
        _crear_qa(client, portal_cookies, "Tenéis parking?", "Sí, gratuito.")
        assert _respuestas("demo")["Tenéis parking?"] == "Sí, gratuito."

        with db._get_db_connection() as conexion:
            conexion.execute(
                "UPDATE kb_qa SET answer = ?, updated_at = ? WHERE cliente_id = ?",
                ("Ahora es de pago.", "2099-01-01T00:00:00Z", "demo"),
            )
            conexion.commit()

        assert _respuestas("demo")["Tenéis parking?"] == "Ahora es de pago."
    finally:
        _limpiar("demo")


def test_dos_guardados_en_el_mismo_segundo(client, portal_cookies, monkeypatch):  # noqa: F811
    """El sello lleva fecha, y la fecha va al segundo: aquí no distingue nada.

    Se congela el reloj y se edita conservando el largo del texto, así que la
    huella de la tabla sale idéntica. Lo que salva el caso es el vaciado local
    del CRUD (`intents.olvidar_tenant`), que es para lo que está.
    """
    from backend import timeutils

    _limpiar("demo")
    monkeypatch.setattr(timeutils, "_utc_now_iso", lambda: "2026-09-12T10:00:00Z")
    try:
        qa_id = _crear_qa(client, portal_cookies, "Tenéis parking?", "AAAA")
        assert _respuestas("demo")["Tenéis parking?"] == "AAAA"

        editada = client.patch(
            "/auth/app/qa/%s" % qa_id, cookies=portal_cookies, json={"answer": "BBBB"},
        )
        assert editada.status_code == 200, editada.text
        assert _respuestas("demo")["Tenéis parking?"] == "BBBB"
    finally:
        _limpiar("demo")


# ─── Catálogo: activar, desactivar y renombrar ─────────────────────────────

@pytest.fixture()
def servicio_temporal(client, portal_cookies):  # noqa: F811
    """Un servicio de este tenant, borrado pase lo que pase."""
    from backend import appstate

    creado = client.post(
        "/auth/services", cookies=portal_cookies,
        json={"nombre": "Masajes descontracturantes", "duration_minutes": 60,
              "price_cents": 5000, "descripcion": "", "is_active": True},
    )
    assert creado.status_code == 200, creado.text
    slug = creado.json()["id"]
    with appstate.state_lock:
        appstate.intent_cache.clear()
    try:
        yield slug
    finally:
        client.delete("/auth/services/%s" % slug, cookies=portal_cookies)
        with appstate.state_lock:
            appstate.intent_cache.clear()


def test_desactivar_un_servicio_lo_saca_de_las_familias(client, portal_cookies, servicio_temporal):  # noqa: F811
    from backend import intents

    assert "masajes" in intents.familias_del_tenant("demo")

    apagado = client.patch(
        "/auth/services/%s" % servicio_temporal, cookies=portal_cookies,
        json={"is_active": False},
    )
    assert apagado.status_code == 200, apagado.text
    assert "masajes" not in intents.familias_del_tenant("demo"), (
        "el asistente sigue ofreciendo una familia que el negocio ha desactivado"
    )


def test_renombrar_un_servicio_cambia_la_familia(client, portal_cookies, servicio_temporal):  # noqa: F811
    from backend import intents

    assert "masajes" in intents.familias_del_tenant("demo")

    renombrado = client.patch(
        "/auth/services/%s" % servicio_temporal, cookies=portal_cookies,
        json={"nombre": "Drenaje linfático"},
    )
    assert renombrado.status_code == 200, renombrado.text
    familias = intents.familias_del_tenant("demo")
    assert "drenaje" in familias and "masajes" not in familias


def test_borrar_un_servicio_lo_saca_de_las_familias(client, portal_cookies, servicio_temporal):  # noqa: F811
    from backend import intents

    assert "masajes" in intents.familias_del_tenant("demo")

    borrado = client.delete("/auth/services/%s" % servicio_temporal, cookies=portal_cookies)
    assert borrado.status_code == 200, borrado.text
    assert "masajes" not in intents.familias_del_tenant("demo")


# ─── Nadie toca la configuración del vecino ────────────────────────────────

def test_el_otro_negocio_conserva_lo_suyo(client, portal_cookies):  # noqa: F811
    """Multi-tenant: editar en "demo" no cambia ni tira lo del tenant de control."""
    from backend import appstate, db, intents, timeutils

    _limpiar("demo", CONTROL)
    try:
        with db._get_db_connection() as conexion:
            ahora = timeutils._utc_now_iso()
            conexion.execute(
                "INSERT INTO kb_qa (id, cliente_id, question, answer, tags_json,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, '[]', ?, ?)",
                ("qa_control", CONTROL, "Abrís los domingos?", "No, cerramos.", ahora, ahora),
            )
            conexion.commit()

        qa_id = _crear_qa(client, portal_cookies, "Tenéis parking?", "Sí, gratuito.")
        assert _respuestas(CONTROL) == {"Abrís los domingos?": "No, cerramos."}
        assert "Tenéis parking?" in _respuestas("demo")

        client.patch("/auth/app/qa/%s" % qa_id, cookies=portal_cookies,
                     json={"answer": "Ahora es de pago."})

        assert _respuestas(CONTROL) == {"Abrís los domingos?": "No, cerramos."}
        with appstate.state_lock:
            guardadas = list(appstate.intent_cache)
        assert any(clave.startswith("preguntas|%s|" % CONTROL) for clave in guardadas), (
            "se ha tirado la memoria de un tenant que nadie ha tocado"
        )
        assert intents.preguntas_del_tenant("demo")[0]["answer"] == "Ahora es de pago."
    finally:
        _limpiar("demo", CONTROL)


# ─── La clasificación cacheada se lleva dentro la respuesta ────────────────

def _modelo_falso(monkeypatch, respuesta_json):
    """Stub del SDK de OpenAI: clasificar no puede depender de la red en un test."""
    class _Mensaje:
        content = respuesta_json

    class _Choice:
        message = _Mensaje()

    class _Respuesta:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):
            return _Respuesta()

    class _Chat:
        completions = _Completions()

    class _Cliente:
        def __init__(self, *a, **k):
            self.chat = _Chat()

    modulo = types.ModuleType("openai")
    modulo.OpenAI = _Cliente
    monkeypatch.setitem(sys.modules, "openai", modulo)


def test_una_clasificacion_guardada_no_repite_una_respuesta_borrada(
    client, portal_cookies, monkeypatch,  # noqa: F811
):
    """Lo más caro de todo: contestar diez minutos con una Q&A que ya no existe."""
    from backend import intents

    _limpiar("demo")
    monkeypatch.setattr(intents, "enabled_for", lambda *a, **k: True)
    monkeypatch.setattr(intents.settings, "OPENAI_API_KEY", "sk-test")
    _modelo_falso(monkeypatch, '{"intencion": "info", "familia": "",'
                               ' "pregunta": 1, "confianza": 0.9}')
    try:
        qa_id = _crear_qa(client, portal_cookies, "Tenéis parking?", "Sí, gratuito.")
        primera = intents.classify("demo", "puedo dejar el coche en algun sitio")
        assert primera and primera["qa_answer"] == "Sí, gratuito."

        borrada = client.delete("/auth/app/qa/%s" % qa_id, cookies=portal_cookies)
        assert borrada.status_code == 200, borrada.text

        segunda = intents.classify("demo", "puedo dejar el coche en algun sitio")
        assert not (segunda or {}).get("qa_answer"), (
            "se sigue contestando con una Q&A que el negocio ha borrado"
        )
    finally:
        _limpiar("demo")
