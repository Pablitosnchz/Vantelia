"""Captacion por telefono: Sara llama a los negocios y la llamada ES la demostracion.

POR QUE EXISTE
--------------
Idea de Pablo (23-sep-2026, docs/PLAN_VOZ_HUMANA_Y_AUTOCAPTACION.md, parte C): en vez
de contarle a una peluqueria que un asistente puede coger su telefono, que le llame
uno. La voz y los turnos son de ElevenLabs (`voz_elevenlabs`); el guion, las reglas y
lo que se apunta de cada llamada, nuestros.

REGLAS QUE NO SE NEGOCIAN (Circular AEPD 1/2023 y Reglamento de IA, art. 50)
------------------------------------------------------------------------------
- La primera frase dice quien llama y que es una asistente virtual (una IA), y que si no le
  encaja lo diga y no se le molesta mas. El motivo (ayudamos a negocios con las llamadas) va
  en la frase siguiente, en palabras de persona y no de formulario (Pablo, 30-sep-2026).
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
import smtplib
import sqlite3
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any, Dict, Optional

import httpx

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8
    from backports.zoneinfo import ZoneInfo

from backend import settings, textnorm, timeutils, voz_elevenlabs

TENANT = "vantelia"
CLAVE_AGENTE = "elevenlabs_agent_captacion"
RUTA = "/voice/el-captacion"
VARIABLE_LLAMADA = "llamada"
CAMPO_LLAMADA = "_llamada"
# Solo ASCII: "recep-recepción@dentalnavarro.com" (Dental Navarro, 2-oct-2026) pasaba la regla
# anterior, el servidor de correo lo rechazaba y el interesado se quedaba sin la demo.
_EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$", re.IGNORECASE)
EMAIL_VANTELIA = "info@vantelia.es"
# Resultado de quien pidio hablar con una persona: le llama Pablo, nunca otra vez Sara.
RESULTADO_PABLO = "llamar_pablo"
WEB = "https://www.vantelia.es"

# La apertura. Primera version (30-sep-2026, variante A de Astra): permiso y una pregunta
# ANTES de ofrecer nada, porque con el gancho de venta hubo 0 demos en 24 llamadas. Segunda,
# el mismo dia: Pablo, "no digas lo de que es una llamada comercial, que sea mas natural, como
# una recepcionista de verdad que llama para preguntarles como atienden a sus clientes; que
# actue como un setter de ventas profesional". Lo que miden en llamadas en frio (Gong, 300 M):
# pedir un momento y decir el motivo en una frase funcionan; "¿te pillo en mal momento?" es lo
# peor. Sigue diciendo quien llama y que es una IA (Reglamento de IA art. 50) y que puede decir
# que no y no se le molesta mas (derecho a oponerse), en palabras de persona; el motivo va en
# la frase siguiente. En una rellamada dirigida pregunta por quien decide. Una sola fuente: el
# guion la repite igual a quien coge tras una espera.
# Tercera (1-oct-2026, Pablo tras probarla): "demasiado largo, la gente oye eso y corta; mas
# 'hola, ¿tienes treinta segundos?', como una setter de verdad". Fuera Vantelia y el "si no te
# encaja" (si no quiere, ya lo dice; "no me llameis" sigue apuntandose al momento). Lo que NO se
# quita es decir que es una IA en la primera frase: el Reglamento de IA (art. 50, en vigor desde
# el 2-ago-2026) obliga a avisarlo como tarde en la primera interaccion. Pablo eligio las dos
# palabras al principio. Se repite en el gancho ("soy una inteligencia artificial que...").
APERTURA = "Hola, soy Sara, una IA. ¿Tienes treinta segundos?"
APERTURA_RELLAMADA = "Hola, soy Sara, una IA. ¿Está %s?"
# El objetivo de la llamada (Pablo, 30-sep-2026): ver si al negocio le interesa la IA que da sus
# citas. Desde el 1-oct: ofrecerle una demo gratuita por SMS o email ("prefiero eso a 'te
# llama Pablo'"); si prefiere que le llamen, se le proponen dos huecos concretos (un setter no
# pregunta "¿cuando te va bien?"). Pablo llama de lunes a viernes a cualquier hora.
HUECOS_ENTRANTE = "entre semana, por la mañana o por la tarde"
_DIAS_DE_LA_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
# Al llamar ella, Sara no suelta la apertura en el segundo 0 (se comia el "¿digame?" y hablaba
# encima). Del 30-sep al 5-oct decia primero "¿Hola?", pero se pisaba con el saludo de la
# recepcion, le contestaban "hola, buenos dias" y eso la cortaba: "Hola, soy... Hola, soy
# Sara... Hola, soy Sara, una IA" en 4 de 16 llamadas del 5-oct. Ahora no dice nada hasta que
# contestan (primer mensaje vacio: ElevenLabs espera a que hable la persona, o
# SEGUNDOS_ANTES_DE_EMPEZAR si nadie habla). En una entrante la primera frase es el saludo
# entero: coge el telefono ella.
PRIMERA_SALIENTE = ""
# El agente que llama ya no lleva {{primera}} en su primer mensaje, pero la variable se sigue
# mandando (vacia): un agente de antes, aun sin sincronizar, la exige y sin ella colgaria cada
# llamada ("Missing required dynamic variables", 30-sep-2026).
PRIMER_MENSAJE = ""
SEGUNDOS_ANTES_DE_EMPEZAR = 4
# Lo que dice la recepcion al coger (o al oir a Sara) NO la interrumpe: era lo que la hacia
# empezar la apertura tres veces (5-oct-2026). Un "no" o cualquier otra cosa si la corta.
SALUDOS_QUE_NO_INTERRUMPEN = ["hola", "buenos días", "buenas", "buenas tardes", "dígame", "diga",
                              "sí, dígame"]
# Cuando nos llaman ELLOS al 91 (Pablo, 30-sep-2026: "si llaman de vuelta, que atienda Sara").
# Las salientes siempre mandan su {{saludo}} y {{sentido}}; los valores por defecto del agente
# son los de una llamada que entra, que no manda nada (el puente solo pasa quien llama).
# Corto (Pablo, 1-oct-2026: "que diga en que te puedo ayudar directamente"), con la IA dicha.
SALUDO_ENTRANTE = "Hola, soy Sara, una IA. ¿En qué te puedo ayudar?"
# En una entrante las tools no llevan el id de la llamada (no lo hay aun): llevan quien llama y
# la conversacion, y el servidor encuentra o crea su ficha (`_fila_entrante`).
# El nombre es el mismo en todas las cuentas (el id no): con el se reconocen sus conversaciones
# en una cuenta de la que ya se roto (transcripciones_llamadas.recoger_entrantes).
NOMBRE_DEL_AGENTE = "Sara - captacion Vantelia (telefono)"
CAMPO_QUIEN = "_quien"
CAMPO_CONVERSACION = "_conversacion"
# Las entrantes las coge OTRO agente, asignado al 91: ElevenLabs NO usa los valores por
# defecto de las variables en una llamada SIP que entra (primera prueba, 30-sep-2026: colgaba
# al segundo con "Missing required dynamic variables in first message: {'saludo'}"). Es la
# misma Sara, con su guion ya rellenado con lo de una entrante y el saludo fijo. Las salientes
# siguen usando la Sara de siempre: la llamada dice que agente usar.
CLAVE_AGENTE_ENTRADA = "elevenlabs_agent_captacion_entrada"
NOMBRE_DEL_AGENTE_ENTRADA = "Sara - devoluciones Vantelia (telefono)"

GUION = """Eres Sara, una asistente virtual de Vantelia: una inteligencia artificial, y lo dices. Llamas por telefono a {{negocio}} ({{sector}}).

