"""Regression tests for v1.80.9 — lodash-class repos that the v1.80.7/.8
work didn't cover. Two compounding issues from sverklo bench round-2:

1. **Force-include `package.json` `main`/`module`/`exports`/`bin` files
   regardless of the per-file size cap.** Lodash 4.17.21 ships as a single
   17K-line monolithic UMD/IIFE (548 KB); the 500 KB default size cap
   excluded it from the index entirely, leaving the package's published
   methods invisible to dead-code analysis (recall=0 in the bench).

2. **Call-graph-only fallback when `index.imports` is empty.** Single-file
   projects (lodash 4.x, monolithic IIFEs, pre-bundled libraries) have no
   inter-file imports — the standard 3-signal analyzer has no graph to
   walk. Pre-1.80.9 the tool returned `{"error": "No import data..."}`,
   which the bench scored as zero predictions. Now falls through to a
   call-graph-only mode using AST `call_references`.
"""

from __future__ import annotations

from jcodemunch_mcp.tools.get_dead_code_v2 import get_dead_code_v2
from jcodemunch_mcp.tools.index_folder import (
    index_folder,
    _scan_package_json_forced_paths,
)


class TestPackageJsonForcedPaths:
    def test_resolves_main_field(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"name":"x","main":"./big.js"}', encoding="utf-8"
        )
        big = tmp_path / "big.js"
        big.write_text("// content\n" * 100, encoding="utf-8")
        forced = _scan_package_json_forced_paths(tmp_path)
        assert str(big.resolve()) in forced

    def test_resolves_extension_less_main(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"name":"x","main":"./entry"}', encoding="utf-8"
        )
        (tmp_path / "entry.js").write_text("// x\n", encoding="utf-8")
        forced = _scan_package_json_forced_paths(tmp_path)
        assert any(p.endswith("entry.js") for p in forced)

    def test_resolves_exports_dict(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"name":"x","exports":{".":"./api.js","./util":"./util.js"}}',
            encoding="utf-8",
        )
        (tmp_path / "api.js").write_text("// a\n", encoding="utf-8")
        (tmp_path / "util.js").write_text("// u\n", encoding="utf-8")
        forced = _scan_package_json_forced_paths(tmp_path)
        names = {p.replace("\\", "/").rsplit("/", 1)[-1] for p in forced}
        assert "api.js" in names
        assert "util.js" in names

    def test_resolves_bin_dict(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"name":"x","bin":{"mycli":"./cli/main.js"}}', encoding="utf-8"
        )
        cli = tmp_path / "cli"
        cli.mkdir()
        (cli / "main.js").write_text("// cli\n", encoding="utf-8")
        forced = _scan_package_json_forced_paths(tmp_path)
        assert any(p.endswith("main.js") for p in forced)

    def test_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "left-pad"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text(
            '{"name":"left-pad","main":"./index.js"}', encoding="utf-8"
        )
        (nm / "index.js").write_text("// x\n", encoding="utf-8")
        forced = _scan_package_json_forced_paths(tmp_path)
        assert not forced, (
            f"node_modules manifests must not influence forced indexing. "
            f"Got: {forced}"
        )

    def test_handles_malformed_json(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"name":"x", broken json', encoding="utf-8"
        )
        # Must not raise.
        forced = _scan_package_json_forced_paths(tmp_path)
        assert forced == set()


class TestSizeCapExemption:
    """End-to-end: a 600 KB main file should be indexed despite the
    500 KB default cap when it's referenced by package.json `main`."""

    def test_oversized_main_is_indexed(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"name":"big-lib","main":"./monolith.js"}', encoding="utf-8"
        )
        # 600 KB of trivial JS.
        body = "function foo() { return 1; }\n" * 25_000
        (tmp_path / "monolith.js").write_text(body, encoding="utf-8")
        store = tmp_path / ".idx"
        store.mkdir()
        # Baseline: also write a small file so something else gets indexed
        # too and we can assert monolith.js specifically passed.
        (tmp_path / "tiny.js").write_text("function bar() {}\n",
                                          encoding="utf-8")
        r = index_folder(str(tmp_path), use_ai_summaries=False,
                         storage_path=str(store))
        assert r["success"] is True
        # monolith.js is ~700KB > 500KB cap, must be indexed via the
        # package.json forced-path mechanism.
        assert "monolith.js" in r.get("files", []) or any(
            f.endswith("monolith.js") for f in r.get("files", [])
        ), f"monolith.js missing from indexed files: {r.get('files')}"


