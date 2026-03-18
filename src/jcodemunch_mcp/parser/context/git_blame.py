"""Git blame context provider — attaches last_author and last_modified to files."""

import logging
import subprocess
from pathlib import Path
from typing import Optional

from .base import ContextProvider, FileContext, register_provider

logger = logging.getLogger(__name__)


@register_provider
class GitBlameProvider(ContextProvider):
    """Context provider that reads per-file last-commit metadata from git.

    Detected automatically when a ``.git`` directory is present in the indexed
    folder.  Runs a single ``git log`` command during ``load()`` to build a
    {relative_path: (author, iso_date)} map; subsequent ``get_file_context``
    calls are O(1) dict lookups.

    Adds to each file's ``FileContext.properties``:
      - ``last_author``: display name of the most recent committer
      - ``last_modified``: ISO-8601 date of the most recent commit
    """

    def __init__(self) -> None:
        self._blame: dict[str, tuple[str, str]] = {}  # path -> (author, date)
        self._folder: Optional[Path] = None

    @property
    def name(self) -> str:
        return "git_blame"

    def detect(self, folder_path: Path) -> bool:
        """Return True if the folder is inside a git repository."""
        return (folder_path / ".git").exists() or self._find_git_root(folder_path) is not None

    def _find_git_root(self, folder_path: Path) -> Optional[Path]:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(folder_path),
                capture_output=True,
                text=True,
                timeout=5,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                return Path(result.stdout.strip())
        except Exception:
            pass
        return None

    def load(self, folder_path: Path) -> None:
        """Run one ``git log`` to populate the blame map for all tracked files."""
        self._folder = folder_path
        try:
            result = subprocess.run(
                [
                    "git", "log",
                    "--name-only",
                    "--format=COMMIT %an|%aI",
                    "--diff-filter=AM",
                    "--no-merges",
                    "--",
                ],
                cwd=str(folder_path),
                capture_output=True,
                text=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
            )
        except Exception as exc:
            logger.warning("GitBlameProvider: git log failed: %s", exc)
            return

        current_author = ""
        current_date = ""
        for line in result.stdout.splitlines():
            line = line.rstrip()
            if line.startswith("COMMIT "):
                rest = line[7:]
                parts = rest.split("|", 1)
                current_author = parts[0].strip()
                current_date = parts[1][:10] if len(parts) > 1 else ""
            elif line and current_author:
                # Only record the first (most recent) entry per file
                if line not in self._blame:
                    self._blame[line] = (current_author, current_date)

        logger.debug("GitBlameProvider: loaded blame for %d files", len(self._blame))

    def get_file_context(self, file_path: str) -> Optional[FileContext]:
        if not self._blame:
            return None
        # Try exact path, then basename fallback
        entry = self._blame.get(file_path) or self._blame.get(Path(file_path).name)
        if not entry:
            return None
        author, date = entry
        return FileContext(properties={"last_author": author, "last_modified": date})

    def stats(self) -> dict:
        return {"files_with_blame": len(self._blame)}

    def get_metadata(self) -> dict:
        """Expose blame data in index for structured access."""
        return {"git_blame": {path: {"author": a, "date": d} for path, (a, d) in self._blame.items()}}
