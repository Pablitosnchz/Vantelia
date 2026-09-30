"""Transcripciones de las llamadas de Sara, guardadas para analizarlas despues.

POR QUE EXISTE
--------------
Pablo (25-sep-2026): "quiero transcripcion de la llamada para posteriormente hacer un
analisis de ellas". Hasta ahora el panel leia la conversacion en vivo de ElevenLabs con
la clave activa: tras una rotacion de cuenta, las llamadas de la cuenta vieja ya no se
podian leer, y no quedaba nada nuestro para analizar. Ahora cada llamada con
conversacion deja en la base de captacion (tabla `llamadas_transcripcion`):

- los turnos (quien, texto, segundo y las herramientas que uso Sara),
- el resumen, la duracion y
- lo que ElevenLabs clasifica al terminar (`captacion_voz.DATOS_AL_TERMINAR`:
  interlocutor, desenlace, escucho_la_demo, responsable_nombre). El lanzador lo usa
  para no volver a llamar tras un rechazo; la segunda oportunidad, para elegir a quien
  escribir.

DOS CAMINOS, EL MISMO GUARDADO (`guardar`)
------------------------------------------
- Aviso de fin de llamada de ElevenLabs (`POST /voice/el-captacion/fin`), firmado con
  `ELEVENLABS_WEBHOOK_SECRET` (cabecera `ElevenLabs-Signature: t=...,v0=...`). Llega
  al colgar. Hay que darlo de alta en cada cuenta de ElevenLabs de la reserva.
- Recogida de respaldo (`recoger_pendientes`): las llamadas terminadas con conversacion
  y sin transcripcion se piden a la API probando TODAS las claves de la reserva (la
  conversacion vive en la cuenta en la que se hizo). La lanza el vigilante de la cuenta
  cada hora, y tambien la exportacion antes de exportar.

Exportacion: `GET /admin/captacion/llamadas/transcripciones.jsonl`, una llamada por linea.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

import httpx

from backend import captacion_voz, cuenta_elevenlabs, settings, textnorm, timeutils

API = "https://api.elevenlabs.io"
TOLERANCIA_FIRMA_SEGUNDOS = 30 * 60
MINUTOS_ANTES_DE_RECOGER = 10
MAX_INTENTOS = 24  # una vez por hora: un dia intentandolo
# Entre dos intentos de la misma llamada. Sin esto, cada descarga del JSONL gastaba un
# intento y veinticuatro descargas seguidas con ElevenLabs caido la daban por perdida en
# segundos (revision de Astra, 25-sep-2026). Algo menos de una hora para no saltarse la
# pasada horaria del vigilante por unos segundos de desfase.
MINUTOS_ENTRE_INTENTOS = 55
ESTADOS_TERMINADOS = ("done", "failed")
# Lo que ElevenLabs pone cuando un dato no salio en la conversacion.
_NADA = ("none", "null", "no", "desconocido", "n/a", "-")
# Desenlaces que solo se dan si hablo alguien: con ellos no se cree un "no hablo nadie".
DESENLACES_CON_PERSONA = ("interesado", "volver_a_llamar", "rechazo", "ocupado_sin_rechazo", "persona_equivocada")


def _es_no(valor: Any) -> bool:
    """Un false explicito (booleano o texto). Vacio o dudoso no es un no."""
    if isinstance(valor, bool):
        return not valor
    return str(valor or "").strip().lower() in ("false", "no")


def _db():
    conn = captacion_voz._db()
    conn.execute("""CREATE TABLE IF NOT EXISTS llamadas_transcripcion (
        llamada_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
        transcripcion_json TEXT NOT NULL DEFAULT '[]', resumen TEXT NOT NULL DEFAULT '',
        duracion_s INTEGER, analisis_json TEXT NOT NULL DEFAULT '{}', origen TEXT NOT NULL DEFAULT '',
        recibida TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS llamadas_transcripcion_intentos (
        llamada_id TEXT PRIMARY KEY, intentos INTEGER NOT NULL DEFAULT 0, ultimo TEXT NOT NULL DEFAULT '')""")
    conn.row_factory = sqlite3.Row
    return conn


# --- Firma del aviso de ElevenLabs -------------------------------------------------

def firma_valida(cuerpo: bytes, cabecera: str, secreto: str, ahora: Optional[float] = None) -> bool:
    """`ElevenLabs-Signature: t=<unix>,v0=<hex>` con v0 = HMAC-SHA256(secreto, "<t>.<cuerpo>")."""
    if not (secreto and cabecera):
        return False
    partes = dict(p.split("=", 1) for p in cabecera.split(",") if "=" in p)
    marca, recibida = partes.get("t", ""), partes.get("v0", "")
    if not (marca.isdigit() and recibida):
        return False
    if abs((ahora if ahora is not None else time.time()) - int(marca)) > TOLERANCIA_FIRMA_SEGUNDOS:
        return False
    esperada = hmac.new(secreto.encode(), marca.encode() + b"." + cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, recibida)


# --- Guardar una conversacion ----------------------------------------------------------

def _valor(dato: Any) -> Any:
    """ElevenLabs da cada dato recogido como {"value": ..., "rationale": ...}."""
    return dato.get("value") if isinstance(dato, dict) else dato


def _turnos(transcript: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    turnos = []
    for turno in transcript or []:
        texto = str(turno.get("message") or "").strip()
        herramientas = [str(t.get("tool_name") or "") for t in (turno.get("tool_calls") or []) if t.get("tool_name")]
        if not (texto or herramientas):
            continue
        entrada: Dict[str, Any] = {"quien": "agente" if turno.get("role") == "agent" else "persona",
                                   "texto": texto, "segundo": turno.get("time_in_call_secs")}
        if herramientas:
            entrada["herramientas"] = herramientas
        turnos.append(entrada)
    return turnos


def _entrante_de_sara(conversacion: Dict[str, Any]):
    """Una llamada que ENTRO al 91 y en la que Sara no uso ninguna herramienta no tiene ficha:
    se crea aqui para que su transcripcion llegue al panel (30-sep-2026). Solo si la
    conversacion es de Sara y entrante; cualquier otra se ignora como siempre."""
    from backend import clients

    try:
        voz = clients._get_client_config(captacion_voz.TENANT).get("voice") or {}
    except Exception:  # noqa: BLE001 - sin el tenant de Sara, solo cuenta el numero
        voz = {}
    agentes = {str(voz.get(c) or "") for c in (captacion_voz.CLAVE_AGENTE, captacion_voz.CLAVE_AGENTE_ENTRADA)} - {""}
    telefonica = (conversacion.get("metadata") or {}).get("phone_call") or {}
    # De Sara: su agente actual, o una llamada a SU 91 (tras cambiar de cuenta el aviso llega
    # con el agente viejo; el numero es el mismo en todas; revision de Astra, 30-sep-2026).
    numero_sara = captacion_voz.telefono_e164(settings.CAPTACION_SIP_NUMERO) if settings.CAPTACION_SIP_NUMERO else ""
    llamado = captacion_voz.telefono_e164(str(telefonica.get("agent_number") or "")) if telefonica.get(
        "agent_number") else ""
    if not (str(conversacion.get("agent_id") or "") in agentes or (numero_sara and llamado == numero_sara)):
        return None
    variables = ((conversacion.get("conversation_initiation_client_data") or {}).get("dynamic_variables") or {})
    entra = (str(telefonica.get("direction") or "").lower() == "inbound"
             or str(variables.get("sentido") or "") == "entrante")
    if not entra:
        return None
    quien = str(telefonica.get("external_number") or variables.get("system__caller_id") or "")
    # La hora real de la llamada, no la de ahora (la recogida puede llegar horas despues).
    inicio = (conversacion.get("metadata") or {}).get("start_time_unix_secs")
    try:
        cuando = datetime.fromtimestamp(int(inicio), tz=timezone.utc).isoformat(timespec="seconds") if inicio else ""
    except (TypeError, ValueError, OverflowError, OSError):
        cuando = ""
    return captacion_voz._fila_entrante(quien, str(conversacion.get("conversation_id") or ""), cuando)


def guardar(conversacion: Dict[str, Any], origen: str) -> Optional[str]:
    """Guarda la conversacion de ElevenLabs en su llamada. Devuelve el id de la llamada, o
    None si no es de ninguna llamada nuestra. Idempotente: la segunda vez la reemplaza."""
    conversation_id = str(conversacion.get("conversation_id") or "")
    if not conversation_id:
        return None
    # Solo lo terminado: una conversacion "processing" guardada como definitiva ya no se
    # volvia a recoger y se perdia su clasificacion final (revision de Astra, 25-sep-2026).
    if str(conversacion.get("status") or "done") not in ESTADOS_TERMINADOS:
        return None
    with _db() as conn:
        fila = conn.execute("SELECT id, interlocutor, responsable_nombre FROM llamadas_voz WHERE conversation_id=?",
                            (conversation_id,)).fetchone()
    if fila is None:
        entrante = _entrante_de_sara(conversacion)
        if entrante is None:
            return None
        fila = (entrante["id"], entrante["interlocutor"], entrante["responsable_nombre"])
    analisis = conversacion.get("analysis") or {}
    metadatos = conversacion.get("metadata") or {}
    datos = analisis.get("data_collection_results") or {}
    guardado = {
        "data_collection_results": datos,
        "evaluation_criteria_results": analisis.get("evaluation_criteria_results") or {},
        "call_successful": analisis.get("call_successful"),
        "termination_reason": metadatos.get("termination_reason"),
    }
    with _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO llamadas_transcripcion (llamada_id, conversation_id, transcripcion_json, "
            "resumen, duracion_s, analisis_json, origen, recibida) VALUES (?,?,?,?,?,?,?,?)",
            (fila[0], conversation_id, json.dumps(_turnos(conversacion.get("transcript")), ensure_ascii=False),
             str(analisis.get("transcript_summary") or ""), metadatos.get("call_duration_secs"),
             json.dumps(guardado, ensure_ascii=False), origen, timeutils._utc_now().isoformat(timespec="seconds")))
        conn.commit()
    # Si Sara no llamo a `anotar_responsable`, lo que clasifico ElevenLabs rellena el hueco.
    # La condicion "esta vacio" va en el propio UPDATE: decidir sobre la fila leida antes
    # pisaba lo que la herramienta escribiera entremedias (revision de Astra, 25-sep-2026).
    interlocutor = str(_valor(datos.get("interlocutor")) or "").strip().lower()
    nombre = str(_valor(datos.get("responsable_nombre")) or "").strip()
    # Cuando suele estar quien decide: el lanzador lo interpreta con `cuando_esta` y, si no
    # lo entiende, no rellama (28-sep-2026: Sara lo oyo y no llamo a `anotar_responsable`).
    cuando = textnorm._sanitize_text(str(_valor(datos.get("responsable_cuando")) or ""))[:120].strip()
    with _db() as conn:
        if interlocutor in captacion_voz.INTERLOCUTORES:
            conn.execute("UPDATE llamadas_voz SET interlocutor=? WHERE id=? AND interlocutor=''",
                         (interlocutor, fila[0]))
        if nombre and nombre.lower() not in _NADA:
            conn.execute("UPDATE llamadas_voz SET responsable_nombre=? WHERE id=? AND responsable_nombre=''",
                         (nombre[:80], fila[0]))
        if cuando and cuando.lower() not in _NADA:
            conn.execute("UPDATE llamadas_voz SET responsable_cuando=? WHERE id=? AND responsable_cuando=''",
                         (cuando, fila[0]))
        # Por SIP no hay aviso de Twilio que la cierre: la cierra su transcripcion terminada.
        conn.execute("UPDATE llamadas_voz SET estado='terminada', actualizada=? WHERE id=? "
                     "AND estado IN ('marcando', 'en_curso')",
                     (timeutils._utc_now().isoformat(timespec="seconds"), fila[0]))
        # Solo grabaciones, un menu de centralita o un buzon: nadie oyo a Sara. Cuenta como
        # contestador (sin conversacion): el lanzador la reintenta y no hay segunda
        # oportunidad por correo (29-sep-2026: 4 de las 10 primeras llamadas reales). Solo
        # con un "no" explicito y sin un desenlace que diga que si hablo alguien. Va antes
        # del respaldo: si no hablo nadie, no se manda nada aunque el analisis diga que si.
        desenlace = str(_valor(datos.get("desenlace")) or "").strip().lower()
        if _es_no(_valor(datos.get("hablo_una_persona"))) and desenlace not in DESENLACES_CON_PERSONA:
            conn.execute("UPDATE llamadas_voz SET resultado='contestador' WHERE id=? AND resultado=''", (fila[0],))
        conn.commit()
    # Lo que Sara dijo que mandaba y no mando. Como mucho una vez: este guardado se repite
    # (aviso y recogida) y el respaldo reclama su sello antes de enviar.
    try:
        captacion_voz.enviar_de_respaldo(fila[0], {k: _valor(v) for k, v in datos.items()})
    except Exception:  # noqa: BLE001 - el respaldo nunca tumba el guardado de la transcripcion
        settings.logger.exception("[transcripciones] fallo el respaldo de la llamada %s", fila[0])
    return fila[0]


# --- Recogida de respaldo ---------------------------------------------------------------

def _pedir(conversation_id: str, cliente: httpx.Client) -> Optional[Dict[str, Any]]:
    """La conversacion, probando todas las claves de la reserva (vive en su cuenta)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,80}", conversation_id or ""):
        return None  # va en la URL: nada que no tenga forma de id de conversacion
    for clave in cuenta_elevenlabs.claves():
        try:
            r = cliente.get("%s/v1/convai/conversations/%s" % (API, conversation_id),
                            headers={"xi-api-key": clave})
        except httpx.HTTPError as exc:
            # Una cuenta que no responde no impide probar las demas (revision de Astra).
            settings.logger.warning("[transcripciones] %s no se pudo pedir: %s", conversation_id,
                                    cuenta_elevenlabs.censurar(exc))
            continue
        if r.status_code == 200:
            return r.json()
    return None


