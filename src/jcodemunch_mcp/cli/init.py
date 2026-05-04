"""jcodemunch-mcp init — one-command onboarding for MCP clients."""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CLAUDE_MD_MARKER = "## Code Exploration Policy"

_CLAUDE_MD_POLICY = """\
## Code Exploration Policy

Always use jCodemunch-MCP tools for code navigation. Never fall back to Read, Grep, Glob, or Bash for code exploration.
**Exception:** Use `Read` when you need to edit a file — the agent harness requires a `Read` before `Edit`/`Write` will succeed. Use jCodemunch tools to *find and understand* code, then `Read` only the specific file you're about to modify.

**Start any session:**
1. `resolve_repo { "path": "." }` — confirm the project is indexed. If not: `index_folder { "path": "." }`
2. `suggest_queries` — when the repo is unfamiliar

**Finding code:**
- symbol by name → `search_symbols` (add `kind=`, `language=`, `file_pattern=`, `decorator=` to narrow)
- decorator-aware queries → `search_symbols(decorator="X")` to find symbols with a specific decorator (e.g. `@property`, `@route`); combine with set-difference to find symbols *lacking* a decorator (e.g. "which endpoints lack CSRF protection?")
- string, comment, config value → `search_text` (supports regex, `context_lines`)
- database columns (dbt/SQLMesh) → `search_columns`

**Reading code:**
- before opening any file → `get_file_outline` first
- one or more symbols → `get_symbol_source` (single ID → flat object; array → batch)
- symbol + its imports → `get_context_bundle`
- specific line range only → `get_file_content` (last resort)

**Repo structure:**
- `get_repo_outline` → dirs, languages, symbol counts
- `get_file_tree` → file layout, filter with `path_prefix`

**Relationships & impact:**
- what imports this file → `find_importers`
- where is this name used → `find_references`
- is this identifier used anywhere → `check_references`
- file dependency graph → `get_dependency_graph`
- what breaks if I change X → `get_blast_radius`
- what symbols actually changed since last commit → `get_changed_symbols`
- find unreachable/dead code → `find_dead_code`
- class hierarchy → `get_class_hierarchy`

## Session-Aware Routing

**Opening move for any task:**
1. `plan_turn { "repo": "...", "query": "your task description", "model": "<your-model-id>" }` — get confidence + recommended files; the `model` parameter narrows the exposed tool list to match your capabilities at zero extra requests.
2. Obey the confidence level:
   - `high` → go directly to recommended symbols, max 2 supplementary reads
   - `medium` → explore recommended files, max 5 supplementary reads
   - `low` → the feature likely doesn't exist. Report the gap to the user. Do NOT search further hoping to find it.

**Interpreting search results:**
- If `search_symbols` returns `negative_evidence` with `verdict: "no_implementation_found"`:
  - Do NOT re-search with different terms hoping to find it
  - Do NOT assume a related file (e.g. auth middleware) implements the missing feature (e.g. CSRF)
  - DO report: "No existing implementation found for X. This would need to be created."
  - DO check `related_existing` files — they show what's nearby, not what exists
- If `verdict: "low_confidence_matches"`: examine the matches critically before assuming they implement the feature

**After editing files:**
- If PostToolUse hooks are installed (Claude Code only), edited files are auto-reindexed
- Otherwise, call `register_edit` with edited file paths to invalidate caches and keep the index fresh
- For bulk edits (5+ files), always use `register_edit` with all paths to batch-invalidate

**Token efficiency:**
- If `_meta` contains `budget_warning`: stop exploring and work with what you have
- If `auto_compacted: true` appears: results were automatically compressed due to turn budget
- Use `get_session_context` to check what you've already read — avoid re-reading the same files

## Model-Driven Tool Tiering

Your jcodemunch-mcp server narrows the exposed tool list based on the model you are running as. To avoid wasting requests on primitives when a composite would do, always include `model="<your-model-id>"` in your opening `plan_turn` call.

Replace `<your-model-id>` with your active model:
- Claude Opus variants → `claude-opus-4-7` (or any `claude-opus-*`)
- Claude Sonnet variants → `claude-sonnet-4-6`
- Claude Haiku variants → `claude-haiku-4-5`
- GPT-4o / GPT-5 / o1 / Llama → use the model id as printed by your runner

The `model=` parameter rides on the existing `plan_turn` call — it does **not** add a separate tool invocation. If `plan_turn` is not appropriate for a non-code task, call `announce_model(model="...")` once instead.
"""

_MCP_ENTRY = {
    "command": "uvx",
    "args": ["jcodemunch-mcp"],
}

