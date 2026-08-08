"""Fase 2A: copy conversacional, bundle y elegibilidad de outreach.

Estas pruebas no permiten red ni SMTP real.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import outreach_campaign as campaign  # noqa: E402
import outreach_templates as templates  # noqa: E402


def _email_for_variant(variant: str) -> str:
    for index in range(1000):
        email = f"persona{index}@independiente.test"
        if templates.assign_variant(email, "cold") == variant:
            return email
    raise AssertionError(f"No se encontro variante {variant}")


def _insert_prospect(
    conn: sqlite3.Connection,
    email: str,
    business: str,
    *,
    contact: str = "",
    website: str = "",
    niche: str = "",
    tags: str = "",
    source: str = "test",
) -> None:
    now = campaign.now_iso()
    conn.execute(
        """INSERT INTO prospects
           (email, business_name, contact_name, niche, website, service_hint,
            city, phone, tags, source, status, created_at, updated_at)
           VALUES (?,?,?,?,?,'','','',?,?, 'new',?,?)""",
        (email, business, contact, niche, website, tags, source, now, now),
    )


def test_copy_is_brief_claim_free_and_variant_stays_across_sequence():
    emails = {variant: _email_for_variant(variant) for variant in ("A", "B")}
    forbidden = (
        "10 primeros", "setup gratis", "60%", "78%", "1 de cada 3",
        "menos de 2 minutos", "demo preparada", "chat hecho", "sin tarjeta",
        "último intento", "lo que se pierden", "negocios como",
    )

    rendered_by_variant: dict[str, dict[str, str]] = {"A": {}, "B": {}}
    for variant, email in emails.items():
        prospect = templates.Prospect(
            email=email,
            business_name="Clínica Norte",
            contact_name="",
            niche="clínica dental",
            city="",
        )
        assert {templates.assign_variant(email, stage) for stage in templates.STAGE_ORDER} == {variant}
        for stage in templates.STAGE_ORDER:
            subject, text, html = templates.render(stage, prospect, "baja@vantelia.es")
            rendered_by_variant[variant][stage] = text
            lowered = f"{subject}\n{text}\n{html}".lower()
            assert not any(claim in lowered for claim in forbidden)
            assert len(text.split()) < 105
            assert text.startswith("Hola,\n")
            assert "Hola equipo" not in text
            assert "Torrejon de Ardoz" not in text
            if stage != "breakup" or variant == "B":
                assert "Clínica Norte" in text

    for stage in templates.STAGE_ORDER:
        assert rendered_by_variant["A"][stage] != rendered_by_variant["B"][stage]
    assert "sí o no" in rendered_by_variant["A"]["cold"]
    assert "1 = sí / 2 = no" in rendered_by_variant["B"]["cold"]


def test_bundle_migrates_legacy_once_and_keeps_logical_rollback(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        """CREATE TABLE templates_overrides (
               stage TEXT PRIMARY KEY, subject_pool TEXT DEFAULT '', body_text TEXT DEFAULT '',
               body_html TEXT DEFAULT '', updated_at TEXT NOT NULL
           )"""
    )
    legacy.execute(
        "INSERT INTO templates_overrides VALUES ('cold','ASUNTO LEGACY','CUERPO LEGACY','<p>LEGACY</p>','old')"
    )
    legacy.commit()
    legacy.close()

    conn = campaign.connect(db_path)
    cold = conn.execute("SELECT * FROM templates_overrides WHERE stage='cold'").fetchone()
    assert cold["bundle_version"] == templates.OUTREACH_COPY_BUNDLE_VERSION
    assert cold["body_text"] != "CUERPO LEGACY"
    history = conn.execute(
        "SELECT * FROM outreach_template_bundle_history WHERE version=?",
        (templates.OUTREACH_COPY_BUNDLE_VERSION,),
    ).fetchone()
    snapshot = json.loads(history["rollback_json"])
    assert snapshot["stages"]["cold"]["body_text"] == "CUERPO LEGACY"
    applied_at = history["applied_at"]

    assert campaign.apply_outreach_copy_bundle(conn) is False
    assert conn.execute("SELECT COUNT(*) n FROM outreach_template_bundle_history").fetchone()["n"] == 1
    assert conn.execute(
        "SELECT applied_at FROM outreach_template_bundle_history"
    ).fetchone()["applied_at"] == applied_at

    assert campaign.rollback_outreach_copy_bundle(conn) is True
    restored = conn.execute("SELECT * FROM templates_overrides WHERE stage='cold'").fetchone()
    assert restored["body_text"] == "CUERPO LEGACY"
    assert conn.execute(
        "SELECT rolled_back_at FROM outreach_template_bundle_history"
    ).fetchone()["rolled_back_at"]
    assert campaign.rollback_outreach_copy_bundle(conn) is False
    conn.close()


def test_override_renderer_uses_actual_stable_variant_and_escapes_html(tmp_path: Path):
    conn = campaign.connect(tmp_path / "variants.db")
    overrides = campaign.load_template_overrides(conn)
    variants_seen = set()
    for expected in ("A", "B"):
        email = _email_for_variant(expected)
        prospect = templates.Prospect(
            email=email,
            business_name='<img src=x onerror="alert(1)">',
        )
        for stage in templates.STAGE_ORDER:
            subject, text, html, actual = campaign.render_with_override_and_variant(
                stage, prospect, "baja@vantelia.es", overrides
            )
            assert actual == expected == templates.assign_variant(email, stage)
            assert subject and text and html
            assert '<img src=x onerror="alert(1)">' not in html
            if stage != "breakup" or expected == "B":
                assert "&lt;img" in html
        variants_seen.add(actual)
    assert variants_seen == {"A", "B"}
    conn.close()


def test_invalid_override_is_fail_closed():
    with pytest.raises(ValueError, match="placeholder no permitido"):
        campaign.validate_template_override(body_text="Hola {inventado}")
    with pytest.raises(ValueError, match="desbalanceadas"):
        campaign.validate_template_override(body_html="<p>{business</p>")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE templates_overrides (stage TEXT, subject_pool TEXT, body_text TEXT, body_html TEXT)"
    )
    with pytest.raises(RuntimeError, match="Schema"):
        campaign.load_template_overrides(conn)
    conn.close()


def test_segmentation_allows_sme_mailboxes_prioritizes_personal_and_guards_only_email(tmp_path: Path):
    conn = campaign.connect(tmp_path / "segments.db")
    allowed = {
        "ana.lopez@estudio.test",
        "info@pyme.test",
        "reservas@restaurante.test",
        "contacto@taller.test",
    }
    for email in allowed:
        _insert_prospect(
            conn,
            email,
            email.split("@", 1)[1],
            contact="Ana López" if email.startswith("ana.") else "",
            website=f"https://{email.split('@', 1)[1]}",
        )
    blocked = {
        "legal@pyme.test": "Empresa privada",
        "privacidad@pyme.test": "Empresa privada",
        "dpd@pyme.test": "Empresa privada",
        "noreply@pyme.test": "Empresa privada",
        "administracion@pyme.test": "Empresa privada",
        "info@municipio.test": "Ayuntamiento de Villa",
        "info@cadena.test": "Clínicas Vitaldent Centro",
    }
    for email, business in blocked.items():
        _insert_prospect(conn, email, business)
    conn.commit()

    candidates = campaign.fetch_candidates(conn, "cold", after_days=0, limit=50)
    candidate_emails = [p.email for p in candidates]
    assert set(candidate_emails) == allowed
    assert candidate_emails[0] == "ana.lopez@estudio.test"
    for email in blocked:
        assert campaign.fetch_candidates(
            conn, "cold", after_days=0, limit=1, only_email=email
        ) == []
    assert campaign.fetch_candidates(
        conn, "cold", after_days=0, limit=1, only_email="info@pyme.test"
    )

    # Un test no altera la elegibilidad; un envio real sí.
    conn.execute(
        "INSERT INTO sends (email,stage,subject,sent_at,mode) VALUES (?,?,?,?,?)",
        ("info@pyme.test", "cold", "test", campaign.now_iso(), "test"),
    )
    conn.commit()
    assert campaign.fetch_candidates(
        conn, "cold", after_days=0, limit=1, only_email="info@pyme.test"
    )
    conn.execute(
        "INSERT INTO sends (email,stage,subject,sent_at,mode) VALUES (?,?,?,?,?)",
        ("info@pyme.test", "cold", "real", campaign.now_iso(), "send"),
    )
    conn.commit()
    assert campaign.fetch_candidates(
        conn, "cold", after_days=0, limit=1, only_email="info@pyme.test"
    ) == []

    followup_email = "persona@seguimiento.test"
    _insert_prospect(conn, followup_email, "Estudio Independiente")
    conn.commit()
    assert campaign.fetch_candidates(
        conn, "fu1", after_days=4, limit=1, only_email=followup_email
    ) == []
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO sends (email,stage,subject,sent_at,mode) VALUES (?,?,?,?,?)",
        (followup_email, "cold", "real", old, "send"),
    )
    conn.commit()
    assert campaign.fetch_candidates(
        conn, "fu1", after_days=4, limit=1, only_email=followup_email
    )
    conn.execute(
        "INSERT INTO suppressions (email,reason,added_at) VALUES (?,?,?)",
        (followup_email, "test", campaign.now_iso()),
    )
    conn.commit()
    assert campaign.fetch_candidates(
        conn, "fu1", after_days=4, limit=1, only_email=followup_email
    ) == []
    conn.close()


def test_test_to_uses_fake_smtp_and_does_not_create_send_history(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "test-mode.db"
    conn = campaign.connect(db_path)
    _insert_prospect(conn, "persona@negocio.test", "Negocio Local")
    conn.commit()
    conn.close()

    delivered = []
    monkeypatch.setattr(campaign, "in_business_window", lambda: (True, "ok"))
    monkeypatch.setattr(campaign, "smtp_send", lambda msg, settings: delivered.append(msg["To"]))
    monkeypatch.setattr(
        campaign,
        "smtp_settings",
        lambda: {
            "host": "smtp.invalid",
            "port": 587,
            "username": "",
            "password": "",
            "from_email": "pablo@vantelia.test",
            "from_name": "Pablo",
            "reply_to": "pablo@vantelia.test",
            "starttls": False,
            "unsubscribe_mailto": "baja@vantelia.test",
            "bcc": "",
            "domain_for_id": "vantelia.test",
        },
    )
    args = Namespace(
        send=False,
        test_to="owner@example.test",
        force_window=True,
        db=db_path,
        max=1,
        email=None,
        after_days=0,
        delay=0.0,
        jitter=0.0,
        stop_on_error=True,
    )
    assert campaign._send_loop(args, "cold") == 0
    assert delivered == ["owner@example.test"]
    conn = campaign.connect(db_path)
    assert conn.execute("SELECT COUNT(*) n FROM sends").fetchone()["n"] == 0
    conn.close()
