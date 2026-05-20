from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from openai import OpenAI


PAGE_LIMIT_CHARS = 16000
MODEL_CONTEXT_LIMIT = 160000
REQUEST_TIMEOUT = 14
MAX_PREVIEW_PAGES = 80
DEFAULT_ONBOARDING_MODEL = os.getenv("ONBOARDING_MODEL", "gpt-4o-mini")
MAX_DERIVED_FAQ_PAIRS = 5

PRIORITY_SLUGS = (
    "faq", "faqs", "preguntas", "preguntas-frecuentes", "ayuda", "help", "soporte", "support",
    "precios", "tarifas", "planes", "pricing", "plans", "tarifa",
    "servicios", "service", "services", "productos", "producto", "product", "products",
    "contacto", "contact", "contactanos", "contactenos",
    "nosotros", "sobre", "sobre-nosotros", "about", "about-us", "quienes-somos", "equipo", "team",
    "resultados", "casos", "casos-de-exito", "clientes", "testimonios", "reviews",
    "plataforma", "platform", "como-funciona", "how-it-works",
    "documentacion", "docs", "guia", "guides",
)

NEG_SLUGS = {
    "tag", "tags", "categoria", "category", "categorias",
    "author", "autor", "page",
    "cookie", "cookies", "privacidad", "politica", "politicas",
    "terminos", "aviso-legal", "legal", "rgpd", "gdpr",
}

SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".svg", ".gif", ".webp", ".zip",
    ".mp4", ".mov", ".avi", ".mp3", ".wav", ".css", ".js", ".ico",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "VanteliaOnboarding/1.1 (+https://vantelia.es)",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
)


@dataclass
class OnboardingResult:
    normalized_url: str
    links: list[str]
    all_text: str
    info_txt: str
    detected_business_name: str
    suggested_welcome: str
    faq_pairs: list[tuple[str, str]] = field(default_factory=list)
    faq_source: str = "none"


# --- URL helpers ----------------------------------------------------------

def normalize_url(raw_url: str) -> str:
    value = raw_url.strip()
    if not value:
        raise ValueError("Introduce una URL valida, por ejemplo https://empresa.com")

    parsed = urlparse(value)
    if not parsed.scheme:
        value = f"https://{value}"
        parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Introduce una URL valida, por ejemplo https://empresa.com")

    return value.rstrip("/")


def slugify_company(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    normalized = normalized.strip("_")
    return normalized or "empresa_demo"


def clean_text(value: str) -> str:
    return "\n".join(line.strip() for line in value.splitlines() if line.strip())


def fetch_html(target_url: str) -> str:
    response = SESSION.get(target_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        raise ValueError(f"La URL no devuelve HTML util ({content_type or 'sin content-type'}).")

    return response.text


def infer_company_name(base_url: str, html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content", "").strip():
        return og_title["content"].strip()

    if soup.title and soup.title.string and soup.title.string.strip():
        title = soup.title.string.strip()
        for separator in ("|", "-", "·", "—", "–"):
            if separator in title:
                left = title.split(separator, 1)[0].strip()
                if left:
                    return left
        return title

    domain = urlparse(base_url).netloc.replace("www.", "")
    base_name = domain.split(".")[0].replace("-", " ").replace("_", " ").strip()
    return base_name.title() or "Empresa"


# --- Link discovery -------------------------------------------------------

def _is_useful_url(url: str, base_domain: str) -> bool:
    p = urlparse(url)
    if p.scheme not in {"http", "https"}:
        return False
    if p.netloc.replace("www.", "") != base_domain:
        return False
    if p.path.lower().endswith(SKIP_EXTENSIONS):
        return False
    return True


def _clean_url(url: str) -> str:
    p = urlparse(url)
    return p._replace(query="", fragment="").geturl().rstrip("/")


def _extract_internal_links(base_url: str, html: str, base_domain: str) -> set[str]:
    found: set[str] = set()
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "whatsapp:")):
            continue
        absolute = urljoin(base_url, href)
        if not _is_useful_url(absolute, base_domain):
            continue
        found.add(_clean_url(absolute))
    return found


def _discover_via_sitemap(base_url: str, base_domain: str) -> set[str]:
    found: set[str] = set()
    candidates = [
        urljoin(base_url + "/", "sitemap.xml"),
        urljoin(base_url + "/", "sitemap_index.xml"),
        urljoin(base_url + "/", "sitemap-index.xml"),
        urljoin(base_url + "/", "wp-sitemap.xml"),
    ]
    seen_sitemaps: set[str] = set()

    def _fetch_xml(url: str) -> str:
        try:
            r = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        except Exception:  # noqa: BLE001
            return ""
        if r.status_code != 200:
            return ""
        ct = r.headers.get("content-type", "").lower()
        if "xml" not in ct and "text" not in ct:
            return ""
        return r.text or ""

    def _process(xml_text: str, depth: int = 0) -> None:
        if not xml_text or depth > 2:
            return
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_text, re.IGNORECASE):
            u = loc.strip()
            if u.lower().endswith((".xml", ".xml.gz")):
                if u in seen_sitemaps:
                    continue
                seen_sitemaps.add(u)
                _process(_fetch_xml(u), depth + 1)
                continue
            if not _is_useful_url(u, base_domain):
                continue
            found.add(_clean_url(u))

    for sm in candidates:
        if sm in seen_sitemaps:
            continue
        seen_sitemaps.add(sm)
        _process(_fetch_xml(sm))

    return found


