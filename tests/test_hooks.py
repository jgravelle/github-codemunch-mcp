"""Tests for CLI hook handlers (PreToolUse / PostToolUse)."""

import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from jcodemunch_mcp.cli.hooks import (
    _CODE_EXTENSIONS,
    _MIN_SIZE_BYTES,
    run_pretooluse,
    run_posttooluse,
    run_precompact,
    run_guard_explore,
    run_guard_edit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hook_input(tool_name: str, file_path: str, **extra) -> str:
    """Build a JSON string mimicking Claude Code hook stdin."""
    data = {
        "session_id": "test-session",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path},
        **extra,
    }
    return json.dumps(data)


def _make_hook_input_with_params(tool_name: str, file_path: str, **tool_input_extra) -> str:
    """Build hook JSON with extra tool_input fields (offset, limit, etc.)."""
    data = {
        "session_id": "test-session",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path, **tool_input_extra},
    }
    return json.dumps(data)


def _run_with_stdin(func, stdin_text: str) -> tuple[int, str, str]:
    """Call *func* with fake stdin/stdout/stderr and return (exit_code, stdout, stderr)."""
    fake_in = io.StringIO(stdin_text)
    fake_out = io.StringIO()
    fake_err = io.StringIO()
    with mock.patch.object(sys, "stdin", fake_in), \
         mock.patch.object(sys, "stdout", fake_out), \
         mock.patch.object(sys, "stderr", fake_err):
        rc = func()
    return rc, fake_out.getvalue(), fake_err.getvalue()


# ---------------------------------------------------------------------------
# PreToolUse tests
# ---------------------------------------------------------------------------

class TestPreToolUse:
    """Tests for run_pretooluse()."""

    def test_allows_non_code_file(self, tmp_path):
        """Non-code extensions (e.g. .txt, .md) are always allowed."""
        f = tmp_path / "readme.md"
        f.write_text("x" * 10_000)
        rc, out, err = _run_with_stdin(run_pretooluse, _make_hook_input("Read", str(f)))
        assert rc == 0
        assert out == ""  # No output → allow
        assert err == ""  # No warning either

    def test_allows_small_code_file(self, tmp_path):
        """Code files below the size threshold are allowed."""
        f = tmp_path / "tiny.py"
        f.write_text("x = 1\n")
        rc, out, err = _run_with_stdin(run_pretooluse, _make_hook_input("Read", str(f)))
        assert rc == 0
        assert out == ""
        assert err == ""

    def test_warns_large_code_file(self, tmp_path):
        """Large code files are allowed but produce a stderr warning."""
        f = tmp_path / "big.py"
        f.write_text("x = 1\n" * 2000)  # well above 4KB
        rc, out, err = _run_with_stdin(run_pretooluse, _make_hook_input("Read", str(f)))
        assert rc == 0
        assert out == ""  # No deny JSON on stdout
        assert "get_file_outline" in err
        assert "get_symbol_source" in err

    def test_allows_large_code_file_with_offset(self, tmp_path):
        """Targeted reads (offset set) are allowed silently — likely pre-edit."""
        f = tmp_path / "big.py"
        f.write_text("x = 1\n" * 2000)
        rc, out, err = _run_with_stdin(
            run_pretooluse,
            _make_hook_input_with_params("Read", str(f), offset=50),
        )
        assert rc == 0
        assert out == ""
        assert err == ""  # No warning for targeted reads

    def test_allows_large_code_file_with_limit(self, tmp_path):
        """Targeted reads (limit set) are allowed silently — likely pre-edit."""
        f = tmp_path / "big.py"
        f.write_text("x = 1\n" * 2000)
        rc, out, err = _run_with_stdin(
            run_pretooluse,
            _make_hook_input_with_params("Read", str(f), limit=50),
        )
        assert rc == 0
        assert out == ""
        assert err == ""

    def test_allows_missing_file(self):
        """Files that don't exist are allowed (can't stat)."""
        rc, out, err = _run_with_stdin(
            run_pretooluse,
            _make_hook_input("Read", "/nonexistent/path/foo.py"),
        )
        assert rc == 0
        assert out == ""

    def test_allows_empty_input(self):
        """Empty/missing file_path is allowed."""
        rc, out, err = _run_with_stdin(
            run_pretooluse,
            json.dumps({"tool_input": {}}),
        )
        assert rc == 0
        assert out == ""

    def test_allows_invalid_json(self):
        """Unparseable stdin is allowed (no crash)."""
        rc, out, err = _run_with_stdin(run_pretooluse, "not json at all")
        assert rc == 0
        assert out == ""

    def test_respects_env_override(self, tmp_path):
        """JCODEMUNCH_HOOK_MIN_SIZE overrides the threshold."""
        f = tmp_path / "medium.ts"
        f.write_text("const x = 1;\n" * 500)  # ~6.5KB
        size = f.stat().st_size

        # With a very high threshold, it should be allowed silently
        with mock.patch("jcodemunch_mcp.cli.hooks._MIN_SIZE_BYTES", size + 1):
            rc, out, err = _run_with_stdin(
                run_pretooluse, _make_hook_input("Read", str(f))
            )
            assert out == ""
            assert err == ""

        # With a low threshold, it should warn on stderr
        with mock.patch("jcodemunch_mcp.cli.hooks._MIN_SIZE_BYTES", 100):
            rc, out, err = _run_with_stdin(
                run_pretooluse, _make_hook_input("Read", str(f))
            )
            assert out == ""  # No deny
            assert "jCodemunch hint" in err

    @pytest.mark.parametrize("ext", [".py", ".ts", ".go", ".rs", ".java", ".cpp", ".rb"])
    def test_code_extensions_covered(self, ext, tmp_path):
        """Spot-check that major code extensions are in the set."""
        assert ext in _CODE_EXTENSIONS

    def test_warning_includes_file_size(self, tmp_path):
        """The stderr warning includes the file size for context."""
        f = tmp_path / "large.go"
        content = "package main\n" * 1000
        f.write_text(content)
        size = f.stat().st_size
        rc, out, err = _run_with_stdin(run_pretooluse, _make_hook_input("Read", str(f)))
        assert f"{size:,}" in err


