# -*- coding: utf-8 -*-
"""La prueba de la dueña del salón por WhatsApp del 15-sep-2026, fallo a fallo.

POR QUE EXISTE
--------------
15-sep-2026, 00:15-00:34. Pidió unas mechas, dio el largo, cambió de idea («pues quiero un grey
blindin»), dio largo, «por las mañanas» y «jueves 17 a las 10:30». Pasó esto:

1. El freno de varios servicios leyó mechas + grey y rechazó la cita tres veces; el agente le
   preguntó «¿cuál de los dos prefieres?» (el freno: `test_varios_servicios_una_cita.py`).
2. Tres segundos después, en el MISMO turno, WhatsApp le mandó el resumen con botones, porque el
   estado estaba completo. Confirmó sin contestar la pregunta.
3. La cita salió con Jose, que no hace grey blending (eso eran datos del equipo: se corrigieron
   en producción desde su Excel).
4. «En la agenda no es necesario que aparezcan los precios»: se pintaban en cada cita.

Aquí se vigilan el 2 y el 4, y que la clienta no vea precios en su página de la cita si el
negocio no los da.
"""
from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from test_agenda_por_pasos import _coger, pack_con_pasos  # noqa: F401
from test_booking_exhaustive import api_module, client  # noqa: F401

ARGUMENTOS = {"servicio": "Pack grey blending medio", "fecha": "2099-09-17", "hora": "10:30",
              "nombre": "Ana Ruiz Perez"}


# ─── 2. Pregunta y resumen a la vez ────────────────────────────────────────

def test_el_rechazo_de_crear_la_cita_queda_anotado_y_la_propuesta_lo_limpia(api_module):  # noqa: F811
    from backend import reserva

    estado = reserva.Estado()
    antes = time.time()
    reserva.anotar_resultado(estado, "crear_cita", dict(ARGUMENTOS),
                             {"ok": False, "conserva_los_datos": True, "error": "Ha pedido varias cosas"})
    assert estado.creacion_rechazada_en >= antes
    reserva.anotar_resultado(estado, "crear_cita", dict(ARGUMENTOS),
                             {"ok": False, "pendiente_de_confirmacion": True})
    assert estado.creacion_rechazada_en == 0.0


def test_el_nombre_inventado_no_llega_al_resumen(api_module):  # noqa: F811
    """Medido al repetir la prueba con modelo real: el modelo llamó a crear_cita con «Maria Garcia»
    (nadie lo dijo), el freno de apellidos lo conservó, y cuando ella dijo su nombre el resumen salió
    a nombre de Maria Garcia. El nombre de la cita que va a confirmar manda."""
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_resultado(estado, "crear_cita", dict(ARGUMENTOS, nombre="Maria Garcia"), {
        "ok": False, "conserva_los_datos": True, "nombre_no_dicho": True, "error": "Faltan apellidos"})
    assert estado.nombre == "", "guardó un nombre que ella no dijo"
    reserva.anotar_resultado(estado, "crear_cita", dict(ARGUMENTOS, nombre="Ana Ruiz Perez"),
                             {"ok": False, "pendiente_de_confirmacion": True})
    assert estado.nombre == "Ana Ruiz Perez"


def test_un_nombre_distinto_del_modelo_no_pisa_el_que_ya_se_sabe(api_module):  # noqa: F811
    """Revisión de Codex a 0beeb96: un nombre alucinado con apellido no puede sustituir en el resumen
    al que ya se sabía (de su teléfono o dicho por ella)."""
    from backend import reserva

    estado = reserva.Estado()
    estado.nombre = "Ana Ruiz Perez"
    reserva.anotar_resultado(estado, "crear_cita", dict(ARGUMENTOS, nombre="Maria Garcia Lopez"),
                             {"ok": False, "pendiente_de_confirmacion": True, "nombre_dicho": False})
    assert estado.nombre == "Ana Ruiz Perez"


