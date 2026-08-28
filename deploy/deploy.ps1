param(
    [string]$ServerHost = "root@72.62.188.104",
    [string]$RemoteBase = "/srv",
    [string]$RemoteProject = "/srv/vantelia",
    [string]$ArchiveName = "vantelia-deploy.tar.gz",
    [string]$SshKeyPath = "",
    [string]$DemoClient = "clinica_saga",
    [switch]$SkipLocalChecks,
    # El humo habla con el modelo: cuesta unos centimos y un par de minutos. Se
    # puede saltar cuando el cambio no toca al asistente (la web, un texto legal).
    [switch]$SinHumo,
    # Vuelve a la version anterior del VPS sin desplegar nada. La imagen anterior
    # queda etiquetada en cada despliegue, asi que volver son segundos y no una
    # reconstruccion entera con la app caida.
    [switch]$Rollback,
    # Que entorno se despliega. "produccion" es lo de siempre, con exactamente
    # los mismos valores que antes de que este parametro existiera; "staging" es
    # el entorno de pruebas del mismo VPS, aislado en contenedor, puerto, imagen
    # y directorio propio.
    [ValidateSet("produccion", "staging")]
    [string]$Entorno = "produccion"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-Command {
    param([string]$CommandName)
    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "No se encontro el comando requerido: $CommandName"
    }
}

function Read-DotEnvFile {
    param([string]$Path)

    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $values
    }

    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }

        $separatorIndex = $line.IndexOf("=")
        if ($separatorIndex -lt 1) {
            continue
        }

        $key = $line.Substring(0, $separatorIndex).Trim()
        $value = $line.Substring($separatorIndex + 1).Trim()

        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        $values[$key] = $value
    }

    return $values
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = ""
    )

    if ($WorkingDirectory) {
        Push-Location $WorkingDirectory
    }

    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "El comando fallo con codigo ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
        }
    }
    finally {
        if ($WorkingDirectory) {
            Pop-Location
        }
    }
}

function Invoke-RobocopyChecked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination,
        [string[]]$ExtraArguments = @()
    )

    & robocopy $Source $Destination @ExtraArguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -gt 7) {
        throw "Robocopy fallo con codigo $exitCode"
    }
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProjectParent = Split-Path $ProjectRoot -Parent
$ProjectName = Split-Path $ProjectRoot -Leaf
$DotEnvValues = Read-DotEnvFile -Path (Join-Path $ProjectRoot ".env")
$StageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("vantelia-deploy-" + [System.Guid]::NewGuid().ToString("N"))
$StageProjectPath = Join-Path $StageRoot $ProjectName

if (-not $PSBoundParameters.ContainsKey("ServerHost") -and $DotEnvValues.ContainsKey("DEPLOY_SERVER_HOST")) {
    $ServerHost = $DotEnvValues["DEPLOY_SERVER_HOST"]
}
if (-not $PSBoundParameters.ContainsKey("RemoteBase") -and $DotEnvValues.ContainsKey("DEPLOY_REMOTE_BASE")) {
    $RemoteBase = $DotEnvValues["DEPLOY_REMOTE_BASE"]
}
if (-not $PSBoundParameters.ContainsKey("RemoteProject") -and $DotEnvValues.ContainsKey("DEPLOY_REMOTE_PROJECT")) {
    $RemoteProject = $DotEnvValues["DEPLOY_REMOTE_PROJECT"]
}
if (-not $PSBoundParameters.ContainsKey("ArchiveName") -and $DotEnvValues.ContainsKey("DEPLOY_ARCHIVE_NAME")) {
    $ArchiveName = $DotEnvValues["DEPLOY_ARCHIVE_NAME"]
}
if (-not $PSBoundParameters.ContainsKey("SshKeyPath") -and $DotEnvValues.ContainsKey("DEPLOY_SSH_KEY_PATH")) {
    $SshKeyPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DotEnvValues["DEPLOY_SSH_KEY_PATH"])
}
if (-not $PSBoundParameters.ContainsKey("DemoClient") -and $DotEnvValues.ContainsKey("DEPLOY_DEMO_CLIENT")) {
    $DemoClient = $DotEnvValues["DEPLOY_DEMO_CLIENT"]
}

