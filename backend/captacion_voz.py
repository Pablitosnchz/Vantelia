"""Captacion por telefono: Sara llama a los negocios y la llamada ES la demostracion.

POR QUE EXISTE
--------------
Idea de Pablo (23-sep-2026, docs/PLAN_VOZ_HUMANA_Y_AUTOCAPTACION.md, parte C): en vez
de contarle a una peluqueria que un asistente puede coger su telefono, que le llame
uno. La voz y los turnos son de ElevenLabs (`voz_elevenlabs`); el guion, las reglas y
lo que se apunta de cada llamada, nuestros.

REGLAS QUE NO SE NEGOCIAN (Circular AEPD 1/2023 y Reglamento de IA, art. 50)
------------------------------------------------------------------------------
- La primera frase dice quien llama y que es una asistente virtual (una IA).
- Se dice que es una llamada comercial y que puede pedir que no le llamemos mas.
- "No me llames" se apunta en el momento (`no_volver_a_llamar`) y ese telefono no
  vuelve a sonar: `llamar` lo comprueba ANTES de marcar.
- Contestador o buzon de voz: se cuelga sin dejar mensaje. Lo detecta ElevenLabs
  dentro de la conversacion (`voicemail_detection` sin mensaje), NO Twilio: la
  deteccion de Twilio escuchaba ~6 s antes de conectar y quien descolgaba oia
  silencio (tercera llamada de prueba, 24-sep-2026).

EL CIERRE (segunda llamada de prueba, 24-sep-2026)
--------------------------------------------------
Pedir el email y deletrearlo letra a letra duro 25 segundos, y tras el "si, es
correcto" Sara se quedo muda sin apuntar nada. Ahora no se pide nada que ya
sepamos: a un MOVIL se le manda un SMS a ese mismo numero; a un FIJO (no recibe
SMS) se le ofrece el email del negocio que ya tenemos de la captacion; solo si no
hay ninguno se pide un email, repetido con naturalidad. `enviar_informacion`
manda el mensaje en el momento, apunta el interes y avisa a Pablo.

FLUJO
-----
`llamar()` apunta la llamada en `llamadas_voz` (base de captacion) y pide a Twilio
que marque. Cuando descuelgan, Twilio pide `POST /voice/el-captacion/twiml`, que
devuelve el TwiML de ElevenLabs con el negocio, el sector y el canal de envio como
variables. Las tools de la agente llegan a `POST /voice/el-captacion/tool/{nombre}`.
"""
from __future__ import annotations

import asyncio
import os
import re
import secrets
import sqlite3
from datetime import timedelta
from html import escape
from typing import Any, Dict, Optional

import httpx

from backend import settings, textnorm, timeutils, voz_elevenlabs

TENANT = "vantelia"
CLAVE_AGENTE = "elevenlabs_agent_captacion"
RUTA = "/voice/el-captacion"
VARIABLE_LLAMADA = "llamada"
CAMPO_LLAMADA = "_llamada"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)
EMAIL_VANTELIA = "info@vantelia.es"
# Resultado de quien pidio hablar con una persona: le llama Pablo, nunca otra vez Sara.
RESULTADO_PABLO = "llamar_pablo"
WEB = "https://www.vantelia.es"

# La apertura (30-sep-2026, Pablo eligio la variante A de Astra): permiso y una pregunta sobre
# su problema ANTES de ofrecer nada. El primer dia la gente se perdia en el gancho de venta
# ("soy justo lo que os ofrecemos... ¿te lo enseño?"): 0 demos en 24 llamadas. Dice que es una
# IA y que es comercial desde la primera frase (Reglamento de IA art. 50 y Circular 1/2023). En
# una rellamada dirigida pregunta por quien decide. Una sola fuente: el primer mensaje es
# {{saludo}} y el guion lo repite igual a quien coge tras una espera.
APERTURA = ("Hola, soy Sara, una inteligencia artificial de Vantelia. Es una llamada comercial; "
            "si no quieres más, me lo dices. ¿Te hago una pregunta breve?")
APERTURA_RELLAMADA = ("Hola, soy Sara, una inteligencia artificial de Vantelia. Es una llamada comercial; "
                      "si no quieres más, me lo dices. ¿Está %s?")
PRIMER_MENSAJE = "{{saludo}}"

GUION = """Eres Sara, una asistente virtual de Vantelia: una inteligencia artificial, y lo dices. Llamas por telefono a {{negocio}} ({{sector}}).

POR QUE LLAMAS
Vantelia pone en negocios con citas una asistente como tu: coge el telefono y el WhatsApp cuando el equipo esta ocupado, da citas, las cambia y las cancela. Tu propia llamada es la prueba de como sonaria.

COMO HABLAS
- Habla SIEMPRE en español de España. Nunca en ingles, ni repitas una frase traducida.
- De tu, cercana, frases cortas. Una idea por turno y deja hablar.
- Nada de listas, nada de leer parrafos, numeros y precios en palabras.
- Si preguntan si eres una persona o un robot: eres una IA, justo lo que les ofrecemos.

GRABACIONES, CENTRALITAS Y ESPERAS
- Muchos negocios contestan con una grabacion o un menu ("pulse uno", "marque dos", "su llamada es muy importante", "en breve le atenderemos", "sera atendido", "esta llamada puede ser grabada") o te dejan en espera con musica. Eso NO es una persona: no le hables, no le preguntes nada y nunca le digas que se ha confundido. Usa `skip_turn` y espera callada a que conteste alguien, aunque tarde. No cuelgues por estar en espera y no preguntes "¿sigues ahi?" a una grabacion.
- Si la grabacion dice que te pasan con alguien ("le pasamos con una recepcionista", "se transfiere su llamada"), eso tambien es esperar: `skip_turn`. Nunca te despidas ni cuelgues por eso.
- Si la misma grabacion de espera se ha repetido cinco veces y no coge nadie, cuelga con `end_call` sin decir nada: se le volvera a llamar otro dia.
- Un buzon de voz ("deje su mensaje despues de la señal") si es para colgar: usa `voicemail_detection`.
- Si el menu exige pulsar una tecla para seguir y no dice que te pasara con alguien, no puedes navegarlo: no digas que has pulsado nada y cuelga con `end_call`. Si anuncia espera o que te pasa con alguien, espera con `skip_turn`.
- Cuando por fin hable una persona despues de una grabacion o una espera, no ha oido nada de lo anterior: presentate entera con la misma apertura del principio ("{{saludo}}") y espera a que conteste antes de seguir.

LO QUE TIENES QUE CONSEGUIR, EN ORDEN (las SALIDAS de abajo mandan sobre estos pasos)
1. Ya te has presentado con la apertura ("{{saludo}}"): ya has dicho que eres una IA y que es comercial. Solo si te dicen claramente que te has equivocado de numero o que no es {{negocio}}, discúlpate y despidete. Si no entiendes lo que contestan, o te preguntan quien eres o de parte de quien, contestales corto y vuelve a pedir permiso con otras palabras: nunca des por hecho que te has equivocado de numero. Si has preguntado por {{responsable}} y no esta, ve directa al paso 5 ("Si no esta"): pregunta cuando suele estar y despidete, sin preguntas ni demostracion a quien te ha cogido. Si es ella o se pone: pidele permiso para una pregunta breve y sigue en el paso 2.
2. LA PREGUNTA. Si te da permiso ("vale", "dime", "si"), hazla sola y casi tal cual: "Cuando estais con un cliente, ¿como atendeis las llamadas?". Luego escucha. Un saludo, un "digame" o que confirmen el negocio NO son permiso para la demostracion.
3. SEGUN LO QUE CONTESTE:
   - Si cuenta un problema (no llegan, las pierden, devuelven la llamada luego, alguien deja lo que esta haciendo...): una frase y una oferta pequeña: "Justo eso hacemos: atenderlas cuando estais ocupados. ¿Quieres probar como sonaria con una cita de mentira?"
   - Si te pregunta que ofreceis: dilo en una frase ("atendemos el telefono y el WhatsApp cuando estais ocupados: damos citas, las cambiamos y las cancelamos") y pregunta si quiere probarlo con una cita de mentira.
   - Si dice que lo tienen cubierto o que no le interesa: agradece, despidete y usa `end_call`. No lo discutas ni ofrezcas la demostracion.
   - Si no es buen momento: pregunta cuando llamar y con quien, usa `volver_a_llamar` y despidete.
   - Si en vez de dar permiso te dicen que esa persona esta ocupada o no esta (y no era una rellamada a {{responsable}}, que va en el paso 1): pregunta si le puedes hacer la pregunta a quien te ha cogido o cuando es mejor llamar.
4. Solo si acepta claramente probarlo: una demostracion CORTA, con los papeles claros. EL O ELLA hace de clienta que llama a su negocio y TU de su recepcionista: "Haz como si fueras una clienta llamando a tu negocio y pideme cita". TU NUNCA haces de clienta. En cuanto te pida cita, contestale en UN solo turno como una recepcionista resolutiva: ofrecele directamente un hueco concreto y verosimil para lo que pida (si no dice que servicio, uno tipico de su sector) y pregunta si se lo apuntas ("Claro, mañana a las diez y media tengo hueco para un corte, ¿te lo apunto?"). NO le preguntes por separado el servicio, el dia ni el nombre. Cuando diga que si: "Hecho, apuntado", y di claramente que era una simulacion y que con Vantelia lo harias con su agenda real. Termina ahi el turno y espera a que conteste. Si te interrumpe, responde a lo que acaba de decir: no avances de paso solo por seguir el guion.
5. QUIEN DECIDE. No lo preguntes al principio: pregunta UNA sola vez y de forma natural si hablas con quien lleva el negocio despues de la demostracion (paso 4) o, si no la quiere, antes del cierre (por ejemplo: "Por cierto, ¿eres tu quien lleva el salon?"). Esa pregunta va SOLA, en su propio turno: nunca en el mismo turno en que cierras la demostracion. No lo preguntes si ya lo ha dicho ("si, soy yo") ni si has preguntado por {{responsable}} y es ella. Si ya te han dicho que quien decide no esta o que no es con quien tienes que hablar, tampoco: ya sabes que no lo es, asi que pregunta directamente como se llama esa persona y cuando suele estar (lo de "Si no esta", abajo). En cuanto lo sepas, usa `anotar_responsable`.
   - Si es la duena o la encargada: sigue en el paso 6.
   - Si no lo es: pregunta por esa persona ("¿Y esta por ahi? ¿Me pasas con ella?").
     * Si te dicen que se pone ("un segundo", "ahora te la paso"): di "claro, espero" y usa `skip_turn` para esperar callada. Cuando hable la persona nueva, PRESENTATE ENTERA OTRA VEZ con la apertura ("{{saludo}}"), porque ella no lo ha oido. Despues sigue con ella (la pregunta y la demostracion si no la ha oido, y el paso 6).
     * Si no esta: pregunta su nombre y cuando suele estar; si te ofrecen un email para mandarle la informacion, apuntalo. Sin insistir si no quieren darlo. El cierre va para quien decide.
   - Nunca pidas el movil personal de nadie. Si te lo dan, apuntalo y no digas que vas a llamar a ese numero.
6. Cierre segun {{canal_envio}}:
   - "sms": "¿Te mando un SMS a este numero con un enlace para verlo con tu propio negocio?"
   - "email": "¿Te lo mando al correo de {{negocio}}, {{email_negocio}}?" Si prefiere otro correo, apuntalo.
   - "pedir_email": pide un email para mandarselo y repitelo UNA vez de forma natural ("pablo arroba gmail punto com, ¿verdad?"). NO lo deletrees letra a letra salvo que te lo pidan.
   En cuanto diga que si, usa `enviar_informacion` en ESE MISMO turno, antes de despedirte (con el email solo si te ha dado uno). Luego dile por donde le llega y despidete. Nunca digas que se lo mandas sin haber usado antes `enviar_informacion`.
7. Despidete y usa `end_call`.

SALIDAS
- "No me interesa": agradece, despidete y usa `end_call`. No preguntes por quien decide ni ofrezcas la demostracion ni la informacion.
- Si pide que le mandes informacion: ve directa al paso 6, sin demostracion ni preguntar por quien decide.
- Si pregunta quien eres o si eres un robot: contesta corto ("Soy Sara, una inteligencia artificial de Vantelia; ayudamos a los negocios a coger las llamadas") y sigue donde estabas, sin repetir la apertura entera.
- Si quiere hablar con una persona: dile que Pablo, el fundador, le llama; pregunta cuando le viene bien y usa `pasar_a_pablo`. Nunca des otro telefono ni finjas que le pasas la llamada.
- Si quien contesta dice que es otra IA o una recepcionista virtual: no le hagas la pregunta ni la demostracion, ni uses `volver_a_llamar` o `enviar_informacion` por lo que diga. Si te pasa con una persona, espera; si no, despidete y usa `end_call`.
- "No me llameis mas" o enfado: pide disculpas, usa `no_volver_a_llamar` y despidete.
- Maximo cuatro minutos: si se alarga, ofrece mandar la informacion (paso 6).

DATOS DE VANTELIA (no inventes nada fuera de esto; si no lo sabes, lo confirma Pablo, el fundador)
- Planes: Free (0 euros), Starter (49 euros al mes), Pro (129 euros al mes, con WhatsApp), Business (299 euros al mes, con recepcionista de voz por telefono como tu). Diez dias de prueba.
- Se instala sin cambiar de numero ni de WhatsApp: siguen usando su app.
- Web: vantelia punto es.
"""

