## Cut code-reading token costs by up to **99%**

Most AI agents explore repositories the expensive way:
open entire files → skim thousands of irrelevant lines → repeat.

**jCodeMunch indexes a codebase once and lets agents retrieve only the exact symbols they need** — functions, classes, methods, constants — with byte-level precision.

| Task                   | Traditional approach | With jCodeMunch |
| ---------------------- | -------------------- | --------------- |
| Find a function        | ~40,000 tokens       | ~200 tokens     |
| Understand module API  | ~15,000 tokens       | ~800 tokens     |
| Explore repo structure | ~200,000 tokens      | ~2k tokens      |

Index once. Query cheaply forever.  
Precision context beats brute-force context.

---

# jCodeMunch MCP

### Structured retrieval for serious AI agents

![License](https://img.shields.io/badge/license-dual--use-blue)
![MCP](https://img.shields.io/badge/MCP-compatible-purple)
![Local-first](https://img.shields.io/badge/local--first-yes-brightgreen)
![Polyglot](https://img.shields.io/badge/parsing-tree--sitter-9cf)

**Stop dumping files into context windows. Start retrieving exactly what the agent needs.**

jCodeMunch indexes a codebase once using tree-sitter AST parsing, then allows MCP-compatible agents (Claude Desktop, VS Code, and others) to **discover and retrieve code by symbol** instead of brute-reading files.

Every symbol stores:
- Signature
- Kind
- Qualified name
- One-line summary
- Byte offsets into the original file

Full source is retrieved on demand using O(1) byte-offset seeking.

---

## Proof: Token savings in the wild

**Repo:** `geekcomputers/Python`  
**Size:** 338 files, 1,422 symbols indexed  
**Task:** Locate calculator / math implementations  

| Approach          | Tokens | What the agent had to do              |
| ----------------- | -----: | ------------------------------------- |
| Raw file approach | ~7,500 | Open multiple files and scan manually |
| jCodeMunch MCP    | ~1,449 | `search_symbols()` → `get_symbol()`   |

### Result: **~80% fewer tokens** (~5× more efficient)

Cost scales with tokens.  
Latency scales with irrelevant context.  

jCodeMunch turns search into navigation.

---

## Why agents need this

Agents waste money when they:

- Open entire files to find one function
- Re-read the same code repeatedly
- Consume imports, boilerplate, and unrelated helpers

jCodeMunch provides precision context access:

- Search symbols by name, kind, or language
- Outline files without loading full contents
- Retrieve exact symbol implementations only
- Fall back to full-text search when necessary

Agents do not need larger context windows.  
They need structured retrieval.

---

## How it works

1. **Discovery** — GitHub API or local directory walk  
2. **Security filtering** — traversal protection, secret exclusion, binary detection  
3. **Parsing** — tree-sitter AST extraction  
4. **Storage** — JSON index + raw files stored locally (`~/.code-index/`)  
5. **Retrieval** — O(1) byte-offset seeking via stable symbol IDs  

### Stable Symbol IDs

```
{file_path}::{qualified_name}#{kind}
```

Examples:

- `src/main.py::UserService.login#method`
- `src/utils.py::authenticate#function`

IDs remain stable across re-indexing when path, qualified name, and kind are unchanged.

---

## Installation

### Prerequisites

- Python 3.10+
- pip

### Install

```bash
pip install git+https://github.com/jgravelle/jcodemunch-mcp.git
```

Verify:

```bash
jcodemunch-mcp --help
```

---

## Configure MCP Client

### Claude Desktop / Claude Code

macOS / Linux  
`~/.config/claude/claude_desktop_config.json`

Windows  
`%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "jcodemunch": {
      "command": "jcodemunch-mcp",
      "env": {
        "GITHUB_TOKEN": "ghp_...",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

Environment variables are optional:

| Variable            | Purpose                                      |
| ------------------- | -------------------------------------------- |
| `GITHUB_TOKEN`      | Higher GitHub API limits / private access    |
| `ANTHROPIC_API_KEY` | AI-generated symbol summaries                |

---

## Usage Examples

```
index_folder: { "path": "/path/to/project" }
index_repo:   { "url": "owner/repo" }

get_repo_outline: { "repo": "owner/repo" }
get_file_outline: { "repo": "owner/repo", "file_path": "src/main.py" }
search_symbols:   { "repo": "owner/repo", "query": "authenticate" }
get_symbol:       { "repo": "owner/repo", "symbol_id": "src/main.py::MyClass.login#method" }
search_text:      { "repo": "owner/repo", "query": "TODO" }
```

---

## Tools (11)

| Tool               | Purpose                     |
| ------------------ | --------------------------- |
| `index_repo`       | Index a GitHub repository   |
| `index_folder`     | Index a local folder        |
| `list_repos`       | List indexed repositories   |
| `get_file_tree`    | Repository file structure   |
| `get_file_outline` | Symbol hierarchy for a file |
| `get_symbol`       | Retrieve full symbol source |
| `get_symbols`      | Batch retrieve symbols      |
| `search_symbols`   | Search symbols with filters |
| `search_text`      | Full-text search            |
| `get_repo_outline` | High-level repo overview    |
| `invalidate_cache` | Remove cached index         |

All tool responses include a `_meta` envelope with timing and metadata.

---

## Supported Languages

| Language   | Extensions    | Symbol Types                            |
| ---------- | ------------- | --------------------------------------- |
| Python     | `.py`         | function, class, method, constant, type |
| JavaScript | `.js`, `.jsx` | function, class, method, constant       |
| TypeScript | `.ts`, `.tsx` | function, class, method, constant, type |
| Go         | `.go`         | function, method, type, constant        |
| Rust       | `.rs`         | function, type, impl, constant          |
| Java       | `.java`       | method, class, type, constant           |
| PHP        | `.php`        | function, class, method, type, constant |

See LANGUAGE_SUPPORT.md for full semantics.

---

## Security

Built-in protections:

- Path traversal prevention  
- Symlink escape protection  
- Secret file exclusion (`.env`, `*.pem`, etc.)  
- Binary detection  
- Configurable file size limits  

See SECURITY.md for details.

---

## Best Use Cases

- Large multi-module repositories  
- Agent-driven refactors  
- Architecture exploration  
- Faster onboarding  
- Token-efficient multi-agent workflows  

---

## Not Intended For

- LSP diagnostics or completions  
- Editing workflows  
- Real-time file watching  
- Cross-repository global indexing  
- Semantic program analysis  

---

## Environment Variables

| Variable            | Purpose                   | Required |
| ------------------- | ------------------------- | -------- |
| `GITHUB_TOKEN`      | GitHub API auth           | No       |
| `ANTHROPIC_API_KEY` | Symbol summary generation | No       |
| `CODE_INDEX_PATH`   | Custom cache path         | No       |

---

## Documentation

- USER_GUIDE.md  
- ARCHITECTURE.md  
- SPEC.md  
- SECURITY.md  
- SYMBOL_SPEC.md  
- CACHE_SPEC.md  
- LANGUAGE_SUPPORT.md  

---

## Star History

<a href="https://www.star-history.com/#jgravelle/jcodemunch-mcp&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=jgravelle/jcodemunch-mcp&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=jgravelle/jcodemunch-mcp&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=jgravelle/jcodemunch-mcp&type=date&legend=top-left" />
 </picture>
</a>

---

## License (Dual Use)

This repository is **free for non-commercial use** under the terms below.  
**Commercial use requires a paid commercial license.**

---

## Copyright and License Text

Copyright (c) 2026 J. Gravelle

### 1. Non-Commercial License Grant (Free)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to use, copy, modify, merge, publish, and distribute the Software for **personal, educational, research, hobby, or other non-commercial purposes**, subject to the following conditions:

1. The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

2. Any modifications made to the Software must clearly indicate that they are derived from the original work, and the name of the original author (J. Gravelle) must remain intact. He's kinda full of himself.

3. Redistributions of the Software in source code form must include a prominent notice describing any modifications from the original version.

### 2. Commercial Use

Commercial use of the Software requires a separate paid commercial license from the author.

“Commercial use” includes, but is not limited to:

- Use of the Software in a business environment
- Internal use within a for-profit organization
- Incorporation into a product or service offered for sale
- Use in connection with revenue generation, consulting, SaaS, hosting, or fee-based services

For commercial licensing inquiries, contact:  
j@gravelle.us | https://j.gravelle.us

Until a commercial license is obtained, commercial use is not permitted.

### 3. Disclaimer of Warranty

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT.

IN NO EVENT SHALL THE AUTHOR OR COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