# Todo lo que cambia entre entornos vive AQUI y en ningun otro sitio. Los de
# produccion son identicos a los de siempre, asi que ese camino no cambia.
$EntornoConfig = @{
    "produccion" = @{
        Proyecto    = "/srv/vantelia"
        Archivo     = "vantelia-deploy.tar.gz"
        Compose     = "deploy/hostinger/docker-compose.yml"
        Imagen      = "vantelia"
        Contenedor  = "vantelia-app"
        Puerto      = 8000
        Backups     = "/srv/vantelia-backups"
        UrlPublica  = "https://app.vantelia.es/health"
    }
    "staging" = @{
        Proyecto    = "/srv/vantelia-staging"
        Archivo     = "vantelia-staging-deploy.tar.gz"
        Compose     = "deploy/hostinger/docker-compose.staging.yml"
        Imagen      = "vantelia-staging"
        Contenedor  = "vantelia-staging"
        Puerto      = 8001
        Backups     = "/srv/vantelia-staging-backups"
        # Vacia hasta que exista el vhost de nginx. Sin ella se omite la
        # comprobacion publica en vez de dar por fallido un despliegue bueno.
        UrlPublica  = ""
    }
}
$Actual = $EntornoConfig[$Entorno]

# Los parametros explicitos del usuario mandan sobre el preset del entorno; si no
# los da, el entorno decide. Asi `-RemoteProject` sigue funcionando como siempre.
if (-not $PSBoundParameters.ContainsKey("RemoteProject") -and -not $DotEnvValues.ContainsKey("DEPLOY_REMOTE_PROJECT")) {
    $RemoteProject = $Actual.Proyecto
}
if (-not $PSBoundParameters.ContainsKey("ArchiveName") -and -not $DotEnvValues.ContainsKey("DEPLOY_ARCHIVE_NAME")) {
    $ArchiveName = $Actual.Archivo
}
if ($Entorno -ne "produccion") {
    # Un preset de produccion heredado del .env apuntaria las pruebas al
    # directorio real: se corta antes de tocar nada.
    if ($RemoteProject -eq $EntornoConfig["produccion"].Proyecto) {
        throw "El entorno de pruebas no puede desplegarse sobre $($RemoteProject): revisa DEPLOY_REMOTE_PROJECT en tu .env."
    }
    if ($ArchiveName -eq $EntornoConfig["produccion"].Archivo) {
        $ArchiveName = $Actual.Archivo
    }
}
$UrlPublica = $Actual.UrlPublica
if ($DotEnvValues.ContainsKey("DEPLOY_STAGING_PUBLIC_URL") -and $Entorno -eq "staging") {
    $UrlPublica = $DotEnvValues["DEPLOY_STAGING_PUBLIC_URL"]
}

$ArchivePath = Join-Path ([System.IO.Path]::GetTempPath()) $ArchiveName
$scpArgsBase = @()
$sshArgsBase = @()
if ($SshKeyPath) {
    $resolvedKeyPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($SshKeyPath)
    if (-not (Test-Path -LiteralPath $resolvedKeyPath)) {
        throw "No se encuentra la clave SSH configurada: $resolvedKeyPath"
    }
    $scpArgsBase += @("-i", $resolvedKeyPath)
    $sshArgsBase += @("-i", $resolvedKeyPath)
}

Write-Step "Validando herramientas locales"
Assert-Command "tar.exe"
Assert-Command "scp.exe"
Assert-Command "ssh.exe"

