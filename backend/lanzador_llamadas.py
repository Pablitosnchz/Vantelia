"""Lanzador automatico de las llamadas de captacion de Sara.

POR QUE EXISTE
--------------
`captacion_voz.llamar` marca UN telefono cuando se lo pide alguien. Este modulo elige
a quien llamar de la base de captacion y lo hace solo, poco a poco, dentro de unas
reglas que no dependen de lo que diga la agente. Apagado de serie.

TRES LLAVES, LAS TRES HACEN FALTA
---------------------------------
1. `CAPTACION_LLAMADAS_ENABLED=true` en el entorno del servidor (sin ella ni arranca
   el hilo).
2. El interruptor del panel (tabla `llamadas_config`, apagado al crearse).
3. Nada en `bloqueos()`: credenciales de la Lista Robinson, ElevenLabs, la agente
   creada y un numero espanol propio (`CAPTACION_TWILIO_NUMBER`: el de pruebas es de
   EEUU y un negocio no coge un +1).

REGLAS (Circular AEPD 1/2023 y sentido comun)
---------------------------------------------
- Lista Robinson ANTES de marcar (art. 4). Si la consulta falla, no se llama a
  nadie: sin respuesta de la lista no hay llamada. La respuesta vale 30 dias.
- Solo FIJOS (8xx/9xx). Un movil de negocio suele ser el de un autonomo, que la
  Circular trata como particular (art. 5): esos, a mano y con cuidado, no en lote.
- Nunca a quien pidio que no (`no_llamar`), ni a prospectos dados de baja, que ya
  respondieron, son clientes o se descartaron.
- Maximo 2 intentos por telefono, separados 2 dias, y solo si el primero no lo cogio
  nadie. Si hubo conversacion, no se vuelve a llamar solo.
- Nada de llamar a quien recibio un correo nuestro hace menos de 3 dias.
- De lunes a viernes, 10:00-12:30 y 16:00-18:00 (hora de Madrid): a primera hora y a
  mediodia estan con clientas. El lunes lo anadio Pablo (24-sep-2026); el criterio
  inicial lo dejaba fuera porque cierran muchas peluquerias, y a esas no les coge
  nadie: la llamada se queda en "no contesta" y cuenta como intento.
- Una llamada cada vez, con un hueco minimo entre dos (config) y un cupo diario.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, time, timedelta, timezone
from html import escape
from typing import Any, Callable, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8
    from backports.zoneinfo import ZoneInfo

from backend import (captacion_voz, clients, cuenta_elevenlabs, lista_robinson, settings, textnorm, timeutils,
                     voz_elevenlabs)

ZONA = ZoneInfo("Europe/Madrid")
DIAS_DE_LLAMADA = (0, 1, 2, 3, 4)  # lunes a viernes
FRANJAS = ((time(10, 0), time(12, 30)), (time(16, 0), time(18, 0)))
MAX_INTENTOS = 2
DIAS_ENTRE_INTENTOS = 2
DIAS_TRAS_UN_CORREO = 3
DIAS_QUE_VALE_ROBINSON = 30
MINUTOS_LLAMADA_VIVA = 15  # una llamada 'marcando'/'en_curso' mas vieja se da por muerta
MINUTOS_ENTRE_RONDAS = 5
ESTADOS_QUE_NO_SE_LLAMAN = ("replied", "client", "lost", "baja")
# Resultados que ACREDITAN que nadie hablo con Sara: solo con ellos se reintenta. Un
# resultado vacio no vale: una conversacion que acabo sin herramienta queda vacia y se
# volvia a llamar a los dos dias (revision de Astra, 24-sep-2026). Y con conversacion
# registrada no se reintenta nunca.
SIN_CONVERSACION = ("no_contesta", "ocupado", "contestador", "fallida")

CUPO_POR_DEFECTO = 8
MINUTOS_ENTRE_POR_DEFECTO = 12

parar = threading.Event()
hilo: Optional[threading.Thread] = None
_cerrojo = threading.Lock()


def _db():
    conn = captacion_voz._db()
    conn.execute("""CREATE TABLE IF NOT EXISTS llamadas_config (
        id INTEGER PRIMARY KEY CHECK (id = 1), activo INTEGER NOT NULL DEFAULT 0,
        cupo_diario INTEGER NOT NULL DEFAULT %d, minutos_entre INTEGER NOT NULL DEFAULT %d,
        ultima_ronda TEXT NOT NULL DEFAULT '', ultimo_motivo TEXT NOT NULL DEFAULT '',
        actualizada TEXT NOT NULL DEFAULT '')""" % (CUPO_POR_DEFECTO, MINUTOS_ENTRE_POR_DEFECTO))
    conn.execute("INSERT OR IGNORE INTO llamadas_config (id) VALUES (1)")
    conn.execute("""CREATE TABLE IF NOT EXISTS robinson_consultas (
        telefono TEXT PRIMARY KEY, en_lista INTEGER NOT NULL, consultado TEXT NOT NULL)""")
    conn.row_factory = sqlite3.Row
    return conn


def _iso(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).isoformat(timespec="seconds")


def config() -> Dict[str, Any]:
    with _db() as conn:
        return dict(conn.execute("SELECT * FROM llamadas_config WHERE id=1").fetchone())


def guardar_config(*, activo: Optional[bool] = None, cupo_diario: Optional[int] = None,
                   minutos_entre: Optional[int] = None) -> Dict[str, Any]:
    campos: Dict[str, Any] = {}
    if activo is not None:
        campos["activo"] = 1 if activo else 0
    if cupo_diario is not None:
        campos["cupo_diario"] = max(1, min(40, int(cupo_diario)))
    if minutos_entre is not None:
        campos["minutos_entre"] = max(5, min(120, int(minutos_entre)))
    if campos:
        with _db() as conn:
            conn.execute("UPDATE llamadas_config SET %s, actualizada=? WHERE id=1"
                         % ", ".join("%s=?" % c for c in campos),
                         tuple(campos.values()) + (_iso(timeutils._utc_now()),))
            conn.commit()
    return config()


def bloqueos() -> List[str]:
    """Lo que impide llamar aunque el interruptor este encendido. Vacio = puede."""
    faltan: List[str] = []
    if not settings.CAPTACION_LLAMADAS_ENABLED:
        faltan.append("CAPTACION_LLAMADAS_ENABLED no esta a 'true' en el servidor.")
    if not lista_robinson.configurada():
        faltan.append("Faltan las credenciales de la Lista Robinson (ROBINSON_API_KEY / ROBINSON_API_SECRET).")
    if not settings.CAPTACION_TWILIO_NUMBER:
        faltan.append("Falta el numero espanol de captacion (CAPTACION_TWILIO_NUMBER).")
    if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN):
        faltan.append("Twilio no esta configurado.")
    if not voz_elevenlabs.configurado():
        faltan.append("ElevenLabs no esta configurado.")
    elif not str((clients._get_client_config(captacion_voz.TENANT).get("voice") or {})
                 .get(captacion_voz.CLAVE_AGENTE) or ""):
        faltan.append("La agente de captacion no esta creada en ElevenLabs.")
    elif cuenta_elevenlabs.cambiando_de_cuenta():
        # A media rotacion la clave nueva puede no tener aun sus agentes.
        faltan.append("Cambiando de cuenta de voz.")
    else:
        # Cuenta sin plan o sin creditos: quien descolgase oiria colgar (cuenta_elevenlabs).
        cuenta = cuenta_elevenlabs.estado()
        if not cuenta["ok"]:
            faltan.append(cuenta["problema"])
    return faltan


def en_horario(ahora: datetime) -> bool:
    local = ahora.astimezone(ZONA)
    if local.weekday() not in DIAS_DE_LLAMADA:
        return False
    return any(desde <= local.time() < hasta for desde, hasta in FRANJAS)


def es_fijo(telefono: str) -> bool:
    return bool(re.fullmatch(r"\+34[89]\d{8}", captacion_voz.telefono_e164(telefono)))


def _inicio_del_dia(ahora: datetime) -> datetime:
    local = ahora.astimezone(ZONA)
    return datetime.combine(local.date(), time(0, 0), tzinfo=ZONA)


def candidatos(ahora: datetime, limite: int = 60) -> List[Dict[str, Any]]:
    """Negocios de la base de captacion a los que hoy se puede llamar, por orden."""
    hace_intentos = _iso(ahora - timedelta(days=DIAS_ENTRE_INTENTOS))
    hace_correo = _iso(ahora - timedelta(days=DIAS_TRAS_UN_CORREO))
    marcadores = ",".join("?" * len(ESTADOS_QUE_NO_SE_LLAMAN))
    with _db() as conn:
        prospectos = conn.execute(
            "SELECT p.email, p.business_name, p.niche, p.phone FROM prospects p "
            "WHERE COALESCE(p.phone, '') <> '' "
            "AND COALESCE(p.status, '') NOT IN (%s) "
            "AND NOT EXISTS (SELECT 1 FROM suppressions s WHERE s.email = p.email) "
            "AND NOT EXISTS (SELECT 1 FROM sends e WHERE e.email = p.email AND e.mode = 'send' "
            "                AND e.sent_at >= ?) "
            "ORDER BY p.created_at, p.email" % marcadores,
            ESTADOS_QUE_NO_SE_LLAMAN + (hace_correo,)).fetchall()
        vetados = {f["telefono"] for f in conn.execute("SELECT telefono FROM no_llamar")}
        intentos: Dict[str, List[sqlite3.Row]] = {}
        for fila in conn.execute("SELECT telefono, resultado, conversation_id, creada FROM llamadas_voz"):
            intentos.setdefault(fila["telefono"], []).append(fila)
        # Quien abrio (1) o pincho (2) en nuestros correos va antes: convierte mejor
        # que un fijo en frio (peticion de Pablo, 24-sep-2026).
        calor = {f["email"]: int(f["calor"] or 0) for f in conn.execute(
            "SELECT email, MAX(CASE type WHEN 'click' THEN 2 WHEN 'open' THEN 1 ELSE 0 END) AS calor "
            "FROM events GROUP BY email")}
    elegidos: List[Dict[str, Any]] = []
    vistos = set()
    for p in prospectos:
        telefono = captacion_voz.telefono_e164(p["phone"])
        if not telefono or telefono in vistos or telefono in vetados or not es_fijo(telefono):
            continue
        previos = intentos.get(telefono, [])
        if len(previos) >= MAX_INTENTOS:
            continue
        if any(f["resultado"] not in SIN_CONVERSACION or f["conversation_id"] for f in previos):
            continue
        if any(f["creada"] >= hace_intentos for f in previos):
            continue
        vistos.add(telefono)
        elegidos.append({"telefono": telefono, "negocio": p["business_name"] or "",
                         "sector": p["niche"] or "", "prospecto": p["email"] or "",
                         "intentos": len(previos), "calor": calor.get(p["email"], 0)})
    # Estable: primero los que nunca sonaron; dentro, los que se interesaron por el correo.
    elegidos.sort(key=lambda c: (c["intentos"], -c["calor"]))
    return elegidos[:limite]


# --- Rellamada dirigida a quien decide (docs/PLAN_HABLAR_CON_EL_RESPONSABLE.md) -------

HORAS_ANTES_DE_RELLAMAR = 2
_DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4}
_HORAS_HABLADAS = {"una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
                   "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12}


def cuando_esta(cuando: str) -> Dict[str, Any]:
    """"por las tardes", "el jueves a partir de las cuatro", "manana por la manana"...
    -> {franja: 0 (manana) | 1 (tarde) | None, dia: 0-4 | None, otro_dia: bool}."""
    texto = textnorm._strip_accents(str(cuando or "").lower())
    franja: Optional[int] = None
    if "tarde" in texto:
        franja = 1
    elif re.search(r"(por|de|a) la manana|primera hora|mediodia", texto):
        franja = 0
    else:
        hora = re.search(r"\b(\d{1,2})\b|\b(" + "|".join(_HORAS_HABLADAS) + r")\b", texto)
        if hora:
            numero = int(hora.group(1)) if hora.group(1) else _HORAS_HABLADAS[hora.group(2)]
            franja = 1 if (1 <= numero <= 7 or 13 <= numero <= 19) else 0 if 8 <= numero <= 12 else None
    dia = next((n for nombre, n in _DIAS.items() if nombre in texto), None)
    # "manana" suelto es el dia siguiente, no la franja de la manana.
    otro_dia = bool(re.search(r"\bmanana\b", re.sub(r"(por|de|a) la manana", "", texto)))
    return {"franja": franja, "dia": dia, "otro_dia": otro_dia}


def _franja_de(ahora: datetime) -> Optional[int]:
    local = ahora.astimezone(ZONA).time()
    return next((i for i, (desde, hasta) in enumerate(FRANJAS) if desde <= local < hasta), None)


def _rechazos_por_la_transcripcion() -> set:
    """Llamadas que la clasificacion de ElevenLabs dio por "rechazo" (la guarda el modulo de
    transcripciones cuando exista). Sin esa tabla, ninguna."""
    try:
        with _db() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='llamadas_transcripcion'"
                                ).fetchone():
                return set()
            filas = conn.execute("SELECT llamada_id, analisis_json FROM llamadas_transcripcion").fetchall()
    except sqlite3.Error:
        return set()
    rechazos = set()
    for fila in filas:
        if re.search(r'"desenlace"[^}]*"rechazo"', fila["analisis_json"] or ""):
            rechazos.add(fila["llamada_id"])
    return rechazos


def rellamadas_dirigidas(ahora: datetime) -> List[Dict[str, Any]]:
    """Llamadas en las que cogio alguien del equipo y dio el nombre de quien decide: se
    vuelve a llamar UNA vez, al fijo del negocio (nunca a un movil que dieran), en la
    franja y el dia que dijeron, y preguntando por esa persona."""
    hace_rato = _iso(ahora - timedelta(hours=HORAS_ANTES_DE_RELLAMAR))
    marcadores = ",".join("?" * len(ESTADOS_QUE_NO_SE_LLAMAN))
    with _db() as conn:
        filas = conn.execute(
            "SELECT l.* FROM llamadas_voz l "
            "WHERE l.origen = 'auto' AND l.interlocutor = 'empleado' AND l.responsable_nombre <> '' "
            "AND l.rellamada_de = '' AND l.resultado NOT IN ('no_llamar', 'interesado') AND l.creada <= ? "
            "AND NOT EXISTS (SELECT 1 FROM llamadas_voz r WHERE r.rellamada_de = l.id) "
            "AND NOT EXISTS (SELECT 1 FROM no_llamar n WHERE n.telefono = l.telefono) "
            "AND NOT EXISTS (SELECT 1 FROM suppressions s WHERE s.email = l.prospecto) "
            "AND NOT EXISTS (SELECT 1 FROM prospects p WHERE p.email = l.prospecto "
            "                AND COALESCE(p.status, '') IN (%s)) "
            "ORDER BY l.creada" % marcadores,
            (hace_rato,) + ESTADOS_QUE_NO_SE_LLAMAN).fetchall()
    rechazos = _rechazos_por_la_transcripcion()
    local = ahora.astimezone(ZONA)
    franja_actual = _franja_de(ahora)
    salida: List[Dict[str, Any]] = []
    for fila in filas:
        if fila["id"] in rechazos or not es_fijo(fila["telefono"]):
            continue
        preferencia = cuando_esta(fila["responsable_cuando"])
        if preferencia["franja"] is not None and preferencia["franja"] != franja_actual:
            continue
        if preferencia["dia"] is not None and preferencia["dia"] != local.weekday():
            continue
        dia_de_la_llamada = datetime.fromisoformat(fila["creada"]).astimezone(ZONA).date()
        if preferencia["otro_dia"] and local.date() <= dia_de_la_llamada:
            continue
        salida.append({"telefono": fila["telefono"], "negocio": fila["negocio"], "sector": fila["sector"],
                       "prospecto": fila["prospecto"], "responsable": fila["responsable_nombre"],
                       "rellamada_de": fila["id"], "intentos": 0, "calor": 0})
    return salida


def fuera_de_robinson(lista: List[Dict[str, Any]], ahora: datetime,
                      consultar: Callable[[List[str]], Dict[str, bool]] = None) -> List[Dict[str, Any]]:
    """Los candidatos que NO estan en la Lista Robinson. Lanza si no se puede saber."""
    consultar = consultar or lista_robinson.consultar
    vigente = _iso(ahora - timedelta(days=DIAS_QUE_VALE_ROBINSON))
    with _db() as conn:
        sabidos = {f["telefono"]: bool(f["en_lista"]) for f in conn.execute(
            "SELECT telefono, en_lista FROM robinson_consultas WHERE consultado >= ?", (vigente,))}
    pendientes = [c["telefono"] for c in lista if c["telefono"] not in sabidos]
    if pendientes:
        respuesta = consultar(pendientes)
        if set(respuesta) != set(pendientes) or not all(isinstance(v, bool) for v in respuesta.values()):
            raise RuntimeError("La Lista Robinson no contesto bien por todos los numeros.")
        with _db() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO robinson_consultas (telefono, en_lista, consultado) VALUES (?,?,?)",
                [(t, 1 if respuesta[t] else 0, _iso(ahora)) for t in pendientes])
            conn.commit()
        sabidos.update({t: bool(respuesta[t]) for t in pendientes})
    return [c for c in lista if sabidos.get(c["telefono"]) is False]


def _motivo(texto: str, ahora: datetime, llamada: str = "") -> Dict[str, Any]:
    with _db() as conn:
        conn.execute("UPDATE llamadas_config SET ultima_ronda=?, ultimo_motivo=? WHERE id=1",
                     (_iso(ahora), texto))
        conn.commit()
    return {"llamada": llamada, "motivo": texto}


def ronda(*, ahora: Optional[datetime] = None, llamar: Callable[..., Dict[str, Any]] = None,
          consultar: Callable[[List[str]], Dict[str, bool]] = None,
          reloj: Optional[Callable[[], datetime]] = None) -> Dict[str, Any]:
    """Una pasada: como mucho UNA llamada. Devuelve {llamada, motivo}.

    `ahora` fija la hora de toda la ronda (tests); sin ella, la hora se vuelve a mirar
    justo antes de marcar."""
    if not _cerrojo.acquire(blocking=False):
        return {"llamada": "", "motivo": "Ya hay una ronda en marcha."}
    try:
        reloj = reloj or ((lambda: ahora) if ahora else timeutils._utc_now)
        return _ronda(reloj, llamar or captacion_voz.llamar, consultar)
    finally:
        _cerrojo.release()


def _impedimento(ahora: datetime) -> str:
    """Lo que impide llamar AHORA, o "". Se mira al empezar la ronda y otra vez justo
    antes de marcar: la consulta a la Lista Robinson tarda, y en ese rato pueden apagar
    el lanzador, acabarse la franja o bajar el cupo (revision de Astra, 24-sep-2026)."""
    ajustes = config()
    if not ajustes["activo"]:
        return "Apagado en el panel."
    faltan = bloqueos()
    if faltan:
        return faltan[0]
    if not en_horario(ahora):
        return "Fuera de horario (lunes a viernes, 10:00-12:30 y 16:00-18:00)."
    with _db() as conn:
        hoy = conn.execute("SELECT COUNT(*) FROM llamadas_voz WHERE origen='auto' AND creada >= ?",
                           (_iso(_inicio_del_dia(ahora)),)).fetchone()[0]
        viva = conn.execute("SELECT 1 FROM llamadas_voz WHERE estado IN ('marcando', 'en_curso') "
                            "AND creada >= ?",
                            (_iso(ahora - timedelta(minutes=MINUTOS_LLAMADA_VIVA)),)).fetchone()
        ultima = conn.execute("SELECT MAX(creada) FROM llamadas_voz WHERE origen='auto'").fetchone()[0]
    if hoy >= int(ajustes["cupo_diario"]):
        return "Cupo de hoy cubierto (%d llamadas)." % hoy
    if viva:
        return "Hay una llamada en curso."
    if ultima and ultima > _iso(ahora - timedelta(minutes=int(ajustes["minutos_entre"]))):
        return "Esperando el hueco entre llamadas."
    return ""


def _ronda(reloj: Callable[[], datetime], llamar: Callable[..., Dict[str, Any]],
           consultar: Optional[Callable[[List[str]], Dict[str, bool]]]) -> Dict[str, Any]:
    ahora = reloj()
    if not config()["activo"]:
        return _motivo("Apagado en el panel.", ahora)
    if voz_elevenlabs.configurado():
        cuenta_elevenlabs.asegurar_cuenta()  # si la cuenta de voz cayo, pasa a otra de la reserva
    motivo = _impedimento(ahora)
    if motivo:
        return _motivo(motivo, ahora)
    # Primero las rellamadas a quien decide (ya hablamos con su negocio); luego, en frio.
    dirigidas = rellamadas_dirigidas(ahora)
    ya = {c["telefono"] for c in dirigidas}
    lista = dirigidas + [c for c in candidatos(ahora) if c["telefono"] not in ya]
    if not lista:
        return _motivo("No quedan negocios a los que llamar.", ahora)
    try:
        libres = fuera_de_robinson(lista, ahora, consultar)
    except Exception as exc:  # noqa: BLE001 - sin respuesta de la lista, no se llama
        settings.logger.warning("[lanzador_llamadas] Lista Robinson sin respuesta: %s", exc)
        return _motivo("La Lista Robinson no contesto: no se llama a nadie.", ahora)
    if not libres:
        return _motivo("Todos los candidatos estan en la Lista Robinson.", ahora)
    # Otra vez, con la hora de AHORA: lo de arriba pudo cambiar mientras contestaba Robinson.
    ahora = reloj()
    motivo = _impedimento(ahora)
    if motivo:
        return _motivo(motivo, ahora)
    elegido = libres[0]
    dirigida = {k: elegido[k] for k in ("responsable", "rellamada_de") if elegido.get(k)}
    try:
        hecho = llamar(elegido["telefono"], elegido["negocio"], elegido["sector"],
                       elegido["prospecto"], origen="auto", **dirigida)
    except Exception as exc:  # noqa: BLE001 - un fallo de Twilio no tumba el hilo
        error = cuenta_elevenlabs.censurar(exc)
        settings.logger.warning("[lanzador_llamadas] no se pudo llamar a %s: %s", elegido["telefono"], error)
        return _motivo("Fallo al llamar: %s" % error[:160], ahora)
    if not hecho.get("ok"):
        return _motivo("No se llamo a %s (%s)." % (elegido["negocio"] or elegido["telefono"],
                                                    hecho.get("motivo") or "sin motivo"), ahora)
    return _motivo("Llamando a %s." % (elegido["negocio"] or elegido["telefono"]), ahora,
                   str(hecho.get("llamada") or ""))


def fallo_de_voz(llamada_id: str, error: str) -> bool:
    """ElevenLabs no conecto una llamada que YA habian descolgado: el negocio oyo colgar.

    Si la culpa es de la cuenta (sin creditos, pago pendiente...) y hay otra en la reserva
    que funciona, la voz pasa a ella y el lanzador sigue (el correo del cambio lo cuenta).
    Si no, una llamada asi es peor que ninguna: el lanzador se apaga en el acto y se avisa
    a Pablo con el motivo y el estado de la cuenta (peticion de Pablo, 24-sep-2026:
    "mandame un email cuando dejemos de hacer llamadas por la suscripcion"). Devuelve si
    se aviso.
    """
    # El texto del error viene del proveedor: se censuran las claves antes de guardarlo,
    # mandarlo o escribirlo en el log (revision de Astra, 24-sep-2026).
    error = cuenta_elevenlabs.censurar(error)
    if llamada_id and captacion_voz._fila(llamada_id) is not None:
        captacion_voz._actualizar(llamada_id, estado="terminada", resultado="fallida",
                                  notas=("ElevenLabs: %s" % error)[:200])
    estaba_activo = bool(config()["activo"])
    cuenta = cuenta_elevenlabs.estado(fresco=True)
    if not cuenta["ok"] and cuenta.get("tipo") in cuenta_elevenlabs.CAIDA:
        cambio = cuenta_elevenlabs.rotar("Un negocio descolgo y la voz fallo (%s). %s"
                                         % (error[:200], cuenta.get("problema", "")))
        if cambio.get("rotada"):
            _motivo("Voz pasada a otra cuenta tras un fallo; sigue llamando.", timeutils._utc_now(), llamada_id)
            return True
    guardar_config(activo=False)
    _motivo("Apagado solo: ElevenLabs no conecto una llamada.", timeutils._utc_now(), llamada_id)
    if not estaba_activo:
        return False  # llamada de prueba: quien la hizo ya lo ha oido
    causa = cuenta.get("problema") or "La cuenta parece en orden; el fallo fue al conectar la llamada."
    texto = ("Sara ha dejado de llamar: un negocio descolgo y ElevenLabs no conecto la llamada.\n\n"
             "Error:  %s\nCuenta: %s\n\nEl lanzador se ha apagado solo. Cuando este arreglado, "
             "vuelve a encenderlo en el panel (Llamadas).\n" % (error[:300], causa))
    html = ("<div style='font-family:sans-serif'><h2 style='color:#dc2626'>Sara ha dejado de llamar</h2>"
            "<p>Un negocio descolgo y ElevenLabs no conecto la llamada.</p><p>Error: %s<br>Cuenta: %s</p>"
            "<p>El lanzador se ha apagado solo. Cuando este arreglado, vuelve a encenderlo en el panel "
            "(Llamadas).</p></div>" % (escape(error[:300]), escape(causa)))
    from backend import outreach

    try:
        outreach._outreach_notify_admin("📵 Sara ha dejado de llamar (ElevenLabs)", texto, html)
    except Exception:  # noqa: BLE001
        settings.logger.exception("[lanzador_llamadas] no se pudo avisar del fallo de voz")
        return False
    if cuenta.get("tipo"):
        cuenta_elevenlabs.marcar_avisado(cuenta["tipo"])  # un solo correo, no dos
    return True


def _trabajador() -> None:
    settings.logger.info("[lanzador_llamadas] iniciado: una ronda cada %s min.", MINUTOS_ENTRE_RONDAS)
    parar.wait(90)
    while not parar.is_set():
        try:
            ronda()
        except Exception:  # noqa: BLE001
            settings.logger.exception("[lanzador_llamadas] error en la ronda")
        parar.wait(MINUTOS_ENTRE_RONDAS * 60)


def arrancar() -> Optional[threading.Thread]:
    """Arranca el hilo si el servidor lo permite. Idempotente."""
    global hilo
    if not settings.CAPTACION_LLAMADAS_ENABLED:
        settings.logger.info("[lanzador_llamadas] apagado por entorno.")
        return None
    if hilo and hilo.is_alive():
        return hilo
    parar.clear()
    hilo = threading.Thread(target=_trabajador, name="vantelia-lanzador-llamadas", daemon=True)
    hilo.start()
    return hilo


def resumen(limite: int = 100) -> Dict[str, Any]:
    """Lo que ensena el panel: ajustes, que falta, como va hoy y las ultimas llamadas."""
    ahora = timeutils._utc_now()
    with _db() as conn:
        llamadas = [dict(f, con_quien=captacion_voz.con_quien_hablo(f)) for f in conn.execute(
            "SELECT id, telefono, negocio, sector, prospecto, estado, resultado, email, notas, origen, "
            "conversation_id, interlocutor, responsable_nombre, responsable_cuando, responsable_nota, "
            "rellamada_de, creada, actualizada FROM llamadas_voz ORDER BY creada DESC LIMIT ?",
            (max(1, min(500, limite)),))]
        hoy = conn.execute("SELECT origen, COUNT(*) FROM llamadas_voz WHERE creada >= ? GROUP BY origen",
                           (_iso(_inicio_del_dia(ahora)),)).fetchall()
        por_resultado = conn.execute(
            "SELECT resultado, COUNT(*) FROM llamadas_voz GROUP BY resultado").fetchall()
        no_llamar = conn.execute("SELECT COUNT(*) FROM no_llamar").fetchone()[0]
    return {
        "config": config(), "bloqueos": bloqueos(), "en_horario": en_horario(ahora),
        "cuenta_voz": cuenta_elevenlabs.estado() if voz_elevenlabs.configurado() else {},
        "cuentas_voz": cuenta_elevenlabs.cuentas() if voz_elevenlabs.configurado() else [],
        "hilo_vivo": bool(hilo and hilo.is_alive()),
        "hoy": {str(o or "manual"): n for o, n in hoy},
        "por_resultado": {str(r or "sin_resultado"): n for r, n in por_resultado},
        "no_llamar": no_llamar, "llamadas": llamadas,
    }
