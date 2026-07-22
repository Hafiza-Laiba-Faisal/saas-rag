# ============================================================
#  TenBit RAG Platform — Dev Launcher (Windows PowerShell)
#  Usage: .\dev-start.ps1
#  (Run PowerShell as Administrator if Docker requires it)
# ============================================================

$ErrorActionPreference = "Stop"

$ROOT     = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKEND  = Join-Path $ROOT "rbs-rag-node"
$FRONTEND = Join-Path $ROOT "chic-interface-design"

function Write-Log   { param($msg) Write-Host "[RAG] $msg" -ForegroundColor Cyan }
function Write-Ok    { param($msg) Write-Host "[RAG] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[RAG] $msg" -ForegroundColor Yellow }

# ── 0. Directory sanity checks ────────────────────────────────
if (-not (Test-Path $BACKEND))  { Write-Host "[RAG] Missing: $BACKEND" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $FRONTEND)) { Write-Host "[RAG] Missing: $FRONTEND" -ForegroundColor Red; exit 1 }

# ── 1. Start Docker containers ────────────────────────────────
Write-Log "Starting Docker containers (qdrant, redis, scraper_service, ocr_service)..."
Set-Location $ROOT
docker compose up -d qdrant redis scraper_service ocr_service

# ── 2. Wait for Qdrant ───────────────────────────────────────
Write-Log "Waiting for Qdrant to be ready..."
$ready = $false
for ($i = 1; $i -le 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:6333/" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($r.StatusCode -lt 500) { Write-Ok "Qdrant is ready."; $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $ready) { Write-Warn "Qdrant did not respond — continuing anyway." }

# ── 3. Wait for Redis ────────────────────────────────────────
Write-Log "Waiting for Redis to be ready..."
$ready = $false
for ($i = 1; $i -le 15; $i++) {
    $result = docker exec tenbit-redis redis-cli ping 2>$null
    if ($result -match "PONG") { Write-Ok "Redis is ready."; $ready = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $ready) { Write-Warn "Redis did not respond — continuing anyway." }

# ── 4. Wait for Scraper ──────────────────────────────────────
Write-Log "Waiting for Scraper service to be ready..."
$ready = $false
for ($i = 1; $i -le 20; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8002/" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($r.StatusCode -lt 500) { Write-Ok "Scraper service is ready."; $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 3
}
if (-not $ready) { Write-Warn "Scraper service did not respond — continuing anyway." }

# ── 5. Start Backend in new window ───────────────────────────
Write-Log "Starting backend (Node.js dev server)..."
$backendCmd = "Set-Location '$BACKEND'; `$env:SCRAPER_SERVICE_URL='http://localhost:8002'; npm run dev"
$backendProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd -PassThru
Write-Ok "Backend started (PID $($backendProcess.Id))"

# ── 6. Start Frontend in new window ──────────────────────────
Write-Log "Starting frontend (Vite dev server)..."
$frontendCmd = "Set-Location '$FRONTEND'; npm run dev"
$frontendProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd -PassThru
Write-Ok "Frontend started (PID $($frontendProcess.Id))"

# ── 7. Docker logs in new window (scraper + ocr — these run detached, no logs otherwise visible) ─
Write-Log "Opening Docker logs (scraper_service + ocr_service)..."
$dockerLogsCmd = "docker compose logs -f scraper_service ocr_service"
$dockerLogsProcess = Start-Process powershell -ArgumentList "-NoExit", "-Command", $dockerLogsCmd -PassThru
Write-Ok "Docker logs window started (PID $($dockerLogsProcess.Id))"

# ── 8. Print summary ─────────────────────────────────────────
Write-Host ""
Write-Host "════════════════════════════════════════" -ForegroundColor Green
Write-Host "  RAG Platform is starting up!          " -ForegroundColor Green
Write-Host "  Frontend  -> http://localhost:5173    " -ForegroundColor Green
Write-Host "  Backend   -> http://localhost:3001    " -ForegroundColor Green
Write-Host "  Qdrant    -> http://localhost:6333    " -ForegroundColor Green
Write-Host "  Scraper   -> http://localhost:8002    " -ForegroundColor Green
Write-Host "  OCR       -> http://localhost:8000    " -ForegroundColor Green
Write-Host "                                        " -ForegroundColor Green
Write-Host "  Close the opened windows to stop.    " -ForegroundColor Green
Write-Host "════════════════════════════════════════" -ForegroundColor Green
Write-Host ""

# Open browser after a short delay
Start-Sleep -Seconds 5
Start-Process "http://localhost:5173"
