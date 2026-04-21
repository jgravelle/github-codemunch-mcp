"""Compact encoder for get_dependency_cycles."""

from .. import schema_driven as sd

TOOLS = ("get_dependency_cycles",)
ENCODING_ID = "dc2"

_CYCLE_SEP = "\x1f"

_TABLES = [
    sd.TableSpec(
        key="cycles",
        tag="y",
        cols=["length", "files"],
        types={"length": "int"},
    ),
]
_SCALARS = ("repo", "cycle_count")
_META = ("timing_ms",)


def encode(tool: str, response: dict) -> tuple[str, str]:
    r = dict(response)
    if "cycles" in r and isinstance(r["cycles"], list):
        r["cycles"] = [
            {"length": len(c), "files": _CYCLE_SEP.join(c)}
            for c in r["cycles"] if isinstance(c, list)
        ]
    return sd.encode(tool, r, ENCODING_ID, _TABLES, _SCALARS, meta_keys=_META)


def decode(payload: str) -> dict:
    result = sd.decode(payload, _TABLES, _SCALARS, meta_keys=_META)
    if "cycles" in result:
        result["cycles"] = [
            c["files"].split(_CYCLE_SEP) for c in result["cycles"]
            if isinstance(c, dict) and "files" in c
        ]
    return result
