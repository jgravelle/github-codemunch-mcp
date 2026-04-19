"""Capture tools/list schema token counts at each profile x compact combo.

§0 pre-flight for the v2.0.0 context-optimization work. These numbers become
the regression guardrails in §7 (see tests/test_schema_budget.py).

Run from the repo root:
    PYTHONPATH=src python benchmarks/harness/capture_schema_baseline.py

Output: benchmarks/schema_baseline.json

Methodology: tokenize the JSON-serialized tool list with tiktoken cl100k_base
(the OpenAI/Anthropic-compatible GPT-4 tokenizer). Schemas are serialized with
the same compaction the server uses for its on-wire tool list.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running directly from repo root without installing the package.
_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import tiktoken  # noqa: E402

from jcodemunch_mcp import config as config_module  # noqa: E402
from jcodemunch_mcp.server import _build_tools_list  # noqa: E402


PROFILES = ["core", "standard", "full"]
COMPACT_FLAGS = [True, False]


def _tools_to_serialized(tools) -> str:
    payload = [
        {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
        for t in tools
    ]
    return json.dumps(payload, separators=(",", ":"))


def _count_tokens(text: str, encoding) -> int:
    return len(encoding.encode(text))


def capture(out_path: Path) -> dict:
    encoding = tiktoken.get_encoding("cl100k_base")
    results: dict[str, int] = {}
    cfg = config_module._GLOBAL_CONFIG  # type: ignore[attr-defined]
    original = {k: cfg.get(k) for k in ("tool_profile", "compact_schemas")}
    try:
        for profile in PROFILES:
            for compact in COMPACT_FLAGS:
                cfg["tool_profile"] = profile
                cfg["compact_schemas"] = compact
                tools = _build_tools_list()
                text = _tools_to_serialized(tools)
                key = f"{profile}_{'compact' if compact else 'full'}"
                results[key] = _count_tokens(text, encoding)
                print(f"  {key}: {results[key]} tokens ({len(tools)} tools)")
    finally:
        for k, v in original.items():
            if v is None:
                cfg.pop(k, None)
            else:
                cfg[k] = v

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "schema_baseline.json"
    data = capture(out)
    print(f"\nWrote baseline to {out}")
    print(json.dumps(data, indent=2))
