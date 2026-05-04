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

import json
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
    "index.mjs", "index.cjs",
    "mod.rs",
})

# CJS re-export: `module.exports = require('./X')` / `exports.foo = require('./X')`
_CJS_REEXPORT_RE = re.compile(
    r"""(?:module\.)?exports?(?:\.\w+)?\s*=\s*require\(\s*['"]([^'"]+)['"]\s*\)"""
)
# ES re-export-all: `export * from './X'` / `export * as ns from './X'`
_ESM_REEXPORT_STAR_RE = re.compile(
    r"""export\s+\*(?:\s+as\s+\w+)?\s+from\s+['"]([^'"]+)['"]"""
)
# ES named re-export: `export { foo, bar } from './X'`
_ESM_REEXPORT_NAMED_RE = re.compile(
    r"""export\s*\{[^}]+\}\s*from\s+['"]([^'"]+)['"]"""
)


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


def _build_forward_adjacency(imports: dict, source_files: frozenset, alias_map: dict, psr4_map: Optional[dict] = None) -> dict[str, list[str]]:
    """Forward adjacency: ``forward[src_file] = [imported targets]``.

    Required so reachability BFS from entry points actually traverses the
    dependency graph (the pre-1.80.7 reverse-only walk only found importers
    of the entry, not files imported by it — which is why every library
    file was treated as unreachable).
    """
    fwd: dict[str, list[str]] = {}
    for src_file, file_imports in imports.items():
        for imp in file_imports:
            target = resolve_specifier(imp["specifier"], src_file, source_files, alias_map, psr4_map)
            if target and target != src_file and target in source_files:
                fwd.setdefault(src_file, []).append(target)
    return {k: list(dict.fromkeys(v)) for k, v in fwd.items()}


def _reachable_from_entry_points(
    source_files: list[str],
    rev: dict[str, list[str]],
    forward: dict[str, list[str]],
    extra_entries: Optional[set[str]] = None,
) -> set[str]:
    """Files reachable from entry points via the import graph.

    Walks both directions to maximise the live set:
      * **Forward**: from each entry, visit everything it imports
        (the standard "what does the entry depend on?" semantic). Pre-1.80.7
        only walked reverse, so library files imported by the entry were
        wrongly treated as unreachable.
      * **Reverse**: also pull in any file that imports the entry (e.g. a
        test that imports ``app.py``). Preserves prior behavior.

    ``extra_entries`` supplements the filename heuristic (e.g. files
    declared by ``package.json`` ``main``).
    """
    live: set[str] = set()
    queue: deque[str] = deque()
    for f in source_files:
        if _is_entry_point(f) or (extra_entries and f in extra_entries):
            live.add(f)
            queue.append(f)
    for f in (extra_entries or ()):
        if f not in live:
            live.add(f)
            queue.append(f)
    while queue:
        node = queue.popleft()
        for imported in forward.get(node, []):
            if imported not in live:
                live.add(imported)
                queue.append(imported)
        for importer in rev.get(node, []):
            if importer not in live:
                live.add(importer)
                queue.append(importer)
    return live


def _barrel_exports(
    index,
    store,
    owner,
    repo_name,
    source_files: frozenset,
    alias_map: dict,
    psr4_map: Optional[dict] = None,
) -> set[str]:
    """Return symbol names exported from any barrel / __init__ file.

    Recursively follows CommonJS ``module.exports = require('./X')`` and ES
    module ``export * from './X'`` / ``export {…} from './X'`` patterns so
    that names defined in ``./X`` count as barrel-exported. Without this,
    libraries that re-export through an index file (Express, Lodash, etc.)
    falsely appear dead. Bounded depth prevents pathological re-export
    chains from blowing up the scan. (Issue: sverklo bench v1 — Express
    `createApplication` flagged as dead due to `module.exports = require(
    './lib/express')`.)
    """
    exported: set[str] = set()
    visited: set[str] = set()
    MAX_DEPTH = 4

    def _collect(file_path: str, depth: int) -> None:
        if file_path in visited or depth > MAX_DEPTH:
            return
        visited.add(file_path)
        content = store.get_file_content(owner, repo_name, file_path)
        if not content:
            return
        # Identifiers literally present in this file (original behavior).
        exported.update(re.findall(r"\b([A-Za-z_]\w*)\b", content))
        # Recursively expand re-export targets.
        targets: set[str] = set()
        for m in _CJS_REEXPORT_RE.finditer(content):
            targets.add(m.group(1))
        for m in _ESM_REEXPORT_STAR_RE.finditer(content):
            targets.add(m.group(1))
        for m in _ESM_REEXPORT_NAMED_RE.finditer(content):
            targets.add(m.group(1))
        for spec in targets:
            resolved = resolve_specifier(spec, file_path, source_files,
                                         alias_map, psr4_map)
            if resolved and resolved in source_files:
                _collect(resolved, depth + 1)

    for f in index.source_files:
        if _is_barrel(f):
            _collect(f, 0)
    return exported


