param(
    [string]$ProjectRoot = "",
    [string]$BackupRoot = "",
    [switch]$IncludeEnv,
    [switch]$NoZip
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Copy-IfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    if (Test-Path -LiteralPath $Source) {
        Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
    }
}

if (-not $ProjectRoot) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

if (-not $BackupRoot) {
    $BackupRoot = Join-Path $ProjectRoot "backups"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupName = "vantelia-backup-$timestamp"
$backupDir = Join-Path $BackupRoot $backupName

Write-Step "Creando backup en $backupDir"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

Copy-IfExists -Source (Join-Path $ProjectRoot "config.json") -Destination $backupDir
Copy-IfExists -Source (Join-Path $ProjectRoot "data") -Destination $backupDir
Copy-IfExists -Source (Join-Path $ProjectRoot "storage") -Destination $backupDir

if ($IncludeEnv) {
    Copy-IfExists -Source (Join-Path $ProjectRoot ".env") -Destination $backupDir
}

$manifestPath = Join-Path $backupDir "manifest.json"
$files = Get-ChildItem -Path $backupDir -File -Recurse | ForEach-Object {
    $relativePath = $_.FullName.Substring($backupDir.Length).TrimStart("\", "/")
    [ordered]@{
        path = $relativePath
        bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
}

$manifest = [ordered]@{
    created_at = (Get-Date).ToString("o")
    project_root = $ProjectRoot
    include_env = [bool]$IncludeEnv
    files = @($files)
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

if (-not $NoZip) {
    $zipPath = "$backupDir.zip"
    Write-Step "Comprimiendo backup en $zipPath"
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $backupDir "*") -DestinationPath $zipPath -Force
    Write-Host "Backup listo: $zipPath" -ForegroundColor Green
}
else {
    Write-Host "Backup listo: $backupDir" -ForegroundColor Green
}
