"""Plantillas de DM para captacion Instagram de Vantelia.

Tono: minusculas, 1-2 frases breves, sin firma email. Emojis opcionales discretos.
Maximo 500 chars (IG corta DMs largos). Variante A/B estable por hash(username|stage).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from urllib.parse import quote, urlencode


MAX_DM_CHARS = 500


@dataclass
class IGProspect:
    username: str
    full_name: str = ""
    bio: str = ""
    business_category: str = ""
    niche: str = ""
    city: str = ""
    website: str = ""
    public_email: str = ""
    service_hint: str = ""

    @property
    def display_name(self) -> str:
        name = (self.full_name or "").strip().split(" ", 1)[0]
        return name or self.business_category or "equipo"

    @property
    def business_label(self) -> str:
        return (self.full_name or self.username or "").strip()


STAGE_ORDER = ["cold", "fu1", "fu2", "breakup"]


# Pools A/B por stage. Lowercase, sin "Hola Estimado", sin signos exclamacion gritones.

OPENERS_COLD_A = [
    "hola {first}, vi {biz} en ig",
    "hola {first}, sigo {biz} y se nota cuidado",
    "hola {first}, breve",
]

OPENERS_COLD_B = [
    "ey {first}, una idea para {biz}",
    "buenas {first}, 30 segundos",
    "hola {first}, va de {biz}",
]

OPENERS_FU1_A = [
    "hola otra vez {first}",
    "{first}, te dejo esto por aqui",
]

OPENERS_FU1_B = [
    "ey {first}, lo viste?",
    "{first}, vuelvo con esto",
]

OPENERS_FU2_A = [
    "{first}, ultima por aqui",
    "te dejo el ejemplo {first}",
]

OPENERS_FU2_B = [
    "{first}, mira como quedaria",
    "{first}, lo dejo preparado",
]

OPENERS_BREAKUP_A = [
    "{first}, cierro el hilo",
    "{first}, lo dejo por ahora",
]

OPENERS_BREAKUP_B = [
    "{first}, no insisto mas",
    "te dejo tranquilo {first}",
]


OPENER_POOLS_AB = {
    "cold":    {"A": OPENERS_COLD_A,    "B": OPENERS_COLD_B},
    "fu1":     {"A": OPENERS_FU1_A,     "B": OPENERS_FU1_B},
    "fu2":     {"A": OPENERS_FU2_A,     "B": OPENERS_FU2_B},
    "breakup": {"A": OPENERS_BREAKUP_A, "B": OPENERS_BREAKUP_B},
}


NICHE_HOOK = [
    (("clinica", "dental", "fisio", "salud", "podolog", "psico", "estet"),
     "monto un asistente IA que responde dudas y agenda citas, sin que tu equipo escriba lo mismo cada dia"),
    (("peluqueria", "barberia", "spa", "belleza"),
     "monto un asistente IA que coge reservas 24/7 y rellena huecos de agenda"),
    (("academia", "formacion", "curso", "escuela", "idiomas"),
     "monto un asistente IA que responde dudas de cursos, precios y plazas mientras dais clase"),
    (("restaurant", "bar", "cafeter", "hotel", "hostal"),
     "monto un asistente IA que coge reservas y responde dudas cuando esta el telefono ocupado"),
    (("abogad", "asesor", "gestor", "consultor"),
     "monto un asistente IA que filtra primeras consultas y agenda solo las que encajan"),
    (("inmobiliaria", "alquiler"),
     "monto un asistente IA que filtra interesados y agenda visitas reales, sin perder leads"),
    (("autoescuela",),
     "monto un asistente IA que informa de precios, planes y horarios fuera de oficina"),
    (("taller", "reforma", "fontan", "electric", "cerraj", "repar"),
     "monto un asistente IA que filtra leads, pide fotos y recoge datos antes de la llamada"),
    (("gimnasio", "crossfit", "yoga", "pilates"),
     "monto un asistente IA que coge altas, responde sobre clases y rellena huecos"),
]


DEFAULT_HOOK = "monto un asistente IA que responde dudas y capta clientes mientras no estais"


def niche_hook(p: IGProspect) -> str:
    blob = f"{p.niche} {p.business_category} {p.bio} {p.service_hint}".lower()
    for keys, hook in NICHE_HOOK:
        if any(k in blob for k in keys):
            return hook
    return DEFAULT_HOOK


def stable_pick(seed: str, options: list[str]) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return options[int(digest, 16) % len(options)]


def assign_variant(username: str, stage: str) -> str:
    digest = hashlib.sha256(f"{username}|{stage}".encode("utf-8")).hexdigest()
    return "A" if int(digest, 16) % 2 == 0 else "B"


def pick_opener(stage: str, p: IGProspect) -> tuple[str, str]:
    pools = OPENER_POOLS_AB.get(stage)
    if not pools:
        raise ValueError(f"Stage desconocido: {stage}")
    variant = assign_variant(p.username, stage)
    pool = pools.get(variant) or pools["A"]
    template = stable_pick(f"{p.username}|{stage}|{variant}", pool)
    return template.format(first=p.display_name, biz=p.business_label), variant


def make_demo_slug(username: str, full_name: str = "") -> str:
    """Slug determinista compatible con sistema demo existente.

    Espejo de make_demo_slug en outreach pero con username como semilla
    (no hay email). Misma forma: {slug-biz}-{hash6}.
    """
    seed = f"ig:{(username or '').lower().strip()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:6]
    base = (full_name or username or "").lower().strip()
    safe = "".join(c if c.isalnum() or c == "-" else "-" for c in base).strip("-")
    safe = "-".join(filter(None, safe.split("-")))[:40] or "demo"
    return f"{safe}-{digest}"


def demo_url(stage: str, p: IGProspect) -> str:
    base = os.getenv("OUTREACH_DEMO_BASE_URL", "").strip().rstrip("/")
    if not base:
        base = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    if not base:
        base = "https://app.vantelia.es"
    slug = make_demo_slug(p.username, p.full_name)
    params = {
        "utm_source": "instagram",
        "utm_medium": "dm",
        "utm_campaign": f"ig_{stage}",
    }
    return f"{base}/d/{slug}?{urlencode(params)}"


def fallback_cta_url() -> str:
    return os.getenv("OUTREACH_CALENDAR_URL", "").strip()


# ----------------------- Renderers -----------------------


def _truncate(text: str, limit: int = MAX_DM_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def render_cold(p: IGProspect) -> tuple[str, str]:
    opener, variant = pick_opener("cold", p)
    hook = niche_hook(p)
    cta = demo_url("cold", p)
    body = f"{opener}. {hook}. te he preparado una demo personalizada, mira: {cta}"
    return _truncate(body), variant


def render_fu1(p: IGProspect) -> tuple[str, str]:
    opener, variant = pick_opener("fu1", p)
    cta = demo_url("fu1", p)
    body = f"{opener}. por si no lo viste, te dejo la demo que prepare para {p.business_label}: {cta}"
    return _truncate(body), variant


def render_fu2(p: IGProspect) -> tuple[str, str]:
    opener, variant = pick_opener("fu2", p)
    cta = demo_url("fu2", p)
    body = f"{opener}. ultimo intento. ejemplo concreto de como quedaria en {p.business_label}: {cta}"
    return _truncate(body), variant


def render_breakup(p: IGProspect) -> tuple[str, str]:
    opener, variant = pick_opener("breakup", p)
    body = f"{opener}. si en otro momento te interesa, escribeme por aqui y lo preparo."
    return _truncate(body), variant


RENDERERS = {
    "cold": render_cold,
    "fu1": render_fu1,
    "fu2": render_fu2,
    "breakup": render_breakup,
}


def render(stage: str, p: IGProspect) -> tuple[str, str]:
    """Devuelve (texto_dm, variante_AB)."""
    if stage not in RENDERERS:
        raise ValueError(f"Stage desconocido: {stage}")
    return RENDERERS[stage](p)


# ----------------------- Deep link IG -----------------------


def igme_deep_link(username: str, message: str) -> str:
    """Construye link ig.me/m/{user}?text=... para envio manual 1-clic."""
    user = (username or "").strip().lstrip("@")
    return f"https://ig.me/m/{quote(user, safe='')}?text={quote(message, safe='')}"