def _package_json_entries(index, store, owner, repo_name) -> set[str]:
    """Return source files referenced by any ``package.json``'s ``main`` /
    ``module`` / ``exports`` / ``bin`` field.

    For JavaScript/TypeScript libraries there is no ``app.py``-equivalent
    filename heuristic that identifies the consumer-facing entry point;
    the canonical answer is whatever the package manifest declares as
    ``main``. Without this, every library file looks unreachable and
    Signal 1 fires for every symbol. (Issue: sverklo bench v1.)
    """
    entries: set[str] = set()
    source_files = frozenset(index.source_files)
    for f in index.source_files:
        if _filename(f) != "package.json":
            continue
        content = store.get_file_content(owner, repo_name, f)
        if not content:
            continue
        try:
            pkg = json.loads(content)
        except (ValueError, TypeError):
            continue
        if not isinstance(pkg, dict):
            continue
        candidates: list[str] = []
        for key in ("main", "module", "browser"):
            v = pkg.get(key)
            if isinstance(v, str):
                candidates.append(v)
        # `exports` can be a string, a dict of subpaths, or a conditional dict.
        exports = pkg.get("exports")
        if isinstance(exports, str):
            candidates.append(exports)
        elif isinstance(exports, dict):
            def _walk_exports(node):
                if isinstance(node, str):
                    candidates.append(node)
                elif isinstance(node, dict):
                    for v in node.values():
                        _walk_exports(v)
            _walk_exports(exports)
        # `bin` can be a string or a {name: path} dict.
        bins = pkg.get("bin")
        if isinstance(bins, str):
            candidates.append(bins)
        elif isinstance(bins, dict):
            candidates.extend(v for v in bins.values() if isinstance(v, str))

        pkg_dir = f.replace("\\", "/").rsplit("/", 1)[0] if "/" in f else ""
        for cand in candidates:
            cand = cand.lstrip("./").replace("\\", "/")
            joined = f"{pkg_dir}/{cand}" if pkg_dir else cand
            joined = joined.lstrip("/")
            # Try the literal path; then try resolve_specifier semantics
            # (handles bare specifiers and extension-less imports).
            if joined in source_files:
                entries.add(joined)
                continue
            # Try common JS/TS extensions if missing.
            for ext in ("", ".js", ".ts", ".mjs", ".cjs", ".jsx", ".tsx",
                        "/index.js", "/index.ts", "/index.mjs", "/index.cjs"):
                trial = joined + ext
                if trial in source_files:
                    entries.add(trial)
                    break
    return entries


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

