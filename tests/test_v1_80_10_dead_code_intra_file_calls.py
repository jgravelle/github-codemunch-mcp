"""Regression tests for v1.80.10 — get_dead_code_v2 false positives on
functions that are defined and called within the same file.

Reproduces the issue surfaced by the sverklo benchmark
(https://github.com/sverklo/sverklo/issues/25 comment by @nike-17):

  jcodemunch v1.80.9 flagged `parseDeadCode` as dead even though it was
  defined at line 311 of `benchmark/src/baselines/jcodemunch.ts` and
  called at line 193 of the same file. Pre-1.80.10, the no_callers
  signal only checked files that imported the symbol's file — never the
  symbol's own file — so any intra-file caller was missed. Combined
  with `unreachable_file` (the file isn't imported by anything because
  it IS the entry) and `not_barrel_exported`, this produced confidence
  1.0 false positives.

Fix: include the symbol's own file in the no-callers search set, both
in the AST fast path and the text-heuristic fallback.
"""

from __future__ import annotations

from jcodemunch_mcp.tools.get_dead_code_v2 import get_dead_code_v2
from jcodemunch_mcp.tools.index_folder import index_folder


def _build_intra_file_caller_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    store = tmp_path / "store"
    store.mkdir()

    (src / "package.json").write_text(
        '{"name": "intra", "main": "./worker.js"}\n', encoding="utf-8"
    )
    # `parseThing` is defined and called inside the same file — no other
    # file imports it. Pre-fix, this was flagged as dead.
    (src / "worker.js").write_text(
        "function parseThing(x) {\n"
        "  return x.trim();\n"
        "}\n"
        "function run(input) {\n"
        "  return parseThing(input);\n"
        "}\n"
        "function actuallyDead() {\n"
        "  return null;\n"
        "}\n"
        "module.exports = { run };\n",
        encoding="utf-8",
    )
    r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
    assert r["success"] is True
    return r["repo"], str(store)


class TestIntraFileCallerNotDead:
    def test_intra_file_caller_not_flagged_as_dead(self, tmp_path):
        repo, store = _build_intra_file_caller_repo(tmp_path)
        result = get_dead_code_v2(repo=repo, min_confidence=0.33,
                                  storage_path=store)
        dead_names = {s["name"] for s in result.get("dead_symbols", [])}
        assert "parseThing" not in dead_names, (
            "parseThing is called by run() in the same file and must not "
            f"be flagged as dead. Got: {sorted(dead_names)}"
        )

    def test_genuinely_dead_intra_file_function_still_flagged(self, tmp_path):
        repo, store = _build_intra_file_caller_repo(tmp_path)
        result = get_dead_code_v2(repo=repo, min_confidence=0.33,
                                  storage_path=store)
        dead_names = {s["name"] for s in result.get("dead_symbols", [])}
        assert "actuallyDead" in dead_names, (
            "actuallyDead has no callers anywhere — the same-file fix must "
            f"not mask genuine dead code. Got: {sorted(dead_names)}"
        )
