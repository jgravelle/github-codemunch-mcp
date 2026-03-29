"""Search symbols across repository."""

import heapq
import math
import re
import time
from fnmatch import fnmatch
from typing import Optional

from ..storage import IndexStore, CodeIndex, record_savings, estimate_savings, cost_avoided
from ..parser.imports import resolve_specifier
from ._utils import resolve_repo

BYTES_PER_TOKEN = 4

# Fuzzy search: BM25 score below this auto-triggers the fuzzy pass
_FUZZY_NEAR_MISS_THRESHOLD = 0.1

# BM25 hyperparameters (standard Robertson et al. values)
_BM25_K1 = 1.5
_BM25_B = 0.75

# Per-field repetition weights: name appears 3× in the virtual doc, etc.
_FIELD_REPS = {"name": 3, "keywords": 2, "signature": 2, "summary": 1, "docstring": 1}

# Centrality: log-scaled bonus for symbols in frequently-imported files (tiebreaker only)
_CENTRALITY_WEIGHT = 0.3

# PageRank weight for sort_by="combined" (scales PR scores to be meaningful vs BM25 range)
_PR_COMBINED_WEIGHT = 100.0

# Pre-compiled regexes for _tokenize (called ~9000× on cold BM25 build)
_CAMEL_RE = re.compile(r"([a-z])([A-Z])")
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]{2,}")


def _tokenize(text: str) -> list[str]:
    """Split camelCase / snake_case text into lowercase tokens."""
    if not text:
        return []
    # Insert separator before each uppercase letter that follows a lowercase letter
    text = _CAMEL_RE.sub(r"\1_\2", text)
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _sym_tokens(sym: dict) -> list[str]:
    """Weighted token bag for a symbol (repetition = field weight).
    Cached on the symbol dict to avoid re-tokenizing across calls.
    Also caches _tf (term frequency dict) and _dl (document length)."""
    cached = sym.get("_tokens")
    # Fast path: tokens AND tf/dl all present — nothing to do
    if cached is not None and "_tf" in sym:
        return cached
    # Build tokens if not yet cached (or reuse if carried forward without _tf/_dl)
    if cached is not None:
        tokens = cached
    else:
        tokens = []
        tokens += _tokenize(sym.get("name", "")) * _FIELD_REPS["name"]
        tokens += [kw.lower() for kw in sym.get("keywords", [])] * _FIELD_REPS["keywords"]
        tokens += _tokenize(sym.get("signature", "")) * _FIELD_REPS["signature"]
        tokens += _tokenize(sym.get("summary", "")) * _FIELD_REPS["summary"]
        tokens += _tokenize(sym.get("docstring", "")) * _FIELD_REPS["docstring"]
        sym["_tokens"] = tokens
    # Always (re)compute tf/dl — cheap dict ops, ensures consistency
    # NB: _tokens/_tf/_dl are internal; all API-facing code must use explicit
    # key picks, not raw dict passthrough
    tf: dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    sym["_tf"] = tf
    sym["_dl"] = len(tokens)
    return tokens


def _compute_bm25(symbols: list[dict]) -> tuple[dict[str, float], float, dict[str, list[int]]]:
    """Return (idf_map, avgdl, inverted_index) computed over all symbols.

    The inverted_index maps each term to the list of symbol indices that
    contain it, enabling candidate-set narrowing at query time.
    """
    N = len(symbols)
    if N == 0:
        return {}, 0.0, {}
    df: dict[str, int] = {}
    total_dl = 0
    inverted: dict[str, list[int]] = {}
    for i, sym in enumerate(symbols):
        toks = _sym_tokens(sym)
        total_dl += len(toks)
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
            inverted.setdefault(t, []).append(i)
    avgdl = total_dl / N
    idf = {t: math.log((N - d + 0.5) / (d + 0.5) + 1.0) for t, d in df.items()}
    return idf, avgdl, inverted


def _compute_centrality(
    symbols: list[dict], imports: Optional[dict], alias_map: Optional[dict] = None
) -> dict[str, float]:
    """Return {file: log-scaled centrality bonus} based on importer count."""
    if not imports:
        return {}
    source_files = frozenset(s["file"] for s in symbols)
    counts: dict[str, int] = {}
    for src_file, file_imports in imports.items():
        for imp in file_imports:
            target = resolve_specifier(imp["specifier"], src_file, source_files, alias_map)
            if target:
                counts[target] = counts.get(target, 0) + 1
    return {f: math.log(1 + c) * _CENTRALITY_WEIGHT for f, c in counts.items()}


