"""Filesystem watcher — monitors folders and triggers incremental re-indexing."""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from watchfiles import awatch, Change

from .tools.index_folder import index_folder

logger = logging.getLogger(__name__)

# Default debounce in milliseconds
DEFAULT_DEBOUNCE_MS = 2000


async def _watch_single(
    folder_path: str,
    debounce_ms: int,
    use_ai_summaries: bool,
    storage_path: Optional[str],
    extra_ignore_patterns: Optional[list[str]],
    follow_symlinks: bool,
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

    print(f"jcodemunch-mcp watcher: monitoring {len(resolved)} folder(s)", file=sys.stderr)

    # Handle graceful shutdown
    stop_event = asyncio.Event()
    if sys.platform == "win32":
        signal.signal(signal.SIGINT, lambda s, f: stop_event.set())
        signal.signal(signal.SIGTERM, lambda s, f: stop_event.set())
    else:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

    tasks = [
        asyncio.create_task(
            _watch_single(
                folder_path=folder,
                debounce_ms=debounce_ms,
                use_ai_summaries=use_ai_summaries,
                storage_path=storage_path,
                extra_ignore_patterns=extra_ignore_patterns,
                follow_symlinks=follow_symlinks,
            ),
            name=f"watch:{folder}",
        )
        for folder in resolved
    ]

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
    await asyncio.gather(*tasks, return_exceptions=True)
    print("Done.", file=sys.stderr)
