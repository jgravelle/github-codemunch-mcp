"""§7 schema-budget regression guardrail.

Parses tools/list output at every profile x compact_schemas combination,
counts tokens with tiktoken cl100k_base, and fails if any count drifts
more than 5% above the frozen baseline in benchmarks/schema_baseline.json.

This is the load-bearing CI check that prevents schema bloat from sneaking
in via new tool additions or description expansions. If you legitimately
need the schema to grow (e.g. documented v2.1 change), update the baseline
in the same PR — the CI diff will make the change reviewable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "benchmarks" / "schema_baseline.json"
DRIFT_TOLERANCE = 0.05  # 5%

try:
    import tiktoken  # noqa: F401
    _HAS_TIKTOKEN = True
except ImportError:
    _HAS_TIKTOKEN = False


@pytest.mark.skipif(not _HAS_TIKTOKEN, reason="tiktoken not installed")
@pytest.mark.skipif(not BASELINE.is_file(), reason="benchmarks/schema_baseline.json missing — run benchmarks/harness/capture_schema_baseline.py")
def test_schema_tokens_within_baseline_tolerance():
    """tools/list token count must stay within 5% of baseline for every
    profile x compact_schemas combo. Catches accidental bloat from new
    tools, expanded descriptions, or schema regressions."""
    import tiktoken as _tk

    from jcodemunch_mcp import config as config_module
    from jcodemunch_mcp.server import _build_tools_list

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    encoding = _tk.get_encoding("cl100k_base")

    cfg = config_module._GLOBAL_CONFIG  # type: ignore[attr-defined]
    original = {k: cfg.get(k) for k in ("tool_profile", "compact_schemas")}
    drifts: list[str] = []
    try:
        for profile in ("core", "standard", "full"):
            for compact in (True, False):
                cfg["tool_profile"] = profile
                cfg["compact_schemas"] = compact
                tools = _build_tools_list()
                payload = [
                    {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                    for t in tools
                ]
                text = json.dumps(payload, separators=(",", ":"))
                count = len(encoding.encode(text))

                key = f"{profile}_{'compact' if compact else 'full'}"
                base = baseline.get(key)
                if base is None:
                    drifts.append(f"{key}: no baseline entry (add {count} to schema_baseline.json)")
                    continue
                ceiling = int(base * (1 + DRIFT_TOLERANCE))
                if count > ceiling:
                    drifts.append(
                        f"{key}: {count} tokens > {ceiling} ceiling "
                        f"(baseline {base}, +{(count - base) / base:.1%})"
                    )
    finally:
        for k, v in original.items():
            if v is None:
                cfg.pop(k, None)
            else:
                cfg[k] = v

    assert not drifts, (
        "Schema token budget exceeded. Either shrink the change or update "
        "benchmarks/schema_baseline.json in the same PR with justification. "
        f"Drifts: {drifts}"
    )


@pytest.mark.skipif(not BASELINE.is_file(), reason="benchmarks/schema_baseline.json missing")
def test_v2_success_criterion_core_compact_under_4000():
    """§10 success criterion: core + compact_schemas stays under 4,000 tokens."""
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    core_compact = baseline.get("core_compact")
    assert core_compact is not None, "baseline missing core_compact"
    assert core_compact <= 4000, (
        f"v2.0.0 success criterion requires core + compact_schemas <= 4000 tokens; "
        f"current baseline is {core_compact}."
    )
