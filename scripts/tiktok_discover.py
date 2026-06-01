"""TikTok discovery via Google Places + web scrape.

Espejo de instagram_discover_v2 para TikTok. Sin fetch publico de
tiktok.com/@user (bloqueado por TT). Confia en Places + handle valido + chain.
"""

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Set

import httpx


OUTREACH_AUTOPILOT_CHAIN_KEYWORDS = (
    "vivanta", "plus dental", "kivet", "sanitas", "vitaldent", "dentix",
    "donte group", "asisa", "dkv", "mapfre", "adeslas", "smile boutique",
    "ortodoncis", "caser", "santaluciaseguros",
)

SECTORS_B2B = [
    "clinica dental", "ortodoncia", "clinica estetica", "centro de estetica",
    "depilacion laser", "fisioterapia", "centro de psicologia", "logopeda",
    "podologo", "optica", "clinica veterinaria", "centro auditivo",
    "centro deportivo", "gimnasio", "estudio pilates", "centro yoga",
    "academia de ingles", "academia oposiciones", "autoescuela",
    "escuela infantil", "academia danza", "academia musica",
    "taller mecanico", "restaurante", "cafeteria", "barberia",
    "peluqueria", "centro de unas", "joyeria", "floristeria",
    "inmobiliaria", "asesoria fiscal", "asesoria laboral", "gestoria",
    "despacho abogados", "agencia marketing digital", "agencia de viajes",
    "empresa de reformas", "empresa de mudanzas", "empresa de limpieza",
    "fontaneria", "electricista", "cerrajeria", "carpinteria",
    "clinica nutricion", "clinica capilar",
]

CITIES_ES = [
    "Madrid", "Barcelona", "Valencia", "Sevilla", "Zaragoza", "Malaga",
    "Murcia", "Palma", "Las Palmas de Gran Canaria", "Bilbao", "Alicante",
    "Cordoba", "Valladolid", "Vigo", "Gijon", "A Coruna", "Granada",
    "Vitoria-Gasteiz", "Elche", "Oviedo", "Badalona", "Cartagena", "Terrassa",
    "Jerez de la Frontera", "Sabadell", "Mostoles", "Alcala de Henares",
    "Pamplona", "Fuenlabrada", "Almeria", "Leganes", "Donostia", "Burgos",
    "Santander", "Castellon de la Plana", "Albacete", "Getafe", "Logrono",
    "Badajoz", "Salamanca", "Huelva", "Lleida", "Tarragona", "Leon", "Cadiz",
    "Jaen", "Ourense", "Torrejon de Ardoz", "Alcorcon", "Reus", "Girona",
    "Marbella", "Toledo", "Caceres", "Pontevedra", "Mijas", "Estepona",
    "Benidorm", "Pozuelo de Alarcon", "Las Rozas", "Talavera de la Reina",
    "Cuenca", "Guadalajara",
]

TT_HANDLE_RE = re.compile(
    r"(?:tiktok\.com|vm\.tiktok\.com)/@([a-zA-Z0-9_.][a-zA-Z0-9_.]{1,23})/?",
    re.IGNORECASE,
)
RESERVED_TT_PATHS = {
    "discover", "explore", "foryou", "following", "music", "tag", "hashtag",
    "live", "trending", "video", "channel", "business", "about", "ads",
    "legal", "privacy", "support", "help", "tos", "feed", "login",
    "signup", "settings", "messages", "inbox", "creator", "creators",
    "embed", "share",
}
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class TKCandidate:
    username: str
    business_name: str = ""
    niche: str = ""
    city: str = ""
    website: str = ""
    bio_snippet: str = ""
    place_rating: float = 0.0
    source: str = "campaign_discover"

    def normalized_username(self) -> str:
        return self.username.lstrip("@").strip().lower()


def _is_chain(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in OUTREACH_AUTOPILOT_CHAIN_KEYWORDS)


def _is_valid_handle(handle: str) -> bool:
    h = handle.strip().lower()
    if not h or len(h) < 2 or len(h) > 24:
        return False
    if h in RESERVED_TT_PATHS:
        return False
    if not re.fullmatch(r"[a-z0-9_.]+", h):
        return False
    return True


