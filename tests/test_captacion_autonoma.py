"""Tests de la captacion autonoma 24/7 (remodelacion ago-2026).

Cubre: pausa automatica con vencimiento vs pausa manual, auto-reanudacion,
warm-up de caps, espaciado global de envio, deteccion de NDR/bounces,
persistencia de consulta_leads con SMTP roto y bounce-rate autopause.
PROHIBIDO enviar emails reales: todo SMTP esta mockeado.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def api(vantelia_env_factory):
    return vantelia_env_factory(env_overrides={
        "OUTREACH_AUTONOMOUS_ENABLED": "true",
        "SMTP_HOST": "smtp.test.invalid",
        "SMTP_FROM_EMAIL": "info@test.invalid",
        "SMTP_USERNAME": "info@test.invalid",
        "SMTP_PASSWORD": "x",
    })


@pytest.fixture()
def outreach_mod(api):
    from backend import outreach

    assert outreach.OUTREACH_AVAILABLE, "modulo outreach debe estar disponible en tests"
    # Limpieza de estado entre tests
    with outreach._outreach_db() as conn:
        outreach._outreach_ensure_autopilot_config_columns(conn)
        conn.execute("INSERT OR IGNORE INTO autopilot_config (id) VALUES (1)")
        conn.execute(
            "UPDATE autopilot_config SET enabled=1, paused_until='', paused_reason='', "
            "ratelimit_days_json='[]', exhausted_targets_json='{}' WHERE id=1"
        )
        conn.execute("DELETE FROM sends")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM prospects")
        conn.execute("DELETE FROM suppressions")
        conn.execute("DELETE FROM jobs")
        try:
            conn.execute("DELETE FROM notify_queue")
        except sqlite3.OperationalError:
            pass
        conn.commit()
    outreach._outreach_last_send_monotonic[0] = 0.0
    return outreach


# ---------------------------------------------------------------- pausas

def test_smtp_ratelimit_pausa_con_vencimiento_no_permanente(outreach_mod, monkeypatch):
    outreach = outreach_mod
    monkeypatch.setattr(outreach, "_outreach_notify_admin", lambda *a, **k: True)
    with outreach._outreach_db() as conn:
        outreach._outreach_pause_autocapture_for_smtp_limit(conn, reason="451 ratelimit test")
        row = conn.execute("SELECT enabled, paused_until, paused_reason FROM autopilot_config WHERE id=1").fetchone()
        # enabled sigue a 1: la pausa automatica NO es la pausa manual
        assert row["enabled"] == 1
        assert row["paused_until"]
        until = outreach._outreach_parse_dt(row["paused_until"])
        assert until > datetime.now(timezone.utc)
        # 9:00 del siguiente dia laborable, no meses
        assert until < datetime.now(timezone.utc) + timedelta(days=4)
        state = outreach._outreach_pause_state(conn)
        assert state["auto"] is True and state["manual"] is False
        assert outreach._outreach_autocapture_is_paused(conn) is True


def test_pausa_vencida_se_considera_reanudada(outreach_mod):
    outreach = outreach_mod
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        conn.execute(
            "UPDATE autopilot_config SET paused_until=?, paused_reason='Rate limit SMTP' WHERE id=1",
            (past,),
        )
        conn.commit()
        state = outreach._outreach_pause_state(conn)
        assert state["expired"] is True and state["auto"] is False
        # Los jobs ya no se consideran pausados aunque el tick aun no limpiara el campo
        assert outreach._outreach_autocapture_is_paused(conn) is False
        outreach._outreach_clear_auto_pause(conn)
        row = conn.execute("SELECT paused_until FROM autopilot_config WHERE id=1").fetchone()
        assert row["paused_until"] == ""


def test_pausa_manual_es_indefinida_y_distinta(outreach_mod):
    outreach = outreach_mod
    with outreach._outreach_db() as conn:
        conn.execute("UPDATE autopilot_config SET enabled=0 WHERE id=1")
        conn.commit()
        state = outreach._outreach_pause_state(conn)
        assert state["manual"] is True and state["auto"] is False
        assert outreach._outreach_autocapture_is_paused(conn) is True
        conn.execute("UPDATE autopilot_config SET enabled=1 WHERE id=1")
        conn.commit()


def test_tres_dias_de_ratelimit_pausa_72h_y_avisa(outreach_mod, monkeypatch):
    outreach = outreach_mod
    avisos = []
    monkeypatch.setattr(outreach, "_outreach_notify_admin", lambda s, t, h="": avisos.append(s) or True)
    today = datetime.now(timezone.utc).date()
    prev_days = [(today - timedelta(days=2)).isoformat(), (today - timedelta(days=1)).isoformat()]
    with outreach._outreach_db() as conn:
        conn.execute("UPDATE autopilot_config SET ratelimit_days_json=? WHERE id=1", (json.dumps(prev_days),))
        conn.commit()
        outreach._outreach_pause_autocapture_for_smtp_limit(conn, reason="451 ratelimit test")
        row = conn.execute("SELECT paused_until FROM autopilot_config WHERE id=1").fetchone()
        until = outreach._outreach_parse_dt(row["paused_until"])
    assert until > datetime.now(timezone.utc) + timedelta(hours=48)
    assert avisos, "el aviso de pausa 72h debe enviarse"


def test_aviso_con_smtp_caido_queda_encolado(outreach_mod, monkeypatch):
    outreach = outreach_mod
    from backend import emailing

    def _boom(*a, **k):
        raise RuntimeError("554 Disabled by user from hPanel")

    monkeypatch.setattr(emailing, "_send_email_message", _boom)
    sent = outreach._outreach_notify_admin("Asunto test", "cuerpo")
    assert sent is False
    with outreach._outreach_db() as conn:
        row = conn.execute("SELECT * FROM notify_queue WHERE sent_at=''").fetchone()
        assert row is not None and row["subject"] == "Asunto test"

    # Cuando el SMTP vuelve, la cola se vacia
    enviados = []
    monkeypatch.setattr(emailing, "_send_email_message", lambda *a, **k: enviados.append(a[1]))
    with outreach._outreach_db() as conn:
        flushed = outreach._outreach_flush_notify_queue(conn)
    assert flushed == 1 and enviados == ["Asunto test"]


# ---------------------------------------------------------------- warm-up

def _insert_send(conn, email, days_ago, stage="cold"):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO sends (email, stage, subject, sent_at, mode) VALUES (?,?,?,?, 'send')",
        (email, stage, "s", ts),
    )


def test_warmup_arranca_en_10_tras_parada_larga(outreach_mod):
    outreach = outreach_mod
    with outreach._outreach_db() as conn:
        assert outreach._outreach_warmup_effective_cap(conn, 30) == 10  # sin historial
        _insert_send(conn, "a@x.es", days_ago=20)
        conn.commit()
        # Ultimo envio hace 20 dias (>7): warm-up reiniciado
        assert outreach._outreach_warmup_effective_cap(conn, 30) == 10


def test_warmup_sube_5_por_semana_hasta_el_cap(outreach_mod):
    outreach = outreach_mod
    with outreach._outreach_db() as conn:
        # Racha continua: envios cada 2 dias desde hace 16 dias
        for i, days in enumerate(range(0, 17, 2)):
            _insert_send(conn, f"p{i}@x.es", days_ago=days)
        conn.commit()
        # 16 dias de racha = 2 semanas → 10 + 5*2 = 20
        assert outreach._outreach_warmup_effective_cap(conn, 30) == 20
        # El cap configurado y el tope 30 mandan
        assert outreach._outreach_warmup_effective_cap(conn, 12) == 12


# ---------------------------------------------------------------- espaciado

def test_espaciado_global_entre_envios(outreach_mod, monkeypatch):
    outreach = outreach_mod
    monkeypatch.setenv("OUTREACH_SEND_SPACING_MIN_SEC", "100")
    monkeypatch.setenv("OUTREACH_SEND_SPACING_MAX_SEC", "100")
    waits = []
    outreach._outreach_last_send_monotonic[0] = 0.0
    outreach._outreach_wait_send_slot(sleep_fn=waits.append)
    outreach._outreach_wait_send_slot(sleep_fn=waits.append)
    outreach._outreach_wait_send_slot(sleep_fn=waits.append)
    # Primer envio inmediato (o casi), los siguientes esperan ~100s cada uno
    assert len(waits) >= 2
    assert all(90 <= w <= 210 for w in waits[-2:])


# ---------------------------------------------------------------- bounces

def _make_ndr_simple():
    msg = EmailMessage()
    msg["From"] = "Mail Delivery System <MAILER-DAEMON@mx.test>"
    msg["Subject"] = "Undelivered Mail Returned to Sender"
    msg["X-Failed-Recipients"] = "roto@empresa.es"
    msg.set_content("bounce")
    return msg


def _make_ndr_delivery_status():
    outer = MIMEMultipart("report")
    outer["From"] = "postmaster@mx.test"
    outer["Subject"] = "Delivery Status Notification (Failure)"
    status = MIMEText(
        "Reporting-MTA: dns; mx.test\n\nFinal-Recipient: rfc822; fallido@negocio.com\nAction: failed\n",
        "plain",
    )
    outer.attach(status)
    return outer


def test_ndr_se_detecta_y_extrae_destinatario(api):
    import outreach_imap

    simple = _make_ndr_simple()
    assert outreach_imap._is_bounce(simple) is True
    assert outreach_imap._bounce_original_recipient(simple) == "roto@empresa.es"

    ds = _make_ndr_delivery_status()
    assert outreach_imap._is_bounce(ds) is True
    assert outreach_imap._bounce_original_recipient(ds) == "fallido@negocio.com"

    normal = EmailMessage()
    normal["From"] = "gerente@clinica.es"
    normal["Subject"] = "Re: tu propuesta"
    normal.set_content("Me interesa, llamame")
    assert outreach_imap._is_bounce(normal) is False


def test_reply_decodifica_asunto_y_extrae_html(api):
    import outreach_imap

    message = EmailMessage()
    message["Subject"] = "=?utf-8?q?Re=3A_informaci=C3=B3n?="
    message.set_content("<p>Me interesa.<br>¿Podemos hablar mañana?</p>", subtype="html")

    assert outreach_imap._message_subject(message) == "Re: información"
    assert outreach_imap._message_text_excerpt(message) == "Me interesa.\n¿Podemos hablar mañana?"


def test_outreach_schema_migra_events_legacy_sin_perder_datos(api, tmp_path):
    import outreach_campaign

    db_path = tmp_path / "outreach-legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE events (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   email TEXT NOT NULL,
                   type TEXT NOT NULL,
                   stage TEXT DEFAULT '',
                   url TEXT DEFAULT '',
                   ts TEXT NOT NULL,
                   ua TEXT DEFAULT '',
                   ip TEXT DEFAULT ''
               )"""
        )
        conn.execute(
            "INSERT INTO events (email, type, stage, url, ts) VALUES (?,?,?,?,?)",
            ("legacy@empresa.es", "reply", "cold", "<legacy@mx>", "2026-08-01T10:00:00+00:00"),
        )
        conn.commit()

    with outreach_campaign.connect(db_path) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
        legacy = conn.execute(
            "SELECT email, type, subject, body_excerpt FROM events WHERE email='legacy@empresa.es'"
        ).fetchone()

    assert {"subject", "body_excerpt"}.issubset(columns)
    assert legacy["type"] == "reply"
    assert legacy["subject"] == ""
    assert legacy["body_excerpt"] == ""


