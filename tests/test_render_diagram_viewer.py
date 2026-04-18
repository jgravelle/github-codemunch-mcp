"""Tests for mermaid_viewer integration — viewer spawn, cleanup, and config gate."""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── mermaid_viewer module tests ─────────────────────────────────────────────

class TestResolveViewerPath:
    """resolve_viewer_path() returns configured path, falls back to $PATH, or None."""

    def test_returns_configured_path_when_exists(self):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        import jcodemunch_mcp.config as config_module
        importlib.reload(mv)
        fake_path = "/usr/local/bin/mmd-viewer"
        with patch.object(config_module, "get", side_effect=lambda k, d=None: fake_path if k == "mermaid_viewer_path" else d):
            with patch.object(Path, "exists", return_value=True):
                result = mv.resolve_viewer_path()
                assert result == fake_path

    def test_returns_none_when_configured_path_missing(self):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        import jcodemunch_mcp.config as config_module
        importlib.reload(mv)
        fake_path = "/nonexistent/mmd-viewer"
        with patch.object(config_module, "get", side_effect=lambda k, d=None: fake_path if k == "mermaid_viewer_path" else d):
            result = mv.resolve_viewer_path()
            assert result is None

    def test_falls_back_to_shutil_which(self):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        import jcodemunch_mcp.config as config_module
        importlib.reload(mv)
        with patch.object(config_module, "get", side_effect=lambda k, d=None: "" if k == "mermaid_viewer_path" else d):
            with patch.object(shutil, "which", return_value="/usr/bin/mmd-viewer"):
                result = mv.resolve_viewer_path()
                assert result == "/usr/bin/mmd-viewer"

    def test_returns_none_when_both_miss(self):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        import jcodemunch_mcp.config as config_module
        importlib.reload(mv)
        with patch.object(config_module, "get", side_effect=lambda k, d=None: "" if k == "mermaid_viewer_path" else d):
            with patch.object(shutil, "which", return_value=None):
                result = mv.resolve_viewer_path()
                assert result is None


class TestOpenDiagram:
    """open_diagram() writes .mmd file and spawns viewer."""

    def test_viewer_not_found(self):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        import jcodemunch_mcp.config as config_module
        importlib.reload(mv)
        with patch.object(config_module, "get", side_effect=lambda k, d=None: "" if k == "mermaid_viewer_path" else d):
            with patch.object(shutil, "which", return_value=None):
                result = mv.open_diagram("graph TD; A-->B;")
                assert result["opened"] is False
                assert result["error"] == "viewer_not_found"

    def test_opens_viewer_and_returns_path(self, tmp_path):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        import jcodemunch_mcp.config as config_module
        importlib.reload(mv)
        fake_viewer = str(tmp_path / "mmd-viewer")
        with patch.object(config_module, "get", side_effect=lambda k, d=None: fake_viewer if k == "mermaid_viewer_path" else d):
            with patch.object(Path, "exists", return_value=True):
                with patch("subprocess.Popen") as mock_popen:
                    result = mv.open_diagram("graph TD; A-->B;", storage_path=tmp_path)
                    assert result["opened"] is True
                    assert result["path"].endswith(".mmd")
                    assert "jcm-diagram-" in result["path"]
                    mock_popen.assert_called_once()

    def test_spawn_failure_is_non_fatal(self, tmp_path):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        import jcodemunch_mcp.config as config_module
        importlib.reload(mv)
        fake_viewer = str(tmp_path / "mmd-viewer")
        with patch.object(config_module, "get", side_effect=lambda k, d=None: fake_viewer if k == "mermaid_viewer_path" else d):
            with patch.object(Path, "exists", return_value=True):
                with patch("subprocess.Popen", side_effect=OSError("exec failed")):
                    result = mv.open_diagram("graph TD; A-->B;", storage_path=tmp_path)
                    assert result["opened"] is False
                    assert "spawn_failed" in result["error"]
                    assert result["path"].endswith(".mmd")

    def test_sets_viewer_used_flag(self, tmp_path):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        import jcodemunch_mcp.config as config_module
        importlib.reload(mv)
        fake_viewer = str(tmp_path / "mmd-viewer")
        with patch.object(config_module, "get", side_effect=lambda k, d=None: fake_viewer if k == "mermaid_viewer_path" else d):
            with patch.object(Path, "exists", return_value=True):
                with patch("subprocess.Popen"):
                    assert mv._viewer_used is False
                    mv.open_diagram("graph TD; A-->B;", storage_path=tmp_path)
                    assert mv._viewer_used is True


