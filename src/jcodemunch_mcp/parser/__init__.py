"""Parser package for extracting symbols from source code."""

from .symbols import Symbol, slugify, make_symbol_id, compute_content_hash
from .languages import (
    LanguageSpec,
    LANGUAGE_REGISTRY,
    LANGUAGE_EXTENSIONS,
    PYTHON_SPEC,
    CANONICAL_LANGUAGES,
    LANGUAGE_ALIASES,
    LANGUAGE_FAMILY_ALIASES,
    normalize_language_name,
    resolve_language_alias,
    resolve_language_filter,
    supported_language_filters,
)
from .extractor import parse_file
from .hierarchy import SymbolNode, build_symbol_tree, flatten_tree

__all__ = [
    "Symbol",
    "slugify",
    "make_symbol_id",
    "compute_content_hash",
    "LanguageSpec",
    "LANGUAGE_REGISTRY",
    "LANGUAGE_EXTENSIONS",
    "CANONICAL_LANGUAGES",
    "LANGUAGE_ALIASES",
    "LANGUAGE_FAMILY_ALIASES",
    "normalize_language_name",
    "resolve_language_alias",
    "resolve_language_filter",
    "supported_language_filters",
    "PYTHON_SPEC",
    "parse_file",
    "SymbolNode",
    "build_symbol_tree",
    "flatten_tree",
]
