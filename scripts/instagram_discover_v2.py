"""Instagram discovery v2 — real y veraz.

Flujo:
1. Itera sector + ciudad random (toda Espana, ~60 sectores B2B, ~80 ciudades).
2. Google Places nearby search → name, website, rating.
3. Scrape website (httpx, sin browser) buscando link/handle a Instagram.
4. Filtros: chain conocida, ya suprimido, sin handle.
5. Fetch instagram.com/{handle}/ publico (sin login) y extrae bio + meta.
6. Devuelve candidatos validos hasta llenar target.

Diseñado para llamarse desde campaign worker en api.py.
"""

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Set

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

IG_HANDLE_RE = re.compile(
    r"(?:instagram\.com|instagr\.am)/(?:p/|reel/|tv/)?@?([a-zA-Z0-9_.][a-zA-Z0-9_.]{0,29})/?",
    re.IGNORECASE,
)
RESERVED_IG_PATHS = {
    "p", "reel", "reels", "tv", "explore", "stories", "about", "directory",
    "developer", "legal", "accounts", "help", "press", "api", "session",
    "challenge", "ads", "web", "channel", "direct", "settings", "blog",
}
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class IGCandidate:
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
    if not h or len(h) < 3 or len(h) > 30:
        return False
    if h in RESERVED_IG_PATHS:
        return False
    if not re.fullmatch(r"[a-z0-9_.]+", h):
        return False
    return True


def _places_search(sector: str, city: str, api_key: str, http: httpx.Client) -> List[dict]:
    """Google Places API (New) Text Search. Devuelve negocios con website + rating ya incluidos."""
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
            try:
                err_txt = r.text[:200]
            except Exception:
                err_txt = ""
            import logging as _log
            _log.getLogger("instagram_discover_v2").warning(
                "Places (New) HTTP %s para '%s en %s': %s",
                r.status_code, sector, city, err_txt,
            )
            return []
        data = r.json() or {}
        results: List[dict] = []
        for p in data.get("places", []):
            dn = p.get("displayName") or {}
            name = dn.get("text") if isinstance(dn, dict) else ""
            results.append({
                "place_id": p.get("id", ""),
                "name": name or "",
                "website": p.get("websiteUri", "") or "",
                "rating": float(p.get("rating") or 0.0),
                "user_ratings_total": int(p.get("userRatingCount") or 0),
                "formatted_address": p.get("formattedAddress", "") or "",
            })
        return results
    except Exception as exc:
        import logging as _log
        _log.getLogger("instagram_discover_v2").warning(
            "Places (New) exception para '%s en %s': %s", sector, city, exc,
        )
        return []


def _place_details(place: dict, api_key: str, http: httpx.Client) -> Optional[dict]:
    """Con Places API (New), website ya viene en la respuesta de search.
    Esta funcion queda como passthrough para mantener compat con el flujo."""
    if not place:
        return None
    return {
        "name": place.get("name", ""),
        "website": place.get("website", ""),
        "rating": place.get("rating", 0),
    }


def _extract_ig_handle_from_website(url: str, http: httpx.Client) -> Optional[str]:
    if not url:
        return None
    try:
        r = http.get(url, timeout=10.0, follow_redirects=True,
                     headers={"User-Agent": DEFAULT_UA})
        if r.status_code != 200:
            return None
        html = r.text[:300_000]  # cap a 300KB
        for m in IG_HANDLE_RE.finditer(html):
            handle = m.group(1)
            if _is_valid_handle(handle):
                return handle.lower()
        return None
    except Exception:
        return None


def _fetch_ig_profile_meta(username: str, http: httpx.Client) -> dict:
    """Fetch publico instagram.com/{username}/ y parsea meta og:description.
    Sin login. Devuelve {ok, bio, is_business_hint}."""
    try:
        r = http.get(
            f"https://www.instagram.com/{username}/",
            timeout=12.0,
            follow_redirects=True,
            headers={
                "User-Agent": DEFAULT_UA,
                "Accept-Language": "es-ES,es;q=0.9",
            },
        )
        if r.status_code != 200:
            return {"ok": False}
        html = r.text
        # og:description suele tener "1,234 Followers, 567 Following, ... - @user en Instagram: \"bio\""
        m_desc = re.search(r'<meta property="og:description" content="([^"]+)"', html)
        m_title = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        bio = (m_desc.group(1) if m_desc else "").strip()
        title = (m_title.group(1) if m_title else "").strip()
        if not bio and not title:
            return {"ok": False}
        # Heuristica is_business: titulo con barra vertical o paréntesis sugiere brand
        is_business = bool(re.search(r"[|()·–-]", title)) or len(bio) > 60
        # Followers heuristic
        followers = 0
        fm = re.search(r"([\d.,]+)\s*Followers", bio, re.IGNORECASE)
        if fm:
            try:
                followers = int(fm.group(1).replace(",", "").replace(".", ""))
            except Exception:
                followers = 0
        return {"ok": True, "bio": bio[:280], "title": title[:180],
                "is_business_hint": is_business, "followers": followers}
    except Exception:
        return {"ok": False}


def discover_real(
    target_count: int,
    suppressed: Optional[Set[str]] = None,
    known: Optional[Set[str]] = None,
    min_followers: int = 0,
    google_api_key: Optional[str] = None,
    rate_limit_sec: float = 1.5,
    on_progress: Optional[callable] = None,
    log: Optional[callable] = None,
) -> List[IGCandidate]:
    """Descubre hasta target_count candidatos IG reales.

    Args:
        target_count: cuantos candidatos validos hace falta.
        suppressed: set de usernames a evitar (bajas).
        known: set de usernames ya en BBDD (evitar dup).
        min_followers: filtro followers minimo (0 = desactivado, lectura publica no fiable).
        google_api_key: Google Places key.
        rate_limit_sec: pausa entre fetches IG publicos.
        on_progress: callback(stage:str, count:int) opcional.
        log: callback(msg:str) opcional para logging.
    """
    suppressed = {s.lower() for s in (suppressed or set())}
    known = {k.lower() for k in (known or set())}
    api_key = google_api_key or os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        if log:
            log("discover_real: sin GOOGLE_PLACES_API_KEY, abortando")
        return []

    out: List[IGCandidate] = []
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
                # Places API (New) ya devuelve website en search → no hace falta details.
                website = (place.get("website") or "").strip()
                if not website:
                    continue
                handle = _extract_ig_handle_from_website(website, http)
                if not handle or handle in seen_handles or handle in suppressed:
                    continue
                time.sleep(rate_limit_sec)
                meta = _fetch_ig_profile_meta(handle, http)
                if not meta.get("ok"):
                    continue
                if min_followers > 0 and meta.get("followers", 0) < min_followers:
                    continue
                cand = IGCandidate(
                    username=handle,
                    business_name=name,
                    niche=sector,
                    city=city,
                    website=website,
                    bio_snippet=meta.get("bio", "")[:240],
                    place_rating=rating,
                )
                out.append(cand)
                seen_handles.add(handle)
                if on_progress:
                    try:
                        on_progress("discovered", len(out))
                    except Exception:
                        pass
                if log:
                    log(f"discover_real: + @{handle} ({name}, {city}, rating {rating})")
                time.sleep(rate_limit_sec / 2)
    finally:
        http.close()
    return out