REGLA PRIMERA, POR ENCIMA DE TODO LO DEMAS: cuando llamas tu, tu primera frase de la llamada es SIEMPRE la apertura, tal cual: "{{saludo}}". Digan lo que digan al coger ("si", "¿si?", "digame", "hola", el nombre del negocio), empiezas por la apertura. Un "si" o un "dime" ANTES de que hayas dicho la apertura NO es permiso para nada: es como cogen el telefono. Nunca empieces por otra frase ni te saltes que eres una IA. (Solo si lo que contesta es una grabacion, un menu o un buzon, sigue GRABACIONES, CENTRALITAS Y ESPERAS.)

POR QUE LLAMAS
Vantelia pone en negocios con citas una asistente como tu: coge el telefono y el WhatsApp cuando el equipo esta ocupado, da citas, las cambia y las cancela. El objetivo de la llamada es pequeño: que acepten que les mandes una demo gratuita (por email o por SMS) para que la vea quien lleva el negocio y pruebe como quedaria. Casi siempre te coge la recepcion, no quien decide: no le pidas opinion ni que decida nada, solo a donde mandar la demo. Si prefieren que les llamen, les llama Pablo, el fundador. Tu propia llamada es la prueba de como sonaria.

COMO HABLAS
- Habla SIEMPRE en español de España. Nunca en ingles, ni repitas una frase traducida.
- Como una recepcionista de verdad que llama a otro negocio: cercana, tranquila y natural, de tu y con frases cortas. Una idea por turno y deja hablar.
- Escucha mas de lo que hablas. Antes de seguir, reacciona a lo que te acaban de decir, como haria una persona ("ya, normal", "claro, con las manos ocupadas..."), y usa sus mismas palabras.
- Nada de frases de vendedora ni de folleto ("solucion", "optimizar", "herramienta", "plataforma"). No insistas ni presiones: si no le encaja, no pasa nada.
- Nada de listas, nada de leer parrafos, numeros y precios en palabras.
- Si preguntan si eres una persona o un robot: eres una IA, justo lo que les ofrecemos.

