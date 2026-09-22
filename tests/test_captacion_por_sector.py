# -*- coding: utf-8 -*-
"""Cada negocio recibe el correo de su sector.

POR QUE EXISTE
--------------
El 22-sep salieron siete correos en frio a centros de masajes que empezaban por
«En las peluquerias pasa mucho...». La plantilla estaba escrita para peluquerias
y la cantera ya no era solo de peluquerias. Pablo pidio que cada negocio
recibiera un mensaje dirigido a el.

No se hace con una plantilla por sector, que no escala, sino con unas frases por
sector (`outreach_templates.SECTOR_COPY`) que la misma plantilla del panel usa:
la escena que les pasa, a quien atienden y que les preguntan. Lo que no se
reconoce cae en una version general.

Y una regla de honestidad: solo se menciona que se trabaja con una peluqueria
donde viene al caso. A una fisio no se le cuenta eso.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import outreach_campaign as campaign  # noqa: E402
import outreach_templates as templates  # noqa: E402


@pytest.mark.parametrize("nicho, sector", [
    ("peluqueria", "las peluquerías"),
    ("Peluquería", "las peluquerías"),
    ("barberia", "las barberías"),
    ("centro de masajes", "los centros de masajes"),
    ("spa", "los centros de masajes"),
    ("clinica estetica", "los centros de estética"),   # estetica gana a clinica
    ("fisioterapia", "las clínicas de fisioterapia"),
    ("osteopatía", "las clínicas de fisioterapia"),
    ("clinica dental", "las clínicas dentales"),
    ("dentista", "las clínicas dentales"),
    ("clinica veterinaria", "las clínicas veterinarias"),
    ("clinica privada", "las clínicas"),
    ("podología", "las clínicas"),
    ("autoescuela", "los negocios que trabajan con cita"),
    ("", "los negocios que trabajan con cita"),
    ("espacio creativo", "los negocios que trabajan con cita"),  # «spa» dentro de «espacio»
])
def test_se_reconoce_el_sector_del_negocio(nicho, sector):
    assert templates.sector_copy(nicho)["sector"] == sector


def test_todos_los_sectores_traen_todas_las_frases():
    campos = set(templates.SECTOR_COPY_GENERAL)
    for _claves, frases in templates.SECTOR_COPY:
        assert set(frases) == campos, frases["sector"]


def test_solo_se_menciona_la_peluqueria_donde_viene_al_caso():
    """El piloto es una peluqueria. Contarselo a una fisio seria faltar a la verdad."""
    for nicho in ("fisioterapia", "clinica dental", "centro de masajes", "clinica estetica",
                  "clinica veterinaria", "autoescuela"):
        assert "peluquer" not in templates.sector_copy(nicho)["estoy_montando"], nicho
    assert "peluquería" in templates.sector_copy("peluqueria")["estoy_montando"]


def _correo(conn, nicho, variante, etapa="cold"):
    for indice in range(200):
        email = f"negocio{indice}@sector.test"
        if templates.assign_variant(email) == variante:
            break
    prospect = templates.Prospect(email=email, business_name="Negocio Ejemplo", niche=nicho, city="Madrid")
    asunto, texto, html, _ = campaign.render_with_override_and_variant(
        etapa, prospect, "baja@vantelia.es", campaign.load_template_overrides(conn))
    return asunto, texto, html


@pytest.mark.parametrize("variante", ["A", "B"])
def test_una_fisio_recibe_un_correo_de_fisio_por_el_camino_del_panel(tmp_path, variante):
    conn = campaign.connect(tmp_path / "fisio.db")
    _asunto, texto, html = _correo(conn, "fisioterapia", variante)
    assert "{" not in texto and "{" not in html.replace("{{", ""), texto
    assert "peluquer" not in texto.lower()
    assert "paciente" in texto or "pacientes" in texto, texto


def test_un_centro_de_masajes_no_recibe_el_texto_de_peluquerias(tmp_path):
    conn = campaign.connect(tmp_path / "masajes.db")
    for variante in ("A", "B"):
        _asunto, texto, _html = _correo(conn, "centro de masajes", variante)
        assert "peluquer" not in texto.lower(), texto


def test_el_seguimiento_habla_de_su_cliente(tmp_path):
    conn = campaign.connect(tmp_path / "seguimiento.db")
    _a, texto_fisio, _h = _correo(conn, "fisioterapia", "A", etapa="fu1")
    _a, texto_pelu, _h = _correo(conn, "peluqueria", "A", etapa="fu1")
    assert "un paciente" in texto_fisio
    assert "una clienta" in texto_pelu


def test_las_plantillas_del_panel_aceptan_las_frases_del_sector():
    for campo in templates.SECTOR_COPY_CAMPOS:
        campaign.validate_template_override(body_text="{%s}" % campo)


def test_el_lote_nuevo_entra_solo_encima_del_de_peluquerias(tmp_path):
    """La situacion de produccion: ya estan aplicados el lote de agosto y el de
    peluquerias del 21-sep. Al arrancar con este codigo, el lote nuevo tiene que
    entrar solo, y quedarse la foto de lo anterior para poder volver atras."""
    ruta = tmp_path / "produccion.db"
    conn = campaign.connect(ruta)
    conn.execute("UPDATE templates_overrides SET body_text=?, bundle_version=? WHERE stage='cold'",
                 ("{greeting}\n\nEn las peluquerías pasa mucho...", "2026-09-peluquerias-humano-v1"))
    conn.execute("DELETE FROM outreach_template_bundle_history WHERE version=?",
                 (templates.OUTREACH_COPY_BUNDLE_VERSION,))
    for version in ("2026-08-human-replies-v1", "2026-09-peluquerias-humano-v1"):
        conn.execute("INSERT OR IGNORE INTO outreach_template_bundle_history "
                     "(version, description, applied_at, rollback_json, rolled_back_at) "
                     "VALUES (?, 'previo', '2026-09-21T00:00:00Z', '{}', '')", (version,))
    conn.commit()
    conn.close()
    campaign._SCHEMA_INITIALIZED.discard(str(ruta.resolve()))

    conn = campaign.connect(ruta)
    fila = conn.execute("SELECT body_text, bundle_version FROM templates_overrides WHERE stage='cold'").fetchone()
    assert fila["bundle_version"] == templates.OUTREACH_COPY_BUNDLE_VERSION
    assert "{sector}" in fila["body_text"], "el lote por sector no ha entrado al arrancar"
    historia = conn.execute("SELECT rollback_json FROM outreach_template_bundle_history WHERE version=?",
                            (templates.OUTREACH_COPY_BUNDLE_VERSION,)).fetchone()
    anterior = json.loads(historia["rollback_json"])["stages"]["cold"]
    assert "peluquerías" in anterior["body_text"], "no queda la foto para volver atras"
