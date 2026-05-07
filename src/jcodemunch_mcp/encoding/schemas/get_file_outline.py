"""Compact encoder for get_file_outline."""

from .. import schema_driven as sd

TOOLS = ("get_file_outline",)
ENCODING_ID = "fo1"

_TABLES = [
    sd.TableSpec(
        key="symbols",
        tag="s",
        cols=["id", "name", "kind", "signature", "line", "end_line", "parent", "summary"],
        intern=["id", "parent"],
        types={"line": "int", "end_line": "int"},
    ),
    sd.TableSpec(
        key="results",
        tag="b",
        cols=["file", "symbol_count"],
        intern=["file"],
        types={"symbol_count": "int"},
    ),
]
_SCALARS = ("repo", "file", "symbol_count", "language")
_META = ("timing_ms", "tokens_saved", "total_tokens_saved")


def encode(tool: str, response: dict) -> tuple[str, str]:
    return sd.encode(tool, response, ENCODING_ID, _TABLES, _SCALARS, meta_keys=_META)


def decode(payload: str) -> dict:
    return sd.decode(payload, _TABLES, _SCALARS, meta_keys=_META)
