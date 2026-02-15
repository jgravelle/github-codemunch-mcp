# Architecture

## Directory Structure

```
jcodemunch-mcp/
├── pyproject.toml
├── README.md
├── SECURITY.md
├── SYMBOL_SPEC.md
├── CACHE_SPEC.md
├── LANGUAGE_SUPPORT.md
│
├── src/jcodemunch_mcp/
│   ├── __init__.py
│   ├── server.py                    # MCP server: 11 tool definitions + dispatch
│   ├── security.py                  # Path traversal, symlink, secret, binary detection
│   │
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── symbols.py              # Symbol dataclass, make_symbol_id(), compute_content_hash()
│   │   ├── extractor.py            # parse_file(): tree-sitter AST walking + symbol extraction
│   │   ├── languages.py            # LanguageSpec registry for 6 languages
│   │   └── hierarchy.py            # SymbolNode tree building for file outlines
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   └── index_store.py          # CodeIndex, IndexStore: save/load, incremental, byte-offset reads
│   │
│   ├── summarizer/
│   │   ├── __init__.py
│   │   └── batch_summarize.py      # Three-tier: docstring > AI (Haiku) > signature fallback
│   │
│   └── tools/
│       ├── __init__.py
│       ├── index_repo.py           # GitHub repo indexing (async, git/trees API)
│       ├── index_folder.py         # Local folder indexing (sync, .gitignore, security)
│       ├── list_repos.py
│       ├── get_file_tree.py
│       ├── get_file_outline.py
│       ├── get_symbol.py           # get_symbol + get_symbols (verify, context_lines)
│       ├── search_symbols.py       # Weighted scoring search (kind, language, file_pattern)
│       ├── search_text.py          # Full-text search across file contents
│       ├── get_repo_outline.py     # High-level repo overview
│       └── invalidate_cache.py     # Delete index + cached files
│
├── tests/
│   ├── fixtures/                   # Per-language test fixtures (Python, JS, TS, Go, Rust, Java)
│   ├── test_parser.py
│   ├── test_languages.py
│   ├── test_storage.py
│   ├── test_summarizer.py
│   ├── test_tools.py
│   ├── test_server.py
│   ├── test_security.py            # 73 tests: path traversal, symlinks, secrets, binary, encoding
│   └── test_hardening.py           # 51 tests: per-language extraction, determinism, incremental
│
├── benchmarks/
│   └── run_benchmarks.py           # Index/search/retrieval benchmarks with Markdown+JSON output
│
└── .github/workflows/
    ├── test.yml                    # pytest on push/PR (Python 3.10/3.11/3.12)
    └── benchmark.yml               # Benchmarks on demand/release
```

## Data Flow

```
Source code (GitHub API or local folder)
    │
    ▼
Security filters (path traversal, symlinks, secrets, binary, size)
    │
    ▼
tree-sitter parse (language-specific grammar via LanguageSpec)
    │
    ▼
Symbol extraction (functions, classes, methods, constants, types)
    │
    ▼
Post-processing (overload disambiguation, content hashing)
    │
    ▼
Summarization (docstring → AI batch → signature fallback)
    │
    ▼
Storage (JSON index + raw files, atomic writes)
    │
    ▼
MCP tools (11 tools for discovery, search, retrieval)
```

## Parser Design

The parser uses a **language registry** pattern. Each language defines a `LanguageSpec` that tells the generic extractor which AST node types to look for and how to extract names, signatures, docstrings, and decorators.

```python
@dataclass
class LanguageSpec:
    ts_language: str                    # tree-sitter grammar name
    symbol_node_types: dict[str, str]   # node_type → symbol kind
    name_fields: dict[str, str]         # node_type → field name for symbol name
    param_fields: dict[str, str]        # node_type → field name for parameters
    return_type_fields: dict[str, str]  # node_type → field name for return type
    docstring_strategy: str             # "next_sibling_string" or "preceding_comment"
    decorator_node_type: str | None     # e.g., "decorator" for Python
    container_node_types: list[str]     # nesting containers (classes for methods)
    constant_patterns: list[str]        # node types for constants
    type_patterns: list[str]            # node types for type definitions
```

The generic extractor (`parse_file()`) walks the tree-sitter CST using the spec, then runs two post-processing passes:

1. **Overload disambiguation** — duplicate IDs get `~1`, `~2` suffixes
2. **Content hashing** — SHA-256 of each symbol's source bytes for drift detection

## Symbol ID Scheme

```
{file_path}::{qualified_name}#{kind}
```

Examples:
- `src/main.py::UserService.login#method`
- `src/utils.py::authenticate#function`
- `config.py::MAX_RETRIES#constant`

IDs are stable across re-indexing when file path, qualified name, and kind are unchanged. See [SYMBOL_SPEC.md](SYMBOL_SPEC.md) for full details.

## Storage

Indexes are stored at `~/.code-index/` (configurable via `CODE_INDEX_PATH`):

- **`{owner}-{name}.json`** — index metadata, file hashes, symbols (no source content)
- **`{owner}-{name}/`** — raw source files preserving directory structure

Content retrieval is O(1) via byte-offset seeking: each symbol stores `byte_offset` and `byte_length`, enabling a direct `seek() + read()` without re-parsing.

**Incremental indexing** compares SHA-256 file hashes to detect changed/new/deleted files, re-parsing only what changed. Writes are atomic (temp file + rename). See [CACHE_SPEC.md](CACHE_SPEC.md).

## Security

All file operations pass through `security.py`:

- **Path traversal prevention** — `validate_path()` ensures targets stay within repo root
- **Symlink escape protection** — symlinks resolved and validated before reading
- **Secret exclusion** — 25 patterns (`.env`, `*.pem`, `*.key`, etc.) blocked by default
- **Binary detection** — extension-based + null-byte content sniffing
- **Encoding safety** — `errors="replace"` on all file reads

See [SECURITY.md](SECURITY.md).

## Response Envelope

All tool responses include a `_meta` object:

```json
{
  "result": "...",
  "_meta": {
    "timing_ms": 42,
    "repo": "owner/repo",
    "symbol_count": 387,
    "truncated": false
  }
}
```

## Search Algorithm

`search_symbols` uses weighted scoring across 6 tiers:

| Match type | Weight |
|-----------|--------|
| Exact name match | +20 |
| Name substring | +10 |
| Name word overlap | +5 per word |
| Signature match | +8 (full) / +2 (word) |
| Summary match | +5 (full) / +1 (word) |
| Keyword/docstring match | +3 / +1 per word |

Filters (kind, language, file_pattern) are applied before scoring. Results with score 0 are excluded.

## Dependencies

| Package | Purpose |
|---------|---------|
| `mcp>=1.0.0` | MCP server framework |
| `httpx>=0.27.0` | Async HTTP for GitHub API |
| `anthropic>=0.40.0` | AI summarization (optional) |
| `tree-sitter-language-pack>=0.7.0` | Pre-compiled grammars for 6 languages |
| `pathspec>=0.12.0` | .gitignore pattern matching |
