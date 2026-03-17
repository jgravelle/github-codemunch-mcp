# jCodeMunch Quick Start

Get from zero to 95% token savings in three steps.

---

## Step 1 — Install

```bash
pip install jcodemunch-mcp
```

> **Recommended alternative:** use `uvx` instead of `pip install`. It resolves the package on demand and avoids PATH issues where MCP clients can't find the executable.

---

## Step 2 — Add to your MCP client

### Claude Code (one command)

```bash
claude mcp add jcodemunch uvx jcodemunch-mcp
```

Restart Claude Code. Confirm with `/mcp` — you should see `jcodemunch` listed as connected.

### Claude Desktop

Edit the config file for your OS:

| OS      | Path |
|---------|------|
| macOS   | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux   | `~/.config/claude/claude_desktop_config.json` |

Add the `jcodemunch` entry:

```json
{
  "mcpServers": {
    "jcodemunch": {
      "command": "uvx",
      "args": ["jcodemunch-mcp"]
    }
  }
}
```

Restart Claude Desktop.

### Other clients (Cursor, Windsurf, Roo, etc.)

Any MCP-compatible client accepts the same JSON block above in its MCP config file.

---

## Step 3 — Tell Claude to use it

**This step is the most commonly missed.** Installing the server makes the tools
*available* — but Claude defaults to its built-in file tools (Read, Grep, Glob) and
will never touch jCodeMunch without explicit instructions.

Create or edit `~/.claude/CLAUDE.md` (global — applies to every project):

```markdown
## Code Exploration Policy
Always use jCodemunch-MCP tools — never fall back to Read, Grep, Glob, or Bash for code exploration.
- Before reading a file: use get_file_outline or get_file_content
- Before searching: use search_symbols or search_text
- Before exploring structure: use get_file_tree or get_repo_outline
- Call list_repos first; if the project is not indexed, call index_folder with the current directory.
```

You can also add the same block to a project-level `CLAUDE.md` in your repo root.

---

## First use

1. Open a project in Claude Code (or Claude Desktop).
2. Ask: *"Index this project"* — Claude will call `index_folder` on the current directory.
3. Ask: *"Find the authenticate function"* — Claude calls `search_symbols`, then `get_symbol`. No file reads.

**Verify it's working:** ask *"What repos do you have indexed?"* — Claude should call `list_repos` without touching any files.

---

## Quick cheat sheet

| Goal | Tool |
|------|------|
| Index a local project | `index_folder { "path": "/your/project" }` |
| Index a GitHub repo | `index_repo { "url": "owner/repo" }` |
| Find a function by name | `search_symbols { "repo": "...", "query": "funcName" }` |
| Read a specific function | `get_symbol { "repo": "...", "symbol_id": "..." }` |
| See all files + structure | `get_repo_outline { "repo": "..." }` |
| See a file's symbols | `get_file_outline { "repo": "...", "file_path": "..." }` |
| Full-text search | `search_text { "repo": "...", "query": "TODO" }` |
| Find what imports a file | `find_importers { "repo": "...", "file_path": "..." }` |
| Find all references to a name | `find_references { "repo": "...", "identifier": "..." }` |

---

## Troubleshooting

**Claude isn't calling jCodeMunch tools**
→ Check that `CLAUDE.md` exists and contains the Code Exploration Policy above.
→ Run `/mcp` in Claude Code to confirm the server is connected.

**`jcodemunch-mcp` not found**
→ Use `uvx jcodemunch-mcp` in your config instead of the bare command name — it bypasses PATH entirely.

**30% more tokens than without it**
→ The agent is using jCodeMunch *in addition to* native file tools, not *instead of* them. The `CLAUDE.md` policy in Step 3 is the fix.

**Index seems stale**
→ Re-run `index_folder` with `incremental: false` to force a full rebuild, or call `invalidate_cache`.

---

For the full reference — all env vars, AI summaries, HTTP transport, dbt/SQL support, and more — see [README.md](README.md).