function Invoke-RemoteRollback {
    param([string]$Motivo = "")

    $rollbackScriptPath = Join-Path $ProjectRoot "deploy/hostinger/rollback.sh"
    if (-not (Test-Path -LiteralPath $rollbackScriptPath)) {
        throw "No se encuentra deploy/hostinger/rollback.sh: no hay vuelta atras automatica."
    }
    if ($Motivo) {
        Write-Host ""
        Write-Host "!! $Motivo" -ForegroundColor Red
    }
    Write-Step "Volviendo a la version anterior del VPS"

    # El script se sube desde el repo en lugar de usar el del VPS: si el arbol
    # remoto quedo a medias, el suyo puede faltar o ser justo el que esta roto.
    $rollbackSource = (Get-Content -LiteralPath $rollbackScriptPath -Raw) -replace "`r`n", "`n"
    $rollbackB64 = [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($rollbackSource))
    $rollbackArgs = ("'$RemoteProject' '$($Actual.Compose)' '$($Actual.Imagen)' " +
                     "'$($Actual.Contenedor)' '$($Actual.Puerto)'")
    $rollbackCommand = "echo $rollbackB64 | base64 -d | bash -s -- $rollbackArgs"

    $ErrorActionPreference = "Continue"
    # `| Out-Host` es imprescindible: sin el, todo lo que escupe el ssh se mezcla
    # con el valor que devuelve la funcion, y quien la llama recibe el LOG ENTERO
    # en vez del codigo de salida. Paso de verdad el 28-ago-2026: el rollback se
    # hizo bien -"la version anterior responde"- y justo despues el script grito
    # "El rollback ha fallado", porque comparaba un array de texto con 0.
    & ssh.exe @sshArgsBase $ServerHost $rollbackCommand | Out-Host
    $rollbackExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    return $rollbackExit
}

if ($Rollback) {
    # Y por si acaso, del valor devuelto se coge SOLO lo ultimo: el codigo.
    $rollbackOnlyExit = @(Invoke-RemoteRollback)[-1]
    if ($rollbackOnlyExit -ne 0) {
        throw "El rollback ha fallado (exit $rollbackOnlyExit). Mira los logs de arriba."
    }
    Write-Host ""
    Write-Host "Rollback completado: produccion vuelve a la version anterior." -ForegroundColor Green
    Write-Host "Health: https://app.vantelia.es/health" -ForegroundColor Green
    exit 0
}

$PythonCommand = "python"
$Python311Venv = Join-Path $ProjectRoot ".venv311\Scripts\python.exe"
$DefaultVenv = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $Python311Venv) {
    $PythonCommand = $Python311Venv
} elseif (Test-Path -LiteralPath $DefaultVenv) {
    $PythonCommand = $DefaultVenv
} else {
    Assert-Command "python"
}

if (-not $SkipLocalChecks) {
    Write-Step "Ejecutando comprobaciones locales"
    $pythonVersionOutput = (& $PythonCommand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo comprobar la version de Python local."
    }
    $pythonVersion = [version]$pythonVersionOutput
    if ($pythonVersion -lt [version]"3.11") {
        throw "Python local debe ser 3.11 o superior para coincidir con Docker (actual: $pythonVersionOutput)."
    }
    Write-Host "Sincronizando dependencias de requirements.txt..."
    Invoke-Checked -FilePath $PythonCommand -Arguments @("-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", "requirements.txt") -WorkingDirectory $ProjectRoot
    Invoke-Checked -FilePath $PythonCommand -Arguments @("-m", "pytest") -WorkingDirectory $ProjectRoot
    Invoke-Checked -FilePath $PythonCommand -Arguments @("-m", "py_compile", "api.py", "auto_onboarding.py", "onboarding_utils.py") -WorkingDirectory $ProjectRoot
}

Write-Step "Empaquetando proyecto para despliegue"
if (Test-Path $ArchivePath) {
    Remove-Item -LiteralPath $ArchivePath -Force
}

