"""mermaid_viewer — spawn mmd-viewer for render_diagram output.

Provides:
  resolve_viewer_path()  — configured path or $PATH lookup
  open_diagram()         — write .mmd file + spawn viewer
  cleanup_temp_dir()     — purge only jcodemunch-owned temp files

Files are prefixed with `jcm-` so cleanup is selective and safe.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from .. import config as config_module

logger = logging.getLogger(__name__)

# Track whether the viewer was ever invoked this session.
_viewer_used = False

# Filename prefix — makes cleanup selective and safe.
_FILE_PREFIX = "jcm-"


def _temp_dir(storage_path: Path | None = None) -> Path:
    base = Path(storage_path) if storage_path else config_module._global_storage_path()
    return base / "temp" / "mermaid"


def resolve_viewer_path() -> str | None:
    """Return the mmd-viewer executable path, or None if not found."""
    configured = config_module.get("mermaid_viewer_path", "")
    if configured:
        return configured if Path(configured).exists() else None
    return shutil.which("mmd-viewer")


def open_diagram(mermaid: str, storage_path: Path | None = None) -> dict:
    """Write mermaid to a timestamped .mmd file and spawn mmd-viewer on it.

    Returns {opened: bool, path: str, error?: str}. Non-fatal on failure.
    Sets _viewer_used=True when a file is written (attempt was made).
    """
    global _viewer_used
    viewer = resolve_viewer_path()
    if not viewer:
        return {"opened": False, "error": "viewer_not_found"}
    d = _temp_dir(storage_path)
    d.mkdir(parents=True, exist_ok=True)
    fname = f"{_FILE_PREFIX}diagram-{os.getpid()}-{time.time_ns()}.mmd"
    p = d / fname
    p.write_text(mermaid, encoding="utf-8")
    _viewer_used = True
    try:
        with open(p, "rb") as f:
            subprocess.Popen(
                [viewer],
                stdin=f,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=(os.name != "nt"),
            )
    except Exception as e:
        return {"opened": False, "path": str(p), "error": f"spawn_failed: {e}"}
    return {"opened": True, "path": str(p)}


def was_viewer_used() -> bool:
    """Return True if open_diagram was called at least once this session."""
    return _viewer_used


def cleanup_temp_dir(storage_path: Path | None = None) -> int:
    """Remove only jcodemunch-owned files (jcm- prefix) from temp/mermaid/.

    Returns count of removed files. Safe to call even if viewer was never used.
    On Windows, retries with a short delay to handle file locks from viewer processes.
    """
    d = _temp_dir(storage_path)
    if not d.exists():
        return 0
    removed = 0
    for entry in d.iterdir():
        if entry.is_file() and entry.name.startswith(_FILE_PREFIX):
            try:
                entry.unlink()
                removed += 1
            except OSError:
                # Windows: viewer process may still hold the file. Retry once.
                time.sleep(0.5)
                try:
                    entry.unlink()
                    removed += 1
                except OSError:
                    logger.debug("Failed to remove mermaid temp file %s", entry, exc_info=True)
    return removed