def get_dead_code_v2(
    repo: str,
    min_confidence: float = 0.5,
    include_tests: bool = False,
    max_results: int = 100,
    file_pattern: Optional[str] = None,
    storage_path: Optional[str] = None,
) -> dict:
    """Find likely-dead functions and methods using three independent signals.

    Args:
        repo:           Repo identifier.
        min_confidence: Minimum confidence threshold (0.0–1.0).
                        Default 0.5 means at least 2 of 3 signals must fire.
        include_tests:  When False (default), test files are treated as
                        reachable and skipped.
        max_results:    Cap on returned symbols (default 100). Pre-1.80.7
                        the response was unbounded; on large libraries this
                        could exceed 8k tokens per call. ``_meta.truncated``
                        + ``_meta.total_matches`` flag when capped. Use 0
                        for unlimited.
        file_pattern:   Optional glob (e.g. ``"src/**"``, ``"*.py"``) — only
                        analyse symbols whose file matches. Smaller scope
                        means smaller, faster, more actionable results.
        storage_path:   Optional index storage path override.

    Returns:
        ``{dead_symbols, total_analysed, min_confidence, timing_ms}``
        Each entry in ``dead_symbols``:
        ``{id, name, kind, file, line, confidence, signals}``
    """
    import fnmatch
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
        # 1.80.9+: when there's no import graph (single-file libs like
        # pre-bundled lodash 4.x, monolithic IIFEs, etc.), fall through
        # to call-graph-only mode rather than erroring out. Reports
        # symbols whose names appear nowhere in any indexed function's
        # call_references.
        return _call_graph_only_dead_code(
            index, owner, name, t0,
            include_tests=include_tests,
            max_results=max_results,
            file_pattern=file_pattern,
        )

    source_files = frozenset(index.source_files)
    alias_map = getattr(index, "alias_map", {}) or {}
    psr4_map = getattr(index, "psr4_map", None)
    rev = _build_reverse_adjacency(index.imports, source_files, alias_map, psr4_map)
    forward = _build_forward_adjacency(index.imports, source_files, alias_map, psr4_map)

    # Pre-compute reachable files from entry points (Signal 1 input).
    # Two heuristics: (a) classic filename match (app.py, main.py, etc.);
    # (b) any file declared as `main`/`module`/`exports`/`bin` in a
    # ``package.json`` (issue: sverklo bench v1 — Express has no
    # filename-style entry point).
    pkg_entries = _package_json_entries(index, store, owner, name)
    entry_point_count = sum(1 for f in index.source_files if _is_entry_point(f)) + len(pkg_entries)
    reachable_files = _reachable_from_entry_points(
        list(index.source_files), rev, forward, extra_entries=pkg_entries
    )

    # Pre-compute barrel exports (Signal 3 input). Recursively follows CJS
    # ``module.exports = require(...)`` / ESM ``export * from`` so that
    # symbols re-exported through index.js are not flagged as dead.
    barrel_names = _barrel_exports(
        index, store, owner, name, source_files, alias_map, psr4_map
    )

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
            # Check the symbol's own file (intra-file calls) and any importing
            # file. Same-file callers were missed pre-1.80.10, which produced
            # false positives in nested-root TS monorepos where a function is
            # defined and called within the same module.
            search_files = (sym_file, *rev.get(sym_file, ()))
            for caller_file in search_files:
                if sym_name in called_names_by_file.get(caller_file, set()):
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
            # Check the symbol's own file (intra-file calls) and any importing
            # file. The text heuristic must avoid matching the symbol's own
            # definition line — otherwise every function trivially "calls"
            # itself. Match the whole file body excluding the symbol's own
            # line range.
            sym_line = sym.get("line", 0)
            sym_end_line = sym.get("end_line", sym_line)
            if sym_file not in _file_cache:
                _file_cache[sym_file] = store.get_file_content(owner, name, sym_file) or ""
            own_content = _file_cache[sym_file]
            if own_content and sym_line:
                lines = own_content.splitlines()
                start_idx = max(0, sym_line - 1)
                end_idx = min(len(lines), sym_end_line)
                outside = "\n".join(lines[:start_idx] + lines[end_idx:])
                if outside and _word_match(outside, sym_name):
                    callee_has_caller.add(sym["id"])
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

        # Skip entry-point files entirely (filename heuristic + package.json
        # main fields).
        if _is_entry_point(sym_file) or sym_file in pkg_entries:
            continue

        # Skip test files unless requested
        if not include_tests and _is_test_file(sym_file):
            continue

        # Optional file-pattern scope filter.
        if file_pattern and not fnmatch.fnmatch(sym_file, file_pattern):
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

    total_matches = len(dead_symbols)
    truncated = False
    if max_results and max_results > 0 and total_matches > max_results:
        dead_symbols = dead_symbols[:max_results]
        truncated = True

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
            "total_matches": total_matches,
            "truncated": truncated,
        },
    }
    if file_pattern:
        result["_meta"]["file_pattern"] = file_pattern
    if pkg_entries:
        result["_meta"]["package_json_entries"] = sorted(pkg_entries)
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