if (Test-Path $StageRoot) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $StageProjectPath -Force | Out-Null

Invoke-RobocopyChecked -Source $ProjectRoot -Destination $StageProjectPath -ExtraArguments @(
    "/E",
    "/XD", ".git", ".git-inner-backup", ".venv", ".venv311", ".pytest_cache", "node_modules", "storage", "data", "backups", "__pycache__", "Identidad Visual", "service_account", "site_exports",
    "/XF", ".env", ".env.backup-*", ".env.ftp", "env.ftp", ".gh_token", "config.json", "ssh-askpass.cmd", "vantelia_deploy", "vantelia_deploy.pub", "vantelia_deploy_runtime", "vantelia_deploy_runtime.pub", "known_hosts", "hoja_llamadas_calientes.md", "whatsapp_calientes.md"
)

$tarArgs = @(
    '-czf',
    $ArchivePath,
    $ProjectName
)
$NativeTar = "$env:SystemRoot\System32\tar.exe"
Invoke-Checked -FilePath $NativeTar -Arguments $tarArgs -WorkingDirectory $StageRoot
try {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force -ErrorAction SilentlyContinue
} catch {
    Write-Host "Aviso: limpieza temporal incompleta (rutas largas). Continuando..." -ForegroundColor Yellow
}

Write-Step "Subiendo paquete al VPS"
# El destino lleva el nombre EXPLICITO: con destino de directorio, scp saca el
# basename buscando "/" y una ruta de Windows no tiene ninguno, asi que subia un
# fichero llamado con la ruta entera y el VPS no lo encontraba.
Invoke-Checked -FilePath "scp.exe" -Arguments ($scpArgsBase + @($ArchivePath, "${ServerHost}:${RemoteBase}/${ArchiveName}"))

$remoteScript = @'
set -euo pipefail

REMOTE_BASE="$1"
REMOTE_PROJECT="$2"
ARCHIVE_NAME="$3"
# Lo que distingue un entorno de otro. Sin argumentos serian los de produccion,
# pero el que llama los pasa siempre explicitos para que no haya dudas.
COMPOSE_FILE="${4:-deploy/hostinger/docker-compose.yml}"
IMAGE_BASE="${5:-vantelia}"
CONTENEDOR="${6:-vantelia-app}"
PUERTO="${7:-8000}"
ENTORNO="${8:-produccion}"
BACKUP_DIR="${9:-/srv/vantelia-backups}"
# Contra que .env se compara para no repetir credenciales. Es un argumento y no
# una ruta fija para poder probar de verdad este guardia.
ENV_PRODUCCION="${10:-/srv/vantelia/.env}"

ARCHIVE_PATH="${REMOTE_BASE}/${ARCHIVE_NAME}"
NEW_DIR="${REMOTE_PROJECT}_new"
PREV_DIR="${REMOTE_PROJECT}_prev"
IMAGE_CURRENT="${IMAGE_BASE}:current"
IMAGE_PREV="${IMAGE_BASE}:prev"

echo "Entorno: ${ENTORNO}  (${REMOTE_PROJECT}, contenedor ${CONTENEDOR}, puerto ${PUERTO})"
# Prueba de que este script ha corrido de verdad. Quien llama la comprueba: si el
# comando llega truncado, el shell remoto imprime el texto y no ejecuta nada, y
# sin esta marca eso pasaba por un despliegue correcto.
date -u +%Y-%m-%dT%H:%M:%SZ > /srv/vantelia_marca_despliegue 2>/dev/null || true

if [ ! -f "$ARCHIVE_PATH" ]; then
  echo "No se encuentra el paquete de despliegue: $ARCHIVE_PATH" >&2
  exit 1
fi