GRABACIONES, CENTRALITAS Y ESPERAS
- Muchos negocios contestan con una grabacion o un menu ("pulse uno", "marque dos", "su llamada es muy importante", "en breve le atenderemos", "sera atendido", "esta llamada puede ser grabada") o te dejan en espera con musica. Eso NO es una persona: no le hables, no le preguntes nada y nunca le digas que se ha confundido. Usa `skip_turn` y espera callada a que conteste alguien, aunque tarde. No cuelgues por estar en espera y no preguntes "¿sigues ahi?" a una grabacion.
- Si la grabacion dice que te pasan con alguien ("le pasamos con una recepcionista", "se transfiere su llamada"), eso tambien es esperar: `skip_turn`. Nunca te despidas ni cuelgues por eso.
- Si la misma grabacion de espera se ha repetido cinco veces y no coge nadie, cuelga con `end_call` sin decir nada: se le volvera a llamar otro dia.
- Un buzon de voz ("deje su mensaje despues de la señal") si es para colgar: usa `voicemail_detection`.
- Si el menu ofrece una opcion para hablar en español, con recepcion, para pedir cita o con una persona ("para español pulse uno", "para pedir cita pulse dos"), pulsa esa tecla UNA sola vez con `play_keypad_touch_tone`, sin decir nada, y despues espera con `skip_turn`. Nunca pulses ninguna otra opcion (urgencias, ventas, administracion, extensiones, dejar un mensaje). Si tras pulsar vuelve el mismo menu, o si ninguna opcion encaja, cuelga con `end_call` sin decir nada. Si el menu anuncia espera o que te pasa con alguien, espera con `skip_turn` sin pulsar.
- Cuando por fin hable una persona despues de una grabacion o una espera, no ha oido nada de lo anterior: presentate entera con la misma apertura del principio ("{{saludo}}") y espera a que conteste antes de seguir.

SI TE LLAMAN ELLOS
Esta llamada es {{sentido}}. Si es "entrante", te han llamado ELLOS al numero de Vantelia (casi siempre para devolver una llamada nuestra) y ya les has saludado. Escucha que quieren:
- Si es por nuestra llamada: dilo en una frase ("Te llame yo, de Vantelia: ayudamos a negocios como el vuestro con las llamadas cuando estais ocupados") y sigue con LA PETICION (paso 2) sin volver a pedir permiso.
- Si es otra cosa: ayudale en lo que puedas con lo que sabes de Vantelia; si quiere hablar con una persona, `pasar_a_pablo`.
- El paso 1 es solo para cuando llamas tu. El resto (peticion, demostracion, quien decide, la demo gratuita y las salidas) es igual.

LO QUE TIENES QUE CONSEGUIR, EN ORDEN (las SALIDAS de abajo mandan sobre estos pasos)
1. LA APERTURA (cuando llamas tu). No dices nada hasta que contesten. En cuanto hable una persona (su saludo, "digame", el nombre del negocio) o si tras unos segundos nadie dice nada, di la apertura casi tal cual y en un solo turno: "{{saludo}}". Si mientras la dices te contestan solo "hola" o "buenos dias", no vuelvas a empezar: termina la frase. Dice quien eres y que eres una IA: no la cambies ni quites lo de la IA. Si lo que contesta es una grabacion, un menu o un buzon, sigue GRABACIONES, CENTRALITAS Y ESPERAS. Solo si te dicen claramente que te has equivocado de numero o que no es {{negocio}}, discúlpate y despidete. Si no entiendes lo que contestan, o te preguntan quien eres o de parte de quien, contestales corto (de Vantelia) y vuelve a pedir un momento con otras palabras: nunca des por hecho que te has equivocado de numero. Si has preguntado por {{responsable}} y no esta, ve directa al paso 5 ("Si no esta"): pregunta cuando suele estar y despidete, sin preguntas ni demostracion a quien te ha cogido. Si es ella o se pone: pidele treinta segundos y sigue en el paso 2.
2. LA PETICION. Si DESPUES de tu apertura te da permiso ("vale", "dime", "si"), di el motivo en media frase y, en el MISMO turno, la oferta de la demo, casi tal cual: "Te cuento: ayudamos a negocios como el vuestro con las llamadas; es una asistente como yo, que coge el telefono y el WhatsApp cuando no llegais y da las citas en vuestra agenda. {{oferta}}" La oferta va TAL CUAL, sin cambiar por donde se manda (paso 6). Una sola pregunta: la de la oferta. No le preguntes a quien te ha cogido como atienden, quien coge el telefono ni si le interesa: suele ser la recepcion y no le toca decidir (el 5-oct, en 7 de 12 llamadas colgaron justo despues de una pregunta asi). Un saludo, un "digame" o que confirmen el negocio NO son permiso para la demostracion ni para la peticion: espera a que te lo den.
3. ESCUCHA, Y SEGUN LO QUE CONTESTE:
   - Reacciona primero a lo que ha dicho, con sus mismas palabras. Nada de interrogatorios.
   - Si dice que si, que se lo mandes, o te da un email: usa `enviar_informacion` en ESE MISMO turno (paso 6).
   - Si dice que no es ella quien decide: justo por eso es la demo, para esa persona. Pide a donde mandarsela (su email o el del negocio), una vez; si te dicen su nombre o cuando esta, usa tambien `anotar_responsable`.
   - Si te pregunta que es, como funciona o quiere saber mas: "Pues justo para eso estoy yo: soy una inteligencia artificial que coge el telefono y el WhatsApp cuando estais liados y da las citas en vuestra agenda." Y vuelve a ofrecer mandar la demo. Si quiere oir como sonaria, ofrecele probarlo ahora con una cita de mentira (paso 4).
   - Si te pregunta cuanto cuesta: contestalo en una frase con los DATOS DE VANTELIA y vuelve a ofrecer mandar la demo.
   - Si esta liada o no es buen momento: no le cuentes nada mas. UNA vez: "Claro, es solo eso: me dices un email y la veis cuando podais." Si tampoco puede, pregunta cuando es mejor llamar, usa `volver_a_llamar` y despidete.
   - Si dice que ya lo tienen cubierto (tienen recepcionista, siempre lo cogen): no lo discutas. Como mucho UNA frase y sin insistir ("Genial. Donde mas ayuda es fuera de horario o cuando la recepcion esta con otra cosa; os la mando por si os sirve"). Si sigue sin querer, agradece, despidete y usa `end_call`.
   - Si dice que no le interesa: es la salida "No me interesa". No lo discutas.
   - Si en vez de dar permiso te dicen que esa persona esta ocupada o no esta (y no era una rellamada a {{responsable}}, que va en el paso 1): ofrece mandarle la demo a ella (paso 6) o pregunta cuando es mejor llamar.
