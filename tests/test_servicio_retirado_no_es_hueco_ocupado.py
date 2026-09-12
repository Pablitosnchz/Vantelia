# -*- coding: utf-8 -*-
"""Retirar un servicio no es quedarse sin hueco, y no se cuenta igual.

POR QUE EXISTE
--------------
El nucleo revalida la propuesta al ejecutarla: si el negocio ha retirado el
servicio desde el panel entre que se ofrecio y ella pulso Confirmar, no se coge
la cita. Correcto. El problema era el MOTIVO: ese 409 es identico al del hueco
ocupado, y los canales traducen cualquier 409 a "ese hueco se acaba de ocupar,
te doy otras horas".

Resultado, en WhatsApp con profesional elegido: 409 -> "se acaba de ocupar" + tres
horas reales -> ella elige otra -> 409 otra vez por lo mismo -> bucle. Se va sin
cita y sin enterarse de que lo que ya no esta es el SERVICIO. Por voz y por texto
libre (todos pasan por el dispatch de voz) pasaba igual.

Aqui se vigila que el motivo se pueda distinguir y que cada canal diga la verdad.
El MOSTRADOR sigue pudiendo apuntarlo a mano: retiran el servicio del catalogo
publico y se lo siguen haciendo a quien ya lo tenia hablado.
"""
from __future__ import annotations

import asyncio
import datetime
import uuid

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401

CID = "demo"


def _servicio_retirado(api_module, nombre):  # noqa: F811
    """Deja en el catalogo un servicio DESACTIVADO y devuelve su nombre."""
    from backend import db

    with db._get_db_connection() as cx:
        cx.execute(
            "INSERT OR REPLACE INTO services"
            " (cliente_id, slug, name, category, duration_minutes, price_cents,"
            "  is_active, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,0,?,?)",
            (CID, "retirado_%s" % uuid.uuid4().hex[:6], nombre, "", 30, 1000,
             "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
        cx.commit()
    return nombre


def _dia_con_hueco():
    """El primer dia con las 10:00 y las 12:00 libres. "Manana" a secas no vale.

    El negocio de pruebas cierra los domingos: con "manana" en fin de semana la
    reserva falla ANTES de llegar a lo que se vigila aqui, y el test acusaria al
    codigo de un cierre del calendario. Mismo criterio que la fixture de
    `test_estirar_la_cita`.
    """
    from backend import agenda, timeutils

    hoy = timeutils._utc_now().date()
    for salto in range(1, 15):
        dia = (hoy + datetime.timedelta(days=salto)).isoformat()
        libres = set(agenda._build_slots_for_day(CID, dia, duration_minutes=30) or [])
        if {"10:00", "12:00"} <= libres:
            return dia
    raise AssertionError("el negocio de pruebas no abre ningun dia con 10:00 y 12:00")


def test_el_nucleo_distingue_el_motivo(api_module):  # noqa: F811
    """Sin poder distinguirlo, el canal no puede decir la verdad."""
    from fastapi import HTTPException

    from backend import agenda, booking

    nombre = _servicio_retirado(api_module, "Masaje retirado")
    empleado = agenda._resolve_employee_for_booking(CID, "", require_active=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(booking._create_booking_core(
            CID, employee_row=empleado, nombre="Ana Ruiz Perez", email="",
            telefono="34600111222", servicio=nombre, booking_date=_dia_con_hueco(),
            booking_time="10:00", notas="", source="whatsapp", send_confirmation=False,
        ))

    assert exc.value.status_code == 409
    assert booking.es_servicio_retirado(exc.value.detail) is True
    # Y lo contrario: el 409 del hueco NO puede confundirse con este.
    assert booking.es_servicio_retirado(
        "Ese horario ya no esta disponible. Elige otro tramo.") is False


def test_por_whatsapp_no_le_ofrece_horas_de_un_servicio_que_no_esta(api_module, monkeypatch):  # noqa: F811
    """El caso medido: con profesional elegido, acababa en bucle de horas."""
    from fastapi import HTTPException, status

    from backend import appstate, booking, messaging, whatsapp

    nombre = _servicio_retirado(api_module, "Masaje retirado wa")
    enviados = []

    async def _capturar(**kwargs):
        enviados.append(kwargs.get("text") or "")
        return True

    async def _retirado(*args, **kwargs):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=booking.SERVICIO_RETIRADO)

    monkeypatch.setattr(messaging, "_send_whatsapp_text", _capturar)
    monkeypatch.setattr(booking, "_create_booking_core", _retirado)

    from backend import agenda

    flow = appstate.WAFlowState(cliente_id=CID, from_number="34600111333")
    # Con profesional elegido, que es el caso medido: asi se va derecha al nucleo
    # y el 409 que llega es el del servicio, no el de "no queda nadie libre".
    flow.employee_id = agenda._resolve_employee_for_booking(
        CID, "", require_active=False)["id"]
    flow.servicio = nombre
    flow.fecha = _dia_con_hueco()
    flow.hora = "10:00"
    flow.nombre = "Ana Ruiz Perez"
    flow.email = ""

    ok = asyncio.run(whatsapp._wa_create_booking(
        cliente_id=CID, phone_number_id="pn_test", to_number=flow.from_number,
        flow=flow, config={}, request=None,
    ))

    assert ok is False
    texto = " ".join(enviados).lower()
    assert "servicio ya no está disponible" in texto, texto
    assert "se acaba de ocupar" not in texto, "le dice que es el hueco: vuelve a elegir hora"
    assert ":" not in texto.split("disponible")[-1][:40] or "hueco" not in texto, (
        "le sigue ofreciendo horas de un servicio que no existe")


def test_por_voz_y_texto_libre_tampoco_se_ofrecen_horas(api_module, monkeypatch):  # noqa: F811
    """Voz, chat y WhatsApp por texto libre pasan todos por este dispatch."""
    from fastapi import HTTPException, status

    from backend import booking, voice

    async def _retirado(*args, **kwargs):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=booking.SERVICIO_RETIRADO)

    monkeypatch.setattr(booking, "_create_booking_core", _retirado)

    resultado = asyncio.run(voice._voice_perform_booking(
        CID, nombre="Ana Ruiz Perez", telefono="34600111444", fecha=_dia_con_hueco(),
        hora="10:00", servicio="Masaje retirado voz",
    ))

    assert resultado.get("ok") is False
    assert resultado.get("servicio_retirado") is True, resultado
    assert not resultado.get("huecos"), "le ofrece horas de un servicio retirado"
    assert "hora" in (resultado.get("que_hacer") or "").lower()


def test_el_mostrador_lo_sigue_pudiendo_apuntar(api_module):  # noqa: F811
    """La regla del negocio: lo retiran del catalogo publico y lo siguen haciendo
    a quien ya lo tenia hablado. Desde el panel no se frena."""
    from backend import agenda, booking

    nombre = _servicio_retirado(api_module, "Masaje retirado mostrador")
    empleado = agenda._resolve_employee_for_booking(CID, "", require_active=False)

    creada = asyncio.run(booking._create_booking_core(
        CID, employee_row=empleado, nombre="Ana Ruiz Perez", email="",
        telefono="34600111555", servicio=nombre, booking_date=_dia_con_hueco(),
        booking_time="12:00", notas="", source="portal_manual", send_confirmation=False,
    ))

    assert creada["id"], "el mostrador ya no puede apuntar lo que tenia hablado"
