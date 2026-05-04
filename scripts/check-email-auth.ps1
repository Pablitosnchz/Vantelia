param([string]$Domain = "vantelia.es")

Write-Host "Comprobando registros email auth para $Domain" -ForegroundColor Cyan
Write-Host ""

Write-Host "== SPF ==" -ForegroundColor Yellow
nslookup -type=TXT $Domain 8.8.8.8 2>&1 | Select-String "v=spf1"

Write-Host ""
Write-Host "== DKIM (probando selectores comunes) ==" -ForegroundColor Yellow
foreach ($sel in @("hostingermail", "hostinger", "default", "mail")) {
    $name = "$sel._domainkey.$Domain"
    Write-Host "  -> $name"
    nslookup -type=TXT $name 8.8.8.8 2>&1 | Select-String "v=DKIM1"
}

Write-Host ""
Write-Host "== DMARC ==" -ForegroundColor Yellow
nslookup -type=TXT "_dmarc.$Domain" 8.8.8.8 2>&1 | Select-String "v=DMARC1"

Write-Host ""
Write-Host "Verifica tambien online:" -ForegroundColor Cyan
Write-Host "  https://mxtoolbox.com/SuperTool.aspx?action=spf%3a$Domain"
Write-Host "  https://mxtoolbox.com/SuperTool.aspx?action=dmarc%3a$Domain"
Write-Host "  https://www.mail-tester.com/  (envia un correo de prueba al hash que te da)"
