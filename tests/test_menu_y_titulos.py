# -*- coding: utf-8 -*-
"""El menu es el que configura el negocio, y las filas de WhatsApp se leen.

Dos fallos reales encontrados enseñando el asistente de un salon:

1. El panel promete "las 3 primeras son fijas; Vantelia no anade mas sugerencias
   automaticamente", pero WhatsApp anteponia CUATRO filas de agenda escritas a
   fuego y el chat web colaba "Cancelar o cambiar mi cita". El negocio veia tres
   opciones en su panel y seis en su WhatsApp, distintas ademas de las del chat.

2. Los titulos de fila se cortaban a 24 caracteres a pelo: "Keratina premium
   corto chico" llegaba como "Keratina premium corto c", identico al recorte de
   "corto medio" y confundible con "Keratina premium corto", que existe de
   verdad. 68 de los 188 servicios de ese catalogo pasaban del limite.
"""
from __future__ import annotations

import pytest

from backend import chat, whatsapp


@pytest.fixture
def config_negocio(monkeypatch):
    """Deja fijar las sugerencias del negocio sin tocar config.json."""
    def aplicar(starters, booking=True):
        monkeypatch.setattr(
            chat.clients, "_get_client_config",
            lambda cid: {"starter_questions": list(starters), "booking": {"enabled": booking}},
        )
        monkeypatch.setattr(chat.commerce, "gift_public_available", lambda cid: False)
    return aplicar


def test_el_menu_solo_lleva_lo_que_configura_el_negocio(config_negocio):
    config_negocio([])
    etiquetas = [e["label"] for e in chat.menu_entries("x", True)]
    assert etiquetas == ["Agendar cita", "Información servicios", "Preguntas frecuentes"]


def test_las_sugerencias_propias_se_anaden_al_final(config_negocio):
    config_negocio(["¿Dónde estáis?", "Precios de alisado"])
    etiquetas = [e["label"] for e in chat.menu_entries("x", True)]
    assert etiquetas[-2:] == ["¿Dónde estáis?", "Precios de alisado"]
    # Una sugerencia propia viaja tal cual: es lo que el negocio quiso preguntar.
    propia = next(e for e in chat.menu_entries("x", True) if e["label"] == "¿Dónde estáis?")
    assert propia["message"] == "¿Dónde estáis?"


def test_whatsapp_y_el_chat_web_muestran_el_mismo_menu(config_negocio):
    config_negocio(["Precios de alisado"])
    web = [e["label"] for e in chat._main_menu_quick_actions(True, cliente_id="x")]
    filas = whatsapp._wa_main_menu_sections(True, "x")[0]["rows"]
    assert [f["title"] for f in filas] == web


def test_agendar_cita_sigue_abriendo_el_flujo_guiado(config_negocio):
    """La fila conserva su id de accion; si pasara como texto libre, iria a la IA."""
    config_negocio([])
    filas = whatsapp._wa_main_menu_sections(True, "x")[0]["rows"]
    assert filas[0]["id"] == "menu_agendar"


def test_sin_agenda_no_se_ofrece_agendar(config_negocio):
    config_negocio([], booking=False)
    etiquetas = [e["label"] for e in chat.menu_entries("x", False)]
    assert "Agendar cita" not in etiquetas


def test_el_menu_nunca_pasa_de_diez_filas(config_negocio):
    config_negocio(["Pregunta %d" % i for i in range(12)])
    filas = whatsapp._wa_main_menu_sections(True, "x")[0]["rows"]
    assert len(filas) <= whatsapp._WA_MAX_FILAS


def test_el_titulo_recortado_conserva_lo_que_distingue():
    chico = whatsapp._wa_recortar_titulo("Keratina premium corto chico")
    medio = whatsapp._wa_recortar_titulo("Keratina premium corto medio")
    assert chico != medio
    assert chico.endswith("corto chico") and medio.endswith("corto medio")
    assert len(chico) <= whatsapp._WA_ROW_TITLE_MAX


def test_un_titulo_que_cabe_no_se_toca():
    assert whatsapp._wa_recortar_titulo("Corte de pelo") == "Corte de pelo"
    justo = "x" * whatsapp._WA_ROW_TITLE_MAX
    assert whatsapp._wa_recortar_titulo(justo) == justo


def test_ningun_titulo_pasa_del_limite_de_whatsapp():
    largos = [
        "Pack cambio de color y mechas o balayage extra largo",
        "Diagnostico y presupuesto para extensiones",
        "Supercalifragilisticoespialidosoquenollevaespacios",
        "",
    ]
    for nombre in largos:
        assert len(whatsapp._wa_recortar_titulo(nombre)) <= whatsapp._WA_ROW_TITLE_MAX


def test_el_nombre_completo_viaja_en_la_descripcion():
    """Si el titulo no cabe, el nombre entero abre la descripcion: es lo unico
    que permite distinguir dos servicios que empiezan igual."""
    svc = {"nombre": "Keratina premium corto chico", "duration_minutes": 50,
           "price_label": "50 €", "descripcion": "alisado de keratina"}
    assert whatsapp._wa_service_detail(svc).startswith("Keratina premium corto chico")
    assert len(whatsapp._wa_service_detail(svc)) <= whatsapp._WA_ROW_DESC_MAX


def test_un_servicio_de_nombre_corto_no_repite_el_nombre():
    svc = {"nombre": "Corte de pelo", "duration_minutes": 30, "price_label": "20 €"}
    assert whatsapp._wa_service_detail(svc) == "30 min · 20 €"
