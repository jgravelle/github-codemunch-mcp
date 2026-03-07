"""Tests for token tracker behavior and path consistency."""

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "jcodemunch_mcp" / "storage" / "token_tracker.py"
SPEC = importlib.util.spec_from_file_location("token_tracker_module", MODULE_PATH)
TOKEN_TRACKER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(TOKEN_TRACKER)


def test_savings_report_uses_code_index_path_env(monkeypatch, tmp_path):
    """When CODE_INDEX_PATH is set, record/report should use the same savings file."""
    monkeypatch.setenv("CODE_INDEX_PATH", str(tmp_path))

    total = TOKEN_TRACKER.record_savings(123)
    report = TOKEN_TRACKER.get_savings_report()

    assert total == 123
    assert report["total_tokens_saved"] == 123
    assert report["savings_file"] == str(tmp_path / "_savings.json")