def _hook_invocation() -> str:
    """Return the executable path used in hook command strings.

    Claude Code spawns hooks via /bin/sh on macOS/Linux, which uses a minimal
    PATH that excludes ~/.local/bin, ~/Library/Python/*/bin, pipx venvs, etc.
    Writing the bare name ``jcodemunch-mcp`` into settings.json works only when
    the user's interactive PATH happens to match the subshell's PATH — fragile.
    Resolve to an absolute path at install time so hooks work regardless of
    the spawning shell. Quote if the path contains spaces.
    """
    resolved = shutil.which("jcodemunch-mcp")
    if not resolved:
        # Fall back to bare name; user will get a clear error if PATH is wrong.
        return "jcodemunch-mcp"
    if " " in resolved:
        return f'"{resolved}"'
    return resolved


def _worktree_hooks() -> dict[str, Any]:
    exe = _hook_invocation()
    return {
        "WorktreeCreate": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": f"{exe} hook-event create"}],
        }],
        "WorktreeRemove": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": f"{exe} hook-event remove"}],
        }],
    }


def _enforcement_hooks() -> dict[str, Any]:
    exe = _hook_invocation()
    return {
        "PreToolUse": [{
            "matcher": "Read",
            "hooks": [{"type": "command", "command": f"{exe} hook-pretooluse"}],
        }],
        "PostToolUse": [{
            "matcher": "Edit|Write",
            "hooks": [{"type": "command", "command": f"{exe} hook-posttooluse"}],
        }],
        "PreCompact": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": f"{exe} hook-precompact"}],
        }],
        "TaskCompleted": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": f"{exe} hook-taskcomplete"}],
        }],
        "SubagentStart": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": f"{exe} hook-subagent-start"}],
        }],
    }

# Cursor rules use MDC format (frontmatter + markdown).
# alwaysApply: true ensures the rule is in context for every agent turn,
# including subagents — which is the main reliability complaint.
_CURSOR_RULES_CONTENT = """\
---
description: Use jCodemunch MCP tools for all code navigation instead of built-in search
alwaysApply: true
---

""" + _CLAUDE_MD_POLICY

# Windsurf uses a plain-text .windsurfrules file in the project root.
_WINDSURF_RULES_CONTENT = _CLAUDE_MD_POLICY


# ---------------------------------------------------------------------------
# Client detection
# ---------------------------------------------------------------------------

class MCPClient:
    """Represents a detected MCP client and how to configure it."""

    def __init__(self, name: str, config_path: Optional[Path], method: str):
        self.name = name
        self.config_path = config_path
        self.method = method  # "cli" | "json_patch"

    def __repr__(self) -> str:
        if self.config_path:
            return f"{self.name} ({self.config_path})"
        return self.name


def _find_executable(name: str) -> Optional[str]:
    """Return path to executable or None."""
    return shutil.which(name)


def _expand_appdata(*parts: str) -> Path:
    """Expand %APPDATA% on Windows, ~/ on others."""
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata, *parts)
    return Path.home().joinpath(*parts)


def _detect_clients() -> list[MCPClient]:
    """Detect installed MCP clients."""
    clients: list[MCPClient] = []

    # Claude Code CLI
    if _find_executable("claude"):
        clients.append(MCPClient("Claude Code", None, "cli"))

    # Claude Desktop
    if platform.system() == "Darwin":
        p = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif platform.system() == "Windows":
        p = _expand_appdata("Claude", "claude_desktop_config.json")
    else:
        p = Path.home() / ".config" / "claude" / "claude_desktop_config.json"
    if p.parent.exists():
        clients.append(MCPClient("Claude Desktop", p, "json_patch"))

    # Cursor
    cursor_dir = Path.home() / ".cursor"
    if cursor_dir.exists():
        clients.append(MCPClient("Cursor", cursor_dir / "mcp.json", "json_patch"))

    # Windsurf
    for d in [Path.home() / ".windsurf", Path.home() / ".codeium" / "windsurf"]:
        if d.exists():
            clients.append(MCPClient("Windsurf", d / "mcp_config.json", "json_patch"))
            break

    # Continue
    continue_dir = Path.home() / ".continue"
    if continue_dir.exists():
        clients.append(MCPClient("Continue", continue_dir / "config.json", "json_patch"))

    return clients


# ---------------------------------------------------------------------------
# Config patching
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON file, returning {} if it doesn't exist."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict[str, Any], *, backup: bool = True) -> None:
    """Write JSON, optionally creating a .bak backup first."""
    if backup and path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _has_jcodemunch_entry(data: dict[str, Any]) -> bool:
    """Check if jcodemunch is already configured in an MCP config."""
    servers = data.get("mcpServers", {})
    return "jcodemunch" in servers


