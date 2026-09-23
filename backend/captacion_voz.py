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

FLUJO
-----
`llamar()` apunta la llamada en `llamadas_voz` (base de captacion) y pide a Twilio
que marque. Cuando descuelgan, Twilio pide `POST /voice/el-captacion/twiml`, que
devuelve el TwiML de ElevenLabs con el negocio y el sector como variables. Las tools
de la agente llegan a `POST /voice/el-captacion/tool/{nombre}`.
"""
from __future__ import annotations

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

PRIMER_MENSAJE = ("Hola, buenas. Soy Sara, una asistente virtual de Vantelia. "
                  "¿Hablo con {{negocio}}?")

GUION = """Eres Sara, una asistente virtual de Vantelia: una inteligencia artificial, y lo dices. Llamas por telefono a {{negocio}} ({{sector}}).

POR QUE LLAMAS
Vantelia pone en negocios con citas una asistente como tu: coge el telefono y el WhatsApp cuando el equipo esta ocupado, da citas, las cambia y las cancela. Tu propia llamada es la prueba de como sonaria.

COMO HABLAS
- Español de España, de tu, cercana, frases cortas. Una idea por turno y deja hablar.
- Nada de listas, nada de leer parrafos, numeros y precios en palabras.
- Si preguntan si eres una persona o un robot: eres una IA, justo lo que les ofrecemos.

LO QUE TIENES QUE CONSEGUIR, EN ORDEN
1. Ya te has presentado. Si no es {{negocio}}, discúlpate y despidete.
2. En cuanto confirmen, primero el gancho y al final el aviso corto, en UN solo turno y casi tal cual: "Te llamo porque soy justo lo que os ofrecemos: una recepcionista que os coge el telefono cuando estais con las manos ocupadas. ¿Te lo enseño en un minuto? Es comercial, y si no quieres mas llamadas, me lo dices." No expliques nada mas antes de que conteste. (Decir que es comercial y que puede no querer mas llamadas es obligatorio al empezar: no lo quites, solo dilo asi de corto.)
3. Si no es buen momento: pregunta cuando llamar y con quien, usa `volver_a_llamar` y despidete.
4. Si dice que si: la demostracion, con los papeles claros. EL O ELLA hace de clienta que llama a su negocio y TU de su recepcionista: "Haz como si fueras una clienta llamando a tu negocio y pideme cita". TU NUNCA haces de clienta. Atiendele como su recepcionista con huecos verosimiles y, al terminar, di claramente que era una simulacion y que con Vantelia lo harias con su agenda real.
5. Cierra: ofrece mandarle un correo con un enlace para probarlo con su propio negocio. Pide el email y DELETREALO de vuelta para confirmarlo. Con el confirmado, usa `apuntar_interes`.
6. Despidete y usa `end_call`.

SALIDAS
- "No me interesa": agradece, no insistas, despidete.
- "No me llameis mas" o enfado: pide disculpas, usa `no_volver_a_llamar` y despidete.
- Si esta el equipo pero no quien decide: pregunta cuando le pillas o deja el correo para esa persona.
- Maximo cuatro minutos: si se alarga, propon seguir por correo.

DATOS DE VANTELIA (no inventes nada fuera de esto; si no lo sabes, lo confirma Pablo, el fundador)
- Planes: Free (0 euros), Starter (49 euros al mes), Pro (129 euros al mes, con WhatsApp), Business (299 euros al mes, con recepcionista de voz por telefono como tu). Diez dias de prueba.
- Se instala sin cambiar de numero ni de WhatsApp: siguen usando su app.
- Web: vantelia punto es.
"""

_HERRAMIENTAS = {
    "apuntar_interes": (
        "Apunta que el negocio quiere recibir el correo para probar Vantelia. Solo con el email "
        "YA deletreado y confirmado.",
        {"type": "object", "description": "Datos del interesado", "properties": {
            "email": {"type": "string", "description": "Email confirmado, en minusculas"},
            "nombre": {"type": "string", "description": "Nombre de quien atiende, si lo ha dicho"},
            "notas": {"type": "string", "description": "Lo importante de la conversacion en una frase"}},
         "required": ["email"]}),
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


def puede_llamarse(telefono: str) -> bool:
    with _db() as conn:
        return conn.execute("SELECT 1 FROM no_llamar WHERE telefono=?", (telefono,)).fetchone() is None


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
                    "negocio": "tu negocio", "sector": "un negocio con citas", VARIABLE_LLAMADA: ""}},
                "prompt": {"prompt": GUION, "llm": voz_elevenlabs.LLM_POR_DEFECTO, "temperature": 0.5,
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
    twiml = voz_elevenlabs.twiml_registrar_llamada(
        agente, desde, hacia, "outbound",
        {"negocio": fila["negocio"] or "tu negocio", "sector": fila["sector"] or "un negocio con citas",
         VARIABLE_LLAMADA: llamada_id}, cliente=cliente)
    _actualizar(llamada_id, estado="en_curso")
    return twiml


def herramienta(nombre: str, cuerpo: Dict[str, Any]) -> Dict[str, Any]:
    """Lo que hace cada tool de la agente de captacion."""
    llamada_id = str(cuerpo.get(CAMPO_LLAMADA) or "")
    fila = _fila(llamada_id) if llamada_id else None
    if fila is None:
        return {"ok": False, "error": "No encuentro esta llamada. Despidete con amabilidad."}
    if nombre == "apuntar_interes":
        email = str(cuerpo.get("email") or "").strip().lower().replace(" ", "")
        if not _EMAIL.match(email):
            return {"ok": False, "error": "Ese email no parece completo. Pideselo otra vez y deletrealo."}
        notas = textnorm._sanitize_text(str(cuerpo.get("notas") or ""), allow_multiline=True)[:500]
        nombre_contacto = textnorm._sanitize_text(str(cuerpo.get("nombre") or ""))[:80]
        _actualizar(llamada_id, resultado="interesado", email=email,
                    notas=("%s. %s" % (nombre_contacto, notas)).strip(". "))
        _avisar_interes(fila, email, nombre_contacto, notas)
        return {"ok": True, "mensaje": "Apuntado. Dile que le llega hoy mismo y despidete."}
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


def _avisar_interes(fila, email: str, nombre: str, notas: str) -> None:
    from backend import outreach

    negocio = fila["negocio"] or fila["telefono"]
    asunto = "📞 Interesado por telefono: %s" % negocio
    texto = ("Sara ha hablado con un negocio interesado:\n\nNegocio:  %s\nTelefono: %s\nEmail:    %s\n"
             "Contacto: %s\nNotas:    %s\n\nMandale el enlace de la demo hoy mismo.\n"
             % (negocio, fila["telefono"], email, nombre or "-", notas or "-"))
    html = ("<div style='font-family:sans-serif'><h2 style='color:#00b1d9'>📞 %s</h2>"
            "<p>Telefono: %s<br>Email: <a href='mailto:%s'>%s</a><br>Contacto: %s</p>"
            "<p>%s</p><p>Mandale el enlace de la demo hoy mismo.</p></div>"
            % (escape(negocio), escape(fila["telefono"]), escape(email), escape(email),
               escape(nombre or "-"), escape(notas or "-")))
    try:
        outreach._outreach_notify_admin(asunto, texto, html)
    except Exception:  # noqa: BLE001 - el aviso nunca tumba la llamada
        settings.logger.exception("[captacion_voz] no se pudo avisar del interesado %s", email)
