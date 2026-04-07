"""Tests for get_blast_radius — depth scoring, risk fields, and include_source."""

import pytest
from jcodemunch_mcp.tools.get_blast_radius import (
    _bfs_importers,
    _extract_reference_snippets,
    _get_symbols_near_references,
    get_blast_radius,
)
from jcodemunch_mcp.tools.index_folder import index_folder


# ---------------------------------------------------------------------------
# Unit tests: _bfs_importers returns depth-bucketed results
# ---------------------------------------------------------------------------

class TestBfsImportersWithDepth:

    def _rev(self):
        # a → b → c → d (linear chain)
        return {
            "a.py": ["b.py"],
            "b.py": ["c.py"],
            "c.py": ["d.py"],
        }

    def test_depth1_returns_direct_only(self):
        flat, by_depth = _bfs_importers("a.py", self._rev(), depth=1)
        assert flat == ["b.py"]
        assert by_depth == {1: ["b.py"]}

    def test_depth2_returns_two_layers(self):
        flat, by_depth = _bfs_importers("a.py", self._rev(), depth=2)
        assert set(flat) == {"b.py", "c.py"}
        assert by_depth[1] == ["b.py"]
        assert by_depth[2] == ["c.py"]

    def test_depth3_returns_three_layers(self):
        flat, by_depth = _bfs_importers("a.py", self._rev(), depth=3)
        assert set(flat) == {"b.py", "c.py", "d.py"}
        assert by_depth[1] == ["b.py"]
        assert by_depth[2] == ["c.py"]
        assert by_depth[3] == ["d.py"]

    def test_no_importers_returns_empty(self):
        flat, by_depth = _bfs_importers("lonely.py", self._rev(), depth=3)
        assert flat == []
        assert by_depth == {}

    def test_no_cycles_on_circular_graph(self):
        # a ↔ b circular
        rev = {"a.py": ["b.py"], "b.py": ["a.py"]}
        flat, by_depth = _bfs_importers("a.py", rev, depth=5)
        assert "a.py" not in flat  # start node excluded
        assert flat.count("b.py") == 1  # visited only once


# ---------------------------------------------------------------------------
# Integration tests: get_blast_radius with new fields
# ---------------------------------------------------------------------------

class TestBlastRadiusRiskFields:
    """Integration tests using a synthetic indexed repo."""

    def _build_repo(self, tmp_path):
        src = tmp_path / "src"
        store = tmp_path / "store"
        src.mkdir()
        store.mkdir()
        # utils.py defines a function
        (src / "utils.py").write_text(
            "def helper():\n    return 42\n"
        )
        # main.py imports utils
        (src / "main.py").write_text(
            "from utils import helper\n\nresult = helper()\n"
        )
        # cli.py imports main (chain)
        (src / "cli.py").write_text(
            "from main import result\n\nprint(result)\n"
        )
        result = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert result["success"] is True
        return result["repo"], str(store)

    def test_overall_risk_score_always_present(self, tmp_path):
        src, store = self._build_repo(tmp_path)
        result = get_blast_radius(
            repo=src, symbol="helper", depth=1, storage_path=store
        )
        assert "overall_risk_score" in result
        assert 0.0 <= result["overall_risk_score"] <= 1.0

    def test_direct_dependents_count_always_present(self, tmp_path):
        src, store = self._build_repo(tmp_path)
        result = get_blast_radius(
            repo=src, symbol="helper", depth=1, storage_path=store
        )
        assert "direct_dependents_count" in result
        assert result["direct_dependents_count"] >= 0

    def test_impact_by_depth_absent_by_default(self, tmp_path):
        src, store = self._build_repo(tmp_path)
        result = get_blast_radius(
            repo=src, symbol="helper", depth=2, storage_path=store
        )
        assert "impact_by_depth" not in result

    def test_impact_by_depth_present_when_requested(self, tmp_path):
        src, store = self._build_repo(tmp_path)
        result = get_blast_radius(
            repo=src, symbol="helper", depth=2,
            include_depth_scores=True, storage_path=store
        )
        assert "impact_by_depth" in result
        layers = result["impact_by_depth"]
        assert isinstance(layers, list)
        assert all("depth" in layer and "files" in layer and "risk_score" in layer
                   for layer in layers)

    def test_depth1_layer_contains_only_direct_importer(self, tmp_path):
        src, store = self._build_repo(tmp_path)
        result = get_blast_radius(
            repo=src, symbol="helper", depth=2,
            include_depth_scores=True, storage_path=store
        )
        depth1 = next((l for l in result["impact_by_depth"] if l["depth"] == 1), None)
        assert depth1 is not None
        assert any("main.py" in f for f in depth1["files"])

    def test_risk_score_depth1_is_1(self, tmp_path):
        src, store = self._build_repo(tmp_path)
        result = get_blast_radius(
            repo=src, symbol="helper", depth=2,
            include_depth_scores=True, storage_path=store
        )
        depth1 = next((l for l in result["impact_by_depth"] if l["depth"] == 1), None)
        assert depth1 is not None
        assert depth1["risk_score"] == 1.0

    def test_risk_score_decreases_with_depth(self, tmp_path):
        src, store = self._build_repo(tmp_path)
        result = get_blast_radius(
            repo=src, symbol="helper", depth=2,
            include_depth_scores=True, storage_path=store
        )
        layers = result["impact_by_depth"]
        if len(layers) >= 2:
            scores = [l["risk_score"] for l in sorted(layers, key=lambda x: x["depth"])]
            assert scores[0] > scores[1]

    def test_zero_importers_gives_risk_score_zero(self, tmp_path):
        src, store = self._build_repo(tmp_path)
        result = get_blast_radius(
            repo=src, symbol="helper", depth=1,
            include_depth_scores=True, storage_path=store
        )
        # overall_risk_score should be 0 if no importers found
        if result.get("importer_count", 0) == 0:
            assert result["overall_risk_score"] == 0.0

    def test_flat_impacted_symbols_list_unchanged(self, tmp_path):
        """Backward compat: confirmed + potential lists still present."""
        src, store = self._build_repo(tmp_path)
        result = get_blast_radius(
            repo=src, symbol="helper", depth=1,
            include_depth_scores=True, storage_path=store
        )
        assert "confirmed" in result
        assert "potential" in result
        assert "confirmed_count" in result
        assert "potential_count" in result