# --- El entorno de pruebas no puede hablar con clientes de verdad -------------
# Es el riesgo real de tener los dos en la misma maquina: un WhatsApp de pruebas
# a una clienta del salon, o un cobro con la clave de Stripe en vivo, no tienen
# vuelta atras. Asi que se comprueba ANTES de arrancar nada, no se confia.
if [ "$ENTORNO" != "produccion" ]; then
  ENV_PRUEBAS="${REMOTE_PROJECT}/.env"
  if [ ! -f "$ENV_PRUEBAS" ]; then
    echo "El entorno de pruebas no tiene su propio .env en ${ENV_PRUEBAS}." >&2
    echo "Crealo a mano con credenciales de PRUEBA (Stripe test, SMTP falso, sin" >&2
    echo "token de WhatsApp real). No se copia el de produccion a proposito." >&2
    exit 1
  fi
  if grep -q "sk_live_" "$ENV_PRUEBAS" 2>/dev/null && true; then
    echo "El .env de pruebas lleva una clave de Stripe EN VIVO (sk_live_)." >&2
    echo "Cambiala por una de test antes de desplegar aqui." >&2
    exit 1
  fi
  # OJO al `|| true`: con `pipefail`, un grep que no encuentra nada devuelve 1 y
  # tumbaba el despliegue entero SIN decir por que. Un .env de pruebas sin linea
  # de WhatsApp es lo normal, no un error.
  token_pruebas="$( (grep -E '^WHATSAPP_ACCESS_TOKEN=' "$ENV_PRUEBAS" 2>/dev/null || true) | head -1 | cut -d= -f2-)"
  token_prod="$( (grep -E '^WHATSAPP_ACCESS_TOKEN=' "$ENV_PRODUCCION" 2>/dev/null || true) | head -1 | cut -d= -f2-)"
  if [ -n "$token_pruebas" ] && [ "$token_pruebas" = "$token_prod" ]; then
    echo "El .env de pruebas usa el MISMO token de WhatsApp que produccion." >&2
    echo "Con el, una prueba puede escribir a una clienta real. Vacialo o pon uno" >&2
    echo "de un numero de pruebas." >&2
    exit 1
  fi
fi

# --- Red de seguridad 1: foto de la base de datos ANTES de tocar nada ---------
# El backup nocturno ya existe, pero puede llevar hasta 24 h encima: si una
# migracion sale mal a las 18:00, restaurar la copia de las 04:00 pierde el dia
# entero de citas, chats y pagos.
DB_PATH="${REMOTE_PROJECT}/storage/vantelia.db"
if [ -f "$DB_PATH" ]; then
  mkdir -p "$BACKUP_DIR"
  SNAPSHOT="${BACKUP_DIR}/pre-deploy-$(date +%Y%m%d-%H%M%S).db"
  # .backup de SQLite, nunca cp: copiar el fichero a pelo deja el WAL fuera y la
  # copia puede no abrir siquiera.
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_PATH" ".backup '$SNAPSHOT'"
  elif docker exec "$CONTENEDOR" python3 -c "import sqlite3; o=sqlite3.connect('/app/storage/vantelia.db'); d=sqlite3.connect('/tmp/pre-deploy.db'); o.backup(d); d.close(); o.close()" >/dev/null 2>&1; then
    docker cp "$CONTENEDOR":/tmp/pre-deploy.db "$SNAPSHOT" >/dev/null
    docker exec "$CONTENEDOR" rm -f /tmp/pre-deploy.db >/dev/null 2>&1 || true
  else
    echo "No se pudo hacer la foto de la base de datos: se aborta el despliegue." >&2
    echo "Sin copia previa, un fallo de migracion no tendria vuelta atras." >&2
    exit 1
  fi
  echo "Foto previa de la base de datos: $SNAPSHOT"
  # Se guardan las 10 ultimas: son la red para el mismo dia, no el archivo.
  ls -1t "${BACKUP_DIR}"/pre-deploy-*.db 2>/dev/null | tail -n +11 | xargs -r rm -f
fi

