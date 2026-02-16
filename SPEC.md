# Technical Specification

## Overview

**jcodemunch-mcp** pre-indexes repository source code using tree-sitter AST parsing, extracting a structured catalog of every symbol (function, class, method, constant, type). Each symbol stores its **signature + one-line summary**, with full source retrievable on demand via O(1) byte-offset seeking.

### Token Savings

| Scenario                        | Raw dump        | codemunch     | Savings   |
| ------------------------------- | --------------- | ------------- | --------- |
| Explore 500-file repo structure | ~200,000 tokens | ~2,000 tokens | **99%**   |
| Find a specific function        | ~40,000 tokens  | ~200 tokens   | **99.5%** |
| Read one function body          | ~40,000 tokens  | ~500 tokens   | **98.7%** |
| Understand module API           | ~15,000 tokens  | ~800 tokens   | **94.7%** |

---

## MCP Tools (11)

### Indexing Tools

#### `index_repo` — Index a GitHub repository

```json
{
  "url": "owner/repo",
  "use_ai_summaries": true
}
```

Fetches source via `git/trees?recursive=1` (single API call), filters through the security pipeline, parses with tree-sitter, summarizes, and saves the index plus raw files.

#### `index_folder` — Index a local folder

```json
{
  "path": "/path/to/project",
  "extra_ignore_patterns": ["*.generated.*"],
  "follow_symlinks": false
}
```

Walks the local directory with full security controls: path traversal prevention, symlink escape protection, secret detection, binary filtering, and `.gitignore` respect.

#### `invalidate_cache` — Delete index for a repository

```json
{
  "repo": "owner/repo"
}
```

Deletes both the index JSON and raw content directory.

---

### Discovery Tools

#### `list_repos` — List indexed repositories

No input required. Returns all indexed repositories with symbol counts, file counts, languages, and index version.

#### `get_file_tree` — Get file structure

```json
{
  "repo": "owner/repo",
  "path_prefix": "src/"
}
```

Returns a nested directory tree with per-file language and symbol count annotations.

#### `get_file_outline` — Get symbols in a file

```json
{
  "repo": "owner/repo",
  "file_path": "src/main.py"
}
```

Returns a hierarchical symbol tree (classes contain methods) with signatures and summaries. Source code is not included; use `get_symbol` for that.

#### `get_repo_outline` — High-level repository overview

```json
{
  "repo": "owner/repo"
}
```

Returns directory file counts, language breakdown, and symbol kind distribution. Lighter than `get_file_tree`.

---

### Retrieval Tools

#### `get_symbol` — Get full source of a symbol

```json
{
  "repo": "owner/repo",
  "symbol_id": "src/main.py::MyClass.login#method",
  "verify": true,
  "context_lines": 3
}
```

Retrieves source via byte-offset seeking (O(1)). Optional `verify` re-hashes the source and compares it to the stored `content_hash`. Optional `context_lines` includes surrounding lines.

#### `get_symbols` — Batch retrieve multiple symbols

```json
{
  "repo": "owner/repo",
  "symbol_ids": ["id1", "id2", "id3"]
}
```

Returns a list of symbols plus an error list for any IDs not found.

---

### Search Tools

#### `search_symbols` — Search across all symbols

```json
{
  "repo": "owner/repo",
  "query": "authenticate",
  "kind": "function",
  "language": "python",
  "file_pattern": "src/**/*.py",
  "max_results": 10
}
```

Weighted scoring search across name, signature, summary, keywords, and docstring. All filters are optional.

#### `search_text` — Full-text search across file contents

```json
{
  "repo": "owner/repo",
  "query": "TODO",
  "file_pattern": "*.py",
  "max_results": 20
}
```

Case-insensitive substring search across indexed file contents. Returns matching lines with file, line number, and surrounding context. Use when symbol search misses (string literals, comments, config values).

---

## Data Models

### Symbol

```python
@dataclass
class Symbol:
    id: str                  # "{file_path}::{qualified_name}#{kind}"
    file: str                # Relative file path
    name: str                # Symbol name
    qualified_name: str      # Dot-separated with parent context
    kind: str                # function | class | method | constant | type
    language: str            # python | javascript | typescript | go | rust | java
    signature: str           # Full signature line(s)
    content_hash: str = ""   # SHA-256 of source bytes (drift detection)
    docstring: str = ""
    summary: str = ""
    decorators: list[str]    # Decorators/attributes
    keywords: list[str]      # Search keywords
    parent: str | None       # Parent symbol ID (methods → class)
    line: int = 0            # Start line (1-indexed)
    end_line: int = 0        # End line (1-indexed)
    byte_offset: int = 0     # Start byte in raw file
    byte_length: int = 0     # Byte length of source
```

### CodeIndex

```python
@dataclass
class CodeIndex:
    repo: str                        # "owner/repo"
    owner: str
    name: str
    indexed_at: str                  # ISO timestamp
    index_version: int               # Schema version (current: 2)
    source_files: list[str]
    languages: dict[str, int]        # language → file count
    symbols: list[dict]              # Serialized symbols (no source)
    file_hashes: dict[str, str]      # file_path → SHA-256 (for incremental)
    git_head: str                    # HEAD commit hash (for git repos, empty if unavailable)
```

---

## File Discovery

### GitHub Repositories

Single API call:
`GET /repos/{owner}/{repo}/git/trees/HEAD?recursive=1`

### Local Folders

Recursive directory walk with the full security pipeline.

### Filtering Pipeline (Both Paths)

1. **Extension filter** — must be in `LANGUAGE_EXTENSIONS` (.py, .js, .jsx, .ts, .tsx, .go, .rs, .java)
2. **Skip patterns** — `node_modules/`, `vendor/`, `.git/`, `build/`, `dist/`, lock files, minified files, etc.
3. **`.gitignore`** — respected via the `pathspec` library
4. **Secret detection** — `.env`, `*.pem`, `*.key`, `*.p12`, credentials files excluded
5. **Binary detection** — extension-based + null-byte content sniffing
6. **Size limit** — 500 KB per file (configurable)
7. **File count limit** — 500 files max, prioritized: `src/` → `lib/` → `pkg/` → `cmd/` → `internal/` → remainder

---

## Response Envelope

All tools return a `_meta` object with timing and context:

```json
{
  "_meta": {
    "timing_ms": 42,
    "repo": "owner/repo",
    "symbol_count": 387,
    "truncated": false,
    "content_verified": true
  }
}
```

---

## Error Handling

All errors return:

```json
{
  "error": "Human-readable message",
  "_meta": { "timing_ms": 1 }
}
```

| Scenario                          | Behavior                                              |
| --------------------------------- | ----------------------------------------------------- |
| Repository not found (GitHub 404) | Error with message                                    |
| Rate limited (GitHub 403)         | Error with reset time; suggest setting `GITHUB_TOKEN` |
| File fetch fails                  | File skipped; indexing continues                      |
| Parse fails (single file)         | File skipped; indexing continues                      |
| No source files found             | Error message returned                                |
| Symbol ID not found               | Error in response                                     |
| Repository not indexed            | Error suggesting indexing first                       |
| AI summarization fails            | Falls back to docstring or signature                  |
| Index version mismatch            | Old index ignored; full reindex required              |

---

## Environment Variables

| Variable            | Purpose                                                  | Required |
| ------------------- | -------------------------------------------------------- | -------- |
| `GITHUB_TOKEN`      | GitHub API authentication (higher limits, private repos) | No       |
| `ANTHROPIC_API_KEY` | AI summarization via Claude Haiku                        | No       |
| `CODE_INDEX_PATH`   | Custom storage path (default: `~/.code-index/`)          | No       |
