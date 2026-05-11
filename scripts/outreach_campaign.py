"""Herramienta de captacion outbound para Vantelia.

Caracteristicas principales:
  - Importacion de prospects desde CSV con deduplicacion.
  - Estado persistente en SQLite (storage/outreach/outreach.db).
  - Secuencia multi-touch: cold -> fu1 -> fu2 -> breakup.
  - Plantillas en scripts/outreach_templates.py, con copy por nicho.
  - Cumplimiento RGPD/LSSI: cabecera List-Unsubscribe, footer con baja, supresion.
  - Throttle por dominio, ventana horaria laboral, jitter humano.
  - Modo dry-run, modo prueba (--test-to) y envio real (--send).
  - Estadisticas y gestion de bajas.

Subcomandos (ejemplos):
  python scripts/outreach_campaign.py import --csv outreach/prospects_torrejon.csv
  python scripts/outreach_campaign.py preview --stage cold --limit 3
  python scripts/outreach_campaign.py send    --stage cold   --max 20
  python scripts/outreach_campaign.py send    --stage cold   --max 20 --send
  python scripts/outreach_campaign.py followup --stage fu1 --after-days 4 --send
  python scripts/outreach_campaign.py suppress --email cliente@x.es --reason "BAJA manual"
  python scripts/outreach_campaign.py suppress --csv outreach/bajas.csv
  python scripts/outreach_campaign.py stats

Sin --send y sin --test-to imprime previsualizaciones, no envia nada.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import smtplib
import sqlite3
import sys
import time
import uuid
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Permite ejecutar el script desde la raiz del repo o desde scripts/.
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from outreach_templates import (  # noqa: E402
    Prospect, STAGE_ORDER, render, niche_copy, stable_pick,
    html_shell, signature_html, cta_button_html, footer_html, footer_text,
    assign_variant, demo_url_with_utm,
)

BASE_DIR = SCRIPTS_DIR.parent
DEFAULT_DB = BASE_DIR / "storage" / "outreach" / "outreach.db"

# -------------------- DB --------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS prospects (
    email          TEXT PRIMARY KEY,
    business_name  TEXT NOT NULL,
    contact_name   TEXT DEFAULT '',
    niche          TEXT DEFAULT '',
    website        TEXT DEFAULT '',
    service_hint   TEXT DEFAULT '',
    city           TEXT DEFAULT '',
    phone          TEXT DEFAULT '',
    tags           TEXT DEFAULT '',
    source         TEXT DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sends (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER DEFAULT 0,
    email       TEXT NOT NULL,
    stage       TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body_text   TEXT DEFAULT '',
    body_html   TEXT DEFAULT '',
    sent_at     TEXT NOT NULL,
    mode        TEXT NOT NULL,
    message_id  TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sends_email_stage ON sends(email, stage);
CREATE INDEX IF NOT EXISTS idx_sends_email_sent  ON sends(email, sent_at);

CREATE TABLE IF NOT EXISTS campaigns (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'draft',
    stage          TEXT NOT NULL DEFAULT 'cold',
    template_stage TEXT NOT NULL DEFAULT 'cold',
    sender         TEXT DEFAULT '',
    delay          REAL DEFAULT 70,
    jitter         REAL DEFAULT 25,
    force_window   INTEGER DEFAULT 0,
    tracking       INTEGER DEFAULT 0,
    job_id         INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    last_sent_at   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status);

CREATE TABLE IF NOT EXISTS campaign_members (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id    INTEGER NOT NULL,
    email          TEXT NOT NULL,
    stage          TEXT NOT NULL DEFAULT 'cold',
    status         TEXT NOT NULL DEFAULT 'pending',
    last_send_id   INTEGER DEFAULT 0,
    last_sent_at   TEXT DEFAULT '',
    next_send_at   TEXT DEFAULT '',
    skip_reason    TEXT DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE(email)
);
CREATE INDEX IF NOT EXISTS idx_campaign_members_campaign ON campaign_members(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_members_email ON campaign_members(email);

CREATE TABLE IF NOT EXISTS suppressions (
    email     TEXT PRIMARY KEY,
    reason    TEXT DEFAULT '',
    added_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    email   TEXT NOT NULL,
    type    TEXT NOT NULL,
    stage   TEXT DEFAULT '',
    url     TEXT DEFAULT '',
    ts      TEXT NOT NULL,
    ua      TEXT DEFAULT '',
    ip      TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_email ON events(email);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL,
    params_json  TEXT DEFAULT '',
    log          TEXT DEFAULT '',
    started_at   TEXT NOT NULL,
    finished_at  TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS templates_overrides (
    stage         TEXT PRIMARY KEY,
    subject_pool  TEXT DEFAULT '',
    body_text     TEXT DEFAULT '',
    body_html     TEXT DEFAULT '',
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autopilot_config (
    id INTEGER PRIMARY KEY CHECK (id=1),
    enabled INTEGER DEFAULT 0,
    targets_json TEXT DEFAULT '[]',
    daily_new_target INTEGER DEFAULT 20,
    daily_cold_cap INTEGER DEFAULT 30,
    auto_followups INTEGER DEFAULT 1,
    last_discovery_at TEXT DEFAULT '',
    last_cold_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
);
INSERT OR IGNORE INTO autopilot_config (id) VALUES (1);
"""

