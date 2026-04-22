from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from openai import OpenAI


PAGE_LIMIT_CHARS = 8000
MODEL_CONTEXT_LIMIT = 48000
REQUEST_TIMEOUT = 12
MAX_PREVIEW_PAGES = 40
DEFAULT_ONBOARDING_MODEL = os.getenv("ONBOARDING_MODEL", "gpt-4o-mini")

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "VanteliaOnboarding/1.0 (+https://vantelia.es)",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
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
        for separator in ("|", "-", "·", "—"):
            if separator in title:
                left = title.split(separator, 1)[0].strip()
                if left:
                    return left
        return title

    domain = urlparse(base_url).netloc.replace("www.", "")
    base_name = domain.split(".")[0].replace("-", " ").replace("_", " ").strip()
    return base_name.title() or "Empresa"


def get_all_links(base_url: str, max_paginas: int) -> list[str]:
    html = fetch_html(base_url)
    soup = BeautifulSoup(html, "html.parser")
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.replace("www.", "")
    links = {base_url}

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.replace("www.", "") != base_domain:
            continue
        if parsed.path.lower().endswith(
            (".pdf", ".jpg", ".jpeg", ".png", ".svg", ".gif", ".webp", ".zip", ".mp4")
        ):
            continue

        clean_url = parsed._replace(query="", fragment="").geturl().rstrip("/")
        links.add(clean_url)

    prioritized = sorted(
        links,
        key=lambda item: (
            0 if item.rstrip("/") == base_url.rstrip("/") else 1,
            len(urlparse(item).path),
            item,
        ),
    )
    return prioritized[: min(max_paginas, MAX_PREVIEW_PAGES)]


def scrape_page(target_url: str) -> str:
    try:
        html = fetch_html(target_url)
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        meta_description = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            meta_description = meta.get("content", "").strip()

        headings = [
            clean_text(node.get_text(" ", strip=True))
            for node in soup.find_all(["h1", "h2", "h3"])
            if node.get_text(strip=True)
        ]
        body_text = clean_text(soup.get_text(separator="\n", strip=True))[:PAGE_LIMIT_CHARS]

        return (
            f"PAGINA: {target_url}\n"
            f"TITULO: {title}\n"
            f"META_DESCRIPTION: {meta_description}\n"
            f"HEADINGS: {' | '.join(headings[:14])}\n"
            f"CONTENIDO:\n{body_text}\n"
        )
    except Exception as exc:  # noqa: BLE001
        return f"PAGINA: {target_url}\nERROR: {exc}\n"


def collect_site_content(base_url: str, max_paginas: int) -> tuple[list[str], str, str]:
    normalized_url = normalize_url(base_url)
    root_html = fetch_html(normalized_url)
    detected_business_name = infer_company_name(normalized_url, root_html)
    links = get_all_links(normalized_url, max_paginas=max_paginas)

    all_text = ""
    for link in links:
        all_text += scrape_page(link)
        all_text += "\n---\n"

    return links, all_text, detected_business_name


def _build_info_prompt(
    all_text: str,
    nombre_bot_value: str,
    tono_value: str,
    idioma_value: str,
) -> str:
    return f"""
Eres un especialista en onboarding de asistentes IA para empresas.
Debes crear un `info.txt` extremadamente util para un sistema RAG de un chatbox comercial y de soporte.
Usa solo contenido verificable de la web.

Objetivo:
- Que la IA pueda responder bien sobre la empresa.
- Que la IA entienda servicios, contexto, procesos, diferenciacion, contacto y limites.
- Que el documento quede listo para vender, atender y captar leads sin inventar informacion.

Reglas:
- No inventes datos factuales.
- Si falta informacion, escribe "No especificado en la web".
- Si propones contenido util no confirmado literalmente, muevelo a "PREGUNTAS SUGERIDAS PARA REVISION HUMANA".
- Mantenn una estructura clara, operativa y facil de indexar por un sistema RAG.
- Prioriza datos concretos: servicios, precios, proceso comercial, contacto, horarios, ubicaciones, politicas y pruebas de autoridad.
- Evita parrafos largos; usa bloques claros y escaneables.
- Responde en {idioma_value}.

Usa exactamente esta estructura:

===== INFORMACION DE [NOMBRE DEL NEGOCIO] =====

DATOS GENERALES:
- Nombre:
- Tipo de negocio:
- Descripcion:
- Eslogan:

CONTACTO Y UBICACION:
- Direccion:
- Ciudad:
- Telefono:
- Email:
- Web:
- Instagram:
- Facebook:
- Google Maps:

HORARIOS:
- Lunes a Viernes:
- Sabados:
- Domingos:
- Notas:

SERVICIOS Y PRECIOS:
- Categoria:
  - Servicio:
  - Precio:
  - Detalle:

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

CONTENIDO FUENTE:
{all_text[:MODEL_CONTEXT_LIMIT]}
""".strip()


def generate_info(
    all_text: str,
    api_key: str,
    nombre_bot_value: str,
    tono_value: str,
    idioma_value: str,
    model: str = DEFAULT_ONBOARDING_MODEL,
) -> str:
    client = OpenAI(api_key=api_key)
    prompt = _build_info_prompt(all_text, nombre_bot_value, tono_value, idioma_value)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Genera documentos de onboarding fiables para asistentes empresariales. "
                    "Prioriza precision, estructura, cobertura comercial y utilidad operativa."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=5500,
    )

    return (response.choices[0].message.content or "").strip()


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
    links, all_text, detected_business_name = collect_site_content(website_url, max_paginas=max_paginas)
    info_txt = generate_info(
        all_text=all_text,
        api_key=api_key,
        nombre_bot_value=nombre_bot,
        tono_value=tono,
        idioma_value=idioma,
        model=model,
    )
    suggested_welcome = f"Hola, soy {nombre_bot}, el asistente de {detected_business_name}. En que puedo ayudarte hoy?"
    return OnboardingResult(
        normalized_url=normalize_url(website_url),
        links=links,
        all_text=all_text,
        info_txt=info_txt,
        detected_business_name=detected_business_name,
        suggested_welcome=suggested_welcome,
    )
