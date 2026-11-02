# Avvia in locale la webapp SEneCa EMS su Windows, con il backend Python.
# La prima volta crea .venv con Python 3.11 e installa le dipendenze bloccate.
# Uso: powershell -ExecutionPolicy Bypass -File scripts\avvia_webapp_ems.ps1 [-Porta 8501]
param([int]$Porta = 8501)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$stores = "pv_batteries_scenarios", "pv_batteries_gmd", "risanamento_scenarios", "risanamento_gmd", "veicoli_scenarios"
$mancanti = $stores | Where-Object { -not (Test-Path "precomputed\$_.parquet") }
if ($mancanti) {
    throw "Mancano i dati pre-calcolati ($($mancanti -join ', ')). Estrai lo ZIP dei dati EMS nella cartella $root."
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -m venv .venv
    } else {
        $versione = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
        if ($versione -ne "3.11") { throw "Serve Python 3.11 (trovato $versione): https://www.python.org/downloads/" }
        & python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw "Creazione dell'ambiente .venv non riuscita: serve Python 3.11." }
}
# Reinstalla solo se il lock delle dipendenze cambia rispetto all'ultima installazione.
$lock = (Get-FileHash "sure_julia\python.lock").Hash
$marker = ".venv\installed-lock.txt"
if (-not (Test-Path $marker) -or (Get-Content $marker) -ne $lock) {
    Write-Host "Installo le dipendenze (solo la prima volta, qualche minuto)..."
    & $python -m pip install --disable-pip-version-check -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Installazione delle dipendenze non riuscita." }
    Set-Content $marker $lock
}

$env:SURE_BACKEND = "python"
$env:SURE_VARIANT = "ems1"
$env:PYTHONIOENCODING = "utf-8"
Write-Host "Webapp SEneCa EMS su http://localhost:$Porta (Ctrl+C per fermarla)"
& $python -m streamlit run server.py --server.port $Porta --server.address 127.0.0.1 --browser.gatherUsageStats false
