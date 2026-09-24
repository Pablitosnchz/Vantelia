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
- Contestador (deteccion de Twilio): se cuelga sin dejar mensaje.

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
WEB = "https://www.vantelia.es"

PRIMER_MENSAJE = ("Hola, buenas. Soy Sara, una asistente virtual de Vantelia. "
                  "¿Hablo con {{negocio}}?")

GUION = """Eres Sara, una asistente virtual de Vantelia: una inteligencia artificial, y lo dices. Llamas por telefono a {{negocio}} ({{sector}}).

POR QUE LLAMAS
Vantelia pone en negocios con citas una asistente como tu: coge el telefono y el WhatsApp cuando el equipo esta ocupado, da citas, las cambia y las cancela. Tu propia llamada es la prueba de como sonaria.

COMO HABLAS
- Habla SIEMPRE en español de España. Nunca en ingles, ni repitas una frase traducida.
- De tu, cercana, frases cortas. Una idea por turno y deja hablar.
- Nada de listas, nada de leer parrafos, numeros y precios en palabras.
- Si preguntan si eres una persona o un robot: eres una IA, justo lo que les ofrecemos.

LO QUE TIENES QUE CONSEGUIR, EN ORDEN
1. Ya te has presentado. Si no es {{negocio}}, discúlpate y despidete.
2. En cuanto confirmen, primero el gancho y al final el aviso corto, en UN solo turno y casi tal cual: "Te llamo porque soy justo lo que os ofrecemos: una recepcionista que os coge el telefono cuando estais con las manos ocupadas. ¿Te lo enseño en un minuto? Es comercial, y si no quieres mas llamadas, me lo dices." No expliques nada mas antes de que conteste. (Decir que es comercial y que puede no querer mas llamadas es obligatorio al empezar: no lo quites, solo dilo asi de corto.)
3. Si no es buen momento: pregunta cuando llamar y con quien, usa `volver_a_llamar` y despidete.
4. Si dice que si: la demostracion, con los papeles claros. EL O ELLA hace de clienta que llama a su negocio y TU de su recepcionista: "Haz como si fueras una clienta llamando a tu negocio y pideme cita". TU NUNCA haces de clienta. Atiendele como una recepcionista de verdad: pregunta que servicio y que dia, ofrece huecos verosimiles, pide su nombre y repite la cita al final ("te apunto el martes a las diez para un corte, a nombre de Marta"). Despues di claramente que era una simulacion y que con Vantelia lo harias con su agenda real.
5. Cierre segun {{canal_envio}}:
   - "sms": "¿Te mando un SMS a este numero con un enlace para verlo con tu propio negocio?"
   - "email": "¿Te lo mando al correo de {{negocio}}, {{email_negocio}}?" Si prefiere otro correo, apuntalo.
   - "pedir_email": pide un email para mandarselo y repitelo UNA vez de forma natural ("pablo arroba gmail punto com, ¿verdad?"). NO lo deletrees letra a letra salvo que te lo pidan.
   En cuanto diga que si, usa `enviar_informacion` en ESE MISMO turno, antes de despedirte (con el email solo si te ha dado uno). Luego dile por donde le llega y despidete.
6. Despidete y usa `end_call`.

SALIDAS
- "No me interesa": agradece, no insistas, despidete.
- "No me llameis mas" o enfado: pide disculpas, usa `no_volver_a_llamar` y despidete.
- Si esta el equipo pero no quien decide: pregunta cuando le pillas y ofrece mandar la informacion igual (paso 5).
- Maximo cuatro minutos: si se alarga, ofrece mandar la informacion (paso 5).

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
            "nombre": {"type": "string", "description": "Nombre de quien atiende, si lo ha dicho"},
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


def agente_de_captacion(base_url: str) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    herramientas = [
        voz_elevenlabs.herramienta_webhook(nombre, descripcion, "%s%s/tool/%s" % (base, RUTA, nombre),
                                           esquema, {CAMPO_LLAMADA: VARIABLE_LLAMADA})
        for nombre, (descripcion, esquema) in _HERRAMIENTAS.items()
    ] + [voz_elevenlabs.colgar("Cuelga despues de despedirte.")]
    audio = voz_elevenlabs.formato_de_audio(telefono=True)
    return {
        "name": "Sara - captacion Vantelia (telefono)",
        "conversation_config": {
            "agent": {
                "first_message": PRIMER_MENSAJE,
                "language": "es",
                "dynamic_variables": {"dynamic_variable_placeholders": {
                    "negocio": "tu negocio", "sector": "un negocio con citas", VARIABLE_LLAMADA: "",
                    "canal_envio": "pedir_email", "email_negocio": ""}},
                "prompt": {"prompt": GUION, "llm": voz_elevenlabs.LLM_POR_DEFECTO, "temperature": 0.4,
                           "tools": herramientas},
            },
            "asr": audio["asr"],
            "tts": dict({"voice_id": settings.ELEVENLABS_VOICE_ID, "model_id": voz_elevenlabs.MODELO_VOZ},
                        **audio["tts"]),
            "turn": {"speculative_turn": True},
        },
    }


def sincronizar_agente(*, base_url: str = "", cliente: Optional[httpx.Client] = None) -> Dict[str, Any]:
    from backend import clients

    if not voz_elevenlabs.configurado():
        raise RuntimeError("Falta ELEVENLABS_API_KEY o ELEVENLABS_TOOL_SECRET.")
    previo = str((clients._get_client_config(TENANT).get("voice") or {}).get(CLAVE_AGENTE) or "")
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=60.0)
    try:
        agent_id = voz_elevenlabs.publicar_agente(cliente, agente_de_captacion(base_url or settings.APP_BASE_URL),
                                                  previo)
    finally:
        if propio:
            cliente.close()
    if agent_id != previo:
        voz_elevenlabs.guardar_en_voz(TENANT, CLAVE_AGENTE, agent_id)
    return {"agent_id": agent_id}


def _numero_de_salida() -> str:
    return settings.CAPTACION_TWILIO_NUMBER or settings.TWILIO_DEFAULT_PHONE_NUMBER


def llamar(telefono: str, negocio: str, sector: str = "", prospecto: str = "", *,
           base_url: str = "", cliente: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Apunta la llamada y pide a Twilio que marque. No marca si ese telefono pidio que no."""
    numero = telefono_e164(telefono)
    if not numero:
        raise ValueError("Telefono no valido.")
    if not puede_llamarse(numero):
        return {"ok": False, "motivo": "no_llamar"}
    if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and _numero_de_salida()):
        raise RuntimeError("Twilio no esta configurado para llamar.")
    if not prospecto:
        # El negocio de la captacion, si lo tenemos: su email es a donde se ofrece mandar.
        encontrado = _prospecto_por(telefono=numero)
        prospecto = str((encontrado or {}).get("email") or "")
    llamada_id = "ll_" + secrets.token_urlsafe(9)
    ahora = _ahora()
    with _db() as conn:
        conn.execute("INSERT INTO llamadas_voz (id, telefono, negocio, sector, prospecto, estado, creada, "
                     "actualizada) VALUES (?,?,?,?,?,?,?,?)",
                     (llamada_id, numero, textnorm._sanitize_text(negocio)[:120],
                      textnorm._sanitize_text(sector)[:80], str(prospecto or "")[:200], "marcando", ahora, ahora))
        conn.commit()
    base = (base_url or settings.APP_BASE_URL).rstrip("/")
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=30.0)
    try:
        r = cliente.post(
            "https://api.twilio.com/2010-04-01/Accounts/%s/Calls.json" % settings.TWILIO_ACCOUNT_SID,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            data={"To": numero, "From": _numero_de_salida(), "Timeout": "25",
                  "Url": "%s%s/twiml?llamada=%s" % (base, RUTA, llamada_id),
                  "StatusCallback": "%s%s/estado?llamada=%s" % (base, RUTA, llamada_id),
                  "MachineDetection": "Enable"})
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
    email_negocio = str(fila["prospecto"] or "")
    twiml = voz_elevenlabs.twiml_registrar_llamada(
        agente, desde, hacia, "outbound",
        {"negocio": fila["negocio"] or "tu negocio", "sector": fila["sector"] or "un negocio con citas",
         VARIABLE_LLAMADA: llamada_id, "canal_envio": canal_de_envio(fila["telefono"], email_negocio),
         "email_negocio": email_hablado(email_negocio)}, cliente=cliente)
    _actualizar(llamada_id, estado="en_curso")
    return twiml


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
            "Pruebalo gratis. Dudas: Pablo, %s" % (textnorm._strip_accents(negocio), enlace, TELEFONO_PABLO))


