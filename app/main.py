"""
main.py — FastAPI Server Entry Point

Serves the GetFirst Resume System UI and API.
Run with: uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from tools.db_writer import init_db
from app.routes import generate, applications

# ─── App Init ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="GetFirst Resume System",
    description="Deterministic, truth-preserving CV tailoring pipeline.",
    version="0.1.0",
)

# Initialize DB on startup
@app.on_event("startup")
async def startup_event():
    init_db()

# ─── API Routes ───────────────────────────────────────────────────────────────

app.include_router(generate.router, prefix="/api")
app.include_router(applications.router, prefix="/api")

# ─── Static Files ─────────────────────────────────────────────────────────────

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

@app.get("/")
async def root():
    return FileResponse(str(_STATIC_DIR / "index.html"))
