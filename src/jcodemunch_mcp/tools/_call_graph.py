"""Shared AST-derived call-graph computation.

Strategy
--------
call_references (v8+): Store call sites in the index. When available,
use _callers_by_name (caller lookup) and sym.call_references (callee lookup)
for precise AST-derived call graphs.

Fallback (v7 and earlier): No call-site data is stored in the index. Callers
and callees are derived at query time using text heuristics:

Callers (who calls symbol X?):
  1. Find files that import X's defining file (import graph, same as blast radius).
  2. Within each importer, check which indexed symbols' source bodies mention
     X's name as a word token.

Callees (what does symbol X call?):
  1. Extract X's source body (by line range from file content).
  2. Find files that X's file imports (import graph).
  3. Within each imported file, check which indexed symbols' names appear in
     X's body.

Fallback heuristics are approximate (no type resolution, no dynamic dispatch
awareness), consistent with the rest of jCodemunch's AST-level analysis.
"""

from __future__ import annotations

import re
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..storage import IndexStore
    from ..storage.index_store import CodeIndex


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _word_match(content: str, name: str) -> bool:
    """Return True if *name* appears as a word token in *content*."""
    return bool(re.search(r"\b" + re.escape(name) + r"\b", content))


def _symbol_body(file_lines: list[str], sym: dict) -> str:
    """Slice *file_lines* to the lines covered by *sym* (1-indexed)."""
    line = sym.get("line", 0)
    end_line = sym.get("end_line", line)
    if not line:
        return ""
    start_idx = max(0, line - 1)
    end_idx = min(len(file_lines), end_line)
    return "\n".join(file_lines[start_idx:end_idx])


def build_symbols_by_file(index: "CodeIndex") -> dict[str, list[dict]]:
    """Build ``{file_path: [symbol_dicts]}`` from *index.symbols*."""
    result: dict[str, list[dict]] = {}
    for sym in index.symbols:
        f = sym.get("file")
        if f:
            result.setdefault(f, []).append(sym)
    return result


# ---------------------------------------------------------------------------
# Direct caller / callee finders
# ---------------------------------------------------------------------------

def _callers_from_references(
    index: "CodeIndex",
    sym: dict,
    reverse_adj: dict[str, list[str]],
) -> list[dict]:
    """Return callers using stored call_references data (AST-based).

    Uses the _callers_by_name reverse index (lazy-built on first access).
    Keyed by (caller_file, called_name) to avoid bare-name collisions between
    different files (e.g. auth.py::process vs data.py::process).
    Only returns callers from files that import sym's file (via reverse_adj).
    """
    get_callers = getattr(index, "get_callers_by_name", None)
    callers_by_name = get_callers() if get_callers else None
    if not callers_by_name:
        return []

    sym_name: str = sym.get("name", "")
    sym_file: str = sym.get("file", "")
    if not sym_name or not sym_file:
        return []

    # Files that import sym's file + sym's own file (for same-file callers)
    importing_files = set(reverse_adj.get(sym_file, []))
    search_files = importing_files | {sym_file}

    # Look up by (file, sym_name) for each candidate file
    sym_id = sym.get("id", "")
    results: list[dict] = []

    for candidate_file in search_files:
        for cid in callers_by_name.get((candidate_file, sym_name), []):
            if cid == sym_id:
                continue  # Skip self-reference
            caller = index._symbol_index.get(cid)
            if caller:
                caller_file = caller.get("file", "")
                if caller_file and caller_file in search_files:
                    results.append({
                        "id": cid,
                        "name": caller.get("name", ""),
                        "kind": caller.get("kind", ""),
                        "file": caller_file,
                        "line": caller.get("line", 0),
                    })
    return results


