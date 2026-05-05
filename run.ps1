# run.ps1 — Antigravity Resume System: One-Command Startup
#
# Usage: .\run.ps1
# Installs dependencies, runs handshake tests, and starts the local server.
# Open your browser at: http://localhost:8000

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "⚡ Antigravity Resume System" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray

# Step 1: Check .env exists
if (-not (Test-Path ".env")) {
    Write-Host ""
    Write-Host "⚠  .env not found. Copying from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "   → .env created. Please add your DEEPSEEK_API_KEY before continuing." -ForegroundColor Yellow
    Write-Host "   → Edit .env, then re-run this script." -ForegroundColor Yellow
    exit 1
}

# Step 2: Install Python dependencies
Write-Host ""
Write-Host "📦 Installing dependencies..." -ForegroundColor DarkGray
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ pip install failed. Make sure Python and pip are installed." -ForegroundColor Red
    exit 1
}
Write-Host "   ✓ Dependencies installed" -ForegroundColor Green

# Step 3: Run handshake tests
Write-Host ""
Write-Host "🔌 Running connection tests..." -ForegroundColor DarkGray
python tools/test_db.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ DB test failed." -ForegroundColor Red
    exit 1
}

python tools/test_llm.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ LLM API test failed. Check your DEEPSEEK_API_KEY in .env." -ForegroundColor Red
    exit 1
}

# Step 4: Create .tmp and output dirs
New-Item -ItemType Directory -Force -Path ".tmp" | Out-Null
New-Item -ItemType Directory -Force -Path "output" | Out-Null

# Step 5: Start server
Write-Host ""
Write-Host "🚀 Starting server at http://localhost:8000" -ForegroundColor Green
Write-Host "   Upload your Overleaf CV PDF directly in the browser." -ForegroundColor DarkGray
Write-Host "   Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

python -m uvicorn app.main:app --reload --port 8000
