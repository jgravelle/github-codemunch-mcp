"""§7 docs/runtime parity guardrail.

Parses CONFIGURATION.md default columns and compares against DEFAULTS
in config.py. Fails on any mismatch. Prevents the kind of drift that
caused the `meta_fields` confusion — docs saying `null` while code had `[]`.

Scope: only keys that appear as bare entries in CONFIGURATION.md tables
where the Default column contains a single unambiguous value. Keys with
"see above", "varies", "platform-specific", or code-block defaults are
skipped (unrepresentable in a simple table cell). The skip list is
explicit — new keys should be documented in a tractable format or added
to the skip set with a comment.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_MD = REPO_ROOT / "CONFIGURATION.md"
CONFIG_PY = REPO_ROOT / "src" / "jcodemunch_mcp" / "config.py"

# Explicit allow-list of keys whose docs representation is intentionally
# not a single literal (e.g. complex dicts documented inline, env-driven
# runtime values, aliases that map onto multiple keys).
DOC_KEYS_SKIPPED = {
    "languages",  # documented as "None = all languages"; cell isn't a literal
    "languages_adaptive",
    "extra_extensions",  # dict default documented inline in a code block
    "descriptions",
    "tool_tier_bundles",
    "model_tier_map",
    "disabled_tools",  # default documented in a code block, not a cell
}


def _load_code_defaults() -> dict:
    """Parse DEFAULTS dict from config.py without importing the package.

    Keeps the test cheap and avoids any side effects from module import.
    """
    source = CONFIG_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DEFAULTS":
                    return ast.literal_eval(node.value)
    raise AssertionError("DEFAULTS constant not found in config.py")


def _parse_doc_defaults() -> dict:
    """Scan CONFIGURATION.md tables for `| key | type | default | ... |` rows.

    Returns a map of key → raw default-cell string. Callers normalize to
    compare against code values.
    """
    rows: dict[str, str] = {}
    for line in CONFIG_MD.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        key_cell = cells[0].strip("`")
        if not re.match(r"^[a-z_][a-z0-9_]*$", key_cell):
            continue
        rows[key_cell] = cells[2].strip()
    return rows


def _normalize_doc_default(raw: str):
    """Map a CONFIGURATION.md Default cell to a Python value, where possible."""
    raw = raw.strip().strip("`")
    if raw in ("`null`", "null", "None"):
        return None
    if raw == "[]":
        return []
    if raw == "{}":
        return {}
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    # numeric literal
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    # strip surrounding quotes
    m = re.match(r'^"(.*)"$', raw)
    if m:
        return m.group(1)
    return raw


@pytest.mark.parametrize("_", [None])  # keep pytest output grouped nicely
def test_documented_defaults_match_code(_):
    """Every key documented in CONFIGURATION.md with a literal default
    must match the DEFAULTS dict in config.py. §7 guardrail — prevents
    the meta_fields-style drift from recurring."""
    code = _load_code_defaults()
    docs = _parse_doc_defaults()

    mismatches: list[tuple[str, object, str]] = []
    for key, raw_default in docs.items():
        if key in DOC_KEYS_SKIPPED:
            continue
        if key not in code:
            # Doc lists a config key that isn't in DEFAULTS — that's a separate
            # bug but not this test's scope. Skip.
            continue
        normalized = _normalize_doc_default(raw_default)
        expected = code[key]
        if normalized != expected:
            mismatches.append((key, expected, raw_default))

    assert not mismatches, (
        "CONFIGURATION.md defaults drift from config.py. "
        "Fix the docs to match code or add the key to DOC_KEYS_SKIPPED. "
        f"Mismatches (key, code_default, docs_raw): {mismatches}"
    )
