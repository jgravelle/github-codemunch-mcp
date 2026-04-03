"""Property-based tests for jcodemunch-mcp invariants (T22).

Three invariants are checked across randomly generated inputs:

1. **ID uniqueness**: All symbols in a freshly-indexed repo have unique IDs.
2. **Incremental idempotency**: Indexing the same files twice produces the
   same symbol IDs and counts (no phantom duplicates or removals).
3. **No self-imports (DAG edge invariant)**: No file in the import graph
   lists itself as one of its own importers.

Note: Tests manage their own temp dirs (not ``tmp_path``) so Hypothesis can
reset state properly between generated examples.
"""

import string
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from jcodemunch_mcp.tools.index_folder import index_folder
from jcodemunch_mcp.storage import IndexStore


# ---------------------------------------------------------------------------
# Strategies — generate valid Python identifiers and source snippets
# ---------------------------------------------------------------------------

_IDENT_CHARS = string.ascii_lowercase + string.digits + "_"
_IDENT_FIRST = string.ascii_lowercase

_ident = st.text(
    alphabet=_IDENT_CHARS,
    min_size=1,
    max_size=16,
).map(lambda s: (s[0] if s[0] in _IDENT_FIRST else "f") + s[1:])

_PY_KEYWORDS = frozenset(
    {"def", "class", "return", "import", "pass", "if", "for", "in",
     "and", "or", "not", "is", "None", "True", "False", "from", "as",
     "with", "while", "try", "except", "finally", "raise", "yield",
     "async", "await", "lambda", "del", "global", "nonlocal", "assert"}
)
_func_name = _ident.filter(lambda s: s not in _PY_KEYWORDS)


def _make_python_module(func_names: list[str], class_names: list[str]) -> str:
    """Generate a syntactically valid Python source string."""
    lines = []
    for cn in class_names:
        lines.append(f"class {cn}:")
        lines.append("    pass")
        lines.append("")
    for fn in func_names:
        lines.append(f"def {fn}(x):")
        lines.append("    return x")
        lines.append("")
    return "\n".join(lines) if lines else "x = 1\n"


def _make_importing_module(importee_name: str) -> str:
    """Python module that imports from another module in the same package."""
    return f"from {importee_name} import x\n\ndef use():\n    return x\n"


def _load_index(store_path: str, repo: str):
    """Helper: load a CodeIndex given a store path and repo string (owner/name)."""
    owner, rname = repo.split("/", 1)
    return IndexStore(base_path=store_path).load_index(owner, rname)


# ---------------------------------------------------------------------------
# Property 1 — ID uniqueness
# ---------------------------------------------------------------------------

class TestIdUniqueness:

    @given(
        func_names=st.lists(_func_name, min_size=1, max_size=8, unique=True),
        class_names=st.lists(_func_name, min_size=0, max_size=4, unique=True),
    )
    @settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_all_symbol_ids_unique(self, func_names, class_names):
        """All symbols in a freshly-indexed folder must have unique IDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "src"
            store = Path(tmpdir) / "store"
            src.mkdir()
            store.mkdir()

            content = _make_python_module(func_names, class_names)
            (src / "module.py").write_text(content)

            r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
            assert r["success"] is True

            index = _load_index(str(store), r["repo"])
            assert index is not None

            ids = [s["id"] for s in index.symbols]
            assert len(ids) == len(set(ids)), (
                f"Duplicate symbol IDs detected: "
                f"{[sid for sid in ids if ids.count(sid) > 1]}"
            )


# ---------------------------------------------------------------------------
# Property 2 — Incremental idempotency
# ---------------------------------------------------------------------------

class TestIncrementalIdempotency:

    @given(
        func_names=st.lists(_func_name, min_size=1, max_size=6, unique=True),
    )
    @settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_second_index_same_symbols(self, func_names):
        """Indexing the same unchanged files twice yields the same symbol set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "src"
            store = Path(tmpdir) / "store"
            src.mkdir()
            store.mkdir()

            content = _make_python_module(func_names, [])
            (src / "utils.py").write_text(content)

            r1 = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
            assert r1["success"] is True
            repo = r1["repo"]
            idx1 = _load_index(str(store), repo)
            ids1 = sorted(s["id"] for s in idx1.symbols)

            # Second run may return incremental-update dict (no symbol_count key)
            r2 = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
            assert r2["success"] is True
            idx2 = _load_index(str(store), repo)
            ids2 = sorted(s["id"] for s in idx2.symbols)

            assert ids1 == ids2, (
                f"Symbol IDs changed between two identical index runs.\n"
                f"First: {ids1}\nSecond: {ids2}"
            )
            assert len(idx1.symbols) == len(idx2.symbols), (
                f"Symbol count changed: {len(idx1.symbols)} -> {len(idx2.symbols)}"
            )

    @given(
        func_names=st.lists(_func_name, min_size=2, max_size=6, unique=True),
    )
    @settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_multi_file_second_index_same_symbols(self, func_names):
        """Multi-file repos are also idempotent across two index runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "src"
            store = Path(tmpdir) / "store"
            src.mkdir()
            store.mkdir()

            mid = max(1, len(func_names) // 2)
            (src / "a.py").write_text(_make_python_module(func_names[:mid], []))
            (src / "b.py").write_text(_make_python_module(func_names[mid:], []))

            r1 = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
            assert r1["success"] is True
            repo = r1["repo"]
            idx1 = _load_index(str(store), repo)

            r2 = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
            assert r2["success"] is True
            idx2 = _load_index(str(store), repo)

            assert len(idx1.symbols) == len(idx2.symbols), (
                f"Symbol count changed between runs: "
                f"{len(idx1.symbols)} -> {len(idx2.symbols)}"
            )


# ---------------------------------------------------------------------------
# Property 3 — No self-imports (DAG edge invariant)
# ---------------------------------------------------------------------------

class TestNoSelfImports:

    @given(
        mod_names=st.lists(_func_name, min_size=2, max_size=5, unique=True),
    )
    @settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_no_file_imports_itself(self, mod_names):
        """No file should list itself as an importer in the import graph."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "src"
            store = Path(tmpdir) / "store"
            src.mkdir()
            store.mkdir()

            # First module is the importee; rest import from it
            importee = mod_names[0]
            (src / f"{importee}.py").write_text("x = 1\n")
            for importer in mod_names[1:]:
                (src / f"{importer}.py").write_text(_make_importing_module(importee))

            r = index_folder(str(src), use_ai_summaries=False, storage_path=str(store))
            assert r["success"] is True

            index = _load_index(str(store), r["repo"])
            assert index is not None

            imports = index.imports  # file_path -> list[{"specifier": ..., "names": ...}]

            for file_path, edges in imports.items():
                stem = Path(file_path).stem
                for edge in edges:
                    spec = edge.get("specifier", "")
                    resolved = edge.get("resolved")

                    if resolved:
                        assert resolved != file_path, (
                            f"Self-import detected: {file_path} resolves to itself "
                            f"via '{spec}'"
                        )
                    # Raw specifier must not equal own stem or full path
                    assert spec != stem, (
                        f"Self-import by stem: {file_path} imports '{spec}'"
                    )
                    assert spec != file_path, (
                        f"Self-import by path: {file_path} imports '{spec}'"
                    )
