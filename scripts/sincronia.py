#!/usr/bin/env python
"""Sincronía entre los agentes que trabajan en este repo (Claude Code y GPT-6 Astra).

Los dos agentes no se ven: cada uno tiene su propia memoria y lo único que
comparten es el repo. Este script contesta a la pregunta de Pablo -"si cambio de
agente ahora, ¿el otro sabe lo que ha hecho el primero?"- mirando solo cosas que
no dependen de lo que digan ellos: git, los worktrees y cuándo se puso al día
cada uno por última vez.

    python scripts/sincronia.py --al-dia claude    lo primero de cada sesión
    python scripts/sincronia.py --al-dia astra
    python scripts/sincronia.py                    el semáforo, en la terminal
    python scripts/sincronia.py --enviar           manda la foto a app.vantelia.es

Ponerse al día ENSEÑA al agente lo que ha cambiado desde su última vez (commits
de los demás, trabajo sin guardar, lo que hay en curso) y deja constancia en
`.sincronia/<agente>.json` del árbol donde trabaja. Esa constancia es lo que
permite decir "Claude ha visto todo lo de Astra" sin fiarse de su palabra.

Quién hizo cada commit sale del mensaje: una línea `Co-Authored-By: Claude` es
Claude, una línea `Agente: astra` es Astra, y lo demás es Pablo.

El PC de Pablo manda la foto cada 5 minutos (tarea programada de Windows
"Vantelia sincronia") a POST /admin/sincronia; el servidor solo la guarda y le
añade qué commit está desplegado. La página es https://app.vantelia.es/sincronia.
El token va en `.sincronia/token`, que no está en git.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

AGENTES = {"claude": "Claude", "astra": "Astra"}
URL_POR_DEFECTO = "https://app.vantelia.es/admin/sincronia"
PAGINA = "https://app.vantelia.es/sincronia"
DIR_LOCAL = ".sincronia"
# Cambios sin commit que nadie toca desde hace mas de esto: alguien se quedo a
# medias (lo tipico, sin tokens). Si son mas recientes, esta trabajando ahora.
A_MEDIAS_MIN = 30
MAX_LISTA = 12
_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_SHA = re.compile(r"^[0-9a-f]{40}$")
_ETIQUETAS = (
    ("testigo", "Testigo"),
    ("tarea", "Tarea"),
    ("rama", "Rama"),
    ("siguiente", "Siguiente"),
    ("espera_a", "Espera a"),
)
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
    return [a for a in arboles if not a.get("perdido") and pathlib.Path(a["ruta"]).exists()]


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
    resultado = subprocess.run(
        ["git", "cat-file", "-e", sha + "^{commit}"],
        cwd=str(raiz),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_SIN_VENTANA,
    )
    return resultado.returncode == 0


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
        # Los fichajes de este script no son trabajo de nadie.
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
                datos[clave] = casa.group(2).strip("* ").strip()
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
            if agente not in fichajes or str(datos.get("cuando") or "") > str(fichajes[agente].get("cuando") or ""):
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


def _ultima_actividad(home: pathlib.Path) -> Dict[str, Optional[dt.datetime]]:
    """Cuando trabajo cada agente en Vantelia por ultima vez. Solo la hora, nunca el contenido."""
    actividad: Dict[str, Optional[dt.datetime]] = {"claude": None, "astra": None}
    for fichero in (home / ".claude" / "projects").glob("*antelia*/*.jsonl"):
        actividad["claude"] = _mas_reciente(actividad["claude"], fichero)
    candidatos = []
    for fichero in (home / ".codex" / "sessions").glob("*/*/*/rollout-*.jsonl"):
        try:
            candidatos.append((fichero.stat().st_mtime, str(fichero)))
        except OSError:
            continue
    # Codex tambien se usa para otras cosas: solo cuentan las sesiones abiertas en Vantelia.
    for _, ruta in sorted(candidatos, reverse=True)[:60]:
        if "vantelia" in _cwd_de_la_sesion(pathlib.Path(ruta)).lower():
            actividad["astra"] = _mas_reciente(None, pathlib.Path(ruta))
            break
    return actividad


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
    if a_medias:
        arbol = a_medias[0]
        return {
            "color": "rojo",
            "titulo": "Hay trabajo a medias sin guardar",
            "detalle": (
                "En %s (%s) hay %d cambio(s) sin commit que nadie toca desde hace más de %d min. "
                "Si a alguien se le acabaron los tokens, dile al otro: «ponte al día y sigue donde se quedó»."
                % (arbol["ruta"], arbol.get("rama") or "sin rama", arbol["sin_guardar_total"], A_MEDIAS_MIN)
            ),
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
            "detalle": (
                "Cada uno se pone al día solo al empezar su sesión. "
                "Si vas a cambiar de agente ahora, dile primero: «ponte al día»."
            ),
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
    actividad = _ultima_actividad(pathlib.Path(home) if home else pathlib.Path.home())

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
            "ultima_actividad": _iso(actividad.get(agente)),
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

    foto: Dict[str, Any] = {
        "version": 1,
        "generada": _iso(ahora),
        "veredicto": {},
        "en_curso": _en_curso(arboles_git),
        "agentes": agentes,
        "arboles": arboles,
        "ramas_sin_integrar": sin_integrar,
        "main": _commits(raiz, ["main"], limite=30) if "main" in ramas else [],
    }
    foto["veredicto"] = veredicto(foto, ahora)
    return foto


# --- ponerse al dia ---------------------------------------------------------------

def _agente(foto: Dict[str, Any], agente: str) -> Dict[str, Any]:
    return next(a for a in foto["agentes"] if a["id"] == agente)


def _nombre(agente: str) -> str:
    return AGENTES.get(agente, "Pablo")


def _informe(antes: Dict[str, Any], despues: Dict[str, Any], agente: str) -> str:
    yo = _agente(antes, agente)
    lineas = ["== Sincronía: puesta al día de %s ==" % yo["nombre"]]
    if yo["estado"] == "nunca":
        lineas.append("Primera puesta al día: no hay registro de lo que viste antes. Lee docs/ESTADO_ACTUAL.md entero.")
    elif yo["no_vistos_total"]:
        lineas.append("Lo nuevo de los demás desde tu última vez (%s):" % _hora_local(yo["ultima_puesta_al_dia"]))
        for commit in yo["no_vistos"]:
            lineas.append("  %s [%s] %s" % (commit["corto"], _nombre(commit["agente"]), commit["asunto"]))
        resto = yo["no_vistos_total"] - len(yo["no_vistos"])
        if resto > 0:
            lineas.append("  … y %d más (git log)" % resto)
        lineas.append("Míralos (git show <sha>) antes de tocar nada.")
    else:
        lineas.append("Nada nuevo de los demás en git desde tu última vez (%s)." % _hora_local(yo["ultima_puesta_al_dia"]))
    for arbol in antes.get("arboles") or []:
        if arbol.get("sin_guardar_total"):
            muestra = ", ".join(arbol["sin_guardar"][:6])
            if arbol["sin_guardar_total"] > 6:
                muestra += " …"
            lineas.append("Sin guardar en %s (%s): %s" % (arbol["ruta"], arbol.get("rama") or "sin rama", muestra))
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
    lineas.append("Queda apuntado que lo has visto. Pablo lo ve en %s" % PAGINA)
    return "\n".join(lineas)


def fichar(
    desde: pathlib.Path, agente: str, ahora: Optional[dt.datetime] = None, home: Optional[pathlib.Path] = None
) -> str:
    """Pone al dia al agente: le devuelve lo que tiene que leer y deja constancia de que lo vio."""
    if agente not in AGENTES:
        raise ValueError("Agente desconocido: %s" % agente)
    ahora = ahora or _ahora()
    antes = construir_foto(desde, ahora=ahora, home=home)
    arbol = _arbol_de(desde)
    carpeta = arbol / DIR_LOCAL
    carpeta.mkdir(exist_ok=True)
    registro = {"agente": agente, "cuando": _iso(ahora), "vio": _ramas(raiz_del_repo(desde)), "arbol": str(arbol)}
    (carpeta / ("%s.json" % agente)).write_text(json.dumps(registro, indent=2), encoding="utf-8")
    despues = construir_foto(desde, ahora=ahora, home=home)
    return _informe(antes, despues, agente)


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


def _anotar_envio(raiz: pathlib.Path, resultado: str) -> None:
    try:
        carpeta = raiz / DIR_LOCAL
        carpeta.mkdir(exist_ok=True)
        (carpeta / "envio.log").write_text("%s %s\n" % (_iso(_ahora()), resultado), encoding="utf-8")
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
        lineas.append("%-7s %s · actividad %s" % (
            agente["nombre"] + ":", estado, _hora_local(agente["ultima_actividad"])))
    for arbol in foto["arboles"]:
        estado = "%d sin guardar" % arbol["sin_guardar_total"] if arbol["sin_guardar_total"] else "limpio"
        lineas.append("Árbol %s (%s): %s" % (arbol["ruta"], arbol["rama"] or "sin rama", estado))
    for rama in foto["ramas_sin_integrar"]:
        lineas.append("Sin integrar en main: %s (%d)" % (rama["rama"], rama["commits"]))
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


def _desde_donde() -> pathlib.Path:
    """El arbol desde el que se llama; si no es un repo, el del propio script."""
    try:
        return _arbol_de(pathlib.Path.cwd())
    except (RuntimeError, OSError):
        return pathlib.Path(__file__).resolve().parents[1]


def main(argv: Optional[List[str]] = None) -> int:
    _preparar_salida()
    parser = argparse.ArgumentParser(description="Sincronía entre Claude Code y GPT-6 Astra.")
    parser.add_argument("--al-dia", choices=sorted(AGENTES), help="ponerse al día (lo primero de cada sesión)")
    parser.add_argument("--enviar", action="store_true", help="mandar la foto a app.vantelia.es")
    parser.add_argument("--json", action="store_true", help="imprimir la foto entera en JSON")
    args = parser.parse_args(argv)
    # La tarea programada arranca en System32: para enviar vale el repo del script.
    desde = pathlib.Path(__file__).resolve().parents[1] if args.enviar else _desde_donde()
    try:
        if args.al_dia:
            print(fichar(desde, args.al_dia))
            _enviar_en_segundo_plano(desde)
            return 0
        if args.enviar:
            resultado = enviar(desde)
            _anotar_envio(raiz_del_repo(desde), resultado)
            print(resultado)
            return 0
        foto = construir_foto(desde)
        print(json.dumps(foto, ensure_ascii=False, indent=2) if args.json else _resumen_terminal(foto))
        return 0
    except (RuntimeError, OSError, ValueError) as error:
        print("Sincronía: no se pudo mirar el repo (%s)." % error)
        # Ponerse al dia corre al arrancar una sesion: si falla, que no la tumbe.
        return 0 if args.al_dia else 1


if __name__ == "__main__":
    sys.exit(main())
