"""Tests for BM25 correctness — T10 (avgdl inflation) and T11 (canonical corpus)."""

import math

from jcodemunch_mcp.tools.search_symbols import (
    _sym_tokens,
    _compute_bm25,
    _FIELD_REPS,
)


# ---------------------------------------------------------------------------
# T10: _dl uses unique token count, not repeated bag
# ---------------------------------------------------------------------------

class TestBM25DlUnique:

    def test_dl_is_unique_token_count(self):
        """_dl must equal len(set(tokens)), not len(tokens)."""
        sym = {"name": "parse_file", "signature": "", "summary": "", "docstring": "", "keywords": []}
        tokens = _sym_tokens(sym)
        # tokens = _tokenize("parse_file") * 3 = ["parse", "file"] * 3 → 6 items
        assert len(tokens) == 6
        assert sym["_dl"] == 2  # unique: {"parse", "file"}

    def test_dl_not_inflated_by_field_reps(self):
        """Repeated tokens from field weights must not inflate _dl."""
        sym = {
            "name": "foo",
            "signature": "foo(x)",
            "summary": "foo does something",
            "docstring": "",
            "keywords": [],
        }
        tokens = _sym_tokens(sym)
        # Raw repeated bag has more entries than unique tokens
        assert len(tokens) > sym["_dl"]
        assert sym["_dl"] == len(set(tokens))

    def test_dl_matches_set_of_tokens(self):
        """_dl must always equal len(set(_tokens)) for any symbol."""
        sym = {
            "name": "process_data",
            "signature": "process_data(df: DataFrame) -> dict",
            "summary": "process a data frame",
            "docstring": "Process the input data and return results.",
            "keywords": ["data", "process"],
        }
        tokens = _sym_tokens(sym)
        assert sym["_dl"] == len(set(tokens))

    def test_dl_no_inflation_compared_to_pre_t10(self):
        """_dl must be strictly less than len(tokens) when tokens have repeats."""
        sym = {"name": "handler", "signature": "handler(req)", "summary": "", "docstring": "", "keywords": []}
        tokens = _sym_tokens(sym)
        # name tokens appear 3×, signature tokens appear 2× — repeated bag > unique
        if len(set(tokens)) < len(tokens):
            assert sym["_dl"] < len(tokens), "_dl should not equal the inflated bag length"

    def test_dl_consistent_on_second_call(self):
        """Fast-path (_tokens cached) does not reset _dl to wrong value."""
        sym = {"name": "connect", "signature": "connect(host, port)", "summary": "", "docstring": "", "keywords": []}
        _sym_tokens(sym)                    # first call — computes everything
        dl_first = sym["_dl"]
        _sym_tokens(sym)                    # second call — fast path
        # _dl is not recomputed on fast path, but should stay correct
        assert sym["_dl"] == dl_first == len(set(sym["_tokens"]))


# ---------------------------------------------------------------------------
# T10 + T11: _compute_bm25 uses canonical unique-token avgdl
# ---------------------------------------------------------------------------

class TestComputeBM25Canonical:

    def _make_sym(self, name: str, summary: str = "") -> dict:
        return {"name": name, "signature": "", "summary": summary, "docstring": "", "keywords": []}

    def test_avgdl_not_inflated(self):
        """avgdl must be computed from unique token counts, not repeated bag lengths."""
        syms = [self._make_sym("parse"), self._make_sym("render"), self._make_sym("connect")]
        _, avgdl, _ = _compute_bm25(syms)
        # Each symbol: name token × 3 field reps → 1 unique token per symbol
        # avgdl should be 1.0 (unique), not 3.0 (repeated bag)
        assert avgdl == 1.0, f"Expected avgdl=1.0 (unique), got {avgdl}"

    def test_compute_bm25_rewrites_dl(self):
        """_compute_bm25 must overwrite stale _dl values on retained symbols (T11)."""
        sym = self._make_sym("alpha")
        # Manually inject a stale _dl (simulating a symbol cached before T10)
        _sym_tokens(sym)
        sym["_dl"] = 999  # stale value from old len(tokens) formula
        _compute_bm25([sym])
        assert sym["_dl"] != 999, "_compute_bm25 must rewrite stale _dl"
        assert sym["_dl"] == len(set(sym["_tokens"]))

    def test_bm25_corpus_size_equals_symbol_count(self):
        """After _compute_bm25, inverted index covers exactly N symbols (no doubling)."""
        syms = [self._make_sym(f"func_{i}") for i in range(5)]
        idf, avgdl, inverted = _compute_bm25(syms)
        # Every symbol index 0-4 must appear in the inverted index
        all_indices = set()
        for idxs in inverted.values():
            all_indices.update(idxs)
        assert all_indices == set(range(5)), "Inverted index must cover exactly the 5 symbols"

    def test_dl_consistent_after_compute(self):
        """All symbols must have _dl == len(set(_tokens)) after _compute_bm25 runs."""
        syms = [
            self._make_sym("alpha", summary="first function"),
            self._make_sym("beta", summary="second function here"),
            self._make_sym("gamma"),
        ]
        _compute_bm25(syms)
        for sym in syms:
            assert sym["_dl"] == len(set(sym["_tokens"])), (
                f"Symbol {sym['name']}: _dl={sym['_dl']} != {len(set(sym['_tokens']))}"
            )

    def test_idf_formula_correct(self):
        """idf uses Robertson formula: log((N - df + 0.5) / (df + 0.5) + 1)."""
        # 2 symbols both containing "shared", 1 symbol with "unique"
        sym_a = {"name": "shared_alpha", "signature": "", "summary": "", "docstring": "", "keywords": []}
        sym_b = {"name": "shared_beta", "signature": "", "summary": "", "docstring": "", "keywords": []}
        sym_c = {"name": "unique_func", "signature": "", "summary": "", "docstring": "", "keywords": []}
        idf, _, _ = _compute_bm25([sym_a, sym_b, sym_c])
        N = 3
        # "shared" appears in 2 docs
        expected_shared = math.log((N - 2 + 0.5) / (2 + 0.5) + 1.0)
        assert abs(idf.get("shared", 0) - expected_shared) < 1e-9
        # "unique" appears in 1 doc
        expected_unique = math.log((N - 1 + 0.5) / (1 + 0.5) + 1.0)
        assert abs(idf.get("unique", 0) - expected_unique) < 1e-9

    def test_retained_symbol_stale_dl_corrected(self):
        """Simulates a retained symbol with pre-T10 stale _dl surviving into a BM25 rebuild."""
        sym = {"name": "process", "signature": "process(x, y)", "summary": "", "docstring": "", "keywords": []}
        # Pre-T10: _tokens cached, _tf cached, _dl set to inflated len(tokens)
        tokens = _sym_tokens(sym)
        inflated_dl = len(tokens)
        sym["_dl"] = inflated_dl  # inject stale pre-T10 value
        # Simulate a BM25 rebuild (e.g., after deferred summarize or server restart)
        _compute_bm25([sym])
        # T11: _compute_bm25 must have corrected _dl
        canonical_dl = len(set(sym["_tokens"]))
        assert sym["_dl"] == canonical_dl, (
            f"After rebuild, _dl={sym['_dl']} should be canonical {canonical_dl}, "
            f"not inflated {inflated_dl}"
        )
