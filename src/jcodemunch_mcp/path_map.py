"""Cross-platform path prefix remapping via JCODEMUNCH_PATH_MAP."""

import logging
import os

logger = logging.getLogger(__name__)

ENV_VAR = "JCODEMUNCH_PATH_MAP"


def parse_path_map() -> list[tuple[str, str]]:
    """Parse JCODEMUNCH_PATH_MAP into (original, replacement) pairs.

    Format: orig1=new1,orig2=new2,...
    Splits on the last '=' so paths containing '=' work correctly.
    Returns [] when the env var is unset or empty.
    Malformed entries (no '=', empty orig, empty new) are skipped with a WARNING.
    """
    raw = os.environ.get(ENV_VAR, "").strip()
    if not raw:
        return []

    pairs: list[tuple[str, str]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            logger.warning("JCODEMUNCH_PATH_MAP: skipping malformed entry (no '='): %r", entry)
            continue
        orig, new = entry.rsplit("=", 1)
        orig = orig.strip()
        new = new.strip()
        if not orig:
            logger.warning("JCODEMUNCH_PATH_MAP: skipping entry with empty original prefix: %r", entry)
            continue
        if not new:
            logger.warning("JCODEMUNCH_PATH_MAP: skipping entry with empty replacement prefix: %r", entry)
            continue
        pairs.append((orig, new))
    return pairs


def remap(path: str, pairs: list[tuple[str, str]], reverse: bool = False) -> str:
    """Apply path prefix substitution with OS separator normalisation.

    Forward (reverse=False): replaces original → replacement.
                             Use when reading stored paths for display.
    Reverse (reverse=True):  replaces replacement → original.
                             Use before hashing a user-supplied path to look
                             up an index that was built on a different machine.

    Tries pairs in order; applies the first match.
    On match, outputs using os.sep.  On no-match, returns path unchanged.
    """
    # Normalise input separators to '/' for comparison
    path_norm = path.replace("\\", "/")

    for orig, new in pairs:
        if reverse:
            src = new.replace("\\", "/")
            dst = orig.replace("\\", "/")
        else:
            src = orig.replace("\\", "/")
            dst = new.replace("\\", "/")

        # Ensure prefix comparison works at directory boundaries
        src_prefix = src.rstrip("/")
        if path_norm == src_prefix or path_norm.startswith(src_prefix + "/"):
            remainder = path_norm[len(src_prefix):]
            remapped = dst.rstrip("/") + remainder
            # Output using OS native separator
            return remapped.replace("/", os.sep)

    # No match — return path unchanged
    return path
