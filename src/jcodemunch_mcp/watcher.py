"""Filesystem watcher — monitors folders and triggers incremental re-indexing."""

import asyncio
import hashlib
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from watchfiles import awatch, Change

from .tools.index_folder import index_folder

logger = logging.getLogger(__name__)

# Default debounce in milliseconds
DEFAULT_DEBOUNCE_MS = 2000

# Platform-specific: fcntl for Unix (advisory locking)
try:
    import fcntl
except ImportError:
    fcntl = None  # Windows

# Module-level lock file descriptors (Unix flock)
_lock_fds: dict[str, int] = {}


# ---------------------------------------------------------------------------
# Lock file helpers
# ---------------------------------------------------------------------------

def _lock_dir(storage_path: Optional[str]) -> Path:
    """Return the directory for lock files, creating it if needed."""
    if storage_path:
        d = Path(storage_path)
    else:
        d = Path.home() / ".code-index"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _folder_hash(folder_path: str) -> str:
    """Return SHA-256 hash (first 12 hex chars) of a normalized folder path."""
    resolved = str(Path(folder_path).resolve())
    if sys.platform == "win32":
        resolved = resolved.lower()
    return hashlib.sha256(resolved.encode()).hexdigest()[:12]


def _lock_path(folder_path: str, storage_path: Optional[str]) -> Path:
    """Return the lock file Path for a given folder."""
    return _lock_dir(storage_path) / f"_watcher_{_folder_hash(folder_path)}.lock"


