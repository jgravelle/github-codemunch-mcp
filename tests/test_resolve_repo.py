"""Tests for resolve_repo tool."""

import hashlib

import pytest

from jcodemunch_mcp.tools.resolve_repo import resolve_repo, _compute_repo_id
from jcodemunch_mcp.watcher import _local_repo_id
from jcodemunch_mcp.tools.index_folder import index_folder


class TestComputeRepoId:
    def test_deterministic_id_matches_local_repo_id(self, tmp_path):
        """_compute_repo_id must produce the same ID as _local_repo_id."""
        folder = tmp_path / "my-project"
        folder.mkdir()
        from pathlib import Path
        assert _compute_repo_id(Path(folder)) == _local_repo_id(str(folder))

    def test_different_paths_produce_different_ids(self, tmp_path):
        left = tmp_path / "left" / "shared"
        right = tmp_path / "right" / "shared"
        left.mkdir(parents=True)
        right.mkdir(parents=True)
        from pathlib import Path
        assert _compute_repo_id(Path(left)) != _compute_repo_id(Path(right))


class TestResolveRepo:
    def test_resolve_exact_indexed_root(self, tmp_path):
        """Resolving an indexed root returns indexed: true with metadata."""
        project = tmp_path / "myproject"
        project.mkdir()
        (project / "main.py").write_text("def hello(): pass\n")
        store_path = str(tmp_path / "store")

        index_folder(str(project), use_ai_summaries=False, storage_path=store_path)

        result = resolve_repo(str(project), storage_path=store_path)
        assert result["found"] is True
        assert result["indexed"] is True
        assert result["repo"].startswith("local/myproject-")
        assert result["symbol_count"] >= 1
        assert result["file_count"] >= 1
        assert "hint" not in result

    def test_resolve_subdirectory_via_git(self, tmp_path, monkeypatch):
        """Resolving a subdirectory finds the repo via git root."""
        import subprocess
        project = tmp_path / "gitrepo"
        project.mkdir()
        subprocess.run(["git", "init"], cwd=str(project), capture_output=True)
        subdir = project / "src" / "pkg"
        subdir.mkdir(parents=True)
        (project / "main.py").write_text("def top(): pass\n")
        store_path = str(tmp_path / "store")

        index_folder(str(project), use_ai_summaries=False, storage_path=store_path)

        result = resolve_repo(str(subdir), storage_path=store_path)
        assert result["found"] is True
        assert result["indexed"] is True
        assert result["repo"].startswith("local/gitrepo-")

    def test_resolve_non_indexed_path(self, tmp_path):
        """Non-indexed path returns indexed: false with hint."""
        project = tmp_path / "unindexed"
        project.mkdir()
        store_path = str(tmp_path / "store")

        result = resolve_repo(str(project), storage_path=store_path)
        assert result["found"] is True
        assert result["indexed"] is False
        assert "repo" in result
        assert result["hint"] == "call index_folder to index this path"

    def test_resolve_nonexistent_path(self, tmp_path):
        """Nonexistent path returns found: false with error."""
        result = resolve_repo(str(tmp_path / "does-not-exist"))
        assert result["found"] is False
        assert result["indexed"] is False
        assert "error" in result

    def test_resolve_file_uses_parent(self, tmp_path):
        """Resolving a file path uses its parent directory."""
        project = tmp_path / "filetest"
        project.mkdir()
        pyfile = project / "app.py"
        pyfile.write_text("def run(): pass\n")
        store_path = str(tmp_path / "store")

        index_folder(str(project), use_ai_summaries=False, storage_path=store_path)

        result = resolve_repo(str(pyfile), storage_path=store_path)
        assert result["found"] is True
        assert result["indexed"] is True
        assert result["repo"].startswith("local/filetest-")

    def test_result_has_timing(self, tmp_path):
        """Result always includes _meta with timing_ms."""
        result = resolve_repo(str(tmp_path))
        assert "_meta" in result
        assert "timing_ms" in result["_meta"]