class TestCallGraphOnlyFallback:
    """End-to-end: a project with symbols but no import edges should
    return dead-code candidates via call-graph-only mode, not error out."""

    def test_returns_candidates_in_fallback_mode(self, tmp_path):
        # Single Python file, no imports between files (just an `import os`
        # within the one file isn't enough — index.imports needs to be
        # truthy at the file level for the standard analyzer to run; the
        # fallback fires when imports is empty/falsy).
        # Simplest: a JS file with just function defs, no requires.
        (tmp_path / "package.json").write_text(
            '{"name":"mono","main":"./mono.js"}', encoding="utf-8"
        )
        (tmp_path / "mono.js").write_text(
            "function publicApi() { return helper(); }\n"
            "function helper() { return 42; }\n"
            "function notCalledAnywhere() { return 'dead'; }\n",
            encoding="utf-8",
        )
        store = tmp_path / ".idx"
        store.mkdir()
        r = index_folder(str(tmp_path), use_ai_summaries=False,
                         storage_path=str(store))

        result = get_dead_code_v2(repo=r["repo"], min_confidence=0.5,
                                  storage_path=str(store))
        # The fallback may or may not fire depending on whether the JS
        # parser captured any import-shaped edges from the file. Two
        # acceptable outcomes:
        #   (a) standard 3-signal mode runs and returns valid output
        #       (no error key)
        #   (b) call_graph_only mode runs and returns a non-error response
        # The pre-1.80.9 behavior of returning {"error": "No import data..."}
        # is what we're guarding against.
        assert "error" not in result, (
            f"Tool must not error out on monolithic single-file repos; "
            f"got: {result.get('error')}"
        )
        assert "dead_symbols" in result
        assert "_meta" in result

    def test_fallback_helper_directly(self):
        """Direct unit test of _call_graph_only_dead_code: a synthetic
        index-like object with no imports should produce candidates only
        for symbols whose names appear in nobody's call_references.
        Easier to assert than going through the full save/load cycle.
        """
        from jcodemunch_mcp.tools.get_dead_code_v2 import (
            _call_graph_only_dead_code,
        )

        class _FakeIndex:
            symbols = [
                {"id": "mono.js::publicApi#function", "name": "publicApi",
                 "kind": "function", "file": "mono.js", "line": 1,
                 "call_references": ["helper"]},
                {"id": "mono.js::helper#function", "name": "helper",
                 "kind": "function", "file": "mono.js", "line": 2,
                 "call_references": []},
                {"id": "mono.js::dead#function", "name": "dead",
                 "kind": "function", "file": "mono.js", "line": 3,
                 "call_references": []},
            ]

            def get_callers_by_name(self):
                # (caller_file, called_name) -> [caller symbol IDs]
                return {("mono.js", "helper"): ["mono.js::publicApi#function"]}

        import time as _t
        result = _call_graph_only_dead_code(
            _FakeIndex(), "local", "mono", _t.monotonic(),
        )
        assert "error" not in result
        assert result["_meta"]["mode"] == "call_graph_only"
        assert "warning" in result["_meta"]
        names = {s["name"] for s in result["dead_symbols"]}
        # `dead` and `publicApi` are never called → flagged.
        # `helper` is called by publicApi → not flagged.
        assert "dead" in names
        assert "publicApi" in names
        assert "helper" not in names
        # All flagged symbols carry the single signal + 0.5 confidence.
        for s in result["dead_symbols"]:
            assert s["signals"] == ["no_callers"]
            assert s["confidence"] == 0.5
