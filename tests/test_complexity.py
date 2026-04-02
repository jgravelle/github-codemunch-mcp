"""Tests for parser/complexity.py metrics."""

from jcodemunch_mcp.parser.complexity import compute_complexity, _count_params, _max_nesting_depth


class TestCountParams:
    def test_no_params(self):
        assert _count_params("def foo()") == 0

    def test_one_param(self):
        assert _count_params("def foo(x)") == 1

    def test_multiple_params(self):
        assert _count_params("def foo(x, y, z)") == 3

    def test_nested_generic(self):
        # Generic type in param: dict[str, int] shouldn't split on inner comma
        assert _count_params("def foo(x: dict[str, int], y: int)") == 2

    def test_empty_string(self):
        assert _count_params("") == 0


class TestMaxNestingDepth:
    def test_flat_code(self):
        assert _max_nesting_depth("def foo(): return 1") == 0

    def test_one_level_deep(self):
        # C/JS style: bracket-based nesting
        body = "function foo() { if (x) { return 1; } }"
        assert _max_nesting_depth(body) >= 1

    def test_deeply_nested(self):
        body = "function foo() { { { { return 1; } } } }"
        assert _max_nesting_depth(body) >= 3


class TestComputeComplexity:
    def test_simple_function(self):
        body = "def foo():\n    return 42\n"
        cyc, nesting, params = compute_complexity(body)
        assert cyc == 1  # no branches
        assert nesting >= 0
        assert params >= 0

    def test_if_increases_cyclomatic(self):
        body = "def foo(x):\n    if x > 0:\n        return 1\n    return 0\n"
        cyc, _, _ = compute_complexity(body)
        assert cyc > 1

    def test_multiple_branches(self):
        body = (
            "def foo(x, y):\n"
            "    if x:\n"
            "        if y:\n"
            "            return 1\n"
            "        elif y < 0:\n"
            "            return -1\n"
            "        else:\n"
            "            return 0\n"
            "    return -2\n"
        )
        cyc, _, _ = compute_complexity(body)
        assert cyc >= 4

    def test_signature_param_count(self):
        body = "def foo(a, b, c):\n    pass\n"
        _, _, params = compute_complexity(body, "def foo(a, b, c)")
        assert params == 3

    def test_for_loop_increments(self):
        body = "def foo():\n    for i in range(10):\n        pass\n"
        cyc, _, _ = compute_complexity(body)
        assert cyc >= 2

    def test_while_loop_increments(self):
        body = "def foo():\n    while True:\n        break\n"
        cyc, _, _ = compute_complexity(body)
        assert cyc >= 2

    def test_empty_body(self):
        cyc, nesting, params = compute_complexity("")
        assert cyc == 1
        assert nesting == 0
        assert params == 0