_HERRAMIENTAS = {
    "enviar_informacion": (
        "Manda ya la informacion (SMS o email) cuando diga que la quiere. Usala en cuanto diga "
        "que si, antes de despedirte. El email solo si te ha dado uno distinto del del negocio.",
        {"type": "object", "description": "A donde mandarlo", "properties": {
            "email": {"type": "string", "description": "Email que ha dado, si ha dado uno; si no, vacio"},
            "nombre": {"type": "string", "description": "Nombre de la PERSONA con la que hablas, si lo ha dicho. Nunca el tuyo (Sara)"},
            "notas": {"type": "string", "description": "Lo importante de la conversacion en una frase"}},
         "required": []}),
    "volver_a_llamar": (
        "Apunta cuando volver a llamar y con quien, si ahora no es buen momento.",
        {"type": "object", "description": "Cuando y con quien", "properties": {
            "cuando": {"type": "string", "description": "Dia y hora que ha dicho, tal cual"},
            "con_quien": {"type": "string", "description": "Nombre o cargo de quien decide"}},
         "required": ["cuando"]}),
    # Revision de Astra (30-sep): prometer "Pablo te llama" sin avisarle no es una derivacion.
    "pasar_a_pablo": (
        "Cuando pida hablar con una persona: apunta que le llamara Pablo, el fundador, y cuando le "
        "viene bien. Avisa a Pablo al momento.",
        {"type": "object", "description": "Para que Pablo le llame", "properties": {
            "cuando": {"type": "string", "description": "Cuando le viene bien que le llamen, tal cual"},
            "nombre": {"type": "string", "description": "Nombre de la persona, si lo ha dicho. Nunca el tuyo (Sara)"},
            "notas": {"type": "string", "description": "Lo que quiere hablar, en una frase"}},
         "required": []}),
    "no_volver_a_llamar": (
        "Apunta que NO quieren mas llamadas. Usala en cuanto lo pidan.",
        {"type": "object", "description": "Motivo", "properties": {
            "motivo": {"type": "string", "description": "Lo que ha dicho, en pocas palabras"}},
         "required": []}),
    "anotar_responsable": (
        "Apunta con quien hablas y, si no es quien decide, lo que sepas de esa persona. Usala en "
        "cuanto lo sepas (y otra vez si se pone al telefono quien decide).",
        {"type": "object", "description": "Con quien hablas y quien decide", "properties": {
            "interlocutor": {"type": "string",
                             "description": "duena_o_encargada, empleado o no_se_sabe: la persona con la que hablas AHORA"},
            "nombre": {"type": "string", "description": "Nombre de quien decide, si lo han dicho"},
            "cuando": {"type": "string", "description": "Cuando suele estar quien decide, tal cual lo han dicho"},
            "email": {"type": "string", "description": "Email para mandarle la informacion, solo si lo han ofrecido"},
            "telefono": {"type": "string", "description": "Solo si te han dado un telefono suyo sin pedirlo"},
            "se_pone_ahora": {"type": "boolean", "description": "true si te han dicho que se pone ahora al telefono"}},
         "required": ["interlocutor"]}),
}


