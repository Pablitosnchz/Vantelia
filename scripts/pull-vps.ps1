# pull-vps.ps1
# Trae archivos del VPS al local para sincronizar
# Uso: .\scripts\pull-vps.ps1
# Uso con clave SSH: .\scripts\pull-vps.ps1 -SshKeyPath ~/.ssh/id_rsa

param(
    [string]$ServerHost = "root@72.62.188.104",
    [string]$RemoteProject = "/srv/vantelia",
    [string]$SshKeyPath = "",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$scpArgs = @()
$sshArgs = @()
if ($SshKeyPath) {
    $scpArgs += @("-i", $SshKeyPath)
    $sshArgs += @("-i", $SshKeyPath)
}

function Write-Step { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Skip { param([string]$m) Write-Host "  [--] $m" -ForegroundColor DarkGray }
function Write-Warn { param([string]$m) Write-Host "  [!]  $m" -ForegroundColor Yellow }

Write-Step "Conectando a $ServerHost"

# ── Ver versión del código en el VPS ──────────────────────────────
Write-Step "Estado del VPS"
& ssh.exe @sshArgs $ServerHost @"
echo "--- Docker ---"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || echo "Docker no disponible"
echo ""
echo "--- Ultimo commit en el repo del VPS (si usa git) ---"
cd $RemoteProject && git log --oneline -5 2>/dev/null || echo "No hay repo git en el VPS"
echo ""
echo "--- Archivos modificados recientemente ---"
find $RemoteProject -maxdepth 2 -newer $RemoteProject/requirements.txt -not -path '*/.git/*' -not -path '*/storage/*' -not -path '*/__pycache__/*' 2>/dev/null | head -20 || true
"@

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[ERROR] No se pudo conectar al VPS. Comprueba:" -ForegroundColor Red
    Write-Host "  - Que tienes acceso SSH (clave o contraseña)" -ForegroundColor Red
    Write-Host "  - Usa -SshKeyPath para especificar tu clave privada" -ForegroundColor Red
    exit 1
}

# ── Traer config.json ──────────────────────────────────────────────
Write-Step "Trayendo config.json del VPS"
$configTarget = Join-Path $ProjectRoot "config.json"
$configBackup = Join-Path $ProjectRoot "config.json.local-backup"

if (-not $DryRun) {
    if (Test-Path $configTarget) {
        Copy-Item $configTarget $configBackup -Force
        Write-Skip "Backup local guardado en config.json.local-backup"
    }
    & scp.exe @scpArgs "${ServerHost}:${RemoteProject}/config.json" $configTarget
    Write-Ok "config.json actualizado desde el VPS"
} else {
    Write-Skip "[DryRun] Se traeria config.json del VPS a $configTarget"
}

# ── Traer .env (como .env.vps, NO sobreescribe el local) ──────────
Write-Step "Trayendo .env del VPS (guardado como .env.vps)"
$envTarget = Join-Path $ProjectRoot ".env.vps"

if (-not $DryRun) {
    & scp.exe @scpArgs "${ServerHost}:${RemoteProject}/.env" $envTarget
    Write-Ok ".env del VPS guardado en .env.vps (no sobreescribe tu .env local)"
    Write-Warn "Revisa .env.vps y fusiona manualmente si necesitas algo de producción"
} else {
    Write-Skip "[DryRun] Se traeria .env del VPS a .env.vps"
}

# ── Mostrar diff de config.json ───────────────────────────────────
if (-not $DryRun -and (Test-Path $configBackup)) {
    Write-Step "Diferencias en config.json (local anterior vs VPS)"
    & git.exe diff --no-index $configBackup $configTarget 2>&1 | Select-Object -First 80
}

Write-Host "`n══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Sync desde VPS completado" -ForegroundColor Green
Write-Host "  Revisa los cambios antes de hacer deploy" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════`n" -ForegroundColor Cyan
