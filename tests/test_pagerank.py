"""Tests for PageRank / centrality ranking (Feature 2 from upgrades-PRD.md)."""

import pytest
from pathlib import Path

from jcodemunch_mcp.tools.pagerank import compute_pagerank, compute_in_out_degrees
from jcodemunch_mcp.tools.get_symbol_importance import get_symbol_importance
from jcodemunch_mcp.tools.search_symbols import search_symbols
from jcodemunch_mcp.tools.get_repo_outline import get_repo_outline
from jcodemunch_mcp.tools.index_folder import index_folder


# ---------------------------------------------------------------------------
# Unit tests: compute_pagerank
# ---------------------------------------------------------------------------

class TestComputePagerank:
    """Unit tests for the core PageRank algorithm."""

    def _make_imports(self, edges: list) -> dict:
        """Build an imports dict from (src, dst) edge list."""
        result: dict = {}
        for src, dst in edges:
            if src not in result:
                result[src] = []
            result[src].append({"specifier": dst, "names": []})
        return result

    def test_scores_sum_to_one(self):
        """PageRank scores must be normalized so they sum to approximately 1.0."""
        files = ["a.py", "b.py", "c.py", "d.py"]
        imports = self._make_imports([("a.py", "b.py"), ("c.py", "b.py"), ("d.py", "b.py")])
        scores, _ = compute_pagerank(imports, files)
        total = sum(scores.values())
        assert abs(total - 1.0) < 0.01

    def test_most_imported_ranks_highest(self):
        """The file with the most importers should have the highest PageRank score."""
        files = ["a.py", "b.py", "c.py"]
        imports = self._make_imports([("a.py", "b.py"), ("c.py", "b.py")])
        scores, _ = compute_pagerank(imports, files)
        assert scores["b.py"] > scores["a.py"]
        assert scores["b.py"] > scores["c.py"]

    def test_empty_import_graph(self):
        """Repo with no imports returns uniform distribution (no crash)."""
        files = ["a.py", "b.py"]
        scores, iters = compute_pagerank({}, files)
        assert len(scores) == 2
        assert abs(scores["a.py"] - 0.5) < 0.01
        assert abs(scores["b.py"] - 0.5) < 0.01

    def test_empty_file_list(self):
        """Empty file list returns empty dict."""
        scores, iters = compute_pagerank({}, [])
        assert scores == {}
        assert iters == 0

    def test_convergence_reported(self):
        """iterations_to_converge should be <= max_iter and >= 1."""
        files = ["a.py", "b.py", "c.py"]
        imports = self._make_imports([("a.py", "b.py"), ("b.py", "c.py"), ("c.py", "a.py")])
        scores, iters = compute_pagerank(imports, files)
        assert 1 <= iters <= 100

    def test_in_out_degrees(self):
        """compute_in_out_degrees returns correct counts."""
        files = ["a.py", "b.py", "c.py", "d.py"]
        # b.py has in_degree=3 (a, c, d all import it)
        imports = self._make_imports([("a.py", "b.py"), ("c.py", "b.py"), ("d.py", "b.py")])
        in_deg, out_deg = compute_in_out_degrees(imports, files)
        assert in_deg["b.py"] == 3
        assert in_deg["a.py"] == 0
        assert out_deg["a.py"] == 1
        assert out_deg["b.py"] == 0

    def test_self_import_ignored(self):
        """Self-imports should not create self-loops."""
        files = ["a.py", "b.py"]
        imports = {"a.py": [{"specifier": "a.py", "names": []}, {"specifier": "b.py", "names": []}]}
        in_deg, out_deg = compute_in_out_degrees(imports, files)
        assert in_deg.get("a.py", 0) == 0  # self-link not counted
        assert in_deg.get("b.py", 0) == 1

    def test_circular_imports_no_infinite_loop(self):
        """Circular imports must converge within max_iter."""
        files = ["a.py", "b.py", "c.py"]
        imports = self._make_imports([("a.py", "b.py"), ("b.py", "c.py"), ("c.py", "a.py")])
        scores, iters = compute_pagerank(imports, files, max_iter=100)
        assert iters <= 100
        assert sum(scores.values()) > 0


