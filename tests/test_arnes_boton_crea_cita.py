"""Oferta y nucleo reales sobre agenda sintetica; ningun modelo ni transporte."""
import asyncio
import copy
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from conftest import DEFAULT_DEMO_CONFIG
from evals import arnes


@pytest.fixture
def entorno(vantelia_env_factory, monkeypatch):
    vantelia_env_factory(copy.deepcopy(DEFAULT_DEMO_CONFIG))
    from backend import agenda, booking, db, emailing, messaging, whatsapp

    # Registrar originales: la captura legacy sustituye funciones globales.
    for modulo, nombres in ((messaging, ("_send_whatsapp_text", "_send_whatsapp_buttons",
        "_send_whatsapp_list", "_send_whatsapp_cta_url", "_send_whatsapp_payload", "_send_client_sms")),
        (booking, ("_send_booking_to_webhook",)), (emailing, ("_send_client_email",))):
        for nombre in nombres:
            monkeypatch.setattr(modulo, nombre, getattr(modulo, nombre))
    arnes.cortar_el_mundo_exterior()
    with db._get_db_connection() as conn:
        conn.execute("INSERT INTO services (cliente_id,slug,name,duration_minutes,price_cents,created_at) "
                     "VALUES ('demo','corte-prueba','Corte de prueba',30,2000,'2026-01-01')")
        empleado = conn.execute("SELECT * FROM employees WHERE cliente_id='demo' AND is_active=1").fetchone()
    for adelanto in range(2, 9):
        dia = (date.today() + timedelta(days=adelanto)).isoformat()
        huecos = asyncio.run(agenda._available_slots_for_day("demo", dia))
        if huecos:
            break
    assert empleado and huecos
    post = []
    async def prohibido(*args, **kwargs):
        post.append(kwargs)
        raise AssertionError("el arnes intento enviar a Meta")
    monkeypatch.setattr(messaging.httpx.AsyncClient, "post", prohibido)
    monkeypatch.setattr(messaging, "_whatsapp_access_token_for_client", lambda *a: "token-sintetico")
    original = whatsapp._handle_whatsapp_message
    async def manejar(**kwargs):
        if kwargs["incoming_text"] == "preparar oferta sintetica":
            flow = whatsapp._wa_get_flow(kwargs["cliente_id"], kwargs["from_number"])
            flow.nombre, flow.servicio = "Ana Prueba", "Corte de prueba"
            flow.fecha, flow.hora = dia, huecos[0]
            flow.employee_id, flow.employee_name = empleado["id"], empleado["name"]
            await whatsapp._wa_send_booking_summary(cliente_id="demo", phone_number_id="PN",
                to_number=kwargs["from_number"], flow=flow)
            assert arnes.citas_de("demo", kwargs["from_number"]) == []
        else:
            await original(**kwargs)
    monkeypatch.setattr(whatsapp, "_handle_whatsapp_message", manejar)
    return SimpleNamespace(dia=dia, hora=huecos[0], post=post)


def test_humo_accion_expresa_crea_una_cita_con_el_boton_real(entorno):
    from scripts import humo
    conversacion = humo._hablar("demo", "34600111001", [
        "preparar oferta sintetica", {"accion": "aceptar_oferta"}])
    entrada = [t for t in conversacion if t["quien"] == "clienta"][-1]
    citas = arnes.citas_de("demo", "34600111001")
    assert len(citas) == 1
    assert entrada["interactive_id"].startswith("confirm_yes:")
    assert (citas[0]["booking_date"], citas[0]["booking_time"]) == (entorno.dia, entorno.hora)
    assert entorno.post == []


def test_simulada_con_id_inventado_falla_sin_corregirlo(entorno, monkeypatch):
    from scripts import simular_clientas
    monkeypatch.setattr(simular_clientas, "_hablar_como_clienta", lambda *a: '{"boton":"confirm_yes:inventado"}')
    combinacion = {"id": "prueba", "estilo": "normal", "persona": {
        "id": "prueba", "objetivo": "reservar", "familia": "corte", "quiere": "un corte"}}
    resultado = simular_clientas._conversar("demo", combinacion, "34600111004")
    assert resultado["veredicto"] == "fallo"
    assert resultado["fallos"] == ["accion_no_disponible"]
    assert arnes.citas_de("demo", "34600111004") == []
    assert entorno.post == []