4. Solo si acepta claramente probarlo: una demostracion CORTA, con los papeles claros. EL O ELLA hace de clienta que llama a su negocio y TU de su recepcionista: "Haz como si fueras una clienta llamando a tu negocio y pideme cita". TU NUNCA haces de clienta. En cuanto te pida cita, contestale en UN solo turno como una recepcionista resolutiva: ofrecele directamente un hueco concreto y verosimil para lo que pida (si no dice que servicio, uno tipico de su sector) y pregunta si se lo apuntas ("Claro, mañana a las diez y media tengo hueco para un corte, ¿te lo apunto?"). NO le preguntes por separado el servicio, el dia ni el nombre. Cuando diga que si: "Hecho, apuntado", y di claramente que era una simulacion y que con Vantelia lo harias con su agenda real. Termina ahi el turno y espera a que conteste. Si te interrumpe, responde a lo que acaba de decir: no avances de paso solo por seguir el guion.
5. QUIEN DECIDE. La demo es para quien lleva el negocio, asi que no hace falta preguntar si hablas con esa persona. Pregunta UNA sola vez, y solo si sale natural al apuntar a donde la mandas, como se llama ("¿Y a nombre de quien se la mando?"). Esa pregunta va SOLA, en su propio turno: nunca en el mismo turno en que cierras la demostracion. No lo preguntes si ya lo ha dicho ("si, soy yo") ni si has preguntado por {{responsable}} y es ella. Si ya te han dicho que quien decide no esta o que no es con quien tienes que hablar, nunca le preguntes a quien te atiende si es ella: pregunta como se llama esa persona, cuando suele estar y a donde mandarle la demo (lo de "Si no esta", abajo). En cuanto sepas algo de quien decide (su nombre, cuando esta, su email o que es ella), usa `anotar_responsable`.
   - Si te dicen que se pone ("un segundo", "ahora te la paso"): di "claro, espero" y usa `skip_turn` para esperar callada. Cuando hable la persona nueva, PRESENTATE ENTERA OTRA VEZ con la apertura ("{{saludo}}"), porque ella no lo ha oido. Despues sigue con ella (la peticion, paso 2).
   - Si no esta: pregunta su nombre y cuando suele estar; si te dan un email para ella, mandale la demo con `enviar_informacion`. Sin insistir si no quieren darlo.
   - Nunca pidas el movil personal de nadie. Si te lo dan, apuntalo y no digas que vas a llamar a ese numero.
6. LA DEMO GRATUITA (es el objetivo de la llamada). Se ofrece SIEMPRE con esta frase, tal cual: "{{oferta}}". Por donde se manda ya esta decidido ({{canal_envio}}): no lo cambies ni ofrezcas otro canal.
   - Si es "sms": cuando diga que si, NO le pidas ningun email: le llega por SMS a este numero.
   - Si es "email": cuando diga que si, se manda a ese correo; si te dan otro correo (el de quien lleve el negocio), apuntalo.
   - Si es "pedir_email": cuando diga que si, si no te lo ha dado ya, pidele el email y repitelo UNA vez de forma natural ("pablo arroba gmail punto com, ¿verdad?"). NO lo deletrees letra a letra salvo que te lo pidan.
   En cuanto diga que si, usa `enviar_informacion` en ESE MISMO turno, antes de despedirte (con el email solo si te ha dado uno). Luego dile por donde le llega y despidete. Nunca digas que se lo mandas sin haber usado antes `enviar_informacion`.
   - Si prefiere que le llamemos para enseñarselo (en vez de la demo o ademas): dale dos opciones concretas, "¿Te viene mejor {{huecos_pablo}}?". Le llama Pablo, el fundador, de lunes a viernes a cualquier hora: si prefiere otro dia u otra hora entre semana, vale; si pide sabado o domingo, propon el lunes. En cuanto diga cuando, usa `pasar_a_pablo` en ESE MISMO turno (cuando, tal cual lo ha dicho; su nombre si lo sabes; en notas, lo que le interesa) y confirmaselo en una frase ("Perfecto, te llama Pablo, el fundador, mañana por la mañana a este numero").
7. Despidete y usa `end_call`.

