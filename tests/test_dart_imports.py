"""Tests for Dart import extraction (T19)."""

from jcodemunch_mcp.parser.imports import extract_imports, _LANGUAGE_EXTRACTORS


DART_SOURCE = """\
import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import './models/user.dart';
import '../utils/helpers.dart';
export 'src/api.dart';
"""


class TestDartImports:

    def test_dart_in_language_extractors(self):
        """Dart must be registered in _LANGUAGE_EXTRACTORS."""
        assert "dart" in _LANGUAGE_EXTRACTORS

    def test_extracts_dart_stdlib_imports(self):
        edges = extract_imports(DART_SOURCE, "main.dart", "dart")
        specifiers = [e["specifier"] for e in edges]
        assert "dart:async" in specifiers
        assert "dart:io" in specifiers

    def test_extracts_package_imports(self):
        edges = extract_imports(DART_SOURCE, "main.dart", "dart")
        specifiers = [e["specifier"] for e in edges]
        assert "package:flutter/material.dart" in specifiers
        assert "package:provider/provider.dart" in specifiers

    def test_extracts_relative_imports(self):
        edges = extract_imports(DART_SOURCE, "main.dart", "dart")
        specifiers = [e["specifier"] for e in edges]
        assert "./models/user.dart" in specifiers
        assert "../utils/helpers.dart" in specifiers

    def test_extracts_export_as_edge(self):
        edges = extract_imports(DART_SOURCE, "main.dart", "dart")
        specifiers = [e["specifier"] for e in edges]
        assert "src/api.dart" in specifiers

    def test_names_are_empty_list(self):
        """Dart import edges carry no named imports (file-level only)."""
        edges = extract_imports(DART_SOURCE, "main.dart", "dart")
        for edge in edges:
            assert edge["names"] == []

    def test_edge_count(self):
        edges = extract_imports(DART_SOURCE, "main.dart", "dart")
        assert len(edges) == 7

    def test_no_false_positives_from_non_import_lines(self):
        source = "void main() {\n  print('import ignored');\n}\n"
        edges = extract_imports(source, "main.dart", "dart")
        assert edges == []

    def test_dart_not_in_missing_extractors_after_t19(self, tmp_path):
        """After T19, Dart should no longer appear in missing_extractors."""
        from jcodemunch_mcp.tools.index_folder import index_folder

        src = tmp_path / "src"
        store = tmp_path / "store"
        src.mkdir()
        store.mkdir()

        (src / "main.dart").write_text(
            "import 'dart:async';\n\nvoid main() {\n  print('hello');\n}\n\n"
            "class Greeter {\n  String greet(String name) => 'Hello, ${name}';\n}\n"
        )

        r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert r["success"] is True

        missing = r.get("missing_extractors", [])
        assert "dart" not in missing, (
            f"Dart should no longer be in missing_extractors after T19: {missing}"
        )
