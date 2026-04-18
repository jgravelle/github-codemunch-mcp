"""Pure helpers for tier bundle validation and model-id → tier resolution.

Kept free of server/config imports so it's trivially unit-testable.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Mapping

_DATE_SUFFIX_RE = re.compile(r"-\d{8}$")
_BRACKET_SUFFIX_RE = re.compile(r"\[[^\]]*\]$")


def normalize_model_id(model_id: object) -> str:
    """Canonicalize a model id for matching.

    Strips provider prefixes (anything up to and including the last '/'),
    bracketed suffixes like '[1m]' / '[beta]', and trailing '-YYYYMMDD'
    date stamps. Lowercases. Non-string input returns ''.
    """
    if not isinstance(model_id, str):
        return ""
    s = model_id.strip().lower()
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    s = _BRACKET_SUFFIX_RE.sub("", s)
    s = _DATE_SUFFIX_RE.sub("", s)
    return s


def resolve_model_to_tier(
    model_id: str,
    model_tier_map: Mapping[str, str],
) -> tuple[str, str]:
    """Resolve a model id to a tier via layered matching.

    Layer order, first match wins:
      1. exact match on normalized config keys
      2. glob match (only keys containing '*' / '?' / '[')
      3. substring match (key appears inside normalized id)
      4. '*' wildcard entry in the map
      5. hardcoded 'full' fallback

    Returns (tier, match_reason) where match_reason is a human-readable
    string for diagnostics (e.g. 'substring:claude-haiku').
    """
    norm = normalize_model_id(model_id)
    if not norm:
        return ("full", "unmatched_fallback")

    # Partition keys once.
    literal_keys: list[tuple[str, str]] = []
    glob_keys: list[tuple[str, str]] = []
    for key, tier in model_tier_map.items():
        if key == "*":
            continue
        if any(c in key for c in "*?["):
            glob_keys.append((key, tier))
        else:
            literal_keys.append((key, tier))

    # 1. Exact (against normalized keys)
    for key, tier in literal_keys:
        if normalize_model_id(key) == norm:
            return (tier, "exact")

    # 2. Glob
    for key, tier in glob_keys:
        if fnmatch.fnmatchcase(norm, key.lower()):
            return (tier, f"glob:{key}")

    # 3. Substring
    for key, tier in literal_keys:
        if key.lower() in norm:
            return (tier, f"substring:{key}")

    # 4. Wildcard
    if "*" in model_tier_map:
        return (model_tier_map["*"], "wildcard")

    # 5. Hardcoded
    return ("full", "unmatched_fallback")


def validate_bundle_disabled_overlap(cfg: Mapping[str, object]) -> list[str]:
    """Return human-readable warnings for tools in both a tier bundle and disabled_tools.

    disabled_tools applies AFTER tier filtering, so any overlap is silently
    filtered from exposure. This helper surfaces the overlap so users aren't
    confused when a tool listed in their core bundle doesn't appear.
    """
    bundles = cfg.get("tool_tier_bundles")
    disabled = cfg.get("disabled_tools")
    if not isinstance(bundles, Mapping) or not isinstance(disabled, (list, tuple, set)):
        return []
    disabled_set = {d for d in disabled if isinstance(d, str)}
    warnings: list[str] = []
    for tier_name, tools in bundles.items():
        if not isinstance(tools, (list, tuple, set)):
            continue
        for tool in tools:
            if isinstance(tool, str) and tool in disabled_set:
                warnings.append(
                    f"'{tool}' is in tool_tier_bundles.{tier_name} AND disabled_tools "
                    f"— it will never be exposed (disabled_tools applies after tier filtering)."
                )
    return warnings
