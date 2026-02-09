
# jCodeMunch MCP
### Precision Code Intelligence for the Agent Era

![Build](https://img.shields.io/badge/build-passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)
![MCP](https://img.shields.io/badge/MCP-compatible-purple)
![Python](https://img.shields.io/badge/python-3.10%2B-yellow)

**Stop loading files. Start navigating symbols.**

jCodeMunch MCP converts any local repository into a semantic navigation engine that AI agents can query with surgical precision. Designed specifically for the MCP / OpenClaw / Claude Desktop ecosystem, it enables autonomous agents to explore large codebases efficiently, reducing token consumption and dramatically improving reasoning quality.

---

## Why Agents Need This

Modern AI agents waste tokens brute‑forcing file reads. jCodeMunch changes the paradigm:

- Symbol‑first discovery instead of file scanning
- Deterministic structural retrieval
- Massive context cost reduction
- Near‑instant semantic navigation
- Local‑first indexing — no vendor lock‑in

Agents don’t need more context.  
They need **better context access**.

---

## Architecture Overview

![Architecture Diagram](docs/architecture.png)

**Pipeline**

1. Parse source with structural parsers
2. Extract symbols and metadata
3. Build persistent local index
4. Serve MCP tools for discovery
5. Retrieve exact source fragments via byte‑offset precision

---

## Quickstart

```bash
git clone https://github.com/jgravelle/jcodemunch-mcp
cd jcodemunch-mcp
pip install -r requirements.txt
```

Configure your MCP client to launch the server and point it to your local repository.

---

## Quickstart Demo

![Quickstart Demo](docs/demo.gif)

See how an agent searches, discovers, and retrieves implementations in seconds using structured queries.

---

## Benchmarks

![Benchmark](docs/benchmark.png)

| Workflow | Tokens |
|----------|------|
| Raw file loading | ~3600 |
| jCodeMunch retrieval | ~689 |

Typical discovery tasks show **~5× token efficiency improvement** and significantly lower latency.

---

## Tool Suite

| Tool | Purpose |
|------|------|
| `index_repo` | Index a repository |
| `search_symbols` | Discover symbols |
| `get_file_outline` | Retrieve file structure |
| `get_symbol` | Fetch exact implementation |

---

## Ecosystem Integration

Designed for:

- Claude Desktop MCP servers
- OpenClaw agent orchestration
- Autonomous engineering pipelines
- Multi‑agent development systems

jCodeMunch provides the **semantic navigation layer** agents need to operate reliably at scale.

---

## Vision

Parse once.  
Retrieve precisely.  
Reason structurally.

jCodeMunch is building the foundational intelligence layer for the next generation of AI‑driven software engineering.

---

## License
MIT
