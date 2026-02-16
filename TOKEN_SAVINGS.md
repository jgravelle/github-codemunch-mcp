# Token Savings: jCodeMunch MCP

## Why This Exists

AI agents waste tokens when they must read entire files to locate a single function, class, or constant.
jCodeMunch indexes a repository once and allows agents to retrieve **exact symbols on demand**, eliminating unnecessary context loading.

---

## Example Scenario

**Repository:** Medium Python codebase (300+ files)
**Task:** Locate and read the `authenticate()` implementation

| Approach         | Tokens Consumed | Process                               |
| ---------------- | --------------- | ------------------------------------- |
| Raw file loading | ~7,500 tokens   | Open multiple files and scan manually |
| jCodeMunch MCP   | ~1,449 tokens   | `search_symbols` → `get_symbol`       |

**Savings:** ~80.7%

---

## Typical Savings by Task

| Task                     | Raw Approach    | With jCodeMunch | Savings |
| ------------------------ | --------------- | --------------- | ------- |
| Explore repo structure   | ~200,000 tokens | ~2k tokens      | ~99%    |
| Find a specific function | ~40,000 tokens  | ~200 tokens     | ~99.5%  |
| Read one implementation  | ~40,000 tokens  | ~500 tokens     | ~98.7%  |
| Understand module API    | ~15,000 tokens  | ~800 tokens     | ~94.7%  |

---

## Scaling Impact

| Queries | Raw Tokens | Indexed Tokens | Savings |
| ------- | ---------- | -------------- | ------- |
| 10      | 400,000    | ~5k            | 98.7%   |
| 100     | 4,000,000  | ~50k           | 98.7%   |
| 1,000   | 40,000,000 | ~500k          | 98.7%   |

---

## Key Insight

jCodeMunch shifts the workflow from:

**“Read everything to find something”**
to
**“Find something, then read only that.”**

---
