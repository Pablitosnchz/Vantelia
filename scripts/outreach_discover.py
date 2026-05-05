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
import urllib.robotparser as robotparser
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
GOOGLE_PLACES_BASE = "https://maps.googleapis.com/maps/api/place"

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
COMMON_CONTACT_PATHS = ["/", "/contacto", "/contact", "/contacto.html", "/contactar", "/aviso-legal", "/legal"]
GENERIC_LOCAL_PARTS = {"noreply", "no-reply", "postmaster", "webmaster", "abuse", "ejemplo", "example"}
SCRAPE_TIMEOUT = 8.0
SCRAPE_HEADERS = {
    "User-Agent": "VanteliaOutreachBot/1.0 (+https://www.vantelia.es; contacto@vantelia.es)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-ES,es;q=0.9",
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
        rp = robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(SCRAPE_HEADERS["User-Agent"], url)
    except Exception:
        return True  # Si robots.txt no responde, permitimos pero con cautela


def _normalize_email(email: str) -> str:
    return email.strip().lower()


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
    """Llama Google Places Text Search + Place Details."""
    _ensure_httpx()
    results: list[dict] = []
    next_page_token = None
    pages = 0
    with httpx.Client(timeout=10.0) as client:
        while pages < 3 and len(results) < max_results:
            params = {"query": query, "key": api_key, "language": "es"}
            if next_page_token:
                params["pagetoken"] = next_page_token
                time.sleep(2.0)  # Google requiere espera para page tokens
            resp = client.get(f"{GOOGLE_PLACES_BASE}/textsearch/json", params=params)
            data = resp.json()
            if data.get("status") not in {"OK", "ZERO_RESULTS"}:
                raise RuntimeError(f"Google Places error: {data.get('status')} {data.get('error_message', '')}")
            for entry in data.get("results", []):
                results.append(entry)
                if len(results) >= max_results:
                    break
            next_page_token = data.get("next_page_token")
            pages += 1
            if not next_page_token:
                break

        # Hidratar con Place Details para conseguir website + telefono
        hydrated: list[dict] = []
        for entry in results:
            place_id = entry.get("place_id")
            if not place_id:
                continue
            details_resp = client.get(
                f"{GOOGLE_PLACES_BASE}/details/json",
                params={
                    "place_id": place_id,
                    "fields": "name,website,international_phone_number,formatted_address,types,url",
                    "key": api_key,
                    "language": "es",
                },
            )
            details = details_resp.json().get("result", {})
            hydrated.append({**entry, **{"_details": details}})
            time.sleep(0.15)
    return hydrated


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


def discover_companies(
    sector: str,
    ciudad: str,
    max_results: int = 50,
    extract_emails: bool = True,
    api_key: str | None = None,
    source: str = "auto",
) -> list[DiscoveredCompany]:
    api_key = (api_key or GOOGLE_PLACES_API_KEY).strip()
    src = (source or "auto").lower().strip()
    if src not in {"auto", "places", "osm"}:
        raise RuntimeError(f"source invalido: {source}. Usa auto|places|osm.")
    if src == "places" and not api_key:
        raise RuntimeError("source=places pero falta GOOGLE_PLACES_API_KEY en .env")
    use_places = (src == "places") or (src == "auto" and bool(api_key))

    if not use_places:
        raw_osm = overpass_search(sector, ciudad, max_results=max_results)
        companies: list[DiscoveredCompany] = []
        for entry in raw_osm:
            company = DiscoveredCompany(
                business_name=entry["name"],
                website=entry.get("website", ""),
                phone=entry.get("phone", ""),
                niche=sector,
                service_hint=sector,
                city=entry.get("city") or ciudad,
                tags="discovery,osm",
                source="discovery:osm",
            )
            tag_email = entry.get("email_tag", "")
            if tag_email and "@" in tag_email:
                company.email = tag_email.lower()
            elif extract_emails and company.website:
                emails = extract_emails_from_website(company.website)
                if emails:
                    company.email = emails[0]
            companies.append(company)
        return companies

    query = f"{sector} en {ciudad}".strip()
    raw = google_places_search(query, api_key, max_results=max_results)

    companies: list[DiscoveredCompany] = []
    for entry in raw:
        details = entry.get("_details", {})
        name = details.get("name") or entry.get("name") or ""
        website = details.get("website") or ""
        phone = details.get("international_phone_number") or ""
        types = entry.get("types", []) or details.get("types", []) or []
        address = details.get("formatted_address") or entry.get("formatted_address", "")
        city = ciudad
        if address:
            for part in address.split(","):
                if part.strip().split(" ", 1)[0].isdigit():
                    continue
                if any(c.isalpha() for c in part):
                    city = part.strip() or city
                    break

        company = DiscoveredCompany(
            business_name=name.strip(),
            website=website.strip(),
            phone=phone.strip(),
            niche=_niche_from_types(types),
            service_hint=sector,
            city=city,
            tags="discovery",
            source="discovery:places",
            place_id=entry.get("place_id", ""),
        )

        if extract_emails and company.website:
            emails = extract_emails_from_website(company.website)
            if emails:
                company.email = emails[0]
        companies.append(company)
    return companies


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
