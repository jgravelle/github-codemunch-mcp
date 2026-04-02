"""get_extraction_candidates — identify functions worth extracting to a shared module.

A function is a good extraction candidate when it:
  - Has high cyclomatic complexity (doing a lot), AND
  - Is called from multiple other files (already implicitly shared).

Requires complexity data stored at index time (INDEX_VERSION >= 7).
For symbols indexed before v1.16, complexity will be 0 and those symbols
are excluded automatically (use ``min_complexity=1`` to include them).
"""

from __future__ import annotations

import time
from typing import Optional

from ..storage import IndexStore
from ..parser.imports import resolve_specifier
from ._utils import resolve_repo as _resolve_repo
from ._call_graph import _word_match


def get_extraction_candidates(
    repo: str,
    file_path: str,
    min_complexity: int = 5,
    min_callers: int = 2,
    storage_path: Optional[str] = None,
) -> dict:
    """Find functions in *file_path* that are good candidates for extraction.

    A candidate must satisfy BOTH criteria:
      - ``cyclomatic >= min_complexity``
      - Called from at least ``min_callers`` distinct files

    Results are ranked by ``cyclomatic * caller_file_count`` descending.

    Args:
        repo:           Repo identifier.
        file_path:      File to analyse (relative repo path, e.g. ``src/utils.py``).
        min_complexity: Minimum cyclomatic complexity. Default 5.
        min_callers:    Minimum number of distinct caller files. Default 2.
        storage_path:   Optional index storage path override.

    Returns:
        ``{candidates, file, min_complexity, min_callers, timing_ms}``
        Each entry: ``{id, name, kind, line, cyclomatic, max_nesting,
                       param_count, caller_count, caller_files, score}``
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

    if not index.has_source_file(file_path):
        # Try a suffix match in case caller passed just the filename
        matches = [f for f in index.source_files if f.endswith(file_path) or f.endswith(file_path.replace("\\", "/"))]
        if len(matches) == 1:
            file_path = matches[0]
        elif len(matches) > 1:
            return {
                "error": f"Ambiguous file path {file_path!r}. Be more specific.",
                "candidates_paths": matches[:10],
            }
        else:
            return {"error": f"File {file_path!r} not found in index."}

    # Gather functions/methods in the target file with sufficient complexity
    target_syms = [
        s for s in index.symbols
        if s.get("file") == file_path
        and s.get("kind") in ("function", "method")
        and (s.get("cyclomatic") or 0) >= min_complexity
    ]

    if not target_syms:
        return {
            "repo": f"{owner}/{name}",
            "file": file_path,
            "candidates": [],
            "min_complexity": min_complexity,
            "min_callers": min_callers,
            "note": (
                "No functions with cyclomatic >= {} found. "
                "If this file was indexed before v1.16, complexity data is not available — "
                "re-index the repo to populate complexity metrics.".format(min_complexity)
            ),
            "_meta": {"timing_ms": round((time.monotonic() - t0) * 1000, 1)},
        }

    # Build reverse adjacency: file → [files that import it]
    source_files_fs = frozenset(index.source_files)
    alias_map = getattr(index, "alias_map", {}) or {}
    rev: dict[str, list[str]] = {}
    if index.imports:
        for src_file, file_imports in index.imports.items():
            for imp in file_imports:
                target = resolve_specifier(imp["specifier"], src_file, source_files_fs, alias_map)
                if target and target != src_file:
                    rev.setdefault(target, []).append(src_file)

    importer_files = list(dict.fromkeys(rev.get(file_path, [])))

    # For each candidate symbol, count how many distinct importer files call it
    candidates: list[dict] = []
    for sym in target_syms:
        sym_name = sym.get("name", "")
        caller_files: list[str] = []
        for imp_file in importer_files:
            content = store.get_file_content(owner, name, imp_file)
            if content and _word_match(content, sym_name):
                caller_files.append(imp_file)

        if len(caller_files) >= min_callers:
            cyclomatic = sym.get("cyclomatic") or 0
            candidates.append({
                "id": sym["id"],
                "name": sym_name,
                "kind": sym.get("kind", ""),
                "line": sym.get("line", 0),
                "cyclomatic": cyclomatic,
                "max_nesting": sym.get("max_nesting") or 0,
                "param_count": sym.get("param_count") or 0,
                "caller_count": len(caller_files),
                "caller_files": caller_files,
                "score": cyclomatic * len(caller_files),
            })

    candidates.sort(key=lambda x: -x["score"])

    timing_ms = round((time.monotonic() - t0) * 1000, 1)
    return {
        "repo": f"{owner}/{name}",
        "file": file_path,
        "candidates": candidates,
        "min_complexity": min_complexity,
        "min_callers": min_callers,
        "_meta": {"timing_ms": timing_ms},
    }