def _callees_from_references(
    index: "CodeIndex",
    sym: dict,
    symbols_by_file: dict[str, list[dict]],
) -> list[dict]:
    """Return callees using stored call_references data (AST-based).

    Resolves the names in sym.call_references to actual symbol dicts.
    Uses a name→symbols index for O(1) lookup instead of O(N) scan.
    """
    call_refs = sym.get("call_references", [])
    if not call_refs:
        return []

    # Build name → list[(name, file_path)] index for O(1) cross-file lookup
    name_index: dict[str, list[tuple[str, str]]] = {}
    for file_path, syms in symbols_by_file.items():
        for s in syms:
            name = s.get("name", "")
            if name:
                name_index.setdefault(name, []).append((name, file_path))

    sym_name = sym.get("name", "")
    sym_file = sym.get("file", "")
    seen_ids: set[str] = set()
    results: list[dict] = []

    for called_name in call_refs:
        # Skip self-recursion
        if called_name == sym_name:
            continue
        # Look up in the same file first (local calls)
        if sym_file:
            for name, file_path in name_index.get(called_name, []):
                if file_path == sym_file:
                    cand = symbols_by_file[sym_file]
                    for s in cand:
                        if s.get("name") == called_name:
                            cid = s.get("id", "")
                            if cid and cid not in seen_ids:
                                seen_ids.add(cid)
                                results.append({
                                    "id": cid,
                                    "name": called_name,
                                    "kind": s.get("kind", ""),
                                    "file": sym_file,
                                    "line": s.get("line", 0),
                                })
                    break
        # Also look in other files (imported calls)
        for name, file_path in name_index.get(called_name, []):
            if file_path != sym_file:
                for s in symbols_by_file.get(file_path, []):
                    if s.get("name") == called_name:
                        cid = s.get("id", "")
                        if cid and cid not in seen_ids:
                            seen_ids.add(cid)
                            results.append({
                                "id": cid,
                                "name": called_name,
                                "kind": s.get("kind", ""),
                                "file": file_path,
                                "line": s.get("line", 0),
                            })
                        break

    return results


def find_direct_callers(
    index: "CodeIndex",
    store: "IndexStore",
    owner: str,
    repo_name: str,
    sym: dict,
    reverse_adj: dict[str, list[str]],
    symbols_by_file: dict[str, list[dict]],
) -> list[dict]:
    """Return symbols in importing files whose bodies mention *sym*'s name.

    Each result is ``{id, name, kind, file, line}``.
    """
    # Try AST-derived call_references first (when available and non-empty)
    get_callers = getattr(index, "get_callers_by_name", None)
    callers_by_name = get_callers() if get_callers else None
    ast_caller_ids: set[str] = set()
    ast_callers: list[dict] = []
    if callers_by_name:
        ast_callers = _callers_from_references(index, sym, reverse_adj)
        if ast_callers:
            for c in ast_callers:
                ast_caller_ids.add(c["id"])

    # Always use text heuristic as fallback (handles partial AST data)
    sym_name: str = sym.get("name", "")
    sym_file: str = sym.get("file", "")
    if not sym_name or not sym_file:
        return [{"id": c["id"], "name": c["name"], "kind": c["kind"],
                 "file": c["file"], "line": c["line"]} for c in ast_callers] if ast_caller_ids else []

    callers: list[dict] = []
    seen_ids: set[str] = set(ast_caller_ids)

    for imp_file in reverse_adj.get(sym_file, []):
        file_content = store.get_file_content(owner, repo_name, imp_file)
        if not file_content:
            continue
        # Fast gate: skip file if sym_name not present anywhere
        if not _word_match(file_content, sym_name):
            continue

        file_lines = file_content.splitlines()
        for candidate in symbols_by_file.get(imp_file, []):
            cid = candidate.get("id", "")
            if not cid or cid in seen_ids or not candidate.get("line"):
                continue
            body = _symbol_body(file_lines, candidate)
            if body and _word_match(body, sym_name):
                seen_ids.add(cid)
                callers.append({
                    "id": cid,
                    "name": candidate.get("name", ""),
                    "kind": candidate.get("kind", ""),
                    "file": imp_file,
                    "line": candidate.get("line", 0),
                })

    return ast_callers + callers


