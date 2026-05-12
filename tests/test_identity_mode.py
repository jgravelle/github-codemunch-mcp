"""Tests for local-first index identity mode selection."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from jcodemunch_mcp import config as config_module
from jcodemunch_mcp.storage import IndexStore
from jcodemunch_mcp.storage import git_root


def _git(*args, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _set_origin(path: Path, url: str) -> None:
    _git("remote", "add", "origin", url, cwd=path)


def test_default_config_for_hosted_clone_is_local_without_git_subprocess(tmp_path, monkeypatch):
    repo = tmp_path / "kibana-clone"
    repo.mkdir()
    _git("init", cwd=repo)
    _set_origin(repo, "https://github.com/elastic/kibana.git")
    monkeypatch.setattr(
        config_module,
        "get",
        lambda key, default=None, repo=None: None if key == "identity_mode" else False if key == "git_root_identity" else default,
    )

    store = IndexStore(base_path=str(tmp_path / "store"))
    with patch.object(git_root.subprocess, "run", side_effect=AssertionError("git subprocess fired")):
        decision = git_root.resolve_index_identity(str(repo), mode="config", store=store)

    assert decision.mode == "local"
    assert decision.owner == "local"
    assert decision.name.startswith("kibana-clone-")
    assert decision.git_root == ""
    assert decision.walk_root == str(repo.resolve())


def test_default_config_for_non_git_path_does_not_scan_repos(tmp_path, monkeypatch):
    project = tmp_path / "plain-project"
    project.mkdir()
    monkeypatch.setattr(
        config_module,
        "get",
        lambda key, default=None, repo=None: None if key == "identity_mode" else False if key == "git_root_identity" else default,
    )

    class Status:
        index_present = False

    class Store:
        def inspect_index(self, owner, name):
            return Status()

        def list_repos(self):
            pytest.fail("repo list scan used")

    decision = git_root.resolve_index_identity(str(project), mode="config", store=Store())

    assert decision.mode == "local"
    assert decision.owner == "local"
    assert decision.name.startswith("plain-project-")


def test_explicit_git_mode_blocked_by_local_index_without_repo_scan(tmp_path):
    project = tmp_path / "plain-project"
    project.mkdir()

    class Status:
        index_present = True

    class Store:
        def inspect_index(self, owner, name):
            return Status()

        def list_repos(self):
            pytest.fail("repo list scan used")

    with pytest.raises(git_root.IdentityModeConflict):
        git_root.resolve_index_identity(str(project), mode="git", store=Store())


def test_explicit_git_mode_uses_origin_identity(tmp_path):
    repo = tmp_path / "kibana-clone"
    repo.mkdir()
    _git("init", cwd=repo)
    _set_origin(repo, "https://github.com/elastic/kibana.git")

    decision = git_root.resolve_index_identity(
        str(repo),
        mode="git",
        store=IndexStore(base_path=str(tmp_path / "store")),
    )

    assert decision.mode == "git"
    assert decision.owner == "elastic"
    assert decision.name == "kibana"
    assert decision.git_root == str(repo.resolve())
    assert decision.walk_root == str(repo.resolve())


def test_existing_git_index_is_preserved_in_config_mode(tmp_path):
    from jcodemunch_mcp.tools.index_folder import index_folder

    repo = tmp_path / "kibana-clone"
    repo.mkdir()
    _git("init", cwd=repo)
    _set_origin(repo, "https://github.com/elastic/kibana.git")
    (repo / "main.py").write_text("def hello(): pass\n", encoding="utf-8")

    store_path = tmp_path / "store"
    first = index_folder(
        str(repo),
        use_ai_summaries=False,
        storage_path=str(store_path),
        context_providers=False,
        identity_mode="git",
    )
    assert first["success"] is True
    assert first["repo"] == "elastic/kibana"

    decision = git_root.resolve_index_identity(
        str(repo),
        mode="config",
        store=IndexStore(base_path=str(store_path)),
    )

    assert decision.mode == "git"
    assert decision.owner == "elastic"
    assert decision.name == "kibana"


def test_existing_git_index_is_preserved_without_full_index_load(tmp_path, monkeypatch):
    from jcodemunch_mcp.tools.index_folder import index_folder

    repo = tmp_path / "kibana-clone"
    repo.mkdir()
    _git("init", cwd=repo)
    _set_origin(repo, "https://github.com/elastic/kibana.git")
    (repo / "main.py").write_text("def hello(): pass\n", encoding="utf-8")

    store_path = tmp_path / "store"
    first = index_folder(
        str(repo),
        use_ai_summaries=False,
        storage_path=str(store_path),
        context_providers=False,
        identity_mode="git",
    )
    assert first["success"] is True

    store = IndexStore(base_path=str(store_path))
    monkeypatch.setattr(store, "load_index", lambda *args, **kwargs: pytest.fail("full index load used"))

    decision = git_root.resolve_index_identity(str(repo), mode="config", store=store)

    assert decision.mode == "git"
    assert decision.owner == "elastic"
    assert decision.name == "kibana"


def test_existing_local_index_blocks_explicit_git_mode(tmp_path):
    from jcodemunch_mcp.tools.index_folder import index_folder

    repo = tmp_path / "kibana-clone"
    repo.mkdir()
    _git("init", cwd=repo)
    _set_origin(repo, "https://github.com/elastic/kibana.git")
    (repo / "main.py").write_text("def hello(): pass\n", encoding="utf-8")

    store_path = tmp_path / "store"
    first = index_folder(
        str(repo),
        use_ai_summaries=False,
        storage_path=str(store_path),
        context_providers=False,
        identity_mode="local",
    )
    assert first["success"] is True
    assert first["repo"].startswith("local/kibana-clone-")

    second = index_folder(
        str(repo),
        use_ai_summaries=False,
        storage_path=str(store_path),
        context_providers=False,
        identity_mode="git",
    )

    assert second["success"] is False
    assert "Existing index" in second["error"]
    assert "invalidate" in second["error"]


def test_existing_git_index_blocks_explicit_local_mode(tmp_path):
    from jcodemunch_mcp.tools.index_folder import index_folder

    repo = tmp_path / "kibana-clone"
    repo.mkdir()
    _git("init", cwd=repo)
    _set_origin(repo, "https://github.com/elastic/kibana.git")
    (repo / "main.py").write_text("def hello(): pass\n", encoding="utf-8")

    store_path = tmp_path / "store"
    first = index_folder(
        str(repo),
        use_ai_summaries=False,
        storage_path=str(store_path),
        context_providers=False,
        identity_mode="git",
    )
    assert first["success"] is True
    assert first["repo"] == "elastic/kibana"

    second = index_folder(
        str(repo),
        use_ai_summaries=False,
        storage_path=str(store_path),
        context_providers=False,
        identity_mode="local",
    )

    assert second["success"] is False
    assert "Existing index" in second["error"]
    assert "invalidate" in second["error"]


def test_both_identity_forms_are_ambiguous(tmp_path):
    repo = tmp_path / "kibana-clone"
    repo.mkdir()
    _git("init", cwd=repo)

    class Status:
        index_present = True

    class Store:
        def inspect_index(self, owner, name):
            assert owner == "local"
            assert name.startswith(repo.name)
            return Status()

        def list_repos(self):
            return [{"repo": "elastic/kibana", "git_root": str(repo.resolve())}]

        def load_index(self, *args, **kwargs):
            pytest.fail("full index load used")

    with pytest.raises(git_root.IdentityModeAmbiguous):
        git_root.resolve_index_identity(str(repo), mode="config", store=Store())


def test_config_template_exposes_git_identity_opt_in():
    template = config_module.generate_template()

    assert '// "identity_mode": "git",' in template
    assert '"local" (default)' in template
    assert '"git"' in template
    assert "Existing indexes keep their current identity" in template
    assert '// "git_root_identity": true,' in template


def test_watcher_and_resolve_repo_delegate_to_identity_resolver(tmp_path):
    from jcodemunch_mcp.tools.resolve_repo import _compute_repo_id
    from jcodemunch_mcp.watcher import _local_repo_id

    project = tmp_path / "project"
    project.mkdir()
    store = IndexStore(base_path=str(tmp_path / "store"))
    decision = git_root.resolve_index_identity(str(project), mode="config", store=store)
    expected = f"{decision.owner}/{decision.name}"

    assert _compute_repo_id(project, store=store) == expected
    assert _local_repo_id(str(project), store=store) == expected


@pytest.mark.asyncio
async def test_watcher_reindex_passes_store_to_identity_resolver(tmp_path, monkeypatch):
    from jcodemunch_mcp import watcher

    project = tmp_path / "project"
    project.mkdir()
    store_path = tmp_path / "store"

    def fake_local_repo_id(folder_path, store=None):
        assert store is not None
        raise RuntimeError("stop after repo-id resolution")

    monkeypatch.setattr(watcher, "_local_repo_id", fake_local_repo_id)
    manager = watcher.WatcherManager(storage_path=str(store_path))

    with pytest.raises(RuntimeError, match="stop after repo-id resolution"):
        await manager._do_reindex(str(project))
