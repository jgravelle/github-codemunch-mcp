"""Tests for Task 2: AST-based call reference extraction during parsing."""

import pytest

from jcodemunch_mcp.parser.extractor import parse_file


class TestPythonCallExtraction:
    """Call extraction for Python."""

    def test_simple_function_call(self):
        """def foo(): bar() -> foo.call_references == ["bar"]"""
        code = 'def foo():\n    bar()\n'
        symbols = parse_file(code, "test.py", "python")
        foo_sym = next((s for s in symbols if s.name == "foo"), None)
        assert foo_sym is not None
        assert "bar" in foo_sym.call_references

    def test_no_calls(self):
        """No function calls -> call_references == []"""
        code = 'def foo():\n    x = 1\n    return x\n'
        symbols = parse_file(code, "test.py", "python")
        foo_sym = next((s for s in symbols if s.name == "foo"), None)
        assert foo_sym is not None
        assert foo_sym.call_references == []

    def test_multiple_calls(self):
        """Multiple calls in one function."""
        code = 'def process():\n    validate()\n    save()\n    notify()\n'
        symbols = parse_file(code, "test.py", "python")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        assert set(process_sym.call_references) == {"validate", "save", "notify"}

    def test_self_recursion_excluded(self):
        """Self-recursion is excluded: def foo(): foo() -> call_references == []"""
        code = 'def foo():\n    foo()\n    return 1\n'
        symbols = parse_file(code, "test.py", "python")
        foo_sym = next((s for s in symbols if s.name == "foo"), None)
        assert foo_sym is not None
        assert "foo" not in foo_sym.call_references

    def test_nested_functions_calls_attributed_to_correct_enclosing(self):
        """Calls in nested functions attributed to correct enclosing symbol."""
        code = 'def outer():\n    def inner():\n        helper()\n    inner()\n'
        symbols = parse_file(code, "test.py", "python")
        outer_sym = next((s for s in symbols if s.name == "outer"), None)
        inner_sym = next((s for s in symbols if s.name == "inner"), None)
        assert outer_sym is not None
        assert inner_sym is not None
        # outer calls inner; inner calls helper
        assert "inner" in outer_sym.call_references
        assert "helper" in inner_sym.call_references

    def test_method_call(self):
        """obj.method() extracts "method" not "obj"."""
        code = 'def process():\n    obj.save()\n    db.query()\n'
        symbols = parse_file(code, "test.py", "python")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        assert "save" in process_sym.call_references
        assert "query" in process_sym.call_references
        # The object names should not be included
        assert "obj" not in process_sym.call_references
        assert "db" not in process_sym.call_references

    def test_class_method_calls_own_class_method(self):
        """Within a class, method calls own class method."""
        code = '''class Service:
    def process(self):
        self.validate()
        self.save()
'''
        symbols = parse_file(code, "test.py", "python")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        # self.validate and self.save should extract validate and save
        assert "validate" in process_sym.call_references
        assert "save" in process_sym.call_references


class TestJavaScriptCallExtraction:
    """Call extraction for JavaScript."""

    def test_simple_call(self):
        """function process() { helper(); } -> ["helper"]"""
        code = 'function process() {\n    helper();\n}\n'
        symbols = parse_file(code, "test.js", "javascript")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        assert "helper" in process_sym.call_references

    def test_member_expression_call(self):
        """obj.method() extracts "method"."""
        code = 'function process() {\n    obj.method();\n    obj.save();\n}\n'
        symbols = parse_file(code, "test.js", "javascript")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        assert "method" in process_sym.call_references
        assert "save" in process_sym.call_references

    def test_nested_calls(self):
        """Multiple nested calls."""
        code = 'function process() {\n    fetch(api).then(x => x.json());\n}\n'
        symbols = parse_file(code, "test.js", "javascript")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        # The then call should be extracted
        assert "then" in process_sym.call_references


class TestTypeScriptCallExtraction:
    """Call extraction for TypeScript."""

    def test_typescript_call(self):
        """Same as JavaScript since TS uses same parser."""
        code = 'function process() {\n    helper();\n    obj.save();\n}\n'
        symbols = parse_file(code, "test.ts", "typescript")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        assert "helper" in process_sym.call_references
        assert "save" in process_sym.call_references


class TestGoCallExtraction:
    """Call extraction for Go."""

    def test_go_call(self):
        """func process() { helper(); } -> ["helper"]"""
        code = 'package main\n\nfunc process() {\n    helper()\n}\n'
        symbols = parse_file(code, "test.go", "go")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        assert "helper" in process_sym.call_references


