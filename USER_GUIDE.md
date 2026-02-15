# User Guide

## Installation

```bash
pip install jcodemunch-mcp
```

Or from source:
```bash
git clone https://github.com/jcodemunch/jcodemunch-mcp.git
cd jcodemunch-mcp
pip install -e .
```

## Configuration

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jcodemunch": {
      "command": "jcodemunch-mcp",
      "env": {
        "GITHUB_TOKEN": "ghp_xxxxxxxx",
        "ANTHROPIC_API_KEY": "sk-ant-xxxxxxxx"
      }
    }
  }
}
```

Both environment variables are optional — `GITHUB_TOKEN` enables private repos and higher rate limits, `ANTHROPIC_API_KEY` enables AI-generated summaries.

### VS Code

Add to `.vscode/settings.json`:

```json
{
  "mcp.servers": {
    "jcodemunch": {
      "command": "jcodemunch-mcp",
      "env": {
        "GITHUB_TOKEN": "ghp_xxxxxxxx"
      }
    }
  }
}
```

## Workflows

### Explore a New Repository

```
index_repo: { "url": "fastapi/fastapi" }
get_repo_outline: { "repo": "fastapi/fastapi" }
get_file_tree: { "repo": "fastapi/fastapi", "path_prefix": "fastapi" }
get_file_outline: { "repo": "fastapi/fastapi", "file_path": "fastapi/main.py" }
```

### Explore a Local Project

```
index_folder: { "path": "/home/user/myproject" }
get_repo_outline: { "repo": "local/myproject" }
search_symbols: { "repo": "local/myproject", "query": "main" }
```

### Find and Read a Function

```
search_symbols: { "repo": "owner/repo", "query": "authenticate", "kind": "function" }
get_symbol: { "repo": "owner/repo", "symbol_id": "src/auth.py::authenticate#function" }
```

### Understand a Class

```
get_file_outline: { "repo": "owner/repo", "file_path": "src/auth.py" }
get_symbols: {
  "repo": "owner/repo",
  "symbol_ids": [
    "src/auth.py::AuthHandler.login#method",
    "src/auth.py::AuthHandler.logout#method"
  ]
}
```

### Verify Source Hasn't Changed

```
get_symbol: {
  "repo": "owner/repo",
  "symbol_id": "src/main.py::process#function",
  "verify": true
}
```

The response `_meta.content_verified` will be `true` if the source matches the stored hash, `false` if it has drifted.

### Search for Non-Symbol Content

```
search_text: { "repo": "owner/repo", "query": "TODO", "file_pattern": "*.py" }
```

Use `search_text` for string literals, comments, config values, or anything that isn't a symbol name.

### Force Re-index

```
invalidate_cache: { "repo": "owner/repo" }
index_repo: { "url": "owner/repo" }
```

## Tool Reference

| Tool | Purpose | Key Parameters |
|------|---------|---------------|
| `index_repo` | Index GitHub repo | `url`, `use_ai_summaries` |
| `index_folder` | Index local folder | `path`, `extra_ignore_patterns`, `follow_symlinks` |
| `list_repos` | List all indexed repos | — |
| `get_file_tree` | Browse file structure | `repo`, `path_prefix` |
| `get_file_outline` | Symbols in a file | `repo`, `file_path` |
| `get_symbol` | Full source of one symbol | `repo`, `symbol_id`, `verify`, `context_lines` |
| `get_symbols` | Batch retrieve symbols | `repo`, `symbol_ids` |
| `search_symbols` | Search symbols | `repo`, `query`, `kind`, `language`, `file_pattern`, `max_results` |
| `search_text` | Full-text search | `repo`, `query`, `file_pattern`, `max_results` |
| `get_repo_outline` | High-level overview | `repo` |
| `invalidate_cache` | Delete cached index | `repo` |

## Symbol IDs

Symbol IDs follow the format `{file_path}::{qualified_name}#{kind}`:

```
src/main.py::UserService#class
src/main.py::UserService.login#method
src/utils.py::authenticate#function
config.py::MAX_RETRIES#constant
```

IDs are returned by `get_file_outline`, `search_symbols`, and `search_text`. Pass them to `get_symbol` or `get_symbols` to retrieve source code.

## Troubleshooting

**"Repository not found"** — Check the URL format (`owner/repo` or full GitHub URL). For private repos, set `GITHUB_TOKEN`.

**"No source files found"** — The repo may not contain supported language files (.py, .js, .ts, .go, .rs, .java), or files may be in skip patterns.

**Rate limiting** — Set `GITHUB_TOKEN` for 5,000 requests/hour (vs 60 without).

**AI summaries not working** — Set `ANTHROPIC_API_KEY`. Without it, summaries fall back to docstrings or signatures.

**Stale index** — Use `invalidate_cache` followed by `index_repo` or `index_folder` to force a clean re-index.

**Encoding issues** — Files with invalid UTF-8 are handled gracefully with replacement characters.

## Storage

Indexes live at `~/.code-index/` (override with `CODE_INDEX_PATH` env var):

```
~/.code-index/
├── owner-repo.json       # Index metadata + symbols
└── owner-repo/           # Raw source files
    └── src/main.py
```

## Tips

1. **Start with `get_repo_outline`** for a quick lay of the land
2. **Use `get_file_outline`** before reading source — understand the API first
3. **Filter searches** with `kind`, `language`, and `file_pattern` to narrow results
4. **Batch retrieve** related symbols with `get_symbols` instead of multiple `get_symbol` calls
5. **Use `search_text`** when symbol search misses — it searches actual file content
6. **Use `verify: true`** on `get_symbol` to detect source drift since indexing
