# v1.70.0 A/B Benchmark Results

_Measured on jcodemunch-mcp dogfooding itself (self-indexed)._

Symbols indexed: **?**

---

## §1.1 — Default `detail_level` flip: `standard` → `auto`

**Discovery queries** (broad `max_results=10`, no `token_budget`, no `debug`): `auto` resolves to **compact**, stripping signatures/summaries that aren't useful until the caller has narrowed down.

- Total tokens across 16 discovery queries:
  - Old default (`standard`): **22,120** tokens
  - New default (`auto`):     **17,416** tokens
  - **Saved: 4,704 tokens (21.3%)**
- Median per-query savings: **18.9%**
- Max per-query savings:    **33.7%**

| query | results | tokens_standard | tokens_auto | savings_tokens | savings_pct |
|---|---|---|---|---|---|
| search | 10 | 1300 | 1010 | 290 | 22.3 |
| index | 10 | 1273 | 1053 | 220 | 17.3 |
| parse | 10 | 1364 | 1030 | 334 | 24.5 |
| symbol | 10 | 1361 | 1115 | 246 | 18.1 |
| config | 10 | 1309 | 1110 | 199 | 15.2 |
| token | 10 | 1519 | 1329 | 190 | 12.5 |
| cache | 10 | 1429 | 1074 | 355 | 24.8 |
| embed | 10 | 1394 | 1149 | 245 | 17.6 |
| error | 10 | 1287 | 1107 | 180 | 14.0 |
| fusion | 10 | 1369 | 1099 | 270 | 19.7 |
| budget | 10 | 1420 | 1187 | 233 | 16.4 |
| detail | 10 | 1490 | 1096 | 394 | 26.4 |
| resolve | 10 | 1571 | 1083 | 488 | 31.1 |
| encode | 10 | 1445 | 1045 | 400 | 27.7 |
| store | 10 | 1264 | 1050 | 214 | 16.9 |
| summar | 10 | 1325 | 879 | 446 | 33.7 |

### Narrow-query parity (no regression)

When `max_results<5`, `auto` escalates to `standard` — caller explicitly asked for few results, so they likely want signatures. Both defaults must produce identical payloads.

**All 6 narrow queries identical under `auto` vs `standard`: True**

| query | results | tokens_standard | tokens_auto | identical |
|---|---|---|---|---|
| _materialize_full_entry | 3 | 454 | 454 | True |
| encode_response | 3 | 388 | 388 | True |
| search_symbols | 3 | 366 | 366 | True |
| index_folder | 3 | 376 | 376 | True |
| get_symbol_source | 3 | 331 | 331 | True |
| resolve_specifier | 3 | 411 | 411 | True |

---

## §1.2 — Full-mode `token_budget` adherence

Under v1.63.1, `detail_level='full'` materialized `source`/`docstring`/`end_line` **after** the budget packer had already picked winners — so the declared budget was routinely overshot by 5–20×. v1.70.0 materializes full content **before** packing, so `byte_length` reflects what actually ships.

Budget: **4,000 bytes** (1000 tokens).

- **All 8 queries compliant: True**
- Worst-case headroom: **0.0%** (negative = overshot)

| query | results | budget_bytes | bytes_used | compliant | headroom_pct | payload_tokens |
|---|---|---|---|---|---|---|
| search | 12 | 4000 | 3989 | True | 0.3 | 2252 |
| index | 9 | 4000 | 3974 | True | 0.6 | 1897 |
| parse | 6 | 4000 | 3940 | True | 1.5 | 1617 |
| symbol | 5 | 4000 | 3994 | True | 0.1 | 1304 |
| config | 17 | 4000 | 3959 | True | 1.0 | 2801 |
| token | 52 | 4000 | 4000 | True | 0.0 | 8293 |
| cache | 7 | 4000 | 3999 | True | 0.0 | 1635 |
| embed | 18 | 4000 | 3978 | True | 0.5 | 3245 |

---

## Methodology

- Index: `jcodemunch-mcp` source tree (self-indexed, dogfood)
- Token counter: `tiktoken` cl100k_base
- `auto` resolution rules: `compact` when `token_budget is None and not debug and max_results>=5`, else `standard`
- Budget adherence: `sum(byte_length)` over returned results vs declared budget in bytes (`token_budget*4`)
- Reproduce: `PYTHONPATH=src python benchmarks/harness/ab_v1_70_0.py`