class TestRustCallExtraction:
    """Call extraction for Rust."""

    def test_rust_call(self):
        """fn process() { helper(); } -> ["helper"]"""
        code = 'fn process() {\n    helper();\n}\n'
        symbols = parse_file(code, "test.rs", "rust")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        assert "helper" in process_sym.call_references


class TestJavaCallExtraction:
    """Call extraction for Java."""

    def test_java_method_invocation(self):
        """void process() { helper(); } -> ["helper"]"""
        code = 'class Test {\n    void process() {\n        helper();\n    }\n}\n'
        symbols = parse_file(code, "test.java", "java")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        assert "helper" in process_sym.call_references


class TestRubyCallExtraction:
    """Call extraction for Ruby."""

    def test_ruby_call(self):
        """def process; helper(); end -> ["helper"]"""
        code = 'def process\n    helper()\nend\n'
        symbols = parse_file(code, "test.rb", "ruby")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        assert "helper" in process_sym.call_references


class TestCSCallExtraction:
    """Call extraction for C#."""

    def test_csharp_invocation(self):
        """void Process() { helper(); } -> ["helper"]"""
        code = 'class Test {\n    void Process() {\n        helper();\n    }\n}\n'
        symbols = parse_file(code, "test.cs", "csharp")
        process_sym = next((s for s in symbols if s.name == "Process"), None)
        assert process_sym is not None
        assert "helper" in process_sym.call_references


class TestCallNodeTypes:
    """Verify correct node types are used for each language."""

    def test_unsupported_language_no_crash(self):
        """Unsupported language should not crash - call_references stays empty."""
        code = 'def foo():\n    bar()\n'
        symbols = parse_file(code, "test.xyz", "unknown_language")
        # Should not crash - returns symbols without call_references
        assert isinstance(symbols, list)


class TestCallReferenceDeduplication:
    """Same call appearing multiple times should be deduplicated."""

    def test_duplicate_calls_deduplicated(self):
        """Same function called twice -> only one entry in call_references."""
        code = 'def process():\n    log()\n    log()\n    save()\n'
        symbols = parse_file(code, "test.py", "python")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        # log appears twice but should only be in call_references once
        assert process_sym.call_references.count("log") == 1
        assert "log" in process_sym.call_references
        assert "save" in process_sym.call_references


class TestCallReferenceOrdering:
    """Call references should preserve order of appearance."""

    def test_order_preserved(self):
        """Calls appear in order of source position."""
        code = 'def process():\n    first()\n    second()\n    third()\n'
        symbols = parse_file(code, "test.py", "python")
        process_sym = next((s for s in symbols if s.name == "process"), None)
        assert process_sym is not None
        assert process_sym.call_references == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# Constructor call extraction tests
# ---------------------------------------------------------------------------

class TestConstructorCallExtraction:
    """Constructor calls (new Foo()) should be extracted as call references."""

    def test_js_new_expression(self):
        """new Date() in JavaScript -> "Date" in call_references."""
        code = 'function foo() {\n    let d = new Date();\n}\n'
        symbols = parse_file(code, "test.js", "javascript")
        foo = next((s for s in symbols if s.name == "foo"), None)
        assert foo is not None
        assert "Date" in foo.call_references

    def test_js_new_mixed_with_regular_calls(self):
        """new and regular calls both extracted."""
        code = 'function foo() {\n    new Map();\n    bar();\n}\n'
        symbols = parse_file(code, "test.js", "javascript")
        foo = next((s for s in symbols if s.name == "foo"), None)
        assert foo is not None
        assert "Map" in foo.call_references
        assert "bar" in foo.call_references

    def test_ts_new_expression(self):
        """new Map() in TypeScript."""
        code = 'function foo(): void {\n    const m = new Map();\n}\n'
        symbols = parse_file(code, "test.ts", "typescript")
        foo = next((s for s in symbols if s.name == "foo"), None)
        assert foo is not None
        assert "Map" in foo.call_references

    def test_tsx_new_expression(self):
        """new Set() in TSX."""
        code = 'function foo() {\n    const s = new Set();\n}\n'
        symbols = parse_file(code, "test.tsx", "tsx")
        foo = next((s for s in symbols if s.name == "foo"), None)
        assert foo is not None
        assert "Set" in foo.call_references

    def test_java_object_creation(self):
        """new Bar() in Java -> "Bar" in call_references."""
        code = 'class Foo {\n    void run() {\n        Bar b = new Bar();\n    }\n}\n'
        symbols = parse_file(code, "Test.java", "java")
        run = next((s for s in symbols if s.name == "run"), None)
        assert run is not None
        assert "Bar" in run.call_references
