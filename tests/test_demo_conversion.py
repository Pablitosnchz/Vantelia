from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _install_auto_demo(
    api_module,
    *,
    email: str,
    booking_enabled: bool = False,
    cliente_id: str = "",
    register: bool = False,
) -> str:
    cliente_id = cliente_id or f"demo_auto_conversion_{uuid.uuid4().hex[:10]}"
    normalized = api_module._normalize_client_config(
        cliente_id,
        {
            "nombre": "Clinica Conversion",
            "color": "#00b1d9",
            "icono": "CC",
            "bienvenida": "Hola, soy el asistente de la demo.",
            "allowed_origins": ["http://testserver"],
            "contacto": {"email": email, "telefono": ""},
            "booking": {"enabled": booking_enabled},
            "whatsapp": {"enabled": False},
        },
    )
    with api_module.state_lock:
        configs = dict(api_module.CONFIG_CLIENTES)
        configs[cliente_id] = normalized
        api_module._update_runtime_configs(configs)
    api_module._persist_configs_to_disk(configs)
    if register:
        api_module._register_demo_tenant(cliente_id, email=email)
    return cliente_id


def _insert_outreach_prospect(api_module, email: str, *, latest_stage: str = "fu2") -> None:
    now = api_module._outreach_now()
    with api_module._outreach_db() as conn:
        conn.execute(
            """INSERT INTO prospects (email, business_name, created_at, updated_at, status)
               VALUES (?,?,?,?,?)""",
            (email, "Clinica Conversion", now, now, "contacted"),
        )
        conn.execute(
            """INSERT INTO sends (email, stage, subject, sent_at, mode)
               VALUES (?,?,?,?,?)""",
            (email, "cold", "Primer contacto", "2026-01-01T10:00:00+00:00", "send"),
        )
        conn.execute(
            """INSERT INTO sends (email, stage, subject, sent_at, mode)
               VALUES (?,?,?,?,?)""",
            (email, latest_stage, "Seguimiento", "2026-01-05T10:00:00+00:00", "send"),
        )
        conn.commit()


def test_public_demo_claim_url_uses_app_origin() -> None:
    html = (REPO_ROOT / "hostinger_site" / "demo" / "index.html").read_text(encoding="utf-8")
    assert "var claimUrl = API + (claimId ? '/acceso?mode=signup&claim='" in html
    assert "var claimUrl = claimId ? '/acceso?mode=signup&claim='" not in html


def test_auto_demo_without_booking_has_contact_ctas_and_no_booking_promise(client, api_module) -> None:
    cliente_id = _install_auto_demo(
        api_module,
        email=f"page-{uuid.uuid4().hex[:8]}@example.com",
        booking_enabled=False,
        register=True,
    )

    response = client.get(f"/demo/{cliente_id}")

    assert response.status_code == 200
    html = response.text
    assert "mailto:info@vantelia.es?subject=" in html
    assert "Tengo una duda" in html
    assert "https://wa.me/34675802001?text=" in html
    assert "Prefiero seguir por WhatsApp" in html
    assert 'trackDemoEvent("demo_viewed"' in html
    assert 'trackDemoEvent("demo_chat_started"' in html
    assert 'trackDemoEvent("demo_contact_clicked"' in html
    assert 'trackDemoEvent("demo_whatsapp_clicked"' in html
    assert 'trackDemoEvent("demo_claim_clicked"' in html
    session_match = re.search(r'const demoSessionId = "([^"]+)";', html)
    tokens_match = re.search(r"const demoSignalTokens = (\{.*?\});", html)
    assert session_match and tokens_match
    demo_session_id = session_match.group(1)
    demo_signal_tokens = json.loads(tokens_match.group(1))
    assert set(demo_signal_tokens) == {
        "demo_chat_started",
        "demo_contact_clicked",
        "demo_whatsapp_clicked",
        "demo_claim_clicked",
    }
    assert all(
        api_module._outreach_verify_demo_signal_token(
            cliente_id, event_name, demo_session_id, token
        )
        for event_name, token in demo_signal_tokens.items()
    )
    assert api_module.OUTREACH_TRACKING_SECRET not in html
    assert "Quiero reservar una cita" not in html
    assert "Gestiona citas" not in html
    assert "confirma reservas" not in html
    assert "agenda citas automáticamente" not in html


def test_registry_keeps_two_different_email_demos_registered_concurrently(api_module) -> None:
    first_id = _install_auto_demo(
        api_module, email=f"registry-a-{uuid.uuid4().hex[:8]}@example.com"
    )
    second_id = _install_auto_demo(
        api_module, email=f"registry-b-{uuid.uuid4().hex[:8]}@example.com"
    )
    start_gate = threading.Barrier(2)

    def register(cliente_id):
        start_gate.wait(timeout=5)
        api_module._register_demo_tenant(cliente_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(register, first_id),
            executor.submit(register, second_id),
        ]
        for future in futures:
            future.result(timeout=10)

    registry = api_module._load_demo_registry()
    assert first_id in registry
    assert second_id in registry


