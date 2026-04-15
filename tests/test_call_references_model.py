"""Tests for Task 1: call_references data model — Symbol field, INDEX_VERSION 8, SQLite storage."""

import json
import pytest
import sqlite3
from pathlib import Path

from jcodemunch_mcp.parser.symbols import Symbol
from jcodemunch_mcp.storage.index_store import INDEX_VERSION, CodeIndex


class TestCallReferencesSymbolField:
    """Symbol dataclass carries call_references."""

    def test_symbol_has_call_references_field(self):
        """Symbol should accept call_references as a field."""
        sym = Symbol(
            id="src/main.py::foo#function",
            file="src/main.py",
            name="foo",
            qualified_name="foo",
            kind="function",
            language="python",
            signature="def foo()",
            call_references=["bar", "baz"],
        )
        assert sym.call_references == ["bar", "baz"]

    def test_symbol_call_references_defaults_to_empty_list(self):
        """call_references should default to an empty list."""
        sym = Symbol(
            id="src/main.py::foo#function",
            file="src/main.py",
            name="foo",
            qualified_name="foo",
            kind="function",
            language="python",
            signature="def foo()",
        )
        assert sym.call_references == []

    def test_symbol_call_references_round_trip(self):
        """call_references should survive a round-trip through Symbol."""
        sym = Symbol(
            id="src/main.py::foo#function",
            file="src/main.py",
            name="foo",
            qualified_name="foo",
            kind="function",
            language="python",
            signature="def foo()",
            call_references=["helper", "validate"],
        )
        # Access all fields to ensure no AttributeError
        assert sym.call_references == ["helper", "validate"]


class TestIndexVersionBump:
    """INDEX_VERSION is bumped to 8."""

    def test_index_version_is_8(self):
        """INDEX_VERSION constant must be 8 after this change."""
        assert INDEX_VERSION == 9


class TestCallersByNameIndex:
    """CodeIndex.get_callers_by_name() builds _callers_by_name lazily from call_references."""

    def test_callers_by_name_populated_from_symbols(self):
        """get_callers_by_name() maps (caller_file, called_name) -> list of caller IDs."""
        symbols = [
            {
                "id": "a.py::foo#function",
                "name": "foo",
                "file": "a.py",
                "qualified_name": "foo",
                "kind": "function",
                "language": "python",
                "signature": "def foo()",
                "call_references": ["helper", "bar"],
            },
            {
                "id": "b.py::bar#function",
                "name": "bar",
                "file": "b.py",
                "qualified_name": "bar",
                "kind": "function",
                "language": "python",
                "signature": "def bar()",
                "call_references": ["baz"],
            },
            {
                "id": "c.py::baz#function",
                "name": "baz",
                "file": "c.py",
                "qualified_name": "baz",
                "kind": "function",
                "language": "python",
                "signature": "def baz()",
                "call_references": [],
            },
        ]
        index = CodeIndex(
            repo="test/repo",
            owner="test",
            name="repo",
            indexed_at="2024-01-01T00:00:00",
            source_files=["a.py", "b.py", "c.py"],
            languages={"python": 3},
            symbols=symbols,
        )
        callers = index.get_callers_by_name()
        # helper is called by a.py::foo
        assert ("a.py", "helper") in callers
        assert "a.py::foo#function" in callers[("a.py", "helper")]
        # bar is called by a.py::foo
        assert ("a.py", "bar") in callers
        assert "a.py::foo#function" in callers[("a.py", "bar")]
        # baz is called by b.py::bar
        assert ("b.py", "baz") in callers
        assert "b.py::bar#function" in callers[("b.py", "baz")]
        # bar does NOT call bar (self-reference doesn't count)
        assert "b.py::bar#function" not in callers.get(("b.py", "bar"), [])

    def test_callers_by_name_absent_when_no_call_references(self):
        """When no symbols have call_references, get_callers_by_name() returns empty dict."""
        symbols = [
            {
                "id": "a.py::foo#function",
                "name": "foo",
                "file": "a.py",
                "qualified_name": "foo",
                "kind": "function",
                "language": "python",
                "signature": "def foo()",
            },
        ]
        index = CodeIndex(
            repo="test/repo",
            owner="test",
            name="repo",
            indexed_at="2024-01-01T00:00:00",
            source_files=["a.py"],
            languages={"python": 1},
            symbols=symbols,
        )
        # Empty because no symbol has call_references populated
        assert index.get_callers_by_name() == {}


