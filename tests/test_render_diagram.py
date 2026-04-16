"""Tests for render_diagram — universal Mermaid renderer."""

import pytest

from jcodemunch_mcp.tools.render_diagram import (
    render_diagram,
    _detect_source,
    _prune_graph,
    _basename,
    _disambiguate_basenames,
    _sanitize_label,
)


# ── Minimal mock data builders ──────────────────────────────────────────────

def _call_hierarchy_data(**overrides):
    base = {
        "repo": "test/repo",
        "symbol": {"id": "server.py::handle", "name": "handle", "kind": "function", "file": "server.py", "line": 10},
        "direction": "both",
        "depth": 3,
        "depth_reached": 2,
        "caller_count": 2,
        "callee_count": 1,
        "callers": [
            {"id": "main.py::run", "name": "run", "kind": "function", "file": "main.py", "line": 5, "depth": 1, "resolution": "ast_resolved"},
            {"id": "app.py::startup", "name": "startup", "kind": "function", "file": "app.py", "line": 1, "depth": 2, "resolution": "text_matched"},
        ],
        "callees": [
            {"id": "db.py::query", "name": "query", "kind": "function", "file": "db.py", "line": 20, "depth": 1, "resolution": "lsp_resolved"},
        ],
        "dispatches": [],
        "_meta": {"timing_ms": 5.0, "methodology": "ast_call_references", "confidence_level": "medium", "source": "ast_call_references", "resolution_tiers": {}, "tip": ""},
    }
    base.update(overrides)
    return base


def _signal_chains_discovery_data(**overrides):
    base = {
        "repo": "test/repo",
        "gateway_count": 2,
        "chain_count": 2,
        "chains": [
            {"gateway": "routes.py::create_user", "gateway_name": "create_user", "kind": "http", "label": "POST /api/users", "depth": 3, "reach": 4, "symbols": ["create_user", "validate", "save", "notify"], "files_touched": ["routes.py", "validators.py", "repo.py", "mailer.py"], "file_count": 4},
            {"gateway": "cli.py::seed_db", "gateway_name": "seed_db", "kind": "cli", "label": "cli:seed-db", "depth": 2, "reach": 3, "symbols": ["seed_db", "generate", "insert"], "files_touched": ["cli.py", "factory.py", "repo.py"], "file_count": 3},
        ],
        "kind_summary": {"http": 1, "cli": 1},
        "orphan_symbols": 5,
        "orphan_symbol_pct": 12.5,
        "_meta": {"timing_ms": 10.0},
    }
    base.update(overrides)
    return base


def _signal_chains_lookup_data(**overrides):
    base = {
        "repo": "test/repo",
        "symbol": "validate",
        "symbol_id": "validators.py::validate",
        "chain_count": 1,
        "chains": [
            {"gateway": "routes.py::create_user", "gateway_name": "create_user", "kind": "http", "label": "POST /api/users", "chain_reach": 4},
        ],
        "on_no_chain": False,
        "_meta": {"timing_ms": 3.0},
    }
    base.update(overrides)
    return base


def _tectonic_map_data(**overrides):
    base = {
        "repo": "test/repo",
        "plate_count": 2,
        "file_count": 6,
        "plates": [
            {
                "plate_id": 0,
                "anchor": "src/api/server.py",
                "file_count": 3,
                "cohesion": 0.82,
                "files": ["src/api/server.py", "src/api/routes.py", "src/api/middleware.py"],
                "majority_directory": "src/api",
            },
            {
                "plate_id": 1,
                "anchor": "src/db/models.py",
                "file_count": 3,
                "cohesion": 0.65,
                "files": ["src/db/models.py", "src/db/queries.py", "src/config/loader.py"],
                "majority_directory": "src/db",
                "drifters": ["src/config/loader.py"],
                "drifter_count": 1,
                "nexus_alert": True,
                "nexus_coupling_count": 4,
                "coupled_to": {"src/api/server.py": 0.45},
            },
        ],
        "isolated_files": ["README.md"],
        "signals_used": ["structural", "behavioral", "temporal"],
        "drifter_summary": [{"file": "src/config/loader.py", "current_directory": "src/config", "belongs_with": "src/db", "plate_anchor": "src/db/models.py"}],
        "_meta": {"timing_ms": 15.0},
    }
    base.update(overrides)
    return base


