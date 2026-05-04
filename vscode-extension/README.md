# jCodeMunch — Auto Reindex on Save (VS Code)

A small VS Code extension that auto-reindexes saved files via the `jcodemunch-mcp` CLI.

## Why

Claude Code's PostToolUse hook handles auto-reindexing in its own ecosystem. VS Code-side MCP clients (GitHub Copilot Chat, Continue, Cline, Roo Code, …) don't fire those hooks — so when you edit a file in the editor and another session queries jCodeMunch, the second session sees a stale index. This extension closes the gap by listening for `onDidSaveTextDocument` and shelling out to `jcodemunch-mcp index-file <path>`.

Two-line summary: **save a file → that one file is re-indexed in the background**, regardless of which MCP client is active.

## Requirements

- VS Code 1.85+
- `jcodemunch-mcp >= 1.81.0` on `PATH` (or override via setting `jcodemunch.indexOnSave.command`)
- A workspace folder that has been indexed at least once (`jcodemunch-mcp index .`)

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `jcodemunch.indexOnSave.enabled` | `true` | Enable/disable auto-reindex |
| `jcodemunch.indexOnSave.command` | `jcodemunch-mcp` | Path to the CLI |
| `jcodemunch.indexOnSave.debounceMs` | `500` | Per-file debounce window |
| `jcodemunch.indexOnSave.exclude` | `[node_modules, .git, dist, build, .venv, venv, __pycache__, *.min.*]` | Glob patterns to skip |

Output appears in the **jCodeMunch** output channel (View → Output → jCodeMunch).

## Install

From the VS Code marketplace:

```
ext install jgravelle.jcodemunch-mcp-vscode
```

Or via the Extensions panel — search for "jCodeMunch".

### Build from source

```bash
cd vscode-extension
npm install
npm run compile
npx @vscode/vsce package
code --install-extension jcodemunch-mcp-vscode-0.1.0.vsix
```

## Issues

File at https://github.com/jgravelle/jcodemunch-mcp/issues — tag `area:vscode`.
