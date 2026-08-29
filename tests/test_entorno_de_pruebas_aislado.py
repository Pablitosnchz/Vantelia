# -*- coding: utf-8 -*-
"""El entorno de pruebas no puede tocar a los clientes de verdad.

POR QUE EXISTE
--------------
Produccion y pruebas viven en el MISMO VPS. Eso ahorra dinero y complica la vida:
si el entorno de pruebas arranca con el token de WhatsApp bueno, una prueba le
escribe a una clienta del salon; si arranca con la clave de Stripe en vivo, cobra
de verdad. Ninguna de las dos cosas tiene vuelta atras, y las dos son a un
descuido de distancia (copiar el .env "para que arranque").

Por eso el deploy no confia: comprueba el .env de pruebas ANTES de construir
nada, y se niega si huele a produccion. Aqui se comprueba que esa negativa
existe de verdad, sobre el MISMO script que se sube al VPS.

Se salta si no hay bash (Windows sin Git Bash). En CI corre siempre.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY_PS1 = os.path.join(RAIZ, "deploy", "deploy.ps1")

DOCKER_STUB = """#!/bin/bash
# Deja constancia de lo que se le pide, para poder afirmar que se llego ahi.
echo "$*" >> "$DOCKER_LOG"
case "$1 $2" in
  "image inspect") exit 1 ;;
