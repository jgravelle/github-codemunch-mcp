"""Compact response encoding — the MUNCH format.

Dispatcher entry point. Given a tool name and a response dict, returns
either the original dict (JSON passthrough) or a MUNCH payload string
together with the encoding id and a savings measurement.

Usage from server.py:

    from .encoding import encode_response

    payload, meta = encode_response(tool_name, result, requested_format)
    if meta["encoding"] == "json":
        text = json.dumps(payload, separators=(",", ":"))
    else:
        text = payload

`requested_format` supports both canonical and user-facing aliases:
- canonical: "auto", "compact", "json"
- aliases: "adaptive", "encoded", "raw"
"""

from __future__ import annotations

import json
import logging
from typing import Any

from . import gate, generic
from .schemas import registry

logger = logging.getLogger(__name__)

_FORMATS = ("auto", "compact", "json")
_FORMAT_ALIASES = {
    "auto": "auto",
    "compact": "compact",
    "json": "json",
    "adaptive": "auto",
    "encoded": "compact",
    "raw": "json",
}


def _normalize_format(raw: str | None, fallback: str) -> str:
    if not isinstance(raw, str):
        return fallback
    return _FORMAT_ALIASES.get(raw.strip().lower(), fallback)


def default_format(repo: str | None = None) -> str:
    try:
        from .. import config as app_config

        configured = app_config.get("server_output", "adaptive", repo=repo)
    except Exception:
        configured = "adaptive"
    return _normalize_format(configured, "auto")


def encode_response(
    tool_name: str,
    response: Any,
    requested_format: str | None = None,
    repo: str | None = None,
) -> tuple[Any, dict]:
    """Return (payload, meta).

    payload is either the original dict (for json path) or a MUNCH string.
    meta is a dict with keys: encoding, json_bytes, encoded_bytes,
    encoding_tokens_saved.
    """
    fmt = _normalize_format(requested_format, default_format(repo=repo))

    if fmt == "json" or not isinstance(response, dict):
        return response, {"encoding": "json"}

    json_bytes = gate.json_size(response)

    try:
        encoder = registry.for_tool(tool_name)
        if encoder is not None:
            payload, enc_id = encoder.encode(tool_name, response)
        else:
            payload, enc_id = generic.encode(tool_name, response)
    except Exception:
        logger.debug("Encoder failed for %s; falling back to JSON", tool_name, exc_info=True)
        return response, {"encoding": "json", "json_bytes": json_bytes}

    encoded_bytes = len(payload)
    if fmt == "auto" and not gate.passes(json_bytes, encoded_bytes, repo=repo):
        return response, {
            "encoding": "json",
            "json_bytes": json_bytes,
            "encoded_bytes": encoded_bytes,
        }

    return payload, {
        "encoding": enc_id,
        "json_bytes": json_bytes,
        "encoded_bytes": encoded_bytes,
        "encoding_tokens_saved": max(0, (json_bytes - encoded_bytes) // 4),
    }


__all__ = ["encode_response", "default_format"]
