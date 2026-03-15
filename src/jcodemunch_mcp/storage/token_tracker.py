"""Persistent token savings tracker.

Records cumulative tokens saved across all tool calls by comparing
raw file sizes against actual MCP response sizes.

Stored in ~/.code-index/_savings.json — a single small JSON file.
No API calls, no file reads — only os.stat for file sizes.

Community meter: token savings are shared anonymously by default to the
global counter at https://j.gravelle.us. Only {"delta": N, "anon_id":
"<uuid>"} is sent — never code, paths, repo names, or anything identifying.
Set JCODEMUNCH_SHARE_SAVINGS=0 to disable.
"""

import json
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Optional

_SAVINGS_FILE = "_savings.json"
_BYTES_PER_TOKEN = 4  # ~4 bytes per token (rough but consistent)
_TELEMETRY_URL = "https://j.gravelle.us/APIs/savings/post.php"

# In-process lock — protects against concurrent async tasks within one server
_lock = threading.Lock()

# Input token pricing ($ per token). Update as models reprice.
PRICING = {
    "claude_opus":  15.00 / 1_000_000,  # Claude Opus 4.6 — $15.00 / 1M input tokens
    "gpt5_latest":  10.00 / 1_000_000,  # GPT-5.2 (latest flagship GPT) — $10.00 / 1M input tokens
}


def _savings_path(base_path: Optional[str] = None) -> Path:
    root = Path(base_path) if base_path else Path.home() / ".code-index"
    root.mkdir(parents=True, exist_ok=True)
    return root / _SAVINGS_FILE


def _lock_file(f):
    """Acquire an exclusive lock on an open file. Cross-platform."""
    if sys.platform == "win32":
        import msvcrt
        # Ensure file has content and position is at byte 0 for msvcrt
        f.write("L")
        f.flush()
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_EX)


def _unlock_file(f):
    """Release the exclusive lock on an open file. Cross-platform."""
    if sys.platform == "win32":
        import msvcrt
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_UN)


def _get_or_create_anon_id(data: dict) -> str:
    """Return the persistent anonymous install ID, creating it if absent."""
    if "anon_id" not in data:
        data["anon_id"] = str(uuid.uuid4())
    return data["anon_id"]


def _share_savings(delta: int, anon_id: str) -> None:
    """Fire-and-forget POST to the community meter. Never raises."""
    def _post() -> None:
        try:
            import httpx
            httpx.post(
                _TELEMETRY_URL,
                json={"delta": delta, "anon_id": anon_id},
                timeout=3.0,
            )
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()


def _read_locked(path: Path) -> dict:
    """Read and parse the savings JSON, returning {} on any failure."""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically via temp file + rename (prevents corruption)."""
    try:
        content = json.dumps(data)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        closed = False
        try:
            os.write(fd, content.encode())
            os.close(fd)
            closed = True
            os.replace(tmp, str(path))
        except Exception:
            if not closed:
                os.close(fd)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        pass


def record_savings(tokens_saved: int, base_path: Optional[str] = None) -> int:
    """Add tokens_saved to the running total. Returns new cumulative total.

    Uses a cross-process file lock + in-process threading lock to prevent
    concurrent read-modify-write races that silently drop accumulated savings.
    """
    delta = max(0, tokens_saved)
    if delta == 0:
        return get_total_saved(base_path)

    path = _savings_path(base_path)
    lock_path = path.with_suffix(".lock")

    with _lock:  # in-process safety
        try:
            # Cross-process lock via a dedicated lock file
            with open(lock_path, "a+") as lf:
                _lock_file(lf)
                try:
                    data = _read_locked(path)
                    total = data.get("total_tokens_saved", 0) + delta
                    data["total_tokens_saved"] = total

                    if os.environ.get("JCODEMUNCH_SHARE_SAVINGS", "1") != "0":
                        anon_id = _get_or_create_anon_id(data)
                        _share_savings(delta, anon_id)

                    _atomic_write(path, data)
                finally:
                    _unlock_file(lf)
        except Exception:
            # Last resort: unlocked write (better than losing data silently)
            try:
                data = _read_locked(path)
                total = data.get("total_tokens_saved", 0) + delta
                data["total_tokens_saved"] = total
                _atomic_write(path, data)
            except Exception:
                total = delta

    return total


def get_total_saved(base_path: Optional[str] = None) -> int:
    """Return the current cumulative total without modifying it."""
    path = _savings_path(base_path)
    try:
        return json.loads(path.read_text()).get("total_tokens_saved", 0)
    except Exception:
        return 0


def estimate_savings(raw_bytes: int, response_bytes: int) -> int:
    """Estimate tokens saved: (raw - response) / bytes_per_token."""
    return max(0, (raw_bytes - response_bytes) // _BYTES_PER_TOKEN)


def cost_avoided(tokens_saved: int, total_tokens_saved: int) -> dict:
    """Return cost avoided estimates for this call and the running total.

    Returns a dict ready to be merged into a _meta envelope:
        cost_avoided:       {claude_opus: float, gpt5_latest: float}
        total_cost_avoided: {claude_opus: float, gpt5_latest: float}

    Values are in USD, rounded to 4 decimal places.
    """
    return {
        "cost_avoided": {
            model: round(tokens_saved * rate, 4)
            for model, rate in PRICING.items()
        },
        "total_cost_avoided": {
            model: round(total_tokens_saved * rate, 4)
            for model, rate in PRICING.items()
        },
    }
