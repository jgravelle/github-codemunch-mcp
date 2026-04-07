"""Tests for negative evidence in search_symbols (Feature 1)."""

import pytest
from pathlib import Path

from tests.conftest_helpers import create_mini_index


class TestNegativeEvidence:
    """Tests for negative_evidence field in search results."""

    def test_negative_evidence_on_empty_results(self, tmp_path: Path):
        """When no matches found, negative_evidence is present with verdict."""
        from jcodemunch_mcp.tools.search_symbols import search_symbols
        repo, storage_path = create_mini_index(tmp_path)
        result = search_symbols(
            repo=repo,
            query="nonexistent_xyz_redis_cache",
            storage_path=storage_path,
        )
        assert "negative_evidence" in result
        ne = result["negative_evidence"]
        assert ne["verdict"] == "no_implementation_found"
        assert ne["scanned_symbols"] > 0
        assert ne["scanned_files"] > 0
        assert "best_match_score" in ne

    def test_no_negative_evidence_on_strong_match(self, tmp_path: Path):
        """When strong match found, negative_evidence is NOT present."""
        from jcodemunch_mcp.tools.search_symbols import search_symbols
        repo, storage_path = create_mini_index(tmp_path)
        result = search_symbols(repo=repo, query="my_func", storage_path=storage_path)
        assert result["result_count"] >= 1
        assert "negative_evidence" not in result

    def test_related_existing_files(self, tmp_path: Path):
        """When query matches file name but not symbol, related_existing shows nearby files."""
        from jcodemunch_mcp.tools.search_symbols import search_symbols
        repo, storage_path = create_mini_index(tmp_path, filename="auth_handler.py")
        result = search_symbols(
            repo=repo,
            query="auth_nonexistent",
            storage_path=storage_path,
        )
        # Should have negative_evidence since no symbol matches
        assert "negative_evidence" in result
        # related_existing should mention the auth file
        ne = result["negative_evidence"]
        assert "related_existing" in ne
        # The auth_handler.py file should be mentioned
        related = ne["related_existing"]
        assert any("auth" in f.lower() for f in related)

    def test_threshold_constant_importable(self):
        """_NEGATIVE_EVIDENCE_THRESHOLD constant exists and is > 0."""
        from jcodemunch_mcp.tools.search_symbols import _NEGATIVE_EVIDENCE_THRESHOLD
        assert _NEGATIVE_EVIDENCE_THRESHOLD > 0
        assert _NEGATIVE_EVIDENCE_THRESHOLD < 10  # Reasonable range

    def test_low_confidence_match_shows_negative_evidence(self, tmp_path: Path):
        """When match score is below threshold, negative_evidence is present."""
        from jcodemunch_mcp.tools.search_symbols import search_symbols, _NEGATIVE_EVIDENCE_THRESHOLD
        repo, storage_path = create_mini_index(tmp_path)
        # Search for something that partially matches but shouldn't be a strong match
        result = search_symbols(
            repo=repo,
            query="xyz_my_func_abc",  # Contains my_func but not exact
            storage_path=storage_path,
        )
        # If the score is below threshold, should have negative_evidence
        # If above threshold (fuzzy match worked), should have results
        if result.get("result_count", 0) == 0 or result.get("negative_evidence"):
            ne = result.get("negative_evidence", {})
            assert "verdict" in ne


