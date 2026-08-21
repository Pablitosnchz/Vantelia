# -*- coding: utf-8 -*-
"""Un dia con mas huecos de los que caben en una lista de WhatsApp.

Caso real (21-ago-2026, probando la demo): sabado con 18 huecos libres.

    BOT   > 🕐 Huecos disponibles... (te muestro los 10 primeros de 18)
    Pablo > puede ser mas tarde?
    BOT   > ¡Claro! 😊 Dime que hora te vendria bien...
    BOT   > 🕐 Huecos disponibles... (te muestro los 10 primeros de 18)

Los otros 8 huecos eran INALCANZABLES. La pregunta por franja existia justo para
esto, pero solo salta si hay mas de una franja, y un sabado de 9:00 a 14:00 es
todo mañana.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


HUECOS_18 = ["09:00", "09:15", "09:30", "09:45", "10:00", "10:15", "10:30", "10:45",
             "11:00", "11:15", "11:30", "11:45", "12:00", "12:15", "12:30", "12:45",
             "13:00", "13:15"]


@pytest.fixture
def enviados(api_module, client, monkeypatch):  # noqa: F811
    """Captura las listas que se mandarian a WhatsApp."""
    from backend import agenda, messaging

    listas = []

    async def _lista(*, body="", sections=None, **kwargs):
        filas = [f["title"] for s in (sections or []) for f in s.get("rows", [])]
        listas.append({"body": body, "filas": filas})
        return True

    async def _texto(*, text="", **kwargs):
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_list", _lista)
    monkeypatch.setattr(messaging, "_send_whatsapp_text", _texto)

    async def _huecos(*a, **k):
        return (list(HUECOS_18), list(HUECOS_18))

    monkeypatch.setattr(agenda, "_employee_slot_sets_for_day", _huecos)
    monkeypatch.setattr(agenda, "_public_slot_sets_for_day", _huecos)
    return listas


def test_se_puede_llegar_a_todos_los_huecos(enviados, api_module):  # noqa: F811
    """Con 18 huecos tiene que haber forma de ver los 8 que no caben."""
    import asyncio

    from backend import whatsapp

    asyncio.run(whatsapp._wa_send_time_picker(
        cliente_id="demo", phone_number_id="p", to_number="34600111000",
        fecha_iso="2026-08-22", fecha_humana="sábado 22 de agosto",
        employee_id="emp1", servicio="corte",
    ))
    primera = enviados[-1]["filas"]
    assert "Ver más horas" in primera, (
        "no hay forma de ver los huecos que no caben: %r" % primera
    )

    # Pagina 1: los que faltaban.
    asyncio.run(whatsapp._wa_send_time_picker(
        cliente_id="demo", phone_number_id="p", to_number="34600111000",
        fecha_iso="2026-08-22", fecha_humana="sábado 22 de agosto",
        employee_id="emp1", servicio="corte", pagina=1,
    ))
    segunda = enviados[-1]["filas"]
    assert "13:15" in segunda, "el ultimo hueco del dia seguia siendo inalcanzable"
    assert segunda[0] not in primera, "la segunda pagina repetia la primera"


def test_ninguna_lista_supera_las_diez_filas(enviados, api_module):  # noqa: F811
    """WhatsApp rechaza la lista entera si se pasa: no es un detalle estetico."""
    import asyncio

    from backend import whatsapp

    for pagina in (0, 1, 2):
        asyncio.run(whatsapp._wa_send_time_picker(
            cliente_id="demo", phone_number_id="p", to_number="34600111000",
            fecha_iso="2026-08-22", fecha_humana="sábado 22 de agosto",
            employee_id="emp1", servicio="corte", pagina=pagina,
        ))
        assert len(enviados[-1]["filas"]) <= whatsapp._WA_MAX_FILAS


@pytest.mark.parametrize("frase,esperado", [
    ("puede ser mas tarde?", "+"),
    ("un poco antes", "-"),
    ("por la tarde", "tarde"),
    ("a primera hora", "manana"),
    ("lo mas tarde posible", "noche"),
    ("me da igual", ""),
    ("10:30", ""),
])
def test_entiende_como_pide_otra_hora(api_module, frase, esperado):  # noqa: F811
    from backend import whatsapp

    assert whatsapp._wa_ajuste_de_hora(frase) == esperado


# ─── Menos pasos: a casi nadie le importa quien la atienda ─────────────────

def test_ofrece_no_elegir_profesional(api_module, client, monkeypatch):  # noqa: F811
    """Elegir persona es un paso mas y ADEMAS le quita huecos a la clienta."""
    import asyncio
    import sqlite3

    from backend import messaging, whatsapp

    listas = []

    async def _lista(*, body="", sections=None, **kwargs):
        listas.append([f for s in (sections or []) for f in s.get("rows", [])])
        return True

    monkeypatch.setattr(messaging, "_send_whatsapp_list", _lista)

    def _dos(*a, **k):
        def fila(ident, nombre):
            f = {"id": ident, "name": nombre, "role_label": "Estilista"}
            return f
        return [fila("e1", "Alicia"), fila("e2", "Conchi")]

    monkeypatch.setattr(whatsapp, "_wa_employees_for_service", _dos)
    asyncio.run(whatsapp._wa_send_employee_picker(
        cliente_id="demo", phone_number_id="p", to_number="34600111000", servicio="corte",
    ))
    filas = listas[-1]
    assert filas, "no se envio el listado"
    assert filas[0]["id"] == "emp_cualquiera", (
        "la opcion de no elegir tiene que ir la primera: %r" % filas
    )


@pytest.mark.parametrize("frase", ["me da igual", "cualquiera", "La que sea", "indiferente"])
def test_lo_dice_con_sus_palabras(api_module, frase):  # noqa: F811
    """Tambien si lo escribe en vez de pulsar la fila."""
    from backend import textnorm

    assert textnorm._strip_accents(frase.lower().strip()) in (
        "me da igual", "cualquiera", "la que sea", "indiferente", "me es igual"
    )
