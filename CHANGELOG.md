# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2025-02-25

### Added
- Tree-sitter AST-based symbol indexing for polyglot codebases
- Token-efficient MCP server exposing code navigation tools to AI agents
- O(1) byte-offset seeking for fast full-source retrieval
- Persistent symbol cache with incremental re-indexing
- Security layer and configurable path policies (`SECURITY.md`)
- Comprehensive language support via `tree-sitter-language-pack`
- Benchmarks showing up to 99 % token-cost reduction vs. file-dumping approaches
- `munch_index` – index a codebase and build the symbol cache
- `munch_search` – search symbols by name/type across the index
- `munch_get` – retrieve full source of a specific symbol by byte offset
- `munch_summarize` – return AI-generated one-line summaries for symbols
- `munch_outline` – produce a structural outline of a file or module
- User guide, architecture doc, spec, and token-savings comparison docs
