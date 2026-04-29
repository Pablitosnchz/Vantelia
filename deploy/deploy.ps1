param(
    [string]$ServerHost = "root@72.62.188.104",
    [string]$RemoteBase = "/srv",
    [string]$RemoteProject = "/srv/vantelia",
    [string]$ArchiveName = "vantelia-deploy.tar.gz",
    [string]$SshKeyPath = "",
    [string]$DemoClient = "clinica_saga",
    [switch]$SkipLocalChecks
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
Assert-Command "python"

if (-not $SkipLocalChecks) {
    Write-Step "Ejecutando comprobaciones locales"
    Invoke-Checked -FilePath "python" -Arguments @("-m", "py_compile", "api.py", "auto_onboarding.py", "onboarding_utils.py") -WorkingDirectory $ProjectRoot
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
    "/XD", ".git", ".git-inner-backup", ".venv", ".pytest_cache", "node_modules", "storage", "data", "backups", "__pycache__", "Identidad Visual", "service_account", "site_exports",
    "/XF", ".env", ".env.ftp", "env.ftp", "config.json"
)

$tarArgs = @(
    '-czf',
    $ArchivePath,
    $ProjectName
)
Invoke-Checked -FilePath "tar.exe" -Arguments $tarArgs -WorkingDirectory $StageRoot
try {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force -ErrorAction SilentlyContinue
} catch {
    Write-Host "Aviso: limpieza temporal incompleta (rutas largas). Continuando..." -ForegroundColor Yellow
}

Write-Step "Subiendo paquete al VPS"
Invoke-Checked -FilePath "scp.exe" -Arguments ($scpArgsBase + @($ArchivePath, "${ServerHost}:${RemoteBase}/"))

$remoteScript = @'
set -euo pipefail

REMOTE_BASE="$1"
REMOTE_PROJECT="$2"
ARCHIVE_NAME="$3"

ARCHIVE_PATH="${REMOTE_BASE}/${ARCHIVE_NAME}"
NEW_DIR="${REMOTE_PROJECT}_new"
PREV_DIR="${REMOTE_PROJECT}_prev"

if [ ! -f "$ARCHIVE_PATH" ]; then
  echo "No se encuentra el paquete de despliegue: $ARCHIVE_PATH" >&2
  exit 1
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

rm -rf "$PREV_DIR"
if [ -d "$REMOTE_PROJECT" ]; then
  mv "$REMOTE_PROJECT" "$PREV_DIR"
fi
mv "$NEW_DIR" "$REMOTE_PROJECT"

cd "$REMOTE_PROJECT"
docker compose -f deploy/hostinger/docker-compose.yml up -d --build
docker ps

attempt=1
until curl --fail --silent --show-error http://127.0.0.1:8000/health; do
  if [ "$attempt" -ge 12 ]; then
    echo ""
    echo "Healthcheck fallido tras varios intentos. Ultimos logs de vantelia-app:" >&2
    docker logs vantelia-app --tail 120 >&2 || true
    exit 1
  fi
  echo "Esperando a que la app responda... intento $attempt/12"
  attempt=$((attempt + 1))
  sleep 3
done

rm -f "$ARCHIVE_PATH"
'@

Write-Step "Actualizando el VPS y reconstruyendo Docker"
($remoteScript -replace "`r`n", "`n") | & ssh.exe @sshArgsBase $ServerHost "bash -s -- '$RemoteBase' '$RemoteProject' '$ArchiveName'"
if ($LASTEXITCODE -ne 0) {
    throw "La actualizacion remota ha fallado."
}

Write-Step "Despliegue completado"
Write-Host "Panel:   https://app.vantelia.es/dashboard" -ForegroundColor Green
Write-Host "Health:  https://app.vantelia.es/health" -ForegroundColor Green
Write-Host "Demo:    https://app.vantelia.es/demo/$DemoClient" -ForegroundColor Green
