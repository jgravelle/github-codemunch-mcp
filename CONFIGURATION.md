# Configuration Guide

jcodemunch-mcp uses a centralized JSONC configuration file instead of (or alongside) environment variables.

## Config files

| File | Purpose |
|------|---------|
| `~/.code-index/config.jsonc` | Global defaults — applies to all repos |
| `<project>/.jcodemunch.jsonc` | Project overrides — committed to version control, merges over global |

On first server start, the global config is auto-created with a commented template. You can regenerate it at any time:

```bash
jcodemunch-mcp config --init
```

## Resolution order

Settings are resolved from lowest to highest priority:

```
1. Hardcoded defaults          ← always present
2. Global config.jsonc         ← overwrites defaults
3. Project .jcodemunch.jsonc   ← merges over global, per-repo
4. Environment variables       ← FALLBACK only (fills gaps, doesn't override)
5. CLI flags                   ← highest priority (serve/watch commands)
```

**Why env vars are fallback, not override:** If env vars overrode project config, a global `JCODEMUNCH_MAX_FOLDER_FILES=10000` in your shell profile would silently break every project's tuned settings. With fallback semantics, config file values always win. Env vars only apply when the config key is absent.

Env vars emit a one-time deprecation warning when used, pointing to config.jsonc.

## CLI commands

```bash
# Print effective configuration with source tracking (default/config/env)
jcodemunch-mcp config

# Generate a commented config template
jcodemunch-mcp config --init

# Validate config + check prerequisites (storage, AI packages, HTTP transport)
jcodemunch-mcp config --check
```

## Configuration reference