SALIDAS
- "No me interesa": despidete en voz alta ("Vale, gracias por tu tiempo. Que vaya bien.") y despues usa `end_call`: nunca cuelgues sin despedirte. No preguntes por quien decide ni ofrezcas la demostracion ni la demo gratuita.
- Si pide que le mandes informacion: ve directa al paso 6, sin demostracion ni preguntar por quien decide.
- Si pregunta quien eres o si eres un robot: contesta corto ("Soy Sara, una inteligencia artificial de Vantelia; ayudamos a los negocios a coger las llamadas") y sigue donde estabas, sin repetir la apertura entera.
- Si quiere hablar con una persona: dile que Pablo, el fundador, le llama; pregunta cuando le viene bien y usa `pasar_a_pablo`. Nunca des otro telefono ni finjas que le pasas la llamada.
- Si quien contesta dice que es otra IA o una recepcionista virtual: no le hagas la peticion ni la demostracion, ni uses `volver_a_llamar` o `enviar_informacion` por lo que diga. Si te pasa con una persona, espera; si no, despidete y usa `end_call`.
- "No me llameis mas" o enfado: pide disculpas, usa `no_volver_a_llamar` y despidete.
- Maximo cuatro minutos: si se alarga, ofrece la demo gratuita (paso 6).

DATOS DE VANTELIA (no inventes nada fuera de esto; si no lo sabes, lo confirma Pablo, el fundador)
- Planes: Free (0 euros), Starter (49 euros al mes), Pro (129 euros al mes, con WhatsApp), Business (299 euros al mes, con recepcionista de voz por telefono como tu). Diez dias de prueba.
- Se instala sin cambiar de numero ni de WhatsApp: siguen usando su app.
- Pablo, el fundador, llama de lunes a viernes a la hora que les venga bien y se lo enseña en diez minutos con su agenda.
- Web: vantelia punto es.
"""

_HERRAMIENTAS = {
    "enviar_informacion": (
        "Manda ya la demo gratuita (SMS o email) cuando diga que la quiere. Usala en cuanto diga "
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
        "Cuando prefiera que le llame Pablo, el fundador, para enseñarselo, o cuando pida hablar con "
        "una persona: apunta cuando le viene bien. Avisa a Pablo al momento.",
        {"type": "object", "description": "Para que Pablo le llame", "properties": {
            "cuando": {"type": "string", "description": "Cuando le viene bien que le llamen, tal cual"},
            "nombre": {"type": "string", "description": "Nombre de la persona, si lo ha dicho. Nunca el tuyo (Sara)"},
            "notas": {"type": "string", "description": "Lo que le interesa o lo que quiere hablar, en una frase"}},
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
            try:
                conn.execute("ALTER TABLE llamadas_voz ADD COLUMN %s %s" % (columna, tipo))
            except sqlite3.OperationalError as exc:
                # Dos conexiones a la vez sobre una base nueva: la otra la anadio entremedias.
                if "duplicate column" not in str(exc).lower():
                    raise
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


def oferta_de_demo(canal: str, negocio: str = "", email_dicho: str = "") -> str:
    """La frase con la que Sara ofrece la demo, ya decidida por el canal. Antes elegia ella
    entre tres frases del guion y en la primera prueba (5-oct-2026) ofrecio "el correo de
    Clinica Dental Pablo" a un movil, sin correo ninguno: ahora la frase la pone el servidor."""
    if canal == "sms":
        return ("¿Os mando por SMS a este número una pequeña demo gratuita, para que vea quien lleve "
                "el negocio cómo quedaría?")
    if canal == "email" and email_dicho:
        return ("¿Os mando una pequeña demo gratuita al correo de %s, %s, o prefieres que se la mande a "
                "quien lleve el negocio?" % (negocio or "vuestro negocio", email_dicho))
    return ("¿Me dices un email y os mando una pequeña demo gratuita, para que vea quien lleve el "
            "negocio cómo quedaría?")


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
# "Para español, pulse 1" (Madrid Vascular, 5-oct-2026): sin teclas, Sara colgaba en el menu.
# Funciona por el SIP del 91 (probado el 3-oct con la llamada de verificacion de WhatsApp, que
# pedia "pulse nueve"). El guion acota cuando: solo espanol, recepcion, citas o una persona.
PULSAR_TECLA = {
    "type": "system", "name": "play_keypad_touch_tone",
    "description": ("Pulsa una tecla del telefono. SOLO en un menu automatico, para la opcion de hablar en "
                    "español, con recepcion, para pedir cita o con una persona; una sola vez."),
    "params": {"system_tool_type": "play_keypad_touch_tone"},
}
# Si mientras espera no habla nadie en este rato, la llamada se corta.
SEGUNDOS_DE_SILENCIO_PARA_COLGAR = 75
# La llamada entera: el guion pide cuatro minutos; cinco dejan sitio a una espera en centralita.
SEGUNDOS_MAXIMOS_DE_LLAMADA = 300

