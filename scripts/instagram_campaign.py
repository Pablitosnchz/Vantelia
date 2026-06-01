"""CLI captacion Instagram para Vantelia.

Espejo de outreach_campaign.py pero adaptado a DM IG y modo HIBRIDO COMPLIANT por defecto:
no envia DMs automaticamente. Genera drafts marcados ready=1 para envio manual 1-clic
desde panel admin via ig.me deep link.

Solo si IG_AUTOSEND_ENABLED=true y existe scripts/instagram_autosend.py (opcional) se
puede activar envio automatizado via Playwright (riesgo bloqueo cuenta Meta).

Subcomandos:
  python scripts/instagram_campaign.py import   --csv outreach/ig_dental.csv
  python scripts/instagram_campaign.py discover --usernames cuenta1,cuenta2 --niche "dental"
  python scripts/instagram_campaign.py preview  --stage cold --limit 3
  python scripts/instagram_campaign.py draft    --stage cold --max 20
  python scripts/instagram_campaign.py send     --stage cold --max 20 --send
  python scripts/instagram_campaign.py followup --stage fu1 --after-days 5 --send
  python scripts/instagram_campaign.py suppress --username @cuenta --reason BAJA
  python scripts/instagram_campaign.py stats

Sin --send marca como draft pendiente (mode='draft'). Con --send queda como
'pending_manual_send' salvo IG_AUTOSEND_ENABLED.
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from instagram_templates import (  # noqa: E402
    IGProspect,
    STAGE_ORDER,
    render,
    igme_deep_link,
)
from instagram_discover import (  # noqa: E402
    IGProfile,
    normalize_username,
    discover_usernames,
)

BASE_DIR = SCRIPTS_DIR.parent
DEFAULT_DB = BASE_DIR / "storage" / "instagram" / "instagram.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS ig_prospects (
    username             TEXT PRIMARY KEY,
    full_name            TEXT DEFAULT '',
    bio                  TEXT DEFAULT '',
    business_category    TEXT DEFAULT '',
    niche                TEXT DEFAULT '',
    city                 TEXT DEFAULT '',
    followers_count      INTEGER DEFAULT 0,
    following_count      INTEGER DEFAULT 0,
    posts_count          INTEGER DEFAULT 0,
    website              TEXT DEFAULT '',
    public_email         TEXT DEFAULT '',
    public_phone         TEXT DEFAULT '',
    profile_url          TEXT DEFAULT '',
    avatar_url           TEXT DEFAULT '',
    is_business_account  INTEGER DEFAULT 0,
    is_verified          INTEGER DEFAULT 0,
    score                INTEGER DEFAULT 0,
    status               TEXT DEFAULT 'new',
    tags                 TEXT DEFAULT '',
    notes                TEXT DEFAULT '',
    source               TEXT DEFAULT '',
    service_hint         TEXT DEFAULT '',
    last_contacted_at    TEXT DEFAULT '',
    next_followup_at     TEXT DEFAULT '',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ig_sends (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL,
    stage           TEXT NOT NULL,
    variant         TEXT DEFAULT '',
    message_text    TEXT NOT NULL,
    mode            TEXT NOT NULL DEFAULT 'draft',
    ready           INTEGER DEFAULT 1,
    sent_at         TEXT DEFAULT '',
    drafted_at      TEXT NOT NULL,
    ig_thread_id    TEXT DEFAULT '',
    skip_reason     TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ig_sends_user_stage ON ig_sends(username, stage);
CREATE INDEX IF NOT EXISTS idx_ig_sends_mode ON ig_sends(mode);

CREATE TABLE IF NOT EXISTS ig_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT NOT NULL,
    type      TEXT NOT NULL,
    stage     TEXT DEFAULT '',
    data_json TEXT DEFAULT '',
    ts        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ig_events_user ON ig_events(username);
CREATE INDEX IF NOT EXISTS idx_ig_events_ts ON ig_events(ts);

CREATE TABLE IF NOT EXISTS ig_suppressions (
    username   TEXT PRIMARY KEY,
    reason     TEXT DEFAULT '',
    added_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ig_autopilot_config (
    id                  INTEGER PRIMARY KEY CHECK (id=1),
    enabled             INTEGER DEFAULT 0,
    targets_json        TEXT DEFAULT '[]',
    daily_new_target    INTEGER DEFAULT 15,
    daily_outreach_cap  INTEGER DEFAULT 25,
    auto_followups      INTEGER DEFAULT 1,
    last_discovery_at   TEXT DEFAULT '',
    last_outreach_at    TEXT DEFAULT '',
    updated_at          TEXT DEFAULT ''
);
INSERT OR IGNORE INTO ig_autopilot_config (id) VALUES (1);

CREATE TABLE IF NOT EXISTS ig_templates_overrides (
    stage      TEXT PRIMARY KEY,
    opener     TEXT DEFAULT '',
    body       TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ig_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL,
    params_json  TEXT DEFAULT '',
    log          TEXT DEFAULT '',
    started_at   TEXT NOT NULL,
    finished_at  TEXT DEFAULT ''
);
"""


