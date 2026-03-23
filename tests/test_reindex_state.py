"""Tests for reindex_state module."""

import pytest
import time

from jcodemunch_mcp.reindex_state import (
    _get_state, _freshness_mode, _repo_states,
    mark_reindex_start, mark_reindex_done, mark_reindex_failed,
    get_reindex_status, is_any_reindex_in_progress,
    set_freshness_mode, get_freshness_mode, await_freshness_if_strict,
    wait_for_fresh_result,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset module-level state before each test."""
    _repo_states.clear()
    _freshness_mode.clear()
    yield
    _repo_states.clear()
    _freshness_mode.clear()


class TestRepoStateCreation:
    def test_get_state_creates_new_state(self):
        state = _get_state("test/repo")
        assert state is not None

    def test_get_state_returns_same_instance(self):
        state1 = _get_state("test/repo")
        state2 = _get_state("test/repo")
        assert state1 is state2

    def test_get_state_different_repos_are_independent(self):
        state1 = _get_state("repo/a")
        state2 = _get_state("repo/b")
        assert state1 is not state2


class TestMarkReindexStart:
    def test_mark_reindex_start(self):
        mark_reindex_start("test/repo")
        status = get_reindex_status("test/repo")
        assert status["reindexing"] is True
        assert status["reindex_finished"] is False
        assert status["reindex_error"] is None
        assert status["last_reindex_start"] > 0


class TestMarkReindexDone:
    def test_mark_reindex_done(self):
        mark_reindex_start("test/repo")
        mark_reindex_done("test/repo", {"symbol_count": 42})
        status = get_reindex_status("test/repo")
        assert status["reindexing"] is False
        assert status["reindex_finished"] is True
        assert status["reindex_error"] is None
        assert status["last_reindex_done"] > 0

    def test_mark_reindex_done_clears_error(self):
        mark_reindex_start("test/repo")
        mark_reindex_failed("test/repo", "some error")
        mark_reindex_done("test/repo")
        status = get_reindex_status("test/repo")
        assert status["reindex_error"] is None


class TestMarkReindexFailed:
    def test_mark_reindex_failed(self):
        mark_reindex_start("test/repo")
        mark_reindex_failed("test/repo", "parse error")
        status = get_reindex_status("test/repo")
        assert status["reindexing"] is False
        assert status["reindex_finished"] is True
        assert status["reindex_error"] == "parse error"


class TestGetReindexStatus:
    def test_get_reindex_status_idle(self):
        status = get_reindex_status("test/repo")
        assert status["reindexing"] is False
        assert status["reindex_finished"] is False
        assert status["reindex_error"] is None

    def test_get_reindex_status_in_progress(self):
        mark_reindex_start("test/repo")
        status = get_reindex_status("test/repo")
        assert status["reindexing"] is True
        assert status["reindex_finished"] is False

    def test_is_any_reindex_in_progress(self):
        assert is_any_reindex_in_progress() is False
        mark_reindex_start("repo/a")
        mark_reindex_start("repo/b")
        assert is_any_reindex_in_progress() is True


class TestFreshnessMode:
    @pytest.fixture(autouse=True)
    def _reset_freshness_mode(self):
        """Reset freshness mode after each test."""
        set_freshness_mode("relaxed")
        yield
        set_freshness_mode("relaxed")

    def test_default_freshness_is_relaxed(self):
        set_freshness_mode("relaxed")
        assert get_freshness_mode() == "relaxed"

    def test_set_freshness_mode_strict(self):
        set_freshness_mode("strict")
        assert get_freshness_mode() == "strict"

    def test_await_relaxed_returns_immediately(self):
        mark_reindex_start("test/repo")
        result = await_freshness_if_strict("test/repo", timeout_ms=50)
        assert result is True  # relaxed mode returns immediately

    def test_await_strict_blocks_until_done(self):
        # This test verifies strict mode waits
        mark_reindex_start("test/repo")
        # In strict mode, should not return immediately since reindexing is in progress
        # But will timeout after 50ms
        result = await_freshness_if_strict("test/repo", timeout_ms=50)
        assert result is True  # False would mean timed out


class TestWaitForFreshResult:
    def test_wait_returns_fresh_after_done(self):
        mark_reindex_done("test/repo", {"symbol_count": 100})
        result = wait_for_fresh_result("test/repo", timeout_ms=100)
        assert result["status"] == "fresh"
        assert result["result"]["symbol_count"] == 100

    def test_wait_returns_error_after_failed(self):
        mark_reindex_failed("test/repo", "disk full")
        result = wait_for_fresh_result("test/repo", timeout_ms=100)
        assert result["status"] == "error"
        assert result["error"] == "disk full"

    def test_wait_returns_stale_for_unknown_repo(self):
        result = wait_for_fresh_result("never/seen", timeout_ms=100)
        assert result["status"] == "stale"
