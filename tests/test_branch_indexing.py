"""Tests for branch-aware delta-layered indexing (v1.50.0).

Covers:
- Branch delta save/load/compose/delete
- Cache key includes branch
- list_branches / list_repos branch info
- Stale delta detection
- Non-git folder graceful degradation
- _get_git_branch helper
"""

import json
import sqlite3
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from jcodemunch_mcp.parser.symbols import Symbol
from jcodemunch_mcp.storage.index_store import (
    CodeIndex,
    INDEX_VERSION,
    _get_git_branch,
)
from jcodemunch_mcp.storage.sqlite_store import (
    SQLiteIndexStore,
    _cache_clear,
    _cache_get,
    _cache_put,
    _db_mtime_ns,
)


# ── Helpers ────────────────────────────────────────────────────────


def _make_symbol(name: str, file: str, line: int = 1) -> Symbol:
    """Create a minimal Symbol for testing."""
    return Symbol(
        id=f"{file}:{name}",
        file=file,
        name=name,
        qualified_name=name,
        kind="function",
        language="python",
        signature=f"def {name}():",
        docstring="",
        summary=f"Summary of {name}",
        decorators=[],
        keywords=[],
        parent=None,
        line=line,
        end_line=line + 5,
        byte_offset=0,
        byte_length=50,
        content_hash="abc123",
    )


def _save_base_index(store: SQLiteIndexStore, owner: str = "local", name: str = "test-repo"):
    """Save a minimal base index for testing."""
    syms = [
        _make_symbol("foo", "src/main.py", 1),
        _make_symbol("bar", "src/utils.py", 1),
        _make_symbol("baz", "src/utils.py", 10),
    ]
    return store.save_index(
        owner=owner, name=name,
        source_files=["src/main.py", "src/utils.py"],
        symbols=syms,
        raw_files={"src/main.py": "def foo(): pass", "src/utils.py": "def bar(): pass\ndef baz(): pass"},
        file_hashes={"src/main.py": "hash_main", "src/utils.py": "hash_utils"},
        git_head="aaa111",
        source_root="/tmp/test-repo",
        file_languages={"src/main.py": "python", "src/utils.py": "python"},
    )


# ── Tests ──────────────────────────────────────────────────────────