def _places_search(sector: str, city: str, api_key: str, http: httpx.Client) -> List[dict]:
    """Google Places API (New) Text Search."""
    try:
        field_mask = ",".join([
            "places.id",
            "places.displayName",
            "places.websiteUri",
            "places.rating",
            "places.userRatingCount",
            "places.formattedAddress",
            "places.types",
        ])
        r = http.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": field_mask,
            },
            json={
                "textQuery": f"{sector} en {city}",
                "languageCode": "es",
                "regionCode": "ES",
                "pageSize": 20,
            },
            timeout=15.0,
        )
        if r.status_code != 200:
            import logging as _log
            _log.getLogger("tiktok_discover").warning(
                "Places (New) HTTP %s '%s en %s': %s",
                r.status_code, sector, city, r.text[:200],
            )
            return []
        data = r.json() or {}
        out: List[dict] = []
        for p in data.get("places", []):
            dn = p.get("displayName") or {}
            name = dn.get("text") if isinstance(dn, dict) else ""
            out.append({
                "place_id": p.get("id", ""),
                "name": name or "",
                "website": p.get("websiteUri", "") or "",
                "rating": float(p.get("rating") or 0.0),
                "user_ratings_total": int(p.get("userRatingCount") or 0),
                "formatted_address": p.get("formattedAddress", "") or "",
            })
        return out
    except Exception as exc:
        import logging as _log
        _log.getLogger("tiktok_discover").warning(
            "Places (New) exception '%s en %s': %s", sector, city, exc,
        )
        return []


def _extract_tt_handle_from_website(url: str, http: httpx.Client) -> Optional[str]:
    if not url:
        return None
    try:
        r = http.get(url, timeout=10.0, follow_redirects=True,
                     headers={"User-Agent": DEFAULT_UA})
        if r.status_code != 200:
            return None
        html = r.text[:300_000]
        for m in TT_HANDLE_RE.finditer(html):
            handle = m.group(1)
            if _is_valid_handle(handle):
                return handle.lower()
        return None
    except Exception:
        return None


def discover_real(
    target_count: int,
    suppressed: Optional[Set[str]] = None,
    known: Optional[Set[str]] = None,
    google_api_key: Optional[str] = None,
    rate_limit_sec: float = 1.0,
    log: Optional[callable] = None,
) -> List[TKCandidate]:
    """Descubre hasta target_count candidatos TikTok reales.

    Mismo flujo que instagram_discover_v2 pero busca handles tiktok.com/@.
    """
    suppressed = {s.lower() for s in (suppressed or set())}
    known = {k.lower() for k in (known or set())}
    api_key = google_api_key or os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        if log:
            log("discover_real: sin GOOGLE_PLACES_API_KEY, abortando")
        return []

    out: List[TKCandidate] = []
    seen_handles: Set[str] = set(known)
    rng = random.SystemRandom()
    sectors = list(SECTORS_B2B)
    cities = list(CITIES_ES)
    rng.shuffle(sectors)
    rng.shuffle(cities)
    combos = [(s, c) for s in sectors for c in cities]
    rng.shuffle(combos)

    http = httpx.Client(timeout=12.0)
    try:
        for sector, city in combos:
            if len(out) >= target_count:
                break
            if log:
                log(f"discover_real: sector={sector} city={city}")
            places = _places_search(sector, city, api_key, http)
            if not places:
                continue
            for place in places[:12]:
                if len(out) >= target_count:
                    break
                name = (place.get("name") or "").strip()
                rating = float(place.get("rating") or 0.0)
                if rating and rating < 3.5:
                    continue
                if _is_chain(name):
                    continue
                website = (place.get("website") or "").strip()
                if not website:
                    continue
                handle = _extract_tt_handle_from_website(website, http)
                if not handle or handle in seen_handles or handle in suppressed:
                    continue
                cand = TKCandidate(
                    username=handle,
                    business_name=name,
                    niche=sector,
                    city=city,
                    website=website,
                    bio_snippet="",
                    place_rating=rating,
                )
                out.append(cand)
                seen_handles.add(handle)
                if log:
                    log(f"discover_real: + @{handle} ({name}, {city}, rating {rating})")
                time.sleep(rate_limit_sec / 2)
    finally:
        http.close()
    return out
