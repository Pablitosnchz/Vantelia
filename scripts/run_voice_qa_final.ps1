# Pasada FINAL de QA de voz (una sola ejecucion, ~2-3 EUR de OpenAI).
# Ejecutar cuando la ventana rodante de cuota (RPD gpt-realtime) tenga hueco:
# lo quemado un dia a las ~16:30 se libera al dia siguiente a esa misma hora.
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_voice_qa_final.ps1
#
# No repite `calls` (ya aprobado 8/9 con los 3 fallos arreglados y unit-testeados).
# Corre: silence + schedule + deep completo, con pausas y reintentos anti-cuota.
# Aprobado = "ok": true en la primera linea del JSON de cada bloque
# (blocked_by_quota: true = repetir SOLO ese script mas tarde, no cuenta como fallo).

$env:QA_VOICE_SCENARIO_PAUSE_SECONDS = "45"
$env:QA_VOICE_RATE_LIMIT_RETRIES = "2"

Write-Host "==> silence" -ForegroundColor Cyan
python scripts\qa_voice_realtime_silence.py | Tee-Object -FilePath qa_voice_silence.json
Start-Sleep -Seconds 120

Write-Host "==> schedule" -ForegroundColor Cyan
python scripts\qa_voice_realtime_schedule.py | Tee-Object -FilePath qa_voice_schedule.json
Start-Sleep -Seconds 120

Write-Host "==> deep (completo)" -ForegroundColor Cyan
python scripts\qa_voice_realtime_deep.py | Tee-Object -FilePath qa_voice_deep.json

Write-Host ""
Write-Host "==> RESUMEN" -ForegroundColor Cyan
foreach ($f in @("qa_voice_silence.json", "qa_voice_schedule.json", "qa_voice_deep.json")) {
    if (Test-Path $f) {
        $raw = Get-Content $f -Raw
        $i = $raw.IndexOf("{")
        if ($i -ge 0) {
            try {
                $d = ($raw.Substring($i) | ConvertFrom-Json)
                Write-Host ("{0}: ok={1} quota={2} ran={3} passed={4}" -f $f, $d.ok, $d.blocked_by_quota, $d.ran, $d.passed)
            } catch { Write-Host "$($f): sin JSON parseable" }
        }
    }
}
