"""Sembrar plantillas profesionales en outreach.db via API admin.

Uso:
    python scripts/seed_outreach_templates.py
    python scripts/seed_outreach_templates.py --base https://app.vantelia.es
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


COLD_SUBJECTS = """Estamos empezando: 3 demos gratis para {business}
{first_or_team}, te cuento (busco 3 negocios en {city})
De emprendedor a emprendedor: una idea para {business}
3 demos gratis esta semana — ¿te la monto para {business}?
Recien empezamos y queriamos enseñartelo, {first_or_team}"""

COLD_TEXT = """{greeting}

Soy Pablo, fundador de Vantelia. Te voy a ser sincero: estamos empezando. Y como tu sabes mejor que nadie lo que es emprender, levantar algo desde cero y buscar los primeros clientes que confien.

Por eso te escribo. Esta semana regalo 3 demos completas a negocios de {city} que esten dispuestos a probar algo nuevo. Vi {business} y eche un ojo a {website} — creo que encaja.

Lo que monto: un asistente IA conectado a vuestra web y a WhatsApp para {task}. Hecho con vuestra propia informacion, listo en 24h.

¿Que pides a cambio? Cero. Lo dejamos 30 dias funcionando, sin permanencia, sin tarjeta. Si genera solicitudes reales hablamos. Si no, sin problema y mucha suerte.

Te lo planteo asi de claro porque {proof}, y porque a un emprendedor no le robas el tiempo: si no encaja respondes "no" y listo.

¿Te paso la demo de {business}? Un "si" basta y manos a la obra.

Pablo Sanchez
Fundador de Vantelia
https://www.vantelia.es
{footer_text}"""

COLD_HTML = """<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{greeting}</p>

<p style="margin:0 0 14px 0;">Soy Pablo, fundador de <strong style="color:#0B132B;">Vantelia</strong>. Te voy a ser sincero: <strong>estamos empezando</strong>. Y como tu sabes mejor que nadie lo que es emprender, levantar algo desde cero y buscar los primeros clientes que confien.</p>

<p style="margin:0 0 14px 0;">Por eso te escribo. Esta semana <strong>regalo 3 demos completas</strong> a negocios de {city} que esten dispuestos a probar algo nuevo. Vi <strong>{business}</strong> y eche un ojo a vuestra web (<a href="{website}" style="color:#0891b2;">{website}</a>) — creo que encaja.</p>

<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;margin:18px 0;">
  <tr><td style="background:#f0fbff;border-left:3px solid #00D1FF;border-radius:8px;padding:16px 18px;font-size:14px;color:#0B132B;line-height:1.6;">
    <strong style="color:#0891b2;">Lo que monto:</strong> asistente IA conectado a vuestra web y a WhatsApp para <strong>{task}</strong>.<br>
    <span style="color:#637c8e;">Con vuestra propia informacion. Listo en 24h.</span>
  </td></tr>
</table>

<p style="margin:0 0 8px 0;"><strong style="color:#0B132B;">¿Que pides a cambio?</strong> Cero.</p>
<p style="margin:0 0 14px 0;">Lo dejamos <strong>30 dias funcionando, sin permanencia, sin tarjeta</strong>. Si genera solicitudes reales hablamos. Si no, sin problema y mucha suerte.</p>

<p style="margin:0 0 18px 0;color:#637c8e;font-size:14px;font-style:italic;">Te lo planteo asi de claro porque {proof}, y porque a un emprendedor no le robas el tiempo: si no encaja respondes "no" y listo.</p>

<p style="margin:0 0 6px 0;font-size:16px;color:#0B132B;"><strong>¿Te paso la demo de {business}?</strong></p>
<p style="margin:0 0 4px 0;color:#637c8e;font-size:14px;">Un "si" basta y manos a la obra.</p>

{cta_html}
{signature_html}
{footer_html}"""


FU1_SUBJECTS = """Re: {business} y la demo
¿Te llego mi mensaje, {first_or_team}?
Reabro: demo IA para {business}
{first_name}, una idea rapida para {business}"""

FU1_TEXT = """{greeting}

Te escribi hace unos dias sobre montaros una demo de asistente IA para {business}. Cierro huecos de agenda esta semana y queria saber si os encaja.

Si lo prefieres, te la grabo en 3 minutos con vuestra info y te la mando por aqui. Sin llamada, sin compromiso.

¿Te interesa que la prepare?

Pablo Sanchez
Fundador de Vantelia
{footer_text}"""

FU1_HTML = """<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{greeting}</p>

<p style="margin:0 0 14px 0;">Te escribi hace unos dias sobre montaros una demo de asistente IA para <strong>{business}</strong>. Cierro huecos de agenda esta semana y queria saber si os encaja.</p>

