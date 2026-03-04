"""Tests that anthropic is optional and fallback paths work."""

import os
from unittest.mock import patch

from jcodemunch_mcp.parser.symbols import Symbol
from jcodemunch_mcp.summarizer.batch_summarize import (
    BatchSummarizer,
    _create_summarizer,
    summarize_symbols,
    summarize_symbols_simple,
)


def _make_symbol(name="my_func", kind="function", signature="def my_func(x, y)", docstring=""):
    return Symbol(
        id=f"test.py::{name}#function",
        file="test.py",
        name=name,
        qualified_name=name,
        kind=kind,
        language="python",
        signature=signature,
        docstring=docstring,
    )


def test_summarize_symbols_simple_no_ai():
    """summarize_symbols_simple works without any AI provider."""
    symbols = [
        _make_symbol("add", docstring="Add two numbers together."),
        _make_symbol("sub", signature="def sub(a, b)"),
    ]
    result = summarize_symbols_simple(symbols)
    assert result[0].summary == "Add two numbers together."
    assert result[1].summary == "def sub(a, b)"


def test_summarize_symbols_use_ai_false():
    """summarize_symbols with use_ai=False produces summaries via fallback."""
    symbols = [_make_symbol("calc", signature="def calc(x)")]
    result = summarize_symbols(symbols, use_ai=False)
    assert result[0].summary == "def calc(x)"


def test_create_summarizer_no_keys():
    """_create_summarizer returns None when no API keys are set."""
    with patch.dict(os.environ, {}, clear=True):
        assert _create_summarizer() is None


def test_batch_summarizer_import_error_fallback():
    """BatchSummarizer falls back when anthropic is not importable."""
    with patch.dict("sys.modules", {"anthropic": None}):
        s = BatchSummarizer()
        assert s.client is None
        # Should still produce summaries via fallback
        symbols = [_make_symbol("foo")]
        result = s.summarize_batch(symbols)
        assert result[0].summary != ""
