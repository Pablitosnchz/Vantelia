"""Sembrar plantillas self-service en outreach.db via API admin.

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


COLD_SUBJECTS = """Bot IA para {business}
{business}: bot en 2 min
{first_or_team}, prueba esto
Crear un bot para {business}
Una idea self-service para {business}"""

COLD_TEXT = """{greeting}

Soy Pablo, de Vantelia. Hemos cambiado el enfoque: ya no hace falta pedir una demo ni esperar a que alguien la monte.

Ahora cualquier negocio puede crear gratis su asistente IA en menos de 2 minutos: pega la URL de la web, Vantelia lee el contenido, genera el bot y lo deja listo para probar.

Para {business} encaja especialmente para {task}, sin que el equipo repita las mismas respuestas cada dia.

El plan gratuito incluye 50 mensajes/mes, no pide tarjeta y permite copiar el snippet si os encaja.

Crear bot gratis para {business}: {cta_url}

{footer_text}"""

COLD_HTML = """<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{greeting}</p>

<p style="margin:0 0 14px 0;">Soy Pablo, de <strong>Vantelia</strong>. Hemos cambiado el enfoque: ya no hace falta pedir una demo ni esperar a que alguien la monte.</p>

<p style="margin:0 0 14px 0;">Ahora cualquier negocio puede crear gratis su asistente IA en menos de 2 minutos: pega la URL de la web, Vantelia lee el contenido, genera el bot y lo deja listo para probar.</p>

<p style="margin:0 0 14px 0;">Para <strong>{business}</strong> encaja especialmente para <strong>{task}</strong>, sin que el equipo repita las mismas respuestas cada dia.</p>

<p style="margin:0 0 14px 0;">El plan gratuito incluye <strong>50 mensajes/mes</strong>, no pide tarjeta y permite copiar el snippet si os encaja.</p>

{cta_html}
{signature_html}
{footer_html}"""


FU1_SUBJECTS = """Re: {business}
{first_or_team}, lo viste?
{business} - sigue en pie
Bot gratis para {business}"""

FU1_TEXT = """{greeting}

Te escribi hace unos dias. Por si no lo viste: Vantelia ya funciona en modo self-service.

Puedes crear el bot de {business} gratis pegando vuestra URL. El sistema lee la web, genera el asistente y te deja probarlo antes de copiar el snippet.

Sin llamada, sin tarjeta y sin esperar a que preparemos nada manualmente.

Crear bot gratis: {cta_url}

{footer_text}"""

FU1_HTML = """<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{greeting}</p>

<p style="margin:0 0 14px 0;">Te escribi hace unos dias. Por si no lo viste: Vantelia ya funciona en modo self-service.</p>

<p style="margin:0 0 14px 0;">Puedes crear el bot de <strong>{business}</strong> gratis pegando vuestra URL. El sistema lee la web, genera el asistente y te deja probarlo antes de copiar el snippet.</p>

<p style="margin:0 0 14px 0;">Sin llamada, sin tarjeta y sin esperar a que preparemos nada manualmente.</p>

{cta_html}
{signature_html}
{footer_html}"""


FU2_SUBJECTS = """3 pasos para {business}
{business}: como empezar
Te dejo el flujo {first_or_team}
Bot gratis para {business}"""

FU2_TEXT = """{greeting}

Te dejo el flujo exacto para probarlo sin hablar con ventas:

1. Pegas la URL de {business}.
2. Vantelia lee la web y genera el bot.
3. Lo pruebas y, si encaja, copias el snippet en vuestra web.

Sirve para {task} y empezar a medir si convierte visitas en conversaciones reales.

Probar el flujo gratis: {cta_url}

{footer_text}"""

FU2_HTML = """<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{greeting}</p>

<p style="margin:0 0 14px 0;">Te dejo el flujo exacto para probarlo sin hablar con ventas:</p>

<ol style="margin:0 0 14px 18px;padding:0;">
  <li>Pegas la URL de {business}.</li>
  <li>Vantelia lee la web y genera el bot.</li>
  <li>Lo pruebas y, si encaja, copias el snippet en vuestra web.</li>
</ol>

<p style="margin:0 0 14px 0;">Sirve para <strong>{task}</strong> y empezar a medir si convierte visitas en conversaciones reales.</p>

{cta_html}
{signature_html}
{footer_html}"""


BREAKUP_SUBJECTS = """Cierro el hilo
{business}: lo dejo aqui
Ultimo correo sobre {business}
Sin presion, {first_or_team}"""

BREAKUP_TEXT = """{greeting}

Lo dejo por ahora para no insistir. Si en otro momento os interesa, podeis crear el bot gratis directamente desde aqui:

{cta_url}

{footer_text}"""

BREAKUP_HTML = """<p style="margin:0 0 16px 0;font-size:16px;color:#0B132B;">{greeting}</p>

<p style="margin:0 0 14px 0;">Lo dejo por ahora para no insistir. Si en otro momento os interesa, podeis crear el bot gratis directamente desde aqui.</p>

{cta_html}
{signature_html}
{footer_html}"""


TEMPLATES = {
    "cold": {"subject_pool": COLD_SUBJECTS, "body_text": COLD_TEXT, "body_html": COLD_HTML},
    "fu1": {"subject_pool": FU1_SUBJECTS, "body_text": FU1_TEXT, "body_html": FU1_HTML},
    "fu2": {"subject_pool": FU2_SUBJECTS, "body_text": FU2_TEXT, "body_html": FU2_HTML},
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

    print("\nTodas las plantillas self-service guardadas. Verifica en Admin -> Captacion -> Copy self-service.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
