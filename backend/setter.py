"""Marta, la setter: del "me interesa" a una llamada en la agenda de Pablo.

POR QUE EXISTE
--------------
Pablo (7-oct-2026): "quiero un setter de ventas". Hasta aqui el sistema cualificaba al
lead, le mandaba la ficha a Pablo... y ahi se paraba todo hasta que Pablo escribia. Los
cuatro leads de octubre lo demostraron: ninguno tenia reunion. Contestar en menos de 5
minutos multiplica por 21 la probabilidad de cualificar (estudio MIT/InsideSales), y una
reunion cerca y con recordatorio es una reunion a la que se va. Plan: docs/PLAN_OFICINA_IA.md.

QUE HACE
--------
1. Recoge a cada lead cualificado (`seguimiento_demo`, estado 'cualificado'), a quien deja
   una consulta en la web (`al_consultar`) y a quien contesta con interes a un correo frio
   (`tras_respuesta_fria`, con el OK de Pablo).
2. Le escribe Pablo en su hilo con DOS horas reales de su agenda: cada una es un boton que
   lleva a /reunion (setter_web.py), donde se confirma con un clic. Como mucho tres correos
   (dias 0, 3 y 6 laborables) y se para al reservar, al contestar o al decir que no.
3. La agenda es el motor de citas de siempre, sobre un tenant interno (`AGENDA_ID`): huecos
   reales, `booking._create_booking_core`, recordatorios de 24 h y 2 h y enlace de gestion.
   Pablo recibe la invitacion de calendario (.ics) y, 30 minutos antes, la ficha.
4. Lo que el lead contesta con sus palabras: "el jueves por la tarde" lo resuelve el CODIGO
   con los huecos reales (reserva o propone dos horas de esa franja). Precio, condiciones o
   cualquier cosa que no sea agendar va a la bandeja de Pablo con un borrador.

REGLAS
------
- Marta no vende ni negocia: agenda. Nunca habla de precios sin que Pablo apruebe.
- Nunca ofrece una hora que la agenda no devuelva. La cita la crea el nucleo de siempre
  (409 si el hueco se acaba de ocupar).
- Nada de WhatsApp a prospectos (la cuenta de Meta es de lo que cuelga el producto).
- Un toque se reserva antes de enviarlo (`setter_toques`): si queda en duda no se repite.
- Los correos a leads calientes NO esperan al tope diario del calentamiento del correo frio
  (perder un "me interesa" por eso seria absurdo), pero si respetan la pausa del buzon y el
  espaciado global de envios, y cuentan en el total del dia (van a `sends`).
"""
from __future__ import annotations

import base64
import copy
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
from email.message import EmailMessage
from html import escape
from typing import Any, Dict, Iterator, List, Optional, Tuple

from backend import appstate, captacion_voz, seguimiento_demo, settings, textnorm, timeutils

ZONA = seguimiento_demo.ZONA
AGENDA_ID = "agenda_pablo"
SERVICIO_SLUG = "llamada_con_pablo"
SERVICIO_NOMBRE = "Llamada con Pablo"
DURACION = 15
# Lo acordado con Pablo el 7-oct-2026: de lunes a viernes, de 10:00 a 13:30 y de 16:00 a 18:00.
HORARIO = {"day_start": "10:00", "day_end": "18:00", "pausa": ("13:30", "16:00"), "cerrados": [5, 6]}
VENTANA = (time(8, 0), time(21, 0))      # el primer correo sale al momento dentro de esta franja
HORA_DE_ARRANQUE = time(8, 30)            # ... y fuera de ella, a esta hora del siguiente laborable
ANTELACION_MINUTOS = 120                  # no se ofrece una hora que empiece antes de 2 horas
DIAS_A_OFRECER = 6                        # dias laborables en los que se buscan huecos
# (dias laborables desde el toque anterior, plantilla). El primero sale al entrar.
CADENCIA = ((0, "huecos"), (3, "otra_hora"), (3, "ultimo"))
DIAS_TRAS_EL_ULTIMO = 3
MINUTOS_FICHA = 30
HORAS_SMS = 2
SEGUNDOS_ENTRE_VUELTAS = 60
ETAPA = "setter_%s"   # en `sends`: el lector IMAP reconoce las respuestas por su Message-ID
ESTADOS_VIVOS = ("pendiente", "revision", "ofrecido", "reservado", "celebrada")
RESULTADOS = {"ganado": "ganada", "seguir": "propuesta", "perdido": "perdida"}
_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_DIAS_CORTOS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
          "octubre", "noviembre", "diciembre")
# Lo que no se agenda solo: Pablo lo lee y aprueba la respuesta (la regla de 2026 de los SDR
# con IA: revision humana si se habla de precio, condiciones, integraciones o competencia).
_DELICADO = re.compile(
    r"prec|cuest|cuant[oa]s? (?:vale|es)|tarifa|coste|cobr|factur|contrat|permanenc|descuent|oferta|"
    r"integra|compatib|programa|software|competen|otra empresa|ya (?:usamos|trabajamos)|"
    r"queja|reclam|enfad|molest|no funciona|cancel|anul|baja\b|proteccion de datos|rgpd|lopd",
    re.IGNORECASE)
_SIN_FRANJA = re.compile(r"\b(?:por|de|a)\s+la\s+(?:mañana|manana)\b|\ba media mañana\b|\bmediodia\b", re.IGNORECASE)

parar = threading.Event()
hilo: Optional[threading.Thread] = None
_cerrojo = threading.Lock()
_cache_ocupado: Dict[str, Any] = {"momento": None, "intervalos": []}


class NoEnviado(Exception):
    """Seguro que NO salio: se puede reintentar."""


# --- Base, ajustes y utilidades -------------------------------------------------------------

@contextmanager
def _conexion() -> Iterator[sqlite3.Connection]:
    with seguimiento_demo._conexion() as conn:
        yield conn


def _iso(momento: datetime) -> str:
    return seguimiento_demo._iso(momento)


def _dt(valor: Any) -> Optional[datetime]:
    return seguimiento_demo._dt(valor)


def _ajuste(clave: str, defecto: str = "") -> str:
    with _conexion() as conn:
        fila = conn.execute("SELECT valor FROM oficina_ajustes WHERE clave=?", ("setter_" + clave,)).fetchone()
    return str(fila[0]) if fila else defecto


def _guardar_ajuste(clave: str, valor: str) -> None:
    with _conexion() as conn:
        conn.execute("INSERT INTO oficina_ajustes (clave, valor) VALUES (?,?) ON CONFLICT(clave) DO UPDATE SET "
                     "valor=excluded.valor", ("setter_" + clave, valor))
        conn.commit()


def esta_encendida() -> bool:
    """El interruptor de Marta en la oficina. Apagada no escribe a nadie (las reservas que
    haga un lead desde su enlace siguen funcionando)."""
    return _ajuste("encendida", "0") == "1"


def guardar_config(*, encendida: Optional[bool] = None) -> Dict[str, Any]:
    if encendida is not None:
        _guardar_ajuste("encendida", "1" if encendida else "0")
        if encendida and not _ajuste("desde"):
            # Solo entran solos los que se cualifiquen a partir de ahora; los de antes, con
            # `importar_cualificados` y el OK de Pablo correo a correo.
            _guardar_ajuste("desde", _iso(timeutils._utc_now()))
    return {"encendida": esta_encendida(), "desde": _ajuste("desde")}


def _lead(lead_id: str):
    with _conexion() as conn:
        return conn.execute("SELECT * FROM setter_leads WHERE id=?", (lead_id,)).fetchone()


def _por_email(conn, email: str):
    email = str(email or "").strip().lower()
    if not email:
        return None
    return conn.execute("SELECT * FROM setter_leads WHERE email=? ORDER BY creado DESC LIMIT 1", (email,)).fetchone()


def _actualizar(lead_id: str, ahora: Optional[datetime] = None, **campos: Any) -> None:
    if not campos:
        return
    campos["actualizado"] = _iso(ahora or timeutils._utc_now())
    with _conexion() as conn:
        conn.execute("UPDATE setter_leads SET %s WHERE id=?" % ", ".join("%s=?" % c for c in campos),
                     list(campos.values()) + [lead_id])
        conn.commit()


def _correo_de_pablo() -> str:
    return str(settings.CONSULTA_NOTIFICATION_EMAIL or "").strip()


def _base_publica() -> str:
    return seguimiento_demo._base_publica()


def _local(momento: datetime) -> datetime:
    return momento.astimezone(ZONA)


def dia_y_hora(momento: datetime) -> str:
    """"jueves 9 de octubre a las 10:30"."""
    local = _local(momento)
    return "%s %d de %s a las %s" % (_DIAS[local.weekday()], local.day, _MESES[local.month - 1],
                                     local.strftime("%H:%M"))


def boton(momento: datetime) -> str:
    """"Jue 9 · 10:30"."""
    local = _local(momento)
    return "%s %d · %s" % (_DIAS_CORTOS[local.weekday()], local.day, local.strftime("%H:%M"))


def _franja(momento: datetime) -> str:
    return "mañana" if _local(momento).hour < 14 else "tarde"


def _nombre_de_pila(nombre: str) -> str:
    return seguimiento_demo._nombre_de_pila(nombre)


# --- La agenda de Pablo (un tenant interno) ------------------------------------------------

def _config_agenda() -> Dict[str, Any]:
    pausa_inicio, pausa_fin = HORARIO["pausa"]
    return {
        "nombre": "Vantelia", "icono": "V", "color": "#00b1d9",
        "bienvenida": "Agenda de Pablo, de Vantelia.", "prompt_extra": "", "allowed_origins": [],
        "contacto": {"email": _correo_de_pablo(), "telefono": ""},
        "branding": {"powered_by": "", "empresa": "Vantelia"},
        "plan": "business", "whatsapp": {"enabled": False},
        "booking": {
            "enabled": True, "timezone": "Europe/Madrid", "slot_minutes": DURACION,
            "day_start": HORARIO["day_start"], "day_end": HORARIO["day_end"],
            "break_windows": [{"start": pausa_inicio, "end": pausa_fin, "reason": "Pausa"}],
            "closed_weekdays": list(HORARIO["cerrados"]), "provider": "internal",
            "success_message": "Llamada agendada.",
            # La confirmacion y el aviso de cancelacion los escribe Marta, en el hilo y a nombre de
            # Pablo: los genericos llegarian duplicados. Recordatorios y "cambio de hora", los de
            # siempre.
            "message_template_enabled": {"confirmed": False, "cancelled": False},
        },
        "interno": {"que_es": "Agenda de Pablo para las llamadas que agenda la setter (backend/setter.py)."},
    }


