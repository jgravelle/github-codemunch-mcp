"""embed_repo tool — precompute and cache symbol embeddings for semantic search.

Calling this tool is optional.  ``search_symbols`` with ``semantic=true`` lazily
computes missing embeddings on first use; ``embed_repo`` just warms the cache in
one deliberate pass so that the first semantic query returns immediately.
"""

import logging
import os
import time
from typing import Optional

from ..storage import IndexStore
from ._utils import resolve_repo

logger = logging.getLogger(__name__)

# Batch size used internally by the lazy embedding path in search_symbols.
EMBED_BATCH_SIZE = 50

# ── Provider detection ──────────────────────────────────────────────────────


def _detect_provider() -> Optional[tuple[str, str]]:
    """Return (provider_name, model_name) or None when nothing is configured.

    Priority order (first match wins):
    1. sentence-transformers  — ``JCODEMUNCH_EMBED_MODEL`` env var
    2. Gemini                 — ``GOOGLE_API_KEY`` + ``GOOGLE_EMBED_MODEL``
    3. OpenAI                 — ``OPENAI_API_KEY`` + ``OPENAI_EMBED_MODEL``
    """
    st_model = os.environ.get("JCODEMUNCH_EMBED_MODEL", "").strip()
    if st_model:
        return ("sentence_transformers", st_model)

    google_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    google_model = os.environ.get("GOOGLE_EMBED_MODEL", "").strip()
    if google_key and google_model:
        return ("gemini", google_model)

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    openai_model = os.environ.get("OPENAI_EMBED_MODEL", "").strip()
    # OPENAI_API_KEY alone is used for the local-LLM summariser; require
    # OPENAI_EMBED_MODEL to be set explicitly to avoid conflation.
    if openai_key and openai_model:
        return ("openai", openai_model)

    return None


# ── Per-provider embedding functions (all lazy-imported) ───────────────────


def _embed_sentence_transformers(texts: list[str], model_name: str) -> list[list[float]]:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "sentence-transformers is not installed. "
            "Run: pip install 'jcodemunch-mcp[semantic]'"
        ) from exc
    model = SentenceTransformer(model_name)
    raw = model.encode(texts, convert_to_numpy=False, show_progress_bar=False)
    return [list(map(float, e)) for e in raw]


def _gemini_task_aware() -> bool:
    """Return True unless the user has opted out via GEMINI_EMBED_TASK_AWARE=0."""
    return os.environ.get("GEMINI_EMBED_TASK_AWARE", "1").strip() not in (
        "0", "false", "no", "off"
    )


def _embed_gemini(
    texts: list[str], model_name: str, task_type: Optional[str] = None
) -> list[list[float]]:
    try:
        import google.generativeai as genai  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "google-generativeai is not installed. "
            "Run: pip install 'jcodemunch-mcp[gemini]'"
        ) from exc
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    genai.configure(api_key=api_key)
    results = []
    for text in texts:
        kwargs: dict = {}
        if task_type:
            kwargs["task_type"] = task_type
        resp = genai.embed_content(model=model_name, content=text, **kwargs)
        results.append(list(map(float, resp["embedding"])))
    return results


def _embed_openai(texts: list[str], model_name: str) -> list[list[float]]:
    try:
        from openai import OpenAI  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "openai package is not installed. Run: pip install openai"
        ) from exc
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    response = client.embeddings.create(model=model_name, input=texts)
    return [list(map(float, item.embedding)) for item in response.data]


def embed_texts(
    texts: list[str],
    provider: str,
    model: str,
    task_type: Optional[str] = None,
) -> list[list[float]]:
    """Embed a list of texts using the named provider.

    Called by ``embed_repo`` and lazily from ``search_symbols`` when
    ``semantic=True`` and embeddings are missing from the store.

    ``task_type`` is forwarded to providers that support it (currently Gemini).
    Pass ``"RETRIEVAL_DOCUMENT"`` when embedding index documents and
    ``"CODE_RETRIEVAL_QUERY"`` when embedding a search query.  Other providers
    silently ignore the parameter.
    """
    if provider == "sentence_transformers":
        return _embed_sentence_transformers(texts, model)
    if provider == "gemini":
        return _embed_gemini(texts, model, task_type=task_type)
    if provider == "openai":
        return _embed_openai(texts, model)
    raise ValueError(f"Unknown embedding provider: {provider!r}")


# ── Symbol text representation ─────────────────────────────────────────────


def _sym_text(sym: dict) -> str:
    """Build the text string used to represent a symbol for embedding."""
    parts = [sym.get("name", ""), sym.get("signature", ""), sym.get("summary", "")]
    return " ".join(p for p in parts if p).strip() or sym.get("name", "")


