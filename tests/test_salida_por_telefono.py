# -*- coding: utf-8 -*-
"""Quien no quiere venir a que le vean el pelo, recibe un telefono al que llamar.

POR QUE EXISTE
--------------
Medido el 5-sep-2026 en la tirada de 40 conversaciones: los DOS fallos de "repite
la misma pregunta" eran el mismo. La clienta rechaza el camino -la cita de
diagnostico en mechas, la foto en alisado-, sigue pidiendo el precio, y el
asistente le repetia su respuesta hasta DIEZ veces hasta que ella se rendia.

    ELLA: no quiero la cita de diagnostico, solo el precio
    IA:   [la misma respuesta de siempre]
    ELLA: sigo buscando el precio sin tener que ir
    IA:   [la misma respuesta de siempre]

La salida ya la habia dictado la duenya: "que nos llame por telefono, que
hablaremos mas detenidamente y le preguntamos para poder darle un presupuesto
aunque sea aproximado". Solo salia si la clienta mencionaba que vivia lejos.

Ofrecerle MAS HUECOS a quien ha dicho que no quiere venir es repetirle el muro,
asi que el remate cambia segun lo que rechaza: la hora o el camino.
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401


# ─── 1. Que cuenta como rechazar el camino ─────────────────────────────────

@pytest.mark.parametrize("mensaje", [
    "no quiero la cita de diagnostico, solo el precio",
    "no quiero mandar fotos, solo saber el precio",
    "¿no podrían darme un rango de precios?",
    "solo quiero saber el precio antes de ir",
    "sin tener que ir primero",
    "me gustaría una idea aproximada",
    "no puedo acercarme, vivo lejos",
])
def test_rechaza_el_camino(mensaje):
    from backend import agent

    assert agent._rechaza_el_camino(mensaje), mensaje


@pytest.mark.parametrize("mensaje", [
    "quiero unas mechas",
    "el jueves por la tarde me viene bien",
    "cuanto cuesta un alisado?",
    "vale, cogeme la cita",
])
def test_no_rechaza_el_camino(mensaje):
    """No puede saltar con cualquier mensaje: seria dar el telefono a todo el mundo."""
    from backend import agent

    assert not agent._rechaza_el_camino(mensaje), mensaje


# ─── 2. El texto que se le da ──────────────────────────────────────────────

def test_el_texto_de_precio_no_habla_de_la_agenda(api_module, monkeypatch):  # noqa: F811
    """A quien pregunta el precio, ofrecerle revisar la agenda no le sirve."""
    from backend import clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": "600 100 200"}, "booking": {}})
    linea = clients.call_us_line("demo", "precio")
    assert "600 100 200" in linea
    assert "presupuesto" in linea.lower()
    assert "agenda" not in linea.lower()


def test_el_negocio_puede_poner_su_propio_texto(api_module, monkeypatch):  # noqa: F811
    from backend import clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": "600 100 200"},
        "booking": {"rescate_precio_texto": "Llamanos al {telefono} y te lo contamos."}})
    assert "Llamanos al 600 100 200 y te lo contamos." in clients.call_us_line("demo", "precio")


def test_sin_telefono_publicado_no_se_inventa_nada(api_module, monkeypatch):  # noqa: F811
    from backend import clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": ""}, "booking": {}})
    assert clients.call_us_line("demo", "precio") == ""


def test_el_negocio_puede_apagarlo(api_module, monkeypatch):  # noqa: F811
    from backend import clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": "600 100 200"}, "booking": {"rescate_enabled": False}})
    assert clients.call_us_line("demo", "precio") == ""


# ─── 3. Enganchado en la respuesta ─────────────────────────────────────────

def test_se_anade_el_telefono_a_quien_rechaza_el_camino(api_module, monkeypatch):  # noqa: F811
    from backend import agent, clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": "600 100 200"}, "booking": {}})
    salida = agent._con_el_telefono_si_hace_falta(
        "demo", "no quiero la cita, solo el precio",
        "El precio depende de tu pelo.", False)
    assert "600 100 200" in salida


def test_no_se_anade_si_la_cita_ya_esta_cogida(api_module, monkeypatch):  # noqa: F811
    """Con la cita hecha, mandarla a llamar por telefono es ruido."""
    from backend import agent, clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": "600 100 200"}, "booking": {}})
    salida = agent._con_el_telefono_si_hace_falta(
        "demo", "no quiero la cita, solo el precio", "Cita confirmada.", True)
    assert "600 100 200" not in salida


def test_no_se_repite_el_telefono_si_ya_estaba(api_module, monkeypatch):  # noqa: F811
    from backend import agent, clients

    monkeypatch.setattr(clients, "_get_client_config", lambda cid: {
        "contacto": {"telefono": "600 100 200"}, "booking": {}})
    ya = "Si prefieres no venir solo para eso, llamanos al 600 100 200: te preguntamos."
    assert agent._con_el_telefono_si_hace_falta(
        "demo", "solo quiero el precio", ya, False).count("600 100 200") == 1