def find_direct_callees(
    index: "CodeIndex",
    store: "IndexStore",
    owner: str,
    repo_name: str,
    sym: dict,
    symbols_by_file: dict[str, list[dict]],
) -> list[dict]:
    """Return symbols from imported files whose names appear in *sym*'s body.

    Each result is ``{id, name, kind, file, line}``.
    """
    # Fast path: use AST-derived call_references if available
    call_refs = sym.get("call_references", [])
    if call_refs:
        return _callees_from_references(index, sym, symbols_by_file)

    # Fallback: text heuristic
    from ..parser.imports import resolve_specifier

    sym_file: str = sym.get("file", "")
    if not sym_file:
        return []

    file_content = store.get_file_content(owner, repo_name, sym_file)
    if not file_content:
        return []

    file_lines = file_content.splitlines()
    sym_body = _symbol_body(file_lines, sym)
    if not sym_body:
        return []

    # Resolve files that sym's file imports
    file_imports = (index.imports or {}).get(sym_file, [])
    source_files_fs = frozenset(index.source_files)
    alias_map = getattr(index, "alias_map", {}) or {}
    psr4_map = getattr(index, "psr4_map", None)

    imported_files: set[str] = set()
    for imp in file_imports:
        target = resolve_specifier(imp["specifier"], sym_file, source_files_fs, alias_map, psr4_map)
        if target and target != sym_file:
            imported_files.add(target)

    callees: list[dict] = []
    seen_ids: set[str] = set()

    for imported_file in imported_files:
        for candidate in symbols_by_file.get(imported_file, []):
            cid = candidate.get("id", "")
            cname = candidate.get("name", "")
            if not cid or not cname or cid in seen_ids:
                continue
            if _word_match(sym_body, cname):
                seen_ids.add(cid)
                callees.append({
                    "id": cid,
                    "name": cname,
                    "kind": candidate.get("kind", ""),
                    "file": imported_file,
                    "line": candidate.get("line", 0),
                })

    return callees


# ---------------------------------------------------------------------------
# BFS traversals
# ---------------------------------------------------------------------------

def bfs_callers(
    index: "CodeIndex",
    store: "IndexStore",
    owner: str,
    repo_name: str,
    sym: dict,
    reverse_adj: dict[str, list[str]],
    symbols_by_file: dict[str, list[dict]],
    max_depth: int,
) -> tuple[list[dict], int]:
    """BFS over callers up to *max_depth* hops.

    Returns ``(results, depth_reached)`` where each result has a ``depth`` field.
    """
    sym_id = sym.get("id", "")
    visited: set[str] = {sym_id}
    queue: deque[tuple[dict, int]] = deque()
    results: list[dict] = []
    depth_reached = 0
    symbol_index: dict[str, dict] = getattr(index, "_symbol_index", {})

    # Depth-1 callers
    for c in find_direct_callers(index, store, owner, repo_name, sym, reverse_adj, symbols_by_file):
        if c["id"] not in visited:
            visited.add(c["id"])
            results.append({**c, "depth": 1})
            depth_reached = 1
            if max_depth > 1:
                queue.append((c, 1))

    while queue:
        curr_dict, curr_depth = queue.popleft()
        if curr_depth >= max_depth:
            continue
        curr_full = symbol_index.get(curr_dict["id"])
        if not curr_full:
            continue
        for c in find_direct_callers(index, store, owner, repo_name, curr_full, reverse_adj, symbols_by_file):
            if c["id"] not in visited:
                visited.add(c["id"])
                new_depth = curr_depth + 1
                results.append({**c, "depth": new_depth})
                depth_reached = max(depth_reached, new_depth)
                if new_depth < max_depth:
                    queue.append((c, new_depth))

    return results, depth_reached


def bfs_callees(
    index: "CodeIndex",
    store: "IndexStore",
    owner: str,
    repo_name: str,
    sym: dict,
    symbols_by_file: dict[str, list[dict]],
    max_depth: int,
) -> tuple[list[dict], int]:
    """BFS over callees up to *max_depth* hops.

    Returns ``(results, depth_reached)`` where each result has a ``depth`` field.
    """
    sym_id = sym.get("id", "")
    visited: set[str] = {sym_id}
    queue: deque[tuple[dict, int]] = deque()
    results: list[dict] = []
    depth_reached = 0
    symbol_index: dict[str, dict] = getattr(index, "_symbol_index", {})

    for c in find_direct_callees(index, store, owner, repo_name, sym, symbols_by_file):
        if c["id"] not in visited:
            visited.add(c["id"])
            results.append({**c, "depth": 1})
            depth_reached = 1
            if max_depth > 1:
                queue.append((c, 1))

    while queue:
        curr_dict, curr_depth = queue.popleft()
        if curr_depth >= max_depth:
            continue
        curr_full = symbol_index.get(curr_dict["id"])
        if not curr_full:
            continue
        for c in find_direct_callees(index, store, owner, repo_name, curr_full, symbols_by_file):
            if c["id"] not in visited:
                visited.add(c["id"])
                new_depth = curr_depth + 1
                results.append({**c, "depth": new_depth})
                depth_reached = max(depth_reached, new_depth)
                if new_depth < max_depth:
                    queue.append((c, new_depth))

    return results, depth_reached
