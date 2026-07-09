"""Extrae usernames de Instagram desde webs de prospects email ya capturados.

Para cada prospect con website no vacio:
  1. Fetch HTML del homepage (timeout corto, follow_redirects).
  2. Busca hrefs hacia instagram.com/<user>.
  3. Filtra reservados (p, explore, accounts, reel, stories...).
  4. Si encuentra username, llama public_scrape() y upsert a ig_prospects.

Tags el prospect IG con niche/city del prospect email origen para que las
plantillas IG usen niche_hook correcto.

Uso:
    python scripts/instagram_extract_from_outreach.py --limit 50 --min-followers 100
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from instagram_discover import (  # type: ignore
    IGProfile,
    is_valid_username,
    normalize_username,
    public_scrape,
)
from instagram_campaign import (  # type: ignore
    DEFAULT_DB as IG_DEFAULT_DB,
    connect as ig_connect,
    upsert_profile,
)

OUTREACH_DB = Path(os.getenv("OUTREACH_DB_PATH") or (ROOT / "storage" / "outreach" / "outreach.db"))

RESERVED_USERNAMES = {
    "p", "explore", "accounts", "reel", "reels", "stories", "tv",
    "directory", "developer", "about", "legal", "privacy", "terms",
    "ads", "business", "creators", "press", "api", "fragment", "share",
    "instagram", "meta", "facebook", "help",
}

IG_HREF_RE = re.compile(
    r'href=["\']https?://(?:www\.)?instagram\.com/([A-Za-z0-9._]{1,30})/?',
    re.IGNORECASE,
)

USER_AGENT = "Mozilla/5.0 (compatible; VanteliaBot/1.0; +https://vantelia.es)"


def fetch_html(url: str, timeout: float = 8.0) -> str:
    if not httpx:
        return ""
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"},
        ) as client:
            r = client.get(url)
            if r.status_code != 200:
                return ""
            return r.text or ""
    except Exception:
        return ""


def extract_ig_usernames(html: str) -> set[str]:
    out: set[str] = set()
    for m in IG_HREF_RE.finditer(html or ""):
        u = normalize_username(m.group(1))
        if not u or u in RESERVED_USERNAMES:
            continue
        if not is_valid_username(u):
            continue
        out.add(u)
    return out


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        p = urlparse(raw)
        if not p.netloc:
            return ""
        return f"{p.scheme}://{p.netloc}/"
    except Exception:
        return ""


def iter_prospects(limit: int = 0) -> Iterable[dict]:
    if not OUTREACH_DB.exists():
        return []
    conn = sqlite3.connect(OUTREACH_DB)
    conn.row_factory = sqlite3.Row
    try:
        q = (
            "SELECT email, business_name, niche, city, website "
            "FROM prospects WHERE website IS NOT NULL AND website != '' "
            "ORDER BY created_at DESC"
        )
        if limit > 0:
            q += f" LIMIT {int(limit)}"
        rows = conn.execute(q).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extrae IG usernames desde webs de prospects email")
    ap.add_argument("--limit", type=int, default=0, help="Limite de prospects a procesar (0=todos)")
    ap.add_argument("--min-followers", type=int, default=0, help="Descarta perfiles bajo este umbral")
    ap.add_argument("--max-followers", type=int, default=0, help="Descarta perfiles sobre este umbral (cadenas)")
    ap.add_argument("--sleep", type=float, default=1.0, help="Segundos entre webs (rate limit propio)")
    ap.add_argument("--ig-sleep", type=float, default=2.0, help="Segundos entre scrapes IG")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not httpx:
        print("ERROR: httpx no instalado", file=sys.stderr)
        return 2

    prospects = list(iter_prospects(limit=args.limit))
    print(f"Prospects con web: {len(prospects)}")

    seen_users: set[str] = set()
    added = updated = skipped = failed = 0
    ig_db_path = Path(os.getenv("IG_DB_PATH") or str(IG_DEFAULT_DB))
    ig_conn = ig_connect(ig_db_path)

    try:
        for i, p in enumerate(prospects, 1):
            url = normalize_url(p.get("website") or "")
            if not url:
                continue
            print(f"[{i}/{len(prospects)}] {p['email']} -> {url}")
            html = fetch_html(url)
            if not html:
                failed += 1
                time.sleep(args.sleep)
                continue
            users = extract_ig_usernames(html)
            if not users:
                time.sleep(args.sleep)
                continue
            print(f"   IG usernames encontrados: {sorted(users)}")
            for u in sorted(users):
                if u in seen_users:
                    continue
                seen_users.add(u)
                profile: Optional[IGProfile] = public_scrape(u)
                if not profile:
                    # IG bloquea scrape publico, pero el username viene de la web
                    # corporativa del prospect email -> es valido. Importar minimo.
                    profile = IGProfile(
                        username=u,
                        full_name=p.get("business_name") or "",
                        bio="",
                        profile_url=f"https://www.instagram.com/{u}/",
                        source="outreach_extract_unverified",
                    )
                    print(f"   - @{u}: scrape bloqueado, importando minimo")
                if args.min_followers and profile.followers_count and profile.followers_count < args.min_followers:
                    print(f"   - @{u}: skip (followers {profile.followers_count} < {args.min_followers})")
                    skipped += 1
                    time.sleep(args.ig_sleep)
                    continue
                if args.max_followers and profile.followers_count and profile.followers_count > args.max_followers:
                    print(f"   - @{u}: skip (followers {profile.followers_count} > {args.max_followers})")
                    skipped += 1
                    time.sleep(args.ig_sleep)
                    continue
                profile.website = url
                profile.niche = p.get("niche") or ""
                profile.city = p.get("city") or ""
                profile.source = "outreach_extract"
                profile.tags = f"outreach_email:{p['email']}"
                if not args.dry_run:
                    a, u_flag = upsert_profile(ig_conn, profile, default_source="outreach_extract")
                    ig_conn.commit()
                    if a:
                        added += 1
                    elif u_flag:
                        updated += 1
                    label = "ADD" if a else "UPD" if u_flag else "SKIP"
                else:
                    label = "DRY"
                print(f"   - @{u}: {label} followers={profile.followers_count} bio='{(profile.bio or '')[:60]}'")
                time.sleep(args.ig_sleep)
            time.sleep(args.sleep)
    finally:
        ig_conn.close()

    print()
    print(f"=== Resumen ===")
    print(f"Webs procesadas:        {len(prospects)}")
    print(f"IG usernames unicos:    {len(seen_users)}")
    print(f"Anadidos:               {added}")
    print(f"Actualizados:           {updated}")
    print(f"Saltados (filtros):     {skipped}")
    print(f"Webs fallidas:          {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
