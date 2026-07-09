"""Discovery automatico de empresas via Google Places (+ extraccion de emails publicos).

Uso CLI:
    python scripts/outreach_discover.py --sector "clinica dental" --ciudad "Torrejon de Ardoz" --max 50 --output outreach/dental_torrejon.csv
    python scripts/outreach_discover.py --sector "academia ingles" --ciudad "Torrejon" --import-direct

Tambien expone discover_companies() para uso desde api.py.

IMPORTANTE: solo se extraen emails que aparecen publicamente en webs corporativas
(footers, paginas de contacto y mailto:). No se realiza scraping agresivo. Respeta
politicas robots.txt cuando es razonable y aplica un rate limit conservador.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
import unicodedata
import urllib.robotparser as robotparser
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()

OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter").strip()
NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search").strip()

# Mapping sector hispano -> tags OSM (lista de pares clave/valor; multiples = OR).
SECTOR_TO_OSM: dict[str, list[tuple[str, str]]] = {
    "clinica dental": [("amenity", "dentist")],
    "dentista": [("amenity", "dentist")],
    "fisioterapia": [("healthcare", "physiotherapist"), ("amenity", "physiotherapist")],
    "fisioterapeuta": [("healthcare", "physiotherapist")],
    "clinica privada": [("amenity", "clinic"), ("amenity", "doctors")],
    "clinica": [("amenity", "clinic")],
    "medico": [("amenity", "doctors")],
    "doctor": [("amenity", "doctors")],
    "veterinaria": [("amenity", "veterinary")],
    "veterinario": [("amenity", "veterinary")],
    "farmacia": [("amenity", "pharmacy")],
    "optica": [("shop", "optician")],
    "peluqueria": [("shop", "hairdresser")],
    "peluqueria y estetica": [("shop", "hairdresser"), ("shop", "beauty")],
    "estetica": [("shop", "beauty")],
    "centro estetica": [("shop", "beauty")],
    "centro de estetica": [("shop", "beauty")],
    "salon belleza": [("shop", "beauty")],
    "barberia": [("shop", "hairdresser")],
    "spa": [("leisure", "spa")],
    "gimnasio": [("leisure", "fitness_centre")],
    "academia": [("amenity", "language_school"), ("office", "educational_institution")],
    "academia ingles": [("amenity", "language_school")],
    "autoescuela": [("amenity", "driving_school")],
    "abogados": [("office", "lawyer")],
    "abogado": [("office", "lawyer")],
    "asesoria": [("office", "accountant"), ("office", "tax_advisor")],
    "asesoria fiscal": [("office", "tax_advisor"), ("office", "accountant")],
    "gestoria": [("office", "tax_advisor"), ("office", "accountant")],
    "inmobiliaria": [("office", "estate_agent")],
    "arquitecto": [("office", "architect")],
    "ingenieria": [("office", "engineer")],
    "restaurante": [("amenity", "restaurant")],
    "bar": [("amenity", "bar"), ("amenity", "pub")],
    "hotel": [("tourism", "hotel")],
    "alojamiento": [("tourism", "hotel"), ("tourism", "guest_house")],
    "cafeteria": [("amenity", "cafe")],
    "panaderia": [("shop", "bakery")],
    "carniceria": [("shop", "butcher")],
    "taller": [("shop", "car_repair")],
    "taller mecanico": [("shop", "car_repair")],
    "concesionario": [("shop", "car")],
    "fontaneria": [("craft", "plumber")],
    "fontanero": [("craft", "plumber")],
    "electricidad": [("craft", "electrician")],
    "electricista": [("craft", "electrician")],
    "reformas": [("craft", "builder"), ("craft", "carpenter")],
    "carpinteria": [("craft", "carpenter")],
    "cerrajeria": [("craft", "locksmith")],
    "tienda": [("shop", "yes")],
    "supermercado": [("shop", "supermarket")],
    "floristeria": [("shop", "florist")],
    "joyeria": [("shop", "jewelry")],
    "libreria": [("shop", "books")],
    "limpieza": [("office", "company"), ("craft", "cleaning")],
    "guarderia": [("amenity", "kindergarten")],
    "psicologo": [("healthcare", "psychotherapist"), ("office", "therapist")],
    "psicologia": [("healthcare", "psychotherapist")],
    "nutricionista": [("healthcare", "dietitian")],
    "podologo": [("healthcare", "podiatrist")],
}

EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)
COMMON_CONTACT_PATHS = [
    p.strip() for p in os.getenv("DISCOVERY_CONTACT_PATHS", "/,/contacto,/contact,/aviso-legal").split(",")
    if p.strip()
]
GENERIC_LOCAL_PARTS = {"noreply", "no-reply", "postmaster", "webmaster", "abuse", "ejemplo", "example"}
SCRAPE_TIMEOUT = float(os.getenv("DISCOVERY_SCRAPE_TIMEOUT", "5.0"))
ROBOTS_TIMEOUT = float(os.getenv("DISCOVERY_ROBOTS_TIMEOUT", "3.0"))
SCRAPE_HEADERS = {
    "User-Agent": "VanteliaOutreachBot/1.0 (+https://www.vantelia.es; contacto@vantelia.es)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-ES,es;q=0.9",
}


LARGE_CITY_AREAS: dict[str, list[str]] = {
    "madrid": [
        "Salamanca", "Chamberi", "Retiro", "Chamartin", "Tetuan", "Moncloa",
        "Arganzuela", "Centro", "Hortaleza", "Usera", "Carabanchel", "Vallecas",
        "Moratalaz", "Fuencarral", "Ciudad Lineal", "Latina",
    ],
    "barcelona": [
        "Eixample", "Gracia", "Sarria", "Les Corts", "Sant Marti", "Sants",
        "Horta", "Sant Andreu", "Ciutat Vella", "Poblenou",
    ],
    "valencia": [
        "Ruzafa", "Ensanche", "Campanar", "Benimaclet", "Patraix", "Camins al Grau",
        "Quatre Carreres", "Algirós",
    ],
}

SECTOR_QUERY_ALIASES: dict[str, list[str]] = {
    "estetica": ["centro estetica", "centro de estetica", "clinica estetica", "salon belleza"],
    "centro estetica": ["centro estetica", "centro de estetica", "clinica estetica", "salon belleza"],
    "centro de estetica": ["centro estetica", "centro de estetica", "clinica estetica", "salon belleza"],
    "peluqueria y estetica": ["peluqueria y estetica", "centro estetica", "salon belleza"],
    "clinica dental": ["clinica dental", "dentista"],
    "academia ingles": ["academia ingles", "academia de ingles", "escuela de idiomas"],
}


@dataclass
class DiscoveredCompany:
    business_name: str
    email: str = ""
    contact_name: str = ""
    niche: str = ""
    website: str = ""
    service_hint: str = ""
    city: str = ""
    phone: str = ""
    tags: str = ""
    source: str = "discovery:places"
    place_id: str = ""
    address: str = ""

    def as_csv_row(self) -> dict[str, str]:
        return {
            "business_name": self.business_name,
            "email": self.email,
            "contact_name": self.contact_name,
            "niche": self.niche,
            "website": self.website,
            "service_hint": self.service_hint,
            "city": self.city,
            "phone": self.phone,
            "tags": self.tags,
            "source": self.source,
        }


def _ensure_httpx() -> None:
    if httpx is None:
        raise RuntimeError("httpx no esta instalado. Anade httpx a requirements.txt.")


def _robots_allows(url: str) -> bool:
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        # Fetch con timeout estricto vía httpx (urllib robotparser no acepta timeout).
        _ensure_httpx()
        try:
            with httpx.Client(timeout=4.0, follow_redirects=True) as c:
                resp = c.get(robots_url, headers=SCRAPE_HEADERS, timeout=ROBOTS_TIMEOUT)
        except Exception:
            return True  # robots.txt no accesible: permitir con cautela
        if resp.status_code >= 400 or not resp.text:
            return True
        rp = robotparser.RobotFileParser()
        rp.parse(resp.text.splitlines())
        return rp.can_fetch(SCRAPE_HEADERS["User-Agent"], url)
    except Exception:
        return True


def _normalize_email(email: str) -> str:
    from urllib.parse import unquote
    return unquote(email).strip().lower()


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value).lower()
    return re.sub(r"\s+", " ", value).strip()


def _sector_query_aliases(sector: str) -> list[str]:
    normalized = _normalize_text(sector)
    aliases = SECTOR_QUERY_ALIASES.get(normalized, [])
    out = [sector.strip()]
    out.extend(aliases)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in out:
        key = _normalize_text(item)
        if item and key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _city_areas(ciudad: str, max_areas: int = 10) -> list[str]:
    normalized = _normalize_text(ciudad)
    for key, areas in LARGE_CITY_AREAS.items():
        if key == normalized or key in normalized:
            return areas[:max_areas]
    return []


def _places_queries(sector: str, ciudad: str, max_results: int) -> list[str]:
    """Genera consultas Places con profundidad extra para ciudades grandes.

    Places Text Search tiende a devolver siempre el mismo top local. Para rondas
    repetidas en ciudades grandes, expandimos por barrios/zonas y por alias del
    sector, manteniendo el numero de queries acotado para no disparar coste.
    """
    aliases = _sector_query_aliases(sector)
    city = ciudad.strip()
    queries: list[str] = []
    for alias in aliases[:3]:
        queries.append(f"{alias} en {city}".strip())

    areas = _city_areas(city, max_areas=12 if max_results >= 80 else 8)
    if areas:
        primary_aliases = aliases[:2]
        for area in areas:
            for alias in primary_aliases:
                queries.append(f"{alias} en {area}, {city}".strip())

    deduped: list[str] = []
    seen: set[str] = set()
    # Con 20 resultados por pagina y hasta 3 paginas por query no hace falta
    # lanzar decenas de queries para max bajos; aun asi damos margen para dedupe.
    query_cap = 1 if max_results <= 20 and not areas else min(len(queries), max(4, min(14, (max_results // 12) + 4)))
    for query in queries:
        key = _normalize_text(query)
        if key and key not in seen:
            seen.add(key)
            deduped.append(query)
        if len(deduped) >= query_cap:
            break
    return deduped


def _normalize_domain(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.netloc or parsed.path.split("/", 1)[0]).lower()
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host.strip(".")


def _normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if digits.startswith("34") and len(digits) > 9:
        digits = digits[2:]
    return digits[-9:] if len(digits) >= 9 else digits


STREET_PREFIX_RE = re.compile(
    r"^\s*(c\.|calle|av\.|avenida|paseo|ps\.|plaza|pl\.|ronda|camino|carretera|ctra\.|traves[ií]a|via|v[ií]a)\b",
    re.IGNORECASE,
)


def _city_from_formatted_address(address: str, fallback: str) -> str:
    """Extrae localidad de una direccion de Places sin confundirla con la calle."""
    fallback = (fallback or "").strip()
    if not address:
        return fallback

    parts = [p.strip() for p in address.split(",") if p.strip()]
    for part in parts:
        match = re.search(r"\b\d{5}\s+(.+)$", part)
        if match:
            city = match.group(1).strip()
            if city and not STREET_PREFIX_RE.match(city):
                return city

    for part in reversed(parts):
        plain = _normalize_text(part)
        if not plain or plain in {"espana", "spain"}:
            continue
        if re.fullmatch(r"\d{5}", plain):
            continue
        if STREET_PREFIX_RE.match(part):
            continue
        if fallback and _normalize_text(fallback) in plain:
            return fallback
    return fallback


def _source_tokens(value: str) -> set[str]:
    raw = (value or "").replace("discovery:", "").replace("fallback", "")
    return {t.strip().lower() for t in re.split(r"[,;+| ]+", raw) if t.strip()}


def _source_label(tokens: set[str]) -> str:
    tokens = {t for t in tokens if t and t != "discovery"}
    if "places" in tokens and "osm" in tokens:
        return "discovery:mixed"
    if "places" in tokens:
        return "discovery:places"
    if "osm" in tokens:
        return "discovery:osm"
    return "discovery:mixed" if len(tokens) > 1 else f"discovery:{next(iter(tokens), 'unknown')}"


def _company_score(company: DiscoveredCompany) -> int:
    return sum([
        10 if company.email else 0,
        8 if company.website else 0,
        5 if company.phone else 0,
        4 if company.address else 0,
        3 if company.niche else 0,
        2 if company.place_id else 0,
    ])


def _merge_company(base: DiscoveredCompany, incoming: DiscoveredCompany) -> DiscoveredCompany:
    """Fusiona datos priorizando el registro mas completo sin perder origen."""
    if _company_score(incoming) > _company_score(base):
        base, incoming = incoming, base
    for field in ("email", "website", "phone", "niche", "service_hint", "city", "place_id", "address"):
        if not getattr(base, field) and getattr(incoming, field):
            setattr(base, field, getattr(incoming, field))
    if len(incoming.business_name or "") > len(base.business_name or ""):
        base.business_name = incoming.business_name
    tags = {t.strip() for t in (base.tags + "," + incoming.tags).split(",") if t.strip()}
    base.tags = ",".join(sorted(tags))
    base.source = _source_label(_source_tokens(base.source) | _source_tokens(incoming.source))
    return base


def _dedupe_companies(companies: Iterable[DiscoveredCompany]) -> list[DiscoveredCompany]:
    """Deduplica por email, dominio, telefono y nombre+ciudad."""
    groups: dict[str, DiscoveredCompany] = {}
    aliases: dict[str, str] = {}

    def keys_for(company: DiscoveredCompany) -> list[str]:
        keys: list[str] = []
        email = _normalize_email(company.email)
        domain = _normalize_domain(company.website)
        phone = _normalize_phone(company.phone)
        name_city = "|".join([_normalize_text(company.business_name), _normalize_text(company.city)])
        if email:
            keys.append(f"email:{email}")
        if domain:
            keys.append(f"domain:{domain}")
        if phone:
            keys.append(f"phone:{phone}")
        if name_city.strip("|"):
            keys.append(f"namecity:{name_city}")
        return keys

    for company in companies:
        if not company.business_name.strip():
            continue
        keys = keys_for(company)
        canonical = next((aliases[k] for k in keys if k in aliases), keys[0] if keys else f"name:{_normalize_text(company.business_name)}")
        current = groups.get(canonical)
        if current:
            groups[canonical] = _merge_company(current, company)
        else:
            groups[canonical] = company
        for key in keys_for(groups[canonical]):
            aliases[key] = canonical

    return sorted(groups.values(), key=lambda c: (_company_score(c), c.business_name.lower()), reverse=True)


def _is_useful_email(email: str, business_domain: str) -> bool:
    email = _normalize_email(email)
    if not email or "@" not in email:
        return False
    local, domain = email.split("@", 1)
    if local in GENERIC_LOCAL_PARTS:
        return False
    if domain in {"sentry.io", "wixpress.com", "godaddy.com", "wordpress.com"}:
        return False
    # Preferir email del mismo dominio que la web
    if business_domain and not domain.endswith(business_domain):
        return False
    return True


def _scrape_emails_from_url(url: str, business_domain: str, client: "httpx.Client") -> list[str]:
    try:
        if not _robots_allows(url):
            return []
        resp = client.get(url, timeout=SCRAPE_TIMEOUT, follow_redirects=True)
        if resp.status_code >= 400 or "text/html" not in resp.headers.get("content-type", ""):
            return []
        text = resp.text
        candidates = set(EMAIL_REGEX.findall(text))
        # mailto: links son la mejor pista
        for match in re.finditer(r'mailto:([^"\'\s>]+)', text, flags=re.IGNORECASE):
            candidates.add(match.group(1).split("?", 1)[0])
        good = [e for e in (_normalize_email(c) for c in candidates) if _is_useful_email(e, business_domain)]
        return sorted(set(good))
    except Exception:
        return []


def extract_emails_from_website(website: str) -> list[str]:
    """Devuelve hasta 3 emails publicos detectados en la web."""
    if not website:
        return []
    _ensure_httpx()
    try:
        parsed = urlparse(website if "://" in website else f"https://{website}")
    except Exception:
        return []
    if not parsed.netloc:
        return []
    base = f"{parsed.scheme}://{parsed.netloc}"
    business_domain = parsed.netloc.lower().replace("www.", "")

    found: list[str] = []
    with httpx.Client(headers=SCRAPE_HEADERS) as client:
        for path in COMMON_CONTACT_PATHS:
            url = urljoin(base, path)
            for email in _scrape_emails_from_url(url, business_domain, client):
                if email not in found:
                    found.append(email)
                if len(found) >= 3:
                    return found
            time.sleep(0.5)  # rate limit conservador
    return found


def google_places_search(
    query: str,
    api_key: str,
    max_results: int = 50,
) -> list[dict]:
    """Llama Places API (New) Text Search. Devuelve filas con _details rellenado en la propia respuesta."""
    _ensure_httpx()
    if not api_key:
        raise RuntimeError("Falta GOOGLE_PLACES_API_KEY")
    results: list[dict] = []
    next_page_token: Optional[str] = None
    pages = 0
    field_mask = ",".join([
        "places.id",
        "places.displayName",
        "places.websiteUri",
        "places.internationalPhoneNumber",
        "places.nationalPhoneNumber",
        "places.formattedAddress",
        "places.types",
        "places.primaryType",
        "places.googleMapsUri",
        "nextPageToken",
    ])
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
    }
    url = "https://places.googleapis.com/v1/places:searchText"
    with httpx.Client(timeout=15.0) as client:
        while pages < 3 and len(results) < max_results:
            page_size = min(20, max_results - len(results))
            body: dict = {
                "textQuery": query,
                "languageCode": "es",
                "regionCode": "ES",
                "pageSize": page_size,
            }
            if next_page_token:
                body["pageToken"] = next_page_token
                time.sleep(2.0)  # tokens necesitan delay antes de usarse
            resp = client.post(url, headers=headers, json=body)
            if resp.status_code == 403:
                msg = resp.text[:200]
                raise RuntimeError(
                    f"Google Places (New) 403: {msg}. Habilita 'Places API (New)' en la consola de Google Cloud y verifica restricciones de la API key."
                )
            if resp.status_code >= 400:
                raise RuntimeError(f"Google Places (New) HTTP {resp.status_code}: {resp.text[:240]}")
            data = resp.json()
            error = data.get("error") if isinstance(data, dict) else None
            if error:
                raise RuntimeError(f"Google Places (New) error: {error.get('status', '')} {error.get('message', '')}")
            for place in data.get("places", []):
                if not place.get("id"):
                    continue
                display_name = ""
                dn = place.get("displayName") or {}
                if isinstance(dn, dict):
                    display_name = dn.get("text", "")
                entry = {
                    "place_id": place.get("id", ""),
                    "name": display_name,
                    "formatted_address": place.get("formattedAddress", ""),
                    "types": place.get("types", []) or [],
                    "_details": {
                        "name": display_name,
                        "website": place.get("websiteUri", ""),
                        "international_phone_number": place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber", ""),
                        "formatted_address": place.get("formattedAddress", ""),
                        "types": place.get("types", []) or [],
                        "url": place.get("googleMapsUri", ""),
                    },
                }
                results.append(entry)
                if len(results) >= max_results:
                    break
            next_page_token = data.get("nextPageToken")
            pages += 1
            if not next_page_token:
                break
    return results


def _niche_from_types(types: list[str]) -> str:
    keys = " ".join(types).lower()
    mapping = {
        "dentist": "clinica dental",
        "doctor": "clinica privada",
        "physiotherapist": "fisioterapia",
        "beauty_salon": "peluqueria y estetica",
        "hair_care": "peluqueria",
        "spa": "spa",
        "school": "academia",
        "lawyer": "abogados",
        "accounting": "asesoria fiscal",
        "real_estate_agency": "inmobiliaria",
        "restaurant": "restaurante",
        "lodging": "hotel",
        "cafe": "cafeteria",
        "car_repair": "taller",
        "plumber": "fontaneria",
        "electrician": "electricidad",
        "general_contractor": "reformas",
    }
    for token, niche in mapping.items():
        if token in keys:
            return niche
    return ""


def _resolve_osm_tags(sector: str) -> list[tuple[str, str]]:
    s = (sector or "").lower().strip()
    if not s:
        return []
    if s in SECTOR_TO_OSM:
        return SECTOR_TO_OSM[s]
    for key, tags in SECTOR_TO_OSM.items():
        if key in s or s in key:
            return tags
    return []


def nominatim_lookup_bbox(ciudad: str) -> tuple[float, float, float, float] | None:
    """Devuelve bbox (south, west, north, east) de la ciudad via Nominatim."""
    _ensure_httpx()
    headers = {"User-Agent": SCRAPE_HEADERS["User-Agent"], "Accept": "application/json"}
    with httpx.Client(headers=headers, timeout=15.0) as client:
        resp = client.get(NOMINATIM_URL, params={
            "q": ciudad, "countrycodes": "es", "format": "json", "limit": "1",
        })
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data:
            return None
        bbox = data[0].get("boundingbox")
        if not bbox or len(bbox) != 4:
            return None
        try:
            south, north, west, east = (float(x) for x in bbox)
        except (TypeError, ValueError):
            return None
        return (south, west, north, east)


def overpass_search(sector: str, ciudad: str, max_results: int = 50) -> list[dict]:
    """Busca empresas en OpenStreetMap via Overpass API. Sin API key."""
    _ensure_httpx()
    tags = _resolve_osm_tags(sector)
    if not tags:
        known = ", ".join(sorted(SECTOR_TO_OSM.keys())[:20]) + ", ..."
        raise RuntimeError(
            f"Sector '{sector}' no mapeado a OSM. Prueba con uno de: {known}"
        )
    bbox = nominatim_lookup_bbox(ciudad)
    if not bbox:
        raise RuntimeError(f"Ciudad '{ciudad}' no encontrada en Nominatim.")
    south, west, north, east = bbox

    selectors = "".join(
        f'nwr["{k}"="{v}"]({south},{west},{north},{east});'
        for k, v in tags
    )
    # Pedimos x6 para tener margen tras filtrar los que no tienen web ni email.
    overshoot = max(max_results * 6, 60)
    query = f"[out:json][timeout:60];({selectors});out tags center {overshoot};"

    headers = {"User-Agent": SCRAPE_HEADERS["User-Agent"], "Accept": "application/json"}
    with httpx.Client(headers=headers, timeout=90.0) as client:
        resp = client.post(OVERPASS_URL, data={"data": query})
        if resp.status_code != 200:
            raise RuntimeError(f"Overpass error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()

    out: list[dict] = []
    seen_names: set[str] = set()
    for el in data.get("elements", []):
        t = el.get("tags", {}) or {}
        name = (t.get("name") or "").strip()
        if not name or name.lower() in seen_names:
            continue
        website = (t.get("website") or t.get("contact:website") or "").strip()
        email_tag = (t.get("email") or t.get("contact:email") or "").strip()
        # Descartar los que no tienen ni web ni email — no son contactables.
        if not website and not email_tag:
            continue
        seen_names.add(name.lower())
        addr_parts = [
            t.get("addr:street", ""),
            t.get("addr:housenumber", ""),
            t.get("addr:city", ""),
            t.get("addr:postcode", ""),
        ]
        out.append({
            "name": name,
            "website": website,
            "phone": (t.get("phone") or t.get("contact:phone") or "").strip(),
            "email_tag": email_tag,
            "city": (t.get("addr:city") or ciudad).strip(),
            "address": ", ".join(p for p in addr_parts if p).strip(", "),
        })
        if len(out) >= max_results:
            break
    return out


def _companies_from_osm(
    sector: str,
    ciudad: str,
    max_results: int,
    extract_emails: bool,
    tags: str = "discovery,osm",
    email_target: Optional[int] = None,
    max_email_scrapes: Optional[int] = None,
) -> list[DiscoveredCompany]:
    raw_osm = overpass_search(sector, ciudad, max_results=max_results)
    companies: list[DiscoveredCompany] = []
    email_hits = 0
    email_scrapes = 0
    for entry in raw_osm:
        company = DiscoveredCompany(
            business_name=entry["name"],
            website=entry.get("website", ""),
            phone=entry.get("phone", ""),
            niche=sector,
            service_hint=sector,
            city=entry.get("city") or ciudad,
            tags=tags,
            source="discovery:osm",
            address=entry.get("address", ""),
        )
        tag_email = entry.get("email_tag", "")
        if tag_email and "@" in tag_email:
            company.email = tag_email.lower()
            email_hits += 1
        elif (
            extract_emails
            and company.website
            and (email_target is None or email_hits < email_target)
            and (max_email_scrapes is None or email_scrapes < max_email_scrapes)
        ):
            email_scrapes += 1
            emails = extract_emails_from_website(company.website)
            if emails:
                company.email = emails[0]
                email_hits += 1
        companies.append(company)
        if email_target is not None and email_hits >= email_target:
            break
    return companies


def _companies_from_places(
    sector: str,
    ciudad: str,
    max_results: int,
    extract_emails: bool,
    api_key: str,
    email_target: Optional[int] = None,
    max_email_scrapes: Optional[int] = None,
) -> list[DiscoveredCompany]:
    companies: list[DiscoveredCompany] = []
    seen_places: set[str] = set()
    email_hits = 0
    email_scrapes = 0
    per_query = max(20, min(60, max_results))
    for query in _places_queries(sector, ciudad, max_results=max_results):
        raw = google_places_search(query, api_key, max_results=per_query)
        for entry in raw:
            place_id = entry.get("place_id", "")
            if place_id and place_id in seen_places:
                continue
            if place_id:
                seen_places.add(place_id)
            details = entry.get("_details", {})
            name = details.get("name") or entry.get("name") or ""
            website = details.get("website") or ""
            phone = details.get("international_phone_number") or ""
            types = entry.get("types", []) or details.get("types", []) or []
            address = details.get("formatted_address") or entry.get("formatted_address", "")
            city = _city_from_formatted_address(address, ciudad)

            company = DiscoveredCompany(
                business_name=name.strip(),
                website=website.strip(),
                phone=phone.strip(),
                niche=_niche_from_types(types) or sector,
                service_hint=sector,
                city=city,
                tags="discovery,places",
                source="discovery:places",
                place_id=place_id,
                address=address,
            )

            if (
                extract_emails
                and company.website
                and (email_target is None or email_hits < email_target)
                and (max_email_scrapes is None or email_scrapes < max_email_scrapes)
            ):
                email_scrapes += 1
                emails = extract_emails_from_website(company.website)
                if emails:
                    company.email = emails[0]
                    email_hits += 1
            companies.append(company)
            if email_target is not None and email_hits >= email_target:
                break
            if len(companies) >= max(max_results * 3, max_results):
                break
        if email_target is not None and email_hits >= email_target:
            break
        if len(companies) >= max(max_results * 3, max_results):
            break
    return companies


def discover_companies(
    sector: str,
    ciudad: str,
    max_results: int = 50,
    extract_emails: bool = True,
    api_key: str | None = None,
    source: str = "auto",
    email_target: Optional[int] = None,
    max_email_scrapes: Optional[int] = None,
) -> list[DiscoveredCompany]:
    """Busca empresas combinando fuentes y eliminando duplicados.

    source=auto usa Google Places primero cuando hay API key y siempre intenta
    complementar con OSM. source=places/source=osm conservan el modo especifico.
    """
    api_key = (api_key or GOOGLE_PLACES_API_KEY).strip()
    src = (source or "auto").lower().strip()
    if src not in {"auto", "places", "osm"}:
        raise RuntimeError(f"source invalido: {source}. Usa auto|places|osm.")
    if src == "places" and not api_key:
        raise RuntimeError("source=places pero falta GOOGLE_PLACES_API_KEY en .env")

    companies: list[DiscoveredCompany] = []
    errors: list[str] = []
    metrics = {
        "sector": sector,
        "ciudad": ciudad,
        "source": src,
        "requested": int(max_results),
        "places_raw": 0,
        "osm_raw": 0,
        "deduped": 0,
        "returned": 0,
        "email_target": email_target,
        "max_email_scrapes": max_email_scrapes,
        "queries": _places_queries(sector, ciudad, max_results) if api_key and src in {"auto", "places"} else [],
        "errors": errors,
    }

    if src in {"auto", "places"} and api_key:
        try:
            places = _companies_from_places(
                sector,
                ciudad,
                max_results,
                extract_emails,
                api_key,
                email_target=email_target,
                max_email_scrapes=max_email_scrapes,
            )
            metrics["places_raw"] = len(places)
            companies.extend(places)
        except Exception as exc:
            errors.append(f"places: {exc}")
            if src == "places":
                raise

    # En auto, OSM complementa a Places para ampliar cobertura; si Places falla,
    # OSM mantiene el discovery operativo sin API key.
    current_email_hits = sum(1 for c in companies if c.email)
    should_query_osm = src in {"auto", "osm"} and not (
        src == "auto" and email_target is not None and current_email_hits >= email_target
    )
    if should_query_osm:
        try:
            remaining_email_target = None
            if email_target is not None:
                remaining_email_target = max(0, email_target - current_email_hits)
            remaining_email_scrapes = max_email_scrapes
            if max_email_scrapes is not None:
                places_with_scraped_emails = sum(1 for c in companies if c.email and c.website)
                remaining_email_scrapes = max(0, max_email_scrapes - places_with_scraped_emails)
            osm = _companies_from_osm(
                sector,
                ciudad,
                max_results,
                extract_emails,
                email_target=remaining_email_target,
                max_email_scrapes=remaining_email_scrapes,
            )
            metrics["osm_raw"] = len(osm)
            companies.extend(osm)
        except Exception as exc:
            errors.append(f"osm: {exc}")
            if src == "osm" or not companies:
                raise RuntimeError("; ".join(errors) or str(exc))

    if not companies and errors:
        raise RuntimeError("; ".join(errors))

    deduped = _dedupe_companies(companies)
    result = deduped[:max_results]
    metrics["deduped"] = len(deduped)
    metrics["returned"] = len(result)
    discover_companies.last_metrics = metrics  # type: ignore[attr-defined]
    return result


discover_companies.last_metrics = {}  # type: ignore[attr-defined]


def write_csv(companies: Iterable[DiscoveredCompany], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "business_name", "email", "contact_name", "niche", "website",
        "service_hint", "city", "phone", "tags", "source",
    ]
    count = 0
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for c in companies:
            writer.writerow(c.as_csv_row())
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Discovery de empresas para Vantelia outreach.")
    parser.add_argument("--sector", required=True)
    parser.add_argument("--ciudad", required=True)
    parser.add_argument("--max", type=int, default=50)
    parser.add_argument("--no-emails", action="store_true", help="No intentar extraer emails de webs.")
    parser.add_argument("--output", type=Path, default=Path("outreach/discovered.csv"))
    parser.add_argument("--import-direct", action="store_true", help="Importar directamente al outreach DB.")
    parser.add_argument("--db", type=Path, default=BASE_DIR / "storage" / "outreach" / "outreach.db")
    parser.add_argument("--source", choices=["auto", "places", "osm"], default="auto",
                        help="Fuente: auto (Places si hay key, si no OSM), places, osm.")
    args = parser.parse_args()

    print(f"Buscando: sector='{args.sector}' ciudad='{args.ciudad}' max={args.max} source={args.source}")
    companies = discover_companies(
        sector=args.sector,
        ciudad=args.ciudad,
        max_results=args.max,
        extract_emails=not args.no_emails,
        source=args.source,
    )
    with_email = [c for c in companies if c.email]
    print(f"Encontradas {len(companies)} empresas, {len(with_email)} con email publico.")

    n = write_csv(companies, args.output)
    print(f"CSV escrito: {args.output} ({n} filas).")

    if args.import_direct:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from outreach_campaign import connect, now_iso
        with connect(args.db) as conn:
            added = updated = skipped = 0
            for c in companies:
                if not c.email:
                    skipped += 1
                    continue
                payload = {**c.as_csv_row(), "now": now_iso()}
                payload["email"] = payload["email"].lower()
                row = conn.execute("SELECT email FROM prospects WHERE email=?", (payload["email"],)).fetchone()
                if row:
                    conn.execute(
                        """UPDATE prospects SET business_name=:business_name, contact_name=:contact_name,
                        niche=:niche, website=:website, service_hint=:service_hint, city=:city,
                        phone=:phone, tags=:tags, source=:source, updated_at=:now WHERE email=:email""",
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
        print(f"Importados al DB: {added} nuevos, {updated} actualizados, {skipped} sin email.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
