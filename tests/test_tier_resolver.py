"""Tests for model id normalization + tier resolution."""

import pytest

from jcodemunch_mcp.tier_resolver import normalize_model_id, resolve_model_to_tier, validate_bundle_disabled_overlap


class TestNormalizeModelId:
    def test_lowercase(self):
        assert normalize_model_id("Claude-Opus") == "claude-opus"

    def test_strip_double_provider_prefix(self):
        assert normalize_model_id("openrouter/anthropic/claude-opus-4-7") == "claude-opus-4-7"

    def test_strip_single_provider_prefix(self):
        assert normalize_model_id("anthropic/claude-haiku-4-5") == "claude-haiku-4-5"

    def test_strip_bracket_suffix(self):
        assert normalize_model_id("claude-opus-4-7[1m]") == "claude-opus-4-7"

    def test_strip_bracket_beta(self):
        assert normalize_model_id("claude-sonnet-4-6[beta]") == "claude-sonnet-4-6"

    def test_strip_date_suffix(self):
        assert normalize_model_id("claude-haiku-4-5-20251001") == "claude-haiku-4-5"

    def test_strip_combined(self):
        assert normalize_model_id("anthropic/claude-opus-4-7[1m]") == "claude-opus-4-7"

    def test_empty_string(self):
        assert normalize_model_id("") == ""

    def test_whitespace_trimmed(self):
        assert normalize_model_id("  claude-opus  ") == "claude-opus"

    def test_non_string_returns_empty(self):
        assert normalize_model_id(None) == ""  # type: ignore[arg-type]
        assert normalize_model_id(123) == ""  # type: ignore[arg-type]


DEFAULT_MAP = {
    "claude-opus": "full",
    "claude-sonnet": "standard",
    "claude-haiku": "core",
    "gpt-4o": "standard",
    "gpt-5": "full",
    "o1": "full",
    "llama": "core",
    "*": "full",
}


class TestResolveModelToTier:
    def test_substring_haiku(self):
        tier, reason = resolve_model_to_tier("claude-haiku-4-5", DEFAULT_MAP)
        assert tier == "core"
        assert reason == "substring:claude-haiku"

    def test_substring_variant_with_date(self):
        tier, reason = resolve_model_to_tier("claude-haiku-4-5-20251001", DEFAULT_MAP)
        assert tier == "core"
        assert reason == "substring:claude-haiku"

    def test_bracket_suffix_opus(self):
        tier, reason = resolve_model_to_tier("claude-opus-4-7[1m]", DEFAULT_MAP)
        assert tier == "full"
        assert reason == "substring:claude-opus"

    def test_provider_prefix_sonnet(self):
        tier, reason = resolve_model_to_tier(
            "openrouter/anthropic/claude-sonnet-4-6", DEFAULT_MAP
        )
        assert tier == "standard"
        assert reason == "substring:claude-sonnet"

    def test_exact_match_takes_precedence(self):
        mp = {"claude-haiku-4-5": "full", "claude-haiku": "core"}
        tier, reason = resolve_model_to_tier("claude-haiku-4-5", mp)
        assert tier == "full"
        assert reason == "exact"

    def test_glob_match(self):
        mp = {"claude-opus-*": "full", "*": "standard"}
        tier, reason = resolve_model_to_tier("claude-opus-4-7", mp)
        assert tier == "full"
        assert reason == "glob:claude-opus-*"

    def test_wildcard_fallback(self):
        tier, reason = resolve_model_to_tier("totally-new-model", DEFAULT_MAP)
        assert tier == "full"
        assert reason == "wildcard"

    def test_hardcoded_fallback_when_no_wildcard(self):
        mp = {"claude-haiku": "core"}
        tier, reason = resolve_model_to_tier("brand-new-model", mp)
        assert tier == "full"
        assert reason == "unmatched_fallback"

    def test_empty_model_id(self):
        tier, reason = resolve_model_to_tier("", DEFAULT_MAP)
        assert tier == "full"
        assert reason == "unmatched_fallback"

    def test_gpt4o_substring(self):
        tier, reason = resolve_model_to_tier("gpt-4o-mini-2024-07-18", DEFAULT_MAP)
        assert tier == "standard"
        assert reason == "substring:gpt-4o"


class TestValidateBundleDisabledOverlap:
    def test_no_overlap_returns_empty(self):
        cfg = {
            "tool_tier_bundles": {"core": ["search_symbols"], "standard": ["find_references"]},
            "disabled_tools": ["test_summarizer"],
        }
        assert validate_bundle_disabled_overlap(cfg) == []

    def test_overlap_core_flagged(self):
        cfg = {
            "tool_tier_bundles": {"core": ["search_symbols", "find_references"]},
            "disabled_tools": ["find_references"],
        }
        warnings = validate_bundle_disabled_overlap(cfg)
        assert len(warnings) == 1
        assert "find_references" in warnings[0]
        assert "core" in warnings[0]
        assert "disabled_tools" in warnings[0]

    def test_overlap_multiple_tiers(self):
        cfg = {
            "tool_tier_bundles": {
                "core": ["get_symbol_source"],
                "standard": ["get_symbol_source"],
            },
            "disabled_tools": ["get_symbol_source"],
        }
        warnings = validate_bundle_disabled_overlap(cfg)
        # Two tiers x one tool = 2 warnings
        assert len(warnings) == 2

    def test_missing_keys_safe(self):
        assert validate_bundle_disabled_overlap({}) == []
        assert validate_bundle_disabled_overlap({"tool_tier_bundles": {}}) == []
        assert validate_bundle_disabled_overlap({"disabled_tools": []}) == []

    def test_malformed_config_safe(self):
        cfg = {"tool_tier_bundles": "not-a-dict", "disabled_tools": "not-a-list"}
        assert validate_bundle_disabled_overlap(cfg) == []
