"""Tests for JCODEMUNCH_PATH_MAP env var parsing and path remapping."""

import logging
import pytest

from jcodemunch_mcp.path_map import parse_path_map, ENV_VAR


def test_parse_unset(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert parse_path_map() == []


def test_parse_whitespace_only(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "   ")
    assert parse_path_map() == []


def test_parse_single_pair(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "/home/user=/mnt/user")
    assert parse_path_map() == [("/home/user", "/mnt/user")]


def test_parse_multiple_pairs(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "/a=/b,/c=/d")
    assert parse_path_map() == [("/a", "/b"), ("/c", "/d")]


def test_parse_equals_in_path(monkeypatch):
    """Last = is the separator; earlier = chars belong to the original path."""
    monkeypatch.setenv(ENV_VAR, "/home/user/a=b=/new/path")
    assert parse_path_map() == [("/home/user/a=b", "/new/path")]


def test_parse_malformed_no_equals_skipped(monkeypatch, caplog):
    monkeypatch.setenv(ENV_VAR, "/valid=/ok,noequalssign,/also=/fine")
    with caplog.at_level(logging.WARNING):
        result = parse_path_map()
    assert result == [("/valid", "/ok"), ("/also", "/fine")]
    assert any("noequalssign" in r.message for r in caplog.records)


def test_parse_empty_orig_skipped(monkeypatch, caplog):
    monkeypatch.setenv(ENV_VAR, "=/new/path")
    with caplog.at_level(logging.WARNING):
        result = parse_path_map()
    assert result == []
    assert len(caplog.records) >= 1


def test_parse_empty_new_skipped(monkeypatch, caplog):
    monkeypatch.setenv(ENV_VAR, "/old/path=")
    with caplog.at_level(logging.WARNING):
        result = parse_path_map()
    assert result == []
    assert len(caplog.records) >= 1


def test_parse_whitespace_stripped(monkeypatch):
    """Leading/trailing whitespace in tokens is stripped."""
    monkeypatch.setenv(ENV_VAR, " /home/user = /mnt/user ")
    assert parse_path_map() == [("/home/user", "/mnt/user")]


import os
from jcodemunch_mcp.path_map import remap


def test_remap_empty_pairs_returns_unchanged():
    """No mapping set: path returned unchanged (no separator normalisation)."""
    path = "/home/user/project/file.py"
    assert remap(path, []) == path


def test_remap_forward_replaces_prefix():
    pairs = [("/home/user", "C:\\Users\\user")]
    result = remap("/home/user/project/file.py", pairs)
    # Normalised with os.sep — on POSIX this is forward slash
    assert result.replace("\\", "/") == "C:/Users/user/project/file.py"


def test_remap_reverse_replaces_prefix():
    pairs = [("/home/user", "C:\\Users\\user")]
    result = remap("C:\\Users\\user\\project\\file.py", pairs, reverse=True)
    assert result.replace("\\", "/") == "/home/user/project/file.py"


def test_remap_no_match_returns_normalised():
    pairs = [("/home/other", "/mnt/other")]
    result = remap("/home/user/project", pairs)
    assert result.replace("\\", "/") == "/home/user/project"


def test_remap_first_pair_wins():
    pairs = [("/home/user", "/first"), ("/home/user", "/second")]
    result = remap("/home/user/file.py", pairs)
    assert result.replace("\\", "/") == "/first/file.py"


def test_remap_mixed_separators_in_input_match():
    """D:/Users/user (forward slashes) matches stored prefix D:\\Users\\user."""
    pairs = [("/home/user", "D:\\Users\\user")]
    result = remap("D:/Users/user/project", pairs, reverse=True)
    assert result.replace("\\", "/") == "/home/user/project"


def test_remap_multiple_pairs_correct_one_matches():
    pairs = [("/home/alice", "/mnt/alice"), ("/home/bob", "/mnt/bob")]
    result = remap("/home/bob/work/file.py", pairs)
    assert result.replace("\\", "/") == "/mnt/bob/work/file.py"


def test_remap_does_not_match_across_directory_boundary():
    pairs = [("/home/user", "/mnt/user")]
    result = remap("/home/username/file.py", pairs)
    assert result.replace("\\", "/") == "/home/username/file.py"


from pathlib import Path
from jcodemunch_mcp.tools.index_folder import index_folder
from jcodemunch_mcp.tools.list_repos import list_repos


def test_list_repos_source_root_remapped(tmp_path, monkeypatch):
    """source_root in list_repos response uses the remapped prefix."""
    # Create a minimal source file so index_folder has something to index
    (tmp_path / "hello.py").write_text("def hello(): pass\n")

    # Index the folder with AI summaries disabled
    monkeypatch.setenv("JCODEMUNCH_USE_AI_SUMMARIES", "false")
    storage = str(tmp_path / ".index")
    result = index_folder(
        path=str(tmp_path),
        storage_path=storage,
        use_ai_summaries=False,
    )
    assert result.get("success"), result

    # Set up a remap: tmp_path prefix → /remapped/prefix
    orig_prefix = str(tmp_path)
    new_prefix = "/remapped/prefix"
    monkeypatch.setenv(ENV_VAR, f"{orig_prefix}={new_prefix}")

    repos = list_repos(storage_path=storage)
    assert repos["count"] == 1
    source_root = repos["repos"][0]["source_root"]
    assert source_root.replace("\\", "/").startswith("/remapped/prefix"), (
        f"Expected remapped prefix, got: {source_root}"
    )


def test_repo_entry_from_data_source_root_remapped(monkeypatch):
    """_repo_entry_from_data remaps source_root (legacy JSON index path)."""
    from jcodemunch_mcp.storage.index_store import IndexStore

    monkeypatch.setenv(ENV_VAR, "/old/root=/new/root")
    store = IndexStore()

    data = {
        "repo": "local/myproject-abc12345",
        "indexed_at": "2026-01-01T00:00:00",
        "symbol_count": 10,
        "file_count": 5,
        "languages": {"python": 5},
        "index_version": 5,
        "source_root": "/old/root/myproject",
    }
    entry = store._repo_entry_from_data(data)
    assert entry is not None
    assert entry["source_root"].replace("\\", "/") == "/new/root/myproject"


def test_index_folder_reverse_remap_finds_existing_index(tmp_path, monkeypatch):
    """index_folder with a remapped path finds the existing index (no re-index)."""
    (tmp_path / "hello.py").write_text("def hello(): pass\n")
    monkeypatch.setenv("JCODEMUNCH_USE_AI_SUMMARIES", "false")
    storage = str(tmp_path / ".index")

    # Index using the real path (simulates "original machine" build)
    result = index_folder(
        path=str(tmp_path),
        storage_path=storage,
        use_ai_summaries=False,
    )
    assert result.get("success"), result

    # Simulate "current machine" using a different prefix
    # Create a real directory at the fake path so the file walk succeeds
    fake_parent = tmp_path.parent / "remapped_root"
    fake_parent.mkdir()
    fake_path_dir = fake_parent / tmp_path.name
    fake_path_dir.mkdir()
    (fake_path_dir / "hello.py").write_text("def hello(): pass\n")

    # ENV_VAR format: orig=new (stored prefix = current machine prefix)
    # The index was built with tmp_path.parent as the prefix ("original machine")
    # On "current machine" the same project is at fake_parent
    monkeypatch.setenv(ENV_VAR, f"{str(tmp_path.parent)}={str(fake_parent)}")

    # Call index_folder with the "current machine" path
    # Reverse remap: looks for new=fake_parent → replaces with orig=tmp_path.parent
    # → hash is computed as if path were tmp_path → matches stored hash!
    # File walk uses fake_path_dir (which exists and has same content)
    result2 = index_folder(
        path=str(fake_path_dir),
        storage_path=storage,
        use_ai_summaries=False,
        incremental=True,
    )
    assert result2.get("success"), result2
    assert result2.get("message") == "No changes detected" or result2.get("changed", 0) == 0, (
        f"Expected no changes, got: {result2}"
    )


def test_watcher_reverse_remap_produces_stored_hash(monkeypatch):
    """Applying reverse remap before _local_repo_id yields the same hash as the stored path.

    This verifies the logic used at both watcher touch points (_watch_single line 274
    and _stop_watching line 751): that a current-machine path remapped back to the
    stored prefix produces the same repo ID the index was built with.
    """
    from jcodemunch_mcp.watcher import _local_repo_id

    monkeypatch.setenv(ENV_VAR, "/real/project=/remapped/project")

    stored_id = _local_repo_id("/real/project")

    _pairs = parse_path_map()
    lookup_id = _local_repo_id(remap("/remapped/project", _pairs, reverse=True))

    assert lookup_id == stored_id, (
        f"Reverse-remapped path must produce same hash as stored path. "
        f"Expected {stored_id!r}, got {lookup_id!r}"
    )


def test_stop_watching_remap_produces_stored_hash(monkeypatch):
    """The reverse remap in _stop_watching produces the same hash as the original indexed path.

    _stop_watching is a closure inside watch() and cannot be called directly.
    This test verifies the underlying remap+hash logic it uses (line 751).
    """
    from jcodemunch_mcp.watcher import _local_repo_id

    monkeypatch.setenv(ENV_VAR, "/stored/root=/current/root")

    original_id = _local_repo_id("/stored/root/myproject")

    _pairs = parse_path_map()
    cleanup_id = _local_repo_id(remap("/current/root/myproject", _pairs, reverse=True))

    assert cleanup_id == original_id, (
        f"_stop_watching reverse remap must match stored hash. "
        f"Expected {original_id!r}, got {cleanup_id!r}"
    )
