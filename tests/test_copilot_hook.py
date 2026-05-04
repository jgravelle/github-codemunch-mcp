"""Tests for the GitHub Copilot postToolUse hook adapter.

Copilot's stdin payload differs from Claude Code's: ``toolArgs`` arrives
as a JSON-encoded **string** rather than a nested object, and tool names
vary by tool implementation. The handler must extract a file path from
the JSON-string-inside-a-string and only reindex code files.
"""

from __future__ import annotations

import io
import json
import os
import sys
from unittest.mock import patch

import pytest

from jcodemunch_mcp.cli.hooks import run_copilot_posttooluse


@pytest.fixture
def stdin_with(monkeypatch):
    def _set(payload: dict):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    return _set


class TestCopilotHookExtraction:
    def test_extracts_file_path_from_string_toolargs(self, stdin_with):
        """toolArgs as JSON string (Copilot's actual payload shape)."""
        stdin_with({
            "toolName": "edit",
            "toolArgs": json.dumps({"file_path": "/tmp/test.py"}),
        })
        with patch("jcodemunch_mcp.cli.hooks.subprocess.Popen") as popen:
            assert run_copilot_posttooluse() == 0
            popen.assert_called_once()
            args = popen.call_args[0][0]
            assert args == ["jcodemunch-mcp", "index-file", "/tmp/test.py"]

    def test_extracts_from_dict_toolargs_too(self, stdin_with):
        """toolArgs delivered as a dict directly (defensive)."""
        stdin_with({
            "toolName": "write",
            "toolArgs": {"path": "/tmp/x.ts"},
        })
        with patch("jcodemunch_mcp.cli.hooks.subprocess.Popen") as popen:
            assert run_copilot_posttooluse() == 0
            popen.assert_called_once()

    def test_skips_non_code_extensions(self, stdin_with):
        stdin_with({
            "toolName": "edit",
            "toolArgs": json.dumps({"file_path": "/tmp/notes.md"}),
        })
        with patch("jcodemunch_mcp.cli.hooks.subprocess.Popen") as popen:
            assert run_copilot_posttooluse() == 0
            popen.assert_not_called()

    def test_handles_invalid_json_stdin(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        with patch("jcodemunch_mcp.cli.hooks.subprocess.Popen") as popen:
            assert run_copilot_posttooluse() == 0
            popen.assert_not_called()

    def test_handles_empty_toolargs(self, stdin_with):
        stdin_with({"toolName": "edit", "toolArgs": ""})
        with patch("jcodemunch_mcp.cli.hooks.subprocess.Popen") as popen:
            assert run_copilot_posttooluse() == 0
            popen.assert_not_called()

    def test_alternate_path_keys(self, stdin_with):
        """Copilot tools use varied path keys; the adapter probes several."""
        for key in ("file_path", "filePath", "path", "filename"):
            stdin_with({
                "toolName": "create_file",
                "toolArgs": json.dumps({key: "/tmp/probe.go"}),
            })
            with patch("jcodemunch_mcp.cli.hooks.subprocess.Popen") as popen:
                run_copilot_posttooluse()
                popen.assert_called_once()