def recoger_pendientes(*, cliente: Optional[httpx.Client] = None, limite: int = 20) -> int:
    """Baja las transcripciones que no llegaron por el aviso. Devuelve cuantas guardo.

    Primero las que nunca se intentaron y luego las que llevan mas tiempo sin intentarse:
    antes, veinte conversaciones que ya no existen ocupaban siempre el cupo y las nuevas no
    se recogian nunca (revision de Astra, 25-sep-2026). Tras MAX_INTENTOS se dejan."""
    ahora = timeutils._utc_now()
    corte = (ahora - timedelta(minutes=MINUTOS_ANTES_DE_RECOGER)).isoformat(timespec="seconds")
    reintento = (ahora - timedelta(minutes=MINUTOS_ENTRE_INTENTOS)).isoformat(timespec="seconds")
    with _db() as conn:
        pendientes = conn.execute(
            "SELECT l.id, l.conversation_id FROM llamadas_voz l "
            "LEFT JOIN llamadas_transcripcion_intentos i ON i.llamada_id = l.id "
            "WHERE l.conversation_id <> '' AND l.estado IN ('terminada', 'en_curso') AND l.actualizada <= ? "
            "AND COALESCE(i.intentos, 0) < ? AND COALESCE(i.ultimo, '') <= ? "
            "AND NOT EXISTS (SELECT 1 FROM llamadas_transcripcion t WHERE t.llamada_id = l.id) "
            "ORDER BY COALESCE(i.ultimo, ''), l.actualizada LIMIT ?",
            (corte, MAX_INTENTOS, reintento, max(1, limite))).fetchall()
    if not pendientes or not cuenta_elevenlabs.claves():
        return 0
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=20.0)
    guardadas = 0
    try:
        for llamada_id, conversation_id in pendientes:
            if not _reservar_intento(llamada_id, ahora, reintento):
                continue  # otra recogida (el vigilante, otra descarga) se la ha quedado
            conversacion = _pedir(conversation_id, cliente)
            if conversacion and guardar(conversacion, "recogida"):
                guardadas += 1
    finally:
        if propio:
            cliente.close()
    return guardadas


