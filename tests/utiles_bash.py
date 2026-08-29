# -*- coding: utf-8 -*-
r"""Ejecutar los guiones del VPS desde los tests, sin depender de la maquina.

POR QUE EXISTE
--------------
Dos tests ejecutan de verdad los guiones que viajan al servidor: el que vigila
que el entorno de pruebas no arranque con credenciales reales y el que vigila
que el rollback no se lleve por delante los datos. Los dos elegian el
interprete con `shutil.which("bash")`, y eso hace que el resultado dependa de
desde donde se lancen:

- Desde **Git Bash** el PATH lleva `/usr/bin`, sale el bash bueno y pasan.
- Desde **PowerShell** -que es como corre `deploy\deploy.ps1`- sale
  `C:\Windows\system32\bash.exe`, el de **WSL**, que monta el disco en
  `/mnt/c` y no ve `/c/Users/...`: el guion "no existe" (codigo 127) y el
  deploy se para en seco sin que haya nada roto.
- Y `C:\Program Files\Git\bin\bash.exe` no es bash, es un **lanzador**: se
  queda con la salida abierta y `subprocess.run(capture_output=True)` espera
  para siempre a un proceso que ya termino.

Verde en local y rojo en el deploy con el MISMO commit. Por eso el bash no se
coge del PATH: se PRUEBA contra una ruta que existe.

Vive aqui y no en cada test para que el arreglo no tenga dos copias: la segunda
se queda vieja y vuelve el mismo dia raro.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_ELEGIDO = []  # cache: [] sin resolver, [None] no hay, [ruta] el bueno

# Un guion de despliegue corre solo en el servidor: si alguna vez se queda
# esperando algo, el test tiene que fallar, no colgarse.
PLAZO = 120


def ruta_posix(ruta: str) -> str:
    """La forma que entiende bash de una ruta de Windows."""
    ruta = ruta.replace("\\", "/")
    if len(ruta) > 1 and ruta[1] == ":":
        return "/" + ruta[0].lower() + ruta[2:]
    return ruta


def _carpetas_donde_buscar():
    """El PATH y, en Windows, donde vive Git Bash aunque no este en el PATH.

    El PATH de PowerShell no suele llevar Git Bash; el de Git Bash si. Buscar
    solo en el PATH hacia que estos tests se saltaran justo desde donde corre
    el deploy, que es cuando mas falta hacen.
    """
    for carpeta in os.environ.get("PATH", "").split(os.pathsep):
        if carpeta:
            yield carpeta
    if os.name != "nt":
        return
    git = shutil.which("git")
    if git:
        # C:/.../Git/mingw64/bin/git.exe -> C:/.../Git/{usr/bin,bin}
        raiz_git = os.path.dirname(os.path.dirname(os.path.dirname(git)))
        yield os.path.join(raiz_git, "usr", "bin")
        yield os.path.join(raiz_git, "bin")
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if not base:
            continue
        for carpeta_git in ("Git", os.path.join("Programs", "Git")):
            yield os.path.join(base, carpeta_git, "usr", "bin")
            yield os.path.join(base, carpeta_git, "bin")


def _candidatos():
    """Todos los bash visibles, no solo el primero del PATH.

    `usr/bin` va antes que `bin` a proposito: ver el lanzador, arriba.
    """
    vistos = set()
    nombres = ("bash.exe", "bash") if os.name == "nt" else ("bash",)
    for carpeta in _carpetas_donde_buscar():
        for nombre in nombres:
            ruta = os.path.normpath(os.path.join(carpeta, nombre))
            clave = ruta.lower() if os.name == "nt" else ruta
            if clave not in vistos and os.path.isfile(ruta):
                vistos.add(clave)
                yield ruta


def bash() -> str:
    """Un bash que entienda las rutas que estos tests le pasan."""
    if not _ELEGIDO:
        prueba = ruta_posix(RAIZ)
        elegido = None
        for candidato in _candidatos():
            try:
                resultado = subprocess.run(
                    [candidato, "-c", 'test -d "$1"', "_", prueba],
                    capture_output=True,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if resultado.returncode == 0:
                elegido = candidato
                break
        _ELEGIDO.append(elegido)
    if _ELEGIDO[0] is None:
        pytest.skip("no hay un bash que entienda las rutas de este entorno")
    return _ELEGIDO[0]


def herramientas_de(ejecutable: str):
    """Las carpetas con sleep, tar, cp... del bash elegido.

    El guion usa coreutils. Lanzado desde Git Bash vienen en el PATH heredado;
    lanzado desde PowerShell no, y un `sleep` que no existe dentro de un
    `while` convierte una espera en un bucle infinito.
    """
    carpeta = os.path.dirname(ejecutable)
    raiz = os.path.dirname(carpeta)
    candidatas = [carpeta, os.path.join(raiz, "usr", "bin"), os.path.join(raiz, "bin")]
    if os.path.basename(raiz).lower() == "usr":
        candidatas.append(os.path.join(os.path.dirname(raiz), "bin"))
    vistas, salida = set(), []
    for candidata in candidatas:
        candidata = os.path.normpath(candidata)
        clave = candidata.lower() if os.name == "nt" else candidata
        if clave not in vistas and os.path.isdir(candidata):
            vistas.add(clave)
            salida.append(candidata)
    return salida


def entorno_con(stubs: str, **extras) -> dict:
    """PATH minimo y a proposito: los stubs y las herramientas del propio bash.

    NO se hereda el PATH de quien lanza los tests: heredarlo hacia que el guion
    encontrara binarios de Windows y el resultado dependiera de la maquina. En
    el VPS el PATH tampoco es el de un escritorio.
    """
    entorno = dict(os.environ)
    partes = [stubs] + herramientas_de(bash())
    if os.name != "nt":
        partes += ["/usr/bin", "/bin"]
    entorno["PATH"] = os.pathsep.join(parte for parte in partes if parte)
    entorno.update(extras)
    return entorno


def ejecutar(argumentos, stubs: str, **extras):
    """Corre un guion del VPS: sin stdin, con plazo y con el bash correcto."""
    return subprocess.run(
        [bash()] + list(argumentos),
        capture_output=True,
        text=True,
        env=entorno_con(stubs, **extras),
        stdin=subprocess.DEVNULL,
        timeout=PLAZO,
    )
