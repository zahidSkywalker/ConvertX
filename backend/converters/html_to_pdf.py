"""
HTML to PDF converter — uses WeasyPrint.

Renders HTML strings into pixel-perfect PDF documents. WeasyPrint supports
modern CSS (Flexbox, Grid, CSS Variables, Web Fonts) and handles page breaks,
margins, and headers/footers via CSS `@page` rules.

Security:
  WeasyPrint has the ability to fetch external resources (images, CSS) via URLs.
  If a user submits HTML like `<img src="file:///etc/passwd">`, WeasyPrint would
  read the file and embed it in the PDF (SSRF/Local File Read).

  To prevent this, we inject a custom `url_fetcher` that:
    1. Blocks all non-HTTP/HTTPS protocols (prevents file://, ftp://, data:).
    2. Blocks requests to internal/private IP ranges (prevents SSRF against
       cloud metadata endpoints like 169.254.169.254).
    3. Enforces a file size limit on fetched resources (prevents memory bombs).
    4. Restricts allowed MIME types (images and CSS only).
"""

import io
import ipaddress
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.converters import ConversionError

logger = logging.getLogger(__name__)

# ─── Import Guard ──────────────────────────────────────────────────────────
try:
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    _HAS_WEASYPRINT = True
except ImportError:
    _HAS_WEASYPRINT = False
    HTML = None

# ─── Security Constants ────────────────────────────────────────────────────
# Maximum size for externally fetched resources (1 MB)
_MAX_RESOURCE_SIZE_BYTES = 1024 * 1024

# Allowed MIME types for external resources
_ALLOWED_RESOURCE_TYPES = {
    "text/css",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/svg+xml",
    "image/webp",
    "image/x-icon",
    "font/woff",
    "font/woff2",
    "font/ttf",
    "font/otf",
}

# Blocked IP networks (Private, Loopback, Link-Local, Cloud Metadata)
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"), # AWS/GCP/Azure metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def convert_html_to_pdf(
    html_string: str,
    output_path: Path,
    css_string: str | None = None,
) -> Path:
    """
    Convert an HTML string to a PDF file.

    Args:
        html_string: The raw HTML content to render.
        output_path: Destination path for the PDF.
        css_string: Optional raw CSS to inject (applied after HTML styles).

    Returns:
        Path to the created PDF.

    Raises:
        ConversionError: If WeasyPrint is missing, HTML is empty, or rendering fails.
    """
    if not _HAS_WEASYPRINT:
        raise ConversionError(
            "HTML to PDF conversion is not available on this server.",
            detail="WeasyPrint is not installed.",
        )

    if not html_string or not html_string.strip():
        raise ConversionError("HTML content cannot be empty.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_config = FontConfiguration()

    logger.info("HTML→PDF: Rendering %.1f KB of HTML", len(html_string) / 1024)

    try:
        # Base URL is set to prevent WeasyPrint from resolving relative paths
        # against the server's local filesystem.
        html_doc = HTML(string=html_string, base_url="http://localhost/", url_fetcher=_secure_url_fetcher)
        
        styles = []
        if css_string:
            styles.append(CSS(string=css_string, font_config=font_config))

        html_doc.write_pdf(
            str(output_path),
            stylesheets=styles,
            font_config=font_config,
        )

    except Exception as e:
        logger.error("WeasyPrint rendering failed: %s", e, exc_info=True)
        
        # Provide user-friendly messages for common CSS/layout errors
        err_str = str(e).lower()
        if "invalid" in err_str and "css" in err_str:
            raise ConversionError(
                "Failed to render HTML. The provided CSS contains invalid syntax.",
                detail=str(e),
            )
        if "network" in err_str or "url" in err_str:
            raise ConversionError(
                "Failed to render HTML. An external resource (image/CSS) could not be loaded. "
                "Ensure all URLs are public and use https://.",
                detail=str(e),
            )
            
        raise ConversionError("Failed to render HTML to PDF.", detail=str(e))

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise ConversionError("PDF generation resulted in an empty file. The HTML may have no visible content.")

    logger.info("HTML→PDF complete: %s (%.1f KB)", output_path.name, output_path.stat().st_size / 1024)
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# Security: Custom URL Fetcher
# ═══════════════════════════════════════════════════════════════════════════════

def _secure_url_fetcher(url: str) -> dict[str, Any]:
    """
    A secure drop-in replacement for WeasyPrint's default URL fetcher.
    
    WeasyPrint expects this to return a dict like:
    {
        "file_obj": io.BytesIO(b"..."),
        "mime_type": "text/css",
        "encoding": "utf-8", # optional
    }
    
    Raises ValueError on blocked requests, which WeasyPrint catches and reports
    as a broken link/image.
    """
    parsed = urlparse(url)

    # 1. Protocol check
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Blocked protocol '{parsed.scheme}'. Only HTTP/HTTPS are allowed.")

    # 2. IP Address resolution check (prevent SSRF)
    try:
        # Note: This uses synchronous resolution. WeasyPrint runs synchronously
        # anyway, so this is fine, but it adds a small latency per resource.
        import socket
        hostname = parsed.hostname
        if hostname:
            # Resolve hostname to IP
            addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            if addr_info:
                ip_str = addr_info[0][4][0]
                ip = ipaddress.ip_address(ip_str)
                
                # Check against blocked networks
                for network in _BLOCKED_NETWORKS:
                    if ip in network:
                        raise ValueError(
                            f"Blocked request to private/internal IP address {ip_str}."
                        )
    except socket.gaierror:
        raise ValueError(f"Could not resolve hostname '{parsed.hostname}'.")
    except ValueError:
        raise # Re-raise our intentional ValueError
    except Exception as e:
        logger.warning("IP check failed for %s: %s. Blocking request.", url, e)
        raise ValueError("Failed security check for requested URL.")

    # 3. Perform the actual HTTP request
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ConvertX/1.0 (Secure HTML Renderer)"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            data = response.read(_MAX_RESOURCE_SIZE_BYTES)
            
            # Check if we hit the size limit
            if len(data) == _MAX_RESOURCE_SIZE_BYTES:
                raise ValueError(f"Resource exceeded maximum size of {_MAX_RESOURCE_SIZE_BYTES // 1024}KB.")
                
    except urllib.error.HTTPError as e:
        raise ValueError(f"HTTP Error {e.code} fetching {url}")
    except Exception as e:
        raise ValueError(f"Failed to fetch external resource: {str(e)}")

    # 4. MIME type check
    if content_type not in _ALLOWED_RESOURCE_TYPES:
        raise ValueError(
            f"Blocked resource type '{content_type}'. "
            f"Only images and CSS are allowed."
        )

    # 5. Return in format WeasyPrint expects
    return {
        "file_obj": io.BytesIO(data),
        "mime_type": content_type,
    }
