"""La oficina de Vantelia: con que esta cada agente, la bandeja de Pablo, el presupuesto de
cada uno y los saldos de los proveedores (Tomas).

POR QUE EXISTE
--------------
Pablo (7-oct-2026) vio una "oficina de IA" en Instagram y pidio la suya: "que si alguno no
tiene nada que hacer vaya a por un cafe y no gaste tokens, pero que sea visual para saber
con que esta cada uno". Plan y razones: docs/PLAN_OFICINA_IA.md.

QUE ES Y QUE NO ES
------------------
- El ESTADO de cada agente sale de la base de datos y de los hilos vivos: pintar la sala no
  llama a ningun modelo. "Cafe" = no hay trabajo, y eso lo decide el codigo.
- Los agentes no charlan entre ellos. Lo que uno propone y necesita a Pablo va a la
  BANDEJA (`proponer`) y Pablo aprueba o rechaza desde la sala.
- Cada agente que usa el modelo tiene un PRESUPUESTO al mes (`hay_presupuesto`,
  `anotar_gasto`); al llegar al tope deja de llamarlo hasta el mes siguiente.
- Tomas mira los SALDOS sin IA (`revisar_saldos`): ElevenLabs, Twilio, OpenAI, Stripe y, si
  estan sus claves, Zadarma y Brevo. Solo avisa a Pablo si algo se va a acabar en menos de 7
  dias. Nunca paga ni recarga nada.

Las tablas (`oficina_*`) viven en la base de captacion, con su esquema
(scripts/outreach_campaign.py).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlencode

from backend import appstate, seguimiento_demo, settings, textnorm, timeutils

ZONA = seguimiento_demo.ZONA
TOPE_OFICINA_EUROS = 6.0
HORAS_ENTRE_SALDOS = 6
DIAS_PARA_AVISAR = 7
HORAS_ENTRE_AVISOS = 24
MINUTOS_TRABAJANDO = 10   # lo hecho hace menos de esto se pinta "trabajando"

# La plantilla. Los que ya trabajaban solo se dibujan; los nuevos llevan su presupuesto.
AGENTES: List[Dict[str, Any]] = [
    {"id": "sara", "nombre": "Sara", "rol": "Llamadas", "depto": "comercial", "icono": "📞"},
    {"id": "cartero", "nombre": "El Cartero", "rol": "Correo frío", "depto": "comercial", "icono": "✉️"},
    {"id": "seguimiento", "nombre": "Seguimiento", "rol": "Tras la demo", "depto": "comercial", "icono": "🔁"},
    {"id": "marta", "nombre": "Marta", "rol": "Setter", "depto": "comercial", "icono": "📅", "presupuesto": 1.0},
    {"id": "buzon", "nombre": "El Buzón", "rol": "Respuestas", "depto": "mantenimiento", "icono": "📬"},
    {"id": "vigilante", "nombre": "El Vigilante", "rol": "Salud del sistema", "depto": "mantenimiento", "icono": "🛡️"},
    {"id": "calidad", "nombre": "Calidad", "rol": "Conversaciones", "depto": "clientes", "icono": "🔎"},
    {"id": "tomas", "nombre": "Tomás", "rol": "Finanzas", "depto": "finanzas", "icono": "💶", "presupuesto": 0.5},
    {"id": "claude", "nombre": "Claude", "rol": "Programa", "depto": "ingenieria", "icono": "🛠️"},
    {"id": "astra", "nombre": "Astra", "rol": "Revisa", "depto": "ingenieria", "icono": "🧐"},
]
ESTADOS = ("trabajando", "cafe", "esperando", "fuera", "atascado", "sin_presupuesto")


@contextmanager
def _conexion() -> Iterator[Any]:
    with seguimiento_demo._conexion() as conn:
        yield conn


def _iso(momento: datetime) -> str:
    return seguimiento_demo._iso(momento)


def _dt(valor: Any) -> Optional[datetime]:
    return seguimiento_demo._dt(valor)


def _ajuste(clave: str, defecto: str = "") -> str:
    with _conexion() as conn:
        fila = conn.execute("SELECT valor FROM oficina_ajustes WHERE clave=?", (clave,)).fetchone()
    return str(fila[0]) if fila else defecto


def _guardar_ajuste(clave: str, valor: str) -> None:
    with _conexion() as conn:
        conn.execute("INSERT INTO oficina_ajustes (clave, valor) VALUES (?,?) ON CONFLICT(clave) DO UPDATE SET "
                     "valor=excluded.valor", (clave, valor))
        conn.commit()


def _inicio_del_dia(ahora: datetime) -> datetime:
    local = ahora.astimezone(ZONA)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _hace(momento: Optional[datetime], ahora: datetime) -> Optional[float]:
    return (ahora - momento).total_seconds() / 60.0 if momento else None


# --- Presupuesto --------------------------------------------------------------------------

def _mes(ahora: Optional[datetime] = None) -> str:
    return (ahora or timeutils._utc_now()).astimezone(ZONA).strftime("%Y-%m")


def gasto_del_mes(agente: str, ahora: Optional[datetime] = None) -> float:
    try:
        return float(_ajuste("gasto_%s_%s" % (agente, _mes(ahora)), "0") or 0)
    except ValueError:
        return 0.0


def gasto_total_del_mes(ahora: Optional[datetime] = None) -> float:
    return round(sum(gasto_del_mes(a["id"], ahora) for a in AGENTES if a.get("presupuesto")), 4)


def presupuesto(agente: str) -> float:
    for datos in AGENTES:
        if datos["id"] == agente:
            return float(datos.get("presupuesto") or 0)
    return 0.0


def hay_presupuesto(agente: str, ahora: Optional[datetime] = None) -> bool:
    """El agente puede llamar al modelo: no ha llegado a su tope del mes ni la oficina al suyo."""
    return (gasto_del_mes(agente, ahora) < presupuesto(agente)
            and gasto_total_del_mes(ahora) < TOPE_OFICINA_EUROS)


def anotar_gasto(agente: str, modelo: str, respuesta: Any, ahora: Optional[datetime] = None) -> float:
    """Suma lo que ha costado una llamada al modelo (por sus tokens) al gasto del mes."""
    from backend import trazas

    uso = getattr(respuesta, "usage", None)
    entrada = int(getattr(uso, "prompt_tokens", 0) or 0)
    salida = int(getattr(uso, "completion_tokens", 0) or 0)
    euros = trazas.coste_euros(modelo, entrada, salida)
    clave = "gasto_%s_%s" % (agente, _mes(ahora))
    with _conexion() as conn:
        conn.execute("INSERT INTO oficina_ajustes (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET "
                     "valor = CAST(CAST(valor AS REAL) + CAST(excluded.valor AS REAL) AS TEXT)",
                     (clave, "%.6f" % euros))
        conn.commit()
    return euros


# --- La bandeja de Pablo ------------------------------------------------------------------

def proponer(*, agente: str, tipo: str, ref: str = "", titulo: str, contexto: str = "",
             borrador: str = "") -> str:
    """Deja en la bandeja algo que necesita a Pablo. Una sola pendiente por (agente, tipo, ref):
    una segunda propuesta sobre lo mismo actualiza la primera."""
    ahora = _iso(timeutils._utc_now())
    with _conexion() as conn:
        fila = conn.execute("SELECT id FROM oficina_bandeja WHERE agente=? AND tipo=? AND ref=? AND estado='pendiente'",
                            (agente, tipo, ref)).fetchone()
        if fila is not None:
            conn.execute("UPDATE oficina_bandeja SET titulo=?, contexto=?, borrador=?, creado=? WHERE id=?",
                         (titulo[:300], contexto[:3000], borrador[:3000], ahora, fila["id"]))
            conn.commit()
            return fila["id"]
        propuesta = "bj_" + secrets.token_urlsafe(8)
        conn.execute("INSERT INTO oficina_bandeja (id, agente, tipo, ref, titulo, contexto, borrador, estado, creado) "
                     "VALUES (?,?,?,?,?,?,?, 'pendiente', ?)",
                     (propuesta, agente, tipo, ref, titulo[:300], contexto[:3000], borrador[:3000], ahora))
        conn.commit()
    return propuesta


def bandeja(estado: str = "pendiente", limite: int = 50) -> List[Dict[str, Any]]:
    from backend import setter

    with _conexion() as conn:
        filas = conn.execute("SELECT * FROM oficina_bandeja WHERE estado=? ORDER BY creado DESC LIMIT ?",
                             (estado, limite)).fetchall()
    salida = []
    for fila in filas:
        dato = dict(fila)
        if fila["agente"] == "marta" and fila["tipo"] == "primer_correo":
            dato["vista_previa"] = setter.vista_previa(fila["ref"])
        salida.append(dato)
    return salida


def resolver(propuesta_id: str, accion: str, texto: str = "", motivo: str = "") -> Dict[str, Any]:
    """Pablo aprueba (con el texto tal cual lo deja) o rechaza una propuesta."""
    from backend import setter

    if accion not in ("aprobar", "rechazar"):
        return {"ok": False, "motivo": "accion_desconocida"}
    ahora = _iso(timeutils._utc_now())
    with _conexion() as conn:
        conn.execute("BEGIN IMMEDIATE")
        fila = conn.execute("SELECT * FROM oficina_bandeja WHERE id=?", (propuesta_id,)).fetchone()
        if fila is None or fila["estado"] != "pendiente":
            conn.rollback()
            return {"ok": False, "motivo": "ya_resuelta"}
        conn.execute("UPDATE oficina_bandeja SET estado=?, motivo=?, resuelto=? WHERE id=?",
                     ("aprobada" if accion == "aprobar" else "rechazada", textnorm._sanitize_text(motivo)[:300],
                      ahora, propuesta_id))
        conn.commit()
    resultado: Dict[str, Any] = {"ok": True}
    if fila["agente"] == "marta":
        if accion == "aprobar":
            texto = textnorm._sanitize_text(texto or fila["borrador"], allow_multiline=True)[:3000]
            envio = setter.aprobar(fila["ref"], fila["tipo"], texto)
            resultado["enviado"] = bool(envio.get("enviado"))
            if not envio.get("enviado"):
                # No ha salido (buzon en pausa, agenda llena...): vuelve a la bandeja.
                with _conexion() as conn:
                    conn.execute("UPDATE oficina_bandeja SET estado='pendiente', resuelto='', motivo=? WHERE id=?",
                                 ("No salió: %s" % envio.get("motivo", ""), propuesta_id))
                    conn.commit()
                resultado.update(ok=False, motivo=envio.get("motivo", ""))
        else:
            setter.rechazar(fila["ref"], fila["tipo"])
    return resultado


# --- Tomas: los saldos ---------------------------------------------------------------------

def _apuntar_saldo(proveedor: str, valor: Optional[float], unidad: str, detalle: str, ahora: datetime) -> None:
    with _conexion() as conn:
        conn.execute("INSERT OR REPLACE INTO oficina_saldos (proveedor, momento, valor, unidad, detalle) "
                     "VALUES (?,?,?,?,?)", (proveedor, _iso(ahora), valor, unidad, detalle[:300]))
        conn.commit()


def _historial(proveedor: str, desde: datetime) -> List[Dict[str, Any]]:
    with _conexion() as conn:
        return [dict(f) for f in conn.execute("SELECT * FROM oficina_saldos WHERE proveedor=? AND momento >= ? "
                                              "AND valor IS NOT NULL ORDER BY momento", (proveedor, _iso(desde)))]


def dias_que_quedan(proveedor: str, ahora: Optional[datetime] = None) -> Optional[float]:
    """Al ritmo de gasto de los ultimos 7 dias (sacado de las lecturas guardadas). None si no
    hay datos o no baja."""
    ahora = ahora or timeutils._utc_now()
    lecturas = _historial(proveedor, ahora - timedelta(days=7))
    if len(lecturas) < 2:
        return None
    primera, ultima = lecturas[0], lecturas[-1]
    dias = ((_dt(ultima["momento"]) or ahora) - (_dt(primera["momento"]) or ahora)).total_seconds() / 86400.0
    gastado = float(primera["valor"]) - float(ultima["valor"])
    if dias < 0.5 or gastado <= 0:
        return None
    return round(float(ultima["valor"]) / (gastado / dias), 1)


def _leer_twilio(cliente) -> Dict[str, Any]:
    sid, token = settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN
    if not (sid and token):
        return {"estado": "sin_clave"}
    respuesta = cliente.get("https://api.twilio.com/2010-04-01/Accounts/%s/Balance.json" % sid, auth=(sid, token))
    respuesta.raise_for_status()
    datos = respuesta.json()
    return {"valor": float(datos.get("balance") or 0), "unidad": str(datos.get("currency") or "USD")}


def _leer_elevenlabs(_cliente) -> Dict[str, Any]:
    from backend import cuenta_elevenlabs

    if not settings.ELEVENLABS_API_KEY:
        return {"estado": "sin_clave"}
    estado = cuenta_elevenlabs.estado()
    limite, usados = int(estado.get("limite") or 0), int(estado.get("usados") or 0)
    return {"valor": float(max(0, limite - usados)), "unidad": "créditos",
            "detalle": "%s · %s" % (estado.get("plan") or "-", estado.get("problema") or estado.get("aviso") or "bien"),
            "ok": bool(estado.get("ok"))}


def _gasto_openai_trazas(desde: datetime) -> float:
    from backend import db

    try:
        with db._get_db_connection() as conn:
            fila = conn.execute("SELECT COALESCE(SUM(coste_euros), 0) FROM agent_turns WHERE created_at >= ?",
                                (desde.isoformat(),)).fetchone()
        return float(fila[0] or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def _gasto_openai_api(cliente, desde: datetime) -> Optional[float]:
    """El gasto real de la organizacion (Costs API). Solo con clave de administrador."""
    clave = os.getenv("OPENAI_ADMIN_KEY", "").strip()
    if not clave:
        return None
    respuesta = cliente.get("https://api.openai.com/v1/organization/costs?" + urlencode(
        {"start_time": int(desde.timestamp()), "limit": 31}), headers={"Authorization": "Bearer " + clave})
    respuesta.raise_for_status()
    total = 0.0
    for cubo in respuesta.json().get("data") or []:
        for linea in cubo.get("results") or []:
            total += float(((linea.get("amount") or {}).get("value")) or 0)
    return total


def _leer_openai(cliente, ahora: datetime) -> Dict[str, Any]:
    """El saldo de prepago de OpenAI no se puede leer por API: Pablo apunta lo que recarga y se
    le resta el gasto desde entonces (el real con la Costs API; si no, el del asistente)."""
    try:
        recarga = json.loads(_ajuste("recarga_openai", "{}") or "{}")
    except ValueError:
        recarga = {}
    desde = _dt(recarga.get("momento"))
    if not desde or not recarga.get("euros"):
        return {"estado": "sin_recarga"}
    real = None
    try:
        real = _gasto_openai_api(cliente, desde)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("[oficina] Costs API de OpenAI: %s", exc)
    gastado = real if real is not None else _gasto_openai_trazas(desde)
    return {"valor": round(float(recarga["euros"]) - gastado, 2), "unidad": "€ (aprox.)",
            "detalle": "recargaste %s € el %s; gastado %.2f (%s)" % (
                recarga["euros"], desde.astimezone(ZONA).strftime("%d/%m"), gastado,
                "real" if real is not None else "solo el asistente")}


def _leer_stripe(_cliente) -> Dict[str, Any]:
    if not settings.STRIPE_SECRET_KEY or settings.STRIPE_SECRET_KEY.startswith("sk_test_dummy"):
        return {"estado": "sin_clave"}
    import stripe

    saldo = stripe.Balance.retrieve(api_key=settings.STRIPE_SECRET_KEY)
    disponible = sum(int(x.get("amount") or 0) for x in (saldo.get("available") or []) if x.get("currency") == "eur")
    pendiente = sum(int(x.get("amount") or 0) for x in (saldo.get("pending") or []) if x.get("currency") == "eur")
    return {"valor": disponible / 100.0, "unidad": "€", "detalle": "pendiente de liquidar %.2f €" % (pendiente / 100.0),
            "sin_aviso": True}


def _firma_zadarma(metodo: str, parametros: Dict[str, Any], clave: str, secreto: str) -> str:
    """Firma de la API de Zadarma: HMAC-SHA1 de metodo + parametros + md5(parametros), en
    hexadecimal y luego en base64 (como su libreria oficial)."""
    texto = urlencode(sorted(parametros.items()))
    datos = metodo + texto + hashlib.md5(texto.encode("utf-8")).hexdigest()
    firma = hmac.new(secreto.encode("utf-8"), datos.encode("utf-8"), hashlib.sha1).hexdigest()
    return "%s:%s" % (clave, base64.b64encode(firma.encode("utf-8")).decode("ascii"))


def _leer_zadarma(cliente) -> Dict[str, Any]:
    clave, secreto = os.getenv("ZADARMA_API_KEY", "").strip(), os.getenv("ZADARMA_API_SECRET", "").strip()
    if not (clave and secreto):
        return {"estado": "sin_clave"}
    metodo = "/v1/info/balance/"
    respuesta = cliente.get("https://api.zadarma.com" + metodo,
                            headers={"Authorization": _firma_zadarma(metodo, {}, clave, secreto)})
    respuesta.raise_for_status()
    datos = respuesta.json()
    return {"valor": float(datos.get("balance") or 0), "unidad": str(datos.get("currency") or "EUR")}


def _leer_brevo(cliente) -> Dict[str, Any]:
    clave = os.getenv("BREVO_API_KEY", "").strip()
    if not clave:
        return {"estado": "sin_clave"}
    respuesta = cliente.get("https://api.brevo.com/v3/account", headers={"api-key": clave, "accept": "application/json"})
    respuesta.raise_for_status()
    planes = respuesta.json().get("plan") or []
    creditos = sum(float(p.get("credits") or 0) for p in planes if str(p.get("type") or "") != "sms")
    return {"valor": creditos, "unidad": "envíos", "detalle": ", ".join(str(p.get("type")) for p in planes)}


PROVEEDORES = (("elevenlabs", "ElevenLabs (voz de Sara)"), ("twilio", "Twilio (SMS)"), ("openai", "OpenAI"),
               ("zadarma", "Zadarma (línea de Sara)"), ("brevo", "Brevo (correo)"), ("stripe", "Stripe (cobros)"))


def revisar_saldos(ahora: Optional[datetime] = None, cliente=None) -> Dict[str, Any]:
    """Una pasada de Tomas, SIN modelo. Avisa a Pablo (una vez al dia por proveedor) si algo se
    acaba en menos de 7 dias."""
    import httpx

    ahora = ahora or timeutils._utc_now()
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=12.0)
    lectores = {"elevenlabs": _leer_elevenlabs, "twilio": _leer_twilio, "zadarma": _leer_zadarma,
                "brevo": _leer_brevo, "stripe": _leer_stripe, "openai": lambda c: _leer_openai(c, ahora)}
    salida: Dict[str, Any] = {}
    try:
        for proveedor, _ in PROVEEDORES:
            try:
                leido = lectores[proveedor](cliente)
            except Exception as exc:  # noqa: BLE001 - un proveedor caido no para a los demas
                leido = {"estado": "error", "detalle": textnorm._sanitize_text(str(exc))[:200]}
            if "valor" in leido:
                _apuntar_saldo(proveedor, leido["valor"], leido.get("unidad", ""), leido.get("detalle", ""), ahora)
                leido["dias"] = None if leido.get("sin_aviso") else dias_que_quedan(proveedor, ahora)
            salida[proveedor] = leido
    finally:
        if propio:
            cliente.close()
    _guardar_ajuste("tomas_ultima", _iso(ahora))
    _guardar_ajuste("tomas_saldos", json.dumps(salida, ensure_ascii=False, default=str))
    _avisar_si_se_acaba(salida, ahora)
    return salida


def _avisar_si_se_acaba(saldos: Dict[str, Any], ahora: datetime) -> int:
    from backend import outreach

    nombres = dict(PROVEEDORES)
    avisos = 0
    for proveedor, leido in saldos.items():
        dias = leido.get("dias")
        caida = proveedor == "elevenlabs" and leido.get("ok") is False
        if not caida and (dias is None or dias >= DIAS_PARA_AVISAR):
            continue
        if proveedor == "elevenlabs":
            continue  # su vigilante (cuenta_elevenlabs) ya avisa y rota de cuenta: no duplicar
        clave = "tomas_aviso_%s" % proveedor
        ultimo = _dt(_ajuste(clave))
        if ultimo and ahora - ultimo < timedelta(hours=HORAS_ENTRE_AVISOS):
            continue
        asunto = "💸 Tomás: a %s le quedan unos %s días" % (nombres.get(proveedor, proveedor), int(dias or 0))
        texto = ("Al ritmo de los últimos 7 días, %s se queda sin saldo en unos %s días.\n\nSaldo: %s %s\n%s\n\n"
                 "No he tocado nada: recargar es cosa tuya.\nOficina: %s/oficina\n" % (
                     nombres.get(proveedor, proveedor), int(dias or 0), leido.get("valor"), leido.get("unidad", ""),
                     leido.get("detalle", ""), (settings.APP_BASE_URL or "").rstrip("/")))
        try:
            if outreach._outreach_notify_admin(asunto, texto, ""):
                _guardar_ajuste(clave, _iso(ahora))
                avisos += 1
        except Exception:  # noqa: BLE001
            settings.logger.exception("[oficina] no se pudo avisar del saldo de %s", proveedor)
    return avisos


def apuntar_recarga(proveedor: str, euros: float, ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Pablo apunta una recarga (de OpenAI, que no deja leer el saldo por API)."""
    if proveedor != "openai" or not (0 < float(euros) < 100000):
        return {"ok": False}
    _guardar_ajuste("recarga_openai", json.dumps({"euros": round(float(euros), 2),
                                                  "momento": _iso(ahora or timeutils._utc_now())}))
    return {"ok": True}