HORAS_BUSCANDO_ENTRANTES = 24
MAX_PAGINAS_POR_CUENTA = 10


NOMBRES_DE_SARA = (captacion_voz.NOMBRE_DEL_AGENTE, captacion_voz.NOMBRE_DEL_AGENTE_ENTRADA)


def _conversaciones_de_sara(cliente: httpx.Client, clave: str, agentes: Set[str], desde: int) -> List[str]:
    """Ids de las conversaciones recientes de Sara en una cuenta, todas las paginas (con tope).
    Suyas: sus agentes actuales (el de llamar y el que coge el 91) o una con su nombre (tras
    rotar, en la cuenta vieja el id es otro)."""
    ids: List[str] = []
    cursor = ""
    for _ in range(MAX_PAGINAS_POR_CUENTA):
        params: Dict[str, Any] = {"call_start_after_unix": desde, "page_size": 100}
        if cursor:
            params["cursor"] = cursor
        try:
            r = cliente.get("%s/v1/convai/conversations" % API, headers={"xi-api-key": clave}, params=params)
        except httpx.HTTPError as exc:
            settings.logger.warning("[transcripciones] no se pudieron buscar entrantes: %s", cuenta_elevenlabs.censurar(exc))
            break
        if r.status_code != 200:
            break
        datos = r.json() or {}
        for c in datos.get("conversations") or []:
            if str(c.get("agent_id") or "") in agentes or str(c.get("agent_name") or "") in NOMBRES_DE_SARA:
                ids.append(str(c.get("conversation_id") or ""))
        cursor = str(datos.get("next_cursor") or "")
        if not datos.get("has_more") or not cursor:
            break
    return [i for i in ids if i]