def asegurar_agenda() -> bool:
    """Crea el tenant de la agenda de Pablo si no existe, con su profesional por defecto y el
    servicio "Llamada con Pablo · 15 min". Idempotente. True si lo ha creado."""
    from backend import agenda, clients, db, demo_agenda

    creado = False
    if AGENDA_ID not in appstate.CONFIG_CLIENTES:
        # Mismo camino que las demos: config.json se cambia bajo su cerrojo y desde la ultima
        # version en disco (un mapa viejo pisaria lo que hubiera guardado otro).
        with demo_agenda._demo_lifecycle_guard():
            clients._reload_runtime_configs_from_disk()
            if AGENDA_ID not in appstate.CONFIG_CLIENTES:
                normalizada = clients._normalize_client_config(AGENDA_ID, _config_agenda())
                with appstate.state_lock:
                    siguiente = copy.deepcopy(appstate.CONFIG_CLIENTES)
                    siguiente[AGENDA_ID] = normalizada
                    clients._update_runtime_configs(siguiente)
                clients._persist_configs_to_disk(siguiente)
                creado = True
    carpeta = settings.DATA_DIR / AGENDA_ID
    carpeta.mkdir(parents=True, exist_ok=True)
    info = carpeta / "info.txt"
    if not info.exists():
        info.write_text("===== AGENDA DE PABLO (VANTELIA) =====\n\nAgenda interna para las llamadas de 15 minutos "
                        "que agenda la setter. No es un negocio.\n", encoding="utf-8")
    agenda._ensure_default_employees_for_all_clients()
    agenda._ensure_default_locations_for_all_clients()
    momento = timeutils._utc_now_iso()
    with db._get_db_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO services (cliente_id, slug, name, duration_minutes, price_cents, "
                     "description, is_active, sort_order, created_at, updated_at) VALUES (?,?,?,?,0,?,1,0,?,?)",
                     (AGENDA_ID, SERVICIO_SLUG, SERVICIO_NOMBRE, DURACION,
                      "Pablo te llama y te enseña cómo quedaría vuestra recepcionista con IA.", momento, momento))
        conn.commit()
    return creado


def _empleado():
    from backend import agenda

    return agenda._resolve_employee_for_booking(AGENDA_ID, "")


# --- Lo que Pablo ya tiene en su calendario (opcional) --------------------------------------

def _url_calendario() -> str:
    return os.getenv("SETTER_ICAL_URL", "").strip()


def ocupado_en_calendario(ahora: Optional[datetime] = None) -> List[Tuple[datetime, datetime]]:
    """Los ratos ocupados del calendario personal de Pablo (su direccion secreta iCal de Google
    Calendar, `SETTER_ICAL_URL`), para no ofrecer esas horas. Cache de 10 minutos; si la
    descarga falla se usa lo ultimo que se leyo. Sin la variable, nada."""
    url = _url_calendario()
    if not url:
        return []
    ahora = ahora or timeutils._utc_now()
    momento = _cache_ocupado.get("momento")
    if momento and (ahora - momento) < timedelta(minutes=10):
        return list(_cache_ocupado["intervalos"])
    try:
        import httpx

        respuesta = httpx.get(url, timeout=8.0, follow_redirects=True)
        respuesta.raise_for_status()
        intervalos = intervalos_del_ical(respuesta.text, ahora, ahora + timedelta(days=21))
    except Exception as exc:  # noqa: BLE001 - sin su calendario se ofrece igual (bloquea en la agenda)
        settings.logger.warning("[setter] no se pudo leer el calendario de Pablo: %s", exc)
        return list(_cache_ocupado["intervalos"])
    _cache_ocupado.update(momento=ahora, intervalos=intervalos)
    return intervalos


def intervalos_del_ical(texto: str, desde: datetime, hasta: datetime) -> List[Tuple[datetime, datetime]]:
    """Los eventos de un .ics entre dos momentos, con las repeticiones expandidas (eso es lo
    dificil y lo hace `recurring_ical_events`). Los de dia completo y los marcados como
    "disponible" (TRANSP:TRANSPARENT) no ocupan."""
    import icalendar
    import recurring_ical_events

    calendario = icalendar.Calendar.from_ical(texto)
    salida: List[Tuple[datetime, datetime]] = []
    for evento in recurring_ical_events.of(calendario).between(desde, hasta):
        if str(evento.get("TRANSP", "")).upper() == "TRANSPARENT":
            continue
        inicio, fin = evento.get("DTSTART"), evento.get("DTEND")
        inicio = inicio.dt if inicio is not None else None
        fin = fin.dt if fin is not None else None
        if not isinstance(inicio, datetime):
            continue  # dia completo (cumpleanos, vacaciones marcadas a mano): no bloquea horas
        if not isinstance(fin, datetime):
            fin = inicio + timedelta(hours=1)
        inicio = inicio if inicio.tzinfo else inicio.replace(tzinfo=ZONA)
        fin = fin if fin.tzinfo else fin.replace(tzinfo=ZONA)
        salida.append((inicio.astimezone(timezone.utc), fin.astimezone(timezone.utc)))
    return salida


# --- Huecos --------------------------------------------------------------------------------

def huecos(ahora: Optional[datetime] = None, *, dias: int = DIAS_A_OFRECER,
           solo_dia: Optional[date] = None) -> List[datetime]:
    """Las horas libres de la agenda de Pablo (UTC), desde dentro de 2 horas, en los proximos
    `dias` laborables (o solo en `solo_dia`). Salen del motor de citas: lo mismo que veria el
    widget, mas lo ocupado de su calendario personal si lo hay."""
    from fastapi import HTTPException

    from backend import agenda

    ahora = ahora or timeutils._utc_now()
    limite = ahora + timedelta(minutes=ANTELACION_MINUTOS)
    try:
        empleado = _empleado()
    except Exception:  # noqa: BLE001 - sin agenda no hay huecos (y no se ofrece nada)
        settings.logger.exception("[setter] la agenda de Pablo no esta disponible")
        return []
    ocupado = ocupado_en_calendario(ahora)
    salida: List[datetime] = []
    dia = solo_dia or _local(ahora).date()
    contados, vueltas = 0, 0
    while contados < (1 if solo_dia else dias) and vueltas < 40:
        vueltas += 1
        if seguimiento_demo.es_laborable(dia):
            contados += 1
            try:
                # La rejilla del dia (horario y pausa) menos lo cogido y lo bloqueado: los mismos
                # filtros que `agenda._employee_slot_sets_for_day`, que es asincrona.
                horas = agenda._build_slots_for_day(AGENDA_ID, dia.isoformat(), employee_id=empleado["id"],
                                                    duration_minutes=DURACION)
                cogido = (agenda._booked_intervals(AGENDA_ID, dia.isoformat(), employee_id=empleado["id"])
                          + agenda._blocked_intervals(AGENDA_ID, dia.isoformat(), employee_id=empleado["id"]))
            except HTTPException:
                horas, cogido = [], []  # fuera de la ventana de reservas
            for hora in horas:
                try:
                    hh, mm = (int(x) for x in str(hora)[:5].split(":"))
                except ValueError:
                    continue
                if agenda._interval_overlaps(hh * 60 + mm, hh * 60 + mm + DURACION, cogido):
                    continue
                inicio = datetime.combine(dia, time(hh, mm), tzinfo=ZONA).astimezone(timezone.utc)
                fin = inicio + timedelta(minutes=DURACION)
                if inicio < limite or any(inicio < b and a < fin for a, b in ocupado):
                    continue
                salida.append(inicio)
        if solo_dia:
            break
        dia += timedelta(days=1)
    return salida


