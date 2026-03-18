"""Diff two indexed snapshots of a repository by comparing symbol sets."""

import time
from typing import Optional

from ..storage import IndexStore
from ._utils import resolve_repo


def get_symbol_diff(
    repo_a: str,
    repo_b: str,
    storage_path: Optional[str] = None,
) -> dict:
    """Diff the symbol sets of two indexed repositories (or two branches indexed separately).

    Compares by ``(name, kind)`` key. Uses ``content_hash`` to detect symbols
    that exist in both repos but whose source has changed.

    Typical use: index the same repo under two names (e.g. ``owner/repo-main``
    and ``owner/repo-feature``), then call ``get_symbol_diff`` to see what
    changed between them.

    Args:
        repo_a: First repository identifier (the "before" snapshot).
        repo_b: Second repository identifier (the "after" snapshot).
        storage_path: Custom storage path.

    Returns:
        Dict with ``added``, ``removed``, ``changed``, and ``unchanged`` counts
        plus the symbol lists for added/removed/changed entries.
    """
    start = time.perf_counter()

    try:
        owner_a, name_a = resolve_repo(repo_a, storage_path)
        owner_b, name_b = resolve_repo(repo_b, storage_path)
    except ValueError as e:
        return {"error": str(e)}

    store = IndexStore(base_path=storage_path)
    index_a = store.load_index(owner_a, name_a)
    index_b = store.load_index(owner_b, name_b)

    if not index_a:
        return {"error": f"Repository not indexed: {owner_a}/{name_a}"}
    if not index_b:
        return {"error": f"Repository not indexed: {owner_b}/{name_b}"}

    # Build lookup maps keyed by (name, kind) — using the first match when dupes exist
    def _sym_map(index) -> dict[tuple, dict]:
        m: dict[tuple, dict] = {}
        for sym in index.symbols:
            key = (sym.get("name", ""), sym.get("kind", ""))
            if key not in m:
                m[key] = sym
        return m

    map_a = _sym_map(index_a)
    map_b = _sym_map(index_b)

    keys_a = set(map_a)
    keys_b = set(map_b)

    added_keys = keys_b - keys_a
    removed_keys = keys_a - keys_b
    common_keys = keys_a & keys_b

    added = sorted(
        [{"name": k[0], "kind": k[1], "file": map_b[k].get("file", ""), "line": map_b[k].get("line", 0)}
         for k in added_keys],
        key=lambda x: (x["file"], x["name"]),
    )
    removed = sorted(
        [{"name": k[0], "kind": k[1], "file": map_a[k].get("file", ""), "line": map_a[k].get("line", 0)}
         for k in removed_keys],
        key=lambda x: (x["file"], x["name"]),
    )

    changed = []
    unchanged_count = 0
    for key in common_keys:
        sym_a = map_a[key]
        sym_b = map_b[key]
        hash_a = sym_a.get("content_hash", "")
        hash_b = sym_b.get("content_hash", "")
        sig_a = sym_a.get("signature", "")
        sig_b = sym_b.get("signature", "")

        if (hash_a and hash_b and hash_a != hash_b) or (not hash_a and sig_a != sig_b):
            changed.append({
                "name": key[0],
                "kind": key[1],
                "file_a": sym_a.get("file", ""),
                "file_b": sym_b.get("file", ""),
                "signature_a": sig_a,
                "signature_b": sig_b,
                "hash_changed": hash_a != hash_b if (hash_a and hash_b) else None,
            })
        else:
            unchanged_count += 1

    changed.sort(key=lambda x: (x["file_b"], x["name"]))

    elapsed = (time.perf_counter() - start) * 1000
    return {
        "repo_a": f"{owner_a}/{name_a}",
        "repo_b": f"{owner_b}/{name_b}",
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "unchanged_count": unchanged_count,
        "added": added,
        "removed": removed,
        "changed": changed,
        "_meta": {
            "timing_ms": round(elapsed, 1),
            "symbols_a": len(index_a.symbols),
            "symbols_b": len(index_b.symbols),
            "tip": "Index the same repo under two names (e.g. repo-main, repo-feature) to diff branches.",
        },
    }
