"""Claude Code hook handlers for jCodemunch enforcement.

PreToolUse  — intercept Read on large code files, suggest jCodemunch tools.
PostToolUse — auto-reindex after Edit/Write to keep the index fresh.
Guard hooks — hard-block code exploration via Bash/Grep/Glob, gate raw edits.

All hooks read JSON from stdin and write JSON to stdout per the Claude Code
hooks specification.
"""

import json
import os
import re
import subprocess
import sys


# Extensions that benefit from jCodemunch structural navigation.
# Kept intentionally broad — mirrors languages.py LANGUAGE_REGISTRY.
_CODE_EXTENSIONS: set[str] = {
    ".py", ".pyi",
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx", ".mts", ".cts",
    ".go",
    ".rs",
    ".java",
    ".php",
    ".rb",
    ".cs", ".cshtml", ".razor",
    ".cpp", ".c", ".h", ".hpp", ".cc", ".cxx",
    ".swift",
    ".kt", ".kts",
    ".scala",
    ".dart",
    ".lua", ".luau",
    ".ex", ".exs",
    ".erl", ".hrl",
    ".vue", ".svelte",
    ".sql",
    ".gd",       # GDScript
    ".al",       # AL (Business Central)
    ".gleam",
    ".nix",
    ".hcl", ".tf",
    ".proto",
    ".graphql", ".gql",
    ".verse",
    ".jl",       # Julia
    ".r", ".R",
    ".hs",       # Haskell
    ".f90", ".f95", ".f03", ".f08",  # Fortran
    ".groovy",
    ".pl", ".pm",  # Perl
    ".bash", ".sh", ".zsh",
}

# Minimum file size to trigger jCodemunch suggestion.
# Override with JCODEMUNCH_HOOK_MIN_SIZE env var.
_MIN_SIZE_BYTES = int(os.environ.get("JCODEMUNCH_HOOK_MIN_SIZE", "4096"))


def run_pretooluse() -> int:
    """PreToolUse hook: intercept Read calls on large code files.

    Reads hook JSON from stdin.  If the target is a code file above the
    size threshold, returns a ``deny`` decision with a message directing
    Claude to use jCodemunch tools instead.

    Small files, non-code files, and unreadable paths are silently allowed.

    Returns exit code (always 0 — errors are swallowed to avoid blocking).
    """
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # Unparseable → allow

    file_path: str = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0

    # Check extension
    _, ext = os.path.splitext(file_path)
    if ext.lower() not in _CODE_EXTENSIONS:
        return 0  # Not a code file → allow

    # Check size
    try:
        size = os.path.getsize(file_path)
    except OSError:
        return 0  # Can't stat → allow (file may not exist yet)

    if size < _MIN_SIZE_BYTES:
        return 0  # Small file → allow

    # Targeted reads (offset/limit set) are likely pre-edit — allow silently.
    tool_input = data.get("tool_input", {})
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return 0

    # Full-file exploratory read on a large code file — warn but allow.
    # Hard deny breaks the Edit workflow (Claude Code requires Read before Edit).
    # Stderr text is surfaced to the agent as guidance.
    print(
        f"jCodemunch hint: this is a {size:,}-byte code file. "
        "Prefer get_file_outline + get_symbol_source for exploration. "
        "Use Read only when you need exact line numbers for Edit.",
        file=sys.stderr,
    )
    return 0


