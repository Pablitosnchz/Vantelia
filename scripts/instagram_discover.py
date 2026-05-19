"""Discovery automatico de perfiles Instagram publicos.

Dos modos:
  1) Graph API (Business Discovery) si hay IG_GRAPH_TOKEN + IG_BUSINESS_ACCOUNT_ID.
     Requiere cuenta IG Business propia y un perfil semilla por username.
     Permite recuperar bio, followers, website y media de un perfil publico.
     Legal y oficial.

  2) Fallback: scrape publico read-only de www.instagram.com/{username}/.
     Sin login. Lee og:description y application/ld+json para extraer
     bio/follower_count basicos. Rate limit 1 req cada 2s. Respeta robots.

Inputs:
  - hashtag (cuando IG_GRAPH_TOKEN soporta hashtag search via Graph API)
  - lista explicita de usernames (manual / scraping previo)
  - lista de competidores (sus followers/following si publico)

Output:
  - lista de dicts compatibles con tabla ig_prospects.

CLI:
  python scripts/instagram_discover.py --usernames cuenta1,cuenta2 --output outreach/ig.csv
  python scripts/instagram_discover.py --hashtag dentistamadrid --max 30 --import-direct
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable, Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GRAPH_TOKEN = os.getenv("IG_GRAPH_TOKEN", "").strip()
GRAPH_BUSINESS_ID = os.getenv("IG_BUSINESS_ACCOUNT_ID", "").strip()
GRAPH_API_VERSION = os.getenv("IG_GRAPH_API_VERSION", "v22.0").strip() or "v22.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

PUBLIC_RATE_LIMIT_SEC = float(os.getenv("IG_PUBLIC_RATE_LIMIT_SEC", "2.0"))
PUBLIC_USER_AGENT = os.getenv(
    "IG_PUBLIC_USER_AGENT",
    "Mozilla/5.0 (compatible; VanteliaResearch/1.0; +https://www.vantelia.es)",
)

USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


@dataclass
class IGProfile:
    username: str
    full_name: str = ""
    bio: str = ""
    business_category: str = ""
    followers_count: int = 0
    following_count: int = 0
    posts_count: int = 0
    website: str = ""
    public_email: str = ""
    public_phone: str = ""
    profile_url: str = ""
    avatar_url: str = ""
    is_business_account: int = 0
    is_verified: int = 0
    source: str = ""
    niche: str = ""
    city: str = ""
    tags: str = ""


def normalize_username(value: str) -> str:
    return (value or "").strip().lstrip("@").lower()


def is_valid_username(value: str) -> bool:
    return bool(value and USERNAME_RE.match(value))


# ----------------------- Graph API mode -----------------------


def graph_business_discovery(username: str, timeout: float = 8.0) -> Optional[dict]:
    """Lookup perfil publico via Business Discovery endpoint.

    Requiere IG_GRAPH_TOKEN con permisos instagram_basic + instagram_manage_insights
    y un IG_BUSINESS_ACCOUNT_ID (cuenta business propia).
    """
    if not (GRAPH_TOKEN and GRAPH_BUSINESS_ID and httpx):
        return None
    fields = (
        "business_discovery.username({user}){{"
        "username,name,biography,followers_count,follows_count,"
        "media_count,profile_picture_url,website"
        "}}"
    ).format(user=username)
    url = f"{GRAPH_BASE}/{GRAPH_BUSINESS_ID}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, params={"fields": fields, "access_token": GRAPH_TOKEN})
            if resp.status_code != 200:
                return None
            data = resp.json().get("business_discovery") or {}
            if not data:
                return None
            return data
    except Exception:
        return None


def graph_to_profile(raw: dict, source: str = "graph", niche: str = "", city: str = "") -> IGProfile:
    return IGProfile(
        username=normalize_username(raw.get("username", "")),
        full_name=(raw.get("name") or "").strip(),
        bio=(raw.get("biography") or "").strip(),
        followers_count=int(raw.get("followers_count") or 0),
        following_count=int(raw.get("follows_count") or 0),
        posts_count=int(raw.get("media_count") or 0),
        website=(raw.get("website") or "").strip(),
        avatar_url=(raw.get("profile_picture_url") or "").strip(),
        profile_url=f"https://www.instagram.com/{normalize_username(raw.get('username', ''))}/",
        is_business_account=1,
        source=source,
        niche=niche,
        city=city,
    )


# ----------------------- Public scrape fallback -----------------------

_OG_TITLE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE)
_OG_DESC = re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE)
_OG_IMAGE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE)
_FOLLOWER_LINE = re.compile(r"([\d.,]+[KMkm]?)\s+Followers", re.IGNORECASE)
_FOLLOWING_LINE = re.compile(r"([\d.,]+[KMkm]?)\s+Following", re.IGNORECASE)
_POSTS_LINE = re.compile(r"([\d.,]+[KMkm]?)\s+Posts", re.IGNORECASE)
_PUBLIC_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def _parse_count(raw: str) -> int:
    if not raw:
        return 0
    s = raw.strip().upper().replace(",", "").replace(".", "")
    mult = 1
    if s.endswith("K"):
        mult = 1000
        s = s[:-1]
    elif s.endswith("M"):
        mult = 1_000_000
        s = s[:-1]
    try:
        n = float(s)
    except ValueError:
        return 0
    return int(n * mult)


def public_scrape(username: str, timeout: float = 8.0) -> Optional[IGProfile]:
    """Scrape minimo read-only de pagina publica. Sin login, sin cookies persistentes.

    Devuelve None si IG bloquea (challenge, login wall) o no hay httpx.
    """
    if not httpx:
        return None
    user = normalize_username(username)
    if not is_valid_username(user):
        return None
    url = f"https://www.instagram.com/{user}/"
    headers = {
        "User-Agent": PUBLIC_USER_AGENT,
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text or ""
    except Exception:
        return None

    if "login" in resp.url.path.lower() or "Login" in html[:2000]:
        # IG redirige a login -> sin datos utiles.
        return None

    title_m = _OG_TITLE.search(html)
    desc_m = _OG_DESC.search(html)
    img_m = _OG_IMAGE.search(html)
    desc = desc_m.group(1).strip() if desc_m else ""

    followers = following = posts = 0
    if desc:
        f_m = _FOLLOWER_LINE.search(desc)
        g_m = _FOLLOWING_LINE.search(desc)
        p_m = _POSTS_LINE.search(desc)
        if f_m:
            followers = _parse_count(f_m.group(1))
        if g_m:
            following = _parse_count(g_m.group(1))
        if p_m:
            posts = _parse_count(p_m.group(1))

    # full_name suele estar en og:title como "Full Name (@user) ...".
    full_name = ""
    if title_m:
        t = title_m.group(1)
        if "(@" in t:
            full_name = t.split("(@", 1)[0].strip()

    # bio: lo que viene tras los counters dentro de og:description.
    bio = ""
    if desc and " - " in desc:
        parts = desc.split(" - ", 2)
        if len(parts) >= 2:
            bio = parts[-1].strip()

    email_m = _PUBLIC_EMAIL_RE.search(bio) if bio else None
    phone_m = _PHONE_RE.search(bio) if bio else None

    return IGProfile(
        username=user,
        full_name=full_name,
        bio=bio,
        followers_count=followers,
        following_count=following,
        posts_count=posts,
        website="",
        public_email=email_m.group(0) if email_m else "",
        public_phone=phone_m.group(0) if phone_m else "",
        avatar_url=(img_m.group(1).strip() if img_m else ""),
        profile_url=url,
        is_business_account=0,
        source="public",
    )


# ----------------------- High-level discover -----------------------


def discover_usernames(
    usernames: Iterable[str],
    niche: str = "",
    city: str = "",
    source_label: str = "manual",
    use_graph: bool = True,
    min_followers: int = 0,
    max_followers: int = 0,
    has_website: bool = False,
    is_business: bool = False,
    progress_cb=None,
) -> list[IGProfile]:
    """Itera lista de usernames y devuelve perfiles enriquecidos.

    use_graph=True prueba Graph API primero (si configurado) y cae a scrape publico.
    """
    out: list[IGProfile] = []
    seen: set[str] = set()
    for raw in usernames:
        user = normalize_username(raw)
        if not is_valid_username(user) or user in seen:
            continue
        seen.add(user)
        profile: Optional[IGProfile] = None
        if use_graph:
            raw_g = graph_business_discovery(user)
            if raw_g:
                profile = graph_to_profile(raw_g, source=source_label or "graph", niche=niche, city=city)
        if profile is None:
            profile = public_scrape(user)
            time.sleep(PUBLIC_RATE_LIMIT_SEC)
        if profile is None:
            if progress_cb:
                progress_cb(user, "skip", "no data")
            continue
        if niche:
            profile.niche = niche
        if city:
            profile.city = city
        if not profile.source:
            profile.source = source_label
        if min_followers and profile.followers_count < min_followers:
            if progress_cb:
                progress_cb(user, "skip", f"<{min_followers} followers")
            continue
        if max_followers and profile.followers_count > max_followers:
            if progress_cb:
                progress_cb(user, "skip", f">{max_followers} followers")
            continue
        if has_website and not profile.website:
            if progress_cb:
                progress_cb(user, "skip", "sin website")
            continue
        if is_business and not profile.is_business_account:
            if progress_cb:
                progress_cb(user, "skip", "no business")
            continue
        out.append(profile)
        if progress_cb:
            progress_cb(user, "ok", f"{profile.followers_count} followers")
    return out


def write_csv(profiles: list[IGProfile], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(IGProfile(username="x")).keys())
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for p in profiles:
            writer.writerow(asdict(p))


# ----------------------- CLI -----------------------


def _parse_usernames(value: str) -> list[str]:
    if not value:
        return []
    if value.startswith("@"):
        value = value[1:]
    return [v.strip() for v in re.split(r"[,;\n]+", value) if v.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discovery Instagram (Graph + scrape publico)")
    parser.add_argument("--usernames", default="", help="Lista usernames separados por coma")
    parser.add_argument("--from-file", default="", help="Archivo txt con un username por linea")
    parser.add_argument("--niche", default="")
    parser.add_argument("--city", default="")
    parser.add_argument("--source", default="manual")
    parser.add_argument("--min-followers", type=int, default=0)
    parser.add_argument("--max-followers", type=int, default=0)
    parser.add_argument("--has-website", action="store_true")
    parser.add_argument("--is-business", action="store_true")
    parser.add_argument("--no-graph", action="store_true", help="Saltar Graph API, solo scrape publico")
    parser.add_argument("--output", default="", help="CSV de salida")
    args = parser.parse_args(argv)

    users: list[str] = []
    if args.usernames:
        users.extend(_parse_usernames(args.usernames))
    if args.from_file:
        with open(args.from_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    users.append(line)
    if not users:
        print("No se proporcionaron usernames (--usernames o --from-file).", file=sys.stderr)
        return 2

    def _log(user: str, status: str, info: str) -> None:
        print(f"[{status}] @{user} {info}")

    profiles = discover_usernames(
        users,
        niche=args.niche,
        city=args.city,
        source_label=args.source,
        use_graph=not args.no_graph,
        min_followers=args.min_followers,
        max_followers=args.max_followers,
        has_website=args.has_website,
        is_business=args.is_business,
        progress_cb=_log,
    )
    print(f"Encontrados {len(profiles)} perfiles validos.")
    if args.output:
        write_csv(profiles, Path(args.output))
        print(f"CSV escrito: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