# --- Red de seguridad 2: la imagen que funciona hoy queda con nombre ----------
# Sin esto, volver atras obliga a reconstruir (minutos con la app caida). Con
# esto, el rollback es un docker tag y levantar el contenedor.
if docker image inspect "$IMAGE_CURRENT" >/dev/null 2>&1; then
  docker tag "$IMAGE_CURRENT" "$IMAGE_PREV"
  echo "Imagen actual etiquetada como $IMAGE_PREV"
elif running_image="$(docker inspect -f '{{.Image}}' "$CONTENEDOR" 2>/dev/null)"; then
  # Primer despliegue con este esquema: la imagen viva aun no tiene nombre fijo.
  docker tag "$running_image" "$IMAGE_PREV"
  echo "Imagen en ejecucion etiquetada como $IMAGE_PREV"
else
  echo "Aviso: no hay imagen previa que etiquetar (primer despliegue)."
fi

mkdir -p "$REMOTE_BASE"
rm -rf "$NEW_DIR"
mkdir -p "$NEW_DIR"
tar -xzf "$ARCHIVE_PATH" -C "$NEW_DIR" --strip-components=1

if [ -f "${REMOTE_PROJECT}/.env" ]; then
  cp "${REMOTE_PROJECT}/.env" "${NEW_DIR}/.env"
fi

if [ -f "${REMOTE_PROJECT}/config.json" ]; then
  cp "${REMOTE_PROJECT}/config.json" "${NEW_DIR}/config.json"
fi

if [ -d "${REMOTE_PROJECT}/data" ]; then
  cp -a "${REMOTE_PROJECT}/data" "${NEW_DIR}/data"
else
  mkdir -p "${NEW_DIR}/data"
fi

if [ -d "${REMOTE_PROJECT}/storage" ]; then
  cp -a "${REMOTE_PROJECT}/storage" "${NEW_DIR}/storage"
else
  mkdir -p "${NEW_DIR}/storage"
fi

if [ -d "${REMOTE_PROJECT}/secrets" ]; then
  cp -a "${REMOTE_PROJECT}/secrets" "${NEW_DIR}/secrets"
else
  mkdir -p "${NEW_DIR}/secrets"
fi

rm -rf "$PREV_DIR"
if [ -d "$REMOTE_PROJECT" ]; then
  mv "$REMOTE_PROJECT" "$PREV_DIR"
fi
mv "$NEW_DIR" "$REMOTE_PROJECT"

cd "$REMOTE_PROJECT"

# El script de rollback se aparta a /tmp porque vive dentro del arbol que el
# propio rollback va a mover: leerlo desde su sitio a mitad de faena no es fiable.
cp deploy/hostinger/rollback.sh "/tmp/vantelia-rollback-${ENTORNO}.sh" 2>/dev/null || true

volver_atras() {
  echo "" >&2
  echo "!! $1" >&2
  if [ -f "/tmp/vantelia-rollback-${ENTORNO}.sh" ]; then
    bash "/tmp/vantelia-rollback-${ENTORNO}.sh" "$REMOTE_PROJECT" "$COMPOSE_FILE" \n      "$IMAGE_BASE" "$CONTENEDOR" "$PUERTO" >&2 ||       echo "!! El rollback automatico tambien ha fallado: entra por SSH." >&2
  else
    echo "!! Sin script de rollback. La version anterior sigue en ${PREV_DIR}." >&2
  fi
  exit 1
}

# Compose escribe el progreso por stderr; lo unificamos con stdout para que
# PowerShell conserve el orden y no muestre mensajes atrasados tras el exito.
if ! docker compose -f "$COMPOSE_FILE" up -d --build 2>&1; then
  volver_atras "La construccion o el arranque han fallado."
fi
docker ps

