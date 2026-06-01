"""Reintento FAMSAM + Skin and Joy."""
import os, smtplib, ssl, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_HOST = os.environ['SMTP_HOST']
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ['SMTP_USERNAME']
SMTP_PASS = os.environ['SMTP_PASSWORD']
FROM      = os.environ.get('SMTP_FROM_EMAIL', SMTP_USER)

def send(to, subject, text, html):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = f'Pablo — Vantelia <{FROM}>'
    msg['To']      = to
    msg['Reply-To'] = 'info@vantelia.es'
    msg.attach(MIMEText(text, 'plain', 'utf-8'))
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo(); s.starttls(context=ctx); s.ehlo()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(FROM, [to], msg.as_bytes())
    print(f'  SENT -> {to}')

def sig_html():
    return """<p style="margin-top:20px;font-size:13px;color:#6b7280;line-height:1.6;">
Pablo<br>Fundador, Vantelia<br>
<a href="tel:+34675802001" style="color:#6b7280;">+34 675 802 001</a> ·
<a href="mailto:info@vantelia.es" style="color:#6b7280;">info@vantelia.es</a> ·
<a href="https://vantelia.es" style="color:#6b7280;">vantelia.es</a></p>"""

def sig():
    return "\nPablo\nFundador, Vantelia\n+34 675 802 001 · info@vantelia.es\nvantelia.es"

emails = [
    {
        'to': 'administracion@famsam.es',
        'subject': 'FAMSAM — asistente IA para vuestra gestoría',
        'text': f"""Hola,

Soy Pablo, de Vantelia. Os escribí hace unos días.

He montado una demo con los datos de FAMSAM para que veáis cómo quedaría en vuestra web — respondiendo dudas de clientes sobre servicios, plazos, documentación:

https://app.vantelia.es/demo/demo_auto_famsam_asesores_a70645

Si os parece útil, en 2 minutos está en vuestra web. Gratis para empezar.

¿Le echáis un vistazo?{sig()}""",
        'html': f"""<p>Hola,</p>
<p>Soy Pablo, de Vantelia. Os escribí hace unos días.</p>
<p>He montado una demo con los datos de FAMSAM para que veáis cómo quedaría en vuestra web — respondiendo dudas de clientes sobre servicios, plazos, documentación:</p>
<p style="margin:24px 0;text-align:center;">
<a href="https://app.vantelia.es/demo/demo_auto_famsam_asesores_a70645"
   style="background:linear-gradient(135deg,#0ea5e9,#0284c7);color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
Ver el bot de FAMSAM en vivo</a></p>
<p>Si os parece útil, en 2 minutos está en vuestra web. Gratis para empezar.</p>
<p>¿Le echáis un vistazo?{sig_html()}"""
    },
    {
        'to': 'hola@skinandjoy.com',
        'subject': 'Skin and Joy — tu asistente IA listo',
        'text': f"""Hola,

Soy Pablo, de Vantelia. Os escribí hace unos días sobre un asistente IA para Skin and Joy.

He preparado uno con los datos de vuestro centro para que lo veáis funcionando — responde sobre servicios, reservas y lo que os preguntan a diario:

https://app.vantelia.es/demo/demo_auto_skin_and_joy_bf95a4

Gratis para empezar, sin tarjeta. Si os gusta, en 2 minutos está en vuestra web.

¿Le echais un vistazo?{sig()}""",
        'html': f"""<p>Hola,</p>
<p>Soy Pablo, de Vantelia. Os escribí hace unos días sobre un asistente IA para Skin and Joy.</p>
<p>He preparado uno con los datos de vuestro centro para que lo veáis funcionando — responde sobre servicios, reservas y lo que os preguntan a diario:</p>
<p style="margin:24px 0;text-align:center;">
<a href="https://app.vantelia.es/demo/demo_auto_skin_and_joy_bf95a4"
   style="background:linear-gradient(135deg,#0ea5e9,#0284c7);color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
Ver el bot de Skin and Joy en vivo</a></p>
<p>Gratis para empezar, sin tarjeta. Si os gusta, en 2 minutos está en vuestra web.</p>
<p>¿Le echais un vistazo?{sig_html()}"""
    },
]

for i, e in enumerate(emails):
    if i > 0:
        print('  pausa 20s...')
        time.sleep(20)
    try:
        send(e['to'], e['subject'], e['text'], e['html'])
    except Exception as ex:
        print(f'  ERROR {e["to"]}: {ex}')

print('Done.')