def recoger_entrantes(*, cliente: Optional[httpx.Client] = None, horas: int = HORAS_BUSCANDO_ENTRANTES) -> int:
    """Entrantes cuyo aviso de fin no llego y en las que Sara no uso herramientas: no tienen
    ficha, asi que `recoger_pendientes` no las ve (revision de Astra, 30-sep-2026). Se recorren
    las conversaciones recientes de Sara en TODAS las cuentas de la reserva (tras rotar, la
    entrante vive en la vieja) y se guardan las que falten; `guardar` solo les crea ficha si
    son entrantes a su 91. Devuelve cuantas guardo."""
    from backend import clients

    try:
        voz = clients._get_client_config(captacion_voz.TENANT).get("voice") or {}
    except Exception:  # noqa: BLE001 - sin el tenant de Sara no hay nada que buscar
        return 0
    agentes = {str(voz.get(c) or "") for c in (captacion_voz.CLAVE_AGENTE, captacion_voz.CLAVE_AGENTE_ENTRADA)} - {""}
    claves = cuenta_elevenlabs.claves()
    if not claves:
        return 0
    desde = int(timeutils._utc_now().timestamp()) - horas * 3600
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=20.0)
    guardadas = 0
    try:
        with _db() as conn:
            conocidas = {f[0] for f in conn.execute("SELECT conversation_id FROM llamadas_voz WHERE conversation_id <> ''")}
        vistas = set(conocidas)
        for clave in claves:
            for conversation_id in _conversaciones_de_sara(cliente, clave, agentes, desde):
                if conversation_id in vistas:
                    continue
                vistas.add(conversation_id)
                conversacion = _pedir(conversation_id, cliente)
                if conversacion and guardar(conversacion, "recogida"):
                    guardadas += 1
    finally:
        if propio:
            cliente.close()
    return guardadas