class TestBranchDeltaSaveLoad:
    """save_branch_delta / load_branch_delta round-trip."""

    def test_save_and_load_branch_delta(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        _save_base_index(store)

        # Simulate a branch where src/main.py was modified and src/new.py was added
        new_sym = _make_symbol("qux", "src/new.py", 1)
        mod_sym = _make_symbol("foo_v2", "src/main.py", 1)

        store.save_branch_delta(
            owner="local", name="test-repo", branch="feature/add-qux",
            changed_files=["src/main.py"],
            new_files=["src/new.py"],
            deleted_files=[],
            new_symbols=[mod_sym, new_sym],
            raw_files={"src/main.py": "def foo_v2(): pass", "src/new.py": "def qux(): pass"},
            git_head="bbb222",
            base_head="aaa111",
            file_hashes={"src/main.py": "hash_main_v2", "src/new.py": "hash_new"},
            file_languages={"src/main.py": "python", "src/new.py": "python"},
        )

        delta = store.load_branch_delta("local", "test-repo", "feature/add-qux")
        assert delta is not None
        assert delta["branch"] == "feature/add-qux"
        assert delta["git_head"] == "bbb222"
        assert delta["base_head"] == "aaa111"
        assert len(delta["files"]) == 2

        # Check file entries
        files_by_path = {f["file"]: f for f in delta["files"]}
        assert "src/main.py" in files_by_path
        assert files_by_path["src/main.py"]["action"] == "modify"
        assert "src/new.py" in files_by_path
        assert files_by_path["src/new.py"]["action"] == "add"

    def test_load_nonexistent_branch_returns_none(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        _save_base_index(store)

        delta = store.load_branch_delta("local", "test-repo", "nonexistent")
        assert delta is None

    def test_deleted_files_in_delta(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        _save_base_index(store)

        store.save_branch_delta(
            owner="local", name="test-repo", branch="cleanup",
            changed_files=[], new_files=[],
            deleted_files=["src/utils.py"],
            new_symbols=[], raw_files={},
            git_head="ccc333", base_head="aaa111",
        )

        delta = store.load_branch_delta("local", "test-repo", "cleanup")
        assert len(delta["files"]) == 1
        assert delta["files"][0]["action"] == "delete"
        assert delta["files"][0]["file"] == "src/utils.py"


class TestBranchCompose:
    """compose_branch_index correctly overlays delta on base."""

    def test_compose_adds_new_file(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        base = _save_base_index(store)

        delta = {
            "git_head": "bbb222",
            "base_head": "aaa111",
            "indexed_at": "2026-04-15T00:00:00",
            "files": [
                {
                    "file": "src/new.py",
                    "action": "add",
                    "symbols": [{"id": "src/new.py:qux", "file": "src/new.py", "name": "qux",
                                 "kind": "function", "language": "python", "signature": "def qux():",
                                 "summary": "", "docstring": "", "qualified_name": "qux",
                                 "decorators": [], "keywords": [], "parent": None,
                                 "line": 1, "end_line": 5, "byte_offset": 0, "byte_length": 20,
                                 "content_hash": "", "ecosystem_context": "",
                                 "cyclomatic": 0, "max_nesting": 0, "param_count": 0,
                                 "call_references": []}],
                    "hash": "hash_new",
                    "language": "python",
                },
            ],
        }

        composed = store.compose_branch_index(base, "feature/add", delta)
        assert "src/new.py" in composed.source_files
        assert len(composed.symbols) == 4  # 3 base + 1 new
        assert composed.branch == "feature/add"
        assert composed.git_head == "bbb222"

    def test_compose_deletes_file(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        base = _save_base_index(store)

        delta = {
            "git_head": "ccc333",
            "base_head": "aaa111",
            "indexed_at": "2026-04-15T00:00:00",
            "files": [
                {"file": "src/utils.py", "action": "delete"},
            ],
        }

        composed = store.compose_branch_index(base, "cleanup", delta)
        assert "src/utils.py" not in composed.source_files
        # bar and baz were in utils.py — should be removed
        sym_names = [s["name"] for s in composed.symbols]
        assert "bar" not in sym_names
        assert "baz" not in sym_names
        assert "foo" in sym_names
        assert len(composed.symbols) == 1

    def test_compose_modifies_file(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        base = _save_base_index(store)

        delta = {
            "git_head": "ddd444",
            "base_head": "aaa111",
            "indexed_at": "2026-04-15T00:00:00",
            "files": [
                {
                    "file": "src/main.py",
                    "action": "modify",
                    "symbols": [{"id": "src/main.py:foo_v2", "file": "src/main.py", "name": "foo_v2",
                                 "kind": "function", "language": "python", "signature": "def foo_v2():",
                                 "summary": "", "docstring": "", "qualified_name": "foo_v2",
                                 "decorators": [], "keywords": [], "parent": None,
                                 "line": 1, "end_line": 5, "byte_offset": 0, "byte_length": 20,
                                 "content_hash": "", "ecosystem_context": "",
                                 "cyclomatic": 0, "max_nesting": 0, "param_count": 0,
                                 "call_references": []}],
                    "hash": "hash_main_v2",
                },
            ],
        }

        composed = store.compose_branch_index(base, "refactor", delta)
        sym_names = [s["name"] for s in composed.symbols]
        assert "foo" not in sym_names  # old symbol removed
        assert "foo_v2" in sym_names   # new symbol added
        assert "bar" in sym_names      # untouched
        assert "baz" in sym_names      # untouched
        assert len(composed.symbols) == 3


class TestBranchLoadIndex:
    """load_index with branch param composes delta automatically."""

    def test_load_index_with_branch_composes_delta(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        _save_base_index(store)

        new_sym = _make_symbol("qux", "src/new.py", 1)
        store.save_branch_delta(
            owner="local", name="test-repo", branch="feature/x",
            changed_files=[], new_files=["src/new.py"], deleted_files=[],
            new_symbols=[new_sym],
            raw_files={"src/new.py": "def qux(): pass"},
            git_head="bbb222", base_head="aaa111",
            file_hashes={"src/new.py": "hash_new"},
            file_languages={"src/new.py": "python"},
        )

        _cache_clear()
        composed = store.load_index("local", "test-repo", branch="feature/x")
        assert composed is not None
        assert composed.branch == "feature/x"
        assert "src/new.py" in composed.source_files
        assert len(composed.symbols) == 4  # 3 base + 1 new

    def test_load_index_without_branch_returns_base(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        _save_base_index(store)

        new_sym = _make_symbol("qux", "src/new.py", 1)
        store.save_branch_delta(
            owner="local", name="test-repo", branch="feature/x",
            changed_files=[], new_files=["src/new.py"], deleted_files=[],
            new_symbols=[new_sym],
            raw_files={"src/new.py": "def qux(): pass"},
            git_head="bbb222", base_head="aaa111",
        )

        _cache_clear()
        base = store.load_index("local", "test-repo")
        assert base is not None
        assert base.branch == ""
        assert "src/new.py" not in base.source_files
        assert len(base.symbols) == 3


class TestBranchCache:
    """Cache key includes branch — different branches get different cache entries."""

    def test_cache_separates_branches(self, tmp_path):
        _cache_clear()
        store = SQLiteIndexStore(base_path=str(tmp_path))
        base = _save_base_index(store)

        new_sym = _make_symbol("qux", "src/new.py", 1)
        store.save_branch_delta(
            owner="local", name="test-repo", branch="feature/x",
            changed_files=[], new_files=["src/new.py"], deleted_files=[],
            new_symbols=[new_sym],
            raw_files={"src/new.py": "def qux(): pass"},
            git_head="bbb222", base_head="aaa111",
        )

        _cache_clear()

        # Load base
        idx_base = store.load_index("local", "test-repo")
        # Load branch
        idx_branch = store.load_index("local", "test-repo", branch="feature/x")

        assert idx_base is not None
        assert idx_branch is not None
        assert len(idx_base.symbols) == 3
        assert len(idx_branch.symbols) == 4

        # Second load should come from cache
        idx_base_2 = store.load_index("local", "test-repo")
        idx_branch_2 = store.load_index("local", "test-repo", branch="feature/x")

        assert len(idx_base_2.symbols) == 3
        assert len(idx_branch_2.symbols) == 4


class TestListBranches:
    """list_branches returns metadata for all indexed branches."""

    def test_list_branches_empty(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        _save_base_index(store)
        assert store.list_branches("local", "test-repo") == []

    def test_list_branches_with_delta(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        _save_base_index(store)

        store.save_branch_delta(
            owner="local", name="test-repo", branch="feature/a",
            changed_files=["src/main.py"], new_files=[], deleted_files=[],
            new_symbols=[_make_symbol("foo_v2", "src/main.py")],
            raw_files={"src/main.py": "def foo_v2(): pass"},
            git_head="bbb222", base_head="aaa111",
        )

        branches = store.list_branches("local", "test-repo")
        assert len(branches) == 1
        assert branches[0]["branch"] == "feature/a"
        assert branches[0]["git_head"] == "bbb222"
        assert branches[0]["delta_file_count"] == 1


class TestDeleteBranchDelta:
    """delete_branch_delta removes a branch's delta data."""

    def test_delete_branch_delta(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        _save_base_index(store)

        store.save_branch_delta(
            owner="local", name="test-repo", branch="feature/a",
            changed_files=[], new_files=["src/new.py"], deleted_files=[],
            new_symbols=[_make_symbol("qux", "src/new.py")],
            raw_files={"src/new.py": "def qux(): pass"},
            git_head="bbb222", base_head="aaa111",
        )

        assert store.delete_branch_delta("local", "test-repo", "feature/a")
        assert store.load_branch_delta("local", "test-repo", "feature/a") is None
        assert store.list_branches("local", "test-repo") == []

    def test_delete_nonexistent_branch(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        _save_base_index(store)
        assert not store.delete_branch_delta("local", "test-repo", "nonexistent")


class TestListReposBranches:
    """list_repos includes branch info."""

    def test_list_repos_shows_branches(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        _save_base_index(store)

        store.save_branch_delta(
            owner="local", name="test-repo", branch="feature/a",
            changed_files=[], new_files=["src/new.py"], deleted_files=[],
            new_symbols=[_make_symbol("qux", "src/new.py")],
            raw_files={"src/new.py": "def qux(): pass"},
            git_head="bbb222", base_head="aaa111",
        )

        repos = store.list_repos()
        assert len(repos) == 1
        assert "branches" in repos[0]
        assert repos[0]["branches"][0]["branch"] == "feature/a"


class TestStaleDelta:
    """Stale delta warning when base has been re-indexed since delta was created."""

    def test_stale_delta_logs_warning(self, tmp_path, caplog):
        store = SQLiteIndexStore(base_path=str(tmp_path))
        _save_base_index(store)

        store.save_branch_delta(
            owner="local", name="test-repo", branch="feature/a",
            changed_files=[], new_files=["src/new.py"], deleted_files=[],
            new_symbols=[_make_symbol("qux", "src/new.py")],
            raw_files={"src/new.py": "def qux(): pass"},
            git_head="bbb222", base_head="old_base_head",  # mismatches base's aaa111
        )

        _cache_clear()
        import logging
        with caplog.at_level(logging.WARNING):
            composed = store.load_index("local", "test-repo", branch="feature/a")

        assert composed is not None
        assert any("stale" in r.message.lower() for r in caplog.records)


class TestMigrationV8ToV9:
    """v8→v9 migration creates branch tables."""

    def test_migration_creates_tables(self, tmp_path):
        # Create a v8 database manually
        db_path = tmp_path / "local-test.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""\
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE symbols (id TEXT PRIMARY KEY, file TEXT, name TEXT,
                kind TEXT, signature TEXT, summary TEXT, docstring TEXT,
                line INTEGER, end_line INTEGER, byte_offset INTEGER,
                byte_length INTEGER, parent TEXT, qualified_name TEXT,
                language TEXT, decorators TEXT, keywords TEXT,
                content_hash TEXT, ecosystem_context TEXT, data TEXT,
                cyclomatic INTEGER, max_nesting INTEGER, param_count INTEGER);
            CREATE TABLE files (path TEXT PRIMARY KEY, hash TEXT, mtime_ns INTEGER,
                language TEXT, summary TEXT, blob_sha TEXT, imports TEXT, size_bytes INTEGER);
        """)
        conn.execute("INSERT INTO meta VALUES ('index_version', '8')")
        conn.commit()
        conn.close()

        # Opening via SQLiteIndexStore triggers migration
        store = SQLiteIndexStore(base_path=str(tmp_path))
        conn = store._connect(db_path)
        try:
            # Verify branch tables exist
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            assert "branch_deltas" in tables
            assert "branch_meta" in tables

            # Verify version was updated
            version = conn.execute(
                "SELECT value FROM meta WHERE key='index_version'"
            ).fetchone()[0]
            assert version == "9"
        finally:
            conn.close()


class TestGetGitBranch:
    """_get_git_branch helper."""

    def test_returns_branch_in_git_repo(self, tmp_path):
        # Create a minimal git repo
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "checkout", "-b", "main"], cwd=str(tmp_path), capture_output=True)
        # Need at least one commit for HEAD to exist
        (tmp_path / "README.md").write_text("test")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init", "--allow-empty"],
            cwd=str(tmp_path), capture_output=True,
            env={**__import__("os").environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"},
        )

        branch = _get_git_branch(tmp_path)
        assert branch == "main"

    def test_returns_none_for_non_git(self, tmp_path):
        branch = _get_git_branch(tmp_path)
        assert branch is None

    def test_returns_sha_for_detached_head(self, tmp_path):
        # Create repo with a commit, then detach
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "README.md").write_text("test")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        env = {**__import__("os").environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
               "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"}
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, env=env)
        # Get HEAD SHA before detaching
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tmp_path), capture_output=True, text=True
        ).stdout.strip()
        subprocess.run(["git", "checkout", "--detach"], cwd=str(tmp_path), capture_output=True)

        branch = _get_git_branch(tmp_path)
        assert branch == head


class TestNonGitFolderGraceful:
    """Non-git folders skip branch awareness entirely."""

    def test_non_git_folder_indexes_normally(self, tmp_path):
        store = SQLiteIndexStore(base_path=str(tmp_path / "store"))
        # No git repo — branch detection returns None, so no delta mode
        index = _save_base_index(store)
        assert index is not None
        assert index.branch == ""
        assert len(index.symbols) == 3


class TestCodeIndexBranchField:
    """CodeIndex dataclass includes branch field."""

    def test_branch_field_default_empty(self):
        idx = CodeIndex(
            repo="test/repo", owner="test", name="repo",
            indexed_at="2026-04-15T00:00:00",
            source_files=[], languages={}, symbols=[],
        )
        assert idx.branch == ""

    def test_branch_field_set(self):
        idx = CodeIndex(
            repo="test/repo", owner="test", name="repo",
            indexed_at="2026-04-15T00:00:00",
            source_files=[], languages={}, symbols=[],
            branch="feature/x",
        )
        assert idx.branch == "feature/x"
