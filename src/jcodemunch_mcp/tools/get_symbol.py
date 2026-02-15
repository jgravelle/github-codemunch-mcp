"""Get symbol source code."""

import hashlib
import time
from typing import Optional

from ..storage import IndexStore


def _make_meta(timing_ms: float, **kwargs) -> dict:
    """Build a _meta envelope dict."""
    meta = {"timing_ms": round(timing_ms, 1)}
    meta.update(kwargs)
    return meta


def _parse_repo(repo: str, storage_path: Optional[str] = None) -> tuple:
    """Parse repo identifier and return (owner, name) or (None, error_dict)."""
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return owner, name
    store = IndexStore(base_path=storage_path)
    repos = store.list_repos()
    matching = [r for r in repos if r["repo"].endswith(f"/{repo}")]
    if not matching:
        return None, {"error": f"Repository not found: {repo}"}
    owner, name = matching[0]["repo"].split("/", 1)
    return owner, name


def get_symbol(
    repo: str,
    symbol_id: str,
    verify: bool = False,
    context_lines: int = 0,
    storage_path: Optional[str] = None
) -> dict:
    """Get full source of a specific symbol.

    Args:
        repo: Repository identifier (owner/repo or just repo name).
        symbol_id: Symbol ID from get_file_outline or search_symbols.
        verify: If True, re-read source and verify content hash matches.
        context_lines: Number of lines before/after the symbol to include.
        storage_path: Custom storage path.

    Returns:
        Dict with symbol details, source code, and _meta envelope.
    """
    start = time.perf_counter()

    result = _parse_repo(repo, storage_path)
    if result[0] is None:
        return result[1]
    owner, name = result

    store = IndexStore(base_path=storage_path)
    index = store.load_index(owner, name)

    if not index:
        return {"error": f"Repository not indexed: {owner}/{name}"}

    symbol = index.get_symbol(symbol_id)

    if not symbol:
        return {"error": f"Symbol not found: {symbol_id}"}

    # Get source via byte-offset read
    source = store.get_symbol_content(owner, name, symbol_id)

    # Add context lines if requested
    context_before = ""
    context_after = ""
    if context_lines > 0 and source:
        file_path = store._content_dir(owner, name) / symbol["file"]
        if file_path.exists():
            try:
                all_lines = file_path.read_text(encoding="utf-8", errors="replace").split("\n")
                start_line = symbol["line"] - 1  # 0-indexed
                end_line = symbol["end_line"]     # exclusive
                before_start = max(0, start_line - context_lines)
                after_end = min(len(all_lines), end_line + context_lines)
                if before_start < start_line:
                    context_before = "\n".join(all_lines[before_start:start_line])
                if end_line < after_end:
                    context_after = "\n".join(all_lines[end_line:after_end])
            except Exception:
                pass

    meta = {}
    if verify and source:
        actual_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        stored_hash = symbol.get("content_hash", "")
        meta["content_verified"] = actual_hash == stored_hash if stored_hash else None

    elapsed = (time.perf_counter() - start) * 1000

    result = {
        "id": symbol["id"],
        "kind": symbol["kind"],
        "name": symbol["name"],
        "file": symbol["file"],
        "line": symbol["line"],
        "end_line": symbol["end_line"],
        "signature": symbol["signature"],
        "decorators": symbol.get("decorators", []),
        "docstring": symbol.get("docstring", ""),
        "content_hash": symbol.get("content_hash", ""),
        "source": source or "",
        "_meta": _make_meta(elapsed, **meta),
    }

    if context_before:
        result["context_before"] = context_before
    if context_after:
        result["context_after"] = context_after

    return result


def get_symbols(
    repo: str,
    symbol_ids: list[str],
    storage_path: Optional[str] = None
) -> dict:
    """Get full source of multiple symbols.

    Args:
        repo: Repository identifier (owner/repo or just repo name).
        symbol_ids: List of symbol IDs.
        storage_path: Custom storage path.

    Returns:
        Dict with symbols list, errors, and _meta envelope.
    """
    start = time.perf_counter()

    result = _parse_repo(repo, storage_path)
    if result[0] is None:
        return result[1]
    owner, name = result

    store = IndexStore(base_path=storage_path)
    index = store.load_index(owner, name)

    if not index:
        return {"error": f"Repository not indexed: {owner}/{name}"}

    symbols = []
    errors = []

    for symbol_id in symbol_ids:
        symbol = index.get_symbol(symbol_id)

        if not symbol:
            errors.append({"id": symbol_id, "error": f"Symbol not found: {symbol_id}"})
            continue

        source = store.get_symbol_content(owner, name, symbol_id)

        symbols.append({
            "id": symbol["id"],
            "kind": symbol["kind"],
            "name": symbol["name"],
            "file": symbol["file"],
            "line": symbol["line"],
            "end_line": symbol["end_line"],
            "signature": symbol["signature"],
            "decorators": symbol.get("decorators", []),
            "docstring": symbol.get("docstring", ""),
            "content_hash": symbol.get("content_hash", ""),
            "source": source or ""
        })

    elapsed = (time.perf_counter() - start) * 1000

    return {
        "symbols": symbols,
        "errors": errors,
        "_meta": _make_meta(elapsed, symbol_count=len(symbols)),
    }
