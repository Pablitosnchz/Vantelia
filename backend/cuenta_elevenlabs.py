"""La cuenta de ElevenLabs: si se acaba, avisar a Pablo y no marcar a nadie.

POR QUE EXISTE
--------------
24-sep-2026: Pablo cancelo la suscripcion Creator ("lo que nos dure") y pidio que le
avisemos cuando se acabe para pasar a otra cuenta. Cuando una cuenta vuelve al plan
gratuito, se queda sin creditos o se revoca su clave, la voz de Laura deja de sonar:
el negocio que descuelga una llamada de Sara oiria colgar. Por eso:

- `estado()` dice si la cuenta sirve. El lanzador de llamadas lo mira en `bloqueos()`:
  con la cuenta caida no marca (cache de 30 min para no preguntar en cada ronda).
- Un hilo la revisa cada hora y manda un correo a CONSULTA_NOTIFICATION_EMAIL cuando
  hay que hacer algo: clave rechazada, pago pendiente, plan gratuito, creditos agotados
  o por debajo del 15 %. El mismo aviso no se repite en 24 h.

PAGO PENDIENTE = CUENTA CAIDA (24-sep-2026)
-------------------------------------------
La Creator cancelada seguia diciendo `tier: creator` con 300.000 creditos, pero con
`status: past_due` y una factura abierta ElevenLabs rechaza TODO uso ("Complete the
latest invoice to continue usage"). Mirar solo plan y creditos la daba por buena.

CAMBIAR DE CUENTA (lo que dice el correo)
-----------------------------------------
1. Clave nueva en ELEVENLABS_API_KEY (.env local y /srv/vantelia/.env) y recrear el
   contenedor (deploy).
2. POST /admin/captacion/voz/agente y POST /admin/clientes/{id}/voz-elevenlabs de cada
   negocio con agente: crean los agentes en la cuenta nueva (el id viejo da 404) y
   anaden la voz de Laura a esa cuenta si no la tiene (`voz_elevenlabs.asegurar_voz`).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, Optional

import httpx

from backend import settings

API = "https://api.elevenlabs.io"
AVISAR_POR_DEBAJO = 0.15
# Estados de la suscripcion en los que ElevenLabs no deja usar la voz. `past_due` solo
# cuenta con factura abierta (en el reintento de cobro puede seguir funcionando).
ESTADOS_SIN_PAGO = ("past_due", "unpaid", "incomplete", "incomplete_expired")
MINUTOS_DE_CACHE = 30
MINUTOS_ENTRE_REVISIONES = 60
HORAS_ENTRE_AVISOS = 24

parar = threading.Event()
hilo: Optional[threading.Thread] = None
_cache: Dict[str, Any] = {}
_avisados: Dict[str, float] = {}


def _consultar(cliente: Optional[httpx.Client]) -> Dict[str, Any]:
    """Lee la suscripcion. `tipo` identifica el aviso ("" = nada que avisar)."""
    if not settings.ELEVENLABS_API_KEY:
        return {"ok": False, "tipo": "", "problema": "Falta ELEVENLABS_API_KEY.", "aviso": ""}
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=15.0)
    try:
        r = cliente.get(API + "/v1/user/subscription", headers={"xi-api-key": settings.ELEVENLABS_API_KEY})
    except httpx.HTTPError as exc:
        # No saber no es lo mismo que estar caida: no se avisa, pero tampoco se llama.
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


def estado(*, fresco: bool = False, cliente: Optional[httpx.Client] = None) -> Dict[str, Any]:
    """Como esta la cuenta. `ok` = se puede usar la voz. Nunca lanza."""
    ahora = time.time()
    if not fresco and _cache and ahora - _cache["_momento"] < MINUTOS_DE_CACHE * 60:
        return {k: v for k, v in _cache.items() if k != "_momento"}
    leido = _consultar(cliente)
    _cache.clear()
    _cache.update(leido, _momento=ahora)
    return leido


def _correo(leido: Dict[str, Any]) -> None:
    from backend import outreach

    if leido["tipo"] == "pocos":
        intro, cierre = "Todavia funciona. Si no se renuevan a tiempo, pasa a otra cuenta Creator:", ""
    elif leido["tipo"] == "pago":
        intro, cierre = ("Paga la factura en ElevenLabs (vuelve a funcionar sola) o pasa a otra cuenta:",
                         "\nMientras tanto Sara no llama a nadie.")
    else:
        intro, cierre = "Para pasar a otra cuenta Creator:", "\nMientras tanto Sara no llama a nadie."
    pasos = (intro + "\n"
             "1. Pon la clave nueva en ELEVENLABS_API_KEY (.env local y /srv/vantelia/.env) y despliega.\n"
             "2. POST /admin/captacion/voz/agente y POST /admin/clientes/{id}/voz-elevenlabs de cada negocio\n"
             "   con agente: se crean en la cuenta nueva y se anade la voz de Laura." + cierre)
    texto = "%s\n\n%s\n" % (leido["aviso"], pasos)
    html = "<div style='font-family:sans-serif'><h2 style='color:#d97706'>%s</h2><pre style='white-space:pre-wrap'>%s</pre></div>" % (
        escape(leido["aviso"]), escape(pasos))
    outreach._outreach_notify_admin("⚠️ ElevenLabs: " + leido["aviso"][:120], texto, html)


def marcar_avisado(tipo: str) -> None:
    """Otro aviso ya conto este problema (lanzador_llamadas.fallo_de_voz): no repetirlo."""
    _avisados[tipo] = time.time()


def vigilar_una_vez(*, cliente: Optional[httpx.Client] = None) -> str:
    """Revisa la cuenta y avisa si toca. Devuelve el tipo de aviso mandado ("" si ninguno)."""
    leido = estado(fresco=True, cliente=cliente)
    tipo = leido.get("tipo") or ""
    if not tipo:
        return ""
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
    """Arranca la vigilancia si hay clave de ElevenLabs. Idempotente."""
    global hilo
    if not settings.ELEVENLABS_API_KEY:
        return None
    if hilo and hilo.is_alive():
        return hilo
    parar.clear()
    hilo = threading.Thread(target=_trabajador, name="vantelia-cuenta-elevenlabs", daemon=True)
    hilo.start()
    return hilo