<p style="margin:0 0 14px 0;">Si lo prefieres, te la <strong style="color:#0891b2;">grabo en 3 minutos</strong> con vuestra info y te la mando por aqui. Sin llamada, sin compromiso.</p>

<p style="margin:0 0 6px 0;font-size:16px;color:#0B132B;"><strong>¿Te interesa que la prepare?</strong></p>

{cta_html}
{signature_html}
{footer_html}"""


FU2_SUBJECTS = """Un caso real parecido a {business}
{business}: 3 minutos para enseñartelo
Te lo dejo grabado para {business}
Como otros {niche} usan Vantelia"""

FU2_TEXT = """{greeting}

Te dejo un caso concreto para que veas el angulo:

Negocios parecidos a {business} usan Vantelia para {task}. En la primera semana suelen ver mas solicitudes desde la web y menos llamadas repetidas.

Si quieres, te lo monto con vuestros datos reales y te paso un enlace de demo privado. 24h y listo.

¿Sigo adelante?

Pablo Sanchez
Fundador de Vantelia
{footer_text}"""

FU2_HTML = """<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{greeting}</p>

<p style="margin:0 0 14px 0;">Te dejo un caso concreto para que veas el angulo:</p>

<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;margin:14px 0 18px 0;">
  <tr><td style="background:#f9fbfd;border-left:3px solid #00F5D4;border-radius:6px;padding:16px 18px;font-size:14px;color:#172033;line-height:1.6;">
    Negocios parecidos a <strong style="color:#0B132B;">{business}</strong> usan Vantelia para <strong style="color:#0891b2;">{task}</strong>. En la primera semana suelen ver <strong>mas solicitudes desde la web</strong> y <strong>menos llamadas repetidas</strong>.
  </td></tr>
</table>

<p style="margin:0 0 14px 0;">Si quieres, te lo monto con vuestros datos reales y te paso un enlace de demo privado. <strong>24h y listo.</strong></p>

<p style="margin:0 0 6px 0;font-size:16px;color:#0B132B;"><strong>¿Sigo adelante?</strong></p>

{cta_html}
{signature_html}
{footer_html}"""


BREAKUP_SUBJECTS = """Cierro tu ficha de {business}
Ultimo correo sobre {business}
Lo dejo aqui, {first_or_team}
Sin presion: cierro contacto con {business}"""

BREAKUP_TEXT = """{greeting}

Cierro la ficha de {business} para no llenarte la bandeja. Si en algun momento quereis ver una demo de asistente IA, basta con responder a este correo y la preparo.

Suerte con todo y un saludo,

Pablo Sanchez
Fundador de Vantelia
{footer_text}"""

BREAKUP_HTML = """<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{greeting}</p>

<p style="margin:0 0 14px 0;">Cierro la ficha de <strong>{business}</strong> para no llenarte la bandeja. Si en algun momento quereis ver una demo de asistente IA, basta con responder a este correo y la preparo.</p>

<p style="margin:0 0 6px 0;color:#637c8e;">Suerte con todo y un saludo,</p>

{signature_html}
{footer_html}"""


TEMPLATES = {
    "cold":    {"subject_pool": COLD_SUBJECTS,    "body_text": COLD_TEXT,    "body_html": COLD_HTML},
    "fu1":     {"subject_pool": FU1_SUBJECTS,     "body_text": FU1_TEXT,     "body_html": FU1_HTML},
    "fu2":     {"subject_pool": FU2_SUBJECTS,     "body_text": FU2_TEXT,     "body_html": FU2_HTML},
    "breakup": {"subject_pool": BREAKUP_SUBJECTS, "body_text": BREAKUP_TEXT, "body_html": BREAKUP_HTML},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.getenv("APP_BASE_URL", "https://app.vantelia.es").rstrip("/"))
    parser.add_argument("--token", default=os.getenv("ADMIN_API_TOKEN", "").strip())
    args = parser.parse_args()

    if not args.token:
        print("ADMIN_API_TOKEN no encontrado en .env ni en --token", file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bearer {args.token}", "Content-Type": "application/json"}
    with httpx.Client(timeout=15.0) as client:
        for stage, body in TEMPLATES.items():
            payload = {"stage": stage, **body}
            resp = client.put(f"{args.base}/admin/outreach/templates", json=payload, headers=headers)
            if resp.status_code >= 300:
                print(f"  {stage}: ERROR {resp.status_code} {resp.text[:200]}")
                return 1
            print(f"  {stage}: OK")

    print("\nTodas las plantillas guardadas. Verifica en panel: Captacion -> Plantillas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