class TestSQLiteCallReferencesRoundTrip:
    """call_references survives SQLite serialization/deserialization."""

    def _round_trip_symbols(self, symbols: list[dict], tmp_path: Path) -> list[dict]:
        """Save symbols to SQLite and read them back."""
        from jcodemunch_mcp.storage.sqlite_store import SQLiteIndexStore

        store = SQLiteIndexStore(base_path=str(tmp_path / "store"))
        db_path = tmp_path / "test.db"
        conn = store._connect(db_path)

        for sym in symbols:
            row = store._symbol_dict_to_row(sym)
            conn.execute(
                "INSERT INTO symbols (id, file, name, kind, signature, summary, docstring, "
                "line, end_line, byte_offset, byte_length, parent, qualified_name, language, "
                "decorators, keywords, content_hash, ecosystem_context, data, cyclomatic, "
                "max_nesting, param_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        conn.commit()

        rows = conn.execute("SELECT * FROM symbols").fetchall()
        col_names = [description[0] for description in conn.execute("SELECT * FROM symbols").description]
        result = []
        for row in rows:
            row_dict = dict(zip(col_names, row))
            result.append(store._row_to_symbol_dict(row_dict))
        return result

    def test_call_references_saved_and_loaded(self, tmp_path):
        """Symbol with call_references survives SQLite save/load."""
        symbols = [
            {
                "id": "src/main.py::foo#function",
                "file": "src/main.py",
                "name": "foo",
                "qualified_name": "foo",
                "kind": "function",
                "language": "python",
                "signature": "def foo()",
                "summary": "",
                "docstring": "",
                "decorators": [],
                "keywords": [],
                "parent": None,
                "line": 1,
                "end_line": 2,
                "byte_offset": 0,
                "byte_length": 50,
                "content_hash": "",
                "ecosystem_context": "",
                "cyclomatic": 0,
                "max_nesting": 0,
                "param_count": 0,
                "call_references": ["bar", "baz"],
            }
        ]
        result = self._round_trip_symbols(symbols, tmp_path)
        assert len(result) == 1
        assert result[0]["call_references"] == ["bar", "baz"]

    def test_call_references_empty_list_saved(self, tmp_path):
        """Symbol with empty call_references list is saved correctly."""
        symbols = [
            {
                "id": "src/main.py::foo#function",
                "file": "src/main.py",
                "name": "foo",
                "qualified_name": "foo",
                "kind": "function",
                "language": "python",
                "signature": "def foo()",
                "summary": "",
                "docstring": "",
                "decorators": [],
                "keywords": [],
                "parent": None,
                "line": 1,
                "end_line": 2,
                "byte_offset": 0,
                "byte_length": 50,
                "content_hash": "",
                "ecosystem_context": "",
                "cyclomatic": 0,
                "max_nesting": 0,
                "param_count": 0,
                "call_references": [],
            }
        ]
        result = self._round_trip_symbols(symbols, tmp_path)
        assert len(result) == 1
        assert result[0]["call_references"] == []

    def test_legacy_v4_json_object_still_parsed(self, tmp_path):
        """Legacy v4 row with JSON object in data column still parses correctly."""
        from jcodemunch_mcp.storage.sqlite_store import SQLiteIndexStore

        store = SQLiteIndexStore(base_path=str(tmp_path / "store"))
        db_path = tmp_path / "test.db"
        conn = store._connect(db_path)

        # Simulate a legacy v4 row: data column contains a JSON object
        legacy_data = json.dumps({
            "qualified_name": "LegacyClass.legacy_method",
            "language": "python",
            "decorators": ["@deprecated"],
            "keywords": ["legacy"],
            "content_hash": "abc123",
            "ecosystem_context": "",
        })

        conn.execute(
            "INSERT INTO symbols (id, file, name, kind, signature, summary, docstring, "
            "line, end_line, byte_offset, byte_length, parent, qualified_name, language, "
            "decorators, keywords, content_hash, ecosystem_context, data, cyclomatic, "
            "max_nesting, param_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy.py::LegacyClass.legacy_method#method",
                "legacy.py",
                "legacy_method",
                "method",
                "def legacy_method(self)",
                "",
                "",
                10,
                15,
                100,
                200,
                None,
                "LegacyClass.legacy_method",
                "python",
                "[]",
                "[]",
                "abc123",
                "",
                legacy_data,  # JSON object in data column
                None,
                None,
                None,
            ),
        )
        conn.commit()

        rows = conn.execute("SELECT * FROM symbols").fetchall()
        col_names = [description[0] for description in conn.execute("SELECT * FROM symbols").description]
        for row in rows:
            row_dict = dict(zip(col_names, row))
            result = store._row_to_symbol_dict(row_dict)
            assert result["qualified_name"] == "LegacyClass.legacy_method"
            assert result["decorators"] == ["@deprecated"]
            # call_references should be [] for legacy rows
            assert result["call_references"] == []

    def test_symbol_to_row_includes_call_references(self):
        """_symbol_to_row serializes call_references to data column."""
        from jcodemunch_mcp.storage.sqlite_store import SQLiteIndexStore

        store = SQLiteIndexStore(base_path=None)  # doesn't need actual path for this test
        sym = Symbol(
            id="src/main.py::foo#function",
            file="src/main.py",
            name="foo",
            qualified_name="foo",
            kind="function",
            language="python",
            signature="def foo()",
            call_references=["helper", "validate"],
        )
        row = store._symbol_to_row(sym)
        # row[18] is the data column (0-indexed)
        data_idx = 18
        assert row[data_idx] == '["helper", "validate"]'

    def test_symbol_to_row_empty_call_references(self):
        """_symbol_to_row with empty call_references writes None to data column."""
        from jcodemunch_mcp.storage.sqlite_store import SQLiteIndexStore

        store = SQLiteIndexStore(base_path=None)
        sym = Symbol(
            id="src/main.py::foo#function",
            file="src/main.py",
            name="foo",
            qualified_name="foo",
            kind="function",
            language="python",
            signature="def foo()",
            call_references=[],
        )
        row = store._symbol_to_row(sym)
        data_idx = 18
        # Empty list -> None (no data to store)
        assert row[data_idx] is None

    def test_symbol_to_dict_includes_call_references(self):
        """_symbol_to_dict includes call_references in output dict."""
        from jcodemunch_mcp.storage.sqlite_store import SQLiteIndexStore

        store = SQLiteIndexStore(base_path=None)
        sym = Symbol(
            id="src/main.py::foo#function",
            file="src/main.py",
            name="foo",
            qualified_name="foo",
            kind="function",
            language="python",
            signature="def foo()",
            call_references=["bar"],
        )
        d = store._symbol_to_dict(sym)
        assert "call_references" in d
        assert d["call_references"] == ["bar"]

    def test_v7_index_loads_with_call_references_defaulting_to_empty(self, tmp_path):
        """Old v7 index (no call_references field) loads with call_references=[]."""
        from jcodemunch_mcp.storage.sqlite_store import SQLiteIndexStore

        store = SQLiteIndexStore(base_path=str(tmp_path / "store"))
        db_path = tmp_path / "test.db"
        conn = store._connect(db_path)

        # Insert a symbol without call_references (simulating old v7 index)
        conn.execute(
            "INSERT INTO symbols (id, file, name, kind, signature, summary, docstring, "
            "line, end_line, byte_offset, byte_length, parent, qualified_name, language, "
            "decorators, keywords, content_hash, ecosystem_context, data, cyclomatic, "
            "max_nesting, param_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "src/main.py::foo#function",
                "src/main.py",
                "foo",
                "function",
                "def foo()",
                "",
                "",
                1,
                2,
                0,
                50,
                None,
                "foo",
                "python",
                "[]",
                "[]",
                "",
                "",
                None,  # data column is None (v5+ format)
                None,
                None,
                None,
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("index_version", "7"),
        )
        conn.commit()

        rows = conn.execute("SELECT * FROM symbols").fetchall()
        col_names = [description[0] for description in conn.execute("SELECT * FROM symbols").description]
        for row in rows:
            row_dict = dict(zip(col_names, row))
            result = store._row_to_symbol_dict(row_dict)
            # call_references should default to [] for old indexes
            assert result["call_references"] == []
