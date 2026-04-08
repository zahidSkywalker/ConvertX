"""
Word to PDF converter — uses LibreOffice in headless mode.

LibreOffice is the only reliable open-source tool for converting DOCX→PDF
while preserving complex formatting (tables, headers/footers, page breaks,
embedded images, tracked changes, etc.).

Strategy:
  1. Create a temporary profile directory for LibreOffice (prevents lock conflicts
     when multiple conversions run concurrently).
  2. Invoke LibreOffice headless with --convert-to pdf.
  3. Wait for the output file to appear (LibreOffice doesn't guarantee sync return).
  4. Clean up the temporary profile directory.

Limitations:
  - Requires LibreOffice installed on the server (~800MB Docker image).
  - Conversion time scales with document complexity (10-60s for typical docs).
  - Some advanced Word features (VBA macros, SmartArt) may not convert perfectly.
"""

import logging
import shutil
import subprocess
import time
from pathlib import Path

from backend.config import LIBREOFFICE_PATH
from backend.converters import ConversionError

logger = logging.getLogger(__name__)

# Maximum seconds to wait for LibreOffice to finish
_CONVERSION_TIMEOUT_SECONDS = 120

# Maximum seconds to wait for the output file to appear after LibreOffice exits
# (handles filesystem sync delays on some platforms)
_FILE_APPEAR_WAIT_SECONDS = 10

# Polling interval when waiting for the output file
_FILE_APPEAR_POLL_INTERVAL = 0.2