def test_stale_worker_write_preserves_other_demo_and_fresh_worker_serves_second(
    client, api_module
) -> None:
    with api_module.state_lock:
        stale_worker_snapshot = dict(api_module.CONFIG_CLIENTES)

    first_email = f"worker-a-{uuid.uuid4().hex[:8]}@example.com"
    first_id = _install_auto_demo(
        api_module, email=first_email, register=True
    )

    second_email = f"worker-b-{uuid.uuid4().hex[:8]}@example.com"
    second_id = f"demo_auto_worker_b_{uuid.uuid4().hex[:10]}"
    second_config = api_module._normalize_client_config(
        second_id,
        {
            "nombre": "Demo Worker B",
            "color": "#00b1d9",
            "icono": "WB",
            "bienvenida": "Hola desde B.",
            "allowed_origins": ["http://testserver"],
            "contacto": {"email": second_email, "telefono": ""},
            "booking": {"enabled": False},
            "whatsapp": {"enabled": False},
        },
    )

    # El worker B arranco antes del write de A y conserva un snapshot obsoleto.
    stale_worker_snapshot[second_id] = second_config
    api_module._update_runtime_configs(stale_worker_snapshot)
    with api_module._demo_lifecycle_guard():
        latest = api_module._reload_runtime_configs_from_disk()
        assert first_id in latest
        latest[second_id] = second_config
        api_module._persist_configs_to_disk(latest)
        api_module._update_runtime_configs(latest)
    api_module._register_demo_tenant(second_id, email=second_email)

    persisted = api_module._load_client_configs()
    assert first_id in persisted
    assert second_id in persisted

    # Simula un tercer worker que aun no conoce B: el lookup SQLite lo hidrata.
    with api_module.state_lock:
        stale_again = dict(api_module.CONFIG_CLIENTES)
        stale_again.pop(second_id, None)
        api_module._update_runtime_configs(stale_again)
    response = client.get(f"/demo/{second_id}")
    assert response.status_code == 200
    assert "Demo Worker B" in response.text
    assert second_id in api_module.CONFIG_CLIENTES


def test_claimed_auto_demo_page_does_not_emit_signal_tokens(
    client, api_module
) -> None:
    email = f"claimed-page-{uuid.uuid4().hex[:8]}@example.com"
    cliente_id = _install_auto_demo(api_module, email=email, register=True)
    with api_module.state_lock:
        configs = dict(api_module.CONFIG_CLIENTES)
    api_module._persist_configs_to_disk(configs)
    api_module.db_set_client_owner(
        cliente_id, f"claimed_owner_{uuid.uuid4().hex[:8]}", source="claim_demo"
    )

    response = client.get(f"/demo/{cliente_id}")

    assert response.status_code == 200
    assert "const demoSignalTokens = {};" in response.text
    assert "v2." not in response.text


def test_claim_between_purge_snapshot_and_reservation_prevents_deletion(
    api_module, monkeypatch
) -> None:
    email = f"claim-race-{uuid.uuid4().hex[:8]}@example.com"
    cliente_id = _install_auto_demo(api_module, email=email)
    with api_module.state_lock:
        configs = dict(api_module.CONFIG_CLIENTES)
    api_module._persist_configs_to_disk(configs)
    created_ts = time.time()
    api_module._register_demo_tenant(
        cliente_id, email=email, created_ts=created_ts
    )
    user = api_module._create_user_self_serve(
        email=f"claimer-{uuid.uuid4().hex[:8]}@example.com",
        password="secret-pass-123",
        display_name="Claim Race",
    )

    candidate_snapshotted = threading.Event()
    continue_purge = threading.Event()
    original_reserve = api_module._reserve_demo_purge

    def paused_reserve(cid, created_ts, purge_owner):
        candidate_snapshotted.set()
        assert continue_purge.wait(timeout=10)
        return original_reserve(cid, created_ts, purge_owner)

    # Fuerza una seleccion ya tomada para aislar la ventana snapshot -> delete.
    monkeypatch.setattr(
        api_module, "_demo_purge_candidates", lambda: [(cliente_id, created_ts)]
    )
    monkeypatch.setattr(api_module, "_reserve_demo_purge", paused_reserve)
    with ThreadPoolExecutor(max_workers=1) as executor:
        purge_future = executor.submit(api_module._purge_expired_demos)
        assert candidate_snapshotted.wait(timeout=10)
        assert api_module._claim_cliente_id(cliente_id, user["id"]) == cliente_id
        continue_purge.set()
        assert purge_future.result(timeout=10) == 0

    assert cliente_id in api_module.CONFIG_CLIENTES
    assert api_module.db_get_client_owner(cliente_id) == user["id"]
    assert cliente_id not in api_module._load_demo_registry()


