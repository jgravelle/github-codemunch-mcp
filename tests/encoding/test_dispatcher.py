"""Dispatcher + gate + generic encoder integration tests."""

import json

from jcodemunch_mcp.encoding import encode_response
from jcodemunch_mcp.encoding.decoder import decode as decode_munch


def _big_response():
    return {
        "repo": "myapp",
        "depth": 3,
        "references": [
            {"file": "src/service/auth.py", "line": 12, "kind": "call"},
            {"file": "src/service/auth.py", "line": 88, "kind": "call"},
            {"file": "src/service/user.py", "line": 21, "kind": "ref"},
            {"file": "src/service/user.py", "line": 44, "kind": "ref"},
            {"file": "tests/integration/auth_test.py", "line": 9, "kind": "call"},
            {"file": "tests/integration/auth_test.py", "line": 15, "kind": "call"},
        ],
    }


def test_auto_falls_back_to_json_for_tiny_responses():
    payload, meta = encode_response("demo", {"ok": True}, "auto")
    assert meta["encoding"] == "json"


def test_force_json():
    payload, meta = encode_response("demo", _big_response(), "json")
    assert meta["encoding"] == "json"
    assert isinstance(payload, dict)


def test_compact_always_encodes_and_is_smaller():
    resp = _big_response()
    payload, meta = encode_response("demo", resp, "compact")
    assert meta["encoding"] != "json"
    assert meta["encoded_bytes"] < meta["json_bytes"]


def test_generic_encoding_round_trip():
    resp = _big_response()
    payload, meta = encode_response("demo", resp, "compact")
    assert isinstance(payload, str)
    rehydrated = decode_munch(payload)
    # Generic decoder preserves original top-level keys and column types.
    assert rehydrated["repo"] == "myapp"
    assert rehydrated["depth"] == 3
    assert "references" in rehydrated
    rows = rehydrated["references"]
    assert any(r["file"] == "src/service/auth.py" for r in rows)
    assert all(isinstance(r["line"], int) for r in rows)


def test_auto_emits_compact_on_big_response():
    resp = _big_response()
    # Artificially inflate the response so the savings gate trips.
    resp["references"] *= 10
    payload, meta = encode_response("demo", resp, "auto")
    assert meta["encoding"] != "json", meta


def test_json_decoder_falls_through_for_json_payloads():
    raw = json.dumps({"hello": 1})
    assert decode_munch(raw) == {"hello": 1}


def test_user_facing_format_aliases_are_supported():
    payload, meta = encode_response("demo", _big_response(), "encoded")
    assert meta["encoding"] != "json"

    payload, meta = encode_response("demo", _big_response(), "raw")
    assert meta["encoding"] == "json"
    assert isinstance(payload, dict)


def test_default_format_uses_server_output_config():
    import jcodemunch_mcp.config as cfg

    snapshot = dict(cfg._GLOBAL_CONFIG)
    try:
        cfg._GLOBAL_CONFIG.clear()
        cfg._GLOBAL_CONFIG.update({"server_output": "raw", "server_output_threshold": 0.15})
        payload, meta = encode_response("demo", _big_response())
        assert meta["encoding"] == "json"

        cfg._GLOBAL_CONFIG["server_output"] = "encoded"
        payload, meta = encode_response("demo", _big_response())
        assert meta["encoding"] != "json"
    finally:
        cfg._GLOBAL_CONFIG.clear()
        cfg._GLOBAL_CONFIG.update(snapshot)


def test_project_server_output_overrides_global_when_repo_provided():
    import jcodemunch_mcp.config as cfg

    repo_key = "D:/tmp/project-a"
    g_snapshot = dict(cfg._GLOBAL_CONFIG)
    p_snapshot = dict(cfg._PROJECT_CONFIGS)
    try:
        cfg._GLOBAL_CONFIG.clear()
        cfg._GLOBAL_CONFIG.update({"server_output": "encoded", "server_output_threshold": 0.15})
        cfg._PROJECT_CONFIGS.clear()
        project_cfg = dict(cfg._GLOBAL_CONFIG)
        project_cfg["server_output"] = "raw"
        cfg._PROJECT_CONFIGS[repo_key] = project_cfg

        payload, meta = encode_response("demo", _big_response(), repo=repo_key)
        assert meta["encoding"] == "json"

        payload, meta = encode_response("demo", _big_response())
        assert meta["encoding"] != "json"
    finally:
        cfg._GLOBAL_CONFIG.clear()
        cfg._GLOBAL_CONFIG.update(g_snapshot)
        cfg._PROJECT_CONFIGS.clear()
        cfg._PROJECT_CONFIGS.update(p_snapshot)


def test_project_threshold_overrides_global_when_repo_provided():
    import jcodemunch_mcp.config as cfg

    repo_key = "D:/tmp/project-b"
    g_snapshot = dict(cfg._GLOBAL_CONFIG)
    p_snapshot = dict(cfg._PROJECT_CONFIGS)
    try:
        cfg._GLOBAL_CONFIG.clear()
        cfg._GLOBAL_CONFIG.update({"server_output": "adaptive", "server_output_threshold": 1.0})
        cfg._PROJECT_CONFIGS.clear()
        project_cfg = dict(cfg._GLOBAL_CONFIG)
        project_cfg["server_output_threshold"] = 0.0
        cfg._PROJECT_CONFIGS[repo_key] = project_cfg

        big = _big_response()
        big["references"] *= 10
        payload, meta = encode_response("demo", big, repo=repo_key)
        assert meta["encoding"] != "json"

        payload, meta = encode_response("demo", big)
        assert meta["encoding"] == "json"
    finally:
        cfg._GLOBAL_CONFIG.clear()
        cfg._GLOBAL_CONFIG.update(g_snapshot)
        cfg._PROJECT_CONFIGS.clear()
        cfg._PROJECT_CONFIGS.update(p_snapshot)
