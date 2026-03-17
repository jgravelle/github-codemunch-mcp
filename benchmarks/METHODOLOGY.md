# Benchmark Methodology

This document provides full methodological detail for the token efficiency
benchmarks reported in `results.md` and the project README.

## Scope

The benchmark measures **retrieval token efficiency** — how many LLM input
tokens a code exploration tool consumes compared to reading all source files.
It does **not** measure answer quality, latency, or end-to-end task completion.

## Repositories Under Test

All repositories are public and pinned to their default branches at the time
of indexing. No filtering or cherry-picking of files was applied beyond
jcodemunch's standard skip patterns (node_modules, __pycache__, etc.).

| Repository | Files Indexed | Symbols Extracted | Baseline Tokens |
|------------|:------------:|:-----------------:|:--------------:|
| expressjs/express | 34 | 117 | 73,838 |
| fastapi/fastapi | 156 | 1,359 | 214,312 |
| gin-gonic/gin | 40 | 805 | 84,892 |

## Query Corpus

Five queries chosen to represent common code exploration intents:

| Query | Intent |
|-------|--------|
| `router route handler` | Core route registration / dispatch |
| `middleware` | Middleware chaining and execution |
| `error exception` | Error handling and exception propagation |
| `request response` | Request/response object definitions |
| `context bind` | Context creation and parameter binding |

These are defined in `tasks.json` for full reproducibility.

## Baseline Definition

**Baseline tokens** = all indexed source files concatenated and tokenized.
This represents the **minimum** cost for a "read everything first" agent.
Real agents typically read files multiple times during a session, so
production savings are higher than what the benchmark reports.

## jcodemunch Workflow

For each query:
1. Call `search_symbols(query, max_results=5)` — returns ranked symbol metadata.
2. Call `get_symbol()` on the top 3 matching symbol IDs — returns full source code.
3. **Total tokens** = search response tokens + 3 x symbol source tokens.

AI summaries were **disabled** during benchmarking (signature-only fallback).

## Token Counting Method

**Tokenizer:** `tiktoken` with `cl100k_base` encoding (used by GPT-4 and
compatible with Claude token estimates within ~5%).

Token counts are computed from the **serialized JSON response** strings,
not raw source bytes. This means:
- JSON field names and structure overhead are included (slightly understates savings).
- The count is deterministic and reproducible across runs.

### Distinction from runtime `_meta.tokens_saved`

The benchmark uses `tiktoken` for actual token counting. The runtime
`_meta.tokens_saved` field uses a byte approximation (`raw_bytes / 4`)
for zero-dependency speed. The byte approximation typically agrees within
~20% of `tiktoken` output for English-language code but can diverge for
non-ASCII content or heavily minified files. The `_meta` envelope includes
`"estimate_method": "byte_approx"` to make this explicit.

## Reproducing Results

```bash
pip install jcodemunch-mcp tiktoken

# Index the three repos
jcodemunch index_repo expressjs/express
jcodemunch index_repo fastapi/fastapi
jcodemunch index_repo gin-gonic/gin

# Run the benchmark
python benchmarks/harness/run_benchmark.py

# Write to file
python benchmarks/harness/run_benchmark.py --out benchmarks/results.md
```

The harness script reads `tasks.json`, runs each query against each repo,
counts tokens with `tiktoken`, and outputs the markdown tables in `results.md`.

## Limitations

1. **Baseline is a lower bound.** Real agents re-read files, explore
   multiple branches, and load documentation. Actual baseline costs are
   higher.
2. **Query corpus is small.** Five queries cannot represent all code
   exploration patterns. Results for specific use cases may vary.
3. **No quality measurement.** The benchmark assumes retrieved symbols
   are relevant. Retrieval precision is measured separately by
   [jMunchWorkbench](https://github.com/jgravelle/jMunchWorkbench).
4. **Single tokenizer.** Claude and GPT tokenizers produce slightly
   different counts for the same input. We use `cl100k_base` as a
   common reference point.

## Retrieval Precision

Retrieval precision (96% as reported in jMunchWorkbench) is measured by:
1. Running the same queries against the same repos.
2. Having a human evaluator judge whether the top-3 retrieved symbols
   are relevant to the query intent.
3. Precision = (relevant symbols retrieved) / (total symbols retrieved).

This evaluation is performed by jMunchWorkbench, which runs the same
prompt in two modes (baseline vs. jcodemunch) and compares answers,
tokens, and latency side-by-side.
