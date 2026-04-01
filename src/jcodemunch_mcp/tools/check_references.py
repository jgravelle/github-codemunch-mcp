"""Check if an identifier is referenced anywhere: imports + file content.

Combines find_references and search_text into one call.
Answers "is this identifier used anywhere?" for quick dead-code detection.
"""

import posixpath
import time
from typing import Optional

from ..storage import IndexStore
from ._utils import resolve_repo


def _check_single(
    identifier: str,
    index,
    search_content: bool,
    max_content_results: int,
    owner: str,
    name: str,
    store: "IndexStore",
    start: float,
) -> dict:
    """Core logic for checking a single identifier against import + content data."""
    ident_lower = identifier.lower()

    # ── Import-level check ──────────────────────────────────────────────────
    import_references = []
    if index.imports is not None:
        for src_file, file_imports in index.imports.items():
            matches = []
            for imp in file_imports:
                named_match = any(n.lower() == ident_lower for n in imp.get("names", []))
                spec = imp["specifier"]
                spec_stem = posixpath.splitext(posixpath.basename(spec))[0].lower()
                stem_match = spec_stem == ident_lower

                if named_match or stem_match:
                    matches.append({
                        "specifier": spec,
                        "names": imp.get("names", []),
                        "match_type": "named" if named_match else "specifier_stem",
                    })

            if matches:
                import_references.append({"file": src_file, "matches": matches})

    import_count = len(import_references)

    # ── Content-level check ─────────────────────────────────────────────────
    # Find files where this identifier is *defined* (via symbol index)
    # so we can skip them — finding the name in the defining file is not a "reference".
    defining_files: set[str] = set()
    for sym in index.symbols:
        if sym.get("name", "").lower() == ident_lower:
            file_path = sym.get("file", "")
            if file_path:
                defining_files.add(file_path)

    content_references = []

    if search_content:
        content_dir = store._content_dir(owner, name)
        for file_path in index.source_files:
            if file_path in defining_files:
                continue

            full_path = store._safe_content_path(content_dir, file_path)
            if not full_path or not full_path.exists():
                continue

            try:
                with open(full_path, "r", encoding="utf-8", errors="replace", newline="") as f:
                    content = f.read()
            except OSError:
                continue

            file_matches = []
            for line_index, line in enumerate(content.split("\n")):
                if ident_lower in line.lower():
                    file_matches.append({
                        "line": line_index + 1,
                        "text": line.rstrip()[:200],
                    })

            if file_matches:
                content_references.append({"file": file_path, "matches": file_matches})
                # Stop after N files, not N lines
                if len(content_references) >= max_content_results:
                    break

    content_count = len(content_references)

    elapsed = (time.perf_counter() - start) * 1000
    is_referenced = import_count > 0 or content_count > 0

    result = {
        "repo": f"{owner}/{name}",
        "identifier": identifier,
        "is_referenced": is_referenced,
        "import_count": import_count,
        "import_references": import_references,
        "content_count": content_count,
        "_meta": {"timing_ms": round(elapsed, 1)},
    }

    if search_content:
        result["content_references"] = content_references

    return result


def _check_batch(
    identifiers: list[str],
    index,
    search_content: bool,
    max_content_results: int,
    owner: str,
    name: str,
    store: "IndexStore",
    start: float,
) -> dict:
    """Batch logic: loop over identifiers, return grouped results array."""
    results = []
    for identifier in identifiers:
        result = _check_single(
            identifier=identifier,
            index=index,
            search_content=search_content,
            max_content_results=max_content_results,
            owner=owner,
            name=name,
            store=store,
            start=start,
        )
        # Strip envelope fields for consistency with other batch tools
        result.pop("repo", None)
        result.pop("_meta", None)
        results.append(result)

    elapsed = (time.perf_counter() - start) * 1000
    return {
        "repo": f"{owner}/{name}",
        "results": results,
        "_meta": {
            "timing_ms": round(elapsed, 1),
            "identifiers_checked": len(identifiers),
        },
    }


def check_references(
    repo: str,
    identifier: Optional[str] = None,
    identifiers: Optional[list[str]] = None,
    search_content: bool = True,
    max_content_results: int = 20,
    storage_path: Optional[str] = None,
) -> dict:
    """Check if an identifier is referenced anywhere: imports + file content.

    Combines find_references and search_text into one call. Answers
    "is this identifier used anywhere?" for quick dead-code detection.

    Supports two modes:
    - Singular: pass ``identifier`` to get the original flat response shape.
    - Batch: pass ``identifiers`` (list) to query multiple identifiers at once,
      returning a grouped ``results`` array.

    Args:
        repo: Repository identifier (owner/repo or display name).
        identifier: The symbol/module name to check (singular mode).
        identifiers: List of symbol/module names to check (batch mode).
        search_content: Also search file contents (not just imports).
            Set False for fast import-only check.
        max_content_results: Max files to return per identifier for content search.
        storage_path: Custom storage path.

    Returns:
        Singular mode: dict with is_referenced, import/content counts, and
            reference lists.
        Batch mode: dict with ``results`` array (one entry per identifier).
    """
    # Normalize: some MCP clients send identifiers=[] alongside identifier when they mean singular mode
    if identifier is not None and identifiers is not None and len(identifiers) == 0:
        identifiers = None
    if (identifier is None and identifiers is None) or (identifier is not None and identifiers is not None):
        raise ValueError("Provide exactly one of 'identifier' or 'identifiers', not both and not neither.")

    start = time.perf_counter()
    max_content_results = max(1, min(max_content_results, 100))

    try:
        owner, name = resolve_repo(repo, storage_path)
    except ValueError as e:
        return {"error": str(e)}

    store = IndexStore(base_path=storage_path)
    index = store.load_index(owner, name)
    if not index:
        return {"error": f"Repository not indexed: {owner}/{name}"}

    if identifiers is not None:
        return _check_batch(
            identifiers,
            index,
            search_content,
            max_content_results,
            owner,
            name,
            store,
            start,
        )
    else:
        return _check_single(
            identifier=identifier,  # type: ignore[arg-type]  # validated above
            index=index,
            search_content=search_content,
            max_content_results=max_content_results,
            owner=owner,
            name=name,
            store=store,
            start=start,
        )
