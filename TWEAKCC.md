# System Prompt Routing via tweakcc

> **Credit:** This approach was designed and spec'd by [@vadash](https://github.com/vadash) in [#173](https://github.com/jgravelle/jcodemunch-mcp/issues/173).
>
> **Requires:** [tweakcc](https://github.com/Piebald-AI/tweakcc) — a tool that patches Claude Code's system prompts directly.

---

## Why system prompt routing?

The common failure mode with jCodemunch isn't forgetting — it's **skipping**. Claude sees the CLAUDE.md policy and reaches for `Read` or `Grep` anyway because native tools feel faster under pressure or in long sessions.

jCodemunch offers three enforcement layers:

| Layer | Mechanism | Strength |
|-------|-----------|----------|
| **CLAUDE.md policy** | Soft rules in project instructions | Weakest — ignored under cognitive load |
| **PreToolUse hooks** | Intercept tool calls at runtime | Medium — stderr warnings, allows Read for edits |
| **System prompt rewrites** (this doc) | Patch Claude's core instructions | Strongest — model internalizes the preference |

System prompt routing embeds jCodemunch preferences directly into the tool descriptions and usage instructions that Claude reads at the start of every conversation. The model never sees "use Grep for code search" — it sees "use search_symbols for code search" from the start.

---

## Architecture

### Before (3 enforcement layers)

```
CLAUDE.md (soft)  -->  PreToolUse hooks (hard)  -->  PostToolUse hook (auto)
  routing policy       read guard, edit guard        index_file after edit
```

### After (2 enforcement layers)

```
System prompts (deep)  -->  PostToolUse hook (auto)
  routing built into         index_file after edit
  core instructions          (unchanged)
```

### What gets dropped

| Component | Reason |
|-----------|--------|
| CLAUDE.md jCodemunch policy block | Replaced by system prompt rewrites |
| PreToolUse read guard | Replaced by prompt routing |
| PreToolUse edit guard | Replaced by prompt routing |

### What stays

| Component | Reason |
|-----------|--------|
| PostToolUse index hook | Auto re-index is free — no model load, no tool call overhead |

---

## Design Principles

1. **Code files** (`.ts` `.js` `.py` `.go` `.rs` `.java` `.rb` `.php` `.cs` `.cpp` `.c` `.h` `.swift` `.kt` `.scala` `.sql` etc.) route to jCodemunch
2. **Non-code files** (`.md` `.json` `.yaml` `.toml` `.env` `.txt` `.html` `.xml` `.csv`, images, PDFs) use native tools (`Read`, `Grep`, `Glob`)
3. **Read is not blocked** — `Edit`/`Write` need file content in context
4. **Read is deprioritized for code exploration** — model reaches for `get_file_outline` / `get_symbol_source` first
5. **Post-edit indexing** handled by hook, not prompt instruction — zero model overhead

---

## Prompt Rewrites (8 files)

All files are tweakcc prompt fragments. Headers (YAML frontmatter in `<!-- -->`) are preserved from the originals — only the content below the closing `-->` is replaced.

### 1. Read files (`system-prompt-tool-usage-read-files.md`)

```
Before reading any source code file, call jCodeMunch get_file_outline to see its structure first. To read specific symbols, use get_symbol_source (single symbol_id or batch symbol_ids[]) or get_context_bundle (symbol + its imports) instead of reading the whole file. Use ${READ_TOOL_NAME} for non-code files (.md, .json, .yaml, .toml, .env, .txt, .html, images, PDFs) and when you need complete file content before editing. Never use cat, head, tail, or sed to read any file.
```

### 2. Search content (`system-prompt-tool-usage-search-content.md`)

```
To search code by symbol name (function, class, method, variable), use jCodeMunch search_symbols -- narrow with kind=, language=, file_pattern=. To search for strings, comments, TODOs, or patterns in source code, use jCodeMunch search_text (supports regex via is_regex, context_lines for surrounding code). For database columns in dbt/SQLMesh projects, use search_columns. Use ${GREP_TOOL_NAME} only for searching non-code file content (.md, .json, .yaml, .txt, .env, config files). Never invoke grep or rg via Bash.
```

### 3. Search files (`system-prompt-tool-usage-search-files.md`)

```
To browse code project structure, use jCodeMunch get_file_tree (filter with path_prefix) or get_repo_outline for a high-level overview of directories, languages, and symbol counts. Use ${GLOB_TOOL_NAME} when finding files by name pattern. Never use find or ls via Bash for file discovery.
```

### 4. Reserve Bash (`system-prompt-tool-usage-reserve-bash.md`)

```
Reserve ${BASH_TOOL_NAME} exclusively for system commands and terminal operations: builds, tests, git, package managers, docker, kubectl, and similar. Never use ${BASH_TOOL_NAME} for code exploration -- do not run grep, rg, find, cat, head, or tail on source code files through it. Use jCodeMunch MCP tools for all code reading and searching. If unsure whether a dedicated tool exists, default to the dedicated tool.
```

### 5. Direct search (`system-prompt-tool-usage-direct-search.md`)

```
For directed codebase searches (finding a specific function, class, or method), use jCodeMunch search_symbols directly -- it is faster and more precise than text search. For text pattern searches in code, use jCodeMunch search_text. Use ${SEARCH_TOOLS} only when searching non-code file content.
```

### 6. Delegate exploration (`system-prompt-tool-usage-delegate-exploration.md`)

```
For broader codebase exploration, start with jCodeMunch: get_repo_outline for project overview, get_file_tree to browse structure, suggest_queries when the repo is unfamiliar. For deep research requiring multiple rounds, use the ${TASK_TOOL_NAME} tool with subagent_type=${EXPLORE_SUBAGENT.agentType} -- instruct subagents to prefer jCodeMunch over ${SEARCH_TOOLS} for source code exploration. Use subagents only when the task will clearly require more than ${QUERY_LIMIT} queries.
```

### 7. Subagent guidance (`system-prompt-tool-usage-subagent-guidance.md`)

```
Use the ${TASK_TOOL_NAME} tool with specialized agents when the task matches the agent's description. Subagents are valuable for parallelizing independent queries or protecting the main context window from excessive results. When delegating code exploration to subagents, instruct them to use jCodeMunch MCP tools (search_symbols, get_symbol_source, get_file_outline) rather than Read, Grep, or Glob for source code. Avoid duplicating work that subagents are already doing - if you delegate research to a subagent, do not also perform the same searches yourself.
```

### 8. Read first (`system-prompt-doing-tasks-read-first.md`)

```
Do not propose changes to code you haven't understood. Before modifying code, use
jCodeMunch to build context: get_file_outline to see the file's structure,
get_symbol_source or get_context_bundle to read the relevant symbols, and
get_blast_radius or find_references to understand the impact of your changes.

When working with source code, call resolve_repo with the current directory to
confirm the project is indexed. If not indexed, call index_folder. When a repo is
unfamiliar, call suggest_queries for orientation.

For non-code files (.md, .json, .yaml, .toml, .env, .txt, .html), use Read
directly.
```

---

## Hook Configuration

### Simplified `~/.claude/settings.json`

With system prompt routing active, only the PostToolUse hook is needed:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{
          "type": "command",
          "command": "jcodemunch-mcp hook-posttooluse"
        }]
      }
    ]
  }
}
```

All `PreToolUse` entries can be removed.

---

## Verification

| Test | Expected behavior |
|------|-------------------|
| "Find the main function in this project" | Uses `search_symbols`, not `Grep` |
| "What does UserService do?" | Uses `get_file_outline` + `get_symbol_source`, not `Read` |
| "Show me the project structure" | Uses `get_file_tree`, not `Glob` or `ls` |
| "Search for TODO comments" | Uses `search_text`, not `Grep` |
| "Read the README" | Uses `Read` (non-code file) |
| "Search package.json for the version" | Uses `Grep` or `Read` (non-code file) |
| Edit a `.ts` file | PostToolUse hook fires, re-indexes automatically |

---

## Combining with hooks

System prompt routing and hooks are **complementary**, not exclusive. You can run both:

- **Prompts** handle the 95% case — Claude reaches for jCodemunch by default
- **PreToolUse hook** (stderr warning) catches the remaining 5% under cognitive load
- **PostToolUse hook** keeps the index fresh regardless

This layered approach gives the strongest enforcement with the least friction.

---

## Rollback

To revert: restore original tweakcc prompt files, re-enable the CLAUDE.md policy block and PreToolUse hooks per [AGENT_HOOKS.md](AGENT_HOOKS.md).