def correo(negocio: str, enlace: str) -> Dict[str, str]:
    texto = (
        "Hola,\n\n"
        "Soy Sara, la asistente virtual de Vantelia que os ha llamado hace un momento. Así "
        "atendería el teléfono y el WhatsApp de %s: da citas, las cambia y las cancela mientras "
        "estáis con las manos ocupadas.\n\n"
        "Pruébalo con tu propio negocio: %s\n\n"
        "Si prefieres que te lo enseñe una persona, Pablo (el fundador) te atiende en el %s o "
        "respondiendo a este correo.\n\n"
        "Un saludo,\nSara · Vantelia\n" % (negocio, enlace, TELEFONO_PABLO))
    html = (
        "<div style='font-family:sans-serif;max-width:560px;color:#1a1a2e;line-height:1.5'>"
        "<p>Hola,</p><p>Soy Sara, la asistente virtual de Vantelia que os ha llamado hace un "
        "momento. Así atendería el teléfono y el WhatsApp de <strong>%s</strong>: da citas, las "
        "cambia y las cancela mientras estáis con las manos ocupadas.</p>"
        "<p><a href='%s' style='display:inline-block;padding:11px 20px;border-radius:999px;"
        "background:#00D1FF;color:#04101C;font-weight:700;text-decoration:none'>Pruébalo con tu "
        "negocio</a></p><p>Si prefieres que te lo enseñe una persona, Pablo (el fundador) te "
        "atiende en el %s o respondiendo a este correo.</p><p>Un saludo,<br>Sara · Vantelia</p></div>"
        % (escape(negocio), escape(enlace, quote=True), TELEFONO_PABLO))
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
            conn.commit()
        _actualizar(llamada_id, resultado="no_llamar", notas=motivo)
        return {"ok": True, "mensaje": "Apuntado: no se le vuelve a llamar. Pide disculpas y despidete."}
    return {"ok": False, "error": "Herramienta desconocida."}


