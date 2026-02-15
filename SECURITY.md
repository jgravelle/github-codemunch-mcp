# Security Controls

jcodemunch-mcp indexes source code from local folders and GitHub repositories. This document describes the security controls that protect against common risks when handling arbitrary codebases.

## Path Traversal Prevention

All user-supplied paths are validated before any file is read or written.

- **`validate_path(root, target)`** resolves both paths to absolute form and verifies the target is a descendant of root using `os.path.commonpath()`.
- Applied in `index_folder` during file discovery and again before each file read (defense in depth).
- Paths like `../../etc/passwd` or absolute paths outside the repo root are rejected.

## Symlink Escape Protection

Symlinks can be used to escape the repo root and read arbitrary files.

- **Default:** `follow_symlinks=False` — all symlinks are skipped during file discovery.
- When symlinks are followed (`follow_symlinks=True`), each symlink target is resolved and validated against the repo root. Escaping symlinks are skipped with a warning.
- **`is_symlink_escape(root, path)`** checks whether a symlink resolves outside root.
- On Windows, symlink tests are skipped (symlinks require elevated privileges).

## Default Ignore Policy

Files are filtered through multiple layers:

1. **SKIP_PATTERNS** — directories and files always excluded: `node_modules/`, `vendor/`, `.git/`, `build/`, `dist/`, `generated/`, minified files, lock files, etc.
2. **`.gitignore`** — respected by default for both local folders and GitHub repos (via `pathspec` library).
3. **`extra_ignore_patterns`** — user-configurable additional gitignore-style patterns passed to `index_folder`.

## Secret Exclusion

Files matching known secret patterns are excluded by default during indexing.

**Excluded patterns:**
- Environment files: `.env`, `.env.*`, `*.env`
- Certificates/keys: `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.keystore`, `*.jks`
- SSH keys: `id_rsa`, `id_ed25519`, `id_dsa`, `id_ecdsa` (and `.pub` variants)
- Credentials: `credentials.json`, `service-account*.json`, `*.credentials`
- Auth files: `.htpasswd`, `.netrc`, `.npmrc`, `.pypirc`
- Generic: `*secret*`, `*.secrets`, `*.token`

When a secret file is detected during indexing, a warning is included in the response. Secret files are never stored in the index or raw content directory.

## File Size Limits

- **Default maximum:** 500KB per file (configurable via `max_file_size`).
- Files exceeding the limit are silently skipped during discovery.
- The file count limit (default 500 files) prevents runaway indexing of large monorepos.

## Binary File Detection

Binary files are excluded using a two-layer check:

1. **Extension-based** — a comprehensive list of known binary extensions: `.exe`, `.dll`, `.so`, `.png`, `.jpg`, `.zip`, `.wasm`, `.pyc`, `.class`, `.pdf`, `.db`, `.sqlite`, etc.
2. **Content-based** — if a file has a source code extension but contains null bytes in the first 8KB, it is treated as binary and skipped.

## Encoding Safety

- All file reads use `errors="replace"` to substitute invalid UTF-8 bytes with the Unicode replacement character (U+FFFD) instead of crashing.
- Symbol content retrieval (`get_symbol_content`) also uses `errors="replace"` for safe decoding.
- Files are stored as UTF-8 in the raw content directory.

## Storage Safety

- Index storage defaults to `~/.code-index/` (user home directory).
- The storage path can be overridden via the `CODE_INDEX_PATH` environment variable.
- Repository identifiers are derived from `{owner}-{name}`, preventing path injection in storage paths.
- Index files are JSON with standard encoding; schema validation is applied on load.

## Summary of Controls

| Control | Location | Default |
|---------|----------|---------|
| Path traversal validation | `security.validate_path()` | Always on |
| Symlink escape protection | `security.is_symlink_escape()` | Symlinks skipped by default |
| Secret file exclusion | `security.is_secret_file()` | Always on |
| Binary file detection | `security.is_binary_file()` | Always on |
| File size limit | `discover_local_files()` | 500KB |
| File count limit | `discover_local_files()` | 500 files |
| .gitignore respect | `index_folder`, `index_repo` | Always on |
| UTF-8 safe decode | All file reads and retrievals | `errors="replace"` |