def _slug_priority(url: str) -> int:
    path_parts = [p for p in urlparse(url).path.lower().split("/") if p]
    if any(part in NEG_SLUGS for part in path_parts):
        return 1000
    for idx, slug in enumerate(PRIORITY_SLUGS):
        for part in path_parts:
            if part == slug or part.startswith(slug + "-") or slug in part:
                return idx
    return len(PRIORITY_SLUGS) + 100


def get_all_links(base_url: str, max_paginas: int) -> list[str]:
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.replace("www.", "")
    base_clean = base_url.rstrip("/")

    discovered: set[str] = {base_clean}

    discovered |= _discover_via_sitemap(base_url, base_domain)

    try:
        root_html = fetch_html(base_url)
        discovered |= _extract_internal_links(base_url, root_html, base_domain)
    except Exception:  # noqa: BLE001
        pass

    cap = min(max_paginas, MAX_PREVIEW_PAGES)

    if len(discovered) < cap * 2:
        first_level = sorted(discovered - {base_clean}, key=_slug_priority)[:10]
        for child_url in first_level:
            try:
                child_html = fetch_html(child_url)
            except Exception:  # noqa: BLE001
                continue
            discovered |= _extract_internal_links(child_url, child_html, base_domain)
            if len(discovered) >= cap * 4:
                break

    prioritized = sorted(
        discovered,
        key=lambda item: (
            0 if item.rstrip("/") == base_clean else 1,
            _slug_priority(item),
            len(urlparse(item).path),
            item,
        ),
    )
    return prioritized[:cap]


# --- FAQ extraction (structured + DOM) ------------------------------------

