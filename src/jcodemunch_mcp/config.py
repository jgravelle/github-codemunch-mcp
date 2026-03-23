"""Centralized JSONC config for jcodemunch-mcp."""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global config storage
_GLOBAL_CONFIG: dict[str, Any] = {}
_PROJECT_CONFIGS: dict[str, dict[str, Any]] = {}  # repo -> merged config
_DEPRECATED_ENV_VARS_LOGGED: set[str] = set()  # Track warned vars

ENV_VAR_MAPPING = {
    "JCODEMUNCH_USE_AI_SUMMARIES": "use_ai_summaries",
    "JCODEMUNCH_MAX_FOLDER_FILES": "max_folder_files",
    "JCODEMUNCH_MAX_INDEX_FILES": "max_index_files",
    "JCODEMUNCH_STALENESS_DAYS": "staleness_days",
    "JCODEMUNCH_MAX_RESULTS": "max_results",
    "JCODEMUNCH_EXTRA_IGNORE_PATTERNS": "extra_ignore_patterns",
    "JCODEMUNCH_EXTRA_EXTENSIONS": "extra_extensions",
    "JCODEMUNCH_CONTEXT_PROVIDERS": "context_providers",
    "JCODEMUNCH_REDACT_SOURCE_ROOT": "redact_source_root",
    "JCODEMUNCH_STATS_FILE_INTERVAL": "stats_file_interval",
    "JCODEMUNCH_SHARE_SAVINGS": "share_savings",
    "JCODEMUNCH_SUMMARIZER_CONCURRENCY": "summarizer_concurrency",
    "JCODEMUNCH_ALLOW_REMOTE_SUMMARIZER": "allow_remote_summarizer",
    "JCODEMUNCH_RATE_LIMIT": "rate_limit",
    "JCODEMUNCH_TRANSPORT": "transport",
    "JCODEMUNCH_HOST": "host",
    "JCODEMUNCH_PORT": "port",
    "JCODEMUNCH_WATCH": "watch",
    "JCODEMUNCH_WATCH_DEBOUNCE_MS": "watch_debounce_ms",
    "JCODEMUNCH_FRESHNESS_MODE": "freshness_mode",
    "JCODEMUNCH_CLAUDE_POLL_INTERVAL": "claude_poll_interval",
    "JCODEMUNCH_LOG_LEVEL": "log_level",
    "JCODEMUNCH_LOG_FILE": "log_file",
}

DEFAULTS = {
    "use_ai_summaries": True,
    "max_folder_files": 2000,
    "max_index_files": 10000,
    "staleness_days": 7,
    "max_results": 500,
    "extra_ignore_patterns": [],
    "extra_extensions": {},
    "context_providers": True,
    "meta_fields": None,  # None = all fields
    "languages": None,  # None = all languages
    "disabled_tools": [],
    "descriptions": {},
    "transport": "stdio",
    "host": "127.0.0.1",
    "port": 8901,
    "rate_limit": 0,
    "watch": False,
    "watch_debounce_ms": 2000,
    "freshness_mode": "relaxed",
    "claude_poll_interval": 5.0,
    "log_level": "WARNING",
    "log_file": None,
    "redact_source_root": False,
    "stats_file_interval": 3,
    "share_savings": True,
    "summarizer_concurrency": 4,
    "allow_remote_summarizer": False,
}

CONFIG_TYPES = {
    "use_ai_summaries": bool,
    "max_folder_files": int,
    "max_index_files": int,
    "staleness_days": int,
    "max_results": int,
    "extra_ignore_patterns": list,
    "extra_extensions": dict,
    "context_providers": bool,
    "meta_fields": (list, type(None)),
    "languages": (list, type(None)),
    "disabled_tools": list,
    "descriptions": dict,
    "transport": str,
    "host": str,
    "port": int,
    "rate_limit": int,
    "watch": bool,
    "watch_debounce_ms": int,
    "freshness_mode": str,
    "claude_poll_interval": float,
    "log_level": str,
    "log_file": (str, type(None)),
    "redact_source_root": bool,
    "stats_file_interval": int,
    "share_savings": bool,
    "summarizer_concurrency": int,
    "allow_remote_summarizer": bool,
}