# ---------------------------------------------------------------------------
# PostToolUse tests
# ---------------------------------------------------------------------------

class TestPostToolUse:
    """Tests for run_posttooluse()."""

    def test_spawns_index_for_code_file(self, tmp_path):
        """Editing a code file triggers jcodemunch-mcp index-file."""
        f = tmp_path / "edited.py"
        f.write_text("def foo(): pass\n")
        inp = json.dumps({
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(f)},
            "tool_response": {"success": True},
        })
        with mock.patch("jcodemunch_mcp.cli.hooks.subprocess.Popen") as mock_popen:
            rc, out, _ = _run_with_stdin(run_posttooluse, inp)

        assert rc == 0
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        assert call_args == ["jcodemunch-mcp", "index-file", str(f)]

    def test_skips_non_code_file(self, tmp_path):
        """Non-code files don't trigger indexing."""
        f = tmp_path / "data.json"
        f.write_text("{}")
        inp = json.dumps({
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(f)},
            "tool_response": {"success": True},
        })
        with mock.patch("jcodemunch_mcp.cli.hooks.subprocess.Popen") as mock_popen:
            rc, out, _ = _run_with_stdin(run_posttooluse, inp)

        assert rc == 0
        mock_popen.assert_not_called()

    def test_handles_missing_file_path(self):
        """Missing file_path in input is handled gracefully."""
        inp = json.dumps({"tool_input": {}})
        with mock.patch("jcodemunch_mcp.cli.hooks.subprocess.Popen") as mock_popen:
            rc, out, _ = _run_with_stdin(run_posttooluse, inp)
        assert rc == 0
        mock_popen.assert_not_called()

    def test_handles_invalid_json(self):
        """Invalid JSON stdin is handled gracefully."""
        with mock.patch("jcodemunch_mcp.cli.hooks.subprocess.Popen") as mock_popen:
            rc, out, _ = _run_with_stdin(run_posttooluse, "broken json")
        assert rc == 0
        mock_popen.assert_not_called()

    def test_handles_popen_failure(self, tmp_path):
        """If jcodemunch-mcp is not in PATH, fail silently."""
        f = tmp_path / "code.rs"
        f.write_text("fn main() {}")
        inp = json.dumps({
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(f)},
            "tool_response": {"success": True},
        })
        with mock.patch(
            "jcodemunch_mcp.cli.hooks.subprocess.Popen",
            side_effect=FileNotFoundError("jcodemunch-mcp not found"),
        ):
            rc, out, _ = _run_with_stdin(run_posttooluse, inp)
        assert rc == 0  # No crash

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_windows_creation_flags(self, tmp_path):
        """On Windows, CREATE_NO_WINDOW flag is passed."""
        import subprocess as sp
        f = tmp_path / "win.py"
        f.write_text("pass\n")
        inp = json.dumps({
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(f)},
            "tool_response": {"success": True},
        })
        with mock.patch("jcodemunch_mcp.cli.hooks.subprocess.Popen") as mock_popen:
            rc, _, _ = _run_with_stdin(run_posttooluse, inp)
        kwargs = mock_popen.call_args[1]
        assert kwargs.get("creationflags") == sp.CREATE_NO_WINDOW