def _patch_mcp_config(path: Path, *, backup: bool = True, dry_run: bool = False) -> str:
    """Add jcodemunch entry to an MCP client JSON config.

    Returns a status message.
    """
    data = _read_json(path)
    if _has_jcodemunch_entry(data):
        return f"  already configured in {path}"

    if dry_run:
        return f"  would add jcodemunch to {path}"

    if "mcpServers" not in data:
        data["mcpServers"] = {}
    data["mcpServers"]["jcodemunch"] = _MCP_ENTRY
    _write_json(path, data, backup=backup)
    return f"  added jcodemunch to {path}"


def _configure_claude_code(*, dry_run: bool = False) -> str:
    """Run `claude mcp add` for Claude Code CLI."""
    if dry_run:
        return "  would run: claude mcp add jcodemunch uvx jcodemunch-mcp"
    try:
        result = subprocess.run(
            ["claude", "mcp", "add", "jcodemunch", "uvx", "jcodemunch-mcp"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return "  ran: claude mcp add jcodemunch uvx jcodemunch-mcp"
        # Already exists or other non-fatal issue
        stderr = result.stderr.strip()
        if "already exists" in stderr.lower():
            return "  already configured in Claude Code"
        return f"  claude mcp add failed: {stderr or result.stdout.strip()}"
    except FileNotFoundError:
        return "  claude CLI not found — skipped"
    except subprocess.TimeoutExpired:
        return "  claude mcp add timed out"


def configure_client(client: MCPClient, *, backup: bool = True, dry_run: bool = False) -> str:
    """Configure a single MCP client. Returns a status message."""
    if client.method == "cli":
        return _configure_claude_code(dry_run=dry_run)
    elif client.method == "json_patch" and client.config_path:
        return _patch_mcp_config(client.config_path, backup=backup, dry_run=dry_run)
    return f"  unknown method for {client.name}"


# ---------------------------------------------------------------------------
# CLAUDE.md injection
# ---------------------------------------------------------------------------

def _claude_md_path(scope: str) -> Path:
    """Return the CLAUDE.md path for the given scope."""
    if scope == "global":
        return Path.home() / ".claude" / "CLAUDE.md"
    return Path.cwd() / "CLAUDE.md"


def _has_policy(path: Path) -> bool:
    """Check if the Code Exploration Policy marker already exists."""
    if not path.exists():
        return False
    return _CLAUDE_MD_MARKER in path.read_text(encoding="utf-8")


def _get_active_tools() -> set[str] | None:
    """Return the set of tool names active under current config.

    Applies tool_profile and disabled_tools filtering.
    Returns ``None`` when the profile is "full" and nothing is disabled
    (i.e. no filtering needed).
    """
    try:
        from ..config import get as cfg_get
        from ..server import _PROFILE_TIERS, _CANONICAL_TOOL_NAMES
    except Exception:
        return None

    profile = cfg_get("tool_profile", "full")
    tier = _PROFILE_TIERS.get(profile)
    disabled = set(cfg_get("disabled_tools", []))

    if tier is None and not disabled:
        return None  # full profile, nothing disabled

    active = set(_CANONICAL_TOOL_NAMES) if tier is None else set(tier)
    active -= disabled
    return active


# Regex matching tool names in backtick contexts:
#  - `tool_name` (exact)
#  - `tool_name { ... }` (tool with inline args)
#  - `tool_name(...)` (tool with call syntax)
_TOOL_REF_RE = re.compile(r"`([a-z][a-z0-9_]*)[`(\s{]")


def _filter_policy_for_tools(policy: str, active_tools: set[str] | None) -> str:
    """Filter the CLAUDE.md policy to only reference available tools.

    Lines containing backtick-quoted tool names that are NOT in
    *active_tools* are removed.  Sections left empty after filtering
    are also removed.  Returns the policy unchanged when *active_tools*
    is ``None`` (full profile, nothing disabled).
    """
    if active_tools is None:
        return policy

    # Build the set of all known tool names for reference-detection.
    try:
        from ..server import _CANONICAL_TOOL_NAMES
        all_tools = set(_CANONICAL_TOOL_NAMES)
    except Exception:
        return policy

    lines = policy.splitlines(keepends=True)
    kept: list[str] = []

    for line in lines:
        refs = _TOOL_REF_RE.findall(line)
        # Only consider refs that are actual tool names
        tool_refs = [r for r in refs if r in all_tools]
        if tool_refs and any(t not in active_tools for t in tool_refs):
            continue  # drop line — references unavailable tool(s)
        kept.append(line)

    # Remove bold-label headers (e.g. "**Finding code:**") that lost all
    # their child bullets.  A bold-label is "empty" if the next non-blank
    # line is another bold-label, a ## heading, or EOF.
    # We do NOT prune ## headings here — they may legitimately sit above
    # bold-label sub-sections that survived filtering.
    result: list[str] = []
    i = 0
    while i < len(kept):
        line = kept[i]
        stripped = line.strip()

        is_bold_label = (
            stripped.startswith("**")
            and stripped.endswith(":**")
            and not stripped.startswith("## ")
        )

        if is_bold_label:
            j = i + 1
            while j < len(kept) and not kept[j].strip():
                j += 1
            if j >= len(kept):
                break  # trailing empty label — drop
            next_s = kept[j].strip()
            next_is_boundary = (
                (next_s.startswith("**") and next_s.endswith(":**"))
                or next_s.startswith("## ")
            )
            if next_is_boundary:
                i = j  # skip empty bold-label section
                continue

        result.append(line)
        i += 1

    return "".join(result)


def install_claude_md(scope: str = "global", *, dry_run: bool = False, backup: bool = True) -> str:
    """Append the Code Exploration Policy to CLAUDE.md.

    scope: "global" or "project"
    Returns a status message.
    Respects ``tool_profile`` and ``disabled_tools`` from config.
    """
    path = _claude_md_path(scope)
    if _has_policy(path):
        return f"  policy already present in {path}"
    if dry_run:
        return f"  would append policy to {path}"

    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(".md.bak"))

    policy = _filter_policy_for_tools(_CLAUDE_MD_POLICY, _get_active_tools())
    with open(path, "a", encoding="utf-8") as f:
        if path.exists() and path.stat().st_size > 0:
            f.write("\n\n")
        f.write(policy)

    return f"  appended policy to {path}"


# ---------------------------------------------------------------------------
# Cursor rules injection
# ---------------------------------------------------------------------------

def _cursor_rules_path() -> Path:
    """Return the project-level Cursor rules path for jcodemunch."""
    return Path.cwd() / ".cursor" / "rules" / "jcodemunch.mdc"


def install_cursor_rules(*, dry_run: bool = False, backup: bool = True) -> str:
    """Write .cursor/rules/jcodemunch.mdc in the current project.

    Returns a status message.
    """
    path = _cursor_rules_path()
    if path.exists() and _CLAUDE_MD_MARKER in path.read_text(encoding="utf-8"):
        return f"  already present in {path}"
    if dry_run:
        return f"  would write {path}"

    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(".mdc.bak"))

    active = _get_active_tools()
    content = _CURSOR_RULES_CONTENT
    if active is not None:
        # Rebuild with filtered policy (preserve MDC frontmatter)
        filtered = _filter_policy_for_tools(_CLAUDE_MD_POLICY, active)
        content = (
            "---\n"
            "description: Use jCodemunch MCP tools for all code navigation instead of built-in search\n"
            "alwaysApply: true\n"
            "---\n\n"
        ) + filtered
    path.write_text(content, encoding="utf-8")
    return f"  wrote {path}"


