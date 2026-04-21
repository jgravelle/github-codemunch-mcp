"""Compact encoder for find_references."""

from .. import schema_driven as sd

TOOLS = ("find_references",)
ENCODING_ID = "fr2"

_ROWS_KEY = "__rows__"
_EMPTY_GROUPS_KEY = "__empty_groups__"

_TABLES = [
    sd.TableSpec(
        key=_ROWS_KEY,
        tag="r",
        cols=["file", "specifier", "match_type"],
        intern=["file", "specifier"],
    ),
]
_SCALARS = ("repo", "identifier", "reference_count", "note")
_META = ("timing_ms", "truncated", "tokens_saved", "total_tokens_saved")
_JSON = ("results", _EMPTY_GROUPS_KEY)


def _flatten(response: dict) -> dict:
    """Replace nested references[].matches[] with flat rows."""
    out = {k: v for k, v in response.items() if k != "references"}
    rows = []
    empty_groups: list[str] = []
    for group in response.get("references") or []:
        if not isinstance(group, dict):
            continue
        file_path = group.get("file")
        matches = group.get("matches") or []
        if not matches:
            if isinstance(file_path, str):
                empty_groups.append(file_path)
            continue
        for m in matches:
            if not isinstance(m, dict):
                continue
            rows.append(
                {
                    "file": file_path,
                    "specifier": m.get("specifier", ""),
                    "match_type": m.get("match_type", ""),
                }
            )
    out[_ROWS_KEY] = rows
    if empty_groups:
        out[_EMPTY_GROUPS_KEY] = empty_groups
    return out


def _regroup(decoded: dict) -> dict:
    """Inverse of _flatten: rebuild references list."""
    rows = decoded.pop(_ROWS_KEY, None) or []
    empty_groups = decoded.pop(_EMPTY_GROUPS_KEY, None) or []
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for file_path in empty_groups:
        if not isinstance(file_path, str):
            continue
        if file_path not in groups:
            groups[file_path] = []
            order.append(file_path)
    for row in rows:
        file_path = row.get("file")
        if not isinstance(file_path, str):
            continue
        match = {"specifier": row.get("specifier", ""), "match_type": row.get("match_type", "")}
        if file_path not in groups:
            groups[file_path] = []
            order.append(file_path)
        groups[file_path].append(match)
    decoded["references"] = [{"file": f, "matches": groups[f]} for f in order]
    return decoded


def encode(tool: str, response: dict) -> tuple[str, str]:
    if "references" not in response:
        return sd.encode(tool, response, ENCODING_ID, _TABLES, _SCALARS, meta_keys=_META, json_blobs=_JSON)
    return sd.encode(tool, _flatten(response), ENCODING_ID, _TABLES, _SCALARS, meta_keys=_META, json_blobs=_JSON)


def decode(payload: str) -> dict:
    decoded = sd.decode(payload, _TABLES, _SCALARS, meta_keys=_META, json_blobs=_JSON)
    if _ROWS_KEY in decoded:
        return _regroup(decoded)
    return decoded