def _reservar_intento(llamada_id: str, ahora: datetime, reintento: str) -> bool:
    """Apunta el intento ANTES de pedir la conversacion, y solo si sigue tocando. Si se
    apuntaba despues, dos recogidas a la vez (el vigilante y una descarga del JSONL)
    elegian la misma llamada y gastaban varios intentos en el mismo minuto: veinticuatro
    descargas simultaneas la daban por perdida (revision de Astra, 25-sep-2026)."""
    with _db() as conn:
        apuntado = conn.execute(
            "INSERT INTO llamadas_transcripcion_intentos (llamada_id, intentos, ultimo) VALUES (?, 1, ?) "
            "ON CONFLICT(llamada_id) DO UPDATE SET intentos = intentos + 1, ultimo = excluded.ultimo "
            "WHERE llamadas_transcripcion_intentos.ultimo <= ? AND llamadas_transcripcion_intentos.intentos < ?",
            (llamada_id, ahora.isoformat(timespec="seconds"), reintento, MAX_INTENTOS))
        conn.commit()
        return apuntado.rowcount == 1


# --- Leer y exportar ------------------------------------------------------------------

def de_la_llamada(llamada_id: str) -> Optional[Dict[str, Any]]:
    """La transcripcion guardada de una llamada, en el formato del panel, o None."""
    with _db() as conn:
        fila = conn.execute("SELECT * FROM llamadas_transcripcion WHERE llamada_id=?", (llamada_id,)).fetchone()
    if fila is None:
        return None
    return {"estado": "done", "turnos": json.loads(fila["transcripcion_json"] or "[]"), "duracion": fila["duracion_s"],
            "resumen": fila["resumen"], "analisis": json.loads(fila["analisis_json"] or "{}")}