def saldos_guardados() -> Dict[str, Any]:
    try:
        return json.loads(_ajuste("tomas_saldos", "{}") or "{}")
    except ValueError:
        return {}


# --- Con que esta cada uno (sin modelo) ----------------------------------------------------

def _estado(estado: str, bocadillo: str, **extra: Any) -> Dict[str, Any]:
    return dict({"estado": estado, "bocadillo": bocadillo}, **extra)


def _vivo(nombre: str) -> Optional[bool]:
    for hilo in appstate.worker_status():
        if hilo["name"] == nombre:
            return bool(hilo["alive"])
    return None


def _sara(conn, ahora: datetime) -> Dict[str, Any]:
    from backend import lanzador_llamadas

    hoy = _iso(_inicio_del_dia(ahora))
    llamadas = int(conn.execute("SELECT COUNT(*) FROM llamadas_voz WHERE creada >= ? AND origen <> 'manual'",
                                (hoy,)).fetchone()[0])
    ultima = conn.execute("SELECT MAX(creada) FROM llamadas_voz WHERE origen <> 'manual'").fetchone()[0]
    demos = int(conn.execute("SELECT COUNT(*) FROM llamadas_voz WHERE creada >= ? AND informacion='enviada'",
                             (hoy,)).fetchone()[0])
    kpis = {"llamadas_hoy": llamadas, "demos_hoy": demos}
    hace = _hace(_dt(ultima), ahora)
    if hace is not None and hace < MINUTOS_TRABAJANDO:
        return _estado("trabajando", "📞 Al teléfono: %d llamadas hoy" % llamadas, kpis=kpis)
    activo = bool(lanzador_llamadas.config().get("activo"))
    if not activo or _vivo("captacion-llamadas") is False:
        return _estado("fuera", "Llamadas apagadas", kpis=kpis)
    if lanzador_llamadas.en_horario(ahora):
        return _estado("cafe", "Entre llamadas (%d hoy)" % llamadas, kpis=kpis)
    return _estado("fuera", "Fuera de franja. Hoy: %d llamadas, %d demos" % (llamadas, demos), kpis=kpis)