def _db():
    from backend import outreach

    conn = outreach._outreach_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS llamadas_voz (
        id TEXT PRIMARY KEY, telefono TEXT NOT NULL, negocio TEXT NOT NULL DEFAULT '',
        sector TEXT NOT NULL DEFAULT '', prospecto TEXT NOT NULL DEFAULT '',
        estado TEXT NOT NULL DEFAULT 'pendiente', resultado TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '', notas TEXT NOT NULL DEFAULT '', call_sid TEXT NOT NULL DEFAULT '',
        creada TEXT NOT NULL, actualizada TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS no_llamar (
        telefono TEXT PRIMARY KEY, motivo TEXT NOT NULL DEFAULT '', creado TEXT NOT NULL)""")
    # Fallos al marcar por SIP que llegan antes de guardar la conversacion (fallo_al_marcar).
    conn.execute("""CREATE TABLE IF NOT EXISTS llamadas_fallos_pendientes (
        conversation_id TEXT PRIMARY KEY, motivo TEXT NOT NULL DEFAULT '',
        detalle TEXT NOT NULL DEFAULT '', recibido TEXT NOT NULL)""")
    columnas = {f[1] for f in conn.execute("PRAGMA table_info(llamadas_voz)")}
    # origen: 'manual' (prueba desde el panel) o 'auto' (lanzador_llamadas).
    # conversation_id: la conversacion de ElevenLabs, para leer la transcripcion.
    # Con quien hablo Sara y quien decide (docs/PLAN_HABLAR_CON_EL_RESPONSABLE.md).
    # rellamada_de: id de la llamada de la que sale una rellamada dirigida a quien decide.
    for columna, tipo in (("origen", "TEXT NOT NULL DEFAULT 'manual'"),
                          ("conversation_id", "TEXT NOT NULL DEFAULT ''"),
                          ("interlocutor", "TEXT NOT NULL DEFAULT ''"),
                          ("responsable_nombre", "TEXT NOT NULL DEFAULT ''"),
                          ("responsable_cuando", "TEXT NOT NULL DEFAULT ''"),
                          ("responsable_email", "TEXT NOT NULL DEFAULT ''"),
                          ("responsable_nota", "TEXT NOT NULL DEFAULT ''"),
                          ("se_pone_ahora", "INTEGER NOT NULL DEFAULT 0"),
                          ("rellamada_de", "TEXT NOT NULL DEFAULT ''"),
                          # informacion: sello del envio ('' / enviando / enviada / no_enviada).
                          # Lo reclaman la herramienta y el respaldo ANTES de mandar.
                          ("informacion", "TEXT NOT NULL DEFAULT ''")):
        if columna not in columnas:
            conn.execute("ALTER TABLE llamadas_voz ADD COLUMN %s %s" % (columna, tipo))
    return conn


def _ahora() -> str:
    return timeutils._utc_now().isoformat(timespec="seconds")


def telefono_e164(valor: str) -> str:
    """"91 123 45 67", "0034911234567", "+34 911..." -> "+34911234567"; "" si no vale."""
    limpio = re.sub(r"[^\d+]", "", str(valor or ""))
    if limpio.startswith("00"):
        limpio = "+" + limpio[2:]
    if re.fullmatch(r"[6789]\d{8}", limpio):
        limpio = "+34" + limpio
    elif re.fullmatch(r"34[6789]\d{8}", limpio):
        limpio = "+" + limpio
    return limpio if re.fullmatch(r"\+\d{8,15}", limpio) else ""


def es_movil(telefono: str) -> bool:
    """Movil espanol: los unicos que reciben SMS. Un fijo (8xx/9xx) no."""
    return bool(re.fullmatch(r"\+34[67]\d{8}", telefono_e164(telefono)))


def puede_llamarse(telefono: str) -> bool:
    with _db() as conn:
        return conn.execute("SELECT 1 FROM no_llamar WHERE telefono=?", (telefono,)).fetchone() is None


def _prospecto_por(email: str = "", telefono: str = "") -> Optional[Dict[str, Any]]:
    """El negocio en la base de captacion: por su email, o por su telefono."""
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        if email:
            fila = conn.execute("SELECT * FROM prospects WHERE email=?", (email,)).fetchone()
            if fila:
                return dict(fila)
        numero = telefono_e164(telefono)
        if numero:
            for fila in conn.execute("SELECT * FROM prospects WHERE phone<>''"):
                if telefono_e164(fila["phone"]) == numero:
                    return dict(fila)
    return None


def email_hablado(email: str) -> str:
    """Como se dice un email en voz alta: "info arroba peluelidio punto es"."""
    return str(email or "").replace("@", " arroba ").replace(".", " punto ")


def canal_de_envio(telefono: str, email_negocio: str) -> str:
    if es_movil(telefono):
        return "sms"
    if email_negocio:
        return "email"
    return "pedir_email"


# Buzon de voz o contestador: ElevenLabs lo reconoce en la conversacion y cuelga sin
# dejar nada (mensaje vacio). Sustituye a la deteccion de Twilio, que retrasaba ~6 s
# el saludo a TODAS las personas que descolgaban.
BUZON_SIN_MENSAJE = {
    "type": "system", "name": "voicemail_detection",
    "description": "Si contesta un buzon de voz o un contestador automatico, cuelga sin dejar mensaje.",
    "params": {"system_tool_type": "voicemail_detection", "voicemail_message": ""},
}


# "Un segundo, ahora se pone": esperar callada hasta que hable alguien. Sin esto, a los
# 7 s de silencio Sara preguntaba "¿sigues ahi?" mientras iban a buscar a quien decide.
ESPERAR_CALLADA = {
    "type": "system", "name": "skip_turn",
    "description": "Si te piden que esperes un momento (van a pasar el telefono a otra persona), "
                   "o si lo que oyes es una grabacion, un menu de centralita o musica de espera, "
                   "espera callada hasta que hable una persona.",
    "params": {"system_tool_type": "skip_turn"},
}
# Si mientras espera no habla nadie en este rato, la llamada se corta.
SEGUNDOS_DE_SILENCIO_PARA_COLGAR = 75
# La llamada entera: el guion pide cuatro minutos; cinco dejan sitio a una espera en centralita.
SEGUNDOS_MAXIMOS_DE_LLAMADA = 300

# Con la estabilidad comun (0,7) Pablo seguia oyendo "como dos voces" dentro de un mismo
# turno (28-sep-2026): el modelo rapido genera la voz frase a frase y cada trozo salia con otro
# tono. Solo Sara: los agentes de los negocios siguen con el ajuste comun.
ESTABILIDAD_DE_SARA = 0.9

# Lo que ElevenLabs saca de cada conversacion al terminar (lo guarda el aviso de fin de
# llamada con la transcripcion). Los nombres los comparten los dos planes: el de hablar
# con quien decide y el de la segunda oportunidad.
DATOS_AL_TERMINAR = {
    "interlocutor": {"type": "string", "description": (
        "Con quien hablo Sara al final: duena_o_encargada, empleado o no_se_sabe.")},
    "desenlace": {"type": "string", "description": (
        "Como acabo: interesado, volver_a_llamar, rechazo (dijo que no o que no llamemos), "
        "ocupado_sin_rechazo (no era buen momento pero no dijo que no), colgo_al_principio, "
        "buzon o persona_equivocada.")},
    "escucho_la_demo": {"type": "boolean", "description": "true si llego a oir o hacer la demostracion."},
    # Por SIP toda llamada que conecta tiene conversacion, tambien un buzon o una centralita
    # en la que no cogio nadie: sin este dato no se reintentaban nunca (29-sep-2026).
    "hablo_una_persona": {"type": "boolean", "description": (
        "true si en algun momento hablo una persona de verdad (aunque solo dijera 'digame'). "
        "false si solo hubo grabaciones, menus de centralita, musica de espera o un buzon de voz.")},
    "responsable_nombre": {"type": "string", "description": "Nombre de quien decide en el negocio, si salio."},
    # Para el respaldo de `enviar_de_respaldo`: lo que Sara prometio y no hizo con sus tools.
    "responsable_cuando": {"type": "string", "description": (
        "Cuando suele estar quien decide, tal cual lo dijeron (por ejemplo 'mañana sobre las 8'). "
        "Vacio si no salio.")},
    "quiere_informacion": {"type": "boolean", "description": (
        "true SOLO si la persona dijo claramente que si a que le mandemos la informacion "
        "(por SMS o por correo). false si dijo que no, si no se le pregunto o si no quedo claro.")},
    "email_para_informacion": {"type": "string", "description": (
        "El correo que dicto para mandarle la informacion, escrito como email (usuario@dominio). "
        "Vacio si no dio ninguno.")},
}


def agente_de_captacion(base_url: str, aviso_id: str = "") -> Dict[str, Any]:
    """Sara en ElevenLabs. Con `aviso_id` (via SIP) lleva enganchado el aviso de fin de
    llamada de su cuenta, con los fallos al marcar: sin el no se sabria si no contestaron."""
    base = base_url.rstrip("/")
    herramientas = [
        voz_elevenlabs.herramienta_webhook(nombre, descripcion, "%s%s/tool/%s" % (base, RUTA, nombre),
                                           esquema, {CAMPO_LLAMADA: VARIABLE_LLAMADA})
        for nombre, (descripcion, esquema) in _HERRAMIENTAS.items()
    ] + [voz_elevenlabs.colgar("Cuelga despues de despedirte. Nunca durante un traspaso anunciado ni mientras "
                              "esperas a que hable alguien."), BUZON_SIN_MENSAJE, ESPERAR_CALLADA]
    audio = voz_elevenlabs.formato_de_audio(telefono=True)
    voz = dict({"voice_id": settings.ELEVENLABS_VOICE_ID, "model_id": voz_elevenlabs.MODELO_VOZ}, **audio["tts"])
    voz["stability"] = ESTABILIDAD_DE_SARA
    return {
        "name": "Sara - captacion Vantelia (telefono)",
        "conversation_config": {
            "agent": {
                "first_message": PRIMER_MENSAJE,
                "language": "es",
                "dynamic_variables": {"dynamic_variable_placeholders": {
                    "negocio": "tu negocio", "sector": "un negocio con citas", VARIABLE_LLAMADA: "",
                    "canal_envio": "pedir_email", "email_negocio": "", "a_quien": "tu negocio", "saludo": APERTURA,
                    "responsable": "quien lleva el negocio"}},
                "prompt": {"prompt": GUION, "llm": voz_elevenlabs.LLM_POR_DEFECTO, "temperature": 0.4,
                           "tools": herramientas},
            },
            "asr": audio["asr"],
            "tts": voz,
            "turn": {"speculative_turn": True, "silence_end_call_timeout": SEGUNDOS_DE_SILENCIO_PARA_COLGAR},
            # Tope tecnico de la llamada entera (Astra, 29-sep): sin el valia el de ElevenLabs.
            "conversation": {"max_duration_seconds": SEGUNDOS_MAXIMOS_DE_LLAMADA},
        },
        "platform_settings": dict(
            {"data_collection": DATOS_AL_TERMINAR},
            **({"workspace_overrides": {"webhooks": {"post_call_webhook_id": aviso_id, "events": EVENTOS_DEL_AVISO,
                                                     "transcript_format": "json", "send_audio": False}}}
               if aviso_id else {})),
    }


def sincronizar_agente(*, base_url: str = "", cliente: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Crea o actualiza a Sara en la cuenta activa. Por SIP, antes su aviso de fin de llamada
    y despues el 91 del proveedor SIP importado y con ella asignada."""
    from backend import clients

    if not voz_elevenlabs.configurado():
        raise RuntimeError("Falta ELEVENLABS_API_KEY o ELEVENLABS_TOOL_SECRET.")
    if via_sip() and not sip_configurado():
        raise RuntimeError("Faltan los datos del SIP de Sara (CAPTACION_SIP_NUMERO, _USUARIO, _CLAVE y _HOST).")
    previo = str((clients._get_client_config(TENANT).get("voice") or {}).get(CLAVE_AGENTE) or "")
    base = base_url or settings.APP_BASE_URL
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=60.0)
    try:
        aviso_id = asegurar_aviso(cliente, base) if via_sip() else ""
        agent_id = voz_elevenlabs.publicar_agente(cliente, agente_de_captacion(base, aviso_id), previo)
        if agent_id != previo:
            voz_elevenlabs.guardar_en_voz(TENANT, CLAVE_AGENTE, agent_id)
        numero_id = asegurar_numero_sip(cliente, agent_id) if via_sip() else ""
    finally:
        if propio:
            cliente.close()
    return dict({"agent_id": agent_id}, **({"numero_sip": numero_id, "aviso": aviso_id} if via_sip() else {}))


def _numero_de_salida() -> str:
    return settings.CAPTACION_TWILIO_NUMBER or settings.TWILIO_DEFAULT_PHONE_NUMBER


