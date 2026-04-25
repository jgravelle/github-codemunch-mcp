"""Tests for get_repo_health tool."""

from jcodemunch_mcp.tools.get_repo_health import get_repo_health
from jcodemunch_mcp.tools.index_folder import index_folder


def _build_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    store = tmp_path / "store"
    store.mkdir()

    (src / "main.py").write_text(
        "from utils import helper\n\ndef main():\n    helper()\n"
    )
    (src / "utils.py").write_text(
        "def helper():\n    return 1\n\n"
        "def dead_fn():\n    pass\n"
    )
    r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
    assert r["success"] is True
    return r["repo"], str(store)


class TestGetRepoHealth:
    def test_returns_required_fields(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_repo_health(repo=repo, storage_path=store)
        assert "summary" in result
        assert "total_files" in result
        assert "total_symbols" in result
        assert "avg_complexity" in result
        assert "dead_code_pct" in result
        assert "dead_count" in result
        assert "cycle_count" in result
        assert "cycles_sample" in result
        assert "unstable_modules" in result
        assert "top_hotspots" in result
        assert "_meta" in result

    def test_summary_is_string(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_repo_health(repo=repo, storage_path=store)
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    def test_counts_are_non_negative(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_repo_health(repo=repo, storage_path=store)
        assert result["total_files"] >= 0
        assert result["total_symbols"] >= 0
        assert result["cycle_count"] >= 0
        assert result["dead_count"] >= 0
        assert result["unstable_modules"] >= 0

    def test_dead_code_pct_range(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_repo_health(repo=repo, storage_path=store)
        assert 0.0 <= result["dead_code_pct"] <= 100.0

    def test_top_hotspots_is_list(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_repo_health(repo=repo, storage_path=store)
        assert isinstance(result["top_hotspots"], list)
        assert len(result["top_hotspots"]) <= 5

    def test_cycles_sample_is_list(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_repo_health(repo=repo, storage_path=store)
        assert isinstance(result["cycles_sample"], list)

    def test_timing_present(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_repo_health(repo=repo, storage_path=store)
        assert "timing_ms" in result["_meta"]

    def test_missing_repo_returns_error(self, tmp_path):
        result = get_repo_health(repo="no_such_repo", storage_path=str(tmp_path))
        assert "error" in result

    def test_repo_field_present(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_repo_health(repo=repo, storage_path=store)
        assert "repo" in result
        assert "/" in result["repo"]

    def test_fn_method_count_present(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_repo_health(repo=repo, storage_path=store)
        assert "fn_method_count" in result
        assert result["fn_method_count"] >= 0

    def test_no_nameerror_when_decorators_present(self, tmp_path):
        """Regression: v1.73.1 raised NameError on _ENTRY_POINT_DECORATOR_RE
        when any symbol carried a decorator. Fixture must trigger the
        decorator-skip branch in dead-code analysis."""
        src = tmp_path / "src"
        src.mkdir()
        store = tmp_path / "store"
        store.mkdir()
        (src / "app.py").write_text(
            "from flask import Flask\n"
            "app = Flask(__name__)\n\n"
            "@app.route('/health')\n"
            "def health():\n    return 'ok'\n\n"
            "@app.route('/items')\n"
            "def items():\n    return []\n"
        )
        r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert r["success"] is True
        result = get_repo_health(repo=r["repo"], storage_path=str(store))
        assert "error" not in result, result
        assert "summary" in result
