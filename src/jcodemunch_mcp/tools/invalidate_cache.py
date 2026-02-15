"""Invalidate cache / delete index tool."""

from typing import Optional

from ..storage import IndexStore


def invalidate_cache(
    repo: str,
    storage_path: Optional[str] = None
) -> dict:
    """Delete an index and all cached data for a repository.

    This is an alias for delete_index that also ensures any in-memory
    state is cleared. Use when you want to force a full re-index.

    Args:
        repo: Repository identifier (owner/repo or just repo name).
        storage_path: Custom storage path.

    Returns:
        Dict with success status.
    """
    # Parse repo identifier
    if "/" in repo:
        owner, name = repo.split("/", 1)
    else:
        store = IndexStore(base_path=storage_path)
        repos = store.list_repos()
        matching = [r for r in repos if r["repo"].endswith(f"/{repo}")]
        if not matching:
            return {"error": f"Repository not found: {repo}"}
        owner, name = matching[0]["repo"].split("/", 1)

    store = IndexStore(base_path=storage_path)
    deleted = store.delete_index(owner, name)

    if deleted:
        return {
            "success": True,
            "repo": f"{owner}/{name}",
            "message": f"Index and cached files deleted for {owner}/{name}",
        }
    else:
        return {
            "success": False,
            "error": f"No index found for {owner}/{name}",
        }
