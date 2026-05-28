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
    """Devuelve el texto del DM cold para este prospect."""
    v = variant or pick_variant(username)
    name = _clean_name(business_name)
    short_niche = _niche_short(niche)
    city_clean = (city or "").strip()

    # Frase de apertura segun lo que tengamos.
    if name and len(name) >= 3:
        ref = name
    elif short_niche:
        ref = f"vuestro {short_niche}"
    else:
        ref = "vuestra cuenta"

    if v == "A":
        line1 = f"hey, vi {ref}"
        if city_clean:
            line1 += f" por {city_clean}"
        line2 = "tengo curiosidad, ¿quien os contesta los dms y consultas cuando estais a tope o fuera de horario?"
        line3 = "monto un asistente IA que responde 24/7, agenda citas y filtra leads. lo uso ya con clinicas y centros parecidos al vuestro y les esta ayudando bastante."
        line4 = "si te interesa te paso un demo de 2 min, sin compromiso. y si no, sin problema."
        return f"{line1}\n\n{line2}\n\n{line3}\n\n{line4}"

    if v == "B":
        opener = f"hola, soy pablo"
        if city_clean:
            opener += f". paso por {city_clean} estos dias y vi {ref}"
        else:
            opener += f". vi {ref} y me llamo la atencion"
        line2 = f"¿como gestionais las consultas que llegan por dm o web fuera de horario? muchos {short_niche or 'negocios'} con buen volumen pierden citas por no contestar a tiempo."
        line3 = "hago una herramienta IA que se encarga de eso. responde como una persona y agenda en vuestra agenda. ¿te mando un demo rapido?"
        return f"{opener}.\n\n{line2}\n\n{line3}"

    # Variant C
    opener = f"buenas, equipo de {name if name else (short_niche or 'la cuenta')}"
    line2 = "una duda: ¿cuantas consultas se os escapan por no responder rapido? lo digo xq estoy haciendo un asistente IA para negocios pequenos que contesta dms, agenda citas y no se le escapa ningun lead."
    line3 = "si quieres te ensenyo en 2 min como funcionaria con vosotros. nada de venta agresiva, solo enseñarlo."
    return f"{opener},\n\n{line2}\n\n{line3}"
