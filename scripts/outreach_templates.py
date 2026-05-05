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


SUBJECTS_COLD = [
    "Idea concreta para {business}",
    "Asistente IA para {business}",
    "Demo personalizada para {business}",
    "Posible mejora para la web de {business}",
]

SUBJECTS_FU1 = [
    "Re: {business} y la demo",
    "¿Te llego mi mensaje, {first_or_team}?",
    "Reabro: demo IA para {business}",
]

SUBJECTS_FU2 = [
    "Un caso real parecido a {business}",
    "{business}: 3 minutos para enseñartelo",
    "Te lo dejo grabado para {business}",
]

SUBJECTS_BREAKUP = [
    "Cierro tu ficha de {business}",
    "Ultimo correo sobre {business}",
    "Lo dejo aqui, {first_or_team}",
]


def fmt_subject(template: str, p: Prospect) -> str:
    first_or_team = p.first_name or "equipo"
    return template.format(business=p.business_name, first_or_team=first_or_team)


def pick_subject(stage: str, p: Prospect) -> str:
    pool = {
        "cold": SUBJECTS_COLD,
        "fu1": SUBJECTS_FU1,
        "fu2": SUBJECTS_FU2,
        "breakup": SUBJECTS_BREAKUP,
    }[stage]
    template = stable_pick(p.email + "|" + stage, pool)
    return fmt_subject(template, p)


SIGNATURE_TEXT = (
    "Pablo Sanchez\n"
    "Fundador de Vantelia\n"
    "https://www.vantelia.es\n"
)


def signature_html(stage: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:24px 0 0 0;border-collapse:collapse;">'
        '<tr><td style="padding:16px 0 0 0;border-top:1px solid #eef2f7;'
        'font-family:Inter,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.6;color:#0B132B;">'
        '<strong style="font-weight:600;color:#0B132B;">Pablo Sanchez</strong><br>'
        '<span style="color:#637c8e;font-size:13px;">Fundador de Vantelia</span><br>'
        f'<a href="https://www.vantelia.es?utm_source=outreach&amp;utm_medium=email&amp;utm_campaign={stage}" '
        'style="color:#0891b2;text-decoration:none;font-size:13px;font-weight:500;">www.vantelia.es</a>'
        '</td></tr></table>'
    )


def cta_button_html(text: str, href: str = "mailto:info@vantelia.es") -> str:
    safe_text = html_lib.escape(text)
    safe_href = html_lib.escape(href, quote=True)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:18px 0 6px 0;border-collapse:collapse;">'
        '<tr><td style="border-radius:10px;'
        'background:linear-gradient(135deg,#00D1FF 0%,#00F5D4 100%);'
        'background-color:#00D1FF;">'
        f'<a href="{safe_href}" style="display:inline-block;padding:13px 28px;'
        'font-family:Inter,Helvetica,Arial,sans-serif;font-size:15px;font-weight:600;'
        'color:#0B132B;text-decoration:none;letter-spacing:0.2px;border-radius:10px;">'
        f'{safe_text}</a>'
        '</td></tr></table>'
    )


def footer_text(unsubscribe_mailto: str) -> str:
    return (
        "\n--\n"
        "Vantelia | Asistentes IA para negocios B2B en España.\n"
        "Si no quieres recibir mas mensajes, responde \"BAJA\" o escribe a "
        f"{unsubscribe_mailto}. Te eliminaremos al instante.\n"
        "Tratamos tus datos solo para este contacto comercial. Responsable: Vantelia. "
        "Base legal: interes legitimo (LSSI/RGPD).\n"
    )