def _parse_jsonld_blocks(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = tag.string or tag.get_text("")
        if not raw or not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            # Some sites embed multiple JSON-LD objects concatenated. Best-effort.
            try:
                data = json.loads(re.sub(r"//.*?\n", "\n", raw))
            except Exception:  # noqa: BLE001
                continue
        if isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                out.extend(d for d in graph if isinstance(d, dict))
            else:
                out.append(data)
    return out


def _faq_pairs_from_jsonld(items: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    def _norm_answer(node) -> str:
        if isinstance(node, list):
            node = node[0] if node else {}
        if isinstance(node, dict):
            text = node.get("text") or node.get("answerText") or ""
        else:
            text = str(node or "")
        if not text:
            return ""
        text = str(text)
        if "<" in text and ">" in text:
            text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()

    for it in items:
        t = it.get("@type")
        types = t if isinstance(t, list) else [t]
        types_lower = [str(x).lower() for x in types if x]

        if any(x in ("faqpage", "qapage") for x in types_lower):
            for q in it.get("mainEntity", []) or []:
                if not isinstance(q, dict):
                    continue
                name = (q.get("name") or q.get("question") or "").strip()
                ans = _norm_answer(q.get("acceptedAnswer") or q.get("suggestedAnswer"))
                if name and ans:
                    pairs.append((name, ans))

        elif "question" in types_lower:
            name = (it.get("name") or "").strip()
            ans = _norm_answer(it.get("acceptedAnswer") or it.get("suggestedAnswer"))
            if name and ans:
                pairs.append((name, ans))

    return pairs


_FAQ_CONTAINER_RE = re.compile(r"accordion|faq|toggle|collapse|question|preg", re.I)


def _faq_pairs_from_dom(soup: BeautifulSoup) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    arrow_rx = re.compile(
        r"[←-⇿■-◿⬀-⯿⟰-⟿⌀-⏿\s]+$"
    )
    arrow_lead_rx = re.compile(
        r"^[←-⇿■-◿⬀-⯿⟰-⟿⌀-⏿\s]+"
    )

    def _clean_q(value: str) -> str:
        value = re.sub(r"\s+", " ", value or "").strip()
        value = arrow_lead_rx.sub("", value)
        value = arrow_rx.sub("", value).strip()
        return value

    def _push(q: str, a: str) -> None:
        q = _clean_q(q)
        a = re.sub(r"\s+", " ", a or "").strip()
        if not q or not a:
            return
        key = q.lower()
        if key in seen:
            return
        seen.add(key)
        pairs.append((q, a))

    # <details><summary>Q</summary>A</details>
    for det in soup.find_all("details"):
        summary = det.find("summary")
        if not summary:
            continue
        q = summary.get_text(" ", strip=True)
        clone = BeautifulSoup(str(det), "html.parser")
        s = clone.find("summary")
        if s:
            s.decompose()
        a = clone.get_text(" ", strip=True)
        if q and a and 4 <= len(q) <= 300 and 8 <= len(a) <= 4000:
            _push(q, a)

    # FAQ-shaped containers
    for container in soup.find_all(class_=_FAQ_CONTAINER_RE):
        for h in container.find_all(["h2", "h3", "h4", "h5", "button", "dt"]):
            q = h.get_text(" ", strip=True)
            if not q or len(q) > 300 or len(q) < 6:
                continue
            if "?" not in q and len(q) < 18:
                continue
            ans_node = h.find_next_sibling()
            a = ""
            if ans_node:
                a = ans_node.get_text(" ", strip=True)
            if not a:
                parent = h.parent
                if parent:
                    a = re.sub(re.escape(q), "", parent.get_text(" ", strip=True), count=1).strip()
            if a and 8 <= len(a) <= 4000:
                _push(q, a)

    # Definition lists
    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            q = dt.get_text(" ", strip=True)
            if not q:
                continue
            dd = None
            for sib in dt.find_next_siblings():
                if sib.name == "dd":
                    dd = sib
                    break
                if sib.name == "dt":
                    break
            if dd:
                a = dd.get_text(" ", strip=True)
                if q and a and 4 <= len(q) <= 300 and 8 <= len(a) <= 4000:
                    _push(q, a)

    # Heuristic: heading ending with ? followed by paragraph
    for h in soup.find_all(["h2", "h3", "h4"]):
        txt = h.get_text(" ", strip=True)
        if not txt or "?" not in txt or len(txt) > 300:
            continue
        nxt = h.find_next_sibling()
        if nxt and nxt.name in ("p", "div", "ul", "ol"):
            a = nxt.get_text(" ", strip=True)
            if a and 8 <= len(a) <= 4000:
                _push(txt, a)

    return pairs


# --- Per-page scrape ------------------------------------------------------

CHROME_SELECTORS = [
    "body > header", "body > footer", "body > nav",
    ".site-header", ".site-footer", "#site-header", "#site-footer",
    ".navbar", ".main-navbar", ".main-nav", ".global-nav", ".mobile-menu",
    ".cookie-banner", ".cookies-banner", ".cookie-consent", "#cookies", "#cookie",
    "[role=banner]", "[role=contentinfo]",
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().\-]{7,}\d)")


def scrape_page(target_url: str) -> dict:
    try:
        html = fetch_html(target_url)
    except Exception as exc:  # noqa: BLE001
        return {"url": target_url, "error": str(exc)}

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "template"]):
        tag.decompose()

    # Extract FAQ BEFORE removing chrome (some sites put FAQs in shared sections)
    jsonld_items = _parse_jsonld_blocks(soup)
    faq_pairs: list[tuple[str, str]] = []
    faq_pairs.extend(_faq_pairs_from_jsonld(jsonld_items))
    faq_pairs.extend(_faq_pairs_from_dom(soup))

    # Remove only true site chrome (keep semantic <header>/<footer> inside sections)
    for sel in CHROME_SELECTORS:
        for node in soup.select(sel):
            node.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_description = ""
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        meta_description = md["content"].strip()
    if not meta_description:
        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.get("content"):
            meta_description = og["content"].strip()

    headings = [
        clean_text(node.get_text(" ", strip=True))
        for node in soup.find_all(["h1", "h2", "h3", "h4"])
        if node.get_text(strip=True)
    ][:40]

    main = soup.select_one("main, article, [role=main]") or soup.body or soup
    raw_text = main.get_text(separator="\n", strip=True)
    body_text = clean_text(raw_text)[:PAGE_LIMIT_CHARS]

    emails = sorted({m.group(0) for m in EMAIL_RE.finditer(raw_text)})[:6]
    phones_raw = {m.group(0).strip() for m in PHONE_RE.finditer(raw_text)}
    phones = sorted({re.sub(r"\s+", " ", p) for p in phones_raw if len(re.sub(r"\D", "", p)) >= 9})[:6]

    return {
        "url": target_url,
        "title": title,
        "meta_description": meta_description,
        "headings": headings,
        "body": body_text,
        "faq": faq_pairs,
        "emails": emails,
        "phones": phones,
    }