# Migraciones de columnas que se han ido anadiendo a posteriori.
PROSPECT_MIGRATIONS = [
    ("status", "TEXT DEFAULT 'new'"),
    ("notes", "TEXT DEFAULT ''"),
    ("score", "INTEGER DEFAULT 0"),
]

SEND_MIGRATIONS = [
    ("campaign_id", "INTEGER DEFAULT 0"),
    ("body_text", "TEXT DEFAULT ''"),
    ("body_html", "TEXT DEFAULT ''"),
    ("subject_variant", "TEXT DEFAULT ''"),
]


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Migracion idempotente de columnas nuevas en prospects
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(prospects)")}
    for column, ddl in PROSPECT_MIGRATIONS:
        if column not in existing:
            try:
                conn.execute(f"ALTER TABLE prospects ADD COLUMN {column} {ddl}")
            except sqlite3.OperationalError:
                pass
    existing_sends = {row["name"] for row in conn.execute("PRAGMA table_info(sends)")}
    for column, ddl in SEND_MIGRATIONS:
        if column not in existing_sends:
            try:
                conn.execute(f"ALTER TABLE sends ADD COLUMN {column} {ddl}")
            except sqlite3.OperationalError:
                pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sends_campaign ON sends(campaign_id)")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_members_email_unique ON campaign_members(email)")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -------------------- Helpers --------------------

def clean(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_email(value: str) -> str:
    return clean(value).lower()


def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1] if "@" in email else ""


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _email_domain(value: str) -> str:
    if not value or "@" not in value:
        return ""
    return value.rsplit("@", 1)[-1].strip().lower()


def _align_from_email(from_email: str, smtp_username: str) -> str:
    if "@" not in from_email and "@" in smtp_username:
        return smtp_username
    from_domain = _email_domain(from_email)
    smtp_domain = _email_domain(smtp_username)
    if smtp_domain and from_domain and smtp_domain != from_domain:
        return smtp_username
    return from_email


# -------------------- Importacion --------------------

CSV_FIELDS = (
    "business_name", "email", "contact_name", "niche", "website",
    "service_hint", "city", "phone", "tags", "source",
)


