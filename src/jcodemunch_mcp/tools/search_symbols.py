"""Search symbols across repository."""

import math
import os
import re
import time
from typing import Optional

from ..storage import IndexStore, CodeIndex, record_savings, estimate_savings, cost_avoided
from ..parser.imports import resolve_specifier
from ._utils import resolve_repo

BYTES_PER_TOKEN = 4

# BM25 hyperparameters (standard Robertson et al. values)
_BM25_K1 = 1.5
_BM25_B = 0.75

# Per-field repetition weights: name appears 3× in the virtual doc, etc.
_FIELD_REPS = {"name": 3, "keywords": 2, "signature": 2, "summary": 1, "docstring": 1}

# Centrality: log-scaled bonus for symbols in frequently-imported files (tiebreaker only)
_CENTRALITY_WEIGHT = 0.3


def _tokenize(text: str) -> list[str]:
    """Split camelCase / snake_case text into lowercase tokens."""
    if not text:
        return []
    # Insert separator before each uppercase letter that follows a lowercase letter
    text = re.sub(r"([a-z])([A-Z])", r"\1_\2", text)
    return [t.lower() for t in re.findall(r"[a-zA-Z0-9]+", text) if len(t) > 1]


def _sym_tokens(sym: dict) -> list[str]:
    """Weighted token bag for a symbol (repetition = field weight)."""
    tokens: list[str] = []
    tokens += _tokenize(sym.get("name", "")) * _FIELD_REPS["name"]
    tokens += [kw.lower() for kw in sym.get("keywords", [])] * _FIELD_REPS["keywords"]
    tokens += _tokenize(sym.get("signature", "")) * _FIELD_REPS["signature"]
    tokens += _tokenize(sym.get("summary", "")) * _FIELD_REPS["summary"]
    tokens += _tokenize(sym.get("docstring", "")) * _FIELD_REPS["docstring"]
    return tokens


def _compute_bm25(symbols: list[dict]) -> tuple[dict[str, float], float]:
    """Return (idf_map, avgdl) computed over all symbols in the index."""
    N = len(symbols)
    if N == 0:
        return {}, 0.0
    df: dict[str, int] = {}
    total_dl = 0
    for sym in symbols:
        toks = _sym_tokens(sym)
        total_dl += len(toks)
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    avgdl = total_dl / N
    idf = {t: math.log((N - d + 0.5) / (d + 0.5) + 1.0) for t, d in df.items()}
    return idf, avgdl


def _compute_centrality(symbols: list[dict], imports: Optional[dict]) -> dict[str, float]:
    """Return {file: log-scaled centrality bonus} based on importer count."""
    if not imports:
        return {}
    source_files = frozenset(s["file"] for s in symbols)
    counts: dict[str, int] = {}
    for src_file, file_imports in imports.items():
        for imp in file_imports:
            target = resolve_specifier(imp["specifier"], src_file, source_files)
            if target:
                counts[target] = counts.get(target, 0) + 1
    return {f: math.log(1 + c) * _CENTRALITY_WEIGHT for f, c in counts.items()}


def _bm25_score(sym: dict, query_terms: list[str], idf: dict[str, float], avgdl: float,
                centrality: Optional[dict] = None) -> float:
    """BM25 score for a single symbol."""
    tokens = _sym_tokens(sym)
    dl = len(tokens)
    tf_raw: dict[str, int] = {}
    for t in tokens:
        tf_raw[t] = tf_raw.get(t, 0) + 1

    # Exact name match bonus so direct lookups still float to the top
    name_lower = sym.get("name", "").lower()
    query_joined = " ".join(query_terms)
    score: float = 50.0 if query_joined == name_lower else 0.0

    K = _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / max(avgdl, 1.0))
    for term in set(query_terms):
        idf_val = idf.get(term, 0.0)
        if idf_val == 0.0:
            continue
        tf = tf_raw.get(term, 0)
        if tf == 0:
            continue
        score += idf_val * (tf * (_BM25_K1 + 1)) / (tf + K)

    if centrality:
        score += centrality.get(sym.get("file", ""), 0.0)

    return score


def _bm25_breakdown(sym: dict, query_terms: list[str], idf: dict[str, float], avgdl: float) -> dict:
    """Per-field BM25 contribution breakdown (for debug mode)."""
    out: dict[str, float] = {}
    K = _BM25_K1 * (1 - _BM25_B + _BM25_B * len(_sym_tokens(sym)) / max(avgdl, 1.0))

    fields = {
        "name": _tokenize(sym.get("name", "")) * _FIELD_REPS["name"],
        "keywords": [kw.lower() for kw in sym.get("keywords", [])] * _FIELD_REPS["keywords"],
        "signature": _tokenize(sym.get("signature", "")) * _FIELD_REPS["signature"],
        "summary": _tokenize(sym.get("summary", "")) * _FIELD_REPS["summary"],
        "docstring": _tokenize(sym.get("docstring", "")) * _FIELD_REPS["docstring"],
    }
    for fname, ftoks in fields.items():
        tf_raw: dict[str, int] = {}
        for t in ftoks:
            tf_raw[t] = tf_raw.get(t, 0) + 1
        field_score = 0.0
        for term in set(query_terms):
            tf = tf_raw.get(term, 0)
            if tf > 0 and idf.get(term, 0.0) > 0:
                field_score += idf[term] * (tf * (_BM25_K1 + 1)) / (tf + K)
        out[fname] = round(field_score, 3)
    out["name_exact_bonus"] = 50.0 if " ".join(query_terms) == sym.get("name", "").lower() else 0.0
    return out