def _cartero(conn, ahora: datetime) -> Dict[str, Any]:
    hoy = _iso(_inicio_del_dia(ahora))
    frios = int(conn.execute("SELECT COUNT(*) FROM sends WHERE sent_at >= ? AND mode='send' AND stage='cold'",
                             (hoy,)).fetchone()[0])
    total = int(conn.execute("SELECT COUNT(*) FROM sends WHERE sent_at >= ? AND mode='send'", (hoy,)).fetchone()[0])
    ultima = conn.execute("SELECT MAX(sent_at) FROM sends WHERE mode='send' AND stage IN ('cold', 'fu1', 'fu2', "
                          "'breakup')").fetchone()[0]
    fila = conn.execute("SELECT enabled, paused_until, paused_reason FROM autopilot_config WHERE id=1").fetchone()
    kpis = {"frios_hoy": frios, "correos_hoy": total}
    if fila is not None and fila["paused_until"] and (_dt(fila["paused_until"]) or ahora) > ahora:
        return _estado("fuera", "En pausa hasta el %s" % _dt(fila["paused_until"]).astimezone(ZONA).strftime("%d/%m %H:%M"),
                       kpis=kpis)
    if fila is None or not fila["enabled"]:
        return _estado("fuera", "Piloto apagado", kpis=kpis)
    hace = _hace(_dt(ultima), ahora)
    if hace is not None and hace < MINUTOS_TRABAJANDO:
        return _estado("trabajando", "✉️ Enviando: %d en frío hoy" % frios, kpis=kpis)
    return _estado("cafe", "%d en frío hoy" % frios if frios else "Hoy aún no le toca", kpis=kpis)


