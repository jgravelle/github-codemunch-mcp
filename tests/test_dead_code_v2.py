"""Tests for get_dead_code_v2 tool."""

import pytest
from jcodemunch_mcp.tools.get_dead_code_v2 import get_dead_code_v2
from jcodemunch_mcp.tools.index_folder import index_folder


def _build_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    store = tmp_path / "store"
    store.mkdir()

    # Entry point
    (src / "main.py").write_text(
        "from utils import used_fn\n\nif __name__ == '__main__':\n    used_fn()\n"
    )
    # Module with one used and one dead function
    (src / "utils.py").write_text(
        "def used_fn():\n    return 1\n\ndef dead_fn():\n    return 2\n"
    )
    # Completely unreachable module
    (src / "orphan.py").write_text(
        "def orphan_fn():\n    pass\n"
    )

    r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
    assert r["success"] is True
    return r["repo"], str(store)


class TestGetDeadCodeV2:
    def test_returns_dead_symbols(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_dead_code_v2(repo=repo, min_confidence=0.33, storage_path=store)
        assert "dead_symbols" in result
        assert isinstance(result["dead_symbols"], list)

    def test_dead_symbol_has_required_fields(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_dead_code_v2(repo=repo, min_confidence=0.1, storage_path=store)
        for sym in result["dead_symbols"]:
            assert "id" in sym
            assert "name" in sym
            assert "confidence" in sym
            assert "signals" in sym
            assert 0.0 <= sym["confidence"] <= 1.0
            assert isinstance(sym["signals"], list)

    def test_confidence_respects_threshold(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result_high = get_dead_code_v2(repo=repo, min_confidence=0.9, storage_path=store)
        result_low = get_dead_code_v2(repo=repo, min_confidence=0.1, storage_path=store)
        high_count = len(result_high["dead_symbols"])
        low_count = len(result_low["dead_symbols"])
        assert low_count >= high_count

    def test_total_analysed_present(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_dead_code_v2(repo=repo, storage_path=store)
        assert "total_analysed" in result
        assert result["total_analysed"] >= 0

    def test_missing_repo_returns_error(self, tmp_path):
        result = get_dead_code_v2(repo="no_such_repo", storage_path=str(tmp_path))
        assert "error" in result

    def test_timing_present(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_dead_code_v2(repo=repo, storage_path=store)
        assert "_meta" in result
        assert "timing_ms" in result["_meta"]

    def test_orphan_file_functions_flagged(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = get_dead_code_v2(repo=repo, min_confidence=0.33, storage_path=store)
        dead_names = {s["name"] for s in result["dead_symbols"]}
        # orphan.py has no importers — orphan_fn should appear
        assert "orphan_fn" in dead_names

    def test_no_signals_field_values(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        valid_signals = {"unreachable_file", "no_callers", "not_barrel_exported"}
        result = get_dead_code_v2(repo=repo, min_confidence=0.1, storage_path=store)
        for sym in result["dead_symbols"]:
            for sig in sym["signals"]:
                assert sig in valid_signals