def search_symbols(
    repo: str,
    query: str,
    kind: Optional[str] = None,
    file_pattern: Optional[str] = None,
    language: Optional[str] = None,
    max_results: int = 10,
    token_budget: Optional[int] = None,
    detail_level: str = "standard",
    debug: bool = False,
    storage_path: Optional[str] = None
) -> dict:
    """Search for symbols matching a query.

    Args:
        repo: Repository identifier (owner/repo or just repo name).
        query: Search query.
        kind: Optional filter by symbol kind.
        file_pattern: Optional glob pattern to filter files.
        language: Optional filter by language (e.g., "python", "javascript").
        max_results: Maximum results to return (ignored when token_budget is set).
        token_budget: Maximum tokens to consume. Results are greedily packed by
            score until the budget is exhausted. Overrides max_results.
        detail_level: Controls result verbosity. "compact" returns id/name/kind/file/line
            only (~15 tokens each, ideal for discovery). "standard" returns signatures
            and summaries (default). "full" inlines source code, docstring, and end_line.
        debug: When True, include per-field score breakdown in each result.
        storage_path: Custom storage path.

    Returns:
        Dict with search results and _meta envelope.
    """
    if detail_level not in ("compact", "standard", "full"):
        return {"error": f"Invalid detail_level '{detail_level}'. Must be 'compact', 'standard', or 'full'."}

    start = time.perf_counter()
    max_results = max(1, min(max_results, 100))

    try:
        owner, name = resolve_repo(repo, storage_path)
    except ValueError as e:
        return {"error": str(e)}

    # Load index
    store = IndexStore(base_path=storage_path)
    index = store.load_index(owner, name)

    if not index:
        return {"error": f"Repository not indexed: {owner}/{name}"}

    # Fetch all candidates so BM25 can re-rank freely (pre-filter still rejects score==0)
    results = index.search(query, kind=kind, file_pattern=file_pattern, limit=0)

    # Apply language filter (post-search since CodeIndex.search doesn't support it)
    if language:
        results = [s for s in results if s.get("language") == language]

    # BM25 scoring + centrality
    query_terms = _tokenize(query) or [query.lower()]
    idf, avgdl = _compute_bm25(index.symbols)
    centrality = _compute_centrality(index.symbols, index.imports)

    candidates_scored = len(results)
    scored_results = []
    for sym in results:
        score = _bm25_score(sym, query_terms, idf, avgdl, centrality)
        if detail_level == "compact":
            entry = {
                "id": sym["id"],
                "name": sym["name"],
                "kind": sym["kind"],
                "file": sym["file"],
                "line": sym["line"],
                "byte_length": sym.get("byte_length", 0),
                "score": score,
            }
        else:
            entry = {
                "id": sym["id"],
                "kind": sym["kind"],
                "name": sym["name"],
                "file": sym["file"],
                "line": sym["line"],
                "signature": sym["signature"],
                "summary": sym.get("summary", ""),
                "byte_length": sym.get("byte_length", 0),
                "score": score,
            }
        if debug:
            entry["score_breakdown"] = _bm25_breakdown(sym, query_terms, idf, avgdl)
        scored_results.append(entry)

    # Sort by BM25 score descending; then apply budget or max_results cap
    scored_results.sort(key=lambda x: x["score"], reverse=True)

    if token_budget is not None:
        budget_bytes = token_budget * BYTES_PER_TOKEN
        packed, used_bytes = [], 0
        for entry in scored_results:
            b = entry["byte_length"]
            if used_bytes + b <= budget_bytes:
                packed.append(entry)
                used_bytes += b
        scored_results = packed
    else:
        scored_results = scored_results[:max_results]

    # Full detail: inline source, docstring, end_line for each result
    if detail_level == "full":
        for entry in scored_results:
            sym = index.get_symbol(entry["id"])
            if sym:
                source = store.get_symbol_content(owner, name, entry["id"], _index=index)
                entry["end_line"] = sym.get("end_line", entry["line"])
                entry["docstring"] = sym.get("docstring", "")
                entry["source"] = source or ""

    # Token savings: files containing matches vs symbol byte_lengths of results
    raw_bytes = 0
    seen_files: set = set()
    response_bytes = 0
    content_dir = store._content_dir(owner, name)
    for sym in results[:max_results]:
        f = sym["file"]
        if f not in seen_files:
            seen_files.add(f)
            try:
                raw_bytes += os.path.getsize(content_dir / f)
            except OSError:
                pass
        response_bytes += sym.get("byte_length", 0)
    tokens_saved = estimate_savings(raw_bytes, response_bytes)
    total_saved = record_savings(tokens_saved, tool_name="search_symbols")

    elapsed = (time.perf_counter() - start) * 1000

    meta = {
        "timing_ms": round(elapsed, 1),
        "total_symbols": len(index.symbols),
        "truncated": len(results) > max_results,
        "tokens_saved": tokens_saved,
        "total_tokens_saved": total_saved,
        **cost_avoided(tokens_saved, total_saved),
    }
    if token_budget is not None:
        used = sum(e["byte_length"] for e in scored_results)
        meta["token_budget"] = token_budget
        meta["tokens_used"] = used // BYTES_PER_TOKEN
        meta["tokens_remaining"] = max(0, token_budget - used // BYTES_PER_TOKEN)
    if debug:
        meta["candidates_scored"] = candidates_scored

    return {
        "repo": f"{owner}/{name}",
        "query": query,
        "result_count": len(scored_results),
        "results": scored_results,
        "_meta": meta,
    }