def test_reply_persiste_asunto_y_cuerpo(outreach_mod):
    outreach = outreach_mod
    import outreach_imap

    email = "reply-content@empresa.es"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        conn.execute(
            "INSERT INTO prospects (email, business_name, created_at, updated_at) VALUES (?,?,?,?)",
            (email, "Empresa Reply", now, now),
        )
        created = outreach_imap._record_reply(
            conn,
            email,
            "fu1",
            now,
            "<reply-content-1@mx>",
            subject="Re: propuesta Vantelia",
            body_excerpt="Me interesa. Llámame mañana.",
        )
        conn.commit()
        event = conn.execute(
            "SELECT subject, body_excerpt FROM events WHERE email=? AND type='reply'",
            (email,),
        ).fetchone()
        prospect = conn.execute("SELECT status FROM prospects WHERE email=?", (email,)).fetchone()

    assert created is True
    assert event["subject"] == "Re: propuesta Vantelia"
    assert event["body_excerpt"] == "Me interesa. Llámame mañana."
    assert prospect["status"] == "replied"


def test_imap_rellena_contenido_de_respuestas_recientes_ya_vistas(outreach_mod, monkeypatch):
    outreach = outreach_mod
    import outreach_imap

    email = "reply-backfill@empresa.es"
    message_id = "<reply-backfill-1@mx>"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        outreach_imap._ensure_schema(conn)
        conn.execute("DELETE FROM imap_seen WHERE message_id=?", (message_id,))
        conn.execute(
            "INSERT INTO prospects (email, business_name, created_at, updated_at) VALUES (?,?,?,?)",
            (email, "Empresa Backfill", now, now),
        )
        conn.execute(
            """INSERT INTO events (email, type, stage, url, subject, body_excerpt, ts)
               VALUES (?, 'reply', 'fu1', ?, '', '', ?)""",
            (email, message_id, now),
        )
        conn.execute(
            "INSERT INTO imap_seen (message_id, email, stage, seen_at) VALUES (?,?,?,?)",
            (message_id, email, "fu1", now),
        )
        conn.commit()

    message = EmailMessage()
    message["Message-ID"] = message_id
    message["Subject"] = "Re: propuesta anterior"
    message.set_content("Sí, quiero que me contéis más.")

    class FakeImapClient:
        def logout(self):
            return "BYE", []

    monkeypatch.setenv("IMAP_HOST", "imap.test.invalid")
    monkeypatch.setattr(outreach_imap, "_connect_imap", lambda: FakeImapClient())
    monkeypatch.setattr(outreach_imap, "_search_recent_uids", lambda client, lookback: [b"1"])
    monkeypatch.setattr(outreach_imap, "_fetch_message", lambda client, uid: message)

    stats = outreach_imap.poll_once(Path(os.environ["OUTREACH_DB_PATH"]))

    with outreach._outreach_db() as conn:
        event = conn.execute(
            "SELECT subject, body_excerpt FROM events WHERE email=? AND type='reply'",
            (email,),
        ).fetchone()

    assert stats["replies_backfilled"] == 1
    assert stats["skipped"] == 1
    assert event["subject"] == "Re: propuesta anterior"
    assert event["body_excerpt"] == "Sí, quiero que me contéis más."