# ── Tool ───────────────────────────────────────────────────────────────────


def embed_repo(
    repo: str,
    batch_size: int = EMBED_BATCH_SIZE,
    force: bool = False,
    storage_path: Optional[str] = None,
) -> dict:
    """Precompute and store all symbol embeddings for a repository.

    This is an optional warm-up step.  ``search_symbols`` with
    ``semantic=true`` will lazily embed any missing symbols on first call,
    but that first call may be slow on large repos.  Running ``embed_repo``
    upfront eliminates that latency.

    Args:
        repo: Repository identifier (owner/repo or bare name).
        batch_size: Symbols per embedding batch (default 50).
        force: When True, recompute all embeddings even if they already
               exist in the store (default False).
        storage_path: Custom storage path (defaults to CODE_INDEX_PATH).

    Returns:
        Dict with embedding stats and _meta envelope.
        On error: ``{"error": "...", "message": "..."}``
    """
    start = time.perf_counter()

    provider_info = _detect_provider()
    if provider_info is None:
        return {
            "error": "no_embedding_provider",
            "message": (
                "No embedding provider is configured. Set one of: "
                "JCODEMUNCH_EMBED_MODEL (sentence-transformers, free/local), "
                "GOOGLE_API_KEY + GOOGLE_EMBED_MODEL (Gemini), or "
                "OPENAI_API_KEY + OPENAI_EMBED_MODEL (OpenAI)."
            ),
        }
    provider, model = provider_info

    # Determine document-side task type (Gemini only).
    doc_task_type: Optional[str] = None
    if provider == "gemini" and _gemini_task_aware():
        doc_task_type = "RETRIEVAL_DOCUMENT"

    try:
        owner, name = resolve_repo(repo, storage_path)
    except ValueError as e:
        return {"error": str(e)}

    store = IndexStore(base_path=storage_path)
    index = store.load_index(owner, name)
    if not index:
        return {"error": f"Repository not indexed: {owner}/{name}"}

    from ..storage.embedding_store import EmbeddingStore
    db_path = store._sqlite._db_path(owner, name)
    emb_store = EmbeddingStore(db_path)

    # Detect dimension mismatch — if the stored model differs, force a rebuild.
    stored_dim = emb_store.get_dimension()

    # If the task type changed (e.g. Gemini task-awareness toggled), existing
    # embeddings were built with a different task type and must be regenerated.
    stored_task_type = emb_store.get_task_type()
    if not force and stored_task_type != (doc_task_type or "") and emb_store.count() > 0:
        logger.info(
            "embed_repo: task_type changed (%r → %r); forcing re-embed",
            stored_task_type,
            doc_task_type,
        )
        force = True

    if force:
        emb_store.clear()
        symbols_to_embed = list(index.symbols)
    else:
        existing_ids = set(emb_store.get_all().keys())
        symbols_to_embed = [s for s in index.symbols if s["id"] not in existing_ids]

    if not symbols_to_embed:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            "repo": f"{owner}/{name}",
            "provider": provider,
            "model": model,
            "symbols_total": len(index.symbols),
            "symbols_embedded": 0,
            "cached": True,
            "_meta": {"timing_ms": round(elapsed, 1)},
        }

    embedded_count = 0
    error_count = 0
    dim: Optional[int] = stored_dim
    batch_size = max(1, min(batch_size, 200))

    for i in range(0, len(symbols_to_embed), batch_size):
        batch = symbols_to_embed[i : i + batch_size]
        texts = [_sym_text(s) for s in batch]
        try:
            vecs = embed_texts(texts, provider, model, task_type=doc_task_type)
        except Exception as exc:
            logger.warning("embed_repo: batch %d failed: %s", i // batch_size, exc)
            error_count += len(batch)
            continue

        if dim is None and vecs:
            dim = len(vecs[0])
            emb_store.set_dimension(dim, model)
            emb_store.set_task_type(doc_task_type or "")

        emb_store.set_many({batch[j]["id"]: vecs[j] for j in range(len(batch))})
        embedded_count += len(batch)

    elapsed = (time.perf_counter() - start) * 1000
    result: dict = {
        "repo": f"{owner}/{name}",
        "provider": provider,
        "model": model,
        "symbols_total": len(index.symbols),
        "symbols_embedded": embedded_count,
        "symbols_skipped_error": error_count,
        "embedding_dimension": dim,
        "_meta": {"timing_ms": round(elapsed, 1)},
    }
    if doc_task_type:
        result["task_type"] = doc_task_type
    return result
