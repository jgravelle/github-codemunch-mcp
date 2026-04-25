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
from ..parser.context._route_utils import ENTRY_POINT_DECORATOR_RE


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


def _filename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _is_entry_point(file_path: str) -> bool:
    return _filename(file_path) in _ENTRY_POINT_FILENAMES


def _is_barrel(file_path: str) -> bool:
    return _filename(file_path) in _BARREL_FILENAMES


def _build_reverse_adjacency(imports: dict, source_files: frozenset, alias_map: dict, psr4_map: Optional[dict] = None) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for src_file, file_imports in imports.items():
        for imp in file_imports:
            target = resolve_specifier(imp["specifier"], src_file, source_files, alias_map, psr4_map)
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
    psr4_map = getattr(index, "psr4_map", None)
    rev = _build_reverse_adjacency(index.imports, source_files, alias_map, psr4_map)

    # Pre-compute reachable files from entry points (Signal 1 input)
    entry_point_count = sum(1 for f in index.source_files if _is_entry_point(f))
    reachable_files = _reachable_from_entry_points(list(index.source_files), rev)

    # Pre-compute barrel exports (Signal 3 input)
    barrel_names = _barrel_exports(index, store, owner, name)

    # Pre-compute call graph: for each symbol, who calls it? (Signal 2 input)
    # Use AST call_references when available (O(N)), fall back to text heuristic.
    get_callers = getattr(index, "get_callers_by_name", None)
    callers_by_name = get_callers() if get_callers else None
    callee_has_caller: set[str] = set()
    if callers_by_name:
        # Fast path: use pre-computed AST call_references index
        # Any symbol whose name appears as a value in callers_by_name has at least one caller
        called_names_by_file: dict[str, set[str]] = {}
        for (caller_file, called_name) in callers_by_name:
            called_names_by_file.setdefault(caller_file, set()).add(called_name)
        for sym in index.symbols:
            if sym.get("kind") not in ("function", "method"):
                continue
            sym_file = sym.get("file", "")
            sym_name = sym.get("name", "")
            if not sym_name or not sym_file:
                continue
            # Check if any importing file has a symbol that calls this name
            for importer_file in rev.get(sym_file, []):
                if sym_name in called_names_by_file.get(importer_file, set()):
                    callee_has_caller.add(sym["id"])
                    break
    else:
        # Fallback: text heuristic with file content caching
        symbols_by_file = build_symbols_by_file(index)
        _file_cache: dict[str, str] = {}
        for sym in index.symbols:
            if sym.get("kind") not in ("function", "method"):
                continue
            sym_file = sym.get("file", "")
            sym_name = sym.get("name", "")
            if not sym_name or not sym_file:
                continue
            for importer_file in rev.get(sym_file, []):
                if importer_file not in _file_cache:
                    _file_cache[importer_file] = store.get_file_content(owner, name, importer_file) or ""
                content = _file_cache[importer_file]
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
        if any(ENTRY_POINT_DECORATOR_RE.search(str(d)) for d in (sym.get("decorators") or [])):
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
    result: dict = {
        "repo": f"{owner}/{name}",
        "dead_symbols": dead_symbols,
        "total_analysed": sum(
            1 for s in index.symbols
            if s.get("kind") in ("function", "method")
        ),
        "min_confidence": min_confidence,
        "_meta": {
            "timing_ms": timing_ms,
            "methodology": "multi_signal",
            "confidence_level": "medium",
        },
    }
    if entry_point_count == 0:
        result["framework_warning"] = (
            "No standard entry points detected (e.g. main.py, app.py, __main__.py). "
            "Signal 1 (unreachable_file) fires for every symbol, inflating dead code counts. "
            "Pass entry_point_patterns to identify framework-specific roots "
            "(e.g. handler functions for AWS Lambda, route modules for FastAPI)."
        )
    return result


def _is_test_file(file_path: str) -> bool:
    fp = file_path.replace("\\", "/")
    fn = fp.rsplit("/", 1)[-1]
    return (
        "/tests/" in fp or "/test/" in fp
        or fn.startswith("test_") or fn.endswith("_test.py")
        or fn == "conftest.py"
    )
