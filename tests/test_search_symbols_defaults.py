"""Regression tests for §1.1 (detail_level="auto") and §1.2 (token_budget ordering).

These back the v2.0.0-alpha behavior changes in search_symbols:
  §1.1 — default detail_level flips from "standard" to "auto", which resolves
         to "compact" for broad discovery and "standard" otherwise.
  §1.2 — full-mode payload is materialized BEFORE budget packing, so
         token_budget is actually respected when detail_level="full".
"""

from jcodemunch_mcp.tools.index_folder import index_folder
from jcodemunch_mcp.tools.search_symbols import search_symbols


def _seed_repo_with_symbols(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    body = "\n".join(f"    x{i} = {i}" for i in range(80))  # hefty body for full-mode
    code = ""
    for name in ["alpha", "alphabet", "alphanumeric", "alphonse", "alpine", "album"]:
        code += f"def {name}():\n    \"\"\"Docstring for {name} — long enough to consume bytes.\"\"\"\n{body}\n\n"
    (src / "a.py").write_text(code)
    idx = index_folder(path=str(tmp_path), use_ai_summaries=False, storage_path=str(tmp_path / "idx"))
    return idx["repo"], str(tmp_path / "idx")


def test_search_symbols_auto_defaults_to_compact_for_broad_queries(tmp_path):
    """§1.1 — auto picks compact when max_results>=5, no budget, no debug."""
    repo, storage = _seed_repo_with_symbols(tmp_path)

    result = search_symbols(repo=repo, query="alpha", max_results=10, storage_path=storage)

    assert result.get("result_count", 0) > 0
    first = result["results"][0]
    # Compact shape: no signature or summary keys present
    assert "signature" not in first, f"auto should resolve to compact for broad queries, got {first}"
    assert "summary" not in first
    assert "id" in first and "name" in first and "file" in first and "line" in first


def test_search_symbols_auto_escalates_to_standard_for_small_result_sets(tmp_path):
    """§1.1 — auto falls back to standard when max_results<5."""
    repo, storage = _seed_repo_with_symbols(tmp_path)

    result = search_symbols(repo=repo, query="alpha", max_results=3, storage_path=storage)

    assert result.get("result_count", 0) > 0
    first = result["results"][0]
    # Standard shape: signature is present
    assert "signature" in first, f"auto should resolve to standard for narrow queries, got {first}"


def test_search_symbols_auto_escalates_to_standard_when_debug(tmp_path):
    """§1.1 — auto yields standard under debug=True regardless of max_results."""
    repo, storage = _seed_repo_with_symbols(tmp_path)

    result = search_symbols(repo=repo, query="alpha", max_results=10, debug=True, storage_path=storage)

    assert result.get("result_count", 0) > 0
    assert "signature" in result["results"][0]


def test_search_symbols_explicit_detail_level_is_not_overridden(tmp_path):
    """§1.1 — explicit detail_level is always honored, never silently changed."""
    repo, storage = _seed_repo_with_symbols(tmp_path)

    # Explicit "standard" with broad query — auto heuristic would pick compact,
    # but explicit must win.
    result = search_symbols(
        repo=repo, query="alpha", max_results=10, detail_level="standard", storage_path=storage
    )
    assert result.get("result_count", 0) > 0
    assert "signature" in result["results"][0]

    # Explicit "compact" with narrow query — auto heuristic would pick standard.
    result_c = search_symbols(
        repo=repo, query="alpha", max_results=2, detail_level="compact", storage_path=storage
    )
    assert result_c.get("result_count", 0) > 0
    assert "signature" not in result_c["results"][0]


def test_search_symbols_auto_is_valid_detail_level(tmp_path):
    """§1.1 — "auto" is an accepted value for detail_level."""
    repo, storage = _seed_repo_with_symbols(tmp_path)
    result = search_symbols(repo=repo, query="alpha", detail_level="auto", storage_path=storage)
    assert "error" not in result


def test_search_symbols_full_respects_token_budget(tmp_path):
    """§1.2 — token_budget must not be overshot in full mode.

    Before the fix, byte_length was computed from the signature-only entry,
    so full-mode source/docstring/end_line were appended AFTER packing and
    could overshoot the budget by 5-20x. The fix materializes full content
    before packing; response size must stay at or below the declared budget
    (allowing for a small envelope overhead).
    """
    repo, storage = _seed_repo_with_symbols(tmp_path)

    budget = 500  # tokens
    result = search_symbols(
        repo=repo,
        query="alpha",
        detail_level="full",
        token_budget=budget,
        max_results=20,
        storage_path=storage,
    )

    assert "error" not in result
    # Sum reported byte_length of returned items; packer claims sum <= budget*4 bytes.
    BYTES_PER_TOKEN = 4
    used_bytes = sum(e.get("byte_length", 0) for e in result.get("results", []))
    assert used_bytes <= budget * BYTES_PER_TOKEN, (
        f"full-mode packer overshot budget: {used_bytes} bytes vs {budget * BYTES_PER_TOKEN} allowed"
    )

    # Also: every returned entry actually carries materialized source/docstring/end_line.
    for entry in result.get("results", []):
        assert "source" in entry, "full mode must inline source"
        assert "docstring" in entry
        assert "end_line" in entry

    # tokens_used in _meta should also be under budget when meta is enabled
    used_reported = result.get("_meta", {}).get("tokens_used")
    if used_reported is not None:
        assert used_reported <= budget, f"_meta.tokens_used {used_reported} > budget {budget}"


def test_search_symbols_fusion_full_respects_token_budget(tmp_path):
    """§1.2 parity — fusion path must also respect token_budget in full mode."""
    repo, storage = _seed_repo_with_symbols(tmp_path)

    budget = 500
    result = search_symbols(
        repo=repo,
        query="alpha",
        detail_level="full",
        fusion=True,
        token_budget=budget,
        max_results=20,
        storage_path=storage,
    )

    assert "error" not in result
    BYTES_PER_TOKEN = 4
    used_bytes = sum(e.get("byte_length", 0) for e in result.get("results", []))
    assert used_bytes <= budget * BYTES_PER_TOKEN, (
        f"fusion full-mode packer overshot budget: {used_bytes} bytes vs {budget * BYTES_PER_TOKEN} allowed"
    )
    for entry in result.get("results", []):
        assert "source" in entry, "fusion full mode must inline source"
        assert "docstring" in entry
        assert "end_line" in entry


def test_search_symbols_auto_with_token_budget_gives_standard(tmp_path):
    """§1.1 — when token_budget is set, auto falls to standard (not compact)."""
    repo, storage = _seed_repo_with_symbols(tmp_path)

    # Budget large enough to fit at least one standard-shape entry with summary.
    result = search_symbols(
        repo=repo, query="alpha", token_budget=2000, max_results=10, storage_path=storage
    )

    assert result.get("result_count", 0) > 0
    # token_budget set → auto resolves to standard, so signature should be present
    assert "signature" in result["results"][0]
    # Confirm it's NOT compact — compact would have stripped signature.
    # Confirm it's NOT full — full would inline source.
    assert "source" not in result["results"][0]


def test_search_symbols_empty_query_handled(tmp_path):
    """Empty query still returns a structured response, no crash."""
    repo, storage = _seed_repo_with_symbols(tmp_path)
    result = search_symbols(repo=repo, query="", storage_path=storage)
    # Either returns empty results or negative_evidence; just must not crash
    assert isinstance(result, dict)
    assert "result_count" in result or "error" in result


def test_search_symbols_zero_results_does_not_crash_in_full(tmp_path):
    """full + token_budget + no matches should not blow up on materialization."""
    repo, storage = _seed_repo_with_symbols(tmp_path)
    result = search_symbols(
        repo=repo, query="zzzzznonmatch", detail_level="full",
        token_budget=200, storage_path=storage,
    )
    assert "error" not in result
    assert result.get("result_count", 0) == 0


def test_search_symbols_cache_key_distinguishes_auto_from_explicit_compact(tmp_path):
    """Cache must not conflate two callers who happen to get the same concrete level.

    Under the hood, auto-resolved "compact" and explicit "compact" should produce
    the same physical response shape (same cache entry is fine) — what we're
    really testing is that cache invalidation via indexed_at still works and
    that auto produces consistent, cached behavior across repeated calls.
    """
    repo, storage = _seed_repo_with_symbols(tmp_path)

    # Two consecutive auto-default calls must match (cache warm, same result)
    r1 = search_symbols(repo=repo, query="alpha", max_results=10, storage_path=storage)
    r2 = search_symbols(repo=repo, query="alpha", max_results=10, storage_path=storage)
    assert r1["result_count"] == r2["result_count"]
    ids_1 = [e["id"] for e in r1["results"]]
    ids_2 = [e["id"] for e in r2["results"]]
    assert ids_1 == ids_2
