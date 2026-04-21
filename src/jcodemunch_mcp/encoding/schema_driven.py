"""Schema-driven encoder helper.

Tier-1 per-tool encoders declare a small schema and reuse the helper to
produce round-trippable MUNCH payloads. Each encoder module is ~30 lines.

Schema shape:
    SCALARS: list of top-level scalar keys to carry through
    TABLES:  list of TableSpec describing list-of-dict fields
    META:    list of _meta keys to preserve (rest of _meta is dropped unless
             passthrough=True, which copies it verbatim)

Nested single-dict fields (like call_hierarchy.symbol) are flattened with a
prefix — declare via NESTED_DICTS mapping {key: [subkeys...]}.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .format import (
    Legends,
    assemble,
    parse_header,
    parse_scalars,
    read_table,
    split_sections,
    write_header,
    write_scalars,
    write_table,
)


@dataclass
class TableSpec:
    key: str                       # response dict key holding list[dict]
    tag: str                       # 1-char table tag
    cols: list[str] = field(default_factory=list)  # column order
    intern: list[str] = field(default_factory=list)  # cols to legend-intern
    types: dict[str, str] = field(default_factory=dict)  # col -> type hint


def _type_of(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    return "str"


def _coerce(raw: str, hint: str) -> Any:
    if raw == "":
        return None
    if hint == "bool":
        return raw == "T"
    if hint == "int":
        try:
            return int(raw)
        except ValueError:
            return raw
    if hint == "float":
        try:
            return float(raw)
        except ValueError:
            return raw
    return raw


def encode(
    tool: str,
    response: dict,
    encoding_id: str,
    tables: Iterable[TableSpec] = (),
    scalars: Iterable[str] = (),
    nested_dicts: dict[str, list[str]] | None = None,
    meta_keys: Iterable[str] = (),
    json_blobs: Iterable[str] = (),
) -> tuple[str, str]:
    tables = list(tables)
    nested_dicts = nested_dicts or {}

    # Build shared path/symbol legend across all string-interned columns.
    legend = Legends(prefix="@")
    for t in tables:
        rows = response.get(t.key, []) or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            for c in t.intern:
                v = row.get(c)
                if isinstance(v, str):
                    legend.observe(v)
    legend.finalize(min_uses=2, min_chars_saved=1)

    # Scalar section
    scalar_payload: dict[str, Any] = {}
    for k in scalars:
        if k in response:
            scalar_payload[k] = response[k]
    for key, subkeys in nested_dicts.items():
        sub = response.get(key) or {}
        if isinstance(sub, dict):
            for sk in subkeys:
                if sk in sub:
                    scalar_payload[f"{key}.{sk}"] = sub[sk]
    meta = response.get("_meta") or {}
    for k in meta_keys:
        if k in meta:
            scalar_payload[f"_meta.{k}"] = meta[k]
    for k in json_blobs:
        if k in response:
            scalar_payload[f"__json.{k}"] = json.dumps(response[k], separators=(",", ":"))
    scalar_types_out: dict[str, str] = {}
    for k, v in scalar_payload.items():
        if k.startswith("__"):
            continue
        if v is not None and not isinstance(v, str):
            scalar_types_out[k] = _type_of(v)
    if scalar_types_out:
        scalar_payload["__stypes"] = "|".join(f"{k}:{t}" for k, t in scalar_types_out.items())
    # Encode the table schema into the payload so decode is self-sufficient.
    scalar_payload["__tables"] = ",".join(
        f"{t.tag}:{t.key}:{'|'.join(t.cols)}" for t in tables
    )

    sections: list[str] = []
    leg_text = legend.write()
    if leg_text:
        sections.append(leg_text)
    sections.append(write_scalars(scalar_payload))

    for t in tables:
        rows = response.get(t.key, []) or []
        out_rows: list[list[Any]] = []
        intern_set = set(t.intern)
        for row in rows:
            if not isinstance(row, dict):
                continue
            encoded_row: list[Any] = []
            for c in t.cols:
                v = row.get(c)
                if c in intern_set and isinstance(v, str):
                    v = legend.encode_prefix(v)
                encoded_row.append(v)
            out_rows.append(encoded_row)
        sections.append(write_table(t.tag, out_rows))

    header = write_header(tool, encoding_id)
    return assemble(header, *sections), encoding_id


def decode(
    payload: str,
    tables: Iterable[TableSpec] = (),
    scalars: Iterable[str] = (),
    nested_dicts: dict[str, list[str]] | None = None,
    meta_keys: Iterable[str] = (),
    json_blobs: Iterable[str] = (),
    scalar_types: Mapping[str, str] | None = None,
) -> dict:
    tables = list(tables)
    nested_dicts = nested_dicts or {}
    scalar_set = set(scalars)
    stypes: dict[str, str] = dict(scalar_types or {})

    head, blocks = split_sections(payload)
    parse_header(head)

    legend = Legends(prefix="@")
    scalar_block: str | None = None
    table_block_text: list[str] = []
    for b in blocks:
        if b.startswith("@") and "=" in b.splitlines()[0]:
            legend = Legends.read(b, prefix="@")
        elif scalar_block is None and "=" in b.splitlines()[0]:
            scalar_block = b
        else:
            table_block_text.append(b)

    raw_scalars = parse_scalars(scalar_block) if scalar_block else {}
    raw_scalars.pop("__tables", None)
    stypes_text = raw_scalars.pop("__stypes", "")
    for part in [p for p in stypes_text.split("|") if p]:
        name, _, hint = part.partition(":")
        if name and hint and name not in stypes:
            stypes[name] = hint

    result: dict[str, Any] = {}
    # Top-level scalars — coerce per scalar_types hint when supplied,
    # otherwise fall through as raw string (back-compat for schemas that
    # don't declare types).
    for k, v in list(raw_scalars.items()):
        if k in scalar_set:
            result[k] = _coerce(v, stypes.get(k, "str"))
    # Nested dicts
    for key, subkeys in nested_dicts.items():
        sub: dict[str, Any] = {}
        for sk in subkeys:
            prefixed = f"{key}.{sk}"
            if prefixed in raw_scalars:
                sub[sk] = _coerce(raw_scalars[prefixed], stypes.get(prefixed, "str"))
        if sub:
            result[key] = sub
    # Meta
    meta_out: dict[str, Any] = {}
    for k in meta_keys:
        prefixed = f"_meta.{k}"
        if prefixed in raw_scalars:
            meta_out[k] = _coerce(raw_scalars[prefixed], stypes.get(prefixed, "str"))
    if meta_out:
        result["_meta"] = meta_out
    # JSON blobs
    for k in json_blobs:
        prefixed = f"__json.{k}"
        if prefixed in raw_scalars:
            try:
                result[k] = json.loads(raw_scalars[prefixed])
            except Exception:
                result[k] = raw_scalars[prefixed]

    # Tables
    for t in tables:
        decoded_rows: list[dict[str, Any]] = []
        intern_set = set(t.intern)
        for block in table_block_text:
            rows = read_table(block, t.tag)
            if not rows:
                continue
            for r in rows:
                row_dict: dict[str, Any] = {}
                for i, c in enumerate(t.cols):
                    raw = r[i] if i < len(r) else ""
                    if c in intern_set and isinstance(raw, str):
                        raw = legend.decode_prefix(raw)
                    row_dict[c] = _coerce(raw, t.types.get(c, "str"))
                decoded_rows.append(row_dict)
        result[t.key] = decoded_rows

    return result
