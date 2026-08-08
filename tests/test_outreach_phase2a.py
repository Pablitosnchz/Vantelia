from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def outreach_mod(api_module):
    from backend import outreach

    with outreach._outreach_db() as conn:
        for table in (
            "campaign_members",
            "campaigns",
            "sends",
            "events",
            "prospects",
            "suppressions",
            "jobs",
            "templates_overrides",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
    return outreach


def _add_prospect(conn, email: str, *, status: str = "new") -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO prospects
           (email, business_name, contact_name, niche, website, service_hint,
            city, phone, tags, source, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            email,
            f"Empresa {email}",
            "",
            "clinica",
            f"https://{email.split('@')[0]}.example",
            "",
            "Madrid",
            "",
            "",
            "pytest",
            status,
            now,
            now,
        ),
    )


def _add_send(conn, email: str, stage: str, sent_at: datetime, *, mode: str = "send") -> None:
    conn.execute(
        """INSERT INTO sends
           (email, stage, subject, body_text, body_html, sent_at, mode, message_id)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            email,
            stage,
            "Asunto historico",
            "Texto historico",
            "<p>Historico</p>",
            sent_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
            mode,
            f"<{stage}-{email}>",
        ),
    )


@pytest.mark.parametrize("status", ["replied", "client", "lost", "bounced", "baja"])
def test_selected_email_cannot_bypass_terminal_status(outreach_mod, status):
    email = f"{status}@example.com"
    with outreach_mod._outreach_db() as conn:
        _add_prospect(conn, email, status=status)
        conn.commit()
        candidates, assessments = outreach_mod._outreach_select_eligible_prospects(
            conn, "cold", 4, 20, emails=[email]
        )

    assert candidates == []
    assert assessments[0]["reason"] == f"status_{status}"


@pytest.mark.parametrize("blocker", ["suppression", "reply", "already_sent"])
def test_selected_email_cannot_bypass_global_blockers(outreach_mod, blocker):
    email = f"{blocker}@example.com"
    with outreach_mod._outreach_db() as conn:
        _add_prospect(conn, email)
        if blocker == "suppression":
            conn.execute(
                "INSERT INTO suppressions (email, reason, added_at) VALUES (?,?,?)",
                (email, "pytest", datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
        elif blocker == "reply":
            conn.execute(
                "INSERT INTO events (email, type, stage, ts) VALUES (?, 'reply', 'cold', ?)",
                (email, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
        else:
            _add_send(conn, email, "cold", datetime.now(timezone.utc) - timedelta(days=10))
        conn.commit()
        candidates, assessments = outreach_mod._outreach_select_eligible_prospects(
            conn, "cold", 4, 20, emails=[email]
        )

    assert candidates == []
    expected = {
        "suppression": "suppressed",
        "reply": "replied",
        "already_sent": "already_contacted",
    }
    assert assessments[0]["reason"] == expected[blocker]


def test_followup_requires_real_predecessor_and_elapsed_after_days(outreach_mod):
    now = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    email = "sequence@example.com"
    with outreach_mod._outreach_db() as conn:
        _add_prospect(conn, email)
        conn.commit()

        missing = outreach_mod._outreach_send_eligibility(
            conn, email, "fu1", 4, now=now
        )
        _add_send(conn, email, "cold", now - timedelta(days=3))
        conn.commit()
        waiting = outreach_mod._outreach_send_eligibility(
            conn, email, "fu1", 4, now=now
        )
        conn.execute("DELETE FROM sends WHERE email=?", (email,))
        _add_send(conn, email, "cold", now - timedelta(days=4))
        conn.commit()
        ready = outreach_mod._outreach_send_eligibility(
            conn, email, "fu1", 4, now=now
        )
        _add_send(conn, email, "fu1", now - timedelta(hours=1))
        conn.commit()
        duplicate = outreach_mod._outreach_send_eligibility(
            conn, email, "fu1", 4, now=now
        )

    assert missing["reason"] == "predecessor_missing"
    assert waiting["reason"] == "after_days_pending"
    assert ready["eligible"] is True
    assert duplicate["reason"] == "stage_already_sent"


def test_test_mode_send_does_not_create_real_history(outreach_mod, monkeypatch):
    email = "test-mode-source@example.com"
    with outreach_mod._outreach_db() as conn:
        _add_prospect(conn, email, status="client")
        cursor = conn.execute(
            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES ('send','queued','','',?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
        )
        job_id = int(cursor.lastrowid)
        conn.commit()

    delivered = []
    monkeypatch.setattr(outreach_mod, "_outreach_wait_send_slot", lambda *args, **kwargs: 0.0)
    monkeypatch.setattr(outreach_mod, "_outreach_send_email_object", lambda msg: delivered.append(msg["To"]))
    outreach_mod._outreach_run_send_job(
        job_id,
        {
            "stage": "cold",
            "max": 1,
            "send": False,
            "test_to": "safe-inbox@example.net",
            "email": "",
            "emails": [],
            "after_days": 4,
            "delay": 0,
            "jitter": 0,
            "force_window": True,
        },
    )

    with outreach_mod._outreach_db() as conn:
        sends = conn.execute("SELECT COUNT(*) AS c FROM sends").fetchone()["c"]
        status = conn.execute("SELECT status FROM prospects WHERE email=?", (email,)).fetchone()["status"]
    assert delivered == ["safe-inbox@example.net"]
    assert sends == 0
    assert status == "client"


def test_worker_revalidates_after_wait_before_smtp(outreach_mod, monkeypatch):
    email = "race@example.com"
    with outreach_mod._outreach_db() as conn:
        _add_prospect(conn, email)
        cursor = conn.execute(
            "INSERT INTO jobs (kind, status, params_json, log, started_at) VALUES ('send','queued','','',?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
        )
        job_id = int(cursor.lastrowid)
        conn.commit()

    def suppress_during_wait(*_args, **_kwargs):
        with outreach_mod._outreach_db() as race_conn:
            race_conn.execute(
                "INSERT INTO suppressions (email, reason, added_at) VALUES (?,?,?)",
                (email, "race", datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            race_conn.commit()
        return 0.0

    monkeypatch.setattr(outreach_mod, "_outreach_wait_send_slot", suppress_during_wait)
    monkeypatch.setattr(
        outreach_mod,
        "_outreach_send_email_object",
        lambda _msg: pytest.fail("SMTP no debe ejecutarse tras una baja concurrente"),
    )
    outreach_mod._outreach_run_send_job(
        job_id,
        {
            "stage": "cold",
            "max": 1,
            "send": True,
            "test_to": "",
            "email": "",
            "emails": [email],
            "after_days": 4,
            "delay": 0,
            "jitter": 0,
            "force_window": True,
        },
    )

    with outreach_mod._outreach_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM sends").fetchone()["c"] == 0
        job = conn.execute("SELECT status, log FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert job["status"] == "done"
    assert "pre-SMTP (suppressed)" in job["log"]