_SCHEMA_INITIALIZED: set[str] = set()


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
    if key not in _SCHEMA_INITIALIZED:
        conn.executescript(SCHEMA)
        _ensure_columns(conn)
        _SCHEMA_INITIALIZED.add(key)
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(ig_prospects)").fetchall()}
    for name in ("last_contacted_at", "next_followup_at"):
        if name not in cols:
            conn.execute(f"ALTER TABLE ig_prospects ADD COLUMN {name} TEXT DEFAULT ''")
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -------------------- helpers --------------------


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def is_autosend_enabled() -> bool:
    return env_bool("IG_AUTOSEND_ENABLED", False)


def _row_to_prospect(row: sqlite3.Row) -> IGProspect:
    return IGProspect(
        username=row["username"],
        full_name=row["full_name"] or "",
        bio=row["bio"] or "",
        business_category=row["business_category"] or "",
        niche=row["niche"] or "",
        city=row["city"] or "",
        website=row["website"] or "",
        public_email=row["public_email"] or "",
        service_hint=row["service_hint"] or "",
    )


def _is_suppressed(conn: sqlite3.Connection, username: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM ig_suppressions WHERE username=?",
        (username,),
    ).fetchone()
    return row is not None


# -------------------- upsert --------------------


def upsert_profile(conn: sqlite3.Connection, profile: IGProfile, default_source: str = "") -> tuple[bool, bool]:
    """Devuelve (added, updated). Idempotente."""
    user = normalize_username(profile.username)
    if not user:
        return False, False
    if _is_suppressed(conn, user):
        return False, False
    payload = asdict(profile)
    payload["username"] = user
    if not payload.get("source") and default_source:
        payload["source"] = default_source
    payload["now"] = now_iso()
    existing = conn.execute("SELECT username FROM ig_prospects WHERE username=?", (user,)).fetchone()
    if existing:
        conn.execute(
            """UPDATE ig_prospects SET
                 full_name=COALESCE(NULLIF(:full_name,''), full_name),
                 bio=COALESCE(NULLIF(:bio,''), bio),
                 business_category=COALESCE(NULLIF(:business_category,''), business_category),
                 niche=COALESCE(NULLIF(:niche,''), niche),
                 city=COALESCE(NULLIF(:city,''), city),
                 followers_count=COALESCE(NULLIF(:followers_count,0), followers_count),
                 following_count=COALESCE(NULLIF(:following_count,0), following_count),
                 posts_count=COALESCE(NULLIF(:posts_count,0), posts_count),
                 website=COALESCE(NULLIF(:website,''), website),
                 public_email=COALESCE(NULLIF(:public_email,''), public_email),
                 public_phone=COALESCE(NULLIF(:public_phone,''), public_phone),
                 profile_url=COALESCE(NULLIF(:profile_url,''), profile_url),
                 avatar_url=COALESCE(NULLIF(:avatar_url,''), avatar_url),
                 is_business_account=COALESCE(NULLIF(:is_business_account,0), is_business_account),
                 is_verified=COALESCE(NULLIF(:is_verified,0), is_verified),
                 tags=COALESCE(NULLIF(:tags,''), tags),
                 source=COALESCE(NULLIF(:source,''), source),
                 updated_at=:now
               WHERE username=:username""",
            payload,
        )
        return False, True
    conn.execute(
        """INSERT INTO ig_prospects
             (username, full_name, bio, business_category, niche, city,
              followers_count, following_count, posts_count, website,
              public_email, public_phone, profile_url, avatar_url,
              is_business_account, is_verified, tags, source,
              created_at, updated_at)
           VALUES
             (:username, :full_name, :bio, :business_category, :niche, :city,
              :followers_count, :following_count, :posts_count, :website,
              :public_email, :public_phone, :profile_url, :avatar_url,
              :is_business_account, :is_verified, :tags, :source,
              :now, :now)""",
        payload,
    )
    conn.execute(
        "INSERT INTO ig_events (username, type, ts) VALUES (?,?,?)",
        (user, "discovered", now_iso()),
    )
    return True, False