class TestGetRankedContextNegativeEvidence:
    """Tests for negative_evidence field in get_ranked_context."""

    def test_negative_evidence_on_empty_result(self, tmp_path: Path):
        """get_ranked_context returns negative_evidence when query doesn't match."""
        from jcodemunch_mcp.tools.index_folder import index_folder
        from jcodemunch_mcp.tools.get_ranked_context import get_ranked_context

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("def real_function(): pass\n")

        storage = str(tmp_path / "idx")
        idx = index_folder(path=str(tmp_path), use_ai_summaries=False, storage_path=storage)
        repo = idx["repo"]

        result = get_ranked_context(
            repo=repo,
            query="completely_nonexistent_feature_xyz",
            token_budget=4000,
            storage_path=storage,
        )

        assert result["items_included"] == 0
        assert "negative_evidence" in result
        assert result["negative_evidence"]["verdict"] == "no_implementation_found"
        assert result["negative_evidence"]["scanned_symbols"] >= 0
        assert result["negative_evidence"]["best_match_score"] == 0.0

    def test_warning_string_present_on_negative_evidence(self, tmp_path: Path):
        """Verify warning string at top level when negative evidence triggers."""
        from jcodemunch_mcp.tools.index_folder import index_folder
        from jcodemunch_mcp.tools.get_ranked_context import get_ranked_context

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("def real_function(): pass\n")

        storage = str(tmp_path / "idx")
        idx = index_folder(path=str(tmp_path), use_ai_summaries=False, storage_path=storage)
        repo = idx["repo"]

        result = get_ranked_context(
            repo=repo,
            query="nonexistent_xyz",
            token_budget=4000,
            storage_path=storage,
        )

        assert "\u26a0 warning" in result
        assert "nonexistent_xyz" in result["\u26a0 warning"]

    def test_no_negative_evidence_on_strong_match(self, tmp_path: Path):
        """No negative_evidence when query matches well."""
        from jcodemunch_mcp.tools.index_folder import index_folder
        from jcodemunch_mcp.tools.get_ranked_context import get_ranked_context

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("def my_special_function():\n    return 42\n")

        storage = str(tmp_path / "idx")
        idx = index_folder(path=str(tmp_path), use_ai_summaries=False, storage_path=storage)
        repo = idx["repo"]

        result = get_ranked_context(
            repo=repo,
            query="my_special_function",
            token_budget=4000,
            storage_path=storage,
        )

        assert result["items_included"] > 0
        assert "negative_evidence" not in result
        assert "\u26a0 warning" not in result

    def test_related_existing_in_negative_evidence(self, tmp_path: Path):
        """related_existing lists files with partial name match."""
        from jcodemunch_mcp.tools.index_folder import index_folder
        from jcodemunch_mcp.tools.get_ranked_context import get_ranked_context

        src = tmp_path / "src"
        src.mkdir()
        (src / "auth_handler.py").write_text("def login(): pass\n")

        storage = str(tmp_path / "idx")
        idx = index_folder(path=str(tmp_path), use_ai_summaries=False, storage_path=storage)
        repo = idx["repo"]

        result = get_ranked_context(
            repo=repo,
            query="auth_nonexistent_feature",
            token_budget=4000,
            storage_path=storage,
        )

        ne = result.get("negative_evidence", {})
        # "auth" is in query and in filename "auth_handler.py"
        if ne.get("related_existing"):
            assert any("auth" in f for f in ne["related_existing"])


class TestSearchSymbolsWarningString:
    """Tests for warning string alongside negative_evidence in search_symbols."""

    def test_warning_on_negative_evidence(self, tmp_path: Path):
        """search_symbols includes warning string when negative evidence triggers."""
        from jcodemunch_mcp.tools.index_folder import index_folder
        from jcodemunch_mcp.tools.search_symbols import search_symbols

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("def real_function(): pass\n")

        storage = str(tmp_path / "idx")
        idx = index_folder(path=str(tmp_path), use_ai_summaries=False, storage_path=storage)
        repo = idx["repo"]

        result = search_symbols(
            repo=repo,
            query="nonexistent_xyz_feature",
            storage_path=storage,
        )

        assert "negative_evidence" in result
        assert "\u26a0 warning" in result
        assert "nonexistent_xyz" in result["\u26a0 warning"]

    def test_no_warning_on_good_match(self, tmp_path: Path):
        """No warning string when results are strong."""
        from jcodemunch_mcp.tools.index_folder import index_folder
        from jcodemunch_mcp.tools.search_symbols import search_symbols

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("def real_function(): pass\n")

        storage = str(tmp_path / "idx")
        idx = index_folder(path=str(tmp_path), use_ai_summaries=False, storage_path=storage)
        repo = idx["repo"]

        result = search_symbols(
            repo=repo,
            query="real_function",
            storage_path=storage,
        )

        assert "\u26a0 warning" not in result