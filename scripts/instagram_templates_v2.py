"""Templates v2 — DMs naturales que no parecen IA.

Reglas:
- Frases cortas, casual, ES.
- Sin emojis, sin saludos formales, sin firma.
- Alguna abreviatura humana (q, x, dm, gestionais).
- Sin link en cold (link solo si responden).
- Variante A/B/C estable por hash(username) % 3.
- Personalizado con business_name, city, niche.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional


VARIANTS = ["A", "B", "C"]


def _clean_name(name: str) -> str:
    if not name:
        return ""
    s = name.strip()
    # Quita sufijos comerciales repetitivos.
    s = re.sub(r"\b(s\.?l\.?|s\.?a\.?|c\.?b\.?|inc\.?|ltd\.?)\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip(" -·,.")
    return s[:60]


def pick_variant(username: str) -> str:
    h = hashlib.sha256((username or "").lower().encode("utf-8")).hexdigest()
    idx = int(h, 16) % len(VARIANTS)
    return VARIANTS[idx]


def _niche_short(niche: str) -> str:
    n = (niche or "").lower().strip()
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
    return mapping.get(n, n or "negocio")


def render_natural(
    username: str,
    business_name: str = "",
    niche: str = "",
    city: str = "",
    variant: Optional[str] = None,
) -> str:
    """Devuelve el texto del DM cold para este prospect.

    Todas las variantes abren con "Soy Pablo de Vantelia" + referencia
    personal a algo del perfil. Tono cercano, sin pinta de bot.
    """
    v = variant or pick_variant(username)
    name = _clean_name(business_name)
    short_niche = _niche_short(niche)
    city_clean = (city or "").strip()

    # Referencia personal segun datos disponibles.
    if name and len(name) >= 3:
        you = name
    else:
        you = "vosotros"

    # Detalle concreto que justifica el "he visto vuestro perfil".
    if name and city_clean:
        observed = f"vuestro perfil de {name} en {city_clean}"
    elif name:
        observed = f"el perfil de {name}"
    elif short_niche and city_clean:
        observed = f"vuestro perfil de {short_niche} en {city_clean}"
    elif short_niche:
        observed = f"vuestro perfil del {short_niche}"
    else:
        observed = "vuestro perfil"

    if v == "A":
        p1 = f"Hola, soy Pablo de Vantelia. He visto {observed} y me ha gustado bastante lo que hacéis."
        p2 = (
            f"Os escribo porque trabajo con negocios como el vuestro montando "
            f"un asistente IA que responde DMs, consultas de la web y agenda citas "
            f"cuando no estáis. Funciona 24/7 y suena como una persona, no como un bot tipico."
        )
        p3 = (
            "¿Te interesa que te enseñe en 2 min cómo quedaría con "
            f"{you}? Es un demo rapido, sin compromiso ni nada por medio."
        )
        return f"{p1}\n\n{p2}\n\n{p3}"

    if v == "B":
        p1 = f"Hola! Soy Pablo, fundador de Vantelia. Me he topado con {observed} y me he quedado mirandolo un rato."
        if short_niche:
            mention = f"Veo que sois {short_niche}"
            if city_clean:
                mention += f" en {city_clean}"
            mention += ", y suelo trabajar con perfiles parecidos al vuestro."
        else:
            mention = "Me ha llamado la atencion lo que mostrais."
        p2 = (
            f"{mention} Lo que monto es un asistente IA que contesta los DMs y "
            f"consultas que os llegan fuera de horario, filtra leads y agenda citas sin que "
            f"tengais que estar pendientes."
        )
        p3 = "¿Te paso un demo de 2 min para que veas como funcionaria con vosotros? Si no os encaja, sin problema."
        return f"{p1}\n\n{p2}\n\n{p3}"

    # Variant C
    p1 = f"Hola, soy Pablo de Vantelia. He estado viendo {observed} y queria escribiros directamente sin rodeos."
    p2 = (
        f"Hago asistentes IA para negocios como {you}. La idea es sencilla: "
        f"contesta los DMs, mensajes de la web y consultas cuando no estais, "
        f"agenda las citas en vuestra agenda y os deja solo los leads que de verdad merecen la pena."
    )
    p3 = "Si os pica la curiosidad, os mando un demo de 2 min y lo veis vosotros mismos. Sin venta agresiva, prometido."
    return f"{p1}\n\n{p2}\n\n{p3}"