def test_simulada_elige_id_presentado_sin_modelo(entorno, monkeypatch):
    from scripts import simular_clientas
    recibidas = []
    def clienta(guion, conversacion, opciones):
        recibidas.append(opciones)
        if not conversacion:
            return "preparar oferta sintetica"
        if len(recibidas) == 2:
            return json.dumps({"boton": next(o["id"] for o in opciones if "_yes:" in o["id"])})
        return "LISTO"
    monkeypatch.setattr(simular_clientas, "_hablar_como_clienta", clienta)
    monkeypatch.setattr(simular_clientas, "_juzgar", lambda *a: a[3])
    combinacion = {"id": "prueba", "estilo": "normal", "persona": {
        "id": "prueba", "objetivo": "reservar", "familia": "corte", "quiere": "un corte"}}
    conversacion = simular_clientas._conversar("demo", combinacion, "34600111002")
    entrada = [t for t in conversacion if t["quien"] == "clienta"][-1]
    assert entrada["interactive_id"] in [o["id"] for o in recibidas[1]]
    assert len(arnes.citas_de("demo", "34600111002")) == 1
    assert entorno.post == []


def test_captura_detailed_rechaza_payload_sin_post(entorno, monkeypatch):
    from backend import booking, messaging, wa_plantillas
    captura = arnes.capturar_envios()
    resultado = asyncio.run(messaging._send_whatsapp_payload(
        cliente_id="demo", phone_number_id="PN", payload={"to": "34600111003"}, detailed=True))
    assert resultado.estado == "rechazado"
    assert captura == []
    assert captura.eventos[-1]["enviado"] is False
    monkeypatch.setattr(wa_plantillas, "estado", lambda *a: {
        "status": wa_plantillas.APROBADA, "name": wa_plantillas.NOMBRE_RECORDATORIO})
    resultado = asyncio.run(booking._enviar_recordatorio_con_plantilla(
        {"id": "cita-sintetica", "cliente_id": "demo", "nombre": "Ana",
         "servicio": "Corte de prueba", "booking_date": entorno.dia, "booking_time": entorno.hora},
        "reminder_24h", phone_number_id="PN", to_number="34600111003", detailed=True))
    assert resultado.estado == "rechazado"
    assert resultado.template_name == wa_plantillas.NOMBRE_RECORDATORIO
    assert entorno.post == []


def test_captura_admite_diccionario_que_normaliza_el_builder(entorno, monkeypatch):
    from backend import messaging
    monkeypatch.setattr(arnes, "_propuesta_vigente", lambda *a: {"id": "actual", "estado": "ofrecida"})
    captura = arnes.capturar_envios()
    assert asyncio.run(messaging._send_whatsapp_buttons(
        cliente_id="demo", phone_number_id="PN", to_number="600", body="Resumen",
        buttons=[{"id": "confirm_yes:actual", "title": "Confirmar"}])) is True
    assert captura.opciones("demo", "600") == [{"id": "confirm_yes:actual", "titulo": "Confirmar"}]
    nueva = arnes.capturar_envios()
    assert asyncio.run(messaging._send_whatsapp_buttons(
        cliente_id="demo", phone_number_id="PN", to_number="600", body="Otro resumen",
        buttons=[{"id": "confirm_yes:actual", "title": "Confirmar"}])) is True
    assert len(captura.eventos) == 1
    assert nueva == ["Otro resumen"]
    assert entorno.post == []


def test_cuarto_boton_descartado_no_es_una_accion_emitida(entorno, monkeypatch):
    from backend import messaging
    monkeypatch.setattr(arnes, "_propuesta_vigente", lambda *a: {"id": "actual", "estado": "ofrecida"})
    captura = arnes.capturar_envios()
    assert asyncio.run(messaging._send_whatsapp_buttons(
        cliente_id="demo", phone_number_id="PN", to_number="600", body="Resumen",
        buttons=[("a", "A"), ("b", "B"), ("c", "C"), ("confirm_yes:actual", "Confirmar")])) is True
    assert [b["id"] for b in captura.eventos[-1]["botones"]] == ["a", "b", "c"]
    with pytest.raises(arnes.AccionNoDisponible):
        arnes.preparar_entrada(captura, "demo", "600", {"boton": "confirm_yes:actual"})
    assert arnes.citas_de("demo", "600") == []
    assert entorno.post == []
