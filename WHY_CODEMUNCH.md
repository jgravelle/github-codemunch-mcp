# Why We Built jcodemunch-mcp

## The Problem AI Assistants Face

When you ask an AI assistant to help with a codebase, it hits a wall immediately. The assistant needs to answer: **"How does this code *work*?"** — understanding implementation, APIs, and execution flow.

The naive approach dumps entire files into context. A 10,000-line codebase consumes ~40,000 tokens just to read. Most of those tokens are implementation details the assistant never needs. This is expensive, slow, and cognitively overwhelming.

We built jcodemunch-mcp to solve this.

---

## jcodemunch-mcp: Answering "How does this code work?"

**Purpose**: Understand source code structure, APIs, and implementation details.

Once you understand *what* the project does, you need to understand *how* it does it. You need to find the `authenticate()` function. You need to see the `DatabaseConnection` class. You need to trace execution flow.

**jcodemunch-mcp** indexes source code using tree-sitter AST parsing. It extracts every symbol — functions, classes, methods, constants — with signatures, docstrings, and byte offsets. You get a structured catalog where you can search by name, browse by file, and retrieve exact source on demand.

**Best for**:

* Finding specific functions and classes
* Understanding module APIs without reading implementation
* Tracing execution flow across files
* Reading implementation details when needed

**Token efficiency**: ~89% savings vs dumping source files

---

## Token-Efficient Code Intelligence

jcodemunch-mcp is built on the following principles:

1. **Pre-index once, query many times** — Parse the expensive parts (AST trees) upfront
2. **Structured over raw** — Return metadata and summaries by default, source on demand
3. **Searchable and navigable** — Find what you need without scrolling through noise
4. **Byte-offset precision** — Retrieve exactly the bytes you need, nothing more

This solves the fundamental problem of AI-assisted code exploration: **cognitive load**. An AI assistant with jcodemunch-mcp does not drown in context windows — it navigates purposefully.

---

## Why This Matters

Without jcodemunch-mcp, every code query is expensive:

* ~40,000 tokens to understand a medium-sized repo
* ~$0.12 per query at Claude Haiku rates
* Slow response times as the assistant processes noise
* High cognitive load as the assistant struggles to find relevance

With jcodemunch-mcp:

* ~500–2,000 tokens for most queries
* ~$0.0015–0.006 per query
* Fast, targeted responses
* Clear execution path from question to answer

For a developer making 50 code queries per day, that is the difference between **$6/day** and **$0.30/day** — or **$180/month** vs **$9/month**.

But the real savings is not monetary. It is **attention** — the ability to ask a question and get a precise answer without wading through boilerplate, imports, and comments.

---

## The Future: Composability

jcodemunch-mcp is not an endpoint — it is a building block. It demonstrates a pattern:

1. **Identify the unit of understanding** (docs = sections, code = symbols)
2. **Parse once, index forever** (Markdown splitter, tree-sitter AST)
3. **Query structured metadata** (search, browse, outline)
4. **Retrieve source on demand** (byte offsets, file ranges)

This pattern applies everywhere:

* Jupyter notebooks (cell-based indexing)
* Configuration files (key-value structured access)
* SQL schemas (table/column metadata)
* API specs (endpoint/request/response structures)

The goal is simple: **Make every codebase AI-navigable at human speed.**

---

## Get Started

jcodemunch-mcp is open source and ready to use:

* **jcodemunch-mcp**: [https://github.com/jgravelle/jcodemunch-mcp](https://github.com/jgravelle/jcodemunch-mcp)

Install it, configure your MCP client, and start exploring codebases the way they were meant to be explored — intelligently, efficiently, and with purpose.

The age of dumping entire files into context windows is over. The age of structured code intelligence has begun.