# -------------------- import csv --------------------


CSV_FIELDS = (
    "username", "full_name", "bio", "business_category", "niche", "city",
    "followers_count", "following_count", "posts_count", "website",
    "public_email", "public_phone", "profile_url", "avatar_url",
    "is_business_account", "is_verified", "tags", "source",
)


def cmd_import(args: argparse.Namespace) -> int:
    csv_path: Path = args.csv
    if not csv_path.exists():
        print(f"CSV no encontrado: {csv_path}")
        return 2
    added = updated = skipped = 0
    with closing(connect(args.db)) as conn, csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            print("CSV vacio o sin cabecera.")
            return 2
        for row in reader:
            user = normalize_username(row.get("username", ""))
            if not user:
                skipped += 1
                continue
            profile = IGProfile(
                username=user,
                full_name=(row.get("full_name") or "").strip(),
                bio=(row.get("bio") or "").strip(),
                business_category=(row.get("business_category") or "").strip(),
                niche=(row.get("niche") or "").strip(),
                city=(row.get("city") or "").strip(),
                followers_count=int(row.get("followers_count") or 0),
                following_count=int(row.get("following_count") or 0),
                posts_count=int(row.get("posts_count") or 0),
                website=(row.get("website") or "").strip(),
                public_email=(row.get("public_email") or "").strip(),
                public_phone=(row.get("public_phone") or "").strip(),
                profile_url=(row.get("profile_url") or "").strip(),
                avatar_url=(row.get("avatar_url") or "").strip(),
                is_business_account=int(row.get("is_business_account") or 0),
                is_verified=int(row.get("is_verified") or 0),
                tags=(row.get("tags") or "").strip(),
                source=(row.get("source") or csv_path.name).strip(),
            )
            a, u = upsert_profile(conn, profile)
            if a:
                added += 1
            elif u:
                updated += 1
            else:
                skipped += 1
        conn.commit()
    print(f"Import OK: {added} nuevos, {updated} actualizados, {skipped} descartados. DB: {args.db}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    users = []
    if args.usernames:
        users.extend([u.strip() for u in args.usernames.replace(";", ",").split(",") if u.strip()])
    if args.from_file:
        with open(args.from_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    users.append(line)
    if not users:
        print("Sin usernames (--usernames / --from-file).")
        return 2
    profiles = discover_usernames(
        users,
        niche=args.niche,
        city=args.city,
        source_label=args.source or "discover",
        use_graph=not args.no_graph,
        min_followers=args.min_followers,
        max_followers=args.max_followers,
        progress_cb=lambda u, s, info: print(f"[{s}] @{u} {info}"),
    )
    added = updated = 0
    with closing(connect(args.db)) as conn:
        for p in profiles:
            a, u = upsert_profile(conn, p)
            if a:
                added += 1
            elif u:
                updated += 1
        conn.commit()
    print(f"Discover OK: {len(profiles)} perfiles, {added} nuevos, {updated} actualizados.")
    return 0


# -------------------- draft / send --------------------


def fetch_candidates(
    conn: sqlite3.Connection,
    stage: str,
    max_count: int,
    after_days: int = 0,
) -> list[sqlite3.Row]:
    """Devuelve prospects elegibles para ese stage.

    cold: sin ningun intento previo y status not in (replied, client, lost, dnc).
    fuX:  ultimo send anterior con stage previo, >=after_days desde ese send,
          sin reply, sin send en este stage.
    """
    excluded_status = ("replied", "client", "lost", "dnc")
    excluded_users = conn.execute(
        "SELECT username FROM ig_prospects WHERE status IN (?,?,?,?)",
        excluded_status,
    ).fetchall()
    excluded_set = {r["username"] for r in excluded_users}

    replied = {r["username"] for r in conn.execute(
        "SELECT DISTINCT username FROM ig_events WHERE type='reply'"
    ).fetchall()}
    suppressed = {r["username"] for r in conn.execute(
        "SELECT username FROM ig_suppressions"
    ).fetchall()}

    if stage == "cold":
        rows = conn.execute(
            """SELECT p.* FROM ig_prospects p
               WHERE NOT EXISTS (
                 SELECT 1 FROM ig_sends s WHERE s.username=p.username
               )
               ORDER BY p.score DESC, p.created_at ASC"""
        ).fetchall()
    else:
        prev_stage = STAGE_ORDER[max(0, STAGE_ORDER.index(stage) - 1)]
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, after_days))).isoformat(timespec="seconds")
        rows = conn.execute(
            """SELECT p.* FROM ig_prospects p
               WHERE EXISTS (
                 SELECT 1 FROM ig_sends s WHERE s.username=p.username AND s.stage=? AND s.mode IN ('sent','sent_auto') AND s.sent_at<=?
               )
               AND NOT EXISTS (
                 SELECT 1 FROM ig_sends s WHERE s.username=p.username AND s.stage=?
               )
               ORDER BY p.score DESC, p.created_at ASC""",
            (prev_stage, cutoff, stage),
        ).fetchall()

    out: list[sqlite3.Row] = []
    for r in rows:
        if r["username"] in excluded_set:
            continue
        if r["username"] in replied:
            continue
        if r["username"] in suppressed:
            continue
        out.append(r)
        if len(out) >= max_count:
            break
    return out