def _dependency_cycles_data(**overrides):
    base = {
        "repo": "test/repo",
        "cycle_count": 1,
        "cycles": [["a.py", "b.py", "c.py"]],
        "_meta": {"timing_ms": 2.0},
    }
    base.update(overrides)
    return base


def _impact_preview_data(**overrides):
    base = {
        "repo": "test/repo",
        "symbol": {"id": "utils.py::parse_config", "name": "parse_config", "kind": "function", "file": "utils.py", "line": 10},
        "affected_files": 2,
        "affected_symbol_count": 3,
        "affected_symbols": [
            {"id": "server.py::init", "name": "init", "kind": "function", "file": "server.py", "line": 5, "call_chain": ["utils.py::parse_config", "server.py::init"]},
            {"id": "main.py::run", "name": "run", "kind": "function", "file": "main.py", "line": 1, "call_chain": ["utils.py::parse_config", "server.py::init", "main.py::run"]},
            {"id": "main.py::startup", "name": "startup", "kind": "function", "file": "main.py", "line": 20, "call_chain": ["utils.py::parse_config", "main.py::startup"]},
        ],
        "affected_by_file": {
            "server.py": [{"id": "server.py::init", "name": "init", "kind": "function", "line": 5}],
            "main.py": [
                {"id": "main.py::run", "name": "run", "kind": "function", "line": 1},
                {"id": "main.py::startup", "name": "startup", "kind": "function", "line": 20},
            ],
        },
        "call_chains": [
            {"symbol_id": "server.py::init", "chain": ["utils.py::parse_config", "server.py::init"]},
            {"symbol_id": "main.py::run", "chain": ["utils.py::parse_config", "server.py::init", "main.py::run"]},
            {"symbol_id": "main.py::startup", "chain": ["utils.py::parse_config", "main.py::startup"]},
        ],
        "_meta": {"timing_ms": 4.0},
    }
    base.update(overrides)
    return base


def _blast_radius_data(**overrides):
    base = {
        "repo": "test/repo",
        "symbol": {"id": "config.py::DB_URL", "name": "DB_URL"},
        "confirmed": [
            {"file": "server.py", "reference_count": 3},
            {"file": "migration.py", "reference_count": 1},
        ],
        "potential": [
            {"file": "tests/test_db.py"},
        ],
        "overall_risk_score": 0.65,
        "direct_dependents_count": 2,
        "_meta": {"timing_ms": 3.0},
    }
    base.update(overrides)
    return base


def _dependency_graph_data(**overrides):
    base = {
        "repo": "test/repo",
        "file": "src/server.py",
        "direction": "imports",
        "depth": 1,
        "neighbors": {
            "src/routes.py": {"specifiers": ["routes"]},
            "src/models.py": {"specifiers": ["models"]},
        },
        "cross_repo_edges": [],
        "_meta": {"timing_ms": 2.0},
    }
    base.update(overrides)
    return base


# ── Detection tests ─────────────────────────────────────────────────────────

class TestDetection:
    @pytest.mark.parametrize("builder,expected", [
        (_call_hierarchy_data, "call_hierarchy"),
        (_signal_chains_discovery_data, "signal_chains_discovery"),
        (_signal_chains_lookup_data, "signal_chains_lookup"),
        (_tectonic_map_data, "tectonic_map"),
        (_dependency_cycles_data, "dependency_cycles"),
        (_impact_preview_data, "impact_preview"),
        (_blast_radius_data, "blast_radius"),
        (_dependency_graph_data, "dependency_graph"),
    ])
    def test_detect_source_types(self, builder, expected):
        """Each source tool maps to its expected source type."""
        assert _detect_source(builder()) == expected

    def test_detect_error_response(self):
        assert _detect_source({"error": "not indexed"}) == "error"

    def test_detect_unknown_shape(self):
        assert _detect_source({"foo": "bar", "baz": 42}) == "unknown"

    def test_detect_callers_only(self):
        """call_hierarchy with direction='callers' has callers but no callees."""
        data = _call_hierarchy_data(callees=[], callee_count=0, direction="callers")
        assert _detect_source(data) == "call_hierarchy"


