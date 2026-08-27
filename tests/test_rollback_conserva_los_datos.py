"""El rollback del VPS revierte el CODIGO y NUNCA los datos del negocio.

Este test existe por un fallo real de la primera version del script: movia el
estado vivo al arbol anterior ANTES de intercambiar los directorios, y cuando el
`mv` fallaba la base de datos se quedaba fuera de produccion. La red de
seguridad empeorando el incidente.

Lo que se vigila aqui, y por que importa:

- El arbol `_prev` lleva dentro copias de `storage/` y `data/` del despliegue
  anterior. Restaurarlo tal cual borraria las citas, chats y pagos entrados
  desde entonces. El estado vivo tiene que VIAJAR al arbol restaurado.
- Si algo sale mal, produccion no puede quedar a medias: sin `_prev` no se
  toca nada, y sin base de datos en su sitio no se arranca (arrancar sin ella
  no da error: crea una vacia, y el negocio veria su agenda borrada).

Se salta si no hay bash (Windows sin Git Bash). En CI corre siempre.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLLBACK_SH = os.path.join(RAIZ, "deploy", "hostinger", "rollback.sh")

DOCKER_STUB = """#!/bin/bash
case "$1 $2" in
  "image inspect") exit 0 ;;
esac
exit 0
"""

CURL_STUB = """#!/bin/bash
echo '{"status":"ok"}'
exit 0
"""


def _bash() -> str:
    ruta = shutil.which("bash")
    if not ruta:
        pytest.skip("bash no disponible en este entorno")
    return ruta


def _ruta_posix(ruta: str) -> str:
    """Convierte una ruta de Windows a la forma que entiende bash.

    En el VPS las rutas ya son POSIX; esto solo existe para que el test corra
    igual en Windows, donde bash se comeria las barras invertidas como escapes.
    """
    if len(ruta) > 1 and ruta[1] == ":":
        return "/" + ruta[0].lower() + ruta[2:].replace("\\", "/")
    return ruta.replace("\\", "/")


def _escribir(ruta: str, contenido: str) -> None:
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as fichero:
        fichero.write(contenido)


def _preparar(tmp_path, con_prev: bool = True):
    """Produccion rota con datos de HOY + arbol anterior con copias viejas."""
    base = str(tmp_path)
    stubs = os.path.join(base, "stubs")
    _escribir(os.path.join(stubs, "docker"), DOCKER_STUB)
    _escribir(os.path.join(stubs, "curl"), CURL_STUB)
    os.chmod(os.path.join(stubs, "docker"), 0o755)
    os.chmod(os.path.join(stubs, "curl"), 0o755)

    proyecto = os.path.join(base, "srv", "vantelia")
    _escribir(os.path.join(proyecto, "marcador.txt"), "CODIGO ROTO")
    _escribir(os.path.join(proyecto, "storage", "vantelia.db"), "CITA DE HOY")
    _escribir(os.path.join(proyecto, "data", "alicia", "info.txt"), "info de hoy")
    _escribir(os.path.join(proyecto, "config.json"), "config vivo")
    _escribir(os.path.join(proyecto, ".env"), "env vivo")
    _escribir(os.path.join(proyecto, "secrets", "token.json"), "secreto vivo")
    _escribir(os.path.join(proyecto, "client_sites", "web.html"), "web parcheada")

    if con_prev:
        previo = proyecto + "_prev"
        _escribir(os.path.join(previo, "marcador.txt"), "CODIGO ANTERIOR")
        _escribir(os.path.join(previo, "storage", "vantelia.db"), "BD DE ANTEAYER")
        _escribir(os.path.join(previo, "data", "alicia", "info.txt"), "info vieja")

    # El script se copia fuera del arbol que va a mover, igual que en el deploy
    # real (se aparta a /tmp) y en el rollback manual (llega por stdin).
    copia = os.path.join(base, "rollback.sh")
    shutil.copyfile(ROLLBACK_SH, copia)
    return base, proyecto, copia, stubs


def _ejecutar(copia, proyecto, stubs):
    entorno = dict(os.environ)
    entorno["PATH"] = stubs + os.pathsep + entorno.get("PATH", "")
    return subprocess.run(
        [_bash(), _ruta_posix(copia), _ruta_posix(proyecto)],
        capture_output=True,
        text=True,
        env=entorno,
    )


def _leer(*partes):
    with open(os.path.join(*partes), encoding="utf-8") as fichero:
        return fichero.read().strip()


def test_rollback_revierte_el_codigo_pero_conserva_los_datos(tmp_path):
    base, proyecto, copia, stubs = _preparar(tmp_path)

    resultado = _ejecutar(copia, proyecto, stubs)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr

    # El codigo vuelve al de antes...
    assert _leer(proyecto, "marcador.txt") == "CODIGO ANTERIOR"

    # ...y todo lo que es del negocio sigue siendo el de hoy.
    assert _leer(proyecto, "storage", "vantelia.db") == "CITA DE HOY"
    assert _leer(proyecto, "data", "alicia", "info.txt") == "info de hoy"
    assert _leer(proyecto, "config.json") == "config vivo"
    assert _leer(proyecto, ".env") == "env vivo"
    assert _leer(proyecto, "secrets", "token.json") == "secreto vivo"
    assert _leer(proyecto, "client_sites", "web.html") == "web parcheada"

    # El arbol que fallaba se guarda para poder mirarlo despues.
    fallidos = [n for n in os.listdir(os.path.join(base, "srv")) if "_failed-" in n]
    assert len(fallidos) == 1


def test_sin_version_anterior_no_toca_nada(tmp_path):
    _base, proyecto, copia, stubs = _preparar(tmp_path, con_prev=False)

    resultado = _ejecutar(copia, proyecto, stubs)

    assert resultado.returncode == 1
    assert "nada que restaurar" in resultado.stderr
    # Produccion sigue exactamente como estaba: rota, pero entera y con sus datos.
    assert _leer(proyecto, "marcador.txt") == "CODIGO ROTO"
    assert _leer(proyecto, "storage", "vantelia.db") == "CITA DE HOY"
