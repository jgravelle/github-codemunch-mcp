"""Compact encoder for find_importers."""

from .. import schema_driven as sd

TOOLS = ("find_importers",)
ENCODING_ID = "fi2"

_TABLES = [
    sd.TableSpec(
        key="importers",
        tag="i",
        cols=["file", "specifier", "has_importers"],
        intern=["file", "specifier"],
        types={"has_importers": "bool"},
    ),
]
_SCALARS = ("repo", "file_path", "importer_count", "note")
_META = ("timing_ms", "truncated", "tokens_saved", "total_tokens_saved")
_JSON = ("results",)


def encode(tool: str, response: dict) -> tuple[str, str]:
    return sd.encode(tool, response, ENCODING_ID, _TABLES, _SCALARS, meta_keys=_META, json_blobs=_JSON)


def decode(payload: str) -> dict:
    return sd.decode(payload, _TABLES, _SCALARS, meta_keys=_META, json_blobs=_JSON)
