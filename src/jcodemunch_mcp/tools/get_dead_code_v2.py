"""get_dead_code_v2 — multi-signal dead code detection with confidence scores.

Three independent evidence signals per symbol:
  1. Import graph: no file imports the symbol's defining file.
  2. Call graph: no indexed symbol calls this symbol.
  3. Barrel export: the symbol is not re-exported from an ``__init__`` or
     barrel/index file that is itself reachable.

Confidence = number of signals present / 3.
Only symbols with kind ``function`` or ``method`` are analysed (classes and
constants are excluded to reduce noise).
"""

from __future__ import annotations

import re
import time
from collections import deque
from typing import Optional

from ..storage import IndexStore
from ..parser.imports import resolve_specifier
from ._utils import resolve_repo as _resolve_repo
from ._call_graph import _word_match, build_symbols_by_file


# ---------------------------------------------------------------------------
# Helpers shared with find_dead_code
# ---------------------------------------------------------------------------

_ENTRY_POINT_FILENAMES = frozenset({
    "__main__.py", "conftest.py", "manage.py", "wsgi.py", "asgi.py",
    "setup.py", "app.py", "main.py", "run.py", "cli.py", "celery.py",
    "Makefile",
})

_BARREL_FILENAMES = frozenset({
    "__init__.py", "index.ts", "index.js", "index.tsx", "index.jsx",
    "mod.rs",
})

_ENTRY_POINT_DECORATOR_RE = re.compile(
    r"@(?:app|router|blueprint|api|bp|flask_app)\."
    r"(?:route|get|post|put|delete|patch|head|options|websocket|before_request|after_request)"
    r"|@pytest\.fixture"
    r"|@(?:cli|app)\.command"
    r"|@(?:celery|huey|dramatiq|rq)\."
    r"|@task\b|@event_handler\b|@on_event\b",
    re.IGNORECASE,
)


def _filename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _is_entry_point(file_path: str) -> bool:
    return _filename(file_path) in _ENTRY_POINT_FILENAMES


def _is_barrel(file_path: str) -> bool:
    return _filename(file_path) in _BARREL_FILENAMES


def _build_reverse_adjacency(imports: dict, source_files: frozenset, alias_map: dict) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for src_file, file_imports in imports.items():
        for imp in file_imports:
            target = resolve_specifier(imp["specifier"], src_file, source_files, alias_map)
            if target and target != src_file:
                rev.setdefault(target, []).append(src_file)
    return {k: list(dict.fromkeys(v)) for k, v in rev.items()}


def _reachable_from_entry_points(
    source_files: list[str],
    rev: dict[str, list[str]],
) -> set[str]:
    """BFS from entry-point files; return the set of all reachable files."""
    live: set[str] = set()
    queue: deque[str] = deque()
    for f in source_files:
        if _is_entry_point(f):
            live.add(f)
            queue.append(f)
    while queue:
        node = queue.popleft()
        for importer in rev.get(node, []):
            if importer not in live:
                live.add(importer)
                queue.append(importer)
    return live


def _barrel_exports(index, store, owner, repo_name) -> set[str]:
    """Return symbol names exported from any barrel / __init__ file."""
    exported: set[str] = set()
    for f in index.source_files:
        if not _is_barrel(f):
            continue
        content = store.get_file_content(owner, repo_name, f)
        if not content:
            continue
        # Collect all word tokens that look like identifiers (simple heuristic)
        exported.update(re.findall(r"\b([A-Za-z_]\w*)\b", content))
    return exported


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

