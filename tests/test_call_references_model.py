"""Tests for Task 1: call_references data model — Symbol field, INDEX_VERSION 9, SQLite storage."""

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
    """INDEX_VERSION is bumped to 9."""

    def test_index_version_is_9(self):
        """INDEX_VERSION constant must be 9 after this change."""
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

    def test_v8_row_preserves_metadata(self, tmp_path):
        """v8 row (data as JSON array) preserves qualified_name, language, decorators, keywords, content_hash, ecosystem_context from row columns."""
        from jcodemunch_mcp.storage.sqlite_store import SQLiteIndexStore

        store = SQLiteIndexStore(base_path=str(tmp_path / "store"))
        db_path = tmp_path / "test.db"
        conn = store._connect(db_path)

        # Insert a raw v8 row: data column is a JSON array (call_references)
        conn.execute(
            "INSERT INTO symbols (id, file, name, kind, signature, summary, docstring, "
            "line, end_line, byte_offset, byte_length, parent, qualified_name, language, "
            "decorators, keywords, content_hash, ecosystem_context, data, cyclomatic, "
            "max_nesting, param_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "src/orders.py::AppToolOrders._build_left_pane_cache#method",
                "src/orders.py",
                "_build_left_pane_cache",
                "method",
                "def _build_left_pane_cache(self, request)",
                "Builds the left pane cache.",
                "",
                50,
                75,
                100,
                500,
                "AppToolOrders",
                "AppToolOrders._build_left_pane_cache",
                "python",
                '["@cache", "@logged"]',
                '["cache", "pane"]',
                "abc123def456",
                '{"cache": "redis"}',
                '["_render_row", "helper"]',  # v8: data is JSON array of call_references
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
            # These fields must come from row columns, NOT from data JSON (which is an array)
            assert result["qualified_name"] == "AppToolOrders._build_left_pane_cache", f"qualified_name mismatch: {result['qualified_name']}"
            assert result["language"] == "python", f"language mismatch: {result['language']}"
            assert result["decorators"] == ["@cache", "@logged"], f"decorators mismatch: {result['decorators']}"
            assert result["keywords"] == ["cache", "pane"], f"keywords mismatch: {result['keywords']}"
            assert result["content_hash"] == "abc123def456", f"content_hash mismatch: {result['content_hash']}"
            assert result["ecosystem_context"] == '{"cache": "redis"}', f"ecosystem_context mismatch: {result['ecosystem_context']}"
            # call_references must be deserialized from the data array
            assert result["call_references"] == ["_render_row", "helper"], f"call_references mismatch: {result['call_references']}"

    def test_v8_row_qualified_name_from_row_not_name(self, tmp_path):
        """When data is a JSON array, qualified_name must come from row['qualified_name'], not row['name']."""
        from jcodemunch_mcp.storage.sqlite_store import SQLiteIndexStore

        store = SQLiteIndexStore(base_path=str(tmp_path / "store"))
        db_path = tmp_path / "test.db"
        conn = store._connect(db_path)

        # Insert a v8 row where name differs from qualified_name
        conn.execute(
            "INSERT INTO symbols (id, file, name, kind, signature, summary, docstring, "
            "line, end_line, byte_offset, byte_length, parent, qualified_name, language, "
            "decorators, keywords, content_hash, ecosystem_context, data, cyclomatic, "
            "max_nesting, param_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "src/ui.py::UIContainer.build_pane#method",
                "src/ui.py",
                "build_pane",  # short name
                "method",
                "def build_pane(self)",
                "",
                "",
                10,
                20,
                0,
                100,
                "UIContainer",
                "UIContainer.build_pane",  # fully qualified name
                "python",
                "[]",
                "[]",
                "",
                "",
                '["helper"]',  # v8: call_references in data array
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
            # qualified_name must be the full path, not just "build_pane"
            assert result["qualified_name"] == "UIContainer.build_pane", f"qualified_name should be 'UIContainer.build_pane', got: {result['qualified_name']}"
            assert result["name"] == "build_pane"
            assert result["call_references"] == ["helper"]

    def test_v8_row_logs_invalid_decorators_and_keywords_json(self, tmp_path, caplog):
        """v8 rows should log warnings when decorators/keywords JSON is corrupted."""
        from jcodemunch_mcp.storage.sqlite_store import SQLiteIndexStore

        store = SQLiteIndexStore(base_path=str(tmp_path / "store"))
        db_path = tmp_path / "test.db"
        conn = store._connect(db_path)

        conn.execute(
            "INSERT INTO symbols (id, file, name, kind, signature, summary, docstring, "
            "line, end_line, byte_offset, byte_length, parent, qualified_name, language, "
            "decorators, keywords, content_hash, ecosystem_context, data, cyclomatic, "
            "max_nesting, param_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "src/ui.py::UIContainer.build_pane#method",
                "src/ui.py",
                "build_pane",
                "method",
                "def build_pane(self)",
                "",
                "",
                10,
                20,
                0,
                100,
                "UIContainer",
                "UIContainer.build_pane",
                "python",
                "[not valid json",
                "{not valid json",
                "",
                "",
                '["helper"]',
                None,
                None,
                None,
            ),
        )
        conn.commit()

        rows = conn.execute("SELECT * FROM symbols").fetchall()
        col_names = [description[0] for description in conn.execute("SELECT * FROM symbols").description]

        with caplog.at_level("WARNING"):
            row_dict = dict(zip(col_names, rows[0]))
            result = store._row_to_symbol_dict(row_dict)

        assert result["decorators"] == []
        assert result["keywords"] == []
        assert "Corrupted decorators JSON for symbol build_pane" in caplog.text
        assert "Corrupted keywords JSON for symbol build_pane" in caplog.text

    def test_v8_row_with_corrupt_data_json_keeps_row_metadata(self, tmp_path, caplog):
        """Corrupt v8 data JSON should still fall back to row metadata columns."""
        from jcodemunch_mcp.storage.sqlite_store import SQLiteIndexStore

        store = SQLiteIndexStore(base_path=str(tmp_path / "store"))
        db_path = tmp_path / "test.db"
        conn = store._connect(db_path)

        conn.execute(
            "INSERT INTO symbols (id, file, name, kind, signature, summary, docstring, "
            "line, end_line, byte_offset, byte_length, parent, qualified_name, language, "
            "decorators, keywords, content_hash, ecosystem_context, data, cyclomatic, "
            "max_nesting, param_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "src/ui.py::UIContainer.build_pane#method",
                "src/ui.py",
                "build_pane",
                "method",
                "def build_pane(self)",
                "",
                "",
                10,
                20,
                0,
                100,
                "UIContainer",
                "UIContainer.build_pane",
                "python",
                '["@cached"]',
                '["pane"]',
                "abc123",
                '{"ui": "left-pane"}',
                "{not valid json",
                None,
                None,
                None,
            ),
        )
        conn.commit()

        rows = conn.execute("SELECT * FROM symbols").fetchall()
        col_names = [description[0] for description in conn.execute("SELECT * FROM symbols").description]

        with caplog.at_level("WARNING"):
            row_dict = dict(zip(col_names, rows[0]))
            result = store._row_to_symbol_dict(row_dict)

        assert result["qualified_name"] == "UIContainer.build_pane"
        assert result["language"] == "python"
        assert result["decorators"] == ["@cached"]
        assert result["keywords"] == ["pane"]
        assert result["content_hash"] == "abc123"
        assert result["ecosystem_context"] == '{"ui": "left-pane"}'
        assert result["call_references"] == []
        assert "Corrupted JSON in symbol data column for row build_pane" in caplog.text

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
