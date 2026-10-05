"""El seguimiento tras la demo: del "te la mando" al lead cualificado.

POR QUE EXISTE
--------------
Pablo (5-oct-2026): "quiero los leads ya cualificados para ponerme a trabajar con ellos; a
partir de ahi ya me encargo yo. Prefiero email". Mandabamos la demo y esperabamos: nadie
volvia a escribir a quien la habia pedido, y las senales de interes se quedaban en la base
sin que nadie las viera (el mismo 5-oct, Noelia Brown pulso "Activar gratis" en su demo y no
termino el alta). Diseno y razones: docs/SISTEMA_CAPTACION_FINAL.md.

QUE HACE
--------
1. Inscribe a quien recibe su demo: Sara (`inscribir_tras_la_llamada`), el formulario de la
   web (`inscribir_demo_web`) o un prospecto del correo que la USA (`inscribir_a_quien_la_usa`).
2. Le escribe Pablo 2-3 veces (correo, o SMS a un movil sin correo), en el hilo que ya
   tenia y pidiendo una respuesta (`ronda`). Apagado de serie: interruptor del panel.
3. Le cualifica cuando dice que si (`cualificar`): el formulario de /interes, una respuesta
   positiva (`al_responder`, la clasifica la IA), un boton de su demo o Sara ("que me llame
   Pablo"). Los avisos de leads no dependen del interruptor: solo escriben a Pablo.
4. Avisa a Pablo en el momento con la ficha (`ficha`), crea la oportunidad del Plan de escala
   y le recuerda UNA vez si a las 24 h sigue sin tocar (`recordar`).

REGLAS (las pone el codigo, no el azar)
---------------------------------------
- Nunca a quien esta de baja, reboto, respondio, es cliente, se descarto o pidio no mas
  llamadas: se mira al inscribir, al elegir y otra vez justo antes de enviar.
- Un toque se reserva antes de enviarlo (tabla `seguimiento_demo_toques`, una fila por paso):
  si el envio queda en duda NO se repite. Mejor un toque de menos que dos.
- Abrir un enlace no cualifica a nadie: los antivirus de correo abren los enlaces. Cuentan
  enviar el formulario (POST), contestar, o una senal que da el JavaScript firmado de la demo.
- Mientras alguien esta en seguimiento, el correo frio no le escribe (`outreach` y
  `scripts/outreach_campaign.py`) y Sara no le llama (`lanzador_llamadas.candidatos`).

Las tablas viven en la base de captacion y se crean con su esquema (`SCHEMA` de
scripts/outreach_campaign.py): asi las consultas del correo frio siempre las encuentran.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote

from backend import captacion_voz, lanzador_llamadas, settings, textnorm, timeutils

ZONA = lanzador_llamadas.ZONA
VENTANA = (time(9, 0), time(19, 0))
VENTANA_SMS = (time(10, 0), time(19, 0))
HORA_DEL_TOQUE = time(10, 30)
HORAS_TRAS_USARLA = 3  # "¿que te ha parecido?" no mientras la esta probando
DIAS_DE_USO = 14       # quien uso su demo hace mas ya no recibe "¿que te ha parecido?"
DIAS_DE_INTERES = 30   # un boton de su demo pulsado hace mas no se avisa
DIAS_PARA_EMPEZAR = 14  # inscrito sin primer toque (interruptor apagado): ya no se empieza
DIAS_DE_RETRASO_MAXIMO = 7  # un toque que se retrasa mas (apagado a mitad): se cierra
MAX_CORREOS_AL_DIA = 20
MAX_SMS_AL_DIA = 10
MAX_POR_RONDA = 10
MINUTOS_ENTRE_RONDAS = 10
HORAS_PARA_RECORDAR = 24
# La misma promesa que hace Sara (DATOS DE VANTELIA): cambiarla aqui si cambia la oferta.
OFERTA_PRUEBA = "diez días de prueba gratis"
ETAPA = "seguimiento_%d"           # en `sends`: el correo frio y el lector IMAP los ven
# Festivos nacionales fijos: un correo de "¿pudisteis verla?" el 12 de octubre no lo lee nadie.
FESTIVOS = {(1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)}
MOTIVO_BAJA = "no_le_interesa_la_demo"  # la baja que pone el "ahora no" (y quita un "si" posterior)

ORIGENES = ("llamada", "web", "correo", "demo")
ORIGEN_TEXTO = {"llamada": "Sara le mandó la demo en una llamada", "web": "generó su demo en la web",
                "correo": "usó la demo de un correo frío", "demo": "pulsó «Me interesa» en su demo"}
_PESO_ORIGEN = {"correo": 1, "demo": 2, "web": 3, "llamada": 3}
ESTADOS = ("activo", "cualificado", "descartado", "respondio", "parado", "terminado", "caducado")
# Estados del prospecto en los que no se le escribe ni se le inscribe.
ESTADOS_PROSPECTO_FUERA = ("replied", "client", "lost", "bounced", "baja")
CADENCIA = {
    "llamada": ((1, "primero"), (3, "valor"), (5, "cierre")),
    "web": ((1, "primero"), (3, "valor"), (5, "cierre")),
    "correo": ((0, "que_tal"), (4, "cierre")),
    "demo": ((0, "que_tal"), (4, "cierre")),
}
CADENCIA_SMS = ((1, "primero"), (8, "cierre"))
# Senales de una PERSONA usando su demo (las da el JavaScript firmado de la pagina o el
# servidor). Un clic al enlace no: los antivirus de correo los abren.
SENALES_DE_USO = ("demo_chat_opened", "demo_interacted", "demo_voice")
SENALES_DE_INTERES = {
    "claim_intent": "pulsó «Activar gratis e instalar» en su demo",
    "contact_intent": "pulsó «Tengo una duda» en su demo",
    "whatsapp_intent": "pulsó «Prefiero seguir por WhatsApp» en su demo",
}
POR_TEXTO = {
    "formulario": "rellenó «Me interesa» en el enlace del seguimiento",
    "respuesta": "contestó al correo con interés",
    "llamada_pablo": "le pidió a Sara que le llames",
    "pablo": "lo marcaste tú en el panel",
}
COMO = {"telefono": "por teléfono", "video": "por videollamada", "email": "por correo"}
# Lo que lee Pablo en el panel y lo que elige el negocio en la pagina "ahora no".
MOTIVOS_NO = {"ya_tenemos": "ya tienen algo parecido", "no_es_momento": "no es buen momento",
              "no_lo_necesitamos": "no lo necesitan", "precio": "el precio", "otro": "otro motivo"}
OPCIONES_NO = {"ya_tenemos": "Ya tenemos algo parecido", "no_es_momento": "No es buen momento",
               "no_lo_necesitamos": "No lo necesitamos", "precio": "Por el precio", "otro": "Otro motivo"}
_EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$", re.IGNORECASE)
_DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

parar = threading.Event()
hilo: Optional[threading.Thread] = None
_cerrojo = threading.Lock()


class NoEnviado(Exception):
    """El toque seguro que NO salio: se puede reintentar. Cualquier otro error puede ser un
    toque que SI salio (y no se repite)."""


# --- Base y ajustes ---------------------------------------------------------------------

@contextmanager
def _conexion() -> Iterator[sqlite3.Connection]:
    # Por el camino de Sara: ademas del esquema de la captacion (con las tablas de este
    # modulo), asegura `llamadas_voz` y `no_llamar`, que crea ella.
    conn = captacion_voz._db()
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _iso(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).isoformat(timespec="seconds")


def _dt(valor: Any) -> Optional[datetime]:
    try:
        momento = datetime.fromisoformat(str(valor or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def _leer(conn, clave: str, defecto: str = "") -> str:
    fila = conn.execute("SELECT valor FROM seguimiento_demo_ajustes WHERE clave=?", (clave,)).fetchone()
    return str(fila[0]) if fila else defecto


def _guardar(conn, clave: str, valor: str) -> None:
    conn.execute("INSERT INTO seguimiento_demo_ajustes (clave, valor) VALUES (?,?) "
                 "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (clave, valor))


def esta_encendido() -> bool:
    """El interruptor del panel: si se le escribe a alguien. Apagado de serie."""
    with _conexion() as conn:
        return _leer(conn, "encendido", "0") == "1"


def guardar_config(*, encendido: Optional[bool] = None) -> Dict[str, Any]:
    if encendido is not None:
        with _conexion() as conn:
            _guardar(conn, "encendido", "1" if encendido else "0")
            conn.commit()
    return {"encendido": esta_encendido()}


def _fila(seg_id: str):
    with _conexion() as conn:
        return conn.execute("SELECT * FROM seguimiento_demo WHERE id=?", (seg_id,)).fetchone()


def _por_email(conn, email: str):
    email = str(email or "").strip().lower()
    if not email:
        return None
    return conn.execute("SELECT * FROM seguimiento_demo WHERE prospecto=? OR clave=? OR "
                        "(canal='email' AND destino=?) ORDER BY creado LIMIT 1",
                        (email, email, email)).fetchone()


# --- Cuando ----------------------------------------------------------------------------

def es_laborable(dia: date) -> bool:
    return dia.weekday() < 5 and (dia.month, dia.day) not in FESTIVOS


def _laborable(dia: date, dias: int) -> date:
    """El dia laborable `dias` despues de `dia` (0: el mismo si lo es, si no el siguiente)."""
    if dias <= 0:
        while not es_laborable(dia):
            dia += timedelta(days=1)
        return dia
    while dias > 0:
        dia += timedelta(days=1)
        if es_laborable(dia):
            dias -= 1
    return dia


def _a_su_hora(dia: date) -> datetime:
    return datetime.combine(dia, HORA_DEL_TOQUE, tzinfo=ZONA).astimezone(timezone.utc)


def en_ventana(momento: datetime, ventana: Tuple[time, time] = VENTANA) -> bool:
    local = momento.astimezone(ZONA)
    return es_laborable(local.date()) and ventana[0] <= local.time() < ventana[1]


def primer_hueco(momento: datetime) -> datetime:
    """El primer momento de la ventana de envio desde `momento` (antes de las 9: a las 10:30)."""
    local = momento.astimezone(ZONA)
    if es_laborable(local.date()) and local.time() < VENTANA[0]:
        return _a_su_hora(local.date())
    if en_ventana(momento):
        return momento.astimezone(timezone.utc)
    return _a_su_hora(_laborable(local.date(), 1))


def cuando_toca(desde: datetime, dias: int) -> datetime:
    """El toque `dias` laborables despues de `desde`, a las 10:30. Con 0, unas horas despues."""
    if dias <= 0:
        return primer_hueco(desde + timedelta(hours=HORAS_TRAS_USARLA))
    return _a_su_hora(_laborable(desde.astimezone(ZONA).date(), dias))


def pasos(origen: str, canal: str) -> Tuple[Tuple[int, str], ...]:
    return CADENCIA_SMS if canal == "sms" else CADENCIA.get(origen, CADENCIA["correo"])


def _cuando_fue(momento: datetime, ahora: datetime) -> str:
    """"esta mañana", "ayer", "el lunes": para que el correo cuadre con el dia."""
    local = momento.astimezone(ZONA)
    dias = (ahora.astimezone(ZONA).date() - local.date()).days
    if dias <= 0:
        return "esta mañana" if local.hour < 14 else "hace un rato"
    if dias == 1:
        return "ayer"
    if dias < 7:
        return "el " + _DIAS_SEMANA[local.weekday()]
    return "hace unos días"


# --- Enlaces firmados -------------------------------------------------------------------

def _secreto() -> str:
    from backend import outreach

    return os.getenv("OUTREACH_TRACKING_SECRET", "").strip() or str(outreach.OUTREACH_TRACKING_SECRET or "")


def _base_publica() -> str:
    return (os.getenv("OUTREACH_TRACKING_BASE_URL", "").strip() or settings.APP_BASE_URL
            or "https://app.vantelia.es").rstrip("/")


def token_de(seg_id: str) -> str:
    secreto = _secreto()
    if not (secreto and seg_id):
        return ""
    firma = hmac.new(secreto.encode("utf-8"), ("interes:v1:" + seg_id).encode("utf-8"), hashlib.sha256).digest()
    return "%s.%s" % (seg_id, base64.urlsafe_b64encode(firma[:12]).decode("ascii").rstrip("="))


def id_del_token(token: str) -> str:
    """El seguimiento de un enlace de /interes, o "" si la firma no vale."""
    seg_id, _, firma = str(token or "").partition(".")
    if not re.fullmatch(r"sd_[A-Za-z0-9_-]{6,24}", seg_id) or not firma:
        return ""
    esperado = token_de(seg_id).partition(".")[2]
    return seg_id if esperado and hmac.compare_digest(firma, esperado) else ""


def enlace_interes(seg_id: str, respuesta: str = "") -> str:
    token = token_de(seg_id)
    if not token:
        return ""
    return "%s/interes/%s%s" % (_base_publica(), token, ("?r=" + respuesta) if respuesta in ("si", "no") else "")


def enlace_demo(prospecto: str) -> str:
    """La demo del negocio por el enlace de siempre (/demo/go: la regenera si caduco y cuenta
    el clic), con la etapa del seguimiento. Sin negocio en la captacion, la web."""
    secreto = _secreto()
    if not (prospecto and secreto):
        return captacion_voz.WEB
    from backend import outreach  # deja scripts/ en el path

    if not outreach.OUTREACH_AVAILABLE:
        return captacion_voz.WEB
    import outreach_templates  # type: ignore

    return "%s/demo/go/%s" % (_base_publica(), outreach_templates.make_tracking_token(prospecto, "seguimiento", secreto))


# --- Inscribir --------------------------------------------------------------------------

def _no_se_le_escribe(conn, emails: List[str], telefono: str) -> str:
    """Motivo para no escribirle ("" si se puede): baja, rebote, ya respondio, cliente..."""
    for email in [e for e in emails if e]:
        if conn.execute("SELECT 1 FROM suppressions WHERE email=?", (email,)).fetchone():
            return "baja"
        fila = conn.execute("SELECT status FROM prospects WHERE email=?", (email,)).fetchone()
        estado = str((fila[0] if fila else "") or "").strip().lower()
        if estado in ESTADOS_PROSPECTO_FUERA:
            return "estado_" + estado
    if telefono and conn.execute("SELECT 1 FROM no_llamar WHERE telefono=?", (telefono,)).fetchone():
        return "no_llamar"
    return ""


def _nombre_de_pila(nombre: str) -> str:
    """"Gonzalo Navarro" -> "Gonzalo"; "Dra. Marta Ruiz" -> "Dra. Marta". Solo para saludar."""
    partes = textnorm._sanitize_text(str(nombre or "")).split()
    if not partes or partes[0].lower() in ("sara", "-", "n/a"):
        return ""
    if textnorm._strip_accents(partes[0]).lower().rstrip(".") in ("dr", "dra", "doctor", "doctora") and len(partes) > 1:
        return " ".join(partes[:2])[:40]
    return partes[0][:30]


def inscribir(*, origen: str, canal: str, destino: str, prospecto: str = "", negocio: str = "", sector: str = "",
              contacto: str = "", telefono: str = "", llamada_id: str = "", hilo: str = "", asunto_hilo: str = "",
              ahora: Optional[datetime] = None, primero_en: Optional[datetime] = None,
              aunque_no_se_le_escriba: bool = False) -> Optional[str]:
    """Apunta a un negocio para el seguimiento. Devuelve su id (o el que ya tenia), o None si
    no se le puede escribir. Una fila por negocio: lo que ya esta en marcha no se reinicia.

    `aunque_no_se_le_escriba`: para cualificar (un "me interesa" cuenta aunque el correo frio
    lo tuviera descartado); el toque igualmente no sale, lo para `_motivo_para_parar`."""
    if origen not in ORIGENES or canal not in ("email", "sms"):
        raise ValueError("origen o canal no validos")
    ahora = ahora or timeutils._utc_now()
    prospecto = str(prospecto or "").strip().lower()
    telefono = captacion_voz.telefono_e164(telefono) if telefono else ""
    if canal == "email":
        destino = str(destino or "").strip().lower()
        if not _EMAIL.match(destino):
            return None
    else:
        destino = captacion_voz.telefono_e164(destino)
        if not destino:
            return None
        telefono = telefono or destino
    clave = prospecto or ("tel:" + telefono if telefono else "mail:" + destino)
    proximo = _iso(primero_en or cuando_toca(ahora, pasos(origen, canal)[0][0]))
    datos = {"negocio": textnorm._sanitize_text(negocio)[:120], "sector": textnorm._sanitize_text(sector)[:80],
             "contacto": textnorm._sanitize_text(contacto)[:80], "telefono": telefono,
             "llamada_id": str(llamada_id or "")[:40], "hilo": str(hilo or "")[:300],
             "asunto_hilo": textnorm._sanitize_text(asunto_hilo)[:200]}
    with _conexion() as conn:
        if not aunque_no_se_le_escriba and _no_se_le_escribe(conn, [prospecto, destino if canal == "email" else ""],
                                                             telefono):
            return None
        conn.execute("BEGIN IMMEDIATE")
        fila = conn.execute("SELECT * FROM seguimiento_demo WHERE clave=?", (clave,)).fetchone()
        if fila is None:
            seg_id = "sd_" + secrets.token_urlsafe(8)
            conn.execute(
                "INSERT INTO seguimiento_demo (id, clave, prospecto, origen, canal, destino, negocio, sector, contacto, "
                "telefono, llamada_id, hilo, asunto_hilo, estado, paso, proximo, creado, actualizado) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'activo',0,?,?,?)",
                (seg_id, clave, prospecto, origen, canal, destino, datos["negocio"], datos["sector"], datos["contacto"],
                 telefono, datos["llamada_id"], datos["hilo"], datos["asunto_hilo"], proximo, _iso(ahora), _iso(ahora)))
        elif fila["estado"] == "caducado" or (fila["estado"] == "activo" and fila["paso"] == 0
                                               and _PESO_ORIGEN[origen] >= _PESO_ORIGEN.get(fila["origen"], 0)):
            # Aun no se le ha escrito nada: lo nuevo manda (una demo pedida por telefono pesa mas
            # que un uso suelto de la demo de un correo). Empieza de nuevo, tambien la fecha: con
            # la vieja, `caducar` lo volvia a cerrar al momento (revision de Astra a c00d68c).
            seg_id = fila["id"]
            conn.execute(
                "UPDATE seguimiento_demo SET origen=?, canal=?, destino=?, negocio=COALESCE(NULLIF(?, ''), negocio), "
                "sector=COALESCE(NULLIF(?, ''), sector), contacto=COALESCE(NULLIF(?, ''), contacto), "
                "telefono=COALESCE(NULLIF(?, ''), telefono), llamada_id=COALESCE(NULLIF(?, ''), llamada_id), "
                "hilo=?, asunto_hilo=?, estado='activo', motivo='', proximo=?, creado=?, actualizado=? WHERE id=?",
                (origen, canal, destino, datos["negocio"], datos["sector"], datos["contacto"], telefono,
                 datos["llamada_id"], datos["hilo"], datos["asunto_hilo"], proximo, _iso(ahora), _iso(ahora), seg_id))
        else:
            # En marcha o cerrado: solo se completa lo que faltaba.
            seg_id = fila["id"]
            conn.execute(
                "UPDATE seguimiento_demo SET contacto=CASE WHEN contacto='' THEN ? ELSE contacto END, "
                "telefono=CASE WHEN telefono='' THEN ? ELSE telefono END, "
                "llamada_id=CASE WHEN llamada_id='' THEN ? ELSE llamada_id END, actualizado=? WHERE id=?",
                (datos["contacto"], telefono, datos["llamada_id"], _iso(ahora), seg_id))
        conn.commit()
    return seg_id


def inscribir_tras_la_llamada(fila, *, canal: str, destino: str, contacto: str = "", mensaje_id: str = "",
                              asunto: str = "", ahora: Optional[datetime] = None) -> Optional[str]:
    """Sara acaba de mandar la demo (`captacion_voz._enviar_informacion`). Se saluda a quien
    decide si se sabe; si no, a quien cogio el telefono."""
    claves = fila.keys() if hasattr(fila, "keys") else []
    responsable = str(fila["responsable_nombre"] or "") if "responsable_nombre" in claves else ""
    return inscribir(origen="llamada", canal=canal, destino=destino, prospecto=str(fila["prospecto"] or ""),
                     negocio=captacion_voz.nombre_corto(fila["negocio"] or ""),
                     sector=lanzador_llamadas.sector_real(fila["negocio"] or "", fila["sector"] or ""),
                     contacto=responsable or contacto, telefono=fila["telefono"], llamada_id=fila["id"],
                     hilo=mensaje_id, asunto_hilo=asunto if mensaje_id else "", ahora=ahora)


def _asegurar_prospecto(conn, email: str, negocio: str, sector: str, web: str, ahora: datetime) -> None:
    """Quien genera su demo en la web entra en la base de captacion (como 'engaged'): asi sus
    senales en la demo se apuntan y el correo frio sabe que ya esta en seguimiento."""
    conn.execute("INSERT OR IGNORE INTO prospects (email, business_name, niche, website, source, tags, status, "
                 "created_at, updated_at) VALUES (?,?,?,?,'demo_web','demo_web','engaged',?,?)",
                 (email, textnorm._sanitize_text(negocio)[:160] or email, textnorm._sanitize_text(sector)[:80],
                  str(web or "")[:300], _iso(ahora), _iso(ahora)))


def inscribir_demo_web(email: str, negocio: str, sector: str = "", web: str = "",
                       ahora: Optional[datetime] = None) -> Optional[str]:
    """Alguien genero su demo en vantelia.es/demo (demo nueva, `POST /demo/generate`)."""
    ahora = ahora or timeutils._utc_now()
    email = str(email or "").strip().lower()
    if not _EMAIL.match(email):
        return None
    with _conexion() as conn:
        _asegurar_prospecto(conn, email, negocio, sector, web, ahora)
        conn.commit()
    return inscribir(origen="web", canal="email", destino=email, prospecto=email, negocio=negocio, sector=sector,
                     ahora=ahora)


def _hilo_del_ultimo_correo(conn, email: str) -> Tuple[str, str]:
    """(Message-ID, asunto) del ultimo correo nuestro a ese negocio: el seguimiento va en su hilo."""
    fila = conn.execute("SELECT message_id, subject FROM sends WHERE email=? AND mode='send' AND message_id<>'' "
                        "ORDER BY sent_at DESC, id DESC LIMIT 1", (email,)).fetchone()
    return (str(fila["message_id"]), str(fila["subject"] or "")) if fila else ("", "")


def datos_de_la_demo(cliente_id: str) -> Dict[str, Any]:
    """Lo que ensena el formulario del boton "Me interesa" de una demo, SIN escribir nada (abrir
    la pagina no cuenta: solo enviarla). {} si la demo no existe o no tiene correo."""
    from backend import clients

    try:
        config = clients._get_client_config(cliente_id)
    except Exception:  # noqa: BLE001 - demo caducada o inexistente
        return {}
    email = str(((config.get("contacto") or {}).get("email")) or "").strip().lower()
    if not _EMAIL.match(email):
        return {}
    with _conexion() as conn:
        prospecto = conn.execute("SELECT * FROM prospects WHERE email=?", (email,)).fetchone()
        fila = _por_email(conn, email)
    return {"negocio": str((prospecto["business_name"] if prospecto else "") or config.get("nombre") or "vuestro negocio"),
            "email": email, "nombre": (fila["contacto"] if fila is not None else "") or "",
            "telefono": captacion_voz.telefono_e164(str((prospecto["phone"] if prospecto else "") or "")),
            "estado": fila["estado"] if fila is not None else "", "enlace_demo": ""}


def seguimiento_para_demo(cliente_id: str, ahora: Optional[datetime] = None) -> str:
    """El seguimiento del dueño de una demo (boton "Me interesa" de la pagina). Lo crea si no
    tiene. "" si la demo no existe o no tiene correo."""
    from backend import clients

    try:
        config = clients._get_client_config(cliente_id)
    except Exception:  # noqa: BLE001 - demo caducada o inexistente
        return ""
    email = str(((config.get("contacto") or {}).get("email")) or "").strip().lower()
    if not _EMAIL.match(email):
        return ""
    ahora = ahora or timeutils._utc_now()
    with _conexion() as conn:
        fila = _por_email(conn, email)
        if fila is not None:
            return fila["id"]
        prospecto = conn.execute("SELECT * FROM prospects WHERE email=?", (email,)).fetchone()
        if prospecto is None:
            _asegurar_prospecto(conn, email, str(config.get("nombre") or ""), "", "", ahora)
            conn.commit()
            prospecto = conn.execute("SELECT * FROM prospects WHERE email=?", (email,)).fetchone()
        hilo, asunto = _hilo_del_ultimo_correo(conn, email)
    return inscribir(origen="demo", canal="email", destino=email, prospecto=email,
                     negocio=str(prospecto["business_name"] or config.get("nombre") or ""),
                     sector=str(prospecto["niche"] or ""), telefono=str(prospecto["phone"] or ""),
                     hilo=hilo, asunto_hilo=asunto, ahora=ahora, aunque_no_se_le_escriba=True) or ""


# --- Senales de la demo -------------------------------------------------------------------

def procesar_senales(ahora: Optional[datetime] = None) -> Dict[str, int]:
    """Los botones de su demo ("Activar", "Tengo una duda", "WhatsApp") pulsados desde la ultima
    vez (cursor por id de evento): quien pulsa uno se cualifica. La primera vez mira
    DIAS_DE_INTERES hacia atras. Quien solo la USA entra por `inscribir_a_quien_la_usa`."""
    ahora = ahora or timeutils._utc_now()
    tipos = tuple(SENALES_DE_INTERES)
    with _conexion() as conn:
        tope = int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0])
        cursor = _leer(conn, "cursor_eventos", "")
        if cursor.isdigit():
            desde = int(cursor)
        else:
            fila = conn.execute("SELECT MIN(id) FROM events WHERE ts >= ?",
                                (_iso(ahora - timedelta(days=DIAS_DE_INTERES)),)).fetchone()
            desde = int(fila[0]) - 1 if fila and fila[0] is not None else tope
        filas = conn.execute("SELECT id, lower(trim(email)) AS email, type, ts FROM events WHERE id > ? AND id <= ? "
                             "AND type IN (%s) ORDER BY id LIMIT 500" % ",".join("?" * len(tipos)),
                             (desde, tope) + tipos).fetchall()
    cualificados = 0
    for fila in filas:
        cuando = _dt(fila["ts"]) or ahora
        try:
            if cuando >= ahora - timedelta(days=DIAS_DE_INTERES) and _cualificar_por_senal(
                    fila["email"], fila["type"], cuando, ahora):
                cualificados += 1
        except Exception:  # noqa: BLE001 - una senal rara no para las demas
            settings.logger.exception("[seguimiento_demo] no se pudo procesar el evento %s", fila["id"])
    with _conexion() as conn:
        _guardar(conn, "cursor_eventos", str(filas[-1]["id"] if len(filas) == 500 else tope))
        conn.commit()
    return {"cualificados": cualificados, "senales": len(filas)}


def _cualificar_por_senal(email: str, tipo: str, cuando: datetime, ahora: datetime) -> bool:
    with _conexion() as conn:
        prospecto = conn.execute("SELECT * FROM prospects WHERE email=?", (email,)).fetchone()
        fila = _por_email(conn, email)
    if prospecto is None:
        return False
    # Ya lo lleva Pablo (respondio), es cliente, o pidio la baja o reboto: no se avisa.
    if str(prospecto["status"] or "").strip().lower() in ("replied", "client", "baja", "bounced"):
        return False
    if fila is not None:
        if fila["estado"] == "cualificado":
            return False
        # Una senal de ANTES de que lo cerraran (Pablo lo descarto, o dijo "ahora no") no lo
        # reabre: solo una nueva (al apagar y encender, o al releer, vuelven las viejas).
        cerrado = _dt(fila["actualizado"])
        if fila["estado"] in ("descartado", "parado") and cerrado is not None and cuando <= cerrado:
            return False
    seg_id = fila["id"] if fila is not None else seguimiento_para_demo_de_prospecto(prospecto, ahora)
    if not seg_id:
        return False
    return cualificar(seg_id, por="demo_" + tipo.split("_")[0], detalle=SENALES_DE_INTERES[tipo], ahora=ahora)


def seguimiento_para_demo_de_prospecto(prospecto, ahora: datetime) -> str:
    email = str(prospecto["email"] or "").strip().lower()
    with _conexion() as conn:
        hilo, asunto = _hilo_del_ultimo_correo(conn, email)
    return inscribir(origen="demo", canal="email", destino=email, prospecto=email,
                     negocio=str(prospecto["business_name"] or ""), sector=str(prospecto["niche"] or ""),
                     telefono=str(prospecto["phone"] or ""), hilo=hilo, asunto_hilo=asunto, ahora=ahora,
                     aunque_no_se_le_escriba=True) or ""


def ultimo_uso(conn, email: str) -> Optional[datetime]:
    """Cuando uso su demo por ultima vez (chat o voz), o None."""
    fila = conn.execute("SELECT MAX(ts) FROM events WHERE email=? AND type IN (%s)"
                        % ",".join("?" * len(SENALES_DE_USO)), (email,) + SENALES_DE_USO).fetchone()
    return _dt(fila[0]) if fila and fila[0] else None


def inscribir_a_quien_la_usa(ahora: Optional[datetime] = None) -> int:
    """Los prospectos que han USADO su demo (chat o voz) en los ultimos DIAS_DE_USO dias y aun no
    estan en seguimiento. Sin estado: al encender el interruptor entran tambien los que la
    usaron mientras estaba apagado. Solo con el interruptor encendido (si no, el correo frio
    sigue como siempre). Devuelve cuantos entraron."""
    ahora = ahora or timeutils._utc_now()
    with _conexion() as conn:
        if _leer(conn, "encendido", "0") != "1":
            return 0
        filas = conn.execute(
            "SELECT lower(trim(e.email)) AS email, MAX(e.ts) AS ts FROM events e WHERE e.type IN (%s) AND e.ts >= ? "
            "AND NOT EXISTS (SELECT 1 FROM seguimiento_demo s WHERE s.prospecto = lower(trim(e.email))) "
            # Los que nunca entraran (baja, ya respondio, cliente...) fuera ya aqui: si no, se
            # reintentaban en cada vuelta y podian tapar a los demas.
            "AND NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.email = lower(trim(e.email))) "
            "AND NOT EXISTS (SELECT 1 FROM prospects p WHERE p.email = lower(trim(e.email)) "
            "                AND COALESCE(p.status, '') IN (%s)) "
            "GROUP BY lower(trim(e.email)) LIMIT 100" % (",".join("?" * len(SENALES_DE_USO)),
                                                       ",".join("?" * len(ESTADOS_PROSPECTO_FUERA))),
            SENALES_DE_USO + (_iso(ahora - timedelta(days=DIAS_DE_USO)),) + ESTADOS_PROSPECTO_FUERA).fetchall()
    inscritos = 0
    for fila in filas:
        try:
            if _inscribir_por_uso(fila["email"], _dt(fila["ts"]) or ahora, ahora):
                inscritos += 1
        except Exception:  # noqa: BLE001 - uno raro no para a los demas
            settings.logger.exception("[seguimiento_demo] no se pudo inscribir a %s", fila["email"])
    return inscritos


def _inscribir_por_uso(email: str, cuando: datetime, ahora: datetime) -> bool:
    with _conexion() as conn:
        prospecto = conn.execute("SELECT * FROM prospects WHERE email=?", (email,)).fetchone()
        if prospecto is None or conn.execute("SELECT 1 FROM events WHERE email=? AND type='reply' LIMIT 1",
                                             (email,)).fetchone():
            return False
        hilo, asunto = _hilo_del_ultimo_correo(conn, email)
    return bool(inscribir(origen="correo", canal="email", destino=email, prospecto=email,
                          negocio=str(prospecto["business_name"] or ""), sector=str(prospecto["niche"] or ""),
                          telefono=str(prospecto["phone"] or ""), hilo=hilo, asunto_hilo=asunto, ahora=ahora,
                          primero_en=max(cuando_toca(cuando, 0), primer_hueco(ahora))))


def registrar_pasar_a_pablo(fila, *, cuando: str = "", persona: str = "", notas: str = "",
                            ahora: Optional[datetime] = None) -> str:
    """Sara: "que le llame Pablo". Es un lead cualificado: se apunta (oportunidad en el Plan de
    escala incluida) sin otro correo a Pablo, que ya tiene el de Sara ("🙋 Llámale")."""
    ahora = ahora or timeutils._utc_now()
    email = str(fila["prospecto"] or "").strip().lower()
    seg_id = inscribir(origen="llamada", canal="email" if email else "sms", destino=email or fila["telefono"],
                       prospecto=email, negocio=captacion_voz.nombre_corto(fila["negocio"] or ""),
                       sector=lanzador_llamadas.sector_real(fila["negocio"] or "", fila["sector"] or ""),
                       contacto=persona, telefono=fila["telefono"], llamada_id=fila["id"], ahora=ahora,
                       aunque_no_se_le_escriba=True)
    if seg_id:
        cualificar(seg_id, por="llamada_pablo", detalle=notas,
                   preferencias={"como": "telefono", "cuando": cuando, "nombre": persona,
                                 "telefono": fila["telefono"]}, ahora=ahora, avisar=False)
    return seg_id or ""


# --- Cualificar y descartar -------------------------------------------------------------

def _limpiar_preferencias(datos: Dict[str, Any]) -> Dict[str, str]:
    limpio: Dict[str, str] = {}
    como = str(datos.get("como") or "").strip().lower()
    if como in COMO:
        limpio["como"] = como
    for campo, largo in (("cuando", 80), ("nombre", 80), ("pregunta", 600)):
        valor = textnorm._sanitize_text(str(datos.get(campo) or ""), allow_multiline=campo == "pregunta")
        if valor:
            limpio[campo] = valor[:largo]
    email = str(datos.get("email") or "").strip().lower()
    if _EMAIL.match(email):
        limpio["email"] = email[:200]
    telefono = captacion_voz.telefono_e164(str(datos.get("telefono") or ""))
    if telefono:
        limpio["telefono"] = telefono
    return limpio


def cualificar(seg_id: str, *, por: str, detalle: str = "", preferencias: Optional[Dict[str, Any]] = None,
               respuesta: str = "", ahora: Optional[datetime] = None, avisar: bool = True) -> bool:
    """Ha dicho que si: la automatizacion se calla y Pablo se entera. Idempotente: True solo
    la primera vez (un segundo "si" no manda otro aviso)."""
    ahora = ahora or timeutils._utc_now()
    preferencias = _limpiar_preferencias(preferencias or {})
    if respuesta:
        preferencias["respuesta"] = textnorm._sanitize_text(respuesta, allow_multiline=True)[:1500]
    with _conexion() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cambio = conn.execute(
            "UPDATE seguimiento_demo SET estado='cualificado', cualificado_en=?, cualificado_por=?, motivo=?, "
            "preferencias=?, actualizado=? WHERE id=? AND estado<>'cualificado'",
            (_iso(ahora), por[:40], textnorm._sanitize_text(detalle)[:300], json.dumps(preferencias, ensure_ascii=False),
             _iso(ahora), seg_id)).rowcount
        if cambio != 1:
            conn.rollback()
            return False
        fila = conn.execute("SELECT * FROM seguimiento_demo WHERE id=?", (seg_id,)).fetchone()
        if fila["prospecto"]:
            # Fuera de toda automatizacion (correo frio, Sara, este seguimiento): ahora es de Pablo.
            conn.execute("UPDATE prospects SET status='replied', updated_at=? WHERE email=? "
                         "AND COALESCE(status, '') <> 'client'", (_iso(ahora), fila["prospecto"]))
            # Si antes dijo "ahora no" aqui, esa baja era nuestra: un "si" la quita.
            conn.execute("DELETE FROM suppressions WHERE email=? AND reason=?", (fila["prospecto"], MOTIVO_BAJA))
        conn.commit()
    try:
        refrescar_uso(seg_id)
    except Exception:  # noqa: BLE001 - la ficha sale igual, con lo que hubiera
        settings.logger.exception("[seguimiento_demo] no se pudo leer el uso de la demo de %s", seg_id)
    try:
        _crear_oportunidad(seg_id, ahora)
    except Exception:  # noqa: BLE001 - el aviso a Pablo importa mas que el Plan de escala
        settings.logger.exception("[seguimiento_demo] no se pudo crear la oportunidad de %s", seg_id)
    if avisar:
        _avisar_a_pablo(seg_id, ahora)
    return True


def descartar(seg_id: str, *, motivo: str, detalle: str = "", ahora: Optional[datetime] = None) -> bool:
    """"Ahora no": se cierra, y la promesa de la pagina se cumple: no se le vuelve a escribir
    ni a llamar (baja de correo, prospecto 'lost' y su telefono en "no llamar")."""
    ahora = ahora or timeutils._utc_now()
    texto = MOTIVOS_NO.get(motivo, motivo or "sin motivo")
    if detalle:
        texto += ": " + textnorm._sanitize_text(detalle, allow_multiline=True)[:300]
    with _conexion() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cambio = conn.execute("UPDATE seguimiento_demo SET estado='descartado', motivo=?, actualizado=? "
                              "WHERE id=? AND estado<>'descartado'", (texto[:400], _iso(ahora), seg_id)).rowcount
        if cambio != 1:
            conn.rollback()
            return False
        fila = conn.execute("SELECT * FROM seguimiento_demo WHERE id=?", (seg_id,)).fetchone()
        for email in {fila["prospecto"], fila["destino"] if fila["canal"] == "email" else ""} - {""}:
            conn.execute("INSERT OR IGNORE INTO suppressions (email, reason, added_at) VALUES (?,?,?)",
                         (email, MOTIVO_BAJA, _iso(ahora)))
            conn.execute("UPDATE prospects SET status='lost', updated_at=? WHERE email=? "
                         "AND COALESCE(status, '') NOT IN ('client', 'baja')", (_iso(ahora), email))
        if fila["telefono"]:
            conn.execute("INSERT OR IGNORE INTO no_llamar (telefono, motivo, creado) VALUES (?,?,?)",
                         (fila["telefono"], "No le interesa la demo (seguimiento)", _iso(ahora)))
        conn.commit()
    return True


def parar_a_mano(seg_id: str, ahora: Optional[datetime] = None) -> bool:
    ahora = ahora or timeutils._utc_now()
    with _conexion() as conn:
        cambio = conn.execute("UPDATE seguimiento_demo SET estado='parado', motivo='parado a mano', actualizado=? "
                              "WHERE id=? AND estado='activo'", (_iso(ahora), seg_id)).rowcount
        conn.commit()
    return cambio == 1


# --- Respuestas por correo -----------------------------------------------------------------

INTENCIONES_RESPUESTA = ("interesado", "pregunta", "no_interesado", "fuera_de_oficina", "otro")
_CITA = re.compile(r"^\s*(?:>|(?:el|on)\s.{3,200}(?:escribi[oó]|wrote)\s*:?\s*$|-{2,}\s*(?:mensaje original|original "
                   r"message)|(?:de|from)\s*:\s.*@)", re.IGNORECASE)
_NO = re.compile(r"\bno (?:nos|me) interesa|\bno estamos interesad|\bno,? gracias\b|\bbaja\b|"
                 r"\bno (?:nos|me) (?:escrib|llam|contact)|\bno (?:lo )?necesitamos\b|\bya (?:tenemos|contamos)\b",
                 re.IGNORECASE)
_AUSENTE = re.compile(r"fuera de la oficina|out of office|respuesta autom[aá]tica|estar[eé] fuera|"
                      r"de vacaciones|ausente hasta", re.IGNORECASE)
_PROMPT_RESPUESTA = (
    "Clasifica la respuesta de un negocio a un correo de Vantelia (una recepcionista con IA para negocios "
    "con citas; le habiamos mandado una demo). Devuelve SOLO un objeto JSON con dos campos: "
    "\"intencion\" (una de: interesado, pregunta, no_interesado, fuera_de_oficina, otro) y \"resumen\" (una "
    "frase corta en español con lo que dice). interesado = quiere verlo, que le llamen, probarlo o saber mas. "
    "pregunta = pregunta algo (precio, como funciona) sin decir que no. no_interesado = dice que no, que no "
    "le escribamos o que ya tiene algo. fuera_de_oficina = respuesta automatica. otro = lo demas.")


def _sin_cita(texto: str) -> str:
    """Lo que escribio el, sin nuestro correo citado debajo (que dice "no os escribo mas")."""
    lineas = []
    for linea in str(texto or "").splitlines():
        if _CITA.match(linea):
            break
        lineas.append(linea)
    return "\n".join(lineas).strip()


def clasificar_respuesta(texto: str, asunto: str = "") -> Dict[str, str]:
    """{"intencion", "resumen"}. Sin modelo (o si falla), todo lo que no sea un "no" claro o una
    respuesta automatica cuenta como pregunta: mejor un aviso de mas que un lead perdido."""
    propio = _sin_cita(texto)[:1500]
    if _AUSENTE.search(propio) or _AUSENTE.search(str(asunto or "")):
        respaldo = {"intencion": "fuera_de_oficina", "resumen": "Respuesta automática."}
    elif _NO.search(propio):
        respaldo = {"intencion": "no_interesado", "resumen": propio[:160]}
    else:
        respaldo = {"intencion": "pregunta", "resumen": propio[:160]}
    if not settings.OPENAI_API_KEY or not propio:
        return respaldo
    try:
        from openai import OpenAI as OpenAISdkClient  # import local, como en intents

        from backend import trazas

        cliente = OpenAISdkClient(api_key=settings.OPENAI_API_KEY, timeout=12.0)
        respuesta = cliente.chat.completions.create(
            model=settings.DEFAULT_CHAT_MODEL,
            messages=[{"role": "system", "content": _PROMPT_RESPUESTA},
                      {"role": "user", "content": "Asunto: %s\n\n%s" % (str(asunto or "")[:200], propio)}],
            temperature=0, max_tokens=120, response_format={"type": "json_object"})
        trazas.anotar_llamada(settings.DEFAULT_CHAT_MODEL, respuesta)
        datos = textnorm.objeto_json((respuesta.choices[0].message.content or "").strip()) or {}
    except Exception as exc:  # noqa: BLE001 - clasificar nunca deja a Pablo sin el aviso
        settings.logger.warning("[seguimiento_demo] no se pudo clasificar una respuesta: %s", exc)
        return respaldo
    intencion = textnorm.texto_de_json(datos.get("intencion")).strip().lower()
    if intencion not in INTENCIONES_RESPUESTA:
        return respaldo
    resumen = textnorm._sanitize_text(textnorm.texto_de_json(datos.get("resumen")))[:200] or respaldo["resumen"]
    return {"intencion": intencion, "resumen": resumen}


def al_responder(respuesta: Dict[str, Any]) -> bool:
    """El lector IMAP ha visto una respuesta. Si el negocio esta en seguimiento: interes o
    pregunta = cualificado y Pablo recibe la ficha (True: el aviso de siempre sobra). Si no, el
    seguimiento se cierra y Pablo recibe el aviso de siempre (False)."""
    email = str(respuesta.get("email") or "").strip().lower()
    with _conexion() as conn:
        fila = _por_email(conn, email)
    if fila is None or fila["estado"] == "cualificado":
        return False
    texto = str(respuesta.get("body_excerpt") or "")
    clasificada = clasificar_respuesta(texto, str(respuesta.get("subject") or ""))
    if clasificada["intencion"] in ("interesado", "pregunta"):
        return cualificar(fila["id"], por="respuesta", detalle=clasificada["resumen"], respuesta=_sin_cita(texto))
    estado = "descartado" if clasificada["intencion"] == "no_interesado" else "respondio"
    with _conexion() as conn:
        conn.execute("UPDATE seguimiento_demo SET estado=?, motivo=?, actualizado=? WHERE id=? "
                     "AND estado NOT IN ('cualificado', 'descartado')",
                     (estado, ("Respondió: " + clasificada["resumen"])[:400], _iso(timeutils._utc_now()), fila["id"]))
        conn.commit()
    return False


# --- Lo que hizo con la demo ---------------------------------------------------------------

def _uso_de_la_demo(prospecto: str, desde: str) -> Dict[str, Any]:
    """Lo que se sabe de su demo: clics al enlace, chat, voz, botones y sus primeras preguntas."""
    uso: Dict[str, Any] = {"clics": 0, "chat": 0, "mensajes": 0, "voz": 0, "botones": [], "preguntas": [],
                           "ultima": "", "alta": False}
    if not prospecto:
        return uso
    with _conexion() as conn:
        for tipo, url, cuantos in conn.execute(
                "SELECT type, COALESCE(url, ''), COUNT(*) FROM events WHERE email=? AND ts >= ? GROUP BY type, "
                "CASE WHEN type='click' THEN url ELSE '' END", (prospecto, desde)):
            if tipo == "click" and url == "demo_go":
                uso["clics"] += int(cuantos)
            elif tipo in ("demo_chat_opened", "demo_interacted"):
                uso["chat"] += int(cuantos)
            elif tipo == "demo_voice":
                uso["voz"] += int(cuantos)
            elif tipo in SENALES_DE_INTERES:
                uso["botones"].append(SENALES_DE_INTERES[tipo])
        ultima = conn.execute("SELECT MAX(ts) FROM events WHERE email=? AND ts >= ? AND type IN (%s)"
                              % ",".join("?" * (len(SENALES_DE_USO) + len(SENALES_DE_INTERES) + 1)),
                              (prospecto, desde) + SENALES_DE_USO + tuple(SENALES_DE_INTERES) + ("click",)).fetchone()
        uso["ultima"] = str((ultima[0] if ultima else "") or "")
    try:
        from backend import db, demo_agenda

        demo_id, _ = demo_agenda._existing_demo_for_email(prospecto)
        if demo_id:
            uso["demo"] = demo_id
            uso["alta"] = bool(db.db_get_client_owner(demo_id))
            with db._get_db_connection() as conn:
                filas = conn.execute("SELECT content FROM chat_messages WHERE cliente_id=? AND role='user' "
                                     "ORDER BY id", (demo_id,)).fetchall()
            conn.close()
            uso["mensajes"] = len(filas)
            uso["preguntas"] = [textnorm._sanitize_text(f["content"])[:160] for f in filas[:6]]
    except Exception:  # noqa: BLE001 - sin la demo (caducada), lo que digan los eventos
        settings.logger.debug("[seguimiento_demo] sin datos de la demo de %s", prospecto, exc_info=True)
    return uso


def refrescar_uso(seg_id: str) -> Dict[str, Any]:
    """Guarda lo que hizo con su demo. Las demos caducan a los 7 dias y se llevan su chat: lo
    que se vio no se pierde (se suma a lo guardado)."""
    fila = _fila(seg_id)
    if fila is None:
        return {}
    desde = _iso((_dt(fila["creado"]) or timeutils._utc_now()) - timedelta(days=DIAS_DE_INTERES))
    nuevo = _uso_de_la_demo(fila["prospecto"], desde)
    try:
        viejo = json.loads(fila["uso_demo"] or "{}")
    except ValueError:
        viejo = {}
    for clave in ("clics", "chat", "mensajes", "voz"):
        nuevo[clave] = max(int(nuevo.get(clave) or 0), int(viejo.get(clave) or 0))
    for clave in ("botones", "preguntas"):
        if not nuevo.get(clave):
            nuevo[clave] = list(viejo.get(clave) or [])
    nuevo["alta"] = bool(nuevo.get("alta") or viejo.get("alta"))
    nuevo["ultima"] = max(str(nuevo.get("ultima") or ""), str(viejo.get("ultima") or ""))
    with _conexion() as conn:
        conn.execute("UPDATE seguimiento_demo SET uso_demo=? WHERE id=?", (json.dumps(nuevo, ensure_ascii=False), seg_id))
        conn.commit()
    return nuevo


def _uso(fila) -> Dict[str, Any]:
    try:
        return json.loads(fila["uso_demo"] or "{}") or {}
    except ValueError:
        return {}


def la_probo(uso: Dict[str, Any]) -> bool:
    return bool(uso.get("chat") or uso.get("mensajes") or uso.get("voz"))


# --- Los textos -----------------------------------------------------------------------------

def _frases_del_sector(sector: str) -> Dict[str, str]:
    return _plantillas().sector_copy(sector or "")


def _plantillas():
    from backend import outreach  # deja scripts/ en el path
    import outreach_templates  # type: ignore

    _ = outreach
    return outreach_templates


def _firma() -> str:
    return _plantillas().SIGNATURE_TEXT


def _con_pie(inner_html: str) -> str:
    """El correo con el pie profesional de Pablo (logo, cargo, telefono, web y direccion), el
    mismo de los correos de captacion: lo pidio Pablo el 5-oct-2026 al ver uno con la firma en
    texto plano."""
    plantillas = _plantillas()
    return plantillas.html_shell(inner_html + plantillas.signature_html("seguimiento"))


def _asunto(fila) -> str:
    base = str(fila["asunto_hilo"] or "")
    if base:
        return base if base.lower().startswith("re:") else "Re: " + base
    return "La demo de %s" % (fila["negocio"] or "vuestro negocio")


def contenido(fila, plantilla: str, ahora: datetime) -> Dict[str, str]:
    """El correo de un toque: {"asunto", "texto", "html"}. Corto, de Pablo, y pide una respuesta
    (los correos con aspecto de marketing van a Promociones: aqui, solo parrafos y enlaces).

    Un enlace se escribe "[texto]{clave}" y va SIEMPRE al final de su parrafo: en el texto plano
    queda "texto: URL" sin nada detras (un punto pegado a la URL la rompe en algunos correos)."""
    from backend import segunda_oportunidad

    negocio = fila["negocio"] or "vuestro negocio"
    frases = _frases_del_sector(fila["sector"])
    nombre = _nombre_de_pila(fila["contacto"])
    uso = _uso(fila)
    creado = _dt(fila["creado"]) or ahora
    enlaces = {"si": enlace_interes(fila["id"], "si"), "no": enlace_interes(fila["id"], "no"),
               "demo": enlace_demo(fila["prospecto"])}
    cta = ("Si os encaja, os la enseño montada con vuestra agenda en 15 minutos. Contéstame con el día y la "
           "hora que mejor os venga" + (", o [elige aquí cuándo]{si}" if enlaces["si"] else "."))
    pd = ("P. D.: si ahora no es para vosotros, no os escribo más; [dímelo con un clic]{no}" if enlaces["no"] else
          "P. D.: si ahora no es para vosotros, contéstame «no» y no os escribo más.")
    if plantilla in ("primero", "que_tal"):
        if plantilla == "que_tal":
            intro = "Soy Pablo, de Vantelia. Te escribo por la demo de %s: ¿qué te ha parecido?" % negocio
            medio = ("Si le pediste una cita, ya has visto cómo atendería a %s mientras estáis %s, también por "
                     "WhatsApp y fuera de horario." % (frases["persona"], frases["atendiendo"]))
        else:
            cuando = _cuando_fue(creado, ahora)
            if fila["origen"] == "web":
                intro = ("Soy Pablo, de Vantelia. %s preparaste en nuestra web la demo de %s: vuestra recepcionista "
                         "con IA, con vuestros servicios y horarios." % (cuando[:1].upper() + cuando[1:], negocio))
            else:
                # "hablasteis", no "os llamo": tambien vale cuando llamaron ellos al 91.
                intro = ("Soy Pablo, de Vantelia. %s hablasteis con Sara, nuestra asistente con IA, y os mandó la demo "
                         "de %s: vuestra recepcionista contestando con vuestros servicios y horarios."
                         % (cuando[:1].upper() + cuando[1:], negocio))
            if la_probo(uso):
                medio = ("¿Qué os pareció? Si le pedisteis una cita, ya habéis visto cómo atendería a %s mientras "
                         "estáis %s." % (frases["persona"], frases["atendiendo"]))
            else:
                medio = ("¿Os dio tiempo a verla? Basta con pedirle una cita como lo haría %s. [Probar la demo de "
                         "%s]{demo}" % (frases["persona"], negocio.replace("[", "(").replace("]", ")")))
        parrafos = [intro, medio, cta, pd]
    elif plantilla == "valor":
        audio = segunda_oportunidad.audio_de_su_sector(fila["sector"])
        parrafos = ["Os escribo por la demo de %s. En %s pasa mucho: %s, y quien no consigue hablar con vosotros "
                    "suele probar en otro sitio." % (negocio, frases["sector"], frases["escena"])]
        if audio:
            enlaces["audio"] = audio["url"]
            parrafos.append("Así atiende Sara una llamada de verdad en %s, en menos de un minuto. "
                            "[Escuchar la llamada]{audio}" % audio["donde"])
        parrafos += ["Os lo dejo funcionando con %s, montado por nosotros y sin cambiar de número ni de WhatsApp. "
                     "¿Os lo enseño en 15 minutos? Contéstame%s"
                     % (OFERTA_PRUEBA, " o [elige aquí cuándo]{si}" if enlaces["si"] else "."), pd]
    else:  # cierre
        parrafos = ["Es mi último correo sobre la demo de %s: no quiero ser pesado." % negocio,
                    "¿Os interesa verla montada con vuestra agenda? Contéstame con un «sí» y os llamo cuando me "
                    "digáis" + (", o [elige aquí cuándo]{si}" if enlaces["si"] else "."),
                    ("Si no es para vosotros, no os escribo más; [dímelo con un clic]{no}" if enlaces["no"] else
                     "Si no es para vosotros, contéstame «no» y lo dejamos aquí.")]
    saludo = ("Hola, %s:" % nombre) if nombre else "Hola:"
    texto_parrafos, html_parrafos = [], []
    marca = re.compile(r"\[([^\]]+)\]\{(%s)\}" % "|".join(enlaces))
    for parrafo in parrafos:
        texto_parrafos.append(marca.sub(lambda m: "%s: %s" % (m.group(1), enlaces[m.group(2)]), parrafo))
        html_parrafos.append(marca.sub(lambda m: "<a href=\"%s\">%s</a>" % (escape(enlaces[m.group(2)], quote=True),
                                                                           m.group(1)), escape(parrafo, quote=False)))
    firma = "Un saludo,\n\n" + _firma().strip()
    texto = "\n\n".join([saludo] + texto_parrafos + [firma]) + "\n"
    html = _con_pie("".join("<p>%s</p>" % p for p in [escape(saludo)] + html_parrafos + ["Un saludo,"]))
    return {"asunto": _asunto(fila), "texto": texto, "html": html}


def texto_sms(fila, plantilla: str) -> str:
    """Sin tildes a proposito: con una, el SMS cambia de codificacion y cuesta el doble."""
    negocio = textnorm._strip_accents(fila["negocio"] or "vuestro negocio")
    enlace = enlace_interes(fila["id"]) or captacion_voz.WEB
    if plantilla == "cierre":
        texto = ("Hola, soy Pablo de Vantelia. Ultimo mensaje sobre la demo de %s: si os interesa verla montada, "
                 "elegid cuando aqui: %s Si no, no os escribo mas." % (negocio, enlace))
    else:
        texto = ("Hola! Soy Pablo, de Vantelia. Visteis la demo de %s? Si os encaja, la vemos montada con vuestra "
                 "agenda en 15 min. Elegid cuando: %s" % (negocio, enlace))
    return textnorm._strip_accents(texto)


# --- Enviar los toques ----------------------------------------------------------------------

def _motivo_para_parar(conn, fila, ahora: datetime) -> str:
    """Lo que cierra el seguimiento antes de un toque ("" si sigue). Se mira al elegir y otra
    vez justo antes de enviar, con la hora de ese momento."""
    if fila["estado"] != "activo":
        return "estado_" + str(fila["estado"])
    emails = [fila["prospecto"], fila["destino"] if fila["canal"] == "email" else ""]
    motivo = _no_se_le_escribe(conn, emails, fila["telefono"])
    if motivo:
        return motivo
    for email in [e for e in emails if e]:
        if conn.execute("SELECT 1 FROM events WHERE email=? AND type='reply' AND ts >= ? LIMIT 1",
                        (email, fila["creado"])).fetchone():
            return "respondio"
    return ""


def _cerrar(fila, motivo: str, ahora: datetime) -> None:
    estado = "respondio" if motivo in ("respondio", "estado_replied") else "parado"
    with _conexion() as conn:
        conn.execute("UPDATE seguimiento_demo SET estado=?, motivo=?, actualizado=? WHERE id=? AND estado='activo'",
                     (estado, motivo[:200], _iso(ahora), fila["id"]))
        conn.commit()


def caducar(ahora: datetime) -> int:
    """Lo que se quedo sin empezar (o a medias) mientras el interruptor estaba apagado no
    arranca semanas despues: "¿pudisteis verla?" ya no cuadra."""
    with _conexion() as conn:
        sin_empezar = conn.execute(
            "UPDATE seguimiento_demo SET estado='caducado', motivo='sin empezar a tiempo', actualizado=? "
            "WHERE estado='activo' AND paso=0 AND creado < ?",
            (_iso(ahora), _iso(ahora - timedelta(days=DIAS_PARA_EMPEZAR)))).rowcount
        a_medias = conn.execute(
            "UPDATE seguimiento_demo SET estado='terminado', motivo='toque retrasado', actualizado=? "
            "WHERE estado='activo' AND paso>0 AND proximo < ?",
            (_iso(ahora), _iso(ahora - timedelta(days=DIAS_DE_RETRASO_MAXIMO)))).rowcount
        conn.commit()
    return int(sin_empezar or 0) + int(a_medias or 0)


def _reservar(seg_id: str, paso: int, canal: str, ahora: datetime) -> bool:
    with _conexion() as conn:
        hecho = conn.execute("INSERT OR IGNORE INTO seguimiento_demo_toques (seguimiento_id, paso, canal, estado, "
                             "momento) VALUES (?,?,?,'enviando',?)", (seg_id, paso, canal, _iso(ahora))).rowcount
        conn.commit()
    return hecho == 1


def _soltar(seg_id: str, paso: int) -> None:
    with _conexion() as conn:
        conn.execute("DELETE FROM seguimiento_demo_toques WHERE seguimiento_id=? AND paso=? AND estado='enviando'",
                     (seg_id, paso))
        conn.commit()


def _apuntar_toque(fila, paso: int, estado: str, momento: datetime, mensaje_id: str = "", detalle: str = "",
                   asunto: str = "") -> None:
    """El toque salio (o pudo salir): se avanza igual, nunca se repite."""
    total = len(pasos(fila["origen"], fila["canal"]))
    with _conexion() as conn:
        conn.execute("UPDATE seguimiento_demo_toques SET estado=?, momento=?, message_id=?, detalle=? "
                     "WHERE seguimiento_id=? AND paso=?",
                     (estado, _iso(momento), mensaje_id[:300], detalle[:300], fila["id"], paso))
        if paso >= total:
            conn.execute("UPDATE seguimiento_demo SET paso=?, proximo='', estado=CASE WHEN estado='activo' THEN "
                         "'terminado' ELSE estado END, motivo=CASE WHEN estado='activo' THEN 'sin respuesta' ELSE "
                         "motivo END, actualizado=? WHERE id=?", (paso, _iso(momento), fila["id"]))
        else:
            siguiente = cuando_toca(momento, pasos(fila["origen"], fila["canal"])[paso][0])
            conn.execute("UPDATE seguimiento_demo SET paso=?, proximo=?, actualizado=? WHERE id=?",
                         (paso, _iso(siguiente), _iso(momento), fila["id"]))
        if mensaje_id and not fila["hilo"]:
            # Los siguientes toques van en el hilo de este.
            conn.execute("UPDATE seguimiento_demo SET hilo=?, asunto_hilo=? WHERE id=? AND hilo=''",
                         (mensaje_id[:300], asunto[:200], fila["id"]))
        conn.commit()


def _enviados_hoy(conn, canal: str, ahora: datetime) -> int:
    inicio = datetime.combine(ahora.astimezone(ZONA).date(), time(0, 0), tzinfo=ZONA)
    return int(conn.execute("SELECT COUNT(*) FROM seguimiento_demo_toques WHERE canal=? AND momento >= ? "
                            "AND estado IN ('enviado', 'incierto', 'enviando')",
                            (canal, _iso(inicio))).fetchone()[0])


def _mandar_toque(fila, plantilla: str, paso: int, momento: datetime) -> Tuple[str, str]:
    """Manda el toque. Devuelve (Message-ID o "", asunto). `NoEnviado` = seguro que no salio."""
    if fila["canal"] == "sms":
        if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN
                and (settings.TWILIO_SMS_SENDER or captacion_voz._numero_de_salida())):
            raise NoEnviado("Twilio no esta configurado para SMS")
        if not captacion_voz._mandar_sms(fila["destino"], texto_sms(fila, plantilla)):
            # Twilio devuelve False tambien si el corte llega despues de aceptarlo: en duda.
            raise RuntimeError("Twilio no confirmo el SMS")
        return "", ""
    from backend import outreach

    if plantilla == "primero" and fila["prospecto"] and not la_probo(_uso(fila)):
        # Lleva el enlace a su demo, que caduca a los 7 dias: que este lista cuando la abra.
        try:
            outreach._outreach_maybe_pregenerate_demo(fila["prospecto"])
        except Exception:  # noqa: BLE001 - sin demo lista, el enlace la genera al pinchar
            settings.logger.warning("[seguimiento_demo] no se pudo adelantar la demo de %s", fila["prospecto"])
    try:
        hecho = contenido(fila, plantilla, momento)
        ajustes = outreach.outreach_smtp_settings()
        mensaje = outreach.outreach_build_message(fila["destino"], hecho["asunto"], hecho["texto"],
                                                  hecho["html"], ajustes, in_reply_to=fila["hilo"] or None)
    except Exception as exc:  # noqa: BLE001 - antes de enviar: no salio nada
        raise NoEnviado("no se pudo preparar: %s" % exc) from exc
    try:
        outreach._outreach_send_email_object(mensaje)
    except (smtplib.SMTPConnectError, smtplib.SMTPAuthenticationError, smtplib.SMTPHeloError,
            smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError,
            smtplib.SMTPNotSupportedError, outreach.EnvioNoIniciado) as exc:
        raise NoEnviado(str(exc)) from exc
    mensaje_id = str(mensaje["Message-ID"] or "")
    # En `sends`, como todo correo de captacion: el lector IMAP reconoce la respuesta por su
    # Message-ID y el correo frio sabe que ya se le ha escrito.
    with _conexion() as conn:
        conn.execute("INSERT INTO sends (email, stage, subject, body_text, body_html, sent_at, mode, message_id) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (fila["prospecto"] or fila["destino"], ETAPA % paso, hecho["asunto"], hecho["texto"],
                      hecho["html"], _iso(momento), "send", mensaje_id))
        conn.commit()
    return mensaje_id, hecho["asunto"]


def _correo_en_pausa() -> bool:
    from backend import segunda_oportunidad

    return segunda_oportunidad.correo_en_pausa()


def _buzon_lleno(momento: datetime) -> str:
    """"" si queda sitio hoy en el buzon de captacion. Su tope TOTAL del dia (warm-up x multiplo,
    el mismo que limita los fu1/fu2/breakup del piloto) cuenta todo lo que sale por el, tambien
    estos toques y los que quedaron en duda (revision de Astra a c00d68c). Los SMS no cuentan."""
    from backend import outreach

    try:
        with _conexion() as conn:
            fila = conn.execute("SELECT daily_cold_cap FROM autopilot_config WHERE id=1").fetchone()
            efectivo = outreach._outreach_warmup_effective_cap(conn, int((fila[0] if fila else 0) or 20),
                                                               today=momento)
            dia = momento.astimezone(timezone.utc).date().isoformat()
            if outreach._outreach_enviados_hoy_total(conn, dia) >= outreach._outreach_tope_total_del_dia(efectivo):
                return "tope_del_buzon"
    except Exception:  # noqa: BLE001 - sin saberlo, no se manda
        settings.logger.exception("[seguimiento_demo] no se pudo leer el tope del buzon")
        return "tope_desconocido"
    return ""


def pendientes(ahora: datetime) -> List[Any]:
    with _conexion() as conn:
        return conn.execute("SELECT * FROM seguimiento_demo WHERE estado='activo' AND proximo<>'' AND proximo <= ? "
                            "ORDER BY proximo LIMIT 200", (_iso(ahora),)).fetchall()


def _aplazar(seg_id: str, cuando: datetime, ahora: datetime) -> None:
    with _conexion() as conn:
        conn.execute("UPDATE seguimiento_demo SET proximo=?, actualizado=? WHERE id=? AND estado='activo'",
                     (_iso(cuando), _iso(ahora), seg_id))
        conn.commit()


def ronda(*, ahora: Optional[datetime] = None, mandar: Callable[..., Tuple[str, str]] = None,
          esperar_turno: Callable[[], Any] = None, reloj: Callable[[], datetime] = None) -> Dict[str, Any]:
    """Manda los toques que tocan. Solo con el interruptor encendido y en horario; uno a uno,
    con el espaciado global de los correos de captacion y los topes del dia. Si ya hay otra
    ronda enviando (el hilo, o el boton del panel), esta no espera: se va."""
    if not _cerrojo.acquire(blocking=False):
        return {"enviados": 0, "motivo": "ya_hay_una_ronda"}
    try:
        return _ronda(ahora=ahora, mandar=mandar, esperar_turno=esperar_turno, reloj=reloj)
    finally:
        _cerrojo.release()


def _ronda(*, ahora: Optional[datetime], mandar, esperar_turno, reloj) -> Dict[str, Any]:
    if reloj is None:
        reloj = (lambda: ahora) if ahora is not None else timeutils._utc_now
    ahora = ahora or timeutils._utc_now()
    if not esta_encendido():
        return {"enviados": 0, "motivo": "apagado"}
    caducar(ahora)
    if not en_ventana(ahora):
        return {"enviados": 0, "motivo": "fuera_de_horario"}
    from backend import outreach

    probar_smtp = mandar is None
    mandar = mandar or _mandar_toque
    esperar_turno = esperar_turno or outreach._outreach_wait_send_slot
    correo_ok: Optional[bool] = None
    enviados, fallidos, saltados = 0, 0, 0
    for fila in pendientes(ahora)[:MAX_POR_RONDA * 3]:
        if enviados >= MAX_POR_RONDA or parar.is_set() or not esta_encendido():
            break
        canal = fila["canal"]
        if canal == "sms" and not en_ventana(ahora, VENTANA_SMS):
            continue
        with _conexion() as conn:
            motivo = _motivo_para_parar(conn, fila, ahora)
            lleno = _enviados_hoy(conn, canal, ahora) >= (MAX_SMS_AL_DIA if canal == "sms" else MAX_CORREOS_AL_DIA)
            uso = ultimo_uso(conn, fila["prospecto"]) if fila["prospecto"] and int(fila["paso"]) == 0 else None
        if motivo:
            _cerrar(fila, motivo, ahora)
            saltados += 1
            continue
        if lleno:
            continue
        if uso is not None and fila["origen"] in ("correo", "demo") and cuando_toca(uso, 0) > ahora:
            # Aun la esta usando: "¿que te ha parecido?" unas horas despues, no en mitad.
            _aplazar(fila["id"], cuando_toca(uso, 0), ahora)
            continue
        if canal == "email":
            if correo_ok is None:
                correo_ok = not _correo_en_pausa() and (not probar_smtp or bool(
                    outreach._outreach_smtp_health().get("ok")))
            if not correo_ok:
                continue
            if _buzon_lleno(ahora):
                # El tope del dia del buzon (warm-up) es uno para todos: hoy ya no salen correos.
                correo_ok = False
                continue
        paso = int(fila["paso"]) + 1
        lista = pasos(fila["origen"], canal)
        if paso > len(lista):
            _cerrar(fila, "sin_pasos", ahora)
            continue
        if not _reservar(fila["id"], paso, canal, ahora):
            continue
        if canal == "email":
            esperar_turno()
        momento = reloj()
        fila = _fila(fila["id"])
        with _conexion() as conn:
            motivo = _motivo_para_parar(conn, fila, momento) if fila is not None else "borrado"
        # Esperar el turno puede tardar minutos: entretanto otro emisor pudo activar la pausa del
        # buzon o llenar el tope del dia (revision de Astra a c00d68c).
        buzon = canal == "email" and (_correo_en_pausa() or bool(_buzon_lleno(momento)))
        if motivo or buzon or not esta_encendido() or not en_ventana(
                momento, VENTANA_SMS if canal == "sms" else VENTANA):
            _soltar(fila["id"] if fila is not None else "", paso)
            if motivo and fila is not None:
                _cerrar(fila, motivo, momento)
            if buzon:
                correo_ok = False
            continue
        try:
            mensaje_id, asunto = mandar(fila, lista[paso - 1][1], paso, momento)
        except NoEnviado as exc:
            fallidos += 1
            _soltar(fila["id"], paso)
            settings.logger.warning("[seguimiento_demo] no salio el toque %s de %s: %s", paso, fila["id"], exc)
            if _pausar_si_hay_limite(exc, fila, paso, canal):
                break
            continue
        except Exception as exc:  # noqa: BLE001 - pudo salir: se avanza y no se repite
            fallidos += 1
            error = textnorm._sanitize_text(str(exc))[:200]
            settings.logger.warning("[seguimiento_demo] toque %s de %s en duda: %s", paso, fila["id"], error)
            _apuntar_toque(fila, paso, "incierto", momento, detalle="Pudo salir; no se repite: " + error)
            if _pausar_si_hay_limite(exc, fila, paso, canal):
                break
            continue
        enviados += 1
        _apuntar_toque(fila, paso, "enviado", momento, mensaje_id=mensaje_id, asunto=asunto)
    return {"enviados": enviados, "fallidos": fallidos, "cerrados": saltados}


def _pausar_si_hay_limite(exc: BaseException, fila, paso: int, canal: str) -> bool:
    """Un limite del SMTP activa la pausa compartida de la captacion y para la ronda."""
    if canal != "email":
        return False
    from backend import outreach

    limite = outreach._outreach_smtp_ratelimit_reason(exc)
    if not limite:
        return False
    with _conexion() as conn:
        outreach._outreach_pause_autocapture_for_smtp_limit(conn, reason=limite, email=fila["destino"],
                                                             stage=ETAPA % paso)
    return True


# --- La ficha y el aviso a Pablo ---------------------------------------------------------------

def _prospecto(email: str) -> Dict[str, Any]:
    if not email:
        return {}
    with _conexion() as conn:
        fila = conn.execute("SELECT * FROM prospects WHERE email=?", (email,)).fetchone()
    return dict(fila) if fila else {}


def _la_llamada(llamada_id: str) -> Optional[Dict[str, Any]]:
    if not llamada_id:
        return None
    from backend import transcripciones_llamadas

    fila = captacion_voz._fila(llamada_id)
    if fila is None:
        return None
    transcripcion = transcripciones_llamadas.de_la_llamada(llamada_id) or {}
    return {"cuando": fila["creada"], "telefono": fila["telefono"], "con_quien": captacion_voz.con_quien_hablo(fila),
            "notas": fila["notas"] or "", "responsable": fila["responsable_nombre"] or "",
            "responsable_cuando": fila["responsable_cuando"] or "", "resumen": transcripcion.get("resumen") or "",
            "duracion": transcripcion.get("duracion")}


def _dia_bonito(momento: Optional[datetime]) -> str:
    if momento is None:
        return ""
    local = momento.astimezone(ZONA)
    return "%s %d a las %s" % (_DIAS_SEMANA[local.weekday()], local.day, local.strftime("%H:%M"))


def _enlace_directo(demo_id: str) -> str:
    if not demo_id:
        return ""
    try:
        from backend import demo_agenda

        return demo_agenda._canonical_demo_url(demo_id)
    except Exception:  # noqa: BLE001
        return ""


def ficha(seg_id: str) -> Dict[str, Any]:
    """Todo lo que Pablo necesita para la primera conversacion."""
    fila = _fila(seg_id)
    if fila is None:
        return {}
    try:
        preferencias = json.loads(fila["preferencias"] or "{}") or {}
    except ValueError:
        preferencias = {}
    prospecto = _prospecto(fila["prospecto"])
    uso = _uso(fila)
    llamada = _la_llamada(fila["llamada_id"])
    nombre = preferencias.get("nombre") or fila["contacto"] or (llamada or {}).get("responsable") or ""
    email = preferencias.get("email") or (fila["destino"] if fila["canal"] == "email" else "") or fila["prospecto"]
    telefono = preferencias.get("telefono") or fila["telefono"] or captacion_voz.telefono_e164(
        str(prospecto.get("phone") or ""))
    negocio = fila["negocio"] or prospecto.get("business_name") or email or telefono
    frases = _frases_del_sector(fila["sector"])
    como = COMO.get(preferencias.get("como", ""), "")
    cuando = preferencias.get("cuando") or ""
    por = str(fila["cualificado_por"] or "")
    por_texto = POR_TEXTO.get(por) or (fila["motivo"] if por.startswith("demo_") else por)
    with _conexion() as conn:
        toques = [dict(t) for t in conn.execute("SELECT paso, canal, estado, momento FROM seguimiento_demo_toques "
                                                "WHERE seguimiento_id=? ORDER BY paso", (seg_id,))]
    # Siguiente paso: un correo listo para mandar (Pablo prefiere el correo) y la conversacion.
    saludo = ("Hola, %s:" % _nombre_de_pila(nombre)) if _nombre_de_pila(nombre) else "Hola:"
    if preferencias.get("como") == "email":
        borrador = ("%s\n\nGracias por tu interés en la demo de %s. ¿Qué te gustaría saber? Si te viene bien, te la "
                    "enseño montada con vuestros servicios y vuestra agenda en 15 minutos, por teléfono o por "
                    "videollamada.\n\nUn saludo,\nPablo" % (saludo, negocio))
    else:
        propuesta = ("%s %s" % (como, cuando)).strip() if (como or cuando) else "cuando mejor os venga"
        borrador = ("%s\n\nGracias por tu interés en la demo de %s. Te propongo enseñártela montada con vuestros "
                    "servicios y vuestra agenda en 15 minutos, %s. ¿Te viene bien? Si prefieres otro momento, dímelo "
                    "y me adapto.\n\nUn saludo,\nPablo" % (saludo, negocio, propuesta))
    mailto = ("mailto:%s?subject=%s&body=%s" % (quote(email, safe="@"), quote("La demo de %s" % negocio),
                                                quote(borrador))
              if email else "")
    if uso.get("preguntas"):
        sobre_la_demo = "En su demo preguntó: «%s». Empieza por ahí." % uso["preguntas"][0]
    elif la_probo(uso):
        sobre_la_demo = "Probó la demo: pregúntale qué le pareció y qué echó en falta."
    else:
        sobre_la_demo = "No consta que probara la demo: enséñasela en directo, con su web y sus servicios."
    ideas = ["Pregúntale cuántas llamadas y mensajes se les escapan cuando están %s." % frases["atendiendo"],
             sobre_la_demo,
             "Cierra con dejarlo funcionando con %s, montado por ti y sin cambiar de número." % OFERTA_PRUEBA]
    plan = "Pro (129 €/mes), con WhatsApp; Business (299 €/mes) si quiere que también coja el teléfono"
    if uso.get("voz"):
        plan += " (probó la demo por voz)"
    elif fila["origen"] == "llamada":
        plan += " (ya ha oído a Sara)"
    plan += "."
    return {
        "id": seg_id, "negocio": negocio, "sector": fila["sector"] or prospecto.get("niche") or "",
        "origen": fila["origen"], "origen_texto": ORIGEN_TEXTO.get(fila["origen"], fila["origen"]),
        "estado": fila["estado"], "cualificado_en": fila["cualificado_en"], "cualificado_por": por,
        "por_texto": por_texto, "detalle": fila["motivo"] or "",
        "contacto": {"nombre": nombre, "telefono": telefono, "email": email,
                     "web": prospecto.get("website") or "", "ciudad": prospecto.get("city") or ""},
        "preferencias": {"como": como, "cuando": cuando, "pregunta": preferencias.get("pregunta") or ""},
        "respuesta": preferencias.get("respuesta") or "", "llamada": llamada, "demo": uso,
        # El enlace directo, no el de /demo/go: el clic de Pablo no puede contar como suyo.
        "enlace_demo": _enlace_directo(uso.get("demo") or ""),
        "toques": toques, "oportunidad_id": fila["oportunidad_id"] or "",
        "siguiente": {"mailto": mailto, "borrador": borrador, "ideas": ideas, "plan": plan},
    }


def _lineas_de_la_ficha(datos: Dict[str, Any]) -> List[Tuple[str, str]]:
    contacto, uso = datos["contacto"], datos["demo"] or {}
    lineas = [("Cómo", datos["por_texto"]), ("Origen", datos["origen_texto"])]
    pref = datos["preferencias"]
    if pref.get("como") or pref.get("cuando"):
        lineas.append(("Quiere", ("%s %s" % (pref.get("como") or "", pref.get("cuando") or "")).strip()))
    if pref.get("pregunta"):
        lineas.append(("Pregunta", pref["pregunta"]))
    lineas += [("Persona", contacto["nombre"] or "-"), ("Teléfono", contacto["telefono"] or "-"),
               ("Email", contacto["email"] or "-"), ("Web", contacto["web"] or "-"),
               ("Ciudad", contacto["ciudad"] or "-"), ("Sector", datos["sector"] or "-")]
    partes = []
    if uso.get("clics"):
        partes.append("abrió el enlace %d %s" % (uso["clics"], "vez" if uso["clics"] == 1 else "veces"))
    if uso.get("mensajes"):
        partes.append("escribió %d mensajes al chat" % uso["mensajes"])
    elif uso.get("chat"):
        partes.append("abrió el chat")
    if uso.get("voz"):
        partes.append("la llamó por voz")
    if uso.get("alta"):
        partes.append("terminó el alta en el portal")
    lineas.append(("Su demo", ", ".join(partes) if partes else "no consta que la abriera"))
    return lineas


def aviso(datos: Dict[str, Any], *, recordatorio: bool = False) -> Tuple[str, str, str]:
    """(asunto, texto, html) del correo a Pablo con la ficha."""
    pref = datos["preferencias"]
    quiere = ("%s %s" % (pref.get("como") or "", pref.get("cuando") or "")).strip()
    asunto = ("⏰ Sigue esperando: %s" if recordatorio else "🔥 Lead cualificado: %s") % datos["negocio"]
    if quiere and not recordatorio:
        asunto += " — " + quiere
    lineas = _lineas_de_la_ficha(datos)
    llamada, uso, siguiente = datos["llamada"], datos["demo"] or {}, datos["siguiente"]
    bloques_texto = ["%s:" % ("Te lo recuerdo: se cualificó y la oportunidad sigue sin tocar" if recordatorio
                              else "Quiere saber más. A partir de aquí es tuyo"),
                     "\n".join("%-9s %s" % (k + ":", v) for k, v in lineas)]
    if datos["respuesta"]:
        bloques_texto.append("Lo que contestó:\n" + datos["respuesta"])
    if uso.get("preguntas"):
        bloques_texto.append("Lo que preguntó en su demo:\n" + "\n".join("- " + p for p in uso["preguntas"]))
    if llamada:
        bloques_texto.append("La llamada de Sara (%s): habló con %s. %s %s" % (
            _dia_bonito(_dt(llamada["cuando"])), llamada["con_quien"], llamada["notas"], llamada["resumen"]))
    bloques_texto.append("Para la conversación:\n" + "\n".join("- " + i for i in siguiente["ideas"])
                         + "\n- Plan: " + siguiente["plan"])
    bloques_texto.append("Borrador para contestarle:\n\n" + siguiente["borrador"])
    if datos["enlace_demo"]:
        bloques_texto.append("Su demo: " + datos["enlace_demo"])
    bloques_texto.append("Panel: %s/dashboard (Llamadas → Leads cualificados)" % (settings.APP_BASE_URL or "").rstrip("/"))
    texto = "\n\n".join(bloques_texto) + "\n"
    contacto = datos["contacto"]
    botones = []
    if siguiente["mailto"]:
        botones.append(("Contestarle (borrador listo)", siguiente["mailto"]))
    if contacto["telefono"]:
        botones.append(("Llamar", "tel:" + contacto["telefono"]))
        if captacion_voz.es_movil(contacto["telefono"]):
            # Le escribes tu, a mano, desde tu WhatsApp: nada automatico en productos de Meta.
            botones.append(("WhatsApp", "https://wa.me/" + contacto["telefono"].lstrip("+")))
    html = ["<div style='font-family:Arial,sans-serif;max-width:600px;color:#1a1a2e;line-height:1.5'>",
            "<h2 style='color:#00a6c7;margin:0 0 8px'>%s %s</h2>" % ("⏰" if recordatorio else "🔥",
                                                                     escape(datos["negocio"])),
            "<p>%s</p>" % escape("Se cualificó y la oportunidad sigue sin tocar." if recordatorio
                                 else "Quiere saber más. A partir de aquí es tuyo.")]
    html.append("<p>" + " ".join(
        "<a href='%s' style='display:inline-block;margin:0 6px 6px 0;padding:9px 14px;border-radius:8px;"
        "background:#00b1d9;color:#04101c;font-weight:700;text-decoration:none'>%s</a>"
        % (escape(url, quote=True), escape(etiqueta)) for etiqueta, url in botones) + "</p>")
    html.append("<table style='border-collapse:collapse;width:100%'>" + "".join(
        "<tr><td style='padding:3px 10px 3px 0;color:#667;width:90px;vertical-align:top'>%s</td><td>%s</td></tr>"
        % (escape(k), escape(v)) for k, v in lineas) + "</table>")
    if datos["respuesta"]:
        html.append("<h3>Lo que contestó</h3><blockquote style='border-left:3px solid #00b1d9;margin:0;padding:6px "
                    "12px;background:#f4fbfd;white-space:pre-wrap'>%s</blockquote>" % escape(datos["respuesta"]))
    if uso.get("preguntas"):
        html.append("<h3>Lo que preguntó en su demo</h3><ul>%s</ul>"
                    % "".join("<li>%s</li>" % escape(p) for p in uso["preguntas"]))
    if llamada:
        html.append("<h3>La llamada de Sara</h3><p>%s · habló con %s</p><p>%s</p><p style='color:#556'>%s</p>" % (
            escape(_dia_bonito(_dt(llamada["cuando"]))), escape(llamada["con_quien"]), escape(llamada["notas"]),
            escape(llamada["resumen"])))
    html.append("<h3>Para la conversación</h3><ul>%s<li>Plan: %s</li></ul>" % (
        "".join("<li>%s</li>" % escape(i) for i in siguiente["ideas"]), escape(siguiente["plan"])))
    html.append("<h3>Borrador</h3><pre style='white-space:pre-wrap;font-family:inherit;background:#f6f7f9;"
                "padding:10px;border-radius:8px'>%s</pre>" % escape(siguiente["borrador"]))
    if datos["enlace_demo"]:
        html.append("<p><a href='%s'>Abrir su demo</a></p>" % escape(datos["enlace_demo"], quote=True))
    html.append("</div>")
    return asunto, texto, "".join(html)


def _avisar_a_pablo(seg_id: str, ahora: datetime, *, recordatorio: bool = False) -> bool:
    from backend import outreach

    datos = ficha(seg_id)
    if not datos:
        return False
    asunto, texto, html = aviso(datos, recordatorio=recordatorio)
    try:
        return bool(outreach._outreach_notify_admin(asunto, texto, html))
    except Exception:  # noqa: BLE001 - el lead queda en el panel aunque el aviso falle
        settings.logger.exception("[seguimiento_demo] no se pudo avisar a Pablo de %s", seg_id)
        return False


def _hoy_madrid(ahora: datetime) -> str:
    return ahora.astimezone(ZONA).date().isoformat()


def _crear_oportunidad(seg_id: str, ahora: datetime) -> str:
    """La oportunidad del Plan de escala (lo que no esta apuntado alli no cuenta). Una por lead."""
    from backend import db, growth

    datos = ficha(seg_id)
    if not datos or datos.get("oportunidad_id"):
        return datos.get("oportunidad_id", "") if datos else ""
    contacto, pref = datos["contacto"], datos["preferencias"]
    quiere = ("%s %s" % (pref.get("como") or "", pref.get("cuando") or "")).strip()
    item = {
        "company": datos["negocio"][:180], "campaign": "Seguimiento de la demo", "offer": "Demo guiada de 15 minutos",
        "stage": "conversacion", "value_eur": 0, "decision_maker": (contacto["nombre"] or "")[:180],
        "contact": " · ".join(x for x in (contacto["telefono"], contacto["email"]) if x)[:240],
        "problem": (pref.get("pregunta") or datos["respuesta"] or datos["detalle"] or "")[:2000],
        "next_action": ("Contactar" + ((" (" + quiere + ")") if quiere else ""))[:1000],
        "next_action_date": _hoy_madrid(ahora), "decision_date": "",
        "notes": ("%s. Origen: %s. Seguimiento %s." % (datos["por_texto"], datos["origen_texto"], seg_id))[:4000],
        "lost_reason": "",
    }
    oportunidad_id, momento = uuid.uuid4().hex, timeutils._utc_now_iso()
    conn = db._get_db_connection()
    try:
        conn.execute(
            "INSERT INTO growth_opportunities (id,company,campaign,offer,stage,value_eur,decision_maker,contact,problem,"
            "next_action,next_action_date,decision_date,notes,lost_reason,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (oportunidad_id, item["company"], item["campaign"], item["offer"], item["stage"], item["value_eur"],
             item["decision_maker"], item["contact"], item["problem"], item["next_action"], item["next_action_date"],
             item["decision_date"], item["notes"], item["lost_reason"], momento, momento))
        growth._growth_audit(conn, oportunidad_id, "created", dict(item, fuente="seguimiento_demo"))
        conn.commit()
    finally:
        conn.close()
    with _conexion() as conn:
        conn.execute("UPDATE seguimiento_demo SET oportunidad_id=? WHERE id=? AND oportunidad_id=''",
                     (oportunidad_id, seg_id))
        conn.commit()
    return oportunidad_id


def _oportunidad(oportunidad_id: str) -> Optional[Dict[str, Any]]:
    if not oportunidad_id:
        return None
    from backend import db

    conn = db._get_db_connection()
    try:
        fila = conn.execute("SELECT * FROM growth_opportunities WHERE id=?", (oportunidad_id,)).fetchone()
    finally:
        conn.close()
    return dict(fila) if fila else None


def recordar(ahora: Optional[datetime] = None) -> int:
    """UN recordatorio por lead si a las 24 h su oportunidad sigue sin tocar (misma etapa y sin
    cambios). Solo en dias laborables y dentro de la ventana."""
    ahora = ahora or timeutils._utc_now()
    if not en_ventana(ahora):
        return 0
    with _conexion() as conn:
        filas = conn.execute("SELECT * FROM seguimiento_demo WHERE estado='cualificado' AND recordado_en='' "
                             "AND cualificado_en<>'' AND cualificado_en <= ?",
                             (_iso(ahora - timedelta(hours=HORAS_PARA_RECORDAR)),)).fetchall()
    enviados = 0
    for fila in filas:
        oportunidad = _oportunidad(fila["oportunidad_id"])
        sin_tocar = bool(oportunidad and oportunidad["stage"] == "conversacion"
                         and oportunidad["updated_at"] == oportunidad["created_at"])
        with _conexion() as conn:
            marcado = conn.execute("UPDATE seguimiento_demo SET recordado_en=? WHERE id=? AND recordado_en=''",
                                   (_iso(ahora) if sin_tocar else "no_hizo_falta", fila["id"])).rowcount
            conn.commit()
        if marcado == 1 and sin_tocar and _avisar_a_pablo(fila["id"], ahora, recordatorio=True):
            enviados += 1
    return enviados


# --- El formulario de /interes -----------------------------------------------------------------

def para_la_pagina(seg_id: str) -> Dict[str, Any]:
    """Lo que ensena la pagina /interes: el negocio, su demo y lo que ya sabemos (para no
    pedirlo otra vez)."""
    fila = _fila(seg_id)
    if fila is None:
        return {}
    return {"id": seg_id, "negocio": fila["negocio"] or "vuestro negocio", "estado": fila["estado"],
            "nombre": fila["contacto"] or "", "email": fila["destino"] if fila["canal"] == "email" else fila["prospecto"],
            "telefono": fila["telefono"] or "", "enlace_demo": enlace_demo(fila["prospecto"]) if fila["prospecto"] else ""}


def huecos_para_elegir(ahora: Optional[datetime] = None) -> List[str]:
    """"mañana por la mañana", "el jueves por la tarde"... los 3 siguientes dias laborables."""
    ahora = ahora or timeutils._utc_now()
    hoy = ahora.astimezone(ZONA).date()
    opciones: List[str] = []
    dia = hoy
    for _ in range(3):
        dia = _laborable(dia, 1)
        nombre = "mañana" if dia == hoy + timedelta(days=1) else "el " + _DIAS_SEMANA[dia.weekday()]
        opciones += ["%s por la mañana" % nombre, "%s por la tarde" % nombre]
    return opciones + ["cuando sea, me adapto"]


def respuesta_del_formulario(seg_id: str, datos: Dict[str, Any], ahora: Optional[datetime] = None) -> str:
    """Lo que envio desde /interes. Devuelve "cualificado", "descartado" o "ya" (ya estaba)."""
    ahora = ahora or timeutils._utc_now()
    if str(datos.get("r") or "") == "no":
        motivo = str(datos.get("motivo") or "").strip()
        hecho = descartar(seg_id, motivo=motivo if motivo in MOTIVOS_NO else "otro",
                          detalle=str(datos.get("detalle") or ""), ahora=ahora)
        return "descartado" if hecho else "ya"
    hecho = cualificar(seg_id, por="formulario", detalle="Pidió que le contactes desde el enlace del seguimiento",
                       preferencias=datos, ahora=ahora)
    return "cualificado" if hecho else "ya"


# --- El panel ------------------------------------------------------------------------------------

def embudo(ahora: Optional[datetime] = None, dias: int = 30) -> Dict[str, Any]:
    """De las llamadas al lead cualificado, los ultimos `dias`. Las pruebas de Pablo (origen
    'manual') no cuentan."""
    ahora = ahora or timeutils._utc_now()
    desde = _iso(ahora - timedelta(days=dias))
    with _conexion() as conn:
        llamadas = conn.execute(
            "SELECT COUNT(*) FROM llamadas_voz WHERE creada >= ? AND origen <> 'manual' AND conversation_id <> '' "
            "AND resultado NOT IN ('contestador', 'no_contesta', 'ocupado', 'fallida')", (desde,)).fetchone()[0]
        demos_sara = conn.execute("SELECT COUNT(*) FROM llamadas_voz WHERE creada >= ? AND origen <> 'manual' "
                                  "AND informacion = 'enviada'", (desde,)).fetchone()[0]
        filas = conn.execute("SELECT origen, estado, uso_demo, cualificado_en, prospecto FROM seguimiento_demo "
                             "WHERE creado >= ? OR cualificado_en >= ?", (desde, desde)).fetchall()
        clientes = conn.execute("SELECT COUNT(*) FROM seguimiento_demo s JOIN prospects p ON p.email = s.prospecto "
                                "WHERE p.status = 'client' AND (s.creado >= ? OR s.cualificado_en >= ?)",
                                (desde, desde)).fetchone()[0]
    usos = [(f, _uso(f)) for f in filas]
    cualificados = [f for f in filas if f["estado"] == "cualificado" and (f["cualificado_en"] or "") >= desde]
    por_llamada = [f for f in cualificados if f["origen"] == "llamada"]

    def tasa(parte: int, total: int) -> float:
        return round(parte * 100.0 / total, 1) if total else 0.0

    return {
        "dias": dias, "llamadas_con_persona": int(llamadas), "demos_por_sara": int(demos_sara),
        "en_seguimiento": len(filas),
        "por_origen": {o: sum(1 for f in filas if f["origen"] == o) for o in ORIGENES},
        "abrieron": sum(1 for _, u in usos if u.get("clics") or la_probo(u)),
        "probaron": sum(1 for _, u in usos if la_probo(u)),
        "cualificados": len(cualificados), "cualificados_por_llamada": len(por_llamada),
        "clientes": int(clientes),
        "demo_por_llamada": tasa(int(demos_sara), int(llamadas)),
        "leads_por_100_llamadas": tasa(len(por_llamada), int(llamadas)),
        "cualificados_por_demo": tasa(len(cualificados), len(filas)),
    }


def _publico(fila) -> Dict[str, Any]:
    uso = _uso(fila)
    try:
        preferencias = json.loads(fila["preferencias"] or "{}") or {}
    except ValueError:
        preferencias = {}
    total = len(pasos(fila["origen"], fila["canal"]))
    return {"id": fila["id"], "negocio": fila["negocio"] or fila["prospecto"] or fila["destino"],
            "origen": fila["origen"], "canal": fila["canal"], "destino": fila["destino"], "estado": fila["estado"],
            "paso": int(fila["paso"]), "pasos": total, "proximo": fila["proximo"], "creado": fila["creado"],
            "motivo": fila["motivo"] or "", "contacto": preferencias.get("nombre") or fila["contacto"] or "",
            "telefono": preferencias.get("telefono") or fila["telefono"] or "",
            "como": COMO.get(preferencias.get("como", ""), ""), "cuando": preferencias.get("cuando") or "",
            "cualificado_en": fila["cualificado_en"] or "", "cualificado_por": fila["cualificado_por"] or "",
            "por_texto": POR_TEXTO.get(fila["cualificado_por"] or "") or (fila["motivo"] or ""),
            "probo": la_probo(uso), "abrio": bool(uso.get("clics")) or la_probo(uso),
            "oportunidad_id": fila["oportunidad_id"] or ""}


def resumen(ahora: Optional[datetime] = None) -> Dict[str, Any]:
    ahora = ahora or timeutils._utc_now()
    with _conexion() as conn:
        cualificados = conn.execute("SELECT * FROM seguimiento_demo WHERE estado='cualificado' "
                                    "ORDER BY cualificado_en DESC LIMIT 50").fetchall()
        activos = conn.execute("SELECT * FROM seguimiento_demo WHERE estado='activo' ORDER BY proximo LIMIT 100").fetchall()
        cerrados = conn.execute("SELECT * FROM seguimiento_demo WHERE estado NOT IN ('activo', 'cualificado') "
                                "ORDER BY actualizado DESC LIMIT 30").fetchall()
        encendido_ = _leer(conn, "encendido", "0") == "1"
    leads = []
    for fila in cualificados:
        dato = _publico(fila)
        oportunidad = _oportunidad(fila["oportunidad_id"]) if fila["oportunidad_id"] else None
        dato["oportunidad_etapa"] = (oportunidad or {}).get("stage", "")
        leads.append(dato)
    return {"encendido": encendido_, "embudo": embudo(ahora), "cualificados": leads,
            "en_seguimiento": [_publico(f) for f in activos], "cerrados": [_publico(f) for f in cerrados],
            "pendientes": len(pendientes(ahora))}


def vista_previa(ahora: Optional[datetime] = None) -> List[Dict[str, str]]:
    """Los toques tal cual saldrian, con un negocio de ejemplo, para que Pablo los lea."""
    ahora = ahora or timeutils._utc_now()
    ejemplo = {"id": "sd_ejemplo00", "prospecto": "", "negocio": "Clínica Dental Ejemplo", "sector": "clinica dental",
               "contacto": "Marta Ruiz", "asunto_hilo": "Lo que te conté por teléfono", "hilo": "<x@y>",
               "creado": _iso(ahora - timedelta(days=1)), "uso_demo": "{}", "destino": "info@ejemplo.es",
               "telefono": "+34600000000", "canal": "email"}
    salida = []
    for origen in ("llamada", "web", "correo"):
        for numero, (_, plantilla) in enumerate(CADENCIA[origen], start=1):
            hecho = contenido(dict(ejemplo, origen=origen), plantilla, ahora)
            salida.append({"origen": origen, "paso": str(numero), "plantilla": plantilla, "asunto": hecho["asunto"],
                           "texto": hecho["texto"]})
    for numero, (_, plantilla) in enumerate(CADENCIA_SMS, start=1):
        salida.append({"origen": "llamada (SMS)", "paso": str(numero), "plantilla": plantilla, "asunto": "",
                       "texto": texto_sms(dict(ejemplo, origen="llamada", canal="sms"), plantilla)})
    return salida


# --- El hilo -------------------------------------------------------------------------------------

def refrescar_usos(ahora: datetime, limite: int = 40) -> int:
    with _conexion() as conn:
        ids = [f[0] for f in conn.execute("SELECT id FROM seguimiento_demo WHERE estado='activo' AND prospecto<>'' "
                                          "ORDER BY actualizado LIMIT ?", (limite,))]
    for seg_id in ids:
        try:
            refrescar_uso(seg_id)
        except Exception:  # noqa: BLE001
            settings.logger.debug("[seguimiento_demo] uso de %s", seg_id, exc_info=True)
    return len(ids)


def ciclo(ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Una vuelta: senales, uso de las demos, toques y recordatorios."""
    ahora = ahora or timeutils._utc_now()
    salida: Dict[str, Any] = {"senales": procesar_senales(ahora), "inscritos": inscribir_a_quien_la_usa(ahora)}
    refrescar_usos(ahora)
    salida["ronda"] = ronda()
    salida["recordatorios"] = recordar(ahora)
    return salida


def _trabajador() -> None:
    settings.logger.info("[seguimiento_demo] iniciado: una vuelta cada %s min.", MINUTOS_ENTRE_RONDAS)
    parar.wait(120)
    while not parar.is_set():
        try:
            ciclo()
        except Exception:  # noqa: BLE001
            settings.logger.exception("[seguimiento_demo] error en la vuelta")
        parar.wait(MINUTOS_ENTRE_RONDAS * 60)


def arrancar() -> Optional[threading.Thread]:
    """Arranca el hilo si hay captacion (modulo outreach). El interruptor del panel decide si
    se escribe a alguien; los avisos de leads a Pablo van siempre. Idempotente."""
    global hilo
    from backend import outreach

    if not outreach.OUTREACH_AVAILABLE:
        return None
    if hilo and hilo.is_alive():
        return hilo
    parar.clear()
    hilo = threading.Thread(target=_trabajador, name="vantelia-seguimiento-demo", daemon=True)
    hilo.start()
    return hilo