def _strip_jsonc(text: str) -> str:
    """Strip // and /* */ comments from JSONC, respecting quoted strings."""
    result, i, n = [], 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            result.append(ch)
            if ch == '\\' and i + 1 < n:
                result.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
        elif ch == '"':
            in_str = True
            result.append(ch)
            i += 1
        elif ch == '/' and i + 1 < n and text[i + 1] == '/':
            # Line comment — strip trailing comma and spaces from previous content
            if result and result[-1] == ',':
                result.pop()
                while result and result[-1] in (' ', '\t'):
                    result.pop()
            end = text.find('\n', i)
            i = n if end == -1 else end
        elif ch == '/' and i + 1 < n and text[i + 1] == '*':
            # Block comment — skip to */
            end = text.find('*/', i + 2)
            if end == -1:
                i = n
            else:
                end_i = end + 2
                if end_i < n and text[end_i] == ',':
                    # Comma immediately after */ — strip it
                    i = end_i + 1
                elif end_i < n and text[end_i] == '\n':
                    # Newline after */ — strip trailing comma only
                    # Walk back to find the last non-whitespace character
                    j = len(result) - 1
                    while j >= 0 and result[j] in (' ', '\t'):
                        j -= 1
                    if j >= 0 and result[j] == ',':
                        result.pop()  # pop comma only
                    i = end_i
                else:
                    i = end_i
        else:
            result.append(ch)
            i += 1
    return ''.join(result)


def _validate_type(key: str, value: Any, expected_type: type | tuple) -> bool:
    """Validate value against expected type."""
    if isinstance(expected_type, tuple):
        return isinstance(value, expected_type)
    return isinstance(value, expected_type)


def load_config(storage_path: str | None = None) -> None:
    """Load global config.jsonc. Called once from main()."""
    global _GLOBAL_CONFIG

    # Determine config path
    if storage_path:
        config_path = Path(storage_path) / "config.jsonc"
    else:
        config_path = Path.home() / ".code-index" / "config.jsonc"

    # Load config if exists
    if config_path.exists():
        try:
            content = config_path.read_text(encoding="utf-8")
            stripped = _strip_jsonc(content)
            loaded = json.loads(stripped)

            # Type validation
            for key, value in loaded.items():
                if key in CONFIG_TYPES:
                    if _validate_type(key, value, CONFIG_TYPES[key]):
                        _GLOBAL_CONFIG[key] = value
                    else:
                        logger.warning(
                            f"Config key '{key}' has invalid type. "
                            f"Expected {CONFIG_TYPES[key]}, got {type(value).__name__}. Using default."
                        )
                        _GLOBAL_CONFIG[key] = DEFAULTS.get(key)
                # Ignore unknown keys silently
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse config.jsonc: {e}")
            _GLOBAL_CONFIG = DEFAULTS.copy()
        except Exception as e:
            logger.error(f"Failed to load config.jsonc: {e}")
            _GLOBAL_CONFIG = DEFAULTS.copy()
    else:
        _GLOBAL_CONFIG = DEFAULTS.copy()

    # Apply env var fallback for keys not set in config
    _apply_env_var_fallback()


def _parse_env_value(value: str, expected_type: type | tuple) -> Any:
    """Parse env var string to expected type."""
    try:
        if expected_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif expected_type == int:
            return int(value)
        elif expected_type == float:
            return float(value)
        elif expected_type == str:
            return value
        elif expected_type == list:
            return json.loads(value)
        elif expected_type == dict:
            return json.loads(value)
    except (ValueError, json.JSONDecodeError):
        logger.warning(f"Failed to parse env var value: {value}")
        return None
    return value


def _apply_env_var_fallback() -> None:
    """Apply deprecated env var fallback for keys not in config."""
    global _GLOBAL_CONFIG

    for env_var, config_key in ENV_VAR_MAPPING.items():
        # Skip if config key already set
        if config_key in _GLOBAL_CONFIG:
            continue

        env_value = os.environ.get(env_var)
        if env_value is not None:
            # Log warning once per var
            if env_var not in _DEPRECATED_ENV_VARS_LOGGED:
                logger.warning(
                    f"Deprecated: Using {env_var} environment variable. "
                    f"This will be removed in v2.0. Use config.jsonc instead."
                )
                _DEPRECATED_ENV_VARS_LOGGED.add(env_var)

            # Parse and apply value
            expected_type = CONFIG_TYPES.get(config_key)
            if expected_type is None:
                continue
            parsed = _parse_env_value(env_value, expected_type)  # type: ignore[arg-type]
            if parsed is not None:
                _GLOBAL_CONFIG[config_key] = parsed