def create_draft(conn: sqlite3.Connection, row: sqlite3.Row, stage: str) -> dict:
    p = _row_to_prospect(row)
    existing = conn.execute(
        "SELECT id FROM ig_sends WHERE username=? AND stage=? LIMIT 1",
        (p.username, stage),
    ).fetchone()
    if existing:
        raise ValueError(f"Ya existe un intento para @{p.username} en stage={stage}")
    message, variant = render(stage, p)
    conn.execute(
        """INSERT INTO ig_sends (username, stage, variant, message_text, mode, ready, drafted_at)
           VALUES (?,?,?,?,?,?,?)""",
        (p.username, stage, variant, message, "draft", 1, now_iso()),
    )
    send_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute(
        "INSERT INTO ig_events (username, type, stage, ts) VALUES (?,?,?,?)",
        (p.username, "draft", stage, now_iso()),
    )
    if stage == "cold":
        conn.execute(
            "UPDATE ig_prospects SET status=CASE WHEN status='new' THEN 'queued' ELSE status END, updated_at=? WHERE username=?",
            (now_iso(), p.username),
        )
    return {
        "id": int(send_id),
        "username": p.username,
        "stage": stage,
        "variant": variant,
        "message": message,
        "deep_link": igme_deep_link(p.username, message),
    }


def cmd_preview(args: argparse.Namespace) -> int:
    with closing(connect(args.db)) as conn:
        rows = fetch_candidates(conn, args.stage, args.limit, args.after_days)
        for r in rows:
            p = _row_to_prospect(r)
            message, variant = render(args.stage, p)
            print(f"\n--- @{p.username} | {args.stage} | variant={variant} ---")
            print(message)
            print(f"link: {igme_deep_link(p.username, message)}")
    return 0


def cmd_draft(args: argparse.Namespace) -> int:
    with closing(connect(args.db)) as conn:
        rows = fetch_candidates(conn, args.stage, args.max, args.after_days)
        created = 0
        for r in rows:
            create_draft(conn, r, args.stage)
            created += 1
        conn.commit()
    print(f"Drafts creados: {created} en stage={args.stage}")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    if not args.send and not args.test_to:
        return cmd_preview(args)
    if not is_autosend_enabled():
        print("IG_AUTOSEND_ENABLED=false. Se generan drafts pendientes de envio manual desde el panel.")
        return cmd_draft(args)
    try:
        from instagram_autosend import autosend_drafts  # type: ignore
    except ImportError:
        print("scripts/instagram_autosend.py no disponible. Instala playwright o desactiva IG_AUTOSEND_ENABLED.")
        return 3
    with closing(connect(args.db)) as conn:
        rows = fetch_candidates(conn, args.stage, args.max, args.after_days)
        drafts = [create_draft(conn, r, args.stage) for r in rows]
        conn.commit()
    sent = autosend_drafts(drafts, dry_run=not args.send)
    print(f"Autosend: {sent} drafts procesados.")
    return 0


