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
from urllib.parse import quote, urlencode


@dataclass
class Prospect:
    email: str
    business_name: str
    contact_name: str = ""
    niche: str = ""
    website: str = ""
    service_hint: str = ""
    city: str = ""
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


# Subjects en dos pools realmente distintos. La variante se asigna una sola vez
# por email y se conserva durante toda la secuencia.

SUBJECTS_COLD_A = [
    "¿te paso una idea para {business}?",
    "una idea sencilla para {business}",
]

SUBJECTS_COLD_B = [
    "{business}: una duda sobre la web",
    "una pregunta sobre {business}",
]

SUBJECTS_FU1_A = [
    "el ejemplo para {business}",
    "re: idea para {business}",
]

SUBJECTS_FU1_B = [
    "una pregunta real en {business}",
    "cómo valorar la idea",
]

SUBJECTS_FU2_A = [
    "¿es prioridad ahora en {business}?",
    "solo una confirmación",
]

SUBJECTS_FU2_B = [
    "¿quién lleva esto en {business}?",
    "la persona adecuada en {business}",
]

SUBJECTS_BREAKUP_A = [
    "cierro por aquí",
    "lo dejamos aquí",
]

SUBJECTS_BREAKUP_B = [
    "no te escribo más sobre esto",
    "gracias por leerme",
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


OUTREACH_COPY_BUNDLE_VERSION = "2026-08-human-replies-v1"

# Estas plantillas son tambien la fuente del bundle que migra los overrides de
# produccion. Solo usan variables que el renderer de overrides ya conoce.
OUTREACH_COPY_VARIANTS = {
    "cold": {
        "A": {
            "body_text": (
                "{greeting}\n\n"
                "Soy Pablo, de Vantelia. Te escribo por {business}. Ayudamos a responder "
                "las consultas que llegan desde la web cuando el equipo está ocupado.\n\n"
                "¿Quieres que te prepare y pase un enlace para verlo con vuestro caso? "
                "Responde sí o no.\n\n"
                "Pablo\nVantelia\n{footer_text}"
            ),
            "body_html": (
                "<p>{greeting}</p>"
                "<p>Soy Pablo, de Vantelia. Te escribo por {business}. Ayudamos a responder "
                "las consultas que llegan desde la web cuando el equipo está ocupado.</p>"
                "<p>¿Quieres que te prepare y pase un enlace para verlo con vuestro caso? "
                "Responde <strong>sí</strong> o <strong>no</strong>.</p>"
                "{signature_html}{footer_html}"
            ),
        },
        "B": {
            "body_text": (
                "{greeting}\n\n"
                "Al ver {business}, me surgió una duda: ¿las consultas que llegan por la web "
                "se quedan esperando cuando no podéis atender?\n\n"
                "Estoy probando una forma sencilla de cubrir ese hueco. ¿Te paso un enlace "
                "adaptado a {business}? Responde 1 = sí / 2 = no.\n\n"
                "Pablo\nVantelia\n{footer_text}"
            ),
            "body_html": (
                "<p>{greeting}</p>"
                "<p>Al ver {business}, me surgió una duda: ¿las consultas que llegan por la web "
                "se quedan esperando cuando no podéis atender?</p>"
                "<p>Estoy probando una forma sencilla de cubrir ese hueco. ¿Te paso un enlace "
                "adaptado a {business}? Responde <strong>1 = sí</strong> / <strong>2 = no</strong>.</p>"
                "{signature_html}{footer_html}"
            ),
        },
    },
    "fu1": {
        "A": {
            "body_text": (
                "{greeting}\n\n"
                "Retomo esto una vez. Aquí puedes probar cómo podría responder un asistente "
                "con la información disponible de {business}:\n{cta_url}\n\n"
                "La idea es resolver una consulta sencilla aunque estéis ocupados. "
                "¿Te encaja? Responde sí o no.\n\n"
                "Pablo\nVantelia\n{footer_text}"
            ),
            "body_html": (
                "<p>{greeting}</p>"
                "<p>Retomo esto una vez. Aquí puedes probar cómo podría responder un asistente "
                "con la información disponible de {business}:</p>"
                "<p><a href=\"{cta_url}\">Probar una demo para {business}</a></p>"
                "<p>La idea es resolver una consulta sencilla aunque estéis ocupados. "
                "¿Te encaja? Responde <strong>sí</strong> o <strong>no</strong>.</p>"
                "{signature_html}{footer_html}"
            ),
        },
        "B": {
            "body_text": (
                "{greeting}\n\n"
                "Para valorar la idea sin una reunión, prueba en este enlace una pregunta real "
                "que os haga un cliente:\n{cta_url}\n\n"
                "Así puedes ver si evita una respuesta repetitiva en {business}. "
                "¿Lo revisamos? Responde 1 = sí / 2 = no.\n\n"
                "Pablo\nVantelia\n{footer_text}"
            ),
            "body_html": (
                "<p>{greeting}</p>"
                "<p>Para valorar la idea sin una reunión, prueba en este enlace una pregunta real "
                "que os haga un cliente:</p>"
                "<p><a href=\"{cta_url}\">Probar una pregunta</a></p>"
                "<p>Así puedes ver si evita una respuesta repetitiva en {business}. "
                "¿Lo revisamos? Responde <strong>1 = sí</strong> / <strong>2 = no</strong>.</p>"
                "{signature_html}{footer_html}"
            ),
        },
    },
    "fu2": {
        "A": {
            "body_text": (
                "{greeting}\n\n"
                "Solo necesito saber si mejorar la respuesta de las consultas web es una "
                "prioridad ahora en {business}.\n\n"
                "Responde 1 y te indico el siguiente paso; responde 2 y cierro el tema.\n\n"
                "Pablo\nVantelia\n{footer_text}"
            ),
            "body_html": (
                "<p>{greeting}</p>"
                "<p>Solo necesito saber si mejorar la respuesta de las consultas web es una "
                "prioridad ahora en {business}.</p>"
                "<p>Responde <strong>1</strong> y te indico el siguiente paso; responde "
                "<strong>2</strong> y cierro el tema.</p>"
                "{signature_html}{footer_html}"
            ),
        },
        "B": {
            "body_text": (
                "{greeting}\n\n"
                "¿Eres tú quien decide cómo se atienden las consultas digitales en {business}?\n\n"
                "Responde 1 si lo vemos contigo / 2 si debo escribir a otra persona. "
                "Si es otra persona, puedes indicarme quién.\n\n"
                "Pablo\nVantelia\n{footer_text}"
            ),
            "body_html": (
                "<p>{greeting}</p>"
                "<p>¿Eres tú quien decide cómo se atienden las consultas digitales en {business}?</p>"
                "<p>Responde <strong>1</strong> si lo vemos contigo / <strong>2</strong> si debo "
                "escribir a otra persona. Si es otra persona, puedes indicarme quién.</p>"
                "{signature_html}{footer_html}"
            ),
        },
    },
    "breakup": {
        "A": {
            "body_text": (
                "{greeting}\n\n"
                "Cierro el hilo por aquí. Gracias por leerme.\n\n"
                "Si más adelante quieres retomarlo, responde a este correo y te paso el enlace.\n\n"
                "Pablo\nVantelia\n{footer_text}"
            ),
            "body_html": (
                "<p>{greeting}</p>"
                "<p>Cierro el hilo por aquí. Gracias por leerme.</p>"
                "<p>Si más adelante quieres retomarlo, responde a este correo y te paso el enlace.</p>"
                "{signature_html}{footer_html}"
            ),
        },
        "B": {
            "body_text": (
                "{greeting}\n\n"
                "No te escribo más sobre esto.\n\n"
                "Si en otro momento encaja para {business}, responde sí y lo retomamos; "
                "si no, no hace falta hacer nada.\n\n"
                "Pablo\nVantelia\n{footer_text}"
            ),
            "body_html": (
                "<p>{greeting}</p>"
                "<p>No te escribo más sobre esto.</p>"
                "<p>Si en otro momento encaja para {business}, responde <strong>sí</strong> y lo "
                "retomamos; si no, no hace falta hacer nada.</p>"
                "{signature_html}{footer_html}"
            ),
        },
    },
}


def fmt_subject(template: str, p: Prospect) -> str:
    first_or_team = p.first_name or "equipo"
    return template.format(business=p.business_name, first_or_team=first_or_team)


def assign_variant(email: str, stage: str = "") -> str:
    """Asigna A/B de forma estable por prospecto durante toda la secuencia.

    ``stage`` se conserva en la firma por compatibilidad con llamadas antiguas,
    pero no participa en el hash.
    """
    normalized_email = (email or "").strip().lower()
    digest = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()
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


VANTELIA_SIGNATURE = {
    "sender_name": "Pablo",
    "sender_role": "Fundador, Vantelia",
    "company_name": "Vantelia",
    "phone": "+34 675 802 001",
    "phone_href": "+34675802001",
    "email": "info@vantelia.es",
    "website": "https://vantelia.es",
    "website_label": "vantelia.es",
    "address": "Calle Garabay 7, Torrejon de Ardoz, 28850 Madrid",
    "logo_url": os.getenv(
        "VANTELIA_EMAIL_LOGO_URL",
        "https://app.vantelia.es/brand-assets/Logo_Letra.png",
    ).strip() or "https://app.vantelia.es/brand-assets/Logo_Letra.png",
}


SIGNATURE_TEXT = (
    f"{VANTELIA_SIGNATURE['sender_name']}\n"
    f"{VANTELIA_SIGNATURE['sender_role']}\n"
    f"{VANTELIA_SIGNATURE['phone']} · {VANTELIA_SIGNATURE['email']}\n"
    f"{VANTELIA_SIGNATURE['website']}\n"
)


def signature_html(stage: str) -> str:
    s = VANTELIA_SIGNATURE
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="width:100%;max-width:560px;margin-top:20px;border-top:2px solid #e5e7eb;'
        'padding-top:16px;font-family:Arial,Helvetica,sans-serif;">'
        '<tr><td style="padding-bottom:10px;">'
        f'<img src="{html_lib.escape(s["logo_url"], quote=True)}" '
        f'alt="{html_lib.escape(s["company_name"], quote=True)}" '
        'style="display:block;max-width:120px;height:auto;border:0;">'
        '</td></tr>'
        '<tr><td style="font-size:14px;line-height:1.7;color:#1f2937;">'
        f'<strong style="font-size:15px;color:#111827;">{html_lib.escape(s["sender_name"])}</strong>'
        f'<span style="color:#6b7280;font-size:13px;"> — {html_lib.escape(s["sender_role"])}</span><br>'
        f'<a href="tel:{html_lib.escape(s["phone_href"], quote=True)}" '
        f'style="color:#00a9cc;text-decoration:none;">{html_lib.escape(s["phone"])}</a>'
        f' · <a href="mailto:{html_lib.escape(s["email"], quote=True)}" '
        f'style="color:#00a9cc;text-decoration:none;">{html_lib.escape(s["email"])}</a><br>'
        f'<a href="{html_lib.escape(s["website"], quote=True)}" '
        f'style="color:#00a9cc;text-decoration:none;font-weight:600;">{html_lib.escape(s["website_label"])}</a>'
        f'<span style="color:#9ca3af;font-size:12px;"> · {html_lib.escape(s["address"])}</span>'
        '</td></tr>'
        '</table>'
    )


