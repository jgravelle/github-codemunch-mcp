"""Tests for Feature 8 — Optional Semantic / Embedding Search.

All tests run without any real embedding provider by mocking embed_texts.
The full no-provider error path and zero-perf-impact defaults are verified
without any optional dependencies installed.
"""

import pytest
from unittest.mock import patch

from jcodemunch_mcp.parser.symbols import Symbol
from jcodemunch_mcp.storage import IndexStore
from jcodemunch_mcp.tools.search_symbols import search_symbols, _cosine_similarity
from jcodemunch_mcp.tools.embed_repo import embed_repo, _detect_provider, _sym_text


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_symbol(id_, name, signature="", summary="", kind="function", file="src/a.py"):
    return Symbol(
        id=id_,
        file=file,
        name=name,
        qualified_name=name,
        kind=kind,
        language="python",
        signature=signature or f"def {name}():",
        byte_offset=0,
        byte_length=50,
        summary=summary,
    )


def _seed(tmp_path, symbols, raw_files=None):
    """Index a small synthetic repo and return (store, repo_id)."""
    store = IndexStore(base_path=str(tmp_path))
    if raw_files is None:
        raw_files = {s.file: f"def {s.name}(): pass\n" for s in symbols}
    file_languages = {s.file: "python" for s in symbols}
    source_files = list({s.file for s in symbols})
    store.save_index(
        owner="test",
        name="semantic",
        source_files=source_files,
        symbols=symbols,
        raw_files=raw_files,
        languages={"python": len(source_files)},
        file_languages=file_languages,
    )
    return store, "test/semantic"


# ── Unit: _cosine_similarity ─────────────────────────────────────────────────

def test_cosine_similarity_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector_returns_zero():
    assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_cosine_similarity_mismatched_lengths_returns_zero():
    assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0


def test_cosine_similarity_opposite_vectors():
    assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


# ── Unit: _detect_provider ────────────────────────────────────────────────────

def test_detect_provider_none_when_nothing_set(monkeypatch):
    monkeypatch.delenv("JCODEMUNCH_EMBED_MODEL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_EMBED_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EMBED_MODEL", raising=False)
    assert _detect_provider() is None


def test_detect_provider_sentence_transformers(monkeypatch):
    monkeypatch.setenv("JCODEMUNCH_EMBED_MODEL", "all-MiniLM-L6-v2")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    provider, model = _detect_provider()
    assert provider == "sentence_transformers"
    assert model == "all-MiniLM-L6-v2"


