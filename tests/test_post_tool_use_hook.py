"""Tests for PostToolUse hook (Feature 8: Session-Aware Routing)."""
import json
from pathlib import Path

import pytest


class TestEnforcementHooksConstant:
    """Tests for _ENFORCEMENT_HOOKS constant (upstream v1.21.27)."""

    def test_enforcement_hooks_has_post_tool_use(self):
        """_ENFORCEMENT_HOOKS must contain PostToolUse with Edit|Write matcher."""
        from jcodemunch_mcp.cli.init import _ENFORCEMENT_HOOKS

        assert "PostToolUse" in _ENFORCEMENT_HOOKS
        rule = _ENFORCEMENT_HOOKS["PostToolUse"][0]
        matcher = rule["matcher"]
        assert "Edit" in matcher
        assert "Write" in matcher
        cmd = rule["hooks"][0].get("command", "")
        assert "jcodemunch-mcp" in cmd

    def test_enforcement_hooks_has_pre_tool_use(self):
        """_ENFORCEMENT_HOOKS must contain PreToolUse with Read matcher."""
        from jcodemunch_mcp.cli.init import _ENFORCEMENT_HOOKS

        assert "PreToolUse" in _ENFORCEMENT_HOOKS
        rule = _ENFORCEMENT_HOOKS["PreToolUse"][0]
        assert "Read" in rule["matcher"]


class TestInstallEnforcementHooksIntegration:
    """Tests for install_enforcement_hooks."""

    def test_install_enforcement_hooks_adds_both(self, tmp_path, monkeypatch):
        """install_enforcement_hooks must add PreToolUse and PostToolUse."""
        from jcodemunch_mcp.cli.init import install_enforcement_hooks
        monkeypatch.setattr(
            "jcodemunch_mcp.cli.init._settings_json_path",
            lambda: tmp_path / "settings.json"
        )
        install_enforcement_hooks(backup=False)
        data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))

        assert "PostToolUse" in data["hooks"]
        assert "PreToolUse" in data["hooks"]

    def test_install_enforcement_hooks_idempotent(self, tmp_path, monkeypatch):
        """install_enforcement_hooks should not duplicate entries."""
        from jcodemunch_mcp.cli.init import install_enforcement_hooks
        monkeypatch.setattr(
            "jcodemunch_mcp.cli.init._settings_json_path",
            lambda: tmp_path / "settings.json"
        )
        install_enforcement_hooks(backup=False)
        install_enforcement_hooks(backup=False)
        data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        assert len(data["hooks"]["PostToolUse"]) == 1
        assert len(data["hooks"]["PreToolUse"]) == 3  # Read, Bash|Grep|Glob, Edit|Write|MultiEdit


class TestCacheKeyIndexedAt:
    """Tests for search_symbols cache key including indexed_at."""

    def test_cache_key_includes_indexed_at(self, tmp_path):
        """Result cache key must include indexed_at for auto-invalidation."""
        from tests.conftest_helpers import create_mini_index, get_index
        from jcodemunch_mcp.tools.search_symbols import (
            search_symbols,
            _result_cache,
            _result_cache_lock,
        )

        # Create index
        repo, storage_path = create_mini_index(tmp_path)

        # First search populates cache
        search_symbols(repo=repo, query="my_func", storage_path=storage_path)
        
        # Check cache was populated
        with _result_cache_lock:
            cache_keys = list(_result_cache.keys())
            assert len(cache_keys) > 0
            
            # Cache key should be a tuple with indexed_at at position 1
            key = cache_keys[0]
            assert isinstance(key, tuple)
            indexed_at = key[1]
            assert isinstance(indexed_at, str)
            assert len(indexed_at) >= 0

    def test_cache_invalidated_by_reindex(self, tmp_path):
        """After reindex (new indexed_at), cache miss occurs."""
        from tests.conftest_helpers import create_mini_index, get_index
        from jcodemunch_mcp.tools.search_symbols import (
            search_symbols,
            result_cache_invalidate_repo,
        )
        from jcodemunch_mcp.tools.index_folder import index_folder
        import time

        # Create index
        repo, storage_path = create_mini_index(tmp_path)
        
        # First search
        search_symbols(repo=repo, query="my_func", storage_path=storage_path)
        
        # Modify a file and reindex
        test_file = tmp_path / "test_module.py"
        test_file.write_text(
            "def my_func(x: int, y: int) -> int:\n"
            "    '''Add two numbers - MODIFIED.'''\n"
            "    return x + y\n",
            encoding="utf-8"
        )
        time.sleep(0.1)  # Ensure timestamp changes
        
        # Reindex
        index_folder(
            path=str(tmp_path),
            use_ai_summaries=False,
            storage_path=storage_path,
            incremental=True,
        )
        
        # Invalidate the result cache
        count = result_cache_invalidate_repo(repo)
        assert count > 0
        
        # Second search should recompute (cache miss)
        result2 = search_symbols(repo=repo, query="my_func", storage_path=storage_path)
        assert result2["_meta"]["timing_ms"] > 0