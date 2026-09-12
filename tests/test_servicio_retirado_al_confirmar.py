# -*- coding: utf-8 -*-
"""Un servicio retirado entre la oferta y el "sí" NO es un hueco ocupado.

EL FALLO (revisión de afecf80, hallazgo 2)
------------------------------------------
`booking._create_booking_core` ya rechazaba crear una cita de un servicio que el
negocio acaba de desactivar en el panel, pero con un 409 idéntico al del hueco
ocupado. Y los canales traducen TODO 409 a "ese hueco se ha ocupado, tengo estas
otras horas": la clienta elige otra hora, vuelve a chocar con el mismo servicio
retirado, y así hasta irse sin cita y sin saber por qué.

- WhatsApp, flujo guiado con profesional elegida: `_wa_create_booking` no
  revalida el servicio contra esa profesional, llega al núcleo y contestaba
  "Ese hueco se acaba de ocupar" + tres horas.
- Voz y texto (el agente usa la misma tool `crear_cita`): la resolución de
  profesional falla antes con "No hay profesionales disponibles...", el canal lo
  casaba con `horario|disponible|hueco` y devolvía horas.

Lo que se exige: un error DISTINGUIBLE (contrato compartido del núcleo), que diga que
ese servicio ya no está, que deje elegir otro servicio y que no ofrezca horas. El
mostrador (`portal_manual`) sigue pudiendo apuntarlo a mano.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest

from test_booking_exhaustive import _run_async, api_module, client  # noqa: F401
from test_crm_light import portal_cookies  # noqa: F401

CID = "demo"
RETIRADO = "Masaje retirado"
OTRO = "Corte de prueba"
UNA_HORA = re.compile(r"\b\d{1,2}:\d{2}\b")


def _dia_habil(desplazamiento: int = 3) -> str:
    dia = date.today() + timedelta(days=desplazamiento)
    while dia.weekday() == 6:  # el tenant de pruebas cierra los domingos
        dia += timedelta(days=1)
    return dia.isoformat()


def _citas_de(nombre: str):
    from backend import db

    with db._get_db_connection() as conexion:
        return conexion.execute(
            "SELECT id FROM bookings WHERE cliente_id = ? AND nombre = ?", (CID, nombre),
        ).fetchall()


@pytest.fixture()
def catalogo(client, portal_cookies):  # noqa: F811
    """Dos servicios y una profesional que hace los dos. Se borra todo al acabar."""
    from backend import db

    slugs = []
    for nombre in (RETIRADO, OTRO):
        creado = client.post("/auth/services", cookies=portal_cookies, json={
            "nombre": nombre, "duration_minutes": 30, "price_cents": 3000,
            "descripcion": "", "is_active": True,
        })
        assert creado.status_code == 200, creado.text
        slugs.append(creado.json()["id"])
    empleada = client.post("/auth/employees", cookies=portal_cookies, json={
        "name": "Laura Retiro", "role_label": "QA", "color": "#00b1d9", "is_active": True,
        "timezone": "Europe/Madrid", "slot_minutes": 30, "day_start": "09:00",
        "day_end": "18:00", "break_windows": [], "closed_weekdays": [6],
        "service_ids": slugs,
    })
    assert empleada.status_code == 200, empleada.text
    datos = {"retirado": slugs[0], "otro": slugs[1], "empleada": empleada.json()["employee_id"]}
    try:
        yield datos
    finally:
        with db._get_db_connection() as conexion:
            ids = [f["id"] for f in conexion.execute(
                "SELECT id FROM bookings WHERE cliente_id = ? AND nombre LIKE 'Retiro %'", (CID,))]
            for booking_id in ids:
                conexion.execute("DELETE FROM booking_audit WHERE booking_id = ?", (booking_id,))
                conexion.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
            conexion.commit()
        client.delete("/auth/employees/%s" % datos["empleada"], cookies=portal_cookies)
        for slug in slugs:
            client.delete("/auth/services/%s" % slug, cookies=portal_cookies)


def _retirar(client, portal_cookies, slug):  # noqa: F811
    apagado = client.patch("/auth/services/%s" % slug, cookies=portal_cookies,
                           json={"is_active": False})
    assert apagado.status_code == 200, apagado.text


# ─── Núcleo: dos 409 distintos ─────────────────────────────────────────────

def test_el_nucleo_distingue_servicio_retirado_de_hueco_ocupado(client, portal_cookies, catalogo):  # noqa: F811
    from fastapi import HTTPException

    from backend import agenda, booking

    fecha = _dia_habil()
    empleada = agenda._resolve_employee_for_booking(CID, catalogo["empleada"])

    def crear(servicio, source, hora, telefono):
        return _run_async(booking._create_booking_core(
            CID, employee_row=empleada, nombre="Retiro Nucleo", email="",
            telefono=telefono, servicio=servicio, booking_date=fecha, booking_time=hora,
            source=source, send_confirmation=False,
        ))

    crear(OTRO, "voice", "11:00", "600111401")
    with pytest.raises(HTTPException) as ocupado:
        crear(OTRO, "whatsapp", "11:00", "600111402")
    assert ocupado.value.status_code == 409
    assert not booking.es_servicio_retirado(ocupado.value.detail), (
        "un hueco ocupado no puede leerse como servicio retirado"
    )

    _retirar(client, portal_cookies, catalogo["retirado"])
    booking.validar_servicio_publico(CID, OTRO)
    with pytest.raises(HTTPException) as retirado:
        crear(RETIRADO, "voice", "12:00", "600111403")
    assert booking.es_servicio_retirado(retirado.value.detail)
    # Para el widget y el portal sigue siendo un 409 con el mismo texto.
    assert retirado.value.status_code == 409
    assert "Ese servicio ya no esta disponible" in str(retirado.value.detail)

    fila = crear(RETIRADO, "portal_manual", "12:00", "600111403")  # el mostrador sí puede
    assert fila["servicio"] == RETIRADO


# ─── Voz y texto: la misma tool `crear_cita` ───────────────────────────────

@pytest.mark.parametrize("profesional", ["", "Laura"])
def test_voz_y_texto_piden_otro_servicio_sin_ofrecer_horas(
    client, portal_cookies, catalogo, profesional,  # noqa: F811
):
    from backend import voice

    _retirar(client, portal_cookies, catalogo["retirado"])
    resultado = _run_async(voice._voice_dispatch_tool(CID, "crear_cita", json.dumps({
        "nombre": "Retiro Voz", "telefono": "600111404", "fecha": _dia_habil(),
        "hora": "11:00", "servicio": RETIRADO, "profesional": profesional,
    })))

    assert resultado["ok"] is False
    assert resultado.get("servicio_retirado") is True, resultado
    assert resultado.get("needs_service") is True, "el modelo tiene que pedir OTRO servicio"
    assert not resultado.get("no_disponible") and not resultado.get("huecos"), (
        "le ofrece horas para un servicio que ya no existe: es el bucle"
    )
    mensaje = resultado["mensaje_voz"]
    assert RETIRADO.lower() in mensaje.lower() and "ya no" in mensaje.lower(), mensaje
    assert "horario" not in mensaje.lower() and not UNA_HORA.search(mensaje), mensaje
    assert resultado["servicios_disponibles"], "sin alternativas no puede elegir otro"
    assert RETIRADO not in resultado["servicios_disponibles"]
    assert not _citas_de("Retiro Voz")


def test_voz_traduce_el_rechazo_del_nucleo_y_el_hueco_sigue_siendo_hueco(
    catalogo, monkeypatch,  # noqa: F811
):
    """Retirado justo entre la comprobación del canal y la escritura."""
    from fastapi import HTTPException

    from backend import booking, voice

    async def retirado_al_escribir(*_a, **_k):
        raise HTTPException(status_code=409, detail=booking.SERVICIO_RETIRADO)

    async def hueco_ocupado(*_a, **_k):
        raise HTTPException(status_code=409, detail="Ese horario ya no esta disponible. Elige otro tramo.")

    def reservar():
        return _run_async(voice._voice_perform_booking(
            CID, nombre="Retiro Carrera", telefono="600111405", fecha=_dia_habil(),
            hora="11:00", servicio=OTRO,
        ))

    monkeypatch.setattr(booking, "_create_booking_core", retirado_al_escribir)
    resultado = reservar()
    assert resultado.get("servicio_retirado") is True, resultado
    assert not resultado.get("huecos")

    monkeypatch.setattr(booking, "_create_booking_core", hueco_ocupado)
    resultado = reservar()
    assert resultado.get("no_disponible") is True, resultado
    assert not resultado.get("servicio_retirado")


# ─── WhatsApp guiado, con profesional elegida ──────────────────────────────

@pytest.fixture()
def whatsapp_falso(monkeypatch):
    from backend import messaging

    enviado = {"textos": [], "listas": [], "botones": []}

    async def texto(**kw):
        enviado["textos"].append(kw["text"])
        return True

    async def lista(**kw):
        enviado["listas"].append(kw)
        return True

    async def botones(**kw):
        enviado["botones"].append(kw)
        enviado["textos"].append(kw.get("body", ""))
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_text", texto)
    monkeypatch.setattr(messaging, "_send_whatsapp_list", lista)
    monkeypatch.setattr(messaging, "_send_whatsapp_buttons", botones)
    return enviado


def _filas(lista):
    return [fila["id"] for seccion in lista["sections"] for fila in seccion["rows"]]


def test_whatsapp_con_profesional_elegida_deja_elegir_otro_servicio(
    client, portal_cookies, catalogo, whatsapp_falso,  # noqa: F811
):
    from backend import appstate, whatsapp

    telefono = "34600111406"
    whatsapp._wa_clear_flow(CID, telefono)
    flow = whatsapp._wa_get_flow(CID, telefono)
    flow.flow = "booking_confirm"
    flow.servicio = RETIRADO
    flow.employee_id = catalogo["empleada"]
    flow.employee_name = "Laura Retiro"
    flow.fecha = _dia_habil()
    flow.hora = "11:00"
    flow.nombre = "Retiro Whatsapp"

    def pulsa(iid):
        _run_async(whatsapp._handle_whatsapp_message(
            cliente_id=CID, phone_number_id="WA_NUM_ID", from_number=telefono,
            incoming_text="", interactive_id=iid, request=None,
        ))

    def flujo():
        return appstate.whatsapp_flows.get(whatsapp._wa_flow_key(CID, telefono))

    _run_async(whatsapp._wa_send_booking_summary(cliente_id=CID, phone_number_id="WA_NUM_ID",
        to_number=telefono, flow=flow))
    confirmar = whatsapp_falso["botones"][-1]["buttons"][0][0]
    whatsapp_falso["textos"].clear()
    _retirar(client, portal_cookies, catalogo["retirado"])  # entre el resumen y el botón
    try:
        pulsa(confirmar)

        dicho = "\n".join(whatsapp_falso["textos"])
        assert "ocupar" not in dicho.lower(), dicho
        assert not UNA_HORA.search(dicho), "le ofrece horas para un servicio que ya no existe: bucle"
        assert RETIRADO in dicho and "ya no" in dicho.lower(), dicho
        assert not _citas_de("Retiro Whatsapp")

        assert whatsapp_falso["listas"], "no se le deja elegir otro servicio"
        filas = _filas(whatsapp_falso["listas"][-1])
        assert "svc_%s" % catalogo["otro"] in filas
        assert "svc_%s" % catalogo["retirado"] not in filas

        sigue = flujo()
        assert sigue is not None and sigue.flow == "booking_service", "se la manda a empezar de cero"
        assert not (sigue.servicio or sigue.employee_id or sigue.fecha or sigue.hora), (
            "profesional, día y hora dependían del servicio retirado"
        )
        assert sigue.nombre == "Retiro Whatsapp"

        pulsa("svc_%s" % catalogo["otro"])
        sigue = flujo()
        assert sigue is not None and sigue.servicio == OTRO
        assert sigue.flow in ("booking_employee", "booking_date"), sigue.flow
    finally:
        whatsapp._wa_clear_flow(CID, telefono)


def test_whatsapp_traduce_el_rechazo_del_nucleo_y_el_hueco_sigue_siendo_hueco(
    catalogo, whatsapp_falso, monkeypatch,  # noqa: F811
):
    from fastapi import HTTPException

    from backend import appstate, booking, clients, whatsapp

    async def retirado_al_escribir(*_a, **_k):
        raise HTTPException(status_code=409, detail=booking.SERVICIO_RETIRADO)

    async def hueco_ocupado(*_a, **_k):
        raise HTTPException(status_code=409, detail="Ese horario ya no esta disponible. Elige otro tramo.")

    def confirmar(telefono):
        flow = appstate.WAFlowState(
            cliente_id=CID, from_number=telefono, flow="booking_confirm", servicio=OTRO,
            employee_id=catalogo["empleada"], employee_name="Laura Retiro",
            fecha=_dia_habil(), hora="11:00", nombre="Retiro Carrera",
        )
        creada = _run_async(whatsapp._wa_create_booking(
            cliente_id=CID, phone_number_id="WA_NUM_ID", to_number=telefono, flow=flow,
            config=clients._get_client_config(CID), request=None,
        ))
        return creada, flow

    monkeypatch.setattr(booking, "_create_booking_core", retirado_al_escribir)
    creada, flow = confirmar("34600111407")
    assert creada is False
    assert "ocupar" not in whatsapp_falso["textos"][-1].lower()
    assert flow.flow == "booking_service" and whatsapp_falso["listas"]

    monkeypatch.setattr(booking, "_create_booking_core", hueco_ocupado)
    creada, flow = confirmar("34600111408")
    assert creada is False
    assert "ocupar" in whatsapp_falso["textos"][-1].lower(), "el hueco ocupado tiene su propio texto"
    assert flow.flow == "booking_confirm"