def footer_html(unsubscribe_mailto: str) -> str:
    safe_mail = html_lib.escape(unsubscribe_mailto)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
        'style="margin:28px 0 0 0;border-collapse:collapse;">'
        '<tr><td style="padding:18px 0 0 0;border-top:1px solid #eef2f7;'
        'font-family:Inter,Helvetica,Arial,sans-serif;font-size:11px;line-height:1.6;'
        'color:#8fa3b4;text-align:left;">'
        '<strong style="color:#637c8e;">Vantelia</strong> &middot; Asistentes IA para negocios B2B en España.<br>'
        f'Si no quieres recibir mas mensajes, responde <strong>BAJA</strong> o escribe a '
        f'<a href="mailto:{safe_mail}?subject=BAJA" style="color:#8fa3b4;text-decoration:underline;">{safe_mail}</a>. '
        'Te eliminaremos al instante.<br>'
        '<span style="color:#aab8c5;">Tratamos tus datos solo para este contacto comercial. '
        'Responsable: Vantelia. Base legal: interes legitimo (LSSI/RGPD).</span>'
        '</td></tr></table>'
    )


def html_shell(inner_html: str, preheader: str = "") -> str:
    pre = ""
    if preheader:
        pre = (
            '<div style="display:none;font-size:1px;color:#f6f8fb;line-height:1px;'
            'max-height:0;max-width:0;opacity:0;overflow:hidden;">'
            f'{html_lib.escape(preheader)}'
            '</div>'
        )
    return (
        '<!doctype html><html lang="es" xmlns:v="urn:schemas-microsoft-com:vml">'
        '<head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="x-apple-disable-message-reformatting">'
        '<meta http-equiv="X-UA-Compatible" content="IE=edge">'
        '<title>Vantelia</title>'
        '<style>'
        '@media (max-width:620px){.vt-card{padding:22px 18px !important;}.vt-shell{padding:14px 8px !important;}}'
        'a{color:#0891b2;}'
        '</style>'
        '</head>'
        '<body style="margin:0;padding:0;background:#f6f8fb;'
        'font-family:Inter,Helvetica,Arial,sans-serif;color:#0B132B;-webkit-font-smoothing:antialiased;">'
        f'{pre}'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
        'style="background:#f6f8fb;border-collapse:collapse;">'
        '<tr><td align="center" class="vt-shell" style="padding:28px 16px;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" '
        'style="max-width:600px;width:100%;border-collapse:collapse;">'
        # Logo / header
        '<tr><td style="padding:0 0 18px 0;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:collapse;">'
        '<tr><td style="font-family:Inter,Helvetica,Arial,sans-serif;font-size:20px;'
        'font-weight:700;letter-spacing:-0.4px;color:#0B132B;">'
        '<span style="background:linear-gradient(135deg,#00D1FF 0%,#00F5D4 100%);'
        '-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
        'background-clip:text;color:#00D1FF;">Vantelia</span>'
        '</td></tr></table>'
        '</td></tr>'
        # Card
        '<tr><td class="vt-card" style="background:#ffffff;border:1px solid #e4eaf2;'
        'border-radius:16px;padding:32px 28px;box-shadow:0 1px 2px rgba(11,19,43,0.04);'
        'font-family:Inter,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.6;color:#172033;">'
        f'{inner_html}'
        '</td></tr>'
        # Outer note
        '<tr><td style="padding:14px 6px 0 6px;'
        'font-family:Inter,Helvetica,Arial,sans-serif;font-size:11px;color:#aab8c5;text-align:center;">'
        'Email enviado a contactos publicos de empresas españolas. '
        '<a href="https://www.vantelia.es" style="color:#aab8c5;text-decoration:underline;">vantelia.es</a>'
        '</td></tr>'
        '</table>'
        '</td></tr></table>'
        '</body></html>'
    )