def test_orientative_demo_events_require_bound_tokens_and_do_not_engage(
    client, api_module
) -> None:
    email = f"events-{uuid.uuid4().hex[:8]}@example.com"
    cliente_id = _install_auto_demo(api_module, email=email, register=True)
    _insert_outreach_prospect(api_module, email, latest_stage="fu2")

    bound_session = "bound_session_123456"
    contact_token = api_module._outreach_demo_signal_token(
        cliente_id, "demo_contact_clicked", bound_session
    )
    assert contact_token

    for index, token in enumerate(("", "token-incorrecto")):
        response = client.post(
            "/analytics/event",
            json={
                "event": "demo_contact_clicked",
                "event_source": "demo_page",
                "cliente_id": cliente_id,
                "session_id": bound_session,
                **({"demo_signal_token": token} if token else {}),
            },
        )
        assert response.status_code == 200

    expired_session = "expired_session_123456"
    expired_token = api_module._outreach_demo_signal_token(
        cliente_id,
        "demo_contact_clicked",
        expired_session,
        expires_at=int(time.time()) - 1,
    )
    expired = client.post(
        "/analytics/event",
        json={
            "event": "demo_contact_clicked",
            "event_source": "demo_page",
            "cliente_id": cliente_id,
            "session_id": expired_session,
            "demo_signal_token": expired_token,
        },
    )
    changed_event = client.post(
        "/analytics/event",
        json={
            "event": "demo_whatsapp_clicked",
            "event_source": "demo_page",
            "cliente_id": cliente_id,
            "session_id": bound_session,
            "demo_signal_token": contact_token,
        },
    )
    changed_session = client.post(
        "/analytics/event",
        json={
            "event": "demo_contact_clicked",
            "event_source": "demo_page",
            "cliente_id": cliente_id,
            "session_id": "changed_session_123456",
            "demo_signal_token": contact_token,
        },
    )
    invalid_session = client.post(
        "/analytics/event",
        json={
            "event": "demo_contact_clicked",
            "event_source": "demo_page",
            "cliente_id": cliente_id,
            "session_id": "id inválido!",
            "demo_signal_token": contact_token,
        },
    )
    assert expired.status_code == 200
    assert changed_event.status_code == 200
    assert changed_session.status_code == 200
    assert invalid_session.status_code == 200

    with api_module._outreach_db() as conn:
        unauthorized_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE email=?", (email,)
        ).fetchone()[0]
        status_before_valid = conn.execute(
            "SELECT status FROM prospects WHERE email=?", (email,)
        ).fetchone()["status"]
    assert unauthorized_count == 0
    assert status_before_valid == "contacted"

    expected_types = {
        "demo_chat_started": "demo_chat_opened",
        "demo_contact_clicked": "contact_intent",
        "demo_whatsapp_clicked": "whatsapp_intent",
        "demo_claim_clicked": "claim_intent",
    }
    for index, event_name in enumerate(expected_types):
        session_id = f"demo_session_{index}_123456"
        signal_token = api_module._outreach_demo_signal_token(
            cliente_id, event_name, session_id
        )
        assert signal_token
        payload = {
            "event": event_name,
            "event_source": "demo_page",
            "cliente_id": cliente_id,
            "session_id": session_id,
            "demo_signal_token": signal_token,
        }
        first = client.post("/analytics/event", json=payload)
        duplicate = client.post("/analytics/event", json=payload)
        assert first.status_code == 200
        assert duplicate.status_code == 200

    for event_name in ("demo_viewed", "widget_message_sent", "open", "reply_intent"):
        response = client.post(
            "/analytics/event",
            json={
                "event": event_name,
                "event_source": "demo_page",
                "cliente_id": cliente_id,
                "session_id": f"ignored_{event_name}_123456",
                "demo_signal_token": contact_token,
            },
        )
        assert response.status_code == 200

    with api_module._outreach_db() as conn:
        rows = conn.execute(
            "SELECT type, stage, url, ua, ip FROM events WHERE email=? ORDER BY id",
            (email,),
        ).fetchall()
        prospect = conn.execute(
            "SELECT status FROM prospects WHERE email=?", (email,)
        ).fetchone()

    assert [row["type"] for row in rows] == list(expected_types.values())
    assert all(row["stage"] == "fu2" for row in rows)
    assert all(row["url"].startswith("demo-analytics:") for row in rows)
    assert all(email not in row["url"] and row["ua"] == "" and row["ip"] == "" for row in rows)
    assert prospect["status"] == "contacted"

    with api_module._get_db_connection() as conn:
        viewed = conn.execute(
            """SELECT COUNT(*) FROM analytics_events
               WHERE cliente_id=? AND event_name='demo_viewed'""",
            (cliente_id,),
        ).fetchone()[0]
        stored_metadata = conn.execute(
            """SELECT metadata_json FROM analytics_events
               WHERE cliente_id=? AND event_name='demo_contact_clicked'
               ORDER BY id DESC LIMIT 1""",
            (cliente_id,),
        ).fetchone()["metadata_json"]
    assert viewed == 1
    assert "demo_signal_token" not in stored_metadata
    assert contact_token not in stored_metadata