# ---------------------------------------------------------------------------
# Windsurf rules injection
# ---------------------------------------------------------------------------

def _windsurf_rules_path() -> Path:
    """Return the project-level .windsurfrules path."""
    return Path.cwd() / ".windsurfrules"


def install_windsurf_rules(*, dry_run: bool = False, backup: bool = True) -> str:
    """Append the Code Exploration Policy to .windsurfrules.

    Returns a status message.
    """
    path = _windsurf_rules_path()
    if path.exists() and _CLAUDE_MD_MARKER in path.read_text(encoding="utf-8"):
        return f"  already present in {path}"
    if dry_run:
        return f"  would append policy to {path}"

    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(".windsurfrules.bak"))

    policy = _filter_policy_for_tools(_CLAUDE_MD_POLICY, _get_active_tools())
    with open(path, "a", encoding="utf-8") as f:
        if path.exists() and path.stat().st_size > 0:
            f.write("\n\n")
        f.write(policy)

    return f"  appended policy to {path}"


# ---------------------------------------------------------------------------
# AGENTS.md (OpenCode, Codex, etc.)
# ---------------------------------------------------------------------------

def install_agents_md(*, dry_run: bool = False, backup: bool = True) -> str:
    """Write ./AGENTS.md with the plan_turn(model=...) directive.

    OpenCode, Codex, and several other agent runners read AGENTS.md as
    their per-project system-prompt augmentation. Mirrors CLAUDE.md
    policy so agents swapped via those runners observe the same
    tier-switching convention.
    """
    target = Path.cwd() / "AGENTS.md"
    policy = _filter_policy_for_tools(_CLAUDE_MD_POLICY, _get_active_tools())
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if _CLAUDE_MD_MARKER in existing:
            return f"  already present in {target}"
        if dry_run:
            return f"  would append policy to {target}"
        if backup:
            shutil.copy2(target, target.with_suffix(".md.bak"))
        target.write_text(existing.rstrip() + "\n\n" + policy + "\n", encoding="utf-8")
    else:
        if dry_run:
            return f"  would create {target}"
        target.write_text(policy + "\n", encoding="utf-8")

    return f"  wrote {target}"