def get_dead_code_v2(
    repo: str,
    min_confidence: float = 0.5,
    include_tests: bool = False,
    storage_path: Optional[str] = None,
) -> dict:
    """Find likely-dead functions and methods using three independent signals.

    Args:
        repo:           Repo identifier.
        min_confidence: Minimum confidence threshold (0.0–1.0).
                        Default 0.5 means at least 2 of 3 signals must fire.
        include_tests:  When False (default), test files are treated as
                        reachable and skipped.
        storage_path:   Optional index storage path override.

    Returns:
        ``{dead_symbols, total_analysed, min_confidence, timing_ms}``
        Each entry in ``dead_symbols``:
        ``{id, name, kind, file, line, confidence, signals}``
    """
    t0 = time.monotonic()
    try:
        owner, name = _resolve_repo(repo, storage_path)
    except ValueError as e:
        return {"error": str(e)}
    store = IndexStore(base_path=storage_path)
    index = store.load_index(owner, name)

    if index is None:
        return {"error": f"No index found for {repo!r}. Run index_folder first."}
    if not index.imports:
        return {"error": "No import data in index. Re-index with a recent version."}

    source_files = frozenset(index.source_files)
    alias_map = getattr(index, "alias_map", {}) or {}
    rev = _build_reverse_adjacency(index.imports, source_files, alias_map)

    # Pre-compute reachable files from entry points (Signal 1 input)
    reachable_files = _reachable_from_entry_points(list(index.source_files), rev)

    # Pre-compute barrel exports (Signal 3 input)
    barrel_names = _barrel_exports(index, store, owner, name)

    # Pre-compute call graph: for each symbol, who calls it? (Signal 2 input)
    # Build a map: sym_id → set of caller sym_ids (1-hop only for speed)
    symbols_by_file = build_symbols_by_file(index)
    callee_has_caller: set[str] = set()
    for sym in index.symbols:
        if sym.get("kind") not in ("function", "method"):
            continue
        sym_file = sym.get("file", "")
        sym_name = sym.get("name", "")
        if not sym_name or not sym_file:
            continue
        for importer_file in rev.get(sym_file, []):
            content = store.get_file_content(owner, name, importer_file)
            if content and _word_match(content, sym_name):
                callee_has_caller.add(sym["id"])
                break

    dead_symbols: list[dict] = []
    seen_ids: set[str] = set()

    for sym in index.symbols:
        sid = sym.get("id", "")
        if not sid or sid in seen_ids:
            continue
        if sym.get("kind") not in ("function", "method"):
            continue

        sym_file = sym.get("file", "")
        sym_name = sym.get("name", "")

        # Skip entry-point files entirely
        if _is_entry_point(sym_file):
            continue

        # Skip test files unless requested
        if not include_tests and _is_test_file(sym_file):
            continue

        # Skip symbols with entry-point decorators
        if any(_ENTRY_POINT_DECORATOR_RE.search(str(d)) for d in (sym.get("decorators") or [])):
            continue

        signals: list[str] = []

        # Signal 1: File is not reachable from any entry point
        if sym_file not in reachable_files:
            signals.append("unreachable_file")

        # Signal 2: No callers in the call graph
        if sid not in callee_has_caller:
            signals.append("no_callers")

        # Signal 3: Not mentioned in any barrel/init export
        if sym_name not in barrel_names:
            signals.append("not_barrel_exported")

        confidence = len(signals) / 3.0
        if confidence >= min_confidence:
            seen_ids.add(sid)
            dead_symbols.append({
                "id": sid,
                "name": sym_name,
                "kind": sym.get("kind", ""),
                "file": sym_file,
                "line": sym.get("line", 0),
                "confidence": round(confidence, 2),
                "signals": signals,
            })

    dead_symbols.sort(key=lambda x: (-x["confidence"], x["file"], x["line"]))

    timing_ms = round((time.monotonic() - t0) * 1000, 1)
    return {
        "repo": f"{owner}/{name}",
        "dead_symbols": dead_symbols,
        "total_analysed": sum(
            1 for s in index.symbols
            if s.get("kind") in ("function", "method")
        ),
        "min_confidence": min_confidence,
        "_meta": {"timing_ms": timing_ms},
    }


def _is_test_file(file_path: str) -> bool:
    fp = file_path.replace("\\", "/")
    fn = fp.rsplit("/", 1)[-1]
    return (
        "/tests/" in fp or "/test/" in fp
        or fn.startswith("test_") or fn.endswith("_test.py")
        or fn == "conftest.py"
    )