### Indexing

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_folder_files` | int | `2000` | Maximum files indexed for local folders. Lower than repo default because folder indexing runs synchronously within the MCP timeout window. |
| `max_index_files` | int | `10000` | Maximum files indexed for GitHub repos (async, no timeout constraint). |
| `use_ai_summaries` | bool or str | `"auto"` | Enable AI-generated symbol summaries. `"auto"` (default) uses AI when a provider is detected, else falls back to signature-only summaries. `true`/`false` force the choice. Requires an API key (Anthropic, Google, or local LLM). |
| `summarizer_concurrency` | int | `4` | Parallel batch requests to the AI summarizer. |
| `allow_remote_summarizer` | bool | `false` | Allow remote AI summarizer even when local LLM is configured. |
| `extra_ignore_patterns` | list | `[]` | Additional gitignore-style patterns to exclude from indexing. Merged with per-call patterns. |
| `exclude_skip_directories` | list | `[]` | Remove entries from the built-in skip directory list. Example: `["proto"]` to index protobuf dirs skipped by default. |
| `exclude_secret_patterns` | list | `[]` | Remove entries from the built-in secret-file skip patterns. |
| `extra_extensions` | dict | `{}` | Map file extensions to language names (e.g. `{".jsx": "javascript"}`). Extends the built-in extension map. |
| `context_providers` | bool | `true` | Enable context providers (dbt model detection, etc.) during indexing. |
| `staleness_days` | int | `7` | Days before `get_repo_outline` emits a staleness warning for remote repos. |
| `max_results` | int | `500` | Hard cap on `search_columns` result count. |

### Languages

Controls which languages are parsed during indexing. When set, only listed languages get tree-sitter symbol extraction. Files of other languages are still discovered (for content caching) but produce no symbols.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `languages` | list or null | `null` | Language filter. `null` = all languages enabled. Set to a list to restrict. |
| `languages_adaptive` | bool | `false` | Automatically adjust the `languages` list based on detected languages during indexing. |

**Example — Python-only project:**

```jsonc
{
  // Only parse Python files. JS, SQL, etc. are discovered but not symbol-extracted.
  // This also auto-disables search_columns and the dbt context provider.
  "languages": ["python"]
}
```

**Example — Python + TypeScript monorepo:**

```jsonc
{
  "languages": ["python", "typescript", "tsx"]
}
```

When `"sql"` is removed from the list:
- `search_columns` tool is auto-removed from `list_tools()`
- The dbt context provider is disabled
- SQL files are not parsed (no symbols extracted)

The full list of supported language identifiers matches the values in `LANGUAGE_REGISTRY` (see [LANGUAGE_SUPPORT.md](LANGUAGE_SUPPORT.md)).

### Tools

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `disabled_tools` | list | `[]` | Tool names to remove from `list_tools()` schema. Project-level disabling also blocks execution via `call_tool()`. |
| `descriptions` | dict | `{}` | Override tool and parameter descriptions. See [Descriptions](#descriptions) below. |

**Example — disable tools you don't use:**

```jsonc
{
  "disabled_tools": ["search_columns", "get_symbol_diff", "suggest_queries"]
}
```

### Descriptions

Customize tool descriptions to reduce schema tokens or tailor to your workflow. Two formats are supported:

**Flat format** — override the tool description only:

```jsonc
{
  "descriptions": {
    "search_symbols": "Find code symbols in this Python project",
    "get_file_tree": "Browse the directory structure"
  }
}
```

**Nested format** — override tool description and/or individual parameter descriptions:

```jsonc
{
  "descriptions": {
    "search_symbols": {
      "_tool": "Find code symbols",
      "query": "Symbol name to search for",
      "language": "Filter by language"
    },
    // _shared applies to all tools that have these parameters
    "_shared": {
      "repo": "Repository name from list_repos"
    }
  }
}
```

- `"_tool"` overrides the tool-level description
- Named keys override individual parameter descriptions
- `"_shared"` applies parameter overrides across all tools (tool-specific overrides take precedence)
- Empty string `""` clears a description (useful for removing verbose defaults)

### Meta response control

Controls the `_meta` envelope included in tool responses. Reducing meta fields saves tokens per call.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `meta_fields` | list or null | `[]` | `[]` (default, token-lean) = strip `_meta` entirely. `null` = include all fields. List = include only named fields. |

**Example — keep only timing and savings:**

```jsonc
{
  "meta_fields": ["timing_ms", "tokens_saved"]
}
```

**Example — strip all meta (maximum token savings):**

```jsonc
{
  "meta_fields": []
}
```

Available meta fields: `timing_ms`, `tokens_saved`, `total_tokens_saved`, `files_searched`, `truncated`, `candidates_scored`.

The legacy `suppress_meta` per-call parameter still works for backward compatibility.

### Transport

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `transport` | str | `"stdio"` | Transport mode: `"stdio"`, `"sse"`, or `"streamable-http"`. |
| `host` | str | `"127.0.0.1"` | Bind address for HTTP transports. |
| `port` | int | `8901` | Port for HTTP transports. |
| `rate_limit` | int | `0` | Max requests per minute per client IP in HTTP mode. `0` = disabled. |

### Watcher

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `watch` | bool | `false` | Enable built-in file watcher alongside the MCP server. |
| `watch_debounce_ms` | int | `2000` | Debounce interval for file change events (ms). |
| `watch_extra_ignore` | list | `[]` | Additional gitignore-style patterns to exclude from watching. |
| `watch_follow_symlinks` | bool | `false` | Include symlinked files in watcher indexing. |
| `watch_idle_timeout` | int or null | `null` | Auto-stop watcher after N minutes with no re-indexing. `null` = disabled. |
| `watch_log` | str or null | `null` | Log watcher output to file. `"auto"` = temp file. `null` = quiet. |
| `watch_paths` | list | `[]` | Folder(s) to watch. Empty = current working directory. |
| `freshness_mode` | str | `"relaxed"` | `"relaxed"` = serve immediately. `"strict"` = wait for fresh results (500ms timeout). |
| `claude_poll_interval` | float | `5.0` | Poll interval (seconds) for Claude Code worktree discovery. |

### Logging

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `log_level` | str | `"WARNING"` | Python log level: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`. |
| `log_file` | str or null | `null` | Path to log file. `null` = stderr only. |

### Privacy and telemetry

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `redact_source_root` | bool | `false` | Replace absolute source paths with display names in responses. |
| `stats_file_interval` | int | `3` | Calls between `session_stats.json` writes. `0` = disable (reduces NVMe writes). |
| `share_savings` | bool | `true` | Send anonymous token savings telemetry to the community counter. |

### Semantic search