def render_cold(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    task, outcome, proof = niche_copy(p.niche, p.service_hint)
    service_line = (
        f"He visto que en {p.business_name} trabajais {p.service_hint}."
        if p.service_hint
        else f"He visto vuestro negocio en {p.city}."
    )
    web_note = (
        f" Eche un ojo a vuestra web ({p.website}) y creo que tiene margen claro de mejora."
        if p.website
        else ""
    )

    text = (
        f"{p.greeting}\n\n"
        f"Soy Pablo, fundador de Vantelia. {service_line}{web_note}\n\n"
        f"Os escribo porque {proof}. Un asistente IA conectado a vuestra web "
        f"y a WhatsApp puede {task}, con el objetivo de {outcome}.\n\n"
        f"Estoy preparando 3 demos personalizadas para negocios de {p.city} esta semana. "
        f"La hago con vuestra propia informacion, en menos de 24h y sin compromiso.\n\n"
        f"Si encaja, lo dejamos funcionando 30 dias gratis, sin permanencia, "
        f"y medimos juntos si genera solicitudes reales.\n\n"
        f"¿Te paso una demo concreta de {p.business_name}? Con un \"si\" basta y te la mando.\n\n"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )

    web_html = ""
    if p.website:
        url = html_lib.escape(p.website, quote=True)
        url_text = html_lib.escape(p.website)
        web_html = (
            f' Eche un ojo a vuestra web (<a href="{url}" style="color:#0891b2;">{url_text}</a>) '
            f"y creo que tiene margen claro de mejora."
        )
    cta = cta_button_html(f"Si, preparame la demo")
    inner = (
        f'<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{html_lib.escape(p.greeting)}</p>'
        f'<p style="margin:0 0 14px 0;">Soy Pablo, fundador de <strong style="color:#0B132B;">Vantelia</strong>. '
        f'{html_lib.escape(service_line)}{web_html}</p>'
        f'<p style="margin:0 0 14px 0;">Os escribo porque '
        f'<em style="color:#0891b2;font-style:normal;font-weight:500;">{html_lib.escape(proof)}</em>. '
        f'Un asistente IA conectado a vuestra web y a WhatsApp puede '
        f'<strong>{html_lib.escape(task)}</strong>, con el objetivo de '
        f'<strong>{html_lib.escape(outcome)}</strong>.</p>'
        # Highlight box
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
        f'style="border-collapse:collapse;margin:18px 0;">'
        f'<tr><td style="background:#f0fbff;border-left:3px solid #00D1FF;border-radius:6px;'
        f'padding:14px 16px;font-size:14px;color:#0B132B;line-height:1.55;">'
        f'<strong style="color:#0891b2;">3 demos personalizadas</strong> esta semana para negocios de '
        f'{html_lib.escape(p.city)}. Hecha con vuestra propia informacion, en menos de 24h y sin compromiso.<br>'
        f'<span style="color:#637c8e;font-size:13px;">Si encaja: 30 dias gratis, sin permanencia.</span>'
        f'</td></tr></table>'
        f'<p style="margin:0 0 6px 0;font-size:16px;color:#0B132B;">'
        f'<strong>¿Te paso una demo concreta de {html_lib.escape(p.business_name)}?</strong></p>'
        f'<p style="margin:0 0 4px 0;color:#637c8e;font-size:14px;">Con un "si" basta y te la mando.</p>'
        f'{cta}'
        f'{signature_html("cold")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    preheader = f"Demo IA personalizada para {p.business_name} en menos de 24h, sin compromiso."
    return pick_subject("cold", p), text, html_shell(inner, preheader=preheader)


def render_fu1(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    text = (
        f"{p.greeting}\n\n"
        f"Te escribi hace unos dias sobre montaros una demo de asistente IA para "
        f"{p.business_name}. Cierro huecos de agenda esta semana y queria saber si os encaja.\n\n"
        f"Si lo prefieres, te la grabo en 3 minutos con vuestra info y te la mando por aqui. "
        f"Sin llamada, sin compromiso.\n\n"
        f"¿Te interesa que la prepare?\n\n"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )
    cta = cta_button_html("Si, prepara la demo")
    inner = (
        f'<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{html_lib.escape(p.greeting)}</p>'
        f'<p style="margin:0 0 14px 0;">Te escribi hace unos dias sobre montaros una demo de '
        f'asistente IA para <strong>{html_lib.escape(p.business_name)}</strong>. Cierro huecos de '
        f'agenda esta semana y queria saber si os encaja.</p>'
        f'<p style="margin:0 0 14px 0;">Si lo prefieres, te la '
        f'<strong style="color:#0891b2;">grabo en 3 minutos</strong> con vuestra info y te la '
        f'mando por aqui. Sin llamada, sin compromiso.</p>'
        f'<p style="margin:0 0 6px 0;font-size:16px;color:#0B132B;">'
        f'<strong>¿Te interesa que la prepare?</strong></p>'
        f'{cta}'
        f'{signature_html("fu1")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    preheader = f"Reabro: demo IA grabada en 3 minutos para {p.business_name}."
    return pick_subject("fu1", p), text, html_shell(inner, preheader=preheader)


def render_fu2(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    task, outcome, proof = niche_copy(p.niche, p.service_hint)
    text = (
        f"{p.greeting}\n\n"
        f"Te dejo un caso concreto para que veas el angulo:\n\n"
        f"Negocios parecidos a {p.business_name} usan Vantelia para {task}. "
        f"En la primera semana suelen ver mas solicitudes desde la web y menos llamadas repetidas.\n\n"
        f"Si quieres, te lo monto con vuestros datos reales y te paso un enlace de demo privado. "
        f"24h y listo.\n\n"
        f"¿Sigo adelante?\n\n"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )
    cta = cta_button_html("Si, montalo con mis datos")
    inner = (
        f'<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{html_lib.escape(p.greeting)}</p>'
        f'<p style="margin:0 0 14px 0;">Te dejo un caso concreto para que veas el angulo:</p>'
        # Quote-style block
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
        f'style="border-collapse:collapse;margin:14px 0 18px 0;">'
        f'<tr><td style="background:#f9fbfd;border-left:3px solid #00F5D4;border-radius:6px;'
        f'padding:16px 18px;font-size:14px;color:#172033;line-height:1.6;">'
        f'Negocios parecidos a <strong style="color:#0B132B;">{html_lib.escape(p.business_name)}</strong> '
        f'usan Vantelia para <strong style="color:#0891b2;">{html_lib.escape(task)}</strong>. '
        f'En la primera semana suelen ver mas solicitudes desde la web y menos llamadas repetidas.'
        f'</td></tr></table>'
        f'<p style="margin:0 0 14px 0;">Si quieres, te lo monto con vuestros datos reales y te '
        f'paso un enlace de demo privado. <strong>24h y listo.</strong></p>'
        f'<p style="margin:0 0 6px 0;font-size:16px;color:#0B132B;"><strong>¿Sigo adelante?</strong></p>'
        f'{cta}'
        f'{signature_html("fu2")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    preheader = f"Caso real parecido a {p.business_name}: demo privada en 24h."
    return pick_subject("fu2", p), text, html_shell(inner, preheader=preheader)


def render_breakup(p: Prospect, unsubscribe_mailto: str) -> tuple[str, str, str]:
    text = (
        f"{p.greeting}\n\n"
        f"Cierro la ficha de {p.business_name} para no llenarte la bandeja. "
        f"Si en algun momento quereis ver una demo de asistente IA, basta con responder a "
        f"este correo y la preparo.\n\n"
        f"Suerte con todo y un saludo,\n\n"
        f"{SIGNATURE_TEXT}"
        f"{footer_text(unsubscribe_mailto)}"
    )
    inner = (
        f'<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{html_lib.escape(p.greeting)}</p>'
        f'<p style="margin:0 0 14px 0;">Cierro la ficha de '
        f'<strong>{html_lib.escape(p.business_name)}</strong> para no llenarte la bandeja. '
        f'Si en algun momento quereis ver una demo de asistente IA, basta con responder a este '
        f'correo y la preparo.</p>'
        f'<p style="margin:0 0 6px 0;color:#637c8e;">Suerte con todo y un saludo,</p>'
        f'{signature_html("breakup")}'
        f'{footer_html(unsubscribe_mailto)}'
    )
    preheader = f"Ultimo correo. Cierro tu ficha, {p.first_name or 'equipo'}."
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

    rewritten = _TRACKABLE_HREF.sub(_rewrite, html_body)
    pixel = (
        f'<img src="{base}/track/open/{token}.gif" '
        f'width="1" height="1" alt="" '
        f'style="display:block;border:0;width:1px;height:1px;" />'
    )
    if "</body>" in rewritten:
        return rewritten.replace("</body>", f"{pixel}</body>")
    return rewritten + pixel
