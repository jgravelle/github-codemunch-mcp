"""Round-trip tests for tier-1 custom encoders.

Each test: build a representative response, encode through the dispatcher,
decode via the public decoder, verify key fields and row contents survive.
"""

import pytest

from jcodemunch_mcp.encoding import encode_response
from jcodemunch_mcp.encoding.decoder import decode
from jcodemunch_mcp.encoding.schemas import registry


def _rt(tool: str, response: dict) -> dict:
    payload, meta = encode_response(tool, response, "compact")
    assert isinstance(payload, str), f"expected compact payload for {tool}, got {type(payload)}"
    assert meta["encoding"] != "json"
    return decode(payload)


def test_registry_loads_all_tier1_encoders():
    expected = {
        "find_references", "find_importers", "get_call_hierarchy",
        "get_dependency_graph", "get_blast_radius", "get_impact_preview",
        "get_signal_chains", "get_dependency_cycles", "get_tectonic_map",
        "search_symbols", "search_text", "search_ast",
        "get_file_outline", "get_repo_outline", "get_ranked_context",
    }
    for tool in expected:
        assert registry.for_tool(tool) is not None, f"missing encoder for {tool}"


def test_find_references_round_trip():
    resp = {
        "repo": "acme/app",
        "identifier": "get_user",
        "reference_count": 2,
        "references": [
            {
                "file": "src/a.py",
                "matches": [
                    {"specifier": "models.user", "match_type": "named"},
                    {"specifier": "models.user", "match_type": "specifier_stem"},
                ],
            },
            {
                "file": "src/b.py",
                "matches": [
                    {"specifier": "models.user", "match_type": "named"},
                ],
            },
        ],
        "_meta": {"timing_ms": 3.1, "truncated": False},
    }
    out = _rt("find_references", resp)
    assert out["repo"] == "acme/app"
    assert out["identifier"] == "get_user"
    assert isinstance(out["reference_count"], int)
    assert out["reference_count"] == 2
    assert len(out["references"]) == 2
    assert out["references"][0]["file"] == "src/a.py"
    assert len(out["references"][0]["matches"]) == 2
    assert len(out["references"][1]["matches"]) == 1


def test_find_references_empty_matches_round_trip():
    resp = {
        "repo": "acme/app",
        "identifier": "get_user",
        "reference_count": 2,
        "references": [
            {"file": "src/a.py", "matches": []},
            {"file": "src/b.py", "matches": [{"specifier": "models.user", "match_type": "named"}]},
        ],
        "_meta": {"timing_ms": 1.0, "truncated": False},
    }
    out = _rt("find_references", resp)
    assert len(out["references"]) == 2
    assert out["references"][0]["file"] == "src/a.py"
    assert out["references"][0]["matches"] == []
    assert out["references"][1]["matches"][0]["match_type"] == "named"


def test_find_references_batch_round_trip():
    resp = {
        "repo": "acme/app",
        "results": [
            {
                "identifier": "get_user",
                "reference_count": 2,
                "references": [
                    {"file": "src/a.py", "specifier": "models.user", "match_type": "named"},
                    {"file": "src/b.py", "specifier": "models.user", "match_type": "named"},
                ],
            },
        ],
        "_meta": {"timing_ms": 2.0},
    }
    out = _rt("find_references", resp)
    assert isinstance(out["results"], list)
    assert len(out["results"]) == 1
    assert out["results"][0]["identifier"] == "get_user"
    assert len(out["results"][0]["references"]) == 2


def test_find_importers_round_trip():
    resp = {
        "repo": "acme/app",
        "file_path": "src/models/user.py",
        "importer_count": 2,
        "importers": [
            {"file": "src/api/handlers.py", "specifier": "models.user", "has_importers": True},
            {"file": "src/api/routes.py", "specifier": "models.user", "has_importers": False},
        ],
        "_meta": {"timing_ms": 1.2, "truncated": False},
    }
    out = _rt("find_importers", resp)
    assert out["file_path"] == "src/models/user.py"
    assert isinstance(out["importer_count"], int)
    assert out["importer_count"] == 2
    assert len(out["importers"]) == 2
    assert out["importers"][0]["file"] == "src/api/handlers.py"
    assert out["importers"][0]["has_importers"] is True


