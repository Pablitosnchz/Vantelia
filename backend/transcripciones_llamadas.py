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
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional

import httpx

from backend import captacion_voz, cuenta_elevenlabs, settings, timeutils

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
        return None
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
    with _db() as conn:
        if interlocutor in captacion_voz.INTERLOCUTORES:
            conn.execute("UPDATE llamadas_voz SET interlocutor=? WHERE id=? AND interlocutor=''",
                         (interlocutor, fila[0]))
        if nombre and nombre.lower() not in ("none", "null", "no", "desconocido"):
            conn.execute("UPDATE llamadas_voz SET responsable_nombre=? WHERE id=? AND responsable_nombre=''",
                         (nombre[:80], fila[0]))
        conn.commit()
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
            "WHERE l.conversation_id <> '' AND l.estado = 'terminada' AND l.actualizada <= ? "
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
            conversacion = _pedir(conversation_id, cliente)
            if conversacion and guardar(conversacion, "recogida"):
                guardadas += 1
                continue
            with _db() as conn:
                conn.execute(
                    "INSERT INTO llamadas_transcripcion_intentos (llamada_id, intentos, ultimo) VALUES (?, 1, ?) "
                    "ON CONFLICT(llamada_id) DO UPDATE SET intentos = intentos + 1, ultimo = excluded.ultimo",
                    (llamada_id, ahora.isoformat(timespec="seconds")))
                conn.commit()
    finally:
        if propio:
            cliente.close()
    return guardadas


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