# ---------------------------------------------------------------------------
# PreCompact tests 
# ---------------------------------------------------------------------------

class TestPreCompact:
    """Tests for run_precompact()."""
    
    def test_precompact_empty_stdin(self):
        """Empty stdin returns exit 0, no stdout."""
        rc, out, _ = _run_with_stdin(run_precompact, "")
        assert rc == 0
        assert out == ""

    def test_precompact_invalid_json(self):
        """Invalid JSON stdin returns exit 0."""
        rc, out, _ = _run_with_stdin(run_precompact, "invalid json")
        assert rc == 0
        assert out == ""
    
    def test_precompact_with_session_data(self, monkeypatch):
        """Populate journal, run hook, verify JSON output has systemMessage."""
        from jcodemunch_mcp.tools.session_journal import get_journal
        
        # Record some session data
        journal = get_journal()
        journal.record_read("src/server.py", "get_file_outline")
        journal.record_search("test_query", 2)
        journal.record_edit("src/test.py")
        
        # Mock the get_session_snapshot function to return predictable data
        def mock_get_session_snapshot(max_files=10, max_searches=5, max_edits=10, include_negative_evidence=True, storage_path=None):
            return {
                "snapshot": "## Session Snapshot (jCodemunch)\n**Duration:** 2m | **Files explored:** 1 | **Searches:** 1\n\n### Focus files (most accessed)\n- src/server.py (1 reads, last: get_file_outline)\n\n### Key searches\n- \"test_query\" → 2 results",
                "structured": {"files_accessed": [], "key_searches": [], "dead_ends": []},
                "_meta": {"timing_ms": 1.0}
            }
        
        monkeypatch.setattr(
            "jcodemunch_mcp.tools.get_session_snapshot.get_session_snapshot", 
            mock_get_session_snapshot
        )
        
        rc, out, _ = _run_with_stdin(run_precompact, '{"hook_event_name": "PreCompact"}')
        assert rc == 0
        assert out != ""
        result = json.loads(out)
        assert "systemMessage" in result
        assert "Session Snapshot" in result["systemMessage"]


# ---------------------------------------------------------------------------
# Init integration: enforcement hooks
# ---------------------------------------------------------------------------

class TestEnforcementHooksInstall:
    """Tests for install_enforcement_hooks() in init.py."""

    def test_installs_enforcement_hooks(self, tmp_path):
        """Enforcement hooks are added to a clean settings file."""
        from jcodemunch_mcp.cli.init import install_enforcement_hooks, _settings_json_path

        settings = tmp_path / "settings.json"
        settings.write_text("{}", encoding="utf-8")

        with mock.patch("jcodemunch_mcp.cli.init._settings_json_path", return_value=settings):
            msg = install_enforcement_hooks(dry_run=False, backup=False)

        assert "PreToolUse" in msg or "PostToolUse" in msg or "PreCompact" in msg
        data = json.loads(settings.read_text(encoding="utf-8"))
        hooks = data["hooks"]
        assert "PreToolUse" in hooks
        assert "PostToolUse" in hooks
        assert "PreCompact" in hooks
        # Verify matchers — 3 PreToolUse rules (Read, Bash|Grep|Glob, Edit|Write|MultiEdit)
        pre_matchers = [r["matcher"] for r in hooks["PreToolUse"]]
        assert "Read" in pre_matchers
        assert "Bash|Grep|Glob" in pre_matchers
        assert "Edit|Write|MultiEdit" in pre_matchers
        post_matcher = hooks["PostToolUse"][0]["matcher"]
        precompact_matcher = hooks["PreCompact"][0]["matcher"]
        assert post_matcher == "Edit|Write"
        assert precompact_matcher == ""  # PreCompact hook has empty matcher

    def test_idempotent(self, tmp_path):
        """Running install_enforcement_hooks twice doesn't duplicate entries."""
        from jcodemunch_mcp.cli.init import install_enforcement_hooks

        settings = tmp_path / "settings.json"
        settings.write_text("{}", encoding="utf-8")

        with mock.patch("jcodemunch_mcp.cli.init._settings_json_path", return_value=settings):
            install_enforcement_hooks(dry_run=False, backup=False)
            msg2 = install_enforcement_hooks(dry_run=False, backup=False)

        assert "already present" in msg2
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert len(data["hooks"]["PreToolUse"]) == 3  # Read, Bash|Grep|Glob, Edit|Write|MultiEdit
        assert len(data["hooks"]["PostToolUse"]) == 1

    def test_preserves_existing_hooks(self, tmp_path):
        """Existing hooks in settings.json are preserved."""
        from jcodemunch_mcp.cli.init import install_enforcement_hooks

        settings = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "SessionStart": [{"hooks": [{"type": "command", "command": "echo hello"}]}],
            }
        }
        settings.write_text(json.dumps(existing), encoding="utf-8")

        with mock.patch("jcodemunch_mcp.cli.init._settings_json_path", return_value=settings):
            install_enforcement_hooks(dry_run=False, backup=False)

        data = json.loads(settings.read_text(encoding="utf-8"))
        assert "SessionStart" in data["hooks"]  # preserved
        assert "PreToolUse" in data["hooks"]     # added
        assert "PostToolUse" in data["hooks"]    # added

    def test_dry_run(self, tmp_path):
        """Dry run doesn't write anything."""
        from jcodemunch_mcp.cli.init import install_enforcement_hooks

        settings = tmp_path / "settings.json"
        settings.write_text("{}", encoding="utf-8")

        with mock.patch("jcodemunch_mcp.cli.init._settings_json_path", return_value=settings):
            msg = install_enforcement_hooks(dry_run=True, backup=False)

        assert "would add" in msg
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert "hooks" not in data  # Nothing written


