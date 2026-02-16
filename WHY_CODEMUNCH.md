# The Documentation Dilemma: Why We Built Two MCP Servers

## The Problem AI Assistants Face

When you ask an AI assistant to help with a codebase, it hits a wall immediately. The assistant has two fundamental questions:

1. **"What does this project *do*?"** — Understanding purpose, architecture, and design decisions
2. **"How does this code *work*?"** — Understanding implementation, APIs, and execution flow

The naive approach dumps entire files into context. A 10,000-line codebase consumes ~40,000 tokens just to read. Most of those tokens are implementation details the assistant never needs. This is expensive, slow, and cognitively overwhelming.

We built two MCP servers to solve this — one for each question.

---

## jdocmunch-mcp: Answering "What does this project do?"

**Purpose**: Understand documentation, READMEs, architecture guides, and design decisions.

When you land in an unfamiliar repository, you don't start by reading `src/utils/helpers.py`. You read the README. You check the docs folder. You look for architecture decisions and API guides.

**jdocmunch-mcp** indexes Markdown documentation using section-based parsing. It breaks docs into logical sections (H1–H6 headings) with summaries, creating a searchable, navigable map of the project's *intent*.

**Best for**:

* Understanding project purpose and getting started
* Learning architecture and design patterns
* Finding configuration and deployment guides
* Reviewing changelogs and contribution guidelines

**Token efficiency**: ~95% savings vs dumping all Markdown files

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

## Side-by-Side: The Complementary Workflow

| Scenario                  | jdocmunch-mcp                             | jcodemunch-mcp                                  |
| ------------------------- | ----------------------------------------- | ----------------------------------------------- |
| **New to a project**      | Read README, architecture docs            | —                                               |
| **Need to add a feature** | Check contributing guide, design patterns | Find relevant functions, understand APIs        |
| **Debugging an issue**    | Check troubleshooting, known issues       | Search for error-handling code, trace execution |
| **Code review**           | Verify against design principles          | Review specific implementation changes          |
| **API integration**       | Read API documentation                    | Find client classes, method signatures          |

**The workflow**: Start with **jdocmunch-mcp** to understand *what* and *why*. Switch to **jcodemunch-mcp** to understand *how*. They are not competitors — they are sequential tools in the exploration pipeline.

---

## The Unified Vision: Token-Efficient Code Intelligence

Both servers share the same philosophy:

1. **Pre-index once, query many times** — Parse the expensive parts (Markdown sections, AST trees) upfront
2. **Structured over raw** — Return metadata and summaries by default, source on demand
3. **Searchable and navigable** — Find what you need without scrolling through noise
4. **Byte-offset precision** — Retrieve exactly the bytes you need, nothing more

Together, they solve the fundamental problem of AI-assisted code exploration: **cognitive load**. An AI assistant with these tools does not drown in context windows — it navigates purposefully.

---

## Why This Matters

Without these tools, every code query is expensive:

* ~40,000 tokens to understand a medium-sized repo
* ~$0.12 per query at Claude Haiku rates
* Slow response times as the assistant processes noise
* High cognitive load as the assistant struggles to find relevance

With these tools:

* ~500–2,000 tokens for most queries
* ~$0.0015–0.006 per query
* Fast, targeted responses
* Clear execution path from question to answer

For a developer making 50 code queries per day, that is the difference between **$6/day** and **$0.30/day** — or **$180/month** vs **$9/month**.

But the real savings is not monetary. It is **attention** — the ability to ask a question and get a precise answer without wading through boilerplate, imports, and comments.

---

## The Future: Composability

These MCP servers are not endpoints — they are building blocks. They demonstrate a pattern:

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

Both servers are open source and ready to use:

* **jdocmunch-mcp**: [https://github.com/jgravelle/jdocmunch-mcp](https://github.com/jgravelle/jdocmunch-mcp)
* **jcodemunch-mcp**: [https://github.com/jgravelle/jcodemunch-mcp](https://github.com/jgravelle/jcodemunch-mcp)

Install them, configure your MCP client, and start exploring codebases the way they were meant to be explored — intelligently, efficiently, and with purpose.

The age of dumping entire files into context windows is over. The age of structured code intelligence has begun.