def test_concurrent_identical_signal_creates_one_outreach_event(api_module) -> None:
    email = f"atomic-{uuid.uuid4().hex[:8]}@example.com"
    cliente_id = _install_auto_demo(api_module, email=email, register=True)
    _insert_outreach_prospect(api_module, email, latest_stage="fu2")
    session_id = "atomic_session_123456"
    signal_token = api_module._outreach_demo_signal_token(
        cliente_id, "demo_chat_started", session_id
    )
    payload = {
        "event": "demo_chat_started",
        "event_source": "demo_page",
        "cliente_id": cliente_id,
        "session_id": session_id,
    }
    start_gate = threading.Barrier(2)

    def mirror_signal():
        start_gate.wait(timeout=5)
        return api_module._outreach_mirror_demo_analytics_event(
            payload, signal_token=signal_token
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(mirror_signal) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]

    assert sum(bool(result) for result in results) == 1
    with api_module._outreach_db() as conn:
        assert conn.execute(
            """SELECT COUNT(*) FROM events
               WHERE email=? AND type='demo_chat_opened'""",
            (email,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT status FROM prospects WHERE email=?", (email,)
        ).fetchone()["status"] == "contacted"


def test_orientative_demo_event_is_ignored_when_secret_is_not_configured(
    client, api_module, monkeypatch
) -> None:
    email = f"nosecret-{uuid.uuid4().hex[:8]}@example.com"
    cliente_id = _install_auto_demo(api_module, email=email, register=True)
    _insert_outreach_prospect(api_module, email)
    session_id = "no_secret_session_123456"
    old_token = api_module._outreach_demo_signal_token(
        cliente_id, "demo_chat_started", session_id
    )
    monkeypatch.setattr(api_module, "OUTREACH_TRACKING_SECRET", "")

    response = client.post(
        "/analytics/event",
        json={
            "event": "demo_chat_started",
            "event_source": "demo_page",
            "cliente_id": cliente_id,
            "session_id": session_id,
            "demo_signal_token": old_token,
        },
    )

    assert response.status_code == 200
    with api_module._outreach_db() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE email=?", (email,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT status FROM prospects WHERE email=?", (email,)
        ).fetchone()["status"] == "contacted"


def test_chat_only_engages_after_user_message_was_persisted(
    client, api_module, monkeypatch
) -> None:
    early_email = f"chat-early-{uuid.uuid4().hex[:8]}@example.com"
    early_id = _install_auto_demo(api_module, email=early_email, register=True)
    _insert_outreach_prospect(api_module, early_email)
    persisted_email = f"chat-persisted-{uuid.uuid4().hex[:8]}@example.com"
    persisted_id = _install_auto_demo(
        api_module, email=persisted_email, register=True
    )
    _insert_outreach_prospect(api_module, persisted_email)

    monkeypatch.setattr(api_module, "_check_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api_module, "db_check_self_serve_quota", lambda cliente_id: {"active": True}
    )

    async def fail_before_persistence(**kwargs):
        raise RuntimeError("fallo antes de persistir")

    monkeypatch.setattr(api_module, "_process_chat_message", fail_before_persistence)
    early = client.post(
        "/chat",
        json={
            "cliente_id": early_id,
            "mensaje": "Quiero saber mas",
            "session_id": "early_failure_123456",
        },
        headers={"origin": "http://testserver"},
    )
    assert early.status_code == 500

    async def fail_after_persistence(**kwargs):
        kwargs["on_user_message_persisted"](kwargs["session_id"])
        raise RuntimeError("fallo de respuesta posterior")

    monkeypatch.setattr(api_module, "_process_chat_message", fail_after_persistence)
    payload = {
        "cliente_id": persisted_id,
        "mensaje": "Quiero saber mas",
        "session_id": "persisted_failure_123456",
    }
    persisted = client.post(
        "/chat", json=payload, headers={"origin": "http://testserver"}
    )
    replay = client.post(
        "/chat", json=payload, headers={"origin": "http://testserver"}
    )
    assert persisted.status_code == 500
    assert replay.status_code == 500

    with api_module._outreach_db() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE email=?", (early_email,)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT status FROM prospects WHERE email=?", (early_email,)
        ).fetchone()["status"] == "contacted"
        assert conn.execute(
            """SELECT COUNT(*) FROM events
               WHERE email=? AND type='demo_interacted'""",
            (persisted_email,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT status FROM prospects WHERE email=?", (persisted_email,)
        ).fetchone()["status"] == "engaged"


def test_email_signup_and_google_claims_run_in_threadpool(
    client, api_module, monkeypatch
) -> None:
    calls = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(api_module, "_to_thread", fake_to_thread)
    signup_demo = _install_auto_demo(
        api_module,
        email=f"signup-demo-{uuid.uuid4().hex[:8]}@example.com",
        register=True,
    )
    signup = client.post(
        "/auth/signup",
        json={
            "email": f"signup-user-{uuid.uuid4().hex[:8]}@example.com",
            "password": "secret-pass-123",
            "display_name": "Signup Claim",
            "claim": signup_demo,
        },
    )
    assert signup.status_code == 200
    assert signup.json()["redirect_to"] == "/app"

    google_demo = _install_auto_demo(
        api_module,
        email=f"google-demo-{uuid.uuid4().hex[:8]}@example.com",
        register=True,
    )
    state = api_module._oauth_create_state(intent="signup", claim=google_demo)
    google_email = f"google-user-{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_ID", "fake-google-id")
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_SECRET", "fake-google-secret")
    monkeypatch.setattr(
        api_module, "GOOGLE_REDIRECT_URI", "https://app.test/auth/google/callback"
    )

    class FakeGoogleResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return FakeGoogleResponse({"access_token": "fake-access"})

        async def get(self, *args, **kwargs):
            return FakeGoogleResponse(
                {
                    "sub": f"google-sub-{uuid.uuid4().hex}",
                    "email": google_email,
                    "name": "Google Claim",
                    "picture": "",
                }
            )

    monkeypatch.setattr(api_module.httpx, "AsyncClient", FakeAsyncClient)
    google = client.get(
        f"/auth/google/callback?code=fake-code&state={state}",
        follow_redirects=False,
    )
    assert google.status_code in (302, 307)
    assert google.headers["location"] == "/app"
    assert calls.count(api_module._claim_cliente_id) == 2


