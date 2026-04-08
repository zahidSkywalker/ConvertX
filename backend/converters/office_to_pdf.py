"""
Office to PDF converter — unified wrapper for Word, Excel, and PowerPoint.

Uses LibreOffice headless to perform the conversion. LibreOffice is the only
reliable open-source method for converting OOXML formats (.docx, .xlsx, .pptx)
to PDF while preserving complex formatting.

All three formats use the exact same LibreOffice command (`--convert-to pdf`).
This module provides a single robust execution function and three thin public
wrappers for clarity.
"""

import logging
import shutil
import subprocess
import time
from pathlib import Path

from backend.config import LIBREOFFICE_PATH
from backend.converters import ConversionError

logger = logging.getLogger(__name__)

# ─── Execution Limits ───────────────────────────────────────────────────────
# LibreOffice can take a long time on large PPTX files with embedded videos.
# 180 seconds is generous but prevents zombie processes.
_CONVERSION_TIMEOUT_SECONDS = 180

# Filesystem sync delay handling
_FILE_APPEAR_WAIT_SECONDS = 15
_FILE_APPEAR_POLL_INTERVAL = 0.25

# ─── Allowed Extensions ─────────────────────────────────────────────────────
_ALLOWED_EXTENSIONS = {".docx", ".xlsx", ".pptx"}


# ═══════════════════════════════════════════════════════════════════════════════
# Public API — One function per format for clean route wiring
# ═══════════════════════════════════════════════════════════════════════════════

def convert_word_to_pdf(input_path: Path, output_dir: Path) -> Path:
    """Convert a Word (.docx) document to PDF."""
    _validate_office_input(input_path, ".docx", "Word")
    return _execute_libreoffice(input_path, output_dir)


def convert_excel_to_pdf(input_path: Path, output_dir: Path) -> Path:
    """Convert an Excel (.xlsx) spreadsheet to PDF."""
    _validate_office_input(input_path, ".xlsx", "Excel")
    return _execute_libreoffice(input_path, output_dir)


def convert_powerpoint_to_pdf(input_path: Path, output_dir: Path) -> Path:
    """Convert a PowerPoint (.pptx) presentation to PDF."""
    _validate_office_input(input_path, ".pptx", "PowerPoint")
    return _execute_libreoffice(input_path, output_dir)


# ═══════════════════════════════════════════════════════════════════════════════
# Core Execution Engine
# ═══════════════════════════════════════════════════════════════════════════════

def _execute_libreoffice(input_path: Path, output_dir: Path) -> Path:
    """
    Run LibreOffice headless to convert an Office file to PDF.

    Handles:
      - Profile isolation (prevents lock conflicts)
      - Timeout enforcement with process cleanup
      - Filesystem sync delay polling
      - Detailed error parsing from stderr
    """
    output_dir = output_dir.resolve()
    input_path = input_path.resolve()

    expected_output_name = input_path.stem + ".pdf"
    expected_output_path = output_dir / expected_output_name
    expected_output_path.unlink(missing_ok=True)

    # Isolated profile directory
    profile_dir = Path("/tmp") / f"convertx_lo_{id(input_path)}"
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ConversionError("Failed to create temporary working directory.", detail=str(e))

    cmd = [
        LIBREOFFICE_PATH,
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--nologo",
        "--nodefault",
        f"--env:UserInstallation=file://{profile_dir}",
        "--convert-to", "pdf",
        "--outdir", str(output_dir),
        str(input_path),
    ]

    logger.debug("LibreOffice CMD: %s", " ".join(cmd))
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_CONVERSION_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        _cleanup_profile(profile_dir)
        raise ConversionError(
            "Office to PDF conversion is unavailable. LibreOffice is not installed.",
            detail=f"Command not found: {LIBREOFFICE_PATH}",
        )
    except subprocess.TimeoutExpired:
        _cleanup_profile(profile_dir)
        _kill_libreoffice_processes(profile_dir)
        raise ConversionError(
            f"Conversion timed out after {_CONVERSION_TIMEOUT_SECONDS} seconds. "
            f"The file may be too large or contain unsupported embedded content.",
        )
    except Exception as e:
        _cleanup_profile(profile_dir)
        logger.error("Unexpected LibreOffice error: %s", e, exc_info=True)
        raise ConversionError("Failed to start the conversion process.", detail=str(e))

    elapsed = time.time() - start_time
    logger.info("LibreOffice exited in %.1fs (code %d)", elapsed, result.returncode)

    if result.returncode != 0:
        _cleanup_profile(profile_dir)
        error_detail = (result.stderr or result.stdout or "No output from LibreOffice.").strip()
        
        error_lower = error_detail.lower()
        if "corrupt" in error_lower or "damaged" in error_lower:
            raise ConversionError("The Office file appears to be corrupted.", detail=error_detail)
        if "generic error" in error_lower:
            raise ConversionError("LibreOffice failed to process this file.", detail=error_detail)
            
        raise ConversionError("Conversion failed.", detail=error_detail)

    # Wait for output file
    output_path = _wait_for_output_file(expected_output_path, output_dir)
    _cleanup_profile(profile_dir)

    if not output_path:
        raise ConversionError(
            "Conversion reported success but no PDF was created. The file may be empty."
        )

    if output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise ConversionError("The converted PDF is empty (0 bytes).")

    logger.info(
        "Office→PDF complete: %s → %s (%.1f KB, %.1fs)",
        input_path.name, output_path.name, output_path.stat().st_size / 1024, elapsed
    )
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# Internal Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _validate_office_input(path: Path, expected_ext: str, format_name: str) -> None:
    """Validate file exists, is not empty, and has the correct extension."""
    if not path.exists():
        raise ConversionError(f"The uploaded {format_name} file was not found.")
    if path.stat().st_size == 0:
        raise ConversionError(f"The uploaded {format_name} file is empty (0 bytes).")
    if path.suffix.lower() != expected_ext:
        raise ConversionError(
            f"Invalid file type. Expected a {format_name} file ({expected_ext}).",
            detail=f"Got extension: {path.suffix}",
        )


def _wait_for_output_file(expected_path: Path, search_dir: Path) -> Path | None:
    """Poll for the output PDF, handling filesystem sync delays."""
    deadline = time.time() + _FILE_APPEAR_WAIT_SECONDS
    while time.time() < deadline:
        if expected_path.exists() and expected_path.stat().st_size > 0:
            return expected_path
        try:
            for pdf_file in search_dir.glob("*.pdf"):
                if pdf_file.stat().st_size > 0:
                    return pdf_file
        except OSError:
            pass
        time.sleep(_FILE_APPEAR_POLL_INTERVAL)
    return None


def _cleanup_profile(profile_dir: Path) -> None:
    """Remove the temporary LibreOffice profile directory."""
    try:
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)
    except Exception as e:
        logger.warning("Failed to cleanup LibreOffice profile: %s", e)


def _kill_libreoffice_processes(profile_dir: Path) -> None:
    """Best-effort cleanup of lingering LibreOffice processes."""
    try:
        subprocess.run(
            ["pkill", "-f", f"UserInstallation=file://{profile_dir}"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass
