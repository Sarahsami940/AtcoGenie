# =============================================================================
# AtcoGenie AI Engine — Development Setup Script (Windows PowerShell)
# Run this once to set up your Python dev environment.
# =============================================================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AtcoGenie AI Engine — Dev Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Check Python
Write-Host "[1/5] Checking Python installation..." -ForegroundColor Yellow
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "  ERROR: Python not found. Install Python 3.12+ from python.org" -ForegroundColor Red
    exit 1
}
$version = python --version
Write-Host "  Found: $version" -ForegroundColor Green

# 2. Create virtual environment
Write-Host "[2/5] Creating virtual environment..." -ForegroundColor Yellow
$venvPath = Join-Path $ProjectRoot ".venv"
if (Test-Path $venvPath) {
    Write-Host "  Virtual environment already exists at $venvPath" -ForegroundColor Gray
} else {
    python -m venv $venvPath
    Write-Host "  Created: $venvPath" -ForegroundColor Green
}

# 3. Activate and install dependencies
Write-Host "[3/5] Installing dependencies..." -ForegroundColor Yellow
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
& $activateScript
pip install -r (Join-Path $ProjectRoot "requirements.txt") --quiet
Write-Host "  Dependencies installed" -ForegroundColor Green

# 4. Create .env from template
Write-Host "[4/5] Checking .env file..." -ForegroundColor Yellow
$envFile = Join-Path $ProjectRoot ".env"
$envExample = Join-Path $ProjectRoot ".env.example"
if (Test-Path $envFile) {
    Write-Host "  .env already exists — skipping" -ForegroundColor Gray
} else {
    Copy-Item $envExample $envFile
    Write-Host "  Created .env from .env.example" -ForegroundColor Green
    Write-Host "  >>> IMPORTANT: Edit .env and fill in your API keys and passwords <<<" -ForegroundColor Red
}

# 5. Check Docker (optional)
Write-Host "[5/5] Checking Docker..." -ForegroundColor Yellow
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    Write-Host "  Docker found. Run: docker-compose up -d" -ForegroundColor Green
} else {
    Write-Host "  Docker not found — Redis and PostgreSQL must be installed manually" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Edit .env with your API keys and DB passwords" -ForegroundColor White
Write-Host "  2. Start Redis + PostgreSQL: docker-compose up -d" -ForegroundColor White
Write-Host "  3. Activate venv: .\.venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  4. Run the server: python -m app.main" -ForegroundColor White
Write-Host "  5. Open: http://localhost:8000/docs" -ForegroundColor White
Write-Host ""
