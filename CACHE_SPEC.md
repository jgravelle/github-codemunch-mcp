# Cache & Invalidation Specification

## Storage Layout

```
~/.code-index/                    (or CODE_INDEX_PATH)
├── {owner}-{name}.json           Index metadata + symbols
├── {owner}-{name}.json.tmp       Temporary file during atomic writes
└── {owner}-{name}/               Raw file content directory
    ├── src/
    │   └── main.py
    └── tests/
        └── test_main.py
```

## Cache Keys

Each repository is identified by `{owner}-{name}`:
- GitHub repos: owner and repo name from the URL (e.g., `pydantic-monty`)
- Local folders: `local-{folder_name}` (e.g., `local-myproject`)

## Index Schema

```json
{
  "repo": "owner/name",
  "owner": "owner",
  "name": "name",
  "indexed_at": "2025-01-15T10:30:00",
  "index_version": 2,
  "git_head": "abc123...",
  "file_hashes": {
    "src/main.py": "sha256hex...",
    "src/utils.py": "sha256hex..."
  },
  "source_files": ["src/main.py", "src/utils.py"],
  "languages": {"python": 2},
  "symbols": [...]
}
```

## Index Versioning

- `index_version` is stored in every index JSON.
- Current version: **2** (defined in `INDEX_VERSION` constant).
- On load, if `stored_version > INDEX_VERSION`, the index is rejected (returns None).
- Older versions (v1) are loaded with missing fields defaulting to empty values.
- Bump `INDEX_VERSION` when making breaking schema changes.

## File Hash Change Detection

Each indexed file's SHA-256 hash is stored in `file_hashes`.

On re-index with `incremental=True`:
1. Read current file contents and compute hashes.
2. Compare against stored `file_hashes`.
3. Classify files as: **changed** (hash differs), **new** (not in old index), **deleted** (in old index but not on disk).

## Incremental Indexing

When `incremental=True` and an existing index is found:

1. **Detect changes** via `IndexStore.detect_changes()`.
2. **Re-parse only** changed and new files.
3. **Remove symbols** for deleted and changed files from existing index.
4. **Merge** new symbols into the remaining symbol list.
5. **Update** file hashes, source files list, and languages.
6. **Save atomically** via temp file + rename.

If no existing index exists, falls back to full index.

## Git Branch Switching

For git repositories (local folders):
- `git_head` stores the HEAD commit hash at index time.
- On re-index, if HEAD changed, a full reindex is triggered (or diff-based if incremental).
- `_get_git_head()` runs `git rev-parse HEAD` with a 5-second timeout.

## Invalidation

### Manual Invalidation
- **`invalidate_cache(repo)`** MCP tool: deletes index JSON and raw content directory.
- **`delete_index(owner, name)`** on IndexStore: same effect programmatically.

### Automatic Invalidation
- Re-indexing the same repo overwrites the existing index.
- Index version mismatch causes the old index to be ignored.

## Atomic Writes

Index JSON is written via a two-step process:
1. Write to `{owner}-{name}.json.tmp`
2. Rename (replace) to `{owner}-{name}.json`

This prevents corrupted index files from partial writes or crashes.

## Hash Strategy

- **File hashes:** SHA-256 of UTF-8 encoded file content string.
- **Symbol content hashes:** SHA-256 of raw symbol source bytes (stored per-symbol for drift detection).
- All hashes are hex-encoded strings.
