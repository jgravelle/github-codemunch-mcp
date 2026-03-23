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


def test_remap_empty_pairs_normalises_sep():
    """No mapping set: path returned with os.sep normalisation."""
    result = remap("/home/user/project/file.py", [])
    assert result == str(os.path.join("/home", "user", "project", "file.py"))


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