# La app tarda en levantar (llama-index, nltk, indices). Con 12 intentos (36 s) el
# deploy daba por fallido un despliegue que en realidad habia funcionado, y eso
# invita a relanzarlo encima. 40 intentos = 2 minutos de margen.
attempt=1
while true; do
  if health_response="$(curl --fail --silent --max-time 5 http://127.0.0.1:${PUERTO}/health 2>/dev/null)"; then
    echo "$health_response"
    break
  fi
  if [ "$attempt" -ge 40 ]; then
    echo ""
    echo "Healthcheck fallido tras varios intentos. Ultimos logs de $CONTENEDOR:" >&2
    docker logs "$CONTENEDOR" --tail 120 >&2 || true
    volver_atras "La version desplegada no responde al healthcheck."
  fi
  echo "Esperando a que la app responda... intento $attempt/40"
  attempt=$((attempt + 1))
  sleep 3
done

rm -f "$ARCHIVE_PATH"
'@

Write-Step "Actualizando el VPS y reconstruyendo Docker"
# Enviamos el script remoto codificado en base64 (ASCII puro) como argumento y
# lo decodificamos en el VPS. Asi evitamos que el encoding de PowerShell para el
# stdin de ssh anteponga un BOM (UTF-8 con firma); ese BOM rompia la primera
# linea en bash ("set: command not found") y desactivaba el modo estricto
# fail-fast. GetBytes() de UTF8 nunca emite preambulo, asi que el base64 es limpio.
$remoteScriptUnix = $remoteScript -replace "`r`n", "`n"
$remoteArgs = ("'$RemoteBase' '$RemoteProject' '$ArchiveName' " +
               "'$($Actual.Compose)' '$($Actual.Imagen)' '$($Actual.Contenedor)' " +
               "'$($Actual.Puerto)' '$Entorno' '$($Actual.Backups)' " +
               "'$($EntornoConfig[""produccion""].Proyecto)/.env'")
# El script viaja como FICHERO, no metido en el comando de ssh.
#
# Antes se mandaba el script entero en base64 dentro del propio comando. Funciono
# meses y un dia dejo de funcionar sin tocar nada de la logica: al crecer el
# script unos cientos de bytes, el comando paso del limite de longitud, se
# TRUNCO, y el VPS recibio algo partido por la mitad. El resultado no fue un
# error: el shell remoto escupio el base64 por pantalla y siguio como si nada, asi
# que el despliegue decia "OK" y el servidor no se actualizaba. Se creyo que
# fallaba el codigo y hasta se volvio atras en produccion por eso.
#
# Con scp no hay limite y se ve enseguida si algo falla.
$remoteScriptLocal = Join-Path ([System.IO.Path]::GetTempPath()) ("vantelia-remote-" + [System.Guid]::NewGuid().ToString("N") + ".sh")
[System.IO.File]::WriteAllText($remoteScriptLocal, $remoteScriptUnix, (New-Object System.Text.UTF8Encoding($false)))
$remoteScriptRemoto = "/tmp/vantelia-deploy-$Entorno.sh"
Invoke-Checked -FilePath "scp.exe" -Arguments ($scpArgsBase + @($remoteScriptLocal, "${ServerHost}:${remoteScriptRemoto}"))
Remove-Item -LiteralPath $remoteScriptLocal -Force -ErrorAction SilentlyContinue
$remoteCommand = "bash $remoteScriptRemoto $remoteArgs"
$ErrorActionPreference = "Continue"
& ssh.exe @sshArgsBase $ServerHost $remoteCommand
$sshExit = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($sshExit -ne 0) {
    throw "La actualizacion remota ha fallado (exit $sshExit)."
}
# El script remoto empieza diciendo en que entorno esta. Si esa linea no ha
# salido, es que NO se ha ejecutado -paso: el comando llego truncado y el shell
# se limito a imprimirlo-, y seguir adelante seria dar por desplegado algo que
# sigue igual que estaba.
$marcaRemota = "/srv/vantelia_marca_despliegue"
$sello = & ssh.exe @sshArgsBase $ServerHost "cat $marcaRemota 2>/dev/null || true"
if (-not ("$sello".Trim())) {
    throw "El VPS no ha ejecutado el script de despliegue (no hay marca). Nada se ha actualizado."
}

