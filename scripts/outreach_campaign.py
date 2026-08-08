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
import html as html_lib
import json
import os
import random
import re
import smtplib
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from string import Formatter
try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 fallback
    from backports.zoneinfo import ZoneInfo  # type: ignore

from dotenv import load_dotenv

# Permite ejecutar el script desde la raiz del repo o desde scripts/.
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from outreach_templates import (  # noqa: E402
    Prospect, STAGE_ORDER, render, niche_copy, stable_pick,
    html_shell, signature_html, cta_button_html, footer_html, footer_text,
    assign_variant, demo_url_with_utm, demo_go_url,
    OUTREACH_COPY_BUNDLE_VERSION, OUTREACH_COPY_VARIANTS, SUBJECT_POOLS_AB,
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
    subject TEXT DEFAULT '',
    body_excerpt TEXT DEFAULT '',
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
    subject_pool_b TEXT DEFAULT '',
    body_text_b    TEXT DEFAULT '',
    body_html_b    TEXT DEFAULT '',
    bundle_version TEXT DEFAULT '',
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_template_bundle_history (
    version        TEXT PRIMARY KEY,
    description    TEXT DEFAULT '',
    applied_at     TEXT NOT NULL,
    rollback_json  TEXT NOT NULL,
    rolled_back_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS autopilot_config (
    id INTEGER PRIMARY KEY CHECK (id=1),
    enabled INTEGER DEFAULT 0,
    targets_json TEXT DEFAULT '[]',
    daily_new_target INTEGER DEFAULT 20,
    daily_cold_cap INTEGER DEFAULT 30,
    auto_followups INTEGER DEFAULT 1,
    followup_days_json TEXT DEFAULT '{"fu1":4,"fu2":5,"breakup":6}',
    last_discovery_at TEXT DEFAULT '',
    last_cold_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
);
INSERT OR IGNORE INTO autopilot_config (id) VALUES (1);

CREATE TABLE IF NOT EXISTS autopilot_activity_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    level    TEXT NOT NULL DEFAULT 'info',
    event    TEXT NOT NULL DEFAULT '',
    message  TEXT NOT NULL DEFAULT '',
    detail   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_autopilot_log_ts ON autopilot_activity_log(ts);
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

EVENT_MIGRATIONS = [
    ("subject", "TEXT DEFAULT ''"),
    ("body_excerpt", "TEXT DEFAULT ''"),
]

TEMPLATE_OVERRIDE_MIGRATIONS = [
    ("subject_pool_b", "TEXT DEFAULT ''"),
    ("body_text_b", "TEXT DEFAULT ''"),
    ("body_html_b", "TEXT DEFAULT ''"),
    ("bundle_version", "TEXT DEFAULT ''"),
]


_SCHEMA_INITIALIZED: set[str] = set()


def _template_bundle_row(stage: str) -> dict[str, str]:
    variants = OUTREACH_COPY_VARIANTS[stage]
    return {
        "stage": stage,
        "subject_pool": "\n".join(SUBJECT_POOLS_AB[stage]["A"]),
        "body_text": variants["A"]["body_text"],
        "body_html": variants["A"]["body_html"],
        "subject_pool_b": "\n".join(SUBJECT_POOLS_AB[stage]["B"]),
        "body_text_b": variants["B"]["body_text"],
        "body_html_b": variants["B"]["body_html"],
        "bundle_version": OUTREACH_COPY_BUNDLE_VERSION,
    }


def apply_outreach_copy_bundle(conn: sqlite3.Connection) -> bool:
    """Aplica una sola vez el copy canonico y conserva un rollback logico.

    Devuelve ``True`` solo cuando esta llamada hizo la migracion. Cualquier
    error aborta la transaccion: no se permite enviar con una mezcla parcial de
    plantillas antiguas y nuevas.
    """
    conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        already_applied = conn.execute(
            "SELECT 1 FROM outreach_template_bundle_history WHERE version=?",
            (OUTREACH_COPY_BUNDLE_VERSION,),
        ).fetchone()
        if already_applied:
            conn.commit()
            return False

        previous: dict[str, dict | None] = {}
        for stage in STAGE_ORDER:
            row = conn.execute(
                """SELECT stage, subject_pool, body_text, body_html,
                          subject_pool_b, body_text_b, body_html_b,
                          bundle_version, updated_at
                   FROM templates_overrides WHERE stage=?""",
                (stage,),
            ).fetchone()
            previous[stage] = dict(row) if row else None

        applied_at = now_iso()
        for stage in STAGE_ORDER:
            payload = _template_bundle_row(stage)
            conn.execute(
                """INSERT INTO templates_overrides
                   (stage, subject_pool, body_text, body_html, subject_pool_b,
                    body_text_b, body_html_b, bundle_version, updated_at)
                   VALUES (:stage,:subject_pool,:body_text,:body_html,:subject_pool_b,
                           :body_text_b,:body_html_b,:bundle_version,:updated_at)
                   ON CONFLICT(stage) DO UPDATE SET
                       subject_pool=excluded.subject_pool,
                       body_text=excluded.body_text,
                       body_html=excluded.body_html,
                       subject_pool_b=excluded.subject_pool_b,
                       body_text_b=excluded.body_text_b,
                       body_html_b=excluded.body_html_b,
                       bundle_version=excluded.bundle_version,
                       updated_at=excluded.updated_at""",
                {**payload, "updated_at": applied_at},
            )

        conn.execute(
            """INSERT INTO outreach_template_bundle_history
               (version, description, applied_at, rollback_json, rolled_back_at)
               VALUES (?,?,?,?, '')""",
            (
                OUTREACH_COPY_BUNDLE_VERSION,
                "Copy conversacional A/B estable para cold, FU1, FU2 y cierre",
                applied_at,
                json.dumps({"stages": previous}, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        raise RuntimeError(
            f"No se pudo aplicar el bundle de outreach {OUTREACH_COPY_BUNDLE_VERSION}"
        ) from exc


def rollback_outreach_copy_bundle(
    conn: sqlite3.Connection,
    version: str = OUTREACH_COPY_BUNDLE_VERSION,
) -> bool:
    """Restaura el snapshot anterior sin borrar el registro de la migracion."""
    conn.commit()
    try:
        conn.execute("BEGIN IMMEDIATE")
        history = conn.execute(
            "SELECT rollback_json, rolled_back_at FROM outreach_template_bundle_history WHERE version=?",
            (version,),
        ).fetchone()
        if not history or (history["rolled_back_at"] or "").strip():
            conn.commit()
            return False
        snapshot = json.loads(history["rollback_json"] or "{}")
        previous = snapshot.get("stages") if isinstance(snapshot, dict) else {}
        for stage in STAGE_ORDER:
            row = previous.get(stage) if isinstance(previous, dict) else None
            if row is None:
                conn.execute(
                    "DELETE FROM templates_overrides WHERE stage=? AND bundle_version=?",
                    (stage, version),
                )
                continue
            conn.execute(
                """INSERT INTO templates_overrides
                   (stage, subject_pool, body_text, body_html, subject_pool_b,
                    body_text_b, body_html_b, bundle_version, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(stage) DO UPDATE SET
                       subject_pool=excluded.subject_pool,
                       body_text=excluded.body_text,
                       body_html=excluded.body_html,
                       subject_pool_b=excluded.subject_pool_b,
                       body_text_b=excluded.body_text_b,
                       body_html_b=excluded.body_html_b,
                       bundle_version=excluded.bundle_version,
                       updated_at=excluded.updated_at""",
                (
                    stage,
                    row.get("subject_pool", ""),
                    row.get("body_text", ""),
                    row.get("body_html", ""),
                    row.get("subject_pool_b", ""),
                    row.get("body_text_b", ""),
                    row.get("body_html_b", ""),
                    row.get("bundle_version", ""),
                    row.get("updated_at") or now_iso(),
                ),
            )
        conn.execute(
            "UPDATE outreach_template_bundle_history SET rolled_back_at=? WHERE version=?",
            (now_iso(), version),
        )
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        raise RuntimeError(f"No se pudo revertir el bundle de outreach {version}") from exc


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=8000")
    except sqlite3.OperationalError:
        pass
    key = str(db_path.resolve())
    first_initialization = key not in _SCHEMA_INITIALIZED
    if first_initialization:
        conn.executescript(SCHEMA)
    else:
        # El bundle se comprueba aun con el schema cacheado: otro proceso pudo
        # haber creado una DB legacy entre conexiones.
        apply_outreach_copy_bundle(conn)
        return conn
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
    existing_events = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
    for column, ddl in EVENT_MIGRATIONS:
        if column not in existing_events:
            try:
                conn.execute(f"ALTER TABLE events ADD COLUMN {column} {ddl}")
            except sqlite3.OperationalError:
                pass
    existing_templates = {
        row["name"] for row in conn.execute("PRAGMA table_info(templates_overrides)")
    }
    for column, ddl in TEMPLATE_OVERRIDE_MIGRATIONS:
        if column not in existing_templates:
            # Las plantillas gobiernan envios reales: una migracion incompleta
            # debe impedir arrancar, no degradar silenciosamente a copy legacy.
            conn.execute(f"ALTER TABLE templates_overrides ADD COLUMN {column} {ddl}")
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sends_campaign ON sends(campaign_id)")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_members_email_unique ON campaign_members(email)")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    apply_outreach_copy_bundle(conn)
    _SCHEMA_INITIALIZED.add(key)
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -------------------- Helpers --------------------

def clean(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_email(value: str) -> str:
    v = clean(value).lower()
    if v.startswith("mailto:"):
        v = v[len("mailto:"):]
    return v.split("?")[0].strip()


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
    # Con SMTP dedicado de captacion (OUTREACH_SMTP_*), el From es el que diga
    # OUTREACH_FROM_EMAIL tal cual: los relays (Brevo, SMTP2GO...) autentican
    # con un usuario que no es del dominio y autorizan el From via DKIM del
    # dominio verificado — alinear al usuario del relay seria un error.
    dedicated_host = os.getenv("OUTREACH_SMTP_HOST", "").strip()
    smtp_user = (
        os.getenv("OUTREACH_SMTP_USERNAME", "").strip()
        or os.getenv("SMTP_USERNAME", "").strip()
    )
    from_email_raw = (
        os.getenv("OUTREACH_FROM_EMAIL", "").strip()
        or os.getenv("SMTP_FROM_EMAIL", "").strip()
        or smtp_user
    )
    if dedicated_host and os.getenv("OUTREACH_FROM_EMAIL", "").strip():
        from_email = from_email_raw
    else:
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


def is_smtp_ratelimit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "ratelimit" in msg
        or "rate limit" in msg
        or "too many" in msg
        or "quota" in msg
        or "throttl" in msg
        or "hostinger_out_ratelimit" in msg
        or ("451" in msg and ("limit" in msg or "temporar" in msg))
    )


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


_BLOCKED_MAILBOXES = {
    "privacy", "privacidad", "legal", "dpd", "dpo", "noreply", "donotreply",
    "noresponder", "postmaster", "abuse", "administracion", "administrator", "admin",
}
_GENERIC_ALLOWED_MAILBOXES = {
    "info", "reservas", "reserva", "contacto", "contact", "hola", "recepcion",
    "citas", "cita", "ventas", "comercial", "clientes", "atencionalcliente",
}
_PUBLIC_DOMAIN_MARKERS = (
    ".gob.es", ".gov.es", ".gov", ".mil", "administracion.gob.es",
)
_PUBLIC_OR_INSTITUTION_MARKERS = (
    "ayuntamiento", "diputacion", "cabildo", "ministerio", "consejeria",
    "gobierno de", "comunidad autonoma", "policia", "guardia civil",
    "embajada", "consulado", "universidad", "colegio oficial", "camara de comercio",
)
_KNOWN_CHAIN_MARKERS = (
    "adeslas", "asisa", "basic fit", "burger king", "dentix", "dkv", "domino s",
    "donte group", "hm hospitales", "kivet", "kids us", "mapfre", "mcdonald",
    "quironsalud", "sanitas", "starbucks", "telepizza", "vitaldent", "vithas", "vivanta",
)


def _normalized_words(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()


def _email_local_part(email: str) -> str:
    return normalize_email(email).split("@", 1)[0] if "@" in normalize_email(email) else ""


def prospect_segmentation_block_reason(p: Prospect) -> str:
    """Motivo estable de exclusion; cadena vacia significa candidato permitido."""
    email = normalize_email(p.email)
    if not email or "@" not in email:
        return "invalid_email"
    local, domain = email.rsplit("@", 1)
    compact_local = re.sub(r"[^a-z0-9]+", "", _normalized_words(local))
    if compact_local in _BLOCKED_MAILBOXES or compact_local.startswith(("noreply", "donotreply")):
        return "blocked_mailbox"
    if any(domain == marker.lstrip(".") or domain.endswith(marker) for marker in _PUBLIC_DOMAIN_MARKERS):
        return "public_administration"

    identity = _normalized_words(
        " ".join((p.business_name, p.niche, p.service_hint, p.tags, p.source))
    )
    if any(marker in identity for marker in _PUBLIC_OR_INSTITUTION_MARKERS):
        return "public_or_institution"
    if any(marker in identity for marker in _KNOWN_CHAIN_MARKERS):
        return "known_chain"
    if any(token in {"cadena", "franquicia", "chain"} for token in identity.split()):
        return "known_chain"
    return ""


def prospect_email_is_personal(email: str) -> bool:
    local = _email_local_part(email)
    compact = re.sub(r"[^a-z0-9]+", "", _normalized_words(local))
    if not compact or compact in _GENERIC_ALLOWED_MAILBOXES or compact in _BLOCKED_MAILBOXES:
        return False
    return bool(re.search(r"[._-]", local)) or len(compact) >= 7


def prospect_priority_score(p: Prospect) -> int:
    """Prioriza persona y negocio independiente sin excluir buzones SME validos."""
    score = 0
    if p.contact_name.strip():
        score += 5
    if prospect_email_is_personal(p.email):
        score += 4
    email_domain = domain_of(p.email)
    if email_domain.startswith("www."):
        email_domain = email_domain[4:]
    website = (p.website or "").strip().lower()
    website_domain = re.sub(r"^https?://", "", website).split("/", 1)[0]
    if website_domain.startswith("www."):
        website_domain = website_domain[4:]
    if email_domain and website_domain and (
        email_domain == website_domain or website_domain.endswith("." + email_domain)
    ):
        score += 2
    if not prospect_segmentation_block_reason(p):
        score += 1
    return score


def revalidate_send_candidate(
    conn: sqlite3.Connection,
    email: str,
    stage: str,
    after_days: int,
) -> tuple[Prospect | None, str]:
    """Relee DB y aplica toda la elegibilidad justo antes de un envio real."""
    if stage not in STAGE_ORDER:
        return None, "invalid_stage"
    normalized = normalize_email(email)
    row = conn.execute("SELECT * FROM prospects WHERE email=?", (normalized,)).fetchone()
    if not row:
        return None, "missing_prospect"
    prospect = _row_to_prospect(row)
    blocked = prospect_segmentation_block_reason(prospect)
    if blocked:
        return None, blocked
    if conn.execute("SELECT 1 FROM suppressions WHERE email=?", (normalized,)).fetchone():
        return None, "suppressed"
    if conn.execute(
        "SELECT 1 FROM events WHERE email=? AND type='reply' LIMIT 1", (normalized,)
    ).fetchone():
        return None, "already_replied"
    status = str(row["status"] or "").strip().lower()
    if status in {"replied", "client", "lost", "bounced", "baja"}:
        return None, f"status_{status}"

    if stage == "cold":
        if conn.execute(
            "SELECT 1 FROM sends WHERE email=? AND mode='send' LIMIT 1", (normalized,)
        ).fetchone():
            return None, "already_contacted"
    else:
        previous_stage = STAGE_ORDER[STAGE_ORDER.index(stage) - 1]
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max(0, int(after_days)))
        ).isoformat(timespec="seconds")
        if not conn.execute(
            """SELECT 1 FROM sends
               WHERE email=? AND stage=? AND mode='send' AND sent_at<=? LIMIT 1""",
            (normalized, previous_stage, cutoff),
        ).fetchone():
            return None, "previous_stage_or_delay_missing"
        if conn.execute(
            "SELECT 1 FROM sends WHERE email=? AND stage=? AND mode='send' LIMIT 1",
            (normalized, stage),
        ).fetchone():
            return None, "stage_already_sent"
    return prospect, ""


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
        prospect, _reason = revalidate_send_candidate(
            conn, only_email, stage, after_days
        )
        return [prospect] if prospect else []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=after_days)).isoformat(timespec="seconds")
    prev_stage = STAGE_ORDER[STAGE_ORDER.index(stage) - 1] if stage != "cold" else None

    if stage == "cold":
        sql = """
        SELECT p.* FROM prospects p
        WHERE NOT EXISTS (SELECT 1 FROM sends s WHERE s.email = p.email AND s.mode='send')
          AND NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.email = p.email)
          AND NOT EXISTS (SELECT 1 FROM events ev WHERE ev.email = p.email AND ev.type = 'reply')
          AND COALESCE(p.status, '') NOT IN ('replied', 'client', 'lost', 'bounced', 'baja')
        ORDER BY
          CASE
            WHEN lower(COALESCE(p.niche,'') || ' ' || COALESCE(p.service_hint,'') || ' ' || COALESCE(p.tags,'')) LIKE '%dental%'
              OR lower(COALESCE(p.niche,'') || ' ' || COALESCE(p.service_hint,'') || ' ' || COALESCE(p.tags,'')) LIKE '%clinica%'
              OR lower(COALESCE(p.niche,'') || ' ' || COALESCE(p.service_hint,'') || ' ' || COALESCE(p.tags,'')) LIKE '%clínica%'
              OR lower(COALESCE(p.niche,'') || ' ' || COALESCE(p.service_hint,'') || ' ' || COALESCE(p.tags,'')) LIKE '%fisio%'
              OR lower(COALESCE(p.niche,'') || ' ' || COALESCE(p.service_hint,'') || ' ' || COALESCE(p.tags,'')) LIKE '%psico%'
              OR lower(COALESCE(p.niche,'') || ' ' || COALESCE(p.service_hint,'') || ' ' || COALESCE(p.tags,'')) LIKE '%abog%'
              OR lower(COALESCE(p.niche,'') || ' ' || COALESCE(p.service_hint,'') || ' ' || COALESCE(p.tags,'')) LIKE '%asesor%'
              OR lower(COALESCE(p.niche,'') || ' ' || COALESCE(p.service_hint,'') || ' ' || COALESCE(p.tags,'')) LIKE '%gestor%'
            THEN 0
            WHEN lower(COALESCE(p.niche,'') || ' ' || COALESCE(p.service_hint,'') || ' ' || COALESCE(p.tags,'')) LIKE '%peluquer%'
              OR lower(COALESCE(p.niche,'') || ' ' || COALESCE(p.service_hint,'') || ' ' || COALESCE(p.tags,'')) LIKE '%barber%'
            THEN 2
            ELSE 1
          END ASC,
          COALESCE(p.score, 0) DESC,
          p.created_at ASC
        """
        rows = conn.execute(sql).fetchall()
    else:
        sql = """
        SELECT p.* FROM prospects p
        WHERE EXISTS (
            SELECT 1 FROM sends s WHERE s.email = p.email AND s.stage = ? AND s.mode='send' AND s.sent_at <= ?
        )
        AND NOT EXISTS (
            SELECT 1 FROM sends s2 WHERE s2.email = p.email AND s2.stage = ? AND s2.mode='send'
        )
        AND NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.email = p.email)
        AND NOT EXISTS (SELECT 1 FROM events ev WHERE ev.email = p.email AND ev.type = 'reply')
        AND COALESCE(p.status, '') NOT IN ('replied', 'client', 'lost', 'bounced', 'baja')
        ORDER BY
          CASE
            WHEN EXISTS (SELECT 1 FROM events ev2 WHERE ev2.email=p.email AND ev2.type IN ('demo_generated','click','reply_intent')) THEN 0
            WHEN EXISTS (SELECT 1 FROM events ev3 WHERE ev3.email=p.email AND ev3.type='open') THEN 1
            ELSE 2
          END ASC,
          COALESCE(p.score, 0) DESC,
          p.created_at ASC
        """
        rows = conn.execute(sql, (prev_stage, cutoff, stage)).fetchall()
    prospects = [
        prospect for prospect in (_row_to_prospect(row) for row in rows)
        if not prospect_segmentation_block_reason(prospect)
    ]
    if stage == "cold":
        # Conserva el orden SQL como desempate y antepone contactos personales
        # o señales de dominio propio/negocio independiente.
        prospects = [
            item[1]
            for item in sorted(
                enumerate(prospects),
                key=lambda item: (-prospect_priority_score(item[1]), item[0]),
            )
        ]
    return prospects[:max(0, int(limit))]


def load_template_overrides(
    conn: sqlite3.Connection,
    *,
    fail_closed: bool = True,
) -> dict[str, dict]:
    try:
        rows = conn.execute(
            """SELECT stage, subject_pool, body_text, body_html,
                      subject_pool_b, body_text_b, body_html_b, bundle_version
               FROM templates_overrides"""
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if fail_closed:
            raise RuntimeError("Schema de templates_overrides incompleto") from exc
        return {}
    out: dict[str, dict] = {}
    for r in rows:
        override = {
            "subject_pool": (r["subject_pool"] or "").strip(),
            "body_text": (r["body_text"] or "").strip(),
            "body_html": (r["body_html"] or "").strip(),
            "subject_pool_b": (r["subject_pool_b"] or "").strip(),
            "body_text_b": (r["body_text_b"] or "").strip(),
            "body_html_b": (r["body_html_b"] or "").strip(),
            "bundle_version": (r["bundle_version"] or "").strip(),
        }
        try:
            validate_template_override(
                subject_pool=override["subject_pool"],
                body_text=override["body_text"],
                body_html=override["body_html"],
            )
            validate_template_override(
                subject_pool=override["subject_pool_b"],
                body_text=override["body_text_b"],
                body_html=override["body_html_b"],
            )
        except ValueError as exc:
            if fail_closed:
                raise RuntimeError(f"Override invalido para stage={r['stage']}") from exc
            continue
        out[r["stage"]] = override
    return out


_ALLOWED_TEMPLATE_FIELDS = {
    "first_name", "first_or_team", "greeting", "business", "city", "niche",
    "service_hint", "website", "phone", "task", "outcome", "proof",
    "unsubscribe", "stage", "signature_html", "footer_html", "footer_text",
    "cta_url", "cta_html",
}


def _validate_template_string(template: str, label: str) -> None:
    if not template:
        return
    try:
        parsed = list(Formatter().parse(template))
    except ValueError as exc:
        raise ValueError(f"{label}: llaves desbalanceadas") from exc
    for _literal, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if field_name not in _ALLOWED_TEMPLATE_FIELDS:
            raise ValueError(f"{label}: placeholder no permitido {{{field_name}}}")
        if format_spec or conversion:
            raise ValueError(f"{label}: formatos o conversiones no permitidos")


def validate_template_override(
    subject_pool: str = "",
    body_text: str = "",
    body_html: str = "",
) -> None:
    _validate_template_string(subject_pool, "subject_pool")
    _validate_template_string(body_text, "body_text")
    _validate_template_string(body_html, "body_html")


def _template_vars(
    p: Prospect,
    unsub: str,
    stage: str,
    *,
    html_context: bool = False,
) -> dict[str, str]:
    task, outcome, proof = niche_copy(p.niche, p.service_hint)
    values = {
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
        "cta_url": demo_go_url(stage, p),
        "cta_html": cta_button_html("Probar una demo", demo_go_url(stage, p)),
    }
    if not html_context:
        return values
    trusted_html = {"signature_html", "footer_html", "cta_html"}
    escaped = {
        key: (value if key in trusted_html else html_lib.escape(str(value), quote=True))
        for key, value in values.items()
    }
    return escaped


def _apply_template(template: str, vars_: dict[str, str]) -> str:
    if not template:
        return template
    _validate_template_string(template, "template")
    return template.format_map(_SafeDict(vars_))


def _html_has_vantelia_signature(html: str) -> bool:
    needle = (html or "").lower()
    return (
        "logo_letra.png" in needle
        or "tel:+34675802001" in needle
        or "info@vantelia.es" in needle
        or "{signature_html}" in needle
    )


def _append_signature_to_inner_html(inner_html: str, stage: str) -> str:
    if not inner_html or _html_has_vantelia_signature(inner_html):
        return inner_html
    return f"{inner_html.rstrip()}\n{signature_html(stage)}"


def _append_signature_to_html_document(html: str, stage: str) -> str:
    if not html or _html_has_vantelia_signature(html):
        return html
    signature = signature_html(stage)
    if "</body>" in html.lower():
        return re.sub(r"</body>", f"{signature}</body>", html, count=1, flags=re.IGNORECASE)
    return f"{html.rstrip()}\n{signature}"


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_with_override_and_variant(
    stage: str,
    p: Prospect,
    unsub: str,
    overrides: dict[str, dict] | None = None,
) -> tuple[str, str, str, str]:
    """Renderiza subject+body de la misma variante A/B y la devuelve."""
    overrides = overrides or {}
    ov = overrides.get(stage) or {}
    variant = assign_variant(p.email, stage)
    suffix = "_b" if variant == "B" else ""
    subject_key = f"subject_pool{suffix}"
    text_key = f"body_text{suffix}"
    html_key = f"body_html{suffix}"
    has_subj = bool(ov.get(subject_key))
    has_text = bool(ov.get(text_key))
    has_html = bool(ov.get(html_key))
    if not (has_subj or has_text or has_html):
        subject, text, html = render(stage, p, unsub)
        return subject, text, html, variant

    vars_ = _template_vars(p, unsub, stage)
    html_vars = _template_vars(p, unsub, stage, html_context=True)
    default_subject, default_text, default_html = render(stage, p, unsub)

    if has_subj:
        pool = [s.strip() for s in ov[subject_key].splitlines() if s.strip()]
        if pool:
            tmpl = stable_pick(p.email + "|" + stage + "|" + variant, pool)
            subject = _apply_template(tmpl, vars_)
        else:
            subject = default_subject
    else:
        subject = default_subject

    text = _apply_template(ov[text_key], vars_) if has_text else default_text

    if has_html:
        raw_template = ov[html_key]
        raw_html = _apply_template(raw_template, html_vars)
        # Si el override es solo el inner (no contiene <html>), envolver en shell.
        if "<html" not in raw_html.lower():
            html = html_shell(_append_signature_to_inner_html(raw_html, stage), preheader="")
        else:
            html = raw_html if "{signature_html}" in raw_template else _append_signature_to_html_document(raw_html, stage)
    else:
        html = default_html

    return subject, text, html, variant


def render_with_override(
    stage: str,
    p: Prospect,
    unsub: str,
    overrides: dict[str, dict] | None = None,
) -> tuple[str, str, str]:
    """Wrapper compatible para consumidores que aun esperan tres valores."""
    subject, text, html, _variant = render_with_override_and_variant(
        stage, p, unsub, overrides
    )
    return subject, text, html


def _row_to_prospect(row: sqlite3.Row) -> Prospect:
    return Prospect(
        email=row["email"],
        business_name=row["business_name"],
        contact_name=row["contact_name"] or "",
        niche=row["niche"] or "",
        website=row["website"] or "",
        service_hint=row["service_hint"] or "",
        city=row["city"] or "",
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
        overrides = load_template_overrides(conn)
    if not prospects:
        print(f"Sin candidatos para stage={args.stage}.")
        return 0
    settings = smtp_settings()
    unsub = str(settings["unsubscribe_mailto"]) or "baja@vantelia.es"
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
                fresh_prospect, eligibility_reason = revalidate_send_candidate(
                    conn, p.email, stage, args.after_days
                )
                if not fresh_prospect:
                    print(f"  skip {p.email}: {eligibility_reason}")
                    continue
                p = fresh_prospect
            if real_send and not args.test_to:
                if domain_today[domain_of(p.email)] >= domain_cap:
                    print(f"  skip {p.email}: cap diario alcanzado para dominio {domain_of(p.email)}")
                    continue

            subject, text, html_body, variant = render_with_override_and_variant(
                stage, p, unsub, overrides
            )
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
                if is_smtp_ratelimit_error(err):
                    print("  RATE LIMIT SMTP detectado. Deteniendo envio para proteger reputacion.")
                    return 5
                if args.stop_on_error:
                    return 4
                continue

            if mode == "send":
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