def _seguimiento(conn, ahora: datetime) -> Dict[str, Any]:
    activos = int(conn.execute("SELECT COUNT(*) FROM seguimiento_demo WHERE estado='activo'").fetchone()[0])
    cualificados = int(conn.execute("SELECT COUNT(*) FROM seguimiento_demo WHERE estado='cualificado' "
                                    "AND cualificado_en >= ?", (_iso(ahora - timedelta(days=30)),)).fetchone()[0])
    ultima = conn.execute("SELECT MAX(momento) FROM seguimiento_demo_toques").fetchone()[0]
    kpis = {"en_seguimiento": activos, "cualificados_30d": cualificados}
    if not seguimiento_demo.esta_encendido():
        return _estado("fuera", "Apagado", kpis=kpis)
    hace = _hace(_dt(ultima), ahora)
    if hace is not None and hace < MINUTOS_TRABAJANDO:
        return _estado("trabajando", "Escribiendo tras la demo", kpis=kpis)
    return _estado("cafe", "%d negocios en seguimiento" % activos if activos else "Nadie esperando", kpis=kpis)


def _marta(conn, ahora: datetime) -> Dict[str, Any]:
    from backend import setter

    pendientes = int(conn.execute("SELECT COUNT(*) FROM oficina_bandeja WHERE agente='marta' AND estado='pendiente'"
                                  ).fetchone()[0])
    vivos = conn.execute("SELECT estado, COUNT(*) n FROM setter_leads GROUP BY estado").fetchall()
    cuenta = {f["estado"]: int(f["n"]) for f in vivos}
    ultima = conn.execute("SELECT MAX(momento) FROM setter_toques WHERE estado IN ('enviado', 'incierto')").fetchone()[0]
    kpis = {"esperando_hora": cuenta.get("ofrecido", 0), "reservadas": cuenta.get("reservado", 0),
            "por_aprobar": pendientes, "gasto_mes": round(gasto_del_mes("marta", ahora), 3)}
    if not setter.esta_encendida():
        return _estado("fuera", "Apagada (enciéndela en la oficina)", kpis=kpis)
    if not hay_presupuesto("marta", ahora):
        return _estado("sin_presupuesto", "Tope del mes alcanzado", kpis=kpis)
    hace = _hace(_dt(ultima), ahora)
    if hace is not None and hace < MINUTOS_TRABAJANDO:
        return _estado("trabajando", "📅 Agendando", kpis=kpis)
    if pendientes:
        return _estado("esperando", "Te espera: %d por aprobar" % pendientes, kpis=kpis)
    if cuenta.get("ofrecido"):
        return _estado("cafe", "Esperando a que %d elijan hora" % cuenta["ofrecido"], kpis=kpis)
    return _estado("cafe", "Ningún interesado nuevo", kpis=kpis)