def lo_que_pide(texto: str, ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Del texto de la persona ("el jueves por la tarde", "mañana a las 11"): {fecha, franja,
    texto_hora}. Determinista, con los mismos parsers que el asistente."""
    ahora = ahora or timeutils._utc_now()
    crudo = str(texto or "")
    plano = textnorm._strip_accents(crudo.lower())
    franja = ""
    if re.search(r"\b(?:por|de|a)\s+la\s+tarde\b|\btarde\b", plano):
        franja = "tarde"
    elif re.search(r"\b(?:por|de|a)\s+la\s+manana\b|\bmedia manana\b|\bprimera hora\b", plano):
        franja = "mañana"
    # "por la mañana" no es "mañana": sin quitarlo, el parser lo leia como el dia siguiente.
    sin_franja = _SIN_FRANJA.sub(" ", crudo)
    sin_franja = re.sub(r"\b(?:por|de|a)\s+la\s+manana\b", " ", sin_franja, flags=re.IGNORECASE)
    fecha = textnorm._extract_date_from_text(sin_franja, "Europe/Madrid") if sin_franja.strip() else ""
    return {"fecha": fecha, "franja": franja, "texto": crudo}


def _hora_dicha(texto: str, candidatos: List[datetime]) -> Optional[datetime]:
    """La hora que dice ("a las 11", "la de las 10:30", "sobre las 5 de la tarde") entre las
    horas libres de ese dia. None si no dice ninguna que exista."""
    from backend import reserva

    if not candidatos:
        return None
    por_hora = {_local(h).strftime("%H:%M"): h for h in candidatos}
    exacta = textnorm._extract_time_from_text(texto or "")
    if exacta and exacta in por_hora:
        return por_hora[exacta]
    coloquial = reserva._hora_coloquial(texto or "", sorted(por_hora))
    return por_hora.get(coloquial) if coloquial else None


def _redondas(lista: List[datetime]) -> List[datetime]:
    return [h for h in lista if _local(h).minute in (0, 30)] or list(lista)


def elegir_dos(lista: List[datetime], preferencia: str = "", ahora: Optional[datetime] = None) -> List[datetime]:
    """Las dos horas que se ofrecen: la primera libre y otra de OTRO dia y otra franja (asi
    hay donde elegir). Si la persona dijo cuando le va bien ("el jueves por la tarde"), las
    dos salen de ahi si se puede. Se prefieren las en punto y las y media."""
    if not lista:
        return []
    candidatos = list(lista)
    if preferencia:
        pide = lo_que_pide(preferencia, ahora)
        filtrados = [h for h in candidatos
                     if (not pide["fecha"] or _local(h).date().isoformat() == pide["fecha"])
                     and (not pide["franja"] or _franja(h) == pide["franja"])]
        if filtrados:
            candidatos = filtrados
    redondas = _redondas(candidatos)
    primera = redondas[0]
    dia = _local(primera).date()
    otras = ([h for h in redondas if _local(h).date() != dia and _franja(h) != _franja(primera)]
             or [h for h in redondas if _local(h).date() != dia]
             or [h for h in redondas if h >= primera + timedelta(hours=1)])
    return [primera] + otras[:1]


# --- Enlaces firmados ----------------------------------------------------------------------

def token_de(lead_id: str) -> str:
    secreto = seguimiento_demo._secreto()
    if not (secreto and lead_id):
        return ""
    firma = hmac.new(secreto.encode("utf-8"), ("reunion:v1:" + lead_id).encode("utf-8"), hashlib.sha256).digest()
    return "%s.%s" % (lead_id, base64.urlsafe_b64encode(firma[:12]).decode("ascii").rstrip("="))


def id_del_token(token: str) -> str:
    lead_id, _, firma = str(token or "").partition(".")
    if not re.fullmatch(r"st_[A-Za-z0-9_-]{6,24}", lead_id) or not firma:
        return ""
    esperado = token_de(lead_id).partition(".")[2]
    return lead_id if esperado and hmac.compare_digest(firma, esperado) else ""


def hueco_en_url(momento: datetime) -> str:
    return _local(momento).strftime("%Y-%m-%dT%H:%M")


def hueco_de_url(valor: str) -> Optional[datetime]:
    try:
        local = datetime.strptime(str(valor or "")[:16], "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    return local.replace(tzinfo=ZONA).astimezone(timezone.utc)


def enlace(lead_id: str, momento: Optional[datetime] = None) -> str:
    token = token_de(lead_id)
    if not token:
        return ""
    return "%s/reunion/%s%s" % (_base_publica(), token, ("?h=" + hueco_en_url(momento)) if momento else "")


# --- Entrar en la lista de Marta ------------------------------------------------------------

def _primer_momento(ahora: datetime) -> datetime:
    """Al momento dentro de 8:00-21:00 de un laborable; si no, a las 8:30 del siguiente."""
    local = _local(ahora)
    if seguimiento_demo.es_laborable(local.date()) and VENTANA[0] <= local.time() < VENTANA[1]:
        return ahora
    dia = local.date()
    if not (seguimiento_demo.es_laborable(dia) and local.time() < VENTANA[0]):
        dia = seguimiento_demo._laborable(dia, 1)
    return datetime.combine(dia, HORA_DE_ARRANQUE, tzinfo=ZONA).astimezone(timezone.utc)


def _de_baja(conn, email: str) -> bool:
    if not email:
        return False
    return bool(conn.execute("SELECT 1 FROM suppressions WHERE email=?", (email,)).fetchone())


def entrar(*, origen: str, email: str = "", telefono: str = "", nombre: str = "", negocio: str = "",
           sector: str = "", nota: str = "", preferencia: str = "", seguimiento_id: str = "", hilo: str = "",
           asunto_hilo: str = "", oportunidad_id: str = "", requiere_ok: bool = False,
           ahora: Optional[datetime] = None) -> Optional[str]:
    """Apunta a un lead. Devuelve su id (o el que ya tenia), o None si no se le puede escribir.
    Lo que ya esta en marcha no se reinicia; lo cerrado (sin respuesta, cancelado...) vuelve a
    empezar, porque si entra otra vez es que ha vuelto a mostrar interes.

    `requiere_ok`: el primer correo no sale solo, va a la bandeja de Pablo (los leads de antes
    de encender a Marta y las respuestas a correos frios)."""
    ahora = ahora or timeutils._utc_now()
    email = str(email or "").strip().lower()
    if email and not seguimiento_demo._EMAIL.match(email):
        email = ""
    telefono = captacion_voz.telefono_e164(telefono) if telefono else ""
    if not (email or telefono):
        return None
    clave = email or "tel:" + telefono
    if not email:
        estado = "solo_telefono"   # la llamada de Sara para agendar llega en la fase 2
    else:
        estado = "revision" if requiere_ok else "pendiente"
    datos = {"nombre": textnorm._sanitize_text(nombre)[:80], "negocio": textnorm._sanitize_text(negocio)[:120],
             "sector": textnorm._sanitize_text(sector)[:80],
             "nota": textnorm._sanitize_text(nota, allow_multiline=True)[:1500],
             "preferencia": textnorm._sanitize_text(preferencia)[:120]}
    with _conexion() as conn:
        if _de_baja(conn, email):
            return None
        conn.execute("BEGIN IMMEDIATE")
        fila = conn.execute("SELECT * FROM setter_leads WHERE clave=?", (clave,)).fetchone()
        if fila is not None and fila["estado"] in ESTADOS_VIVOS + ("solo_telefono",):
            lead_id = fila["id"]
            conn.execute(
                "UPDATE setter_leads SET telefono=CASE WHEN telefono='' THEN ? ELSE telefono END, "
                "nombre=CASE WHEN nombre='' THEN ? ELSE nombre END, negocio=CASE WHEN negocio='' THEN ? ELSE negocio END, "
                "seguimiento_id=CASE WHEN seguimiento_id='' THEN ? ELSE seguimiento_id END, actualizado=? WHERE id=?",
                (telefono, datos["nombre"], datos["negocio"], seguimiento_id, _iso(ahora), lead_id))
            conn.commit()
            return lead_id
        proximo = _iso(_primer_momento(ahora)) if estado == "pendiente" else ""
        if fila is None:
            lead_id = "st_" + secrets.token_urlsafe(8)
            conn.execute(
                "INSERT INTO setter_leads (id, clave, seguimiento_id, origen, email, telefono, nombre, negocio, sector, "
                "nota, preferencia, hilo, asunto_hilo, estado, proximo, oportunidad_id, creado, actualizado) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lead_id, clave, seguimiento_id, origen, email, telefono, datos["nombre"], datos["negocio"],
                 datos["sector"], datos["nota"], datos["preferencia"], str(hilo or "")[:300],
                 textnorm._sanitize_text(asunto_hilo)[:200], estado, proximo, oportunidad_id, _iso(ahora),
                 _iso(ahora)))
        else:
            lead_id = fila["id"]
            conn.execute(
                "UPDATE setter_leads SET origen=?, seguimiento_id=COALESCE(NULLIF(?, ''), seguimiento_id), "
                "telefono=COALESCE(NULLIF(?, ''), telefono), nombre=COALESCE(NULLIF(?, ''), nombre), "
                "negocio=COALESCE(NULLIF(?, ''), negocio), nota=?, preferencia=?, estado=?, paso=0, proximo=?, "
                "ofrecidos='[]', booking_id='', cita_inicio='', rescate=0, sms_en='', ficha_en='', resultado='', "
                "motivo='', actualizado=? WHERE id=?",
                (origen, seguimiento_id, telefono, datos["nombre"], datos["negocio"], datos["nota"],
                 datos["preferencia"], estado, proximo, _iso(ahora), lead_id))
            conn.execute("DELETE FROM setter_toques WHERE lead_id=? AND clave LIKE 'paso%'", (lead_id,))
        conn.commit()
    if estado == "revision":
        from backend import oficina

        oficina.proponer(agente="marta", tipo="primer_correo", ref=lead_id,
                         titulo="¿Le escribo a %s con dos horas para llamarle?" % (datos["negocio"] or email),
                         contexto=datos["nota"])
    return lead_id


def importar_cualificados(ahora: Optional[datetime] = None, *, solo_antes_de: str = "") -> List[str]:
    """Los leads ya cualificados que no estan en la lista de Marta (por ejemplo, los de antes
    de encenderla), con `requiere_ok`: Pablo ve cada primer correo antes de que salga."""
    with _conexion() as conn:
        filas = conn.execute(
            "SELECT s.* FROM seguimiento_demo s WHERE s.estado='cualificado' "
            "AND NOT EXISTS (SELECT 1 FROM setter_leads l WHERE l.seguimiento_id = s.id) "
            + ("AND s.cualificado_en < ? " if solo_antes_de else "") + "ORDER BY s.cualificado_en",
            (solo_antes_de,) if solo_antes_de else ()).fetchall()
    return [i for i in (_entrar_desde_seguimiento(f, requiere_ok=True, ahora=ahora, origen="seguimiento_previo")
                        for f in filas) if i]


def _entrar_desde_seguimiento(fila, *, requiere_ok: bool, ahora: Optional[datetime] = None,
                              origen: str = "seguimiento") -> Optional[str]:
    try:
        preferencias = json.loads(fila["preferencias"] or "{}") or {}
    except ValueError:
        preferencias = {}
    email = preferencias.get("email") or (fila["destino"] if fila["canal"] == "email" else "") or fila["prospecto"]
    telefono = preferencias.get("telefono") or fila["telefono"] or ""
    nota = preferencias.get("pregunta") or preferencias.get("respuesta") or fila["motivo"] or ""
    with _conexion() as conn:
        hilo, asunto = seguimiento_demo._hilo_del_ultimo_correo(conn, email) if email else ("", "")
    return entrar(origen=origen, email=email, telefono=telefono,
                  nombre=preferencias.get("nombre") or fila["contacto"] or "", negocio=fila["negocio"] or "",
                  sector=fila["sector"] or "", nota=nota, preferencia=preferencias.get("cuando") or "",
                  seguimiento_id=fila["id"], hilo=hilo or fila["hilo"] or "",
                  asunto_hilo=asunto or fila["asunto_hilo"] or "", oportunidad_id=fila["oportunidad_id"] or "",
                  requiere_ok=requiere_ok, ahora=ahora)


def recoger_cualificados(ahora: Optional[datetime] = None) -> int:
    """Los que el seguimiento ha cualificado desde que Marta esta encendida y aun no estan en
    su lista. Cualquier camino de cualificar (formulario, respuesta, boton de la demo, Sara)
    pasa por aqui, sin tocar el seguimiento."""
    desde = _ajuste("desde")
    if not desde:
        return 0
    with _conexion() as conn:
        filas = conn.execute(
            "SELECT s.* FROM seguimiento_demo s WHERE s.estado='cualificado' AND s.cualificado_en >= ? "
            "AND NOT EXISTS (SELECT 1 FROM setter_leads l WHERE l.seguimiento_id = s.id) LIMIT 50",
            (desde,)).fetchall()
    entrados = 0
    for fila in filas:
        try:
            if _entrar_desde_seguimiento(fila, requiere_ok=False, ahora=ahora):
                entrados += 1
        except Exception:  # noqa: BLE001 - uno raro no para a los demas
            settings.logger.exception("[setter] no se pudo recoger %s", fila["id"])
    return entrados


def al_consultar(*, nombre: str, email: str, telefono: str = "", empresa: str = "", mensaje: str = "",
                 ahora: Optional[datetime] = None) -> Optional[str]:
    """Alguien deja una consulta en vantelia.es/consultas: es el caso de manual de "contestar
    en 5 minutos". Pablo recibe el aviso de siempre; Marta le escribe con dos horas."""
    if not esta_encendida() or es_cliente(email):
        return None
    return entrar(origen="consulta", email=email, telefono=telefono, nombre=nombre, negocio=empresa,
                  nota=mensaje, asunto_hilo="", ahora=ahora)


def es_cliente(email: str) -> bool:
    """Quien ya tiene cuenta en el portal escribe por soporte, no para que le vendan: a ese no le
    escribe Marta (Pablo recibe la consulta igual)."""
    from backend import db

    email = str(email or "").strip().lower()
    if not email:
        return False
    with db._get_db_connection() as conn:
        return bool(conn.execute("SELECT 1 FROM users WHERE lower(email)=? AND role<>'admin'", (email,)).fetchone())


def tras_respuesta_fria(respuesta: Dict[str, Any]) -> bool:
    """Una respuesta a un correo frio de quien NO esta en el seguimiento ni con Marta. Si dice
    que le interesa, Marta propone escribirle con dos horas, con el OK de Pablo (una respuesta
    mal leida no puede acabar en un correo de agenda a quien estaba molesto)."""
    if not esta_encendida():
        return False
    email = str(respuesta.get("email") or "").strip().lower()
    with _conexion() as conn:
        if _por_email(conn, email) is not None:
            return False
        prospecto = conn.execute("SELECT * FROM prospects WHERE email=?", (email,)).fetchone()
        hilo, asunto = seguimiento_demo._hilo_del_ultimo_correo(conn, email)
    clasificada = seguimiento_demo.clasificar_respuesta(str(respuesta.get("body_excerpt") or ""),
                                                        str(respuesta.get("subject") or ""))
    if clasificada["intencion"] != "interesado":
        return False
    entrar(origen="respuesta", email=email, telefono=str((prospecto["phone"] if prospecto else "") or ""),
           negocio=str((prospecto["business_name"] if prospecto else "") or ""),
           sector=str((prospecto["niche"] if prospecto else "") or ""), nota=clasificada["resumen"],
           hilo=hilo, asunto_hilo=asunto or str(respuesta.get("subject") or ""), requiere_ok=True)
    return True


# --- Los correos ------------------------------------------------------------------------------

def _asunto(lead) -> str:
    base = str(lead["asunto_hilo"] or "")
    if base:
        return base if base.lower().startswith("re:") else "Re: " + base
    negocio = lead["negocio"] or ""
    return "Una llamada de 15 minutos" + ((" sobre %s" % negocio) if negocio else "")


def _intro(lead) -> str:
    origen = lead["origen"]
    negocio = lead["negocio"] or "vuestro negocio"
    if origen == "consulta":
        return "Soy Pablo, de Vantelia. Gracias por escribirnos desde la web."
    if origen == "respuesta":
        return "Gracias por contestarme."
    if origen == "seguimiento_previo":
        # Los de antes de encender a Marta: Pablo ya les habia escrito.
        return "Para que no se quede en el aire lo de la demo de %s:" % negocio
    with _conexion() as conn:
        seg = conn.execute("SELECT cualificado_por FROM seguimiento_demo WHERE id=?",
                           (lead["seguimiento_id"],)).fetchone() if lead["seguimiento_id"] else None
    if seg is not None and seg["cualificado_por"] == "llamada_pablo":
        return "Soy Pablo, de Vantelia. Sara me ha dicho que preferís que os llame yo."
    return "Soy Pablo, de Vantelia. Gracias por tu interés en la demo de %s." % negocio


def contenido(lead, plantilla: str, horas: List[datetime], ahora: datetime, *,
              extra: str = "", cuando_antes: Optional[datetime] = None) -> Dict[str, str]:
    """El correo: {"asunto", "texto", "html"}. Corto y de Pablo. Las horas van como botones;
    debajo, el enlace para elegir otra."""
    nombre = _nombre_de_pila(lead["nombre"])
    saludo = ("Hola, %s:" % nombre) if nombre else "Hola:"
    otra = enlace(lead["id"])
    if plantilla == "huecos":
        parrafos = [_intro(lead),
                    "Te propongo una llamada de 15 minutos: te llamo yo, te enseño cómo quedaría con vuestra agenda "
                    "y te resuelvo lo que quieras saber. ¿Te va bien alguna de estas horas?"]
    elif plantilla == "otra_hora":
        parrafos = ["¿Te viene mejor otra hora para la llamada de 15 minutos? Te dejo dos nuevas:"]
    elif plantilla == "ultimo":
        parrafos = ["Es mi último correo sobre esto, no quiero ser pesado.",
                    "Si más adelante os encaja hablarlo, elige cuándo te llamo y en 15 minutos te lo enseño "
                    "montado con vuestra agenda:"]
    elif plantilla == "mover":
        parrafos = ["Me ha surgido un imprevisto y no voy a poder llamarte el %s. Perdona." % (
            dia_y_hora(cuando_antes) if cuando_antes else "día que quedamos"),
                    "¿Te va bien alguna de estas horas?"]
    elif plantilla == "no_vino":
        parrafos = ["Te he llamado %s y no he podido localizarte. ¿Lo movemos? Te dejo dos horas:" % (
            ("el " + dia_y_hora(cuando_antes)) if cuando_antes else "hoy")]
    elif plantilla == "propuesta":
        parrafos = ["Perfecto. Te dejo las horas que tengo libres:" if horas else
                    "Ese día no me queda hueco, perdona."]
    elif plantilla == "respuesta":
        parrafos = [p.strip() for p in re.split(r"\n\s*\n", extra or "") if p.strip()]
        if horas:
            parrafos.append("Si te va bien que lo hablemos, elige hora y te llamo:")
    else:
        raise ValueError("plantilla desconocida: %s" % plantilla)
    if plantilla == "huecos" and lead["preferencia"]:
        parrafos[-1] += " (me dijiste %s)" % lead["preferencia"]
    cierre = ("Si ninguna te encaja, [elige otra hora aquí]{otra}, o contéstame con el día que mejor te venga."
              if otra else "Si ninguna te encaja, contéstame con el día que mejor te venga.")
    if plantilla == "ultimo":
        cierre = ("[Elegir cuándo me llamas]{otra}. Y si no es para vosotros, contéstame «no» y lo dejo aquí."
                  if otra else "Contéstame con el día que mejor te venga, o «no» y lo dejo aquí.")
        horas = []
    botones = [(boton(h), enlace(lead["id"], h)) for h in horas]
    marca = re.compile(r"\[([^\]]+)\]\{otra\}")
    texto_cierre = marca.sub(lambda m: "%s: %s" % (m.group(1), otra), cierre)
    html_cierre = marca.sub(lambda m: "<a href=\"%s\">%s</a>" % (escape(otra, quote=True), m.group(1)),
                            escape(cierre, quote=False))
    texto = [saludo] + parrafos
    if botones:
        texto.append("\n".join("- %s: %s" % (dia_y_hora(h)[:1].upper() + dia_y_hora(h)[1:], u)
                               for h, (_, u) in zip(horas, botones)))
    texto += [texto_cierre, "Un saludo,\n\n" + seguimiento_demo._firma().strip()]
    html = ["<p>%s</p>" % escape(p) for p in [saludo] + parrafos]
    if botones:
        html.append("<p>" + " ".join(
            "<a href='%s' style='display:inline-block;margin:0 8px 8px 0;padding:11px 18px;border-radius:999px;"
            "background:#00D1FF;color:#04101C;font-weight:700;text-decoration:none'>%s</a>"
            % (escape(u, quote=True), escape(etiqueta)) for etiqueta, u in botones) + "</p>")
    html += ["<p>%s</p>" % html_cierre, "<p>Un saludo,</p>"]
    return {"asunto": _asunto(lead), "texto": "\n\n".join(texto) + "\n",
            "html": seguimiento_demo._con_pie("".join(html))}


def confirmacion(lead, inicio: datetime, telefono: str, gestion: str) -> Dict[str, str]:
    nombre = _nombre_de_pila(lead["nombre"])
    saludo = ("Hola, %s:" % nombre) if nombre else "Hola:"
    numero = " al %s" % telefono if telefono else ""
    parrafos = ["Hecho: te llamo el %s%s. Son 15 minutos." % (dia_y_hora(inicio), numero),
                "Te mando la invitación para que la tengas en el calendario."]
    texto = [saludo] + parrafos
    html = ["<p>%s</p>" % escape(p) for p in [saludo] + parrafos]
    if gestion:
        texto.append("Si te surge algo, cámbiala aquí: %s" % gestion)
        html.append("<p>Si te surge algo, <a href=\"%s\">cámbiala aquí</a>.</p>" % escape(gestion, quote=True))
    texto.append("Un saludo,\n\n" + seguimiento_demo._firma().strip())
    html.append("<p>Un saludo,</p>")
    return {"asunto": _asunto(lead), "texto": "\n\n".join(texto) + "\n",
            "html": seguimiento_demo._con_pie("".join(html))}


def invitacion(lead, inicio: datetime, *, para: str, metodo: str = "REQUEST", secuencia: int = 0,
               descripcion: str = "") -> bytes:
    """La invitacion .ics (la genera `icalendar`): Gmail y Outlook la meten en el calendario.
    El mismo UID para la cita de un lead, con la SECUENCIA subiendo en cada cambio."""
    import icalendar

    calendario = icalendar.Calendar()
    calendario.add("prodid", "-//Vantelia//Setter//ES")
    calendario.add("version", "2.0")
    calendario.add("method", metodo)
    evento = icalendar.Event()
    evento.add("uid", "%s@setter.vantelia.es" % lead["id"])
    evento.add("dtstamp", timeutils._utc_now())
    evento.add("dtstart", inicio.astimezone(timezone.utc))
    evento.add("dtend", (inicio + timedelta(minutes=DURACION)).astimezone(timezone.utc))
    evento.add("sequence", int(secuencia))
    es_pablo = para == _correo_de_pablo()
    negocio = lead["negocio"] or lead["email"] or lead["telefono"]
    evento.add("summary", ("📞 %s (Vantelia)" % negocio) if es_pablo else "Llamada con Pablo, de Vantelia")
    if descripcion:
        evento.add("description", descripcion)
    organizador = icalendar.vCalAddress("mailto:" + (settings.SMTP_REPLY_TO or "info@vantelia.es"))
    organizador.params["cn"] = icalendar.vText("Pablo Sánchez · Vantelia")
    evento.add("organizer", organizador)
    asistente = icalendar.vCalAddress("mailto:" + para)
    asistente.params["rsvp"] = icalendar.vText("FALSE")
    evento.add("attendee", asistente)
    evento.add("status", "CANCELLED" if metodo == "CANCEL" else "CONFIRMED")
    calendario.add_component(evento)
    return calendario.to_ical()


def _adjuntar_ics(mensaje: EmailMessage, ics: bytes, metodo: str) -> None:
    mensaje.add_attachment(ics, maintype="text", subtype="calendar", filename="llamada.ics",
                           params={"method": metodo})


# --- Enviar ------------------------------------------------------------------------------------

def _reservar_toque(lead_id: str, clave: str, ahora: datetime) -> bool:
    with _conexion() as conn:
        hecho = conn.execute("INSERT OR IGNORE INTO setter_toques (lead_id, clave, estado, momento) "
                             "VALUES (?,?,'enviando',?)", (lead_id, clave, _iso(ahora))).rowcount
        conn.commit()
    return hecho == 1


def _soltar_toque(lead_id: str, clave: str) -> None:
    with _conexion() as conn:
        conn.execute("DELETE FROM setter_toques WHERE lead_id=? AND clave=? AND estado='enviando'", (lead_id, clave))
        conn.commit()


def _apuntar_toque(lead_id: str, clave: str, estado: str, momento: datetime, mensaje_id: str = "",
                   detalle: str = "") -> None:
    with _conexion() as conn:
        conn.execute("UPDATE setter_toques SET estado=?, momento=?, message_id=?, detalle=? WHERE lead_id=? AND clave=?",
                     (estado, _iso(momento), mensaje_id[:300], detalle[:300], lead_id, clave))
        conn.commit()


def _enviar_correo(lead, hecho: Dict[str, str], clave: str, momento: datetime, *, esperar_turno: bool = True,
                   ics: Optional[bytes] = None) -> str:
    """Manda el correo en su hilo. Devuelve el Message-ID. `NoEnviado` = seguro que no salio."""
    from backend import outreach

    if seguimiento_demo._correo_en_pausa():
        raise NoEnviado("el buzon de captacion esta en pausa")
    try:
        ajustes = outreach.outreach_smtp_settings()
        mensaje = outreach.outreach_build_message(lead["email"], hecho["asunto"], hecho["texto"], hecho["html"],
                                                  ajustes, in_reply_to=lead["hilo"] or None)
        if ics:
            _adjuntar_ics(mensaje, ics, "REQUEST")
    except Exception as exc:  # noqa: BLE001 - antes de enviar: no salio nada
        raise NoEnviado("no se pudo preparar: %s" % exc) from exc
    if esperar_turno:
        outreach._outreach_wait_send_slot()
    try:
        outreach._outreach_send_email_object(mensaje)
    except (smtplib.SMTPConnectError, smtplib.SMTPAuthenticationError, smtplib.SMTPHeloError,
            smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError,
            smtplib.SMTPNotSupportedError, outreach.EnvioNoIniciado) as exc:
        limite = outreach._outreach_smtp_ratelimit_reason(exc)
        if limite:
            with _conexion() as conn:
                outreach._outreach_pause_autocapture_for_smtp_limit(conn, reason=limite, email=lead["email"],
                                                                     stage=ETAPA % clave)
        raise NoEnviado(str(exc)) from exc
    mensaje_id = str(mensaje["Message-ID"] or "")
    with _conexion() as conn:
        conn.execute("INSERT INTO sends (email, stage, subject, body_text, body_html, sent_at, mode, message_id) "
                     "VALUES (?,?,?,?,?,?,?,?)", (lead["email"], ETAPA % clave, hecho["asunto"], hecho["texto"],
                                                  hecho["html"], _iso(momento), "send", mensaje_id))
        if mensaje_id and not lead["hilo"]:
            conn.execute("UPDATE setter_leads SET hilo=?, asunto_hilo=? WHERE id=? AND hilo=''",
                         (mensaje_id[:300], hecho["asunto"][:200], lead["id"]))
        conn.commit()
    return mensaje_id


def ofrecer(lead_id: str, plantilla: str, *, clave: str = "", ahora: Optional[datetime] = None,
            extra: str = "", preferencia: str = "", cuando_antes: Optional[datetime] = None,
            esperar_turno: bool = True) -> Dict[str, Any]:
    """Escribe al lead con dos horas (o, en el ultimo, solo con el enlace). Avanza la cadencia
    si es un paso. {"enviado": bool, "motivo": str, "horas": [...]}"""
    ahora = ahora or timeutils._utc_now()
    lead = _lead(lead_id)
    if lead is None or not lead["email"]:
        return {"enviado": False, "motivo": "sin_correo"}
    with _conexion() as conn:
        if _de_baja(conn, lead["email"]):
            _actualizar(lead_id, ahora, estado="descartado", motivo="de baja", proximo="")
            return {"enviado": False, "motivo": "baja"}
    libres = huecos(ahora)
    pide = preferencia or (lead["preferencia"] if plantilla == "huecos" else "")
    horas = elegir_dos(libres, pide, ahora)
    if plantilla == "propuesta" and preferencia:
        dia = lo_que_pide(preferencia, ahora)
        horas = elegir_dos([h for h in libres if not dia["fecha"] or _local(h).date().isoformat() == dia["fecha"]]
                           or libres, preferencia, ahora)
    if plantilla == "ultimo":
        horas = []  # el ultimo solo lleva el enlace a la agenda
    elif not horas and plantilla != "respuesta":
        return {"enviado": False, "motivo": "agenda_llena"}
    clave = clave or plantilla
    if not _reservar_toque(lead_id, clave, ahora):
        return {"enviado": False, "motivo": "ya_enviado"}
    hecho = contenido(lead, plantilla, horas, ahora, extra=extra, cuando_antes=cuando_antes)
    try:
        mensaje_id = _enviar_correo(lead, hecho, clave, ahora, esperar_turno=esperar_turno)
    except NoEnviado as exc:
        _soltar_toque(lead_id, clave)
        settings.logger.warning("[setter] no salio %s a %s: %s", clave, lead_id, exc)
        return {"enviado": False, "motivo": "no_salio"}
    except Exception as exc:  # noqa: BLE001 - pudo salir: no se repite
        _apuntar_toque(lead_id, clave, "incierto", ahora, detalle=textnorm._sanitize_text(str(exc))[:200])
        settings.logger.warning("[setter] %s a %s en duda: %s", clave, lead_id, exc)
        mensaje_id = ""
    else:
        _apuntar_toque(lead_id, clave, "enviado", ahora, mensaje_id=mensaje_id)
    campos: Dict[str, Any] = {"ofrecidos": json.dumps([_iso(h) for h in horas])}
    if lead["estado"] in ("pendiente", "revision", "celebrada", "ofrecido"):
        campos["estado"] = "ofrecido"
    if not lead["primer_contacto"]:
        campos["primer_contacto"] = _iso(ahora)
    if clave.startswith("paso"):
        paso = int(clave[4:] or 1)
        campos["paso"] = paso
        if paso < len(CADENCIA):
            campos["proximo"] = _iso(seguimiento_demo._a_su_hora(
                seguimiento_demo._laborable(_local(ahora).date(), CADENCIA[paso][0])))
        else:
            campos["proximo"] = _iso(seguimiento_demo._a_su_hora(
                seguimiento_demo._laborable(_local(ahora).date(), DIAS_TRAS_EL_ULTIMO)))
    elif lead["estado"] != "reservado":
        # Un correo fuera de la cadencia (propuesta, mover, respuesta de Pablo): el siguiente
        # recordatorio, a los 3 laborables.
        campos["proximo"] = _iso(seguimiento_demo._a_su_hora(seguimiento_demo._laborable(_local(ahora).date(), 3)))
    _actualizar(lead_id, ahora, **campos)
    _anotar_oportunidad(lead_id, "Marta le ofreció: " + ", ".join(dia_y_hora(h) for h in horas) if horas
                        else "Marta le mandó el enlace de la agenda", ahora)
    return {"enviado": True, "motivo": "", "horas": [_iso(h) for h in horas], "message_id": mensaje_id}


# --- Reservar ------------------------------------------------------------------------------------

async def reservar(lead_id: str, inicio: datetime, *, telefono: str = "", por: str = "web",
                   ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Crea la cita en la agenda de Pablo con el nucleo de siempre. {"ok", "motivo",
    "inicio", "gestion", "alternativas"}. 409 del nucleo = "ocupado"."""
    from fastapi import HTTPException

    from backend import booking

    ahora = ahora or timeutils._utc_now()
    lead = _lead(lead_id)
    if lead is None:
        return {"ok": False, "motivo": "no_existe"}
    if lead["estado"] == "descartado":
        return {"ok": False, "motivo": "descartado"}
    if lead["estado"] == "reservado" and lead["booking_id"]:
        actual = _cita(lead["booking_id"])
        if actual is not None and actual["status"] in ("confirmed", "pending_review"):
            return {"ok": False, "motivo": "ya_reservado", "inicio": lead["cita_inicio"],
                    "gestion": booking._build_booking_manage_url(actual["manage_token"])}
    libres = huecos(ahora, solo_dia=_local(inicio).date())
    if inicio not in libres:
        return {"ok": False, "motivo": "ocupado", "alternativas": [_iso(h) for h in elegir_dos(huecos(ahora))]}
    telefono = captacion_voz.telefono_e164(telefono) or lead["telefono"] or ""
    local = _local(inicio)
    try:
        fila = await booking._create_booking_core(
            AGENDA_ID, employee_row=_empleado(), nombre=(lead["nombre"] or lead["negocio"] or "Lead")[:80],
            email=lead["email"], telefono=telefono, servicio=SERVICIO_SLUG,
            booking_date=local.strftime("%Y-%m-%d"), booking_time=local.strftime("%H:%M"),
            notas=("Llamada de 15 min con Pablo. %s. Origen: %s (%s)." % (
                lead["negocio"] or "-", lead["origen"], por))[:500],
            source="setter", send_confirmation=False)
    except HTTPException as exc:
        if exc.status_code == 409:
            return {"ok": False, "motivo": "ocupado", "alternativas": [_iso(h) for h in elegir_dos(huecos(ahora))]}
        raise
    gestion = booking._build_booking_manage_url(fila["manage_token"])
    _actualizar(lead_id, ahora, estado="reservado", booking_id=fila["id"], cita_inicio=_iso(inicio),
                telefono=telefono, proximo="", sms_en="", ficha_en="", secuencia=int(lead["secuencia"] or 0) + 1,
                motivo="reservó (%s)" % por)
    _anotar_oportunidad(lead_id, "Llamada el %s" % dia_y_hora(inicio), ahora, etapa="demo",
                        fecha=local.date().isoformat())
    _en_segundo_plano(_avisar_reserva, lead_id, inicio, telefono, gestion)
    return {"ok": True, "motivo": "", "inicio": _iso(inicio), "gestion": gestion}


def reservar_ya(lead_id: str, inicio: datetime, **kwargs: Any) -> Dict[str, Any]:
    """`reservar` desde un hilo sin bucle de eventos (el lector IMAP)."""
    import asyncio

    return asyncio.run(reservar(lead_id, inicio, **kwargs))


def _en_segundo_plano(funcion, *args: Any) -> None:
    def correr() -> None:
        try:
            funcion(*args)
        except Exception:  # noqa: BLE001
            settings.logger.exception("[setter] fallo en segundo plano (%s)", getattr(funcion, "__name__", "?"))

    if getattr(appstate, "SETTER_SINCRONO", False):  # tests: sin hilos
        correr()
        return
    threading.Thread(target=correr, name="vantelia-setter-aviso", daemon=True).start()


def _cita(booking_id: str):
    from backend import db

    if not booking_id:
        return None
    with db._get_db_connection() as conn:
        return conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()


def _avisar_reserva(lead_id: str, inicio: datetime, telefono: str, gestion: str) -> None:
    """La confirmacion al lead (en su hilo, con la invitacion) y el aviso a Pablo (con la suya)."""
    lead = _lead(lead_id)
    if lead is None:
        return
    ahora = timeutils._utc_now()
    if lead["email"] and _reservar_toque(lead_id, "confirmacion_%s" % lead["secuencia"], ahora):
        hecho = confirmacion(lead, inicio, telefono, gestion)
        ics = invitacion(lead, inicio, para=lead["email"], secuencia=lead["secuencia"],
                         descripcion="Pablo te llama%s. Para cambiarla: %s" % (
                             (" al " + telefono) if telefono else "", gestion))
        clave = "confirmacion_%s" % lead["secuencia"]
        try:
            mensaje_id = _enviar_correo(lead, hecho, clave, ahora, esperar_turno=False, ics=ics)
            _apuntar_toque(lead_id, clave, "enviado", ahora, mensaje_id=mensaje_id)
        except NoEnviado as exc:
            _soltar_toque(lead_id, clave)
            settings.logger.warning("[setter] no salio la confirmacion de %s: %s", lead_id, exc)
        except Exception as exc:  # noqa: BLE001
            _apuntar_toque(lead_id, clave, "incierto", ahora, detalle=str(exc)[:200])
    _avisar_a_pablo(lead, "📅 Llamada agendada: %s, %s" % (lead["negocio"] or lead["email"], dia_y_hora(inicio)),
                    "Marta le ha agendado una llamada contigo el %s%s." % (
                        dia_y_hora(inicio), (" al " + telefono) if telefono else ""),
                    inicio=inicio, telefono=telefono)


# --- Avisos a Pablo ----------------------------------------------------------------------------

def _lineas(lead) -> List[Tuple[str, str]]:
    if lead["seguimiento_id"]:
        datos = seguimiento_demo.ficha(lead["seguimiento_id"])
        if datos:
            return seguimiento_demo._lineas_de_la_ficha(datos)
    lineas = [("Origen", {"consulta": "dejó una consulta en la web", "respuesta": "contestó a un correo frío",
                          "manual": "lo añadiste tú"}.get(lead["origen"], lead["origen"])),
              ("Persona", lead["nombre"] or "-"), ("Teléfono", lead["telefono"] or "-"),
              ("Email", lead["email"] or "-"), ("Negocio", lead["negocio"] or "-")]
    if lead["nota"]:
        lineas.append(("Escribió", lead["nota"]))
    return lineas


def _sala() -> str:
    return "%s/oficina" % (settings.APP_BASE_URL or "https://app.vantelia.es").rstrip("/")


def _avisar_a_pablo(lead, asunto: str, frase: str, *, inicio: Optional[datetime] = None, telefono: str = "",
                    metodo: str = "REQUEST") -> bool:
    """Correo a Pablo con la ficha y, si hay cita, su invitacion de calendario."""
    from backend import emailing, outreach

    para = _correo_de_pablo()
    if not para:
        return False
    lineas = _lineas(lead)
    telefono = telefono or lead["telefono"] or ""
    botones = [("Abrir la oficina", _sala())]
    if telefono:
        botones.insert(0, ("Llamar", "tel:" + telefono))
    texto = "%s\n\n%s\n\nOficina: %s\n" % (frase, "\n".join("%-9s %s" % (k + ":", v) for k, v in lineas), _sala())
    html = ("<div style='font-family:Arial,sans-serif;max-width:600px;color:#1a1a2e;line-height:1.5'>"
            "<p style='font-size:16px'>%s</p><p>%s</p><table style='border-collapse:collapse;width:100%%'>%s</table>"
            "</div>") % (escape(frase), " ".join(
                "<a href='%s' style='display:inline-block;margin:0 6px 6px 0;padding:9px 14px;border-radius:8px;"
                "background:#00b1d9;color:#04101c;font-weight:700;text-decoration:none'>%s</a>"
                % (escape(u, quote=True), escape(e)) for e, u in botones), "".join(
                "<tr><td style='padding:3px 10px 3px 0;color:#667;width:90px;vertical-align:top'>%s</td><td>%s</td></tr>"
                % (escape(k), escape(v)) for k, v in lineas))
    if inicio is None:
        try:
            return bool(outreach._outreach_notify_admin(asunto, texto, html))
        except Exception:  # noqa: BLE001
            settings.logger.exception("[setter] no se pudo avisar a Pablo")
            return False
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = emailing._email_sender()
    mensaje["To"] = para
    mensaje.set_content(texto)
    mensaje.add_alternative(html, subtype="html")
    _adjuntar_ics(mensaje, invitacion(lead, inicio, para=para, metodo=metodo, secuencia=lead["secuencia"],
                                      descripcion=texto[:1500]), metodo)
    try:
        emailing._send_email_object(mensaje)
        return True
    except Exception:  # noqa: BLE001 - sin la invitacion, al menos el aviso (con reintento)
        settings.logger.exception("[setter] no salio la invitacion a Pablo; va el aviso sin ella")
        try:
            return bool(outreach._outreach_notify_admin(asunto, texto, html))
        except Exception:  # noqa: BLE001
            return False


# --- El Plan de escala -----------------------------------------------------------------------

def _anotar_oportunidad(lead_id: str, accion: str, ahora: datetime, *, etapa: str = "", fecha: str = "",
                        motivo_perdida: str = "") -> None:
    """Lo que hace Marta queda en la oportunidad del Plan de escala (y asi el recordatorio de
    "sigue sin tocar" no salta: la oportunidad se ha movido)."""
    from backend import db, growth

    lead = _lead(lead_id)
    if lead is None:
        return
    try:
        oportunidad_id = lead["oportunidad_id"]
        if not oportunidad_id and lead["seguimiento_id"]:
            with _conexion() as conn:
                seg = conn.execute("SELECT oportunidad_id FROM seguimiento_demo WHERE id=?",
                                   (lead["seguimiento_id"],)).fetchone()
            oportunidad_id = (seg["oportunidad_id"] if seg else "") or ""
        conn = db._get_db_connection()
        try:
            momento = timeutils._utc_now_iso()
            if not oportunidad_id:
                oportunidad_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO growth_opportunities (id,company,campaign,offer,stage,value_eur,decision_maker,contact,"
                    "problem,next_action,next_action_date,decision_date,notes,lost_reason,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (oportunidad_id, (lead["negocio"] or lead["email"] or lead["telefono"])[:180], "Setter",
                     "Llamada de 15 minutos", etapa or "conversacion", 0, lead["nombre"][:180],
                     " · ".join(x for x in (lead["telefono"], lead["email"]) if x)[:240], lead["nota"][:2000],
                     accion[:1000], fecha or seguimiento_demo._hoy_madrid(ahora), "",
                     "Lead de la setter %s (%s)." % (lead_id, lead["origen"]), motivo_perdida, momento, momento))
                growth._growth_audit(conn, oportunidad_id, "created", {"fuente": "setter", "lead": lead_id})
            else:
                conn.execute(
                    "UPDATE growth_opportunities SET next_action=?, next_action_date=?, stage=COALESCE(NULLIF(?, ''), "
                    "stage), lost_reason=CASE WHEN ?<>'' THEN ? ELSE lost_reason END, updated_at=? WHERE id=?",
                    (accion[:1000], fecha or seguimiento_demo._hoy_madrid(ahora), etapa, motivo_perdida,
                     motivo_perdida, momento, oportunidad_id))
                growth._growth_audit(conn, oportunidad_id, "updated", {"fuente": "setter", "accion": accion[:200],
                                                                       "etapa": etapa})
            conn.commit()
        finally:
            conn.close()
        if oportunidad_id != lead["oportunidad_id"]:
            _actualizar(lead_id, ahora, oportunidad_id=oportunidad_id)
    except Exception:  # noqa: BLE001 - el Plan de escala nunca para a Marta
        settings.logger.exception("[setter] no se pudo anotar la oportunidad de %s", lead_id)


# --- Lo que contesta el lead -------------------------------------------------------------------

def al_responder(respuesta: Dict[str, Any]) -> bool:
    """El lector IMAP ha visto una respuesta. Si el lead esta con Marta, lo gestiona ella (True:
    el aviso generico sobra). False: no es suyo, o es un "no" y va el aviso de siempre."""
    email = str(respuesta.get("email") or "").strip().lower()
    with _conexion() as conn:
        lead = _por_email(conn, email)
    if lead is None or lead["estado"] not in ESTADOS_VIVOS:
        return False
    texto = seguimiento_demo._sin_cita(str(respuesta.get("body_excerpt") or ""))[:1500]
    asunto = str(respuesta.get("subject") or "")
    ahora = timeutils._utc_now()
    if seguimiento_demo._AUSENTE.search(texto) or seguimiento_demo._AUSENTE.search(asunto):
        return True  # respuesta automatica: ni se para ni se molesta a Pablo
    if seguimiento_demo._NO.search(texto) and lead["estado"] != "reservado":
        _actualizar(lead["id"], ahora, estado="descartado", motivo="Respondió que no: " + texto[:200], proximo="")
        _anotar_oportunidad(lead["id"], "Dijo que no", ahora, etapa="perdida", motivo_perdida=texto[:200])
        return False
    # Con un lead que aun espera el OK de Pablo (su primer correo esta en la bandeja), Marta no
    # contesta sola: lo que diga va a Pablo.
    if lead["estado"] not in ("reservado", "revision") and not _DELICADO.search(texto):
        if _agendar_por_texto(lead, texto, ahora):
            return True
    from backend import oficina

    oficina.proponer(agente="marta", tipo="respuesta", ref=lead["id"],
                     titulo="%s ha contestado: ¿le respondo así?" % (lead["negocio"] or lead["email"]),
                     contexto=texto, borrador=borrador(lead, texto))
    _actualizar(lead["id"], ahora, proximo="")   # la cadencia espera a Pablo
    _avisar_a_pablo(lead, "✋ Marta necesita tu OK: %s" % (lead["negocio"] or lead["email"]),
                    "Ha contestado y no es solo agendar. Te he dejado un borrador en la bandeja: «%s»" % texto[:300])
    return True


def _agendar_por_texto(lead, texto: str, ahora: datetime) -> bool:
    """"el jueves a las 11" -> reserva; "el jueves por la tarde" -> le propone dos horas de esa
    franja; "la de las 10:30" -> una de las que se le ofrecieron. El modelo no interviene: lo
    que no se entiende va a Pablo."""
    pide = lo_que_pide(texto, ahora)
    try:
        ofrecidas = [d for d in (_dt(x) for x in json.loads(lead["ofrecidos"] or "[]")) if d]
    except ValueError:
        ofrecidas = []
    if pide["fecha"]:
        try:
            dia = date.fromisoformat(pide["fecha"])
        except ValueError:
            return False
        del_dia = [h for h in huecos(ahora, solo_dia=dia) if not pide["franja"] or _franja(h) == pide["franja"]]
        elegida = _hora_dicha(texto, del_dia)
        if elegida is not None:
            hecho = reservar_ya(lead["id"], elegida, por="respuesta")
            if hecho.get("ok"):
                return True
        resultado = ofrecer(lead["id"], "propuesta", clave="propuesta_%s" % secrets.token_hex(3), ahora=ahora,
                            preferencia=texto)
        return bool(resultado.get("enviado"))
    elegida = _hora_dicha(texto, ofrecidas)
    if elegida is not None:
        return bool(reservar_ya(lead["id"], elegida, por="respuesta").get("ok"))
    if pide["franja"]:
        resultado = ofrecer(lead["id"], "propuesta", clave="propuesta_%s" % secrets.token_hex(3), ahora=ahora,
                            preferencia=texto)
        return bool(resultado.get("enviado"))
    return False


_PROMPT_BORRADOR = (
    "Eres Pablo Sánchez, fundador de Vantelia (recepcionista con IA para negocios con citas: contesta el chat de "
    "la web, WhatsApp y el teléfono, y da citas en su agenda). Escribe la respuesta a este correo de un negocio "
    "interesado. Reglas: español de España, tuteo, cercano y profesional, 2-5 frases, sin saludo ni firma (los "
    "pongo yo). No inventes nada. Datos que puedes usar si vienen al caso: planes Pro 129 €/mes (con WhatsApp) "
    "y Business 299 €/mes (también coge el teléfono); diez días de prueba gratis; lo dejamos montado nosotros "
    "sin cambiar de número. Si pregunta algo que no está en estos datos, di que se lo cuento en la llamada. "
    "Termina proponiendo una llamada de 15 minutos (las horas las añado yo debajo).")


def borrador(lead, texto: str) -> str:
    """El borrador que Pablo aprueba o corrige. Con el modelo si hay clave y presupuesto; si no,
    uno de plantilla."""
    from backend import oficina

    respaldo = ("Gracias por escribirme. Te lo cuento todo en una llamada de 15 minutos: te enseño cómo quedaría "
                "con vuestra agenda y te resuelvo las dudas.")
    if not settings.OPENAI_API_KEY or not oficina.hay_presupuesto("marta"):
        return respaldo
    try:
        from openai import OpenAI as OpenAISdkClient

        cliente = OpenAISdkClient(api_key=settings.OPENAI_API_KEY, timeout=15.0)
        respuesta = cliente.chat.completions.create(
            model=settings.DEFAULT_CHAT_MODEL,
            messages=[{"role": "system", "content": _PROMPT_BORRADOR},
                      {"role": "user", "content": "Negocio: %s\n\nSu correo:\n%s" % (lead["negocio"] or "-",
                                                                                   texto[:1500])}],
            temperature=0.3, max_tokens=300)
        oficina.anotar_gasto("marta", settings.DEFAULT_CHAT_MODEL, respuesta)
        propuesto = textnorm._sanitize_text(respuesta.choices[0].message.content or "", allow_multiline=True).strip()
    except Exception as exc:  # noqa: BLE001 - sin borrador del modelo, el de plantilla
        settings.logger.warning("[setter] no se pudo redactar el borrador: %s", exc)
        return respaldo
    return propuesto[:1500] or respaldo


# --- Lo que hace Pablo desde la oficina ----------------------------------------------------------

def aprobar(lead_id: str, tipo: str, texto: str = "") -> Dict[str, Any]:
    """Pablo ha aprobado en la bandeja: el primer correo de un lead en revision, o su respuesta
    (con el texto tal cual lo deja)."""
    lead = _lead(lead_id)
    if lead is None:
        return {"enviado": False, "motivo": "no_existe"}
    if tipo == "primer_correo":
        if lead["estado"] != "revision":
            return {"enviado": False, "motivo": "estado_" + lead["estado"]}
        # Un envio suelto aprobado a mano: sin esperar el espaciado (Pablo esta delante).
        return ofrecer(lead_id, "huecos", clave="paso1", esperar_turno=False)
    return ofrecer(lead_id, "respuesta", clave="respuesta_%s" % secrets.token_hex(3), extra=texto,
                   esperar_turno=False)


def rechazar(lead_id: str, tipo: str) -> None:
    lead = _lead(lead_id)
    if lead is not None and tipo == "primer_correo" and lead["estado"] == "revision":
        _actualizar(lead_id, estado="parado", motivo="Pablo prefirió no escribirle", proximo="")


async def mover(lead_id: str, *, nueva: Optional[datetime] = None, request=None) -> Dict[str, Any]:
    """Pablo no puede a esa hora. Con `nueva`, se mueve la cita (el lead recibe el aviso de
    cambio de siempre); sin ella, se cancela y Marta le escribe con dos horas nuevas."""
    from fastapi import HTTPException

    from api_models import BookingUpdatePayload
    from backend import booking

    lead = _lead(lead_id)
    if lead is None or lead["estado"] != "reservado":
        return {"ok": False, "motivo": "sin_cita"}
    fila = _cita(lead["booking_id"])
    if fila is None:
        return {"ok": False, "motivo": "sin_cita"}
    antes = _dt(lead["cita_inicio"])
    ahora = timeutils._utc_now()
    if nueva is not None:
        if nueva not in huecos(ahora, solo_dia=_local(nueva).date()):
            return {"ok": False, "motivo": "ocupado"}
        local = _local(nueva)
        datos = BookingUpdatePayload(nombre=(fila["nombre"] or "Lead")[:80], email=fila["email"] or "",
                                     telefono=fila["telefono"] or "", servicio=fila["servicio"] or SERVICIO_SLUG,
                                     employee_id=fila["employee_id"] or "", fecha=local.strftime("%Y-%m-%d"),
                                     hora=local.strftime("%H:%M"), notas=fila["notas"] or "")
        try:
            await booking._update_booking_details(fila, datos, request, source="setter",
                                                  audit_payload={"por": "pablo"})
        except HTTPException as exc:
            return {"ok": False, "motivo": "ocupado" if exc.status_code == 409 else str(exc.detail)}
        _actualizar(lead_id, ahora, cita_inicio=_iso(nueva), secuencia=int(lead["secuencia"] or 0) + 1, sms_en="",
                    ficha_en="")
        lead = _lead(lead_id)
        _avisar_a_pablo(lead, "🔁 Llamada movida: %s, %s" % (lead["negocio"] or lead["email"], dia_y_hora(nueva)),
                        "La has movido al %s. Le ha llegado el aviso del cambio." % dia_y_hora(nueva), inicio=nueva)
        _anotar_oportunidad(lead_id, "Llamada el %s" % dia_y_hora(nueva), ahora, fecha=local.date().isoformat())
        return {"ok": True, "inicio": _iso(nueva)}
    await booking._cancel_booking_core(fila, source="setter", reason="Pablo la mueve", request=request)
    _actualizar(lead_id, ahora, estado="ofrecido", booking_id="", cita_inicio="", motivo="Pablo la movió")
    if antes is not None:
        _avisar_a_pablo(_lead(lead_id), "🔁 Llamada anulada: %s" % (lead["negocio"] or lead["email"]),
                        "Le escribo para que elija otra hora.", inicio=antes, metodo="CANCEL")
    resultado = ofrecer(lead_id, "mover", clave="mover_%s" % secrets.token_hex(3), cuando_antes=antes,
                        esperar_turno=False)
    return {"ok": True, "enviado": resultado.get("enviado"), "motivo": resultado.get("motivo")}


def marcar_resultado(lead_id: str, resultado: str) -> Dict[str, Any]:
    """Tras la llamada, Pablo marca en un clic: ganado, seguir, perdido o no_vino (a quien no
    se presenta, Marta le ofrece moverla, UNA vez)."""
    from backend import booking

    lead = _lead(lead_id)
    if lead is None:
        return {"ok": False, "motivo": "no_existe"}
    ahora = timeutils._utc_now()
    fila = _cita(lead["booking_id"])
    if resultado == "no_vino":
        if fila is not None and fila["status"] in ("confirmed", "pending_review", "completed"):
            booking._update_booking_record(fila["id"], status="no_show", completed_source="manual")
            booking._record_booking_audit(fila["id"], AGENDA_ID, "booking_no_show", {"source": "setter"})
        antes = _dt(lead["cita_inicio"])
        if int(lead["rescate"] or 0) >= 1:
            _actualizar(lead_id, ahora, estado="cerrado", resultado="no_vino", motivo="No vino dos veces", proximo="")
            return {"ok": True, "enviado": False}
        _actualizar(lead_id, ahora, estado="ofrecido", rescate=1, booking_id="", cita_inicio="", motivo="No vino")
        envio = ofrecer(lead_id, "no_vino", clave="no_vino", cuando_antes=antes, esperar_turno=False)
        return {"ok": True, "enviado": envio.get("enviado")}
    if resultado not in RESULTADOS:
        return {"ok": False, "motivo": "resultado_desconocido"}
    if fila is not None and fila["status"] in ("confirmed", "pending_review"):
        booking._update_booking_record(fila["id"], status="completed", completed_source="manual")
    _actualizar(lead_id, ahora, estado="cerrado", resultado=resultado, proximo="", motivo="Resultado: " + resultado)
    _anotar_oportunidad(lead_id, {"ganado": "Ganado tras la llamada", "seguir": "Seguir tras la llamada",
                                  "perdido": "Perdido tras la llamada"}[resultado], ahora,
                        etapa=RESULTADOS[resultado], motivo_perdida="Tras la llamada" if resultado == "perdido" else "")
    return {"ok": True}


def parar_a_mano(lead_id: str) -> bool:
    lead = _lead(lead_id)
    if lead is None or lead["estado"] not in ESTADOS_VIVOS + ("solo_telefono",):
        return False
    _actualizar(lead_id, estado="parado", motivo="parado a mano", proximo="")
    return True


# --- La vuelta del hilo --------------------------------------------------------------------------

def _cadencia(ahora: datetime) -> int:
    """Los toques que tocan: el primero (al entrar) y los recordatorios (dias 3 y 6)."""
    if not esta_encendida():
        return 0
    with _conexion() as conn:
        filas = conn.execute("SELECT * FROM setter_leads WHERE estado IN ('pendiente', 'ofrecido') AND proximo<>'' "
                             "AND proximo <= ? ORDER BY proximo LIMIT 20", (_iso(ahora),)).fetchall()
    enviados = 0
    for lead in filas:
        if parar.is_set():
            break
        paso = int(lead["paso"] or 0) + 1
        if lead["estado"] == "pendiente":
            if not seguimiento_demo.es_laborable(_local(ahora).date()) or not (
                    VENTANA[0] <= _local(ahora).time() < VENTANA[1]):
                continue
            paso, plantilla = 1, "huecos"
        elif paso > len(CADENCIA):
            _actualizar(lead["id"], ahora, estado="sin_respuesta", proximo="", motivo="sin respuesta")
            _anotar_oportunidad(lead["id"], "Sin respuesta a Marta: decide tú", ahora)
            continue
        else:
            if not seguimiento_demo.en_ventana(ahora):
                continue
            plantilla = CADENCIA[paso - 1][1]
        resultado = ofrecer(lead["id"], plantilla, clave="paso%d" % paso, ahora=ahora)
        if resultado.get("enviado"):
            enviados += 1
        elif resultado.get("motivo") == "agenda_llena":
            _actualizar(lead["id"], ahora, proximo=_iso(ahora + timedelta(hours=2)))
    return enviados


def _seguir_citas(ahora: datetime) -> Dict[str, int]:
    """Las citas agendadas: cambios hechos por el lead (cancelo o movio desde su enlace), el SMS
    2 horas antes (solo a moviles, con Marta encendida), la ficha a Pablo 30 minutos antes y,
    pasada la hora, "celebrada" hasta que Pablo marque el resultado."""
    from backend import booking

    salida = {"sms": 0, "fichas": 0, "cambios": 0}
    with _conexion() as conn:
        filas = conn.execute("SELECT * FROM setter_leads WHERE estado='reservado'").fetchall()
    for lead in filas:
        fila = _cita(lead["booking_id"])
        if fila is None or fila["status"] == "cancelled":
            _actualizar(lead["id"], ahora, estado="cancelada", motivo="Canceló la llamada", proximo="")
            antes = _dt(lead["cita_inicio"])
            _avisar_a_pablo(lead, "❌ Ha cancelado la llamada: %s" % (lead["negocio"] or lead["email"]),
                            "Ha cancelado la llamada desde su enlace. No le escribo más: decide tú.",
                            inicio=antes, metodo="CANCEL")
            salida["cambios"] += 1
            continue
        inicio = _dt(fila["start_at"]) or _dt(lead["cita_inicio"])
        if inicio is None:
            continue
        if _iso(inicio) != lead["cita_inicio"]:
            _actualizar(lead["id"], ahora, cita_inicio=_iso(inicio), secuencia=int(lead["secuencia"] or 0) + 1,
                        sms_en="", ficha_en="")
            lead = _lead(lead["id"])
            _avisar_a_pablo(lead, "🔁 Ha movido la llamada: %s, %s" % (lead["negocio"] or lead["email"],
                                                                       dia_y_hora(inicio)),
                            "La ha movido desde su enlace al %s." % dia_y_hora(inicio), inicio=inicio)
            salida["cambios"] += 1
        falta = inicio - ahora
        telefono = fila["telefono"] or lead["telefono"]
        if (esta_encendida() and not lead["sms_en"] and timedelta(0) < falta <= timedelta(hours=HORAS_SMS)
                and captacion_voz.es_movil(telefono)):
            if _reservar_toque(lead["id"], "sms_%s" % lead["secuencia"], ahora):
                texto = textnorm._strip_accents(
                    "Hola, soy Pablo de Vantelia. Te llamo hoy a las %s (15 min). Si no te viene bien, cambiala aqui: %s"
                    % (_local(inicio).strftime("%H:%M"), booking._build_booking_manage_url(fila["manage_token"])))
                ok = captacion_voz._mandar_sms(telefono, texto)
                _apuntar_toque(lead["id"], "sms_%s" % lead["secuencia"], "enviado" if ok else "incierto", ahora)
                salida["sms"] += 1
            _actualizar(lead["id"], ahora, sms_en=_iso(ahora))
        if not lead["ficha_en"] and timedelta(0) < falta <= timedelta(minutes=MINUTOS_FICHA):
            _actualizar(lead["id"], ahora, ficha_en=_iso(ahora))
            _avisar_a_pablo(lead, "📞 En %d min: %s" % (max(1, int(falta.total_seconds() // 60)),
                                                       lead["negocio"] or lead["email"]),
                            "A las %s le llamas%s. Después marca el resultado en la oficina." % (
                                _local(inicio).strftime("%H:%M"), (" al " + telefono) if telefono else ""))
            salida["fichas"] += 1
        if ahora >= inicio + timedelta(minutes=DURACION):
            _actualizar(lead["id"], ahora, estado="celebrada")
    return salida


def ciclo(ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Una vuelta: senales de interes, cualificados nuevos, toques, citas y la oficina."""
    if not _cerrojo.acquire(blocking=False):
        return {"motivo": "ya_hay_una_vuelta"}
    try:
        ahora = ahora or timeutils._utc_now()
        salida: Dict[str, Any] = {}
        if esta_encendida():
            try:
                # Las del seguimiento van cada 10 minutos; aqui, cada minuto: un "me interesa"
                # no espera.
                seguimiento_demo.procesar_senales(ahora)
            except Exception:  # noqa: BLE001
                settings.logger.exception("[setter] no se pudieron leer las senales")
            salida["recogidos"] = recoger_cualificados(ahora)
        salida["enviados"] = _cadencia(ahora)
        salida["citas"] = _seguir_citas(ahora)
        return salida
    finally:
        _cerrojo.release()


def _trabajador() -> None:
    settings.logger.info("[setter] iniciada: una vuelta cada %s s.", SEGUNDOS_ENTRE_VUELTAS)
    parar.wait(90)
    while not parar.is_set():
        try:
            ciclo()
        except Exception:  # noqa: BLE001
            settings.logger.exception("[setter] error en la vuelta")
        try:
            from backend import oficina

            oficina.ciclo()
        except Exception:  # noqa: BLE001
            settings.logger.exception("[oficina] error en la vuelta")
        parar.wait(SEGUNDOS_ENTRE_VUELTAS)


def arrancar() -> Optional[threading.Thread]:
    """Asegura la agenda de Pablo y arranca el hilo (si hay captacion). Idempotente."""
    global hilo
    from backend import outreach

    if not outreach.OUTREACH_AVAILABLE:
        return None
    try:
        asegurar_agenda()
    except Exception:  # noqa: BLE001 - sin agenda, Marta no ofrece horas, pero lo demas sigue
        settings.logger.exception("[setter] no se pudo asegurar la agenda de Pablo")
    if hilo and hilo.is_alive():
        return hilo
    parar.clear()
    hilo = threading.Thread(target=_trabajador, name="vantelia-setter", daemon=True)
    hilo.start()
    return hilo


# --- Para la oficina ---------------------------------------------------------------------------

def _publico(lead) -> Dict[str, Any]:
    try:
        ofrecidas = json.loads(lead["ofrecidos"] or "[]")
    except ValueError:
        ofrecidas = []
    return {"id": lead["id"], "negocio": lead["negocio"] or lead["email"] or lead["telefono"],
            "nombre": lead["nombre"], "email": lead["email"], "telefono": lead["telefono"], "origen": lead["origen"],
            "estado": lead["estado"], "paso": int(lead["paso"] or 0), "proximo": lead["proximo"],
            "ofrecidos": ofrecidas, "cita_inicio": lead["cita_inicio"], "resultado": lead["resultado"],
            "motivo": lead["motivo"], "primer_contacto": lead["primer_contacto"], "creado": lead["creado"],
            "nota": lead["nota"][:300], "enlace": enlace(lead["id"])}


def resumen(ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Lo que pinta la oficina: los leads, las reuniones y los indicadores de Marta."""
    ahora = ahora or timeutils._utc_now()
    with _conexion() as conn:
        filas = conn.execute("SELECT * FROM setter_leads ORDER BY actualizado DESC LIMIT 200").fetchall()
    leads = [_publico(f) for f in filas]
    reuniones = sorted((l for l in leads if l["estado"] in ("reservado", "celebrada")),
                       key=lambda l: l["cita_inicio"] or "")
    hace30 = _iso(ahora - timedelta(days=30))
    recientes = [f for f in filas if (f["creado"] or "") >= hace30]
    minutos = [((_dt(f["primer_contacto"]) - _dt(f["creado"])).total_seconds() / 60.0)
               for f in recientes if f["primer_contacto"] and _dt(f["creado"])
               and f["origen"] not in ("seguimiento_previo", "respuesta")]
    con_reunion = [f for f in recientes if f["booking_id"] or f["resultado"] in ("ganado", "seguir", "perdido")
                   or f["estado"] in ("reservado", "celebrada")]
    celebradas = [f for f in recientes if f["resultado"] in ("ganado", "seguir", "perdido", "no_vino")]
    vinieron = [f for f in celebradas if f["resultado"] != "no_vino"]
    return {
        "encendida": esta_encendida(), "leads": leads, "reuniones": reuniones,
        "kpis": {"leads_30d": len(recientes),
                 "minutos_primer_contacto": round(sorted(minutos)[len(minutos) // 2], 1) if minutos else None,
                 "con_reunion_pct": round(len(con_reunion) * 100.0 / len(recientes), 1) if recientes else None,
                 "asistencia_pct": round(len(vinieron) * 100.0 / len(celebradas), 1) if celebradas else None,
                 "reuniones_semana": sum(1 for l in reuniones if l["cita_inicio"]
                                         and _dt(l["cita_inicio"]) and _dt(l["cita_inicio"]) <= ahora + timedelta(days=7))},
    }


def vista_previa(lead_id: str, ahora: Optional[datetime] = None) -> Dict[str, str]:
    """El primer correo tal como saldria ahora (con las horas de ahora), para la bandeja."""
    ahora = ahora or timeutils._utc_now()
    lead = _lead(lead_id)
    if lead is None:
        return {}
    hecho = contenido(lead, "huecos", elegir_dos(huecos(ahora), lead["preferencia"], ahora), ahora)
    return {"asunto": hecho["asunto"], "texto": hecho["texto"], "para": lead["email"]}