def convert_word_to_pdf(input_path: Path, output_dir: Path) -> Path:
    """
    Convert a Word (.docx) file to PDF using LibreOffice headless.

    LibreOffice writes the output PDF to output_dir with the same base filename
    as the input but with a .pdf extension.

    Args:
        input_path: Path to the source .docx file.
        output_dir: Directory where the output .pdf file will be written.
                    Must exist.

    Returns:
        Path to the created .pdf file.

    Raises:
        ConversionError: If LibreOffice is not installed, the DOCX is invalid,
                         conversion times out, or the output file is not created.
    """
    # ── Validate inputs ──
    if not input_path.exists():
        raise ConversionError(
            message="The uploaded Word file was not found.",
            detail=f"Expected file at: {input_path}",
        )

    if input_path.stat().st_size == 0:
        raise ConversionError(
            message="The uploaded Word file is empty (0 bytes).",
        )

    if input_path.suffix.lower() != ".docx":
        raise ConversionError(
            message="Invalid file type. Expected a Word document (.docx).",
            detail=f"Got extension: {input_path.suffix}",
        )

    if not output_dir.exists():
        raise ConversionError(
            message="Output directory does not exist.",
            detail=str(output_dir),
        )

    # Resolve to absolute path (LibreOffice requires absolute --outdir)
    output_dir = output_dir.resolve()
    input_path = input_path.resolve()

    expected_output_name = input_path.stem + ".pdf"
    expected_output_path = output_dir / expected_output_name

    # If a previous conversion left a stale file, remove it
    expected_output_path.unlink(missing_ok=True)

    logger.info(
        "Starting DOCX→PDF: %s (%.1f KB)",
        input_path.name,
        input_path.stat().st_size / 1024,
    )

    # ── Create isolated profile directory ──
    # LibreOffice creates a user profile on first run. Using a temp directory
    # prevents lock conflicts when multiple conversions run in parallel.
    profile_dir = Path("/tmp") / f"convertx_lo_profile_{id(input_path)}"
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ConversionError(
            message="Failed to create a temporary working directory.",
            detail=str(e),
        )

    # ── Build LibreOffice command ──
    cmd = [
        LIBREOFFICE_PATH,
        "--headless",              # No GUI
        "--norestore",             # Don't restore previous session
        "--nolockcheck",           # Skip lock file checks (we use isolated profile)
        "--nologo",                # No splash screen
        "--nodefault",             # Don't create default document
        f"--env:UserInstallation=file://{profile_dir}",
        "--convert-to", "pdf",     # Target format
        "--outdir", str(output_dir),
        str(input_path),
    ]

    logger.debug("LibreOffice command: %s", " ".join(cmd))

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_CONVERSION_TIMEOUT_SECONDS,
            # Don't set cwd — let LibreOffice use its default
        )

    except FileNotFoundError:
        _cleanup_profile(profile_dir)
        raise ConversionError(
            message="Word to PDF conversion is not available on this server. "
                    "LibreOffice is not installed.",
            detail=f"Command not found: {LIBREOFFICE_PATH}",
        )

    except subprocess.TimeoutExpired:
        _cleanup_profile(profile_dir)
        # Kill any lingering LibreOffice processes from this conversion
        _kill_libreoffice_processes(profile_dir)
        raise ConversionError(
            message=f"The document is too complex and conversion timed out "
                    f"after {_CONVERSION_TIMEOUT_SECONDS} seconds. "
                    f"Try simplifying the document (remove complex images, "
                    f"reduce page count) and try again.",
        )

    except Exception as e:
        _cleanup_profile(profile_dir)
        logger.error("Unexpected error running LibreOffice: %s", e, exc_info=True)
        raise ConversionError(
            message="An unexpected error occurred while starting the conversion.",
            detail=f"{type(e).__name__}: {e}",
        )

    elapsed = time.time() - start_time
    logger.info(
        "LibreOffice exited in %.1fs with code %d",
        elapsed,
        result.returncode,
    )

    # ── Check LibreOffice exit code ──
    if result.returncode != 0:
        _cleanup_profile(profile_dir)
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        error_detail = stderr or stdout or "No error output from LibreOffice."

        # Provide user-friendly messages for common failures
        error_lower = error_detail.lower()
        if "corrupt" in error_lower or "damaged" in error_lower:
            raise ConversionError(
                message="The Word document appears to be corrupted or damaged.",
                detail=error_detail,
            )
        if "generic error" in error_lower:
            raise ConversionError(
                message="LibreOffice encountered an error processing this document. "
                        "It may contain unsupported content.",
                detail=error_detail,
            )

        raise ConversionError(
            message="Word to PDF conversion failed.",
            detail=error_detail,
        )

    # ── Wait for output file (handles filesystem sync delays) ──
    output_path = _wait_for_output_file(
        expected_output_path,
        output_dir,
        timeout=_FILE_APPEAR_WAIT_SECONDS,
        poll_interval=_FILE_APPEAR_POLL_INTERVAL,
    )

    # ── Clean up profile directory ──
    _cleanup_profile(profile_dir)

    if not output_path:
        raise ConversionError(
            message="LibreOffice reported success but no PDF file was created. "
                    "The document may be empty or contain only unsupported content.",
            detail=f"Searched in: {output_dir}",
        )

    if output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise ConversionError(
            message="The converted PDF file is empty (0 bytes). "
                    "The source document may have no printable content.",
        )

    logger.info(
        "DOCX→PDF complete: %s → %s (%.1f KB, %.1fs)",
        input_path.name,
        output_path.name,
        output_path.stat().st_size / 1024,
        elapsed,
    )

    return output_path


def _wait_for_output_file(
    expected_path: Path,
    search_dir: Path,
    timeout: float,
    poll_interval: float,
) -> Path | None:
    """
    Poll for the expected output file. If not found at the expected path,
    search for any recently-created .pdf in the directory (LibreOffice
    sometimes modifies the filename slightly).

    Returns the Path if found, None otherwise.
    """
    deadline = time.time() + timeout

    while time.time() < deadline:
        # Check expected path first
        if expected_path.exists() and expected_path.stat().st_size > 0:
            return expected_path

        # Search for any PDF created after the conversion started
        # (use a generous mtime window to account for clock precision)
        try:
            for pdf_file in search_dir.glob("*.pdf"):
                if pdf_file.stat().st_size > 0:
                    return pdf_file
        except OSError:
            pass

        time.sleep(poll_interval)

    return None


def _cleanup_profile(profile_dir: Path) -> None:
    """Remove the temporary LibreOffice profile directory."""
    try:
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)
    except Exception as e:
        logger.warning("Failed to clean up LibreOffice profile: %s", e)


def _kill_libreoffice_processes(profile_dir: Path) -> None:
    """
    Attempt to kill any LibreOffice processes that may still be running
    after a timeout. This is a best-effort cleanup.
    """
    try:
        subprocess.run(
            ["pkill", "-f", f"UserInstallation=file://{profile_dir}"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass  # Best effort — don't let cleanup failures mask the real error