# ── Sanitisation helper tests ───────────────────────────────────────────────

class TestHelpers:
    def test_basename_unix(self):
        assert _basename("src/api/server.py") == "server.py"

    def test_basename_windows(self):
        assert _basename("src\\api\\server.py") == "server.py"

    def test_basename_flat(self):
        assert _basename("server.py") == "server.py"

    def test_sanitize_label_quotes(self):
        assert '"' not in _sanitize_label('say "hello"')

    def test_sanitize_label_angles(self):
        result = _sanitize_label("List<int>")
        assert "<" not in result and ">" not in result

    def test_disambiguate_no_collision(self):
        paths = ["src/a.py", "src/b.py"]
        d = _disambiguate_basenames(paths)
        assert d["src/a.py"] == "a.py"
        assert d["src/b.py"] == "b.py"

    def test_disambiguate_collision(self):
        paths = ["src/api/server.py", "src/db/server.py"]
        d = _disambiguate_basenames(paths)
        assert d["src/api/server.py"] != d["src/db/server.py"]
        assert "api" in d["src/api/server.py"]
        assert "db" in d["src/db/server.py"]


# ── Pruning tests ───────────────────────────────────────────────────────────

class TestPruning:
    @pytest.mark.parametrize("nodes,edges,max_nodes,preserve,expect_pruned,expect_preserve", [
        (["a", "b", "c"], [("a", "b"), ("b", "c")], 10, set(), 0, {"a", "b", "c"}),
        (["root", "a", "b", "leaf1", "leaf2", "leaf3"], [("root", "a"), ("root", "b"), ("a", "leaf1"), ("a", "leaf2"), ("b", "leaf3")], 3, {"root"}, True, {"root"}),
        (["target", "a"], [("target", "a")], 1, {"target"}, None, {"target"}),
        (["a", "b", "c"], [("a", "b"), ("b", "c")], 3, set(), 0, {"a", "b", "c"}),
    ])
    def test_prune_graph(self, nodes, edges, max_nodes, preserve, expect_pruned, expect_preserve):
        result_nodes, _, pruned = _prune_graph(nodes, edges, max_nodes, preserve)
        if expect_pruned == 0:
            assert pruned == 0
            assert set(result_nodes) == set(nodes)
        elif expect_pruned is True:
            assert pruned > 0
            assert "root" in result_nodes
        if expect_preserve:
            for node in expect_preserve:
                assert node in result_nodes


# ── Theme tests ─────────────────────────────────────────────────────────────

class TestThemes:
    def test_flow_theme_has_color(self):
        result = render_diagram(_call_hierarchy_data(), theme="flow")
        assert "error" not in result
        assert "#4A90D9" in result["mermaid"] or "fill:" in result["mermaid"]

    def test_risk_theme_has_color(self):
        result = render_diagram(_blast_radius_data(), theme="risk")
        assert "error" not in result
        # Risk theme should use red/orange palette
        assert "FF4136" in result["mermaid"] or "FF851B" in result["mermaid"]

    def test_minimal_theme_no_bright_colors(self):
        result = render_diagram(_dependency_cycles_data(), theme="minimal")
        assert "error" not in result
        # Minimal still uses red for cycle highlighting (semantic, not theme)
        assert "mermaid" in result

    def test_invalid_theme_defaults_to_flow(self):
        result = render_diagram(_call_hierarchy_data(), theme="nonexistent")
        assert "error" not in result
        assert result["_meta"]["theme"] == "nonexistent"  # theme name recorded as-is


# ── Renderer tests: call_hierarchy ──────────────────────────────────────────