# ---------------------------------------------------------------------------
# Hooks injection
# ---------------------------------------------------------------------------

def _settings_json_path() -> Path:
    """Return the Claude Code settings.json path."""
    if platform.system() == "Windows":
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".claude" / "settings.json"
    return Path.home() / ".claude" / "settings.json"


def _merge_hooks(
    data: dict[str, Any],
    hook_defs: dict[str, list],
    marker: str,
) -> list[str]:
    """Merge hook definitions into settings data, returning names of added events.

    ``marker`` is a substring used to detect whether our hook is already
    installed (e.g. ``"jcodemunch-mcp hook-event"``).

    Each rule is checked individually: if a rule's command already exists
    in the event's hook list, it is skipped.  This allows multiple rules
    for the same event to be added incrementally.
    """
    hooks = data.setdefault("hooks", {})
    added: list[str] = []

    for event_name, event_hooks in hook_defs.items():
        existing_cmds: set[str] = set()
        if event_name in hooks:
            for rule in hooks[event_name]:
                for h in rule.get("hooks", []):
                    existing_cmds.add(h.get("command", ""))

        new_rules = []
        for rule in event_hooks:
            rule_cmds = [h.get("command", "") for h in rule.get("hooks", [])]
            # Skip if this specific rule's command is already installed.
            if any(cmd in existing_cmds for cmd in rule_cmds if cmd):
                continue
            # Fallback: check against the broad marker for legacy detection.
            if any(marker in cmd for cmd in existing_cmds):
                if any(marker in cmd for cmd in rule_cmds):
                    continue
            new_rules.append(rule)

        if new_rules:
            if event_name in hooks:
                hooks[event_name].extend(new_rules)
            else:
                hooks[event_name] = new_rules
            added.append(event_name)

    return added


def install_hooks(*, dry_run: bool = False, backup: bool = True) -> str:
    """Merge worktree and tool hooks into ~/.claude/settings.json.

    Returns a status message.
    """
    path = _settings_json_path()
    data = _read_json(path)
    added = _merge_hooks(data, _worktree_hooks(), "jcodemunch-mcp hook-event")

    if not added:
        return f"  hooks already present in {path}"
    if dry_run:
        return f"  would add {', '.join(added)} hooks to {path}"

    _write_json(path, data, backup=backup)
    return f"  added {', '.join(added)} hooks to {path}"


def _install_version_path() -> Path:
    """Path to the file recording the jcodemunch-mcp version that last ran ``init``."""
    base = Path(os.environ.get("CODE_INDEX_PATH", str(Path.home() / ".code-index")))
    return base / "last_init_version.txt"


def _stamp_install_version() -> None:
    """Record the currently-installed jcodemunch-mcp version.

    Used by the server-startup version probe to detect when the package
    has been upgraded but ``init`` has not been re-run (so hooks/config
    may be stale).
    """
    from .. import __version__
    path = _install_version_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__version__.strip(), encoding="utf-8")


def read_install_version() -> Optional[str]:
    """Read the version recorded by the last ``init`` run, if any."""
    path = _install_version_path()
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def install_copilot_hooks(*, dry_run: bool = False, backup: bool = True) -> str:
    """Write a ``.github/hooks/hooks.json`` for GitHub Copilot CLI / cloud agent.

    Generates a postToolUse hook that invokes
    ``jcodemunch-mcp hook-copilot-posttooluse`` so that file edits made
    by Copilot trigger an automatic re-index, parallel to the Claude
    Code PostToolUse handling.

    The file is written at ``<cwd>/.github/hooks/hooks.json``. If a
    hooks.json already exists, the postToolUse rule is appended only if
    no rule with the same command is present (idempotent).
    """
    cwd = Path.cwd()
    hooks_dir = cwd / ".github" / "hooks"
    hooks_path = hooks_dir / "hooks.json"

    rule = {
        "type": "command",
        "bash": "jcodemunch-mcp hook-copilot-posttooluse",
        "powershell": "jcodemunch-mcp hook-copilot-posttooluse",
        "timeoutSec": 30,
        "comment": "jcodemunch-mcp: auto-reindex edited files",
    }

    if hooks_path.exists():
        try:
            data = json.loads(hooks_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, OSError):
            return f"  failed to parse existing {hooks_path}; skipping"
        hooks = data.setdefault("hooks", {})
        existing = hooks.setdefault("postToolUse", [])
        for r in existing:
            if r.get("bash", "").startswith("jcodemunch-mcp hook-copilot"):
                return f"  Copilot hooks already present in {hooks_path}"
        if dry_run:
            return f"  would append jcodemunch postToolUse hook to {hooks_path}"
        existing.append(rule)
        data.setdefault("version", 1)
        if backup:
            hooks_path.with_suffix(".json.bak").write_text(
                hooks_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        hooks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return f"  appended Copilot postToolUse hook to {hooks_path}"

    if dry_run:
        return f"  would create {hooks_path} with jcodemunch postToolUse hook"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "hooks": {"postToolUse": [rule]}}
    hooks_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return f"  wrote {hooks_path} with jcodemunch postToolUse hook"


