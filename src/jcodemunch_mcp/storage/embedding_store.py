"""SQLite-backed storage for symbol embeddings.

The symbol_embeddings table lives in the same .db file as the symbol index.
Embeddings are stored as float32 BLOBs serialised via the stdlib ``array`` module —
no numpy or other deps required.
"""

import array
import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_EMBEDDINGS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS symbol_embeddings (
    symbol_id TEXT PRIMARY KEY,
    embedding  BLOB NOT NULL
);
"""

_EMBED_DIM_KEY = "embed_dimension"
_EMBED_MODEL_KEY = "embed_model"
_EMBED_TASK_TYPE_KEY = "embed_task_type"


def _encode_embedding(vec: list[float]) -> bytes:
    """Serialise a float list to bytes (float32, native byte order)."""
    return array.array("f", vec).tobytes()


def _decode_embedding(data: bytes) -> list[float]:
    """Deserialise bytes back to a float list."""
    a: array.array = array.array("f")
    a.frombytes(data)
    return list(a)


class EmbeddingStore:
    """Thin CRUD wrapper around the ``symbol_embeddings`` SQLite table."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    # ── Connection ─────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(_EMBEDDINGS_SCHEMA)
        return conn

    # ── Dimension / model meta ─────────────────────────────────────────────

    def get_dimension(self) -> Optional[int]:
        """Return stored embedding dimension, or None if not set."""
        try:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key = ?", (_EMBED_DIM_KEY,)
                ).fetchone()
                return int(row[0]) if row else None
            finally:
                conn.close()
        except Exception:
            logger.debug("EmbeddingStore.get_dimension failed", exc_info=True)
            return None

    def set_dimension(self, dim: int, model: str = "") -> None:
        """Persist embedding dimension (and optionally model name) to meta."""
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (_EMBED_DIM_KEY, str(dim)),
            )
            if model:
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    (_EMBED_MODEL_KEY, model),
                )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def get_task_type(self) -> Optional[str]:
        """Return stored embedding task type, or None if not set."""
        try:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key = ?", (_EMBED_TASK_TYPE_KEY,)
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()
        except Exception:
            logger.debug("EmbeddingStore.get_task_type failed", exc_info=True)
            return None

    def set_task_type(self, task_type: str) -> None:
        """Persist the embedding task type used when building the index."""
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (_EMBED_TASK_TYPE_KEY, task_type),
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    # ── Read ───────────────────────────────────────────────────────────────

    def get(self, symbol_id: str) -> Optional[list[float]]:
        """Return the embedding for one symbol, or None."""
        try:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT embedding FROM symbol_embeddings WHERE symbol_id = ?",
                    (symbol_id,),
                ).fetchone()
                return _decode_embedding(row[0]) if row else None
            finally:
                conn.close()
        except Exception:
            logger.debug("EmbeddingStore.get failed for %s", symbol_id, exc_info=True)
            return None

    def get_all(self) -> dict[str, list[float]]:
        """Return every stored embedding as {symbol_id: vector}."""
        try:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT symbol_id, embedding FROM symbol_embeddings"
                ).fetchall()
                return {row[0]: _decode_embedding(row[1]) for row in rows}
            finally:
                conn.close()
        except Exception:
            logger.debug("EmbeddingStore.get_all failed", exc_info=True)
            return {}

    def count(self) -> int:
        """Return the number of stored embeddings."""
        try:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM symbol_embeddings"
                ).fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()
        except Exception:
            return 0

    # ── Write ──────────────────────────────────────────────────────────────

    def set_many(self, embeddings: dict[str, list[float]]) -> None:
        """Upsert multiple symbol embeddings in one transaction."""
        if not embeddings:
            return
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            conn.executemany(
                "INSERT OR REPLACE INTO symbol_embeddings (symbol_id, embedding) VALUES (?, ?)",
                [(sid, _encode_embedding(vec)) for sid, vec in embeddings.items()],
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def delete_many(self, symbol_ids: list[str]) -> None:
        """Remove embeddings for specific symbols (e.g. after incremental reindex)."""
        if not symbol_ids:
            return
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            placeholders = ",".join("?" * len(symbol_ids))
            conn.execute(
                f"DELETE FROM symbol_embeddings WHERE symbol_id IN ({placeholders})",
                symbol_ids,
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def clear(self) -> None:
        """Delete all stored embeddings (used by embed_repo with force=True)."""
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM symbol_embeddings")
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()
