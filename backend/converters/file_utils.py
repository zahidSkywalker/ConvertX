"""
Converters file_utils — re-exports from the canonical location.

This module exists for backwards compatibility. All actual logic
lives in backend/utils/file_utils.py. Routes should import from there.
"""

from backend.utils.file_utils import (  # noqa: F401
    register_output_file,
    get_file_entry,
    unregister_file,
    get_registry_size,
    save_upload_file,
    save_upload_files,
    cleanup_expired_files,
    cleanup_all_files,
    format_file_size,
    _safe_delete,
)
