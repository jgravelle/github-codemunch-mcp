"""Tests for the embedded watcher (--watcher flag on serve subcommand)."""
import asyncio
import os
import signal
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

pytest.importorskip("watchfiles")

from jcodemunch_mcp.watcher import watch_folders


# ---------------------------------------------------------------------------
# Task 1: External stop_event
# ---------------------------------------------------------------------------

class TestExternalStopEvent:
    """watch_folders with an external stop_event skips signal handler setup."""

    @pytest.fixture()
    def folder(self, tmp_path):
        d = tmp_path / "project"
        d.mkdir()
        return d

    def test_external_stop_event_no_signal_handlers(self, folder, tmp_path):
        """When stop_event is provided, watch_folders must NOT install signal handlers."""
        storage = tmp_path / "storage"
        storage.mkdir()
        stop = asyncio.Event()

        async def run():
            # Set stop immediately so watch_folders exits after lock acquisition
            stop.set()
            with patch("jcodemunch_mcp.watcher._watch_single") as mock_ws:
                mock_ws.return_value = None
                with patch("signal.signal") as mock_sig:
                    await watch_folders(
                        paths=[str(folder)],
                        storage_path=str(storage),
                        stop_event=stop,
                    )
                    # signal.signal should NOT have been called for SIGINT/SIGTERM
                    for call in mock_sig.call_args_list:
                        assert call[0][0] not in (signal.SIGINT, signal.SIGTERM), \
                            "signal handler installed despite external stop_event"

        asyncio.run(run())


# ---------------------------------------------------------------------------
# Task 2: Parse watcher flag (placeholder - implemented in server.py)
# ---------------------------------------------------------------------------

class TestParseWatcherFlag:
    """Unit tests for _parse_watcher_flag."""

    def test_none_means_disabled(self):
        from jcodemunch_mcp.server import _parse_watcher_flag
        assert _parse_watcher_flag(None) is False

    def test_true_string_means_enabled(self):
        from jcodemunch_mcp.server import _parse_watcher_flag
        for val in ("true", "True", "TRUE", "1", "yes", "Yes"):
            assert _parse_watcher_flag(val) is True, f"Failed for {val!r}"

    def test_false_string_means_disabled(self):
        from jcodemunch_mcp.server import _parse_watcher_flag
        for val in ("false", "False", "0", "no", "No"):
            assert _parse_watcher_flag(val) is False, f"Failed for {val!r}"