def test_la_cita_para_otra_persona_va_a_su_nombre(api_module):  # noqa: F811
    """Revisión de Codex a 7f3f1d0: «la cita es para mi hija Laura Garcia Lopez» con la madre ya
    conocida se quedaba a nombre de la madre."""
    from backend import agent, reserva

    dicho = "Hola, quiero cita para un corte. La cita es para mi hija Laura Garcia Lopez"
    assert agent._nombre_aparece_en(dicho, "Laura Garcia Lopez")
    assert not agent._nombre_aparece_en(dicho, "Maria Garcia Lopez")
    estado = reserva.Estado()
    estado.nombre = "Ana Ruiz Perez"
    reserva.anotar_resultado(estado, "crear_cita", dict(ARGUMENTOS, nombre="Laura Garcia Lopez"),
                             {"ok": False, "pendiente_de_confirmacion": True, "nombre_dicho": True})
    assert estado.nombre == "Laura Garcia Lopez"


def test_el_freno_de_apellidos_marca_el_nombre_que_ella_no_dijo(api_module, monkeypatch):  # noqa: F811
    from backend import agent, clients

    monkeypatch.setattr(clients, "exige_dos_apellidos", lambda cliente_id: True)
    inventado = asyncio.run(agent._ejecutar(
        "demo", "crear_cita", dict(ARGUMENTOS, nombre="Maria Garcia"), telefono="34600111999",
        remate_manual=True, dicho="Pues quiero un grey blending. Y prefiero antes de mediodia"))
    assert inventado.get("conserva_los_datos") and inventado.get("nombre_no_dicho") is True, inventado
    dicho = asyncio.run(agent._ejecutar(
        "demo", "crear_cita", dict(ARGUMENTOS, nombre="Maria Garcia"), telefono="34600111999",
        remate_manual=True, dicho="me llamo Maria Garcia"))
    assert dicho.get("conserva_los_datos") and dicho.get("nombre_no_dicho") is False, dicho


@pytest.fixture
def turno_whatsapp(api_module, monkeypatch):  # noqa: F811
    from backend import agent, appstate, messaging, reserva, whatsapp

    numero = "346" + str(uuid.uuid4().int % 100000000).zfill(8)
    vistos = {"resumenes": 0, "textos": []}
    modo = {"rechaza": True}

    async def responder(cliente_id, mensaje, **kw):
        # El agente de verdad llama a crear_cita y anota lo que devuelve: aquí solo el modelo.
        estado = reserva.cargar(cliente_id, numero)
        estado.intencion = "reservar"
        estado.servicio = estado.servicio_exacto = ARGUMENTOS["servicio"]
        estado.nombre = ARGUMENTOS["nombre"]
        if modo["rechaza"]:
            reserva.anotar_resultado(estado, "crear_cita", dict(ARGUMENTOS), {
                "ok": False, "conserva_los_datos": True,
                "error": "Ha pedido varias cosas (mechas, grey) y no hay un servicio que las cubra."})
            texto = "¿Cuál de los dos servicios prefieres reservar?"
        else:
            reserva.anotar_resultado(estado, "crear_cita", dict(ARGUMENTOS),
                                     {"ok": False, "pendiente_de_confirmacion": True})
            texto = "Te paso el resumen para que lo confirmes."
        reserva.guardar(cliente_id, numero, estado)
        return texto, False

    async def resumen(**kw):
        vistos["resumenes"] += 1
        return True

    async def enviar(**kw):
        vistos["textos"].append(kw["text"])
        return True

    monkeypatch.setattr(agent, "disponible", lambda cliente_id: True)
    monkeypatch.setattr(agent, "responder", responder)
    monkeypatch.setattr(whatsapp, "_wa_resumen_para_confirmar", resumen)
    monkeypatch.setattr(whatsapp, "_wa_cita_recien_hecha", lambda *a, **k: "")
    monkeypatch.setattr(whatsapp, "_wa_registrar", lambda **k: "sesion-prueba")
    monkeypatch.setattr(messaging, "_send_whatsapp_text", enviar)
    flow = appstate.WAFlowState(cliente_id="demo", from_number=numero)

    def turno(dicho):
        return asyncio.run(whatsapp._wa_turno_del_agente(
            cliente_id="demo", phone_number_id="PN", from_number=numero, incoming_text=dicho,
            flow=flow, config={}, request=None))

    yield dict(turno=turno, vistos=vistos, modo=modo)
    whatsapp._wa_clear_flow("demo", numero)


