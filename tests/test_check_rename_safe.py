"""Tests for check_rename_safe tool."""

import pytest
from jcodemunch_mcp.tools.check_rename_safe import check_rename_safe
from jcodemunch_mcp.tools.index_folder import index_folder


def _build_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    store = tmp_path / "store"
    store.mkdir()

    (src / "utils.py").write_text(
        "def helper():\n    return 42\n\ndef other():\n    return 0\n"
    )
    (src / "main.py").write_text(
        "from utils import helper\n\nresult = helper()\n"
    )
    (src / "cli.py").write_text(
        "from main import result\nfrom utils import other\nprint(result)\n"
    )

    r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
    assert r["success"] is True
    return r["repo"], str(store)


class TestCheckRenameSafe:
    def test_safe_rename_returns_true(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = check_rename_safe(
            repo=repo, symbol_id="helper", new_name="compute", storage_path=store
        )
        assert result.get("safe") is True
        assert result["conflicts"] == []
        assert result["checked_files"] >= 1

    def test_collision_detected(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        # Renaming "helper" to "other" would collide (other already exists in utils.py)
        result = check_rename_safe(
            repo=repo, symbol_id="helper", new_name="other", storage_path=store
        )
        assert result.get("safe") is False
        assert len(result["conflicts"]) >= 1
        names = [c["existing_name"] for c in result["conflicts"]]
        assert "other" in names

    def test_missing_symbol_returns_error(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = check_rename_safe(
            repo=repo, symbol_id="nonexistent_symbol_xyz", new_name="foo", storage_path=store
        )
        assert "error" in result

    def test_missing_repo_returns_error(self, tmp_path):
        store = str(tmp_path / "empty_store")
        result = check_rename_safe(repo="no_such_repo", symbol_id="x", new_name="y", storage_path=store)
        assert "error" in result

    def test_result_includes_symbol_info(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = check_rename_safe(
            repo=repo, symbol_id="helper", new_name="foo", storage_path=store
        )
        assert "symbol" in result
        assert result["symbol"]["name"] == "helper"
        assert result["new_name"] == "foo"

    def test_timing_present(self, tmp_path):
        repo, store = _build_repo(tmp_path)
        result = check_rename_safe(
            repo=repo, symbol_id="helper", new_name="foo", storage_path=store
        )
        assert "_meta" in result
        assert "timing_ms" in result["_meta"]
