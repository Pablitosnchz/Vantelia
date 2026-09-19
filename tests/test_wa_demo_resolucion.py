"""La consulta demo no vincula ni modifica SQLite; el wrapper conserva efectos."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from test_booking_exhaustive import api_module  # noqa: F401


@pytest.fixture
def demo_resolution_db(api_module):
    from backend import db

    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM wa_demo_routes")
        connection.execute("DELETE FROM wa_demo_codes")
        connection.executemany(
            """INSERT INTO wa_demo_codes
               (code, cliente_id, active, expires_at, uses, created_at)
               VALUES (?, ?, ?, ?, 0, '2026-09-19T00:00:00Z')""",
            [
                ("SAL234", "demo", 1, "2099-01-01T00:00:00Z"),
                ("HOT456", "van", 1, "2099-01-01T00:00:00Z"),
                ("OLD678", "van", 1, "2020-01-01T00:00:00Z"),
                ("OFF789", "van", 0, "2099-01-01T00:00:00Z"),
            ],
        )
        connection.commit()
    yield
    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM wa_demo_routes")
        connection.execute("DELETE FROM wa_demo_codes")
        connection.commit()


def _snapshot_demo_resolution():
    from backend import db

    # Todas las filas del runtime temporal: detecta escrituras, reset o limpieza,
    # no solo llamadas a un doble de bind_phone.
    with db._get_db_connection() as connection:
        return tuple(connection.iterdump())


def test_consultar_codigo_valido_no_vincula_ni_consume_usos(demo_resolution_db):
    from backend import wa_demo

    before = _snapshot_demo_resolution()
    decision = wa_demo.resolve_incoming_readonly("hub-1", "+34 600 111 222", "demo: SAL234")
    assert _snapshot_demo_resolution() == before
    assert decision.cliente_id == "demo"
    assert decision.code_to_bind == "SAL234"
    assert decision.help_text == ""
    assert wa_demo.route_for_phone("34600111222") == ""
    assert wa_demo.resolve_incoming_readonly("hub-1", "34600111222", "SAL234") == decision
    assert _snapshot_demo_resolution() == before
    with pytest.raises(FrozenInstanceError):
        decision.cliente_id = "van"


@pytest.mark.parametrize("text", ["DEMO BAD999", "DEMO OLD678", "DEMO OFF789", "hola, buenas"])
@pytest.mark.parametrize("already_bound", [False, True])
def test_consulta_sin_codigo_util_conserva_ruta_o_ayuda(demo_resolution_db, text, already_bound):
    from backend import wa_demo

    if already_bound:
        wa_demo.bind_phone("34600111222", "SAL234")
    before = _snapshot_demo_resolution()
    decision = wa_demo.resolve_incoming_readonly("hub-1", "34600111222", text)
    assert _snapshot_demo_resolution() == before
    assert decision.cliente_id == ("demo" if already_bound else "")
    assert decision.code_to_bind == ""
    if already_bound:
        assert decision.help_text == ""
    elif text.startswith("DEMO"):
        assert "no es valido o ha caducado" in decision.help_text
    else:
        assert decision.help_text == wa_demo.HELP_TEXT
    assert wa_demo.resolve_incoming("hub-1", "34600111222", text) == {
        "cliente_id": decision.cliente_id, "just_bound": False, "help_text": decision.help_text,
    }
    assert _snapshot_demo_resolution() == before


def test_cambio_de_negocio_es_consultivo_y_wrapper_vincula_solo_un_telefono(demo_resolution_db):
    from backend import db, wa_demo

    wa_demo.bind_phone("34600111222", "SAL234")
    wa_demo.bind_phone("34600333444", "HOT456")
    before = _snapshot_demo_resolution()
    decision = wa_demo.resolve_incoming_readonly("hub-1", "34600111222", "Hola, DEMO-HOT456")
    assert _snapshot_demo_resolution() == before
    assert (decision.cliente_id, decision.code_to_bind) == ("van", "HOT456")
    assert wa_demo.route_for_phone("34600111222") == "demo"
    assert wa_demo.route_for_phone("34600333444") == "van"

    assert wa_demo.resolve_incoming("hub-1", "34600111222", "Hola, DEMO-HOT456") == {
        "cliente_id": "van", "just_bound": True, "help_text": "",
    }
    assert wa_demo.route_for_phone("34600111222") == "van"
    assert wa_demo.route_for_phone("34600333444") == "van"
    with db._get_db_connection() as connection:
        uses = dict(connection.execute("SELECT code, uses FROM wa_demo_codes"))
    assert uses == {"SAL234": 1, "HOT456": 2, "OLD678": 0, "OFF789": 0}


def test_consulta_no_limpia_ruta_caducada(demo_resolution_db):
    from backend import db, wa_demo

    wa_demo.bind_phone("34600111222", "SAL234")
    with db._get_db_connection() as connection:
        connection.execute("UPDATE wa_demo_routes SET expires_at = '2020-01-01T00:00:00Z'")
        connection.commit()
    before = _snapshot_demo_resolution()
    decision = wa_demo.resolve_incoming_readonly("hub-1", "34600111222", "hola, buenas")
    assert _snapshot_demo_resolution() == before
    assert decision.cliente_id == ""
    assert decision.help_text == wa_demo.HELP_TEXT


def test_wrapper_revalida_codigo_revocado_despues_de_consulta(demo_resolution_db, monkeypatch):
    from backend import db, wa_demo

    wa_demo.bind_phone("34600111222", "SAL234")
    original_query = wa_demo.resolve_incoming_readonly

    def revoke_after_query(*args):
        decision = original_query(*args)
        wa_demo.revoke_code("HOT456")
        return decision

    monkeypatch.setattr(wa_demo, "resolve_incoming_readonly", revoke_after_query)
    assert wa_demo.resolve_incoming("hub-1", "34600111222", "DEMO HOT456") == {
        "cliente_id": "demo", "just_bound": False, "help_text": "",
    }
    assert wa_demo.route_for_phone("34600111222") == "demo"
    with db._get_db_connection() as connection:
        assert connection.execute("SELECT uses FROM wa_demo_codes WHERE code = 'HOT456'").fetchone()[0] == 0


def test_telefono_vacio_no_propone_binding(demo_resolution_db):
    from backend import wa_demo

    before = _snapshot_demo_resolution()
    decision = wa_demo.resolve_incoming_readonly("hub-1", "", "DEMO SAL234")
    assert _snapshot_demo_resolution() == before
    assert decision.cliente_id == decision.code_to_bind == ""
    assert "no es valido o ha caducado" in decision.help_text