def _is_pid_alive(pid: int) -> bool:
    """Return True if a process with the given PID is running."""
    if sys.platform == "win32":
        import ctypes

        class _BOOL(ctypes.Structure):
            _fields_ = [("value", ctypes.c_int)]

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle == 0:
            return False
        try:
            kernel32.CloseHandle(handle)
            return True
        except OSError:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def _acquire_lock(folder_path: str, storage_path: Optional[str]) -> bool:
    """
    Attempt to acquire an exclusive lock for the given folder.

    Uses O_EXCL for atomic file creation, eliminating the TOCTOU race window
    that exists when checking lock existence before writing. On Unix, also
    uses fcntl.flock() for OS-level advisory locking.

    Returns True if the lock was acquired, False if another watcher
    is already running (active PID).
    """
    lock_fp = _lock_path(folder_path, storage_path)

    data = {
        "pid": os.getpid(),
        "folder": folder_path,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    data_bytes = json.dumps(data).encode("utf-8")

    def _try_atomic_create() -> bool:
        """Attempt atomic lock file creation using O_EXCL. Returns True on success."""
        try:
            fd = os.open(str(lock_fp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                os.write(fd, data_bytes)
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            return False
        except OSError:
            return False

    # Step 1: Try atomic creation (fast path - no pre-check)
    if _try_atomic_create():
        # Success - apply OS-level flock on Unix
        if fcntl is not None:
            fd = os.open(str(lock_fp), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                # Race: another process grabbed the lock between create and flock
                # (should be rare on Unix). Clean up our file.
                try:
                    lock_fp.unlink()
                except OSError:
                    pass
                return False
            _lock_fds[folder_path] = fd
        return True

    # Step 2: Lock file exists - check if it's stale or active
    try:
        data = json.loads(lock_fp.read_text(encoding="utf-8"))
        pid = data.get("pid")
        if pid is None:
            print(f"Removing stale lock for {folder_path} (no pid key)", file=sys.stderr)
        elif _is_pid_alive(pid):
            print(f"Watcher already running for {folder_path} (PID {pid})", file=sys.stderr)
            return False
        else:
            print(f"Removing stale lock for {folder_path} (PID {pid} is dead)", file=sys.stderr)
    except (json.JSONDecodeError, OSError):
        print(f"Removing corrupted lock for {folder_path}", file=sys.stderr)

    # Step 3: Clean up stale lock and retry
    try:
        lock_fp.unlink()
    except OSError:
        # Couldn't delete (locked by another process on Windows, or race).
        # Proceed to retry anyway - O_EXCL will handle it.
        pass

    time.sleep(0.05)  # Brief pause to reduce collision window

    if _try_atomic_create():
        # Success on retry
        if fcntl is not None:
            fd = os.open(str(lock_fp), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                try:
                    lock_fp.unlink()
                except OSError:
                    pass
                return False
            _lock_fds[folder_path] = fd
        return True

    # Step 4: Still can't create - either another process won the race, or
    # the OS is holding the file locked (Windows). Give up gracefully.
    print(f"WARNING: could not acquire lock for {folder_path}", file=sys.stderr)
    return False


def _release_lock(folder_path: str, storage_path: Optional[str]) -> None:
    """Release and remove the lock for the given folder."""
    # Release flock on Unix
    if folder_path in _lock_fds:
        try:
            os.close(_lock_fds[folder_path])
        except OSError:
            pass
        del _lock_fds[folder_path]

    # Delete lock file
    try:
        _lock_path(folder_path, storage_path).unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Idle timeout watchdog
# ---------------------------------------------------------------------------

async def _idle_timeout_watchdog(
    stop_event: asyncio.Event,
    idle_minutes: int,
    get_last_reindex: Callable[[], float],
    _check_interval_seconds: float = 30.0,
) -> None:
    """Auto-shutdown if no re-indexing activity for idle_minutes."""
    while not stop_event.is_set():
        await asyncio.sleep(_check_interval_seconds)
        if stop_event.is_set():
            break
        idle_seconds = idle_minutes * 60
        if time.monotonic() - get_last_reindex() > idle_seconds:
            print(
                f"No re-indexing activity for {idle_minutes} minute(s) — shutting down.",
                file=sys.stderr,
            )
            stop_event.set()
            break


# ---------------------------------------------------------------------------
# Core watching
# ---------------------------------------------------------------------------

async def _watch_single(
    folder_path: str,
    debounce_ms: int,
    use_ai_summaries: bool,
    storage_path: Optional[str],
    extra_ignore_patterns: Optional[list[str]],
    follow_symlinks: bool,
    on_reindex: Optional[Callable[[], None]] = None,
) -> None:
    """Watch a single folder and re-index on changes."""
    print(f"Watching {folder_path} (debounce={debounce_ms}ms)", file=sys.stderr)

    # Do an initial incremental index to ensure the index is current
    print(f"  Initial index for {folder_path}...", file=sys.stderr)
    result = await asyncio.to_thread(
        index_folder,
        path=folder_path,
        use_ai_summaries=use_ai_summaries,
        storage_path=storage_path,
        extra_ignore_patterns=extra_ignore_patterns,
        follow_symlinks=follow_symlinks,
        incremental=True,
    )
    if result.get("success"):
        msg = result.get("message", f"{result.get('symbol_count', '?')} symbols")
        print(f"  Indexed {folder_path}: {msg} ({result.get('duration_seconds', '?')}s)", file=sys.stderr)
        # Count initial index as activity (only if it actually did work)
        if on_reindex is not None and result.get("message") != "No changes detected":
            on_reindex()
    else:
        print(f"  WARNING: initial index failed for {folder_path}: {result.get('error')}", file=sys.stderr)

    async for changes in awatch(
        folder_path,
        debounce=debounce_ms,
        recursive=True,
        step=200,
    ):
        relevant = [
            (change_type, path)
            for change_type, path in changes
            if change_type in (Change.added, Change.modified, Change.deleted)
            and not any(
                part.startswith(".")
                for part in Path(path).relative_to(folder_path).parts
            )
        ]

        if not relevant:
            continue

        n_added = sum(1 for c, _ in relevant if c == Change.added)
        n_modified = sum(1 for c, _ in relevant if c == Change.modified)
        n_deleted = sum(1 for c, _ in relevant if c == Change.deleted)

        print(
            f"  Changes detected in {folder_path}: "
            f"+{n_added} ~{n_modified} -{n_deleted}",
            file=sys.stderr,
        )

        try:
            result = await asyncio.to_thread(
                index_folder,
                path=folder_path,
                use_ai_summaries=use_ai_summaries,
                storage_path=storage_path,
                extra_ignore_patterns=extra_ignore_patterns,
                follow_symlinks=follow_symlinks,
                incremental=True,
            )
            if result.get("success"):
                duration = result.get("duration_seconds", "?")
                if result.get("message") == "No changes detected":
                    print(f"  Re-indexed {folder_path}: no indexable changes ({duration}s)", file=sys.stderr)
                else:
                    changed = result.get("changed", 0)
                    new = result.get("new", 0)
                    deleted = result.get("deleted", 0)
                    print(
                        f"  Re-indexed {folder_path}: "
                        f"changed={changed} new={new} deleted={deleted} ({duration}s)",
                        file=sys.stderr,
                    )
                    # Report re-index activity (only if it actually did work)
                    if on_reindex is not None:
                        on_reindex()
            else:
                print(
                    f"  WARNING: re-index failed for {folder_path}: {result.get('error')}",
                    file=sys.stderr,
                )
        except Exception as e:
            logger.exception("Re-index error for %s: %s", folder_path, e)
            print(f"  ERROR: re-index failed for {folder_path}: {e}", file=sys.stderr)


async def watch_folders(
    paths: list[str],
    debounce_ms: int = DEFAULT_DEBOUNCE_MS,
    use_ai_summaries: bool = True,
    storage_path: Optional[str] = None,
    extra_ignore_patterns: Optional[list[str]] = None,
    follow_symlinks: bool = False,
    idle_timeout_minutes: Optional[int] = None,
) -> None:
    """Watch multiple folders concurrently."""
    resolved = []
    for p in paths:
        folder = Path(p).expanduser().resolve()
        if not folder.is_dir():
            print(f"WARNING: skipping {p} — not a directory", file=sys.stderr)
            continue
        resolved.append(str(folder))

    if not resolved:
        print("ERROR: no valid directories to watch", file=sys.stderr)
        sys.exit(1)

    # --- Acquire locks ---
    locked_folders: list[str] = []
    for folder in resolved[:]:  # iterate over a copy so we can modify resolved
        if _acquire_lock(folder, storage_path):
            locked_folders.append(folder)
        else:
            resolved.remove(folder)

    if not resolved:
        print("All folders already have active watchers.", file=sys.stderr)
        return

    print(f"jcodemunch-mcp watcher: monitoring {len(resolved)} folder(s)", file=sys.stderr)

    # Handle graceful shutdown
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    if sys.platform == "win32":
        # Windows: signal handlers run synchronously outside the event loop.
        # Using call_soon_threadsafe ensures stop_event.set() is scheduled
        # safely on the event loop thread rather than called directly.
        def _handle_signal(sig, frame):
            loop.call_soon_threadsafe(stop_event.set)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

    # Idle timeout tracking
    last_reindex_time = time.monotonic()

    def update_reindex_time() -> None:
        nonlocal last_reindex_time
        last_reindex_time = time.monotonic()

    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(
            _watch_single(
                folder_path=folder,
                debounce_ms=debounce_ms,
                use_ai_summaries=use_ai_summaries,
                storage_path=storage_path,
                extra_ignore_patterns=extra_ignore_patterns,
                follow_symlinks=follow_symlinks,
                on_reindex=update_reindex_time,
            ),
            name=f"watch:{folder}",
        )
        for folder in resolved
    ]

    # Optionally add idle timeout watchdog
    if idle_timeout_minutes is not None and idle_timeout_minutes > 0:
        watchdog_task = asyncio.create_task(
            _idle_timeout_watchdog(
                stop_event=stop_event,
                idle_minutes=idle_timeout_minutes,
                get_last_reindex=lambda: last_reindex_time,
            ),
            name="idle-watchdog",
        )
        tasks.append(watchdog_task)

    # Wait until stop signal or a task crashes
    done_waiter = asyncio.ensure_future(
        asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    )
    stop_waiter = asyncio.ensure_future(stop_event.wait())

    await asyncio.wait(
        [done_waiter, stop_waiter],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Clean up
    print("\nShutting down watchers...", file=sys.stderr)
    for t in tasks:
        t.cancel()
    done_waiter.cancel()
    stop_waiter.cancel()
    # Gather all tasks including the waiter tasks to ensure they're fully cleaned up
    # before returning. This prevents Python 3.14+ "coroutine never awaited" warnings.
    await asyncio.gather(
        *tasks, done_waiter, stop_waiter, return_exceptions=True
    )

    # Release locks
    for folder in locked_folders:
        _release_lock(folder, storage_path)

    print("Done.", file=sys.stderr)