def test_find_importers_batch_round_trip():
    resp = {
        "repo": "acme/app",
        "results": [
            {
                "file_path": "src/models/user.py",
                "importer_count": 1,
                "importers": [
                    {"file": "src/api/handlers.py", "specifier": "models.user", "has_importers": True},
                ],
            },
        ],
        "_meta": {"timing_ms": 0.9},
    }
    out = _rt("find_importers", resp)
    assert isinstance(out["results"], list)
    assert len(out["results"]) == 1
    assert out["results"][0]["file_path"] == "src/models/user.py"
    assert out["results"][0]["importers"][0]["has_importers"] is True


def test_get_call_hierarchy_round_trip():
    resp = {
        "repo": "acme/app",
        "symbol": {"id": "sym1", "name": "foo", "kind": "function", "file": "x.py", "line": 1},
        "direction": "both",
        "depth": 2,
        "depth_reached": 2,
        "caller_count": 2,
        "callee_count": 1,
        "callers": [
            {"id": "c1", "name": "a", "kind": "function", "file": "x.py", "line": 10, "depth": 1, "resolution": "lsp"},
            {"id": "c2", "name": "b", "kind": "function", "file": "x.py", "line": 20, "depth": 2, "resolution": "ast"},
        ],
        "callees": [
            {"id": "e1", "name": "helper", "kind": "function", "file": "y.py", "line": 5, "depth": 1, "resolution": "lsp"},
        ],
        "dispatches": [],
        "_meta": {"timing_ms": 4.0, "methodology": "ast+lsp"},
    }
    out = _rt("get_call_hierarchy", resp)
    assert out["symbol"]["name"] == "foo"
    assert len(out["callers"]) == 2
    assert out["callers"][0]["file"] == "x.py"
    assert len(out["callees"]) == 1


def test_get_dependency_graph_round_trip():
    resp = {
        "repo": "acme/app",
        "file": "src/main.py",
        "direction": "both",
        "depth": 2,
        "depth_reached": 2,
        "node_count": 3,
        "edge_count": 2,
        "edges": [
            {"from": "src/main.py", "to": "src/lib/a.py", "depth": 1},
            {"from": "src/main.py", "to": "src/lib/b.py", "depth": 1},
        ],
        "cross_repo_edges": [],
        "_meta": {"timing_ms": 2.1, "truncated": False, "cross_repo": False},
    }
    out = _rt("get_dependency_graph", resp)
    assert len(out["edges"]) == 2
    assert out["edges"][0]["from"] == "src/main.py"


def test_get_blast_radius_round_trip():
    resp = {
        "repo": "acme/app",
        "symbol": {"id": "s1", "name": "get_user", "kind": "function", "file": "auth.py", "line": 42},
        "depth": 3,
        "importer_count": 2,
        "confirmed_count": 2,
        "potential_count": 1,
        "direct_dependents_count": 5,
        "overall_risk_score": 0.75,
        "confirmed": [
            {"file": "api.py", "references": 3, "has_test_reach": True},
            {"file": "main.py", "references": 1, "has_test_reach": False},
        ],
        "potential": [
            {"file": "utils.py", "reason": "wildcard import"},
        ],
        "_meta": {"timing_ms": 3.0},
    }
    out = _rt("get_blast_radius", resp)
    assert len(out["confirmed"]) == 2
    assert out["confirmed"][0]["file"] == "api.py"
    assert out["confirmed"][0]["references"] == 3
    assert out["confirmed"][0]["has_test_reach"] is True
    assert len(out["potential"]) == 1
    assert out["potential"][0]["file"] == "utils.py"
    assert out["symbol"]["name"] == "get_user"
    assert isinstance(out["overall_risk_score"], float)
    assert out["overall_risk_score"] == 0.75


def test_get_dependency_cycles_round_trip():
    resp = {
        "repo": "acme/app",
        "cycle_count": 1,
        "cycles": [["a.py", "b->c.py", "c.py"]],
        "_meta": {"timing_ms": 1.0},
    }
    out = _rt("get_dependency_cycles", resp)
    assert len(out["cycles"]) == 1
    assert isinstance(out["cycle_count"], int)
    assert out["cycle_count"] == 1
    assert out["cycles"][0] == ["a.py", "b->c.py", "c.py"]