# ---------------------------------------------------------------------------
# Integration tests: get_symbol_importance
# ---------------------------------------------------------------------------

class TestGetSymbolImportance:
    """Integration tests for the get_symbol_importance tool."""

    @pytest.fixture
    def indexed_repo(self, tmp_path):
        """Create a small Python repo with clear import hierarchy and index it."""
        src = tmp_path / "src"
        src.mkdir()
        store = tmp_path / "store"

        # core.py: imported by utils.py and app.py
        (src / "core.py").write_text(
            "class Engine:\n    def run(self): pass\n\ndef helper(): pass\n"
        )
        # utils.py: imports core.py
        (src / "utils.py").write_text(
            "from core import Engine\n\ndef format_date(): pass\n"
        )
        # app.py: imports core.py and utils.py
        (src / "app.py").write_text(
            "from core import Engine\nfrom utils import format_date\n\ndef main(): pass\n"
        )
        # standalone.py: no imports, not imported
        (src / "standalone.py").write_text(
            "def unused(): pass\n"
        )
        result = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert "error" not in result
        return result["repo"], store

    def test_most_imported_symbol_ranks_first(self, indexed_repo):
        """core.py is imported by 2 files, so its symbols should rank #1."""
        repo_id, store = indexed_repo
        result = get_symbol_importance(repo_id, top_n=10, storage_path=str(store))
        assert "error" not in result
        assert len(result["ranked_symbols"]) > 0
        top_sym = result["ranked_symbols"][0]
        assert "core.py" in top_sym["symbol_id"]

    def test_response_shape(self, indexed_repo):
        """Response must include ranked_symbols, algorithm, iterations_to_converge."""
        repo_id, store = indexed_repo
        result = get_symbol_importance(repo_id, storage_path=str(store))
        assert "ranked_symbols" in result
        assert "algorithm" in result
        assert "iterations_to_converge" in result
        assert result["algorithm"] == "pagerank"
        for sym in result["ranked_symbols"]:
            assert "symbol_id" in sym
            assert "rank" in sym
            assert "score" in sym
            assert "in_degree" in sym
            assert "out_degree" in sym
            assert "kind" in sym

    def test_degree_algorithm(self, indexed_repo):
        """algorithm='degree' returns results without calling PageRank."""
        repo_id, store = indexed_repo
        result = get_symbol_importance(repo_id, algorithm="degree", storage_path=str(store))
        assert "error" not in result
        assert result["algorithm"] == "degree"
        assert result["iterations_to_converge"] == 0
        assert len(result["ranked_symbols"]) > 0

    def test_degree_same_top_as_pagerank(self, indexed_repo):
        """degree algorithm top-1 should be the same file as PageRank top-1 on simple graphs."""
        repo_id, store = indexed_repo
        pr_result = get_symbol_importance(repo_id, algorithm="pagerank", storage_path=str(store))
        deg_result = get_symbol_importance(repo_id, algorithm="degree", storage_path=str(store))
        assert "error" not in pr_result
        assert "error" not in deg_result
        # Both should agree that core.py is most important
        pr_top_file = pr_result["ranked_symbols"][0]["symbol_id"].split("::")[0]
        deg_top_file = deg_result["ranked_symbols"][0]["symbol_id"].split("::")[0]
        assert pr_top_file == deg_top_file

    def test_invalid_algorithm(self, indexed_repo):
        """Invalid algorithm returns error, not crash."""
        repo_id, store = indexed_repo
        result = get_symbol_importance(repo_id, algorithm="louvain", storage_path=str(store))
        assert "error" in result

    def test_top_n_respected(self, indexed_repo):
        """top_n=1 returns at most 1 result."""
        repo_id, store = indexed_repo
        result = get_symbol_importance(repo_id, top_n=1, storage_path=str(store))
        assert "error" not in result
        assert len(result["ranked_symbols"]) <= 1

    def test_missing_repo(self, tmp_path):
        """Missing repo returns structured error."""
        result = get_symbol_importance("nonexistent_repo_xyz", storage_path=str(tmp_path / ".idx"))
        assert "error" in result