def cmd_followup(args: argparse.Namespace) -> int:
    args.send = bool(args.send)
    return cmd_send(args)


def cmd_suppress(args: argparse.Namespace) -> int:
    if not args.username and not args.csv:
        print("Pasa --username @cuenta o --csv ruta.csv")
        return 2
    with closing(connect(args.db)) as conn:
        users = []
        if args.username:
            users.append(normalize_username(args.username))
        if args.csv:
            with open(args.csv, "r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    users.append(normalize_username(row.get("username", "")))
        added = 0
        for u in users:
            if not u:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO ig_suppressions (username, reason, added_at) VALUES (?,?,?)",
                (u, args.reason or "manual", now_iso()),
            )
            conn.execute(
                "UPDATE ig_prospects SET status='dnc', updated_at=? WHERE username=?",
                (now_iso(), u),
            )
            added += 1
        conn.commit()
    print(f"Supresion OK: {added} usuarios.")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with closing(connect(args.db)) as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM ig_prospects").fetchone()["c"]
        suppr = conn.execute("SELECT COUNT(*) AS c FROM ig_suppressions").fetchone()["c"]
        per_stage = conn.execute(
            "SELECT stage, COUNT(*) AS c FROM ig_sends WHERE mode IN ('sent','sent_auto') GROUP BY stage"
        ).fetchall()
        drafts_pending = conn.execute(
            "SELECT COUNT(*) AS c FROM ig_sends WHERE mode='draft' AND ready=1"
        ).fetchone()["c"]
        replies = conn.execute(
            "SELECT COUNT(DISTINCT username) AS c FROM ig_events WHERE type='reply'"
        ).fetchone()["c"]
        print(f"Prospects: {total} | suppressed: {suppr} | drafts pendientes: {drafts_pending} | replies: {replies}")
        for row in per_stage:
            print(f"  {row['stage']}: {row['c']} enviados")
    return 0


# -------------------- argparse --------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Captacion Instagram CLI")
    parser.add_argument("--db", type=Path, default=Path(os.getenv("IG_DB_PATH", str(DEFAULT_DB))))
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import")
    p_import.add_argument("--csv", type=Path, required=True)
    p_import.set_defaults(func=cmd_import)

    p_disc = sub.add_parser("discover")
    p_disc.add_argument("--usernames", default="")
    p_disc.add_argument("--from-file", default="")
    p_disc.add_argument("--niche", default="")
    p_disc.add_argument("--city", default="")
    p_disc.add_argument("--source", default="")
    p_disc.add_argument("--min-followers", type=int, default=0)
    p_disc.add_argument("--max-followers", type=int, default=0)
    p_disc.add_argument("--no-graph", action="store_true")
    p_disc.set_defaults(func=cmd_discover)

    p_prev = sub.add_parser("preview")
    p_prev.add_argument("--stage", default="cold")
    p_prev.add_argument("--limit", type=int, default=3)
    p_prev.add_argument("--after-days", type=int, default=4)
    p_prev.set_defaults(func=cmd_preview)

    p_dft = sub.add_parser("draft")
    p_dft.add_argument("--stage", default="cold")
    p_dft.add_argument("--max", type=int, default=20)
    p_dft.add_argument("--after-days", type=int, default=4)
    p_dft.set_defaults(func=cmd_draft)

    p_send = sub.add_parser("send")
    p_send.add_argument("--stage", default="cold")
    p_send.add_argument("--max", type=int, default=20)
    p_send.add_argument("--after-days", type=int, default=4)
    p_send.add_argument("--send", action="store_true")
    p_send.add_argument("--test-to", default="")
    p_send.set_defaults(func=cmd_send)

    p_fu = sub.add_parser("followup")
    p_fu.add_argument("--stage", default="fu1")
    p_fu.add_argument("--max", type=int, default=20)
    p_fu.add_argument("--after-days", type=int, default=5)
    p_fu.add_argument("--send", action="store_true")
    p_fu.add_argument("--test-to", default="")
    p_fu.set_defaults(func=cmd_followup)

    p_sup = sub.add_parser("suppress")
    p_sup.add_argument("--username", default="")
    p_sup.add_argument("--csv", default="")
    p_sup.add_argument("--reason", default="manual")
    p_sup.set_defaults(func=cmd_suppress)

    p_st = sub.add_parser("stats")
    p_st.set_defaults(func=cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(BASE_DIR / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
