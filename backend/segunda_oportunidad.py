"""La segunda oportunidad: un correo a quien no dijo que no en la llamada de Sara.

POR QUE EXISTE
--------------
Idea de Pablo (25-sep-2026, docs/PLAN_SEGUNDA_OPORTUNIDAD_LLAMADAS.md): muchas llamadas
se pierden por el momento, no por el producto. El negocio que colgo a los pocos segundos
o estaba con una clienta recibe UN correo, escrito para su sector y con su propia demo.
A quien dijo que no, nunca.

QUIEN LO RECIBE (lo decide el codigo, no el prompt)
---------------------------------------------------
- Manda su ULTIMA llamada con desenlace conocido, y tiene que ser `colgo_al_principio`
  u `ocupado_sin_rechazo`. Lo que apuntaron las herramientas de Sara (interesado, volver
  a llamar, no llamar) manda sobre la clasificacion de ElevenLabs. Si en CUALQUIER
  llamada dijo que no o ya se intereso, no hay correo.
- Tiene email; no esta de baja, ni ha respondido, ni es cliente, ni esta descartado, ni
  reboto; no le ha llegado ningun correo nuestro en DIAS_SIN_OTRO_CORREO dias; y como
  mucho UNA segunda oportunidad por negocio, para siempre.
- Si queda pendiente la rellamada dirigida a quien decide, se espera a que se haga.
- La llamada es de los ultimos DIAS_HACIA_ATRAS dias: encender el interruptor no escribe
  a todo el historico.

CUANDO
------
Llamada por la manana -> esa misma tarde, desde las 16:30. Por la tarde -> el siguiente
dia laborable a las 10:30. Nunca en fin de semana ni fuera de 9 a 19 h (hora de Madrid).

Apagado de serie: interruptor propio en el panel "Llamadas" (`llamadas_config`).
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, time, timedelta
from html import escape
from typing import Any, Callable, Dict, List, Optional

from backend import captacion_voz, lanzador_llamadas, settings, textnorm, timeutils, transcripciones_llamadas

ETAPA = "llamada"  # la etapa en `sends`: la ve el resto de la captacion por email
DESENLACES = ("interesado", "volver_a_llamar", "rechazo", "ocupado_sin_rechazo", "colgo_al_principio",
              "buzon", "persona_equivocada")
DESENLACES_CON_CORREO = ("colgo_al_principio", "ocupado_sin_rechazo")
# Si alguna llamada al negocio acabo asi, no se le escribe nunca.
DESENLACES_QUE_CIERRAN = ("rechazo", "interesado", "volver_a_llamar", "persona_equivocada")
DIAS_SIN_OTRO_CORREO = 3
DIAS_HACIA_ATRAS = 3
MAX_POR_RONDA = 10
MINUTOS_ENTRE_RONDAS = 30
HORA_TARDE = time(16, 30)
HORA_MANANA = time(10, 30)
VENTANA = (time(9, 0), time(19, 0))
_DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)

parar = threading.Event()
hilo: Optional[threading.Thread] = None
_cerrojo = threading.Lock()


def _db():
    conn = transcripciones_llamadas._db()  # llamadas_voz + llamadas_transcripcion
    conn.execute("""CREATE TABLE IF NOT EXISTS segunda_oportunidad (
        prospecto TEXT PRIMARY KEY, llamada_id TEXT NOT NULL, estado TEXT NOT NULL,
        detalle TEXT NOT NULL DEFAULT '', momento TEXT NOT NULL)""")
    conn.row_factory = sqlite3.Row
    return conn


def _iso(momento: datetime) -> str:
    return lanzador_llamadas._iso(momento)


def activa() -> bool:
    return bool(lanzador_llamadas.config().get("segunda_oportunidad"))


def desenlace_de(fila, analisis_json: str) -> str:
    """Como acabo la llamada. Lo que apunto Sara con sus herramientas manda."""
    resultado = str(fila["resultado"] or "")
    if resultado == "no_llamar":
        return "rechazo"
    if resultado in ("interesado", "volver_a_llamar"):
        return resultado
    try:
        datos = (json.loads(analisis_json or "{}") or {}).get("data_collection_results") or {}
    except (ValueError, AttributeError):
        datos = {}
    valor = datos.get("desenlace") if isinstance(datos, dict) else None
    if isinstance(valor, dict):
        valor = valor.get("value")
    valor = str(valor or "").strip().lower()
    return valor if valor in DESENLACES else ""


def cuando_toca(creada: datetime) -> datetime:
    """El momento a partir del cual sale el correo de una llamada."""
    local = creada.astimezone(lanzador_llamadas.ZONA)
    if local.time() < time(13, 0):
        objetivo = datetime.combine(local.date(), HORA_TARDE, tzinfo=lanzador_llamadas.ZONA)
    else:
        objetivo = datetime.combine(local.date() + timedelta(days=1), HORA_MANANA, tzinfo=lanzador_llamadas.ZONA)
    while objetivo.weekday() >= 5:
        objetivo = datetime.combine(objetivo.date() + timedelta(days=1), HORA_MANANA,
                                    tzinfo=lanzador_llamadas.ZONA)
    return objetivo


def en_ventana(ahora: datetime) -> bool:
    local = ahora.astimezone(lanzador_llamadas.ZONA)
    return local.weekday() < 5 and VENTANA[0] <= local.time() < VENTANA[1]


def _rellamada_pendiente(fila, llamadas_del_negocio: List[Any]) -> bool:
    """Cogio alguien del equipo, dio el nombre de quien decide y se le va a volver a llamar
    (lanzador_llamadas.rellamadas_dirigidas): el correo espera a esa llamada."""
    if fila["origen"] != "auto" or fila["interlocutor"] != "empleado" or not fila["responsable_nombre"]:
        return False
    if fila["rellamada_de"] or not lanzador_llamadas.es_fijo(fila["telefono"]):
        return False
    if any(otra["rellamada_de"] == fila["id"] for otra in llamadas_del_negocio):
        return False
    return bool(lanzador_llamadas.cuando_esta(fila["responsable_cuando"])["entendido"])


def motivo_para_no_escribir(conn, email: str, ahora: datetime, *, reserva_propia: str = "") -> str:
    """Vacio si se le puede escribir. Mismas reglas que la captacion por email.

    `reserva_propia` es la llamada que YA reservo esta ronda: su propia fila no cuenta como
    "ya tuvo su correo" (si contaba, tapaba el resto de comprobaciones y se mandaba igual
    encima de un correo recien salido; revision de Astra, 27-sep-2026)."""
    from backend import outreach

    email = str(email or "").strip().lower()
    if not _EMAIL.match(email):
        return "email_no_valido"
    prospecto = conn.execute("SELECT status FROM prospects WHERE email=?", (email,)).fetchone()
    if prospecto is None:
        return "no_esta_en_captacion"
    if conn.execute("SELECT 1 FROM suppressions WHERE email=?", (email,)).fetchone():
        return "de_baja"
    if conn.execute("SELECT 1 FROM events WHERE email=? AND type='reply' LIMIT 1", (email,)).fetchone():
        return "respondio"
    estado = str(prospecto["status"] or "").strip().lower()
    if estado in outreach.OUTREACH_TERMINAL_STATUSES:
        return "estado_" + estado
    reservada = conn.execute("SELECT llamada_id FROM segunda_oportunidad WHERE prospecto=?", (email,)).fetchone()
    if (reservada and not (reserva_propia and reservada[0] == reserva_propia)) or conn.execute(
            "SELECT 1 FROM sends WHERE email=? AND stage=? AND mode='send' LIMIT 1", (email, ETAPA)).fetchone():
        return "ya_tuvo_su_correo"
    reciente = _iso(ahora - timedelta(days=DIAS_SIN_OTRO_CORREO))
    if conn.execute("SELECT 1 FROM sends WHERE email=? AND mode='send' AND sent_at >= ? LIMIT 1",
                    (email, reciente)).fetchone():
        return "correo_reciente"
    return ""


def elegibles(ahora: datetime, *, contar_horario: bool = True, solo: str = "",
              reserva_propia: str = "") -> List[Dict[str, Any]]:
    """Los negocios a los que toca escribir ahora (sin mirar el interruptor). Con `solo`, se
    evalua un negocio entero otra vez (llamadas y email) justo antes de mandarle el correo."""
    desde = _iso(ahora - timedelta(days=DIAS_HACIA_ATRAS))
    with _db() as conn:
        filas = conn.execute(
            "SELECT l.*, COALESCE(t.analisis_json, '') AS analisis_json FROM llamadas_voz l "
            "LEFT JOIN llamadas_transcripcion t ON t.llamada_id = l.id "
            "WHERE l.prospecto <> '' AND (? = '' OR lower(trim(l.prospecto)) = ?) ORDER BY l.creada DESC",
            (solo, solo)).fetchall()
        no_llamar = {f["telefono"] for f in conn.execute("SELECT telefono FROM no_llamar")}
        por_negocio: Dict[str, List[Any]] = {}
        for fila in filas:
            por_negocio.setdefault(str(fila["prospecto"]).strip().lower(), []).append(fila)
        salida: List[Dict[str, Any]] = []
        for email, llamadas in por_negocio.items():
            desenlaces = [(fila, desenlace_de(fila, fila["analisis_json"])) for fila in llamadas]
            if any(d in DESENLACES_QUE_CIERRAN for _, d in desenlaces):
                continue
            if any(fila["telefono"] in no_llamar for fila in llamadas):
                continue
            decisiva = next(((fila, d) for fila, d in desenlaces if d), None)  # la mas reciente
            if decisiva is None or decisiva[1] not in DESENLACES_CON_CORREO or decisiva[0]["creada"] < desde:
                continue
            fila = decisiva[0]
            if _rellamada_pendiente(fila, llamadas):
                continue
            if contar_horario and ahora < cuando_toca(datetime.fromisoformat(fila["creada"])):
                continue
            if motivo_para_no_escribir(conn, email, ahora, reserva_propia=reserva_propia):
                continue
            salida.append({"llamada_id": fila["id"], "prospecto": email, "negocio": fila["negocio"] or "",
                           "sector": fila["sector"] or "", "creada": fila["creada"],
                           "responsable": fila["responsable_nombre"] or "", "desenlace": decisiva[1]})
    return salida


def _cuando_fue(creada: datetime, ahora: datetime) -> str:
    """"esta mañana", "ayer", "el viernes"... para que el correo cuadre con el dia."""
    llamada = creada.astimezone(lanzador_llamadas.ZONA)
    dias = (ahora.astimezone(lanzador_llamadas.ZONA).date() - llamada.date()).days
    if dias <= 0:
        return "esta mañana" if llamada.hour < 14 else "hace un rato"
    if dias == 1:
        return "ayer"
    return "el " + _DIAS_SEMANA[llamada.weekday()]


# Llamadas de ejemplo publicadas en la web (aprobadas por Pablo el 26-sep-2026). El orden
# importa: "barberia" antes que "peluqueria"; una clinica sin mas (veterinaria...) no tiene audio.
AUDIOS_WEB = "https://www.vantelia.es/assets/audio/%s.mp3"
_AUDIO_POR_SECTOR = (
    (("barber",), "barberia", "una barbería"),
    (("peluquer", "hairdress"), "peluqueria", "una peluquería"),
    (("fisio", "osteopat", "quiropract"), "fisioterapia", "un centro de fisioterapia"),
    (("dental", "dentist", "odontolog"), "clinica_dental", "una clínica dental"),
    (("estetic", "belleza", "beauty", "depilac", "masaj", " spa", " unas", "nail"), "estetica",
     "un centro de estética"),
)


def audio_de_su_sector(sector: str) -> Optional[Dict[str, str]]:
    """La llamada de ejemplo de su sector, o None si no hay una que le encaje."""
    texto = " " + textnorm._strip_accents(str(sector or "").lower())
    for claves, archivo, donde in _AUDIO_POR_SECTOR:
        if any(clave in texto for clave in claves):
            return {"url": AUDIOS_WEB % archivo, "donde": donde}
    return None


def correo(negocio: str, sector: str, enlace: str, cuando: str, responsable: str = "") -> Dict[str, str]:
    """El correo, en nombre de Pablo. No pregunta "que te parecio": muchos no llegaron a
    oir la demo. Promete lo que se cumple: no se les vuelve a escribir."""
    import outreach_templates  # type: ignore  # scripts/ en el path (lo deja backend.outreach)

    frases = outreach_templates.sector_copy(sector)
    negocio = negocio or "vuestro negocio"
    saludo = "Hola, %s:" % responsable if responsable else "Hola:"
    parrafos = [
        saludo,
        "%s os llamó Sara, nuestra asistente con inteligencia artificial, y os pillamos en mal momento. "
        "Es lo que pasa en %s: %s." % (cuando[:1].upper() + cuando[1:], frases["sector"], frases["escena"]),
        "Para eso está Sara: coge el teléfono y el WhatsApp de %s cuando estáis %s, da citas, las "
        "cambia y las cancela." % (negocio, frases["atendiendo"]),
    ]
    audio = audio_de_su_sector(sector)
    escucha = ("Así atiende una llamada en %s (menos de un minuto):" % audio["donde"]) if audio else ""
    prueba = ("Y aquí" if audio else "Aquí") + " la puedes probar con vuestro propio negocio:"
    cierre = [
        "Si te encaja, respóndeme a este correo y lo vemos. Y si no, tranquilo: no te volvemos a escribir.",
        "Un saludo,\nPablo Sánchez · Vantelia",
    ]
    texto = "\n\n".join(parrafos + ([escucha, audio["url"]] if audio else []) + [prueba, enlace] + cierre) + "\n"
    html = (
        "<div style='font-family:sans-serif;max-width:560px;color:#1a1a2e;line-height:1.55'>"
        + "".join("<p>%s</p>" % escape(p) for p in parrafos)
        + ("<p>%s <a href='%s'>escuchar la llamada</a></p>" % (escape(escucha), escape(audio["url"], quote=True))
           if audio else "")
        + "<p>%s</p>" % escape(prueba)
        + "<p><a href='%s' style='display:inline-block;padding:11px 20px;border-radius:999px;"
          "background:#00D1FF;color:#04101C;font-weight:700;text-decoration:none'>Probar con %s</a></p>"
        % (escape(enlace, quote=True), escape(negocio))
        + "".join("<p>%s</p>" % escape(p).replace("\n", "<br>") for p in cierre)
        + "</div>")
    asunto = "Lo de la llamada " + ("del " + cuando[3:] if cuando.startswith("el ") else "de " + cuando)
    return {"asunto": asunto, "texto": texto, "html": html}


def _mandar(candidato: Dict[str, Any], ahora: datetime) -> str:
    """Manda el correo y lo apunta en `sends`. Devuelve el Message-ID."""
    from backend import outreach
    import outreach_templates  # type: ignore

    email = candidato["prospecto"]
    try:
        outreach._outreach_maybe_pregenerate_demo(email)  # su demo, lista cuando la abra
    except Exception:  # noqa: BLE001 - sin demo lista, el enlace la genera al pinchar
        settings.logger.warning("[segunda_oportunidad] no se pudo adelantar la demo de %s", email)
    contenido = correo(candidato["negocio"], candidato["sector"], captacion_voz.enlace_de_demo(email),
                       _cuando_fue(datetime.fromisoformat(candidato["creada"]), ahora), candidato["responsable"])
    ajustes = outreach.outreach_smtp_settings()
    baja = str(ajustes.get("unsubscribe_mailto") or "baja@vantelia.es")
    texto = contenido["texto"] + outreach_templates.footer_text(baja)
    html = contenido["html"] + outreach_templates.footer_html(baja)
    if (not outreach.OUTREACH_TRACKING_DISABLED and outreach.OUTREACH_TRACKING_SECRET
            and outreach.OUTREACH_TRACKING_BASE_URL):
        html = outreach.outreach_apply_tracking(html, email, ETAPA, outreach.OUTREACH_TRACKING_BASE_URL,
                                                outreach.OUTREACH_TRACKING_SECRET)
    mensaje = outreach.outreach_build_message(email, contenido["asunto"], texto, html, ajustes)
    outreach._outreach_send_email_object(mensaje)
    with _db() as conn:
        conn.execute("INSERT INTO sends (email, stage, subject, body_text, body_html, sent_at, mode, message_id) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (email, ETAPA, contenido["asunto"], texto, html, _iso(ahora), "send",
                      mensaje["Message-ID"] or ""))
        conn.execute("UPDATE prospects SET status=CASE WHEN COALESCE(status,'new') IN ('','new') "
                     "THEN 'contacted' ELSE status END, updated_at=? WHERE email=?", (_iso(ahora), email))
        conn.commit()
    return str(mensaje["Message-ID"] or "")


def _reservar(candidato: Dict[str, Any], ahora: datetime) -> bool:
    """Una segunda oportunidad por negocio, PARA SIEMPRE: se apunta antes de mandar, y la
    ronda que llegue a la vez la ve y se la salta."""
    with _db() as conn:
        apuntada = conn.execute(
            "INSERT OR IGNORE INTO segunda_oportunidad (prospecto, llamada_id, estado, momento) VALUES (?,?,?,?)",
            (candidato["prospecto"], candidato["llamada_id"], "enviando", _iso(ahora)))
        conn.commit()
        return apuntada.rowcount == 1


def _apuntar(prospecto: str, estado: str, detalle: str = "", *, borrar: bool = False) -> None:
    with _db() as conn:
        if borrar:
            conn.execute("DELETE FROM segunda_oportunidad WHERE prospecto=? AND estado='enviando'", (prospecto,))
        else:
            conn.execute("UPDATE segunda_oportunidad SET estado=?, detalle=? WHERE prospecto=?",
                         (estado, detalle[:300], prospecto))
        conn.commit()


def _sigue_en_pie(candidato: Dict[str, Any], momento: datetime) -> bool:
    """Interruptor, horario y el negocio ENTERO otra vez con la hora de ESE momento: sus
    llamadas (un "rechazo" clasificado mientras se esperaba el turno cierra la puerta; revision
    de Astra, 27-sep-2026), "no llamar", la rellamada pendiente y las reglas del email."""
    if parar.is_set() or not activa() or not en_ventana(momento):
        return False
    return any(c["llamada_id"] == candidato["llamada_id"]
               for c in elegibles(momento, solo=candidato["prospecto"], reserva_propia=candidato["llamada_id"]))


def ronda(*, ahora: Optional[datetime] = None, mandar: Callable[[Dict[str, Any], datetime], str] = None,
          esperar_turno: Callable[[], Any] = None, reloj: Callable[[], datetime] = None) -> Dict[str, Any]:
    """Manda las segundas oportunidades que tocan. Solo con el interruptor encendido y en
    horario; una a una, respetando el espaciado de todos los correos de captacion.
    `reloj` da la hora tras esperar el turno (en pruebas, la fija de `ahora`)."""
    if reloj is None:
        reloj = (lambda: ahora) if ahora is not None else timeutils._utc_now
    ahora = ahora or timeutils._utc_now()
    if not activa():
        return {"enviadas": 0, "motivo": "apagada"}
    if not en_ventana(ahora):
        return {"enviadas": 0, "motivo": "fuera_de_horario"}
    from backend import outreach

    mandar = mandar or _mandar
    esperar_turno = esperar_turno or outreach._outreach_wait_send_slot
    enviadas, fallidas = 0, 0
    with _cerrojo:
        for candidato in elegibles(ahora)[:MAX_POR_RONDA]:
            if parar.is_set() or not activa():
                break
            if not _reservar(candidato, ahora):
                continue
            # Entre elegirla y mandarla pudo llegar una baja, una respuesta u otro correo; y
            # esperar el turno de envio puede tardar minutos: se mira antes Y despues, con la
            # hora de ese momento (revision de Astra, 27-sep-2026).
            if not _sigue_en_pie(candidato, ahora):
                _apuntar(candidato["prospecto"], "", borrar=True)
                continue
            esperar_turno()
            momento = reloj()
            if not _sigue_en_pie(candidato, momento):
                _apuntar(candidato["prospecto"], "", borrar=True)
                continue
            try:
                message_id = mandar(candidato, momento)
            except Exception as exc:  # noqa: BLE001 - se reintenta en la siguiente ronda
                fallidas += 1
                settings.logger.warning("[segunda_oportunidad] no se pudo mandar a %s: %s",
                                        candidato["prospecto"], textnorm._sanitize_text(str(exc))[:200])
                _apuntar(candidato["prospecto"], "", borrar=True)
                continue
            enviadas += 1
            _apuntar(candidato["prospecto"], "enviada", message_id)
    return {"enviadas": enviadas, "fallidas": fallidas}


def por_llamada(ids: List[str]) -> Dict[str, Dict[str, str]]:
    """Para el panel: desenlace de cada llamada y si su negocio tuvo segunda oportunidad."""
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    with _db() as conn:
        filas = conn.execute(
            "SELECT l.id, l.resultado, l.prospecto, COALESCE(t.analisis_json, '') AS analisis_json, "
            "COALESCE(s.estado, '') AS segunda, COALESCE(s.llamada_id, '') AS segunda_de FROM llamadas_voz l "
            "LEFT JOIN llamadas_transcripcion t ON t.llamada_id = l.id "
            "LEFT JOIN segunda_oportunidad s ON s.prospecto = lower(l.prospecto) "
            "WHERE l.id IN (%s)" % marcas, tuple(ids)).fetchall()
    return {f["id"]: {"desenlace": desenlace_de(f, f["analisis_json"]),
                      "segunda_oportunidad": f["segunda"] if f["segunda_de"] == f["id"] else ""}
            for f in filas}


def _trabajador() -> None:
    settings.logger.info("[segunda_oportunidad] iniciada: una ronda cada %s min.", MINUTOS_ENTRE_RONDAS)
    parar.wait(180)
    while not parar.is_set():
        try:
            ronda()
        except Exception:  # noqa: BLE001
            settings.logger.exception("[segunda_oportunidad] error en la ronda")
        parar.wait(MINUTOS_ENTRE_RONDAS * 60)


def arrancar() -> Optional[threading.Thread]:
    """Arranca el hilo si Sara existe (ElevenLabs configurado). El interruptor del panel
    decide despues si se manda algo. Idempotente."""
    global hilo
    from backend import voz_elevenlabs

    if not voz_elevenlabs.configurado():
        return None
    if hilo and hilo.is_alive():
        return hilo
    parar.clear()
    hilo = threading.Thread(target=_trabajador, name="vantelia-segunda-oportunidad", daemon=True)
    hilo.start()
    return hilo