def _buzon(conn, ahora: datetime) -> Dict[str, Any]:
    hoy = _iso(_inicio_del_dia(ahora))
    respuestas = int(conn.execute("SELECT COUNT(*) FROM events WHERE type='reply' AND ts >= ?", (hoy,)).fetchone()[0])
    ultima = conn.execute("SELECT MAX(ts) FROM events WHERE type='reply'").fetchone()[0]
    kpis = {"respuestas_hoy": respuestas}
    if _vivo("outreach-imap") is False:
        return _estado("atascado", "El lector de correo no está en marcha", kpis=kpis)
    hace = _hace(_dt(ultima), ahora)
    if hace is not None and hace < MINUTOS_TRABAJANDO:
        return _estado("trabajando", "📬 Ha llegado una respuesta", kpis=kpis)
    return _estado("cafe", "%d respuestas hoy" % respuestas if respuestas else "Sin respuestas nuevas", kpis=kpis)


def _vigilante(_conn, _ahora: datetime) -> Dict[str, Any]:
    from backend import emailing, rag

    ia = rag._ia_health_cached()
    correo = dict(getattr(emailing, "_smtp_health_cache", {}) or {})
    problemas = []
    if ia.get("ok") is False:
        problemas.append("OpenAI: %s" % (ia.get("error") or "no responde")[:80])
    if correo.get("ok") is False:
        problemas.append("Correo: %s" % (correo.get("error") or "no responde")[:80])
    caidos = [h["name"] for h in appstate.worker_status() if not h["alive"]]
    if caidos:
        problemas.append("Hilos parados: " + ", ".join(caidos[:4]))
    if problemas:
        return _estado("atascado", "; ".join(problemas))
    return _estado("cafe", "Todo en orden")


