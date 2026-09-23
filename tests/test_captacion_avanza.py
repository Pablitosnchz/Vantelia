# -*- coding: utf-8 -*-
"""La busqueda avanza por la ciudad en vez de mirar siempre lo mismo.

POR QUE EXISTE
--------------
El 22-sep la captacion se quedo otra vez sin a quien escribir: los 26 objetivos
(sector x ciudad) estaban agotados con Madrid practicamente sin tocar. La causa:
Overpass devuelve SIEMPRE los mismos primeros resultados de la ciudad, la ronda
siguiente los descartaba por repetidos, no importaba a nadie y a las dos rondas
el objetivo se marcaba agotado.

Ahora la busqueda recuerda que negocios ya miro en cada sector y ciudad, los
salta, y un objetivo solo se agota cuando de verdad no quedan negocios nuevos.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import outreach_discover as descubrir  # noqa: E402

from test_captacion_autonoma import api, outreach_mod  # noqa: F401,E402


def _mapa_falso(monkeypatch, negocios):
    """Overpass sin red: devuelve estos negocios, siempre en el mismo orden."""
    elementos = [{"type": "node", "id": i, "tags": {"name": n, "website": "https://%s.test" % n.lower()}}
                 for i, n in enumerate(negocios, start=1)]
    consultas = []

    class Respuesta:
        status_code = 200

        @staticmethod
        def json():
            return {"elements": elementos}

    class Cliente:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None):
            consultas.append((data or {}).get("data", ""))
            return Respuesta()

    monkeypatch.setattr(descubrir, "httpx", SimpleNamespace(Client=Cliente))
    monkeypatch.setattr(descubrir, "nominatim_lookup_bbox", lambda ciudad: (40.3, -3.8, 40.5, -3.6))
    return consultas


def test_la_busqueda_salta_los_negocios_que_ya_miro(monkeypatch):
    _mapa_falso(monkeypatch, ["Peluqueria Uno", "Peluqueria Dos", "Peluqueria Tres"])
    primera = descubrir.overpass_search("peluqueria", "madrid", max_results=2)
    assert [n["name"] for n in primera] == ["Peluqueria Uno", "Peluqueria Dos"]
    assert all(n["osm_key"] for n in primera), "sin clave no se puede recordar cual se miro"

    segunda = descubrir.overpass_search("peluqueria", "madrid", max_results=2,
                                        saltar={n["osm_key"] for n in primera})
    assert [n["name"] for n in segunda] == ["Peluqueria Tres"], (
        "la ronda siguiente vuelve a los mismos: la ciudad no avanza")


def test_la_ventana_del_mapa_crece_con_lo_ya_visto(monkeypatch):
    consultas = _mapa_falso(monkeypatch, ["Uno"])
    descubrir.overpass_search("peluqueria", "madrid", max_results=10)
    descubrir.overpass_search("peluqueria", "madrid", max_results=10,
                              saltar={"node/%d" % i for i in range(300)})
    pedidos = [int(c.rsplit(" ", 1)[1].rstrip(";")) for c in consultas]
    assert pedidos[1] > pedidos[0], (
        "con 300 vistos se pide la misma ventana: no se llega a los nuevos (%r)" % pedidos)


def test_la_web_que_no_se_llego_a_mirar_no_cuenta_como_vista(monkeypatch):
    """23-sep: en Madrid la ronda encontraba 22 peluquerias, miraba la web de
    unas pocas (tope por ronda) y el resto salia "sin email" y quedaba anotado
    como visto. Esas webs no se abrian nunca: cantera perdida en silencio."""
    negocios = [{"osm_key": "node/%d" % i, "name": "Peluqueria %d" % i,
                 "website": "https://p%d.test" % i} for i in range(1, 6)]
    monkeypatch.setattr(descubrir, "overpass_search", lambda *a, **k: list(negocios))
    abiertas = []
    monkeypatch.setattr(descubrir, "extract_emails_from_website",
                        lambda url: abiertas.append(url) or [])
    devueltos = descubrir._companies_from_osm("peluqueria", "madrid", max_results=5,
                                              extract_emails=True, max_email_scrapes=2)
    assert len(abiertas) == 2
    assert [c.osm_key for c in devueltos] == ["node/1", "node/2"], (
        "se devuelven (y se anotan como vistos) negocios cuya web no se abrio")


def test_lo_mirado_se_recuerda_entre_rondas(outreach_mod):  # noqa: F811
    outreach = outreach_mod
    with outreach._outreach_db() as conn:
        assert outreach._outreach_vistos_de(conn, "peluqueria|madrid") == set()
        assert outreach._outreach_anotar_vistos(conn, "peluqueria|madrid", ["node/1", "node/2", ""]) == 2
        assert outreach._outreach_anotar_vistos(conn, "peluqueria|madrid", ["node/2", "node/3"]) == 1
        assert outreach._outreach_vistos_de(conn, "peluqueria|madrid") == {"node/1", "node/2", "node/3"}
        # Cada sector y ciudad lleva su cuenta.
        assert outreach._outreach_vistos_de(conn, "peluqueria|getafe") == set()


def test_avanzar_por_la_ciudad_no_agota_el_objetivo(outreach_mod):  # noqa: F811
    """Una ronda sin importables pero con negocios nuevos mirados NO agota: es
    justo lo que dejo Madrid fuera de la rotacion con la ciudad sin tocar."""
    outreach = outreach_mod
    with outreach._outreach_db() as conn:
        for _ in range(4):
            assert outreach._outreach_register_target_result(
                conn, "peluqueria|madrid", 0, avanzo=True) is False
        fila = conn.execute("SELECT exhausted_targets_json FROM autopilot_config WHERE id=1").fetchone()
        assert "peluqueria|madrid" not in json.loads(fila[0] or "{}")
        # Sin avanzar y sin importar, a la segunda sigue agotandose.
        assert outreach._outreach_register_target_result(conn, "peluqueria|madrid", 0) is False
        assert outreach._outreach_register_target_result(conn, "peluqueria|madrid", 0) is True


def test_una_ronda_del_piloto_deja_memoria_y_la_siguiente_la_usa(outreach_mod, monkeypatch):  # noqa: F811
    """El caso entero: dos rondas del piloto sobre la misma ciudad. La segunda
    tiene que pedir la busqueda SALTANDO lo que miro la primera."""
    outreach = outreach_mod
    from backend import emailing

    monkeypatch.setenv("OUTREACH_AUTONOMOUS_ENABLED", "true")
    monkeypatch.setenv("OUTREACH_RESPECT_WINDOW", "false")
    monkeypatch.setattr(emailing, "_email_delivery_configured", lambda cliente_id="": True)
    monkeypatch.setattr(emailing, "_smtp_health_check",
                        lambda force=False: {"ok": True, "error": "", "checked_at": ""})
    monkeypatch.setattr(outreach, "_outreach_run_send_job", lambda *a: None)
    monkeypatch.setattr(outreach, "_outreach_run_autopilot_job", lambda *a: None)

    saltados = []

    def _buscar(**kwargs):
        saltados.append(set(kwargs.get("saltar") or ()))
        indice = len(saltados)
        return [descubrir.DiscoveredCompany(
            business_name="Peluqueria %d" % indice, email="", website="https://p%d.test" % indice,
            niche=kwargs.get("sector", ""), city=kwargs.get("ciudad", ""),
            osm_key="node/%d" % indice, source="discovery:osm")]

    monkeypatch.setattr(descubrir, "discover_companies", _buscar)
    with outreach._outreach_db() as conn:
        # Ciudad propia y sin memoria previa: otras pruebas comparten esta base.
        outreach._outreach_asegurar_vistos(conn)
        conn.execute("DELETE FROM osm_vistos WHERE combo='peluqueria|leganes'")
        conn.execute("UPDATE autopilot_config SET targets_json=?, exhausted_targets_json='{}', "
                     "last_discovery_at='' WHERE id=1",
                     (json.dumps([{"sector": "peluqueria", "city": "leganes"}]),))
        conn.commit()

    for _ in range(2):
        with outreach._outreach_db() as conn:
            conn.execute("UPDATE autopilot_config SET last_discovery_at='' WHERE id=1")
            conn.commit()
        outreach._outreach_autonomous_tick_inner()

    assert len(saltados) == 2, saltados
    assert saltados[0] == set(), "la primera ronda no tiene nada que saltar"
    assert "node/1" in saltados[1], (
        "la segunda ronda vuelve a mirar lo mismo: no se recordo nada (%r)" % saltados[1])