def test_search_text_round_trip():
    # Mirrors the real shape of tools/search_text.py: results grouped by file,
    # with matches nested inside each group.
    resp = {
        "result_count": 2,
        "query": "TODO",
        "results": [
            {
                "file": "a.py",
                "matches": [
                    {"line": 10, "text": "# TODO: fix"},
                    {"line": 22, "text": "# TODO: refactor"},
                ],
            },
        ],
        "_meta": {"timing_ms": 0.5, "files_searched": 30, "truncated": False},
    }
    out = _rt("search_text", resp)
    assert len(out["results"]) == 1
    assert out["results"][0]["file"] == "a.py"
    matches = out["results"][0]["matches"]
    assert len(matches) == 2
    assert matches[0]["line"] == 10
    assert matches[0]["text"] == "# TODO: fix"
    assert matches[1]["line"] == 22
    # Typed scalars: ints, floats, bools survive the round trip.
    assert out["result_count"] == 2
    assert out["_meta"]["timing_ms"] == 0.5
    assert out["_meta"]["files_searched"] == 30
    assert out["_meta"]["truncated"] is False


def test_search_text_round_trip_with_context_lines():
    # context_lines>0 emits before/after arrays per match; must survive the
    # nested→flat→nested transform without data loss.
    resp = {
        "result_count": 1,
        "results": [
            {
                "file": "a.py",
                "matches": [
                    {
                        "line": 10,
                        "text": "target",
                        "before": ["above_1", "above_2"],
                        "after": ["below_1"],
                    },
                ],
            },
        ],
        "_meta": {"timing_ms": 0.1, "files_searched": 1, "truncated": False},
    }
    out = _rt("search_text", resp)
    m = out["results"][0]["matches"][0]
    assert m["before"] == ["above_1", "above_2"]
    assert m["after"] == ["below_1"]


def test_search_text_round_trip_adversarial_cells_and_st1_compat():
    """Round-trip adversarial CSV/JSON cell content and ensure st1 decode compatibility."""
    tricky_text = 'target, with "quotes" and newline\nline_two'
    tricky_before = [
        'before,comma',
        'before "quoted"',
        "before multi\nline",
    ]
    tricky_after = [
        'after, "mix"',
        "after multi\nline",
    ]
    resp = {
        "result_count": 1,
        "results": [
            {
                "file": "a.py",
                "matches": [
                    {
                        "line": 10,
                        "text": tricky_text,
                        "before": tricky_before,
                        "after": tricky_after,
                    },
                ],
            },
        ],
        "_meta": {"timing_ms": 0.1, "files_searched": 1, "truncated": False},
    }

    payload, meta = encode_response("search_text", resp, "compact")
    assert isinstance(payload, str)
    assert meta["encoding"] != "json"

    # st2 current decode
    out = decode(payload)
    m = out["results"][0]["matches"][0]
    assert m["text"] == tricky_text
    assert m["before"] == tricky_before
    assert m["after"] == tricky_after

    # st1 compatibility decode path (legacy header id)
    payload_st1 = payload.replace("enc=st2", "enc=st1", 1)
    out_st1 = decode(payload_st1)
    m_st1 = out_st1["results"][0]["matches"][0]
    assert m_st1["text"] == tricky_text
    assert m_st1["before"] == tricky_before
    assert m_st1["after"] == tricky_after


def test_search_text_round_trip_multi_file():
    # Separate files must stay separate on regroup; order preserved.
    resp = {
        "result_count": 3,
        "results": [
            {"file": "a.py", "matches": [{"line": 1, "text": "x"}]},
            {"file": "b.py", "matches": [{"line": 5, "text": "y"}, {"line": 9, "text": "z"}]},
        ],
        "_meta": {"timing_ms": 0.2, "files_searched": 2, "truncated": False},
    }
    out = _rt("search_text", resp)
    assert [g["file"] for g in out["results"]] == ["a.py", "b.py"]
    assert len(out["results"][1]["matches"]) == 2


def test_search_symbols_round_trip():
    resp = {
        "result_count": 2,
        "query": "user",
        "results": [
            {"id": "s1", "name": "get_user", "kind": "function", "file": "models/user.py", "line": 10, "score": 0.92, "signature": "def get_user(id)", "summary": "Fetches a user"},
            {"id": "s2", "name": "User", "kind": "class", "file": "models/user.py", "line": 1, "score": 0.88, "signature": "class User", "summary": "User model"},
        ],
        "_meta": {"timing_ms": 1.3, "total_symbols": 1200, "truncated": False},
    }
    out = _rt("search_symbols", resp)
    assert len(out["results"]) == 2
    assert out["results"][0]["name"] == "get_user"