def test_si_el_freno_rechaza_la_cita_no_sale_el_resumen_en_ese_turno(turno_whatsapp):
    t = turno_whatsapp
    assert t["turno"]("Jueves 17 a las 10:30") is True
    assert t["vistos"]["resumenes"] == 0, "le mandó el resumen a la vez que le preguntaba"
    assert any("prefieres" in texto for texto in t["vistos"]["textos"]), t["vistos"]["textos"]


def test_al_contestar_la_pregunta_si_sale_el_resumen(turno_whatsapp):
    t = turno_whatsapp
    t["turno"]("Jueves 17 a las 10:30")
    t["modo"]["rechaza"] = False
    t["turno"]("solo el grey blending")
    assert t["vistos"]["resumenes"] == 1


# ─── 4. Precios en la agenda y en la página de la cita ─────────────────────

def _con_config(monkeypatch, **booking):
    from backend import clients

    original = clients._get_client_config

    def config(*args, **kwargs):
        cfg = dict(original(*args, **kwargs))
        cfg["booking"] = dict(cfg.get("booking") or {}, **booking)
        return cfg

    monkeypatch.setattr(clients, "_get_client_config", config)


def test_la_agenda_no_ensena_precios_si_el_negocio_no_los_quiere(pack_con_pasos, monkeypatch):  # noqa: F811
    from backend import booking

    fila = _coger()
    assert booking._portal_booking_summary_from_row(fila).service_price_label, "sin la opción, como siempre"
    _con_config(monkeypatch, precios_en_agenda=False)
    resumen = booking._portal_booking_summary_from_row(fila)
    assert resumen.service_price_label == ""
    # La ficha de Gestionar cita no lo pinta (revisión de Codex a 0beeb96), pero el importe se queda
    # para cobrar y el TPV (revisión de Codex a 7f3f1d0).
    assert resumen.precios_en_agenda is False
    assert resumen.service_price_cents > 0


def test_la_ficha_de_gestionar_cita_respeta_los_precios_ocultos():
    from pathlib import Path

    panel = (Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")
    assert "precios_en_agenda === false" in panel, "la ficha de Gestionar cita sigue pintando el precio"


def test_la_pagina_de_la_cita_no_ensena_precio_si_el_negocio_no_los_da(pack_con_pasos, monkeypatch):  # noqa: F811
    from backend import booking

    fila = _coger()
    detalle = booking._booking_public_detail_from_row(fila)
    precio = detalle.service_price_label
    assert precio and ("min · " + precio) in booking._booking_manage_page(detalle)
    _con_config(monkeypatch, mostrar_precios=False)
    oculto = booking._booking_public_detail_from_row(fila)
    assert oculto.service_price_label == ""
    assert ("min · " + precio) not in booking._booking_manage_page(oculto)


def test_el_negocio_tampoco_ve_el_precio_en_la_pagina_si_lo_quito_de_la_agenda(pack_con_pasos, monkeypatch):  # noqa: F811
    from backend import booking

    fila = _coger()
    detalle = booking._booking_public_detail_from_row(fila)
    precio = detalle.service_price_label
    _con_config(monkeypatch, precios_en_agenda=False)
    assert ("min · " + precio) not in booking._booking_manage_page(detalle, viewer="client")