esac
exit 0
"""

CURL_STUB = """#!/bin/bash
echo '{"status":"ok"}'
exit 0
"""

SQLITE_STUB = """#!/bin/bash
exit 0
"""


_BASH_ELEGIDO = []  # cache: [] sin resolver, [None] no hay, [ruta] el bueno


def _carpetas_donde_buscar_bash():
    """El PATH y, en Windows, donde vive Git Bash aunque no este en el PATH.

    El PATH de PowerShell no suele llevar Git Bash; el de Git Bash si. Buscar
    solo en el PATH hacia que este test se saltara justo desde donde corre el
    deploy, que es cuando mas falta hace.
    """
    for carpeta in os.environ.get("PATH", "").split(os.pathsep):
        if carpeta:
            yield carpeta
    if os.name != "nt":
        return
    git = shutil.which("git")
    if git:
        # C:/.../Git/mingw64/bin/git.exe -> C:/.../Git/{bin,usr/bin}
        raiz_git = os.path.dirname(os.path.dirname(os.path.dirname(git)))
        # usr/bin ANTES que bin: Git/bin/bash.exe es un lanzador que se queda
        # con la salida abierta, asi que subprocess espera para siempre a un
        # proceso que ya termino. Git/usr/bin/bash.exe es el bash de verdad.
        yield os.path.join(raiz_git, "usr", "bin")
        yield os.path.join(raiz_git, "bin")
    for archivos in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(archivos)
        if not base:
            continue
        for git in ("Git", os.path.join("Programs", "Git")):
            yield os.path.join(base, git, "usr", "bin")
            yield os.path.join(base, git, "bin")


def _candidatos_bash():
    """Todos los bash visibles, no solo el primero del PATH."""
    vistos = set()
    nombres = ("bash.exe", "bash") if os.name == "nt" else ("bash",)
    for carpeta in _carpetas_donde_buscar_bash():
        for nombre in nombres:
            ruta = os.path.normpath(os.path.join(carpeta, nombre))
            clave = ruta.lower() if os.name == "nt" else ruta
            if clave not in vistos and os.path.isfile(ruta):
                vistos.add(clave)
                yield ruta


def _bash() -> str:
    """Un bash que entienda las rutas /c/... que este test le pasa.

    En Windows con WSL instalado, shutil.which("bash") devuelve el bash de WSL
    (C:/Windows/system32/bash.exe), que monta el disco en /mnt/c y NO ve
    /c/Users/...: el guion "no existia" (codigo 127) y el test fallaba por un
    detalle del PATH, no por nada real. Y como el PATH de PowerShell no es el de
    Git Bash, pasaba suelto y tumbaba el deploy. Por eso no se coge el primero:
    se prueba cada uno contra una ruta que existe de verdad.
    """
    if not _BASH_ELEGIDO:
        prueba = _ruta_posix(RAIZ)
        elegido = None
        for candidato in _candidatos_bash():
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
        _BASH_ELEGIDO.append(elegido)
    if _BASH_ELEGIDO[0] is None:
        pytest.skip("no hay un bash que entienda las rutas de este entorno")
    return _BASH_ELEGIDO[0]


def _ruta_posix(ruta: str) -> str:
    """Convierte una ruta de Windows a la forma que entiende bash."""
    ruta = ruta.replace("\\", "/")
    if len(ruta) > 1 and ruta[1] == ":":
        return "/" + ruta[0].lower() + ruta[2:]
    return ruta


def _script_remoto() -> str:
    """El script que deploy.ps1 sube al VPS, tal cual viaja.

    Se extrae del propio deploy.ps1 en vez de tener una copia: una copia se
    quedaria vieja y el test aprobaria un script que ya no es el que se ejecuta.
    """
    with open(DEPLOY_PS1, encoding="utf-8") as fichero:
        contenido = fichero.read()
    encontrado = re.search(r"\$remoteScript = @'\r?\n(.*?)\r?\n'@", contenido, re.S)
    assert encontrado, "no se encuentra el script remoto dentro de deploy.ps1"
    return encontrado.group(1).replace("\r\n", "\n")


def _escribir(ruta: str, contenido: str, ejecutable: bool = False) -> None:
    carpeta = os.path.dirname(ruta)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as fichero:
        fichero.write(contenido)
    if ejecutable:
        os.chmod(ruta, 0o755)


def _montar(tmp_path, env_pruebas, env_produccion="WHATSAPP_ACCESS_TOKEN=TOKEN_REAL_DE_PRODUCCION\n"):
    """Un VPS de mentira con produccion, pruebas y el paquete ya subido."""
    base = str(tmp_path)
    stubs = os.path.join(base, "stubs")
    _escribir(os.path.join(stubs, "docker"), DOCKER_STUB, True)
    _escribir(os.path.join(stubs, "curl"), CURL_STUB, True)
    _escribir(os.path.join(stubs, "sqlite3"), SQLITE_STUB, True)

    # Produccion, para poder comparar credenciales contra ella.
    _escribir(os.path.join(base, "srv", "vantelia", ".env"), env_produccion)

    pruebas = os.path.join(base, "srv", "vantelia-staging")
    os.makedirs(pruebas, exist_ok=True)
    if env_pruebas is not None:
        _escribir(os.path.join(pruebas, ".env"), env_pruebas)

    # El paquete que subiria el deploy, con lo justo para que se pueda extraer.
    contenido = os.path.join(base, "paquete", "vantelia")
    _escribir(os.path.join(contenido, "deploy", "hostinger", "rollback.sh"), "#!/bin/bash\nexit 0\n")
    archivo = os.path.join(base, "srv", "vantelia-staging-deploy.tar.gz")
    with tarfile.open(archivo, "w:gz") as tar:
        tar.add(contenido, arcname="vantelia")

    guion = os.path.join(base, "remoto.sh")
    _escribir(guion, _script_remoto())
    return base, stubs, guion


def _herramientas_del_bash(bash):
    """Las carpetas con sleep, tar, cp... del bash elegido.

    El guion remoto usa coreutils. Lanzado desde Git Bash vienen en el PATH
    heredado; lanzado desde PowerShell no, y un `sleep` que no existe dentro de
    un `while` convierte una espera en un bucle infinito: el test se colgaba en
    vez de fallar. Se anaden explicitamente.
    """
    carpeta = os.path.dirname(bash)
    raiz = os.path.dirname(carpeta)
    candidatas = [carpeta, os.path.join(raiz, "usr", "bin"), os.path.join(raiz, "bin")]
    if os.path.basename(raiz).lower() == "usr":
        candidatas.append(os.path.join(os.path.dirname(raiz), "bin"))
    vistas, salida = set(), []
    for c in candidatas:
        c = os.path.normpath(c)
        clave = c.lower() if os.name == "nt" else c
        if clave not in vistas and os.path.isdir(c):
            vistas.add(clave)
            salida.append(c)
    return salida


def _desplegar_pruebas(base, stubs, guion):
    entorno = dict(os.environ)
    bash = _bash()
    # PATH minimo y a proposito: los stubs y las herramientas del propio bash.
    # NO se hereda el PATH de quien lanza los tests. Heredarlo hacia que el
    # guion encontrara binarios de Windows (Docker Desktop, curl.exe de
    # System32...) y el resultado dependia de la maquina: pasaba lanzado desde
    # Git Bash y se colgaba lanzado desde PowerShell, que es como corre el
    # deploy. En el VPS el PATH tampoco es el de un escritorio.
    partes = [stubs] + _herramientas_del_bash(bash)
    if os.name != "nt":
        partes += ["/usr/bin", "/bin"]
    entorno["PATH"] = os.pathsep.join(p for p in partes if p)
    entorno["DOCKER_LOG"] = _ruta_posix(os.path.join(base, "docker.log"))
    argumentos = [
        bash, _ruta_posix(guion),
        _ruta_posix(os.path.join(base, "srv")),                    # REMOTE_BASE
        _ruta_posix(os.path.join(base, "srv", "vantelia-staging")),  # REMOTE_PROJECT
        "vantelia-staging-deploy.tar.gz",
        "deploy/hostinger/docker-compose.staging.yml",
        "vantelia-staging", "vantelia-staging", "8001", "staging",
        _ruta_posix(os.path.join(base, "backups")),
        _ruta_posix(os.path.join(base, "srv", "vantelia", ".env")),
    ]
    # Sin stdin y con plazo: el guion corre solo en el VPS, y si alguna vez se
    # queda esperando algo tiene que fallar el test, no colgarlo.
    return subprocess.run(
        argumentos,
        capture_output=True,
        text=True,
        env=entorno,
        stdin=subprocess.DEVNULL,
        timeout=120,
    )


# ─── Las tres formas de colarse con credenciales de verdad ────────────────

def test_sin_env_propio_no_despliega(tmp_path):
    """No se hereda el .env de produccion "para que arranque"."""
    base, stubs, guion = _montar(tmp_path, env_pruebas=None)

    resultado = _desplegar_pruebas(base, stubs, guion)

    assert resultado.returncode == 1
    assert "no tiene su propio .env" in resultado.stderr
    assert "No se copia el de produccion" in resultado.stderr


def test_con_clave_de_stripe_en_vivo_no_despliega(tmp_path):
    base, stubs, guion = _montar(
        tmp_path, env_pruebas="STRIPE_SECRET_KEY=sk_live_algoqueescobradeverdad\n"
    )

    resultado = _desplegar_pruebas(base, stubs, guion)

    assert resultado.returncode == 1
    assert "Stripe EN VIVO" in resultado.stderr


def test_con_el_token_de_whatsapp_de_produccion_no_despliega(tmp_path):
    """El peor de los tres: una prueba escribiendo a una clienta del salon."""
    base, stubs, guion = _montar(
        tmp_path, env_pruebas="WHATSAPP_ACCESS_TOKEN=TOKEN_REAL_DE_PRODUCCION\n"
    )

    resultado = _desplegar_pruebas(base, stubs, guion)

    assert resultado.returncode == 1
    assert "MISMO token de WhatsApp que produccion" in resultado.stderr


# ─── Y con credenciales de pruebas, sigue adelante ────────────────────────

def test_con_credenciales_de_pruebas_despliega(tmp_path):
    base, stubs, guion = _montar(
        tmp_path,
        env_pruebas=("STRIPE_SECRET_KEY=sk_test_deprueba\n"
                     "WHATSAPP_ACCESS_TOKEN=\n"
                     "OPENAI_API_KEY=de-prueba\n"),
    )

    resultado = _desplegar_pruebas(base, stubs, guion)

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    with open(os.path.join(base, "docker.log"), encoding="utf-8") as fichero:
        ordenes = fichero.read()
    # Lo que importa: ha construido el entorno de PRUEBAS, no el de produccion.
    assert "docker-compose.staging.yml" in ordenes
    assert "docker-compose.yml up" not in ordenes
    assert "vantelia-staging" in ordenes
    assert "vantelia-app" not in ordenes


def test_el_entorno_de_pruebas_no_escribe_en_el_directorio_de_produccion(tmp_path):
    base, stubs, guion = _montar(tmp_path, env_pruebas="OPENAI_API_KEY=de-prueba\n")
    produccion = os.path.join(base, "srv", "vantelia")
    antes = sorted(os.listdir(produccion))

    resultado = _desplegar_pruebas(base, stubs, guion)

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert sorted(os.listdir(produccion)) == antes
    # Y no ha aparecido ningun arbol nuevo colgando de produccion.
    hermanos = os.listdir(os.path.join(base, "srv"))
    assert "vantelia_prev" not in hermanos and "vantelia_new" not in hermanos


# ─── Los dos entornos no comparten NADA que pueda pisarse ─────────────────

def _presets():
    """Los valores de cada entorno, leidos del propio deploy.ps1."""
    with open(DEPLOY_PS1, encoding="utf-8") as fichero:
        contenido = fichero.read()
    bloque = re.search(r"\$EntornoConfig = @\{(.*?)\n\}", contenido, re.S)
    assert bloque, "no se encuentra la tabla de entornos en deploy.ps1"
    presets = {}
    actual = None
    for linea in bloque.group(1).split("\n"):
        cabecera = re.match(r'\s*"(\w+)"\s*=\s*@\{', linea)
        if cabecera:
            actual = cabecera.group(1)
            presets[actual] = {}
            continue
        campo = re.match(r'\s*(\w+)\s*=\s*"?([^"\n]*)"?\s*$', linea)
        if campo and actual and campo.group(1) not in ("", None):
            presets[actual][campo.group(1)] = campo.group(2).strip()
    return presets


def test_produccion_conserva_exactamente_sus_valores_de_siempre():
    """Anadir el entorno de pruebas no puede haber movido produccion ni un byte."""
    produccion = _presets()["produccion"]

    assert produccion["Proyecto"] == "/srv/vantelia"
    assert produccion["Archivo"] == "vantelia-deploy.tar.gz"
    assert produccion["Compose"] == "deploy/hostinger/docker-compose.yml"
    assert produccion["Imagen"] == "vantelia"
    assert produccion["Contenedor"] == "vantelia-app"
    assert produccion["Puerto"] == "8000"
    assert produccion["UrlPublica"] == "https://app.vantelia.es/health"


def test_pruebas_y_produccion_no_comparten_nada_pisable():
    """Directorio, contenedor, imagen, puerto y paquete: todo distinto.

    Si compartieran cualquiera de los cinco, desplegar pruebas podria tumbar,
    sobrescribir o reetiquetar produccion sin que nadie lo pidiera.
    """
    presets = _presets()
    produccion, pruebas = presets["produccion"], presets["staging"]

    for campo in ("Proyecto", "Archivo", "Compose", "Imagen", "Contenedor", "Puerto", "Backups"):
        assert produccion[campo] != pruebas[campo], (
            "produccion y pruebas comparten %s (%s)" % (campo, produccion[campo])
        )

    # Y el arbol de pruebas no puede colgar de dentro del de produccion: los
    # _prev y _failed del rollback se mezclarian.
    assert not pruebas["Proyecto"].startswith(produccion["Proyecto"] + "/")


def test_el_compose_de_pruebas_existe_y_esta_aislado():
    ruta = os.path.join(RAIZ, "deploy", "hostinger", "docker-compose.staging.yml")
    assert os.path.exists(ruta)
    with open(ruta, encoding="utf-8") as fichero:
        contenido = fichero.read()

    assert "container_name: vantelia-staging" in contenido
    assert "image: vantelia-staging:current" in contenido
    # El puerto de fuera es otro; el de dentro sigue siendo 8000 porque la imagen
    # es la MISMA que en produccion (no hay un codigo "de pruebas" distinto).
    assert '"8001:8000"' in contenido


# ─── La resolucion del entorno, ejecutando el script de verdad ────────────

def _powershell():
    for nombre in ("powershell", "pwsh"):
        ruta = shutil.which(nombre)
        if ruta:
            return ruta
    pytest.skip("PowerShell no disponible en este entorno")


def _resolver(*argumentos):
    """Lo que deploy.ps1 decide antes de tocar nada, preguntandoselo a el."""
    resultado = subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", DEPLOY_PS1, "-MostrarEntorno"] + list(argumentos),
        capture_output=True, text=True, cwd=RAIZ,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    valores = {}
    for linea in resultado.stdout.splitlines():
        if "=" in linea:
            clave, valor = linea.split("=", 1)
            valores[clave.strip()] = valor.strip()
    return valores


def test_produccion_se_resuelve_como_siempre():
    produccion = _resolver()

    assert produccion["Entorno"] == "produccion"
    assert produccion["Proyecto"] == "/srv/vantelia"
    assert produccion["Contenedor"] == "vantelia-app"
    assert produccion["Puerto"] == "8000"


def test_el_env_de_produccion_no_arrastra_al_entorno_de_pruebas():
    """El fallo que tuvo esto y por poco se entrega.

    Las variables DEPLOY_* del .env describen PRODUCCION
    (`DEPLOY_REMOTE_PROJECT=/srv/vantelia`). En la primera version ganaban
    tambien en pruebas, asi que `-Entorno staging` acababa apuntando al arbol de
    produccion: el cortafuegos lo paraba, pero dejaba el entorno de pruebas
    inservible para cualquiera con ese .env, que es todo el mundo.
    """
    pruebas = _resolver("-Entorno", "staging")

    assert pruebas["Proyecto"] == "/srv/vantelia-staging"
    assert pruebas["Archivo"] == "vantelia-staging-deploy.tar.gz"
    assert pruebas["Contenedor"] == "vantelia-staging"
    assert pruebas["Imagen"] == "vantelia-staging"
    assert pruebas["Puerto"] == "8001"


def test_los_dos_entornos_resueltos_no_coinciden_en_nada():
    produccion, pruebas = _resolver(), _resolver("-Entorno", "staging")

    for clave in ("Proyecto", "Archivo", "Compose", "Imagen", "Contenedor",
                  "Puerto", "Backups"):
        assert produccion[clave] != pruebas[clave], clave