def _calidad(_conn, ahora: datetime) -> Dict[str, Any]:
    from backend import db

    try:
        with db._get_db_connection() as conn:
            marcadas = int(conn.execute("SELECT COUNT(*) FROM conversation_reviews WHERE atendida=0 AND created_at >= ?",
                                        ((ahora - timedelta(days=1)).isoformat(),)).fetchone()[0])
    except Exception:  # noqa: BLE001
        marcadas = 0
    if marcadas:
        return _estado("esperando", "%d conversaciones raras en 24 h" % marcadas, kpis={"marcadas_24h": marcadas})
    return _estado("cafe", "Ninguna conversación rara", kpis={"marcadas_24h": 0})


def _tomas(_conn, ahora: datetime) -> Dict[str, Any]:
    saldos = saldos_guardados()
    ultima = _dt(_ajuste("tomas_ultima"))
    justos = [p for p, d in saldos.items() if d.get("dias") is not None and d["dias"] < DIAS_PARA_AVISAR]
    if justos:
        return _estado("atascado", "Saldo justo: " + ", ".join(justos), saldos=saldos)
    if ultima is None:
        return _estado("cafe", "Aún no ha mirado los saldos", saldos=saldos)
    return _estado("cafe", "Saldos mirados a las %s" % ultima.astimezone(ZONA).strftime("%H:%M"), saldos=saldos)