def get(key: str, default: Any = None, repo: str | None = None) -> Any:
    """Get config value. If repo is given, uses merged project config."""
    if repo and repo in _PROJECT_CONFIGS:
        return _PROJECT_CONFIGS[repo].get(key, default)
    return _GLOBAL_CONFIG.get(key, default)


def load_project_config(source_root: str) -> None:
    """Load and cache .jcodemunch.jsonc for a project. Called on first index."""
    project_config_path = Path(source_root) / ".jcodemunch.jsonc"
    repo_key = str(Path(source_root).resolve())

    if project_config_path.exists():
        try:
            content = project_config_path.read_text(encoding="utf-8")
            stripped = _strip_jsonc(content)
            project_config = json.loads(stripped)

            # Merge over global
            merged = {**_GLOBAL_CONFIG}
            for key, value in project_config.items():
                if key in CONFIG_TYPES:
                    if _validate_type(key, value, CONFIG_TYPES[key]):
                        merged[key] = value
                    else:
                        logger.warning(
                            f"Project config key '{key}' has invalid type. Using global default."
                        )
            _PROJECT_CONFIGS[repo_key] = merged
        except Exception as e:
            logger.warning(f"Failed to load project config: {e}")
            _PROJECT_CONFIGS[repo_key] = _GLOBAL_CONFIG.copy()
    else:
        _PROJECT_CONFIGS[repo_key] = _GLOBAL_CONFIG.copy()


def is_tool_disabled(tool_name: str, repo: str | None = None) -> bool:
    """Check if a tool is in disabled_tools."""
    disabled = get("disabled_tools", [], repo=repo)
    return tool_name in disabled


def is_language_enabled(language: str, repo: str | None = None) -> bool:
    """Check if a language is in the languages list."""
    languages = get("languages", None, repo=repo)
    if languages is None:  # None = all enabled
        return True
    return language in languages


def get_descriptions() -> dict:
    """Get the nested descriptions dict."""
    return _GLOBAL_CONFIG.get("descriptions", {})


# Lazy import to avoid circular dependency
def generate_template() -> str:
    """Return default config.jsonc content."""
    from .parser.languages import LANGUAGE_REGISTRY

    languages_list = list(LANGUAGE_REGISTRY.keys())
    lang_str = ", ".join(f'"{lang}"' for lang in languages_list)

    return f'''// jcodemunch-mcp configuration
// Global: ~/.code-index/config.jsonc
// Project: {{project_root}}/.jcodemunch.jsonc (optional, overrides global)
//
// All values below show defaults. Uncomment to override.
// Env vars still work as fallback but are deprecated.
{{
  // === Indexing ===
  "use_ai_summaries": true,
  "max_folder_files": 2000,
  "max_index_files": 10000,
  "staleness_days": 7,
  "max_results": 500,
  "extra_ignore_patterns": [],
  "extra_extensions": {{}},
  "context_providers": true,

  // === Meta Response Control ===
  "meta_fields": null,

  // === Languages ===
  "languages": [{lang_str}],

  // === Disabled Tools ===
  "disabled_tools": [],

  // === Descriptions ===
  "descriptions": {{}},

  // === Transport ===
  "transport": "stdio",
  "host": "127.0.0.1",
  "port": 8901,
  "rate_limit": 0,

  // === Watcher ===
  "watch": false,
  "watch_debounce_ms": 2000,
  "freshness_mode": "relaxed",
  "claude_poll_interval": 5.0,

  // === Logging ===
  "log_level": "WARNING",
  "log_file": null,

  // === Privacy & Telemetry ===
  "redact_source_root": false,
  "stats_file_interval": 3,
  "share_savings": true,
  "summarizer_concurrency": 4,
  "allow_remote_summarizer": false
}}
'''