class TestWasViewerUsed:
    """was_viewer_used() tracks session usage."""

    def test_initially_false(self):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        importlib.reload(mv)
        assert mv.was_viewer_used() is False

    def test_true_after_open_diagram(self, tmp_path):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        import jcodemunch_mcp.config as config_module
        importlib.reload(mv)
        fake_viewer = str(tmp_path / "mmd-viewer")
        with patch.object(config_module, "get", side_effect=lambda k, d=None: fake_viewer if k == "mermaid_viewer_path" else d):
            with patch.object(Path, "exists", return_value=True):
                with patch("subprocess.Popen"):
                    mv.open_diagram("graph TD; A-->B;", storage_path=tmp_path)
                    assert mv.was_viewer_used() is True


class TestCleanupTempDir:
    """cleanup_temp_dir() removes only jcm- prefixed files."""

    def test_removes_jcm_files_only(self, tmp_path):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        importlib.reload(mv)
        d = tmp_path / "temp" / "mermaid"
        d.mkdir(parents=True)
        (d / "jcm-diagram-1.mmd").write_text("test")
        (d / "jcm-diagram-2.mmd").write_text("test")
        (d / "other-tool-file.txt").write_text("leave me alone")
        result = mv.cleanup_temp_dir(storage_path=tmp_path)
        assert result == 2
        assert d.exists()
        remaining = list(d.iterdir())
        assert len(remaining) == 1
        assert remaining[0].name == "other-tool-file.txt"

    def test_noop_when_dir_missing(self, tmp_path):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        importlib.reload(mv)
        result = mv.cleanup_temp_dir(storage_path=tmp_path / "nonexistent")
        assert result == 0

    def test_noop_when_no_jcm_files(self, tmp_path):
        import importlib
        import jcodemunch_mcp.tools.mermaid_viewer as mv
        importlib.reload(mv)
        d = tmp_path / "temp" / "mermaid"
        d.mkdir(parents=True)
        (d / "other-file.txt").write_text("test")
        result = mv.cleanup_temp_dir(storage_path=tmp_path)
        assert result == 0
        assert (d / "other-file.txt").exists()


# ── render_diagram integration tests ────────────────────────────────────────