def _call_graph_only_dead_code(
    index,
    owner: str,
    name: str,
    t0: float,
    include_tests: bool = False,
    max_results: int = 100,
    file_pattern: Optional[str] = None,
) -> dict:
    """Fallback dead-code detection when ``index.imports`` is empty.

    Single-file libraries (pre-bundled lodash 4.x, monolithic IIFEs,
    minified-then-indexed bundles) have no inter-file imports — the
    main 3-signal analyzer can't run. This mode falls back to the
    call-graph signal: a function whose name appears nowhere in any
    indexed function's ``call_references`` is a dead candidate.

    The result is intentionally lower-confidence than the 3-signal
    output; ``_meta.mode = "call_graph_only"`` flags this so callers
    can interpret. Each returned symbol has a single signal
    (``no_callers``); ``confidence`` is fixed at 0.5 to reflect the
    weaker evidence (cf. 3-signal where each signal is worth 1/3).
    """
    import fnmatch

    get_callers = getattr(index, "get_callers_by_name", None)
    if not get_callers:
        return {
            "repo": f"{owner}/{name}",
            "dead_symbols": [],
            "total_analysed": 0,
            "_meta": {
                "mode": "unavailable",
                "warning": (
                    "No import data and no call-references index. "
                    "Re-index with jcodemunch-mcp >= 1.78.0 (INDEX_VERSION 8) "
                    "to enable AST call-reference indexing."
                ),
                "timing_ms": round((time.monotonic() - t0) * 1000, 1),
            },
        }

    callers_by_name = get_callers() or {}
    # Names that have at least one caller in the indexed call graph.
    called_names: set[str] = {ref for (_caller_file, ref) in callers_by_name.keys()}

    dead_symbols: list[dict] = []
    seen: set[str] = set()
    total_analysed = 0

    for sym in index.symbols:
        if sym.get("kind") not in ("function", "method"):
            continue
        sid = sym.get("id", "")
        if not sid or sid in seen:
            continue
        sym_file = sym.get("file", "")
        sym_name = sym.get("name", "")
        if not sym_name or not sym_file:
            continue
        if not include_tests and _is_test_file(sym_file):
            continue
        if file_pattern and not fnmatch.fnmatch(sym_file, file_pattern):
            continue
        # Skip entry-point decorated symbols (Flask routes, click commands etc.)
        if any(ENTRY_POINT_DECORATOR_RE.search(str(d))
               for d in (sym.get("decorators") or [])):
            continue
        total_analysed += 1
        if sym_name in called_names:
            continue
        seen.add(sid)
        dead_symbols.append({
            "id": sid,
            "name": sym_name,
            "kind": sym.get("kind", ""),
            "file": sym_file,
            "line": sym.get("line", 0),
            "confidence": 0.5,
            "signals": ["no_callers"],
        })

    dead_symbols.sort(key=lambda x: (x["file"], x["line"]))

    total_matches = len(dead_symbols)
    truncated = False
    if max_results and max_results > 0 and total_matches > max_results:
        dead_symbols = dead_symbols[:max_results]
        truncated = True

    return {
        "repo": f"{owner}/{name}",
        "dead_symbols": dead_symbols,
        "total_analysed": total_analysed,
        "_meta": {
            "mode": "call_graph_only",
            "warning": (
                "Import graph is empty (single-file project, monolithic "
                "bundle, or pre-tree-shaken library). Falling back to "
                "call-graph-only analysis: a function with no callers "
                "elsewhere in the indexed call graph is treated as a dead "
                "candidate. Confidence is fixed at 0.5 to reflect the "
                "single-signal nature; expect more false positives than "
                "the standard 3-signal mode."
            ),
            "timing_ms": round((time.monotonic() - t0) * 1000, 1),
            "total_matches": total_matches,
            "truncated": truncated,
        },
    }