# La voz de Sara, TAL CUAL viene de ElevenLabs: los ajustes de serie de "Laura - Customer
# service" (GET /v1/voices/{id}/settings). Pablo, 1-oct-2026: "dice 'hola, soy Sara, una IA' en
# un tono y luego '¿tienes treinta segundos?' como con otra voz; pon la voz estandar sin filtros".
# Historia: con la comun (0,7) se oian "dos voces" en un turno (28-sep) y se subio a 0,9 / 0,9,
# sin que se fuera: el modelo rapido genera la voz frase a frase y cada trozo puede salir con
# otro tono. Solo Sara: los agentes de los negocios siguen con el ajuste comun.
# Probado en llamadas con Pablo el mismo dia y descartado: eleven_v3_conversational y
# eleven_v4_turbo (este tambien con estabilidad 0,5 y modo expresivo) mantienen el tono entre
# turnos pero suenan "mas robot, le falta la emocion de la flash". Se queda Flash (MODELO_VOZ)
# con estos ajustes: "cambia un poco el tono pero esta bien". Modo expresivo apagado a proposito.
AJUSTES_DE_VOZ_DE_SARA = {"stability": 0.65, "similarity_boost": 0.76, "speed": 1.0, "expressive_mode": False}

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
        "true SOLO si la persona dijo claramente que si a que le mandemos la demo gratuita o la "
        "informacion (por SMS o por correo). false si dijo que no, si no se le pregunto o si no "
        "quedo claro.")},
    "email_para_informacion": {"type": "string", "description": (
        "El correo que dicto para mandarle la informacion, escrito como email (usuario@dominio). "
        "Vacio si no dio ninguno.")},
}


# Lo que valen las variables del guion en una llamada que ENTRA (no las manda nadie).
VARIABLES_DE_ENTRADA = {
    "negocio": "tu negocio", "sector": "un negocio con citas", VARIABLE_LLAMADA: "",
    "canal_envio": "pedir_email", "email_negocio": "", "a_quien": "tu negocio",
    "responsable": "quien lleva el negocio", "primera": SALUDO_ENTRANTE, "saludo": SALUDO_ENTRANTE,
    "sentido": "entrante", "huecos_pablo": HUECOS_ENTRANTE, "oferta": oferta_de_demo("pedir_email"),
}


def guion_de_entrada() -> str:
    """El guion con sus {{variables}} ya puestas para una entrante. Una variable sin valor
    aqui es un error (KeyError): colgaria la llamada igual que el 30-sep."""
    return re.sub(r"\{\{(\w+)\}\}", lambda m: VARIABLES_DE_ENTRADA[m.group(1)], GUION)