def run_posttooluse() -> int:
    """PostToolUse hook: auto-index files after Edit/Write.

    Reads hook JSON from stdin, extracts the file path, and spawns
    ``jcodemunch-mcp index-file <path>`` as a fire-and-forget background
    process to keep the index fresh.

    Non-code files are skipped.  Errors are swallowed silently.

    Returns exit code (always 0).
    """
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path: str = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0

    # Only re-index code files
    _, ext = os.path.splitext(file_path)
    if ext.lower() not in _CODE_EXTENSIONS:
        return 0

    # Fire-and-forget: spawn index-file in background
    try:
        kwargs: dict = dict(
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # On Windows, CREATE_NO_WINDOW prevents a console flash
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        subprocess.Popen(
            ["jcodemunch-mcp", "index-file", file_path],
            **kwargs,
        )
    except (OSError, FileNotFoundError):
        pass  # jcodemunch-mcp not in PATH → skip silently

    return 0


def run_precompact() -> int:
    """PreCompact hook: generate session snapshot before context compaction.

    Reads hook JSON from stdin. Builds a compact snapshot of the current
    session state and returns it as a message for context injection.

    Returns exit code (always 0 — errors are swallowed to avoid blocking).
    """
    try:
        json.load(sys.stdin)  # Validate stdin is valid JSON
    except (json.JSONDecodeError, ValueError):
        return 0

    # Build snapshot in-process (no MCP round-trip needed)
    try:
        from jcodemunch_mcp.tools.get_session_snapshot import get_session_snapshot
        snapshot_result = get_session_snapshot()
        snapshot_text = snapshot_result.get("snapshot", "")
    except Exception:
        return 0  # Snapshot failure must not block compaction

    if not snapshot_text:
        return 0

    # Return snapshot as hook output for context injection.
    # PreCompact has no hookSpecificOutput variant in Claude Code's schema,
    # so we use the top-level systemMessage field instead.
    result = {
        "systemMessage": snapshot_text,
    }
    json.dump(result, sys.stdout)
    return 0


# ---------------------------------------------------------------------------
# Guard hooks — replacements for the legacy shell scripts
# ---------------------------------------------------------------------------

# Regex for code-file extensions used by the explore guard.
_EXT_PATTERN = r"\.(?:" + "|".join(
    ext.lstrip(".") for ext in sorted(_CODE_EXTENSIONS)
) + r")\b"

# Commands that are safe even when they touch code files (builds, tests, VCS).
_SAFE_COMMANDS_RE = re.compile(
    r"(?:npm|yarn|pnpm|cargo|go |pytest|jest|vitest|rspec|mvn|gradle|"
    r"git |docker|kubectl|uv |pip |brew |jcodemunch|uvx jcodemunch)",
)

# Bash commands that indicate code exploration.
_EXPLORATION_COMMANDS_RE = re.compile(
    r"(?:grep|rg|find|cat|head|tail|sed|awk)\b",
)

_GUARD_EXPLORE_MESSAGE = """\
jCodemunch guard -- use structured retrieval instead.

  Discovery
  suggest_queries  -> best first step for an unfamiliar repo
  get_repo_outline -> high-level overview of the repo
  get_file_tree    -> browse directory structure
  get_file_outline -> list all symbols in a file (before reading any source)

  Retrieval
  search_symbols   -> find a function/class/method by name
  get_symbol_source -> fetch one symbol (symbol_id) or many (symbol_ids[])
  get_context_bundle -> symbol + its imports (+ optional callers) in one call
  get_file_content -> read a specific line range (last resort)

  Search
  search_text      -> full-text search (strings, comments, TODOs)
  search_columns   -> search dbt / SQLMesh / database column metadata

  Relationship & Impact
  find_importers   -> what imports a file
  find_references  -> where is an identifier used
  check_references -> quick dead-code check
  get_dependency_graph -> file-level dependency graph (up to 3 hops)
  get_blast_radius -> what breaks if this symbol changes
  get_class_hierarchy  -> full inheritance chain (ancestors + descendants)
  get_related_symbols  -> symbols related via co-location / shared importers
  get_symbol_diff  -> diff symbol sets between two indexed repo snapshots

  Utilities
  get_session_stats -> token savings and cost-avoided breakdown for this session

Not indexed yet? -> index_folder { "path": "/path/to/project" } first.
"""

_GUARD_EDIT_MESSAGE = """\
jCodemunch edit guard -- raw file edit {verb}.
{file_hint}
Before writing to source files, jCodeMunch read tools give you safer context:

  get_symbol_source            -> confirm you are editing the right implementation
  get_file_outline             -> see all symbols in the file before touching it
  get_blast_radius             -> understand what else breaks if you change this
  find_references              -> find all call sites that may need updating too
  search_text                  -> locate related strings, comments, or config values

To suppress this warning:  JCODEMUNCH_ALLOW_RAW_WRITE=1
To hard-block all edits:   JCODEMUNCH_HARD_BLOCK=1

Not indexed yet? -> index_folder {{ "path": "/path/to/project" }} first.
"""


def run_guard_explore() -> int:
    """PreToolUse guard: hard-block Bash/Grep/Glob code exploration.

    Intercepts Bash (grep/find/cat patterns), Grep, and Glob when they look
    like code exploration.  Builds, tests, and git operations pass through.

    Exit 2 = block with feedback.  Exit 0 = allow.
    Returns exit code (0 on parse errors to avoid blocking).
    """
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name: str = data.get("tool_name", "")
    if tool_name not in ("Bash", "Grep", "Glob"):
        return 0

    tool_input: dict = data.get("tool_input", {})

    # Build a single payload string from all relevant fields.
    payload_parts = [
        tool_input.get("command", ""),
        tool_input.get("file_path", ""),
        tool_input.get("pattern", ""),
        tool_input.get("query", ""),
    ]
    payload = " ".join(p for p in payload_parts if p)

    is_exploration = False

    if tool_name == "Bash":
        # Safe commands pass through even if they touch code files.
        if _SAFE_COMMANDS_RE.search(payload):
            return 0
        # Check for exploration commands targeting code files.
        if _EXPLORATION_COMMANDS_RE.search(payload) and re.search(_EXT_PATTERN, payload, re.IGNORECASE):
            is_exploration = True

    elif tool_name == "Grep":
        is_exploration = True

    elif tool_name == "Glob":
        if re.search(_EXT_PATTERN, payload, re.IGNORECASE):
            is_exploration = True

    if not is_exploration:
        return 0

    print(_GUARD_EXPLORE_MESSAGE, file=sys.stderr)
    return 2


def run_guard_edit() -> int:
    """PreToolUse guard: gate Edit/Write/MultiEdit with a warning or block.

    Default: soft gate (exit 0 + stderr warning).
    JCODEMUNCH_HARD_BLOCK=1: hard block (exit 2).
    JCODEMUNCH_ALLOW_RAW_WRITE=1: skip entirely.

    Returns exit code (0 on parse errors to avoid blocking).
    """
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name: str = data.get("tool_name", "")
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        return 0

    if os.environ.get("JCODEMUNCH_ALLOW_RAW_WRITE", "0") == "1":
        return 0

    tool_input: dict = data.get("tool_input", {})
    file_path: str = tool_input.get("file_path", "")
    file_hint = f"  Target file: {file_path}\n" if file_path else ""

    hard_block = os.environ.get("JCODEMUNCH_HARD_BLOCK", "0") == "1"

    if hard_block:
        verb = "blocked"
        exit_code = 2
    else:
        verb = "allowed -- but consider consulting jCodeMunch first"
        exit_code = 0

    print(_GUARD_EDIT_MESSAGE.format(verb=verb, file_hint=file_hint), file=sys.stderr)
    return exit_code