# --- Aggregator -----------------------------------------------------------

def collect_site_content(base_url: str, max_paginas: int) -> tuple[list[str], str, str, dict]:
    normalized_url = normalize_url(base_url)
    try:
        root_html = fetch_html(normalized_url)
        detected_business_name = infer_company_name(normalized_url, root_html)
    except Exception:  # noqa: BLE001
        detected_business_name = urlparse(normalized_url).netloc.replace("www.", "")

    links = get_all_links(normalized_url, max_paginas=max_paginas)

    pages: list[dict] = []
    seen_body_hashes: set[str] = set()
    for link in links:
        page = scrape_page(link)
        if page.get("error"):
            continue
        key = (page.get("body") or "")[:1500]
        if key and key in seen_body_hashes and not page.get("faq"):
            continue
        seen_body_hashes.add(key)
        pages.append(page)

    all_text_parts: list[str] = []
    seen_faq: set[str] = set()
    all_faq: list[tuple[str, str]] = []
    all_emails: set[str] = set()
    all_phones: set[str] = set()

    for p in pages:
        all_emails.update(p.get("emails") or [])
        all_phones.update(p.get("phones") or [])
        for q, a in (p.get("faq") or []):
            q_clean = re.sub(r"\s+", " ", (q or "")).strip()
            a_clean = re.sub(r"\s+", " ", (a or "")).strip()
            if not q_clean or not a_clean:
                continue
            key = q_clean.lower()
            if key in seen_faq:
                continue
            seen_faq.add(key)
            all_faq.append((q_clean, a_clean[:1500]))

        all_text_parts.append(
            f"PAGINA: {p['url']}\n"
            f"TITULO: {p.get('title') or ''}\n"
            f"META: {p.get('meta_description') or ''}\n"
            f"HEADINGS: {' | '.join(p.get('headings') or [])}\n"
            f"CONTENIDO:\n{p.get('body') or ''}\n"
        )

    all_text = "\n---\n".join(all_text_parts)

    aggregate = {
        "emails": sorted(all_emails)[:10],
        "phones": sorted(all_phones)[:10],
        "faq_pairs": all_faq[:60],
    }

    return links, all_text, detected_business_name, aggregate


# --- LLM info.txt synthesis ----------------------------------------------