def test_demo_generate_uses_real_stage_and_confirms_only_new_demo(
    client, api_module, monkeypatch
) -> None:
    email = f"generate-{uuid.uuid4().hex[:8]}@example.com"
    _insert_outreach_prospect(api_module, email, latest_stage="fu1")
    cliente_id = f"demo_auto_generated_{uuid.uuid4().hex[:10]}"
    demo_url = f"https://app.test.local/demo/{cliente_id}"
    untrusted_demo_url = f"https://request-controlled.invalid/demo/{cliente_id}"
    build_calls = []
    sent_messages = []
    to_thread_calls = []

    def fake_build_demo_tenant(**kwargs):
        build_calls.append(kwargs)
        normalized = api_module._normalize_client_config(
            cliente_id,
            {
                "nombre": kwargs["nombre_empresa"],
                "color": "#00b1d9",
                "icono": "CG",
                "bienvenida": "Hola.",
                "allowed_origins": ["http://testserver"],
                "contacto": {"email": kwargs["email"], "telefono": ""},
                "booking": {"enabled": False},
                "whatsapp": {"enabled": False},
            },
        )
        with api_module.state_lock:
            configs = dict(api_module.CONFIG_CLIENTES)
            configs[cliente_id] = normalized
            api_module._update_runtime_configs(configs)
        api_module._register_demo_tenant(cliente_id)
        return {
            "cliente_id": cliente_id,
            "demo_url": untrusted_demo_url,
            "reused": False,
        }

    def fake_send_email(to_email, subject, text_body, html_body="", reply_to=None, **kwargs):
        sent_messages.append(
            {
                "to": to_email,
                "subject": subject,
                "text": text_body,
                "html": html_body,
                "reply_to": reply_to,
            }
        )

    async def fake_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(api_module, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(api_module, "build_demo_tenant", fake_build_demo_tenant)
    monkeypatch.setattr(api_module, "_check_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_module, "_email_delivery_configured", lambda: True)
    monkeypatch.setattr(api_module, "_send_email_message", fake_send_email)
    monkeypatch.setattr(api_module, "_to_thread", fake_to_thread)

    payload = {
        "nombre_empresa": "Clinica Generada",
        "sector": "Salud / Clínica",
        "email": email,
        "website_url": "https://example.com",
    }
    first = client.post(
        "/demo/generate",
        json=payload,
        headers={"host": "request-controlled.invalid", "user-agent": "sensitive-test-agent"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["demo_url"] == demo_url

    lead_messages = [message for message in sent_messages if message["to"] == email]
    assert len(lead_messages) == 1
    assert demo_url in lead_messages[0]["text"]
    assert "1, 2 o 3" in lead_messages[0]["text"]
    assert lead_messages[0]["reply_to"] == api_module.PORTAL_SUPPORT_EMAIL

    with api_module._outreach_db() as conn:
        event = conn.execute(
            """SELECT stage, url, ua, ip FROM events
               WHERE email=? AND type='demo_generated' ORDER BY id DESC LIMIT 1""",
            (email,),
        ).fetchone()
    assert event["stage"] == "fu1"
    assert event["url"] == demo_url
    assert event["ua"] == ""
    assert event["ip"] == ""
    assert to_thread_calls[0] is api_module._purge_expired_demos
    assert fake_build_demo_tenant in to_thread_calls
    assert to_thread_calls.count(fake_send_email) == 2

    # Reutilizar una demo viva no vuelve a enviar la confirmacion al prospecto.
    sent_before_reuse = len(sent_messages)
    reused = client.post("/demo/generate", json=payload)
    assert reused.status_code == 200, reused.text
    assert reused.json()["cliente_id"] == cliente_id
    assert len(sent_messages) == sent_before_reuse
    assert len(build_calls) == 1


def test_demo_generate_reused_result_skips_event_and_all_email(
    client, api_module, monkeypatch
) -> None:
    email = f"reused-{uuid.uuid4().hex[:8]}@example.com"
    _insert_outreach_prospect(api_module, email, latest_stage="fu2")
    cliente_id = f"demo_auto_reused_{uuid.uuid4().hex[:10]}"
    sent_messages = []

    monkeypatch.setattr(api_module, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(api_module, "_check_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api_module,
        "build_demo_tenant",
        lambda **kwargs: {
            "cliente_id": cliente_id,
            "demo_url": "https://request-controlled.invalid/demo/reused",
            "reused": True,
        },
    )
    monkeypatch.setattr(api_module, "_email_delivery_configured", lambda: True)
    monkeypatch.setattr(
        api_module,
        "_send_email_message",
        lambda *args, **kwargs: sent_messages.append((args, kwargs)),
    )

    response = client.post(
        "/demo/generate",
        json={
            "nombre_empresa": "Demo Reutilizada",
            "sector": "Otro",
            "email": email,
        },
        headers={"host": "request-controlled.invalid"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["demo_url"] == f"https://app.test.local/demo/{cliente_id}"
    assert sent_messages == []
    with api_module._outreach_db() as conn:
        assert conn.execute(
            """SELECT COUNT(*) FROM events
               WHERE email=? AND type='demo_generated'""",
            (email,),
        ).fetchone()[0] == 0


def test_concurrent_demo_generation_serializes_email_and_sends_confirmation_once(
    client, api_module, monkeypatch
) -> None:
    email = f"race-{uuid.uuid4().hex[:8]}@example.com"
    _insert_outreach_prospect(api_module, email, latest_stage="fu1")
    cliente_id = f"demo_auto_race_{uuid.uuid4().hex[:10]}"
    start_gate = threading.Barrier(2)
    state_lock = threading.Lock()
    state = {"active": 0, "max_active": 0, "created": False, "calls": 0}
    sent_messages = []

    def fake_unlocked_builder(**kwargs):
        with state_lock:
            state["active"] += 1
            state["calls"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        try:
            time.sleep(0.25)
            with state_lock:
                reused = state["created"]
                state["created"] = True
            return {
                "cliente_id": cliente_id,
                "demo_url": "https://request-controlled.invalid/demo/race",
                "reused": reused,
            }
        finally:
            with state_lock:
                state["active"] -= 1

    def fake_send_email(to_email, *args, **kwargs):
        with state_lock:
            sent_messages.append(to_email)

    monkeypatch.setattr(api_module, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(api_module, "_check_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_module, "_new_demo_cliente_id", lambda nombre: cliente_id)
    monkeypatch.setattr(api_module, "_build_demo_tenant_unlocked", fake_unlocked_builder)
    monkeypatch.setattr(api_module, "_email_delivery_configured", lambda: True)
    monkeypatch.setattr(api_module, "_send_email_message", fake_send_email)

    payload = {
        "nombre_empresa": "Clinica Carrera",
        "sector": "Salud / Clínica",
        "email": email,
    }

    def submit_request():
        start_gate.wait(timeout=5)
        return client.post("/demo/generate", json=payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit_request) for _ in range(2)]
        responses = [future.result(timeout=15) for future in futures]

    assert all(response.status_code == 200 for response in responses)
    assert {response.json()["cliente_id"] for response in responses} == {cliente_id}
    assert state["calls"] == 1
    assert state["max_active"] == 1
    assert sent_messages.count(email) == 1
    with api_module._outreach_db() as conn:
        assert conn.execute(
            """SELECT COUNT(*) FROM events
               WHERE email=? AND type='demo_generated'""",
            (email,),
        ).fetchone()[0] == 1


def test_generation_reserves_cliente_id_and_renews_lease_during_build(
    api_module, monkeypatch
) -> None:
    email = f"lease-{uuid.uuid4().hex[:8]}@example.com"
    cliente_id = f"demo_auto_lease_{uuid.uuid4().hex[:10]}"
    started = threading.Event()
    release = threading.Event()
    captured = {}

    def blocked_builder(**kwargs):
        captured["cliente_id"] = kwargs["cliente_id"]
        started.set()
        assert release.wait(timeout=10)
        return {
            "cliente_id": kwargs["cliente_id"],
            "demo_url": f"https://app.test.local/demo/{kwargs['cliente_id']}",
            "reused": False,
        }

    monkeypatch.setattr(api_module, "_DEMO_GENERATION_LEASE_SECONDS", 0.6)
    monkeypatch.setattr(api_module, "_new_demo_cliente_id", lambda nombre: cliente_id)
    monkeypatch.setattr(api_module, "_build_demo_tenant_unlocked", blocked_builder)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            api_module.build_demo_tenant,
            nombre_empresa="Demo Lease",
            sector="Otro",
            email=email,
        )
        assert started.wait(timeout=10)
        with api_module._get_db_connection() as conn:
            first = conn.execute(
                "SELECT * FROM demo_tenants_registry WHERE email=?", (email,)
            ).fetchone()
        assert first["state"] == "generating"
        assert first["cliente_id"] == cliente_id == captured["cliente_id"]
        first_expiry = float(first["lease_expires_ts"])

        time.sleep(0.9)
        with api_module._get_db_connection() as conn:
            renewed = conn.execute(
                "SELECT lease_expires_ts FROM demo_tenants_registry WHERE email=?",
                (email,),
            ).fetchone()
        assert float(renewed["lease_expires_ts"]) > first_expiry
        competitor = api_module._reserve_demo_generation(
            email,
            "competitor-owner",
            f"demo_auto_competitor_{uuid.uuid4().hex[:8]}",
        )
        assert competitor[0] == "wait"
        release.set()
        result = future.result(timeout=10)

    assert result["cliente_id"] == cliente_id
    assert api_module._demo_registry_row_for_cliente(cliente_id)["state"] == "active"
    api_module._unregister_demo_tenant(cliente_id)


def test_activation_failure_compensates_persisted_reserved_tenant(
    api_module, monkeypatch
) -> None:
    email = f"compensate-{uuid.uuid4().hex[:8]}@example.com"
    cliente_id = f"demo_auto_compensate_{uuid.uuid4().hex[:8]}"

    def persisted_builder(**kwargs):
        normalized = api_module._normalize_client_config(
            kwargs["cliente_id"],
            {
                "nombre": "Demo Compensada",
                "color": "#00b1d9",
                "icono": "DC",
                "bienvenida": "Hola.",
                "allowed_origins": ["http://testserver"],
                "contacto": {"email": email, "telefono": ""},
                "booking": {"enabled": False},
                "whatsapp": {"enabled": False},
            },
        )
        latest = api_module._load_client_configs()
        latest[kwargs["cliente_id"]] = normalized
        api_module._persist_configs_to_disk(latest)
        api_module._update_runtime_configs(latest)
        return {
            "cliente_id": kwargs["cliente_id"],
            "demo_url": f"https://app.test.local/demo/{kwargs['cliente_id']}",
            "reused": False,
        }

    monkeypatch.setattr(api_module, "_new_demo_cliente_id", lambda nombre: cliente_id)
    monkeypatch.setattr(api_module, "_build_demo_tenant_unlocked", persisted_builder)
    monkeypatch.setattr(api_module, "_register_demo_tenant", lambda *args, **kwargs: False)

    with pytest.raises(RuntimeError, match="activar la reserva"):
        api_module.build_demo_tenant(
            nombre_empresa="Demo Compensada",
            sector="Otro",
            email=email,
        )

    assert cliente_id not in api_module._load_client_configs()
    assert cliente_id not in api_module.CONFIG_CLIENTES
    with api_module._get_db_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM clientes WHERE cliente_id=?", (cliente_id,)
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM demo_tenants_registry WHERE email=?", (email,)
        ).fetchone() is None


def test_stale_generating_reservation_is_purged_with_its_tenant(
    api_module,
) -> None:
    email = f"stale-build-{uuid.uuid4().hex[:8]}@example.com"
    cliente_id = _install_auto_demo(api_module, email=email, register=True)
    with api_module._get_db_connection() as conn:
        conn.execute(
            """UPDATE demo_tenants_registry
               SET state='generating', lease_owner='crashed-worker',
                   lease_expires_ts=0, updated_ts=?
               WHERE email=?""",
            (time.time(), email),
        )
        conn.commit()

    assert api_module._purge_expired_demos() >= 1
    assert cliente_id not in api_module._load_client_configs()
    with api_module._get_db_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM demo_tenants_registry WHERE email=?", (email,)
        ).fetchone() is None


def test_background_pregen_replaces_expired_demo_without_losing_cleanup_pointer(
    api_module, monkeypatch
) -> None:
    email = f"pregen-expired-{uuid.uuid4().hex[:8]}@example.com"
    old_id = _install_auto_demo(api_module, email=email, register=True)
    _insert_outreach_prospect(api_module, email, latest_stage="fu2")
    with api_module._outreach_db() as conn:
        conn.execute(
            "UPDATE prospects SET website=? WHERE email=?",
            ("https://example.com", email),
        )
        conn.commit()
    with api_module._get_db_connection() as conn:
        conn.execute(
            "UPDATE demo_tenants_registry SET created_ts=? WHERE email=?",
            (time.time() - api_module.DEMO_TTL_SECONDS - 30, email),
        )
        conn.commit()

    new_id = f"demo_auto_pregen_new_{uuid.uuid4().hex[:8]}"
    builder_started = threading.Event()
    release_builder = threading.Event()

    def blocked_pregen_builder(**kwargs):
        normalized = api_module._normalize_client_config(
            kwargs["cliente_id"],
            {
                "nombre": "Demo Pregen Nueva",
                "color": "#00b1d9",
                "icono": "PN",
                "bienvenida": "Hola.",
                "allowed_origins": ["http://testserver"],
                "contacto": {"email": email, "telefono": ""},
                "booking": {"enabled": False},
                "whatsapp": {"enabled": False},
            },
        )
        latest = api_module._load_client_configs()
        latest[kwargs["cliente_id"]] = normalized
        api_module._persist_configs_to_disk(latest)
        api_module._update_runtime_configs(latest)
        builder_started.set()
        assert release_builder.wait(timeout=10)
        return {
            "cliente_id": kwargs["cliente_id"],
            "demo_url": f"https://app.test.local/demo/{kwargs['cliente_id']}",
            "reused": False,
        }

    monkeypatch.setattr(api_module, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(api_module, "_outreach_demo_pregen_enabled", lambda: True)
    monkeypatch.setattr(api_module, "_new_demo_cliente_id", lambda nombre: new_id)
    monkeypatch.setattr(api_module, "_build_demo_tenant_unlocked", blocked_pregen_builder)

    api_module._outreach_maybe_pregenerate_demo(email)
    assert builder_started.wait(timeout=10)
    with api_module._get_db_connection() as conn:
        active_reservation = conn.execute(
            "SELECT * FROM demo_tenants_registry WHERE email=?", (email,)
        ).fetchone()
        cleanup = conn.execute(
            "SELECT * FROM demo_tenant_cleanup_queue WHERE cliente_id=?", (old_id,)
        ).fetchone()
    assert active_reservation["state"] == "generating"
    assert active_reservation["cliente_id"] == new_id
    assert cleanup["reason"] == "expired_replaced"
    assert old_id in api_module._load_client_configs()

    release_builder.set()
    deadline = time.time() + 10
    while email in api_module._demo_pregen_inflight and time.time() < deadline:
        time.sleep(0.05)
    assert email not in api_module._demo_pregen_inflight
    assert api_module._demo_registry_row_for_cliente(new_id)["state"] == "active"

    assert api_module._purge_expired_demos() >= 1
    persisted = api_module._load_client_configs()
    assert old_id not in persisted
    assert new_id in persisted
    with api_module._get_db_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM demo_tenant_cleanup_queue WHERE cliente_id=?", (old_id,)
        ).fetchone() is None


def _add_runtime_demo_config(api_module, cliente_id: str, email: str) -> None:
    normalized = api_module._normalize_client_config(
        cliente_id,
        {
            "nombre": cliente_id,
            "color": "#00b1d9",
            "icono": "MG",
            "bienvenida": "Hola.",
            "allowed_origins": [],
            "contacto": {"email": email, "telefono": ""},
            "booking": {"enabled": False},
            "whatsapp": {"enabled": False},
        },
    )
    with api_module.state_lock:
        configs = dict(api_module.CONFIG_CLIENTES)
        configs[cliente_id] = normalized
        api_module._update_runtime_configs(configs)


def _open_registry_test_db(path: Path):
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def test_legacy_registry_valid_json_migrates_and_marks_success(
    api_module, monkeypatch, tmp_path
) -> None:
    cliente_id = f"demo_auto_migrate_valid_{uuid.uuid4().hex[:8]}"
    email = f"migrate-valid-{uuid.uuid4().hex[:8]}@example.com"
    _add_runtime_demo_config(api_module, cliente_id, email)
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    (tmp_path / "demo_tenants.json").write_text(
        json.dumps({cliente_id: 1234.5}), encoding="utf-8"
    )
    connection = _open_registry_test_db(tmp_path / "valid.db")
    try:
        api_module._ensure_demo_registry_migrated(connection)
        row = connection.execute(
            "SELECT * FROM demo_tenants_registry WHERE email=?", (email,)
        ).fetchone()
        assert row["cliente_id"] == cliente_id
        assert float(row["created_ts"]) == 1234.5
        assert connection.execute(
            "SELECT value FROM demo_registry_meta WHERE key='json_migrated_v2'"
        ).fetchone()["value"] == "1"
    finally:
        connection.close()


def test_legacy_registry_corrupt_json_is_retryable_and_not_marked(
    api_module, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    registry_path = tmp_path / "demo_tenants.json"
    registry_path.write_text("{no-es-json", encoding="utf-8")
    connection = _open_registry_test_db(tmp_path / "corrupt.db")
    try:
        with pytest.raises(RuntimeError, match="corrupto"):
            api_module._ensure_demo_registry_migrated(connection)
        assert connection.execute(
            "SELECT 1 FROM demo_registry_meta WHERE key='json_migrated_v2'"
        ).fetchone() is None

        cliente_id = f"demo_auto_migrate_retry_{uuid.uuid4().hex[:8]}"
        email = f"migrate-retry-{uuid.uuid4().hex[:8]}@example.com"
        _add_runtime_demo_config(api_module, cliente_id, email)
        registry_path.write_text(
            json.dumps({cliente_id: 5678.0}), encoding="utf-8"
        )
        api_module._ensure_demo_registry_migrated(connection)
        assert connection.execute(
            "SELECT cliente_id FROM demo_tenants_registry WHERE email=?", (email,)
        ).fetchone()["cliente_id"] == cliente_id
        assert connection.execute(
            "SELECT 1 FROM demo_registry_meta WHERE key='json_migrated_v2'"
        ).fetchone() is not None
    finally:
        connection.close()


def test_legacy_registry_duplicate_email_keeps_canonical_and_queues_discarded(
    api_module, monkeypatch, tmp_path
) -> None:
    email = f"migrate-dupe-{uuid.uuid4().hex[:8]}@example.com"
    older_id = f"demo_auto_migrate_old_{uuid.uuid4().hex[:8]}"
    newer_id = f"demo_auto_migrate_new_{uuid.uuid4().hex[:8]}"
    _add_runtime_demo_config(api_module, older_id, email)
    _add_runtime_demo_config(api_module, newer_id, email)
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    (tmp_path / "demo_tenants.json").write_text(
        json.dumps({older_id: 1000.0, newer_id: 2000.0}), encoding="utf-8"
    )
    connection = _open_registry_test_db(tmp_path / "duplicate.db")
    try:
        api_module._ensure_demo_registry_migrated(connection)
        canonical = connection.execute(
            "SELECT cliente_id, created_ts FROM demo_tenants_registry WHERE email=?",
            (email,),
        ).fetchone()
        discarded = connection.execute(
            """SELECT cliente_id, created_ts, reason
               FROM demo_tenant_cleanup_queue WHERE cliente_id=?""",
            (older_id,),
        ).fetchone()
        assert canonical["cliente_id"] == newer_id
        assert float(canonical["created_ts"]) == 2000.0
        assert discarded["cliente_id"] == older_id
        assert float(discarded["created_ts"]) == 1000.0
        assert discarded["reason"] == "migration_duplicate_email"
    finally:
        connection.close()
