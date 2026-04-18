"""Encoder registry — maps tool names and encoding ids to modules."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType

logger = logging.getLogger(__name__)

_BY_TOOL: dict[str, ModuleType] = {}
_BY_ID: dict[str, ModuleType] = {}


def _discover() -> None:
    from . import __path__ as pkg_path, __name__ as pkg_name
    for mod_info in pkgutil.iter_modules(pkg_path):
        if mod_info.name in ("registry",):
            continue
        try:
            mod = importlib.import_module(f"{pkg_name}.{mod_info.name}")
        except Exception:
            logger.debug("Failed to load encoder %s", mod_info.name, exc_info=True)
            continue
        enc_id = getattr(mod, "ENCODING_ID", None)
        legacy_ids = getattr(mod, "LEGACY_ENCODING_IDS", ())
        tools = getattr(mod, "TOOLS", ())
        if not enc_id or not tools:
            continue
        _BY_ID[enc_id] = mod
        for legacy_id in legacy_ids:
            _BY_ID[legacy_id] = mod
        for t in tools:
            _BY_TOOL[t] = mod


def for_tool(tool_name: str) -> ModuleType | None:
    return _BY_TOOL.get(tool_name)


def get(encoding_id: str) -> ModuleType:
    mod = _BY_ID.get(encoding_id)
    if mod is None:
        raise KeyError(encoding_id)
    return mod


_discover()
