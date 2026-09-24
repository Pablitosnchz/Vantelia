"""Las cuentas de ElevenLabs: vigilar la activa, pasar sola a otra si deja de servir y avisar.

POR QUE EXISTE
--------------
24-sep-2026: Pablo cancelo la suscripcion Creator ("lo que nos dure"), pidio que le
avisemos cuando se acabe y despues dio varias claves de cuentas para rotarlas cuando
una se quede sin creditos. Cuando una cuenta vuelve al plan gratuito, se queda sin
creditos, tiene un pago pendiente o se revoca su clave, la voz de Laura deja de sonar:
el negocio que descuelga una llamada de Sara oiria colgar. Por eso:

- `estado()` dice si una cuenta sirve (cache de 30 min por cuenta).
- `ELEVENLABS_API_KEYS` es la reserva de claves, en orden de preferencia. Si la activa
  cae, `rotar()` pasa a la primera que sirva, crea en ella los agentes (Sara y los de
  cada negocio; la voz de Laura se anade sola), borra los de la cuenta vieja y avisa a
  Pablo. La cuenta activa se guarda en `storage/` por su huella (nunca la clave) para
  que sobreviva a reinicios y despliegues.
- Un hilo revisa cada hora; el lanzador de llamadas tambien mira antes de marcar
  (`asegurar_cuenta`). Sin ninguna cuenta que sirva, Sara no llama y llega UN correo
  por problema cada 24 h (tambien con menos del 15 % de creditos).

PAGO PENDIENTE = CUENTA CAIDA (24-sep-2026)
-------------------------------------------
Una Creator cancelada seguia diciendo `tier: creator` con 300.000 creditos, pero con
`status: past_due` y una factura abierta ElevenLabs rechaza TODO uso ("Complete the
latest invoice to continue usage"). Mirar solo plan y creditos la daba por buena.
Esas cuentas se saltan al rotar.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from html import escape
from typing import Any, Callable, Dict, List, Optional

import httpx

from backend import settings

API = "https://api.elevenlabs.io"
AVISAR_POR_DEBAJO = 0.15
# Estados de la suscripcion en los que ElevenLabs no deja usar la voz. `past_due` solo
# cuenta con factura abierta (en el reintento de cobro puede seguir funcionando).
ESTADOS_SIN_PAGO = ("past_due", "unpaid", "incomplete", "incomplete_expired")
# Problemas que tumban la cuenta (y hacen rotar). "pocos" solo avisa.
CAIDA = ("clave", "pago", "gratis", "agotados")
MINUTOS_DE_CACHE = 30
MINUTOS_ENTRE_REVISIONES = 60
HORAS_ENTRE_AVISOS = 24

parar = threading.Event()
hilo: Optional[threading.Thread] = None
_cache: Dict[str, Dict[str, Any]] = {}
_avisados: Dict[str, float] = {}
_rotando = threading.Lock()


def huella(clave: str) -> str:
    """Como se nombra una cuenta en logs, panel y correos: nunca la clave."""
    return hashlib.sha256(clave.encode()).hexdigest()[:10] if clave else ""


def claves() -> List[str]:
    """La reserva, en orden de preferencia. La activa entra aunque no este en la lista."""
    lista = [c for c in settings.ELEVENLABS_API_KEYS if c]
    if settings.ELEVENLABS_API_KEY and settings.ELEVENLABS_API_KEY not in lista:
        lista.insert(0, settings.ELEVENLABS_API_KEY)
    return list(dict.fromkeys(lista))


def _consultar(cliente: Optional[httpx.Client], clave: str) -> Dict[str, Any]:
    """Lee la suscripcion. `tipo` identifica el aviso ("" = nada que avisar)."""
    if not clave:
        return {"ok": False, "tipo": "", "problema": "Falta ELEVENLABS_API_KEY.", "aviso": ""}
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=15.0)
    try:
        r = cliente.get(API + "/v1/user/subscription", headers={"xi-api-key": clave})
    except httpx.HTTPError as exc:
        # No saber no es lo mismo que estar caida: no se avisa ni se rota, pero tampoco se llama.
        return {"ok": False, "tipo": "", "problema": "No se pudo consultar ElevenLabs (%s)." % type(exc).__name__,
                "aviso": ""}
    finally:
        if propio:
            cliente.close()
    if r.status_code in (401, 403):
        texto = "ElevenLabs rechaza la clave: esta revocada o la cuenta ya no existe."
        return {"ok": False, "tipo": "clave", "problema": texto, "aviso": texto}
    if r.status_code >= 400:
        return {"ok": False, "tipo": "", "problema": "ElevenLabs respondio %s al consultar la cuenta." % r.status_code,
                "aviso": ""}
    datos = r.json() or {}
    usados = int(datos.get("character_count") or 0)
    limite = int(datos.get("character_limit") or 0)
    renueva = datos.get("next_character_count_reset_unix")
    salida: Dict[str, Any] = {
        "ok": True, "tipo": "", "problema": "", "aviso": "",
        "plan": str(datos.get("tier") or ""), "estado": str(datos.get("status") or ""),
        "usados": usados, "limite": limite,
        "renueva": datetime.fromtimestamp(int(renueva), timezone.utc).date().isoformat() if renueva else "",
    }
    if salida["estado"] in ESTADOS_SIN_PAGO and (datos.get("has_open_invoices") or salida["estado"] != "past_due"):
        texto = ("La suscripcion de ElevenLabs tiene un pago pendiente (%s): no deja usar la voz hasta pagar "
                 "la factura." % salida["estado"])
        salida.update(ok=False, tipo="pago", problema=texto, aviso=texto)
    elif salida["plan"] == "free":
        texto = "La cuenta de ElevenLabs ha vuelto al plan gratuito: sin plan de pago la voz de Laura no suena."
        salida.update(ok=False, tipo="gratis", problema=texto, aviso=texto)
    elif limite and usados >= limite:
        texto = "Se han gastado los creditos de ElevenLabs (%d de %d)." % (usados, limite)
        salida.update(ok=False, tipo="agotados", problema=texto, aviso=texto)
    elif limite and limite - usados < limite * AVISAR_POR_DEBAJO:
        salida.update(tipo="pocos", aviso="Quedan pocos creditos de ElevenLabs: %d de %d (se renuevan el %s)."
                      % (limite - usados, limite, salida["renueva"] or "?"))
    return salida


def estado(*, fresco: bool = False, cliente: Optional[httpx.Client] = None,
           clave: Optional[str] = None) -> Dict[str, Any]:
    """Como esta una cuenta (la activa si no se dice). `ok` = se puede usar. Nunca lanza."""
    clave = settings.ELEVENLABS_API_KEY if clave is None else clave
    cuenta = huella(clave)
    ahora = time.time()
    guardado = _cache.get(cuenta)
    if not fresco and guardado and ahora - guardado["_momento"] < MINUTOS_DE_CACHE * 60:
        return {k: v for k, v in guardado.items() if k != "_momento"}
    leido = _consultar(cliente, clave)
    leido["cuenta"] = cuenta
    _cache[cuenta] = dict(leido, _momento=ahora)
    return leido


def cuentas(cliente: Optional[httpx.Client] = None) -> List[Dict[str, Any]]:
    """Resumen de la reserva para el panel (sin claves)."""
    salida = []
    for clave in claves():
        e = estado(clave=clave, cliente=cliente)
        salida.append({"cuenta": huella(clave), "activa": clave == settings.ELEVENLABS_API_KEY, "ok": e["ok"],
                       "plan": e.get("plan", ""), "quedan": max(0, e.get("limite", 0) - e.get("usados", 0)),
                       "problema": e.get("problema") or e.get("aviso") or ""})
    return salida


# --- Cuenta activa entre reinicios ------------------------------------------------

def _ruta_activa():
    return settings.STORAGE_DIR / "elevenlabs_cuenta_activa.json"


def aplicar_activa_guardada() -> str:
    """Al arrancar: si una rotacion eligio otra cuenta de la reserva, se sigue con ella."""
    try:
        guardada = json.loads(_ruta_activa().read_text(encoding="utf-8")).get("cuenta", "")
    except (OSError, ValueError):
        return ""
    for clave in claves():
        if huella(clave) == guardada:
            settings.ELEVENLABS_API_KEY = clave
            return guardada
    return ""


def _guardar_activa(clave: str) -> None:
    try:
        _ruta_activa().parent.mkdir(parents=True, exist_ok=True)
        _ruta_activa().write_text(json.dumps({"cuenta": huella(clave), "desde": datetime.now(timezone.utc)
                                              .isoformat(timespec="seconds")}), encoding="utf-8")
    except OSError:
        settings.logger.exception("[cuenta_elevenlabs] no se pudo guardar la cuenta activa")


# --- Rotacion -------------------------------------------------------------------

def _agentes_guardados() -> List[str]:
    from backend import appstate

    ids = []
    for cfg in list(appstate.CONFIG_CLIENTES.values()):
        for campo, valor in ((cfg or {}).get("voice") or {}).items():
            if campo.startswith("elevenlabs_agent") and valor:
                ids.append(str(valor))
    return ids


def sincronizar_agentes() -> Dict[str, str]:
    """Crea (o actualiza) en la cuenta activa todos los agentes que tenemos guardados."""
    from backend import appstate, captacion_voz, voz_elevenlabs

    hechos: Dict[str, str] = {}
    for cliente_id, cfg in list(appstate.CONFIG_CLIENTES.items()):
        voz = (cfg or {}).get("voice") or {}
        if voz.get(captacion_voz.CLAVE_AGENTE):
            hechos["captacion (Sara)"] = captacion_voz.sincronizar_agente()["agent_id"]
        if voz.get("elevenlabs_agent_id") or voz.get("elevenlabs_agent_id_telefono"):
            hechos[cliente_id] = voz_elevenlabs.sincronizar_agente(cliente_id)["agent_id"]
    return hechos


def _borrar_agentes(clave: str, ids: List[str], cliente: Optional[httpx.Client] = None) -> int:
    """Quita los agentes (y sus tools) de la cuenta que se deja. Lo que falle, se queda."""
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=20.0)
    cabeceras = {"xi-api-key": clave}
    borrados = 0
    try:
        for agent_id in ids:
            try:
                r = cliente.get("%s/v1/convai/agents/%s" % (API, agent_id), headers=cabeceras)
                if r.status_code != 200:
                    continue
                prompt = ((r.json().get("conversation_config") or {}).get("agent") or {}).get("prompt") or {}
                if cliente.delete("%s/v1/convai/agents/%s" % (API, agent_id), headers=cabeceras).status_code < 400:
                    borrados += 1
                for tool_id in prompt.get("tool_ids") or []:
                    cliente.delete("%s/v1/convai/tools/%s" % (API, tool_id), headers=cabeceras, params={"force": "true"})
            except httpx.HTTPError:
                continue
    finally:
        if propio:
            cliente.close()
    return borrados


def rotar(motivo: str, *, cliente: Optional[httpx.Client] = None, destino: str = "",
          sincronizar: Optional[Callable[[], Dict[str, str]]] = None) -> Dict[str, Any]:
    """Pasa a `destino` o a la primera cuenta de la reserva que sirva. {rotada, de, a, agentes|motivo}."""
    if not _rotando.acquire(blocking=False):
        return {"rotada": False, "motivo": "Ya se esta cambiando de cuenta."}
    try:
        vieja = settings.ELEVENLABS_API_KEY
        opciones = [destino] if destino else claves()
        nueva = next((c for c in opciones if c != vieja and estado(fresco=True, cliente=cliente, clave=c)["ok"]), "")
        if not nueva:
            return {"rotada": False, "motivo": "No queda ninguna otra cuenta de ElevenLabs que funcione."}
        ids_viejos = _agentes_guardados()
        settings.ELEVENLABS_API_KEY = nueva
        _guardar_activa(nueva)
        try:
            agentes = (sincronizar or sincronizar_agentes)()
            error = ""
        except Exception as exc:  # noqa: BLE001 - la cuenta cambia igual; se avisa del fallo
            settings.logger.exception("[cuenta_elevenlabs] no se pudieron crear los agentes en la cuenta nueva")
            agentes, error = {}, str(exc)[:300]
        borrados = 0 if error else _borrar_agentes(vieja, [i for i in ids_viejos if i not in agentes.values()],
                                                   cliente=cliente)
        salida = {"rotada": True, "de": huella(vieja), "a": huella(nueva), "agentes": agentes,
                  "borrados": borrados, "error": error}
        settings.logger.warning("[cuenta_elevenlabs] voz pasada de %s a %s: %s", salida["de"], salida["a"], motivo)
        try:
            _correo_rotacion(motivo, salida, estado(clave=nueva, cliente=cliente))
        except Exception:  # noqa: BLE001
            settings.logger.exception("[cuenta_elevenlabs] no se pudo avisar del cambio de cuenta")
        return salida
    finally:
        _rotando.release()


def preferida_que_sirve(cliente: Optional[httpx.Client] = None) -> str:
    """La primera cuenta de la reserva (orden de preferencia) que funciona, o ""."""
    return next((c for c in claves() if estado(cliente=cliente, clave=c)["ok"]), "")


def asegurar_cuenta(cliente: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """La cuenta activa, o la siguiente de la reserva si la activa ha caido."""
    actual = estado(cliente=cliente)
    if actual["ok"] or actual.get("tipo") not in CAIDA:
        return actual
    if rotar(actual["problema"], cliente=cliente).get("rotada"):
        return estado(cliente=cliente)
    return actual


# --- Avisos ----------------------------------------------------------------------

def _correo_rotacion(motivo: str, salida: Dict[str, Any], nueva: Dict[str, Any]) -> None:
    from backend import outreach

    agentes = ", ".join("%s: %s" % (k, v) for k, v in salida["agentes"].items()) or "-"
    quedan = max(0, nueva.get("limite", 0) - nueva.get("usados", 0))
    texto = ("La voz ha pasado a otra cuenta de ElevenLabs.\n\nMotivo:  %s\nDe:      cuenta %s\nA:       cuenta %s "
             "(plan %s, quedan %s creditos)\nAgentes creados en la nueva: %s\nAgentes borrados de la vieja: %s\n%s\n"
             "No hace falta hacer nada. Si la cuenta vieja era de pago, revisa por que ha caido.\n"
             % (motivo, salida["de"], salida["a"], nueva.get("plan", "?"), quedan, agentes, salida["borrados"],
                ("\nOJO: no se pudieron crear los agentes: %s\n" % salida["error"]) if salida["error"] else ""))
    html = "<div style='font-family:sans-serif'><h2 style='color:#0891b2'>Voz pasada a otra cuenta</h2><pre style='white-space:pre-wrap'>%s</pre></div>" % escape(texto)
    outreach._outreach_notify_admin("🔁 ElevenLabs: voz pasada a otra cuenta", texto, html)


def _correo(leido: Dict[str, Any]) -> None:
    from backend import outreach

    if leido["tipo"] == "pocos":
        intro = ("Todavia funciona. Cuando se acabe, la voz pasara sola a la siguiente cuenta de "
                 "ELEVENLABS_API_KEYS que funcione (%d de %d funcionan ahora)." % (
                     sum(1 for c in cuentas() if c["ok"]), len(claves())))
        pasos = ""
    else:
        intro = "No queda ninguna otra cuenta de ELEVENLABS_API_KEYS que funcione. Mientras tanto Sara no llama a nadie."
        pasos = ("\nPara arreglarlo:\n"
                 "- Paga la factura pendiente en ElevenLabs (vuelve a funcionar sola), o\n"
                 "- Anade la clave de otra cuenta de pago a ELEVENLABS_API_KEYS en /srv/vantelia/.env y despliega:\n"
                 "  la voz pasara a ella sola y creara alli los agentes y la voz de Laura.")
    texto = "%s\n\n%s%s\n" % (leido["aviso"], intro, pasos)
    html = "<div style='font-family:sans-serif'><h2 style='color:#d97706'>%s</h2><pre style='white-space:pre-wrap'>%s</pre></div>" % (
        escape(leido["aviso"]), escape(intro + pasos))
    outreach._outreach_notify_admin("⚠️ ElevenLabs: " + leido["aviso"][:120], texto, html)


def marcar_avisado(tipo: str) -> None:
    """Otro aviso ya conto este problema (lanzador_llamadas.fallo_de_voz): no repetirlo."""
    _avisados[tipo] = time.time()


def vigilar_una_vez(*, cliente: Optional[httpx.Client] = None) -> str:
    """Revisa la cuenta activa: rota si ha caido y avisa si toca. Devuelve lo que hizo
    ("rotada", el tipo de aviso mandado, o "" si nada)."""
    leido = estado(fresco=True, cliente=cliente)
    tipo = leido.get("tipo") or ""
    if leido["ok"]:
        # Pablo (24-sep-2026): "usa la creator primero". Si una cuenta preferida vuelve a
        # funcionar (se pago su factura), la voz vuelve a ella.
        lista = claves()
        for clave in lista[:lista.index(settings.ELEVENLABS_API_KEY)] if settings.ELEVENLABS_API_KEY in lista else []:
            if estado(fresco=True, cliente=cliente, clave=clave)["ok"]:
                if rotar("Vuelve a funcionar una cuenta que va antes en el orden de preferencia.",
                         cliente=cliente, destino=clave).get("rotada"):
                    return "rotada"
                break
    if not tipo:
        return ""
    if tipo in CAIDA and rotar(leido["problema"], cliente=cliente).get("rotada"):
        return "rotada"
    ahora = time.time()
    if ahora - _avisados.get(tipo, 0) < HORAS_ENTRE_AVISOS * 3600:
        return ""
    try:
        _correo(leido)
    except Exception:  # noqa: BLE001 - el aviso nunca tumba el hilo
        settings.logger.exception("[cuenta_elevenlabs] no se pudo avisar: %s", leido.get("aviso"))
        return ""
    _avisados[tipo] = ahora
    settings.logger.warning("[cuenta_elevenlabs] aviso mandado: %s", leido.get("aviso"))
    return tipo


def _trabajador() -> None:
    parar.wait(120)
    while not parar.is_set():
        try:
            vigilar_una_vez()
        except Exception:  # noqa: BLE001
            settings.logger.exception("[cuenta_elevenlabs] error revisando la cuenta")
        parar.wait(MINUTOS_ENTRE_REVISIONES * 60)


def arrancar() -> Optional[threading.Thread]:
    """Arranca la vigilancia si hay alguna clave de ElevenLabs. Idempotente."""
    global hilo
    if not claves():
        return None
    if hilo and hilo.is_alive():
        return hilo
    parar.clear()
    hilo = threading.Thread(target=_trabajador, name="vantelia-cuenta-elevenlabs", daemon=True)
    hilo.start()
    return hilo
