# -*- coding: utf-8 -*-
"""La captacion no puede quedarse parada sin que nadie se entere.

POR QUE EXISTE
--------------
Del 12-ago al 21-sep de 2026 el piloto de captacion estuvo ENCENDIDO, sin pausa
y con el SMTP dedicado bien, y no escribio a nadie. Dos cosas a la vez:

- la cantera se vacio: los 385 negocios encontrados ya habian recibido toda la
  secuencia, y 9 de los 10 objetivos (sector x ciudad) estaban agotados;
- el unico que quedaba, «centro de masajes · Madrid», FALLABA cada hora porque
  el buscador gratuito no conocia ese sector. Como fallaba en vez de volver
  vacio, el bucle hacia `continue` sin anotarlo, nunca se agotaba y la rotacion
  se quedaba intentandolo para siempre.

Y el panel avisaba de un SMTP caido o de una pausa, pero no de esto.
"""
from __future__ import annotations

import json

from test_captacion_autonoma import api, outreach_mod  # noqa: F401


def _datos_objetivos(outreach):
    with outreach._outreach_db() as conn:
        fila = conn.execute("SELECT exhausted_targets_json FROM autopilot_config WHERE id=1").fetchone()
    return json.loads(fila["exhausted_targets_json"] or "{}")


def _config_del_panel(outreach):
    with outreach._outreach_db() as conn:
        return outreach._autopilot_config_row(conn)


def _poner_objetivos(outreach, objetivos, agotados=None):
    with outreach._outreach_db() as conn:
        conn.execute("UPDATE autopilot_config SET targets_json=?, exhausted_targets_json=?, "
                     "last_discovery_at='' WHERE id=1",
                     (json.dumps(objetivos), json.dumps(agotados or {})))
        conn.commit()


def test_un_objetivo_que_falla_cuenta_como_intento_y_guarda_el_motivo(outreach_mod):  # noqa: F811
    outreach = outreach_mod
    with outreach._outreach_db() as conn:
        assert outreach._outreach_register_target_result(
            conn, "centro de masajes|madrid", 0, error="Sector no mapeado") is False
        assert outreach._outreach_register_target_result(
            conn, "centro de masajes|madrid", 0, error="Sector no mapeado") is True
    entrada = _datos_objetivos(outreach)["centro de masajes|madrid"]
    assert entrada["exhausted_at"], "un objetivo que falla dos veces se tiene que excluir"
    assert "no mapeado" in entrada["error"]


def test_una_ronda_real_con_el_buscador_fallando_no_se_queda_atascada(
        outreach_mod, monkeypatch):  # noqa: F811
    """El caso de verdad: el piloto hace su ronda, el buscador lanza, y a la
    segunda el objetivo queda fuera en vez de reintentarse cada hora."""
    import outreach_discover
    from backend import emailing

    outreach = outreach_mod
    monkeypatch.setenv("OUTREACH_AUTONOMOUS_ENABLED", "true")
    monkeypatch.setenv("OUTREACH_RESPECT_WINDOW", "false")
    monkeypatch.setattr(emailing, "_email_delivery_configured", lambda cliente_id="": True)
    monkeypatch.setattr(emailing, "_smtp_health_check",
                        lambda force=False: {"ok": True, "error": "", "checked_at": ""})
    monkeypatch.setattr(outreach, "_outreach_run_send_job", lambda *a: None)
    monkeypatch.setattr(outreach, "_outreach_run_autopilot_job", lambda *a: None)
    intentos = []

    def _falla(**kwargs):
        intentos.append(kwargs.get("sector"))
        raise ValueError("osm: Sector 'inventado' no mapeado a OSM")

    monkeypatch.setattr(outreach_discover, "discover_companies", _falla)
    _poner_objetivos(outreach, [{"sector": "inventado", "city": "madrid"}])

    for _ in range(3):
        with outreach._outreach_db() as conn:
            conn.execute("UPDATE autopilot_config SET last_discovery_at='' WHERE id=1")
            conn.commit()
        outreach._outreach_autonomous_tick_inner()

    assert intentos, "la ronda no ha llegado a buscar: la prueba no ejercita nada"
    assert len(intentos) == 2, (
        "el objetivo que falla se ha reintentado %d veces: sigue atascando la rotacion" % len(intentos))
    assert _datos_objetivos(outreach)["inventado|madrid"]["exhausted_at"]


def test_el_panel_avisa_cuando_no_queda_a_quien_escribir(outreach_mod):  # noqa: F811
    outreach = outreach_mod
    _poner_objetivos(outreach, [{"sector": "clinica dental", "city": "madrid"}],
                     {"clinica dental|madrid": {"misses": 2, "exhausted_at": "2026-08-10T08:08:25+00:00"}})
    avisos = _config_del_panel(outreach)["blockers"]
    assert any("no tiene a quien escribir" in a for a in avisos), avisos


def test_el_panel_avisa_cuando_el_buscador_falla(outreach_mod):  # noqa: F811
    outreach = outreach_mod
    _poner_objetivos(outreach, [{"sector": "centro de masajes", "city": "madrid"}],
                     {"centro de masajes|madrid": {"misses": 1, "error": "Sector no mapeado a OSM"}})
    avisos = _config_del_panel(outreach)["blockers"]
    assert any("El buscador falla" in a and "no mapeado" in a for a in avisos), avisos


def test_con_objetivos_vivos_no_hay_falsa_alarma(outreach_mod):  # noqa: F811
    outreach = outreach_mod
    _poner_objetivos(outreach, [{"sector": "peluqueria", "city": "madrid"}])
    avisos = _config_del_panel(outreach)["blockers"]
    assert not any("no tiene a quien escribir" in a or "El buscador falla" in a for a in avisos), avisos


def test_el_buscador_reconoce_los_centros_de_masajes():
    import outreach_discover

    assert outreach_discover.SECTOR_TO_OSM.get("centro de masajes") == [("shop", "massage")]
    assert outreach_discover.SECTOR_TO_OSM.get("peluqueria") == [("shop", "hairdresser")]