def _avisar_interes(fila, destino: str, nombre: str, notas: str, canal: str, enviado: bool,
                    enlace: str) -> None:
    from backend import outreach

    negocio = fila["negocio"] or fila["telefono"]
    estado = ("Le hemos mandado el enlace por %s." % canal) if enviado else (
        "NO se pudo mandar el %s: escribele tu." % canal)
    asunto = "📞 Interesado por telefono: %s" % negocio
    texto = ("Sara ha hablado con un negocio interesado:\n\nNegocio:  %s\nTelefono: %s\nEnviado a: %s\n"
             "Contacto: %s\nNotas:    %s\nEnlace:   %s\n\n%s\n"
             % (negocio, fila["telefono"], destino, nombre or "-", notas or "-", enlace, estado))
    html = ("<div style='font-family:sans-serif'><h2 style='color:#00b1d9'>📞 %s</h2>"
            "<p>Telefono: %s<br>Enviado a: %s<br>Contacto: %s</p><p>%s</p>"
            "<p><a href='%s'>Enlace enviado</a></p><p><strong>%s</strong></p></div>"
            % (escape(negocio), escape(fila["telefono"]), escape(destino), escape(nombre or "-"),
               escape(notas or "-"), escape(enlace, quote=True), escape(estado)))
    try:
        outreach._outreach_notify_admin(asunto, texto, html)
    except Exception:  # noqa: BLE001 - el aviso nunca tumba la llamada
        settings.logger.exception("[captacion_voz] no se pudo avisar del interesado %s", destino)
