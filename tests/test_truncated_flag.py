"""Regression tests for the `truncated` flag in search_symbols.

Verifies that token_budget packing correctly sets truncated=True when results
are dropped, and truncated=False when no results are dropped.
"""
import pytest
from jcodemunch_mcp.tools.index_folder import index_folder
from jcodemunch_mcp.tools.search_symbols import search_symbols


def _build_repo(tmp_path):
    """Build a synthetic repo with many small symbols to test budget packing."""
    src = tmp_path / "src"
    store = tmp_path / "store"
    src.mkdir()
    store.mkdir()

    # Write 20 small functions with a common keyword so BM25 finds them all
    lines = []
    for i in range(20):
        lines.append(f"def budget_test_func_{i}():\n    return {i}\n")
    (src / "funcs.py").write_text("\n".join(lines))

    result = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
    assert result["success"] is True
    return result["repo"], str(store)


class TestTruncatedFlag:
    def test_no_budget_truncated_is_false(self, tmp_path):
        """Without token_budget, truncated must be False."""
        repo, store = _build_repo(tmp_path)
        result = search_symbols(
            repo=repo,
            query="budget_test_func",
            max_results=50,
            storage_path=store,
        )
        assert "error" not in result
        assert result["_meta"]["truncated"] is False

    def test_budget_packing_sets_truncated_true(self, tmp_path):
        """token_budget=1 forces budget packing; truncated must be True."""
        repo, store = _build_repo(tmp_path)
        result = search_symbols(
            repo=repo,
            query="budget_test_func",
            max_results=50,
            token_budget=1,  # tiny budget — forces packing to drop results
            storage_path=store,
        )
        assert "error" not in result
        # With budget=1 token, most results must be dropped
        assert result["_meta"]["truncated"] is True

    def test_large_budget_truncated_is_false(self, tmp_path):
        """A budget large enough to fit all results must leave truncated=False."""
        repo, store = _build_repo(tmp_path)
        result = search_symbols(
            repo=repo,
            query="budget_test_func",
            max_results=50,
            token_budget=100_000,  # huge budget — nothing dropped
            storage_path=store,
        )
        assert "error" not in result
        assert result["_meta"]["truncated"] is False

    def test_truncated_true_when_fuzzy_augments_after_budget_drop(self, tmp_path):
        """Regression: fuzzy augmentation after budget packing must not mask truncated=True.

        Previously: truncated was computed as (candidates_scored > len(scored_results))
        AFTER fuzzy results were appended, which could produce False even when budget
        packing had dropped BM25 results.
        """
        repo, store = _build_repo(tmp_path)
        result = search_symbols(
            repo=repo,
            query="budget_test_func",
            max_results=50,
            token_budget=1,
            fuzzy=True,
            storage_path=store,
        )
        assert "error" not in result
        assert result["_meta"]["truncated"] is True