def test_bounce_marca_prospect_y_suprime(outreach_mod):
    outreach = outreach_mod
    import outreach_imap

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        conn.execute(
            "INSERT INTO prospects (email, business_name, created_at, updated_at) VALUES (?,?,?,?)",
            ("roto@empresa.es", "Empresa Rota", now, now),
        )
        conn.commit()
        created = outreach_imap._record_bounce(conn, "roto@empresa.es", "<ndr-1@mx>")
        conn.commit()
        assert created is True
        prospect = conn.execute("SELECT status FROM prospects WHERE email='roto@empresa.es'").fetchone()
        assert prospect["status"] == "bounced"
        assert conn.execute("SELECT 1 FROM suppressions WHERE email='roto@empresa.es'").fetchone()
        # Idempotente
        assert outreach_imap._record_bounce(conn, "roto@empresa.es", "<ndr-2@mx>") is False


def test_bounce_rate_alto_pausa_48h(outreach_mod, monkeypatch):
    outreach = outreach_mod
    monkeypatch.setattr(outreach, "_outreach_notify_admin", lambda *a, **k: True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        for i in range(30):
            _insert_send(conn, f"b{i}@x.es", days_ago=0)
        for i in range(5):  # 5/30 = 16.6% > 8%
            conn.execute(
                "INSERT INTO events (email, type, ts) VALUES (?, 'bounce', ?)", (f"b{i}@x.es", now)
            )
        conn.commit()
    assert outreach._outreach_check_bounce_rate() is True
    with outreach._outreach_db() as conn:
        state = outreach._outreach_pause_state(conn)
        assert state["auto"] is True
        assert "Bounce rate" in state["reason"]


# ------------------------------------------------------- consulta_leads

def test_consulta_lead_se_persiste_aunque_smtp_reviente(api, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import emailing

    def _boom(*a, **k):
        raise RuntimeError("554 5.7.1 Disabled by user from hPanel")

    monkeypatch.setattr(emailing, "_send_email_message", _boom)
    monkeypatch.setattr(emailing, "_email_delivery_configured", lambda cliente_id="": True)
    client = TestClient(api.app)
    resp = client.post(
        "/consulta",
        json={"nombre": "Lead Test", "email": "lead@negocio.es", "mensaje": "Quiero info"},
    )
    assert resp.status_code == 200 and resp.json()["ok"] is True

    headers = {"Authorization": "Bearer test-admin-token"}
    data = client.get("/admin/consulta-leads?status=pending", headers=headers).json()
    assert data["pending"] >= 1
    lead = next(it for it in data["items"] if it["email"] == "lead@negocio.es")
    assert lead["notif_sent"] == 0 and lead["confirm_sent"] == 0

    patched = client.patch(
        f"/admin/consulta-leads/{lead['id']}", json={"status": "attended"}, headers=headers
    )
    assert patched.status_code == 200
    data2 = client.get("/admin/consulta-leads?status=pending", headers=headers).json()
    assert all(it["id"] != lead["id"] for it in data2["items"])


def test_email_health_endpoint(api, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import emailing

    monkeypatch.setattr(
        emailing, "_smtp_health_check",
        lambda force=False: {"ok": False, "error": "554 disabled", "checked_at": "2026-08-04T00:00:00+00:00"},
    )
    client = TestClient(api.app)
    resp = client.get("/admin/email-health", headers={"Authorization": "Bearer test-admin-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and "554" in body["smtp"]["error"]


# --------------------------------------------------- E2E dry-run del tick

def test_tick_completo_lanza_cold_con_warmup_y_sin_discovery(outreach_mod, monkeypatch):
    outreach = outreach_mod
    from backend import emailing

    monkeypatch.setenv("OUTREACH_AUTONOMOUS_ENABLED", "true")
    monkeypatch.setenv("OUTREACH_RESPECT_WINDOW", "false")
    monkeypatch.setattr(emailing, "_email_delivery_configured", lambda cliente_id="": True)
    monkeypatch.setattr(
        emailing, "_smtp_health_check",
        lambda force=False: {"ok": True, "error": "", "checked_at": "2026-08-04T00:00:00+00:00"},
    )

    launched = []
    monkeypatch.setattr(outreach, "_outreach_run_send_job", lambda job_id, params: launched.append(("cold", params)))
    monkeypatch.setattr(outreach, "_outreach_run_autopilot_job", lambda job_id, params: launched.append(("fu", params)))

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        conn.execute(
            "UPDATE autopilot_config SET enabled=1, auto_followups=1, discovery_enabled=0, "
            "daily_cold_cap=30, paused_until='', paused_reason='' WHERE id=1"
        )
        # 40 prospects new: mas que el pool minimo (30) para que no difiera el cold
        for i in range(40):
            conn.execute(
                "INSERT INTO prospects (email, business_name, status, created_at, updated_at) VALUES (?,?,?,?,?)",
                (f"nuevo{i}@x.es", f"Negocio {i}", "new", now, now),
            )
        conn.commit()

    outreach._outreach_autonomous_tick_inner()
    time.sleep(0.3)  # los jobs mockeados corren en threads

    cold_jobs = [p for kind, p in launched if kind == "cold"]
    assert cold_jobs, "el tick debe lanzar un job cold"
    # Warm-up sin historial: cap 10 → por ronda max(3, 10//3+) = 4
    assert len(cold_jobs[0]["emails"]) <= 10
    assert any(kind == "fu" for kind, _ in launched), "follow-ups tambien se lanzan"

    with outreach._outreach_db() as conn:
        events = [r["event"] for r in conn.execute(
            "SELECT event FROM autopilot_activity_log ORDER BY id DESC LIMIT 30"
        ).fetchall()]
    assert "cold_budget" in events and "tick_end" in events


def test_tope_diario_total_limita_followups(outreach_mod, monkeypatch):
    """En dominio nuevo el warm-up limita el VOLUMEN total (cold + follow-ups),
    no solo el cold. Con el tope ya alcanzado hoy, el job de follow-ups no sale."""
    outreach = outreach_mod
    from backend import emailing

    monkeypatch.setenv("OUTREACH_AUTONOMOUS_ENABLED", "true")
    monkeypatch.setenv("OUTREACH_RESPECT_WINDOW", "false")
    monkeypatch.setenv("OUTREACH_TOTAL_DAILY_MULTIPLIER", "4")
    monkeypatch.setattr(emailing, "_email_delivery_configured", lambda cliente_id="": True)
    monkeypatch.setattr(
        emailing, "_smtp_health_check",
        lambda force=False: {"ok": True, "error": "", "checked_at": "2026-08-04T00:00:00+00:00"},
    )
    monkeypatch.setattr(outreach, "_outreach_smtp_health",
                        lambda: {"ok": True, "error": "", "checked_at": "x", "dedicated": True})
    launched = []
    monkeypatch.setattr(outreach, "_outreach_run_send_job", lambda j, p: launched.append(("cold", p)))
    monkeypatch.setattr(outreach, "_outreach_run_autopilot_job", lambda j, p: launched.append(("fu", p)))

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        conn.execute(
            "UPDATE autopilot_config SET enabled=1, auto_followups=1, discovery_enabled=0, "
            "daily_cold_cap=10, paused_until='', paused_reason='' WHERE id=1"
        )
        # Warm-up sin historial de racha => cap 10; tope total = 10*4 = 40.
        # Ya enviados hoy 40 (mezcla) => followup_budget_today = 0.
        for i in range(40):
            _insert_send(conn, f"sent{i}@x.es", days_ago=0, stage="fu1")
        conn.commit()

    outreach._outreach_autonomous_tick_inner()
    time.sleep(0.2)

    assert not any(kind == "fu" for kind, _ in launched), "follow-ups no deben salir con tope total alcanzado"
    with outreach._outreach_db() as conn:
        events = [r["event"] for r in conn.execute(
            "SELECT event FROM autopilot_activity_log ORDER BY id DESC LIMIT 20"
        ).fetchall()]
    assert "followups_cap_reached" in events


def test_guard_no_lanza_job_si_hay_uno_activo(outreach_mod, monkeypatch):
    """Con un job de envio ya activo, el tick no lanza otro (evita duplicados)."""
    outreach = outreach_mod
    from backend import emailing

    monkeypatch.setenv("OUTREACH_AUTONOMOUS_ENABLED", "true")
    monkeypatch.setenv("OUTREACH_RESPECT_WINDOW", "false")
    monkeypatch.setattr(emailing, "_email_delivery_configured", lambda cliente_id="": True)
    monkeypatch.setattr(emailing, "_smtp_health_check",
                        lambda force=False: {"ok": True, "error": "", "checked_at": "x"})
    monkeypatch.setattr(outreach, "_outreach_smtp_health",
                        lambda: {"ok": True, "error": "", "checked_at": "x", "dedicated": True})
    launched = []
    monkeypatch.setattr(outreach, "_outreach_run_send_job", lambda j, p: launched.append("cold"))
    monkeypatch.setattr(outreach, "_outreach_run_autopilot_job", lambda j, p: launched.append("fu"))

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        conn.execute("UPDATE autopilot_config SET enabled=1, auto_followups=1, discovery_enabled=0 WHERE id=1")
        # Job de envio ya activo (started hace poco)
        conn.execute(
            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES ('autopilot','running','{}','',?)",
            (now,),
        )
        conn.commit()
        assert outreach._outreach_active_send_job(conn) is not None

    outreach._outreach_autonomous_tick_inner()
    time.sleep(0.2)
    assert not launched, "no debe lanzarse ningun job de envio con otro activo"
    with outreach._outreach_db() as conn:
        events = [r["event"] for r in conn.execute(
            "SELECT event FROM autopilot_activity_log ORDER BY id DESC LIMIT 12"
        ).fetchall()]
    assert "sending_job_active" in events


def test_reset_stale_jobs_limpia_zombies(outreach_mod):
    outreach = outreach_mod
    old = "2026-06-03T09:00:00+00:00"
    with outreach._outreach_db() as conn:
        conn.execute("INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES ('send','running','{}','',?)", (old,))
        conn.execute("INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES ('autopilot','queued','{}','',?)", (old,))
        conn.commit()
    outreach._outreach_reset_stale_jobs()
    with outreach._outreach_db() as conn:
        stuck = conn.execute("SELECT COUNT(*) c FROM jobs WHERE status IN ('running','queued')").fetchone()["c"]
        interrupted = conn.execute("SELECT COUNT(*) c FROM jobs WHERE status='interrupted'").fetchone()["c"]
    assert stuck == 0 and interrupted >= 2


def test_tick_auto_reanuda_pausa_vencida(outreach_mod, monkeypatch):
    outreach = outreach_mod
    from backend import emailing

    monkeypatch.setenv("OUTREACH_AUTONOMOUS_ENABLED", "true")
    monkeypatch.setenv("OUTREACH_RESPECT_WINDOW", "false")
    monkeypatch.setattr(emailing, "_email_delivery_configured", lambda cliente_id="": True)
    monkeypatch.setattr(
        emailing, "_smtp_health_check",
        lambda force=False: {"ok": True, "error": "", "checked_at": "2026-08-04T00:00:00+00:00"},
    )
    monkeypatch.setattr(outreach, "_outreach_run_send_job", lambda *a: None)
    monkeypatch.setattr(outreach, "_outreach_run_autopilot_job", lambda *a: None)

    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        conn.execute(
            "UPDATE autopilot_config SET enabled=1, paused_until=?, paused_reason='Rate limit SMTP' WHERE id=1",
            (past,),
        )
        conn.commit()

    outreach._outreach_autonomous_tick_inner()

    with outreach._outreach_db() as conn:
        row = conn.execute("SELECT paused_until FROM autopilot_config WHERE id=1").fetchone()
        assert row["paused_until"] == ""
        events = [r["event"] for r in conn.execute(
            "SELECT event FROM autopilot_activity_log ORDER BY id DESC LIMIT 30"
        ).fetchall()]
    assert "auto_resumed" in events


def test_tick_respeta_pausa_automatica_activa(outreach_mod, monkeypatch):
    outreach = outreach_mod
    monkeypatch.setenv("OUTREACH_AUTONOMOUS_ENABLED", "true")
    future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat(timespec="seconds")
    launched = []
    monkeypatch.setattr(outreach, "_outreach_run_send_job", lambda *a: launched.append("cold"))
    with outreach._outreach_db() as conn:
        conn.execute(
            "UPDATE autopilot_config SET enabled=1, paused_until=?, paused_reason='Bounce rate 10%' WHERE id=1",
            (future,),
        )
        conn.commit()

    outreach._outreach_autonomous_tick_inner()
    assert not launched

    with outreach._outreach_db() as conn:
        events = [r["event"] for r in conn.execute(
            "SELECT event FROM autopilot_activity_log ORDER BY id DESC LIMIT 10"
        ).fetchall()]
    assert "skip_auto_paused" in events


# ---------------------------------------------------- discovery agotados

def test_brevo_webhook_bounce_suprime(outreach_mod):
    outreach = outreach_mod
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        conn.execute("INSERT INTO prospects (email, business_name, created_at, updated_at) VALUES (?,?,?,?)",
                     ("rebote@x.es", "Rebote SL", now, now))
        conn.commit()
    r = outreach._outreach_process_brevo_event({"event": "hard_bounce", "email": "rebote@x.es", "reason": "550"})
    assert r["action"] == "bounce"
    with outreach._outreach_db() as conn:
        st = conn.execute("SELECT status FROM prospects WHERE email='rebote@x.es'").fetchone()["status"]
        supp = conn.execute("SELECT 1 FROM suppressions WHERE email='rebote@x.es'").fetchone()
    assert st == "bounced" and supp


def test_brevo_webhook_spam_da_de_baja(outreach_mod):
    outreach = outreach_mod
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with outreach._outreach_db() as conn:
        conn.execute("INSERT INTO prospects (email, business_name, created_at, updated_at) VALUES (?,?,?,?)",
                     ("queja@x.es", "Queja SL", now, now))
        conn.commit()
    r = outreach._outreach_process_brevo_event({"event": "spam", "email": "queja@x.es"})
    assert r["action"] == "unsubscribe"
    with outreach._outreach_db() as conn:
        st = conn.execute("SELECT status FROM prospects WHERE email='queja@x.es'").fetchone()["status"]
    assert st == "baja"


def test_brevo_webhook_ignora_eventos_no_relevantes(outreach_mod):
    outreach = outreach_mod
    r = outreach._outreach_process_brevo_event({"event": "opened", "email": "x@y.es"})
    assert r["handled"] is False


def test_cta_apunta_a_demo_go_y_no_se_duplica(monkeypatch):
    monkeypatch.setenv("OUTREACH_TRACKING_SECRET", "sek")
    monkeypatch.setenv("OUTREACH_TRACKING_BASE_URL", "https://app.vantelia.es")
    import importlib, sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts"))
    ot = importlib.import_module("outreach_templates")
    p = ot.Prospect(email="a@b.es", business_name="Bar Pepe", niche="restaurante", website="https://b.es")
    url = ot.demo_go_url("cold", p)
    assert url.startswith("https://app.vantelia.es/demo/go/")
    # apply_tracking NO debe envolver el /demo/go
    html = f'<a href="{url}">demo</a>'
    wrapped = ot.apply_tracking(html, "a@b.es", "cold", "https://app.vantelia.es", "sek")
    assert "/track/click/" not in wrapped.split("</a>")[0]  # el href del CTA queda intacto
    assert "track/open" in wrapped  # pixel de apertura si


def test_demo_go_sin_secret_cae_al_formulario(monkeypatch):
    monkeypatch.delenv("OUTREACH_TRACKING_SECRET", raising=False)
    import importlib
    ot = importlib.import_module("outreach_templates")
    p = ot.Prospect(email="a@b.es", business_name="X", website="https://b.es")
    url = ot.demo_go_url("cold", p)
    assert "/demo/go/" not in url and "vantelia.es/demo" in url


def test_combo_agotado_tras_dos_rondas_sin_importables(outreach_mod):
    outreach = outreach_mod
    with outreach._outreach_db() as conn:
        assert outreach._outreach_register_target_result(conn, "spa|madrid", 0) is False
        assert outreach._outreach_register_target_result(conn, "spa|madrid", 0) is True
        assert "spa|madrid" in outreach._outreach_exhausted_targets(conn)
        # Importar algo lo resetea
        outreach._outreach_register_target_result(conn, "dental|toledo", 0)
        outreach._outreach_register_target_result(conn, "dental|toledo", 3)
        assert "dental|toledo" not in outreach._outreach_exhausted_targets(conn)
        # Reactivacion manual
        outreach._outreach_clear_exhausted_targets(conn)
        assert outreach._outreach_exhausted_targets(conn) == {}
