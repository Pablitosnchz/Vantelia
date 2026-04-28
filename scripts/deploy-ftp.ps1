# deploy-ftp.ps1
# Sube hostinger_site/ a Hostinger via FTP
# Uso: .\scripts\deploy-ftp.ps1
# Requiere: .env.ftp en la raiz del proyecto (gitignoreado)

param(
    [string]$EnvFile = "$PSScriptRoot\..\env.ftp",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Cargar .env.ftp ────────────────────────────────────────────────
$envPath = Resolve-Path "$PSScriptRoot\..\env.ftp" -ErrorAction SilentlyContinue
if (-not $envPath) {
    $envPath = Join-Path $PSScriptRoot "..\env.ftp"
}

$realEnvPath = Join-Path (Split-Path $PSScriptRoot -Parent) ".env.ftp"
if (-not (Test-Path $realEnvPath)) {
    Write-Error "No se encontro .env.ftp. Crea el archivo con FTP_HOST, FTP_USER, FTP_PASSWORD, FTP_PORT y REMOTE_DIR."
    exit 1
}

$config = @{}
Get-Content $realEnvPath | Where-Object { $_ -match "^\s*[^#]" -and $_ -match "=" } | ForEach-Object {
    $parts = $_ -split "=", 2
    $config[$parts[0].Trim()] = $parts[1].Trim()
}

$FTP_HOST   = $config["FTP_HOST"]
$FTP_USER   = $config["FTP_USER"]
$FTP_PASS   = $config["FTP_PASSWORD"]
$FTP_PORT   = if ($config["FTP_PORT"]) { $config["FTP_PORT"] } else { "21" }
$REMOTE_DIR = if ($config["REMOTE_DIR"]) { $config["REMOTE_DIR"] } else { "public_html" }

$LOCAL_DIR  = Join-Path (Split-Path $PSScriptRoot -Parent) "hostinger_site"

if (-not (Test-Path $LOCAL_DIR)) {
    Write-Error "No existe la carpeta local: $LOCAL_DIR"
    exit 1
}

Write-Host ""
Write-Host "══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Vantelia · Deploy FTP a Hostinger" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Host      : $FTP_HOST`:$FTP_PORT"
Write-Host "  Usuario   : $FTP_USER"
Write-Host "  Directorio: /$REMOTE_DIR"
Write-Host "  Local     : $LOCAL_DIR"
if ($DryRun) { Write-Host "  MODO      : DRY RUN (no sube nada)" -ForegroundColor Yellow }
Write-Host ""

if ($DryRun) {
    Write-Host "[DryRun] Archivos que se subirian:" -ForegroundColor Yellow
    Get-ChildItem $LOCAL_DIR -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($LOCAL_DIR.Length + 1)
        Write-Host "  $rel"
    }
    exit 0
}

# ── Subir via WinSCP .NET assembly o SFTP nativo ──────────────────
# Metodo 1: usando FTP nativo de PowerShell + WebClient
$credential = New-Object System.Net.NetworkCredential($FTP_USER, $FTP_PASS)
$baseUri    = "ftp://${FTP_HOST}:${FTP_PORT}/${REMOTE_DIR}/"

$files   = Get-ChildItem $LOCAL_DIR -Recurse -File
$total   = $files.Count
$current = 0
$errors  = 0

foreach ($file in $files) {
    $current++
    $relPath    = $file.FullName.Substring($LOCAL_DIR.Length + 1).Replace("\", "/")
    $remoteUri  = $baseUri + $relPath

    Write-Progress -Activity "Subiendo archivos a Hostinger" `
                   -Status "$current/$total : $relPath" `
                   -PercentComplete (($current / $total) * 100)

    try {
        $req = [System.Net.FtpWebRequest]::Create($remoteUri)
        $req.Method      = [System.Net.WebRequestMethods+Ftp]::UploadFile
        $req.Credentials = $credential
        $req.UseBinary   = $true
        $req.UsePassive  = $true
        $req.KeepAlive   = $true
        $req.EnableSsl   = $true
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

        $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
        $req.ContentLength = $bytes.Length

        $stream = $req.GetRequestStream()
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Close()

        $resp = $req.GetResponse()
        $resp.Close()

        Write-Host "  [OK] $relPath" -ForegroundColor Green
    }
    catch {
        # Intentar crear el directorio padre si falla
        $dirPath = ($relPath -split "/")[0..($relPath.Split("/").Count - 2)] -join "/"
        if ($dirPath) {
            try {
                $dirUri  = $baseUri + $dirPath
                $dirReq  = [System.Net.FtpWebRequest]::Create($dirUri)
                $dirReq.Method      = [System.Net.WebRequestMethods+Ftp]::MakeDirectory
                $dirReq.Credentials = $credential
                $dirReq.UsePassive  = $true
                $dirReq.EnableSsl   = $true
                $dirResp = $dirReq.GetResponse()
                $dirResp.Close()
            } catch { <# directorio ya existe #> }

            # Reintentar subida
            try {
                $req2 = [System.Net.FtpWebRequest]::Create($remoteUri)
                $req2.Method      = [System.Net.WebRequestMethods+Ftp]::UploadFile
                $req2.Credentials = $credential
                $req2.UseBinary   = $true
                $req2.UsePassive  = $true
                $req2.EnableSsl   = $true

                $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
                $req2.ContentLength = $bytes.Length
                $s2 = $req2.GetRequestStream(); $s2.Write($bytes, 0, $bytes.Length); $s2.Close()
                $r2 = $req2.GetResponse(); $r2.Close()
                Write-Host "  [OK] $relPath" -ForegroundColor Green
            } catch {
                Write-Host "  [ERR] $relPath : $_" -ForegroundColor Red
                $errors++
            }
        } else {
            Write-Host "  [ERR] $relPath : $_" -ForegroundColor Red
            $errors++
        }
    }
}

Write-Progress -Activity "Subiendo archivos" -Completed
Write-Host ""
Write-Host "══════════════════════════════════════════" -ForegroundColor Cyan
if ($errors -eq 0) {
    Write-Host "  Deploy completado: $total archivos subidos" -ForegroundColor Green
} else {
    Write-Host "  Deploy con errores: $($total - $errors) OK, $errors fallidos" -ForegroundColor Yellow
}
Write-Host "  URL: https://www.vantelia.es/" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