def _build_info_prompt(
    all_text: str,
    nombre_bot_value: str,
    tono_value: str,
    idioma_value: str,
    aggregate: dict,
) -> str:
    pairs = aggregate.get("faq_pairs") or []
    if pairs:
        faq_lines = []
        for i, (q, a) in enumerate(pairs, 1):
            faq_lines.append(f"{i}. P: {q}\n   R: {a}")
        faq_block_raw = "\n".join(faq_lines)
        faq_mode = "literal"
    else:
        faq_block_raw = "(No se encontraron preguntas frecuentes literales en la web.)"
        faq_mode = "derive"

    emails = ", ".join(aggregate.get("emails") or []) or "No detectado"
    phones = ", ".join(aggregate.get("phones") or []) or "No detectado"

    return f"""
Eres especialista en onboarding de asistentes IA para empresas.
Genera un `info.txt` exhaustivo para alimentar un sistema RAG comercial y de soporte.

REGLAS ESTRICTAS (NO INFRINGIR):
- No inventes ningun dato factual. Si no esta en CONTENIDO FUENTE, escribe "No especificado en la web".
- Modo PREGUNTAS FRECUENTES: {faq_mode}
  - Si modo = "literal": copia EXACTAMENTE las preguntas de FAQS_LITERALES, en el mismo orden, sin parafrasear. Puedes limpiar HTML residual de respuestas pero NO las resumas ni inventes nuevas FAQs.
  - Si modo = "derive": no hay FAQs literales en la web. Genera como maximo 5 preguntas frecuentes utiles basandote SOLO en CONTENIDO FUENTE (servicios, precios, contacto, politicas, proceso). Las respuestas deben citar datos reales del contenido. Si un dato no aparece, no fuerces la pregunta.
- En "PREGUNTAS SUGERIDAS PARA REVISION HUMANA" puedes proponer hasta 6 preguntas adicionales que el bot reciba habitualmente, marcadas claramente como propuestas.
- Cada titulo de seccion debe ir en MAYUSCULAS seguido de dos puntos, en su propia linea.
- Lista TODOS los servicios, planes y precios que aparezcan literalmente en el contenido.
- Idioma de salida: {idioma_value}.
- Tono general del bot: {tono_value}.

ESTRUCTURA OBLIGATORIA (manten cabeceras literales y orden):

===== INFORMACION DE [NOMBRE DEL NEGOCIO] =====

DATOS GENERALES:
- Nombre:
- Tipo de negocio:
- Descripcion:
- Eslogan:
- Web:

CONTACTO Y UBICACION:
- Direccion:
- Ciudad:
- Pais:
- Telefono: (candidatos detectados: {phones})
- Email: (candidatos detectados: {emails})
- Instagram:
- Facebook:
- LinkedIn:
- TikTok:
- YouTube:
- Otras redes:
- Google Maps:

HORARIOS:
- Lunes a Viernes:
- Sabados:
- Domingos:
- Notas:

SERVICIOS Y PRECIOS:
- (Lista TODOS los servicios/planes/productos visibles. Para cada uno: Categoria / Servicio / Precio / Detalle.)

PROCESO COMERCIAL Y OPERATIVO:
- Como funciona la atencion:
- Como reservar o solicitar informacion:
- Pasos del servicio:
- Requisitos previos:
- Seguimiento o post-servicio:

PERFIL DE CLIENTE IDEAL:
- Tipos de cliente:
- Casos de uso:
- Problemas que resuelve:

OBJECIONES HABITUALES Y RESPUESTAS:
P: ...
R: ...

EQUIPO PROFESIONAL:
- Nombre - Cargo - Notas

PREGUNTAS FRECUENTES:
(Copia EXACTAMENTE de FAQS_LITERALES. Una P/R por bloque.)
P: ...
R: ...

PREGUNTAS SUGERIDAS PARA REVISION HUMANA:
P: ...
R: ...

POLITICAS:
- Citas/Reservas:
- Metodos de pago:
- Cancelaciones:
- Garantias:
- Privacidad/RGPD:

DIFERENCIACION:
- Ventajas competitivas:
- Certificaciones/Premios:
- Pruebas de confianza:

GUIA DEL ASISTENTE:
- Nombre del bot: {nombre_bot_value}
- Tono: {tono_value}
- Idioma: {idioma_value}
- Instrucciones:
  - Responder con precision.
  - No inventar informacion.
  - Mantenerse dentro del contexto del negocio.
  - Derivar al equipo humano cuando falten datos.
  - Priorizar reserva, contacto o captacion de lead cuando tenga sentido.

==================== FAQS_LITERALES ====================
{faq_block_raw}
========================================================

CONTENIDO FUENTE:
{all_text[:MODEL_CONTEXT_LIMIT]}
""".strip()


def generate_info(
    all_text: str,
    api_key: str,
    nombre_bot_value: str,
    tono_value: str,
    idioma_value: str,
    aggregate: dict | None = None,
    model: str = DEFAULT_ONBOARDING_MODEL,
) -> str:
    client = OpenAI(api_key=api_key)
    prompt = _build_info_prompt(all_text, nombre_bot_value, tono_value, idioma_value, aggregate or {})

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un sintetizador de fichas de empresa para sistemas RAG. "
                    "Precision factual obligatoria. Cero invencion. Estructura literal. "
                    "Si un dato falta, escribes 'No especificado en la web' en lugar de adivinar."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=8000,
    )

    return (response.choices[0].message.content or "").strip()