def install_enforcement_hooks(*, dry_run: bool = False, backup: bool = True) -> str:
    """Merge PreToolUse/PostToolUse enforcement hooks into ~/.claude/settings.json.

    PreToolUse (Read)  — nudge Claude toward jCodemunch for large code files.
    PostToolUse (Edit|Write) — auto-reindex modified files.

    Returns a status message.
    """
    path = _settings_json_path()
    data = _read_json(path)
    added = _merge_hooks(data, _enforcement_hooks(), "jcodemunch-mcp hook-p")  # matches hook-pretooluse & hook-posttooluse & hook-precompact

    if not added:
        return f"  enforcement hooks already present in {path}"
    if dry_run:
        return f"  would add {', '.join(added)} enforcement hooks to {path}"

    _write_json(path, data, backup=backup)
    return f"  added {', '.join(added)} enforcement hooks to {path}"


# ---------------------------------------------------------------------------
# Index current directory
# ---------------------------------------------------------------------------

def run_index(*, dry_run: bool = False) -> str:
    """Index the current working directory using index_folder."""
    cwd = os.getcwd()
    if dry_run:
        return f"  would index {cwd}"

    try:
        from ..tools.index_folder import index_folder
        result = index_folder(path=cwd)
        files = result.get("files_indexed", "?")
        symbols = result.get("symbols_indexed", "?")
        return f"  indexed {cwd} ({files} files, {symbols} symbols)"
    except Exception as e:
        return f"  indexing failed: {e}"


# ---------------------------------------------------------------------------
# Audit agent config
# ---------------------------------------------------------------------------

def run_audit(*, project_path: Optional[str] = None, dry_run: bool = False) -> list[str]:
    """Run audit_agent_config and return formatted output lines."""
    if dry_run:
        return ["  would audit agent config files for token waste"]

    try:
        from ..tools.audit_agent_config import audit_agent_config
        result = audit_agent_config(project_path=project_path or os.getcwd())
    except Exception as e:
        return [f"  audit failed: {e}"]

    lines: list[str] = []
    total = result.get("total_tokens", 0)
    scanned = result.get("files_scanned", 0)

    if scanned == 0:
        lines.append("  no agent config files found")
        return lines

    lines.append(f"  scanned {scanned} file(s), {total:,} tokens total per turn")

    # Token breakdown (compact)
    for entry in result.get("token_breakdown", []):
        scope_tag = " (global)" if entry["scope"] == "global" else ""
        lines.append(f"    {entry['tokens']:>5,} tokens  {entry['description']}{scope_tag}")

    # Findings
    findings = result.get("findings", [])
    if findings:
        lines.append(f"  {len(findings)} finding(s):")
        for f in findings[:10]:  # Cap display at 10
            icon = "!" if f["severity"] == "warning" else "-"
            loc = f" (line {f['line']})" if f.get("line") else ""
            lines.append(f"    {icon} [{f['category']}]{loc} {f['message']}")
        if len(findings) > 10:
            lines.append(f"    ... and {len(findings) - 10} more")
    else:
        lines.append("  no issues found")

    return lines


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