def test_detect_provider_gemini(monkeypatch):
    monkeypatch.delenv("JCODEMUNCH_EMBED_MODEL", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_EMBED_MODEL", "models/embedding-001")
    monkeypatch.delenv("OPENAI_EMBED_MODEL", raising=False)
    provider, model = _detect_provider()
    assert provider == "gemini"
    assert model == "models/embedding-001"


def test_detect_provider_openai(monkeypatch):
    monkeypatch.delenv("JCODEMUNCH_EMBED_MODEL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
    provider, model = _detect_provider()
    assert provider == "openai"
    assert model == "text-embedding-3-small"


def test_detect_provider_sentence_transformers_wins_over_others(monkeypatch):
    """sentence-transformers takes priority when multiple providers are set."""
    monkeypatch.setenv("JCODEMUNCH_EMBED_MODEL", "all-MiniLM-L6-v2")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_EMBED_MODEL", "models/embedding-001")
    provider, _ = _detect_provider()
    assert provider == "sentence_transformers"


def test_detect_provider_openai_requires_embed_model(monkeypatch):
    """OPENAI_API_KEY alone (used for local LLM) must NOT activate OpenAI embeddings."""
    monkeypatch.delenv("JCODEMUNCH_EMBED_MODEL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "local-llm")
    monkeypatch.delenv("OPENAI_EMBED_MODEL", raising=False)
    assert _detect_provider() is None


# ── Integration: semantic=False has zero impact ───────────────────────────────

def test_semantic_false_default_is_pure_bm25(tmp_path):
    """semantic=False (default) must not touch the embedding code at all."""
    symbols = [
        _make_symbol("s1", "connection_pool", summary="manages db connections"),
        _make_symbol("s2", "render_html", summary="renders html templates"),
    ]
    _seed(tmp_path, symbols)

    # No monkeypatching of providers — if any embedding code ran it would fail
    result = search_symbols("test/semantic", "connection_pool", storage_path=str(tmp_path))
    assert result["result_count"] >= 1
    assert result["results"][0]["name"] == "connection_pool"
    assert "_meta" in result
    assert "search_mode" not in result["_meta"]  # not set by BM25 path


# ── Integration: no provider → structured error ───────────────────────────────

def test_semantic_true_no_provider_returns_error(tmp_path, monkeypatch):
    symbols = [_make_symbol("s1", "foo")]
    _seed(tmp_path, symbols)

    monkeypatch.delenv("JCODEMUNCH_EMBED_MODEL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_EMBED_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EMBED_MODEL", raising=False)

    result = search_symbols("test/semantic", "foo", semantic=True, storage_path=str(tmp_path))
    assert result.get("error") == "no_embedding_provider"
    assert "message" in result


def test_embed_repo_no_provider_returns_error(tmp_path, monkeypatch):
    symbols = [_make_symbol("s1", "foo")]
    _seed(tmp_path, symbols)

    monkeypatch.delenv("JCODEMUNCH_EMBED_MODEL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_EMBED_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EMBED_MODEL", raising=False)

    result = embed_repo("test/semantic", storage_path=str(tmp_path))
    assert result.get("error") == "no_embedding_provider"
    assert "message" in result


# ── Integration: mock provider — hybrid search ────────────────────────────────

def _make_vec(seed: float, dim: int = 8) -> list[float]:
    """Deterministic unit vector for testing."""
    import math
    v = [math.cos(seed + i * 0.5) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def test_semantic_hybrid_surfaces_missed_bm25_symbol(tmp_path, monkeypatch):
    """Hybrid search returns connection_pool for 'database pool' even when BM25 misses."""
    symbols = [
        _make_symbol("s1", "connection_pool", summary="manages db connections"),
        _make_symbol("s2", "render_html", summary="renders html templates"),
        _make_symbol("s3", "parse_config", summary="parses config file"),
    ]
    store, repo = _seed(tmp_path, symbols)

    # Assign embeddings: connection_pool very similar to query, others distant
    query_vec = _make_vec(0.0)
    sym_vecs = {
        "s1": _make_vec(0.05),   # very close to query
        "s2": _make_vec(3.14),   # orthogonal-ish
        "s3": _make_vec(2.0),    # distant
    }

    def _mock_embed(texts, provider, model, task_type=None):
        if len(texts) == 1 and texts[0].startswith("database"):
            return [query_vec]
        # Called for symbol texts — map by index into sym order
        return [sym_vecs.get(f"s{i+1}", _make_vec(i)) for i in range(len(texts))]

    monkeypatch.setenv("JCODEMUNCH_EMBED_MODEL", "all-MiniLM-L6-v2")
    # Patch embed_texts at its definition site — both embed_repo and
    # _search_symbols_semantic import it from there at call time.
    with patch("jcodemunch_mcp.tools.embed_repo.embed_texts", side_effect=_mock_embed):
        embed_repo(repo, storage_path=str(tmp_path))
        result = search_symbols(
            repo, "database pool", semantic=True, storage_path=str(tmp_path)
        )

    assert result.get("error") is None, result
    assert result["result_count"] >= 1
    names = [r["name"] for r in result["results"]]
    assert "connection_pool" in names, f"Expected connection_pool in {names}"
    assert result["_meta"]["search_mode"] == "hybrid"


def test_semantic_weight_zero_equals_pure_bm25(tmp_path, monkeypatch):
    """semantic_weight=0.0 must return identical ranking to pure BM25."""
    symbols = [
        _make_symbol("s1", "connection_pool", summary="database pool manager"),
        _make_symbol("s2", "render_html", summary="html renderer"),
    ]
    _seed(tmp_path, symbols)

    bm25_result = search_symbols(
        "test/semantic", "connection_pool", storage_path=str(tmp_path)
    )

    dummy_vec = _make_vec(1.0)

    def _mock_embed(texts, provider, model, task_type=None):
        return [dummy_vec for _ in texts]

    monkeypatch.setenv("JCODEMUNCH_EMBED_MODEL", "all-MiniLM-L6-v2")
    with patch("jcodemunch_mcp.tools.embed_repo.embed_texts", side_effect=_mock_embed):
        embed_repo("test/semantic", storage_path=str(tmp_path))
        sem_result = search_symbols(
            "test/semantic", "connection_pool",
            semantic=True, semantic_weight=0.0,
            storage_path=str(tmp_path),
        )

    # Both must rank connection_pool first
    assert bm25_result["results"][0]["name"] == "connection_pool"
    assert sem_result["results"][0]["name"] == "connection_pool"


def test_semantic_only_skips_bm25(tmp_path, monkeypatch):
    """semantic_only=True must surface symbols with no BM25 token overlap."""
    symbols = [
        _make_symbol("s1", "connection_pool", summary="manages db connections"),
        _make_symbol("s2", "render_html", summary="renders html"),
    ]
    _seed(tmp_path, symbols)

    # connection_pool gets a near-perfect cosine match; render_html is distant
    query_vec = _make_vec(0.0)
    sym_vecs = {"s1": _make_vec(0.01), "s2": _make_vec(3.0)}

    def _mock_embed(texts, provider, model, task_type=None):
        if len(texts) == 1:
            return [query_vec]
        return [sym_vecs.get(f"s{i+1}", _make_vec(i)) for i in range(len(texts))]

    monkeypatch.setenv("JCODEMUNCH_EMBED_MODEL", "all-MiniLM-L6-v2")
    with patch("jcodemunch_mcp.tools.embed_repo.embed_texts", side_effect=_mock_embed):
        embed_repo("test/semantic", storage_path=str(tmp_path))
        result = search_symbols(
            "test/semantic", "xyzzy_no_match",
            semantic=True, semantic_only=True,
            storage_path=str(tmp_path),
        )

    assert result.get("error") is None, result
    assert result["_meta"]["search_mode"] == "semantic_only"
    assert result["result_count"] >= 1
    assert result["results"][0]["name"] == "connection_pool"


# ── Integration: embed_repo tool ──────────────────────────────────────────────

def test_embed_repo_caches_and_skips_on_second_call(tmp_path, monkeypatch):
    """embed_repo must not recompute embeddings that are already stored."""
    symbols = [_make_symbol("s1", "foo"), _make_symbol("s2", "bar")]
    _seed(tmp_path, symbols)

    call_count = {"n": 0}

    def _mock_embed(texts, provider, model, task_type=None):
        call_count["n"] += len(texts)
        return [_make_vec(i) for i in range(len(texts))]

    monkeypatch.setenv("JCODEMUNCH_EMBED_MODEL", "all-MiniLM-L6-v2")
    with patch("jcodemunch_mcp.tools.embed_repo.embed_texts", side_effect=_mock_embed):
        r1 = embed_repo("test/semantic", storage_path=str(tmp_path))
        r2 = embed_repo("test/semantic", storage_path=str(tmp_path))

    assert r1["symbols_embedded"] == 2
    assert r2["symbols_embedded"] == 0
    assert r2.get("cached") is True
    # embed_texts was only called for the first invocation
    assert call_count["n"] == 2


def test_embed_repo_force_recomputes(tmp_path, monkeypatch):
    """force=True must recompute even when embeddings already exist."""
    symbols = [_make_symbol("s1", "foo")]
    _seed(tmp_path, symbols)

    call_count = {"n": 0}

    def _mock_embed(texts, provider, model, task_type=None):
        call_count["n"] += len(texts)
        return [_make_vec(i) for i in range(len(texts))]

    monkeypatch.setenv("JCODEMUNCH_EMBED_MODEL", "all-MiniLM-L6-v2")
    with patch("jcodemunch_mcp.tools.embed_repo.embed_texts", side_effect=_mock_embed):
        embed_repo("test/semantic", storage_path=str(tmp_path))
        r2 = embed_repo("test/semantic", force=True, storage_path=str(tmp_path))

    assert r2["symbols_embedded"] == 1
    assert call_count["n"] == 2  # called twice total


def test_embed_repo_returns_stats(tmp_path, monkeypatch):
    """embed_repo result must include provider, model, dimension, and timing."""
    symbols = [_make_symbol("s1", "foo"), _make_symbol("s2", "bar")]
    _seed(tmp_path, symbols)

    def _mock_embed(texts, provider, model, task_type=None):
        return [_make_vec(i, dim=4) for i in range(len(texts))]

    monkeypatch.setenv("JCODEMUNCH_EMBED_MODEL", "all-MiniLM-L6-v2")
    with patch("jcodemunch_mcp.tools.embed_repo.embed_texts", side_effect=_mock_embed):
        result = embed_repo("test/semantic", storage_path=str(tmp_path))

    assert result["provider"] == "sentence_transformers"
    assert result["model"] == "all-MiniLM-L6-v2"
    assert result["symbols_total"] == 2
    assert result["symbols_embedded"] == 2
    assert result["embedding_dimension"] == 4
    assert "_meta" in result
    assert result["_meta"]["timing_ms"] >= 0


# ── Integration: EmbeddingStore ───────────────────────────────────────────────

def test_embedding_store_persist_and_retrieve(tmp_path):
    """Embeddings must survive a process restart (new EmbeddingStore instance)."""
    from jcodemunch_mcp.storage.embedding_store import EmbeddingStore

    symbols = [_make_symbol("s1", "foo")]
    store, _ = _seed(tmp_path, symbols)
    db_path = store._sqlite._db_path("test", "semantic")

    vec = [0.1, 0.2, 0.3, 0.4]
    es1 = EmbeddingStore(db_path)
    es1.set_many({"s1": vec})
    es1.set_dimension(4, "test-model")

    # New instance simulates a new process
    es2 = EmbeddingStore(db_path)
    retrieved = es2.get("s1")
    assert retrieved is not None
    assert len(retrieved) == 4
    for a, b in zip(retrieved, vec):
        assert abs(a - b) < 1e-5
    assert es2.get_dimension() == 4


def test_embedding_store_delete_many(tmp_path):
    from jcodemunch_mcp.storage.embedding_store import EmbeddingStore

    symbols = [_make_symbol("s1", "foo"), _make_symbol("s2", "bar")]
    store, _ = _seed(tmp_path, symbols)
    db_path = store._sqlite._db_path("test", "semantic")

    es = EmbeddingStore(db_path)
    es.set_many({"s1": [1.0, 0.0], "s2": [0.0, 1.0]})
    assert es.count() == 2

    es.delete_many(["s1"])
    assert es.count() == 1
    assert es.get("s1") is None
    assert es.get("s2") is not None


# ── Unit: task-type helpers ───────────────────────────────────────────────────

def test_gemini_task_aware_default_is_on(monkeypatch):
    """Task-type support is enabled by default (no env var set)."""
    from jcodemunch_mcp.tools.embed_repo import _gemini_task_aware
    monkeypatch.delenv("GEMINI_EMBED_TASK_AWARE", raising=False)
    assert _gemini_task_aware() is True


def test_gemini_task_aware_opt_out(monkeypatch):
    """GEMINI_EMBED_TASK_AWARE=0 disables task types."""
    from jcodemunch_mcp.tools.embed_repo import _gemini_task_aware
    for val in ("0", "false", "no", "off"):
        monkeypatch.setenv("GEMINI_EMBED_TASK_AWARE", val)
        assert _gemini_task_aware() is False, f"should be False for {val!r}"


# ── Integration: Gemini task-type routing ─────────────────────────────────────

def test_embed_repo_passes_retrieval_document_for_gemini(tmp_path, monkeypatch):
    """embed_repo must pass task_type='RETRIEVAL_DOCUMENT' when using Gemini."""
    symbols = [_make_symbol("s1", "foo")]
    _seed(tmp_path, symbols)

    received_task_types: list = []

    def _mock_embed(texts, provider, model, task_type=None):
        received_task_types.append(task_type)
        return [_make_vec(0)]

    monkeypatch.delenv("JCODEMUNCH_EMBED_MODEL", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_EMBED_MODEL", "models/text-embedding-004")
    monkeypatch.delenv("GEMINI_EMBED_TASK_AWARE", raising=False)

    with patch("jcodemunch_mcp.tools.embed_repo.embed_texts", side_effect=_mock_embed):
        result = embed_repo("test/semantic", storage_path=str(tmp_path))

    assert result.get("error") is None, result
    assert all(tt == "RETRIEVAL_DOCUMENT" for tt in received_task_types), received_task_types
    assert result.get("task_type") == "RETRIEVAL_DOCUMENT"


def test_search_symbols_passes_code_retrieval_query_for_gemini(tmp_path, monkeypatch):
    """semantic search must use CODE_RETRIEVAL_QUERY for the query and
    RETRIEVAL_DOCUMENT for lazy symbol embedding when using Gemini."""
    symbols = [_make_symbol("s1", "authenticate_user", summary="handles auth")]
    _seed(tmp_path, symbols)

    calls: list[dict] = []
    query_vec = _make_vec(0.0)
    sym_vec = _make_vec(0.01)

    def _mock_embed(texts, provider, model, task_type=None):
        calls.append({"texts": texts, "task_type": task_type})
        # First call is the query; subsequent calls are symbol batches
        if len(texts) == 1 and texts[0] == "authenticate user":
            return [query_vec]
        return [sym_vec for _ in texts]

    monkeypatch.delenv("JCODEMUNCH_EMBED_MODEL", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_EMBED_MODEL", "models/text-embedding-004")
    monkeypatch.delenv("GEMINI_EMBED_TASK_AWARE", raising=False)

    with patch("jcodemunch_mcp.tools.embed_repo.embed_texts", side_effect=_mock_embed):
        result = search_symbols(
            "test/semantic", "authenticate user",
            semantic=True, storage_path=str(tmp_path),
        )

    assert result.get("error") is None, result
    query_calls = [c for c in calls if c["texts"] == ["authenticate user"]]
    symbol_calls = [c for c in calls if c["texts"] != ["authenticate user"]]
    assert query_calls, "expected at least one query embedding call"
    assert all(c["task_type"] == "CODE_RETRIEVAL_QUERY" for c in query_calls)
    assert all(c["task_type"] == "RETRIEVAL_DOCUMENT" for c in symbol_calls)


def test_task_type_opt_out_disables_task_types(tmp_path, monkeypatch):
    """GEMINI_EMBED_TASK_AWARE=0 must result in no task_type being passed."""
    symbols = [_make_symbol("s1", "foo")]
    _seed(tmp_path, symbols)

    received: list = []

    def _mock_embed(texts, provider, model, task_type=None):
        received.append(task_type)
        return [_make_vec(0)]

    monkeypatch.delenv("JCODEMUNCH_EMBED_MODEL", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_EMBED_MODEL", "models/text-embedding-004")
    monkeypatch.setenv("GEMINI_EMBED_TASK_AWARE", "0")

    with patch("jcodemunch_mcp.tools.embed_repo.embed_texts", side_effect=_mock_embed):
        result = embed_repo("test/semantic", storage_path=str(tmp_path))

    assert result.get("error") is None, result
    assert all(tt is None for tt in received), received
    assert "task_type" not in result


def test_task_type_change_triggers_reembed(tmp_path, monkeypatch):
    """Toggling GEMINI_EMBED_TASK_AWARE must invalidate existing embeddings."""
    symbols = [_make_symbol("s1", "foo")]
    _seed(tmp_path, symbols)

    call_count = {"n": 0}

    def _mock_embed(texts, provider, model, task_type=None):
        call_count["n"] += len(texts)
        return [_make_vec(0)]

    monkeypatch.delenv("JCODEMUNCH_EMBED_MODEL", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_EMBED_MODEL", "models/text-embedding-004")

    with patch("jcodemunch_mcp.tools.embed_repo.embed_texts", side_effect=_mock_embed):
        # First run: task-type aware (RETRIEVAL_DOCUMENT stored)
        monkeypatch.delenv("GEMINI_EMBED_TASK_AWARE", raising=False)
        embed_repo("test/semantic", storage_path=str(tmp_path))
        assert call_count["n"] == 1

        # Second run: same settings — should skip (all embedded)
        embed_repo("test/semantic", storage_path=str(tmp_path))
        assert call_count["n"] == 1  # no new calls

        # Third run: opt-out — task_type changed → must re-embed
        monkeypatch.setenv("GEMINI_EMBED_TASK_AWARE", "0")
        r = embed_repo("test/semantic", storage_path=str(tmp_path))
        assert r["symbols_embedded"] == 1
        assert call_count["n"] == 2


# ── Integration: EmbeddingStore task type persistence ─────────────────────────

def test_embedding_store_task_type_persist_and_retrieve(tmp_path):
    """set_task_type / get_task_type must round-trip through SQLite."""
    from jcodemunch_mcp.storage.embedding_store import EmbeddingStore

    symbols = [_make_symbol("s1", "foo")]
    store, _ = _seed(tmp_path, symbols)
    db_path = store._sqlite._db_path("test", "semantic")

    es1 = EmbeddingStore(db_path)
    assert es1.get_task_type() is None  # not set yet

    es1.set_task_type("RETRIEVAL_DOCUMENT")

    es2 = EmbeddingStore(db_path)  # new instance simulates new process
    assert es2.get_task_type() == "RETRIEVAL_DOCUMENT"

    es2.set_task_type("")  # clearing
    es3 = EmbeddingStore(db_path)
    assert es3.get_task_type() == ""