class TestRenderDiagramViewerGate:
    """render_diagram(open_in_viewer=True) respects config gate."""

    def _call_hierarchy_data(self):
        return {
            "repo": "test/repo",
            "symbol": {"id": "server.py::handle", "name": "handle", "kind": "function", "file": "server.py", "line": 10},
            "direction": "both",
            "depth": 3,
            "depth_reached": 2,
            "caller_count": 1,
            "callee_count": 1,
            "callers": [{"id": "main.py::run", "name": "run", "kind": "function", "file": "main.py", "line": 5, "depth": 1, "resolution": "ast_resolved"}],
            "callees": [{"id": "db.py::query", "name": "query", "kind": "function", "file": "db.py", "line": 20, "depth": 1, "resolution": "ast_resolved"}],
            "dispatches": [],
        }

    def test_config_off_does_not_call_open_diagram(self):
        """When render_diagram_viewer_enabled=False, open_diagram is never called."""
        import importlib
        import jcodemunch_mcp.config as config_module
        original_get = config_module.get
        config_module.get = lambda k, d=None: False if k == "render_diagram_viewer_enabled" else original_get(k, d)
        try:
            import jcodemunch_mcp.tools.mermaid_viewer as mv
            importlib.reload(mv)
            with patch.object(mv, "open_diagram", return_value={"opened": True, "path": "/tmp/test.mmd"}) as mock_open:
                from jcodemunch_mcp.tools.render_diagram import render_diagram
                result = render_diagram(self._call_hierarchy_data(), open_in_viewer=True)
                mock_open.assert_not_called()
                assert "viewer_path" not in result
                assert "viewer_error" not in result
                assert "mermaid" in result
        finally:
            config_module.get = original_get

    def test_config_on_calls_open_diagram(self):
        """When render_diagram_viewer_enabled=True, open_diagram is called."""
        import importlib
        import jcodemunch_mcp.config as config_module
        original_get = config_module.get
        config_module.get = lambda k, d=None: True if k == "render_diagram_viewer_enabled" else original_get(k, d)
        try:
            import jcodemunch_mcp.tools.mermaid_viewer as mv
            importlib.reload(mv)
            with patch.object(mv, "open_diagram", return_value={"opened": True, "path": "/tmp/test.mmd"}) as mock_open:
                from jcodemunch_mcp.tools.render_diagram import render_diagram
                result = render_diagram(self._call_hierarchy_data(), open_in_viewer=True)
                mock_open.assert_called_once()
                assert result["viewer_path"] == "/tmp/test.mmd"
        finally:
            config_module.get = original_get

    def test_viewer_error_propagated_non_fatal(self):
        """Viewer failure adds viewer_error but mermaid is still returned."""
        import importlib
        import jcodemunch_mcp.config as config_module
        original_get = config_module.get
        config_module.get = lambda k, d=None: True if k == "render_diagram_viewer_enabled" else original_get(k, d)
        try:
            import jcodemunch_mcp.tools.mermaid_viewer as mv
            importlib.reload(mv)
            with patch.object(mv, "open_diagram", return_value={"opened": False, "error": "viewer_not_found"}):
                from jcodemunch_mcp.tools.render_diagram import render_diagram
                result = render_diagram(self._call_hierarchy_data(), open_in_viewer=True)
                assert result["viewer_error"] == "viewer_not_found"
                assert "mermaid" in result
        finally:
            config_module.get = original_get


# ── Schema gate test ────────────────────────────────────────────────────────

class TestSchemaGate:
    """open_in_viewer appears in schema only when config gate is on."""

    def test_schema_without_viewer(self):
        """Default config: render_diagram schema has no open_in_viewer."""
        import importlib
        import jcodemunch_mcp.config as config_module
        original_get = config_module.get
        config_module.get = lambda k, d=None: False if k == "render_diagram_viewer_enabled" else original_get(k, d)
        try:
            import jcodemunch_mcp.server as server_module
            importlib.reload(server_module)
            tools = server_module._build_tools_list()
            render_tool = next(t for t in tools if t.name == "render_diagram")
            assert "open_in_viewer" not in render_tool.inputSchema["properties"]
        finally:
            config_module.get = original_get

    def test_schema_with_viewer_enabled(self):
        """Config on: render_diagram schema includes open_in_viewer."""
        import importlib
        import jcodemunch_mcp.config as config_module
        original_get = config_module.get
        config_module.get = lambda k, d=None: True if k == "render_diagram_viewer_enabled" else original_get(k, d)
        try:
            import jcodemunch_mcp.server as server_module
            importlib.reload(server_module)
            tools = server_module._build_tools_list()
            render_tool = next(t for t in tools if t.name == "render_diagram")
            assert "open_in_viewer" in render_tool.inputSchema["properties"]
            prop = render_tool.inputSchema["properties"]["open_in_viewer"]
            assert prop["type"] == "boolean"
            assert prop["default"] is False
        finally:
            config_module.get = original_get