# ---------------------------------------------------------------------------
# Guard explore tests (replaces jcodemunch_read_guard.sh)
# ---------------------------------------------------------------------------

def _make_guard_input(tool_name: str, **tool_input_fields) -> str:
    """Build a JSON string for guard hook stdin."""
    data = {
        "session_id": "test-session",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input_fields,
    }
    return json.dumps(data)


class TestGuardExplore:
    """Tests for run_guard_explore()."""

    def test_blocks_grep_tool(self):
        """Grep tool is always treated as code exploration."""
        inp = _make_guard_input("Grep", pattern="def foo")
        rc, out, err = _run_with_stdin(run_guard_explore, inp)
        assert rc == 2
        assert "search_symbols" in err
        assert "get_symbol_source" in err

    def test_blocks_bash_code_exploration(self):
        """Bash commands exploring code files are blocked."""
        inp = _make_guard_input("Bash", command="grep -r 'TODO' src/main.py")
        rc, out, err = _run_with_stdin(run_guard_explore, inp)
        assert rc == 2
        assert "jCodemunch guard" in err

    def test_blocks_bash_find_code(self):
        """Bash find targeting code extensions is blocked."""
        inp = _make_guard_input("Bash", command="find . -name '*.ts' -type f")
        rc, out, err = _run_with_stdin(run_guard_explore, inp)
        assert rc == 2

    def test_blocks_bash_cat_code(self):
        """Bash cat on code files is blocked."""
        inp = _make_guard_input("Bash", command="cat src/server.py")
        rc, out, err = _run_with_stdin(run_guard_explore, inp)
        assert rc == 2

    def test_allows_bash_safe_commands(self):
        """Safe commands (npm, pytest, git, etc.) pass through."""
        for cmd in ["npm test", "pytest -v", "git status", "cargo build", "uv pip install foo"]:
            inp = _make_guard_input("Bash", command=cmd)
            rc, out, err = _run_with_stdin(run_guard_explore, inp)
            assert rc == 0, f"Should allow safe command: {cmd}"
            assert err == "", f"Should be silent for: {cmd}"

    def test_allows_bash_non_code_command(self):
        """Bash commands that don't match exploration patterns pass through."""
        inp = _make_guard_input("Bash", command="ls -la")
        rc, out, err = _run_with_stdin(run_guard_explore, inp)
        assert rc == 0
        assert err == ""

    def test_blocks_glob_code_pattern(self):
        """Glob targeting code extensions is blocked."""
        inp = _make_guard_input("Glob", pattern="**/*.py")
        rc, out, err = _run_with_stdin(run_guard_explore, inp)
        assert rc == 2
        assert "jCodemunch guard" in err

    def test_allows_glob_non_code(self):
        """Glob targeting non-code extensions passes through."""
        inp = _make_guard_input("Glob", pattern="**/*.md")
        rc, out, err = _run_with_stdin(run_guard_explore, inp)
        assert rc == 0
        assert err == ""

    def test_allows_glob_json(self):
        """Glob for JSON files passes through."""
        inp = _make_guard_input("Glob", pattern="*.json")
        rc, out, err = _run_with_stdin(run_guard_explore, inp)
        assert rc == 0

    def test_allows_unknown_tool(self):
        """Tools other than Bash/Grep/Glob pass through immediately."""
        for tool in ["Read", "Edit", "Write", "MultiEdit"]:
            inp = _make_guard_input(tool, file_path="/some/file.py")
            rc, out, err = _run_with_stdin(run_guard_explore, inp)
            assert rc == 0, f"Should allow tool: {tool}"

    def test_handles_invalid_json(self):
        """Invalid JSON stdin doesn't crash."""
        rc, out, err = _run_with_stdin(run_guard_explore, "not json")
        assert rc == 0

    def test_handles_empty_input(self):
        """Missing tool_input fields are handled gracefully."""
        inp = json.dumps({"tool_name": "Bash", "tool_input": {}})
        rc, out, err = _run_with_stdin(run_guard_explore, inp)
        assert rc == 0

    def test_allows_jcodemunch_command(self):
        """jcodemunch commands in Bash are safe."""
        inp = _make_guard_input("Bash", command="jcodemunch-mcp index-file src/app.py")
        rc, out, err = _run_with_stdin(run_guard_explore, inp)
        assert rc == 0

    @pytest.mark.parametrize("ext", [".py", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".cpp"])
    def test_blocks_bash_rg_code_extensions(self, ext):
        """rg targeting various code extensions is blocked."""
        inp = _make_guard_input("Bash", command=f"rg 'pattern' file{ext}")
        rc, out, err = _run_with_stdin(run_guard_explore, inp)
        assert rc == 2


