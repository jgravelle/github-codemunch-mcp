#!/usr/bin/env python
"""
Groq x jCodeMunch — End-to-end validation script.

Validates that Groq's remote MCP can discover and execute jCodeMunch tools,
and that the full retrieval + inference pipeline produces correct answers.

Prerequisites:
  - A running jCodeMunch SSE endpoint (HTTPS with bearer token auth)
  - GROQ_API_KEY env var set
  - JCODEMUNCH_MCP_URL env var set (e.g., https://mcp.example.com)
  - JCODEMUNCH_MCP_TOKEN env var set (bearer token for the MCP endpoint)

Usage:
  python examples/groq_validate.py
  python examples/groq_validate.py --repo jgravelle/jcodemunch-mcp
  python examples/groq_validate.py --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    from openai import OpenAI
except ImportError:
    sys.exit("Missing dependency: pip install openai")


# ── Allowed-tools presets ────────────────────────────────────────────────────

PRESETS = {
    "explore": [
        "list_repos", "resolve_repo", "get_repo_outline",
        "get_file_tree", "get_file_outline",
        "search_symbols", "get_symbol_source",
    ],
    "deep": [
        "list_repos", "resolve_repo", "get_repo_outline",
        "get_file_tree", "get_file_outline",
        "search_symbols", "get_symbol_source",
        "get_ranked_context", "get_context_bundle",
        "get_blast_radius", "get_call_hierarchy",
        "find_importers", "find_references",
    ],
    "review": [
        "list_repos", "resolve_repo",
        "search_symbols", "get_symbol_source",
        "get_ranked_context", "get_context_bundle",
        "get_changed_symbols", "get_blast_radius",
        "get_impact_preview", "check_rename_safe",
    ],
    "full": None,  # None = no filter, all tools available
}


# ── Test cases ───────────────────────────────────────────────────────────────

TESTS = [
    {
        "name": "tool_discovery",
        "description": "Groq discovers jCodeMunch tools via MCP",
        "input": "List all available tools from the jcodemunch MCP server. Just list their names.",
        "expect_contains": ["search_symbols", "get_symbol_source"],
        "preset": "explore",
    },
    {
        "name": "search_symbols",
        "description": "Search for a symbol via Groq → jCodeMunch",
        "input": "Use the search_symbols tool to find the 'parse_file' function in repo {repo}. Return the symbol name and file path.",
        "expect_contains": ["parse_file"],
        "preset": "explore",
    },
    {
        "name": "ranked_context",
        "description": "Retrieve ranked context for a natural language query",
        "input": "Use the get_ranked_context tool on repo {repo} with query 'how does file indexing work' and a token_budget of 4000. Summarize what you found.",
        "expect_contains": ["index"],
        "preset": "deep",
    },
    {
        "name": "full_qa",
        "description": "End-to-end: answer a codebase question using retrieval + inference",
        "input": "What does the parse_file function do in {repo}? Use the jcodemunch tools to look it up, then explain it.",
        "expect_contains": ["parse", "tree-sitter"],
        "preset": "deep",
    },
]


# ── Runner ───────────────────────────────────────────────────────────────────

def build_mcp_tool(url: str, token: str, preset: str) -> dict:
    """Build the Groq MCP tool configuration."""
    tool = {
        "type": "mcp",
        "server_label": "jcodemunch",
        "server_url": url,
        "server_description": (
            "Code intelligence: search symbols, get source, analyze "
            "dependencies across any indexed GitHub repo."
        ),
        "require_approval": "never",
    }
    if token:
        tool["headers"] = {"Authorization": f"Bearer {token}"}
    allowed = PRESETS.get(preset)
    if allowed is not None:
        tool["allowed_tools"] = allowed
    return tool


def run_test(
    client: OpenAI,
    model: str,
    mcp_url: str,
    mcp_token: str,
    test: dict,
    repo: str,
    verbose: bool,
) -> tuple[bool, str, float]:
    """Run a single validation test. Returns (passed, detail, elapsed_s)."""
    input_text = test["input"].format(repo=repo)
    tool = build_mcp_tool(mcp_url, mcp_token, test["preset"])

    start = time.perf_counter()
    try:
        response = client.responses.create(
            model=model,
            input=input_text,
            tools=[tool],
        )
        elapsed = time.perf_counter() - start

        # Extract text output from the response
        output_text = ""
        for item in response.output:
            if hasattr(item, "text"):
                output_text += item.text
            elif hasattr(item, "content"):
                for block in item.content:
                    if hasattr(block, "text"):
                        output_text += block.text

        if verbose:
            print(f"    Response ({elapsed:.1f}s): {output_text[:500]}")

        # Check expectations
        lower = output_text.lower()
        missing = [kw for kw in test["expect_contains"] if kw.lower() not in lower]
        if missing:
            return False, f"Missing expected keywords: {missing}", elapsed
        return True, "OK", elapsed

    except Exception as e:
        elapsed = time.perf_counter() - start
        return False, f"Error: {e}", elapsed


def main():
    parser = argparse.ArgumentParser(description="Validate Groq x jCodeMunch MCP integration")
    parser.add_argument("--repo", default="jgravelle/jcodemunch-mcp",
                        help="Repo to test against (must be indexed on the MCP server)")
    parser.add_argument("--model", default="llama-3.3-70b-versatile",
                        help="Groq model to use")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print full responses")
    parser.add_argument("--preset", choices=list(PRESETS.keys()),
                        help="Override allowed_tools preset for all tests")
    args = parser.parse_args()

    # Config from env
    groq_key = os.environ.get("GROQ_API_KEY")
    mcp_url = os.environ.get("JCODEMUNCH_MCP_URL")
    mcp_token = os.environ.get("JCODEMUNCH_MCP_TOKEN", "")

    if not groq_key:
        sys.exit("Set GROQ_API_KEY env var")
    if not mcp_url:
        sys.exit("Set JCODEMUNCH_MCP_URL env var (e.g., https://mcp.example.com)")

    client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")

    print(f"Groq x jCodeMunch Validation")
    print(f"  MCP endpoint: {mcp_url}")
    print(f"  Model:        {args.model}")
    print(f"  Repo:         {args.repo}")
    print(f"  Auth:         {'bearer token' if mcp_token else 'none'}")
    print()

    passed = 0
    failed = 0

    for test in TESTS:
        if args.preset:
            test = {**test, "preset": args.preset}

        print(f"  [{test['name']}] {test['description']}...", end=" ", flush=True)
        ok, detail, elapsed = run_test(
            client, args.model, mcp_url, mcp_token, test, args.repo, args.verbose
        )
        if ok:
            print(f"PASS ({elapsed:.1f}s)")
            passed += 1
        else:
            print(f"FAIL ({elapsed:.1f}s)")
            print(f"    {detail}")
            failed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed")

    if failed:
        # Dump presets for debugging
        print("\nAllowed-tools presets used:")
        for test in TESTS:
            p = args.preset or test["preset"]
            tools = PRESETS[p]
            print(f"  {test['name']}: {p} ({len(tools) if tools else 'all'} tools)")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
