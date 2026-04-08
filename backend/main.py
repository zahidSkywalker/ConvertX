"""
ConvertX — FastAPI application entry point.

Run locally:
    cd convertx
    uvicorn backend.main:app --reload --port 8000

Run in production:
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1

Note: Workers must be 1 because we use in-memory file registry.
      For multi-worker scaling, swap the registry for Redis.
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
    ENVIRONMENT,
    DEBUG,
    ALLOWED_ORIGINS,
    CLEANUP_INTERVAL_SECONDS,
    LIBREOFFICE_PATH,
    TESSERACT_PATH,
)
from backend.utils.file_utils import (
    cleanup_expired_files,
    cleanup_all_files,
    get_file_entry,
    unregister_file,
)
from backend.utils.response_models import (
    HealthResponse,
    ErrorResponse,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Logging Configuration
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("convertx")


# ═══════════════════════════════════════════════════════════════════════════════
# External Tool Detection — run once at startup to report availability
# ═══════════════════════════════════════════════════════════════════════════════

def _check_tool_installed(command: str, display_name: str) -> bool:
    """
    Try to run `{command} --version` to verify the tool is installed.
    Returns True if the command succeeds, False otherwise.
    """
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        available = result.returncode == 0
        if available:
            version_line = (result.stdout or result.stderr or "").strip().split("\n")[0]
            logger.info("%s detected: %s", display_name, version_line)
        return available
    except FileNotFoundError:
        logger.warning("%s not found at '%s'", display_name, command)
        return False
    except subprocess.TimeoutExpired:
        logger.warning("%s timed out during version check", display_name)
        return False


TESSERACT_AVAILABLE: bool = _check_tool_installed(TESSERACT_PATH, "Tesseract OCR")
LIBREOFFICE_AVAILABLE: bool = _check_tool_installed(LIBREOFFICE_PATH, "LibreOffice")


# ═══════════════════════════════════════════════════════════════════════════════
# Application Lifespan — startup and shutdown hooks
# ═══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the application lifecycle:
      - Startup: log status, launch background cleanup task
      - Shutdown: cancel cleanup, delete all temp files
    """
    # ── Startup ──
    logger.info("=" * 60)
    logger.info("ConvertX API starting")
    logger.info("  Environment : %s", ENVIRONMENT)
    logger.info("  Debug       : %s", DEBUG)
    logger.info("  Tesseract   : %s", "available" if TESSERACT_AVAILABLE else "NOT installed (Image->Excel disabled)")
    logger.info("  LibreOffice : %s", "available" if LIBREOFFICE_AVAILABLE else "NOT installed (Word->PDF disabled)")
    logger.info("  CORS origins: %s", ALLOWED_ORIGINS)
    logger.info("=" * 60)

    cleanup_task = asyncio.create_task(_periodic_cleanup())

    yield

    # ── Shutdown ──
    logger.info("ConvertX shutting down...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    cleanup_all_files()
    logger.info("ConvertX stopped cleanly")


async def _periodic_cleanup():
    """Background coroutine — removes temp files older than the configured TTL."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            deleted = cleanup_expired_files()
            if deleted:
                logger.info("Periodic cleanup: removed %d expired file(s)", deleted)
        except Exception as e:
            logger.error("Periodic cleanup failed: %s", e, exc_info=True)


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI Application Instance
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="ConvertX API",
    description="All-in-one file conversion API — PDF, Word, Image, OCR",
    version="1.0.0",
    docs_url="/api/docs" if DEBUG else None,
    redoc_url="/api/redoc" if DEBUG else None,
    lifespan=lifespan,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Middleware
# ═══════════════════════════════════════════════════════════════════════════════

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════════════════
# Public Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/health", response_model=HealthResponse, tags=["system"])
async def health_check():
    """
    Health check endpoint — reports tool availability.
    Used by deploy platforms and monitoring.
    """
    return HealthResponse(
        tesseract_available=TESSERACT_AVAILABLE,
        libreoffice_available=LIBREOFFICE_AVAILABLE,
    )


@app.get("/api/download/{filename}", tags=["download"])
async def download_file(filename: str):
    """
    Serve a converted file for download.

    The filename must be a UUID-based name generated by the server.
    After the first download, the file is deleted after a 30-second
    grace period to handle slow connections or retries.
    """
    # ── Security: reject path traversal attempts ──
    if (
        "/" in filename
        or "\\" in filename
        or ".." in filename
        or filename.startswith(".")
        or len(filename) > 100
    ):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    entry = get_file_entry(filename)
    if not entry or not entry.file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="File not found or has expired. Converted files are kept "
                   "for 10 minutes after conversion, or 30 seconds after download.",
        )

    entry.download_count += 1
    logger.info(
        "Download: '%s' → %s (download #%d)",
        entry.original_filename,
        filename,
        entry.download_count,
    )

    # Schedule deletion after first download (30s grace period)
    if entry.download_count == 1:
        asyncio.create_task(
            _delete_after_download(filename, entry.file_path, delay_seconds=30)
        )

    return FileResponse(
        path=str(entry.file_path),
        filename=entry.original_filename,
        media_type="application/octet-stream",
    )


async def _delete_after_download(
    uuid_filename: str,
    file_path: Path,
    delay_seconds: int,
):
    """
    Wait for the grace period, then delete the file and remove from registry.
    Handles slow connections and browser retries on interrupted downloads.
    """
    await asyncio.sleep(delay_seconds)
    try:
        if file_path.exists():
            file_path.unlink()
            logger.info("Post-download cleanup: deleted '%s'", uuid_filename)
        unregister_file(uuid_filename)
    except Exception as e:
        logger.warning(
            "Post-download cleanup failed for '%s': %s", uuid_filename, e
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Error Handlers
# ═══════════════════════════════════════════════════════════════════════════════

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    """Convert HTTPExceptions to our standard ErrorResponse format."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail,
            detail=exc.detail,
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """Catch-all — log full traceback, return safe message to client."""
    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            detail="An unexpected error occurred. Please try again.",
        ).model_dump(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Routers — conversion endpoints
# ═══════════════════════════════════════════════════════════════════════════════

from backend.routes.pdf_routes import router as pdf_router
from backend.routes.image_routes import router as image_router

app.include_router(pdf_router)
app.include_router(image_router)