def test_get_file_outline_round_trip():
    resp = {
        "repo": "acme/app",
        "file": "src/models/user.py",
        "symbol_count": 2,
        "symbols": [
            {"id": "s1", "name": "User", "kind": "class", "line": 1, "end_line": 20, "parent": "", "summary": ""},
            {"id": "s2", "name": "get_user", "kind": "function", "line": 25, "end_line": 40, "parent": "", "summary": ""},
        ],
        "_meta": {"timing_ms": 0.3},
    }
    out = _rt("get_file_outline", resp)
    assert len(out["symbols"]) == 2


def test_get_repo_outline_round_trip():
    resp = {
        "repo": "acme/app",
        "source_root": "/tmp/app",
        "file_count": 2,
        "symbol_count": 4,
        "files": [
            {"file": "a.py", "language": "python", "symbol_count": 2, "line_count": 30, "summary": "foo"},
            {"file": "b.py", "language": "python", "symbol_count": 2, "line_count": 40, "summary": "bar"},
        ],
        "_meta": {"timing_ms": 2.0, "is_stale": False},
    }
    out = _rt("get_repo_outline", resp)
    assert len(out["files"]) == 2
    assert out["files"][0]["language"] == "python"


@pytest.mark.parametrize("tool,resp", [
    ("get_impact_preview", {
        "repo": "a/b",
        "symbol": {"id": "s1", "name": "foo", "kind": "function", "file": "x.py", "line": 1},
        "affected_files": 2,
        "affected_symbol_count": 3,
        "affected_symbols": [
            {"id": "t1", "name": "bar", "kind": "function", "file": "y.py", "line": 10, "depth": 1},
            {"id": "t2", "name": "baz", "kind": "function", "file": "y.py", "line": 20, "depth": 1},
        ],
        "_meta": {"timing_ms": 1.0},
    }),
    ("get_signal_chains", {
        "repo": "a/b",
        "gateway_count": 1,
        "chain_count": 2,
        "orphan_symbols": 0,
        "orphan_symbol_pct": 0.0,
        "chains": [
            {
                "gateway": "routes.py::create_user",
                "gateway_name": "create_user",
                "kind": "http",
                "label": "POST /api/users",
                "depth": 3,
                "reach": 4,
                "symbols": ["create_user", "validate", "save", "notify"],
                "files_touched": ["routes.py", "validators.py", "repo.py", "mailer.py"],
                "file_count": 4,
            },
            {
                "gateway": "cli.py::seed_db",
                "gateway_name": "seed_db",
                "kind": "cli",
                "label": "cli:seed-db",
                "depth": 2,
                "reach": 3,
                "symbols": ["seed_db", "generate", "insert"],
                "files_touched": ["cli.py", "factory.py", "repo.py"],
                "file_count": 3,
            },
        ],
        "kind_summary": {"http": 1, "cli": 1},
        "_meta": {"timing_ms": 5.0, "max_depth": 5, "include_tests": True, "symbols_on_chains": 6, "total_functions_methods": 12},
    }),
    ("get_signal_chains", {
        "repo": "a/b",
        "symbol": "validate",
        "symbol_id": "validators.py::validate",
        "chain_count": 1,
        "chains": [
            {"gateway": "routes.py::create_user", "gateway_name": "create_user", "kind": "http", "label": "POST /api/users", "chain_reach": 4, "depth_from_gateway": 1},
        ],
        "on_no_chain": False,
        "_meta": {"timing_ms": 3.0, "max_depth": 5, "include_tests": False, "symbols_on_chains": 1, "total_functions_methods": 8, "total_gateways": 1},
    }),
    ("search_ast", {
        "result_count": 1,
        "query": "call:print",
        "results": [
            {"file": "a.py", "line": 10, "match_type": "call", "snippet": "print(x)", "symbol_id": "s1", "symbol_name": "foo"},
        ],
        "_meta": {"timing_ms": 1.0, "files_searched": 20},
    }),
    ("get_ranked_context", {
        "total_tokens": 500,
        "budget_tokens": 1000,
        "items_included": 2,
        "items_considered": 10,
        "context_items": [
            {"id": "s1", "name": "foo", "kind": "function", "file": "a.py", "line": 1, "score": 0.9, "token_cost": 250, "summary": "does foo"},
            {"id": "s2", "name": "bar", "kind": "function", "file": "b.py", "line": 1, "score": 0.8, "token_cost": 250, "summary": "does bar"},
        ],
        "_meta": {"timing_ms": 2.0, "fusion": True},
    }),
    ("get_tectonic_map", {
        "repo": "a/b",
        "plate_count": 1,
        "file_count": 2,
        "plates": [{"plate_id": 0, "anchor": "src/core.py", "file_count": 2, "cohesion": 0.82, "majority_directory": "src", "drifter_count": 0, "nexus_alert": False}],
        "drifter_summary": [{"file": "src/config/loader.py", "current_directory": "src/config", "belongs_with": "src", "plate_anchor": "src/core.py"}],
        "isolated_files": ["README.md"],
        "signals_used": ["structural", "behavioral", "temporal"],
        "_meta": {"timing_ms": 3.0, "methodology": "tectonic"},
    }),
])
def test_remaining_tier1_round_trip(tool, resp):
    out = _rt(tool, resp)
    # Just confirm the decode produces something usable with table keys preserved.
    for table_key in ("affected_symbols", "chains", "results", "context_items", "plates"):
        if table_key in resp:
            assert table_key in out, f"{tool} lost {table_key}"