def _bm25_score(sym: dict, query_terms: list[str], idf: dict[str, float], avgdl: float,
                centrality: Optional[dict] = None) -> float:
    """BM25 score for a single symbol.

    Uses pre-cached _tf and _dl from _sym_tokens() to avoid rebuilding
    the term frequency dict on every call.
    """
    _sym_tokens(sym)  # ensure _tf/_dl are populated
    tf_raw = sym["_tf"]
    dl = sym["_dl"]

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
    """Per-field BM25 contribution breakdown (for debug mode).

    Uses cached _dl from _sym_tokens() for K computation but re-tokenizes
    per field to attribute score contributions individually.
    """
    _sym_tokens(sym)  # ensure _dl is populated
    dl = sym["_dl"]
    K = _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / max(avgdl, 1.0))

    query_set = set(query_terms)
    # Per-field tokenization is unavoidable here — we need per-field attribution
    fields = {
        "name": _tokenize(sym.get("name", "")) * _FIELD_REPS["name"],
        "keywords": [kw.lower() for kw in sym.get("keywords", [])] * _FIELD_REPS["keywords"],
        "signature": _tokenize(sym.get("signature", "")) * _FIELD_REPS["signature"],
        "summary": _tokenize(sym.get("summary", "")) * _FIELD_REPS["summary"],
        "docstring": _tokenize(sym.get("docstring", "")) * _FIELD_REPS["docstring"],
    }
    out: dict[str, float] = {}
    for fname, ftoks in fields.items():
        tf_raw: dict[str, int] = {}
        for t in ftoks:
            tf_raw[t] = tf_raw.get(t, 0) + 1
        field_score = 0.0
        for term in query_set:
            tf = tf_raw.get(term, 0)
            if tf > 0 and idf.get(term, 0.0) > 0:
                field_score += idf[term] * (tf * (_BM25_K1 + 1)) / (tf + K)
        out[fname] = round(field_score, 3)
    out["name_exact_bonus"] = 50.0 if " ".join(query_terms) == sym.get("name", "").lower() else 0.0
    return out


