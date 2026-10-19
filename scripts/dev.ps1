# Start Lifafa: Ollama (if needed) + the app on http://localhost:8020
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 2 | Out-Null }
catch {
    $ollama = (Get-Command ollama -ErrorAction SilentlyContinue)?.Source
    if (-not $ollama) { $ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" }
    if (Test-Path $ollama) { Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep 3 }
    else { Write-Warning "Ollama not found. You can still type entries in by hand." }
}
Set-Location $root
.\.venv\Scripts\python -m uvicorn lifafa.main:app --host 0.0.0.0 --port 8020
