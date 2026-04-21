"""Savings gate — decide whether to emit compact or JSON.

Cheap pre-check runs before full encoding. Full check compares actual
byte sizes. Threshold is configurable via env/config; default 15%.
"""

from __future__ import annotations

import json

DEFAULT_THRESHOLD = 0.15


def threshold(repo: str | None = None) -> float:
    try:
        from .. import config as app_config

        raw = app_config.get("server_output_threshold", DEFAULT_THRESHOLD, repo=repo)
    except Exception:
        raw = DEFAULT_THRESHOLD

    if raw is not None:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_THRESHOLD


def json_size(response: dict) -> int:
    return len(json.dumps(response, separators=(",", ":")))


def savings_ratio(json_bytes: int, compact_bytes: int) -> float:
    if json_bytes <= 0:
        return 0.0
    return max(0.0, (json_bytes - compact_bytes) / json_bytes)


def passes(json_bytes: int, compact_bytes: int, repo: str | None = None) -> bool:
    return savings_ratio(json_bytes, compact_bytes) >= threshold(repo=repo)
