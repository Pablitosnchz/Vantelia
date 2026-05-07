"""Plantillas de email y logica de personalizacion para la captacion de Vantelia.

Cada stage es una etapa de la secuencia. Devuelve (subject, text, html).
Se mantiene fuera de outreach_campaign.py para poder iterar el copy
sin tocar la logica de envio.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html as html_lib
import os
import re
import secrets
from dataclasses import dataclass
from urllib.parse import quote


@dataclass
class Prospect:
    email: str
    business_name: str
    contact_name: str = ""
    niche: str = ""
    website: str = ""
    service_hint: str = ""
    city: str = "Torrejon de Ardoz"
    phone: str = ""
    tags: str = ""
    source: str = ""

    @property
    def first_name(self) -> str:
        return (self.contact_name or "").strip().split(" ", 1)[0]

    @property
    def greeting(self) -> str:
        return f"Hola {self.first_name}," if self.first_name else "Hola,"


NICHE_VALUE = [
    (
        ("clinica", "clínica", "estet", "dental", "fisio", "salud", "podolog", "psico"),
        "responder dudas sobre servicios, horarios y primera cita",
        "convertir mas visitas web en solicitudes de cita reales",
        "el 60% de pacientes preguntan fuera del horario de recepcion",
    ),
    (
        ("academia", "formacion", "formación", "curso", "escuela", "idiomas"),
        "resolver dudas sobre cursos, plazas, horarios y precios",
        "captar matriculas sin que el equipo conteste lo mismo cada dia",
        "muchas academias pierden alumnos por no contestar a tiempo",
    ),
    (
        ("reforma", "taller", "fontan", "electric", "albañil", "carpinter", "cerraj"),
        "filtrar consultas, pedir fotos y recoger datos antes de llamar",
        "recibir leads ya cualificados y ahorrar llamadas que no cierran",
        "los gremios pierden trabajos por no responder rapido al primer mensaje",
    ),
    (
        ("inmobiliaria", "inmobil", "alquiler"),
        "filtrar interesados, recoger preferencias y agendar visitas",
        "concentrar al equipo solo en visitas con intencion real",
        "el primer agente que responde se queda con la visita el 78% de las veces",
    ),
    (
        ("restaurant", "bar", "cafeter", "hotel", "hostal"),
        "responder dudas frecuentes y gestionar reservas",
        "no perder reservas cuando el telefono esta ocupado",
        "una reserva perdida es una mesa vacia esa noche",
    ),
    (
        ("abogad", "asesor", "gestor", "consultor"),
        "filtrar consultas iniciales y agendar primera reunion",
        "dedicar tu tiempo solo a clientes que encajan",
        "la mayoria de bufetes pierden 1 de cada 3 consultas por tardar en responder",
    ),
    (
        ("autoescuela", "auto-escuela"),
        "informar sobre precios, planes y horarios de practicas",
        "captar matriculas mientras el equipo da clase",
        "las consultas llegan en franja de tarde cuando la oficina ya cerro",
    ),
    (
        ("peluqueria", "peluquería", "barberia", "barbería", "estetica", "estética", "spa"),
        "gestionar reservas, dudas de servicios y precios",
        "llenar huecos de agenda y reducir no-shows",
        "los clientes reservan a las 22h cuando ya cerrasteis",
    ),
]

DEFAULT_TASK = "responder preguntas frecuentes y recoger solicitudes de informacion"
DEFAULT_OUTCOME = "no perder oportunidades cuando no podeis atender"
DEFAULT_PROOF = "la mayoria de leads se pierden por no contestar en la primera hora"


def niche_copy(niche: str, service_hint: str = "") -> tuple[str, str, str]:
    blob = f"{niche} {service_hint}".lower()
    for keys, task, outcome, proof in NICHE_VALUE:
        if any(k in blob for k in keys):
            return task, outcome, proof
    return DEFAULT_TASK, DEFAULT_OUTCOME, DEFAULT_PROOF


def stable_pick(seed: str, options: list[str]) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return options[int(digest, 16) % len(options)]


def _personal_context(p: Prospect) -> str:
    parts = [p.city, p.niche, p.service_hint]
    clean_parts = [part.strip() for part in parts if part and part.strip()]
    return ", ".join(clean_parts)


def _personal_line_text(p: Prospect) -> str:
    if not p.business_name:
        return ""
    context = _personal_context(p)
    if context:
        return f"Sobre {p.business_name} ({context})."
    return f"Sobre {p.business_name}."


def _personal_line_html(p: Prospect) -> str:
    line = _personal_line_text(p)
    if not line:
        return ""
    return f'<p style="margin:0 0 12px 0;color:#4b5563;">{html_lib.escape(line)}</p>'

# Subjects en dos pools (A/B). Asignacion estable por hash(email).
# Tono: lowercase, breve, curiosidad. Evitar gatillos spam ("oferta", "gratis",
# "consulta rapida", signos de admiracion, mayusculas).

SUBJECTS_COLD_A = [
    "duda sobre {business}",
    "5 min, {first_or_team}?",
    "{business} y la web",
    "pregunta rapida {first_or_team}",
]

SUBJECTS_COLD_B = [
    "una idea para {business}",
    "{first_or_team}, esto encaja?",
    "{business} - una pregunta",
    "antes de cerrar la semana, {first_or_team}",
]

SUBJECTS_FU1_A = [
    "lo dejo aqui {first_or_team}",
    "re: {business}",
    "ultima por aqui",
]

SUBJECTS_FU1_B = [
    "{first_or_team}, lo viste?",
    "vuelvo con esto {first_or_team}",
    "{business} - sigue en pie",
]

SUBJECTS_FU2_A = [
    "ejemplo de 30 segundos para {business}",
    "{business} - mira esto",
]

SUBJECTS_FU2_B = [
    "te dejo el esquema {first_or_team}",
    "{business}: como quedaria",
]

SUBJECTS_BREAKUP_A = [
    "cierro el hilo",
    "{business}: lo dejo aqui",
]

SUBJECTS_BREAKUP_B = [
    "ultima vez, {first_or_team}",
    "te dejo tranquilo, {first_or_team}",
]

# Compatibilidad hacia atras: codigo antiguo importa SUBJECTS_*.
SUBJECTS_COLD = SUBJECTS_COLD_A + SUBJECTS_COLD_B
SUBJECTS_FU1 = SUBJECTS_FU1_A + SUBJECTS_FU1_B
SUBJECTS_FU2 = SUBJECTS_FU2_A + SUBJECTS_FU2_B
SUBJECTS_BREAKUP = SUBJECTS_BREAKUP_A + SUBJECTS_BREAKUP_B

SUBJECT_POOLS_AB = {
    "cold":    {"A": SUBJECTS_COLD_A,    "B": SUBJECTS_COLD_B},
    "fu1":     {"A": SUBJECTS_FU1_A,     "B": SUBJECTS_FU1_B},
    "fu2":     {"A": SUBJECTS_FU2_A,     "B": SUBJECTS_FU2_B},
    "breakup": {"A": SUBJECTS_BREAKUP_A, "B": SUBJECTS_BREAKUP_B},
}


def fmt_subject(template: str, p: Prospect) -> str:
    first_or_team = p.first_name or "equipo"
    return template.format(business=p.business_name, first_or_team=first_or_team)


def assign_variant(email: str, stage: str) -> str:
    """Asignacion A/B estable por hash(email|stage). Mismo prospect siempre
    recibe misma variante en ese stage (evita sesgar tests con re-envios)."""
    digest = hashlib.sha256(f"{email}|{stage}".encode("utf-8")).hexdigest()
    return "A" if int(digest, 16) % 2 == 0 else "B"


def pick_subject(stage: str, p: Prospect) -> str:
    """Compat: devuelve solo subject. Para tracking de variante usar pick_subject_with_variant."""
    subject, _variant = pick_subject_with_variant(stage, p)
    return subject


def pick_subject_with_variant(stage: str, p: Prospect) -> tuple[str, str]:
    pools = SUBJECT_POOLS_AB.get(stage)
    if not pools:
        raise ValueError(f"Stage desconocido: {stage}")
    variant = assign_variant(p.email, stage)
    pool = pools.get(variant) or pools["A"]
    template = stable_pick(p.email + "|" + stage + "|" + variant, pool)
    return fmt_subject(template, p), variant


SIGNATURE_TEXT = (
    "Pablo Sanchez\n"
    "Vantelia\n"
    "https://www.vantelia.es\n"
)


def signature_html(stage: str) -> str:
    # Firma plana tipo email humano: sin tablas, sin gradientes, sin UTMs.
    return (
        '<p style="margin:18px 0 0 0;">'
        'Un saludo,<br>'
        'Pablo Sanchez<br>'
        'Vantelia &middot; <a href="https://www.vantelia.es">vantelia.es</a>'
        '</p>'
    )


DEMO_REPLY_SUBJECT = "Demo gratuita Vantelia"
DEMO_REPLY_BODY = (
    "Buenas,\n\n"
    "Me interesa. Preparame la demo gratuita sin compromiso.\n\n"
    "Gracias."
)


def demo_reply_mailto(to_email: str | None = None) -> str:
    recipient = (
        (to_email or "").strip()
        or os.getenv("OUTREACH_REPLY_TO", "").strip()
        or os.getenv("SMTP_REPLY_TO", "").strip()
        or "info@vantelia.es"
    )
    return (
        f"mailto:{recipient}"
        f"?subject={quote(DEMO_REPLY_SUBJECT, safe='')}"
        f"&body={quote(DEMO_REPLY_BODY, safe='')}"
    )


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, fallback: str = "demo", max_len: int = 30) -> str:
    base = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    if not base:
        return fallback
    return base[:max_len].strip("-") or fallback


def make_demo_slug(email: str, business_name: str) -> str:
    """Slug deterministico para URL demo personalizada.

    Formato: {slug-empresa}-{hash6} donde hash6 = sha256(email)[:6].
    Determinista: misma entrada => misma salida (sin necesidad de DB).
    """
    slug_part = slugify(business_name)
    h = hashlib.sha256((email or "").lower().encode("utf-8")).hexdigest()[:6]
    return f"{slug_part}-{h}"


def demo_url_for(p: Prospect) -> str:
    base = os.getenv("OUTREACH_DEMO_BASE_URL", "").strip().rstrip("/")
    if not base:
        base = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/d/{make_demo_slug(p.email, p.business_name)}"


def booking_url_for(p: Prospect) -> str:
    """Devuelve URL para agendar 15 min. Prioriza booking interno de Vantelia
    (apunta a /d/{slug}#agenda donde vive el modulo de reservas), si no
    `OUTREACH_CALENDAR_URL` externo, si no vacio.
    """
    if os.getenv("OUTREACH_BOOKING_CLIENTE_ID", "").strip():
        demo = demo_url_for(p)
        if demo:
            return f"{demo}#agenda"
    return os.getenv("OUTREACH_CALENDAR_URL", "").strip()


def calendar_url() -> str:
    """Compat: ahora alias de booking_url_for sin contexto. Vacio si no hay
    booking interno ni OUTREACH_CALENDAR_URL.
    """
    return os.getenv("OUTREACH_CALENDAR_URL", "").strip()


def cta_button_html(text: str, href: str | None = None) -> str:
    # Boton CTA con degradado Vantelia, estilo compatible con clientes de email.
    safe_text = html_lib.escape(text)
    safe_href = html_lib.escape(href or demo_reply_mailto(), quote=True)
    return (
        '<table role="presentation" cellspacing="0" cellpadding="0" style="margin:14px 0;">'
        '<tr>'
        '<td style="border-radius:999px; background:#00D1FF; '
        'background:linear-gradient(135deg,#00D1FF,#00F5D4); '
        'box-shadow:0 10px 26px rgba(0,209,255,0.28);">'
        f'<a href="{safe_href}" '
        'style="display:inline-block;padding:12px 22px;border-radius:999px;'
        'color:#04101C;font-size:14px;font-weight:700;text-decoration:none;'
        'font-family:Arial,Helvetica,sans-serif;">'
        f'{safe_text}'
        '</a>'
        '</td>'
        '</tr>'
        '</table>'
    )


def footer_text(unsubscribe_mailto: str) -> str:
    # Footer minimo sin linea de baja. Las menciones legales completas se incluyen
    # solo si OUTREACH_LEGAL_FOOTER=true (se activa con volumen alto).
    legal = (
        "Tratamos tus datos solo para este contacto comercial. Responsable: Vantelia. "
        "Base legal: interes legitimo (LSSI/RGPD).\n"
    )
    if os.getenv("OUTREACH_LEGAL_FOOTER", "").lower() in ("1", "true", "yes"):
        return "\n--\n" + legal
    return ""


def footer_html(unsubscribe_mailto: str) -> str:
    if os.getenv("OUTREACH_LEGAL_FOOTER", "").lower() in ("1", "true", "yes"):
        return (
            '<p style="margin:18px 0 0 0;font-size:12px;color:#666;">'
            'Tratamos tus datos solo para este contacto comercial. Responsable: Vantelia. '
            'Base legal: interes legitimo (LSSI/RGPD).'
            '</p>'
        )
    return ""


def html_shell(inner_html: str, preheader: str = "") -> str:
    pre = ""
    if preheader:
        pre = (
            '<div style="display:none;font-size:1px;color:#f6f8fb;line-height:1px;'
            'max-height:0;max-width:0;opacity:0;overflow:hidden;">'
            f'{html_lib.escape(preheader)}'
            '</div>'
        )
    # Email plano tipo correo humano: sin card, sin logo grafico, sin marketing chrome.
    # Gmail clasifica como Promociones cuando ve tablas anidadas, gradientes, botones grandes.
    return (
        '<!doctype html><html lang="es"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '</head>'
        '<body style="margin:0;padding:16px;font-family:Arial,Helvetica,sans-serif;'
        'font-size:14px;line-height:1.5;color:#222;">'
        f'{pre}'
        f'<div style="max-width:560px;">{inner_html}</div>'
        '</body></html>'
    )


def _proof_line() -> str:
    """Proof concreto opcional. Si OUTREACH_PROOF_LINE esta definido, se incluye
    en cold como ultima frase de credibilidad. Vacio = sin proof.

    Ejemplo en .env:
      OUTREACH_PROOF_LINE=Lo monte para Clinica Dental Sonrisa (Madrid). Reciben 22 consultas a la semana sin tocar nada.
    """
    return os.getenv("OUTREACH_PROOF_LINE", "").strip()


def _booking_minutes() -> int:
    """Duracion en minutos para copy del CTA secundario. Override via env
    OUTREACH_BOOKING_MINUTES; default 15."""
    raw = os.getenv("OUTREACH_BOOKING_MINUTES", "").strip()
    try:
        return int(raw) if raw else 15
    except ValueError:
        return 15


def _cta_block(p: Prospect, primary_text: str, fallback_text: str) -> tuple[str, str]:
    """Devuelve (text_cta, html_cta). Si hay demo URL la usa como CTA principal.
    El secundario apunta al booking interno de Vantelia (anchor #agenda dentro
    de la propia demo) si OUTREACH_BOOKING_CLIENTE_ID esta configurado, si no
    a OUTREACH_CALENDAR_URL externo. Sin ninguna URL recae en mailto."""
    demo = demo_url_for(p)
    book = booking_url_for(p)
    minutes = _booking_minutes()
    text_lines: list[str] = []
    html_parts: list[str] = []
    if demo:
        text_lines.append(f"Demo personalizada para {p.business_name}: {demo}")
        html_parts.append(cta_button_html(primary_text, demo))
    if book and book != demo:
        text_lines.append(f"Si prefieres reservar {minutes} min directamente: {book}")
        # Enlace plano, sin degradado, para no parecer marketing duplicado.
        safe_book = html_lib.escape(book, quote=True)
        html_parts.append(
            f'<p style="margin:0 0 14px 0;font-size:14px;">'
            f'<a href="{safe_book}" style="color:#0B132B;border-bottom:1px solid #0B132B;text-decoration:none;">'
            f'Reservar {minutes} min</a></p>'
        )
    if not text_lines:
        html_parts.append(cta_button_html(fallback_text))
        text_lines.append("Responde a este correo y lo preparo.")
    return ("\n".join(text_lines), "".join(html_parts))


def render_cold(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    personal_line = _personal_line_text(p)
    personal_text = f"{personal_line}\n\n" if personal_line else ""
    proof = _proof_line()
    proof_text = f"{proof}\n\n" if proof else ""
    proof_html = (
        f'<p style="margin:0 0 14px 0;">{html_lib.escape(proof)}</p>' if proof else ""
    )
    subject, _variant = pick_subject_with_variant("cold", p)
    cta_text, cta_html = _cta_block(p, "Si, preparame la demo", "Si, preparame la demo")
    text = (
        f"{p.greeting}\n\n"
        f"{personal_text}"
        f"Soy Pablo, de Vantelia. Monto asistentes IA en web y WhatsApp para que "
        f"contesten preguntas frecuentes y recojan solicitudes 24/7, sin que tu "
        f"equipo escriba lo mismo cada dia.\n\n"
        f"{proof_text}"
        f"Te he preparado una demo adaptada a {p.business_name}.\n"
        f"{cta_text}\n\n"
        f"Si no encaja, dime con quien deberia hablar.\n\n"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )
    personal_html = _personal_line_html(p)
    inner = (
        f'<p>{html_lib.escape(p.greeting)}</p>'
        f'{personal_html}'
        f'<p>Soy Pablo, de Vantelia. Monto asistentes IA en web y WhatsApp para que '
        f'contesten preguntas frecuentes y recojan solicitudes 24/7, sin que tu '
        f'equipo escriba lo mismo cada dia.</p>'
        f'{proof_html}'
        f'<p>Te he preparado una demo adaptada a <strong>{html_lib.escape(p.business_name)}</strong>.</p>'
        f'{cta_html}'
        f'<p><strong>Si no encaja, dime con quien deberia hablar.</strong></p>'
        f'{signature_html("cold")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    return subject, text, html_shell(inner)


def render_fu1(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    personal_line = _personal_line_text(p)
    personal_text = f"{personal_line}\n\n" if personal_line else ""
    cta_text, cta_html = _cta_block(p, "Ver demo personalizada", "Si, preparame la demo")
    text = (
        f"{p.greeting}\n\n"
        f"{personal_text}"
        f"Te escribi hace unos dias. La demo que prepare para {p.business_name} sigue ahi.\n"
        f"{cta_text}\n\n"
        f"Si no es prioridad ahora, lo dejo aqui.\n\n"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )
    personal_html = _personal_line_html(p)
    inner = (
        f'<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{html_lib.escape(p.greeting)}</p>'
        f'{personal_html}'
        f'<p style="margin:0 0 14px 0;">Te escribi hace unos dias. La demo que prepare para '
        f'<strong>{html_lib.escape(p.business_name)}</strong> sigue ahi.</p>'
        f'{cta_html}'
        f'<p style="margin:0 0 6px 0;font-size:16px;color:#0B132B;">'
        f'<strong>Si no es prioridad ahora, lo dejo aqui.</strong></p>'
        f'{signature_html("fu1")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    preheader = f"Seguimiento breve para {p.business_name}."
    return pick_subject("fu1", p), text, html_shell(inner, preheader=preheader)


def render_fu2(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    personal_line = _personal_line_text(p)
    personal_text = f"{personal_line}\n\n" if personal_line else ""
    cta_text, cta_html = _cta_block(p, "Ver demo personalizada", "Si, preparame la demo")
    text = (
        f"{p.greeting}\n\n"
        f"{personal_text}"
        f"Te dejo un ejemplo rapido de lo que solemos montar: preguntas frecuentes + "
        f"captura de datos + derivacion a la persona adecuada.\n\n"
        f"Lo tienes adaptado a {p.business_name} aqui:\n"
        f"{cta_text}\n\n"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )
    personal_html = _personal_line_html(p)
    inner = (
        f'<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{html_lib.escape(p.greeting)}</p>'
        f'{personal_html}'
        f'<p style="margin:0 0 14px 0;">Te dejo un ejemplo rapido de lo que solemos montar: '
        f'preguntas frecuentes + captura de datos + derivacion a la persona adecuada.</p>'
        f'<p style="margin:0 0 6px 0;font-size:16px;color:#0B132B;">'
        f'<strong>Lo tienes adaptado a {html_lib.escape(p.business_name)} aqui:</strong></p>'
        f'{cta_html}'
        f'{signature_html("fu2")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    preheader = f"Ejemplo rapido para {p.business_name}."
    return pick_subject("fu2", p), text, html_shell(inner, preheader=preheader)


def render_breakup(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    personal_line = _personal_line_text(p)
    personal_text = f"{personal_line}\n\n" if personal_line else ""
    text = (
        f"{p.greeting}\n\n"
        f"{personal_text}"
        f"Lo dejo por ahora para no insistir. Si en otro momento te interesa, "
        f"responde a este correo y lo preparo.\n\n"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )
    personal_html = _personal_line_html(p)
    inner = (
        f'<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{html_lib.escape(p.greeting)}</p>'
        f'{personal_html}'
        f'<p style="margin:0 0 14px 0;">Lo dejo por ahora para no insistir. '
        f'Si en otro momento te interesa, responde a este correo y lo preparo.</p>'
        f'{signature_html("breakup")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    preheader = f"Cierro el hilo por ahora, {p.first_name or 'equipo'}."
    return pick_subject("breakup", p), text, html_shell(inner, preheader=preheader)


RENDERERS = {
    "cold": render_cold,
    "fu1": render_fu1,
    "fu2": render_fu2,
    "breakup": render_breakup,
}

STAGE_ORDER = ["cold", "fu1", "fu2", "breakup"]


def render(stage: str, p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    if stage not in RENDERERS:
        raise ValueError(f"Stage desconocido: {stage}")
    return RENDERERS[stage](p, unsubscribe_mailto)


# ----------------------- Tracking (opens + clicks) -----------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def make_tracking_token(email: str, stage: str, secret: str) -> str:
    nonce = secrets.token_urlsafe(6)
    payload = f"{email}|{stage}|{nonce}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()[:16]
    return f"{_b64url(payload)}.{_b64url(sig)}"


def verify_tracking_token(token: str, secret: str) -> tuple[str, str] | None:
    """Devuelve (email, stage) si el token es valido."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _b64url_decode(payload_b64)
        sig = _b64url_decode(sig_b64)
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        parts = payload.decode("utf-8").split("|")
        if len(parts) < 2:
            return None
        return parts[0].lower(), parts[1]
    except Exception:
        return None


_TRACKABLE_HREF = re.compile(r'href=(["\'])(https?://[^"\']+)(["\'])', re.IGNORECASE)
_REPLY_MAILTO_HREF = re.compile(r'href=(["\'])(mailto:[^"\']+)(["\'])', re.IGNORECASE)


def apply_tracking(html_body: str, email: str, stage: str, base_url: str, secret: str) -> str:
    """Inyecta pixel de apertura y reescribe links externos para tracking de clicks."""
    if not base_url or not secret:
        return html_body
    base = base_url.rstrip("/")
    token = make_tracking_token(email, stage, secret)

    def _rewrite(match: re.Match[str]) -> str:
        quote_char, url, end_quote = match.group(1), match.group(2), match.group(3)
        # No reescribir el propio dominio de tracking ni mailto/anchors
        if base in url:
            return match.group(0)
        wrapped = f"{base}/track/click/{token}?u={quote(url, safe='')}"
        return f"href={quote_char}{wrapped}{end_quote}"

    def _rewrite_reply(match: re.Match[str]) -> str:
        quote_char, url, end_quote = match.group(1), match.group(2), match.group(3)
        wrapped = f"{base}/track/reply/{token}?u={quote(html_lib.unescape(url), safe='')}"
        return f"href={quote_char}{wrapped}{end_quote}"

    rewritten = _TRACKABLE_HREF.sub(_rewrite, html_body)
    rewritten = _REPLY_MAILTO_HREF.sub(_rewrite_reply, rewritten)
    pixel = (
        f'<img src="{base}/track/open/{token}.gif" '
        f'width="1" height="1" alt="" '
        f'style="display:block;border:0;width:1px;height:1px;" />'
    )
    if "</body>" in rewritten:
        return rewritten.replace("</body>", f"{pixel}</body>")
    return rewritten + pixel