class TestRenderCallHierarchy:
    def test_core_rendering(self):
        """All core rendering aspects for call hierarchy with callers and callees."""
        result = render_diagram(_call_hierarchy_data())
        assert result["diagram_type"] == "flowchart TD"
        assert result["mermaid"].startswith("flowchart TD")
        assert "handle" in result["mermaid"]
        assert "run" in result["mermaid"]
        assert "query" in result["mermaid"]
        assert "classDef" in result["mermaid"]
        assert "subgraph" in result["mermaid"]
        assert result["source_tool"] == "call_hierarchy"
        assert "Edge color" in result["legend"]

    def test_empty_callers_callees(self):
        data = _call_hierarchy_data(callers=[], callees=[], caller_count=0, callee_count=0)
        result = render_diagram(data)
        assert "error" not in result
        assert "handle" in result["mermaid"]


# ── Renderer tests: signal_chains ───────────────────────────────────────────

class TestRenderSignalChains:
    def test_discovery_rendering(self):
        """Core rendering for signal chains discovery mode."""
        result = render_diagram(_signal_chains_discovery_data())
        assert result["diagram_type"] == "sequenceDiagram"
        assert result["mermaid"].startswith("sequenceDiagram")
        assert "create_user" in result["mermaid"]
        assert "seed_db" in result["mermaid"]
        assert "box" in result["mermaid"]
        assert "HTTP" in result["mermaid"]
        assert "CLI" in result["mermaid"]
        assert "12.5%" in result["mermaid"]
        assert result["source_tool"] == "signal_chains"

    @pytest.mark.parametrize("data_fn,assertion", [
        (_signal_chains_lookup_data, lambda r: r["source_tool"] == "signal_chains"),
        (lambda: _signal_chains_discovery_data(chains=[], gateway_count=0, chain_count=0, orphan_symbols=0, orphan_symbol_pct=0), lambda r: "No signal chains" in r["mermaid"]),
    ])
    def test_edge_cases(self, data_fn, assertion):
        result = render_diagram(data_fn())
        assert "error" not in result
        assertion(result)


# ── Renderer tests: tectonic_map ────────────────────────────────────────────

class TestRenderTectonicMap:
    def test_plate_rendering(self):
        """Core plate rendering: subgraph count, anchor, drifter, nexus, cohesion, coupling, isolated."""
        result = render_diagram(_tectonic_map_data())
        mermaid = result["mermaid"]
        assert mermaid.count("subgraph plate") == 2
        assert ":::anchor" in mermaid
        assert ":::drifter" in mermaid
        assert "NEXUS" in mermaid
        assert "0.82" in mermaid
        assert "0.65" in mermaid
        assert "0.45" in mermaid
        assert "Isolated" in mermaid

    def test_empty_plates(self):
        data = _tectonic_map_data(plates=[], plate_count=0)
        result = render_diagram(data)
        assert "error" not in result


# ── Renderer tests: dependency_cycles ───────────────────────────────────────

class TestRenderDependencyCycles:
    def test_cycle_rendering(self):
        """Core cycle rendering: subgraph labels, red edges, cycled class marker."""
        result = render_diagram(_dependency_cycles_data())
        assert "Cycle 1" in result["mermaid"]
        assert "FF4136" in result["mermaid"]
        assert ":::cycled" in result["mermaid"]
        assert result["edge_count"] == 3

    @pytest.mark.parametrize("data_fn,expected", [
        (lambda: _dependency_cycles_data(cycles=[], cycle_count=0), "No circular dependencies"),
        (lambda: _dependency_cycles_data(cycles=[["a.py", "b.py"], ["x.py", "y.py", "z.py"]], cycle_count=2), "Cycle 1"),
    ])
    def test_edge_cases(self, data_fn, expected):
        result = render_diagram(data_fn())
        assert expected in result["mermaid"]


# ── Renderer tests: impact_preview ──────────────────────────────────────────

class TestRenderImpactPreview:
    def test_core_rendering(self):
        """Core impact preview rendering: flowchart BT, target marker, affected symbols, grouping, depth coloring."""
        result = render_diagram(_impact_preview_data())
        assert result["diagram_type"] == "flowchart BT"
        assert "parse_config" in result["mermaid"]
        assert ":::target" in result["mermaid"]
        assert "init" in result["mermaid"]
        assert "run" in result["mermaid"]
        assert "subgraph" in result["mermaid"]
        assert "classDef d1" in result["mermaid"]

    def test_empty_affected(self):
        """Edge case: no affected symbols."""
        data = _impact_preview_data(affected_files=0, affected_symbol_count=0, affected_symbols=[], affected_by_file={}, call_chains=[])
        result = render_diagram(data)
        assert "error" not in result