# ---------------------------------------------------------------------------
# Unit tests: _extract_reference_snippets
# ---------------------------------------------------------------------------

class TestExtractReferenceSnippets:

    def test_finds_matching_lines(self):
        content = "import helper\n\nx = helper()\ny = 42\nz = helper(1)\n"
        result = _extract_reference_snippets(content, "helper")
        assert len(result) == 3
        assert result[0] == {"line": 1, "text": "import helper"}
        assert result[1] == {"line": 3, "text": "x = helper()"}
        assert result[2] == {"line": 5, "text": "z = helper(1)"}

    def test_no_matches_returns_empty(self):
        assert _extract_reference_snippets("x = 42\n", "helper") == []

    def test_word_boundary_prevents_partial(self):
        content = "helpers = []\nhelper_fn()\nhelper()\n"
        result = _extract_reference_snippets(content, "helper")
        assert len(result) == 1
        assert result[0]["line"] == 3


# ---------------------------------------------------------------------------
# Integration tests: include_source flag
# ---------------------------------------------------------------------------

class TestBlastRadiusIncludeSource:
    """Tests for include_source flag."""

    def _build_repo(self, tmp_path):
        src = tmp_path / "src"
        store = tmp_path / "store"
        src.mkdir()
        store.mkdir()
        (src / "utils.py").write_text("def helper():\n    return 42\n")
        (src / "main.py").write_text(
            "from utils import helper\n\nresult = helper()\n\n"
            "def process():\n    return helper()\n"
        )
        (src / "cli.py").write_text("from main import result\n\nprint(result)\n")
        result = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert result["success"] is True
        return result["repo"], str(store)

    def test_include_source_false_no_snippets(self, tmp_path):
        """Default behavior: no source_snippets in confirmed entries."""
        repo, store = self._build_repo(tmp_path)
        r = get_blast_radius(repo, "helper", storage_path=store)
        for entry in r["confirmed"]:
            assert "source_snippets" not in entry
            assert "symbols_in_file" not in entry

    def test_include_source_true_adds_snippets(self, tmp_path):
        """With include_source=True, confirmed entries have source_snippets."""
        repo, store = self._build_repo(tmp_path)
        r = get_blast_radius(repo, "helper", include_source=True, storage_path=store)
        main_entry = next(e for e in r["confirmed"] if e["file"] == "main.py")
        assert "source_snippets" in main_entry
        assert len(main_entry["source_snippets"]) >= 2  # import + usage(s)
        assert all("line" in s and "text" in s for s in main_entry["source_snippets"])

    def test_include_source_adds_symbols_in_file(self, tmp_path):
        """With include_source=True, confirmed entries have symbols_in_file."""
        repo, store = self._build_repo(tmp_path)
        r = get_blast_radius(repo, "helper", include_source=True, storage_path=store)
        main_entry = next(e for e in r["confirmed"] if e["file"] == "main.py")
        assert "symbols_in_file" in main_entry
        sym_names = [s["name"] for s in main_entry["symbols_in_file"]]
        assert "process" in sym_names

    def test_source_budget_limits_output(self, tmp_path):
        """source_budget=1 should truncate snippets severely."""
        repo, store = self._build_repo(tmp_path)
        r = get_blast_radius(
            repo, "helper", include_source=True, source_budget=1, storage_path=store
        )
        total_snippets = sum(
            len(e.get("source_snippets", [])) for e in r["confirmed"]
        )
        assert total_snippets <= 1

    def test_include_source_does_not_affect_potential(self, tmp_path):
        """Potential entries should NOT get source_snippets."""
        repo, store = self._build_repo(tmp_path)
        r = get_blast_radius(repo, "helper", include_source=True, storage_path=store)
        for entry in r.get("potential", []):
            assert "source_snippets" not in entry

    def test_confirmed_sorted_by_file_after_enrichment(self, tmp_path):
        """Confirmed entries remain sorted by file path after enrichment."""
        repo, store = self._build_repo(tmp_path)
        r = get_blast_radius(repo, "helper", include_source=True, storage_path=store)
        files = [e["file"] for e in r["confirmed"]]
        assert files == sorted(files)

    def test_source_budget_zero_gives_empty_snippets(self, tmp_path):
        """source_budget=0 with include_source=True → consistent shape, empty lists."""
        repo, store = self._build_repo(tmp_path)
        r = get_blast_radius(
            repo, "helper", include_source=True, source_budget=0, storage_path=store
        )
        for entry in r["confirmed"]:
            assert entry["source_snippets"] == []
            assert entry["symbols_in_file"] == []

    def test_include_source_no_importers(self, tmp_path):
        """include_source=True on a leaf symbol with no importers is a no-op."""
        src = tmp_path / "src"
        store = tmp_path / "store2"
        src.mkdir(exist_ok=True)
        store.mkdir()
        (src / "leaf.py").write_text("def lonely():\n    return 1\n")
        res = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
        assert res["success"]
        r = get_blast_radius(res["repo"], "lonely", include_source=True, storage_path=str(store))
        assert "error" not in r
        assert r["confirmed"] == []