if ($UrlPublica) {
    Write-Step "Verificando el acceso publico ($Entorno)"
    $publicHealth = $null
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        try {
            $publicHealth = Invoke-RestMethod -Uri $UrlPublica -TimeoutSec 15
            if ($publicHealth.status -eq "ok") {
                break
            }
        } catch {
            if ($attempt -eq 6) {
                throw "El VPS responde, pero el healthcheck publico ha fallado: $($_.Exception.Message)"
            }
            Start-Sleep -Seconds 3
        }
    }
    if (-not $publicHealth -or $publicHealth.status -ne "ok") {
        throw "El healthcheck publico no devolvio status=ok."
    }
    Write-Host "Acceso publico: OK" -ForegroundColor Green
} else {
    # El entorno de pruebas puede no tener aun vhost de nginx. La app ya ha
    # respondido dentro del VPS: dar el despliegue por fallido aqui seria mentir.
    Write-Step "Sin URL publica configurada para '$Entorno': se omite esa comprobacion"
    Write-Host "  (la app responde en el VPS, puerto $($Actual.Puerto))" -ForegroundColor DarkGray
}

# Cinco conversaciones enteras contra una COPIA de la base de datos. Existe porque
# el 26-ago-2026 se colaron dos regresiones que pasaron los 1.373 tests: los tests
# comprueban que un detector salta; esto comprueba que la clienta acaba con su
# cita. Se salta con -SinHumo cuando el cambio no toca al asistente.
if (-not $SinHumo) {
    Write-Step "Humo: cinco conversaciones de principio a fin"
    $humo = & ssh.exe @sshArgsBase $ServerHost "docker exec $($Actual.Contenedor) sh -c 'cd /app && timeout 900 python scripts/humo.py 2>/dev/null'"
    $humoExit = $LASTEXITCODE
    $humo | ForEach-Object { Write-Host $_ }
    if ($humoExit -ne 0) {
        Write-Host ""
        Write-Host "!! HAY CAMINOS ROTOS EN LO QUE ACABAS DE DESPLEGAR" -ForegroundColor Red
        Write-Host "   Mira arriba cual y por que." -ForegroundColor Yellow
        # El health decia que si y la conversacion se rompe igual: es justo el
        # fallo que no se ve hasta que lo sufre un cliente. Se vuelve atras solo.
        $humoRollbackExit = @(Invoke-RemoteRollback -Motivo "El humo ha fallado: la conversacion no llega al final.")[-1]
        if ($humoRollbackExit -ne 0) {
            throw "El humo ha fallado Y el rollback tambien (exit $humoRollbackExit). Entra por SSH: produccion esta rota."
        }
        Write-Host ""
        Write-Host "Produccion restaurada a la version anterior." -ForegroundColor Green
        throw "El humo ha fallado: se ha vuelto atras. Arregla el camino roto antes de volver a desplegar."
    }
}

Write-Step "Despliegue completado ($Entorno)"
if ($Entorno -eq "produccion") {
    Write-Host "Panel:   https://app.vantelia.es/dashboard" -ForegroundColor Green
    Write-Host "Health:  $UrlPublica" -ForegroundColor Green
    Write-Host "Demo:    https://app.vantelia.es/demo/$DemoClient" -ForegroundColor Green
} else {
    Write-Host "Entorno de pruebas en $RemoteProject (contenedor $($Actual.Contenedor))" -ForegroundColor Green
    if ($UrlPublica) {
        Write-Host "Health:  $UrlPublica" -ForegroundColor Green
    } else {
        Write-Host "Health:  desde el VPS -> curl http://127.0.0.1:$($Actual.Puerto)/health" -ForegroundColor Green
    }
    Write-Host "Produccion NO se ha tocado." -ForegroundColor Green
}