_FAQ_SECTION_REPLACE_RE = re.compile(
    r"(PREGUNTAS\s+FRECUENTES[^\n]*:\s*\n)(?P<body>.*?)(?=\nPREGUNTAS\s+SUGERIDAS|\n=====|\n[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s/]{3,}:\s*\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)

_FAQ_STRIPPED_PLACEHOLDER = (
    "(Las preguntas frecuentes se gestionan desde el panel del cliente.\n"
    " Ver bloque PREGUNTAS FRECUENTES (PANEL) al final de este documento.)\n"
)


def _parse_faq_section(info_txt: str) -> list[tuple[str, str]]:
    """Parse the LLM-generated 'PREGUNTAS FRECUENTES' section into pairs."""
    if not info_txt:
        return []
    m = _FAQ_SECTION_REPLACE_RE.search(info_txt)
    if not m:
        return []
    body = m.group("body")
    pairs: list[tuple[str, str]] = []
    cur_q: str | None = None
    cur_a: list[str] = []

    def flush() -> None:
        nonlocal cur_q, cur_a
        if cur_q:
            ans = " ".join(s.strip() for s in cur_a).strip()
            q = cur_q.strip().strip(".").strip()
            if q and ans and len(q) >= 4 and len(ans) >= 4 and "..." not in q:
                pairs.append((q, ans))
        cur_q = None
        cur_a = []

    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^P\s*:\s*", line, re.IGNORECASE):
            flush()
            cur_q = re.sub(r"^P\s*:\s*", "", line, flags=re.IGNORECASE)
            cur_a = []
        elif re.match(r"^R\s*:\s*", line, re.IGNORECASE):
            cur_a.append(re.sub(r"^R\s*:\s*", "", line, flags=re.IGNORECASE))
        else:
            if cur_q is not None:
                cur_a.append(line)
    flush()
    return pairs


def _strip_faq_section(info_txt: str) -> str:
    """Replace the FAQ section body with a pointer to the panel-managed block.

    The actual FAQ content lives in the kb_qa table and is rendered into
    info.txt by api.py via the PREGUNTAS FRECUENTES (PANEL) marker. Stripping
    the LLM-generated body guarantees dashboard and bot stay in sync.
    """
    if not info_txt or not _FAQ_SECTION_REPLACE_RE.search(info_txt):
        return info_txt
    return _FAQ_SECTION_REPLACE_RE.sub(
        lambda m: m.group(1) + _FAQ_STRIPPED_PLACEHOLDER, info_txt, count=1
    )


def run_onboarding(
    *,
    website_url: str,
    api_key: str,
    nombre_bot: str,
    tono: str,
    idioma: str,
    max_paginas: int,
    model: str = DEFAULT_ONBOARDING_MODEL,
) -> OnboardingResult:
    links, all_text, detected_business_name, aggregate = collect_site_content(
        website_url, max_paginas=max_paginas
    )
    info_txt = generate_info(
        all_text=all_text,
        api_key=api_key,
        nombre_bot_value=nombre_bot,
        tono_value=tono,
        idioma_value=idioma,
        aggregate=aggregate,
        model=model,
    )

    literal_pairs = aggregate.get("faq_pairs") or []
    if literal_pairs:
        final_pairs = literal_pairs
        faq_source = "literal"
    else:
        final_pairs = _parse_faq_section(info_txt)[:MAX_DERIVED_FAQ_PAIRS]
        faq_source = "derived" if final_pairs else "none"

    # Strip LLM-rendered FAQ body so the only source of truth for FAQs is the
    # kb_qa table (rendered back into info.txt by api.py via the PANEL marker).
    info_txt = _strip_faq_section(info_txt)
    faq_pairs = final_pairs

    suggested_welcome = (
        f"Hola, soy {nombre_bot}, el asistente de {detected_business_name}. "
        "En que puedo ayudarte hoy?"
    )
    return OnboardingResult(
        normalized_url=normalize_url(website_url),
        links=links,
        all_text=all_text,
        info_txt=info_txt,
        detected_business_name=detected_business_name,
        suggested_welcome=suggested_welcome,
        faq_pairs=faq_pairs,
        faq_source=faq_source,
    )
