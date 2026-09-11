#!/usr/bin/env python
"""Sincronía entre los agentes que trabajan en este repo (Claude Code y GPT-6 Astra).

Los dos agentes no se ven: cada uno tiene su propia memoria y lo único que
comparten es este PC y el repo. Este script hace de canal entre ellos y contesta a
la pregunta de Pablo -"¿el otro sabe lo que ha hecho el primero?"- con hechos
(git, ficheros sin guardar, cuándo se puso al día cada uno), no con lo que digan.

    --al-dia claude|astra [--hook] [--solo-novedades]
        Ponerse al día: enseña al agente lo nuevo desde su última vez (commits y
        mensajes de los demás, trabajo sin guardar, "En curso") y lo apunta. Lo
        corren SOLOS los hooks de los dos agentes, al empezar y con cada mensaje
        de Pablo (`.claude/settings.local.json` y `~/.codex/hooks.json`). --hook
        lee por stdin el JSON del hook (apunta la sesión); --solo-novedades no
        imprime nada si no hay nada nuevo.
    --pedir-revision "qué"      Astra, al terminar una tarea: pide revisión.
    --pedir-despliegue "qué"    Astra, cuando Pablo dice que se despliegue.
    --pedir-ayuda "pregunta"    Astra pregunta a Claude (contexto, dónde, por qué,
                                segunda opinión); contesta solo, sin tocar nada.
    --encargar DE PARA "tarea"  un agente le encarga trabajo al otro. A Claude: lo
                                hace solo en su rama claude/encargo-*. A Astra: le
                                llega a su sesión al momento.
    --avisar DE PARA "texto"    una nota cualquiera por el buzón.
    --revisor                   lo corre la tarea programada "Vantelia revisor":
                                atiende la petición más antigua (tests + revisión
                                de Claude sin intervención, o fusión en main +
                                despliegue) y entrega la respuesta en la sesión
                                de Astra con `codex queue`.
    --enviar                    manda la foto a app.vantelia.es/sincronia.
    (sin nada)                  el semáforo, en la terminal.

El buzón son ficheros en `.sincronia/buzon/` de cada árbol, fuera de git: los dos
agentes están en el mismo PC. Quién hizo cada commit sale de su firma: una línea
`Co-Authored-By: Claude` es Claude, una línea `Agente: astra` es Astra, y lo demás
es Pablo. Solo se despliega un commit que tenga una revisión OK de Claude.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

AGENTES = {"claude": "Claude", "astra": "Astra"}
AUTORES = {"claude": "Claude", "astra": "Astra", "revisor": "Claude (revisión automática)", "pablo": "Pablo"}
URL_POR_DEFECTO = "https://app.vantelia.es/admin/sincronia"
PAGINA = "https://app.vantelia.es/sincronia"
DIR_LOCAL = ".sincronia"
PREFIJO_REVISION = "vantelia-revision-"
# Cambios sin commit que nadie toca desde hace mas de esto: alguien se quedo a
# medias (lo tipico, sin tokens). Si son mas recientes, esta trabajando ahora.
A_MEDIAS_MIN = 30
MAX_LISTA = 12
MAX_BUZON_FOTO = 15
CERROJO_CADUCA_H = 3
_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_VEREDICTO = re.compile(r"VEREDICTO:\s*\**\s*(OK|CAMBIOS)\b", re.I)
_UUID = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", re.I)
# Como avisan de que se acabo la cuota: Codex en su sesion ("You've hit your usage
# limit ... try again at 3:30 PM"), Claude Code en la salida de claude -p ("Claude AI
# usage limit reached|<epoch>", "You've hit your session limit · resets 4:20pm").
_SIN_CREDITOS = re.compile(
    r"usage limit|session limit|limit reached|hit your (?:\w+ )?limit|out of (?:extra )?usage|credit balance", re.I)
_A_LAS = re.compile(r"(?:try again at|resets?(?: at)?)\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)\b", re.I)
_LIMITE_EPOCH = re.compile(r"limit reached\|(\d{10})")
_ETIQUETAS = (
    ("testigo", "Testigo"),
    ("tarea", "Tarea"),
    ("rama", "Rama"),
    ("siguiente", "Siguiente"),
    ("espera_a", "Espera a"),
)
_TIPOS = {
    "revisar": "pide revisión",
    "revision": "revisión",
    "desplegar": "pide desplegar",
    "despliegue": "despliegue",
    "ayuda": "pide ayuda",
    "respuesta": "respuesta",
    "encargo": "encargo",
    "entrega": "entrega",
    "nota": "nota",
}
_VEREDICTOS = {
    "ok": "OK",
    "cambios": "CAMBIOS",
    "error": "NO SE PUDO",
    "sin_veredicto": "SIN VEREDICTO",
    "rechazado": "NO SE DESPLIEGA",
    "fallo": "FALLÓ",
    "hecho": "HECHO",
    "sin_cambios": "SIN CAMBIOS",
}
# Lo que el revisor le atiende a Claude, lo rapido primero; y como se llama su respuesta.
_PRIORIDAD = {"desplegar": 0, "revisar": 1, "ayuda": 2, "encargo": 3}
_RESPUESTA = {"desplegar": "despliegue", "revisar": "revision", "ayuda": "respuesta", "encargo": "entrega"}
_LINEA_EN_CURSO = re.compile(
    r"^\s*[-*]?\s*\**\s*(testigo|tarea|rama|siguiente|espera a)\s*\**\s*:\s*\**\s*(.*?)\s*$",
    re.I,
)


# --- tiempo ---------------------------------------------------------------------

def _ahora() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(momento: Optional[dt.datetime]) -> Optional[str]:
    if momento is None:
        return None
    return momento.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _desde_iso(texto: Any) -> Optional[dt.datetime]:
    if not isinstance(texto, str) or not texto:
        return None
    try:
        return dt.datetime.strptime(texto, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _hora_local(texto: Any) -> str:
    momento = _desde_iso(texto)
    if momento is None:
        return "nunca"
    return momento.astimezone().strftime("%d-%m %H:%M")


def _hora_corta(texto: Any) -> str:
    """"15:30" si es hoy; "12-09 15:30" si no."""
    momento = _desde_iso(texto)
    if momento is None:
        return ""
    local = momento.astimezone()
    if local.date() == dt.datetime.now().astimezone().date():
        return local.strftime("%H:%M")
    return local.strftime("%d-%m %H:%M")


def _a_las(texto: str, ahora: dt.datetime) -> Optional[dt.datetime]:
    """"try again at 3:30 PM" / "resets 3pm": la proxima vez que el reloj local marque esa hora."""
    casa = _A_LAS.search(texto or "")
    if not casa:
        return None
    hora = int(casa.group(1)) % 12 + (12 if casa.group(3).lower() == "pm" else 0)
    local = ahora.astimezone()
    momento = local.replace(hour=hora, minute=int(casa.group(2) or 0), second=0, microsecond=0)
    if momento <= local:
        momento += dt.timedelta(days=1)
    return momento.astimezone(dt.timezone.utc)


# --- git ------------------------------------------------------------------------

def _git(args: List[str], cwd: pathlib.Path, check: bool = True) -> str:
    resultado = subprocess.run(
        ["git", "-c", "core.quotepath=off"] + list(args),
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_SIN_VENTANA,
    )
    if check and resultado.returncode != 0:
        detalle = resultado.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError("git %s: %s" % (" ".join(args), detalle))
    return resultado.stdout.decode("utf-8", "replace")


def _git_ok(args: List[str], cwd: pathlib.Path) -> bool:
    resultado = subprocess.run(
        ["git"] + list(args),
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_SIN_VENTANA,
    )
    return resultado.returncode == 0


def raiz_del_repo(desde: pathlib.Path) -> pathlib.Path:
    """El repo PRINCIPAL, aunque se llame desde el worktree de Astra."""
    desde = pathlib.Path(desde).resolve()
    comun = pathlib.Path(_git(["rev-parse", "--git-common-dir"], desde).strip())
    if not comun.is_absolute():
        comun = (desde / comun).resolve()
    return comun.parent


def _arbol_de(desde: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(_git(["rev-parse", "--show-toplevel"], pathlib.Path(desde)).strip()).resolve()


def _arboles(raiz: pathlib.Path) -> List[Dict[str, Any]]:
    """El arbol principal y los worktrees (el de Astra), con su rama."""
    arboles: List[Dict[str, Any]] = []
    actual: Dict[str, Any] = {}
    for linea in _git(["worktree", "list", "--porcelain"], raiz).splitlines():
        if linea.startswith("worktree "):
            if actual:
                arboles.append(actual)
            actual = {"ruta": linea[len("worktree "):].strip(), "rama": ""}
        elif linea.startswith("branch "):
            actual["rama"] = linea[len("branch "):].strip().replace("refs/heads/", "", 1)
        elif linea.strip() == "detached":
            actual["rama"] = "(sin rama)"
        elif linea.startswith("prunable"):
            actual["perdido"] = True
    if actual:
        arboles.append(actual)
    # Las copias temporales del revisor no son trabajo de nadie.
    return [
        a for a in arboles
        if not a.get("perdido") and PREFIJO_REVISION not in a["ruta"] and pathlib.Path(a["ruta"]).exists()
    ]


def _ramas(raiz: pathlib.Path) -> Dict[str, str]:
    """main y las ramas de los agentes (astra/*, claude/*), con su commit."""
    ramas: Dict[str, str] = {}
    salida = _git(["for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/"], raiz)
    for linea in salida.splitlines():
        partes = linea.split()
        if len(partes) != 2:
            continue
        nombre, sha = partes
        if nombre == "main" or nombre.startswith("astra/") or nombre.startswith("claude/"):
            ramas[nombre] = sha
    return ramas


def agente_del_commit(mensaje: str) -> str:
    """Quien hizo el commit, por la linea que deja cada agente al final del mensaje."""
    texto = mensaje.lower()
    if re.search(r"^\s*agente:\s*astra\b", texto, re.M):
        return "astra"
    if re.search(r"^\s*(co-authored-by:\s*claude|agente:\s*claude)\b", texto, re.M):
        return "claude"
    return "pablo"


def _toca_codigo(fichero: str) -> bool:
    return not (fichero.startswith("docs/") or fichero.lower().endswith(".md"))


def _fecha_de_git(texto: str) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(texto.strip())
    except ValueError:
        return None


def _commits(raiz: pathlib.Path, rango: List[str], limite: int) -> List[Dict[str, Any]]:
    formato = "%x1e%H%x1f%h%x1f%cI%x1f%s%x1f%B%x1f"
    salida = _git(["log", "--name-only", "-n", str(limite), "--format=" + formato] + list(rango), raiz)
    commits = []
    for bloque in salida.split("\x1e")[1:]:
        partes = bloque.split("\x1f")
        if len(partes) < 6:
            continue
        sha, corto, fecha, asunto, cuerpo, ficheros = partes[:6]
        nombres = [f.strip() for f in ficheros.splitlines() if f.strip()]
        commits.append({
            "sha": sha.strip(),
            "corto": corto.strip(),
            "fecha": _iso(_fecha_de_git(fecha)),
            "asunto": asunto.strip(),
            "agente": agente_del_commit(cuerpo),
            "toca_codigo": any(_toca_codigo(n) for n in nombres),
        })
    return commits


def _existe(raiz: pathlib.Path, sha: str) -> bool:
    return _git_ok(["cat-file", "-e", sha + "^{commit}"], raiz)


def _sin_guardar(ruta: pathlib.Path) -> Tuple[List[str], Optional[dt.datetime]]:
    """Ficheros cambiados sin commit en un arbol, y cuando se toco el ultimo."""
    salida = _git(["status", "--porcelain", "--untracked-files=all"], ruta, check=False)
    ficheros = []
    for linea in salida.splitlines():
        if len(linea) < 4:
            continue
        fichero = linea[3:].strip()
        if " -> " in fichero:
            fichero = fichero.split(" -> ", 1)[1].strip()
        fichero = fichero.strip('"')
        # Los fichajes y el buzon de este script no son trabajo de nadie.
        if fichero == DIR_LOCAL or fichero.startswith(DIR_LOCAL + "/"):
            continue
        ficheros.append(fichero)
    ultimo = None
    for fichero in ficheros:
        try:
            momento = dt.datetime.fromtimestamp((ruta / fichero).stat().st_mtime, dt.timezone.utc)
        except OSError:
            continue  # borrado: no tiene fecha
        if ultimo is None or momento > ultimo:
            ultimo = momento
    return ficheros, ultimo


def _cambios_seguidos(arbol: pathlib.Path) -> List[str]:
    """Cambios sin commit en ficheros que git ya sigue (lo nuevo sin anadir no cuenta)."""
    salida = _git(["status", "--porcelain", "--untracked-files=no"], arbol, check=False)
    return [linea[3:].strip() for linea in salida.splitlines() if len(linea) > 3]


# --- lo que no es git -----------------------------------------------------------

def _leer_en_curso(texto: str) -> Optional[Dict[str, str]]:
    dentro = False
    datos: Dict[str, str] = {}
    for linea in texto.splitlines():
        if linea.startswith("## "):
            if dentro:
                break
            dentro = linea[3:].strip().lower().startswith("en curso")
            continue
        if dentro:
            casa = _LINEA_EN_CURSO.match(linea)
            if casa:
                clave = casa.group(1).lower().replace(" ", "_")
                # La pagina lo pinta como texto: sin las marcas de markdown.
                datos[clave] = casa.group(2).replace("`", "").strip("* ").strip()
    return datos or None


def _en_curso(arboles: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """La seccion "En curso" de docs/ESTADO_ACTUAL.md, de la copia tocada mas tarde."""
    mejor = None
    for arbol in arboles:
        fichero = pathlib.Path(arbol["ruta"]) / "docs" / "ESTADO_ACTUAL.md"
        try:
            texto = fichero.read_text(encoding="utf-8")
            cuando = fichero.stat().st_mtime
        except OSError:
            continue
        datos = _leer_en_curso(texto)
        if datos and (mejor is None or cuando > mejor[0]):
            datos["fuente"] = arbol["ruta"]
            mejor = (cuando, datos)
    return mejor[1] if mejor else None


def _fichajes(arboles: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """La ultima puesta al dia de cada agente, en cualquiera de los arboles."""
    fichajes: Dict[str, Dict[str, Any]] = {}
    for arbol in arboles:
        for agente in AGENTES:
            fichero = pathlib.Path(arbol["ruta"]) / DIR_LOCAL / ("%s.json" % agente)
            try:
                datos = json.loads(fichero.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(datos, dict):
                continue
            if agente not in fichajes or float(datos.get("marca") or 0) > float(fichajes[agente].get("marca") or 0):
                fichajes[agente] = datos
    return fichajes


def _no_vistos(
    raiz: pathlib.Path, ramas: Dict[str, str], fichaje: Optional[Dict[str, Any]], agente: str
) -> Optional[List[Dict[str, Any]]]:
    """Commits de los DEMAS que el agente no habia visto al ponerse al dia. None = sin registro."""
    if not fichaje:
        return None
    vio = fichaje.get("vio")
    vistos = sorted({
        sha for sha in (vio.values() if isinstance(vio, dict) else [])
        if isinstance(sha, str) and _SHA.match(sha) and _existe(raiz, sha)
    })
    if not vistos:
        return None
    actuales = sorted(set(ramas.values()))
    if not actuales:
        return []
    commits = _commits(raiz, actuales + ["--not"] + vistos, limite=200)
    return [c for c in commits if c["agente"] != agente]


def _mas_reciente(actual: Optional[dt.datetime], fichero: pathlib.Path) -> Optional[dt.datetime]:
    try:
        momento = dt.datetime.fromtimestamp(fichero.stat().st_mtime, dt.timezone.utc)
    except OSError:
        return actual
    return momento if actual is None or momento > actual else actual


def _cwd_de_la_sesion(fichero: pathlib.Path) -> str:
    try:
        with fichero.open(encoding="utf-8", errors="replace") as manejador:
            primera = json.loads(manejador.readline() or "{}")
    except (OSError, ValueError):
        return ""
    datos = primera.get("payload") if isinstance(primera, dict) else None
    return str(datos.get("cwd") or "") if isinstance(datos, dict) else ""


def _casa(home: Optional[pathlib.Path] = None) -> pathlib.Path:
    # SINCRONIA_HOME deja a los tests fuera de las sesiones de verdad de este PC.
    return pathlib.Path(home) if home else pathlib.Path(os.environ.get("SINCRONIA_HOME") or pathlib.Path.home())


def _sesion_codex_de_vantelia(home: pathlib.Path) -> Optional[pathlib.Path]:
    """La ultima sesion de Codex abierta en Vantelia (Codex tambien se usa para otras cosas)."""
    candidatos = []
    for fichero in (home / ".codex" / "sessions").glob("*/*/*/rollout-*.jsonl"):
        try:
            candidatos.append((fichero.stat().st_mtime, str(fichero)))
        except OSError:
            continue
    for _, ruta in sorted(candidatos, reverse=True)[:60]:
        if "vantelia" in _cwd_de_la_sesion(pathlib.Path(ruta)).lower():
            return pathlib.Path(ruta)
    return None


def _creditos_de_codex(fichero: pathlib.Path, ahora: dt.datetime) -> Dict[str, Any]:
    """Si Astra se ha quedado sin creditos, lo dice su propia sesion de Codex.

    Al acabarse la cuota, el turno termina con un `task_complete` cuyo error es
    `usage_limit_exceeded`, y los `token_count` traen `rate_limits` con la ventana
    al 100 % y cuando se renueva. Vuelve a tener creditos si un turno posterior
    termina bien o si ya ha pasado la hora de la renovacion.
    """
    try:
        with fichero.open(encoding="utf-8", errors="replace") as manejador:
            cola = collections.deque(manejador, maxlen=400)
    except OSError:
        return {"sin_creditos": False}
    ultimo_fin: Dict[str, Any] = {}
    ventanas: Dict[str, Dict[str, Any]] = {}
    # La hora del ultimo evento: el mtime del fichero no sirve, Codex lo tiene abierto
    # y Windows no lo actualiza hasta que lo cierra.
    ultima: Optional[dt.datetime] = None
    for linea in cola:
        try:
            fila = json.loads(linea)
        except ValueError:
            continue
        if not isinstance(fila, dict):
            continue
        ultima = _fecha_de_evento(fila.get("timestamp")) or ultima
        datos = fila.get("payload")
        if not isinstance(datos, dict):
            continue
        if datos.get("type") == "task_complete":
            ultimo_fin = datos
        elif datos.get("type") == "token_count" and isinstance(datos.get("rate_limits"), dict):
            for nombre in ("primary", "secondary"):
                ventana = datos["rate_limits"].get(nombre)
                if isinstance(ventana, dict) and ventana.get("used_percent") is not None:
                    ventanas[nombre] = ventana
    estado = _cuota_de_codex(ultimo_fin, ventanas, ahora)
    estado["actividad"] = ultima
    return estado


def _fecha_de_evento(texto: Any) -> Optional[dt.datetime]:
    if not isinstance(texto, str) or not texto:
        return None
    try:
        return dt.datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cuota_de_codex(ultimo_fin: Dict[str, Any], ventanas: Dict[str, Dict[str, Any]],
                    ahora: dt.datetime) -> Dict[str, Any]:
    error = ultimo_fin.get("error")
    if not isinstance(error, dict):
        return {"sin_creditos": False}
    mensaje = str(error.get("message") or "")
    if "usage_limit" not in str(error.get("codex_error_info") or "") and not _SIN_CREDITOS.search(mensaje):
        return {"sin_creditos": False}
    renovaciones = [int(v["resets_at"]) for v in ventanas.values()
                    if float(v.get("used_percent") or 0) >= 100 and v.get("resets_at")]
    hasta = (dt.datetime.fromtimestamp(max(renovaciones), dt.timezone.utc) if renovaciones
             else _a_las(mensaje, ahora))
    if hasta is not None and hasta <= ahora:
        return {"sin_creditos": False}
    return {"sin_creditos": True, "hasta": _iso(hasta), "motivo": mensaje[:300]}


def _agentes_fuera(home: pathlib.Path, ahora: dt.datetime) -> Dict[str, Dict[str, Any]]:
    """Lo que se sabe de cada agente por sus propias sesiones: horas y cuota, nunca el contenido."""
    estado: Dict[str, Dict[str, Any]] = {"claude": {"actividad": None}, "astra": {"actividad": None}}
    for fichero in (home / ".claude" / "projects").glob("*antelia*/*.jsonl"):
        estado["claude"]["actividad"] = _mas_reciente(estado["claude"]["actividad"], fichero)
    sesion = _sesion_codex_de_vantelia(home)
    if sesion is not None:
        uuid = _UUID.search(sesion.name)
        estado["astra"].update(_creditos_de_codex(sesion, ahora))
        estado["astra"]["actividad"] = estado["astra"].get("actividad") or _mas_reciente(None, sesion)
        estado["astra"]["sesion"] = uuid.group(1) if uuid else ""
    return estado


def _limite_de_claude(raiz: pathlib.Path, ahora: dt.datetime) -> Dict[str, Any]:
    """Lo apunta el revisor cuando claude -p se queda sin cuota; caduca solo."""
    try:
        datos = json.loads((raiz / DIR_LOCAL / "claude_limite.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"sin_creditos": False}
    hasta = _desde_iso(datos.get("hasta")) if isinstance(datos, dict) else None
    if hasta is None or hasta <= ahora:
        return {"sin_creditos": False}
    return {"sin_creditos": True, "hasta": _iso(hasta), "motivo": str(datos.get("motivo") or "")[:300]}


# --- el buzon -------------------------------------------------------------------

def _escribir_mensaje(arbol: pathlib.Path, de: str, para: str, tipo: str, texto: str, **extra: Any) -> Dict[str, Any]:
    carpeta = pathlib.Path(arbol) / DIR_LOCAL / "buzon"
    carpeta.mkdir(parents=True, exist_ok=True)
    marca = time.time()
    momento = dt.datetime.fromtimestamp(marca, dt.timezone.utc)
    ident = "%s-%s-%s" % (momento.strftime("%Y%m%dT%H%M%S%f"), de, secrets.token_hex(3))
    mensaje: Dict[str, Any] = {
        "id": ident,
        "marca": marca,
        "cuando": _iso(momento),
        "de": de,
        "para": para,
        "tipo": tipo,
        "texto": (texto or "").strip(),
    }
    mensaje.update({clave: valor for clave, valor in extra.items() if valor not in (None, "")})
    (carpeta / (ident + ".json")).write_text(json.dumps(mensaje, ensure_ascii=False, indent=2), encoding="utf-8")
    return mensaje


def _buzon(arboles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Todos los mensajes de todos los arboles, del mas antiguo al mas nuevo."""
    mensajes: Dict[str, Dict[str, Any]] = {}
    for arbol in arboles:
        for fichero in (pathlib.Path(arbol["ruta"]) / DIR_LOCAL / "buzon").glob("*.json"):
            try:
                mensaje = json.loads(fichero.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(mensaje, dict) and mensaje.get("id"):
                mensajes[str(mensaje["id"])] = mensaje
    return sorted(mensajes.values(), key=lambda m: float(m.get("marca") or 0))


def _pendientes(mensajes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Lo que le han pedido a Claude y nadie ha contestado todavia, lo rapido primero."""
    contestadas = {m.get("responde_a") for m in mensajes if m.get("responde_a")}
    pendientes = [m for m in mensajes
                  if m.get("tipo") in _PRIORIDAD and m.get("para") == "claude" and m.get("id") not in contestadas]
    return sorted(pendientes, key=lambda m: (_PRIORIDAD[m["tipo"]], float(m.get("marca") or 0)))


def avisar(desde: pathlib.Path, de: str, para: str, texto: str) -> Dict[str, Any]:
    return _escribir_mensaje(_arbol_de(desde), de, para, "nota", texto)


_PEDIDO = {
    "revisar": ("Revisión pedida para %s (%s). Claude la hace solo en unos minutos (tests + revisión) "
                "y la respuesta te llega aquí; no hace falta que Pablo haga nada."),
    "desplegar": ("Despliegue pedido para %s (%s). Solo sale si Claude revisó OK ese mismo commit; "
                  "el resultado te llega aquí."),
    "ayuda": "Pregunta enviada a Claude desde %s (%s). Contesta solo en unos minutos, aquí mismo.",
    "encargo": ("Encargo enviado a Claude desde %s (%s). Lo hace en su propia rama, sin tocar la tuya, "
                "y te avisa aquí al terminar."),
}


def _pedir(desde: pathlib.Path, tipo: str, texto: str, de: str = "astra") -> Tuple[bool, str]:
    arbol = _arbol_de(desde)
    cambios = _cambios_seguidos(arbol)
    if cambios and tipo in ("revisar", "desplegar"):
        return False, ("No: hay %d cambio(s) sin commit en %s (%s). Haz commit y vuelve a pedirlo: "
                       "se revisa y se despliega lo que está en un commit, no lo que está a medias."
                       % (len(cambios), arbol, ", ".join(cambios[:4])))
    rama = _git(["rev-parse", "--abbrev-ref", "HEAD"], arbol).strip()
    commit = _git(["rev-parse", "HEAD"], arbol).strip()
    _escribir_mensaje(arbol, de, "claude", tipo, texto, rama=rama, commit=commit)
    aviso = ""
    if cambios:
        aviso = (" Ojo: tienes %d cambio(s) sin commit; Claude parte de tu último commit (%s) y no los verá."
                 % (len(cambios), commit[:7]))
    return True, _PEDIDO[tipo] % (rama, commit[:7]) + aviso


def pedir_revision(desde: pathlib.Path, texto: str) -> Tuple[bool, str]:
    return _pedir(desde, "revisar", texto)


def pedir_despliegue(desde: pathlib.Path, texto: str) -> Tuple[bool, str]:
    return _pedir(desde, "desplegar", texto)


def pedir_ayuda(desde: pathlib.Path, texto: str) -> Tuple[bool, str]:
    return _pedir(desde, "ayuda", texto)


def encargar(desde: pathlib.Path, de: str, para: str, texto: str,
             ejecutor: Optional["Ejecutor"] = None, home: Optional[pathlib.Path] = None) -> Tuple[bool, str]:
    """Un agente le encarga trabajo al otro: trabajan a la vez, no solo uno revisa al otro."""
    if para == "claude":
        return _pedir(desde, "encargo", texto, de=de)
    if para != "astra":
        return False, "Solo se le puede encargar algo a claude o a astra."
    arbol = _arbol_de(desde)
    mensaje = _escribir_mensaje(arbol, de, "astra", "encargo", texto,
                                rama=_git(["rev-parse", "--abbrev-ref", "HEAD"], arbol).strip(),
                                commit=_git(["rev-parse", "HEAD"], arbol).strip())
    entregado, detalle = _entregar_a_astra(raiz_del_repo(desde), _aviso_para_astra(mensaje), ejecutor or Ejecutor(), home)
    return True, ("Encargo entregado a Astra en su sesión." if entregado
                  else "Encargo dejado en el buzón de Astra (%s)." % detalle)


def _mensaje_para_foto(mensaje: Dict[str, Any]) -> Dict[str, Any]:
    datos = {clave: mensaje.get(clave)
             for clave in ("id", "cuando", "de", "para", "tipo", "rama", "rama_claude", "veredicto")}
    datos["commit"] = str(mensaje.get("commit") or "")[:7]
    datos["texto"] = str(mensaje.get("texto") or "")[:1500]
    return {clave: valor for clave, valor in datos.items() if valor}


def _estado_revisor(raiz: pathlib.Path) -> Optional[Dict[str, Any]]:
    try:
        datos = json.loads((raiz / DIR_LOCAL / "revisor.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


# --- la foto --------------------------------------------------------------------

def veredicto(foto: Dict[str, Any], ahora: dt.datetime) -> Dict[str, str]:
    """Una frase para Pablo. Rojo solo cuando hay trabajo que se puede quedar sin explicar."""
    a_medias, trabajando = [], []
    for arbol in foto.get("arboles") or []:
        if not arbol.get("sin_guardar_total"):
            continue
        ultimo = _desde_iso(arbol.get("ultimo_cambio"))
        if ultimo is None or (ahora - ultimo).total_seconds() > A_MEDIAS_MIN * 60:
            a_medias.append(arbol)
        else:
            trabajando.append(arbol)
    sin_creditos = [a for a in foto.get("agentes") or [] if a.get("sin_creditos")]
    if a_medias:
        arbol = a_medias[0]
        if (any(a["id"] == "astra" for a in sin_creditos)
                and str(arbol.get("rama") or "").startswith("astra/")):
            return {
                "color": "rojo",
                "titulo": "Astra se quedó sin créditos a medias",
                "detalle": ("Tiene cambios sin guardar en %s. Escribe a Claude: se pone al día solo "
                            "y sigue donde lo dejó." % arbol.get("rama")),
            }
        return {
            "color": "rojo",
            "titulo": "Hay trabajo a medias sin guardar",
            "detalle": (
                "En %s (%s) hay %d cambio(s) sin commit que nadie toca desde hace más de %d min. "
                "Si a alguien se le acabaron los tokens, el otro lo verá solo al empezar y seguirá donde se quedó."
                % (arbol["ruta"], arbol.get("rama") or "sin rama", arbol["sin_guardar_total"], A_MEDIAS_MIN)
            ),
        }
    if sin_creditos:
        agente = sin_creditos[0]
        hasta = _hora_corta(agente.get("creditos_hasta"))
        if agente["id"] == "astra":
            detalle = "Si necesitas algo antes, escríbele a Claude: se pone al día solo y sigue él."
        else:
            detalle = "Las revisiones esperan en el buzón y se harán solas cuando vuelva; Astra puede seguir programando."
        return {
            "color": "amarillo",
            "titulo": "%s está sin créditos%s" % (agente["nombre"], (" hasta las " + hasta) if hasta else ""),
            "detalle": detalle,
        }
    if trabajando:
        arbol = trabajando[0]
        return {
            "color": "amarillo",
            "titulo": "Alguien está trabajando ahora",
            "detalle": (
                "Hay cambios sin commit en %s (%s). Si cambias de agente antes de que se guarden, "
                "el otro los verá pero sin saber por qué." % (arbol["ruta"], arbol.get("rama") or "sin rama")
            ),
        }
    atrasados = [a for a in foto.get("agentes") or [] if a.get("estado") != "al_dia"]
    if atrasados:
        partes = []
        for agente in atrasados:
            if agente.get("estado") == "nunca":
                partes.append("%s no se ha puesto al día nunca" % agente["nombre"])
            else:
                total = agente.get("no_vistos_total") or 0
                partes.append("%s aún no ha visto %d cambio%s" % (agente["nombre"], total, "" if total == 1 else "s"))
        return {
            "color": "amarillo",
            "titulo": "Casi: " + "; ".join(partes),
            "detalle": "Cada uno se pone al día solo en cuanto le escribes. No tienes que decirle nada.",
        }
    return {
        "color": "verde",
        "titulo": "Sí, estáis sincronizados",
        "detalle": "Los dos han visto todo lo que hay en git y no hay nada a medias. Puedes cambiar de agente.",
    }


def construir_foto(
    desde: pathlib.Path, ahora: Optional[dt.datetime] = None, home: Optional[pathlib.Path] = None
) -> Dict[str, Any]:
    ahora = ahora or _ahora()
    raiz = raiz_del_repo(desde)
    arboles_git = _arboles(raiz)
    ramas = _ramas(raiz)
    fichajes = _fichajes(arboles_git)
    fuera = _agentes_fuera(_casa(home), ahora)
    fuera["claude"].update(_limite_de_claude(raiz, ahora))

    agentes = []
    for agente, nombre in AGENTES.items():
        fichaje = fichajes.get(agente)
        no_vistos = _no_vistos(raiz, ramas, fichaje, agente)
        if no_vistos is None:
            estado = "nunca"
        elif no_vistos:
            estado = "atrasado"
        else:
            estado = "al_dia"
        agentes.append({
            "id": agente,
            "nombre": nombre,
            "estado": estado,
            "ultima_puesta_al_dia": (fichaje or {}).get("cuando"),
            "ultima_actividad": _iso(fuera[agente].get("actividad")),
            "sin_creditos": bool(fuera[agente].get("sin_creditos")),
            "creditos_hasta": fuera[agente].get("hasta"),
            "creditos_motivo": fuera[agente].get("motivo") or "",
            "no_vistos": (no_vistos or [])[:MAX_LISTA],
            "no_vistos_total": len(no_vistos or []),
        })

    arboles = []
    for arbol in arboles_git:
        ficheros, ultimo = _sin_guardar(pathlib.Path(arbol["ruta"]))
        arboles.append({
            "ruta": arbol["ruta"],
            "rama": arbol.get("rama") or "",
            "sin_guardar": ficheros[:MAX_LISTA],
            "sin_guardar_total": len(ficheros),
            "ultimo_cambio": _iso(ultimo),
        })

    sin_integrar = []
    if "main" in ramas:
        for rama in sorted(ramas):
            if rama == "main":
                continue
            cuenta = _git(["rev-list", "--count", "main.." + rama], raiz, check=False).strip()
            if cuenta.isdigit() and int(cuenta):
                sin_integrar.append({"rama": rama, "commits": int(cuenta)})

    mensajes = _buzon(arboles_git)
    foto: Dict[str, Any] = {
        "version": 1,
        "generada": _iso(ahora),
        "veredicto": {},
        "en_curso": _en_curso(arboles_git),
        "agentes": agentes,
        "arboles": arboles,
        "ramas_sin_integrar": sin_integrar,
        "buzon": [_mensaje_para_foto(m) for m in reversed(mensajes[-MAX_BUZON_FOTO:])],
        "pendientes": len(_pendientes(mensajes)),
        "revisor": _estado_revisor(raiz),
        "main": _commits(raiz, ["main"], limite=30) if "main" in ramas else [],
    }
    foto["veredicto"] = veredicto(foto, ahora)
    return foto


# --- ponerse al dia ---------------------------------------------------------------

def _agente(foto: Dict[str, Any], agente: str) -> Dict[str, Any]:
    return next(a for a in foto["agentes"] if a["id"] == agente)


def _nombre(autor: str) -> str:
    return AUTORES.get(autor, autor.capitalize() if autor else "Pablo")


def _linea_mensaje(mensaje: Dict[str, Any], agente: str) -> str:
    tipo = _TIPOS.get(str(mensaje.get("tipo")), "nota")
    etiqueta = _VEREDICTOS.get(str(mensaje.get("veredicto") or ""), "")
    donde = ""
    if mensaje.get("rama_claude"):
        donde = " %s" % mensaje["rama_claude"]
    elif mensaje.get("rama"):
        donde = " %s (%s)" % (mensaje["rama"], str(mensaje.get("commit") or "")[:7])
    # A quien va dirigido lo lee entero: una revision con cambios hay que poder aplicarla.
    limite = 4000 if mensaje.get("para") == agente else 600
    texto = str(mensaje.get("texto") or "")
    if len(texto) > limite:
        texto = texto[:limite] + " …"
    cabecera = "[%s → %s · %s%s%s]" % (
        _nombre(str(mensaje.get("de") or "")), _nombre(str(mensaje.get("para") or "")), tipo,
        (" " + etiqueta) if etiqueta else "", donde)
    return "  %s %s" % (cabecera, texto.replace("\n", "\n    "))


def _lineas_creditos(foto: Dict[str, Any], agente: str, cuales: Dict[str, str]) -> List[str]:
    """Que el otro se ha quedado sin cuota (o la ha recuperado), y que hacer con eso."""
    lineas = []
    for otro in foto.get("agentes") or []:
        if otro["id"] == agente or otro["id"] not in cuales:
            continue
        if not otro.get("sin_creditos"):
            lineas.append("%s vuelve a tener créditos." % otro["nombre"])
            continue
        hasta = _hora_corta(otro.get("creditos_hasta"))
        if otro["id"] == "astra":
            accion = ("Si Pablo te pide algo, hazlo tú sin esperarla; si dejó trabajo a medias, "
                      "sigue en su rama. Cuéntaselo a Pablo en una línea.")
        else:
            accion = ("Tus revisiones esperan en el buzón y se harán solas cuando vuelva; "
                      "sigue programando y cuéntaselo a Pablo en una línea.")
        lineas.append("%s está SIN CRÉDITOS%s (%s). %s" % (
            otro["nombre"], (" hasta las " + hasta) if hasta else "",
            (otro.get("creditos_motivo") or "cuota agotada")[:140], accion))
    return lineas


def _informe(
    antes: Dict[str, Any],
    despues: Dict[str, Any],
    agente: str,
    mensajes: List[Dict[str, Any]],
    arbol: pathlib.Path,
    desde_marca: float,
    solo_novedades: bool,
    cambios_creditos: Optional[Dict[str, str]] = None,
) -> str:
    yo = _agente(antes, agente)
    if yo["estado"] == "nunca":
        # La primera vez siempre habla, aunque venga del hook de cada mensaje: una
        # sesion abierta antes de la sincronia no conoce las reglas y no hay nada
        # "nuevo" que la despierte.
        solo_novedades = False
    sin_guardar = [a for a in antes.get("arboles") or [] if a.get("sin_guardar_total")]
    if solo_novedades:
        # En cada mensaje de Pablo: solo lo de los DEMAS que haya cambiado desde la ultima vez.
        def _cambio_despues(a: Dict[str, Any]) -> bool:
            ultimo = _desde_iso(a.get("ultimo_cambio"))
            return ultimo is not None and ultimo.timestamp() > desde_marca
        sin_guardar = [a for a in sin_guardar
                       if pathlib.Path(a["ruta"]).resolve() != arbol and _cambio_despues(a)]
        if not (yo["no_vistos_total"] or mensajes or sin_guardar or cambios_creditos):
            return ""

    titulo = ("novedades para %s" if solo_novedades else "puesta al día de %s") % yo["nombre"]
    lineas = ["== Sincronía: %s ==" % titulo]
    # Al empezar, cualquiera que este sin cuota; en cada mensaje, solo si ha cambiado.
    cuales = (cambios_creditos or {}) if solo_novedades else {
        a["id"]: "sin" for a in antes.get("agentes") or [] if a["id"] != agente and a.get("sin_creditos")}
    lineas.extend(_lineas_creditos(antes, agente, cuales))
    if yo["estado"] == "nunca":
        lineas.append("Primera puesta al día: no hay registro de lo que viste antes. Relee AGENTS.md "
                      "(sección «Sincronía»: han cambiado las reglas) y docs/ESTADO_ACTUAL.md entero.")
    elif yo["no_vistos_total"]:
        lineas.append("Commits nuevos de los demás desde tu última vez (%s):" % _hora_local(yo["ultima_puesta_al_dia"]))
        for commit in yo["no_vistos"]:
            lineas.append("  %s [%s] %s" % (commit["corto"], _nombre(commit["agente"]), commit["asunto"]))
        resto = yo["no_vistos_total"] - len(yo["no_vistos"])
        if resto > 0:
            lineas.append("  … y %d más (git log)" % resto)
        lineas.append("Míralos (git show <sha>) antes de tocar lo mismo.")
    elif not solo_novedades:
        lineas.append("Nada nuevo de los demás en git desde tu última vez (%s)." % _hora_local(yo["ultima_puesta_al_dia"]))
    if mensajes:
        lineas.append("Mensajes nuevos en el buzón:")
        lineas.extend(_linea_mensaje(m, agente) for m in mensajes)
    for a in sin_guardar:
        muestra = ", ".join(a["sin_guardar"][:6]) + (" …" if a["sin_guardar_total"] > 6 else "")
        lineas.append("Sin guardar en %s (%s): %s" % (a["ruta"], a.get("rama") or "sin rama", muestra))
    if not solo_novedades:
        en_curso = antes.get("en_curso")
        if en_curso:
            piezas = ["%s: %s" % (etiqueta, en_curso[clave]) for clave, etiqueta in _ETIQUETAS if en_curso.get(clave)]
            lineas.append("En curso (docs/ESTADO_ACTUAL.md) — " + " · ".join(piezas))
        else:
            lineas.append("En curso: no hay nada apuntado en docs/ESTADO_ACTUAL.md.")
        for rama in antes.get("ramas_sin_integrar") or []:
            lineas.append("Rama sin integrar en main: %s (%d commit%s)"
                          % (rama["rama"], rama["commits"], "" if rama["commits"] == 1 else "s"))
        semaforo = despues["veredicto"]
        lineas.append("Semáforo: %s. %s" % (semaforo["titulo"], semaforo["detalle"]))
    lineas.append("Cuéntale a Pablo en una o dos líneas lo que le afecte de esto: él no tiene que pedírtelo. "
                  "(Queda apuntado que lo has visto; Pablo lo ve en %s)" % PAGINA)
    return "\n".join(lineas)


def fichar(
    desde: pathlib.Path,
    agente: str,
    ahora: Optional[dt.datetime] = None,
    home: Optional[pathlib.Path] = None,
    sesion: str = "",
    solo_novedades: bool = False,
) -> str:
    """Pone al dia al agente: le devuelve lo que tiene que leer y deja constancia de que lo vio."""
    if agente not in AGENTES:
        raise ValueError("Agente desconocido: %s" % agente)
    ahora = ahora or _ahora()
    raiz = raiz_del_repo(desde)
    arbol = _arbol_de(desde)
    anterior = _fichajes(_arboles(raiz)).get(agente) or {}
    desde_marca = float(anterior.get("marca") or 0)
    antes = construir_foto(desde, ahora=ahora, home=home)
    mensajes = [m for m in _buzon(_arboles(raiz))
                if m.get("de") != agente and float(m.get("marca") or 0) > desde_marca]
    # La cuota de los demas: se cuenta cuando cambia, no en cada mensaje.
    creditos = {a["id"]: ((a.get("creditos_hasta") or "sin") if a.get("sin_creditos") else "")
                for a in antes["agentes"] if a["id"] != agente}
    vistos = anterior.get("creditos_vistos") if isinstance(anterior.get("creditos_vistos"), dict) else {}
    cambios_creditos = {otro: estado for otro, estado in creditos.items() if vistos.get(otro, "") != estado}
    carpeta = arbol / DIR_LOCAL
    carpeta.mkdir(exist_ok=True)
    registro = {
        "agente": agente,
        "cuando": _iso(ahora),
        "marca": time.time(),
        "vio": _ramas(raiz),
        "arbol": str(arbol),
        # La sesion del hook es a donde se le entregan los avisos (codex queue).
        "sesion": sesion or anterior.get("sesion") or "",
        "creditos_vistos": creditos,
    }
    (carpeta / ("%s.json" % agente)).write_text(json.dumps(registro, indent=2), encoding="utf-8")
    despues = construir_foto(desde, ahora=ahora, home=home)
    return _informe(antes, despues, agente, mensajes, arbol, desde_marca, solo_novedades, cambios_creditos)


# --- el revisor ---------------------------------------------------------------------

def _python_con_consola() -> str:
    ejecutable = pathlib.Path(sys.executable)
    if ejecutable.name.lower() == "pythonw.exe" and ejecutable.with_name("python.exe").exists():
        return str(ejecutable.with_name("python.exe"))
    return str(ejecutable)


def _una_linea(texto: str, limite: int = 900) -> str:
    # Viaja como argumento por el lanzador .cmd de codex: fuera lo que cmd.exe interpreta,
    # y sin tildes (la pagina de codigos de la consola las estropea por el camino).
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    limpio = re.sub(r'["%^&|<>]', "", ascii_.replace("\n", " "))
    return re.sub(r"\s+", " ", limpio).strip()[:limite]


class SinCreditos(RuntimeError):
    """claude -p se ha quedado sin cuota: la revision espera, no se da por hecha."""

    def __init__(self, motivo: str, hasta: Optional[dt.datetime] = None):
        super().__init__(motivo)
        self.hasta = hasta


def _hasta_de_claude(texto: str, ahora: dt.datetime) -> Optional[dt.datetime]:
    casa = _LIMITE_EPOCH.search(texto or "")
    if casa:
        return dt.datetime.fromtimestamp(int(casa.group(1)), dt.timezone.utc)
    return _a_las(texto, ahora)


class Ejecutor:
    """Lo que el revisor hace fuera de git. Los tests lo cambian por uno falso."""

    def pytest(self, arbol: pathlib.Path) -> Tuple[bool, str]:
        extra = os.environ.get("SINCRONIA_PYTEST_ARGS", "").split()
        resultado = subprocess.run(
            [_python_con_consola(), "-m", "pytest", "-q", "-p", "no:cacheprovider"] + extra,
            cwd=str(arbol), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=_SIN_VENTANA, timeout=45 * 60,
        )
        lineas = resultado.stdout.decode("utf-8", "replace").strip().splitlines()
        fallos = [linea for linea in lineas if linea.startswith(("FAILED", "ERROR"))][:20]
        return resultado.returncode == 0, "\n".join(fallos + lineas[-1:])

    LECTURA = ["Read", "Grep", "Glob", "Bash(git diff *)", "Bash(git log *)", "Bash(git show *)"]
    # Encargos: escribir en su copia (dontAsk niega lo que pida permiso fuera de ella),
    # tests y commits. Ni red, ni despliegue, ni nada mas.
    ESCRITURA = LECTURA + ["Edit", "Write", "Bash(git status*)", "Bash(git add *)", "Bash(git commit *)",
                           "Bash(python -m pytest *)", "Bash(python -m pyflakes *)"]

    def claude(self, arbol: pathlib.Path, prompt: str) -> str:
        """Revisiones y preguntas: solo lectura."""
        return self._claude(arbol, prompt, escribir=False)

    def claude_escribe(self, arbol: pathlib.Path, prompt: str) -> str:
        """Encargos: trabaja en su copia y hace commits en su rama."""
        return self._claude(arbol, prompt, escribir=True)

    def _claude(self, arbol: pathlib.Path, prompt: str, escribir: bool) -> str:
        ejecutable = shutil.which("claude")
        if not ejecutable:
            raise RuntimeError("no encuentro el comando claude en este PC")
        ajustes = pathlib.Path(tempfile.gettempdir()) / ("sincronia-ajustes-%s.json" % secrets.token_hex(4))
        # Sin hooks: la copia temporal no es una sesion de trabajo de nadie.
        ajustes.write_text(json.dumps({"disableAllHooks": True}), encoding="utf-8")
        orden = [ejecutable, "-p", "--output-format", "text", "--permission-mode", "dontAsk",
                 "--settings", str(ajustes)]
        if not escribir:
            orden += ["--disallowedTools", "Edit", "Write", "NotebookEdit"]
        orden += ["--allowedTools"] + (self.ESCRITURA if escribir else self.LECTURA)
        try:
            resultado = subprocess.run(
                orden,
                input=prompt.encode("utf-8"), cwd=str(arbol), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=_SIN_VENTANA, timeout=(60 if escribir else 30) * 60,
            )
        finally:
            try:
                ajustes.unlink()
            except OSError:
                pass
        salida = resultado.stdout.decode("utf-8", "replace")
        texto = (resultado.stderr.decode("utf-8", "replace") + "\n" + salida).strip()
        # Sin cuota sale con error, o con un aviso corto en vez de la revision.
        if _SIN_CREDITOS.search(texto) and (resultado.returncode != 0 or len(salida) < 400):
            raise SinCreditos(texto[-300:], _hasta_de_claude(texto, _ahora()))
        if resultado.returncode != 0:
            raise RuntimeError(texto[-400:] or "claude terminó con error")
        return salida

    def desplegar(self, raiz: pathlib.Path) -> Tuple[bool, str]:
        registro = raiz / DIR_LOCAL / "despliegue.log"
        with registro.open("wb") as salida:
            resultado = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(raiz / "deploy" / "deploy.ps1")],
                cwd=str(raiz), stdin=subprocess.DEVNULL, stdout=salida, stderr=subprocess.STDOUT,
                creationflags=_SIN_VENTANA, timeout=90 * 60,
            )
        cola = registro.read_bytes().decode("utf-8", "replace").strip().splitlines()[-12:]
        return resultado.returncode == 0, "\n".join(cola)

    def entregar(self, sesion: str, texto: str) -> Tuple[bool, str]:
        ejecutable = shutil.which("codex")
        if not ejecutable or not sesion:
            return False, "sin codex o sin sesión de Astra apuntada"
        resultado = subprocess.run(
            [ejecutable, "queue", "--thread", sesion, "--message", _una_linea(texto)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=_SIN_VENTANA, timeout=60,
        )
        salida = resultado.stdout.decode("utf-8", "replace").strip()
        # codex queue sale con 0 aunque no encuentre la sesion: manda lo que dice.
        return resultado.returncode == 0 and "error" not in salida.lower(), salida


def _coger_cerrojo(cerrojo: pathlib.Path) -> bool:
    cerrojo.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            descriptor = os.open(str(cerrojo), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                viejo = time.time() - cerrojo.stat().st_mtime > CERROJO_CADUCA_H * 3600
            except OSError:
                viejo = True
            if not viejo:
                return False
            try:
                cerrojo.unlink()
            except OSError:
                return False
            continue
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
        return True
    return False


def _prompt_revision(peticion: Dict[str, Any], base: str, commits: List[Dict[str, Any]],
                     estadistica: str, diff: str, tests_ok: bool, resumen_tests: str) -> str:
    lista = "\n".join("- %s %s" % (c["corto"], c["asunto"]) for c in commits) or "- (ninguno)"
    return (
        "Eres el revisor de Vantelia. GPT-6 Astra pide revisión de la rama %s (commit %s): «%s».\n\n"
        "Lee primero CLAUDE.md, la sección «Si te piden revisar» de AGENTS.md y docs/CAZA_DE_FALLOS.md. "
        "Revisa SOLO estos cambios (desde %s). Puedes leer cualquier fichero y usar git diff/log/show. "
        "No edites nada: tu salida es la revisión.\n\n"
        "Commits:\n%s\n\nFicheros:\n%s\n\n"
        "Tests (los ha ejecutado el sistema en esta misma copia): %s\n%s\n\n"
        "Diff (puede venir recortado; el completo con git diff %s %s):\n```diff\n%s\n```\n\n"
        "Responde en español, para Astra: cada hallazgo con gravedad (crítico / importante / menor), "
        "fichero:línea, el caso concreto que lo rompe y si algún test lo cazaría. Sin caso concreto no es un "
        "hallazgo. Si no hay nada, dilo en una línea.\n"
        "La ÚLTIMA línea tiene que ser exactamente «VEREDICTO: OK» (se puede desplegar) "
        "o «VEREDICTO: CAMBIOS» (hay que arreglar algo antes)."
        % (peticion.get("rama"), str(peticion.get("commit"))[:7], peticion.get("texto"), base[:7], lista,
           estadistica.strip() or "(sin cambios)", "VERDES" if tests_ok else "ROJOS", resumen_tests,
           base[:7], str(peticion.get("commit"))[:7], diff)
    )


def _leer_veredicto(salida: str) -> Optional[str]:
    casados = _VEREDICTO.findall(salida or "")
    return casados[-1].lower() if casados else None


def _hacer_revision(raiz: pathlib.Path, peticion: Dict[str, Any], ejecutor: Ejecutor) -> Dict[str, Any]:
    commit = str(peticion.get("commit") or "")
    comun = {"responde_a": peticion["id"], "rama": peticion.get("rama"), "commit": commit}
    if not _SHA.match(commit) or not _existe(raiz, commit):
        return _escribir_mensaje(raiz, "revisor", "astra", "revision",
                                 "No encuentro el commit %s en el repo." % commit[:7], veredicto="error", **comun)
    copia = pathlib.Path(tempfile.gettempdir()) / (PREFIJO_REVISION + secrets.token_hex(4))
    # site_exports/ tiene rutas que bajo %TEMP% pasan del limite de Windows: sin
    # core.longpaths la copia sale a medias ("Filename too long").
    _git(["-c", "core.longpaths=true", "worktree", "add", "--detach", str(copia), commit], raiz)
    try:
        tests_ok, resumen_tests = ejecutor.pytest(copia)
        base = _git(["merge-base", "main", commit], raiz).strip() or commit
        commits = _commits(raiz, [base + ".." + commit], limite=30)
        estadistica = _git(["diff", "--stat", base, commit], raiz)
        diff = _git(["diff", base, commit], raiz)
        if len(diff) > 60000:
            diff = diff[:60000] + "\n… (recortado)"
        salida = ejecutor.claude(copia, _prompt_revision(peticion, base, commits, estadistica, diff,
                                                         tests_ok, resumen_tests))
    finally:
        _git(["-c", "core.longpaths=true", "worktree", "remove", "--force", str(copia)], raiz, check=False)
        _git(["worktree", "prune"], raiz, check=False)
    dictamen = _leer_veredicto(salida) or "sin_veredicto"
    texto = salida.strip()
    if not tests_ok:
        # Con tests en rojo no se despliega, diga lo que diga la lectura del diff.
        dictamen = "cambios"
        texto = "Tests en ROJO en tu rama:\n%s\n\n%s" % (resumen_tests, texto)
    return _escribir_mensaje(raiz, "revisor", "astra", "revision", texto[:12000], veredicto=dictamen, **comun)


def _hacer_despliegue(raiz: pathlib.Path, peticion: Dict[str, Any], ejecutor: Ejecutor) -> Dict[str, Any]:
    commit = str(peticion.get("commit") or "")
    comun = {"responde_a": peticion["id"], "rama": peticion.get("rama"), "commit": commit}

    def _no(texto: str) -> Dict[str, Any]:
        return _escribir_mensaje(raiz, "revisor", "astra", "despliegue", texto, veredicto="rechazado", **comun)

    revisado = any(
        m.get("tipo") == "revision" and m.get("commit") == commit and m.get("veredicto") == "ok"
        for m in _buzon(_arboles(raiz))
    )
    if not revisado:
        return _no("No despliego %s: ese commit no tiene una revisión OK de Claude. Pide revisión primero "
                   "(si has hecho commits después de la revisión, hay que revisar el último)." % commit[:7])
    if _git(["rev-parse", "--abbrev-ref", "HEAD"], raiz).strip() != "main":
        return _no("No despliego: el árbol principal (%s) no está en main." % raiz)
    cambios = _cambios_seguidos(raiz)
    if cambios:
        return _no("No despliego: hay cambios sin guardar en main (%s). Alguien está trabajando ahí; "
                   "que Claude lo integre a mano." % ", ".join(cambios[:4]))
    if not _git_ok(["merge-base", "--is-ancestor", commit, "main"], raiz):
        mensaje = ("Merge %s: %s\n\nIntegrado y desplegado a peticion de Pablo, tras revision OK de Claude.\n\n"
                   "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
                   % (peticion.get("rama") or commit[:7], (peticion.get("texto") or "").strip()[:200]))
        try:
            _git(["merge", "--no-ff", "-m", mensaje, commit], raiz)
        except RuntimeError as error:
            _git(["merge", "--abort"], raiz, check=False)
            return _no("No despliego: la fusión con main da conflicto. Que Claude lo integre a mano. (%s)"
                       % str(error)[-300:])
    ok, resumen = ejecutor.desplegar(raiz)
    texto = ("Desplegado en producción." if ok
             else "El despliegue falló y se volvió atrás solo; producción sigue como estaba.") + "\n" + resumen
    return _escribir_mensaje(raiz, "revisor", "astra", "despliegue", texto, veredicto="ok" if ok else "fallo", **comun)


def _copia_temporal(raiz: pathlib.Path, ref: str, rama_nueva: str = "", en_rama: bool = False) -> pathlib.Path:
    """Un worktree en %TEMP% para trabajar sin tocar el arbol de nadie."""
    copia = pathlib.Path(tempfile.gettempdir()) / (PREFIJO_REVISION + secrets.token_hex(4))
    orden = ["-c", "core.longpaths=true", "worktree", "add"]
    if rama_nueva:
        orden += ["-b", rama_nueva, str(copia), ref]
    elif en_rama:
        orden += [str(copia), ref]
    else:
        orden += ["--detach", str(copia), ref]
    _git(orden, raiz)
    return copia


def _quitar_copia(raiz: pathlib.Path, copia: pathlib.Path) -> None:
    _git(["-c", "core.longpaths=true", "worktree", "remove", "--force", str(copia)], raiz, check=False)
    _git(["worktree", "prune"], raiz, check=False)


def _commit_de_la_peticion(raiz: pathlib.Path, peticion: Dict[str, Any]) -> str:
    commit = str(peticion.get("commit") or "")
    if _SHA.match(commit) and _existe(raiz, commit):
        return commit
    return _git(["rev-parse", "main"], raiz).strip()


def _prompt_ayuda(peticion: Dict[str, Any]) -> str:
    return (
        "Eres Claude Code, compañero de GPT-6 Astra en Vantelia. Astra te pide ayuda desde la rama %s "
        "(commit %s; esta copia es ese commit): «%s».\n\n"
        "Lee CLAUDE.md y lo que haga falta del repo (docs/MAPA_DEL_CODIGO.md dice dónde está cada cosa; "
        "docs/CAZA_DE_FALLOS.md, las trampas que ya costaron un incidente). Contesta en español, útil y "
        "concreto: dónde está (fichero:línea), por qué está así si hay un incidente detrás, qué harías tú y "
        "qué riesgos ves. Si no se puede contestar mirando el repo (datos de producción, una decisión de "
        "Pablo), dilo claro y di quién puede. No edites nada."
        % (peticion.get("rama"), str(peticion.get("commit"))[:7], peticion.get("texto"))
    )


def _prompt_encargo(peticion: Dict[str, Any], rama: str, base: str) -> str:
    return (
        "Eres Claude Code, compañero de GPT-6 Astra en Vantelia. Astra te encarga: «%s».\n\n"
        "Trabajas en una copia aparte, en tu propia rama %s, que parte de su commit %s. Lee CLAUDE.md "
        "(reglas del repo) y docs/CAZA_DE_FALLOS.md (trampas).\n"
        "- Commits pequeños, cada uno con el porqué y la línea final "
        "«Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>».\n"
        "- Corre los tests que toquen (python -m pytest tests/<fichero>): un test que no falla sin el "
        "arreglo no prueba nada.\n"
        "- No despliegues, no uses la red y no toques secretos (.env, tokens) ni storage/.\n"
        "- Si algo no se puede hacer bien desde aquí, no lo fuerces: explícalo.\n"
        "Al terminar, resume para Astra en pocas líneas: qué has hecho, qué falta y cómo integrarlo."
        % (peticion.get("texto"), rama, base[:7])
    )


def _hacer_ayuda(raiz: pathlib.Path, peticion: Dict[str, Any], ejecutor: Ejecutor) -> Dict[str, Any]:
    commit = _commit_de_la_peticion(raiz, peticion)
    copia = _copia_temporal(raiz, commit)
    try:
        salida = ejecutor.claude(copia, _prompt_ayuda(peticion))
    finally:
        _quitar_copia(raiz, copia)
    return _escribir_mensaje(raiz, "revisor", peticion.get("de") or "astra", "respuesta", salida.strip()[:12000],
                             responde_a=peticion["id"], rama=peticion.get("rama"), commit=commit)


def _hacer_encargo(raiz: pathlib.Path, peticion: Dict[str, Any], ejecutor: Ejecutor) -> Dict[str, Any]:
    base = _commit_de_la_peticion(raiz, peticion)
    rama = "claude/encargo-" + str(peticion["id"])[-6:]
    # Si un intento anterior se corto (sin creditos), se sigue donde se quedo.
    if _git_ok(["rev-parse", "--verify", "--quiet", "refs/heads/" + rama], raiz):
        copia = _copia_temporal(raiz, rama, en_rama=True)
    else:
        copia = _copia_temporal(raiz, base, rama_nueva=rama)
    try:
        salida = ejecutor.claude_escribe(copia, _prompt_encargo(peticion, rama, base))
        if _sin_guardar(copia)[0]:
            # Lo que quede sin commit se guarda: si no, se iria con la copia temporal.
            _git(["add", "-A"], copia)
            _git(["commit", "-q", "-m",
                  "wip: %s (sin terminar; lo guarda el revisor para que no se pierda)\n\n"
                  "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
                  % re.sub(r"\s+", " ", str(peticion.get("texto") or ""))[:60]], copia)
    finally:
        _quitar_copia(raiz, copia)
        # Si se corto antes de hacer nada (sin creditos), no se deja una rama vacia
        # colgando; si llego a hacer commits, se conserva para seguir.
        if _git(["rev-list", "--count", base + ".." + rama], raiz, check=False).strip() in ("", "0"):
            _git(["branch", "-D", rama], raiz, check=False)
    comun = {"responde_a": peticion["id"], "rama": peticion.get("rama"), "commit": base}
    para = peticion.get("de") or "astra"
    hechos = _commits(raiz, [base + ".." + rama], limite=30) if _git_ok(
        ["rev-parse", "--verify", "--quiet", "refs/heads/" + rama], raiz) else []
    if not hechos:
        return _escribir_mensaje(raiz, "revisor", para, "entrega",
                                 ("No he llegado a cambiar nada.\n\n" + salida.strip())[:12000],
                                 veredicto="sin_cambios", **comun)
    lista = "\n".join("- %s %s" % (c["corto"], c["asunto"]) for c in hechos)
    texto = ("Hecho en la rama %s (parte de tu commit %s):\n%s\n\nPara usarlo: git merge %s en tu rama, "
             "y pide revisión como siempre.\n\n%s" % (rama, base[:7], lista, rama, salida.strip()))
    return _escribir_mensaje(raiz, "revisor", para, "entrega", texto[:12000],
                             veredicto="hecho", rama_claude=rama, **comun)


def _aviso_para_astra(respuesta: Dict[str, Any]) -> str:
    donde = "%s (%s)" % (respuesta.get("rama") or "tu rama", str(respuesta.get("commit") or "")[:7])
    dictamen = respuesta.get("veredicto")
    pie = " El detalle te sale al ponerte al día: python scripts/sincronia.py --al-dia astra"
    if respuesta.get("tipo") == "encargo":
        return ("[Encargo de Claude Code, no lo escribe Pablo] " + str(respuesta.get("texto") or "")
                + " Trátalo como una tarea más, salvo que choque con lo que te haya pedido Pablo (entonces "
                "pregúntale), y cuéntaselo a Pablo en una línea." + pie)
    if respuesta.get("tipo") == "respuesta":
        return ("[Aviso automático de Claude Code, no lo escribe Pablo] He contestado tu pregunta: "
                + re.sub(r"\s+", " ", str(respuesta.get("texto") or ""))[:450] + pie)
    if respuesta.get("tipo") == "entrega":
        rama = respuesta.get("rama_claude") or ""
        cuerpo = ("He hecho tu encargo en la rama %s. Intégralo con git merge %s en tu rama y pide revisión "
                  "como siempre; cuéntaselo a Pablo en una línea." % (rama, rama) if dictamen == "hecho"
                  else "No he podido completar tu encargo: te explico por qué en el buzón.")
        return "[Aviso automático de Claude Code, no lo escribe Pablo] " + cuerpo + pie
    if respuesta.get("tipo") == "revision":
        cuerpos = {
            "ok": "He revisado %s: OK, tests en verde. Díselo a Pablo y pregúntale si lo despliego." % donde,
            "cambios": ("He revisado %s: hay cosas que arreglar. Arréglalas en la misma rama y vuelve a pedir "
                        "revisión; cuéntaselo a Pablo en una línea." % donde),
        }
        cuerpo = cuerpos.get(dictamen, "No he podido cerrar la revisión de %s. Díselo a Pablo." % donde)
    else:
        cuerpos = {
            "ok": "Desplegado %s en producción. Díselo a Pablo." % donde,
            "fallo": "El despliegue de %s falló y se volvió atrás solo. Díselo a Pablo." % donde,
        }
        cuerpo = cuerpos.get(dictamen, "No he desplegado %s: te explico por qué en el buzón. Díselo a Pablo." % donde)
    return "[Aviso automático de Claude Code, no lo escribe Pablo] " + cuerpo + pie


def _entregar_a_astra(raiz: pathlib.Path, texto: str, ejecutor: Ejecutor,
                      home: Optional[pathlib.Path] = None) -> Tuple[bool, str]:
    astra = _agentes_fuera(_casa(home), _ahora())["astra"]
    # La del hook si la hay; si no (hook sin aprobar), su ultima sesion de Codex en Vantelia.
    sesion = str((_fichajes(_arboles(raiz)).get("astra") or {}).get("sesion") or astra.get("sesion") or "")
    if astra.get("sin_creditos"):
        # Entregarselo solo abriria un turno que falla y se perderia: le espera en el buzon.
        return False, "Astra está sin créditos; lo verá al volver"
    return ejecutor.entregar(sesion, texto)


def revisor(desde: pathlib.Path, ejecutor: Optional[Ejecutor] = None,
            home: Optional[pathlib.Path] = None) -> str:
    """Atiende la peticion mas antigua sin contestar. Una por pasada; nunca dos a la vez."""
    raiz = raiz_del_repo(desde)
    ejecutor = ejecutor or Ejecutor()
    ahora = _ahora()
    pendientes = _pendientes(_buzon(_arboles(raiz)))
    if not pendientes:
        return "Nada pendiente."
    limite = _limite_de_claude(raiz, ahora)
    if limite["sin_creditos"]:
        # Sin Claude no hay revision; un despliegue ya revisado no lo necesita.
        pendientes = [p for p in pendientes if p.get("tipo") == "desplegar"]
        if not pendientes:
            return ("Claude está sin créditos hasta las %s: lo que le habéis pedido espera."
                    % _hora_corta(limite.get("hasta")))
    cerrojo = raiz / DIR_LOCAL / "revisor.lock"
    if not _coger_cerrojo(cerrojo):
        return "El revisor ya está con otra petición."
    peticion = pendientes[0]
    estado = raiz / DIR_LOCAL / "revisor.json"
    try:
        estado.write_text(json.dumps({
            "haciendo": peticion.get("tipo"), "rama": peticion.get("rama"),
            "commit": str(peticion.get("commit") or "")[:7], "desde": _iso(_ahora()),
        }), encoding="utf-8")
        try:
            tipo = peticion.get("tipo")
            if tipo == "revisar":
                respuesta = _hacer_revision(raiz, peticion, ejecutor)
            elif tipo == "desplegar":
                respuesta = _hacer_despliegue(raiz, peticion, ejecutor)
            elif tipo == "ayuda":
                respuesta = _hacer_ayuda(raiz, peticion, ejecutor)
            else:
                respuesta = _hacer_encargo(raiz, peticion, ejecutor)
        except SinCreditos as error:
            # No es un fallo de la peticion: se queda pendiente y se reintenta al renovarse.
            hasta = error.hasta or (ahora + dt.timedelta(minutes=30))
            (raiz / DIR_LOCAL / "claude_limite.json").write_text(json.dumps({
                "hasta": _iso(hasta), "motivo": str(error)[:300], "cuando": _iso(_ahora()),
            }), encoding="utf-8")
            return "Claude está sin créditos hasta las %s: %s de %s espera." % (
                _hora_corta(_iso(hasta)), _TIPOS.get(str(peticion.get("tipo")), "la petición"),
                peticion.get("rama") or "")
        except Exception as error:  # que una peticion rota no se reintente para siempre
            respuesta = _escribir_mensaje(
                raiz, "revisor", peticion.get("de") or "astra", _RESPUESTA.get(str(peticion.get("tipo")), "nota"),
                "No pude atender la petición: %s" % error, veredicto="error",
                responde_a=peticion["id"], rama=peticion.get("rama"), commit=peticion.get("commit"))
    finally:
        for fichero in (estado, cerrojo):
            try:
                fichero.unlink()
            except OSError:
                pass
    entregado, detalle = _entregar_a_astra(raiz, _aviso_para_astra(respuesta), ejecutor, home)
    return "%s %s → %s (%s)" % (
        peticion.get("tipo"), peticion.get("rama") or "", respuesta.get("veredicto"),
        "entregado a Astra" if entregado else "queda en el buzón: " + detalle[:120])


# --- enviar -----------------------------------------------------------------------

def _leer_token(raiz: pathlib.Path) -> str:
    try:
        return (raiz / DIR_LOCAL / "token").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def enviar(desde: pathlib.Path, url: Optional[str] = None, token: Optional[str] = None) -> str:
    raiz = raiz_del_repo(desde)
    token = token or os.environ.get("SINCRONIA_TOKEN", "").strip() or _leer_token(raiz)
    if not token:
        return "Sin token (%s/token): no se envía nada." % DIR_LOCAL
    foto = construir_foto(desde)
    peticion = urllib.request.Request(
        url or os.environ.get("SINCRONIA_URL", "").strip() or URL_POR_DEFECTO,
        data=json.dumps(foto, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
            "User-Agent": "vantelia-sincronia/1",
        },
    )
    try:
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            codigo = respuesta.status
    except urllib.error.HTTPError as error:
        return "El servidor respondió %s." % error.code
    except (urllib.error.URLError, OSError) as error:
        return "No se pudo enviar: %s" % error
    return "Enviada (%s): %s" % (codigo, foto["veredicto"]["titulo"])


def _anotar(raiz: pathlib.Path, fichero: str, resultado: str) -> None:
    try:
        carpeta = raiz / DIR_LOCAL
        carpeta.mkdir(exist_ok=True)
        (carpeta / fichero).write_text("%s %s\n" % (_iso(_ahora()), resultado), encoding="utf-8")
    except OSError:
        pass


def _enviar_en_segundo_plano(desde: pathlib.Path) -> None:
    """Tras ponerse al dia, que la pagina se entere ya y no a los 5 minutos. Nunca bloquea."""
    ejecutable = pathlib.Path(sys.executable)
    sin_consola = ejecutable.with_name("pythonw.exe")
    if os.name == "nt" and sin_consola.exists():
        ejecutable = sin_consola
    opciones: Dict[str, Any] = {}
    if os.name == "nt":
        opciones["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
    else:
        opciones["start_new_session"] = True
    try:
        subprocess.Popen(
            [str(ejecutable), str(pathlib.Path(__file__).resolve()), "--enviar"],
            cwd=str(desde),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **opciones
        )
    except OSError:
        pass


# --- terminal ---------------------------------------------------------------------

def _resumen_terminal(foto: Dict[str, Any]) -> str:
    semaforo = foto["veredicto"]
    lineas = [
        "Sincronía — %s" % _hora_local(foto["generada"]),
        "[%s] %s" % (semaforo["color"].upper(), semaforo["titulo"]),
        "  " + semaforo["detalle"],
        "",
    ]
    for agente in foto["agentes"]:
        if agente["estado"] == "nunca":
            estado = "nunca se ha puesto al día"
        else:
            estado = "%s (se puso al día %s)" % (
                "al día" if agente["estado"] == "al_dia" else "le faltan %d cambio(s)" % agente["no_vistos_total"],
                _hora_local(agente["ultima_puesta_al_dia"]))
        if agente.get("sin_creditos"):
            estado += " · SIN CRÉDITOS hasta %s" % (_hora_corta(agente.get("creditos_hasta")) or "?")
        lineas.append("%-7s %s · actividad %s" % (
            agente["nombre"] + ":", estado, _hora_local(agente["ultima_actividad"])))
    for arbol in foto["arboles"]:
        estado = "%d sin guardar" % arbol["sin_guardar_total"] if arbol["sin_guardar_total"] else "limpio"
        lineas.append("Árbol %s (%s): %s" % (arbol["ruta"], arbol["rama"] or "sin rama", estado))
    for rama in foto["ramas_sin_integrar"]:
        lineas.append("Sin integrar en main: %s (%d)" % (rama["rama"], rama["commits"]))
    if foto.get("revisor"):
        lineas.append("Revisor: %s %s desde %s" % (foto["revisor"].get("haciendo"), foto["revisor"].get("rama"),
                                                     _hora_local(foto["revisor"].get("desde"))))
    lineas.append("Peticiones sin contestar: %d · mensajes en el buzón: %d" % (foto["pendientes"], len(foto["buzon"])))
    lineas.append("Página: %s" % PAGINA)
    return "\n".join(lineas)


def _preparar_salida() -> None:
    for nombre in ("stdout", "stderr"):
        flujo = getattr(sys, nombre)
        if flujo is None:  # pythonw: no hay consola
            setattr(sys, nombre, open(os.devnull, "w", encoding="utf-8"))
            continue
        reconfigurar = getattr(flujo, "reconfigure", None)
        if reconfigurar is not None:
            try:
                reconfigurar(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _datos_del_hook() -> Dict[str, Any]:
    try:
        crudo = sys.stdin.read() if sys.stdin is not None else ""
        datos = json.loads(crudo or "{}")
    except (ValueError, OSError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _desde_donde(cwd: Optional[str] = None) -> pathlib.Path:
    """El arbol desde el que se llama; si no es un repo, el del propio script."""
    try:
        return _arbol_de(pathlib.Path(cwd) if cwd else pathlib.Path.cwd())
    except (RuntimeError, OSError):
        return pathlib.Path(__file__).resolve().parents[1]


def main(argv: Optional[List[str]] = None) -> int:
    _preparar_salida()
    parser = argparse.ArgumentParser(description="Sincronía entre Claude Code y GPT-6 Astra.")
    parser.add_argument("--al-dia", choices=sorted(AGENTES), help="ponerse al día")
    parser.add_argument("--hook", action="store_true", help="lo llama un hook: lee su JSON por stdin")
    parser.add_argument("--solo-novedades", action="store_true", help="no imprimir nada si no hay nada nuevo")
    parser.add_argument("--pedir-revision", metavar="QUE", help="Astra pide a Claude que revise su rama")
    parser.add_argument("--pedir-despliegue", metavar="QUE", help="Astra pide desplegar lo revisado")
    parser.add_argument("--pedir-ayuda", metavar="PREGUNTA", help="Astra pregunta algo a Claude (contesta solo)")
    parser.add_argument("--encargar", nargs=3, metavar=("DE", "PARA", "TAREA"), help="encargar trabajo al otro agente")
    parser.add_argument("--avisar", nargs=3, metavar=("DE", "PARA", "TEXTO"), help="dejar una nota en el buzón")
    parser.add_argument("--revisor", action="store_true", help="atender la petición pendiente más antigua")
    parser.add_argument("--enviar", action="store_true", help="mandar la foto a app.vantelia.es")
    parser.add_argument("--json", action="store_true", help="imprimir la foto entera en JSON")
    args = parser.parse_args(argv)
    # Las tareas programadas arrancan en System32: para ellas vale el repo del script.
    del_script = pathlib.Path(__file__).resolve().parents[1]
    try:
        if args.al_dia:
            datos = _datos_del_hook() if args.hook else {}
            # Codex y Claude lanzan el hook en el directorio de la sesion: si el JSON no
            # se deja leer, ese directorio dice igual de que proyecto es la sesion.
            cwd = str(datos.get("cwd") or (os.getcwd() if args.hook else ""))
            if args.hook and "vantelia" not in cwd.lower():
                return 0  # hook de usuario en una sesion de otro proyecto: no es asunto nuestro
            desde = _desde_donde(cwd or None)
            informe = fichar(desde, args.al_dia, sesion=str(datos.get("session_id") or ""),
                             solo_novedades=args.solo_novedades)
            if informe:
                print(informe)
            _enviar_en_segundo_plano(desde)
            return 0
        if args.pedir_revision is not None or args.pedir_despliegue is not None or args.pedir_ayuda is not None:
            desde = _desde_donde()
            if args.pedir_revision is not None:
                ok, texto = pedir_revision(desde, args.pedir_revision)
            elif args.pedir_despliegue is not None:
                ok, texto = pedir_despliegue(desde, args.pedir_despliegue)
            else:
                ok, texto = pedir_ayuda(desde, args.pedir_ayuda)
            print(texto)
            if ok:
                _enviar_en_segundo_plano(desde)
            return 0 if ok else 1
        if args.encargar:
            de, para, tarea = args.encargar
            desde = _desde_donde()
            ok, texto = encargar(desde, de.lower(), para.lower(), tarea)
            print(texto)
            if ok:
                _enviar_en_segundo_plano(desde)
            return 0 if ok else 1
        if args.avisar:
            de, para, texto = args.avisar
            avisar(_desde_donde(), de.lower(), para.lower(), texto)
            print("Nota dejada en el buzón para %s." % _nombre(para.lower()))
            return 0
        if args.revisor:
            resultado = revisor(del_script)
            _anotar(raiz_del_repo(del_script), "revisor.log", resultado)
            print(resultado)
            return 0
        if args.enviar:
            resultado = enviar(del_script)
            _anotar(raiz_del_repo(del_script), "envio.log", resultado)
            print(resultado)
            return 0
        foto = construir_foto(_desde_donde())
        print(json.dumps(foto, ensure_ascii=False, indent=2) if args.json else _resumen_terminal(foto))
        return 0
    except (RuntimeError, OSError, ValueError) as error:
        print("Sincronía: no se pudo mirar el repo (%s)." % error)
        # Ponerse al dia corre desde los hooks: si falla, que no tumbe la sesion.
        return 0 if args.al_dia else 1


if __name__ == "__main__":
    sys.exit(main())