def leer(llamada_id: str, *, cliente: Optional[httpx.Client] = None) -> Optional[Dict[str, Any]]:
    """Para el panel: la guardada; si aun no esta, se pide (en cualquier cuenta) y se guarda."""
    guardada = de_la_llamada(llamada_id)
    if guardada is not None:
        return guardada
    fila = captacion_voz._fila(llamada_id)
    if fila is None or not fila["conversation_id"]:
        return None
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=20.0)
    try:
        conversacion = _pedir(fila["conversation_id"], cliente)
    finally:
        if propio:
            cliente.close()
    if not conversacion:
        return None
    if guardar(conversacion, "panel"):
        return de_la_llamada(llamada_id)
    # Aun sin terminar: se ensena tal cual, sin guardarla como definitiva.
    analisis = conversacion.get("analysis") or {}
    return {"estado": str(conversacion.get("status") or ""), "turnos": _turnos(conversacion.get("transcript")),
            "duracion": (conversacion.get("metadata") or {}).get("call_duration_secs"),
            "resumen": str(analisis.get("transcript_summary") or ""), "analisis": {}}


def exportar() -> Iterable[str]:
    """Una linea JSON por llamada: sus datos, la transcripcion y la clasificacion."""
    with _db() as conn:
        filas = conn.execute(
            "SELECT l.*, t.transcripcion_json, t.resumen, t.duracion_s, t.analisis_json, t.origen AS via "
            "FROM llamadas_voz l LEFT JOIN llamadas_transcripcion t ON t.llamada_id = l.id "
            "ORDER BY l.creada").fetchall()
    for fila in filas:
        registro = {k: fila[k] for k in fila.keys() if k not in ("transcripcion_json", "analisis_json")}
        registro["transcripcion"] = json.loads(fila["transcripcion_json"] or "[]")
        registro["analisis"] = json.loads(fila["analisis_json"] or "{}")
        yield json.dumps(registro, ensure_ascii=False) + "\n"
