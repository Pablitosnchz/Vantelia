"""TikTok templates v2 - DMs naturales con tono casual.

Espejo de instagram_templates_v2 con tono ligeramente mas directo/cercano
(TikTok es plataforma mas casual). Mismas variantes A/B/C, mismos placeholders.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional


VARIANTS = ["A", "B", "C"]
PLACEHOLDERS_HELP = (
    "Placeholders disponibles: {business_name}, {city}, {niche}, {observed}, {you}. "
    "Usa \\n para saltos de linea."
)


def _clean_name(name: str) -> str:
    if not name:
        return ""
    s = name.strip()
    s = re.sub(r"\b(s\.?l\.?|s\.?a\.?|c\.?b\.?|inc\.?|ltd\.?)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip(" -·,.")
    return s[:60]


def pick_variant(username: str) -> str:
    h = hashlib.sha256((username or "").lower().encode("utf-8")).hexdigest()
    idx = int(h, 16) % len(VARIANTS)
    return VARIANTS[idx]


def _niche_short(niche: str) -> str:
    mapping = {
        "clinica dental": "clinica dental",
        "ortodoncia": "clinica de ortodoncia",
        "clinica estetica": "centro de estetica",
        "centro de estetica": "centro de estetica",
        "depilacion laser": "centro de depilacion",
        "fisioterapia": "centro de fisio",
        "centro de psicologia": "consulta de psicologia",
        "logopeda": "consulta de logopedia",
        "podologo": "consulta de podologia",
        "optica": "optica",
        "clinica veterinaria": "clinica veterinaria",
        "centro deportivo": "centro deportivo",
        "gimnasio": "gym",
        "estudio pilates": "estudio de pilates",
        "centro yoga": "estudio de yoga",
        "academia de ingles": "academia de ingles",
        "academia oposiciones": "academia de oposiciones",
        "autoescuela": "autoescuela",
        "escuela infantil": "escuela infantil",
        "academia danza": "academia de danza",
        "academia musica": "academia de musica",
        "taller mecanico": "taller mecanico",
        "restaurante": "restaurante",
        "cafeteria": "cafeteria",
        "barberia": "barberia",
        "peluqueria": "peluqueria",
        "centro de unas": "salon de unas",
        "joyeria": "joyeria",
        "floristeria": "floristeria",
        "inmobiliaria": "inmobiliaria",
        "asesoria fiscal": "asesoria",
        "asesoria laboral": "asesoria",
        "gestoria": "gestoria",
        "despacho abogados": "despacho de abogados",
        "agencia marketing digital": "agencia",
        "agencia de viajes": "agencia de viajes",
        "empresa de reformas": "empresa de reformas",
        "empresa de mudanzas": "empresa de mudanzas",
        "empresa de limpieza": "empresa de limpieza",
        "fontaneria": "empresa de fontaneria",
        "electricista": "empresa de electricidad",
        "cerrajeria": "cerrajeria",
        "carpinteria": "carpinteria",
        "clinica nutricion": "consulta de nutricion",
        "clinica capilar": "clinica capilar",
    }
    return mapping.get((niche or "").lower(), niche or "negocio")


def _load_override(variant: str, db_path: str) -> Optional[str]:
    try:
        import sqlite3
        with sqlite3.connect(db_path) as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS tk_dm_templates_v2 (
                    variant TEXT PRIMARY KEY,
                    body TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            row = c.execute("SELECT body FROM tk_dm_templates_v2 WHERE variant=?", (variant,)).fetchone()
            if row and row[0] and row[0].strip():
                return row[0]
    except Exception:
        return None
    return None


def render_natural(
    username: str,
    business_name: str = "",
    niche: str = "",
    city: str = "",
    variant: Optional[str] = None,
    db_path: Optional[str] = None,
) -> str:
    """Devuelve texto DM cold para este prospect en TikTok."""
    v = variant or pick_variant(username)
    name = _clean_name(business_name)
    short_niche = _niche_short(niche)
    city_clean = (city or "").strip()

    if name and len(name) >= 3:
        you = name
    else:
        you = "vosotros"

    if name and city_clean:
        observed = f"vuestro TikTok de {name} en {city_clean}"
    elif name:
        observed = f"vuestro TikTok de {name}"
    elif short_niche and city_clean:
        observed = f"vuestro TikTok de {short_niche} en {city_clean}"
    elif short_niche:
        observed = f"vuestro TikTok del {short_niche}"
    else:
        observed = "vuestro TikTok"

    # Override usuario
    if db_path:
        override = _load_override(v, db_path)
        if override:
            return (override
                    .replace("\\n", "\n")
                    .replace("{business_name}", name or "vosotros")
                    .replace("{city}", city_clean or "")
                    .replace("{niche}", short_niche or "negocio")
                    .replace("{observed}", observed)
                    .replace("{you}", you))

    if v == "A":
        p1 = f"Hola, soy Pablo de Vantelia."
        p2 = f"Estuve viendo {observed} esta mañana y queria escribirte directamente, sin guion."
        p3 = (
            f"Lo que hago es esto: un asistente IA que contesta los DMs y consultas de la web por vosotros "
            f"(suena como una persona, no como bot) y agenda las citas solo en vuestra agenda. "
            f"Pensado para que no se os escape ningun lead cuando no estais."
        )
        p4 = f"¿Te paso un video de 1 min enseñando como quedaria con {you}? Si no os encaja te dejo tranquilo. Sin compromiso."
        return f"{p1}\n\n{p2}\n\n{p3}\n\n{p4}"

    if v == "B":
        p1 = f"Hola! Soy Pablo, fundador de Vantelia."
        p2 = f"Me he topado con {observed} y me he quedado un rato mirandolo."
        p3 = (
            f"He montado un asistente IA pensado para negocios como {you}: contesta automaticamente "
            f"DMs y consultas web, filtra leads y agenda directamente las citas en vuestra agenda. "
            f"Lo estamos probando ya con varios {short_niche} y los resultados estan siendo buenos."
        )
        p4 = "¿Me das 2 minutos para enseñarte como quedaria con vosotros? Sin rollo comercial, prometido."
        return f"{p1}\n\n{p2}\n\n{p3}\n\n{p4}"

    # Variant C
    p1 = "Buenas, soy Pablo de Vantelia."
    p2 = f"Estuve viendo {observed} y queria escribirte sin rodeos."
    p3 = (
        f"Monto asistentes IA para negocios como {you}. La idea es sencilla: se encargan de los DMs "
        f"y consultas que llegan cuando no estais, responden como una persona y agendan las citas "
        f"directamente en vuestra agenda. Asi no perdeis clientes por tardar en contestar."
    )
    p4 = "Si te interesa, te grabo un video de 90 segundos enseñando como funcionaria con vosotros. Sin presion, lo ves y decides. ¿Te lo paso?"
    return f"{p1}\n\n{p2}\n\n{p3}\n\n{p4}"
