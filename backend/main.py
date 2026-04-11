"""
ConvertX API — Final Production Entry Point.

Run locally:
    uvicorn backend.main:app --reload --port 8000

Production:
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1
"""

import asyncio
import logging
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from backend.config import (
    ENVIRONMENT, DEBUG, ALLOWED_ORIGINS,
    CLEANUP_INTERVAL_SECONDS, LIBREOFFICE_PATH, TESSERACT_PATH,
)
from backend.utils.file_utils import (
    cleanup_expired_files, cleanup_all_files,
    get_file_entry, unregister_file,
)
from backend.utils.response_models import HealthResponse, ErrorResponse

# ═══════════════════════════════════════════════════════════════════════════════
# Logging & Tool Detection
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("convertx")

def _check_tool(cmd: str, name: str) -> bool:
    try:
        r = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            logger.info("%s detected: %s", name, (r.stdout or r.stderr).strip().split("\n")[0])
            return True
    except Exception: pass
    logger.warning("%s NOT found at '%s'", name, cmd)
    return False

TESSERACT_AVAILABLE = _check_tool(TESSERACT_PATH, "Tesseract OCR")
LIBREOFFICE_AVAILABLE = _check_tool(LIBREOFFICE_PATH, "LibreOffice")

# ═══════════════════════════════════════════════════════════════════════════════
# Lifespan
# ═══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("ConvertX API v1.0.0 starting | Env: %s | Debug: %s", ENVIRONMENT, DEBUG)
    logger.info("Tools -> Tesseract: %s | LibreOffice: %s", 
                "✓" if TESSERACT_AVAILABLE else "✗", "✓" if LIBREOFFICE_AVAILABLE else "✗")
    logger.info("=" * 60)
    
    task = asyncio.create_task(_periodic_cleanup())
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
    cleanup_all_files()
    logger.info("ConvertX stopped.")

async def _periodic_cleanup():
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            d = cleanup_expired_files()
            if d: logger.info("Cleanup: %d files removed", d)
        except Exception as e: logger.error("Cleanup err: %s", e)

# ═══════════════════════════════════════════════════════════════════════════════
# App Setup
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="ConvertX API",
    version="1.0.0",
    docs_url="/api/docs" if DEBUG else None,
    redoc_url="/api/redoc" if DEBUG else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# Core Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/", tags=["system"])
async def root():
    """Friendly root endpoint — prevents confusing 'Not Found' when visiting the backend URL directly."""
    return {
        "name": "ConvertX API",
        "version": "1.0.0",
        "status": "running",
        "health": "/api/health",
        "docs": "/api/docs" if DEBUG else "disabled (set ENVIRONMENT=development)",
    }

@app.get("/api/health", response_model=HealthResponse, tags=["system"])
async def health():
    return HealthResponse(tesseract_available=TESSERACT_AVAILABLE, libreoffice_available=LIBREOFFICE_AVAILABLE)

@app.get("/api/download/{filename}", tags=["download"])
async def download(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename or filename.startswith(".") or len(filename) > 100:
        raise HTTPException(400, "Invalid filename.")
    
    entry = get_file_entry(filename)
    if not entry or not entry.file_path.exists():
        raise HTTPException(404, "File not found or has expired.")
        
    entry.download_count += 1
    if entry.download_count == 1:
        asyncio.create_task(_delete_later(filename, entry.file_path))

    return FileResponse(path=str(entry.file_path), filename=entry.original_filename, media_type="application/octet-stream")

async def _delete_later(uuid: str, path: Path, delay: int = 30):
    await asyncio.sleep(delay)
    try:
        if path.exists(): path.unlink()
        unregister_file(uuid)
    except Exception as e: logger.warning("Post-dl cleanup err: %s", e)

# ═══════════════════════════════════════════════════════════════════════════════
# Error Handlers
# ═══════════════════════════════════════════════════════════════════════════════

@app.exception_handler(HTTPException)
async def http_err(request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=ErrorResponse(error=exc.detail, detail=exc.detail).model_dump())

@app.exception_handler(Exception)
async def gen_err(request, exc: Exception):
    logger.error("Unhandled on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content=ErrorResponse(error="Internal server error", detail="").model_dump())

# ═══════════════════════════════════════════════════════════════════════════════
# Routers (19 Endpoints Total)
# ═══════════════════════════════════════════════════════════════════════════════

from backend.routes.pdf_core_routes import router as pdf_core_router
from backend.routes.pdf_to_office_routes import router as pdf_to_office_router
from backend.routes.office_to_pdf_routes import router as office_to_pdf_router
from backend.routes.pdf_edit_routes import router as pdf_edit_router
from backend.routes.image_routes import router as image_router
from backend.routes.html_routes import router as html_router

app.include_router(pdf_core_router)        # 8 endpoints
app.include_router(pdf_to_office_router)   # 3 endpoints
app.include_router(office_to_pdf_router)   # 3 endpoints
app.include_router(pdf_edit_router)        # 2 endpoints
app.include_router(image_router)           # 2 endpoints
app.include_router(html_router)            # 1 endpoint