def test_get_signal_chains_lookup_round_trip():
    resp = {
        "repo": "a/b",
        "symbol": "validate",
        "symbol_id": "validators.py::validate",
        "chain_count": 1,
        "chains": [
            {"gateway": "routes.py::create_user", "gateway_name": "create_user", "kind": "http", "label": "POST /api/users", "chain_reach": 4, "depth_from_gateway": 1},
        ],
        "on_no_chain": False,
        "_meta": {"timing_ms": 3.0, "max_depth": 5, "include_tests": False, "symbols_on_chains": 1, "total_functions_methods": 8, "total_gateways": 1},
    }
    out = _rt("get_signal_chains", resp)
    assert out["symbol"] == "validate"
    assert out["symbol_id"] == "validators.py::validate"
    assert out["on_no_chain"] is False
    assert out["chains"][0]["chain_reach"] == 4
    assert out["chains"][0]["depth_from_gateway"] == 1
    assert out["_meta"] == {"timing_ms": 3.0, "total_gateways": 1}


def test_get_signal_chains_discovery_meta_shape():
    resp = {
        "repo": "a/b",
        "gateway_count": 1,
        "chain_count": 2,
        "orphan_symbols": 0,
        "orphan_symbol_pct": 0.0,
        "chains": [
            {
                "gateway": "routes.py::create_user",
                "gateway_name": "create_user",
                "kind": "http",
                "label": "POST /api/users",
                "depth": 3,
                "reach": 4,
                "symbols": ["create_user", "validate", "save", "notify"],
                "files_touched": ["routes.py", "validators.py", "repo.py", "mailer.py"],
                "file_count": 4,
            },
        ],
        "kind_summary": {"http": 1},
        "_meta": {"timing_ms": 5.0, "max_depth": 5, "include_tests": True, "symbols_on_chains": 4, "total_functions_methods": 12},
    }
    out = _rt("get_signal_chains", resp)
    assert out["_meta"] == {
        "timing_ms": 5.0,
        "max_depth": 5,
        "include_tests": True,
        "symbols_on_chains": 4,
        "total_functions_methods": 12,
    }


def test_get_signal_chains_no_gateway_round_trip():
    resp = {
        "repo": "a/b",
        "gateway_count": 0,
        "chain_count": 0,
        "chains": [],
        "gateway_warning": "No gateways detected.",
        "_meta": {"timing_ms": 1.0},
    }
    out = _rt("get_signal_chains", resp)
    assert out["gateway_count"] == 0
    assert out["chain_count"] == 0
    assert out["gateway_warning"] == "No gateways detected."
    assert isinstance(out["chains"], list)
    assert out["chains"] == []
    assert out["_meta"] == {"timing_ms": 1.0}


def test_get_tectonic_map_round_trip_realistic():
    resp = {
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
        "_meta": {"timing_ms": 15.0, "methodology": "tectonic"},
    }
    out = _rt("get_tectonic_map", resp)
    assert len(out["plates"]) == 2
    assert out["plates"][0]["plate_id"] == 0
    assert isinstance(out["plates"][0]["cohesion"], float)
    assert "drifter_count" not in out["plates"][0]
    assert "nexus_alert" not in out["plates"][0]
    assert out["plates"][1]["drifter_count"] == 1
    assert out["plates"][1]["nexus_alert"] is True
    assert out["drifter_summary"][0]["plate_anchor"] == "src/db/models.py"
    assert out["isolated_files"] == ["README.md"]
    assert out["signals_used"] == ["structural", "behavioral", "temporal"]
