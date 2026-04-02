"""Tests for get_extraction_candidates tool."""

import pytest
from jcodemunch_mcp.tools.get_extraction_candidates import get_extraction_candidates
from jcodemunch_mcp.tools.index_folder import index_folder


def _build_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    store = tmp_path / "store"
    store.mkdir()

    # A utility module with a complex function called from multiple files
    (src / "utils.py").write_text(
        "def complex_util(x, y, z):\n"
        "    if x > 0:\n"
        "        if y > 0:\n"
        "            if z > 0:\n"
        "                return x + y + z\n"
        "            else:\n"
        "                return x + y\n"
        "        elif y < 0:\n"
        "            return x - y\n"
        "        else:\n"
        "            return x\n"
        "    elif x < 0:\n"
        "        return -x\n"
        "    else:\n"
        "        return 0\n\n"
        "def simple_fn():\n"
        "    return 42\n"
    )
    (src / "a.py").write_text("from utils import complex_util\nresult = complex_util(1, 2, 3)\n")
    (src / "b.py").write_text("from utils import complex_util\nresult = complex_util(4, 5, 6)\n")
    (src / "c.py").write_text("from utils import complex_util\nresult = complex_util(7, 8, 9)\n")

    r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
    assert r["success"] is True
    return r["repo"], str(store)


class TestGetExtractionCandidates:
    def test_returns_candidates_structure(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_extraction_candidates(
            repo=repo, file_path="utils.py", storage_path=store
        )
        assert "candidates" in result
        assert "file" in result
        assert isinstance(result["candidates"], list)

    def test_candidate_has_required_fields(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_extraction_candidates(
            repo=repo, file_path="utils.py", min_complexity=1, min_callers=1,
            storage_path=store,
        )
        for c in result["candidates"]:
            assert "id" in c
            assert "name" in c
            assert "cyclomatic" in c
            assert "caller_count" in c
            assert "caller_files" in c
            assert "score" in c
            assert c["score"] >= 0

    def test_min_complexity_filters(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result_low = get_extraction_candidates(
            repo=repo, file_path="utils.py", min_complexity=1, min_callers=1,
            storage_path=store,
        )
        result_high = get_extraction_candidates(
            repo=repo, file_path="utils.py", min_complexity=100, min_callers=1,
            storage_path=store,
        )
        assert len(result_low["candidates"]) >= len(result_high["candidates"])

    def test_min_callers_filters(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result_low = get_extraction_candidates(
            repo=repo, file_path="utils.py", min_complexity=1, min_callers=1,
            storage_path=store,
        )
        result_high = get_extraction_candidates(
            repo=repo, file_path="utils.py", min_complexity=1, min_callers=100,
            storage_path=store,
        )
        assert len(result_low["candidates"]) >= len(result_high["candidates"])

    def test_results_sorted_by_score(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_extraction_candidates(
            repo=repo, file_path="utils.py", min_complexity=1, min_callers=1,
            storage_path=store,
        )
        scores = [c["score"] for c in result["candidates"]]
        assert scores == sorted(scores, reverse=True)

    def test_missing_repo_returns_error(self, tmp_path):
        result = get_extraction_candidates(
            repo="no_such_repo", file_path="utils.py", storage_path=str(tmp_path)
        )
        assert "error" in result

    def test_missing_file_returns_error(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_extraction_candidates(
            repo=repo, file_path="nonexistent_xyz.py", storage_path=store
        )
        assert "error" in result

    def test_timing_present(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_extraction_candidates(
            repo=repo, file_path="utils.py", storage_path=store
        )
        assert "_meta" in result
        assert "timing_ms" in result["_meta"]
