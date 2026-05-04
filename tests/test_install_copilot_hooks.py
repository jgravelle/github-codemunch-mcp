"""Tests for `init --copilot-hooks` writer (.github/hooks/hooks.json)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from jcodemunch_mcp.cli.init import install_copilot_hooks


@pytest.fixture
def in_tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestInstallCopilotHooks:
    def test_creates_hooks_file_when_absent(self, in_tmp_cwd):
        msg = install_copilot_hooks()
        assert "wrote" in msg
        path = in_tmp_cwd / ".github" / "hooks" / "hooks.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == 1
        rules = data["hooks"]["postToolUse"]
        assert len(rules) == 1
        assert "jcodemunch-mcp hook-copilot-posttooluse" in rules[0]["bash"]

    def test_idempotent_when_already_present(self, in_tmp_cwd):
        install_copilot_hooks()
        msg = install_copilot_hooks()
        assert "already present" in msg

    def test_appends_to_existing_hooks_json(self, in_tmp_cwd):
        path = in_tmp_cwd / ".github" / "hooks" / "hooks.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "version": 1,
            "hooks": {
                "postToolUse": [
                    {"type": "command", "bash": "echo other-tool"},
                ],
            },
        }), encoding="utf-8")
        msg = install_copilot_hooks(backup=False)
        assert "appended" in msg
        data = json.loads(path.read_text(encoding="utf-8"))
        rules = data["hooks"]["postToolUse"]
        assert len(rules) == 2
        cmds = [r.get("bash", "") for r in rules]
        assert any("jcodemunch-mcp" in c for c in cmds)
        assert any("other-tool" in c for c in cmds)

    def test_dry_run_does_not_write(self, in_tmp_cwd):
        msg = install_copilot_hooks(dry_run=True)
        assert "would" in msg
        assert not (in_tmp_cwd / ".github" / "hooks" / "hooks.json").exists()