def agente_de_captacion(base_url: str, aviso_id: str = "", *, entrada: bool = False) -> Dict[str, Any]:
    """Sara en ElevenLabs. Con `aviso_id` (via SIP) lleva enganchado el aviso de fin de
    llamada de su cuenta, con los fallos al marcar: sin el no se sabria si no contestaron.
    Con `entrada`, la Sara que coge las llamadas al 91: sin ninguna variable nuestra (ni en el
    saludo, ni en el guion, ni en las tools), solo las del sistema."""
    base = base_url.rstrip("/")
    variables = {CAMPO_QUIEN: "system__caller_id", CAMPO_CONVERSACION: "system__conversation_id"}
    if not entrada:
        variables[CAMPO_LLAMADA] = VARIABLE_LLAMADA
    herramientas = [
        voz_elevenlabs.herramienta_webhook(nombre, descripcion, "%s%s/tool/%s" % (base, RUTA, nombre),
                                           esquema, variables)
        for nombre, (descripcion, esquema) in _HERRAMIENTAS.items()
    ] + [voz_elevenlabs.colgar("Cuelga despues de despedirte. Nunca durante un traspaso anunciado ni mientras "
                              "esperas a que hable alguien."), BUZON_SIN_MENSAJE, ESPERAR_CALLADA, PULSAR_TECLA]
    audio = voz_elevenlabs.formato_de_audio(telefono=True)
    voz = dict({"voice_id": settings.ELEVENLABS_VOICE_ID, "model_id": voz_elevenlabs.MODELO_VOZ}, **audio["tts"])
    voz.update(AJUSTES_DE_VOZ_DE_SARA)
    if entrada:
        agente = {"first_message": SALUDO_ENTRANTE, "language": "es",
                  "prompt": {"prompt": guion_de_entrada(), "llm": voz_elevenlabs.LLM_POR_DEFECTO,
                             "temperature": 0.4, "tools": herramientas}}
    else:
        agente = {"first_message": PRIMER_MENSAJE, "language": "es",
                  # Solo para probarla en el panel de ElevenLabs: en una llamada de verdad las
                  # manda siempre el servidor (`_variables`).
                  "dynamic_variables": {"dynamic_variable_placeholders": dict(VARIABLES_DE_ENTRADA)},
                  "prompt": {"prompt": GUION, "llm": voz_elevenlabs.LLM_POR_DEFECTO, "temperature": 0.4,
                             "tools": herramientas}}
    return {
        "name": NOMBRE_DEL_AGENTE_ENTRADA if entrada else NOMBRE_DEL_AGENTE,
        "conversation_config": {
            "agent": agente,
            "asr": audio["asr"],
            "tts": voz,
            "turn": {"speculative_turn": True, "silence_end_call_timeout": SEGUNDOS_DE_SILENCIO_PARA_COLGAR,
                     # Sin primer mensaje (al llamar ella): si nadie habla en estos segundos, empieza.
                     "initial_wait_time": SEGUNDOS_ANTES_DE_EMPEZAR,
                     "interruption_ignore_terms": list(SALUDOS_QUE_NO_INTERRUMPEN)},
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
    voz = clients._get_client_config(TENANT).get("voice") or {}
    previo = str(voz.get(CLAVE_AGENTE) or "")
    previo_entrada = str(voz.get(CLAVE_AGENTE_ENTRADA) or "")
    base = base_url or settings.APP_BASE_URL
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=60.0)
    try:
        aviso_id = asegurar_aviso(cliente, base) if via_sip() else ""
        agent_id = voz_elevenlabs.publicar_agente(cliente, agente_de_captacion(base, aviso_id), previo)
        if agent_id != previo:
            voz_elevenlabs.guardar_en_voz(TENANT, CLAVE_AGENTE, agent_id)
        numero_id = entrada_id = ""
        if via_sip():
            # Al 91 se asigna la Sara de ENTRADA (es la que coge cuando llaman); las salientes
            # dicen en cada llamada que agente usar.
            entrada_id = voz_elevenlabs.publicar_agente(
                cliente, agente_de_captacion(base, aviso_id, entrada=True), previo_entrada)
            if entrada_id != previo_entrada:
                voz_elevenlabs.guardar_en_voz(TENANT, CLAVE_AGENTE_ENTRADA, entrada_id)
            numero_id = asegurar_numero_sip(cliente, entrada_id)
    finally:
        if propio:
            cliente.close()
    return dict({"agent_id": agent_id},
                **({"agente_entrada": entrada_id, "numero_sip": numero_id, "aviso": aviso_id} if via_sip() else {}))


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
    canal = canal_de_envio(fila["telefono"], email_negocio)
    return {"negocio": negocio, "sector": fila["sector"] or "un negocio con citas",
            VARIABLE_LLAMADA: fila["id"], "canal_envio": canal,
            "oferta": oferta_de_demo(canal, negocio, email_hablado(email_negocio)),
            "email_negocio": email_hablado(email_negocio),
            "a_quien": responsable or (negocio_hablado(negocio, fila["sector"]) if fila["negocio"] else negocio),
            "responsable": responsable or "quien lleva el negocio",
            "saludo": (APERTURA_RELLAMADA % responsable) if responsable else APERTURA,
            "sentido": "saliente", "primera": PRIMERA_SALIENTE, "huecos_pablo": huecos_de_pablo()}


def huecos_de_pablo(ahora: Optional[datetime] = None) -> str:
    """Los dos huecos que Sara propone para que llame Pablo: el siguiente dia laborable por la
    mañana y el otro por la tarde ("mañana por la mañana o el jueves por la tarde"). Nunca hoy
    (nadie quiere que le llamen en una hora) ni en fin de semana."""
    hoy = (ahora or datetime.now(timezone.utc)).astimezone(ZoneInfo("Europe/Madrid")).date()
    dias = []
    dia = hoy
    while len(dias) < 2:
        dia += timedelta(days=1)
        if dia.weekday() < 5:
            dias.append(dia)

    def dicho(d):
        return "mañana" if d == hoy + timedelta(days=1) else "el " + _DIAS_DE_LA_SEMANA[d.weekday()]

    return "%s por la mañana o %s por la tarde" % (dicho(dias[0]), dicho(dias[1]))


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
    """El 91 del proveedor SIP importado en la cuenta activa y con `agent_id` asignado (la Sara
    de entrada: la que coge cuando llaman). Devuelve su id."""
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
    email_negocio = str(fila["prospecto"] or "").strip().lower()
    if dado and not _EMAIL.match(dado):
        if not email_negocio:
            return {"ok": False, "error": "Ese email no parece completo. Pideselo otra vez."}
        # Mal dictado, pero el negocio ya tiene su correo en captacion: mejor ahi que perderlo
        # (Dental Navarro, 2-oct-2026: estaba gonzalo@ y no le llego nada).
        dado = ""
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
    except Exception as exc:  # noqa: BLE001 - no poder mandarlo no puede perder al interesado
        settings.logger.exception("[captacion_voz] no se pudo mandar la informacion de %s", fila["id"])
        canal, enviado = ("email" if destino_email else "sms"), False
        # Segundo intento SOLO si consta que el primero no salio: el servidor rechazo al
        # destinatario. Un corte tras aceptar el mensaje no es eso, y reintentar duplicaria el
        # correo (revision de Astra a 52bd382, 4-oct-2026; NORMAS_AGENTE_IA).
        if (isinstance(exc, smtplib.SMTPRecipientsRefused) and destino_email and email_negocio
                and email_negocio != destino_email and _EMAIL.match(email_negocio)):
            # El destino se apunta ANTES: si este segundo envio queda en duda, la ficha y el aviso
            # tienen que decir a donde pudo salir, no el correo que ya sabemos rechazado (Astra).
            destino_email = email_negocio
            try:
                enviado = _mandar_correo(email_negocio, correo(negocio, enlace))
            except Exception:  # noqa: BLE001
                settings.logger.exception("[captacion_voz] tampoco al correo del negocio de %s", fila["id"])
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


MINUTOS_MISMA_ENTRANTE = 30


def _fila_entrante(quien: str, conversation_id: str = "", cuando: str = ""):
    """La ficha de una llamada que nos hacen al 91. La primera vez se crea, con el negocio,
    sector y email de nuestra ultima llamada a ese numero si la hubo; despues se reutiliza (por
    la conversacion, o la del mismo numero de los ultimos minutos). None si no hay por donde.

    `cuando` = hora real de la llamada si se crea tarde (al recogerla): con la de la recogida,
    parecia posterior a una saliente y cancelaba su rellamada (revision de Astra, 30-sep)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,80}", conversation_id or ""):
        conversation_id = ""
    telefono = telefono_e164(quien) if quien else ""
    if not (telefono or conversation_id):
        return None
    hace = (timeutils._utc_now() - timedelta(minutes=MINUTOS_MISMA_ENTRANTE)).isoformat(timespec="seconds")
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        # Buscar y crear en UNA transaccion de escritura: dos herramientas a la vez en la misma
        # entrante creaban dos fichas, cada una con su sello de envio (revision de Astra, 30-sep).
        conn.execute("BEGIN IMMEDIATE")
        llamada_id = ""
        if conversation_id:
            fila = conn.execute("SELECT id FROM llamadas_voz WHERE conversation_id=?", (conversation_id,)).fetchone()
            llamada_id = fila["id"] if fila is not None else ""
        if not llamada_id and telefono:
            # Solo la de la MISMA conversacion (o una aun sin ella): dos llamadas del mismo numero
            # en media hora son dos fichas, o la segunda pisaba la transcripcion y el sello de
            # envio de la primera (revision de Astra, 30-sep-2026).
            fila = conn.execute("SELECT id, conversation_id FROM llamadas_voz WHERE telefono=? AND origen='entrante' "
                                "AND creada >= ? AND (? = '' OR conversation_id = '') ORDER BY creada DESC LIMIT 1",
                                (telefono, hace, conversation_id)).fetchone()
            if fila is not None:
                llamada_id = fila["id"]
                if conversation_id and not fila["conversation_id"]:
                    conn.execute("UPDATE llamadas_voz SET conversation_id=? WHERE id=?", (conversation_id, llamada_id))
        if not llamada_id:
            previa = conn.execute("SELECT negocio, sector, prospecto FROM llamadas_voz WHERE telefono=? AND "
                                  "origen<>'entrante' ORDER BY creada DESC LIMIT 1",
                                  (telefono,)).fetchone() if telefono else None
            llamada_id, ahora = "ll_" + secrets.token_urlsafe(9), _ahora()
            creada = cuando or ahora
            conn.execute("INSERT INTO llamadas_voz (id, telefono, negocio, sector, prospecto, estado, origen, "
                         "conversation_id, creada, actualizada) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (llamada_id, telefono, previa["negocio"] if previa else "", previa["sector"] if previa else "",
                          previa["prospecto"] if previa else "", "en_curso", "entrante", conversation_id, creada, ahora))
        conn.commit()
    return _fila(llamada_id)


def herramienta(nombre: str, cuerpo: Dict[str, Any]) -> Dict[str, Any]:
    """Lo que hace cada tool de la agente de captacion."""
    llamada_id = str(cuerpo.get(CAMPO_LLAMADA) or "")
    fila = _fila(llamada_id) if llamada_id else None
    if fila is None and not llamada_id:
        # Una llamada que ENTRA no tiene id (Astra, 30-sep: sin esto, "No encuentro esta llamada").
        fila = _fila_entrante(str(cuerpo.get(CAMPO_QUIEN) or ""), str(cuerpo.get(CAMPO_CONVERSACION) or ""))
        llamada_id = fila["id"] if fila is not None else ""
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
                    notas=("Le llama Pablo. Cuando: %s. %s %s" % (cuando or "-", persona, notas)).strip())
        _avisar_a_pablo(fila, cuando, persona, notas)
        return {"ok": True, "mensaje": "Apuntado: Pablo le llamara. Confirmaselo en una frase (cuando y a este "
                                       "numero) y despidete."}
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
                                        "nueva, presentate entera otra vez con la misma apertura del principio "
                                        "(quien eres y que eres una IA) y espera a que conteste.")}
    return {"ok": True, "mensaje": ("Apuntado. Ofrece mandar la demo gratuita para quien decide y despidete; si "
                                    "quien te atiende tiene curiosidad, puedes hacerle la demo.")}


def _avisar_a_pablo(fila, cuando: str, persona: str, notas: str) -> None:
    """Le interesa (o pide hablar con una persona) y ha quedado en que le llama Pablo: tiene que
    enterarse al momento."""
    from backend import outreach

    negocio = fila["negocio"] or fila["telefono"]
    asunto = "🙋 Llámale: %s" % negocio
    texto = ("En una llamada de Sara han quedado en que les llamas tu.\n\n"
             "Negocio:  %s\nTelefono: %s\nCuando:   %s\nPersona:  %s\nNotas:    %s\n"
             % (negocio, fila["telefono"], cuando or "-", persona or "-", notas or "-"))
    html = ("<div style='font-family:sans-serif'><h2 style='color:#00b1d9'>🙋 %s</h2>"
            "<p>Han quedado en que les llamas tu.</p>"
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