def _sincronia() -> Dict[str, Any]:
    try:
        guardado = json.loads((settings.STORAGE_DIR / "sincronia.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    foto = guardado.get("foto") if isinstance(guardado, dict) else None
    return {a.get("id"): a for a in ((foto or {}).get("agentes") or []) if isinstance(a, dict)}


def _ingeniero(agente: str, ahora: datetime) -> Dict[str, Any]:
    datos = _sincronia().get(agente)
    if not datos:
        return _estado("fuera", "Sin noticias (el PC no manda la foto)")
    if datos.get("sin_creditos"):
        hasta = _dt(datos.get("creditos_hasta"))
        return _estado("sin_presupuesto", "Sin créditos" + (" hasta las %s" % hasta.astimezone(ZONA).strftime("%H:%M")
                                                            if hasta else ""))
    hace = _hace(_dt(datos.get("ultima_actividad")), ahora)
    if hace is not None and hace < MINUTOS_TRABAJANDO:
        return _estado("trabajando", "Trabajando en el código" if agente == "claude" else "Revisando")
    return _estado("cafe", "Esperando encargo")


def estado(ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Todo lo que pinta la sala. No llama a ningun modelo."""
    from backend import setter

    ahora = ahora or timeutils._utc_now()
    calculos = {"sara": _sara, "cartero": _cartero, "seguimiento": _seguimiento, "marta": _marta, "buzon": _buzon,
                "vigilante": _vigilante, "calidad": _calidad, "tomas": _tomas}
    agentes = []
    with _conexion() as conn:
        for datos in AGENTES:
            try:
                if datos["id"] in ("claude", "astra"):
                    situacion = _ingeniero(datos["id"], ahora)
                else:
                    situacion = calculos[datos["id"]](conn, ahora)
            except Exception as exc:  # noqa: BLE001 - un agente que no se puede leer no tumba la sala
                settings.logger.warning("[oficina] estado de %s: %s", datos["id"], exc)
                situacion = _estado("atascado", "No he podido leer su estado")
            fuera_de_hora = not seguimiento_demo.es_laborable(ahora.astimezone(ZONA).date()) or not (
                8 <= ahora.astimezone(ZONA).hour < 21)
            if situacion["estado"] == "cafe" and fuera_de_hora:
                situacion["estado"] = "fuera"
            agentes.append(dict(datos, **situacion, gasto_mes=round(gasto_del_mes(datos["id"], ahora), 3)
                                if datos.get("presupuesto") else None))
    marta = setter.resumen(ahora)
    return {"ahora": _iso(ahora), "agentes": agentes, "bandeja": bandeja(), "reuniones": marta["reuniones"],
            "setter": {"encendida": marta["encendida"], "kpis": marta["kpis"],
                       "leads": [l for l in marta["leads"] if l["estado"] not in ("reservado", "celebrada")][:60]},
            "gasto": {"mes": gasto_total_del_mes(ahora), "tope": TOPE_OFICINA_EUROS},
            "proveedores": [{"id": p, "nombre": n, **(saldos_guardados().get(p) or {"estado": "sin_leer"})}
                            for p, n in PROVEEDORES]}


def escaparate(ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Lo mismo SIN un solo dato de clientes ni de prospectos (nombres, telefonos, correos,
    textos): solo agentes, estados y contadores. Para grabar la sala para redes."""
    completo = estado(ahora)
    agentes = []
    for a in completo["agentes"]:
        publico = {k: a[k] for k in ("id", "nombre", "rol", "depto", "icono", "estado")}
        publico["bocadillo"] = _sin_datos(a.get("bocadillo", ""))  # sin "|": AGENTS.md pide Python 3.8
        agentes.append(publico)
    return {"ahora": completo["ahora"], "agentes": agentes,
            "contadores": {"reuniones": len(completo["reuniones"]), "por_aprobar": len(completo["bandeja"])}}


def _sin_datos(texto: str) -> str:
    """Los bocadillos solo llevan cifras y frases fijas; por si acaso, fuera emails y numeros
    de telefono."""
    import re

    texto = re.sub(r"\S+@\S+", "…", str(texto or ""))
    return re.sub(r"\+?\d[\d\s]{7,}\d", "…", texto)


# --- La vuelta -------------------------------------------------------------------------------

def ciclo(ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """Lo que hace la oficina por su cuenta: hoy, solo Tomas mirando saldos cada 6 horas."""
    ahora = ahora or timeutils._utc_now()
    ultima = _dt(_ajuste("tomas_ultima"))
    if ultima is None or ahora - ultima >= timedelta(hours=HORAS_ENTRE_SALDOS):
        return {"saldos": revisar_saldos(ahora)}
    return {}
