"""Tests for T17 (missing_extractors / parse_warnings) and T18 (framework_warning).

T17: index_folder reports missing_extractors when a language has symbol extraction
     but no import extraction. Example: Elixir has symbols but no import extractor.
     (Dart had this gap in Phase 5 and was fixed in Phase 6 via T19.)

T18: get_dead_code_v2 emits framework_warning when no standard entry points are found.
"""

import pytest

from jcodemunch_mcp.tools.index_folder import index_folder
from jcodemunch_mcp.tools.get_dead_code_v2 import get_dead_code_v2


# ---------------------------------------------------------------------------
# T17 — missing_extractors
# ---------------------------------------------------------------------------

class TestMissingExtractors:

    def test_elixir_produces_missing_extractors(self, tmp_path):
        """Indexing an Elixir file should report missing_extractors: ['elixir'].

        Elixir has tree-sitter symbol extraction but no import extractor in
        _LANGUAGE_EXTRACTORS. Dart had this gap in Phase 5; it was closed in
        Phase 6 via T19. Elixir remains a representative example.
        """
        src = tmp_path / "src"
        store = tmp_path / "store"
        src.mkdir()
        store.mkdir()

        (src / "app.ex").write_text(
            "defmodule MyApp do\n  def hello(name) do\n    name\n  end\nend\n"
        )

        r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert r["success"] is True, f"index_folder failed: {r}"

        # Elixir has symbol extraction but no import extractor
        assert "missing_extractors" in r, (
            f"Expected 'missing_extractors' in result. Got: {list(r.keys())}"
        )
        assert "elixir" in r["missing_extractors"], (
            f"Expected 'elixir' in missing_extractors, got: {r['missing_extractors']}"
        )

    def test_missing_extractors_not_present_for_python_only(self, tmp_path):
        """Python has both symbol and import extraction — no missing_extractors."""
        src = tmp_path / "src"
        store = tmp_path / "store"
        src.mkdir()
        store.mkdir()

        (src / "utils.py").write_text(
            "def add(a, b):\n    return a + b\n"
        )

        r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert r["success"] is True

        # Python has full import extraction — should not appear
        missing = r.get("missing_extractors", [])
        assert "python" not in missing

    def test_parse_warnings_included_when_extractors_missing(self, tmp_path):
        """parse_warnings should be present alongside missing_extractors."""
        src = tmp_path / "src"
        store = tmp_path / "store"
        src.mkdir()
        store.mkdir()

        (src / "app.ex").write_text(
            "defmodule App do\n  def run(), do: :ok\nend\n"
        )

        r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert r["success"] is True

        if "missing_extractors" not in r:
            pytest.skip("Elixir symbols not extracted in this environment")

        assert "parse_warnings" in r
        assert any("elixir" in w.lower() for w in r["parse_warnings"]), (
            f"Expected elixir mention in parse_warnings: {r['parse_warnings']}"
        )

    def test_missing_extractors_is_sorted_list(self, tmp_path):
        """missing_extractors must be a sorted list (stable output)."""
        src = tmp_path / "src"
        store = tmp_path / "store"
        src.mkdir()
        store.mkdir()

        (src / "app.ex").write_text(
            "defmodule App do\n  def run(), do: :ok\nend\n"
        )

        r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert r["success"] is True

        if "missing_extractors" not in r:
            pytest.skip("Elixir symbols not extracted in this environment")

        extractors = r["missing_extractors"]
        assert isinstance(extractors, list)
        assert extractors == sorted(extractors)


# ---------------------------------------------------------------------------
# T18 — framework_warning in get_dead_code_v2
# ---------------------------------------------------------------------------

class TestFrameworkWarning:

    def _build_no_entrypoint_repo(self, tmp_path):
        """Build a repo with no standard entry points (no main.py, app.py, etc.)."""
        src = tmp_path / "src"
        store = tmp_path / "store"
        src.mkdir()
        store.mkdir()

        # Helper module (no entry-point filename)
        (src / "helpers.py").write_text(
            "def compute(x):\n    return x * 2\n\n"
            "def transform(data):\n    return [compute(d) for d in data]\n"
        )
        # Models imports helpers to create import data in the index
        (src / "models.py").write_text(
            "from helpers import compute\n\n"
            "class Item:\n    def process(self, value):\n        return compute(value)\n"
        )

        r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert r["success"] is True
        return r["repo"], str(store)

    def test_framework_warning_present_when_no_entry_points(self, tmp_path):
        """When no entry points exist, framework_warning must be in the response."""
        repo, store = self._build_no_entrypoint_repo(tmp_path)
        r = get_dead_code_v2(repo=repo, storage_path=store)
        assert "framework_warning" in r, (
            f"Expected framework_warning in result. Got keys: {list(r.keys())}"
        )

    def test_framework_warning_mentions_entry_points(self, tmp_path):
        """framework_warning text should mention entry points."""
        repo, store = self._build_no_entrypoint_repo(tmp_path)
        r = get_dead_code_v2(repo=repo, storage_path=store)
        if "framework_warning" not in r:
            pytest.skip("No framework_warning in result")
        assert "entry point" in r["framework_warning"].lower()

    def test_no_framework_warning_when_entry_point_present(self, tmp_path):
        """When main.py is present, framework_warning must NOT appear."""
        src = tmp_path / "src"
        store = tmp_path / "store"
        src.mkdir()
        store.mkdir()

        (src / "main.py").write_text(
            "from helpers import compute\n\n"
            "if __name__ == '__main__':\n    print(compute(5))\n"
        )
        (src / "helpers.py").write_text(
            "def compute(x):\n    return x * 2\n"
        )

        r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert r["success"] is True
        repo = r["repo"]

        result = get_dead_code_v2(repo=repo, storage_path=store)
        assert "framework_warning" not in result, (
            f"Unexpected framework_warning: {result.get('framework_warning')}"
        )

    def test_framework_warning_not_present_with_app_py(self, tmp_path):
        """app.py is a recognised entry point — no framework_warning."""
        src = tmp_path / "src"
        store = tmp_path / "store"
        src.mkdir()
        store.mkdir()

        (src / "app.py").write_text("def run():\n    pass\n")
        (src / "utils.py").write_text("def helper():\n    pass\n")

        r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert r["success"] is True

        result = get_dead_code_v2(repo=r["repo"], storage_path=store)
        assert "framework_warning" not in result

    def test_dead_code_meta_methodology(self, tmp_path):
        """get_dead_code_v2 _meta should include methodology + confidence_level."""
        repo, store = self._build_no_entrypoint_repo(tmp_path)
        r = get_dead_code_v2(repo=repo, storage_path=store)
        assert "_meta" in r
        assert r["_meta"].get("methodology") == "multi_signal"
        assert r["_meta"].get("confidence_level") == "medium"