DEMO_REPLY_SUBJECT = "Crear bot gratis Vantelia"
DEMO_REPLY_BODY = (
    "Buenas,\n\n"
    "Me interesa crear el bot gratis para mi web.\n\n"
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


DEMO_PAGE_URL = os.getenv("OUTREACH_SIGNUP_URL", "https://www.vantelia.es/demo/").strip() or "https://www.vantelia.es/demo/"


def _demo_sector_for_prospect(p: Prospect) -> str:
    blob = f"{p.niche} {p.service_hint}".lower()
    if any(k in blob for k in ("clinica", "clínica", "dental", "fisio", "salud", "podolog", "psico")):
        return "Clínica / Salud"
    if any(k in blob for k in ("estet", "belleza", "peluquer", "barber", "spa")):
        return "Belleza y estética"
    if any(k in blob for k in ("academia", "formacion", "formación", "curso", "escuela", "idiomas")):
        return "Educación / Academias"
    if any(k in blob for k in ("restaurant", "bar", "cafeter", "hotel", "hostal")):
        return "Restaurante / Hostelería"
    if any(k in blob for k in ("inmobiliaria", "inmobil", "alquiler")):
        return "Inmobiliaria"
    if any(k in blob for k in ("taller", "reforma", "fontan", "electric", "cerraj", "repar")):
        return "Talleres y reparación"
    if any(k in blob for k in ("abogad", "asesor", "gestor", "consultor")):
        return "Servicios profesionales"
    return "Otro"


def demo_url_with_utm(stage: str, p: Prospect | None = None) -> str:
    params = {
        "utm_source": "outreach",
        "utm_medium": "email",
        "utm_campaign": stage,
    }
    if "app.vantelia.es/acceso" in DEMO_PAGE_URL:
        params["signup"] = "1"
    if p:
        params.update({
            "empresa": p.business_name or "",
            "sector": _demo_sector_for_prospect(p),
            "email": p.email or "",
            "web": p.website or "",
        })
    separator = "&" if "?" in DEMO_PAGE_URL else "?"
    return f"{DEMO_PAGE_URL}{separator}{urlencode({k: v for k, v in params.items() if v})}"


def demo_go_url(stage: str, p: "Prospect | None" = None) -> str:
    """CTA del email: enlace /demo/go/{token} que sirve la demo YA generada al
    instante (pre-generada al abrir). Sin tracking configurado o sin prospect,
    cae al formulario clasico. app.vantelia.es lo resuelve por el token."""
    secret = os.getenv("OUTREACH_TRACKING_SECRET", "").strip()
    base = os.getenv("OUTREACH_TRACKING_BASE_URL", "").strip().rstrip("/") or "https://app.vantelia.es"
    if not secret or not p or not getattr(p, "email", ""):
        return demo_url_with_utm(stage, p)
    token = make_tracking_token(p.email, stage, secret)
    return f"{base}/demo/go/{token}"


def calendar_url() -> str:
    return os.getenv("OUTREACH_CALENDAR_URL", "").strip()


def cta_button_html(text: str, href: str | None = None) -> str:
    # Boton CTA con degradado Vantelia, estilo compatible con clientes de email.
    safe_text = html_lib.escape(text)
    safe_href = html_lib.escape(href or demo_reply_mailto(), quote=True)
    return (
        '<table role="presentation" cellspacing="0" cellpadding="0" style="margin:14px 0;">'
        '<tr>'
        '<td style="border-radius:999px; background:#00D1FF; background:linear-gradient(135deg,#00D1FF,#00F5D4); box-shadow:0 10px 26px rgba(0,209,255,0.28);">'
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


def niche_opener(p: Prospect) -> str:
    """Primera frase personalizada por sector, sin parecer volcado de base de datos."""
    blob = f"{p.niche} {p.service_hint}".lower()
    name = p.business_name or "vuestro negocio"
    city = p.city or ""
    city_str = f" en {city}" if city else ""
    if any(k in blob for k in ("clinica", "clínica", "dental", "fisio", "salud", "podolog", "psico")):
        return f"He visto que {name} es una clinica{city_str}."
    if any(k in blob for k in ("estet", "belleza", "peluquer", "barber", "spa")):
        return f"He visto que {name} es un centro de belleza{city_str}."
    if any(k in blob for k in ("academia", "formacion", "formación", "curso", "escuela", "idiomas")):
        return f"He visto que {name} ofrece formacion{city_str}."
    if any(k in blob for k in ("restaurant", "bar", "cafeter", "hotel", "hostal")):
        return f"He visto que {name} es un restaurante o local de hosteleria{city_str}."
    if any(k in blob for k in ("inmobiliaria", "inmobil", "alquiler")):
        return f"He visto que {name} trabaja en el sector inmobiliario{city_str}."
    if any(k in blob for k in ("abogad", "asesor", "gestor", "consultor")):
        return f"He visto que {name} es un despacho o consultoria{city_str}."
    if any(k in blob for k in ("veterinaria", "veterinar")):
        return f"He visto que {name} es una clinica veterinaria{city_str}."
    if city:
        return f"He visto que {name} esta en {city}."
    return ""


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


def _cta_block(primary_text: str, stage: str = "cold", p: Prospect | None = None) -> tuple[str, str]:
    """Devuelve (text_cta, html_cta). CTA con UTM por stage para analytics."""
    if p and p.business_name:
        # La demo ya esta montada y se sirve al instante -> CTA de "ya listo,
        # solo miralo" (mas clic que "generar", que suena a trabajo/espera).
        primary_text = f"Ver el asistente de {p.business_name} funcionando"
    utm_url = demo_go_url(stage, p)
    book = calendar_url()
    minutes = _booking_minutes()
    text_lines: list[str] = [f"{primary_text}: {utm_url}"]
    html_parts: list[str] = [cta_button_html(primary_text, utm_url)]
    if book:
        text_lines.append(f"O reserva {minutes} min directamente: {book}")
        safe_book = html_lib.escape(book, quote=True)
        html_parts.append(
            f'<p style="margin:0 0 14px 0;font-size:14px;">'
            f'<a href="{safe_book}" style="color:#0B132B;border-bottom:1px solid #0B132B;text-decoration:none;">'
            f'Reservar {minutes} min</a></p>'
        )
    return ("\n".join(text_lines), "".join(html_parts))


def _render_human_stage(stage: str, p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    """Renderer canonico del bundle de conversacion A/B."""
    variant = assign_variant(p.email, stage)
    copy = OUTREACH_COPY_VARIANTS[stage][variant]
    subject, _ = pick_subject_with_variant(stage, p)
    plain_vars = {
        "greeting": p.greeting,
        "business": p.business_name or "vuestro negocio",
        "cta_url": demo_go_url(stage, p),
        "footer_text": footer_text(unsubscribe_mailto),
        "signature_html": signature_html(stage),
        "footer_html": footer_html(unsubscribe_mailto),
    }
    html_vars = {
        **plain_vars,
        "greeting": html_lib.escape(plain_vars["greeting"]),
        "business": html_lib.escape(plain_vars["business"]),
        "cta_url": html_lib.escape(plain_vars["cta_url"], quote=True),
    }
    text = copy["body_text"].format_map(plain_vars)
    inner = copy["body_html"].format_map(html_vars)
    return subject, text, html_shell(inner)


def render_cold(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    return _render_human_stage("cold", p, unsubscribe_mailto)

    # Conservado temporalmente debajo del return para compatibilidad de diffs
    # historicos; el renderer canonico de arriba es el unico ejecutable.
    env_proof = _proof_line()
    name = p.business_name
    subject, _variant = pick_subject_with_variant("cold", p)
    cta_text, cta_html = _cta_block(f"Crear el bot de {name} gratis", "cold", p)
    opener = niche_opener(p)
    opener_html = (
        f'<p style="margin:0 0 14px 0;">{html_lib.escape(opener)}</p>'
        if opener else ""
    )
    proof_html = (
        f'<p style="margin:0 0 14px 0;color:#4b5563;font-style:italic;">'
        f'{html_lib.escape(env_proof)}</p>'
        if env_proof else ""
    )
    proof_text = f"\n{env_proof}\n" if env_proof else ""
    text = (
        f"{p.greeting}\n\n"
        f"Soy Pablo, fundador de Vantelia. Te escribo porque hacemos chats para negocios "
        f"como {name} que responden por vosotros cuando estais ocupados o cerrados.\n\n"
        f"Ahora cualquier negocio puede crear gratis su asistente IA en menos de 2 minutos: "
        f"pega la URL de la web, Vantelia lee el contenido, genera el bot y lo deja listo "
        f"para probar.\n\n"
        f"{f'{opener} ' if opener else ''}"
        f"He dejado una demo preparada con vuestros datos para que la revises en un minuto. "
        f"Si la web esta incluida, Vantelia la usara para personalizar el asistente antes de abrirlo:\n"
        f"{cta_text}\n"
        f"{proof_text}"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )
    inner = (
        f'<p>{html_lib.escape(p.greeting)}</p>'
        f'<p>Soy Pablo, fundador de Vantelia. Te escribo porque hacemos chats para negocios '
        f'como {html_lib.escape(name)} que responden por vosotros cuando estais ocupados o cerrados.</p>'
        f'<p>Ahora cualquier negocio puede crear gratis su asistente IA en menos de 2 minutos: '
        f'pega la URL de la web, Vantelia lee el contenido, genera el bot y lo deja listo '
        f'para probar.</p>'
        f'{opener_html}'
        f'<p>He dejado una demo preparada con vuestros datos para que la revises en un minuto. '
        f'Si la web esta incluida, Vantelia la usara para personalizar el asistente antes de abrirlo:</p>'
        f'{cta_html}'
        f'{proof_html}'
        f'{signature_html("cold")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    return subject, text, html_shell(inner)


def render_fu1(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    return _render_human_stage("fu1", p, unsubscribe_mailto)

    name = p.business_name
    cta_text, cta_html = _cta_block("Empezar gratis", "fu1", p)
    text = (
        f"{p.greeting}\n\n"
        f"Te escribi hace unos dias (soy Pablo, de Vantelia — vantelia.es).\n\n"
        f"Por si no llegaste: tengo un chat hecho especificamente para {name} "
        f"que atiende a tus clientes las 24 horas. "
        f"Te dejo el formulario ya cargado para generar la demo:\n"
        f"{cta_text}\n\n"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )
    inner = (
        f'<p>{html_lib.escape(p.greeting)}</p>'
        f'<p>Te escribi hace unos dias '
        f'(soy Pablo, de <a href="https://vantelia.es" style="color:#00a9cc;">Vantelia</a>).</p>'
        f'<p>Por si no llegaste: tengo un chat hecho especificamente para {html_lib.escape(name)} '
        f'que atiende a tus clientes las 24 horas. '
        f'Te dejo el formulario ya cargado para generar la demo:</p>'
        f'{cta_html}'
        f'{signature_html("fu1")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    preheader = f"Demo para {name} preparada. Revisala en un minuto."
    return pick_subject("fu1", p), text, html_shell(inner, preheader=preheader)


def render_fu2(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    return _render_human_stage("fu2", p, unsubscribe_mailto)

    task, _outcome, _ = niche_copy(p.niche, p.service_hint)
    name = p.business_name
    cta_text, cta_html = _cta_block("Probarlo gratis ahora", "fu2", p)
    text = (
        f"{p.greeting}\n\n"
        f"Ultimo mensaje de mi parte (Pablo, Vantelia — vantelia.es).\n\n"
        f"El chat que prepare para {name}:\n\n"
        f"- Responde preguntas sobre {task}\n"
        f"- Funciona las 24 horas, tambien cuando estais cerrados\n"
        f"- Se genera gratis y sin tarjeta\n\n"
        f"Solo hay que darle al boton, revisar los datos y generar la demo:\n"
        f"{cta_text}\n\n"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )
    inner = (
        f'<p>{html_lib.escape(p.greeting)}</p>'
        f'<p>Ultimo intento, lo prometo '
        f'(Pablo, de <a href="https://vantelia.es" style="color:#00a9cc;">Vantelia</a>).</p>'
        f'<p>Negocios como {html_lib.escape(name)} usan Vantelia para:</p>'
        f'<ul style="margin:0 0 16px 0;padding-left:20px;line-height:2;">'
        f'<li>Responde preguntas sobre {html_lib.escape(task)}</li>'
        f'<li>Funciona las 24 horas, tambien cuando estais cerrados</li>'
        f'<li>Se genera gratis y sin tarjeta</li>'
        f'</ul>'
        f'<p>Solo hay que darle al boton, revisar los datos y generar la demo:</p>'
        f'{cta_html}'
        f'{signature_html("fu2")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    preheader = f"Demo para {name}. Gratis, sin tarjeta, lista para generar."
    return pick_subject("fu2", p), text, html_shell(inner, preheader=preheader)


def render_breakup(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    return _render_human_stage("breakup", p, unsubscribe_mailto)

    name = p.business_name
    cta_text, cta_html = _cta_block("Crear mi bot gratis", "breakup", p)
    text = (
        f"{p.greeting}\n\n"
        f"Lo dejo por aqui, no te escribire mas.\n\n"
        f"Si algun dia queréis probar como funciona un chat automatico en vuestra web, "
        f"el de {name} sigue disponible en vantelia.es. "
        f"Un clic, revisas los datos y generas una demo para ver si tiene sentido. "
        f"Sin tarjeta, sin compromiso.\n"
        f"{cta_text}\n\n"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )
    inner = (
        f'<p>{html_lib.escape(p.greeting)}</p>'
        f'<p>Lo dejo por aqui, no te escribire mas.</p>'
        f'<p>Si algun dia quereis probar como funciona un chat automatico en vuestra web, '
        f'el de {html_lib.escape(name)} sigue disponible en '
        f'<a href="https://vantelia.es" style="color:#00a9cc;">vantelia.es</a>. '
        f'Un clic, revisas los datos y generas una demo para ver si tiene sentido. '
        f'Sin tarjeta, sin compromiso.</p>'
        f'{cta_html}'
        f'{signature_html("breakup")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    preheader = f"Sin tarjeta ni compromiso. La demo de {name} sigue disponible."
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
        # No reescribir enlaces que ya son del propio tracker ni el /demo/go
        # (registra su propio clic; envolverlo duplicaria el evento).
        if url.startswith(f"{base}/track/") or "/demo/go/" in url:
            return match.group(0)
        wrapped = f"{base}/track/click/{token}?u={quote(html_lib.unescape(url), safe='')}"
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