def cmd_import(args: argparse.Namespace) -> int:
    csv_path: Path = args.csv
    if not csv_path.exists():
        print(f"CSV no encontrado: {csv_path}")
        return 2

    with closing(connect(args.db)) as conn, csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            print("CSV vacio o sin cabecera.")
            return 2
        added = updated = skipped = 0
        for row in reader:
            email = normalize_email(row.get("email", ""))
            business = clean(row.get("business_name", ""))
            if not email or "@" not in email or not business:
                skipped += 1
                continue
            payload = {
                "email": email,
                "business_name": business,
                "contact_name": clean(row.get("contact_name", "")),
                "niche": clean(row.get("niche", "")),
                "website": clean(row.get("website", "")),
                "service_hint": clean(row.get("service_hint", "")),
                "city": clean(row.get("city", "")) or "Torrejon de Ardoz",
                "phone": clean(row.get("phone", "")),
                "tags": clean(row.get("tags", "")),
                "source": clean(row.get("source", "")) or csv_path.name,
                "now": now_iso(),
            }
            existing = conn.execute("SELECT email FROM prospects WHERE email=?", (email,)).fetchone()
            if existing:
                conn.execute(
                    """UPDATE prospects SET business_name=:business_name, contact_name=:contact_name,
                       niche=:niche, website=:website, service_hint=:service_hint, city=:city,
                       phone=:phone, tags=:tags, source=:source,
                       updated_at=:now WHERE email=:email""",
                    payload,
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO prospects (email, business_name, contact_name, niche, website,
                       service_hint, city, phone, tags, source, created_at, updated_at)
                       VALUES (:email, :business_name, :contact_name, :niche, :website,
                       :service_hint, :city, :phone, :tags, :source, :now, :now)""",
                    payload,
                )
                added += 1
        conn.commit()

    print(f"Import OK: {added} nuevos, {updated} actualizados, {skipped} descartados. DB: {args.db}")
    return 0


# -------------------- SMTP --------------------

def smtp_settings() -> dict[str, object]:
    load_dotenv(BASE_DIR / ".env")
    # OUTREACH_FROM_* permite usar buzon/nombre personal solo para outreach,
    # dejando SMTP_FROM_* para transaccionales (reset, recordatorios, etc.).
    # Personal sender (Pablo Sanchez <pablo@...>) entra mejor en Primary que
    # marca corporativa (Vantelia <info@...>).
    smtp_user = os.getenv("SMTP_USERNAME", "").strip()
    from_email_raw = (
        os.getenv("OUTREACH_FROM_EMAIL", "").strip()
        or os.getenv("SMTP_FROM_EMAIL", "").strip()
        or smtp_user
    )
    from_email = _align_from_email(from_email_raw, smtp_user)
    from_name = (
        os.getenv("OUTREACH_FROM_NAME", "").strip()
        or os.getenv("SMTP_FROM_NAME", "Vantelia").strip()
    )
    reply_to = (
        os.getenv("OUTREACH_REPLY_TO", "").strip()
        or os.getenv("SMTP_REPLY_TO", "soporte@vantelia.es").strip()
    )
    domain_for_id = os.getenv("OUTREACH_MSGID_DOMAIN", "").strip()
    if not domain_for_id:
        domain_for_id = _email_domain(from_email) or "vantelia.es"
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "username": smtp_user,
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_email": from_email,
        "from_name": from_name,
        "reply_to": reply_to,
        "starttls": env_bool("SMTP_STARTTLS", True),
        "unsubscribe_mailto": os.getenv("OUTREACH_UNSUBSCRIBE_EMAIL", "baja@vantelia.es").strip(),
        "bcc": os.getenv("OUTREACH_BCC", "").strip(),
        "domain_for_id": domain_for_id,
    }


def build_message(
    to_email: str,
    subject: str,
    text: str,
    html_body: str,
    settings: dict[str, object],
    in_reply_to: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((str(settings["from_name"]), str(settings["from_email"])))
    msg["To"] = to_email
    if settings["reply_to"]:
        msg["Reply-To"] = str(settings["reply_to"])
    if settings["bcc"]:
        msg["Bcc"] = str(settings["bcc"])
    msg["Message-ID"] = make_msgid(domain=str(settings["domain_for_id"]))
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(text)
    # Enviamos multipart con HTML para mantener consistencia visual y version rica.
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    return msg


def smtp_send(msg: EmailMessage, settings: dict[str, object]) -> None:
    host = str(settings["host"])
    if not host:
        raise RuntimeError("Falta SMTP_HOST en .env")
    with smtplib.SMTP(host, int(settings["port"]), timeout=25) as smtp:
        smtp.ehlo()
        if settings["starttls"]:
            smtp.starttls()
            smtp.ehlo()
        if settings["username"]:
            smtp.login(str(settings["username"]), str(settings["password"]))
        smtp.send_message(msg)


# -------------------- Ventana horaria & throttle --------------------

def in_business_window() -> tuple[bool, str]:
    """Comprueba ventana laboral configurable. Devuelve (ok, motivo)."""
    if not env_bool("OUTREACH_RESPECT_WINDOW", True):
        return True, "ventana desactivada"
    try:
        start = int(os.getenv("OUTREACH_START_HOUR", "9"))
        end = int(os.getenv("OUTREACH_END_HOUR", "19"))
    except ValueError:
        start, end = 9, 19
    skip_weekend = env_bool("OUTREACH_SKIP_WEEKEND", True)
    tz_name = os.getenv("OUTREACH_TIMEZONE", "Europe/Madrid")
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now = datetime.now(ZoneInfo("Europe/Madrid"))
    if skip_weekend and now.weekday() >= 5:
        return False, f"fin de semana ({now.strftime('%a')})"
    if not (start <= now.hour < end):
        return False, f"fuera de horario ({now.hour:02d}h, ventana {start:02d}-{end:02d}h)"
    return True, "ok"


# -------------------- Seleccion --------------------

def fetch_candidates(
    conn: sqlite3.Connection,
    stage: str,
    after_days: int,
    limit: int,
    only_email: str | None = None,
) -> list[Prospect]:
    """Devuelve prospects pendientes para el stage indicado.

    - cold: nunca enviados, no suprimidos.
    - fu1/fu2/breakup: enviado el stage anterior hace >= after_days y no enviado este.
    """
    if stage not in STAGE_ORDER:
        raise ValueError(f"Stage invalido: {stage}")

    if only_email:
        rows = conn.execute(
            "SELECT * FROM prospects WHERE email = ?",
            (normalize_email(only_email),),
        ).fetchall()
        return [_row_to_prospect(r) for r in rows]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=after_days)).isoformat(timespec="seconds")
    prev_stage = STAGE_ORDER[STAGE_ORDER.index(stage) - 1] if stage != "cold" else None

    if stage == "cold":
        sql = """
        SELECT p.* FROM prospects p
        WHERE NOT EXISTS (SELECT 1 FROM sends s WHERE s.email = p.email)
          AND NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.email = p.email)
          AND NOT EXISTS (SELECT 1 FROM events ev WHERE ev.email = p.email AND ev.type = 'reply')
          AND COALESCE(p.status, '') NOT IN ('replied', 'client', 'lost')
        ORDER BY p.created_at ASC
        LIMIT ?
        """
        rows = conn.execute(sql, (limit,)).fetchall()
    else:
        sql = """
        SELECT p.* FROM prospects p
        WHERE EXISTS (
            SELECT 1 FROM sends s WHERE s.email = p.email AND s.stage = ? AND s.sent_at <= ?
        )
        AND NOT EXISTS (
            SELECT 1 FROM sends s2 WHERE s2.email = p.email AND s2.stage = ?
        )
        AND NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.email = p.email)
        AND NOT EXISTS (SELECT 1 FROM events ev WHERE ev.email = p.email AND ev.type = 'reply')
        AND COALESCE(p.status, '') NOT IN ('replied', 'client', 'lost')
        ORDER BY p.created_at ASC
        LIMIT ?
        """
        rows = conn.execute(sql, (prev_stage, cutoff, stage, limit)).fetchall()
    return [_row_to_prospect(r) for r in rows]


def load_template_overrides(conn: sqlite3.Connection) -> dict[str, dict]:
    try:
        rows = conn.execute(
            "SELECT stage, subject_pool, body_text, body_html FROM templates_overrides"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[str, dict] = {}
    for r in rows:
        out[r["stage"]] = {
            "subject_pool": (r["subject_pool"] or "").strip(),
            "body_text": (r["body_text"] or "").strip(),
            "body_html": (r["body_html"] or "").strip(),
        }
    return out


def _template_vars(p: Prospect, unsub: str, stage: str) -> dict[str, str]:
    task, outcome, proof = niche_copy(p.niche, p.service_hint)
    return {
        "first_name": p.first_name or "equipo",
        "first_or_team": p.first_name or "equipo",
        "greeting": p.greeting,
        "business": p.business_name or "",
        "city": p.city or "",
        "niche": p.niche or "",
        "service_hint": p.service_hint or "",
        "website": p.website or "",
        "phone": p.phone or "",
        "task": task,
        "outcome": outcome,
        "proof": proof,
        "unsubscribe": unsub,
        "stage": stage,
        "signature_html": signature_html(stage),
        "footer_html": footer_html(unsub),
        "footer_text": footer_text(unsub),
        "cta_html": cta_button_html("Ver mi demo preparada (1 min)", demo_url_with_utm(stage, p)),
    }


def _apply_template(template: str, vars_: dict[str, str]) -> str:
    if not template:
        return template
    try:
        return template.format_map(_SafeDict(vars_))
    except Exception:
        out = template
        for k, v in vars_.items():
            out = out.replace("{" + k + "}", str(v))
        return out


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_with_override(
    stage: str,
    p: Prospect,
    unsub: str,
    overrides: dict[str, dict] | None = None,
) -> tuple[str, str, str]:
    """Renderiza un email aplicando override de DB si existe, si no usa default."""
    overrides = overrides or {}
    ov = overrides.get(stage) or {}
    has_subj = bool(ov.get("subject_pool"))
    has_text = bool(ov.get("body_text"))
    has_html = bool(ov.get("body_html"))
    if not (has_subj or has_text or has_html):
        return render(stage, p, unsub)

    vars_ = _template_vars(p, unsub, stage)
    default_subject, default_text, default_html = render(stage, p, unsub)

    if has_subj:
        pool = [s.strip() for s in ov["subject_pool"].splitlines() if s.strip()]
        if pool:
            tmpl = stable_pick(p.email + "|" + stage, pool)
            subject = _apply_template(tmpl, vars_)
        else:
            subject = default_subject
    else:
        subject = default_subject

    text = _apply_template(ov["body_text"], vars_) if has_text else default_text

    if has_html:
        raw_html = _apply_template(ov["body_html"], vars_)
        # Si el override es solo el inner (no contiene <html>), envolver en shell.
        if "<html" not in raw_html.lower():
            html = html_shell(raw_html, preheader="")
        else:
            html = raw_html
    else:
        html = default_html

    return subject, text, html


def _row_to_prospect(row: sqlite3.Row) -> Prospect:
    return Prospect(
        email=row["email"],
        business_name=row["business_name"],
        contact_name=row["contact_name"] or "",
        niche=row["niche"] or "",
        website=row["website"] or "",
        service_hint=row["service_hint"] or "",
        city=row["city"] or "Torrejon de Ardoz",
        phone=row["phone"] or "",
        tags=row["tags"] or "",
        source=row["source"] or "",
    )


# -------------------- Comandos send / preview / followup --------------------

def cmd_preview(args: argparse.Namespace) -> int:
    with closing(connect(args.db)) as conn:
        prospects = fetch_candidates(
            conn, args.stage, after_days=args.after_days, limit=args.limit, only_email=args.email,
        )
    if not prospects:
        print(f"Sin candidatos para stage={args.stage}.")
        return 0
    settings = smtp_settings()
    unsub = str(settings["unsubscribe_mailto"]) or "baja@vantelia.es"
    overrides = load_template_overrides(conn)
    for i, p in enumerate(prospects, 1):
        subject, text, _ = render_with_override(args.stage, p, unsub, overrides)
        print(f"\n=== [{i}/{len(prospects)}] {p.email} | {p.business_name} ===")
        print(f"Asunto: {subject}\n")
        print(text)
    return 0


def _send_loop(args: argparse.Namespace, stage: str) -> int:
    real_send = bool(args.send or args.test_to)
    if real_send:
        ok_window, motivo = in_business_window()
        if not ok_window and not args.force_window:
            print(f"Bloqueado por ventana horaria: {motivo}. Usa --force-window para ignorar.")
            return 3

    with closing(connect(args.db)) as conn:
        candidates = fetch_candidates(
            conn, stage, after_days=args.after_days, limit=args.max, only_email=args.email,
        )
        if not candidates:
            print(f"Sin candidatos para stage={stage}.")
            return 0

        settings = smtp_settings()
        unsub = str(settings["unsubscribe_mailto"]) or "baja@vantelia.es"
        overrides = load_template_overrides(conn)
        domain_cap = int(os.getenv("OUTREACH_DOMAIN_DAILY_CAP", "3"))
        # contadores para tope diario por dominio (en envios reales)
        today = datetime.now(timezone.utc).date().isoformat()
        domain_today = defaultdict(int)
        for row in conn.execute(
            "SELECT email FROM sends WHERE substr(sent_at,1,10)=? AND mode='send'",
            (today,),
        ):
            domain_today[domain_of(row["email"])] += 1

        mode = "test" if args.test_to else ("send" if args.send else "dry-run")
        print(f"Stage={stage} mode={mode} candidatos={len(candidates)}")

        sent_count = 0
        for index, p in enumerate(candidates, 1):
            if real_send and not args.test_to:
                if domain_today[domain_of(p.email)] >= domain_cap:
                    print(f"  skip {p.email}: cap diario alcanzado para dominio {domain_of(p.email)}")
                    continue

            subject, text, html_body = render_with_override(stage, p, unsub, overrides)
            recipient = normalize_email(args.test_to) if args.test_to else p.email

            print(f"\n[{index}/{len(candidates)}] {mode.upper()} -> {recipient} | {p.business_name}")
            print(f"  Asunto: {subject}")

            if not real_send:
                continue

            in_reply_to = None
            if stage != "cold":
                prev_stage = STAGE_ORDER[STAGE_ORDER.index(stage) - 1]
                row = conn.execute(
                    "SELECT message_id FROM sends WHERE email=? AND stage=? AND message_id<>'' "
                    "ORDER BY id DESC LIMIT 1",
                    (p.email, prev_stage),
                ).fetchone()
                if row and row["message_id"]:
                    in_reply_to = row["message_id"]

            msg = build_message(recipient, subject, text, html_body, settings, in_reply_to=in_reply_to)
            try:
                smtp_send(msg, settings)
            except Exception as err:  # noqa: BLE001
                print(f"  ERROR enviando a {recipient}: {err}")
                if args.stop_on_error:
                    return 4
                continue

            variant = assign_variant(p.email, stage)
            conn.execute(
                "INSERT INTO sends (campaign_id, email, stage, subject, body_text, body_html, sent_at, mode, message_id, subject_variant) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (0, p.email, stage, subject, text, html_body, now_iso(), mode, msg["Message-ID"] or "", variant),
            )
            conn.commit()
            sent_count += 1
            domain_today[domain_of(p.email)] += 1

            if index < len(candidates):
                delay = max(0.0, args.delay + random.uniform(-args.jitter, args.jitter))
                time.sleep(delay)

    if real_send:
        print(f"\nListo. Enviados: {sent_count}.")
    else:
        print("\nDry-run completado. Usa --test-to tu@email para probar o --send para enviar real.")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    return _send_loop(args, args.stage)


def cmd_followup(args: argparse.Namespace) -> int:
    if args.stage not in {"fu1", "fu2", "breakup"}:
        print("followup requiere --stage fu1|fu2|breakup")
        return 2
    return _send_loop(args, args.stage)


# -------------------- Suppress / stats --------------------

def cmd_suppress(args: argparse.Namespace) -> int:
    with closing(connect(args.db)) as conn:
        added = 0
        if args.email:
            email = normalize_email(args.email)
            conn.execute(
                "INSERT OR REPLACE INTO suppressions (email, reason, added_at) VALUES (?, ?, ?)",
                (email, args.reason, now_iso()),
            )
            added += 1
        if args.csv:
            if not args.csv.exists():
                print(f"CSV no encontrado: {args.csv}")
                return 2
            with args.csv.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle) if args.csv.suffix.lower() == ".csv" else None
                if reader:
                    for row in reader:
                        email = normalize_email(row.get("email", ""))
                        if not email:
                            continue
                        conn.execute(
                            "INSERT OR REPLACE INTO suppressions (email, reason, added_at) VALUES (?, ?, ?)",
                            (email, row.get("reason", "") or args.reason, now_iso()),
                        )
                        added += 1
                else:
                    for line in args.csv.read_text(encoding="utf-8").splitlines():
                        email = normalize_email(line)
                        if email and not email.startswith("#"):
                            conn.execute(
                                "INSERT OR REPLACE INTO suppressions (email, reason, added_at) VALUES (?, ?, ?)",
                                (email, args.reason, now_iso()),
                            )
                            added += 1
        conn.commit()
    print(f"Suprimidos: {added}.")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with closing(connect(args.db)) as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM prospects").fetchone()["c"]
        suppressed = conn.execute("SELECT COUNT(*) AS c FROM suppressions").fetchone()["c"]
        per_stage = conn.execute(
            "SELECT stage, COUNT(*) AS c FROM sends WHERE mode='send' GROUP BY stage"
        ).fetchall()
        last = conn.execute(
            "SELECT email, stage, sent_at FROM sends ORDER BY id DESC LIMIT 5"
        ).fetchall()

        today = datetime.now(timezone.utc).date().isoformat()
        sent_today = conn.execute(
            "SELECT COUNT(*) AS c FROM sends WHERE mode='send' AND substr(sent_at,1,10)=?",
            (today,),
        ).fetchone()["c"]

    print(f"Prospects: {total}")
    print(f"Suprimidos (bajas): {suppressed}")
    print(f"Enviados hoy ({today}): {sent_today}")
    print("Enviados por stage:")
    for row in per_stage:
        print(f"  - {row['stage']}: {row['c']}")
    if last:
        print("Ultimos envios:")
        for row in last:
            print(f"  - {row['sent_at']}  {row['stage']:8s}  {row['email']}")
    return 0


# -------------------- CLI --------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Captacion outbound de Vantelia (multi-touch, RGPD, SQLite).",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Ruta SQLite. Por defecto storage/outreach/outreach.db")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_imp = sub.add_parser("import", help="Importar prospects desde CSV.")
    p_imp.add_argument("--csv", type=Path, required=True)
    p_imp.set_defaults(func=cmd_import)

    p_pre = sub.add_parser("preview", help="Previsualizar emails sin enviar.")
    p_pre.add_argument("--stage", choices=STAGE_ORDER, default="cold")
    p_pre.add_argument("--limit", type=int, default=3)
    p_pre.add_argument("--after-days", type=int, default=0)
    p_pre.add_argument("--email", default="", help="Previsualizar solo un email concreto.")
    p_pre.set_defaults(func=cmd_preview)

    def _attach_send_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--max", type=int, default=20)
        sp.add_argument("--send", action="store_true", help="Enviar de verdad. Sin esto solo previsualiza.")
        sp.add_argument("--test-to", default="", help="Mandar todos los emails a este destinatario para revision.")
        sp.add_argument("--delay", type=float, default=70.0, help="Segundos base entre envios reales.")
        sp.add_argument("--jitter", type=float, default=25.0, help="Jitter aleatorio +/- segundos.")
        sp.add_argument("--after-days", type=int, default=4, help="Dias minimos desde el stage previo (followup).")
        sp.add_argument("--email", default="", help="Forzar el envio a un solo email del DB.")
        sp.add_argument("--force-window", action="store_true", help="Ignorar ventana laboral.")
        sp.add_argument("--stop-on-error", action="store_true", help="Parar la ejecucion al primer error SMTP.")

    p_send = sub.add_parser("send", help="Enviar el primer correo (cold) u otro stage.")
    p_send.add_argument("--stage", choices=STAGE_ORDER, default="cold")
    _attach_send_flags(p_send)
    p_send.set_defaults(func=cmd_send)

    p_fu = sub.add_parser("followup", help="Enviar followup respetando dias minimos.")
    p_fu.add_argument("--stage", choices=["fu1", "fu2", "breakup"], required=True)
    _attach_send_flags(p_fu)
    p_fu.set_defaults(func=cmd_followup)

    p_sup = sub.add_parser("suppress", help="Anadir email(s) a la lista de baja.")
    p_sup.add_argument("--email", default="")
    p_sup.add_argument("--csv", type=Path)
    p_sup.add_argument("--reason", default="manual")
    p_sup.set_defaults(func=cmd_suppress)

    p_st = sub.add_parser("stats", help="Mostrar estadisticas.")
    p_st.set_defaults(func=cmd_stats)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