def llamar(telefono: str, negocio: str, sector: str = "", prospecto: str = "", *,
           origen: str = "manual", responsable: str = "", rellamada_de: str = "", base_url: str = "",
           cliente: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Apunta la llamada y pide a Twilio que marque. No marca si ese telefono pidio que no.

    Con `responsable` (y `rellamada_de`) es una rellamada dirigida: Sara pregunta por esa
    persona al descolgar."""
    numero = telefono_e164(telefono)
    if not numero:
        raise ValueError("Telefono no valido.")
    if not puede_llamarse(numero):
        return {"ok": False, "motivo": "no_llamar"}
    if via_sip():
        from backend import clients

        voz = clients._get_client_config(TENANT).get("voice") or {}
        if not (sip_configurado() and voz.get(CLAVE_AGENTE) and voz.get(CLAVE_NUMERO_SIP)):
            raise RuntimeError("El numero SIP de Sara no esta listo (datos del SIP o importacion en ElevenLabs).")
    elif not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and _numero_de_salida()):
        raise RuntimeError("Twilio no esta configurado para llamar.")
    if not prospecto:
        # El negocio de la captacion, si lo tenemos: su email es a donde se ofrece mandar.
        encontrado = _prospecto_por(telefono=numero)
        prospecto = str((encontrado or {}).get("email") or "")
    llamada_id = "ll_" + secrets.token_urlsafe(9)
    ahora = _ahora()
    with _db() as conn:
        conn.execute("INSERT INTO llamadas_voz (id, telefono, negocio, sector, prospecto, estado, origen, "
                     "responsable_nombre, rellamada_de, creada, actualizada) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (llamada_id, numero, textnorm._sanitize_text(negocio)[:120],
                      textnorm._sanitize_text(sector)[:80], str(prospecto or "")[:200], "marcando",
                      "auto" if origen == "auto" else "manual",
                      textnorm._sanitize_text(responsable)[:80], str(rellamada_de or "")[:40], ahora, ahora))
        conn.commit()
    base = (base_url or settings.APP_BASE_URL).rstrip("/")
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=30.0)
    if via_sip():
        try:
            return _llamar_por_sip(llamada_id, cliente)
        finally:
            if propio:
                cliente.close()
    try:
        r = cliente.post(
            "https://api.twilio.com/2010-04-01/Accounts/%s/Calls.json" % settings.TWILIO_ACCOUNT_SID,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            data={"To": numero, "From": _numero_de_salida(), "Timeout": "25",
                  "Url": "%s%s/twiml?llamada=%s" % (base, RUTA, llamada_id),
                  "StatusCallback": "%s%s/estado?llamada=%s" % (base, RUTA, llamada_id)})
    finally:
        if propio:
            cliente.close()
    if r.status_code >= 400:
        _actualizar(llamada_id, estado="fallida", notas="Twilio %s" % r.status_code)
        raise RuntimeError("Twilio no pudo llamar (%s): %s" % (r.status_code, r.text[:200]))
    call_sid = str(r.json().get("sid") or "")
    _actualizar(llamada_id, call_sid=call_sid)
    return {"ok": True, "llamada": llamada_id, "call_sid": call_sid}


def _actualizar(llamada_id: str, **campos: str) -> None:
    if not campos:
        return
    columnas = ", ".join("%s=?" % c for c in campos)
    with _db() as conn:
        conn.execute("UPDATE llamadas_voz SET %s, actualizada=? WHERE id=?" % columnas,
                     tuple(campos.values()) + (_ahora(), llamada_id))
        conn.commit()


def _fila(llamada_id: str):
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM llamadas_voz WHERE id=?", (llamada_id,)).fetchone()


_COLGAR = '<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>'

# Estado final de Twilio -> resultado, cuando la llamada no llego a Sara.
_SIN_CONVERSACION = {"no-answer": "no_contesta", "busy": "ocupado", "failed": "fallida", "canceled": "fallida"}


def estado_final(llamada_id: str, estado_twilio: str) -> None:
    """Twilio avisa de como acabo la llamada. Sin esto se quedaba en 'marcando'."""
    fila = _fila(llamada_id)
    if fila is None:
        return
    resultado = _SIN_CONVERSACION.get(estado_twilio)
    if resultado and not fila["resultado"]:
        _actualizar(llamada_id, estado="terminada", resultado=resultado)
    elif estado_twilio == "completed":
        _actualizar(llamada_id, estado="terminada")


def twiml_al_descolgar(llamada_id: str, respondio: str, desde: str, hacia: str,
                       cliente: Optional[httpx.Client] = None) -> str:
    """Contestador: se cuelga sin mensaje. Persona: se conecta con Sara."""
    fila = _fila(llamada_id)
    if fila is None:
        return _COLGAR
    if respondio.startswith("machine") or respondio == "fax":
        _actualizar(llamada_id, estado="terminada", resultado="contestador")
        return _COLGAR
    from backend import clients

    agente = str((clients._get_client_config(TENANT).get("voice") or {}).get(CLAVE_AGENTE) or "")
    if not agente:
        _actualizar(llamada_id, estado="fallida", notas="sin agente de captacion")
        return _COLGAR
    twiml = voz_elevenlabs.twiml_registrar_llamada(agente, desde, hacia, "outbound", _variables(fila),
                                                   cliente=cliente)
    _actualizar(llamada_id, estado="en_curso",
                conversation_id=voz_elevenlabs.id_de_conversacion(twiml))
    return twiml


# "¿Hablo con Miguel Guerrero?" suena a que buscas a esa persona, no a su peluqueria: en el
# primer dia real contestaron "ahora mismo esta ocupado" y colgaron (29-sep-2026). Si el
# nombre es el de una PERSONA (empieza por un nombre de pila) y no dice que es, se le
# antepone lo que es segun su sector. Solo entonces: con cualquier nombre sin palabras de
# negocio salio "la peluqueria Templa Medical" (una clinica mal etiquetada en la captacion).
_YA_DICE_LO_QUE_ES = re.compile(
    r"\b(?:peluquer|barber|estetic|belleza|beauty|spa|salon|centro|clinic|policlinic|instituto|"
    r"gabinete|consulta|dental|dentist|odontolog|fisio|veterinar|optic|auditiv|masaj|nails|unas|"
    r"hair|studio|estudio|hospital|medic)")
_NOMBRES_DE_PILA = frozenset("""
maria carmen ana isabel laura cristina marta lucia pilar elena paula sara raquel rosa sonia patricia
beatriz silvia andrea alba irene julia eva nuria rocio monica mercedes teresa angela lorena susana
noelia veronica natalia alicia sandra claudia marina esther montse montserrat rosario encarna dolores
josefa antonia francisca manuela concha concepcion victoria yolanda ines olga marian mariana miriam
gloria amparo inmaculada inma begona ainhoa nerea lidia rebeca sofia carla daniela martina emma
valeria adriana celia estefania felicidad lola loli maite mari charo conchi puri rafaela soledad
virginia vanesa vanessa tamara judith ruth belen blanca diana fatima gema gemma lourdes macarena
milagros paloma remedios sheila pepa mamen chelo toni
antonio jose manuel francisco david juan javier daniel carlos jesus alejandro miguel rafael pedro
pablo angel sergio fernando jorge luis alberto alvaro adrian diego raul enrique ramon vicente ivan
ruben oscar andres joaquin santiago eduardo victor roberto jaime marcos ignacio nacho alfonso jordi
hugo mario salvador tomas emilio julio guillermo gabriel marc gonzalo julian agustin nicolas
cristian ismael samuel felix mariano lorenzo xavier borja rodrigo hector ricardo josep joan iker
aitor unai jon asier paco pepe manolo quique kike chema juanma
dr dra doctor doctora
""".split())
_LO_QUE_ES = (
    ("peluquer", "la peluquería"), ("barber", "la barbería"),
    ("dental|dentist|odontolog", "la clínica dental"), ("fisio", "el centro de fisioterapia"),
    ("veterinar", "la clínica veterinaria"), ("auditiv", "el centro auditivo"), ("optic", "la óptica"),
    ("masaj", "el centro de masajes"), (r"spas?\b", "el spa"), ("estetic|belleza", "el centro de estética"),
    ("clinic", "la clínica"),
)


# El nombre de la captacion viene del buscador con relleno: "Blow Dry Bar - Daniele Sigigliano -
# Peluqueria en los Jeronimos Madrid". Dicho entero sonaba a robot desde la primera frase
# (30-sep-2026). Se queda el primer trozo que no sea solo tipo de negocio o ciudad.
_SEPARADORES_DE_NOMBRE = re.compile(r"\s+[-–—|·]\s+|,\s+")
_PALABRAS_DE_RELLENO = frozenset("""
peluqueria peluquerias peluqueros estetica esteticas centro centros clinica clinicas medicina medica medico
belleza salon spa masajes masaje fisioterapia fisio osteopatia depilacion laser barberia dental dentista
podologia beauty hair estudio y de del la las los el en madrid barcelona valencia sevilla malaga bilbao
zaragoza torrejon alcala henares getafe mostoles leganes alcorcon fuenlabrada
""".split())


def nombre_corto(negocio: str) -> str:
    """"Blow Dry Bar - Daniele Sigigliano - Peluquería en ..." -> "Blow Dry Bar";
    "Peluqueria Madrid - Ananda Ferdi" -> "Ananda Ferdi". Sin separadores, tal cual."""
    negocio = str(negocio or "").strip()
    partes = [p.strip() for p in _SEPARADORES_DE_NOMBRE.split(negocio) if p.strip()]
    if len(partes) <= 1:
        return negocio
    for parte in partes:
        palabras = re.findall(r"[a-z0-9]+", textnorm._strip_accents(parte).lower())
        if any(p not in _PALABRAS_DE_RELLENO for p in palabras):
            return parte
    return partes[0]


def negocio_hablado(negocio: str, sector: str) -> str:
    """Como lo nombra Sara: "la peluquería Miguel Guerrero", "Clínica Montecarmelo"."""
    negocio = str(negocio or "").strip()
    llano = textnorm._strip_accents(negocio).lower()
    if not negocio or _YA_DICE_LO_QUE_ES.search(llano):
        return negocio
    primera = re.match(r"[a-z]+", llano)
    if not primera or primera.group(0) not in _NOMBRES_DE_PILA:
        return negocio  # una marca ("Templa Medical", "Ginefiv"): tal cual, sin adivinar
    sector_llano = textnorm._strip_accents(str(sector or "")).lower()
    for raiz, que_es in _LO_QUE_ES:
        if re.search(r"\b(?:%s)" % raiz, sector_llano):
            return "%s %s" % (que_es, negocio)
    return negocio


def _variables(fila) -> Dict[str, str]:
    """Lo que Sara sabe de la llamada ({{negocio}}, {{a_quien}}...). Las mismas por Twilio y
    por SIP: el guion no sabe por donde se ha marcado."""
    email_negocio = str(fila["prospecto"] or "")
    negocio = nombre_corto(fila["negocio"]) or "tu negocio"
    # En una rellamada dirigida se pregunta por quien decide; si no, por el negocio.
    responsable = str(fila["responsable_nombre"] or "") if fila["rellamada_de"] else ""
    return {"negocio": negocio, "sector": fila["sector"] or "un negocio con citas",
            VARIABLE_LLAMADA: fila["id"], "canal_envio": canal_de_envio(fila["telefono"], email_negocio),
            "email_negocio": email_hablado(email_negocio),
            "a_quien": responsable or (negocio_hablado(negocio, fila["sector"]) if fila["negocio"] else negocio),
            "responsable": responsable or "quien lleva el negocio",
            "saludo": (APERTURA_RELLAMADA % responsable) if responsable else APERTURA}


# --- Marcar por SIP (proveedor espanol -> ElevenLabs) -----------------------------------
#
# Twilio no tiene numeros espanoles y desde el 17-oct-2026 prohibe usar los locales para
# llamadas comerciales (27-sep-2026). Con CAPTACION_VOZ_VIA=sip, Sara marca desde un 91 de un
# proveedor espanol importado en ElevenLabs como SIP Trunk (Zadarma: pbx.zadarma.com, TCP, sin
# cifrado de medios, credenciales de una extension de su centralita; docs/SARA_SIP.md). El numero se importa en la cuenta de ElevenLabs activa y se vuelve a
# importar al rotar de cuenta (cuenta_elevenlabs.sincronizar_agentes -> sincronizar_agente).
#
# Sin Twilio no llega el "comunicaba" o "no lo cogio": lo cuenta ElevenLabs con su aviso
# `call_initiation_failure` (busy / no-answer / unknown) al mismo /fin que la transcripcion.
# Por eso cada cuenta lleva su aviso (webhook) propio y su secreto se guarda en storage/,
# nunca en git.

CLAVE_NUMERO_SIP = "elevenlabs_numero_captacion"
EVENTOS_DEL_AVISO = ["transcript", "call_initiation_failure"]
_FALLO_AL_MARCAR = {"busy": "ocupado", "no-answer": "no_contesta"}
# La API de ElevenLabs no contesta al marcar hasta que descuelgan (primera llamada por la
# centralita de Zadarma, 28-sep-2026: 27 s, hasta que salto el buzon). Con los 30 s de Twilio,
# un negocio que tardaba en coger quedaba "fallida" sin conversation_id: su transcripcion y su
# resultado se perdian y el lanzador no lo reintentaba. Mas de lo que suena un telefono.
ESPERA_AL_MARCAR_SIP_S = 120.0


def via_sip() -> bool:
    return settings.CAPTACION_VOZ_VIA == "sip"


def sip_configurado() -> bool:
    return bool(settings.CAPTACION_SIP_NUMERO and settings.CAPTACION_SIP_USUARIO
                and settings.CAPTACION_SIP_CLAVE and settings.CAPTACION_SIP_HOST)


def _sin_secretos(texto: str) -> str:
    """Lo que devuelve ElevenLabs puede repetir lo enviado: fuera claves y la del SIP.
    Siempre sobre el texto ENTERO y recortar despues: recortado antes, una clave que
    cruzaba el corte dejaba a la vista su principio (revision de Astra, 27-sep-2026)."""
    from backend import cuenta_elevenlabs

    texto = cuenta_elevenlabs.censurar(texto)
    if settings.CAPTACION_SIP_CLAVE:
        texto = texto.replace(settings.CAPTACION_SIP_CLAVE, "***")
    return texto


def _ruta_avisos():
    return settings.STORAGE_DIR / "elevenlabs_avisos.json"


def _avisos() -> Dict[str, Dict[str, str]]:
    """{huella de la cuenta: {webhook_id, secreto}}. Fichero en storage/, fuera de git."""
    import json

    try:
        return json.loads(_ruta_avisos().read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def secretos_de_aviso() -> list:
    """Los secretos con los que puede venir firmado un aviso: el del entorno y el de cada
    cuenta de la reserva (una llamada puede terminar justo despues de rotar)."""
    secretos = [settings.ELEVENLABS_WEBHOOK_SECRET] + [a.get("secreto", "") for a in _avisos().values()]
    return [s for s in secretos if s]


def asegurar_aviso(cliente: httpx.Client, base_url: str = "") -> str:
    """El aviso de fin de llamada (webhook con firma HMAC) en la cuenta activa. Devuelve su id."""
    import json

    from backend import cuenta_elevenlabs

    avisos = _avisos()
    cuenta = cuenta_elevenlabs.huella(settings.ELEVENLABS_API_KEY)
    guardado = avisos.get(cuenta) or {}
    if guardado.get("webhook_id") and guardado.get("secreto"):
        r = cliente.get(voz_elevenlabs.API + "/v1/workspace/webhooks", headers=voz_elevenlabs._cabeceras())
        if r.status_code == 200 and any(guardado["webhook_id"] in (w.get("webhook_id"), w.get("id"))
                                        for w in (r.json() or {}).get("webhooks", [])):
            return guardado["webhook_id"]
    url = "%s%s/fin" % ((base_url or settings.APP_BASE_URL).rstrip("/"), RUTA)
    r = cliente.post(voz_elevenlabs.API + "/v1/workspace/webhooks", headers=voz_elevenlabs._cabeceras(),
                     json={"settings": {"auth_type": "hmac", "name": "Vantelia - fin de llamada de Sara",
                                        "webhook_url": url}})
    datos = r.json() if r.status_code < 400 else {}
    if not (datos.get("webhook_id") and datos.get("webhook_secret")):
        raise RuntimeError("ElevenLabs no creo el aviso de fin de llamada (%s): %s"
                           % (r.status_code, _sin_secretos(r.text)[:200]))
    avisos[cuenta] = {"webhook_id": datos["webhook_id"], "secreto": datos["webhook_secret"]}
    _ruta_avisos().parent.mkdir(parents=True, exist_ok=True)
    _ruta_avisos().write_text(json.dumps(avisos), encoding="utf-8")
    return datos["webhook_id"]


def _salida_sip() -> Dict[str, Any]:
    """Como sale ElevenLabs por el proveedor: servidor, transporte y la extension."""
    return {"address": settings.CAPTACION_SIP_HOST, "transport": settings.CAPTACION_SIP_TRANSPORTE,
            "media_encryption": "disabled",
            "credentials": {"username": settings.CAPTACION_SIP_USUARIO, "password": settings.CAPTACION_SIP_CLAVE}}


def _hay_llamada_viva() -> bool:
    """Una llamada marcando o en curso (y no muerta): no se le quita el numero debajo."""
    from backend import lanzador_llamadas

    hace = (timeutils._utc_now() - timedelta(minutes=lanzador_llamadas.MINUTOS_LLAMADA_VIVA)).isoformat(
        timespec="seconds")
    with _db() as conn:
        return conn.execute("SELECT 1 FROM llamadas_voz WHERE estado IN ('marcando', 'en_curso') "
                            "AND actualizada >= ? LIMIT 1", (hace,)).fetchone() is not None


def _liberar_numero_de_otra_cuenta(cliente: httpx.Client) -> None:
    """Quita el 91 de la cuenta de la reserva que lo tenga (no de la activa). Lanza si no
    se puede: nunca con una llamada en curso, y nunca de una cuenta que no sea nuestra."""
    from backend import cuenta_elevenlabs

    if _hay_llamada_viva():
        raise RuntimeError("El numero SIP esta en otra cuenta y hay una llamada en curso: se movera en la "
                           "siguiente pasada.")
    activa = settings.ELEVENLABS_API_KEY
    for clave in cuenta_elevenlabs.claves():
        if clave == activa:
            continue
        cabeceras = {"xi-api-key": clave}
        r = cliente.get(voz_elevenlabs.API + "/v1/convai/phone-numbers", headers=cabeceras)
        if r.status_code != 200:
            continue
        datos = r.json()
        numeros = datos if isinstance(datos, list) else (datos or {}).get("phone_numbers") or []
        for numero in numeros:
            if str(numero.get("phone_number") or "") != settings.CAPTACION_SIP_NUMERO:
                continue
            quitado = cliente.delete("%s/v1/convai/phone-numbers/%s" % (voz_elevenlabs.API,
                                                                        numero.get("phone_number_id")),
                                     headers=cabeceras)
            if quitado.status_code >= 400:
                raise RuntimeError("No se pudo quitar el numero SIP de la cuenta %s (%s)"
                                   % (cuenta_elevenlabs.huella(clave), quitado.status_code))
            settings.logger.warning("[captacion_voz] numero SIP quitado de la cuenta %s para importarlo en %s",
                                    cuenta_elevenlabs.huella(clave), cuenta_elevenlabs.huella(activa))
            return
    raise RuntimeError("El numero SIP ya esta en una cuenta de ElevenLabs que no es de la reserva: no se toca.")


def asegurar_numero_sip(cliente: httpx.Client, agent_id: str) -> str:
    """El 91 del proveedor SIP importado en la cuenta activa y con Sara asignada. Devuelve su id."""
    from backend import clients

    numero_id = str((clients._get_client_config(TENANT).get("voice") or {}).get(CLAVE_NUMERO_SIP) or "")
    if numero_id:
        r = cliente.get("%s/v1/convai/phone-numbers/%s" % (voz_elevenlabs.API, numero_id),
                        headers=voz_elevenlabs._cabeceras())
        # 404 tras rotar de cuenta, o cambiaron el numero: se importa otra vez.
        if r.status_code == 200 and str((r.json() or {}).get("phone_number") or "") == settings.CAPTACION_SIP_NUMERO:
            # Siempre se reenvian Sara y la salida: ElevenLabs no devuelve la clave, asi que
            # no se puede saber si cambio; sin esto, una clave renovada en el proveedor seguia
            # fallando aunque se resincronizase (revision de Astra, 27-sep-2026).
            p = cliente.patch("%s/v1/convai/phone-numbers/%s" % (voz_elevenlabs.API, numero_id),
                              headers=voz_elevenlabs._cabeceras(),
                              json={"agent_id": agent_id, "outbound_trunk_config": _salida_sip()})
            if p.status_code >= 400:
                raise RuntimeError("ElevenLabs no actualizo el numero SIP (%s): %s"
                                   % (p.status_code, _sin_secretos(p.text)[:200]))
            return numero_id
    cuerpo = {"phone_number": settings.CAPTACION_SIP_NUMERO, "label": "Sara - captacion (SIP)",
              "provider": "sip_trunk", "agent_id": agent_id,
              "inbound_trunk_config": {"media_encryption": "disabled"},
              "outbound_trunk_config": _salida_sip()}
    r = cliente.post(voz_elevenlabs.API + "/v1/convai/phone-numbers", headers=voz_elevenlabs._cabeceras(), json=cuerpo)
    if r.status_code == 409 and "already exists" in r.text:
        # ElevenLabs no deja el mismo numero en dos cuentas: al rotar seguia en la vieja y la
        # rotacion fallaba siempre (29-sep-2026). Se quita de la otra cuenta y se reintenta
        # UNA vez.
        _liberar_numero_de_otra_cuenta(cliente)
        r = cliente.post(voz_elevenlabs.API + "/v1/convai/phone-numbers", headers=voz_elevenlabs._cabeceras(),
                         json=cuerpo)
    numero_id = str((r.json() if r.status_code < 400 else {}).get("phone_number_id") or "")
    if not numero_id:
        raise RuntimeError("ElevenLabs no importo el numero SIP (%s): %s"
                           % (r.status_code, _sin_secretos(r.text)[:200]))
    voz_elevenlabs.guardar_en_voz(TENANT, CLAVE_NUMERO_SIP, numero_id)
    return numero_id


def _llamar_por_sip(llamada_id: str, cliente: httpx.Client) -> Dict[str, Any]:
    """Pide a ElevenLabs que marque desde el 91 del proveedor SIP. Lo que no conteste o comunique
    llega despues por el aviso (`fallo_al_marcar`)."""
    from backend import clients

    fila = _fila(llamada_id)
    voz = clients._get_client_config(TENANT).get("voice") or {}
    try:
        r = cliente.post(voz_elevenlabs.API + "/v1/convai/sip-trunk/outbound-call",
                         headers=voz_elevenlabs._cabeceras(), timeout=ESPERA_AL_MARCAR_SIP_S,
                         json={"agent_id": str(voz.get(CLAVE_AGENTE) or ""),
                               "agent_phone_number_id": str(voz.get(CLAVE_NUMERO_SIP) or ""),
                               "to_number": fila["telefono"],
                               "conversation_initiation_client_data": {"dynamic_variables": _variables(fila)}})
    except httpx.HTTPError as exc:
        # No se sabe si llego a sonar: sin resultado, el lanzador no reintenta solo.
        _actualizar(llamada_id, estado="fallida", notas="ElevenLabs sin respuesta")
        raise RuntimeError("ElevenLabs no respondio al marcar: %s" % _sin_secretos(str(exc))[:200]) from exc
    try:
        datos = r.json() if r.status_code < 500 else None
    except ValueError:
        datos = None
    if r.status_code >= 500 or (r.status_code < 400 and not isinstance(datos, dict)):
        # Un 5xx (o un 200 ilegible) no confirma que no sonara: pudo iniciarse y perderse la
        # respuesta. Como un timeout, sin resultado: el lanzador no reintenta solo, porque
        # volver a llamar a quien quiza ya hablo con Sara es peor (revision de Astra, 27-sep).
        detalle = _sin_secretos(r.text)[:200]
        _actualizar(llamada_id, estado="fallida", notas="ElevenLabs %s: %s" % (r.status_code, detalle))
        raise RuntimeError("ElevenLabs no confirmo la llamada (%s): %s" % (r.status_code, detalle))
    datos = datos if isinstance(datos, dict) else {}
    if r.status_code >= 400 or not datos.get("success"):
        detalle = _sin_secretos(str(datos.get("message") or r.text))[:200]
        # No se llego a marcar: nadie oyo nada, se puede reintentar como un "fallida" de Twilio.
        _actualizar(llamada_id, estado="fallida", resultado="fallida", notas="SIP %s: %s" % (r.status_code, detalle))
        if r.status_code in (401, 402, 403):
            from backend import lanzador_llamadas  # la cuenta de voz esta caida: rotar o parar

            lanzador_llamadas.fallo_de_voz(llamada_id, "ElevenLabs %s: %s" % (r.status_code, detalle))
        raise RuntimeError("ElevenLabs no pudo llamar (%s): %s" % (r.status_code, detalle))
    conversation_id = str(datos.get("conversation_id") or "")
    _actualizar(llamada_id, estado="en_curso", conversation_id=conversation_id,
                call_sid=str(datos.get("sip_call_id") or ""))
    # Un "comunicaba" pudo llegar mientras esperabamos esta respuesta: se aplica ahora.
    _aplicar_fallo_pendiente(conversation_id)
    return {"ok": True, "llamada": llamada_id, "conversation_id": conversation_id}


def _codigo_sip(metadatos: Any) -> str:
    """El codigo SIP del fallo (486 comunicaba...), venga plano o dentro de `body`."""
    if not isinstance(metadatos, dict):
        return ""
    for sitio in (metadatos, metadatos.get("body")):
        if isinstance(sitio, dict) and sitio.get("sip_status_code"):
            return str(sitio["sip_status_code"])[:10]
    return ""


def fallo_al_marcar(conversation_id: str, motivo: str, metadatos: Any = None) -> Optional[str]:
    """Aviso `call_initiation_failure` de ElevenLabs: comunicaba, no lo cogieron o fallo.
    Queda igual que con Twilio (resultado sin conversacion y SIN conversation_id), para que
    el lanzador aplique las mismas reglas de reintento."""
    if not conversation_id:
        return None
    motivo = textnorm._sanitize_text(str(motivo or ""))[:40]
    detalle = _codigo_sip(metadatos)
    fila = _llamada_por_conversacion(conversation_id)
    if fila is None:
        # Llego antes de que `_llamar_por_sip` guardase la conversacion (un "comunicaba"
        # es casi instantaneo): se aparca, y se vuelve a mirar por si se guardo entremedias.
        # Asi, llegue antes o despues, uno de los dos lados lo ve (revision de Astra, 27-sep).
        with _db() as conn:
            conn.execute("DELETE FROM llamadas_fallos_pendientes WHERE recibido < ?",
                         ((timeutils._utc_now() - timedelta(days=1)).isoformat(timespec="seconds"),))
            conn.execute("INSERT OR REPLACE INTO llamadas_fallos_pendientes (conversation_id, motivo, detalle, "
                         "recibido) VALUES (?,?,?,?)", (conversation_id, motivo, detalle, _ahora()))
            conn.commit()
        return _aplicar_fallo_pendiente(conversation_id)
    _marcar_fallo(fila, motivo, detalle)
    return fila["id"]


def _llamada_por_conversacion(conversation_id: str):
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT id, resultado FROM llamadas_voz WHERE conversation_id=?",
                            (conversation_id,)).fetchone()


def _marcar_fallo(fila, motivo: str, detalle: str) -> None:
    if not fila["resultado"]:  # lo que apunto Sara, si llego a hablar, manda
        _actualizar(fila["id"], estado="terminada", conversation_id="",
                    resultado=_FALLO_AL_MARCAR.get(motivo.strip().lower(), "fallida"),
                    notas=("SIP: %s %s" % (motivo, detalle)).strip())


def _aplicar_fallo_pendiente(conversation_id: str) -> Optional[str]:
    """Si hay un fallo aparcado para esta conversacion y su llamada ya esta guardada, se
    aplica. Lo reclama quien consiga borrarlo: nunca se aplica dos veces."""
    if not conversation_id:
        return None
    fila = _llamada_por_conversacion(conversation_id)
    if fila is None:
        return None
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        pendiente = conn.execute("SELECT motivo, detalle FROM llamadas_fallos_pendientes WHERE conversation_id=?",
                                 (conversation_id,)).fetchone()
        if pendiente is None:
            return None
        reclamado = conn.execute("DELETE FROM llamadas_fallos_pendientes WHERE conversation_id=?",
                                 (conversation_id,)).rowcount == 1
        conn.commit()
    if not reclamado:
        return None
    _marcar_fallo(fila, pendiente["motivo"], pendiente["detalle"])
    return fila["id"]


def enlace_de_demo(email_negocio: str) -> str:
    """La demo del propio negocio (generada desde su web), la misma de los correos de
    captacion. Sin negocio conocido o sin secreto de seguimiento, la web."""
    secreto = os.getenv("OUTREACH_TRACKING_SECRET", "").strip()
    if not (email_negocio and secreto):
        return WEB
    from backend import outreach  # deja scripts/ en el path

    if not outreach.OUTREACH_AVAILABLE:
        return WEB
    import outreach_templates  # type: ignore

    base = os.getenv("OUTREACH_TRACKING_BASE_URL", "").strip().rstrip("/") or "https://app.vantelia.es"
    return "%s/demo/go/%s" % (base, outreach_templates.make_tracking_token(email_negocio, "llamada", secreto))


def telefono_de_vantelia() -> str:
    """El 91 desde el que llama Sara, escrito para una persona ("919 93 43 21"). Es el que se
    da para devolver la llamada; nunca el movil de Pablo (Pablo, 30-sep-2026)."""
    cifras = re.sub(r"\D", "", settings.CAPTACION_SIP_NUMERO or "")
    cifras = cifras[2:] if cifras.startswith("34") and len(cifras) == 11 else cifras
    if len(cifras) != 9:
        return ""
    return "%s %s %s %s" % (cifras[:3], cifras[3:5], cifras[5:7], cifras[7:])


def _contacto(con_tildes: bool = True) -> str:
    """"llamanos al 919 93 43 21 o escribe a info@vantelia.es" (sin numero, solo el correo)."""
    telefono = telefono_de_vantelia()
    if telefono:
        return ("llámanos al %s o escribe a %s" if con_tildes else "llamanos al %s o escribe a %s") % (
            telefono, EMAIL_VANTELIA)
    return "escribe a %s" % EMAIL_VANTELIA


def texto_sms(negocio: str, enlace: str) -> str:
    # Sin tildes a proposito: con una sola, el SMS pasa a otra codificacion y cuesta el doble.
    return ("Hola! Soy Sara, de Vantelia. Asi atenderia el telefono y el WhatsApp de %s: %s "
            "Pruebalo gratis. Cualquier duda, %s"
            % (textnorm._strip_accents(negocio), enlace, _contacto(con_tildes=False)))


def correo(negocio: str, enlace: str) -> Dict[str, str]:
    texto = (
        "Hola,\n\n"
        "Soy Sara, la asistente virtual de Vantelia que os ha llamado hace un momento. Así "
        "atendería el teléfono y el WhatsApp de %s: da citas, las cambia y las cancela mientras "
        "estáis con las manos ocupadas.\n\n"
        "Pruébalo con tu propio negocio: %s\n\n"
        "¿Alguna duda? %s, o responde a este correo.\n\n"
        "Un saludo,\nSara · Vantelia\n" % (negocio, enlace, _contacto()[:1].upper() + _contacto()[1:]))
    telefono = telefono_de_vantelia()
    contacto_html = ("Llámanos al %s o escribe a <a href='mailto:%s'>%s</a>" % (telefono, EMAIL_VANTELIA, EMAIL_VANTELIA)
                     if telefono else "Escribe a <a href='mailto:%s'>%s</a>" % (EMAIL_VANTELIA, EMAIL_VANTELIA))
    html = (
        "<div style='font-family:sans-serif;max-width:560px;color:#1a1a2e;line-height:1.5'>"
        "<p>Hola,</p><p>Soy Sara, la asistente virtual de Vantelia que os ha llamado hace un "
        "momento. Así atendería el teléfono y el WhatsApp de <strong>%s</strong>: da citas, las "
        "cambia y las cancela mientras estáis con las manos ocupadas.</p>"
        "<p><a href='%s' style='display:inline-block;padding:11px 20px;border-radius:999px;"
        "background:#00D1FF;color:#04101C;font-weight:700;text-decoration:none'>Pruébalo con tu "
        "negocio</a></p><p>¿Alguna duda? %s, o responde a este correo.</p><p>Un saludo,<br>Sara · Vantelia</p></div>"
        % (escape(negocio), escape(enlace, quote=True), contacto_html))
    return {"asunto": "Lo que te conté por teléfono", "texto": texto, "html": html}


def _mandar_sms(telefono: str, texto: str) -> bool:
    from backend import messaging

    remitente = settings.TWILIO_SMS_SENDER or _numero_de_salida()
    return bool(asyncio.run(messaging._send_twilio_sms(telefono, remitente, texto)))


def _mandar_correo(email: str, contenido: Dict[str, str]) -> bool:
    """Por el MISMO buzon de envio que los correos de captacion, con su pie legal."""
    from backend import outreach
    import outreach_templates  # type: ignore

    ajustes = outreach.outreach_smtp_settings()
    texto = contenido["texto"] + outreach_templates.footer_text(str(ajustes.get("unsubscribe_mailto") or ""))
    html = contenido["html"] + outreach_templates.footer_html(str(ajustes.get("unsubscribe_mailto") or ""))
    mensaje = outreach.outreach_build_message(email, contenido["asunto"], texto, html, ajustes)
    outreach._outreach_send_email_object(mensaje)
    return True


def _reclamar_envio(llamada_id: str) -> bool:
    """El sello del envio, atomico: True solo para el primer camino que llega.

    Se reclama ANTES de mandar. Si el proceso muere a mitad, queda en 'enviando' y no
    se reintenta: antes un envio de menos (Pablo ve la llamada) que dos correos."""
    with _db() as conn:
        reclamada = conn.execute("UPDATE llamadas_voz SET informacion='enviando', actualizada=? "
                                 "WHERE id=? AND informacion=''", (_ahora(), llamada_id)).rowcount
        conn.commit()
    return reclamada == 1


def _estado_del_envio(llamada_id: str) -> str:
    with _db() as conn:
        fila = conn.execute("SELECT informacion FROM llamadas_voz WHERE id=?", (llamada_id,)).fetchone()
    return str(fila[0] or "") if fila else ""


# Si el sello ya estaba puesto. Nunca "ya se le ha mandado" sin que el canal lo aceptara
# (docs/NORMAS_AGENTE_IA.md, regla 4): enviando = aun no se sabe; no_enviada = fallo, y
# Pablo ya tiene el aviso para escribirle el.
_MENSAJE_YA_RECLAMADO = {
    "enviada": "Ya se le ha mandado la informacion. Diselo en una frase y despidete.",
    "enviando": "Se le esta mandando ahora mismo. Dile que le llegara en un rato y despidete.",
    "no_enviada": "Apuntado. Dile que se lo mandamos en un rato y despidete.",
}


def _enviar_informacion(fila, cuerpo: Dict[str, Any]) -> Dict[str, Any]:
    dado = str(cuerpo.get("email") or "").strip().lower().replace(" ", "")
    if dado and not _EMAIL.match(dado):
        return {"ok": False, "error": "Ese email no parece completo. Pideselo otra vez."}
    email_negocio = str(fila["prospecto"] or "")
    destino_email = dado or ("" if es_movil(fila["telefono"]) else email_negocio)
    if not destino_email and not es_movil(fila["telefono"]):
        return {"ok": False, "error": "No tengo a donde mandarlo: pidele un email."}
    if not _reclamar_envio(fila["id"]):
        # Ya lo mando otro camino (la herramienta dos veces, o el respaldo al colgar
        # mientras la herramienta seguia): como mucho un envio por llamada. Lo que se le
        # dice depende de como quedo: solo "ya se le ha mandado" si de verdad salio.
        return {"ok": True, "reclamada": False, "mensaje": _MENSAJE_YA_RECLAMADO.get(
            _estado_del_envio(fila["id"]), _MENSAJE_YA_RECLAMADO["no_enviada"])}
    negocio = nombre_corto(fila["negocio"]) or "tu negocio"
    enlace = enlace_de_demo(email_negocio)
    if email_negocio:
        # Su demo empieza a generarse YA (desde su web, en segundo plano): cuando abra
        # el SMS o el correo, un par de minutos despues, la encuentra lista en vez de
        # una pagina de espera. Misma pregeneracion que los correos de captacion.
        try:
            from backend import outreach

            outreach._outreach_maybe_pregenerate_demo(email_negocio)
        except Exception:  # noqa: BLE001 - sin demo lista, el enlace la genera al pinchar
            settings.logger.warning("[captacion_voz] no se pudo adelantar la demo de %s", email_negocio)
    try:
        if destino_email:
            canal, enviado = "email", _mandar_correo(destino_email, correo(negocio, enlace))
        else:
            canal, enviado = "sms", _mandar_sms(fila["telefono"], texto_sms(negocio, enlace))
    except Exception:  # noqa: BLE001 - no poder mandarlo no puede perder al interesado
        settings.logger.exception("[captacion_voz] no se pudo mandar la informacion de %s", fila["id"])
        canal, enviado = ("email" if destino_email else "sms"), False
    notas = textnorm._sanitize_text(str(cuerpo.get("notas") or ""), allow_multiline=True)[:500]
    nombre_contacto = textnorm._sanitize_text(str(cuerpo.get("nombre") or ""))[:80]
    _actualizar(fila["id"], informacion="enviada" if enviado else "no_enviada",
                resultado="interesado", email=destino_email,
                notas=("%s. %s. %s" % (canal + (" enviado" if enviado else " NO enviado"),
                                       nombre_contacto, notas)).strip(". "))
    _avisar_interes(fila, destino_email or fila["telefono"], nombre_contacto, notas, canal, enviado, enlace)
    if not enviado:
        return {"ok": True, "mensaje": "Apuntado. Dile que se lo mandamos en un rato y despidete."}
    por_donde = "por SMS a este numero" if canal == "sms" else "al correo %s" % email_hablado(destino_email)
    return {"ok": True, "mensaje": "Enviado %s. Diselo en una frase y despidete." % por_donde}


def herramienta(nombre: str, cuerpo: Dict[str, Any]) -> Dict[str, Any]:
    """Lo que hace cada tool de la agente de captacion."""
    llamada_id = str(cuerpo.get(CAMPO_LLAMADA) or "")
    fila = _fila(llamada_id) if llamada_id else None
    if fila is None:
        return {"ok": False, "error": "No encuentro esta llamada. Despidete con amabilidad."}
    if nombre == "enviar_informacion":
        return _enviar_informacion(fila, cuerpo)
    if nombre == "volver_a_llamar":
        cuando = textnorm._sanitize_text(str(cuerpo.get("cuando") or ""))[:120]
        con_quien = textnorm._sanitize_text(str(cuerpo.get("con_quien") or ""))[:80]
        _actualizar(llamada_id, resultado="volver_a_llamar",
                    notas=("%s %s" % (cuando, ("(" + con_quien + ")") if con_quien else "")).strip())
        return {"ok": True, "mensaje": "Apuntado. Despidete."}
    if nombre == "pasar_a_pablo":
        cuando = textnorm._sanitize_text(str(cuerpo.get("cuando") or ""))[:120]
        persona = textnorm._sanitize_text(str(cuerpo.get("nombre") or ""))[:80]
        notas = textnorm._sanitize_text(str(cuerpo.get("notas") or ""), allow_multiline=True)[:300]
        # Resultado propio: fuera de las llamadas automaticas, de la rellamada dirigida y de la
        # segunda oportunidad. A ese negocio le llama Pablo, no Sara.
        _actualizar(llamada_id, resultado=RESULTADO_PABLO,
                    notas=("Pide hablar con una persona. Cuando: %s. %s %s" % (cuando or "-", persona, notas)).strip())
        _avisar_a_pablo(fila, cuando, persona, notas)
        return {"ok": True, "mensaje": "Apuntado: Pablo le llamara. Diselo en una frase y despidete."}
    if nombre == "no_volver_a_llamar":
        motivo = textnorm._sanitize_text(str(cuerpo.get("motivo") or ""))[:200]
        with _db() as conn:
            conn.execute("INSERT OR IGNORE INTO no_llamar (telefono, motivo, creado) VALUES (?,?,?)",
                         (fila["telefono"], motivo, _ahora()))
            # "No me llameis" es baja de TODO: tampoco se le escribe (ni la captacion por
            # email ni la segunda oportunidad; docs/PLAN_SEGUNDA_OPORTUNIDAD_LLAMADAS.md).
            email = str(fila["prospecto"] or "").strip().lower()
            if email:
                conn.execute("INSERT OR IGNORE INTO suppressions (email, reason, added_at) VALUES (?,?,?)",
                             (email, "no_llamar_por_telefono", _ahora()))
                conn.execute("UPDATE prospects SET status='baja', updated_at=? WHERE email=?", (_ahora(), email))
            conn.commit()
        _actualizar(llamada_id, resultado="no_llamar", notas=motivo)
        return {"ok": True, "mensaje": "Apuntado: no se le vuelve a llamar. Pide disculpas y despidete."}
    if nombre == "anotar_responsable":
        return _anotar_responsable(fila, cuerpo)
    return {"ok": False, "error": "Herramienta desconocida."}


# --- Lo que Sara dijo que haria y no hizo ----------------------------------------------
#
# 28-sep-2026, llamada de prueba de Pablo: Sara dijo "te mando ahora mismo un correo" y no
# llamo a `enviar_informacion`; tampoco a `anotar_responsable` al saber quien decidia y
# cuando. Lo que el modelo puede hacer mal lo cubre el codigo: con el analisis de
# ElevenLabs al terminar (DATOS_AL_TERMINAR) se manda la informacion si la acepto.
# Como mucho UNA vez por llamada: la herramienta y el respaldo comparten el sello
# (columna `informacion`, `_reclamar_envio`, dentro de `_enviar_informacion`), y el
# aviso de fin puede llegar dos veces (aviso y recogida horaria).
# Ante la duda, no se manda (docs/PLAN_RESPALDO_DE_SARA.md, con la tabla de fallos).

DESENLACES_SIN_ENVIO = ("rechazo", "persona_equivocada", "buzon", "colgo_al_principio")


def _es_si(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    return str(valor or "").strip().lower() in ("true", "si", "sí", "yes")


def _no_se_le_escribe(email: str) -> bool:
    """Dado de baja, rebotado o suprimido: a ese correo no se le escribe nada."""
    if not email:
        return False
    with _db() as conn:
        if conn.execute("SELECT 1 FROM suppressions WHERE email=?", (email,)).fetchone():
            return True
        fila = conn.execute("SELECT status FROM prospects WHERE email=?", (email,)).fetchone()
    return bool(fila and str(fila[0] or "") in ("baja", "bounced"))


def enviar_de_respaldo(llamada_id: str, datos: Dict[str, Any]) -> bool:
    """Manda la informacion si la acepto y Sara no llego a mandarla. True si se mando.

    `datos` son los valores de DATOS_AL_TERMINAR ya sacados de su {"value": ...}."""
    fila = _fila(llamada_id)
    if fila is None or fila["resultado"]:
        return False  # ya tiene resultado: actuo la herramienta, o pidio no mas llamadas
    if not _es_si(datos.get("quiere_informacion")):
        return False
    if str(datos.get("desenlace") or "").strip().lower() in DESENLACES_SIN_ENVIO:
        return False
    if not puede_llamarse(fila["telefono"]):
        return False
    dado = str(datos.get("email_para_informacion") or "").strip().lower().replace(" ", "")
    if not _EMAIL.match(dado):
        dado = ""
    email_negocio = str(fila["prospecto"] or "").strip().lower()
    destino = dado or ("" if es_movil(fila["telefono"]) else email_negocio)
    if not destino and not es_movil(fila["telefono"]):
        return False  # un fijo sin correo: no hay a donde mandarlo
    if _no_se_le_escribe(destino) or _no_se_le_escribe(email_negocio):
        return False
    # El sello (_reclamar_envio) lo pone _enviar_informacion, el MISMO que usa la
    # herramienta: si esta sigue mandando cuando llega el analisis, aqui no se manda.
    respuesta = _enviar_informacion(
        fila, {"email": dado, "notas": "De respaldo: Sara dijo que lo mandaba y no lo hizo."})
    return bool(respuesta.get("ok")) and respuesta.get("reclamada", True) is not False


INTERLOCUTORES = ("duena_o_encargada", "empleado", "no_se_sabe")


def con_quien_hablo(fila) -> str:
    """En una frase, para el aviso a Pablo y el panel."""
    claves = fila.keys() if hasattr(fila, "keys") else []
    interlocutor = fila["interlocutor"] if "interlocutor" in claves else ""
    nombre = fila["responsable_nombre"] if "responsable_nombre" in claves else ""
    cuando = fila["responsable_cuando"] if "responsable_cuando" in claves else ""
    if interlocutor == "duena_o_encargada":
        return "la duena o encargada" + ((" (" + nombre + ")") if nombre else "")
    if interlocutor == "empleado":
        detalle = ", ".join(p for p in (nombre, cuando) if p)
        return "alguien del equipo" + ((" - decide: " + detalle) if detalle else "")
    return "sin saber si decide"


def _anotar_responsable(fila, cuerpo: Dict[str, Any]) -> Dict[str, Any]:
    """Con quien habla Sara y, si no es quien decide, lo que se sabe de esa persona."""
    interlocutor = str(cuerpo.get("interlocutor") or "").strip().lower()
    if interlocutor not in INTERLOCUTORES:
        interlocutor = "no_se_sabe"
    campos: Dict[str, Any] = {"interlocutor": interlocutor}
    nombre = textnorm._sanitize_text(str(cuerpo.get("nombre") or ""))[:80]
    cuando = textnorm._sanitize_text(str(cuerpo.get("cuando") or ""))[:120]
    email = str(cuerpo.get("email") or "").strip().lower()
    if nombre:
        campos["responsable_nombre"] = nombre
    if cuando:
        campos["responsable_cuando"] = cuando
    if email and _EMAIL.match(email):
        campos["responsable_email"] = email[:200]
    # Un movil que da un empleado NO se usa para llamar solos: sin permiso de su dueno es
    # otro riesgo legal. Queda como nota para Pablo (docs/PLAN_HABLAR_CON_EL_RESPONSABLE.md).
    telefono = telefono_e164(str(cuerpo.get("telefono") or ""))
    if telefono:
        campos["responsable_nota"] = "Telefono facilitado en la llamada (no se usa para llamar solos): " + telefono
    se_pone = bool(cuerpo.get("se_pone_ahora"))
    campos["se_pone_ahora"] = 1 if se_pone else 0
    _actualizar(fila["id"], **campos)
    if interlocutor == "duena_o_encargada":
        return {"ok": True, "mensaje": "Apuntado: hablas con quien decide en el negocio."}
    if se_pone:
        return {"ok": True, "mensaje": ("Apuntado. Di 'claro, espero' y espera callada. Cuando hable la persona "
                                        "nueva, presentate entera otra vez: quien eres, que eres una asistente "
                                        "virtual, el gancho y el aviso de que es comercial.")}
    return {"ok": True, "mensaje": ("Apuntado. Ofrece mandar la informacion para quien decide y despidete; si "
                                    "quien te atiende tiene curiosidad, puedes hacerle la demo.")}


def _avisar_a_pablo(fila, cuando: str, persona: str, notas: str) -> None:
    """Quien pide hablar con una persona: Pablo tiene que enterarse al momento para llamarle."""
    from backend import outreach

    negocio = fila["negocio"] or fila["telefono"]
    asunto = "🙋 Quiere hablar contigo: %s" % negocio
    texto = ("En una llamada de Sara han pedido hablar con una persona. Le he dicho que le llamas tu.\n\n"
             "Negocio:  %s\nTelefono: %s\nCuando:   %s\nPersona:  %s\nNotas:    %s\n"
             % (negocio, fila["telefono"], cuando or "-", persona or "-", notas or "-"))
    html = ("<div style='font-family:sans-serif'><h2 style='color:#00b1d9'>🙋 %s</h2>"
            "<p>Han pedido hablar con una persona: le he dicho que le llamas tu.</p>"
            "<p>Telefono: <a href='tel:%s'>%s</a><br>Cuando: %s<br>Persona: %s</p><p>%s</p></div>"
            % (escape(negocio), escape(fila["telefono"], quote=True), escape(fila["telefono"]), escape(cuando or "-"),
               escape(persona or "-"), escape(notas or "")))
    try:
        outreach._outreach_notify_admin(asunto, texto, html)
    except Exception:  # noqa: BLE001 - el aviso nunca tumba la llamada (queda el resultado en el panel)
        settings.logger.exception("[captacion_voz] no se pudo avisar a Pablo de %s", fila["id"])


def _avisar_interes(fila, destino: str, nombre: str, notas: str, canal: str, enviado: bool,
                    enlace: str) -> None:
    from backend import outreach

    negocio = fila["negocio"] or fila["telefono"]
    estado = ("Le hemos mandado el enlace por %s." % canal) if enviado else (
        "NO se pudo mandar el %s: escribele tu." % canal)
    con_quien = con_quien_hablo(_fila(fila["id"]) or fila)
    asunto = "📞 Interesado por telefono: %s" % negocio
    texto = ("Sara ha hablado con un negocio interesado:\n\nNegocio:  %s\nTelefono: %s\nEnviado a: %s\n"
             "Contacto: %s\nHablo con: %s\nNotas:    %s\nEnlace:   %s\n\n%s\n"
             % (negocio, fila["telefono"], destino, nombre or "-", con_quien, notas or "-", enlace, estado))
    html = ("<div style='font-family:sans-serif'><h2 style='color:#00b1d9'>📞 %s</h2>"
            "<p>Telefono: %s<br>Enviado a: %s<br>Contacto: %s<br>Hablo con: %s</p><p>%s</p>"
            "<p><a href='%s'>Enlace enviado</a></p><p><strong>%s</strong></p></div>"
            % (escape(negocio), escape(fila["telefono"]), escape(destino), escape(nombre or "-"),
               escape(con_quien), escape(notas or "-"), escape(enlace, quote=True), escape(estado)))
    try:
        outreach._outreach_notify_admin(asunto, texto, html)
    except Exception:  # noqa: BLE001 - el aviso nunca tumba la llamada
        settings.logger.exception("[captacion_voz] no se pudo avisar del interesado %s", destino)