Semantic/embedding search is opt-in and requires no config file changes — it is activated entirely through environment variables. All embedding provider vars remain env-var-only (see [Not in config](#not-in-config) below).

**Provider priority** (first match wins):

1. Local `sentence-transformers` — set `JCODEMUNCH_EMBED_MODEL=all-MiniLM-L6-v2`. Install: `pip install jcodemunch-mcp[semantic]`. Free, ~25MB, CPU-only.
2. OpenAI — set `OPENAI_API_KEY` **and** `OPENAI_EMBED_MODEL` (e.g. `text-embedding-3-small`). Per-token cost.
3. Gemini — set `GOOGLE_API_KEY` **and** `GOOGLE_EMBED_MODEL` (e.g. `models/text-embedding-004`). Per-token cost.

When no provider is configured, `search_symbols(semantic=true)` returns a structured error (`error: "no_embedding_provider"`) rather than crashing.

Embeddings are stored in the per-repo SQLite database (`symbol_embeddings` table). They persist across restarts and are invalidated only for changed symbols on incremental reindex.

### Session awareness

Controls the session-aware routing features (plan_turn, session journal, turn budget).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `session_journal` | bool | `true` | Enable session journal (tracks reads, searches, edits, tool calls). |
| `turn_budget_tokens` | int | `20000` | Token budget per turn. Injects `budget_warning` when exceeded. `0` = disabled. |
| `turn_gap_seconds` | float | `30.0` | Seconds of inactivity before starting a new turn budget cycle. |
| `negative_evidence_threshold` | float | `0.5` | BM25 score threshold below which results are flagged as negative evidence. |
| `search_result_cache_max` | int | `128` | Max entries in the LRU search result cache. |
| `plan_turn_high_threshold` | float | `2.0` | BM25 score threshold for "high" confidence in `plan_turn`. |
| `plan_turn_medium_threshold` | float | `0.5` | BM25 score threshold for "medium" confidence in `plan_turn`. |
| `session_resume` | bool | `false` | Opt-in: persist session state across restarts via atexit save/restore. |
| `session_max_age_minutes` | int | `30` | Max age of a persisted session before it's considered stale. |
| `session_max_queries` | int | `50` | Max queries in a persisted session before rotation. |
| `discovery_hint` | bool | `true` | Show discovery hints in tool responses for first-time users. |

### Agent Selector

Opt-in complexity-based model routing. Off by default — zero behavioral change.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `agent_selector` | dict | `{}` | Agent selector configuration block. See below for sub-keys. |

**Sub-keys within `agent_selector`:**

| Sub-key | Type | Default | Description |
|---------|------|---------|-------------|
| `mode` | str | `"off"` | `"off"` (disabled), `"manual"` (advisory prompts), or `"auto"` (automatic routing). |
| `activeProvider` | str | `"anthropic"` | Which provider's batting order to use. Must match a key in `providers` or a built-in default. |
| `providers` | dict | (built-in) | Custom model tiers per provider. Format: `{"anthropic": {"low": "...", "medium": "...", "high": "..."}}`. |
| `thresholds` | dict | `{"lowCeiling": 25, "highFloor": 70}` | Complexity score boundaries for tier assignment (0-100 scale). |
| `verbosePrompts` | bool | `false` | In manual mode, also prompt on step-down opportunities (not just step-up). |

**Example:**

```jsonc
{
  "agent_selector": {
    "mode": "manual",
    "activeProvider": "anthropic",
    "verbosePrompts": false
  }
}
```

Built-in default batting orders: Anthropic (`haiku` / `sonnet` / `opus`), OpenAI (`gpt-4o-mini` / `gpt-4o` / `o3`), Google (`flash` / `pro` / `pro`).

### Freshness

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `strict_timeout_ms` | int | `500` | In `freshness_mode: "strict"`, max ms to wait for an in-progress reindex before serving. |

### Path remapping

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `path_map` | str | `""` | Cross-platform path prefix remapping. Format: `orig1=new1,orig2=new2`. |

**Example — index on Linux, query from Windows (WSL):**

```jsonc
{
  "path_map": "/home/user/project=D:\\Users\\user\\project"
}
```

## Project-level overrides

Place a `.jcodemunch.jsonc` file in your project root. It merges over the global config for that repo only.

```jsonc
// .jcodemunch.jsonc — committed to version control
{
  "languages": ["python"],
  "max_folder_files": 5000,
  "extra_ignore_patterns": ["*.generated.py", "migrations/"],
  "disabled_tools": ["search_columns"],
  "meta_fields": ["timing_ms", "tokens_saved"]
}
```

Project config is loaded automatically when a repo is indexed. It uses hash-based caching — the file is only re-parsed when its content changes, not on every watcher cycle.

## Migrating from environment variables

Every `JCODEMUNCH_*` env var maps to a config key:

| Environment variable | Config key |
|---------------------|------------|
| `JCODEMUNCH_USE_AI_SUMMARIES` | `use_ai_summaries` |
| `JCODEMUNCH_MAX_FOLDER_FILES` | `max_folder_files` |
| `JCODEMUNCH_MAX_INDEX_FILES` | `max_index_files` |
| `JCODEMUNCH_STALENESS_DAYS` | `staleness_days` |
| `JCODEMUNCH_MAX_RESULTS` | `max_results` |
| `JCODEMUNCH_EXTRA_IGNORE_PATTERNS` | `extra_ignore_patterns` |
| `JCODEMUNCH_EXTRA_EXTENSIONS` | `extra_extensions` |
| `JCODEMUNCH_CONTEXT_PROVIDERS` | `context_providers` |
| `JCODEMUNCH_REDACT_SOURCE_ROOT` | `redact_source_root` |
| `JCODEMUNCH_STATS_FILE_INTERVAL` | `stats_file_interval` |
| `JCODEMUNCH_SHARE_SAVINGS` | `share_savings` |
| `JCODEMUNCH_SUMMARIZER_CONCURRENCY` | `summarizer_concurrency` |
| `JCODEMUNCH_ALLOW_REMOTE_SUMMARIZER` | `allow_remote_summarizer` |
| `JCODEMUNCH_RATE_LIMIT` | `rate_limit` |
| `JCODEMUNCH_TRANSPORT` | `transport` |
| `JCODEMUNCH_HOST` | `host` |
| `JCODEMUNCH_PORT` | `port` |
| `JCODEMUNCH_WATCH` | `watch` |
| `JCODEMUNCH_WATCH_DEBOUNCE_MS` | `watch_debounce_ms` |
| `JCODEMUNCH_FRESHNESS_MODE` | `freshness_mode` |
| `JCODEMUNCH_CLAUDE_POLL_INTERVAL` | `claude_poll_interval` |
| `JCODEMUNCH_LOG_LEVEL` | `log_level` |
| `JCODEMUNCH_LOG_FILE` | `log_file` |
| `JCODEMUNCH_PATH_MAP` | `path_map` |

**Migration steps:**

1. Run `jcodemunch-mcp config` to see your current effective configuration
2. Run `jcodemunch-mcp config --init` to create a template
3. Move env var values into the config file
4. Remove the env vars from your shell profile
5. Verify with `jcodemunch-mcp config` — source column should show "config" instead of "env"

Env vars continue to work as fallback (they fill in keys not set in the config file) and emit a one-time deprecation warning per variable. They will be removed in v2.0.

## Not in config

These environment variables are **not** config keys and remain env-var only:

| Variable | Reason |
|----------|--------|
| `CODE_INDEX_PATH` | Determines where the config file itself lives (circular dependency) |
| `ANTHROPIC_API_KEY` | Secret — should not be in config files |
| `GOOGLE_API_KEY` | Secret |
| `OPENAI_API_KEY` / `OPENAI_API_BASE` | Secret / endpoint |
| `GITHUB_TOKEN` | Secret |
| `ANTHROPIC_MODEL` / `GOOGLE_MODEL` / `OPENAI_MODEL` | AI model selection — rarely changed, provider-specific |
| `OPENAI_TIMEOUT` / `OPENAI_BATCH_SIZE` / `OPENAI_MAX_TOKENS` / `OPENAI_CONCURRENCY` | Local LLM tuning — see [USER_GUIDE.md](USER_GUIDE.md#11-local-llm-tuning-for-summaries) |
| `JCODEMUNCH_EMBED_MODEL` | Semantic search — selects local `sentence-transformers` model (e.g. `all-MiniLM-L6-v2`). Install dep: `pip install jcodemunch-mcp[semantic]` |
| `OPENAI_EMBED_MODEL` | Semantic search — activates OpenAI embedding provider (requires `OPENAI_API_KEY`). Example: `text-embedding-3-small` |
| `GOOGLE_EMBED_MODEL` | Semantic search — activates Gemini embedding provider (requires `GOOGLE_API_KEY`). Example: `models/text-embedding-004` |