# ---------------------------------------------------------------------------
# Integration tests: search_symbols sort_by
# ---------------------------------------------------------------------------

class TestSearchSymbolsSortBy:
    """Tests for the sort_by parameter on search_symbols."""

    @pytest.fixture
    def indexed_repo(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        store = tmp_path / "store"
        (src / "core.py").write_text(
            "class Engine:\n    def run(self): pass\n"
        )
        (src / "utils.py").write_text(
            "from core import Engine\n\ndef helper(): pass\n"
        )
        (src / "app.py").write_text(
            "from core import Engine\nfrom utils import helper\n\ndef main(): pass\n"
        )
        result = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert "error" not in result
        return result["repo"], store

    def test_relevance_is_default(self, indexed_repo):
        """sort_by='relevance' (default) returns results without error."""
        repo_id, store = indexed_repo
        result = search_symbols(repo_id, query="Engine", sort_by="relevance", storage_path=str(store))
        assert "error" not in result
        assert result["result_count"] > 0

    def test_centrality_sort(self, indexed_repo):
        """sort_by='centrality' returns query-matched results."""
        repo_id, store = indexed_repo
        result = search_symbols(repo_id, query="Engine", sort_by="centrality", storage_path=str(store))
        assert "error" not in result
        assert result["result_count"] > 0

    def test_combined_sort(self, indexed_repo):
        """sort_by='combined' returns results without error."""
        repo_id, store = indexed_repo
        result = search_symbols(repo_id, query="helper", sort_by="combined", storage_path=str(store))
        assert "error" not in result
        assert result["result_count"] > 0

    def test_invalid_sort_by(self, indexed_repo):
        """Invalid sort_by returns structured error."""
        repo_id, store = indexed_repo
        result = search_symbols(repo_id, query="Engine", sort_by="magic", storage_path=str(store))
        assert "error" in result

    def test_sort_by_backward_compat(self, indexed_repo):
        """sort_by='relevance' produces same results as omitting sort_by (backward compat)."""
        repo_id, store = indexed_repo
        r1 = search_symbols(repo_id, query="Engine", storage_path=str(store))
        r2 = search_symbols(repo_id, query="Engine", sort_by="relevance", storage_path=str(store))
        assert "error" not in r1
        assert "error" not in r2
        assert [s["id"] for s in r1["results"]] == [s["id"] for s in r2["results"]]


# ---------------------------------------------------------------------------
# Integration tests: get_repo_outline most_central_symbols
# ---------------------------------------------------------------------------

class TestRepoOutlineMostCentralSymbols:
    """Tests for the most_central_symbols field in get_repo_outline."""

    @pytest.fixture
    def indexed_repo(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        store = tmp_path / "store"
        (src / "core.py").write_text("class Engine:\n    def run(self): pass\n")
        (src / "utils.py").write_text("from core import Engine\n\ndef helper(): pass\n")
        (src / "app.py").write_text("from core import Engine\n\ndef main(): pass\n")
        result = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert "error" not in result
        return result["repo"], store

    def test_most_central_symbols_present(self, indexed_repo):
        """get_repo_outline includes most_central_symbols when import graph exists."""
        repo_id, store = indexed_repo
        result = get_repo_outline(repo_id, storage_path=str(store))
        assert "error" not in result
        assert "most_central_symbols" in result

    def test_most_central_symbols_shape(self, indexed_repo):
        """Each entry has symbol_id, score, kind."""
        repo_id, store = indexed_repo
        result = get_repo_outline(repo_id, storage_path=str(store))
        for sym in result.get("most_central_symbols", []):
            assert "symbol_id" in sym
            assert "score" in sym
            assert "kind" in sym

    def test_most_central_top_is_most_imported_file(self, indexed_repo):
        """core.py (imported by 2 files) should contain the #1 most central symbol."""
        repo_id, store = indexed_repo
        result = get_repo_outline(repo_id, storage_path=str(store))
        central = result.get("most_central_symbols", [])
        assert len(central) > 0
        assert "core.py" in central[0]["symbol_id"]