# ── Renderer tests: blast_radius ────────────────────────────────────────────

class TestRenderBlastRadius:
    def test_core_rendering(self):
        """Core blast radius rendering: flowchart TD, target, confirmed/potential markers, risk badge, ref counts."""
        result = render_diagram(_blast_radius_data())
        assert result["diagram_type"] == "flowchart TD"
        assert "DB_URL" in result["mermaid"]
        assert ":::target" in result["mermaid"]
        assert ":::confirmed" in result["mermaid"]
        assert ":::potential" in result["mermaid"]
        assert "0.65" in result["mermaid"]
        assert "medium" in result["mermaid"]
        assert "3 refs" in result["mermaid"]

    def test_risk_theme(self):
        result = render_diagram(_blast_radius_data(), theme="risk")
        assert "FF4136" in result["mermaid"] or "FF851B" in result["mermaid"]


# ── Renderer tests: dependency_graph ────────────────────────────────────────

class TestRenderDependencyGraph:
    def test_core_rendering(self):
        """Core dependency graph rendering: flowchart LR, focal node, neighbors."""
        result = render_diagram(_dependency_graph_data())
        assert result["diagram_type"] == "flowchart LR"
        assert "server.py" in result["mermaid"]
        assert ":::focal" in result["mermaid"]
        assert "routes.py" in result["mermaid"]
        assert "models.py" in result["mermaid"]

    @pytest.mark.parametrize("data_fn,assertion", [
        (lambda: render_diagram(_dependency_graph_data(cross_repo_edges=[{"file": "other-repo/utils.py"}])), lambda r: "cross-repo" in r["mermaid"] and ":::cross" in r["mermaid"]),
        (lambda: render_diagram(_dependency_graph_data(direction="importers")), lambda r: "importers" in r["legend"]),
    ])
    def test_edge_cases(self, data_fn, assertion):
        assertion(data_fn())


# ── Return shape tests ──────────────────────────────────────────────────────

class TestReturnShape:
    """Every successful render must have all required keys."""

    _ALL_SOURCES = [
        _call_hierarchy_data,
        _signal_chains_discovery_data,
        _signal_chains_lookup_data,
        _tectonic_map_data,
        _dependency_cycles_data,
        _impact_preview_data,
        _blast_radius_data,
        _dependency_graph_data,
    ]

    _REQUIRED_KEYS = {"diagram_type", "mermaid", "node_count", "edge_count", "pruned_count", "legend", "source_tool", "_meta"}

    @pytest.mark.parametrize("builder", _ALL_SOURCES)
    def test_all_keys_present(self, builder):
        result = render_diagram(builder())
        assert "error" not in result, result.get("error")
        missing = self._REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Missing keys: {missing}"

    @pytest.mark.parametrize("builder", _ALL_SOURCES)
    def test_mermaid_is_nonempty_string(self, builder):
        result = render_diagram(builder())
        assert isinstance(result["mermaid"], str)
        assert len(result["mermaid"]) > 10

    @pytest.mark.parametrize("builder", _ALL_SOURCES)
    def test_node_count_nonnegative(self, builder):
        result = render_diagram(builder())
        assert result["node_count"] >= 0

    @pytest.mark.parametrize("builder", _ALL_SOURCES)
    def test_meta_has_timing(self, builder):
        result = render_diagram(builder())
        assert "timing_ms" in result["_meta"]


# ── Error handling tests ────────────────────────────────────────────────────

class TestErrorHandling:
    def test_error_response_rejected(self):
        result = render_diagram({"error": "not indexed"})
        assert "error" in result

    def test_unknown_shape_rejected(self):
        result = render_diagram({"foo": "bar"})
        assert "error" in result
        assert "Unrecognised" in result["error"]

    def test_empty_dict_rejected(self):
        result = render_diagram({})
        assert "error" in result