def _trigrams(text: str) -> frozenset:
    """Return trigram frozenset for a lowercased string."""
    s = text.lower()
    if len(s) < 3:
        return frozenset({s}) if s else frozenset()
    return frozenset(s[i:i + 3] for i in range(len(s) - 2))


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein edit distance (Wagner-Fischer, O(min(m,n)) space)."""
    if len(a) > len(b):
        a, b = b, a
    la, lb = len(a), len(b)
    row = list(range(la + 1))
    for j in range(1, lb + 1):
        prev, row[0] = row[0], j
        for i in range(1, la + 1):
            temp = row[i]
            row[i] = min(row[i] + 1, row[i - 1] + 1, prev + (0 if a[i - 1] == b[j - 1] else 1))
            prev = temp
    return row[la]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in pure Python (no numpy).

    Returns 0.0 if either vector is zero-length or the lists differ in size.
    Uses ``math.sqrt`` and ``sum()`` — no external deps.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


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
    fuzzy: bool = False,
    fuzzy_threshold: float = 0.4,
    max_edit_distance: int = 2,
    sort_by: str = "relevance",
    semantic: bool = False,
    semantic_weight: float = 0.5,
    semantic_only: bool = False,
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
        fuzzy: Enable fuzzy matching. When True (or when BM25 confidence is low),
            uses trigram overlap + edit distance as fallback. Fuzzy results carry
            match_type="fuzzy", fuzzy_similarity, and edit_distance fields.
        fuzzy_threshold: Minimum Jaccard trigram similarity (0.0–1.0) for fuzzy
            candidates. Default 0.4.
        max_edit_distance: Maximum Levenshtein distance for direct name matching
            (catches typos even when trigrams don't match). Default 2.
        sort_by: Ranking strategy. "relevance" (default) = BM25 + centrality tiebreaker.
            "centrality" = filter by query match, rank by PageRank score.
            "combined" = BM25 + PageRank weighted combination.
        semantic: Enable semantic (embedding-based) search. Requires an embedding
            provider to be configured (JCODEMUNCH_EMBED_MODEL, GOOGLE_API_KEY +
            GOOGLE_EMBED_MODEL, or OPENAI_API_KEY + OPENAI_EMBED_MODEL).
            When False (default) there is zero performance impact and no new imports.
        semantic_weight: Weight for semantic score in hybrid ranking (0.0–1.0).
            BM25 receives ``1 - semantic_weight``. Default 0.5.
            Set to 0.0 for pure BM25 behaviour; set to 1.0 for pure semantic.
        semantic_only: Skip BM25 entirely; rank solely by embedding similarity.
            Implies semantic=True.
        storage_path: Custom storage path.

    Returns:
        Dict with search results and _meta envelope.
    """
    if detail_level not in ("compact", "standard", "full"):
        return {"error": f"Invalid detail_level '{detail_level}'. Must be 'compact', 'standard', or 'full'."}

    if sort_by not in ("relevance", "centrality", "combined"):
        return {"error": f"Invalid sort_by '{sort_by}'. Must be 'relevance', 'centrality', or 'combined'."}

    _MAX_QUERY_LEN = 500
    if len(query) > _MAX_QUERY_LEN:
        return {"error": f"Query too long ({len(query)} chars, max {_MAX_QUERY_LEN})"}

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

    # Semantic: validate provider before doing any expensive work
    _semantic_provider: Optional[tuple[str, str]] = None
    if semantic or semantic_only:
        semantic = True  # semantic_only implies semantic
        from .embed_repo import _detect_provider
        _semantic_provider = _detect_provider()
        if _semantic_provider is None:
            return {
                "error": "no_embedding_provider",
                "message": (
                    "No embedding provider is configured. Set one of: "
                    "JCODEMUNCH_EMBED_MODEL (sentence-transformers, free/local), "
                    "GOOGLE_API_KEY + GOOGLE_EMBED_MODEL (Gemini), or "
                    "OPENAI_API_KEY + OPENAI_EMBED_MODEL (OpenAI)."
                ),
            }

    # BM25 corpus stats — cached on CodeIndex, computed once per index load
    query_terms = _tokenize(query) or [query.lower()]
    cache = index._bm25_cache
    if "idf" not in cache:
        cache["idf"], cache["avgdl"], cache["inverted"] = _compute_bm25(index.symbols)
        cache["centrality"] = _compute_centrality(index.symbols, index.imports, index.alias_map)
    idf = cache["idf"]
    avgdl = cache["avgdl"]
    centrality = cache["centrality"]
    inverted = cache["inverted"]

    # PageRank scores — computed and cached when sort_by requires it
    pagerank: dict = {}
    if sort_by in ("centrality", "combined"):
        if "pagerank" not in cache:
            from .pagerank import compute_pagerank
            pr_scores, _ = compute_pagerank(
                index.imports or {}, index.source_files, index.alias_map
            )
            cache["pagerank"] = pr_scores
        pagerank = cache["pagerank"]

    has_filters = bool(kind or file_pattern or language)

    # Bound the heap size in both modes.
    # token_budget mode: estimate ceiling as budget_bytes / min_symbol_size so the
    # heap stays O(N log K) instead of O(N log N) on large indexes.
    # A 20-byte floor is conservative — real symbols are rarely smaller.
    _MIN_BYTES_PER_SYMBOL = 20
    if token_budget is not None:
        budget_bytes = token_budget * BYTES_PER_TOKEN
        effective_limit = max(max_results, budget_bytes // _MIN_BYTES_PER_SYMBOL)
    else:
        budget_bytes = 0
        effective_limit = max_results

    # ── Semantic / hybrid search path ──────────────────────────────────────
    # Diverges here when semantic=True; pure BM25 path continues below.
    if semantic and _semantic_provider is not None:
        return _search_symbols_semantic(
            index=index,
            store=store,
            owner=owner,
            name=name,
            query=query,
            query_terms=query_terms,
            idf=idf,
            avgdl=avgdl,
            centrality=centrality,
            has_filters=has_filters,
            kind=kind,
            file_pattern=file_pattern,
            language=language,
            max_results=max_results,
            effective_limit=effective_limit,
            token_budget=token_budget,
            budget_bytes=budget_bytes,
            detail_level=detail_level,
            debug=debug,
            semantic_weight=semantic_weight,
            semantic_only=semantic_only,
            provider=_semantic_provider[0],
            model=_semantic_provider[1],
            start=start,
        )

    # Narrow candidates using inverted index: only score symbols that
    # contain at least one query term (union of posting lists).
    # Filters (kind/file_pattern/language) are applied AFTER narrowing.
    # Falls back to full scan when no posting lists match (e.g. query
    # terms not in any symbol) to preserve centrality-only results.
    candidate_indices: set[int] = set()
    for term in query_terms:
        posting = inverted.get(term)
        if posting:
            candidate_indices.update(posting)
    if candidate_indices:
        candidates = [index.symbols[i] for i in sorted(candidate_indices)]
    else:
        candidates = index.symbols
    heap: list[tuple[float, int, dict]] = []  # (score, candidates_scored, entry)
    candidates_scored = 0
    max_bm25_score = 0.0

    for sym in candidates:
        if has_filters:
            if kind and sym.get("kind") != kind:
                continue
            if file_pattern and not fnmatch(sym.get("file", ""), file_pattern):
                continue
            if language and sym.get("language") != language:
                continue

        score = _bm25_score(sym, query_terms, idf, avgdl, centrality)
        if score <= 0:
            continue

        if score > max_bm25_score:
            max_bm25_score = score
        candidates_scored += 1

        # Compute sort key based on sort_by strategy
        if sort_by == "centrality":
            heap_score = pagerank.get(sym.get("file", ""), 0.0)
        elif sort_by == "combined":
            heap_score = score + pagerank.get(sym.get("file", ""), 0.0) * _PR_COMBINED_WEIGHT
        else:
            heap_score = score

        if detail_level == "compact":
            entry = {
                "id": sym["id"],
                "name": sym["name"],
                "kind": sym["kind"],
                "file": sym["file"],
                "line": sym["line"],
                "byte_length": sym.get("byte_length", 0),
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
            }
        if debug:
            entry["score"] = round(score, 3)
            entry["score_breakdown"] = _bm25_breakdown(sym, query_terms, idf, avgdl)

        # Bounded heap: O(N log K) instead of O(N log N)
        if len(heap) < effective_limit:
            heapq.heappush(heap, (heap_score, candidates_scored, entry))
        elif heap_score > heap[0][0]:
            heapq.heapreplace(heap, (heap_score, candidates_scored, entry))

    # Extract results sorted by score descending
    scored_results = [entry for _, _, entry in sorted(heap, key=lambda x: x[0], reverse=True)]

    if token_budget is not None:
        packed, used_bytes = [], 0
        for entry in scored_results:
            b = entry["byte_length"]
            if used_bytes + b <= budget_bytes:
                packed.append(entry)
                used_bytes += b
        scored_results = packed

    # Fuzzy pass: runs when explicitly requested OR when BM25 found nothing useful
    run_fuzzy = fuzzy or (max_bm25_score < _FUZZY_NEAR_MISS_THRESHOLD)
    if run_fuzzy:
        for entry in scored_results:
            entry["match_type"] = "exact"

        query_lower = query.lower()
        query_tris = _trigrams(query_lower)
        existing_ids = {e["id"] for e in scored_results}
        fuzzy_hits: list[tuple[dict, float, int]] = []

        for sym in index.symbols:
            if sym["id"] in existing_ids:
                continue
            if has_filters:
                if kind and sym.get("kind") != kind:
                    continue
                if file_pattern and not fnmatch(sym.get("file", ""), file_pattern):
                    continue
                if language and sym.get("language") != language:
                    continue
            name_lower = sym.get("name", "").lower()
            name_tris = _trigrams(name_lower)
            union_size = len(query_tris | name_tris)
            jac = len(query_tris & name_tris) / union_size if union_size else 0.0
            ed = _edit_distance(query_lower, name_lower)
            if jac < fuzzy_threshold and ed > max_edit_distance:
                continue
            fuzzy_hits.append((sym, jac, ed))

        # Rank: lowest edit distance first, then highest Jaccard as tiebreaker
        fuzzy_hits.sort(key=lambda x: (x[2], -x[1]))

        for sym, jac, ed in fuzzy_hits[:max_results]:
            if detail_level == "compact":
                entry = {
                    "id": sym["id"],
                    "name": sym["name"],
                    "kind": sym["kind"],
                    "file": sym["file"],
                    "line": sym["line"],
                    "byte_length": sym.get("byte_length", 0),
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
                }
            entry["match_type"] = "fuzzy"
            entry["fuzzy_similarity"] = round(jac, 3)
            entry["edit_distance"] = ed
            if debug:
                entry["score"] = 0.0
            scored_results.append(entry)

    # Full detail: inline source, docstring, end_line for each result
    if detail_level == "full":
        for entry in scored_results:
            sym = index._get_symbol_raw(entry["id"])
            if sym:
                source = store.get_symbol_content(owner, name, entry["id"], _index=index)
                entry["end_line"] = sym.get("end_line", entry["line"])
                entry["docstring"] = sym.get("docstring", "")
                entry["source"] = source or ""

    # Token savings: files containing matches vs symbol byte_lengths of results
    raw_bytes = 0
    seen_files: set = set()
    response_bytes = 0
    for entry in scored_results:
        f = entry["file"]
        if f not in seen_files:
            seen_files.add(f)
            raw_bytes += index.file_sizes.get(f, 0)
        response_bytes += entry["byte_length"]
    tokens_saved = estimate_savings(raw_bytes, response_bytes)
    total_saved = record_savings(tokens_saved, tool_name="search_symbols")

    elapsed = (time.perf_counter() - start) * 1000

    meta = {
        "timing_ms": round(elapsed, 1),
        "total_symbols": len(index.symbols),
        "truncated": candidates_scored > len(scored_results),
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
    if scored_results:
        meta["hint"] = "Use get_context_bundle(symbol_id) to retrieve source + imports in one call"

    return {
        "result_count": len(scored_results),
        "results": scored_results,
        "_meta": meta,
    }


def _search_symbols_semantic(
    *,
    index,
    store,
    owner: str,
    name: str,
    query: str,
    query_terms: list[str],
    idf: dict,
    avgdl: float,
    centrality: dict,
    has_filters: bool,
    kind: Optional[str],
    file_pattern: Optional[str],
    language: Optional[str],
    max_results: int,
    effective_limit: int,
    token_budget: Optional[int],
    budget_bytes: int,
    detail_level: str,
    debug: bool,
    semantic_weight: float,
    semantic_only: bool,
    provider: str,
    model: str,
    start: float,
) -> dict:
    """Semantic / hybrid scoring path for search_symbols.

    Two-pass algorithm:
    1. Compute BM25 scores for all filtered symbols (for normalisation).
    2. Compute cosine similarity against the query embedding for all symbols.
    3. Combine: ``combined = (1-w)*bm25_norm + w*cosine``.

    When ``semantic_only=True`` the BM25 component is skipped entirely (w=1).
    When ``semantic_weight=0.0`` the result is identical to pure BM25.
    """
    from .embed_repo import embed_texts, _sym_text, EMBED_BATCH_SIZE, _gemini_task_aware
    from ..storage.embedding_store import EmbeddingStore
    import logging as _logging

    _logger = _logging.getLogger(__name__)

    # Determine task types (Gemini only; no-op for other providers).
    query_task_type: Optional[str] = None
    doc_task_type: Optional[str] = None
    if provider == "gemini" and _gemini_task_aware():
        query_task_type = "CODE_RETRIEVAL_QUERY"
        doc_task_type = "RETRIEVAL_DOCUMENT"

    # ── Get query embedding ────────────────────────────────────────────────
    try:
        query_vec = embed_texts([query], provider, model, task_type=query_task_type)[0]
    except Exception as exc:
        return {"error": f"Failed to embed query: {exc}"}

    # ── Load / lazily compute symbol embeddings ────────────────────────────
    db_path = store._sqlite._db_path(owner, name)
    emb_store = EmbeddingStore(db_path)
    all_emb: dict[str, list[float]] = emb_store.get_all()

    missing = [s for s in index.symbols if s["id"] not in all_emb]
    if missing:
        new_emb: dict[str, list[float]] = {}
        for bi in range(0, len(missing), EMBED_BATCH_SIZE):
            batch = missing[bi : bi + EMBED_BATCH_SIZE]
            try:
                vecs = embed_texts(
                    [_sym_text(s) for s in batch], provider, model,
                    task_type=doc_task_type,
                )
                for j, sym in enumerate(batch):
                    new_emb[sym["id"]] = vecs[j]
            except Exception as exc:
                _logger.warning("semantic: embedding batch %d failed: %s", bi // EMBED_BATCH_SIZE, exc)
        if new_emb:
            if emb_store.get_dimension() is None:
                dim = len(next(iter(new_emb.values())))
                emb_store.set_dimension(dim, model)
                emb_store.set_task_type(doc_task_type or "")
            emb_store.set_many(new_emb)
            all_emb.update(new_emb)

    # ── Two-pass scoring ───────────────────────────────────────────────────
    # Pass 1: collect BM25 + cosine for every filtered symbol
    raw: list[tuple[dict, float, float]] = []  # (sym, bm25, cosine)
    max_bm25 = 0.0

    for sym in index.symbols:
        if has_filters:
            if kind and sym.get("kind") != kind:
                continue
            if file_pattern and not fnmatch(sym.get("file", ""), file_pattern):
                continue
            if language and sym.get("language") != language:
                continue

        bm25 = 0.0 if semantic_only else _bm25_score(sym, query_terms, idf, avgdl, centrality)
        if bm25 > max_bm25:
            max_bm25 = bm25

        sym_vec = all_emb.get(sym["id"])
        cos = _cosine_similarity(query_vec, sym_vec) if sym_vec else 0.0

        raw.append((sym, bm25, cos))

    # Pass 2: normalise BM25 and compute combined score
    scored: list[tuple[float, dict]] = []
    for sym, bm25, cos in raw:
        bm25_norm = (bm25 / max_bm25) if max_bm25 > 0.0 else 0.0
        score = cos if semantic_only else (1.0 - semantic_weight) * bm25_norm + semantic_weight * cos
        if score <= 0.0:
            continue
        scored.append((score, sym))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:effective_limit]

    # ── Build result entries ───────────────────────────────────────────────
    scored_results: list[dict] = []
    for score, sym in top:
        if detail_level == "compact":
            entry: dict = {
                "id": sym["id"],
                "name": sym["name"],
                "kind": sym["kind"],
                "file": sym["file"],
                "line": sym["line"],
                "byte_length": sym.get("byte_length", 0),
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
            }
        if debug:
            entry["score"] = round(score, 4)
        scored_results.append(entry)

    # ── Token budget packing ───────────────────────────────────────────────
    if token_budget is not None:
        packed: list[dict] = []
        used = 0
        for entry in scored_results:
            b = entry["byte_length"]
            if used + b <= budget_bytes:
                packed.append(entry)
                used += b
        scored_results = packed

    # ── Full detail: inline source + docstring ─────────────────────────────
    if detail_level == "full":
        for entry in scored_results:
            sym_raw = index._get_symbol_raw(entry["id"])
            if sym_raw:
                src = store.get_symbol_content(owner, name, entry["id"], _index=index)
                entry["end_line"] = sym_raw.get("end_line", entry["line"])
                entry["docstring"] = sym_raw.get("docstring", "")
                entry["source"] = src or ""

    # ── Meta ───────────────────────────────────────────────────────────────
    raw_bytes = 0
    seen_files: set = set()
    response_bytes = 0
    for entry in scored_results:
        f = entry["file"]
        if f not in seen_files:
            seen_files.add(f)
            raw_bytes += index.file_sizes.get(f, 0)
        response_bytes += entry["byte_length"]
    tokens_saved = estimate_savings(raw_bytes, response_bytes)
    total_saved = record_savings(tokens_saved, tool_name="search_symbols")
    elapsed = (time.perf_counter() - start) * 1000

    meta: dict = {
        "timing_ms": round(elapsed, 1),
        "total_symbols": len(index.symbols),
        "truncated": len(scored) > len(scored_results),
        "tokens_saved": tokens_saved,
        "total_tokens_saved": total_saved,
        "search_mode": "semantic_only" if semantic_only else "hybrid",
        **cost_avoided(tokens_saved, total_saved),
    }
    if token_budget is not None:
        used_bytes = sum(e["byte_length"] for e in scored_results)
        meta["token_budget"] = token_budget
        meta["tokens_used"] = used_bytes // BYTES_PER_TOKEN
        meta["tokens_remaining"] = max(0, token_budget - used_bytes // BYTES_PER_TOKEN)
    if scored_results:
        meta["hint"] = "Use get_context_bundle(symbol_id) to retrieve source + imports in one call"

    return {
        "result_count": len(scored_results),
        "results": scored_results,
        "_meta": meta,
    }


