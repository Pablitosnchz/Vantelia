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
TELEFONO_PABLO = "675 802 001"
EMAIL_VANTELIA = "info@vantelia.es"
WEB = "https://www.vantelia.es"

# {{a_quien}} es el negocio, o el nombre de quien decide cuando se le vuelve a llamar
# a proposito (docs/PLAN_HABLAR_CON_EL_RESPONSABLE.md).
PRIMER_MENSAJE = ("Hola, buenas. Soy Sara, una asistente virtual de Vantelia. "
                  "¿Hablo con {{a_quien}}?")

GUION = """Eres Sara, una asistente virtual de Vantelia: una inteligencia artificial, y lo dices. Llamas por telefono a {{negocio}} ({{sector}}).

POR QUE LLAMAS
Vantelia pone en negocios con citas una asistente como tu: coge el telefono y el WhatsApp cuando el equipo esta ocupado, da citas, las cambia y las cancela. Tu propia llamada es la prueba de como sonaria.

COMO HABLAS
- Habla SIEMPRE en español de España. Nunca en ingles, ni repitas una frase traducida.
- De tu, cercana, frases cortas. Una idea por turno y deja hablar.
- Nada de listas, nada de leer parrafos, numeros y precios en palabras.
- Si preguntan si eres una persona o un robot: eres una IA, justo lo que les ofrecemos.

LO QUE TIENES QUE CONSEGUIR, EN ORDEN
1. Ya te has presentado. Si no es {{negocio}} (numero equivocado), discúlpate y despidete. Si has preguntado por {{responsable}} y no esta, ve directa al paso 3 (no esta).
2. En cuanto confirmen, primero el gancho y al final el aviso corto, en UN solo turno y casi tal cual: "Te llamo porque soy justo lo que os ofrecemos: una recepcionista que os coge el telefono cuando estais con las manos ocupadas. ¿Te lo enseño en un minuto? Es comercial, y si no quieres mas llamadas, me lo dices." No expliques nada mas antes de que conteste. (Decir que es comercial y que puede no querer mas llamadas es obligatorio al empezar: no lo quites, solo dilo asi de corto.)
3. QUIEN DECIDE. Justo despues del gancho, cuando conteste, pregunta UNA sola vez y de forma natural si hablas con quien lleva el negocio (por ejemplo: "Por cierto, ¿hablo con quien lleva el salon?"). No lo preguntes si ya lo ha dicho ("si, soy yo") ni si has preguntado por {{responsable}} y es ella. En cuanto lo sepas, usa `anotar_responsable`.
   - Si es la duena o la encargada: sigue en el paso 4.
   - Si no lo es: pregunta por esa persona ("¿Y esta por ahi? ¿Me pasas con ella?").
     * Si te dicen que se pone ("un segundo", "ahora te la paso"): di "claro, espero" y usa `skip_turn` para esperar callada. Cuando hable la persona nueva, PRESENTATE ENTERA OTRA VEZ, porque ella no lo ha oido: quien eres, que eres una asistente virtual de Vantelia, el gancho y el aviso de que es comercial y de que puede pedir no mas llamadas. Despues sigue en el paso 4 con ella.
     * Si no esta: pregunta su nombre y cuando suele estar; si te ofrecen un email para mandarle la informacion, apuntalo. Sin insistir si no quieren darlo. Si quien te atiende tiene curiosidad, puedes hacerle la demo, pero el cierre va para quien decide.
   - Nunca pidas el movil personal de nadie. Si te lo dan, apuntalo y no digas que vas a llamar a ese numero.
4. Si no es buen momento: pregunta cuando llamar y con quien, usa `volver_a_llamar` y despidete.
5. Si dice que si: la demostracion, con los papeles claros. EL O ELLA hace de clienta que llama a su negocio y TU de su recepcionista: "Haz como si fueras una clienta llamando a tu negocio y pideme cita". TU NUNCA haces de clienta. Atiendele como una recepcionista de verdad: pregunta que servicio y que dia, ofrece huecos verosimiles, pide su nombre y repite la cita al final ("te apunto el martes a las diez para un corte, a nombre de Marta"). Despues di claramente que era una simulacion y que con Vantelia lo harias con su agenda real.
6. Cierre segun {{canal_envio}}:
   - "sms": "¿Te mando un SMS a este numero con un enlace para verlo con tu propio negocio?"
   - "email": "¿Te lo mando al correo de {{negocio}}, {{email_negocio}}?" Si prefiere otro correo, apuntalo.
   - "pedir_email": pide un email para mandarselo y repitelo UNA vez de forma natural ("pablo arroba gmail punto com, ¿verdad?"). NO lo deletrees letra a letra salvo que te lo pidan.
   En cuanto diga que si, usa `enviar_informacion` en ESE MISMO turno, antes de despedirte (con el email solo si te ha dado uno). Luego dile por donde le llega y despidete.
7. Despidete y usa `end_call`.

SALIDAS
- "No me interesa": agradece, no insistas, despidete.
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
                          ("rellamada_de", "TEXT NOT NULL DEFAULT ''")):
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
                   "espera callada hasta que vuelvan a hablar.",
    "params": {"system_tool_type": "skip_turn"},
}
# Si mientras espera no habla nadie en este rato, la llamada se corta.
SEGUNDOS_DE_SILENCIO_PARA_COLGAR = 75

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
    "responsable_nombre": {"type": "string", "description": "Nombre de quien decide en el negocio, si salio."},
}


def agente_de_captacion(base_url: str, aviso_id: str = "") -> Dict[str, Any]:
    """Sara en ElevenLabs. Con `aviso_id` (via SIP) lleva enganchado el aviso de fin de
    llamada de su cuenta, con los fallos al marcar: sin el no se sabria si no contestaron."""
    base = base_url.rstrip("/")
    herramientas = [
        voz_elevenlabs.herramienta_webhook(nombre, descripcion, "%s%s/tool/%s" % (base, RUTA, nombre),
                                           esquema, {CAMPO_LLAMADA: VARIABLE_LLAMADA})
        for nombre, (descripcion, esquema) in _HERRAMIENTAS.items()
    ] + [voz_elevenlabs.colgar("Cuelga despues de despedirte."), BUZON_SIN_MENSAJE, ESPERAR_CALLADA]
    audio = voz_elevenlabs.formato_de_audio(telefono=True)
    return {
        "name": "Sara - captacion Vantelia (telefono)",
        "conversation_config": {
            "agent": {
                "first_message": PRIMER_MENSAJE,
                "language": "es",
                "dynamic_variables": {"dynamic_variable_placeholders": {
                    "negocio": "tu negocio", "sector": "un negocio con citas", VARIABLE_LLAMADA: "",
                    "canal_envio": "pedir_email", "email_negocio": "", "a_quien": "tu negocio",
                    "responsable": "quien lleva el negocio"}},
                "prompt": {"prompt": GUION, "llm": voz_elevenlabs.LLM_POR_DEFECTO, "temperature": 0.4,
                           "tools": herramientas},
            },
            "asr": audio["asr"],
            "tts": dict({"voice_id": settings.ELEVENLABS_VOICE_ID, "model_id": voz_elevenlabs.MODELO_VOZ},
                        **audio["tts"]),
            "turn": {"speculative_turn": True, "silence_end_call_timeout": SEGUNDOS_DE_SILENCIO_PARA_COLGAR},
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


def _variables(fila) -> Dict[str, str]:
    """Lo que Sara sabe de la llamada ({{negocio}}, {{a_quien}}...). Las mismas por Twilio y
    por SIP: el guion no sabe por donde se ha marcado."""
    email_negocio = str(fila["prospecto"] or "")
    negocio = fila["negocio"] or "tu negocio"
    # En una rellamada dirigida se pregunta por quien decide; si no, por el negocio.
    responsable = str(fila["responsable_nombre"] or "") if fila["rellamada_de"] else ""
    return {"negocio": negocio, "sector": fila["sector"] or "un negocio con citas",
            VARIABLE_LLAMADA: fila["id"], "canal_envio": canal_de_envio(fila["telefono"], email_negocio),
            "email_negocio": email_hablado(email_negocio), "a_quien": responsable or negocio,
            "responsable": responsable or "quien lleva el negocio"}


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
    r = cliente.post(voz_elevenlabs.API + "/v1/convai/phone-numbers", headers=voz_elevenlabs._cabeceras(), json={
        "phone_number": settings.CAPTACION_SIP_NUMERO, "label": "Sara - captacion (SIP)",
        "provider": "sip_trunk", "agent_id": agent_id,
        "inbound_trunk_config": {"media_encryption": "disabled"},
        "outbound_trunk_config": _salida_sip()})
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
                         headers=voz_elevenlabs._cabeceras(),
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


def texto_sms(negocio: str, enlace: str) -> str:
    # Sin tildes a proposito: con una sola, el SMS pasa a otra codificacion y cuesta el doble.
    return ("Hola! Soy Sara, de Vantelia. Asi atenderia el telefono y el WhatsApp de %s: %s "
            "Pruebalo gratis. Cualquier duda, te llamamos: escribe a Pablo al %s o a %s"
            % (textnorm._strip_accents(negocio), enlace, TELEFONO_PABLO, EMAIL_VANTELIA))


def correo(negocio: str, enlace: str) -> Dict[str, str]:
    texto = (
        "Hola,\n\n"
        "Soy Sara, la asistente virtual de Vantelia que os ha llamado hace un momento. Así "
        "atendería el teléfono y el WhatsApp de %s: da citas, las cambia y las cancela mientras "
        "estáis con las manos ocupadas.\n\n"
        "Pruébalo con tu propio negocio: %s\n\n"
        "¿Alguna duda? Te llamamos cuando te venga bien: escribe a Pablo al %s, a %s o "
        "responde a este correo.\n\n"
        "Un saludo,\nSara · Vantelia\n" % (negocio, enlace, TELEFONO_PABLO, EMAIL_VANTELIA))
    html = (
        "<div style='font-family:sans-serif;max-width:560px;color:#1a1a2e;line-height:1.5'>"
        "<p>Hola,</p><p>Soy Sara, la asistente virtual de Vantelia que os ha llamado hace un "
        "momento. Así atendería el teléfono y el WhatsApp de <strong>%s</strong>: da citas, las "
        "cambia y las cancela mientras estáis con las manos ocupadas.</p>"
        "<p><a href='%s' style='display:inline-block;padding:11px 20px;border-radius:999px;"
        "background:#00D1FF;color:#04101C;font-weight:700;text-decoration:none'>Pruébalo con tu "
        "negocio</a></p><p>¿Alguna duda? Te llamamos cuando te venga bien: escribe a Pablo al %s, "
        "a <a href='mailto:%s'>%s</a> o responde a este correo.</p><p>Un saludo,<br>Sara · Vantelia</p></div>"
        % (escape(negocio), escape(enlace, quote=True), TELEFONO_PABLO, EMAIL_VANTELIA, EMAIL_VANTELIA))
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


def _enviar_informacion(fila, cuerpo: Dict[str, Any]) -> Dict[str, Any]:
    dado = str(cuerpo.get("email") or "").strip().lower().replace(" ", "")
    if dado and not _EMAIL.match(dado):
        return {"ok": False, "error": "Ese email no parece completo. Pideselo otra vez."}
    email_negocio = str(fila["prospecto"] or "")
    destino_email = dado or ("" if es_movil(fila["telefono"]) else email_negocio)
    if not destino_email and not es_movil(fila["telefono"]):
        return {"ok": False, "error": "No tengo a donde mandarlo: pidele un email."}
    negocio = fila["negocio"] or "tu negocio"
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
    _actualizar(fila["id"], resultado="interesado", email=destino_email,
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
        return {"ok": True, "mensaje": "Apuntado. Hablas con quien decide: sigue con la demostracion."}
    if se_pone:
        return {"ok": True, "mensaje": ("Apuntado. Di 'claro, espero' y espera callada. Cuando hable la persona "
                                        "nueva, presentate entera otra vez: quien eres, que eres una asistente "
                                        "virtual, el gancho y el aviso de que es comercial.")}
    return {"ok": True, "mensaje": ("Apuntado. Ofrece mandar la informacion para quien decide y despidete; si "
                                    "quien te atiende tiene curiosidad, puedes hacerle la demo.")}


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