def _prompt_yn(message: str, default: bool = True) -> bool:
    """Prompt for yes/no, with a default."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    try:
        answer = input(message + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default
    return answer in ("y", "yes")


def _prompt_choice(message: str, options: list[str], allow_all: bool = True) -> list[str]:
    """Prompt user to pick from numbered options. Returns selected option labels."""
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")
    extra = "/all/none" if allow_all else "/none"
    try:
        raw = input(f"{message} [1-{len(options)}{extra}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return []
    if raw == "none" or raw == "":
        return []
    if raw == "all":
        return options
    selected = []
    for part in raw.replace(",", " ").split():
        try:
            idx = int(part) - 1
            if 0 <= idx < len(options):
                selected.append(options[idx])
        except ValueError:
            continue
    return selected


def _prompt_scope(message: str) -> Optional[str]:
    """Prompt for global/project/skip."""
    try:
        raw = input(f"{message} [global/project/skip]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if raw in ("global", "g"):
        return "global"
    if raw in ("project", "p"):
        return "project"
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_init(
    *,
    clients: Optional[list[str]] = None,
    claude_md: Optional[str] = None,
    hooks: bool = False,
    copilot_hooks: bool = False,
    index: bool = False,
    audit: bool = False,
    dry_run: bool = False,
    demo: bool = False,
    yes: bool = False,
    no_backup: bool = False,
) -> int:
    """Run the init flow. Returns exit code (0 = success)."""
    if demo:
        dry_run = True  # demo never writes anything
    backup = not no_backup
    interactive = not yes and sys.stdin.isatty()

    if demo:
        print("\njCodeMunch init -- DEMO MODE (no changes will be made)\n")
    else:
        print("\njCodeMunch init -- one-command setup\n")

    # Collects (action_label, benefit) for the demo summary
    _demo_actions: list[tuple[str, str]] = []

    # ----- Step 1: MCP client registration -----
    detected = _detect_clients()

    if clients is not None:
        # Explicit --client flag
        if "auto" in clients:
            targets = detected
        elif "none" in clients:
            targets = []
        else:
            name_map = {c.name.lower().replace(" ", "-"): c for c in detected}
            targets = [name_map[n] for n in clients if n in name_map]
    elif interactive and detected:
        print("Detected MCP clients:")
        names = [repr(c) for c in detected]
        selected = _prompt_choice("Configure which?", names)
        targets = [c for c in detected if repr(c) in selected]
    elif detected:
        targets = detected  # non-interactive + no flag = configure all
    else:
        targets = []
        print("No MCP clients detected.\n")

    for client in targets:
        msg = configure_client(client, backup=backup, dry_run=dry_run)
        print(f"  {client.name}:{msg}")
        if demo and "would" in msg:
            loc = str(client.config_path) if client.config_path else "via CLI"
            _demo_actions.append((
                f"Register jcodemunch with {client.name} ({loc})",
                "Your AI assistant could immediately call all jCodemunch tools without any manual setup or restart",
            ))

    # ----- Step 2: Agent policies -----
    selected_names = {c.name for c in targets}

    # 2a: CLAUDE.md (Claude Code / Claude Desktop)
    md_scope = claude_md
    if md_scope is None and interactive:
        print()
        md_scope = _prompt_scope("Install CLAUDE.md policy?")
    elif md_scope is None and yes:
        md_scope = "global"  # default for --yes mode

    if md_scope in ("global", "project"):
        msg = install_claude_md(md_scope, dry_run=dry_run, backup=backup)
        print(f"  CLAUDE.md:{msg}")
        if demo and "would" in msg:
            where = "globally (all projects)" if md_scope == "global" else "in this project only"
            _demo_actions.append((
                f"Inject Code Exploration Policy into CLAUDE.md {where}",
                "Every future Claude session would automatically navigate code via jCodemunch — no slow, token-heavy file reads",
            ))

    # 2b: Cursor rules (.cursor/rules/jcodemunch.mdc)
    if "Cursor" in selected_names:
        do_cursor_rules = yes or not interactive
        if interactive:
            print()
            do_cursor_rules = _prompt_yn(
                "Install Cursor rules (.cursor/rules/jcodemunch.mdc)?",
            )
        if do_cursor_rules:
            msg = install_cursor_rules(dry_run=dry_run, backup=backup)
            print(f"  Cursor rules:{msg}")
            if demo and "would" in msg:
                _demo_actions.append((
                    "Write .cursor/rules/jcodemunch.mdc (alwaysApply: true)",
                    "Cursor and its subagents would prefer jCodemunch tools over built-in search on every turn — no more unreliable fallbacks",
                ))

    # 2c: Windsurf rules (.windsurfrules)
    if "Windsurf" in selected_names:
        do_windsurf_rules = yes or not interactive
        if interactive:
            print()
            do_windsurf_rules = _prompt_yn(
                "Install Windsurf rules (.windsurfrules)?",
            )
        if do_windsurf_rules:
            msg = install_windsurf_rules(dry_run=dry_run, backup=backup)
            print(f"  Windsurf rules:{msg}")
            if demo and "would" in msg:
                _demo_actions.append((
                    "Append Code Exploration Policy to .windsurfrules",
                    "Windsurf Cascade would prefer jCodemunch tools over built-in search on every turn",
                ))

    # 2d: AGENTS.md (OpenCode, Codex, etc.)
    do_agents_md = yes or not interactive
    if interactive:
        print()
        do_agents_md = _prompt_yn(
            "Install AGENTS.md (OpenCode/Codex policy)?",
        )
    if do_agents_md:
        msg = install_agents_md(dry_run=dry_run, backup=backup)
        print(f"  AGENTS.md:{msg}")
        if demo and "would" in msg:
            _demo_actions.append((
                "Create AGENTS.md with Code Exploration Policy",
                "OpenCode, Codex, and other AGENTS.md-reading agents would prefer jCodemunch tools over built-in search",
            ))

    # ----- Step 3: Agent hooks -----
    do_hooks = hooks
    if not do_hooks and interactive:
        print()
        do_hooks = _prompt_yn("Install worktree hooks?", default=False)
    if do_hooks:
        msg = install_hooks(dry_run=dry_run, backup=backup)
        print(f"  Hooks:{msg}")
        if demo and "would" in msg:
            _demo_actions.append((
                "Install WorktreeCreate/WorktreeRemove hooks in ~/.claude/settings.json",
                "New git worktrees would be automatically indexed so jCodemunch stays in sync with every branch you check out",
            ))

    # ----- Step 3b: Enforcement hooks (PreToolUse + PostToolUse) -----
    do_enforce = hooks  # same flag enables enforcement hooks
    if not do_enforce and interactive:
        print()
        do_enforce = _prompt_yn(
            "Install enforcement hooks (intercept Read on large code files, auto-reindex after Edit/Write)?",
            default=True,
        )
    elif not do_enforce and yes:
        do_enforce = True  # default for --yes mode
    if do_enforce:
        msg = install_enforcement_hooks(dry_run=dry_run, backup=backup)
        print(f"  Enforcement:{msg}")
        # touch the install-version stamp so `serve` startup can detect drift
        try:
            _stamp_install_version()
        except Exception:
            pass
        if demo and "would" in msg:
            _demo_actions.append((
                "Install PreToolUse + PostToolUse enforcement hooks in ~/.claude/settings.json",
                "Large code files would be routed through jCodemunch (get_file_outline + get_symbol_source) "
                "instead of raw Read, and the index would auto-update after every Edit/Write — "
                "eliminating staleness anxiety and enforcing token-efficient navigation",
            ))

    # ----- Step 3c: Copilot hooks (.github/hooks/hooks.json) -----
    if copilot_hooks:
        msg = install_copilot_hooks(dry_run=dry_run, backup=backup)
        print(f"  Copilot hooks:{msg}")
        if demo and "would" in msg:
            _demo_actions.append((
                "Write .github/hooks/hooks.json with a jcodemunch postToolUse rule",
                "GitHub Copilot CLI / cloud-agent runs would auto-reindex edited files, "
                "keeping jCodemunch fresh without any manual `index-file` calls",
            ))

    # ----- Step 4: Index -----
    do_index = index
    if not do_index and interactive:
        print()
        do_index = _prompt_yn(f"Index current directory ({os.getcwd()})?", default=True)
    if do_index:
        msg = run_index(dry_run=dry_run)
        print(f"  Index:{msg}")
        if demo and "would" in msg:
            _demo_actions.append((
                f"Index {os.getcwd()}",
                "Symbol search, find-references, and repo exploration would be available immediately — without opening a single file",
            ))

    # ----- Step 5: Audit agent config -----
    do_audit = audit
    if not do_audit and interactive:
        print()
        do_audit = _prompt_yn("Audit agent config files for token waste?", default=True)
    elif not do_audit and yes:
        do_audit = True  # default for --yes mode

    if do_audit:
        print()
        print("  Audit:")
        for line in run_audit(project_path=os.getcwd(), dry_run=dry_run):
            print(line)
        if demo:
            _demo_actions.append((
                "Audit agent config files (CLAUDE.md, .cursorrules, etc.) for token waste",
                "Stale symbols, oversized instructions, and repeated boilerplate would be flagged — reducing context overhead on every Claude turn",
            ))

    # ----- Done -----
    print()
    if demo:
        print("Demo complete — no changes were made.\n")
        if _demo_actions:
            print("Had this NOT been a demo, I would have:\n")
            for action, benefit in _demo_actions:
                print(f"  • {action}")
                print(f"    Benefit: {benefit}")
                print()
        else:
            print("(Nothing to do — everything is already configured.)")
        print()
    elif dry_run:
        print("Dry run complete -- no changes were made.")
    else:
        print("Done. Restart your MCP client(s) to connect.")
    print()
    return 0