# ---------------------------------------------------------------------------
# Guard edit tests (replaces jcodemunch_edit_guard.sh)
# ---------------------------------------------------------------------------

class TestGuardEdit:
    """Tests for run_guard_edit()."""

    def test_soft_gate_default(self):
        """Default mode: allow edit but print warning to stderr."""
        inp = _make_guard_input("Edit", file_path="src/app.py")
        rc, out, err = _run_with_stdin(run_guard_edit, inp)
        assert rc == 0
        assert "edit guard" in err
        assert "get_symbol_source" in err
        assert "get_blast_radius" in err

    def test_soft_gate_includes_file_path(self):
        """Warning includes the target file path."""
        inp = _make_guard_input("Edit", file_path="src/server.py")
        rc, out, err = _run_with_stdin(run_guard_edit, inp)
        assert rc == 0
        assert "src/server.py" in err

    def test_hard_block_env(self, monkeypatch):
        """JCODEMUNCH_HARD_BLOCK=1 exits 2 (hard block)."""
        monkeypatch.setenv("JCODEMUNCH_HARD_BLOCK", "1")
        inp = _make_guard_input("Edit", file_path="src/app.py")
        rc, out, err = _run_with_stdin(run_guard_edit, inp)
        assert rc == 2
        assert "blocked" in err

    def test_allow_raw_write_env(self, monkeypatch):
        """JCODEMUNCH_ALLOW_RAW_WRITE=1 skips entirely."""
        monkeypatch.setenv("JCODEMUNCH_ALLOW_RAW_WRITE", "1")
        inp = _make_guard_input("Edit", file_path="src/app.py")
        rc, out, err = _run_with_stdin(run_guard_edit, inp)
        assert rc == 0
        assert err == ""

    def test_write_tool(self):
        """Write tool is also gated."""
        inp = _make_guard_input("Write", file_path="src/new.py")
        rc, out, err = _run_with_stdin(run_guard_edit, inp)
        assert rc == 0
        assert "edit guard" in err

    def test_multiedit_tool(self):
        """MultiEdit tool is also gated."""
        inp = _make_guard_input("MultiEdit", file_path="src/refactor.py")
        rc, out, err = _run_with_stdin(run_guard_edit, inp)
        assert rc == 0
        assert "edit guard" in err

    def test_non_edit_tool_passes(self):
        """Non-edit tools pass through silently."""
        for tool in ["Read", "Bash", "Grep", "Glob"]:
            inp = _make_guard_input(tool, file_path="src/app.py")
            rc, out, err = _run_with_stdin(run_guard_edit, inp)
            assert rc == 0, f"Should allow tool: {tool}"
            assert err == "", f"Should be silent for: {tool}"

    def test_handles_invalid_json(self):
        """Invalid JSON stdin doesn't crash."""
        rc, out, err = _run_with_stdin(run_guard_edit, "not json")
        assert rc == 0

    def test_handles_missing_file_path(self):
        """Missing file_path still shows warning but no file hint."""
        inp = json.dumps({"tool_name": "Edit", "tool_input": {}})
        rc, out, err = _run_with_stdin(run_guard_edit, inp)
        assert rc == 0
        assert "edit guard" in err
        assert "Target file:" not in err
