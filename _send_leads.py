"""Envía emails personalizados a leads calientes."""
import os, smtplib, ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_HOST = os.environ['SMTP_HOST']
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SMTP_USER = os.environ['SMTP_USERNAME']
SMTP_PASS = os.environ['SMTP_PASSWORD']
FROM      = os.environ.get('SMTP_FROM_EMAIL', SMTP_USER)

def send(to, subject, text, html, reply_to='info@vantelia.es'):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = f'Pablo — Vantelia <{FROM}>'
    msg['To']      = to
    msg['Reply-To'] = reply_to
    msg.attach(MIMEText(text, 'plain', 'utf-8'))
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo(); s.starttls(context=ctx); s.ehlo()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(FROM, [to], msg.as_bytes())
    print(f'  SENT -> {to}')

def sig():
    return """
Pablo
Fundador, Vantelia
+34 675 802 001 · info@vantelia.es
vantelia.es"""

def sig_html():
    return """<p style="margin-top:20px;font-size:13px;color:#6b7280;line-height:1.6;">
Pablo<br>Fundador, Vantelia<br>
<a href="tel:+34675802001" style="color:#6b7280;">+34 675 802 001</a> ·
<a href="mailto:info@vantelia.es" style="color:#6b7280;">info@vantelia.es</a> ·
<a href="https://vantelia.es" style="color:#6b7280;">vantelia.es</a>
</p>"""

emails = [
    {
        'to': 'reservas@thenookmadrid.com',
        'subject': 'Re: The Nook — tu bot ya está listo',
        'text': f"""Hola,

Sobre lo que preguntabas: con el código NOOK1MES tienes el primer mes gratis del plan que elijas. Sin permanencia ni tarjeta para empezar.

Para que no tengas que montar nada, te lo he dejado preparado yo con los datos de The Nook. Aquí lo tienes respondiendo como lo haría en tu web — pregúntale por los masajes, las sedes, los horarios:

https://app.vantelia.es/demo/demo_auto_the_nook_940b21

Dime qué te parece — si responde bien o si le falta algo. Lo ajusto en el momento. Y si activamos las reservas, además agenda las sesiones solo.

Si lo prefieres te lo enseño en una llamada de 5 min. Tú dime.
{sig()}""",
        'html': f"""<p>Hola,</p>
<p>Sobre lo que preguntabas: con el código <strong>NOOK1MES</strong> tienes el primer mes gratis del plan que elijas. Sin permanencia ni tarjeta para empezar.</p>
<p>Para que no tengas que montar nada, te lo he dejado preparado yo con los datos de The Nook. Aquí lo tienes respondiendo como lo haría en tu web — pregúntale por los masajes, las sedes, los horarios:</p>
<p style="margin:24px 0;text-align:center;">
<a href="https://app.vantelia.es/demo/demo_auto_the_nook_940b21"
   style="background:linear-gradient(135deg,#0ea5e9,#0284c7);color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
Ver el bot de The Nook en vivo
</a></p>
<p>Dime qué te parece — si responde bien o si le falta algo. Lo ajusto en el momento. Y si activamos las reservas, además agenda las sesiones solo.</p>
<p>Si lo prefieres te lo enseño en una llamada de 5 min. Tú dime.{sig_html()}"""
    },
    {
        'to': 'sap@ginefiv.com',
        'subject': 'Ginefiv — asistente IA listo para probar',
        'text': f"""Hola,

Soy Pablo, de Vantelia. Os escribí hace unos días sobre un asistente IA para la web de Ginefiv.

He preparado una versión con los datos de vuestra clínica para que podáis verlo funcionando antes de decidir nada. Podéis preguntarle sobre tratamientos, proceso de cita, o lo que queráis:

https://app.vantelia.es/demo/demo_auto_ginefiv_6aa2b1

Si responde bien, en 2 minutos está en vuestra web. Si le falta algo, lo ajusto.

Sin coste, sin tarjeta. ¿Le echáis un vistazo?
{sig()}""",
        'html': f"""<p>Hola,</p>
<p>Soy Pablo, de Vantelia. Os escribí hace unos días sobre un asistente IA para la web de Ginefiv.</p>
<p>He preparado una versión con los datos de vuestra clínica para que podáis verlo funcionando antes de decidir nada. Preguntadle sobre tratamientos, proceso de cita, o lo que queráis:</p>
<p style="margin:24px 0;text-align:center;">
<a href="https://app.vantelia.es/demo/demo_auto_ginefiv_6aa2b1"
   style="background:linear-gradient(135deg,#0ea5e9,#0284c7);color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
Ver el bot de Ginefiv en vivo
</a></p>
<p>Si responde bien, en 2 minutos está en vuestra web. Si le falta algo, lo ajusto.</p>
<p>Sin coste, sin tarjeta. ¿Le echáis un vistazo?{sig_html()}"""
    },
    {
        'to': 'administracion@famsam.es',
        'subject': 'FAMSAM — asistente IA para vuestra gestoría',
        'text': f"""Hola,

Soy Pablo, de Vantelia. Os escribí hace unos días.

He montado una demo con los datos de FAMSAM para que veáis cómo quedaría en vuestra web — respondiendo dudas de clientes sobre servicios, plazos, documentación:

https://app.vantelia.es/demo/demo_auto_famsam_asesores_a70645

Si os parece útil, en 2 minutos está en vuestra web. Gratis para empezar.

¿Le echáis un vistazo?
{sig()}""",
        'html': f"""<p>Hola,</p>
<p>Soy Pablo, de Vantelia. Os escribí hace unos días.</p>
<p>He montado una demo con los datos de FAMSAM para que veáis cómo quedaría en vuestra web — respondiendo dudas de clientes sobre servicios, plazos, documentación:</p>
<p style="margin:24px 0;text-align:center;">
<a href="https://app.vantelia.es/demo/demo_auto_famsam_asesores_a70645"
   style="background:linear-gradient(135deg,#0ea5e9,#0284c7);color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
Ver el bot de FAMSAM en vivo
</a></p>
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

¿Le echais un vistazo?
{sig()}""",
        'html': f"""<p>Hola,</p>
<p>Soy Pablo, de Vantelia. Os escribí hace unos días sobre un asistente IA para Skin and Joy.</p>
<p>He preparado uno con los datos de vuestro centro para que lo veáis funcionando — responde sobre servicios, reservas y lo que os preguntan a diario:</p>
<p style="margin:24px 0;text-align:center;">
<a href="https://app.vantelia.es/demo/demo_auto_skin_and_joy_bf95a4"
   style="background:linear-gradient(135deg,#0ea5e9,#0284c7);color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
Ver el bot de Skin and Joy en vivo
</a></p>
<p>Gratis para empezar, sin tarjeta. Si os gusta, en 2 minutos está en vuestra web.</p>
<p>¿Le echais un vistazo?{sig_html()}"""
    },
]

for e in emails:
    try:
        send(e['to'], e['subject'], e['text'], e['html'])
    except Exception as ex:
        print(f'  ERROR {e["to"]}: {ex}')

print('Done.')
